#!/usr/bin/env python3
"""
Set GNOME Login Keyring password to empty via D-Bus Secret Service API.
This enables auto-unlock on fingerprint login.

Usage: python3 set-empty-keyring-password.py
"""

import dbus
import getpass
import sys

SERVICE_NAME = "org.freedesktop.secrets"
SERVICE_PATH = "/org/freedesktop/secrets"
SERVICE_IFACE = "org.freedesktop.Secret.Service"
INTERNAL_IFACE = "org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface"
COLLECTION_PATH = "/org/freedesktop/secrets/collection/login"

def main():
    print("=== Set Empty Keyring Password (D-Bus API) ===")
    print()

    # Connect to session bus
    bus = dbus.SessionBus()
    service_obj = bus.get_object(SERVICE_NAME, SERVICE_PATH)

    # Open a plain-text session (no encryption needed for local D-Bus)
    service_iface = dbus.Interface(service_obj, SERVICE_IFACE)
    output, session_path = service_iface.OpenSession(
        "plain",                    # algorithm
        dbus.String("", variant_level=1)  # input (empty for plain)
    )

    print(f"Session: {session_path}")
    print(f"Collection: {COLLECTION_PATH}")
    print()

    # Get current password
    current_pw = getpass.getpass("Enter your CURRENT keyring password: ")

    # Build Secret structs: (session_path, params, value, content_type)
    # For "plain" algorithm, params is empty byte array
    old_secret = dbus.Struct([
        dbus.ObjectPath(session_path),
        dbus.ByteArray(b""),               # params (empty for plain)
        dbus.ByteArray(current_pw.encode("utf-8")),  # the password
        dbus.String("text/plain"),         # content type
    ], signature="oayays")

    new_secret = dbus.Struct([
        dbus.ObjectPath(session_path),
        dbus.ByteArray(b""),               # params
        dbus.ByteArray(b""),               # empty password
        dbus.String("text/plain"),
    ], signature="oayays")

    # Call ChangeWithMasterPassword
    internal_iface = dbus.Interface(service_obj, INTERNAL_IFACE)
    try:
        internal_iface.ChangeWithMasterPassword(
            dbus.ObjectPath(COLLECTION_PATH),
            old_secret,
            new_secret,
        )
        print()
        print("SUCCESS: Login keyring password is now empty.")
        print("It will auto-unlock on every login (fingerprint or password).")
        print()
        print("Reboot and log in with your fingerprint to verify.")
    except dbus.exceptions.DBusException as e:
        print()
        print(f"FAILED: {e.get_dbus_message()}")
        if "password" in str(e).lower() or "denied" in str(e).lower():
            print("The current password was probably wrong. Try again.")
        sys.exit(1)

if __name__ == "__main__":
    main()
