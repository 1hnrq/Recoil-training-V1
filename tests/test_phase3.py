from decimal import localcontext
from fractions import Fraction as F
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from r6_rebuild import ApplicationState, OperatorProfile, Parameters, WeaponProfile
from r6_rebuild.core.exact import (FractionalAccumulator, Sensitivity,
                                   effective_axes, interval_nanoseconds)
from r6_rebuild.core.compensation import SimulationEngine
from r6_rebuild.core.simulation import SimulationRuntime
from r6_rebuild.core.timing import NoCatchUpSchedule
from r6_rebuild.core.waiting import make_waiter, PortableWaiter


def state_for(x='0.4', y='0.4', interval='0.005'):
    weapon = WeaponProfile(Parameters(interval, x, y))
    return ApplicationState([OperatorProfile(name, name.title(), weapon, weapon)
                             for name in ('jager', 'ash')], 'jager')


def activate(state):
    state.set_mouse_buttons(left=True, right=True)
    state.set_global_pause(False)


class ExactArithmeticTests(unittest.TestCase):
    def test_positive_and_negative_sequences_truncate_toward_zero(self):
        for value, expected in [('0.4', [0, 0, 1, 0, 1]), ('-0.4', [0, 0, -1, 0, -1]),
                                ('1.5', [1, 2, 1, 2, 1]), ('-1.5', [-1, -2, -1, -2, -1])]:
            with self.subTest(value=value):
                acc = FractionalAccumulator()
                values = [acc.step(F(value), F(value), horizontal_selected=True)[0] for _ in range(5)]
                self.assertEqual(values, expected)

    def test_conservation_every_cycle_for_signed_fractional_products(self):
        for x, y, mx, my in [('0.4', '-1.5', '1', '1'), ('-0.13', '0.07', '1.25', '0.3'),
                             ('12.15', '-8.199', '0.999', '1.001'), ('0', '0', '2', '3')]:
            acc = FractionalAccumulator()
            ex, ey = effective_axes(Parameters('0.001', x, y), Sensitivity(mx, my))
            sx = sy = selected_count = 0
            for index in range(1000):
                selected = index % 2 == 0
                dx, dy = acc.step(ex, ey, horizontal_selected=selected)
                sx += dx
                sy += dy
                selected_count += selected
                rx, ry = acc.residuals
                self.assertEqual(F(sx) + rx, selected_count * ex)
                self.assertEqual(F(sy) + ry, (index + 1) * ey)
                self.assertLess(abs(rx), 1)
                self.assertLess(abs(ry), 1)
                self.assertIs(type(dx), int)
                self.assertIs(type(dy), int)

    def test_skipped_horizontal_cycle_preserves_x_residue(self):
        acc = FractionalAccumulator()
        acc.step(F('0.6'), F('0.1'), horizontal_selected=True)
        self.assertEqual(acc.step(F('0.6'), F('0.1'), horizontal_selected=False), (0, 0))
        self.assertEqual(acc.residuals, (F('0.6'), F('0.2')))
        self.assertEqual(acc.step(F('0.6'), F('0.1'), horizontal_selected=True), (1, 0))

    def test_precision_does_not_depend_on_decimal_context(self):
        with localcontext() as context:
            context.prec = 2
            axes = effective_axes(Parameters('0.001', '0.1234567890123456789', '-0.17'),
                                  Sensitivity('1.1234567890123456789', '0.2'))
            self.assertEqual(axes[0], F('0.1234567890123456789') * F('1.1234567890123456789'))
            self.assertEqual(axes[1], F('-0.034'))

    def test_exact_requested_intervals_and_legacy_40ms(self):
        for text, ns in [('0.035', 35000000), ('0.020', 20000000), ('0.010', 10000000),
                         ('0.005', 5000000), ('0.001', 1000000), ('0.04', 40000000)]:
            self.assertEqual(interval_nanoseconds(Parameters(text, '0', '0')), ns)

    def test_sub_nanosecond_rounding_is_upward_only_at_scheduler_boundary(self):
        parameters = Parameters('0.00100000001', '0', '0')
        self.assertEqual(interval_nanoseconds(parameters), 1000001)
        self.assertEqual(parameters.interval_seconds, '0.00100000001')

    def test_unconfigured_and_legacy_subminimum_do_not_schedule(self):
        for interval in ['0', '0.00099']:
            state = state_for(interval=interval)
            activate(state)
            engine = SimulationEngine(state)
            self.assertIsNone(engine.period_ns)
            self.assertIsNone(engine.step(0))
            with self.assertRaises(ValueError):
                interval_nanoseconds(state.active_profile.parameters)

    def test_multiplier_inputs_reject_nonpositive_float_and_nonfinite(self):
        for bad in ['0', '-1', 'NaN', 'Infinity', '1,2', '', 1.2, True]:
            with self.subTest(value=bad), self.assertRaises((ValueError, TypeError)):
                Sensitivity(bad, '1')

    def test_accumulator_rejects_inexact_axes_and_invalid_coin_atomically(self):
        acc = FractionalAccumulator()
        for x, coin in [(0.1, True), (F('0.1'), 1)]:
            with self.assertRaises(TypeError):
                acc.step(x, F(0), horizontal_selected=coin)
            self.assertEqual(acc.residuals, (0, 0))


