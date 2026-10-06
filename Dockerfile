# Riparr Server.
#
#   docker run -d --name riparr -p 9797:9797 \
#     -e MAKEMKV_ACCEPT_EULA=yes -e PUID=1000 -e PGID=1000 \
#     --device-cgroup-rule='b 11:* rmw' --device-cgroup-rule='c 21:* rmw' \
#     -v ./data:/data -v ./staging:/srv/staging \
#     ghcr.io/ziggy46/riparr-server:latest
#
# The image carries no MakeMKV and no libdvdcss. Both are compiled on the first start
# into /data -- MakeMKV only once MAKEMKV_ACCEPT_EULA=yes says you have read and accept
# https://www.makemkv.com/eula/ -- and reused after that.
FROM debian:trixie-slim

COPY deploy/install-tools.sh /opt/riparr/deploy/install-tools.sh
RUN bash /opt/riparr/deploy/install-tools.sh

COPY server/requirements.txt /opt/riparr/server/requirements.txt
RUN python3 -m venv /opt/riparr/.venv \
 && /opt/riparr/.venv/bin/pip install --no-cache-dir -q -r /opt/riparr/server/requirements.txt

COPY packaging/makemkv-manifest.json /opt/riparr/packaging/makemkv-manifest.json
COPY deploy /opt/riparr/deploy
COPY server /opt/riparr/server

# /data          database, settings, logs, backups, MakeMKV's key, and the compiled tools
# /srv/staging   where a rip is written before it is copied to your share
# /srv/library   optional: bind-mount your library here to rip straight into it
ENV RIPARR_PORT=9797 \
    RIPARR_DB=/data/riparr.db \
    RIPARR_STAGING=/srv/staging \
    HOME=/data \
    PUID=1000 \
    PGID=1000 \
    PYTHONUNBUFFERED=1

VOLUME ["/data", "/srv/staging"]
EXPOSE 9797
WORKDIR /opt/riparr/server

# The first start compiles MakeMKV before the web interface comes up.
HEALTHCHECK --interval=60s --timeout=5s --start-period=15m \
  CMD python3 -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/setup/state' % os.environ.get('RIPARR_PORT','9797'), timeout=4)"

# Which build this is, shown next to the version in the interface. Set by the publish
# workflow: "latest" for a release, "edge" for a build of main. Last, so changing it
# doesn't invalidate the cached layers above.
ARG RIPARR_CHANNEL=local
ARG RIPARR_COMMIT=
ENV RIPARR_CHANNEL=$RIPARR_CHANNEL \
    RIPARR_COMMIT=$RIPARR_COMMIT

# tini as PID 1: the drive watcher runs alongside Riparr and someone has to reap.
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/riparr/deploy/entrypoint.sh"]
