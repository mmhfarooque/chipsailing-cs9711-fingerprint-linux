#!/bin/bash
# ============================================================================
# Build a .deb package for CS9711 fingerprint driver
# ============================================================================
# Creates a .deb that:
#   - Installs the patched libfprint .so to the correct lib path
#   - Runs ldconfig and restarts fprintd on install
#   - Configures PAM with sensible defaults
#   - Declares runtime dependencies (fprintd, libpam-fprintd)
#
# Usage: ./packaging/deb/build-deb.sh
# Output: ./cs9711-fingerprint_1.0.0_<arch>.deb
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DRIVER_DIR="$PROJECT_DIR/libfprint-CS9711"
VERSION=$(cat "$PROJECT_DIR/VERSION" 2>/dev/null | tr -d '[:space:]' || echo "1.2.0")
ARCH=$(dpkg --print-architecture 2>/dev/null || echo "amd64")

case "$ARCH" in
    amd64)   LIB_ARCH="x86_64-linux-gnu" ;;
    arm64)   LIB_ARCH="aarch64-linux-gnu" ;;
    armhf)   LIB_ARCH="arm-linux-gnueabihf" ;;
    *)       LIB_ARCH="$ARCH-linux-gnu" ;;
esac

PKG_NAME="cs9711-fingerprint"
PKG_DIR="$PROJECT_DIR/build/${PKG_NAME}_${VERSION}_${ARCH}"
DEB_OUTPUT="$PROJECT_DIR/${PKG_NAME}_${VERSION}_${ARCH}.deb"

echo ""
echo "=== Building CS9711 .deb package ==="
echo "  Version: $VERSION"
echo "  Arch:    $ARCH ($LIB_ARCH)"
echo ""

# ---- Step 1: Build the driver ----
echo "[1/4] Building driver from source..."
if [ ! -d "$DRIVER_DIR/.git" ]; then
    echo "  Cloning driver source..."
    git clone https://github.com/archeYR/libfprint-CS9711.git "$DRIVER_DIR"
fi

# Apply patch
CS9711_FILE="$DRIVER_DIR/libfprint/drivers/cs9711/cs9711.c"
if ! grep -q "CS9711_DEFAULT_RESET_SLEEP  1500" "$CS9711_FILE"; then
    sed -i 's/#define CS9711_DEFAULT_RESET_SLEEP.*/#define CS9711_DEFAULT_RESET_SLEEP  1500/' "$CS9711_FILE"
fi

# Make doctest optional (only needed for tests, not the driver)
SIGFM_MESON="$DRIVER_DIR/libfprint/sigfm/meson.build"
if [ -f "$SIGFM_MESON" ] && grep -q "required: true" "$SIGFM_MESON"; then
    sed -i "s/dependency('doctest', required: true)/dependency('doctest', required: false)/" "$SIGFM_MESON"
    if ! grep -q "if doctest.found()" "$SIGFM_MESON"; then
        sed -i '/^sigfm_tests/i if doctest.found()' "$SIGFM_MESON"
        echo "endif" >> "$SIGFM_MESON"
    fi
fi

cd "$DRIVER_DIR"
rm -rf builddir
meson setup builddir \
    -Ddrivers=cs9711 \
    -Dudev_rules=disabled \
    -Dudev_hwdb=disabled \
    -Ddoc=false \
    -Dinstalled-tests=false \
    -Dgtk-examples=false
meson compile -C builddir
echo "  Build complete"
echo ""

# ---- Step 2: Create package structure ----
echo "[2/4] Creating package structure..."
rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR/DEBIAN"
mkdir -p "$PKG_DIR/usr/local/lib/$LIB_ARCH"
mkdir -p "$PKG_DIR/usr/share/doc/$PKG_NAME"

# Copy the built library
cp -P "$DRIVER_DIR/builddir/libfprint/libfprint-2.so"* "$PKG_DIR/usr/local/lib/$LIB_ARCH/" 2>/dev/null || true
# Also copy the versioned .so
find "$DRIVER_DIR/builddir/libfprint/" -name "libfprint-2.so*" -exec cp -P {} "$PKG_DIR/usr/local/lib/$LIB_ARCH/" \;

