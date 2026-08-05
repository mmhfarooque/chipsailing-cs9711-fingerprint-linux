Name:           cs9711-fingerprint
Version:        2.2.2
Release:        1%{?dist}
Summary:        Chipsailing CS9711 USB fingerprint scanner driver for Linux
License:        LGPL-2.1-or-later AND MIT
URL:            https://github.com/mmhfarooque/chipsailing-cs9711-fingerprint-linux
Source0:        %{name}-%{version}.tar.gz

# meson installs the full libfprint tree (headers, pkgconfig, gir); we only
# ship the runtime .so that shadows the system libfprint, so do not abort the
# build over the rest of the installed-but-unpackaged files.
%define _unpackaged_files_terminate_build 0

BuildRequires:  git gcc gcc-c++ meson
BuildRequires:  libfprint-devel glib2-devel libgusb-devel
BuildRequires:  cairo-devel opencv-devel gobject-introspection-devel
# Package names diverge between the RPM families:
%if 0%{?suse_version}
BuildRequires:  ninja libpixman-1-0-devel libopenssl-devel
%else
BuildRequires:  ninja-build pixman-devel openssl-devel
%endif

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
# OpenCV version-resilient (issue #2) — inline copy of helpers/opencv-flex.sh:
# opencv4 -> opencv5 -> opencv pkg-config names, then CMake's OpenCV, so a
# distro OpenCV major bump doesn't fail the build.
if ! grep -q "method: 'cmake'" libfprint/sigfm/meson.build; then
    sed -i "s|opencv = dependency('opencv4', required: true)|opencv = dependency('opencv4', required: false)\nif not opencv.found()\n  opencv = dependency('opencv5', required: false)\nendif\nif not opencv.found()\n  opencv = dependency('opencv', required: false)\nendif\nif not opencv.found()\n  opencv = dependency('OpenCV', method: 'cmake', required: true)\nendif|" \
        libfprint/sigfm/meson.build
fi

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
* Wed Aug 05 2026 Mahmud Farooque <farooque7@gmail.com> - 2.2.2-1
- Installer now verifies the patched libfprint is the one the linker actually
  resolves, and extends the linker path via /etc/ld.so.conf.d if not. On
  Arch/CachyOS /usr/local is not searched, so the stock library kept winning
  and fprintd reported no device while lsusb saw the scanner (issue #2)
- Update-guard restore cache is populated from meson's real install directory
  instead of ldconfig resolution, which cached the STOCK library on Arch
- A post-install run where fprintd cannot see the scanner is now a hard error
  with diagnostics, not a warning that let a broken install look successful

* Wed Aug 05 2026 Mahmud Farooque <farooque7@gmail.com> - 2.2.1-1
- Author credit is now visible on the window itself (footer under both columns,
  with profile/email/repo links and the dual-licence note), not only inside the
  About dialog which has to be opened to be seen

* Wed Aug 05 2026 Mahmud Farooque <farooque7@gmail.com> - 2.2.0-1
- GUI rebuilt as an adaptive two-column dashboard: everything fits on screen
  instead of a ~1900px single column, and it collapses back to one column
  below 880sp for narrow/mobile-style windows
- Status is now a single hero card; scan and authentication settings merged;
  a driver stranded by a library upgrade is reported in a banner with a
  Rebuild button rather than a buried subtitle
- Added an About dialog with developer credit, project and issue links, and
  the MIT (manager) / LGPL-2.1-or-later (driver) licence note
- Icon names resolved against the running theme — auth-fingerprint-symbolic
  does not exist on KDE Breeze and rendered as a broken-image glyph

* Wed Aug 05 2026 Mahmud Farooque <farooque7@gmail.com> - 2.1.0-1
- Survive a distro OpenCV major upgrade (issue #2): sigfm now resolves OpenCV as
  opencv4 -> opencv5 -> opencv (pkg-config) -> CMake OpenCV, so an OpenCV 4 -> 5
  bump no longer fails the build or strands an installed driver
- Update guard detects an unloadable (not just replaced) driver, restores from
  cache only when that copy still loads, and names the vanished libraries;
  pacman/dnf hooks now fire on opencv transactions too
- GUI reports a stranded driver as BROKEN with the missing libraries named,
  instead of a generic not-installed message
- Apply PAM Settings works on Arch/CachyOS (issue #1) — options are re-stamped
  onto each enabled per-service file, never the absent common-auth

* Tue Jun 23 2026 Mahmud Farooque <farooque7@gmail.com> - 2.0.2-1
- Per-service PAM control: enable fingerprint independently for login, lock
  screen, sudo and polkit via each service's own PAM file (not the shared
  common-auth), so each location can be toggled on/off separately
- GUI: "Where to Use Fingerprint" is now four real on/off switches
- installer: configure_pam() rewritten to the per-service model (deb + rpm parity);
  fixes openSUSE where fingerprint PAM was never wired before
- Password fallback always preserved (fprintd is only ever 'sufficient')

* Tue Jun 23 2026 Mahmud Farooque <farooque7@gmail.com> - 2.0.1-1
- Sync spec Version with VERSION file (was stuck at 1.2.0, broke rpmbuild %%setup)
- Cross-distro BuildRequires: correct openSUSE names via %%if suse_version
  (ninja, libpixman-1-0-devel, libopenssl-devel); add gcc-c++ for sigfm/OpenCV
- Package only the runtime libfprint-2.so* (ignore meson's dev files)
- Rebuilt and hardware-verified on openSUSE Tumbleweed (CS9711 enrol + verify)

* Sat May 30 2026 Mahmud Farooque <farooque7@gmail.com> - 2.0.0-1
- Milestone: all-distro support (apt/dnf/pacman/zypper), container build-verified
- Self-healing update guard; hardened against real-world install hazards

* Sun Apr 12 2026 Mahmud Farooque <farooque7@gmail.com> - 1.2.0-1
- Add GTK4 GUI manager for scanner settings
- Fix enrollment progress showing fprintd debug noise
- Add retry feedback during enrollment (bad read, too short, not centered)
- Fix uninstall.sh for multi-distro and multi-arch support
- GLib callback pattern compliance
- Add CHANGELOG.md and VERSION tracking

* Sun Apr 12 2026 Mahmud Farooque <farooque7@gmail.com> - 1.0.0-1
- Initial package: CS9711 driver with 1500ms retry delay patch
- Multi-distro installer (apt/dnf/pacman/zypper)
- .deb, RPM, and Arch packaging
- PAM configuration with 7 retries, 30s timeout
