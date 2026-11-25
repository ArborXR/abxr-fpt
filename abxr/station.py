#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#
"""Provisioning several headsets at once, in one process.

Work on a headset is almost all waiting on adb, so one thread per headset runs them in parallel on one adb server,
as the Device Setup App does. A headset that's done or failed isn't touched again until it's unplugged.
"""

import subprocess
import threading
import time

RUNNING = "running"
DONE = "done"
FAILED = "failed"
UNAUTHORIZED = "unauthorized"

# How long --once waits for someone to tap "Allow USB debugging" on a headset before giving up on it.
ALLOW_WAIT_SECONDS = 60


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
    proc = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    if proc.returncode:
        return []
    return parse_adb_devices(proc.stdout)


class Station:
    def __init__(self, run, max_parallel=8, only_serial=None, clock=time.monotonic):
        """run(serial, log) provisions one headset and returns True on success. It's called on its own thread."""
        self._run = run
        self._slots = threading.BoundedSemaphore(max_parallel)
        self._only_serial = only_serial
        self._clock = clock
        self._lock = threading.Lock()
        self._states = {}
        self._active = 0
        self._waiting_since = {}
        self._threads = []

    def update(self, devices):
        """Start work for newly connected headsets. devices is [(serial, adb state)] from `adb devices`."""
        connected = dict(devices)
        with self._lock:
            # Forget finished headsets that were unplugged, so plugging one back in provisions it again.
            for serial in list(self._states):
                if serial not in connected and self._states[serial] != RUNNING:
                    del self._states[serial]
                    self._waiting_since.pop(serial, None)

            for serial, state in devices:
                if self._only_serial and serial != self._only_serial:
                    continue
                current = self._states.get(serial)

                if state == "unauthorized":
                    if current is None:
                        self._states[serial] = UNAUTHORIZED
                        self._waiting_since[serial] = self._clock()
                        print(f"[{serial}] Tap \"Allow USB debugging\" and \"Always allow from this computer\" on the headset.", flush=True)
                    continue
                if state != "device" or current in (RUNNING, DONE, FAILED):
                    continue

                self._states[serial] = RUNNING
                self._waiting_since.pop(serial, None)
                thread = threading.Thread(target=self._work, args=(serial,), daemon=True)
                self._threads.append(thread)
                thread.start()

    def _work(self, serial):
        def log(message):
            print(f"[{serial}] {message}", flush=True)

        with self._slots:
            with self._lock:
                self._active += 1
            try:
                ok = self._run(serial, log)
            except Exception as e:
                log(f"Unhandled error: {e}")
                ok = False
            finally:
                with self._lock:
                    self._active -= 1
                    self._states[serial] = DONE if ok else FAILED

    def _count(self, state):
        with self._lock:
            return sum(1 for value in self._states.values() if value == state)

    def running_count(self):
        return self._count(RUNNING)

    def failed_count(self):
        return self._count(FAILED)

    def is_idle(self):
        """Nothing is running, and no headset is still within its wait for "Allow USB debugging"."""
        with self._lock:
            if any(state == RUNNING for state in self._states.values()):
                return False
            now = self._clock()
            return all(now - since >= ALLOW_WAIT_SECONDS for since in self._waiting_since.values())

    def summary(self):
        with self._lock:
            counts = {state: 0 for state in (RUNNING, DONE, FAILED, UNAUTHORIZED)}
            for state in self._states.values():
                counts[state] += 1
            queued = counts[RUNNING] - self._active
        parts = [f"{self._active} running"]
        if queued:
            parts.append(f"{queued} queued")
        parts += [f"{counts[DONE]} done", f"{counts[FAILED]} failed"]
        if counts[UNAUTHORIZED]:
            parts.append(f"{counts[UNAUTHORIZED]} waiting for Allow")
        return ", ".join(parts)

    def join(self, timeout=None):
        for thread in list(self._threads):
            thread.join(timeout)