# Copy docs
cp "$PROJECT_DIR/README.md" "$PKG_DIR/usr/share/doc/$PKG_NAME/"
cp "$PROJECT_DIR/CHANGELOG.md" "$PKG_DIR/usr/share/doc/$PKG_NAME/" 2>/dev/null || true
echo ""

# ---- Step 3: Create debian control files ----
echo "[3/4] Creating package metadata..."

# Installed size in KB
INSTALLED_SIZE=$(du -sk "$PKG_DIR" 2>/dev/null | awk '{print $1}')

cat > "$PKG_DIR/DEBIAN/control" << EOF
Package: $PKG_NAME
Version: $VERSION
Section: libs
Priority: optional
Architecture: $ARCH
Depends: fprintd, libpam-fprintd, libglib2.0-0 (>= 2.50), libgusb2 (>= 0.3.0)
Installed-Size: $INSTALLED_SIZE
Maintainer: Mahmud Farooque <farooque7@gmail.com>
Homepage: https://github.com/mmhfarooque/chipsailing-cs9711-fingerprint-linux
Description: Chipsailing CS9711 USB fingerprint scanner driver for Linux
 Patched libfprint with support for the Chipsailing CS9711 fingerprint
 scanner (USB ID: 2541:0236). Includes a 1500ms retry delay patch for
 human-friendly scanning and PAM configuration for fingerprint auth.
 .
 Enables fingerprint login, lock screen unlock, and sudo authentication.
 .
 Based on the archeYR/libfprint-CS9711 community driver.
 .
 Includes GTK4 GUI manager for scanner settings.
 See CHANGELOG.md for version history.
EOF

# postinst — runs after install
cat > "$PKG_DIR/DEBIAN/postinst" << 'EOF'
#!/bin/bash
set -e

# Update library cache
ldconfig

# Restart fprintd to pick up the new driver
if systemctl is-active --quiet fprintd 2>/dev/null; then
    systemctl restart fprintd
fi

# Configure PAM if not already done
PAM_FILE="/etc/pam.d/common-auth"
if [ -f "$PAM_FILE" ] && grep -q "pam_fprintd.so" "$PAM_FILE"; then
    if ! grep -q "max-tries=7" "$PAM_FILE"; then
        sed -i 's/pam_fprintd.so.*/pam_fprintd.so max-tries=7 timeout=30/' "$PAM_FILE"
    fi
fi

echo ""
echo "============================================"
echo "  CS9711 fingerprint driver installed!"
echo "============================================"
echo ""
echo "  Enroll:  fprintd-enroll        (15 touches)"
echo "  Test:    fprintd-verify"
echo "  Check:   fprintd-list \$(whoami)"
echo ""
EOF
chmod 755 "$PKG_DIR/DEBIAN/postinst"

# postrm — runs after removal
cat > "$PKG_DIR/DEBIAN/postrm" << 'EOF'
#!/bin/bash
set -e
ldconfig
if systemctl is-active --quiet fprintd 2>/dev/null; then
    systemctl restart fprintd
fi
EOF
chmod 755 "$PKG_DIR/DEBIAN/postrm"

echo ""

# ---- Step 4: Build the .deb ----
echo "[4/4] Building .deb package..."
dpkg-deb --build "$PKG_DIR" "$DEB_OUTPUT"
echo ""

# Cleanup build dir
rm -rf "$PROJECT_DIR/build"

echo "============================================"
echo "  Package built: $DEB_OUTPUT"
echo "============================================"
echo ""
echo "  Install:    sudo dpkg -i $DEB_OUTPUT"
echo "  Or:         sudo apt install ./$DEB_OUTPUT"
echo "  Remove:     sudo apt remove $PKG_NAME"
echo ""
echo "  Share this .deb — works on Ubuntu, Debian, Mint, Pop!_OS, etc."
echo ""
