"""Reliability R1: retrying the remembered interface language, and bounded History window background work.

Synthetic workbooks, temporary folders and temporary SQLite only; no real data, API or user window."""
import threading
import time
from unittest.mock import patch

from checker import history, i18n
from checker.appdata import InterfacePreferences
from checker.history import HistoryReadError
from tests.test_b1_l10n import Base as L10nBase
from tests.test_m31 import UiBase


class SameLanguageRetryTests(L10nBase):
    def prefs(self):
        return InterfacePreferences(self.base / "appdata" / "interface.json")

    def quiet(self, app):
        """Spies proving a same-language click re-renders nothing and starts no work."""
        return (patch.object(app, "_apply_tree_headings", side_effect=AssertionError("interface re-rendered")),
                patch.object(app, "load_file", side_effect=AssertionError("Excel read")))

    def test_clicking_the_current_language_repairs_a_corrupt_file(self):
        path = self.base / "appdata" / "interface.json"
        path.parent.mkdir(parents=True)
        path.write_text("{broken", encoding="utf-8")
        app = self.start(preferences=self.prefs()); self.load(); self.check()
        self.assertEqual(app.language.language, "en")
        self.assertEqual(app.preference_label.cget("text"), i18n.tr("pref_unreadable", "en"))
        result, status, job = app.result, app.status_message, app.job
        first, second = self.quiet(app)
        with first, second:
            app.set_language("en")
        self.assertEqual(self.prefs().load(), ("en", None))
        self.assertEqual(app.preference_label.cget("text"), "")
        self.assertIs(app.result, result); self.assertTrue(app.result_current)
        self.assertEqual((app.status_message, app.job, app.busy), (status, job, False))
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["interface.json"])  # no settings.json, no temp
        self.assertFalse(self.errors or self.warnings)

    def test_clicking_the_current_language_retries_a_failed_save(self):
        app = self.start(preferences=self.prefs()); self.load(); self.check()
        with patch.object(InterfacePreferences, "save", side_effect=PermissionError(13, "synthetic read-only folder")):
            app.set_language("zh")
            app.set_language("zh")  # still not writable: the session language stays, the warning stays
        self.assertEqual(app.language.language, "zh")
        self.assertIn("synthetic read-only folder", app.preference_label.cget("text"))
        self.assertEqual(self.prefs().load(), ("en", None))  # nothing written yet
        result, status, job = app.result, app.status_message, app.job
        first, second = self.quiet(app)
        with first, second:
            app.set_language("zh")  # writable again
        self.assertEqual(self.prefs().load(), ("zh", None))
        self.assertEqual(app.preference_label.cget("text"), "")
        self.assertIs(app.result, result); self.assertTrue(app.result_current)
        self.assertEqual((app.status_message, app.job, app.busy, app.language.language), (status, job, False, "zh"))
        self.assertFalse(self.errors or self.warnings)


class Gate:
    """A stand-in for a slow history read that ignores cancellation until released, then reads for real."""

    def __init__(self, real):
        self.real, self.release, self.calls = real, threading.Event(), []

    def __call__(self, *args):
        self.calls.append(args)
        self.release.wait(10)
        return self.real(*args)


