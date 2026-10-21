"""M3.1 tests: automatic Excel → SQLite synchronisation, inventory history, freshness and failure recovery.

Synthetic workbooks and a temporary data folder only; the real %LOCALAPPDATA% folder is never used.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
import shutil
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from checker import binding as binding_module, queries as queries_module, sync as sync_module
from checker.appdata import Settings, default_data_dir
from checker.core import check_materials
from checker.inventory_db import SCHEMA_VERSION, DatabaseError, decode, encode
from checker.queries import (OBSERVED_CHANGE_CAVEAT, bom_lines, current_stock, data_quality, data_quality_summary,
                             freshness, list_products, load_workbook_data, observed_change_summary, observed_changes,
                             open_readonly, overall_state, overall_times, snapshots, stock_history, sync_history)
from checker.reader import ReadOnlyCache
from checker.report import build_report
from checker.sync import (CLOUD_NOT_VERIFIED, DATABASE_UNAVAILABLE, FAILED, IMPORTED, LOCAL_VERIFIED, NOT_SYNCED,
                          SOURCE_CHANGED, SOURCE_UNAVAILABLE,
                          STATUS_UNKNOWN, SYNC_FAILED, SYNCING, UNAVAILABLE, UNCHANGED, USING_PREVIOUS, InventorySync)
from checker.ui import SHORT_TIME, CheckerApp, local_time
from tests.fixtures import workbook, stock_rows, bom_rows
from tests.test_m2 import BOM as M2_BOM, STOCK as M2_STOCK

UTC = timezone.utc
VERIFIED_STATUS = f'Status: {LOCAL_VERIFIED}'  # always shown beside the permanent Cloud Not Verified label


class Clock:
    """Deterministic UTC clock; each reading advances one second."""

    def __init__(self):
        self.now = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)

    def __call__(self):
        self.now += timedelta(seconds=1)
        return self.now


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest(), Path(path).stat().st_mtime_ns


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='_MRC_M31_TEST_')
        self.base = Path(self.tmp.name)
        self.stock, self.bom = self.base / 'drive' / 'storage.xlsx', self.base / 'drive' / 'bom.xlsx'
        self.stock.parent.mkdir()
        self.data = self.base / 'appdata'
        self.db = self.data / 'inventory.db'
        self.clock = Clock()
        self.write_stock([('A', 100), ('B', 5), ('C', 0)])
        self.write_bom([('A', 2), ('B', 1)])
        self.inv = InventorySync(self.db, settle_seconds=0, clock=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def write_stock(self, entries, sheets=None):
        return workbook(self.stock, sheets or [('Stock', stock_rows(entries))])

    def write_bom(self, entries, sheets=None):
        return workbook(self.bom, sheets or [('PRODUCT-1', bom_rows(entries))])

    def sync(self, role='stock', trigger='manual', **kw):
        return self.inv.sync_role(role, str(self.stock if role == 'stock' else self.bom), trigger, **kw)

    def query(self, sql, *args):
        conn = self.inv.connect()
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()

    def count(self, table):
        return self.query(f'SELECT count(*) FROM {table}')[0][0]

    def read(self, function, *args, **kw):
        conn = open_readonly(self.db)
        try:
            return function(conn, *args, **kw)
        finally:
            conn.close()

    def state(self):
        """Everything a failed sync must leave untouched."""
        tables = ('source_versions', 'current_sources', 'stock_sheets', 'stock_records', 'bom_products', 'bom_lines',
                  'inventory_snapshots', 'inventory_changes', 'data_quality_issues', 'materials')
        return {t: [tuple(r) for r in self.query(f'SELECT * FROM {t} ORDER BY 1')] for t in tables}


class SyncTests(Base):
    def test_initial_synchronisation(self):
        stock, bom = self.sync('stock', 'startup'), self.sync('bom', 'startup')
        self.assertEqual((stock.outcome, bom.outcome), (IMPORTED, IMPORTED))
        self.assertEqual([r['qty_value'] for r in self.read(current_stock)], ['100', '5', '0'])
        self.assertEqual([p['product_id'] for p in self.read(list_products)], ['PRODUCT-1'])
        self.assertEqual([(l['code'], l['qty']) for l in self.read(bom_lines, 'PRODUCT-1')], [('A', 2), ('B', 1)])
        snap = self.read(snapshots)
        self.assertEqual(len(snap), 1)  # Storage only; BOM has no inventory snapshot
        self.assertIsNone(snap[0]['previous_version_id']); self.assertIsNone(snap[0]['has_differences'])
        self.assertEqual(snap[0]['source_version_id'], stock.version_id)
        version = self.query('SELECT * FROM source_versions WHERE id = ?', stock.version_id)[0]
        self.assertEqual(version['file_sha256'], hashlib.sha256(self.stock.read_bytes()).hexdigest())
        self.assertEqual(version['source_path'], str(self.stock.resolve()))
        self.assertEqual({r.state for r in self.inv.freshness().values()}, {LOCAL_VERIFIED})
        self.assertEqual([r['trigger'] for r in self.read(sync_history)], ['startup', 'startup'])

    def test_reopening_with_unchanged_files_reads_no_workbook_and_adds_no_snapshot(self):
        self.sync('stock'); self.sync('bom')
        before = self.state()
        reopened = InventorySync(self.db, settle_seconds=0, clock=self.clock)  # a new program start, same database
        parse = lambda *a: self.fail('An unchanged workbook must not be parsed')
        results = reopened.sync_all({'stock': str(self.stock), 'bom': str(self.bom)}, 'startup', parse=parse)
        self.assertEqual({r.outcome for r in results.values()}, {UNCHANGED})
        self.assertEqual(self.state(), before)
        self.assertEqual([r['outcome'] for r in self.read(sync_history)][:2], [UNCHANGED, UNCHANGED])

    def test_resaved_file_with_identical_content_is_unchanged(self):
        self.sync()
        self.write_stock([('A', 100), ('B', 5), ('C', 0)])
        os.utime(self.stock, ns=(time.time_ns(), time.time_ns() + 5_000_000_000))  # new modified time, same content
        self.assertEqual(self.sync().outcome, UNCHANGED)
        self.assertEqual(self.count('inventory_snapshots'), 1)

    def test_same_size_and_time_but_changed_content_is_detected(self):
        self.sync(); s = self.stock.stat()
        self.write_stock([('A', 199), ('B', 5), ('C', 0)])
        os.utime(self.stock, ns=(s.st_atime_ns, s.st_mtime_ns))
        self.assertEqual(self.stock.stat().st_size, s.st_size)
        self.assertEqual(self.sync().outcome, IMPORTED)

    def test_storage_update_records_observed_changes_not_consumption(self):
        first = self.sync()
        self.write_stock([('A', 97), ('B', 5), ('D', 4)])
        second = self.sync()
        self.assertEqual(second.outcome, IMPORTED); self.assertNotEqual(second.version_id, first.version_id)
        changes = {c['material_key']: c for c in self.read(observed_changes)}
        self.assertEqual(changes['A']['change_type'], 'QUANTITY_CHANGED')
        self.assertEqual((changes['A']['previous_value'], changes['A']['new_value'], changes['A']['observed_net_change']),
                         ('100', '97', '-3'))
        self.assertEqual(changes['C']['change_type'], 'REMOVED'); self.assertIsNone(changes['C']['observed_net_change'])
        self.assertEqual(changes['D']['change_type'], 'ADDED'); self.assertIsNone(changes['D']['observed_net_change'])
        self.assertNotIn('B', changes)  # unchanged material, no row
        snap = self.read(snapshots)[-1]
        self.assertEqual((snap['previous_version_id'], snap['has_differences'], snap['same_source_path']),
                         (first.version_id, 1, 1))
        self.assertEqual((snap['quantity_changed_count'], snap['added_count'], snap['removed_count']), (1, 1, 1))
        summary = self.read(observed_change_summary, 30, now=self.clock.now)
        self.assertIn('not confirmed consumption', summary['caveat'])
        names = set(self.query("SELECT name FROM pragma_table_info('inventory_changes')")[i][0] for i in range(12))
        self.assertFalse({n for n in names if 'consum' in n or 'usage' in n})

    def test_new_version_without_inventory_differences_is_distinguished(self):
        self.sync()
        rows = stock_rows([('A', 100), ('B', 5), ('C', 0)]); rows[15]['F'] = 'Renamed description'
        self.write_stock(None, [('Stock', rows)])
        result = self.sync()
        self.assertEqual(result.outcome, IMPORTED)
        snap = self.read(snapshots)[-1]
        self.assertEqual((snap['has_differences'], snap['quantity_changed_count']), (0, 0))
        self.assertEqual(self.read(observed_changes), [])
        # A check with no new source version is a run, not a snapshot.
        self.assertEqual(self.sync().outcome, UNCHANGED)
        self.assertEqual(self.count('inventory_snapshots'), 2)

    def test_bom_update(self):
        first = self.sync('bom')
        self.write_bom(None, [('PRODUCT-1', bom_rows([('A', 3)])), ('PRODUCT-2', bom_rows([('C', 1)]))])
        second = self.sync('bom')
        self.assertEqual(second.outcome, IMPORTED)
        self.assertEqual([p['product_id'] for p in self.read(list_products)], ['PRODUCT-1', 'PRODUCT-2'])
        self.assertEqual([l['qty'] for l in self.read(bom_lines, 'PRODUCT-1')], [3])
        self.assertEqual(self.count('inventory_snapshots'), 0)
        old = self.query('SELECT superseded_at FROM source_versions WHERE id = ?', first.version_id)[0][0]
        self.assertIsNotNone(old)  # history kept, marked superseded
        self.assertEqual(self.query('SELECT count(*) FROM bom_lines WHERE source_version_id = ?', first.version_id)[0][0], 2)

    def test_source_files_are_never_modified(self):
        before = digest(self.stock), digest(self.bom)
        self.sync('stock'); self.sync('bom'); self.sync('stock'); self.sync('bom')
        self.read(load_workbook_data, 'stock'); self.read(current_stock)
        self.assertEqual((digest(self.stock), digest(self.bom)), before)


class FailureRecoveryTests(Base):
    def setUp(self):
        super().setUp()
        self.first = self.sync('stock', 'startup'); self.sync('bom', 'startup')
        self.good = self.state()
        self.success = self.inv.freshness()['stock'].last_success

    def assert_previous_data_intact(self, role='stock'):
        self.assertEqual(self.state(), self.good)
        self.assertEqual([r['qty_value'] for r in self.read(current_stock)], ['100', '5', '0'])
        info = self.inv.freshness()[role]
        self.assertTrue(info.has_data); self.assertTrue(info.using_previous)
        self.assertEqual(info.last_success, self.success if role == 'stock' else info.last_success)
        self.assertGreater(info.last_checked, info.last_success)  # checked again, but not synchronised again

    def test_missing_google_drive_source(self):
        os.replace(self.stock, self.base / 'away.bin')  # Drive disconnected / file moved away
        result = self.sync()
        self.assertEqual((result.outcome, result.recorded), (UNAVAILABLE, True))
        self.assert_previous_data_intact()
        info = self.inv.freshness()['stock']
        self.assertEqual((info.state, info.label), (SOURCE_UNAVAILABLE, f'{SOURCE_UNAVAILABLE} · {USING_PREVIOUS}'))
        missing_drive = self.inv.sync_role('stock', 'Q:\\No Drive Here\\storage.xlsx', 'startup')
        self.assertEqual(missing_drive.outcome, UNAVAILABLE)
        os.replace(self.base / 'away.bin', self.stock)  # reconnected: retry works
        self.assertEqual(self.sync().outcome, UNCHANGED)
        self.assertEqual(self.inv.freshness()['stock'].state, LOCAL_VERIFIED)

    def test_corrupted_workbook(self):
        self.stock.write_bytes(b'PK\x03\x04 this is not a complete workbook')
        result = self.sync()
        self.assertEqual(result.outcome, FAILED); self.assertTrue(result.error)
        self.assert_previous_data_intact()
        self.assertEqual(self.inv.freshness()['stock'].state, SYNC_FAILED)

    def test_invalid_workbook_structure(self):
        workbook(self.stock, [('Stock', {1: {'A': 'no header here'}})])
        result = self.sync()
        self.assertEqual(result.outcome, FAILED); self.assertIn('F01', result.error)
        self.assert_previous_data_intact()

    def test_truncated_file_while_being_replaced(self):
        data = self.stock.read_bytes(); self.write_stock([('A', 1)])
        self.stock.write_bytes(self.stock.read_bytes()[:150])  # a half-written copy
        self.assertEqual(self.sync().outcome, FAILED)
        self.assert_previous_data_intact()
        self.stock.write_bytes(data)
        self.assertEqual(self.sync().outcome, UNCHANGED)

    def test_source_changing_during_import_is_not_published(self):
        self.write_stock([('A', 50), ('B', 5), ('C', 0)])
        def parse_while_writer_saves(path, role):
            book = ReadOnlyCache().read(path, role)
            self.write_stock([('A', 1), ('B', 1), ('C', 1)])  # Excel / Drive saves a new version meanwhile
            return book
        result = self.sync(parse=parse_while_writer_saves)
        self.assertEqual(result.outcome, FAILED); self.assertIn('变化', result.error)
        self.assert_previous_data_intact()
        retry = self.sync()  # the user retries: the finished new version is imported
        self.assertEqual(retry.outcome, IMPORTED)
        self.assertEqual([r['qty_value'] for r in self.read(current_stock)], ['1', '1', '1'])

    def test_change_detected_at_final_revalidation_inside_transaction(self):
        self.write_stock([('A', 50), ('B', 5), ('C', 0)])
        real, calls = sync_module.fingerprint, []
        def fingerprint(path):
            calls.append(path); value = real(path)
            return (*value[:-1], ('changed',)) if len(calls) == 3 else value  # 3rd call: just before COMMIT
        self.inv.max_attempts = 1  # this attempt alone: nothing may be committed
        with patch.object(sync_module, 'fingerprint', fingerprint):
            result = self.sync()
        self.assertEqual(result.outcome, FAILED); self.assertIn('再次变化', result.error)
        self.assert_previous_data_intact()
        self.inv.max_attempts, calls[:] = 3, []  # with retries: the second attempt imports the file as it really is
        with patch.object(sync_module, 'fingerprint', fingerprint):
            result = self.sync()
        self.assertEqual((result.outcome, result.attempts), (IMPORTED, 2))
        self.assertEqual([r['qty_value'] for r in self.read(current_stock)], ['50', '5', '0'])

    def test_file_still_being_written_is_not_read(self):
        self.inv.settle_seconds = 0.3
        self.write_stock([('A', 60), ('B', 5), ('C', 0)])  # modified just now
        with patch.object(sync_module.time, 'sleep', lambda _s: self.write_stock([('A', 61), ('B', 5), ('C', 0)])):
            result = self.sync(parse=lambda *a: self.fail('must not parse a file that is still changing'))
        self.assertEqual(result.outcome, FAILED); self.assertIn('正在被更新', result.error)
        self.assert_previous_data_intact()

    def test_database_write_failure_rolls_back_the_whole_import(self):
        self.write_stock([('A', 1), ('B', 2), ('C', 3), ('E', 4)])
        with patch.object(InventorySync, '_write_snapshot', side_effect=sqlite3.OperationalError('disk I/O error')):
            result = self.sync()  # source_versions and stock_records were already inserted in the transaction
        self.assertEqual(result.outcome, FAILED); self.assertIn('disk I/O error', result.error)
        self.assert_previous_data_intact()
        self.assertEqual(self.read(sync_history)[0]['error_type'], 'OperationalError')
        self.write_bom([('Z', 1)])
        with patch.object(InventorySync, '_register_materials', side_effect=sqlite3.OperationalError('database is locked')):
            self.assertEqual(self.sync('bom').outcome, FAILED)
        self.assertEqual(self.state(), self.good)
        self.assertEqual(self.sync().outcome, IMPORTED)  # retry succeeds

    def test_failure_that_cannot_even_be_recorded_is_still_reported(self):
        os.replace(self.stock, self.base / 'away.bin')
        with patch.object(InventorySync, 'connect', side_effect=sqlite3.OperationalError('unable to open database')):
            result = self.sync()
        self.assertEqual((result.outcome, result.recorded), (UNAVAILABLE, False))
        self.assertEqual(self.state(), self.good)

    def test_duplicate_publication_by_a_second_program_instance(self):
        self.write_stock([('A', 7), ('B', 5), ('C', 0)])
        book = ReadOnlyCache().read(str(self.stock), 'stock')
        other = InventorySync(self.db, settle_seconds=0, clock=self.clock)
        first = other._publish('stock', str(self.stock), 'startup', self.clock(), book, 'x')
        second = self.inv._publish('stock', str(self.stock), 'startup', self.clock(), book, 'x')
        self.assertEqual((first.outcome, second.outcome), (IMPORTED, UNCHANGED))
        self.assertEqual(self.count('inventory_snapshots'), 2)


class SourceRaceTests(Base):
    """P0-2: a concurrent save injected deterministically at the protocol boundaries where the independent audit
    reproduced a false success: (A) after the signature comparison, before UNCHANGED is recorded, and (B) after the
    final fingerprint, before COMMIT. A success may only ever be reported for the version the database holds."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.sync().outcome, IMPORTED)  # published: A = 100
        self.good = self.state()

    def inject(self, stage, quantities, role='stock'):
        """At `stage` of a `role` sync, a writer saves Storage with the next quantity of A (Excel / Drive saving)."""
        quantities, hits = list(quantities), []
        def checkpoint(_inventory, at, at_role):
            if at == stage and at_role == role and quantities:
                hits.append(at)
                self.write_stock([('A', quantities.pop(0)), ('B', 5), ('C', 0)])
        return patch.object(InventorySync, '_checkpoint', checkpoint), hits

    def source_a(self):
        return str(ReadOnlyCache().read(str(self.stock), 'stock').stock_sheets[0].materials[0].quantity)

    def database_a(self):
        return self.read(current_stock, 'A')[0]['qty_value']

    def outcomes(self):
        return [(r['outcome'], r['error_type']) for r in reversed(self.read(sync_history))]

    def assert_not_verified(self, result):
        self.assertEqual((result.ok, result.changed), (False, True))
        info = self.inv.freshness()['stock']
        self.assertEqual(info.state, SOURCE_CHANGED); self.assertTrue(info.using_previous)
        self.assertNotIn(overall_state(self.inv.freshness()), (LOCAL_VERIFIED,))

    def test_a_change_after_comparison_is_never_recorded_as_unchanged(self):
        self.inv.max_attempts = 1
        guard, hits = self.inject('compared', [99])
        with guard:
            result = self.sync()
        self.assertEqual(hits, ['compared'])
        self.assertEqual((self.database_a(), self.source_a()), ('100', '99'))
        self.assert_not_verified(result)
        self.assertEqual(self.outcomes(), [(IMPORTED, None), (FAILED, 'SourceChanged')])  # no UNCHANGED was committed
        self.assertEqual(self.state(), self.good)

    def test_a_change_after_comparison_is_retried_and_the_saved_version_imported(self):
        guard, hits = self.inject('compared', [99])
        with guard:
            result = self.sync()
        self.assertEqual((result.outcome, result.attempts, hits), (IMPORTED, 2, ['compared']))
        self.assertEqual((self.database_a(), self.source_a()), ('99', '99'))
        self.assertEqual(self.inv.freshness()['stock'].state, LOCAL_VERIFIED)

    def test_a_change_after_the_final_check_of_an_unchanged_file_is_not_reported_as_checked(self):
        self.inv.max_attempts = 1
        guard, _hits = self.inject('verified', [99])
        with guard:
            result = self.sync()
        self.assertEqual((self.database_a(), self.source_a()), ('100', '99'))
        self.assert_not_verified(result)
        # The UNCHANGED record was true when committed; the change right after it is recorded on top.
        self.assertEqual(self.outcomes()[-2:], [(UNCHANGED, None), (FAILED, 'SourceChanged')])

    def test_b_change_after_the_final_check_before_import_commit(self):
        self.write_stock([('A', 11), ('B', 5), ('C', 0)])
        version_11 = hashlib.sha256(self.stock.read_bytes()).hexdigest()
        self.inv.max_attempts = 1
        guard, hits = self.inject('verified', [99])
        with guard:
            result = self.sync()
        self.assertEqual(hits, ['verified'])
        self.assertEqual((self.database_a(), self.source_a()), ('11', '99'))
        self.assert_not_verified(result)
        # The committed import is a correct historical version (exactly the bytes that were read), kept, not verified.
        current = self.query('SELECT v.file_sha256 FROM current_sources c JOIN source_versions v'
                             ' ON v.id = c.source_version_id WHERE c.role = ?', 'stock')[0][0]
        self.assertEqual(current, version_11)
        self.assertEqual(self.count('inventory_snapshots'), 2)
        self.assertEqual(self.outcomes()[-2:], [(IMPORTED, None), (FAILED, 'SourceChanged')])
        retry = self.sync()  # Refresh: the saved version is imported and verified
        self.assertEqual((retry.outcome, self.database_a(), self.inv.freshness()['stock'].state), (IMPORTED, '99', LOCAL_VERIFIED))

    def test_b_change_before_import_commit_is_retried(self):
        self.write_stock([('A', 11), ('B', 5), ('C', 0)])
        guard, _hits = self.inject('verified', [99])
        with guard:
            result = self.sync()
        self.assertEqual((result.outcome, result.attempts), (IMPORTED, 2))
        self.assertEqual((self.database_a(), self.source_a()), ('99', '99'))
        self.assertEqual(self.outcomes()[-3:], [(IMPORTED, None), (FAILED, 'SourceChanged'), (IMPORTED, None)])
        self.assertEqual(self.inv.freshness()['stock'].state, LOCAL_VERIFIED)

    def test_retries_are_bounded_when_the_source_keeps_changing(self):
        guard, hits = self.inject('verified', range(1, 50))  # a new save after every final check
        with guard:
            result = self.sync()
        self.assertEqual((result.attempts, len(hits)), (3, 3))
        self.assertEqual(self.database_a(), '2'); self.assertEqual(self.source_a(), '3')
        self.assert_not_verified(result)

    def test_a_file_changed_while_the_other_file_synchronises_is_not_shown_as_checked(self):
        guard, hits = self.inject('verified', [99], role='bom')  # Storage is saved while BOM is being imported
        with guard:
            results = self.inv.sync_all({'stock': str(self.stock), 'bom': str(self.bom)}, 'manual')
        self.assertEqual(hits, ['verified'])
        self.assertEqual((results['stock'].ok, results['stock'].changed, results['bom'].outcome), (False, True, IMPORTED))
        roles = self.inv.freshness()
        self.assertEqual((roles['stock'].state, roles['bom'].state), (SOURCE_CHANGED, LOCAL_VERIFIED))
        self.assertEqual(overall_state(roles), SOURCE_CHANGED)
        self.assertEqual((self.database_a(), self.source_a()), ('100', '99'))

    def test_a_publication_by_another_instance_meanwhile_is_not_recorded_as_unchanged(self):
        """The file itself does not change; another program instance publishes a different Storage file."""
        other_file = self.base / 'drive' / 'storage-other.xlsx'
        workbook(other_file, [('Stock', stock_rows([('A', 7)]))])
        other = InventorySync(self.db, settle_seconds=0, clock=self.clock)
        def checkpoint(_inventory, at, role):
            if at == 'compared' and not checkpoint.done:
                checkpoint.done = True
                self.assertEqual(other.sync_role('stock', str(other_file), 'startup').outcome, IMPORTED)
        checkpoint.done = False
        with patch.object(InventorySync, '_checkpoint', checkpoint):
            result = self.sync()
        self.assertEqual((result.outcome, result.attempts), (IMPORTED, 2))  # re-published: this file is current again
        self.assertEqual(self.outcomes()[-3:], [(IMPORTED, None), (FAILED, 'SourceChanged'), (IMPORTED, None)])
        self.assertIn('另一程序实例', self.read(sync_history)[1]['error_message'])
        self.assertEqual((self.database_a(), self.source_a()), ('100', '100'))


