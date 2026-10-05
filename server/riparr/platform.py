"""
Everything that differs between the appliance and a development Mac.

The rest of the codebase talks to this module and never shells out directly, so the
whole app runs on a laptop with realistic fake data and runs unchanged on the Pi.
`IS_APPLIANCE` is the only switch.
"""
import datetime
import os
import platform as _p
import re
import shutil
import socket
import subprocess
import threading
import time

from . import drives as DRV, optical as OPT

def _is_appliance():
    """Are we running against real hardware, or on a development machine?

    Upstream keyed this off /proc/device-tree/model, which every ARM board has and no
    x86 server, VM, container or LXC does. On the hardware this fork targets, that
    check fails silently: the service comes up in MOCK mode, finds a fabricated disc in
    a fabricated drive, and the interface looks entirely correct while the real drive
    is never touched.

    So the rule here is the other way round. Linux is real hardware unless told
    otherwise; anything else (a Mac, Windows) can only be a development machine.
    RIPARR_MOCK=1 asks for mock mode on Linux, and RIPARR_APPLIANCE still overrides
    either way.
    """
    env = os.environ.get("RIPARR_APPLIANCE")
    if env is not None:
        return env not in ("", "0", "no", "false")
    if os.environ.get("RIPARR_MOCK", "") not in ("", "0", "no", "false"):
        return False
    return _p.system() == "Linux"


IS_APPLIANCE = _is_appliance()
MOCK = not IS_APPLIANCE


def hostname():
    return socket.gethostname().split(".")[0]


# ─────────────────────────────── system ───────────────────────────────

def runtime():
    """Where this process is running: "docker", "lxc", or "host".

    Shown in the interface, and used to word advice about passing a drive through.
    RIPARR_RUNTIME overrides the guess.
    """
    env = os.environ.get("RIPARR_RUNTIME")
    if env:
        return env
    if os.path.exists("/.dockerenv"):
        return "docker"
    marker = _read("/run/systemd/container").strip() or os.environ.get("container", "")
    if marker:
        return "lxc" if "lxc" in marker else marker
    if "lxc" in _read("/proc/1/environ"):
        return "lxc"
    return "host"


def _memory_mb():
    """(total, used) in MB -- the container's limit when it has one, else the machine's.

    /proc/meminfo inside a container reports the whole host unless something like lxcfs
    is in front of it, so a cgroup v2 limit, when set, is the more honest number.
    """
    limit = _read("/sys/fs/cgroup/memory.max").strip()
    current = _read("/sys/fs/cgroup/memory.current").strip()
    if limit.isdigit() and current.isdigit():
        return int(limit) // 2**20, int(current) // 2**20
    mem = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        mem[k] = int(v.strip().split()[0]) if v.strip().split() else 0
    total = mem.get("MemTotal", 0) // 1024
    avail = mem.get("MemAvailable", 0) // 1024
    return total, total - avail


def system_status():
    if MOCK:
        return {
            "model": "Development machine (simulated)",
            "runtime": "docker",
            "os": "Debian GNU/Linux 13 (trixie)",
            "kernel": "6.8.12-pve",
            "uptime_seconds": 48213,
            "memory_total_mb": 2048,
            "memory_used_mb": 214,
            "cpu_temp_c": None,
            "throttled": False,
            "mock": True,
        }
    total, used = _memory_mb()
    raw = _read("/sys/class/thermal/thermal_zone0/temp").strip()
    rt = runtime()
    return {
        "model": {"docker": "Docker container", "lxc": "LXC container"}.get(
            rt, _p.node() or "Linux host"),
        "runtime": rt,
        "os": _osname(),
        "kernel": _p.release(),
        "uptime_seconds": int(float(_read("/proc/uptime").split()[0] or 0)),
        "memory_total_mb": total,
        "memory_used_mb": used,
        "cpu_temp_c": int(raw) / 1000.0 if raw.isdigit() else None,
        "throttled": False,
        "mock": False,
    }


def storage_status():
    """Staging capacity, expressed so the UI can talk in discs rather than gigabytes.

    Falls back to whatever filesystem holds the staging path when the dedicated staging
    partition (D4) does not exist. Stock Raspberry Pi OS resizes rootfs to fill the card,
    so on any image that is not yet a Riparr image there is no /srv/staging — and a
    statvfs on a missing path would otherwise 500 the entire status page.
    """
    if MOCK:
        total, free = 22.8 * 2**30, 16.1 * 2**30
        return {"total_bytes": int(total), "free_bytes": int(free),
                "used_bytes": int(total - free), "path": STAGING, "dedicated": True}

    path, dedicated = STAGING, True
    if not os.path.isdir(path):
        path, dedicated = "/", False
    try:
        st = os.statvfs(path)
    except OSError:
        return {"total_bytes": 0, "free_bytes": 0, "used_bytes": 0,
                "path": path, "dedicated": False, "error": "staging is not readable"}
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    return {"total_bytes": int(total), "free_bytes": int(free),
            "used_bytes": int(total - free), "path": path, "dedicated": dedicated}


