"""SQLite schema and value encoding for the local, read-only mirror of the Storage and BOM workbooks.

The Excel files on Google Drive stay the source of truth. Every imported workbook version is kept as an immutable
set of rows; `current_sources` points at the published version of each role, so a failed import never touches it.
Raw cell values are stored losslessly (kind + text) so the original identifiers and quantities can be rebuilt exactly.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
import sqlite3
from typing import Any

SCHEMA_VERSION = 3               # created for new databases
LEGACY_SCHEMA_VERSION = 1        # usable as before; upgraded only by the explicit, backed-up upgrade
# 2 = thresholds + first alert tables (M3.2C development); 3 = alert identity/provenance per source file.
# Every supported version opens unchanged; stock alerts need 3 (checker.upgrade: 1 → 3 or 2 → 3, explicit).
SUPPORTED_SCHEMA_VERSIONS = (LEGACY_SCHEMA_VERSION, 2, SCHEMA_VERSION)
ALERT_SCHEMA_VERSION = 3


class DatabaseError(Exception):
    """The inventory database cannot be opened or used safely."""


SCHEMA = """
CREATE TABLE schema_info (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per imported workbook version. Rows are never updated except superseded_at.
CREATE TABLE source_versions (
    id                 INTEGER PRIMARY KEY,
    role               TEXT NOT NULL CHECK (role IN ('stock', 'bom')),
    source_path        TEXT NOT NULL,          -- resolved path as read
    file_name          TEXT NOT NULL,
    size_bytes         INTEGER NOT NULL,
    mtime_ns           INTEGER NOT NULL,
    source_modified_at TEXT NOT NULL,          -- UTC, from the file's modified time
    content_signature  TEXT NOT NULL,          -- SHA-256 over the ZIP part CRCs/sizes (xl/, without media)
    file_sha256        TEXT NOT NULL,          -- SHA-256 of the whole file at import
    imported_at        TEXT NOT NULL,          -- UTC
    superseded_at      TEXT,                   -- UTC, when a newer version was published
    parser_version     TEXT NOT NULL,
    notes              TEXT NOT NULL,          -- JSON list of reader notes (skipped sheets, unusable codes)
    sheet_count        INTEGER NOT NULL,
    record_count       INTEGER NOT NULL
);
CREATE INDEX source_versions_role ON source_versions (role, id);

-- The published version per role. Changed only inside the transaction that completes an import.
CREATE TABLE current_sources (
    role              TEXT PRIMARY KEY CHECK (role IN ('stock', 'bom')),
    source_version_id INTEGER NOT NULL REFERENCES source_versions (id),
    published_at      TEXT NOT NULL
);

-- Every check of a source file, successful or not ("Last Checked").
CREATE TABLE sync_runs (
    id                INTEGER PRIMARY KEY,
    role              TEXT NOT NULL CHECK (role IN ('stock', 'bom')),
    trigger           TEXT NOT NULL,           -- startup / manual / selected / check / reload
    source_path       TEXT NOT NULL,           -- path as selected by the user
    started_at        TEXT NOT NULL,
    finished_at       TEXT NOT NULL,
    outcome           TEXT NOT NULL CHECK (outcome IN ('IMPORTED', 'UNCHANGED', 'UNAVAILABLE', 'FAILED')),
    source_version_id INTEGER REFERENCES source_versions (id),  -- imported or verified version
    observed_size     INTEGER,
    observed_mtime_ns INTEGER,
    owner_lock_files  TEXT,                    -- JSON list of ~$ files seen beside the workbook
    error_type        TEXT,
    error_message     TEXT
);
CREATE INDEX sync_runs_role ON sync_runs (role, id);

-- Identity registry of normalized text Material IDs ever seen. Holds no quantities and merges no records.
CREATE TABLE materials (
    material_key         TEXT PRIMARY KEY,
    first_seen_at        TEXT NOT NULL,
    last_seen_at         TEXT NOT NULL,
    stock_last_version_id INTEGER REFERENCES source_versions (id),
    bom_last_version_id   INTEGER REFERENCES source_versions (id)
);

CREATE TABLE stock_sheets (
    id                INTEGER PRIMARY KEY,
    source_version_id INTEGER NOT NULL REFERENCES source_versions (id),
    sheet_index       INTEGER NOT NULL,        -- order of the recognised stock sheets in the workbook
    sheet_name        TEXT NOT NULL,           -- original name, never trimmed
    header_row        INTEGER NOT NULL,
    UNIQUE (source_version_id, sheet_index)
);

-- One row per Storage material row exactly as read. Duplicates are separate rows.
CREATE TABLE stock_records (
    id                INTEGER PRIMARY KEY,
    source_version_id INTEGER NOT NULL REFERENCES source_versions (id),
    stock_sheet_id    INTEGER NOT NULL REFERENCES stock_sheets (id),
    ordinal           INTEGER NOT NULL,        -- order within the sheet
    row_no            INTEGER NOT NULL,
    code_kind         TEXT, code_text TEXT, code_cell_type TEXT NOT NULL,
    material_key      TEXT,                    -- matching key (normalized text); NULL if not a usable text code
    numeric_code      TEXT,                    -- digits of a code held in a numeric cell; never a key
    description_kind  TEXT, description_text TEXT,
    qty_kind          TEXT, qty_text TEXT, qty_cell_type TEXT NOT NULL,
    qty_status        TEXT NOT NULL CHECK (qty_status IN ('VALID', 'BLANK', 'INVALID')),
    qty_value         TEXT,                    -- exact decimal, only when qty_status = 'VALID'
    rack_kind         TEXT, rack_text TEXT,
    level_kind        TEXT, level_text TEXT,
    section           TEXT NOT NULL
);
CREATE INDEX stock_records_key ON stock_records (source_version_id, material_key);
CREATE INDEX stock_records_sheet ON stock_records (stock_sheet_id, ordinal);

CREATE TABLE bom_products (
    id                INTEGER PRIMARY KEY,
    source_version_id INTEGER NOT NULL REFERENCES source_versions (id),
    sheet_index       INTEGER NOT NULL,        -- order of the product sheets in the workbook
    sheet_name        TEXT NOT NULL,           -- original name, never trimmed
    product_id        TEXT NOT NULL,           -- Product ID shown to the user
    header_row        INTEGER NOT NULL,
    UNIQUE (source_version_id, sheet_index)
);

CREATE TABLE bom_lines (
    id                INTEGER PRIMARY KEY,
    source_version_id INTEGER NOT NULL REFERENCES source_versions (id),
    bom_product_id    INTEGER NOT NULL REFERENCES bom_products (id),
    ordinal           INTEGER NOT NULL,
    row_no            INTEGER NOT NULL,
    code_kind         TEXT, code_text TEXT, code_cell_type TEXT NOT NULL,
    material_key      TEXT,
    numeric_code      TEXT,
    description_kind  TEXT, description_text TEXT,
    qty_kind          TEXT, qty_text TEXT, qty_cell_type TEXT NOT NULL,
    qty_status        TEXT NOT NULL CHECK (qty_status IN ('VALID', 'BLANK', 'INVALID')),
    qty_value         TEXT,                    -- exact decimal, only when > 0 and usable
    column_j_kind     TEXT, column_j_text TEXT,
    column_k_kind     TEXT, column_k_text TEXT,
    section           TEXT NOT NULL            -- assembly section label, unconfirmed configuration
);
CREATE INDEX bom_lines_product ON bom_lines (bom_product_id, ordinal);
CREATE INDEX bom_lines_key ON bom_lines (source_version_id, material_key);

-- Storage only: one snapshot per imported Storage version (never for an unchanged file).
CREATE TABLE inventory_snapshots (
    id                         INTEGER PRIMARY KEY,
    source_version_id          INTEGER NOT NULL UNIQUE REFERENCES source_versions (id),
    previous_version_id        INTEGER REFERENCES source_versions (id),  -- NULL: first (baseline) snapshot
    same_source_path           INTEGER,                                  -- NULL for a baseline
    observed_at                TEXT NOT NULL,                            -- UTC, when this state was synchronized
    source_modified_at         TEXT NOT NULL,
    record_count               INTEGER NOT NULL,
    valid_count                INTEGER NOT NULL,
    blank_count                INTEGER NOT NULL,
    invalid_count              INTEGER NOT NULL,
    unkeyed_count              INTEGER NOT NULL,   -- rows whose Material ID is not a usable text code
    duplicate_key_count        INTEGER NOT NULL,   -- keys with more than one row in the same sheet
    quantity_changed_count     INTEGER NOT NULL,
    added_count                INTEGER NOT NULL,
    removed_count              INTEGER NOT NULL,
    validity_changed_count     INTEGER NOT NULL,
    duplicate_changed_count    INTEGER NOT NULL,
    has_differences            INTEGER             -- NULL baseline; 0 new version without observed differences
);

-- Observed differences between consecutive published Storage versions. Not confirmed consumption.
CREATE TABLE inventory_changes (
    id                    INTEGER PRIMARY KEY,
    snapshot_id           INTEGER NOT NULL REFERENCES inventory_snapshots (id),
    sheet_name            TEXT NOT NULL,
    material_key          TEXT NOT NULL,
    change_type           TEXT NOT NULL CHECK (change_type IN
                          ('QUANTITY_CHANGED', 'ADDED', 'REMOVED', 'VALIDITY_CHANGED', 'DUPLICATE_CHANGED')),
    previous_status       TEXT,      -- VALID / BLANK / INVALID / DUPLICATE; NULL when absent
    previous_value        TEXT,      -- exact decimal when previous_status = VALID
    previous_raw          TEXT,      -- JSON list of [kind, text] raw values, one per row
    new_status            TEXT,
    new_value             TEXT,
    new_raw               TEXT,
    observed_net_change   TEXT       -- new - previous; only for QUANTITY_CHANGED
);
CREATE INDEX inventory_changes_key ON inventory_changes (material_key, snapshot_id);

CREATE TABLE data_quality_issues (
    id                INTEGER PRIMARY KEY,
    source_version_id INTEGER NOT NULL REFERENCES source_versions (id),
    role              TEXT NOT NULL CHECK (role IN ('stock', 'bom')),
    sheet_name        TEXT NOT NULL,
    row_no            INTEGER,
    issue_type        TEXT NOT NULL,
    material_key      TEXT,
    raw_value         TEXT,
    detail            TEXT NOT NULL
);
CREATE INDEX data_quality_version ON data_quality_issues (source_version_id, issue_type);
"""

# Schema 2 (M3.2C) only adds. New databases apply SCHEMA then these statements; an existing schema-1 database receives
# the same statements only through checker.upgrade (preview, explicit consent, verified backup, one transaction), so
# both paths end with identical schema SQL. Existing rows are not rewritten by the upgrade.
UPGRADE_TO_2 = (
    # Threshold column of each Storage Sheet. NULL state = not captured (a version imported under schema 1).
    "ALTER TABLE stock_sheets ADD COLUMN threshold_state TEXT",       # FOUND / NOT_FOUND / AMBIGUOUS
    "ALTER TABLE stock_sheets ADD COLUMN threshold_column TEXT",      # column letter of the single candidate
    "ALTER TABLE stock_sheets ADD COLUMN threshold_header TEXT",      # original header text, spelling unchanged
    "ALTER TABLE stock_sheets ADD COLUMN threshold_candidates TEXT",  # JSON [[column, header], ...] when AMBIGUOUS
    # Raw minimum-stock candidate of each Storage row, lossless like the other raw values.
    "ALTER TABLE stock_records ADD COLUMN threshold_kind TEXT",
    "ALTER TABLE stock_records ADD COLUMN threshold_text TEXT",
    "ALTER TABLE stock_records ADD COLUMN threshold_cell_type TEXT",
    # One row per alert evaluation. Bounded: only the most recent evaluations are kept (checker.alerts).
    """CREATE TABLE alert_evaluations (
    id                INTEGER PRIMARY KEY,
    trigger           TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    finished_at       TEXT NOT NULL,
    outcome           TEXT NOT NULL CHECK (outcome IN ('COMPLETED', 'UNVERIFIED', 'FAILED')),
    stock_version_id  INTEGER REFERENCES source_versions (id),
    bom_version_id    INTEGER REFERENCES source_versions (id),
    sources_verified  INTEGER NOT NULL,      -- 1 only when both roles were Local File Checked for this evaluation
    sheet_scope       TEXT,                  -- JSON list of the Storage Sheets evaluated
    summary           TEXT,                  -- JSON counts and notes
    error_message     TEXT
)""",
    # One row per alert identity (de-duplication). Never merges materials, Sheets, products or quantities.
    """CREATE TABLE stock_alerts (
    id                      INTEGER PRIMARY KEY,
    alert_key               TEXT NOT NULL UNIQUE,  -- JSON identity: type, subtype, Storage Sheet, key or row
    alert_type              TEXT NOT NULL CHECK (alert_type IN ('OUT_OF_STOCK', 'LOW_STOCK',
                            'BOM_MATERIAL_NOT_IN_STOCK_MASTER', 'DATA_ISSUE', 'THRESHOLD_NOT_CONFIGURED')),
    subtype                 TEXT NOT NULL,
    stock_sheet             TEXT NOT NULL,
    material_key            TEXT,
    status                  TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RESOLVED')),
    first_seen_at           TEXT NOT NULL,
    last_seen_at            TEXT NOT NULL,
    resolved_at             TEXT,
    first_evaluation_id     INTEGER NOT NULL,
    last_evaluation_id      INTEGER NOT NULL,
    resolved_evaluation_id  INTEGER,
    stock_version_id        INTEGER REFERENCES source_versions (id),
    bom_version_id          INTEGER REFERENCES source_versions (id),
    detail                  TEXT NOT NULL     -- JSON: raw values, rows, occurrences, notes of the last observation
)""",
    "CREATE INDEX stock_alerts_status ON stock_alerts (status, alert_type)",
)
# Schema 3 (M3.2C remediation) only adds: the source scope of every alert and evaluation, so alerts of different
# Storage/BOM files are never one alert and one file's evaluation can never resolve another file's alert. A schema-2
# database gets these columns through checker.upgrade, which also attributes its existing alerts to their files
# (from the recorded version headers) in the same transaction. Nothing is reset or deleted.
UPGRADE_TO_3 = (
    "ALTER TABLE alert_evaluations ADD COLUMN storage_source TEXT",  # normalised Storage file identity
    "ALTER TABLE alert_evaluations ADD COLUMN bom_source TEXT",      # normalised BOM file identity
    "ALTER TABLE stock_alerts ADD COLUMN storage_source TEXT",       # part of the alert identity
    "ALTER TABLE stock_alerts ADD COLUMN bom_source TEXT",           # part of the identity of BOM-coverage alerts
    "CREATE INDEX stock_alerts_scope ON stock_alerts (storage_source, status)",
)
TABLES_1 = ('schema_info', 'source_versions', 'current_sources', 'sync_runs', 'materials', 'stock_sheets',
            'stock_records', 'bom_products', 'bom_lines', 'inventory_snapshots', 'inventory_changes', 'data_quality_issues')
TABLES_2 = TABLES_1 + ('alert_evaluations', 'stock_alerts')


def tables_for(version: int) -> tuple[str, ...]:
    return {1: TABLES_1, 2: TABLES_2, 3: TABLES_2}[version]


def source_identity(path: str | None) -> str | None:
    """Normalised identity of a source file (letter case and separators as Windows compares them)."""
    if not path:
        return None
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(moment: datetime) -> str:
    """UTC text that sorts correctly and works with SQLite date functions: YYYY-MM-DD HH:MM:SS.mmm."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%d %H:%M:%S.") + f"{moment.microsecond // 1000:03d}"


