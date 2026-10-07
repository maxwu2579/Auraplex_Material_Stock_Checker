"""M2.1 presentation tests. Existing material rules remain in the original suites."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tkinter as tk
import unittest

from checker.core import EXCEPTION, SHORTAGE, ENOUGH
from checker.presentation import ellipsize
from checker.report import build_report, HEADER_ROW
from checker.report_style import DARK_AMBER, DARK_RED, RED, YELLOW, METADATA_START, METADATA_VALUE_COLUMN
from tests.test_m2 import Files, UiFlowTests


class PresentationTests(UiFlowTests):
    # Reuse setup/workflow only, not inherited test methods (those already run once in test_m2).
    def test_card_counts_and_primary_action(self):
        self.assertEqual(self.app.check_button['text'], 'CHECK MATERIALS')
        self.assertEqual(self.app.filter_category.get(), 'All')
        self.assertEqual(set(self.app.summary_counts), {'total', SHORTAGE, EXCEPTION, ENOUGH})
        self.assertFalse(self.app.detail_frame.winfo_manager())
        self.load(); self.check()
        self.assertEqual([self.app.summary_counts[key].get() for key in ('total', SHORTAGE, EXCEPTION, ENOUGH)], ['13', '3', '8', '2'])
        self.assertIn('Verification Required', self.app.verification_label['text'])
        self.assertEqual(self.app.file_view['stock']['button']['text'], 'Change…')

    def test_filters_preserve_counts_order_and_export_payload(self):
        self.load(); self.check()
        result = self.app.result
        stock, bom = self.app.stock_book, self.app.bom_book
        baseline = build_report(result, stock, bom, datetime(2026, 10, 7))
        payload = lambda book: {s.title: list(s.iter_rows(min_row=HEADER_ROW, values_only=True)) for s in book}
        counts = [v.get() for v in self.app.summary_counts.values()]
        for category, expected in ((SHORTAGE, 3), (EXCEPTION, 8), (ENOUGH, 2), ('All', 13)):
            self.app.filter_buttons[category].invoke()
            shown = self.shown()
            self.assertEqual(len(shown), expected)
            self.assertTrue(all(category == 'All' or row['result'] == category for row in shown))
            self.assertIs(self.app.result, result)
            self.assertEqual(counts, [v.get() for v in self.app.summary_counts.values()])
            self.assertEqual(payload(baseline), payload(build_report(result, stock, bom, datetime(2026, 10, 7))))

    def test_details_only_for_selection_and_keep_raw_provenance(self):
        self.load(); self.check()
        self.assertFalse(self.app.detail_frame.winfo_manager())
        item = next(i for i in self.app.tree.get_children() if self.app.tree.item(i, 'values')[0] == 'TEXT')
        self.app.tree.selection_set(item); self.app.show_details()
        self.assertEqual(self.app.detail_frame.winfo_manager(), 'grid')
        text = self.app.details.get('1.0', 'end')
        for part in ('Material ID: TEXT', 'Description:', '0+10', 'INVALID_STOCK', str(self.bom.resolve()), "'DEMO-200-A-40W '", '原值=1'):
            self.assertIn(part, text)
        self.app.filter_buttons[ENOUGH].invoke()
        self.assertFalse(self.app.detail_frame.winfo_manager())
        self.app.quantity_text.set('4')
        self.assertTrue(all(v.get() == '—' for v in self.app.summary_counts.values()))

    def test_card_paths_ellipsis_and_full_details(self):
        self.load(); self.check()
        path = str(self.stock.resolve())
        self.assertIn(path, self.app._file_details('stock'))
        shortened = ellipsize(path, 120, ('Segoe UI', 9), middle=True)
        self.assertIn('…', shortened)
        self.assertTrue(shortened.endswith(path[-4:]))
        (self.base / '~$storage.xlsx').write_bytes(b'owner')
        self.check()
        self.assertEqual(self.app.file_view['stock']['warning']['text'], 'File may currently be open in Excel')
        self.assertIn('不能证明存在未保存', self.app._file_details('stock'))

    def test_export_feedback_is_nonmodal_and_complete(self):
        self.load(); self.check()
        written = self.app.write_export(self.base / 'report.xlsx')
        self.assertEqual(self.app.status.get(), 'Report exported successfully.')
        self.assertEqual(self.app.export_path.get(), str(written))
        self.assertEqual(self.app.export_feedback.winfo_manager(), 'grid')

    def test_small_window_and_font_scaling_keep_actions_visible(self):
        # Tk font scaling simulation; this does not change Windows display settings.
        self.load(); self.check()
        self.root.deiconify()
        sizes = ((1280, 720), (1366, 728), (960, 600))
        for scale in (1, 1.25, 1.5):
            self.root.tk.call('tk', 'scaling', 96 / 72 * scale)
            for width, height in sizes:
                self.root.geometry(f'{width}x{height}+0+0'); self.root.update()
                with self.subTest(scale=scale, size=(width, height)):
                    for control in (self.app.check_button, self.app.export_button, self.app.reload_button):
                        self.assertTrue(control.winfo_ismapped())
                        x, y = control.winfo_rootx() - self.root.winfo_rootx(), control.winfo_rooty() - self.root.winfo_rooty()
                        self.assertGreaterEqual(x, 0); self.assertGreaterEqual(y, 0)
                        self.assertLessEqual(x + control.winfo_width(), self.root.winfo_width())
                        self.assertLessEqual(y + control.winfo_height(), self.root.winfo_height())
                    self.assertGreater(self.app.tree.winfo_height(), 60)
        self.root.withdraw()


# Avoid discovering the base class's five tests a second time through this subclass.
for _name in tuple(vars(UiFlowTests)):
    if _name.startswith('test_'):
        setattr(PresentationTests, _name, None)
del UiFlowTests


class FreshWindowLayoutTests(Files):
    def test_fresh_scaled_windows_and_selected_details_keep_table_usable(self):
        stock, bom = self.books()
        result = self.result()
        for scale in (1, 1.25, 1.5):
            for size in ('1280x720', '1366x728', '960x600'):
                root = tk.Tk()
                root.tk.call('tk', 'scaling', 96 / 72 * scale)
                from checker.ui import CheckerApp
                app = CheckerApp(root)
                try:
                    root.geometry(size + '+0+0')
                    app.stock_path.set(stock.path); app.bom_path.set(bom.path)
                    app._apply('stock', (stock, ('~$storage.xlsx',), None, False))
                    app._apply('bom', (bom, (), None, False))
                    app.render_result(result); root.update()
                    with self.subTest(scale=scale, size=size):
                        for button in (app.check_button, app.export_button, app.reload_button):
                            x, y = button.winfo_rootx() - root.winfo_rootx(), button.winfo_rooty() - root.winfo_rooty()
                            self.assertLessEqual(x + button.winfo_width(), root.winfo_width())
                            self.assertLessEqual(y + button.winfo_height(), root.winfo_height())
                        self.assertGreaterEqual(app.tree.winfo_height(), 96)
                        app.tree.selection_set('0'); app.show_details(); root.update()
                        self.assertGreaterEqual(app.tree.winfo_height(), 80)
                        self.assertTrue(app.detail_frame.winfo_ismapped() or
                                        app.row_detail_window is not None and app.row_detail_window.winfo_exists())
                        for col in app.tree['columns']:
                            self.assertGreaterEqual(app.tree.column(col, 'width'), app.tree.column(col, 'minwidth'))
                finally:
                    app.close()


class ExportStyleTests(Files):
    def setUp(self):
        super().setUp()
        self.stock_book, self.bom_book = self.books()
        self.book = build_report(self.result(), self.stock_book, self.bom_book, datetime(2026, 10, 7, 9, 30, 5))

    def test_report_titles_metadata_and_summary(self):
        sheet = self.book['Shortage']
        self.assertEqual(sheet['A1'].value, 'Material Requirement & Stock Report')
        self.assertEqual([sheet.cell(12, col).value for col in (1, 4, 7, 10)], [13, 3, 8, 2])
        self.assertEqual(sheet['G4'].value, 'storage.xlsx')
        self.assertEqual(sheet['G6'].value, 'bom.xlsx')
        metadata = {sheet.cell(r, 1).value: sheet.cell(r, METADATA_VALUE_COLUMN).value for r in range(METADATA_START, METADATA_START+5)}
        self.assertEqual(metadata['Storage File'], self.stock_book.path)
        self.assertEqual(metadata['BOM File'], self.bom_book.path)
        self.assertEqual(self.book['Exceptions']['A11'].value, 'These rows require manual review.')
        self.assertIn('Total Exceptions: 8', self.book['Exceptions']['A12'].value)
        self.assertIn('DUPLICATE_BOM: 2', self.book['Exceptions']['A13'].value)

    def test_headers_alignment_borders_freeze_and_filters(self):
        for sheet in self.book:
            self.assertEqual(sheet.freeze_panes, 'A16')
            self.assertTrue(sheet.auto_filter.ref.startswith('A15:'))
            self.assertFalse(sheet.sheet_view.showGridLines)
            for cell in sheet[HEADER_ROW]:
                self.assertTrue(cell.font.bold)
                self.assertEqual(cell.fill.fgColor.rgb[-6:], 'EAF0F5')
                self.assertEqual(cell.alignment.horizontal, 'center')
            self.assertEqual(sheet['B16'].alignment.horizontal, 'left')
            self.assertEqual(sheet['D16'].alignment.horizontal, 'right')
            self.assertEqual(sheet['B16'].border.bottom.color.rgb[-6:], 'E2E7EC')
            self.assertGreaterEqual(sheet.column_dimensions['B'].width, 24)
            self.assertGreaterEqual(sheet.column_dimensions['C'].width, 42)

    def test_shortage_and_exception_cell_styles(self):
        sheet = self.book['Shortage']
        for row in sheet.iter_rows(min_row=HEADER_ROW+1):
            category = row[8].value
            for cell in row:
                if category == ENOUGH:
                    self.assertIsNone(cell.fill.fill_type)
                else:
                    self.assertEqual(cell.fill.fgColor.rgb[-6:], RED if category == SHORTAGE else YELLOW)
            if row[7].value and row[7].value > 0:
                self.assertTrue(row[7].font.bold)
                self.assertEqual(row[7].font.color.rgb[-6:], DARK_RED)
            if category == EXCEPTION:
                self.assertEqual(row[9].font.color.rgb[-6:], DARK_AMBER)
        for row in self.book['Exceptions'].iter_rows(min_row=HEADER_ROW+1):
            self.assertTrue(all(c.fill.fgColor.rgb[-6:] == YELLOW for c in row))
            self.assertEqual(row[6].font.color.rgb[-6:], DARK_AMBER)

    def test_table_payload_matches_frozen_m2_baseline(self):
        # Baseline digests were captured before any M2.1 edit. Only the temporary source path is replaced.
        # v1.0.0: the fixture's product sheet was renamed to a synthetic ID for the public repository; the digests were
        # re-derived after checking the payload equals the frozen baseline once that one name is substituted back.
        expected = BASELINE_DIGESTS
        for sheet in self.book:
            rows = [list(row) for row in sheet.iter_rows(min_row=HEADER_ROW, values_only=True)]
            if sheet.title == 'Exceptions':
                column = rows[0].index('Source File')
                for row in rows[1:]:
                    self.assertEqual(row[column], str(self.bom.resolve()))
                    row[column] = '<BOM_FILE>'
            digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
            self.assertEqual(digest, expected[sheet.title])


BASELINE_DIGESTS = {'Shortage': 'cb60ecee86722bcbfbd533c5aa66e5e92b7f740020f655661ebb4ba34c80c9d0', 'Exceptions': '311bf87ae97b1eb3ed91087261f2d7dc6b0fad5ce3f767b838be5180be36ba73'}


if __name__ == '__main__':
    unittest.main()
