"""M1 regression tests for the P1 findings in M0_CODE_REVIEW.md. Synthetic files in a temp directory only.

Updated for M2 where the approved M2 rules replace M1 behaviour; each change is marked "M2:".
- M1's evaluation (ESTIMATED_SHORTAGE / ESTIMATED_NO_SHORTAGE / NOT_EVALUATED) is replaced by the M2 category
  (SHORTAGE / EXCEPTION / ENOUGH). Not-found, blank and invalid stock are now calculated with an assumed 0.
- M1's CSV export is replaced by the XLSX report; the two CSV tests now check the same safety properties on it.
  Report content is tested in tests/test_m2.py.
"""
import ctypes
import os
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from checker import reader
from openpyxl import load_workbook

from checker.core import DataReadError, ROW_CAVEAT, check_materials
from checker.reader import ReadOnlyCache, owner_lock_files
from checker.service import CheckerService
from checker.ui import CheckerApp
from tests.fixtures import workbook, stock_rows, bom_rows


class TempFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.stock = self.base / 'stock.xlsx'
        self.bom = self.base / 'bom.xlsx'

    def tearDown(self):
        self.tmp.cleanup()

    def checked(self, stock_entries, bom_entries, count=3):
        workbook(self.stock, [('Stock', stock_rows(stock_entries))])
        workbook(self.bom, [('Product', bom_rows(bom_entries))])
        cache = ReadOnlyCache()
        return check_materials(cache.read(str(self.bom), 'bom').products[0],
                               cache.read(str(self.stock), 'stock').stock_sheets[0], count)


class CodeTypeTests(TempFiles):
    """P1-2: a code kept in a numeric cell is neither matched nor reported as a confirmed mismatch."""

    def test_numeric_stock_code_is_not_reported_as_not_found(self):
        r = self.checked([(51102, 5)], [('51102', 1)]).rows[0]
        self.assertEqual(r.match_status, 'CODE_TYPE_MISMATCH')
        self.assertIsNone(r.delta); self.assertIsNone(r.shortage)
        self.assertEqual([s.source.row for s in r.stock], [15])
        self.assertEqual(r.stock[0].code, 51102)  # original value and type preserved
        # M2: was evaluation NOT_EVALUATED. Still not calculated, and no stock value is assumed for it.
        self.assertEqual((r.category, r.data_status, r.stock_used), ('EXCEPTION', 'CODE_TYPE_MISMATCH', None))

    def test_numeric_bom_code_against_text_or_numeric_stock(self):
        result = self.checked([('51102', 5), (777, 1)], [(51102, 1), (777, 1), (999, 1)])
        self.assertEqual([r.match_status for r in result.rows], ['CODE_TYPE_MISMATCH', 'CODE_TYPE_MISMATCH', 'UNVERIFIED_BOM'])
        self.assertTrue(all(r.delta is None for r in result.rows))
        self.assertEqual(result.counts['CODE_TYPE_MISMATCH'], 2); self.assertEqual(result.counts['NOT_FOUND'], 0)

    def test_text_codes_still_match_and_unrelated_digits_stay_not_found(self):
        result = self.checked([('51102', 5), (60000, 1)], [('51102', 1), ('51103', 1)])
        self.assertEqual([r.match_status for r in result.rows], ['MATCHED', 'NOT_FOUND'])
        self.assertEqual(result.rows[0].delta, 2)

    def test_text_match_notes_additional_numeric_lookalike_without_using_it(self):
        r = self.checked([('51102', 5), (51102, 100)], [('51102', 1)]).rows[0]
        self.assertEqual(r.match_status, 'MATCHED'); self.assertEqual(len(r.stock), 1); self.assertEqual(r.delta, 2)
        self.assertTrue(any('数值单元格' in issue for issue in r.issues))

    def test_fractional_and_formula_codes_are_not_converted(self):
        result = self.checked([(1.5, 5), (('f', '51102'), 5)], [('1.5', 1), ('51102', 1), ('15', 1)])
        self.assertEqual([r.match_status for r in result.rows], ['CODE_TYPE_MISMATCH', 'NOT_FOUND', 'NOT_FOUND'])


