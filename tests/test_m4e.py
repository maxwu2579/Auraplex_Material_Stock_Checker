"""M4E synthetic/offline source checks. Never read a real workbook, database or Windows API key."""
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont
import unittest
from unittest.mock import patch

from checker.assistant import AssistantSession, render, render_details
from checker.assistant_language import ERRORS, TEXT, error_text, route, tr
from checker.assistant_ui import AssistantLauncher, TOOLS
from checker.providers import DeepSeekProvider
from checker.ui import CheckerApp
from tests.fixtures import stock_rows
from tests.test_m31 import Base, digest
from tests.test_m4d import FakeService, Keys, response


class FakeKeys(Keys):
    def save(self, value):
        self.value = value

    def delete(self):
        self.value = None


def wait_session(session, timeout=4):
    deadline = time.monotonic() + timeout
    while session.busy and time.monotonic() < deadline:
        time.sleep(.002)
    if session.busy:
        raise AssertionError('Assistant worker did not finish')
    return session.drain()


class LanguageTests(unittest.TestCase):
    def test_roadmap_language_acceptance_matrix_and_per_turn_switching(self):
        examples = [('帮我查 A123 的库存', 'zh'), ('How much stock is available for A123?', 'en'),
                    ('Berapa baki stok A123?', 'ms'), ('帮我 check A123 的库存', 'en'),
                    ('帮我查询 A123 的 baki stok', 'ms'), ('Please semak stok A123', 'en'),
                    ('请 check A123 的 baki stok', 'en'),
                    ('Please answer in Chinese: how much stock is available for A123?', 'zh'),
                    ('帮我查A123的库存', 'zh'), ('A123', 'zh')]
        previous = 'en'
        for question, expected in examples:
            with self.subTest(question=question):
                language, _ = route(question, previous)
                self.assertEqual(language, expected)
                previous = language

    def test_identifiers_units_source_labels_and_shared_tokens_are_not_english_evidence(self):
        for question in ('帮我查 BOM PCS KG A123', '帮我查 "How much stock" 的库存', '帮我查ＰＲＯＤＵＣＴ－１２的库存'):
            self.assertEqual(route(question)[0], 'zh')
        self.assertEqual(route('帮我查询 Special Product 的库存', protected=('Special Product',))[0], 'zh')
        self.assertEqual(route('How much is available?', protected=('A',))[0], 'en')
        self.assertEqual(route('status', previous='ms'), ('ms', True))
        self.assertEqual(route('A123', previous='en'), ('en', True))

    def test_explicit_requests_and_manual_selection(self):
        for question, expected in [('用英文回答：库存多少', 'en'), ('用马来文回答：库存多少', 'ms'), ('请用英文：库存多少', 'en'),
                                   ('Jawab dalam bahasa Cina: berapa baki stok?', 'zh')]:
            self.assertEqual(route(question)[0], expected)
        self.assertEqual(route('check stock', preferred='ms')[0], 'ms')
        self.assertEqual(route('reply in Chinese: check stock', preferred='ms')[0], 'zh')

    def test_all_warning_and_error_templates_have_three_nonempty_languages(self):
        for key in TEXT:
            for language in ('en', 'zh', 'ms'):
                self.assertTrue(tr(key, language))
        for code in (*ERRORS, 'CANCELLED', 'STALE_SESSION', 'UNKNOWN'):
            values = [error_text(code, language) for language in ('en', 'zh', 'ms')]
            self.assertEqual(len(set(values)), 3)


