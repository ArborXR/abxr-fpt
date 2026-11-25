import threading
import unittest

from abxr.station import Station, parse_adb_devices


def run_until_released(release, started, results=None):
    def run(serial, log):
        started.append(serial)
        release.wait(5)
        return True if results is None else results.get(serial, True)
    return run


class ParseAdbDevicesTest(unittest.TestCase):
    def test_reads_serials_and_states(self):
        output = (
            "* daemon not running; starting now at tcp:5037\n"
            "* daemon started successfully\n"
            "List of devices attached\n"
            "2G0YC5ZH9M05BX\tdevice\n"
            "340YC10G8V0R5V\tunauthorized\n"
            "PA7H40MGH7290946W\toffline\n"
            "\n"
        )
        self.assertEqual(
            [("2G0YC5ZH9M05BX", "device"), ("340YC10G8V0R5V", "unauthorized"), ("PA7H40MGH7290946W", "offline")],
            parse_adb_devices(output),
        )


class StationTest(unittest.TestCase):
    def test_provisions_connected_headsets_in_parallel(self):
        barrier = threading.Barrier(3, timeout=5)

        def run(serial, log):
            barrier.wait()  # times out unless all three run at the same time
            return True

        station = Station(run, max_parallel=3)
        station.update([("A", "device"), ("B", "device"), ("C", "device")])
        station.join(5)
        self.assertEqual("0 running, 3 done, 0 failed", station.summary())

    def test_max_parallel_limits_how_many_run_at_once(self):
        lock = threading.Lock()
        active = [0]
        peak = [0]

        def run(serial, log):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            threading.Event().wait(0.05)
            with lock:
                active[0] -= 1
            return True

        station = Station(run, max_parallel=2)
        station.update([(serial, "device") for serial in "ABCDE"])
        station.join(5)
        self.assertEqual(2, peak[0])
        self.assertEqual("0 running, 5 done, 0 failed", station.summary())

    def test_a_finished_headset_runs_again_only_after_it_is_unplugged(self):
        release = threading.Event()
        release.set()
        started = []
        station = Station(run_until_released(release, started), max_parallel=2)

        station.update([("A", "device")])
        station.join(5)
        station.update([("A", "device"), ("B", "device")])
        station.join(5)
        self.assertEqual(["A", "B"], started)

        station.update([("B", "device")])  # A unplugged
        station.update([("A", "device"), ("B", "device")])  # A plugged back in
        station.join(5)
        self.assertEqual(["A", "B", "A"], started)

    def test_failures_are_counted_and_not_retried_while_plugged_in(self):
        release = threading.Event()
        release.set()
        started = []
        station = Station(run_until_released(release, started, results={"A": False}), max_parallel=2)

        station.update([("A", "device")])
        station.join(5)
        station.update([("A", "device")])
        station.join(5)
        self.assertEqual(["A"], started)
        self.assertEqual(1, station.failed_count())

    def test_an_exception_counts_as_a_failure(self):
        def run(serial, log):
            raise RuntimeError("adb went away")

        station = Station(run)
        station.update([("A", "device")])
        station.join(5)
        self.assertEqual(1, station.failed_count())

    def test_waits_for_allow_usb_debugging(self):
        now = [0.0]
        release = threading.Event()
        release.set()
        started = []
        station = Station(run_until_released(release, started), clock=lambda: now[0])

        station.update([("A", "unauthorized")])
        self.assertEqual("0 running, 0 done, 0 failed, 1 waiting for Allow", station.summary())
        self.assertFalse(station.is_idle())
        now[0] = 61.0
        self.assertTrue(station.is_idle())

        station.update([("A", "device")])
        station.join(5)
        self.assertEqual(["A"], started)

    def test_only_the_chosen_serial_is_provisioned(self):
        release = threading.Event()
        release.set()
        started = []
        station = Station(run_until_released(release, started), only_serial="B")
        station.update([("A", "device"), ("B", "device")])
        station.join(5)
        self.assertEqual(["B"], started)


if __name__ == "__main__":
    unittest.main()
