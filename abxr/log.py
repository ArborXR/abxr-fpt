#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#
"""Logging that says which headset a line is about, when several are provisioned at once."""

import threading

_current = threading.local()


def set_serial(serial):
    """Tag every log() call on this thread with a headset's serial."""
    _current.serial = serial


def log(message):
    serial = getattr(_current, "serial", None)
    print(f"[{serial}] {message}" if serial else message, flush=True)
