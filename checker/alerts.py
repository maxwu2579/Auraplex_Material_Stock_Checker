"""M3.2C stock alerts from the synchronised Storage and BOM data. Deterministic, read-mostly, never writes Excel.

Evaluation (evaluate) reads ONE consistent view of the current Storage and BOM versions, per Storage Sheet:

OUT_OF_STOCK                       unique Material ID whose LIVE STOCK is the valid number 0 (whatever the threshold).
                                   It is the recorded stock; it does not prove that any production order is short.
LOW_STOCK                          unique ID, valid LIVE STOCK and valid threshold, LIVE STOCK < threshold (trial).
                                   Equal is not low. Threshold meaning and units are pending business confirmation;
                                   LIVE STOCK and the threshold of the same row are compared as trial-comparable. The
                                   threshold shortfall (threshold − LIVE STOCK) is shown; it is not a production need.
BOM_MATERIAL_NOT_IN_STOCK_MASTER   a valid BOM Material ID with no exact match in that Storage Sheet: stock unknown,
                                   never 0. One alert per (Sheet, ID) listing every product / BOM Sheet / row; BOM
                                   quantities are never added and no production total is calculated.
DATA_ISSUE                         blank or invalid LIVE STOCK, invalid threshold, duplicate Storage ID (rows kept
                                   separate, never added), unusable Storage ID, ambiguous threshold columns.
THRESHOLD_NOT_CONFIGURED           unique ID whose threshold cell is blank. Not 0; other alerts are not suppressed.

A threshold 0 is kept as the number 0 and not interpreted ("no stock needed" / "alert off" are not assumed).
Matching uses the checker's exact normalisation (normalize_code); the M2 CHECK rules (ASSUMED 0) are not used here.

Identity and scope (schema 3). An alert is identified by (type, subtype, Storage file, [BOM file for BOM-coverage
alerts], Storage Sheet, Material ID or row). New versions of the same file therefore de-duplicate, while the same
Sheet / ID in another file is a different alert. An evaluation can resolve only alerts of its own files: an alert of
another file stays ACTIVE ("other source, not re-checked"), it is never treated as recovered.

Verification. An evaluation may add, update or resolve alerts only when ALL of the following hold, checked again under
the database write lock immediately before anything is written:
- for both roles, the newest sync record is a success for the current version (a failure recorded meanwhile, even for
  the same version, makes the evaluation stale and nothing is written);
- the caller's Authorization names exactly those versions and source paths (taken from its own successful syncs);
- the caller's SessionGate generation is unchanged (the UI invalidates it on every source selection, sync, failure -
  also failures that could not be written to SQLite - and database read failure).
Otherwise the evaluation is recorded as UNVERIFIED (or FAILED) and no alert changes.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
import json
import queue
import threading

from .core import number
from .history import _change, read_view
from .inventory_db import (ALERT_SCHEMA_VERSION, connect, decode, schema_version, source_identity, stamp, utc_now)
from .queries import current_version
from .sync import IMPORTED, UNCHANGED, same_path

OUT_OF_STOCK, LOW_STOCK = "OUT_OF_STOCK", "LOW_STOCK"
NOT_IN_MASTER, DATA_ISSUE, NOT_CONFIGURED = "BOM_MATERIAL_NOT_IN_STOCK_MASTER", "DATA_ISSUE", "THRESHOLD_NOT_CONFIGURED"
TYPES = (OUT_OF_STOCK, LOW_STOCK, NOT_IN_MASTER, DATA_ISSUE, NOT_CONFIGURED)
ACTIVE, RESOLVED = "ACTIVE", "RESOLVED"
COMPLETED, UNVERIFIED, FAILED = "COMPLETED", "UNVERIFIED", "FAILED"
KEEP_EVALUATIONS = 200          # most recent evaluation rows kept, plus every row still needed as provenance
KEEP_RESOLVED_DAYS = 180        # resolved alerts kept this long after resolution
MAX_LOADED_ALERTS = 5000        # rows returned to the UI per load; totals are always counted
MAX_LOADED_CHANGES = 2000       # observed-change rows returned per load; totals are always counted
CHANGE_RANGES = (30, 60, 90)
PENDING_CONFIRMATION = "Threshold meaning and units are pending business confirmation."

NOTES = {
    OUT_OF_STOCK: "Recorded LIVE STOCK is 0. This does not prove that a production order is short.",
    LOW_STOCK: "Trial only: LIVE STOCK < threshold of the same row; equal is not low. The threshold shortfall is "
               "not a production requirement. " + PENDING_CONFIRMATION,
    NOT_IN_MASTER: "No exact Material ID match in this Storage Sheet: actual stock unknown, not 0. "
                   "BOM quantities are listed per row, never added.",
    NOT_CONFIGURED: "Threshold cell is blank: not configured. Not treated as 0.",
    "BLANK_STOCK": "LIVE STOCK is blank: unknown, not 0.",
    "INVALID_STOCK": "LIVE STOCK is not a valid non-negative number (text, formula, error, boolean or negative); "
                     "shown as read, never converted.",
    "INVALID_THRESHOLD": "Threshold is not a valid non-negative number; shown as read, never converted.",
    "DUPLICATE_STOCK_ID": "Several Storage rows share this Material ID in one Sheet: kept separate, never added; "
                          "stock and threshold cannot be assessed.",
    "UNUSABLE_STOCK_ID": "Storage row without a usable text Material ID (blank, numeric cell, formula or error); "
                         "it cannot be matched.",
    "THRESHOLD_COLUMN_AMBIGUOUS": "Several threshold columns (MIN QTY / MIIN QTY) found; none chosen. Confirm which "
                                  "column is the minimum stock. Threshold checks are not done for this Sheet.",
}


class AlertError(Exception):
    """The evaluation could not be completed; no alert was changed."""


class AlertUnavailable(AlertError):
    """Alerts need the schema-3 database (explicit upgrade) or synchronised Storage and BOM data."""


class AlertStale(AlertError):
    """Versions or sync records changed between reading and writing; nothing was written."""


def alert_key(alert_type, subtype, storage_source, bom_source, sheet, material_key, row) -> str:
    """The schema-3 alert identity. The BOM file belongs to the identity of BOM-coverage alerts only."""
    return json.dumps([alert_type, subtype, storage_source, bom_source, sheet, material_key, row], ensure_ascii=False)


def quantity_status(value, cell_type) -> tuple[str, Decimal | None]:
    """The M2 stock rule, applied to a threshold as well: only a native, finite, non-negative number is valid."""
    parsed = number(value) if cell_type not in ("f", "e") else None
    if parsed is not None and parsed >= 0:
        return "VALID", parsed
    blank = value is None or (isinstance(value, str) and not value.strip())
    return ("BLANK" if blank else "INVALID"), None


# ---------------------------------------------------------------------- session verification
class SessionGate:
    """Thread-safe generation of the caller's verification. Invalidate it whenever an earlier verification may no
    longer describe the files (selection, sync, failure, database read failure). Workers check it under the lock."""

    def __init__(self):
        self._lock = threading.Lock()
        self._generation = 0

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def invalidate(self) -> int:
        with self._lock:
            self._generation += 1
            return self._generation

    def valid(self, generation) -> bool:
        with self._lock:
            return generation == self._generation

    @contextmanager
    def publishing(self, generation):
        """Publication guard: yields whether `generation` is still current and keeps invalidate() waiting until the
        block ends. The publisher holds its SQLite EXCLUSIVE lock BEFORE entering, so the block (a final check and
        COMMIT) never waits for another connection; invalidate() is therefore ordered entirely before or after the
        publication, and the gate lock is never held while waiting for SQLite."""
        with self._lock:
            yield generation == self._generation


def _always_valid():
    return nullcontext(True)


def _checkpoint(stage, conn):
    """No-op test hook inside the publication transaction: 'evaluation_inserted', 'alerts_upserted',
    'alerts_resolved', 'before_commit'."""


@dataclass(frozen=True)
class Authorization:
    """What the caller itself verified in this session: per role the version ID and the selected source path of its
    latest successful sync, at one gate generation."""
    generation: int
    sources: tuple  # ((role, version_id, path), ...)

    def source(self, role):
        return next(((v, p) for r, v, p in self.sources if r == role), None)


# ---------------------------------------------------------------------- evaluation (pure read)
@dataclass(frozen=True)
class Alert:
    alert_type: str
    subtype: str
    stock_sheet: str
    material_key: str | None
    row: int | None            # identity only for rows without a usable Material ID
    storage_source: str | None
    bom_source: str | None     # BOM-coverage alerts only
    detail: dict = field(compare=False)

    @property
    def key(self) -> str:
        return alert_key(self.alert_type, self.subtype, self.storage_source, self.bom_source, self.stock_sheet,
                         self.material_key, self.row)


@dataclass(frozen=True)
class Evaluation:
    stock_version: dict
    bom_version: dict
    runs: dict                 # role -> latest sync record (id, outcome, source_version_id, source_path)
    db_verified: bool          # newest sync of both roles succeeded for the current versions
    storage_source: str
    bom_source: str
    sheets: tuple[str, ...]
    alerts: tuple[Alert, ...]
    summary: dict


def _versions(conn):
    stock, bom = current_version(conn, "stock"), current_version(conn, "bom")
    if stock is None or bom is None:
        raise AlertUnavailable("Storage and BOM must both be synchronised before alerts can be evaluated.")
    return stock, bom


def _latest_runs(conn) -> dict:
    runs = {}
    for role in ("stock", "bom"):
        row = conn.execute("SELECT id, outcome, source_version_id, source_path FROM sync_runs WHERE role = ?"
                           " ORDER BY id DESC LIMIT 1", (role,)).fetchone()
        runs[role] = tuple(row) if row else None
    return runs


def _require_schema(conn):
    if schema_version(conn) < ALERT_SCHEMA_VERSION:
        raise AlertUnavailable("Stock alerts need the upgraded local database (schema 3).")


def evaluate(conn) -> Evaluation:
    """Pure read inside the caller's read transaction."""
    _require_schema(conn)
    stock_v, bom_v = _versions(conn)
    for version, table in ((stock_v, "stock_records"), (bom_v, "bom_lines")):
        stored = conn.execute(f"SELECT count(*) FROM {table} WHERE source_version_id = ?", (version["id"],)).fetchone()[0]
        if stored != version["record_count"]:
            raise AlertError(f"The current {version['role']} version is incomplete in the database; no alerts evaluated.")
    runs = _latest_runs(conn)
    db_verified = all(runs[role] is not None and runs[role][1] in (IMPORTED, UNCHANGED) and runs[role][2] == version["id"]
                      for role, version in (("stock", stock_v), ("bom", bom_v)))
    storage, bom_scope = source_identity(stock_v["source_path"]), source_identity(bom_v["source_path"])
    sheets = conn.execute("SELECT * FROM stock_sheets WHERE source_version_id = ? ORDER BY sheet_index",
                          (stock_v["id"],)).fetchall()
    bom = conn.execute(
        "SELECT p.product_id, p.sheet_name, l.row_no, l.material_key, l.code_kind, l.code_text, l.description_kind,"
        " l.description_text, l.qty_kind, l.qty_text FROM bom_lines l JOIN bom_products p ON p.id = l.bom_product_id"
        " WHERE l.source_version_id = ? ORDER BY p.sheet_index, l.ordinal", (bom_v["id"],)).fetchall()
    bom_keyed = [b for b in bom if b["material_key"]]
    files = dict(storage_file=stock_v["source_path"], storage_version=stock_v["id"])
    alerts, per_sheet = [], {}
    for sheet in sheets:
        name = sheet["sheet_name"]
        records = conn.execute("SELECT * FROM stock_records WHERE stock_sheet_id = ? ORDER BY ordinal",
                               (sheet["id"],)).fetchall()
        state = sheet["threshold_state"] or "NOT_CAPTURED"
        threshold_info = dict(state=state, column=sheet["threshold_column"], header=sheet["threshold_header"],
                              candidates=json.loads(sheet["threshold_candidates"]) if sheet["threshold_candidates"] else [])
        sheet_alerts = _sheet_alerts(name, records, state, sheet["threshold_header"], sheet["threshold_column"],
                                     threshold_info, storage, files)
        keys = {r["material_key"] for r in records if r["material_key"]}
        missing = defaultdict(list)
        for b in bom_keyed:
            if b["material_key"] not in keys:
                missing[b["material_key"]].append(b)
        for key, rows in sorted(missing.items()):
            occurrences = [dict(product=b["product_id"], bom_sheet=b["sheet_name"], row=b["row_no"],
                                code=[b["code_kind"], b["code_text"]],
                                description=[b["description_kind"], b["description_text"]],
                                qty=[b["qty_kind"], b["qty_text"]]) for b in rows]
            sheet_alerts.append(Alert(NOT_IN_MASTER, NOT_IN_MASTER, name, key, None, storage, bom_scope, dict(
                files, bom_file=bom_v["source_path"], bom_version=bom_v["id"], occurrences=occurrences,
                bom_rows=len(rows), products=sorted({b["product_id"] for b in rows}), note=NOTES[NOT_IN_MASTER])))
        counts = defaultdict(int)
        for a in sheet_alerts:
            counts[a.alert_type] += 1
        missing_rows = [b for rows in missing.values() for b in rows]
        per_sheet[name] = dict(
            threshold=threshold_info, storage_rows=len(records), counts={t: counts[t] for t in TYPES},
            data_issue_subtypes=dict(sorted(_subtypes(sheet_alerts).items())),
            missing_distinct_ids=len(missing), missing_bom_rows=len(missing_rows),
            missing_products=len({b["product_id"] for b in missing_rows}))
        alerts.extend(sheet_alerts)
    summary = dict(sheets=per_sheet, bom_rows=len(bom), bom_rows_without_usable_id=len(bom) - len(bom_keyed),
                   bom_distinct_ids=len({b["material_key"] for b in bom_keyed}),
                   bom_products=len({b["product_id"] for b in bom}))
    version = lambda v: dict(id=v["id"], path=v["source_path"], file_name=v["file_name"], imported_at=v["imported_at"],
                             source_modified_at=v["source_modified_at"])
    return Evaluation(version(stock_v), version(bom_v), runs, db_verified, storage, bom_scope,
                      tuple(s["sheet_name"] for s in sheets), tuple(alerts), summary)


