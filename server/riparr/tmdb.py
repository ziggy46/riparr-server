"""
Looking films up on The Movie Database (themoviedb.org).

A disc says very little about itself: a volume label like BLADE_RUNNER_DC, or whatever
somebody typed. TMDb turns that into the film's real title and year, its TMDb and IMDb
IDs (which Plex, Emby and Jellyfin match on, and the TRaSH naming presets put in the
file name), and a poster.

**Your own key.** TMDb's terms don't allow a shared key in public source, so this is
off until somebody pastes a token from https://www.themoviedb.org/settings/api into
Settings → Library (or RIPARR_TMDB_TOKEN). Either kind works: the long "API Read Access
Token", or the 32-character "API Key".

**A wrong match is worse than none.** An ID in a file name is trusted over the title by
every media server, so the wrong one files a film as a different film, quietly. A match
is only accepted when the title is the same and the year agrees -- or, with no year, when
there is one obvious film by that name. Anything less is handed back as candidates, for
a person to choose from or to ignore.

Never raises to a caller: no network, a bad key or TMDb having a bad day all come back
as "no match", and the rip carries on with the name it had.
"""
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

# RIPARR_TMDB_API points at a stand-in server, for testing without a key.
API = os.environ.get("RIPARR_TMDB_API", "https://api.themoviedb.org/3")
IMAGES = "https://image.tmdb.org/t/p/"
POSTER_SIZE = "w780"
TIMEOUT = 10
CACHE_TTL = 6 * 3600
ATTRIBUTION = "This product uses the TMDB API but is not endorsed or certified by TMDB."

# With no year to go on, the most-voted film of that exact title only wins outright when
# it dwarfs the next one -- "Alien" (1979) against an obscure namesake. "Dune" (1984 and
# 2021) is close enough that a person should choose.
DOMINANCE = 10
MIN_VOTES = 50


class TmdbError(Exception):
    pass


def token():
    from . import db
    return ((db.get("tmdb_token") or "").strip()
            or os.environ.get("RIPARR_TMDB_TOKEN", "").strip())


def configured():
    return bool(token())


def _request(path, params=None, key=None):
    key = key or token()
    if not key:
        raise TmdbError("No TMDb key is set.")
    params = dict(params or {})
    headers = {"Accept": "application/json",
               "User-Agent": "riparr-server/%s" % __version__}
    if re.fullmatch(r"[0-9a-f]{32}", key):
        params["api_key"] = key                 # a v3 API key
    else:
        headers["Authorization"] = "Bearer %s" % key   # a v4 read access token
    url = "%s%s?%s" % (API, path, urllib.parse.urlencode(params))
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                    timeout=TIMEOUT) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise TmdbError("TMDb didn't accept the key.")
        if e.code == 404:
            raise TmdbError("TMDb doesn't have that.")
        raise TmdbError("TMDb answered HTTP %s." % e.code)
    except Exception as e:
        raise TmdbError("Couldn't reach TMDb: %s" % e)


_cache = {}
_cache_lock = threading.Lock()


def _cached(key, fn):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]
    value = fn()
    with _cache_lock:
        if len(_cache) > 500:
            _cache.clear()
        _cache[key] = (now, value)
    return value


def check(key=None):
    """{"ok", "message"}: does this key work? For the settings page's test button."""
    try:
        _request("/configuration", key=key)
    except TmdbError as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "message": "TMDb accepted the key."}


def _year(date):
    m = re.match(r"(\d{4})", date or "")
    return int(m.group(1)) if m else None


def _film(r):
    return {"id": r.get("id"), "title": r.get("title") or r.get("original_title") or "",
            "original_title": r.get("original_title") or "",
            "year": _year(r.get("release_date")),
            "poster_path": r.get("poster_path") or "",
            "votes": int(r.get("vote_count") or 0),
            "original_language": r.get("original_language") or "",
            "overview": (r.get("overview") or "")[:280]}


def search(title, year=None):
    """Films matching a title, best first. [] on any failure."""
    title = (title or "").strip()
    if not title or not configured():
        return []

    def go():
        params = {"query": title, "include_adult": "false"}
        if year:
            params["year"] = str(year)
        data = _request("/search/movie", params)
        results = [_film(r) for r in data.get("results") or []]
        # A year narrows TMDb's search to that release year exactly, and discs are
        # often dated a year off. Ask again without it before giving up.
        if year and not results:
            data = _request("/search/movie", {"query": title, "include_adult": "false"})
            results = [_film(r) for r in data.get("results") or []]
        return results[:10]
    try:
        return _cached(("search", title.lower(), year), go)
    except TmdbError:
        return []


