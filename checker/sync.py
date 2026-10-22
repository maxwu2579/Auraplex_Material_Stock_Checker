"""Excel → SQLite synchronisation. The Excel files stay the source of truth and are only ever read.

Change detection, cheapest first:
1. the file is not there / not accessible             → UNAVAILABLE, nothing parsed;
2. ZIP central-directory signature (CRC and size of every xl/ part, the same signature the reader cache uses)
   equals the published version from the same path    → UNCHANGED, nothing parsed, no snapshot (exception, schema 2:
   a Storage version imported before thresholds were stored is captured once from the caller's parse, see
   capture_thresholds; nothing else of the version changes);
3. otherwise the file is parsed by the unchanged M2.1 reader, hashed, revalidated and published in ONE transaction.

A failure at any point leaves the published version, its rows and its timestamps exactly as they were.

Source-version consistency. A Google Drive / Excel file cannot be locked, so no sequence of checks can guarantee that
it will not change after the last one. A successful outcome therefore means exactly: this local file version matched
the database at `checked_at`. To make that statement true when it is recorded and when it is shown:
- the file is fingerprinted again inside the write transaction, immediately before COMMIT, for UNCHANGED as well as
  IMPORTED, and nothing is committed if it differs;
- it is fingerprinted again after COMMIT; a change there keeps the committed (correct, historical) version but records
  a SourceChanged failure, so the role is not shown as checked;
- sync_all checks every verified file once more after all roles are done, right before the results are displayed;
- a SourceChanged attempt is retried at most max_attempts times in total, never in an open loop.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Callable

from .core import DataReadError, Material, WorkbookData, material_key, number, numeric_code_text
from .inventory_db import DatabaseError, connect, encode, initialise, schema_version, stamp, utc_now
from .reader import ReadOnlyCache, fingerprint, owner_lock_files

PARSER_VERSION = "m2.1"  # rows are produced by checker.reader exactly as the BOM Checker reads them

# Outcomes of one check (sync_runs.outcome)
IMPORTED, UNCHANGED, UNAVAILABLE, FAILED = "IMPORTED", "UNCHANGED", "UNAVAILABLE", "FAILED"
# States shown to the user. LOCAL_VERIFIED means the database matched the Excel file on this computer at the Last
# Verified time; it never means the Google Drive cloud copy was checked, so it is always shown with CLOUD_NOT_VERIFIED.
LOCAL_VERIFIED, CLOUD_NOT_VERIFIED = "Local File Checked", "Cloud Not Verified"
CHECKING, SYNCING = "Checking", "Syncing"
SYNC_FAILED, USING_PREVIOUS, SOURCE_UNAVAILABLE, NOT_SYNCED = ("Sync Failed", "Using Previous Data",
                                                               "Source File Unavailable", "Not Synced")
SOURCE_CHANGED = "Source Changed — Refresh Needed"          # changed during / right after synchronisation
STATUS_UNKNOWN = "Status Unknown — Database Read Failed"     # the sync status itself could not be read
DATABASE_UNAVAILABLE = "Database Unavailable"                # the database could not be opened at start
MAX_ATTEMPTS = 3  # per role and request, when the source keeps changing


class SourceChanged(DataReadError):
    """The source file changed while it was being synchronised, or right after; it is not reported as checked."""


@dataclass(frozen=True)
class SyncResult:
    role: str
    path: str
    trigger: str
    outcome: str
    checked_at: datetime
    version_id: int | None = None   # the version imported or verified; None when the check failed
    snapshot_id: int | None = None  # new inventory snapshot (Storage imports only)
    error: str | None = None
    recorded: bool = True           # False when even the failure could not be written to the database
    changed: bool = False           # the failure is SourceChanged: retry / Refresh, not a broken file
    observed: tuple | None = None   # the exact fingerprint verified (successful outcomes only)
    attempts: int = 1

    @property
    def ok(self) -> bool:
        return self.outcome in (IMPORTED, UNCHANGED)


def content_signature(print_: tuple) -> str:
    """Identity of the workbook content, independent of path, times and file system identifiers."""
    return hashlib.sha256(json.dumps(print_[6], ensure_ascii=False).encode("utf-8")).hexdigest()


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def same_path(a: str | None, b: str | None) -> bool:
    return bool(a and b) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def stock_quantity(m: Material) -> tuple[str, Decimal | None]:
    """M2 rule: only a native, finite, non-negative number is stock. Nothing else is converted or trusted."""
    live = number(m.quantity) if m.quantity_type not in ("f", "e") else None
    if live is not None and live >= 0:
        return "VALID", live
    return ("BLANK" if _blank(m.quantity) else "INVALID"), None


def bom_quantity(m: Material) -> tuple[str, Decimal | None]:
    """M2 rule: BOM QTY must be a native number greater than zero."""
    qty = number(m.quantity) if m.quantity_type not in ("f", "e") else None
    if qty is not None and qty > 0:
        return "VALID", qty
    return ("BLANK" if _blank(m.quantity) else "INVALID"), None


def _identity(m: Material) -> tuple[str | None, str | None]:
    """(matching key, numeric-cell digits). A numeric cell is never a key, exactly as in check_materials."""
    key = material_key(m) or None
    digits = numeric_code_text(m.code) if m.code_type not in ("f", "e") else ""
    return key, (digits or None) if key is None else None


def _raw(value) -> str:
    return json.dumps(list(encode(value)), ensure_ascii=False)


class InventorySync:
    def __init__(self, db_path: str | Path, *, settle_seconds: float = 2.0, clock: Callable[[], datetime] = utc_now,
                 app_version: str = "", max_attempts: int = MAX_ATTEMPTS):
        self.db_path = Path(db_path)
        self.settle_seconds = settle_seconds
        self.clock = clock
        self.max_attempts = max(1, max_attempts)
        initialise(self.db_path, app_version)  # raises DatabaseError; the app then runs without the database

    def connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

    # ------------------------------------------------------------------ public API
    def sync_role(self, role: str, path: str, trigger: str, parse: Callable | None = None,
                  progress: Callable[[str, str], None] | None = None) -> SyncResult:
        """Check one source file and publish it if it changed. Never raises for source or database problems.

        A source that changes during or right after an attempt is retried, at most max_attempts attempts in total;
        every attempt is recorded in sync_runs."""
        if role not in ("stock", "bom"):
            raise ValueError("Unknown workbook role")
        notify = progress or (lambda _role, _state: None)
        for attempt in range(1, self.max_attempts + 1):
            result = self._attempt(role, path, trigger, parse, notify)
            if not result.changed:
                break
        return replace(result, attempts=attempt)

    def _attempt(self, role, path, trigger, parse, notify) -> SyncResult:
        started = self.clock()
        notify(role, CHECKING)
        try:
            if not Path(path).is_file():
                raise FileNotFoundError(f"源文件不存在或当前无法访问：{path}")
        except OSError as exc:  # also a disconnected Google Drive, a missing drive letter, a permission error
            return self._record_failure(role, path, trigger, started, UNAVAILABLE, exc)
        try:
            before = fingerprint(path)
            signature = content_signature(before)
            with self._connection() as conn:
                current = self._current(conn, role)
            if current is not None and same_path(current["source_path"], before[0]) \
                    and current["content_signature"] == signature:
                self._checkpoint("compared", role)
                result = self._record_unchanged(role, path, trigger, started, before, current["id"])
                if role == "stock":  # schema 2: a version imported before thresholds were stored gets them once
                    self.capture_thresholds(path, before, current["id"], parse)
            else:
                notify(role, SYNCING)
                self._wait_until_settled(before)
                book = (parse or (lambda p, r: ReadOnlyCache().read(p, r)))(path, role)
                # The parsed snapshot must be the file as it is now, byte for byte, before anything is published.
                if fingerprint(book.path) != book.fingerprint:
                    raise SourceChanged("同步期间源文件发生变化（正在保存或同步）。未发布本次读取，请稍后重试。")
                digest = file_sha256(book.path)
                result = self._publish(role, path, trigger, started, book, digest)
            self._confirm(result.observed)  # after COMMIT: still the version just recorded?
            return result
        except Exception as exc:  # parse, validation, revalidation and database failures alike
            return self._record_failure(role, path, trigger, started, FAILED, exc)

    def sync_all(self, paths: dict[str, str], trigger: str, parse: Callable | None = None,
                 progress: Callable | None = None) -> dict[str, SyncResult]:
        """Each role on its own: one file failing never discards or blocks the other.

        Then, immediately before the results are returned for display, every verified file is checked once more:
        a file that changed meanwhile (e.g. while the other file was being parsed) is recorded as SourceChanged
        (Refresh needed) instead of being reported as checked. This final pass does not retry, so it always ends."""
        results = {role: self.sync_role(role, path, trigger, parse, progress) for role, path in paths.items() if path}
        for role, result in results.items():
            if result.ok:
                try:
                    self._confirm(result.observed)
                except SourceChanged as exc:
                    results[role] = replace(self._record_failure(role, result.path, trigger, self.clock(), FAILED, exc),
                                            attempts=result.attempts)
        return results

    def freshness(self):
        from .queries import freshness
        with self._connection() as conn:
            return freshness(conn)

    # ------------------------------------------------------------------ helpers
    def _checkpoint(self, stage: str, role: str) -> None:
        """No-op. Named boundaries of the consistency protocol, where tests inject a concurrent source change:
        'compared' (signature matched, nothing recorded yet) and 'verified' (final in-transaction fingerprint
        matched, COMMIT not yet executed)."""

    @staticmethod
    def _confirm(observed: tuple) -> None:
        """The file must still be exactly the version just verified; otherwise that success is not reported."""
        try:
            now = fingerprint(observed[0])
        except DataReadError as exc:
            raise SourceChanged(f"同步后源文件无法再次读取，不能确认数据库与本机文件一致：{exc}") from exc
        if now != observed:
            raise SourceChanged("同步后源文件再次变化（Excel 保存或 Google Drive 同步中）。已写入的版本仅作为历史保留，"
                                "不能确认它是当前本机文件；请稍后点击 Refresh Excel。")

    def _connection(self):
        class Managed:
            def __enter__(inner):
                inner.conn = self.connect()
                return inner.conn

            def __exit__(inner, *exc):
                if inner.conn.in_transaction:
                    inner.conn.execute("ROLLBACK")
                inner.conn.close()
        return Managed()

    @staticmethod
    def _current(conn, role):
        return conn.execute("SELECT v.* FROM current_sources c JOIN source_versions v ON v.id = c.source_version_id "
                            "WHERE c.role = ?", (role,)).fetchone()

    def _wait_until_settled(self, before: tuple) -> None:
        """A file modified moments ago may still be being written by Excel or Google Drive: wait, then re-check."""
        if not self.settle_seconds:
            return
        age = time.time() - before[2] / 1e9
        if age < self.settle_seconds:
            time.sleep(min(self.settle_seconds, self.settle_seconds - age))
            if fingerprint(before[0]) != before:
                raise SourceChanged("源文件正在被更新（Excel 保存或 Google Drive 同步中）。未读取，请稍后点击 Refresh Excel。")

    def _run_row(self, role, path, trigger, started, outcome, version_id=None, observed=None, locks=(), exc=None):
        return (role, trigger, path, stamp(started), stamp(self.clock()), outcome, version_id,
                observed[1] if observed else None, observed[2] if observed else None,
                json.dumps(list(locks), ensure_ascii=False) if observed else None,
                type(exc).__name__ if exc else None, str(exc) if exc else None)

    _INSERT_RUN = ("INSERT INTO sync_runs (role, trigger, source_path, started_at, finished_at, outcome, source_version_id,"
                   " observed_size, observed_mtime_ns, owner_lock_files, error_type, error_message)"
                   " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")

    def _record_unchanged(self, role, path, trigger, started, observed, version_id):
        """Record that the file `observed` matches the published version. Committed only if, inside the write
        transaction, that version is still the published one and the file is still exactly `observed`."""
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            current = self._current(conn, role)
            if current is None or current["id"] != version_id:
                raise SourceChanged("同步期间另一程序实例发布了新的数据库版本。未记录本次检查，请重试。")
            if fingerprint(observed[0]) != observed:
                raise SourceChanged("检查期间源文件发生变化（正在保存或同步）。未记录为未变化，请稍后重试。")
            conn.execute(self._INSERT_RUN, self._run_row(role, path, trigger, started, UNCHANGED, version_id, observed,
                                                         owner_lock_files(observed[0])))
            self._checkpoint("verified", role)
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        return SyncResult(role, path, trigger, UNCHANGED, started, version_id, observed=observed)

    def _record_failure(self, role, path, trigger, started, outcome, exc):
        message = str(exc) or type(exc).__name__
        try:
            with self._connection() as conn:
                conn.execute(self._INSERT_RUN, self._run_row(role, path, trigger, started, outcome, exc=exc))
            recorded = True
        except (sqlite3.Error, OSError, DatabaseError):
            recorded = False  # the database itself is the problem; the UI still shows the failure
        return SyncResult(role, path, trigger, outcome, started, error=message, recorded=recorded,
                          changed=isinstance(exc, SourceChanged))

    def _publish(self, role, path, trigger, started, book: WorkbookData, digest: str) -> SyncResult:
        now = stamp(self.clock())
        print_ = book.fingerprint
        signature = content_signature(print_)
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            current = self._current(conn, role)
            if current is not None and same_path(current["source_path"], print_[0]) \
                    and current["content_signature"] == signature:
                # Another instance of the program published this exact version meanwhile.
                conn.execute("ROLLBACK")
                return self._record_unchanged(role, path, trigger, started, print_, current["id"])
            sheets = book.stock_sheets if role == "stock" else book.products
            version_id = conn.execute(
                "INSERT INTO source_versions (role, source_path, file_name, size_bytes, mtime_ns, source_modified_at,"
                " content_signature, file_sha256, imported_at, parser_version, notes, sheet_count, record_count)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (role, print_[0], Path(print_[0]).name, print_[1], print_[2],
                 stamp(datetime.fromtimestamp(print_[2] / 1e9, timezone.utc)), signature, digest, now, PARSER_VERSION,
                 json.dumps(list(book.notes), ensure_ascii=False), len(sheets),
                 sum(len(s.materials) for s in sheets))).lastrowid
            if role == "stock":
                keys = self._write_stock(conn, version_id, book, thresholds=schema_version(conn) >= 2)
                snapshot_id = self._write_snapshot(conn, version_id, current, now)
            else:
                keys = self._write_bom(conn, version_id, book)
                snapshot_id = None
            self._register_materials(conn, role, version_id, keys, now)
            if current is not None:
                conn.execute("UPDATE source_versions SET superseded_at = ? WHERE id = ?", (now, current["id"]))
            conn.execute("INSERT INTO current_sources (role, source_version_id, published_at) VALUES (?, ?, ?)"
                         " ON CONFLICT (role) DO UPDATE SET source_version_id = excluded.source_version_id,"
                         " published_at = excluded.published_at", (role, version_id, now))
            # Last revalidation, inside the transaction: publish only if the file is still exactly what was read.
            if fingerprint(print_[0]) != print_:
                raise SourceChanged("同步完成前源文件再次变化。未发布本次读取，保留上一次成功同步的数据。")
            conn.execute(self._INSERT_RUN, self._run_row(role, path, trigger, started, IMPORTED, version_id, print_,
                                                         owner_lock_files(print_[0])))
            self._checkpoint("verified", role)
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        return SyncResult(role, path, trigger, IMPORTED, started, version_id, snapshot_id, observed=print_)

    # ------------------------------------------------------------------ writers (inside the publish transaction)
    def _write_stock(self, conn, version_id, book, thresholds=False) -> set[str]:
        """thresholds: schema 2 also stores each Sheet's MIN QTY / MIIN QTY column and every row's raw threshold."""
        keys, issues = set(), []
        for index, sheet in enumerate(book.stock_sheets):
            sheet_id = conn.execute("INSERT INTO stock_sheets (source_version_id, sheet_index, sheet_name, header_row)"
                                    " VALUES (?, ?, ?, ?)", (version_id, index, sheet.name, sheet.header_row)).lastrowid
            if thresholds:
                conn.execute("UPDATE stock_sheets SET threshold_state = ?, threshold_column = ?, threshold_header = ?,"
                             " threshold_candidates = ? WHERE id = ?", (*_sheet_threshold(sheet), sheet_id))
            counts = defaultdict(int)
            for m in sheet.materials:
                key = _identity(m)[0]
                if key:
                    counts[key] += 1
            rows = []
            for ordinal, m in enumerate(sheet.materials):
                key, digits = _identity(m)
                status, value = stock_quantity(m)
                keys.update([key] if key else [])
                rows.append((version_id, sheet_id, ordinal, m.source.row, *encode(m.code), m.code_type, key, digits,
                             *encode(m.description), *encode(m.quantity), m.quantity_type, status,
                             None if value is None else str(value), *encode(m.rack), *encode(m.level), m.section))
                issues.extend(self._identity_issues(version_id, "stock", sheet.name, m, key, digits))
                if status != "VALID":
                    issues.append((version_id, "stock", sheet.name, m.source.row, f"{status}_STOCK", key, _raw(m.quantity),
                                   "LIVE STOCK 为空白。" if status == "BLANK" else
                                   "LIVE STOCK 不是有效的非负数值（文本、公式/错误、布尔或负数）；未转换、未作为可信库存。"))
                if key and counts[key] > 1:
                    issues.append((version_id, "stock", sheet.name, m.source.row, "DUPLICATE_STOCK", key, _raw(m.code),
                                   f"同一 Sheet 内有 {counts[key]} 条相同编号的记录；保留为独立记录，不相加、不合并。"))
            if thresholds:
                rows = [(*row, *_threshold(m)) for row, m in zip(rows, sheet.materials)]
                conn.executemany(
                    "INSERT INTO stock_records (source_version_id, stock_sheet_id, ordinal, row_no, code_kind, code_text,"
                    " code_cell_type, material_key, numeric_code, description_kind, description_text, qty_kind, qty_text,"
                    " qty_cell_type, qty_status, qty_value, rack_kind, rack_text, level_kind, level_text, section,"
                    " threshold_kind, threshold_text, threshold_cell_type)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
                continue
            conn.executemany(
                "INSERT INTO stock_records (source_version_id, stock_sheet_id, ordinal, row_no, code_kind, code_text,"
                " code_cell_type, material_key, numeric_code, description_kind, description_text, qty_kind, qty_text,"
                " qty_cell_type, qty_status, qty_value, rack_kind, rack_text, level_kind, level_text, section)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        self._write_issues(conn, issues)
        return keys

    def capture_thresholds(self, path, observed, version_id, parse=None) -> bool:
        """Schema 2: fill the thresholds of a Storage version imported before they were stored (schema 1), from a
        parse of exactly that file version. Only empty (not captured) threshold fields are written, and only when the
        parse has the version's content signature and every Sheet / row / Material ID matches the stored rows.
        Returns True when thresholds were captured. Never raises: thresholds then stay 'not captured'."""
        try:
            with self._connection() as conn:
                if schema_version(conn) < 2 or not conn.execute(
                        "SELECT 1 FROM stock_sheets WHERE source_version_id = ? AND threshold_state IS NULL",
                        (version_id,)).fetchone():
                    return False
            book = (parse or (lambda p, r: ReadOnlyCache().read(p, r)))(path, "stock")
            if book.fingerprint != observed:
                return False
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                current = self._current(conn, "stock")
                if current is None or current["id"] != version_id \
                        or current["content_signature"] != content_signature(book.fingerprint):
                    raise SourceChanged("threshold capture: version changed")
                sheets = conn.execute("SELECT * FROM stock_sheets WHERE source_version_id = ? ORDER BY sheet_index",
                                      (version_id,)).fetchall()
                if [(s["sheet_name"], s["header_row"]) for s in sheets] != \
                        [(s.name, s.header_row) for s in book.stock_sheets]:
                    raise SourceChanged("threshold capture: Sheets differ")
                for stored, sheet in zip(sheets, book.stock_sheets):
                    if stored["threshold_state"] is not None:
                        continue
                    records = conn.execute("SELECT id, row_no, material_key, threshold_kind FROM stock_records"
                                           " WHERE stock_sheet_id = ? ORDER BY ordinal", (stored["id"],)).fetchall()
                    if [(r["row_no"], r["material_key"]) for r in records] != \
                            [(m.source.row, _identity(m)[0]) for m in sheet.materials]:
                        raise SourceChanged("threshold capture: rows differ")
                    conn.executemany("UPDATE stock_records SET threshold_kind = ?, threshold_text = ?,"
                                     " threshold_cell_type = ? WHERE id = ? AND threshold_kind IS NULL"
                                     " AND threshold_cell_type IS NULL",
                                     [(*_threshold(m), r["id"]) for r, m in zip(records, sheet.materials)])
                    conn.execute("UPDATE stock_sheets SET threshold_state = ?, threshold_column = ?, threshold_header = ?,"
                                 " threshold_candidates = ? WHERE id = ?", (*_sheet_threshold(sheet), stored["id"]))
                if fingerprint(path) != observed:
                    raise SourceChanged("threshold capture: file changed")
                conn.execute("COMMIT")
                return True
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
        except Exception:
            return False

    def _write_bom(self, conn, version_id, book) -> set[str]:
        keys, issues = set(), []
        for index, product in enumerate(book.products):
            product_id = conn.execute(
                "INSERT INTO bom_products (source_version_id, sheet_index, sheet_name, product_id, header_row)"
                " VALUES (?, ?, ?, ?, ?)",
                (version_id, index, product.sheet_name, product.display_name, product.header_row)).lastrowid
            counts = defaultdict(int)
            for m in product.materials:
                key = _identity(m)[0]
                if key:
                    counts[key] += 1
            rows = []
            for ordinal, m in enumerate(product.materials):
                key, digits = _identity(m)
                status, value = bom_quantity(m)
                keys.update([key] if key else [])
                rows.append((version_id, product_id, ordinal, m.source.row, *encode(m.code), m.code_type, key, digits,
                             *encode(m.description), *encode(m.quantity), m.quantity_type, status,
                             None if value is None else str(value), *encode(m.rack), *encode(m.level), m.section))
                issues.extend(self._identity_issues(version_id, "bom", product.sheet_name, m, key, digits))
                if status != "VALID":
                    issues.append((version_id, "bom", product.sheet_name, m.source.row, "INVALID_BOM_QTY", key,
                                   _raw(m.quantity), "BOM QTY 为空、非数值、公式/错误或不大于零。"))
                if key and counts[key] > 1:
                    issues.append((version_id, "bom", product.sheet_name, m.source.row, "DUPLICATE_BOM", key, _raw(m.code),
                                   f"同一产品 Sheet 内有 {counts[key]} 行相同编号；按装配段分别保留，不合并。"))
            conn.executemany(
                "INSERT INTO bom_lines (source_version_id, bom_product_id, ordinal, row_no, code_kind, code_text,"
                " code_cell_type, material_key, numeric_code, description_kind, description_text, qty_kind, qty_text,"
                " qty_cell_type, qty_status, qty_value, column_j_kind, column_j_text, column_k_kind, column_k_text, section)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        self._write_issues(conn, issues)
        return keys

    @staticmethod
    def _identity_issues(version_id, role, sheet, m, key, digits):
        if key:
            return []
        if digits:
            return [(version_id, role, sheet, m.source.row, "NUMERIC_MATERIAL_ID", None, _raw(m.code),
                     f"编号 {digits} 保存在数值单元格中；不作为文本编号匹配，也不与文本编号合并。")]
        return [(version_id, role, sheet, m.source.row, "INVALID_MATERIAL_ID", None, _raw(m.code),
                 "材料编号为空、公式、Excel 错误或非文本；不能用于匹配。")]

    @staticmethod
    def _write_issues(conn, issues):
        conn.executemany("INSERT INTO data_quality_issues (source_version_id, role, sheet_name, row_no, issue_type,"
                         " material_key, raw_value, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", issues)

    @staticmethod
    def _register_materials(conn, role, version_id, keys, now):
        column = "stock_last_version_id" if role == "stock" else "bom_last_version_id"
        conn.executemany(f"INSERT INTO materials (material_key, first_seen_at, last_seen_at, {column}) VALUES (?, ?, ?, ?)"
                         f" ON CONFLICT (material_key) DO UPDATE SET last_seen_at = excluded.last_seen_at,"
                         f" {column} = excluded.{column}", ((key, now, now, version_id) for key in sorted(keys)))

    @staticmethod
    def _stock_groups(conn, version_id):
        """(sheet name, material key) → list of (status, exact value, raw kind, raw text), in sheet order."""
        groups = defaultdict(list)
        for row in conn.execute(
                "SELECT s.sheet_name, r.material_key, r.qty_status, r.qty_value, r.qty_kind, r.qty_text"
                " FROM stock_records r JOIN stock_sheets s ON s.id = r.stock_sheet_id"
                " WHERE r.source_version_id = ? AND r.material_key IS NOT NULL ORDER BY s.sheet_index, r.ordinal",
                (version_id,)):
            groups[(row[0], row[1])].append((row[2], row[3], row[4], row[5]))
        return groups

    def _write_snapshot(self, conn, version_id, previous, now) -> int:
        new = self._stock_groups(conn, version_id)
        totals = conn.execute(
            "SELECT count(*), sum(qty_status = 'VALID'), sum(qty_status = 'BLANK'), sum(qty_status = 'INVALID'),"
            " sum(material_key IS NULL) FROM stock_records WHERE source_version_id = ?", (version_id,)).fetchone()
        changes = []
        baseline = previous is None or previous["role"] != "stock"
        if not baseline:
            old = self._stock_groups(conn, previous["id"])
            for sheet_key in sorted(set(old) | set(new)):
                before, after = old.get(sheet_key), new.get(sheet_key)
                change = _compare(before, after)
                if change:
                    changes.append((sheet_key, change, before, after))
        kinds = defaultdict(int)
        for _key, change, _before, _after in changes:
            kinds[change[0]] += 1
        version = conn.execute("SELECT source_modified_at FROM source_versions WHERE id = ?", (version_id,)).fetchone()
        snapshot_id = conn.execute(
            "INSERT INTO inventory_snapshots (source_version_id, previous_version_id, same_source_path, observed_at,"
            " source_modified_at, record_count, valid_count, blank_count, invalid_count, unkeyed_count,"
            " duplicate_key_count, quantity_changed_count, added_count, removed_count, validity_changed_count,"
            " duplicate_changed_count, has_differences) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (version_id, None if baseline else previous["id"],
             None if baseline else int(same_path(previous["source_path"], conn.execute(
                 "SELECT source_path FROM source_versions WHERE id = ?", (version_id,)).fetchone()[0])),
             now, version[0], totals[0], totals[1] or 0, totals[2] or 0, totals[3] or 0, totals[4] or 0,
             sum(len(rows) > 1 for rows in new.values()), kinds["QUANTITY_CHANGED"], kinds["ADDED"], kinds["REMOVED"],
             kinds["VALIDITY_CHANGED"], kinds["DUPLICATE_CHANGED"], None if baseline else int(bool(changes)))).lastrowid
        conn.executemany(
            "INSERT INTO inventory_changes (snapshot_id, sheet_name, material_key, change_type, previous_status,"
            " previous_value, previous_raw, new_status, new_value, new_raw, observed_net_change)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ((snapshot_id, sheet, key, change[0], *_side(before), *_side(after), change[1])
             for (sheet, key), change, before, after in changes))
        return snapshot_id


def _threshold(m: Material) -> tuple:
    """(kind, text, cell type) of a row's raw threshold; cell type None when the Sheet has no single threshold column."""
    return (*encode(m.threshold), m.threshold_type or None)