def _subtypes(alerts):
    counts = defaultdict(int)
    for a in alerts:
        if a.alert_type == DATA_ISSUE:
            counts[a.subtype] += 1
    return counts


def _sheet_alerts(sheet, records, state, header, column, threshold_info, storage, files):
    alerts = []

    def alert(alert_type, subtype, key, row, detail):
        alerts.append(Alert(alert_type, subtype, sheet, key, row, storage, None, dict(files, **detail)))

    if state == "AMBIGUOUS":
        alert(DATA_ISSUE, "THRESHOLD_COLUMN_AMBIGUOUS", None, None,
              dict(threshold=threshold_info, note=NOTES["THRESHOLD_COLUMN_AMBIGUOUS"]))
    groups, unkeyed = defaultdict(list), []
    for r in records:
        (groups[r["material_key"]] if r["material_key"] else unkeyed).append(r)

    def side(r):
        return dict(row=r["row_no"], code=[r["code_kind"], r["code_text"]],
                    description=[r["description_kind"], r["description_text"]],
                    stock=[r["qty_kind"], r["qty_text"]], stock_status=r["qty_status"], stock_value=r["qty_value"],
                    threshold=[r["threshold_kind"], r["threshold_text"]] if state == "FOUND" else None,
                    threshold_header=header if state == "FOUND" else None,
                    threshold_column=column if state == "FOUND" else None,
                    rack=[r["rack_kind"], r["rack_text"]], level=[r["level_kind"], r["level_text"]])

    for key, rows in groups.items():
        if len(rows) > 1:
            alert(DATA_ISSUE, "DUPLICATE_STOCK_ID", key, None,
                  dict(rows=[side(r) for r in rows], note=NOTES["DUPLICATE_STOCK_ID"]))
            continue
        r = rows[0]
        stock_status = r["qty_status"]
        stock = Decimal(r["qty_value"]) if stock_status == "VALID" else None
        # NOT_FOUND / NOT_CAPTURED / AMBIGUOUS: no threshold check is possible and nothing is assumed.
        t_status, threshold = (quantity_status(decode(r["threshold_kind"], r["threshold_text"]),
                                               r["threshold_cell_type"]) if state == "FOUND" else (None, None))
        # Every alert of this row carries the threshold as recorded (a 0 threshold stays the number 0).
        base = dict(side(r), threshold_status=t_status, threshold_value=None if threshold is None else str(threshold))
        if stock_status == "VALID" and stock == 0:
            alert(OUT_OF_STOCK, OUT_OF_STOCK, key, None, dict(base, note=NOTES[OUT_OF_STOCK]))
        elif stock_status == "BLANK":
            alert(DATA_ISSUE, "BLANK_STOCK", key, None, dict(base, note=NOTES["BLANK_STOCK"]))
        elif stock_status == "INVALID":
            alert(DATA_ISSUE, "INVALID_STOCK", key, None, dict(base, note=NOTES["INVALID_STOCK"]))
        if state != "FOUND":
            continue
        if t_status == "BLANK":
            alert(NOT_CONFIGURED, NOT_CONFIGURED, key, None, dict(base, note=NOTES[NOT_CONFIGURED]))
        elif t_status == "INVALID":
            alert(DATA_ISSUE, "INVALID_THRESHOLD", key, None, dict(base, note=NOTES["INVALID_THRESHOLD"]))
        elif stock is not None and stock < threshold:
            alert(LOW_STOCK, LOW_STOCK, key, None,
                  dict(base, threshold_shortfall=str(threshold - stock), note=NOTES[LOW_STOCK]))
    for r in unkeyed:
        alert(DATA_ISSUE, "UNUSABLE_STOCK_ID", None, r["row_no"],
              dict(side(r), numeric_code=r["numeric_code"], note=NOTES["UNUSABLE_STOCK_ID"]))
    return alerts


