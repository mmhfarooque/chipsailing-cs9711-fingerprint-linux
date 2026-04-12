#!/usr/bin/env python3
"""
CS9711 Fingerprint Manager — GUI for Chipsailing CS9711 fingerprint scanner.

Controls: retry delay, PAM attempts/timeout, auth locations, enrollment,
driver maintenance. Uses GTK4 + libadwaita for native GNOME look.
"""

import gi
import os
import re
import signal
import subprocess
import threading

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

APP_ID = "com.github.mmhfarooque.cs9711-manager"
USB_ID = "2541:0236"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DRIVER_DIR = os.path.join(SCRIPT_DIR, "libfprint-CS9711")
CS9711_SRC = os.path.join(DRIVER_DIR, "libfprint", "drivers", "cs9711", "cs9711.c")

def get_app_version():
    """Read version from VERSION file."""
    try:
        with open(os.path.join(SCRIPT_DIR, "VERSION")) as f:
            return f.read().strip()
    except FileNotFoundError:
        return "dev"

APP_VERSION = get_app_version()

PAM_FILES = [
    "/etc/pam.d/common-auth",
    "/etc/pam.d/system-auth",
    "/etc/pam.d/fingerprint-auth",
]

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


# ============================================================================
# Helper functions — read system state
# ============================================================================


def run_cmd(cmd, timeout=10):
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, "", str(e)


def is_scanner_connected():
    rc, out, _ = run_cmd(["lsusb"])
    return USB_ID in out if rc == 0 else False


def is_driver_installed():
    rc, out, err = run_cmd(["fprintd-list", os.environ.get("USER", "nobody")])
    combined = f"{out} {err}".lower()
    return "cs9711" in combined or "9711" in combined or "chipsailing" in combined


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


def get_pam_settings():
    """Read max-tries and timeout from PAM config."""
    max_tries = 1
    timeout = 10
    for pam_file in PAM_FILES:
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
        except FileNotFoundError:
            continue
    return max_tries, timeout, None


def get_pam_auth_locations():
    """Check which PAM services have fingerprint enabled."""
    locations = {}
    services = {
        "Login screen": ["/etc/pam.d/gdm-password", "/etc/pam.d/gdm-fingerprint",
                         "/etc/pam.d/sddm", "/etc/pam.d/lightdm"],
        "Lock screen": ["/etc/pam.d/gdm-password", "/etc/pam.d/gdm-fingerprint",
                        "/etc/pam.d/kde"],
        "sudo": ["/etc/pam.d/sudo", "/etc/pam.d/common-auth", "/etc/pam.d/system-auth"],
        "polkit": ["/etc/pam.d/polkit-1"],
    }
    for name, paths in services.items():
        enabled = False
        for path in paths:
            try:
                with open(path) as f:
                    content = f.read()
                    if "pam_fprintd.so" in content or "common-auth" in content or "system-auth" in content:
                        enabled = True
                        break
            except FileNotFoundError:
                continue
        locations[name] = enabled
    return locations


def run_as_root(cmd_str):
    """Run a shell command as root via pkexec."""
    return run_cmd(["pkexec", "bash", "-c", cmd_str], timeout=60)


# ============================================================================
# Main Application
# ============================================================================


class CS9711ManagerApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.connect("activate", self.on_activate)

    def on_activate(self, app):
        self.win = CS9711Window(application=app)
        self.win.present()


