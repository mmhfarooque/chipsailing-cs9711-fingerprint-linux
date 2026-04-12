#!/bin/bash
# ============================================================================
# Install the CS9711 Fingerprint Manager GUI
# ============================================================================
# Installs Python GTK4 dependencies and creates a desktop shortcut.
#
# Usage: ./setup-gui.sh
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "=== CS9711 Fingerprint Manager — GUI Setup ==="
echo ""

# Detect package manager
if command -v apt &>/dev/null; then
    echo "[1/3] Installing GTK4 Python dependencies (apt)..."
    sudo apt install -y python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 2>&1 | tail -3
elif command -v dnf &>/dev/null; then
    echo "[1/3] Installing GTK4 Python dependencies (dnf)..."
    sudo dnf install -y python3-gobject gtk4 libadwaita 2>&1 | tail -3
elif command -v pacman &>/dev/null; then
    echo "[1/3] Installing GTK4 Python dependencies (pacman)..."
    sudo pacman -S --needed --noconfirm python-gobject gtk4 libadwaita 2>&1 | tail -3
elif command -v zypper &>/dev/null; then
    echo "[1/3] Installing GTK4 Python dependencies (zypper)..."
    sudo zypper install -y python3-gobject typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 2>&1 | tail -3
else
    echo "[1/3] Unknown package manager — install these manually:"
    echo "       python3-gi (PyGObject), GTK4, libadwaita"
fi
echo ""

# Make GUI executable
echo "[2/3] Setting up GUI..."
chmod +x "$SCRIPT_DIR/cs9711-manager.py"

# Create desktop shortcut
echo "[3/3] Creating desktop shortcut..."
DESKTOP_FILE="$HOME/.local/share/applications/cs9711-manager.desktop"
mkdir -p "$HOME/.local/share/applications"

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Type=Application
Name=CS9711 Fingerprint Manager
Comment=Configure Chipsailing CS9711 fingerprint scanner
Exec=python3 $SCRIPT_DIR/cs9711-manager.py
Icon=auth-fingerprint-symbolic
Terminal=false
Categories=Settings;HardwareSettings;System;
Keywords=fingerprint;scanner;cs9711;biometric;chipsailing;
EOF

echo ""
echo "=== Setup complete ==="
echo ""
echo "  Launch from terminal:  python3 $SCRIPT_DIR/cs9711-manager.py"
echo "  Launch from app menu:  Search 'CS9711' or 'Fingerprint Manager'"
echo ""
