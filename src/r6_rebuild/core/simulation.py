"""Existing exact worker with optional, explicitly armed output (Phase 5).

No device exists by default. Math/scheduling remain shared by both modes.
Native output never holds the state lock. One worker, no movement queue.
"""

from collections import deque
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from threading import Condition, Event, Thread
from time import monotonic_ns
from typing import Callable
from uuid import uuid4

from .compensation import SimulatedMovement, SimulationEngine
from .state import ApplicationState
from .timing import CycleTiming, NoCatchUpSchedule
from .waiting import make_waiter
from ..mouse_output import OutputGate


@dataclass(frozen=True, slots=True)
class SimulationRecord:
    movement: SimulatedMovement
    timing: CycleTiming
    mode: str = 'simulation'


class SimulatedOutput:
    """Bounded diagnostic buffer; total counters include discarded old records."""

    def __init__(self, capacity: int = 2048):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("capacity must be a positive integer")
        self._records = deque(maxlen=capacity)
        self.cycles = 0
        self.total_x = self.total_y = 0

    def record(self, movement: SimulatedMovement, timing: CycleTiming, mode='simulation') -> None:
        self._records.append(SimulationRecord(movement, timing, mode))
        self.cycles += 1
        self.total_x += movement.dx
        self.total_y += movement.dy

    def snapshot(self) -> dict:
        return {"simulation_only": True, "cycles": self.cycles,
                "total_x": self.total_x, "total_y": self.total_y,
                "discarded_records": self.cycles - len(self._records),
                "records": [asdict(record) for record in self._records]}


