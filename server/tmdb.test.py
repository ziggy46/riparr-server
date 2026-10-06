#!/usr/bin/env python3
"""TMDb lookups: how the key is sent, when a match is trusted, and how the IDs reach a
file name. No network: TMDb's answers are stubbed.

The rule under test is the one that matters: a wrong film is worse than none, so a
match is only accepted when it is unambiguous.

Run: python3 server/tmdb.test.py
"""
import io
import json
import os
import sys
import tempfile
from unittest import mock

_tmp = tempfile.mkdtemp(prefix="riparr-test-")
os.environ["RIPARR_DB"] = os.path.join(_tmp, "riparr.db")
os.environ.pop("RIPARR_TMDB_TOKEN", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from riparr import db, naming as N, rip as R, tmdb as T  # noqa: E402

failures = []


def check(name, got, want):
    if got == want:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s\n         got  %r\n         want %r" % (name, got, want))
        failures.append(name)


def film(id, title, year, votes=100, original=None, poster="/p%d.jpg"):
    return {"id": id, "title": title, "original_title": original or title,
            "year": year, "votes": votes, "poster_path": poster % id, "overview": ""}


db.init()

print("the key")
check("not configured without one", T.configured(), False)
check("and a lookup is then quietly nothing", T.search("Alien"), [])
check("identify too", T.identify("Alien (1979)")["match"], None)

seen = {}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(req, timeout=None):
    seen["url"] = req.full_url
    seen["auth"] = req.headers.get("Authorization")
    return _Resp(json.dumps({"images": {}}).encode())


with mock.patch.object(T.urllib.request, "urlopen", fake_urlopen):
    db.set("tmdb_token", "0123456789abcdef0123456789abcdef")
    T.check()
    check("a 32-character API key goes in the query", "api_key=0123" in seen["url"], True)
    check("and not in a header", seen["auth"], None)
    db.set("tmdb_token", "eyJhbGciOiJIUzI1NiJ9.a-long-read-access-token")
    T.check()
    check("a read access token goes in the Authorization header",
          seen["auth"], "Bearer eyJhbGciOiJIUzI1NiJ9.a-long-read-access-token")
    check("and not in the query", "api_key" in seen["url"], False)


def unauthorised(req, timeout=None):
    raise T.urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)


with mock.patch.object(T.urllib.request, "urlopen", unauthorised):
    check("a rejected key is reported plainly", T.check(),
          {"ok": False, "message": "TMDb didn't accept the key."})
    T._cache.clear()
    check("and a search with it is nothing, not an error", T.search("Heat"), [])

print("when a match is trusted")
blade = [film(78, "Blade Runner", 1982, 13000), film(335984, "Blade Runner 2049", 2017, 13000)]
check("exact title and year", T.pick("Blade Runner", 1982, blade)["id"], 78)
check("the sequel isn't the film", T.pick("Blade Runner", 2017, blade), None)
check("a year out by one, when there's only one such film",
      T.pick("Blade Runner", 1983, blade)["id"], 78)
check("case, punctuation and a leading article don't matter",
      T.pick("blade runner", 1982, [film(78, "The Blade Runner", 1982)])["id"], 78)
check("nor does & against and",
      T.pick("Fast and Furious", 2009, [film(13804, "Fast & Furious", 2009)])["id"], 13804)
check("the original title counts",
      T.pick("Sen to Chihiro no Kamikakushi", 2001,
             [film(129, "Spirited Away", 2001, original="Sen to Chihiro no Kamikakushi")])["id"],
      129)
check("a near title isn't a match", T.pick("Blade Runner", 1982,
                                           [film(1, "Blade Runner Black Out", 1982)]), None)
dune = [film(841, "Dune", 1984, 3000), film(438631, "Dune", 2021, 12000)]
check("no year and two well-known films of that name: ask", T.pick("Dune", None, dune), None)
check("no year, but one film dwarfs its namesake",
      T.pick("Alien", None, [film(348, "Alien", 1979, 15000), film(9, "Alien", 2016, 12)])["id"],
      348)
check("no year and only one film of that name", T.pick("Heat", None,
                                                      [film(949, "Heat", 1995)])["id"], 949)
check("two films of that name in the same year: ask",
      T.pick("Crash", 1996, [film(1, "Crash", 1996), film(2, "Crash", 1996)]), None)
