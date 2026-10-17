"""Regression contract for explicit pause; every movement goes to a mock."""
from pathlib import Path
import sys
import tempfile
from threading import Event
from time import monotonic_ns
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from r6_rebuild.application import Application
from r6_rebuild.bridge import BridgeAPI
from r6_rebuild.global_input import InputEvent, InputReducer, GlobalInput
from r6_rebuild.mouse_output import DiscardingMouseSink


class PauseCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.app = Application(self.temp.name, sink=DiscardingMouseSink())
        self.addCleanup(self.app.close)
        self.reducer = InputReducer(self.app.on_global_input)

    def real(self):
        self.app.on_global_input(InputEvent('health', True, monotonic_ns()))
        self.app.dispatch('set_mode', {'mode': 'real', 'epoch': self.app.snapshot()['safety_epoch']})
        self.app.dispatch('toggle_pause')

    def test_own_click_and_editing_preserve_both_pause_values(self):
        self.real()
        for paused in (False, True):
            self.app.runtime.command('set_global_pause', paused)
            for own in (True, False):
                for msg in (0x201, 0x204, 0x202, 0x205):
                    self.reducer.mouse(msg, own_window=own)
                    self.assertEqual(self.app.diagnostics()['paused'], paused)
            for editing in (True, False, True, False):
                self.app.dispatch('set_editing', {'editing': editing})
                self.assertEqual(self.app.diagnostics()['paused'], paused)

    def test_profiles_parameters_multipliers_individual_pauses_and_pages_preserve_pause(self):
        commands = [('select_operator', {'id': 'ash'}), ('select_weapon', {'weapon': 'secondary'}),
                    ('toggle_weapon', {'operator': 'ash', 'weapon': 'primary'}),
                    ('toggle_weapon', {'operator': 'ash', 'weapon': 'secondary'}),
                    ('set_multiplier', {'axis': 'x', 'value': '1.25'}),
                    ('set_multiplier', {'axis': 'y', 'value': '1.5'}),
                    ('set_view', {'view': 'files'}), ('set_view', {'view': 'operators'})]
        commands += [('update_parameter', {'operator': 'ash', 'weapon': 'secondary', 'field': field, 'value': value})
                     for field, value in [('x', '-0.4'), ('y', '0.6'), ('interval_seconds', '0.005')]]
        self.real()
        for paused in (False, True):
            self.app.runtime.command('set_global_pause', paused)
            for action, payload in commands:
                with self.subTest(paused=paused, action=action, payload=payload):
                    self.assertEqual(self.app.dispatch(action, payload)['paused'], paused)

    def test_blur_modal_close_and_diagnostic_reads_cannot_release_real_input(self):
        self.real(); self.reducer.mouse(0x201, own_window=True); self.reducer.mouse(0x204, own_window=True)
        for _ in range(5):
            self.app.dispatch('simulate_stop')  # same command used by blur/modal close
            self.app.dispatch('snapshot'); self.app.diagnostics()
        d = self.app.diagnostics()
        self.assertTrue(d['holding']); self.assertTrue(d['eligible']); self.assertFalse(d['paused'])
        self.assertTrue(self.app.runtime.wait_for_cycles(2, .2))

    def test_file_dialog_cancel_preserves_unpaused_state(self):
        api = BridgeAPI(self.app); self.real(); app = self.app
        class Window:
            def create_file_dialog(self, *args, **kwargs):
                d = app.diagnostics()
                self_check.assertIn('operation_block', d['blockers'])
                self_check.assertFalse(d['paused'])
                return None
        self_check = self; api._window = Window()
        try:
            before = self.app.export_bytes()
            for action in ('import_file', 'export_file'):
                self.assertTrue(api.invoke(action)['ok'])
                self.assertFalse(self.app.diagnostics()['paused'])
                self.assertFalse(self.app.diagnostics()['operation_blocks'])
            self.assertEqual(before, self.app.export_bytes())
        finally: api._close()

    def test_failed_dialog_removes_only_its_block_and_preserves_pause(self):
        api = BridgeAPI(self.app); self.real()
        class Window:
            def create_file_dialog(self, *args, **kwargs): raise OSError('mock picker')
        api._window = Window()
        try:
            reply = api.invoke('export_file')
            self.assertFalse(reply['ok']); self.assertFalse(reply['state']['paused'])
            self.assertEqual(reply['state']['diagnostics']['operation_blocks'], [])
        finally: api._close()

    def test_nested_blocks_do_not_resume_and_exception_cleanup_is_safe(self):
        self.real(); self.reducer.mouse(0x201); self.reducer.mouse(0x204)
        with self.app.runtime.operational_block('outer'):
            with self.assertRaisesRegex(ValueError, 'mock'):
                with self.app.runtime.operational_block('inner'): raise ValueError('mock')
            self.assertEqual(self.app.diagnostics()['operation_blocks'], ['outer'])
            before = self.app.diagnostics()['cycles']
            self.assertFalse(self.app.runtime.wait_for_cycles(before + 1, .02))
            self.assertFalse(self.app.diagnostics()['paused'])
        d = self.app.diagnostics()
        self.assertTrue(d['await_release']); self.assertFalse(d['eligible'])
        self.reducer.mouse(0x202); self.reducer.mouse(0x205)
        self.reducer.mouse(0x201); self.reducer.mouse(0x204)
        self.assertTrue(self.app.diagnostics()['eligible'])

    def test_input_during_block_never_emits_or_becomes_stale_active_input(self):
        self.real()
        with self.app.runtime.operational_block('picker'):
            self.reducer.mouse(0x201); self.reducer.mouse(0x204)
            d = self.app.diagnostics()
            self.assertTrue(d['holding']); self.assertFalse(d['engine_holding'])
            self.assertFalse(self.app.runtime.wait_for_cycles(1, .02))
            self.assertEqual(self.app.diagnostics()['sink']['calls'], 0)
        self.assertIn('await_release', self.app.diagnostics()['blockers'])

    def test_f12_during_block_is_not_undone_by_cleanup(self):
        self.real()
        with self.app.runtime.operational_block('picker'):
            self.reducer.keyboard(0x100, 0x7B)
        d = self.app.diagnostics()
        self.assertTrue(d['paused']); self.assertEqual(d['mode'], 'simulation')
        self.assertTrue(d['sink']['blocked']); self.assertTrue(d['emergency'])

    def test_P_during_block_is_not_undone_by_cleanup(self):
        self.real()
        with self.app.runtime.operational_block('picker'):
            self.reducer.keyboard(0x100, 0x50); self.reducer.keyboard(0x101, 0x50)
        self.assertTrue(self.app.diagnostics()['paused'])

    def test_fault_disarms_but_does_not_claim_P_or_F12(self):
        self.real()
        self.app.on_global_input(InputEvent('health', False, monotonic_ns()))
        d = self.app.diagnostics()
        self.assertFalse(d['paused']); self.assertFalse(d['emergency'])
        self.assertEqual(d['mode'], 'simulation'); self.assertTrue(d['sink']['blocked'])
        self.assertIn('falha operacional', d['last_stop']['reason'])

    def test_synthetic_start_rejected_during_operation(self):
        self.app.dispatch('toggle_pause')
        with self.app.runtime.operational_block('picker'):
            with self.assertRaises(RuntimeError): self.app.dispatch('simulate_start')
        self.assertFalse(self.app.diagnostics()['engine_holding'])

    def test_export_then_confirmed_import_is_explicit_paused_boundary(self):
        api = BridgeAPI(self.app); self.real()
        target = Path(self.temp.name) / 'roundtrip.json'
        class Window:
            def create_file_dialog(self, *args, **kwargs): return (str(target),)
        api._window = Window()
        try:
            self.assertTrue(api.invoke('export_file')['exported'])
            self.assertFalse(self.app.diagnostics()['paused'])
            preview = api.invoke('import_file')
            self.assertFalse(preview['state']['paused'])
            reply = api.invoke('confirm_import', {'token': preview['import_preview']['token']})
            self.assertTrue(reply['ok']); self.assertTrue(reply['state']['paused'])
            self.assertEqual(reply['state']['mode'], 'simulation')
        finally: api._close()

    def test_global_listener_worker_while_held_and_clean_shutdown(self):
        pressed = Event(); send_down = Event(); closed = Event()
        class API:
            def open(self, reducer): self.reducer = reducer; self.sent = False
            def pump(self):
                if send_down.is_set() and not self.sent:
                    self.reducer.mouse(0x201); self.reducer.mouse(0x204)
                    self.sent = True; pressed.set()
                closed.wait(.005)
            def buttons_down(self): return (self.sent, self.sent)
            def close(self): closed.set()
        self.app.start_global_input(lambda cb: GlobalInput(cb, api_factory=API))
        self.real(); send_down.set(); self.assertTrue(pressed.wait(.5))
        self.assertTrue(self.app.runtime.wait_for_cycles(3, .3))
        self.assertTrue(self.app.diagnostics()['holding'])
        self.assertTrue(self.app.diagnostics()['worker_active'])
        self.app.close()
        self.assertTrue(closed.is_set())
        self.assertFalse(self.app._input_source.snapshot()['running'])
        self.assertFalse(self.app.runtime.snapshot()['running'])


if __name__ == '__main__': unittest.main()
