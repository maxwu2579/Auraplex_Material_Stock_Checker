"""Writes a check result to a NEW .xlsx report. Source workbooks are never opened for writing."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import os
from pathlib import Path
import re

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font

from .core import CheckResult, EXCEPTION, ROW_CAVEAT, SHORTAGE, WorkbookData
from .report_style import FILLS, HEADER_ROW, METADATA_START, NOTE_ROW, format_report


class ReportError(ValueError):
    """The chosen report destination is not acceptable; nothing was written."""


ALL_HEADER = ("No.", "Material ID", "Description", "BOM QTY", "Production Quantity", "Required", "Stock", "Shortage",
              "Result", "Data Status", "Rack", "Level", "Original Stock Value", "Source Sheet", "Source Row")
EXCEPTION_HEADER = ("No.", "Material ID", "Description", "Required", "Assumed / Used Stock", "Calculated Shortage",
                    "Exception Type", "Original Value", "Details", "Rack", "Level", "Source File", "Source Sheet", "Source Row")
NOTE = ("Calculated from the files as last saved. Not a production approval. Rows marked EXCEPTION need a person to check the "
        "source data; where Data Status says ASSUMED 0, the stock value 0 was assumed, not read from Storage.")


def default_filename(product_id: str, quantity: int, when: datetime) -> str:
    # Only characters Windows forbids in file names are replaced; the Product ID shown elsewhere is unchanged.
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", product_id).strip(" .") or "product"
    return f"Material_Check_{safe}_QTY{quantity}_{when:%Y%m%d_%H%M%S}.xlsx"


def _same_file(a: Path, b: Path) -> bool:
    try:
        if a.exists() and b.exists() and os.path.samefile(a, b):
            return True
    except OSError:
        pass
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def safe_target(path: str | Path, sources) -> Path:
    """A path that is a .xlsx, is not a source workbook, and does not exist yet (a number is added if needed)."""
    target = Path(path)
    if target.suffix.lower() != ".xlsx":
        raise ReportError("报告只能保存为新的 .xlsx 文件。")
    if target.name.startswith("~$"):
        raise ReportError("不能使用 ~$ 开头的 Excel 占用标记文件名。")
    if any(_same_file(target, Path(source)) for source in sources):
        raise ReportError("导出目标是当前的 Storage 或 BOM 源工作簿；已拒绝，源文件不会被覆盖。")
    candidate, n = target, 1
    while candidate.exists():  # never overwrite anything, including unrelated workbooks
        n += 1
        candidate = target.with_name(f"{target.stem} ({n}){target.suffix}")
    return candidate


def _value(value):
    """Cell value: numbers stay numbers, everything else becomes text that Excel cannot run."""
    if value is None or isinstance(value, bool):
        return None if value is None else str(value)
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (int, float)):
        return value
    return ILLEGAL_CHARACTERS_RE.sub("", str(value))


def _write_row(sheet, row, values, fill=None, bold=False):
    for column, value in enumerate(values, 1):
        cell = sheet.cell(row=row, column=column, value=_value(value))
        if isinstance(cell.value, str) and cell.data_type == "f":
            cell.data_type = "s"  # text copied from a source workbook must never become a live formula
        if fill is not None:
            cell.fill = fill
        if bold:
            cell.font = Font(bold=True)


def _joined(values):
    return " | ".join("" if v is None else str(v) for v in values)


def _original_value(r):
    parts = []
    if "INVALID_MATERIAL_ID" in r.exceptions or "CODE_TYPE_MISMATCH" in r.exceptions:
        parts.append(f"BOM Material ID: {r.bom.code!r}")
    if "INVALID_BOM_QTY" in r.exceptions:
        parts.append(f"BOM QTY: {'(blank)' if r.bom.quantity is None else r.bom.quantity}")
    if r.stock:
        parts.append(f"Storage LIVE STOCK: {r.original_stock}")
    elif "STOCK_NOT_FOUND" in r.exceptions:
        parts.append("Storage: no record")
    return "; ".join(parts)


def _details(r):
    where = _joined(f"{s.source.sheet}!row {s.source.row} (code {s.code!r})" for s in r.stock)
    return " ".join(r.issues) + (f" Storage records: {where}." if where else " Storage records: none.") + \
        (f" Assembly section: {r.bom.section}." if r.bom.section else "")


def build_report(result: CheckResult, stock_book: WorkbookData, bom_book: WorkbookData, generated: datetime) -> Workbook:
    book = Workbook()
    rows = result.sorted_rows
    for sheet, title in ((book.active, "Shortage"), (book.create_sheet(), "Exceptions")):
        sheet.title = title
        for row, (label, value) in enumerate((("Product ID", result.product.display_name),
                                              ("Production Quantity", result.production_count),
                                              ("Storage File", stock_book.path), ("BOM File", bom_book.path),
                                              ("Generated Time", generated.strftime("%Y-%m-%d %H:%M:%S"))), METADATA_START):
            _write_row(sheet, row, (label, None, value))
            sheet.cell(row=row, column=1).font = Font(bold=True)
        _write_row(sheet, NOTE_ROW, (NOTE + " " + ROW_CAVEAT,))
    everything, exceptions = book["Shortage"], book["Exceptions"]
    _write_row(everything, HEADER_ROW, ALL_HEADER, bold=True)
    for n, r in enumerate(rows, 1):
        _write_row(everything, HEADER_ROW + n,
                   (n, r.bom.code, r.bom.description, r.bom.quantity, result.production_count, r.required, r.stock_used,
                    r.shortage, r.category, r.data_status, _joined(s.rack for s in r.stock), _joined(s.level for s in r.stock),
                    r.original_stock, r.bom.source.sheet, r.bom.source.row), fill=FILLS.get(r.category))
    _write_row(exceptions, HEADER_ROW, EXCEPTION_HEADER, bold=True)
    for n, r in enumerate((r for r in rows if r.category == EXCEPTION), 1):
        _write_row(exceptions, HEADER_ROW + n,
                   (n, r.bom.code, r.bom.description, r.required, r.stock_used, r.shortage, r.data_status, _original_value(r),
                    _details(r), _joined(s.rack for s in r.stock), _joined(s.level for s in r.stock), r.bom.source.path,
                    r.bom.source.sheet, r.bom.source.row))
    format_report(book, result, stock_book, bom_book, _write_row)
    return book


def save_report(path: str | Path, result: CheckResult, stock_book: WorkbookData, bom_book: WorkbookData,
                generated: datetime | None = None) -> Path:
    """Write the report to a new file and return the path actually used. Raises ReportError before writing anything."""
    target = safe_target(path, (stock_book.path, bom_book.path))
    build_report(result, stock_book, bom_book, generated or datetime.now()).save(target)
    return target
