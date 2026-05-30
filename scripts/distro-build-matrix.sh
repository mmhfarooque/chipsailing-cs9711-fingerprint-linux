#!/bin/bash
# ============================================================================
# Run build-in-container.sh across the latest distro families via podman.
# Validates the BUILD path (deps + patches + meson compile) only.
# Usage:  bash scripts/distro-build-matrix.sh           # all images
#         bash scripts/distro-build-matrix.sh fedora     # one image by keyword
# Requires: podman (rootless ok).  sudo apt install -y podman uidmap
# ============================================================================
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"

# image | friendly label
IMAGES=(
    "ubuntu:26.04|Ubuntu 26.04 LTS"
    "fedora:44|Fedora 44"
    "archlinux:latest|Arch Linux"
    "opensuse/tumbleweed|openSUSE Tumbleweed"
    "debian:trixie|Debian 13"
    "docker.io/linuxmintd/mint22-amd64|Linux Mint 22"
)

FILTER="${1:-}"
PASS=(); FAIL=()

for entry in "${IMAGES[@]}"; do
    IMG="${entry%%|*}"; LABEL="${entry##*|}"
    [ -n "$FILTER" ] && [[ "$IMG" != *"$FILTER"* ]] && continue
    echo ""
    echo "================================================================"
    echo "  $LABEL   ($IMG)"
    echo "================================================================"
    if podman run --rm \
        -v "$REPO:/src:ro" \
        "$IMG" \
        bash /src/scripts/build-in-container.sh; then
        PASS+=("$LABEL")
    else
        FAIL+=("$LABEL  (exit $?)")
    fi
done

echo ""
echo "================== SUMMARY =================="
printf '  PASS: %s\n' "${PASS[@]:-(none)}"
printf '  FAIL: %s\n' "${FAIL[@]:-(none)}"
[ ${#FAIL[@]} -eq 0 ]