class SimulationRuntime:
    HEARTBEAT_TIMEOUT_NS = 250_000_000
    COMMANDS = frozenset({"select_operator", "select_weapon", "set_global_pause",
                          "toggle_global_pause", "on_p_release", "set_mouse_buttons",
                          "set_weapon_enabled", "toggle_weapon_enabled",
                          "update_parameters", "set_sensitivity"})

    def __init__(self, state: ApplicationState, *, seed: int | None = None,
                 capacity: int = 2048, coin: Callable[[], bool] | None = None, sink=None):
        self._state = state.clone()  # the caller cannot mutate the worker's state
        self._engine = SimulationEngine(self._state, seed=seed, coin=coin)
        self._schedule = NoCatchUpSchedule()
        self._output = SimulatedOutput(capacity)
        self._condition = Condition()
        self._waiter = make_waiter()
        self._thread = None
        self._stopped = False
        self._error = None
        self._wait_calls = 0
        self._gate = OutputGate(sink)
        self._mode = 'simulation'
        self._emergency = False
        self._emergency_pending = Event()
        self._input_healthy = False
        self._heartbeat_ns = 0
        self._physical = {'left': False, 'right': False}
        self._await_release = False
        self._editing = False
        self._revision = 0
        self._last_emergency_ns = None
        self._safety_error = None
        self._instance_id = uuid4().hex
        self._input_diagnostics = None
        self._last_input_change = None
        self._last_stop = None
        self._was_eligible = False
        self._operation_blocks = {}
        self._input_generation = 0
        self._input_received = None
        self._input_rejected = 0
        self._watchdog = None
        self._heartbeat_received_ns = None
        self._heartbeat_delay_ns = None
        self._heartbeat_gap_ns = None
        self._last_health_delivery = None
        self._listener_probe = None
        self._last_transition = None
        self._lock_wait = {}
        self._dispatch_context = None
        self._stale_completions = 0
        self._discarded_preparations = 0

    @contextmanager
    def _locked(self, caller):
        start = monotonic_ns()
        with self._condition:
            waited = monotonic_ns() - start
            old = self._lock_wait.get(caller, {'max_ns': 0, 'count': 0})
            self._lock_wait[caller] = {'last_ns': waited, 'max_ns': max(waited, old['max_ns']),
                                       'count': old['count'] + 1}
            yield

    def set_listener_probe(self, probe):
        # Must only read the listener's immutable progress publication; no I/O.
        with self._locked('listener_probe'):
            self._listener_probe = probe

    def _listener_status(self):
        try:
            return deepcopy(self._listener_probe()) if self._listener_probe else None
        except Exception as error:
            # Diagnostic collection must never prevent a safety transition.
            return {'diagnostic_error': f'{type(error).__name__}: {error}'}

    def _heartbeat_info(self, now):
        return {'produced_ns': self._heartbeat_ns, 'received_ns': self._heartbeat_received_ns,
                'age_ns': max(0, now - self._heartbeat_ns), 'timeout_ns': self.HEARTBEAT_TIMEOUT_NS,
                'delivery_delay_ns': self._heartbeat_delay_ns, 'publication_gap_ns': self._heartbeat_gap_ns,
                'healthy': self._input_healthy, 'last_delivery': deepcopy(self._last_health_delivery)}

    def _record_transition(self, code, detail, now=None):
        if self._mode != 'real':
            return
        now = monotonic_ns() if now is None else now
        self._last_transition = {'code': code, 'detail': detail, 'observed_ns': now,
                                 'from': 'real', 'to': 'simulation', 'heartbeat': self._heartbeat_info(now),
                                 'listener': self._listener_status(), 'output': self._gate.snapshot(),
                                 'lock_wait': deepcopy(self._lock_wait), 'input_generation': self._input_generation,
                                 'state_generation': self._state.reset_generation}

    def _operational_failure(self, code, detail, now=None):
        self._record_transition(code, detail, now)
        self._gate.block()  # metadata only, never waits for an in-flight native call
        self._safety_error = detail
        self._safe_state()

    def _check_availability(self, now):
        if self._mode != 'real':
            return
        if not self._input_healthy:
            self._operational_failure('listener_unavailable', 'Listener global indisponível.', now)
        elif now - self._heartbeat_ns > self.HEARTBEAT_TIMEOUT_NS:
            self._operational_failure('heartbeat_timeout', 'Heartbeat global vencido (limite 250 ms); confirme Real novamente.', now)
        elif not self._gate.operational:
            error = self._gate.snapshot()['error']
            self._operational_failure('output_failure' if error else 'output_unavailable',
                                      error or 'Saída Windows indisponível; confirme Real novamente.', now)

    def input_token(self):
        with self._locked('input_token'):
            return f'{self._instance_id}:{self._input_generation}'

    def _observed_hook_buttons(self):
        return (self._input_diagnostics or {}).get('hook_buttons', self._physical)

    @property
    def _period_ns(self):
        return None if self._operation_blocks else self._engine.period_ns

    def _changed(self, reason='mudança de estado'):
        self._revision += 1
        self._engine.synchronize()
        eligible = self._period_ns is not None
        context = (self._state.reset_generation, self._mode, self._period_ns,
                   self._await_release, bool(self._operation_blocks),
                   self._state.left_pressed, self._state.right_pressed)
        if context != self._dispatch_context:
            self._dispatch_context = context
            self._gate.invalidate()
        if self._was_eligible and not eligible:
            self._last_stop = {'reason': reason, 'observed_ns': monotonic_ns()}
        self._was_eligible = eligible
        self._schedule.remaining(monotonic_ns(), self._period_ns,
                                 self._state.reset_generation)
        self._waiter.wake()
        self._condition.notify_all()

    def _clear_active_input(self):
        self._state.set_mouse_buttons(left=False, right=False)
        self._engine.synchronize()
        self._schedule.disarm()

    def _safe_state(self, *, emergency=False):
        self._input_generation += 1
        self._mode = 'simulation'
        self._emergency = emergency
        if emergency:
            self._state.set_global_pause(True)
        self._clear_active_input()
        self._await_release = True
        reason = 'emergência F12/controle' if emergency else 'falha operacional: ' + str(self._safety_error)
        self._last_stop = {'reason': reason, 'observed_ns': monotonic_ns()}
        self._changed(reason)

    def fail(self, reason):
        self._gate.block()
        with self._locked('failure'):
            if not self._stopped:
                self._operational_failure('critical_failure', str(reason))

    def emergency(self):
        start = monotonic_ns()
        self._emergency_pending.set()
        self._gate.block()  # bypass Application/disk/bridge queues
        with self._locked('emergency'):
            if not self._stopped:
                self._record_transition('emergency', 'F12/controle de emergência')
                self._safe_state(emergency=True)
            self._last_emergency_ns = monotonic_ns() - start
            self._emergency_pending.clear()

    def set_mode(self, mode, epoch):
        if mode not in ('simulation', 'real') or type(epoch) is not int:
            raise ValueError('Modo ou autorização inválidos.')
        with self._locked('mode'):
            if self._stopped:
                raise RuntimeError('Motor encerrado.')
            if epoch != self._gate.epoch or self._emergency_pending.is_set():
                raise RuntimeError('Confirmação expirada; confirme o modo novamente.')
            if mode == 'real':
                if not self._input_healthy or monotonic_ns() - self._heartbeat_ns > self.HEARTBEAT_TIMEOUT_NS:
                    raise RuntimeError('Entradas globais indisponíveis.')
                self._gate.arm(epoch)
            else:
                self._record_transition('manual_mode', 'Troca explícita para Simulação')
                self._gate.block()
            self._state.set_global_pause(True)
            self._clear_active_input()
            self._input_generation += 1
            self._mode = mode
            self._emergency = False
            self._safety_error = None
            self._await_release = any(self._observed_hook_buttons().values())
            self._changed('troca de modo confirmada')

    def set_editing(self, editing):
        if type(editing) is not bool:
            raise ValueError('Estado de edição inválido.')
        with self._condition:
            self._editing = editing

    @contextmanager
    def operational_block(self, reason):
        """Suspend emission, not the user's pause; never restore stale input.

        Tokens allow nested operations and finally releases only its own token.
        F12/other pause commands during the operation are never overwritten.
        """
        token = uuid4().hex
        with self._condition:
            if self._stopped:
                raise RuntimeError('Motor encerrado.')
            self._operation_blocks[token] = str(reason)
            self._input_generation += 1
            self._clear_active_input()
            self._changed('operação interna: ' + str(reason))
        try:
            yield
        finally:
            with self._condition:
                self._operation_blocks.pop(token, None)
                if not self._stopped:
                    if self._mode == 'real':
                        self._await_release = self._await_release or any(self._observed_hook_buttons().values())
                    self._changed('fim da operação interna')

    def request_pause(self, paused, epoch):
        with self._condition:
            if self._stopped:
                raise RuntimeError('Motor encerrado.')
            if not paused and (epoch != self._gate.epoch or self._emergency_pending.is_set()):
                raise RuntimeError('Solicitação de retomada expirada após parada de segurança.')
            self._state.set_global_pause(paused)
            self._changed('comando explícito de pausa geral')

    def handle_input(self, event):
        if event.kind == 'emergency':
            self.emergency()
            return False
        with self._locked('input'):
            if self._stopped:
                return False
            if event.kind == 'buttons' and event.sequence is not None:
                previous = self._input_received
                if ((event.safety_token is not None and event.safety_token != self.input_token())
                        or (previous and (event.observed_ns < previous['observed_ns'] or
                            (event.source_id == previous['source_id'] and event.sequence <= previous['sequence'])))):
                    self._input_rejected += 1
                    return False
                self._input_received = {'observed_ns': event.observed_ns, 'sequence': event.sequence,
                                        'source_id': event.source_id, 'buttons': dict(event.value)}
            if event.diagnostics is not None:
                if (event.diagnostics.get('published_ns', event.observed_ns) >=
                        (self._input_diagnostics or {}).get('published_ns', 0)):
                    self._input_diagnostics = deepcopy(event.diagnostics)
            if event.kind == 'health':
                now = monotonic_ns()
                self._last_health_delivery = {'healthy': bool(event.value), 'produced_ns': event.observed_ns,
                                             'received_ns': now, 'delay_ns': max(0, now - event.observed_ns),
                                             'publication_gap_ns': event.observed_ns - self._heartbeat_ns if self._heartbeat_ns else None}
                # Do not hide a missed deadline by replacing the old timestamp
                # with a late publication. Only real listener progress renews it.
                if not event.value and self._mode == 'real':
                    self._operational_failure('listener_unavailable', 'Listener global indisponível.', now)
                else:
                    self._check_availability(now)
                changed = self._input_healthy != bool(event.value)
                self._input_healthy = bool(event.value)
                self._heartbeat_gap_ns = event.observed_ns - self._heartbeat_ns if self._heartbeat_ns else None
                self._heartbeat_ns = event.observed_ns
                self._heartbeat_received_ns = now
                self._heartbeat_delay_ns = max(0, now - event.observed_ns)
                self._check_availability(now)
                if changed:
                    self._revision += 1
                self._condition.notify_all()  # wakes watchdog, not a synthetic heartbeat
                return False
            if event.kind == 'buttons':
                if self._physical != event.value:
                    self._last_input_change = {'observed_ns': event.observed_ns,
                                              'buttons': dict(event.value),
                                              'source': (event.diagnostics or {}).get('last_change', {}).get('source', 'event')}
                self._physical = dict(event.value)
                if self._mode == 'real':
                    if self._await_release and not any(self._observed_hook_buttons().values()):
                        self._await_release = False
                    buttons = self._physical if not (self._await_release or self._operation_blocks) else {'left': False, 'right': False}
                    self._state.set_mouse_buttons(**buttons)
                    self._changed('entrada: ' + self._last_input_change['source'] if self._last_input_change else 'entrada')
                return False
            if event.kind == 'key':
                if event.own_window and self._editing:
                    return False
                if event.value == 'pause':
                    self._state.toggle_global_pause()
                elif event.value in ('primary', 'secondary'):
                    self._state.select_weapon(event.value)
                else:
                    return False
                self._changed('atalho global: ' + event.value)
                return event.value in ('primary', 'secondary')
            return False

    def command(self, name: str, *args, **kwargs):
        if name not in self.COMMANDS:
            raise ValueError("unknown simulation command")
        with self._locked('command'):
            if self._stopped:
                raise RuntimeError("simulation is stopped")
            if name == 'set_mouse_buttons' and self._mode == 'real':
                if any(kwargs.values()):
                    raise RuntimeError('Entrada sintética não pode alimentar o modo Real.')
                return  # browser blur/simulation stop must not override global input
            if name == 'set_mouse_buttons' and self._operation_blocks and any(kwargs.values()):
                raise RuntimeError('Entrada sintética bloqueada durante operação interna.')
            result = getattr(self._state, name)(*args, **kwargs)
            self._changed('comando: ' + name)
            return result

    def start(self) -> None:
        with self._condition:
            if self._thread is not None or self._stopped:
                raise RuntimeError("a simulation runtime is single-use")
            self._schedule.disarm()
            self._thread = Thread(target=self._run, name="R6-compensation", daemon=True)
            self._watchdog = Thread(target=self._watch_health, name='R6-safety-watchdog', daemon=True)
            self._watchdog.start()
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._gate.block()
        with self._condition:
            if not self._stopped:
                self._record_transition('shutdown', 'Encerramento solicitado')
                self._mode = 'simulation'
                self._stopped = True
                self._input_generation += 1
                self._clear_active_input()
                self._last_stop = {'reason': 'encerramento', 'observed_ns': monotonic_ns()}
                self._state.set_global_pause(True)
                self._engine.synchronize()
                self._schedule.disarm()
                self._waiter.wake()
                self._condition.notify_all()
            thread = self._thread
        deadline = monotonic_ns() + int(timeout * 1e9)
        for worker in (thread, self._watchdog):
            if worker is not None:
                worker.join(max(0, (deadline - monotonic_ns()) / 1e9))
                if worker.is_alive():
                    raise TimeoutError('Worker ainda encerrando; chamada nativa em andamento não pode ser cancelada.')
        with self._condition:
            self._waiter.close()

    def wait_for_cycles(self, count: int, timeout: float = 2.0) -> bool:
        if type(count) is not int or count < 0:
            raise ValueError("count must be a nonnegative integer")
        with self._condition:
            self._condition.wait_for(lambda: self._output.cycles >= count or self._stopped,
                                     timeout=timeout)
            if self._error is not None:
                raise RuntimeError(self._error)
            return self._output.cycles >= count

    def snapshot(self) -> dict:
        with self._locked('snapshot'):
            rx, ry = self._engine.residuals
            state, output = self._state.snapshot(), self._output.snapshot()
            state['simulation_only'] = output['simulation_only'] = self._mode == 'simulation'
            return {"state": state, "output": output,
                    "revision": self._revision, "mode": self._mode,
                    "authorization": f'{self._instance_id}:{self._gate.epoch}',
                    "emergency": self._emergency, "safety_epoch": self._gate.epoch,
                    "sink": self._gate.snapshot(), "physical": dict(self._physical),
                    "status": self._status(),
                    "input_healthy": self._input_healthy, "await_release": self._await_release,
                    "last_emergency_ns": self._last_emergency_ns, "safety_error": self._safety_error,
                    "residuals": {"x": str(rx), "y": str(ry)}, "error": self._error,
                    "stopped": self._stopped, "wait_calls": self._wait_calls,
                    "wait_backend": self._waiter.name,
                    "running": self._thread is not None and self._thread.is_alive()}

    def _status(self):
        # Called under the same condition as the worker/input transitions.
        now = monotonic_ns()
        running = bool(self._thread and self._thread.is_alive() and not self._stopped)
        reasons = []
        if not running: reasons.append('worker_inactive')
        if self._error: reasons.append('worker_error')
        if self._operation_blocks: reasons.append('operation_block')
        if self._state.global_paused: reasons.append('global_pause')
        if not self._state.active_profile.enabled: reasons.append('weapon_pause')
        if not self._state.active_profile.parameters.configured: reasons.append('unconfigured_profile')
        if self._mode == 'real':
            if any((self._input_diagnostics or {}).get('pending', {}).values()): reasons.append('input_revalidation')
            if self._await_release: reasons.append('await_release')
            if not self._input_healthy: reasons.append('listener_unavailable')
            if now - self._heartbeat_ns > self.HEARTBEAT_TIMEOUT_NS: reasons.append('heartbeat_stale')
            if not self._gate.operational: reasons.append('output_unavailable')
            if self._gate.snapshot()['blocked']: reasons.append('output_blocked')
        if not self._state.left_pressed: reasons.append('left_released')
        if not self._state.right_pressed: reasons.append('right_released')
        return {'observed_ns': now, 'eligible': not reasons, 'blockers': reasons,
                'worker_running': running, 'worker_active': not reasons,
                'mode': self._mode, 'paused': self._state.global_paused,
                'selected_operator': self._state.selected_operator,
                'selected_weapon': self._state.selected_weapon.value,
                'weapon_enabled': self._state.active_profile.enabled,
                'holding': all(self._physical.values()),
                'engine_holding': self._state.left_pressed and self._state.right_pressed,
                'listener_events': deepcopy(self._input_diagnostics),
                'last_input_change': deepcopy(self._last_input_change),
                'input_received': deepcopy(self._input_received), 'input_rejected': self._input_rejected,
                'last_stop': deepcopy(self._last_stop),
                'heartbeat': self._heartbeat_info(now), 'listener_progress': self._listener_status(),
                'last_transition': deepcopy(self._last_transition), 'lock_wait': deepcopy(self._lock_wait),
                'stale_completions': self._stale_completions,
                'discarded_preparations': self._discarded_preparations,
                'operation_blocks': sorted(self._operation_blocks.values())}

    def _watch_health(self):
        """Observe the existing 250 ms deadline even while native output blocks.

        This thread NEVER produces/refreshes a heartbeat or emits a movement.
        """
        try:
            with self._condition:
                while not self._stopped:
                    now = monotonic_ns()
                    self._check_availability(now)
                    timeout = (max(1, self._heartbeat_ns + self.HEARTBEAT_TIMEOUT_NS - now) / 1e9
                               if self._mode == 'real' else None)
                    self._condition.wait(timeout)
        except Exception as error:
            self._fatal_worker(error, 'watchdog')

    def _fatal_worker(self, error, source):
        self._gate.block()
        with self._condition:
            self._error = f'{source}: {type(error).__name__}: {error}'
            self._record_transition('critical_worker_failure', self._error)
            self._mode = 'simulation'
            self._safety_error = self._error
            self._stopped = True
            self._input_generation += 1
            self._last_stop = {'reason': 'falha do worker: ' + self._error, 'observed_ns': monotonic_ns()}
            self._clear_active_input()
            self._waiter.wake()
            self._condition.notify_all()

    def _run(self) -> None:
        try:
            while True:
                prepared = None
                with self._locked('worker'):
                    if self._stopped:
                        break
                    now = monotonic_ns()
                    self._check_availability(now)
                    remaining = self._schedule.remaining(now, self._period_ns,
                                                         self._state.reset_generation)
                    if remaining == 0:
                        start = monotonic_ns()
                        movement = self._engine.step(start)
                        if self._mode == 'real':
                            prepared = (movement, self._gate.ticket(), self._heartbeat_ns + self.HEARTBEAT_TIMEOUT_NS)
                        else:
                            timing = self._schedule.complete(start, monotonic_ns())
                            self._output.record(movement, timing, 'simulation')
                            self._condition.notify_all()
                            continue
                    else:
                        self._wait_calls += 1
                if prepared is not None:
                    # The sole emitter performs native I/O with NO runtime lock.
                    # Gate admission rechecks the ticket; there is no queue/retry.
                    movement, ticket, valid_until = prepared
                    failure = None
                    try:
                        outcome = self._gate.dispatch(movement.dx, movement.dy, ticket, valid_until_ns=valid_until)
                    except Exception as exc:
                        failure = f'{type(exc).__name__}: {exc}'
                    end = monotonic_ns()
                    with self._locked('completion'):
                        if failure is not None:
                            if not self._stopped and self._mode == 'real':
                                self._operational_failure('output_failure', failure, end)
                            continue
                        if self._stopped:
                            break
                        self._check_availability(end)
                        if ticket != self._gate.ticket() or self._mode != 'real':
                            self._stale_completions += int(outcome['admitted'])
                            self._discarded_preparations += int(not outcome['admitted'])
                            # Never complete an old generation into the new
                            # schedule or rush a pending cycle after a slow call.
                            self._schedule.disarm()
                            self._schedule.remaining(end, self._period_ns, self._state.reset_generation)
                        elif not outcome['admitted']:
                            self._discarded_preparations += 1
                            self._operational_failure('dispatch_rejected', 'Emissão preparada descartada: ' + outcome['reason'], end)
                        else:
                            timing = self._schedule.complete(start, end)
                            self._output.record(movement, timing, 'real')
                        self._condition.notify_all()
                    continue
                # Release the state lock while blocking. The interrupt signal
                # stays pending even if a command arrives before this wait.
                self._waiter.wait(remaining)
                # Every wake rechecks eligibility and deadline, including early wakes.
        except Exception as error:
            self._fatal_worker(error, 'compensation')