class DataIntegrityTests(Base):
    def test_duplicate_material_ids_are_never_merged(self):
        self.write_stock([('DUP', 3), (' dup ', 7), ('ONE', 1)])
        self.write_bom([('DUP', 1), ('DUP', 2)])
        self.sync(); self.sync('bom')
        rows = self.read(current_stock, 'dup')
        self.assertEqual([(r['code'], r['qty_value'], r['row_no']) for r in rows], [('DUP', '3', 15), (' dup ', '7', 16)])
        self.assertEqual(len(self.read(bom_lines, material_id='DUP')), 2)
        summary = self.read(data_quality_summary)
        self.assertEqual((summary[('stock', 'DUPLICATE_STOCK')], summary[('bom', 'DUPLICATE_BOM')]), (2, 2))
        self.write_stock([('DUP', 3), (' dup ', 8), ('ONE', 1)])
        self.sync()
        change = self.read(observed_changes, material_id='DUP')[0]
        self.assertEqual((change['change_type'], change['previous_status'], change['observed_net_change']),
                         ('DUPLICATE_CHANGED', 'DUPLICATE', None))
        self.assertEqual(json.loads(change['new_raw']), [['int', '3'], ['int', '8']])

    def test_invalid_stock_values_are_kept_raw_and_never_trusted(self):
        values = [('TEXT', '0+10'), ('NEG', -2), ('FORMULA', ('f', 'B1*2')), ('ERROR', ('e', '#N/A')),
                  ('BOOL', ('b', 1)), ('BLANK', None), ('SPACE', '  '), ('ZERO', 0), ('FRACTION', 2.5)]
        self.write_stock(values); self.sync()
        rows = {r['code']: r for r in self.read(current_stock)}
        self.assertEqual({k: (r['qty_status'], r['qty_value']) for k, r in rows.items()},
                         {'TEXT': ('INVALID', None), 'NEG': ('INVALID', None), 'FORMULA': ('INVALID', None),
                          'ERROR': ('INVALID', None), 'BOOL': ('INVALID', None), 'BLANK': ('BLANK', None),
                          'SPACE': ('BLANK', None), 'ZERO': ('VALID', '0'), 'FRACTION': ('VALID', '2.5')})
        self.assertEqual((rows['TEXT']['qty'], rows['NEG']['qty'], rows['BOOL']['qty']), ('0+10', -2, True))
        self.assertEqual((rows['FORMULA']['qty'], rows['FORMULA']['qty_cell_type']), ('=B1*2', 'f'))
        self.assertEqual(rows['ERROR']['qty_cell_type'], 'e')
        kinds = {(i['material_key'], i['issue_type']) for i in self.read(data_quality, 'stock')}
        self.assertTrue({('TEXT', 'INVALID_STOCK'), ('BLANK', 'BLANK_STOCK'), ('SPACE', 'BLANK_STOCK'),
                         ('NEG', 'INVALID_STOCK')} <= kinds)
        self.assertNotIn(('ZERO', 'INVALID_STOCK'), kinds)
        snap = self.read(snapshots)[0]
        self.assertEqual((snap['valid_count'], snap['blank_count'], snap['invalid_count']), (2, 2, 5))
        self.write_stock([(c, 5 if c == 'TEXT' else v) for c, v in values]); self.sync()
        change = self.read(observed_changes, material_id='TEXT')[0]
        self.assertEqual((change['change_type'], change['previous_status'], change['new_status'], change['observed_net_change']),
                         ('VALIDITY_CHANGED', 'INVALID', 'VALID', None))  # no net change across an invalid value

    def test_numeric_and_text_material_ids_stay_distinct(self):
        self.write_stock([('1001', 4), (1001, 9), (2002.0, 1), (('f', 'A1'), 3)])
        self.write_bom([(1001, 1), ('1001', 1)])
        self.sync(); self.sync('bom')
        rows = self.read(current_stock)
        self.assertEqual([(r['code'], r['code_cell_type'], r['material_key'], r['numeric_code']) for r in rows],
                         [('1001', 's', '1001', None), (1001, 'n', None, '1001'), (2002, 'n', None, '2002'),
                          ('=A1', 'f', None, None)])
        self.assertIsInstance(rows[1]['code'], int)
        self.assertEqual([r['qty_value'] for r in self.read(current_stock, '1001')], ['4'])  # text key only
        self.assertEqual([r[0] for r in self.query('SELECT material_key FROM materials')], ['1001'])
        issues = {(i['row_no'], i['issue_type']) for i in self.read(data_quality, 'stock')}
        self.assertEqual(issues, {(16, 'NUMERIC_MATERIAL_ID'), (17, 'NUMERIC_MATERIAL_ID'), (18, 'INVALID_MATERIAL_ID')})
        self.assertEqual(self.read(snapshots)[0]['unkeyed_count'], 3)

    def test_value_codec_round_trips_every_cell_type(self):
        samples = [None, True, False, 0, -3, 10 ** 20, 2.5, 0.1 + 0.2, 1e-30, float('inf'), 'text', ' padded ', '',
                   Decimal('1.50'), datetime(2026, 1, 2, 3, 4, 5, 6), datetime(2026, 1, 2).date(), timedelta(days=2, seconds=3)]
        for value in samples:
            back = decode(*encode(value))
            self.assertEqual((type(back), back), (type(value), value))

    def test_inventory_history_supports_30_60_90_day_windows(self):
        self.write_stock([('A', 100)]); self.sync()                       # baseline, day 0
        for days, qty in ((20, 90), (50, 95), (80, 70), (85, 70)):
            self.clock.now += timedelta(days=days - (self.clock.now - datetime(2026, 10, 1, 8, 0, tzinfo=UTC)).days)
            self.write_stock([('A', qty)] if days != 85 else [('A', 70), ('NEW', 1)]); self.sync()
        now = self.clock.now
        history = self.read(stock_history, 'a')
        self.assertEqual([[r['value'] for r in h['rows']] for h in history], [['100'], ['90'], ['95'], ['70'], ['70']])
        windows = {d: self.read(observed_change_summary, d, now=now) for d in (30, 60, 90)}
        a = {d: next(m for m in w['materials'] if m['material_key'] == 'A') for d, w in windows.items()}
        self.assertEqual(a[30]['observed_net_change'], Decimal(-25))   # 95 → 70
        self.assertEqual((a[60]['observed_net_change'], a[60]['observed_increase'], a[60]['observed_decrease']),
                         (Decimal(-20), Decimal(5), Decimal(25)))  # 90 → 95 → 70
        self.assertEqual(a[90]['observed_net_change'], Decimal(-30))    # 100 → 70
        # History starts at the first synchronisation (day 0): only the 30- and 60-day windows are fully covered.
        self.assertEqual([windows[d]['covers_full_window'] for d in (30, 60, 90)], [True, True, False])
        self.assertEqual(windows[90]['caveat'], OBSERVED_CHANGE_CAVEAT)
        self.assertEqual(self.count('inventory_snapshots'), 5)

    def test_freshness_timestamps(self):
        self.assertEqual({r.state for r in self.inv.freshness().values()}, {NOT_SYNCED})
        self.sync()
        imported = self.inv.freshness()['stock']
        self.assertEqual(imported.last_checked, imported.last_success)
        self.assertEqual(imported.source_modified, datetime.fromtimestamp(self.stock.stat().st_mtime_ns // 1_000_000 / 1000, UTC))
        self.sync()  # unchanged: checked and confirmed again, data still from the first import
        again = self.inv.freshness()['stock']
        self.assertGreater(again.last_success, imported.last_success)
        self.assertEqual(again.data_imported, imported.data_imported)
        os.replace(self.stock, self.base / 'away.bin'); self.sync()
        failed = self.inv.freshness()['stock']
        self.assertGreater(failed.last_checked, again.last_checked)
        self.assertEqual((failed.last_success, failed.data_imported), (again.last_success, again.data_imported))
        roles = self.inv.freshness()
        self.assertEqual(roles['bom'].state, NOT_SYNCED)
        self.assertEqual(overall_state(roles), USING_PREVIOUS)  # a problem outranks a file never synchronised
        self.inv.sync_role('bom', str(self.base / 'no-bom.xlsx'), 'startup')
        self.assertEqual(overall_state(self.inv.freshness()), SOURCE_UNAVAILABLE)  # unavailable and no previous data
        self.sync('bom')
        roles = self.inv.freshness()
        self.assertEqual(overall_state(roles), USING_PREVIOUS)
        self.assertEqual(overall_state(roles, {'stock': SYNCING}), SYNCING)
        checked, success = overall_times(roles)
        self.assertEqual(checked, roles['bom'].last_checked)
        self.assertEqual(success, roles['stock'].last_success)  # the older one: never overstates freshness


class StorageAndSchemaTests(Base):
    def test_default_location_is_local_app_data(self):
        with patch.dict(os.environ, {'LOCALAPPDATA': r'C:\Users\x\AppData\Local'}):
            self.assertEqual(default_data_dir(), Path(r'C:\Users\x\AppData\Local\Auraplex\MaterialStockChecker'))

    def test_schema_version_and_refusals(self):
        conn = self.inv.connect()
        self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], SCHEMA_VERSION)
        conn.execute(f'PRAGMA user_version = {SCHEMA_VERSION + 1}'); conn.close()
        with self.assertRaisesRegex(DatabaseError, '更新版本'):
            InventorySync(self.db)
        foreign = self.base / 'other.db'
        other = sqlite3.connect(foreign); other.execute('CREATE TABLE t (x)'); other.commit(); other.close()
        before = foreign.read_bytes()
        with self.assertRaisesRegex(DatabaseError, '不是本程序'):
            InventorySync(foreign)
        self.assertEqual(foreign.read_bytes(), before)
        garbage = self.base / 'garbage.db'; garbage.write_bytes(b'not a database' * 100)
        with self.assertRaises(DatabaseError):
            InventorySync(garbage)
        self.assertEqual(garbage.read_bytes(), b'not a database' * 100)  # never deleted or rewritten

    def test_readonly_query_connection_cannot_write(self):
        self.sync()
        conn = open_readonly(self.db)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute('DELETE FROM stock_records')
        finally:
            conn.close()

    def test_settings_remember_paths_atomically(self):
        settings = Settings(self.data / 'settings.json')
        self.assertEqual(settings.load(), {})
        self.assertTrue(settings.remember('stock', r'H:\Shared drives\Data\Storage.xlsx'))
        self.assertFalse(settings.remember('stock', r'H:\Shared drives\Data\Storage.xlsx'))
        settings.remember('bom', str(self.bom))
        self.assertEqual(Settings(self.data / 'settings.json').load(),
                         {'stock': r'H:\Shared drives\Data\Storage.xlsx', 'bom': str(self.bom)})
        self.assertEqual([p.name for p in self.data.iterdir() if p.name.startswith('.settings-')], [])
        (self.data / 'settings.json').write_text('{broken', encoding='utf-8')
        self.assertEqual(settings.load(), {})


