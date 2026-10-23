"""Alerts-window localisation; synthetic workbooks and temporary SQLite only."""
import gc
import hashlib
import sqlite3
import threading
from string import Formatter
from unittest.mock import patch

from checker import alerts, alerts_i18n
from tests.test_m32c_remediation import SessionUiBase


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AlertsLanguageTests(SessionUiBase):
    def setUp(self):
        gc.collect()  # dispose previous test's destroyed Tk roots on the Tk thread before workers start
        super().setUp()
        self.callback_errors = []
        self.current_session()
        self.root.report_callback_exception = lambda *error: self.callback_errors.append(error)
        self.app.open_alerts()
        self.window = self.app.alerts_window
        self.pump(lambda: self.window.state is not None and self.window.changes is not None
                  and not any(self.window.loading.values()))

    def tearDown(self):
        try:
            self.assertEqual(self.callback_errors, [])
        finally:
            super().tearDown()
            self.apps.clear()
            self.window = self.app = self.root = None
            gc.collect()  # do not leave destroyed Tk-variable cycles for a later worker's garbage collection

    def test_switch_preserves_rows_filters_selection_authorization_and_never_reads(self):
        w = self.window
        w.material_filter.set('a'); w.type_filter.set('LOW_STOCK'); w._apply_filters()
        w.tree.selection_set('0'); w._show_row('alerts')
        state, changes = w.state, w.changes
        before = (dict(w.visible), dict(w.shown), w.tree.selection(), w.tree.item('0', 'values'),
                  w.details.get('1.0', 'end'), w.material_filter.get(), w.type_filter.get(),
                  self.app.alert_authorization(), self.app.alert_gate.generation, self.app.result)
        hashes = tuple(digest(p) for p in (self.db, self.stock, self.bom))
        with patch.object(alerts, 'load_state', side_effect=AssertionError('language read alerts')), \
             patch.object(alerts, 'observed_changes_view', side_effect=AssertionError('language read changes')), \
             patch.object(self.app, 'request_alerts', side_effect=AssertionError('language evaluated')):
            for lang, title, button in (('zh', '库存提醒', '重新评估'), ('ms', 'Amaran stok', 'Nilai semula'), ('en', 'Stock Alerts', 'Re-evaluate')):
                self.app.set_language(lang); self.root.update()
                self.assertIn(title, w.top.title())
                self.assertEqual(w.evaluate_button.cget('text'), button)
                self.assertIn('Cloud Not Verified', w.banner.cget('text'))
                self.assertIs(w.state, state); self.assertIs(w.changes, changes)
                self.assertEqual(w.sheet_combo.current(), 0)
                after = (dict(w.visible), dict(w.shown), w.tree.selection(), w.tree.item('0', 'values'),
                         w.details.get('1.0', 'end'), w.material_filter.get(), w.type_filter.get(),
                         self.app.alert_authorization(), self.app.alert_gate.generation, self.app.result)
                self.assertEqual(before, after)
        self.assertEqual(hashes, tuple(digest(p) for p in (self.db, self.stock, self.bom)))
        w.type_combo.current(0); w.change_combo.current(0)
        self.app.set_language('zh')
        w._apply_filters()
        self.assertEqual(len(w.visible['alerts']), 2)
        w.sheet_combo.configure(values=(w.text(alerts_i18n.message('All Sheets')), 'Stock', '原始 Sheet'))
        w.sheet_combo.current(2)
        self.app.set_language('ms')
        self.assertEqual(w.sheet_filter.get(), '原始 Sheet')
        w._apply_filters()
        self.assertEqual(w.visible['alerts'], ())

    def test_read_failure_remains_failed_and_cannot_resurrect_counts(self):
        w = self.window
        with patch.object(alerts, 'load_state', side_effect=sqlite3.OperationalError('RAW Sheet-A locked')):
            w.reload('alerts')
            self.pump(lambda: not w.loading['alerts'] and w.state is None)
        generation = self.app.alert_gate.generation
        for lang, failed in (('zh', '读取失败'), ('ms', 'Bacaan gagal'), ('en', 'Read failed')):
            self.app.set_language(lang); self.root.update()
            self.assertIn(failed, w.status.get())
            self.assertIn('DATABASE READ FAILED', w.session.cget('text'))
            self.assertIn('NOT RE-CHECKED', w.session.cget('text'))
            self.assertIn('RAW Sheet-A locked', w.basis.get('1.0', 'end'))
            self.assertIsNone(w.state)
            self.assertEqual(w.tree.get_children(), ())
            self.assertEqual(w.count_labels['alerts'].cget('text'), '')
            self.assertFalse(self.app.alert_current)
            self.assertIsNone(self.app.alert_authorization())
            self.assertEqual(generation, self.app.alert_gate.generation)
        with patch.object(alerts, 'observed_changes_view', side_effect=sqlite3.OperationalError('RAW changes failed')):
            w.reload('changes')
            self.pump(lambda: not w.loading['changes'])
        self.app.set_language('zh')
        self.assertIn('无法读取观察变化', w.count_labels['changes'].cget('text'))
        self.assertIn('RAW changes failed', w.count_labels['changes'].cget('text'))

    def test_held_read_completes_in_new_language_and_reopen_uses_it(self):
        w = self.window
        entered, release = threading.Event(), threading.Event()
        real = alerts.load_state
        def held(*args, **kwargs):
            result = real(*args, **kwargs)
            entered.set(); release.wait(10)
            return result
        try:
            with patch.object(alerts, 'load_state', side_effect=held) as read:
                w.reload('alerts')
                self.assertTrue(entered.wait(5))
                self.app.set_language('ms')
                self.assertEqual(read.call_count, 1)
                release.set()
                self.pump(lambda: not w.loading['alerts'])
                self.assertIn('amaran aktif', w.status.get())
                self.assertEqual(read.call_count, 1)
        finally:
            release.set()
        w.close()
        self.app.open_alerts()
        self.window = self.app.alerts_window
        self.pump(lambda: not any(self.window.loading.values()))
        self.assertIn('Amaran stok', self.window.top.title())
        self.assertEqual(self.window.evaluate_button.cget('text'), 'Nilai semula')

    def test_compact_three_language_geometry_with_font_scaling(self):
        for scale in (1, 1.5):
            self.window.close()
            gc.collect()
            self.root.tk.call('tk', 'scaling', 96 / 72 * scale)
            self.app.open_alerts()
            self.window = w = self.app.alerts_window
            self.pump(lambda: w.state is not None and w.changes is not None and not any(w.loading.values()))
            w.top.geometry('960x600')
            for lang in ('en', 'zh', 'ms'):
                with self.subTest(scale=scale, language=lang):
                    self.app.set_language(lang)
                    for _ in range(4): w.top.update()
                    for widget in (w.banner, w.session, w.sheet_combo, w.material_entry, w.evaluate_button):
                        self.assertTrue(widget.winfo_ismapped())
                        self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), w.top.winfo_rootx()+w.top.winfo_width())
                        self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), w.top.winfo_rooty()+w.top.winfo_height())
                    self.assertGreater(w.tree.winfo_height(), 60)

    def test_translation_parameters_match(self):
        fields = lambda text: sorted(field for _, field, _, _ in Formatter().parse(text) if field is not None)
        for english, translated in alerts_i18n.TEXT.items():
            for text in translated:
                self.assertEqual(fields(english), fields(text), english)
