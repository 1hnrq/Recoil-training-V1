"""No native input/output. Concurrency is orchestrated with Events and mocks."""
import ctypes as C
from copy import deepcopy
from pathlib import Path
import sys
from threading import Event, Thread
from time import monotonic_ns
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from r6_rebuild import settings
from r6_rebuild.application import Application
from r6_rebuild.core.simulation import SimulationRuntime
from r6_rebuild.core.waiting import PortableWaiter
from r6_rebuild.global_input import GlobalInput, InputEvent, InputReducer
from r6_rebuild.mouse_output import INPUT, OutputGate, WindowsMouseSink
from r6_rebuild.profiles.models import Parameters


def event(kind, value=None):
    return InputEvent(kind, value, monotonic_ns())


class Rig:
    def __init__(self, period='.020', *, block=True, result=1, heartbeat=True):
        self.entered, self.release, self.finished = Event(), Event(), Event()
        self.heartbeat_stop = Event()
        self.calls = []
        self.errors = []
        def send(count, pointer, size):
            packet = C.cast(pointer, C.POINTER(INPUT)).contents
            self.calls.append((monotonic_ns(), packet.mi.dx, packet.mi.dy))
            if block and len(self.calls) == 1:
                self.entered.set()
                if not self.release.wait(3):
                    raise AssertionError('mock release missing')
            self.finished.set()
            return result
        self.sink = WindowsMouseSink(send_input=send)
        state = settings.state_from(settings.defaults())
        state.update_parameters('primary', Parameters(period, '10', '10'))
        with patch('r6_rebuild.core.simulation.make_waiter', PortableWaiter):
            self.r = SimulationRuntime(state, capacity=128, sink=self.sink, coin=lambda: True)
        self.r.handle_input(event('health', True))
        self.r.set_mode('real', self.r.snapshot()['safety_epoch'])
        self.r.command('set_global_pause', False)
        self.reducer = InputReducer(self.r.handle_input, safety_epoch=self.r.input_token)
        self.reducer.mouse(0x201); self.reducer.mouse(0x204)
        def publish():
            try:
                while not self.heartbeat_stop.wait(.010):
                    self.r.handle_input(event('health', True))
            except Exception as exc:
                self.errors.append(exc)
        self.publisher = Thread(target=publish)
        if heartbeat: self.publisher.start()

    def start(self):
        self.r.start()
        if not self.entered.wait(1): raise AssertionError('mock call not entered')

    def close(self):
        self.release.set()
        self.heartbeat_stop.set()
        if self.publisher.ident is not None: self.publisher.join(1)
        self.r.stop()
        if self.errors: raise AssertionError(self.errors)


