"""Readable chat answers, AI reports and daily summaries. Synthetic workbooks, temporary SQLite, fake key/transport.

Checks that the short summaries keep the deterministic facts: correct quantity and location, blank/text/duplicate/
not-found never shown as stock, source switches and first imports never shown as stock activity, overlapping or
unknown alert counts never summed or zeroed, and the same facts in every language, with full details still available.
"""
from contextlib import closing
from datetime import date
import gc
import html
import json
import re
import sqlite3
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import patch

from checker import agent_tools, daily, daily_preview, narrative, readable, report_delivery as rd
from checker.assistant import SYNC_STATES, AssistantSession, render, render_details
from checker.assistant_language import tr
from checker.assistant_ui import AssistantLauncher
from checker.providers import DeepSeekProvider
from checker.sync import IMPORTED, UNAVAILABLE, InventorySync
from tests.fixtures import bom_rows, stock_rows, workbook
from tests.test_m31 import Base
from tests.test_m32c import stock_with_threshold
from tests.test_m32c_remediation import SessionUiBase
from tests.test_m32d import TZ, DailyBase
from tests.test_m4d import FakeService, response
from tests.test_m4e import FakeKeys, wait_session
from tests.test_m4f import finish
from tests.test_m4f_delivery import DeliveryBase

LANGS = ('en', 'zh', 'ms')


def numbers(text):
    """Every number in a text, in order: the same facts must give the same numbers in every language."""
    return re.findall(r'\d+', text)


