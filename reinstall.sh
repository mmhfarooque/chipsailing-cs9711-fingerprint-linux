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
    echo "Driver source not found. Run ./install.sh first for a fresh install."
    exit 1
fi

# Verify patch is still applied
echo "[1/4] Checking 1500ms retry patch..."
if grep -q "CS9711_DEFAULT_RESET_SLEEP  1500" "$DRIVER_DIR/libfprint/drivers/cs9711/cs9711.c"; then
    echo "  Patch OK"
else
    echo "  Re-applying patch..."
    sed -i 's/#define CS9711_DEFAULT_RESET_SLEEP.*/#define CS9711_DEFAULT_RESET_SLEEP  1500/' \
        "$DRIVER_DIR/libfprint/drivers/cs9711/cs9711.c"
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
