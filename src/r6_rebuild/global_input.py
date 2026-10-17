"""Windows low-level input observation; no suppression, text log or injection.

Only four shortcuts and two mouse buttons survive the reducer. Low-level hooks
run on our message-pump thread, not inside another process. Callbacks must be
short and must never perform disk I/O. All native calls are replaceable in tests.
"""

import ctypes as C
from copy import deepcopy
from ctypes import wintypes as W
from dataclasses import dataclass
import os
from threading import Event, Thread
from time import monotonic_ns
from uuid import uuid4


@dataclass(frozen=True)
class InputEvent:
    kind: str
    value: object
    observed_ns: int
    own_window: bool = False
    diagnostics: dict | None = None
    sequence: int | None = None
    source_id: str | None = None
    safety_token: object = None


@dataclass(frozen=True)
class SampleTicket:
    sequence: int
    started_ns: int
    hook_sequences: tuple[int, int]
    generation: int
    source_id: str


class InputReducer:
    # Input validation only; never changes the compensation scheduler.
    MAX_SAMPLE_AGE_NS = 50_000_000
    VALIDATION_NS = 100_000_000
    VOTE_GAP_NS = 5_000_000
    KEYS = {0x50: 'pause', 0x31: 'primary', 0x32: 'secondary', 0x7B: 'emergency'}
    MOUSE = {0x201: ('left', True), 0x202: ('left', False),
             0x204: ('right', True), 0x205: ('right', False)}

    def __init__(self, emit, *, clock=monotonic_ns, safety_epoch=None):
        self.emit = emit
        self.clock = clock
        self.safety_epoch = safety_epoch
        self._safety_token = safety_epoch() if safety_epoch else None
        self.source_id = uuid4().hex
        self.sequence = self.delivery_sequence = self.sample_sequence = self.generation = 0
        self._last_sample = 0
        self.held = set()
        self.hook_buttons = {'left': False, 'right': False}
        self.buttons = {'left': False, 'right': False}
        self.hook_sequences = {'left': 0, 'right': 0}
        self.presses = {'left': None, 'right': None}
        self.pending = {'left': None, 'right': None}
        self.stats = {'down': {'left': 0, 'right': 0}, 'up': {'left': 0, 'right': 0},
                      'duplicates': 0, 'injected_ignored': 0,
                      'reconciled_releases': {'left': 0, 'right': 0},
                      'confirmed_releases': {'left': 0, 'right': 0},
                      'recoveries': {'left': 0, 'right': 0}, 'discarded_samples': 0,
                      'last_release': None, 'last_rejected_sample': None,
                      'last_event': None, 'last_change': None, 'async_sample': None}

    def diagnostics(self):
        return deepcopy({**self.stats, 'hook_buttons': self.hook_buttons,
                         'reconciled_buttons': self.buttons, 'pending': self.pending,
                         'presses': self.presses, 'hook_sequences': self.hook_sequences,
                         'event_sequence': self.sequence, 'delivery_sequence': self.delivery_sequence,
                         'source_id': self.source_id, 'generation': self.generation,
                         'published_ns': self.clock()})

    def _sync_safety(self):
        if self.safety_epoch:
            token = self.safety_epoch()
            if token != self._safety_token:
                self._safety_token = token
                self.invalidate('safety_epoch')

    def invalidate(self, reason):
        """Revoke every press lease, retaining raw hook evidence until UP."""
        self.generation += 1
        for name in self.buttons:
            had_press = self.presses[name] is not None
            self.presses[name] = self.pending[name] = None
            if had_press:
                self._release_reason(name, reason, confirmed=True)
            self._transition(name, False, reason, force=had_press)

    def begin_sample(self):
        self._sync_safety()
        self.sample_sequence += 1
        return SampleTicket(self.sample_sequence, self.clock(), tuple(self.hook_sequences.values()),
                            self.generation, self.source_id)

    def keyboard(self, message, vk, flags=0, own_window=False):
        self._sync_safety()
        if vk not in self.KEYS or flags & 0x12:  # injected / lower integrity
            return
        down = message in (0x100, 0x104)
        up = message in (0x101, 0x105)
        if down and vk not in self.held:
            self.held.add(vk)
            if vk == 0x7B:  # emergency on DOWN, never wait for release
                self.emit(InputEvent('emergency', None, self.clock(), own_window))
                self.invalidate('F12')
        elif up and vk in self.held:
            self.held.remove(vk)
            if vk != 0x7B:
                self.emit(InputEvent('key', self.KEYS[vk], self.clock(), own_window))

    def mouse(self, message, flags=0, own_window=False):
        self._sync_safety()
        if message not in self.MOUSE:
            return  # never retain positions, wheel or movement
        if flags & 3:
            self.stats['injected_ignored'] += 1
            return
        name, down = self.MOUSE[message]
        self.sequence += 1
        self.hook_sequences[name] = self.sequence
        self.stats['down' if down else 'up'][name] += 1
        self.stats['last_event'] = {'button': name, 'down': down, 'source': 'hook',
                                    'observed_ns': self.clock(), 'sequence': self.sequence}
        if self.hook_buttons[name] == down:
            self.stats['duplicates'] += 1
            return  # duplicate DOWN cannot renew a revoked press or its deadline
        self.hook_buttons[name] = down
        self.presses[name] = self.sequence if down else None
        self.pending[name] = None
        if not down:
            self._release_reason(name, 'hook_up', confirmed=True)
        self._transition(name, down, 'hook', own_window, force=not down)

    def _transition(self, name, down, source, own_window=False, *, force=False):
        if self.buttons[name] != down or force:
            self.buttons[name] = down
            now = self.clock()
            self.delivery_sequence += 1
            self.stats['last_change'] = {'button': name, 'down': down,
                                         'source': source, 'observed_ns': now,
                                         'sequence': self.delivery_sequence}
            self.emit(InputEvent('buttons', dict(self.buttons), now, own_window and down,
                                self.diagnostics(), self.delivery_sequence, self.source_id,
                                self._safety_token))

    def _release_reason(self, name, reason, *, confirmed):
        self.stats['last_release'] = {'button': name, 'reason': reason, 'confirmed': confirmed,
                                      'observed_ns': self.clock(), 'event_sequence': self.sequence,
                                      'sample_sequence': self._last_sample}

    def _suspend(self, name, reason, now):
        if self.presses[name] is None or self.pending[name] is not None:
            return
        self.pending[name] = {'press': self.presses[name], 'since_ns': now,
                              'reason': reason, 'positive': 0,
                              'negative': 1 if reason == 'async_negative' else 0,
                              'last_vote_ns': now if reason == 'async_negative' else None}
        if self.buttons[name]:
            self.stats['reconciled_releases'][name] += 1
        self._release_reason(name, reason, confirmed=False)
        self._transition(name, False, 'reconcile', force=True)

    def _confirm_release(self, name, reason):
        self.presses[name] = self.pending[name] = None
        self.stats['confirmed_releases'][name] += 1
        self._release_reason(name, reason, confirmed=True)
        self._transition(name, False, reason, force=True)

    def reconcile(self, left_down, right_down, *, ticket=None, finished_ns=None):
        """Only a live non-injected hook DOWN authorizes a bounded recovery.

        Production takes a ticket BEFORE querying either Windows button. The
        no-ticket form is for already-coherent simulated samples in tests.
        """
        ticket = ticket or self.begin_sample()
        self._sync_safety()
        now = self.clock()
        end = now if finished_ns is None else finished_ns
        for name, pending in self.pending.items():
            if pending and now - pending['since_ns'] >= self.VALIDATION_NS:
                self._confirm_release(name, 'validation_timeout')
        if (ticket.source_id != self.source_id or ticket.generation != self.generation
                or ticket.sequence <= self._last_sample):
            self.stats['discarded_samples'] += 1
            self.stats['last_rejected_sample'] = {'sequence': ticket.sequence, 'reason': 'obsolete',
                                                  'observed_ns': now}
            return
        self._last_sample = ticket.sequence
        sample = {'left': bool(left_down), 'right': bool(right_down), 'sequence': ticket.sequence,
                  'started_ns': ticket.started_ns, 'observed_ns': end,
                  'hook_sequences': dict(zip(self.buttons, ticket.hook_sequences)), 'valid': {}}
        self.stats['async_sample'] = sample
        timely = ticket.started_ns <= end <= now and now - ticket.started_ns <= self.MAX_SAMPLE_AGE_NS
        sample['valid'] = {name: timely and sample['hook_sequences'][name] == self.hook_sequences[name]
                           for name in self.buttons}
        for name, down in [('left', bool(left_down)), ('right', bool(right_down))]:
            valid = sample['valid'][name]
            if not valid:
                self._suspend(name, 'sample_interleaved' if timely else 'sample_expired', now)
                continue
            if not self.hook_buttons[name] or self.presses[name] is None:
                continue  # positive polling alone NEVER creates a press
            if not down:
                self._suspend(name, 'async_negative', now)
            pending = self.pending[name]
            if pending is None:
                continue  # coherent held press needs no recovery
            if ticket.started_ns < pending['since_ns']:
                continue  # acquisition predates the divergence; cannot vote
            if pending['last_vote_ns'] is not None and end - pending['last_vote_ns'] < self.VOTE_GAP_NS:
                continue
            pending['last_vote_ns'] = end
            key, other = ('positive', 'negative') if down else ('negative', 'positive')
            pending[key] += 1
            pending[other] = 0
            if pending['negative'] >= 2:
                self._confirm_release(name, 'async_release_confirmed')
            elif pending['positive'] >= 2:
                self.pending[name] = None
                self.stats['recoveries'][name] += 1
                self._transition(name, True, 'revalidated')


