"""M3.2D Daily Stock Summary. Synthetic workbooks and temporary SQLite only (TemporaryDirectory via tests.test_m31.Base)."""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone, tzinfo
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from unittest.mock import patch

from checker import alerts, daily
from checker.alerts import AlertService, SessionGate
from checker.sync import IMPORTED, UNAVAILABLE, InventorySync
from tests.fixtures import bom_rows, workbook
from tests.test_m31 import Base, digest
from tests.test_m32c import authorize, logical, make_schema_1, stock_with_threshold
from tests.test_m32c_remediation import SessionUiBase

UTC = timezone.utc
TZ = timezone(timedelta(hours=8))
STOCK = [('A', 0, 5), ('B', 3, 5), ('C', 10, 2)]   # A: OUT_OF_STOCK and LOW_STOCK; B: LOW_STOCK; C fine


class ShiftTZ(tzinfo):
    """Test zone: UTC+1, UTC+2 from 2026-03-29 02:00 local (a 23-hour day)."""

    def utcoffset(self, dt):
        return timedelta(hours=2) if dt.replace(tzinfo=None) >= datetime(2026, 3, 29, 2) else timedelta(hours=1)

    def dst(self, dt):
        return self.utcoffset(dt) - timedelta(hours=1)

    def tzname(self, dt):
        return "TEST"


def files(folder):
    return sorted(p.name for p in Path(folder).iterdir())


class DailyBase(Base):
    def setUp(self):
        super().setUp()
        workbook(self.stock, [('Stock', stock_with_threshold(STOCK))])
        self.gate = SessionGate()
        self.out = self.base / 'reports'
        self.out.mkdir()

    def today(self):
        return self.clock.now.astimezone(TZ).date()

    def verify_all(self):
        """Both files synchronised and a verified evaluation: the Session a current application would hold."""
        self.assertEqual(self.sync().outcome, IMPORTED)
        self.assertEqual(self.sync('bom').outcome, IMPORTED)
        return self.evaluate()

    def evaluate(self):
        auth = alerts.Authorization(self.gate.generation, authorize(self.db).sources)
        result = AlertService(self.db, clock=self.clock).run('manual', auth, lambda: self.gate.publishing(auth.generation))
        self.assertEqual(result.outcome, alerts.COMPLETED, result.reason)
        return daily.Session(self.gate.generation, auth, True)

    def generate(self, session, day=None, **kw):
        kw.setdefault('now', self.clock.now)
        return daily.generate(self.db, day or self.today(), session, gate=self.gate, tz=TZ, **kw)

    def alert_type(self, summary, name):
        return next(t for t in summary.data()['alerts']['at_generation']['by_type'] if t['type'] == name)


