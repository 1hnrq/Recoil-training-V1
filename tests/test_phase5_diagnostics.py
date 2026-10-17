"""No OS input/output: reducer events, disposable storage and discarded output."""
from pathlib import Path
import sys
import tempfile
from threading import Event, Thread
from time import monotonic_ns
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from r6_rebuild.application import Application
from r6_rebuild.bridge import BridgeAPI
from r6_rebuild.global_input import InputEvent, InputReducer
from r6_rebuild.mouse_output import DiscardingMouseSink


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Application(self.temp.name, sink=DiscardingMouseSink())
        self.addCleanup(self.app.close)
        self.reducer = InputReducer(self.app.on_global_input)

    def real(self):
        self.app.on_global_input(InputEvent('health', True, monotonic_ns()))
        self.app.dispatch('set_mode', {'mode': 'real', 'epoch': self.app.snapshot()['safety_epoch']})
        self.app.dispatch('toggle_pause')

    def test_physical_input_visible_in_simulation_without_generation_or_cycles(self):
        generation = self.app.diagnostics()['generation']
        self.reducer.mouse(0x201); self.reducer.mouse(0x204)
        d = self.app.diagnostics()
        self.assertTrue(d['holding']); self.assertFalse(d['engine_holding'])
        self.assertEqual(d['generation'], generation)
        self.assertEqual(d['listener_events']['down'], {'left': 1, 'right': 1})
        self.assertEqual(d['cycles'], 0)

    def test_L_R_transitions_reach_runtime_without_waiting_for_release(self):
        self.real()
        for message, expected in [(0x201, (True, False)), (0x204, (True, True)),
                                  (0x202, (False, True)), (0x201, (True, True)),
                                  (0x205, (True, False))]:
            self.reducer.mouse(message)
            d = self.app.diagnostics()
            self.assertEqual(tuple(d['physical_input'].values()), expected)
            self.assertEqual(tuple(d['input'].values()), expected)
            self.assertEqual(d['holding'], all(expected))
            self.assertEqual(d['eligible'], all(expected))
        self.assertEqual(self.app.diagnostics()['last_stop']['reason'], 'entrada: hook')

    def test_R_first_can_hold_both(self):
        self.real(); self.reducer.mouse(0x204); self.reducer.mouse(0x201)
        self.assertTrue(self.app.diagnostics()['eligible'])

    def test_reconciliation_has_own_counter_and_never_claims_hook_UP(self):
        self.reducer.mouse(0x201); self.reducer.mouse(0x204)
        self.reducer.reconcile(False, True)
        d = self.app.diagnostics()
        self.assertEqual(d['listener_events']['up'], {'left': 0, 'right': 0})
        self.assertEqual(d['listener_events']['reconciled_releases'], {'left': 1, 'right': 0})
        self.assertEqual(d['last_input_change']['source'], 'reconcile')
        self.reducer.reconcile(True, True)
        self.assertFalse(self.app.diagnostics()['holding'])  # one positive cannot revalidate DOWN

    def test_duplicates_out_of_order_and_injected_are_not_extra_transitions(self):
        for msg in [0x202, 0x201, 0x201, 0x204]: self.reducer.mouse(msg)
        self.reducer.mouse(0x205, flags=1)
        self.app.on_global_input(InputEvent('health', True, monotonic_ns(),
                                           diagnostics=self.reducer.diagnostics()))
        d = self.app.diagnostics()
        self.assertTrue(d['holding'])
        self.assertEqual(d['listener_events']['duplicates'], 2)
        self.assertEqual(d['listener_events']['injected_ignored'], 1)
        self.assertEqual(d['listener_events']['down'], {'left': 2, 'right': 1})

    def test_each_blocker_is_explicit(self):
        self.reducer.mouse(0x201)
        d = self.app.diagnostics()
        self.assertIn('global_pause', d['blockers'])
        self.app.dispatch('toggle_weapon', {'operator': 'jager', 'weapon': 'primary'})
        self.app.dispatch('update_parameter', {'operator': 'jager', 'weapon': 'primary',
                                              'field': 'interval_seconds', 'value': '0'})
        d = self.app.diagnostics()
        self.assertIn('weapon_pause', d['blockers']); self.assertIn('unconfigured_profile', d['blockers'])
        self.assertIn('right_released', d['blockers'])
        self.app.runtime.stop()
        self.assertIn('worker_inactive', self.app.diagnostics()['blockers'])

    def test_cycles_and_sink_acceptances_are_separate_from_events(self):
        self.real(); self.reducer.mouse(0x201); self.reducer.mouse(0x204)
        self.assertTrue(self.app.runtime.wait_for_cycles(2, .2))
        self.app.dispatch('toggle_pause')
        d = self.app.diagnostics()
        self.assertGreaterEqual(d['cycles'], 2)
        self.assertEqual(sum(d['listener_events']['down'].values()), 2)
        self.assertTrue(d['sink']['test_only'])
        self.assertFalse(d['worker_active']); self.assertTrue(d['worker_running'])

    def test_snapshot_does_not_mutate_pause_or_input_or_generation(self):
        self.real(); self.reducer.mouse(0x201)
        before = self.app.diagnostics()
        for _ in range(20): self.app.diagnostics(); self.app.snapshot()
        after = self.app.diagnostics()
        for key in ('paused', 'input', 'physical_input', 'generation'):
            self.assertEqual(before[key], after[key])

    def test_diagnostics_bypass_both_command_queue_and_application_disk_lock(self):
        api = BridgeAPI(self.app); release = Event(); entered = Event(); done = Event()
        api._queue.submit(lambda: (entered.set(), release.wait(2)))
        self.assertTrue(entered.wait(1)); replies = []
        try:
            with self.app._lock:
                reader = Thread(target=lambda: (replies.append(api.invoke('diagnostics')), done.set()))
                reader.start()
                self.assertTrue(done.wait(.5))
            reader.join(1)
            self.assertTrue(replies[0]['ok']); self.assertNotIn('state', replies[0])
            self.assertFalse(api.invoke('diagnostics', {'unexpected': True})['ok'])
        finally:
            release.set(); api._close()

    def test_diagnostic_reads_and_telemetry_do_not_expire_import_token(self):
        preview = self.app.preview_import(self.app.export_bytes())
        self.reducer.mouse(0x201)
        for _ in range(4): self.app.diagnostics()
        self.assertTrue(self.app.confirm_import(preview['token'])['paused'])


if __name__ == '__main__': unittest.main()