STAGING = os.environ.get("RIPARR_STAGING") or (
    "/srv/staging" if IS_APPLIANCE else "/tmp/riparr-staging")


# ─────────────────────────────── optical ───────────────────────────────

# A drive's own capabilities never change while it is plugged in, and asking costs a
# SCSI command that spins an idle drive up. Asked once per device identity and kept.
_caps_cache = {}


def _capabilities(device, vendor, model):
    key = (device, vendor, model)
    if key not in _caps_cache:
        _caps_cache[key] = OPT.capabilities(device)
    return _caps_cache[key]


# Per-insertion cache of the things that cost a subprocess: media kind, volume label
# and size. Cleared the moment the tray reports empty, which is the only way a disc can
# be swapped. See the comment inside optical_drives().
_disc_cache = {}


def optical_drives():
    """Every optical drive, what it can read, and what is in it right now.

    `present`, `media` and `label` used to be hardcoded to False/None/None on real
    hardware -- nothing ever filled them in, and the mock branch was the only place a
    disc was ever reported as loaded. Everything that starts a rip keys off `present`,
    so on the appliance there was no way to start one: the watcher never fired, Auto
    Rip was inert, and the "Rip this disc" button never rendered. `optical.py` is what
    makes these fields answer from the hardware.

    Kept cheap on purpose. The disc watcher calls this every three seconds forever, so
    what happens per call is one ioctl the kernel answers from state it already has,
    plus -- only when a disc is actually loaded -- the media and label lookups. The
    drive's own capability list is cached, and MakeMKV is not consulted at all; that is
    `libredrive_status()`, which is far too expensive to sit in a poll loop.
    """
    if MOCK:
        return _mock_drives()
    out = []
    for dev in sorted(_glob("/dev/sr*")):
        name = os.path.basename(dev)
        # The names are in sysfs; reading them saves showing a nameless drive.
        vendor = _read("/sys/block/%s/device/vendor" % name).strip()
        model = _read("/sys/block/%s/device/model" % name).strip()

        caps = _capabilities(dev, vendor, model)
        present, tray = OPT.tray_status(dev)
        uhd, known = DRV.expectation(vendor, model, can_read_bluray=caps.get("bluray"))

        d = {"device": dev, "vendor": vendor, "model": model,
             "present": present, "tray": tray,
             "media": None, "label": None, "size_bytes": 0,
             "reads_dvd": bool(caps.get("dvd")), "reads_bluray": bool(caps.get("bluray")),
             "uhd": uhd, "known_as": known["name"] if known else None,
             "form": known["form"] if known else None}

        if present:
            # Read the disc's identity once per insertion, not once per call. The
            # label lookup shells out to `blkid`, which opens the drive -- and this
            # function is called by the 3s disc watcher AND by every /api/status, which
            # the browser polls once a second while a rip runs. That had `blkid`
            # reopening the drive underneath MakeMKV continuously: makemkvcon spent
            # two minutes spinning on futexes having read 6 MB, and it looked like
            # "reading the disc is slow". A closed tray cannot change discs, so the
            # answer cannot go stale; `present` going False is the invalidation.
            cached = _disc_cache.get(dev)
            if cached is None:
                profile, _ = OPT.get_configuration(dev)
                cached = {
                    "media": OPT.PROFILES.get(profile) if profile else None,
                    "media_kind": OPT.profile_kind(profile) if profile else None,
                    "label": OPT.volume_label(dev) or None,
                    "size_bytes": OPT.disc_size_bytes(dev),
                }
                _disc_cache[dev] = cached
            d.update(cached)
        else:
            _disc_cache.pop(dev, None)
        out.append(d)
    return out