class SummaryContentTests(DailyBase):
    def test_verified_summary_counts_types_and_distinct_materials_separately(self):
        summary = self.generate(self.verify_all())
        self.assertTrue(summary.verified)
        data = summary.data()
        self.assertEqual(data['status'], daily.VERIFIED)
        self.assertEqual(data['verification']['reasons'], [])
        g = data['alerts']['at_generation']
        self.assertEqual(g['status'], daily.CURRENT)
        self.assertTrue(data['alerts']['for_report_date']['available'])
        self.assertEqual((self.alert_type(summary, alerts.OUT_OF_STOCK)['alerts'],
                          self.alert_type(summary, alerts.LOW_STOCK)['alerts']), (1, 2))
        # A is both OUT_OF_STOCK and LOW_STOCK: 3 alerts, 2 distinct materials, never "3 materials".
        self.assertEqual(sum(t['alerts'] for t in g['by_type']), 3)
        self.assertEqual(g['distinct_material_ids_any_type'], 2)
        self.assertIn('must not be added up', data['alerts']['sum_note'])
        self.assertEqual(g['scope']['storage_version'], data['sources']['stock']['current']['id'])
        self.assertEqual(data['timezone']['label'], 'UTC+08:00')
        self.assertEqual(data['window']['start_utc'], '2026-09-30 16:00:00.000')
        self.assertEqual(data['window']['end_utc'], '2026-10-01 16:00:00.000')
        a = next(i for i in g['items'] if i['material_id'] == 'A' and i['type'] == alerts.LOW_STOCK)
        self.assertEqual((a['stock'], a['shortfall']), ('0', '5'))
        self.assertIn(daily.CLOUD_NOT_VERIFIED, daily.render_text(summary))
        self.assertIn(daily.OBSERVED_NOT_CONSUMPTION, daily.render_html(summary))

    def test_no_alerts_is_never_called_normal_stock(self):
        workbook(self.stock, [('Stock', stock_with_threshold([('A', 9, 5), ('B', 9, 5)]))])
        summary = self.generate(self.verify_all())
        g = summary.data()['alerts']['at_generation']
        self.assertEqual((g['status'], g['total']), (daily.CURRENT, 0))
        for text in (daily.render_text(summary), daily.render_html(summary)):
            self.assertIn('Nothing in this report states that stock is normal', text)
            self.assertIn('not a statement that stock is sufficient', text)
            for claim in ('stock normal', 'stock is ok', 'all stock', 'no shortage', '库存正常'):
                self.assertNotIn(claim, text.lower())

    def test_no_change_on_the_day_means_no_record_not_no_movement(self):
        session = self.verify_all()
        self.clock.now += timedelta(days=2)
        session = self.evaluate()  # today, after the only snapshot day
        summary = self.generate(session)
        c = summary.data()['changes']
        self.assertEqual((c['total'], c['snapshots']), (0, []))
        self.assertIn('does not mean the warehouse had no movement', c['no_record_note'])
        self.assertTrue(summary.verified)

    def test_observed_quantity_change_has_a_difference_but_no_consumption(self):
        self.verify_all()
        workbook(self.stock, [('Stock', stock_with_threshold([('A', 4, 5), ('B', 3, 5), ('C', 10, 2)]))])
        self.assertEqual(self.sync().outcome, IMPORTED)
        summary = self.generate(self.evaluate())
        c = summary.data()['changes']
        self.assertEqual(c['by_type']['QUANTITY_CHANGED'], dict(changes=1, distinct_material_ids=1))
        item = c['items'][0]
        self.assertEqual((item['material_id'], item['before'], item['after'], item['observed_difference']),
                         ('A', '0', '4', '+4'))
        not_calculated = summary.data()['limitations']['not_calculated']
        self.assertTrue(all(n['value'] is None for n in not_calculated))
        self.assertTrue(any('consumption' in n['field'].lower() for n in not_calculated))

    def test_blank_invalid_and_duplicate_states_are_reported_not_converted(self):
        self.verify_all()
        workbook(self.stock, [('Stock', stock_with_threshold([('A', None, 5), ('B', 'abc', 5), ('C', 1, 2),
                                                               ('C', 2, 2)]))])
        self.assertEqual(self.sync().outcome, IMPORTED)
        summary = self.generate(self.evaluate())
        data = summary.data()
        kinds = {i['change_type'] for i in data['changes']['items']}
        self.assertEqual(kinds, {'VALIDITY_CHANGED', 'DUPLICATE_CHANGED'})
        self.assertTrue(all(i['observed_difference'] is None and i['difference_reason'] for i in data['changes']['items']))
        raw = data['limitations']['current_storage_raw']
        self.assertEqual((raw['blank'], raw['invalid'], raw['duplicate_ids']), (1, 1, 1))
        issues = self.alert_type(summary, alerts.DATA_ISSUE)['subtypes']
        self.assertEqual(issues, {'BLANK_STOCK': 1, 'DUPLICATE_STOCK_ID': 1, 'INVALID_STOCK': 1})
        before = next(i for i in data['changes']['items'] if i['material_id'] == 'A')
        self.assertEqual(before['after'], '(blank) (BLANK — not 0)')

    def test_source_switch_is_listed_and_not_comparable(self):
        self.verify_all()
        other = self.stock.with_name('storage-copy.xlsx')
        workbook(other, [('Stock', stock_with_threshold([('A', 7, 5), ('B', 3, 5), ('C', 10, 2)]))])
        self.assertEqual(self.inv.sync_role('stock', str(other), 'manual').outcome, IMPORTED)
        summary = self.generate(self.evaluate())
        c = summary.data()['changes']
        self.assertEqual([s['role'] for s in c['source_switches']], ['Storage'])
        change = c['items'][0]
        self.assertTrue(change['source_switched'])
        self.assertIsNone(change['observed_difference'])
        self.assertIn('not comparable', change['difference_reason'])


class DateWindowTests(DailyBase):
    def publish(self, qty):
        workbook(self.stock, [('Stock', stock_with_threshold([('A', qty, 5)]))])
        self.assertEqual(self.sync().outcome, IMPORTED)

    def set_observed(self, stamps):
        with closing(sqlite3.connect(self.db)) as conn:
            for (snapshot_id,), value in zip(conn.execute('SELECT id FROM inventory_snapshots ORDER BY id').fetchall(),
                                             stamps):
                conn.execute('UPDATE inventory_snapshots SET observed_at = ? WHERE id = ?', (value, snapshot_id))
            conn.commit()

    def test_midnight_belongs_to_exactly_one_day(self):
        for qty in (0, 1, 2):
            self.publish(qty)
        self.sync('bom')
        # Local +08:00: 00:00:00.000 of 10-01, 23:59:59.999 of 10-01, 00:00:00.000 of 10-02.
        self.set_observed(['2026-09-30 16:00:00.000', '2026-10-01 15:59:59.999', '2026-10-01 16:00:00.000'])
        now = datetime(2026, 10, 2, 9, tzinfo=UTC)
        session = daily.Session(None, None, False, 'not verified (test)')
        first = self.generate(session, date(2026, 10, 1), now=now, allow_unverified=True).data()['changes']
        second = self.generate(session, date(2026, 10, 2), now=now, allow_unverified=True).data()['changes']
        self.assertEqual([s['observed_utc'] for s in first['snapshots']],
                         ['2026-09-30 16:00:00.000', '2026-10-01 15:59:59.999'])
        self.assertEqual([(i['before'], i['after']) for i in first['items']], [('0', '1')])
        self.assertEqual([s['observed_utc'] for s in second['snapshots']], ['2026-10-01 16:00:00.000'])
        self.assertEqual([(i['before'], i['after']) for i in second['items']], [('1', '2')])
        previous = self.generate(session, date(2026, 9, 30), now=now, allow_unverified=True).data()
        self.assertEqual(previous['changes']['total'], 0)
        self.assertEqual(previous['limitations']['history']['coverage'], 'BEFORE_HISTORY')
        self.assertIn('BOM was not checked on this date (no synchronisation record).',
                      previous['limitations']['sync_notes'])

    def test_cleanup_boundary_is_stated_not_reconstructed(self):
        self.publish(0)
        self.sync('bom')
        self.set_observed(['2026-09-20 08:00:00.000'])
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("INSERT INTO schema_info VALUES ('history_retained_from', '2026-09-26 04:00:00.000')")
            conn.commit()
        session, now = daily.Session(None, None, False), datetime(2026, 10, 1, 9, tzinfo=UTC)
        coverage = lambda day: self.generate(session, day, now=now, allow_unverified=True).data()['limitations']['history']
        self.assertEqual(coverage(date(2026, 9, 25))['coverage'], 'REMOVED')
        self.assertEqual(coverage(date(2026, 9, 26))['coverage'], 'PARTLY_REMOVED')
        self.assertEqual(coverage(date(2026, 9, 27))['coverage'], 'COVERED')
        self.assertIn('not reconstructed', coverage(date(2026, 9, 25))['note'])

    def test_daylight_saving_day_has_its_real_length(self):
        window = daily.day_window(date(2026, 3, 29), ShiftTZ())
        self.assertEqual((window['start_utc'], window['end_utc'], window['hours']),
                         ('2026-03-28 23:00:00.000', '2026-03-29 22:00:00.000', 23.0))
        self.assertEqual(daily.day_window(date(2026, 3, 30), ShiftTZ())['start_utc'], window['end_utc'])

    def test_future_date_is_refused(self):
        with self.assertRaises(daily.DailyError):
            self.generate(daily.Session(None, None, False), self.today() + timedelta(days=1), allow_unverified=True)


