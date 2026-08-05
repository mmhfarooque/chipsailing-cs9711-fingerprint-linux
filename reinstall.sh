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

# Keep OpenCV version-resilient on rebuilds too (issue #2): opencv4 ->
# opencv5 -> opencv -> CMake OpenCV. Also upgrades trees still carrying the
# v2.0.x two-step patch.
source "$SCRIPT_DIR/helpers/opencv-flex.sh"
patch_opencv_flex "$SIGFM_MESON"
echo "  OpenCV dependency made version-resilient (opencv4/opencv5/opencv/cmake)"
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

# Same linker-path guarantee as install.sh (issue #2): on Arch/CachyOS
# /usr/local is not searched, so without this the stock libfprint keeps winning
# and a rebuild appears to succeed while changing nothing.
source "$SCRIPT_DIR/helpers/link-path.sh"
INSTALLED_DIR=$(cs9711_install_libdir builddir)
echo "  Installed to $INSTALLED_DIR"
if cs9711_ensure_link_path "$INSTALLED_DIR"; then
    [ -f "$CS9711_LDCONF" ] && echo "  Linker path extended ($CS9711_LDCONF)"
else
    echo ""
    echo "ERROR: the patched libfprint is at $INSTALLED_DIR but the system still"
    echo "       resolves $(cs9711_resolved_lib)"
    echo "       Fingerprint will not work. Please report with:"
    echo "         ldconfig -p | grep libfprint"
    echo "         ls -la $INSTALLED_DIR/libfprint*"
    exit 1
fi

# Refresh the root-owned restore cache used by the update guard, from meson's
# real install dir (NOT ldconfig resolution — that cached the stock lib on Arch)
CACHE_DIR="/var/lib/cs9711-fingerprint"
if [ -e "$INSTALLED_DIR/libfprint-2.so.2" ]; then
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
if [ "$REAL_USER" = "root" ] && [ -n "${PKEXEC_UID:-}" ]; then
    REAL_USER=$(getent passwd "$PKEXEC_UID" | cut -d: -f1)
fi

# Refresh the update guard + package-manager hooks — v2.1.0 taught them to
# catch OpenCV upgrades, and an existing install only reruns install.sh rarely,
# so the rebuild path is where users actually pick this up.
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
source "$SCRIPT_DIR/helpers/install-guard.sh"
install_update_guard_and_hooks "$(detect_pkg_family)" "${REAL_HOME:-$HOME}/.local/share/cs9711-manager/cs9711.log"
sudo rm -f /var/lib/cs9711-fingerprint/BROKEN 2>/dev/null || true
echo "  Update guard + package hooks refreshed"

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
