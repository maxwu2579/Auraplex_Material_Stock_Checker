"""M4F delivery: saved HTML + JSON aggregate reports and local .eml drafts. Synthetic workbooks, temporary SQLite,
fake keys/transport; no real API, no mail server, nothing is sent."""
from contextlib import closing
from email import message_from_bytes, policy
import hashlib
import json
from pathlib import Path
import re
import socket
import sqlite3
import threading
import time
import tkinter as tk
from unittest.mock import patch

from checker import narrative, report_delivery as rd
from checker.assistant import AssistantSession
from checker.assistant_language import tr
from checker.providers import DeepSeekProvider
from checker.sync import IMPORTED, InventorySync
from tests.fixtures import bom_rows, stock_rows, workbook
from tests.test_m31 import Base
from tests.test_m4d import FakeService, response
from tests.test_m4e import FakeKeys, wait_session
from tests import test_m4f as m4f
from tests.test_m4f import NOW, finish

SECRETS = ('PRIVATE-ID-77881', 'CONFIDENTIAL-ZZ', 'SECRET DESCRIPTION', 'SECRET-SHEET', 'SECRET-PRODUCT', 'Fixture material')


def files(folder):
    return sorted(p.name for p in Path(folder).iterdir())


class DeliveryBase(Base):
    """A session holding local-data authorisation and one weekly preview of synthetic data."""

    def setUp(self):
        super().setUp()
        rows = stock_rows([('PRIVATE-ID-77881', 41), ('CONFIDENTIAL-ZZ', 'abc'), ('CONFIDENTIAL-ZZ', 3)])
        rows[15]['F'] = 'SECRET DESCRIPTION'
        workbook(self.stock, [('SECRET-SHEET', rows)])
        workbook(self.bom, [('SECRET-PRODUCT', bom_rows([('PRIVATE-ID-77881', 2), ('BOM-ONLY', 1)]))])
        self.assertEqual(self.sync().outcome, IMPORTED)
        self.assertEqual(self.sync('bom').outcome, IMPORTED)
        self.keys, self.service = FakeKeys(), FakeService((200, response(text='Coverage is limited.')))
        self.session = AssistantSession(self.db, key_store=self.keys,
                                        provider=DeepSeekProvider(key_store=self.keys, transport=self.service))
        data = finish(self.session, 'preview_data')
        finish(self.session, 'authorize', expected_basis=data['basis'])
        self.preview = finish(self.session, 'report_preview', period='weekly')
        self.epoch, self.basis = self.session.epoch, self.preview['basis']
        self.out = self.base / 'reports'
        self.out.mkdir()

    def tearDown(self):
        self.session.close()
        wait_session(self.session)
        super().tearDown()

    def document(self, language='en', ai=None):
        return rd.build_document(self.preview['facts'], self.preview['facts_digest'], self.basis, language,
                                 narrative_text=ai)

    def save(self, document=None, **kw):
        return rd.save_report(document or self.document(), self.out, self.db, basis_of=self.session.data_basis,
                              guard=lambda: self.session.report_guard(self.epoch, self.basis), **kw)

    def other_sync(self):
        workbook(self.stock, [('SECRET-SHEET', stock_rows([('PRIVATE-ID-77881', 7)]))])
        self.assertEqual(InventorySync(self.db, settle_seconds=0, clock=self.clock).sync_role(
            'stock', str(self.stock), 'manual').outcome, IMPORTED)


