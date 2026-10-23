"""B1 main window: dialog bodies and status bar in zh/en/ms, and the remembered interface language.

Synthetic workbooks, temporary folders and temporary SQLite only; no real data, API or user window."""
import json
import os
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from checker import i18n
from checker.appdata import InterfacePreferences, Settings
from checker.binding import OUTDATED
from checker.sync import CLOUD_NOT_VERIFIED, InventorySync
from checker.ui import CheckerApp
from tests.fixtures import workbook, bom_rows, stock_rows


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="_MRC_B1_L10N_")
        self.base = Path(self.tmp.name)
        self.stock, self.bom = self.base / "drive" / "Storage L10N.xlsx", self.base / "drive" / "BOM L10N.xlsx"
        self.stock.parent.mkdir()
        workbook(self.stock, [("Stock", stock_rows([("A", 100), ("B", 0)]))])
        workbook(self.bom, [("PRODUCT-1", bom_rows([("A", 2), ("B", 1)])), ("PRODUCT-2", bom_rows([("A", 1)]))])
        self.errors, self.warnings = [], []
        self.patches = [patch("checker.ui.messagebox.showerror", side_effect=lambda t, m, **k: self.errors.append((t, m))),
                        patch("checker.ui.messagebox.showwarning", side_effect=lambda t, m, **k: self.warnings.append((t, m)))]
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

    def start(self, inventory=False, preferences=None):
        self.app = CheckerApp(self.root, inventory=InventorySync(self.base / "app" / "inventory.db", settle_seconds=0)
                              if inventory else None, preferences=preferences)
        self.finish()
        return self.app

    def finish(self):
        deadline = time.monotonic() + 15
        while self.app.busy and time.monotonic() < deadline:
            self.root.update(); time.sleep(0.005)
        self.assertFalse(self.app.busy)
        self.root.update()

    def load(self):
        self.app.load_file("stock", str(self.stock)); self.finish()
        self.app.load_file("bom", str(self.bom)); self.finish()

    def check(self, product="PRODUCT-1", quantity="3"):
        self.app.product_text.set(product); self.app.quantity_text.set(quantity)
        self.app.check_button.invoke(); self.finish()

    def last_error(self):
        return self.errors[-1][1]


