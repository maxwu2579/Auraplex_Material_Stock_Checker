"""Focused History interface-language checks: synthetic workbooks/temp database only."""
import gc
import hashlib
import threading
import time
from unittest.mock import patch

from checker import history, history_i18n, i18n
from tests.test_m31 import UiBase


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HistoryLanguageTests(UiBase):
    def setUp(self):
        gc.collect()  # destroyed Tk roots must be collected on the UI thread, before workers start
        super().setUp()
        self.callback_errors = []
        self.start_app()
        self.select_files()
        self.root.report_callback_exception = lambda *error: self.callback_errors.append(error)
        self.app.open_history()
        self.window = self.app.history_window
        self.pump(lambda: len(self.window.sheet_combo['values']) > 1)

    def tearDown(self):
        try:
            self.assertEqual(self.callback_errors, [])
        finally:
            super().tearDown()
            self.apps.clear()
            self.window = self.app = self.root = None
            gc.collect()  # release test-owned Tk cycles here, not in a later worker

    def pump(self, done):
        end = time.monotonic() + 10
        while time.monotonic() < end:
            self.root.update()
            if done():
                return
            time.sleep(.005)
        self.fail('Timed out')

    def choose(self):
        self.window.select('A')
        self.pump(lambda: self.window.result is not None)

    def test_switch_preserves_results_filters_sources_and_does_not_read(self):
        self.window.search_text.set("a"); self.window.search()
        self.pump(lambda: bool(self.window.candidates))
        self.window.candidate_list.selection_set(0); self.window._picked()
        self.pump(lambda: self.window.result is not None)
        w = self.window
        tree = w.trees['records']
        tree.selection_set('0'); w._show_row('records')
        before = (w.result, w.selected_key, w.days.get(), dict(w.shown), w.query_gen, w.search_gen,
                  tree.selection(), tree.item('0', 'values'), w.details.get('1.0', 'end'))
        hashes = tuple(digest(p) for p in (self.db, self.stock, self.bom))
        threads = {kind: lane.started for kind, lane in w.lanes.items()}
        self.app.product_text.set('untouched'); self.app.quantity_text.set('13')
        with patch.object(history, 'material_history', side_effect=AssertionError('unexpected query')), \
             patch.object(history, 'search_materials', side_effect=AssertionError('unexpected search')), \
             patch.object(history, 'list_sheets', side_effect=AssertionError('unexpected sheets')):
            for lang, title, query in [('zh', '库存历史', '查询'), ('ms', 'Sejarah inventori', 'Tanya'), ('en', 'Inventory History', 'Query')]:
                self.app.set_language(lang)
                self.root.update()
                self.assertIn(title, w.top.title())
                self.assertEqual(w.query_button.cget('text'), query)
                self.assertIn('Cloud Not Verified', w.banner.cget('text'))
                self.assertEqual(w.sheet_combo.current(), 0)
                self.assertEqual(w.sheet.get(), w.text(history_i18n.message('All Sheets (shown separately)')))
                after = (w.result, w.selected_key, w.days.get(), dict(w.shown), w.query_gen, w.search_gen,
                         tree.selection(), tree.item('0', 'values'), w.details.get('1.0', 'end'))
                self.assertEqual(before, after)
                self.assertEqual((self.app.product_text.get(), self.app.quantity_text.get()), ('untouched', '13'))
        self.assertEqual(threads, {kind: lane.started for kind, lane in w.lanes.items()})
        self.assertEqual(hashes, tuple(digest(p) for p in (self.db, self.stock, self.bom)))

    def test_pending_query_uses_latest_language_without_restart(self):
        entered, release = threading.Event(), threading.Event()
        real = history.material_history
        def hold(*args):
            entered.set(); release.wait(10)
            return real(*args)
        try:
            with patch.object(history, 'material_history', side_effect=hold):
                self.window.select('A')
                self.assertTrue(entered.wait(5))
                generation = self.window.query_gen
                self.app.set_language('ms')
                self.assertIn('Menanya A', self.window.status.get())
                self.app.set_language('zh')
                self.assertIn('正在查询 A', self.window.status.get())
                self.assertEqual(self.window.query_gen, generation)
                release.set()
                self.pump(lambda: self.window.result is not None)
            self.assertIn('历史载入于', self.window.status.get())
            self.assertIn('范围内有', self.window.coverage.get('1.0', 'end'))
            self.assertEqual(self.window.lanes['query'].started, 1)
        finally:
            release.set()

    def test_failure_stays_failure_after_switch_and_reopen_uses_current_language(self):
        self.choose()
        with patch.object(history, 'material_history', side_effect=history.HistoryReadError('RAW Sheet-A database locked')):
            self.window.query()
            self.pump(lambda: 'Query failed' in self.window.status.get())
        for lang, failure in [('zh', '查询失败'), ('ms', 'Pertanyaan gagal')]:
            self.app.set_language(lang)
            self.assertIn(failure, self.window.status.get())
            self.assertIn('QUERY FAILED', self.window.coverage.get('1.0', 'end'))
            self.assertIn('RAW Sheet-A database locked', self.window.coverage.get('1.0', 'end'))
            self.assertIsNone(self.window.result)
            self.assertEqual(self.window.trees['records'].get_children(), ())
            self.assertEqual(self.window.count_labels['records'].cget('text'), '')
        self.window.close()
        self.app.set_language('zh')
        self.app.open_history()
        self.window = self.app.history_window
        self.assertIn('库存历史', self.window.top.title())
        self.assertEqual(self.window.query_button.cget('text'), '查询')

    def test_resources_have_equivalent_placeholders_and_sheet_names_remain_exact(self):
        from string import Formatter
        fields = lambda text: sorted(field for _, field, _, _ in Formatter().parse(text) if field is not None)
        for english, translations in history_i18n.TEXT.items():
            for translated in translations:
                self.assertEqual(fields(english), fields(translated), english)
        self.app.set_language('zh')
        self.window._sheets_loaded(['Sheet original 查询', 'Sheet A'], None)
        self.window.sheet_combo.current(1)
        with patch.object(history, 'material_history', wraps=history.material_history) as read:
            self.window.select('A')
            self.pump(lambda: self.window.result is not None)
        self.assertEqual(read.call_args.args[-1], 'Sheet original 查询')
        self.app.set_language('ms')
        self.assertEqual(self.window.sheet.get(), 'Sheet original 查询')
        self.assertEqual(self.window.sheet_combo.current(), 1)

    def test_compact_layout_in_three_languages_with_font_scaling(self):
        for scale in (1, 1.5):
            self.window.close()
            gc.collect()
            self.root.tk.call('tk', 'scaling', 96 / 72 * scale)
            self.app.open_history()
            self.window = self.app.history_window
            top = self.window.top
            top.geometry('960x600')
            self.choose()
            for lang in ('en', 'zh', 'ms'):
                with self.subTest(scale=scale, language=lang):
                    self.app.set_language(lang)
                    for _ in range(4): top.update()
                    for widget in (self.window.banner, self.window.search_entry,
                                   self.window.query_button, self.window.sheet_combo,
                                   self.window.range_buttons[90], self.window.status_label):
                        self.assertTrue(widget.winfo_ismapped())
                        self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), top.winfo_rootx()+top.winfo_width())
                        self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), top.winfo_rooty()+top.winfo_height())
                    self.assertGreater(self.window.trees['records'].winfo_height(), 60)