# The mock drive and the mock disc are separate knobs because the interesting cases
# are the mismatches -- a UHD disc in a Blu-ray drive is the whole reason `drives.py`
# exists, and it has to be reachable without owning either.
#
#   RIPARR_MOCK_DRIVE = uhd | bluray | dvd | none
#   RIPARR_MOCK_DISC  = uhd | bluray | dvd | none
_MOCK_DRIVES = {
    "uhd": {"vendor": "HL-DT-ST", "model": "BD-RE BU40N",
            "reads_dvd": True, "reads_bluray": True},
    "bluray": {"vendor": "Pioneer", "model": "BDR-XD08U",
               "reads_dvd": True, "reads_bluray": True},
    "dvd": {"vendor": "HL-DT-ST", "model": "DVDRAM GP65NB60",
            "reads_dvd": True, "reads_bluray": False},
}

_MOCK_DISCS = {
    "uhd": {"media": "BD-ROM", "media_kind": "bluray", "label": "DUNE_UHD",
            "size_bytes": 62 * 2 ** 30},
    "bluray": {"media": "BD-ROM", "media_kind": "bluray", "label": "THE_MATRIX",
               "size_bytes": 24 * 2 ** 30},
    "dvd": {"media": "DVD-ROM", "media_kind": "dvd", "label": "THE_MATRIX",
            "size_bytes": 7 * 2 ** 30},
}


def _mock_drives():
    which = os.environ.get("RIPARR_MOCK_DRIVE", "bluray")
    if which == "none":
        return []
    spec = _MOCK_DRIVES.get(which, _MOCK_DRIVES["bluray"])
    caps = {"dvd": spec["reads_dvd"], "bluray": spec["reads_bluray"]}
    uhd, known = DRV.expectation(spec["vendor"], spec["model"],
                                 can_read_bluray=caps["bluray"])
    d = {"device": "/dev/sr0", "vendor": spec["vendor"], "model": spec["model"],
         "present": False, "tray": "empty",
         "media": None, "media_kind": None, "label": None, "size_bytes": 0,
         "reads_dvd": caps["dvd"], "reads_bluray": caps["bluray"],
         "uhd": uhd, "known_as": known["name"] if known else None,
         "form": known["form"] if known else None}

    disc = os.environ.get("RIPARR_MOCK_DISC", "bluray")
    if disc != "none" and disc in _MOCK_DISCS:
        # A drive that cannot read the medium still reports the tray as loaded -- that
        # is what the hardware does, and pretending otherwise would hide the exact
        # mismatch this knob exists to exercise.
        d.update(_MOCK_DISCS[disc], present=True, tray="loaded")
        # The volume label is what the identify stage reasons from -- a film name, or a
        # season and disc number on a box set. Overridable so that behaviour can be
        # exercised off-hardware without a drawer of real discs.
        label = os.environ.get("RIPARR_MOCK_LABEL")
        if label:
            d["label"] = label
    return [d]


# ─────────────────────── UHD: the question only MakeMKV can answer ───────────────────────

# Probing costs a makemkvcon run, so the answer is kept for the life of the process
# per drive identity. A drive does not gain LibreDrive support while plugged in, and
# the one thing that would change the answer -- installing MakeMKV -- restarts nothing
# but is caught by the `installed` guard below returning `None` until it is there.
_libredrive_cache = {}
# key -> Event, set when that key's probe finishes. Without this, every poll that
# arrives during the ~2 minutes a probe takes starts its own `makemkvcon`: the cache is
# only written *after* the run, so it cannot suppress a stampede. Nine of them piled up
# on the first real drive we ever attached.
_libredrive_inflight = {}
_libredrive_lock = threading.Lock()


def libredrive_status(drive, block=False):
    """Whether MakeMKV can get underneath this drive's firmware -- the UHD question.

    `drives.py` explains why nothing else can answer it: there is no MMC profile for
    UHD, so neither the drive nor the disc will say. MakeMKV's LibreDrive is the only
    route to a UHD disc on this hardware, and MakeMKV is the only thing that knows
    whether it has one.

    Returns "enabled", "possible", "no", or None for "not asked / cannot tell".

    Costs a ~2 minute `makemkvcon` run against a real drive, so by default it is started
    in the background and this returns None until the answer is cached. `block=True` is
    for the rip path, where the refusal actually has to be correct and waiting is fine.
    **Never block a polled endpoint on this** -- `/api/status` did, and the dashboard
    polls it, so signing in hung on the first drive we ever attached.
    """
    if MOCK:
        return {"uhd": "enabled", "bluray": "no", "dvd": None}.get(
            os.environ.get("RIPARR_MOCK_DRIVE", "bluray"))
    if not drive or not drive.get("reads_bluray"):
        return None                      # a DVD drive has no UHD question to ask
    if not makemkv_status().get("installed"):
        return None

    key = (drive.get("vendor"), drive.get("model"))
    if key in _libredrive_cache:
        return _libredrive_cache[key]

    with _libredrive_lock:
        ev = _libredrive_inflight.get(key)
        first = ev is None
        if first:
            ev = _libredrive_inflight[key] = threading.Event()

    if first:
        if block:
            _libredrive_probe(key, drive, ev)
            return _libredrive_cache.get(key)
        threading.Thread(target=_libredrive_probe, args=(key, drive, ev),
                         daemon=True).start()
    elif block:
        ev.wait(timeout=150)

    # None already means "not asked / cannot tell" to every caller, so a probe still
    # running is reported the same way and the answer appears on a later poll.
    return _libredrive_cache.get(key)