class VerificationTests(DailyBase):
    def test_historical_date_never_presents_current_alerts_as_that_day(self):
        session = self.verify_all()
        self.clock.now += timedelta(days=1)
        yesterday = self.today() - timedelta(days=1)
        with self.assertRaises(daily.ConfirmationRequired) as caught:
            self.generate(session, yesterday)
        self.assertIn('past date', caught.exception.reasons[0])
        summary = self.generate(session, yesterday, allow_unverified=True)
        data = summary.data()
        self.assertFalse(summary.verified)
        self.assertFalse(data['alerts']['for_report_date']['available'])
        self.assertIn('cannot be reconstructed', data['alerts']['for_report_date']['reason'])
        self.assertTrue(daily.file_stem(summary).startswith('UNVERIFIED_Daily_Stock_Summary_' + yesterday.isoformat()))
        page = daily.render_html(summary)
        self.assertIn('UNVERIFIED REPORT', page)
        self.assertIn('not the state on ' + yesterday.isoformat(), page)
        self.assertIn('UNVERIFIED', daily.render_text(summary).splitlines()[0])
        self.assertEqual(data['changes']['total'], 0)  # yesterday's observations only

    def test_sync_failure_makes_the_summary_unverified_and_lists_it(self):
        session = self.verify_all()
        self.stock.unlink()
        self.assertEqual(self.sync().outcome, UNAVAILABLE)
        with self.assertRaises(daily.ConfirmationRequired) as caught:
            self.generate(session)
        self.assertTrue(any('not a success' in r for r in caught.exception.reasons))
        data = self.generate(session, allow_unverified=True).data()
        self.assertEqual(data['status'], daily.UNVERIFIED)
        self.assertEqual(data['alerts']['at_generation']['status'], daily.STORED)
        self.assertIn('NOT RE-CHECKED', data['alerts']['at_generation']['label'])
        self.assertEqual(data['sources']['stock']['failures_on_day_total'], 1)
        self.assertEqual(data['sources']['stock']['failures_on_day'][0]['outcome'], UNAVAILABLE)
        self.assertTrue(any(n.startswith('Storage: the latest check failed (UNAVAILABLE')
                            for n in data['limitations']['sync_notes']))

    def test_unverified_session_never_produces_a_verified_summary(self):
        self.verify_all()
        summary = self.generate(daily.Session(self.gate.generation, None, False, 'Excel files not checked'),
                                allow_unverified=True)
        self.assertFalse(summary.verified)
        self.assertIn('Excel files not checked', summary.data()['verification']['reasons'][0])
        self.assertEqual(summary.data()['alerts']['at_generation']['status'], daily.STORED)

    def test_alert_evaluation_of_an_older_version_of_the_same_path_is_not_current(self):
        self.verify_all()
        workbook(self.stock, [('Stock', stock_with_threshold([('A', 9, 5), ('B', 9, 5), ('C', 10, 2)]))])
        self.assertEqual(self.sync().outcome, IMPORTED)  # same path, new version, no evaluation yet
        session = daily.Session(self.gate.generation, alerts.Authorization(self.gate.generation,
                                                                            authorize(self.db).sources), True)
        with self.assertRaises(daily.ConfirmationRequired) as caught:
            self.generate(session)
        self.assertTrue(any('not shown as current' in r for r in caught.exception.reasons))
        g = self.generate(session, allow_unverified=True).data()['alerts']['at_generation']
        self.assertEqual(g['status'], daily.UNAVAILABLE)
        self.assertNotIn('items', g)
        self.assertIn('not a statement that there are no alerts', g['label'])

    def test_session_verified_an_older_version_than_the_database(self):
        session = self.verify_all()
        other = alerts.Authorization(self.gate.generation, authorize(self.db).sources)
        workbook(self.stock, [('Stock', stock_with_threshold([('A', 1, 5), ('B', 3, 5), ('C', 10, 2)]))])
        self.assertEqual(self.sync().outcome, IMPORTED)
        self.evaluate()  # the database's newest evaluation is current, but THIS session verified the older version
        with self.assertRaises(daily.ConfirmationRequired) as caught:
            self.generate(daily.Session(session.generation, other, True))
        self.assertTrue(any('this session verified Storage' in r for r in caught.exception.reasons))

    def test_verification_changed_during_generation(self):
        session = self.verify_all()
        real = daily._changes

        def changing(conn, window):
            self.gate.invalidate()  # e.g. a sync started in the application meanwhile
            return real(conn, window)
        with patch.object(daily, '_changes', changing):
            with self.assertRaises(daily.ConfirmationRequired) as caught:
                self.generate(session)
        self.assertTrue(any('changed while the summary was generated' in r for r in caught.exception.reasons))

    def test_schema_1_database_still_summarises_without_upgrading(self):
        legacy = self.base / 'legacy' / 'inventory.db'
        make_schema_1(legacy)
        before = logical(legacy)
        summary = daily.generate(legacy, self.today(), daily.Session(None, None, False), tz=TZ, now=self.clock.now,
                                 allow_unverified=True)
        g = summary.data()['alerts']['at_generation']
        self.assertEqual(g['status'], daily.UNAVAILABLE)
        self.assertIn('schema 1', g['reason'])
        self.assertEqual(logical(legacy), before)
        with closing(sqlite3.connect(legacy)) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 1)

    def test_database_read_failures_produce_no_summary(self):
        with self.assertRaises(daily.DailyReadError):
            daily.generate(self.base / 'missing.db', self.today(), daily.Session(None, None, False), tz=TZ,
                           now=self.clock.now, allow_unverified=True)
        self.assertFalse((self.base / 'missing.db').exists())  # never created
        session = self.verify_all()
        with patch.object(daily, '_changes', side_effect=sqlite3.OperationalError('synthetic read failure')):
            with self.assertRaises(daily.DailyReadError):
                self.generate(session)


