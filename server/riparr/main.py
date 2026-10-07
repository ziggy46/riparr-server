"""
The Riparr service. API-first: the web UI is just the first client of this API (D2),
which is what makes Homepage widgets and multi-unit setups nearly free later.
"""
import html
import json
import os
import re
import threading
import time

from fastapi import (FastAPI, File, HTTPException, Request, Response, Depends,
                     UploadFile)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from typing import Dict, List

from pydantic import BaseModel
from itsdangerous import URLSafeTimedSerializer, BadSignature

from . import (__version__, build, artwork as ART, backup as BK, db, drives as DRV,
               makemkv as MK,
               naming as NM, notify as NT, tmdb as TM, platform as P, rip as RIP, shares as SH, system as SY,
               tv as TV, updater)

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
COOKIE = "riparr_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30       # 30 days, matched to the cookie's Max-Age

# The interactive API docs and the schema they read describe every endpoint, so on the
# shipped box — which sits on an untrusted LAN behind one login — they are turned off
# rather than handed to anyone who asks before signing in. They stay on in development
# (MOCK mode) where they are useful and the box is a laptop, not an appliance.
# RIPARR_API_DOCS=1 turns them on in a deployment too, for wiring up dashboards.
_SHOW_DOCS = (not P.IS_APPLIANCE
              or os.environ.get("RIPARR_API_DOCS", "") not in ("", "0", "no", "false"))
_DOCS = "/api/docs" if _SHOW_DOCS else None
_OPENAPI = "/api/openapi.json" if _SHOW_DOCS else None

app = FastAPI(title="Riparr", version=__version__, docs_url=_DOCS,
              openapi_url=_OPENAPI)


def _secret():
    s = db.get("session_secret")
    if not s:
        s = db.set("session_secret", os.urandom(32).hex())
    return s


def _rotate_secret():
    """Mint a fresh session secret, which invalidates every cookie signed with the old
    one. This is how a password change logs out other devices: the sessions are
    stateless (nothing to delete), so revocation is done by changing the key they were
    signed under."""
    return db.set("session_secret", os.urandom(32).hex())


# ─────────────────────────────── password recovery ───────────────────────────────

RESET_FILENAMES = ("riparr-reset", "riparr-reset.txt")


def _check_password_reset():
    """Honour a reset file left beside the database.

    There is no console and no email, and opening the reset to the network would be a
    hole in the one thing standing between this service and everyone else on the LAN.

    A file in the data directory is the right key for this lock: creating it needs a
    shell on the host or container, which is proof of ownership. Settings, shares and
    disc history all survive. The file is deleted as it is honoured, then restart.
    """
    d = os.path.dirname(os.path.abspath(db.DB_PATH))
    if not os.path.isdir(d):
        return
    for name in RESET_FILENAMES:
        path = os.path.join(d, name)
        if not os.path.exists(path):
            continue
        try:
            os.unlink(path)               # consumed first: never loop on a failure
        except OSError as e:
            SY.component("Setup").error("Found %s but couldn't remove it: %s", path, e)
            return
        db.clear_users()
        db.set("setup_complete", False)
        SY.component("Setup").warning(
            "Password reset requested from %s. The account has been cleared; the next "
            "person to open the web interface will be asked to create one.", path)
        return


@app.on_event("startup")
def _startup():
    db.init()
    _secret()
    SY.init()
    _check_password_reset()
    SY.start_scheduler()
    RIP.start()


# ─────────────────────────────── auth ───────────────────────────────

def _serializer():
    return URLSafeTimedSerializer(_secret(), salt="riparr-session")


def current_user(request: Request):
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        # max_age turns the timestamp the token already carried — and never checked —
        # into a real expiry: a cookie older than the window is refused as a bad
        # signature, so a leaked one does not stay valid forever. SignatureExpired is a
        # subclass of BadSignature, so both land here.
        return _serializer().loads(raw, max_age=SESSION_MAX_AGE).get("u")
    except BadSignature:
        return None


def require_user(request: Request):
    """During first run there is no account yet, so the API stays open until there is.

    Once an account exists the box is closed — it must never sit on someone's network
    unprotected after setup.
    """
    if not db.has_users():
        return "__setup__"
    u = current_user(request)
    if not u:
        raise HTTPException(status_code=401, detail="Not signed in")
    return u


class Login(BaseModel):
    username: str
    password: str


# ── login throttle ──
# The box is single-user and sits on a LAN, so a wrong password is either a typo or a
# guessing run. This slows the second case without punishing the first: the delay is
# applied *before* the response and grows with the run of recent failures, so a few
# fat-fingered tries cost nothing perceptible while a script hits an escalating wall.
#
# It is a delay, not a lockout, and on purpose. A hard lockout on the only account of a
# headless appliance is a denial-of-service an attacker can trigger against the owner;
# making them wait a few seconds cannot lock anyone out of their own box.
_LOGIN_LOCK = threading.Lock()
_login_fails = 0            # consecutive failures across the box; reset on any success
_LOGIN_DELAY_CAP = 5.0      # seconds; the longest anyone ever waits
_LOGIN_ALERT_AT = 5         # failures before it becomes a logged security event


def _login_delay():
    with _LOGIN_LOCK:
        n = _login_fails
    if n <= 0:
        return 0.0
    return min(_LOGIN_DELAY_CAP, 0.5 * (2 ** (n - 1)))


def _login_failed(username):
    global _login_fails
    with _LOGIN_LOCK:
        _login_fails += 1
        n = _login_fails
    if n == _LOGIN_ALERT_AT:
        SY.component("Auth").warning(
            "%d failed sign-ins in a row (most recent for '%s'). If this wasn't you, "
            "someone on the network may be guessing the password.", n, username)


def _login_succeeded():
    global _login_fails
    with _LOGIN_LOCK:
        _login_fails = 0


@app.post("/api/auth/login")
def login(body: Login, response: Response, request: Request):
    time.sleep(_login_delay())            # pay the accumulated cost before answering
    if not db.verify_user(body.username, body.password):
        _login_failed(body.username)
        raise HTTPException(status_code=401, detail="Wrong username or password")
    _login_succeeded()
    # The address you sign in at is the best guess at how your phone reaches Riparr,
    # for the buttons in notifications, until one is set on Settings → Connect.
    db.set("seen_url", str(request.base_url).rstrip("/"))
    token = _serializer().dumps({"u": body.username, "t": int(time.time())})
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax",
                        max_age=SESSION_MAX_AGE)
    return {"ok": True, "username": body.username}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/auth/me")
def me(request: Request):
    return {"username": current_user(request), "has_users": db.has_users()}


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/auth/password")
def change_password(body: PasswordChange, request: Request, response: Response,
                    user=Depends(require_user)):
    if not db.verify_user(user, body.current_password):
        raise HTTPException(status_code=400, detail="Current password is wrong")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Use at least 8 characters")
    db.set_password(user, body.new_password)
    # Changing the password logs out everywhere else. Rotating the signing secret
    # invalidates every existing cookie; re-issuing this one keeps the person who just
    # changed it signed in on this device, which is the expected behaviour.
    _rotate_secret()
    token = _serializer().dumps({"u": user, "t": int(time.time())})
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax",
                        max_age=SESSION_MAX_AGE)
    return {"ok": True}


# ─────────────────────────── first run ───────────────────────────

class SetupUser(BaseModel):
    username: str
    password: str


@app.get("/api/setup/state")
def setup_state():
    """What the setup wizard needs to know before anyone has signed in.

    Unauthenticated by necessity -- it is what the page asks to find out whether an
    account exists yet. That makes everything it returns public to anything that can
    reach the port, so the share comes back as the four fields the wizard actually
    draws. It used to return `db.default_share()` whole, which includes the SMB
    **password in the clear**: an unauthenticated GET handed out the credentials to
    the user's NAS.
    """
    share = db.default_share()
    return {
        "has_users": db.has_users(),
        "complete": bool(db.get("setup_complete")),
        "makemkv": P.makemkv_status(),
        "share": None if not share else {
            "id": share["id"], "name": share["name"],
            "host": share["host"], "path": share["path"],
            "verified_at": share["verified_at"],
        },
        "hostname": P.hostname(),
        "version": __version__,
        # So the sign-in page is drawn in the chosen theme. It's a look, not a secret,
        # and it goes into a stylesheet URL, so only a plain name is passed on.
        "theme": _theme_name(db.get("theme")),
    }


def _theme_name(name):
    return name if isinstance(name, str) and re.fullmatch(r"[a-z0-9-]{1,32}", name) else "servarr"


