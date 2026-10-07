"""
Ripping audio CDs: cdparanoia reads each track, flac encodes it.

A CD is the one disc Riparr reads without MakeMKV. cdparanoia is the standard careful
reader -- it re-reads and checks what it gets, and corrects the jitter and scratches a
plain copy would let through -- and it says when it couldn't, which is passed on. FLAC
is lossless, tags each track with what MusicBrainz knows about it, and carries the
front cover inside the file.

The album lands as Plex, Jellyfin and Plexamp file music:

    Music/Fleetwood Mac/Rumours (1977)/01 - Second Hand News.flac
                                       ...
                                       cover.jpg

and the discs of a set share one album folder, as 1-01, 1-02... 2-01, 2-02, so the
whole set sorts in order.
"""
import os
import shutil
import subprocess
import threading

from . import naming, platform as P

SECTOR = 2352                 # bytes of audio in one CD sector
WAV_HEADER = 44


def tools():
    """Whether this box can rip a CD: {"cdparanoia", "flac", "ready"}."""
    cdp = shutil.which("cdparanoia")
    flac = shutil.which("flac")
    return {"cdparanoia": cdp, "flac": flac, "ready": bool(P.MOCK or (cdp and flac))}


def missing_tools_reason():
    t = tools()
    if t["ready"]:
        return None
    need = [n for n in ("cdparanoia", "flac") if not t[n]]
    return ("Ripping audio CDs needs %s, which this install doesn't have. Update Riparr "
            "-- the image and the installer include them from 0.10.0." % " and ".join(need))


# ─────────────────────────────── names ───────────────────────────────

def album_folder(music):
    """'Fleetwood Mac/Rumours (1977)' -- the album artist's folder, then the album's."""
    artist = naming.sanitise(music.get("artist") or "Unknown Artist") or "Unknown Artist"
    album = naming.sanitise(music.get("album") or "Unknown Album") or "Unknown Album"
    year = music.get("year")
    return "%s/%s" % (artist, "%s (%s)" % (album, year) if year else album)


def track_file(music, track):
    """'01 - Title.flac', or '2-01 - Title.flac' on disc 2 of a set, so a whole set sorts
    in order in one folder."""
    title = naming.sanitise(track.get("title") or "") or "Track %02d" % track["number"]
    prefix = ("%d-%02d" % (music.get("disc") or 1, track["number"])
              if (music.get("discs") or 1) > 1 else "%02d" % track["number"])
    return "%s - %s.flac" % (prefix, title)


def tags(music, track):
    """Vorbis comments for one track, named the way Picard, Plex and beets read them."""
    out = {
        "TITLE": track.get("title") or "Track %d" % track["number"],
        "ARTIST": track.get("artist") or music.get("artist") or "Unknown Artist",
        "ALBUMARTIST": music.get("artist") or "Unknown Artist",
        "ALBUM": music.get("album") or "Unknown Album",
        "TRACKNUMBER": str(track["number"]),
        "TRACKTOTAL": str(len(music.get("tracks") or [])),
        "DISCNUMBER": str(music.get("disc") or 1),
        "DISCTOTAL": str(music.get("discs") or 1),
        "DATE": music.get("date") or (str(music["year"]) if music.get("year") else ""),
        "MUSICBRAINZ_ALBUMID": music.get("release_id") or "",
        "MUSICBRAINZ_TRACKID": track.get("recording_id") or "",
        "MUSICBRAINZ_RELEASETRACKID": track.get("track_id") or "",
        "MUSICBRAINZ_DISCID": music.get("disc_id") or "",
    }
    return {k: v for k, v in out.items() if v}


# ─────────────────────────────── reading and encoding ───────────────────────────────

class TrackFailed(Exception):
    pass


def rip_track(device, number, wav_path, expected_bytes, cancel_ev, on_bytes=None):
    """Read one track to a WAV with cdparanoia. Returns how many times it had to give
    up on part of the track (0 is a clean read) -- an imperfect read is still a usable
    track, and the user is told which ones they were."""
    if P.MOCK:
        return _mock_track(wav_path, expected_bytes, cancel_ev, on_bytes)
    log_path = wav_path + ".log"
    with open(log_path, "w") as err:
        # -e: progress as lines, which is what says where it skipped. -w: WAV out.
        proc = subprocess.Popen(["cdparanoia", "-e", "-w", "-d", device, "--",
                                 str(number), wav_path],
                                stdout=subprocess.DEVNULL, stderr=err)
        while proc.poll() is None:
            if cancel_ev.wait(1):
                proc.terminate()
                proc.wait()
                raise TrackFailed("cancelled")
            if on_bytes:
                try:
                    on_bytes(os.path.getsize(wav_path))
                except OSError:
                    pass
    try:
        with open(log_path, errors="replace") as f:
            text = f.read()
    except OSError:
        text = ""
    try:
        os.remove(log_path)
    except OSError:
        pass
    if proc.returncode != 0 or not os.path.exists(wav_path):
        last = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("##")]
        raise TrackFailed("cdparanoia couldn't read track %d%s" % (
            number, ": %s" % last[-1].strip() if last else ""))
    return text.count("[skip]")


def encode(wav_path, flac_path, track_tags, cover_path=None):
    """WAV to FLAC, tagged, with the cover inside. The WAV is removed afterwards."""
    os.makedirs(os.path.dirname(flac_path), exist_ok=True)
    if P.MOCK:
        with open(wav_path, "rb") as src, open(flac_path, "wb") as dst:
            dst.write(b"fLaC")
            shutil.copyfileobj(src, dst)
        os.remove(wav_path)
        return
    cmd = ["flac", "--silent", "--force", "-5", "-o", flac_path]
    for k, v in track_tags.items():
        cmd.append("--tag=%s=%s" % (k, v))
    if cover_path and os.path.exists(cover_path):
        cmd.append("--picture=%s" % cover_path)
    cmd.append(wav_path)
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise TrackFailed("flac couldn't encode %s: %s" % (
            os.path.basename(flac_path), (p.stderr or p.stdout).strip()[-300:]))
    os.remove(wav_path)


def _mock_track(wav_path, expected_bytes, cancel_ev, on_bytes):
    """A believable, small track: real bytes, written over a moment."""
    size = min(expected_bytes or 0, 256 * 1024) or 64 * 1024
    fast = os.environ.get("RIPARR_MOCK_FAST")
    with open(wav_path, "wb") as f:
        for i in range(4):
            if cancel_ev.is_set():
                raise TrackFailed("cancelled")
            f.write(os.urandom(size // 4))
            f.flush()
            if on_bytes:
                on_bytes(f.tell())
            if not fast:
                cancel_ev.wait(0.3)
    return 0


class Encoder:
    """Encodes the last track while the next one is being read: the drive is the slow
    part, so the CPU work happens in its shadow."""

    def __init__(self):
        self._thread = None
        self.error = None

    def submit(self, *args):
        self.wait()
        self._thread = threading.Thread(target=self._run, args=args,
                                        name="riparr-flac", daemon=True)
        self._thread.start()

    def _run(self, *args):
        try:
            encode(*args)
        except Exception as e:
            self.error = e

    def wait(self):
        if self._thread:
            self._thread.join()
            self._thread = None
        if self.error:
            e, self.error = self.error, None
            raise e
