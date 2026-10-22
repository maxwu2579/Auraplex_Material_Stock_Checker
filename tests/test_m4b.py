"""M4B: synthetic history only. No company database, workbook, scheduler or network access."""
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import sqlite3
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from checker import analytics, analytics_ui
from checker.daily import DailyRunner
from checker.history import HistoryReadError
from checker.inventory_db import parse_stamp
from tests.fixtures import workbook, stock_rows
from tests.test_m31 import Base, UiBase, digest
from tests.test_m32c import make_schema_1
from checker.sync import InventorySync

UTC=timezone.utc


class AnalyticsBase(Base):
    def publish(self, entries, month=9, day=1, *, sheets=None, path=None):
        self.clock.now=datetime(2026,month,day,8,tzinfo=UTC)
        target=path or self.stock
        data=sheets or [('Stock',stock_rows(entries))]
        revision=self.count('inventory_snapshots')
        for name,rows in data:
            rows[1]={'A':f'Fixture revision {revision}'}
        workbook(target,data)
        result=self.inv.sync_role('stock',str(target),'manual')
        self.assertEqual(result.outcome,'IMPORTED',result.error)
        return result

    def analyze(self,days=90,**kwargs):
        return analytics.analyze(self.db,days,now=kwargs.pop('now',datetime(2026,10,2,8,tzinfo=UTC)),**kwargs)

    def material(self,key='A',**kwargs):
        return next(r for r in self.analyze(**kwargs).materials if r.material_key==key)


