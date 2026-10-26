"""M4E host controller. One worker, memory-only permissions, queued immutable observations; no Tk."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import queue
import re
import threading
import uuid

from .agent import Agent, ProviderFailure, SYSTEM
from .agent_tools import InventoryTools, specifications, encoded
from .assistant_language import LANGUAGES, error_text, tool_error_text, tr
from .credentials import WindowsKeyStore
from .history import read_view
from . import narrative, readable
from .providers import create_provider


@dataclass(frozen=True)
class Delivery:
    epoch: int
    action: str
    language: str
    result: dict
    reply: str
    evidence_text: str


def failure(code):
    return {'status': 'FAILED', 'error': code, 'evidence': []}


class SessionFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class AssistantSession:
    """Owned by one chat surface; never persist conversation, permissions or database selections.

    Closing/Stop/source changes revoke bindings and in-flight capabilities; a new explicit Send
    rebinds recorded data without modal permission steps. Legacy guarded actions remain available.
    A cancelled worker must exit before another
    worker can start. Network cancellation is also bounded/single-flight by the existing M4D transport.
    """
    def __init__(self, database=None, *, provider=None, key_store=None):
        self.tools = InventoryTools(database) if database is not None else None
        self.keys = key_store if key_store is not None else WindowsKeyStore()
        self.provider = provider if provider is not None else create_provider(key_store=self.keys)
        self._lock = threading.RLock()
        self._epoch, self._busy, self.closed = 0, False, False
        self._cancel = threading.Event()
        self.events = queue.Queue()
        self.authorized = self.outbound = False
        self._authorized_basis = None
        self._report_approval = None
        self.context, self._selections = {}, {}

    @property
    def epoch(self):
        with self._lock:
            return self._epoch

    @property
    def busy(self):
        with self._lock:
            return self._busy

    def invalidate(self):
        with self._lock:
            self._epoch += 1
            self._cancel.set()
            self._revoke()

    def _revoke(self):
        self.authorized = self.outbound = False
        self._authorized_basis = None
        self._report_approval = None
        self.context, self._selections = {}, {}
        if self.tools is not None:
            self.tools.revoke()
        self.provider.revoke_outbound()

    def close(self):
        with self._lock:
            self.closed = True
            self.invalidate()

    def allow_outbound(self, expected_epoch, accepted):
        """Trusted Tk host only, after a No-default disclosure and exact request preview."""
        with self._lock:
            if self.closed or self._busy or self._epoch != expected_epoch:
                return False
            self.provider.authorize_outbound(policy=self.provider.policy, accepted=accepted)
            self.outbound = accepted
            self._report_approval = None
            return True

    def approve_report(self, expected_epoch, basis, facts_digest, report_language, request_sha256, accepted):
        """Mint a one-use report grant only after the UI displayed the exact request and received Yes."""
        with self._lock:
            if (not accepted or self.closed or self._busy or self._epoch != expected_epoch or
                    not self.authorized or not self.outbound or basis != self._authorized_basis or
                    type(facts_digest) is not str or not re.fullmatch(r'[0-9a-f]{64}', facts_digest) or
                    report_language not in narrative.LANGUAGES or type(request_sha256) is not str or
                    not re.fullmatch(r'[0-9a-f]{64}', request_sha256)):
                self._report_approval = None
                self.provider.clear_narrative_authorization()
                return None
            if not self.provider.authorize_narrative(policy=narrative.REPORT_POLICY, accepted=True):
                self._report_approval = None
                return None
            token = uuid.uuid4().hex
            self._report_approval = (token, expected_epoch, basis, facts_digest, report_language, request_sha256)
            return token

    def discard_report_approval(self, token=None):
        with self._lock:
            if self._report_approval is not None and (token is None or self._report_approval[0] == token):
                self._report_approval = None
                self.provider.clear_narrative_authorization()

    @contextmanager
    def report_guard(self, expected_epoch, basis):
        """M4F delivery: held while a saved report is published. Yields whether this session still holds exactly the
        local-data authorisation the report was built under; invalidate()/close() wait until the block ends. Never
        waits for SQLite while held (callers take their database read lock first)."""
        with self._lock:
            yield (not self.closed and self._epoch == expected_epoch and self.authorized and
                   basis is not None and basis == self._authorized_basis)

    def data_basis(self, conn):
        """The data basis inside the caller's read transaction (the same digest report previews are bound to)."""
        return self.tools._basis(conn)

    def preview_request(self, question):
        return self.provider.preview([{'role': 'system', 'content': SYSTEM},
                                      {'role': 'user', 'content': question}], specifications()).decode('utf-8')

    def protected_labels(self):
        with self._lock:
            return tuple(list(self.context.get('stock_sheets', ())) + list(self.context.get('products', ())) +
                         list(self.context.get('source_names', ())) +
                         [s['row']['material_id'] for s in self._selections.values() if s['kind'] == 'material'])

    def submit(self, action, language='en', *, expected_epoch=None, **payload):
        with self._lock:
            if self.closed or self._busy or (expected_epoch is not None and expected_epoch != self._epoch):
                return False
            if action == 'report_narrative':
                approval = self._report_approval
                if (approval is None or approval[0] != payload.get('approval') or approval[1] != self._epoch or
                        approval[2] != payload.get('basis') or approval[3] != payload.get('facts_digest') or
                        approval[4] != payload.get('report_language') or approval[5] != payload.get('request_sha256') or
                        not self.authorized or not self.outbound):
                    return False
                self._report_approval = None
            self._busy = True
            epoch, cancel = self._epoch, threading.Event()
            self._cancel = cancel

        def work():
            result = failure('REQUEST_FAILED')
            try:
                result = self._execute(action, payload, cancel)
                basis = result.get('basis')
                if basis and action in ('chat', 'current_chat', 'local', 'report_preview', 'report_narrative') and basis != self._authorized_basis:
                    result = failure('STALE_DATA')
                if basis and (self.tools is None or self.tools.basis() != basis):
                    result = failure('STALE_DATA')
            except (ProviderFailure, SessionFailure) as exc:
                result = failure(exc.code)
            except ValueError:
                result = failure('INVALID_ARGUMENTS' if action in ('report_preview', 'report_narrative') else 'DATABASE_READ_FAILED')
            except Exception:
                result = failure('KEY_FAILED' if action in ('save_key', 'delete_key') else 'DATABASE_READ_FAILED')
            finally:
                payload.clear()  # no key/question in the completion queue; Python cannot guarantee zeroization
                # Format bounded display strings on the worker, before taking the short publication lock.
                try:
                    reply = render(result, language)
                    evidence_text = render_details(result, language)  # readable rows, data basis, canonical JSON
                except Exception:
                    result = failure('DATABASE_READ_FAILED')
                    reply, evidence_text = error_text('DATABASE_READ_FAILED', language), ''
                with self._lock:
                    if not self.closed and epoch == self._epoch and not cancel.is_set():
                        if result.get('error') in ('DATABASE_READ_FAILED', 'STALE_DATA', 'STALE_SESSION'):
                            self._revoke()
                        self._publish_selections(result)
                        self.events.put(Delivery(epoch, action, language, result, reply, evidence_text))
                    elif action in ('authorize', 'current_chat', 'load_current'):
                        # Authorization may finish after invalidate(); it cannot restore old consent.
                        if self.tools is not None:
                            self.tools.revoke()
                        self.authorized = False
                    self._busy = False

        try:
            threading.Thread(target=work, name='MRC-Assistant', daemon=True).start()
        except Exception:
            with self._lock:
                self._busy = False
            raise
        return True

    def drain(self):
        deliveries = []
        with self._lock:
            while True:
                try:
                    event = self.events.get_nowait()
                except queue.Empty:
                    break
                if not self.closed and event.epoch == self._epoch:
                    deliveries.append(event)
        return deliveries

    def _context(self, basis):
        with read_view(self.tools.database) as conn:
            # Host-only metadata; no arbitrary SQL/path is exposed to a model or user input.
            sheets = [r[0] for r in conn.execute(
                "SELECT s.sheet_name FROM stock_sheets s JOIN current_sources c ON c.source_version_id=s.source_version_id"
                " WHERE c.role='stock' ORDER BY s.sheet_index LIMIT 201")]
            products = [r[0] for r in conn.execute(
                "SELECT p.sheet_name FROM bom_products p JOIN current_sources c ON c.source_version_id=p.source_version_id"
                " WHERE c.role='bom' ORDER BY p.sheet_index LIMIT 201")]
        if self.tools.basis() != basis:
            raise SessionFailure('STALE_DATA')
        if len(sheets) > 200 or len(products) > 200:
            raise SessionFailure('LIMIT_EXCEEDED')
        return {'stock_sheets': sheets, 'products': products, 'source_names': []}

    def _execute(self, action, payload, cancel):
        if action in ('save_key', 'delete_key'):
            with self._lock:
                self._revoke()
            if action == 'save_key':
                self.keys.save(payload.pop('key'))
            else:
                self.keys.delete()
            return {'status': 'KEY_SAVED' if action == 'save_key' else 'KEY_DELETED'}
        if self.tools is None:
            return failure('DATABASE_READ_FAILED')
        if action in ('preview_data', 'authorize'):
            observation = self.tools.call('data_status', {}, cancel=cancel)
            if not observation['ok']:
                return failure(observation['error']['code'])
            if not observation['provenance']['versions']:
                return failure('DATA_UNAVAILABLE')
            basis = observation['basis']
            context = self._context(basis)
            context['source_names'] = [Path(v['source_path']).name for v in observation['provenance']['versions']]
            if action == 'authorize':
                if basis != payload['expected_basis']:
                    return failure('STALE_DATA')
                self.tools.authorize_cached()
                if self.tools.basis() != basis:
                    return failure('STALE_DATA')
                with self._lock:
                    if not cancel.is_set() and not self.closed:
                        self.authorized = True
                        self._authorized_basis = basis
                        self.context = context
            return {'status': 'PREVIEW' if action == 'preview_data' else 'AUTHORIZED', 'basis': basis,
                    'observation': observation, 'context': context}
        if action in ('current_chat', 'load_current'):
            # A deliberate Send/load action uses the current recorded snapshot. This is a host
            # operation, never a model tool. Rebind data, but never retry a network request.
            if action == 'current_chat':
                question = payload.get('question')
                if not isinstance(question, str) or not question.strip() or len(question) > 4000:
                    return failure('INVALID_QUESTION')
            if cancel.is_set() or self.closed:
                return failure('CANCELLED')
            basis = self.tools.basis()
            if not self.authorized or basis != self._authorized_basis:
                prepared = self._execute('authorize', {'expected_basis': basis}, cancel)
                if prepared.get('status') != 'AUTHORIZED':
                    return prepared
            if cancel.is_set() or self.closed:
                return failure('CANCELLED')
            if action == 'load_current':
                return {'status': 'AUTHORIZED', 'basis': self._authorized_basis}
            with self._lock:
                if cancel.is_set() or self.closed:
                    return failure('CANCELLED')
                if not self.outbound:
                    self.provider.authorize_outbound(policy=self.provider.policy, accepted=True)
                    self.outbound = True
            result = self._execute('chat', payload, cancel)
            result.setdefault('basis', self._authorized_basis)
            return result
        if not self.authorized:
            return failure('CONSENT_REQUIRED')
        if action == 'report_preview':
            if payload.get('period') not in narrative.PERIODS:
                return failure('INVALID_ARGUMENTS')
            with read_view(self.tools.database) as conn:
                basis = self.tools._basis(conn)
                if basis != self._authorized_basis:
                    raise SessionFailure('STALE_DATA')
                try:
                    facts = narrative.build_in(conn, payload['period'])
                except ValueError:
                    raise SessionFailure('INVALID_ARGUMENTS') from None
            return {'status': 'REPORT_PREVIEW', 'basis': basis, 'facts': facts,
                    'facts_digest': narrative.digest(facts), 'evidence': []}
        if action == 'report_narrative':
            if not self.outbound:
                return failure('OUTBOUND_CONSENT_REQUIRED')
            try:
                facts = narrative.validate_facts(payload.get('facts'))
            except ValueError:
                raise SessionFailure('INVALID_ARGUMENTS') from None
            facts_digest = narrative.digest(facts)
            if facts_digest != payload.get('facts_digest') or payload.get('basis') != self._authorized_basis:
                raise SessionFailure('STALE_DATA')
            if self.tools.basis() != self._authorized_basis:
                raise SessionFailure('STALE_DATA')
            reply = self.provider.complete_narrative(
                facts, payload.get('report_language', 'en'), expected_request_sha256=payload.get('request_sha256'),
                timeout=20, cancel=cancel)
            if reply.calls or type(reply.text) is not str or not reply.text.strip() or len(reply.text) > 4000:
                raise ProviderFailure('INVALID_PROVIDER_RESPONSE')
            return {'status': 'NARRATIVE', 'basis': self._authorized_basis, 'facts': facts,
                    'facts_digest': facts_digest, 'narrative': reply.text, 'evidence': []}
        if action == 'chat':
            if not self.outbound:
                return failure('OUTBOUND_CONSENT_REQUIRED')
            return Agent(self.tools, self.provider).run(payload['question'], cancel=cancel)
        if action != 'local':
            return failure('INVALID_ARGUMENTS')
        name, args = payload['tool'], {}
        if name in ('search_materials', 'search_products'):
            args['text'] = payload.get('text', '')
        elif name in ('get_stock', 'material_history', 'material_analysis', 'get_bom', 'estimate_requirements'):
            with self._lock:
                selected = self._selections.get(payload.get('candidate'))
            needed = 'product' if name in ('get_bom', 'estimate_requirements') else 'material'
            if selected is None or selected['kind'] != needed:
                return failure('SELECTION_REQUIRED')
            if self.tools.basis() != selected['basis']:
                return failure('STALE_DATA')
            row = selected['row']
            args = {'product_sheet': row['sheet']} if needed == 'product' else {
                'material_id': row['material_id'], 'sheet': row['sheet']}
            if name in ('material_history', 'material_analysis'):
                args['days'] = payload.get('days')
            elif name == 'estimate_requirements':
                if payload.get('stock_sheet') not in self.context.get('stock_sheets', ()):
                    return failure('SELECTION_REQUIRED')
                args.update(stock_sheet=payload['stock_sheet'], quantity=payload.get('quantity'))
        elif name not in ('get_stock_alerts', 'data_status'):
            return failure('INVALID_ARGUMENTS')
        observation = self.tools.call(name, args, cancel=cancel)
        return {'status': 'TOOL_RESULTS' if observation['ok'] else 'FAILED',
                'error': None if observation['ok'] else observation['error']['code'],
                'basis': observation.get('basis'), 'evidence': [observation] if observation['ok'] else []}

    def _publish_selections(self, result):
        candidates = []
        searches = [item for item in result.get('evidence', ()) if item['ok'] and item['tool'] in
                    ('search_materials', 'search_products')]
        if searches:
            self._selections.clear()
        for item in searches:
            kind = 'material' if item['tool'] == 'search_materials' else 'product'
            for row in item['data']['candidates']:
                token = uuid.uuid4().hex
                selected = {'kind': kind, 'row': row, 'basis': item['basis']}
                self._selections[token] = selected
                candidates.append({'token': token, **selected})
        if searches:
            result['candidates'] = candidates