class HistoryLaneTests(UiBase):
    def setUp(self):
        super().setUp()
        self.callback_errors = []
        self.start_app()
        self.select_files()
        self.root.report_callback_exception = lambda *exc: self.callback_errors.append(exc)
        self.app.open_history()
        self.window = self.app.history_window
        self.pump(lambda: not self.window.lanes["sheets"].active)

    def tearDown(self):
        self.assertEqual(self.callback_errors, [])
        super().tearDown()

    def pump(self, condition, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(0.01)
        self.fail("condition not reached")

    def settle(self, seconds=0.3):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.root.update(); time.sleep(0.01)

    def alive(self, kind):
        return sum(t.is_alive() and t.name == f"m4a-history-{kind}" for t in threading.enumerate())

    def test_rapid_searches_and_queries_stay_bounded(self):
        searches, queries = Gate(history.search_materials), Gate(history.material_history)
        window, limit = self.window, self.window.lanes["query"].LIMIT
        with patch.object(history, "search_materials", side_effect=searches), \
                patch.object(history, "material_history", side_effect=queries):
            window.selected_key = "A"
            for i in range(30):
                window.search_text.set("A" if i == 29 else f"ZZ{i}"); window.search()
                window.days.set((30, 90, 60)[i % 3]); window.query(auto=True)
                self.root.update()
            for kind in ("search", "query"):
                lane = window.lanes[kind]
                self.assertEqual((lane.started, len(lane.active)), (limit, limit))
                self.assertLessEqual(self.alive(kind), limit)
                self.assertIsNotNone(lane.pending)
            self.assertEqual((len(searches.calls), len(queries.calls)), (limit, limit))
            searches.release.set(); queries.release.set()
            self.pump(lambda: window.result is not None and window.candidates)
            self.settle()
        for kind in ("search", "query"):  # only the newest pending request ran after the two held ones
            lane = window.lanes[kind]
            self.assertEqual((lane.started, lane.active, lane.pending), (limit + 1, [], None))
        self.assertEqual([c.key for c in window.candidates][:1], ["A"])
        self.assertEqual((window.result.material_key, window.result.coverage.days), ("A", 60))
        self.assertEqual(searches.calls[-1][1], "A")
        self.assertEqual(queries.calls[-1][1:3], ("A", 60))

    def test_newer_selection_replaces_the_pending_one_and_owns_the_result(self):
        queries = Gate(history.material_history)
        window = self.window
        with patch.object(history, "material_history", side_effect=queries):
            for key in ("A", "B", "C", "B"):  # A and the first B are held; C waits and is then replaced by B
                window.select(key)
                self.root.update()
            self.assertEqual(window.lanes["query"].pending[0], window.query_gen)
            self.assertIn("Querying", window.coverage.get("1.0", "end"))
            self.assertIsNone(window.result)  # the earlier selections never show a result
            queries.release.set()
            self.pump(lambda: window.result is not None)
            self.settle()
        self.assertEqual([call[1] for call in queries.calls], ["A", "B", "B"])  # C never ran
        self.assertEqual(window.result.material_key, "B")
        self.assertEqual(window.selected_label.cget("text"), "Selected: B")
        self.assertEqual(window.trees["records"].item("0", "values")[1], "B")

    def test_a_superseded_real_query_stops_cooperatively(self):
        cancel = threading.Event()
        with patch.object(history, "_checkpoint", side_effect=lambda stage: cancel.set()):
            with history.cancellable(cancel), self.assertRaises(history.HistoryCancelled):
                history.material_history(self.db, "A", 30)  # cancelled between statements, no partial result
        long_count = ("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 200000000)"
                      " SELECT count(*) FROM n")
        cancel = threading.Event()
        threading.Timer(0.2, cancel.set).start()
        began = time.monotonic()
        with history.cancellable(cancel), self.assertRaises(history.HistoryCancelled):
            with history.read_view(self.db) as conn:
                conn.execute(long_count).fetchone()  # interrupted inside one statement
        self.assertLess(time.monotonic() - began, 5)
        self.assertEqual(history.material_history(self.db, "A", 30).material_key, "A")  # outside: unchanged

    def test_closing_during_queries_starts_nothing_and_applies_nothing(self):
        queries = Gate(history.material_history)
        window = self.window
        with patch.object(history, "material_history", side_effect=queries):
            for key in ("A", "B", "C"):
                window.select(key)
                self.root.update()
            lane = window.lanes["query"]
            held = list(lane.active)
            window.close()
            self.assertIsNone(self.app.history_window)
            self.assertIsNone(lane.pending)
            self.assertTrue(all(event.is_set() for event in held))
            window.query(); window.search()  # after closing: no new work
            queries.release.set()
            deadline = time.monotonic() + 10
            while window.events.qsize() < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.settle()
        self.assertEqual([call[1] for call in queries.calls], ["A", "B"])  # the pending C never started
        self.assertEqual(lane.started, 2)
        self.assertEqual(window.events.qsize(), 2)  # late responses were never applied to destroyed widgets
        self.assertEqual(self.alive("query"), 0)

    def test_failures_recover_on_the_next_request(self):
        window, real = self.window, history.search_materials
        failing = [HistoryReadError("synthetic database is locked")]

        def search(*args):
            if failing:
                raise failing.pop()
            return real(*args)
        with patch.object(history, "search_materials", side_effect=search):
            window.search_text.set("A"); window.search()
            self.pump(lambda: "Search failed" in window.candidate_note.cget("text"))
            window.search()
            self.pump(lambda: window.candidates)
        with patch.object(history, "material_history", side_effect=HistoryReadError("synthetic database is locked")):
            window.select("A")
            self.pump(lambda: "Query failed" in window.status.get())
        self.assertIn("QUERY FAILED", window.coverage.get("1.0", "end"))
        window.query()
        self.pump(lambda: window.result is not None)
        self.assertEqual(window.result.material_key, "A")
        self.assertNotIn("QUERY FAILED", window.coverage.get("1.0", "end"))
        self.assertEqual(window.lanes["query"].active, [])
