from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
import re
import unicodedata


class DataReadError(Exception):
    """A file or worksheet cannot safely be used for this check."""


def normalize_code(value: Any) -> str:
    # Internal spaces, hyphens, revisions and suffixes remain significant.
    if not isinstance(value, str):
        return ""
    return unicodedata.normalize("NFKC", value).strip().upper()


def numeric_code_text(value: Any) -> str:
    """Digits of a code kept in a numeric cell, for flagging only; never used as a match key."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return ""
        if value.is_integer():
            value = int(value)
    return str(value)


def number(value: Any) -> Decimal | None:
    """Only native, finite spreadsheet numbers are usable; text is not evaluated."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def production_quantity(text: str) -> int:
    text = text.strip()
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise ValueError("Production Quantity 必须是正整数。")
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError("Production Quantity 位数过长，超出 Python 的整数输入限制。") from exc


def display(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, Decimal):
        return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else str(value)
    return str(value)


@dataclass(frozen=True)
class Source:
    path: str
    sheet: str
    row: int


@dataclass(frozen=True)
class Material:
    source: Source
    code: Any
    description: Any
    quantity: Any
    quantity_type: str = "n"
    code_type: str = "s"
    rack: Any = None
    level: Any = None
    section: str = ""


def material_key(material: Material) -> str:
    return normalize_code(material.code) if material.code_type not in ("f", "e") else ""


@dataclass(frozen=True)
class Product:
    file_path: str
    sheet_name: str  # Never trim this value when locating the worksheet.
    display_name: str  # Product ID shown to the user: the trimmed Sheet name, made unique within the workbook.
    header_row: int
    materials: tuple[Material, ...]


@dataclass(frozen=True)
class StockSheet:
    name: str
    header_row: int
    materials: tuple[Material, ...]


@dataclass(frozen=True)
class WorkbookData:
    path: str
    fingerprint: tuple
    products: tuple[Product, ...] = ()
    stock_sheets: tuple[StockSheet, ...] = ()
    notes: tuple[str, ...] = ()
    loaded_at: float = 0.0  # time.time() of the parse that produced this snapshot


def search_products(products: tuple[Product, ...], text: str) -> tuple[Product, ...]:
    query = unicodedata.normalize("NFKC", text).strip().casefold()
    return tuple(p for p in products if query in unicodedata.normalize("NFKC", p.display_name).casefold())


def select_product(products: tuple[Product, ...], text: str) -> Product | None:
    """The one product whose Product ID was selected or typed in full (case-insensitive); never a partial match."""
    exact = [p for p in products if p.display_name == text]
    if len(exact) == 1:
        return exact[0]
    wanted = normalize_code(text)
    names = [p for p in products if wanted and wanted in (normalize_code(p.sheet_name), normalize_code(p.display_name))]
    return names[0] if len(names) == 1 else None


# Primary display categories, in priority order (M2).
SHORTAGE, EXCEPTION, ENOUGH = "SHORTAGE", "EXCEPTION", "ENOUGH"
CATEGORIES = (SHORTAGE, EXCEPTION, ENOUGH)
# Exception types, in the order used to pick the first one shown for a row.
DATA_STATUSES = ("INVALID_MATERIAL_ID", "CODE_TYPE_MISMATCH", "INVALID_BOM_QTY", "DUPLICATE_BOM",
                 "DUPLICATE_STOCK", "STOCK_NOT_FOUND", "BLANK_STOCK", "INVALID_STOCK")


@dataclass(frozen=True)
class Result:
    bom: Material
    stock: tuple[Material, ...]
    match_status: str
    required: Decimal | None
    delta: Decimal | None
    shortage: Decimal | None
    issues: tuple[str, ...]
    bom_status: str = "UNVERIFIED_BOM"
    estimate_status: str = "ESTIMATED / UNVERIFIED"
    category: str = EXCEPTION
    exceptions: tuple[str, ...] = ()       # every exception type that applies, ordered as DATA_STATUSES
    stock_used: Decimal | None = None      # None when no single stock value is authoritative
    stock_assumed: bool = False            # True when stock_used is the approved "assume 0" value, not a stock record

    @property
    def data_status(self) -> str:
        if not self.exceptions:
            return "NORMAL"
        return " / ".join(self.exceptions) + (" / ASSUMED 0" if self.stock_assumed else "")

    @property
    def original_stock(self) -> str:
        """Raw LIVE STOCK value(s) exactly as read; empty when there is no stock record."""
        return " | ".join("(blank)" if s.quantity is None else str(s.quantity) for s in self.stock)


@dataclass(frozen=True)
class CheckResult:
    product: Product
    production_count: int
    rows: tuple[Result, ...]  # BOM source order
    counts: dict[str, int]
    verification_required: int
    overall_status: str = "Verification Required"

    def category_count(self, category: str) -> int:
        return sum(r.category == category for r in self.rows)

    @property
    def calculated_shortage_rows(self) -> int:
        """Rows with a calculated shortage above zero, including exception rows where stock was assumed 0."""
        return sum(bool(r.shortage) for r in self.rows)

    @property
    def sorted_order(self) -> tuple[int, ...]:
        """Indexes into rows: SHORTAGE, then EXCEPTION, then ENOUGH; Material ID ascending inside each."""
        def key(i):
            r = self.rows[i]
            code = normalize_code(r.bom.code) or ("" if r.bom.code is None else str(r.bom.code).strip().upper())
            return CATEGORIES.index(r.category), code, r.bom.source.row
        return tuple(sorted(range(len(self.rows)), key=key))

    @property
    def sorted_rows(self) -> tuple[Result, ...]:
        return tuple(self.rows[i] for i in self.sorted_order)