class AnalysisTests(AnalyticsBase):
    def test_steady_positive_stock_is_only_a_review_cue_with_coverage(self):
        self.publish([('A',100)],8,1)
        self.publish([('A',100)],9,1)
        self.publish([('A',100)],10,1)
        row=self.material()
        self.assertEqual((row.movement,row.net_change,row.comparable_intervals),(0,0,2))
        self.assertGreater(row.window_span_days,60)
        self.assertIn('LOW_OBSERVED_MOVEMENT',row.signals)
        self.assertIn('POSITIVE_UNCHANGED_REVIEW',row.signals)
        self.assertIn('not proof of excess', ' '.join(row.notes))
        self.assertNotIn('consumption',row.__dict__)

    def test_decimal_movement_and_reversal_are_exact_and_not_net_consumption(self):
        for day,value in [(1,.1),(2,.3),(3,.2)]:self.publish([('A',value)],9,day)
        row=self.material()
        self.assertEqual((row.movement,row.net_change,row.largest_step),(Decimal('.3'),Decimal('.1'),Decimal('.2')))
        self.assertEqual(row.changed_intervals,2)
        self.assertEqual(row.large_change_count,1)  # 200%, then 33.3%; default 50%
        self.assertIn('INSUFFICIENT_HISTORY',row.signals)
        self.assertNotIn('LOW_OBSERVED_MOVEMENT',row.signals)

    def test_recent_change_ends_the_positive_unchanged_review_cue(self):
        self.publish([('A',100)],8,1)
        self.publish([('A',100)],9,15)
        self.publish([('A',120)],10,1)
        row=self.material()
        self.assertGreater(row.longest_unchanged_days,30)
        self.assertEqual(row.trailing_unchanged_days,0)
        self.assertNotIn('POSITIVE_UNCHANGED_REVIEW',row.signals)
        self.assertNotIn('LONG_UNCHANGED_OBSERVATIONS',row.signals)

    def test_partial_metrics_are_labelled_and_net_is_withheld(self):
        for day,value in [(1,10),(2,12),(3,None),(4,20),(5,23)]:self.publish([('A',value)],9,day)
        row=self.material()
        self.assertEqual((row.movement,row.comparable_intervals),(5,2))
        self.assertIsNone(row.net_change)
        self.assertIn('INCOMPARABLE_GAP',row.signals)
        self.assertNotIn('LOW_OBSERVED_MOVEMENT',row.signals)

    def test_snapshots_after_evaluation_time_are_not_used(self):
        self.publish([('A',10)],9,1)
        self.publish([('A',999)],10,1)
        row=self.material(now=datetime(2026,9,2,tzinfo=UTC))
        self.assertEqual(len(row.observations),1)
        self.assertEqual(row.observations[-1].value,10)

    def test_blank_invalid_and_duplicate_are_preserved_never_added(self):
        self.publish([('A',10),('D',1),('D',2)],9,1)
        self.publish([('A',None),('D',2),('D',3)],9,2)
        self.publish([('A','0+10'),('D',3),('D',4)],9,3)
        a,d=self.material(),self.material('D')
        self.assertEqual([p.state for p in a.observations],['VALID','BLANK','INVALID'])
        self.assertEqual(a.observations[-1].raw_quantities,('0+10',))
        self.assertIsNone(a.movement);self.assertIsNone(a.net_change)
        self.assertEqual(d.observations[-1].raw_quantities,(3,4))
        self.assertIn('DUPLICATE',d.signals);self.assertIsNone(d.movement)
        self.assertEqual(d.observations[-1].rows,(16,17))

    def test_absence_and_reappearance_never_become_zero_or_bridge(self):
        self.publish([('A',10)],9,1)
        self.publish([('B',2)],9,2)
        self.publish([('A',20)],9,3)
        row=self.material()
        self.assertEqual([p.state for p in row.observations],['VALID','ABSENT','VALID'])
        self.assertEqual(row.comparable_intervals,0)
        self.assertIsNone(row.movement);self.assertIsNone(row.net_change)

    def test_source_switch_and_return_are_isolated(self):
        other=self.stock.parent/'other.xlsx'
        self.publish([('A',10)],9,1)
        self.publish([('A',90)],9,2,path=other)
        self.publish([('A',15)],9,3)
        rows=self.analyze().materials
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r.movement is None and r.net_change is None for r in rows))
        own=next(r for r in rows if r.source_path==str(self.stock.resolve()))
        self.assertIn('INCOMPARABLE_GAP',own.signals)
        self.assertIn('OTHER_SOURCE_HISTORY',next(r for r in rows if r is not own).signals)

    def test_original_sheet_names_and_similar_ids_remain_distinct(self):
        sheets=lambda:[('Stock',stock_rows([('A-1',1),('A-10',10),('A_1',20)])),
                        (' Stock ',stock_rows([('A-1',100)]))]
        self.publish(None,9,1,sheets=sheets())
        self.publish(None,9,2,sheets=sheets())
        result=self.analyze(sheet=' Stock ',material_text='a-1')
        self.assertEqual([(r.sheet,r.material_key) for r in result.materials],[(' Stock ','A-1')])
        self.assertEqual(result.materials[0].observations[-1].value,100)
        self.assertEqual([r.material_key for r in self.analyze(material_text='_').materials],['A_1'])
        self.assertEqual(len(self.analyze(material_text='A-1').materials),3)

    def test_reference_and_30_60_90_ranges_do_not_extrapolate_to_now(self):
        self.publish([('A',1)],6,1)
        self.publish([('A',2)],9,1)
        for days in (30,60,90):
            result=self.analyze(days)
            row=result.materials[0]
            self.assertTrue(row.observations[0].reference)
            self.assertLessEqual(row.window_span_days,days)
            self.assertNotIn('LOW_OBSERVED_MOVEMENT',row.signals)
        stale=self.analyze(30,now=datetime(2026,12,1,tzinfo=UTC))
        row=stale.materials[0]
        self.assertEqual((stale.snapshots_in_window,len(row.observations)),(0,1))
        self.assertIsNone(row.movement)
        self.assertEqual(row.window_span_days,0)

    def test_zero_denominator_does_not_invent_a_percentage(self):
        self.publish([('A',0)],9,1)
        self.publish([('A',10)],9,2)
        row=self.material()
        self.assertIn('FROM_ZERO_PERCENT_UNKNOWN',row.signals)
        self.assertEqual(row.large_change_count,0)
        self.publish([('A',0)],9,3)
        self.assertIn('LAST_OBSERVED_ZERO',self.material().signals)

    def test_deleted_snapshot_and_incomplete_payload_break_comparability(self):
        self.publish([('A',10)],8,1)
        middle=self.publish([('A',11)],9,1)
        last=self.publish([('A',12)],10,1)
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('DELETE FROM inventory_changes WHERE snapshot_id IN (SELECT id FROM inventory_snapshots WHERE source_version_id=?)',(middle.version_id,))
            conn.execute('DELETE FROM inventory_snapshots WHERE source_version_id=?',(middle.version_id,))
            conn.commit()
        self.assertIsNone(self.material().net_change)
        self.assertEqual(self.material().comparable_intervals,0)
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('DELETE FROM stock_records WHERE source_version_id=?',(last.version_id,));conn.commit()
        row=self.material()
        self.assertEqual(row.observations[-1].state,'NOT_RETAINED')
        self.assertIsNone(row.observations[-1].value)

    def test_retention_boundary_blocks_whole_window_classification(self):
        self.publish([('A',10)],8,1)
        self.publish([('A',10)],10,1)
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("INSERT OR REPLACE INTO schema_info VALUES ('history_retained_from','2026-09-01 00:00:00.000')")
            conn.commit()
        row=self.material()
        self.assertIn('HISTORY_PRUNED',row.signals)
        self.assertNotIn('LOW_OBSERVED_MOVEMENT',row.signals)
        self.assertIsNone(row.net_change)

    def test_unknown_numeric_ids_empty_db_and_read_failures_do_not_invent_data(self):
        self.assertEqual(self.analyze().materials,())
        self.publish([(51102,4),('A',5)],9,1)
        result=self.analyze()
        self.assertEqual(result.unkeyed_rows,1)
        self.assertEqual(self.analyze(material_text='51102').materials,())
        path=self.base/'missing.db'
        with self.assertRaises(HistoryReadError):analytics.analyze(path)
        self.assertFalse(path.exists())

    def test_no_excel_or_db_writes_and_unsupported_schema_refused(self):
        self.publish([('A',10)],9,1)
        before=digest(self.db),digest(self.stock)
        self.analyze()
        self.assertEqual((digest(self.db),digest(self.stock)),before)
        with closing(sqlite3.connect(self.db)) as conn:conn.execute('pragma user_version=999');conn.commit()
        before=digest(self.db)
        with self.assertRaises(HistoryReadError):self.analyze()
        self.assertEqual(digest(self.db),before)

    def test_legacy_schema_one_is_read_without_migration(self):
        path=self.base/'legacy.db'
        make_schema_1(path)
        inventory=InventorySync(path,settle_seconds=0,clock=self.clock)
        self.assertTrue(inventory.sync_role('stock',str(self.stock),'manual').ok)
        before=digest(path)
        result=analytics.analyze(path,now=self.clock.now)
        self.assertTrue(result.materials)
        self.assertEqual(digest(path),before)
        with closing(sqlite3.connect(path)) as conn:self.assertEqual(conn.execute('pragma user_version').fetchone()[0],1)

    def test_missing_all_payloads_is_explained_even_without_known_materials(self):
        self.publish([('A',10)],9,1)
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('DELETE FROM stock_records');conn.commit()
        result=self.analyze()
        self.assertEqual(result.materials,())
        self.assertIn('payload(s) incomplete/not retained',' '.join(result.notes))

    def test_limits_and_cancellation_fail_closed(self):
        self.publish([('A',10),('B',1)],9,1)
        self.publish([('A',11),('B',2)],9,2)
        for limits in ({'max_snapshots':1},{'max_rows':1},{'max_groups':1}):
            with self.assertRaises(analytics.AnalyticsLimit):self.analyze(**limits)
        cancel=threading.Event();cancel.set()
        with self.assertRaises(analytics.AnalyticsCancelled):self.analyze(cancel=cancel)
        with patch.object(analytics.time,'monotonic',side_effect=[0,10,10]):
            with self.assertRaises(analytics.AnalyticsLimit):self.analyze(budget_seconds=1)

    def test_policy_validation_and_rule_changes_are_explicit(self):
        for kwargs in ({'minimum_days':0},{'low_movement':'NaN'},{'large_change_percent':0},{'low_movement':-1}):
            with self.assertRaises(analytics.AnalyticsError):analytics.Policy(**kwargs)
        self.publish([('A',100)],8,1)
        self.publish([('A',101)],10,1)
        self.assertNotIn('LOW_OBSERVED_MOVEMENT',self.material().signals)
        self.assertIn('LOW_OBSERVED_MOVEMENT',self.material(policy=analytics.Policy(30,1,50)).signals)

    def test_concurrent_writer_cannot_mix_query_versions(self):
        self.publish([('A',10)],9,1)
        wrote=threading.Event();committed=threading.Event();errors=[]
        def writer():
            try:
                with closing(sqlite3.connect(self.db,timeout=3)) as conn:
                    conn.execute("UPDATE stock_records SET qty_value='999' WHERE material_key='A'")
                    wrote.set();conn.commit();committed.set()
            except Exception as exc:errors.append(exc)
        thread=threading.Thread(target=writer)
        def checkpoint(stage):
            if stage=='snapshot_view':
                thread.start();self.assertTrue(wrote.wait(1));self.assertFalse(committed.is_set())
        with patch.object(analytics,'_checkpoint',side_effect=checkpoint):row=self.material()
        thread.join(3)
        self.assertEqual(row.observations[-1].value,10)
        self.assertTrue(committed.is_set());self.assertFalse(errors)