def parse_stamp(text: str | None) -> datetime | None:
    return None if not text else datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)


def encode(value: Any) -> tuple[str | None, str | None]:
    """A raw cell value as (kind, text); decode() returns an equal value of the same Python type."""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return "bool", "1" if value else "0"
    if isinstance(value, int):
        return "int", str(value)
    if isinstance(value, float):
        return "float", repr(value)
    if isinstance(value, Decimal):
        return "decimal", str(value)
    if isinstance(value, str):
        return "str", value
    if isinstance(value, datetime):
        return "datetime", value.isoformat()
    if isinstance(value, date):
        return "date", value.isoformat()
    if isinstance(value, time):
        return "time", value.isoformat()
    if isinstance(value, timedelta):
        return "timedelta", f"{value.days}:{value.seconds}:{value.microseconds}"
    return "repr", repr(value)  # not produced by openpyxl; kept for evidence only


def decode(kind: str | None, text: str | None) -> Any:
    if kind is None:
        return None
    if kind == "bool":
        return text == "1"
    if kind == "int":
        return int(text)
    if kind == "float":
        return float(text)
    if kind == "decimal":
        return Decimal(text)
    if kind == "str":
        return text
    if kind == "datetime":
        return datetime.fromisoformat(text)
    if kind == "date":
        return date.fromisoformat(text)
    if kind == "time":
        return time.fromisoformat(text)
    if kind == "timedelta":
        days, seconds, micro = (int(x) for x in text.split(":"))
        return timedelta(days=days, seconds=seconds, microseconds=micro)
    return text


