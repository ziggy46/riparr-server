#!/usr/bin/env python3
"""Audio CDs, end to end, through the real pipeline.

A CD is the one disc that isn't a film: no MakeMKV, no titles, no label -- just a track
layout that MusicBrainz turns into an album, and a folder of FLAC tracks at the end.
Everything here runs against the mock drive and the mock share; only MusicBrainz is
stood in for, so the tests don't depend on what's in its database today.

Run: python3 server/music-pipeline.test.py
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_tmp = tempfile.mkdtemp(prefix="riparr-music-test-")
os.environ["RIPARR_DB"] = os.path.join(_tmp, "test.db")
os.environ["RIPARR_STAGING"] = os.path.join(_tmp, "staging")
os.environ["RIPARR_APPLIANCE"] = "0"
os.environ["RIPARR_MOCK_FAST"] = "1"
os.environ["RIPARR_MOCK_DISC"] = "cd"
_MOCK_SHARE = "/tmp/riparr-mock-share"
os.environ["RIPARR_LIBRARY_MOUNT"] = os.path.join(_MOCK_SHARE, "nas", "Media")

from riparr import db, music as MU, musicbrainz as MB, notify, optical as OPT  # noqa: E402
from riparr import platform as P, rip, shares as SH  # noqa: E402

failures = []


def check(name, got, want):
    if got == want:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s: got %r, wanted %r" % (name, got, want))
        failures.append(name)


# ── MusicBrainz, stood in for ──
RELEASES = {}


def album(rid, title, artist, year, n, disc=1, discs=1):
    RELEASES[rid] = {"id": rid, "title": title, "artist": artist, "date": str(year),
                     "year": year, "country": "GB", "disc": disc, "discs": discs,
                     "format": "CD", "track_count": n,
                     "tracks": [{"number": i + 1, "title": "Song %d" % (i + 1),
                                 "artist": artist, "seconds": 200,
                                 "recording_id": "rec-%s-%d" % (rid, i),
                                 "track_id": "trk-%s-%d" % (rid, i)} for i in range(n)]}
    return RELEASES[rid]


answers = {}
MB.lookup = lambda disc, toc=None: answers.get(disc, [])
MB.get_release = lambda rid, disc=None: RELEASES.get(rid)
MB.cover = lambda rid, size=500: b"\xff\xd8\xff" + b"jpeg" * 100 if rid else None
sent = []
notify.send = lambda event, title="", body="", force=False, actions=None: sent.append(
    (event, [a["label"] for a in actions or []]))


def toc(starts, leadout):
    return {"first": 1, "last": len(starts), "leadout": leadout,
            "tracks": [{"number": i + 1, "lba": s, "audio": True}
                       for i, s in enumerate(starts)]}


def insert(starts, leadout=None):
    """Put a CD with these track starts in the mock drive; returns its disc ID."""
    leadout = leadout or starts[-1] + 15000
    P._MOCK_DISCS["cd"].update(toc=toc(starts, leadout), audio_tracks=len(starts))
    return MB.disc_id(*OPT.audio_session(P._MOCK_DISCS["cd"]["toc"]))


def run_disc():
    job_id, why = rip.enqueue()
    if not job_id:
        return None, why
    rip._run_job(db.get_job(job_id))
    j = db.get_job(job_id)
    if j["state"] == "transferring":
        rip._send_one(j)
    return db.get_job(job_id), None


def library(under="nas/Media/Music"):
    out = []
    base = os.path.join(SH.MOCK_SHARE_ROOT, under)
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != ".riparr-incoming"]
        out += [os.path.relpath(os.path.join(root, f), base) for f in files]
    return sorted(out)


shutil.rmtree(SH.MOCK_SHARE_ROOT, ignore_errors=True)
os.makedirs(os.environ["RIPARR_LIBRARY_MOUNT"], exist_ok=True)
os.makedirs(P.STAGING, exist_ok=True)
db.init()
db.set("setup_complete", True)
db.set("session_secret", "a" * 64)      # made at startup; signs notification buttons
db.set("transfer_mode", "burst")
db.set("verify_mode", "quick")
db.add_share("Media", "nas", "Media", None, None, make_default=True)

print("a CD is named by its track layout")
check("MusicBrainz's own example", MB.disc_id(1, 6, 95312, [0, 15213, 32164, 46442, 63264, 80339]),
      "49HHV7Eb8UKF3aQiNmu1GR8vKTY-")
enhanced = {"first": 1, "last": 3, "leadout": 90000, "tracks": [
    {"number": 1, "lba": 0, "audio": True}, {"number": 2, "lba": 20000, "audio": True},
    {"number": 3, "lba": 60000, "audio": False}]}
check("an enhanced CD's music ends 11400 sectors before its data track",
      OPT.audio_session(enhanced), (1, 2, 48600, [0, 20000]))
check("a data CD has no music", OPT.audio_session({"first": 1, "last": 1, "leadout": 5000,
      "tracks": [{"number": 1, "lba": 0, "audio": False}]}), None)
check("track lengths come from the layout", MB.track_seconds(150 + 7500, [150, 150 + 4500]),
      [60, 40])

print("tags are the ones Picard and Plex read")
plan = {"artist": "Fleetwood Mac", "album": "Rumours", "year": 1977, "date": "1977-02-04",
        "disc": 1, "discs": 1, "release_id": "rel", "disc_id": "id", "tracks": [{}] * 11}
t = MU.tags(plan, {"number": 3, "title": "Never Going Back Again", "artist": "Fleetwood Mac",
                   "recording_id": "rec"})
check("title, number, album artist", (t["TITLE"], t["TRACKNUMBER"], t["TRACKTOTAL"],
                                      t["ALBUMARTIST"]),
      ("Never Going Back Again", "3", "11", "Fleetwood Mac"))
check("and MusicBrainz's IDs", (t["MUSICBRAINZ_ALBUMID"], t["MUSICBRAINZ_TRACKID"],
                                t["MUSICBRAINZ_DISCID"]), ("rel", "rec", "id"))

print("an album MusicBrainz knows")
disc = insert([0, 15000, 30000])
answers[disc] = [album("rel-a", "Blue Skies", "The Mockers", 1999, 3)]
j, _ = run_disc()
check("ripped and filed", j["state"], "done")
check("as the album, by its artist, track by track, with the cover", library(),
      ["The Mockers/Blue Skies (1999)/01 - Song 1.flac",
       "The Mockers/Blue Skies (1999)/02 - Song 2.flac",
       "The Mockers/Blue Skies (1999)/03 - Song 3.flac",
       "The Mockers/Blue Skies (1999)/cover.jpg"])
check("named after the album", (j["title"], j["year"], j["kind"], j["disc_family"]),
      ("Blue Skies", 1999, "music", "cd"))
check("checked file by file", j["verified_mode"], "quick")
check("and gone from staging", (j["local_path"], os.listdir(P.STAGING)), (None, []))
check("the CD is remembered by its disc ID", db.get_disc("cd:" + disc)["release_id"], "rel-a")
again, why = rip.enqueue()
check("so putting it back in is refused as already ripped",
      (again, "already ripped" in (why or "")), (None, True))

print("two albums share this CD")
disc = insert([0, 12000])
answers[disc] = [album("rel-b", "Greatest Hits", "Band One", 2001, 2),
                 album("rel-c", "Live at Home", "Band Two", 2005, 2)]
sent.clear()
db.set("public_url", "http://riparr.local:9797")
j, _ = run_disc()
check("it asks which", j["state"], "needs_input")
check("and the notification has a button for each",
      [s for s in sent if s[0] == "needs_you"],
      [("needs_you", ["Greatest Hits (2001) by Band One", "Live at Home (2005) by Band Two",
                      "Open Riparr"])])
check("offering both", [c["id"] for c in __import__("json").loads(j["candidates"])],
      ["rel-b", "rel-c"])
ok, msg = rip.answer(j["id"], release_id="rel-c")
check("answering with one", ok, True)
rip._run_job(db.get_job(j["id"]))
j = db.get_job(j["id"])
if j["state"] == "transferring":
    rip._send_one(j)
    j = db.get_job(j["id"])
check("rips it as that album", (j["state"], j["title"]), ("done", "Live at Home"))
check("into that album's folder", "Band Two/Live at Home (2005)/01 - Song 1.flac" in library(),
      True)

print("a CD MusicBrainz doesn't know")
disc = insert([0, 9000, 18000, 27000])
j, _ = run_disc()
check("it asks", (j["state"], "doesn't know" in j["question"]), ("needs_input", True))
ok, _ = rip.answer(j["id"], artist="Garage Tapes", album="Demo (2024)")
rip._run_job(db.get_job(j["id"]))
j = db.get_job(j["id"])
if j["state"] == "transferring":
    rip._send_one(j)
    j = db.get_job(j["id"])
check("and rips it with the names given", (j["state"], j["title"], j["year"]),
      ("done", "Demo", 2024))
check("with numbered tracks where nobody has names",
      [f for f in library() if f.startswith("Garage Tapes/")],
      ["Garage Tapes/Demo (2024)/%02d - Track %02d.flac" % (n, n) for n in range(1, 5)])

print("disc 2 of a set joins disc 1")
d1 = insert([0, 10000])
answers[d1] = [album("rel-set", "Anthology", "The Set", 2010, 2, disc=1, discs=2)]
run_disc()
d2 = insert([0, 11000, 22000])
set2 = dict(album("rel-set", "Anthology", "The Set", 2010, 3, disc=2, discs=2))
answers[d2] = [set2]
j, _ = run_disc()
check("filed", j["state"], "done")
names = [os.path.basename(f) for f in library() if f.startswith("The Set/Anthology (2010)/")]
check("in the same album folder, numbered by disc so the set sorts in order",
      sorted(n for n in names if n.endswith(".flac")),
      ["1-01 - Song 1.flac", "1-02 - Song 2.flac", "2-01 - Song 1.flac", "2-02 - Song 2.flac",
       "2-03 - Song 3.flac"])

print("a different album with the same name")
disc = insert([0, 13000])
answers[disc] = [album("rel-other", "Blue Skies", "The Mockers", 1999, 2)]
j, _ = run_disc()
check("goes beside it, not into it", "The Mockers/Blue Skies (1999) (2)/01 - Song 1.flac"
      in library(), True)
check("and says so", "different album" in (j["warning"] or ""), True)

print("discs that can't be ripped as music")
P._MOCK_DISCS["cd"].update(audio_tracks=0)
check("a data CD is refused", "data CD" in (rip.unreadable_reason(rip.drive_for()) or ""), True)
P._MOCK_DISCS["cd"].update(audio_tracks=2)
real = MU.tools
MU.tools = lambda: {"cdparanoia": None, "flac": "/usr/bin/flac", "ready": False}
check("and without cdparanoia, the reason is said",
      "needs cdparanoia" in (rip.unreadable_reason(rip.drive_for()) or ""), True)
MU.tools = real

print("the drive's direct mode files straight into the library")
db.set("transfer_mode", "direct")
disc = insert([0, 14000])
answers[disc] = [album("rel-d", "Direct Hits", "The Mockers", 2020, 2)]
j, _ = run_disc()
check("filed", j["state"], "done")
check("in the album folder", "The Mockers/Direct Hits (2020)/02 - Song 2.flac" in library(), True)

print()
if failures:
    print("%d check(s) failed: %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("all good")
