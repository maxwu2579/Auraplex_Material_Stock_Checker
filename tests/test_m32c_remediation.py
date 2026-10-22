"""M3.2C remediation (Codex review P1-1, P1-2, P1-3, P2-1, P2-2). Synthetic workbooks and temporary SQLite only."""
from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import shutil
import sqlite3
import threading
import time
from unittest.mock import patch

from checker import alerts, upgrade
from checker.alerts import LOW_STOCK, NOT_IN_MASTER, OUT_OF_STOCK, AlertService, load_state, observed_changes_view
from checker.inventory_db import UPGRADE_TO_2, source_identity
from checker.queries import open_readonly
from checker.sync import IMPORTED, InventorySync
from tests.fixtures import bom_rows, workbook
from tests.test_m31 import Base, UiBase
from tests.test_m32c import authorize, logical, make_schema_1, stock_with_threshold

BASE_STOCK = [('A', 0, 5), ('B', 3, 5), ('C', 9, 1)]
FIXED_STOCK = [('A', 0, 5), ('B', 10, 5), ('C', 9, 1)]   # B no longer below its threshold


def active(db, alert_type=None, key=None, all_sources=True):
    state = load_state(db)
    return {(r.alert_type, r.material_key, r.storage_source) for r in state.rows
            if r.status == alerts.ACTIVE and (all_sources or r.in_scope)
            and (alert_type is None or r.alert_type == alert_type) and (key is None or r.material_key == key)}


def row_of(db, alert_type, key, storage=None):
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        sql, args = "SELECT * FROM stock_alerts WHERE alert_type = ? AND material_key = ?", [alert_type, key]
        if storage is not None:
            sql += " AND storage_source = ?"
            args.append(storage)
        return [dict(r) for r in conn.execute(sql + " ORDER BY id", args)]


class Remediation(Base):
    def setUp(self):
        super().setUp()
        workbook(self.stock, [('Stock', stock_with_threshold(BASE_STOCK))])
        workbook(self.bom, [('P1', bom_rows([('A', 1), ('X1', 2)]))])
        self.sync(); self.sync('bom')
        self.service = AlertService(self.db, clock=self.clock)
        first = self.service.run('sync', authorize(self.db))
        self.assertEqual(first.outcome, alerts.COMPLETED)
        self.assertIn((LOW_STOCK, 'B', source_identity(str(self.stock))), active(self.db))

    def publish_fixed(self):
        workbook(self.stock, [('Stock', stock_with_threshold(FIXED_STOCK))])
        self.assertEqual(self.sync().outcome, IMPORTED)


class AuthorizationTests(Remediation):
    """P1-1: verification is bound to concrete versions, paths, sync records and the session gate."""

    def test_same_version_failure_recorded_between_read_and_write_resolves_nothing(self):
        self.publish_fixed()
        granted = authorize(self.db)  # the session verified the fixed version
        real_connect = alerts.connect

        def failure_then_connect(path):  # another sync fails after the read view closed: version IDs unchanged
            self.stock.unlink()
            self.assertEqual(self.sync().outcome, 'UNAVAILABLE')
            return real_connect(path)
        with patch.object(alerts, 'connect', side_effect=failure_then_connect):
            with self.assertRaises(alerts.AlertStale):
                self.service.run('race', granted)
        self.assertIn(LOW_STOCK, {t for t, k, s in active(self.db, key='B')})
        again = self.service.run('race', granted)  # what the runner does next: re-evaluate from scratch
        self.assertEqual((again.outcome, again.resolved, again.new), (alerts.UNVERIFIED, 0, 0))
        self.assertIn('newest synchronisation', again.reason)
        self.assertIn(LOW_STOCK, {t for t, k, s in active(self.db, key='B')})

    def test_unrecorded_session_failure_invalidates_a_running_evaluation(self):
        self.publish_fixed()
        gate = alerts.SessionGate()
        granted = alerts.Authorization(gate.generation, authorize(self.db).sources)
        real_connect = alerts.connect

        def failure_then_connect(path):  # the UI saw a failure that could not be written to SQLite
            gate.invalidate()
            return real_connect(path)
        with patch.object(alerts, 'connect', side_effect=failure_then_connect):
            result = self.service.run('race', granted, lambda: gate.publishing(granted.generation))
        self.assertEqual((result.outcome, result.resolved), (alerts.UNVERIFIED, 0))
        self.assertIn('session', result.reason)
        self.assertIn(LOW_STOCK, {t for t, k, s in active(self.db, key='B')})

    def test_verification_of_an_older_version_never_covers_a_newer_one(self):
        old = authorize(self.db)
        self.publish_fixed()
        result = self.service.run('retry', old)
        self.assertEqual((result.outcome, result.resolved), (alerts.UNVERIFIED, 0))
        self.assertIn('did not verify the current Storage version', result.reason)

    def test_verification_must_name_the_same_source_path(self):
        granted = authorize(self.db)
        forged = alerts.Authorization(0, tuple((r, v, str(self.base / 'elsewhere.xlsx') if r == 'stock' else p)
                                               for r, v, p in granted.sources))
        self.publish_fixed()
        result = self.service.run('x', forged)
        self.assertEqual(result.outcome, alerts.UNVERIFIED)
        self.assertEqual(self.service.run('x', authorize(self.db)).resolved, 1)  # the proper session resolves B


