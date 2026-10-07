"""
File and folder names, in the template language Radarr and Sonarr use.

Riparr's original templates were `{Title} ({Year})` and a few episode fields. This
reads those exactly as before, and also Radarr's syntax, so the naming schemes people
already use -- TRaSH Guides' above all -- can be pasted in unchanged:

    {Movie CleanTitle}          a token
    {(Release Year)}            text inside the braces wraps the value, and the whole
    {[Quality Full]}            thing disappears when the value is empty
    {-Release Group}
    {[Mediainfo AudioCodec}{ Mediainfo AudioChannels]}   a wrapper split across two
    {imdb-{ImdbId}}             nested: the outer braces are literal output, as Plex
    {edition-{Edition Tags}}    wants them -- "{imdb-tt0066921}" -- or nothing at all
    {{Edition Tags}}            the same, with no prefix: "{Director's Cut}"
    {Season:00} {Episode:00}    zero padding, as before

A group that names no token Riparr knows is left exactly as written, so a typo shows
up in the file name instead of silently vanishing.

The media fields come from MakeMKV's description of the title that was ripped:
`media_info()` turns its stream list into the values Radarr would show.
"""
import re

# ─────────────────────────────── values ───────────────────────────────

_ILLEGAL = re.compile(r'[<>"|?*\x00-\x1f]')
_SEPARATORS = re.compile(r'[/\\:]')