class EngineTransitionTests(unittest.TestCase):
    def test_factor_change_with_no_effect_on_active_axes_preserves_residue(self):
        state = state_for('0', '0.4')
        activate(state)
        engine = SimulationEngine(state, coin=lambda: True)
        engine.step(1)
        state.set_sensitivity('2', '1')
        self.assertEqual(engine.residuals, (0, F('0.4')))

    def ready(self):
        state = state_for()
        activate(state)
        engine = SimulationEngine(state, coin=lambda: True)
        engine.step(1)
        self.assertEqual(engine.residuals, (F('0.4'), F('0.4')))
        return state, engine

    def test_global_pause_resets_and_produces_no_cycles(self):
        state, engine = self.ready()
        state.on_p_release()
        self.assertTrue(state.global_paused)
        self.assertIsNone(engine.step(2))
        self.assertEqual(engine.residuals, (0, 0))
        state.on_p_release()
        self.assertEqual(engine.step(3).dy, 0)

    def test_each_active_weapon_pause_resets_without_touching_other_flags(self):
        for weapon in ['primary', 'secondary']:
            state = state_for()
            state.select_weapon(weapon)
            activate(state)
            engine = SimulationEngine(state, coin=lambda: True)
            engine.step(1)
            state.set_weapon_enabled(weapon, False)
            self.assertIsNone(engine.step(2))
            self.assertEqual(engine.residuals, (0, 0))
            other = 'secondary' if weapon == 'primary' else 'primary'
            self.assertTrue(getattr(state.operators['jager'], other).enabled)

    def test_release_either_button_resets(self):
        for left, right in [(False, True), (True, False), (False, False)]:
            state, engine = self.ready()
            state.set_mouse_buttons(left=left, right=right)
            self.assertIsNone(engine.step(2))
            self.assertEqual(engine.residuals, (0, 0))

    def test_transient_pause_release_or_switch_between_cycles_is_not_lost(self):
        transitions = [
            lambda s: (s.on_p_release(), s.on_p_release()),
            lambda s: (s.set_weapon_enabled('primary', False), s.set_weapon_enabled('primary', True)),
            lambda s: (s.set_mouse_buttons(left=False, right=True), s.set_mouse_buttons(left=True, right=True)),
            lambda s: (s.select_operator('ash'), s.select_operator('jager')),
            lambda s: (s.select_weapon('secondary'), s.select_weapon('primary')),
        ]
        for transition in transitions:
            state, engine = self.ready()
            transition(state)
            self.assertEqual(engine.residuals, (0, 0))
            self.assertEqual(engine.step(3).dy, 0)

    def test_parameter_sign_interval_and_multiplier_changes_reset(self):
        changes = [lambda s: s.update_parameters('primary', Parameters('0.005', '-0.4', '0.4')),
                   lambda s: s.update_parameters('primary', Parameters('0.005', '0.4', '-0.4')),
                   lambda s: s.update_parameters('primary', Parameters('0.001', '0.4', '0.4')),
                   lambda s: s.set_sensitivity('1.25', '0.5')]
        for change in changes:
            state, engine = self.ready()
            change(state)
            self.assertEqual(engine.residuals, (0, 0))

    def test_inactive_profile_edits_and_flags_preserve_active_residue(self):
        state, engine = self.ready()
        for operator, weapon in [('jager', 'secondary'), ('ash', 'primary'), ('ash', 'secondary')]:
            state.update_parameters(weapon, Parameters('0.001', '-99', '99'), operator_id=operator)
            state.set_weapon_enabled(weapon, False, operator_id=operator)
            self.assertEqual(engine.residuals, (F('0.4'), F('0.4')))

    def test_numerically_equal_edits_and_reselection_do_not_reset(self):
        state, engine = self.ready()
        state.update_parameters('primary', Parameters('0.0050', '.40', '+0.400'))
        state.set_sensitivity('1.000', '1.0')
        state.select_operator('jager')
        state.select_weapon('primary')
        state.set_weapon_enabled('primary', True)
        self.assertEqual(engine.residuals, (F('0.4'), F('0.4')))

    def test_uniform_multipliers_across_operator_weapon_and_edit_paths(self):
        state = state_for('2.5', '-1.2')
        state.set_sensitivity('1.2', '2.5')
        activate(state)
        original = state.snapshot()['operators']
        engine = SimulationEngine(state, coin=lambda: True)
        for operator in ['jager', 'ash', 'jager']:
            state.select_operator(operator)
            for weapon in ['primary', 'secondary']:
                state.select_weapon(weapon)
                move = engine.step(1)
                self.assertEqual((move.dx, move.dy), (3, -3))
                state.update_parameters(weapon, Parameters('0.005', '2.50', '-1.20'))
                self.assertEqual((engine.step(2).dx, engine.step(3).dy), (3, -3))
        # Only explicit edits changed textual spelling, never multiplication in place.
        for op in state.operators.values():
            for weapon in [op.primary, op.secondary]:
                self.assertEqual(F(weapon.parameters.x), F('2.5'))
                self.assertEqual(F(weapon.parameters.y), F('-1.2'))
        self.assertEqual(original[0]['primary']['parameters']['x'], '2.5')

    def test_all_catalog_profiles_use_uniform_exact_products_without_mutation(self):
        import json
        from r6_rebuild.profiles.catalog import from_catalog
        raw = json.loads((Path(__file__).resolve().parents[1]/'data/profiles.json').read_text(encoding='utf-8'))
        state = ApplicationState(from_catalog(raw))
        before = state.snapshot()['operators']
        state.set_sensitivity('1.25', '0.8')
        activate(state)
        engine = SimulationEngine(state, coin=lambda: True)
        for operator in state.operators:
            state.select_operator(operator)
            for weapon in ['primary', 'secondary']:
                state.select_weapon(weapon)
                move = engine.step(1)
                parameters = state.active_profile.parameters
                if not parameters.configured:
                    self.assertIsNone(move)
                else:
                    self.assertEqual((move.dx, move.dy),
                                     (int(F(parameters.x)*F('1.25')), int(F(parameters.y)*F('0.8'))))
        self.assertEqual(state.snapshot()['operators'], before)

    def test_no_profile_mutation_by_engine_and_sensitivity(self):
        state = state_for()
        before = state.snapshot()['operators']
        state.set_sensitivity('1.7', '0.3')
        activate(state)
        engine = SimulationEngine(state, seed=16)
        for index in range(500):
            engine.step(index)
        self.assertEqual(state.snapshot()['operators'], before)

    def test_seeded_coin_is_reproducible_and_near_half(self):
        states = [state_for() for _ in range(2)]
        for state in states:
            activate(state)
        engines = [SimulationEngine(state, seed=23) for state in states]
        traces = [[engine.step(i).horizontal_selected for i in range(6000)] for engine in engines]
        self.assertEqual(traces[0], traces[1])
        self.assertGreater(sum(traces[0]), 2800)
        self.assertLess(sum(traces[0]), 3200)

    def test_inactive_engine_neither_draws_coin_nor_accumulates(self):
        def forbidden():
            raise AssertionError('coin drawn while paused')
        engine = SimulationEngine(state_for(), coin=forbidden)
        for index in range(20):
            self.assertIsNone(engine.step(index))
        self.assertEqual(engine.residuals, (0, 0))

    def test_edits_and_selection_never_clear_general_or_individual_pause(self):
        state = state_for()
        state.set_weapon_enabled('primary', False)
        state.update_parameters('primary', Parameters('0.001', '-2', '1'))
        state.set_sensitivity('2', '3')
        state.select_operator('ash')
        state.select_operator('jager')
        self.assertTrue(state.global_paused)
        self.assertFalse(state.active_profile.enabled)

    def test_invalid_commands_leave_state_generation_and_residue_unchanged(self):
        state, engine = self.ready()
        before = state.snapshot()
        for action in [lambda: state.set_sensitivity('0', '2'),
                       lambda: state.select_operator('missing'),
                       lambda: state.set_mouse_buttons(left=False, right=1)]:
            with self.assertRaises((ValueError, KeyError, TypeError)):
                action()
            self.assertEqual(state.snapshot(), before)
            self.assertEqual(engine.residuals, (F('0.4'), F('0.4')))