# Applies to every row; shown once in the summary/details/report instead of in each row's reason.
ROW_CAVEAT = ("QTY 每件/每套基数、单位、装配配置及库存可用口径未确认；差额仅为假设单位一致、"
              "QTY为单生产单位的行级试算，非可用性结论。")
STATUSES = ("MATCHED", "NOT_FOUND", "INVALID_STOCK", "DUPLICATE_STOCK", "CODE_TYPE_MISMATCH", "UNVERIFIED_BOM")


def check_materials(product: Product, stock_sheet: StockSheet, count: int) -> CheckResult:
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("Production Quantity 必须是正整数。")
    index: dict[str, list[Material]] = defaultdict(list)
    # Stock codes kept in numeric cells are evidence for a warning only; they never join a calculation.
    numeric_index: dict[str, list[Material]] = defaultdict(list)
    for record in stock_sheet.materials:
        key = material_key(record)
        if key:
            index[key].append(record)
        elif record.code_type not in ("f", "e") and numeric_code_text(record.code):
            numeric_index[numeric_code_text(record.code)].append(record)
    bom_counts = Counter(material_key(m) for m in product.materials if material_key(m))
    results = []
    distinct_statuses = {}
    for m in product.materials:
        key = material_key(m)
        issues, flags = [], set()
        bom_digits = numeric_code_text(m.code) if m.code_type not in ("f", "e") else ""
        if isinstance(m.description, str) and m.description.startswith(("#REF!", "#VALUE!", "#N/A")):
            issues.append("BOM 描述含 Excel 错误；需人工核对材料身份。")
        qty = number(m.quantity) if m.quantity_type not in ("f", "e") else None
        required = qty * count if qty is not None and qty > 0 else None
        if required is None:
            flags.add("INVALID_BOM_QTY")
            issues.append("BOM QTY 为空、非数值、公式/错误或不大于零；不试算需求。")
        if key and bom_counts[key] > 1:
            flags.add("DUPLICATE_BOM")
            issues.append("同一编号在所选 Sheet 重复；保留装配段，不合并配置，不计算库存差额。")
        if key.startswith("ASSY"):
            issues.append("装配件不自动展开下层 BOM。")
        if "/" in m.section or "MIR" in m.section.upper():
            issues.append("装配段含替代/镜像提示，仅保留当前行，配置需确认。")
        records = tuple(index.get(key, ())) if key else ()
        # Same digits, but at least one side is a numeric cell: identity is unconfirmed either way.
        lookalikes = tuple(numeric_index.get(key, ())) if key else \
            tuple(index.get(bom_digits, ())) + tuple(numeric_index.get(bom_digits, ())) if bom_digits else ()
        # stock_used stays None unless exactly one value is authoritative or the approved "assume 0" rule applies.
        stock_used, assumed = None, False
        if lookalikes and not records:
            status = "CODE_TYPE_MISMATCH"
            records = lookalikes
            flags.add("CODE_TYPE_MISMATCH")
            issues.append(f"库存第 {'、'.join(str(s.source.row) for s in lookalikes)} 行有相同数字的编号，但 BOM 或库存一方是数值单元格、"
                          "另一方是文本；不自动视为同一材料，也不判为库存未找到。请核对并统一为文本编号。")
        elif not key:
            status = "UNVERIFIED_BOM"
            flags.add("INVALID_MATERIAL_ID")
            issues.append("BOM 材料编号为空、非文本、公式或 Excel 错误，不能匹配。")
        elif not records:
            status = "NOT_FOUND"
            flags.add("STOCK_NOT_FOUND")
            stock_used, assumed = Decimal(0), True
            issues.append("所选库存 Sheet 未找到精确编号；按 M2 规则以库存 0 试算，并列为异常而非正常缺料。")
        elif len(records) > 1:
            status = "DUPLICATE_STOCK"
            flags.add("DUPLICATE_STOCK")
            issues.append(f"库存有 {len(records)} 条同编号记录；不相加、不取第一条，差额不可用。")
        else:
            s = records[0]
            live = number(s.quantity) if s.quantity_type not in ("f", "e") else None
            if live is None or live < 0:
                status = "INVALID_STOCK"
                blank = s.quantity is None or (isinstance(s.quantity, str) and not s.quantity.strip())
                flags.add("BLANK_STOCK" if blank else "INVALID_STOCK")
                stock_used, assumed = Decimal(0), True
                issues.append("LIVE STOCK 为空白；按 M2 规则以库存 0 试算，并列为异常。" if blank else
                              f"LIVE STOCK 原值 {s.quantity!r} 不是有效的非负数值（文本、公式/错误、布尔或负数）；"
                              "不执行、不换算，按 M2 规则以库存 0 试算，并列为异常。")
            else:
                status = "MATCHED"
                stock_used = live
            if lookalikes:
                issues.append(f"另：库存第 {'、'.join(str(s.source.row) for s in lookalikes)} 行有以数值单元格保存的相同数字编号，未计入。")
        delta = shortage = None
        if required is not None and stock_used is not None and "DUPLICATE_BOM" not in flags:
            # Row arithmetic under the stated assumptions: same unit, QTY is per production unit.
            delta = stock_used - required
            shortage = max(-delta, Decimal(0))
        category = EXCEPTION if flags else SHORTAGE if shortage else ENOUGH
        distinct_statuses[key or f"missing:{m.source.row}"] = status
        results.append(Result(m, records, status, required, delta, shortage, tuple(issues), category=category,
                              exceptions=tuple(x for x in DATA_STATUSES if x in flags),
                              stock_used=stock_used, stock_assumed=assumed))
    counts = {s: sum(x == s for x in distinct_statuses.values()) for s in STATUSES}
    return CheckResult(product, count, tuple(results), counts, len(results))
