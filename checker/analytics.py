"""M4B deterministic historical observations. Read-only; never consumption or current availability.

Separate cohorts are (source path, original Sheet name, exact normalized Material ID).
Only adjacent, retained, same-source snapshots with single valid records can form an interval.
Absence, duplicates, missing payloads and source switches break comparability, never imply zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
import time

from .core import normalize_code
from .history import HistoryError, HistoryReadError, RANGES, read_view
from .inventory_db import decode, parse_stamp, stamp, utc_now

BANNER = 'HISTORICAL ANALYSIS · UNVERIFIED · Not current stock · Cloud Not Verified'
CAVEAT = ('Observed Change ≠ Actual Consumption. Blank ≠ 0; duplicates are not added. '
          'Units, critical spares, demand and lead times need human confirmation.')
MAX_SNAPSHOTS, MAX_ROWS, MAX_GROUPS = 400, 200_000, 5_000


class AnalyticsError(HistoryError):
    pass


class AnalyticsCancelled(AnalyticsError):
    pass


class AnalyticsLimit(AnalyticsError):
    pass


@dataclass(frozen=True)
class Policy:
    minimum_days: int = 30
    low_movement: Decimal = Decimal('0')
    large_change_percent: Decimal = Decimal('50')

    def __post_init__(self):
        if type(self.minimum_days) is not int or not 1 <= self.minimum_days <= 90:
            raise AnalyticsError('Minimum observed span must be an integer from 1 to 90 days.')
        for name in ('low_movement', 'large_change_percent'):
            try:
                value = Decimal(str(getattr(self, name)))
            except (InvalidOperation, ValueError):
                raise AnalyticsError('Analysis thresholds must be finite non-negative numbers.') from None
            if not value.is_finite() or value < 0 or value > Decimal('1e12'):
                raise AnalyticsError('Analysis thresholds must be finite, non-negative and at most 1e12.')
            if name == 'large_change_percent' and value == 0:
                raise AnalyticsError('Large-change percentage must be positive.')
            object.__setattr__(self, name, value)


@dataclass(frozen=True)
class Observation:
    snapshot_id: int
    version_id: int
    observed_at: str
    reference: bool
    state: str
    value: Decimal | None
    rows: tuple[int, ...]
    raw_quantities: tuple
    description: object = None
    racks: tuple = ()
    levels: tuple = ()


@dataclass(frozen=True)
class MaterialAnalysis:
    source_path: str
    sheet: str
    material_key: str
    observations: tuple[Observation, ...]
    comparable_intervals: int
    changed_intervals: int
    movement: Decimal | None  # sum of absolute deltas on comparable intervals only
    net_change: Decimal | None  # withheld unless the complete chain is comparable
    largest_step: Decimal | None
    large_change_count: int
    window_span_days: float
    longest_unchanged_days: float
    trailing_unchanged_days: float
    signals: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class Analysis:
    database: str
    days: int
    start: str
    evaluated_at: str
    policy: Policy
    materials: tuple[MaterialAnalysis, ...]
    snapshots_in_window: int
    reference_at: str | None
    retained_from: str | None
    sheet_names: tuple[str, ...]
    unkeyed_rows: int
    notes: tuple[str, ...]


def _checkpoint(stage):
    """Fault-injection boundary inside the same read transaction."""


def analyze(database, days=30, sheet=None, material_text='', *, now=None, policy=None, cancel=None,
            max_snapshots=MAX_SNAPSHOTS, max_rows=MAX_ROWS, max_groups=MAX_GROUPS, budget_seconds=5):
    """One consistent bounded read view. No file reads, sync, migrations, writes or extrapolation to today.

    Includes the last global snapshot before the window as a labelled reference. Deltas involving it are observed
    at the later snapshot, not measurements of when the physical movement occurred. Limit failure returns no result.
    """
    if type(days) is not int or days not in RANGES:
        raise AnalyticsError('Choose 30, 60 or 90 days.')
    if any(type(v) is not int or v < 1 for v in (max_snapshots, max_rows, max_groups)) or not 0 < budget_seconds <= 30:
        raise AnalyticsError('Invalid analysis resource limits.')
    policy = policy or Policy()
    end = now or utc_now()
    if end.tzinfo is None or end.utcoffset() is None:
        raise AnalyticsError('Analysis time must include a time zone.')
    start_s, end_s = stamp(end - timedelta(days=days)), stamp(end)
    needle = normalize_code(material_text)
    deadline = time.monotonic() + budget_seconds

    def check():
        if cancel is not None and cancel.is_set():
            raise AnalyticsCancelled('Analysis cancelled; no result published.')
        if time.monotonic() >= deadline:
            raise AnalyticsLimit('Analysis time limit reached. Choose a shorter range or narrower filter.')

    with read_view(database) as conn, localcontext() as context:
        # Native Excel quantities span binary64 values; avoid default-28-digit rounding of their stored decimals.
        context.prec = 2048
        conn.set_progress_handler(lambda: int((cancel is not None and cancel.is_set()) or
                                             time.monotonic() >= deadline), 1000)
        try:
            check()
            window = list(conn.execute('SELECT * FROM inventory_snapshots WHERE observed_at >= ? AND observed_at <= ?'
                                       ' ORDER BY observed_at, id LIMIT ?', (start_s, end_s, max_snapshots + 1)))
            if len(window) > max_snapshots:
                raise AnalyticsLimit('Too many snapshots. Choose a shorter range; no partial analysis is shown.')
            reference = conn.execute('SELECT * FROM inventory_snapshots WHERE observed_at < ? ORDER BY observed_at DESC,'
                                     ' id DESC LIMIT 1', (start_s,)).fetchone()
            snaps = ([reference] if reference is not None else []) + window
            retained = conn.execute("SELECT value FROM schema_info WHERE key='history_retained_from'").fetchone()
            retained_from = retained[0] if retained else None
            _checkpoint('snapshot_view')
            if sum(s['record_count'] for s in snaps) > max_rows:
                raise AnalyticsLimit('Too many historical rows. Choose a shorter range; no partial analysis is shown.')
            payloads, groups, sheets, unkeyed = [], set(), set(), 0
            for snap in snaps:
                check()
                version = conn.execute('SELECT source_path, record_count FROM source_versions WHERE id=?',
                                       (snap['source_version_id'],)).fetchone()
                if version is None:
                    raise HistoryReadError('Snapshot source metadata is missing.')
                count = conn.execute('SELECT count(*) FROM stock_records WHERE source_version_id=?',
                                     (snap['source_version_id'],)).fetchone()[0]
                complete = count == version['record_count'] == snap['record_count']
                selected = {}
                for s in conn.execute('SELECT sheet_name FROM stock_sheets WHERE source_version_id=?',
                                      (snap['source_version_id'],)):
                    sheets.add(s[0])
                if complete:
                    for r in conn.execute('SELECT r.*, s.sheet_name FROM stock_records r JOIN stock_sheets s'
                                          ' ON s.id=r.stock_sheet_id WHERE r.source_version_id=? ORDER BY s.sheet_index,'
                                          ' r.ordinal', (snap['source_version_id'],)):
                        check()
                        if sheet is not None and r['sheet_name'] != sheet:
                            continue
                        if r['material_key'] is None:
                            unkeyed += 1
                            continue
                        if needle and needle not in r['material_key']:
                            continue
                        key = (version['source_path'], r['sheet_name'], r['material_key'])
                        groups.add(key)
                        if len(groups) > max_groups:
                            raise AnalyticsLimit('Too many material/source groups. Enter a Material ID filter.')
                        selected.setdefault(key, []).append(dict(r))
                payloads.append((dict(snap), version['source_path'], complete, selected))
            _checkpoint('payloads')
            notes = [CAVEAT, 'Reference snapshots may predate the window. Differences are dated by the later sync.',
                     'Only imported versions create snapshots; no new snapshot does not prove unchanged physical stock.',
                     'No demand, consumption, reorder quantity or confirmed excess-stock quantity is calculated.']
            if not window:
                notes.append('No snapshot imported in the selected window; an older reference is not a new observation.')
            if reference is None and (not window or window[0]['observed_at'] > start_s):
                notes.append('History does not cover the window start; earlier quantities are unknown.')
            if retained_from and start_s < retained_from:
                notes.append('History was pruned; removed values are unknown, not zero.')
            missing_payloads = sum(not p[2] for p in payloads)
            if missing_payloads:
                notes.append(f'{missing_payloads} snapshot payload(s) incomplete/not retained; quantities are unknown.')
            materials = []
            for key in sorted(groups):
                check()
                materials.append(_material(key, payloads, start_s, policy,
                                           bool(retained_from and start_s < retained_from)))
            check()
            return Analysis(str(Path(database)), days, start_s, end_s, policy, tuple(materials), len(window),
                            reference['observed_at'] if reference else None, retained_from, tuple(sorted(sheets)),
                            unkeyed, tuple(notes))
        except Exception:
            check()  # turn SQLite's interrupted error into a useful cancellation/limit reason
            raise
        finally:
            conn.set_progress_handler(None, 0)


def _observation(snap, complete, records, start):
    state = 'NOT_RETAINED' if not complete else 'ABSENT' if not records else (
        'DUPLICATE' if len(records) > 1 else records[0]['qty_status'])
    value = None
    if state == 'VALID':
        try:
            value = Decimal(records[0]['qty_value'])
        except (InvalidOperation, TypeError):
            raise HistoryReadError('A VALID stock record has an invalid stored number.') from None
        if not value.is_finite() or value < 0 or abs(value.adjusted()) > 400:
            raise HistoryReadError('A stored stock number is outside the supported finite Excel range.')
    raw = lambda column: tuple(decode(r[column + '_kind'], r[column + '_text']) for r in records)
    return Observation(snap['id'], snap['source_version_id'], snap['observed_at'], snap['observed_at'] < start,
                       state, value, tuple(r['row_no'] for r in records), raw('qty'),
                       decode(records[0]['description_kind'], records[0]['description_text']) if records else None,
                       raw('rack'), raw('level'))


def _material(key, payloads, start, policy, pruned):
    points, intervals, flags = [], [], set()
    full_chain = not pruned
    unchanged_start = None
    longest = 0.0
    previous = None
    for index, (snap, path, complete, selected) in enumerate(payloads):
        if path != key[0]:
            continue
        point = _observation(snap, complete, selected.get(key, ()), start)
        if point.state != 'VALID':
            flags.add(point.state)
            full_chain = False
        if previous is not None:
            prev_index, prev_snap, prev_point = previous
            comparable = (index == prev_index + 1 and snap['same_source_path'] != 0
                          and snap['previous_version_id'] == prev_snap['source_version_id']
                          and point.state == prev_point.state == 'VALID')
            if comparable:
                delta = point.value - prev_point.value
                intervals.append((delta, prev_point.value))
                if delta == 0:
                    unchanged_start = unchanged_start or max(prev_point.observed_at, start)
                    longest = max(longest, (parse_stamp(point.observed_at) - parse_stamp(unchanged_start)).total_seconds()/86400)
                else:
                    unchanged_start = None
            else:
                flags.add('INCOMPARABLE_GAP')
                full_chain = False
                unchanged_start = None
        points.append(point)
        previous = index, snap, point
    if pruned:
        flags.add('HISTORY_PRUNED')
    if payloads[-1][1] != key[0]:
        flags.add('OTHER_SOURCE_HISTORY')
    movement = sum((abs(d) for d, _ in intervals), Decimal(0)) if intervals else None
    net = sum((d for d, _ in intervals), Decimal(0)) if intervals and full_chain else None
    span = max(0, (parse_stamp(points[-1].observed_at) - parse_stamp(max(points[0].observed_at, start))).total_seconds()/86400)
    enough = bool(full_chain and intervals and span >= policy.minimum_days and 'OTHER_SOURCE_HISTORY' not in flags)
    if not enough:
        flags.add('INSUFFICIENT_HISTORY')
    elif movement <= policy.low_movement:
        flags.add('LOW_OBSERVED_MOVEMENT')
    trailing = max(0, (parse_stamp(points[-1].observed_at) - parse_stamp(unchanged_start)).total_seconds()/86400) if unchanged_start else 0
    if enough and trailing >= policy.minimum_days:
        flags.add('LONG_UNCHANGED_OBSERVATIONS')
        if points[-1].value is not None and points[-1].value > 0:
            flags.add('POSITIVE_UNCHANGED_REVIEW')
    large = sum(1 for delta, before in intervals if before > 0 and abs(delta)*100 >= before*policy.large_change_percent)
    if large:
        flags.add('LARGE_OBSERVED_CHANGE')
    if any(before == 0 and delta > 0 for delta, before in intervals):
        flags.add('FROM_ZERO_PERCENT_UNKNOWN')
    if points[-1].value == 0:
        flags.add('LAST_OBSERVED_ZERO')
    notes = ['Movement sums |delta| on comparable intervals only; net is withheld across gaps.',
             'Span is clipped to the selected window; unchanged duration is between recorded observations only.',
             'Positive unchanged stock is a human-review cue, not proof of excess stock or low importance.']
    if any(p.reference for p in points):
        notes.append('Includes a before-window reference, not a newly observed opening quantity.')
    return MaterialAnalysis(*key, tuple(points), len(intervals), sum(d != 0 for d, _ in intervals), movement, net,
                            max((abs(d) for d, _ in intervals), default=None), large, span, longest, trailing,
                            tuple(sorted(flags)), tuple(notes))