class ScopeTests(Remediation):
    """P1-3: alerts of different Storage / BOM files are never one alert; no cross-file recovery."""

    def test_switching_storage_files_keeps_alerts_apart_and_switching_back_resumes(self):
        first_file = source_identity(str(self.stock))
        original = row_of(self.db, OUT_OF_STOCK, 'A')
        other = self.stock.parent / 'storage_copy.xlsx'
        shutil.copyfile(self.stock, other)
        self.assertEqual(self.inv.sync_role('stock', str(other), 'selected').outcome, IMPORTED)
        result = self.service.run('switch', authorize(self.db))
        self.assertEqual(result.outcome, alerts.COMPLETED)
        self.assertGreater(result.new, 0)
        self.assertEqual(result.resolved, 0)  # the first file's alerts are not "recovered"
        rows = row_of(self.db, OUT_OF_STOCK, 'A')
        self.assertEqual([r['storage_source'] for r in rows], [first_file, source_identity(str(other))])
        self.assertEqual(rows[0]['first_seen_at'], original[0]['first_seen_at'])  # untouched provenance
        self.assertEqual(rows[0]['stock_version_id'], original[0]['stock_version_id'])
        state = load_state(self.db)
        self.assertGreater(state.other_sources_active, 0)
        self.assertFalse(next(r for r in state.rows if r.storage_source == first_file).in_scope)
        # back to the first file: its alerts resume (same identity, first seen kept), the copy's stay apart
        self.assertEqual(self.sync().outcome, IMPORTED)
        back = self.service.run('back', authorize(self.db))
        self.assertEqual((back.new, back.resolved), (0, 0))
        self.assertEqual(row_of(self.db, OUT_OF_STOCK, 'A', first_file)[0]['first_seen_at'], original[0]['first_seen_at'])

    def test_new_versions_of_the_same_file_still_deduplicate(self):
        workbook(self.stock, [('Stock', stock_with_threshold(BASE_STOCK + [('Z', 50, 1)]))])
        self.assertEqual(self.sync().outcome, IMPORTED)
        result = self.service.run('next', authorize(self.db))
        self.assertEqual((result.new, result.resolved), (0, 0))
        self.assertEqual(len(row_of(self.db, OUT_OF_STOCK, 'A')), 1)

    def test_bom_file_change_scopes_coverage_alerts_only(self):
        self.assertIn((NOT_IN_MASTER, 'X1', source_identity(str(self.stock))), active(self.db))
        other_bom = self.bom.parent / 'bom_copy.xlsx'
        shutil.copyfile(self.bom, other_bom)
        self.assertEqual(self.inv.sync_role('bom', str(other_bom), 'selected').outcome, IMPORTED)
        result = self.service.run('bom', authorize(self.db))
        self.assertEqual((result.new, result.resolved), (1, 0))  # only the coverage alert is new for the new BOM
        coverage = row_of(self.db, NOT_IN_MASTER, 'X1')
        self.assertEqual([r['bom_source'] for r in coverage], [source_identity(str(self.bom)), source_identity(str(other_bom))])
        self.assertEqual([r['status'] for r in coverage], ['ACTIVE', 'ACTIVE'])  # the old BOM's is not recovered
        self.assertEqual(len(row_of(self.db, OUT_OF_STOCK, 'A')), 1)  # Storage-only alerts unaffected