def _libredrive_probe(key, drive, ev):
    """Ask MakeMKV, once per drive model, off the request path."""
    try:
        binary = shutil.which("makemkvcon") or "/usr/local/bin/makemkvcon"
        m = re.search(r"sr(\d+)$", drive.get("device") or "")
        out = _run([binary, "-r", "--cache=1", "info",
                    "disc:%s" % (m.group(1) if m else "0")], timeout=120) or ""
        _libredrive_cache[key] = DRV.parse_libredrive(out)
    except Exception:
        # A probe that blew up must not be retried on every poll for ever, but it also
        # must not poison the answer permanently -- leave the cache empty and let the
        # next caller start a fresh one.
        pass
    finally:
        ev.set()
        with _libredrive_lock:
            _libredrive_inflight.pop(key, None)


def optical_diagnosis():
    """Why there is no drive -- not merely that there isn't one.

    On a server the drive reaches this process through a passthrough, and the usual
    reason for "no drive" is that the passthrough is missing or incomplete rather than
    anything about the drive itself. The hint says where to look.
    """
    drives = optical_drives()
    if drives:
        return {"drives": drives, "hint": None, "fixable": None}
    if MOCK:
        hint = "Development mode is simulating no drive (RIPARR_MOCK_DRIVE=none)."
    else:
        hint = (
            "No /dev/sr* device is visible to Riparr. Check that the drive shows up on "
            "the host (lsscsi -g), then pass **both** of its device nodes through: the "
            "block device (/dev/sr0) and its SCSI generic node (/dev/sg*), which is "
            "what MakeMKV reads from, with --device (or devices: in docker-compose.yml), "
            "then recreate the container. docs/guide/02-docker.md has the details.")
    return {"drives": drives, "hint": hint, "fixable": None}

# ─────────────────────────────── the clock ───────────────────────────────

# Nothing this service does can legitimately believe it is earlier than the day the
# code was written. A machine with a dead RTC battery comes up in 1970.
CLOCK_FLOOR = 1755000000        # 2025-08-12

def clock_status():
    """Whether the time can be trusted, on a board with no RTC.

    This matters more here than it looks. The MakeMKV key expiry is "N days left"
    computed against now; the scheduler's due-ness is computed from a stored `last_end`
    (D19); every "3 days ago" in the interface is a subtraction. A box that thinks it
    is 1970 reports all of them confidently and all of them wrong -- and D4 says
    losing power is the expected operating condition, not an edge case.
    """
    now = int(time.time())
    if MOCK:
        return {"now": now, "synced": True, "plausible": True, "source": "simulated"}

    synced = None
    if os.path.exists("/run/systemd/timesync/synchronized"):
        synced = True
    else:
        out = _run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"]) or ""
        if out.strip():
            synced = out.strip().lower() in ("yes", "true", "1")
    plausible = now >= CLOCK_FLOOR
    return {"now": now, "synced": synced, "plausible": plausible,
            "source": "ntp" if synced else "unknown"}


def trust_dates():
    """Whether anything derived from the clock is worth showing."""
    c = clock_status()
    return bool(c["plausible"] and c["synced"] is not False)


# ─────────────────────── the library, mounted ───────────────────────
#
# The SD card is the slowest thing in the pipeline on this class of board. Measured on
# the reference box, 600 MB each way:
#
#     write to the card         9.4 MB/s
#     write through the mount  18.0 MB/s
#     read back through it     17.8 MB/s
#
# So pointing MakeMKV at the share directly is not a workaround for a small card --
# it is roughly twice as fast, and it retires the card as a size limit, which is the
# only thing that stopped a 22 GiB Blu-ray fitting on a 32 GB card. It also stops
# writing tens of gigabytes per disc through flash that has a finite number of them.
#
# The mount itself is made by `tools/mount-library.sh`, run by systemd as root before
# the service starts. Nothing here mounts anything: this process is unprivileged and
# should stay that way.