def _sheet_threshold(sheet) -> tuple:
    candidates = json.dumps([list(c) for c in sheet.threshold_candidates], ensure_ascii=False) \
        if sheet.threshold_candidates else None
    return sheet.threshold_state, sheet.threshold_column, sheet.threshold_header, candidates


def _side(rows):
    """(status, exact value, raw values) of one side of a comparison."""
    if not rows:
        return None, None, None
    raw = json.dumps([[kind, text] for _status, _value, kind, text in rows], ensure_ascii=False)
    if len(rows) > 1:
        return "DUPLICATE", None, raw
    return rows[0][0], rows[0][1], raw


def _compare(before, after) -> tuple[str, str | None] | None:
    """(change type, observed net change) or None. A net change exists only between two single, valid values."""
    if before is None:
        return "ADDED", None
    if after is None:
        return "REMOVED", None
    if len(before) > 1 or len(after) > 1:
        same = sorted((k or "", t or "") for _s, _v, k, t in before) == sorted((k or "", t or "") for _s, _v, k, t in after)
        return None if same else ("DUPLICATE_CHANGED", None)
    (old_status, old_value, old_kind, old_text), (new_status, new_value, new_kind, new_text) = before[0], after[0]
    if old_status == new_status == "VALID":
        delta = Decimal(new_value) - Decimal(old_value)
        return ("QUANTITY_CHANGED", str(delta)) if delta else None
    if old_status != new_status or (old_kind, old_text) != (new_kind, new_text):
        return "VALIDITY_CHANGED", None
    return None