heat = [film(949, "Heat", 1995, 7500), film(136795, "The Heat", 2013, 5000)]
check("HEAT is Heat, not The Heat", T.pick("Heat", None, heat)["id"], 949)
check("and THE_HEAT is The Heat", T.pick("The Heat", None, heat)["id"], 136795)
check("a label without 'The' doesn't pick an obscure exact title",
      T.pick("Matrix", None, [film(603, "The Matrix", 1999, 26000),
                              film(5, "Matrix", 1998, 20)])["id"], 603)

print("names")
check("a stored name splits into title and year", T.split("Blade Runner (1982)"),
      ("Blade Runner", 1982))
check("a volume label is cleaned for searching", T.split("BLADE_RUNNER_DISC_1"),
      ("blade runner", None))
check("display name", T.display_name({"title": "Heat", "year": 1995}), "Heat (1995)")

print("identify, end to end")
db.set("tmdb_token", "eyJ.test-token")
T._cache.clear()


def tmdb_api(req, timeout=None):
    url = req.full_url
    if "/search/movie" in url:
        results = [{"id": 78, "title": "Blade Runner", "original_title": "Blade Runner",
                    "release_date": "1982-06-25", "poster_path": "/br.jpg", "vote_count": 13000},
                   {"id": 335984, "title": "Blade Runner 2049",
                    "original_title": "Blade Runner 2049", "release_date": "2017-10-04",
                    "vote_count": 13000}]
        return _Resp(json.dumps({"results": results}).encode())
    if "/movie/78" in url:
        return _Resp(json.dumps({"id": 78, "title": "Blade Runner", "original_title":
                                 "Blade Runner", "release_date": "1982-06-25",
                                 "imdb_id": "tt0083658", "poster_path": "/br.jpg",
                                 "vote_count": 13000}).encode())
    raise AssertionError("unexpected TMDb call: %s" % url)


with mock.patch.object(T.urllib.request, "urlopen", tmdb_api):
    r = T.identify("BLADE_RUNNER (1982)")
    check("a confident match comes back with its IMDb ID",
          (r["match"]["id"], r["match"]["imdb_id"]), (78, "tt0083658"))
    r = T.identify("Blade Runner")
    check("without a year, two films named Blade Runner-ish still pick the exact one",
          (r["match"] or {}).get("id"), 78)
    check("and the candidates are kept for asking", len(r["candidates"]), 2)
    check("a poster URL", T.poster_url("/br.jpg"), "https://image.tmdb.org/t/p/w780/br.jpg")


def searched_as(name):
    """The (query, year) pairs identify() tries for a name, in order."""
    seen = []

    def fake_search(t, y=None):
        seen.append((t, y))
        return []
    with mock.patch.object(T, "search", fake_search):
        T.identify(name)
    return seen


check("edition words are dropped only after the full name fails",
      searched_as("ALIEN_DIRECTORS_CUT"), [("alien directors cut", None), ("alien", None)])
check("a bare year is tried as the year, after the whole name",
      searched_as("DUNE_2021"), [("dune 2021", None), ("dune", 2021)])
check("so a film called Wonder Woman 1984 is searched as itself first",
      searched_as("WONDER_WOMAN_1984")[0], ("wonder woman 1984", None))

print("the IDs reach the file name")
job = {"disc_family": "bluray", "tmdb_id": 78, "imdb_id": "tt0083658",
       "chosen_title": 0, "titles": [{"index": 0, "streams": R._MOCK_STREAMS["bluray"]}]}
media = R._media_for(job, 0)
plex = [p["template"] for p in N.MOVIE_PRESETS if p["id"] == "trash-plex"][0]
check("the Plex preset gets {tmdb-78}",
      R._render_template(plex, "Blade Runner", 1982, source="bluray", media=media),
      "Blade Runner (1982)/Blade Runner (1982) {tmdb-78} [Remux-1080p][DTS-HD MA 5.1][AVC].mkv")
check("and {ImdbId} the IMDb one",
      R._render_template("{Title} [imdbid-{ImdbId}].mkv", "Blade Runner", media=media),
      "Blade Runner [imdbid-tt0083658].mkv")

print()
if failures:
    print("%d check(s) failed: %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("all good")
