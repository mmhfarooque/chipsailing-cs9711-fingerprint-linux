# Chipsailing CS9711 Fingerprint Scanner — Linux Driver Installer

One-command installer for the **Chipsailing CS9711** USB fingerprint scanner on Ubuntu Linux.

Stock Ubuntu `libfprint` does **not** support this chip. This project automates the entire setup: cloning the community driver, applying patches, building, installing, and configuring PAM — so your fingerprint works for login, lock screen, and sudo.

## Supported Hardware

| Detail | Value |
|--------|-------|
| **Chip** | Chipsailing CS9711 |
| **USB ID** | `2541:0236` |
| **Form factor** | USB dongle / integrated sensor |
| **Matching algorithm** | sigfm (optimised for small sensors) |
| **Enrollment** | 15 touches per finger |

To check if you have this device:

```bash
lsusb | grep 2541:0236
```

## Tested On

- Ubuntu 24.04 LTS (Noble Numbat)
- Ubuntu 26.04 LTS (Resolute Reedbuck)
- Should work on any Debian-based distro with `libfprint` and `fprintd`

## Quick Start

```bash
git clone https://github.com/mmhfarooque/chipsailing-cs9711-fingerprint-linux.git
cd chipsailing-cs9711-fingerprint-linux
chmod +x install.sh
./install.sh
```

The installer will:

1. Install all build dependencies (`meson`, `libfprint-2-dev`, `libgusb-dev`, etc.)
2. Clone the [archeYR/libfprint-CS9711](https://github.com/archeYR/libfprint-CS9711) community driver
3. Apply the **1500ms retry delay patch** (see below)
4. Build and install the patched `libfprint`
5. Configure PAM with `max-tries=7 timeout=30`
6. Verify the scanner is detected

Then enroll your fingerprint:

```bash
fprintd-enroll          # 15 touches required
fprintd-verify          # test it
```

## After System Updates

When `apt` updates the `libfprint-2-2` package, it overwrites the patched library with stock. Just run:

```bash
./reinstall.sh
```

This rebuilds from the existing local source — no re-download needed.

## The 1500ms Retry Delay Patch

The upstream driver uses a 250ms delay between scan retries. This is too fast — the scanner burns through all retry attempts before you can reposition your finger.

This project patches `CS9711_DEFAULT_RESET_SLEEP` from `250` to `1500` (milliseconds), giving you a comfortable pause between scans.

The patch is in `patches/cs9711-retry-delay-1500ms.patch`.

## PAM Configuration

The installer sets `/etc/pam.d/common-auth` to:

```
auth sufficient pam_fprintd.so max-tries=7 timeout=30
```

- **max-tries=7** — 7 fingerprint attempts before falling back to password (default is 1)
- **timeout=30** — 30-second window for all attempts (default is 10)

## What It Enables

- Lock screen unlock via fingerprint
- `sudo` authentication (fingerprint prompt before password)
- Login screen fingerprint auth
- All via `libpam-fprintd`

## Optional: Auto-Unlock GNOME Keyring

By default, GNOME Keyring requires your password to unlock (fingerprint login skips it). To set an empty keyring password so it auto-unlocks:

```bash
python3 helpers/set-empty-keyring-password.py
```

## File Structure

```
.
├── install.sh              # Full installer (fresh install)
├── reinstall.sh            # Quick rebuild (after system updates)
├── uninstall.sh            # Remove driver and restore stock libfprint
├── patches/
│   └── cs9711-retry-delay-1500ms.patch   # The retry delay fix
├── helpers/
│   └── set-empty-keyring-password.py     # GNOME Keyring auto-unlock
└── README.md
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No devices available` | Check USB connection. Run `sudo ldconfig`. Run `lsusb \| grep 2541`. |
| `verify-no-match` | Old enrollment data. Run `fprintd-delete $(whoami) && fprintd-enroll`. |
| System update broke it | Run `./reinstall.sh`. |
| Scanner not detected | USB passthrough keyboards only work when wired (not Bluetooth). |
| Burns through retries | Check patch: `grep CS9711_DEFAULT_RESET_SLEEP libfprint-CS9711/libfprint/drivers/cs9711/cs9711.c` should show `1500`. |

## Useful Commands

```bash
fprintd-enroll                        # Enroll default finger (right index)
fprintd-enroll -f left-index-finger   # Enroll specific finger
fprintd-list $(whoami)                # List enrolled fingers
fprintd-verify                        # Test fingerprint
fprintd-delete $(whoami)              # Delete all enrolled fingerprints
```

## Credits

- **Community driver:** [archeYR/libfprint-CS9711](https://github.com/archeYR/libfprint-CS9711) (maintained fork, originally by [ddlsmurf](https://github.com/ddlsmurf))
- **Retry delay patch & Ubuntu integration:** [mmhfarooque](https://github.com/mmhfarooque)

## License

The libfprint driver is licensed under LGPL-2.1 (same as upstream libfprint). The installer scripts in this repo are MIT licensed.
