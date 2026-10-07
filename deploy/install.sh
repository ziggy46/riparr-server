#!/bin/bash
# shellcheck disable=SC1090,SC1091  # it reads its own settings files, by design
# Installs Riparr Server straight onto Debian or Ubuntu, without Docker: the same
# packages, MakeMKV build and service the image carries, run by systemd.
#
#   curl -fsSL https://raw.githubusercontent.com/ziggy46/riparr-server/main/deploy/install.sh | sudo bash
#   sudo bash deploy/install.sh               from a checkout: installs that checkout
#
# Run it again, or with --update, to update. Everything it does:
#
#   /opt/riparr                 the code and its Python environment (replaced on update)
#   /etc/riparr/riparr.env      your settings: port, folders, the MakeMKV licence
#   /var/lib/riparr             the database, logs, backups, MakeMKV's key and its build
#   /var/lib/riparr/staging     where a rip is written before it goes to your library
#   riparr.service              runs it as the `riparr` user, in the `cdrom` group
#
# MakeMKV is compiled from source (a few minutes, once) and installed into /usr, as the
# image does on its first start. It's only built once you've accepted its licence.
#
# Options:
#   --accept-eula      you have read and accept https://www.makemkv.com/eula/
#   --port N           the web interface's port (default 9797)
#   --data DIR         where the database and settings go (default /var/lib/riparr)
#   --staging DIR      where rips are staged (default /var/lib/riparr/staging)
#   --edge             install the newest code on main, and keep updating from it
#   --release          install the latest release, and keep updating from releases
#   --version X.Y.Z    install that release
#   --update           update whatever is installed, from where it came from
#   --from DIR         install from a source checkout at DIR
#   --no-start         install, but don't start the service
#   --uninstall        remove Riparr; keeps your data and settings
#   --purge            with --uninstall: remove those too, and the riparr user
set -euo pipefail

REPO="${RIPARR_UPDATE_REPO:-ziggy46/riparr-server}"
PREFIX=/opt/riparr
CONF_DIR=/etc/riparr
CONF="$CONF_DIR/riparr.env"
UNIT=/etc/systemd/system/riparr.service
SERVICE_USER=riparr

say() { echo "riparr: $*"; }
die() { echo "riparr: $*" >&2; exit 1; }

# An update replaces this very file. Bash reads a script as it goes, so run a copy.
if [ -z "${RIPARR_INSTALL_COPY:-}" ] && [ -n "${BASH_SOURCE[0]:-}" ] \
   && [ -f "${BASH_SOURCE[0]}" ] && [ "${BASH_SOURCE[0]}" -ef "$PREFIX/deploy/install.sh" ]; then
  copy="$(mktemp)"
  cp "${BASH_SOURCE[0]}" "$copy"
  RIPARR_INSTALL_COPY="$copy" exec bash "$copy" "$@"
fi
[ -n "${RIPARR_INSTALL_COPY:-}" ] && trap 'rm -f "$RIPARR_INSTALL_COPY"' EXIT

# ── options ──
ACCEPT=""; PORT=""; DATA=""; STAGING=""; WANT=""; VERSION=""; FROM=""
START=1; UNINSTALL=""; PURGE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --accept-eula) ACCEPT=yes ;;
    --port) PORT="${2:?--port needs a number}"; shift ;;
    --data) DATA="${2:?--data needs a folder}"; shift ;;
    --staging) STAGING="${2:?--staging needs a folder}"; shift ;;
    --edge) WANT=edge ;;
    --release|--latest) WANT=latest ;;
    --version) WANT=version; VERSION="${2:?--version needs a version}"; VERSION="${VERSION#v}"; shift ;;
    --update) ;;                          # the default for an existing install anyway
    --from) FROM="${2:?--from needs a folder}"; shift ;;
    --no-start) START="" ;;
    --uninstall) UNINSTALL=1 ;;
    --purge) PURGE=1 ;;
    -h|--help) echo "See the top of deploy/install.sh, or docs/guide/03-bare-metal.md."; exit 0 ;;
    *) die "unknown option $1 (try --help)" ;;
  esac
  shift
