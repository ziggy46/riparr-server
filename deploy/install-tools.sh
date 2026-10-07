#!/bin/bash
# Installs the packages the Riparr Server image carries, on Debian, as root. Run by the
# Dockerfile, and by install.sh with --host, which leaves apt's package lists in place:
# emptying them makes sense for an image, not for somebody's server.
#
# MakeMKV and libdvdcss are deliberately NOT installed here. MakeMKV is proprietary and
# can only be fetched by somebody who has accepted its licence, so the published image
# can't contain it; libdvdcss is kept out for the same kind of reason. Both are compiled
# on the first start instead (deploy/build-tools.sh), into the /data volume, which is why
# the compilers stay in the image.
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "Run this as root." >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive

PKGS=(
  # Riparr itself
  python3 python3-venv ca-certificates curl smbclient eject util-linux procps tini
  dvdbackup
  # Audio CDs: the careful reader, and the lossless encoder
  cdparanoia flac
  # Building MakeMKV and libdvdcss on first start
  build-essential pkg-config libssl-dev libexpat1-dev zlib1g-dev
  libavcodec-dev libavutil-dev libavformat-dev meson ninja-build xz-utils
)

apt-get update -qq
apt-get install -y -qq --no-install-recommends "${PKGS[@]}"
if [ "${1:-}" != --host ]; then
  apt-get clean
  rm -rf /var/lib/apt/lists/*
fi
