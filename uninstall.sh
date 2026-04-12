#!/bin/bash
# ============================================================================
# CS9711 Uninstall — Remove the patched driver and restore stock libfprint
# Supports: Ubuntu/Debian, Fedora/RHEL, Arch, openSUSE
# ============================================================================

set -e

# Logging — same log file as the GUI
LOG_DIR="$HOME/.local/share/cs9711-manager"
LOG_FILE="$LOG_DIR/cs9711.log"
mkdir -p "$LOG_DIR"
logmsg() { echo "$(date '+%Y-%m-%d %H:%M:%S') [UNINSTALL] $1" >> "$LOG_FILE"; }

echo ""
echo "=== CS9711 Fingerprint Driver — Uninstall ==="
echo ""
logmsg "=== CLI UNINSTALL STARTING ==="

# Detect distro
if [ -f /etc/os-release ]; then
    . /etc/os-release
    case "$ID" in
        ubuntu|debian|linuxmint|pop|elementary|zorin|kali|raspbian) PKG_FAMILY="apt" ;;
        fedora|rhel|centos|rocky|alma|nobara) PKG_FAMILY="dnf" ;;
        arch|manjaro|endeavouros|garuda|artix) PKG_FAMILY="pacman" ;;
        opensuse*|sles) PKG_FAMILY="zypper" ;;
        *)
            case "$ID_LIKE" in
                *debian*|*ubuntu*) PKG_FAMILY="apt" ;;
                *fedora*|*rhel*)   PKG_FAMILY="dnf" ;;
                *arch*)            PKG_FAMILY="pacman" ;;
                *suse*)            PKG_FAMILY="zypper" ;;
                *)                 PKG_FAMILY="unknown" ;;
            esac
            ;;
    esac
else
    PKG_FAMILY="unknown"
fi

# Detect library path
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  LIB_ARCH="x86_64-linux-gnu" ;;
    aarch64) LIB_ARCH="aarch64-linux-gnu" ;;
    armv7l)  LIB_ARCH="arm-linux-gnueabihf" ;;
    *)       LIB_ARCH="$ARCH-linux-gnu" ;;
esac

# Resolve real user (may be running under sudo/pkexec)
REAL_USER="${SUDO_USER:-$(whoami)}"
if [ "$REAL_USER" = "root" ] && [ -n "$PKEXEC_UID" ]; then
    REAL_USER=$(getent passwd "$PKEXEC_UID" | cut -d: -f1)
fi

# Remove enrolled fingerprints
echo "[1/4] Removing enrolled fingerprints..."
fprintd-delete "$REAL_USER" 2>/dev/null && echo "  Fingerprints deleted" || echo "  No fingerprints to delete"
echo ""

# Remove the patched library (check multiple possible locations)
echo "[2/4] Removing patched libfprint..."
sudo rm -f "/usr/local/lib/$LIB_ARCH/libfprint-2.so"* 2>/dev/null
sudo rm -f "/usr/local/lib/$LIB_ARCH/girepository-1.0/FPrint-2.0.typelib" 2>/dev/null
sudo rm -f /usr/local/lib64/libfprint-2.so* 2>/dev/null
sudo rm -f /usr/local/lib64/girepository-1.0/FPrint-2.0.typelib 2>/dev/null
sudo rm -f /usr/local/lib/libfprint-2.so* 2>/dev/null
sudo ldconfig
echo "  Patched library removed"
echo ""

# Reinstall stock libfprint
echo "[3/4] Reinstalling stock libfprint..."
case "$PKG_FAMILY" in
    apt)
        sudo apt install --reinstall -y libfprint-2-2 2>&1 | tail -3
        ;;
    dnf)
        sudo dnf reinstall -y libfprint 2>&1 | tail -3
        ;;
    pacman)
        sudo pacman -S --noconfirm libfprint 2>&1 | tail -3
        ;;
    zypper)
        sudo zypper install -f -y libfprint-2-2 2>&1 | tail -3
        ;;
    *)
        echo "  Unknown distro — please reinstall libfprint manually"
        ;;
esac
sudo ldconfig
echo ""

# Restart fprintd
echo "[4/4] Restarting fprintd..."
sudo systemctl restart fprintd 2>/dev/null || true
echo ""

# Remove desktop shortcut if present
DESKTOP_FILE="$HOME/.local/share/applications/cs9711-manager.desktop"
if [ -f "$DESKTOP_FILE" ]; then
    rm -f "$DESKTOP_FILE"
    echo "  GUI desktop shortcut removed"
fi

echo "=== Uninstall complete ==="
echo ""
echo "Stock libfprint restored. CS9711 will no longer be supported."
echo ""

# Ask about full cleanup
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
read -p "Also delete the project folder ($SCRIPT_DIR)? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Removing project folder..."
    # builddir/ contains root-owned files from sudo meson install
    sudo rm -rf "$SCRIPT_DIR/libfprint-CS9711/builddir" 2>/dev/null || true
    rm -rf "$SCRIPT_DIR"
    echo "Done. Everything removed."
    logmsg "Project folder deleted"
else
    echo "Project folder kept. To reinstall later: ./install.sh"
fi