def details(tmdb_id):
    """{"id", "title", "year", "imdb_id", "poster_path"} for one film, or None."""
    if not tmdb_id or not configured():
        return None

    def go():
        r = _request("/movie/%d" % int(tmdb_id))
        film = _film(r)
        film["imdb_id"] = r.get("imdb_id") or ""
        return film
    try:
        return _cached(("movie", int(tmdb_id)), go)
    except (TmdbError, ValueError):
        return None


def _key(title):
    """A title reduced to what has to match: case, accents, punctuation, "&" and a
    leading article don't count; the words and numbers do."""
    t = unicodedata.normalize("NFKD", title or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = t.replace("&", " and ")
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    t = re.sub(r"^(the|a|an)\s+", "", t)
    return t


def _strict(title):
    """_key, but keeping a leading article: "Heat" and "The Heat" are different films."""
    t = unicodedata.normalize("NFKD", title or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", t.replace("&", " and ")).strip()


def pick(title, year, results):
    """The one film these results confidently mean, or None. See the module docstring."""
    want = _key(title)
    if not want:
        return None
    same = [r for r in results
            if _key(r["title"]) == want or _key(r["original_title"]) == want]
    # Titles that match with the article as written come first. Ignoring "The" is
    # right for MATRIX -> The Matrix, but it made HEAT ambiguous with The Heat (2013).
    strict = [r for r in same if _strict(title) in (_strict(r["title"]),
                                                    _strict(r["original_title"]))]
    if strict and len(strict) < len(same):
        found = pick_from(strict, year)
        # Unless it's obscure next to the others: a label that dropped "The" (MATRIX)
        # must not pick a 20-vote film called "Matrix" over The Matrix.
        others = max((r["votes"] for r in same if r not in strict), default=0)
        if found and found["votes"] >= MIN_VOTES and found["votes"] * DOMINANCE >= others:
            return found
    return pick_from(same, year)


def pick_from(same, year):
    """The confident choice among results whose titles all match."""
    if year:
        exact = [r for r in same if r["year"] == year]
        if len(exact) == 1:
            return exact[0]
        near = [r for r in same if r["year"] and abs(r["year"] - year) == 1]
        return near[0] if not exact and len(near) == 1 else None
    if len(same) == 1:
        return same[0]
    if len(same) > 1:
        ranked = sorted(same, key=lambda r: r["votes"], reverse=True)
        top, second = ranked[0], ranked[1]
        if top["votes"] >= MIN_VOTES and top["votes"] >= DOMINANCE * max(second["votes"], 1):
            return top
    return None


_YEAR = re.compile(r"^(.*?)\s*\((\d{4})\)\s*$")
# A year with no brackets at the end of a label: DUNE_2021. Only tried after the whole
# name has failed, because for Wonder Woman 1984 or Blade Runner 2049 it's the title.
_BARE_YEAR = re.compile(r"^(.+?)\s+((?:19|20)\d{2})$")
# Words on the box rather than in the title. Dropped only after the full name failed,
# so a film actually called "The Final Cut" is still found by its name.
_EDITION = re.compile(
    r"\s+(?:(?:the\s+)?(?:directors?|director s|final|theatrical|extended|ultimate|"
    r"special|collectors?|collector s|anniversary|definitive|unrated|uncut|remastered|"
    r"limited|criterion)(?:\s+(?:cut|edition|version|collection))?|"
    r"(?:\d+(?:th)?\s+)?anniversary(?:\s+edition)?|imax(?:\s+edition)?|"
    r"4k|uhd|blu\s*ray|dvd)(?:\s+.*)?$", re.I)


def split(name):
    """"Blade Runner (1982)" -> ("Blade Runner", 1982); a label -> (cleaned, None)."""
    m = _YEAR.match(name or "")
    if m:
        return m.group(1).strip(), int(m.group(2))
    # A raw volume label: BLADE_RUNNER -> blade runner.
    if "_" in (name or "") or (name or "").isupper():
        from .artwork import normalize
        return normalize(name), None
    return (name or "").strip(), None


def identify(name):
    """What film a name means: {"match": film-with-imdb_id or None, "candidates": [...]}.

    `candidates` is the top few results, for a person to choose from when there's no
    confident match.
    """
    title, year = split(name)
    tries = [(title, year)]
    if not year:
        bare = _EDITION.sub("", title).strip()
        if bare and bare != title:
            tries.append((bare, None))
        for t in (title, bare):
            m = _BARE_YEAR.match(t or "")
            if m and (m.group(1).strip(), int(m.group(2))) not in tries:
                tries.append((m.group(1).strip(), int(m.group(2))))
    # The suggestions shown when nothing is certain come from the last reading that
    # found anything -- the most cleaned-up one, which is the best list to pick from.
    shown = ([], title, year)
    for t, y in tries:
        results = search(t, y)
        if results:
            shown = (results, t, y)
        chosen = pick(t, y, results)
        if chosen:
            return {"match": details(chosen["id"]), "candidates": results[:6],
                    "query": t, "year": y}
    return {"match": None, "candidates": shown[0][:6], "query": shown[1], "year": shown[2]}


def poster_url(path):
    return IMAGES + POSTER_SIZE + path if path else ""


def display_name(film):
    """"Title (Year)", as Riparr stores a film's name."""
    if not film:
        return ""
    return "%s (%s)" % (film["title"], film["year"]) if film.get("year") else film["title"]


# ── television ───────────────────────────────────────────────────────────────
#
# For season discs, when TMDb is the episode source (tv.source()). TMDb numbers seasons
# the way Plex and Jellyfin do -- specials are season 0 -- and gives the TVDB and IMDb
# IDs that TV naming schemes put in folder names.

def search_tv(name):
    """Shows matching a name, best first: [{"id", "name", "year", "votes"}]. [] on failure."""
    name = (name or "").strip()
    if not name or not configured():
        return []

    def go():
        data = _request("/search/tv", {"query": name, "include_adult": "false"})
        return [{"id": r.get("id"), "name": r.get("name") or r.get("original_name") or "",
                 "year": _year(r.get("first_air_date")),
                 "country": "/".join(r.get("origin_country") or []),
                 "votes": int(r.get("vote_count") or 0)}
                for r in (data.get("results") or [])[:10] if r.get("id")]
    try:
        return _cached(("search-tv", name.lower()), go)
    except TmdbError:
        return []


def tv_show(tmdb_id):
    """{"id", "name", "year", "network", "seasons": [n...], "tvdb_id", "imdb_id"} or None."""
    if not tmdb_id or not configured():
        return None

    def go():
        r = _request("/tv/%d" % int(tmdb_id), {"append_to_response": "external_ids"})
        ext = r.get("external_ids") or {}
        nets = r.get("networks") or []
        return {"id": r.get("id"), "name": r.get("name") or "",
                "year": _year(r.get("first_air_date")),
                "network": (nets[0] or {}).get("name", "") if nets else "",
                "seasons": sorted(int(s["season_number"]) for s in r.get("seasons") or []
                                  if s.get("season_number") is not None),
                "tvdb_id": ext.get("tvdb_id") or None,
                "imdb_id": ext.get("imdb_id") or ""}
    try:
        return _cached(("tv", int(tmdb_id)), go)
    except (TmdbError, ValueError):
        return None


def tv_episodes(tmdb_id):
    """Every episode of a show: [{"season", "number", "name", "runtime", "special"}].

    TMDb serves episodes a season at a time, but appends up to twenty seasons to one
    request, so even a long-running show is one or two calls. [] on failure.
    """
    show = tv_show(tmdb_id)
    if not show:
        return []

    def go():
        out = []
        seasons = show["seasons"]
        for i in range(0, len(seasons), 20):
            chunk = seasons[i:i + 20]
            r = _request("/tv/%d" % int(tmdb_id), {
                "append_to_response": ",".join("season/%d" % n for n in chunk)})
            for n in chunk:
                for e in (r.get("season/%d" % n) or {}).get("episodes") or []:
                    if e.get("episode_number") is None:
                        continue
                    out.append({"season": n, "number": int(e["episode_number"]),
                                "name": e.get("name") or "",
                                "runtime": e.get("runtime") or 0,
                                "special": n == 0})
        return out
    try:
        return _cached(("tv-episodes", int(tmdb_id)), go)
    except (TmdbError, ValueError):
        return []
