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

# rpmbuild is the only hard requirement. We do NOT auto-install anything:
# a packaging script that calls sudo cannot run unattended (it just hangs on a
# password prompt), and rpmdevtools is a convenience, not a dependency.
if ! command -v rpmbuild >/dev/null 2>&1; then
    echo "ERROR: rpmbuild not found. Install it first:"
    echo "  Fedora/RHEL:  sudo dnf install rpm-build"
    echo "  openSUSE:     sudo zypper install rpm-build"
    exit 1
fi

# Set up the RPM build tree. rpmdev-setuptree (rpmdevtools) is nicer but often
# absent; the tree is just a fixed set of directories, so create them directly
# when it is missing.
if command -v rpmdev-setuptree >/dev/null 2>&1; then
    rpmdev-setuptree
else
    mkdir -p "$HOME"/rpmbuild/{SOURCES,SPECS,BUILD,BUILDROOT,RPMS,SRPMS}
fi

# Create source tarball
TARBALL_DIR="$HOME/rpmbuild/SOURCES"
mkdir -p "$TARBALL_DIR"
cd "$PROJECT_DIR/.."
tar czf "$TARBALL_DIR/${PKG_NAME}-${VERSION}.tar.gz" \
    --transform="s/^chipsailing-cs9711-fingerprint-linux/${PKG_NAME}-${VERSION}/" \
    chipsailing-cs9711-fingerprint-linux/

# Sync the spec's Version to the VERSION file before building — the spec has
# drifted twice before (v2.0.1, v2.1.0) when this was left to manual edits.
# Same pattern as build-arch.sh syncing PKGBUILD's pkgver.
SPEC_VERSION=$(grep -E '^Version:' "$SCRIPT_DIR/cs9711-fingerprint.spec" | awk '{print $2}')
if [ "$SPEC_VERSION" != "$VERSION" ]; then
    echo "  spec Version was $SPEC_VERSION — syncing to $VERSION"
    sed -i "s/^Version:.*/Version:        $VERSION/" "$SCRIPT_DIR/cs9711-fingerprint.spec"
fi

# Copy spec file
cp "$SCRIPT_DIR/cs9711-fingerprint.spec" "$HOME/rpmbuild/SPECS/"

# Build
echo "Building RPM..."
rpmbuild -ba "$HOME/rpmbuild/SPECS/cs9711-fingerprint.spec"

echo ""
echo "============================================"
# Match THIS version's main package. The old glob was ${PKG_NAME}*.rpm piped to
# head -1, which happily returned a stale build or a -debuginfo/-debugsource
# subpackage — so the script printed an install command for the wrong file.
RPM_PATH=$(find "$HOME/rpmbuild/RPMS/" -name "${PKG_NAME}-${VERSION}-*.rpm" \
    ! -name '*-debuginfo-*' ! -name '*-debugsource-*' | sort | head -1)
echo "  RPM built: $RPM_PATH"
echo "============================================"
echo ""
echo "  Install (Fedora/RHEL): sudo dnf install $RPM_PATH"
echo "  Install (openSUSE):    sudo zypper install $RPM_PATH"
echo "  Remove:                sudo dnf remove $PKG_NAME"
echo ""
