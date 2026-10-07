import tempfile
import time
import tkinter as tk
from pathlib import Path
import unittest
from unittest.mock import patch

from checker.ui import CheckerApp
from tests.fixtures import workbook, bom_rows, stock_rows


class TkWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.stock=workbook(self.base/'stock.xlsx',[('Stock',stock_rows([('A',8)]))])
        self.bom=workbook(self.base/'bom.xlsx',[('Product A ',bom_rows([('A',2)])),('Product B',bom_rows([('A',1)]))])
        self.root=tk.Tk();self.root.withdraw();self.app=CheckerApp(self.root)
        self.errors=[]
        self.error_patch=patch('checker.ui.messagebox.showerror',side_effect=lambda title,text,**kw:self.errors.append(text))
        self.error_patch.start()

    def tearDown(self):
        self.app.close();self.error_patch.stop();self.tmp.cleanup()

    def finish(self):
        deadline=time.monotonic()+10
        while self.app.busy and time.monotonic()<deadline:
            self.root.update();time.sleep(.005)
        self.assertFalse(self.app.busy,'Background work did not finish')
        self.root.update()

    def load(self):
        for role,path in [('stock',self.stock),('bom',self.bom)]:
            self.app.load_file(role,str(path));self.finish()
        self.assertFalse(self.errors)

    def check_first(self):
        self.app.product_combo.current(0);self.app.quantity_text.set('3')
        self.app.check_button.invoke();self.finish()

    def test_browse_search_select_check_provenance(self):
        with patch('checker.ui.filedialog.askopenfilename',side_effect=[str(self.stock),str(self.bom)]):
            self.app.browse('stock');self.finish();self.app.browse('bom');self.finish()
        self.app.product_text.set('duct a');self.app.product_combo.event_generate('<KeyRelease>');self.app._search()
        self.assertEqual(len(self.app.product_combo['values']),1)
        self.app.product_combo.current(0);self.app.product_combo.event_generate('<<ComboboxSelected>>')
        self.app.quantity_text.set('3');self.app.check_button.invoke();self.finish()
        self.assertFalse(self.errors);self.assertEqual(len(self.app.tree.get_children()),1)
        self.assertEqual(self.app.result.rows[0].required,6)
        self.app.tree.selection_set('0');self.app.show_details()
        details=self.app.details.get('1.0','end')
        self.assertIn(str(self.bom.resolve()),details);self.assertIn("'Product A '",details)
        self.assertIn('Verification Required',self.app.summary.get())
        self.assertNotIn('READY FOR PRODUCTION',self.app.summary.get())

    def test_input_change_invalidates_existing_results(self):
        self.load();self.check_first();self.assertIsNotNone(self.app.result)
        self.app.quantity_text.set('4')
        self.assertIsNone(self.app.result);self.assertEqual(len(self.app.tree.get_children()),0)

    def test_nonexistent_product_and_invalid_quantity_block_check(self):
        self.load();self.app.product_text.set('invented');self.app.check_button.invoke()
        self.assertIsNone(self.app.result);self.assertIn('实际存在',self.errors[-1])
        self.app.product_combo.current(0);self.app.quantity_text.set('0');self.app.check_button.invoke()
        self.assertIn('正整数',self.errors[-1]);self.assertFalse(self.app.busy)

    def test_failed_file_load_clears_old_results(self):
        self.load();self.check_first()
        self.app.load_file('stock',str(self.base/'missing.xlsx'));self.finish()
        self.assertTrue(self.errors);self.assertIsNone(self.app.result)
        self.assertEqual(len(self.app.tree.get_children()),0)

    def test_updated_source_refreshes_check_without_reselection(self):
        self.load();self.check_first();self.assertEqual(self.app.result.rows[0].stock[0].quantity,8)
        workbook(self.stock,[('Stock',stock_rows([('A',1)]))])
        self.app.check_button.invoke();self.finish()
        self.assertEqual(self.app.result.rows[0].stock[0].quantity,1)
        self.assertEqual(self.app.result.rows[0].shortage,5)
        self.app.reload_button.invoke();self.finish()
        self.assertIsNone(self.app.result);self.assertEqual(self.app.product_text.get(),self.app.bom_book.products[0].display_name)

    def test_changed_source_removed_sheet_fails_closed(self):
        self.load();self.check_first()
        workbook(self.bom,[('New Sheet',bom_rows([('A',1)]))])
        self.app.check_button.invoke();self.finish()
        self.assertTrue(self.errors);self.assertIsNone(self.app.result)
        self.assertEqual(len(self.app.tree.get_children()),0)
        self.assertEqual(tuple(self.app.product_combo['values']),())

    def test_background_io_disables_controls_but_keeps_event_loop_alive(self):
        with patch.object(self.app.service.cache,'read',side_effect=lambda *a,**kw:(time.sleep(.2),None)[1]):
            self.app._start(lambda:self.app.service.cache.read('x','stock'),lambda _:None,'test')
            self.assertTrue(self.app.busy);self.assertTrue(self.app.check_button.instate(['disabled']))
            ticks=[];self.root.after(10,lambda:ticks.append(True));self.finish()
            self.assertTrue(ticks);self.assertFalse(self.app.check_button.instate(['disabled']))


if __name__=='__main__':unittest.main()
