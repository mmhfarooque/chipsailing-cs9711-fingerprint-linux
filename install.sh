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

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DRIVER_DIR="$SCRIPT_DIR/libfprint-CS9711"
REPO_URL="https://github.com/archeYR/libfprint-CS9711.git"

# Logging — same log file as the GUI
LOG_DIR="$HOME/.local/share/cs9711-manager"
LOG_FILE="$LOG_DIR/cs9711.log"
mkdir -p "$LOG_DIR"
logmsg() { echo "$(date '+%Y-%m-%d %H:%M:%S') [INSTALL] $1" >> "$LOG_FILE"; }

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; logmsg "OK: $1"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $1"; logmsg "WARN: $1"; }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; logmsg "FAIL: $1"; }
info() { echo -e "  ${BLUE}[>>]${NC} $1"; logmsg "INFO: $1"; }

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
        build-essential git meson ninja-build \
        libfprint-2-dev libglib2.0-dev libgusb-dev \
        libpixman-1-dev libcairo2-dev libssl-dev \
        libopencv-dev doctest-dev \
        gobject-introspection libgirepository1.0-dev \
        fprintd libpam-fprintd 2>&1 | tail -5
}

install_deps_dnf() {
    sudo dnf install -y \
        gcc gcc-c++ git meson ninja-build \
        libfprint-devel glib2-devel libgusb-devel \
        pixman-devel cairo-devel openssl-devel \
        opencv-devel doctest \
        gobject-introspection gobject-introspection-devel \
        fprintd fprintd-pam 2>&1 | tail -5
}

install_deps_pacman() {
    sudo pacman -S --needed --noconfirm \
        base-devel git meson ninja \
        libfprint glib2 glib2-devel libgusb \
        pixman cairo openssl \
        opencv doctest \
        gobject-introspection \
        fprintd 2>&1 | tail -5
}

