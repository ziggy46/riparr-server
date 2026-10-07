"""
MakeMKV: consent, fetch, verify, install.

MakeMKV is made by GuinpinSoft, not by us. Its EULA is an agreement between the user and
GuinpinSoft — "by installing or using this Software, you agree to be bound by the terms"
— and that agreement cannot be given on somebody else's behalf. So nothing here downloads
a single byte before the user has explicitly accepted (D14).

Riparr invokes `makemkvcon` as a separate process over its CLI and never links against
libmakemkv, which is what keeps a GPL-3 codebase and a proprietary decoder at arm's
length.
"""
import calendar
import datetime
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

from . import platform as P

log = logging.getLogger("riparr.MakeMKV")

EULA_URL = "https://www.makemkv.com/eula/"
HOMEPAGE = "https://www.makemkv.com/"
FORUM_KEY_TOPIC = "https://forum.makemkv.com/forum/viewtopic.php?f=5&t=1053"
BUY_URL = "https://www.makemkv.com/buy/"

# A second place to ask, for the same reason there are mirrors for the binary below:
# forum.makemkv.com is regularly slow to the point of unusable -- four minutes to a first
# byte has been observed -- and an appliance that cannot tell you your key has lapsed
# because somebody else's phpBB is thrashing is an appliance that lies by omission.
#
# This one is not a scrape. It is an API built for exactly this, and it answers with the
# expiry as a Unix timestamp, which is the thing the forum only ever states in prose.
# It requires a descriptive User-Agent and publishes the timestamp after which it wants
# to be asked again; both are honoured.
AYRA_KEY_API = "https://cable.ayra.ch/makemkv/api.php?json"
USER_AGENT = "riparr-server/%s (+https://github.com/ziggy46/riparr-server)"

# The pinned release, its checksums, and every place it can be fetched from, all read
# from packaging/makemkv-manifest.json so that this service and the builder
# (deploy/build-tools.sh) can never disagree about what they are downloading.
#
# Why mirrors: makemkv.com was down for the whole of August 2026. An appliance whose
# first-run setup cannot complete because somebody else's web server is having a month
# is not an appliance. Sources are tried in order and the first whose bytes match the
# pinned sha256 wins.
#
# Why that is safe: the hash is pinned here, in the repository, and checked after every
# download. A mirror serving the wrong file -- stale, truncated or hostile -- fails the
# check and the next source is tried. Mirrors cost nothing in trust; dropping the hash
# would cost everything.
MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "packaging", "makemkv-manifest.json")

# A last-resort copy of the pin. If the manifest file is missing -- a partial install, a
# packaging mistake -- refusing to know the checksum would be worse than knowing it,
# because the checksum is the safety property and the URL list is only convenience.
_FALLBACK_MANIFEST = {
    "version": "2.0.0",
    "verified_against_official": True,
    "packages": [
        {"name": "makemkv-oss-2.0.0.tar.gz",
         "sha256": "435316b2d219eb48c880526557addd076b5f5e6de5171424c7651f9cac95b161",
         "urls": [{"where": "makemkv.com",
                   "url": "https://www.makemkv.com/download/makemkv-oss-2.0.0.tar.gz"}]},
        {"name": "makemkv-bin-2.0.0.tar.gz",
         "sha256": "f1265e74875a186efdfbbbec7459a64e969033515e53cbc4d805f0a374f0a124",
         "urls": [{"where": "makemkv.com",
                   "url": "https://www.makemkv.com/download/makemkv-bin-2.0.0.tar.gz"}]},
    ],
}


def _load_manifest():
    try:
        with open(MANIFEST_PATH) as f:
            m = json.load(f)
    except (OSError, ValueError):
        return dict(_FALLBACK_MANIFEST)
    if not m.get("packages"):
        return dict(_FALLBACK_MANIFEST)
    return m


MANIFEST = _load_manifest()


def sources(pkg):
    """Every place one package can be fetched from, in the order to try them."""
    return [u for u in pkg.get("urls", []) if u.get("url")]


