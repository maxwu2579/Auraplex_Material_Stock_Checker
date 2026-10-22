"""M3.2C re-review repairs P1-R1 (publication ordering) and P1-R2 (read failures, stale evidence).
Synthetic workbooks and temporary SQLite only."""
from contextlib import closing
import sqlite3
import threading
import time
from unittest.mock import patch

from checker import alerts
from checker.alerts import LOW_STOCK, OUT_OF_STOCK, AlertRunner, AlertService, SessionGate, load_state
from checker.sync import IMPORTED, InventorySync
from tests.fixtures import workbook
from tests.test_m32c import authorize, stock_with_threshold
from tests.test_m32c_remediation import Remediation, SessionUiBase

BOUNDARIES = ('evaluation_inserted', 'alerts_upserted', 'alerts_resolved', 'before_commit')


def alert_rows(db):
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute('SELECT alert_key, status, last_seen_at, last_evaluation_id, resolved_at FROM stock_alerts'
                            ' ORDER BY id').fetchall()


def evaluations(db):
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute('SELECT id, outcome, error_message FROM alert_evaluations ORDER BY id').fetchall()


def wait_idle(runner, timeout=15):
    deadline = time.monotonic() + timeout
    while (runner.running or runner.pending is not None) and time.monotonic() < deadline:
        time.sleep(0.01)


class PublicationTests(Remediation):
    """P1-R1: a verified result is published only while the session's verification is still current."""

    def granted(self, gate):
        return alerts.Authorization(gate.generation, authorize(self.db).sources)

    def test_invalidation_at_every_boundary_rolls_back_the_whole_publication(self):
        self.publish_fixed()  # B no longer low: a verified evaluation would resolve it
        for stage in BOUNDARIES:
            with self.subTest(stage=stage):
                gate = SessionGate()
                granted = self.granted(gate)
                before_alerts, before_evaluations = alert_rows(self.db), evaluations(self.db)

                def hook(name, conn, stage=stage):
                    if name == stage:
                        gate.invalidate()  # e.g. a failure the session saw but could not write to SQLite
                with patch.object(alerts, '_checkpoint', side_effect=hook):
                    result = self.service.run('race', granted, lambda: gate.publishing(granted.generation))
                self.assertEqual((result.outcome, result.verified, result.new, result.resolved),
                                 (alerts.UNVERIFIED, False, 0, 0))
                self.assertIn('before publication', result.reason)
                self.assertEqual(alert_rows(self.db), before_alerts)  # every upsert and recovery rolled back
                after = evaluations(self.db)
                self.assertEqual(after[:-1], before_evaluations)   # the verified evaluation row was rolled back too
                self.assertEqual(after[-1][1], alerts.UNVERIFIED)  # only the refusal is recorded
                self.assertIn(LOW_STOCK, {r.alert_type for r in load_state(self.db).rows if r.material_key == 'B'})
        gate = SessionGate()  # genuinely re-authorised: the same data now publishes
        granted = self.granted(gate)
        result = self.service.run('ok', granted, lambda: gate.publishing(granted.generation))
        self.assertEqual((result.outcome, result.resolved), (alerts.COMPLETED, 1))

    def test_invalidation_from_another_thread_before_commit_rolls_back(self):
        self.publish_fixed()
        gate = SessionGate()
        granted = self.granted(gate)
        before = alert_rows(self.db)

        def hook(name, conn):
            if name == 'alerts_resolved':
                other = threading.Thread(target=gate.invalidate)
                other.start(); other.join(5)
        with patch.object(alerts, '_checkpoint', side_effect=hook):
            result = self.service.run('race', granted, lambda: gate.publishing(granted.generation))
        self.assertEqual((result.outcome, result.resolved), (alerts.UNVERIFIED, 0))
        self.assertEqual(alert_rows(self.db), before)

    def test_guard_orders_a_concurrent_invalidation_after_the_commit(self):
        gate, inside, release, order = SessionGate(), threading.Event(), threading.Event(), []

        def publisher():
            with gate.publishing(0) as current:
                order.append(('check', current)); inside.set(); release.wait(5)
                order.append('commit')
        p = threading.Thread(target=publisher); p.start()
        self.assertTrue(inside.wait(5))
        q = threading.Thread(target=lambda: (gate.invalidate(), order.append('invalidated'))); q.start()
        time.sleep(0.2)
        self.assertEqual(order, [('check', True)])  # invalidate() waits for the publication block
        release.set(); p.join(5); q.join(5)
        self.assertEqual(order, [('check', True), 'commit', 'invalidated'])
        self.assertFalse(gate.valid(0))

    def test_invalidate_never_waits_for_sqlite(self):
        """Lock order: SQLite first, gate second. A publisher blocked on SQLite does not hold the gate."""
        self.publish_fixed()
        gate = SessionGate()
        granted = self.granted(gate)
        reader = sqlite3.connect(self.db)
        reader.execute('BEGIN'); reader.execute('SELECT count(*) FROM stock_alerts').fetchone()  # SHARED lock held
        outcome = {}
        worker = threading.Thread(target=lambda: outcome.update(
            result=self.service.run('blocked', granted, lambda: gate.publishing(granted.generation))))
        worker.start()
        time.sleep(0.4)  # the publisher is waiting for its EXCLUSIVE lock
        started = time.monotonic()
        gate.invalidate()
        self.assertLess(time.monotonic() - started, 0.2)
        reader.rollback(); reader.close()
        worker.join(30)
        self.assertEqual((outcome['result'].outcome, outcome['result'].resolved), (alerts.UNVERIFIED, 0))

    def test_runner_retry_stays_unverified_until_genuinely_reauthorised(self):
        self.publish_fixed()
        gate = SessionGate()
        runner = AlertRunner(self.service, gate)
        old = self.granted(gate)
        fired = []

        def hook(name, conn):
            if name == 'before_commit' and not fired:
                fired.append(1); gate.invalidate()
        with patch.object(alerts, '_checkpoint', side_effect=hook):
            runner.request('race', old); wait_idle(runner)
        _generation, first, error = runner.events.get_nowait()
        self.assertIsNone(error)
        self.assertEqual(first.outcome, alerts.UNVERIFIED)
        runner.request('retry', old); wait_idle(runner)  # the same (old) authorization again
        self.assertEqual(runner.events.get_nowait()[1].outcome, alerts.UNVERIFIED)
        self.assertIn(LOW_STOCK, {r.alert_type for r in load_state(self.db).rows if r.material_key == 'B'})
        runner.request('fresh', self.granted(gate)); wait_idle(runner)  # new evidence at the current generation
        fresh = runner.events.get_nowait()[1]
        self.assertEqual((fresh.outcome, fresh.resolved), (alerts.COMPLETED, 1))