class AnalyticsUiTests(UiBase):
    def wait_window(self,window):
        deadline=time.monotonic()+5
        while window.runner.busy and time.monotonic()<deadline:
            self.root.update();time.sleep(.005)
        self.assertFalse(window.runner.busy)
        time.sleep(.06);self.root.update()

    def test_main_entry_reuses_window_and_failure_clears_results(self):
        self.sync();self.sync('bom')
        app=self.start_app();app.open_analytics();window=app.analytics_window
        app.open_analytics();self.assertIs(app.analytics_window,window)
        window.query();self.wait_window(window)
        self.assertIsNotNone(window.result)
        with patch.object(analytics,'analyze',side_effect=HistoryReadError('synthetic read failed')):
            window.query();self.wait_window(window)
        self.assertIsNone(window.result)
        self.assertEqual(window.tree.get_children(),())
        self.assertIn('QUERY FAILED',window.status.get())
        self.assertTrue(app.alert_read_error)
        app.close();self.assertTrue(window.closed)

    def test_newest_request_stop_and_close_never_publish_old_results(self):
        app=self.start_app();app.open_analytics();window=app.analytics_window
        started=threading.Event();release=threading.Event();calls=[]
        original=analytics.analyze
        def slow(*args,**kwargs):
            calls.append(args[3]);started.set();release.wait(2)
            return original(*args,**kwargs)
        with patch.object(analytics,'analyze',side_effect=slow):
            window.query();self.assertTrue(started.wait(1))
            for i in range(15):window.material_text.set(str(i));window.query()
            self.assertEqual(window.runner.threads_started,1)
            window.stop();release.set();self.wait_window(window)
        self.assertIsNone(window.result)
        self.assertLessEqual(len(calls),2)
        window.query();window.close()
        deadline=time.monotonic()+2
        while window.runner.busy and time.monotonic()<deadline:time.sleep(.005)
        self.assertTrue(window.closed);self.assertIsNone(app.analytics_window)
        self.assertTrue(window.runner.events.empty())

    def test_small_window_scaling_matrix_keeps_banner_and_table_visible(self):
        app=self.start_app()
        old=float(self.root.tk.call('tk','scaling'))
        try:
            for scale in (1,1.5):
                for width,height in ((960,600),(1280,720),(1366,728)):
                    with self.subTest(scale=scale,size=(width,height)):
                        self.root.tk.call('tk','scaling',scale)
                        app.open_analytics();window=app.analytics_window
                        window.top.geometry(f'{width}x{height}+0+0')
                        self.root.update();self.root.update()
                        self.assertIn('Cloud Not Verified',window.banner.cget('text'))
                        self.assertGreater(window.tree.winfo_height(),70)
                        right=window.banner.winfo_x()+window.banner.winfo_reqwidth()
                        self.assertLessEqual(right,window.top.winfo_width())
                        def descendants(widget):
                            for child in widget.winfo_children():
                                yield child
                                yield from descendants(child)
                        actions=[w for w in descendants(window.top) if w.winfo_class()=='TButton' and w.cget('text') in ('Analyze','Stop','Close')]
                        self.assertEqual(len(actions),3)
                        for widget in actions:
                            self.assertTrue(widget.winfo_ismapped())
                            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),window.top.winfo_rootx()+window.top.winfo_width())
                            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),window.top.winfo_rooty()+window.top.winfo_height())
                        window.close()
        finally:self.root.tk.call('tk','scaling',old)

    def test_large_result_is_rendered_in_pages_and_editing_clears_summary(self):
        self.write_stock([(f'A{i:03d}',i) for i in range(230)])
        self.sync()
        app=self.start_app();app.open_analytics();window=app.analytics_window
        window.query();self.wait_window(window)
        self.assertEqual(len(window.result.materials),230)
        self.assertEqual(len(window.tree.get_children()),200)
        window.more.invoke()
        self.assertEqual(len(window.tree.get_children()),230)
        self.assertIn('230',window.coverage.get('1.0','end'))
        window.material_text.set('A0')
        self.assertIsNone(window.result)
        self.assertNotIn('230',window.coverage.get('1.0','end'))
        self.assertEqual(window.tree.get_children(),())


if __name__=='__main__':unittest.main()
