"""Bounded manual harness safety, with discard-only output and fake time."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from manual_mouse_smoke import BoundedTrial
from r6_rebuild.mouse_output import DiscardingMouseSink


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.safe = True
        self.sink = DiscardingMouseSink()
        self.trial = BoundedTrial(self.sink, safe=lambda: self.safe, clock=lambda: self.now)

    def test_no_automatic_start_and_exact_bounded_one_shot(self):
        self.assertFalse(self.trial.step()); self.assertEqual(self.sink.calls, 0)
        self.trial.start()
        for _ in range(30):
            self.now += 100_000_000
            self.trial.step()
        self.assertEqual(self.sink.calls, 10)
        self.assertEqual(self.trial.total, [10, 10])
        self.assertEqual(sum(row['dx'] for row in self.trial.rows), 0)
        with self.assertRaises(RuntimeError): self.trial.start()

    def test_deadline_no_late_or_catchup_output(self):
        self.trial.start(); self.now = 2_000_000_000
        self.assertFalse(self.trial.step()); self.assertEqual(self.sink.calls, 0)

    def test_emergency_stops_and_cannot_rearm(self):
        self.trial.start(); self.trial.step(); self.trial.stop('F12')
        self.assertFalse(self.trial.step()); self.assertEqual(self.sink.calls, 1)
        self.assertTrue(self.trial.gate.snapshot()['blocked'])
        with self.assertRaises(RuntimeError): self.trial.start()

    def test_focus_loss_or_button_press_stops(self):
        self.trial.start(); self.safe = False
        self.assertFalse(self.trial.step()); self.assertEqual(self.sink.calls, 0)

    def test_unsafe_start_refused(self):
        self.safe = False
        with self.assertRaises(RuntimeError): self.trial.start()
        self.assertEqual(self.sink.calls, 0)