# M2 fixtures plus every awkward value: parity must hold value for value.
PARITY_STOCK = M2_STOCK + [(1001, 4), ('2002', 3), (3003, 2), ('FLOAT', 2.5), ('ERR', ('e', '#N/A')), ('BOOL', ('b', 1)),
                           ('NEG', -1), (('e', '#REF!'), 1), (None, 7)]
PARITY_BOM = M2_BOM + [('1001', 1), (2002, 1), (3003, 1), ('FLOAT', 1.5), ('ERR', 1), ('BOOL', 1), ('NEG', 1),
                       ('ASSY-1', 1), ('#REF!', ('f', 'X1'))]


class ParityTests(Base):
    def test_bom_checker_results_are_identical_from_excel_and_from_the_database(self):
        second = stock_rows([('SHORT', 1), ('ENOUGH', 1)])
        workbook(self.stock, [('Stock', stock_rows(PARITY_STOCK)), ('Stock 2 ', second), ('TEMPLATE', stock_rows([]))])
        workbook(self.bom, [('DEMO-200-A-40W ', bom_rows(PARITY_BOM)), ('DEMO-200-A-40W', bom_rows([('SHORT', 3)])),
                            ('KIT-115', bom_rows([(1001, 2), ('FLOAT', 0.5)])), ('BOM TEMPLATE', bom_rows([]))])
        self.sync(); self.sync('bom')
        cache = ReadOnlyCache()
        excel_stock, excel_bom = cache.read(str(self.stock), 'stock'), cache.read(str(self.bom), 'bom')
        db_stock, db_bom = self.read(load_workbook_data, 'stock'), self.read(load_workbook_data, 'bom')
        self.assertEqual(db_stock.stock_sheets, excel_stock.stock_sheets)
        self.assertEqual(db_bom.products, excel_bom.products)
        self.assertEqual((db_stock.notes, db_bom.notes), (excel_stock.notes, excel_bom.notes))
        payload = lambda book: {s.title: [[(c.value, c.fill.fgColor.rgb) for c in row] for row in s.iter_rows()] for s in book}
        compared = 0
        for product_excel, product_db in zip(excel_bom.products, db_bom.products):
            for sheet_excel, sheet_db in zip(excel_stock.stock_sheets, db_stock.stock_sheets):
                for count in (1, 3, 10):
                    from_excel = check_materials(product_excel, sheet_excel, count)
                    from_db = check_materials(product_db, sheet_db, count)
                    self.assertEqual(from_db, from_excel)
                    self.assertEqual([r.category for r in from_db.sorted_rows], [r.category for r in from_excel.sorted_rows])
                    compared += 1
            when = datetime(2026, 10, 7)
            self.assertEqual(payload(build_report(from_db, db_stock, db_bom, when)),
                             payload(build_report(from_excel, excel_stock, excel_bom, when)))
        self.assertEqual(compared, 3 * 2 * 3)
        result = check_materials(db_bom.products[0], db_stock.stock_sheets[0], 10)
        self.assertEqual({r.category for r in result.rows}, {'SHORTAGE', 'EXCEPTION', 'ENOUGH'})
        self.assertIn('CODE_TYPE_MISMATCH', {x for r in result.rows for x in r.exceptions})


