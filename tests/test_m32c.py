"""M3.2C thresholds, schema upgrade and stock alerts. Synthetic workbooks and temporary SQLite only."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import threading
import time
from unittest.mock import patch

from checker import alerts, cached, history, retention, upgrade
from checker.alerts import (DATA_ISSUE, LOW_STOCK, NOT_CONFIGURED, NOT_IN_MASTER, OUT_OF_STOCK, AlertService,
                            AlertRunner, load_state)
from checker.core import check_materials
from checker.inventory_db import SCHEMA, SCHEMA_VERSION, initialise, stamp
from checker.queries import load_workbook_data, open_readonly
from checker.reader import ReadOnlyCache
from checker.sync import IMPORTED, UNCHANGED, InventorySync
from tests.fixtures import bom_rows, stock_rows, workbook
from tests.test_m31 import Base, UiBase, digest


def stock_with_threshold(entries, header='MIIN QTY', column='P', extra_headers=None):
    """entries: (code, LIVE STOCK, threshold or None for a blank cell)."""
    rows = stock_rows([(code, qty) for code, qty, _ in entries])
    rows[13][column] = header
    for n, (_code, _qty, threshold) in enumerate(entries, 15):
        if threshold is not None:
            rows[n][column] = threshold
    for col, text in (extra_headers or {}).items():
        rows[13][col] = text
    return rows


def make_schema_1(path):
    """A database exactly as the schema-1 releases created it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(f"BEGIN;\n{SCHEMA}\nPRAGMA user_version = 1;\nCOMMIT;")
        conn.executemany("INSERT INTO schema_info VALUES (?, ?)", (('schema_version', '1'), ('created_at', 'x'),
                                                                  ('created_by', 'test')))
        conn.commit()


def schema_sql(path):
    with closing(sqlite3.connect(path)) as conn:
        return sorted(conn.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))


def logical(path):
    with closing(open_readonly(path)) as conn:
        return retention._digest(conn)


def authorize(db, generation=0):
    """The Authorization a session would hold after its own successful syncs of the current files."""
    with closing(open_readonly(db)) as conn:
        sources = []
        for role in ('stock', 'bom'):
            run = conn.execute("SELECT source_version_id, source_path FROM sync_runs WHERE role = ? AND outcome IN"
                               " ('IMPORTED', 'UNCHANGED') ORDER BY id DESC LIMIT 1", (role,)).fetchone()
            sources.append((role, run[0], run[1]))
    return alerts.Authorization(generation, tuple(sources))


MIXED = [('A', 0, None), ('B', 3, 5), ('C', 5, 5), ('D', 0, 0), ('E', None, 2), ('F', 'abc', 1), ('G', 10, 'x'),
         ('H', 1, 4), ('H', 2, 4), (51102, 4, 1), ('J', 7, -1), ('K', 2, ('f', 'O15*2'))]


