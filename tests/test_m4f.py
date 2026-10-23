"""M4F first-slice checks: synthetic read-only aggregate reports and per-report API consent."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from checker import daily, narrative
from checker.assistant import AssistantSession
from checker.assistant_language import ERRORS, TEXT, error_text, tr
from checker.assistant_ui import AssistantLauncher
from checker.outbound import POLICY
from checker.providers import DeepSeekProvider
from checker.agent import ProviderFailure
from tests.test_m31 import Base
from tests.test_m4d import FakeService, Keys, response
from tests.test_m4e import FakeKeys, wait_session

UTC = timezone.utc
NOW = datetime(2026, 10, 22, 9, 30, tzinfo=UTC)


def finish(session, action, **payload):
    if not session.submit(action, **payload):
        raise AssertionError(f"Could not start {action}")
    events = wait_session(session)
    if len(events) != 1:
        raise AssertionError(f"Expected one {action} event, got {len(events)}")
    return events[0].result


class ReportFactsTests(Base):
    def setUp(self):
        super().setUp()
        self.sync('stock')
        self.sync('bom')

    def test_daily_facts_are_fixed_shape_unverified_and_missing_counts_stay_unknown(self):
        facts = self.read(narrative.build_in, 'daily', now=NOW)
        self.assertEqual(facts['period'], 'DAILY')
        self.assertEqual(facts['verification'], 'UNVERIFIED')
        self.assertEqual(facts['cloud'], 'NOT_VERIFIED')
        self.assertIsNone(facts['previous_period'])
        self.assertIsNone(facts['recorded_alerts']['counts_by_type'])
        self.assertEqual(facts['recorded_alerts']['status'], 'UNAVAILABLE')
        self.assertEqual(facts['latest_sync_attempts']['stock']['outcome'], 'IMPORTED')
        self.assertEqual(facts['latest_sync_attempts']['bom']['outcome'], 'IMPORTED')
        self.assertEqual(narrative.validate_facts(facts), facts)

    def test_weekly_comparison_counts_only_observed_aggregate_events(self):
        self.clock.now = datetime(2026, 10, 10, 12, tzinfo=UTC)
        self.sync('stock')  # successful previous-window observation, even without a new snapshot
        self.write_stock([('PRIVATE-MAT-9942', 100)])
        self.sync('stock')
        self.write_stock([('PRIVATE-MAT-9942', 97)])
        outcome = self.sync('stock')
        conn = self.inv.connect()
        try:
            window = daily.day_window(daily.local_moment(NOW).date() - timedelta(days=1))
            observed = datetime.fromisoformat(window['start_utc']) + timedelta(hours=2)
            stamp = observed.strftime('%Y-%m-%d %H:%M:%S.') + f'{observed.microsecond // 1000:03d}'
            conn.execute('UPDATE inventory_snapshots SET observed_at=? WHERE source_version_id=?',
                         (stamp, outcome.version_id))
            conn.execute('UPDATE source_versions SET imported_at=? WHERE id=?', (stamp, outcome.version_id))
            conn.commit()
        finally:
            conn.close()
        facts = self.read(narrative.build_in, 'weekly', now=NOW)
        self.assertEqual(facts['period'], 'WEEKLY')
        self.assertIsNotNone(facts['previous_period'])
        self.assertEqual(facts['comparison']['status'], 'COMPARABLE')
        self.assertEqual(facts['current_period']['changes_by_type']['QUANTITY_CHANGED']['events'], 1)
        self.assertEqual(facts['comparison']['change_event_delta_by_type']['QUANTITY_CHANGED'], 1)
        self.assertEqual(facts['verification'], 'UNVERIFIED')

    def test_payload_contains_only_allowlisted_aggregate_fields_and_no_tool_definitions(self):
        facts = self.read(narrative.build_in, 'weekly', now=NOW)
        payload = narrative.request_payload(facts, 'zh', 'deepseek-flash', 2048)
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(str(self.stock), encoded)
        self.assertNotIn(str(self.bom), encoded)
        self.assertNotIn('PRIVATE-MAT-9942', encoded)
        self.assertNotIn('Fixture material', encoded)
        self.assertNotIn('tools', payload)
        self.assertNotIn('tool_choice', payload)
        self.assertIn('Simplified Chinese', encoded)
        self.assertEqual(payload['max_tokens'], 512)

    def test_injected_paths_ids_and_non_integer_counts_are_rejected(self):
        facts = self.read(narrative.build_in, 'daily', now=NOW)
        for change in (
            lambda value: value.update(source_path='C:\\private\\workbook.xlsx'),
            lambda value: value['current_period']['changes_by_type']['ADDED'].update(material_id='secret'),
            lambda value: value['current_period']['changes_by_type']['ADDED'].update(events=True),
        ):
            candidate = json.loads(json.dumps(facts))
            change(candidate)
            with self.assertRaises(ValueError):
                narrative.validate_facts(candidate)

    def test_retention_marker_preserves_removed_history_state_when_no_snapshots_remain(self):
        conn = self.inv.connect()
        try:
            end = daily.day_window(daily.local_moment(NOW).date())['end_utc']
            conn.execute("INSERT OR REPLACE INTO schema_info VALUES ('history_retained_from',?)", (end,))
            conn.execute('DELETE FROM inventory_changes')
            conn.execute('DELETE FROM inventory_snapshots')
            conn.commit()
        finally:
            conn.close()
        facts = self.read(narrative.build_in, 'daily', now=NOW)
        self.assertIn(facts['current_period']['coverage'], {'REMOVED', 'PARTLY_PRUNED'})


class ReportAccuracyTests(Base):
    def facts(self, period='daily'):
        return self.read(narrative.build_in, period, now=NOW)

    def test_no_sources_keep_all_role_issue_counts_unknown_in_payload(self):
        facts = self.facts()
        quality = facts['data_quality']
        self.assertIsNone(quality['latest_retained_storage'])
        for counts in quality['recorded_issue_rows'].values():
            self.assertTrue(all(value is None for value in counts.values()))
        body = narrative.request_payload(facts, 'en', 'deepseek-flash', 512)
        sent = json.loads(body['messages'][1]['content'].split('Facts JSON:\n', 1)[1])
        self.assertEqual(sent['data_quality'], quality)

    def test_storage_only_keeps_bom_unknown_and_known_clean_storage_zero(self):
        self.sync('stock')
        counts = self.facts()['data_quality']['recorded_issue_rows']
        self.assertTrue(all(value == 0 for value in counts['stock'].values()))
        self.assertTrue(all(value is None for value in counts['bom'].values()))

    def test_bom_only_keeps_storage_unknown(self):
        self.sync('bom')
        quality = self.facts()['data_quality']
        self.assertIsNone(quality['latest_retained_storage'])
        self.assertTrue(all(value is None for value in quality['recorded_issue_rows']['stock'].values()))
        self.assertTrue(all(value == 0 for value in quality['recorded_issue_rows']['bom'].values()))

    def test_numeric_id_issues_are_counted_separately_for_each_role(self):
        self.write_stock([(123, 10)])
        self.write_bom([(456, 1), (789, 2)])
        self.sync('stock'); self.sync('bom')
        counts = self.facts()['data_quality']['recorded_issue_rows']
        self.assertEqual(counts['stock']['NUMERIC_MATERIAL_ID'], 1)
        self.assertEqual(counts['bom']['NUMERIC_MATERIAL_ID'], 2)

    def test_unobserved_previous_week_is_not_comparable(self):
        self.sync('stock')  # baseline before both windows
        for day in range(16, 22):
            self.clock.now = datetime(2026, 10, day, 12, tzinfo=UTC)
            self.write_stock([('A', day)])
            self.sync('stock')
        facts = self.facts('weekly')
        self.assertEqual(facts['previous_period']['snapshots'], 0)
        self.assertEqual(facts['previous_period']['stock_sync_attempts'], 0)
        self.assertEqual(facts['current_period']['successful_stock_checks'], 6)
        self.assertEqual(facts['comparison']['status'], 'INCOMPLETE_HISTORY')
        self.assertTrue(all(value is None for value in facts['comparison']['change_event_delta_by_type'].values()))

    def test_successful_unchanged_checks_distinguish_zero_changes_from_no_observation(self):
        self.sync('stock')
        for day in (10, 17):
            self.clock.now = datetime(2026, 10, day, 12, tzinfo=UTC)
            self.assertEqual(self.sync('stock').outcome, 'UNCHANGED')
        facts = self.facts('weekly')
        for part in (facts['current_period'], facts['previous_period']):
            self.assertEqual(part['snapshots'], 0)
            self.assertEqual(part['stock_sync_attempts'], 1)
            self.assertEqual(part['successful_stock_checks'], 1)
        self.assertEqual(facts['comparison']['status'], 'COMPARABLE')
        self.assertTrue(all(value == 0 for value in facts['comparison']['change_event_delta_by_type'].values()))

    def test_failed_checks_and_bom_checks_do_not_establish_storage_observation(self):
        self.sync('stock')
        self.clock.now = datetime(2026, 10, 10, 12, tzinfo=UTC)
        absent = self.stock.with_suffix('.unavailable')
        self.stock.rename(absent)
        try:
            self.assertEqual(self.sync('stock').outcome, 'UNAVAILABLE')
        finally:
            absent.rename(self.stock)
        self.sync('bom')
        self.clock.now = datetime(2026, 10, 17, 12, tzinfo=UTC)
        self.sync('stock')
        facts = self.facts('weekly')
        self.assertEqual(facts['previous_period']['stock_sync_attempts'], 1)
        self.assertEqual(facts['previous_period']['successful_stock_checks'], 0)
        self.assertEqual(facts['comparison']['status'], 'INCOMPLETE_HISTORY')


class ProviderReportConsentTests(Base):
    def setUp(self):
        super().setUp()
        self.sync('stock'); self.sync('bom')
        self.keys, self.service = Keys(), FakeService((200, response(text='The retained observations are limited.')))
        self.provider = DeepSeekProvider(key_store=self.keys, transport=self.service)

    def test_preview_reads_no_key_and_sends_nothing(self):
        facts = self.read(narrative.build_in, 'daily', now=NOW)
        body = self.provider.preview_narrative(facts, 'en')
        self.assertEqual(self.keys.reads, 0)
        self.assertEqual(self.service.calls, [])
        payload = json.loads(body)
        self.assertNotIn('tools', payload)
        self.assertNotIn('tool_choice', payload)

    def test_one_report_requires_general_and_per_report_consent_and_is_single_use(self):
        facts = self.read(narrative.build_in, 'daily', now=NOW)
        request_hash = hashlib.sha256(self.provider.preview_narrative(facts, 'en')).hexdigest()
        with self.assertRaises(ProviderFailure) as raised:
            self.provider.complete_narrative(facts, 'en', expected_request_sha256=request_hash,
                                             timeout=2, cancel=threading.Event())
        self.assertEqual(raised.exception.code, 'OUTBOUND_CONSENT_REQUIRED')
        self.provider.authorize_outbound(policy=POLICY, accepted=True)
        with self.assertRaises(ProviderFailure) as raised:
            self.provider.complete_narrative(facts, 'en', expected_request_sha256=request_hash,
                                             timeout=2, cancel=threading.Event())
        self.assertEqual(raised.exception.code, 'OUTBOUND_CONSENT_REQUIRED')
        self.assertTrue(self.provider.authorize_narrative(policy=narrative.REPORT_POLICY, accepted=True))
        reply = self.provider.complete_narrative(facts, 'en', expected_request_sha256=request_hash,
                                                 timeout=2, cancel=threading.Event())
        self.assertEqual(reply.text, 'The retained observations are limited.')
        self.assertEqual(len(self.service.calls), 1)
        request = self.service.calls[0][0]
        self.assertNotIn('tools', request)
        self.assertNotIn(str(self.stock), json.dumps(request))
        with self.assertRaises(ProviderFailure) as raised:
            self.provider.complete_narrative(facts, 'en', expected_request_sha256=request_hash,
                                             timeout=2, cancel=threading.Event())
        self.assertEqual(raised.exception.code, 'OUTBOUND_CONSENT_REQUIRED')

    def test_request_change_after_confirmation_is_rejected_before_network(self):
        facts = self.read(narrative.build_in, 'daily', now=NOW)
        self.provider.authorize_outbound(policy=POLICY, accepted=True)
        expected = hashlib.sha256(self.provider.preview_narrative(facts, 'en')).hexdigest()
        self.provider.authorize_narrative(policy=narrative.REPORT_POLICY, accepted=True)
        with self.assertRaises(ProviderFailure) as raised:
            self.provider.complete_narrative(facts, 'ms', expected_request_sha256=expected,
                                             timeout=2, cancel=threading.Event())
        self.assertEqual(raised.exception.code, 'STALE_REPORT')
        self.assertEqual(self.keys.reads, 0)
        self.assertEqual(self.service.calls + self.service.balance_calls, [])

    def test_numeric_model_claim_is_discarded(self):
        facts = self.read(narrative.build_in, 'daily', now=NOW)
        request_hash = hashlib.sha256(self.provider.preview_narrative(facts, 'en')).hexdigest()
        self.provider.authorize_outbound(policy=POLICY, accepted=True)
        self.provider.authorize_narrative(policy=narrative.REPORT_POLICY, accepted=True)
        self.service.steps = iter([(200, response(text='There are 12 observed changes.'))])
        with self.assertRaises(ProviderFailure) as raised:
            self.provider.complete_narrative(facts, 'en', expected_request_sha256=request_hash,
                                             timeout=2, cancel=threading.Event())
        self.assertEqual(raised.exception.code, 'NARRATIVE_REJECTED')

    def test_forbidden_claims_and_number_words_are_discarded_after_one_request(self):
        facts = self.read(narrative.build_in, 'daily', now=NOW)
        request_hash = hashlib.sha256(self.provider.preview_narrative(facts, 'en')).hexdigest()
        self.provider.authorize_outbound(policy=POLICY, accepted=True)
        for text in ('Stock is sufficient and production can proceed.', 'Twelve materials changed.',
                     '库存充足，建议尽快采购。', 'Data telah disahkan di awan.'):
            with self.subTest(text=text):
                calls = len(self.service.calls)
                self.provider.authorize_narrative(policy=narrative.REPORT_POLICY, accepted=True)
                self.service.steps = iter([(200, response(text=text))])
                with self.assertRaises(ProviderFailure) as raised:
                    self.provider.complete_narrative(facts, 'en', expected_request_sha256=request_hash,
                                                     timeout=2, cancel=threading.Event())
                self.assertEqual(raised.exception.code, 'NARRATIVE_REJECTED')
                self.assertEqual(len(self.service.calls), calls + 1)  # one request; the grant is spent
                with self.assertRaises(ProviderFailure) as again:
                    self.provider.complete_narrative(facts, 'en', expected_request_sha256=request_hash,
                                                     timeout=2, cancel=threading.Event())
                self.assertEqual(again.exception.code, 'OUTBOUND_CONSENT_REQUIRED')


class SessionReportTests(Base):
    def setUp(self):
        super().setUp()
        self.sync('stock'); self.sync('bom')
        self.keys, self.service = FakeKeys(), FakeService((200, response(text='The recorded history is incomplete.')))
        self.provider = DeepSeekProvider(key_store=self.keys, transport=self.service)
        self.session = AssistantSession(self.db, key_store=self.keys, provider=self.provider)
        preview = finish(self.session, 'preview_data')
        finish(self.session, 'authorize', expected_basis=preview['basis'])
        self.basis = self.session._authorized_basis
        self.facts_preview = finish(self.session, 'report_preview', period='weekly')

    def tearDown(self):
        self.session.close()
        wait_session(self.session)
        super().tearDown()

    def test_local_preview_does_not_call_provider_and_send_requires_ui_grant(self):
        result = self.facts_preview
        self.assertEqual(result['status'], 'REPORT_PREVIEW')
        self.assertEqual(result['basis'], self.basis)
        self.assertEqual(self.keys.reads, 0)
        self.assertEqual(self.service.calls + self.service.balance_calls, [])
        self.assertFalse(self.session.submit('report_narrative', facts=result['facts'], basis=self.basis,
                                             facts_digest=result['facts_digest'], approval='forged'))
        self.assertIsNone(self.session.approve_report(self.session.epoch, self.basis,
                                                     result['facts_digest'], 'en', '0' * 64, False))

    def test_report_consent_is_bound_to_exact_facts_and_stale_database_fails_before_network(self):
        result = self.facts_preview
        self.assertTrue(self.session.allow_outbound(self.session.epoch, True))
        request_hash = hashlib.sha256(self.provider.preview_narrative(result['facts'], 'en')).hexdigest()
        approval = self.session.approve_report(self.session.epoch, self.basis, result['facts_digest'], 'en',
                                               request_hash, True)
        self.assertIsNotNone(approval)
        self.write_stock([('A', 0), ('B', 5), ('C', 0)])
        self.sync('stock')
        self.assertTrue(self.session.submit('report_narrative', approval=approval, basis=self.basis,
                                            facts=result['facts'], facts_digest=result['facts_digest'],
                                            report_language='en', request_sha256=request_hash))
        events = wait_session(self.session)
        self.assertEqual(events[0].result['error'], 'STALE_DATA')
        self.assertEqual(self.service.calls + self.service.balance_calls, [])

    def test_current_basis_report_runs_without_tools_and_keeps_unverified_markers(self):
        result = self.facts_preview
        self.assertTrue(self.session.allow_outbound(self.session.epoch, True))
        request_hash = hashlib.sha256(self.provider.preview_narrative(result['facts'], 'ms')).hexdigest()
        approval = self.session.approve_report(self.session.epoch, self.basis, result['facts_digest'], 'ms',
                                               request_hash, True)
        self.assertTrue(self.session.submit('report_narrative', language='ms', approval=approval, basis=self.basis,
                                            facts=result['facts'], facts_digest=result['facts_digest'], report_language='ms',
                                            request_sha256=request_hash))
        events = wait_session(self.session)
        self.assertEqual(events[0].result['status'], 'NARRATIVE')
        self.assertIn('UNVERIFIED', events[0].reply)
        self.assertIn('Cloud Not Verified', events[0].reply)
        self.assertIn('pemerhatian sejarah', events[0].reply)
        self.assertIn('Bahasa Melayu', self.service.calls[0][0]['messages'][1]['content'])
        body = json.dumps(self.service.calls[0][0], ensure_ascii=False)
        self.assertNotIn(str(self.stock), body)
        self.assertNotIn(str(self.bom), body)
        self.assertEqual(self.service.calls[0][0].get('tools'), None)
        self.assertFalse(self.session.submit('report_narrative', approval=approval, basis=self.basis,
                                             facts=result['facts'], facts_digest=result['facts_digest'],
                                             report_language='ms', request_sha256=request_hash))


class ReportDialogTests(Base):
    def setUp(self):
        super().setUp(); self.sync('stock'); self.sync('bom')
        self.root = tk.Tk()
        self.scaling = float(self.root.tk.call('tk', 'scaling'))
        self.root.tk.call('tk', 'scaling', 96/72)
        self.root.maxsize(4000, 3000)
        self.root.geometry('960x600')
        self.outer = ttk.Frame(self.root); self.outer.pack(fill='both', expand=True)
        self.footer = ttk.Frame(self.outer); self.footer.pack(side='bottom', fill='x')
        self.keys, self.service = FakeKeys(), FakeService((200, response(text='The recorded history is limited.')))
        self.session = AssistantSession(self.db, key_store=self.keys,
                                        provider=DeepSeekProvider(key_store=self.keys, transport=self.service))
        self.app = SimpleNamespace(root=self.root, outer=self.outer, inventory=self.inv, busy=False,
                                   alert_read_failed=lambda _reason: None)
        self.host = AssistantLauncher(self.app, self.footer, session=self.session)
        self.host.toggle(); self.root.update()
        data = finish(self.session, 'preview_data')
        finish(self.session, 'authorize', expected_basis=data['basis'])
        report = finish(self.session, 'report_preview', period='daily')
        self.host.report_facts, self.host.report_digest, self.host.report_basis = (
            report['facts'], report['facts_digest'], report['basis'])
        self.session.allow_outbound(self.session.epoch, True)
        self.host.view.show_report(report['facts'])

    def tearDown(self):
        self.host.close(); wait_session(self.session)
        self.root.tk.call('tk', 'scaling', self.scaling)
        self.root.destroy(); super().tearDown()

    def test_unknown_quality_and_incomplete_weekly_deltas_render_as_unknown(self):
        conn = self.inv.connect()
        try:
            conn.execute("DELETE FROM current_sources WHERE role='bom'")
        finally:
            conn.close()
        facts = self.read(narrative.build_in, 'weekly', now=NOW)
        self.host.view.show_report(facts)
        text = self.host.view.report_preview.get('1.0', 'end-1c')
        self.assertIn('bom / INVALID_BOM_QTY: unknown issue rows', text)
        self.assertIn('QUANTITY_CHANGED event-count delta: unknown', text)
        self.assertIn('Successful Storage checks: 0', text)

    def answer_dialog(self, accepted, seen):
        dialogs = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel) and w is not self.host.surface]
        if len(dialogs) != 1:
            return
        dialog = dialogs[0]
        def walk(widget):
            for child in widget.winfo_children():
                yield child
                yield from walk(child)
        widgets = list(walk(dialog))
        text = next(w for w in widgets if isinstance(w, tk.Text))
        disclosure = next(w for w in widgets if isinstance(w, ttk.Label))
        focused = dialog.focus_get()
        seen.append({'request': text.get('1.0', 'end'), 'disclosure': disclosure.cget('text'),
                     'focused_text': focused.cget('text') if isinstance(focused, ttk.Button) else None})
        wanted = 'Yes' if accepted else 'No'
        button = next(w for w in widgets if isinstance(w, ttk.Button) and str(w.cget('text')).startswith(wanted))
        button.invoke()

    def pump(self, predicate=lambda: True):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(.005)
        self.fail('Tk report operation did not finish')

    def test_report_confirmation_is_no_default_and_decline_sends_nothing(self):
        seen = []
        self.root.after(40, lambda: self.answer_dialog(False, seen))
        self.host.send_report()
        self.assertTrue(seen)
        self.assertIn('No is the default', seen[0]['disclosure'])
        self.assertIn('Cloud Not Verified', seen[0]['disclosure'])
        self.assertTrue(str(seen[0]['focused_text']).startswith('No'))
        self.assertEqual(self.service.calls + self.service.balance_calls, [])
        self.assertEqual(self.keys.reads, 0)

    def test_yes_sends_only_the_exact_aggregate_preview_once(self):
        seen = []
        self.root.after(40, lambda: self.answer_dialog(True, seen))
        self.host.send_report()
        self.pump(lambda: not self.session.busy and bool(self.service.calls))
        self.assertTrue(seen)
        body = json.dumps(self.service.calls[0][0], ensure_ascii=False)
        self.assertNotIn(str(self.stock), body)
        self.assertNotIn(str(self.bom), body)
        self.assertNotIn('Fixture material', body)
        self.assertNotIn('tools', self.service.calls[0][0])
        self.assertEqual(json.loads(seen[0]['request']), self.service.calls[0][0])
        self.assertEqual(len(self.service.calls), 1)
        self.assertEqual(self.keys.reads, 1)

    def test_refresh_invalidation_clears_the_old_preview_before_another_send(self):
        self.assertIsNotNone(self.host.report_facts)
        self.host.invalidate()
        self.assertIsNone(self.host.report_facts)
        self.assertEqual(self.host.view.report_preview.get('1.0', 'end-1c'), '')
        self.assertEqual(str(self.host.view.report_send_button.cget('state')), 'disabled')
        self.assertEqual(self.service.calls + self.service.balance_calls, [])

    def test_database_change_after_preview_clears_it_and_sends_nothing(self):
        self.write_stock([('A', 0), ('B', 5), ('C', 0)])
        self.sync('stock')
        seen = []
        self.root.after(40, lambda: self.answer_dialog(True, seen))
        self.host.send_report()
        self.pump(lambda: not self.session.busy and self.host.report_facts is None)
        self.assertEqual(self.service.calls + self.service.balance_calls, [])
        self.assertIsNone(self.host.report_facts)
        self.assertEqual(self.host.view.report_preview.get('1.0', 'end-1c'), '')
        self.assertFalse(self.session.authorized)

    def test_report_tab_has_scrollable_space_in_small_window(self):
        view = self.host.view
        view.tabs.select(view.report_page)
        self.root.update_idletasks()
        self.root.update()
        self.assertTrue(view.report_preview.winfo_ismapped())
        self.assertGreater(view.report_preview.winfo_height(), 70)
        for widget in (view.report_period, view.report_build_button, view.report_send_button, view.report_preview):
            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                 self.host.surface.winfo_rootx() + self.host.surface.winfo_width() + 1)

    def test_rejected_ai_reply_keeps_the_local_preview(self):
        self.service.steps = iter([(200, response(text='Stock is sufficient; production can proceed.'))])
        before = self.host.view.report_preview.get('1.0', 'end-1c')
        seen = []
        self.root.after(40, lambda: self.answer_dialog(True, seen))
        self.host.send_report()
        self.pump(lambda: not self.session.busy and any('NARRATIVE_REJECTED' in text for _s, text in self.host.messages))
        self.assertEqual(len(self.service.calls), 1)
        self.assertIsNotNone(self.host.report_facts)
        self.assertEqual(self.host.view.report_preview.get('1.0', 'end-1c'), before)
        self.assertFalse(any('production can proceed' in text for _s, text in self.host.messages))

    def test_preview_follows_language_without_changing_facts_or_consent(self):
        facts, digest_before = self.host.report_facts, self.host.report_digest
        texts = {}
        for language in ('zh', 'ms', 'en'):
            self.host.language = language
            self.pump(lambda: self.host.view.report_shown_language == language)
            texts[language] = self.host.view.report_preview.get('1.0', 'end-1c')
            self.assertIn('UNVERIFIED', texts[language])
            self.assertIn('Cloud Not Verified', texts[language])
        self.assertEqual(len(set(texts.values())), 3)
        self.assertIn('观察到的变化 ≠ 实际消耗', texts['zh'])
        self.assertIn('Penggunaan Sebenar', texts['ms'])
        self.assertIn('not continuous monitoring', texts['en'])
        self.assertIn('(NOT_APPLICABLE)', texts['zh'])  # canonical codes stay visible
        self.assertIs(self.host.report_facts, facts)
        self.assertEqual(self.host.report_digest, digest_before)
        self.assertEqual(self.service.calls + self.service.balance_calls, [])
        self.host.language = 'zh'
        self.pump(lambda: self.host.view.report_shown_language == 'zh')
        seen = []
        self.root.after(40, lambda: self.answer_dialog(True, seen))
        self.host.send_report()
        self.pump(lambda: not self.session.busy and bool(self.service.calls))
        self.assertIn('Simplified Chinese', self.service.calls[0][0]['messages'][1]['content'])
        self.assertEqual(json.loads(seen[0]['request']), self.service.calls[0][0])

    def test_language_switch_after_invalidation_cannot_restore_the_old_preview(self):
        self.host.invalidate()
        self.host.language = 'ms'
        self.pump()
        self.root.update()
        self.assertEqual(self.host.view.report_preview.get('1.0', 'end-1c'), '')
        self.assertIsNone(self.host.report_facts)
        self.assertEqual(str(self.host.view.report_send_button.cget('state')), 'disabled')


class ReplyGuardTests(unittest.TestCase):
    """P2-1: conservative keyword guard of the narrative reply only (M4E chat replies are not affected)."""
    REJECT = {
        'STOCK_SUFFICIENT_OR_PRODUCTION_READY': ('Stock is sufficient for the coming weeks.',
                                                 'The inventory looks healthy and production can proceed.',
                                                 '库存充足，可以正常生产。', 'Stok mencukupi untuk minggu ini.'),
        'CLOUD_VERIFIED': ('Data were verified in the cloud.', '数据已在云端验证。', 'Data telah disahkan di awan.'),
        'ACTUAL_CONSUMPTION': ('Actual consumption rose this week.', '实际消耗增加。',
                               'Ini menunjukkan penggunaan sebenar.'),
        'PURCHASE_ACTION': ('You should purchase more material soon.', 'Reorder the affected items.', '建议尽快采购。',
                            'Disyorkan membeli bahan tambahan.'),
        'NUMBER': ('There were 3 alerts.', 'Twelve materials changed this week.', '本周有十二项变化。',
                   'Terdapat dua belas perubahan minggu ini.'),
    }
    ACCEPT = ('Observed changes are not actual consumption.', 'The data are UNVERIFIED and Cloud Not Verified.',
              'History coverage is incomplete, so the trend cannot be concluded.',
              'This report does not recommend any purchase.', 'It is unknown whether stock is sufficient.',
              'One of the categories shows more activity than before.', 'Both periods had recorded observations.',
              '观察到的变化不等于实际消耗。', '无法判断库存是否充足。', '两个时间段的覆盖不完整，无法得出趋势结论。',
              '一些类别出现了变化，但这不代表需求增加。', '第二个窗口的记录较少。', '数据未经云端验证。',
              '本报告不提供采购建议。', 'Perubahan yang diperhatikan bukan penggunaan sebenar.',
              'Salah satu kategori menunjukkan perubahan.', 'Data belum disahkan di awan.',
              'Liputan sejarah tidak lengkap; trend tidak dapat disimpulkan.')

    def test_plain_forbidden_claims_are_found_in_three_languages(self):
        for code, texts in self.REJECT.items():
            for text in texts:
                with self.subTest(text=text):
                    self.assertIn(code, narrative.reply_problems(text))

    def test_cautious_and_negated_sentences_pass(self):
        for text in self.ACCEPT:
            with self.subTest(text=text):
                self.assertEqual(narrative.reply_problems(text), ())

    def test_a_negation_in_one_sentence_does_not_excuse_another(self):
        self.assertEqual(narrative.reply_problems('Coverage is not complete. Stock is sufficient.'),
                         ('STOCK_SUFFICIENT_OR_PRODUCTION_READY',))

    def test_rejection_message_keeps_local_counts_in_three_languages(self):
        texts = [error_text('NARRATIVE_REJECTED', language) for language in ('en', 'zh', 'ms')]
        self.assertEqual(len(set(texts)), 3)
        self.assertIn('local counts above are unchanged', texts[0])
        self.assertIn('cannot guarantee', texts[0])


class TranslationTests(unittest.TestCase):
    def test_new_report_ui_copy_has_all_three_languages(self):
        for key in ('report_tab', 'report_intro', 'report_period', 'report_build', 'report_send',
                    'report_no_data', 'report_preview_ready', 'report_interpretation',
                    'report_review_caveat', 'report_disclosure', 'report_confirm_title', 'daily', 'weekly'):
            values = [tr(key, language) for language in ('en', 'zh', 'ms')]
            self.assertTrue(all(values))
            self.assertEqual(len(set(values)), 3)
        for code in ERRORS:
            self.assertEqual(len({error_text(code, language) for language in ('en', 'zh', 'ms')}), 3)
        self.assertIn('Cloud Not Verified', TEXT['report_interpretation'][1])
