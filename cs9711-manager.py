#!/usr/bin/env python3
"""
CS9711 Fingerprint Manager — GUI for Chipsailing CS9711 fingerprint scanner.

Controls: retry delay, PAM attempts/timeout, auth locations, enrollment,
driver maintenance. Uses GTK4 + libadwaita for native GNOME look.
"""

import gi
import logging
import os
import re
import shlex
import signal
import subprocess
import tempfile
import threading
import time

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

APP_ID = "com.github.mmhfarooque.cs9711-manager"
APP_AUTHOR = "Mahmud Farooque"
APP_AUTHOR_EMAIL = "farooque7@gmail.com"
AUTHOR_URL = "https://github.com/mmhfarooque"
PROJECT_URL = "https://github.com/mmhfarooque/chipsailing-cs9711-fingerprint-linux"
USB_ID = "2541:0236"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DRIVER_DIR = os.path.join(SCRIPT_DIR, "libfprint-CS9711")
CS9711_SRC = os.path.join(DRIVER_DIR, "libfprint", "drivers", "cs9711", "cs9711.c")

# ============================================================================
# Logging — all events written to ~/.local/share/cs9711-manager/cs9711.log
# ============================================================================

LOG_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "cs9711-manager")
LOG_FILE = os.path.join(LOG_DIR, "cs9711.log")
os.makedirs(LOG_DIR, exist_ok=True)

log = logging.getLogger("cs9711")
log.setLevel(logging.DEBUG)

# File handler — keeps last 3 logs, 1MB each
from logging.handlers import RotatingFileHandler
_fh = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3)
_fh.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
log.addHandler(_fh)

# Also log to stderr for terminal debugging
_sh = logging.StreamHandler()
_sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
_sh.setLevel(logging.INFO)
log.addHandler(_sh)

def get_app_version():
    """Read version from VERSION file."""
    try:
        with open(os.path.join(SCRIPT_DIR, "VERSION")) as f:
            return f.read().strip()
    except FileNotFoundError:
        return "dev"

APP_VERSION = get_app_version()

PAM_DIR = "/etc/pam.d"
# Vendor PAM dir: on modern openSUSE/Fedora, service files (sddm, sudo, polkit-1,
# kde-fingerprint, ...) ship here and /etc/pam.d holds only admin overrides.
# PAM searches /etc/pam.d first, then this. We mirror that so detection and the
# per-service toggles see the real files, not just the (often empty) /etc copies.
VENDOR_PAM_DIR = "/usr/lib/pam.d"

# Marker stamped into any /etc/pam.d override the GUI creates, so we can safely
# identify and revert our own files without clobbering admin-authored ones.
PAM_MARK = "# cs9711-managed"


def _pam_path(name):
    """Resolve a PAM service name to its active file: /etc/pam.d wins, else vendor."""
    if name.startswith("/"):
        return name
    etc = os.path.join(PAM_DIR, name)
    if os.path.exists(etc):
        return etc
    vendor = os.path.join(VENDOR_PAM_DIR, name)
    return vendor if os.path.exists(vendor) else etc

# Distro-wide common authentication stack files. Used by get_pam_settings() to
# locate the file holding the active pam_fprintd.so line, and by the auth-
# location heuristic to detect services that fall back to PAM defaults.
PAM_FILES = [
    "/etc/pam.d/common-auth",       # Debian, Ubuntu, Mint, Pop!_OS
    "/etc/pam.d/system-auth",       # Fedora, RHEL, CentOS, Arch, Manjaro
    "/etc/pam.d/fingerprint-auth",  # Fedora alternative
    "/etc/pam.d/password-auth",     # Fedora alternative
    "/etc/pam.d/common-auth-pc",    # openSUSE
]

# Bare filenames (relative to /etc/pam.d/) of the same set, for include-resolution.
DISTRO_COMMON_AUTH_FILES = [os.path.basename(p) for p in PAM_FILES]

# PAM service files to check per auth context, covering the major
# desktop environments and login managers across popular distros.
SERVICE_PAM_FILES = {
    "Login screen": [
        "sddm",                  # KDE
        "gdm-password",          # GNOME
        "gdm-fingerprint",       # GNOME (fingerprint-specific)
        "lightdm",               # XFCE / Cinnamon / Mint default
        "lxdm",                  # LXDE
        "login",                 # TTY login fallback
    ],
    "Lock screen": [
        "kde-fingerprint",       # KDE Plasma 6 — dedicated fingerprint stack (native)
        "kscreenlocker",         # KDE Plasma 6
        "kscreenlocker_greet",   # KDE Plasma 6 (alt)
        "kde",                   # KDE generic
        "gdm-password",          # GNOME (also handles unlock)
        "cinnamon-screensaver",  # Cinnamon (Mint)
        "mate-screensaver",      # MATE
        "xfce4-screensaver",     # XFCE
        "light-locker",          # LightDM lock helper
    ],
    "sudo": ["sudo"],
    "polkit": ["polkit-1", "polkit-1-kde-1"],
}

FINGERS = [
    ("right-index-finger", "Right index finger"),
    ("left-index-finger", "Left index finger"),
    ("right-thumb", "Right thumb"),
    ("left-thumb", "Left thumb"),
    ("right-middle-finger", "Right middle finger"),
    ("left-middle-finger", "Left middle finger"),
    ("right-ring-finger", "Right ring finger"),
    ("left-ring-finger", "Left ring finger"),
    ("right-little-finger", "Right little finger"),
    ("left-little-finger", "Left little finger"),
]

FINGER_NAMES = {fid: fname for fid, fname in FINGERS}

# ============================================================================
# Styling
# ============================================================================
# Deliberately theme-agnostic: no hardcoded colours, only alpha over
# currentColor, so the same sheet reads correctly under GNOME's Adwaita, KDE
# Plasma's Breeze, Cinnamon, XFCE and in both light and dark variants.
_CSS = b"""
.cs-pill {
  padding: 2px 10px;
  border-radius: 999px;
  background: alpha(currentColor, .10);
}
.cs-hero {
  padding: 6px 2px;
}
.cs-hero-icon {
  min-width: 52px;
  min-height: 52px;
}
"""


def install_css():
    """Attach the stylesheet once per display."""
    display = Gdk.Display.get_default()
    if display is None or getattr(install_css, "_done", False):
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(_CSS)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    install_css._done = True


def pick_icon(*names):
    """First icon name that the running icon theme actually has.

    Symbolic names are NOT portable: `auth-fingerprint-symbolic` exists in
    Adwaita but not in KDE Breeze, where it renders as the broken-image glyph
    (the same trap documented in cs9711-manager.desktop). Callers pass a
    preference list ending in something universally present.
    """
    display = Gdk.Display.get_default()
    if display is not None:
        theme = Gtk.IconTheme.get_for_display(display)
        for n in names:
            if theme.has_icon(n):
                return n
    return names[-1]


# Resolved once: the app's own identity icon, and the state icons.
def icon_fingerprint():
    return pick_icon("auth-fingerprint-symbolic", "fingerprint-symbolic",
                     "fingerprint", "dialog-password-symbolic", "dialog-password")


def icon_warning():
    return pick_icon("dialog-warning-symbolic", "dialog-warning")


def status_pill(label):
    """Small rounded status chip. Colour is carried by a libadwaita style
    class (.success/.warning/.error/.dim-label) set at refresh time."""
    lbl = Gtk.Label(label=label, css_classes=["cs-pill", "caption", "dim-label"])
    lbl.set_valign(Gtk.Align.CENTER)
    return lbl


def set_pill(lbl, text, level):
    """level: ok | warn | bad | idle"""
    lbl.set_label(text)
    for c in ("success", "warning", "error", "dim-label"):
        lbl.remove_css_class(c)
    lbl.add_css_class(
        {"ok": "success", "warn": "warning", "bad": "error"}.get(level, "dim-label")
    )


# ============================================================================
# Helper functions — read system state
# ============================================================================


def run_cmd(cmd, timeout=10):
    """Run a command and return (returncode, stdout, stderr)."""
    cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
    log.debug(f"CMD: {cmd_str} (timeout={timeout}s)")
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if r.returncode != 0:
            log.warning(f"CMD FAILED (rc={r.returncode}): {cmd_str} | stdout={r.stdout.strip()!r} | stderr={r.stderr.strip()!r}")
        else:
            log.debug(f"CMD OK: {cmd_str}")
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        log.error(f"CMD TIMEOUT ({timeout}s): {cmd_str}")
        return 1, "", f"Command timed out after {timeout}s"
    except FileNotFoundError:
        log.error(f"CMD NOT FOUND: {cmd_str}")
        return 1, "", f"Command not found: {cmd[0]}"


def is_scanner_connected():
    rc, out, _ = run_cmd(["lsusb"])
    connected = USB_ID in out if rc == 0 else False
    log.debug(f"Scanner connected: {connected}")
    return connected


def is_driver_installed():
    rc, out, err = run_cmd(["fprintd-list", os.environ.get("USER", "nobody")])
    combined = f"{out} {err}".lower()
    installed = "cs9711" in combined or "9711" in combined or "chipsailing" in combined
    log.debug(f"Driver installed: {installed}")
    return installed