@app.post("/api/setup/user")
def setup_user(body: SetupUser, response: Response):
    if db.has_users():
        raise HTTPException(status_code=400, detail="An account already exists")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Use at least 8 characters")
    db.create_user(body.username, body.password)
    token = _serializer().dumps({"u": body.username, "t": int(time.time())})
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax",
                        max_age=SESSION_MAX_AGE)
    return {"ok": True}


@app.post("/api/setup/complete")
def setup_complete(user=Depends(require_user)):
    db.set("setup_complete", True)
    return {"ok": True}


# ─────────────────────────────── status ───────────────────────────────

# Typical payload of the largest disc of each kind, for expressing capacity in discs.
DISC_BYTES = {"dvd": 8 * 2**30, "bluray": 25 * 2**30, "uhd": 66 * 2**30}
WINDOW_BYTES = RIP.WINDOW_BYTES   # the streaming window (D11) — one definition, not two


DISC_NAMES = {"uhd": ("4K UHD disc", "4K UHD discs"),
              "bluray": ("Blu-ray", "Blu-rays"),
              "dvd": ("DVD", "DVDs")}
DISC_ORDER = ("uhd", "bluray", "dvd")


def _capacity(free_bytes, direct=None):
    """Capacity, in the terms the engine actually operates in.

    `direct` matters because it changes what the card *is*. When rips go straight to
    the library the card holds no films at all, so counting how many Blu-rays fit on it
    answers a question nobody is asking and reads as a ceiling that does not exist.
    What still matters is the working window -- MakeMKV needs scratch room wherever it
    writes -- so "not enough room to rip safely" is still reachable and still true.

    This used to describe D11 as designed rather than as built, and the two disagree.
    D11 says a buffer too small for the next disc means stream mode, not refusal — but
    follow-copy is not built (D22), so `rip._plan_transfer()` **refuses**. This
    function was reporting `mode: "stream"` and the sentence "discs are never refused
    for space" in precisely the case where the engine would refuse the next disc put
    in the tray. A status page that contradicts the engine is worse than one that says
    something disappointing.

    So the mode is now read off the same seam `_plan_transfer` branches on, and the
    two cannot drift: when `supports_follow_copy` goes True, both switch together.

    The window is also subtracted before counting discs, which it never was. On a card
    with 16 GB free the old arithmetic promised two DVDs and the engine allowed one.

    "Room for 1 more disc" was true and useless: a disc is anywhere from 8 to 66 GB,
    so the number silently meant Blu-ray and was wrong by a factor of eight for a DVD.
    Count each kind and say which is which.
    """
    streaming = SH.Transport.supports_follow_copy
    if direct is None:
        direct = RIP.use_direct()
    usable = max(0, free_bytes - WINDOW_BYTES)
    by_kind = {k: int(usable // v) for k, v in DISC_BYTES.items()}
    discs = by_kind["bluray"]

    if free_bytes < WINDOW_BYTES:
        mode, phrase = "degraded", "Not enough room to rip safely"
    elif direct:
        # The films are not going here, so the card's size is not the limit. Say where
        # they are going instead -- the number somebody wants when rips go direct is
        # their library's free space, which the Library panel already shows.
        mode, phrase = "direct", "Rips go straight to your library — staging space isn't the limit"
    elif any(by_kind[k] for k in DISC_ORDER):
        mode = "burst"
        parts = []
        for k in DISC_ORDER:
            n = by_kind[k]
            if not n:
                continue
            one, many = DISC_NAMES[k]
            parts.append("%d %s" % (n, one if n == 1 else many))
        phrase = "Room for " + parts[0]
        if len(parts) > 1:
            phrase += " — or " + ", or ".join(parts[1:])
    elif streaming:
        mode, phrase = "stream", "Streaming — discs are never refused for space"
    else:
        # Room to work in, but not room for a whole disc of any kind, and no
        # follow-copy to rescue it. Say what will happen, because it is about to.
        mode, phrase = "full", "Not enough room for another disc — let the queue drain"

    return {"discs_free": discs, "by_kind": by_kind, "mode": mode, "phrase": phrase,
            "streaming": streaming, "direct": direct,
            "disc_names": {k: list(v) for k, v in DISC_NAMES.items()},
            "window_bytes": WINDOW_BYTES}


@app.get("/api/status")
def status(request: Request, user=Depends(require_user)):
    # Signed in from before this was recorded at sign-in: the page loads this first, so
    # the notification buttons get an address without signing in again. Once only.
    if not db.get("seen_url"):
        db.set("seen_url", str(request.base_url).rstrip("/"))
    storage = P.storage_status()
    # The user should never see a gigabyte: capacity is expressed in discs and mode.
    return {
        "version": __version__,
        "build": build(),
        "hostname": P.hostname(),
        "system": P.system_status(),
        "storage": dict(storage, **_capacity(storage["free_bytes"])),
        "optical": P.optical_diagnosis(),
        "clock": P.clock_status(),
        "makemkv": dict(P.makemkv_status(), sdf_stop=MK.conf_value("sdf_Stop")),
        "drives": _drive_report(),
        # Four fields, not the row. The row carries the SMB password, and the browser
        # has never needed it -- same argument as /api/setup/state, which was handing
        # it out to anyone at all.
        "share": _share_out(db.default_share()),
        "setup_complete": bool(db.get("setup_complete")),
        "autorip": _autorip_state(),
        # A refused duplicate leaves no job and no file, so this is the only trace of
        # it. The page turns it into "you already ripped this, here it is".
        "duplicate": RIP.pending_duplicate(),
        "library": P.library_status(),
        "tmdb": TM.configured(),
    }


def _share_out(share):
    if not share:
        return None
    return {"id": share["id"], "name": share["name"], "host": share["host"],
            "path": share["path"], "verified_at": share["verified_at"]}


@app.post("/api/drive/eject")
def drive_eject(user=Depends(require_user)):
    return P.eject()


@app.post("/api/drive/close")
def drive_close(user=Depends(require_user)):
    ok, message = P.close_tray()
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message}


class SpeedTest(BaseModel):
    pass


@app.post("/api/storage/speedtest")
def storage_speedtest(body: SpeedTest = SpeedTest(), user=Depends(require_user)):
    """Measure the card, and recommend a transfer mode from what comes back.

    The recommendation is the point. "Direct is probably better" is an opinion; "your
    card writes at 9.4 MB/s and your library takes 18, so staging on the card makes
    every rip slower" is a reason. Somebody with a fast card and a weak link gets the
    opposite advice from the same code.
    """
    if db.active_job():
        raise HTTPException(status_code=400,
                            detail="Riparr is working on a disc — this would fight it "
                                   "for the staging disk. Try again when it has finished.")
    card = P.card_speed()
    lib = P.library_status()
    result = {"card": card, "library": lib}
    db.set("card_speed", card)

    w = card.get("write_mbs")
    if not w:
        result["recommend"] = None
        result["why"] = "Riparr couldn't measure the staging disk."
        return result
    if not lib.get("mounted"):
        # No recommendation rather than "switch to the card". A share that is not
        # mounted right now is not evidence about which mode suits this box -- and
        # rips already fall back to the card on their own when it is missing (see
        # rip.use_direct), so there is nothing here for the user to fix by changing a
        # setting they would then have to remember to change back.
        result["recommend"] = None
        result["why"] = ("Your staging disk writes at about %s MB/s. Riparr can't "
                         "compare that with your library until it is mounted at "
                         "%s — rips are staged until then, either way."
                         % (w, P.LIBRARY_MOUNT))
        return result
    # No network measurement here: it would mean writing a test file into somebody's
    # library, and the honest comparison is against what this box has actually done.
    result["recommend"] = "direct" if w < 15 else "auto"
    result["why"] = (
        ("Your staging disk writes at about %s MB/s, which is slow enough that writing "
         "straight to your library will likely be faster." % w)
        if w < 15 else
        ("Your staging disk writes at about %s MB/s, which is quick enough that staging "
         "costs little — and it means a rip survives the network dropping out "
         "mid-disc." % w))
    return result


@app.post("/api/duplicate/ack")
def duplicate_ack(user=Depends(require_user)):
    """The interface has shown the user their already-ripped disc. Stop pointing."""
    RIP.ack_duplicate()
    return {"ok": True}


class SignalTest(BaseModel):
    mode: str = "flash"


@app.post("/api/drive/signal-test")
def drive_signal_test(body: SignalTest = SignalTest(), user=Depends(require_user)):
    """Fire the "already ripped" signal on demand, with a disc in the tray.

    Nobody can see the drive's light from inside the software, so the only way to know
    whether the blink works on a given drive is for a person to watch it happen. This
    is the button that lets them, without having to find a duplicate disc first.
    """
    if body.mode not in ("flash", "tray", "both"):
        raise HTTPException(status_code=400, detail="Unknown signal.")
    if db.active_job():
        raise HTTPException(status_code=400,
                            detail="Riparr is working on a disc — this would fight it "
                                   "for the drive. Try again when it has finished.")
    d = next((x for x in P.optical_drives() if x.get("present")), None)
    if body.mode in ("flash", "both") and not d:
        raise HTTPException(status_code=400,
                            detail="Put a disc in first — the light is blinked by "
                                   "reading one.")
    r = P.duplicate_signal((d or {}).get("device") or "/dev/sr0", mode=body.mode)
    return {"ok": bool(r.get("ok")), "message": r.get("message")}


@app.get("/api/disc/details")
def disc_details(user=Depends(require_user)):
    """Every title MakeMKV found on the disc, with its streams and what Riparr makes of
    them -- for checking a name before the rip, or reporting one that came out wrong."""
    return RIP.disc_details()


@app.post("/api/disc/scan")
def disc_scan(user=Depends(require_user)):
    ok, message = RIP.scan_disc()
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message}


