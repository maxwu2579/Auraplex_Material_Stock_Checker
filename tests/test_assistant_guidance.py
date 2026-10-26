"""Guidance and alert-size regressions. Synthetic databases; no real network, key or Tk root."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from checker import agent_tools
from checker.agent import Agent, ModelReply
from checker.agent_tools import InventoryTools, encoded
from checker.assistant import render
from checker.assistant_ui import AssistantLauncher, AssistantView
from checker.assistant_language import tr, tool_error_text
from tests.test_m4c import ScriptedProvider, invoke
from tests.test_m32d import DailyBase
from tests.test_m32c import stock_with_threshold
from tests.fixtures import workbook


class GuidanceTests(unittest.TestCase):
    def test_no_tool_reply_becomes_fixed_guidance_never_model_claim(self):
        for question, key in [('查询材料历史，编号', 'ask_history'), ('查询产品试算缺口，产品', 'ask_product'),
                              ('check stock for A', 'ask_stock')]:
            p=ScriptedProvider(ModelReply(text='A stock is 99999; READY FOR PRODUCTION'))
            result=Agent(SimpleNamespace(generation=1),p).run(question)
            self.assertEqual(result['status'],'NEEDS_INPUT')
            self.assertEqual(result['guidance'],key)
            self.assertEqual(result['evidence'],[])
            for lang in ('en','zh','ms'):
                text=render(result,lang)
                self.assertEqual(text,tr(key,lang))
                self.assertNotIn('99999',text)
                self.assertNotIn('NO_TOOL_EVIDENCE',text)

    def test_unfinished_quick_draft_is_not_sent_and_keeps_input(self):
        for question in ('查询材料历史，编号 ', '查询产品试算缺口，产品 ', 'How much stock is recorded for '):
            box=SimpleNamespace(get=Mock(return_value=question),delete=Mock())
            host=SimpleNamespace(view=SimpleNamespace(input=box),session=SimpleNamespace(busy=False),language='zh',
                                 append=Mock(),start=Mock(),_language_for=Mock())
            AssistantLauncher.send(host)
            host.start.assert_not_called()
            box.delete.assert_not_called()
            self.assertNotIn('NO_TOOL_EVIDENCE',str(host.append.call_args))

    def test_quick_options_show_parameter_guidance_without_sending(self):
        for lang in ('en','zh','ms'):
            for index in (0,2,3):
                host=SimpleNamespace(language=lang,append=Mock(),send=Mock())
                view=SimpleNamespace(host=host,quick=SimpleNamespace(current=lambda:index),
                                     input=SimpleNamespace(delete=Mock(),insert=Mock(),focus_set=Mock()))
                AssistantView._quick(view)
                host.append.assert_called_once()
                host.send.assert_not_called()

    def test_limit_errors_use_distinct_local_messages_and_no_model_retry(self):
        for reason,key in [('RESULT_TOO_LARGE','query_too_large'),('QUERY_TIMEOUT','query_timeout')]:
            for lang in ('en','zh','ms'):
                self.assertEqual(tool_error_text({'code':'LIMIT_EXCEEDED','reason':reason},lang),tr(key,lang))
        item=InventoryTools._error('get_stock_alerts','LIMIT_EXCEEDED','test',reason='RESULT_TOO_LARGE')
        tools=SimpleNamespace(generation=1,call=lambda *a,**kw:item)
        provider=ScriptedProvider(invoke('get_stock_alerts',{}))
        result=Agent(tools,provider).run('Show low stock alerts')
        self.assertEqual(result['status'],'NEEDS_ACTION')
        self.assertEqual(len(provider.messages),1)
        self.assertIn(tr('query_too_large','zh'),render(result,'zh'))


class AlertSummaryTests(DailyBase):
    def prepare(self,count=160):
        workbook(self.stock,[('Stock',stock_with_threshold([(f'DEMO-{n:03}',0,5) for n in range(count)]))])
        self.verify_all()
        self.tools=InventoryTools(self.db)
        self.tools.authorize_cached()

    def test_many_alerts_return_complete_counts_and_bounded_details(self):
        self.prepare()
        result=self.tools.call('get_stock_alerts',{})
        self.assertTrue(result['ok'],result)
        data=result['data'];state=data['recorded']
        self.assertEqual(state['active_counts']['OUT_OF_STOCK'],160)
        self.assertEqual(state['active_counts']['LOW_STOCK'],160)
        self.assertLessEqual(len(state['rows']),20)
        self.assertGreater(state['total_rows'],len(state['rows']))
        self.assertTrue(data['truncated'])
        self.assertLessEqual(len(encoded(result).encode('utf-8')),agent_tools.MAX_BYTES)
        text=render({'status':'TOOL_RESULTS','evidence':[result]},'zh')
        self.assertIn('160',text)
        self.assertNotIn('LIMIT_EXCEEDED',text)
        self.assertIn(tr('c_capped','zh').format(loaded=len(state['rows']),total=state['total_rows']),text)

    def test_byte_budget_reduces_rows_not_aggregate_counts(self):
        self.prepare(30)
        with patch.object(agent_tools,'MAX_BYTES',15000):
            result=self.tools.call('get_stock_alerts',{})
        self.assertTrue(result['ok'],result)
        self.assertLess(len(result['data']['recorded']['rows']),20)
        self.assertEqual(result['data']['recorded']['active_counts']['LOW_STOCK'],30)
        self.assertLessEqual(len(encoded(result).encode('utf-8')),15000)

    def test_remaining_oversize_error_keeps_hard_limit_and_reason(self):
        self.prepare(2)
        with patch.object(agent_tools,'MAX_BYTES',100):
            result=self.tools.call('get_stock_alerts',{})
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'],'LIMIT_EXCEEDED')
        self.assertEqual(result['error']['reason'],'RESULT_TOO_LARGE')
