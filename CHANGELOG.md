# Changelog

All notable changes to the CS9711 Fingerprint Manager are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.2.4] - 2026-08-05

**The Arch fix now works on the first run — confirmed working on CachyOS with OpenCV 5.**

@josepcarles confirmed v2.2.2 gets a CS9711 scanner working again on CachyOS with `opencv 5.0.0-7.1`, which closes out the original report. But his first `reinstall.sh` run failed, and he only got through by running `sudo ldconfig` by hand and trying again. That was a real bug in my fix.

### Fixed
- **The linker-cache refresh was running without root, so it silently did nothing.** `ldconfig -p` reads the cache and works unprivileged; plain `ldconfig` *rebuilds* it and needs root. The helper called the rebuild without `sudo` and sent the resulting permission error to `/dev/null`, so after writing `/etc/ld.so.conf.d/00-cs9711-local.conf` the cache was never actually rebuilt. The verification then read a **stale** cache, concluded the patched driver still was not being resolved, and aborted — even though the fix was correctly in place. A manual `sudo ldconfig` plus a re-run was the only way past it.
- The helper now separates the two operations explicitly: an unprivileged query for reading, and a root-elevated refresh for rebuilding, with the failure surfaced rather than swallowed.

If you installed v2.2.2 or v2.2.3 and saw the abort message about the system still resolving `/usr/lib/libfprint-2.so.2`, this is why — and `sudo ldconfig` followed by `./reinstall.sh` was the correct workaround. On v2.2.4 the first run should just work.

---

## [2.2.3] - 2026-08-05

**Packaging parity: the .deb ships again, the Arch version stops lying, and both packages carry the install verification.**

Until now every release attached only an x86_64 RPM. The .deb build script existed and worked — it was the original packaging path, written on Ubuntu — but no .deb had been built or attached for any recent release.

### Fixed
- **The .deb can now be built from any distro.** `build-deb.sh` required `dpkg-deb`, so it could only run on a Debian-family machine. A `.deb` is just an `ar` archive of three members in a fixed order, so when `dpkg-deb` is absent the script now assembles it with `ar` and `tar` instead. Same output, no Debian tooling needed — which is what lets it be released from a Fedora/openSUSE/Arch workstation.
- **The Arch `PKGBUILD` version was hardcoded at `1.2.0`** while `VERSION` had moved on for many releases, so pacman compared the wrong version on upgrade. It now tracks `VERSION`, and `build-arch.sh` syncs it before building. (Same class of drift that broke the v2.0.1 RPM.)
- **The .deb was shipping build artifacts** — meson's `libfprint-2.so.2.0.0.p/` object directory and a `.symbols` file both matched the copy glob and ended up inside the package. Now only the real library and its symlinks are packaged.
- **The .deb postinst now verifies the install took effect**, the same check `install.sh` gained in v2.2.2: if the linker does not resolve our patched library it adds the install directory to `/etc/ld.so.conf.d` and re-checks, and warns clearly if it still does not. Debian and Ubuntu normally ship `/usr/local/lib/<triplet>` in the linker path so this passes silently, but a trimmed or derivative image may not — and that silent-failure mode is exactly what issue #2 turned out to be.

### Note on packages
The RPM and .deb contain **the patched driver only** — the library, plus docs and licence. They do not include the GTK4 GUI manager or `install.sh`. For the GUI, the update guard and the PAM management, use the repository route (`git clone` then `./install.sh`), which remains the supported path on every distro.

There is **no AppImage and cannot be one**: the whole job is patching the system's libfprint and editing `/etc/pam.d`, neither of which a sandboxed bundle can do. Package parity targets are deb and rpm.

---

## [2.2.2] - 2026-08-05

**The installer now verifies that it actually took effect — fixes the second half of #2 on Arch/CachyOS.**

Reported by @josepcarles, who retested v2.1.0 on CachyOS with `opencv 5.0.0-7.1`: the build completed with no errors (so the OpenCV work in v2.1.0 did its job), but enrolment still failed with *No devices available* while `lsusb` showed the scanner.