class SaveTests(DailyBase):
    def test_html_and_json_come_from_one_summary(self):
        summary = self.generate(self.verify_all())
        saved = daily.save(summary, self.out, self.db, gate=self.gate)
        self.assertEqual(files(self.out), [saved.folder.name])  # one report directory, holding exactly the pair
        self.assertEqual(files(saved.folder), sorted([saved.html.name, saved.json.name]))
        self.assertRegex(saved.html.name, r'^Daily_Stock_Summary_2026-10-01_generated_20261001_\d{6}\.html$')
        self.assertEqual((saved.json.stem, saved.folder.name), (saved.html.stem, saved.html.stem))
        raw = saved.json.read_bytes()
        self.assertEqual(json.loads(raw), summary.data())
        page = saved.html.read_text(encoding='utf-8')
        self.assertIn(f'<meta name="data-sha256" content="{hashlib.sha256(raw).hexdigest()}">', page)
        self.assertIn(f'<meta name="report-id" content="{summary.report_id}">', page)
        data = summary.data()
        for value in (data['report_date'], data['sources']['stock']['current']['file_name'],
                      f"evaluation #{data['alerts']['at_generation']['scope']['evaluation_id']}"):
            self.assertIn(value, page)
        again = daily.save(summary, self.out, self.db, gate=self.gate)  # never overwrites
        self.assertEqual(again.folder.name, saved.folder.name + ' (2)')
        self.assertEqual(again.json.read_bytes(), raw)
        self.assertEqual(saved.json.read_bytes(), raw)
        self.assertEqual(len(files(self.out)), 2)

    def test_saving_reads_nothing_new_and_writes_no_source_or_database(self):
        session = self.verify_all()
        sources = [digest(self.stock), digest(self.bom)]
        before = logical(self.db)
        daily.save(self.generate(session), self.out, self.db, gate=self.gate)
        self.assertEqual([digest(self.stock), digest(self.bom)], sources)
        self.assertEqual(logical(self.db), before)

    def test_unverified_files_are_marked(self):
        self.verify_all()
        summary = self.generate(daily.Session(None, None, False), allow_unverified=True)
        saved = daily.save(summary, self.out, self.db)
        self.assertTrue(all(p.name.startswith('UNVERIFIED_') for p in (saved.folder, saved.html, saved.json)))
        self.assertIn('UNVERIFIED REPORT', saved.html.read_text(encoding='utf-8'))
        self.assertEqual(json.loads(saved.json.read_text(encoding='utf-8'))['status'], 'UNVERIFIED')

    def test_changed_data_or_verification_refuses_saving(self):
        session = self.verify_all()
        summary = self.generate(session)
        self.assertEqual(self.sync().outcome, 'UNCHANGED')  # only a new sync record
        with self.assertRaises(daily.DailyStale):
            daily.save(summary, self.out, self.db, gate=self.gate)
        summary = self.generate(self.evaluate())
        self.gate.invalidate()
        with self.assertRaises(daily.DailyStale):
            daily.save(summary, self.out, self.db, gate=self.gate)
        self.assertEqual(files(self.out), [])

    def test_verification_withdrawn_while_saving_publishes_nothing(self):
        summary = self.generate(self.verify_all())
        with patch.object(daily, '_checkpoint', lambda stage: stage == 'staged' and self.gate.invalidate()):
            with self.assertRaises(daily.DailyStale):
                daily.save(summary, self.out, self.db, gate=self.gate)
        self.assertEqual(files(self.out), [])  # no partial directory either

    def test_database_failure_while_saving(self):
        summary = self.generate(self.verify_all())
        with patch.object(daily, '_basis', side_effect=sqlite3.OperationalError('locked')):
            with self.assertRaises(daily.DailyReadError):
                daily.save(summary, self.out, self.db, gate=self.gate)
        self.assertEqual(files(self.out), [])
        with self.assertRaises(daily.DailyError):
            daily.save(summary, self.out / 'missing', self.db, gate=self.gate)

    def test_raw_text_is_escaped_and_the_page_is_self_contained(self):
        hostile = '<script>alert("x")</script>'
        rows = stock_with_threshold([(hostile, 3, None), ('B&<i>', 0, 5)])
        rows[15]['F'] = '<img src=x onerror=alert(1)> & "quoted" \'single\''
        workbook(self.stock, [('Stock <b>&"', rows)])
        workbook(self.bom, [('PRODUCT-1', bom_rows([('B&<i>', 1), ('<Z>', 2)]))])
        summary = self.generate(self.verify_all())
        page = daily.render_html(summary)
        for bad in ('<script', '<img', '<i>', '<b>&', '<Z>', 'onerror=alert(1)>'):
            self.assertNotIn(bad, page)
        self.assertIn('&lt;SCRIPT&gt;ALERT(&quot;X&quot;)&lt;/SCRIPT&gt;', page)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt; &amp; &quot;quoted&quot; &#x27;single&#x27;', page)
        self.assertIn('Stock &lt;b&gt;&amp;&quot;', page)
        tags = set(re.findall(r'<([a-zA-Z0-9]+)', page))
        self.assertLessEqual(tags, {'html', 'head', 'meta', 'title', 'style', 'body', 'h1', 'h2', 'h3', 'div', 'p',
                                    'b', 'dl', 'dt', 'dd', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'footer',
                                    'details', 'summary', 'ul', 'li'})
        for external in ('http://', 'https://', 'src=', 'href=', '@import', 'url(', '<link'):
            self.assertNotIn(external, page.replace('src=x', ''))
        # JSON keeps the original text unchanged (escaping is an HTML concern only)
        self.assertIn(hostile.upper(), summary.json_text.replace('\\"', '"'))