class UiBase(Base):
    """A real CheckerApp on the temporary data folder; message boxes are captured, not shown."""

    def setUp(self):
        super().setUp()
        self.errors, self.warnings, self.apps = [], [], []
        self.patches = [patch('checker.ui.messagebox.showerror', side_effect=lambda t, text, **kw: self.errors.append(text)),
                        patch('checker.ui.messagebox.showwarning', side_effect=lambda t, text, **kw: self.warnings.append(text))]
        for p in self.patches:
            p.start()
        self.root = None

    def tearDown(self):
        for app in self.apps:
            if not app.closed:
                app.close()
        for p in self.patches:
            p.stop()
        super().tearDown()

    def start_app(self, inventory=True, settings=True, inventory_error=None):
        """A new program start sharing the same local data folder."""
        if self.apps and not self.apps[-1].closed:
            self.apps[-1].close()
        self.root = tk.Tk(); self.root.withdraw()
        self.app = CheckerApp(self.root, inventory=InventorySync(self.db, settle_seconds=0, clock=self.clock) if inventory else None,
                              settings=Settings(self.data / 'settings.json') if settings else None,
                              inventory_error=inventory_error)
        self.apps.append(self.app)
        self.finish()
        return self.app

    def finish(self):
        deadline = time.monotonic() + 15
        while self.app.busy and time.monotonic() < deadline:
            self.root.update(); time.sleep(.005)
        self.assertFalse(self.app.busy, 'Background work did not finish')
        self.root.update()

    def select_files(self):
        self.app.load_file('stock', str(self.stock)); self.finish()
        self.app.load_file('bom', str(self.bom)); self.finish()

    def check(self, quantity='10'):
        self.app.product_text.set('PRODUCT-1'); self.app.quantity_text.set(quantity)
        self.app.check_button.invoke(); self.finish()

    def runs(self):
        return [(r['role'], r['trigger'], r['outcome']) for r in reversed(self.read(sync_history))]

    def assert_cloud_notice(self, app):
        """The permanent cloud limitation: its own label beside the status, full text, in every state."""
        self.assertEqual(app.db_cloud_label.cget('text'), CLOUD_NOT_VERIFIED)
        self.assertEqual(app.db_cloud_label.winfo_manager(), 'pack')
        if self.root.winfo_viewable():
            self.root.update()
            self.assertTrue(app.db_cloud_label.winfo_ismapped())
            self.assertLessEqual(app.db_cloud_label.winfo_rootx() + app.db_cloud_label.winfo_width(),
                                 app.refresh_button.winfo_rootx())

    def assert_verified(self, app):
        self.assertEqual(app.db_status.get(), VERIFIED_STATUS)
        self.assert_cloud_notice(app)


