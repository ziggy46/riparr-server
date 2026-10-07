#!/usr/bin/env python3
"""The parts Riparr Server changed from upstream: how it decides what it's running on,
which networks the share scan covers, the update check, and the password reset file.

Each of these is easy to break quietly in an upstream merge -- the first one most of
all, since getting it wrong means a real server serving a simulated drive while the
interface looks perfectly normal.

Run: python3 server/server-mode.test.py
"""
import io
import ipaddress
import json
import os
import sys
import tempfile
import urllib.error
from unittest import mock

# The database has to point somewhere disposable before anything imports it.
_tmp = tempfile.mkdtemp(prefix="riparr-test-")
os.environ["RIPARR_DB"] = os.path.join(_tmp, "riparr.db")
os.environ.pop("RIPARR_SCAN_SUBNETS", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from riparr import db, platform as P, shares as SH, updater  # noqa: E402

failures = []


def check(name, got, want):
    if got == want:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s\n         got  %r\n         want %r" % (name, got, want))
        failures.append(name)


def env(**kw):
    """os.environ with exactly these Riparr variables set (None removes one)."""
    base = {k: v for k, v in os.environ.items()
            if k not in ("RIPARR_APPLIANCE", "RIPARR_MOCK", "RIPARR_RUNTIME", "container")}
    base.update({k: v for k, v in kw.items() if v is not None})
    return mock.patch.dict(os.environ, base, clear=True)


print("real hardware or simulation")
for system, kw, want, name in [
    ("Linux", {}, True, "Linux is real hardware, with no device tree needed"),
    ("Darwin", {}, False, "a Mac is a development machine"),
    ("Windows", {}, False, "so is Windows"),
    ("Linux", {"RIPARR_MOCK": "1"}, False, "RIPARR_MOCK=1 asks for simulation on Linux"),
    ("Linux", {"RIPARR_MOCK": "0"}, True, "RIPARR_MOCK=0 doesn't"),
    ("Linux", {"RIPARR_MOCK": "false"}, True, "nor does RIPARR_MOCK=false"),
    ("Darwin", {"RIPARR_APPLIANCE": "1"}, True, "RIPARR_APPLIANCE=1 forces real"),
    ("Linux", {"RIPARR_APPLIANCE": "0"}, False, "RIPARR_APPLIANCE=0 forces simulation"),
    ("Linux", {"RIPARR_APPLIANCE": "1", "RIPARR_MOCK": "1"}, True,
     "RIPARR_APPLIANCE wins over RIPARR_MOCK"),
]:
    with env(**kw), mock.patch.object(P._p, "system", return_value=system):
        check(name, P._is_appliance(), want)

print("what kind of host")
with env(RIPARR_RUNTIME="podman"):
    check("RIPARR_RUNTIME overrides the guess", P.runtime(), "podman")
with env(), mock.patch.object(P.os.path, "exists", side_effect=lambda p: p == "/.dockerenv"):
    check("/.dockerenv means Docker", P.runtime(), "docker")
with env(container="lxc"), mock.patch.object(P.os.path, "exists", return_value=False), \
        mock.patch.object(P, "_read", return_value=""):
    check("container=lxc means LXC", P.runtime(), "lxc")
with env(), mock.patch.object(P.os.path, "exists", return_value=False), \
        mock.patch.object(P, "_read", return_value=""):
    check("nothing at all means a plain host", P.runtime(), "host")

print("which networks the share scan covers")
nets, err = SH.parse_subnets("192.168.1.0/24")
check("a CIDR parses", (nets, err), ([ipaddress.ip_network("192.168.1.0/24")], None))
nets, err = SH.parse_subnets("10.0.0.7")
check("a bare address means its /24", nets, [ipaddress.ip_network("10.0.0.0/24")])
nets, err = SH.parse_subnets("192.168.1.0/24; 192.168.2.0/24")
check("several, separated by ; or ,", len(nets), 2)
check("nothing typed is not an error", SH.parse_subnets("  "), ([], None))
check("a /22 is the most it will sweep", SH.parse_subnets("10.0.0.0/22")[1], None)
check("a /21 is refused", bool(SH.parse_subnets("10.0.0.0/21")[1]), True)
check("so is a /8", "1024" in (SH.parse_subnets("10.0.0.0/8")[1] or ""), True)
check("IPv6 is refused", bool(SH.parse_subnets("fd00::/120")[1]), True)
check("nonsense is refused, with the text quoted",
      "tower.local" in (SH.parse_subnets("tower.local")[1] or ""), True)

db.init()
db.set("scan_subnets", "")
with env(RIPARR_SCAN_SUBNETS=None), mock.patch.object(P, "_ip", return_value="172.17.0.5"):
    check("with nothing set, its own /24", SH.scan_subnets(), ("172.17.0.0/24", "local"))
with env(RIPARR_SCAN_SUBNETS="192.168.50.0/24"):
    check("RIPARR_SCAN_SUBNETS beats its own network",
          SH.scan_subnets(), ("192.168.50.0/24", "environment"))
    db.set("scan_subnets", "192.168.1.0/24")
    check("a saved setting beats the environment",
          SH.scan_subnets(), ("192.168.1.0/24", "setting"))
    check("and what the caller asked for beats everything",
          SH.scan_subnets("10.1.2.0/24"), ("10.1.2.0/24", "given"))
db.set("scan_subnets", "")

print("the update check")
check("0.5.1 is newer than 0.5.0", updater._newer("0.5.1", "0.5.0"), True)
check("0.10.0 is newer than 0.9.9, numerically", updater._newer("0.10.0", "0.9.9"), True)
check("equal is not newer", updater._newer("0.5.1", "0.5.1"), False)
check("0.5.0-server.2 is newer than 0.5.0-server.1",
      updater._newer("0.5.0-server.2", "0.5.0-server.1"), True)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def release(tag):
    return lambda *a, **k: _Resp(json.dumps({"tag_name": tag, "body": "notes",
                                             "html_url": "https://example"}).encode())


with mock.patch.object(updater, "__version__", "0.5.1"):
    with mock.patch.object(updater.urllib.request, "urlopen", release("v0.6.0")):
        r = updater.check()
        check("a newer release is reported", (r["status"], r["latest"]), ("update", "0.6.0"))
        check("and says how to update", bool(r.get("how")), True)
    with mock.patch.object(updater.urllib.request, "urlopen", release("v0.5.1")):
        check("the same release is current", updater.check()["status"], "current")

    def missing(*a, **k):
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)
    with mock.patch.object(updater.urllib.request, "urlopen", missing):
        check("no releases yet is not an error", updater.check()["status"], "no-releases")

    def offline(*a, **k):
        raise OSError("no route to host")
    with mock.patch.object(updater.urllib.request, "urlopen", offline):
        check("offline never raises", updater.check()["status"], "offline")