LIBRARY_MOUNT = os.environ.get("RIPARR_LIBRARY_MOUNT", "/srv/library")


def library_mount(share=None):
    """The local path a given share is mounted at.

    The default share keeps `/srv/library`, unchanged, because that path is baked into
    an installed unit file and into every box already running. A second share -- films
    on the NAS, box sets on the spare drive -- gets `/srv/library-<id>` beside it.
    """
    if not share or share.get("is_default"):
        return LIBRARY_MOUNT
    return "%s-%d" % (LIBRARY_MOUNT, int(share["id"]))


def library_mounted(share=None):
    """Is this share mounted and writable by this process right now?

    Checked rather than assumed on every job, because a NAS that went away leaves a
    mount point that still exists and a directory that is no longer the share. Writing
    a 22 GiB rip into what turns out to be the root filesystem is how an appliance
    fills its own card and dies, so this asks the kernel, not the path.
    """
    mount = library_mount(share)
    if MOCK:
        return os.path.isdir(mount) and os.access(mount, os.W_OK)
    try:
        if not os.path.ismount(mount):
            return False
    except OSError:
        return False
    return os.access(mount, os.W_OK)


def library_status(share=None):
    """What the interface needs to say about direct-to-library writing."""
    mount = library_mount(share)
    mounted = library_mounted(share)
    free = None
    if mounted:
        try:
            st = os.statvfs(mount)
            free = st.f_bavail * st.f_frsize
        except OSError:
            free = None
    return {"mount": mount, "mounted": mounted, "free_bytes": free}


# ─────────────────────── how fast is this card, really? ───────────────────────
#
# SD cards lie on the packaging and vary by an order of magnitude, and the difference
# decides how Riparr should work: on the reference board the card manages 9.4 MB/s
# while the network manages 18, so staging a rip on the card makes it *slower*. That is
# not a thing to assume in either direction -- somebody with a good A2 card and a
# flaky 2.4 GHz link is in the opposite situation. So measure it, once, and let the
# measurement pick the default.

SPEED_SAMPLE = 64 * 1024 * 1024          # big enough to outrun the write cache