class ReadFailureUiTests(SessionUiBase):
    """P1-R2: every alert/status read failure invalidates the session and its evidence; only new source checks
    re-authorise. Stored alerts stay visible as historical and unverified; nothing is deleted."""

    def failing_load(self):
        return patch.object(alerts, 'load_state', side_effect=sqlite3.OperationalError('synthetic database read failure'))

    def assert_invalidated(self, generation):
        self.assertFalse(self.app.alert_current)
        self.assertGreater(self.app.alert_gate.generation, generation)
        self.assertEqual(self.app.alert_sources, {})
        self.assertFalse(self.app.sources_verified())
        self.assertIsNone(self.app.alert_authorization())
        self.assertIn('not re-checked', self.app.alert_text)
        self.assertIn('database read failed', self.app.alert_text)

    def test_alert_window_read_failure_invalidates_session_line_entry_and_evidence(self):
        self.current_session()
        self.app.open_alerts()
        window = self.app.alerts_window
        self.pump(lambda: window.state is not None)
        self.assertIn('Re-checked in this session', window.session.cget('text'))
        generation = self.app.alert_gate.generation
        with self.failing_load():
            window.reload('alerts')
            self.pump(lambda: not self.app.alert_current and not window.loading['alerts'])
        self.assert_invalidated(generation)
        self.assertIn('DATABASE READ FAILED', window.session.cget('text'))
        self.assertIn('NOT RE-CHECKED', window.session.cget('text'))
        self.assertIn('COULD NOT BE READ', window.basis.get('1.0', 'end'))
        window.close()  # reopening: the data is readable again, the session is still not re-checked
        self.app.open_alerts()
        reopened = self.app.alerts_window
        self.pump(lambda: reopened.state is not None)
        self.assertIn('NOT RE-CHECKED', reopened.session.cget('text'))
        self.assertNotIn('DATABASE READ FAILED', reopened.session.cget('text'))
        self.assertEqual(self.app.alert_text, 'Stock Alerts: 2 active · not re-checked')  # stored, qualified

    def test_observed_change_read_failure_invalidates_too(self):
        self.current_session()
        self.app.open_alerts()
        window = self.app.alerts_window
        self.pump(lambda: window.changes is not None)
        generation = self.app.alert_gate.generation
        with patch.object(alerts, 'observed_changes_view', side_effect=sqlite3.OperationalError('read failure')):
            window.reload('changes')
            self.pump(lambda: not window.loading['changes'] and not self.app.alert_current)
        self.assert_invalidated(generation)

    def test_delayed_background_status_read_failure_invalidates(self):
        self.current_session()
        generation = self.app.alert_gate.generation
        with self.failing_load():
            self.app._load_alert_status()
            self.pump(lambda: not self.app.alert_current)
        self.assert_invalidated(generation)

    def test_manual_reevaluate_after_failure_cannot_recover_but_refresh_can(self):
        self.current_session()  # A: OUT_OF_STOCK and LOW_STOCK active
        workbook(self.stock, [('Stock', stock_with_threshold([('A', 9, 5), ('B', 5, 2)]))])
        other = InventorySync(self.db, settle_seconds=0, clock=self.clock)  # another program publishes A fixed
        self.assertEqual(other.sync_role('stock', str(self.stock), 'manual').outcome, IMPORTED)
        with self.failing_load():
            self.app._load_alert_status()
            self.pump(lambda: not self.app.alert_current)
        self.assertIsNone(self.app.alert_authorization())
        self.app.request_alerts('manual')  # Re-evaluate: no evidence, so no authorization
        self.pump(lambda: not self.app.alert_runner.running and self.app.alert_runner.events.empty())
        state = load_state(self.db, include_resolved=True)
        self.assertEqual(state.latest['outcome'], alerts.UNVERIFIED)
        self.assertEqual({r.alert_type for r in state.rows if r.material_key == 'A' and r.status == alerts.ACTIVE},
                         {OUT_OF_STOCK, LOW_STOCK})  # not recovered by an unverified evaluation
        self.assertFalse(self.app.alert_current)
        self.app.refresh_excel(); self.finish()  # new successful source checks of both files
        self.pump(lambda: self.app.alert_current and not self.app.alert_runner.running)
        self.assertEqual(self.app.alert_text, 'Stock Alerts: 0 active')
        state = load_state(self.db, include_resolved=True)
        self.assertEqual({r.status for r in state.rows if r.material_key == 'A'}, {alerts.RESOLVED})
        self.assertIsNone(self.app.alert_read_error)