check("install never installs", updater.install()["ok"], False)


def release_with(body):
    return lambda *a, **k: _Resp(json.dumps({"tag_name": "v9.9.9", "body": body,
                                             "html_url": "https://example"}).encode())


with mock.patch.object(updater.urllib.request, "urlopen", release_with(
        "Notes.\n<!-- riparr-update: git stash && git pull -->\nMore notes.")):
    r = updater.check()
    check("a release can say how to update to it", r["how"], "git stash && git pull")
    check("and that line is left out of the notes shown", "riparr-update" in r["notes"], False)
    check("the rest of the notes are kept", ("Notes." in r["notes"], "More notes." in r["notes"]),
          (True, True))
with mock.patch.object(updater.urllib.request, "urlopen", release_with(
        "<!--   RIPARR-UPDATE:   git stash\n   && git pull   -->")):
    check("spacing and case don't matter, and it can wrap",
          updater.check()["how"], "git stash && git pull")
with mock.patch.object(updater.urllib.request, "urlopen", release_with("Just notes.")):
    check("without one, the built-in instruction is used",
          updater.check()["how"], updater.how_to_update())

print("which build this is")
import riparr  # noqa: E402
with env(RIPARR_CHANNEL="edge", RIPARR_COMMIT="def75c3a9b1e"):
    check("an edge image says so, with a short commit", riparr.build(),
          {"version": riparr.__version__, "channel": "edge", "commit": "def75c3"})
with env(RIPARR_CHANNEL="latest", RIPARR_COMMIT=""):
    check("a release image is latest", riparr.build()["channel"], "latest")
