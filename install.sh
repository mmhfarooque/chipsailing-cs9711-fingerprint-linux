#!/bin/bash
# ============================================================================
# Chipsailing CS9711 Fingerprint Scanner — One-Command Installer for Ubuntu
# ============================================================================
# USB ID: 2541:0236
# Tested on: Ubuntu 24.04 LTS, Ubuntu 26.04 LTS
# Upstream: https://github.com/archeYR/libfprint-CS9711
#
# Usage:
#   chmod +x install.sh
#   ./install.sh
#
# What this does:
#   1. Installs all build dependencies
#   2. Clones the community libfprint fork with CS9711 support
#   3. Applies the 1500ms retry delay patch (human-friendly scanning)
#   4. Builds and installs the patched libfprint
#   5. Configures PAM for comfortable retry window (7 tries, 30s)
#   6. Walks you through fingerprint enrollment
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DRIVER_DIR="$SCRIPT_DIR/libfprint-CS9711"
REPO_URL="https://github.com/archeYR/libfprint-CS9711.git"
PATCH_FILE="$SCRIPT_DIR/patches/cs9711-retry-delay-1500ms.patch"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; }

echo ""
echo "============================================"
echo "  Chipsailing CS9711 Fingerprint Installer"
echo "  USB ID: 2541:0236"
echo "============================================"
echo ""

# ---- Pre-flight checks ----
echo "[0/7] Pre-flight checks..."

if [ "$(id -u)" -eq 0 ]; then
    fail "Do not run as root. The script will use sudo when needed."
    exit 1
fi

if lsusb | grep -q "2541:0236"; then
    ok "CS9711 scanner detected on USB"
else
    warn "CS9711 scanner NOT detected on USB"
    echo "       Make sure it's plugged in. If using a keyboard passthrough,"
    echo "       the keyboard must be connected via USB cable (not wireless)."
    read -p "  Continue anyway? [y/N] " -n 1 -r
    echo
    [[ $REPLY =~ ^[Yy]$ ]] || exit 1
fi
echo ""

# ---- Step 1: Dependencies ----
echo "[1/7] Installing build dependencies..."
sudo apt update -qq
sudo apt install -y \
    git meson ninja-build \
    libfprint-2-dev libglib2.0-dev libgusb-dev \
    libpixman-1-dev libcairo2-dev libssl-dev \
    libopencv-dev doctest-dev \
    gobject-introspection libgirepository1.0-dev \
    fprintd libpam-fprintd 2>&1 | tail -5
ok "Dependencies installed"
echo ""

# ---- Step 2: Clone or update source ----
echo "[2/7] Fetching driver source..."
if [ -d "$DRIVER_DIR/.git" ]; then
    cd "$DRIVER_DIR"
    echo "  Existing repo found — pulling latest..."
    git fetch origin
    DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@refs/remotes/origin/@@')
    if [ -z "$DEFAULT_BRANCH" ]; then
        DEFAULT_BRANCH=$(git branch -r | grep 'origin/HEAD' | sed 's@.*-> origin/@@' || echo "cs9711-rebase")
    fi
    git reset --hard "origin/$DEFAULT_BRANCH"
    ok "Updated to latest ($DEFAULT_BRANCH)"
else
    echo "  Cloning from $REPO_URL..."
    git clone "$REPO_URL" "$DRIVER_DIR"
    cd "$DRIVER_DIR"
    ok "Cloned successfully"
fi
echo "  Latest commits:"
git log --oneline -3 | sed 's/^/    /'
echo ""

# ---- Step 3: Apply retry delay patch ----
echo "[3/7] Applying 1500ms retry delay patch..."
CS9711_FILE="$DRIVER_DIR/libfprint/drivers/cs9711/cs9711.c"

if [ ! -f "$CS9711_FILE" ]; then
    fail "cs9711.c not found — driver structure may have changed"
    exit 1
fi

if grep -q "CS9711_DEFAULT_RESET_SLEEP  1500" "$CS9711_FILE"; then
    ok "Patch already applied"
elif grep -q "CS9711_DEFAULT_RESET_SLEEP" "$CS9711_FILE"; then
    sed -i 's/#define CS9711_DEFAULT_RESET_SLEEP.*/#define CS9711_DEFAULT_RESET_SLEEP  1500/' "$CS9711_FILE"
    ok "Patched retry delay: 250ms -> 1500ms"
    echo "       (Prevents scanner from burning through retries before you reposition)"
else
    fail "CS9711_DEFAULT_RESET_SLEEP not found — check driver version"
    exit 1
fi
echo ""

# ---- Step 4: Build ----
echo "[4/7] Building driver (this may take a few minutes)..."
cd "$DRIVER_DIR"
rm -rf builddir
meson setup builddir \
    -Ddrivers=cs9711 \
    -Dudev_rules=disabled \
    -Dudev_hwdb=disabled \
    -Ddoc=false \
    -Dinstalled-tests=false \
    -Dgtk-examples=false 2>&1 | tail -3
meson compile -C builddir 2>&1 | tail -5
ok "Build complete"
echo ""

# ---- Step 5: Install ----
echo "[5/7] Installing driver..."
sudo meson install -C builddir 2>&1 | tail -3
sudo ldconfig
ok "Library installed to /usr/local/lib/x86_64-linux-gnu/"
echo ""

# ---- Step 6: Restart fprintd and verify ----
echo "[6/7] Restarting fingerprint service..."
sudo systemctl restart fprintd
sleep 2

if fprintd-list "$USER" 2>&1 | grep -qi "CS9711\|9711\|chipsailing"; then
    ok "CS9711 scanner detected by fprintd!"
    fprintd-list "$USER" 2>&1 | sed 's/^/    /'
else
    warn "Scanner not yet detected by fprintd"
    echo "       Try: fprintd-list \$(whoami)"
    echo "       If 'No devices available', check USB connection and run: sudo ldconfig"
fi
echo ""

# ---- Step 7: Configure PAM ----
echo "[7/7] Configuring PAM for fingerprint auth..."
PAM_FILE="/etc/pam.d/common-auth"

if grep -q "pam_fprintd.so" "$PAM_FILE"; then
    if grep -q "max-tries=7" "$PAM_FILE"; then
        ok "PAM already configured (max-tries=7 timeout=30)"
    else
        sudo sed -i 's/pam_fprintd.so.*/pam_fprintd.so max-tries=7 timeout=30/' "$PAM_FILE"
        ok "PAM updated: max-tries=7 timeout=30"
    fi
else
    warn "pam_fprintd not found in $PAM_FILE"
    echo "       Fingerprint login may not work. Check libpam-fprintd is installed."
fi
echo ""

# ---- Done ----
echo "============================================"
echo -e "  ${GREEN}Installation complete!${NC}"
echo "============================================"
echo ""
echo "  Next steps:"
echo "    1. Enroll your fingerprint (15 touches required):"
echo "       fprintd-enroll"
echo ""
echo "    2. Test it:"
echo "       fprintd-verify"
echo ""
echo "    3. (Optional) Enroll more fingers:"
echo "       fprintd-enroll -f left-index-finger"
echo ""
echo "  Troubleshooting:"
echo "    - 'No devices': check USB, run 'sudo ldconfig'"
echo "    - 'verify-no-match': delete + re-enroll:"
echo "        fprintd-delete \$(whoami) && fprintd-enroll"
echo "    - After system update breaks it: run this script again"
echo ""
echo "  Optional — auto-unlock GNOME keyring on fingerprint login:"
echo "    python3 helpers/set-empty-keyring-password.py"
echo ""
