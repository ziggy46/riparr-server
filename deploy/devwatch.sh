#!/bin/bash
# Keeps /dev in step with the host's optical drives, so a drive can be plugged in,
# unplugged and replugged without restarting the container. Run as root, in the
# background, by the entrypoint.
#
# Docker fixes a container's device list when it starts, so a USB drive that is
# replugged comes back as a device node the container doesn't have -- often with a
# different /dev/sg number too. But /sys inside the container is the host's, so the
# drive's major:minor is visible as soon as the host sees it. This makes the node.
#
# Only optical drives: block devices named sr*, and SCSI generic nodes whose SCSI
# device type is 5 (CD/DVD/BD). Every other disk's sg node is never created.
#
# Creating a node is always allowed; *opening* it needs the container to be allowed
# that device class:
#     device_cgroup_rules: ["b 11:* rmw", "c 21:* rmw"]
# Without those the node exists but every read fails, and this says so once.
#
# Nodes are root:$GROUP, mode 0660, so the unprivileged service can use them.
set -uo pipefail

SYSFS="${RIPARR_SYSFS:-/sys}"
DEV="${RIPARR_DEVDIR:-/dev}"
GROUP="${PGID:-0}"
INTERVAL="${RIPARR_DEVWATCH_INTERVAL:-3}"
STATE="${RIPARR_DEVWATCH_STATE:-/run/riparr-devwatch}"

mkdir -p "$STATE"
touch "$STATE/created"

# The optical nodes the host has right now: "<b|c> <name> <major:minor>" per line.
wanted() {
  local d t
  for d in "$SYSFS"/class/block/sr*; do
    [ -e "$d/dev" ] || continue
    echo "b $(basename "$d") $(cat "$d/dev")"
  done
  for d in "$SYSFS"/class/scsi_generic/sg*; do
    [ -e "$d/dev" ] || continue
    t="$(cat "$d/device/type" 2>/dev/null || true)"
    [ "$t" = 5 ] || continue
    echo "c $(basename "$d") $(cat "$d/dev")"
  done
}

# Is this node already what the host says it should be?
matches() {
  local kind="$1" path="$2" majmin="$3" have
  if [ "$kind" = b ]; then
    [ -b "$path" ] || return 1
  else
    [ -c "$path" ] || return 1
  fi
  have="$(stat -c '%Hr:%Lr' "$path" 2>/dev/null)" || return 1
  [ "$have" = "$majmin" ]
}

# Can this node actually be opened? EPERM means the cgroup rules are missing.
openable() {
  python3 - "$1" <<'PY'
import errno, os, sys
try:
    os.close(os.open(sys.argv[1], os.O_RDONLY | os.O_NONBLOCK))
except OSError as e:
    sys.exit(3 if e.errno == errno.EPERM else 0)
PY
}

warned=0
sync_once() {
  local kind name majmin path now
  now="$(wanted)"
  while read -r kind name majmin; do
    [ -n "${name:-}" ] || continue
    path="$DEV/$name"
    if ! matches "$kind" "$path" "$majmin"; then
      rm -f "$path"
      if mknod "$path" "$kind" "${majmin%%:*}" "${majmin##*:}"; then
        grep -qx "$name" "$STATE/created" || echo "$name" >> "$STATE/created"
        echo "riparr: optical device $path is present"
      else
        continue
      fi
    fi
    chown "0:$GROUP" "$path" 2>/dev/null
    chmod 0660 "$path" 2>/dev/null
    if [ "$warned" = 0 ] && [ "$kind" = c ]; then
      openable "$path"
      if [ $? = 3 ]; then
        warned=1
        echo "riparr: $path can't be opened (operation not permitted). The usual cause is"
        echo "riparr: missing device_cgroup_rules: [\"b 11:* rmw\", \"c 21:* rmw\"] in"
        echo "riparr: docker-compose.yml. Or pass the drive with devices: instead."
      fi
    fi
  done <<< "$now"

  # Remove nodes this script made whose device has gone from the host.
  local keep
  keep="$(printf '%s\n' "$now" | awk '{print $2}')"
  while read -r name; do
    [ -n "$name" ] || continue
    if ! grep -qx "$name" <<< "$keep"; then
      rm -f "$DEV/$name"
      grep -vx "$name" "$STATE/created" > "$STATE/created.tmp" || true
      mv "$STATE/created.tmp" "$STATE/created"
      echo "riparr: optical device $DEV/$name went away"
    fi
  done < "$STATE/created"
}

if [ "${1:-}" = "--once" ]; then
  sync_once
  exit 0
fi
while :; do
  sync_once
  sleep "$INTERVAL"
done