class EvaluationTests(TempFiles):
    """P1-1 / P1-6: shortage, no-shortage and not-evaluated rows are distinguishable and counted."""

    def result(self):
        return self.checked([('SHORT', 1), ('ZERO', 0), ('ENOUGH', 100), ('TEXT', '0+10'), ('DUP', 1), ('DUP', 2), ('TWICE', 50)],
                            [('SHORT', 2), ('ZERO', 1), ('ENOUGH', 1), ('TEXT', 1), ('DUP', 1), ('MISSING', 1),
                             ('TWICE', 1), ('TWICE', 1), ('ENOUGH2', 0)])

    def test_evaluation_per_row_and_counts(self):
        # M2: categories replace M1 evaluations. The six rows M1 called NOT_EVALUATED are all EXCEPTION now;
        # TEXT and MISSING get a shortage from an assumed stock of 0, the duplicate rows and the zero-QTY row do not.
        result = self.result()
        self.assertEqual([r.category for r in result.rows], ['SHORTAGE', 'SHORTAGE', 'ENOUGH'] + ['EXCEPTION'] * 6)
        self.assertEqual([result.category_count(c) for c in ('SHORTAGE', 'ENOUGH', 'EXCEPTION')], [2, 1, 6])
        self.assertEqual([r.shortage for r in result.rows], [5, 3, 0, 3, None, 3, None, None, None])
        self.assertEqual(result.calculated_shortage_rows, 4)

    def test_business_rules_unchanged(self):
        result = self.result()
        self.assertEqual(result.rows[1].match_status, 'MATCHED')            # zero stock is still a number, not missing data
        self.assertEqual(result.rows[3].match_status, 'INVALID_STOCK')      # text stock is never executed (M2: assumed 0)
        self.assertEqual(result.rows[3].stock_used, 0)                      # '0+10' is not 10
        self.assertEqual(result.rows[4].match_status, 'DUPLICATE_STOCK')    # duplicate stock is not summed
        self.assertEqual([r.required for r in result.rows[6:8]], [3, 3])    # duplicate BOM rows are not merged
        self.assertTrue(all(r.estimate_status == 'ESTIMATED / UNVERIFIED' and r.bom_status == 'UNVERIFIED_BOM' for r in result.rows))
        self.assertEqual(result.overall_status, 'Verification Required')

    def test_constant_caveat_is_not_repeated_in_row_reasons(self):
        result = self.result()
        # The fixture's assembly name contains "/ MIR", so that one section-specific hint remains.
        self.assertEqual(len(result.rows[2].issues), 1); self.assertIn('装配段', result.rows[2].issues[0])
        self.assertTrue(all(ROW_CAVEAT not in issue and '每件/每套' not in issue for r in result.rows for issue in r.issues))
        self.assertTrue(result.rows[5].issues)  # a specific reason is still given

    def test_assumed_zero_is_never_presented_as_a_stock_record(self):
        # M2: replaces M1's test_export_rows_keep_unknown_empty_and_label_every_row (CSV rows no longer exist).
        # M1 kept unknown stock empty; M2 uses 0 for not-found stock by approved rule, so the guarantee is now that
        # an assumed 0 is always marked, a real 0 never is, and non-authoritative stock stays empty.
        result = self.result(); zero, missing, duplicate = result.rows[1], result.rows[5], result.rows[4]
        self.assertEqual((zero.stock_used, zero.stock_assumed, zero.data_status), (0, False, 'NORMAL'))
        self.assertEqual((missing.stock_used, missing.stock_assumed), (0, True)); self.assertIn('ASSUMED 0', missing.data_status)
        self.assertEqual((duplicate.stock_used, duplicate.shortage, duplicate.original_stock), (None, None, '1 | 2'))
        self.assertTrue(all(r.estimate_status == 'ESTIMATED / UNVERIFIED' for r in result.rows))