with mock.patch.dict(os.environ, {}, clear=False):
    os.environ.pop("RIPARR_CHANNEL", None)
    check("no image at all is a source checkout", riparr.build()["channel"], "dev")

print("why the library can't be written to")
_lib = tempfile.mkdtemp(prefix="riparr-lib-")
with mock.patch.object(P, "MOCK", False), mock.patch.object(P, "LIBRARY_MOUNT", _lib):
    check("a plain folder is not a mount", "Nothing is mounted" in (P.library_problem() or ""), True)
    with mock.patch.object(P.os.path, "ismount", return_value=True), \
            mock.patch.object(P.os, "access", return_value=False):
        msg = P.library_problem() or ""
        check("a mount Riparr can't write to says so, with the fix",
              ("can't write" in msg, "PUID/PGID" in msg), (True, True))
    with mock.patch.object(P.os.path, "ismount", return_value=True):
        check("a writable mount has no problem", P.library_problem(), None)

print("MakeMKV's SDF hang is worked around")
from riparr import makemkv as MKV  # noqa: E402
_home = tempfile.mkdtemp(prefix="riparr-home-")
_bin = os.path.join(_home, "makemkvcon")


def fake_makemkv(hang):
    # A stand-in makemkvcon: prints its start line, writes the debug log line naming
    # the drive, then either hangs (the bug) or lists drives like a working one.
    with open(_bin, "w") as f:
        f.write("#!/bin/sh\n"
                "echo 'MSG:1005,0,1,\"MakeMKV started\",\"\",\"\"'\n"
                "printf 'SDF auto v0a6: hp_TEST_DRIVE_123\\n' > \"$HOME/MakeMKV_log.txt\"\n"
                + ("sleep 30\n" if hang else "echo 'DRV:0,2,999,1,\"BD-ROM hp\",\"X\",\"/dev/sr0\"'\n"))
    os.chmod(_bin, 0o755)


with mock.patch.dict(os.environ, {"HOME": _home}), mock.patch.object(MKV.P, "MOCK", False), \
        mock.patch.object(MKV.shutil, "which", return_value=_bin), \
        mock.patch.object(MKV, "PROBE_SECONDS", 3):
    fake_makemkv(hang=False)
    MKV._probed.clear()
    check("a drive MakeMKV reads normally is left alone",
          (MKV.ensure_drive_ready("dev:/dev/sr0"), MKV.conf_value("sdf_Stop")), (None, None))
    fake_makemkv(hang=True)
    MKV._probed.clear()
    note = MKV.ensure_drive_ready("dev:/dev/sr0")
    check("a hang names the drive and sets sdf_Stop for it",
          (bool(note), MKV.conf_value("sdf_Stop")), (True, "hp_TEST_DRIVE_123"))
    check("and it's only probed once per drive", MKV.ensure_drive_ready("dev:/dev/sr0"), None)
check("drives are addressed by path, not MakeMKV's index",
      (RIP_disc := __import__("riparr.rip", fromlist=["x"])._disc_arg("/dev/sr1")), "dev:/dev/sr1")

print("the password reset file")
from riparr import main  # noqa: E402  (imported late: it reads RIPARR_DB at import)
db.create_user("admin", "a-test-password")
check("there is an account to reset", db.has_users(), True)
reset = os.path.join(_tmp, "riparr-reset")
open(reset, "w").close()
main._check_password_reset()
check("the reset file clears the account", db.has_users(), False)
check("and is consumed", os.path.exists(reset), False)
db.create_user("admin", "a-test-password")
main._check_password_reset()
check("with no file, nothing happens", db.has_users(), True)

print("the sign-in page knows the theme")
check("the default before anything is chosen", main.setup_state()["theme"], "servarr")
db.set("theme", "win98")
check("the chosen one after", main.setup_state()["theme"], "win98")
db.set("theme", "../../etc/passwd")
check("anything that isn't a plain name falls back", main.setup_state()["theme"], "servarr")
db.set("theme", "servarr")

