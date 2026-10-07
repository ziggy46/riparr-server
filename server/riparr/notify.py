"""
Telling the user something happened when they are not looking at the page.

The product's whole pitch is *insert a disc and walk away*, and until now the only
thing that could reach a person who had walked away was a coloured LED on the box --
which requires them to walk past the box. `webhook_url` has been a field on the
Connect settings page since the beginning and nothing in the codebase read it.

Four channels, all on the standard library: no new dependency, because a native wheel
that fails to build on this hardware turns into a box that installed fine and cannot
tell you anything (see the note in requirements.txt).

Every send is fire-and-forget on its own thread. A notification that blocks a rip is
worse than no notification, and a NAS-adjacent box is exactly where a webhook to some
unreachable host will hang for thirty seconds.
"""
import json
import re
import smtplib
import threading
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

from itsdangerous import BadSignature, URLSafeTimedSerializer

from . import db, platform as P, system as SY

log = SY.component("Notifications")

TIMEOUT = 10

# What Riparr can tell you about, and whether it does by default. The defaults are the
# things you would want to know at the shops; the rest are for people who want a log.
EVENTS = [
    ("done",        "A rip finished",            True),
    # Distinct from "done" on purpose: this one is actionable. The disc is out and the
    # next one can go in, while the last is still crossing the network.
    ("ripped",      "A disc is read and ejected — ready for the next", True),
    ("needs_you",   "A disc needs your input",   True),
    ("failed",      "A rip failed",              True),
    ("share_lost",  "Your library went away",    True),
    ("duplicate",   "A disc was already ripped", False),
    ("key_expiring", "The MakeMKV key is about to expire", True),
    # On by default and quiet by nature: the update check fires every six hours but
    # each version is announced once, so this is a handful of messages a year.
    ("update_available", "A new version of Riparr is available", True),
]

DEFAULT_EVENTS = [k for k, _, on in EVENTS if on]

# ntfy's priority/emoji vocabulary, so a phone notification looks like it was designed
# rather than dumped.
_TAGS = {
    "done": ("white_check_mark", 3),
    "ripped": ("eject", 3),
    "needs_you": ("raising_hand", 4),
    "failed": ("rotating_light", 4),
    "share_lost": ("warning", 4),
    "duplicate": ("recycle", 2),
    "key_expiring": ("key", 4),
    # Priority 2: worth seeing, never worth waking somebody at 3am. Nothing is broken.
    "update_available": ("arrow_up", 2),
}


def enabled_events():
    got = db.get("notify_events")
    return got if isinstance(got, list) else DEFAULT_EVENTS


def send(event, title="", body="", force=False, actions=None):
    """Queue a notification on every configured channel. Never raises, never blocks.

    `actions` are buttons, from `answer_action` and `open_action`: ntfy shows them as
    buttons, Discord and email as links, and the webhook gets them as data.
    """
    if not force and event not in enabled_events():
        return
    actions = actions or []
    payload = {"event": event, "title": title, "body": body,
               "hostname": P.hostname()}
    if actions:
        payload["actions"] = [{"label": a["label"], "url": a["url"],
                               "method": "POST" if a["kind"] == "answer" else "GET"}
                              for a in actions]
    threading.Thread(target=_fanout, args=(event, title, body, payload, actions),
                     name="riparr-notify", daemon=True).start()


def _fanout(event, title, body, payload, actions=()):
    for name, fn in (("ntfy", _ntfy), ("Discord", _discord),
                     ("webhook", _webhook), ("email", _email)):
        try:
            fn(event, title, body, payload, actions)
        except Exception as e:
            log.warning("%s notification failed: %s", name, e)


# ─────────────────────────────── answering from a notification ───────────────────────
#
# A disc that stops to ask "which film is this?" used to need somebody to walk to a
# computer. These are the buttons that answer it from the notification instead.
#
# Each button is a link carrying a signed answer -- this job, this choice -- so it needs
# no sign-in, and can't be edited into a different answer. It works once: answering
# moves the job out of "needs input", and the second tap is refused. A password change
# mints a new secret, which retires every link already sent, on purpose.