class SchemaTwoMigrationTests(Base):
    """Existing schema-2 databases (M3.2C development) are upgraded explicitly; their alerts are attributed."""

    def test_schema_2_alerts_are_attributed_to_their_files_and_deduplicate_afterwards(self):
        legacy = self.base / 'legacy' / 'inventory.db'
        make_schema_1(legacy)
        with closing(sqlite3.connect(legacy)) as conn:
            for statement in UPGRADE_TO_2:
                conn.execute(statement)
            conn.execute('PRAGMA user_version = 2'); conn.commit()
        inv = InventorySync(legacy, settle_seconds=0, clock=self.clock)
        workbook(self.stock, [('Stock', stock_with_threshold(BASE_STOCK))])
        workbook(self.bom, [('P1', bom_rows([('A', 1), ('X1', 2)]))])
        inv.sync_role('stock', str(self.stock), 'manual'); inv.sync_role('bom', str(self.bom), 'manual')
        with closing(sqlite3.connect(legacy)) as conn:  # rows as the schema-2 build wrote them
            stock_v = conn.execute("SELECT source_version_id FROM current_sources WHERE role='stock'").fetchone()[0]
            bom_v = conn.execute("SELECT source_version_id FROM current_sources WHERE role='bom'").fetchone()[0]
            conn.execute("INSERT INTO alert_evaluations (id, trigger, started_at, finished_at, outcome, stock_version_id,"
                         " bom_version_id, sources_verified, sheet_scope, summary) VALUES (1, 'sync', 'x', 'x',"
                         " 'COMPLETED', ?, ?, 1, '[\"Stock\"]', '{}')", (stock_v, bom_v))
            for alert_type, key in ((OUT_OF_STOCK, 'A'), (NOT_IN_MASTER, 'X1')):
                conn.execute("INSERT INTO stock_alerts (alert_key, alert_type, subtype, stock_sheet, material_key, status,"
                             " first_seen_at, last_seen_at, first_evaluation_id, last_evaluation_id, stock_version_id,"
                             " bom_version_id, detail) VALUES (?, ?, ?, 'Stock', ?, 'ACTIVE', '2026-01-01 00:00:00.000',"
                             " '2026-01-01 00:00:00.000', 1, 1, ?, ?, '{}')",
                             (json.dumps([alert_type, alert_type, 'Stock', key, None]), alert_type, alert_type, key,
                              stock_v, bom_v))
            conn.commit()
        before = logical(legacy)
        with self.assertRaises(alerts.AlertUnavailable):
            AlertService(legacy).run('x', None)
        plan = upgrade.preview(legacy)
        self.assertIn('Stock alerts to attribute: 2', plan.describe())
        backup = upgrade.apply(plan)
        self.assertEqual(logical(backup), before)
        with closing(sqlite3.connect(legacy)) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 3)
            rows = conn.execute('SELECT alert_type, storage_source, bom_source, first_seen_at FROM stock_alerts'
                                ' ORDER BY id').fetchall()
        self.assertEqual(rows, [(OUT_OF_STOCK, source_identity(str(self.stock)), None, '2026-01-01 00:00:00.000'),
                                (NOT_IN_MASTER, source_identity(str(self.stock)), source_identity(str(self.bom)),
                                 '2026-01-01 00:00:00.000')])
        result = AlertService(legacy, clock=self.clock).run('sync', authorize(legacy))
        self.assertEqual(result.outcome, alerts.COMPLETED)
        for alert_type, key in ((OUT_OF_STOCK, 'A'), (NOT_IN_MASTER, 'X1')):  # matched, not duplicated
            matching = row_of(legacy, alert_type, key)
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]['first_seen_at'], '2026-01-01 00:00:00.000')


class ProvenanceTests(Remediation):
    """P2-1: bounded history never removes the verified basis or provenance that retained alerts use."""

    def test_unverified_runs_do_not_prune_the_verified_basis(self):
        # #1 created the alerts (their first evaluation); #2 is the latest verified basis (their last evaluation).
        self.assertEqual(self.service.run('sync', authorize(self.db)).new, 0)
        with patch.object(alerts, 'KEEP_EVALUATIONS', 3):
            for _ in range(4):
                self.service.run('x', None)
            for _ in range(5):
                with patch.object(alerts, 'evaluate', side_effect=sqlite3.OperationalError('disk')):
                    with self.assertRaises(alerts.AlertError):
                        self.service.run('x', None)
        state = load_state(self.db)
        self.assertIsNotNone(state.latest_completed)
        self.assertEqual(state.latest['outcome'], alerts.FAILED)
        with closing(sqlite3.connect(self.db)) as conn:
            ids = {r[0] for r in conn.execute('SELECT id FROM alert_evaluations')}
            referenced = {v for r in conn.execute('SELECT first_evaluation_id, last_evaluation_id, resolved_evaluation_id'
                                                  ' FROM stock_alerts') for v in r if v is not None}
            self.assertLessEqual(referenced, ids)  # no dangling provenance
            self.assertIn(1, referenced)
            self.assertEqual(len(ids), 5)  # bounded: 3 newest + latest verified basis (#2) + first-seen provenance (#1)

    def test_verified_basis_kept_when_no_alert_references_it(self):
        workbook(self.stock, [('Stock', stock_with_threshold([('A', 5, 1)]))])
        workbook(self.bom, [('P1', bom_rows([('A', 1)]))])
        self.sync(); self.sync('bom')
        self.assertGreater(self.service.run('clean', authorize(self.db)).resolved, 0)
        self.clock.now += timedelta(days=alerts.KEEP_RESOLVED_DAYS + 1)
        basis = self.service.run('clean', authorize(self.db))  # nothing active; old resolved alerts age out
        self.assertEqual(basis.active, 0)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM stock_alerts').fetchone()[0], 0)
        with patch.object(alerts, 'KEEP_EVALUATIONS', 3):
            for _ in range(5):
                self.service.run('x', None)
        state = load_state(self.db)
        self.assertEqual(state.latest_completed['id'], basis.evaluation_id)  # the verified basis survives