@app.get("/api/disc/raw")
def disc_raw(user=Depends(require_user)):
    """MakeMKV's own output from the last scan, exactly as it printed it."""
    raw = RIP.last_scan_raw()
    if not raw:
        raise HTTPException(status_code=404, detail="No disc has been scanned yet.")
    return Response(content=raw, media_type="text/plain",
                    headers={"Content-Disposition": 'attachment; filename="makemkv-info.txt"'})


@app.get("/api/drives/guide")
def drives_guide(user=Depends(require_user)):
    """Which drive to buy — the list `docs/guide/01-what-you-need.md` has promised.

    Served from the same registry the running box identifies its own drive against,
    so the advice and the diagnosis can never disagree.
    """
    return {"drives": DRV.buying_guide(), "libredrive_list": DRV.LIBREDRIVE_LIST}


# ─────────────────────────────── auto rip ───────────────────────────────

def _reads_phrase(drive):
    """What this drive reads, in the words a person shopping for one would use.

    4K is named separately from Blu-ray on purpose. They are one checkbox on a
    retail listing and two entirely different pieces of hardware (`drives.py`), and
    collapsing them here would reproduce the exact confusion the drive registry
    exists to prevent.
    """
    parts = []
    if drive.get("reads_dvd"):
        parts.append("DVD")
    if drive.get("reads_bluray"):
        parts.append("Blu-ray")
    if not parts:
        return "capability unknown"
    if drive.get("uhd") == "yes" or drive.get("libredrive") == "enabled":
        parts.append("4K UHD")
    return ", ".join(parts)


def _drive_report():
    """The drives, plus the two things that are too expensive for the disc watcher.

    `optical_drives()` runs every three seconds and stays cheap. LibreDrive costs a
    `makemkvcon` run and the UHD label is derived from it, so both are attached here,
    on the status request a human made.
    """
    out = []
    busy = db.active_job() is not None
    for d in P.optical_drives():
        d = dict(d)
        # Ask MakeMKV about LibreDrive only when it cannot get in the way. The probe is
        # a two-minute `makemkvcon` run that holds the drive, and rip.py:136 already
        # states the rule -- "LibreDrive is asked only for a 4K disc" -- which this
        # ignored, probing on every status poll for any Blu-ray-capable drive. With a
        # DVD in the tray that meant a background probe owned /dev/sr0 and the rip's own
        # makemkvcon queued behind it, so POST /api/rip simply hung and the user saw a
        # button that did nothing. Idle tray, or a disc that actually raises the UHD
        # question: otherwise leave it None and let the chip stay unlit.
        ask = not busy and (not d.get("present") or RIP.disc_family(d) == "uhd")
        d["libredrive"] = P.libredrive_status(d) if ask else None
        # MakeMKV outranks the registry in both directions. The registry is what to
        # expect of a drive you have not bought; MakeMKV is what this drive does.
        verdict = {"enabled": "yes", "no": "no"}.get(d["libredrive"]) or d.get("uhd")
        d["uhd_label"] = DRV.UHD_LABEL.get(verdict)
        d["reads"] = _reads_phrase(d)
        # Family and refusal come from the engine rather than being re-derived in the
        # browser. "Is this a UHD disc" has a subtle answer (rip.disc_family) and the
        # frontend having its own copy of it is how two screens start disagreeing.
        family = RIP.disc_family(d)
        d["disc_family"] = family
        d["disc_word"] = RIP.DISC_WORD.get(family)
        d["cannot_read"] = (RIP.unreadable_reason(d, d["libredrive"])
                            if d.get("present") else None)
        d["space_warning"] = _space_warning(d) if d.get("present") else None
        d["known"] = _known_disc(d) if d.get("present") else None
        out.append(d)
    return out


def _known_disc(drive):
    """The disc in the tray, if Riparr has already ripped it -- recognised by label and
    size, the same quick check enqueue makes. Lets the queue say "already ripped" up
    front instead of offering a Rip button whose only effect is to refuse and eject.
    """
    try:
        known = db.disc_by_label_size(drive.get("label") or "", drive.get("size_bytes"))
    except Exception:
        return None
    if not known or not RIP._already_have(known):
        return None
    return {"fingerprint": known.get("fingerprint"), "title": known.get("title"),
            "year": known.get("year"), "ripped_at": known.get("ripped_at")}


