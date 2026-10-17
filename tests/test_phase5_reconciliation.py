"""Deterministic L/R regressions. No hooks, native input or physical output."""
from dataclasses import replace
from pathlib import Path
import random
import sys
import tempfile
from time import monotonic_ns
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from r6_rebuild.application import Application
from r6_rebuild.global_input import GlobalInput, InputEvent, InputReducer, WindowsHooks
from r6_rebuild.mouse_output import DiscardingMouseSink


class Clock:
    def __init__(self): self.now = monotonic_ns()
    def __call__(self): return self.now
    def advance(self, ms=10): self.now += int(ms * 1_000_000)


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.events = []
        self.r = InputReducer(self.events.append, clock=self.clock)

    def sample(self, left=True, right=True, ms=10):
        self.clock.advance(ms)
        self.r.reconcile(left, right)

    def both(self):
        self.r.mouse(0x201); self.r.mouse(0x204)

    def test_seven_step_hold_reconcile_and_independent_releases(self):
        self.r.mouse(0x201)
        for _ in range(5): self.sample(True, False)
        self.assertEqual(self.r.buttons, {'left': True, 'right': False})
        self.r.mouse(0x204)
        for _ in range(100):
            self.sample()
            self.assertTrue(all(self.r.buttons.values()))
        self.r.mouse(0x205)
        self.assertEqual(self.r.buttons, {'left': True, 'right': False})
        self.r.mouse(0x202)
        self.assertFalse(any(self.r.buttons.values()))
        self.assertEqual(self.r.stats['reconciled_releases'], {'left': 0, 'right': 0})

    def test_transient_negative_blocks_then_two_fresh_positives_recover(self):
        self.both(); self.sample(False, False)
        self.assertTrue(all(self.r.hook_buttons.values()))
        self.assertFalse(any(self.r.buttons.values()))
        self.sample()
        self.assertFalse(any(self.r.buttons.values()))
        self.sample()
        self.assertTrue(all(self.r.buttons.values()))
        self.assertEqual(self.r.stats['recoveries'], {'left': 1, 'right': 1})
        self.assertEqual(self.r.stats['up'], {'left': 0, 'right': 0})

    def test_independent_left_validation_does_not_release_right(self):
        self.both(); self.sample(False, True)
        self.assertEqual(self.r.buttons, {'left': False, 'right': True})
        self.assertIsNone(self.r.pending['right'])
        self.sample(); self.sample()
        self.assertTrue(all(self.r.buttons.values()))

    def test_positive_polling_without_hook_never_creates_down(self):
        for _ in range(100): self.sample()
        self.assertFalse(self.events)
        self.assertFalse(any(self.r.buttons.values()))

    def test_injected_down_cannot_authorize_recovery(self):
        self.r.mouse(0x201, flags=1); self.r.mouse(0x204, flags=2)
        self.sample(); self.sample()
        self.assertFalse(self.events)

    def test_two_negative_votes_revoke_press_until_up_down(self):
        self.both(); self.sample(False, True); self.sample(False, True)
        self.assertIsNone(self.r.presses['left'])
        for _ in range(5): self.sample()
        self.r.mouse(0x201)  # duplicate cannot renew revoked DOWN
        self.assertFalse(self.r.buttons['left'])
        self.r.mouse(0x202); self.r.mouse(0x201)
        self.assertTrue(self.r.buttons['left'])
        self.assertEqual(self.r.stats['confirmed_releases']['left'], 1)

    def test_up_during_validation_is_immediate_and_not_duplicate(self):
        self.both(); self.sample(False, True)
        self.r.mouse(0x202)
        self.assertEqual(self.r.stats['duplicates'], 0)
        self.assertEqual(self.r.stats['last_release']['reason'], 'hook_up')
        for _ in range(3): self.sample()
        self.assertFalse(self.r.buttons['left'])
        self.assertIsNone(self.r.pending['left'])

    def test_duplicate_down_cannot_extend_validation_deadline(self):
        self.both(); self.sample(False, True)
        original = dict(self.r.pending['left'])
        self.clock.advance(50); self.r.mouse(0x201)
        self.assertEqual(self.r.pending['left'], original)
        self.sample(ms=50)
        self.assertIsNone(self.r.presses['left'])
        self.assertEqual(self.r.stats['last_release']['reason'], 'validation_timeout')

    def test_positive_votes_must_be_separated_in_time(self):
        self.both(); self.sample(False, True)
        self.sample(ms=5)
        for _ in range(4): self.sample(ms=1)
        self.assertFalse(self.r.buttons['left'])
        self.sample(ms=1)
        self.assertTrue(self.r.buttons['left'])

    def test_negative_votes_must_be_separated_in_time(self):
        self.both(); self.sample(False, True)
        self.sample(False, True, ms=1)
        self.assertIsNotNone(self.r.presses['left'])
        self.sample(False, True, ms=4)
        self.assertIsNone(self.r.presses['left'])

    def test_same_ticket_cannot_vote_twice(self):
        self.both(); self.sample(False, True)
        self.clock.advance(); ticket = self.r.begin_sample()
        self.r.reconcile(True, True, ticket=ticket)
        self.clock.advance(); self.r.reconcile(True, True, ticket=ticket)
        self.assertFalse(self.r.buttons['left'])
        self.assertEqual(self.r.stats['discarded_samples'], 1)
        self.sample(); self.assertTrue(self.r.buttons['left'])

    def test_positive_vote_then_negative_resets_positive_streak(self):
        self.both(); self.sample(False, True); self.sample(); self.sample(False, True)
        self.sample(); self.assertFalse(self.r.buttons['left'])
        self.sample(); self.assertTrue(self.r.buttons['left'])

    def test_validation_deadline_wins_over_second_positive(self):
        self.both(); self.sample(False, True)
        self.sample(ms=50); self.sample(ms=50)
        self.assertFalse(self.r.buttons['left'])
        self.assertIsNone(self.r.presses['left'])

    def test_old_query_never_overwrites_newer_sample_or_down(self):
        self.both(); old = self.r.begin_sample()
        self.sample()
        newest = dict(self.r.stats['async_sample'])
        self.r.reconcile(False, False, ticket=old)
        self.assertTrue(all(self.r.buttons.values()))
        self.assertEqual(self.r.stats['async_sample'], newest)

    def test_query_exceeding_acquisition_age_suspends_not_votes(self):
        self.both(); ticket = self.r.begin_sample()
        self.clock.advance(51); self.r.reconcile(True, True, ticket=ticket)
        self.assertFalse(any(self.r.buttons.values()))
        self.assertEqual(self.r.pending['left']['positive'], 0)
        self.assertEqual(self.r.pending['left']['reason'], 'sample_expired')
        self.sample(); self.sample()
        self.assertTrue(all(self.r.buttons.values()))

    def test_invalid_time_order_cannot_validate(self):
        self.both(); ticket = self.r.begin_sample()
        self.r.reconcile(True, True, ticket=ticket, finished_ns=ticket.started_ns - 1)
        self.assertFalse(any(self.r.buttons.values()))
        self.assertFalse(any(self.r.stats['async_sample']['valid'].values()))

    def test_interleaved_down_invalidates_only_affected_button(self):
        self.r.mouse(0x204); ticket = self.r.begin_sample()
        self.r.mouse(0x201)  # while Windows query is in progress
        self.r.reconcile(False, True, ticket=ticket)
        self.assertTrue(self.r.hook_buttons['left'])
        self.assertEqual(self.r.buttons, {'left': False, 'right': True})
        self.assertEqual(self.r.stats['async_sample']['valid'], {'left': False, 'right': True})
        self.sample(); self.sample()
        self.assertTrue(all(self.r.buttons.values()))

    def test_interleaved_up_prevents_old_positive_restoring_press(self):
        self.both(); ticket = self.r.begin_sample(); self.r.mouse(0x205)
        self.r.reconcile(True, True, ticket=ticket)
        self.sample(); self.sample()
        self.assertFalse(self.r.buttons['right'])
        self.assertTrue(self.r.buttons['left'])

    def test_foreign_source_or_generation_ticket_is_discarded(self):
        self.both(); ticket = self.r.begin_sample()
        self.r.reconcile(False, False, ticket=replace(ticket, source_id='foreign'))
        self.r.reconcile(False, False, ticket=replace(ticket, generation=-1))
        self.assertTrue(all(self.r.buttons.values()))
        self.assertEqual(self.r.stats['discarded_samples'], 2)

    def test_f12_revokes_pending_press_before_any_later_positive(self):
        self.both(); self.sample(False, True); ticket = self.r.begin_sample()
        self.r.keyboard(0x100, 0x7B)
        self.assertFalse(any(self.r.buttons.values()))
        self.r.reconcile(True, True, ticket=ticket)
        self.sample(); self.sample()
        self.assertFalse(any(self.r.buttons.values()))
        emergency_index = next(i for i, e in enumerate(self.events) if e.kind == 'emergency')
        self.assertTrue(all(not e.value['right'] for e in self.events[emergency_index+2:] if e.kind == 'buttons'))

    def test_shutdown_and_critical_failure_revoke_all_leases(self):
        for reason in ('listener_shutdown', 'listener_failure'):
            with self.subTest(reason=reason):
                self.setUp(); self.both(); self.sample(False, True)
                self.r.invalidate(reason); self.sample(); self.sample()
                self.assertFalse(any(self.r.buttons.values()))
                self.assertFalse(any(self.r.presses.values()))
                self.assertEqual(self.r.stats['last_release']['reason'], reason)

    def test_epoch_change_invalidates_query_and_previous_press(self):
        epoch = [0]
        self.r = InputReducer(self.events.append, clock=self.clock, safety_epoch=lambda: epoch[0])
        self.both(); ticket = self.r.begin_sample(); epoch[0] += 1
        self.r.reconcile(True, True, ticket=ticket)
        self.sample(); self.sample()
        self.assertFalse(any(self.r.buttons.values()))
        self.assertEqual(self.r.stats['discarded_samples'], 1)

    def test_diagnostics_are_detached_and_have_per_layer_sequence_and_time(self):
        self.both(); self.sample(False, True)
        d = self.r.diagnostics()
        self.assertEqual(d['event_sequence'], 2)
        self.assertEqual(d['delivery_sequence'], 3)
        self.assertEqual(d['async_sample']['sequence'], 1)
        self.assertTrue(d['hook_buttons']['left']); self.assertFalse(d['reconciled_buttons']['left'])
        d['pending']['left']['positive'] = 999
        self.assertEqual(self.r.pending['left']['positive'], 0)

    def test_randomized_sequences_never_emit_pending_or_unauthorized_press(self):
        rng = random.Random(60216)
        for _ in range(2000):
            action = rng.randrange(8)
            self.clock.advance(rng.randrange(1, 15))
            if action < 4: self.r.mouse((0x201, 0x202, 0x204, 0x205)[action])
            elif action == 4: self.r.invalidate('mock_emergency')
            else: self.r.reconcile(bool(rng.getrandbits(1)), bool(rng.getrandbits(1)))
            for name in self.r.buttons:
                if self.r.buttons[name]:
                    self.assertTrue(self.r.hook_buttons[name])
                    self.assertIsNotNone(self.r.presses[name])
                    self.assertIsNone(self.r.pending[name])

    def test_windows_bit_mask_uses_high_bit_and_correct_button_codes(self):
        class User:
            def __init__(self): self.calls = []; self.values = {1: -32768, 2: 1}
            def GetAsyncKeyState(self, vk): self.calls.append(vk); return self.values[vk]
        api = object.__new__(WindowsHooks)  # deliberately never loads a native library
        api.user = User()
        self.assertEqual(api.buttons_down(), (True, False))
        self.assertEqual(api.user.calls, [1, 2])
        api.user.values = {1: 0, 2: -32767}
        self.assertEqual(api.buttons_down(), (False, True))

    def test_listener_takes_ticket_before_query_and_always_closes(self):
        events = []; closed = []
        class API:
            def open(self, reducer): self.r = reducer; self.r.mouse(0x204)
            def pump(self): pass
            def buttons_down(self):
                self.r.mouse(0x201)
                source._stop.set()
                return False, True
            def close(self): closed.append(True)
        source = GlobalInput(events.append, api_factory=API)
        source._run()  # synchronous fake API, no thread or Windows calls
        health = next(e for e in events if e.kind == 'health' and e.diagnostics)
        self.assertEqual(health.diagnostics['async_sample']['valid'], {'left': False, 'right': True})
        self.assertEqual(health.diagnostics['pending']['left']['reason'], 'sample_interleaved')
        self.assertEqual(closed, [True])
        self.assertFalse(events[-1].value)

    def test_listener_cleanup_closes_api_even_when_release_delivery_fails(self):
        closed = []
        def emit(event):
            if event.kind == 'buttons' and not event.value['left']: raise RuntimeError('mock delivery failure')
        class API:
            def open(self, reducer): reducer.mouse(0x201)
            def pump(self): raise RuntimeError('mock pump failure')
            def close(self): closed.append(True)
        source = GlobalInput(emit, api_factory=API)
        source._run()
        self.assertEqual(closed, [True])
        self.assertFalse(source.operational)


class ReconciliationRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Application(self.temp.name, sink=DiscardingMouseSink())
        self.addCleanup(self.app.close)
        self.clock = Clock()
        self.events = []
        def emit(event):
            self.events.append(event)
            self.app.on_global_input(event)
        self.r = InputReducer(emit, clock=self.clock, safety_epoch=lambda: self.app.runtime.input_token())
        self.app.on_global_input(InputEvent('health', True, monotonic_ns()))
        self.app.dispatch('set_mode', {'mode': 'real', 'epoch': self.app.snapshot()['safety_epoch']})
        self.app.dispatch('toggle_pause')
        self.r.mouse(0x201); self.r.mouse(0x204)

    def sample(self, left=True, right=True):
        self.clock.advance(5)
        self.r.reconcile(left, right)

    def test_transient_negative_blocks_motor_without_changing_pause_and_recovers(self):
        self.assertTrue(self.app.diagnostics()['eligible'])
        self.sample(False, True)
        d = self.app.diagnostics()
        self.assertFalse(d['eligible']); self.assertFalse(d['engine_holding'])
        self.assertIn('input_revalidation', d['blockers'])
        self.assertFalse(d['paused'])
        cycles = d['cycles']
        self.assertFalse(self.app.runtime.wait_for_cycles(cycles + 1, .02))
        self.sample(); self.assertFalse(self.app.diagnostics()['eligible'])
        self.sample(); self.assertTrue(self.app.diagnostics()['eligible'])
        self.assertTrue(self.app.diagnostics()['sink']['test_only'])

    def test_old_delivered_sequence_does_not_restore_after_up(self):
        old = self.events[-1]
        self.r.mouse(0x205)
        self.app.on_global_input(old)
        d = self.app.diagnostics()
        self.assertFalse(d['holding']); self.assertFalse(d['engine_holding'])
        self.assertEqual(d['input_rejected'], 1)

    def test_old_time_is_rejected_even_with_higher_delivery_sequence(self):
        old = self.events[-1]
        self.clock.advance(); self.r.mouse(0x205)
        self.app.on_global_input(replace(old, sequence=999))
        self.assertFalse(self.app.diagnostics()['holding'])
        self.assertEqual(self.app.diagnostics()['input_rejected'], 1)

    def test_emergency_rejects_inflight_delivery_and_revokes_recovery(self):
        old = self.events[-1]
        self.sample(False, True); self.app.runtime.emergency()
        self.app.on_global_input(replace(old, sequence=999, observed_ns=self.clock()))
        self.sample(); self.sample()
        d = self.app.diagnostics()
        self.assertEqual(d['mode'], 'simulation'); self.assertTrue(d['paused'])
        self.assertFalse(d['engine_holding']); self.assertFalse(d['holding'])
        self.assertEqual(d['input_rejected'], 1)

    def test_mode_change_requires_raw_up_not_suspended_false(self):
        self.sample(False, False)
        self.app.dispatch('set_mode', {'mode': 'simulation', 'epoch': self.app.snapshot()['safety_epoch']})
        self.app.dispatch('set_mode', {'mode': 'real', 'epoch': self.app.snapshot()['safety_epoch']})
        self.app.dispatch('toggle_pause')
        self.sample(); self.sample()
        self.assertTrue(self.app.diagnostics()['await_release'])
        self.r.mouse(0x202); self.r.mouse(0x205)
        self.assertFalse(self.app.diagnostics()['await_release'])
        self.r.mouse(0x201); self.r.mouse(0x204)
        self.assertTrue(self.app.diagnostics()['eligible'])

    def test_operation_preserves_pause_but_revokes_pending_recovery(self):
        self.sample(False, True)
        with self.app.runtime.operational_block('mock file operation'):
            self.sample(); self.sample()
            self.assertFalse(self.app.diagnostics()['eligible'])
        d = self.app.diagnostics()
        self.assertFalse(d['paused']); self.assertTrue(d['await_release'])
        self.sample(); self.sample()
        self.assertFalse(self.app.diagnostics()['engine_holding'])

    def test_critical_fault_revokes_pending_recovery(self):
        self.sample(False, True); self.app.runtime.fail('mock critical fault')
        self.sample(); self.sample()
        d = self.app.diagnostics()
        self.assertEqual(d['mode'], 'simulation'); self.assertFalse(d['engine_holding'])
        self.assertFalse(d['holding']); self.assertFalse(d['paused'])

    def test_shutdown_immediately_clears_motor_and_rejects_later_events(self):
        self.sample(False, True); self.app.runtime.stop()
        self.sample(); self.sample()
        self.assertFalse(self.app.diagnostics()['engine_holding'])
        self.assertFalse(self.app.diagnostics()['worker_running'])

    def test_latest_windows_sample_and_engine_delivery_keep_distinct_timestamps(self):
        self.sample(False, True)
        delivered = self.app.diagnostics()['input_received']['observed_ns']
        self.sample()
        self.app.on_global_input(InputEvent('health', True, monotonic_ns(), diagnostics=self.r.diagnostics()))
        d = self.app.diagnostics()
        self.assertGreater(d['listener_events']['async_sample']['observed_ns'], delivered)
        self.assertEqual(d['input_received']['observed_ns'], delivered)
        self.assertTrue(d['listener_events']['async_sample']['left'])
        self.assertFalse(d['reconciled_input']['left'])

    def test_import_replacement_revokes_old_runtime_press_authorization(self):
        self.sample(False, True)
        previous = self.app.runtime.input_token()
        preview = self.app.preview_import(self.app.export_bytes())
        self.app.confirm_import(preview['token'])
        self.assertNotEqual(self.app.runtime.input_token(), previous)
        self.sample(); self.sample()
        self.assertFalse(any(self.r.presses.values()))
        d = self.app.diagnostics()
        self.assertTrue(d['paused']); self.assertEqual(d['mode'], 'simulation')
        self.assertFalse(d['holding']); self.assertFalse(d['engine_holding'])

    def test_old_diagnostic_publication_cannot_replace_newer_layer_snapshot(self):
        old = self.r.diagnostics()
        self.sample(False, True)
        self.app.on_global_input(InputEvent('health', True, monotonic_ns(), diagnostics=old))
        self.assertIsNotNone(self.app.diagnostics()['listener_events']['pending']['left'])


if __name__ == '__main__': unittest.main()