### Fixed
- **The patched library was installed where the linker never looks.** `meson` installs under `/usr/local`, which only shadows the distro's own libfprint when `/usr/local/lib{,64}` is in the dynamic linker's search path. openSUSE, Fedora and Debian list it first in `/etc/ld.so.conf`; **Arch and CachyOS do not** — glibc's built-in search covers `/usr/lib` and `/lib` only. So on Arch the stock libfprint kept winning, `fprintd` saw no device, and the install looked successful.
  - The installer and the rebuild path now check whether the **resolved** libfprint is actually ours (it carries the `cs9711` marker). If not, they add the real install directory to `/etc/ld.so.conf.d/00-cs9711-local.conf`, refresh the cache and re-verify. Reversible: `uninstall.sh` removes the file.
  - We deliberately do **not** install with `--prefix=/usr`, which would overwrite a distro-owned file that the next package update clobbers anyway.
  - Diagnostic worth knowing: run `ldd` on the resolved libfprint. Our build links OpenCV (the sigfm matcher needs it); a resolved library with **no OpenCV libraries at all** is the distro's, not ours.
- **The update guard was caching the wrong library on Arch.** The restore cache was populated from whatever `ldconfig` resolved — which on Arch was the stock library, recorded against `/usr/lib`. The guard was therefore silently useless there. The cache now comes from meson's real install directory.
- **A failed install no longer reports success.** The post-install check that `fprintd` can see the scanner was a warning; it is now a hard error with the exact diagnostics to paste into a bug report. That warning is how this stayed hidden through a run that finished without errors.

---

## [2.2.1] - 2026-08-05

**Author credit is visible in the app, not hidden behind a dialog.**

### Changed
- v2.2.0 put the developer credit only in the About dialog, which has to be opened before it can be seen. There is now a **footer across the bottom of the window**, under both columns: developer name linking to the GitHub profile, contact email as a mailto link, a link to the source and issue tracker, and the version plus dual-licence line (MIT for this manager, LGPL-2.1-or-later for the patched driver). The About dialog keeps the same details.

---

## [2.2.0] - 2026-08-05

**GUI rebuilt as an adaptive two-column dashboard — no more endless scrolling.**

### Changed
- **The window is no longer one tall column.** Seven stacked groups ran to roughly 1900px, so Maintenance and Diagnostics sat below the fold on most screens. The layout is now two columns: the left carries the workflow (status → enrol → scanner/authentication tuning), the right carries configuration and upkeep (where fingerprint applies → maintenance → diagnostics). Everything fits on screen at once at 1120×720.
- **Adaptive, not merely wide.** An `Adw.Breakpoint` collapses the two columns back into a single vertical column below 880sp, so the app stays correct in a narrow/mobile GNOME context, a half-tiled window, or on a small laptop screen. Verified programmatically: horizontal at 1200sp, vertical at 600sp.
- **Status is a hero card**, not three stacked rows. One headline answers whether fingerprint works right now, with Scanner / Driver / Fingers as colour-coded chips beneath it — ~120px instead of ~200px, and the three facts are only ever read together anyway.
- **Scan Settings and Authentication Settings merged** into a single group. Two headings and two descriptions for four controls that all answer the same question (how hard should it try before giving up).
- **A broken driver is now an `Adw.Banner`** across the top of the window with a Rebuild button, instead of a subtitle buried mid-page.

### Added
- **About dialog** (header bar) with developer credit, contact, GitHub profile, project and issue links, upstream driver link, and the correct dual-licence note — MIT for this manager and installer, LGPL-2.1-or-later for the patched libfprint driver.

### Fixed
- **Icon names are resolved against the running icon theme.** `auth-fingerprint-symbolic` is an Adwaita name that KDE Breeze does not ship, so it rendered as the broken-image glyph — the same portability trap already documented for the `.desktop` file. A fallback chain now picks the first name the theme actually has.
- A bare ampersand in a `PreferencesGroup` title raised a Pango markup error and blanked the heading (those titles are parsed as markup).

