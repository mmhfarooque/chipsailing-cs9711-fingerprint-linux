#!/bin/bash
# ============================================================================
# Chipsailing CS9711 Fingerprint Scanner — Universal Linux Installer
# ============================================================================
# USB ID: 2541:0236
# Supported: Ubuntu, Debian, Linux Mint, Pop!_OS, Fedora, RHEL, CentOS,
#            Arch, Manjaro, openSUSE, and other systemd-based distros
# Upstream driver: https://github.com/archeYR/libfprint-CS9711
#
# Usage:
#   chmod +x install.sh
#   ./install.sh
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DRIVER_DIR="$SCRIPT_DIR/libfprint-CS9711"
REPO_URL="https://github.com/archeYR/libfprint-CS9711.git"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; }
info() { echo -e "  ${BLUE}[>>]${NC} $1"; }

# ============================================================================
# Detect distro family
# ============================================================================
detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO_ID="$ID"
        DISTRO_ID_LIKE="$ID_LIKE"
        DISTRO_NAME="$PRETTY_NAME"
    else
        fail "Cannot detect distro (/etc/os-release missing)"
        exit 1
    fi

    # Determine package manager family
    case "$DISTRO_ID" in
        ubuntu|debian|linuxmint|pop|elementary|zorin|kali|raspbian)
            PKG_FAMILY="apt"
            ;;
        fedora|rhel|centos|rocky|alma|nobara)
            PKG_FAMILY="dnf"
            ;;
        arch|manjaro|endeavouros|garuda|artix)
            PKG_FAMILY="pacman"
            ;;
        opensuse*|sles)
            PKG_FAMILY="zypper"
            ;;
        *)
            # Check ID_LIKE for derivatives
            case "$DISTRO_ID_LIKE" in
                *debian*|*ubuntu*)  PKG_FAMILY="apt" ;;
                *fedora*|*rhel*)    PKG_FAMILY="dnf" ;;
                *arch*)             PKG_FAMILY="pacman" ;;
                *suse*)             PKG_FAMILY="zypper" ;;
                *)
                    fail "Unsupported distro: $DISTRO_NAME ($DISTRO_ID)"
                    echo "       Supported: Debian/Ubuntu, Fedora/RHEL, Arch, openSUSE families"
                    echo "       You can install dependencies manually — see README.md"
                    exit 1
                    ;;
            esac
            ;;
    esac
}

# ============================================================================
# Install dependencies per distro
# ============================================================================
install_deps_apt() {
    sudo apt update -qq
    sudo apt install -y \
        git meson ninja-build \
        libfprint-2-dev libglib2.0-dev libgusb-dev \
        libpixman-1-dev libcairo2-dev libssl-dev \
        libopencv-dev doctest-dev \
        gobject-introspection libgirepository1.0-dev \
        fprintd libpam-fprintd 2>&1 | tail -5
}

install_deps_dnf() {
    sudo dnf install -y \
        git meson ninja-build \
        libfprint-devel glib2-devel libgusb-devel \
        pixman-devel cairo-devel openssl-devel \
        opencv-devel doctest \
        gobject-introspection gobject-introspection-devel \
        fprintd fprintd-pam 2>&1 | tail -5
}

install_deps_pacman() {
    sudo pacman -S --needed --noconfirm \
        base-devel git meson ninja \
        libfprint glib2 libgusb \
        pixman cairo openssl \
        opencv doctest \
        gobject-introspection \
        fprintd 2>&1 | tail -5
}

install_deps_zypper() {
    sudo zypper install -y \
        git meson ninja \
        libfprint-devel glib2-devel libgusb-devel \
        pixman-devel cairo-devel libopenssl-devel \
        opencv-devel doctest-devel \
        gobject-introspection-devel \
        fprintd fprintd-pam 2>&1 | tail -5
}

# ============================================================================
# Determine library install path
# ============================================================================
get_lib_path() {
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  LIB_ARCH="x86_64-linux-gnu" ;;
        aarch64) LIB_ARCH="aarch64-linux-gnu" ;;
        armv7l)  LIB_ARCH="arm-linux-gnueabihf" ;;
        *)       LIB_ARCH="$ARCH-linux-gnu" ;;
    esac

    # Some distros use /usr/local/lib64/ instead
    if [ -d "/usr/local/lib64" ] && [ "$PKG_FAMILY" != "apt" ]; then
        LIB_INSTALL_DIR="/usr/local/lib64"
    else
        LIB_INSTALL_DIR="/usr/local/lib/$LIB_ARCH"
    fi
}

# ============================================================================
# Configure PAM (distro-aware)
# ============================================================================
configure_pam() {
    # Debian/Ubuntu use common-auth, Fedora/Arch use system-auth or fingerprint-auth
    PAM_FILES=(
        "/etc/pam.d/common-auth"
        "/etc/pam.d/system-auth"
        "/etc/pam.d/fingerprint-auth"
    )

    PAM_CONFIGURED=false
    for PAM_FILE in "${PAM_FILES[@]}"; do
        if [ -f "$PAM_FILE" ] && grep -q "pam_fprintd.so" "$PAM_FILE"; then
            if grep -q "max-tries=7" "$PAM_FILE"; then
                ok "PAM already configured in $PAM_FILE (max-tries=7 timeout=30)"
            else
                sudo sed -i 's/pam_fprintd.so.*/pam_fprintd.so max-tries=7 timeout=30/' "$PAM_FILE"
                ok "PAM updated in $PAM_FILE: max-tries=7 timeout=30"
            fi
            PAM_CONFIGURED=true
            break
        fi
    done

    if [ "$PAM_CONFIGURED" = false ]; then
        # Check if authselect is used (Fedora/RHEL)
        if command -v authselect &>/dev/null; then
            if authselect current 2>/dev/null | grep -q "with-fingerprint"; then
                ok "Fingerprint auth enabled via authselect"
            else
                info "Enabling fingerprint auth via authselect..."
                sudo authselect enable-feature with-fingerprint 2>/dev/null || \
                    warn "authselect fingerprint enable failed — configure manually"
            fi
        else
            warn "pam_fprintd not found in PAM config"
            echo "       You may need to configure PAM manually for your distro."
        fi
    fi
}

# ============================================================================
# Main installer
# ============================================================================

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

detect_distro
ok "Detected: $DISTRO_NAME (package manager: $PKG_FAMILY)"

get_lib_path
ok "Architecture: $(uname -m)"

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
echo "[1/7] Installing build dependencies via $PKG_FAMILY..."
if ! declare -f "install_deps_$PKG_FAMILY" &>/dev/null; then
    fail "No installer defined for package manager: $PKG_FAMILY"
    exit 1
fi
install_deps_$PKG_FAMILY
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

# Make doctest optional (only needed for tests, not the driver itself)
SIGFM_MESON="$DRIVER_DIR/libfprint/sigfm/meson.build"
if [ -f "$SIGFM_MESON" ] && grep -q "required: true" "$SIGFM_MESON"; then
    sed -i "s/dependency('doctest', required: true)/dependency('doctest', required: false)/" "$SIGFM_MESON"
    # Wrap test executable in if-block if not already
    if ! grep -q "if doctest.found()" "$SIGFM_MESON"; then
        sed -i '/^sigfm_tests/i if doctest.found()' "$SIGFM_MESON"
        echo "endif" >> "$SIGFM_MESON"
    fi
    ok "Made doctest optional (not needed for driver)"
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
ok "Library installed"
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
configure_pam
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
echo "    4. (Optional) Install the graphical manager:"
echo "       ./setup-gui.sh"
echo "       Then search 'CS9711' in your app launcher."
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
