#!/usr/bin/env python3
"""Two drives, two discs, ripping at once, through the real engine.

Everything here used to assume one drive: one worker, one "is the drive busy", one
eject that always opened /dev/sr0. With two, each disc has to be read from its own
tray, ripped alongside the other, given back from its own tray, and kept out of the
other's way -- including the staging space they share.

Nothing is stubbed except the hardware, as everywhere else in this repository.

Run: python3 server/multi-drive.test.py
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_tmp = tempfile.mkdtemp(prefix="riparr-multi-test-")
os.environ["RIPARR_DB"] = os.path.join(_tmp, "test.db")
os.environ["RIPARR_STAGING"] = os.path.join(_tmp, "staging")
os.environ["RIPARR_MOCK_CONTENT"] = "movie"
os.environ["RIPARR_APPLIANCE"] = "0"
os.environ["RIPARR_MOCK_FAST"] = "1"
os.environ["RIPARR_MOCK_DRIVES"] = "2"
os.environ["RIPARR_MOCK_DISC"] = "bluray"
os.environ["RIPARR_MOCK_LABEL"] = "THE_MATRIX"
os.environ["RIPARR_MOCK_DISC2"] = "dvd"
os.environ["RIPARR_MOCK_LABEL2"] = "ARRIVAL"

from riparr import db, platform as P, rip, shares as SH  # noqa: E402

for _d in P._MOCK_DISCS.values():
    _d["size_bytes"] = 64 * 2 ** 20

failures = []


def check(name, got, want):
    if got == want:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s: got %r, wanted %r" % (name, got, want))
        failures.append(name)


ejected = []
P.eject = lambda device="/dev/sr0": ejected.append(device) or {"ok": True}

shutil.rmtree(SH.MOCK_SHARE_ROOT, ignore_errors=True)
os.makedirs(P.STAGING, exist_ok=True)
db.init()
db.set("setup_complete", True)
db.set("transfer_mode", "burst")
db.set("verify_mode", "deep")
db.set("on_unknown_disc", "label")
db.add_share("Media", "nas", "Media", None, None, make_default=True)

print("each drive is its own")
drives = P.optical_drives()
check("two drives, each with its own disc",
      [(d["device"], d["label"]) for d in drives],
      [("/dev/sr0", "THE_MATRIX"), ("/dev/sr1", "ARRIVAL")])
check("a drive is found by its path", rip.drive_for("/dev/sr1")["label"], "ARRIVAL")
check("and a path no drive has finds nothing", rip.drive_for("/dev/sr9"), None)

print("each disc is queued on its own drive")
a, why = rip.enqueue(device="/dev/sr1")
check("the second drive's disc is queued", (bool(a), why), (True, None))
check("on that drive", db.get_job(a)["device"], "/dev/sr1")
check("which is busy now", bool(db.drive_busy("/dev/sr1")), True)
check("and the other isn't", db.drive_busy("/dev/sr0"), None)
again, why = rip.enqueue(device="/dev/sr1")
check("the same drive can't be queued twice", (again, "already working" in why),
      (None, True))
b, why = rip.enqueue()
check("without a drive named, the free one is used",
      (bool(b), db.get_job(b)["device"]), (True, "/dev/sr0"))
check("both drives are held", db.busy_devices(), ["/dev/sr0", "/dev/sr1"])

slow = rip._drive_lock("/dev/sr1")
slow.acquire()                       # a slow check (a 4K disc's probe) on the second drive
other = rip._drive_lock("/dev/sr0").acquire(timeout=0.2)
check("one drive's slow claim doesn't hold up the other", other, True)
rip._drive_lock("/dev/sr0").release()
slow.release()

print("staging is shared fairly")
db.update_job(a, mode="burst", state="ripping", bytes_total=10 * 2 ** 30, bytes_ripped=2 ** 30)
check("a rip still writing holds what it hasn't written yet",
      rip._reserved_staging(job_id=b), 9 * 2 ** 30)
check("but not against itself", rip._reserved_staging(job_id=a), 0)
# 20 GB free: room for either disc, not both.
rip._staging_free = lambda: 20 * 2 ** 30
rip.purge_staging = lambda need_bytes=0, keep_newest=0: (0, [])
mode, refusal = rip._plan_transfer(8 * 2 ** 30, job_id=b)
check("on its own, the space check says a second rip won't fit beside the first",
      (mode, "free in staging" in (refusal or "")), (None, True))
check("and one that fits beside it isn't", rip._plan_transfer(4 * 2 ** 30, job_id=b),
      ("burst", None))

import threading  # noqa: E402


def staged_by_a():
    """What A has on the disk: what it's written so far, until its file leaves staging."""
    j = db.get_job(a)
    if j["state"] in ("ripping", "transferring", "verifying") or j.get("local_path"):
        return int(j.get("bytes_ripped") or 0)
    return 0