class InventoryUiTests(UiBase):
    def test_first_run_selection_is_remembered_and_reopening_uses_the_database(self):
        app = self.start_app()
        self.assertEqual((app.stock_path.get(), app.bom_path.get()), ('', ''))  # first run: user must select
        self.assertEqual(app.db_status.get(), f'Status: {NOT_SYNCED}')
        self.assertTrue(app.status.get().startswith('Ready · Choose Storage and BOM files.'))
        with patch('checker.ui.filedialog.askopenfilename', side_effect=[str(self.stock), str(self.bom)]):
            app.browse('stock'); self.finish(); app.browse('bom'); self.finish()
        self.assert_verified(app)
        self.assertEqual(Settings(self.data / 'settings.json').load(), {'stock': str(self.stock), 'bom': str(self.bom)})
        self.check(); first_result = app.result
        snapshots_before = self.count('inventory_snapshots')
        app = self.start_app()  # reopen the program
        self.assertEqual((app.stock_path.get(), app.bom_path.get()), (str(self.stock), str(self.bom)))
        self.assertIsNotNone(app.stock_book); self.assertIsNotNone(app.bom_book)
        self.assertEqual(self.runs()[-2:], [('stock', 'startup', UNCHANGED), ('bom', 'startup', UNCHANGED)])
        self.assertEqual(self.count('inventory_snapshots'), snapshots_before)
        self.assert_verified(app)
        self.check()
        self.assertEqual(app.result, first_result)  # same engine, same files, same result
        self.assertFalse(self.errors or self.warnings)

    def test_failed_selection_is_not_remembered(self):
        app = self.start_app()
        app.load_file('stock', str(self.base / 'missing.xlsx')); self.finish()
        self.assertEqual(Settings(self.data / 'settings.json').load(), {})
        self.assertIn('Source File Unavailable', app.db_role_text['stock'].get())

    def test_manual_refresh_synchronises_changes_and_recalculates(self):
        app = self.start_app(); self.select_files(); self.check()
        self.assertEqual(app.result.rows[0].category, 'ENOUGH')
        app.refresh_button.invoke(); self.finish()
        self.assertEqual(self.runs()[-2:], [('stock', 'manual', UNCHANGED), ('bom', 'manual', UNCHANGED)])
        self.assertEqual(self.count('inventory_snapshots'), 1)  # no duplicate snapshot
        self.assertIsNotNone(app.result)
        source = digest(self.stock)
        self.write_stock([('A', 3), ('B', 5), ('C', 0)]); source = digest(self.stock)
        app.refresh_button.invoke(); self.finish()
        self.assertEqual(self.runs()[-2][2], IMPORTED)
        self.assertEqual(self.count('inventory_snapshots'), 2)
        self.assertEqual((app.result.rows[0].category, app.result.rows[0].shortage), ('SHORTAGE', Decimal(17)))
        self.assertEqual(self.read(observed_changes)[0]['observed_net_change'], '-97')
        self.assertIn('Inventory Database: Local File Checked — Cloud Not Verified', app.status.get())
        self.assertEqual(digest(self.stock), source)  # refresh never writes the source
        self.assertFalse(self.errors or self.warnings)

    def test_refresh_without_result_reloads_files_and_keeps_selection(self):
        app = self.start_app(); self.select_files()
        app.product_text.set('PRODUCT-1')
        self.write_bom([('A', 2), ('B', 1), ('C', 1)])
        app.refresh_excel(); self.finish()
        self.assertEqual(self.runs()[-1], ('bom', 'manual', IMPORTED))
        self.assertEqual(app.product_text.get(), 'PRODUCT-1')
        self.assertEqual(len(app.bom_book.products[0].materials), 3)

    def test_startup_with_unavailable_source_warns_and_keeps_previous_data(self):
        app = self.start_app(); self.select_files()
        os.replace(self.stock, self.base / 'away.bin')
        app = self.start_app()
        self.assertEqual(len(self.errors), 1)
        self.assertIn('数据库保留此前同步的数据', self.errors[0]); self.assertIn('当前未验证', self.errors[0])
        self.assertIn('Refresh Excel', self.errors[0])
        self.assertEqual(app.db_status.get(), f'Status: {USING_PREVIOUS}')
        self.assertIn(f'{SOURCE_UNAVAILABLE} · {USING_PREVIOUS}', app.db_role_text['stock'].get())
        self.assertIsNone(app.stock_book); self.assertIsNotNone(app.bom_book)
        self.assertEqual([r['qty_value'] for r in self.read(current_stock)], ['100', '5', '0'])
        self.assertIn('Last error', app._inventory_details())
        os.replace(self.base / 'away.bin', self.stock)  # Drive reconnected
        app.refresh_button.invoke(); self.finish()
        self.assert_verified(app); self.assertIsNotNone(app.stock_book)

    def test_database_write_failure_with_good_excel_is_a_warning_not_a_blocked_check(self):
        app = self.start_app(); self.select_files(); self.check()
        self.write_stock([('A', 1), ('B', 5), ('C', 0)])
        with patch.object(InventorySync, '_write_snapshot', side_effect=sqlite3.OperationalError('disk I/O error')):
            app.refresh_button.invoke(); self.finish()
        self.assertFalse(self.errors); self.assertEqual(len(self.warnings), 1)
        self.assertIn('disk I/O error', self.warnings[0])
        self.assertIsNotNone(app.result)  # the Excel-based result is valid and shown
        self.assertEqual(app.db_status.get(), f'Status: {USING_PREVIOUS}')
        self.assertEqual([r['qty_value'] for r in self.read(current_stock)], ['100', '5', '0'])

    def test_background_sync_keeps_the_ui_responsive_and_touches_tk_only_on_the_main_thread(self):
        app = self.start_app(); self.select_files()
        self.write_stock([('A', 99), ('B', 5), ('C', 0)])
        real_sync, threads, states = InventorySync.sync_role, [], []
        def slow_sync(inventory, role, path, trigger, parse=None, progress=None):
            progress(role, SYNCING); time.sleep(.3)
            return real_sync(inventory, role, path, trigger, parse, progress)
        real_render = CheckerApp._render_inventory
        def render(app_self):
            threads.append(threading.current_thread() is threading.main_thread())
            states.append(app_self.db_status.get()) if app_self.db_panel else None
            return real_render(app_self)
        ticks = []
        with patch.object(InventorySync, 'sync_role', slow_sync), patch.object(CheckerApp, '_render_inventory', render):
            app.refresh_excel()
            self.assertTrue(app.busy); self.assertTrue(app.refresh_button.instate(['disabled']))
            self.root.after(20, lambda: ticks.append(1)); self.root.after(150, lambda: ticks.append(2))
            self.finish()
        self.assertEqual(ticks, [1, 2])  # the event loop kept running during the sync
        self.assertTrue(threads and all(threads))
        self.assertIn(f'Status: {SYNCING}', states)
        self.assert_verified(app)
        self.assertFalse(app.refresh_button.instate(['disabled']))

    def test_status_read_failure_clears_the_previous_success_state(self):
        """P0-1, the independent audit's reproduction: a success state exists, then reading the sync status fails."""
        app = self.start_app(); self.select_files(); self.check()
        self.assert_verified(app)
        with patch.object(InventorySync, 'freshness', side_effect=sqlite3.OperationalError('database disk image is malformed')):
            app.refresh_button.invoke(); self.finish()
        shown = [app.db_status.get(), app.status.get(), app.db_times.get(), app.db_times_label.cget('text'),
                 *(v.get() for v in app.db_role_text.values()), *(l.cget('text') for l in app.db_role_labels.values())]
        for text in shown:
            for success in (LOCAL_VERIFIED, 'Up to Date'):
                self.assertNotIn(success, text)
        self.assertEqual(app.db_status.get(), f'Status: {STATUS_UNKNOWN}')
        self.assertIn(f'Inventory Database: {STATUS_UNKNOWN} — {CLOUD_NOT_VERIFIED}', app.status.get())  # status bar too
        self.assert_cloud_notice(app)
        self.assertIn('Last Verified: —', app.db_times.get())  # no time that cannot be read reliably
        self.assertEqual({v.get() for v in app.db_role_text.values()}, {f'Storage: {STATUS_UNKNOWN}', f'BOM: {STATUS_UNKNOWN}'})
        self.assertIn('database disk image is malformed', app._inventory_details())
        self.assertEqual(len(self.warnings), 1); self.assertIn('状态读取失败', self.warnings[0])
        self.assertIsNotNone(app.result)  # the Excel-based check itself is unaffected
        self.assertEqual([r['qty_value'] for r in self.read(current_stock)], ['100', '5', '0'])  # data preserved
        app.refresh_button.invoke(); self.finish()  # the database is readable again
        self.assert_verified(app)

    def test_status_unknown_when_the_whole_sync_fails_unexpectedly(self):
        app = self.start_app(); self.select_files()
        with patch.object(InventorySync, 'sync_all', side_effect=RuntimeError('worker crashed')):
            app.refresh_button.invoke(); self.finish()
        self.assertEqual(app.db_status.get(), f'Status: {STATUS_UNKNOWN}')
        self.assertNotIn(LOCAL_VERIFIED, app.status.get())

    def test_an_older_job_cannot_overwrite_a_newer_status(self):
        app = self.start_app(); self.select_files()
        old_job = app.job
        old_report = app._sync_sources({'stock': str(self.stock), 'bom': str(self.bom)}, 'manual', old_job)  # verified
        os.replace(self.stock, self.base / 'away.bin')
        app.refresh_button.invoke(); self.finish()  # newer job: Storage unavailable
        newer = app.db_status.get()
        self.assertEqual(newer, f'Status: {USING_PREVIOUS}'); self.errors.clear()
        called = []
        app.inventory_events.put((old_job, 'stock', SYNCING))
        app.events.put((old_job, lambda data: called.append(data), {}, None, 0.1, old_report, 'manual'))
        deadline = time.monotonic() + .3
        while time.monotonic() < deadline:
            self.root.update(); time.sleep(.005)
        self.assertEqual((app.db_status.get(), called, app.sync_active), (newer, [], {}))
        self.assertTrue(app.events.empty()); self.assertFalse(self.errors or self.warnings)

    def test_local_match_is_qualified_and_shows_the_verification_time_without_a_tooltip(self):
        app = self.start_app(); self.select_files()
        self.assertEqual(str(app.db_status_label.cget('textvariable')), str(app.db_status))
        self.assert_cloud_notice(app)
        verified = overall_times(self.inv.freshness())[1].astimezone().strftime('%Y-%m-%d %H:%M')
        self.assertIn(f'Last Verified: {verified}', app.db_times.get())
        self.root.deiconify()
        for width in (1280, 960):
            self.root.geometry(f'{width}x720+0+0'); self.root.update()
            with self.subTest(width=width):
                self.assertTrue(app.db_times_label.winfo_ismapped())
                self.assertIn('Verified', app.db_times_label.cget('text'))
                self.assertIn(verified[5:], app.db_times_label.cget('text'))  # at least month-day hour:minute
                self.assertLessEqual(app.db_times_label.winfo_rootx() + app.db_times_label.winfo_width(),
                                     app.refresh_button.winfo_rootx())
        self.root.withdraw()

    def test_database_unavailable_keeps_the_checker_working(self):
        app = self.start_app(inventory=False, inventory_error='本地数据库无法使用：disk full')
        self.assertEqual(app.db_status.get(), 'Status: Database Unavailable')
        self.assertIn('disk full', app._inventory_details())
        self.select_files(); self.check()
        self.assertIsNotNone(app.result); self.assertFalse(self.errors or self.warnings)

    def test_without_local_data_the_app_behaves_as_v1(self):
        before = sorted(self.data.iterdir())
        root = tk.Tk(); root.withdraw()
        app = CheckerApp(root)
        try:
            self.assertIsNone(app.db_panel); self.assertFalse(app.busy)
            self.assertEqual(sorted(self.data.iterdir()), before)  # no settings written, nothing synchronised
            self.assertEqual(self.count('sync_runs'), 0)
        finally:
            app.close()

    def test_inventory_panel_keeps_actions_visible_in_small_windows(self):
        app = self.start_app(); self.select_files(); self.check()
        self.root.deiconify()
        for scale in (1, 1.25, 1.5):
            self.root.tk.call('tk', 'scaling', 96 / 72 * scale)
            for width, height in ((1280, 720), (1366, 728), (960, 600)):
                self.root.geometry(f'{width}x{height}+0+0'); self.root.update()
                with self.subTest(scale=scale, size=(width, height)):
                    # The database status is outside the scrolling file overview: visible without scrolling.
                    # On a short window the per-file line is hidden (compact) so the table keeps its room.
                    if (scale, width, height) == (1, 1280, 720):
                        self.assertTrue(app.db_role_labels['bom'].winfo_ismapped())
                    if not app.db_role_labels['bom'].winfo_ismapped():
                        self.assertIn('BOM: Local File Checked', app._inventory_details())
                    # Visible without a tooltip at every size: the qualified status and the verification time.
                    self.assert_verified(app)
                    times = app.db_times_label.cget('text')
                    self.assertTrue(app.db_times_label.winfo_ismapped())
                    self.assertIn('Verified', times); self.assertNotIn('…', times)
                    for label in (app.db_status_label, app.db_cloud_label, app.db_times_label):
                        self.assertLessEqual(label.winfo_rootx() + label.winfo_width(), app.refresh_button.winfo_rootx())
                    for control in (app.check_button, app.export_button, app.reload_button, app.refresh_button,
                                    app.db_status_label):
                        self.assertTrue(control.winfo_ismapped())
                        x, y = control.winfo_rootx() - self.root.winfo_rootx(), control.winfo_rooty() - self.root.winfo_rooty()
                        self.assertGreaterEqual(y, 0)
                        self.assertLessEqual(x + control.winfo_width(), self.root.winfo_width())
                        self.assertLessEqual(y + control.winfo_height(), self.root.winfo_height())
                    self.assertGreater(app.tree.winfo_height(), 60)
        self.root.withdraw()