class ChatAnswerTests(Base):
    def setUp(self):
        super().setUp()
        self.write_stock([('A', 100), ('BL', None), ('TX', '0+10'), ('D', 2), ('D', 3)] +
                         [(f'P-{n}', n) for n in range(1, 13)])
        self.write_bom([('A', 2), ('BL', 1), ('D', 1), ('ZZ', 4)])
        self.sync('stock'); self.sync('bom')
        self.keys, self.service = FakeKeys(), FakeService()
        self.session = AssistantSession(self.db, key_store=self.keys,
                                        provider=DeepSeekProvider(key_store=self.keys, transport=self.service))
        self.authorize()

    def tearDown(self):
        self.session.close(); wait_session(self.session)
        super().tearDown()

    def act(self, action, **payload):
        self.assertTrue(self.session.submit(action, **payload))
        events = wait_session(self.session)
        self.assertEqual(len(events), 1)
        return events[0].result

    def authorize(self):
        preview = self.act('preview_data')
        self.assertEqual(self.act('authorize', expected_basis=preview['basis'])['status'], 'AUTHORIZED')

    def stock_answer(self, material):
        found = self.act('local', tool='search_materials', text=material)
        token = next(c['token'] for c in found['candidates'] if c['row']['material_id'] == material)
        return self.act('local', tool='get_stock', candidate=token)

    def test_plain_material_answer_is_short_with_quantity_location_and_one_status_line(self):
        result = self.stock_answer('A')
        for lang in LANGS:
            text = render(result, lang)
            self.assertIn('A · Fixture material', text)
            self.assertIn(f"{tr('raw', lang)}{'：' if lang == 'zh' else ': '}100", text)
            self.assertIn('Rack 1 / Level 2', text)
            self.assertIn(tr('c_source_row', lang).format(sheet='Stock', row=15), text)
            self.assertEqual(text.count('Cloud Not Verified'), 1)   # one status line, no repeated disclaimers
            self.assertLessEqual(len(text.splitlines()), 8)
            for technical in (str(self.stock), str(self.stock.resolve()), 'sha256', 'basis=', '"tool"', 'v1 ·',
                              tr('recorded_only', lang)):
                self.assertNotIn(technical, text)
            details = render_details(result, lang)       # nothing is dropped: it moved to Evidence
            for kept in (str(self.stock.resolve()), 'sha256=', 'basis=', '"evidence"', tr('recorded_only', lang)):
                self.assertIn(kept, details)
        self.assertEqual(result['evidence'][0]['data']['rows'][0]['quantity'], 100)  # evidence itself unchanged

    def test_blank_text_duplicate_and_not_found_are_never_stock_values(self):
        blank, text, duplicate = self.stock_answer('BL'), self.stock_answer('TX'), self.stock_answer('D')
        missing = {'status': 'TOOL_RESULTS', 'evidence': [self.session.tools.call('get_stock', {'material_id': 'NOPE-1'})]}
        for lang in LANGS:
            colon = '：' if lang == 'zh' else ': '
            shown = render(blank, lang)
            self.assertIn(tr('c_blank', lang), shown)
            self.assertNotIn(f"{tr('raw', lang)}{colon}0", shown)
            self.assertIn(tr('c_text_qty', lang).format(raw='0+10'), render(text, lang))
            shown = render(duplicate, lang)
            self.assertIn(tr('c_duplicate', lang).format(id='D', count=2), shown)
            self.assertIn(f"{tr('raw', lang)}{colon}2", shown)
            self.assertIn(f"{tr('raw', lang)}{colon}3", shown)
            self.assertNotIn(f"{tr('raw', lang)}{colon}5", shown)              # never added together
            shown = render(missing, lang)
            self.assertIn(tr('c_not_found', lang).format(id='NOPE-1'), shown)
            self.assertNotIn(tr('raw', lang), shown)

    def test_ambiguous_candidates_are_short_counted_and_need_a_choice(self):
        found = self.act('local', tool='search_materials', text='P-')
        self.assertEqual(found['evidence'][0]['data']['total'], 12)
        for lang in LANGS:
            text = render(found, lang)
            self.assertIn(tr('c_candidates', lang).format(total=12), text)
            self.assertIn(tr('select', lang), text)
            self.assertEqual(sum(line.startswith('• ') for line in text.splitlines()), 8)
            self.assertIn(tr('c_shown', lang).format(shown=8, total=12), text)
            details = render_details(found, lang)
            self.assertTrue(all(f'• P-{n} ' in details for n in range(1, 13)))

    def test_estimate_leads_with_counts_and_main_shortages_from_the_unchanged_m2_result(self):
        product = self.act('local', tool='search_products', text='PRODUCT')['candidates'][0]['token']
        result = self.act('local', tool='estimate_requirements', candidate=product, stock_sheet='Stock', quantity=60)
        calc = result['evidence'][0]['data']['calculation']
        a = next(r for r in calc['rows'] if r['bom']['code'] == 'A')
        self.assertEqual((a['category'], a['required'], a['shortage']), ('SHORTAGE', '120', '20'))
        for lang in LANGS:
            text = render(result, lang)
            self.assertIn(tr('c_estimate', lang).format(product='PRODUCT-1', count=60, short=1, exceptions=3,
                                                        enough=0), text)
            self.assertIn(f"{tr('required', lang)} 120 · {tr('shortage', lang)} 20", text)
            self.assertIn(tr('c_exc_title', lang), text)
            self.assertIn(tr('c_estimate_note', lang), text)
            self.assertNotIn(tr('c_no_short', lang), text)
            self.assertIn('STOCK_NOT_FOUND', render_details(result, lang))   # codes stay in the details

    def test_several_tools_share_one_status_line_and_a_failed_sync_is_stated(self):
        stock = self.stock_answer('A')
        token = next(c['token'] for c in self.act('local', tool='search_materials', text='A')['candidates']
                     if c['row']['material_id'] == 'A')
        history = self.act('local', tool='material_history', candidate=token, days=30)
        combined = {'status': 'TOOL_RESULTS', 'evidence': stock['evidence'] + history['evidence']}
        for lang in LANGS:
            text = render(combined, lang)
            self.assertEqual(text.count('Cloud Not Verified'), 1)
            self.assertEqual(text.count(tr('c_details', lang)), 1)
            self.assertIn(tr('c_history_short', lang).split('{')[0], text)  # incomplete history stated, no trend
        self.stock.unlink()
        self.sync('stock')                                                   # recorded failure, earlier data kept
        self.authorize()
        stale = self.stock_answer('A')
        finished = self.query("SELECT finished_at FROM sync_runs WHERE role = 'stock' ORDER BY id DESC LIMIT 1")[0][0]
        for lang in LANGS:
            text = render(stale, lang)
            self.assertIn(tr('c_stale_unavailable', lang).format(role=readable.label(readable.ROLE, 'stock', lang),
                                                     time=readable.local_time(finished)), text)
            self.assertIn(f"{tr('raw', lang)}{'：' if lang == 'zh' else ': '}100", text)