class DialogLanguageTests(Base):
    def test_input_problems_in_three_languages_keep_detail_and_recovery(self):
        app = self.start(); self.load()
        expected = {
            "en": ("positive whole number", "must be a positive whole number", "2 matches", "No Product ID",
                   "Load both the Storage and BOM files"),
            "zh": ("正整数", "请输入正整数后重新 CHECK", "有 2 个匹配项", "BOM 中没有匹配的 Product ID", "请先成功读取库存与 BOM 文件"),
            "ms": ("nombor bulat positif", "Masukkan nombor bulat", "2 padanan", "Tiada ID produk", "Baca fail Storage dan BOM"),
        }
        for language, (quantity, recovery, ambiguous, none, files) in expected.items():
            app.set_language(language)
            with self.subTest(language=language):
                self.check(quantity="0")
                self.assertIn(quantity, self.last_error()); self.assertIn(recovery, self.last_error())
                self.assertIn("Production Quantity 必须是正整数。", self.last_error())  # the rule's own detail kept
                self.assertEqual(self.errors[-1][0], i18n.tr("title_input", language))
                self.check(product="product")
                self.assertIn(ambiguous, self.last_error()); self.assertIn("“product”", self.last_error())
                self.check(product="invented")
                self.assertIn(none, self.last_error())
                self.assertIsNone(app.result)
        app.stock_book = None  # files not loaded: refused before anything is read
        for language in i18n.LANGUAGES:
            app.set_language(language)
            self.check()
            self.assertIn(expected[language][4], self.last_error())
            self.assertIn("Reload Files", self.last_error())

    def test_read_failure_names_the_file_keeps_the_error_and_says_how_to_recover(self):
        app = self.start(); self.load()
        self.bom.write_bytes(b"not a workbook")
        for language, recovery in (("zh", "修正后点击 Reload Files 重试；另一文件不受影响"),
                                   ("ms", "kemudian klik Reload Files"), ("en", "then click Reload Files")):
            app.set_language(language)
            before = len(self.errors)
            app.reload_files(); self.finish()
            with self.subTest(language=language):
                self.assertEqual(len(self.errors), before + 1)
                title, body = self.errors[-1]
                self.assertEqual(title, i18n.tr("title_failed", language))
                self.assertIn(i18n.tr("role_bom", language), body)
                self.assertNotIn(i18n.tr("role_stock", language), body)  # the other file is not blamed
                self.assertIn(recovery, body)
                self.assertIsNone(app.bom_book); self.assertIsNotNone(app.stock_book)
                self.assertIn(i18n.tr("st_failed_card", language, db=""), app.status.get())

    def test_export_refusals_and_write_failure_in_three_languages(self):
        app = self.start(); self.load()
        app.export()
        self.assertIn("Run CHECK first", self.last_error())
        self.check()
        self.assertTrue(app.result_current)
        target = self.base / "out" / "report.xlsx"
        target.parent.mkdir()
        for language, recovery in (("en", "Choose another folder"), ("zh", "请选择其他文件夹"), ("ms", "Pilih folder lain")):
            app.set_language(language)
            with patch("checker.ui.save_verified_report", side_effect=PermissionError(13, "synthetic denied")):
                self.assertIsNone(app.write_export(str(target)))
            with self.subTest(language=language):
                title, body = self.errors[-1]
                self.assertEqual(title, i18n.tr("title_export_failed", language))
                self.assertIn(str(target), body); self.assertIn("synthetic denied", body); self.assertIn(recovery, body)
                self.assertTrue(app.result_current)  # a write failure changes no result state
        bound = app.result_binding
        app.result_binding = type(bound)(bound.versions, {r: None for r in bound.versions}, bound.via_sync,
                                         bound.checked_at, bound.attempts)
        for language, words in (("en", "cannot be exported as a valid report"), ("zh", "不能导出为有效报告"),
                                ("ms", "tidak boleh dieksport sebagai laporan sah")):
            app.set_language(language)
            self.assertIsNone(app.write_export(str(target)))
            self.assertEqual(self.errors[-1][0], OUTDATED)  # the code itself is the title, untranslated
            self.assertIn(words, self.last_error())
        self.assertFalse(target.exists())


class ChineseWordingTests(unittest.TestCase):
    """zh keeps the former Chinese dialog wording exactly; values (details, codes, times) pass through unchanged."""

    def test_former_chinese_text_is_kept(self):
        render = lambda key, **v: i18n.render(i18n.Message(key, **v), "zh")
        self.assertEqual(render("sync_kept_previous", time="T"),
                         "数据库保留此前同步的数据（Previously Verified T，历史时间），但当前未验证，未显示为新同步。")
        self.assertEqual(render("sync_unrecorded"), "（本次失败未能写入数据库记录。）")
        self.assertTrue(render("sync_status_failed", error="E", state="S").startswith("Inventory Database 状态读取失败：E"))
        self.assertEqual(render("err_result_changed"), "选择导出位置期间 CHECK 结果已变化，请重新发起导出。")
        self.assertEqual(render("err_product", text="x", matches=i18n.Message("err_product_none")),
                         "“x” 不是一个已选定的 Product ID。BOM 中没有匹配的 Product ID；请从下拉列表选择实际存在的产品。"
                         "部分名称、虚构名称或歧义名称不能检查。")
        self.assertEqual(render("err_role_failed", role=i18n.Message("role_stock"), error="E").splitlines()[0],
                         "Storage / 库存 Excel：E")
        self.assertEqual(render("err_outdated", detail=""),
                         "此结果不能确认属于当前的本机 Storage / BOM 文件版本（源文件已变化或无法复核），不能导出为有效报告。请重新 CHECK。")
        for language in i18n.LANGUAGES:  # codes and details are never translated
            text = i18n.render(i18n.Message("st_cache_export_failed", outdated=OUTDATED, label="CACHED DATA / UNVERIFIED",
                                            cloud=CLOUD_NOT_VERIFIED), language)
            self.assertEqual(text, f"{OUTDATED} · CACHED DATA / UNVERIFIED · {CLOUD_NOT_VERIFIED}")


