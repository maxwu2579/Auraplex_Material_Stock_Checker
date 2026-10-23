"""Focused Analytics/Daily window languages; synthetic data and temporary folders only."""
import gc
import hashlib
import json
import sqlite3
import threading
from datetime import date, timedelta
from pathlib import Path
from string import Formatter
from unittest.mock import patch

from checker import analytics, daily, daily_preview, analysis_daily_i18n, i18n
from tests.test_m32c_remediation import SessionUiBase


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SecondaryLanguageTests(SessionUiBase):
    def setUp(self):
        gc.collect()
        super().setUp()
        self.current_session()
        self.callback_errors = []
        self.root.report_callback_exception = lambda *error: self.callback_errors.append(error)

    def tearDown(self):
        try:
            self.assertEqual(self.callback_errors, [])
        finally:
            super().tearDown()
            self.apps.clear()
            self.app = self.root = None
            gc.collect()

    def analysis(self):
        self.app.open_analytics()
        w = self.app.analytics_window
        w.query()
        self.pump(lambda: w.result is not None and not w.runner.busy)
        return w

    def summary(self):
        self.app.open_daily()
        w = self.app.daily_window
        w.generate()
        self.pump(lambda: w.summary is not None and not w.runner.busy)
        return w

    def test_analysis_language_is_display_only_and_keeps_unknown_values(self):
        w = self.analysis()
        w.tree.selection_set('0'); w._selected()
        result = w.result
        options = tuple(v.get() for v in (w.days, w.material_text, w.sheet, w.minimum_days, w.low_movement, w.percent))
        generation, shown, selected = w.generation, w.shown, w.tree.selection()
        auth = self.app.alert_authorization()
        hashes = tuple(digest(p) for p in (self.db, self.stock, self.bom))
        with patch.object(analytics, 'analyze', side_effect=AssertionError('language queried')):
            for lang, heading, unknown in (('zh', '库存分析', '未知'), ('ms', 'Analisis inventori', 'tidak diketahui'), ('en', 'Inventory Analytics', 'unknown')):
                self.app.set_language(lang); self.root.update()
                self.assertIn(heading, w.top.title())
                self.assertIn('Cloud Not Verified', w.banner.cget('text'))
                self.assertIs(w.result, result)
                self.assertEqual((w.generation, w.shown, w.tree.selection()), (generation, shown, selected))
                self.assertEqual(options, tuple(v.get() for v in (w.days, w.material_text, w.sheet, w.minimum_days, w.low_movement, w.percent)))
                for item in w.tree.get_children():
                    row = result.materials[int(item)]
                    if row.net_change is None:
                        self.assertEqual(w.tree.item(item, 'values')[8], unknown)
                self.assertEqual(self.app.alert_authorization(), auth)
        self.assertEqual(hashes, tuple(digest(p) for p in (self.db, self.stock, self.bom)))

    def test_analysis_stop_failure_and_pending_language_do_not_restore_results(self):
        self.app.open_analytics(); w = self.app.analytics_window
        entered, release = threading.Event(), threading.Event()
        real = analytics.analyze
        def held(*args, **kwargs):
            entered.set(); release.wait(10)
            return real(*args, **kwargs)
        try:
            with patch.object(analytics, 'analyze', side_effect=held):
                w.query(); self.assertTrue(entered.wait(5))
                generation, started = w.generation, w.runner.threads_started
                self.app.set_language('zh')
                self.assertIn('分析中', w.status.get())
                self.assertEqual((generation, started), (w.generation, w.runner.threads_started))
                w.stop(); release.set()
                self.pump(lambda: not w.runner.busy)
                self.root.update()
            self.app.set_language('ms')
            self.assertIn('Dibatalkan', w.status.get())
            self.assertIsNone(w.result)
            with patch.object(analytics, 'analyze', side_effect=analytics.HistoryReadError('RAW analytical failure')):
                w.query()
                self.pump(lambda: 'QUERY FAILED' in w.status.get())
            self.app.set_language('zh')
            self.assertIn('QUERY FAILED', w.status.get())
            self.assertIn('RAW analytical failure', w.coverage.get('1.0', 'end'))
            self.assertEqual(w.tree.get_children(), ())
        finally:
            release.set()

    def test_daily_preview_language_does_not_change_summary_authorization_or_saved_bytes(self):
        w = self.summary()
        summary = w.summary
        original_json, original_html = summary.json_text, daily.render_html(summary)
        auth, generation = self.app.alert_authorization(), self.app.alert_gate.generation
        request_id = w.request_id
        with patch.object(daily, 'generate', side_effect=AssertionError('language generated')):
            for lang, section in (('zh', '1. 数据来源'), ('ms', '1. SUMBER'), ('en', '1. SOURCES')):
                self.app.set_language(lang); self.root.update()
                self.assertIn(section, w.preview.get('1.0', 'end'))
                self.assertIn('Cloud Not Verified', w.preview.get('1.0', 'end'))
                self.assertIn(summary.report_id, w.preview.get('1.0', 'end'))
                self.assertIs(w.summary, summary)
                self.assertEqual(summary.json_text, original_json)
                self.assertEqual((auth, generation, request_id), (self.app.alert_authorization(), self.app.alert_gate.generation, w.request_id))
                self.assertTrue(w.can_save())
        self.assertEqual(daily_preview.render(summary, 'en'), daily.render_text(summary))
        output = self.base / 'reports'; output.mkdir()
        entered, release = threading.Event(), threading.Event()
        def staged(stage):
            if stage == 'staged':
                entered.set(); release.wait(10)
        try:
            with patch('checker.daily_ui.filedialog.askdirectory', return_value=str(output)), patch.object(daily, '_checkpoint', side_effect=staged):
                w.save(); self.assertTrue(entered.wait(5))
                saving = w.saving
                self.app.set_language('ms')
                self.assertEqual(w.saving, saving)
                self.assertIn('Menyimpan', w.status.get())
                release.set()
                self.pump(lambda: w.saved is not None and w.saving is None)
            self.assertEqual(w.saved.html.read_text(encoding='utf-8'), original_html)
            self.assertEqual(json.loads(w.saved.json.read_text(encoding='utf-8')), json.loads(original_json))
            self.assertIn('Folder laporan disimpan', w.status.get())
        finally:
            release.set()

    def test_daily_unverified_confirmation_is_default_no_in_all_languages(self):
        self.app.open_daily(); w = self.app.daily_window
        w.date_text.set((date.today() - timedelta(days=1)).isoformat())
        for lang, title in (('zh', '生成 UNVERIFIED'), ('ms', 'Jana ringkasan UNVERIFIED'), ('en', 'Generate UNVERIFIED')):
            self.app.set_language(lang)
            with patch('checker.daily_ui.messagebox.askyesno', return_value=False) as ask:
                w.generate()
            self.assertIn(title, ask.call_args.args[0])
            self.assertEqual(ask.call_args.kwargs['default'], 'no')
            self.assertEqual(w.runner.threads_started, 0)
            self.assertIsNone(w.summary)
        self.app.set_language('zh')
        with patch('checker.daily_ui.messagebox.askyesno', return_value=True):
            w.generate(); self.pump(lambda: w.summary is not None)
        self.assertFalse(w.summary.verified)
        self.assertIn('UNVERIFIED', w.preview.get('1.0', 'end'))
        self.assertIn('NOT AVAILABLE', w.preview.get('1.0', 'end'))
        for lang in ('ms', 'en', 'zh'):
            self.app.set_language(lang)
            self.assertFalse(w.summary.verified)
            self.assertIn('UNVERIFIED', w.state.cget('text'))

    def test_daily_pending_generation_failure_and_staleness_survive_switching(self):
        self.app.open_daily(); w = self.app.daily_window
        entered, release = threading.Event(), threading.Event()
        real = daily.generate
        def held(*args, **kwargs):
            entered.set(); release.wait(10)
            return real(*args, **kwargs)
        try:
            with patch.object(daily, 'generate', side_effect=held):
                w.generate(); self.assertTrue(entered.wait(5))
                rid, started = w.request_id, w.runner.threads_started
                self.app.set_language('ms')
                self.assertIn('Menjana', w.status.get())
                self.assertEqual((rid, started), (w.request_id, w.runner.threads_started))
                release.set(); self.pump(lambda: w.summary is not None and not w.runner.busy)
            self.assertIn('1. SUMBER', w.preview.get('1.0', 'end'))
            self.app._invalidate_alerts('RAW source check changed')
            self.pump(lambda: w.stale is not None)
            self.app.set_language('zh')
            self.assertIn('OUT OF DATE', w.state.cget('text'))
            self.assertFalse(w.can_save())
            with patch.object(daily, 'generate', side_effect=daily.DailyReadError('RAW daily read failed')), patch('checker.daily_ui.messagebox.askyesno', return_value=True):
                w.generate()
                self.pump(lambda: not w.runner.busy and w.summary is None)
            self.app.set_language('ms')
            self.assertIn('GENERATION FAILED', w.state.cget('text'))
            self.assertIn('RAW daily read failed', w.state.cget('text'))
            self.assertEqual(w.preview.get('1.0', 'end').strip(), '')
            self.assertFalse(w.can_save()); self.assertIsNone(self.app.alert_authorization())
        finally:
            release.set()

    def test_new_resource_parameters_and_preview_unknown_are_preserved(self):
        fields = lambda text: sorted(field for _, field, _, _ in Formatter().parse(text) if field is not None)
        for english, translations in analysis_daily_i18n.TEXT.items():
            for translated in translations:
                self.assertEqual(fields(english), fields(translated), english)
        summary = self.summary().summary
        data = summary.data()
        # Pure presentation fixture: canonical unknown and literal 0 must stay distinct.
        data['limitations']['current_storage_raw'].update(blank=None, invalid=0)
        changed = daily.DailySummary(summary.report_id, summary.report_date, summary.verified, summary.generation,
                                     summary.basis, summary.generated_local, json.dumps(data))
        for lang, unknown in (('zh', '空白 未知'), ('ms', 'kosong tidak diketahui')):
            rendered = daily_preview.render(changed, lang)
            self.assertIn(unknown, rendered)
            self.assertIn('0', rendered)
            self.assertEqual(changed.data()['limitations']['current_storage_raw']['blank'], None)

    def test_empty_database_preview_keeps_unavailable_alerts_and_sources_unknown(self):
        from checker.sync import InventorySync
        database = self.base / 'empty' / 'inventory.db'
        InventorySync(database)
        summary = daily.generate(database, date.today(), daily.Session(None, None, False, 'not checked'), allow_unverified=True)
        before = summary.json_text
        for lang, source_title in (('zh', '1. 数据来源'), ('ms', '1. SUMBER'), ('en', '1. SOURCES')):
            rendered = daily_preview.render(summary, lang)
            self.assertIn(source_title, rendered)
            self.assertIn('UNVERIFIED', rendered)
            self.assertIn('UNAVAILABLE', rendered)
            self.assertEqual(summary.json_text, before)
            self.assertIsNone(summary.data()['sources']['stock']['current'])
            self.assertIsNone(summary.data()['sources']['bom']['current'])
            self.assertEqual(summary.data()['alerts']['at_generation']['status'], daily.UNAVAILABLE)

    def test_compact_layout_both_windows_in_three_languages_and_font_scales(self):
        for scale in (1, 1.5):
            self.root.tk.call('tk', 'scaling', 96 / 72 * scale)
            for kind in ('analytics', 'daily'):
                if kind == 'analytics':
                    self.app.open_analytics(); w = self.app.analytics_window
                else:
                    self.app.open_daily(); w = self.app.daily_window
                w.top.geometry('960x600')
                for lang in ('en', 'zh', 'ms'):
                    with self.subTest(window=kind, scale=scale, language=lang):
                        self.app.set_language(lang)
                        for _ in range(4): w.top.update()
                        actions = []
                        def visit(widget):
                            if widget.winfo_class() == 'TButton' and widget.winfo_manager(): actions.append(widget)
                            for child in widget.winfo_children(): visit(child)
                        visit(w.top)
                        for widget in (w.banner, *actions):
                            self.assertTrue(widget.winfo_ismapped())
                            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), w.top.winfo_rootx()+w.top.winfo_width())
                            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), w.top.winfo_rooty()+w.top.winfo_height())
                        table = w.tree if kind == 'analytics' else w.preview
                        self.assertGreater(table.winfo_height(), 60)
                w.close(); gc.collect()
