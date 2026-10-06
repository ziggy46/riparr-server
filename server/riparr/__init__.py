"""Riparr Server — the service. Single process, SQLite, no external daemons (D2)."""
__version__ = "0.7.1"


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
            "commit": commit[:7] or None}
