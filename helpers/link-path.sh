# Shared by install.sh and reinstall.sh.
#
# WHY THIS EXISTS (issue #2, second half — reported by @josepcarles on CachyOS):
# meson's default prefix is /usr/local, so the patched libfprint installs to
# /usr/local/lib{,64}. That only shadows the distro's own libfprint if that
# directory is in the dynamic linker's search path.
#
#   openSUSE/Fedora/Debian: /etc/ld.so.conf lists /usr/local/lib{,64} FIRST,
#                           so our build wins and everything works.
#   Arch/CachyOS:           /etc/ld.so.conf only carries an include line, and
#                           glibc's built-in search covers /usr/lib and /lib
#                           but NOT /usr/local/lib. Our build is installed to a
#                           place the linker never looks at, the stock libfprint
#                           keeps winning, and fprintd reports no devices while
#                           lsusb still shows the scanner.
#
# The give-away in a bug report: `ldd` on the resolved libfprint shows NO
# OpenCV libraries. The CS9711 fork's sigfm matcher is built against OpenCV, so
# a resolved library without OpenCV cannot be our build.
#
# Fix: detect it, then add the real install libdir to /etc/ld.so.conf.d/ (which
# is read before ldconfig auto-appends /usr/lib), refresh the cache and
# re-verify. Reversible — uninstall.sh removes the file.
#
# We deliberately do NOT install with --prefix=/usr: that overwrites a
# distro-owned file, which the next package update clobbers anyway.

CS9711_LDCONF="/etc/ld.so.conf.d/00-cs9711-local.conf"

# Absolute path so this works from package-manager hooks with a minimal PATH.
_ldconfig() { PATH="/usr/sbin:/sbin:$PATH" ldconfig "$@"; }

# Path of the libfprint the dynamic linker actually resolves (empty if none).
cs9711_resolved_lib() {
    _ldconfig -p 2>/dev/null | awk '/libfprint-2\.so\.2 /{print $NF; exit}'
}

# True when the resolved libfprint is OUR build (carries the cs9711 driver).
cs9711_resolved_is_ours() {
    local r; r=$(cs9711_resolved_lib)
    [ -n "$r" ] && [ -e "$r" ] && grep -aq cs9711 "$r" 2>/dev/null
}

# Directory meson actually installed the library into — asked of meson rather
# than inferred from ldconfig, because on Arch ldconfig resolves the STOCK lib
# and the old code cached that by mistake.
cs9711_install_libdir() {
    local builddir="${1:-builddir}" prefix libdir
    prefix=$(meson introspect --buildoptions "$builddir" 2>/dev/null \
        | tr ',' '\n' | grep -A2 '"name": "prefix"' | grep '"value"' \
        | head -1 | sed 's/.*"value": *"//; s/".*//')
    libdir=$(meson introspect --buildoptions "$builddir" 2>/dev/null \
        | tr ',' '\n' | grep -A2 '"name": "libdir"' | grep '"value"' \
        | head -1 | sed 's/.*"value": *"//; s/".*//')
    [ -n "$prefix" ] || prefix=/usr/local
    if [ -n "$libdir" ]; then
        echo "$prefix/$libdir"
        return
    fi
    # Fallback: whichever standard libdir under the prefix actually holds it
    for d in "$prefix/lib64" "$prefix/lib"; do
        [ -e "$d/libfprint-2.so.2" ] && { echo "$d"; return; }
    done
    echo "$prefix/lib"
}

# Make our install directory win over the distro's libfprint. Returns 0 when
# the resolved library is ours by the end, 1 when it still is not.
cs9711_ensure_link_path() {
    local libdir="$1"
    _ldconfig 2>/dev/null || true
    if cs9711_resolved_is_ours; then
        return 0
    fi
    [ -n "$libdir" ] && [ -e "$libdir/libfprint-2.so.2" ] || return 1
    printf '# Added by chipsailing-cs9711-fingerprint-linux (issue #2).\n# Puts the patched libfprint ahead of the distro copy on distros that do\n# not carry /usr/local in the default linker path (Arch/CachyOS).\n# Removed by uninstall.sh.\n%s\n' \
        "$libdir" | sudo tee "$CS9711_LDCONF" >/dev/null
    sudo chmod 644 "$CS9711_LDCONF"
    _ldconfig 2>/dev/null || true
    cs9711_resolved_is_ours
}
