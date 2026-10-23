"""Retention failure injection uses only synthetic workbooks/SQLite under TemporaryDirectory."""
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import os
import threading
import time
from unittest.mock import patch

from checker import cached, retention
from checker.inventory_db import stamp
from checker.queries import freshness, load_workbook_data, observed_change_summary, open_readonly
from checker.sync import UNAVAILABLE
from tests.test_m31 import Base, UiBase, digest

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


class History:
    def seed(self, dates=None):
        dates = dates or ((2024, 7, 1), (2025, 7, 1), (2025, 10, 1), (2025, 11, 1), (2026, 10, 1))
        self.ids = []
        for i, date in enumerate(dates):
            self.clock.now = datetime(*date, tzinfo=timezone.utc)
            self.write_stock([('A', 100-i), ('B', '0+10'), ('D', 1), ('D', 2)])
            result = self.sync('stock')
            self.ids.append(result.version_id)
            if i == 0:
                self.sync('bom')
        self.retainer = retention.RetentionService(self.db)

    def logical(self):
        with closing(open_readonly(self.db)) as conn:
            return retention._digest(conn)


class RetentionTests(History, Base):
    def setUp(self):
        super().setUp(); self.seed()

    def test_preview_readonly_calendar_cutoff_baseline_and_dependencies(self):
        before = digest(self.db)
        plan = self.retainer.preview(NOW)
        self.assertEqual(digest(self.db), before)
        self.assertEqual(plan.snapshot_cutoff, stamp(NOW.replace(year=2025)))
        self.assertEqual(len(plan.snapshots), 2)
        self.assertEqual(plan.payloads, (self.ids[0],))  # predecessor of baseline still has payload
        self.assertIn(self.count('inventory_snapshots'), plan.protected_snapshots)
        self.assertFalse((self.data/'backups').exists())

    def test_apply_backup_integrity_current_cache_and_sources_unchanged(self):
        before = self.logical(); files = digest(self.stock), digest(self.bom)
        cache = cached.load(self.db)
        plan = self.retainer.preview(NOW)
        with patch('checker.reader.ReadOnlyCache.read', side_effect=AssertionError('No Excel read')):
            result = self.retainer.apply(plan)
        with closing(open_readonly(result.backup)) as conn:
            self.assertEqual(retention._digest(conn), before)
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(self.query('PRAGMA foreign_key_check'), [])
        self.assertEqual(self.count('inventory_snapshots'), 3)
        self.assertEqual(self.query('SELECT count(*) FROM stock_records WHERE source_version_id=?', self.ids[0])[0][0], 0)
        self.assertEqual(self.count('source_versions'), 6)  # headers retained; BOM untouched
        with closing(open_readonly(self.db)) as conn:
            with self.assertRaises(LookupError): load_workbook_data(conn, 'stock', self.ids[0])
            self.assertEqual(len(load_workbook_data(conn, 'stock', self.ids[1]).stock_sheets[0].materials), 4)
        cached.verify(cache)
        self.assertEqual((digest(self.stock), digest(self.bom)), files)

    def test_log_cutoffs_and_old_latest_failure_and_success_are_protected(self):
        with closing(self.inv.connect()) as conn:
            conn.execute('DELETE FROM sync_runs')
            rows = [('IMPORTED', NOW-timedelta(days=91)), ('FAILED', NOW-timedelta(days=181)),
                    ('UNCHANGED', NOW-timedelta(days=90)), ('FAILED', NOW-timedelta(days=180)),
                    ('UNAVAILABLE', NOW-timedelta(days=200))]
            ids = []
            for outcome, when in rows:
                ids.append(conn.execute('INSERT INTO sync_runs '
                    '(role,trigger,source_path,started_at,finished_at,outcome,source_version_id) VALUES (?,?,?,?,?,?,?)',
                    ('stock', 'test', str(self.stock), stamp(when), stamp(when), outcome,
                     self.ids[-1] if outcome in ('IMPORTED', 'UNCHANGED') else None)).lastrowid)
            # BOM needs its own successful current-version record for cache reconstruction.
            version = conn.execute("SELECT source_version_id FROM current_sources WHERE role='bom'").fetchone()[0]
            conn.execute('INSERT INTO sync_runs (role,trigger,source_path,started_at,finished_at,outcome,source_version_id) '
                         'VALUES (?,?,?,?,?,?,?)', ('bom','test',str(self.bom),stamp(NOW-timedelta(days=500)),
                         stamp(NOW-timedelta(days=500)), 'IMPORTED',version))
            old_state = freshness(conn)
        plan = self.retainer.preview(NOW)
        self.assertEqual(set(plan.runs), set(ids[:2]))
        self.retainer.apply(plan)
        with closing(open_readonly(self.db)) as conn:
            self.assertEqual(freshness(conn), old_state)
        cached.load(self.db)

    def test_leap_day_calendar_cutoff(self):
        plan = self.retainer.preview(datetime(2028, 2, 29, 6, tzinfo=timezone.utc))
        self.assertTrue(plan.snapshot_cutoff.startswith('2027-02-28 06:'))

    def test_latest_snapshot_is_never_removed_even_all_data_is_old(self):
        plan = self.retainer.preview(NOW.replace(year=2035))
        latest = self.query('SELECT max(id) FROM inventory_snapshots')[0][0]
        self.assertNotIn(latest, plan.snapshots)
        self.retainer.apply(plan)
        self.assertEqual(self.count('inventory_snapshots'), 1)
        cached.load(self.db)

    def test_plan_is_stale_after_another_attempt(self):
        plan = self.retainer.preview(NOW)
        self.sync('stock')
        before = self.logical()
        with self.assertRaises(retention.RetentionError): self.retainer.apply(plan)
        self.assertEqual(self.logical(), before)
        self.assertFalse((self.data/'backups').exists())

    def test_many_expired_ids_do_not_exceed_sqlite_parameter_limit(self):
        with closing(self.inv.connect()) as conn:
            conn.executemany('INSERT INTO sync_runs (role,trigger,source_path,started_at,finished_at,outcome,source_version_id) '
                             'VALUES (?,?,?,?,?,?,?)', [('stock','test',str(self.stock),stamp(NOW-timedelta(days=100)),
                             stamp(NOW-timedelta(days=100)),'UNCHANGED',self.ids[-1]) for _ in range(1205)])
            before = freshness(conn)
        plan = self.retainer.preview(NOW)
        self.assertGreater(len(plan.runs),1000)
        old_count = self.count('sync_runs')
        self.retainer.apply(plan)
        self.assertEqual(self.count('sync_runs'),old_count-len(plan.runs))
        with closing(open_readonly(self.db)) as conn:
            self.assertEqual(freshness(conn),before)

    def test_database_unavailable_after_preview_is_unknown_and_not_recreated(self):
        plan = self.retainer.preview(NOW)
        away = self.base/'away.db'
        os.replace(self.db,away); before = digest(away)
        try:
            with self.assertRaises(retention.RetentionReadError): self.retainer.apply(plan)
            self.assertFalse(self.db.exists())
            self.assertEqual(digest(away),before)
        finally: os.replace(away,self.db)

    def test_forged_plan_cannot_delete_current_data(self):
        plan = self.retainer.preview(NOW)
        altered = replace(plan, payloads=tuple(self.ids))
        before = self.logical()
        with self.assertRaises(retention.RetentionError): self.retainer.apply(altered)
        self.assertEqual(self.logical(), before)

    def test_each_write_failure_rolls_back_all_tables(self):
        for point in ('snapshots', 'payloads', 'logs', 'before_commit'):
            with self.subTest(point=point):
                plan = self.retainer.preview(NOW); before = self.logical()
                def checkpoint(stage, conn):
                    if stage == point: raise sqlite3.OperationalError('injected write failure')
                with patch.object(self.retainer, '_checkpoint', side_effect=checkpoint):
                    with self.assertRaises(retention.RetentionError): self.retainer.apply(plan)
                self.assertEqual(self.logical(), before)

    def test_change_after_backup_is_refused_before_deleting(self):
        plan = self.retainer.preview(NOW)
        def checkpoint(stage, conn):
            if stage == 'backup': self.sync('stock')
        with patch.object(self.retainer, '_checkpoint', side_effect=checkpoint):
            with self.assertRaises(retention.RetentionError): self.retainer.apply(plan)
        self.assertEqual(self.count('inventory_snapshots'), 5)
        self.assertEqual(self.count('stock_records'), 20)

    def test_backup_failure_blocks_all_deletes(self):
        plan = self.retainer.preview(NOW); before = self.logical()
        original = sqlite3.connect
        def connect(path, *args, **kwargs):
            if not kwargs.get('uri') and Path(path).parent.name == 'backups':
                raise OSError('backup disk full')
            return original(path, *args, **kwargs)
        with patch('checker.retention.sqlite3.connect', side_effect=connect):
            with self.assertRaises(retention.RetentionError) as error: self.retainer.apply(plan)
        self.assertIn('backup disk full', str(error.exception))
        self.assertEqual(self.logical(), before)
        self.assertTrue(list((self.data/'backups').glob('*.partial')))
        self.assertFalse(list((self.data/'backups').glob('*.sqlite3')))

    def test_cancelled_cleanup_does_nothing(self):
        event = threading.Event(); event.set()
        before = self.logical()
        with self.assertRaises(retention.RetentionError): self.retainer.apply(self.retainer.preview(NOW), event)
        self.assertEqual(self.logical(), before)
        self.assertFalse((self.data/'backups').exists())

    def test_repeated_cleanup_noop_and_completed_plan_cannot_be_reused(self):
        plan = self.retainer.preview(NOW); self.retainer.apply(plan)
        with self.assertRaises(retention.RetentionError): self.retainer.apply(plan)
        next_plan = self.retainer.preview(NOW)
        self.assertTrue(next_plan.empty)
        before = digest(self.db)
        self.assertIsNone(self.retainer.apply(next_plan).backup)
        self.assertEqual(digest(self.db), before)

    def test_sync_continues_after_cleanup_and_unchanged_creates_no_snapshot(self):
        self.retainer.apply(self.retainer.preview(NOW))
        count = self.count('inventory_snapshots')
        self.sync('stock'); self.assertEqual(self.count('inventory_snapshots'), count)
        self.write_stock([('A', 500)])
        self.sync('stock')
        self.assertEqual(self.count('inventory_snapshots'), count+1)
        self.assertEqual(self.query('PRAGMA foreign_key_check'), [])

    def test_missing_foreign_corrupt_database_refused_without_creating(self):
        missing = self.base/'missing.db'
        with self.assertRaises(retention.RetentionReadError): retention.RetentionService(missing).preview(NOW)
        self.assertFalse(missing.exists())
        path = self.base/'bad.db'; path.write_bytes(b'bad database')
        with self.assertRaises(retention.RetentionReadError): retention.RetentionService(path).preview(NOW)
        foreign = self.base/'foreign.db'
        with closing(sqlite3.connect(foreign)) as conn:
            conn.execute('CREATE TABLE unrelated (id)'); conn.commit()
        with self.assertRaises(retention.RetentionReadError): retention.RetentionService(foreign).preview(NOW)

    def test_backup_timeout_refuses_cleanup_and_keeps_partial_separate(self):
        plan = self.retainer.preview(NOW); before = self.logical()
        with patch('checker.retention.time.monotonic',side_effect=[0,31]):
            with self.assertRaises(retention.RetentionError): self.retainer.apply(plan)
        self.assertEqual(self.logical(),before)
        self.assertTrue(list((self.data/'backups').glob('*.partial')))
        self.assertFalse(list((self.data/'backups').glob('*.sqlite3')))

    def test_lock_contention_is_bounded_and_nothing_is_deleted(self):
        plan = self.retainer.preview(NOW); before = self.logical()
        with closing(self.inv.connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            start = time.monotonic()
            try:
                with self.assertRaises(retention.RetentionError): self.retainer.apply(plan)
            finally: conn.execute('ROLLBACK')
        self.assertLess(time.monotonic()-start,5)
        self.assertEqual(self.logical(),before)

    def test_wal_database_backup_is_standalone_and_consistent(self):
        with closing(self.inv.connect()) as keeper:
            self.assertEqual(keeper.execute('PRAGMA journal_mode=WAL').fetchone()[0],'wal')
            before = self.logical()
            result = self.retainer.apply(self.retainer.preview(NOW))
            with closing(open_readonly(result.backup)) as conn:
                self.assertEqual(retention._digest(conn),before)
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_unexpected_triggers_refused(self):
        with closing(self.inv.connect()) as conn:
            conn.execute('CREATE TRIGGER extra AFTER DELETE ON sync_runs BEGIN SELECT 1; END')
        with self.assertRaises(retention.RetentionReadError): self.retainer.preview(NOW)

    def test_history_coverage_does_not_overstate_pruned_period(self):
        # Sparse historical observations leave an old baseline but a known pruned interval.
        # Use an independent synthetic DB to isolate the sparse scenario.
        from checker.sync import InventorySync
        from checker.queries import observed_change_summary
        other = self.base/'sparse.db'; inv = InventorySync(other, settle_seconds=0, clock=self.clock)
        for i, date in enumerate(((2023,1,1),(2024,1,1),(2026,10,1))):
            self.clock.now = datetime(*date,tzinfo=timezone.utc)
            self.write_stock([('A',i+1)])
            inv.sync_role('stock',str(self.stock),'test')
        service = retention.RetentionService(other)
        service.apply(service.preview(NOW))
        with closing(open_readonly(other)) as conn:
            long = observed_change_summary(conn, 730, NOW)
            short = observed_change_summary(conn, 90, NOW)
        self.assertFalse(long['covers_full_window'])
        self.assertTrue(short['covers_full_window'])
        self.assertEqual(long['retained_from'], stamp(NOW.replace(year=2025)))

    def test_supported_trend_windows_keep_the_same_material_results(self):
        with closing(open_readonly(self.db)) as conn:
            before = {d: observed_change_summary(conn,d,NOW) for d in (30,60,90)}
        self.retainer.apply(self.retainer.preview(NOW))
        with closing(open_readonly(self.db)) as conn:
            for d in (30,60,90):
                after = observed_change_summary(conn,d,NOW)
                for key in ('materials','covers_full_window','snapshot_count','window_start','window_end'):
                    self.assertEqual(after[key],before[d][key])

    def test_rollback_error_does_not_mask_original_failure(self):
        class RollbackError(sqlite3.Connection):
            def execute(inner, sql, *args, **kwargs):
                if sql == 'ROLLBACK': raise sqlite3.OperationalError('rollback fault')
                return super().execute(sql,*args,**kwargs)
        original = sqlite3.connect
        def connect(path,*args,**kwargs):
            if 'mode=rw' in str(path): kwargs['factory'] = RollbackError
            return original(path,*args,**kwargs)
        def checkpoint(stage,conn):
            if stage == 'payloads': raise sqlite3.OperationalError('original write fault')
        before = self.logical()
        with patch('checker.retention.sqlite3.connect', side_effect=connect), \
             patch.object(self.retainer,'_checkpoint',side_effect=checkpoint):
            with self.assertRaises(retention.RetentionError) as error: self.retainer.apply(self.retainer.preview(NOW))
        self.assertIn('original write fault',str(error.exception))
        self.assertIn('rollback fault',str(error.exception))
        self.assertEqual(self.logical(),before)


class RetentionUiTests(History, UiBase):
    def setUp(self):
        super().setUp(); self.seed(); self.start_app()

    def run_cleanup(self, accepted):
        with patch('checker.retention.utc_now', return_value=NOW), \
             patch('checker.ui.messagebox.askyesno', return_value=accepted) as confirm, \
             patch('checker.ui.messagebox.showinfo'):
            self.app.preview_cleanup(); self.finish()
        return confirm

    def test_preview_decline_does_not_write_or_backup(self):
        before = digest(self.db)
        confirm = self.run_cleanup(False)
        self.assertEqual(confirm.call_args.kwargs['default'], 'no')
        self.assertEqual(digest(self.db), before)
        self.assertFalse((self.data/'backups').exists())

    def test_explicit_apply_runs_new_job_and_keeps_cloud_limitation(self):
        job = self.app.job
        self.run_cleanup(True)
        self.assertEqual(self.count('inventory_snapshots'), 3)
        self.assertEqual(self.app.job, job+2)
        self.assertIn('cleanup completed', self.app.status.get())
        self.assertIn('Cloud Not Verified', self.app.status.get())
        self.assertTrue(list((self.data/'backups').glob('*.sqlite3')))

    def test_busy_maintenance_is_serialised(self):
        job = self.app.job; self.app.busy = True
        try:
            self.app.preview_cleanup(); self.app.check(); self.app.use_cached_data(); self.app.refresh_excel()
        finally: self.app.busy = False
        self.assertEqual(self.app.job, job)

    def test_background_preview_keeps_tk_responsive(self):
        original = retention.RetentionService.preview
        def slow(service): time.sleep(.15); return original(service, NOW)
        ticks = []
        with patch.object(retention.RetentionService,'preview',slow), \
             patch('checker.ui.messagebox.askyesno',return_value=False):
            self.app.preview_cleanup()
            self.root.after(10,lambda:ticks.append(self.app.busy)); self.finish()
        self.assertEqual(ticks,[True])

    def test_stale_confirmation_cannot_start_cleanup(self):
        def answer(*args,**kwargs): self.app.job += 1; return True
        before = self.logical()
        with patch('checker.retention.utc_now',return_value=NOW), \
             patch('checker.ui.messagebox.askyesno',side_effect=answer), \
             patch.object(retention.RetentionService,'apply',side_effect=AssertionError('stale dialog')):
            self.app.preview_cleanup(); self.finish()
        self.assertEqual(self.logical(),before)

    def test_database_read_failure_shows_unknown_without_deleting(self):
        before = self.logical()
        with patch.object(retention.RetentionService,'preview',side_effect=retention.RetentionReadError('bad read')):
            self.app.preview_cleanup(); self.finish()
        self.assertIn('Status Unknown',self.app.db_status.get())
        self.assertEqual(self.logical(),before)

    def test_apply_read_failure_expires_cached_consent(self):
        with patch('checker.ui.messagebox.askyesno',return_value=True):
            self.app.use_cached_data(); self.finish()
        self.assertTrue(self.app.cache_authorized)
        with patch.object(retention.RetentionService,'apply',side_effect=retention.RetentionReadError('db unavailable')):
            self.run_cleanup(True)
        self.assertFalse(self.app.cache_authorized)
        self.assertIn('Status Unknown',self.app.db_status.get())

    def test_maintenance_controls_fit_small_windows_and_scaling(self):
        self.root.deiconify()
        for size in ((960,600),(1280,720),(1366,728)):
            for scale in (1,1.5):
                with self.subTest(size=size,scale=scale):
                    self.root.tk.call('tk','scaling',96/72*scale)
                    self.root.geometry(f'{size[0]}x{size[1]}')
                    # B1: Use Cached Data is on the shortage check page, Local History on Settings.
                    for page, button in (('settings', self.app.maintenance_button), ('check', self.app.cache_button)):
                        self.app.show_page(page)
                        self.root.update(); self.app._resize(); self.root.update()
                        self.assertTrue(button.winfo_ismapped())
                        self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),
                                             self.root.winfo_rootx()+self.root.winfo_width())
                    self.assertGreater(self.app.tree.winfo_height(),60)
                    self.assert_cloud_notice(self.app)
