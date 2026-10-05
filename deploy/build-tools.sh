#!/bin/bash
# Builds MakeMKV and libdvdcss into the /data volume, and makes them live in this
# container. Run as root by the entrypoint on every start; cheap after the first.
#
#   build-tools.sh makemkv     needs MAKEMKV_ACCEPT_EULA=yes
#   build-tools.sh libdvdcss
#
# Each tool is compiled once into $TOOLS/<name>-<version>-<arch>/root (via DESTDIR), and
# on every start that tree is copied over / . A container is recreated on every image
# update, so the copy is what makes a build survive that without compiling again.
#
# A cached build links against the image's libraries (libavcodec, libssl). When a new
# image moves those, the old build stops loading -- so after activating, everything is
# checked with ldd, and a build that no longer links is thrown away and rebuilt.
set -uo pipefail

TOOLS="${RIPARR_TOOLS_DIR:-/data/tools}"
MANIFEST="${RIPARR_MAKEMKV_MANIFEST:-/opt/riparr/packaging/makemkv-manifest.json}"
ARCH="$(uname -m)"
JOBS="$(nproc 2>/dev/null || echo 2)"

DVDCSS_VERSION=1.6.0
DVDCSS_SHA256=7ea556c846b7bfc32d47b41cae56d1863a6b6d5f706bb162778d6f298490977c
DVDCSS_URL="https://download.videolan.org/pub/videolan/libdvdcss/$DVDCSS_VERSION/libdvdcss-$DVDCSS_VERSION.tar.xz"

say() { echo "riparr: $*"; }
sha_of() { sha256sum "$1" | cut -d" " -f1; }

# Activate a cached tree: copy it over /, then prove what it installed still links.
activate() {
  local dir="$1"
  cp -a "$dir/root/." /
  ldconfig
  local libs
  libs="$(find "$dir/root" -type f \( -name '*.so*' -o -path '*/bin/*' \) | sed "s|^$dir/root||")"
  local out
  # Into a variable first: `ldd | grep -q` under pipefail reports ldd's SIGPIPE when
  # grep stops early, which turned "missing library" into "fine".
  # shellcheck disable=SC2086
  out="$(ldd $libs 2>/dev/null)"
  case "$out" in
    *"not found"*) return 1 ;;
  esac
  return 0
}

# Download one file from the first source whose bytes match the checksum.
# fetch <dest> <sha256> <url> [<url>...]
fetch() {
  local dest="$1" want="$2"; shift 2
  local url
  for url in "$@"; do
    say "  downloading $(basename "$dest") from ${url#https://}"
    if curl -fsSL --compressed --retry 2 --connect-timeout 20 --max-time 900 \
            -o "$dest.part" "$url"; then
      if [ "$(sha_of "$dest.part")" = "$want" ]; then
        mv "$dest.part" "$dest"
        return 0
      fi
      say "  that copy didn't match its checksum; trying the next source"
    fi
    rm -f "$dest.part"
  done
  return 1
}

# Run a build; on failure leave nothing half-made behind and say where the log is.
# build <name> <dir> <function>
build() {
  local name="$1" dir="$2" fn="$3" log="$TOOLS/$1-build.log"
  local work
  work="$(mktemp -d)"
  rm -rf "$dir"
  mkdir -p "$dir/root"
  say "building $name -- the first start only, a few minutes (log: $log)"
  # Not `if "$fn"`: bash ignores set -e inside anything run as an if-condition, so a
  # failed compile would carry on and look like success.
  local rc
  ( set -e; "$fn" "$work" "$dir/root" ) >"$log" 2>&1
  rc=$?
  if [ "$rc" = 0 ]; then
    touch "$dir/complete"
    rm -rf "$work"
    say "built $name"
    return 0
  fi
  say "building $name FAILED. The last lines of $log:"
  tail -n 15 "$log" | sed 's/^/    /'
  rm -rf "$work" "$dir"
  return 1
}

