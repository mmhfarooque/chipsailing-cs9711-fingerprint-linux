#!/bin/bash
# ============================================================================
# Build an Arch Linux package for CS9711 fingerprint driver
# ============================================================================
# For: Arch Linux, Manjaro, EndeavourOS, Garuda
#
# Usage: ./packaging/arch/build-arch.sh
# Or:    cd packaging/arch && makepkg -si
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "=== Building CS9711 Arch package ==="
echo ""

cd "$SCRIPT_DIR"
makepkg -si --noconfirm

echo ""
echo "Done! The package is installed."
echo "  Enroll: fprintd-enroll (15 touches)"
echo "  Test:   fprintd-verify"