def _space_warning(drive):
    """"This disc is bigger than the room you have", said before the button is pressed.

    Preflight already refuses a title that does not fit (`rip._plan_transfer`), but it
    can only do that *after* reading the disc, which is a minute in and past the point
    the user committed. The disc's own size is known the moment it spins up, so the
    tray can say it up front.

    Hedged on purpose: this compares the whole **disc**, and what actually gets written
    is the main title, which is smaller by an unknown amount. So it is a caution and
    never a refusal — the certainty stays where the real number is.
    """
    if SH.Transport.supports_follow_copy:
        return None                      # streaming, so size stopped mattering
    size = drive.get("size_bytes") or 0
    free = P.storage_status().get("free_bytes") or 0
    if not size or size + WINDOW_BYTES <= free:
        return None
    return ("This is a %d GB disc and there's %d GB free in staging. The film itself "
            "is smaller than the whole disc, so it may still fit — Riparr will say "
            "for certain once it has read it."
            % (size // 2 ** 30, free // 2 ** 30))


def _autorip_state():
    """Auto Rip's prerequisites, every one of them, whether or not it is met.

    This used to return only the things that were wrong. That is the right shape for
    refusing to enable the switch and the wrong shape for the question people actually
    arrive with, which is "it isn't auto ripping, why not" — asked most often when the
    switch is ON and something downstream of it has since broken. A list that is empty
    when things are fine cannot answer that; a checklist can.

    Three states, and only `fail` blocks:

      ok    met, with `detail` naming what met it
      warn  Auto Rip still runs, but a disc put in right now may not get ripped --
            the card is full, or the key dies this week
      fail  Auto Rip cannot work at all and the switch stays unavailable
    """
    mk = P.makemkv_status()
    share = db.default_share()
    drives = P.optical_drives()
    cap = _capacity(P.storage_status()["free_bytes"])
    warn_days = int(db.get("warn_key_days") or 7)
    checks = []

    def check(what, state, detail, why=None, where=None):
        checks.append({"what": what, "state": state, "detail": detail,
                       "why": why, "where": where})

    # 1. Something to read discs with, in software...
    if mk.get("installed"):
        check("Riparr can read discs", "ok",
              "MakeMKV %s" % (mk.get("version") or "installed"))
    else:
        check("Riparr can read discs", "fail", "MakeMKV isn't installed",
              "Riparr has no way to read a disc without it.", "#/settings/general")

    # 2. ...and a licence for it. Kept separate from the install because a key that
    #    lapsed last week is a working install and a dead appliance, and those two
    #    facts want separate lines.
    days = mk.get("days_left")
    if days is not None and not P.trust_dates():
        days = None                       # a day count computed against a wrong clock
    if not mk.get("installed"):
        check("The MakeMKV key is current", "fail", "Nothing installed to key yet",
              "Install MakeMKV first.", "#/settings/general")
    elif not db.get("makemkv_key"):
        check("The MakeMKV key is current", "fail", "No key entered",
              "Encrypted discs won't decode without one.", "#/settings/general")
    elif mk.get("installed") and not P.MOCK and not MK.key_is_registered():
        # The key is in Riparr but not in MakeMKV. This was the silent case: the row
        # above went green on a stored key while makemkvcon had never been given one.
        check("The MakeMKV key is current", "fail", "Entered but not registered",
              "Re-save the key in Settings to write it to MakeMKV.",
              "#/settings/general")
    elif days is not None and days <= 0:
        check("The MakeMKV key is current", "fail", "Expired",
              "Every rip will fail until it's replaced.", "#/settings/general")
    elif mk.get("key_stale"):
        check("The MakeMKV key is current", "warn", "A newer key has been published",
              "Yours is an older key and may already be dead. Settings offers the "
              "current one.", "#/settings/general")
    elif days is not None and days <= warn_days:
        check("The MakeMKV key is current", "warn",
              "%s key, %d day%s left" % ((mk.get("key_type") or "Beta").capitalize(),
                                         days, "" if days == 1 else "s"),
              "Rips start failing the day it lapses.", "#/settings/general")
    else:
        check("The MakeMKV key is current", "ok",
              "%s key%s" % ((mk.get("key_type") or "Licence").capitalize(),
                            ", %d days left" % days if days is not None else ""))

    # 3. Something to read discs with, in hardware. What it *reads* belongs on this
    #    row too: "a drive is attached" and "that drive can read the discs on your
    #    shelf" are the same prerequisite asked one level deeper, and the second is
    #    the one that ruins an evening.
    if drives:
        d = drives[0]
        name = " ".join(x for x in (d.get("vendor"), d.get("model")) if x)
        check("A drive to read them in", "ok",
              "%s · %s" % (name or "Optical drive", _reads_phrase(d)))
    else:
        check("A drive to read them in", "fail", "No optical drive detected",
              "A working USB bridge appears here even with no disc in the tray.",
              "#/system/status")

    # 4. Somewhere for the finished file to go. Configured and *tested* are one row:
    #    an untested share is not a second problem, it is the same problem earlier.
    if not share:
        check("Somewhere to put the files", "fail", "No library share",
              "Finished rips would have nowhere to go.", "#/settings/library")
    elif not share.get("verified_at"):
        check("Somewhere to put the files", "fail", "Share hasn't been tested",
              "Riparr writes a test file before it will trust a share with a rip.",
              "#/settings/library")
    else:
        check("Somewhere to put the files", "ok",
              "//%s/%s" % (share["host"], share["path"]))

    # 5. Room to work. Not a blocker: under D11 a small buffer means stream mode, not
    #    a refused disc. "degraded" is the one case where a disc really is turned away,
    #    which is a switch that looks on and a box that looks broken.
    if cap["mode"] == "degraded":
        check("Room to work", "warn", cap["phrase"],
              "Discs are refused before they start rather than failing at 90%.",
              "#/system/status")
    else:
        check("Room to work", "ok", cap["phrase"])

    # Kept in the shape the enable endpoint and older API callers expect: the headline
    # of a failing check is its `detail`, which is the specific thing that is wrong.
    blockers = [{"what": c["detail"], "why": c["why"], "where": c["where"]}
                for c in checks if c["state"] == "fail"]

    ready = not blockers
    enabled = bool(db.get("auto_rip")) and ready
    return {"enabled": enabled, "ready": ready, "blockers": blockers,
            "checks": checks, "requested": bool(db.get("auto_rip"))}


class AutoRip(BaseModel):
    enabled: bool


@app.get("/api/autorip")
def autorip(user=Depends(require_user)):
    return _autorip_state()


@app.post("/api/autorip")
def autorip_set(body: AutoRip, user=Depends(require_user)):
    st = _autorip_state()
    if body.enabled and not st["ready"]:
        raise HTTPException(
            status_code=400,
            detail="Auto Rip isn't ready yet — %s." % st["blockers"][0]["what"])
    db.set("auto_rip", body.enabled)
    return _autorip_state()


# ─────────────────────────────── settings ───────────────────────────────

# Settings that are credentials. They go out to the browser as a placeholder and come
# back the same way when untouched, which is what makes "save" on a page you did not
# retype your SMTP password into not wipe it. `list_shares` established the precedent
# of never returning a stored password at all; these follow it.
SECRET_SETTINGS = ("smtp_password", "ntfy_token", "tmdb_token")
SECRET_MASK = "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"


def _redact(s):
    s = dict(s)
    s.pop("session_secret", None)
    # Wi-Fi PSKs. Not masked but removed: unlike an SMTP password there is no field on
    # any settings page to type one back into, so a mask would only be a thing to
    # accidentally save. The Network page has its own endpoints.
    s.pop("wifi_networks", None)
    for k in SECRET_SETTINGS:
        if s.get(k):
            s[k] = SECRET_MASK
    return s


@app.get("/api/settings")
def get_settings(user=Depends(require_user)):
    return _redact(db.all_settings())


@app.put("/api/settings")
async def put_settings(request: Request, user=Depends(require_user)):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected an object")
    body.pop("session_secret", None)
    body.pop("seen_url", None)
    if (body.get("public_url") or "").strip():
        try:
            NT._check_url(body["public_url"].strip())
        except NT.BadWebhookURL:
            raise HTTPException(status_code=400,
                                detail="Riparr's address must start with http:// or https://")
    for k, v in body.items():
        if k in SECRET_SETTINGS and v == SECRET_MASK:
            continue                      # unchanged; do not overwrite with the mask
        db.set(k, v)

    # The MakeMKV key is not an ordinary setting: storing it registers nothing. The
    # Settings page saves it through here (only the setup wizard uses the dedicated
    # endpoint), so the write into MakeMKV's own settings.conf has to happen on this
    # path too, or registering would work in the wizard and silently not afterwards.
    if "makemkv_key" in body and body["makemkv_key"] != SECRET_MASK:
        MK.apply_key(body["makemkv_key"])
        MK.record_expiry_for(body["makemkv_key"])

    # Some settings stop meaning anything in direct mode -- see db.DIRECT_FORBIDS. The
    # response is the whole settings object, so a client that re-renders from it picks
    # the correction up for free; `adjusted` is there for one that wants to say why.
    adjusted = db.reconcile(body)

    out = _redact(db.all_settings())
    if adjusted:
        out["adjusted"] = adjusted
    return out


@app.get("/api/notifications")
def notifications(user=Depends(require_user)):
    return {"events": [{"key": k, "label": label, "default": on} for k, label, on in NT.EVENTS],
            "enabled": NT.enabled_events(),
            "configured": NT.configured(),
            "seen_url": db.get("seen_url") or ""}


class NotifyTest(BaseModel):
    channel: str


@app.post("/api/notifications/test")
def notifications_test(body: NotifyTest, user=Depends(require_user)):
    r = NT.test(body.channel)
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r.get("error"))
    return r


class DiscordCheck(BaseModel):
    url: str = ""


@app.post("/api/notifications/discord/check")
def notifications_discord_check(body: DiscordCheck = DiscordCheck(),
                                user=Depends(require_user)):
    """Confirm a Discord webhook URL points at something real, and say what.

    Deliberately not an error: a bad URL here is the normal outcome of pasting the
    wrong half of something, and the page shows the reason next to the field rather
    than as a failure.
    """
    return NT.discord_check(body.url or None)


# ─────────────────────────────── shares ───────────────────────────────

class ShareQuery(BaseModel):
    host: str
    username: str = ""
    password: str = ""


class ShareTest(BaseModel):
    host: str
    share: str
    path: str = ""
    username: str = ""
    password: str = ""


class ShareCreate(ShareTest):
    name: str = ""


@app.exception_handler(SH.SmbToolMissing)
def _smb_tool_missing(request, exc):
    """A missing smbclient is a fixable setup problem, not a server fault.

    Unhandled it becomes a 500, which tells the user "Request failed (500)" and puts
    the only useful sentence — FileNotFoundError: 'smbclient' — in a log they will
    never read.
    """
    return JSONResponse(status_code=503, content={"detail": exc.message})


@app.get("/api/shares")
def shares_list(user=Depends(require_user)):
    """Every share, and what each kind of disc is currently pointed at.

    Returned together because the Library page draws them together: a share list with
    no indication of what writes to it is a list of network paths, and the question
    people actually have is "where do my films go".
    """
    return {"shares": db.list_shares(),
            "destinations": db.destinations(),
            "library": {k: P.library_status(db.destination(k)[0]) for k in db.KINDS}}


# ─────────────────────────────── naming ───────────────────────────────

@app.get("/api/naming")
def naming_info(user=Depends(require_user)):
    """The presets the Library page offers, and the tokens a template can use."""
    return {"movie": NM.MOVIE_PRESETS, "tv": NM.TV_PRESETS, "tokens": NM.TOKENS}


class TmdbTest(BaseModel):
    token: str = ""


@app.post("/api/tmdb/test")
def tmdb_test(body: TmdbTest = TmdbTest(), user=Depends(require_user)):
    """Check a TMDb key before saving it -- or the saved one, when none is given."""
    key = body.token.strip()
    if key == SECRET_MASK:
        key = ""
    if not key and not TM.configured():
        return {"ok": False, "message": "No TMDb key is set."}
    return TM.check(key or None)


@app.get("/api/tmdb/search")
def tmdb_search(q: str = "", user=Depends(require_user)):
    """Films for the "which film is this?" question's search box."""
    title, year = TM.split(q)
    return {"results": _with_posters(TM.search(title, year)[:8]),
            "configured": TM.configured()}


class NamingPreview(BaseModel):
    template: str
    kind: str = "movie"


@app.post("/api/naming/preview")
def naming_preview(body: NamingPreview, user=Depends(require_user)):
    """What a template makes of a sample 4K disc, so a long one can be read."""
    return {"path": NM.preview(body.template, "tv" if body.kind == "tv" else "movie")}


class DiscoverQuery(BaseModel):
    subnets: str = ""


@app.post("/api/shares/discover")
def shares_discover(body: DiscoverQuery = DiscoverQuery(), user=Depends(require_user)):
    """Look for SMB servers. `subnets` overrides which networks are swept, and is
    remembered once it finds something, so the next scan uses it without asking."""
    try:
        r = SH.discover(subnets=body.subnets or None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if body.subnets.strip() and r["hosts"]:
        db.set("scan_subnets", r["subnets"])
    return r


@app.post("/api/shares/browse")
def shares_browse(body: ShareQuery, user=Depends(require_user)):
    return SH.list_shares(body.host, body.username, body.password)


@app.exception_handler(SH.BadPath)
def _bad_share_path(request, exc):
    """A share or folder that cannot be used. The user's typing, not a server fault."""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.post("/api/shares/test")
def shares_test(body: ShareTest, user=Depends(require_user)):
    return SH.test_write(body.host, body.share, body.path, body.username, body.password)


@app.post("/api/shares")
def shares_create(body: ShareCreate, user=Depends(require_user)):
    result = SH.test_write(body.host, body.share, body.path,
                           body.username, body.password)
    if not result.get("ok"):
        raise HTTPException(status_code=400,
                            detail=result.get("error", "The write test failed"))
    # Store what was proved, not what was typed. Normalisation can move a segment from
    # the share box into the folder box -- somebody pasting `Media/Movies` into "Share"
    # gets share `Media`, folder `Movies` -- and storing the typed version would save a
    # path the write test never used.
    share, path = result["share"], result["path"]
    sid = db.add_share(body.name or SH.describe(body.host, share, path).lstrip("/"),
                       body.host, "/".join(x for x in (share, path) if x),
                       body.username, body.password)
    db.mark_share_verified(sid)
    return {"ok": True, "id": sid, "test": result}


@app.delete("/api/shares/{share_id}")
def shares_delete(share_id: int, user=Depends(require_user)):
    """Remove a share, and stop anything pointing at it.

    A destination naming a share that no longer exists falls back to the default one
    anyway, but leaving the dead id in settings means the page shows a blank selection
    and the next share to be given that id inherits somebody else's films.
    """
    db.delete_share(share_id)
    for kind, (share_key, _, _) in db.KINDS.items():
        if db.get(share_key) == share_id:
            db.set(share_key, None)
    return {"ok": True}


# ─────────────────────────────── queue ───────────────────────────────

def _job_out(j):
    """Shape a job row for the interface: parse the JSON column, drop the noise."""
    j = dict(j)
    if j.get("titles"):
        try:
            j["titles"] = json.loads(j["titles"])
        except (ValueError, TypeError):
            j["titles"] = []
    if j.get("episode_plan"):
        j["episode_plan"] = db.episode_plan(j)
    # Which stage is running and since when. The queue's counting timer is built from
    # this against the medians: the two slowest stages of a rip -- the disc scan and
    # the decrypt pass -- can report no progress at all, so "this box usually takes
    # nine minutes and you are four minutes in" is the only number available.
    try:
        raw = json.loads(j.get("stages") or "[]")
    except (ValueError, TypeError):
        raw = []
    j["stages"] = db.job_stages(j)
    open_now = next((st for st in reversed(raw) if st.get("ended") is None), None)
    j["stage_name"] = open_now.get("name") if open_now else None
    j["stage_started"] = open_now.get("started") if open_now else None
    if j.get("candidates"):
        try:
            j["candidates"] = _with_posters(json.loads(j["candidates"]))
        except (ValueError, TypeError):
            j["candidates"] = []
    # Where it's going, before it gets there -- so a wrong name or preset is caught
    # before a forty-minute rip rather than after.
    if j.get("state") not in db.FINAL_STATES:
        j["planned"] = RIP.planned_destination(j)
    return j


def _with_posters(films):
    """TMDb results with a poster thumbnail the browser can load -- through our own
    image proxy, so the browser never talks to TMDb and the page needs no key."""
    out = []
    for f in films or []:
        f = dict(f)
        if f.get("poster_path"):
            f["poster"] = "/api/artwork/image/%s" % ART._remember(
                TM.IMAGES + "w185" + f["poster_path"])
        out.append(f)
    return out


@app.get("/api/queue")
def queue(user=Depends(require_user)):
    jobs = [_job_out(j) for j in db.list_jobs(states=db.ACTIVE_STATES)]
    # What a rip usually costs on this machine, from this machine's own history. The
    # slow half of a rip cannot report progress at all -- see db.typical_job_seconds --
    # so a fuzzy "usually done by" beats an empty space, provided it is labelled as the
    # guess it is and only offered once there is something to average.
    # Estimates are per disc family. A Blu-ray and a DVD are not the same job wearing
    # different labels -- Megamind saved for 10m40s and Arthur Christmas is four times
    # the data -- so a median that mixes them describes neither. `kind` is taken from
    # whatever is in flight, falling back to the tray, so the numbers on screen are
    # about the disc on screen.
    # Jobs that have given the disc back and are still crossing the network. Split out
    # so the page can show them as a quiet strip rather than as competing rip panels --
    # the user is watching the disc that is in the drive now, not the one on its way.
    sending = [j for j in jobs if j.get("state") in db.SENDING_STATES]
    active = next((j for j in jobs if j.get("disc_family")), None)
    kind = active.get("disc_family") if active else _tray_family()
    typical, samples = db.typical_job_seconds(kind=kind)
    stages = db.typical_stage_seconds(kind=kind)
    # Per-stage medians as well as the total. The total answers "when will this be
    # done"; the stages answer "should the fact that nothing has moved for six minutes
    # worry me", which is the question that actually gets asked.
    # The rip that just finished, so the page can show where it went once the job has
    # left the queue. A toast was the only trace before, and it was gone in three
    # seconds. Twelve hours: long enough to come back to, short enough that it is news.
    filed = db.last_finished(time.time() - 12 * 3600)
    return {"jobs": [j for j in jobs if j.get("state") not in db.SENDING_STATES],
            "sending": sending,
            "filed": _filed_out(filed) if filed else None,
            # What MakeMKV has been saying, newest last -- only while something is
            # happening, for the rip card's "What MakeMKV is doing".
            "makemkv": RIP.makemkv_recent() if jobs else [],
            "drive_busy": bool(db.drive_busy()),
            "typical_seconds": typical, "typical_samples": samples,
            "typical_stages": stages, "typical_kind": kind,
            "stage_labels": db.stage_labels(db.get("transfer_mode") == "direct"),
            # Both sets, so each job's stage is named for how *it* is travelling: a
            # staged rip isn't "writing to your library", whatever the setting says.
            "stage_label_sets": {"direct": db.stage_labels(True),
                                 "staged": db.stage_labels(False)},
            "stage_order": db.STAGE_ORDER}


def _filed_out(job):
    """The last finished rip, with the retries History would offer for it."""
    j = _job_out(job)
    local = j.get("local_path")
    j["local_exists"] = bool(local and os.path.exists(local))
    j["retries"] = _retries_for(j)
    j["titles"] = None
    return j


def _tray_family():
    """What kind of disc is loaded, so an idle queue still estimates the right thing."""
    try:
        d = next((x for x in P.optical_drives() if x.get("present")), None)
        return RIP.disc_family(d) if d else None
    except Exception:
        return None


class RipRequest(BaseModel):
    force: bool = False


@app.post("/api/rip")
def rip_now(body: RipRequest = RipRequest(), user=Depends(require_user)):
    """Rip the disc that is in the tray, right now.

    The product had no manual verb at all before this: the only way to rip anything
    was to turn Auto Rip on and re-insert the disc. A page that correctly names the
    disc it can see and offers no way to act on it is the worst kind of broken,
    because everything on it looks like it is working.
    """
    job_id, why = RIP.enqueue(force=body.force)
    if not job_id:
        raise HTTPException(status_code=400, detail=why)
    return {"ok": True, "job_id": job_id}


@app.post("/api/queue/{job_id}/cancel")
def rip_cancel(job_id: int, user=Depends(require_user)):
    ok, message = RIP.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message}


@app.post("/api/queue/{job_id}/retry")
def rip_retry(job_id: int, user=Depends(require_user)):
    ok, message = RIP.resume_transfer(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message}


class VerifyRequest(BaseModel):
    mode: str = "quick"


@app.post("/api/queue/{job_id}/verify")
def rip_reverify(job_id: int, body: VerifyRequest = VerifyRequest(),
                 user=Depends(require_user)):
    """Check a finished job's file against the share again, without re-ripping.

    The read-back is the one stage that can fail for reasons that have nothing to do
    with the disc -- a NAS that went to sleep, a share that filled up, a box that ran
    out of RAM writing the temporary copy. Re-running it should not cost the forty
    minutes the rip did, and until now the only retry offered was the transfer.
    """
    if body.mode not in ("quick", "deep"):
        raise HTTPException(status_code=400, detail="Unknown verification mode.")
    ok, message = RIP.reverify(job_id, mode=body.mode)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message}