class SourceSwitchTests(DailyBase):
    """storage.xlsx → another workbook: the record differences are a source switch, not stock activity."""

    def switch(self):
        self.verify_all()                                                    # first import: a baseline
        workbook(self.stock, [('Stock', stock_with_threshold([('A', 0, 5), ('B', 2, 5), ('C', 10, 2)]))])
        self.assertEqual(self.sync().outcome, IMPORTED)                      # B 3 → 2 in the same file
        self.other = self.stock.with_name('storage_switch.xlsx')
        workbook(self.other, [('Stock', stock_with_threshold([(f'T{n}', n + 1, 1) for n in range(20)] + [('A', 1, 5)]))])
        self.assertEqual(self.inv.sync_role('stock', str(self.other), 'manual').outcome, IMPORTED)
        return self.generate(self.evaluate())

    def test_daily_summary_keeps_switch_differences_separate_and_reconciled(self):
        summary = self.switch()
        c = summary.data()['changes']
        self.assertEqual((c['same_source']['total'], c['cross_source']['total'], c['total']), (1, 23, 24))
        for kind in daily.CHANGE_TYPES:
            self.assertEqual(c['same_source']['by_type'][kind]['changes'] + c['cross_source']['by_type'][kind]['changes'],
                             c['by_type'][kind]['changes'])
        self.assertEqual(c['cross_source']['by_type']['ADDED']['changes'], 20)
        self.assertEqual(c['cross_source']['by_type']['REMOVED']['changes'], 2)
        with closing(sqlite3.connect(self.db)) as conn:                     # an independent count of the raw rows
            crossed = conn.execute('SELECT count(*) FROM inventory_changes c JOIN inventory_snapshots s'
                                   ' ON s.id = c.snapshot_id WHERE s.same_source_path = 0').fetchone()[0]
        self.assertEqual(crossed, 23)
        for lang in LANGS:
            text = daily_preview.summary_text(summary, lang)
            same = readable.tx('changes_line', lang, events=1, ids=1,
                               parts=f"{readable.label(readable.CHANGE, 'QUANTITY_CHANGED', lang)} 1")
            self.assertIn(same, text)
            self.assertIn('storage.xlsx → storage_switch.xlsx', text)
            switch_line = next(line for line in text.splitlines() if '→ storage_switch.xlsx' in line)
            self.assertIn(f"{readable.label(readable.CHANGE, 'ADDED', lang)} 20", switch_line)
            self.assertIn('23', switch_line)
            self.assertNotRegex(text, r'(?<!\d)24(?!\d)')                  # never one mixed total in the summary
            self.assertIn(readable.tx('d_baseline', lang), text)
            self.assertNotIn(str(self.other.resolve()), text)                # full paths stay in the details
            self.assertIn(str(self.other.resolve()), daily_preview.render(summary, lang))
        page = daily.render_html(summary)
        self.assertLess(page.index('<h2>Summary</h2>'), page.index('<details>'))
        self.assertIn('Differences caused by switching the source file', page)
        self.assertIn(html.escape(readable.tx('changes_line', 'en', events=1, ids=1, parts='quantity changed 1')), page)

    def test_report_facts_split_the_same_counts_and_refuse_a_mismatch(self):
        self.switch()
        facts = self.read(narrative.build_in, 'daily', now=self.clock.now)
        current = facts['current_period']
        self.assertEqual((current['same_source']['events'], current['cross_source']['events'],
                          current['observed_change_events'], current['source_switches'], current['baseline_snapshots']),
                         (1, 23, 24, 1, 1))
        for lang in LANGS:
            text = readable.text(readable.report_sections(facts, lang))
            self.assertIn(readable.tx('changes_line', lang, events=1, ids=1,
                                      parts=f"{readable.label(readable.CHANGE, 'QUANTITY_CHANGED', lang)} 1"), text)
            self.assertIn(readable.tx('rv_switch', lang), text)
            self.assertNotRegex(text, r'(?<!\d)24(?!\d)')
        payload = json.dumps(narrative.request_payload(facts, 'en', 'deepseek-flash', 512), ensure_ascii=False)
        self.assertIn('cross_source', payload)
        self.assertNotIn('storage_switch', payload)                          # still counts only, no names
        tampered = json.loads(json.dumps(facts))
        tampered['current_period']['cross_source']['events'] -= 1
        tampered['current_period']['cross_source']['changes_by_type']['ADDED']['events'] -= 1
        with self.assertRaises(ValueError):
            narrative.validate_facts(tampered)                               # a hidden difference cannot pass

    def test_a_first_import_alone_is_a_baseline_not_stock_received(self):
        self.verify_all()
        summary = self.generate(self.evaluate())
        facts = self.read(narrative.build_in, 'daily', now=self.clock.now)
        self.assertEqual(summary.data()['changes']['total'], 0)
        self.assertEqual(facts['current_period']['baseline_snapshots'], 1)
        for lang in LANGS:
            text = daily_preview.summary_text(summary, lang)
            self.assertIn(readable.tx('d_baseline', lang), text)
            self.assertNotIn(readable.tx('d_no_change', lang), text)        # history starts today: no conclusion
            report = readable.text(readable.report_sections(facts, lang))
            self.assertIn(readable.tx('baseline_line', lang, count=1), report)
            for conclusion in ('changes_none', 'changes_no_snapshot'):
                self.assertNotIn(readable.tx(conclusion, lang), report)


