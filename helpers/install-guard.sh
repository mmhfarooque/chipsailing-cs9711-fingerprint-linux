# Shared by install.sh and reinstall.sh — installs/refreshes the update guard
# and wires the package-manager hooks. Idempotent. Since v2.1.0 the hooks also
# fire on OpenCV transactions, because an OpenCV major bump strands the driver
# (issue #2) exactly like a libfprint update does.
#
# Uses sudo for the writes — under pkexec we are already root, so no prompt.

# Best-effort package-family detection for callers (reinstall.sh) that don't
# run the installer's full distro detection.
detect_pkg_family() {
    if command -v pacman >/dev/null 2>&1; then echo pacman
    elif command -v zypper >/dev/null 2>&1; then echo zypper
    elif command -v dnf5 >/dev/null 2>&1 || command -v dnf >/dev/null 2>&1; then echo dnf
    elif command -v apt-get >/dev/null 2>&1; then echo apt
    else echo unknown
    fi
}

install_update_guard_and_hooks() {
    local family="$1" logf="$2"
    local helper_dir guard_src guard_bin
    helper_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    guard_src="$helper_dir/cs9711-update-guard"
    guard_bin="/usr/local/bin/cs9711-update-guard"

    if [ ! -f "$guard_src" ]; then
        echo "  [WARN] guard source missing ($guard_src) — skipping guard refresh"
        return 0
    fi
    sudo install -m 0755 "$guard_src" "$guard_bin"
    sudo sed -i "s|__LOG__|$logf|g" "$guard_bin"

    case "$family" in
        apt)
            echo 'DPkg::Post-Invoke { "/usr/local/bin/cs9711-update-guard || true"; };' \
                | sudo tee /etc/apt/apt.conf.d/99-cs9711-guard >/dev/null
            ;;
        dnf)
            if command -v dnf5 >/dev/null 2>&1 || [ -d /etc/dnf/libdnf5-plugins ]; then
                sudo dnf install -y libdnf5-plugin-actions >/dev/null 2>&1 || true
                sudo mkdir -p /etc/dnf/libdnf5-plugins/actions.d
                printf '%s\n' \
                    'post_transaction:libfprint*:::/usr/local/bin/cs9711-update-guard' \
                    'post_transaction:opencv*:::/usr/local/bin/cs9711-update-guard' \
                    | sudo tee /etc/dnf/libdnf5-plugins/actions.d/cs9711.actions >/dev/null
            elif [ -d /etc/dnf/plugins/post-transaction-actions.d ] \
                    || sudo dnf install -y python3-dnf-plugin-post-transaction-actions >/dev/null 2>&1; then
                sudo mkdir -p /etc/dnf/plugins/post-transaction-actions.d
                printf '%s\n' \
                    'libfprint*:any:/usr/local/bin/cs9711-update-guard' \
                    'opencv*:any:/usr/local/bin/cs9711-update-guard' \
                    | sudo tee /etc/dnf/plugins/post-transaction-actions.d/cs9711.action >/dev/null
            fi
            ;;
        pacman)
            sudo mkdir -p /etc/pacman.d/hooks 2>/dev/null || true
            sudo tee /etc/pacman.d/hooks/cs9711.hook >/dev/null << 'PHOOK'
[Trigger]
Operation = Upgrade
Type = Package
Target = libfprint

[Trigger]
Operation = Upgrade
Operation = Remove
Type = Package
Target = opencv

[Action]
Description = Checking CS9711 fingerprint driver health...
When = PostTransaction
Exec = /usr/local/bin/cs9711-update-guard
PHOOK
            ;;
        *)
            : # zypper/unknown: guard binary refreshed; no auto-hook available
            ;;
    esac
}
