import ctypes
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from checker.core import DataReadError, Material, Product, Source, StockSheet, check_materials, normalize_code, production_quantity, search_products, select_product
from checker.reader import ReadOnlyCache
from checker.service import CheckerService
from tests.fixtures import workbook, stock_rows, bom_rows


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.stock=workbook(self.base/'stock.xlsx',[('Stock',stock_rows([('A-01-K',10),('EMPTY',None),('TEXT','0+10'),('DUP',3),('DUP',7)]))])
        self.bom=workbook(self.base/'bom.xlsx',[('BOM TEMPLATE',bom_rows([])),('Product A ',bom_rows([('a-01-k',2),('MISSING',1),('EMPTY',1),('TEXT',1),('DUP',1)])),('Product B',bom_rows([('A-01-K',3)],18))])
        self.cache=ReadOnlyCache()

    def tearDown(self):self.tmp.cleanup()

    def checked(self):
        return check_materials(self.cache.read(str(self.bom),'bom').products[0],self.cache.read(str(self.stock),'stock').stock_sheets[0],3)

    def test_match_estimated_arithmetic(self):
        r=self.checked().rows[0]
        self.assertEqual((r.match_status,r.required,r.delta,r.shortage),('MATCHED',6,4,0))
        self.assertEqual(r.bom_status,'UNVERIFIED_BOM')
        self.assertEqual(r.estimate_status,'ESTIMATED / UNVERIFIED')

    def test_unknown_stock_not_zero(self):
        # Updated for M2 (approved rule 5.2 / 19): a material missing from Storage is calculated with Stock = 0.
        # M0/M1 asserted delta and shortage were empty. The zero must stay visibly assumed and the row an EXCEPTION,
        # never a normal SHORTAGE.
        r=self.checked().rows[1]
        self.assertEqual(r.match_status,'NOT_FOUND');self.assertEqual(r.stock,())
        self.assertEqual((r.stock_used,r.stock_assumed,r.shortage),(0,True,3))
        self.assertEqual((r.category,r.data_status),('EXCEPTION','STOCK_NOT_FOUND / ASSUMED 0'))

    def test_blank_stock(self):
        # Updated for M2 (approved rule 5.3 / 19): blank LIVE STOCK is calculated with an assumed 0 and flagged.
        # M0/M1 asserted delta was empty.
        r=self.checked().rows[2]
        self.assertEqual(r.match_status,'INVALID_STOCK');self.assertIsNone(r.stock[0].quantity)
        self.assertEqual((r.stock_used,r.stock_assumed,r.shortage),(0,True,3))
        self.assertEqual((r.category,r.data_status),('EXCEPTION','BLANK_STOCK / ASSUMED 0'))

    def test_text_stock_not_evaluated(self):
        # Updated for M2 (approved rule 5.4 / 19): text stock is still never evaluated ('0+10' is not 10) and the
        # raw value is kept, but the row is now calculated with an assumed 0. M0/M1 asserted delta was empty.
        r=self.checked().rows[3]
        self.assertEqual(r.match_status,'INVALID_STOCK');self.assertEqual(r.stock[0].quantity,'0+10')
        self.assertEqual((r.stock_used,r.stock_assumed,r.shortage),(0,True,3));self.assertEqual(r.original_stock,'0+10')
        self.assertEqual((r.category,r.data_status),('EXCEPTION','INVALID_STOCK / ASSUMED 0'))

    def test_duplicate_stock_never_summed(self):
        r=self.checked().rows[4]
        self.assertEqual(r.match_status,'DUPLICATE_STOCK');self.assertEqual(len(r.stock),2);self.assertIsNone(r.delta)

    def test_sheet_selection_preserves_original_name(self):
        products=self.cache.read(str(self.bom),'bom').products
        self.assertEqual([p.sheet_name for p in products],['Product A ','Product B'])
        self.assertEqual(products[0].header_row,21);self.assertEqual(products[1].header_row,18)
        self.assertEqual(select_product(products,products[0].display_name).sheet_name,'Product A ')
        self.assertIsNone(select_product(products,'Product'))
        self.assertIsNone(select_product(products,'invented'))

    def test_product_search_case_insensitive(self):
        products=self.cache.read(str(self.bom),'bom').products
        self.assertEqual([p.sheet_name for p in search_products(products,'DUCT a')],['Product A '])
        self.assertEqual(len(search_products(products,'')),2)

    def test_sheet_display_collision_is_disambiguated(self):
        workbook(self.bom,[('Same',bom_rows([('A',1)])),('Same ',bom_rows([('B',1)]))])
        products=self.cache.read(str(self.bom),'bom').products
        self.assertIsNone(select_product(products,'Same'))
        self.assertNotEqual(products[0].display_name,products[1].display_name)
        self.assertEqual(select_product(products,products[1].display_name).sheet_name,'Same ')

    def test_production_quantity_invalid(self):
        for val in ('','0','-1','1.2','1e2','true','1 2','+2','１'):
            with self.subTest(value=val), self.assertRaises(ValueError):production_quantity(val)
        self.assertEqual(production_quantity(' 12 '),12)
        self.assertEqual(production_quantity('1000000000'),1000000000)

    def test_missing_file(self):
        with self.assertRaises(DataReadError):self.cache.read(str(self.base/'absent.xlsx'),'stock')

    @unittest.skipUnless(os.name=='nt','Windows exclusive handle test')
    def test_exclusively_locked_file(self):
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
        kernel.CreateFileW.restype=ctypes.c_void_p
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.CreateFileW(str(self.stock),0x80000000,0,None,3,0x80,None)
        self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
        try:
            with self.assertRaises(DataReadError):self.cache.read(str(self.stock),'stock')
        finally:kernel.CloseHandle(handle)

    def test_unsupported_old_stock_mapping_rejected(self):
        rows=stock_rows([('A',10)]);rows[13]['N']=rows[13].pop('O');rows[15]['N']=rows[15].pop('O')
        workbook(self.stock,[('Old',rows)])
        with self.assertRaises(DataReadError):self.cache.read(str(self.stock),'stock')

    def test_malformed_file(self):
        self.stock.write_bytes(b'not-an-excel-file')
        with self.assertRaises(DataReadError):self.cache.read(str(self.stock),'stock')

    def test_source_read_only_and_no_media_access(self):
        workbook(self.stock,[('Stock',stock_rows([('A',1)]))],media=b'image-payload')
        original=self.stock.read_bytes();real_open=ZipFile.open
        def guarded(archive,name,*args,**kwargs):
            filename=name.filename if hasattr(name,'filename') else name
            self.assertFalse(filename.startswith('xl/media/'))
            return real_open(archive,name,*args,**kwargs)
        with patch.object(ZipFile,'open',guarded):self.cache.read(str(self.stock),'stock')
        self.assertEqual(self.stock.read_bytes(),original)

    def test_cache_reused_and_force_reload(self):
        first=self.cache.read(str(self.stock),'stock')
        self.assertIs(first,self.cache.read(str(self.stock),'stock'))
        self.assertEqual(self.cache.parse_count,1)
        self.cache.read(str(self.stock),'stock',force=True)
        self.assertEqual(self.cache.parse_count,2)

    def test_cache_invalidation_with_preserved_size_mtime(self):
        first=self.cache.read(str(self.stock),'stock');s=self.stock.stat()
        workbook(self.stock,[('Stock',stock_rows([('A-01-K',11),('EMPTY',None),('TEXT','0+10'),('DUP',3),('DUP',7)]))])
        os.utime(self.stock,ns=(s.st_atime_ns,s.st_mtime_ns))
        self.assertEqual(self.stock.stat().st_size,s.st_size)
        second=self.cache.read(str(self.stock),'stock')
        self.assertIsNot(first,second);self.assertEqual(second.stock_sheets[0].materials[0].quantity,11)

    def test_source_change_during_read_rejected(self):
        from checker.reader import fingerprint
        before=fingerprint(self.stock)
        with patch('checker.reader.fingerprint',side_effect=[before,(*before[:-1],('changed',))]):
            with self.assertRaisesRegex(DataReadError,'发生变化'):self.cache.read(str(self.stock),'stock')

    def test_formula_quantities_not_recalculated_or_used(self):
        workbook(self.stock,[('Stock',stock_rows([('A',('f','2+7'))]))])
        workbook(self.bom,[('Product',bom_rows([('A',('f','2+7'))]))])
        r=self.checked().rows[0]
        self.assertEqual(r.match_status,'INVALID_STOCK');self.assertIsNone(r.required);self.assertIsNone(r.delta)

    def test_zero_negative_boolean_quantities(self):
        for value in (0,-1,('b','1')):
            workbook(self.bom,[('Product',bom_rows([('A-01-K',value)]))])
            r=self.checked().rows[0]
            self.assertIsNone(r.required);self.assertIsNone(r.delta)

    def test_zero_stock_is_valid(self):
        workbook(self.stock,[('Stock',stock_rows([('A-01-K',0)]))])
        r=self.checked().rows[0];self.assertEqual(r.match_status,'MATCHED');self.assertEqual(r.shortage,6)

    def test_bom_duplicates_not_merged_no_delta(self):
        workbook(self.bom,[('Product',bom_rows([('A-01-K',2),('A-01-K',3)]))])
        result=self.checked()
        self.assertEqual(len(result.rows),2);self.assertEqual([r.required for r in result.rows],[6,9])
        self.assertTrue(all(r.delta is None for r in result.rows));self.assertEqual(result.counts['MATCHED'],1)

    def test_missing_bom_code_retained_and_flagged(self):
        workbook(self.bom,[('Product',bom_rows([(None,2)]))])
        r=self.checked().rows[0];self.assertEqual(r.match_status,'UNVERIFIED_BOM');self.assertIsNone(r.delta)

    def test_normalization_preserves_significant_parts(self):
        self.assertEqual(normalize_code('  ａｂ－１２－ＭＩＲ－ｋ  '),'AB-12-MIR-K')
        self.assertNotEqual(normalize_code('B 51102'),normalize_code('B51102'))
        self.assertNotEqual(normalize_code('A-V1-K'),normalize_code('A-V2-K'))
        self.assertEqual(normalize_code(123),'')

    def test_normalized_stock_collision_is_duplicate(self):
        workbook(self.stock,[('Stock',stock_rows([('a-01-k',1),(' Ａ-０１-Ｋ ',2)]))])
        self.assertEqual(self.checked().rows[0].match_status,'DUPLICATE_STOCK')

    def test_multi_stock_sheets_not_merged(self):
        workbook(self.stock,[('One',stock_rows([('A-01-K',3)])),('Two',stock_rows([('A-01-K',5)]))])
        service=CheckerService()
        s,b,r=service.run(str(self.stock),'Two',str(self.bom),'Product A ','1')
        self.assertEqual(len(s.stock_sheets),2);self.assertEqual(r.rows[0].stock[0].quantity,5)

    def test_provenance_and_overall_verification(self):
        result=self.checked();source=result.rows[0].bom.source
        self.assertEqual(source.sheet,'Product A ');self.assertEqual(source.row,22)
        self.assertEqual(source.path,str(self.bom.resolve()))
        self.assertEqual(result.overall_status,'Verification Required');self.assertEqual(result.verification_required,5)

    def test_formula_identifiers_never_used_as_material_codes(self):
        workbook(self.stock,[('Stock',stock_rows([(('f','"A"'),5)]))])
        workbook(self.bom,[('Product',bom_rows([(('f','"A"'),1)]))])
        r=self.checked().rows[0]
        self.assertEqual(r.match_status,'UNVERIFIED_BOM');self.assertEqual(r.stock,());self.assertIsNone(r.delta)

    def test_negative_boolean_and_error_stock_not_usable(self):
        for value in (-1,('b','1'),('e','#VALUE!'),'10'):
            workbook(self.stock,[('Stock',stock_rows([('A-01-K',value)]))])
            self.assertEqual(self.checked().rows[0].match_status,'INVALID_STOCK')

    def test_code_only_incomplete_stock_record_is_not_silently_dropped(self):
        rows=stock_rows([]);rows[15]={'E':'A-01-K'}
        workbook(self.stock,[('Stock',rows)])
        self.assertEqual(self.checked().rows[0].match_status,'INVALID_STOCK')

    def test_header_beyond_documented_search_range_is_rejected(self):
        workbook(self.bom,[('Product',bom_rows([('A',1)],101))])
        with self.assertRaises(DataReadError):self.cache.read(str(self.bom),'bom')


if __name__=='__main__':unittest.main()