class ScheduleTests(unittest.TestCase):
    def test_all_requested_periods_are_exact_with_virtual_clock(self):
        for period in [35000000, 20000000, 10000000, 5000000, 1000000]:
            schedule = NoCatchUpSchedule()
            now = 123456789
            for i in range(100):
                self.assertEqual(schedule.remaining(now, period, 0), period)
                self.assertEqual(schedule.remaining(now + period - 1, period, 0), 1)
                now += period
                self.assertEqual(schedule.remaining(now, period, 0), 0)
                timing = schedule.complete(now, now)
                self.assertEqual(timing.observed_interval_ns, None if i == 0 else period)
                self.assertEqual(timing.lateness_ns, 0)

    def test_late_wake_never_creates_catch_up_cycles(self):
        schedule = NoCatchUpSchedule()
        schedule.remaining(0, 1000000, 0)
        self.assertEqual(schedule.remaining(11000000, 1000000, 0), 0)
        timing = schedule.complete(11000000, 11200000)
        self.assertEqual(timing.missed_intervals, 10)
        self.assertEqual(schedule.remaining(11200000, 1000000, 0), 1000000)

    def test_compute_time_is_not_recovered_by_shortening_next_interval(self):
        schedule = NoCatchUpSchedule()
        schedule.remaining(0, 1000000, 0)
        schedule.complete(1000000, 9000000)
        self.assertEqual(schedule.deadline_ns, 10000000)

    def test_pause_and_context_change_rearm_full_period_and_clear_metrics_baseline(self):
        schedule = NoCatchUpSchedule()
        schedule.remaining(0, 1000000, 0)
        schedule.complete(1000000, 1000000)
        self.assertIsNone(schedule.remaining(1500000, None, 1))
        self.assertEqual(schedule.remaining(5000000, 2000000, 1), 2000000)
        self.assertIsNone(schedule.complete(7000000, 7000000).observed_interval_ns)
        self.assertEqual(schedule.remaining(7100000, 2000000, 2), 2000000)

    def test_notifications_do_not_move_deadline_or_generate_early_cycles(self):
        schedule = NoCatchUpSchedule()
        for now in [0, 100000, 200000, 999999]:
            self.assertEqual(schedule.remaining(now, 1000000, 0), 1000000 - now)
        with self.assertRaises(ValueError):
            schedule.complete(999999, 999999)

    def test_inactive_schedule_blocks_without_a_period(self):
        schedule = NoCatchUpSchedule()
        self.assertIsNone(schedule.remaining(123, None, 0))
        self.assertIsNone(schedule.deadline_ns)
        with self.assertRaises(ValueError):
            schedule.remaining(123, 999999, 0)


