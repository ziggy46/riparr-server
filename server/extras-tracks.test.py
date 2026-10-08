#!/usr/bin/env python3
"""Extras, track languages and the media server, through the real pipeline.

  * the track rules MakeMKV is given: off leaves MakeMKV alone; on keeps the listed
    languages plus the film's original one, and never leaves a film silent
  * which titles count as extras: not the film, not another cut or decoy of it, not a
    "play all", each only once, and none at all on an obfuscated disc
  * a film ripped with its extras files them in Featurettes beside it, staged and
    direct, and a naming template with no film folder keeps the film and says why
  * Plex and Jellyfin are asked to scan just the new folder when their library folder
    has the same name as Riparr's, and the whole library of that kind when it hasn't

Nothing is stubbed except the hardware, TMDb's answer, and the media server, which is a
small HTTP server in this process.

Run: python3 server/extras-tracks.test.py
"""
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_tmp = tempfile.mkdtemp(prefix="riparr-extras-test-")
os.environ["RIPARR_DB"] = os.path.join(_tmp, "test.db")
os.environ["RIPARR_MOCK_CONTENT"] = "movie"
os.environ["RIPARR_APPLIANCE"] = "0"
os.environ["RIPARR_MOCK_FAST"] = "1"
os.environ["RIPARR_MOCK_DISC"] = "bluray"
_MOCK_SHARE = "/tmp/riparr-mock-share"
os.environ["RIPARR_LIBRARY_MOUNT"] = os.path.join(_MOCK_SHARE, "nas", "Media")

from riparr import db, makemkv as MK, mediaserver as MS, platform as P, rip, shares as SH  # noqa: E402
from riparr import tmdb as TM  # noqa: E402

for _d in P._MOCK_DISCS.values():
    _d["size_bytes"] = 64 * 2 ** 20

failures = []


def check(name, got, want):
    if got == want:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s: got %r, wanted %r" % (name, got, want))
        failures.append(name)


def contains(name, haystack, needle):
    ok = needle in (haystack or "")
    print("  %s %s" % ("ok  " if ok else "FAIL", name))
    if not ok:
        print("       %r does not contain %r" % (haystack, needle))
        failures.append(name)


def share_files(under="nas/Media/Movies"):
    out = []
    base = os.path.join(SH.MOCK_SHARE_ROOT, under)
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != ".riparr-incoming"]
        for f in files:
            out.append(os.path.relpath(os.path.join(root, f), base))
    return sorted(out)


def fresh_share():
    shutil.rmtree(SH.MOCK_SHARE_ROOT, ignore_errors=True)
    os.makedirs(os.environ["RIPARR_LIBRARY_MOUNT"], exist_ok=True)
    shutil.rmtree(P.STAGING, ignore_errors=True)
    os.makedirs(P.STAGING, exist_ok=True)
    for row in db.list_shares():
        db.delete_share(row["id"])
    return db.add_share("Media", "nas", "Media", None, None, make_default=True)


def new_job(label):
    os.environ["RIPARR_MOCK_LABEL"] = label
    job_id = db.create_job(state="queued", disc_label=label, kind="movie",
                           fingerprint="fp-%s-%f" % (label, time.time()))
    return db.get_job(job_id)


def run(job):
    rip._run_job(job)
    j = db.get_job(job["id"])
    if j["state"] == "transferring":
        rip._send_one(j)
    return db.get_job(job["id"])


db.init()
db.set("setup_complete", True)
db.set("verify_mode", "quick")
db.set("on_unknown_disc", "label")
db.set("session_secret", "test-secret")

# ── the track rules ───────────────────────────────────────────────────────────

print("languages, however they're written")
check("two letters", MK.lang_codes("en"), {"eng"})
check("both spellings of French", MK.lang_codes(["fra"]), {"fre", "fra"})
check("a list as typed", MK.lang_codes("eng, de"), {"eng", "ger", "deu"})
check("nonsense is ignored", MK.lang_codes(["", "english", "12"]), set())

print("the rules MakeMKV is given")
rules = MK.selection_string({"eng", "jpn"}, {"eng"}, forced=True, commentary=False,
                           first="eng")
check("starts from nothing", rules.split(",")[:2], ["-sel:all", "+sel:video"])
contains("keeps audio in the languages, and audio with none marked", rules,
         "+sel:(audio&(eng|jpn|nolang))")
contains("keeps subtitles in the languages", rules, "+sel:(subtitle&(eng))")
contains("keeps forced subtitles", rules, "+sel:(subtitle&forced)")
contains("drops commentary", rules, "-sel:special")
contains("their language first", rules, "-10:eng")
check("commentary kept when asked", "-sel:special" in MK.selection_string(
    {"eng"}, set(), commentary=True), False)
