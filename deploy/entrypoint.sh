#!/bin/bash
# Container entrypoint. Starts as root to do the few things that need it, then runs
# Riparr as PUID:PGID:
#
#   1. a user for PUID/PGID, so files Riparr writes belong to you rather than root
#   2. MakeMKV and libdvdcss, built into /data the first time and reused after that
#   3. the optical-drive watcher (devwatch.sh), which stays running as root
#   4. Riparr itself, unprivileged
set -uo pipefail

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
export PGID
DATA="$(dirname "${RIPARR_DB:-/data/riparr.db}")"
STAGING="${RIPARR_STAGING:-/srv/staging}"
mkdir -p "$DATA" "$STAGING" "$DATA/tools"

say() { echo "riparr: $*"; }
off() { case "${1:-}" in ""|0|no|false|off) return 0 ;; *) return 1 ;; esac; }

# ── 1. the account ──
if [ "$PUID" != 0 ]; then
  if ! getent group "$PGID" >/dev/null; then
    groupadd -o -g "$PGID" riparr
  fi
  if getent passwd riparr >/dev/null; then
    usermod -o -u "$PUID" -g "$PGID" riparr >/dev/null
  else
    # A real passwd entry, not just a number: smbclient looks the uid up.
    useradd -o -u "$PUID" -g "$PGID" -d "$DATA" -s /usr/sbin/nologin -M riparr
  fi
  # Only what isn't already ours, so a full staging folder isn't re-chowned on every
  # start. Never the library: that is the user's, and may be a NAS mount.
  find "$DATA" "$STAGING" \( ! -user "$PUID" -o ! -group "$PGID" \) \
       -exec chown -h "$PUID:$PGID" {} + 2>/dev/null
fi

# ── 2. MakeMKV and libdvdcss ──
if off "${RIPARR_MOCK:-}"; then
  bash /opt/riparr/deploy/build-tools.sh libdvdcss
  bash /opt/riparr/deploy/build-tools.sh makemkv
  [ "$PUID" != 0 ] && chown -R "$PUID:$PGID" "$DATA/tools" 2>/dev/null
fi

# ── 3. optical drives ──
if off "${RIPARR_MOCK:-}" && ! off "${RIPARR_DEVWATCH:-1}"; then
  bash /opt/riparr/deploy/devwatch.sh --once
  bash /opt/riparr/deploy/devwatch.sh &
fi
if off "${RIPARR_MOCK:-}" && ! ls /dev/sr* >/dev/null 2>&1; then
  say "no optical drive visible yet. Riparr will pick one up when it appears, as long as"
  say "  the container has device_cgroup_rules: [\"b 11:* rmw\", \"c 21:* rmw\"]."
fi

# ── 4. Riparr ──
umask "${UMASK:-022}"

# Recent Docker gives containers an open-files limit of about a billion. MakeMKV closes
# every possible descriptor, one by one, before starting its helper process -- so with
# that limit it sits at 100% CPU for half an hour and never reads the disc. Cap the soft
# limit; nothing here needs more than a few thousand.
NOFILE_CAP="${RIPARR_NOFILE:-65536}"
if [ "$(ulimit -n)" = "unlimited" ] || [ "$(ulimit -n)" -gt "$NOFILE_CAP" ] 2>/dev/null; then
  ulimit -n "$NOFILE_CAP" 2>/dev/null || ulimit -Sn "$NOFILE_CAP" 2>/dev/null || true
fi
CMD=(/opt/riparr/.venv/bin/python -m uvicorn riparr.main:app
     --host "${RIPARR_HOST:-0.0.0.0}" --port "${RIPARR_PORT:-9797}" "$@")
if [ "$PUID" = 0 ]; then
  exec "${CMD[@]}"
fi
# The watcher gives drive nodes our group. Nodes passed in with devices: and no watcher
# keep the host's group, so join whatever groups those have too.
GIDS="$(stat -c '%g' /dev/sr* /dev/sg* 2>/dev/null | grep -vx 0 | sort -u | paste -sd, -)"
say "running as uid $PUID, gid $PGID${GIDS:+, groups $GIDS}"
if [ -n "$GIDS" ]; then GROUPS_ARG="--groups=$GIDS"; else GROUPS_ARG="--clear-groups"; fi
exec setpriv --reuid="$PUID" --regid="$PGID" "$GROUPS_ARG" --inh-caps=-all \
     env HOME="$DATA" "${CMD[@]}"