class ThresholdReaderTests(Base):
    def test_miin_qty_and_min_qty_are_the_only_recognised_headers(self):
        for header in ('MIIN QTY', 'MIN QTY', ' miin qty '):
            with self.subTest(header=header):
                workbook(self.stock, [('Stock', stock_with_threshold([('A', 1, 5), ('B', 2, None)], header))])
                sheet = ReadOnlyCache().read(str(self.stock), 'stock').stock_sheets[0]
                self.assertEqual((sheet.threshold_state, sheet.threshold_column, sheet.threshold_header),
                                 ('FOUND', 'P', header))  # original spelling kept
                self.assertEqual([(m.threshold, m.threshold_type) for m in sheet.materials], [(5, 'n'), (None, 'n')])
        for header in ('MIN. QTY', 'MINIMUM QTY', 'MIN  QTY', 'MINQTY', 'MIN QTY (PCS)'):
            with self.subTest(header=header):
                workbook(self.stock, [('Stock', stock_with_threshold([('A', 1, 5)], header))])
                sheet = ReadOnlyCache().read(str(self.stock), 'stock').stock_sheets[0]
                self.assertEqual(sheet.threshold_state, 'NOT_FOUND')
                self.assertIsNone(sheet.materials[0].threshold)

    def test_several_candidates_are_never_chosen_automatically(self):
        workbook(self.stock, [('Stock', stock_with_threshold([('A', 1, 5)], 'MIIN QTY', 'P', {'R': 'MIN QTY'}))])
        book = ReadOnlyCache().read(str(self.stock), 'stock')
        sheet = book.stock_sheets[0]
        self.assertEqual(sheet.threshold_state, 'AMBIGUOUS')
        self.assertEqual(sheet.threshold_candidates, (('P', 'MIIN QTY'), ('R', 'MIN QTY')))
        self.assertIsNone(sheet.materials[0].threshold)
        self.assertTrue(any('多个最低库存候选列' in note for note in book.notes))

    def test_m2_check_is_identical_with_and_without_a_threshold_column(self):
        entries = [('A', 100, 5), ('B', 0, 3), ('C', None, None), ('D', 1, 0), ('D', 2, 0)]
        self.write_bom([('A', 2), ('B', 1), ('C', 1), ('D', 1), ('Z', 1)])
        bom = ReadOnlyCache().read(str(self.bom), 'bom').products[0]
        workbook(self.stock, [('Stock', stock_rows([(c, q) for c, q, _ in entries]))])
        plain = check_materials(bom, ReadOnlyCache().read(str(self.stock), 'stock').stock_sheets[0], 3)
        workbook(self.stock, [('Stock', stock_with_threshold(entries))])
        with_threshold = check_materials(bom, ReadOnlyCache().read(str(self.stock), 'stock').stock_sheets[0], 3)
        strip = lambda result: [(r.bom.code, r.category, r.data_status, r.required, r.stock_used, r.shortage,
                                 r.exceptions) for r in result.sorted_rows]
        self.assertEqual(strip(with_threshold), strip(plain))  # ASSUMED 0 and every M2 class unchanged

    def test_excel_and_database_reconstruction_stay_identical(self):
        workbook(self.stock, [('Stock', stock_with_threshold(MIXED))])
        self.sync()
        excel = ReadOnlyCache().read(str(self.stock), 'stock')
        with closing(open_readonly(self.db)) as conn:
            database = load_workbook_data(conn, 'stock')
        self.assertEqual(database.stock_sheets, excel.stock_sheets)