def driver_health():
    """Loadability check on the active libfprint: ('ok'|'broken'|'absent', detail).

    'broken' means the resolved library exists but carries unresolvable
    dependencies — the classic cause is a distro OpenCV major upgrade (4 -> 5)
    removing the sonames the driver was built against (issue #2). fprintd then
    reports no device while lsusb still sees the scanner, which used to read
    as a USB problem. detail = the missing library names.
    """
    rc, out, _ = run_cmd(
        ["sh", "-c", "ldconfig -p 2>/dev/null | awk '/libfprint-2\\.so\\.2 /{print $NF; exit}'"]
    )
    path = out.strip()
    if not path or not os.path.exists(path):
        return "absent", ""
    rc, out, err = run_cmd(["ldd", path], timeout=15)
    missing = sorted({ln.split()[0] for ln in out.splitlines() if "not found" in ln})
    if missing:
        log.warning(f"driver_health: {path} unloadable — missing {missing}")
        return "broken", ", ".join(missing)
    return "ok", path


def get_enrolled_fingers():
    rc, out, err = run_cmd(["fprintd-list", os.environ.get("USER", "nobody")])
    fingers = []
    for line in (out + "\n" + err).splitlines():
        line = line.strip()
        if line.startswith("- #"):
            # Format: " - #0: right-index-finger"
            match = re.search(r":\s*(.+)", line)
            if match:
                fingers.append(match.group(1).strip())
        elif "finger" in line.lower() and ":" in line and "enrolled" not in line.lower():
            match = re.search(r"(\w+-\w+-finger|\w+-thumb)", line)
            if match:
                fingers.append(match.group(1))
    return fingers


def get_retry_delay():
    """Read CS9711_DEFAULT_RESET_SLEEP from source."""
    try:
        with open(CS9711_SRC) as f:
            for line in f:
                m = re.search(
                    r"#define\s+CS9711_DEFAULT_RESET_SLEEP\s+(\d+)", line
                )
                if m:
                    return int(m.group(1))
    except FileNotFoundError:
        pass
    return 1500


def _managed_pam_files():
    """Per-service override files we created (tagged with PAM_MARK)."""
    out = []
    try:
        for fn in os.listdir(PAM_DIR):
            p = os.path.join(PAM_DIR, fn)
            try:
                with open(p) as f:
                    if PAM_MARK in f.read():
                        out.append(p)
            except (OSError, UnicodeDecodeError):
                continue
    except OSError:
        pass
    return out


def get_pam_settings():
    """Read max-tries/timeout from the fprintd line. Prefer our per-service
    overrides; fall back to the distro common-auth files."""
    max_tries = 7
    timeout = 30
    for pam_file in _managed_pam_files() + PAM_FILES:
        try:
            with open(pam_file) as f:
                for line in f:
                    if "pam_fprintd.so" in line:
                        m = re.search(r"max-tries=(\d+)", line)
                        if m:
                            max_tries = int(m.group(1))
                        m = re.search(r"timeout=(\d+)", line)
                        if m:
                            timeout = int(m.group(1))
                        return max_tries, timeout, pam_file
        except (FileNotFoundError, UnicodeDecodeError):
            continue
    return max_tries, timeout, None


def _read_pam_resolved(name, seen=None):
    """Read a PAM file and recursively resolve all @include / include / substack
    directives, returning the concatenated effective content (or '' if missing).

    Handles both Debian/Ubuntu syntax (@include common-auth) and Fedora/Arch
    syntax (auth include system-auth, auth substack password-auth). Cycle-safe
    via the `seen` set.
    """
    if seen is None:
        seen = set()
    if name in seen:
        return ""
    seen.add(name)

    path = _pam_path(name)
    try:
        with open(path) as f:
            raw = f.read()
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        return ""

    chunks = [raw]
    for line in raw.splitlines():
        line = line.split("#", 1)[0].strip()  # strip comments
        if not line:
            continue
        # @include FILE  (Debian/Ubuntu/openSUSE)
        m = re.match(r"^@include\s+(\S+)$", line)
        # auth/account/password/session  include|substack  FILE  (Fedora/Arch)
        if not m:
            m = re.match(r"^\S+\s+(?:include|substack)\s+(\S+)$", line)
        if m:
            chunks.append(_read_pam_resolved(m.group(1), seen))
    return "\n".join(chunks)


def _has_fprintd_in_stack(name):
    """True iff pam_fprintd.so appears in the effective PAM stack of `name`."""
    return "pam_fprintd.so" in _read_pam_resolved(name)


def get_pam_auth_locations():
    """Check which PAM services have fingerprint enabled.

    Walks each candidate service file's @include / include / substack chain so
    that on Debian/Ubuntu (where /etc/pam.d/sudo etc. just @include common-auth)
    we correctly report enabled. If a service has *no* PAM file at all (e.g.
    /etc/pam.d/polkit-1 missing on Kubuntu — polkitd falls back to PAM
    defaults), report enabled iff the distro common stack carries fprintd.
    """
    common_enabled = any(
        _has_fprintd_in_stack(f) for f in DISTRO_COMMON_AUTH_FILES
    )

    locations = {}
    for name, files in SERVICE_PAM_FILES.items():
        enabled = False
        any_file_present = False
        for f in files:
            if os.path.exists(_pam_path(f)):
                any_file_present = True
                if _has_fprintd_in_stack(f):
                    enabled = True
                    break
        # No service-specific PAM file => service inherits PAM defaults,
        # which on every major distro route through the common-auth equivalent.
        if not enabled and not any_file_present and common_enabled:
            enabled = True
        locations[name] = enabled
    return locations


def run_as_root(cmd_str):
    """Run a shell command as root via pkexec."""
    return run_cmd(["pkexec", "bash", "-c", cmd_str], timeout=60)


def pam_toggle_cmd(location, enable, max_tries=7, timeout=30):
    """Build a root bash script that enables/disables fingerprint for one auth
    location by managing that service's own PAM file — independently of the others.

    Reversible and cross-distro:
      * Services whose file lives in the vendor dir (openSUSE/Fedora) get an
        /etc/pam.d override created (and removed again on revert).
      * Services whose file already lives in /etc (Debian/Ubuntu) are edited in
        place; on disable our marked line is stripped (file kept).
      * Services whose vendor file already carries fprintd (KDE's kde-fingerprint)
        are toggled by removing the line via a shadow override instead of adding.
    The full vendor stack (incl. the password path) is always preserved, and the
    fprintd line is only ever 'sufficient', so password auth never breaks.
    """
    services = SERVICE_PAM_FILES.get(location, [])
    svc_list = " ".join(s for s in services if re.match(r"^[A-Za-z0-9._-]+$", s))
    fp_opts = f"max-tries={int(max_tries)} timeout={int(timeout)}"
    en = "1" if enable else "0"
    # INS keeps literal \t; awk -v converts them to tabs when writing the line.
    ins = f"auth\\tsufficient\\tpam_fprintd.so\\t{fp_opts}\\t{PAM_MARK}"
    return f'''set -u
ETC={PAM_DIR}; VENDOR={VENDOR_PAM_DIR}; MARK="{PAM_MARK}"; ENABLE={en}
INS="{ins}"
has_vendor_fp(){{ [ -f "$VENDOR/$1" ] && grep -qE '^[^#]*pam_fprintd\\.so' "$VENDOR/$1"; }}
ensure_copy(){{ [ -f "$ETC/$1" ] || {{ [ -f "$VENDOR/$1" ] && cp -a "$VENDOR/$1" "$ETC/$1"; }}; }}
strip_ours(){{ [ -f "$ETC/$1" ] && {{ grep -v "$MARK" "$ETC/$1" > "$ETC/$1.tmp" && mv "$ETC/$1.tmp" "$ETC/$1"; }}; true; }}
add_fp(){{ ensure_copy "$1"; [ -f "$ETC/$1" ] || return 0; strip_ours "$1"
  awk -v ins="$INS" '!d && $1=="auth" && /common-auth|system-auth|system-login|system-local-login/ {{print ins; d=1}} {{print}} END{{if(!d)exit 3}}' "$ETC/$1" > "$ETC/$1.tmp" \\
    || awk -v ins="$INS" 'NR==1{{print; print ins; next}} {{print}}' "$ETC/$1" > "$ETC/$1.tmp"
  mv "$ETC/$1.tmp" "$ETC/$1"; chmod 644 "$ETC/$1"; }}
revert_vendor(){{ [ -f "$ETC/$1" ] && grep -q "$MARK" "$ETC/$1" && rm -f "$ETC/$1"; true; }}
remove_fp(){{ [ -f "$ETC/$1" ] || return 0; grep -q "$MARK" "$ETC/$1" || return 0; strip_ours "$1"
  [ -f "$VENDOR/$1" ] && cmp -s "$ETC/$1" "$VENDOR/$1" && rm -f "$ETC/$1"; true; }}
shadow_nofp(){{ [ -f "$VENDOR/$1" ] || return 0
  {{ grep -vE '^[^#]*pam_fprintd\\.so' "$VENDOR/$1"; echo "$MARK"; }} > "$ETC/$1.tmp"
  mv "$ETC/$1.tmp" "$ETC/$1"; chmod 644 "$ETC/$1"; }}
# Self-heal: per-service files are the source of truth, so any leftover *global*
# fprintd in common-auth (from an older global setup) must go, or "off" wouldn't
# actually disable. Safe: only the fprintd line is removed; pam_unix (password) stays.
for cf in common-auth common-auth-pc; do
  [ -f "$ETC/$cf" ] && grep -q "pam_fprintd" "$ETC/$cf" && sed -i '/pam_fprintd/d' "$ETC/$cf"
done
# Prefer a "native" fingerprint service (vendor file already ships fprintd, e.g.
# kde-fingerprint / gdm-fingerprint). If one exists, that alone controls this
# location; otherwise we manage every existing generic service file.
NATIVE=""
for svc in {svc_list}; do has_vendor_fp "$svc" && NATIVE="$NATIVE $svc"; done
if [ -n "$NATIVE" ]; then TARGETS="$NATIVE"; else TARGETS="{svc_list}"; fi
for svc in $TARGETS; do
  [ -f "$ETC/$svc" ] || [ -f "$VENDOR/$svc" ] || continue
  if [ "$ENABLE" = 1 ]; then
    if has_vendor_fp "$svc"; then revert_vendor "$svc"; else add_fp "$svc"; fi
  else
    if has_vendor_fp "$svc"; then shadow_nofp "$svc"; else remove_fp "$svc"; fi
  fi
done'''