class AlertAndUnknownTests(DailyBase):
    def test_overlapping_alert_categories_are_material_ids_never_a_sum(self):
        summary = self.generate(self.verify_all())                           # A: zero and low; B: low
        facts = self.read(narrative.build_in, 'daily', now=self.clock.now)
        self.assertEqual(facts['recorded_alerts']['distinct_material_ids_any_type'], 2)
        for lang in LANGS:
            for text in (daily_preview.summary_text(summary, lang),
                         readable.text(readable.report_sections(facts, lang))):
                zero = readable.tx('alert_line', lang, label=readable.label(readable.ALERT, 'OUT_OF_STOCK', lang),
                                   ids=1, alerts=1)
                low = readable.tx('alert_line', lang, label=readable.label(readable.ALERT, 'LOW_STOCK', lang),
                                  ids=2, alerts=2)
                self.assertIn(zero, text)
                self.assertIn(low, text)
                self.assertIn(readable.tx('alerts_any', lang, count=2), text)
                self.assertNotIn(readable.tx('alerts_any', lang, count=3), text)
            daily_text = daily_preview.summary_text(summary, lang)
            self.assertNotIn({'en': 'shortage', 'zh': '缺料', 'ms': 'kekurangan'}[lang], daily_text.lower())

    def test_unknown_alerts_quality_and_missing_history_stay_unknown(self):
        self.assertEqual(self.sync().outcome, IMPORTED)                     # Storage only, alerts never evaluated
        facts = self.read(narrative.build_in, 'daily', now=self.clock.now)
        summary = self.generate(daily.Session(None, None, False, 'not checked'), allow_unverified=True)
        for lang in LANGS:
            report = readable.text(readable.report_sections(facts, lang))
            self.assertIn(readable.tx('alerts_unknown', lang), report)
            self.assertIn(readable.tx('r_sync_never', lang, role='BOM'), report)
            unknown_bom = readable.tx('q_issue', lang, role='BOM', label=readable.label(readable.ISSUE, 'DUPLICATE_BOM', lang),
                                      count=readable.tx('unknown', lang))
            self.assertIn(unknown_bom, report)
            text = daily_preview.summary_text(summary, lang)
            self.assertIn(readable.tx('d_alerts_unavailable', lang), text)
            self.assertNotIn(readable.tx('alerts_any', lang, count=0), text)
        empty = self.base / 'empty' / 'inventory.db'
        InventorySync(empty)
        nothing = daily.generate(empty, date.today(), daily.Session(None, None, False, 'not checked'),
                                 allow_unverified=True)
        for lang in LANGS:
            text = daily_preview.summary_text(nothing, lang)
            self.assertIn(readable.tx('hist_none', lang, coverage=readable.label(readable.COVERAGE, 'NO_HISTORY', lang)),
                          text)
            self.assertNotIn(readable.tx('d_no_change', lang), text)

    def test_summaries_state_the_same_numbers_in_every_language(self):
        workbook(self.bom, [('PRODUCT-1', bom_rows([('A', 2), ('MISSING-1', 1)]))])
        summary = self.generate(self.verify_all())
        facts = self.read(narrative.build_in, 'daily', now=self.clock.now)
        for render_one in (lambda lang: daily_preview.summary_text(summary, lang),
                           lambda lang: readable.text(readable.report_sections(facts, lang))):
            texts = {lang: render_one(lang) for lang in LANGS}
            self.assertEqual(len(set(texts.values())), 3)
            self.assertEqual(numbers(texts['zh']), numbers(texts['en']))
            self.assertEqual(numbers(texts['ms']), numbers(texts['en']))