def card_speed(sample=SPEED_SAMPLE):
    """Write then read a scratch file on the staging partition. MB/s, or None.

    `conv=fsync` in spirit: the file is flushed and fsync'd before the clock stops,
    because a card that accepts 64 MB into RAM instantly and then spends ten seconds
    writing it is exactly the card this is trying to catch.
    """
    if MOCK:
        return {"write_mbs": 9.4, "read_mbs": 11.0, "sample_bytes": sample,
                "measured_at": int(time.time()), "note": "simulated"}
    path = os.path.join(STAGING, ".riparr-speedtest")
    chunk = b"\0" * (1024 * 1024)
    try:
        os.makedirs(STAGING, exist_ok=True)
        started = time.time()
        with open(path, "wb") as f:
            for _ in range(sample // len(chunk)):
                f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
        write_s = time.time() - started

        # Drop what we can of the cache, so the read measures the card and not RAM.
        try:
            fd = os.open(path, os.O_RDONLY)
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
            os.close(fd)
        except (OSError, AttributeError):
            pass

        started = time.time()
        with open(path, "rb") as f:
            while f.read(len(chunk)):
                pass
        read_s = time.time() - started
    except OSError as e:
        return {"write_mbs": None, "read_mbs": None, "error": str(e)}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    mb = sample / 1e6
    return {"write_mbs": round(mb / write_s, 1) if write_s > 0 else None,
            "read_mbs": round(mb / read_s, 1) if read_s > 0 else None,
            "sample_bytes": sample, "measured_at": int(time.time())}


# ─────────────────── saying something with the drive itself ───────────────────
#
# The status LED on the board is the documented way the box speaks without a browser,
# and on a board with nothing wired to SPI it says nothing at all. The optical drive
# has a light on the front of it and it is always there, so it is worth using.
#
# **There is no way to address that light.** MMC -- the command set every optical drive
# speaks -- has no LED control command, and the vendor-specific ones that exist are
# per-manufacturer guesses that do not belong anywhere near a stranger's hardware.
#
# What the light actually does is report *media access*. So Riparr does not switch it
# on; it gives the drive something to do, in a rhythm. Reads are issued with O_DIRECT
# so the page cache cannot answer them -- a cached read lights nothing -- and from a
# fresh offset each time so the head has to move. The result is a real blink pattern
# out of nothing but ordinary reads, on any drive, with no vendor knowledge at all.

# A DVD sector is 2048 bytes, so every offset and length here is a multiple of it;
# O_DIRECT on a block device rejects anything else.
_SECTOR = 2048
_FLASH_CHUNK = 256 * 1024          # big enough that one read is audible head movement

# (on_seconds, off_seconds) per blink, then the gap before the group repeats. Three
# short flashes is deliberately unlike the steady flicker of a rip in progress.
DUPLICATE_PATTERN = {"blinks": 3, "on": 0.22, "off": 0.22, "gap": 0.55, "groups": 3}


def drive_flash(device="/dev/sr0", blinks=3, on=0.22, off=0.22, gap=0.55, groups=3):
    """Blink the drive's own activity light by reading the disc in a rhythm.

    Returns {"ok", "message", "sectors"} -- `sectors` is how far the block layer says
    the drive actually read, which is the only evidence available that anything
    happened. Nobody here can see the light.

    Never raises. A drive that is busy, empty, or refuses O_DIRECT simply reports that
    it could not blink; this is a courtesy signal and nothing depends on it.
    """
    if MOCK:
        return {"ok": True, "message": "Drive light flashed (simulated)", "sectors": 0}

    before = _sr_sectors_read(device)
    fd = None
    buf = None
    try:
        import mmap
        # mmap gives page-aligned memory, which satisfies O_DIRECT's alignment rule
        # without hand-rolling an aligned allocator.
        buf = mmap.mmap(-1, _FLASH_CHUNK)
        flags = os.O_RDONLY | getattr(os, "O_DIRECT", 0)
        try:
            fd = os.open(device, flags)
        except OSError:
            # Some filesystems and some drives refuse O_DIRECT outright. Without it the
            # cache may answer and the light will not move, so say so rather than
            # pretending the signal was sent.
            if not getattr(os, "O_DIRECT", 0):
                return {"ok": False, "sectors": 0,
                        "message": "This system has no O_DIRECT, so reads would come "
                                   "from cache and the light would not move."}
            fd = os.open(device, os.O_RDONLY)

        offset = 0
        for _ in range(max(1, groups)):
            for _ in range(max(1, blinks)):
                # Hold the drive busy for the whole "on" period. One read is over in
                # milliseconds; a light that flickers for 4 ms is a light nobody sees.
                until = time.monotonic() + on
                while time.monotonic() < until:
                    try:
                        os.preadv(fd, [buf], offset)
                    except OSError:
                        # Past the end of a short disc, or a bad sector. Go back to the
                        # start rather than leaving the offset stranded -- otherwise
                        # every remaining flash fails instantly and the light, having
                        # blinked once, simply stops.
                        offset = 0
                        break
                    offset += _FLASH_CHUNK
                    # Stay inside the first 512 MB. Every real disc has data there, and
                    # seeking past the end of a short disc only earns I/O errors.
                    if offset > 512 * 1024 * 1024:
                        offset = 0
                time.sleep(off)
            time.sleep(gap)
    except Exception as e:
        return {"ok": False, "message": "Could not flash the drive light: %s" % e,
                "sectors": max(0, _sr_sectors_read(device) - before)}
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if buf is not None:
            try:
                buf.close()
            except Exception:
                pass

    read = max(0, _sr_sectors_read(device) - before)
    # Zero sectors means the reads never reached the device -- cache, or a drive that
    # ignored them -- so the light did not move and saying "sent" would be a lie.
    return {"ok": read > 0,
            "sectors": read,
            "message": ("Flashed the drive light (%d sectors read)." % read) if read
                       else "The reads never reached the drive, so the light did not move."}


def _sr_sectors_read(device="/dev/sr0"):
    """Sectors the block layer has read from this drive, or 0 if it cannot say.

    Field 3 of /sys/block/<dev>/stat. This is the proof that a `drive_flash` did
    something: MakeMKV's own reads go through /dev/sg0 and never appear here, so any
    movement in this counter is ours.
    """
    name = os.path.basename(device or "")
    try:
        with open("/sys/block/%s/stat" % name) as f:
            return int(f.read().split()[2])
    except (OSError, IndexError, ValueError):
        return 0


def close_tray(device="/dev/sr0", wait=25):
    """Pull the tray in and wait for the drive to work out what is on it.

    The counterpart to `eject`, and the reason Re-rip can be a single click: the disc
    is sitting on an open tray at exactly the moment somebody decides they meant it.
    `wait=0` closes the tray and says nothing about what is in it -- which is what
    `tray_gesture` wants, since it is only moving the tray to be looked at.
    Returns (ok, message).
    """
    if MOCK:
        return True, "Tray closed (simulated)"
    try:
        p = subprocess.run(["eject", "-t", device], capture_output=True, text=True)
    except OSError as e:
        return False, "Riparr could not close the tray (%s)." % e
    if p.returncode != 0:
        return False, ((p.stderr or p.stdout).strip()
                       or "The drive would not pull the tray in.")
    if not wait:
        return True, "Tray closed."
    # Closing returns long before the disc is readable -- a DVD takes 15-25 s to spin
    # up and report its table of contents, and asking too early gets "no medium".
    #
    # "Present" alone is not enough to stop waiting. The drive can report a disc a
    # moment before it can describe one, and `optical_drives()` caches a disc's
    # identity for as long as it stays loaded -- so a read taken one second too early
    # would latch a nameless, zero-byte disc until the next eject, and the rip that
    # followed would be called "Unknown disc". Wait for an identity, and throw away
    # any half-answer taken on the way there.
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(2)
        d = next((x for x in optical_drives() if x.get("present")), None)
        if not d:
            continue
        if d.get("size_bytes") or d.get("label"):
            return True, "Tray closed."
        _disc_cache.pop(d["device"], None)
    return False, ("The tray closed but the drive could not read a disc in it. "
                   "Put the disc in and try again.")


def tray_gesture(device="/dev/sr0", cycles=2):
    """Say something by opening and closing the tray -- the loudest thing this box owns.

    Unmissable across a room, and it is machinery, so it is deliberately restrained:
    a couple of cycles, not a drum solo. The tray is left **open** at the end, because
    whatever the box was trying to say, the user's disc is theirs to take back.
    """
    if MOCK:
        return {"ok": True, "message": "Tray gesture (simulated)"}
    ok = True
    for i in range(max(1, cycles)):
        r = eject(device)
        ok = ok and r.get("ok")
        time.sleep(1.2)
        if i < cycles - 1:
            done, _ = close_tray(device, wait=0)
            ok = ok and done
            time.sleep(1.2)
    return {"ok": ok, "message": "Opened the tray %d times." % max(1, cycles)}


def duplicate_signal(device="/dev/sr0", mode="flash"):
    """Tell somebody with no screen that this disc is already in their library.

    Ordering matters: the light can only be blinked while the disc is still in the
    drive, so that happens first and the eject follows. Returns a message describing
    what was actually done, which is not always what was asked -- a flash that never
    reached the drive falls back to the tray rather than silently doing nothing.
    """
    if mode == "off":
        return {"ok": True, "message": "No physical signal (turned off)."}
    out = []
    flashed = False
    if mode in ("flash", "both"):
        r = drive_flash(device, **DUPLICATE_PATTERN)
        flashed = r.get("ok")
        out.append(r.get("message"))
    if mode == "tray" or mode == "both" or (mode == "flash" and not flashed):
        if mode == "flash":
            out.append("Falling back to the tray.")
        out.append(tray_gesture(device).get("message"))
    return {"ok": True, "message": " ".join(x for x in out if x)}


def eject(device="/dev/sr0"):
    """Give the user their disc back. There is no physical button on the enclosure."""
    if MOCK:
        return {"ok": True, "message": "Tray ejected (simulated)"}
    try:
        p = subprocess.run(["eject", device], capture_output=True, text=True)
    except OSError as e:
        # Giving the disc back is a courtesy; it is never the point of the job. This
        # used to raise straight through the failure handler that called it, so a box
        # without /usr/bin/eject reported "No such file or directory: 'eject'" as the
        # reason a rip failed -- masking the real error entirely and costing a session.
        return {"ok": False, "message": "Riparr could not open the tray (%s)." % e}
    return {"ok": p.returncode == 0,
            "message": (p.stderr or p.stdout).strip() or "Tray ejected"}


# ─────────────────────────────── makemkv ───────────────────────────────

def makemkv_status():
    """The one setting that needs periodic attention, so it is reported first-class."""
    if MOCK:
        # RIPARR_MOCK_MAKEMKV lets the first-run and expiry paths be exercised off-Pi:
        #   missing  — not installed, so the licence + install flow shows
        #   expiring — installed, key nearly dead, so the warning paths show
        #   old      — installed, but older than the pinned version, so upgrade shows
        mode = os.environ.get("RIPARR_MOCK_MAKEMKV", "ready")
        if mode == "missing":
            return {"installed": False, "version": None, "eula_accepted": False,
                    "key_type": None, "key_expires": None, "days_left": None}
        if mode == "old":
            return {"installed": True, "version": "1.18.4", "eula_accepted": True,
                    "key_type": "beta", "key_expires": "2026-10-31", "days_left": 30,
                    "key_stale": False}
        if mode == "expiring":
            return {"installed": True, "version": "2.0.0", "eula_accepted": True,
                    "key_type": "beta", "key_expires": "2026-08-23", "days_left": 4}
        return {"installed": True, "version": "2.0.0", "eula_accepted": True,
                "key_type": "beta", "key_expires": "2026-10-14", "days_left": 56}
    binary = shutil.which("makemkvcon") or "/usr/local/bin/makemkvcon"
    installed = os.path.exists(binary)
    ver = _makemkv_version(binary) if installed else None
    out = {"installed": installed, "version": ver,
           "eula_accepted": _makemkv_eula_accepted()}
    out.update(_key_state())
    return out


def _key_state():
    """Key type and days remaining, off the database rather than off the network.

    This runs on every status poll, so it makes no request and reads no file that might
    block. `makemkv._record_expiry` puts the date here whenever a source was reached;
    until one has been, the honest answer is None and the interface says "unknown"
    rather than inventing a countdown.

    These three fields were hardcoded to None on real hardware while the only values that
    were ever not-None came from the MOCK branch above -- which meant every expiry
    warning, the key_expiring notification and the "N days left" pill were unreachable
    code on the machines they were written for.
    """
    from . import db
    key = (db.get("makemkv_key") or "").strip()
    if not key:
        return {"key_type": None, "key_expires": None, "days_left": None,
                "key_stale": False}
    if not key.startswith("T-"):
        # Purchased keys do not expire, so there is nothing to count down.
        return {"key_type": "purchased", "key_expires": None, "days_left": None,
                "key_stale": False}

    stale = bool(db.get("makemkv_key_stale"))
    iso = (db.get("makemkv_key_expires") or "").strip()
    days = None
    if iso:
        try:
            y, m, d = (int(x) for x in iso.split("-"))
            days = (datetime.date(y, m, d) - datetime.date.today()).days
        except (ValueError, TypeError):
            iso = ""
    return {"key_type": "beta", "key_expires": iso or None, "days_left": days,
            "key_stale": stale}


_version_cache = {}


VERSION_FILE = "/usr/local/lib/riparr/makemkv.version"
EULA_FILE = "/usr/local/lib/riparr/makemkv.eula"


def _makemkv_eula_accepted():
    """Whether the installed MakeMKV was installed under an accepted licence.

    This used to look for ~/.MakeMKV/eula_accepted, which MakeMKV never creates — the
    bin package's Makefile gate is a differently named file inside the build directory,
    and it is gone once the build is. So this was always False, and the interface went
    on asking for consent that had already been given and recorded.

    Our installer cannot run without --accept-eula, so it writes EULA_FILE at the point
    the user's consent was acted on. The legacy path is still honoured for a MakeMKV
    that arrived some other way.
    """
    return (os.path.exists(EULA_FILE)
            or os.path.exists(os.path.expanduser("~/.MakeMKV/eula_accepted")))


def _makemkv_version(binary):
    """The version, without running makemkvcon at all.

    There is no cheap way to ask the binary. It has no --version and no --help — both
    print usage and exit non-zero. `-r info disc:99` does print the banner, but it
    enumerates every optical device first and blocks for 20+ seconds doing it, which is
    impossible for an endpoint the status page polls and would collide with a rip. The
    version strings inside the executable belong to bundled libraries, not to MakeMKV.

    So the installer records it at install time, when it is already known from the
    tarball name. A MakeMKV installed some other way has no such file; report the
    version as unknown rather than paying 20 seconds to find out.
    """
    try:
        key = (binary, os.path.getmtime(binary))
    except OSError:
        return None
    if key in _version_cache:
        return _version_cache[key]
    ver = None
    try:
        with open(VERSION_FILE) as f:
            m = re.match(r"\s*v?([\d.]+)", f.read())
            ver = m.group(1) if m else None
    except OSError:
        pass
    _version_cache.clear()
    _version_cache[key] = ver
    return ver


# ─────────────────────────────── helpers ───────────────────────────────

def _read(path):
    try:
        return open(path, errors="ignore").read()
    except OSError:
        return ""


def _run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout
    except Exception:
        return None


def _glob(pat):
    import glob
    return glob.glob(pat)


def _osname():
    for line in _read("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip('"')
    return "Linux"


def _ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None