# ─────────────────────── is MakeMKV's own infrastructure up? ───────────────────────
#
# This matters more than it should. As of 2026-08 `makemkv.com` has been down for
# weeks, which means the installer cannot fetch and -- because beta keys are published
# on the forum and rotate -- the way to get a working key is a forum post. The two are
# on different hosts and fail independently, so they are tracked separately: "the site
# is down but the forum is up" is the exact situation, and it is the difference between
# "you are stuck" and "go here and copy the key".

SITES = [
    {"key": "site", "name": "makemkv.com", "url": HOMEPAGE,
     "why": "Where MakeMKV itself is downloaded from when the image is built. While it "
            "is down a rebuild falls back to mirrors; the MakeMKV you already have keeps "
            "working."},
    {"key": "forum", "name": "forum.makemkv.com", "url": "https://forum.makemkv.com/",
     "why": "Where the free beta key is published, and where its author posts when the "
            "site is having trouble. A different host from the main site, so it is "
            "often up when the site is not."},
]

_SITE_CACHE = {"at": 0, "results": None, "checking": False}
_SITE_LOCK = threading.Lock()
SITE_CACHE_SECONDS = 300
PROBE_TIMEOUT = 5


def _probe(url, timeout=PROBE_TIMEOUT):
    """Is this host answering? Any HTTP reply counts, including an error page.

    A 500 or a 403 means the server is there and talking, which is what a user needs to
    know before being sent to it. Only a connection that cannot be made at all, or one
    that hangs, is "down". Deliberately generous: the question is "is it worth clicking
    that link", not "is the service healthy".
    """
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "Riparr")
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"up": True, "status": r.status,
                    "ms": int((time.time() - started) * 1000)}
    except urllib.error.HTTPError as e:
        # It answered. It answered badly, and that is still an answer.
        return {"up": True, "status": e.code, "ms": int((time.time() - started) * 1000),
                "note": "answering, but with an error (%s)" % e.code}
    except Exception as e:
        return {"up": False, "status": None,
                "ms": int((time.time() - started) * 1000),
                "note": str(e)[:120]}


def _probe_all():
    """Every site at once. Serially this was two five-second waits, one after the other."""
    out = [dict(site) for site in SITES]
    threads = []
    for r in out:
        t = threading.Thread(target=lambda d=r: d.update(_probe(d["url"])),
                             name="riparr-probe", daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=PROBE_TIMEOUT + 3)
    return out


def _refresh_sites():
    try:
        results = _probe_all()
    except Exception:
        results = _SITE_CACHE["results"]
    with _SITE_LOCK:
        if results is not None:
            _SITE_CACHE["results"] = results
            _SITE_CACHE["at"] = time.time()
        _SITE_CACHE["checking"] = False


def site_status(force=False, wait=False):
    """Both MakeMKV hosts. Returns immediately unless explicitly told to wait.

    This used to probe inline, and `/api/makemkv` is what the General settings page
    fetches before it draws a single pixel. So opening General meant waiting on two of
    somebody else's web servers -- one of which has been down for weeks and therefore
    burns the whole timeout every time. The page took as long as the slowest host to
    appear, the sidebar link looked broken for ten seconds, and people clicked it
    again.

    The rule now: a settings page never waits on a network probe. The last known answer
    comes back instantly, a refresh runs on a thread behind it, and the interface says
    "checking" until it lands. Only the explicit "Check again" button passes wait=True,
    because there the waiting *is* the interaction.

    Returns (results, checking). `results` is a list, empty when nothing has ever been
    probed -- never None, so no caller has to defend against it.
    """
    now = time.time()
    with _SITE_LOCK:
        fresh = (_SITE_CACHE["results"] is not None
                 and now - _SITE_CACHE["at"] < SITE_CACHE_SECONDS)
        if fresh and not force:
            return _SITE_CACHE["results"], False
        already = _SITE_CACHE["checking"]
        _SITE_CACHE["checking"] = True

    if wait:
        _refresh_sites()
        with _SITE_LOCK:
            return _SITE_CACHE["results"] or [], False

    if not already:
        threading.Thread(target=_refresh_sites, name="riparr-sites",
                         daemon=True).start()
    with _SITE_LOCK:
        return _SITE_CACHE["results"] or [], True