ANSWER_SALT = "riparr-answer"     # never the cookie's salt: one can't stand in for the other
ANSWER_MAX_AGE = 7 * 24 * 3600    # a disc can sit waiting over a long weekend
LABEL_MAX = 40


def _signer():
    secret = db.get("session_secret") or ""
    return URLSafeTimedSerializer(secret, salt=ANSWER_SALT)


def public_url():
    """How a phone reaches Riparr: the address set on Settings → Connect, or else the
    one it was last signed in at. Empty when neither is known, and then there are no
    buttons -- a button that points nowhere is worse than none."""
    url = (db.get("public_url") or db.get("seen_url") or "").strip().rstrip("/")
    try:
        return _check_url(url) if url else ""
    except BadWebhookURL:
        return ""


def _label(text):
    text = " ".join((text or "").split())
    return text if len(text) <= LABEL_MAX else text[:LABEL_MAX - 1].rstrip() + "…"


def answer_action(job_id, label, answer):
    """A button that answers job `job_id` with `answer` (the fields rip.answer takes)."""
    base = public_url()
    if not base:
        return None
    token = _signer().dumps({"j": int(job_id), "a": answer, "l": _label(label)})
    url = "%s/api/answer/%s" % (base, token)
    return {"kind": "answer", "label": _label(label), "url": url}


def open_action(label="Open Riparr", where="#/queue"):
    base = public_url()
    return {"kind": "open", "label": label, "url": base + "/" + where} if base else None


def actions(*items):
    """The buttons that could be made, at most three (ntfy's limit)."""
    return [a for a in items if a][:3]


# The only answers a button can give: a film, a show, or "as proposed" (no fields).
ANSWER_FIELDS = {"tmdb_id", "series_id"}


def read_answer(token):
    """{"job", "answer", "label"} from a button's token, or {"error": why}."""
    try:
        got = _signer().loads(token, max_age=ANSWER_MAX_AGE)
    except BadSignature:
        return {"error": "This button has expired, or Riparr's password was changed "
                         "since it was sent. Answer on the Queue page instead."}
    if (not isinstance(got, dict) or not isinstance(got.get("a"), dict)
            or set(got["a"]) - ANSWER_FIELDS):
        return {"error": "That isn't a Riparr answer."}
    return {"job": int(got["j"]), "answer": got["a"], "label": got.get("l") or "Rip it"}


class BadWebhookURL(ValueError):
    """A notification target that is not a plain http(s) URL."""


def _check_url(url):
    """Reject anything that is not an http(s) URL with a host.

    These URLs come from settings, so a signed-in user chooses them -- and pointing the
    box at a service on the same LAN (a self-hosted ntfy, a webhook on the NAS) is the
    normal, intended case, so private addresses are deliberately allowed. What is not
    allowed is a non-network scheme: `file://`, `gopher://` and friends turn a webhook
    field into a way to make the box read local files or speak odd protocols, and no
    legitimate notification target needs them.
    """
    parsed = urllib.parse.urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise BadWebhookURL("Notification URLs must start with http:// or https://")
    return url


def _post(url, data, headers=None, content_type="application/json"):
    _check_url(url)
    body = data if isinstance(data, bytes) else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", content_type)
    req.add_header("User-Agent", "Riparr")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status


# ─────────────────────────────── channels ───────────────────────────────