def render(result, language):
    """The chat answer: deterministic local evidence only; arbitrary model prose is never displayed.

    Business answer first (identity, recorded quantity, location, counts), one data-status line, and only the limits
    that belong to this answer. Paths, hashes, versions, sync logs and codes stay in render_details (Evidence)."""
    if result.get('status') == 'NEEDS_INPUT':
        key = result.get('guidance')
        return tr(key if key in ('ask_stock', 'ask_history', 'ask_product', 'ask_query') else 'ask_query', language)
    if result.get('status') == 'FAILED':
        return error_text(result.get('error', 'REQUEST_FAILED'), language)
    if result.get('status') == 'AUTHORIZED':
        return tr('authorized', language)
    if result.get('status') == 'REPORT_PREVIEW':
        return tr('report_preview_ready', language)
    if result.get('status') == 'NARRATIVE':
        return (tr('report_interpretation', language) + '\n' + result['narrative'] + '\n' +
                tr('report_review_caveat', language))
    if result.get('status') in ('KEY_SAVED', 'KEY_DELETED'):
        return tr('saved_key' if result['status'] == 'KEY_SAVED' else 'deleted_key', language)
    evidence = result.get('evidence') or []
    lines = _status_lines(evidence, language)
    shortened = False
    for item in evidence:
        lines.append('')
        if not item['ok']:
            lines.append(tool_error_text(item['error'], language))
            continue
        body, cut = _answer(item, language, SUMMARY_ITEMS)
        lines += body
        shortened = shortened or cut
    if not evidence:
        lines.append(error_text(result.get('error') or 'NO_TOOL_EVIDENCE', language))
    if any(item['ok'] for item in evidence):
        lines += ['', tr('c_details', language)]
    text = '\n'.join(lines)
    return text if len(text) <= 80_000 else text[:80_000] + '\n' + tr('omitted', language)


