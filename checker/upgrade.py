"""Explicit local database upgrade to schema 3 (M3.2C thresholds, stock alerts per source file). Never automatic.

From schema 1: add the threshold columns and alert tables (UPGRADE_TO_2) and the alert source scope (UPGRADE_TO_3).
From schema 2 (an M3.2C development database): add the alert source scope, and attribute every existing alert and
evaluation to its Storage / BOM file using the version headers it already references, rewriting each alert identity
to include that file. Nothing is reset or deleted; an alert whose file cannot be attributed keeps an empty scope and is
never resolved by any later evaluation.

preview() reads only. apply() needs the matching preview (the user's explicit consent in the UI) and then:
1. re-checks the database against the preview inside a read transaction;
2. writes a recovery backup in the database folder's `backups` subfolder, published only after its integrity and
   logical content equal the preview (the M3.2B procedure);
3. under the write lock re-checks once more, then applies all changes, sets user_version and records the upgrade in
   schema_info, in ONE transaction. Existing inventory rows are not rewritten.
Any failure rolls back completely; the database stays at its previous schema and usable. Excel is never touched.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from .inventory_db import (SCHEMA_VERSION, UPGRADE_TO_2, UPGRADE_TO_3, source_identity, stamp, utc_now)
from .alerts import NOT_IN_MASTER, alert_key
from .queries import open_readonly
from .retention import _digest, _identity, _validate

UPGRADABLE = (1, 2)


class UpgradeError(ValueError):
    """The upgrade was refused or rolled back; the database is unchanged."""


@dataclass(frozen=True)
class UpgradePlan:
    database: str
    identity: tuple
    from_version: int
    digest: str
    counts: tuple[tuple[str, int], ...]

    def describe(self):
        change = ("adds storage for the MIN QTY / MIIN QTY threshold of each Storage row, and tables for stock-alert "
                  "evaluations and de-duplicated alerts, kept separately per Storage / BOM file"
                  if self.from_version == 1 else
                  "keeps stock alerts separately per Storage / BOM file: existing alerts are attributed to the files "
                  "they came from, and an alert is never resolved by an evaluation of a different file")
        return (f"Local database upgrade — preview only\n{self.database}\n\n"
                f"Schema {self.from_version} → {SCHEMA_VERSION}: {change}.\n" +
                "\n".join(f"{name}: {count}" for name, count in self.counts) +
                "\n\nExisting inventory rows are kept unchanged and nothing is deleted." +
                ("\nStorage versions imported before this upgrade have no thresholds until the current Storage file "
                 "is read again (Refresh Excel); they are shown as 'threshold not captured', never as blank or 0."
                 if self.from_version == 1 else "") +
                "\nA verified recovery backup is created first in the database folder's backups subfolder."
                "\nRecovery backups are not deleted automatically. Older development builds of this program cannot "
                "open an upgraded database; keep the backup if you need to go back."
                "\nExcel files are not changed.")


def _plan(conn, path) -> UpgradePlan:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        raise UpgradeError("The database is already upgraded; nothing to do.")
    if version not in UPGRADABLE:
        raise UpgradeError(f"Unsupported database schema {version}; upgrade refused.")
    _validate(conn)  # the table set of that schema only, no triggers, quick_check and foreign keys clean
    count = lambda table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    counts = [("Source versions", count("source_versions")), ("Storage rows", count("stock_records")),
              ("Inventory snapshots", count("inventory_snapshots"))]
    if version == 2:
        counts += [("Stock alerts to attribute", count("stock_alerts")),
                   ("Alert evaluations to attribute", count("alert_evaluations"))]
    return UpgradePlan(str(path), _identity(path), version, _digest(conn), tuple(counts))


def preview(database) -> UpgradePlan:
    path = Path(database).resolve()
    conn = None
    try:
        identity = _identity(path)
        conn = open_readonly(path)
        conn.execute("PRAGMA busy_timeout = 1500")
        conn.execute("BEGIN")
        plan = _plan(conn, path)
        if plan.identity != identity:
            raise UpgradeError("Database replaced during preview; nothing was changed.")
        return plan
    except UpgradeError:
        raise
    except Exception as exc:  # unreadable, missing, foreign or damaged: refused, never created
        raise UpgradeError(f"Cannot prepare the database upgrade: {exc}") from exc
    finally:
        if conn is not None:
            conn.close()


def _checkpoint(stage):
    """No-op fault-injection boundaries: 'backup' (backup published), 'before_commit'."""


def _attribute_alerts(writer):
    """Schema 2 → 3: give every existing alert and evaluation the files of the versions it references."""
    path_of = {r[0]: source_identity(r[1]) for r in writer.execute("SELECT id, source_path FROM source_versions")}
    for row in writer.execute("SELECT id, stock_version_id, bom_version_id FROM alert_evaluations").fetchall():
        writer.execute("UPDATE alert_evaluations SET storage_source = ?, bom_source = ? WHERE id = ?",
                       (path_of.get(row[1]), path_of.get(row[2]), row[0]))
    for row in writer.execute("SELECT id, alert_key, alert_type, stock_version_id, bom_version_id FROM stock_alerts"
                              ).fetchall():
        old = json.loads(row[1])  # [type, subtype, sheet, material_key, row]
        storage = path_of.get(row[3])
        bom = path_of.get(row[4]) if row[2] == NOT_IN_MASTER else None
        writer.execute("UPDATE stock_alerts SET storage_source = ?, bom_source = ?, alert_key = ? WHERE id = ?",
                       (storage, bom, alert_key(old[0], old[1], storage, bom, old[2], old[3], old[4]), row[0]))


def apply(plan, cancelled=None) -> str:
    """Returns the recovery backup path. Raises UpgradeError; on any failure the database is unchanged."""
    if not isinstance(plan, UpgradePlan):
        raise UpgradeError("No upgrade preview; preview again.")
    path = Path(plan.database)
    source = destination = writer = None
    backup = None
    try:
        _cancel(cancelled)
        source = open_readonly(path)
        source.execute("PRAGMA busy_timeout = 1500")
        source.execute("BEGIN")
        if _plan(source, path) != plan:
            raise UpgradeError("Database changed after preview. Nothing changed; preview again.")
        directory = path.parent / "backups"
        directory.mkdir(exist_ok=True)
        if directory.resolve().parent != path.parent:
            raise UpgradeError("Backup directory resolves outside the database folder; upgrade refused.")
        final_backup = directory / f"inventory_before_upgrade_{uuid.uuid4().hex}.sqlite3"
        backup = Path(str(final_backup) + ".partial")
        os.close(os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        destination = sqlite3.connect(str(backup))
        deadline = time.monotonic() + 30

        def progress(status, remaining, total):
            _cancel(cancelled)
            if time.monotonic() > deadline:
                raise UpgradeError("Backup timed out; upgrade refused.")
        source.backup(destination, pages=256, progress=progress, sleep=0.1)
        if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok" or _digest(destination) != plan.digest:
            raise UpgradeError("Recovery backup integrity failed; upgrade refused.")
        destination.close(); destination = None
        if os.name == "nt":
            os.rename(backup, final_backup)  # never replaces an existing file on Windows
        else:
            os.link(backup, final_backup)
            os.unlink(backup)
        backup = final_backup
        source.close(); source = None
        _checkpoint("backup")
        writer = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=1.5, isolation_level=None)
        writer.row_factory = sqlite3.Row
        writer.execute("PRAGMA foreign_keys = ON")
        writer.execute("BEGIN IMMEDIATE")
        if _plan(writer, path) != plan:
            raise UpgradeError("Database changed while backing up. Nothing changed; preview again.")
        _cancel(cancelled)
        statements = (UPGRADE_TO_2 if plan.from_version == 1 else ()) + UPGRADE_TO_3
        for statement in statements:
            writer.execute(statement)
        if plan.from_version == 2:
            _attribute_alerts(writer)
        writer.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        now = stamp(utc_now())
        writer.executemany("INSERT OR REPLACE INTO schema_info (key, value) VALUES (?, ?)",
                           (("schema_version", str(SCHEMA_VERSION)),
                            (f"upgraded_{plan.from_version}_to_{SCHEMA_VERSION}_at", now),
                            ("upgrade_backup", str(backup))))
        _validate(writer)  # schema-3 tables, integrity and foreign keys before COMMIT
        _checkpoint("before_commit")
        _cancel(cancelled)
        writer.execute("COMMIT")
        return str(backup)
    except Exception as exc:
        rollback = None
        if writer is not None and writer.in_transaction:
            try:
                writer.execute("ROLLBACK")
            except sqlite3.Error as error:
                rollback = error
        detail = f"{exc}\nThe database was not upgraded and remains usable as before."
        if rollback is not None:
            detail += f"\nRollback also reported: {rollback}"
        if backup is not None:
            detail += f"\nBackup file (check integrity before any recovery): {backup}"
        raise UpgradeError(detail) from exc
    finally:
        for conn in (writer, destination, source):
            if conn is not None:
                conn.close()


def _cancel(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise UpgradeError("Upgrade cancelled.")
