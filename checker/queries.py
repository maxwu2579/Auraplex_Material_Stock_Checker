"""Read-only queries over the inventory database, for the UI now and for restricted query tools later (M3.2 / M4).

Every function takes an open sqlite3 connection and only reads. open_readonly() gives a connection that SQLite itself
refuses to write through. "Observed change" always means a difference between two synchronised Storage versions;
it is never confirmed material consumption (the Storage workbook is updated irregularly, by hand).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from .core import Material, Product, Source, StockSheet, WorkbookData, normalize_code
from .inventory_db import decode, parse_stamp, stamp, utc_now
from .sync import (CLOUD_NOT_VERIFIED, FAILED, IMPORTED, LOCAL_VERIFIED, NOT_SYNCED, SOURCE_CHANGED,
                   SOURCE_UNAVAILABLE, SYNC_FAILED, UNAVAILABLE, UNCHANGED, USING_PREVIOUS, SourceChanged)

OBSERVED_CHANGE_CAVEAT = ("Observed net change is the difference between two synchronised Storage versions. It is not "
                          "confirmed consumption: the workbook is edited irregularly and may include receipts, "
                          "corrections, recounts and data-entry changes.")


def open_readonly(db_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


# ---------------------------------------------------------------------- freshness
@dataclass(frozen=True)
class RoleFreshness:
    role: str
    state: str                       # LOCAL_VERIFIED / SOURCE_CHANGED / SYNC_FAILED / SOURCE_UNAVAILABLE / NOT_SYNCED
    last_checked: datetime | None    # last check of the source, whatever the outcome
    last_success: datetime | None    # Last Verified: the database last matched one local file version (import or unchanged)
    source_modified: datetime | None # modified time of the file the current data came from
    data_imported: datetime | None   # when the current data version was imported
    data_path: str | None            # the file the current data came from
    last_run_path: str | None
    last_error: str | None
    has_data: bool
    unrecorded: bool = False         # the state comes from a failure this program saw but could not write to SQLite

    @property
    def using_previous(self) -> bool:
        """Previously synchronised data exists but is not currently verified against the local file."""
        return self.state in (SYNC_FAILED, SOURCE_UNAVAILABLE, SOURCE_CHANGED) and self.has_data

    @property
    def label(self) -> str:
        return f"{self.state} · {USING_PREVIOUS}" if self.using_previous else self.state


def freshness(conn) -> dict[str, RoleFreshness]:
    result = {}
    for role in ("stock", "bom"):
        last = conn.execute("SELECT * FROM sync_runs WHERE role = ? ORDER BY id DESC LIMIT 1", (role,)).fetchone()
        success = conn.execute("SELECT finished_at FROM sync_runs WHERE role = ? AND outcome IN (?, ?)"
                               " ORDER BY id DESC LIMIT 1", (role, IMPORTED, UNCHANGED)).fetchone()
        current = conn.execute("SELECT v.* FROM current_sources c JOIN source_versions v ON v.id = c.source_version_id"
                               " WHERE c.role = ?", (role,)).fetchone()
        if last is None:
            state = NOT_SYNCED
        elif last["outcome"] in (IMPORTED, UNCHANGED):
            state = LOCAL_VERIFIED
        elif last["outcome"] == UNAVAILABLE:
            state = SOURCE_UNAVAILABLE
        elif last["outcome"] == FAILED and last["error_type"] == SourceChanged.__name__:
            state = SOURCE_CHANGED
        else:
            state = SYNC_FAILED
        result[role] = RoleFreshness(
            role, state, parse_stamp(last["finished_at"]) if last else None,
            parse_stamp(success["finished_at"]) if success else None,
            parse_stamp(current["source_modified_at"]) if current else None,
            parse_stamp(current["imported_at"]) if current else None,
            current["source_path"] if current else None, last["source_path"] if last else None,
            last["error_message"] if last else None, current is not None)
    return result


def overall_state(roles: dict[str, RoleFreshness], active: dict[str, str] | None = None) -> str:
    """One status for both files. A check in progress wins; then the most serious problem; LOCAL_VERIFIED only if all
    files are."""
    active = {role: state for role, state in (active or {}).items() if state}
    for state in ("Syncing", "Checking"):
        if state in active.values():
            return state
    states = [r for r in roles.values()]
    for problem in (SOURCE_UNAVAILABLE, SYNC_FAILED, SOURCE_CHANGED):  # failed, and no earlier data to fall back on
        if any(r.state == problem and not r.has_data for r in states):
            return problem
    if any(r.state == SOURCE_CHANGED for r in states):
        return SOURCE_CHANGED
    if any(r.using_previous for r in states):
        return USING_PREVIOUS
    if not states or any(r.state == NOT_SYNCED for r in states):
        return NOT_SYNCED
    return LOCAL_VERIFIED


def status_text(state: str) -> str:
    """One-line text for any state (status bar): every state is qualified, because no state checks the cloud copy."""
    return f"{state} — {CLOUD_NOT_VERIFIED}"


def with_known_failures(roles: dict[str, RoleFreshness], failures: dict) -> dict[str, RoleFreshness]:
    """Overlay failures this program observed (role -> failed SyncResult) on the states read from the database.

    A failure that could not be written to SQLite leaves an older IMPORTED/UNCHANGED run as the newest record; read
    alone, it would show the file as checked again. A known failure therefore always wins for its role. The data and
    the Last Verified time stay as stored; the UI labels that time as historical."""
    roles = dict(roles)
    for role, result in failures.items():
        info = roles.get(role) or RoleFreshness(role, NOT_SYNCED, None, None, None, None, None, None, None, False)
        state = (SOURCE_UNAVAILABLE if result.outcome == UNAVAILABLE else
                 SOURCE_CHANGED if result.changed else SYNC_FAILED)
        checked = max(t for t in (info.last_checked, result.checked_at) if t is not None)
        roles[role] = replace(info, state=state, last_checked=checked, last_run_path=result.path,
                              last_error=result.error, unrecorded=not result.recorded)
    return roles


def overall_times(roles: dict[str, RoleFreshness]) -> tuple[datetime | None, datetime | None]:
    """(latest Last Checked, oldest Last Verified): the overall verification time never overstates freshness."""
    checked = [r.last_checked for r in roles.values() if r.last_checked]
    success = [r.last_success for r in roles.values()]
    return (max(checked) if checked else None,
            None if not success or any(s is None for s in success) else min(success))


# ---------------------------------------------------------------------- versions, runs
def current_version(conn, role: str):
    return conn.execute("SELECT v.* FROM current_sources c JOIN source_versions v ON v.id = c.source_version_id"
                        " WHERE c.role = ?", (role,)).fetchone()


def sync_history(conn, role: str | None = None, limit: int = 50) -> list[dict]:
    sql, args = "SELECT * FROM sync_runs", []
    if role:
        sql, args = sql + " WHERE role = ?", [role]
    return [dict(r) for r in conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))]


# ---------------------------------------------------------------------- current data
def _record(row, prefix_pairs) -> dict:
    data = dict(row)
    for name in prefix_pairs:
        data[name] = decode(data.pop(f"{name}_kind"), data.pop(f"{name}_text"))
    return data


def current_stock(conn, material_id: str | None = None, sheet: str | None = None) -> list[dict]:
    """Storage rows of the published version. material_id is matched exactly as the BOM Checker matches it."""
    sql = ("SELECT s.sheet_name, r.* FROM current_sources c JOIN stock_records r ON r.source_version_id = c.source_version_id"
           " JOIN stock_sheets s ON s.id = r.stock_sheet_id WHERE c.role = 'stock'")
    args = []
    if material_id is not None:
        sql += " AND r.material_key = ?"
        args.append(normalize_code(material_id))
    if sheet is not None:
        sql += " AND s.sheet_name = ?"
        args.append(sheet)
    rows = conn.execute(sql + " ORDER BY s.sheet_index, r.ordinal", args)
    return [_record(r, ("code", "description", "qty", "rack", "level")) for r in rows]


def list_products(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT p.product_id, p.sheet_name, p.header_row, count(l.id) AS line_count FROM current_sources c"
        " JOIN bom_products p ON p.source_version_id = c.source_version_id LEFT JOIN bom_lines l ON l.bom_product_id = p.id"
        " WHERE c.role = 'bom' GROUP BY p.id ORDER BY p.sheet_index")]


def bom_lines(conn, product_id: str | None = None, material_id: str | None = None) -> list[dict]:
    sql = ("SELECT p.product_id, p.sheet_name, l.* FROM current_sources c JOIN bom_products p"
           " ON p.source_version_id = c.source_version_id JOIN bom_lines l ON l.bom_product_id = p.id WHERE c.role = 'bom'")
    args = []
    if product_id is not None:
        sql += " AND p.product_id = ?"
        args.append(product_id)
    if material_id is not None:
        sql += " AND l.material_key = ?"
        args.append(normalize_code(material_id))
    rows = conn.execute(sql + " ORDER BY p.sheet_index, l.ordinal", args)
    return [_record(r, ("code", "description", "qty", "column_j", "column_k")) for r in rows]


def data_quality(conn, role: str | None = None, issue_type: str | None = None) -> list[dict]:
    sql = ("SELECT i.* FROM current_sources c JOIN data_quality_issues i ON i.source_version_id = c.source_version_id"
           " WHERE 1 = 1")
    args = []
    if role:
        sql += " AND i.role = ?"
        args.append(role)
    if issue_type:
        sql += " AND i.issue_type = ?"
        args.append(issue_type)
    return [dict(r) for r in conn.execute(sql + " ORDER BY i.role, i.sheet_name, i.row_no, i.id", args)]


def data_quality_summary(conn) -> dict[tuple[str, str], int]:
    return {(r[0], r[1]): r[2] for r in conn.execute(
        "SELECT i.role, i.issue_type, count(*) FROM current_sources c JOIN data_quality_issues i"
        " ON i.source_version_id = c.source_version_id GROUP BY i.role, i.issue_type ORDER BY i.role, i.issue_type")}


# ---------------------------------------------------------------------- history
def snapshots(conn, since: datetime | None = None, until: datetime | None = None) -> list[dict]:
    sql, args = "SELECT * FROM inventory_snapshots WHERE 1 = 1", []
    if since:
        sql += " AND observed_at >= ?"
        args.append(stamp(since))
    if until:
        sql += " AND observed_at <= ?"
        args.append(stamp(until))
    return [dict(r) for r in conn.execute(sql + " ORDER BY id", args)]


def stock_history(conn, material_id: str, sheet: str | None = None, since: datetime | None = None) -> list[dict]:
    """The observed Storage rows for one Material ID in every snapshot (absent snapshots are listed with no rows)."""
    key = normalize_code(material_id)
    history = []
    for snap in snapshots(conn, since):
        sql = ("SELECT s.sheet_name, r.row_no, r.qty_status, r.qty_value, r.qty_kind, r.qty_text FROM stock_records r"
               " JOIN stock_sheets s ON s.id = r.stock_sheet_id WHERE r.source_version_id = ? AND r.material_key = ?")
        args = [snap["source_version_id"], key]
        if sheet is not None:
            sql += " AND s.sheet_name = ?"
            args.append(sheet)
        rows = [dict(sheet=r[0], row=r[1], status=r[2], value=r[3], raw=decode(r[4], r[5]))
                for r in conn.execute(sql + " ORDER BY s.sheet_index, r.ordinal", args)]
        history.append(dict(snapshot_id=snap["id"], observed_at=snap["observed_at"],
                            source_modified_at=snap["source_modified_at"], rows=rows))
    return history


def observed_changes(conn, since: datetime | None = None, until: datetime | None = None,
                     material_id: str | None = None, change_types: tuple[str, ...] | None = None) -> list[dict]:
    sql = ("SELECT c.*, s.observed_at, s.source_modified_at, s.same_source_path FROM inventory_changes c"
           " JOIN inventory_snapshots s ON s.id = c.snapshot_id WHERE 1 = 1")
    args = []
    if since:
        sql += " AND s.observed_at >= ?"
        args.append(stamp(since))
    if until:
        sql += " AND s.observed_at <= ?"
        args.append(stamp(until))
    if material_id is not None:
        sql += " AND c.material_key = ?"
        args.append(normalize_code(material_id))
    if change_types:
        sql += f" AND c.change_type IN ({', '.join('?' * len(change_types))})"
        args.extend(change_types)
    return [dict(r) for r in conn.execute(sql + " ORDER BY s.id, c.sheet_name, c.material_key", args)]


def observed_change_summary(conn, days: int, now: datetime | None = None, material_id: str | None = None) -> dict:
    """Per material, the observed changes over the last `days` days (e.g. 30 / 60 / 90).

    Coverage is reported because history starts with the first synchronisation and the source is edited irregularly:
    `covers_full_window` is False when the first snapshot is inside the window."""
    end = now or utc_now()
    start = end - timedelta(days=days)
    in_window = snapshots(conn, start, end)
    first = conn.execute("SELECT min(observed_at) FROM inventory_snapshots").fetchone()[0]
    retained = conn.execute("SELECT value FROM schema_info WHERE key='history_retained_from'").fetchone()
    retained_from = retained[0] if retained else None
    materials = {}
    for change in observed_changes(conn, start, end, material_id):
        entry = materials.setdefault((change["sheet_name"], change["material_key"]), dict(
            sheet=change["sheet_name"], material_key=change["material_key"], quantity_change_events=0,
            observed_net_change=Decimal(0), observed_decrease=Decimal(0), observed_increase=Decimal(0),
            interruptions=0, cross_source_changes=0))
        if change["change_type"] == "QUANTITY_CHANGED":
            delta = Decimal(change["observed_net_change"])
            entry["quantity_change_events"] += 1
            entry["observed_net_change"] += delta
            entry["observed_decrease" if delta < 0 else "observed_increase"] += abs(delta)
        else:  # added, removed, became blank/invalid, duplicate rows changed: the series is not continuous
            entry["interruptions"] += 1
        if change["same_source_path"] == 0:
            entry["cross_source_changes"] += 1
    return dict(window_days=days, window_start=stamp(start), window_end=stamp(end), snapshot_count=len(in_window),
                first_snapshot_at=first, retained_from=retained_from,
                covers_full_window=bool(first and first <= stamp(start) and
                                       (retained_from is None or stamp(start) >= retained_from)),
                materials=list(materials.values()), caveat=OBSERVED_CHANGE_CAVEAT)


# ---------------------------------------------------------------------- reconstruction (parity with the Excel reader)
def load_workbook_data(conn, role: str, version_id: int | None = None) -> WorkbookData:
    """Rebuild WorkbookData for parity checks and explicit M3.2A historical-cache calculations.

    The default CHECK still reads Excel. Cache callers must hold a read transaction across both roles."""
    version = (conn.execute("SELECT * FROM source_versions WHERE id = ?", (version_id,)).fetchone() if version_id
               else current_version(conn, role))
    if version is None or version["role"] != role:
        raise LookupError(f"No synchronised {role} version")
    path = version["source_path"]

    def material(row, sheet_name, extra):
        keys = row.keys()
        threshold = ((decode(row["threshold_kind"], row["threshold_text"]), row["threshold_cell_type"] or "")
                     if "threshold_kind" in keys else (None, ""))  # schema 2 only
        return Material(Source(path, sheet_name, row["row_no"]), decode(row["code_kind"], row["code_text"]),
                        decode(row["description_kind"], row["description_text"]),
                        decode(row["qty_kind"], row["qty_text"]), row["qty_cell_type"], row["code_cell_type"],
                        decode(row[f"{extra[0]}_kind"], row[f"{extra[0]}_text"]),
                        decode(row[f"{extra[1]}_kind"], row[f"{extra[1]}_text"]), row["section"], *threshold)

    stock_sheets, products = [], []
    if role == "stock":
        for sheet in conn.execute("SELECT * FROM stock_sheets WHERE source_version_id = ? ORDER BY sheet_index",
                                  (version["id"],)).fetchall():
            rows = conn.execute("SELECT * FROM stock_records WHERE stock_sheet_id = ? ORDER BY ordinal", (sheet["id"],))
            # A version imported before thresholds were stored (schema 1, or not yet captured) says so explicitly.
            state = sheet["threshold_state"] if "threshold_state" in sheet.keys() else None
            candidates = (tuple(tuple(c) for c in json.loads(sheet["threshold_candidates"]))
                          if state and sheet["threshold_candidates"] else ())
            stock_sheets.append(StockSheet(sheet["sheet_name"], sheet["header_row"],
                                           tuple(material(r, sheet["sheet_name"], ("rack", "level")) for r in rows),
                                           state or "NOT_CAPTURED", sheet["threshold_column"] if state else None,
                                           sheet["threshold_header"] if state else None, candidates))
    else:
        for product in conn.execute("SELECT * FROM bom_products WHERE source_version_id = ? ORDER BY sheet_index",
                                    (version["id"],)).fetchall():
            rows = conn.execute("SELECT * FROM bom_lines WHERE bom_product_id = ? ORDER BY ordinal", (product["id"],))
            products.append(Product(path, product["sheet_name"], product["product_id"], product["header_row"],
                                    tuple(material(r, product["sheet_name"], ("column_j", "column_k")) for r in rows)))
    imported = parse_stamp(version["imported_at"])
    sheets = stock_sheets if role == 'stock' else products
    if len(sheets) != version['sheet_count'] or sum(len(s.materials) for s in sheets) != version['record_count']:
        raise LookupError('Workbook payload is no longer retained or is incomplete; no data was reconstructed.')
    return WorkbookData(path, (path, version["size_bytes"], version["mtime_ns"]), tuple(products), tuple(stock_sheets),
                        tuple(json.loads(version["notes"])), imported.replace(tzinfo=timezone.utc).timestamp())