done

[ "$(id -u)" = 0 ] || die "run this as root: sudo bash $0"
[ "$(uname -s)" = Linux ] || die "Riparr needs Linux. On a Mac or Windows PC, run it in a Linux VM."
command -v apt-get >/dev/null || die "this installer is for Debian and Ubuntu (it needs apt-get)."
HAVE_SYSTEMD=""; [ -d /run/systemd/system ] && HAVE_SYSTEMD=1

# Settings from an earlier install win over the defaults, so an update keeps them.
if [ -f "$CONF" ]; then
  OLD_DB="$(. "$CONF"; echo "${RIPARR_DB:-}")"
  OLD_STAGING="$(. "$CONF"; echo "${RIPARR_STAGING:-}")"
  [ -n "$DATA" ] && [ -n "$OLD_DB" ] && [ "$DATA" != "$(dirname "$OLD_DB")" ] \
    && say "keeping the data folder from the first install, $(dirname "$OLD_DB"); edit $CONF to move it"
  DATA="$(dirname "${OLD_DB:-/var/lib/riparr/riparr.db}")"
  STAGING="${OLD_STAGING:-${STAGING:-$DATA/staging}}"
fi
DATA="${DATA:-/var/lib/riparr}"
STAGING="${STAGING:-$DATA/staging}"