def sanitise(name):
    """Safe as one path segment on every filesystem a share might be.

    SMB and NTFS refuse some characters outright. A film called "Mission: Impossible"
    is not an edge case, and a rip that succeeds for forty minutes and then cannot be
    written because of a colon is the worst possible place to discover that.
    """
    # Separators become spaces rather than vanishing: "Face/Off" should read as
    # "Face Off", not "FaceOff". Everything else is simply dropped.
    s = _SEPARATORS.sub(" ", name or "")
    s = _ILLEGAL.sub("", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    # Windows also refuses a name ending in a dot or a space, silently, at the server.
    return s.rstrip(". ") or "Untitled"


# What a disc family is called in a filename, as {Source}.
SOURCE_TAG = {"dvd": "DVD", "bluray": "Bluray", "uhd": "UHD"}

# Every token, by its normalised name (lower case, single spaces, "MediaInfo" in one
# spelling). Several names for one value, because Radarr, Sonarr and Riparr each call
# the same thing something different.
ALIASES = {
    "title": "title", "movie title": "title", "movie cleantitle": "title",
    "series title": "title", "series cleantitle": "title",
    "year": "year", "release year": "year",
    "source": "source",
    "episodetitle": "episode_title", "episode title": "episode_title",
    "episode cleantitle": "episode_title",
    "quality full": "quality", "quality title": "quality",
    "mediainfo videocodec": "video_codec",
    "mediainfo audiocodec": "audio_codec",
    "mediainfo audiochannels": "audio_channels",
    "mediainfo videodynamicrangetype": "dynamic_range",
    "mediainfo videodynamicrange": "dynamic_range",
    "mediainfo 3d": "three_d",
    "mediainfo audiolanguages": "audio_languages",
    "mediainfo videobitdepth": "bit_depth",
    "edition tags": "edition",
    "custom formats": "custom_formats",
    "release group": "release_group",
    "imdbid": "imdb_id", "tmdbid": "tmdb_id", "tvdbid": "tvdb_id",
}
PADDED = {"season": "season", "episode": "episode"}

# The documented list, for the settings page. Radarr tokens a rip can't fill --
# {Edition Tags}, {Custom Formats}, {Release Group} -- and the unreliable {MediaInfo 3D}
# and {MediaInfo VideoDynamicRangeType} are still understood, so a pasted TRaSH template
# renders cleanly, but aren't offered.
TOKENS = ["{Title}", "{Year}", "{Source}", "{Season:00}", "{Episode:00}",
          "{EpisodeTitle}", "{Movie CleanTitle}", "{Release Year}", "{Quality Full}",
          "{MediaInfo VideoCodec}", "{MediaInfo AudioCodec}",
          "{MediaInfo AudioChannels}", "{MediaInfo AudioLanguages}",
          "{MediaInfo VideoBitDepth}", "{ImdbId}", "{TmdbId}", "{TvdbId}"]


def _norm(text):
    t = re.sub(r"\s+", " ", text.strip().lower())
    return t


# The longest names first, so "Movie CleanTitle" is found before "Title" is.
_NAMES = sorted(set(ALIASES) | set(PADDED), key=len, reverse=True)
_NAME_RE = re.compile(
    r"(?P<name>%s)(?::(?P<pad>0+))?" % "|".join(
        re.escape(n).replace(r"\ ", r"\s+") for n in _NAMES),
    re.I)


def _find_token(content):
    """(start, end, key, pad) of the token inside a {group}, or None."""
    norm_content = content.replace("Mediainfo", "MediaInfo")
    for m in _NAME_RE.finditer(norm_content):
        name = _norm(m.group("name"))
        key = ALIASES.get(name) or PADDED.get(name)
        if key:
            return m.start(), m.end(), key, m.group("pad")
    return None


def _value(key, pad, values, episode_last=None):
    if key in ("season", "episode"):
        v = values.get(key)
        if v is None:
            return None                     # not ours to fill: leave it visible
        width = len(pad or "") or 1
        out = "%0*d" % (width, int(v))
        # A two-episode file: E{Episode:00} becomes E01-E02, which Plex and Jellyfin
        # both read as one file holding two episodes.
        if key == "episode" and episode_last and int(episode_last) > int(v):
            out += "-E%0*d" % (width, int(episode_last))
        return out
    return values.get(key) or ""


_GROUP = re.compile(r"\{([^{}]*)\}")
_NESTED = re.compile(r"\{([^{}]*)\{([^{}]*)\}([^{}]*)\}")


def render(template, values, episode_last=None):
    """Fill a template. `values` is keyed by the names in ALIASES/PADDED's values."""
    out = []
    pos = 0
    text = template or ""
    # Nested groups first: {imdb-{ImdbId}}, {edition-{Edition Tags}}, {{Edition Tags}}.
    # Their outer braces are output, and the whole group goes when the value is empty.
    def nested(m):
        prefix, inner, suffix = m.group(1), m.group(2), m.group(3)
        found = _find_token(inner)
        if not found:
            return m.group(0)
        s, e, key, pad = found
        v = _value(key, pad, values, episode_last)
        if v is None:
            return m.group(0)
        if not v:
            return ""
        return "{" + prefix + inner[:s] + v + inner[e:] + suffix + "}"
    text = _NESTED.sub(nested, text)

    for m in _GROUP.finditer(text):
        out.append(text[pos:m.start()])
        content = m.group(1)
        found = _find_token(content)
        if not found:
            out.append(m.group(0))          # unknown: leave it as written
        else:
            s, e, key, pad = found
            v = _value(key, pad, values, episode_last)
            if v is None:
                out.append(m.group(0))
            elif v:
                out.append(content[:s] + v + content[e:])
        pos = m.end()
    out.append(text[pos:])
    return _tidy("".join(out))


def _tidy(out):
    # Old-style templates write the wrapper outside the braces -- "({Year})" -- so an
    # empty value leaves the wrapper behind. Radarr-style ones don't need any of this.
    out = re.sub(r"\s*\(\)\s*", " ", out)
    out = re.sub(r"\s*\[\]\s*", " ", out)
    # An ID token that came out empty inside literal brackets: "[imdbid-]".
    out = re.sub(r"\s*\[[A-Za-z]+-\]", "", out)
    out = re.sub(r"\s+-\s+(\.[A-Za-z0-9]+)$", r"\1", out)    # "Film - .mkv"
    out = re.sub(r"\s+-\s+(?=\[)", " ", out)                  # no edition: "(2010) - [Remux"
    out = re.sub(r"\s+-\s*(?=/|$)", "", out)                   # "Film -/" and "Film -"
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\s+(\.[A-Za-z0-9]+)$", r"\1", out)          # a space before .mkv
    segments = []
    parts = out.split("/")
    for i, seg in enumerate(parts):
        seg = seg.strip()
        if not seg:
            continue
        # Only the leaf keeps its extension; a trailing dot on a directory is invalid.
        segments.append(seg if i == len(parts) - 1 else seg.rstrip(". "))
    return "/".join(segments)


def values_for(title, year=None, source=None, season=None, episode=None,
               episode_title=None, media=None):
    """The values `render` fills from, for one file."""
    v = {"title": sanitise(title), "year": str(year) if year else "",
         "source": SOURCE_TAG.get(source or "", ""),
         "episode_title": sanitise(episode_title) if episode_title else "",
         "season": season, "episode": episode}
    for k, val in (media or {}).items():
        v.setdefault(k, sanitise(val) if val else "")
    return v


# ─────────────────────────────── media info ───────────────────────────────
#
# MakeMKV describes every stream in a title with SINFO lines; read_titles() keeps them
# as `streams`. Attribute IDs are from MakeMKV's own apdefs.h.
#
# The codec names below are matched loosely, by substring, because the exact strings
# MakeMKV prints vary by disc and version and haven't all been checked against real
# discs. Anything not recognised comes through as MakeMKV's own short name.

SINFO_FIELDS = {1: "type", 2: "name", 3: "lang", 5: "codec_id", 6: "codec_short",
                7: "codec_long", 14: "channels", 19: "video_size", 22: "flags",
                40: "layout", 41: "output_codec"}

FLAG_CORE_AUDIO = 256
FLAG_DERIVED = 2048

_VIDEO = [("hevc", "HEVC"), ("mpegh", "HEVC"), ("h265", "HEVC"), ("h.265", "HEVC"),
          ("avc", "AVC"), ("mpeg4", "AVC"), ("h264", "AVC"), ("h.264", "AVC"),
          ("vc-1", "VC1"), ("vc1", "VC1"), ("mpeg2", "MPEG2"), ("mpeg-2", "MPEG2")]
_AUDIO = [("truehd", "TrueHD"), ("dts:x", "DTS-X"), ("dts-x", "DTS-X"),
          ("dtsx", "DTS-X"), ("dts-hd ma", "DTS-HD MA"), ("dts-hd master", "DTS-HD MA"),
          ("dts-hd hr", "DTS-HD HRA"), ("dts-hd hi", "DTS-HD HRA"), ("dts-es", "DTS-ES"),
          ("dts", "DTS"), ("e-ac3", "EAC3"), ("eac3", "EAC3"), ("dd+", "EAC3"),
          ("ac3", "AC3"), ("dolby digital", "AC3"), ("lpcm", "PCM"), ("pcm", "PCM"),
          ("flac", "FLAC"), ("aac", "AAC"), ("mp2", "MP2"), ("mpeg audio", "MP2")]
_LAYOUTS = {"mono": "1.0", "stereo": "2.0"}
_CHANNELS = {1: "1.0", 2: "2.0", 3: "2.1", 6: "5.1", 7: "6.1", 8: "7.1"}
# ISO 639-2 -> the two letters Radarr shows.
_LANG2 = {"eng": "EN", "deu": "DE", "ger": "DE", "fra": "FR", "fre": "FR", "spa": "ES",
          "ita": "IT", "jpn": "JA", "kor": "KO", "zho": "ZH", "chi": "ZH", "por": "PT",
          "rus": "RU", "nld": "NL", "dut": "NL", "swe": "SV", "dan": "DA", "nor": "NO",
          "fin": "FI", "pol": "PL", "ces": "CS", "cze": "CS", "hun": "HU", "tur": "TR",
          "ell": "EL", "gre": "EL", "heb": "HE", "ara": "AR", "hin": "HI", "tha": "TH"}


def _match(text, table):
    t = (text or "").lower()
    for needle, name in table:
        if needle in t:
            return name
    return None


def _height(size):
    m = re.match(r"\s*(\d+)\s*x\s*(\d+)", size or "")
    return int(m.group(2)) if m else 0


def quality(family, height, backup=False):
    """Radarr's quality name for a rip: Remux-1080p, Remux-2160p, DVD, BR-DISK..."""
    if backup:
        return "DVD-R" if family == "dvd" else "BR-DISK" if family else ""
    if family == "dvd":
        return "DVD"
    if family in ("bluray", "uhd"):
        res = ("2160p" if height >= 1800 else "1080p" if height >= 900
               else "720p" if height >= 650 else "576p" if height >= 560 else "480p")
        return "Remux-%s" % res
    return ""


def media_info(title, family=None, backup=False):
    """The media tokens for one MakeMKV title: {"video_codec": "HEVC", ...}."""
    streams = (title or {}).get("streams") or []
    video = [s for s in streams if (s.get("type") or "").lower().startswith("video")]
    audio = [s for s in streams if (s.get("type") or "").lower().startswith("audio")
             and not (int(s.get("flags") or 0) & (FLAG_CORE_AUDIO | FLAG_DERIVED))]
    out = {}

    main = video[0] if video else {}
    vtext = " ".join(str(main.get(k) or "") for k in ("codec_short", "codec_long", "codec_id"))
    out["video_codec"] = _match(vtext, _VIDEO) or (main.get("codec_short") or "")
    out["bit_depth"] = ("10" if re.search(r"main\s*10|10[- ]?bit", vtext, re.I)
                        else "8" if main else "")
    height = _height(main.get("video_size"))
    out["quality"] = quality(family, height, backup)

    everything = " ".join(" ".join(str(v) for v in s.values()) for s in video).lower()
    # Dolby Vision arrives as a second video stream (the enhancement layer) or is named
    # outright. There is no HDR attribute at all, so HDR10 is only claimed when MakeMKV
    # says so in a description -- never inferred from "it's a 4K disc".
    dv = "dolby vision" in everything or len([s for s in video
                                              if "mvc" not in str(s).lower()]) > 1
    hdr = ("HDR10Plus" if "hdr10+" in everything or "hdr10plus" in everything
           else "HDR10" if "hdr10" in everything or "hdr" in everything else "")
    out["dynamic_range"] = " ".join(x for x in ("DV" if dv else "", hdr) if x)
    out["three_d"] = "3D" if "mvc" in everything else ""

    first = audio[0] if audio else {}
    atext = " ".join(str(first.get(k) or "") for k in
                     ("output_codec", "codec_short", "codec_long", "name"))
    codec = _match(atext, _AUDIO) or (first.get("codec_short") or "")
    if codec in ("TrueHD", "EAC3") and "atmos" in atext.lower():
        codec += " Atmos"
    out["audio_codec"] = codec
    layout = (first.get("layout") or "").strip().lower()
    try:
        n = int(first.get("channels") or 0)
    except ValueError:
        n = 0
    out["audio_channels"] = (_LAYOUTS.get(layout)
                             or (layout if re.match(r"^\d\.\d$", layout) else "")
                             or _CHANNELS.get(n, ""))

    langs = []
    for s in audio:
        code = _LANG2.get((s.get("lang") or "").lower(), (s.get("lang") or "")[:2].upper())
        if code and code != "EN" and code not in langs:
            langs.append(code)
    out["audio_languages"] = "[%s]" % "+".join(langs) if langs else ""
    return out


# ─────────────────────────────── presets ───────────────────────────────
#
# Based on TRaSH Guides' recommended Radarr naming (TMDb variants), as one Riparr
# template each, folder/file:
# https://trash-guides.info/Radarr/Radarr-recommended-naming-scheme/
#
# Trimmed to what a disc rip can actually fill. TRaSH's {Edition Tags}, {Custom
# Formats}, {Release Group}, {MediaInfo 3D} and {MediaInfo VideoDynamicRangeType} are
# left out: the first three have no source for a rip at all, and the last two are blank
# or incomplete on most discs. They still render cleanly if pasted in.

_MEDIA = ("{[Quality Full]}{[Mediainfo AudioCodec}{ Mediainfo AudioChannels]}"
          "{[Mediainfo VideoCodec]}")
_FOLDER = "{Movie CleanTitle} ({Release Year})"


def _trash(ids):
    # The ID on the folder as well as the file, as TRaSH has it: the folder is where
    # Plex, Emby and Jellyfin look first, and it survives a file being replaced.
    return "%s%s/{Movie CleanTitle} {(Release Year)}%s %s.mkv" % (_FOLDER, ids, ids, _MEDIA)


def _trash_before_0_9(ids):
    """The film presets as they were, with the ID on the file only."""
    return "%s/{Movie CleanTitle} {(Release Year)}%s %s.mkv" % (_FOLDER, ids, _MEDIA)


MOVIE_PRESETS = [
    {"id": "riparr", "label": "Riparr default (simple)",
     "template": "{Title} ({Year})/{Title} ({Year}).mkv"},
    {"id": "trash", "label": "TRaSH Guides: Standard",
     "template": _trash("")},
    {"id": "trash-plex", "label": "TRaSH Guides: Plex",
     "template": _trash(" {tmdb-{TmdbId}}")},
    {"id": "trash-emby", "label": "TRaSH Guides: Emby",
     "template": _trash(" [tmdb-{TmdbId}]")},
    {"id": "trash-jellyfin", "label": "TRaSH Guides: Jellyfin",
     "template": _trash(" [tmdbid-{TmdbId}]")},
]

# A template saved from one of those presets becomes the new version of it, so the
# settings page still shows the preset's name rather than "Custom".
_UPGRADES = {"movie_template": {_trash_before_0_9(ids): _trash(ids) for ids in
                                (" {tmdb-{TmdbId}}", " [tmdb-{TmdbId}]", " [tmdbid-{TmdbId}]")}}


def upgrade_saved_templates(get, put):
    """Bring a saved copy of an older preset up to date. Returns the keys changed. A
    template somebody wrote themselves is never touched."""
    changed = []
    for key, table in _UPGRADES.items():
        now = get(key)
        if now in table:
            put(key, table[now])
            changed.append(key)
    return changed


# TRaSH Guides' recommended Sonarr naming, trimmed the same way as the film presets:
# https://trash-guides.info/Sonarr/Sonarr-recommended-naming-scheme/
# The ID goes on the series folder, which is where Plex, Emby and Jellyfin look for it.
# {TvdbId} is filled when the show was found on TMDb or TVmaze; without one the
# brackets disappear.
_SERIES = "{Series CleanTitle} {(Year)}"


def _sonarr(ids):
    return ("%s%s/Season {Season:00}/%s - S{Season:00}E{Episode:00} - "
            "{Episode CleanTitle} %s.mkv" % (_SERIES, ids, _SERIES, _MEDIA))


TV_PRESETS = [
    {"id": "riparr", "label": "Riparr default",
     "template": "{Title} ({Year})/Season {Season:00}/"
                 "{Title} - S{Season:00}E{Episode:00} - {EpisodeTitle}.mkv"},
    {"id": "trash", "label": "TRaSH Guides: Standard", "template": _sonarr("")},
    {"id": "trash-plex", "label": "TRaSH Guides: Plex",
     "template": _sonarr(" {tvdb-{TvdbId}}")},
    {"id": "trash-emby", "label": "TRaSH Guides: Emby",
     "template": _sonarr(" [tvdbid-{TvdbId}]")},
    {"id": "trash-jellyfin", "label": "TRaSH Guides: Jellyfin",
     "template": _sonarr(" [tvdbid-{TvdbId}]")},
]

# A made-up film, described the way MakeMKV would describe a UHD disc, so a preview
# shows every field filled in.
SAMPLE_MEDIA = {"video_codec": "HEVC", "bit_depth": "10", "quality": "Remux-2160p",
                "dynamic_range": "DV HDR10", "three_d": "", "audio_codec": "TrueHD Atmos",
                "audio_channels": "7.1", "audio_languages": "", "tmdb_id": "345691",
                "tvdb_id": "81189"}


def preview(template, kind="movie"):
    values = values_for("The Show Title" if kind == "tv" else "The Movie Title", 2010,
                        source="uhd", media=SAMPLE_MEDIA,
                        season=1 if kind == "tv" else None,
                        episode=1 if kind == "tv" else None,
                        episode_title="Pilot" if kind == "tv" else None)
    return render(template, values)
