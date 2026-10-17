"""Relative Windows output, independent of profiles, math and scheduling.

Import/construction never moves the pointer. Only an explicitly armed gate can
reach move(). Tests must supply a fake send_input callable, never the real API.
"""

import ctypes as C
from contextlib import contextmanager
from copy import deepcopy
import os
from threading import Event, Lock
from time import monotonic_ns


class MOUSEINPUT(C.Structure):
    _fields_ = [('dx', C.c_int32), ('dy', C.c_int32), ('mouseData', C.c_uint32),
                ('dwFlags', C.c_uint32), ('time', C.c_uint32), ('dwExtraInfo', C.c_size_t)]


class KEYBDINPUT(C.Structure):
    _fields_ = [('wVk', C.c_uint16), ('wScan', C.c_uint16), ('dwFlags', C.c_uint32),
                ('time', C.c_uint32), ('dwExtraInfo', C.c_size_t)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [('uMsg', C.c_uint32), ('wParamL', C.c_uint16), ('wParamH', C.c_uint16)]


class _Payload(C.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ('payload',)
    _fields_ = [('type', C.c_uint32), ('payload', _Payload)]


class WindowsMouseSink:
    def __init__(self, *, send_input=None):
        self._send_input = send_input
        self.error = None
        self.calls = 0
        self.last_call = None
        self._native = send_input is None
        if send_input is None:
            if os.name != 'nt':
                raise OSError('Saída real disponível somente no Windows.')
            self._user = C.WinDLL('user32', use_last_error=True)
            self._send_input = self._user.SendInput
            self._send_input.argtypes = [C.c_uint32, C.POINTER(INPUT), C.c_int]
            self._send_input.restype = C.c_uint32

    @property
    def operational(self):
        return self.error is None

    def move(self, dx, dy):
        if not self.operational:
            raise RuntimeError(self.error)
        for value in (dx, dy):
            if type(value) is not int or not -(2**31) <= value < 2**31:
                raise ValueError('Deslocamento deve ser inteiro LONG de 32 bits.')
        if dx == 0 and dy == 0:
            return False
        packet = INPUT(type=0, mi=MOUSEINPUT(dx=dx, dy=dy, dwFlags=0x0001))
        start = monotonic_ns()
        result = error_code = failure = None
        self.last_call = {'started_ns': start, 'finished_ns': None, 'duration_ns': None,
                          'return_value': None, 'winerror': None, 'error': None,
                          'native': self._native}
        try:
            # One relative movement; never clicks, absolute positioning, retries
            # or catch-up batches. Windows acceleration can affect pixel distance.
            if self._native:
                C.set_last_error(0)
            result = self._send_input(1, C.byref(packet), C.sizeof(INPUT))
            if self._native:
                error_code = C.get_last_error()
            if result != 1:
                raise OSError('SendInput não aceitou o movimento (possível UIPI); saída desativada.')
            self.calls += 1
            return True
        except Exception as exc:
            failure = f'{type(exc).__name__}: {exc}'
            raise
        finally:
            end = monotonic_ns()
            self.last_call = {'started_ns': start, 'finished_ns': end, 'duration_ns': end - start,
                              'return_value': result, 'winerror': error_code, 'error': failure,
                              'native': self._native}
            # Publish the complete native record before making a fault visible
            # to the watchdog; its frozen evidence must include this call.
            if failure is not None:
                self.error = failure


class OutputGate:
    """One synchronous sender, zero queue; control never waits for native I/O.

    Admission under the short control lock is the handoff to the adapter. Stop
    invalidates every not-yet-admitted ticket, not the one already in flight.
    No gate lock is held while calling the adapter or any runtime callback.
    """

    def __init__(self, sink=None):
        self.sink = sink
        self._blocked = Event(); self._blocked.set()
        self._lock = Lock()
        self.epoch = 0
        self._version = 0
        self._in_flight = None
        self._serial = 0
        self._rejected = 0
        self._last_dispatch = None
        self._lock_wait = {'last_ns': 0, 'max_ns': 0}
        self.last_stop_ns = None

    @contextmanager
    def _control(self):
        start = monotonic_ns()
        with self._lock:
            elapsed = monotonic_ns() - start
            self._lock_wait = {'last_ns': elapsed, 'max_ns': max(elapsed, self._lock_wait['max_ns'])}
            yield

    def ticket(self):
        with self._control():
            return self.epoch, self._version

    def invalidate(self):
        """Invalidate prepared work without changing explicit Real authorization."""
        with self._control():
            self._version += 1

    @property
    def operational(self):
        return self.sink is not None and self.sink.operational

    def arm(self, epoch):
        with self._control():
            if self._in_flight is not None or epoch != self.epoch or not self.operational:
                raise RuntimeError('Autorização de modo expirada ou saída indisponível.')
            self._version += 1
            self._blocked.clear()

    def block(self):
        start = monotonic_ns()
        with self._control():
            self._blocked.set()
            self.epoch += 1
            self._version += 1
            self.last_stop_ns = monotonic_ns() - start
        return self.last_stop_ns

    def move(self, dx, dy):
        return self.dispatch(dx, dy, self.ticket())['accepted']

    def dispatch(self, dx, dy, ticket, *, valid_until_ns=None):
        with self._control():
            now = monotonic_ns()
            reason = ('blocked' if self._blocked.is_set() else
                      'obsolete' if ticket != (self.epoch, self._version) else
                      'in_flight' if self._in_flight is not None else
                      'heartbeat_expired' if valid_until_ns is not None and now > valid_until_ns else None)
            if reason:
                self._rejected += 1
                return {'admitted': False, 'accepted': False, 'reason': reason}
            self._serial += 1
            call = {'id': self._serial, 'ticket': ticket, 'started_ns': now, 'dx': dx, 'dy': dy}
            self._in_flight = call
        accepted, error = False, None
        try:
            accepted = bool(self.sink.move(dx, dy))
            return {'admitted': True, 'accepted': accepted, 'id': call['id']}
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'
            raise
        finally:
            end = monotonic_ns()
            with self._control():
                self._last_dispatch = {**call, 'finished_ns': end, 'duration_ns': end - now,
                                       'accepted': accepted, 'error': error}
                self._in_flight = None

    def snapshot(self):
        with self._control():
            return {'operational': self.operational, 'blocked': self._blocked.is_set(),
                    'test_only': bool(getattr(self.sink, 'test_only', False)),
                    'epoch': self.epoch, 'version': self._version, 'last_stop_ns': self.last_stop_ns,
                    'calls': self.sink.calls if self.sink is not None else 0,
                    'error': self.sink.error if self.sink is not None else None,
                    'in_flight': deepcopy(self._in_flight), 'last_dispatch': deepcopy(self._last_dispatch),
                    'last_api_call': deepcopy(getattr(self.sink, 'last_call', None)),
                    'rejected': self._rejected, 'lock_wait': dict(self._lock_wait), 'queued': 0}


class DiscardingMouseSink:
    """Native GUI QA only: deliberately has no Windows API binding."""
    test_only = True
    operational = True
    error = None

    def __init__(self):
        self.calls = 0

    def move(self, dx, dy):
        if any(type(v) is not int or not -(2**31) <= v < 2**31 for v in (dx, dy)):
            raise ValueError('Deslocamento inválido.')
        if dx or dy:
            self.calls += 1
            return True
        return False