# ── uninstall ──
if [ -n "$UNINSTALL" ]; then
  if [ -n "$HAVE_SYSTEMD" ] && [ -f "$UNIT" ]; then
    systemctl disable --now riparr >/dev/null 2>&1 || true
  fi
  rm -f "$UNIT"
  [ -n "$HAVE_SYSTEMD" ] && systemctl daemon-reload
  # MakeMKV and libdvdcss: exactly the files their builds put in place, nothing else.
  for root in "$DATA"/tools/*/root; do
    [ -d "$root" ] || continue
    (cd "$root" && find . \( -type f -o -type l \)) | while read -r f; do
      rm -f "/${f#./}"
    done
  done
  ldconfig
  rm -rf "$PREFIX"
  if [ -n "$PURGE" ]; then
    rm -rf "$DATA" "$STAGING" "$CONF_DIR"
    id "$SERVICE_USER" >/dev/null 2>&1 && userdel "$SERVICE_USER" 2>/dev/null || true
    say "removed Riparr, its data and its settings"
  else
    say "removed Riparr. Your data is still in $DATA and your settings in $CONF;"
    say "  run this again to reinstall with them, or with --uninstall --purge to delete them."
  fi
  exit 0
fi

# ── 1. packages ──
say "installing packages"
src_dir=""
if [ -n "$FROM" ]; then
  src_dir="$(cd "$FROM" && pwd)"
elif [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ] && [ -z "${RIPARR_INSTALL_COPY:-}" ]; then
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  [ -f "$here/server/riparr/__init__.py" ] && [ "$here" != "$PREFIX" ] && src_dir="$here"
fi
[ -n "$src_dir" ] && [ ! -f "$src_dir/server/riparr/__init__.py" ] && die "$src_dir isn't a Riparr Server checkout"
apt-get update -qq
if [ -n "$src_dir" ]; then
  bash "$src_dir/deploy/install-tools.sh" --host
else
  # The package list lives with the code, which isn't here yet: fetch just that file.
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends curl ca-certificates python3 >/dev/null
fi

# ── 2. the code ──
work="$(mktemp -d)"
trap 'rm -rf "$work"; [ -n "${RIPARR_INSTALL_COPY:-}" ] && rm -f "$RIPARR_INSTALL_COPY"' EXIT
CHANNEL=""; COMMIT=""
if [ -n "$src_dir" ]; then
  CHANNEL=local
  COMMIT="$(git -C "$src_dir" rev-parse HEAD 2>/dev/null || true)"
  say "installing from $src_dir"
else
  # Where to update from: what was asked, else what's installed, else releases.
  if [ -z "$WANT" ] && [ -f "$PREFIX/build.env" ]; then
    WANT="$(. "$PREFIX/build.env"; echo "${RIPARR_CHANNEL:-latest}")"
    [ "$WANT" = local ] && WANT=latest
  fi
  WANT="${WANT:-latest}"
  api() { curl -fsSL -H "Accept: application/vnd.github+json" "https://api.github.com/repos/$REPO/$1"; }
  json() { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }
  case "$WANT" in
    edge)
      COMMIT="$(api commits/main | json '["sha"]')" || die "couldn't ask GitHub for the newest code"
      ref="$COMMIT"; CHANNEL=edge ;;
    version)
      ref="refs/tags/v$VERSION"; CHANNEL=latest ;;
    *)
      tag="$(api releases/latest | json '["tag_name"]')" || die "couldn't ask GitHub for the latest release"
      ref="refs/tags/$tag"; CHANNEL=latest ;;
  esac
  say "downloading ${ref#refs/tags/} from github.com/$REPO"
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$ref" -o "$work/src.tar.gz" \
    || die "couldn't download it"
  mkdir "$work/src"
  tar -xzf "$work/src.tar.gz" -C "$work/src" --strip-components=1
  src_dir="$work/src"
  bash "$src_dir/deploy/install-tools.sh" --host
fi

if [ -n "$HAVE_SYSTEMD" ] && systemctl is-active --quiet riparr 2>/dev/null; then
  say "stopping Riparr to update it"
  systemctl stop riparr
fi
mkdir -p "$PREFIX"
rm -rf "$PREFIX/server" "$PREFIX/deploy" "$PREFIX/packaging"
tar -C "$src_dir" --exclude=.venv --exclude=__pycache__ -cf - server deploy packaging \
  | tar -C "$PREFIX" -xf -
cat > "$PREFIX/build.env" <<EOF
# Written by install.sh: which build this is. Not a settings file -- see $CONF.
RIPARR_CHANNEL=$CHANNEL
RIPARR_COMMIT=$COMMIT
EOF

say "setting up Python"
if ! "$PREFIX/.venv/bin/python" -c "" 2>/dev/null; then
  rm -rf "$PREFIX/.venv"                 # missing, or the system Python moved under it
  python3 -m venv "$PREFIX/.venv"
fi
"$PREFIX/.venv/bin/pip" install -q --disable-pip-version-check --upgrade \
  -r "$PREFIX/server/requirements.txt"

# ── 3. the user, folders and settings ──
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "$DATA" --no-create-home \
          --shell /usr/sbin/nologin "$SERVICE_USER"
fi
# The drive: udev gives optical drives' sr and sg nodes to the cdrom group.
getent group cdrom >/dev/null && usermod -aG cdrom "$SERVICE_USER"
mkdir -p "$DATA/tools" "$STAGING" "$CONF_DIR"

if [ ! -f "$CONF" ]; then
  cat > "$CONF" <<EOF
# Riparr Server's settings. After changing one: sudo systemctl restart riparr
# Everything else is set in the web interface.

# The web interface.
RIPARR_HOST=0.0.0.0
RIPARR_PORT=${PORT:-9797}

# "yes" means you have read and accept MakeMKV's licence: https://www.makemkv.com/eula/
# Riparr then compiles MakeMKV the next time it starts, which takes a few minutes.
MAKEMKV_ACCEPT_EULA=no

# Where things go.
RIPARR_DB=$DATA/riparr.db
RIPARR_STAGING=$STAGING
RIPARR_TOOLS_DIR=$DATA/tools
# Mount your library here to rip straight into it rather than copying over SMB.
# RIPARR_LIBRARY_MOUNT=/srv/library

# Networks to look for your NAS on, if the setup wizard's scan finds nothing.
# RIPARR_SCAN_SUBNETS=192.168.1.0/24
EOF
elif [ -n "$PORT" ]; then
  sed -i "s/^RIPARR_PORT=.*/RIPARR_PORT=$PORT/" "$CONF"
fi

