"""Manual local SQLite retention: immutable preview, consistent backup and atomic guarded deletion."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from .inventory_db import SCHEMA_VERSION, parse_stamp, stamp, utc_now
from .queries import open_readonly

TABLES = ('schema_info', 'source_versions', 'current_sources', 'sync_runs', 'materials', 'stock_sheets',
          'stock_records', 'bom_products', 'bom_lines', 'inventory_snapshots', 'inventory_changes', 'data_quality_issues')


class RetentionError(ValueError):
    """Maintenance was refused or rolled back; no partial deletion is accepted."""


class RetentionReadError(RetentionError):
    """The database cannot be read safely."""


@dataclass(frozen=True)
class Plan:
    database: str
    identity: tuple
    evaluated_at: str
    snapshot_cutoff: str
    routine_cutoff: str
    failure_cutoff: str
    snapshots: tuple[int, ...]
    payloads: tuple[int, ...]
    runs: tuple[int, ...]
    protected_snapshots: tuple[int, ...]
    counts: tuple[tuple[str, int], ...]
    digest: str

    @property
    def empty(self):
        return not (self.snapshots or self.payloads or self.runs)

    def describe(self):
        return ('Local database maintenance — preview only\n' + self.database +
                f'\n\nEvaluated UTC: {self.evaluated_at}\nInventory: 12 calendar months, before {self.snapshot_cutoff} UTC'
                f'\nRoutine logs: 90 days, before {self.routine_cutoff} UTC'
                f'\nFailure logs: 180 days, before {self.failure_cutoff} UTC\n\n' +
                '\n'.join(f'{name}: {count}' for name, count in self.counts) +
                '\n\nLatest/current snapshots, trend baseline and required predecessors are protected.'
                '\nLatest attempt/success logs remain even when older than their retention limit.'
                '\nSource-version headers, BOM history and material registry remain.'
                '\nA recovery backup will be created in the database folder’s backups subfolder.'
                '\nRecovery backups contain the old history and are not automatically deleted.'
                '\nExcel files are not changed. SQLite file size may not shrink; free pages are reused.')


@dataclass(frozen=True)
class Result:
    plan: Plan
    backup: str | None


def _identity(path):
    info = path.stat()
    return info.st_dev, info.st_ino


def _validate(conn):
    if conn.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
        raise RetentionReadError('Unsupported database schema; cleanup refused.')
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if names != set(TABLES) or conn.execute("SELECT 1 FROM sqlite_master WHERE type='trigger'").fetchone():
        raise RetentionReadError('Unrecognised database tables/triggers; cleanup refused.')
    if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchone():
        raise RetentionReadError('Database integrity check failed; cleanup refused.')


def _digest(conn):
    """Logical snapshot digest also covers WAL content; memory is bounded to one row at a time."""
    digest = hashlib.sha256()
    for row in conn.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name'):
        digest.update(json.dumps(tuple(row), ensure_ascii=True).encode())
    for table in TABLES:
        digest.update(table.encode())
        for row in conn.execute(f'SELECT * FROM {table} ORDER BY 1'):
            digest.update(json.dumps(tuple(row), ensure_ascii=True).encode())
    return digest.hexdigest()


def _groups(ids):
    for offset in range(0, len(ids), 500):
        yield ids[offset:offset+500]


def _delete(conn, table, column, ids):
    for group in _groups(ids):
        conn.execute(f'DELETE FROM {table} WHERE {column} IN ({",".join("?" for _ in group)})', group)


def _plan(conn, path, now):
    _validate(conn)
    if now.tzinfo is None:
        raise RetentionError('An explicit UTC-aware clock is required.')
    now = now.astimezone(timezone.utc)
    previous_year = now.year - 1
    cutoff = stamp(now.replace(year=previous_year, day=min(now.day, calendar.monthrange(previous_year, now.month)[1])))
    routine, failure = stamp(now-timedelta(days=90)), stamp(now-timedelta(days=180))
    snapshots = [dict(r) for r in conn.execute('SELECT * FROM inventory_snapshots ORDER BY id')]
    versions = [dict(r) for r in conn.execute('SELECT * FROM source_versions ORDER BY id')]
    runs = [dict(r) for r in conn.execute('SELECT * FROM sync_runs ORDER BY id')]
    for text in ([s['observed_at'] for s in snapshots] + [v['imported_at'] for v in versions] +
                 [r['finished_at'] for r in runs]):
        if parse_stamp(text) is None:
            raise RetentionReadError('Missing retention timestamp; cleanup refused.')
    floor = conn.execute("SELECT value FROM schema_info WHERE key='history_retained_from'").fetchone()
    if floor and parse_stamp(floor[0]) is None:
        raise RetentionReadError('Invalid history retention timestamp; cleanup refused.')
    current = {r['role']: r['source_version_id'] for r in conn.execute('SELECT * FROM current_sources')}
    keep = {s['id'] for s in snapshots if s['observed_at'] >= cutoff or s['source_version_id'] in current.values()}
    if snapshots:
        keep.add(snapshots[-1]['id'])  # never delete the latest successful snapshot, even with clock skew
    earlier = [s for s in snapshots if s['observed_at'] < cutoff]
    if earlier:
        keep.add(max(earlier, key=lambda s: (s['observed_at'], s['id']))['id'])
    kept = [s for s in snapshots if s['id'] in keep]
    needed_versions = set(current.values()) | {s['source_version_id'] for s in kept}
    needed_versions.update(s['previous_version_id'] for s in kept if s['previous_version_id'] is not None)
    expired_snapshots = tuple(s['id'] for s in snapshots if s['id'] not in keep)
    payloads = tuple(v['id'] for v in versions if v['role'] == 'stock' and v['id'] not in needed_versions
                     and v['imported_at'] < cutoff and any(conn.execute(f'SELECT 1 FROM {t} WHERE source_version_id=? LIMIT 1',
                         (v['id'],)).fetchone() for t in ('stock_sheets', 'stock_records', 'data_quality_issues')))
    protected_runs = set()
    for role in ('stock', 'bom'):
        attempts = [r for r in runs if r['role'] == role]
        successes = [r for r in attempts if r['outcome'] in ('IMPORTED', 'UNCHANGED')]
        for group in (attempts, successes, [r for r in successes if r['source_version_id'] == current.get(role)]):
            if group:
                protected_runs.add(group[-1]['id'])
    expired_runs = tuple(r['id'] for r in runs if r['id'] not in protected_runs and
                         r['finished_at'] < (routine if r['outcome'] in ('IMPORTED', 'UNCHANGED') else failure))
    def count(table, column, ids):
        # Bound parameters and avoid scanning inventory_changes once per expired snapshot.
        return sum(conn.execute(f'SELECT count(*) FROM {table} WHERE {column} IN '
                   f'({",".join("?" for _ in group)})', group).fetchone()[0] for group in _groups(ids))
    counts = (('Expired inventory snapshots', len(expired_snapshots)), ('Expired Storage payloads', len(payloads)),
              ('Stock rows', count('stock_records', 'source_version_id', payloads)),
              ('Stock sheets', count('stock_sheets', 'source_version_id', payloads)),
              ('Quality issues', count('data_quality_issues', 'source_version_id', payloads)),
              ('Observed changes', count('inventory_changes', 'snapshot_id', expired_snapshots)),
              ('Expired logs', len(expired_runs)))
    return Plan(str(path), _identity(path), stamp(now), cutoff, routine, failure, expired_snapshots, payloads,
                expired_runs, tuple(sorted(keep)), counts, _digest(conn))


class RetentionService:
    def __init__(self, database):
        self.path = Path(database).resolve()

    def preview(self, now=None):
        conn = None
        try:
            identity = _identity(self.path)
            conn = open_readonly(self.path)
            conn.execute('PRAGMA busy_timeout=1500')
            conn.execute('BEGIN')
            plan = _plan(conn, self.path, now or utc_now())
            if plan.identity != identity:
                raise RetentionError('Database replaced during preview; nothing was deleted.')
            return plan
        except Exception as exc:
            if isinstance(exc, RetentionError):
                raise
            raise RetentionReadError(f'Cannot preview local database: {exc}') from exc
        finally:
            if conn is not None:
                conn.close()

    def _checkpoint(self, stage, conn):
        """No-op fault-injection boundaries: backup, snapshots, payloads, logs, before_commit."""

    def apply(self, plan, cancelled=None):
        """Never creates a missing source DB. Backup before mutation; replan under write lock; atomic delete."""
        if not isinstance(plan, Plan) or plan.database != str(self.path):
            raise RetentionError('No matching cleanup preview; preview again.')
        backup = None
        phase = 'read'
        source = destination = writer = None
        try:
            self._cancel(cancelled)
            source = open_readonly(self.path)
            source.execute('PRAGMA busy_timeout=1500')
            source.execute('BEGIN')
            now = parse_stamp(plan.evaluated_at)
            if _plan(source, self.path, now) != plan:
                raise RetentionError('Database changed after preview. Nothing deleted; preview again.')
            if plan.empty:
                return Result(plan, None)
            phase = 'backup'
            directory = self.path.parent / 'backups'
            directory.mkdir(exist_ok=True)
            if directory.resolve().parent != self.path.parent:
                raise RetentionError('Backup directory resolves outside the database folder; cleanup refused.')
            final_backup = directory / f'inventory_before_cleanup_{uuid.uuid4().hex}.sqlite3'
            backup = Path(str(final_backup) + '.partial')
            descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            destination = sqlite3.connect(str(backup))
            deadline = time.monotonic() + 30
            def progress(status, remaining, total):
                self._cancel(cancelled)
                if time.monotonic() > deadline:
                    raise RetentionError('Backup timed out; cleanup refused.')
            source.backup(destination, pages=256, progress=progress, sleep=0.1)
            if destination.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or _digest(destination) != plan.digest:
                raise RetentionError('Recovery backup integrity failed; cleanup refused.')
            destination.close(); destination = None
            if os.name == 'nt':
                os.rename(backup, final_backup)  # No-overwrite publication on the supported Windows target.
            else:
                os.link(backup, final_backup)
                os.unlink(backup)
            backup = final_backup
            source.close(); source = None
            self._checkpoint('backup', None)
            phase = 'read'
            writer = sqlite3.connect(self.path.as_uri()+'?mode=rw', uri=True, timeout=1.5, isolation_level=None)
            writer.row_factory = sqlite3.Row
            writer.execute('PRAGMA foreign_keys=ON')
            writer.execute('BEGIN IMMEDIATE')
            if _plan(writer, self.path, now) != plan:
                raise RetentionError('Database changed while backing up. Nothing deleted; preview again.')
            phase = 'write'
            self._cancel(cancelled)
            _delete(writer, 'inventory_changes', 'snapshot_id', plan.snapshots)
            _delete(writer, 'inventory_snapshots', 'id', plan.snapshots)
            self._checkpoint('snapshots', writer)
            for table in ('stock_records', 'stock_sheets', 'data_quality_issues'):
                _delete(writer, table, 'source_version_id', plan.payloads)
            self._checkpoint('payloads', writer)
            _delete(writer, 'sync_runs', 'id', plan.runs)
            self._checkpoint('logs', writer)
            if plan.snapshots:
                old = writer.execute("SELECT value FROM schema_info WHERE key='history_retained_from'").fetchone()
                floor = max(plan.snapshot_cutoff, old[0]) if old else plan.snapshot_cutoff
                writer.execute("INSERT OR REPLACE INTO schema_info VALUES ('history_retained_from',?)", (floor,))
            writer.execute("INSERT OR REPLACE INTO schema_info VALUES ('last_cleanup_at',?)", (stamp(utc_now()),))
            writer.execute("INSERT OR REPLACE INTO schema_info VALUES ('last_cleanup_backup',?)", (str(backup),))
            _validate(writer)
            self._checkpoint('before_commit', writer)
            self._cancel(cancelled)
            writer.execute('COMMIT')
            return Result(plan, str(backup))
        except Exception as exc:
            rollback_error = None
            if writer is not None and writer.in_transaction:
                try:
                    writer.execute('ROLLBACK')
                except sqlite3.Error as error:
                    rollback_error = error  # Connection close below also rolls back an uncommitted transaction.
            detail = f'{exc}\nCleanup did not complete; reload the preview before retrying.'
            if rollback_error is not None:
                detail += f'\nRollback also reported: {rollback_error}'
            if backup is not None:
                detail += f'\nBackup file (check integrity before recovery): {backup}'
            unavailable = (phase == 'read' and isinstance(exc, (OSError, sqlite3.Error)) and
                           getattr(exc, 'sqlite_errorcode', None) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED))
            error_type = RetentionReadError if isinstance(exc, RetentionReadError) or unavailable else RetentionError
            raise error_type(detail) from exc
        finally:
            for conn in (writer, destination, source):
                if conn is not None:
                    conn.close()

    @staticmethod
    def _cancel(cancelled):
        if cancelled is not None and cancelled.is_set():
            raise RetentionError('Maintenance cancelled.')
