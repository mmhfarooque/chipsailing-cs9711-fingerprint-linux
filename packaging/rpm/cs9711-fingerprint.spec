Name:           cs9711-fingerprint
Version:        1.2.0
Release:        1%{?dist}
Summary:        Chipsailing CS9711 USB fingerprint scanner driver for Linux
License:        LGPL-2.1-or-later AND MIT
URL:            https://github.com/mmhfarooque/chipsailing-cs9711-fingerprint-linux
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  git meson ninja-build gcc
BuildRequires:  libfprint-devel glib2-devel libgusb-devel
BuildRequires:  pixman-devel cairo-devel openssl-devel
BuildRequires:  opencv-devel gobject-introspection-devel

Requires:       fprintd fprintd-pam

%description
Patched libfprint with support for the Chipsailing CS9711 fingerprint
scanner (USB ID: 2541:0236). Includes a 1500ms retry delay patch for
human-friendly scanning and a GTK4 GUI manager.

Enables fingerprint login, lock screen unlock, and sudo authentication.
Based on the archeYR/libfprint-CS9711 community driver.

%prep
%setup -q
if [ ! -d libfprint-CS9711 ]; then
    git clone https://github.com/archeYR/libfprint-CS9711.git
fi
cd libfprint-CS9711
sed -i 's/#define CS9711_DEFAULT_RESET_SLEEP.*/#define CS9711_DEFAULT_RESET_SLEEP  1500/' \
    libfprint/drivers/cs9711/cs9711.c
# Make doctest optional (only needed for tests)
sed -i "s/dependency('doctest', required: true)/dependency('doctest', required: false)/" \
    libfprint/sigfm/meson.build
sed -i '/^sigfm_tests/i if doctest.found()' libfprint/sigfm/meson.build
echo "endif" >> libfprint/sigfm/meson.build

%build
cd libfprint-CS9711
meson setup builddir \
    -Ddrivers=cs9711 \
    -Dudev_rules=disabled \
    -Dudev_hwdb=disabled \
    -Ddoc=false \
    -Dinstalled-tests=false \
    -Dgtk-examples=false
meson compile -C builddir

%install
cd libfprint-CS9711
DESTDIR=%{buildroot} meson install -C builddir

%post
ldconfig
systemctl restart fprintd 2>/dev/null || true

# Enable fingerprint auth via authselect if available
if command -v authselect &>/dev/null; then
    authselect enable-feature with-fingerprint 2>/dev/null || true
fi

echo ""
echo "CS9711 fingerprint driver installed!"
echo "  Enroll:  fprintd-enroll        (15 touches)"
echo "  Test:    fprintd-verify"
echo "  GUI:     python3 /path/to/cs9711-manager.py"

%postun
ldconfig
systemctl restart fprintd 2>/dev/null || true

%files
%license LICENSE
%doc README.md CHANGELOG.md
/usr/local/lib*/libfprint-2.so*

%changelog
* Sat Apr 12 2026 Mahmud Farooque <farooque7@gmail.com> - 1.2.0-1
- Add GTK4 GUI manager for scanner settings
- Fix enrollment progress showing fprintd debug noise
- Add retry feedback during enrollment (bad read, too short, not centered)
- Fix uninstall.sh for multi-distro and multi-arch support
- GLib callback pattern compliance
- Add CHANGELOG.md and VERSION tracking

* Sat Apr 12 2026 Mahmud Farooque <farooque7@gmail.com> - 1.0.0-1
- Initial package: CS9711 driver with 1500ms retry delay patch
- Multi-distro installer (apt/dnf/pacman/zypper)
- .deb, RPM, and Arch packaging
- PAM configuration with 7 retries, 30s timeout