class SimulationRuntimeTests(unittest.TestCase):
    def test_waiters_remember_a_signal_sent_before_the_wait(self):
        from time import monotonic
        for waiter in [PortableWaiter(), make_waiter()]:
            try:
                waiter.wake()
                start = monotonic()
                waiter.wait(100000000)
                self.assertLess(monotonic() - start, 0.09)
            finally:
                waiter.close()
                waiter.close()  # teardown is idempotent

    def test_commands_interrupt_wait_without_resuming_disabled_weapon(self):
        runtime = self.runtime(coin=lambda: True)
        runtime.command('set_mouse_buttons', left=True, right=True)
        runtime.command('set_global_pause', False)
        runtime.start()
        self.assertTrue(runtime.wait_for_cycles(3))
        runtime.command('set_weapon_enabled', 'primary', False)
        count = runtime.snapshot()['output']['cycles']
        runtime.command('update_parameters', 'primary', Parameters('0.001', '-1', '2'))
        runtime.command('select_operator', 'ash')
        runtime.command('set_global_pause', True)
        runtime.command('select_operator', 'jager')
        self.assertFalse(runtime.wait_for_cycles(runtime.snapshot()['output']['cycles'] + 1, timeout=0.02))
        snap = runtime.snapshot()
        self.assertFalse(snap['state']['operators'][0]['primary']['enabled'])
        self.assertTrue(snap['state']['global_paused'])
        self.assertGreaterEqual(snap['output']['cycles'], count)

    def runtime(self, **kwargs):
        runtime = SimulationRuntime(state_for(interval='0.001'), **kwargs)
        self.addCleanup(runtime.stop)
        return runtime

    def test_worker_pauses_resets_and_stops_without_real_output(self):
        runtime = self.runtime(seed=1)
        runtime.start()
        self.assertFalse(runtime.wait_for_cycles(1, timeout=0.02))
        runtime.command('set_mouse_buttons', left=True, right=True)
        runtime.command('on_p_release')
        self.assertTrue(runtime.wait_for_cycles(4))
        runtime.command('on_p_release')
        snapshot = runtime.snapshot()
        count = snapshot['output']['cycles']
        self.assertEqual(snapshot['residuals'], {'x': '0', 'y': '0'})
        self.assertFalse(runtime.wait_for_cycles(count + 1, timeout=0.02))
        self.assertEqual(runtime.snapshot()['output']['cycles'], count)
        runtime.stop()
        self.assertFalse(runtime.snapshot()['running'])

    def test_idle_worker_waits_instead_of_polling(self):
        runtime = self.runtime()
        runtime.start()
        self.assertFalse(runtime.wait_for_cycles(1, timeout=0.04))
        snap = runtime.snapshot()
        self.assertEqual(snap['output']['cycles'], 0)
        self.assertLessEqual(snap['wait_calls'], 2)

    def test_real_clock_records_intervals_no_shorter_than_requested(self):
        runtime = self.runtime(seed=2)
        runtime.command('set_global_pause', False)
        runtime.command('set_mouse_buttons', left=True, right=True)
        runtime.start()
        self.assertTrue(runtime.wait_for_cycles(15, timeout=3))
        runtime.stop()
        intervals = [row['timing']['observed_interval_ns'] for row in runtime.snapshot()['output']['records']][1:]
        self.assertTrue(all(value >= 1000000 for value in intervals))

    def test_output_memory_is_bounded_while_totals_remain_complete(self):
        runtime = self.runtime(capacity=3, coin=lambda: True)
        runtime.command('set_global_pause', False)
        runtime.command('set_mouse_buttons', left=True, right=True)
        runtime.start()
        self.assertTrue(runtime.wait_for_cycles(10))
        runtime.stop()
        output = runtime.snapshot()['output']
        self.assertEqual(len(output['records']), 3)
        self.assertEqual(output['discarded_records'], output['cycles'] - 3)
        self.assertEqual(output['total_y'], int(F('0.4') * output['cycles']))

    def test_external_state_cannot_race_the_worker(self):
        state = state_for()
        runtime = SimulationRuntime(state)
        self.addCleanup(runtime.stop)
        activate(state)
        self.assertTrue(runtime.snapshot()['state']['global_paused'])

    def test_bad_coin_fails_closed_and_reports_error(self):
        runtime = self.runtime(coin=lambda: 1)
        runtime.command('set_global_pause', False)
        runtime.command('set_mouse_buttons', left=True, right=True)
        runtime.start()
        with self.assertRaises(RuntimeError):
            runtime.wait_for_cycles(1)
        snap = runtime.snapshot()
        self.assertTrue(snap['stopped'])
        self.assertFalse(snap['state']['global_paused'])  # fault is not a pause command
        self.assertFalse(any(snap['state']['input'].values()))
        self.assertIn('falha do worker', snap['status']['last_stop']['reason'])
        self.assertEqual(snap['output']['cycles'], 0)

    def test_stop_interrupts_long_active_wait(self):
        runtime = SimulationRuntime(state_for(interval='3600'))
        runtime.command('set_global_pause', False)
        runtime.command('set_mouse_buttons', left=True, right=True)
        runtime.start()
        runtime.stop(timeout=1)
        self.assertFalse(runtime.snapshot()['running'])

    def test_unknown_commands_and_restart_are_rejected(self):
        runtime = self.runtime()
        with self.assertRaises(ValueError):
            runtime.command('snapshot')
        runtime.start()
        with self.assertRaises(RuntimeError):
            runtime.start()
        runtime.stop()
        with self.assertRaises(RuntimeError):
            runtime.command('on_p_release')


if __name__ == '__main__':
    unittest.main()
