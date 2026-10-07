from .core import DataReadError, check_materials, production_quantity
from .reader import ReadOnlyCache, owner_lock_files


class CheckerService:
    def __init__(self):
        self.cache = ReadOnlyCache()

    def load(self, path, role, force=False, cancelled=None):
        """One workbook plus the Excel owner files seen beside it at this moment."""
        book = self.cache.read(path, role, force=force, cancelled=cancelled)
        return book, owner_lock_files(book.path)

    @staticmethod
    def find_stock_sheet(stock, stock_name):
        return next((s for s in stock.stock_sheets if s.name == stock_name), None)

    @staticmethod
    def find_product(bom, product_name):
        return next((p for p in bom.products if p.sheet_name == product_name), None)

    def run(self, stock_path, stock_name, bom_path, product_name, quantity_text, cancelled=None):
        count = production_quantity(quantity_text)
        stock = self.cache.read(stock_path, "stock", cancelled=cancelled)
        bom = self.cache.read(bom_path, "bom", cancelled=cancelled)
        product = self.find_product(bom, product_name)
        selected_stock = self.find_stock_sheet(stock, stock_name)
        if product is None or selected_stock is None:
            raise DataReadError("源文件更新后，所选 Sheet 不再存在/不符合表头。请 Reload Files 并重新选择。")
        return stock, bom, check_materials(product, selected_stock, count)