# 20 GB of disk, less whatever A has written: the free space a real disk would report.
rip._staging_free = lambda: 20 * 2 ** 30 - staged_by_a()
db.update_job(a, mode="burst", state="ripping", bytes_total=10 * 2 ** 30, bytes_ripped=0)
got = {}
waiter = threading.Thread(target=lambda: got.update(
    mode=rip._plan_or_wait(dict(db.get_job(b), bytes_total=8 * 2 ** 30), threading.Event())))
waiter.start()
time.sleep(1)
check("instead, it waits for the other drive's rip", (waiter.is_alive(), db.get_job(b)["phase"]),
      (True, rip.WAIT_FOR_ROOM))
# A finishes writing: its whole file is on the disk now, waiting to be uploaded.
db.update_job(a, bytes_ripped=10 * 2 ** 30, state="transferring",
              local_path="/staging/job-a/film.mkv")
time.sleep(7)
check("and keeps waiting while that rip's file is still in staging", waiter.is_alive(), True)
# A is uploaded and its staged copy is gone.
db.update_job(a, state="done", local_path=None)
waiter.join(timeout=15)
check("then starts once that file has left staging", got.get("mode"), "burst")
db.update_job(a, state="ripping", bytes_ripped=0, local_path=None)
try:
    rip._plan_or_wait(dict(db.get_job(b), bytes_total=30 * 2 ** 30), threading.Event())
    refused = None
except rip.RipFailed as e:
    refused = str(e)
check("a disc that wouldn't fit even then is refused straight away",
      "free in staging" in (refused or ""), True)
db.update_job(a, mode=None, state="queued", bytes_total=64 * 2 ** 20, bytes_ripped=0)
db.update_job(b, mode=None, phase="Waiting to start")
rip._staging_free = lambda: 100 * 2 ** 30

print("both rip at once")
spans = {}
_real_rip = rip._rip


def _timed_rip(job, s, cancel_ev):
    start = time.time()
    try:
        time.sleep(0.5)                  # a fast mock rip is over before the other starts
        return _real_rip(job, s, cancel_ev)
    finally:
        spans[job["id"]] = (start, time.time())


rip._rip = _timed_rip
rip.start()
deadline = time.time() + 120
while time.time() < deadline:
    states = [db.get_job(j)["state"] for j in (a, b)]
    if all(st in db.FINAL_STATES for st in states):
        break
    time.sleep(0.05)
(a0, a1), (b0, b1) = spans.get(a, (0, 0)), spans.get(b, (0, 0))
print("       rips: %.2fs and %.2fs, overlapping %.2fs"
      % (a1 - a0, b1 - b0, max(0, min(a1, b1) - max(a0, b0))))
check("two rips ran at the same time", max(a0, b0) < min(a1, b1), True)
check("both finished", [db.get_job(j)["state"] for j in (a, b)], ["done", "done"])
for j in (a, b):
    if db.get_job(j)["state"] != "done":
        print("       job %d: %s" % (j, db.get_job(j)["error"]))
check("each disc came out of its own tray", sorted(ejected), ["/dev/sr0", "/dev/sr1"])
films = sorted(os.listdir(os.path.join(SH.MOCK_SHARE_ROOT, "nas", "Media", "Movies")))
check("and both films are in the library", len(films), 2)
check("their staged copies are gone once verified",
      ([db.get_job(j)["local_path"] for j in (a, b)], sorted(os.listdir(P.STAGING))), ([None, None], []))
check("and the checksum is kept for History",
      [len(db.get_job(j)["sha256"] or "") for j in (a, b)], [64, 64])

print("what each drive did is kept apart")
check("the last rip from each drive", (db.last_finished(0, device="/dev/sr1")["id"],
                                       db.last_finished(0, device="/dev/sr0")["id"]), (a, b))
check("MakeMKV's commentary is kept per drive",
      all(x["text"] for x in rip.makemkv_recent(device="/dev/sr1")), True)
check("disc details are per drive", rip.disc_details("/dev/sr1")["drive"]["label"], "ARRIVAL")
check("and say which drive", rip.disc_details("/dev/sr0")["device"], "/dev/sr0")

print("a job from before there were two drives")
old = db.create_job(state="ripping", disc_label="OLD", kind="movie", fingerprint="fp-old")
check("holds every drive, since it can't be told apart",
      (bool(db.drive_busy("/dev/sr0")), bool(db.drive_busy("/dev/sr1"))), (True, True))
check("and its eject goes to the first drive", rip.device_of(db.get_job(old)), "/dev/sr0")
db.update_job(old, state="failed", finished_at=int(time.time()) + 60)
check("it's the first drive's last rip", db.last_finished(0, device="/dev/sr0")["id"], old)
check("and not the second's", db.last_finished(0, device="/dev/sr1", legacy=False)["id"], a)
rip.stop()

print()
if failures:
    print("%d check(s) failed: %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("all good")
