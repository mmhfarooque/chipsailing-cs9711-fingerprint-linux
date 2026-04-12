# Changelog

All notable changes to the CS9711 Fingerprint Manager are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.4.0] - 2026-04-12

### Added
- **Enrollment status banner** — shows "Enrolled: 1 finger(s) enrolled: right-index-finger" or "Not Enrolled" with guidance to enroll
- **Re-enroll confirmation** — if fingerprints already exist, clicking Enroll shows a dialog: "Fingerprints already enrolled. Add another finger?" instead of silently starting enrollment
- **Auto-verify after enrollment** — after successful 15-touch enrollment, the GUI automatically asks you to touch the scanner to verify the fingerprint works, confirming everything is set up
- **Dynamic button label** — "Enroll" changes to "Add Another Finger" when fingerprints are already enrolled

### Fixed
- **Empty desktop shortcut** — heredoc in install.sh was writing 0-byte .desktop file, making app invisible in launcher. Switched to echo.
- **Native fingerprint icon** — uses `auth-fingerprint-symbolic` from Adwaita/Yaru instead of generic gear icon

---

## [1.3.0] - 2026-04-12

### Changed
- **GUI Manager now installs automatically** — `install.sh` step 8/8 installs GTK4 deps, creates desktop shortcut, no separate `setup-gui.sh` needed
- Install completion message now shows the GUI launch command (`python3 cs9711-manager.py`)
- Install completion message now shows uninstall command (`./uninstall.sh`)

### Fixed
- GUI shortcut was not created during install — users searching "CS9711" in app launcher found nothing
- Completion message had no way to launch GUI or uninstall

### Improved
- `uninstall.sh` now asks whether to also delete the project folder for full cleanup (`y/N` prompt)
- Steps renumbered from 7 to 8 across all install output

---

## [1.2.1] - 2026-04-12

### Fixed
- **CRITICAL:** GUI custom retry delay was silently overwritten back to 1500ms by `reinstall.sh` — now preserves any custom value already set in source
- **CRITICAL:** Keyring helper (`set-empty-keyring-password.py`) crashed when launched from GUI because `getpass` needs a terminal — now opens in a terminal emulator (ptyxis/gnome-terminal/konsole/xterm)
- `$USER` resolved to "root" when scripts ran via pkexec from GUI, causing `fprintd-list` to check root's prints instead of the real user — all scripts now resolve the real user via `SUDO_USER`/`PKEXEC_UID`

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