class WindowsHooks:
    """Thin native binding. Constructing this object does not install hooks."""

    def __init__(self):
        if os.name != 'nt':
            raise OSError('Entradas globais disponíveis somente no Windows.')
        self.user = C.WinDLL('user32', use_last_error=True)
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.proc = C.WINFUNCTYPE(C.c_ssize_t, C.c_int, C.c_size_t, C.c_ssize_t)
        class Keyboard(C.Structure):
            _fields_ = [('vk', W.DWORD), ('scan', W.DWORD), ('flags', W.DWORD),
                        ('time', W.DWORD), ('extra', C.c_size_t)]
        class Mouse(C.Structure):
            _fields_ = [('point', W.POINT), ('data', W.DWORD), ('flags', W.DWORD),
                        ('time', W.DWORD), ('extra', C.c_size_t)]
        self.Keyboard, self.Mouse = Keyboard, Mouse
        signatures = {
            'SetWindowsHookExW': ([C.c_int, self.proc, W.HINSTANCE, W.DWORD], W.HANDLE),
            'UnhookWindowsHookEx': ([W.HANDLE], W.BOOL),
            'CallNextHookEx': ([W.HANDLE, C.c_int, C.c_size_t, C.c_ssize_t], C.c_ssize_t),
            'MsgWaitForMultipleObjectsEx': ([W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.DWORD], W.DWORD),
            'PeekMessageW': ([C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT], W.BOOL),
            'TranslateMessage': ([C.POINTER(W.MSG)], W.BOOL),
            'DispatchMessageW': ([C.POINTER(W.MSG)], C.c_ssize_t),
            'GetAsyncKeyState': ([C.c_int], C.c_short),
            'GetForegroundWindow': ([], W.HWND),
            'WindowFromPoint': ([W.POINT], W.HWND),
            'GetAncestor': ([W.HWND, W.UINT], W.HWND),
            'GetWindowThreadProcessId': ([W.HWND, C.POINTER(W.DWORD)], W.DWORD),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.user, name); fn.argtypes, fn.restype = args, result
        self.kernel.GetModuleHandleW.argtypes = [W.LPCWSTR]
        self.kernel.GetModuleHandleW.restype = W.HMODULE
        self.handles = []
        self.callbacks = []  # keep callback pointers alive through unhook
        self.error = None

    def _own_window(self):
        pid = W.DWORD()
        self.user.GetWindowThreadProcessId(self.user.GetForegroundWindow(), C.byref(pid))
        return pid.value == os.getpid()

    def _own_click(self, point):
        # Resolve the clicked root, even before it becomes foreground. The
        # coordinate is used transiently, never kept or emitted to the backend.
        root = self.user.GetAncestor(self.user.WindowFromPoint(point), 2)
        pid = W.DWORD()
        self.user.GetWindowThreadProcessId(root, C.byref(pid))
        return pid.value == os.getpid()

    def open(self, reducer):
        def callback(kind, code, message, pointer):
            if code >= 0 and self.error is None:
                try:
                    if kind == 13:
                        data = C.cast(pointer, C.POINTER(self.Keyboard)).contents
                        if data.vk in reducer.KEYS:
                            reducer.keyboard(message, data.vk, data.flags, self._own_window())
                    elif message in reducer.MOUSE:
                        data = C.cast(pointer, C.POINTER(self.Mouse)).contents
                        reducer.mouse(message, data.flags, self._own_click(data.point))
                except Exception as exc:
                    self.error = exc
            return self.user.CallNextHookEx(None, code, message, pointer)
        try:
            for kind in (13, 14):
                proc = self.proc(lambda code, msg, ptr, kind=kind: callback(kind, code, msg, ptr))
                self.callbacks.append(proc)
                handle = self.user.SetWindowsHookExW(kind, proc, self.kernel.GetModuleHandleW(None), 0)
                if not handle:
                    raise C.WinError(C.get_last_error())
                self.handles.append(handle)
        except Exception:
            self.close()
            raise

    def pump(self):
        # A blocking wait, not a polling spin. Bounded timeout permits clean
        # shutdown and conservative release reconciliation after missed events.
        result = self.user.MsgWaitForMultipleObjectsEx(0, None, 20, 0x04FF, 0x0004)
        if result == 0xFFFFFFFF:
            raise C.WinError(C.get_last_error())
        msg = W.MSG()
        for _ in range(256):
            if not self.user.PeekMessageW(C.byref(msg), None, 0, 0, 1):
                break
            if msg.message == 0x12:
                raise RuntimeError('Message pump encerrada inesperadamente.')
            self.user.TranslateMessage(C.byref(msg))
            self.user.DispatchMessageW(C.byref(msg))
        if self.error:
            raise self.error

    def buttons_down(self):
        return tuple(bool(self.user.GetAsyncKeyState(vk) & 0x8000) for vk in (1, 2))

    def emergency_down(self):
        # Independent conservative fallback if Windows silently removes a slow
        # keyboard hook. An injected F12 may also stop; it can never activate.
        return bool(self.user.GetAsyncKeyState(0x7B) & 0x8000)

    def close(self):
        failed = []
        for handle in reversed(self.handles):
            if not self.user.UnhookWindowsHookEx(handle):
                failed.append(handle)
        self.handles = failed
        if failed:
            raise OSError('Não foi possível liberar todos os hooks Windows.')
        self.callbacks.clear()


