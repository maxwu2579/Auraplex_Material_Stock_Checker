"""M4D DeepSeek adapter. Explicit session consent, minimal disclosure, no retries/fallbacks.

No request is made at import, construction or preview. Use from a host worker, not the Tk thread.
"""
from __future__ import annotations

from dataclasses import dataclass
import http.client
import math
import re
import socket
import ssl
import threading
import time

from .agent import ModelReply, ProviderFailure, ToolCall
from .agent_tools import _validate, encoded, specifications
from .credentials import CredentialError, WindowsKeyStore, validate_key
from .outbound import DISCLOSURE, POLICY, project, safe_text, strict_json
from .quota import QuotaMonitor, amount

HOST, ENDPOINT = 'api.deepseek.com', '/chat/completions'
MAX_REQUEST, MAX_RESPONSE = 65_536, 262_144


@dataclass(frozen=True)
class ProviderConfig:
    model: str = 'deepseek-flash'
    max_output_tokens: int = 1024
    max_requests: int = 10  # attempted requests per explicit outbound-consent session, including failures
    low_balance_usd: str = '1.00'
    low_balance_cny: str = '5.00'  # independent currency thresholds; no FX conversion

    def __post_init__(self):
        if (type(self.model) is not str or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}', self.model) or
                type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 2048 or
                type(self.max_requests) is not int or not 1 <= self.max_requests <= 20):
            raise ValueError('Invalid provider limits.')
        if amount(self.low_balance_usd) < 0 or amount(self.low_balance_cny) < 0:
            raise ValueError('Invalid balance thresholds.')


class _Cancellation:
    def __init__(self, caller, revoked):
        self.caller, self.revoked = caller, revoked

    def is_set(self):
        return self.caller.is_set() or self.revoked.is_set()


class HTTPSJSONTransport:
    """Fixed HTTPS endpoint with certificate checking; never follows redirects or environment proxies.

    Caller waits only to its deadline. Cancellation shuts down the socket. OS DNS resolution may outlive
    it: that worker keeps the single-flight lock, checks cancellation before sending, and no second
    worker starts on this transport until it exits. An already-sent request cannot be recalled/refunded.
    """
    def __init__(self):
        self._running = threading.Lock()

    def post(self, body, key, *, timeout, cancel):
        return self._request('POST', ENDPOINT, body, key, timeout=timeout, cancel=cancel)

    def get_balance(self, key, *, timeout, cancel):
        return self._request('GET', '/user/balance', None, key, timeout=timeout, cancel=cancel)

    def _request(self, method, path, body, key, *, timeout, cancel):
        if (method, path) not in (('POST', ENDPOINT), ('GET', '/user/balance')):
            raise ProviderFailure('OUTBOUND_DATA_REFUSED')
        if cancel.is_set():
            raise ProviderFailure('CANCELLED')
        if not self._running.acquire(blocking=False):
            raise ProviderFailure('PROVIDER_BUSY')
        deadline = time.monotonic() + timeout
        done, abandon = threading.Event(), threading.Event()
        outcome, active = [], []

        def check():
            if cancel.is_set() or abandon.is_set():
                raise ProviderFailure('CANCELLED')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderFailure('PROVIDER_TIMEOUT')
            return remaining

        def abort():
            abandon.set()
            sock = active[0].sock if active else None
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        def work():
            conn = None
            try:
                conn = http.client.HTTPSConnection(HOST, timeout=check(), context=ssl.create_default_context())
                active.append(conn)
                conn.connect()
                conn.sock.settimeout(check())
                conn.request(method, path, body=body, headers={'Authorization': 'Bearer ' + key,
                             'Content-Type': 'application/json', 'Accept': 'application/json',
                             'User-Agent': 'Auraplex-MaterialStockChecker/M4D'})
                check()
                response = conn.getresponse()
                raw = response.read(MAX_RESPONSE + 1)
                check()
                if len(raw) > MAX_RESPONSE:
                    raise ProviderFailure('PROVIDER_LIMIT')
                outcome.append((response.status, raw))
            except ProviderFailure as exc:
                outcome.append(exc)
            except (TimeoutError, socket.timeout):
                outcome.append(ProviderFailure('PROVIDER_TIMEOUT'))
            except Exception:
                outcome.append(ProviderFailure('PROVIDER_UNAVAILABLE'))
            finally:
                try:
                    if conn is not None:
                        try:
                            conn.close()
                        except Exception:
                            pass  # never print request/credential context from a worker cleanup error
                finally:
                    self._running.release()
                    done.set()

        worker = threading.Thread(target=work, name='MRC-DeepSeek-Request', daemon=True)
        try:
            worker.start()
        except BaseException:
            self._running.release()
            raise
        while not done.wait(min(.025, max(0, deadline - time.monotonic()))):
            if cancel.is_set():
                abort()
                raise ProviderFailure('CANCELLED')
            if time.monotonic() >= deadline:
                abort()
                raise ProviderFailure('PROVIDER_TIMEOUT')
        if cancel.is_set():
            raise ProviderFailure('CANCELLED')
        if time.monotonic() >= deadline:
            raise ProviderFailure('PROVIDER_TIMEOUT')
        if isinstance(outcome[0], ProviderFailure):
            raise outcome[0]
        return outcome[0]


