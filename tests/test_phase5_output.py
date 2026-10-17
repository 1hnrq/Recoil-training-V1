import ctypes as C
from pathlib import Path
import sys
from threading import Event, Thread
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from r6_rebuild.mouse_output import INPUT, MOUSEINPUT, OutputGate, WindowsMouseSink


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.packets = []
        def fake(count, pointer, size):
            p = C.cast(pointer, C.POINTER(INPUT)).contents
            self.packets.append((count, size, p.type, p.mi.dx, p.mi.dy, p.mi.dwFlags, p.mi.mouseData))
            return 1
        self.sink = WindowsMouseSink(send_input=fake)

    def test_windows_structure_size_and_alignment(self):
        self.assertEqual(C.sizeof(INPUT), 40 if C.sizeof(C.c_void_p) == 8 else 28)
        self.assertEqual(C.sizeof(MOUSEINPUT), 32 if C.sizeof(C.c_void_p) == 8 else 24)

    def test_construction_and_zero_never_call_api(self):
        self.assertFalse(self.packets); self.assertFalse(self.sink.move(0, 0))
        self.assertFalse(self.packets)

    def test_signed_relative_only_one_packet(self):
        self.sink.move(-3, 5)
        self.assertEqual(self.packets, [(1, C.sizeof(INPUT), 0, -3, 5, 1, 0)])

    def test_invalid_or_overflow_never_wrap_or_call_api(self):
        for value in [True, .5, '1', 2**31, -(2**31)-1]:
            with self.assertRaises(ValueError): self.sink.move(value, 0)
        self.assertFalse(self.packets)

    def test_failed_send_disables_sink_without_retry(self):
        calls = []
        sink = WindowsMouseSink(send_input=lambda *a: calls.append(a) or 0)
        with self.assertRaises(OSError): sink.move(1, 1)
        with self.assertRaises(RuntimeError): sink.move(1, 1)
        self.assertEqual(len(calls), 1); self.assertFalse(sink.operational)

    def test_gate_closed_by_default_explicit_arm_and_block(self):
        gate = OutputGate(self.sink)
        self.assertFalse(gate.move(1, 1)); self.assertFalse(self.packets)
        gate.arm(gate.epoch); self.assertTrue(gate.move(1, 1))
        epoch = gate.epoch; gate.block()
        self.assertFalse(gate.move(1, 1))
        with self.assertRaises(RuntimeError): gate.arm(epoch)
        self.assertEqual(len(self.packets), 1)

    def test_missing_sink_cannot_be_armed(self):
        with self.assertRaises(RuntimeError): OutputGate().arm(0)

    def test_stop_invalidates_immediately_without_waiting_for_inflight_call(self):
        entered, release, stopped = Event(), Event(), Event()
        calls = []
        def fake(*args):
            calls.append(True); entered.set(); release.wait(1); return 1
        gate = OutputGate(WindowsMouseSink(send_input=fake)); gate.arm(0)
        mover = Thread(target=lambda: gate.move(1, 1)); mover.start()
        self.assertTrue(entered.wait(1))
        stopper = Thread(target=lambda: (gate.block(), stopped.set())); stopper.start()
        # Wait for the stop signal itself, not a timing-dependent sleep.
        self.assertTrue(gate._blocked.wait(1)); self.assertTrue(stopped.wait(.2))
        self.assertTrue(mover.is_alive())  # acknowledgment is NOT native cancellation
        with self.assertRaises(RuntimeError): gate.arm(gate.epoch)
        queued = Thread(target=lambda: gate.move(2, 2)); queued.start()
        release.set()
        for t in (mover, stopper, queued): t.join(1); self.assertFalse(t.is_alive())
        self.assertEqual(len(calls), 1); self.assertTrue(stopped.is_set())


if __name__ == '__main__': unittest.main()
