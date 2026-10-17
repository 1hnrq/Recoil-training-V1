import ctypes as C
from pathlib import Path
import sys
import tempfile
from threading import Event, Thread
from time import monotonic_ns
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from r6_rebuild import settings
from r6_rebuild.application import Application
from r6_rebuild.bridge import BridgeAPI
from r6_rebuild.core.simulation import SimulationRuntime
from r6_rebuild.core.compensation import SimulationEngine
from r6_rebuild.global_input import GlobalInput, InputEvent
from r6_rebuild.mouse_output import INPUT, WindowsMouseSink
from r6_rebuild.profiles.models import Parameters


class FakeSink(WindowsMouseSink):
    def __init__(self):
        self.packets = []
        def fake(count, pointer, size):
            p = C.cast(pointer, C.POINTER(INPUT)).contents
            self.packets.append((p.mi.dx, p.mi.dy))
            return 1
        super().__init__(send_input=fake)


def event(kind, value=None, own=False):
    return InputEvent(kind, value, monotonic_ns(), own)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.state = settings.state_from(settings.defaults())
        self.state.update_parameters('primary', Parameters('.001', '-.4', '.4'))
        self.state.set_sensitivity('1.25', '1.5')
        self.sink = FakeSink()
        self.r = SimulationRuntime(self.state, sink=self.sink, coin=lambda: True)
        self.addCleanup(self.r.stop)

    def real(self):
        self.r.handle_input(event('health', True))
        self.r.set_mode('real', self.r.snapshot()['safety_epoch'])

    def pressed(self, left=True, right=True, own=False):
        self.r.handle_input(event('buttons', {'left': left, 'right': right}, own))

    def run_active(self):
        self.real(); self.r.command('set_global_pause', False)
        self.pressed(); self.r.start()
        self.assertTrue(self.r.wait_for_cycles(8, .2))

    def test_simulation_default_never_reaches_sink_even_with_synthetic_buttons(self):
        self.r.command('set_mouse_buttons', left=True, right=True)
        self.r.command('set_global_pause', False); self.r.start()
        self.assertTrue(self.r.wait_for_cycles(8)); self.r.stop()
        self.assertFalse(self.sink.packets)

    def test_real_uses_identical_exact_engine_and_keeps_base_values(self):
        self.run_active(); self.r.command('set_global_pause', True)
        snap = self.r.snapshot(); rows = snap['output']['records']
        state = self.state.clone(); state.set_mouse_buttons(left=True, right=True); state.set_global_pause(False)
        reference = SimulationEngine(state, coin=lambda: True)
        expected = [reference.step(i) for i in range(len(rows))]
        self.assertEqual([(r['movement']['dx'], r['movement']['dy']) for r in rows], [(m.dx, m.dy) for m in expected])
        self.assertEqual(self.sink.packets, [(m.dx, m.dy) for m in expected if m.dx or m.dy])
        self.assertEqual(snap['state']['operators'], self.state.snapshot()['operators'])
        self.assertTrue(all(r['timing']['observed_interval_ns'] is None or r['timing']['observed_interval_ns'] >= 1_000_000 for r in rows))

    def test_real_requires_operational_input_and_sink(self):
        with self.assertRaises(RuntimeError): self.r.set_mode('real', 0)
        r = SimulationRuntime(self.state); self.addCleanup(r.stop)
        r.handle_input(event('health', True))
        with self.assertRaises(RuntimeError): r.set_mode('real', 0)

    def test_real_rejects_synthetic_start_and_blur_cannot_release_physical(self):
        self.real(); self.pressed()
        with self.assertRaises(RuntimeError): self.r.command('set_mouse_buttons', left=True, right=True)
        self.r.command('set_mouse_buttons', left=False, right=False)
        self.assertTrue(self.r.snapshot()['state']['input']['left_pressed'])

    def test_mode_switch_starts_paused_and_requires_held_buttons_released(self):
        self.pressed(); self.real(); self.r.command('set_global_pause', False)
        self.pressed(); self.assertFalse(self.r.snapshot()['state']['simulation_eligible'])
        self.pressed(False, False); self.pressed()
        self.assertTrue(self.r.snapshot()['state']['simulation_eligible'])

    def test_release_or_each_pause_stops_and_clears_residues(self):
        self.run_active(); self.pressed(False, True)
        before = len(self.sink.packets)
        self.assertFalse(self.r.wait_for_cycles(self.r.snapshot()['output']['cycles']+1, .01))
        self.assertEqual(len(self.sink.packets), before)
        self.assertEqual(self.r.snapshot()['residuals'], {'x':'0','y':'0'})
        self.r.command('set_weapon_enabled', 'primary', False); self.pressed()
        self.assertFalse(self.r.snapshot()['state']['simulation_eligible'])
        self.r.command('set_weapon_enabled', 'primary', True); self.r.command('set_global_pause', True)
        self.assertFalse(self.r.snapshot()['state']['simulation_eligible'])

    def test_operator_weapon_and_edits_never_lift_pause(self):
        self.real(); self.r.command('set_weapon_enabled', 'secondary', False)
        self.r.handle_input(event('key', 'secondary'))
        self.r.command('select_operator', 'ash'); self.r.command('select_operator', 'jager')
        self.r.command('update_parameters', 'primary', Parameters('.005','-1.2','.25'))
        self.r.command('set_sensitivity', '2', '.5')
        s = self.r.snapshot()['state']; self.assertTrue(s['global_paused'])
        self.assertFalse(next(p for p in s['operators'] if p['id']=='jager')['secondary']['enabled'])

    def test_f12_stops_returns_simulation_resets_and_rejects_old_confirmation(self):
        self.run_active(); epoch = self.r.snapshot()['safety_epoch']
        self.r.handle_input(event('emergency'))
        s = self.r.snapshot(); before = len(self.sink.packets)
        self.assertEqual(s['mode'], 'simulation'); self.assertTrue(s['state']['global_paused'])
        self.assertTrue(s['emergency']); self.assertEqual(s['residuals'], {'x':'0','y':'0'})
        self.assertIsNotNone(s['last_emergency_ns'])
        with self.assertRaises(RuntimeError): self.r.set_mode('real', epoch)
        self.r.handle_input(event('key', 'pause')); self.pressed()
        self.assertEqual(len(self.sink.packets), before); self.assertEqual(self.r.snapshot()['mode'], 'simulation')

    def test_explicit_real_after_emergency_keeps_paused(self):
        self.real(); self.r.emergency(); self.real()
        self.assertTrue(self.r.snapshot()['state']['global_paused'])
        self.assertFalse(self.r.snapshot()['emergency'])

    def test_own_control_click_preserves_pause_like_other_windows(self):
        self.real(); self.r.command('set_global_pause', False); self.pressed(own=False)
        self.assertTrue(self.r.snapshot()['state']['simulation_eligible'])
        self.pressed(own=True); self.assertFalse(self.r.snapshot()['state']['global_paused'])
        self.assertTrue(self.r.snapshot()['state']['simulation_eligible'])

    def test_own_editing_suppresses_shortcuts_not_f12_or_other_windows(self):
        self.real(); self.r.set_editing(True)
        self.r.handle_input(event('key', 'pause', True))
        self.assertTrue(self.r.snapshot()['state']['global_paused'])
        self.r.handle_input(event('key', 'pause', False))
        self.assertFalse(self.r.snapshot()['state']['global_paused'])
        self.r.handle_input(event('emergency', own=True)); self.assertTrue(self.r.snapshot()['emergency'])

    def test_input_failure_immediately_disarms(self):
        self.run_active(); self.r.handle_input(event('health', False))
        self.assertEqual(self.r.snapshot()['mode'], 'simulation'); self.assertTrue(self.r.snapshot()['sink']['blocked'])

    def test_stale_heartbeat_disarms_before_next_output(self):
        self.real(); self.pressed(); self.r.command('set_global_pause', False)
        self.r.handle_input(InputEvent('health', True, 0)); self.r.start()
        self.assertFalse(self.r.wait_for_cycles(1, .02)); self.assertFalse(self.sink.packets)
        self.assertEqual(self.r.snapshot()['mode'], 'simulation')

    def test_send_failure_returns_simulation_but_simulator_remains_usable(self):
        self.sink._send_input = lambda *a: 0
        self.real(); self.pressed(); self.r.command('set_global_pause', False); self.r.start()
        self.r.wait_for_cycles(8, .03)
        self.assertEqual(self.r.snapshot()['mode'], 'simulation')
        self.assertFalse(self.r.snapshot()['state']['global_paused'])
        self.assertFalse(self.r.snapshot()['emergency'])
        self.assertIn('falha operacional', self.r.snapshot()['status']['last_stop']['reason'])
        self.r.command('set_mouse_buttons', left=True, right=True); self.r.command('set_global_pause', False)
        self.assertTrue(self.r.wait_for_cycles(8)); self.assertEqual(self.sink.calls, 0)

    def test_shutdown_leaves_no_worker_or_armed_gate(self):
        self.run_active(); self.r.stop(); self.r.stop()
        self.assertFalse(self.r.snapshot()['running']); self.assertTrue(self.r.snapshot()['sink']['blocked'])


class ApplicationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.sink = FakeSink()
        self.app = Application(self.temp.name, sink=self.sink); self.addCleanup(self.app.close)

    def test_startup_and_restart_never_restore_real_or_transients(self):
        self.app.on_global_input(event('health', True))
        self.app.dispatch('set_mode', {'mode':'real','epoch':self.app.snapshot()['safety_epoch']})
        self.app.on_global_input(event('key', 'pause'))
        raw = self.app.export_bytes()
        for token in (b'"mode"', b'emergency', b'global_paused', b'residual', b'physical'):
            self.assertNotIn(token, raw)
        self.app.close(); self.app = Application(self.temp.name, sink=self.sink)
        s = self.app.snapshot(); self.assertEqual(s['mode'],'simulation'); self.assertTrue(s['paused'])

    def test_global_selection_advances_revision_and_invalidates_import(self):
        pending = self.app.preview_import(self.app.export_bytes()); before = self.app.snapshot()['revision']
        self.app.on_global_input(event('key', 'secondary'))
        self.assertGreater(self.app.snapshot()['revision'], before)
        with self.assertRaises(ValueError): self.app.confirm_import(pending['token'])

    def test_emergency_does_not_wait_for_application_disk_lock(self):
        done = Event()
        with self.app._lock:
            t = Thread(target=lambda: (self.app.emergency(), done.set())); t.start()
            self.assertTrue(done.wait(.5))
        t.join(1); self.assertTrue(self.app.snapshot()['paused'])

    def test_global_listener_and_deferred_persistence_clean_shutdown(self):
        class API:
            def open(self, reducer): self.reducer = reducer; self.once = False
            def pump(self):
                if not self.once:
                    self.reducer.keyboard(0x100, 0x32); self.reducer.keyboard(0x101, 0x32); self.once = True
                Event().wait(.005)
            def buttons_down(self): return False, False
            def close(self): pass
        self.app.start_global_input(lambda cb: GlobalInput(cb, api_factory=API))
        self.app.close()
        self.assertEqual(settings.decode(self.app.store.path.read_bytes())['selected_weapon'],'secondary')
        self.assertFalse(self.app._input_source.snapshot()['running'])
        self.assertFalse(self.app._persist_thread.is_alive())

    def test_emergency_bypasses_bridge_executor(self):
        api = BridgeAPI(self.app); release = Event(); entered = Event()
        api._queue.submit(lambda: (entered.set(), release.wait(1)))
        self.assertTrue(entered.wait(1))
        try:
            reply = api.invoke('emergency')
            self.assertTrue(reply['state']['emergency']); self.assertFalse(release.is_set())
        finally: release.set(); api._close()

    def test_import_returns_simulation_and_future_global_events_reach_replacement(self):
        self.app.on_global_input(event('health', True)); self.app.dispatch('set_mode',{'mode':'real','epoch':self.app.snapshot()['safety_epoch']})
        preview = self.app.preview_import(self.app.export_bytes())
        s = self.app.confirm_import(preview['token']); self.assertEqual(s['mode'],'simulation')
        self.app.on_global_input(event('key','secondary')); self.assertEqual(self.app.snapshot()['weapon'],'secondary')

    def test_import_invalidates_real_confirmation_from_previous_runtime(self):
        old = self.app.snapshot()['safety_epoch']
        preview = self.app.preview_import(self.app.export_bytes())
        self.app.confirm_import(preview['token']); self.app.on_global_input(event('health', True))
        with self.assertRaises(RuntimeError): self.app.dispatch('set_mode',{'mode':'real','epoch':old})

    def test_emergency_invalidates_queued_real_mode_authorization(self):
        old = self.app.snapshot()['safety_epoch']; self.app.on_global_input(event('health', True))
        self.app.emergency()
        with self.assertRaises(RuntimeError): self.app.dispatch('set_mode',{'mode':'real','epoch':old})

    def test_simulation_timer_cannot_clear_real_physical_input(self):
        self.app.dispatch('simulate_start'); old = self.app._simulation_epoch
        self.app.on_global_input(event('health', True))
        self.app.dispatch('set_mode',{'mode':'real','epoch':self.app.snapshot()['safety_epoch']})
        self.app.on_global_input(event('buttons',{'left':True,'right':True}))
        self.app._stop_input(old)
        self.assertTrue(self.app.snapshot()['diagnostics']['input']['left_pressed'])

    def test_explicit_pause_from_ui_not_inverted_by_own_click_interlock(self):
        self.app.on_global_input(event('health', True))
        self.app.dispatch('set_mode',{'mode':'real','epoch':self.app.snapshot()['safety_epoch']})
        self.app.dispatch('set_pause',{'paused':False,'epoch':self.app.snapshot()['safety_epoch']})
        self.app.on_global_input(event('buttons',{'left':True,'right':False},True))
        self.app.dispatch('set_pause',{'paused':True,'epoch':self.app.snapshot()['safety_epoch']})
        self.assertTrue(self.app.snapshot()['paused'])

    def test_old_unpause_cannot_undo_emergency(self):
        old = self.app.snapshot()['safety_epoch']
        self.app.emergency()
        with self.assertRaises(RuntimeError): self.app.dispatch('set_pause',{'paused':False,'epoch':old})
        self.assertTrue(self.app.snapshot()['paused'])


if __name__ == '__main__': unittest.main()