# ── 4. MakeMKV's licence ──
eula="$(. "$CONF"; echo "${MAKEMKV_ACCEPT_EULA:-no}")"
if [ "$eula" != yes ] && [ -z "$ACCEPT" ] && [ -r /dev/tty ] && ( : < /dev/tty ) 2>/dev/null; then
  echo
  echo "Riparr reads discs with MakeMKV, which is proprietary software by GuinpinSoft."
  echo "Its licence is at https://www.makemkv.com/eula/"
  printf "Type yes if you have read and accept it, or press Enter to skip for now: "
  read -r reply < /dev/tty || reply=""
  [ "$reply" = yes ] && ACCEPT=yes
fi
if [ -n "$ACCEPT" ]; then
  sed -i 's/^MAKEMKV_ACCEPT_EULA=.*/MAKEMKV_ACCEPT_EULA=yes/' "$CONF"
  eula=yes
fi

# ── 5. MakeMKV and libdvdcss ──
# Built here once, so the first start isn't minutes of silence. The service checks them
# again on every start, and rebuilds one if a system update moved a library under it.
(
  set -a; . "$CONF"; set +a
  bash "$PREFIX/deploy/build-tools.sh" libdvdcss || say "libdvdcss didn't build; DVDs that need it won't decrypt"
  bash "$PREFIX/deploy/build-tools.sh" makemkv || say "MakeMKV didn't build; the log above says why"
)
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA"
chown "$SERVICE_USER:$SERVICE_USER" "$STAGING"
chmod 640 "$CONF"; chgrp "$SERVICE_USER" "$CONF"

# ── 6. the service ──
cat > "$UNIT" <<EOF
# Written by $PREFIX/deploy/install.sh; running it again rewrites this file. Settings
# belong in $CONF.
[Unit]
Description=Riparr Server
Documentation=https://github.com/$REPO
After=network-online.target remote-fs.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
EnvironmentFile=$CONF
EnvironmentFile=-$PREFIX/build.env
Environment=RIPARR_INSTALL=bare HOME=$DATA PYTHONUNBUFFERED=1
WorkingDirectory=$PREFIX/server
# As root (the +): put MakeMKV and libdvdcss in place, and rebuild one if a system
# update moved a library it links against. Quick when nothing changed. A failed build
# (the -) still starts Riparr, which then says MakeMKV isn't installed and why.
ExecStartPre=-+/bin/bash $PREFIX/deploy/build-tools.sh libdvdcss
ExecStartPre=-+/bin/bash $PREFIX/deploy/build-tools.sh makemkv
ExecStartPre=-+/bin/chown -R $SERVICE_USER:$SERVICE_USER $DATA/tools
ExecStart=$PREFIX/.venv/bin/python -m uvicorn riparr.main:app --host \${RIPARR_HOST} --port \${RIPARR_PORT}
# A rebuild after a system update takes minutes.
TimeoutStartSec=45min
# MakeMKV hangs when the open-files limit is huge.
LimitNOFILE=65536
UMask=0022
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

port="$(. "$CONF"; echo "${RIPARR_PORT:-9797}")"
addr="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
if [ -n "$HAVE_SYSTEMD" ]; then
  systemctl daemon-reload
  systemctl enable riparr >/dev/null 2>&1
  if [ -n "$START" ]; then
    systemctl restart riparr
    say "Riparr is running: http://${addr:-this-machine}:$port"
  else
    say "installed. Start it with: sudo systemctl start riparr"
  fi
  say "  logs: journalctl -u riparr -f     settings: $CONF"
else
  say "installed, but this machine isn't running systemd, so nothing will start it."
  say "  $UNIT shows how it's meant to run; start it the same way with your init system."
fi
if [ "$eula" != yes ]; then
  say "MakeMKV isn't installed yet. Once you've read https://www.makemkv.com/eula/, set"
  say "  MAKEMKV_ACCEPT_EULA=yes in $CONF and run: sudo systemctl restart riparr"
fi
say "update later with: sudo $PREFIX/deploy/install.sh --update"