check("3D kept when asked", "-sel:mvcvideo" in MK.selection_string(
    {"eng"}, set(), keep_3d=True), False)

print("which rules a rip gets")
_real_details = TM.details
TM.details = lambda tid: {"id": tid, "original_language": "ja"}
jid = db.create_job(state="queued", disc_label="X", kind="movie", tmdb_id=129)
job = db.get_job(jid)
s = rip._settings()
db.set("tracks_filter", False)
check("off: MakeMKV's own choice", rip._track_rules(job, rip._settings()), None)
db.set("tracks_filter", True)
db.set("audio_languages", ["eng"])
db.set("subtitle_languages", ["eng"])
r = rip._track_rules(job, rip._settings(), [{"type": "Audio", "lang": "eng"},
                                             {"type": "Audio", "lang": "jpn"}])
contains("on: the film's original language as well", r, "(audio&(eng|jpn|nolang))")
db.set("keep_original_audio", False)
r = rip._track_rules(job, rip._settings(), [{"type": "Audio", "lang": "eng"}])
contains("original language off: only theirs", r, "(audio&(eng|nolang))")
r = rip._track_rules(job, rip._settings(), [{"type": "Audio", "lang": "fre"}])
check("no audio in their languages: keep everything, not a silent film", r, None)
contains("...and say so", db.get_job(jid)["warning"], "every track was kept")
db.set("audio_languages", [])
check("no languages at all: keep everything",
      rip._track_rules(job, rip._settings(), []), None)
db.set("audio_languages", ["eng"])
db.set("keep_original_audio", True)
db.set("tracks_filter", False)
TM.details = _real_details

# ── which titles are extras ───────────────────────────────────────────────────

print("which titles are extras")


def t(i, secs, segs="", gb=1.0):
    return {"index": i, "seconds": secs, "bytes": int(gb * 2 ** 30), "segments": segs}


film = t(0, 7200, "1", 30)
titles = [film,
          t(1, 7180, "1,2", 30),          # another cut of the film
          t(2, 900, "10"), t(3, 600, "11"),
          t(4, 1500, "10,11"),            # play all
          t(5, 900, "10"),                # the same featurette again
          t(6, 60, "12"),                 # under the floor
          t(7, 300, "", 0.3), t(8, 300, "", 0.3)]   # no segments, same length and size
picked = [x["index"] for x in rip.pick_extras(titles, film, 120)]
check("featurettes, each once, no play-all, no other cut", picked, [2, 3, 7])
decoys = [t(i, 7200 + i, str(i), 30) for i in range(5)] + [t(9, 900, "9")]
check("an obfuscated disc gives none", rip.pick_extras(decoys, decoys[0], 120), [])
check("named by number and length", rip._extra_name(3, t(0, 1452)), "Extra 03 (24 min).mkv")
check("short ones in seconds", rip._extra_name(1, t(0, 75)), "Extra 01 (75 s).mkv")

# ── extras, end to end ────────────────────────────────────────────────────────

print("a film with its extras, staged")
fresh_share()
db.set("rip_mode", "all")
db.set("transfer_mode", "burst")
job = run(new_job("THE_MATRIX"))
check("finished", job["state"], "done")
check("film and extras", share_files(), [
    "The Matrix/Featurettes/Extra 01 (2 min).mkv",
    "The Matrix/Featurettes/Extra 02 (24 min).mkv",
    "The Matrix/The Matrix.mkv"])
check("each extra recorded as filed", [e["state"] for e in rip._job_extras(job)], ["done", "done"])
check("staging emptied", os.path.exists(os.path.join(P.STAGING, "job-%d" % job["id"])), False)

print("a film with its extras, straight to the library")
fresh_share()
db.set("transfer_mode", "direct")
job = run(new_job("THE_MATRIX"))
check("finished", job["state"], "done")
check("film and extras", share_files(), [
    "The Matrix/Featurettes/Extra 01 (2 min).mkv",
    "The Matrix/Featurettes/Extra 02 (24 min).mkv",
    "The Matrix/The Matrix.mkv"])
check("no scratch left in the library",
      os.listdir(os.path.join(os.environ["RIPARR_LIBRARY_MOUNT"], "Movies", ".riparr-incoming"))
      if os.path.isdir(os.path.join(os.environ["RIPARR_LIBRARY_MOUNT"], "Movies",
                                    ".riparr-incoming")) else [], [])

