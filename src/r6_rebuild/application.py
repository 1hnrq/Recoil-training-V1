"""Backend authority; optional global input/output with safe transient modes."""

from copy import deepcopy
from threading import Event, RLock, Thread, Timer
import uuid

from . import settings
from .core.exact import effective_axes
from .core.simulation import SimulationRuntime
from .profiles.models import Parameters, _keys
from .storage import SettingsStore


class Application:
    def __init__(self, directory, *, sink=None):
        self._lock = RLock()
        self.store = SettingsStore(directory)
        document, self.notices = self.store.load()
        self.ui = document['ui']
        self._sink = sink
        self.runtime = SimulationRuntime(settings.state_from(document), capacity=128, sink=sink)
        self.runtime.start()
        self.revision = 0
        self._timer = None
        self._simulation_epoch = 0
        self._pending_import = None
        self._closed = False
        self._input_source = None
        self._persist_requested = Event()
        self._persist_stop = Event()
        self._persist_thread = None

    def start_global_input(self, source_factory=None):
        from .global_input import GlobalInput
        if self._input_source is not None:
            raise RuntimeError('Entradas globais já iniciadas.')
        self._persist_thread = Thread(target=self._persist_global, name='R6-global-settings', daemon=True)
        self._persist_thread.start()
        self._input_source = (source_factory(self.on_global_input) if source_factory else
                              GlobalInput(self.on_global_input, safety_epoch=lambda: self.runtime.input_token()))
        self.runtime.set_listener_probe(self._input_source.snapshot)
        try:
            self._input_source.start()
        except Exception as exc:
            self.notices.append(f'Entradas globais indisponíveis: {exc}. Use Simulação.')
            self.runtime.fail(f'Inicialização das entradas globais: {exc}')

    def on_global_input(self, event):
        # Never acquire the GUI/disk lock here: the hook must return promptly.
        if not self._closed and self.runtime.handle_input(event):
            self._persist_requested.set()

    def _persist_global(self):
        while True:
            self._persist_requested.wait()
            self._persist_requested.clear()
            with self._lock:
                try:
                    self.store.save(self.configuration())
                except Exception as exc:
                    self.notices.append(f'Falha ao salvar seleção global: {exc}')
                    self.runtime.fail(f'Persistência da seleção global: {exc}')
            if self._persist_stop.is_set():
                return

    def emergency(self):
        self.runtime.emergency()

    def request_pause(self, paused, authorization):
        runtime = self.runtime
        snapshot = runtime.snapshot()
        if not paused and authorization != snapshot['authorization']:
            raise RuntimeError('Solicitação de retomada expirada; confirme novamente.')
        runtime.request_pause(paused, snapshot['safety_epoch'])

    def _stamp(self):
        return self.revision + self.runtime.snapshot()['revision']

    def configuration(self):
        return settings.from_snapshot(self.runtime.snapshot()['state'], self.ui)

    def diagnostics(self):
        # Read-only path: no disk/UI lock, no file picker or mutation queue.
        # Capture one runtime reference so import cannot mix two instances.
        runtime = self.runtime
        return self._diagnostics(runtime.snapshot())

    @staticmethod
    def _diagnostics(snapshot):
        state = snapshot['state']
        operator = next(p for p in state['operators'] if p['id'] == state['selected_operator'])
        active = operator[state['selected_weapon']]
        from .core.exact import Sensitivity
        x, y = effective_axes(Parameters(**active['parameters']), Sensitivity(**state['sensitivity']))
        records = snapshot['output']['records']
        return {**snapshot['status'], 'input': state['input'],
                'operator_label': operator['label'], 'emergency': snapshot['emergency'],
                'primary_enabled': operator['primary']['enabled'],
                'secondary_enabled': operator['secondary']['enabled'],
                # Legacy key retained for consumers; this is reconciled, not a
                # direct Windows query. The panel names each source explicitly.
                'physical_input': snapshot['physical'], 'reconciled_input': snapshot['physical'],
                'sink': snapshot['sink'],
                'input_healthy': snapshot['input_healthy'], 'await_release': snapshot['await_release'],
                'last_emergency_ns': snapshot['last_emergency_ns'],
                'safety_error': snapshot['safety_error'],
                'effective': {'x': str(x), 'y': str(y)},
                'requested_seconds': active['parameters']['interval_seconds'],
                'residuals': snapshot['residuals'], 'generation': state['reset_generation'],
                'last': records[-1] if records else None, 'recent': records[-12:],
                'cycles': snapshot['output']['cycles'], 'total_x': snapshot['output']['total_x'],
                'total_y': snapshot['output']['total_y'], 'error': snapshot['error'],
                'wait_backend': snapshot['wait_backend']}

    def snapshot(self):
        with self._lock:
            snapshot = self.runtime.snapshot()
            state = snapshot['state']
            entries = {p['id']: p for p in state['operators']}
            operators = []
            for original in settings.catalog()['operators']:
                p = entries[original['id']]
                operators.append({'id': p['id'], 'label': p['label'], 'legacy_index': original['legacy_index'],
                                  **{slot: {**p[slot]['parameters'], 'enabled': p[slot]['enabled']}
                                     for slot in ('primary', 'secondary')}})
            return {'revision': self.revision + snapshot['revision'], 'operators': operators,
                    'selected': state['selected_operator'], 'weapon': state['selected_weapon'],
                    'paused': state['global_paused'], 'multipliers': state['sensitivity'],
                    'view': self.ui['view'], 'reticle': deepcopy(self.ui['reticle']),
                    'notices': list(self.notices), 'saved': not self._persist_requested.is_set(),
                    'simulation_only': snapshot['mode'] == 'simulation',
                    'mode': snapshot['mode'], 'safety_epoch': snapshot['authorization'],
                    'emergency': snapshot['emergency'],
                    'global_input': self._input_source.snapshot() if self._input_source else None,
                    'diagnostics': self._diagnostics(snapshot)}

    def _stop_input(self, epoch=None):
        with self._lock:
            if not self._closed and (epoch is None or epoch == self._simulation_epoch):
                if any(self.runtime.snapshot()['state']['input'].values()):
                    self.runtime.command('set_mouse_buttons', left=False, right=False)

    def dispatch(self, action, payload=None):
        with self._lock:
            if self._closed:
                raise RuntimeError('Aplicação encerrada.')
            if payload is None:
                payload = {}
            if not isinstance(payload, dict):
                raise ValueError('Comando precisa de um objeto.')
            fields = {'snapshot': set(), 'select_operator': {'id'}, 'select_weapon': {'weapon'},
                      'toggle_weapon': {'weapon', 'operator'}, 'toggle_pause': set(),
                      'update_parameter': {'operator', 'weapon', 'field', 'value'},
                      'step_parameter': {'operator', 'weapon', 'field', 'direction'},
                      'set_multiplier': {'axis', 'value'}, 'set_view': {'view'},
                      'set_reticle': {'field', 'value'}, 'save': set(),
                      'simulate_start': set(), 'simulate_stop': set(),
                      'set_mode': {'mode', 'epoch'}, 'set_editing': {'editing'}, 'emergency': set(),
                      'set_pause': {'paused', 'epoch'}}
            if action not in fields:
                raise ValueError('Comando desconhecido.')
            _keys(payload, fields[action], action)
            if action == 'snapshot':
                return self.snapshot()
            if action == 'emergency':
                self.emergency()
                return self.snapshot()
            if action == 'set_mode':
                authorization = self.runtime.snapshot()
                if payload['epoch'] != authorization['authorization']:
                    raise RuntimeError('Confirmação expirada; confirme o modo novamente.')
                if self._timer is not None:
                    self._timer.cancel()
                self._simulation_epoch += 1
                self.runtime.set_mode(payload['mode'], authorization['safety_epoch'])
                return self.snapshot()
            if action == 'set_editing':
                self.runtime.set_editing(payload['editing'])
                return self.snapshot()
            if action == 'set_pause':
                self.request_pause(payload['paused'], payload['epoch'])
                return self.snapshot()
            if action in ('toggle_pause', 'simulate_start', 'simulate_stop'):
                if action == 'toggle_pause':
                    self.runtime.command('on_p_release')
                elif action == 'simulate_start':
                    if self._timer is not None:
                        self._timer.cancel()
                    # Does not lift any pause. Two seconds of synthetic input only.
                    self.runtime.command('set_mouse_buttons', left=True, right=True)
                    self._simulation_epoch += 1
                    self._timer = Timer(2.0, self._stop_input, args=(self._simulation_epoch,))
                    self._timer.daemon = True
                    self._timer.start()
                else:
                    if self._timer is not None:
                        self._timer.cancel()
                    self._simulation_epoch += 1
                    already_released = not any(self.runtime.snapshot()['state']['input'].values())
                    self._stop_input()
                    if already_released:
                        return self.snapshot()  # focus loss is idempotent; import token stays valid
                self.revision += 1
                return self.snapshot()

            document = self.configuration()
            candidate = settings.state_from(document)
            command, args, kwargs = None, (), {}
            if action == 'select_operator':
                command, args = 'select_operator', (payload['id'],)
                document['ui']['view'] = 'weapons'
            elif action == 'select_weapon':
                command, args = 'select_weapon', (payload['weapon'],)
            elif action == 'toggle_weapon':
                command, args, kwargs = 'toggle_weapon_enabled', (payload['weapon'],), {'operator_id': payload['operator']}
            elif action in ('update_parameter', 'step_parameter'):
                if payload['field'] not in ('x', 'y', 'interval_seconds'):
                    raise ValueError('Campo desconhecido.')
                # Target is explicit: queued edits never drift to another selected operator.
                profile = candidate.operators[payload['operator']]
                if payload['weapon'] not in ('primary', 'secondary'):
                    raise ValueError('Arma desconhecida.')
                values = getattr(profile, payload['weapon']).parameters.to_dict()
                value = (settings.stepped(payload['field'], values[payload['field']], payload['direction'])
                         if action == 'step_parameter' else payload['value'])
                values[payload['field']] = settings.decimal_text(value, payload['field'])
                command, args = 'update_parameters', (payload['weapon'], Parameters(**values))
                kwargs = {'operator_id': payload['operator']}
            elif action == 'set_multiplier':
                if payload['axis'] not in ('x', 'y'):
                    raise ValueError('Eixo desconhecido.')
                settings.decimal_text(payload['value'], payload['axis'])
                factors = deepcopy(document['sensitivity'])
                factors[payload['axis']] = payload['value']
                command, kwargs = 'set_sensitivity', factors
            elif action == 'set_view':
                document['ui']['view'] = payload['view']
            elif action == 'set_reticle':
                if payload['field'] not in ('mark', 'opacity', 'size'):
                    raise ValueError('Preferência desconhecida.')
                document['ui']['reticle'][payload['field']] = payload['value']
            if command:
                getattr(candidate, command)(*args, **kwargs)
            next_document = settings.from_snapshot(candidate.snapshot(), document['ui'])
            # Acknowledgment means durable: disk errors leave runtime/settings untouched.
            self.store.save(next_document)
            if command:
                self.runtime.command(command, *args, **kwargs)
            self.ui = next_document['ui']
            self.revision += 1
            return self.snapshot()

    def preview_import(self, raw):
        with self._lock:
            document, warnings = settings.import_document(raw, self.configuration())
            token = uuid.uuid4().hex
            self._pending_import = (token, self._stamp(), document)
            return {'token': token, 'warnings': warnings, 'operators': 75, 'parameters': 450}

    def confirm_import(self, token):
        with self._lock:
            pending = self._pending_import
            if not pending or token != pending[0] or pending[1] != self._stamp():
                raise ValueError('Importação expirada; selecione o arquivo novamente.')
            document = pending[2]
            # Prepare replacement before committing; startup pause/input policy applies.
            replacement = SimulationRuntime(settings.state_from(document), capacity=128, sink=self._sink)
            try:
                self.store.save(document)
            except Exception:
                replacement.stop()
                raise
            if self._timer is not None:
                self._timer.cancel()
            self._simulation_epoch += 1
            self.revision += self.runtime.snapshot()['revision']
            self.runtime.stop()
            self.runtime = replacement
            if self._input_source:
                self.runtime.set_listener_probe(self._input_source.snapshot)
            self.runtime.start()
            self.ui = document['ui']
            self._pending_import = None
            self.revision += 1
            return self.snapshot()

    def export_bytes(self):
        with self._lock:
            return settings.encode(self.configuration())

    def close(self):
        self.emergency()  # stop before waiting for file operations / executor
        if self._input_source:
            self._input_source.close()
        if self._persist_thread and self._persist_thread.is_alive():
            self._persist_stop.set()
            self._persist_requested.set()
            self._persist_thread.join(2)
            if self._persist_thread.is_alive():
                raise TimeoutError('Persistência global não encerrou.')
        with self._lock:
            if not self._closed:
                self._closed = True
                if self._timer is not None:
                    self._timer.cancel()
                self.runtime.stop()