class OriginalScopeTests(Remediation):
    """P2-2: threshold shortfall, per-alert source detail, observed stock changes with filters."""

    def test_low_stock_shortfall_and_per_alert_sources(self):
        state = load_state(self.db)
        low = next(r for r in state.rows if r.alert_type == LOW_STOCK and r.material_key == 'B')
        self.assertEqual((low.detail['threshold_shortfall'], low.detail['storage_file']), ('2', str(self.stock)))
        self.assertEqual((low.detail['rack'], low.detail['level']), (['int', '1'], ['int', '2']))
        coverage = next(r for r in state.rows if r.alert_type == NOT_IN_MASTER)
        self.assertEqual(coverage.detail['bom_file'], str(self.bom))
        self.assertNotIn('threshold_shortfall', next(r for r in state.rows if r.alert_type == OUT_OF_STOCK).detail)

    def test_observed_changes_view_current_file_only_with_m4a_rules(self):
        self.publish_fixed()                                            # B 3 -> 10
        workbook(self.stock, [('Stock', stock_with_threshold([('A', None, 5), ('B', 10, 5), ('D', 1, 1)]))])
        self.sync()                                                     # A -> blank, C removed, D added
        view = observed_changes_view(self.db, 30, now=self.clock.now)
        changes = {(key, c.change_type): c for key, c in view.rows}
        self.assertEqual(changes[('B', 'QUANTITY_CHANGED')].difference, '7')
        self.assertIsNone(changes[('A', 'VALIDITY_CHANGED')].difference)
        self.assertIn(('C', 'REMOVED'), changes)
        self.assertIn(('D', 'ADDED'), changes)
        self.assertEqual(view.total, len(view.rows))
        other = self.stock.parent / 'other.xlsx'                        # another file: its history is separate
        workbook(other, [('Stock', stock_with_threshold([('B', 1, 5)]))])
        self.inv.sync_role('stock', str(other), 'selected')
        switched = observed_changes_view(self.db, 30, now=self.clock.now)
        self.assertEqual({k for k, _c in switched.rows}, {'A', 'B', 'D'})  # only the new file's own snapshot
        self.assertTrue(all(Path(c.after_path) == other for _k, c in switched.rows))
        crossing = [c for _k, c in switched.rows if c.source_switched]
        self.assertTrue(crossing and all(c.difference is None for c in crossing))
        capped = observed_changes_view(self.db, 30, now=self.clock.now, limit=1)
        self.assertEqual(len(capped.rows), 1)
        self.assertTrue(any('Only the newest' in n for n in capped.notes) or capped.total == 1)
        with self.assertRaises(alerts.AlertError):
            observed_changes_view(self.db, 45)


