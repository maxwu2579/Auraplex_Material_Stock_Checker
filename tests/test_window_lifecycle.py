"""Close/late-worker regressions: a worker must not own the last reference to Tk variables."""
import gc
import sys
import threading
import time
import weakref
from unittest.mock import patch

from checker import history, alerts
from tests.test_m31 import UiBase


class ClosedWindowLifetimeTests(UiBase):
    def setUp(self):
        gc.collect()
        super().setUp()
        self.start_app(); self.select_files()

    def tearDown(self):
        try:
            super().tearDown()
        finally:
            self.apps.clear(); self.app = self.root = None
            gc.collect()

    def pump(self, ready):
        end = time.monotonic()+5
        while time.monotonic()<end:
            self.root.update()
            if ready(): return
            time.sleep(.005)
        self.fail('window did not settle')

    def collect_worker(self):
        thread = threading.Thread(target=gc.collect, name='audit-collector')
        thread.start(); thread.join(10)
        self.assertFalse(thread.is_alive())

    def test_closed_history_has_no_tk_finalizers_on_a_background_collector(self):
        self.app.open_history()
        window = self.app.history_window
        self.pump(lambda: not window.lanes['sheets'].active)
        caught, original = [], sys.unraisablehook
        enabled = gc.isenabled(); gc.disable()
        sys.unraisablehook = lambda event: caught.append((threading.current_thread().name, str(event.exc_value)))
        try:
            ref = weakref.ref(window)
            window.close(); del window
            self.collect_worker()
            self.assertIsNone(ref())
            self.assertEqual(caught, [])
        finally:
            sys.unraisablehook = original
            if enabled: gc.enable()
            gc.collect()

    def test_running_history_and_alert_reads_do_not_retain_closed_windows(self):
        for kind in ('history', 'alerts'):
            entered, release = threading.Event(), threading.Event()
            module, name = (history, 'material_history') if kind == 'history' else (alerts, 'load_state')
            real = getattr(module, name)
            expected = 'm4a-history-query' if kind == 'history' else 'm32c-alerts-alerts'
            def held(*args, **kwargs):
                if threading.current_thread().name == expected:
                    entered.set(); release.wait(10)
                return real(*args, **kwargs)
            caught, original = [], sys.unraisablehook
            enabled = gc.isenabled(); gc.disable()
            sys.unraisablehook = lambda event: caught.append((threading.current_thread().name, str(event.exc_value)))
            try:
                with patch.object(module, name, side_effect=held):
                    if kind == 'history':
                        self.app.open_history(); window = self.app.history_window
                        self.pump(lambda: not window.lanes['sheets'].active)
                        window.select('A')
                    else:
                        self.app.open_alerts(); window = self.app.alerts_window
                    self.assertTrue(entered.wait(5))
                    ref = weakref.ref(window)
                    window.close(); del window
                    self.collect_worker()
                    self.assertIsNone(ref(), f'{kind}: a running read retained the closed Tk window')
                    release.set()
                    deadline = time.monotonic()+5
                    while any(t.name == expected for t in threading.enumerate()) and time.monotonic()<deadline:
                        time.sleep(.005)
                    self.assertFalse(any(t.name == expected for t in threading.enumerate()))
                    self.collect_worker()
                    self.assertEqual(caught, [])
            finally:
                release.set()
                sys.unraisablehook = original
                if enabled: gc.enable()
                gc.collect()

    def test_closed_analytics_and_daily_windows_release_their_variable_callbacks(self):
        for kind, open_window, attr in (('analytics', self.app.open_analytics, 'analytics_window'),
                                        ('daily', self.app.open_daily, 'daily_window')):
            open_window(); window = getattr(self.app, attr)
            caught, original = [], sys.unraisablehook
            enabled = gc.isenabled(); gc.disable()
            sys.unraisablehook = lambda event: caught.append((threading.current_thread().name, str(event.exc_value)))
            try:
                ref = weakref.ref(window)
                window.close(); del window
                self.collect_worker()
                self.assertIsNone(ref(), f'{kind}: destroyed window remains owned by a variable callback')
                self.assertEqual(caught, [])
            finally:
                sys.unraisablehook = original
                if enabled: gc.enable()
                gc.collect()