class CheckBindingTests(UiBase):
    """Round 2, P0-A: a CHECK result is published as current only for the Storage / BOM versions that were confirmed
    after its calculation. Concurrent saves are injected deterministically right after the calculation."""

    def setUp(self):
        super().setUp()
        self.app = self.start_app(); self.select_files()
        self.renders = []
        real_render = CheckerApp.render_result
        def render(app, result, bound=None):
            self.renders.append((result, bound))
            return real_render(app, result, bound)
        self.render_patch = patch.object(CheckerApp, 'render_result', render); self.render_patch.start()

    def tearDown(self):
        self.render_patch.stop()
        super().tearDown()

    def save_after_calculation(self, role, entries, times=1):
        """Patch the calculation so that, after it returns, the role's workbook is saved with `entries`."""
        calls = []
        from checker import ui as ui_module
        calculate = ui_module.check_materials
        def check_materials(*args):
            result = calculate(*args)
            calls.append(1)
            if len(calls) <= times:
                (self.write_stock if role == 'stock' else self.write_bom)(entries(len(calls)) if callable(entries) else entries)
            return result
        return patch.object(ui_module, 'check_materials', check_materials), calls

    def current_signature(self, role):
        return self.query('SELECT v.content_signature FROM current_sources c JOIN source_versions v'
                          ' ON v.id = c.source_version_id WHERE c.role = ?', role)[0][0]

    def assert_published_current(self, app):
        bound = app.result_binding
        self.assertTrue(app.result_current); self.assertTrue(bound.current)
        for role in ('stock', 'bom'):  # the result belongs to exactly the versions the database verified
            self.assertEqual(sync_module.content_signature(bound.versions[role]), self.current_signature(role))
            self.assertEqual(bound.versions[role], sync_module.fingerprint(str(self.stock if role == 'stock' else self.bom)))
        self.assertIn('Local Sources Verified', app.result_state_label.cget('text'))
        self.assertFalse(app.export_button.instate(['disabled']))
        # Only current results were ever rendered: no stale intermediate result was published.
        self.assertTrue(all(b is not None and b.current for _r, b in self.renders))

    def assert_outdated(self, app, changed):
        self.assertIsNotNone(app.result); self.assertFalse(app.result_current)
        self.assertEqual(app.result_binding.changed, changed)
        self.assertIn('OUTDATED / RECHECK REQUIRED', app.result_state_label.cget('text'))
        self.assertIn('OUTDATED / RECHECK REQUIRED', app.status.get())
        self.assertTrue(app.export_button.instate(['disabled']))
        target = self.base / 'outdated.xlsx'
        self.assertIsNone(app.write_export(str(target))); self.assertFalse(target.exists())
        self.assertIn('不能导出为有效报告', self.errors[-1])
        with patch('checker.ui.filedialog.asksaveasfilename', side_effect=AssertionError('no save dialog')):
            app.export()
        self.assertEqual(len([e for e in self.errors if '不能导出为有效报告' in e]), 2)

    def test_check_with_old_storage_then_new_storage_synchronised_is_recalculated(self):
        guard, calls = self.save_after_calculation('stock', [('A', 3), ('B', 5), ('C', 0)])
        with guard:
            self.check()
        self.assertEqual(len(calls), 2)  # the first calculation (A = 100) was discarded and repeated
        self.assertEqual((self.app.result.rows[0].category, self.app.result.rows[0].shortage), ('SHORTAGE', Decimal(17)))
        self.assertEqual(self.app.result_binding.attempts, 2)
        self.assertEqual(self.read(current_stock, 'A')[0]['qty_value'], '3')
        self.assert_published_current(self.app)
        self.assertEqual(len(self.renders), 1)

    def test_check_with_old_bom_then_new_bom_synchronised_is_recalculated(self):
        guard, calls = self.save_after_calculation('bom', [('A', 20), ('B', 1)])
        with guard:
            self.check()
        self.assertEqual(len(calls), 2)
        self.assertEqual((self.app.result.rows[0].required, self.app.result.rows[0].category), (Decimal(200), 'SHORTAGE'))
        self.assertEqual(self.read(bom_lines, 'PRODUCT-1')[0]['qty'], 20)
        self.assert_published_current(self.app)

    def test_outdated_storage_result_is_marked_and_cannot_be_exported(self):
        guard, _calls = self.save_after_calculation('stock', [('A', 3), ('B', 5), ('C', 0)])
        with guard, patch.object(binding_module, 'CHECK_ATTEMPTS', 1):
            self.check()
        self.assert_outdated(self.app, ('stock',))
        self.assertEqual(self.app.result.rows[0].category, 'ENOUGH')  # calculated from A = 100 ...
        self.assertEqual(self.read(current_stock, 'A')[0]['qty_value'], '3')  # ... while the database holds A = 3
        self.assert_verified(self.app)  # the database itself is verified: a different statement, shown separately

    def test_outdated_bom_result_is_marked_and_cannot_be_exported(self):
        guard, _calls = self.save_after_calculation('bom', [('A', 20), ('B', 1)])
        with guard, patch.object(binding_module, 'CHECK_ATTEMPTS', 1):
            self.check()
        self.assert_outdated(self.app, ('bom',))

    def test_source_changing_on_every_attempt_ends_outdated_after_bounded_retries(self):
        guard, calls = self.save_after_calculation('stock', lambda n: [('A', n), ('B', 5), ('C', 0)], times=99)
        with guard:
            self.check()
        self.assertEqual(len(calls), binding_module.CHECK_ATTEMPTS)
        self.assert_outdated(self.app, ('stock',))
        self.assertEqual(self.app.result_binding.attempts, 3)
        self.assertTrue(all(b is not None and not b.current for _r, b in self.renders))  # never shown as current

    def test_source_change_during_a_sync_retry_does_not_validate_the_earlier_calculation(self):
        """The sync retry succeeds (IMPORTED, verified) -- but for a newer file than the one calculated."""
        hits = []
        def checkpoint(_inventory, at, role):
            if at == 'compared' and role == 'stock' and not hits:
                hits.append(at); self.write_stock([('A', 3), ('B', 5), ('C', 0)])
        with patch.object(InventorySync, '_checkpoint', checkpoint):
            self.check()
        runs = [(r['role'], r['outcome'], r['error_type']) for r in reversed(self.read(sync_history))]
        self.assertIn([('stock', FAILED, 'SourceChanged'), ('stock', IMPORTED, None)],
                      [runs[i:i + 2] for i in range(len(runs) - 1)])  # the sync's own retry imported A = 3
        self.assertEqual(self.app.result_binding.attempts, 2)
        self.assertEqual(self.app.result.rows[0].shortage, Decimal(17))  # recalculated from A = 3
        self.assert_published_current(self.app)

    def test_fresh_check_result_is_exportable(self):
        self.check()
        self.assert_published_current(self.app)
        self.assertEqual(self.app.result_binding.attempts, 1)
        self.assertTrue(all(self.app.result_binding.via_sync.values()))
        written = self.app.write_export(str(self.base / 'fresh.xlsx'))
        self.assertTrue(written and Path(written).is_file()); self.assertFalse(self.errors)

    def test_fresh_check_without_database_is_bound_to_the_re_read_files(self):
        app = self.start_app(inventory=False, inventory_error='disabled for this test'); self.select_files(); self.check()
        self.assertTrue(app.result_current); self.assertFalse(any(app.result_binding.via_sync.values()))
        self.assertTrue(app.write_export(str(self.base / 'no-db.xlsx')))
        guard, _calls = self.save_after_calculation('stock', [('A', 3), ('B', 5), ('C', 0)])
        with guard, patch.object(binding_module, 'CHECK_ATTEMPTS', 1):
            self.check()
        self.assertFalse(app.result_current); self.assertTrue(app.export_button.instate(['disabled']))

    def test_an_older_check_job_cannot_overwrite_a_newer_result(self):
        delivered = []
        real_put = self.app.events.put
        self.app.events.put = lambda event: (delivered.append(event), real_put(event))
        self.check('10'); older = delivered[-1]
        self.check('1'); newer = self.app.result
        self.assertEqual(newer.production_count, 1)
        real_put(older)  # the older job's completion arrives late
        deadline = time.monotonic() + .3
        while time.monotonic() < deadline:
            self.root.update(); time.sleep(.005)
        self.assertIs(self.app.result, newer); self.assertTrue(self.app.result_current)
        self.assertEqual(len(self.renders), 2)