class SessionTests(Base):
    def setUp(self):
        super().setUp()
        self.sync('stock'); self.sync('bom')
        self.keys, self.service = FakeKeys(), FakeService()
        self.provider = DeepSeekProvider(key_store=self.keys, transport=self.service)
        self.session = AssistantSession(self.db, key_store=self.keys, provider=self.provider)

    def tearDown(self):
        self.session.close()
        wait_session(self.session)
        super().tearDown()

    def act(self, action, **payload):
        self.assertTrue(self.session.submit(action, **payload))
        events = wait_session(self.session)
        self.assertEqual(len(events), 1)
        return events[0].result

    def authorize(self):
        preview = self.act('preview_data')
        self.assertEqual(preview['status'], 'PREVIEW', preview)
        result = self.act('authorize', expected_basis=preview['basis'])
        self.assertEqual(result['status'], 'AUTHORIZED', result)
        return result

    def candidate(self, tool='search_materials', text='A'):
        result = self.act('local', tool=tool, text=text)
        return result['candidates'][0]['token']

    def test_defaults_and_denied_data_never_read_key_or_network(self):
        self.assertEqual(self.act('chat', question='check stock A')['error'], 'CONSENT_REQUIRED')
        self.assertEqual(self.act('local', tool='get_stock_alerts')['error'], 'CONSENT_REQUIRED')
        preview = self.act('preview_data')
        self.assertFalse(self.session.authorized)
        self.assertIn('Stock', preview['context']['stock_sheets'])
        self.assertEqual(self.keys.reads, 0)
        self.assertEqual(self.service.calls + self.service.balance_calls, [])

    def test_permission_basis_change_declines_and_data_status_is_never_fresh(self):
        preview = self.act('preview_data')
        self.sync('stock')  # even UNCHANGED invalidates the reviewed database basis
        result = self.act('authorize', expected_basis=preview['basis'])
        self.assertEqual(result['error'], 'STALE_DATA')
        self.assertFalse(self.session.authorized)
        self.authorize()
        status = self.act('local', tool='data_status')
        self.assertEqual(status['evidence'][0]['data']['session_source_verification'], 'NOT_PERFORMED')

    def test_stock_is_local_exact_candidate_required_and_separate_sheets_preserved(self):
        self.write_stock([], [('Stock', stock_rows([('A-1', 1), ('A-10', 10)])), (' Stock ', stock_rows([('A-1', 99)]))])
        self.sync('stock'); self.authorize()
        found = self.act('local', tool='search_materials', text='A-1')
        self.assertEqual(len(found['candidates']), 3)
        denied = self.act('local', tool='get_stock', candidate='invented')
        self.assertEqual(denied['error'], 'SELECTION_REQUIRED')
        selected = next(c for c in found['candidates'] if c['row']['sheet'] == ' Stock ')
        result = self.act('local', tool='get_stock', candidate=selected['token'])
        rows = result['evidence'][0]['data']['rows']
        self.assertEqual(len(rows), 1); self.assertEqual(rows[0]['quantity'], 99)
        self.assertEqual(rows[0]['source']['sheet'], ' Stock ')
        self.assertEqual(self.service.calls, [])

    def test_blank_invalid_duplicate_and_not_found_are_not_aggregated(self):
        self.write_stock([('A', None), ('B', '0+10'), ('D', 2), ('D', 3)])
        self.sync('stock'); self.authorize()
        for text, expected in [('A', [None]), ('B', ['0+10']), ('D', [2, 3])]:
            candidate = self.candidate(text=text)
            result = self.act('local', tool='get_stock', candidate=candidate)
            self.assertEqual([r['quantity'] for r in result['evidence'][0]['data']['rows']], expected)
            for language in ('en', 'zh', 'ms'):
                rendered = render(result, language)
                self.assertIn('UNVERIFIED', rendered)
                self.assertIn('Cloud Not Verified', rendered)
                self.assertNotIn('Local Sources Verified', rendered)
        empty = self.act('local', tool='search_materials', text='MISSING')
        self.assertEqual(empty['candidates'], [])
        self.assertEqual(self.act('local', tool='get_stock', candidate=candidate)['error'], 'SELECTION_REQUIRED')

    def test_bom_selection_quantity_validation_and_m2_parity_in_all_languages(self):
        self.authorize()
        token = self.candidate('search_products', 'PRODUCT')
        self.assertEqual(self.act('local', tool='get_stock', candidate=token)['error'], 'SELECTION_REQUIRED')
        for qty in (None, 0, -1, '2', 1.5, True, 1_000_001):
            result = self.act('local', tool='estimate_requirements', candidate=token, stock_sheet='Stock', quantity=qty)
            self.assertEqual(result['error'], 'INVALID_ARGUMENTS')
        self.assertEqual(self.act('local', tool='estimate_requirements', candidate=token, stock_sheet='invented', quantity=2)['error'], 'SELECTION_REQUIRED')
        result = self.act('local', tool='estimate_requirements', candidate=token, stock_sheet='Stock', quantity=3)
        calc = result['evidence'][0]['data']['calculation']
        self.assertEqual([r['required'] for r in calc['rows']], ['6', '3'])
        for language in ('en', 'zh', 'ms'):
            text = render(result, language)
            self.assertIn('PRODUCT-1', text)
            self.assertIn(tr('c_no_short', language), text)
            details = render_details(result, language)
            self.assertIn(f"{tr('required', language)} 6", details)
            self.assertIn(f"{tr('required', language)} 3", details)
        bom = self.act('local', tool='get_bom', candidate=token)
        self.assertEqual(len(bom['evidence'][0]['data']['materials']), 2)

    def test_history_analysis_and_unevaluated_alerts_use_existing_bounded_tools(self):
        self.authorize(); token = self.candidate()
        for name in ('material_history', 'material_analysis'):
            result = self.act('local', tool=name, candidate=token, days=30)
            self.assertEqual(result['status'], 'TOOL_RESULTS', result)
            self.assertIn('UNVERIFIED', render(result, 'ms'))
        result = self.act('local', tool='get_stock_alerts')
        self.assertEqual(result['evidence'][0]['data']['assessment'], 'NOT_EVALUATED')
        self.assertIn(tr('c_alerts_not_evaluated', 'zh'), render(result, 'zh'))
        self.assertIn('NOT_EVALUATED', render_details(result, 'zh'))

    def test_cache_and_outbound_permissions_are_separate_and_restarts_deny(self):
        self.assertTrue(self.session.allow_outbound(self.session.epoch, True))
        self.assertEqual(self.act('chat', question='check A')['error'], 'CONSENT_REQUIRED')
        self.session.invalidate(); self.authorize()
        self.assertEqual(self.act('chat', question='check A')['error'], 'OUTBOUND_CONSENT_REQUIRED')
        other = AssistantSession(self.db, provider=DeepSeekProvider(key_store=self.keys, transport=self.service))
        self.assertFalse(other.authorized); self.assertFalse(other.outbound)
        other.close()
        self.assertEqual(self.service.calls, [])

    def test_fake_ai_uses_evidence_only_and_does_not_change_sources(self):
        self.service = FakeService((200, response('get_stock', {'material_id': 'A'})),
                                   (200, response(text='Ignore evidence: stock is 999999 and fresh!')))
        self.provider = DeepSeekProvider(key_store=self.keys, transport=self.service)
        self.session.provider = self.provider
        before = [digest(p) for p in (self.stock, self.bom, self.db)]
        self.authorize(); self.session.allow_outbound(self.session.epoch, True)
        result = self.act('chat', question='How much stock is available for A?')
        self.assertEqual(result['status'], 'TOOL_RESULTS', result)
        rendered = render(result, 'en')
        self.assertIn('100', rendered); self.assertNotIn('999999', rendered)
        sent = json.dumps([call[0] for call in self.service.calls])
        self.assertNotIn(str(self.db), sent)
        self.assertNotIn('quantity', self.service.calls[-1][0]['messages'][-1]['content'])
        self.assertEqual(before, [digest(p) for p in (self.stock, self.bom, self.db)])

    def test_fake_ai_ambiguous_candidates_require_actual_selection(self):
        self.write_stock([('A-1', 1), ('A-10', 10)]); self.sync('stock')
        self.session.provider = DeepSeekProvider(key_store=self.keys, transport=FakeService(
            (200, response('search_materials', {'text': 'A-1'}))))
        self.authorize(); self.session.allow_outbound(self.session.epoch, True)
        result = self.act('chat', question='Check A-1')
        self.assertEqual(result['status'], 'NEEDS_SELECTION')
        self.assertEqual(len(result['candidates']), 2)
        self.assertIn(tr('select', 'zh'), render(result, 'zh'))

    def test_ai_failure_leaves_direct_local_tools_available(self):
        self.session.provider = DeepSeekProvider(key_store=self.keys, transport=FakeService((429, b'private error')))
        self.authorize(); token = self.candidate()
        self.session.allow_outbound(self.session.epoch, True)
        self.assertEqual(self.act('chat', question='Check A')['error'], 'PROVIDER_RATE_LIMITED')
        self.assertTrue(self.session.authorized)
        self.assertEqual(self.act('local', tool='get_stock', candidate=token)['status'], 'TOOL_RESULTS')

    def test_database_changed_or_failed_revokes_permissions_and_old_selection(self):
        self.authorize(); token = self.candidate()
        self.session.allow_outbound(self.session.epoch, True)
        self.write_stock([('A', 0)]); self.sync('stock')
        result = self.act('local', tool='get_stock', candidate=token)
        self.assertEqual(result['error'], 'STALE_DATA')
        self.assertFalse(self.session.authorized); self.assertFalse(self.session.outbound)
        self.authorize()
        with patch.object(self.session.tools, 'basis', side_effect=OSError('private-path')):
            failed = self.act('local', tool='data_status')
        self.assertEqual(failed['error'], 'DATABASE_READ_FAILED')
        self.assertFalse(self.session.authorized)
        self.assertNotIn('private-path', render(failed, 'en'))

    def test_stop_revoke_source_changes_block_queued_and_inflight_late_results(self):
        self.authorize()
        started, release = threading.Event(), threading.Event()
        original = self.session.tools.call
        def delayed(*args, **kwargs):
            started.set(); release.wait(2)
            return original(*args, **kwargs)
        with patch.object(self.session.tools, 'call', side_effect=delayed):
            self.assertTrue(self.session.submit('local', tool='search_materials', text='A'))
            self.assertTrue(started.wait(1))
            self.assertFalse(self.session.submit('local', tool='data_status'))
            self.session.invalidate(); release.set()
            self.assertEqual(wait_session(self.session), [])
        self.assertFalse(self.session.authorized)
        self.authorize()
        self.assertTrue(self.session.submit('local', tool='data_status'))
        deadline = time.monotonic()+2
        while self.session.busy and time.monotonic() < deadline:
            time.sleep(.002)
        self.session.invalidate()  # result was already queued
        self.assertEqual(self.session.drain(), [])

    def test_close_during_authorization_cannot_restore_consent(self):
        preview = self.act('preview_data')
        started, release = threading.Event(), threading.Event()
        original = self.session.tools.authorize_cached
        def late_grant():
            started.set(); release.wait(2); original()
        with patch.object(self.session.tools, 'authorize_cached', side_effect=late_grant):
            self.session.submit('authorize', expected_basis=preview['basis'])
            self.assertTrue(started.wait(1)); self.session.close(); release.set()
            self.assertEqual(wait_session(self.session), [])
        self.assertFalse(self.session.authorized)
        self.assertEqual(self.session.tools.call('get_stock', {'material_id': 'A'})['error']['code'], 'CONSENT_REQUIRED')

    def test_settings_revoke_and_do_not_echo_key_or_read_real_vault(self):
        self.authorize(); self.session.allow_outbound(self.session.epoch, True)
        result = self.act('save_key', key='synthetic-private-key')
        self.assertEqual(result['status'], 'KEY_SAVED')
        self.assertNotIn('synthetic-private-key', json.dumps(result))
        self.assertFalse(self.session.authorized); self.assertFalse(self.session.outbound)
        self.assertEqual(self.act('delete_key')['status'], 'KEY_DELETED')
        self.assertIsNone(self.keys.value)

    def test_preview_and_stale_dialog_cannot_grant_external_permission(self):
        preview = self.session.preview_request('check stock A')
        self.assertIn('deepseek-flash', preview)
        self.assertEqual(self.keys.reads, 0)
        epoch = self.session.epoch
        self.session.invalidate()
        self.assertFalse(self.session.allow_outbound(epoch, True))
        self.assertFalse(self.session.outbound)

    def test_stale_historical_dialog_does_not_grant_after_unrecorded_source_failure(self):
        preview = self.act('preview_data'); epoch = self.session.epoch
        self.session.invalidate()  # no SQLite change: e.g. source unavailable and failure recording failed
        self.assertFalse(self.session.submit('authorize', expected_epoch=epoch, expected_basis=preview['basis']))
        self.assertFalse(self.session.authorized)

    def test_status_query_does_not_upgrade_an_old_cache_consent_to_a_new_version(self):
        self.authorize()
        self.write_stock([('A', 0)]); self.sync('stock')
        result = self.act('local', tool='data_status')
        self.assertEqual(result['error'], 'STALE_DATA')
        self.assertFalse(self.session.authorized)

    def test_multiple_evidence_types_render_together_without_numeric_changes(self):
        self.authorize(); token = self.candidate()
        stock = self.act('local', tool='get_stock', candidate=token)
        analysis = self.act('local', tool='material_analysis', candidate=token, days=30)
        product = self.candidate('search_products', 'PRODUCT')
        estimate = self.act('local', tool='estimate_requirements', candidate=product, stock_sheet='Stock', quantity=3)
        combined = {'status': 'TOOL_RESULTS', 'evidence': stock['evidence']+analysis['evidence']+estimate['evidence']}
        for language in ('en', 'zh', 'ms'):
            text = render(combined, language)
            self.assertIn(f"{tr('required', language)} 6", render_details(combined, language))
            self.assertIn(tr('movement', language), text)


