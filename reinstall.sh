#!/bin/bash
# ============================================================================
# CS9711 Quick Reinstall — Run after system updates overwrite the patched lib
# ============================================================================
# When apt updates libfprint-2-2, it replaces the patched .so with stock.
# This script rebuilds and reinstalls from the existing local source.
#
# Usage: ./reinstall.sh
# ============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DRIVER_DIR="$SCRIPT_DIR/libfprint-CS9711"

echo ""
echo "=== CS9711 Quick Reinstall ==="
echo ""

if [ ! -d "$DRIVER_DIR/libfprint/drivers/cs9711" ]; then
    echo "Error: Driver source not found at $DRIVER_DIR"
    echo ""
    echo "This script is for REBUILDING after system updates — not for initial setup."
    echo "Run ./install.sh first to do a fresh installation."
    exit 1
fi

# Verify source file exists
CS9711_SRC="$DRIVER_DIR/libfprint/drivers/cs9711/cs9711.c"
if [ ! -f "$CS9711_SRC" ]; then
    echo "Error: cs9711.c not found at $CS9711_SRC"
    echo "The driver source structure may have changed. Run ./install.sh for a fresh install."
    exit 1
fi

# Verify retry delay patch is applied (preserve custom values from GUI)
echo "[1/4] Checking patches..."
CURRENT_DELAY=$(grep -oP 'CS9711_DEFAULT_RESET_SLEEP\s+\K\d+' "$CS9711_SRC" 2>/dev/null || echo "")
if [ -n "$CURRENT_DELAY" ] && [ "$CURRENT_DELAY" -ge 500 ]; then
    echo "  Retry delay: ${CURRENT_DELAY}ms (preserved)"
else
    echo "  Re-applying retry delay patch (1500ms default)..."
    sed -i 's/#define CS9711_DEFAULT_RESET_SLEEP.*/#define CS9711_DEFAULT_RESET_SLEEP  1500/' "$CS9711_SRC"
fi

# Make doctest optional
SIGFM_MESON="$DRIVER_DIR/libfprint/sigfm/meson.build"
if [ -f "$SIGFM_MESON" ] && grep -q "required: true" "$SIGFM_MESON"; then
    sed -i "s/dependency('doctest', required: true)/dependency('doctest', required: false)/" "$SIGFM_MESON"
    if ! grep -q "if doctest.found()" "$SIGFM_MESON"; then
        sed -i '/^sigfm_tests/i if doctest.found()' "$SIGFM_MESON"
        echo "endif" >> "$SIGFM_MESON"
    fi
    echo "  Made doctest optional"
fi

# Keep OpenCV version-flexible (opencv4 -> opencv5 fallback) on rebuilds too
if [ -f "$SIGFM_MESON" ] && grep -q "dependency('opencv4', required: true)" "$SIGFM_MESON"; then
    sed -i "s|opencv = dependency('opencv4', required: true)|opencv = dependency('opencv4', required: false)\nif not opencv.found()\n  opencv = dependency('opencv5', required: true)\nendif|" "$SIGFM_MESON"
    echo "  OpenCV dependency made version-flexible (opencv4 -> opencv5 fallback)"
fi
echo ""

# Build
echo "[2/4] Building..."
cd "$DRIVER_DIR"
rm -rf builddir
meson setup builddir \
    -Ddrivers=cs9711 \
    -Dudev_rules=disabled \
    -Dudev_hwdb=disabled \
    -Ddoc=false \
    -Dinstalled-tests=false \
    -Dgtk-examples=false 2>&1 | tail -3
meson compile -C builddir 2>&1 | tail -3
echo ""

# Install
echo "[3/4] Installing..."
sudo meson install -C builddir 2>&1 | tail -3
sudo ldconfig

# Refresh the root-owned restore cache used by the update guard
CACHE_DIR="/var/lib/cs9711-fingerprint"
INSTALLED_SO=$(ldconfig -p 2>/dev/null | awk '/libfprint-2\.so\.2 /{print $NF; exit}')
if [ -n "$INSTALLED_SO" ] && [ -e "$INSTALLED_SO" ]; then
    INSTALLED_DIR=$(dirname "$INSTALLED_SO")
    sudo mkdir -p "$CACHE_DIR"
    sudo cp -a "$INSTALLED_DIR"/libfprint-2.so* "$CACHE_DIR"/ 2>/dev/null || true
    echo "$INSTALLED_DIR" | sudo tee "$CACHE_DIR/install-dir" >/dev/null
    TYPELIB=$(find /usr/local -name 'FPrint-2.0.typelib' 2>/dev/null | head -1)
    if [ -n "$TYPELIB" ]; then
        sudo cp -a "$TYPELIB" "$CACHE_DIR"/ 2>/dev/null || true
        dirname "$TYPELIB" | sudo tee "$CACHE_DIR/typelib-dir" >/dev/null
    fi
    echo "  Restore cache refreshed"
fi
echo ""

# Restart and verify
echo "[4/4] Restarting fprintd..."
sudo systemctl restart fprintd
sleep 2

# Use SUDO_USER or PKEXEC_UID to find the real user when running via pkexec/sudo
REAL_USER="${SUDO_USER:-${USER}}"
if [ "$REAL_USER" = "root" ] && [ -n "$PKEXEC_UID" ]; then
    REAL_USER=$(getent passwd "$PKEXEC_UID" | cut -d: -f1)
fi

if fprintd-list "$REAL_USER" 2>&1 | grep -qi "CS9711\|9711\|chipsailing"; then
    echo ""
    echo "SUCCESS: CS9711 scanner working!"
    fprintd-list "$REAL_USER" 2>&1 | sed 's/^/  /'
else
    echo ""
    echo "Scanner not detected. Try: lsusb | grep 2541"
fi

echo ""
echo "If fingerprints don't match, re-enroll:"
echo "  fprintd-delete \$(whoami) && fprintd-enroll"