### Notes
- Styling uses only alpha-over-currentColor, no hardcoded colours, so it reads correctly under Adwaita, Breeze, Cinnamon and XFCE in both light and dark variants.
- No change to the driver, installer, PAM model or packaging — this release is the GUI only.

---

## [2.1.0] - 2026-08-05

**OpenCV-upgrade resilience + Arch/CachyOS PAM apply — fixes #1 and #2.**

### Fixed
- **A distro OpenCV major upgrade (4 → 5) no longer strands the driver** (issue #2, reported on CachyOS with `opencv 5.0.0-1`). The patched `libfprint` links against specific OpenCV sonames; when the distro removes them, `fprintd` silently loses the device while `lsusb` still shows it — and the old restore-from-cache guard could not help, because the cached copy was built against the same vanished sonames.
  - The sigfm build patch now resolves OpenCV as `opencv4` → `opencv5` → `opencv` (pkg-config), then falls back to **CMake's `OpenCV`** — which works on Arch-family systems even when no `.pc` file is shipped. Trees still carrying the old two-step patch are upgraded in place, so a plain `./reinstall.sh` picks this up.
  - Applied identically in `install.sh`, `reinstall.sh`, the container build, **PKGBUILD**, the **RPM spec** and the **deb build** (the packaged builds previously still hard-required `opencv4`).
- **The update guard now detects an unloadable driver**, not just a replaced one: after every package transaction it `ldd`-checks the active library, restores from cache only when the cached copy itself still loads, and otherwise logs exactly which libraries vanished and flags the state for the GUI. The pacman and dnf hooks additionally **fire on `opencv` transactions**, not just `libfprint`.
- **GUI diagnoses the stranded-driver state** (issue #2's confusing symptom): when `fprintd` reports no device, the Driver status row now runs a loadability check and shows *BROKEN — missing libopencv_… (system OpenCV upgrade?) — use Maintenance → Rebuild Driver* instead of a generic not-installed message.
- **“Apply PAM Settings” now works on Arch/CachyOS** (issue #1). It re-stamps max-tries/timeout onto every location that is currently enabled, through the same per-service files the switches manage — no `common-auth` involved, which Arch does not have. All locations are combined into one `pkexec` call, and with nothing enabled the GUI now says to turn a location switch on instead of silently claiming success.
- Per-service insertion now also anchors on `system-auth` / `system-login` includes (Arch-family), not just `common-auth`.

### Changed
- `reinstall.sh` refreshes the update guard and package-manager hooks on every rebuild, so existing installs receive the new guard without rerunning `install.sh`.
- Guard/hook installation moved to shared `helpers/install-guard.sh` + `helpers/cs9711-update-guard`; the OpenCV meson patch to `helpers/opencv-flex.sh` (PKGBUILD/spec carry an inline copy — they build from the bare fork checkout).

---

## [2.0.2] - 2026-06-23

**Per-location fingerprint control — independent on/off switches.**

### Added
- **"Where to Use Fingerprint" is now four real on/off switches** (Login screen, Lock screen, sudo, polkit) instead of read-only status. Each can be enabled or disabled independently from the GUI.
- Per-service PAM model: fingerprint is wired into each service's **own** PAM file (`sddm`/display-manager, `kde-fingerprint`/lock, `sudo`, `polkit-1`) rather than the shared `common-auth`, so toggling one location no longer affects the others.

### Fixed
- **openSUSE PAM was never configured by the installer** (no `pam-auth-update`/`authselect`, and the old fallback only edited a line if one already existed). `configure_pam()` is rewritten to the per-service model and now works on openSUSE too — **deb + rpm parity**.
- Vendor-dir PAM layout (`/usr/lib/pam.d`) is now detected, so KDE's `kde-fingerprint` lock-screen stack and openSUSE service files are seen correctly.
- "Apply PAM Settings" (max-tries/timeout) now updates the per-service override files instead of `common-auth`.

### Safety
- Every override preserves the full vendor stack and adds `pam_fprintd` only as `sufficient`, so **password authentication can never be locked out**. Changes are reversible (remove the override → revert to vendor).

---

## [2.0.1] - 2026-06-23

**Packaging fix — RPM now builds and is hardware-verified on openSUSE.**

### Fixed
- **RPM spec version drift.** `cs9711-fingerprint.spec` was pinned at `1.2.0` while `VERSION` had moved to `2.0.0`, so `build-rpm.sh` produced a `…-2.0.0.tar.gz` tarball that `%setup` (expecting `…-1.2.0`) could not unpack — the RPM build was broken. Spec version now tracks `VERSION`.
- **openSUSE BuildRequires.** The spec used Fedora-only package names (`ninja-build`, `pixman-devel`, `openssl-devel`). Added an `%if 0%{?suse_version}` branch with the correct openSUSE names (`ninja`, `libpixman-1-0-devel`, `libopenssl-devel`) and added `gcc-c++` (required by the sigfm/OpenCV C++ build).
- **Unpackaged-files build abort.** `meson install` lays down the full libfprint tree (headers, pkgconfig, gir). Since the package only ships the runtime `libfprint-2.so*` that shadows the system library, the build no longer aborts over the unpackaged dev files.

### Verified
- Built and installed as an RPM on **openSUSE Tumbleweed** on real CS9711 hardware (`2541:0236`); enrol + verify confirmed.

---

## [2.0.0] - 2026-05-30

**Milestone release.** Consolidates the v1.9.x line into one headline: the CS9711 installer now builds and sets up correctly on **every current mainstream Linux distro**, repairs itself after system updates, and is hardened against the two real-world hazards an end-user review surfaced. No breaking changes — the major bump marks the leap from "tested on one machine" to "verified across the ecosystem."

### All-distro compatibility — container-verified (2026-05-30)
Build-tested green (deps → meson → compile → `cs9711` driver present in the `.so`) on:
- **Stable / LTS:** Ubuntu 26.04 LTS, Fedora 44, Arch Linux, openSUSE Tumbleweed, Debian 13 (Trixie), Linux Mint 22.
- **Bleeding-edge:** Fedora Rawhide (F45 prerelease), Debian sid, Ubuntu devel ("Resolute Raccoon").
- **Reference platform (real hardware, daily use):** Kubuntu 26.04 / Plasma 6.6.4 — enroll, verify/match, and `sudo`/lock/login all functional.

Real packaging gaps the matrix exposed and fixed (each would have failed a fresh install):
- No C/C++ compiler in the dep lists → added `build-essential` (apt) and `gcc gcc-c++` (dnf/zypper); Arch's `base-devel` already covered it.
- **Arch** split the glib dev tools out → added `glib2-devel` (build failed at `meson setup` without it).
- **openSUSE** package name `pixman-devel` → `libpixman-1-0-devel`.
- **OpenCV:** sigfm hardcoded `opencv4` (`required: true`) → now prefers `opencv4` and falls back to `opencv5` for future distros (control-flow proven; OpenCV 5 ships nowhere yet — even Rawhide is 4.13.0).

### Self-healing update guard — fixes the #1 community complaint
*"A system update overwrote libfprint and broke fingerprint."* A package-manager post-transaction hook now detects when the active libfprint loses the `cs9711` driver and **restores it automatically**:
- Hooks: apt `DPkg::Post-Invoke`, **dnf5 `libdnf5-plugin-actions`** (verified firing on Fedora 44), dnf4 `post-transaction-actions`, pacman `PostTransaction`.
- Restore is from a **root-owned cache** (`/var/lib/cs9711-fingerprint`) via plain file-copy — fast, can't fail to compile, and never executes build files as root.

### Security & footgun hardening (end-user review pass)
- **No build-as-root.** Earlier guards ran `meson` as root from the user's home directory — a local privilege-escalation vector. Replaced with the root-owned-cache restore above.
- **Won't silently break a different reader.** The installer builds a CS9711-only libfprint into `/usr/local` that shadows the system one; on a laptop with a *different* fingerprint reader that would break it. Now **aborts if the CS9711 (`2541:0236`) isn't detected** (override `CS9711_FORCE=1`) + prominent README warning.
- `uninstall.sh` removes the guard / hooks / cache **first**, so reinstalling stock libfprint can't re-trigger the guard.

### Scope note
This project is the **installer / setup / packaging layer**. The driver and its fingerprint *matching* (e.g. `verify-no-match`) are upstream **[archeYR/libfprint-CS9711](https://github.com/archeYR/libfprint-CS9711)** — we default users to that best-maintained fork and prompt a clean re-enroll.

*(Rolls up [1.9.0] + [1.9.1] + [1.9.2]; granular history below.)*

---

## [1.9.2] - 2026-05-30

### Changed — security & robustness (end-user review pass)
- **The update guard no longer compiles as root.** v1.9.0–1.9.1 ran `meson compile && meson install` *as root* from the source tree in the user's home directory — a local privilege-escalation vector (root executing build files from a user-writable path) and a silent-failure risk if the toolchain was missing. The built driver is now snapshotted into a **root-owned cache** (`/var/lib/cs9711-fingerprint`) at install time, and the guard restores it with a **plain file copy** — faster, can't fail to compile, and never executes anything from a user-writable directory. Verified end-to-end in a container (install → cache → simulated update wipe → guard restore).

### Fixed — footgun for users with a *different* fingerprint reader
- **install.sh refuses to silently shadow another reader's driver.** The installer builds a CS9711-only `libfprint` into `/usr/local` that takes precedence over the system one, so running it on a typical laptop (Goodix/Synaptics/ELAN reader) would break that reader. It now **aborts when the CS9711 (`2541:0236`) isn't detected** rather than building blindly — the old non-interactive/GUI path auto-continued. Override with `CS9711_FORCE=1`. README carries a prominent warning.

---

## [1.9.1] - 2026-05-30

### Fixed
- **`uninstall.sh` could un-uninstall itself.** Step 3 reinstalls stock libfprint via the package manager, which fired the new update-guard hook — the guard then saw stock libfprint (no `cs9711`) and rebuilt the patched driver right back. The guard + all package-manager hooks are now removed **first** (new step `[0/4]`), before any package operation.
- **Fedora / dnf5 auto-guard now actually wires up.** v1.9.0 only handled the dnf4 `post-transaction-actions` plugin (absent on Fedora 41+/dnf5), so the #1 complaint — which originated from Fedora users — wasn't auto-fixed there. `install.sh` now detects dnf5, installs `libdnf5-plugin-actions`, and writes `/etc/dnf/libdnf5-plugins/actions.d/cs9711.actions` (`post_transaction:libfprint*:::…`) — verified to fire on a libfprint transaction in a Fedora 44 container. dnf4 path retained as fallback.

### Verified (sanity-check pass)
- Full build matrix re-run **against the released code** — green on Ubuntu 26.04 LTS, Fedora 44, Arch, openSUSE Tumbleweed, Debian 13, Linux Mint 22.
- OpenCV `opencv4`→`opencv5` fallback control flow proven (meson falls through when the first dependency is absent).
- Update-guard detection proven (patched lib with `cs9711` marker → no-op; stock lib → rebuild).

---

## [1.9.0] - 2026-05-30

### Added
- **All-latest-distro compatibility, container-validated.** The driver build-tests green on **Ubuntu 26.04 LTS, Fedora 44, Arch Linux, openSUSE Tumbleweed, Debian 13, and Linux Mint 22** via the new `scripts/distro-build-matrix.sh` (podman). Tracked in `COMPAT-CHECKLIST.md`.
- **Update guard — fixes the #1 community complaint ("a system update broke fingerprint").** `install.sh` deploys `/usr/local/bin/cs9711-update-guard` plus a package-manager post-transaction hook (apt `DPkg::Post-Invoke`, dnf `post-transaction-actions`, pacman `PostTransaction`). After any transaction, if the active `libfprint` no longer carries the `cs9711` driver marker, the guard rebuilds + reinstalls from local source in the background. `uninstall.sh` removes the guard and all hooks.

### Fixed
- **OpenCV 5 build break.** sigfm hardcoded `dependency('opencv4', required: true)`, which fails on distros that have moved to OpenCV 5. `install.sh` and `reinstall.sh` now patch it to prefer `opencv4` and fall back to `opencv5`.
- **Missing build dependencies on minimal / fresh installs** (caught by the container matrix):
  - No explicit C/C++ compiler in the apt/dnf/zypper dep lists — added `build-essential` (apt) and `gcc gcc-c++` (dnf/zypper). Arch's `base-devel` already covered it.
  - **Arch:** missing `glib2-devel` — Arch split the glib dev tools (incl. `glib-mkenums`) into a separate package, so `meson setup` failed.
  - **openSUSE:** wrong package name `pixman-devel` → `libpixman-1-0-devel`.
- **README:** documented the unpowered-USB-hub detection failure (the CS9711 is power-sensitive) and the powered-hub fix.

### Notes
- Container tests validate the **build** path only (deps + meson + compile + cs9711 driver marker present). PAM / desktop-environment behaviour, fingerprint enrollment, and the update-guard's live trigger still need a real machine per distro — tracked in `COMPAT-CHECKLIST.md`.

---

## [1.8.3] - 2026-05-02

### Fixed
- **App icon was blank on every non-GNOME desktop** — the `.desktop` file referenced `Icon=auth-fingerprint-symbolic`, which only ships in the Adwaita icon set. KDE Plasma (Breeze), Cinnamon (Mint-Y), MATE, XFCE, and any user not on Adwaita got the generic blank-page glyph in their app launcher. v1.4.0's claim "Native fingerprint icon — uses auth-fingerprint-symbolic from Adwaita/Yaru" was GNOME-only. Now ships a bundled `assets/cs9711-manager.svg` and the `.desktop` writes `Icon=$SCRIPT_DIR/assets/cs9711-manager.svg` (absolute path) — theme-independent on every freedesktop-compliant DE.
- **GUI auth-locations panel falsely reported "Lock screen: Not configured" / "polkit: Not configured" while fingerprint actually worked** — `get_pam_auth_locations()` did substring-only matching ("common-auth" in content) and never followed `@include` / `include` / `substack` directives, so on Debian/Ubuntu/Mint where `/etc/pam.d/sudo` etc. just say `@include common-auth` (with the actual `pam_fprintd.so` line living in `common-auth`), some contexts were missed. On Kubuntu specifically `/etc/pam.d/polkit-1` and `/etc/pam.d/kscreenlocker` aren't even shipped — those services fall back to PAM defaults — and the old code had no concept of that fallback. Now the function recursively resolves `@include` (Debian/Ubuntu/openSUSE), `include`, and `substack` (Fedora/Arch) directives with cycle detection, lists per-DE PAM files for KDE Plasma / GNOME / Cinnamon / MATE / XFCE / LightDM / LXDM, checks all distro common-auth equivalents (`common-auth`, `system-auth`, `password-auth`, `fingerprint-auth`, `common-auth-pc`), and reports services that have no specific PAM file as enabled when the common stack carries fprintd.

### Tested
- Kubuntu 26.04 LTS / Plasma 6.6.4 — icon renders in app launcher; all four auth contexts (Login, Lock, sudo, polkit) correctly report Enabled.

---

## [1.8.2] - 2026-04-25

### Fixed
- **PAM never enabled on a fresh Debian/Ubuntu install** — `configure_pam()` only edited an existing `pam_fprintd.so` line in `/etc/pam.d/common-auth`, but on a fresh install that line doesn't exist yet (the `libpam-fprintd` profile at `/usr/share/pam-configs/fprintd` ships disabled by default with `Default: no`). The script silently skipped PAM configuration, leaving fingerprint working only for `fprintd-verify` while `sudo`, lock screen, and SDDM never even tried it. The Fedora branch handled this via `authselect enable-feature with-fingerprint`; Ubuntu had no equivalent. Now also runs `pam-auth-update --enable fprintd` and bumps `max-tries=7 timeout=30` directly in the source pam-configs profile so the change survives package upgrades.

### Added
- **Stale-enrollment warning in step 6** — if `fprintd-list` shows an enrolled fingerprint after a fresh driver build, the installer now warns that templates from a previous driver version typically `verify-no-match` against the new build, and prints the exact `fprintd-delete && fprintd-enroll` command to re-enroll cleanly. Doesn't auto-delete (could destroy a working enrollment from the same driver build).

---

## [1.8.1] - 2026-04-12

### Fixed
- **Uninstall left behind folder with root-owned files** — `meson install` runs via sudo, creating root-owned build artifacts in `libfprint-CS9711/builddir/`. The cleanup script's `rm -rf` ran as the normal user and couldn't delete these files, leaving an undeletable folder. Now the pkexec uninstall step removes `builddir/` while it still has root privileges, before the cleanup script runs. CLI `uninstall.sh` also fixed with `sudo rm -rf` on the builddir.

---

## [1.8.0] - 2026-04-12

### Added
- **Self-update from Git** — new "Check for Updates" button in Maintenance section. Shows current version, fetches the latest from GitHub, displays what changed, and offers a one-click update. After updating, the GUI auto-restarts with the new version. No uninstall/reinstall needed — the app runs directly from the git clone.

---

## [1.7.1] - 2026-04-12

### Fixed
- **Delete All always failed after enrollment** — the auto-verify process (`fprintd-verify`, 30s timeout) kept the device claimed, blocking `fprintd-delete`. Now kills any running `fprintd-verify` or `fprintd-enroll` process before attempting delete.
- **Post-enrollment verify confused users** — after 15 touches, the GUI silently started `fprintd-verify` requesting another touch, making users think enrollment wasn't done. Now shows a clear dialog: "Enrollment complete! All 15 touches recorded. Would you like to verify?" with Skip/Verify buttons.

### Removed
- **Full Install button** — running `install.sh` via pkexec failed because the script refuses to run as root. Rebuild Driver covers the use case. Users who need a fresh install should run `./install.sh` from the terminal.

---

## [1.7.0] - 2026-04-12

### Added
- **Comprehensive activity logging** — every user action, system command, and result is logged to `~/.local/share/cs9711-manager/cs9711.log`. Includes GUI events, fprintd operations, pkexec auth, install/uninstall steps, and errors. Log file auto-rotates at 1MB (keeps 3 backups).
- **In-GUI log viewer** — "View Log" button in the Diagnostics section opens a scrollable, read-only text view of the log. Includes a "Copy to clipboard" button for easy bug reporting.
- **Clear Log button** — resets the log for fresh debugging sessions.
- **Install/uninstall script logging** — `install.sh` and `uninstall.sh` also write to the same log file, creating a complete timeline from install through usage to uninstall.

---

## [1.6.2] - 2026-04-12

### Fixed
- **"Delete All" fingerprints failed** — `fprintd-delete` returned "AlreadyInUse" because the scanner device was still claimed from a recent operation (enrollment, verify, or status refresh). The error message was also blank because fprintd puts errors on stdout, not stderr. Now retries up to 3 times with a 1.5s pause between attempts, and shows the actual error message if all retries fail. Delete also runs in a background thread so the UI stays responsive.

---

## [1.6.1] - 2026-04-12

### Fixed
- **Double password prompt on first enrollment** — `fprintd-delete` was called before every enrollment, even the first time when no fingers exist. Both `fprintd-delete` and `fprintd-enroll` trigger polkit authentication, so users saw two back-to-back password dialogs on first use. Now only deletes if the specific finger is already enrolled — single password prompt on first enrollment.

---

## [1.6.0] - 2026-04-12

### Security
- **Shell injection in GUI uninstall** — user/path variables were written directly into temp shell scripts that run as root via pkexec. Now uses `shlex.quote()` to safely escape all values
- **TOCTOU race condition** — uninstall and cleanup scripts used predictable filenames (`/tmp/cs9711-uninstall-now.sh`, `/tmp/cs9711-cleanup.sh`). A local attacker could replace the file between creation and pkexec execution for privilege escalation. Now uses `tempfile.mkstemp()` with randomised names and `0o700` permissions
- **Cleanup script race** — project folder deletion used a fixed 2-second `sleep` delay. Now waits for the GUI process to actually exit (`kill -0` PID check loop) before deleting

### Fixed
- **GUI uninstall was x86_64 and apt-only** — the temp script only removed x86_64 library paths and ran `apt install --reinstall`. On arm64 or Fedora/Arch/openSUSE, the patched driver would remain and stock wouldn't be restored. Now matches the full multi-distro, multi-arch logic from `uninstall.sh`
- **pkexec cancellation ignored** — if the user dismissed the password dialog during uninstall, the GUI continued anyway: removed the desktop shortcut and queued project folder deletion while the driver stayed installed. Now checks the return code and aborts cleanly with "Uninstall cancelled — no changes made"
- **refresh_status() blocked the UI** — called `fprintd-list` and `lsusb` synchronously on the GTK main thread, freezing the window for seconds. Replaced with async `refresh_all()` which runs in a background thread
- **install.sh hung when launched from GUI** — the `read -p "Continue anyway?"` prompt requires a terminal (stdin). When the GUI's "Full Install" button ran install.sh via pkexec, the prompt hung forever. Now detects non-interactive mode (`[ -t 0 ]`) and skips the prompt
- **kill $PPID could kill wrong process** — after install, `kill -9 $PPID` was unconditional. If install.sh was launched from a script, IDE terminal, or the GUI, it would kill the wrong parent. Now checks that the parent is actually a shell (bash/zsh/sh/fish) before killing
- **install.sh and reinstall.sh silently swallowed pipe failures** — used `set -e` but piped to `tail`, masking errors from `apt`/`meson`. Now uses `set -eo pipefail`

### Improved
- **Friendly finger names** — enrolled fingers now display as "Right index finger" instead of fprintd's raw "right-index-finger" format throughout the GUI
- **Uninstall progress bar in correct location** — progress bar is now in the Maintenance section directly below the Uninstall button, not hidden in the Enrollment section

---

## [1.5.1] - 2026-04-12

### Fixed
- **Welcome dialog showed even with fingers enrolled** — was triggered before refresh finished. Now triggers only after refresh confirms no fingers exist
- **Enrollment Status stuck on "Checking..."** — `_apply_refresh` wasn't updating enrollment banner. Now properly shows "Enrolled: N finger(s)" or "Not Enrolled"
- **Re-enrolling same finger failed** — fprintd-enroll fails if finger already enrolled. Now auto-deletes old enrollment for that finger before re-enrolling
- **Enrollment progress text** — shows "Touch the scanner NOW" prominently during enrollment

### Added
- **Uninstall progress bar** — shows step-by-step progress: removing fingerprints → removing driver → cleaning up → removing project files → closing GUI
- Uninstall shows 100% and "closing in 3 seconds" before auto-closing

---

## [1.5.0] - 2026-04-12

### Added
- **First-launch enrollment prompt** — when GUI opens with no enrolled fingers, shows a welcome dialog explaining what's about to happen, which finger will be scanned, and how to change it for left-handers
- **Apply PAM shows "Applying..." spinner** — button disables and shows progress text while running
- **Password requirement note** — "Requires your login password" shown next to Apply PAM button so users aren't surprised by the password prompt after just scanning their finger

### Fixed
- **Multiple instances bug** — clicking the app icon while GUI is open no longer launches a second instance. Uses GApplication single-instance to bring existing window to front
- **Terminal stays in project folder** — script can't cd parent shell, so now shows "Run 'cd ~' or close this terminal" message
- **GUI uninstall failing** — multi-line pkexec string was breaking. Now uses temp script file

---

## [1.4.1] - 2026-04-12

### Changed
- **Uninstall is now full cleanup** — "Uninstall Everything" removes driver, fingerprints, GUI, desktop shortcut, AND the entire project folder. System returns to a state as if it was never installed. GUI auto-closes after uninstall.

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
