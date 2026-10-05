"""
Checking for a new release.

Upstream Riparr replaces its own files in place, because an appliance with no screen
has nobody to do it. A container doesn't: the image is the unit
of deployment, and a process rewriting itself underneath Docker would be undone by the
next `docker compose up` anyway. So this only looks, and says how to update.

RIPARR_UPDATE_REPO points the check at a different fork.
"""
import json
import os
import re
import urllib.error
import urllib.request

from . import __version__

REPO = os.environ.get("RIPARR_UPDATE_REPO", "ziggy46/riparr-server")
GITHUB_API = "https://api.github.com"


def current_version():
    return __version__


def how_to_update():
    return "docker compose pull && docker compose up -d"


def check(repo=REPO, timeout=8):
    """Never raises. A server with no internet still has to run."""
    url = "%s/repos/%s/releases/latest" % (GITHUB_API, repo)
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "riparr-server/%s" % __version__,
    })
    base = {"current": __version__, "repo": repo,
            "how": how_to_update()}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return dict(base, status="no-releases", message="No published releases yet.")
        return dict(base, status="error", message="GitHub returned HTTP %s" % e.code)
    except Exception as e:
        return dict(base, status="offline", message="Could not reach GitHub: %s" % e)

    latest = (data.get("tag_name") or "").lstrip("v")
    newer = _newer(latest, __version__)
    return dict(base,
                status="update" if newer else "current",
                latest=latest,
                tag=data.get("tag_name"),
                notes=data.get("body") or "",
                published=data.get("published_at"),
                url=data.get("html_url"),
                message=("Version %s is available." % latest) if newer
                        else "Riparr is up to date.")


def install(repo=REPO):
    return {"ok": False, "message": how_to_update()}


def _newer(a, b):
    def parts(v):
        return [int(x) if x.isdigit() else 0
                for x in re.split(r"[.\-+]", v or "") if x != ""]
    pa, pb = parts(a), parts(b)
    n = max(len(pa), len(pb))
    return (pa + [0] * (n - len(pa))) > (pb + [0] * (n - len(pb)))
