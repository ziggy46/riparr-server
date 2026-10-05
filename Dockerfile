# Riparr Server. Build it yourself -- MakeMKV is proprietary, so the image is not
# published with it inside:
#
#   docker build --build-arg MAKEMKV_ACCEPT_EULA=yes -t riparr-server .
#
# MAKEMKV_ACCEPT_EULA=yes means you have read and accept https://www.makemkv.com/eula/
FROM debian:trixie-slim

ARG MAKEMKV_ACCEPT_EULA=no

# The tool installer runs first and on its own, so changing Riparr's code does not
# throw away a MakeMKV build that took several minutes.
COPY deploy/install-tools.sh /opt/riparr/deploy/install-tools.sh
COPY tools/makemkv-install.sh /opt/riparr/tools/makemkv-install.sh
COPY packaging/makemkv-manifest.json /opt/riparr/packaging/makemkv-manifest.json
COPY packaging/dvdtools-install.sh /opt/riparr/packaging/dvdtools-install.sh
RUN if [ "$MAKEMKV_ACCEPT_EULA" != "yes" ]; then \
      echo "MakeMKV's licence has to be accepted to build this image:"; \
      echo "  read https://www.makemkv.com/eula/, then build with"; \
      echo "  --build-arg MAKEMKV_ACCEPT_EULA=yes"; \
      exit 1; \
    fi \
 && bash /opt/riparr/deploy/install-tools.sh --accept-eula --slim

COPY server/requirements.txt /opt/riparr/server/requirements.txt
RUN python3 -m venv /opt/riparr/.venv \
 && /opt/riparr/.venv/bin/pip install --no-cache-dir -q -r /opt/riparr/server/requirements.txt

COPY server /opt/riparr/server
COPY deploy/entrypoint.sh /opt/riparr/deploy/entrypoint.sh

# /data      database, session secret and MakeMKV's key (HOME, so ~/.MakeMKV lands here)
# /srv/staging   where a rip is written before it is copied to your share
# /srv/library   optional: bind-mount your library here to rip straight into it
ENV RIPARR_PORT=9797 \
    RIPARR_DB=/data/riparr.db \
    RIPARR_STAGING=/srv/staging \
    HOME=/data \
    PYTHONUNBUFFERED=1

VOLUME ["/data", "/srv/staging"]
EXPOSE 9797
WORKDIR /opt/riparr/server

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
  CMD python3 -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/setup/state' % os.environ.get('RIPARR_PORT','9797'), timeout=4)"

ENTRYPOINT ["/opt/riparr/deploy/entrypoint.sh"]