class DeliveryReadabilityTests(DeliveryBase):
    def test_saved_html_and_mail_put_the_summary_first_and_keep_the_full_json(self):
        for lang in LANGS:
            doc = self.document(lang)
            page = rd.render_html(doc)
            sections = readable.report_sections(self.preview['facts'], lang)
            self.assertLess(page.index(f"<h2>{html.escape(rd.tx('summary', lang))}</h2>"), page.index('<details>'))
            for _title, lines in sections:
                for line in lines:
                    self.assertIn(html.escape(line.removeprefix('• ')), page)
            self.assertLess(page.index('<details>'), page.index(html.escape(rd.tx('basis', lang))))  # digests collapsed
            data = doc.data()
            self.assertEqual(data['facts'], self.preview['facts'])
            self.assertEqual(data['facts']['format'], narrative.FORMAT)
            self.assertIn('same_source', data['facts']['current_period'])
        saved = self.save(self.document('zh'))
        body = rd.mail_body(saved)
        self.assertLess(body.index(readable.text(readable.report_sections(self.preview['facts'], 'zh'))),
                        body.index(rd.tx('report_id', 'zh')))

    def test_publication_protections_are_unchanged(self):
        self.session.invalidate()
        with self.assertRaises(rd.DeliveryStale):
            self.save()
        self.assertEqual(list(self.out.iterdir()), [])


