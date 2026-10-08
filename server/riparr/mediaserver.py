"""
Telling Plex, Jellyfin or Emby that a rip has landed.

Without this a finished film sits in the library folder until the media server's next
scheduled scan, which can be hours away. With it, the film is on the server's home
screen a few seconds after Riparr says "done".

The media server sees the library through its own paths (`/data/movies`, `M:\\Films`),
not Riparr's share path, so Riparr can't just tell it "this file". What it can do is
find the server's library whose folder has the same name as the one Riparr wrote into
(Riparr's "Movies" and Plex's "/data/Movies") and ask for a scan of just the new
folder inside it. When no library's folder matches, it scans the libraries of that
kind instead: slower on a big library, but the film still appears.

Never raises to a rip. A media server that's down or misconfigured is logged and the
rip is done regardless.
"""
import json
import posixpath
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import db, system as SY

log = SY.component("Media server")
TIMEOUT = 10

KINDS = {"plex": "Plex", "jellyfin": "Jellyfin", "emby": "Emby"}
# Riparr's kind -> the media server's word for a library of it.
PLEX_TYPE = {"movie": "movie", "tv": "show", "music": "artist"}
JELLYFIN_TYPE = {"movie": "movies", "tv": "tvshows", "music": "music"}


class MediaServerError(Exception):
    pass


def configured(s=None):
    s = s or db.all_settings()
    return bool(s.get("media_server") in KINDS and (s.get("media_server_url") or "").strip()
                and s.get("media_server_token"))


def _request(method, url, token, server, body=None):
    headers = {"Accept": "application/json"}
    if server == "plex":
        headers["X-Plex-Token"] = token
    else:
        headers["X-Emby-Token"] = token
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise MediaServerError("%s turned the token down (HTTP %d). Check it's "
                                   "the right one." % (KINDS[server], e.code))
        raise MediaServerError("%s answered HTTP %d." % (KINDS[server], e.code))
    except Exception as e:
        raise MediaServerError("Couldn't reach %s at %s: %s"
                               % (KINDS[server], url.split("?")[0], getattr(e, "reason", e)))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _base(s):
    url = (s.get("media_server_url") or "").strip().rstrip("/")
    if url and "://" not in url:
        url = "http://" + url
    return url


def libraries(s=None):
    """[{"key", "title", "type", "paths"}] for the configured server. Raises."""
    s = s or db.all_settings()
    server, base, token = s.get("media_server"), _base(s), s.get("media_server_token")
    if server not in KINDS or not base or not token:
        raise MediaServerError("Choose a media server and fill in its address and token.")
    if server == "plex":
        data = _request("GET", base + "/library/sections", token, server) or {}
        dirs = (data.get("MediaContainer") or {}).get("Directory") or []
        return [{"key": str(d.get("key")), "title": d.get("title") or "",
                 "type": d.get("type") or "",
                 "paths": [l.get("path") for l in d.get("Location") or [] if l.get("path")]}
                for d in dirs]
    data = _request("GET", base + "/Library/VirtualFolders", token, server) or []
    return [{"key": d.get("ItemId") or d.get("Name") or "", "title": d.get("Name") or "",
             "type": d.get("CollectionType") or "",
             "paths": [p for p in d.get("Locations") or [] if p]} for d in data]


def test(s=None):
    """{"ok", "message"} for the Test button."""
    s = s or db.all_settings()
    try:
        libs = libraries(s)
    except MediaServerError as e:
        return {"ok": False, "error": str(e)}
    name = KINDS[s.get("media_server")]
    if not libs:
        return {"ok": True, "message": "Connected to %s, but it has no libraries yet." % name}
    return {"ok": True, "message": "Connected to %s: %s." % (
        name, ", ".join(l["title"] for l in libs))}


def _join(root, rel):
    """A path inside a media server's library folder, in that server's own style."""
    sep = "\\" if "\\" in root and "/" not in root else "/"
    return root.rstrip("/\\") + sep + rel.replace("/", sep)


def _targets(libs, kind, folder, rel_dir, server):
    """[(library, path-or-None)]: which libraries to scan, and the folder inside each
    when it can be worked out. `folder` is Riparr's folder for this kind ("Movies");
    `rel_dir` is where the rip went inside it ("Arrival (2016)")."""
    want = (PLEX_TYPE if server == "plex" else JELLYFIN_TYPE).get(kind)
    leaf = posixpath.basename(folder.rstrip("/")).lower() if folder else ""
    exact = []
    if leaf:
        for lib in libs:
            for p in lib["paths"]:
                if p.rstrip("/\\").replace("\\", "/").split("/")[-1].lower() == leaf:
                    exact.append((lib, _join(p, rel_dir) if rel_dir else p))
    if exact:
        return exact
    # No folder by that name: every library of this kind, whole. Jellyfin's "mixed"
    # libraries (no type) count, since they can hold anything.
    return [(lib, None) for lib in libs
            if lib["type"] == want or (server != "plex" and not lib["type"])]


def refresh(kind, rel_path, s=None):
    """Ask the media server to pick up what was just written at `rel_path` (relative to
    the share's library path, folder included). Returns a sentence for the log."""
    s = s or db.all_settings()
    server, base, token = s.get("media_server"), _base(s), s.get("media_server_token")
    _share, folder = db.destination(kind)
    rel = (rel_path or "").strip("/")
    inside = rel[len(folder):].strip("/") if folder and rel.startswith(folder) else rel
    libs = libraries(s)
    targets = _targets(libs, kind, folder, inside, server)
    if not targets:
        return "%s has no %s library to scan." % (KINDS[server], {
            "movie": "film", "tv": "TV", "music": "music"}.get(kind, kind))
    if server == "plex":
        for lib, path in targets:
            q = "?path=%s" % urllib.parse.quote(path) if path else ""
            _request("GET", "%s/library/sections/%s/refresh%s" % (base, lib["key"], q),
                     token, server)
    else:
        paths = [p for _l, p in targets if p]
        if paths:
            _request("POST", base + "/Library/Media/Updated", token, server,
                     body={"Updates": [{"Path": p, "UpdateType": "Created"} for p in paths]})
        else:
            _request("POST", base + "/Library/Refresh", token, server, body={})
    where = [p or l["title"] for l, p in targets]
    return "Asked %s to scan %s." % (KINDS[server], ", ".join(where))


def after_rip(kind, rel_path):
    """Called when a rip is in the library. In the background, so a slow media server
    never holds the drive."""
    s = db.all_settings()
    if not configured(s):
        return

    def go():
        try:
            log.info(refresh(kind, rel_path, s))
        except MediaServerError as e:
            log.warning("Couldn't tell your media server about %s: %s" % (rel_path, e))
        except Exception as e:
            log.warning("Couldn't tell your media server about %s: %s" % (rel_path, e))
    threading.Thread(target=go, name="riparr-mediaserver", daemon=True).start()
