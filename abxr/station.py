#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#
"""Provisioning several headsets at once, in one process.

Work on a headset is almost all waiting on adb, so one thread per headset runs them in parallel on one adb server,
as the Device Setup App does. A headset that's done isn't touched again until it's been unplugged for a while.
"""

import subprocess
import threading
import time

from abxr.log import log as print_log
from abxr.log import set_serial

RUNNING = "running"
DONE = "done"
FAILED = "failed"
NOT_READY = "not-ready"

# How long --once waits for a headset that adb sees but can't use yet (e.g. "Allow USB debugging" not tapped).
NOT_READY_WAIT_SECONDS = 60

# A finished headset is forgotten, so plugging it back in provisions it again, only after it's been gone this long.
# Long enough to ride out a reboot (the VIVE Flow reboots at the end) or a USB hiccup.
FORGET_DONE_AFTER_SECONDS = 120
# A failed or not-ready headset is forgotten quickly, so replugging it is how an operator retries it.
FORGET_OTHER_AFTER_SECONDS = 4

NOT_READY_MESSAGES = {
    "unauthorized": 'Tap "Allow USB debugging" and "Always allow from this computer" on the headset.',
    "no permissions": "adb can't open this headset. On Linux, add udev rules for it.",
    "offline": "adb sees the headset but it's offline. Replug it or restart it.",
    "authorizing": "Waiting for the headset to finish authorizing USB debugging.",
}


def parse_adb_devices(adb_devices_output):
    """(serial, state) for each line of `adb devices`, e.g. ("2G0YC5ZH9M05BX", "device") or (..., "unauthorized")."""
    devices = []
    for line in adb_devices_output.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            devices.append((parts[0], parts[1].strip()))
    return devices


def list_adb_devices():
    """The connected headsets, or None when adb couldn't answer (so a failed poll isn't read as "all unplugged")."""
    try:
        proc = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode or "List of devices" not in proc.stdout:
        return None
    return parse_adb_devices(proc.stdout)


class Station:
    def __init__(self, run, max_parallel=8, only_serial=None, clock=time.monotonic):
        """run(serial, log) provisions one headset and returns True on success, or (ok, reason) to give a short
        failure reason for the display. It's called on its own thread."""
        self._run = run
        self._slots = threading.BoundedSemaphore(max_parallel)
        self._only_serial = only_serial
        self._clock = clock
        self._lock = threading.Lock()
        self._states = {}
        self._adb_states = {}
        self._last_seen = {}
        self._not_ready_since = {}
        self._results = {}
        self._active = 0
        self._stopping = False
        self._threads = []
        self.last_failure = None

    def update(self, devices):
        """Start work for newly connected headsets. devices is [(serial, adb state)] from `adb devices`, or None
        when adb couldn't answer, in which case nothing changes."""
        if devices is None:
            return
        now = self._clock()
        connected = dict(devices)

        with self._lock:
            for serial in connected:
                self._last_seen[serial] = now

            for serial in list(self._states):
                state = self._states[serial]
                if serial in connected or state == RUNNING:
                    continue
                limit = FORGET_DONE_AFTER_SECONDS if state == DONE else FORGET_OTHER_AFTER_SECONDS
                if now - self._last_seen.get(serial, now) >= limit:
                    del self._states[serial]
                    self._adb_states.pop(serial, None)
                    self._not_ready_since.pop(serial, None)

            for serial, adb_state in devices:
                if self._only_serial and serial != self._only_serial:
                    continue
                current = self._states.get(serial)
                if current in (RUNNING, DONE, FAILED):
                    continue

                if adb_state != "device":
                    if current != NOT_READY or self._adb_states.get(serial) != adb_state:
                        self._states[serial] = NOT_READY
                        self._adb_states[serial] = adb_state
                        self._not_ready_since.setdefault(serial, now)
                        message = NOT_READY_MESSAGES.get(adb_state, f"adb reports it as \"{adb_state}\".")
                        print(f"[{serial}] {message}", flush=True)
                    continue

                if self._stopping:
                    continue

                self._states[serial] = RUNNING
                self._adb_states.pop(serial, None)
                self._not_ready_since.pop(serial, None)
                thread = threading.Thread(target=self._work, args=(serial,), daemon=True)
                self._threads.append(thread)
                thread.start()

    def _work(self, serial):
        set_serial(serial)
        last_message = [""]

        def log(message):
            last_message[0] = message
            print_log(message)

        ok, reason = False, None
        with self._slots:
            with self._lock:
                self._active += 1
            try:
                result = self._run(serial, log)
                ok, reason = result if isinstance(result, tuple) else (bool(result), None)
            except Exception as e:
                log(f"Unhandled error: {e}")
            finally:
                with self._lock:
                    self._active -= 1
                    self._states[serial] = DONE if ok else FAILED
                    self._results[serial] = DONE if ok else FAILED
                    if not ok:
                        self.last_failure = (serial, reason or last_message[0])

    def stop(self):
        """Start no new headsets. Running ones carry on."""
        with self._lock:
            self._stopping = True

    def running_count(self):
        with self._lock:
            return sum(1 for state in self._states.values() if state == RUNNING)

    def failed_count(self):
        with self._lock:
            return sum(1 for state in self._states.values() if state == FAILED)

    def is_idle(self):
        """Nothing is running, and no headset adb can't use yet is still within its wait."""
        with self._lock:
            if any(state == RUNNING for state in self._states.values()):
                return False
            now = self._clock()
            return all(
                now - since >= NOT_READY_WAIT_SECONDS
                for serial, since in self._not_ready_since.items()
                if self._states.get(serial) == NOT_READY
            )

    def all_succeeded(self):
        """For --once: every headset seen was provisioned. One that failed, or that adb never let us use, wasn't."""
        with self._lock:
            never_ready = any(state == NOT_READY for state in self._states.values())
            return not never_ready and all(result == DONE for result in self._results.values())

    def counts(self):
        with self._lock:
            counts = {RUNNING: 0, DONE: 0, FAILED: 0, NOT_READY: 0}
            for state in self._states.values():
                counts[state] += 1
            counts["active"] = self._active
            return counts

    def summary(self):
        counts = self.counts()
        queued = counts[RUNNING] - counts["active"]
        parts = [f"{counts['active']} running"]
        if queued:
            parts.append(f"{queued} queued")
        parts += [f"{counts[DONE]} done", f"{counts[FAILED]} failed"]
        if counts[NOT_READY]:
            parts.append(f"{counts[NOT_READY]} not ready (check the headset)")
        return ", ".join(parts)

    def display_lines(self):
        """At most 4 short lines for the FPD's 128x32 display (21 characters each)."""
        counts = self.counts()
        queued = counts[RUNNING] - counts["active"]
        lines = [
            f"Run {counts['active']}  Queue {queued}"[:21],
            f"Done {counts[DONE]}  Failed {counts[FAILED]}"[:21],
        ]
        if counts[NOT_READY]:
            lines.append(f"Not ready {counts[NOT_READY]}: check"[:21])
        if self.last_failure:
            serial, message = self.last_failure
            lines.append(f"{serial[-5:]}: {message}"[:21])
        return lines[:4]

    def join(self, timeout=None):
        for thread in list(self._threads):
            thread.join(timeout)