class FileAccessTests(TempFiles):
    """P1-4 and the Google Drive review items that can be exercised on any Windows folder."""

    def setUp(self):
        super().setUp()
        workbook(self.stock, [('Stock', stock_rows([('A', 1)]))])
        self.cache = ReadOnlyCache()

    def test_owner_lock_file_detected_without_blocking_read(self):
        self.assertEqual(owner_lock_files(self.stock), ())
        (self.base / '~$stock.xlsx').write_bytes(b'owner')
        book, locks = CheckerService().load(str(self.stock), 'stock')
        self.assertEqual(locks, ('~$stock.xlsx',)); self.assertEqual(book.stock_sheets[0].materials[0].quantity, 1)
        (self.base / '~$stock.xlsx').unlink()
        self.assertEqual(CheckerService().load(str(self.stock), 'stock')[1], ())

    def test_rejected_selections(self):
        lock = self.base / '~$stock.xlsx'; lock.write_bytes(self.stock.read_bytes())
        old = self.base / 'old.xls'; old.write_bytes(self.stock.read_bytes())
        for path in (lock, old, self.base):
            with self.subTest(path=path.name), self.assertRaises(DataReadError):
                self.cache.read(str(path), 'stock')

    def test_xlsm_accepted_and_wrong_role_rejected(self):
        macro = self.base / 'stock.xlsm'; macro.write_bytes(self.stock.read_bytes())
        self.assertEqual(len(self.cache.read(str(macro), 'stock').stock_sheets), 1)
        with self.assertRaises(DataReadError):
            self.cache.read(str(self.stock), 'bom')

    def test_snapshot_records_load_time_and_saved_time(self):
        before = time.time(); book = self.cache.read(str(self.stock), 'stock')
        self.assertGreaterEqual(book.loaded_at, before - 1); self.assertLessEqual(book.loaded_at, time.time() + 1)
        self.assertEqual(book.fingerprint[2], self.stock.stat().st_mtime_ns)
        self.assertEqual(self.cache.read(str(self.stock), 'stock').loaded_at, book.loaded_at)  # cache hit keeps load time

    @unittest.skipUnless(os.name == 'nt', 'Windows share-mode test')
    def test_workbook_held_open_with_shared_read_is_readable(self):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateFileW(str(self.stock), 0xC0000000, 1, None, 3, 0x80, None)  # read/write access, others may only read
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            self.assertEqual(self.cache.read(str(self.stock), 'stock').stock_sheets[0].materials[0].quantity, 1)
        finally:
            kernel.CloseHandle(handle)

    def test_atomic_replace_invalidates_cache(self):
        first = self.cache.read(str(self.stock), 'stock')
        os.replace(workbook(self.base / 'incoming.xlsx', [('Stock', stock_rows([('A', 2)]))]), self.stock)
        second = self.cache.read(str(self.stock), 'stock')
        self.assertIsNot(first, second); self.assertEqual(second.stock_sheets[0].materials[0].quantity, 2)

    def test_real_change_during_read_is_rejected_then_recovers(self):
        real_load = reader.load_workbook
        def load_then_replace(stream, **kwargs):
            book = real_load(stream, **kwargs)
            # Another writer finishes while this read is in progress (sync clients replace, they do not edit in place).
            workbook(self.base / 'stock.xlsx.tmp', [('Stock', stock_rows([('A', 99)]))])
            self.changed = self.base / 'stock.xlsx.tmp'
            return book
        with patch.object(reader, 'load_workbook', load_then_replace), patch.object(reader, 'fingerprint', self.fingerprint_after_swap()):
            with self.assertRaisesRegex(DataReadError, '发生变化'):
                self.cache.read(str(self.stock), 'stock')
        self.assertEqual(self.cache.read(str(self.stock), 'stock').stock_sheets[0].materials[0].quantity, 99)

    def fingerprint_after_swap(self):
        real = reader.fingerprint
        def fingerprint(path):
            changed = getattr(self, 'changed', None)
            if changed is not None and changed.exists():
                os.replace(changed, self.stock)  # the read handle is closed by now, as on a real save
            return real(path)
        return fingerprint

    def test_unavailable_file_fails_then_same_path_recovers(self):
        self.cache.read(str(self.stock), 'stock'); away = self.base / 'away.bin'
        os.replace(self.stock, away)
        with self.assertRaises(DataReadError):
            self.cache.read(str(self.stock), 'stock')
        os.replace(away, self.stock)
        self.assertEqual(self.cache.read(str(self.stock), 'stock').stock_sheets[0].materials[0].quantity, 1)

    def test_truncated_file_is_rejected(self):
        self.stock.write_bytes(self.stock.read_bytes()[:200])
        with self.assertRaises(DataReadError):
            self.cache.read(str(self.stock), 'stock')

    def test_sections_and_area_headings(self):
        rows = bom_rows([('A', 1)])
        rows[23] = {'B': 'Assy Name:', 'E': 'Second section'}; rows[24] = {'B': 2, 'D': 'B', 'E': 'x', 'L': 1}
        workbook(self.bom, [('Product', rows)])
        materials = self.cache.read(str(self.bom), 'bom').products[0].materials
        self.assertEqual([m.section for m in materials], ['Assy-V1 / MIR (unconfirmed)', 'Second section'])
        rows = stock_rows([('A', 1)]); rows[16] = {'A': 'GROUND FLOOR', 'E': 'SCREW STORE'}
        workbook(self.stock, [('Stock', rows)])
        self.assertEqual([m.code for m in self.cache.read(str(self.stock), 'stock').stock_sheets[0].materials], ['A'])


