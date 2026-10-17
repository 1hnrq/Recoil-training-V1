"""Packaged verification with a discard-only sink. Never binds SendInput.

Native input hooks are opened and closed to check packaging; synthetic test
commands validate the backend, not physical global hotkey recognition.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
from time import monotonic_ns

from . import settings
from .application import Application
from .bridge import BridgeAPI
from .mouse_output import DiscardingMouseSink
from .paths import frozen, resource_root, configuration_directory


def require(condition, description, results):
    results[description] = bool(condition)
    if not condition:
        raise RuntimeError(description)


def check_reconciliation(results):
    """Exercise the bundled reducer with a virtual clock; no OS input/output."""
    from .global_input import InputReducer
    now = [1_000_000_000]
    events = []
    reducer = InputReducer(events.append, clock=lambda: now[0])
    def sample(left=True, right=True):
        now[0] += 10_000_000
        reducer.reconcile(left, right)
    sample(); sample()
    require(not events, 'polling alone cannot create a press', results)
    reducer.mouse(0x201); reducer.mouse(0x204)
    sample(False, True)
    diagnostic = reducer.diagnostics()
    require(diagnostic['hook_buttons']['left'] and not diagnostic['reconciled_buttons']['left']
            and diagnostic['async_sample']['sequence'] == 3 and diagnostic['pending']['left'],
            'separate hook Windows reconciled layers packaged', results)
    sample()
    require(not reducer.buttons['left'], 'one positive sample cannot recover', results)
    sample()
    require(all(reducer.buttons.values()), 'two fresh samples recover valid hook DOWN', results)
    old = reducer.begin_sample()
    sample()
    reducer.reconcile(False, False, ticket=old)
    require(all(reducer.buttons.values()) and reducer.stats['discarded_samples'] == 1,
            'obsolete query cannot overwrite newer state', results)
    reducer.mouse(0x205); sample(); sample()
    require(not reducer.buttons['right'], 'confirmed UP cannot recover from polling', results)
    reducer.mouse(0x204); reducer.keyboard(0x100, 0x7B); sample(); sample()
    require(not any(reducer.buttons.values()) and not any(reducer.presses.values()),
            'F12 revokes pending recovery', results)


def check_synchronization(results):
    """Verify the bundled concurrency path with discard-only blocking output."""
    from .core.simulation import SimulationRuntime
    from .global_input import InputEvent
    from .profiles.models import Parameters
    for publish in (True, False):
        entered, release, halt = threading.Event(), threading.Event(), threading.Event()
        class BlockingSink(DiscardingMouseSink):
            def move(self, dx, dy):
                entered.set()
                if not release.wait(3):
                    raise RuntimeError('self-check mock release timed out')
                return super().move(dx, dy)
        sink = BlockingSink()
        state = settings.state_from(settings.defaults())
        state.update_parameters('primary', Parameters('.020', '10', '10'))
        runtime = SimulationRuntime(state, sink=sink, coin=lambda: True)
        def emit(kind, value):
            runtime.handle_input(InputEvent(kind, value, monotonic_ns()))
        def heartbeat():
            while not halt.wait(.010):
                emit('health', True)
        publisher = threading.Thread(target=heartbeat, name='R6-selfcheck-heartbeat', daemon=True)
        try:
            emit('health', True)
            runtime.set_mode('real', runtime.snapshot()['safety_epoch'])
            runtime.command('set_global_pause', False)
            emit('buttons', {'left': True, 'right': True})
            if publish: publisher.start()
            runtime.start()
            if not entered.wait(1):
                raise RuntimeError('bundled worker did not enter discard-only output')
            if publish:
                threading.Event().wait(.300)
                snap = runtime.snapshot()
                require(snap['mode'] == 'real' and snap['status']['heartbeat']['age_ns'] < 250_000_000
                        and snap['sink']['in_flight'] is not None,
                        'heartbeat progresses during blocked discard-only output', results)
                emit('buttons', {'left': True, 'right': False})
                require(not runtime.snapshot()['status']['engine_holding'],
                        'UP stops eligibility while output is in flight', results)
            else:
                with runtime._condition:
                    runtime._condition.wait_for(lambda: runtime._mode == 'simulation', .7)
                fault = runtime.snapshot()['status']['last_transition']
                require(fault is not None and fault['code'] == 'heartbeat_timeout'
                        and fault['heartbeat']['timeout_ns'] == 250_000_000
                        and fault['output']['in_flight'] is not None,
                        'real heartbeat expiry freezes 250ms evidence during blocked output', results)
            release.set()
            runtime.wait_for_cycles(1, .06)
        finally:
            release.set(); halt.set()
            if publisher.ident is not None: publisher.join(1)
            runtime.stop()
        require(sink.calls == 1 and runtime.snapshot()['sink']['queued'] == 0,
                'no resend after ' + ('UP' if publish else 'heartbeat expiry'), results)


def run(folder):
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    results = {}
    report = {'at_utc': datetime.now(timezone.utc).isoformat(), 'frozen': frozen(),
              'resource_root': str(resource_root()), 'default_config_directory': str(configuration_directory()),
              'physical_output': False, 'checks': results}
    app = api = None
    try:
        check_reconciliation(results)
        check_synchronization(results)
        assets = ['frontend/' + name for name in ('index.html', 'app.js', 'model.js', 'bridge-client.js',
                  'preview-transport.js', 'styles.css', 'operator-icons.css')]
        entries = settings.catalog()['operators']
        assets += [f'frontend/assets/operators/{op["id"]}.svg' for op in entries]
        assets += ['frontend/assets/operators/LICENSE.txt', 'data/profiles.json', 'assets/branding/r6-rebuild.ico']
        report['asset_hashes'] = {name: hashlib.sha256((resource_root() / name).read_bytes()).hexdigest() for name in assets}
        require(len(entries) == 75, '75 profiles and logos available', results)
        panel = (resource_root() / 'frontend/bridge-client.js').read_text(encoding='utf-8')
        require(all(label in panel for label in ('Hook L/R', 'Windows L/R', 'Reconciliado L/R',
                'Validação pendente', 'Última entrega aceita pelo motor', 'Última liberação/suspensão')),
                'reconciliation diagnostic indicators packaged', results)
        require(all(label in panel for label in ('Sincronização e segurança', 'registro congelado',
                'atraso até recebimento', 'intervalo entre publicações', 'erro Windows',
                'SendInput (última chamada)', 'Espera pelo lock do motor')),
                'synchronization diagnostic indicators packaged', results)
        # Import frozen native browser dependencies, but do not open a GUI.
        from webview.guilib import initialize
        engine = initialize('edgechromium')
        require(engine.renderer == 'edgechromium', 'WebView2 and pythonnet load', results)
        from System.Drawing import Icon
        brand_icon = Icon(str(resource_root() / 'assets/branding/r6-rebuild.ico'), 32, 32)
        try:
            require(brand_icon.Width == 32 and brand_icon.Height == 32,
                    'official multiresolution icon loads in native window backend', results)
        finally:
            brand_icon.Dispose()
        sink = DiscardingMouseSink()
        app = Application(folder / 'settings', sink=sink)
        api = BridgeAPI(app)
        app.start_global_input()
        initial = app.snapshot()
        require(initial['global_input']['operational'], 'native hooks operational', results)
        require(initial['mode'] == 'simulation' and initial['paused'] and sink.calls == 0, 'safe startup', results)
        diagnostic = api.invoke('diagnostics')['diagnostics']
        require(all(key in diagnostic for key in ('physical_input', 'holding', 'engine_holding',
                'worker_active', 'blockers', 'listener_events', 'last_input_change', 'last_stop',
                'reconciled_input', 'input_received', 'input_rejected')),
                'new input diagnostics packaged and readable', results)
        require(diagnostic['heartbeat']['timeout_ns'] == 250_000_000 and
                all(key in diagnostic for key in ('last_transition', 'lock_wait', 'listener_progress'))
                and all(key in diagnostic['sink'] for key in ('last_api_call', 'in_flight', 'queued')),
                'synchronization diagnostics readable with unchanged timeout', results)
        require('global_pause' in diagnostic['blockers'] and not diagnostic['eligible'],
                'startup diagnostic explains global pause', results)
        app.dispatch('toggle_pause')
        app.dispatch('set_editing', {'editing': True})
        app.dispatch('set_editing', {'editing': False})
        require(not app.snapshot()['paused'], 'editing preserves explicit pause state', results)
        app.dispatch('toggle_pause')
        for field, value in [('x', '-0.4'), ('y', '0.4'), ('interval_seconds', '0.005')]:
            app.dispatch('update_parameter', {'operator': 'jager', 'weapon': 'primary', 'field': field, 'value': value})
        for axis, value in [('x', '1.25'), ('y', '1.5')]:
            app.dispatch('set_multiplier', {'axis': axis, 'value': value})
        app.dispatch('toggle_pause'); app.dispatch('simulate_start')
        require(app.runtime.wait_for_cycles(12, 1), 'simulation emits diagnostic cycles', results)
        app.dispatch('simulate_stop'); app.dispatch('toggle_pause')
        require(sink.calls == 0, 'simulation never reaches output sink', results)
        report['simulation'] = app.snapshot()['diagnostics']
        s = app.snapshot()
        app.dispatch('set_mode', {'mode': 'real', 'epoch': s['safety_epoch']})
        require(app.snapshot()['paused'], 'explicit Real starts paused (discard-only)', results)
        app.emergency()
        s = app.snapshot()
        require(s['mode'] == 'simulation' and s['paused'] and s['emergency'], 'emergency returns safe state', results)
        app.dispatch('toggle_weapon', {'operator': 'jager', 'weapon': 'secondary'})
        app.dispatch('select_weapon', {'weapon': 'secondary'})
        expected = app.export_bytes()
        export = folder / 'export.json'
        class Dialog:
            def create_file_dialog(self, *args, **kwargs): return (str(export),)
        api._window = Dialog()
        require(api.invoke('export_file')['exported'] and export.read_bytes() == expected, 'bridge export JSON', results)
        app.dispatch('set_multiplier', {'axis': 'x', 'value': '2'})
        preview = api.invoke('import_file')
        reply = api.invoke('confirm_import', {'token': preview['import_preview']['token']})
        require(reply['ok'] and app.export_bytes() == expected and app.snapshot()['paused'], 'bridge import and safe restoration', results)
        api._close(); api = None
        require(not app._input_source.snapshot()['running'], 'native hooks closed', results)
        app = Application(folder / 'settings', sink=DiscardingMouseSink())
        require(app.export_bytes() == expected, 'settings restored after restart', results)
        require(app.snapshot()['paused'] and app.snapshot()['mode'] == 'simulation', 'restart never restores Real or unpause', results)
        app.close(); app = None
        workers = [t.name for t in threading.enumerate() if t.name.startswith(('R6-', 'r6-'))]
        require(not workers, 'no application workers left', results)
        report['status'] = 'passed'
    except Exception as exc:
        report['status'] = 'failed'; report['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        try:
            if api: api._close()
            elif app: app.close()
        finally:
            with (folder / 'report.json').open('x', encoding='utf-8') as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2)