class PublicationBasisTests(DailyBase):
    """P1-D1: the database basis is checked again after staging, under a held read lock, right before publication."""

    def other_instance(self):
        return InventorySync(self.db, settle_seconds=0, clock=self.clock)  # another program on the same database

    def changes(self):
        self.edits = getattr(self, 'edits', 0) + 1  # every call writes different content: a genuinely new version

        def storage():
            workbook(self.stock, [('Stock', stock_with_threshold([('A', self.edits, 5), ('B', 3, 5), ('C', 10, 2)]))])
            self.assertEqual(self.other_instance().sync_role('stock', str(self.stock), 'manual').outcome, IMPORTED)

        def bom():
            workbook(self.bom, [('PRODUCT-1', bom_rows([('A', 2), ('B', 1), ('C', 4 + self.edits)]))])
            self.assertEqual(self.other_instance().sync_role('bom', str(self.bom), 'manual').outcome, IMPORTED)

        def unchanged():
            self.assertEqual(self.other_instance().sync_role('stock', str(self.stock), 'manual').outcome, 'UNCHANGED')

        def evaluation():
            AlertService(self.db, clock=self.clock).run('manual', None)  # another program's (unverified) attempt
        return dict(storage=storage, bom=bom, unchanged=unchanged, evaluation=evaluation)

    def test_another_program_publishing_during_staging_refuses_the_save(self):
        self.verify_all()
        for verified in (True, False):
            for name in ('storage', 'bom', 'unchanged', 'evaluation'):
                with self.subTest(verified=verified, change=name):
                    summary = (self.generate(self.evaluate()) if verified else
                               self.generate(daily.Session(None, None, False), allow_unverified=True))
                    self.assertEqual(summary.verified, verified)
                    generation = self.gate.generation
                    change = self.changes()[name]
                    with patch.object(daily, '_checkpoint', lambda stage: stage == 'staged' and change()):
                        with self.assertRaises(daily.DailyStale):
                            daily.save(summary, self.out, self.db, gate=self.gate)
                    self.assertEqual(self.gate.generation, generation)  # this session's gate never noticed
                    self.assertEqual(files(self.out), [])

    def test_no_commit_can_happen_inside_the_publication_window(self):
        summary = self.generate(self.verify_all())
        attempts = []

        def try_commit(stage):
            if stage != 'before_publish':
                return
            self.assertFalse(any(p.name.startswith('Daily_') for p in self.out.iterdir()))  # not yet visible
            staged = [p for p in self.out.iterdir() if p.name.endswith('.partial')]
            self.assertEqual(len(staged), 1)
            self.assertEqual(len(files(staged[0])), 2)  # staging already complete
            with closing(sqlite3.connect(self.db, timeout=0.2, isolation_level=None)) as writer:
                writer.execute('BEGIN IMMEDIATE')
                writer.execute("INSERT INTO schema_info VALUES ('m32d_probe', 'x')")
                try:
                    writer.execute('COMMIT')
                    attempts.append('committed')
                except sqlite3.OperationalError as exc:
                    attempts.append(str(exc))
                    writer.execute('ROLLBACK')
        with patch.object(daily, '_checkpoint', try_commit):
            saved = daily.save(summary, self.out, self.db, gate=self.gate)
        self.assertEqual(attempts, ['database is locked'])
        self.assertEqual(files(self.out), [saved.folder.name])
        self.assertEqual(daily.read_basis(self.db), summary.basis)

    def test_every_name_race_retry_checks_the_basis_again(self):
        summary = self.generate(self.verify_all())
        stem = daily.file_stem(summary)
        real = daily._publish

        def racing(staging, target):
            if target.name == stem:  # another program takes the first name at the last moment
                target.mkdir()
                (target / 'theirs.txt').write_text('not ours')
            return real(staging, target)
        changed = lambda stage: stage == 'retry' and self.changes()['storage']()
        with patch.object(daily, '_publish', racing), patch.object(daily, '_checkpoint', changed):
            with self.assertRaises(daily.DailyStale):
                daily.save(summary, self.out, self.db, gate=self.gate)
        self.assertEqual(files(self.out), [stem])  # only theirs, untouched
        self.assertEqual(files(self.out / stem), ['theirs.txt'])
        summary = self.generate(self.evaluate())  # unchanged data: the retry publishes under the next free name
        stem = daily.file_stem(summary)
        with patch.object(daily, '_publish', racing):
            saved = daily.save(summary, self.out, self.db, gate=self.gate)
        self.assertEqual(saved.folder.name, stem + ' (2)')
        self.assertEqual(files(self.out / stem), ['theirs.txt'])
        self.assertEqual(json.loads(saved.json.read_bytes()), summary.data())