class SessionUiBase(UiBase):
    """Helpers only (no tests): a CheckerApp on synthetic files with a verified alert session."""

    def setUp(self):
        super().setUp()
        workbook(self.stock, [('Stock', stock_with_threshold([('A', 0, 5), ('B', 5, 2)]))])
        self.errors_seen = []

    def pump(self, condition, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(0.01)
        self.fail(f'condition not reached; label={self.app.alert_text!r}')

    def current_session(self):
        self.start_app(); self.select_files()
        self.pump(lambda: self.app.alert_current and not self.app.alert_runner.running)
        self.assertEqual(self.app.alert_text, 'Stock Alerts: 2 active')


class SessionUiTests(SessionUiBase):
    """P1-2: obsolete background results never clear a newer failure warning; restart and selection invalidate."""

    def test_late_success_after_a_failed_refresh_keeps_the_warning(self):
        self.current_session()
        self.app.open_alerts()
        window = self.app.alerts_window
        committed, release, real_run = threading.Event(), threading.Event(), AlertService.run

        def held_run(service, *args, **kwargs):
            result = real_run(service, *args, **kwargs)  # committed in the database ...
            committed.set()
            release.wait(10)                            # ... but delivered late
            return result
        with patch.object(AlertService, 'run', held_run):
            self.app.request_alerts('manual')
            self.assertTrue(committed.wait(10))
            self.stock.unlink()
            self.app.refresh_excel(); self.finish()
            self.root.update()
            self.assertIn('not re-checked', self.app.alert_text)
            self.assertFalse(self.app.alert_current)
            self.assertIn('NOT RE-CHECKED', window.session.cget('text'))
            release.set()
            self.pump(lambda: not self.app.alert_runner.running and self.app.alert_runner.events.empty())
            for _ in range(10):
                self.root.update(); time.sleep(0.01)
        self.assertIn('not re-checked', self.app.alert_text)       # the late success did not remove it
        self.assertFalse(self.app.alert_current)
        self.assertIn('NOT RE-CHECKED', window.session.cget('text'))
        self.assertFalse(self.app.sources_verified())

    def test_delayed_status_read_cannot_clear_a_failure_warning(self):
        self.current_session()
        self.stock.unlink()
        self.app.refresh_excel(); self.finish()
        self.app._load_alert_status()
        self.pump(lambda: self.app.alert_status_events.empty())
        for _ in range(20):
            self.root.update(); time.sleep(0.01)
        self.assertIn('not re-checked', self.app.alert_text)

    def test_restart_shows_stored_alerts_as_not_rechecked(self):
        self.current_session()
        self.app.close()
        self.stock.unlink()  # the restart cannot verify Storage
        self.start_app()
        self.assertFalse(self.app.alert_current)
        self.pump(lambda: self.app.alert_active is not None and not self.app.busy)
        self.assertEqual(self.app.alert_text, 'Stock Alerts: 2 active · not re-checked')
        self.app.open_alerts()
        self.pump(lambda: self.app.alerts_window.state is not None)
        self.assertIn('NOT RE-CHECKED', self.app.alerts_window.session.cget('text'))

    def test_selecting_a_source_invalidates_until_its_verified_evaluation(self):
        self.current_session()
        other = self.stock.parent / 'storage_b.xlsx'
        shutil.copyfile(self.stock, other)
        generation = self.app.alert_gate.generation
        self.app.load_file('stock', str(other))
        self.assertFalse(self.app.alert_current)
        self.assertGreater(self.app.alert_gate.generation, generation)
        self.finish()
        self.pump(lambda: self.app.alert_current and not self.app.alert_runner.running)
        self.assertEqual(self.app.alert_text, 'Stock Alerts: 2 active')  # the new file's own alerts
        self.assertEqual(load_state(self.db).other_sources_active, 2)    # the first file's: kept, not recovered

    def test_window_filters_and_observed_changes_tab(self):
        self.current_session()
        self.app.open_alerts()
        window = self.app.alerts_window
        self.pump(lambda: window.state is not None and window.changes is not None)
        all_rows = len(window.visible['alerts'])
        window.material_filter.set('b'); window._apply_filters()
        self.assertEqual({r.material_key for r in window.visible['alerts']}, set())  # B has no alert
        window.material_filter.set('a'); window._apply_filters()
        self.assertEqual({r.material_key for r in window.visible['alerts']}, {'A'})
        window.type_filter.set('LOW_STOCK'); window._apply_filters()
        self.assertEqual([r.alert_type for r in window.visible['alerts']], [LOW_STOCK])
        window.trees['alerts'].selection_set('0'); window._show_row('alerts')
        details = window.details.get('1.0', 'end')
        for text in ('Rack 1', 'Level 2', str(self.stock), 'shortfall vs threshold 5', 'MIIN QTY'):
            self.assertIn(text, details)
        window.material_filter.set(''); window.type_filter.set('All types'); window._apply_filters()
        self.assertEqual(len(window.visible['alerts']), all_rows)
        window.sheet_filter.set('Other'); window._apply_filters()
        self.assertEqual(window.visible['alerts'], ())
        self.assertIn('Observed Change ≠ Actual Consumption', window.change_note.cget('text'))
        self.assertNotIn('Local Sources Verified', window.session.cget('text') + window.banner.cget('text'))
