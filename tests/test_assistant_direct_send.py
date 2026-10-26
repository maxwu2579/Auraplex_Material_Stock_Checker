"""Direct Send UX: synthetic databases and fake transport only."""
import threading
from unittest.mock import patch
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from checker.assistant import AssistantSession
from checker.assistant_ui import AssistantLauncher
from checker.providers import DeepSeekProvider
from tests.test_m4e import FakeKeys, wait_session
from tests.test_m31 import Base
from tests import test_m4e as existing
from tests.test_m4d import FakeService, response


class DirectSessionTests(Base):
    def setUp(self):
        Base.setUp(self)
        self.sync('stock'); self.sync('bom')
        self.keys, self.service = FakeKeys(), FakeService()
        self.provider = DeepSeekProvider(key_store=self.keys, transport=self.service)
        self.session = AssistantSession(self.db, key_store=self.keys, provider=self.provider)

    def tearDown(self):
        self.session.close()
        wait_session(self.session)
        Base.tearDown(self)

    act = existing.SessionTests.act

    def test_first_send_and_second_send_need_no_dialog_or_quota_reset(self):
        self.service.steps = iter([(200, response()), (200, response())])
        self.assertEqual(self.act('current_chat', question='check stock')['status'], 'NEEDS_SELECTION')
        self.assertTrue(self.session.authorized)
        self.assertTrue(self.session.outbound)
        self.act('current_chat', question='check again')
        self.assertEqual(len(self.service.calls), 2)
        self.assertEqual(self.provider.requests_used, 2)

    def test_invalidation_then_next_send_rebinds_without_network_retry(self):
        self.act('load_current')
        before = self.session._authorized_basis
        self.session.invalidate()
        self.sync('stock')
        self.act('current_chat', question='check stock')
        self.assertNotEqual(before, self.session._authorized_basis)
        self.assertTrue(self.session.authorized)
        self.assertEqual(len(self.service.calls), 1)

    def test_database_change_during_request_rejects_old_result(self):
        def changed(body, options):
            self.sync('stock')
            return 200, response()
        self.service.steps = iter([changed])
        result = self.act('current_chat', question='check stock')
        self.assertEqual(result['error'], 'STALE_DATA')
        self.assertFalse(self.session.authorized)
        self.assertEqual(len(self.service.calls), 1)

    def test_empty_question_never_reads_key_or_sends(self):
        self.assertEqual(self.act('current_chat', question='')['error'], 'INVALID_QUESTION')
        self.assertEqual(self.keys.reads, 0)
        self.assertFalse(self.service.calls)

    def test_database_failure_never_reads_key_or_sends(self):
        with patch.object(self.session.tools, 'basis', side_effect=OSError('synthetic')):
            self.assertEqual(self.act('current_chat', question='check stock')['error'], 'DATABASE_READ_FAILED')
        self.assertEqual(self.keys.reads, 0)
        self.assertFalse(self.service.calls)

    def test_cancel_during_preparation_cannot_restore_session(self):
        entered, release = threading.Event(), threading.Event()
        original = self.session._context
        def held(basis):
            entered.set()
            if not release.wait(3):
                raise AssertionError('test release missing')
            return original(basis)
        with patch.object(self.session, '_context', side_effect=held):
            self.assertTrue(self.session.submit('current_chat', question='check stock'))
            self.assertTrue(entered.wait(3))
            self.session.invalidate()
            release.set()
            existing.wait_session(self.session)
        self.assertFalse(self.session.authorized)
        self.assertFalse(self.session.outbound)
        self.assertFalse(self.service.calls)
        self.assertEqual(self.keys.reads, 0)


class DirectViewTests(Base):
    def setUp(self):
        Base.setUp(self); self.sync('stock'); self.sync('bom')
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
        self.root.destroy(); Base.tearDown(self)

    pump = existing.ViewTests.pump

    def test_send_without_permissions_stays_in_chat_on_candidates(self):
        self.write_stock([('A-1', 1), ('A-10', 10)])
        self.sync('stock')
        self.service.steps = iter([(200, response('search_materials', {'text': 'A-1'}))])
        view = self.host.view
        view.input.insert('1.0', 'Check A-1')
        with patch('checker.assistant_ui.messagebox.askyesno', side_effect=AssertionError('no consent modal')):
            self.host.send()
            self.pump(lambda: bool(self.host.candidates))
        self.assertEqual(view.tabs.select(), str(view.chat_page))
        self.assertEqual(len(self.host.candidates), 2)
        self.assertEqual(view.input.get('1.0', 'end-1c'), '')
        self.assertFalse(view.ai_button.winfo_manager())

    def test_failed_send_preserves_question(self):
        self.service.steps = iter([(401, b'fake invalid key')])
        self.host.view.input.insert('1.0', 'Check stock')
        self.host.send()
        self.pump(lambda: not self.session.busy and 'FAILED' in self.host.view.transcript.get('1.0', 'end'))
        self.assertEqual(self.host.view.input.get('1.0', 'end-1c'), 'Check stock')
        self.assertEqual(len(self.service.calls), 1)