# ─────────────────────── what a beta key's expiry means ───────────────────────
#
# Beta keys are not a 30-day timer that starts when you paste one in. They are
# published on the forum and expire on a **month boundary** -- a key issued mid-month
# dies at the end of that month, so the time you get from one is anywhere between a day
# and about five weeks. Counting down "23 days left" from the day it was entered would
# be a confident, wrong number.
#
# So Riparr says the true thing instead: which month this key is good for, and that
# a new one is a copy and paste away.

def key_advice(entered_at=None):
    """A month-boundary-aware note about the beta key. Never a countdown."""
    now = time.localtime()
    # The last day of the current month, without importing calendar arithmetic.
    if now.tm_mon == 12:
        nxt = time.struct_time((now.tm_year + 1, 1, 1, 0, 0, 0, 0, 1, -1))
    else:
        nxt = time.struct_time((now.tm_year, now.tm_mon + 1, 1, 0, 0, 0, 0, 1, -1))
    end = time.mktime(nxt) - 86400
    days = max(0, int((end - time.time()) // 86400))
    return {
        "month": time.strftime("%B", now),
        "ends": time.strftime("%d %b", time.localtime(end)),
        "days_to_month_end": days,
        "soon": days <= 5,
        "note": ("Free beta keys expire at the end of the month rather than a fixed "
                 "number of days after you enter one, so this one stops working on or "
                 "around %s. %s"
                 % (time.strftime("%d %B", time.localtime(end)),
                    "Riparr puts in the next one itself."
                    if _db_get("auto_renew_beta_key", True)
                    else "Getting the next one is a copy and paste.")),
    }


# Shown before consent. Paraphrased from makemkv-oss-2.0.0/License.txt; the full text is
# always one click away, and the wizard links to it rather than relying on this summary.
EULA_POINTS = [
    "MakeMKV is made by GuinpinSoft inc. This agreement is between you and them.",
    "You may only use it to copy discs you own or are otherwise permitted to copy.",
    "You may not sell, rent, lease or sublicense it.",
    "You may not reverse engineer, decompile or modify it.",
    "The free beta key expires on a month boundary. A permanent key can be purchased.",
]

def _vtuple(v):
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("v").split("."))
    except (TypeError, ValueError):
        return None


def upgrade_available(st=None):
    """The version Riparr would install, when it is newer than the one installed."""
    st = st or P.makemkv_status()
    if not st.get("installed"):
        return None
    have, want = _vtuple(st.get("version")), _vtuple(MANIFEST.get("version"))
    if have and want and want > have:
        return MANIFEST["version"]
    return None


def info():
    st = P.makemkv_status()
    sites, checking = site_status()
    return {
        "status": st,
        "manifest": {
            "version": MANIFEST.get("version"),
            "verified_against_official": MANIFEST.get("verified_against_official", False),
            "verified_note": MANIFEST.get("verified_note", ""),
            # Named, not linked. The list is for reassurance -- "this does not depend on
            # one website" -- and a row of raw URLs reads as a debugging dump.
            "sources": [u.get("where") for u in sources(MANIFEST["packages"][0])],
        },
        "eula_url": EULA_URL,
        "eula_points": EULA_POINTS,
        "homepage": HOMEPAGE,
        "key_topic": FORUM_KEY_TOPIC,
        "install_hint": install_hint(),
        "install": _install(),
        "upgrade": upgrade_available(st),
        "auto_renew": bool(_db_get("auto_renew_beta_key", True)),
        "buy_url": BUY_URL,
        "shop_open": _db_get("makemkv_shop_open", None),
        "sites": sites,
        "sites_checking": checking,
        "key_advice": key_advice(),
    }


def _db_get(key, default=None):
    try:
        from . import db
        return db.get(key, default)
    except Exception:
        return default


# ── installing ──
# Upstream builds MakeMKV from the web page, through a root path unit the unprivileged
# service can poke. Here the container's entrypoint compiles it on start, as root, before
# Riparr runs (deploy/build-tools.sh). A web service that can compile and install
# software as root is not something a server should carry, so this only says where to go.
def _install():
    from . import install
    return install()


def install_hint():
    if _install() == "bare":
        return ("MakeMKV is compiled when Riparr starts, once you've accepted its licence: "
                "set MAKEMKV_ACCEPT_EULA=yes in /etc/riparr/riparr.env and run "
                "sudo systemctl restart riparr. That start takes a few minutes; "
                "journalctl -u riparr shows progress, and why if it fails.")
    return ("MakeMKV is compiled when the container starts, once you've accepted its licence: "
            "set MAKEMKV_ACCEPT_EULA=yes in the container's environment (docker-compose.yml) "
            "and restart it. The first start takes a few minutes; the container log shows "
            "progress, and why if it fails.")


# ── the current beta key ──
# MakeMKV is free while it is in beta, and GuinpinSoft publishes a registration key on
# their forum that they roll over roughly monthly. Everyone running a beta is expected
# to fetch it themselves, notice when it lapses, and paste in the new one — which is a
# chore this box is in a much better position to do than its owner.
#
# This is a forum page, not an API, so it will break one day. Every failure path here
# ends in "here is the link, paste it yourself" rather than an error, because that is
# exactly as good as the situation before this existed.
_key_cache = {"at": 0, "ttl": 0, "value": None}
_EMPTY_KEY = {"key": None, "expires": None, "expires_text": None,
              "source": FORUM_KEY_TOPIC, "sources_agree": None, "shop_open": None,
              "fetched_at": 0, "error": None}
KEY_TTL = 6 * 3600
# A failure is cached too, briefly. Without this, a forum having a bad hour cost a
# fresh timeout on every render of Settings and of the setup wizard.
FAIL_TTL = 15 * 60
FORUM_TIMEOUT = 20
API_TIMEOUT = 10
KEY_RE = re.compile(r"\bT-[A-Za-z0-9@_\-]{40,80}\b")
# "end of" is *captured*, not skipped. It used to sit in a non-capturing group, which
# threw away the only word that distinguishes "valid until September 2026" from "valid
# until the end of September 2026" -- a 29-day difference, and always in the direction of
# warning a month early. The forum has said "end of" every month it has been read.
EXPIRY_RE = re.compile(
    r"valid\s+until\s+(?:the\s+)?(end\s+of\s+)?([A-Z][a-z]+\s+\d{1,2},?\s+\d{4}"
    r"|[A-Z][a-z]+\s+\d{4}|\d{1,2}\s+[A-Z][a-z]+\s+\d{4})", re.I)

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


def _resolve_expiry(text, end_of):
    """Turn the forum's prose into a real date. Returns "YYYY-MM-DD" or None.

    A bare month ("September 2026") is ambiguous by a month. `end_of` decides which edge
    it means, and the answer is the *last* day of that month when the forum said so --
    which is also what the second source's timestamp resolves to, so the two agree rather
    than merely coexisting.
    """
    if not text:
        return None
    t = " ".join(text.split()).rstrip(".,")

    m = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", t)      # September 30, 2026
    if not m:
        m2 = re.match(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", t)   # 30 September 2026
        if m2:
            m = None
            mon, day, year = m2.group(2), int(m2.group(1)), int(m2.group(3))
        else:
            m3 = re.match(r"^([A-Za-z]+)\s+(\d{4})$", t)             # September 2026
            if not m3:
                return None
            mon, year = m3.group(1), int(m3.group(2))
            day = None
    else:
        mon, day, year = m.group(1), int(m.group(2)), int(m.group(3))

    month = _MONTHS.get(mon.lower())
    if not month:
        return None
    if day is None:
        day = _last_day(year, month) if end_of else 1
    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


def _last_day(year, month):
    return calendar.monthrange(year, month)[1]


def beta_key(force=False, allow_fetch=True):
    """The current beta key and the date it lapses, from whichever source answers.

    Two sources, tried in order, exactly as the binary download below uses mirrors and
    for the same reason: the forum is authoritative but frequently unusable, and an
    appliance must not depend on somebody else's uptime to tell you your key is dead.

    The forum is asked first because it is GuinpinSoft's own word. The API is asked when
    the forum fails *or* when the forum gave a key but no date -- it carries the expiry
    as a timestamp, so a month named in prose and a month named in seconds can be
    checked against each other rather than merely believed.

    `allow_fetch=False` returns whatever is cached and never touches the network, which
    is what any caller on a hot path wants.
    """
    now = time.time()
    if _key_cache["value"] and now - _key_cache["at"] < _key_cache["ttl"]:
        if not force:
            return dict(_key_cache["value"], cached=True)
    if not allow_fetch:
        return dict(_key_cache["value"] or _EMPTY_KEY, cached=True)

    result = {"key": None, "expires": None, "expires_text": None,
              "source": FORUM_KEY_TOPIC, "sources_agree": None,
              "fetched_at": int(now), "error": None, "cached": False}

    # makemkv.com's own purchase page first. While sales are closed it publishes the
    # current beta key itself, on GuinpinSoft's main site, in a page that answers in a
    # second -- so it is both the most official source and the fastest. It carries no
    # expiry, so the backup service (also fast) is asked alongside it for the date and
    # as a second opinion. The forum, which can take minutes, is asked only when those
    # two do not settle it between them.
    buy = _key_from_buy_page()
    api = _key_from_api()
    forum = None
    if not (buy.get("key") and api.get("key") == buy["key"] and api.get("expires")):
        forum = _key_from_forum()
    result["shop_open"] = buy.get("shop_open")
    _record_shop(buy.get("shop_open"))

    answered = [x for x in (buy, forum, api) if x and x.get("key")]
    if not answered:
        # Nothing answered. Cache the *failure* briefly so a forum having a bad hour
        # costs one wait per quarter-hour rather than one per visit to Settings.
        result["error"] = (buy.get("error") or (forum or {}).get("error")
                           or api.get("error")
                           or "Couldn't reach any source for the current beta key.")
        _remember(result, FAIL_TTL)
        return result

    # GuinpinSoft's own word wins, the site over the forum; the backup service only
    # when neither of theirs answered.
    chosen = answered[0]
    result["key"] = chosen["key"]
    result["source"] = chosen.get("source", FORUM_KEY_TOPIC)

    # The date from whichever source states it *for this key*.
    for x in (forum, api):
        if x and x.get("key") == result["key"] and x.get("expires"):
            result["expires"] = x["expires"]
            result["expires_text"] = x.get("expires_text")
            break

    # Corroboration, when more than one answered. Disagreement is reported, not
    # silently resolved -- and it stops the automatic renewal -- because sources
    # differing about a registration key is a fact the user should see.
    if len(answered) > 1:
        result["sources_agree"] = all(x["key"] == result["key"] for x in answered)
        if not result["sources_agree"]:
            result["error"] = ("MakeMKV's sources disagree about the current key. "
                               "GuinpinSoft's own is shown; check makemkv.com before "
                               "relying on it.")

    _remember(result, KEY_TTL)
    _record_expiry(result)
    _maybe_renew(result)
    return result


def _key_from_buy_page():
    """makemkv.com/buy/. Publishes the beta key while sales are closed.

    Also the only place that says whether a licence can be bought at all, which is what
    decides whether Riparr shows a Buy button. `shop_open` is None when the page could
    not be read: unknown is not the same as closed.
    """
    out = {"source": BUY_URL, "shop_open": None}
    try:
        req = urllib.request.Request(
            BUY_URL, headers={"User-Agent": "Mozilla/5.0 (compatible; riparr)"})
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as r:
            html = r.read(200000).decode("utf-8", "replace")
    except Exception as e:
        out["error"] = "Couldn't reach makemkv.com (%s)." % e
        return out
    text = _strip_tags(html)
    m = KEY_RE.search(text)
    closed = bool(m) or bool(SHOP_CLOSED_RE.search(text))
    out["shop_open"] = not closed
    if m:
        out["key"] = m.group(0)
    return out


# The wording on makemkv.com/buy/ while sales are closed (2026-10): "one cannot purchase
# MakeMKV for a moment. You have to use it for free". A key on the page means the same.
SHOP_CLOSED_RE = re.compile(r"cannot\s+purchase|use\s+it\s+for\s+free", re.I)


def _record_shop(shop_open):
    if shop_open is None:
        return                            # unreachable says nothing about the shop
    try:
        from . import db
        db.set("makemkv_shop_open", bool(shop_open))
    except Exception:
        pass


def _key_from_forum():
    """GuinpinSoft's own announcement post. Authoritative, and often very slow."""
    out = {"source": FORUM_KEY_TOPIC}
    try:
        req = urllib.request.Request(
            FORUM_KEY_TOPIC,
            headers={"User-Agent": "Mozilla/5.0 (compatible; riparr)"})
        with urllib.request.urlopen(req, timeout=FORUM_TIMEOUT) as r:
            html = r.read(400000).decode("utf-8", "replace")
    except Exception as e:
        out["error"] = ("Couldn't reach the MakeMKV forum (%s)." % e)
        return out

    text = _strip_tags(html)
    # The first match is the announcement post, which is the one kept up to date.
    m = KEY_RE.search(text)
    if not m:
        out["error"] = "The forum page didn't contain a key in the expected format."
        return out
    out["key"] = m.group(0)
    e = EXPIRY_RE.search(text)
    if e:
        out["expires_text"] = (e.group(0) or "").strip()
        out["expires"] = _resolve_expiry(e.group(2), bool(e.group(1)))
    return out


def _key_from_api():
    """The backup service. Answers with the expiry as a Unix timestamp."""
    out = {"source": AYRA_KEY_API}
    try:
        req = urllib.request.Request(
            AYRA_KEY_API, headers={"User-Agent": USER_AGENT % _version()})
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as r:
            data = json.loads(r.read(20000).decode("utf-8", "replace"))
    except Exception as e:
        out["error"] = "Couldn't reach the backup key service (%s)." % e
        return out

    key = (data.get("key") or "").strip()
    if not KEY_RE.fullmatch(key or ""):
        out["error"] = "The backup key service returned nothing key-shaped."
        return out
    out["key"] = key
    ts = data.get("keydate")
    if isinstance(ts, (int, float)) and ts > 0:
        try:
            out["expires"] = datetime.date.fromtimestamp(ts).isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    return out


def _version():
    from . import __version__
    return __version__


def _remember(result, ttl):
    _key_cache["at"] = time.time()
    _key_cache["ttl"] = ttl
    _key_cache["value"] = result


def record_expiry_for(key):
    """Re-derive the stored expiry after the user enters a key, without a network wait.

    Uses only what is already cached. If nothing has been fetched yet the expiry stays
    unknown and the next lookup fills it in -- which is the right trade against making
    somebody wait on a forum that may take four minutes to answer.
    """
    cached = beta_key(allow_fetch=False)
    _record_expiry(cached if cached.get("key") else {"key": None})


def _record_expiry(result):
    """Write the expiry of *the key this box actually has* where status can read it.

    `platform.makemkv_status()` runs on every status poll and must never make a network
    call, and it cannot import this module anyway -- this one imports it. The database is
    the channel between them, and it is also durable, so the countdown keeps running
    while every source is unreachable.

    The distinction that matters: the published key's expiry is only *our* expiry when it
    is the key we hold. Holding a different one means holding an older one, and that is
    worth saying now rather than on the date the current key happens to lapse.
    """
    try:
        _record_expiry_inner(result)
    except Exception:
        # Recording the date is a convenience for the status poll. It must never be the
        # reason a successfully fetched key is thrown away.
        pass


def _record_expiry_inner(result):
    from . import db
    mine = (db.get("makemkv_key") or "").strip()
    if not mine:
        db.set("makemkv_key_expires", "")
        db.set("makemkv_key_stale", False)
        return
    if not mine.startswith("T-"):
        # A purchased key. It does not expire, and the beta schedule does not apply.
        db.set("makemkv_key_expires", "")
        db.set("makemkv_key_stale", False)
        return
    published = result.get("key")
    if not published:
        return
    if mine == published:
        db.set("makemkv_key_expires", result.get("expires") or "")
        db.set("makemkv_key_stale", False)
    else:
        # Holding a key that is not the published one means holding an older one, and
        # the published key's expiry is emphatically not its expiry. Saying "34 days
        # left" about somebody else's key is worse than admitting the date is unknown.
        db.set("makemkv_key_stale", True)
        db.set("makemkv_key_expires", "")


# ── renewing the beta key ──
# The beta key lapses at the end of every month and every rip fails the next morning.
# Noticing that and pasting the new key in was left to the owner, and the box sat on a
# dead key until somebody opened Settings -- so the box does it itself now.
#
# Narrowly. Only a beta key is ever replaced, and only by the key GuinpinSoft has
# published: a purchased key is never touched, and two sources disagreeing about the
# current key stops it. A box with no key at all is given the current one too -- a
# fresh install shouldn't open on "No key entered" when the key is published and the
# licence has been accepted. What it does is said once, on
# the next visit to the web page, together with the case for buying MakeMKV -- the
# point is to keep a box working while the shop is down, not to stand in for buying.

def _maybe_renew(result):
    try:
        _maybe_renew_inner(result)
    except Exception:
        # A renewal is a convenience. It must never break the key lookup itself.
        pass


def _maybe_renew_inner(result):
    from . import db
    if not db.get("auto_renew_beta_key", True):
        return
    mine = (db.get("makemkv_key") or "").strip()
    new = (result.get("key") or "").strip()
    if (mine and not mine.startswith("T-")) or not new.startswith("T-") or new == mine:
        return
    if result.get("sources_agree") is False:
        return
    if result.get("source") not in (BUY_URL, FORUM_KEY_TOPIC):
        # The backup service alone is a third party's say-so. Good enough to show, not
        # to act on without GuinpinSoft's own page or forum behind it.
        return
    expires = result.get("expires") or ""
    if expires and expires < datetime.date.today().isoformat():
        return                            # never swap one dead key for another

    ok, _ = apply_key(new)
    if not ok:
        # Leave the database on the key MakeMKV actually has; the stale warning stays
        # up and says what to do.
        return
    db.set("makemkv_key", new)
    db.set("makemkv_key_expires", expires)
    db.set("makemkv_key_stale", False)
    db.set("makemkv_key_renewal", {"at": int(time.time()), "expires": expires,
                                   "seen": False, "first": not mine})
    try:
        from .system import component
        component("MakeMKV").info(
            "Renewed the beta key%s", " (good until %s)" % expires if expires else "")
    except Exception:
        pass


def renewal_notice():
    """The renewal the web page has not mentioned yet, or None."""
    from . import db
    r = db.get("makemkv_key_renewal") or None
    if not isinstance(r, dict) or r.get("seen"):
        return None
    return {"at": r.get("at"), "expires": r.get("expires") or None,
            "first": bool(r.get("first")),
            "buy_url": BUY_URL, "shop_open": db.get("makemkv_shop_open", None)}


def dismiss_renewal_notice():
    from . import db
    r = db.get("makemkv_key_renewal") or None
    if isinstance(r, dict):
        r["seen"] = True
        db.set("makemkv_key_renewal", r)


SETTINGS_CONF = "~/.MakeMKV/settings.conf"


def settings_conf_path():
    """Where makemkvcon reads its registration key.

    makemkvcon keeps its state in `$HOME/.MakeMKV`, and the unit sets HOME to the state
    directory (`/var/lib/riparr`) rather than leaving it at a home that ProtectHome=yes
    hides. `ReadWritePaths=` names that directory, so the unprivileged service can write
    here; the installer creates the file and owns it to the same user.
    """
    return os.path.expanduser(SETTINGS_CONF)


def _set_conf(name, value):
    """Set one `name = "value"` line in MakeMKV's settings.conf (None removes it).

    Replaces any existing line for the name rather than appending: MakeMKV reads the file
    top to bottom and the last assignment wins, so a second line would work by luck and
    the file would grow by one line per save. Written via a temporary file and renamed,
    so a power cut mid-write leaves the old settings.conf rather than half of a new one.
    """
    path = settings_conf_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = []
    if os.path.exists(path):
        with open(path) as f:
            lines = f.read().splitlines()
    out = [l for l in lines if not re.match(r"\s*%s\s*=" % re.escape(name), l)]
    if value:
        out.append('%s = "%s"' % (name, str(value).replace('\\', '\\\\').replace('"', '\\"')))
    body = "\n".join(out).rstrip("\n") + "\n"
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".settings.conf.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(body)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def conf_value(name):
    """The value of one setting in MakeMKV's settings.conf, or None."""
    try:
        with open(settings_conf_path()) as f:
            m = re.search(r'^\s*%s\s*=\s*"(.*)"\s*$' % re.escape(name), f.read(), re.M)
    except OSError:
        return None
    return m.group(1) if m else None


def apply_key(key):
    """Put the key where MakeMKV will actually read it. Returns (ok, message).

    Storing a key in Riparr's database registered nothing: `app_Key` was written nowhere,
    so a user could paste a valid key, watch the warning clear, and still have every
    encrypted disc fail. The database row is the record of what the user chose; this is
    the part that makes it true.

    Purely local. It needs no network, which is the point -- makemkv.com can be down for
    a month, as it was in August 2026, and registering still works.
    """
    key = (key or "").strip()
    path = settings_conf_path()
    if P.MOCK:
        return True, "Simulated: would write app_Key to %s" % path
    try:
        _set_conf("app_Key", key or None)
    except OSError as e:
        return False, ("Saved, but MakeMKV could not be registered: %s could not be "
                       "written (%s)." % (path, e))
    return True, ("Registered." if key else "Key cleared.")


# ── the SDF hang ──────────────────────────────────────────────────────────────
#
# A Linux-only MakeMKV bug since 1.17.8: the first time it meets a drive it fetches
# that drive's data ("SDF auto ...: <drive id>" in its debug log) and the fetch can
# spin at 100% CPU forever. Nothing after it runs -- not the drive scan, not the disc
# -- so a rip sits on "Reading the disc" until it times out. The known workaround is
# `sdf_Stop = "<drive id>"` in settings.conf, which skips that step for that drive. It
# only costs LibreDrive (4K UHD firmware features); DVDs and Blu-rays rip as usual.
# https://forum.makemkv.com/forum/viewtopic.php?p=204167
#
# So before the first MakeMKV run on a drive, a short probe: if MakeMKV gets as far as
# listing drives, all is well; if it goes silent after starting, read the drive id from
# its debug log, set sdf_Stop, and carry on.

SDF_LINE = re.compile(r"SDF(?:\s+auto)?\s+v\w+:\s+(\S+)")
PROBE_SECONDS = 60
_probed = set()
_probe_lock = threading.Lock()


def ensure_drive_ready(disc_arg):
    """Work around MakeMKV's SDF hang for this drive if needed. Returns a note or None."""
    if P.MOCK or not disc_arg:
        return None
    with _probe_lock:
        if disc_arg in _probed:
            return None
        _probed.add(disc_arg)
        if conf_value("sdf_Stop"):
            return None
        binary = shutil.which("makemkvcon") or "/usr/local/bin/makemkvcon"
        if not os.path.exists(binary):
            return None
        log_path = os.path.join(os.path.expanduser("~"), "MakeMKV_log.txt")
        proc = subprocess.Popen([binary, "-r", "--debug", "info", disc_arg],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        lines = queue.Queue()

        def pump():
            for ln in proc.stdout:
                lines.put(ln)
            lines.put(None)
        threading.Thread(target=pump, daemon=True).start()

        healthy, start = False, time.time()
        while time.time() - start < PROBE_SECONDS:
            try:
                ln = lines.get(timeout=1)
            except queue.Empty:
                continue
            if ln is None or ln.startswith("DRV:"):
                healthy = True          # listed the drives, or finished on its own
                break
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        if healthy:
            return None

        try:
            with open(log_path, errors="replace") as f:
                ids = SDF_LINE.findall(f.read())
        except OSError:
            ids = []
        if not ids:
            log.warning("MakeMKV went quiet after starting, but its log names no drive "
                        "to work around; the scan may hang.")
            return None
        drive_id = ids[-1]
        try:
            _set_conf("sdf_Stop", drive_id)
        except OSError as e:
            log.warning("MakeMKV hangs fetching drive data (known MakeMKV bug); "
                        "couldn't write sdf_Stop: %s", e)
            return None
        note = ("MakeMKV was hanging on a known bug while fetching data for this drive "
                "(%s), so Riparr told it to skip that step. DVDs and Blu-rays rip as "
                "usual; only 4K LibreDrive features are affected." % drive_id)
        log.warning(note)
        return note


def key_is_registered():
    """Whether settings.conf currently carries an app_Key. Cheap; no makemkvcon run."""
    path = settings_conf_path()
    try:
        with open(path) as f:
            return bool(re.search(r"^\s*app_Key\s*=\s*\"..*\"", f.read(), re.M))
    except OSError:
        return False


def _strip_tags(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    return re.sub(r"<[^>]+>", " ", html)