print("the live log")
import logging  # noqa: E402
from riparr import system as SY  # noqa: E402
live = SY.LiveHandler()
live.setFormatter(logging.Formatter("%(message)s"))
lg = logging.getLogger("riparr.test-live")
lg.addHandler(live)
lg.setLevel(logging.DEBUG)
lg.info("first")
lg.debug("noisy")
lg.warning("second")
got = live.since(0)
check("every line, numbered", [(l["seq"], l["text"]) for l in got["lines"]],
      [(1, "first"), (2, "noisy"), (3, "second")])
check("only what's new after a given line", [l["text"] for l in live.since(2)["lines"]],
      ["second"])
check("debug can be left out", [l["text"] for l in
                                live.since(0, ("info", "warning"))["lines"]], ["first", "second"])
check("and the last number is reported even when nothing is new", live.since(3)["last"], 3)

print("diagnostics leave credentials out")
scrubbed = main._scrub({"makemkv_key": "T-abc", "tmdb_token": "x", "smtp_password": "p",
                        "discord_webhook": "https://discord/1", "movie_folder": "Movies",
                        "nested": [{"password": "q", "host": "nas"}], "empty_token": ""})
check("secrets are replaced", (scrubbed["makemkv_key"], scrubbed["tmdb_token"],
                               scrubbed["smtp_password"], scrubbed["discord_webhook"]),
      ("[redacted]",) * 4)
check("everything else is kept", (scrubbed["movie_folder"], scrubbed["nested"][0]["host"]),
      ("Movies", "nas"))
check("inside lists too", scrubbed["nested"][0]["password"], "[redacted]")

print("where a rip will be saved")
from riparr import rip as RIP  # noqa: E402
sid = db.add_share("NAS", "tower", "Media", "", "")
db.set("movie_folder", "Films")
db.set("movie_template", "{Title} ({Year})/{Title} ({Year}) {[Quality Full]}.mkv")
job = {"kind": "movie", "title": "Heat", "year": 1995, "disc_family": "bluray",
       "chosen_title": 0, "titles": [{"index": 0, "streams": [
           {"type": "Video", "codec_short": "Mpeg4", "video_size": "1920x1080"}]}]}
check("a film", RIP.planned_destination(job),
      {"path": "//tower/Media/Films/Heat (1995)/Heat (1995) [Remux-1080p].mkv",
       "count": 1, "kind": "movie"})
check("nothing until there's a name", RIP.planned_destination(dict(job, title=None)), None)

print("the rip that just finished")
import time  # noqa: E402
now = int(time.time())
for state, ago in (("done", 600), ("cancelled", 60), ("failed", 7200)):
    jid = db.create_job(title="Heat", disc_label="HEAT", kind="movie", fingerprint="",
                        state=state, phase=None, mode=None, bytes_total=1)
    db.update_job(jid, finished_at=now - ago)
got = db.last_finished(now - 3600)
check("the newest done or failed job, skipping cancelled",
      (got or {}).get("state"), "done")
check("nothing older than asked for", db.last_finished(now - 300), None)

print("an already-ripped disc in the tray")
db.record_disc("fp-heat", label="HEAT", size_bytes=4096, title="Heat", year=1995,
               ripped_at=now)
known = main._known_disc({"label": "HEAT", "size_bytes": 4096})
check("is recognised before Rip is pressed, with its year",
      (known or {}).get("title"), "Heat")
check("and the year comes with it", (known or {}).get("year"), 1995)
check("a disc we don't have isn't", main._known_disc({"label": "ALIEN", "size_bytes": 1}),
      None)

print("answering a disc from a notification")
from riparr import notify as NT  # noqa: E402


class _Req:  # the two things the answer endpoint reads off a request
    def __init__(self, accept=""):
        self.headers = {"accept": accept}


db.set("seen_url", "")


class _Base:
    base_url = "http://10.0.0.5:8080/"


main.status(_Base(), user="admin")
check("a page load by somebody already signed in records the address",
      db.get("seen_url"), "http://10.0.0.5:8080")
_Base.base_url = "http://other:1/"
main.status(_Base(), user="admin")
check("once, not on every poll", db.get("seen_url"), "http://10.0.0.5:8080")

db.set("public_url", "")
db.set("seen_url", "http://10.0.0.5:8080")
db.set("session_secret", "")
check("no secret, no buttons -- never signed with an empty key",
      NT.answer_action(1, "X", {}), None)