# ---------------------------------------------------------------------- persistence
@dataclass(frozen=True)
class RunResult:
    evaluation_id: int
    outcome: str
    verified: bool
    reason: str | None
    stock_version_id: int
    bom_version_id: int
    storage_source: str
    bom_source: str
    active: int                # ACTIVE alerts of this evaluation's files
    new: int
    resolved: int
    summary: dict


def _in_scope_sql(alias=""):
    """ACTIVE-alert scope of an evaluation: its Storage file, and for BOM-coverage alerts also its BOM file."""
    a = f"{alias}." if alias else ""
    return (f"({a}storage_source IS ? AND ({a}alert_type <> '{NOT_IN_MASTER}' OR {a}bom_source IS ?))")


class AlertService:
    def __init__(self, database, clock=utc_now):
        self.database = database
        self.clock = clock

    def run(self, trigger: str, authorization: Authorization | None, guard=None) -> RunResult:
        """Evaluate and record. Raises AlertUnavailable / AlertStale / AlertError.

        guard() returns a context manager yielding whether the caller's verification is still current (the runner
        passes SessionGate.publishing). A verified result is published only inside that guard: if the verification
        was invalidated at any point before COMMIT, the whole transaction is rolled back and the attempt is recorded
        as UNVERIFIED in a separate transaction that changes no alert."""
        guard = guard or _always_valid
        started = stamp(self.clock())
        try:
            with read_view(self.database) as conn:
                evaluation = evaluate(conn)
        except AlertUnavailable:
            raise
        except Exception as exc:
            self._record_failure(trigger, started, exc)
            raise AlertError(f"Stock alerts could not be evaluated; no alert was changed: {exc}") from exc
        result = self._publish(trigger, started, evaluation, authorization, guard)
        if result is None:
            result = self._publish(trigger, started, evaluation, None, _always_valid,
                                   refused="the session's verification changed before publication")
        return result

    def _publish(self, trigger, started, evaluation, authorization, guard, refused=None):
        """One write transaction. Returns None when a verified publication was refused by the guard (rolled back)."""
        stock_id, bom_id = evaluation.stock_version["id"], evaluation.bom_version["id"]
        conn = connect(self.database)
        try:
            # EXCLUSIVE now, so that COMMIT inside the guard never has to wait for another connection.
            conn.execute("BEGIN EXCLUSIVE")
            _require_schema(conn)
            stock, bom = _versions(conn)
            # Anything recorded since the read - a new version, or any sync record (a failure of the same version
            # included) - makes this evaluation stale: nothing is written, the caller evaluates again.
            if (stock["id"], bom["id"]) != (stock_id, bom_id) or _latest_runs(conn) != evaluation.runs:
                raise AlertStale("Synchronisation records changed while alerts were evaluated.")
            reasons = [refused] if refused else []
            if not evaluation.db_verified:
                reasons.append("the newest synchronisation of Storage and BOM is not a success for the current versions")
            if authorization is None:
                if not refused:
                    reasons.append("the Excel files were not both verified in this session")
            else:
                for role, version_id in (("stock", stock_id), ("bom", bom_id)):
                    granted, run = authorization.source(role), evaluation.runs[role]
                    if granted is None or granted[0] != version_id or run is None or not same_path(granted[1], run[3]):
                        reasons.append(f"this session did not verify the current {'Storage' if role == 'stock' else 'BOM'}"
                                       " version")
            with guard() as current:  # early exit only; the authoritative check is the one around COMMIT
                pass
            if not current:
                reasons.append("the session's verification changed during the evaluation")
            verified = not reasons
            reason = None if verified else "; ".join(reasons)
            now = stamp(self.clock())
            summary = dict(evaluation.summary, stock_version=evaluation.stock_version,
                           bom_version=evaluation.bom_version)
            evaluation_id = conn.execute(
                "INSERT INTO alert_evaluations (trigger, started_at, finished_at, outcome, stock_version_id,"
                " bom_version_id, sources_verified, sheet_scope, summary, error_message, storage_source, bom_source)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (trigger, started, now, COMPLETED if verified else UNVERIFIED, stock_id, bom_id, int(verified),
                 json.dumps(list(evaluation.sheets), ensure_ascii=False),
                 json.dumps(summary, ensure_ascii=False, default=str), reason,
                 evaluation.storage_source, evaluation.bom_source)).lastrowid
            _checkpoint("evaluation_inserted", conn)
            new = resolved = 0
            if verified:
                scope = (evaluation.storage_source, evaluation.bom_source)
                existing = {r["alert_key"]: r for r in conn.execute(
                    "SELECT alert_key, status, alert_type, bom_source FROM stock_alerts WHERE storage_source IS ?",
                    (evaluation.storage_source,))}
                seen = set()
                for alert in evaluation.alerts:
                    seen.add(alert.key)
                    detail = json.dumps(alert.detail, ensure_ascii=False, default=str)
                    old = existing.get(alert.key)
                    if old is None:
                        new += 1
                        conn.execute(
                            "INSERT INTO stock_alerts (alert_key, alert_type, subtype, stock_sheet, material_key, status,"
                            " first_seen_at, last_seen_at, first_evaluation_id, last_evaluation_id, stock_version_id,"
                            " bom_version_id, detail, storage_source, bom_source)"
                            " VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (alert.key, alert.alert_type, alert.subtype, alert.stock_sheet, alert.material_key, now, now,
                             evaluation_id, evaluation_id, stock_id, bom_id, detail, alert.storage_source,
                             alert.bom_source))
                    elif old["status"] == RESOLVED:  # a new episode of an earlier alert of the same files
                        new += 1
                        conn.execute(
                            "UPDATE stock_alerts SET status = 'ACTIVE', first_seen_at = ?, last_seen_at = ?,"
                            " first_evaluation_id = ?, last_evaluation_id = ?, resolved_at = NULL,"
                            " resolved_evaluation_id = NULL, stock_version_id = ?, bom_version_id = ?, detail = ?"
                            " WHERE alert_key = ?", (now, now, evaluation_id, evaluation_id, stock_id, bom_id, detail,
                                                     alert.key))
                    else:
                        conn.execute("UPDATE stock_alerts SET last_seen_at = ?, last_evaluation_id = ?,"
                                     " stock_version_id = ?, bom_version_id = ?, detail = ? WHERE alert_key = ?",
                                     (now, evaluation_id, stock_id, bom_id, detail, alert.key))
                _checkpoint("alerts_upserted", conn)
                # Only alerts of exactly these files can recover; another BOM file's coverage alerts stay as they are.
                gone = [key for key, row in existing.items() if row["status"] == ACTIVE and key not in seen
                        and (row["alert_type"] != NOT_IN_MASTER or row["bom_source"] == scope[1])]
                for key in gone:
                    conn.execute("UPDATE stock_alerts SET status = 'RESOLVED', resolved_at = ?,"
                                 " resolved_evaluation_id = ? WHERE alert_key = ?", (now, evaluation_id, key))
                resolved = len(gone)
                _checkpoint("alerts_resolved", conn)
            self._prune(conn)
            active = conn.execute("SELECT count(*) FROM stock_alerts WHERE status = 'ACTIVE' AND " + _in_scope_sql(),
                                  (evaluation.storage_source, evaluation.bom_source)).fetchone()[0]
            _checkpoint("before_commit", conn)
            if verified:
                # Publication point: the verification must still be current while COMMIT happens.
                with guard() as current:
                    if current:
                        conn.execute("COMMIT")
                if not current:
                    conn.execute("ROLLBACK")
                    return None
            else:
                conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        return RunResult(evaluation_id, COMPLETED if verified else UNVERIFIED, verified, reason, stock_id, bom_id,
                         evaluation.storage_source, evaluation.bom_source, active, new, resolved, summary)

    def _prune(self, conn):
        """Bounded history that never removes provenance still in use: the newest KEEP_EVALUATIONS rows, the latest
        verified evaluation of every file scope, and every evaluation an alert row references are kept."""
        conn.execute(
            "DELETE FROM alert_evaluations WHERE id NOT IN (SELECT id FROM alert_evaluations ORDER BY id DESC LIMIT ?)"
            " AND id NOT IN (SELECT max(id) FROM alert_evaluations WHERE outcome = 'COMPLETED'"
            "                GROUP BY storage_source, bom_source)"
            " AND id NOT IN (SELECT first_evaluation_id FROM stock_alerts UNION SELECT last_evaluation_id FROM stock_alerts"
            "                UNION SELECT resolved_evaluation_id FROM stock_alerts WHERE resolved_evaluation_id IS NOT NULL)",
            (KEEP_EVALUATIONS,))
        cutoff = stamp(self.clock() - timedelta(days=KEEP_RESOLVED_DAYS))
        conn.execute("DELETE FROM stock_alerts WHERE status = 'RESOLVED' AND resolved_at < ?", (cutoff,))

    def _record_failure(self, trigger, started, exc):
        """Best effort: a failed evaluation is visible later, changes no alert, and is pruned like the others."""
        try:
            conn = connect(self.database)
            try:
                if schema_version(conn) >= ALERT_SCHEMA_VERSION:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("INSERT INTO alert_evaluations (trigger, started_at, finished_at, outcome,"
                                 " sources_verified, error_message) VALUES (?, ?, ?, 'FAILED', 0, ?)",
                                 (trigger, started, stamp(self.clock()), str(exc)))
                    self._prune(conn)
                    conn.execute("COMMIT")
            finally:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------- read model for the UI
