"""
Looking audio CDs up on MusicBrainz (musicbrainz.org).

An audio CD carries no names at all -- no volume label, nothing but where each track
starts. That layout is enough, though: MusicBrainz identifies a CD from it (the "disc
ID"), and a disc ID leads to the album, its artist and year, and every track's title.
The front cover comes from the Cover Art Archive, which MusicBrainz runs alongside.

No key, no account. MusicBrainz asks for two things in return, both kept here: a
User-Agent that says who is asking, and no more than one request a second.

Never raises to a caller: no network or MusicBrainz having a bad day comes back as "no
match", and the disc asks a person instead.
"""
import base64
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

# RIPARR_MB_API / RIPARR_CAA point at stand-in servers, for testing offline.
API = os.environ.get("RIPARR_MB_API", "https://musicbrainz.org/ws/2")
COVER_ART = os.environ.get("RIPARR_CAA", "https://coverartarchive.org")
TIMEOUT = 15
USER_AGENT = ("riparr-server/%s ( https://github.com/ziggy46/riparr-server )"
              % __version__)
LEAD_IN = 150                      # sectors before track 1: every offset is counted from 0


class MusicBrainzError(Exception):
    pass


# ─────────────────────────────── the disc ID ───────────────────────────────

def disc_id(first, last, leadout, starts):
    """MusicBrainz's ID for a CD, from its audio session (optical.audio_session).

    https://musicbrainz.org/doc/Disc_ID_Calculation: the first and last track numbers,
    the lead-out and all 99 track offsets as hex, each 150 sectors on from the LBA the
    drive reports, SHA-1'd and base64'd with `.`, `_` and `-` for `+`, `/` and `=`.
    """
    offsets = [x + LEAD_IN for x in starts] + [0] * (99 - len(starts))
    text = "%02X%02X%08X" % (first, last, leadout + LEAD_IN)
    text += "".join("%08X" % x for x in offsets[:99])
    raw = base64.b64encode(hashlib.sha1(text.encode("ascii")).digest()).decode("ascii")
    return raw.replace("+", ".").replace("/", "_").replace("=", "-")


def toc_string(first, last, leadout, starts):
    """The `toc` parameter MusicBrainz's discid lookup takes: what lets it find a CD whose
    exact ID nobody has submitted yet, by its track lengths."""
    return " ".join(str(x) for x in [first, last, leadout + LEAD_IN]
                    + [s + LEAD_IN for s in starts])