class ReportPreviewViewTests(Base):
    """The assistant's AI-report preview: summary first, details collapsed and one click away."""

    def setUp(self):
        gc.collect()  # dispose earlier tests' destroyed Tk roots on the Tk thread before workers start
        super().setUp(); self.sync('stock'); self.sync('bom')
        self.root = tk.Tk()
        self.root.geometry('960x600')
        outer = ttk.Frame(self.root); outer.pack(fill='both', expand=True)
        footer = ttk.Frame(outer); footer.pack(side='bottom', fill='x')
        self.keys = FakeKeys()
        self.session = AssistantSession(self.db, key_store=self.keys,
                                        provider=DeepSeekProvider(key_store=self.keys, transport=FakeService()))
        app = SimpleNamespace(root=self.root, outer=outer, inventory=self.inv, busy=False,
                              alert_read_failed=lambda _reason: None)
        self.host = AssistantLauncher(app, footer, session=self.session)
        self.host.toggle(); self.root.update()
        data = finish(self.session, 'preview_data')
        finish(self.session, 'authorize', expected_basis=data['basis'])
        self.facts = finish(self.session, 'report_preview', period='weekly')['facts']

    def tearDown(self):
        self.host.close(); wait_session(self.session)
        self.root.destroy(); super().tearDown()
        self.host = self.root = None
        gc.collect()  # release this test's Tk cycles here, never in a later worker thread

    def test_summary_is_shown_and_details_toggle_without_changing_facts(self):
        view = self.host.view
        before = json.dumps(self.facts, sort_keys=True)
        for lang in LANGS:
            view.show_report(self.facts, lang)
            text = view.report_preview.get('1.0', 'end-1c')
            summary = readable.text(readable.report_sections(self.facts, lang))
            self.assertTrue(text.startswith(summary))
            self.assertTrue(int(view.report_preview.tag_cget('details', 'elide')))
            self.assertIn(tr('report_details_title', lang), text)            # details present, hidden
        view.toggle_report_details()
        self.assertFalse(int(view.report_preview.tag_cget('details', 'elide')))
        view.show_report(self.facts, 'zh')                                   # a re-render keeps the choice
        self.assertFalse(int(view.report_preview.tag_cget('details', 'elide')))
        self.assertEqual(str(view.report_details_button.cget('text')), tr('report_details_hide', 'zh'))
        self.assertEqual(json.dumps(self.facts, sort_keys=True), before)


class DailyWindowViewTests(SessionUiBase):
    def setUp(self):
        gc.collect()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.apps.clear()
        self.app = self.root = None
        gc.collect()

    def test_daily_window_opens_on_the_summary_with_details_collapsed(self):
        self.current_session()
        self.app.open_daily(); w = self.app.daily_window
        w.generate()
        self.pump(lambda: w.summary is not None and not w.runner.busy)
        for lang in ('zh', 'ms', 'en'):
            self.app.set_language(lang); self.root.update()
            text = w.preview.get('1.0', 'end-1c')
            self.assertTrue(text.startswith(daily_preview.summary_text(w.summary, lang)))
            self.assertIn(daily_preview.render(w.summary, lang), text)       # every detail is still in the window
            self.assertTrue(int(w.preview.tag_cget('details', 'elide')))
        w.toggle_details()
        self.assertFalse(int(w.preview.tag_cget('details', 'elide')))
        self.app.set_language('zh'); self.root.update()
        self.assertFalse(int(w.preview.tag_cget('details', 'elide')))
        self.assertEqual(str(w.details_button.cget('text')), '隐藏明细 ▾')


# ---------------------------------------------------------------------- independent review fixes RD1–RD3
class SessionMixin:
    """A local-tools session on the test's temporary database: fake key and transport, never a network call."""

    def open_session(self):
        keys = FakeKeys()
        self.session = AssistantSession(self.db, key_store=keys,
                                        provider=DeepSeekProvider(key_store=keys, transport=FakeService()))
        preview = self.act('preview_data')
        self.assertEqual(self.act('authorize', expected_basis=preview['basis'])['status'], 'AUTHORIZED')

    def tearDown(self):
        if getattr(self, 'session', None) is not None:
            self.session.close(); wait_session(self.session)
        super().tearDown()

    def act(self, action, **payload):
        self.assertTrue(self.session.submit(action, **payload))
        events = wait_session(self.session)
        self.assertEqual(len(events), 1)
        return events[0].result

    def observed(self, tool, **arguments):
        return {'status': 'TOOL_RESULTS', 'evidence': [self.session.tools.call(tool, arguments)]}


