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
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION=$(tr -d '[:space:]' < "$PROJECT_DIR/VERSION")

echo ""
echo "=== Building CS9711 Arch package ==="
echo "  Version: $VERSION"
echo ""

# Keep pkgver in step with VERSION. The PKGBUILD sat at 1.2.0 for many releases
# while VERSION moved on, so pacman compared the wrong version on upgrade.
CURRENT=$(sed -n 's/^pkgver=//p' "$SCRIPT_DIR/PKGBUILD")
if [ "$CURRENT" != "$VERSION" ]; then
    echo "  pkgver was $CURRENT — syncing to $VERSION"
    sed -i "s/^pkgver=.*/pkgver=$VERSION/" "$SCRIPT_DIR/PKGBUILD"
fi

cd "$SCRIPT_DIR"
makepkg -si --noconfirm

echo ""
echo "Done! The package is installed."
echo "  Enroll: fprintd-enroll (15 touches)"
echo "  Test:   fprintd-verify"