def render_details(result, language):
    """Evidence tab: every returned row in business language, then the data basis, then the canonical JSON."""
    evidence = result.get('evidence') or []
    lines = []
    for item in evidence:
        if not item['ok']:
            lines += [tool_error_text(item['error'], language), '']
            continue
        body, _cut = _answer(item, language, None)
        lines += body + ['']
    basis = []
    for item in evidence:
        if not item['ok']:
            continue
        basis.append(f"{item['tool']} · {tr('observed', language)}: {item['observed_at']} UTC · "
                     f"{item['status']} · {item['cloud']}")
        for version in item['provenance']['versions']:
            basis.append(f"{version['role']} · v{version['id']} · {version['source_path']} · "
                         f"sha256={version['file_sha256']} · {tr('imported', language)}={version['imported_at']} UTC")
        basis.append(tr('recorded_only', language))
        for run in item['provenance']['latest_attempts']:
            basis.append(f"{tr('recorded_sync', language)}: {run['role']} · {run['outcome']} · {run['finished_at']} UTC")
        basis.append(f"basis={item['basis']}")
        basis.extend(item['warnings'])
        basis.append('')
    text = '\n'.join([tr('c_details_title', language), ''] + lines + [tr('c_basis_title', language), ''] + basis +
                     [tr('c_json_title', language), json.dumps(result, ensure_ascii=False, indent=2)])
    return text if len(text) <= 200_000 else text[:200_000] + '\n[DISPLAY TRUNCATED]'


