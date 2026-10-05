#!/usr/bin/env python3
"""The naming template language: Riparr's own templates, Radarr's syntax, the TRaSH
Guides presets, and the media fields made from MakeMKV's stream descriptions.

Run: python3 server/naming.test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from riparr import naming as N  # noqa: E402

failures = []


def check(name, got, want):
    if got == want:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s\n         got  %r\n         want %r" % (name, got, want))
        failures.append(name)


def r(template, **kw):
    media = kw.pop("media", None)
    last = kw.pop("episode_last", None)
    return N.render(template, N.values_for(media=media, **kw), episode_last=last)


print("Riparr's own templates, unchanged")
check("the shipped film template",
      r("{Title} ({Year})/{Title} ({Year}).mkv", title="Spirited Away", year=2001),
      "Spirited Away (2001)/Spirited Away (2001).mkv")
check("no year leaves no empty brackets",
      r("{Title} ({Year})/{Title} ({Year}).mkv", title="Spirited Away"),
      "Spirited Away/Spirited Away.mkv")
check("{Source}", r("{Title} [{Source}].mkv", title="Heat", source="uhd"), "Heat [UHD].mkv")
check("episode padding",
      r("S{Season:00}E{Episode:000}.mkv", title="x", season=3, episode=7), "S03E007.mkv")
check("a double episode",
      r("S{Season:00}E{Episode:00}.mkv", title="x", season=1, episode=1, episode_last=2),
      "S01E01-E02.mkv")
check("a missing episode title drops its dash",
      r("{Title} - S{Season:00}E{Episode:00} - {EpisodeTitle}.mkv",
        title="Firefly", season=1, episode=4),
      "Firefly - S01E04.mkv")
check("an unknown token is left visible", r("{Titel}.mkv", title="Heat"), "{Titel}.mkv")
check("a colon in a title can't make a folder", r("{Title}.mkv", title="Mission: Impossible"),
      "Mission Impossible.mkv")

print("Radarr's syntax")
check("a wrapper inside the braces", r("{Title}{ [Source]}.mkv", title="Heat", source="dvd"),
      "Heat [DVD].mkv")
check("and the wrapper goes when the value is empty",
      r("{Title}{ [Source]}.mkv", title="Heat"), "Heat.mkv")
check("Radarr's names for the same things",
      r("{Movie CleanTitle} {(Release Year)}.mkv", title="Alien", year=1979),
      "Alien (1979).mkv")
check("token names ignore case and MediaInfo's spelling",
      r("{[mediainfo videocodec]}{[MEDIAINFO VideoBitDepth]}.mkv", title="x",
        media={"video_codec": "VC1", "bit_depth": "8"}), "[VC1][8].mkv")
check("a wrapper split across two tokens",
      r("{[Mediainfo AudioCodec}{ Mediainfo AudioChannels]}", title="x",
        media={"audio_codec": "DTS-HD MA", "audio_channels": "5.1"}), "[DTS-HD MA 5.1]")
check("nested: the outer braces are output",
      r("{Title} {tmdb-{TmdbId}}.mkv", title="Alien", media={"tmdb_id": "348"}),
      "Alien {tmdb-348}.mkv")
check("nested, and nothing at all when empty", r("{Title} {tmdb-{TmdbId}}.mkv", title="Alien"),
      "Alien.mkv")
check("{{Edition Tags}} is the edition in literal braces",
      r("{Title} - {{Edition Tags}}.mkv", title="Alien", media={"edition": "Director's Cut"}),
      "Alien - {Director's Cut}.mkv")
check("an empty ID in literal square brackets goes too",
      r("{Title} [tmdbid-{TmdbId}].mkv", title="Alien"), "Alien.mkv")
check("no edition doesn't leave a dangling dash",
      r("{Title} - {{Edition Tags}} {[Quality Full]}.mkv", title="Alien",
        media={"quality": "Remux-1080p"}), "Alien [Remux-1080p].mkv")

print("TRaSH Guides presets")
known = N.values_for("Dune", 2021, source="uhd", media=dict(N.SAMPLE_MEDIA, tmdb_id="438631"))
preset = {p["id"]: p["template"] for p in N.MOVIE_PRESETS}
media = "[Remux-2160p][TrueHD Atmos 7.1][HEVC].mkv"
check("Standard", N.render(preset["trash"], known), "Dune (2021)/Dune (2021) " + media)
check("Plex puts the ID in braces", N.render(preset["trash-plex"], known),
      "Dune (2021)/Dune (2021) {tmdb-438631} " + media)
check("Emby in brackets", N.render(preset["trash-emby"], known),
      "Dune (2021)/Dune (2021) [tmdb-438631] " + media)
check("Jellyfin as tmdbid", N.render(preset["trash-jellyfin"], known),
      "Dune (2021)/Dune (2021) [tmdbid-438631] " + media)
no_id = N.values_for("Dune", 2021, source="uhd",
                     media={k: v for k, v in N.SAMPLE_MEDIA.items() if k != "tmdb_id"})
for pid in ("trash-plex", "trash-emby", "trash-jellyfin"):
    check("%s without an ID is clean" % pid, N.render(preset[pid], no_id),
          "Dune (2021)/Dune (2021) " + media)
dropped = ("Edition Tags", "Custom Formats", "Release Group", "MediaInfo 3D",
           "VideoDynamicRangeType")
check("the presets leave out what a rip can't fill",
      [d for d in dropped if any(d in t for t in preset.values())], [])
check("and so does the documented token list",
      [d for d in dropped if any(d in t for t in N.TOKENS)], [])
full_trash = ("{Movie CleanTitle} {(Release Year)} - {{Edition Tags}} {[MediaInfo 3D]}"
              "{[Custom Formats]}{[Quality Full]}{[Mediainfo AudioCodec}"
              "{ Mediainfo AudioChannels]}{[MediaInfo VideoDynamicRangeType]}"
              "{[Mediainfo VideoCodec]}{-Release Group}.mkv")
check("TRaSH's full template, pasted in, still renders cleanly",
      N.render(full_trash, known), "Dune (2021) [Remux-2160p][TrueHD Atmos 7.1][DV HDR10][HEVC].mkv")

print("media fields from MakeMKV's streams")
uhd = {"streams": [
    {"type": "Video", "codec_short": "MpegH", "codec_long": "MpegH HEVC Main10@L5.1",
     "video_size": "3840x2160"},
    {"type": "Video", "codec_short": "MpegH", "name": "Dolby Vision", "video_size": "1920x1080"},
    {"type": "Audio", "codec_short": "TrueHD", "codec_long": "TrueHD Atmos", "layout": "7.1",
     "lang": "eng"},
    {"type": "Audio", "codec_short": "AC3", "flags": "256", "lang": "eng"},
    {"type": "Audio", "codec_short": "DTS", "channels": "6", "lang": "deu"},
]}
m = N.media_info(uhd, "uhd")
check("HEVC at 2160p is Remux-2160p", (m["video_codec"], m["quality"]), ("HEVC", "Remux-2160p"))
check("Main10 is 10-bit", m["bit_depth"], "10")
check("a second video stream is Dolby Vision", m["dynamic_range"], "DV")
check("TrueHD with Atmos, 7.1", (m["audio_codec"], m["audio_channels"]), ("TrueHD Atmos", "7.1"))
check("non-English audio languages, Radarr-style", m["audio_languages"], "[DE]")
m = N.media_info({"streams": [
    {"type": "Video", "codec_short": "Mpeg2", "video_size": "720x576"},
    {"type": "Audio", "codec_short": "AC3", "channels": "2"}]}, "dvd")
check("a DVD", (m["video_codec"], m["quality"], m["audio_codec"], m["audio_channels"]),
      ("MPEG2", "DVD", "AC3", "2.0"))
check("HDR is never assumed from a 4K disc",
      N.media_info({"streams": [{"type": "Video", "codec_short": "MpegH",
                                 "video_size": "3840x2160"}]}, "uhd")["dynamic_range"], "")
check("a full-disc backup is BR-DISK", N.quality("bluray", 1080, backup=True), "BR-DISK")
check("no streams at all gives empty fields, not an error",
      N.media_info({}, "bluray")["video_codec"], "")

print()
if failures:
    print("%d check(s) failed: %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("all good")