@dataclass(frozen=True)
class AlertRow:
    alert_type: str
    subtype: str
    stock_sheet: str
    material_key: str | None
    status: str
    first_seen_at: str
    last_seen_at: str
    resolved_at: str | None
    stock_version_id: int | None
    bom_version_id: int | None
    storage_source: str | None
    bom_source: str | None
    in_scope: bool             # belongs to the files that are current in the database now
    detail: dict


@dataclass(frozen=True)
class AlertState:
    schema: int
    storage_source: str | None     # files current in the database (normalised identity)
    bom_source: str | None
    storage_path: str | None
    bom_path: str | None
    latest: dict | None            # most recent evaluation attempt, any outcome or scope
    latest_completed: dict | None  # most recent COMPLETED evaluation of the current files
    active_counts: dict            # ACTIVE alerts of the current files, by type
    other_sources_active: int      # ACTIVE alerts of other files: not re-checked, never treated as recovered
    rows: tuple[AlertRow, ...]
    total_rows: int


def _evaluation(row):
    if row is None:
        return None
    data = dict(row)
    data["summary"] = json.loads(data["summary"]) if data["summary"] else {}
    data["sheet_scope"] = json.loads(data["sheet_scope"]) if data["sheet_scope"] else []
    return data


def load_state(database, include_resolved=False, include_other_sources=True, limit=MAX_LOADED_ALERTS) -> AlertState:
    """Read-only, one consistent view. Below schema 3: an empty state saying an upgrade is required."""
    with read_view(database) as conn:
        version = schema_version(conn)
        if version < ALERT_SCHEMA_VERSION:
            return AlertState(version, None, None, None, None, None, None, {}, 0, (), 0)
        stock, bom = current_version(conn, "stock"), current_version(conn, "bom")
        storage = source_identity(stock["source_path"]) if stock else None
        bom_scope = source_identity(bom["source_path"]) if bom else None
        scope = (storage, bom_scope)
        latest = _evaluation(conn.execute("SELECT * FROM alert_evaluations ORDER BY id DESC LIMIT 1").fetchone())
        completed = _evaluation(conn.execute(
            "SELECT * FROM alert_evaluations WHERE outcome = 'COMPLETED' AND storage_source IS ? AND bom_source IS ?"
            " ORDER BY id DESC LIMIT 1", scope).fetchone())
        counts = {r[0]: r[1] for r in conn.execute(
            "SELECT alert_type, count(*) FROM stock_alerts WHERE status = 'ACTIVE' AND " + _in_scope_sql() +
            " GROUP BY alert_type", scope)}
        others = conn.execute("SELECT count(*) FROM stock_alerts WHERE status = 'ACTIVE' AND NOT " + _in_scope_sql(),
                              scope).fetchone()[0]
        conditions = [] if include_resolved else ["status = 'ACTIVE'"]
        args = []
        if not include_other_sources:
            conditions.append(_in_scope_sql())
            args.extend(scope)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        total = conn.execute("SELECT count(*) FROM stock_alerts" + where, args).fetchone()[0]
        order = " ".join(f"WHEN '{t}' THEN {i}" for i, t in enumerate(TYPES))
        rows = tuple(AlertRow(r["alert_type"], r["subtype"], r["stock_sheet"], r["material_key"], r["status"],
                              r["first_seen_at"], r["last_seen_at"], r["resolved_at"], r["stock_version_id"],
                              r["bom_version_id"], r["storage_source"], r["bom_source"], bool(r["in_scope"]),
                              json.loads(r["detail"]))
                     for r in conn.execute(f"SELECT *, {_in_scope_sql()} AS in_scope FROM stock_alerts{where}"
                                           f" ORDER BY status = 'RESOLVED', in_scope DESC,"
                                           f" CASE alert_type {order} END, stock_sheet, subtype, material_key, id"
                                           f" LIMIT ?", (*scope, *args, limit)))
    return AlertState(version, storage, bom_scope, stock["source_path"] if stock else None,
                      bom["source_path"] if bom else None, latest, completed, counts, others, rows, total)


