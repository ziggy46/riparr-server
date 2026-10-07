"""Riparr Server — the service. Single process, SQLite, no external daemons (D2)."""
__version__ = "0.8.0"


def build():
    """Which build is running: the version, the image channel and the commit.

    The channel is baked into the image by the publish workflow -- "latest" for a
    release, "edge" for a build of main, "local" for an image built by hand. Running
    from a source checkout there's no image at all, which is "dev".
    """
    import os
    commit = (os.environ.get("RIPARR_COMMIT") or "").strip()
    return {"version": __version__,
            "channel": (os.environ.get("RIPARR_CHANNEL") or "dev").strip() or "dev",
            "commit": commit[:7] or None,
            "install": install()}


def install():
    """How this was installed: "docker", or "bare" for deploy/install.sh, whose
    service sets RIPARR_INSTALL. It decides what advice the interface gives -- a
    `docker compose` command is no use to somebody running it under systemd."""
    import os
    return "bare" if (os.environ.get("RIPARR_INSTALL") or "").strip() == "bare" else "docker"