class PairPublicationTests(DailyBase):
    """P1-D2: the pair becomes visible by one directory rename; failures never leave a final-name report and are
    reported, with any leftover staging directory named."""

    def test_failed_publication_leaves_no_report_and_keeps_the_original_error(self):
        summary = self.generate(self.verify_all())
        with patch.object(daily, '_publish', side_effect=OSError('synthetic publication failure')):
            with self.assertRaises(OSError) as caught:
                daily.save(summary, self.out, self.db, gate=self.gate)
        self.assertEqual(str(caught.exception), 'synthetic publication failure')
        self.assertFalse(hasattr(caught.exception, 'cleanup_warning'))
        self.assertEqual(files(self.out), [])

    def test_cleanup_failure_is_reported_with_the_leftover_path(self):
        summary = self.generate(self.verify_all())
        with patch.object(daily, '_publish', side_effect=OSError('synthetic publication failure')), \
                patch.object(daily.shutil, 'rmtree', side_effect=PermissionError('synthetic sharing violation')):
            with self.assertRaises(OSError) as caught:
                daily.save(summary, self.out, self.db, gate=self.gate)
        error = caught.exception
        self.assertEqual(str(error), 'synthetic publication failure')  # the original error is the raised one
        leftover = error.leftover
        self.assertTrue(leftover.name.startswith('.mrc-daily-') and leftover.name.endswith('.partial'))
        self.assertIn(str(leftover), error.cleanup_warning)
        self.assertIn('synthetic sharing violation', error.cleanup_warning)
        self.assertIn(error.cleanup_warning, getattr(error, '__notes__', []))
        self.assertEqual(files(self.out), [leftover.name])  # nothing under a report name

    def test_staging_failure_after_the_first_file(self):
        summary = self.generate(self.verify_all())
        real = daily._write_verified

        def write(path, payload):
            if path.suffix == '.html':
                raise OSError('disk full')
            return real(path, payload)
        with patch.object(daily, '_write_verified', write):
            with self.assertRaises(OSError):
                daily.save(summary, self.out, self.db, gate=self.gate)
        self.assertEqual(files(self.out), [])

    def test_existing_report_file_or_folder_names_are_never_replaced(self):
        summary = self.generate(self.verify_all())
        stem = daily.file_stem(summary)
        (self.out / stem).write_text('an unrelated file')
        (self.out / (stem + ' (2)')).mkdir()
        saved = daily.save(summary, self.out, self.db, gate=self.gate)
        self.assertEqual(saved.folder.name, stem + ' (3)')
        self.assertEqual((self.out / stem).read_text(), 'an unrelated file')
        self.assertEqual(files(self.out / (stem + ' (2)')), [])
        self.assertEqual(files(saved.folder), sorted([stem + '.html', stem + '.json']))

    def test_interrupted_before_the_commit_point_publishes_nothing(self):
        summary = self.generate(self.verify_all())

        def interrupt(stage):
            if stage == 'before_publish':
                raise KeyboardInterrupt
        with patch.object(daily, '_checkpoint', interrupt):
            with self.assertRaises(KeyboardInterrupt):
                daily.save(summary, self.out, self.db, gate=self.gate)
        self.assertEqual(files(self.out), [])