install_deps_zypper() {
    sudo zypper install -y \
        gcc gcc-c++ git meson ninja \
        libfprint-devel glib2-devel libgusb-devel \
        libpixman-1-0-devel cairo-devel libopenssl-devel \
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
    # Per-service fingerprint setup — matches the GUI's independent per-location
    # switches. Enables fprintd in each service's OWN PAM file (login / display
    # manager, lock screen, sudo, polkit) rather than the shared common stack, so
    # each location can be toggled independently afterwards.
    #
    # Cross-distro & reversible:
    #   * vendor file in /usr/lib/pam.d (openSUSE/Fedora) -> /etc/pam.d override
    #   * file already in /etc/pam.d (Debian/Ubuntu)       -> edited in place
    #   * a service whose vendor file already ships fprintd (kde-fingerprint /
    #     gdm-fingerprint) is left to the vendor — it's already on.
    # The full stack incl. the password path is always preserved, and fprintd is
    # only ever 'sufficient', so password authentication can never break.
    info "Configuring fingerprint per-service (login, lock screen, sudo, polkit)..."

    local tmp; tmp="$(mktemp)"
    cat > "$tmp" <<'PAMEOF'
#!/usr/bin/env bash
set -u
ETC=/etc/pam.d; VENDOR=/usr/lib/pam.d; MARK="# cs9711-managed"
INS="auth\tsufficient\tpam_fprintd.so\tmax-tries=7 timeout=30\t$MARK"
# Native = a distro-shipped fprintd line (not one of ours — those carry MARK),
# reachable from the service's own stack INCLUDING include/substack targets.
# Two measurements on Fedora 44 forced this (2026-08-08):
#   * kde-fingerprint lives in /etc/pam.d, not /usr/lib/pam.d — so both dirs count.
#   * fingerprint support arrives through includes, never a direct line:
#     gdm-fingerprint -> fingerprint-auth, and sudo/polkit-1 -> system-auth
#     (authselect's with-fingerprint feature, on by default on Fedora KDE).
# A flat grep sees none of that, calls the location unconfigured, and injects
# duplicates — or, far worse, injects into gdm-password (see enable_loc below).
has_vendor_fp(){ _hvf "$1" 0; }
_hvf(){ local s="$1" depth="$2" f t
  [ "$depth" -ge 3 ] && return 1
  for f in "$ETC/$s" "$VENDOR/$s"; do
    [ -f "$f" ] || continue
    grep -E '^[^#]*pam_fprintd\.so' "$f" 2>/dev/null | grep -qv "$MARK" && return 0
    for t in $(awk '$1=="auth" && ($2=="include"||$2=="substack"){print $3}' "$f"); do
      _hvf "$t" $((depth+1)) && return 0
    done
  done
  return 1; }
ensure_copy(){ [ -f "$ETC/$1" ] || { [ -f "$VENDOR/$1" ] && cp -a "$VENDOR/$1" "$ETC/$1"; }; }
# Insertion point matters for safety, not just for tidiness. Our line is
# 'sufficient', so anything ABOVE it still runs and anything below is skipped
# on a successful touch. It must therefore land AFTER the stack's required /
# requisite pre-checks (pam_securetty, pam_nologin) and immediately BEFORE the
# include of the common stack that does the password work.
# The old code anchored on the literal string common-auth and otherwise fell
# back to line 1 — which on Arch put fingerprint ahead of pam_nologin, letting
# a touch bypass a login lockout (measured on /etc/pam.d/greetd, 2026-08-08).
# Anchors handled: auth include/substack <common stack> (openSUSE, Fedora,
# Arch) and Debian/Ubuntu's @include common-auth.
add_fp(){ ensure_copy "$1"; [ -f "$ETC/$1" ] || return 0; grep -q "$MARK" "$ETC/$1" && return 0
  awk -v ins="$INS" '
    { lines[NR]=$0
      if (!anchor && (($1=="@include" && $2 ~ /auth/) ||
                      ($1=="auth" && ($2=="include" || $2=="substack")))) anchor=NR
      if ($1=="auth" && ($2=="required" || $2=="requisite")) lastreq=NR }
    END{ if (anchor) pos=anchor-1; else if (lastreq) pos=lastreq;
         else pos=(lines[1] ~ /^#/) ? 1 : 0
         for (i=1;i<=NR;i++) { if (i==pos+1) print ins; print lines[i] }
         if (pos>=NR) print ins }' "$ETC/$1" > "$ETC/$1.tmp" || return 0
  mv "$ETC/$1.tmp" "$ETC/$1"; chmod 644 "$ETC/$1"; }
# Enable a location: if a native fingerprint service exists (vendor ships fprintd,
# e.g. kde-fingerprint/gdm-fingerprint) it's already on; otherwise add our line to
# every existing generic service file for that location.
enable_loc(){ local native='' s; for s in "$@"; do has_vendor_fp "$s" && native=x; done
  [ -n "$native" ] && return 0
  for s in "$@"; do [ -f "$ETC/$s" ] || [ -f "$VENDOR/$s" ] || continue; add_fp "$s"; done; }
# plasmalogin (Plasma 6.7+ replaced sddm; seen on Fedora 44 KDE) has no
# common-auth anchor and starts with pam_selinux_permit, which must stay
# first. Insertion recipe verified by @popy2k14 on Fedora 44 (#1): typed
# password authenticates instantly via pam_unix, empty/failed password
# falls through to fingerprint — plasmalogin has no parallel prompt yet.
add_fp_plasmalogin(){ ensure_copy plasmalogin; local f="$ETC/plasmalogin"
  [ -f "$f" ] || return 0; grep -q "$MARK" "$f" && return 0
  has_vendor_fp plasmalogin && return 0
  awk -v m="$MARK" '{print}
    !d && /^[^#]*pam_selinux_permit\.so/ {
      print "auth\tsufficient\tpam_unix.so\ttry_first_pass likeauth nullok\t" m
      print "auth\tsufficient\tpam_fprintd.so\tmax-tries=5 timeout=10\t" m
      d=1 }
    END{if(!d) exit 3}' "$f" > "$f.tmp" || { rm -f "$f.tmp"; return 0; }
  mv "$f.tmp" "$f"; chmod 644 "$f"; }
add_fp_plasmalogin
# gdm-password is deliberately NOT in either list. It carries the keyring
# capture (pam_gnome_keyring auth), and a 'sufficient' fprintd line ahead of
# that short-circuits the stack on a successful touch, so the keyring never
# gets the password and every saved credential looks lost — the GNOME twin of
# the KWallet/pam_kwallet5 breakage this project hit on openSUSE. GNOME's own
# fingerprint path is gdm-fingerprint, for both the login screen and the
# unlock dialog, so nothing is lost by leaving gdm-password alone.
# greetd is the login stack for COSMIC (cosmic-greeter), and for tuigreet /
# regreet on minimal Wayland setups — none of which existed in this list, so
# fingerprint login was silently never configured on any of them. Measured on
# Arch + COSMIC 1.5.0, 2026-08-08: /etc/pam.d/greetd includes
# system-local-login, carries no fingerprint of its own, and ships no
# cosmic-greeter service file at all.
enable_loc sddm gdm-fingerprint lightdm lxdm greetd
enable_loc kde-fingerprint kscreenlocker kscreenlocker_greet kde gdm-fingerprint cinnamon-screensaver mate-screensaver xfce4-screensaver light-locker
enable_loc sudo sudo-i
enable_loc polkit-1 polkit-1-kde-1
# Per-service files are authoritative: drop any global fprintd from the common stack.
for cf in common-auth common-auth-pc; do
  [ -f "$ETC/$cf" ] && grep -q pam_fprintd "$ETC/$cf" && sed -i '/pam_fprintd/d' "$ETC/$cf"
done
# The loop above legitimately ends nonzero on distros without common-auth
# (Fedora/Arch) — that must not become this script's exit status.
exit 0
PAMEOF

    # set -e-safe capture: a bare `sudo bash; rc=$?` dies before the capture
    local rc=0; sudo bash "$tmp" || rc=$?
    rm -f "$tmp"
    if [ "$rc" -eq 0 ]; then
        ok "Fingerprint enabled per-service — toggle any location in the GUI ('Where to Use Fingerprint')"
    else
        warn "Per-service PAM setup hit an issue — configure via the GUI; password login is unaffected"
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
logmsg "=== INSTALL STARTING === ($(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo 'unknown'))"
logmsg "User: $(whoami) | Distro: $(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"')"

# ---- Pre-flight checks ----
echo "[0/8] Pre-flight checks..."

if [ "$(id -u)" -eq 0 ]; then
    fail "Do not run as root. The script will use sudo when needed."
    exit 1
fi

detect_distro
ok "Detected: $DISTRO_NAME (package manager: $PKG_FAMILY)"

get_lib_path
ok "Architecture: $(uname -m)"

# Scanner detection reads sysfs, NOT lsusb. Arch (and other minimal installs)
# do not ship usbutils, so `lsusb` is simply absent — and because this check
# runs BEFORE dependencies are installed, it could never fix itself: the
# scanner was plugged in, sysfs listed it, and the installer aborted saying it
# was not there. Measured on a stock Arch VM, 2026-08-08. sysfs is always
# present on Linux; lsusb stays only as a fallback.
cs9711_on_usb() {
    local f
    for f in /sys/bus/usb/devices/*/idVendor; do
        [ -r "$f" ] || continue
        [ "$(cat "$f" 2>/dev/null)" = "2541" ] || continue
        [ "$(cat "${f%idVendor}idProduct" 2>/dev/null)" = "0236" ] && return 0
    done
    command -v lsusb >/dev/null 2>&1 && lsusb 2>/dev/null | grep -q "2541:0236"
}
if cs9711_on_usb; then
    ok "CS9711 scanner detected on USB"
else
    warn "CS9711 scanner NOT detected on USB"
    echo "       Make sure it's plugged in. If using a keyboard passthrough,"
    echo "       the keyboard must be connected via USB cable (not wireless)."
    echo "       IMPORTANT: this installs a CS9711-only libfprint into /usr/local"
    echo "       that SHADOWS your system libfprint. If this machine has a"
    echo "       DIFFERENT built-in fingerprint reader, THAT reader will stop"
    echo "       working. Only continue if you actually have the CS9711 (2541:0236)."
    if [ "${CS9711_FORCE:-0}" = "1" ]; then
        warn "CS9711_FORCE=1 set — continuing without a detected scanner"
    elif [ -t 0 ]; then
        read -p "  Continue anyway? [y/N] " -n 1 -r
        echo
        [[ $REPLY =~ ^[Yy]$ ]] || exit 1
    else
        # Non-interactive (e.g. launched from the GUI) — DON'T blindly build a
        # driver that shadows the system one. Require the device or an override.
        fail "Scanner not detected and not running interactively — aborting."
        echo "       Plug in the CS9711, or re-run with CS9711_FORCE=1 to override."
        exit 1
    fi
fi
echo ""

# ---- Step 1: Dependencies ----
echo "[1/8] Installing build dependencies via $PKG_FAMILY..."
if ! declare -f "install_deps_$PKG_FAMILY" &>/dev/null; then
    fail "No installer defined for package manager: $PKG_FAMILY"
    exit 1
fi
install_deps_$PKG_FAMILY
ok "Dependencies installed"
echo ""

# ---- Step 2: Clone or update source ----
echo "[2/8] Fetching driver source..."
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
echo "[3/8] Applying 1500ms retry delay patch..."
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

# Make OpenCV version-resilient (issue #2): opencv4 -> opencv5 -> opencv
# pkg-config names, then CMake's OpenCV — survives a distro OpenCV major bump.
source "$SCRIPT_DIR/helpers/opencv-flex.sh"
patch_opencv_flex "$SIGFM_MESON"
ok "OpenCV dependency made version-resilient (opencv4/opencv5/opencv/cmake)"
echo ""

# ---- Step 4: Build ----
echo "[4/8] Building driver (this may take a few minutes)..."
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
echo "[5/8] Installing driver..."
sudo meson install -C builddir 2>&1 | tail -3
sudo ldconfig
ok "Library installed"

# Make sure the install ACTUALLY takes effect. meson installs under /usr/local,
# which only shadows the distro's libfprint where /usr/local is in the linker
# path — true on openSUSE/Fedora/Debian, NOT on Arch/CachyOS (issue #2). Without
# this the stock library keeps winning and fprintd reports no devices while
# lsusb still shows the scanner.
source "$SCRIPT_DIR/helpers/link-path.sh"
INSTALLED_DIR=$(cs9711_install_libdir builddir)
info "Installed to $INSTALLED_DIR"
if cs9711_ensure_link_path "$INSTALLED_DIR"; then
    if [ -f "$CS9711_LDCONF" ]; then
        ok "Linker path extended ($CS9711_LDCONF) — patched driver now takes precedence"
    else
        ok "Patched driver already takes precedence"
    fi
else
    fail "The patched libfprint is installed at $INSTALLED_DIR but the system"
    echo "       still resolves a different one:"
    echo "         $(cs9711_resolved_lib)"
    echo "       Fingerprint will NOT work in this state. Please report this with:"
    echo "         ldconfig -p | grep libfprint"
    echo "         ls -la $INSTALLED_DIR/libfprint*"
    echo "       https://github.com/mmhfarooque/chipsailing-cs9711-fingerprint-linux/issues"
    exit 1
fi

# Snapshot the installed driver into a ROOT-OWNED cache. The update-guard
# restores from here after a system upgrade with a plain file copy — so it
# never executes build files from a user-writable directory as root, and can't
# fail to compile.
#
# The source is meson's REAL install dir, not whatever ldconfig resolves: on
# Arch the old code resolved the stock library and cached that by mistake,
# leaving the guard silently useless.
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
    ok "Driver cached for safe restore ($CACHE_DIR)"
fi
echo ""

# ---- Step 6: Restart fprintd and verify ----
echo "[6/8] Restarting fingerprint service..."
sudo systemctl restart fprintd
sleep 2

# Resolve real user (may be running under sudo/pkexec)
REAL_USER="${SUDO_USER:-${USER}}"
if [ "$REAL_USER" = "root" ] && [ -n "$PKEXEC_UID" ]; then
    REAL_USER=$(getent passwd "$PKEXEC_UID" | cut -d: -f1)
fi

# fprintd queries go through polkit, which denies sessions that are not local
# and active — running this over ssh gets "Not Authorized", and a DENIED query
# looks exactly like NO DEVICE to a naive grep. Measured on Fedora 44: the
# unprivileged query printed only object paths (no device name) while the
# daemon logged the denial naming the CS9711. So: query as the user first,
# then retry via sudo (root is implicitly authorised) before concluding the
# device is absent. Same lesson as the ldconfig bug — never let a check's own
# failure mode impersonate the failure it checks for.
# The || true guards matter: this script runs under set -e, and fprintd-list
# exits nonzero on the very authorization denial we are probing for — a bare
# assignment would kill the whole script mid-step with no message at all.
FPL_OUT=$(fprintd-list "$REAL_USER" 2>&1) || true
if ! printf '%s' "$FPL_OUT" | grep -qi "CS9711\|9711\|chipsailing"; then
    FPL_OUT=$(sudo fprintd-list "$REAL_USER" 2>&1) || true
fi
if printf '%s' "$FPL_OUT" | grep -qi "CS9711\|9711\|chipsailing"; then
    ok "CS9711 scanner detected by fprintd!"
    printf '%s\n' "$FPL_OUT" | sed 's/^/    /'

    # Detect existing enrollment — likely stale if it pre-dates this build of
    # the patched driver, since template timing/format can differ. We don't
    # auto-delete (could destroy a working enrollment), but we tell the user.
    if printf '%s\n' "$FPL_OUT" | grep -qE '^\s*-\s*#[0-9]+:'; then
        warn "Existing enrolled fingerprint(s) detected"
        echo "       If this driver was just freshly built (or you previously"
        echo "       used an older driver), the old template will likely fail"
        echo "       'verify-no-match'. Re-enroll for a clean template:"
        echo "         fprintd-delete \$(whoami) && fprintd-enroll"
    fi
else
    # HARD failure, not a warning. The linker-path check above already proved
    # our driver is the one being resolved, so if fprintd still cannot see the
    # scanner the install has objectively not worked — and reporting that as a
    # warning is how issue #2's second half stayed hidden through a run that
    # "completed with no errors".
    fail "Driver is active but fprintd still reports no CS9711 device"
    echo "       Resolved library: $(cs9711_resolved_lib)"
    echo "       Diagnostics to include in a bug report:"
    echo "         lsusb | grep 2541:0236"
    echo "         ldconfig -p | grep libfprint"
    echo "         ldd \$(ldconfig -p | awk '/libfprint-2\\.so\\.2 /{print \$NF; exit}')"
    echo "         fprintd-list \$(whoami)"
    echo "         tail -40 $LOG_FILE"
    echo "       https://github.com/mmhfarooque/chipsailing-cs9711-fingerprint-linux/issues"
    exit 1
fi
echo ""

# ---- Step 7: Configure PAM ----
echo "[7/8] Configuring PAM for fingerprint auth..."
configure_pam
echo ""

# ---- Step 7b: Install update guard (survives system upgrades) ----
# Fixes the most-reported community complaint: "a system update overwrote
# libfprint and broke fingerprint." A package-manager hook runs after every
# transaction; if our patched driver is no longer the active one, it rebuilds.
echo "[7b/8] Installing update guard (re-applies driver after system updates)..."
# Guard + hooks live in helpers/ (shared with reinstall.sh). Since v2.1.0 the
# guard also detects a driver stranded by an OpenCV major upgrade (issue #2)
# and the pacman/dnf hooks fire on opencv transactions too.
source "$SCRIPT_DIR/helpers/install-guard.sh"
install_update_guard_and_hooks "$PKG_FAMILY" "$LOG_FILE"
sudo rm -f /var/lib/cs9711-fingerprint/BROKEN 2>/dev/null || true
ok "Update guard installed at /usr/local/bin/cs9711-update-guard"
case "$PKG_FAMILY" in
    apt)    ok "APT hook installed — driver survives 'apt upgrade'" ;;
    dnf)    ok "dnf hook installed — fires on libfprint AND opencv updates" ;;
    pacman) ok "pacman hook installed — fires on libfprint AND opencv updates" ;;
    zypper) warn "openSUSE: no auto-hook wired — run ./reinstall.sh after a libfprint/OpenCV update" ;;
esac
echo ""

# ---- Step 8: Install GUI Manager ----
echo "[8/8] Installing GUI Manager..."

# Install GTK4 Python deps
if [ "$PKG_FAMILY" = "apt" ]; then
    sudo apt install -y python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 2>&1 | tail -2
elif [ "$PKG_FAMILY" = "dnf" ]; then
    sudo dnf install -y python3-gobject gtk4 libadwaita 2>&1 | tail -2
elif [ "$PKG_FAMILY" = "pacman" ]; then
    sudo pacman -S --needed --noconfirm python-gobject gtk4 libadwaita 2>&1 | tail -2
elif [ "$PKG_FAMILY" = "zypper" ]; then
    sudo zypper install -y python3-gobject typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 2>&1 | tail -2
fi

# Make GUI executable
chmod +x "$SCRIPT_DIR/cs9711-manager.py" 2>/dev/null || true

# Create desktop shortcut
DESKTOP_FILE="$HOME/.local/share/applications/cs9711-manager.desktop"
mkdir -p "$HOME/.local/share/applications"
echo "[Desktop Entry]
Type=Application
Name=CS9711 Fingerprint Manager
Comment=Configure Chipsailing CS9711 fingerprint scanner
Exec=python3 $SCRIPT_DIR/cs9711-manager.py
Icon=$SCRIPT_DIR/assets/cs9711-manager.svg
Terminal=false
Categories=Settings;HardwareSettings;System;
Keywords=fingerprint;scanner;cs9711;biometric;chipsailing;" > "$DESKTOP_FILE"

ok "GUI Manager installed — search 'CS9711' or 'Fingerprint' in app launcher"
logmsg "=== INSTALL COMPLETE ==="
echo ""

# ---- Done ----
echo "============================================"
echo -e "  ${GREEN}Installation complete!${NC}"
echo "============================================"
echo ""
echo "  CS9711 Fingerprint Manager has been added to your App Launcher."
echo "  Search 'CS9711' or 'Fingerprint Manager' to open it anytime."
echo ""
echo "  Quick start:"
echo "    1. fprintd-enroll          (15 touches to register your finger)"
echo "    2. fprintd-verify          (test it works)"
echo "    3. Super+Space on lock screen to use fingerprint login"
echo ""
echo "  Or do everything from the GUI — launching now..."
echo ""
echo "  Uninstall: ./uninstall.sh"
echo ""

# Auto-launch the GUI Manager
if [ -f "$SCRIPT_DIR/cs9711-manager.py" ]; then
    nohup python3 "$SCRIPT_DIR/cs9711-manager.py" >/dev/null 2>&1 &
    disown
fi

# Only close the terminal if we're running interactively in a terminal emulator.
# This prevents killing the wrong parent when launched from GUI, scripts, or IDEs.
if [ -t 0 ] && [ -n "$PPID" ]; then
    PARENT_NAME=$(ps -o comm= -p "$PPID" 2>/dev/null || echo "")
    case "$PARENT_NAME" in
        bash|zsh|sh|dash|fish)
            # Parent is a shell inside a terminal — safe to close
            echo "  Terminal will close in 5 seconds — the GUI handles everything now."
            echo ""
            sleep 5
            kill -9 $PPID 2>/dev/null || true
            ;;
        *)
            echo "  You can close this terminal — the GUI handles everything now."
            echo ""
            ;;
    esac
else
    echo "  Installation complete. The GUI is now running."
    echo ""
fi
