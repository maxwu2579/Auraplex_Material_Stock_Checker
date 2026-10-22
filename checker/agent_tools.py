"""M4C allowlisted local tools. No SQL, file path or write capability is exposed to a model.

All data answers are explicitly selected historical SQLite observations, never local/cloud verification.
The host must obtain consent and call authorize_cached(); this capability is absent from the tool registry.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import threading
import time

from . import alerts, analytics, history, queries
from .core import check_materials, normalize_code, ROW_CAVEAT
from .inventory_db import stamp, utc_now

WARNINGS = ('UNVERIFIED — historical SQLite data; Excel sources were not checked.',
            'Cloud Not Verified', 'Blank stock means not recorded, not zero.',
            'Duplicate IDs are never added. Observed Change ≠ Actual Consumption.')
MAX_BYTES = 131_072


def plain(value):
    """Lossless JSON boundary: decimal quantities stay strings, not rounded floats."""
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or type(value) in (str, int, bool, float):
        return value
    raise TypeError('Unsupported tool result type')


def encoded(value):
    return json.dumps(plain(value), ensure_ascii=False, allow_nan=False, separators=(',', ':'))


class ToolError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _string():
    return {'type': 'string', 'minLength': 1, 'maxLength': 200}


def _spec(name, description, properties=None, required=()):
    return {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties or {},
                           'required': list(required), 'additionalProperties': False}}


TEXT = _string()
SHEET = _string()  # original Sheet names: no trimming or case folding
DAYS = {'type': 'integer', 'enum': [30, 60, 90]}
SPECS = (
    _spec('data_status', 'Recorded synchronization status only; never a new source verification.'),
    _spec('search_materials', 'Find literal partial IDs in the selected Storage version. Never merge candidates.',
          {'text': TEXT}, ('text',)),
    _spec('search_products', 'Find product candidates. Choose an original Sheet explicitly before calculation.',
          {'text': TEXT}, ('text',)),
    _spec('get_stock', 'Exact normalized Material ID; preserves separate Sheets and duplicate/raw rows.',
          {'material_id': TEXT, 'sheet': SHEET}, ('material_id',)),
    _spec('get_bom', 'Read one exact original BOM product Sheet; no configuration merging.',
          {'product_sheet': SHEET}, ('product_sheet',)),
    _spec('get_stock_alerts', 'Recorded active alerts only, not re-evaluated or verified in this session.'),
    _spec('estimate_requirements', 'Historical ESTIMATED / UNVERIFIED calculation using unchanged M2 engine.',
          {'product_sheet': SHEET, 'stock_sheet': SHEET,
           'quantity': {'type': 'integer', 'minimum': 1, 'maximum': 1_000_000}},
          ('product_sheet', 'stock_sheet', 'quantity')),
    _spec('material_history', 'Historical rows/observed changes, with coverage and truncation disclosed.',
          {'material_id': TEXT, 'days': DAYS, 'sheet': SHEET}, ('material_id', 'days')),
    _spec('material_analysis', 'M4B historical observations for an exact ID; never consumption/current availability.',
          {'material_id': TEXT, 'days': DAYS, 'sheet': SHEET}, ('material_id', 'days')),
)


def specifications():
    return json.loads(encoded(SPECS))  # adapters cannot mutate the registry through this accessor


def _validate(name, arguments):
    spec = next((s for s in SPECS if s['name'] == name), None)
    if spec is None:
        raise ToolError('TOOL_NOT_ALLOWED', 'Tool is not in the read-only allowlist.')
    if type(arguments) is not dict:
        raise ToolError('INVALID_ARGUMENTS', 'Arguments must be an object.')
    schema = spec['parameters']
    if set(arguments) - set(schema['properties']) or set(schema['required']) - set(arguments):
        raise ToolError('INVALID_ARGUMENTS', 'Missing or unknown argument.')
    for key, value in arguments.items():
        field = schema['properties'][key]
        if field['type'] == 'string':
            valid = type(value) is str and 0 < len(value) <= 200 and bool(value.strip()) and '\x00' not in value
        else:
            valid = type(value) is int and (value in field['enum'] if 'enum' in field else
                                           field['minimum'] <= value <= field['maximum'])
        if not valid:
            raise ToolError('INVALID_ARGUMENTS', f'Invalid {key}.')


class InventoryTools:
    """Session-owned capability; no consent is persisted. Construct off the Tk thread.

    One consistent view per tool. Basis checks reject normal synchronization/retention/replacement changes
    across calls. They do not prove Excel/cloud freshness or defend against a hostile database editor.
    """
    def __init__(self, database):
        self.database = Path(database).resolve()
        self._lock = threading.RLock()
        self._generation = 0
        self._consent_basis = None

    def revoke(self):
        with self._lock:
            self._generation += 1
            self._consent_basis = None

    @property
    def generation(self):
        with self._lock:
            return self._generation

    def authorize_cached(self):
        """HOST ONLY: call after explicit informed user consent, never from a provider/tool call."""
        basis = self.basis()
        with self._lock:
            self._generation += 1
            self._consent_basis = basis

    def _metadata(self, conn):
        versions = [dict(r) for r in conn.execute(
            'SELECT v.* FROM current_sources c JOIN source_versions v ON v.id=c.source_version_id ORDER BY c.role')]
        runs = [dict(r) for r in conn.execute(
            'SELECT * FROM sync_runs WHERE id IN (SELECT max(id) FROM sync_runs GROUP BY role) ORDER BY role')]
        retention = [tuple(r) for r in conn.execute('SELECT * FROM schema_info ORDER BY key')]
        snaps = tuple(conn.execute('SELECT count(*), max(id), sum(id) FROM inventory_snapshots').fetchone())
        evaluation = (conn.execute('SELECT id, outcome, finished_at, stock_version_id, bom_version_id'
                                   ' FROM alert_evaluations ORDER BY id DESC LIMIT 1').fetchone()
                      if conn.execute('PRAGMA user_version').fetchone()[0] >= 3 else None)
        return {'versions': versions, 'latest_attempts': runs, 'retention': retention, 'snapshots': snaps,
                'last_alert_evaluation': dict(evaluation) if evaluation else None}

    def _basis(self, conn):
        info = self.database.stat()
        content = [info.st_dev, info.st_ino, self._metadata(conn)]
        return hashlib.sha256(encoded(content).encode('utf-8')).hexdigest()

    def basis(self):
        with history.read_view(self.database) as conn:
            return self._basis(conn)

    def _allowed(self, generation, basis):
        with self._lock:
            if self._generation != generation:
                raise ToolError('STALE_SESSION', 'Session changed; previous evidence must not be published.')
            if self._consent_basis is None:
                raise ToolError('CONSENT_REQUIRED', 'Explicit selection of UNVERIFIED cached data is required.')
            if basis != self._consent_basis:
                raise ToolError('STALE_DATA', 'Database basis changed. Select cached data again.')

    def call(self, name, arguments, *, cancel=None, budget_seconds=5):
        started, generation = time.monotonic(), self.generation
        try:
            if type(budget_seconds) not in (int, float) or not 0 < budget_seconds <= 5:
                raise ToolError('INVALID_ARGUMENTS', 'Invalid query time budget.')
            _validate(name, arguments)
            if cancel is not None and cancel.is_set():
                raise ToolError('CANCELLED', 'Request cancelled.')
            with history.read_view(self.database) as conn:
                deadline = started + budget_seconds
                conn.set_progress_handler(lambda: int(time.monotonic() > deadline or
                    (cancel is not None and cancel.is_set())), 1000)
                basis = self._basis(conn)
                if name != 'data_status':
                    self._allowed(generation, basis)
                metadata = self._metadata(conn)
                data = self._execute(conn, name, arguments, cancel, deadline)
            if self.basis() != basis:
                raise ToolError('STALE_DATA', 'Database changed during query; no result published.')
            if name != 'data_status':
                self._allowed(generation, basis)
            if cancel is not None and cancel.is_set():
                raise ToolError('CANCELLED', 'Request cancelled.')
            if time.monotonic() > deadline:
                raise ToolError('LIMIT_EXCEEDED', 'Query time limit reached; no result published.')
            result = {'ok': True, 'tool': name, 'status': 'UNVERIFIED', 'cloud': 'NOT_VERIFIED',
                      'observed_at': stamp(utc_now()), 'basis': basis, 'session_generation': generation,
                      'warnings': WARNINGS,
                      'provenance': metadata, 'data': data}
            result = plain(result)
            if len(encoded(result).encode('utf-8')) > MAX_BYTES:
                raise ToolError('LIMIT_EXCEEDED', 'Result too large; narrow the query.')
            return result
        except ToolError as exc:
            return self._error(name, exc.code, str(exc))
        except analytics.AnalyticsCancelled:
            return self._error(name, 'CANCELLED', 'Request cancelled.')
        except analytics.AnalyticsLimit:
            return self._error(name, 'LIMIT_EXCEEDED', 'Analysis limit reached; narrow the query.')
        except (history.HistoryError, OSError, ValueError, TypeError, LookupError, ArithmeticError):
            if cancel is not None and cancel.is_set():
                return self._error(name, 'CANCELLED', 'Request cancelled.')
            if time.monotonic() - started >= budget_seconds:
                return self._error(name, 'LIMIT_EXCEEDED', 'Query time limit reached; no result published.')
            self.revoke()  # read failures invalidate all prior session evidence
            return self._error(name, 'DATABASE_READ_FAILED', 'Database unavailable or inconsistent; no result published.')

    @staticmethod
    def _error(name, code, message):
        return {'ok': False, 'tool': name, 'status': 'UNVERIFIED', 'cloud': 'NOT_VERIFIED',
                'warnings': list(WARNINGS), 'error': {'code': code, 'message': message}, 'data': None}

    @staticmethod
    def _book(conn, role):
        version = queries.current_version(conn, role)
        if version is None:
            raise ToolError('DATA_UNAVAILABLE', f'No successful {role} import.')
        # Validate record ownership before reconstruction (not just overall counts).
        table, parent, foreign = (('stock_records', 'stock_sheets', 'stock_sheet_id') if role == 'stock' else
                                  ('bom_lines', 'bom_products', 'bom_product_id'))
        broken = conn.execute(
            f'SELECT (SELECT count(*) FROM {table} r LEFT JOIN {parent} p ON p.id=r.{foreign}'
            ' WHERE r.source_version_id=? AND (p.id IS NULL OR p.source_version_id!=r.source_version_id))'
            f' + (SELECT count(*) FROM {parent} p JOIN {table} r ON r.{foreign}=p.id'
            ' WHERE p.source_version_id=? AND r.source_version_id!=p.source_version_id)',
            (version['id'], version['id'])).fetchone()[0]
        if broken:
            raise history.HistoryReadError('Inconsistent row ownership.')
        if version['record_count'] > 50_000:
            raise ToolError('LIMIT_EXCEEDED', 'Workbook exceeds the M4C query row limit.')
        return queries.load_workbook_data(conn, role)

    def _execute(self, conn, name, args, cancel, deadline):
        if name == 'data_status':
            return {'recorded_states': queries.freshness(conn), 'session_source_verification': 'NOT_PERFORMED',
                    'note': 'Recorded success is historical; unrecorded failures and live Excel state are unknown.'}
        if name in ('material_history', 'material_analysis'):
            key = normalize_code(args['material_id'])
            # M4A has no overall snapshot cap: impose one at the new tool boundary.
            now = utc_now()
            start, end = stamp(now - timedelta(days=args['days'])), stamp(now)
            window = conn.execute('SELECT source_version_id, record_count FROM inventory_snapshots'
                                  ' WHERE observed_at>=? AND observed_at<=? LIMIT 401', (start, end)).fetchall()
            reference = conn.execute('SELECT source_version_id, record_count FROM inventory_snapshots WHERE observed_at<?'
                                     ' ORDER BY observed_at DESC, id DESC LIMIT 1', (start,)).fetchone()
            selected = window + ([reference] if reference is not None else [])
            if len(window) > 400 or sum(s['record_count'] for s in selected) > 50_000:
                raise ToolError('LIMIT_EXCEEDED', 'Too many historical observations; narrow the range.')
            versions = sorted({s['source_version_id'] for s in selected})
            if versions:
                slots = ','.join('?' for _ in versions)
                # Check both directions using per-version indexes: a foreign row attached to a selected
                # Sheet is inconsistent even when that row's declared version is outside the window.
                broken = conn.execute(
                    'SELECT EXISTS(SELECT 1 FROM stock_records r LEFT JOIN stock_sheets s ON s.id=r.stock_sheet_id'
                    f' WHERE r.source_version_id IN ({slots})'
                    ' AND (s.id IS NULL OR s.source_version_id!=r.source_version_id))'
                    ' OR EXISTS(SELECT 1 FROM stock_sheets s JOIN stock_records r ON r.stock_sheet_id=s.id'
                    f' WHERE s.source_version_id IN ({slots}) AND r.source_version_id!=s.source_version_id)',
                    versions + versions).fetchone()[0]
                if broken:
                    raise history.HistoryReadError('Historical row ownership is inconsistent.')
            # Reuse this read-only snapshot and its SQLite timeout/cancellation handler.
            if name == 'material_history':
                return history.material_history(self.database, key, args['days'], args.get('sheet'),
                                                now=now, max_rows=200, max_changes=200, connection=conn)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ToolError('LIMIT_EXCEEDED', 'Query time limit reached; no result published.')
            try:
                result = analytics.analyze(self.database, args['days'], args.get('sheet'), key,
                                           now=now, cancel=cancel, max_rows=50_000, max_groups=200,
                                           budget_seconds=remaining, connection=conn)
            finally:
                # analyze installs/removes its own handler; restore the caller's original deadline.
                conn.set_progress_handler(lambda: int(time.monotonic() > deadline or
                    (cancel is not None and cancel.is_set())), 1000)
            return {**plain(result), 'materials': [plain(m) for m in result.materials if m.material_key == key]}
        if name == 'get_stock_alerts':
            state = alerts.state_in(conn, include_other_sources=False, limit=200)
            return {'recorded': plain(state), 'truncated': state.total_rows > len(state.rows),
                    'assessment': ('UPGRADE_REQUIRED' if state.schema < 3 else
                                   'NOT_EVALUATED' if state.latest_completed is None else 'NOT_RECHECKED'),
                    'note': 'Not re-checked. No evaluation means unknown, never no stock problems. '
                            'Counts overlap; their sum is not a count of distinct materials.'}
        if name in ('search_materials', 'get_stock'):
            book = self._book(conn, 'stock')
            rows = [(s.name, m) for s in book.stock_sheets for m in s.materials]
            if name == 'search_materials':
                needle = normalize_code(args['text'])
                found = sorted({(s, normalize_code(m.code)) for s, m in rows
                                if m.code_type not in ('f', 'e') and needle in normalize_code(m.code)})
                return {'candidates': [{'sheet': s, 'material_id': k} for s, k in found[:200]],
                        'total': len(found), 'truncated': len(found) > 200, 'selection_required': True}
            key = normalize_code(args['material_id'])
            found = [m for s, m in rows if normalize_code(m.code) == key and m.code_type not in ('f', 'e')
                     and ('sheet' not in args or s == args['sheet'])]
            if len(found) > 200:
                raise ToolError('LIMIT_EXCEEDED', 'Too many matching rows; choose a Sheet.')
            result_rows = []
            for material in found:
                duplicates = sum(m.source.sheet == material.source.sheet for m in found)
                state = alerts.quantity_status(material.quantity, material.quantity_type)[0]
                result_rows.append({**plain(material), 'recorded_qty_status': state,
                                    'match_status': 'DUPLICATE_STOCK' if duplicates > 1 else state,
                                    'duplicate_rows_in_sheet': duplicates})
            return {'material_id': key, 'found': bool(found), 'rows': result_rows,
                    'note': 'Separate raw rows; missing means unknown, never zero. No aggregate stock supplied.'}
        bom = self._book(conn, 'bom')
        if name == 'search_products':
            found = [p for p in bom.products if normalize_code(args['text']) in normalize_code(p.display_name)]
            return {'candidates': [{'source_path': p.file_path, 'sheet': p.sheet_name,
                                    'display_name': p.display_name} for p in found[:200]],
                    'total': len(found), 'truncated': len(found) > 200, 'selection_required': True}
        product = next((p for p in bom.products if p.sheet_name == args['product_sheet']), None)
        if product is None:
            raise ToolError('SELECTION_REQUIRED', 'Select an exact original product Sheet from search_products.')
        if name == 'get_bom':
            return plain(product)
        stock = self._book(conn, 'stock')
        selected = next((s for s in stock.stock_sheets if s.name == args['stock_sheet']), None)
        if selected is None:
            raise ToolError('SELECTION_REQUIRED', 'Select an exact original Storage Sheet.')
        return {'calculation': plain(check_materials(product, selected, args['quantity'])),
                'caveat': ROW_CAVEAT, 'mode': 'ESTIMATED / UNVERIFIED'}