class DiscAnswer(BaseModel):
    title_index: int = None
    name: str = ""
    skip: bool = False
    # A season disc answers with rather more. Every field is optional and whatever is
    # left out keeps the value Riparr proposed, so the common answer -- "yes, that is
    # right" -- is still an empty body.
    season: int = None
    first_episode: int = None
    series_id: int = None
    include: List[int] = None           # title indexes to keep; None means keep all
    episode_titles: Dict[str, str] = None   # title index -> a name typed by hand
    order: List[int] = None             # title indexes, in the order they should go
    tmdb_id: int = None                 # a film picked from TMDb's suggestions


@app.post("/api/queue/{job_id}/answer")
def rip_answer(job_id: int, body: DiscAnswer, user=Depends(require_user)):
    """The other end of the "ask me" settings: `on_unknown_disc` for the name,
    `on_ambiguous_title` for which title is the film, and `on_season_disc` for the
    episode plan. One prompt answers all of them, because a disc that needs more than
    one question asked should not need answering more than once."""
    ok, message = RIP.answer(job_id, title_index=body.title_index,
                             name=(body.name or "").strip(), skip=body.skip,
                             season=body.season, first_episode=body.first_episode,
                             series_id=body.series_id, include=body.include,
                             episode_titles=body.episode_titles, order=body.order,
                             tmdb_id=body.tmdb_id)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message}


