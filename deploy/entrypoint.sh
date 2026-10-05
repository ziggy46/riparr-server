#!/bin/sh
# Container entrypoint: make sure the persistent paths exist, then run the service.
set -e

mkdir -p "$(dirname "${RIPARR_DB:-/data/riparr.db}")" "${RIPARR_STAGING:-/srv/staging}" \
         "${HOME:-/data}"

if ! ls /dev/sr* >/dev/null 2>&1; then
  echo "riparr: no optical drive visible in this container (/dev/sr*)." >&2
  echo "riparr: pass it through, e.g. --device /dev/sr0 --device /dev/sg1" >&2
fi

exec /opt/riparr/.venv/bin/python -m uvicorn riparr.main:app \
  --host "${RIPARR_HOST:-0.0.0.0}" --port "${RIPARR_PORT:-9797}" "$@"