def track_seconds(leadout, starts):
    """Each track's length in seconds, from where it starts and where the next one does
    (75 sectors a second)."""
    ends = starts[1:] + [leadout]
    return [max(0, (e - s) // 75) for s, e in zip(starts, ends)]


# ─────────────────────────────── asking MusicBrainz ───────────────────────────────

_last = [0.0]
_pace = threading.Lock()


def _get(path, params=None, base=None):
    """One request to MusicBrainz's JSON API, at most one a second."""
    params = dict(params or {}, fmt="json")
    url = "%s%s?%s" % (base or API, path, urllib.parse.urlencode(params))
    with _pace:
        wait = 1.0 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise MusicBrainzError("MusicBrainz answered HTTP %s." % e.code)
    except Exception as e:
        raise MusicBrainzError("Couldn't reach MusicBrainz: %s" % e)


def _artist(credit):
    """'Simon & Garfunkel' from MusicBrainz's list of credited names and join phrases."""
    return "".join((c.get("name") or (c.get("artist") or {}).get("name") or "")
                   + (c.get("joinphrase") or "") for c in credit or []).strip()


def _year(date):
    return int(date[:4]) if date and date[:4].isdigit() else None


def release(data, disc=None):
    """A MusicBrainz release, reduced to what a rip needs. `disc` picks which of its
    media this CD is (by disc ID); without one, the first."""
    media = data.get("media") or []
    medium = None
    if disc:
        medium = next((m for m in media
                       if any(d.get("id") == disc for d in m.get("discs") or [])), None)
    medium = medium or (media[0] if media else {})
    album_artist = _artist(data.get("artist-credit"))
    tracks = []
    for t in medium.get("tracks") or []:
        rec = t.get("recording") or {}
        tracks.append({
            "number": t.get("position") or len(tracks) + 1,
            "title": t.get("title") or rec.get("title") or "Track %d" % (len(tracks) + 1),
            "artist": _artist(t.get("artist-credit") or rec.get("artist-credit"))
            or album_artist,
            "seconds": int((t.get("length") or rec.get("length") or 0) / 1000),
            "recording_id": rec.get("id"), "track_id": t.get("id")})
    return {"id": data.get("id"), "title": data.get("title") or "Unknown Album",
            "artist": album_artist or "Unknown Artist",
            "date": data.get("date") or "", "year": _year(data.get("date")),
            "country": data.get("country") or "",
            "disc": medium.get("position") or 1, "discs": len(media) or 1,
            "format": medium.get("format") or "",
            "track_count": medium.get("track-count") or len(tracks),
            "tracks": tracks}


def lookup(disc, toc=None):
    """Every release this CD is part of, best first. [] when MusicBrainz doesn't know it."""
    try:
        params = {"inc": "artist-credits+recordings", "cdstubs": "no"}
        if toc:
            params["toc"] = toc                  # finds unsubmitted pressings by length
        data = _get("/discid/%s" % urllib.parse.quote(disc), params)
    except MusicBrainzError:
        return []
    if not data:
        return []
    found = [release(r, disc) for r in data.get("releases") or []]
    # A CD this exact pressing came from first, then the rest in MusicBrainz's order.
    exact = [r for r in found
             if any(d.get("id") == disc for m in next(
                 (x.get("media") or [] for x in data.get("releases") or []
                  if x.get("id") == r["id"]), []) for d in m.get("discs") or [])]
    return exact + [r for r in found if r not in exact]


def get_release(release_id, disc=None):
    """One release by its MusicBrainz ID, with its tracks, or None."""
    try:
        data = _get("/release/%s" % urllib.parse.quote(release_id),
                    {"inc": "artist-credits+recordings+discids"})
    except MusicBrainzError:
        return None
    return release(data, disc) if data else None


def _quoted(text):
    return '"%s"' % text.replace("\\", " ").replace('"', " ").strip()


def search(album="", artist="", tracks=None, limit=8):
    """Releases matching an album and/or artist name, CDs first, and ones with this
    disc's number of tracks before others."""
    album, artist = (album or "").strip(), (artist or "").strip()
    if not album and not artist:
        return []
    terms = []
    if album:
        terms.append("release:%s" % _quoted(album))
    if artist:
        terms.append("artist:%s" % _quoted(artist))
    query = " AND ".join(terms) + " AND format:CD"
    try:
        data = _get("/release", {"query": query, "limit": limit})
        if not (data or {}).get("releases"):
            # Some releases have no format recorded; ask again without it.
            data = _get("/release", {"query": " AND ".join(terms), "limit": limit})
    except MusicBrainzError:
        return []
    out = []
    for r in (data or {}).get("releases") or []:
        media = r.get("media") or []
        out.append({"id": r.get("id"), "title": r.get("title") or "",
                    "artist": _artist(r.get("artist-credit")),
                    "year": _year(r.get("date")), "country": r.get("country") or "",
                    "track_count": r.get("track-count") or sum(
                        m.get("track-count") or 0 for m in media),
                    "discs": len(media) or 1,
                    "format": ", ".join(sorted({m.get("format") or "" for m in media} - {""}))})
    if tracks:
        # A release whose track count matches this CD's is far likelier to be it.
        out.sort(key=lambda r: r["track_count"] != tracks)
    return out


def same_album(releases):
    """True when every candidate is the same album by the same artist -- pressings in
    different countries, say -- so it doesn't matter which one is used."""
    keys = {(r["artist"].casefold(), r["title"].casefold()) for r in releases}
    return len(keys) <= 1


def describe(r):
    """'Rumours (1977) by Fleetwood Mac', for buttons and questions."""
    year = " (%s)" % r["year"] if r.get("year") else ""
    return "%s%s by %s" % (r.get("title") or "Unknown Album", year,
                           r.get("artist") or "Unknown Artist")


# ─────────────────────────────── the cover ───────────────────────────────

def cover_url(release_id, size=500):
    return "%s/release/%s/front-%d" % (COVER_ART, release_id, size)


def cover(release_id, size=500):
    """The front cover's bytes, or None. The Cover Art Archive redirects to wherever
    the image actually lives; urllib follows that."""
    if not release_id:
        return None
    req = urllib.request.Request(cover_url(release_id, size),
                                 headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = r.read(20 * 2 ** 20)
        return data if data[:3] == b"\xff\xd8\xff" or data[:4] == b"\x89PNG" else None
    except Exception:
        return None