class SynchronizationTests(unittest.TestCase):
    def rig(self, *args, **kwargs):
        rig = Rig(*args, **kwargs)
        self.addCleanup(rig.close)
        return rig

    def quick(self, operation):
        done = Event(); errors = []
        def run():
            try: operation()
            except Exception as exc: errors.append(exc)
            finally: done.set()
        thread = Thread(target=run); thread.start()
        self.assertTrue(done.wait(.2), 'operation waited for blocked native output')
        thread.join(1)
        self.assertFalse(errors, errors)

    def test_20_30_40_100ms_slow_send_does_not_block_heartbeat_or_snapshot(self):
        for period in ('.020', '.030', '.040', '.100'):
            with self.subTest(period=period):
                rig = self.rig(period); rig.start()
                before = rig.r.snapshot()['status']['heartbeat']['produced_ns']
                self.quick(lambda: (rig.r.input_token(), rig.r.snapshot()))
                Event().wait(.300)  # longer than unchanged 250 ms watchdog deadline
                s = rig.r.snapshot()
                self.assertEqual(s['mode'], 'real')
                self.assertIsNone(s['safety_error'])
                self.assertGreater(s['status']['heartbeat']['produced_ns'], before)
                self.assertLess(s['status']['heartbeat']['age_ns'], 250_000_000)
                self.assertIsNotNone(s['sink']['in_flight'])
                self.assertEqual(len(rig.calls), 1)
                self.quick(lambda: rig.reducer.mouse(0x202))
                rig.release.set(); rig.close()

    def test_fast_output_all_intervals_and_speed_changes_remain_real(self):
        for period in ('.020', '.030', '.040', '.100'):
            with self.subTest(period=period):
                rig = self.rig(period, block=False); rig.r.start()
                self.assertTrue(rig.r.wait_for_cycles(2, .5))
                for changed in ('.030', '.020', '.040', '.100'):
                    rig.r.command('update_parameters', 'primary', Parameters(changed, '10', '10'))
                    cycles = rig.r.snapshot()['output']['cycles']
                    self.assertTrue(rig.r.wait_for_cycles(cycles + 1, .4))
                    self.assertEqual(rig.r.snapshot()['mode'], 'real')
                rig.close()

    def test_each_stop_during_send_returns_without_waiting_and_prevents_next_call(self):
        actions = {
            'left_up': lambda r: r.reducer.mouse(0x202),
            'right_up': lambda r: r.reducer.mouse(0x205),
            'F12': lambda r: r.reducer.keyboard(0x100, 0x7B),
            'general_pause': lambda r: r.r.command('set_global_pause', True),
            'P': lambda r: (r.reducer.keyboard(0x100, 0x50), r.reducer.keyboard(0x101, 0x50)),
            'individual_pause': lambda r: r.r.command('toggle_weapon_enabled', 'primary'),
            'disable_weapon': lambda r: r.r.command('set_weapon_enabled', 'primary', False),
            'simulation': lambda r: r.r.set_mode('simulation', r.r.snapshot()['safety_epoch']),
            'input_failure': lambda r: r.r.handle_input(event('health', False)),
            'critical_failure': lambda r: r.r.fail('mock critical failure'),
        }
        for name, action in actions.items():
            with self.subTest(stop=name):
                rig = self.rig(); rig.start()
                self.quick(lambda: action(rig))
                self.assertEqual(len(rig.calls), 1)
                self.assertFalse(rig.r.snapshot()['status']['eligible'])
                rig.release.set()
                self.assertTrue(rig.finished.wait(.5))
                self.assertFalse(rig.r.wait_for_cycles(1, .06))
                self.assertEqual(len(rig.calls), 1)
                self.assertEqual(rig.r.snapshot()['sink']['queued'], 0)
                rig.close()

    def test_shutdown_blocks_immediately_and_reports_still_inflight(self):
        rig = self.rig(); rig.start()
        with self.assertRaises(TimeoutError): rig.r.stop(timeout=.025)
        s = rig.r.snapshot()
        self.assertTrue(s['stopped']); self.assertTrue(s['sink']['blocked'])
        self.assertEqual(s['mode'], 'simulation')
        self.assertFalse(s['status']['engine_holding'])
        self.assertEqual(s['status']['last_transition']['code'], 'shutdown')
        rig.release.set(); rig.r.stop()
        self.assertEqual(len(rig.calls), 1)
        self.assertFalse(rig.r._watchdog.is_alive())

    def test_speed_change_during_send_does_not_complete_old_schedule_or_catch_up(self):
        rig = self.rig(); rig.start()
        self.quick(lambda: rig.r.command('update_parameters', 'primary', Parameters('.040', '2', '3')))
        Event().wait(.080)  # new deadline passes while the old native call is held
        released = monotonic_ns(); rig.release.set()
        self.assertTrue(rig.r.wait_for_cycles(1, .5))
        rig.r.command('set_global_pause', True)
        s = rig.r.snapshot()
        self.assertEqual(s['mode'], 'real')
        self.assertGreaterEqual(s['status']['stale_completions'], 1)
        self.assertEqual(rig.calls[1][1:], (2, 3))
        self.assertGreaterEqual(rig.calls[1][0] - released, 40_000_000)
        self.assertTrue(all((row['movement']['dx'], row['movement']['dy']) == (2, 3)
                            for row in s['output']['records']))

    def test_prepared_move_is_discarded_if_generation_changes_before_admission(self):
        rig = self.rig(block=False)
        prepared, release = Event(), Event()
        original = rig.r._gate.dispatch
        once = [True]
        def delayed(*args, **kwargs):
            if once[0]:
                once[0] = False; prepared.set(); release.wait(1)
            return original(*args, **kwargs)
        with patch.object(rig.r._gate, 'dispatch', delayed):
            rig.r.start(); self.assertTrue(prepared.wait(.5))
            try:
                rig.r.command('update_parameters', 'primary', Parameters('.020', '2', '3'))
                self.assertFalse(rig.calls)
            finally: release.set()
            self.assertTrue(rig.r.wait_for_cycles(1, .5))
        rig.r.command('set_global_pause', True)
        self.assertEqual(rig.calls[0][1:], (2, 3))
        self.assertEqual(rig.r.snapshot()['status']['discarded_preparations'], 1)

    def test_release_and_repress_before_admission_does_not_restore_old_ticket(self):
        rig = self.rig(block=False)
        prepared, release = Event(), Event()
        original = rig.r._gate.dispatch
        once = [True]
        def delayed(*args, **kwargs):
            if once[0]: once[0] = False; prepared.set(); release.wait(1)
            return original(*args, **kwargs)
        with patch.object(rig.r._gate, 'dispatch', delayed):
            rig.r.start(); self.assertTrue(prepared.wait(.5))
            try:
                rig.reducer.mouse(0x202); rig.reducer.mouse(0x201)
            finally: release.set()
            self.assertTrue(rig.r.wait_for_cycles(1, .5))
        self.assertEqual(rig.r.snapshot()['status']['discarded_preparations'], 1)

    def test_heartbeat_really_stops_while_output_blocked_and_freezes_evidence(self):
        rig = self.rig(heartbeat=False)
        rig.r.set_listener_probe(lambda: {'operational': True, 'error': None,
                                         'progress': {'phase': 'pump', 'heartbeat_sequence': 1}})
        rig.start()
        with rig.r._condition:
            self.assertTrue(rig.r._condition.wait_for(lambda: rig.r._mode == 'simulation', .6))
        frozen = rig.r.snapshot()['status']['last_transition']
        self.assertEqual(frozen['code'], 'heartbeat_timeout')
        self.assertGreater(frozen['heartbeat']['age_ns'], 250_000_000)
        self.assertEqual(frozen['heartbeat']['timeout_ns'], 250_000_000)
        self.assertEqual(frozen['listener']['progress']['phase'], 'pump')
        self.assertIsNotNone(frozen['output']['in_flight'])
        self.assertTrue(frozen['output']['operational'])
        self.assertFalse(rig.release.is_set())
        rig.r.handle_input(event('health', True))
        self.assertEqual(rig.r.snapshot()['status']['last_transition'], frozen)
        rig.release.set(); self.assertTrue(rig.finished.wait(.5))
        self.assertFalse(rig.r.wait_for_cycles(1, .05))
        self.assertEqual(len(rig.calls), 1)

    def test_late_heartbeat_cannot_erase_a_missed_deadline(self):
        rig = self.rig(heartbeat=False)
        with rig.r._condition:
            rig.r._heartbeat_ns = monotonic_ns() - 251_000_000
        rig.r.handle_input(event('health', True))
        s = rig.r.snapshot()
        self.assertEqual(s['mode'], 'simulation')
        self.assertEqual(s['status']['last_transition']['code'], 'heartbeat_timeout')
        self.assertLess(s['status']['heartbeat']['age_ns'], 250_000_000)

    def test_error_code_duration_return_and_output_failure_are_distinct(self):
        rig = self.rig(result=0); rig.start(); rig.release.set()
        with rig.r._condition:
            self.assertTrue(rig.r._condition.wait_for(lambda: rig.r._mode == 'simulation', .5))
        s = rig.r.snapshot()
        self.assertEqual(s['status']['last_transition']['code'], 'output_failure')
        self.assertEqual(s['status']['last_transition']['output']['last_api_call']['return_value'], 0)
        self.assertFalse(s['sink']['operational'])
        self.assertEqual(s['sink']['last_api_call']['return_value'], 0)
        self.assertGreater(s['sink']['last_api_call']['duration_ns'], 0)
        self.assertIsNone(s['sink']['last_api_call']['winerror'])  # mock, never invent an OS error

    def test_listener_failure_keeps_its_specific_frozen_reason(self):
        rig = self.rig(); rig.start()
        rig.r.handle_input(event('health', False))
        s = rig.r.snapshot()
        self.assertEqual(s['status']['last_transition']['code'], 'listener_unavailable')
        self.assertFalse(s['status']['last_transition']['heartbeat']['last_delivery']['healthy'])
        self.assertTrue(s['sink']['operational'])
        self.assertEqual(s['mode'], 'simulation')

    def test_diagnostic_probe_error_cannot_prevent_safety_stop(self):
        rig = self.rig(); rig.start()
        def broken(): raise RuntimeError('mock diagnostic probe')
        rig.r.set_listener_probe(broken)
        self.quick(rig.r.emergency)
        s = rig.r.snapshot()
        self.assertEqual(s['mode'], 'simulation')
        self.assertTrue(s['sink']['blocked'])
        self.assertIn('mock diagnostic probe', s['status']['last_transition']['listener']['diagnostic_error'])

    def test_worker_failure_is_frozen_and_stops_in_simulation(self):
        rig = self.rig(block=False)
        with patch.object(rig.r._engine, 'step', side_effect=RuntimeError('mock worker')):
            rig.r.start()
            with self.assertRaisesRegex(RuntimeError, 'mock worker'):
                rig.r.wait_for_cycles(1, .5)
        s = rig.r.snapshot()
        self.assertEqual(s['mode'], 'simulation')
        self.assertTrue(s['stopped']); self.assertTrue(s['sink']['blocked'])
        self.assertFalse(s['state']['global_paused'])  # failure is not a user pause
        self.assertEqual(s['status']['last_transition']['code'], 'critical_worker_failure')
        self.assertFalse(rig.calls)

    def test_operator_and_weapon_changes_cannot_complete_old_generation(self):
        for command, value in [('select_operator', 'ash'), ('select_weapon', 'secondary')]:
            with self.subTest(command=command):
                rig = self.rig(); rig.start()
                self.quick(lambda: rig.r.command(command, value))
                rig.r.command('set_global_pause', True)
                rig.release.set(); self.assertFalse(rig.r.wait_for_cycles(1, .06))
                self.assertEqual(len(rig.calls), 1)
                self.assertTrue(rig.r.snapshot()['state']['global_paused'])
                self.assertEqual(rig.r.snapshot()['status']['stale_completions'], 1)
                rig.close()

    def test_f12_does_not_wait_for_native_call_and_cannot_rearm_it(self):
        rig = self.rig(); rig.start()
        self.quick(rig.r.emergency)
        s = rig.r.snapshot()
        self.assertTrue(s['emergency']); self.assertTrue(s['state']['global_paused'])
        self.assertEqual(s['status']['last_transition']['code'], 'emergency')
        with self.assertRaises(RuntimeError): rig.r.set_mode('real', s['safety_epoch'])
        rig.release.set(); rig.r.stop()
        self.assertEqual(len(rig.calls), 1)

    def test_output_failure_after_F12_does_not_overwrite_emergency(self):
        rig = self.rig(result=0); rig.start(); rig.r.emergency()
        frozen = rig.r.snapshot()['status']['last_transition']
        rig.release.set(); self.assertTrue(rig.finished.wait(.5))
        self.assertFalse(rig.r.wait_for_cycles(1, .05))
        self.assertEqual(rig.r.snapshot()['status']['last_transition'], frozen)
        self.assertFalse(rig.r.snapshot()['sink']['operational'])

    def test_real_listener_loop_progress_and_reconciliation_during_blocked_send(self):
        rig = self.rig(heartbeat=False)
        send_down, sent, up, up_done = Event(), Event(), Event(), Event()
        class API:
            def open(self, reducer): self.r = reducer; self.did_down = self.did_up = False
            def pump(self):
                Event().wait(.005)
                if send_down.is_set() and not self.did_down:
                    self.r.mouse(0x201); self.r.mouse(0x204); self.did_down = True; sent.set()
                if up.is_set() and not self.did_up:
                    self.r.mouse(0x205); self.did_up = True; up_done.set()
            def buttons_down(self): return self.did_down, self.did_down and not self.did_up
            def emergency_down(self): return False
            def close(self): pass
        source = GlobalInput(rig.r.handle_input, api_factory=API, safety_epoch=rig.r.input_token)
        self.addCleanup(source.close)
        rig.r.set_listener_probe(source.snapshot)
        source.start(); send_down.set(); self.assertTrue(sent.wait(.5)); rig.start()
        seq = source.snapshot()['progress']['heartbeat_sequence']
        Event().wait(.300)
        self.assertGreater(source.snapshot()['progress']['heartbeat_sequence'], seq)
        self.assertEqual(rig.r.snapshot()['mode'], 'real')
        up.set(); self.assertTrue(up_done.wait(.2))
        s = rig.r.snapshot()
        self.assertEqual(s['physical'], {'left': True, 'right': False})
        self.assertFalse(s['status']['engine_holding'])
        self.assertIsNotNone(s['sink']['in_flight'])
        rig.release.set(); self.assertFalse(rig.r.wait_for_cycles(1, .05))
        self.assertEqual(len(rig.calls), 1)

    def test_slow_memory_only_profile_save_does_not_stall_listener(self):
        entered = Event()
        class Store:
            def __init__(self, directory): self.document = settings.defaults()
            def load(self): return deepcopy(self.document), []
            def save(self, document): entered.set(); Event().wait(.300); self.document = deepcopy(document)
        with patch('r6_rebuild.application.SettingsStore', Store), \
                patch('r6_rebuild.core.simulation.make_waiter', PortableWaiter):
            app = Application(None, sink=WindowsMouseSink(send_input=lambda *args: 1))
        self.addCleanup(app.close)
        app.on_global_input(event('health', True))
        app.dispatch('set_mode', {'mode': 'real', 'epoch': app.snapshot()['safety_epoch']})
        done = Event(); errors = []
        def edit():
            try: app.dispatch('update_parameter', {'operator': 'jager', 'weapon': 'primary',
                                                  'field': 'interval_seconds', 'value': '0.020'})
            except Exception as exc: errors.append(exc)
            finally: done.set()
        thread = Thread(target=edit); thread.start(); self.assertTrue(entered.wait(.5))
        while not done.wait(.010): app.on_global_input(event('health', True))
        thread.join(1); self.assertFalse(errors)
        self.assertEqual(app.runtime.snapshot()['mode'], 'real')