class SchemaUpgradeTests(Base):
    def setUp(self):
        super().setUp()
        self.legacy = self.base / 'legacy' / 'inventory.db'
        make_schema_1(self.legacy)
        self.old = InventorySync(self.legacy, settle_seconds=0, clock=self.clock)
        workbook(self.stock, [('Stock', stock_with_threshold([('A', 0, 5), ('B', 3, 5)]))])
        self.assertEqual(self.old.sync_role('stock', str(self.stock), 'manual').outcome, IMPORTED)
        self.assertEqual(self.old.sync_role('bom', str(self.bom), 'manual').outcome, IMPORTED)

    def version(self, path):
        with closing(sqlite3.connect(path)) as conn:
            return conn.execute('PRAGMA user_version').fetchone()[0]

    def test_new_databases_are_schema_2_and_schema_1_is_never_migrated_automatically(self):
        self.assertEqual(self.version(self.db), SCHEMA_VERSION)
        before = digest(self.legacy)
        initialise(self.legacy)
        InventorySync(self.legacy, settle_seconds=0)
        self.assertEqual(self.version(self.legacy), 1)
        self.assertEqual(digest(self.legacy), before)
        # Every existing function keeps working on schema 1.
        self.assertEqual(self.old.sync_role('stock', str(self.stock), 'manual').outcome, UNCHANGED)
        self.assertEqual(history.material_history(self.legacy, 'A', 30, now=self.clock.now).rows[0].value, '0')
        with closing(open_readonly(self.legacy)) as conn:
            self.assertEqual(load_workbook_data(conn, 'stock').stock_sheets[0].threshold_state, 'NOT_CAPTURED')
        cached.load(self.legacy)
        retention.RetentionService(self.legacy).preview()
        with self.assertRaises(alerts.AlertUnavailable):
            AlertService(self.legacy).run('test', None)
        self.assertEqual(load_state(self.legacy).schema, 1)

    def test_preview_is_read_only_and_apply_backs_up_then_adds_only(self):
        before, before_logical = digest(self.legacy), logical(self.legacy)
        plan = upgrade.preview(self.legacy)
        self.assertEqual(digest(self.legacy), before)
        self.assertFalse((self.legacy.parent / 'backups').exists())
        self.assertIn('Schema 1 → 3', plan.describe())
        with closing(sqlite3.connect(self.legacy)) as conn:
            rows_before = {t: conn.execute(f'SELECT * FROM {t} ORDER BY rowid').fetchall() for t in
                           ('source_versions', 'stock_sheets', 'stock_records', 'sync_runs', 'inventory_snapshots')}
        backup = Path(upgrade.apply(plan))
        self.assertEqual(self.version(self.legacy), 3)
        self.assertEqual(backup.parent, self.legacy.parent / 'backups')
        self.assertEqual(logical(backup), before_logical)  # the backup is the pre-upgrade database
        with closing(sqlite3.connect(backup)) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 1)
        with closing(sqlite3.connect(self.legacy)) as conn:
            for table, old in rows_before.items():  # existing rows unchanged; new columns empty
                new = conn.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
                self.assertEqual([row[:len(old[0])] for row in new], old, table)
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(conn.execute('SELECT count(*) FROM stock_sheets WHERE threshold_state IS NOT NULL')
                             .fetchone()[0], 0)
        self.assertEqual(schema_sql(self.legacy), schema_sql(self.db))  # same schema as a new database
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.preview(self.legacy)  # already upgraded

    def test_refused_or_failed_upgrade_leaves_schema_1_intact(self):
        plan = upgrade.preview(self.legacy)
        self.old.sync_role('stock', str(self.bom), 'manual')  # another attempt is recorded after the preview
        before = logical(self.legacy)
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.apply(plan)
        self.assertEqual((self.version(self.legacy), logical(self.legacy)), (1, before))
        plan = upgrade.preview(self.legacy)
        with patch.object(upgrade, '_checkpoint', side_effect=lambda s: (_ for _ in ()).throw(OSError('disk'))
                          if s == 'before_commit' else None):
            with self.assertRaises(upgrade.UpgradeError) as caught:
                upgrade.apply(plan)
        self.assertIn('Backup file', str(caught.exception))
        self.assertEqual((self.version(self.legacy), logical(self.legacy)), (1, before))
        missing = self.base / 'missing' / 'inventory.db'
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.preview(missing)
        self.assertFalse(missing.exists())

    def test_thresholds_are_captured_once_from_the_same_file_version(self):
        upgrade.apply(upgrade.preview(self.legacy))
        self.old.sync_role('bom', str(self.bom), 'manual')
        with closing(open_readonly(self.legacy)) as conn:
            evaluation = alerts.evaluate(conn)
        self.assertEqual(evaluation.summary['sheets']['Stock']['threshold']['state'], 'NOT_CAPTURED')
        self.assertNotIn(LOW_STOCK, {a.alert_type for a in evaluation.alerts})
        cache = ReadOnlyCache()
        parse = lambda path, role: cache.read(path, role)
        result = self.old.sync_role('stock', str(self.stock), 'manual', parse=parse)
        self.assertEqual(result.outcome, UNCHANGED)
        self.assertEqual(cache.parse_count, 1)
        with closing(open_readonly(self.legacy)) as conn:
            sheet = load_workbook_data(conn, 'stock').stock_sheets[0]
            self.assertEqual((sheet.threshold_state, sheet.threshold_header), ('FOUND', 'MIIN QTY'))
            self.assertEqual([m.threshold for m in sheet.materials], [5, 5])
            self.assertEqual({a.alert_type for a in alerts.evaluate(conn).alerts}, {OUT_OF_STOCK, LOW_STOCK})
        before = logical(self.legacy)
        self.old.sync_role('stock', str(self.stock), 'manual', parse=parse)  # already captured: nothing rewritten
        with closing(open_readonly(self.legacy)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM stock_records WHERE threshold_kind IS NOT NULL')
                             .fetchone()[0], 2)

    def test_capture_refuses_a_different_row_layout(self):
        upgrade.apply(upgrade.preview(self.legacy))
        with closing(sqlite3.connect(self.legacy)) as conn:
            conn.execute('UPDATE stock_records SET row_no = row_no + 1'); conn.commit()
        self.old.sync_role('stock', str(self.stock), 'manual')
        with closing(open_readonly(self.legacy)) as conn:
            self.assertIsNone(conn.execute('SELECT threshold_state FROM stock_sheets').fetchone()[0])
            self.assertEqual(conn.execute('SELECT count(*) FROM stock_records WHERE threshold_cell_type IS NOT NULL')
                             .fetchone()[0], 0)

    def test_retention_and_cache_work_on_schema_2_with_alert_tables(self):
        upgrade.apply(upgrade.preview(self.legacy))
        self.old.sync_role('bom', str(self.bom), 'manual')
        AlertService(self.legacy, clock=self.clock).run('test', authorize(self.legacy))
        service = retention.RetentionService(self.legacy)
        plan = service.preview(self.clock.now + timedelta(days=800))
        before = logical(self.legacy)
        result = service.apply(plan)
        self.assertEqual(logical(result.backup), before)
        with closing(sqlite3.connect(self.legacy)) as conn:
            self.assertGreater(conn.execute('SELECT count(*) FROM stock_alerts').fetchone()[0], 0)
        cached.load(self.legacy)