class ViewTests(Base):
    def setUp(self):
        super().setUp(); self.sync('stock'); self.sync('bom')
        self.root = tk.Tk()
        self.scaling = float(self.root.tk.call('tk', 'scaling'))
        self.root.tk.call('tk', 'scaling', 96/72)
        self.root.maxsize(4000, 3000)  # geometry simulation beyond this monitor's work area, not physical DPI acceptance
        self.root.geometry('960x600')
        self.outer = ttk.Frame(self.root)
        self.outer.pack(fill='both', expand=True)
        self.footer = ttk.Frame(self.outer)
        self.footer.pack(side='bottom', fill='x')
        self.keys, self.service = FakeKeys(), FakeService()
        self.session = AssistantSession(self.db, key_store=self.keys,
                                        provider=DeepSeekProvider(key_store=self.keys, transport=self.service))
        self.read_errors = []
        self.app = SimpleNamespace(root=self.root, outer=self.outer, inventory=self.inv, busy=False,
                                   alert_read_failed=self.read_errors.append)
        self.host = AssistantLauncher(self.app, self.footer, session=self.session)
        self.host.toggle(); self.root.update()

    def tearDown(self):
        self.host.close(); wait_session(self.session)
        self.root.tk.call('tk', 'scaling', self.scaling)
        self.root.destroy(); super().tearDown()

    def pump(self, predicate=lambda: True):
        deadline = time.monotonic()+4
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(.005)
        self.fail('Tk operation did not finish')

    def test_no_default_historical_dialog_and_restart_permissions(self):
        with patch('checker.assistant_ui.messagebox.askyesno', return_value=False) as ask:
            self.host.start('preview_data')
            self.pump(lambda: ask.called)
            self.assertEqual(ask.call_args.kwargs['default'], 'no')
        self.assertFalse(self.session.authorized)
        self.assertEqual(self.keys.reads, 0)

    def test_outbound_dialog_no_default_preview_and_stale_yes_are_guarded(self):
        self.host.view.input.insert('1.0', 'How much stock for A?')
        previews = []
        def answer(accepted, invalidate=False):
            dialogs = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel) and w is not self.host.surface]
            self.assertEqual(len(dialogs), 1)
            dialog = dialogs[0]
            def children(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from children(child)
            widgets = list(children(dialog))
            text = next(w for w in widgets if isinstance(w, tk.Text))
            previews.append(text.get('1.0', 'end'))
            if invalidate:
                self.host.invalidate()
            button = next(w for w in widgets if isinstance(w, ttk.Button) and
                          str(w.cget('text')).startswith('Yes' if accepted else 'No'))
            button.invoke()
        self.root.after(40, lambda: answer(False))
        self.host.authorize_api()
        self.assertFalse(self.session.outbound)
        self.assertIn('How much stock for A?', previews[0])
        self.root.after(40, lambda: answer(True, True))
        self.host.authorize_api()
        self.assertFalse(self.session.outbound)
        self.root.after(40, lambda: answer(True))
        self.host.authorize_api()
        self.assertTrue(self.session.outbound)
        self.assertEqual(self.keys.reads, 0)
        self.assertEqual(self.service.calls + self.service.balance_calls, [])

    def test_historical_yes_after_session_change_cannot_restore_consent(self):
        def invalidate_and_accept(*args, **kwargs):
            self.host.invalidate()
            return True
        with patch('checker.assistant_ui.messagebox.askyesno', side_effect=invalidate_and_accept) as ask:
            self.host.start('preview_data')
            self.pump(lambda: ask.called)
        self.assertFalse(self.session.authorized)

    def test_actual_local_search_selection_run_and_all_widgets_on_tk_thread(self):
        caller = threading.get_ident()
        original = self.host.append
        threads = []
        def append(*args):
            threads.append(threading.get_ident()); original(*args)
        self.host.append = append
        with patch('checker.assistant_ui.messagebox.askyesno', return_value=True):
            self.host.start('preview_data')
            self.pump(lambda: self.session.authorized and str(self.host.view.local_button.cget('state')) == 'normal')
        view = self.host.view
        view.local_text.set('A'); view.local_button.invoke()
        self.pump(lambda: bool(view.candidate_tree.get_children()))
        token = view.candidate_tree.get_children()[0]
        view.candidate_tree.selection_set(token); view._selected()
        view.local_button.invoke()
        self.pump(lambda: 'Recorded stock: 100' in view.transcript.get('1.0', 'end'))
        self.assertEqual(set(threads), {caller})
        self.assertEqual(self.service.calls, [])

    def test_direct_send_and_enter_shift_enter(self):
        self.host.language = 'zh'
        view = self.host.view
        view.input.insert('1.0', '帮我查询 A 的库存')
        self.assertIsNone(view._enter(SimpleNamespace(state=1)))
        self.assertEqual(view._enter(SimpleNamespace(state=0)), 'break')
        self.pump(lambda: not self.session.busy and bool(self.service.calls))
        self.assertNotIn('CONSENT_REQUIRED', view.transcript.get('1.0', 'end'))
        self.assertEqual(len(self.service.calls), 1)

    def test_small_window_and_scaling_matrix_keeps_warning_input_and_actions_visible(self):
        quota = self.session.provider._quota
        quota.balance({'is_available': True, 'balance_infos': [{'currency': 'USD', 'total_balance': '0.50'}]}, time.monotonic())
        quota.requests(8, 10)
        quota.usage({'prompt_tokens': 90, 'completion_tokens': 10, 'total_tokens': 100})
        for scale in (96/72, 2.0):
            self.root.tk.call('tk', 'scaling', scale)
            for width, height in ((960, 600), (1280, 720), (1366, 728)):
                with self.subTest(scale=scale, width=width):
                    self.root.geometry(f'{width}x{height}')
                    if self.host.surface is not None:
                        self.host._destroy_surface()
                    self.host._show()
                    self.host.surface.geometry(f'680x{min(height-45, 650)}')
                    self.pump(lambda: bool(self.host.view.quota.cget('text')))
                    self.root.update_idletasks()
                    view = self.host.view
                    self.assertEqual(self.host.mode, 'window')
                    self.assertIn('Cloud Not Verified', view.banner.cget('text'))
                    self.assertGreater(view.transcript.winfo_height(), 50)
                    for widget in (view.input, view.send_button, view.history_button, view.banner, view.quota):
                        self.assertTrue(widget.winfo_ismapped())
                        self.assertLess(widget.winfo_rooty()+widget.winfo_height(), self.host.surface.winfo_rooty()+self.host.surface.winfo_height()+2)

    def test_wide_window_docks_and_collapse_preserves_checker_and_revokes_permissions(self):
        self.root.geometry('1680x800'); self.root.update_idletasks()
        self.host._adapt(); self.root.update_idletasks()
        self.assertEqual(self.host.mode, 'docked')
        self.assertGreaterEqual(self.outer.winfo_width(), 960)
        self.session.allow_outbound(self.session.epoch, True)
        self.host.toggle()
        self.assertIsNone(self.host.surface)
        self.assertFalse(self.session.outbound)
        self.assertTrue(self.outer.winfo_ismapped())

    def test_explicit_150_percent_font_enlargement_has_measurably_larger_text(self):
        # Changing Tk scaling alone may reuse cached fonts. Force larger point sizes and verify metrics.
        view = self.host.view
        before = tkfont.Font(font=view.input.cget('font')).metrics('linespace')
        fonts = []
        def enlarge(widget):
            try:
                original = widget.cget('font') or 'TkDefaultFont'
                face = tkfont.Font(font=original)
                face.configure(size=round(face.actual('size')*1.5))
                fonts.append(face); widget.configure(font=face)
            except tk.TclError:
                pass
            for child in widget.winfo_children():
                enlarge(child)
        enlarge(self.host.surface)
        style = ttk.Style(self.root)
        style.configure('M4EFont.TButton', font=('Segoe UI', 15))
        style.configure('M4EFont.TNotebook.Tab', font=('Segoe UI', 14))
        view.tabs.configure(style='M4EFont.TNotebook')
        def buttons(widget):
            if isinstance(widget, ttk.Button):
                widget.configure(style='M4EFont.TButton')
            for child in widget.winfo_children():
                buttons(child)
        buttons(self.host.surface)
        self.host.surface.geometry('680x555')
        self.pump(lambda: bool(view.quota.cget('text')))
        self.root.update_idletasks()
        after = tkfont.Font(font=view.input.cget('font')).metrics('linespace')
        self.assertGreaterEqual(after, before*1.4)
        self.assertGreater(view.transcript.winfo_height(), 50)
        for widget in (view.banner, view.history_button, view.ai_button, view.input, view.send_button, view.quota):
            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), self.host.surface.winfo_rootx()+self.host.surface.winfo_width()+1)
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), self.host.surface.winfo_rooty()+self.host.surface.winfo_height()+1)
        self.host.candidates = [{'token': 'visual-row', 'kind': 'material', 'row': {'sheet': 'Stock', 'material_id': 'A'}}]
        view.fill_candidates(self.host.candidates)
        view.tabs.select(view.local_page); self.root.update()
        self.assertTrue(view.candidate_tree.bbox('visual-row'), 'The first candidate row must remain visible')
        view.tabs.select(2); self.root.update()
        self.assertTrue(view.limits.winfo_ismapped())
        view.limits.yview_moveto(1)
        self.assertEqual(view.limits.yview()[1], 1.0)

    def test_quota_notice_visible_in_selected_language_deduplicated_and_observation_time(self):
        self.host.language = 'ms'
        quota = self.session.provider._quota
        quota.balance({'is_available': True, 'balance_infos': [{'currency': 'USD', 'total_balance': '0.50'}]}, time.monotonic())
        self.pump(lambda: any('Baki API bagi' in text for _, text in self.host.messages))
        messages = len(self.host.messages)
        self.root.update(); self.assertEqual(messages, len(self.host.messages))
        self.assertIn('USD 0.50', self.host.view.quota.cget('text'))
        self.assertIn(quota.status(time.monotonic())['checked_at'], self.host.view.quota.cget('text'))
        self.host.view._balance()
        self.assertTrue(quota.status(time.monotonic())['balance_check_due'])
        self.assertEqual(self.service.balance_calls, [])

    def test_main_busy_blocks_chat_and_database_failure_notifies_host(self):
        self.app.busy = True
        self.assertFalse(self.host.start('preview_data'))
        self.app.busy = False
        with patch.object(self.session.tools, 'basis', side_effect=OSError('private')):
            self.host.start('preview_data'); self.pump(lambda: bool(self.read_errors))
        self.assertIn('DATABASE_READ_FAILED', self.host.view.transcript.get('1.0', 'end'))

    def test_hide_and_close_prevent_late_ui_updates_and_draft_is_preserved(self):
        self.host.view.input.insert('1.0', 'draft question')
        self.host.hide(); self.host.toggle()
        self.assertEqual(self.host.view.input.get('1.0', 'end-1c'), 'draft question')
        count = len(self.host.messages)
        self.host.close()
        self.assertFalse(self.session.submit('preview_data'))
        self.root.update(); self.assertEqual(len(self.host.messages), count)

    def test_quota_exhausted_unknown_request_and_output_warnings_use_question_language(self):
        self.host.language = 'zh'
        quota = self.session.provider._quota
        quota.exhausted(time.monotonic()); quota.unknown(time.monotonic())
        quota.requests(10, 10); quota.output_limit()
        self.pump(lambda: 'API 账户余额不足' in self.host.view.transcript.get('1.0', 'end'))
        text = self.host.view.transcript.get('1.0', 'end')
        for expected in ('剩余额度未知', '会话请求上限', '输出长度上限'):
            self.assertIn(expected, text)
        self.assertNotIn('100%', text)
        self.assertIn('API 额度未知', self.host.view.quota.cget('text'))