class DeepSeekProvider:
    disclosure = DISCLOSURE
    policy = POLICY

    def __init__(self, *, config=None, key_store=None, transport=None):
        self.config = config or ProviderConfig()
        self._keys = key_store if key_store is not None else WindowsKeyStore()
        self._transport = transport if transport is not None else HTTPSJSONTransport()
        self._lock, self._running = threading.Lock(), threading.Lock()
        self._revoked = threading.Event()
        self._revoked.set()
        self._requests = 0
        self._quota = self._new_quota()

    def _new_quota(self):
        return QuotaMonitor(usd=self.config.low_balance_usd, cny=self.config.low_balance_cny)

    def authorize_outbound(self, *, policy, accepted):
        """HOST ONLY, after showing disclosure/preview. Independent of historical cache consent."""
        if policy != POLICY or type(accepted) is not bool:
            raise ValueError('Explicit consent to the current disclosure policy is required.')
        with self._lock:
            self._revoked.set()  # also cancel an older in-flight consent session
            self._revoked = threading.Event()
            self._requests = 0
            self._quota = self._new_quota()
            if not accepted:
                self._revoked.set()

    def revoke_outbound(self):
        with self._lock:
            self._revoked.set()
            self._quota = self._new_quota()

    def quota_status(self):
        """Local observation only. No network or key read; host renders in its selected reply language."""
        with self._lock:
            return self._quota.status(time.monotonic())

    def take_notifications(self):
        """Host-only drain: deterministic, deduplicated warnings, never AI-generated quota estimates."""
        with self._lock:
            return self._quota.take_notifications()

    def request_balance_refresh(self):
        """Host-only: next authorized chat request rechecks balance (does not reset request allowance)."""
        with self._lock:
            self._quota.request_refresh()

    @property
    def requests_used(self):
        with self._lock:
            return self._requests

    def preview(self, messages, tools):
        payload = {'model': self.config.model, 'messages': project(messages, tools),
                   'tools': [{'type': 'function', 'function': spec} for spec in specifications()],
                   'thinking': {'type': 'disabled'}, 'stream': False,
                   'max_tokens': self.config.max_output_tokens, 'tool_choice': 'auto'}
        body = encoded(payload).encode('utf-8')
        if len(body) > MAX_REQUEST:
            raise ProviderFailure('PROVIDER_LIMIT')
        return body

    def complete(self, messages, tools, *, timeout, cancel):
        if not self._running.acquire(blocking=False):
            raise ProviderFailure('PROVIDER_BUSY')
        try:
            return self._complete(messages, tools, timeout=timeout, cancel=cancel)
        finally:
            self._running.release()

    def _complete(self, messages, tools, *, timeout, cancel):
        if type(timeout) not in (float, int) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ProviderFailure('PROVIDER_LIMIT')
        deadline = time.monotonic() + timeout
        with self._lock:
            revoked = self._revoked
            quota = self._quota
            if revoked.is_set():
                raise ProviderFailure('OUTBOUND_CONSENT_REQUIRED')
        cancellation = _Cancellation(cancel, revoked)
        if cancellation.is_set():
            raise ProviderFailure('CANCELLED')
        body = self.preview(messages, tools)
        try:
            key = self._keys.load()
            if key is None:
                raise CredentialError('Missing credential')
            validate_key(key)
        except Exception:
            raise ProviderFailure('PROVIDER_AUTH_REQUIRED') from None
        with self._lock:
            if cancellation.is_set():
                raise ProviderFailure('CANCELLED')
            if self._requests >= self.config.max_requests:
                raise ProviderFailure('PROVIDER_LIMIT')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderFailure('PROVIDER_TIMEOUT')
        if quota.due(time.monotonic()):
            try:
                status, raw = self._transport.get_balance(key, timeout=min(1, remaining / 4), cancel=cancellation)
                if cancellation.is_set():
                    raise ProviderFailure('CANCELLED')
                if status != 200 or type(raw) is not bytes or len(raw) > MAX_RESPONSE:
                    raise ValueError('Balance unavailable')
                quota.balance(strict_json(raw.decode('utf-8')), time.monotonic())
            except Exception:
                quota.unknown(time.monotonic())  # never retain old success as a new balance check
        with self._lock:
            if cancellation.is_set():
                raise ProviderFailure('CANCELLED')
            if quota.is_exhausted():
                raise ProviderFailure('PROVIDER_QUOTA_EXHAUSTED')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderFailure('PROVIDER_TIMEOUT')
            self._requests += 1
            quota.requests(self._requests, self.config.max_requests)
        try:
            status, raw = self._transport.post(body, key, timeout=remaining, cancel=cancellation)
        except ProviderFailure:
            raise
        except Exception:
            raise ProviderFailure('PROVIDER_UNAVAILABLE') from None
        finally:
            key = None  # best effort only: Python strings/network buffers cannot guarantee zeroization
        if cancellation.is_set():
            raise ProviderFailure('CANCELLED')
        if time.monotonic() >= deadline:
            raise ProviderFailure('PROVIDER_TIMEOUT')
        code = {401: 'PROVIDER_AUTH_FAILED', 403: 'PROVIDER_AUTH_FAILED', 402: 'PROVIDER_QUOTA_EXHAUSTED',
                429: 'PROVIDER_RATE_LIMITED'}.get(status)
        if code or status != 200:
            if status == 402:
                quota.exhausted(time.monotonic())
            raise ProviderFailure(code or 'PROVIDER_UNAVAILABLE')
        try:
            if type(raw) is not bytes or len(raw) > MAX_RESPONSE:
                raise ValueError('Invalid body size')
            data = strict_json(raw.decode('utf-8'))
            quota.usage(data.get('usage'))
            choices = data['choices']
            if type(choices) is not list or len(choices) != 1:
                raise ValueError('Invalid choices')
            choice, calls = choices[0], []
            message = choice['message']
            if choice['finish_reason'] == 'length':
                quota.output_limit()
                raise ValueError('Output limit reached')
            if message['role'] != 'assistant' or choice['finish_reason'] not in ('stop', 'tool_calls'):
                raise ValueError('Incomplete reply')
            text = message.get('content')
            text = '' if text is None else text
            if type(text) is not str or len(text) > 8000:
                raise ValueError('Invalid text')
            raw_calls = message.get('tool_calls')
            raw_calls = [] if raw_calls is None else raw_calls
            if type(raw_calls) is not list or len(raw_calls) > 4:
                raise ValueError('Too many calls')
            if bool(raw_calls) != (choice['finish_reason'] == 'tool_calls'):
                raise ValueError('Inconsistent finish reason')
            for call in raw_calls:
                function = call['function']
                if call['type'] != 'function' or not safe_text(call['id'], 100):
                    raise ValueError('Invalid call')
                arguments = function['arguments']
                if type(arguments) is not str or len(arguments.encode('utf-8')) > 4096:
                    raise ValueError('Invalid arguments')
                arguments = strict_json(arguments)
                _validate(function['name'], arguments)
                calls.append(ToolCall(call['id'], function['name'], arguments))
            if len({c.id for c in calls}) != len(calls):
                raise ValueError('Duplicate call ID')
        except Exception:
            raise ProviderFailure('INVALID_PROVIDER_RESPONSE') from None
        if cancellation.is_set():
            raise ProviderFailure('CANCELLED')
        if time.monotonic() >= deadline:
            raise ProviderFailure('PROVIDER_TIMEOUT')
        return ModelReply(tuple(calls), text)


def create_provider(name='deepseek', **options):
    """Explicit factory. Unsupported/unavailable providers are never silently substituted."""
    if name != 'deepseek':
        raise ValueError('Unsupported AI provider.')
    return DeepSeekProvider(**options)
