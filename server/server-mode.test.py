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

print()
if failures:
    print("%d check(s) failed: %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("all good")