# ─────────────────────────────── answering from a notification ───────────────────────
#
# No sign-in: the signed token in the URL is the permission, and it can only give the
# one answer it was made for (see notify.read_answer). GET only shows the question and
# a button, because link previews and mail scanners open links too; POST answers. The
# ntfy app POSTs straight from the phone, so ntfy's buttons skip the page.

def _answer_page(title, lines, form=None, status=200):
    theme = html.escape(main_theme())
    body = "".join("<p>%s</p>" % ln for ln in lines)
    button = ("""<form method="post" style="margin-top:18px">
      <button class="btn primary wide" type="submit">%s</button></form>"""
              % html.escape(form) if form else "")
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Riparr</title>
<link rel="stylesheet" href="/static/app.css">
<link rel="stylesheet" href="/static/themes/%s.css">
<style>.gate-card p { margin: 10px 0 0; line-height: 1.5; } .gate-card .btn.wide { width: 100%%; }</style>
</head><body><div class="gate"><div class="gate-card">
<img class="gate-mark" src="/static/img/riparr-mark.png" alt="">
<h1>%s</h1>%s%s
<p><a href="/#/queue">Open Riparr</a></p>
</div></div></body></html>""" % (theme, html.escape(title), body, button)
    return HTMLResponse(page, status_code=status, headers={"Cache-Control": "no-store"})


def main_theme():
    return _theme_name(db.get("theme"))


def _answer_target(token):
    got = NT.read_answer(token)
    if got.get("error"):
        return got, None
    job = db.get_job(got["job"])
    if not job or job["state"] != "needs_input":
        return {"error": "This disc has already been answered."}, job
    return got, job


@app.get("/api/answer/{token}")
def answer_page(token: str):
    got, job = _answer_target(token)
    name = (job or {}).get("title") or (job or {}).get("disc_label") or "A disc"
    if got.get("error"):
        return _answer_page(name if job else "Riparr", [html.escape(got["error"])],
                            status=410 if job is None and "expired" in got["error"] else 200)
    return _answer_page(name, [html.escape(job.get("question") or "")], form=_answer_verb(got))


def _answer_verb(got):
    """The button reads as what it does: "Rip as The Thing (1982)"."""
    return "Rip as %s" % got["label"] if got["answer"] else got["label"]


@app.post("/api/answer/{token}")
def answer_from_notification(token: str, request: Request):
    """Answer a disc's question from a notification's button."""
    wants_page = "text/html" in (request.headers.get("accept") or "")
    got, job = _answer_target(token)
    if got.get("error"):
        if wants_page:
            return _answer_page("Riparr", [html.escape(got["error"])], status=409)
        raise HTTPException(status_code=409, detail=got["error"])
    ok, message = RIP.answer(got["job"], **got["answer"])
    if not ok:
        if wants_page:
            return _answer_page("Riparr", [html.escape(message)], status=400)
        raise HTTPException(status_code=400, detail=message)
    SY.component("Queue").info("Job %d answered from a notification: %s", got["job"], got["label"])
    done = ("Riparr is ripping it as %s." % got["label"] if got["answer"]
            else "Riparr is ripping it now.")
    if wants_page:
        return _answer_page(job.get("title") or job.get("disc_label") or "A disc",
                            [html.escape(done)])
    return {"ok": True, "message": done}


@app.get("/api/tv/search")
def tv_search(q: str = "", user=Depends(require_user)):
    """Series matching a name, for the picker on the episode-plan prompt.

    Proxied through the box rather than called from the browser so that the only thing
    talking to TVmaze is the box -- the same reasoning as the artwork proxy, minus the
    image. Returns an empty list rather than an error when TVmaze is unreachable,
    because a box with no internet must still be able to rip and file a season.
    """
    return {"results": TV.search_series(q, limit=8), "credit": "TVmaze"}


@app.get("/api/tv/episodes")
def tv_episode_list(series_id: int, season: int = None, user=Depends(require_user)):
    """Every episode of a series, so the prompt can show what a numbering will produce."""
    eps = TV.episodes(series_id)
    if season is not None:
        eps = [e for e in eps if e["season"] == season]
    return {"episodes": eps, "credit": "TVmaze"}


@app.post("/api/discs/{fingerprint}/rerip")
def disc_rerip(fingerprint: str, user=Depends(require_user)):
    """Re-rip a disc Riparr already knows.

    The button is pressed at the exact moment the disc is sitting on an open tray,
    because that is where a refused duplicate leaves it -- so this closes the tray
    rather than telling the user to. `_start_rerip` carries the rest.
    """
    return _start_rerip(fingerprint)


@app.post("/api/queue/{job_id}/rerip")
def rip_rerip(job_id: int, user=Depends(require_user)):
    """Read the disc again from the start, for a job whose rip is gone.

    Distinct from the disc-fingerprint form only in where the fingerprint comes from.
    A job that died before identification never got one, in which case this rips
    whatever is in the tray -- which is the best available reading of "try that again"
    when nobody, including Riparr, ever found out what that disc was.
    """
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="No such job.")
    return _start_rerip(job.get("fingerprint") or None,
                        what=job.get("title") or job.get("disc_label"))


def _start_rerip(fingerprint, what=None):
    """Pull the tray in if it is open, then queue this disc past the duplicate check.

    Two things have to be true at once and they fight each other. The duplicate check
    must not refuse this disc -- and the *disc watcher* may well get to it first, three
    seconds after the tray closes, with no idea a human asked for it. So the
    authorisation is armed on the disc rather than passed to one call: whichever path
    reaches `enqueue` first consumes it, and the loser is turned away by the
    already-working-on-a-disc guard rather than by ejecting the disc.
    """
    RIP.arm_force(fingerprint)
    d = next((x for x in P.optical_drives() if x.get("present")), None)
    if not d:
        ok, message = P.close_tray()
        if not ok:
            raise HTTPException(
                status_code=400,
                detail="Put %s in the tray and press Re-rip again. (%s)"
                       % (what or "the disc", message))
    job_id, why = RIP.enqueue(force=True, expect=fingerprint)
    if not job_id:
        # The watcher beat us to it. That is a success wearing an error's clothes:
        # the disc it picked up is the one that was armed, so it is already being
        # ripped and the only correct answer is to point at that job.
        active = db.active_job()
        if active and (not fingerprint or active.get("fingerprint") in (fingerprint, "")):
            return {"ok": True, "job_id": active["id"]}
        raise HTTPException(status_code=400, detail=why)
    return {"ok": True, "job_id": job_id}


@app.get("/api/history")
def history(user=Depends(require_user)):
    """Every finished job, with what each stage cost and what can still be retried.

    History is the data page: the question it answers is "what happened, how long did
    each part take, and what can I do about it". The four retry verbs are computed
    here rather than in the browser, because whether a retry is possible depends on
    something only the box can see -- whether the staged file is still in staging.
    """
    jobs = []
    for j in db.list_jobs(states=["done", "failed", "cancelled"], limit=100):
        j = _job_out(j)                       # this is what parses `stages`
        local = j.get("local_path")
        j["local_exists"] = bool(local and os.path.exists(local))
        j["retries"] = _retries_for(j)
        jobs.append(j)
    # History spans every kind of disc, so its key is per family rather than one
    # blended median that is wrong about all of them.
    return {"jobs": jobs,
            "typical_by_kind": {k: db.typical_stage_seconds(kind=k)
                                for k in ("dvd", "bluray", "uhd")},
            "typical_stages": db.typical_stage_seconds(),
            "stage_order": db.STAGE_ORDER, "stage_labels": db.STAGE_LABEL}


def _retries_for(j):
    """Which of the four retry verbs apply to this job, and why.

    Each one is offered only when it would actually do something:

    * **Retry rip** -- the rip itself is gone or was never made, so the disc has to go
      back in. Always available on a job that did not finish; it needs the disc.
    * **Retry upload** -- the file is still staged on the card, so the expensive half
      is already paid for and this is a re-copy, not a re-rip.
    * **Size check again** / **Full check** -- the file reached
      the share, so it can be checked again without touching the disc. Deep needs the
      staged copy to compare against; fast only needs the size, so it needs the staged
      copy too (that is what the size is compared *to*).
    """
    out = []
    state, local = j.get("state"), j.get("local_exists")
    landed = bool(j.get("dest_path"))
    if state != "done":
        if local:
            out.append({"action": "upload", "label": "Retry upload",
                        "why": "The rip is still in staging, so this is a re-copy "
                               "rather than a re-read of the disc."})
        out.append({"action": "rip", "label": "Retry rip", "needs_disc": True,
                    "why": "Put the disc back in the tray and Riparr will read it "
                           "again from the start."})
    if landed and local:
        done_mode = j.get("verified_mode")
        out.append({"action": "verify-quick", "label": "Size check again",
                    "why": "Compares the size on your library against the rip. "
                           "Seconds, and it catches a truncated transfer."})
        out.append({"action": "verify-deep", "label": "Full check",
                    "why": ("Reads the whole file back and hashes it. Slow, and it "
                            "needs as much free space again as the film."
                            + (" This one has only ever been size-checked."
                               if done_mode == "quick" else ""))})
    return out


@app.get("/api/discs")
def discs(user=Depends(require_user)):
    return {"discs": db.list_discs()}


@app.delete("/api/discs/{fingerprint}")
def disc_forget(fingerprint: str, user=Depends(require_user)):
    db.forget_disc(fingerprint)
    return {"ok": True}


# ─────────────────────────────── makemkv ───────────────────────────────

class MakeMKVKey(BaseModel):
    key: str


@app.get("/api/makemkv")
def makemkv(user=Depends(require_user)):
    return MK.info()


@app.get("/api/makemkv/sites")
def makemkv_sites_state(user=Depends(require_user)):
    """Whatever is known right now, without waiting for anything.

    The General settings page draws before this has an answer and polls here until it
    does, so this must never block -- that is the whole point of the split.
    """
    sites, checking = MK.site_status()
    return {"sites": sites, "checking": checking}


@app.post("/api/makemkv/sites")
def makemkv_sites(user=Depends(require_user)):
    """Re-probe now and wait for the result.

    The only path that is allowed to block on somebody else's web server, because it
    is the one the user asked for by pressing "Check again".
    """
    sites, checking = MK.site_status(force=True, wait=True)
    return {"sites": sites, "checking": checking}


# ── full-disc backup's DVD half ──
# MakeMKV backs up Blu-ray and UHD itself. DVDs need dvdbackup and libdvdcss, which are
# built into the image.

@app.get("/api/backup/tools")
def backup_tools(user=Depends(require_user)):
    return BK.status()


@app.get("/api/makemkv/renewal")
def makemkv_renewal(user=Depends(require_user)):
    """A key renewal the page has not mentioned yet. Asked once, when the page loads."""
    return {"renewal": MK.renewal_notice()}


@app.post("/api/makemkv/renewal/dismiss")
def makemkv_renewal_dismiss(user=Depends(require_user)):
    MK.dismiss_renewal_notice()
    return {"ok": True}


@app.get("/api/artwork")
def artwork_lookup(label: str = "", user=Depends(require_user)):
    """Cover art for a disc label, only when the match is beyond doubt.

    Returns `{"ok": false}` far more often than not, and that is the intended
    behaviour: a confidently wrong poster is worse than a plain background.
    """
    if not db.get("disc_artwork", True):
        return {"ok": False, "reason": "disabled"}
    hit = ART.look_up(label)
    if not hit:
        return {"ok": False}
    return {"ok": True, "title": hit["title"], "confidence": hit["confidence"],
            "image": "/api/artwork/image/%s" % hit["token"]}


@app.get("/api/artwork/image/{token}")
def artwork_image(token: str, user=Depends(require_user)):
    """Proxy the matched image.

    The caller passes a token this process issued, never a URL: an endpoint that
    fetches whatever it is handed is an open proxy sitting inside somebody's LAN.
    Cached in the browser for a day -- it is decoration, and the disc will be gone
    long before it goes stale.
    """
    blob, ctype = ART.image_bytes(token)
    if not blob:
        raise HTTPException(status_code=404, detail="No image for that token.")
    return Response(content=blob, media_type=ctype,
                    headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/makemkv/beta-key")
def makemkv_beta_key(refresh: bool = False, user=Depends(require_user)):
    """The beta key GuinpinSoft publishes, fetched so the user does not have to.

    MakeMKV is free during beta behind a key that rolls over roughly monthly. Reading
    it off a forum and noticing when it lapses is a chore the box is better placed to
    do than its owner.
    """
    return MK.beta_key(force=refresh)


@app.post("/api/makemkv/key")
def makemkv_key(body: MakeMKVKey, user=Depends(require_user)):
    """Save the key *and* register it. Those used to be the same call doing only the first.

    Registration is local -- it writes app_Key into MakeMKV's own settings.conf -- so it
    works whether or not makemkv.com is reachable. The expiry is then re-derived from
    whatever source is already cached, so the countdown starts from the key just entered
    rather than waiting for the next scheduled lookup.
    """
    key = body.key.strip()
    db.set("makemkv_key", key)

    ok, message = MK.apply_key(key)

    # Cache-only: the user is waiting on this response, and a slow forum must not be in
    # the way of a key they have already pasted in.
    MK.record_expiry_for(key)

    return {"ok": ok, "registered": ok, "message": message,
            "expires": db.get("makemkv_key_expires") or None,
            "stale": bool(db.get("makemkv_key_stale"))}


# ─────────────────────────────── updates ───────────────────────────────

@app.get("/api/update")
def update_check(user=Depends(require_user)):
    return updater.check()


@app.post("/api/update/install")
def update_install(user=Depends(require_user)):
    return updater.install()


# ─────────────────────────── config backup ───────────────────────────

@app.get("/api/config/export")
def config_export(user=Depends(require_user)):
    s = db.all_settings()
    s.pop("session_secret", None)
    return JSONResponse(
        {"version": __version__, "exported_at": int(time.time()),
         "settings": s, "shares": db.list_shares()},
        headers={"Content-Disposition": 'attachment; filename="riparr-config.json"'})


@app.post("/api/config/import")
async def config_import(request: Request, user=Depends(require_user)):
    """Restore settings *and* shares, and say plainly what could not be restored.

    This used to import settings, ignore the `shares` list it had itself exported, and
    answer `{"ok": true}` -- so restoring onto a fresh box looked like it had worked,
    and the share, which is the one thing without which nothing rips, was quietly not
    there.

    Share passwords are deliberately not exported, so a restored share arrives without
    one and is reported as needing it rather than being silently created broken. That
    keeps the export file from being a credential for your NAS on top of everything else
    it already carries.
    """
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected an object")

    settings = body.get("settings") or {}
    for k, v in settings.items():
        if k != "session_secret":
            db.set(k, v)

    # Registering the key is not a db.set -- see put_settings.
    if "makemkv_key" in settings:
        MK.apply_key(settings["makemkv_key"])
        MK.record_expiry_for(settings["makemkv_key"])

    existing = {(s["host"], s["path"]) for s in db.list_shares()}
    restored, need_password = [], []
    for sh in (body.get("shares") or []):
        host, path = sh.get("host"), sh.get("path")
        if not host or not path or (host, path) in existing:
            continue
        db.add_share(sh.get("name") or "%s/%s" % (host, path), host, path,
                     sh.get("username") or "", "",
                     make_default=bool(sh.get("is_default")))
        existing.add((host, path))
        restored.append("%s/%s" % (host, path))
        need_password.append("%s/%s" % (host, path))

    parts = ["%d setting%s restored" % (len(settings), "" if len(settings) == 1 else "s")]
    if restored:
        parts.append("%d share%s restored" % (len(restored),
                                              "" if len(restored) == 1 else "s"))
    if need_password:
        parts.append("re-enter the password for %s before it can be used"
                     % ", ".join(need_password))
    return {"ok": True, "settings_imported": len(settings),
            "shares_restored": restored, "shares_need_password": need_password,
            "message": ". ".join(parts) + "."}


# ──────────────────── system: tasks, events, logs, backups ────────────────────

@app.get("/api/system/tasks")
def system_tasks(user=Depends(require_user)):
    return {"scheduled": SY.task_list(), "queue": SY.task_history(limit=20)}


@app.post("/api/system/tasks/{name}")
def system_task_run(name: str, user=Depends(require_user)):
    r = SY.run_task(name, trigger="manual")
    if r is None:
        raise HTTPException(status_code=404, detail="No such task")
    return r


@app.get("/api/system/events")
def system_events(limit: int = 50, offset: int = 0, levels: str = "",
                  user=Depends(require_user)):
    wanted = [l for l in levels.split(",") if l] or None
    return SY.events(limit=min(limit, 200), offset=offset, levels=wanted)


@app.delete("/api/system/events")
def system_events_clear(user=Depends(require_user)):
    SY.clear_events()
    return {"ok": True}


@app.get("/api/system/logs")
def system_logs(user=Depends(require_user)):
    return {"path": SY.LOG_DIR, "files": SY.log_files()}


@app.get("/api/system/logs/live")
def system_logs_live(after: int = 0, debug: bool = False, user=Depends(require_user)):
    """Log lines newer than `after`, for the live log. Polled about once a second."""
    levels = None if debug else ("info", "warning", "error", "critical")
    return SY.LIVE.since(after, levels)


_SECRET_WORDS = ("password", "token", "secret", "key", "webhook", "session")


def _scrub(obj):
    """A copy with anything that looks like a credential replaced, for diagnostics."""
    if isinstance(obj, dict):
        return {k: ("[redacted]" if v and any(w in str(k).lower() for w in _SECRET_WORDS)
                    else _scrub(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


@app.get("/api/system/diagnostics")
def system_diagnostics(user=Depends(require_user)):
    """Everything worth sending with a bug report, in one zip: logs, recent events, the
    last raw MakeMKV scan, recent jobs, and status and settings with every password,
    token, key and webhook taken out."""
    import io
    import zipfile
    buf = io.BytesIO()
    budget = 40 * 1024 * 1024
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in SY.log_files():
            path = SY.log_path(f["name"])
            if path and f["size"] <= budget:
                z.write(path, "logs/" + f["name"])
                budget -= f["size"]
        dump = lambda name, data: z.writestr(name, json.dumps(data, indent=2, default=str))
        dump("events.json", SY.events(limit=500))
        try:
            dump("status.json", _scrub(status(user)))
        except Exception as e:
            z.writestr("status-error.txt", str(e))
        dump("settings.json", _scrub(db.all_settings()))
        dump("shares.json", _scrub([dict(r) for r in db.list_shares()]))
        dump("jobs.json", _scrub([dict(j) for j in db.list_jobs(limit=20)]))
        z.writestr("disc-scan.txt", RIP.last_scan_raw() or "(no disc has been scanned since "
                                                         "Riparr started)\n")
        env = {k: v for k, v in os.environ.items()
               if k.startswith(("RIPARR_", "MAKEMKV_")) or k in ("PUID", "PGID", "UMASK", "TZ")}
        dump("about.json", _scrub({"version": __version__, "runtime": P.runtime(),
                                   "system": P.system_status(), "environment": env,
                                   "makemkv": P.makemkv_status()}))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return Response(content=buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition":
                             'attachment; filename="riparr-diagnostics-%s.zip"' % stamp})


@app.get("/api/system/logs/{name}")
def system_log_download(name: str, user=Depends(require_user)):
    path = SY.log_path(name)
    if not path:
        raise HTTPException(status_code=404, detail="No such log file")
    return FileResponse(path, media_type="text/plain", filename=name)


@app.delete("/api/system/logs")
def system_logs_clear(user=Depends(require_user)):
    return {"ok": True, "deleted": SY.delete_log_files()}


@app.get("/api/system/backups")
def system_backups(user=Depends(require_user)):
    return {"path": SY.BACKUP_DIR, "keep": SY.BACKUP_KEEP, "backups": SY.backups()}


@app.post("/api/system/backups/upload")
async def system_backup_upload(file: UploadFile = File(...), user=Depends(require_user)):
    r = SY.import_backup(file.filename or "upload", await file.read())
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r.get("error", "Restore failed"))
    return r


@app.post("/api/system/backups")
def system_backup_create(user=Depends(require_user)):
    return SY.create_backup(kind="manual")


@app.get("/api/system/backups/{name}")
def system_backup_download(name: str, user=Depends(require_user)):
    path = SY.backup_path(name)
    if not path:
        raise HTTPException(status_code=404, detail="No such backup")
    return FileResponse(path, media_type="application/zip", filename=name)


@app.post("/api/system/backups/{name}/restore")
def system_backup_restore(name: str, user=Depends(require_user)):
    r = SY.restore_backup(name)
    if not r.get("ok"):
        raise HTTPException(status_code=404, detail=r.get("error", "Restore failed"))
    return r


@app.delete("/api/system/backups/{name}")
def system_backup_delete(name: str, user=Depends(require_user)):
    if not SY.delete_backup(name):
        raise HTTPException(status_code=404, detail="No such backup")
    return {"ok": True}


# ─────────────────────────────── static ───────────────────────────────

class RevalidatingStatic(StaticFiles):
    """Static files the browser must revalidate rather than assume.

    With no Cache-Control at all, browsers apply a heuristic freshness lifetime and
    happily serve a stale app.js for hours -- so an upgraded box keeps showing the old
    interface and the user is told to "hard refresh", which is not an answer an
    appliance gets to give. `no-cache` does not mean "do not store": the file is still
    cached, it is just revalidated, so the normal case is a 304 with no body. On a LAN
    that is free, and a plain reload always shows the version that is installed.
    """

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/static", RevalidatingStatic(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"),
                        headers={"Cache-Control": "no-cache"})


@app.get("/{path:path}")
def spa(path: str):
    """Client-side routing: unknown paths return the shell, not a 404.

    The file lookup is contained to STATIC. `os.path.join` on an attacker path with
    `../` in it happily walks out of the static directory, and FileResponse would then
    serve any file the service account can read — the database (session secret, password
    hashes, the share password) included, with no login. So resolve the real path and
    refuse anything that is not inside STATIC, the same guard system.py already uses for
    log and backup downloads. Falling through to the shell is the right refusal here:
    a traversal attempt is not a route, so it gets the same answer any other non-file
    path does rather than a 403 that confirms the file exists.
    """
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="No such endpoint")
    if path:
        candidate = os.path.realpath(os.path.join(STATIC, path))
        root = os.path.realpath(STATIC)
        if (candidate == root or candidate.startswith(root + os.sep)) \
                and os.path.isfile(candidate):
            return FileResponse(candidate)
    return FileResponse(os.path.join(STATIC, "index.html"))