# ---------------------------------------------------------------------- observed stock changes (historical view)
@dataclass(frozen=True)
class ChangesView:
    storage_path: str | None
    days: int
    window_start: str
    evaluated_at: str
    rows: tuple                    # ((material_key, history.ChangeRow), ...), newest first
    total: int
    first_snapshot_at: str | None
    retained_from: str | None
    notes: tuple[str, ...]


def observed_changes_view(database, days: int, now=None, limit=MAX_LOADED_CHANGES) -> ChangesView:
    """Observed differences between synchronised versions of the CURRENT Storage file in the last `days` days, all
    materials, from the stored M3.1 snapshots (no Excel parsing). Historical observations only: never consumption,
    never a production-order shortage; a difference only between single valid records of the same file."""
    if days not in CHANGE_RANGES:
        raise AlertError(f"Unsupported range: {days} days")
    end = now or utc_now()
    start_s, end_s = stamp(end - timedelta(days=days)), stamp(end)
    with read_view(database) as conn:
        stock = current_version(conn, "stock")
        if stock is None:
            return ChangesView(None, days, start_s, end_s, (), 0, None, None,
                               ("No Storage file has been synchronised yet. Nothing is shown and nothing is assumed.",))
        where = (" FROM inventory_changes c JOIN inventory_snapshots s ON s.id = c.snapshot_id"
                 " JOIN source_versions av ON av.id = s.source_version_id"
                 " LEFT JOIN source_versions pv ON pv.id = s.previous_version_id"
                 " WHERE av.source_path = ? AND s.observed_at >= ? AND s.observed_at <= ?")
        args = (stock["source_path"], start_s, end_s)
        total = conn.execute("SELECT count(*)" + where, args).fetchone()[0]
        rows = tuple((r["material_key"], _change(r)) for r in conn.execute(
            "SELECT c.*, s.observed_at, s.same_source_path, pv.imported_at AS before_at, pv.source_path AS before_path,"
            " av.source_path AS after_path" + where + " ORDER BY s.observed_at DESC, s.id DESC, c.sheet_name,"
            " c.material_key, c.id LIMIT ?", (*args, limit)))
        first = conn.execute("SELECT min(s.observed_at) FROM inventory_snapshots s JOIN source_versions v"
                             " ON v.id = s.source_version_id WHERE v.source_path = ?", (stock["source_path"],)).fetchone()[0]
        retained = conn.execute("SELECT value FROM schema_info WHERE key = 'history_retained_from'").fetchone()
    notes = []
    if first is None or first > start_s:
        notes.append(f"History of this Storage file starts at {first or '—'} UTC, inside the {days}-day window: "
                     "earlier changes are unknown.")
    if retained and start_s < retained[0]:
        notes.append(f"Local History maintenance removed records before {retained[0]} UTC; the window is partly covered.")
    if total > len(rows):
        notes.append(f"Only the newest {len(rows)} of {total} observed changes were loaded; use the filters.")
    return ChangesView(stock["source_path"], days, start_s, end_s, rows, total, first,
                       retained[0] if retained else None, tuple(notes))