class JournalModeTests(DailyBase):
    """Re-review P1-D1: saving needs a rollback journal (the held read lock must block other commits). Any other
    journal mode is refused inside the final publication transaction; the mode is never changed."""

    def mode(self):
        with closing(sqlite3.connect(self.db)) as conn:
            return conn.execute('PRAGMA journal_mode').fetchone()[0].lower()

    def set_wal(self):
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower(), 'wal')

    def test_default_rollback_journal_saves(self):
        summary = self.generate(self.verify_all())
        self.assertEqual(self.mode(), 'delete')
        saved = daily.save(summary, self.out, self.db, gate=self.gate)
        self.assertEqual(files(self.out), [saved.folder.name])
        self.assertEqual(self.mode(), 'delete')

    def test_wal_database_is_refused_without_leftovers_or_mode_change(self):
        session = self.verify_all()
        self.set_wal()
        for summary in (self.generate(self.evaluate()),  # generation and preview stay available in WAL
                        self.generate(daily.Session(None, None, False), allow_unverified=True)):
            with self.subTest(verified=summary.verified):
                with self.assertRaises(daily.DailyUnsupported) as caught:
                    daily.save(summary, self.out, self.db, gate=self.gate)
                self.assertIn('WAL', str(caught.exception))
                self.assertEqual(files(self.out), [])  # no report and no .partial staging directory
                self.assertEqual(self.mode(), 'wal')   # never changed by the save
        self.assertIsNotNone(session)

    def test_mode_is_checked_in_the_final_transaction_and_on_retry(self):
        summary = self.generate(self.verify_all())
        with patch.object(daily, '_checkpoint', lambda stage: stage == 'staged' and self.set_wal()):
            with self.assertRaises(daily.DailyUnsupported):  # switched after the early checks, before publication
                daily.save(summary, self.out, self.db, gate=self.gate)
        self.assertEqual((files(self.out), self.mode()), ([], 'wal'))
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('PRAGMA journal_mode=DELETE')
        summary = self.generate(self.evaluate())
        stem = daily.file_stem(summary)
        real = daily._publish

        def racing(staging, target):
            if target.name == stem:
                target.mkdir()  # another program takes the first name at the last moment
            return real(staging, target)
        with patch.object(daily, '_publish', racing),                 patch.object(daily, '_checkpoint', lambda stage: stage == 'retry' and self.set_wal()):
            with self.assertRaises(daily.DailyUnsupported):
                daily.save(summary, self.out, self.db, gate=self.gate)
        self.assertEqual(files(self.out), [stem])  # only the other program's folder, untouched and empty
        self.assertEqual(files(self.out / stem), [])
        self.assertEqual(self.mode(), 'wal')


class RunnerTests(DailyBase):
    def test_one_task_and_one_newest_waiting_request(self):
        runner = daily.DailyRunner()
        release, ran = threading.Event(), []

        def task(n):
            def action():
                ran.append(n)
                if n == 0:
                    release.wait(10)
                return n
            return action
        for n in range(20):
            runner.request(n, 'generate', task(n))
        release.set()
        deadline = time.monotonic() + 10
        while runner.busy and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(ran, [0, 19])
        self.assertEqual(runner.threads_started, 1)
        events = [runner.events.get_nowait()[0] for _ in range(2)]
        self.assertEqual(events, [0, 19])

    def test_nothing_is_delivered_after_close(self):
        runner, release = daily.DailyRunner(), threading.Event()
        runner.request(1, 'generate', lambda: release.wait(10))
        runner.close()
        release.set()
        deadline = time.monotonic() + 10
        while runner.running and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(runner.events.empty())
        self.assertEqual(runner.request(2, 'generate', lambda: 2), 'closed')


