"""M4A Inventory History: synthetic workbooks and temporary SQLite only (TemporaryDirectory via tests.test_m31.Base)."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import threading
import time
import tkinter as tk
from unittest.mock import patch

from checker import history, history_ui, retention
from checker.history import ABSENT, NOT_RETAINED, RECORD, HistoryReadError, material_history, search_materials
from checker.inventory_db import parse_stamp
from checker.sync import CLOUD_NOT_VERIFIED, IMPORTED, InventorySync
from tests.fixtures import workbook, stock_rows
from tests.test_m31 import Base, UiBase, digest

UTC = timezone.utc


class HistoryBase(Base):
    def publish(self, entries, when, sheets=None, path=None):
        self.clock.now = when
        target = Path(path) if path else self.stock
        workbook(target, sheets or [('Stock', stock_rows(entries))])
        result = self.inv.sync_role('stock', str(target), 'manual')
        self.assertEqual(result.outcome, IMPORTED, result.error)
        return result

    def stamps(self):
        return [r[0] for r in self.query('SELECT observed_at FROM inventory_snapshots ORDER BY id')]

    def history(self, key, days=30, sheet=None, now=None, **kw):
        return material_history(self.db, key, days, sheet, now=now or self.clock.now, **kw)


class HistoryQueryTests(HistoryBase):
    def test_normal_records_and_quantity_change_with_source_details(self):
        self.publish([('A', 100), ('B', 5)], datetime(2026, 9, 1, 8, tzinfo=UTC))
        self.publish([('A', 90), ('B', 5)], datetime(2026, 9, 10, 8, tzinfo=UTC))
        first, second = self.stamps()
        result = self.history('a', 30, now=datetime(2026, 9, 20, tzinfo=UTC))
        self.assertEqual(result.material_key, 'A')
        self.assertEqual([r.kind for r in result.rows], [RECORD, RECORD])
        newest, oldest = result.rows
        self.assertEqual((newest.observed_at, newest.value, newest.quantity, newest.status), (second, '90', 90, 'VALID'))
        self.assertEqual((oldest.observed_at, oldest.value), (first, '100'))
        self.assertEqual((newest.sheet, newest.row_no, newest.code, newest.description, newest.rack, newest.level),
                         ('Stock', 15, 'A', 'Fixture material', 1, 2))
        self.assertEqual(Path(newest.source_path).name, 'storage.xlsx')
        self.assertNotEqual(newest.version_id, oldest.version_id)
        self.assertEqual(len(result.changes), 1)
        change = result.changes[0]
        self.assertEqual((change.change_type, change.difference, change.before_at, change.after_at),
                         ('QUANTITY_CHANGED', '-10', first, second))
        self.assertFalse(change.source_switched)
        self.assertIn('not consumption', change.note)
        self.assertFalse(result.coverage.covers_full_window)
        self.assertTrue(any('History starts' in n for n in result.coverage.notes))

    def test_blank_text_and_invalid_quantities_are_shown_as_read(self):
        dates = [datetime(2026, 9, d, 8, tzinfo=UTC) for d in (1, 2, 3, 4)]
        for qty, when in zip((5, None, 'abc', '0+10'), dates):
            self.publish([('A', qty)], when)
        rows = self.history('A', now=datetime(2026, 9, 5, tzinfo=UTC)).rows
        self.assertEqual([(r.status, r.value, r.quantity) for r in rows],
                         [('INVALID', None, '0+10'), ('INVALID', None, 'abc'), ('BLANK', None, None), ('VALID', '5', 5)])
        values = [history_ui.HistoryWindow._record_values(r)[0] for r in rows]
        self.assertEqual([v[3] for v in values], ['0+10', 'abc', '(blank)', '5'])
        self.assertEqual(values[2][4], 'BLANK — not 0')
        self.assertEqual(values[1][4], 'INVALID — not converted')
        changes = self.history('A', now=datetime(2026, 9, 5, tzinfo=UTC)).changes
        self.assertTrue(changes)
        self.assertTrue(all(c.difference is None for c in changes))
        self.assertEqual({c.change_type for c in changes}, {'VALIDITY_CHANGED'})

    def test_duplicates_are_separate_rows_never_added(self):
        self.publish([('D', 1), ('D', 2)], datetime(2026, 9, 1, tzinfo=UTC))
        self.publish([('D', 1), ('D', 3)], datetime(2026, 9, 2, tzinfo=UTC))
        result = self.history('D', now=datetime(2026, 9, 3, tzinfo=UTC))
        self.assertEqual([(r.value, r.duplicates) for r in result.rows], [('1', 2), ('3', 2), ('1', 2), ('2', 2)])
        self.assertNotIn('4', [r.value for r in result.rows])
        self.assertNotIn('3', [r.value for r in result.rows[2:]])
        self.assertIn('not added', result.rows[0].note)
        self.assertEqual([(c.change_type, c.difference) for c in result.changes], [('DUPLICATE_CHANGED', None)])
        self.assertIn('DUPLICATE: 1 | 3', history_ui.side_text(result.changes[0].after_status, result.changes[0].after_raw))

    def test_sheets_are_isolated_and_filterable(self):
        sheets = lambda a, b: [('Stock', stock_rows([('A', a)])), ('Stock B', stock_rows([('A', b)]))]
        self.publish(None, datetime(2026, 9, 1, tzinfo=UTC), sheets=sheets(10, 50))
        self.publish(None, datetime(2026, 9, 2, tzinfo=UTC), sheets=sheets(12, 50))
        now = datetime(2026, 9, 3, tzinfo=UTC)
        both = self.history('A', now=now)
        self.assertEqual([(r.sheet, r.value) for r in both.rows], [('Stock', '12'), ('Stock B', '50'),
                                                                  ('Stock', '10'), ('Stock B', '50')])
        self.assertTrue(all(r.duplicates == 1 for r in both.rows))  # same ID in two Sheets is not a duplicate
        only_b = self.history('A', sheet='Stock B', now=now)
        self.assertEqual([(r.sheet, r.value) for r in only_b.rows], [('Stock B', '50'), ('Stock B', '50')])
        self.assertEqual(only_b.changes, ())
        self.assertEqual([(c.sheet, c.difference) for c in self.history('A', sheet='Stock', now=now).changes],
                         [('Stock', '2')])
        self.assertEqual(history.list_sheets(self.db), ['Stock', 'Stock B'])
        missing = self.history('A', sheet='Gone', now=now)
        self.assertEqual({r.kind for r in missing.rows}, {ABSENT})
        self.assertIn('not in this Storage version', missing.rows[0].note)

    def test_source_switch_is_never_a_comparable_difference(self):
        self.publish([('A', 100)], datetime(2026, 9, 1, tzinfo=UTC))
        other = self.stock.parent / 'other_storage.xlsx'
        self.publish([('A', 80)], datetime(2026, 9, 2, tzinfo=UTC), path=other)
        result = self.history('A', now=datetime(2026, 9, 3, tzinfo=UTC))
        self.assertEqual([Path(r.source_path).name for r in result.rows], ['other_storage.xlsx', 'storage.xlsx'])
        change = result.changes[0]
        self.assertEqual(change.change_type, 'QUANTITY_CHANGED')
        self.assertTrue(change.source_switched)
        self.assertIsNone(change.difference)
        self.assertIn('not comparable', change.note)
        self.assertEqual(history_ui.HistoryWindow._change_values(change)[0][6], 'not comparable (source switch)')
        self.assertEqual(len(result.coverage.source_switches), 1)
        self.assertTrue(any('switched' in n for n in result.coverage.notes))

    def test_30_60_90_day_boundaries_are_inclusive(self):
        self.publish([('A', 1)], datetime(2026, 5, 1, tzinfo=UTC))
        self.publish([('A', 2)], datetime(2026, 6, 1, tzinfo=UTC))
        observed = parse_stamp(self.stamps()[1])
        for days in history.RANGES:
            with self.subTest(days=days):
                edge = self.history('A', days, now=observed + timedelta(days=days))
                self.assertEqual([(r.reference, r.value) for r in edge.rows], [(False, '2'), (True, '1')])
                self.assertEqual(len(edge.changes), 1)
                outside = self.history('A', days, now=observed + timedelta(days=days, milliseconds=1))
                self.assertEqual([(r.reference, r.value) for r in outside.rows], [(True, '2')])
                self.assertEqual(outside.changes, ())
                self.assertEqual(outside.coverage.snapshots_in_window, 0)
                self.assertTrue(any('No Storage version was synchronised' in n for n in outside.coverage.notes))
        with self.assertRaises(history.HistoryError):
            self.history('A', 45)

    def test_empty_database_and_unknown_material_invent_nothing(self):
        empty = self.history('A')
        self.assertEqual((empty.rows, empty.changes), ((), ()))
        self.assertIn('No Storage history', empty.coverage.notes[0])
        self.publish([('A', 1)], datetime(2026, 9, 1, tzinfo=UTC))
        unknown = self.history('ZZZ', now=datetime(2026, 9, 2, tzinfo=UTC))
        self.assertEqual([(r.kind, r.value, r.quantity) for r in unknown.rows], [(ABSENT, None, None)])
        self.assertIn('not 0', unknown.rows[0].note)
        self.assertEqual(search_materials(self.db, 'ZZZ'), ([], False))

    def test_cleanup_boundary_and_removed_payload_are_reported_not_filled(self):
        for date, qty in (((2024, 7, 1), 100), ((2025, 7, 1), 99), ((2025, 10, 1), 98), ((2025, 11, 1), 97)):
            self.publish([('A', qty)], datetime(*date, tzinfo=UTC))
        now = datetime(2026, 10, 21, 12, tzinfo=UTC)
        service = retention.RetentionService(self.db)
        service.apply(service.preview(now))
        retained_from = self.query("SELECT value FROM schema_info WHERE key='history_retained_from'")[0][0]
        result = self.history('A', 90, now=datetime(2025, 12, 1, tzinfo=UTC))
        self.assertEqual(result.coverage.retained_from, retained_from)
        self.assertFalse(result.coverage.covers_full_window)
        self.assertTrue(any('Local History maintenance removed' in n for n in result.coverage.notes))
        self.assertEqual([r.value for r in result.rows], ['97', '98'])
        # The removed 2025-07-01 snapshot would have been the 'Before window' row; it is not reconstructed.
        self.assertFalse(any(r.reference for r in result.rows))
        self.assertIsNone(result.coverage.reference_at)
        # A snapshot whose Storage rows are no longer stored is "unknown", never absent or 0.
        version = self.query('SELECT source_version_id FROM inventory_snapshots ORDER BY id DESC LIMIT 1')[0][0]
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('DELETE FROM stock_records WHERE source_version_id = ?', (version,)); conn.commit()
        rows = self.history('A', 90, now=datetime(2025, 12, 1, tzinfo=UTC)).rows
        self.assertEqual((rows[0].kind, rows[0].value, rows[0].quantity), (NOT_RETAINED, None, None))
        self.assertIn('unknown', rows[0].note)

    def test_unavailable_foreign_or_corrupt_database_is_refused_and_never_created(self):
        missing = self.base / 'nowhere' / 'inventory.db'
        for call in (lambda p: material_history(p, 'A', 30), lambda p: search_materials(p, 'A'),
                     lambda p: history.list_sheets(p)):
            with self.assertRaises(HistoryReadError):
                call(missing)
        self.assertFalse(missing.exists())
        garbage = self.base / 'garbage.db'; garbage.write_bytes(b'not a database' * 100)
        foreign = self.base / 'foreign.db'
        with closing(sqlite3.connect(foreign)) as conn:
            conn.execute('CREATE TABLE x (y)'); conn.commit()
        for path in (garbage, foreign):
            before = digest(path)
            with self.assertRaises(HistoryReadError):
                material_history(path, 'A', 30)
            self.assertEqual(digest(path), before)

    def test_search_is_partial_exact_first_and_never_merges_similar_ids(self):
        self.publish([('A-1', 1), ('A-10', 2), ('XA-1', 3), ('A_1', 4), ('A%1', 5)], datetime(2026, 9, 1, tzinfo=UTC))
        found, more = search_materials(self.db, ' a-1 ')
        self.assertEqual([c.key for c in found], ['A-1', 'A-10', 'XA-1'])
        self.assertFalse(more)
        self.assertEqual([c.description for c in found], ['Fixture material'] * 3)
        self.assertEqual([c.key for c in search_materials(self.db, '_')[0]], ['A_1'])
        self.assertEqual([c.key for c in search_materials(self.db, '%')[0]], ['A%1'])
        self.assertEqual(search_materials(self.db, 'A', limit=2)[1], True)
        rows = self.history('A-1', now=datetime(2026, 9, 2, tzinfo=UTC)).rows
        self.assertEqual([(r.code, r.value) for r in rows], [('A-1', '1')])  # A-10 / XA-1 are not merged in

    def test_numeric_cell_ids_are_not_searchable_keys(self):
        self.publish([('A', 1), (51102, 4)], datetime(2026, 9, 1, tzinfo=UTC))
        self.assertEqual(search_materials(self.db, '51102'), ([], False))

    def test_cap_reports_totals_instead_of_silently_dropping(self):
        self.publish([('A', i) for i in range(1, 8)], datetime(2026, 9, 1, tzinfo=UTC))
        result = self.history('A', now=datetime(2026, 9, 2, tzinfo=UTC), max_rows=5)
        self.assertEqual((len(result.rows), result.total_rows), (5, 7))
        self.assertTrue(result.truncated)

    def test_queries_never_write_database_or_workbooks(self):
        self.publish([('A', 1)], datetime(2026, 9, 1, tzinfo=UTC))
        before = digest(self.db), digest(self.stock)
        self.history('A'); search_materials(self.db, 'A'); history.list_sheets(self.db)
        self.assertEqual((digest(self.db), digest(self.stock)), before)

    def test_one_consistent_view_while_another_program_publishes(self):
        self.publish([('A', 100)], datetime(2026, 9, 1, tzinfo=UTC))
        other = InventorySync(self.db, settle_seconds=0, clock=lambda: datetime(2026, 9, 2, tzinfo=UTC))
        workbook(self.stock, [('Stock', stock_rows([('A', 50)]))])
        outcome, seen = {}, {}

        def publish():
            outcome['result'] = other.sync_role('stock', str(self.stock), 'manual')

        writer = threading.Thread(target=publish)

        def checkpoint(stage):
            if stage == 'snapshots':
                writer.start(); time.sleep(0.6)  # the other program reads, parses and tries to commit meanwhile
            if stage == 'records':
                seen['writer_waiting'] = writer.is_alive()
        with patch.object(history, '_checkpoint', side_effect=checkpoint):
            result = self.history('A', now=datetime(2026, 9, 3, tzinfo=UTC))
        writer.join(30)
        self.assertTrue(seen['writer_waiting'], 'the other program should still be waiting to commit')
        self.assertEqual([r.value for r in result.rows], ['100'])  # only the state when the view began
        self.assertEqual(result.changes, ())
        self.assertEqual(outcome['result'].outcome, IMPORTED, outcome['result'].error)
        after = self.history('A', now=datetime(2026, 9, 3, tzinfo=UTC))
        self.assertEqual([r.value for r in after.rows], ['50', '100'])
        self.assertEqual([c.difference for c in after.changes], ['-50'])


class HistoryWindowTests(UiBase):
    def setUp(self):
        super().setUp()
        self.callback_errors = []
        self.start_app()
        self.select_files()
        self.root.report_callback_exception = lambda *exc: self.callback_errors.append(exc)
        self.app.open_history()
        self.window = self.app.history_window

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
        self.fail('condition not reached')

    def choose(self, text='a', key='A'):
        self.window.search_text.set(text); self.window.search()
        self.pump(lambda: self.window.candidates)
        index = [c.key for c in self.window.candidates].index(key)
        self.window.candidate_list.selection_set(index); self.window._picked()

    def texts(self, widget):
        found = []
        for child in widget.winfo_children():
            for option in ('text',):
                try:
                    found.append(str(child.cget(option)))
                except tk.TclError:
                    pass
            found.extend(self.texts(child))
        return found

    def test_query_flow_and_permanent_historical_labels(self):
        before = digest(self.db), digest(self.stock), digest(self.bom)
        self.choose()
        self.pump(lambda: self.window.result is not None)
        tree = self.window.trees['records']
        self.assertEqual(len(tree.get_children()), 1)
        self.assertEqual(tree.item('0', 'values')[3], '100')
        self.assertIn(history.HISTORICAL, self.window.banner.cget('text'))
        self.assertIn(CLOUD_NOT_VERIFIED, self.window.banner.cget('text'))
        self.assertIn(CLOUD_NOT_VERIFIED, self.window.status.get())
        self.assertIn('Observed Change ≠ Actual Consumption', self.window.caveats.cget('text'))
        everything = ' '.join(self.texts(self.window.top)) + self.window.status.get() + \
            self.window.coverage.get('1.0', 'end')
        self.assertNotIn('Local Sources Verified', everything)
        self.assertEqual((digest(self.db), digest(self.stock), digest(self.bom)), before)
        self.assertIsNone(self.app.result)  # the CHECK workflow is untouched
        self.app.open_history()
        self.assertIs(self.app.history_window, self.window)  # one window, brought forward

    def test_typing_alone_does_not_query_and_selection_is_exact(self):
        self.window.search_text.set('A'); self.window.search()
        self.pump(lambda: self.window.candidates)
        self.root.update()
        self.assertIsNone(self.window.selected_key)
        self.assertIsNone(self.window.result)
        self.window.query()
        self.assertIn('Select a Material ID', self.window.status.get())

    def test_older_query_cannot_overwrite_newer_result(self):
        gate, real = threading.Event(), history.material_history

        def slow(db, key, days, sheet):
            if days == 30:
                gate.wait(10)
            return real(db, key, days, sheet)
        with patch.object(history, 'material_history', side_effect=slow):
            self.choose()                        # 30 days: held back
            self.window.days.set(90); self.window.query(auto=True)
            self.pump(lambda: self.window.result is not None)
            self.assertEqual(self.window.result.coverage.days, 90)
            gate.set()
            end = time.monotonic() + 0.5
            while time.monotonic() < end:
                self.root.update(); time.sleep(0.01)
        self.assertEqual(self.window.result.coverage.days, 90)

    def test_closing_during_query_never_touches_destroyed_widgets(self):
        gate, real, finished = threading.Event(), history.material_history, threading.Event()

        def slow(*args):
            gate.wait(10)
            try:
                return real(*args)
            finally:
                finished.set()
        with patch.object(history, 'material_history', side_effect=slow):
            self.choose()
            self.window.close()
            self.assertIsNone(self.app.history_window)
            gate.set(); finished.wait(10)
            end = time.monotonic() + 0.3
            while time.monotonic() < end:
                self.root.update(); time.sleep(0.01)
        self.assertTrue(self.window.closed)
        self.assertFalse(self.window.events.empty())  # the late response was never applied

    def test_database_failure_clears_previous_result(self):
        self.choose()
        self.pump(lambda: self.window.result is not None)
        with patch.object(history, 'material_history', side_effect=HistoryReadError('database is locked')):
            self.window.query()
            self.pump(lambda: 'Query failed' in self.window.status.get())
        self.assertIsNone(self.window.result)
        self.assertEqual(self.window.trees['records'].get_children(), ())
        self.assertIn('QUERY FAILED', self.window.coverage.get('1.0', 'end'))
        self.assertIn(CLOUD_NOT_VERIFIED, self.window.status.get())

    def test_rows_render_in_batches(self):
        self.write_stock([('A', i) for i in range(450)])
        self.sync('stock')
        self.choose()
        self.pump(lambda: self.window.result is not None)
        tree, button = self.window.trees['records'], self.window.more_buttons['records']
        self.assertEqual(len(tree.get_children()), history_ui.PAGE)
        self.assertTrue(button.winfo_manager())
        button.invoke(); button.invoke()
        self.assertEqual(len(tree.get_children()), self.window.result.total_rows)
        self.assertFalse(button.winfo_manager())

    def test_main_app_close_closes_history(self):
        self.app.close()
        self.assertTrue(self.window.closed)

    def test_small_windows_keep_controls_and_tables_usable(self):
        # Tk keeps `tk scaling` per process and fonts take it when they are created, so each scale builds a fresh
        # window after setting it (otherwise the result would depend on which test ran before).
        for scale in (1, 1.25, 1.5):
            self.window.close()
            self.root.tk.call('tk', 'scaling', 96 / 72 * scale)
            self.app.open_history()
            self.window = self.app.history_window
            self.choose()
            self.pump(lambda: self.window.result is not None)
            top = self.window.top
            self.pump(top.winfo_viewable)  # under load the window manager may map a new Toplevel late
            for width, height in ((960, 600), (1280, 720)):
                with self.subTest(size=(width, height), scale=scale):
                    top.geometry(f'{width}x{height}')
                    for _ in range(3):  # the compact/expanded fit settles after one more layout pass
                        top.update()
                    for name in ('records', 'changes'):
                        tree = self.window.trees[name]
                        self.window.tabs.select(0 if name == 'records' else 1)
                        self.pump(lambda: tree.winfo_ismapped() and tree.winfo_height() > 1)  # tab laid out
                        self.assertGreater(tree.winfo_height(), 60)
                        # Columns scroll sideways; they are never squeezed (Data Status stays readable).
                        for column in tree['columns']:
                            self.assertGreaterEqual(int(tree.column(column, 'width')),
                                                    int(tree.column(column, 'minwidth')), column)
                    status = self.window.trees['records'].column('status', 'width')
                    self.assertGreaterEqual(int(status), 230)
                    for widget in (self.window.banner, self.window.caveats, self.window.search_entry,
                                   self.window.query_button, self.window.sheet_combo, self.window.range_buttons[90],
                                   self.window.coverage, self.window.status_label):
                        self.assertTrue(widget.winfo_ismapped(), widget)
                        self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                             top.winfo_rooty() + top.winfo_height())
                        self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                             top.winfo_rootx() + top.winfo_width())

    def test_entry_button_fits_main_window(self):
        self.root.deiconify()
        for width, height, scale in ((960, 600, 1), (1280, 720, 1), (960, 600, 1.5), (1280, 720, 1.5)):
            with self.subTest(size=(width, height), scale=scale):
                self.root.tk.call('tk', 'scaling', 96 / 72 * scale)
                self.root.geometry(f'{width}x{height}')
                # B1: each entry is on its navigation page (Materials & history, Settings, shortage check).
                for page, button in (('materials', self.app.history_button), ('settings', self.app.maintenance_button),
                                     ('check', self.app.cache_button)):
                    self.app.show_page(page)
                    self.root.update(); self.app._resize(); self.root.update()
                    self.assertTrue(button.winfo_ismapped())
                    self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                         self.root.winfo_rootx() + self.root.winfo_width())
                self.assertGreater(self.app.tree.winfo_height(), 60)
                self.assert_cloud_notice(self.app)
