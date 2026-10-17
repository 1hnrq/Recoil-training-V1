"""Interruptible blocking waits. Windows uses a private high-resolution timer.

Only kernel32 synchronization APIs: no user32/input APIs, priority changes or
global timer-resolution changes. Handles are unnamed and non-inheritable.
"""

import os
from threading import Event


class PortableWaiter:
    name = 'threading.Event (portable; OS-dependent precision)'

    def __init__(self):
        self._event = Event()

    def wake(self):
        self._event.set()

    def wait(self, timeout_ns: int | None):
        self._event.wait(None if timeout_ns is None else min(timeout_ns, 60_000_000_000) / 1e9)
        # Always re-read state after this clear. A command before the clear is
        # observed in that read; a command after it keeps the event signaled.
        self._event.clear()

    def close(self):
        pass


class WindowsHighResolutionWaiter:
    name = 'Windows high-resolution waitable timer + interrupt event'

    def __init__(self):
        import ctypes
        from ctypes import wintypes as w
        self._ctypes = ctypes
        self._kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        k = self._kernel
        k.CreateWaitableTimerExW.argtypes = [ctypes.c_void_p, w.LPCWSTR, w.DWORD, w.DWORD]
        k.CreateWaitableTimerExW.restype = w.HANDLE
        k.CreateEventW.argtypes = [ctypes.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR]
        k.CreateEventW.restype = w.HANDLE
        k.SetEvent.argtypes = [w.HANDLE]
        k.SetEvent.restype = w.BOOL
        k.SetWaitableTimer.argtypes = [w.HANDLE, ctypes.POINTER(ctypes.c_longlong), w.LONG,
                                       ctypes.c_void_p, ctypes.c_void_p, w.BOOL]
        k.SetWaitableTimer.restype = w.BOOL
        k.CancelWaitableTimer.argtypes = [w.HANDLE]
        k.CancelWaitableTimer.restype = w.BOOL
        k.WaitForMultipleObjects.argtypes = [w.DWORD, ctypes.POINTER(w.HANDLE), w.BOOL, w.DWORD]
        k.WaitForMultipleObjects.restype = w.DWORD
        k.CloseHandle.argtypes = [w.HANDLE]
        k.CloseHandle.restype = w.BOOL
        self._closed = False
        # CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, SYNCHRONIZE | TIMER_MODIFY_STATE.
        self._timer = k.CreateWaitableTimerExW(None, None, 0x2, 0x00100002)
        if not self._timer:
            raise ctypes.WinError(ctypes.get_last_error())
        self._event = k.CreateEventW(None, False, False, None)  # auto reset
        if not self._event:
            error = ctypes.get_last_error()
            k.CloseHandle(self._timer)
            raise ctypes.WinError(error)
        # Interrupt goes first, so it wins if both event and timer are signaled.
        self._handles = (w.HANDLE * 2)(self._event, self._timer)

    def wake(self):
        if self._closed:
            raise RuntimeError('waiter is closed')
        if not self._kernel.SetEvent(self._event):
            raise self._ctypes.WinError(self._ctypes.get_last_error())

    def wait(self, timeout_ns: int | None):
        if self._closed:
            raise RuntimeError('waiter is closed')
        count = 1
        if timeout_ns is not None:
            # Negative due time = relative 100 ns units; one-shot, no APC/resume.
            units = max(1, (min(timeout_ns, 60_000_000_000) + 99) // 100)
            due = self._ctypes.c_longlong(-units)
            if not self._kernel.SetWaitableTimer(self._timer, self._ctypes.byref(due),
                                                 0, None, None, False):
                raise self._ctypes.WinError(self._ctypes.get_last_error())
            count = 2
        result = self._kernel.WaitForMultipleObjects(count, self._handles, False, 0xFFFFFFFF)
        if result == 0xFFFFFFFF:
            raise self._ctypes.WinError(self._ctypes.get_last_error())
        if result not in range(count):
            raise OSError(f'unexpected wait status: {result}')

    def close(self):
        # Called only after joining the worker: never close a handle being waited on.
        if not self._closed:
            self._kernel.CancelWaitableTimer(self._timer)
            self._kernel.CloseHandle(self._timer)
            self._kernel.CloseHandle(self._event)
            self._closed = True


def make_waiter():
    # On Windows fail explicitly if high-resolution timer creation is unsupported;
    # do not silently fall back to coarse waits and claim millisecond precision.
    return WindowsHighResolutionWaiter() if os.name == 'nt' else PortableWaiter()