def _ntfy(event, title, body, payload, actions=()):
    topic = (db.get("ntfy_topic") or "").strip()
    if not topic:
        return
    server = (db.get("ntfy_server") or "https://ntfy.sh").strip().rstrip("/")
    tag, priority = _TAGS.get(event, ("cd", 3))
    headers = {}
    token = (db.get("ntfy_token") or "").strip()
    if token:
        headers["Authorization"] = "Bearer %s" % token
    if actions:
        # Buttons go as JSON, not in the Actions header, where a comma in a film's
        # title would split one button into two.
        _post(server + "/", ntfy_message(topic, event, title, body, actions), headers)
        return
    headers.update({"Title": _ascii(title or "Riparr"),
                    "Tags": tag, "Priority": str(priority)})
    _post("%s/%s" % (server, urllib.parse.quote(topic)),
          (body or "").encode("utf-8"), headers, content_type="text/plain")


def ntfy_message(topic, event, title, body, actions):
    """ntfy's JSON publish. An answer is an `http` action, which the ntfy app sends
    straight from the phone and then clears the notification; Open is a `view`."""
    tag, priority = _TAGS.get(event, ("cd", 3))
    out = []
    for a in actions:
        if a["kind"] == "answer":
            out.append({"action": "http", "label": a["label"], "url": a["url"],
                        "method": "POST", "clear": True})
        else:
            out.append({"action": "view", "label": a["label"], "url": a["url"]})
    msg = {"topic": topic, "title": title or "Riparr", "message": body or "",
           "tags": [tag], "priority": priority, "actions": out}
    opener = next((a for a in actions if a["kind"] == "open"), None)
    if opener:
        msg["click"] = opener["url"]
    return msg



_DISCORD_RE = re.compile(
    r"^https://(?:\w+\.)?discord(?:app)?\.com/api(?:/v\d+)?/webhooks/(\d+)/([\w-]+)")


def discord_mention_prefix(event):
    """`<@id>` when this event is one the user asked to be pinged for.

    A message in a channel is something you find later. A mention is something your
    phone tells you about, and the whole product is "walk away" -- so the events that
    mean *come back* are the ones that get the ping, and the rest stay quiet. Roles
    (`&`-prefixed IDs) work too, for a household that shares the box.
    """
    who = (db.get("discord_mention") or "").strip()
    if not who:
        return "", None
    want = db.get("discord_mention_events")
    if isinstance(want, list) and event not in want and event != "test":
        return "", None
    if who.startswith("&"):
        return "<@%s> " % who, {"parse": [], "roles": [who[1:]]}
    return "<@%s> " % who, {"parse": [], "users": [who]}


def _discord(event, title, body, payload, actions=()):
    url = (db.get("discord_webhook") or "").strip()
    if not url:
        return
    colour = {"done": 0x27C24C, "failed": 0xF05050, "needs_you": 0xFF9F1A,
              "share_lost": 0xFF9F1A, "key_expiring": 0xFF9F1A,
              "update_available": 0x4C9AFF}.get(event, 0x5B5B8A)
    mention, allowed = discord_mention_prefix(event)
    msg = {"username": "Riparr",
           "embeds": [{"title": title or "Riparr",
                       "description": (body or "") + discord_links(actions),
                       "color": colour,
                       "footer": {"text": "Riparr on %s" % P.hostname()}}]}
    if mention:
        msg["content"] = mention.strip()
        # Without this Discord will happily render `<@everyone>`-shaped text but will
        # not ping anyone the webhook was not explicitly told to ping.
        msg["allowed_mentions"] = allowed
    _post(url, msg)


def discord_links(actions):
    """Webhooks can't send Discord buttons -- those need a bot -- so the choices are
    links under the message. Opening an answer's link shows a page with the button on
    it rather than answering: link previews and mail scanners open links too."""
    if not actions:
        return ""
    return "\n\n" + " · ".join("[%s](%s)" % (a["label"].replace("]", ")"), a["url"])
                               for a in actions)