class FailureOverrideTests(UiBase):
    """Round 2, P0-B: a failure this program observed overrides older success records in SQLite, also when the
    failure itself could not be written."""

    def setUp(self):
        super().setUp()
        self.app = self.start_app(); self.select_files(); self.check()
        self.assert_verified(self.app)
        self.good = self.state()
        self.success = self.inv.freshness()['stock'].last_success

    @staticmethod
    def unrecorded(inventory, role, path, trigger, started, outcome, exc):
        """_record_failure whose database write failed: nothing is written, recorded=False."""
        return sync_module.SyncResult(role, path, trigger, outcome, started, error=str(exc), recorded=False,
                                      changed=isinstance(exc, sync_module.SourceChanged))

    def assert_storage_failure_shown(self, app):
        self.assertEqual(app.db_status.get(), f'Status: {USING_PREVIOUS}')
        self.assertIn(f'Storage: {SOURCE_UNAVAILABLE} · {USING_PREVIOUS}', app.db_role_text['stock'].get())
        self.assertIn(f'Inventory Database: {USING_PREVIOUS} — {CLOUD_NOT_VERIFIED}', app.status.get())
        for text in (app.db_status.get(), app.status.get(), app.db_role_text['stock'].get()):
            self.assertNotIn(LOCAL_VERIFIED, text)
        self.assertTrue(app.db_times.get().startswith('Previously Verified: '))  # historical, labelled as such
        self.assertIn(local_time(self.success, SHORT_TIME), app.db_times.get())
        self.assert_cloud_notice(app)

    def test_unrecorded_failure_with_old_success_still_in_sqlite(self):
        """The independent audit's reproduction."""
        os.replace(self.stock, self.base / 'away.bin')
        with patch.object(InventorySync, '_record_failure', self.unrecorded):
            self.app.refresh_button.invoke(); self.finish()
        stored = self.inv.freshness()['stock']
        self.assertEqual((stored.state, stored.last_success), (LOCAL_VERIFIED, self.success))  # SQLite: old success
        self.assert_storage_failure_shown(self.app)
        self.assertIn('could not be written to the database', self.app._inventory_details())
        self.assertIn('Previously Verified (historical)', self.app._inventory_details())
        self.assertEqual(self.state(), self.good)  # stored data and history untouched

    def test_current_failure_overrides_success_records_read_by_later_jobs(self):
        os.replace(self.stock, self.base / 'away.bin')
        with patch.object(InventorySync, '_record_failure', self.unrecorded):
            self.app.refresh_button.invoke(); self.finish()
            self.app.load_file('bom', str(self.bom)); self.finish()  # a later job: only BOM, status read again
        self.assert_storage_failure_shown(self.app)
        self.assertIn(f'BOM: {LOCAL_VERIFIED}', self.app.db_role_text['bom'].get())
        os.replace(self.base / 'away.bin', self.stock)
        self.app.refresh_button.invoke(); self.finish()  # verified again by this program: the override ends
        self.assert_verified(self.app)
        self.assertEqual(self.app.sync_failures, {})

    def test_sqlite_write_failure_while_recording_a_partial_failure(self):
        """Storage unavailable and its failure row cannot be written (real SQLite error); BOM changes and imports."""
        real_row = InventorySync._run_row
        def run_row(inventory, role, path, trigger, started, outcome, *args, **kw):
            if outcome in (UNAVAILABLE, FAILED):
                raise sqlite3.OperationalError('disk I/O error')
            return real_row(inventory, role, path, trigger, started, outcome, *args, **kw)
        os.replace(self.stock, self.base / 'away.bin')
        self.write_bom([('A', 3), ('B', 1)])
        with patch.object(InventorySync, '_run_row', run_row):
            self.app.refresh_button.invoke(); self.finish()
        self.assertEqual(self.app.sync_failures['stock'].recorded, False)
        self.assertEqual(self.inv.freshness()['stock'].state, LOCAL_VERIFIED)  # what SQLite alone would claim
        self.assert_storage_failure_shown(self.app)
        self.assertIn(f'BOM: {LOCAL_VERIFIED}', self.app.db_role_text['bom'].get())
        self.assertEqual(self.read(bom_lines, 'PRODUCT-1')[0]['qty'], 3)  # BOM imported independently
        self.assertEqual([r['qty_value'] for r in self.read(current_stock)], ['100', '5', '0'])
        self.assertIsNone(self.app.result)  # Storage could not be read: no result at all
        self.assertTrue(any('本次失败未能写入数据库记录' in e for e in self.errors))

    def test_failure_during_startup_sync_is_not_hidden_by_old_success(self):
        os.replace(self.stock, self.base / 'away.bin')
        with patch.object(InventorySync, '_record_failure', self.unrecorded):
            app = self.start_app()
        self.assert_storage_failure_shown(app)


