#!/bin/bash
# ============================================================================
# CS9711 Quick Reinstall — Run after system updates overwrite the patched lib
# ============================================================================
# When apt updates libfprint-2-2, it replaces the patched .so with stock.
# This script rebuilds and reinstalls from the existing local source.
#
# Usage: ./reinstall.sh
# ============================================================================

set -e

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

# Verify patch is still applied
echo "[1/4] Checking patches..."
if grep -q "CS9711_DEFAULT_RESET_SLEEP  1500" "$CS9711_SRC"; then
    echo "  Retry delay patch OK"
else
    echo "  Re-applying retry delay patch..."
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
echo ""

# Restart and verify
echo "[4/4] Restarting fprintd..."
sudo systemctl restart fprintd
sleep 2

if fprintd-list "$USER" 2>&1 | grep -qi "CS9711\|9711\|chipsailing"; then
    echo ""
    echo "SUCCESS: CS9711 scanner working!"
    fprintd-list "$USER" 2>&1 | sed 's/^/  /'
else
    echo ""
    echo "Scanner not detected. Try: lsusb | grep 2541"
fi

echo ""
echo "If fingerprints don't match, re-enroll:"
echo "  fprintd-delete \$(whoami) && fprintd-enroll"
