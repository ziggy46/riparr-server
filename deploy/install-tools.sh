#!/bin/bash
# Installs everything Riparr Server needs outside its own Python code, on Debian or
# Ubuntu, as root: the runtime packages, MakeMKV (built from source), and the DVD
# backup tools (dvdbackup + libdvdcss).
#
# Run by the Dockerfile. Both MakeMKV and libdvdcss are fetched by upstream's own
# installers, which check every download against a checksum pinned in this repository.
#
#   install-tools.sh --accept-eula [--slim] [--jobs N]
#
# --accept-eula  You have read and accept MakeMKV's licence: https://www.makemkv.com/eula/
#                Nothing is downloaded without it.
# --slim         Remove the compilers afterwards (for container images). The shared
#                libraries MakeMKV and libdvdcss actually link against are kept.
set -euo pipefail

ACCEPT=0
SLIM=0
JOBS="$(nproc 2>/dev/null || echo 2)"
while [ $# -gt 0 ]; do
  case "$1" in
    --accept-eula) ACCEPT=1 ;;
    --slim) SLIM=1 ;;
    --jobs) JOBS="$2"; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ "$ACCEPT" != 1 ]; then
  cat >&2 <<'EOF'
MakeMKV is proprietary software by GuinpinSoft inc, with its own licence:
    https://www.makemkv.com/eula/
Read it, then re-run with --accept-eula to confirm you accept it.
EOF
  exit 1
fi
[ "$(id -u)" = 0 ] || { echo "Run this as root." >&2; exit 1; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
export DEBIAN_FRONTEND=noninteractive

RUNTIME_PKGS=(python3 python3-venv ca-certificates curl smbclient eject util-linux
              dvdbackup procps)
BUILD_PKGS=(build-essential pkg-config libssl-dev libexpat1-dev zlib1g-dev
            libavcodec-dev libavutil-dev libavformat-dev time meson ninja-build xz-utils)

echo "=== Packages ==="
apt-get update -qq
apt-get install -y -qq --no-install-recommends "${RUNTIME_PKGS[@]}" "${BUILD_PKGS[@]}"

# Upstream's installers call `sudo make install`. Root needs no sudo, and a minimal
# image has none, so put a pass-through on PATH for the duration.
SHIM="$(mktemp -d)"
trap 'rm -rf "$SHIM"' EXIT
printf '#!/bin/sh\nexec "$@"\n' > "$SHIM/sudo"
chmod +x "$SHIM/sudo"
export PATH="$SHIM:$PATH"

echo "=== MakeMKV ==="
SRC="$(mktemp -d)"
HOME=/root bash "$ROOT/tools/makemkv-install.sh" --accept-eula --jobs "$JOBS" --srcdir "$SRC"
rm -rf "$SRC" /root/validation

echo "=== DVD backup tools ==="
mkdir -p /run/riparr
if ! bash "$ROOT/packaging/dvdtools-install.sh"; then
  cat /run/riparr/dvdtools.log >&2 || true
  exit 1
fi

# Prove the result links, rather than finding out on the first disc.
check_links() {
  local missing
  missing="$(ldd "$@" 2>/dev/null | grep 'not found' || true)"
  if [ -n "$missing" ]; then
    echo "Missing shared libraries:" >&2
    echo "$missing" >&2
    exit 1
  fi
}

LINKED=(/usr/bin/makemkvcon)
for l in /usr/lib/libmakemkv.so* /usr/lib/libdriveio.so* /usr/lib/libmmbd.so* \
         /usr/local/lib/libdvdcss.so*; do
  [ -e "$l" ] && LINKED+=("$l")
done
check_links "${LINKED[@]}"

if [ "$SLIM" = 1 ]; then
  echo "=== Removing build tools ==="
  # Purging the -dev packages would let autoremove take their runtime libraries with
  # them, because dpkg has no idea makemkvcon needs those. So first mark every package
  # that owns a library these binaries load as manually installed.
  keep="$(ldd "${LINKED[@]}" 2>/dev/null | awk '/=>/ {print $3}' | sort -u \
          | xargs -r readlink -f | xargs -r dpkg -S 2>/dev/null \
          | cut -d: -f1 | sort -u || true)"
  [ -n "$keep" ] && apt-mark manual $keep >/dev/null
  apt-get purge -y -qq "${BUILD_PKGS[@]}" >/dev/null
  apt-get autoremove -y -qq --purge >/dev/null
  apt-get clean
  rm -rf /var/lib/apt/lists/*
  check_links "${LINKED[@]}"
fi

echo "=== Done ==="
echo "MakeMKV $(cat /usr/local/lib/riparr/makemkv.version 2>/dev/null || echo '?')," \
     "dvdbackup $(command -v dvdbackup), libdvdcss $(ldconfig -p | grep -c 'libdvdcss\.so') lib(s)"
