#!/bin/bash
# ============================================================================
# Build-test the CS9711 driver INSIDE a distro container (build path only).
# Runs as root in a minimal image — installs deps, copies the mounted fork to
# /tmp/b, applies the same doctest + OpenCV-flexible patches install.sh uses,
# then meson setup + compile. Verifies the cs9711 driver marker is in the .so.
# No PAM / GUI / systemd / fingerprint hardware — those need a real machine.
# Repo is expected mounted read-only at /src.
# ============================================================================
set -e
. /etc/os-release
echo ">>> Distro: $PRETTY_NAME"

case "$ID" in
    ubuntu|debian|linuxmint|pop|elementary|zorin)        FAM=apt ;;
    fedora|rhel|centos|rocky|alma|nobara)                FAM=dnf ;;
    arch|manjaro|endeavouros|garuda|artix)               FAM=pacman ;;
    opensuse*|sles)                                      FAM=zypper ;;
    *) case "$ID_LIKE" in
           *debian*|*ubuntu*) FAM=apt ;;
           *fedora*|*rhel*)   FAM=dnf ;;
           *arch*)            FAM=pacman ;;
           *suse*)            FAM=zypper ;;
           *) echo "!!! Unknown distro family for $ID"; exit 2 ;;
       esac ;;
esac
echo ">>> Package family: $FAM"

echo ">>> Installing build dependencies..."
case "$FAM" in
    apt)
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        apt-get install -y build-essential git meson ninja-build \
            libfprint-2-dev libglib2.0-dev libgusb-dev \
            libpixman-1-dev libcairo2-dev libssl-dev \
            libopencv-dev doctest-dev \
            gobject-introspection libgirepository1.0-dev
        ;;
    dnf)
        dnf install -y gcc gcc-c++ git meson ninja-build \
            libfprint-devel glib2-devel libgusb-devel \
            pixman-devel cairo-devel openssl-devel \
            opencv-devel doctest \
            gobject-introspection gobject-introspection-devel
        ;;
    pacman)
        pacman -Sy --needed --noconfirm base-devel git meson ninja \
            libfprint glib2 glib2-devel libgusb pixman cairo openssl \
            opencv doctest gobject-introspection
        ;;
    zypper)
        zypper -n install gcc gcc-c++ git meson ninja \
            libfprint-devel glib2-devel libgusb-devel \
            libpixman-1-0-devel cairo-devel libopenssl-devel \
            opencv-devel doctest-devel \
            gobject-introspection-devel
        ;;
esac
echo ">>> Dependencies installed"

# Copy the mounted fork so we don't touch the host tree
rm -rf /tmp/b
cp -r /src/libfprint-CS9711 /tmp/b
cd /tmp/b
rm -rf builddir

SIGFM=libfprint/sigfm/meson.build
# doctest optional
sed -i "s/dependency('doctest', required: true)/dependency('doctest', required: false)/" "$SIGFM"
grep -q "if doctest.found()" "$SIGFM" || { sed -i "/^sigfm_tests/i if doctest.found()" "$SIGFM"; echo "endif" >> "$SIGFM"; }
# OpenCV version-flexible (opencv4 -> opencv5)
if grep -q "dependency('opencv4', required: true)" "$SIGFM"; then
    sed -i "s|opencv = dependency('opencv4', required: true)|opencv = dependency('opencv4', required: false)\nif not opencv.found()\n  opencv = dependency('opencv5', required: true)\nendif|" "$SIGFM"
fi
echo ">>> Patches applied (doctest optional + OpenCV flexible)"

echo ">>> meson setup..."
meson setup builddir \
    -Ddrivers=cs9711 \
    -Dudev_rules=disabled \
    -Dudev_hwdb=disabled \
    -Ddoc=false \
    -Dinstalled-tests=false \
    -Dgtk-examples=false

echo ">>> meson compile..."
meson compile -C builddir

# The real shared object — not the .p/ build intermediates or .symbols file
SO=$(find builddir -type f -name 'libfprint-2.so.2.0.0' ! -path '*.p/*' | head -1)
[ -z "$SO" ] && SO=$(find builddir -type f -name 'libfprint-2.so*' ! -path '*.p/*' ! -name '*.symbols' | head -1)
MARK=$(grep -ac "cs9711" "$SO" 2>/dev/null)
[ -z "$MARK" ] && MARK=0
echo ">>> Built: $SO   (cs9711 marker lines: $MARK)"
[ "$MARK" -gt 0 ] || { echo "!!! cs9711 driver NOT in built lib"; exit 3; }
echo ">>> BUILD OK on $PRETTY_NAME"