class DocumentTests(DeliveryBase):
    def test_local_statistics_export_without_ai_keeps_status_and_unknowns(self):
        doc = self.document()
        data = doc.data()
        self.assertEqual(data['facts'], self.preview['facts'])  # the facts are carried unchanged
        self.assertIsNone(data['ai_interpretation'])
        self.assertEqual((data['verification'], data['cloud'], data['statement']),
                         ('UNVERIFIED', 'Cloud Not Verified', 'Observed Change ≠ Actual Consumption'))
        page = rd.render_html(doc)
        for text in ('UNVERIFIED', 'Cloud Not Verified', 'Observed Change ≠ Actual Consumption',
                     'No AI interpretation is included', 'INCOMPLETE_HISTORY'):
            self.assertIn(text, page)

    def test_unknown_values_render_as_unknown_in_three_languages(self):
        conn = self.inv.connect()
        try:
            conn.execute("DELETE FROM current_sources WHERE role='bom'")  # BOM issue counts become unknown
        finally:
            conn.close()
        with closing(sqlite3.connect(self.db)) as c:
            pass
        facts = self.read(narrative.build_in, 'weekly', now=NOW)
        self.assertIsNone(facts['data_quality']['recorded_issue_rows']['bom']['DUPLICATE_BOM'])
        pages = {}
        for lang, word in (('en', 'unknown'), ('zh', '未知'), ('ms', 'tidak diketahui')):
            doc = rd.build_document(facts, narrative.digest(facts), self.basis, lang)
            pages[lang] = rd.render_html(doc)
            self.assertRegex(pages[lang], r'bom / DUPLICATE_BOM[^<]*</th><td>' + re.escape(word) + '<')
            self.assertNotRegex(pages[lang], r'bom / DUPLICATE_BOM[^<]*</th><td>0<')
            self.assertEqual(set(doc.data()), set(self.document().data()))  # canonical JSON keys in every language
        self.assertEqual(len(set(pages.values())), 3)

    def test_ai_interpretation_is_a_separate_escaped_section_and_never_changes_facts(self):
        doc = self.document(ai='History coverage is limited <b>here</b> & elsewhere.')
        data = doc.data()
        self.assertEqual(data['facts'], self.preview['facts'])
        self.assertEqual(data['ai_interpretation']['host_check'], 'PASSED_KEYWORD_GUARD')
        page = rd.render_html(doc)
        self.assertIn('class="ai"', page)
        self.assertIn('limited &lt;b&gt;here&lt;/b&gt; &amp; elsewhere', page)
        self.assertNotIn('<b>here</b>', page)
        self.assertLess(page.index('Local deterministic statistics'), page.index('class="ai"'))

    def test_rejected_or_mismatched_inputs_are_refused(self):
        for text in ('Stock is sufficient.', 'There were 3 alerts.', '库存充足。', '', 'x' * 4001):
            with self.subTest(text=text[:20]):
                with self.assertRaises(rd.DeliveryError):
                    self.document(ai=text)
        with self.assertRaises(rd.DeliveryError):
            rd.build_document(self.preview['facts'], '0' * 64, self.basis, 'en')
        with self.assertRaises(rd.DeliveryError):
            rd.build_document(self.preview['facts'], self.preview['facts_digest'], 'not-a-basis', 'en')
        with self.assertRaises(rd.DeliveryError):
            rd.build_document(dict(self.preview['facts'], extra='C:/secret.xlsx'), self.preview['facts_digest'],
                              self.basis, 'en')

    def test_no_identifiers_paths_or_file_hashes_in_report(self):
        doc = self.document(ai='Coverage is limited.')
        text = doc.json_text + rd.render_html(doc)
        with closing(sqlite3.connect(self.db)) as conn:
            hashes = [r[0] for r in conn.execute('SELECT file_sha256 FROM source_versions')] + \
                     [r[0] for r in conn.execute('SELECT content_signature FROM source_versions')]
        for needle in SECRETS + (str(self.stock), str(self.bom), 'storage.xlsx', 'bom.xlsx', 'BOM-ONLY', *hashes):
            self.assertNotIn(needle, text)