class StatusLanguageTests(Base):
    def test_status_is_structured_and_rerendered_not_string_replaced(self):
        app = self.start(); self.load(); self.check()
        english = app.status.get()
        self.assertRegex(english, r"^Checked 2 materials in \d+\.\d\ds · Local Sources Verified$")
        message = app.status_message
        seconds = english.split(" in ")[1].split("s ·")[0]
        app.set_language("zh")
        self.assertEqual(app.status.get(), f"已检查 2 种材料，用时 {seconds} 秒 · Local Sources Verified")
        app.set_language("ms")
        self.assertEqual(app.status.get(), f"2 bahan disemak dalam {seconds}s · Local Sources Verified")
        app.set_language("en")
        self.assertEqual(app.status.get(), english)
        self.assertEqual(app.status_message, message)  # the same stored facts, re-rendered three times

    def test_database_suffix_keeps_cloud_not_verified_and_the_state_snapshot(self):
        app = self.start(inventory=True); self.load(); self.check()
        self.assertTrue(app.status.get().endswith(f" · Inventory Database: Local File Checked — {CLOUD_NOT_VERIFIED}"))
        app.set_language("zh")
        self.assertTrue(app.status.get().endswith(f" · 库存数据库：本地文件已核对 — {CLOUD_NOT_VERIFIED}"))
        app.db_overall = "Sync Failed"  # a later state change is not folded into the earlier message
        app.set_language("ms")
        self.assertIn("Fail setempat disemak", app.status.get())
        self.assertIn(CLOUD_NOT_VERIFIED, app.status.get())

    def test_switching_during_a_running_check_shows_the_running_then_the_finished_job(self):
        app = self.start(); self.load()
        app.product_text.set("PRODUCT-1"); app.quantity_text.set("2")
        app.check_button.invoke()
        self.assertTrue(app.busy)
        self.assertEqual(app.status.get(), "Checking materials…")
        app.set_language("ms")
        self.assertEqual(app.status.get(), "Menyemak bahan…")
        self.finish()
        self.assertTrue(app.result_current); self.assertEqual(app.result.production_count, 2)
        self.assertTrue(app.status.get().startswith("2 bahan disemak"))
        app.set_language("zh")  # the finished job is rendered, never the earlier "checking" text
        self.assertTrue(app.status.get().startswith("已检查 2 种材料"))

    def test_a_failed_job_is_never_rendered_as_success(self):
        app = self.start(); self.load(); self.check()
        self.stock.write_bytes(b"broken")
        app.reload_files(); self.finish()
        self.assertEqual(app.status_message.key, "st_failed_card")
        success = {"en": "Checked", "zh": "已检查", "ms": "bahan disemak"}
        for language in ("zh", "ms", "en"):
            app.set_language(language)
            with self.subTest(language=language):
                self.assertIn(i18n.tr("st_failed_card", language, db=""), app.status.get())
                self.assertNotIn(success[language], app.status.get())
                self.assertIsNone(app.result)


class PreferenceFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="_MRC_B1_PREF_")
        self.path = Path(self.tmp.name) / "data" / "interface.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_corrupt_and_invalid_files_give_english(self):
        prefs = InterfacePreferences(self.path)
        self.assertEqual(prefs.load(), ("en", None))
        self.path.parent.mkdir(parents=True)
        for content in (b"{not json", b"\xff\xfe\x00", json.dumps({"language": "fr"}).encode(), b"[]", b""):
            self.path.write_bytes(content)
            language, problem = prefs.load()
            self.assertEqual(language, "en"); self.assertTrue(problem)

    def test_save_is_atomic_and_a_failure_keeps_the_old_file(self):
        prefs = InterfacePreferences(self.path)
        prefs.save("zh")
        self.assertEqual(prefs.load(), ("zh", None))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"version": 1, "language": "zh"})
        with patch("checker.appdata.os.replace", side_effect=PermissionError(13, "synthetic locked")):
            with self.assertRaises(OSError):
                prefs.save("ms")
        self.assertEqual(prefs.load(), ("zh", None))
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["interface.json"])  # no temp left
        with self.assertRaises(ValueError):
            prefs.save("fr")


class PreferenceAppTests(Base):
    def prefs(self):
        return InterfacePreferences(self.base / "appdata" / "interface.json")

    def test_the_last_choice_is_restored_without_extra_work_and_settings_stay_untouched(self):
        settings = Settings(self.base / "appdata" / "settings.json")
        settings.remember("stock", str(self.stock))
        settings_bytes = settings.path.read_bytes()
        self.prefs().save("ms")
        with patch.object(CheckerApp, "_startup") as startup:
            app = self.start(preferences=self.prefs())
        startup.assert_not_called()  # no settings passed here: nothing is synchronised because of the language
        self.assertEqual(app.language.language, "ms")
        self.assertEqual(app.page_title.cget("text"), i18n.tr("nav_home", "ms"))
        self.assertEqual(app.status.get(), i18n.tr("st_ready", "ms"))
        self.assertEqual((app.job, app.busy), (0, False))
        app.set_language("zh")
        self.assertEqual(self.prefs().load(), ("zh", None))
        self.assertEqual(settings.path.read_bytes(), settings_bytes)
        self.assertEqual(sorted(p.name for p in settings.path.parent.iterdir()), ["interface.json", "settings.json"])

    def test_corrupt_file_starts_in_english_and_says_so(self):
        path = self.base / "appdata" / "interface.json"
        path.parent.mkdir(parents=True)
        path.write_text("{broken", encoding="utf-8")
        app = self.start(preferences=self.prefs())
        self.assertEqual(app.language.language, "en")
        self.assertEqual(app.preference_label.cget("text"), i18n.tr("pref_unreadable", "en"))
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")  # not rewritten until the user chooses
        self.load(); self.check()
        self.assertTrue(app.result_current)
        app.set_language("zh")
        self.assertEqual(self.prefs().load(), ("zh", None))
        self.assertEqual(app.preference_label.cget("text"), "")

    def test_a_write_failure_keeps_the_session_language_and_everything_else(self):
        app = self.start(preferences=self.prefs()); self.load(); self.check()
        result, status = app.result, app.status_message
        with patch.object(InterfacePreferences, "save", side_effect=PermissionError(13, "synthetic read-only folder")):
            app.set_language("zh")
        self.assertEqual(app.language.language, "zh")
        self.assertIn("synthetic read-only folder", app.preference_label.cget("text"))
        self.assertIs(app.result, result); self.assertTrue(app.result_current)
        self.assertEqual(app.status_message, status)
        self.assertFalse(self.errors)  # no dialog, nothing blocked
        app.set_language("ms")  # writable again: saved, warning cleared
        self.assertEqual(self.prefs().load(), ("ms", None))
        self.assertEqual(app.preference_label.cget("text"), "")

    def test_an_unreadable_location_never_blocks_start(self):
        with patch.object(InterfacePreferences, "load", return_value=("en", "OSError: synthetic")):
            app = self.start(preferences=self.prefs())
        self.assertEqual(app.language.language, "en")
        self.load(); self.check()
        self.assertTrue(app.result_current)


if __name__ == "__main__":
    unittest.main()