class CS9711Window(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title(f"CS9711 Fingerprint Manager v{APP_VERSION}")
        self.set_default_size(680, 780)

        # Enroll process tracking
        self._enroll_process = None
        self._enroll_cancel = False

        # Main layout
        self.toolbar_view = Adw.ToolbarView()
        self.set_content(self.toolbar_view)

        # Header bar
        header = Adw.HeaderBar()
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh status")
        refresh_btn.connect("clicked", lambda _: self.refresh_all())
        header.pack_end(refresh_btn)
        self.toolbar_view.add_top_bar(header)

        # Scrollable content
        scroll = Gtk.ScrolledWindow(vexpand=True)
        self.toolbar_view.set_content(scroll)

        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main_box.set_margin_start(16)
        main_box.set_margin_end(16)
        main_box.set_margin_top(8)
        main_box.set_margin_bottom(16)
        scroll.set_child(main_box)

        # Build all sections
        self.build_status_section(main_box)
        self.build_enrollment_section(main_box)
        self.build_scan_settings_section(main_box)
        self.build_pam_settings_section(main_box)
        self.build_auth_section(main_box)
        self.build_maintenance_section(main_box)

        # Toast overlay for notifications
        self.toast_overlay = Adw.ToastOverlay()
        content = self.toolbar_view.get_content()
        self.toolbar_view.set_content(self.toast_overlay)
        self.toast_overlay.set_child(content)

        # Initial data load
        self.refresh_all()

    def show_toast(self, message):
        toast = Adw.Toast(title=message, timeout=3)
        self.toast_overlay.add_toast(toast)

    # ========================================================================
    # Status Section
    # ========================================================================

    def build_status_section(self, parent):
        group = Adw.PreferencesGroup(title="Status")
        parent.append(group)

        self.status_scanner = Adw.ActionRow(title="Scanner", subtitle="Checking...")
        self.status_scanner.add_prefix(Gtk.Image.new_from_icon_name("drive-removable-media-symbolic"))
        group.add(self.status_scanner)

        self.status_driver = Adw.ActionRow(title="Driver", subtitle="Checking...")
        self.status_driver.add_prefix(Gtk.Image.new_from_icon_name("emblem-system-symbolic"))
        group.add(self.status_driver)

        self.status_fingers = Adw.ActionRow(title="Enrolled Fingers", subtitle="Checking...")
        self.status_fingers.add_prefix(Gtk.Image.new_from_icon_name("contact-new-symbolic"))
        group.add(self.status_fingers)

    def refresh_status(self):
        # Scanner
        connected = is_scanner_connected()
        self.status_scanner.set_subtitle(
            "Connected (USB 2541:0236)" if connected else "Not detected — check USB"
        )

        # Driver
        installed = is_driver_installed()
        self.status_driver.set_subtitle(
            "Installed and working" if installed else "Not installed or scanner not detected"
        )

        # Fingers
        fingers = get_enrolled_fingers()
        if fingers:
            self.status_fingers.set_subtitle(", ".join(fingers))
            self._has_enrolled_fingers = True
            self.enroll_btn.set_label("Add Another Finger")
            self.enroll_status_row.set_title("Enrolled")
            self.enroll_status_row.set_subtitle(
                f"{len(fingers)} finger(s) enrolled: {', '.join(fingers)}"
            )
        else:
            self.status_fingers.set_subtitle("None enrolled")
            self._has_enrolled_fingers = False
            self.enroll_btn.set_label("Enroll")
            self.enroll_status_row.set_title("Not Enrolled")
            self.enroll_status_row.set_subtitle(
                "No fingerprints enrolled yet — enroll below to get started"
            )

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
        if response == "add":
            self._start_enroll()

    def _start_enroll(self):
        idx = self.finger_dropdown.get_selected()
        finger_id = FINGERS[idx][0]
        finger_name = FINGERS[idx][1]

        self.enroll_progress.set_visible(True)
        self.enroll_progress.set_fraction(0)
        self.enroll_progress.set_text(f"Enrolling {finger_name}... Touch the scanner")
        self.enroll_btn.set_sensitive(False)
        self.cancel_enroll_btn.set_visible(True)
        self._enroll_cancel = False

        def do_enroll():
            try:
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
        self.enroll_progress.set_fraction(1.0 if success else 0)
        self.enroll_btn.set_sensitive(True)
        self.cancel_enroll_btn.set_visible(False)
        self._enroll_process = None
        if success:
            self.enroll_progress.set_text("Enrollment complete! Now verify — touch the scanner...")
            self.show_toast("Enrollment complete! Verifying...")
            self.refresh_status()
            # Auto-trigger verification after successful enrollment
            GLib.timeout_add(1500, self._auto_verify_after_enroll)
        else:
            self.enroll_progress.set_text(message)
            self.show_toast(message)
        return False

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
        self._enroll_cancel = True
        if self._enroll_process:
            try:
                self._enroll_process.terminate()
            except ProcessLookupError:
                pass

    def on_verify(self, btn):
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
        self.enroll_progress.set_text(message)
        self.enroll_progress.set_fraction(1.0 if success else 0)
        self.verify_btn.set_sensitive(True)
        self.show_toast(message)
        return False

    def on_delete_fingers(self, btn):
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
        user = os.environ.get("USER", "nobody")
        rc, out, err = run_cmd(["fprintd-delete", user])
        if rc == 0:
            self.show_toast("All fingerprints deleted")
        else:
            self.show_toast(f"Delete failed: {err}")
        self.refresh_status()

    # ========================================================================
    # Scan Settings Section
    # ========================================================================

    def build_scan_settings_section(self, parent):
        group = Adw.PreferencesGroup(
            title="Scan Settings",
            description="Controls how the scanner behaves between retries",
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

    def build_pam_settings_section(self, parent):
        group = Adw.PreferencesGroup(
            title="Authentication Settings",
            description="How many fingerprint attempts before falling back to password",
        )
        parent.append(group)

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

        # Apply button
        apply_row = Adw.ActionRow(title="")
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

        _, _, pam_file = get_pam_settings()
        if not pam_file:
            # Try common-auth as default
            pam_file = "/etc/pam.d/common-auth"

        cmd = (
            f"sed -i 's/pam_fprintd.so.*/pam_fprintd.so "
            f"max-tries={max_tries} timeout={timeout}/' '{pam_file}'"
        )
        rc, _, err = run_as_root(cmd)
        if rc == 0:
            self.show_toast(f"PAM updated: {max_tries} tries, {timeout}s timeout")
        else:
            self.show_toast(f"Failed: {err[:80]}")

    # ========================================================================
    # Auth Locations Section
    # ========================================================================

    def build_auth_section(self, parent):
        group = Adw.PreferencesGroup(
            title="Where to Use Fingerprint",
            description="Fingerprint auth is controlled by PAM — these show current status",
        )
        parent.append(group)

        self.auth_rows = {}
        icons = {
            "Login screen": "system-users-symbolic",
            "Lock screen": "system-lock-screen-symbolic",
            "sudo": "utilities-terminal-symbolic",
            "polkit": "dialog-password-symbolic",
        }

        for name, icon in icons.items():
            row = Adw.ActionRow(title=name, subtitle="Checking...")
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            self.auth_rows[name] = row
            group.add(row)

    def refresh_auth_locations(self):
        locations = get_pam_auth_locations()
        for name, row in self.auth_rows.items():
            enabled = locations.get(name, False)
            row.set_subtitle("Enabled" if enabled else "Not configured")

    # ========================================================================
    # Maintenance Section
    # ========================================================================

    def build_maintenance_section(self, parent):
        group = Adw.PreferencesGroup(title="Maintenance")
        parent.append(group)

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

        # Full reinstall
        reinstall_row = Adw.ActionRow(
            title="Full Install",
            subtitle="Fresh clone, patch, build, and install from scratch",
        )
        reinstall_row.add_prefix(Gtk.Image.new_from_icon_name("emblem-downloads-symbolic"))
        reinstall_btn = Gtk.Button(label="Install", valign=Gtk.Align.CENTER)
        reinstall_btn.connect("clicked", self.on_full_install)
        reinstall_row.add_suffix(reinstall_btn)
        group.add(reinstall_row)
        self._maintenance_install_btn = reinstall_btn

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

    def on_rebuild_driver(self, btn):
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

    def on_full_install(self, btn):
        btn.set_sensitive(False)
        btn.set_label("Installing...")
        self.show_toast("Running full install — this may take several minutes...")

        def do_install():
            script = os.path.join(SCRIPT_DIR, "install.sh")
            rc, out, err = run_cmd(["pkexec", "bash", script], timeout=600)
            if rc == 0:
                GLib.idle_add(self._maintenance_done, btn, "Install", "Installation complete!", True)
            else:
                GLib.idle_add(self._maintenance_done, btn, "Install", f"Failed: {err[:80]}", False)

        threading.Thread(target=do_install, daemon=True).start()

    def on_uninstall(self, btn):
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
        if response != "uninstall":
            return

        project_dir = SCRIPT_DIR
        desktop_file = os.path.expanduser("~/.local/share/applications/cs9711-manager.desktop")

        def do_uninstall():
            # Step 1: Remove driver (needs sudo)
            uninstall_script = os.path.join(project_dir, "uninstall.sh")
            # Run uninstall.sh but pipe "n" to skip the folder delete prompt
            # (we'll handle folder deletion ourselves after closing the GUI)
            rc, out, err = run_cmd(
                ["bash", "-c", f"echo n | bash '{uninstall_script}'"],
                timeout=120,
            )

            # Step 2: Remove desktop shortcut
            try:
                os.remove(desktop_file)
            except FileNotFoundError:
                pass

            # Step 3: Create a self-destruct script that runs after GUI closes
            cleanup_script = "/tmp/cs9711-cleanup.sh"
            with open(cleanup_script, "w") as f:
                f.write("#!/bin/bash\n")
                f.write("sleep 2\n")
                f.write(f"rm -rf '{project_dir}'\n")
                f.write(f"rm -f '{cleanup_script}'\n")
            os.chmod(cleanup_script, 0o755)

            if rc == 0:
                # Launch cleanup and close GUI
                subprocess.Popen([cleanup_script])
                def _done():
                    self.show_toast("Uninstall complete — closing...")
                    GLib.timeout_add(2000, lambda: self.close() or False)
                    return False
                GLib.idle_add(_done)
            else:
                GLib.idle_add(lambda: (self.show_toast(f"Uninstall failed: {err[:80]}"), False)[-1])

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
            fingers = get_enrolled_fingers()
            delay = get_retry_delay()
            max_tries, timeout, pam_file = get_pam_settings()
            auth_locs = get_pam_auth_locations()

            # Update UI on main thread
            GLib.idle_add(self._apply_refresh, scanner, driver, fingers,
                          delay, max_tries, timeout, auth_locs)

        threading.Thread(target=do_refresh, daemon=True).start()

    def _apply_refresh(self, scanner, driver, fingers, delay, max_tries, timeout, auth_locs):
        # Status
        self.status_scanner.set_subtitle(
            "Connected (USB 2541:0236)" if scanner else "Not detected — check USB"
        )
        self.status_driver.set_subtitle(
            "Installed and working" if driver else "Not installed or scanner not detected"
        )
        self.status_fingers.set_subtitle(
            ", ".join(fingers) if fingers else "None enrolled"
        )

        # Scan settings
        self.delay_adj.set_value(delay)
        self._original_delay = delay
        self.rebuild_notice.set_visible(False)

        # PAM settings
        self.tries_adj.set_value(max_tries)
        self.timeout_adj.set_value(timeout)

        # Auth locations
        for name, row in self.auth_rows.items():
            enabled = auth_locs.get(name, False)
            row.set_subtitle("Enabled" if enabled else "Not configured")


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
