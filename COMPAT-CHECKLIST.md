# CS9711 — All-Latest-Distro Compatibility Checklist

Living tracker for making the installer build and run cleanly on every current
mainstream Linux distro, and for closing the user-reported issues collected from
the community (GitHub `ddlsmurf#7`, Linux Mint forum threads `t=451286` / `t=451322`).

> The published mfaruk.com article (post_id 1, *"Making a Cheap USB Fingerprint
> Scanner Work on Linux — CS9711"*) and this Git repo move together as the
> reference, but neither is a frozen constraint — fresh edits, restructures and
> version bumps are fine. Keep the documented `git clone … && ./install.sh`
> entrypoint working so the article's instructions never break.

---

## Verified facts (on ms7e41 / Kubuntu 26.04, 2026-05-30)

| Fact | Value | Why it matters |
|---|---|---|
| Fork base libfprint | **1.94.10** | System ships **1.95.1+tod1** — two minors ahead. We sidestep by installing a *full* patched tree to `/usr/local`. |
| Install prefix | `/usr/local/lib/x86_64-linux-gnu/` (meson default, no `--prefix`) | Confirmed: `ld.so` resolves `/usr/local` **before** `/usr/lib`, so the patched lib wins. |
| Driver marker | patched lib contains `cs9711` ×19; stock has **0** | Basis of the update-guard's breakage detection — prefix/device independent. |
| sigfm dep | `dependency('opencv4', required: true)` (hardcoded) | Breaks the build the moment a distro moves to **OpenCV 5**. Now patched to fall back. |

---

## Reported complaints → status

| # | Complaint (source) | Fix | Status |
|---|---|---|---|
| 1 | System update overwrites/shadows libfprint → breaks (ddlsmurf#7: Ferlinuxdebian, nickthaskater) | `cs9711-update-guard` + apt/dnf/pacman post-transaction hooks; rebuilds in background when active libfprint loses the `cs9711` marker | ✅ Implemented — ⏳ needs real-upgrade test per distro |
| 2 | `verify-no-match` — enrolls, never matches (Mint: Ammonsul) | Uses correct archeYR/sigfm fork; install + reinstall warn on stale enrollment | ✅ Already handled |
| 3 | Device not detected / USB power (Mint: oschyns) | `lsusb` pre-flight + keyboard-passthrough warning | 🟡 Add explicit "unpowered hub" note to README |
| 4 | Wrong fork / wrong USB-ID confusion (Mint: yossarian_yon; ddlsmurf redirect) | Installer hardcodes archeYR fork + `2541:0236` | ✅ Handled by construction |
| 5 | Fedora GNOME polkit dialog needs custom `/etc/pam.d/polkit-1` (ddlsmurf#7: Aryan-Techie) | `authselect with-fingerprint` should cover it via system-auth include | ❓ Verify on Fedora GNOME; do **not** ship a blind PAM edit |

---

## Target distros & test status

| Distro (latest) | Build | Runtime (PAM/DE) | Notes |
|---|---|---|---|
| Kubuntu 26.04 / Plasma 6.6.4 | ✅ real HW | ✅ real HW | Reference platform |
| Ubuntu 26.04 LTS | ✅ container (2026-05-30) | ❌ | gdm-password / gdm-fingerprint |
| Linux Mint 22 (+ Fingwit) | ✅ container (2026-05-30) | ❌ | Ubuntu 24.04 base; Fingwit XApp detection |
| Fedora 44 | ✅ container (2026-05-30) | ❌ | OpenCV fallback held; dnf5 hook + polkit pending |
| Debian 13 (Trixie) | ✅ container (2026-05-30) | ❌ | same apt path |
| openSUSE Tumbleweed | ✅ container (2026-05-30) | ❌ | Leap 16 not yet tested; no auto-hook |
| Arch / Manjaro | ✅ container (2026-05-30) | ❌ | rolling; pacman hook added |

---

## Checklist

### A. Build toolchain (highest priority — hard build-breaks)
- [x] OpenCV version-flexible: `opencv4` → fall back to `opencv5` (install.sh + reinstall.sh)
- [x] Explicit C/C++ compiler in dep lists (`build-essential` apt; `gcc gcc-c++` dnf/zypper; Arch via `base-devel`)
- [x] Container build-test on **Fedora 44** (OpenCV + GCC15) — PASS
- [x] Container build-test on **Arch, openSUSE Tumbleweed, Ubuntu 26.04, Debian 13, Mint 22** — all PASS
- [x] **Bleeding-edge** build-test PASS (2026-05-30): **Fedora Rawhide (F45 prerelease), Debian sid (forky/sid), Ubuntu devel (Resolute Raccoon)** — newest GCC/meson, no breakage. OpenCV 5 still in no distro (Rawhide = opencv 4.13.0), so the `opencv5` fallback remains forward-looking only
- [x] Confirmed fork meson option names valid on every distro's meson (all configured cleanly)
- [ ] Decide libfprint-drift policy (pin a known-good fork commit vs detect+warn) — fork still on 1.94.10 while distros ship 1.95.x

### B. Package-name drift (verified via container builds)
- [x] apt (26.04/Mint/Debian 13): build deps confirmed (added `build-essential`)
- [x] dnf (Fedora 44): build deps confirmed (added `gcc gcc-c++`)
- [x] pacman (Arch): added `glib2-devel`
- [x] zypper (Tumbleweed): added `gcc gcc-c++`; `pixman-devel` → `libpixman-1-0-devel`
- [ ] GUI runtime deps (gtk4 / libadwaita / typelibs) still only checked on Kubuntu — verify per distro at runtime (step 8 of install.sh)

### C. Update-survival (closes complaint #1)
- [x] `cs9711-update-guard` helper — restores the driver from a **root-owned cache** (`/var/lib/cs9711-fingerprint`) when the `cs9711` marker is missing from the active lib. Plain file copy, **no build-as-root** (v1.9.2 hardening — closed a local-privesc vector). Container-verified end-to-end.
- [x] APT hook (`/etc/apt/apt.conf.d/99-cs9711-guard`)
- [x] pacman hook (`/etc/pacman.d/hooks/cs9711.hook`)
- [x] dnf4 post-transaction-action (`/etc/dnf/plugins/post-transaction-actions.d/cs9711.action`)
- [x] **dnf5 (Fedora 41+) actions plugin** — `install.sh` installs `libdnf5-plugin-actions` and writes `actions.d/cs9711.actions`; **verified firing** on a libfprint transaction in a Fedora 44 container (v1.9.1)
- [x] uninstall removes guard + all hooks **before** the stock-libfprint reinstall (fixed v1.9.1 — was re-triggering the guard)
- [ ] Real test: `apt/dnf/pacman upgrade` that bumps libfprint on a live machine → guard auto-recovers (container fired the hook; full rebuild path still real-machine-only)
- [ ] Assumption to revisit: OpenCV 5's pkg-config name is `opencv5` (matches the `opencv4` convention) — confirm when a distro actually ships OpenCV 5

### G. End-user-perspective review (v1.9.2)
- [x] **Shadow-a-different-reader footgun** — installs a CS9711-only libfprint to `/usr/local`; aborts now if `2541:0236` not detected (`CS9711_FORCE=1` to override) + README warning.
- [x] **Guard ran build-as-root from user home** (local privesc) — replaced with root-owned-cache restore (plain copy).
- [ ] **`install.sh` force-closes the user's terminal** (`kill -9 $PPID` at the end). Aggressive UX from a user's view — consider replacing with a printed "you can close this terminal" message. (Flagged, not changed — deliberate GUI-autolaunch design; Mahmud's call.)
- [ ] Guard restore can't help if a libfprint **SONAME bump** makes the cached 1.94.10 `.so` ABI-incompatible with a newer fprintd — same limitation as the fork-drift item; tracked under A.
- [ ] Immutable/atomic distros (Silverblue, Bazzite, SteamOS) — `/usr/local` writability + `ldconfig` behaviour unverified.

### D. PAM / desktop-environment auth
- [ ] Fedora 44 GNOME: confirm `authselect with-fingerprint` lights up the polkit password dialog (else add reversible polkit-1 stanza)
- [ ] Ubuntu 26.04 GNOME: verify gdm-password / gdm-fingerprint
- [ ] Mint: verify driver registers with **Fingwit** + Cinnamon screensaver/lightdm
- [ ] openSUSE: `common-auth-pc`

### E. Runtime / detection
- [ ] `fprintd-list` name-grep (`CS9711\|9711\|chipsailing`) still matches on fprintd 1.95.x
- [ ] `cs9711-manager.py` vs libadwaita version shipped by each LTS (no deprecated widgets)
- [ ] README: add powered-hub note (complaint #3)

### F. Non-issues (don't spend effort)
- Secure Boot — N/A (libfprint is userspace, no kernel module)

---

## How to run the container build matrix
Requires podman (rootless):

```
sudo apt install -y podman uidmap
bash scripts/distro-build-matrix.sh    # (to be added) builds the fork in fedora:44, archlinux, opensuse/tumbleweed, ubuntu:26.04
```

Each container only validates the **build** path (deps + meson + compile) — fingerprint
hardware and PAM/DE behaviour still need a real machine per the runtime rows above.