print("films filed loose in Movies/ keep the film, not the extras")
fresh_share()
db.set("transfer_mode", "burst")
db.set("movie_template", "{Title} ({Year}).mkv")
job = run(new_job("THE_MATRIX"))
check("finished", job["state"], "done")
check("just the film", share_files(), ["The Matrix.mkv"])
contains("and it says why", job["warning"], "folder of its own")
db.set("movie_template", db.DEFAULTS["movie_template"])

print("main title only rips no extras")
fresh_share()
db.set("rip_mode", "main")
job = run(new_job("THE_MATRIX"))
check("just the film", share_files(), ["The Matrix/The Matrix.mkv"])

# ── the media server ──────────────────────────────────────────────────────────

calls = []
SERVER = {"kind": "plex"}


class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, code, body=None):
        raw = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        token = self.headers.get("X-Plex-Token") or self.headers.get("X-Emby-Token")
        if token != "good":
            return self._reply(401, {})
        u = urllib.parse.urlparse(self.path)
        calls.append(("GET", u.path, urllib.parse.parse_qs(u.query)))
        if u.path == "/library/sections":
            return self._reply(200, {"MediaContainer": {"Directory": [
                {"key": "1", "type": "movie", "title": "Films",
                 "Location": [{"path": SERVER.get("movies", "/data/Movies")}]},
                {"key": "2", "type": "show", "title": "TV Shows",
                 "Location": [{"path": "/data/TV"}]}]}})
        if u.path.endswith("/refresh"):
            return self._reply(200)
        if u.path == "/Library/VirtualFolders":
            return self._reply(200, [
                {"Name": "Films", "CollectionType": "movies",
                 "Locations": [SERVER.get("movies", "/media/Movies")]},
                {"Name": "Music", "CollectionType": "music", "Locations": ["/media/Music"]}])
        return self._reply(404, {})

    def do_POST(self):
        if self.headers.get("X-Emby-Token") != "good":
            return self._reply(401, {})
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"null") if n else None
        calls.append(("POST", self.path, body))
        return self._reply(204)


httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d" % httpd.server_address[1]

print("Plex")
fresh_share()
db.set("media_server", "plex")
db.set("media_server_url", URL)
db.set("media_server_token", "bad")
r = MS.test()
check("a wrong token is said plainly", r["ok"], False)
contains("...naming the server", r.get("error"), "Plex turned the token down")
db.set("media_server_token", "good")
r = MS.test()
contains("a right one lists the libraries", r.get("message"), "Films, TV Shows")
calls.clear()
MS.refresh("movie", "Movies/Arrival (2016)")
check("just the new folder, in Plex's own path", calls[-1],
      ("GET", "/library/sections/1/refresh", {"path": ["/data/Movies/Arrival (2016)"]}))
SERVER["movies"] = "/data/films"
calls.clear()
MS.refresh("movie", "Movies/Arrival (2016)")
check("no folder by that name: the whole film library", calls[-1],
      ("GET", "/library/sections/1/refresh", {}))
SERVER.pop("movies")

print("Jellyfin")
db.set("media_server", "jellyfin")
calls.clear()
MS.refresh("movie", "Movies/Arrival (2016)")
check("tells it which folder changed", calls[-1],
      ("POST", "/Library/Media/Updated",
       {"Updates": [{"Path": "/media/Movies/Arrival (2016)", "UpdateType": "Created"}]}))
SERVER["movies"] = "/media/films"
calls.clear()
MS.refresh("movie", "Movies/Arrival (2016)")
check("no folder by that name: a library scan", calls[-1], ("POST", "/Library/Refresh", {}))
SERVER.pop("movies")

print("a finished rip tells the media server, without waiting for it")
db.set("media_server", "plex")
db.set("rip_mode", "main")
calls.clear()
job = run(new_job("ARRIVAL"))
check("finished", job["state"], "done")
for th in threading.enumerate():
    if th.name == "riparr-mediaserver":
        th.join(timeout=10)
check("Plex was asked to scan the film's folder", calls[-1][:2],
      ("GET", "/library/sections/1/refresh"))
contains("...that folder", calls[-1][2]["path"][0], "/data/Movies/")

print("a media server that's down doesn't fail a rip")
db.set("media_server_url", "http://127.0.0.1:9")
job = run(new_job("ARRIVAL"))
check("still finished", job["state"], "done")
db.set("media_server", "")

httpd.shutdown()
shutil.rmtree(_tmp, ignore_errors=True)
print()
if failures:
    print("%d failed: %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("all passed")