def connect(path: str | Path) -> sqlite3.Connection:
    """A connection in autocommit mode; callers open explicit transactions (BEGIN IMMEDIATE ... COMMIT)."""
    connection = sqlite3.connect(str(path), timeout=15, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


def schema_version(conn) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def initialise(path: str | Path, app_version: str = "") -> None:
    """Create the schema on first use; accept the current and the legacy schema unchanged (a schema-1 database is
    never migrated here: see checker.upgrade); refuse a database from a newer release or a foreign file."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = connect(path)
    except (OSError, sqlite3.Error) as exc:
        raise DatabaseError(f"无法打开本地数据库 {path}：{exc}") from exc
    try:
        version = schema_version(connection)
        if version in SUPPORTED_SCHEMA_VERSIONS:
            return
        if version > SCHEMA_VERSION:
            raise DatabaseError(f"本地数据库 {path} 由更新版本的程序创建（schema {version}），本版本不会修改它。")
        if connection.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]:
            raise DatabaseError(f"{path} 不是本程序的数据库（无版本号但含有数据），不会修改它。")
        try:
            # One transaction: the schema, its metadata and the version number appear together or not at all.
            upgrade = "".join(statement + ";\n" for statement in UPGRADE_TO_2 + UPGRADE_TO_3)
            connection.executescript(f"BEGIN IMMEDIATE;\n{SCHEMA}\n{upgrade}PRAGMA user_version = {SCHEMA_VERSION};")
            connection.executemany("INSERT INTO schema_info (key, value) VALUES (?, ?)",
                                   (("schema_version", str(SCHEMA_VERSION)), ("created_at", stamp(utc_now())),
                                    ("created_by", app_version or "unknown")))
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
    except sqlite3.Error as exc:
        raise DatabaseError(f"本地数据库 {path} 无法使用：{exc}") from exc
    finally:
        connection.close()