class SaveTests(DeliveryBase):
    def test_pair_published_once_with_one_report_id_and_never_overwritten(self):
        doc = self.document('zh')
        saved = self.save(doc)
        self.assertEqual(files(self.out), [saved.folder.name])
        self.assertEqual(files(saved.folder), sorted([saved.html.name, saved.json.name]))
        raw = saved.json.read_bytes()
        self.assertEqual(raw.decode('utf-8'), doc.json_text)
        page = saved.html.read_text(encoding='utf-8')
        self.assertIn(f'<meta name="data-sha256" content="{hashlib.sha256(raw).hexdigest()}">', page)
        self.assertIn(f'<meta name="report-id" content="{doc.report_id}">', page)
        self.assertEqual(dict(saved.sha256)[saved.json.name], hashlib.sha256(raw).hexdigest())
        self.assertTrue(saved.folder.name.startswith('UNVERIFIED_AI_Report_WEEKLY_'))
        again = self.save(doc)
        self.assertEqual(again.folder.name, saved.folder.name + ' (2)')
        self.assertEqual(saved.json.read_bytes(), raw)

    def test_data_change_cleanup_or_session_change_during_staging_refuses(self):
        changes = {
            'other program sync': self.other_sync,
            'local history cleanup marker': lambda: self._cleanup_marker(),
            'Stop / Refresh invalidation': lambda: self.session.invalidate(),
        }
        for name, change in changes.items():
            with self.subTest(change=name):
                with patch.object(rd, '_checkpoint', lambda stage, c=change: stage == 'staged' and c()):
                    with self.assertRaises(rd.DeliveryStale):
                        self.save()
                self.assertEqual(files(self.out), [])
                self.tearDown(); self.setUp()

    def _cleanup_marker(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("INSERT OR REPLACE INTO schema_info VALUES ('history_retained_from', '2026-09-01 00:00:00.000')")
            conn.commit()

    def test_invalidated_session_refuses_before_writing(self):
        self.session.invalidate()
        with self.assertRaises(rd.DeliveryStale):
            self.save()
        self.assertEqual(files(self.out), [])

    def test_no_commit_can_happen_inside_the_publication_window(self):
        attempts = []

        def try_commit(stage):
            if stage != 'before_publish':
                return
            with closing(sqlite3.connect(self.db, timeout=0.2, isolation_level=None)) as writer:
                writer.execute('BEGIN IMMEDIATE')
                writer.execute("INSERT INTO schema_info VALUES ('m4f_probe', 'x')")
                try:
                    writer.execute('COMMIT')
                    attempts.append('committed')
                except sqlite3.OperationalError as exc:
                    attempts.append(str(exc))
                    writer.execute('ROLLBACK')
        with patch.object(rd, '_checkpoint', try_commit):
            saved = self.save()
        self.assertEqual(attempts, ['database is locked'])
        self.assertEqual(files(self.out), [saved.folder.name])

    def test_wal_database_is_refused_and_left_unchanged(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('PRAGMA journal_mode=WAL')
        with self.assertRaises(rd.DeliveryUnsupported):
            self.save()
        self.assertEqual(files(self.out), [])
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('PRAGMA journal_mode').fetchone()[0].lower(), 'wal')

    def test_write_publish_and_cleanup_failures(self):
        real = rd._write_verified
        with patch.object(rd, '_write_verified', lambda p, b: real(p, b) if p.suffix != '.html' else
                          (_ for _ in ()).throw(OSError('disk full'))):
            with self.assertRaises(OSError):
                self.save()
        self.assertEqual(files(self.out), [])
        with patch.object(rd, '_publish', side_effect=OSError('publish failed')), \
                patch.object(rd.shutil, 'rmtree', side_effect=PermissionError('locked by scanner')):
            with self.assertRaises(OSError) as caught:
                self.save()
        error = caught.exception
        self.assertEqual(str(error), 'publish failed')
        self.assertTrue(error.leftover.name.startswith('.mrc-report-') and error.leftover.name.endswith('.partial'))
        self.assertIn('locked by scanner', error.cleanup_warning)
        self.assertEqual(files(self.out), [error.leftover.name])  # nothing under a report name

    def test_name_race_retry_checks_again_and_never_touches_the_other_folder(self):
        doc = self.document()
        stem = rd.file_stem(doc)
        real = rd._publish

        def racing(staging, target):
            if target.name == stem:
                target.mkdir()
                (target / 'theirs.txt').write_text('not ours')
            return real(staging, target)
        with patch.object(rd, '_publish', racing), \
                patch.object(rd, '_checkpoint', lambda stage: stage == 'retry' and self.other_sync()):
            with self.assertRaises(rd.DeliveryStale):
                self.save(doc)
        self.assertEqual(files(self.out), [stem])
        self.assertEqual(files(self.out / stem), ['theirs.txt'])

    def test_missing_folder_is_refused(self):
        with self.assertRaises(rd.DeliveryError):
            rd.save_report(self.document(), self.out / 'missing', self.db, basis_of=self.session.data_basis,
                           guard=lambda: self.session.report_guard(self.epoch, self.basis))


class EmailTests(DeliveryBase):
    def setUp(self):
        super().setUp()
        self.saved = self.save(self.document('zh', ai='历史覆盖不完整，无法得出趋势结论。'))

    def parsed(self, payload):
        return message_from_bytes(payload, policy=policy.default)

    def test_mime_structure_unicode_and_exact_attachments(self):
        (self.saved.folder / 'other.txt').write_text('must not be attached')  # never scanned
        payload = rd.build_eml(self.saved, to='planner@example.com; boss@example.org')
        msg = self.parsed(payload)
        self.assertTrue(msg.is_multipart())
        self.assertEqual(msg['X-Unsent'], '1')
        self.assertEqual(msg['Content-Language'], 'zh-CN')
        self.assertEqual(msg['To'], 'planner@example.com, boss@example.org')
        self.assertTrue(msg['Subject'].startswith('[UNVERIFIED] 周报库存报告'))
        self.assertIn('Cloud Not Verified', msg['Subject'])
        body = msg.get_body(('plain',)).get_content()
        for text in ('尚未发送', 'UNVERIFIED', 'Cloud Not Verified', 'Observed Change ≠ Actual Consumption', '未知',
                     'AI 解读：作为单独的 UNVERIFIED 部分', self.saved.html.name, self.saved.json.name):
            self.assertIn(text, body)
        attachments = {part.get_filename(): part.get_content() for part in msg.iter_attachments()}
        self.assertEqual(sorted(attachments), sorted([self.saved.html.name, self.saved.json.name]))
        self.assertEqual(attachments[self.saved.json.name].encode('utf-8') if isinstance(
            attachments[self.saved.json.name], str) else attachments[self.saved.json.name], self.saved.json.read_bytes())
        self.assertNotIn(b'must not be attached', payload)

    def test_header_injection_and_bad_addresses_are_refused(self):
        for to in ('a@example.com\r\nBcc: x@evil.test', 'a@example.com\nX: y', 'not an address', 'a@b', '<a@example.com>',
                   ','.join(f'u{i}@example.com' for i in range(11))):
            with self.subTest(to=to[:30]):
                with self.assertRaises(rd.DeliveryError):
                    rd.build_eml(self.saved, to=to)
        for subject in ('ok\r\nBcc: x@evil.test', 'line\nbreak', 'tab\tchar', '', 'x' * 201, 'sep\u2028x'):
            with self.subTest(subject=subject[:20]):
                with self.assertRaises(rd.DeliveryError):
                    rd.build_eml(self.saved, subject=subject)
        msg = self.parsed(rd.build_eml(self.saved, to=''))
        self.assertIsNone(msg['To'])
        self.assertIsNone(msg['Bcc'])

    def test_changed_saved_report_is_refused(self):
        self.saved.json.write_text('{}', encoding='utf-8')
        with self.assertRaises(rd.DeliveryStale):
            rd.build_eml(self.saved)

    def test_draft_contains_no_source_data_and_three_languages_differ(self):
        payload = rd.build_eml(self.saved)
        decoded = b''.join(part.get_payload(decode=True) or b'' for part in self.parsed(payload).walk())
        for needle in SECRETS + (str(self.stock), 'storage.xlsx'):
            self.assertNotIn(needle.encode('utf-8'), decoded)
        self.assertNotIn(b'PK\x03\x04', decoded)  # no workbook (zip) attached
        bodies = set()
        for lang in ('en', 'zh', 'ms'):
            saved = self.save(self.document(lang))
            bodies.add(self.parsed(rd.build_eml(saved)).get_body(('plain',)).get_content())
        self.assertEqual(len(bodies), 3)

    def test_save_eml_never_overwrites_and_refuses_bad_targets(self):
        payload = rd.build_eml(self.saved)
        target = self.out / 'draft.eml'
        target.write_bytes(b'existing')
        written = rd.save_eml(payload, target)
        self.assertEqual(written.name, 'draft (2).eml')
        self.assertEqual(target.read_bytes(), b'existing')
        self.assertEqual(written.read_bytes(), payload)
        with self.assertRaises(rd.DeliveryError):
            rd.save_eml(payload, self.out / 'draft.txt')
        with self.assertRaises(rd.DeliveryError):
            rd.save_eml(payload, self.out / 'missing' / 'x.eml')
        with patch.object(rd, '_write_verified', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                rd.save_eml(payload, self.out / 'fail.eml')
        self.assertFalse(any(p.name.endswith('.partial') for p in self.out.iterdir()))
        self.assertFalse((self.out / 'fail.eml').exists())

    def test_nothing_touches_the_network_or_a_mail_server(self):
        source = Path(rd.__file__).read_text(encoding='utf-8')
        for word in ('smtplib', 'socket', 'subprocess', 'webbrowser', 'startfile', 'urllib', 'http.client'):
            self.assertNotIn(word, source)
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network used')):
            rd.save_eml(rd.build_eml(self.saved, to='a@example.com'), self.out / 'net.eml')
            self.save(self.document())
        self.assertEqual(self.service.calls + self.service.balance_calls, [])


class DeliveryUiTests(m4f.ReportDialogTests):
    """The real launcher/report tab (dialogs answered by the test, never shown to a person). Reuses the M4F dialog
    fixture; its own tests are not re-run here."""

    def save_via_ui(self, folder):
        with patch('checker.assistant_ui.filedialog.askdirectory', return_value=str(folder)):
            self.host.save_report()

    def test_save_without_ai_then_draft(self):
        self.host.report_epoch = self.session.epoch
        out = self.base / 'out'; out.mkdir()
        self.assertEqual(str(self.host.view.report_ai_check.cget('state')), 'normal' if self.host.valid_narrative()
                         else 'disabled')
        self.save_via_ui(out)
        self.pump(lambda: self.host.report_saved is not None)
        saved = self.host.report_saved
        self.assertIsNone(json.loads(saved.json.read_text(encoding='utf-8'))['ai_interpretation'])
        self.host.email_draft()
        self.pump(lambda: getattr(self.host, 'email_window', None) is not None)
        target = out / 'draft.eml'
        with patch('checker.assistant_ui.filedialog.asksaveasfilename', return_value=str(target)):
            save = next(w for w in self.walk(self.host.email_window) if isinstance(w, tk.ttk.Button) and
                        'eml' in str(w.cget('text')))
            save.invoke()
        self.pump(lambda: target.exists())
        msg = message_from_bytes(target.read_bytes(), policy=policy.default)
        self.assertEqual(sorted(p.get_filename() for p in msg.iter_attachments()), sorted([saved.html.name, saved.json.name]))
        self.assertEqual(self.service.calls + self.service.balance_calls, [])

    def walk(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self.walk(child)

    def test_valid_ai_interpretation_is_included_only_when_ticked(self):
        self.host.report_epoch = self.session.epoch
        seen = []
        self.root.after(40, lambda: self.answer_dialog(True, seen))
        self.host.send_report()
        self.pump(lambda: not self.session.busy and self.host.report_narrative is not None)
        self.root.update()
        self.assertEqual(str(self.host.view.report_ai_check.cget('state')), 'normal')
        out = self.base / 'out'; out.mkdir()
        self.save_via_ui(out)
        self.pump(lambda: self.host.report_saved is not None)
        self.assertIsNone(json.loads(self.host.report_saved.json.read_text(encoding='utf-8'))['ai_interpretation'])
        self.host.report_saved = None
        self.host.view.report_include_ai.set(True)
        self.save_via_ui(out)
        self.pump(lambda: self.host.report_saved is not None)
        data = json.loads(self.host.report_saved.json.read_text(encoding='utf-8'))
        self.assertEqual(data['ai_interpretation']['text'], 'The recorded history is limited.')
        self.assertEqual(data['facts'], self.host.report_facts)

    def test_rejected_ai_reply_is_never_kept(self):
        self.host.report_epoch = self.session.epoch
        self.service.steps = iter([(200, response(text='Stock is sufficient; production can proceed.'))])
        seen = []
        self.root.after(40, lambda: self.answer_dialog(True, seen))
        self.host.send_report()
        self.pump(lambda: not self.session.busy and bool(self.service.calls))
        self.root.update()
        self.assertIsNone(self.host.report_narrative)
        self.assertEqual(str(self.host.view.report_ai_check.cget('state')), 'disabled')

    def test_stale_or_invalidated_report_cannot_be_saved(self):
        self.host.report_epoch = self.session.epoch
        out = self.base / 'out'; out.mkdir()
        workbook(self.stock, [('Stock', stock_rows([('A', 1)]))])
        self.assertEqual(InventorySync(self.db, settle_seconds=0, clock=self.clock).sync_role(
            'stock', str(self.stock), 'manual').outcome, IMPORTED)
        self.save_via_ui(out)
        self.pump(lambda: self.host.report_facts is None)
        self.assertEqual(files(out), [])
        self.assertTrue(any('not saved' in text for _s, text in self.host.messages))
        self.host.invalidate()
        self.root.update()
        self.assertEqual(str(self.host.view.report_save_button.cget('state')), 'disabled')
        with patch('checker.assistant_ui.filedialog.askdirectory') as ask:
            self.host.save_report()
        ask.assert_not_called()

    def test_repeated_clicks_run_one_task_and_close_drops_late_results(self):
        self.host.report_epoch = self.session.epoch
        out = self.base / 'out'; out.mkdir()
        release, real = threading.Event(), rd.save_report

        def held(*args, **kwargs):
            release.wait(10)
            return real(*args, **kwargs)
        errors = []
        self.root.report_callback_exception = lambda *exc: errors.append(exc)
        with patch.object(rd, 'save_report', held):
            self.save_via_ui(out)
            for _ in range(5):
                self.save_via_ui(out)
            self.assertEqual(self.host.delivery.threads_started, 1)
            self.assertTrue(any('still being written' in text for _s, text in self.host.messages))
            self.host.close()
            release.set()
            deadline = time.monotonic() + 5
            while self.host.delivery.running and time.monotonic() < deadline:
                time.sleep(0.02)
            for _ in range(10):
                self.root.update(); time.sleep(0.01)
        self.assertEqual(errors, [])
        self.assertTrue(self.host.delivery.events.empty())
        # Closing revoked the session, so the in-flight save was refused at its final check: nothing published, nothing partial.
        self.assertEqual(files(out), [])


class DeliveryRaceTests(DeliveryUiTests):
    """P1-DL1: a save result belongs to the exact preview it was submitted from (generation, facts digest, basis,
    session epoch, output language, included AI text). Older results stay on disk but are never attached to a newer
    preview, and the e-mail handler checks this itself, not only the button."""

    def build(self, period_index):
        self.host.view.report_period.current(period_index)
        before = self.host.report_generation
        self.host.build_report()
        self.pump(lambda: not self.session.busy and self.host.report_facts is not None and
                  self.host.report_generation > before)
        return self.host.report_facts

    def paused_save(self, folder):
        """Start a real save and hold it after both files are staged. Returns (release, staged)."""
        staged, release = threading.Event(), threading.Event()

        def checkpoint(stage):
            if stage == 'staged':
                staged.set()
                release.wait(10)
        self.patcher = patch.object(rd, '_checkpoint', checkpoint)
        self.patcher.start()
        self.save_via_ui(folder)
        self.assertTrue(staged.wait(10))
        return release

    def finish_save(self, release):
        release.set()
        self.pump(lambda: not self.host.delivery.busy and self.host.delivery.events.empty())
        self.patcher.stop()
        self.root.update()

    def assert_draft_refused(self):
        self.assertIsNone(self.host.saved_report())
        self.pump(lambda: str(self.host.view.report_email_button.cget('state')) == 'disabled')  # next poll tick
        started = self.host.delivery.threads_started
        self.host.email_draft()  # the handler refuses on its own, whatever the button says
        self.assertEqual(self.host.delivery.threads_started, started)
        self.assertEqual(self.host.messages[-1][1], tr('report_need_save', self.host.language))

    def test_daily_save_finishing_after_a_weekly_preview_is_not_attached_to_it(self):
        self.assertEqual(self.build(0)['period'], 'DAILY')
        out = self.base / 'out'; out.mkdir()
        release = self.paused_save(out)
        self.assertEqual(self.build(1)['period'], 'WEEKLY')  # built while the daily save is staged
        self.finish_save(release)
        saved_files = [p for p in out.iterdir()]
        self.assertEqual(len(saved_files), 1)  # the requested daily report was published and kept on disk
        self.assertIn('_DAILY_', saved_files[0].name)
        self.assertEqual(self.host.report_facts['period'], 'WEEKLY')
        self.assertIsNone(self.host.report_saved)
        self.assertTrue(any('belongs to an earlier preview' in text for _s, text in self.host.messages))
        self.assert_draft_refused()

    def test_same_period_regeneration_during_a_save_is_a_different_preview(self):
        self.build(1)
        out = self.base / 'out'; out.mkdir()
        release = self.paused_save(out)
        generation = self.host.report_generation
        self.build(1)  # WEEKLY again: same period, same data, but a new preview
        self.assertGreater(self.host.report_generation, generation)
        self.finish_save(release)
        self.assertEqual(len(list(out.iterdir())), 1)
        self.assertIsNone(self.host.report_saved)
        self.assert_draft_refused()

    def test_old_job_failure_never_clears_a_newer_preview(self):
        self.build(1)
        out = self.base / 'out'; out.mkdir()
        release = self.paused_save(out)
        workbook(self.stock, [('Stock', stock_rows([('A', 3)]))])
        self.assertEqual(InventorySync(self.db, settle_seconds=0, clock=self.clock).sync_role(
            'stock', str(self.stock), 'manual').outcome, IMPORTED)
        data = finish(self.session, 'preview_data')       # re-authorise the new data (same session epoch rules)
        finish(self.session, 'authorize', expected_basis=data['basis'])
        self.root.update()
        newer = self.build(1)
        self.finish_save(release)
        self.assertEqual(list(out.iterdir()), [])          # the old save was refused at its final check
        self.assertIs(self.host.report_facts, newer)       # ...and did not clear the newer preview
        self.assertTrue(any('not saved' in text for _s, text in self.host.messages))

    def test_language_switch_or_ai_choice_change_detaches_the_saved_report(self):
        self.build(1)
        seen = []
        self.root.after(40, lambda: self.answer_dialog(True, seen))
        self.host.send_report()
        self.pump(lambda: not self.session.busy and self.host.report_narrative is not None)
        out = self.base / 'out'; out.mkdir()
        self.save_via_ui(out)                               # saved WITHOUT the AI text, in English
        self.pump(lambda: self.host.saved_report() is not None)
        saved = self.host.saved_report()
        self.host.language = 'ms'                           # another output language
        self.root.update()
        self.assert_draft_refused()
        self.host.language = 'en'                           # exactly the saved presentation again
        self.root.update()
        self.assertIs(self.host.saved_report(), saved)
        self.host.view.report_include_ai.set(True)          # now the AI text would be included: not the saved file
        self.root.update()
        self.assert_draft_refused()
        self.save_via_ui(out)
        self.pump(lambda: self.host.saved_report() is not None)
        with_ai = self.host.saved_report()
        self.assertIsNot(with_ai, saved)
        self.assertIsNotNone(json.loads(with_ai.json.read_text(encoding='utf-8'))['ai_interpretation'])
        self.host.report_narrative = dict(self.host.report_narrative, text='A different accepted interpretation.')
        self.root.update()                                  # a new AI text is a different presentation
        self.assert_draft_refused()


for _cls in (DeliveryUiTests, DeliveryRaceTests):
    for _name in [n for n in dir(m4f.ReportDialogTests) if n.startswith('test')]:
        if _name not in _cls.__dict__ and _name not in DeliveryUiTests.__dict__:
            setattr(_cls, _name, None)  # not collected: callable() is False
for _name in [n for n in DeliveryUiTests.__dict__ if n.startswith('test')]:
    setattr(DeliveryRaceTests, _name, None)  # the race class runs only its own tests
del _cls, _name  # loop names must not stay as module attributes (the loader would collect the class twice)