SUMMARY_ITEMS = 5     # stock rows / shortages per chat answer; Evidence holds every returned row
LIST_ITEMS = 8        # candidates, BOM rows and alerts per chat answer
# Tools whose answer depends on the BOM source too: stock alerts include BOM coverage, data_status reports both.
BOM_TOOLS = ('get_bom', 'estimate_requirements', 'search_products', 'get_stock_alerts', 'data_status')
SYNC_OK = ('IMPORTED', 'UNCHANGED')


def _status_lines(evidence, language):
    """One data-status line for the whole answer (never repeated per tool), plus failed-sync warnings."""
    ok = [item for item in evidence if item['ok']]
    if not ok:
        return [tr('c_status', language).format(asof=tr('c_asof_unknown', language))]
    provenance = ok[0]['provenance']
    roles = ['stock'] + (['bom'] if any(item['tool'] in BOM_TOOLS for item in ok) else [])
    versions = {v['role']: v for v in provenance['versions']}
    asof = ' · '.join(tr('c_asof', language).format(role=readable.label(readable.ROLE, role, language),
                                                    time=readable.local_time(versions[role]['imported_at']))
                      for role in roles if role in versions) or tr('c_asof_unknown', language)
    lines = [tr('c_status', language).format(asof=asof)]
    for role in roles:
        if role not in versions:
            lines.append(tr('c_never', language).format(role=readable.label(readable.ROLE, role, language)))
    for run in provenance['latest_attempts']:
        if run['role'] in roles and run['outcome'] not in SYNC_OK:
            key = 'c_stale_unavailable' if run['outcome'] == 'UNAVAILABLE' else 'c_stale'
            lines.append(tr(key, language).format(role=readable.label(readable.ROLE, run['role'], language),
                                                  time=readable.local_time(run['finished_at'])))
    return lines


