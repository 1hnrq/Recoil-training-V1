"""Measure simulated cycles only. Emits a JSON report to stdout, writes nothing.

No game, UI bridge, physical input listener, mouse adapter, timer-resolution or
process-priority changes. Results characterize this run, not a real-time SLA.
"""

import argparse
import json
import math
from pathlib import Path
import platform
import statistics
import sys
from time import get_clock_info, monotonic_ns, process_time_ns

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from r6_rebuild import ApplicationState, OperatorProfile, Parameters, WeaponProfile
from r6_rebuild.core.exact import interval_nanoseconds
from r6_rebuild.core.simulation import SimulationRuntime

INTERVALS = ('0.035', '0.020', '0.010', '0.005', '0.001')


def distribution(values: list[int], target: int) -> dict:
    ordered = sorted(values)
    return {'count': len(values), 'target_ns': target, 'min_ns': min(values),
            'mean_ns': statistics.mean(values), 'median_ns': statistics.median(values),
            'p95_ns': ordered[math.ceil(.95 * len(values)) - 1], 'max_ns': max(values),
            'mean_overshoot_ns': statistics.mean(values) - target,
            'within_10_percent': sum(target <= value <= target * 1.1 for value in values),
            'shorter_than_requested': sum(value < target for value in values)}


def measure(interval: str, samples: int, repeat: int) -> dict:
    params = Parameters(interval, '-0.4', '1.25')
    weapon = WeaponProfile(params)
    state = ApplicationState([OperatorProfile('study', 'Simulation only', weapon, weapon)])
    runtime = SimulationRuntime(state, seed=6000 + repeat, capacity=samples + 16)
    runtime.command('set_mouse_buttons', left=True, right=True)
    runtime.command('set_global_pause', False)
    wall_start, cpu_start = monotonic_ns(), process_time_ns()
    try:
        runtime.start()
        if not runtime.wait_for_cycles(samples, timeout=max(5, samples * float(interval) * 4)):
            raise TimeoutError('Not enough simulated samples')
    finally:
        runtime.stop()
    cpu_ns, wall_ns = process_time_ns() - cpu_start, monotonic_ns() - wall_start
    snapshot = runtime.snapshot()
    records = snapshot['output']['records'][:samples]
    if len(records) != samples or snapshot['error']:
        raise RuntimeError('Incomplete measurement')
    observed = [record['timing']['observed_interval_ns'] for record in records[1:]]
    return {'requested_seconds': interval, 'repeat': repeat, 'cycles': samples,
            'observed_intervals_ns': observed,
            'lateness_ns': [record['timing']['lateness_ns'] for record in records],
            'missed_intervals': sum(record['timing']['missed_intervals'] for record in records),
            'statistics': distribution(observed, interval_nanoseconds(params)),
            'process_cpu_ns': cpu_ns, 'wall_ns': wall_ns,
            'cpu_percent_of_one_core': 100 * cpu_ns / wall_ns,
            'wait_calls': snapshot['wait_calls'],
            'wait_backend': snapshot['wait_backend'],
            'output_cycles_at_stop': snapshot['output']['cycles'],
            'records_discarded': snapshot['output']['discarded_records']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=101)
    parser.add_argument('--repetitions', type=int, default=3)
    args = parser.parse_args()
    if not 2 <= args.samples <= 2000 or not 1 <= args.repetitions <= 10:
        parser.error('samples must be 2..2000 and repetitions 1..10')
    runs = [measure(interval, args.samples, repeat)
            for interval in INTERVALS for repeat in range(1, args.repetitions + 1)]
    aggregates = []
    for interval in INTERVALS:
        matching = [run for run in runs if run['requested_seconds'] == interval]
        values = [value for run in matching for value in run['observed_intervals_ns']]
        row = distribution(values, matching[0]['statistics']['target_ns'])
        row['requested_seconds'] = interval
        row['cpu_percent_of_one_core'] = (100 * sum(run['process_cpu_ns'] for run in matching)
                                         / sum(run['wall_ns'] for run in matching))
        aggregates.append(row)
    clock = get_clock_info('monotonic')
    print(json.dumps({'simulation_only': True, 'platform': platform.platform(),
                      'python': sys.version, 'clock': {'implementation': clock.implementation,
                      'monotonic': clock.monotonic, 'adjustable': clock.adjustable,
                      'resolution_seconds': clock.resolution},
                      'policy': 'full interval after completion; no catch-up; interruptible blocking wait',
                      'samples_per_run': args.samples, 'repetitions': args.repetitions,
                      'aggregates': aggregates, 'runs': runs}, indent=2))


if __name__ == '__main__':
    main()
