"""Prevent repeated rendering hints and reentrant native event feedback."""
import unittest
from core.render_lifecycle import RenderState


class RenderStateTests(unittest.TestCase):
    def test_normal_window_is_visible(self):
        events = []
        self.assertTrue(RenderState().update(True, False, lambda *s: events.append(s)))
        self.assertEqual(events, [(True, 'visible')])

    def test_hidden_and_minimized_states(self):
        for shown, minimized, reason in [(False, False, 'tray'), (False, True, 'tray'), (True, True, 'minimized')]:
            with self.subTest(shown=shown, minimized=minimized):
                events = []
                RenderState().update(shown, minimized, lambda *s: events.append(s))
                self.assertEqual(events, [(False, reason)])

    def test_repeated_resize_does_not_republish(self):
        gate, events = RenderState(), []
        for _ in range(300):
            gate.update(True, False, lambda *s: events.append(s))
        self.assertEqual(events, [(True, 'visible')])

    def test_minimize_tray_and_restore_sequences(self):
        gate, events = RenderState(), []
        for shown, minimized in [(True, False), (True, True), (True, False), (False, False), (True, False)]:
            gate.update(shown, minimized, lambda *s: events.append(s))
        self.assertEqual(events, [(True, 'visible'), (False, 'minimized'), (True, 'visible'), (False, 'tray'), (True, 'visible')])

    def test_reentrant_callback_cannot_start_visibility_loop(self):
        gate, events = RenderState(), []
        def publish(*state):
            events.append(state)
            gate.update(True, False, publish)
        gate.update(True, False, publish)
        self.assertEqual(events, [(True, 'visible')])

    def test_failed_publication_can_retry(self):
        gate, events = RenderState(), []
        def broken(*_):
            raise RuntimeError('Synthetic renderer not ready')
        self.assertFalse(gate.update(True, False, broken))
        self.assertIsNone(gate.last)
        self.assertTrue(gate.update(True, False, lambda *s: events.append(s)))
        self.assertEqual(events, [(True, 'visible')])

    def test_reload_republishes_once(self):
        gate, events = RenderState(), []
        for force in [False, True, False]:
            gate.update(True, False, lambda *s: events.append(s), force=force)
        self.assertEqual(events, [(True, 'visible'), (True, 'visible')])