class BomFailureSummaryTests(SessionMixin, DailyBase):
    """RD1: stock alerts include BOM coverage, so a failed or unavailable BOM check is stated in the answer."""

    def test_bom_unavailable_is_stated_for_alerts_combined_answers_and_status(self):
        self.verify_all()                                                    # stored, completed evaluation
        self.bom.unlink()
        self.assertEqual(self.sync('bom').outcome, UNAVAILABLE)
        self.open_session()
        alerts = self.observed('get_stock_alerts')
        stock = self.observed('get_stock', material_id='A')
        status = self.observed('data_status')
        combined = {'status': 'TOOL_RESULTS', 'evidence': stock['evidence'] + alerts['evidence']}
        self.assertEqual(alerts['evidence'][0]['data']['recorded']['active_counts'], {'OUT_OF_STOCK': 1, 'LOW_STOCK': 2})
        finished = self.query("SELECT finished_at FROM sync_runs WHERE role = 'bom' ORDER BY id DESC LIMIT 1")[0][0]
        for lang in LANGS:
            warning = tr('c_stale_unavailable', lang).format(role='BOM', time=readable.local_time(finished))
            for result in (alerts, combined, status):
                self.assertIn(warning, render(result, lang).split('\n\n')[0])  # in the status block, at the top
            self.assertNotIn(warning, render(stock, lang))                   # a stock-only answer needs no BOM
            text = render(alerts, lang)
            for kind, count in (('OUT_OF_STOCK', 1), ('LOW_STOCK', 2)):     # stored counts unchanged
                self.assertIn(tr('c_alert_count', lang).format(label=readable.label(readable.ALERT, kind, lang),
                                                               count=count), text)
            self.assertIn(SYNC_STATES['Source File Unavailable'][LANGS.index(lang)], render(status, lang))


class HistoryLatestObservationTests(SessionMixin, Base):
    """RD2: the newest observation leads the history answer; an older number is labelled as the last record."""

    def history(self):
        result = self.observed('material_history', material_id='A', days=30)
        return result, result['evidence'][0]['data']['rows']

    def test_absent_latest_snapshot_is_stated_before_the_last_recorded_quantity(self):
        self.write_stock([('A', 100), ('B', 5)]); self.sync()
        self.write_stock([('B', 5)]); self.sync()                            # A removed from the same file
        self.open_session()
        result, rows = self.history()
        self.assertEqual([r['kind'] for r in rows[:2]], ['ABSENT', 'RECORD'])
        for lang in LANGS:
            text = render(result, lang)
            absent = tr('c_latest_absent', lang).format(time=readable.local_time(rows[0]['observed_at']))
            last = tr('c_last_qty', lang).format(time=readable.local_time(rows[1]['observed_at']), qty='100',
                                                 sheet='Stock')
            self.assertIn(absent, text)
            self.assertIn(last, text)
            self.assertLess(text.index(absent), text.index(last))
            self.assertNotIn(tr('c_latest', lang).format(time=readable.local_time(rows[1]['observed_at']),
                                                         qty='100', sheet='Stock'), text)

    def test_cleaned_up_latest_snapshot_is_unknown_never_zero_or_the_cleaned_value(self):
        self.write_stock([('A', 100)]); self.sync()
        self.write_stock([('A', 50)]); latest = self.sync()
        with closing(sqlite3.connect(self.db)) as conn:                     # what history cleanup leaves behind
            conn.execute('DELETE FROM stock_records WHERE source_version_id = ?', (latest.version_id,))
            conn.commit()
        self.open_session()
        result, rows = self.history()
        self.assertEqual([r['kind'] for r in rows[:2]], ['NOT_RETAINED', 'RECORD'])
        for lang in LANGS:
            text = render(result, lang)
            self.assertIn(tr('c_latest_pruned', lang).format(time=readable.local_time(rows[0]['observed_at'])), text)
            self.assertIn(tr('c_last_qty', lang).format(time=readable.local_time(rows[1]['observed_at']), qty='100',
                                                        sheet='Stock'), text)
            for qty in ('0', '50'):
                self.assertNotIn(tr('c_latest', lang).format(time=readable.local_time(rows[0]['observed_at']),
                                                             qty=qty, sheet='Stock'), text)

    def test_each_sheet_of_the_latest_snapshot_stays_separate(self):
        self.write_stock(None, sheets=[('S1', stock_rows([('A', 1)])), ('S2', stock_rows([('A', 2)]))]); self.sync()
        self.open_session()
        result, rows = self.history()
        for lang in LANGS:
            text = render(result, lang)
            for sheet, qty in (('S1', '1'), ('S2', '2')):
                self.assertIn(tr('c_latest', lang).format(time=readable.local_time(rows[0]['observed_at']), qty=qty,
                                                          sheet=sheet), text)


