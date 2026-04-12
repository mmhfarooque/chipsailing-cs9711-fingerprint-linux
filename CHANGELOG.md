# Changelog

All notable changes to the CS9711 Fingerprint Manager are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.2.0] - 2026-04-12

### Fixed
- GLib idle callbacks now return `False` to prevent re-execution (GTK4 pattern compliance)
- `reinstall.sh` validates `cs9711.c` exists before attempting sed patch
- `install.sh` validates package installer function exists before calling it

---

## [1.1.0] - 2026-04-12

### Fixed
- `uninstall.sh` now supports all distros (apt/dnf/pacman/zypper) — previously apt-only
- `uninstall.sh` detects library path by architecture (x86_64/aarch64/armv7l) — previously x86_64-only
- `uninstall.sh` removes GUI desktop shortcut on uninstall
- `.desktop` template no longer has misleading hardcoded `/opt/` path
- `reinstall.sh` shows clearer error when driver source is missing
- `setup-gui.sh` shows fallback instructions for unknown package managers
- Enrollment progress bar no longer shows fprintd debug noise (`ListEnrolledFingers failed`)
- Enrollment now shows retry feedback: bad read, too short, not centered, lift and retry

### Added
- GTK4 + libadwaita GUI manager (`cs9711-manager.py`)
  - Status panel: scanner, driver, enrolled fingers
  - Fingerprint enrollment with live 15-touch progress bar
  - Verify and delete fingerprints
  - Retry delay slider (250ms–3000ms) with rebuild trigger
  - PAM settings: max attempts (1–15), timeout (5–120s)
  - Auth location status: login, lock screen, sudo, polkit
  - Maintenance: rebuild, full install, uninstall, keyring auto-unlock
- `setup-gui.sh` — installs GTK4 deps and creates desktop shortcut
- GUI screenshot in README
- "Complete Setup (Driver + GUI)" section in README
- `install.sh` now mentions GUI setup in completion message

---

## [1.0.0] - 2026-04-12

### Added
- Universal `install.sh` — auto-detects distro (Ubuntu, Debian, Mint, Pop!_OS, Fedora, RHEL, Arch, Manjaro, openSUSE) and installs correct dependencies via apt/dnf/pacman/zypper
- `reinstall.sh` — quick rebuild after system updates overwrite patched library
- `uninstall.sh` — clean removal, restores stock libfprint
- `.deb` package builder (`packaging/deb/build-deb.sh`)
- RPM spec + builder for Fedora/RHEL/openSUSE (`packaging/rpm/`)
- Arch PKGBUILD for Arch/Manjaro/EndeavourOS (`packaging/arch/`)
- 1500ms retry delay patch (`patches/cs9711-retry-delay-1500ms.patch`)
- GNOME Keyring auto-unlock helper (`helpers/set-empty-keyring-password.py`)
- Distro-aware PAM configuration (common-auth vs authselect)
- Architecture-aware library paths (x86_64, aarch64, armv7l)
- Doctest dependency made optional (upstream changed it to required but it lacks pkg-config on Debian)
- Pre-built `.deb` in GitHub Releases (amd64)

### Hardware
- **Chip:** Chipsailing CS9711
- **USB ID:** `2541:0236`
- **Matching:** sigfm algorithm, 15-touch enrollment

### Tested On
- Ubuntu 24.04 LTS (Noble Numbat)
- Ubuntu 26.04 LTS (Resolute Reedbuck)
