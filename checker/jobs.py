"""M3.2E unattended daily run. Fresh Excel verification only; no UI, cache consent or schema upgrade."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

from . import alerts, daily
from .appdata import Settings
from .history import read_view
from .inventory_db import ALERT_SCHEMA_VERSION, schema_version, stamp, utc_now
from .sync import InventorySync

SUCCESS, CONFIG_ERROR, SOURCE_ERROR, DATABASE_ERROR, SAVE_ERROR, ALREADY_RUNNING = 0, 2, 3, 4, 5, 6


class JobBusy(Exception):
    pass


@dataclass(frozen=True)
class Outcome:
    run_id: str
    code: int
    reason: str
    attempts: int
    finished_utc: str
    report_folder: str | None = None
    report_id: str | None = None
    cloud: str = "Cloud Not Verified"
    attempt_errors: tuple[str, ...] = ()


@contextmanager
def run_lock(data_dir):
    """OS-released, per-data-directory process lock. A crash cannot leave a permanently locked sentinel."""
    path = Path(data_dir) / 'daily-run.lock'
    stream = path.open('a+b')
    locked = False
    try:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise JobBusy('Another daily run owns this data folder; nothing was synchronised or published.') from exc
        locked = True
        yield
    finally:
        try:
            if locked:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


def _record(data_dir, outcome):
    """Bound only this feature's own run receipts; never touches inventory/sync/alert history."""
    path = Path(data_dir) / 'daily-runs.json'
    previous = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    if not isinstance(previous, list) or any(not isinstance(row, dict) for row in previous):
        raise ValueError('Invalid daily run log; existing log preserved.')
    rows = previous + [asdict(outcome)]
    # Keep latest 200 and the last successful receipt, even after a long failure sequence.
    kept = rows[-200:]
    success = next((r for r in reversed(rows) if r.get('code') == SUCCESS), None)
    if success is not None and success not in kept:
        kept.insert(0, success)
    descriptor, temporary = tempfile.mkstemp(prefix='.daily-runs-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(kept, stream, ensure_ascii=False, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(data_dir, output_dir, *, attempts=1, retry_delay=5, clock=utc_now, sleep=time.sleep):
    """Each attempt verifies BOTH files itself, evaluates, generates today's report, then uses guarded daily.save.

    A failed source or unverified evaluation never generates a cached report. Existing schema 3 is required;
    neither a missing database nor an older schema is created/upgraded here. No Tk functions are called.
    """
    data_dir, output_dir = Path(data_dir).resolve(), Path(output_dir).resolve()
    run_id = uuid.uuid4().hex
    def outcome(code, reason, count=0, saved=None, report_id=None):
        return Outcome(run_id, code, reason, count, stamp(clock()), str(saved) if saved else None, report_id)
    if type(attempts) is not int or not 1 <= attempts <= 3 or not 0 <= retry_delay <= 30:
        return outcome(CONFIG_ERROR, 'Attempts must be 1–3 and retry delay 0–30 seconds.')
    if not data_dir.is_dir() or not output_dir.is_dir():
        return outcome(CONFIG_ERROR, 'Existing application-data and output folders are required; open the GUI first.')
    try:
        with run_lock(data_dir):
            result = _run_locked(data_dir, output_dir, attempts, retry_delay, clock, sleep, outcome)
            try:
                _record(data_dir, result)
            except (OSError, ValueError, TypeError) as exc:
                # Report may already exist: explicitly retain its path rather than claiming nothing was saved.
                return replace(result, code=SAVE_ERROR, finished_utc=stamp(clock()),
                               reason=f'{result.reason}; run log could not be saved: {exc}')
            return result
    except JobBusy as exc:
        return outcome(ALREADY_RUNNING, str(exc))
    except OSError as exc:
        return outcome(CONFIG_ERROR, f'Cannot acquire the local run lock: {exc}')


def _run_locked(data_dir, output_dir, attempts, retry_delay, clock, sleep, outcome):
    database = data_dir / 'inventory.db'
    try:
        with read_view(database) as conn:
            if schema_version(conn) != ALERT_SCHEMA_VERSION:
                return outcome(CONFIG_ERROR, 'Open Stock Alerts in the GUI and explicitly upgrade the database first.')
        paths = Settings(data_dir / 'settings.json').load()
        if set(paths) != {'stock', 'bom'}:
            return outcome(CONFIG_ERROR, 'Select and successfully load both Excel files in the GUI first.')
    except Exception as exc:
        return outcome(DATABASE_ERROR, f'Local database unavailable; no automatic creation or upgrade: {exc}')
    last = None
    errors = []
    for count in range(1, attempts + 1):
        if count > 1:
            sleep(retry_delay)
        try:
            inventory = InventorySync(database, clock=clock)
            results = inventory.sync_all(paths, 'scheduled')
            if set(results) != {'stock', 'bom'} or not all(r.ok for r in results.values()):
                reason = '; '.join(f'{role}: {r.outcome}: {r.error or ""}' for role, r in results.items() if not r.ok)
                last = outcome(SOURCE_ERROR, 'Sources not verified; no cached report produced. ' + reason, count)
                errors.append(f'Attempt {count}: {last.reason}')
                continue
            gate = alerts.SessionGate()  # new authorization from THIS attempt, never inherited GUI/cache consent
            auth = alerts.Authorization(gate.generation, tuple(
                (role, results[role].version_id, results[role].path) for role in ('stock', 'bom')))
            evaluated = alerts.AlertService(database, clock=clock).run(
                'scheduled', auth, lambda: gate.publishing(auth.generation))
            if not evaluated.verified:
                last = outcome(DATABASE_ERROR, 'Alert evaluation was not verified; no report produced. ' +
                               (evaluated.reason or ''), count)
                errors.append(f'Attempt {count}: {last.reason}')
                continue
            now = clock()
            summary = daily.generate(database, now.astimezone().date(), daily.Session(gate.generation, auth, True),
                                     gate=gate, now=now)
            saved = daily.save(summary, output_dir, database, gate=gate)
            return replace(outcome(SUCCESS, 'Local versions checked; daily report saved. Cloud Not Verified.', count,
                                   saved.folder, summary.report_id), attempt_errors=tuple(errors))
        except daily.DailyUnsupported as exc:
            return replace(outcome(CONFIG_ERROR, str(exc), count), attempt_errors=tuple(errors))
        except (daily.DailyError, OSError) as exc:
            detail = '\n'.join(x for x in (str(exc), getattr(exc, 'cleanup_warning', '')) if x)
            last = outcome(SAVE_ERROR, detail, count)
        except Exception as exc:
            last = outcome(DATABASE_ERROR, f'{type(exc).__name__}: {exc}', count)
        errors.append(f'Attempt {count}: {last.reason}')
    return replace(last, attempt_errors=tuple(errors))
