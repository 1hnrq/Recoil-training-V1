from pathlib import Path
import sys
from threading import Event
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from r6_rebuild.global_input import GlobalInput, InputReducer


class InputTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.r = InputReducer(self.events.append)

    def test_release_shortcuts_no_repeats(self):
        for vk, name in ((0x50, 'pause'), (0x31, 'primary'), (0x32, 'secondary')):
            self.r.keyboard(0x100, vk); self.r.keyboard(0x100, vk)
            self.r.keyboard(0x101, vk); self.r.keyboard(0x101, vk)
        self.assertEqual([e.value for e in self.events], ['pause', 'primary', 'secondary'])

    def test_f12_immediate_once_even_held(self):
        self.r.keyboard(0x100, 0x7B)
        self.assertEqual(self.events[0].kind, 'emergency')
        self.r.keyboard(0x100, 0x7B); self.r.keyboard(0x101, 0x7B)
        self.assertEqual(len(self.events), 1)

    def test_unrelated_keys_and_injected_events_not_retained(self):
        for vk in range(256):
            self.r.keyboard(0x100, vk, 0x10)
        for vk in (0x41, 0x42, 0x43): self.r.keyboard(0x100, vk)
        self.r.mouse(0x201, 1); self.r.mouse(0x204, 2); self.r.mouse(0x200)
        self.assertFalse(self.events); self.assertFalse(self.r.held)
        self.assertEqual(self.r.buttons, {'left': False, 'right': False})

    def test_both_physical_buttons_and_release(self):
        for msg in (0x201, 0x204, 0x201, 0x202): self.r.mouse(msg)
        self.assertEqual(len(self.events), 3)
        self.assertEqual(self.events[1].value, {'left': True, 'right': True})
        self.assertEqual(self.events[-1].value, {'left': False, 'right': True})

    def test_no_game_focus_or_minimized_dependency(self):
        # No target/focus/minimized argument exists. The own-window bit only
        # identifies an explicit interaction with our own controls for safety.
        for own in (False, True):
            self.r.keyboard(0x100, 0x31, own_window=own)
            self.r.keyboard(0x101, 0x31, own_window=own)
        self.assertEqual([e.value for e in self.events], ['primary', 'primary'])

    def test_reconcile_only_releases_never_creates_press(self):
        self.r.reconcile(True, True); self.assertFalse(self.events)
        self.r.mouse(0x201); self.r.mouse(0x204)
        self.r.reconcile(False, False)
        self.assertEqual(self.events[-1].value, {'left': False, 'right': False})

    def test_start_stop_releases_native_resources(self):
        events = []; closed = Event()
        class API:
            def open(self, reducer): self.reducer = reducer
            def pump(self): closed.wait(.005)
            def buttons_down(self): return False, False
            def close(self): closed.set()
        source = GlobalInput(events.append, api_factory=API)
        source.start(); self.assertTrue(source.operational)
        source.close(); source.close()
        self.assertTrue(closed.is_set()); self.assertFalse(source.snapshot()['running'])
        self.assertFalse(events[-1].value)

    def test_install_failure_fails_closed_and_cleans(self):
        closed = []
        class API:
            def open(self, reducer): raise OSError('mock denied')
            def close(self): closed.append(True)
        source = GlobalInput(self.events.append, api_factory=API)
        with self.assertRaises(RuntimeError): source.start()
        source.close(); self.assertEqual(closed, [True])
        self.assertFalse(source.operational)

    def test_pump_failure_notifies_unhealthy(self):
        failed = Event()
        class API:
            def open(self, reducer): pass
            def pump(self): failed.wait(.03); raise OSError('mock pump failure')
            def close(self): pass
        source = GlobalInput(self.events.append, api_factory=API)
        source.start(); failed.set(); source.close()
        self.assertIn('mock pump failure', source.error)
        self.assertFalse(self.events[-1].value)

    def test_f12_fallback_without_keyboard_hook_event(self):
        seen = Event()
        def emit(e):
            self.events.append(e)
            if e.kind == 'emergency': seen.set()
        class API:
            def open(self, reducer): pass
            def pump(self): Event().wait(.005)
            def buttons_down(self): return False, False
            def emergency_down(self): return True
            def close(self): pass
        source = GlobalInput(emit, api_factory=API)
        try:
            source.start(); self.assertTrue(seen.wait(.5))
        finally: source.close()
        self.assertEqual(sum(e.kind == 'emergency' for e in self.events), 1)


if __name__ == '__main__': unittest.main()