main._secret()                       # as startup does
db.set("seen_url", "")
check("no address known, no buttons", NT.actions(NT.answer_action(1, "X", {}), NT.open_action()), [])
db.set("seen_url", "http://10.0.0.5:8080")
check("the address you signed in at is the fallback", NT.public_url(), "http://10.0.0.5:8080")
db.set("public_url", "https://riparr.example.com/")
check("one set on Connect wins, without its trailing slash", NT.public_url(),
      "https://riparr.example.com")
db.set("public_url", "file:///etc/passwd")
check("an address that isn't http(s) gives no buttons", NT.public_url(), "")
db.set("public_url", "")

jid = db.create_job(title=None, disc_label="THE_THING", kind="movie", fingerprint="",
                    state="needs_input", question="TMDb isn't sure which film.",
                    phase="Waiting for you", mode=None, bytes_total=1)
picks = RIP._film_buttons(jid, [{"id": 1091, "title": "The Thing", "year": 1982, "votes": 7000},
                                {"id": 60935, "title": "The Thing", "year": 2011, "votes": 3000},
                                {"id": 9, "title": "The Thing", "year": 1951, "votes": 500}])
check("the two best-known films, then Open",
      [a["label"] for a in picks], ["The Thing (1982)", "The Thing (2011)", "Open Riparr"])
token = picks[0]["url"].rsplit("/", 1)[1]
check("a button carries its own answer", NT.read_answer(token),
      {"job": jid, "answer": {"tmdb_id": 1091}, "label": "The Thing (1982)"})
check("a tampered one is refused", "error" in NT.read_answer(token[:-3] + "abc"), True)
forged = NT._signer().dumps({"j": jid, "a": {"skip": True}})
check("and so is an answer a button can't give", "error" in NT.read_answer(forged), True)
saved = NT.ANSWER_MAX_AGE
NT.ANSWER_MAX_AGE = -1
check("an old one has expired", "expired" in NT.read_answer(token).get("error", ""), True)
NT.ANSWER_MAX_AGE = saved

msg = NT.ntfy_message("topic", "needs_you", "THE_THING", "Which?", picks)
check("ntfy gets buttons that answer from the phone",
      msg["actions"][0], {"action": "http", "label": "The Thing (1982)",
                          "url": picks[0]["url"], "method": "POST", "clear": True})
check("and one that opens Riparr", msg["actions"][2]["action"], "view")
check("tapping the notification opens Riparr too", msg["click"], picks[2]["url"])
check("Discord gets links", "[The Thing (2011)](" in NT.discord_links(picks), True)

page = main.answer_page(token)
check("following the link only asks", (page.status_code, db.get_job(jid)["state"]),
      (200, "needs_input"))
check("with the choice on the button", b"Rip as The Thing (1982)</button>" in page.body, True)
got = main.answer_from_notification(token, _Req())
check("the button answers it", (got["ok"], db.get_job(jid)["tmdb_id"], db.get_job(jid)["state"]),
      (True, 1091, "queued"))
try:
    main.answer_from_notification(token, _Req())
    again = None
except main.HTTPException as e:
    again = e.status_code
check("a second tap is refused", again, 409)
check("and the page says so", b"already been answered" in main.answer_page(token).body, True)

db.set("seen_url", "")
check("a season disc with no season gets only Open",
      len(RIP._season_buttons(jid, {"season": None}, False)), 0)
db.set("seen_url", "http://10.0.0.5:8080")
check("…which is there when the address is known",
      [a["kind"] for a in RIP._season_buttons(jid, {"season": None}, False)], ["open"])
check("a sure one can be ripped as it is",
      [a["label"] for a in RIP._season_buttons(jid, {"season": 2}, False)],
      ["Looks right, rip it", "Open Riparr"])
check("an unsure one offers the shows",
      [a["label"] for a in RIP._season_buttons(jid, {"season": 2, "series_options": [
          {"id": 526, "name": "The Office", "year": 2005},
          {"id": 2996, "name": "The Office", "year": 2001}]}, True)],
      ["The Office (2005)", "The Office (2001)", "Open Riparr"])

print()
if failures:
    print("%d check(s) failed: %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("all good")
