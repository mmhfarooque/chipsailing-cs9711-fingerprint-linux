# Shared by install.sh, reinstall.sh, build-deb.sh and build-in-container.sh.
# PKGBUILD and the RPM spec carry an inline copy of the same seds (they build
# from the bare fork checkout and cannot source repo helpers) — keep in sync.
#
# Make the sigfm OpenCV dependency survive a distro OpenCV major bump
# (issue #2 — CachyOS moving 4.13 -> 5.0 stranded the driver):
#   pkg-config opencv4 -> opencv5 -> opencv, then CMake's OpenCV as the last
#   resort — Arch-family ships CMake configs even when no .pc file exists.
# Idempotent: the cmake fallback line is the done-marker. Trees still carrying
# the v2.0.x two-step patch (opencv4 -> opencv5 hard-required) are upgraded
# in place, so an existing install's rebuild picks this up too.
patch_opencv_flex() {
    local mf="$1"
    [ -f "$mf" ] || return 0
    grep -q "method: 'cmake'" "$mf" && return 0
    # Sequential single-name lookups on purpose — meson's multi-name
    # dependency() needs 0.60 and the fork still declares >= 0.59.
    if grep -q "dependency('opencv4', required: true)" "$mf"; then
        # pristine fork: single hard-required opencv4 line
        sed -i "s|opencv = dependency('opencv4', required: true)|opencv = dependency('opencv4', required: false)\nif not opencv.found()\n  opencv = dependency('opencv5', required: false)\nendif\nif not opencv.found()\n  opencv = dependency('opencv', required: false)\nendif\nif not opencv.found()\n  opencv = dependency('OpenCV', method: 'cmake', required: true)\nendif|" "$mf"
    elif grep -q "dependency('opencv5', required: true)" "$mf"; then
        # v2.0.x flexible patch present: extend its terminal opencv5 line
        sed -i "s|opencv = dependency('opencv5', required: true)|opencv = dependency('opencv5', required: false)\nendif\nif not opencv.found()\n  opencv = dependency('opencv', required: false)\nendif\nif not opencv.found()\n  opencv = dependency('OpenCV', method: 'cmake', required: true)|" "$mf"
    fi
}
