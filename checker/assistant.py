"""M4E host controller. One worker, memory-only permissions, queued immutable observations; no Tk."""
from dataclasses import dataclass
import json
from pathlib import Path
import queue
import threading
import uuid

from .agent import Agent, ProviderFailure, SYSTEM
from .agent_tools import InventoryTools, specifications, encoded
from .assistant_language import error_text, tr
from .credentials import WindowsKeyStore
from .history import read_view
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

    Closing/Stop/source changes revoke both permissions. A cancelled worker must exit before another
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
            return True

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
            self._busy = True
            epoch, cancel = self._epoch, threading.Event()
            self._cancel = cancel

        def work():
            result = failure('REQUEST_FAILED')
            try:
                result = self._execute(action, payload, cancel)
                basis = result.get('basis')
                if basis and action in ('chat', 'local') and basis != self._authorized_basis:
                    result = failure('STALE_DATA')
                if basis and (self.tools is None or self.tools.basis() != basis):
                    result = failure('STALE_DATA')
            except (ProviderFailure, SessionFailure) as exc:
                result = failure(exc.code)
            except Exception:
                result = failure('KEY_FAILED' if action in ('save_key', 'delete_key') else 'DATABASE_READ_FAILED')
            finally:
                payload.clear()  # no key/question in the completion queue; Python cannot guarantee zeroization
                # Format bounded display strings on the worker, before taking the short publication lock.
                try:
                    reply = render(result, language)
                    evidence_text = json.dumps(result, ensure_ascii=False, indent=2)
                    if len(evidence_text) > 200_000:
                        evidence_text = evidence_text[:200_000] + '\n[DISPLAY TRUNCATED]'
                except Exception:
                    result = failure('DATABASE_READ_FAILED')
                    reply, evidence_text = error_text('DATABASE_READ_FAILED', language), ''
                with self._lock:
                    if not self.closed and epoch == self._epoch and not cancel.is_set():
                        if result.get('error') in ('DATABASE_READ_FAILED', 'STALE_DATA', 'STALE_SESSION'):
                            self._revoke()
                        self._publish_selections(result)
                        self.events.put(Delivery(epoch, action, language, result, reply, evidence_text))
                    elif action == 'authorize':
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
        if not self.authorized:
            return failure('CONSENT_REQUIRED')
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
    """Only deterministic local evidence is rendered; arbitrary model prose is never displayed."""
    if result.get('status') == 'FAILED':
        return error_text(result.get('error', 'REQUEST_FAILED'), language)
    if result.get('status') == 'AUTHORIZED':
        return tr('authorized', language)
    if result.get('status') in ('KEY_SAVED', 'KEY_DELETED'):
        return tr('saved_key' if result['status'] == 'KEY_SAVED' else 'deleted_key', language)
    lines = [tr('history', language)]
    format_value = lambda x: tr('unknown', language) if x is None else str(x)
    for item in result.get('evidence', ()):
        if not item['ok']:
            lines.append(error_text(item['error']['code'], language))
            continue
        name, data = item['tool'], item['data']
        lines.append(f"{name} · {tr('observed', language)}: {item['observed_at']}")
        if name in ('search_materials', 'search_products'):
            lines.append(tr('select', language) if data['total'] else tr('no_results', language))
            lines.append(f"{len(data['candidates'])} / {data['total']} · truncated={data['truncated']}")
        elif name == 'get_stock':
            if not data['found']:
                lines.append(tr('no_results', language))
            for row in data['rows'][:50]:
                value = tr('blank', language) if row['quantity'] is None else str(row['quantity'])
                source = row['source']
                lines += [f"{row['code']} · {row['description'] or ''}",
                          f"{tr('raw', language)}: {value} · {row['match_status']}",
                          f"{tr('source', language)}: {source['sheet']!r} / {source['row']} · Rack={row['rack']} · Level={row['level']}"]
        elif name == 'get_bom':
            lines.append(f"{data['sheet_name']!r} · {len(data['materials'])} BOM {tr('rows', language)} · UNVERIFIED_BOM")
            for row in data['materials'][:50]:
                qty = tr('blank', language) if row['quantity'] is None else str(row['quantity'])
                lines.append(f"{row['code']} · QTY={qty} · {row['description'] or ''} · row={row['source']['row']}")
        elif name == 'estimate_requirements':
            calc = data['calculation']
            lines.append(f"{calc['product']['sheet_name']!r} × {calc['production_count']} · ESTIMATED / UNVERIFIED")
            lines.append(str(calc['counts']))
            for row in calc['rows'][:50]:
                lines.append(f"{row['bom']['code']} · {row['category']} · {tr('required', language)}={format_value(row['required'])} · "
                             f"{tr('shortage', language)}={format_value(row['shortage'])} · {' / '.join(row['exceptions'])}")
                if row['stock_assumed']:
                    lines.append(tr('assumed', language))
        elif name == 'material_history':
            coverage = data['coverage']
            lines.append(f"{data['material_key']} · {coverage['days']} {tr('days', language)} · {data['total_rows']} {tr('rows', language)} / {data['total_changes']} {tr('changes', language)}")
            lines.append(f"{tr('coverage', language)}: {coverage['first_snapshot_at']} → {coverage['latest_snapshot_at']} · {tr('full', language)}={coverage['covers_full_window']}")
            for row in data['rows'][:50]:
                value = (tr('blank', language) if row['quantity'] is None else str(row['quantity'])) if row['kind'] == 'RECORD' else 'UNKNOWN — ' + row['kind']
                lines.append(f"{row['observed_at']} · {row['sheet']!r} · {value} · {row['status']} · {tr('reference', language)}={row['reference']}")
        elif name == 'material_analysis':
            lines.append(f"{data['days']} {tr('days', language)} · {data['snapshots_in_window']} {tr('snapshots', language)}")
            for row in data['materials'][:50]:
                lines.append(f"{row['material_key']} · {row['sheet']!r} · {tr('movement', language)}={format_value(row['movement'])} · {tr('net', language)}={format_value(row['net_change'])}")
                lines.append(' / '.join(row['signals']) + f" · {tr('span', language)}=" + str(row['window_span_days']))
        elif name == 'get_stock_alerts':
            lines.append(f"{data['assessment']} · {tr('rechecked', language)}")
            lines.append(tr('unknown', language) if data['assessment'] in ('NOT_EVALUATED', 'UPGRADE_REQUIRED') else
                         encoded(data['recorded']['active_counts']))
            lines.append(tr('counts', language))
        elif name == 'data_status':
            lines.append('NOT_PERFORMED')
            for role, state in data['recorded_states'].items():
                lines.append(f"{role} · {state['state']} · {state['last_checked']}")
        for version in item['provenance']['versions']:
            lines.append(f"{version['role']} · v{version['id']} · {version['source_path']} · "
                         f"sha256={version['file_sha256']} · {tr('imported', language)}={version['imported_at']}")
        lines.append(tr('recorded_only', language))
        for run in item['provenance']['latest_attempts']:
            lines.append(f"{tr('recorded_sync', language)}: {run['role']} · {run['outcome']} · {run['finished_at']}")
        shown = data.get('calculation', data)
        if (len(shown.get('rows', ())) > 50 or len(shown.get('materials', ())) > 50 or
                data.get('truncated') or (name == 'get_stock_alerts' and data['recorded']['total_rows'])):
            lines.append(tr('omitted', language))
    if not result.get('evidence'):
        lines.append(error_text(result.get('error') or 'NO_TOOL_EVIDENCE', language))
    lines.append(tr('caveat', language))
    text = '\n'.join(lines)
    return text if len(text) <= 80_000 else text[:80_000] + '\n' + tr('omitted', language)