class AlertEvaluationTests(Base):
    def setUp(self):
        super().setUp()
        workbook(self.stock, [('Stock', stock_with_threshold(MIXED))])
        workbook(self.bom, [('P1', bom_rows([('A', 1), ('X1', 2), ('h', 1)])),
                            ('P2', bom_rows([('X1', 5), ('Y', 1), ('B', 1)])),
                            ('P3', bom_rows([('X 1', 1), (99, 1)]))])
        self.sync(); self.sync('bom')
        self.service = AlertService(self.db, clock=self.clock)

    def evaluate(self):
        with closing(open_readonly(self.db)) as conn:
            return alerts.evaluate(conn)

    def by(self, evaluation):
        found = {}
        for a in evaluation.alerts:
            found.setdefault((a.alert_type, a.subtype), set()).add(a.material_key or f'row {a.row}')
        return found

    def test_alert_classification_rules(self):
        found = self.by(self.evaluate())
        self.assertEqual(found[(OUT_OF_STOCK, OUT_OF_STOCK)], {'A', 'D'})
        self.assertEqual(found[(LOW_STOCK, LOW_STOCK)], {'B'})            # C equal is not low; D 0/0 not low
        self.assertEqual(found[(NOT_CONFIGURED, NOT_CONFIGURED)], {'A'})  # blank threshold; OUT_OF_STOCK still shown
        self.assertEqual(found[(DATA_ISSUE, 'BLANK_STOCK')], {'E'})
        self.assertEqual(found[(DATA_ISSUE, 'INVALID_STOCK')], {'F'})
        self.assertEqual(found[(DATA_ISSUE, 'INVALID_THRESHOLD')], {'G', 'J', 'K'})  # text, negative, formula
        self.assertEqual(found[(DATA_ISSUE, 'DUPLICATE_STOCK_ID')], {'H'})
        self.assertEqual(found[(DATA_ISSUE, 'UNUSABLE_STOCK_ID')], {'row 24'})  # numeric-cell ID, never a key
        for key in ('C', 'E', 'F', 'H'):  # nothing else is inferred
            self.assertNotIn(key, found[(LOW_STOCK, LOW_STOCK)] | found[(OUT_OF_STOCK, OUT_OF_STOCK)])

    def test_raw_values_are_kept_and_zero_threshold_is_not_interpreted(self):
        alerts_ = {(a.alert_type, a.material_key): a for a in self.evaluate().alerts}
        d = alerts_[(OUT_OF_STOCK, 'D')].detail
        self.assertEqual((d['stock'], d['threshold'], d['threshold_status'], d['threshold_value']),
                         (['int', '0'], ['int', '0'], 'VALID', '0'))
        self.assertEqual(d['threshold_header'], 'MIIN QTY')
        self.assertEqual(alerts_[(DATA_ISSUE, 'F')].detail['stock'], ['str', 'abc'])
        duplicate = alerts_[(DATA_ISSUE, 'H')].detail['rows']
        self.assertEqual([(r['row'], r['stock']) for r in duplicate], [(22, ['int', '1']), (23, ['int', '2'])])
        self.assertEqual([r['stock_value'] for r in duplicate], ['1', '2'])  # per row, never added (no 3)
        self.assertFalse({'total', 'sum', 'stock_total'} & set(alerts_[(DATA_ISSUE, 'H')].detail))

    def test_bom_coverage_checks_every_product_and_counts_distinct_ids_rows_and_products(self):
        evaluation = self.evaluate()
        missing = {a.material_key: a.detail for a in evaluation.alerts if a.alert_type == NOT_IN_MASTER}
        self.assertEqual(set(missing), {'X1', 'Y', 'X 1'})  # 'X 1' is not merged with 'X1'; 'h' matches 'H'
        self.assertEqual([(o['product'], o['row']) for o in missing['X1']['occurrences']], [('P1', 23), ('P2', 22)])
        self.assertEqual([o['qty'] for o in missing['X1']['occurrences']], [['int', '2'], ['int', '5']])  # not summed
        sheet = evaluation.summary['sheets']['Stock']
        self.assertEqual((sheet['missing_distinct_ids'], sheet['missing_bom_rows'], sheet['missing_products']), (3, 4, 3))
        self.assertEqual(evaluation.summary['bom_products'], 3)
        self.assertEqual(evaluation.summary['bom_rows_without_usable_id'], 1)  # numeric-cell BOM ID not checked
        self.assertNotIn('H', missing)  # duplicate in Storage is a DATA_ISSUE, not "not found"

    def test_persistence_deduplicates_and_only_verified_evaluations_resolve(self):
        first = self.service.run('sync', authorize(self.db))
        self.assertEqual(first.outcome, alerts.COMPLETED)
        total = first.active
        self.assertEqual(total, first.new)
        again = self.service.run('sync', authorize(self.db))
        self.assertEqual((again.active, again.new, again.resolved), (total, 0, 0))
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM stock_alerts').fetchone()[0], total)
            first_seen = conn.execute("SELECT first_seen_at, last_seen_at FROM stock_alerts WHERE alert_type = ?"
                                      " AND material_key = 'B'", (LOW_STOCK,)).fetchone()
            self.assertLess(first_seen[0], first_seen[1])
        changed = [(c, 10, t) if c == 'B' else (c, q, t) for c, q, t in MIXED]
        workbook(self.stock, [('Stock', stock_with_threshold(changed))])
        self.sync()
        unverified = self.service.run('manual', None)  # e.g. a failure was seen in this session
        self.assertEqual((unverified.outcome, unverified.resolved, unverified.new), (alerts.UNVERIFIED, 0, 0))
        self.assertIn('B', {r.material_key for r in load_state(self.db).rows if r.alert_type == LOW_STOCK})
        verified = self.service.run('sync', authorize(self.db))
        self.assertEqual(verified.resolved, 1)
        state = load_state(self.db, include_resolved=True)
        low_b = next(r for r in state.rows if r.alert_type == LOW_STOCK and r.material_key == 'B')
        self.assertEqual(low_b.status, alerts.RESOLVED)
        self.assertEqual(state.latest_completed['stock_version_id'], verified.stock_version_id)

    def test_read_failure_or_failed_sync_never_resolves(self):
        self.service.run('sync', authorize(self.db))
        active = load_state(self.db).active_counts
        self.stock.unlink()
        self.sync()  # UNAVAILABLE: Storage no longer Local File Checked
        result = self.service.run('sync', authorize(self.db))
        self.assertEqual((result.outcome, result.resolved), (alerts.UNVERIFIED, 0))
        with patch.object(alerts, 'evaluate', side_effect=sqlite3.OperationalError('disk I/O error')):
            with self.assertRaises(alerts.AlertError):
                self.service.run('sync', authorize(self.db))
        state = load_state(self.db)
        self.assertEqual(state.active_counts, active)
        self.assertEqual(state.latest['outcome'], alerts.FAILED)
        self.assertIn('disk I/O error', state.latest['error_message'])

    def test_version_published_between_read_and_write_writes_nothing(self):
        real_connect = alerts.connect
        other = InventorySync(self.db, settle_seconds=0, clock=self.clock)

        def publish_then_connect(path):
            # Another program publishes after the evaluation's read view closed, before its write transaction.
            workbook(self.bom, [('P1', bom_rows([('A', 9)]))])
            self.assertEqual(other.sync_role('bom', str(self.bom), 'manual').outcome, IMPORTED)
            return real_connect(path)
        before = logical(self.db)
        with patch.object(alerts, 'connect', side_effect=publish_then_connect):
            with self.assertRaises(alerts.AlertStale):
                self.service.run('sync', authorize(self.db))
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM alert_evaluations').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT count(*) FROM stock_alerts').fetchone()[0], 0)
        self.assertNotEqual(logical(self.db), before)  # only the other program's import was committed

    def test_alert_history_is_bounded(self):
        with patch.object(alerts, 'KEEP_EVALUATIONS', 3):
            for _ in range(6):
                self.service.run('sync', authorize(self.db))
        with closing(sqlite3.connect(self.db)) as conn:
            # the 3 newest, plus the first evaluation the active alerts still reference as their provenance
            self.assertEqual([r[0] for r in conn.execute('SELECT id FROM alert_evaluations ORDER BY id')], [1, 4, 5, 6])
        workbook(self.stock, [('Stock', stock_with_threshold([('A', 5, 1)]))])
        self.sync(); self.service.run('sync', authorize(self.db))
        self.clock.now += timedelta(days=alerts.KEEP_RESOLVED_DAYS + 1)
        self.service.run('sync', authorize(self.db))
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM stock_alerts WHERE status = 'RESOLVED'").fetchone()[0], 0)

    def test_sheets_are_evaluated_separately(self):
        workbook(self.stock, [('One', stock_with_threshold([('A', 0, 1)])), ('Two', stock_with_threshold([('Z', 1, 1)]))])
        self.sync()
        evaluation = self.evaluate()
        self.assertEqual(evaluation.sheets, ('One', 'Two'))
        missing = {(a.stock_sheet, a.material_key) for a in evaluation.alerts if a.alert_type == NOT_IN_MASTER}
        self.assertIn(('Two', 'A'), missing)       # A exists only in Sheet One: Sheets are not merged
        self.assertNotIn(('One', 'A'), missing)