class GlobalInput:
    def __init__(self, emit, *, api_factory=WindowsHooks, safety_epoch=None):
        self.emit, self.api_factory = emit, api_factory
        self.safety_epoch = safety_epoch
        self._stop, self._ready = Event(), Event()
        self._thread = None
        self.operational = False
        self.error = None
        self._progress = {'phase': 'created', 'observed_ns': monotonic_ns(), 'heartbeat_sequence': 0}

    def _phase(self, phase, *, heartbeat=False):
        # Immutable publication, no runtime lock and no fabricated heartbeat.
        self._progress = {'phase': phase, 'observed_ns': monotonic_ns(),
                          'heartbeat_sequence': self._progress['heartbeat_sequence'] + int(heartbeat)}

    def start(self):
        if self._thread is not None:
            raise RuntimeError('Listener de uso único.')
        self._thread = Thread(target=self._run, name='R6-global-input', daemon=True)
        self._thread.start()
        if not self._ready.wait(2):
            self.close()
            raise TimeoutError('Inicialização das entradas globais excedeu 2 segundos.')
        if self.error:
            raise RuntimeError(self.error)

    def _run(self):
        api = reducer = None
        try:
            self._phase('opening')
            api = self.api_factory()
            reducer = InputReducer(self.emit, safety_epoch=self.safety_epoch)
            api.open(reducer)
            self.operational = True
            self._phase('publish', heartbeat=True)
            self.emit(InputEvent('health', True, monotonic_ns()))
            self._ready.set()
            while not self._stop.is_set():
                self._phase('pump')
                api.pump()
                self._phase('sample_ticket')
                ticket = reducer.begin_sample()
                self._phase('windows_sample')
                buttons = api.buttons_down()
                self._phase('reconcile')
                reducer.reconcile(*buttons, ticket=ticket)
                self._phase('emergency_check')
                if hasattr(api, 'emergency_down'):
                    reducer.keyboard(0x100 if api.emergency_down() else 0x101, 0x7B)
                self._phase('publish', heartbeat=True)
                self.emit(InputEvent('health', True, monotonic_ns(), diagnostics=reducer.diagnostics()))
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'
        finally:
            self.operational = False
            self._phase('closing')
            try:
                if reducer:
                    reducer.invalidate('listener_failure' if self.error else 'listener_shutdown')
            except Exception as exc:
                self.error = f'{type(exc).__name__}: {exc}'
            try:
                if api:
                    api.close()
            except Exception as exc:
                self.error = f'{type(exc).__name__}: {exc}'
            try:
                self.emit(InputEvent('health', False, monotonic_ns()))
            finally:
                self._phase('stopped')
                self._ready.set()

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(2)
            if self._thread.is_alive():
                raise TimeoutError('Listener global não encerrou.')

    def snapshot(self):
        return {'operational': self.operational, 'error': self.error,
                'progress': dict(self._progress),
                'running': bool(self._thread and self._thread.is_alive())}