class BoundedListTests(SessionMixin, DailyBase):
    """RD3: 'complete list in Details' only when Details hold it; a read-limited result says loaded of total."""

    def test_alert_list_cut_by_the_tool_read_limit_says_loaded_of_total(self):
        self.verify_all()
        self.open_session()
        real = agent_tools.alerts.state_in
        with patch.object(agent_tools.alerts, 'state_in', side_effect=lambda conn, **kw: real(conn, **{**kw, 'limit': 1})):
            result = self.observed('get_stock_alerts')                      # simulates the 200-row read limit
        self.assertEqual((len(result['evidence'][0]['data']['recorded']['rows']),
                          result['evidence'][0]['data']['recorded']['total_rows']), (1, 3))
        for lang in LANGS:
            capped = tr('c_capped', lang).format(loaded=1, total=3)
            for text in (render(result, lang), render_details(result, lang)):
                self.assertIn(capped, text)
                self.assertIn(tr('c_narrow_alerts', lang), text)
                self.assertNotIn(tr('c_shown', lang).split('{')[0], text)

    def test_search_over_the_real_200_candidate_limit_is_not_promised_complete(self):
        self.write_stock([(f'P-{n:03}', n) for n in range(205)]); self.sync()
        self.open_session()
        result = self.observed('search_materials', text='P-')
        data = result['evidence'][0]['data']
        self.assertEqual((len(data['candidates']), data['total'], data['truncated']), (200, 205, True))
        for lang in LANGS:
            text = render(result, lang)
            self.assertIn(tr('c_shown_only', lang).format(shown=8) + ' ' +
                          tr('c_capped', lang).format(loaded=200, total=205), text)
            self.assertIn(tr('c_narrow_search', lang), text)
            self.assertIn(tr('c_capped', lang).format(loaded=200, total=205), render_details(result, lang))

    def test_daily_lists_cut_by_the_read_limits_state_loaded_and_total(self):
        self.verify_all()
        workbook(self.stock, [('Stock', stock_with_threshold([('A', 0, 5), ('B', 2, 5), ('C', 10, 2)]))])
        self.assertEqual(self.sync().outcome, IMPORTED)                      # one same-source change
        with patch.object(daily, 'MAX_CHANGE_ITEMS', 0), patch.object(daily, 'MAX_ALERT_ITEMS', 1):
            summary = self.generate(self.evaluate())                         # simulated 2000 / 5000-row limits
        data = summary.data()
        self.assertEqual((len(data['changes']['items']), data['changes']['same_source']['total']), (0, 1))
        for lang in LANGS:
            text = daily_preview.summary_text(summary, lang)
            self.assertIn(readable.tx('capped', lang, loaded=0, total=1) + ' ' + readable.tx('hint_history', lang),
                          text)
            self.assertIn(readable.tx('capped', lang, loaded=1, total=3) + ' ' + readable.tx('hint_alerts', lang),
                          text)
            self.assertNotIn(readable.tx('shown', lang, shown=0, total=1), text)