class AlertRunnerTests(Base):
    def test_one_running_and_one_latest_pending(self):
        gate, calls = threading.Event(), []

        class Slow:
            def run(self, trigger, authorization, still_valid):
                calls.append((trigger, authorization))
                gate.wait(10)
                return trigger
        runner = AlertRunner(Slow())
        first = alerts.Authorization(0, (('stock', 1, 's'), ('bom', 2, 'b')))
        self.assertEqual(runner.request('a', first), 'started')
        for i in range(10):
            self.assertEqual(runner.request(f'b{i}', None), 'queued')
        self.assertEqual(runner.threads_started, 1)
        gate.set()
        deadline = time.monotonic() + 10
        while runner.running and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(calls, [('a', first), ('b9', None)])  # only the newest pending request ran
        self.assertEqual(runner.threads_started, 1)

    def test_nothing_is_delivered_after_close(self):
        gate = threading.Event()

        class Slow:
            def run(self, trigger, authorization, still_valid):
                gate.wait(10)
                return trigger
        runner = AlertRunner(Slow())
        runner.request('a', None); runner.request('b', None)
        runner.close()
        gate.set()
        deadline = time.monotonic() + 10
        while runner.running and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(runner.events.empty())
        self.assertEqual(runner.request('c', None), 'closed')


