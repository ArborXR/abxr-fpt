import threading
import unittest

from abxr.station import Station, parse_adb_devices


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def recording_run(started, results=None):
    def run(serial, log):
        started.append(serial)
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
            "PA7H40MGH7290946W\tno permissions (missing udev rules?)\n"
            "\n"
        )
        self.assertEqual(
            [("2G0YC5ZH9M05BX", "device"), ("340YC10G8V0R5V", "unauthorized"), ("PA7H40MGH7290946W", "no permissions (missing udev rules?)")],
            parse_adb_devices(output),
        )


class StationTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.started = []

    def station(self, run=None, **kwargs):
        return Station(run or recording_run(self.started), clock=self.clock, **kwargs)

    def test_provisions_connected_headsets_in_parallel(self):
        barrier = threading.Barrier(3, timeout=5)

        def run(serial, log):
            barrier.wait()  # times out unless all three run at the same time
            return True

        station = self.station(run, max_parallel=3)
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

        station = self.station(run, max_parallel=2)
        station.update([(serial, "device") for serial in "ABCDE"])
        station.join(5)
        self.assertEqual(2, peak[0])

    def test_a_failed_adb_poll_forgets_nothing(self):
        station = self.station()
        station.update([("A", "device")])
        station.join(5)
        self.clock.now = 500
        station.update(None)
        station.update([("A", "device")])
        station.join(5)
        self.assertEqual(["A"], self.started)

    def test_a_finished_headset_that_drops_off_briefly_isnt_run_again(self):
        # e.g. the VIVE Flow reboot at the end of setup, or a USB hiccup
        station = self.station()
        station.update([("A", "device")])
        station.join(5)
        self.clock.now = 60
        station.update([])
        self.clock.now = 90
        station.update([("A", "device")])
        station.join(5)
        self.assertEqual(["A"], self.started)

    def test_a_finished_headset_runs_again_after_it_was_really_unplugged(self):
        station = self.station()
        station.update([("A", "device")])
        station.join(5)
        self.clock.now = 10
        station.update([])
        self.clock.now = 200
        station.update([])
        station.update([("A", "device")])
        station.join(5)
        self.assertEqual(["A", "A"], self.started)

    def test_a_failed_headset_is_retried_by_replugging_it(self):
        station = self.station(recording_run(self.started, results={"A": False}))
        station.update([("A", "device")])
        station.join(5)
        station.update([("A", "device")])
        station.join(5)
        self.assertEqual(["A"], self.started)
        self.assertEqual(1, station.failed_count())

        self.clock.now = 5
        station.update([])
        station.update([("A", "device")])
        station.join(5)
        self.assertEqual(["A", "A"], self.started)

    def test_waits_for_headsets_adb_cant_use_yet(self):
        station = self.station()
        station.update([("A", "unauthorized"), ("B", "no permissions (missing udev rules?)")])
        self.assertEqual("0 running, 0 done, 0 failed, 2 not ready (check the headset)", station.summary())
        self.assertFalse(station.is_idle())

        station.update([("A", "device"), ("B", "no permissions (missing udev rules?)")])
        station.join(5)
        self.assertEqual(["A"], self.started)

        self.clock.now = 61
        self.assertTrue(station.is_idle())
        self.assertFalse(station.all_succeeded())  # B was never provisioned

    def test_all_succeeded_needs_every_headset_done(self):
        station = self.station(recording_run(self.started, results={"B": False}))
        station.update([("A", "device")])
        station.join(5)
        self.assertTrue(station.all_succeeded())
        station.update([("A", "device"), ("B", "device")])
        station.join(5)
        self.assertFalse(station.all_succeeded())

    def test_stop_starts_no_new_headsets(self):
        station = self.station()
        station.stop()
        station.update([("A", "device")])
        station.join(5)
        self.assertEqual([], self.started)

    def test_stop_doesnt_start_queued_headsets(self):
        release = threading.Event()
        started = []

        def run(serial, log):
            started.append(serial)
            release.wait(5)
            return True

        station = self.station(run, max_parallel=1)
        station.update([("A", "device"), ("B", "device")])
        while not started:
            threading.Event().wait(0.01)
        station.stop()
        release.set()
        station.join(5)
        self.assertEqual(["A"], started)
        self.assertEqual(0, station.running_count())

    def test_nothing_provisioned_isnt_success(self):
        station = self.station()
        station.update([])
        self.assertTrue(station.is_idle())
        self.assertFalse(station.all_succeeded())

    def test_a_fixed_headset_clears_its_failure_from_the_display(self):
        outcomes = {"A": [(False, "Install failed"), True]}
        station = self.station(lambda serial, log: outcomes[serial].pop(0))
        station.update([("A", "device")])
        station.join(5)
        self.assertEqual(("A", "Install failed"), station.last_failure)
        self.clock.now += 10
        station.update([])
        station.update([("A", "device")])
        station.join(5)
        self.assertIsNone(station.last_failure)

    def test_a_worker_that_exits_strangely_still_counts_as_failed(self):
        def run(serial, log):
            raise SystemExit(1)

        station = self.station(run)
        station.update([("A", "device")])
        station.join(5)
        self.assertEqual(1, station.failed_count())
        self.assertEqual(0, station.running_count())

    def test_display_fits_the_fpd_screen_and_shows_the_last_failure(self):
        station = self.station(lambda serial, log: (False, "Client is newer"))
        station.update([("2G0YC5ZH9M05BX", "device"), ("X", "unauthorized")])
        station.join(5)
        lines = station.display_lines()
        self.assertLessEqual(len(lines), 4)
        self.assertTrue(all(len(line) <= 21 for line in lines))
        self.assertEqual("M05BX: Client is newe", lines[-1])

    def test_only_the_chosen_serial_is_provisioned(self):
        station = self.station(only_serial="B")
        station.update([("A", "device"), ("B", "device")])
        station.join(5)
        self.assertEqual(["B"], self.started)


if __name__ == "__main__":
    unittest.main()