class UiTests(TempFiles):
    def setUp(self):
        super().setUp()
        workbook(self.stock, [('Stock', stock_rows([('SHORT', 1), ('ENOUGH', 100), (51102, 4)]))])
        workbook(self.bom, [('Product A', bom_rows([('SHORT', 2), ('ENOUGH', 1), ('MISSING', 1), ('51102', 1)])),
                            ('Product B', bom_rows([('ENOUGH', 1)]))])
        self.root = tk.Tk(); self.root.withdraw(); self.app = CheckerApp(self.root)
        self.errors = []
        self.error_patch = patch('checker.ui.messagebox.showerror', side_effect=lambda title, text, **kw: self.errors.append(text))
        self.error_patch.start()

    def tearDown(self):
        self.app.close(); self.error_patch.stop(); super().tearDown()

    def finish(self):
        deadline = time.monotonic() + 10
        while self.app.busy and time.monotonic() < deadline:
            self.root.update(); time.sleep(.005)
        self.assertFalse(self.app.busy, 'Background work did not finish')
        self.root.update()

    def load_and_check(self):
        self.app.load_file('stock', str(self.stock)); self.finish()
        self.app.load_file('bom', str(self.bom)); self.finish()
        self.app.product_combo.current(0); self.app.quantity_text.set('3')
        self.app.check_button.invoke(); self.finish()
        self.assertFalse(self.errors); self.assertIsNotNone(self.app.result)

    def tags(self):
        return {self.app.tree.item(i, 'values')[0]: self.app.tree.item(i, 'tags')[0] for i in self.app.tree.get_children()}

    def test_shortage_rows_are_tagged_and_summarised(self):
        # M2: tags are the three categories (red / yellow / default) instead of M1's status tags, and the summary
        # shows category counts instead of M1's evaluation counts.
        self.load_and_check()
        self.assertEqual(self.tags(), {'SHORT': 'SHORTAGE', 'ENOUGH': 'ENOUGH', 'MISSING': 'EXCEPTION', '51102': 'EXCEPTION'})
        self.assertNotEqual(self.app.tree.tag_configure('SHORTAGE', 'background'),
                            self.app.tree.tag_configure('ENOUGH', 'background'))
        summary = self.app.summary.get()
        for expected in ('ESTIMATED / UNVERIFIED', 'SHORTAGE: 1 ', 'ENOUGH: 1 ', 'EXCEPTION: 2 ', 'Total Material Rows: 4',
                         'Total calculated shortage rows: 2', 'Verification Required'):
            self.assertIn(expected, summary)
        self.assertNotIn('READY', summary.upper())
        columns = self.app.tree['columns']; values = self.app.tree.item('0', 'values')
        self.assertEqual((values[columns.index('result')], values[columns.index('shortage')]), ('SHORTAGE', '5'))

    def test_filter_hides_only_no_shortage_rows_and_keeps_result(self):
        self.load_and_check()
        self.app.filter_buttons['EXCEPTION'].invoke()
        self.assertEqual(set(self.tags()), {'MISSING', '51102'}); self.assertIsNotNone(self.app.result)
        self.app.tree.selection_set('3'); self.app.show_details()
        self.assertIn('CODE_TYPE_MISMATCH', self.app.details.get('1.0', 'end'))
        self.app.filter_buttons['All'].invoke(); self.assertEqual(len(self.app.tree.get_children()), 4)

    def test_failed_stock_keeps_bom_and_shows_no_stale_result(self):
        self.load_and_check(); product = self.app.product_text.get()
        self.app.load_file('stock', str(self.base / 'missing.xlsx')); self.finish()
        self.assertEqual(len(self.errors), 1); self.assertIsNone(self.app.result); self.assertEqual(self.app.tree.get_children(), ())
        self.assertIsNone(self.app.stock_book); self.assertIsNotNone(self.app.bom_book)
        self.assertEqual(self.app.product_text.get(), product); self.assertTrue(self.app.product_combo['values'])
        self.assertIn('未加载', self.app.file_status['stock'].get())
        self.app.check_button.invoke()  # cannot check against a file that is not loaded
        self.assertEqual(len(self.errors), 2); self.assertFalse(self.app.busy); self.assertIsNone(self.app.result)

    def test_reload_loads_good_file_when_other_path_is_bad_then_recovers(self):
        self.load_and_check(); away = self.base / 'away.bin'
        os.replace(self.stock, away)
        self.app.reload_button.invoke(); self.finish()
        self.assertEqual(len(self.errors), 1); self.assertIn('库存 Excel', self.errors[0]); self.assertNotIn('BOM Excel', self.errors[0])
        self.assertIsNone(self.app.stock_book); self.assertIsNotNone(self.app.bom_book); self.assertIsNone(self.app.result)
        self.assertEqual(self.app.product_text.get(), self.app.bom_book.products[0].display_name)
        os.replace(away, self.stock)
        self.app.reload_button.invoke(); self.finish()
        self.app.check_button.invoke(); self.finish()  # no re-selection needed
        self.assertEqual(len(self.errors), 1); self.assertEqual(len(self.app.result.rows), 4)

    def test_check_failure_on_one_file_keeps_other_and_clears_result(self):
        self.load_and_check()
        self.bom.write_bytes(b'being replaced')
        self.app.check_button.invoke(); self.finish()
        self.assertEqual(len(self.errors), 1); self.assertIsNone(self.app.result); self.assertEqual(self.app.tree.get_children(), ())
        self.assertIsNotNone(self.app.stock_book); self.assertEqual(self.app.stock_name.get(), 'Stock'); self.assertIsNone(self.app.bom_book)

    def test_file_status_shows_name_times_refresh_and_lock_warning(self):
        self.load_and_check()
        status = self.app.file_status['stock'].get()
        for expected in ('stock.xlsx', '文件保存时间', '成功加载', '文件未变化，沿用已加载数据'):
            self.assertIn(expected, status)
        self.assertIn(time.strftime('%Y-%m-%d'), status); self.assertNotIn('⚠', status)
        (self.base / '~$stock.xlsx').write_bytes(b'owner')
        workbook(self.stock, [('Stock', stock_rows([('SHORT', 9), ('ENOUGH', 100)]))])
        self.app.check_button.invoke(); self.finish()
        status = self.app.file_status['stock'].get()
        self.assertIn('已从文件重新读取', status); self.assertIn('~$stock.xlsx', status); self.assertIn('不能证明存在未保存的修改', status)
        self.assertFalse(self.errors); self.assertEqual(self.app.result.rows[0].shortage, 0)  # warning does not block the check
        self.assertNotIn('⚠', self.app.file_status['bom'].get())

    def test_export_writes_new_file_and_never_a_source_workbook(self):
        # M2: was test_export_writes_new_csv_and_never_a_workbook. The export is now a new .xlsx; the safety
        # properties are the same: nothing without a result, never onto a source workbook, sources unchanged.
        self.assertIsNone(self.app.write_export(str(self.base / 'nothing.xlsx'))); self.assertFalse((self.base / 'nothing.xlsx').exists())
        self.load_and_check(); before = (self.stock.read_bytes(), self.bom.read_bytes())
        self.assertIsNone(self.app.write_export(str(self.stock))); self.assertIsNone(self.app.write_export(str(self.bom)))
        self.assertIsNone(self.app.write_export(str(self.base / 'out.csv'))); self.assertFalse((self.base / 'out.csv').exists())
        self.assertEqual(before, (self.stock.read_bytes(), self.bom.read_bytes())); self.assertEqual(len(self.errors), 3)
        target = self.base / 'out.xlsx'
        with patch('checker.ui.filedialog.asksaveasfilename', return_value=str(target)):
            self.app.export_button.invoke()
        book = load_workbook(target)
        self.assertEqual(book.sheetnames, ['Shortage', 'Exceptions'])
        from checker.report import HEADER_ROW
        self.assertEqual([row[1] for row in book['Shortage'].iter_rows(min_row=HEADER_ROW + 1, values_only=True)], ['SHORT', '51102', 'MISSING', 'ENOUGH'])
        self.assertEqual(before, (self.stock.read_bytes(), self.bom.read_bytes()))

    def test_export_after_input_change_is_refused(self):
        self.load_and_check(); self.app.quantity_text.set('4')
        with patch('checker.ui.filedialog.asksaveasfilename', return_value=str(self.base / 'stale.xlsx')):  # M2: .xlsx
            self.app.export_button.invoke()
        self.assertFalse((self.base / 'stale.xlsx').exists()); self.assertEqual(len(self.errors), 1)


if __name__ == '__main__':
    unittest.main()