class DailyWindowTests(SessionUiBase):
    """The real CheckerApp and window; dialogs are patched, nothing is shown."""

    def setUp(self):
        super().setUp()
        self.out = self.base / 'reports'
        self.out.mkdir()
        self.dialogs = []
        self.window_patches = [
            patch('checker.daily_ui.messagebox.showerror', side_effect=lambda t, text, **kw: self.dialogs.append(text)),
            patch('checker.daily_ui.filedialog.askdirectory', return_value=str(self.out))]
        for p in self.window_patches:
            p.start()

    def tearDown(self):
        for p in self.window_patches:
            p.stop()
        super().tearDown()

    def open(self):
        self.app.open_daily()
        return self.app.daily_window

    def test_verified_generate_preview_save_and_out_of_date(self):
        self.current_session()
        window = self.open()
        self.assertIsNotNone(self.app.daily_link)
        window.generate()  # verified: no confirmation needed
        self.pump(lambda: window.summary is not None)
        self.assertTrue(window.summary.verified)
        self.assertIn('VERIFIED summary', window.state.cget('text'))
        self.assertIn('Cloud Not Verified', window.preview.get('1.0', 'end'))
        self.assertTrue(window.can_save())
        window.save()
        self.pump(lambda: window.saved is not None)
        self.assertEqual(files(self.out), [window.saved.folder.name])
        self.assertEqual(len(files(window.saved.folder)), 2)
        self.app._invalidate_alerts('the Excel files are being checked again')  # e.g. Refresh Excel
        self.pump(lambda: window.stale is not None)
        self.assertIn('OUT OF DATE', window.state.cget('text'))
        self.assertEqual(str(window.save_button.cget('state')), 'disabled')

    def test_unverified_needs_explicit_confirmation(self):
        self.start_app()  # nothing verified in this session
        window = self.open()
        with patch('checker.daily_ui.messagebox.askyesno', return_value=False) as ask:
            window.generate()
        self.assertEqual(ask.call_args.kwargs.get('default'), 'no')
        self.assertEqual(window.runner.threads_started, 0)
        with patch('checker.daily_ui.messagebox.askyesno', return_value=True):
            window.date_text.set((date.today() - timedelta(days=1)).isoformat())
            window.generate()
            self.pump(lambda: window.summary is not None)
        self.assertFalse(window.summary.verified)
        self.assertIn('UNVERIFIED summary', window.state.cget('text'))
        self.assertTrue(window.preview.get('1.0', '2.0').strip().endswith('UNVERIFIED · Cloud Not Verified'))
        window.save()
        self.pump(lambda: window.saved is not None)
        self.assertTrue(all(name.startswith('UNVERIFIED_') for name in files(self.out)))

    def test_worker_detected_problem_asks_before_generating_unverified(self):
        self.current_session()
        window = self.open()
        real, calls = daily.generate, []

        def generate(*args, **kwargs):
            calls.append(kwargs['allow_unverified'])
            if not kwargs['allow_unverified']:
                raise daily.ConfirmationRequired(['synthetic: alerts lag the Storage version'])
            return real(*args, **kwargs)
        with patch.object(daily, 'generate', generate), \
                patch('checker.daily_ui.messagebox.askyesno', return_value=True) as ask:
            window.generate()
            self.pump(lambda: window.summary is not None)
        self.assertEqual(calls, [False, True])
        self.assertIn('alerts lag', ask.call_args.args[1])

    def test_newest_request_wins_and_failure_clears_the_preview(self):
        self.current_session()
        window = self.open()
        real, held = daily.generate, threading.Event()

        def slow(database, day, *args, **kwargs):
            if day == date.today():
                held.wait(10)
            return real(database, day, *args, **kwargs)
        with patch.object(daily, 'generate', slow), patch('checker.daily_ui.messagebox.askyesno', return_value=True):
            window.generate()                                   # today: held
            for back in (1, 2, 3):                              # rapid date changes and repeated clicks
                window.date_text.set((date.today() - timedelta(days=back)).isoformat())
                window.generate()
            held.set()
            self.pump(lambda: window.summary is not None and not window.runner.busy)
        self.assertEqual(window.summary.report_date, (date.today() - timedelta(days=3)).isoformat())
        self.assertLessEqual(window.runner.threads_started, 2)
        with patch.object(daily, 'generate', side_effect=daily.DailyReadError('synthetic database failure')), \
                patch('checker.daily_ui.messagebox.askyesno', return_value=True):
            window.generate()
            self.pump(lambda: window.summary is None and not window.runner.busy)
        self.assertIn('GENERATION FAILED', window.state.cget('text'))
        self.assertEqual(window.preview.get('1.0', 'end').strip(), '')
        self.assertEqual(str(window.save_button.cget('state')), 'disabled')

    def test_closing_during_generation_updates_nothing(self):
        self.current_session()
        window = self.open()
        real, held, finished = daily.generate, threading.Event(), threading.Event()

        def slow(*args, **kwargs):
            held.wait(10)
            try:
                return real(*args, **kwargs)
            finally:
                finished.set()
        errors = []
        self.root.report_callback_exception = lambda *exc: errors.append(exc)
        with patch.object(daily, 'generate', slow):
            window.generate()
            window.close()
            held.set()
            self.assertTrue(finished.wait(10))
            for _ in range(20):
                self.root.update(); time.sleep(0.01)
        self.assertEqual(errors, [])
        self.assertIsNone(self.app.daily_window)
        self.assertTrue(window.runner.events.empty())
        self.assertIsNone(window.summary)
        self.app.open_daily()  # reopening gives a fresh window
        self.assertIsNot(self.app.daily_window, window)

    def test_read_failure_discards_the_session_verification(self):
        self.current_session()
        window = self.open()
        generation = self.app.alert_gate.generation
        with patch.object(daily, '_changes', side_effect=sqlite3.OperationalError('synthetic read failure')):
            window.generate()
            self.pump(lambda: not window.runner.busy and 'GENERATION FAILED' in window.state.cget('text'))
        self.assertFalse(self.app.alert_current)
        self.assertGreater(self.app.alert_gate.generation, generation)
        self.assertIsNone(self.app.alert_authorization())
        self.assertIn('database read failed', self.app.alert_text)

    def test_entry_and_window_fit_small_windows(self):
        self.current_session()
        self.root.deiconify()
        self.root.geometry('960x600')
        self.app.show_page('daily')  # B1: the entry is on the Daily summary page (no shared header row any more)
        self.root.update(); self.app._resize(); self.root.update()
        link = self.app.daily_link
        self.assertTrue(link.winfo_ismapped())
        self.assertLessEqual(link.winfo_rootx() + link.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width())
        self.assertLessEqual(link.winfo_rooty() + link.winfo_height(), self.root.winfo_rooty() + self.root.winfo_height())
        window = self.open()
        for size in ('760x480', '960x600', '1280x720'):
            window.top.geometry(size)
            for _ in range(3):
                window.top.update()
            for widget in (window.banner, window.generate_button, window.save_button, window.state, window.preview):
                self.assertTrue(widget.winfo_ismapped(), (size, widget))
                self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                     window.top.winfo_rooty() + window.top.winfo_height())
                self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                     window.top.winfo_rootx() + window.top.winfo_width())
            self.assertGreater(window.preview.winfo_height(), 120)