# ============================================================================
# Main Application
# ============================================================================


class CS9711ManagerApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.connect("activate", self.on_activate)
        self.win = None

    def on_activate(self, app):
        # Single instance — if window exists, just bring it to front
        if self.win is not None:
            log.info("Window already open — bringing to front")
            self.win.present()
            return
        log.info(f"=== CS9711 Fingerprint Manager v{APP_VERSION} starting ===")
        log.info(f"User: {os.environ.get('USER', 'unknown')} | PID: {os.getpid()}")
        log.info(f"Script dir: {SCRIPT_DIR}")
        log.info(f"Log file: {LOG_FILE}")
        self.win = CS9711Window(application=app)
        self.win.present()


class CS9711Window(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title(f"CS9711 Fingerprint Manager v{APP_VERSION}")
        # Wide enough for the two-column layout; the breakpoint below collapses
        # to a single column when the window (or the screen) is narrower.
        self.set_default_size(1120, 720)
        self.set_size_request(360, 480)

        # Enroll process tracking
        self._enroll_process = None
        self._enroll_cancel = False

        install_css()

        # Main layout
        self.toolbar_view = Adw.ToolbarView()
        self.set_content(self.toolbar_view)

        # Header bar
        header = Adw.HeaderBar()
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh status")
        refresh_btn.connect("clicked", lambda _: self.refresh_all())
        header.pack_end(refresh_btn)

        # About — author credit and project links. Standard for a desktop app
        # (every GNOME/KDE app carries one) and where users expect to find the
        # issue tracker.
        about_btn = Gtk.Button(icon_name=pick_icon("help-about-symbolic", "help-about"),
                               tooltip_text="About this app")
        about_btn.connect("clicked", self.on_about)
        header.pack_end(about_btn)
        self.toolbar_view.add_top_bar(header)

        # Driver-health banner. A driver stranded by an OpenCV upgrade used to
        # be a subtitle halfway down the page; as a banner it is unmissable and
        # carries the fix as a button.
        self.health_banner = Adw.Banner(revealed=False, button_label="Rebuild Driver")
        self.health_banner.connect(
            "button-clicked", lambda *_: self.on_rebuild_driver(self._maintenance_rebuild_btn)
        )
        self.toolbar_view.add_top_bar(self.health_banner)

        # Scrollable content. Horizontal scrolling is off: the breakpoint
        # guarantees the content reflows instead of overflowing sideways.
        scroll = Gtk.ScrolledWindow(vexpand=True,
                                    hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.toolbar_view.set_content(scroll)

        # Clamp keeps the dashboard readable on ultrawide screens rather than
        # stretching two columns across 3840px.
        clamp = Adw.Clamp(maximum_size=1500, tightening_threshold=1100)
        scroll.set_child(clamp)

        self.columns = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=18,
            margin_start=16, margin_end=16, margin_top=10, margin_bottom=20,
        )
        clamp.set_child(self.columns)

        self.col_left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                                hexpand=True, valign=Gtk.Align.START)
        self.col_right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                                 hexpand=True, valign=Gtk.Align.START)
        self.columns.append(self.col_left)
        self.columns.append(self.col_right)

        # Left column is the workflow you came for: does it work → enrol a
        # finger → tune how hard it tries. Right column is configuration and
        # upkeep: where it applies → maintenance → diagnostics, i.e. importance
        # decreasing toward the bottom-right.
        #
        # The split is also chosen so the two columns finish at roughly the same
        # height. Putting all four config groups on the right left the bottom
        # half of the left column empty, which looks broken rather than airy.
        self.build_status_section(self.col_left)
        self.build_enrollment_section(self.col_left)
        self.build_settings_section(self.col_left)
        self.build_auth_section(self.col_right)
        self.build_maintenance_section(self.col_right)

        # Below this width two columns stop being readable — stack them. This is
        # what keeps the app correct in a narrow/mobile GNOME context, in a
        # half-tiled window, and on small laptop screens, without giving up the
        # dashboard when there IS room for it.
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 880sp"))
        bp.add_setter(self.columns, "orientation", Gtk.Orientation.VERTICAL)
        self.add_breakpoint(bp)

        # Toast overlay for notifications
        self.toast_overlay = Adw.ToastOverlay()
        content = self.toolbar_view.get_content()
        self.toolbar_view.set_content(self.toast_overlay)
        self.toast_overlay.set_child(content)

        # Track first refresh for enrollment prompt
        self._first_refresh_done = False

        # Initial data load — enrollment prompt triggers after refresh completes
        self.refresh_all()

    def _check_first_launch(self):
        """Show enrollment prompt if no fingers enrolled."""
        log.info("First launch check: no fingers enrolled, scanner connected — showing welcome dialog")
        if not self._has_enrolled_fingers and is_scanner_connected():
            dialog = Adw.AlertDialog(
                heading="Welcome! Let's set up your fingerprint",
                body=(
                    "Your CS9711 scanner is connected and the driver is installed.\n\n"
                    "To start using fingerprint login, you need to enroll a finger. "
                    "This takes 15 touches on the scanner.\n\n"
                    "By default, your RIGHT INDEX FINGER will be enrolled. "
                    "If you're left-handed, you can change the finger in the dropdown below the Enroll button.\n\n"
                    "Click 'Start Enrollment' to begin — then place your finger on the scanner when prompted."
                ),
            )
            dialog.add_response("later", "Later")
            dialog.add_response("enroll", "Start Enrollment")
            dialog.set_response_appearance("enroll", Adw.ResponseAppearance.SUGGESTED)
            dialog.connect("response", self._on_first_launch_response)
            dialog.present(self)
        return False  # don't repeat

    def _on_first_launch_response(self, dialog, response):
        log.info(f"Welcome dialog response: {response}")
        if response == "enroll":
            self._start_enroll()

    def show_toast(self, message):
        toast = Adw.Toast(title=message, timeout=3)
        self.toast_overlay.add_toast(toast)

    # ========================================================================
    # Status Section
    # ========================================================================

    def build_status_section(self, parent):
        """Hero card: one glance answers whether fingerprint works right now.

        This replaces three stacked rows (scanner / driver / fingers) that cost
        ~200px to say what a headline plus three chips now says in ~120px —
        and says it better, because the three facts are only ever read together.
        """
        group = Adw.PreferencesGroup()
        parent.append(group)

        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                       css_classes=["card", "cs-hero"])
        group.add(card)

        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16, hexpand=True,
                        margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        card.append(inner)

        self.hero_icon = Gtk.Image.new_from_icon_name(icon_fingerprint())
        self.hero_icon.set_pixel_size(48)
        self.hero_icon.add_css_class("cs-hero-icon")
        self.hero_icon.set_valign(Gtk.Align.CENTER)
        inner.append(self.hero_icon)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3,
                       valign=Gtk.Align.CENTER, hexpand=True)
        inner.append(text)

        self.hero_title = Gtk.Label(xalign=0, label="Checking…", css_classes=["title-2"])
        self.hero_title.set_wrap(True)
        text.append(self.hero_title)

        self.hero_sub = Gtk.Label(xalign=0, label="", css_classes=["dim-label"], wrap=True)
        text.append(self.hero_sub)

        chips = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, margin_top=8)
        text.append(chips)
        self.pill_scanner = status_pill("Scanner")
        self.pill_driver = status_pill("Driver")
        self.pill_fingers = status_pill("Fingers")
        for p in (self.pill_scanner, self.pill_driver, self.pill_fingers):
            chips.append(p)

    # ========================================================================
    # Enrollment Section
    # ========================================================================

    def build_enrollment_section(self, parent):
        group = Adw.PreferencesGroup(title="Fingerprint Enrollment",
                                     description="15 touches required per finger")
        parent.append(group)

        # Enrollment status banner
        self.enroll_status_row = Adw.ActionRow(
            title="Enrollment Status",
            subtitle="Checking...",
        )
        self.enroll_status_row.add_prefix(
            Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        )
        group.add(self.enroll_status_row)

        # Finger selector
        self.finger_dropdown = Adw.ComboRow(title="Finger to enroll")
        finger_names = Gtk.StringList()
        for _, name in FINGERS:
            finger_names.append(name)
        self.finger_dropdown.set_model(finger_names)
        group.add(self.finger_dropdown)

        # Progress
        self.enroll_progress = Gtk.ProgressBar(show_text=True, margin_top=8, margin_bottom=4,
                                               margin_start=12, margin_end=12)
        self.enroll_progress.set_fraction(0)
        self.enroll_progress.set_text("")
        self.enroll_progress.set_visible(False)
        parent.append(self.enroll_progress)

        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          halign=Gtk.Align.CENTER, margin_top=8, margin_bottom=16)
        parent.append(btn_box)

        self.enroll_btn = Gtk.Button(label="Enroll", css_classes=["suggested-action"])
        self.enroll_btn.connect("clicked", self.on_enroll_clicked)
        btn_box.append(self.enroll_btn)

        self.verify_btn = Gtk.Button(label="Test Verify")
        self.verify_btn.connect("clicked", self.on_verify)
        btn_box.append(self.verify_btn)

        self.delete_btn = Gtk.Button(label="Delete All", css_classes=["destructive-action"])
        self.delete_btn.connect("clicked", self.on_delete_fingers)
        btn_box.append(self.delete_btn)

        self.cancel_enroll_btn = Gtk.Button(label="Cancel", visible=False)
        self.cancel_enroll_btn.connect("clicked", self.on_cancel_enroll)
        btn_box.append(self.cancel_enroll_btn)

        # Track enrolled state
        self._has_enrolled_fingers = False

    def on_enroll_clicked(self, btn):
        """Handle enroll button — confirm re-enroll if fingers already exist."""
        log.info(f"User clicked Enroll (has_enrolled={self._has_enrolled_fingers})")
        if self._has_enrolled_fingers:
            dialog = Adw.AlertDialog(
                heading="Fingerprints already enrolled",
                body="You already have fingerprints enrolled. Enrolling a new finger "
                     "will add to the existing ones. To start fresh, delete all first.",
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("add", "Add Another Finger")
            dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
            dialog.connect("response", self._on_reenroll_confirmed)
            dialog.present(self)
        else:
            self._start_enroll()

    def _on_reenroll_confirmed(self, dialog, response):
        log.info(f"Re-enroll dialog response: {response}")
        if response == "add":
            self._start_enroll()

    def _start_enroll(self):
        idx = self.finger_dropdown.get_selected()
        finger_id = FINGERS[idx][0]
        finger_name = FINGERS[idx][1]

        log.info(f"Starting enrollment: finger={finger_id} ({finger_name})")
        self.enroll_progress.set_visible(True)
        self.enroll_progress.set_fraction(0)
        self.enroll_progress.set_text(f"Preparing {finger_name}...")
        self.enroll_btn.set_sensitive(False)
        self.cancel_enroll_btn.set_visible(True)
        self._enroll_cancel = False

        def do_enroll():
            try:
                # Only delete existing enrollment for this finger if it's already enrolled
                # (avoids a second unnecessary polkit password prompt on first enrollment)
                enrolled = get_enrolled_fingers()
                if finger_id in enrolled:
                    log.info(f"Finger {finger_id} already enrolled — deleting before re-enroll")
                    run_cmd(["fprintd-delete", os.environ.get("USER", "nobody"), finger_id], timeout=5)
                else:
                    log.debug(f"Finger {finger_id} not enrolled — skipping delete")

                self._enroll_progress_text = f"Enrolling {finger_name}... Touch the scanner NOW"
                GLib.idle_add(lambda: (self.enroll_progress.set_text(self._enroll_progress_text), False)[-1])

                log.info(f"Launching fprintd-enroll -f {finger_id} (polkit auth expected)")
                self._enroll_process = subprocess.Popen(
                    ["fprintd-enroll", "-f", finger_id],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                )
                touch_count = 0
                for line in self._enroll_process.stdout:
                    if self._enroll_cancel:
                        self._enroll_process.terminate()
                        GLib.idle_add(self._enroll_done, "Cancelled", False)
                        return
                    line = line.strip()
                    low = line.lower()
                    if "enroll-stage-passed" in low or "stage passed" in low:
                        touch_count += 1
                        log.info(f"Enroll touch {touch_count}/15 accepted")
                        frac = min(touch_count / 15.0, 1.0)
                        GLib.idle_add(
                            self._enroll_update,
                            frac,
                            f"Touch {touch_count}/15 — good, keep going!",
                        )
                    elif "enroll-completed" in low:
                        GLib.idle_add(self._enroll_done, "Enrollment complete!", True)
                        return
                    elif "enroll-retry-scan" in low or "retry" in low:
                        GLib.idle_add(
                            self._enroll_update,
                            touch_count / 15.0,
                            f"Touch {touch_count}/15 — bad read, try again",
                        )
                    elif "enroll-swipe-too-short" in low or "too short" in low:
                        GLib.idle_add(
                            self._enroll_update,
                            touch_count / 15.0,
                            f"Touch {touch_count}/15 — too short, hold longer",
                        )
                    elif "enroll-finger-not-centered" in low or "not centered" in low:
                        GLib.idle_add(
                            self._enroll_update,
                            touch_count / 15.0,
                            f"Touch {touch_count}/15 — center your finger",
                        )
                    elif "enroll-remove-and-retry" in low or "remove" in low:
                        GLib.idle_add(
                            self._enroll_update,
                            touch_count / 15.0,
                            f"Touch {touch_count}/15 — lift and touch again",
                        )
                    elif "enroll-failed" in low or "enroll-unknown-error" in low:
                        GLib.idle_add(self._enroll_done, "Enrollment failed — try again", False)
                        return
                    elif "enroll-data-full" in low:
                        GLib.idle_add(self._enroll_done, "Storage full — delete old prints first", False)
                        return
                    # Ignore noise: fprintd debug lines like "ListEnrolledFingers failed"

                self._enroll_process.wait()
                if self._enroll_process.returncode == 0:
                    GLib.idle_add(self._enroll_done, "Enrollment complete!", True)
                else:
                    GLib.idle_add(self._enroll_done, "Enrollment failed", False)

            except Exception as e:
                GLib.idle_add(self._enroll_done, f"Error: {e}", False)

        threading.Thread(target=do_enroll, daemon=True).start()

    def _enroll_update(self, fraction, text):
        self.enroll_progress.set_fraction(fraction)
        self.enroll_progress.set_text(text)
        return False

    def _enroll_done(self, message, success):
        log.info(f"Enrollment finished: success={success} message={message!r}")
        self.enroll_progress.set_fraction(1.0 if success else 0)
        self.enroll_btn.set_sensitive(True)
        self.cancel_enroll_btn.set_visible(False)
        self._enroll_process = None
        if success:
            self.enroll_progress.set_text("All 15 touches done! Enrollment saved.")
            self.refresh_all()
            # Ask user if they want to verify
            dialog = Adw.AlertDialog(
                heading="Enrollment complete!",
                body="All 15 touches recorded successfully.\n\n"
                     "Would you like to do a quick verification touch to confirm "
                     "your fingerprint is working?",
            )
            dialog.add_response("skip", "Skip")
            dialog.add_response("verify", "Verify Now")
            dialog.set_response_appearance("verify", Adw.ResponseAppearance.SUGGESTED)
            dialog.connect("response", self._on_post_enroll_verify_response)
            dialog.present(self)
        else:
            self.enroll_progress.set_text(message)
            self.show_toast(message)
        return False

    def _on_post_enroll_verify_response(self, dialog, response):
        log.info(f"Post-enroll verify dialog response: {response}")
        if response == "verify":
            self.show_toast("Touch the scanner once to verify...")
            self.enroll_progress.set_text("Verification — touch the scanner once...")
            self._auto_verify_after_enroll()
        else:
            self.show_toast("Enrollment saved — you're all set!")
            self.enroll_progress.set_text("Enrollment saved.")

    def _auto_verify_after_enroll(self):
        """Auto-verify after enrollment to confirm the fingerprint works."""
        self.verify_btn.set_sensitive(False)

        def do_verify():
            rc, out, err = run_cmd(["fprintd-verify"], timeout=30)
            combined = f"{out}\n{err}".lower()
            if "verify-match" in combined:
                GLib.idle_add(self._post_enroll_verify_done, True)
            else:
                GLib.idle_add(self._post_enroll_verify_done, False)

        threading.Thread(target=do_verify, daemon=True).start()
        return False  # don't repeat

    def _post_enroll_verify_done(self, success):
        self.verify_btn.set_sensitive(True)
        if success:
            self.enroll_progress.set_text("Fingerprint verified! Everything is working.")
            self.enroll_progress.set_fraction(1.0)
            self.show_toast("Fingerprint verified! You're all set.")
        else:
            self.enroll_progress.set_text("Verification failed — try Test Verify again")
            self.enroll_progress.set_fraction(0)
            self.show_toast("Verification didn't match — try again with Test Verify")
        return False

    def on_cancel_enroll(self, btn):
        log.info("User cancelled enrollment")
        self._enroll_cancel = True
        if self._enroll_process:
            try:
                self._enroll_process.terminate()
            except ProcessLookupError:
                pass

    def on_verify(self, btn):
        log.info("User clicked Test Verify")
        self.enroll_progress.set_visible(True)
        self.enroll_progress.set_fraction(0)
        self.enroll_progress.set_text("Touch the scanner to verify...")
        self.verify_btn.set_sensitive(False)

        def do_verify():
            rc, out, err = run_cmd(["fprintd-verify"], timeout=30)
            combined = f"{out}\n{err}".lower()
            if "verify-match" in combined:
                GLib.idle_add(self._verify_done, "Fingerprint verified!", True)
            elif "verify-no-match" in combined:
                GLib.idle_add(self._verify_done, "No match — try again or re-enroll", False)
            else:
                msg = out or err or "Verification timed out"
                GLib.idle_add(self._verify_done, msg, False)

        threading.Thread(target=do_verify, daemon=True).start()

    def _verify_done(self, message, success):
        log.info(f"Verify result: success={success} message={message!r}")
        self.enroll_progress.set_text(message)
        self.enroll_progress.set_fraction(1.0 if success else 0)
        self.verify_btn.set_sensitive(True)
        self.show_toast(message)
        return False

    def on_delete_fingers(self, btn):
        log.info("User clicked Delete All")
        dialog = Adw.AlertDialog(
            heading="Delete all fingerprints?",
            body="You will need to re-enroll after deletion.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete All")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_delete_confirmed)
        dialog.present(self)

    def _on_delete_confirmed(self, dialog, response):
        if response != "delete":
            return
        self.delete_btn.set_sensitive(False)

        def do_delete():
            user = os.environ.get("USER", "nobody")
            log.info(f"Delete confirmed — deleting all fingerprints for {user}")

            # Kill any running fprintd operation (verify/enroll) that holds the device
            if self._enroll_process:
                log.info("Terminating active enrollment before delete")
                try:
                    self._enroll_process.terminate()
                    self._enroll_process.wait(timeout=3)
                except Exception:
                    pass
                self._enroll_process = None

            # Also kill any stray fprintd-verify/fprintd-enroll processes
            for proc_name in ["fprintd-verify", "fprintd-enroll"]:
                subprocess.run(["pkill", "-f", proc_name], capture_output=True)
            time.sleep(0.5)

            # Retry up to 3 times in case device claim takes a moment to release
            for attempt in range(3):
                rc, out, err = run_cmd(["fprintd-delete", user], timeout=10)
                msg = err or out  # fprintd puts some errors on stdout
                if rc == 0 or "AlreadyInUse" not in msg:
                    break
                log.warning(f"Delete attempt {attempt + 1}/3 got AlreadyInUse — retrying in 2s")
                time.sleep(2)
            def _done():
                self.delete_btn.set_sensitive(True)
                if rc == 0:
                    self.show_toast("All fingerprints deleted")
                else:
                    self.show_toast(f"Delete failed: {msg}")
                self.refresh_all()
                return False
            GLib.idle_add(_done)

        threading.Thread(target=do_delete, daemon=True).start()

    # ========================================================================
    # Scan Settings Section
    # ========================================================================

    def build_settings_section(self, parent):
        """Scanner pacing and authentication limits in ONE group.

        They were two groups with two headings and two descriptions for four
        controls that are all answers to the same question — how hard should it
        try before giving up. Merging them removes a heading, a description and
        a group gap without hiding anything.
        """
        group = Adw.PreferencesGroup(
            # NB: PreferencesGroup titles are parsed as Pango markup — a bare
            # ampersand here raises a markup error and blanks the heading.
            title="Scanner and Authentication",
            description="How the scanner paces retries, and how many tries before password",
        )
        parent.append(group)

        # Retry delay
        self.delay_row = Adw.ActionRow(title="Retry Delay",
                                       subtitle="Pause between scan attempts (ms)")
        group.add(self.delay_row)

        delay_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                            valign=Gtk.Align.CENTER)
        self.delay_row.add_suffix(delay_box)

        self.delay_adj = Gtk.Adjustment(value=1500, lower=250, upper=3000, step_increment=250)
        self.delay_scale = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.delay_adj,
            digits=0, draw_value=True, value_pos=Gtk.PositionType.LEFT,
            width_request=200
        )
        self.delay_scale.add_mark(250, Gtk.PositionType.BOTTOM, "250")
        self.delay_scale.add_mark(1500, Gtk.PositionType.BOTTOM, "1500")
        self.delay_scale.add_mark(3000, Gtk.PositionType.BOTTOM, "3000")
        delay_box.append(self.delay_scale)

        self.delay_label = Gtk.Label(label="ms", css_classes=["dim-label"])
        delay_box.append(self.delay_label)

        # Rebuild notice
        self.rebuild_notice = Adw.ActionRow(
            title="Rebuild Required",
            subtitle="Retry delay changes require a driver rebuild to take effect",
            visible=False,
        )
        self.rebuild_notice.add_prefix(
            Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        )
        self.rebuild_apply_btn = Gtk.Button(
            label="Rebuild Now", css_classes=["suggested-action"],
            valign=Gtk.Align.CENTER
        )
        self.rebuild_apply_btn.connect("clicked", self.on_rebuild_with_delay)
        self.rebuild_notice.add_suffix(self.rebuild_apply_btn)
        group.add(self.rebuild_notice)

        # Track changes
        self._original_delay = 1500
        self.delay_adj.connect("value-changed", self._on_delay_changed)

        # --- authentication limits, same group ---
        self.build_pam_settings_section(group)

    def _on_delay_changed(self, adj):
        current = int(adj.get_value())
        self.rebuild_notice.set_visible(current != self._original_delay)

    def on_rebuild_with_delay(self, btn):
        new_delay = int(self.delay_adj.get_value())

        btn.set_sensitive(False)
        btn.set_label("Rebuilding...")

        def do_rebuild():
            # Update source file
            if os.path.exists(CS9711_SRC):
                cmd = (
                    f"sed -i 's/#define CS9711_DEFAULT_RESET_SLEEP.*/"
                    f"#define CS9711_DEFAULT_RESET_SLEEP  {new_delay}/' "
                    f"'{CS9711_SRC}'"
                )
                subprocess.run(["bash", "-c", cmd])

            # Rebuild and install
            reinstall = os.path.join(SCRIPT_DIR, "reinstall.sh")
            rc, out, err = run_cmd(
                ["pkexec", "bash", reinstall], timeout=300
            )

            if rc == 0:
                GLib.idle_add(self._rebuild_done, new_delay, True, "Driver rebuilt!")
            else:
                GLib.idle_add(self._rebuild_done, new_delay, False, f"Rebuild failed: {err[:100]}")

        threading.Thread(target=do_rebuild, daemon=True).start()

    def _rebuild_done(self, delay, success, message):
        self.rebuild_apply_btn.set_sensitive(True)
        self.rebuild_apply_btn.set_label("Rebuild Now")
        if success:
            self._original_delay = delay
            self.rebuild_notice.set_visible(False)
        self.show_toast(message)
        self.refresh_status()
        return False

    # ========================================================================
    # PAM Settings Section
    # ========================================================================

    def build_pam_settings_section(self, group):
        """Rows only — the caller owns the group (see build_settings_section)."""
        # Max tries
        self.tries_adj = Gtk.Adjustment(value=7, lower=1, upper=15, step_increment=1)
        self.tries_row = Adw.SpinRow(
            title="Max Attempts",
            subtitle="Number of fingerprint tries before password fallback",
            adjustment=self.tries_adj,
        )
        group.add(self.tries_row)

        # Timeout
        self.timeout_adj = Gtk.Adjustment(value=30, lower=5, upper=120, step_increment=5)
        self.timeout_row = Adw.SpinRow(
            title="Timeout (seconds)",
            subtitle="Total time window for all fingerprint attempts",
            adjustment=self.timeout_adj,
        )
        group.add(self.timeout_row)

        # Apply button with note about password
        apply_row = Adw.ActionRow(
            title="",
            subtitle="Requires your login password (system files need admin access)",
        )
        self.pam_apply_btn = Gtk.Button(
            label="Apply PAM Settings", css_classes=["suggested-action"],
            valign=Gtk.Align.CENTER
        )
        self.pam_apply_btn.connect("clicked", self.on_apply_pam)
        apply_row.add_suffix(self.pam_apply_btn)
        group.add(apply_row)

    def on_apply_pam(self, btn):
        max_tries = int(self.tries_adj.get_value())
        timeout = int(self.timeout_adj.get_value())
        log.info(f"User clicked Apply PAM: max_tries={max_tries} timeout={timeout}")

        btn.set_sensitive(False)
        btn.set_label("Applying...")

        def do_apply():
            # Re-stamp the options onto every location that is currently ON,
            # through the same per-service path the switches use. This is what
            # makes Apply work on Arch/CachyOS too (issue #1): there is no
            # /etc/pam.d/common-auth there, and nothing global is ever needed —
            # each enabled service file gets its own line. All locations are
            # combined into ONE root script so pkexec prompts once, not four
            # times. With nothing enabled there is nothing to write, so say so
            # instead of silently claiming success.
            locations = get_pam_auth_locations()
            enabled = [n for n, on in locations.items() if on]
            if not enabled:
                def _noop():
                    btn.set_sensitive(True)
                    btn.set_label("Apply PAM Settings")
                    self.show_toast(
                        "Nothing enabled yet — turn on a switch under "
                        "“Where to Use Fingerprint”; these settings apply with it"
                    )
                    return False
                GLib.idle_add(_noop)
                return
            parts = [pam_toggle_cmd(n, True, max_tries, timeout) for n in enabled]
            # Safety net: refresh options on any other override we manage, and
            # keep the global common-auth files free of stray fprintd lines.
            parts.append(f'''set -u
ETC={PAM_DIR}; MARK="{PAM_MARK}"
for f in "$ETC"/*; do
  [ -f "$f" ] || continue
  grep -q "$MARK" "$f" || continue
  sed -i -E 's/(pam_fprintd\\.so)[^#]*/\\1 max-tries={max_tries} timeout={timeout} /' "$f"
done
for cf in common-auth common-auth-pc; do
  [ -f "$ETC/$cf" ] && grep -q pam_fprintd "$ETC/$cf" && sed -i '/pam_fprintd/d' "$ETC/$cf"
done
true''')
            rc, _, err = run_as_root("\n".join(parts))
            def _done():
                btn.set_sensitive(True)
                btn.set_label("Apply PAM Settings")
                if rc == 0:
                    self.show_toast(
                        f"PAM updated: {max_tries} tries, {timeout}s timeout "
                        f"(applied to: {', '.join(enabled)})"
                    )
                else:
                    self.show_toast(f"Failed: {err[:80]}")
                # switches re-read real state — authoritative
                self._set_auth_switches(get_pam_auth_locations())
                return False
            GLib.idle_add(_done)

        threading.Thread(target=do_apply, daemon=True).start()

    # ========================================================================
    # Auth Locations Section
    # ========================================================================

    def build_auth_section(self, parent):
        group = Adw.PreferencesGroup(
            title="Where to Use Fingerprint",
            description="Turn fingerprint on or off for each place independently — "
                        "password always still works",
        )
        parent.append(group)

        self.auth_rows = {}
        self._auth_updating = False
        icons = {
            "Login screen": "system-users-symbolic",
            "Lock screen": "system-lock-screen-symbolic",
            "sudo": "utilities-terminal-symbolic",
            "polkit": "dialog-password-symbolic",
        }

        for name, icon in icons.items():
            row = Adw.SwitchRow(title=name, subtitle="Checking...")
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            row.connect("notify::active", self.on_auth_toggle, name)
            self.auth_rows[name] = row
            group.add(row)

    def refresh_auth_locations(self):
        self._set_auth_switches(get_pam_auth_locations())

    def _set_auth_switches(self, locations):
        """Set switch positions from real state without firing the toggle handler."""
        self._auth_updating = True
        for name, row in self.auth_rows.items():
            enabled = bool(locations.get(name, False))
            row.set_active(enabled)
            row.set_subtitle("On" if enabled else "Off")
        self._auth_updating = False

    def on_auth_toggle(self, row, _pspec, name):
        if self._auth_updating:
            return
        enable = row.get_active()
        try:
            mt = int(self.tries_adj.get_value())
            to = int(self.timeout_adj.get_value())
        except Exception:
            mt, to = 7, 30
        cmd = pam_toggle_cmd(name, enable, mt, to)
        row.set_sensitive(False)
        row.set_subtitle("Applying…")

        def work():
            rc, out, err = run_as_root(cmd)
            GLib.idle_add(self._after_auth_toggle, name, enable, rc, err)

        threading.Thread(target=work, daemon=True).start()

    def _after_auth_toggle(self, name, enable, rc, err):
        self.auth_rows[name].set_sensitive(True)
        if rc != 0:
            log.warning(f"PAM toggle failed for {name}: rc={rc} err={err!r}")
            self.show_toast(f"Couldn't change “{name}” — authentication cancelled or failed")
        else:
            self.show_toast(f"Fingerprint {'enabled' if enable else 'disabled'} for {name}")
        # Re-read the real state — it's authoritative and reverts the switch if needed.
        self._set_auth_switches(get_pam_auth_locations())
        return False

    # ========================================================================
    # Maintenance Section
    # ========================================================================

    def build_maintenance_section(self, parent):
        group = Adw.PreferencesGroup(title="Maintenance")
        parent.append(group)

        # Update checker
        self.update_row = Adw.ActionRow(
            title=f"Version: v{APP_VERSION}",
            subtitle="Click to check for updates",
        )
        self.update_row.add_prefix(Gtk.Image.new_from_icon_name("software-update-available-symbolic"))
        self.update_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
                                       valign=Gtk.Align.CENTER)
        self.check_update_btn = Gtk.Button(label="Check for Updates")
        self.check_update_btn.connect("clicked", self.on_check_update)
        self.update_btn_box.append(self.check_update_btn)
        self.update_row.add_suffix(self.update_btn_box)
        group.add(self.update_row)

        # Rebuild driver
        rebuild_row = Adw.ActionRow(
            title="Rebuild Driver",
            subtitle="Run after system updates overwrite the patched library",
        )
        rebuild_row.add_prefix(Gtk.Image.new_from_icon_name("system-software-install-symbolic"))
        rebuild_btn = Gtk.Button(label="Rebuild", valign=Gtk.Align.CENTER)
        rebuild_btn.connect("clicked", self.on_rebuild_driver)
        rebuild_row.add_suffix(rebuild_btn)
        group.add(rebuild_row)
        self._maintenance_rebuild_btn = rebuild_btn

        # Uninstall
        uninstall_row = Adw.ActionRow(
            title="Uninstall Everything",
            subtitle="Remove driver, fingerprints, GUI, desktop shortcut, and project files",
        )
        uninstall_row.add_prefix(Gtk.Image.new_from_icon_name("user-trash-symbolic"))
        uninstall_btn = Gtk.Button(
            label="Uninstall", css_classes=["destructive-action"],
            valign=Gtk.Align.CENTER,
        )
        uninstall_btn.connect("clicked", self.on_uninstall)
        uninstall_row.add_suffix(uninstall_btn)
        group.add(uninstall_row)

        # Uninstall progress bar (hidden until uninstall starts)
        self.uninstall_progress = Gtk.ProgressBar(show_text=True, margin_top=8, margin_bottom=4,
            margin_start=12, margin_end=12)
        self.uninstall_progress.set_fraction(0)
        self.uninstall_progress.set_text("")
        self.uninstall_progress.set_visible(False)
        parent.append(self.uninstall_progress)

        # Keyring
        keyring_row = Adw.ActionRow(
            title="GNOME Keyring Auto-Unlock",
            subtitle="Set empty keyring password for fingerprint login",
        )
        keyring_row.add_prefix(Gtk.Image.new_from_icon_name("channel-secure-symbolic"))
        keyring_btn = Gtk.Button(label="Configure", valign=Gtk.Align.CENTER)
        keyring_btn.connect("clicked", self.on_keyring)
        keyring_row.add_suffix(keyring_btn)
        group.add(keyring_row)

        # Log viewer
        log_group = Adw.PreferencesGroup(title="Diagnostics",
                                          description=f"Log: {LOG_FILE}")
        parent.append(log_group)

        log_row = Adw.ActionRow(
            title="Activity Log",
            subtitle="View all events for troubleshooting",
        )
        log_row.add_prefix(Gtk.Image.new_from_icon_name("document-open-symbolic"))
        log_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
                              valign=Gtk.Align.CENTER)
        view_log_btn = Gtk.Button(label="View Log")
        view_log_btn.connect("clicked", self.on_view_log)
        log_btn_box.append(view_log_btn)
        clear_log_btn = Gtk.Button(label="Clear Log", css_classes=["destructive-action"])
        clear_log_btn.connect("clicked", self.on_clear_log)
        log_btn_box.append(clear_log_btn)
        log_row.add_suffix(log_btn_box)
        log_group.add(log_row)

    def on_rebuild_driver(self, btn):
        log.info("User clicked Rebuild Driver")
        btn.set_sensitive(False)
        btn.set_label("Rebuilding...")
        self.show_toast("Rebuilding driver — this may take a minute...")

        def do_rebuild():
            script = os.path.join(SCRIPT_DIR, "reinstall.sh")
            rc, out, err = run_cmd(["pkexec", "bash", script], timeout=300)
            if rc == 0:
                GLib.idle_add(self._maintenance_done, btn, "Rebuild", "Driver rebuilt!", True)
            else:
                GLib.idle_add(self._maintenance_done, btn, "Rebuild", f"Failed: {err[:80]}", False)

        threading.Thread(target=do_rebuild, daemon=True).start()

    def on_check_update(self, btn):
        log.info("User clicked Check for Updates")
        btn.set_sensitive(False)
        btn.set_label("Checking...")
        self.update_row.set_subtitle("Checking for updates...")

        def do_check():
            # Fetch latest from remote
            rc, _, err = run_cmd(["git", "-C", SCRIPT_DIR, "fetch", "origin"], timeout=30)
            if rc != 0:
                GLib.idle_add(self._update_check_done, None, f"Fetch failed: {err[:60]}")
                return

            # Read remote VERSION
            rc, remote_version, _ = run_cmd(
                ["git", "-C", SCRIPT_DIR, "show", "origin/main:VERSION"], timeout=5
            )
            remote_version = remote_version.strip() if rc == 0 else None

            # Get changelog diff
            rc, changelog, _ = run_cmd(
                ["git", "-C", SCRIPT_DIR, "log", f"HEAD..origin/main",
                 "--oneline", "--no-decorate"], timeout=5
            )

            GLib.idle_add(self._update_check_done, remote_version, changelog)

        threading.Thread(target=do_check, daemon=True).start()

    def _update_check_done(self, remote_version, changelog):
        self.check_update_btn.set_sensitive(True)
        self.check_update_btn.set_label("Check for Updates")

        if remote_version is None:
            self.update_row.set_subtitle(f"v{APP_VERSION} — could not check remote")
            self.show_toast(f"Update check failed: {changelog}")
            return False

        if not changelog or remote_version == APP_VERSION:
            self.update_row.set_subtitle(f"v{APP_VERSION} — up to date!")
            log.info(f"No updates available (local={APP_VERSION}, remote={remote_version})")
            self.show_toast("You're on the latest version!")
            return False

        # Update available
        log.info(f"Update available: v{APP_VERSION} → v{remote_version}")
        self.update_row.set_subtitle(f"v{APP_VERSION} → v{remote_version} available")

        # Show update dialog
        dialog = Adw.AlertDialog(
            heading=f"Update available: v{remote_version}",
            body=f"You have v{APP_VERSION}. Changes:\n\n{changelog}\n\n"
                 "The GUI will restart after updating.",
        )
        dialog.add_response("cancel", "Later")
        dialog.add_response("update", "Update Now")
        dialog.set_response_appearance("update", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_update_confirmed, remote_version)
        dialog.present(self)
        return False

    def _on_update_confirmed(self, dialog, response, remote_version):
        log.info(f"Update dialog response: {response}")
        if response != "update":
            return

        self.check_update_btn.set_sensitive(False)
        self.update_row.set_subtitle("Updating...")
        log.info(f"Updating from v{APP_VERSION} to v{remote_version}")

        def do_update():
            # Pull latest
            rc, out, err = run_cmd(["git", "-C", SCRIPT_DIR, "pull", "origin", "main"], timeout=60)
            if rc != 0:
                log.error(f"git pull failed: {err}")
                GLib.idle_add(self._update_failed, err)
                return

            # Check if driver-related files changed (need rebuild)
            rc2, changed, _ = run_cmd(
                ["git", "-C", SCRIPT_DIR, "diff", "--name-only", f"HEAD~1..HEAD"], timeout=5
            )
            needs_rebuild = any(f in changed for f in [
                "install.sh", "reinstall.sh", "patches/"
            ]) if rc2 == 0 else False

            log.info(f"Update pulled. Changed files: {changed}. Needs rebuild: {needs_rebuild}")

            def _restart():
                self.update_row.set_subtitle(f"Updated to v{remote_version} — restarting...")
                self.show_toast("Updated! Restarting GUI...")

                if needs_rebuild:
                    log.info("Driver files changed — prompting rebuild after restart")

                # Restart the GUI after a short delay
                GLib.timeout_add(1500, self._restart_gui)
                return False
            GLib.idle_add(_restart)

        threading.Thread(target=do_update, daemon=True).start()

    def _update_failed(self, err):
        self.check_update_btn.set_sensitive(True)
        self.check_update_btn.set_label("Check for Updates")
        self.update_row.set_subtitle(f"v{APP_VERSION} — update failed")
        self.show_toast(f"Update failed: {err[:60]}")
        return False

    def _restart_gui(self):
        log.info("=== GUI restarting after update ===")
        # Re-launch self and exit
        subprocess.Popen(["python3", os.path.join(SCRIPT_DIR, "cs9711-manager.py")])
        self.close()
        return False

    def on_uninstall(self, btn):
        log.info("User clicked Uninstall Everything")
        dialog = Adw.AlertDialog(
            heading="Uninstall everything?",
            body="This will completely remove:\n\n"
                 "- Enrolled fingerprints\n"
                 "- Patched CS9711 driver\n"
                 "- GUI Manager and desktop shortcut\n"
                 "- The entire project folder\n\n"
                 "Stock libfprint will be restored. It will be as if this was never installed.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("uninstall", "Uninstall Everything")
        dialog.set_response_appearance("uninstall", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_uninstall_confirmed)
        dialog.present(self)

    def _on_uninstall_confirmed(self, dialog, response):
        log.info(f"Uninstall dialog response: {response}")
        if response != "uninstall":
            return

        log.info("=== UNINSTALL STARTING ===")
        project_dir = SCRIPT_DIR
        desktop_file = os.path.expanduser("~/.local/share/applications/cs9711-manager.desktop")
        user = os.environ.get("USER", "nobody")

        # Show uninstall progress bar
        self.uninstall_progress.set_visible(True)
        self.uninstall_progress.set_fraction(0)
        self.uninstall_progress.set_text("Uninstalling... removing fingerprints")

        def do_uninstall():
            def _update(fraction, text):
                self.uninstall_progress.set_fraction(fraction)
                self.uninstall_progress.set_text(text)
                return False

            GLib.idle_add(_update, 0.1, "Step 1/5 — Removing fingerprints...")
            log.info("Uninstall step 1/5: writing temp script")

            # Step 1: Write uninstall commands to a secure temp script
            fd, tmp_script = tempfile.mkstemp(prefix="cs9711-uninstall-", suffix=".sh")
            try:
                with os.fdopen(fd, "w") as f:
                    f.write("#!/bin/bash\n")
                    f.write(f"fprintd-delete {shlex.quote(user)} 2>/dev/null || true\n")
                    # Remove patched libraries — all possible arch paths
                    f.write("for libdir in"
                            " /usr/local/lib/x86_64-linux-gnu"
                            " /usr/local/lib/aarch64-linux-gnu"
                            " /usr/local/lib/arm-linux-gnueabihf"
                            " /usr/local/lib64"
                            " /usr/local/lib; do\n")
                    f.write("  rm -f \"$libdir\"/libfprint-2.so* 2>/dev/null\n")
                    f.write("  rm -f \"$libdir\"/girepository-1.0/FPrint-2.0.typelib 2>/dev/null\n")
                    f.write("done\n")
                    f.write("ldconfig\n")
                    # Reinstall stock libfprint — detect distro
                    f.write("if command -v apt >/dev/null 2>&1; then\n")
                    f.write("  apt install --reinstall -y libfprint-2-2 2>/dev/null || true\n")
                    f.write("elif command -v dnf >/dev/null 2>&1; then\n")
                    f.write("  dnf reinstall -y libfprint 2>/dev/null || true\n")
                    f.write("elif command -v pacman >/dev/null 2>&1; then\n")
                    f.write("  pacman -S --noconfirm libfprint 2>/dev/null || true\n")
                    f.write("elif command -v zypper >/dev/null 2>&1; then\n")
                    f.write("  zypper install -f -y libfprint-2-2 2>/dev/null || true\n")
                    f.write("fi\n")
                    f.write("ldconfig\n")
                    f.write("systemctl restart fprintd 2>/dev/null || true\n")
                    # Remove root-owned build files (meson creates these under sudo)
                    f.write(f"rm -rf {shlex.quote(os.path.join(project_dir, 'libfprint-CS9711', 'builddir'))} 2>/dev/null || true\n")
                os.chmod(tmp_script, 0o700)

                GLib.idle_add(_update, 0.3, "Step 2/5 — Removing driver (enter password)...")
                log.info("Uninstall step 2/5: running pkexec (password prompt expected)")

                # Step 2: Run via pkexec
                rc, out, err = run_cmd(["pkexec", tmp_script], timeout=120)
            finally:
                try:
                    os.remove(tmp_script)
                except FileNotFoundError:
                    pass

            # Abort if user cancelled pkexec or script failed
            log.info(f"Uninstall pkexec result: rc={rc}")
            if rc != 0:
                log.warning("Uninstall aborted — pkexec cancelled or failed")
                def _aborted():
                    self.uninstall_progress.set_fraction(0)
                    self.uninstall_progress.set_text("Uninstall cancelled — no changes made")
                    self.show_toast("Uninstall cancelled")
                    return False
                GLib.idle_add(_aborted)
                return

            GLib.idle_add(_update, 0.5, "Step 3/5 — Restoring stock driver...")
            time.sleep(0.5)

            GLib.idle_add(_update, 0.7, "Step 4/5 — Removing desktop shortcut...")

            # Step 3: Remove desktop shortcut
            try:
                os.remove(desktop_file)
            except FileNotFoundError:
                pass

            GLib.idle_add(_update, 0.9, "Step 5/5 — Removing project files...")

            # Step 4: Create cleanup script to delete project folder after GUI exits
            # Root-owned builddir/ was already removed in the pkexec step above
            fd2, cleanup_script = tempfile.mkstemp(prefix="cs9711-cleanup-", suffix=".sh")
            with os.fdopen(fd2, "w") as f:
                f.write("#!/bin/bash\n")
                f.write(f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.5; done\n")
                f.write(f"rm -rf {shlex.quote(project_dir)}\n")
                f.write(f"rm -f {shlex.quote(cleanup_script)}\n")
            os.chmod(cleanup_script, 0o700)

            # Launch cleanup and close GUI
            log.info(f"Uninstall step 5/5: launching cleanup script, GUI closing in 3s")
            subprocess.Popen([cleanup_script])
            def _done():
                self.uninstall_progress.set_fraction(1.0)
                self.uninstall_progress.set_text("Uninstall complete — closing in 3 seconds...")
                self.show_toast("Uninstall complete — everything removed")
                GLib.timeout_add(3000, lambda: self.close() or False)
                return False
            GLib.idle_add(_done)

        threading.Thread(target=do_uninstall, daemon=True).start()

    def on_keyring(self, btn):
        helper = os.path.join(SCRIPT_DIR, "helpers", "set-empty-keyring-password.py")
        if not os.path.exists(helper):
            self.show_toast("Keyring helper not found")
            return

        # Needs a terminal for password input — try common terminal emulators
        terminals = [
            ["ptyxis", "--"],
            ["gnome-terminal", "--"],
            ["kgx", "--"],
            ["konsole", "-e"],
            ["xfce4-terminal", "-e"],
            ["xterm", "-e"],
        ]
        cmd = ["python3", helper]
        for term in terminals:
            term_bin = term[0]
            if subprocess.run(["which", term_bin], capture_output=True).returncode == 0:
                subprocess.Popen(term + cmd)
                self.show_toast(f"Keyring helper opened in {term_bin}")
                return
        # Fallback: tell user to run manually
        self.show_toast("No terminal found — run manually: python3 helpers/set-empty-keyring-password.py")

    def on_about(self, btn):
        """Author credit, project links and licence.

        Adw.AboutDialog is libadwaita 1.5+; AboutWindow is the 1.2 equivalent
        and is used as the fallback so the button still works on older
        distributions rather than raising.
        """
        fields = dict(
            application_name="CS9711 Fingerprint Manager",
            application_icon=APP_ID,
            version=APP_VERSION,
            developer_name=APP_AUTHOR,
            # libadwaita renders "Name <mail>" as a mailto link in the credits
            developers=[f"{APP_AUTHOR} <{APP_AUTHOR_EMAIL}>"],
            license_type=Gtk.License.MIT_X11,
            website=PROJECT_URL,
            issue_url=f"{PROJECT_URL}/issues",
            copyright=f"© 2026 {APP_AUTHOR}",
            comments=(
                "Driver installer and manager for the Chipsailing CS9711 "
                "fingerprint scanner (USB 2541:0236) on Linux.\n\n"
                "This manager and the installer scripts are MIT licensed. The "
                "patched libfprint driver it builds is LGPL-2.1-or-later, from "
                "the archeYR/libfprint-CS9711 community fork."
            ),
        )
        def links(d):
            d.add_link("Developer on GitHub", AUTHOR_URL)
            d.add_link("Report an issue", f"{PROJECT_URL}/issues")
            d.add_link("Upstream driver", "https://github.com/archeYR/libfprint-CS9711")

        if hasattr(Adw, "AboutDialog"):
            dlg = Adw.AboutDialog(**fields)
            links(dlg)
            dlg.present(self)
        else:
            dlg = Adw.AboutWindow(transient_for=self, **fields)
            links(dlg)
            dlg.present()

    def on_view_log(self, btn):
        log.info("User opened log viewer")
        try:
            with open(LOG_FILE) as f:
                content = f.read()
        except FileNotFoundError:
            content = "(No log file yet)"

        # Build a scrollable text window
        dialog = Adw.Dialog()
        dialog.set_title("Activity Log")
        dialog.set_content_width(750)
        dialog.set_content_height(500)

        toolbar_view = Adw.ToolbarView()
        dialog.set_child(toolbar_view)

        header = Adw.HeaderBar()
        # Copy to clipboard button
        copy_btn = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copy log to clipboard")
        header.pack_end(copy_btn)
        toolbar_view.add_top_bar(header)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        text_view = Gtk.TextView(editable=False, monospace=True,
                                  wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                  top_margin=8, bottom_margin=8,
                                  left_margin=8, right_margin=8)
        text_view.get_buffer().set_text(content)
        scroll.set_child(text_view)
        toolbar_view.set_content(scroll)

        # Scroll to bottom
        def _scroll_to_end(*args):
            adj = scroll.get_vadjustment()
            adj.set_value(adj.get_upper())
            return False
        GLib.idle_add(_scroll_to_end)

        def _copy(*args):
            clipboard = self.get_clipboard()
            clipboard.set(content)
            self.show_toast("Log copied to clipboard")
        copy_btn.connect("clicked", _copy)

        dialog.present(self)

    def on_clear_log(self, btn):
        log.info("User cleared log")
        # Close and reopen the file handler to truncate
        for handler in log.handlers:
            if isinstance(handler, RotatingFileHandler):
                handler.close()
                log.removeHandler(handler)
        # Truncate the log file
        with open(LOG_FILE, "w") as f:
            f.write("")
        # Re-add the handler
        fh = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        ))
        log.addHandler(fh)
        log.info(f"=== Log cleared — CS9711 Fingerprint Manager v{APP_VERSION} ===")
        self.show_toast("Log cleared")

    def _maintenance_done(self, btn, label, message, success):
        btn.set_sensitive(True)
        btn.set_label(label)
        self.show_toast(message)
        if success:
            self.refresh_all()
        return False

    # ========================================================================
    # Refresh all
    # ========================================================================

    def refresh_all(self):
        """Refresh all sections from system state."""

        def do_refresh():
            # Gather all data in background
            scanner = is_scanner_connected()
            driver = is_driver_installed()
            # Only pay for the ldd health probe when fprintd can't see the
            # device — that's exactly the state a stranded driver produces.
            health = ("ok", "") if driver else driver_health()
            fingers = get_enrolled_fingers()
            delay = get_retry_delay()
            max_tries, timeout, pam_file = get_pam_settings()
            auth_locs = get_pam_auth_locations()

            # Update UI on main thread
            GLib.idle_add(self._apply_refresh, scanner, driver, health, fingers,
                          delay, max_tries, timeout, auth_locs)

        threading.Thread(target=do_refresh, daemon=True).start()

    def _apply_refresh(self, scanner, driver, health, fingers, delay, max_tries, timeout, auth_locs):
        friendly_fingers = [FINGER_NAMES.get(f, f) for f in fingers]
        broken = (not driver) and health[0] == "broken"

        # ---- hero card: headline states the ONE thing that matters ----
        # Icon names go through the theme probe — hardcoding Adwaita's
        # auth-fingerprint-symbolic here renders a broken-image glyph on KDE
        # Breeze, which ships fingerprint-symbolic instead.
        ok_icon, warn_icon = icon_fingerprint(), icon_warning()
        if broken:
            # A system library the driver links against was upgraded away
            # (usually an OpenCV 4 -> 5 bump). Rebuilding relinks against the
            # new version — do NOT chase USB/cable ghosts in this state.
            title, sub, icon = (
                "Driver needs rebuilding",
                f"Missing {health[1]} — a system library the driver was built "
                "against was upgraded. Rebuild to relink against the new one.",
                warn_icon,
            )
        elif not scanner:
            title, sub, icon = (
                "Scanner not detected",
                "Check the USB connection. If it plugs into a keyboard hub, the "
                "keyboard must be connected by cable, not wirelessly.",
                warn_icon,
            )
        elif not driver:
            title, sub, icon = (
                "Driver not installed",
                "Run install.sh, or use Rebuild Driver below if it was working before.",
                warn_icon,
            )
        elif not fingers:
            title, sub, icon = (
                "Ready to set up",
                "Scanner and driver are working — enrol a finger to start using it.",
                ok_icon,
            )
        else:
            enabled = [n for n, on in auth_locs.items() if on]
            title = "Fingerprint is ready"
            sub = (
                f"Active for {', '.join(enabled)}."
                if enabled
                else "Enrolled, but not switched on anywhere yet — see Where to Use Fingerprint."
            )
            icon = ok_icon

        self.hero_title.set_label(title)
        self.hero_sub.set_label(sub)
        self.hero_icon.set_from_icon_name(icon)
        for c in ("success", "warning", "error"):
            self.hero_icon.remove_css_class(c)
        self.hero_icon.add_css_class(
            "error" if broken or not scanner else ("warning" if not driver or not fingers else "success")
        )

        set_pill(self.pill_scanner, "Scanner ✓" if scanner else "Scanner ✕",
                 "ok" if scanner else "bad")
        set_pill(self.pill_driver,
                 "Driver ✓" if driver else ("Driver broken" if broken else "Driver ✕"),
                 "ok" if driver else "bad")
        set_pill(self.pill_fingers,
                 f"{len(fingers)} finger(s)" if fingers else "No fingers",
                 "ok" if fingers else "idle")

        # Banner carries the actionable failure to the top of the window
        if broken:
            self.health_banner.set_title(
                f"Driver cannot load — missing {health[1]} (system OpenCV upgrade?)"
            )
            self.health_banner.set_revealed(True)
        else:
            self.health_banner.set_revealed(False)

        # Enrollment status banner + button label
        if fingers:
            self._has_enrolled_fingers = True
            self.enroll_btn.set_label("Add Another Finger")
            self.enroll_status_row.set_title("Enrolled")
            self.enroll_status_row.set_subtitle(
                f"{len(fingers)} finger(s): {', '.join(friendly_fingers)}"
            )
        else:
            self._has_enrolled_fingers = False
            self.enroll_btn.set_label("Enroll")
            self.enroll_status_row.set_title("Not Enrolled")
            self.enroll_status_row.set_subtitle(
                "No fingerprints enrolled — click Enroll to get started"
            )

        # Scan settings
        self.delay_adj.set_value(delay)
        self._original_delay = delay
        self.rebuild_notice.set_visible(False)

        # PAM settings
        self.tries_adj.set_value(max_tries)
        self.timeout_adj.set_value(timeout)

        # Auth locations (independent per-service switches)
        self._set_auth_switches(auth_locs)

        # First-launch enrollment prompt — only once, only if no fingers enrolled
        if not self._first_refresh_done:
            self._first_refresh_done = True
            if not fingers and scanner:
                self._check_first_launch()


# ============================================================================
# Entry point
# ============================================================================


def main():
    # Allow Ctrl+C to work
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = CS9711ManagerApp()
    app.run(None)


if __name__ == "__main__":
    main()
