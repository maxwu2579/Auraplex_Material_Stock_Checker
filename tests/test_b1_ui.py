"""B1 main window: navigation, interface language and state protection. Synthetic workbooks, temporary SQLite only.

Visual acceptance is done with screenshots (see B1_UI_TEST_REPORT.md); these tests pin behaviour, not pixels."""
from pathlib import Path
import string
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from checker import alerts, i18n
from checker.appdata import Settings
from checker.core import ENOUGH, EXCEPTION, SHORTAGE
from checker.sync import CLOUD_NOT_VERIFIED, InventorySync
from checker.ui import CheckerApp, NAV
from tests.fixtures import workbook, bom_rows
from tests.test_m32c import stock_with_threshold


class TranslationTableTests(unittest.TestCase):
    def test_every_key_has_three_languages_with_the_same_placeholders(self):
        fields = lambda text: sorted(f for _, f, _, _ in string.Formatter().parse(text) if f)
        for key, texts in i18n.S.items():
            with self.subTest(key=key):
                self.assertEqual(len(texts), 3)
                self.assertTrue(all(t.strip() for t in texts))
                self.assertEqual(fields(texts[0]), fields(texts[1]))
                self.assertEqual(fields(texts[0]), fields(texts[2]))

    def test_codes_and_the_cloud_limitation_are_never_translated(self):
        for language in i18n.LANGUAGES:
            self.assertEqual(i18n.state_text("Sync Failed · Using Previous Data", "en"), "Sync Failed · Using Previous Data")
            self.assertIn("UNVERIFIED", i18n.tr("state_cached", language))
            self.assertIn("OUTDATED / RECHECK REQUIRED", i18n.tr("state_outdated", language))
            self.assertIn("Cloud Not Verified", i18n.tr("state_bound", language, time="t"))
            self.assertIn("Cloud Not Verified", i18n.tr("brand_sub", language))
        self.assertEqual(i18n.state_text("Unknown Future State", "zh"), "Unknown Future State")  # never guessed