def discord_check(url=None):
    """Ask Discord what a webhook URL actually points at, before trusting it.

    A webhook URL is a long opaque string a user pasted, and the failure mode of
    getting it slightly wrong is silence -- notifications that go nowhere, discovered
    weeks later when the one that mattered did not arrive. Discord answers an
    unauthenticated GET on the webhook itself with its name and channel, so the
    settings page can say *what it is connected to* rather than "saved".
    """
    url = (url if url is not None else db.get("discord_webhook") or "").strip()
    if not url:
        return {"ok": False, "error": "Paste the webhook URL first."}
    m = _DISCORD_RE.match(url)
    if not m:
        return {"ok": False,
                "error": "That doesn't look like a Discord webhook URL. It should "
                         "start https://discord.com/api/webhooks/ and Discord gives "
                         "you the whole thing on the Copy Webhook URL button."}
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "Riparr")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            info = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            return {"ok": False,
                    "error": "Discord doesn't recognise that webhook. It was probably "
                             "deleted, or the URL got truncated when it was copied."}
        return {"ok": False, "error": "Discord said %s %s" % (e.code, e.reason)}
    except urllib.error.URLError as e:
        return {"ok": False, "error": "Couldn't reach Discord: %s" % e.reason}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True,
            "name": info.get("name") or "Riparr",
            "channel_id": info.get("channel_id"),
            "guild_id": info.get("guild_id")}


def _webhook(event, title, body, payload, actions=()):
    """The field that has been on the settings page all along, finally connected."""
    url = (db.get("webhook_url") or "").strip()
    if not url:
        return
    _post(url, payload)


def _email(event, title, body, payload, actions=()):
    host = (db.get("smtp_host") or "").strip()
    to = (db.get("smtp_to") or "").strip()
    if not host or not to:
        return
    msg = EmailMessage()
    msg["Subject"] = "Riparr: %s" % (title or event)
    msg["From"] = (db.get("smtp_from") or "riparr@localhost").strip()
    msg["To"] = to
    links = "".join("\n%s: %s" % (a["label"], a["url"]) for a in actions)
    msg.set_content("%s\n\n%s\n%s\n— Riparr" % (title or "", body or "", links))

    port = int(db.get("smtp_port") or 587)
    user = (db.get("smtp_username") or "").strip()
    password = db.get("smtp_password") or ""
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT)
    else:
        server = smtplib.SMTP(host, port, timeout=TIMEOUT)
    try:
        if port != 465 and db.get("smtp_tls", True):
            server.starttls()
        if user:
            server.login(user, password)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass


def _ascii(s):
    """ntfy puts the title in an HTTP header, and headers are latin-1 at best."""
    return (s or "").encode("ascii", "replace").decode("ascii")


# ─────────────────────────────── the test button ───────────────────────────────

def configured():
    return {
        "ntfy": bool((db.get("ntfy_topic") or "").strip()),
        "discord": bool((db.get("discord_webhook") or "").strip()),
        "webhook": bool((db.get("webhook_url") or "").strip()),
        "email": bool((db.get("smtp_host") or "").strip()
                      and (db.get("smtp_to") or "").strip()),
    }


def test(channel):
    """Send one notification down one channel and report what actually happened.

    Synchronous and error-reporting, unlike `send` -- the entire value of a test button
    is the error message, so this is the one path that must not swallow it.
    """
    fns = {"ntfy": _ntfy, "discord": _discord, "webhook": _webhook, "email": _email}
    fn = fns.get(channel)
    if not fn:
        return {"ok": False, "error": "Unknown channel."}
    if not configured().get(channel):
        return {"ok": False, "error": "That channel isn't configured yet."}
    title = "Riparr test"
    body = "If you're reading this, notifications work."
    payload = {"event": "test", "title": title, "body": body}
    try:
        fn("done", title, body, payload)
        return {"ok": True, "message": "Sent. Check your %s." % channel}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": "%s said %s %s" % (channel, e.code, e.reason)}
    except urllib.error.URLError as e:
        return {"ok": False, "error": "Couldn't reach it: %s" % e.reason}
    except Exception as e:
        return {"ok": False, "error": str(e)}
