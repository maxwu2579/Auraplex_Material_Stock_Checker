"""Cache/maintenance consent localisation. Real preview objects, synthetic workbooks/temp SQLite only."""
import gc
import hashlib
import time
from string import Formatter
from unittest.mock import patch

from checker import cached, retention, upgrade, maintenance_i18n, history, alerts, analytics, daily
from checker.sync import InventorySync
from tests.test_m31 import UiBase
from tests.test_m32b import History, NOW
from tests.test_m32c import make_schema_1


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MaintenanceLanguageTests(History, UiBase):
    def setUp(self):
        gc.collect()
        super().setUp()
        self.seed(); self.start_app()

    def tearDown(self):
        try:
            super().tearDown()
        finally:
            self.apps.clear(); self.app = self.root = None
            gc.collect()

    def test_preview_resources_keep_fields_counts_and_english_contract(self):
        before = digest(self.db), digest(self.stock), digest(self.bom)
        snapshot = cached.load(self.db)
        plan = self.retainer.preview(NOW)
        legacy = self.base / 'legacy' / 'inventory.db'; make_schema_1(legacy)
        upgrade_plan = upgrade.preview(legacy)
        self.assertEqual(maintenance_i18n.cache_description(snapshot, 'en'), snapshot.describe())
        self.assertEqual(maintenance_i18n.retention_description(plan, 'en'), plan.describe())
        self.assertEqual(maintenance_i18n.upgrade_description(upgrade_plan, 'en'), upgrade_plan.describe())
        fields = lambda text: sorted(field for _, field, _, _ in Formatter().parse(text) if field is not None)
        for english, translations in maintenance_i18n.TEXT.items():
            for text in translations: self.assertEqual(fields(english), fields(text), english)
        for lang in ('zh', 'ms'):
            cache = maintenance_i18n.cache_description(snapshot, lang)
            self.assertIn('CACHED DATA / UNVERIFIED', cache); self.assertIn('Cloud Not Verified', cache)
            for version in snapshot.versions:
                for value in (version.path, version.imported_at, version.source_modified_at): self.assertIn(value, cache)
            text = maintenance_i18n.retention_description(plan, lang)
            for value in (plan.database, plan.snapshot_cutoff, plan.routine_cutoff, plan.failure_cutoff): self.assertIn(value, text)
            for name, count in plan.counts:
                label = self.app.text(maintenance_i18n.message(name)) if lang == self.app.language.language else maintenance_i18n._text(lang, name)
                self.assertIn(f'{label}: {count}', text)
            text = maintenance_i18n.upgrade_description(upgrade_plan, lang)
            self.assertIn(str(legacy), text); self.assertIn('MIN QTY / MIIN QTY', text)
        self.assertEqual(before, (digest(self.db), digest(self.stock), digest(self.bom)))

    def test_cache_dialog_defaults_no_in_all_languages_and_explicit_yes_is_unverified(self):
        before = digest(self.db)
        for lang, title in (('zh', '使用历史缓存'), ('ms', 'Guna data cache sejarah'), ('en', 'Use historical cached data')):
            self.app.set_language(lang)
            with patch('checker.ui.messagebox.askyesno', return_value=False) as ask:
                self.app.use_cached_data(); self.finish()
            self.assertIn(title, ask.call_args.args[0]); self.assertEqual(ask.call_args.kwargs['default'], 'no')
            self.assertIn('UNVERIFIED', ask.call_args.args[1]); self.assertIn('Cloud Not Verified', ask.call_args.args[1])
            self.assertIn(str(self.stock), ask.call_args.args[1]); self.assertIn(str(self.bom), ask.call_args.args[1])
            self.assertFalse(self.app.cache_authorized); self.assertIsNone(self.app.cache_selection)
        self.app.set_language('ms')
        with patch('checker.ui.messagebox.askyesno', return_value=True):
            self.app.use_cached_data(); self.finish()
        self.assertTrue(self.app.cache_authorized)
        self.assertIn('CACHED DATA / UNVERIFIED', self.app.status.get())
        self.assertTrue(self.app.mode_label.cget('text').startswith('CACHED'))  # compact badge may be ellipsized
        self.assertFalse(self.app.result_current)
        self.assertEqual(digest(self.db), before)

    def test_retention_confirmation_is_default_no_and_cannot_delete_by_switching_language(self):
        before = digest(self.db)
        for lang, title in (('zh', '确认清理'), ('ms', 'Sahkan pembersihan'), ('en', 'Confirm local history cleanup')):
            self.app.set_language(lang)
            with patch('checker.retention.utc_now', return_value=NOW), patch('checker.ui.messagebox.askyesno', return_value=False) as ask, \
                 patch.object(retention.RetentionService, 'apply', side_effect=AssertionError('declined cleanup')):
                self.app.preview_cleanup(); self.finish()
            self.assertIn(title, ask.call_args.args[0]); self.assertEqual(ask.call_args.kwargs['default'], 'no')
            self.assertIn(str(self.db), ask.call_args.args[1])
            self.assertEqual(digest(self.db), before)
        self.assertFalse((self.data / 'backups').exists())

    def test_all_four_open_windows_switch_without_queries_or_authorization_changes(self):
        self.app.open_history(); self.app.open_alerts(); self.app.open_analytics(); self.app.open_daily()
        history_window, alert_window = self.app.history_window, self.app.alerts_window
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            self.root.update()
            if not history_window.lanes['sheets'].active and not any(alert_window.loading.values()): break
            time.sleep(.005)
        self.assertFalse(history_window.lanes['sheets'].active)
        self.assertFalse(any(alert_window.loading.values()))
        before = (self.app.job, self.app.alert_gate.generation, self.app.alert_authorization(),
                  self.app.cache_authorized, self.app.analytics_window.generation, self.app.daily_window.request_id)
        with patch.object(history, 'list_sheets', side_effect=AssertionError('language read Sheets')), \
             patch.object(alerts, 'load_state', side_effect=AssertionError('language read alerts')), \
             patch.object(analytics, 'analyze', side_effect=AssertionError('language analyzed')), \
             patch.object(daily, 'generate', side_effect=AssertionError('language generated')):
            for lang, titles in (('zh', ('库存历史', '库存提醒', '库存分析', '库存日报')),
                                 ('ms', ('Sejarah inventori', 'Amaran stok', 'Analisis inventori', 'Ringkasan stok harian')),
                                 ('en', ('Inventory History', 'Stock Alerts', 'Inventory Analytics', 'Daily Stock Summary'))):
                self.app.set_language(lang); self.root.update()
                for window, title in zip((history_window, alert_window, self.app.analytics_window, self.app.daily_window), titles):
                    self.assertIn(title, window.top.title())
                    self.assertIn('Cloud Not Verified', window.banner.cget('text'))
                after = (self.app.job, self.app.alert_gate.generation, self.app.alert_authorization(),
                         self.app.cache_authorized, self.app.analytics_window.generation, self.app.daily_window.request_id)
                self.assertEqual(before, after)

    def test_upgrade_confirmation_is_default_no_and_preserves_schema(self):
        legacy = self.base / 'legacy' / 'inventory.db'; make_schema_1(legacy)
        before = digest(legacy)
        original = self.app.inventory
        self.app.inventory = InventorySync(legacy, settle_seconds=0)
        try:
            for lang, title in (('zh', '升级本地数据库'), ('ms', 'Naik taraf pangkalan data setempat'), ('en', 'Upgrade local database')):
                self.app.set_language(lang)
                with patch('checker.ui.messagebox.askyesno', return_value=False) as ask, \
                     patch.object(upgrade, 'apply', side_effect=AssertionError('declined upgrade')):
                    self.app.preview_upgrade(); self.finish()
                self.assertIn(title, ask.call_args.args[0]); self.assertEqual(ask.call_args.kwargs['default'], 'no')
                self.assertIn(str(legacy), ask.call_args.args[1])
                self.assertEqual(digest(legacy), before)
        finally:
            self.app.inventory = original
        self.assertFalse((legacy.parent / 'backups').exists())


class ClosedCacheConsentTests(UiBase):
    def test_closing_during_consent_never_authorizes_or_updates_destroyed_widgets(self):
        self.start_app(); self.select_files()
        errors = []
        self.root.report_callback_exception = lambda *error: errors.append(str(error[1]))
        def answer(*args, **kwargs):
            self.app.close()
            return True
        with patch('checker.ui.messagebox.askyesno', side_effect=answer):
            self.app.use_cached_data()
            end = time.monotonic()+5
            while not self.app.closed and time.monotonic()<end:
                self.root.update(); time.sleep(.005)
        self.assertTrue(self.app.closed)
        self.assertFalse(self.app.cache_authorized)
        self.assertIsNone(self.app.cache_selection)
        self.assertEqual(errors, [])
