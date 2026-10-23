"""M4A read-only Inventory History queries: what Storage recorded for one Material ID, and the observed changes.

Everything here is a historical observation of synchronised Storage versions. Nothing is current stock, nothing is
consumption, and nothing is derived to fill a gap: a missing record stays missing, a blank stays blank, a duplicate
stays separate rows, an invalid quantity is shown as read, and Sheets / source files are never merged.

Each query runs inside one read transaction of a read-only connection (`read_view`), so every row of a result comes
from the same database state even if another program publishes a new version meanwhile. Results are capped; totals
are counted so the UI can say what was not loaded. The database is never created, migrated or written.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3

from .core import normalize_code
from .inventory_db import SUPPORTED_SCHEMA_VERSIONS, decode, stamp, utc_now
from .queries import OBSERVED_CHANGE_CAVEAT, open_readonly, snapshots
from .sync import CLOUD_NOT_VERIFIED

RANGES = (30, 60, 90)
MAX_RECORDS = 1000        # history rows loaded per query (the UI renders them in pages)
MAX_CHANGES = 1000
MAX_CANDIDATES = 200
HISTORICAL = "HISTORICAL OBSERVATIONS"
NOT_CURRENT = "Not current stock"
CAVEATS = ("Observed Change ≠ Actual Consumption",
           "Blank stock ≠ 0",
           "Duplicate IDs never added",
           "Invalid quantities never converted",
           "Sheets / source files never merged",
           "No comparable difference across a source switch")
# Row kinds
RECORD, ABSENT, NOT_RETAINED = "RECORD", "ABSENT", "NOT_RETAINED"


class HistoryError(Exception):
    """The history query cannot be answered."""


class HistoryReadError(HistoryError):
    """The database could not be read safely; nothing from this query may be shown as a result."""


class HistoryCancelled(HistoryError):
    """A newer request (or closing the window) superseded this query; it stopped early and has no result."""


_CANCEL = ContextVar("history_cancel", default=None)
PROGRESS_STEPS = 1000     # SQLite steps between cancellation checks inside one statement


@contextmanager
def cancellable(event):
    """Reads started in this block (on this thread) stop cooperatively once `event` is set: before each statement and
    every PROGRESS_STEPS SQLite steps within one. Nothing is killed; the read transaction ends and the connection
    closes as usual. Without this block read_view behaves exactly as before."""
    token = _CANCEL.set(event)
    try:
        yield
    finally:
        _CANCEL.reset(token)


class _Cancellable:
    """The read_view connection, checking the cancel event before each statement."""

    def __init__(self, conn, event):
        self._conn, self._event = conn, event

    def execute(self, *args):
        if self._event.is_set():
            raise HistoryCancelled("History query superseded; no result.")
        return self._conn.execute(*args)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _checkpoint(stage: str) -> None:
    """Test hook between the steps of one query (all steps share one read transaction)."""


@contextmanager
def read_view(database):
    """One consistent read-only view: a deferred read transaction on a `mode=ro` connection.

    A missing file is refused (never created); a foreign or newer schema is refused."""
    path = Path(database)
    conn, cancel = None, _CANCEL.get()
    try:
        if cancel is not None and cancel.is_set():
            raise HistoryCancelled("History query superseded; no result.")
        if not path.is_file():
            raise HistoryReadError(f"Inventory database not found: {path}")
        conn = open_readonly(path)
        if cancel is not None:
            conn.set_progress_handler(cancel.is_set, PROGRESS_STEPS)
        conn.execute("PRAGMA busy_timeout = 1500")
        conn.execute("BEGIN")
        if conn.execute("PRAGMA user_version").fetchone()[0] not in SUPPORTED_SCHEMA_VERSIONS:
            raise HistoryReadError("Unsupported inventory database schema; history query refused.")
        conn.execute("SELECT count(*) FROM inventory_snapshots").fetchone()  # starts the read snapshot
        yield conn if cancel is None else _Cancellable(conn, cancel)
    except HistoryError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError, LookupError, ArithmeticError) as exc:
        if cancel is not None and cancel.is_set():  # interrupted by the progress handler, not a read failure
            raise HistoryCancelled("History query superseded; no result.") from exc
        # Unreadable or inconsistent stored content is a read failure too, never a partial result.
        raise HistoryReadError(f"Inventory database cannot be read: {exc}") from exc
    finally:
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------------- material search
@dataclass(frozen=True)
class Candidate:
    key: str                 # the exact normalized Material ID; selecting it queries exactly this key
    description: object      # raw description in the current Storage version, or None
    in_current: bool


def search_materials(database, text: str, limit: int = MAX_CANDIDATES) -> tuple[list[Candidate], bool]:
    """Material IDs ever seen in Storage that contain `text` (same normalisation as the checker). Exact match first,
    then prefix, then the rest. Similar IDs are separate candidates; nothing is merged. Returns (candidates, more)."""
    needle = normalize_code(text)
    if not needle:
        return [], False
    pattern = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with read_view(database) as conn:
        keys = [r[0] for r in conn.execute(
            "SELECT material_key FROM materials WHERE stock_last_version_id IS NOT NULL"
            " AND material_key LIKE ? ESCAPE '\\'"
            " ORDER BY material_key <> ?, substr(material_key, 1, length(?)) <> ?, length(material_key), material_key"
            " LIMIT ?", (pattern, needle, needle, needle, limit + 1))]
        current = conn.execute("SELECT source_version_id FROM current_sources WHERE role = 'stock'").fetchone()
        result = []
        for key in keys[:limit]:
            row = conn.execute("SELECT description_kind, description_text FROM stock_records"
                               " WHERE source_version_id = ? AND material_key = ? ORDER BY stock_sheet_id, ordinal"
                               " LIMIT 1", (current[0], key)).fetchone() if current else None
            result.append(Candidate(key, decode(row[0], row[1]) if row else None, row is not None))
    return result, len(keys) > limit


def list_sheets(database) -> list[str]:
    """Storage Sheet names present in retained history (exact names, never trimmed or merged)."""
    with read_view(database) as conn:
        return [r[0] for r in conn.execute(
            "SELECT sheet_name FROM stock_sheets GROUP BY sheet_name ORDER BY min(sheet_index), sheet_name")]


# ---------------------------------------------------------------------- history query
@dataclass(frozen=True)
class HistoryRow:
    kind: str                # RECORD / ABSENT / NOT_RETAINED
    reference: bool          # the last snapshot before the window: the state at the window start
    observed_at: str         # UTC stamp of the snapshot (when that Storage version was synchronised)
    snapshot_id: int
    version_id: int
    source_path: str
    sheet: str | None = None
    row_no: int | None = None
    code: object = None
    description: object = None
    quantity: object = None  # raw cell value, exactly as stored
    status: str | None = None  # VALID / BLANK / INVALID
    value: str | None = None   # exact decimal text, only when VALID
    duplicates: int = 1        # rows with this Material ID in the same Sheet of the same version
    rack: object = None
    level: object = None
    note: str = ""


@dataclass(frozen=True)
class ChangeRow:
    snapshot_id: int
    sheet: str
    change_type: str         # QUANTITY_CHANGED / ADDED / REMOVED / VALIDITY_CHANGED / DUPLICATE_CHANGED
    before_at: str | None    # UTC: when the previous Storage version was synchronised
    after_at: str            # UTC: when this Storage version was synchronised
    before_status: str | None
    before_value: str | None
    before_raw: tuple
    after_status: str | None
    after_value: str | None
    after_raw: tuple
    difference: str | None   # only between single VALID records of the same source file
    source_switched: bool
    before_path: str | None
    after_path: str
    note: str


@dataclass(frozen=True)
class Coverage:
    days: int
    evaluated_at: str
    window_start: str
    first_snapshot_at: str | None
    latest_snapshot_at: str | None
    retained_from: str | None
    snapshots_in_window: int
    reference_at: str | None
    covers_full_window: bool
    source_switches: tuple   # (UTC time, from path, to path) inside the window
    notes: tuple[str, ...]


@dataclass(frozen=True)
class HistoryResult:
    database: str
    material_key: str
    sheet: str | None
    rows: tuple[HistoryRow, ...]
    total_rows: int
    changes: tuple[ChangeRow, ...]
    total_changes: int
    coverage: Coverage

    @property
    def truncated(self) -> bool:
        return self.total_rows > len(self.rows) or self.total_changes > len(self.changes)


def _raw_list(text):
    return tuple(decode(kind, value) for kind, value in json.loads(text)) if text else ()


def material_history(database, material_key: str, days: int, sheet: str | None = None,
                     now: datetime | None = None, max_rows: int = MAX_RECORDS,
                     max_changes: int = MAX_CHANGES, *, connection=None) -> HistoryResult:
    """Records and observed changes of exactly one Material ID over the last `days` days, newest first.

    `sheet=None` lists every Sheet, each row labelled with its own Sheet; values are never combined.
    Internal callers may supply an already validated read_view connection to share its snapshot/limits."""
    if days not in RANGES:
        raise HistoryError(f"Unsupported range: {days} days")
    key = normalize_code(material_key)
    if not key:
        raise HistoryError("Select an existing Material ID.")
    end = now or utc_now()
    start = end - timedelta(days=days)
    start_s, end_s = stamp(start), stamp(end)
    with (nullcontext(connection) if connection is not None else read_view(database)) as conn:
        window = snapshots(conn, start, end)
        reference = conn.execute("SELECT * FROM inventory_snapshots WHERE observed_at < ? ORDER BY observed_at DESC,"
                                 " id DESC LIMIT 1", (start_s,)).fetchone()
        first, latest = conn.execute("SELECT min(observed_at), max(observed_at) FROM inventory_snapshots").fetchone()
        retained = conn.execute("SELECT value FROM schema_info WHERE key = 'history_retained_from'").fetchone()
        retained_from = retained[0] if retained else None
        _checkpoint("snapshots")
        listed = sorted(window, key=lambda s: (s["observed_at"], s["id"]), reverse=True)
        if reference is not None:
            listed.append(dict(reference))
        rows, total = [], 0
        for snap in listed:
            version = conn.execute("SELECT source_path, record_count FROM source_versions WHERE id = ?",
                                   (snap["source_version_id"],)).fetchone()
            is_reference = reference is not None and snap["id"] == reference["id"]
            base = dict(reference=is_reference, observed_at=snap["observed_at"], snapshot_id=snap["id"],
                        version_id=snap["source_version_id"], source_path=version["source_path"])
            stored = conn.execute("SELECT count(*) FROM stock_records WHERE source_version_id = ?",
                                  (snap["source_version_id"],)).fetchone()[0]
            if stored != version["record_count"]:
                total += 1
                if len(rows) < max_rows:
                    rows.append(HistoryRow(NOT_RETAINED, sheet=sheet, note=(
                        "Storage rows of this version were removed by Local History maintenance; "
                        "its values are unknown (not 0, not absent)."), **base))
                continue
            sql = ("SELECT s.sheet_name, s.sheet_index, r.* FROM stock_records r JOIN stock_sheets s"
                   " ON s.id = r.stock_sheet_id WHERE r.source_version_id = ? AND r.material_key = ?")
            args = [snap["source_version_id"], key]
            if sheet is not None:
                sql += " AND s.sheet_name = ?"
                args.append(sheet)
            found = conn.execute(sql + " ORDER BY s.sheet_index, r.ordinal", args).fetchall()
            if not found:
                total += 1
                if len(rows) < max_rows:
                    has_sheet = sheet is None or conn.execute(
                        "SELECT 1 FROM stock_sheets WHERE source_version_id = ? AND sheet_name = ?",
                        (snap["source_version_id"], sheet)).fetchone() is not None
                    rows.append(HistoryRow(ABSENT, sheet=sheet, note=(
                        "No record of this Material ID in this Storage version" +
                        (f" (Sheet {sheet!r})" if sheet is not None else "") + "; not 0." if has_sheet else
                        f"Sheet {sheet!r} is not in this Storage version; nothing is known for it."), **base))
                continue
            per_sheet = {}
            for r in found:
                per_sheet[r["sheet_name"]] = per_sheet.get(r["sheet_name"], 0) + 1
            for r in found:
                total += 1
                if len(rows) >= max_rows:
                    continue
                count = per_sheet[r["sheet_name"]]
                rows.append(HistoryRow(
                    RECORD, sheet=r["sheet_name"], row_no=r["row_no"], code=decode(r["code_kind"], r["code_text"]),
                    description=decode(r["description_kind"], r["description_text"]),
                    quantity=decode(r["qty_kind"], r["qty_text"]), status=r["qty_status"], value=r["qty_value"],
                    duplicates=count, rack=decode(r["rack_kind"], r["rack_text"]),
                    level=decode(r["level_kind"], r["level_text"]),
                    note=(f"{count} rows with this ID in this Sheet: kept separate, not added." if count > 1 else ""),
                    **base))
        _checkpoint("records")
        where = " WHERE c.material_key = ? AND s.observed_at >= ? AND s.observed_at <= ?"
        args = [key, start_s, end_s]
        if sheet is not None:
            where += " AND c.sheet_name = ?"
            args.append(sheet)
        total_changes = conn.execute("SELECT count(*) FROM inventory_changes c JOIN inventory_snapshots s"
                                     " ON s.id = c.snapshot_id" + where, args).fetchone()[0]
        changes = [_change(r) for r in conn.execute(
            "SELECT c.*, s.observed_at, s.same_source_path, pv.imported_at AS before_at, pv.source_path AS before_path,"
            " av.source_path AS after_path FROM inventory_changes c JOIN inventory_snapshots s ON s.id = c.snapshot_id"
            " JOIN source_versions av ON av.id = s.source_version_id"
            " LEFT JOIN source_versions pv ON pv.id = s.previous_version_id" + where +
            " ORDER BY s.observed_at DESC, s.id DESC, c.sheet_name, c.id LIMIT ?", (*args, max_changes))]
        switches = tuple((s["observed_at"], *conn.execute(
            "SELECT pv.source_path, av.source_path FROM source_versions av LEFT JOIN source_versions pv ON pv.id = ?"
            " WHERE av.id = ?", (s["previous_version_id"], s["source_version_id"])).fetchone())
            for s in sorted(window, key=lambda s: s["id"]) if s["same_source_path"] == 0)
    covers = bool(first and first <= start_s and (retained_from is None or start_s >= retained_from))
    coverage = Coverage(days, end_s, start_s, first, latest, retained_from, len(window),
                        reference["observed_at"] if reference is not None else None, covers, switches,
                        _coverage_notes(days, start_s, first, retained_from, window, reference, switches))
    return HistoryResult(str(Path(database)), key, sheet, tuple(rows), total, tuple(changes), total_changes, coverage)


def _change(r) -> ChangeRow:
    switched = r["same_source_path"] == 0
    kind = r["change_type"]
    difference = r["observed_net_change"] if kind == "QUANTITY_CHANGED" and not switched else None
    notes = {"QUANTITY_CHANGED": "Observed difference between two single valid records; not consumption.",
             "ADDED": "Material ID appeared in this Sheet; no earlier record to compare.",
             "REMOVED": "Material ID no longer in this Sheet; removal is not consumption and not 0.",
             "VALIDITY_CHANGED": "Quantity became or stopped being blank/invalid; no difference calculated.",
             "DUPLICATE_CHANGED": "Duplicate rows changed; duplicates are never added, no difference calculated."}
    note = notes.get(kind, "")
    if switched:
        note = "Source file switched between these versions: not comparable. " + note
    return ChangeRow(r["snapshot_id"], r["sheet_name"], kind, r["before_at"], r["observed_at"], r["previous_status"],
                     r["previous_value"], _raw_list(r["previous_raw"]), r["new_status"], r["new_value"],
                     _raw_list(r["new_raw"]), difference, switched, r["before_path"], r["after_path"], note)


def _coverage_notes(days, start, first, retained_from, window, reference, switches) -> tuple[str, ...]:
    notes = []
    if first is None:
        return ("No Storage history has been synchronised yet. Nothing is shown and nothing is assumed.",)
    if retained_from is not None and start < retained_from:
        notes.append(f"Local History maintenance removed records before {retained_from} UTC: "
                     f"the {days}-day window is only partly covered.")
    if first > start:
        notes.append(f"History starts at {first} UTC, inside the {days}-day window: "
                     "earlier stock is unknown, not 0.")
    if not window:
        notes.append(f"No Storage version was synchronised in the last {days} days. Snapshots are recorded only "
                     "when a new Storage version is imported.")
    if reference is not None:
        notes.append(f"The row marked 'Before window' is the last snapshot before the window ({reference['observed_at']} "
                     "UTC): the recorded state at the window start, not a new observation.")
    for at, before, after in switches:
        notes.append(f"Source file switched at {at} UTC ({before} → {after}): differences across it are not comparable.")
    return tuple(notes)


def summary_line() -> str:
    return f"{HISTORICAL} · {NOT_CURRENT} · {CLOUD_NOT_VERIFIED}"


__all__ = ["CAVEATS", "OBSERVED_CHANGE_CAVEAT", "HISTORICAL", "RANGES", "HistoryError", "HistoryReadError",
           "HistoryResult", "HistoryRow", "ChangeRow", "Coverage", "Candidate", "read_view", "search_materials",
           "list_sheets", "material_history", "summary_line", "RECORD", "ABSENT", "NOT_RETAINED"]