class CloudNoticeTests(UiBase):
    """Round 2, P0-C: "Cloud Not Verified" stays visible beside the status in every synchronisation state, at the
    supported window sizes and Tk scalings, without shrinking the result table below its minimum."""

    def roles(self, stock_state, bom_state=LOCAL_VERIFIED, data=True):
        when = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
        make = lambda role, state: queries_module.RoleFreshness(
            role, state, when, when if data else None, when, when, 'x.xlsx', 'x.xlsx', 'error' if state != LOCAL_VERIFIED
            else None, data or state == LOCAL_VERIFIED)
        return {'stock': make('stock', stock_state), 'bom': make('bom', bom_state)}

    def test_every_state_shows_the_cloud_limitation_at_every_size_and_scale(self):
        app = self.start_app(); self.select_files(); self.check()
        states = {
            LOCAL_VERIFIED: dict(roles=self.roles(LOCAL_VERIFIED)),
            USING_PREVIOUS: dict(roles=self.roles(SOURCE_UNAVAILABLE)),
            SOURCE_UNAVAILABLE: dict(roles=self.roles(SOURCE_UNAVAILABLE, data=False)),
            SOURCE_CHANGED: dict(roles=self.roles(SOURCE_CHANGED)),
            SYNC_FAILED: dict(roles=self.roles(SYNC_FAILED, data=False)),
            STATUS_UNKNOWN: dict(roles={}, read_error='database disk image is malformed'),
            NOT_SYNCED: dict(roles=self.roles(NOT_SYNCED, NOT_SYNCED, data=False)),
            SYNCING: dict(roles=self.roles(LOCAL_VERIFIED), active={'stock': SYNCING}),
            DATABASE_UNAVAILABLE: dict(roles={}, inventory=None),
        }
        inventory = app.inventory
        self.root.deiconify()
        try:
            for scale in (1, 1.25, 1.5):
                self.root.tk.call('tk', 'scaling', 96 / 72 * scale)
                for width, height in ((960, 600), (1280, 720), (1366, 728)):
                    self.root.geometry(f'{width}x{height}+0+0'); self.root.update()
                    for state, case in states.items():
                        app.inventory = case.get('inventory', inventory)
                        app.inventory_roles, app.sync_active = case['roles'], case.get('active', {})
                        app.inventory_read_error = case.get('read_error')
                        app._render_inventory(); self.root.update()
                        with self.subTest(scale=scale, size=(width, height), state=state):
                            self.assertEqual(app.db_status.get(), f'Status: {state}')
                            self.assert_cloud_notice(app)
                            self.assertLessEqual(app.db_status_label.winfo_rootx() + app.db_status_label.winfo_width(),
                                                 app.db_cloud_label.winfo_rootx())  # status itself not covered
                            self.assertGreater(app.tree.winfo_height(), 60)
        finally:
            app.inventory = inventory
            self.root.withdraw()

    def test_status_bar_carries_the_cloud_limitation_in_failure_states(self):
        app = self.start_app(); self.select_files()
        os.replace(self.stock, self.base / 'away.bin')
        app.refresh_button.invoke(); self.finish()
        self.assertIn(f'Inventory Database: {USING_PREVIOUS} — {CLOUD_NOT_VERIFIED}', app.status.get())
        with patch.object(InventorySync, 'freshness', side_effect=sqlite3.OperationalError('locked')):
            app.refresh_button.invoke(); self.finish()
        self.assertIn(f'Inventory Database: {STATUS_UNKNOWN} — {CLOUD_NOT_VERIFIED}', app.status.get())
        self.assert_cloud_notice(app)


class BindingUnitTests(Base):
    def test_a_verified_sync_of_a_different_version_does_not_bind(self):
        book = ReadOnlyCache().read(str(self.stock), 'stock')
        self.write_stock([('A', 1), ('B', 5), ('C', 0)])
        newer = self.sync()
        self.assertEqual(newer.outcome, IMPORTED)
        bound = binding_module.bind({'stock': book}, {'stock': newer}, 1)
        self.assertFalse(bound.current); self.assertEqual(bound.changed, ('stock',)); self.assertTrue(bound.via_sync['stock'])
        same = binding_module.bind({'stock': ReadOnlyCache().read(str(self.stock), 'stock')}, {'stock': newer}, 2)
        self.assertTrue(same.current)
        self.assertIn('Google Drive cloud copy is not verified', same.describe())

    def test_without_a_verified_sync_the_file_is_re_read(self):
        book = ReadOnlyCache().read(str(self.stock), 'stock')
        failed = sync_module.SyncResult('stock', str(self.stock), 'manual', FAILED, self.clock(), error='x')
        self.assertTrue(binding_module.bind({'stock': book}, {'stock': failed}, 1).current)
        os.replace(self.stock, self.base / 'away.bin')
        gone = binding_module.bind({'stock': book}, {}, 1)
        self.assertFalse(gone.current); self.assertIsNone(gone.confirmed['stock'])


ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which('powershell.exe'), 'Windows PowerShell is required')
class PackagingVersionTests(unittest.TestCase):
    """P1-1: the portable package script has no default version and refuses a version other than app.py's.
    Only refusing / -ValidateOnly runs are made, so build\\ and dist\\ are never cleaned by this test."""

    def build(self, *args):
        return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
                               str(ROOT / 'build_portable.ps1'), *args], capture_output=True, text=True,
                              errors='replace', timeout=120)

    def outputs(self):
        return {folder: sorted(p.name for p in (ROOT / folder).iterdir()) if (ROOT / folder).is_dir() else None
                for folder in ('build', 'dist')}

    def test_version_must_be_explicit_and_match_the_application(self):
        import app
        before = self.outputs()
        self.assertEqual(app.VERSION, '1.1.0.dev0')
        for args, message in (((), 'explicitly'), (('-Version', '1.0.0'), 'does not match'),
                              (('-Version', app.VERSION), 'development version'),
                              (('-Version', '1.0.0', '-AllowDevBuild', '-ValidateOnly'), 'does not match')):
            with self.subTest(args=args):
                run = self.build(*args)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn(message, run.stdout + run.stderr)
        run = self.build('-Version', app.VERSION, '-AllowDevBuild', '-ValidateOnly')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('development build, not for release', run.stdout)
        self.assertEqual(self.outputs(), before)


if __name__ == '__main__':
    unittest.main()
