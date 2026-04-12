#!/bin/bash
# ============================================================================
# Build an RPM package for CS9711 fingerprint driver
# ============================================================================
# For: Fedora, RHEL, CentOS, Rocky Linux, Alma Linux, openSUSE
#
# Usage: ./packaging/rpm/build-rpm.sh
# Requires: rpm-build, rpmdevtools
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION=$(cat "$PROJECT_DIR/VERSION" 2>/dev/null | tr -d '[:space:]' || echo "1.2.0")
PKG_NAME="cs9711-fingerprint"

echo ""
echo "=== Building CS9711 RPM package ==="
echo ""

# Install RPM build tools
if command -v dnf &>/dev/null; then
    sudo dnf install -y rpm-build rpmdevtools 2>&1 | tail -3
elif command -v zypper &>/dev/null; then
    sudo zypper install -y rpm-build rpmdevtools 2>&1 | tail -3
fi

# Set up RPM build tree
rpmdev-setuptree

# Create source tarball
TARBALL_DIR="$HOME/rpmbuild/SOURCES"
mkdir -p "$TARBALL_DIR"
cd "$PROJECT_DIR/.."
tar czf "$TARBALL_DIR/${PKG_NAME}-${VERSION}.tar.gz" \
    --transform="s/^chipsailing-cs9711-fingerprint-linux/${PKG_NAME}-${VERSION}/" \
    chipsailing-cs9711-fingerprint-linux/

# Copy spec file
cp "$SCRIPT_DIR/cs9711-fingerprint.spec" "$HOME/rpmbuild/SPECS/"

# Build
echo "Building RPM..."
rpmbuild -ba "$HOME/rpmbuild/SPECS/cs9711-fingerprint.spec"

echo ""
echo "============================================"
RPM_PATH=$(find "$HOME/rpmbuild/RPMS/" -name "${PKG_NAME}*.rpm" | head -1)
echo "  RPM built: $RPM_PATH"
echo "============================================"
echo ""
echo "  Install (Fedora/RHEL): sudo dnf install $RPM_PATH"
echo "  Install (openSUSE):    sudo zypper install $RPM_PATH"
echo "  Remove:                sudo dnf remove $PKG_NAME"
echo ""