class MainIntegrationTests(Base):
    def setUp(self):
        super().setUp(); self.sync('stock'); self.sync('bom')
        self.root = tk.Tk(); self.root.withdraw()
        self.app = CheckerApp(self.root, inventory=self.inv)
        deadline = time.monotonic()+3
        while self.app.busy and time.monotonic() < deadline:
            self.root.update(); time.sleep(.005)
        self.keys, self.service = FakeKeys(), FakeService()
        self.app.assistant.session.close()
        self.session = AssistantSession(self.db, key_store=self.keys,
                                        provider=DeepSeekProvider(key_store=self.keys, transport=self.service))
        self.app.assistant.session = self.session

    def tearDown(self):
        self.app.close(); wait_session(self.session); super().tearDown()

    def authorize(self):
        self.session.submit('preview_data')
        preview = wait_session(self.session)[0].result
        self.session.submit('authorize', expected_basis=preview['basis'])
        wait_session(self.session)
        self.session.allow_outbound(self.session.epoch, True)

    def test_refresh_read_failure_and_maintenance_start_revoke_both_permissions(self):
        self.authorize()
        self.app._invalidate_alerts('source failed without database record')
        self.assertFalse(self.session.authorized); self.assertFalse(self.session.outbound)
        self.authorize()
        self.app.stock_path.set(str(self.stock)); self.app.bom_path.set(str(self.bom))
        self.app.refresh_excel()
        self.assertFalse(self.session.authorized); self.assertFalse(self.session.outbound)
        deadline = time.monotonic()+3
        while self.app.busy and time.monotonic() < deadline:
            self.root.update(); time.sleep(.005)
        self.assertFalse(self.app.busy)
        self.authorize()
        self.app._start(lambda: None, lambda _: None, 'preview')
        self.assertFalse(self.session.authorized); self.assertFalse(self.session.outbound)
        deadline = time.monotonic()+3
        while self.app.busy and time.monotonic() < deadline:
            self.root.update(); time.sleep(.005)

    def test_launcher_present_and_main_close_does_not_leave_permission_or_callbacks(self):
        self.assertTrue(self.app.assistant.button.winfo_exists())
        self.authorize()
        self.app.assistant.toggle(); self.root.update()
        self.app.assistant.close()
        self.assertTrue(self.app.root.winfo_exists())
        self.assertFalse(self.session.authorized); self.assertFalse(self.session.outbound)