class GateConcurrencyTests(unittest.TestCase):
    def test_generation_and_epoch_tickets_cannot_be_reused(self):
        calls = []
        gate = OutputGate(WindowsMouseSink(send_input=lambda *a: calls.append(1) or 1))
        gate.arm(0); ticket = gate.ticket(); gate.invalidate()
        self.assertFalse(gate.dispatch(10, 10, ticket)['admitted'])
        ticket = gate.ticket(); gate.block(); gate.arm(gate.epoch)
        self.assertFalse(gate.dispatch(10, 10, ticket)['admitted'])
        self.assertFalse(calls)

    def test_no_queue_or_parallel_emission_while_native_call_blocks(self):
        entered, release = Event(), Event(); calls = []
        def send(*args): calls.append(1); entered.set(); release.wait(1); return 1
        gate = OutputGate(WindowsMouseSink(send_input=send)); gate.arm(0)
        mover = Thread(target=lambda: gate.move(10, 10)); mover.start()
        self.assertTrue(entered.wait(.5))
        try:
            for _ in range(20): self.assertFalse(gate.move(10, 10))
            gate.block()
            self.assertEqual(gate.snapshot()['queued'], 0)
            self.assertIsNotNone(gate.snapshot()['in_flight'])
            self.assertEqual(len(calls), 1)
        finally: release.set(); mover.join(1)
        self.assertEqual(len(calls), 1)

    def test_expired_admission_does_not_reach_adapter(self):
        calls = []
        gate = OutputGate(WindowsMouseSink(send_input=lambda *a: calls.append(1) or 1)); gate.arm(0)
        result = gate.dispatch(10, 10, gate.ticket(), valid_until_ns=monotonic_ns() - 1)
        self.assertEqual(result['reason'], 'heartbeat_expired'); self.assertFalse(calls)

    def test_windows_error_is_captured_immediately_with_mocked_api(self):
        sink = WindowsMouseSink(send_input=lambda *args: 0)
        sink._native = True  # ctypes error functions also mocked: still no native send
        with patch('r6_rebuild.mouse_output.C.set_last_error') as reset, \
                patch('r6_rebuild.mouse_output.C.get_last_error', return_value=5):
            with self.assertRaises(OSError): sink.move(10, 10)
        reset.assert_called_once_with(0)
        self.assertEqual(sink.last_call['return_value'], 0)
        self.assertEqual(sink.last_call['winerror'], 5)


if __name__ == '__main__': unittest.main()
