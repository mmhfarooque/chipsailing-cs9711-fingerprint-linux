#!/bin/bash
# ============================================================================
# CS9711 Uninstall — Remove the patched driver and restore stock libfprint
# ============================================================================

set -e

echo ""
echo "=== CS9711 Fingerprint Driver — Uninstall ==="
echo ""

# Remove enrolled fingerprints
echo "[1/4] Removing enrolled fingerprints..."
fprintd-delete "$(whoami)" 2>/dev/null && echo "  Fingerprints deleted" || echo "  No fingerprints to delete"
echo ""

# Remove the patched library
echo "[2/4] Removing patched libfprint from /usr/local/..."
sudo rm -f /usr/local/lib/x86_64-linux-gnu/libfprint-2.so*
sudo rm -f /usr/local/lib/x86_64-linux-gnu/girepository-1.0/FPrint-2.0.typelib
sudo ldconfig
echo "  Patched library removed"
echo ""

# Reinstall stock libfprint
echo "[3/4] Reinstalling stock libfprint..."
sudo apt install --reinstall -y libfprint-2-2 2>&1 | tail -3
sudo ldconfig
echo ""

# Restart fprintd
echo "[4/4] Restarting fprintd..."
sudo systemctl restart fprintd
echo ""

echo "=== Uninstall complete ==="
echo ""
echo "Stock libfprint restored. CS9711 will no longer be supported."
echo "To reinstall later: ./install.sh"