class B1Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="_MRC_B1_TEST_")
        base = Path(self.tmp.name)
        self.stock, self.bom = base / "drive" / "Storage B1.xlsx", base / "drive" / "BOM B1.xlsx"
        self.stock.parent.mkdir()
        workbook(self.stock, [("Stock", stock_with_threshold([("A", 0, 5), ("B", 2, 10), ("C", 100, 5),
                                                              ("D", None, 3)]))])
        workbook(self.bom, [("PRODUCT-1", bom_rows([("A", 2), ("B", 1), ("C", 1), ("MISSING", 1)]))])
        self.db = base / "app" / "inventory.db"
        self.settings = base / "app" / "settings.json"
        self.errors = []
        self.patches = [patch("checker.ui.messagebox.showerror", side_effect=lambda t, m, **k: self.errors.append(m)),
                        patch("checker.ui.messagebox.showwarning", side_effect=lambda t, m, **k: self.errors.append(m))]
        for p in self.patches:
            p.start()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = None

    def tearDown(self):
        if self.app is not None and not self.app.closed:
            self.app.close()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def start(self, inventory=True):
        self.app = CheckerApp(self.root, inventory=InventorySync(self.db, settle_seconds=0) if inventory else None,
                              settings=Settings(self.settings))
        self.finish()
        return self.app

    def pump(self, condition, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(0.005)
        self.fail("condition not reached")

    def finish(self):
        self.pump(lambda: not self.app.busy)
        self.root.update()

    def load_and_check(self):
        app = self.app
        app.load_file("stock", str(self.stock)); self.finish()
        app.load_file("bom", str(self.bom)); self.finish()
        if app.alert_runner is not None:
            self.pump(lambda: app.alert_current and not app.alert_runner.running)
        app.product_text.set("PRODUCT-1"); app.quantity_text.set("3")
        app.check_button.invoke(); self.finish()
        self.assertIsNotNone(app.result)
        return app


class LanguageSwitchTests(B1Base):
    def snapshot(self):
        app = self.app
        return dict(product=app.product_text.get(), quantity=app.quantity_text.get(), sheet=app.stock_name.get(),
                    result=app.result, binding=app.result_binding, filter=app.filter_category.get(),
                    rows=[app.tree.item(i, "values") for i in app.tree.get_children()],
                    selection=app.tree.selection(), stock=app.stock_book, bom=app.bom_book,
                    generation=app.alert_gate.generation, current=app.alert_current,
                    authorization=app.alert_authorization(), cache=(app.cache_selection, app.cache_authorized),
                    epoch=app.assistant.session.epoch, authorized=app.assistant.session.authorized,
                    page=app.page, job=app.job, exportable=app.result_exportable,
                    export_state=str(app.export_button.cget("state")))

    def test_switching_keeps_every_input_result_filter_and_permission_and_reads_nothing(self):
        app = self.start(); self.load_and_check()
        app.filter_buttons[SHORTAGE].invoke()
        app.tree.selection_set(app.tree.get_children()[0])
        self.pump(lambda: not app.home.loading and not app.home.wanted or app.page != "home")
        before = self.snapshot()
        reads = []
        with patch.object(app.service.cache, "read", side_effect=lambda *a, **k: reads.append(a)), \
                patch.object(app.inventory, "sync_all", side_effect=lambda *a, **k: reads.append(a)), \
                patch.object(alerts, "load_state", side_effect=lambda *a, **k: reads.append(a)), \
                patch.object(app.alert_runner, "request", side_effect=lambda *a, **k: reads.append(a)), \
                patch.object(app.assistant, "invalidate", side_effect=lambda *a, **k: reads.append(a)):
            for language in ("zh", "ms", "en", "zh"):
                app.lang_buttons[language].invoke()
                for _ in range(5):
                    self.root.update(); time.sleep(0.01)
                with self.subTest(language=language):
                    self.assertEqual(app.language.language, language)
                    self.assertEqual(self.snapshot(), before)
                    self.assertEqual(app.db_cloud_label.cget("text"), CLOUD_NOT_VERIFIED)
                    self.assertEqual(app.page_title.cget("text"), i18n.tr("nav_check", language))
                    # Material IDs, result codes and file names are shown as read.
                    self.assertTrue(all(row[5] == SHORTAGE for row in before["rows"]))
                    self.assertEqual(app.file_view["stock"]["name"].cget("text"), self.stock.name)
        self.assertEqual(reads, [])
        self.assertFalse(self.errors)
        app.set_language("en")
        self.assertEqual(app.db_status.get(), "Status: Local File Checked")

    def test_a_running_check_finishes_normally_across_a_switch(self):
        app = self.start(); self.load_and_check()
        app.quantity_text.set("4")
        app.check_button.invoke()
        self.assertTrue(app.busy)
        app.set_language("ms")
        self.finish()
        self.assertEqual(app.result.production_count, 4)
        self.assertTrue(app.result_current)
        self.assertEqual(app.check_button.cget("text"), i18n.tr("check_button", "ms"))

    def test_without_a_database_the_cloud_limitation_stays_visible_in_every_language(self):
        app = self.start(inventory=False)
        for language in i18n.LANGUAGES:
            app.set_language(language)
            self.assertEqual(app.cloud_chip.cget("text"), CLOUD_NOT_VERIFIED)
            self.assertEqual(app.cloud_chip.winfo_manager(), "grid")


class StateProtectionTests(B1Base):
    def test_an_invalidated_result_is_never_restored_by_language_or_navigation(self):
        app = self.start(); self.load_and_check()
        old = app.result
        app.quantity_text.set("5")  # input changed: the result is withdrawn by the existing invalidation
        self.assertIsNone(app.result)
        for language in i18n.LANGUAGES:
            app.set_language(language)
            for page, _glyph, _key in NAV:
                if page != "ai":
                    app.show_page(page)
            with self.subTest(language=language):
                self.assertIsNone(app.result)
                self.assertEqual(app.tree.get_children(), ())
                self.assertIn(i18n.tr("state_recheck", language), app.home.last_state.cget("text"))
                self.assertEqual({l.cget("text") for l in app.home.last_counts.values()},
                                 {f"{c} —" for c in (SHORTAGE, EXCEPTION, ENOUGH)})
                self.assertIn("disabled", app.home.open_button.state())
        self.assertIs(app.last_check["result"], old)  # kept only as history of what was checked

    def test_an_outdated_result_stays_outdated_and_not_exportable(self):
        app = self.start(); self.load_and_check()
        bound = app.result_binding
        app.result_binding = type(bound)(bound.versions, {role: None for role in bound.versions}, bound.via_sync,
                                         bound.checked_at, bound.attempts)
        app._show_result_state()
        for language in i18n.LANGUAGES:
            app.set_language(language)
            app.show_page("home"); app.show_page("check")
            with self.subTest(language=language):
                self.assertFalse(app.result_exportable)
                self.assertIn("OUTDATED / RECHECK REQUIRED", app.result_state_label.cget("text"))
                self.assertIn("OUTDATED / RECHECK REQUIRED", app.home.last_state.cget("text"))
                self.assertEqual(str(app.export_button.cget("state")), "disabled")

    def test_alert_counts_are_unknown_never_zero_when_not_known(self):
        app = self.start(inventory=False)
        texts = [button.cget("text") for button, _key in app.home.tiles.values()]
        self.assertTrue(all(t.endswith(i18n.tr("alerts_unknown")) for t in texts), texts)
        self.assertEqual(app.home.alert_state.cget("text"), i18n.tr("alerts_no_db"))
        app.close()
        self.root = tk.Tk(); self.root.withdraw()
        app = self.start()  # a database exists but no evaluation of these files yet
        app.home.state = alerts.AlertState(alerts.ALERT_SCHEMA_VERSION, None, None, None, None, None, None, {}, 0, (), 0)
        app.home.render()
        for language in i18n.LANGUAGES:
            app.set_language(language)
            texts = [button.cget("text") for button, _key in app.home.tiles.values()]
            with self.subTest(language=language):
                self.assertTrue(all(t.endswith(i18n.tr("alerts_unknown", language)) for t in texts), texts)
                self.assertFalse(any(t.endswith(" 0") for t in texts))
                self.assertEqual(app.home.alert_state.cget("text"), i18n.tr("alerts_not_evaluated", language))
        app.alert_read_failed("synthetic read failure")
        self.assertEqual(app.home.alert_state.cget("text"), i18n.tr("alerts_read_failed", app.language.language))
        self.assertEqual(app.home.tree.get_children(), ())

    def test_home_tiles_group_stored_rows_and_state_the_overlap(self):
        app = self.start(); self.load_and_check()
        app.show_page("home")
        app.home.request()
        self.pump(lambda: app.home.state is not None and not app.home.loading)
        state = app.home.state
        shown = sum(int(button.cget("text").rsplit(" ", 1)[1]) for button, _key in app.home.tiles.values())
        self.assertEqual(shown, state.total_rows)            # every stored row is in exactly one tile
        self.assertEqual(sum(state.active_counts.values()), state.total_rows)
        self.assertIn(str(state.total_rows), app.home.overlap.cget("text"))
        app.home.tiles["zero"][0].invoke()
        self.assertTrue(all(app.home.tree.item(i, "values")[0] == "OUT_OF_STOCK" for i in app.home.tree.get_children()))
        app.home.select_tile("")
        self.assertEqual(len(app.home.tree.get_children()), len(state.rows))


class NavigationTests(B1Base):
    def test_every_entry_opens_the_existing_function(self):
        app = self.start(); self.load_and_check()
        with patch("checker.ui.HistoryWindow") as history, patch("checker.ui.AnalyticsWindow") as analytics, \
                patch("checker.ui.AlertsWindow") as alerts_window, patch("checker.ui.DailySummaryWindow") as daily:
            for button, opened in ((app.history_button, history), (app.analytics_link, analytics),
                                   (app.alerts_button, alerts_window), (app.home.open_alerts_button, alerts_window),
                                   (app.daily_link, daily)):
                button.invoke()
                self.assertTrue(opened.called)
                app.history_window = app.analytics_window = app.alerts_window = app.daily_window = None
        for page, _glyph, _key in NAV:
            app.show_page(page)
            self.assertEqual(app.page, page)
            self.assertTrue(app.page_frames[page].winfo_manager())
            self.assertEqual(sum(bool(f.winfo_manager()) for f in app.page_frames.values()), 1)
        self.assertIsNotNone(app.result)  # navigation never touches the result

    def test_settings_file_buttons_and_cache_entry_use_the_existing_handlers(self):
        app = self.start(); self.load_and_check()
        with patch("checker.ui.filedialog.askopenfilename", return_value="") as dialog:
            for button in app.settings_file_buttons.values():
                button.invoke()
        self.assertEqual(dialog.call_count, 2)
        self.assertIsNotNone(app.result)  # a cancelled file dialog changes nothing

    def test_ai_reports_entry_opens_the_assistant_report_tab_and_keeps_its_session(self):
        app = self.start(); self.load_and_check()
        epoch = app.assistant.session.epoch
        app.show_page("ai")
        app.open_ai_reports(); self.root.update()
        view = app.assistant.view
        self.assertIsNotNone(view)
        self.assertEqual(view.tabs.tab(view.tabs.select(), "text"),
                         i18n_report_tab(app.assistant.language))
        app.set_language("zh")  # the interface language never changes the assistant's own language
        self.assertEqual(view.tabs.tab(view.tabs.select(), "text"), i18n_report_tab(app.assistant.language))
        self.assertEqual(app.assistant.session.epoch, epoch)
        app.assistant.hide()

    def test_docked_assistant_keeps_check_export_status_and_robot_visible(self):
        app = self.start(); self.load_and_check()
        self.root.deiconify()
        self.root.geometry("1280x680+0+0"); self.root.update()
        with patch.object(type(app.assistant), "_wanted_mode", return_value="docked"):
            app.assistant.toggle()
            app.assistant.view.input.insert("1.0", "draft kept")
            for _ in range(5):
                self.root.update(); app._resize(); time.sleep(0.02)
            self.assertEqual(app.assistant.mode, "docked")
            self.assertTrue(app.sidebar_slim)  # the shell narrowed, so the sidebar collapsed to icons
            for widget in (app.check_button, app.export_button, app.refresh_button, app.db_status_label,
                           app.db_cloud_label, app.assistant.button):
                x = widget.winfo_rootx() - self.root.winfo_rootx()
                self.assertTrue(widget.winfo_ismapped(), widget)
                self.assertLessEqual(x + widget.winfo_width(), app.outer.winfo_width(), widget)
        app.assistant._adapt(); self.root.update()  # back to the separate window: draft and session kept
        self.assertEqual(app.assistant.mode, "window")
        self.assertEqual(app.assistant.view.input.get("1.0", "end-1c"), "draft kept")
        self.assertIsNotNone(app.result)
        app.assistant.hide()
        self.root.withdraw()

    def test_sidebar_collapse_is_a_user_choice_and_changes_nothing_else(self):
        app = self.start(); self.load_and_check()
        result, product = app.result, app.product_text.get()
        slim = app.sidebar_slim
        app.toggle_sidebar()
        self.assertEqual(app.sidebar_slim, not slim)
        app._resize()
        self.assertEqual(app.sidebar_slim, not slim)  # resizing keeps the user's choice
        self.assertIs(app.result, result); self.assertEqual(app.product_text.get(), product)


class LastTrialLayoutTests(B1Base):
    def check_layout(self, scale):
        from tkinter import font as tkfont
        self.root.tk.call("tk", "scaling", 96 / 72 * scale)
        app = self.start(); self.load_and_check()
        self.root.deiconify()
        app.show_page("home")
        result = app.result
        for size in ("960x600", "1280x720"):
            self.root.geometry(size)
            for digits in (None, 123456):
                if digits is not None:
                    # Stress the display only, without allocating thousands of synthetic material rows.
                    app.last_check["counts"] = {code: digits for code in (SHORTAGE, EXCEPTION, ENOUGH)}
                app.home.render_check()
                for _ in range(3):
                    self.root.update(); app._resize()
                with self.subTest(scale=scale, size=size, digits=digits):
                    for label in app.home.last_counts.values():
                        self.assertTrue(label.winfo_ismapped())
                        needed = tkfont.Font(font=label.cget("font")).measure(label.cget("text"))
                        self.assertGreaterEqual(label.winfo_width(), needed + 2)
                        self.assertLessEqual(label.winfo_rootx() + label.winfo_width(),
                                             label.master.winfo_rootx() + label.master.winfo_width())
                        self.assertLessEqual(label.winfo_rooty() + label.winfo_height(),
                                             label.master.winfo_rooty() + label.master.winfo_height())
                    self.assertIs(app.result, result)

    def test_last_trial_counters_fit_at_normal_font_size(self):
        self.check_layout(1)

    def test_last_trial_counters_fit_at_150_percent_font_size(self):
        self.check_layout(1.5)


def i18n_report_tab(language):
    from checker.assistant_language import tr
    return tr("report_tab", language)


if __name__ == "__main__":
    unittest.main()