# ---------------------------------------------------------------------- bounded background runner (no Tk)
class AlertRunner:
    """At most one evaluation runs; at most one request waits (a newer request replaces it). Every result is
    delivered as (generation, result, error) with the gate generation of its request, so the UI can tell a current
    result from an obsolete one. Nothing is delivered after close()."""

    def __init__(self, service: AlertService, gate: SessionGate | None = None):
        self.service = service
        self.gate = gate or SessionGate()
        self.events = queue.Queue()
        self._lock = threading.Lock()
        self.running = False
        self.pending = None
        self.closed = False
        self.threads_started = 0

    def request(self, trigger: str, authorization: Authorization | None) -> str:
        generation = authorization.generation if authorization is not None else self.gate.generation
        with self._lock:
            if self.closed:
                return "closed"
            if self.running:
                self.pending = (trigger, authorization, generation)
                return "queued"
            self.running = True
            self.threads_started += 1
        threading.Thread(target=self._work, args=(trigger, authorization, generation), daemon=True,
                         name="m32c-alerts").start()
        return "started"

    def close(self):
        with self._lock:
            self.closed = True
            self.pending = None

    def _work(self, trigger, authorization, generation):
        stale_retry = True
        while True:
            try:
                result, error = self.service.run(trigger, authorization,
                                                 lambda: self.gate.publishing(generation)), None
            except AlertStale as exc:
                result, error = None, exc
                with self._lock:  # records moved on: evaluate once more (its verification is re-checked from scratch)
                    if stale_retry and self.pending is None and not self.closed:
                        self.pending = (trigger, authorization, generation)
                stale_retry = False
            except Exception as exc:
                result, error = None, exc
            with self._lock:
                if not self.closed:
                    self.events.put((generation, result, error))
                if self.closed or self.pending is None:
                    self.running = False
                    return
                trigger, authorization, generation = self.pending
                self.pending = None
