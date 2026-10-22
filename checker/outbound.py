"""Minimal, versioned disclosure policy for model routing. Numeric evidence stays in the host."""
from __future__ import annotations

import json
import re

from .agent import ProviderFailure, SYSTEM
from .agent_tools import _validate, encoded, specifications

POLICY = 'inventory-routing-v2'
DISCLOSURE = ('Sends your question, fixed tools and requested arguments (including production quantity/range), '
              'candidate Material IDs/product Sheets and tool success/error/selection status to DeepSeek. '
              'Stock/BOM result quantities, descriptions, rack/level, '
              'local paths, source hashes and full database/workbook contents are not included. '
              'Also checks API account balance through the same provider; no inventory data is sent in that check. '
              'Questions may themselves contain company information. Cloud Not Verified.')
_SENSITIVE = re.compile(r'[a-z]:[\\/]|\\\\|file://|/(?:Users|home|tmp|var)/|'
                        r'\b(?:api[_ -]?key|password|token|secret)\s*[:=]|'
                        r'\bsk-[a-z0-9_-]{8,}|[\w.+-]+@[\w.-]+\.[a-z]{2,}', re.I)


def safe_text(value, limit=4000):
    if type(value) is not str or len(value) > limit or '\x00' in value or _SENSITIVE.search(value):
        raise ProviderFailure('OUTBOUND_DATA_REFUSED')
    return value


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def _arguments(name, args):
    _validate(name, args)
    for value in args.values():
        if isinstance(value, str):
            safe_text(value, 200)
    return args


def _outcome(result):
    """Positive allowlist, never generic recursion/redaction of a full evidence envelope."""
    name = result['tool']
    if name not in {s['name'] for s in specifications()} or type(result['ok']) is not bool:
        raise ProviderFailure('OUTBOUND_DATA_REFUSED')
    output = {'tool': name, 'ok': result['ok'], 'status': 'UNVERIFIED', 'cloud': 'NOT_VERIFIED'}
    if not result['ok']:
        code = result['error']['code']
        if type(code) is not str or not re.fullmatch('[A-Z_]{1,64}', code):
            raise ProviderFailure('OUTBOUND_DATA_REFUSED')
        output['error'] = {'code': code}
    elif name in ('search_materials', 'search_products'):
        data = result['data']
        fields = ('sheet', 'material_id') if name == 'search_materials' else ('sheet',)
        if len(data['candidates']) > 200 or type(data['total']) is not int:
            raise ProviderFailure('OUTBOUND_DATA_REFUSED')
        output['selection'] = {'candidates': [{k: safe_text(c[k], 200) for k in fields}
                                               for c in data['candidates']],
                               'total': data['total'], 'truncated': bool(data['truncated'])}
    else:
        output['evidence_available_in_host'] = True
    return output


def project(messages, tools):
    """Preview exactly the messages allowed out, with no key access or network activity.

    This is not general DLP: arbitrary secrets in free text cannot reliably be detected. The host must
    obtain informed consent for the question/candidate scope before enabling actual transmission.
    """
    try:
        if tools != specifications() or not 2 <= len(messages) <= 32:
            raise ValueError('Invalid context')
        if messages[0] != {'role': 'system', 'content': SYSTEM} or messages[1]['role'] != 'user':
            raise ValueError('Invalid system/question')
        result = [{'role': 'system', 'content': SYSTEM + ' Numeric evidence is retained locally. '
                   'Tool outcomes omit quantities and descriptions. When evidence is available, finish '
                   'without inventing values; the host will render it.'},
                  {'role': 'user', 'content': safe_text(messages[1]['content'])}]
        for message in messages[2:]:
            if message['role'] == 'assistant':
                calls = message['tool_calls']
                if not 1 <= len(calls) <= 4:
                    raise ValueError('Invalid calls')
                result.append({'role': 'assistant', 'content': None, 'tool_calls': [
                    {'id': safe_text(c['id'], 100), 'type': 'function', 'function': {
                        'name': c['name'], 'arguments': encoded(_arguments(c['name'], c['arguments']))}}
                    for c in calls]})
            elif message['role'] == 'tool':
                result.append({'role': 'tool', 'tool_call_id': safe_text(message['tool_call_id'], 100),
                               'content': encoded(_outcome(strict_json(message['content'])))})
            else:
                raise ValueError('Unexpected role')
        return result
    except ProviderFailure:
        raise
    except Exception:
        raise ProviderFailure('OUTBOUND_DATA_REFUSED') from None
