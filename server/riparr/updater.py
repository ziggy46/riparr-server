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

from . import __version__, install as install_kind

REPO = os.environ.get("RIPARR_UPDATE_REPO", "ziggy46/riparr-server")
GITHUB_API = "https://api.github.com"


def current_version():
    return __version__


def how_to_update():
    if install_kind() == "bare":
        return "sudo /opt/riparr/deploy/install.sh --update"
    return "docker compose pull && docker compose up -d"


# A release can say how to update to it, overriding how_to_update() above. The line goes
# anywhere in the release notes, as an HTML comment so GitHub doesn't show it:
#
#     <!-- riparr-update: docker compose pull && docker compose up -d -->
#
# and for an install made by deploy/install.sh, which updates differently:
#
#     <!-- riparr-update-bare: sudo /opt/riparr/deploy/install.sh --update -->
#
# This exists because the instruction is otherwise fixed in the version already running.
# 0.5.1 told everybody to `git pull && docker compose up -d --build` for 0.6.0, which no
# longer worked, and nothing published afterwards could change what 0.5.1 said.
UPDATE_HINT_RE = re.compile(r"<!--\s*riparr-update(-bare)?:\s*(.+?)\s*-->", re.I | re.S)


def release_how(notes, kind=None):
    """(the release's own update instruction for this kind of install or None, the
    notes without any of them)."""
    want = "-bare" if (kind or install_kind()) == "bare" else None
    how = None
    for m in UPDATE_HINT_RE.finditer(notes or ""):
        if (m.group(1) or None) == want:
            how = " ".join(m.group(2).split())[:300] or None
    return how, UPDATE_HINT_RE.sub("", notes or "").strip()


def check(repo=REPO, timeout=8):
    """Never raises. A server with no internet still has to run."""
    url = "%s/repos/%s/releases/latest" % (GITHUB_API, repo)
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "riparr-server/%s" % __version__,
    })
    from . import build
    base = {"current": __version__, "build": build(), "repo": repo,
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
    how, notes = release_how(data.get("body"))
    if how:
        base["how"] = how
    # An edge build is ahead of every release: "up to date" would be checking it against
    # something it already has, and a release would be a step back.
    edge = base["build"].get("channel") == "edge" and not newer
    return dict(base,
                status="update" if newer else "edge" if edge else "current",
                latest=latest,
                tag=data.get("tag_name"),
                notes=notes,
                published=data.get("published_at"),
                url=data.get("html_url"),
                message=("Version %s is available." % latest) if newer
                        else ("You're on edge, built from the newest code on main: newer "
                              "than the latest release, %s." % latest) if edge
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