class AlertUiTests(UiBase):
    def setUp(self):
        super().setUp()
        self.write_stock_threshold()
        self.callback_errors = []

    def write_stock_threshold(self, entries=None):
        workbook(self.stock, [('Stock', stock_with_threshold(entries or [('A', 0, 5), ('B', 5, 2)]))])

    def pump(self, condition, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(0.01)
        self.fail(f'condition not reached; label={self.app.alert_text!r}')

    def test_evaluated_automatically_after_both_files_are_verified(self):
        self.start_app()
        self.root.report_callback_exception = lambda *exc: self.callback_errors.append(exc)
        self.app.load_file('stock', str(self.stock)); self.finish()
        self.assertEqual(self.app.alert_runner.threads_started, 0)  # one verified file is not enough
        self.app.load_file('bom', str(self.bom)); self.finish()
        self.pump(lambda: 'active' in self.app.alert_text)
        self.assertEqual(self.app.alert_text, 'Stock Alerts: 2 active')  # A: OUT_OF_STOCK and LOW_STOCK (0 < 5)
        self.app.open_alerts()
        window = self.app.alerts_window
        self.pump(lambda: window.state is not None and window.tree.get_children())
        self.assertIn('Cloud Not Verified', window.banner.cget('text'))
        self.assertIn('pending business confirmation', window.banner.cget('text'))
        types = {window.tree.item(i, 'values')[0] for i in window.tree.get_children()}
        self.assertIn('OUT_OF_STOCK', types)
        texts = window.basis.get('1.0', 'end') + window.status.get() + window.caveats.cget('text')
        self.assertNotIn('Local Sources Verified', texts)
        self.assertIn('MIIN QTY', window.basis.get('1.0', 'end'))
        self.assertIsNone(self.app.result)  # the CHECK workflow is untouched
        self.assertEqual(self.callback_errors, [])

    def test_failed_refresh_keeps_alerts_and_marks_them_not_rechecked(self):
        self.start_app(); self.select_files()
        self.pump(lambda: 'active' in self.app.alert_text)
        active = load_state(self.db).active_counts
        self.stock.unlink()
        self.app.refresh_excel(); self.finish()
        self.root.update()
        self.assertIn('not re-checked', self.app.alert_text)
        time.sleep(0.3); self.root.update()
        self.assertEqual(load_state(self.db).active_counts, active)
        self.assertFalse(self.app.sources_verified())

    def test_schema_1_database_needs_explicit_upgrade(self):
        self.tmp_db = self.db
        self.db = self.base / 'legacy' / 'inventory.db'
        make_schema_1(self.db)
        self.start_app(); self.select_files()
        self.pump(lambda: 'upgrade required' in self.app.alert_text and not self.app.alert_runner.running)
        before = digest(self.db)
        with patch('checker.ui.messagebox.askyesno', return_value=False):
            self.app.preview_upgrade(); self.finish(); self.root.update()
        self.assertEqual(digest(self.db), before)  # declined: nothing changed
        with patch('checker.ui.messagebox.askyesno', return_value=True), \
                patch('checker.ui.messagebox.showinfo') as info:
            self.app.preview_upgrade(); self.finish()
            self.pump(lambda: info.called)
            self.pump(lambda: 'active' in self.app.alert_text)  # refresh captured thresholds, then evaluated
        with closing(open_readonly(self.db)) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 3)
            self.assertEqual(conn.execute('SELECT threshold_state FROM stock_sheets ORDER BY id DESC').fetchone()[0],
                             'FOUND')
        self.assertTrue(any((self.db.parent / 'backups').glob('inventory_before_upgrade_*.sqlite3')))

    def test_alert_window_and_entry_fit_small_windows(self):
        self.start_app(); self.select_files()
        self.pump(lambda: 'active' in self.app.alert_text)
        self.root.deiconify()
        self.root.geometry('960x600')
        self.app.show_page('alerts')  # B1: the alert entry line is on the Alerts page (count also in the sidebar)
        self.root.update(); self.app._resize(); self.root.update()
        label = self.app.alerts_label
        self.assertTrue(label.winfo_ismapped())
        self.assertLessEqual(label.winfo_rootx() + label.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width())
        self.app.show_page('check'); self.root.update(); self.app._resize(); self.root.update()
        self.assertGreater(self.app.tree.winfo_height(), 60)
        self.app.open_alerts()
        window = self.app.alerts_window
        self.pump(lambda: window.state is not None)
        for size in ('960x600', '1280x720'):
            window.top.geometry(size)
            for _ in range(3):
                window.top.update()
            self.pump(lambda: window.tree.winfo_height() > 1)
            self.assertGreater(window.tree.winfo_height(), 60, size)
            for widget in (window.banner, window.evaluate_button, window.status_label):
                self.assertTrue(widget.winfo_ismapped())
                self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                     window.top.winfo_rooty() + window.top.winfo_height())
        window.close()
        self.assertIsNone(self.app.alerts_window)