def _num(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _value(value, language):
    return tr('unknown', language) if value is None else _num(value)


def _stock_qty(row, language):
    status = row.get('recorded_qty_status')
    if status == 'BLANK' or row['quantity'] is None:
        return tr('c_blank', language)
    if status != 'VALID':
        return tr('c_text_qty', language).format(raw=row['quantity'])
    return _num(row['quantity'])


def _more(lines, shown, loaded, total, language, hint=None):
    """Nothing is cut silently. 'Showing X of Y; the rest is in Details' only when Details really holds all Y;
    when the tool itself returned fewer rows than exist (its read limit), say so and give the narrowing hint."""
    if loaded < total:
        text = (tr('c_shown_only', language).format(shown=shown) + ' ' if shown < loaded else '')
        text += tr('c_capped', language).format(loaded=loaded, total=total)
        lines.append(text + (' ' + tr(hint, language) if hint else ''))
        return True
    if shown < total:
        lines.append(tr('c_shown', language).format(shown=shown, total=total))
        return True
    return False


def _take(rows, limit):
    return rows if limit is None else rows[:limit]


def _answer(item, language, limit):
    """(lines, shortened) for one successful tool observation. limit=None lists every returned row (details)."""
    name, data = item['tool'], item['data']
    full = limit is None
    cap = None if full else LIST_ITEMS
    lines, cut = [], False
    if name in ('search_materials', 'search_products'):
        total, rows = data['total'], data['candidates']
        if not total:
            lines.append(tr('no_results', language))
            return lines, False
        key = ('c_candidates' if name == 'search_materials' else 'c_products') if total > 1 else 'c_one_candidate'
        lines.append(tr(key, language).format(total=total))
        for row in _take(rows, cap):
            label = row.get('material_id') or row.get('display_name') or row['sheet']
            lines.append(f"• {label} · Sheet {row['sheet']!r}")
        cut = _more(lines, len(_take(rows, cap)), len(rows), total, language, 'c_narrow_search')
        if total > 1:
            lines.append(tr('select', language))
    elif name == 'get_stock':
        rows = data['rows']
        if not data['found']:
            lines.append(tr('c_not_found', language).format(id=data['material_id']))
            return lines, False
        duplicated = max(r['duplicate_rows_in_sheet'] for r in rows)
        sheets = {r['source']['sheet'] for r in rows}
        if duplicated > 1:
            lines.append(tr('c_duplicate', language).format(id=data['material_id'], count=len(rows)))
        elif len(sheets) > 1:
            lines.append(tr('c_sheets', language).format(id=data['material_id'], count=len(sheets)))
        for row in _take(rows, limit):
            description = row['description'] if row['description'] not in (None, '') else '—'
            lines.append(f"• {row['code']} · {description}")
            place = [f"{tr('raw', language)}{'：' if language == 'zh' else ': '}{_stock_qty(row, language)}"]
            if row.get('rack') not in (None, '') or row.get('level') not in (None, ''):
                place.append(tr('c_location', language).format(rack=_value(row.get('rack'), language),
                                                               level=_value(row.get('level'), language)))
            place.append(tr('c_source_row', language).format(sheet=row['source']['sheet'], row=row['source']['row']))
            if full:
                place.append(f"{row['match_status']} · quantity_type={row['quantity_type']}")
            lines.append('  ' + ' · '.join(place))
        cut = _more(lines, len(_take(rows, limit)), len(rows), len(rows), language)
    elif name == 'get_bom':
        rows = data['materials']
        lines.append(tr('c_bom', language).format(product=data['display_name'], count=len(rows)))
        for row in _take(rows, cap):
            qty = (tr('c_bom_qty_blank', language) if row['quantity'] is None else
                   tr('c_bom_qty', language).format(qty=_num(row['quantity'])))
            lines.append(f"• {row['code']} · {qty} · {row['description'] or '—'}" +
                         (f" · row={row['source']['row']}" if full else ''))
        cut = _more(lines, len(_take(rows, cap)), len(rows), len(rows), language)
    elif name == 'estimate_requirements':
        lines, cut = _estimate(data['calculation'], language, limit)
    elif name == 'material_history':
        lines, cut = _history(data, language, limit)
    elif name == 'material_analysis':
        lines, cut = _analysis(data, language, limit)
    elif name == 'get_stock_alerts':
        lines, cut = _alerts(data, language, limit)
    elif name == 'data_status':
        for role, state in data['recorded_states'].items():
            lines.append('• ' + tr('c_role_state', language).format(
                role=readable.label(readable.ROLE, role, language),
                state=SYNC_STATES.get(state['state'], (state['state'],) * 3)[LANGUAGES.index(language)],
                checked=readable.local_time(state['last_checked']) or '—',
                imported=readable.local_time(state['data_imported']) or '—'))
        lines.append(tr('recorded_only', language))
    return lines, cut


def _estimate(calc, language, limit):
    rows = calc['rows']
    by = {category: [r for r in rows if r['category'] == category] for category in ('SHORTAGE', 'EXCEPTION', 'ENOUGH')}
    product = calc['product']['display_name']
    lines = [tr('c_estimate', language).format(product=product, count=calc['production_count'],
                                              short=len(by['SHORTAGE']), exceptions=len(by['EXCEPTION']),
                                              enough=len(by['ENOUGH']))]
    cut = False
    describe = lambda r: f"{r['bom']['code']} · {r['bom']['description'] or '—'}"
    if limit is None:
        for r in rows:
            lines.append(f"• {describe(r)} · {CATEGORY[r['category']][LANGUAGES.index(language)]} · "
                         f"{tr('required', language)} {_value(r['required'], language)} · "
                         f"{tr('shortage', language)} {_value(r['shortage'], language)}" +
                         (' · ' + ' / '.join(r['exceptions']) if r['exceptions'] else ''))
            if r['stock_assumed']:
                lines.append('  ' + tr('assumed', language))
            lines.extend('  ' + issue for issue in r['issues'])
    else:
        if by['SHORTAGE']:
            lines.append(tr('c_short_title', language))
            for r in by['SHORTAGE'][:limit]:
                lines.append(f"• {describe(r)}: {tr('required', language)} {_value(r['required'], language)} · "
                             f"{tr('shortage', language)} {_value(r['shortage'], language)}")
            cut = _more(lines, min(limit, len(by['SHORTAGE'])), len(by['SHORTAGE']), len(by['SHORTAGE']), language)
        else:
            lines.append(tr('c_no_short', language))
        if by['EXCEPTION']:
            lines.append(tr('c_exc_title', language))
            for r in by['EXCEPTION'][:limit]:
                reasons = ' / '.join(EXCEPTIONS.get(x, (x,) * 3)[LANGUAGES.index(language)] for x in r['exceptions'])
                lines.append(f"• {describe(r)}: {reasons}")
            cut = _more(lines, min(limit, len(by['EXCEPTION'])), len(by['EXCEPTION']), len(by['EXCEPTION']),
                        language) or cut
    lines.append(tr('c_estimate_note', language))
    return lines, cut


def _history(data, language, limit):
    coverage = data['coverage']
    lines = [tr('c_history', language).format(id=data['material_key'], days=coverage['days'],
                                              changes=data['total_changes'], rows=data['total_rows'])]
    if coverage['first_snapshot_at'] is None:
        lines.append(tr('c_history_none', language))
    elif not coverage['covers_full_window']:
        lines.append(tr('c_history_short', language).format(time=readable.local_time(coverage['first_snapshot_at']),
                                                             days=coverage['days']))
    if coverage['source_switches']:
        lines.append(tr('c_history_switch', language).format(count=len(coverage['source_switches'])))
    if data['rows'] and limit is not None:
        lines += _latest_observation(data['rows'], language, limit)
    changes = _take(data['changes'], limit)  # newest first
    for change in changes:
        before = _change_side(change['before_status'], change['before_value'], change['before_raw'], language)
        after = _change_side(change['after_status'], change['after_value'], change['after_raw'], language)
        lines.append(f"• {readable.local_time(change['after_at'])} · "
                     f"{readable.label(readable.CHANGE, change['change_type'], language)}: {before} → {after}" +
                     (f" · {change['note']}" if limit is None else ''))
    cut = _more(lines, len(changes), len(data['changes']), data['total_changes'], language, 'c_narrow_history')
    if limit is None:
        _more(lines, len(data['rows']), len(data['rows']), data['total_rows'], language, 'c_narrow_history')
        for row in data['rows']:
            value = _history_qty(row, language) if row['kind'] == 'RECORD' else 'UNKNOWN — ' + row['kind']
            lines.append(f"  {row['observed_at']} UTC · {row['sheet']!r} · {value} · {row['status']} · "
                         f"{tr('reference', language)}={row['reference']}")
        lines.extend('  ' + note for note in coverage['notes'])
    return lines, cut


def _latest_observation(rows, language, limit):
    """Rows are newest first and one snapshot may hold several Sheet rows. The newest snapshot is described as it
    is - found, not found, or cleaned up (unknown) - never skipped in favour of an older number. When it holds no
    record, the last recorded quantities follow, with their own time and, if different, their source file."""
    newest = [r for r in rows if r['snapshot_id'] == rows[0]['snapshot_id']]
    when = readable.local_time(rows[0]['observed_at'])
    found = [r for r in newest if r['kind'] == 'RECORD']
    if found:
        return [tr('c_latest', language).format(time=when, qty=_history_qty(r, language), sheet=r['sheet'])
                for r in found[:limit]]
    lines = [tr('c_latest_pruned' if newest[0]['kind'] == 'NOT_RETAINED' else 'c_latest_absent',
                language).format(time=when)]
    earlier = [r for r in rows if r['kind'] == 'RECORD']
    if earlier:
        for r in [r for r in earlier if r['snapshot_id'] == earlier[0]['snapshot_id']][:limit]:
            line = tr('c_last_qty', language).format(time=readable.local_time(r['observed_at']),
                                                     qty=_history_qty(r, language), sheet=r['sheet'])
            if r['source_path'] != rows[0]['source_path']:
                line += tr('c_other_source', language).format(file=readable.file_name(r['source_path']))
            lines.append(line)
    return lines


def _change_side(status, value, raw, language):
    if status is None:
        return '—'
    if status == 'VALID' and value is not None:
        return _num(value)
    if status == 'BLANK':
        return tr('c_blank', language)
    return tr('c_text_qty', language).format(raw=' | '.join('—' if x is None else _num(x) for x in raw) or '—')


def _history_qty(row, language):
    if row['status'] == 'BLANK' or row['quantity'] is None:
        return tr('c_blank', language)
    if row['status'] != 'VALID':
        return tr('c_text_qty', language).format(raw=row['quantity'])
    return _num(row['quantity'])


def _analysis(data, language, limit):
    lines = []
    materials = data['materials']
    for row in _take(materials, limit):
        lines.append(tr('c_analysis', language).format(
            id=row['material_key'], sheet=row['sheet'], days=data['days'], movement_label=tr('movement', language),
            movement=_value(row['movement'], language), net_label=tr('net', language),
            net=_value(row['net_change'], language), span=_value(row['window_span_days'], language)))
        signals = [SIGNALS.get(s, (s,) * 3)[LANGUAGES.index(language)] for s in row['signals']]
        if signals:
            lines.append('  ' + ' · '.join(signals) + (f" ({' / '.join(row['signals'])})" if limit is None else ''))
    if not materials:
        lines.append(tr('no_results', language))
    cut = _more(lines, len(_take(materials, limit)), len(materials), len(materials), language)
    lines.append(tr('c_observed', language))
    return lines, cut


def _alerts(data, language, limit):
    assessment, recorded = data['assessment'], data['recorded']
    if assessment == 'UPGRADE_REQUIRED':
        return [tr('c_alerts_upgrade', language)] + ([f"({assessment})"] if limit is None else []), False
    if assessment == 'NOT_EVALUATED':
        return [tr('c_alerts_not_evaluated', language)] + ([f"({assessment})"] if limit is None else []), False
    completed = recorded.get('latest_completed') or {}
    lines = [tr('c_alerts', language).format(time=readable.local_time(completed.get('finished_at')) or '—')]
    counts = recorded['active_counts']
    for kind in readable.ALERT:
        lines.append('• ' + tr('c_alert_count', language).format(label=readable.label(readable.ALERT, kind, language),
                                                                 count=counts.get(kind, 0)))
    lines.append(tr('counts', language))
    order = {kind: i for i, kind in enumerate(readable.ALERT)}
    rows = sorted(recorded['rows'], key=lambda r: order.get(r['alert_type'], len(order)))
    cap = None if limit is None else LIST_ITEMS
    for row in _take(rows, cap):
        lines.append(f"• {readable.label(readable.ALERT, row['alert_type'], language)} · "
                     f"{row['material_key'] or '—'} · Sheet {row['stock_sheet']!r}" +
                     (f" · {row['alert_type']}/{row['subtype']}" if limit is None else ''))
    cut = _more(lines, len(_take(rows, cap)), len(rows), recorded['total_rows'], language, 'c_narrow_alerts')
    return lines, cut


CATEGORY = {'SHORTAGE': ('short', '缺料', 'kurang'), 'EXCEPTION': ('exception', '异常', 'pengecualian'),
            'ENOUGH': ('enough', '足够', 'mencukupi')}
EXCEPTIONS = {
    'INVALID_MATERIAL_ID': ('invalid Material ID', '材料编号无效', 'ID bahan tidak sah'),
    'CODE_TYPE_MISMATCH': ('ID stored as a number on one side', '编号格式不一致（数字/文本）',
                           'ID disimpan sebagai nombor di satu pihak'),
    'INVALID_BOM_QTY': ('invalid BOM quantity', 'BOM 用量无效', 'kuantiti BOM tidak sah'),
    'DUPLICATE_BOM': ('listed more than once in the BOM', 'BOM 中重复出现', 'tersenarai lebih sekali dalam BOM'),
    'DUPLICATE_STOCK': ('several stock records, not merged', '库存有多条记录，未合并',
                        'beberapa rekod stok, tidak digabung'),
    'STOCK_NOT_FOUND': ('not found in the stock list (estimate assumes 0)', '库存表未找到（试算按 0 计）',
                        'tiada dalam senarai stok (anggaran menganggap 0)'),
    'BLANK_STOCK': ('stock not recorded yet (estimate assumes 0)', '库存尚未登记（试算按 0 计）',
                    'stok belum direkod (anggaran menganggap 0)'),
    'INVALID_STOCK': ('stock quantity to be confirmed (estimate assumes 0)', '库存数量待确认（试算按 0 计）',
                      'kuantiti stok perlu disahkan (anggaran menganggap 0)'),
}
SIGNALS = {
    'INSUFFICIENT_HISTORY': ('history is insufficient: no trend conclusion', '历史不足，无法得出趋势结论',
                             'sejarah tidak mencukupi: tiada kesimpulan trend'),
    'LOW_OBSERVED_MOVEMENT': ('little observed movement', '观察到的变动很少', 'pergerakan diperhatikan sedikit'),
    'LONG_UNCHANGED_OBSERVATIONS': ('unchanged for a long time', '长时间没有变化', 'tidak berubah untuk tempoh lama'),
    'POSITIVE_UNCHANGED_REVIEW': ('stock recorded but unchanged for long: worth a review', '有库存但长期未变，建议复核',
                                  'stok direkod tetapi lama tidak berubah: wajar disemak'),
    'LARGE_OBSERVED_CHANGE': ('a large single observed change', '有一次较大的观察变化', 'satu perubahan besar diperhatikan'),
    'FROM_ZERO_PERCENT_UNKNOWN': ('started from 0: percentage unknown', '从 0 开始，百分比未知',
                                  'bermula dari 0: peratus tidak diketahui'),
    'LAST_OBSERVED_ZERO': ('last record is 0', '最近一次记录为 0', 'rekod terakhir ialah 0'),
    'INCOMPARABLE_GAP': ('some records are not comparable', '部分记录之间不可比较', 'sesetengah rekod tidak boleh dibanding'),
    'HISTORY_PRUNED': ('part of the history was removed by cleanup', '部分历史已被清理',
                       'sebahagian sejarah dibuang oleh pembersihan'),
    'OTHER_SOURCE_HISTORY': ('includes history from another source file', '包含其他数据源的历史',
                             'termasuk sejarah daripada fail sumber lain'),
}
SYNC_STATES = {
    'Local File Checked': ('last sync succeeded', '上次同步成功', 'penyegerakan terakhir berjaya'),
    'Sync Failed': ('sync failed — earlier data in use', '同步失败——正在使用之前的数据',
                    'penyegerakan gagal — data terdahulu digunakan'),
    'Source File Unavailable': ('source file unavailable — earlier data in use', '源文件不可用——正在使用之前的数据',
                           'fail sumber tidak tersedia — data terdahulu digunakan'),
    'Source Changed — Refresh Needed': ('source changed — refresh needed', '源文件已变化——需要刷新',
                                        'sumber berubah — perlu disegarkan'),
    'Not Synced': ('never synchronised', '尚未同步', 'belum disegerakkan'),
}
