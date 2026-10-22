"""Deterministic account/resource notices for the future chat host. Never estimates tokens remaining."""
from __future__ import annotations

from datetime import datetime, timezone
import copy
from decimal import Decimal
import re
import threading

BALANCE_INTERVAL = 300  # seconds; applies to failed checks too, avoiding retry storms
TEXT = {
    'LOW_BALANCE': {
        'zh': '部分币种的 API 余额偏低，请检查账户余额；这不是剩余 Token 数量。',
        'en': 'An API currency balance is low. Check your account; this is not a remaining-token count.',
        'ms': 'Baki API bagi mata wang tertentu rendah. Semak akaun; ini bukan jumlah token yang tinggal.'},
    'QUOTA_EXHAUSTED': {
        'zh': 'API 账户余额不足，AI 对话暂时不可用。补充额度后重新检查；本地库存功能仍可使用。',
        'en': 'API balance is insufficient. AI chat is unavailable until credit is restored and rechecked. Local stock tools still work.',
        'ms': 'Baki API tidak mencukupi. Sembang AI tidak tersedia sehingga kredit ditambah dan disemak semula. Fungsi stok tempatan masih boleh digunakan.'},
    'QUOTA_UNKNOWN': {
        'zh': '暂时无法确认 API 余额，剩余额度未知。',
        'en': 'API balance could not be verified. Remaining credit is unknown.',
        'ms': 'Baki API tidak dapat disahkan. Baki kredit tidak diketahui.'},
    'SESSION_LIMIT_NEAR': {
        'zh': '即将达到本程序的会话请求上限；这不是账户 Token 已用完。',
        'en': 'This application session is nearing its request limit; this is not account token exhaustion.',
        'ms': 'Sesi aplikasi menghampiri had permintaannya; ini tidak bermaksud token akaun telah habis.'},
    'SESSION_LIMIT_REACHED': {
        'zh': '已达到本程序的会话请求上限，请重新确认会话授权。',
        'en': 'The application session request limit was reached. Renew session consent to continue.',
        'ms': 'Had permintaan sesi aplikasi telah dicapai. Perbaharui persetujuan sesi untuk meneruskan.'},
    'OUTPUT_LIMIT_REACHED': {
        'zh': '本次回答达到输出长度上限，未使用不完整回答。请缩小问题范围；这不表示账户额度用完。',
        'en': 'This reply hit its output limit and was discarded. Narrow the question; this does not mean account credit ran out.',
        'ms': 'Jawapan mencapai had output dan dibuang. Kecilkan skop soalan; ini tidak bermaksud kredit akaun habis.'},
}


def notice_text(code, language='en'):
    return TEXT[code][language]  # host supplies the M4E-selected reply language


def amount(text):
    if type(text) is not str or not re.fullmatch(r'-?\d{1,12}(?:\.\d{1,8})?', text):
        raise ValueError('Invalid balance amount.')
    return Decimal(text)


class QuotaMonitor:
    def __init__(self, *, usd='1.00', cny='5.00'):
        self.thresholds = {'USD': amount(usd), 'CNY': amount(cny)}
        if any(v < 0 for v in self.thresholds.values()):
            raise ValueError('Invalid low-balance threshold.')
        self._lock = threading.Lock()
        self._active, self._pending = {}, {}
        self._balance, self._checked_at, self._checked_tick = None, None, None
        self._usage = None

    def _notice(self, code, severity='warning'):
        value = {'code': code, 'severity': severity}
        if code not in self._active:
            self._pending[code] = value
        self._active[code] = value

    def _clear(self, *codes):
        for code in codes:
            self._active.pop(code, None)
            self._pending.pop(code, None)

    def due(self, tick):
        with self._lock:
            return self._checked_tick is None or tick - self._checked_tick >= BALANCE_INTERVAL

    def request_refresh(self):
        with self._lock:
            self._checked_tick = None  # retain the labelled last observation, never pretend it was rechecked

    def is_exhausted(self):
        with self._lock:
            return 'QUOTA_EXHAUSTED' in self._active

    def balance(self, data, tick):
        if type(data.get('is_available')) is not bool or type(data.get('balance_infos')) is not list:
            raise ValueError('Invalid balance response.')
        infos = data['balance_infos']
        if not 1 <= len(infos) <= 2 or len({i['currency'] for i in infos}) != len(infos):
            raise ValueError('Invalid balance currencies.')
        rows = []
        for info in infos:
            currency, total = info['currency'], amount(info['total_balance'])
            if currency not in self.thresholds:
                raise ValueError('Unsupported currency.')
            rows.append({'currency': currency, 'balance': str(total),
                         'low_threshold': str(self.thresholds[currency]),
                         'low': total <= self.thresholds[currency]})
        with self._lock:
            self._balance = {'available': data['is_available'], 'currencies': rows}
            self._checked_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
            self._checked_tick = tick
            self._clear('QUOTA_UNKNOWN')
            if not data['is_available']:
                self._clear('LOW_BALANCE')
                self._notice('QUOTA_EXHAUSTED', 'error')
            else:
                self._clear('QUOTA_EXHAUSTED')
                if any(r['low'] for r in rows):
                    self._notice('LOW_BALANCE')
                else:
                    self._clear('LOW_BALANCE')

    def unknown(self, tick):
        with self._lock:
            self._balance = None
            self._checked_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
            self._checked_tick = tick
            # A 402 remains an observed exhaustion until a successful balance check supersedes it.
            self._clear('LOW_BALANCE')
            self._notice('QUOTA_UNKNOWN')

    def exhausted(self, tick):
        with self._lock:
            self._balance = None  # invalidate any older positive balance observation immediately
            self._checked_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
            self._checked_tick = tick
            self._clear('LOW_BALANCE', 'QUOTA_UNKNOWN')
            self._notice('QUOTA_EXHAUSTED', 'error')

    def requests(self, used, limit):
        with self._lock:
            if used >= limit:
                self._clear('SESSION_LIMIT_NEAR')
                self._notice('SESSION_LIMIT_REACHED')
            elif used * 5 >= limit * 4:
                self._notice('SESSION_LIMIT_NEAR')

    def output_limit(self):
        with self._lock:
            self._notice('OUTPUT_LIMIT_REACHED')

    def usage(self, value):
        usage = None
        if isinstance(value, dict):
            keys = ('prompt_tokens', 'completion_tokens', 'total_tokens')
            if all(type(value.get(k)) is int and 0 <= value[k] <= 10**9 for k in keys) and (
                    value['total_tokens'] == value['prompt_tokens'] + value['completion_tokens']):
                usage = {k: value[k] for k in keys}
        with self._lock:
            self._usage = usage  # reported last-request usage only, never a remaining-token estimate
            self._clear('OUTPUT_LIMIT_REACHED')

    def status(self, tick):
        with self._lock:
            return copy.deepcopy({'balance': self._balance, 'checked_at': self._checked_at,
                                  'balance_check_due': self._checked_tick is None or
                                  tick - self._checked_tick >= BALANCE_INTERVAL,
                                  'last_request_usage': self._usage,
                                  'remaining_tokens': None, 'notices': list(self._active.values())})

    def take_notifications(self):
        with self._lock:
            result = list(self._pending.values())
            self._pending.clear()
            return result