ensure() {
  local name="$1" dir="$2" fn="$3"
  if [ -f "$dir/complete" ]; then
    if activate "$dir"; then
      return 0
    fi
    say "the cached $name build no longer matches this image's libraries; rebuilding"
  fi
  build "$name" "$dir" "$fn" || return 1
  activate "$dir" || { say "$name built but doesn't link; see $TOOLS/$name-build.log"; return 1; }
}

# ── MakeMKV ──

makemkv_version() {
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$MANIFEST"
}

build_makemkv() {
  local work="$1" dest="$2" name sha urls oss bin
  # name<TAB>sha256<TAB>url url url, one line per package
  while IFS=$'\t' read -r name sha urls; do
    # shellcheck disable=SC2086
    fetch "$work/$name" "$sha" $urls || { echo "Could not download $name from any source"; exit 1; }
    tar xzf "$work/$name" -C "$work"
  done < <(python3 - "$MANIFEST" <<'PY'
import json, sys
for p in json.load(open(sys.argv[1]))["packages"]:
    print("\t".join([p["name"], p["sha256"],
                     " ".join(u["url"] for u in p.get("urls", []) if u.get("url"))]))
PY
)
  oss="$(find "$work" -maxdepth 1 -type d -name 'makemkv-oss-*' | head -1)"
  bin="$(find "$work" -maxdepth 1 -type d -name 'makemkv-bin-*' | head -1)"
  local ver="${bin##*/makemkv-bin-}"

  echo "=== makemkv-oss $ver"
  (cd "$oss" && ./configure --disable-gui --prefix=/usr && make -j"$JOBS" \
     && make install DESTDIR="$dest")
  echo "=== makemkv-bin $ver"
  # The bin package's Makefile asks for the licence interactively unless this file
  # exists. MAKEMKV_ACCEPT_EULA=yes is the acceptance; we never get here without it.
  mkdir -p "$bin/tmp" && echo accepted > "$bin/tmp/eula_accepted"
  (cd "$bin" && make install DESTDIR="$dest" PREFIX=/usr)

  # What Riparr reads to show the version and to know the licence was accepted,
  # without running makemkvcon (which has no --version).
  install -d "$dest/usr/local/lib/riparr"
  printf '%s\n' "$ver" > "$dest/usr/local/lib/riparr/makemkv.version"
  printf 'accepted %s via MAKEMKV_ACCEPT_EULA\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "$dest/usr/local/lib/riparr/makemkv.eula"
}

# ── libdvdcss ──

build_libdvdcss() {
  local work="$1" dest="$2"
  fetch "$work/libdvdcss.tar.xz" "$DVDCSS_SHA256" "$DVDCSS_URL" \
    || { echo "Could not download libdvdcss"; exit 1; }
  tar -xJf "$work/libdvdcss.tar.xz" -C "$work"
  cd "$work/libdvdcss-$DVDCSS_VERSION"
  # --libdir=lib puts it in /usr/local/lib, which Debian's ld.so.conf always includes.
  meson setup build --prefix=/usr/local --libdir=lib --buildtype=release
  ninja -C build
  DESTDIR="$dest" ninja -C build install
}

mkdir -p "$TOOLS"
case "${1:-}" in
  makemkv)
    if [ "${MAKEMKV_ACCEPT_EULA:-}" != "yes" ]; then
      say "MakeMKV is not installed: set MAKEMKV_ACCEPT_EULA=yes once you have read"
      say "  https://www.makemkv.com/eula/ -- then restart the container."
      exit 0
    fi
    v="$(makemkv_version)" || { say "can't read $MANIFEST"; exit 1; }
    ensure MakeMKV "$TOOLS/makemkv-$v-$ARCH" build_makemkv
    ;;
  libdvdcss)
    ensure libdvdcss "$TOOLS/libdvdcss-$DVDCSS_VERSION-$ARCH" build_libdvdcss
    ;;
  *)
    echo "usage: $0 makemkv|libdvdcss" >&2
    exit 2
    ;;
esac
