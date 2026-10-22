"""M3.2E entry/task-draft tests. Synthetic files only; never registers Windows tasks."""
from contextlib import closing
from datetime import datetime
import json
import sqlite3
import subprocess
import sys
from unittest.mock import patch
import xml.etree.ElementTree as ET

from checker import jobs, scheduling
from checker.appdata import Settings
from checker.sync import InventorySync
from tests.test_m31 import Base, digest
from tests.test_m32c import make_schema_1, stock_with_threshold
from tests.fixtures import workbook
from tests.test_m32c_remediation import SessionUiBase


class HeadlessTests(Base):
    def setUp(self):
        super().setUp()
        self.output = self.base / 'reports'; self.output.mkdir()
        workbook(self.stock, [('Stock', stock_with_threshold([('A', 0, 5), ('B', 9, 2)]))])
        settings = Settings(self.data / 'settings.json')
        settings.remember('stock', str(self.stock)); settings.remember('bom', str(self.bom))

    def run_job(self, **kwargs):
        def inventory(path, **options):
            return InventorySync(path, settle_seconds=0, **options)
        with patch.object(jobs, 'InventorySync', side_effect=inventory):
            return jobs.run(self.data, self.output, clock=self.clock, **kwargs)

    def test_fresh_job_exports_verified_pair_and_never_writes_sources(self):
        before = digest(self.stock), digest(self.bom)
        result = self.run_job()
        self.assertEqual(result.code, jobs.SUCCESS, result.reason)
        reports = list(self.output.iterdir()); self.assertEqual(len(reports), 1)
        data = json.loads(next(reports[0].glob('*.json')).read_text(encoding='utf-8'))
        self.assertEqual(data['status'], 'VERIFIED')
        self.assertEqual(data['report_id'], result.report_id)
        self.assertEqual(len(list(reports[0].iterdir())), 2)
        self.assertEqual((digest(self.stock), digest(self.bom)), before)
        log = json.loads((self.data / 'daily-runs.json').read_text(encoding='utf-8'))
        self.assertEqual(log[-1]['code'], jobs.SUCCESS)
        self.assertEqual(log[-1]['report_folder'], str(reports[0]))

    def test_source_failure_preserves_cache_but_never_exports_it_and_retries_are_bounded(self):
        self.assertEqual(self.run_job().code, jobs.SUCCESS)
        folders = list(self.output.iterdir()); snapshots = self.count('inventory_snapshots')
        self.stock.unlink(); delays = []
        result = self.run_job(attempts=2, retry_delay=0.25, sleep=delays.append)
        self.assertEqual((result.code, result.attempts), (jobs.SOURCE_ERROR, 2))
        self.assertEqual(delays, [0.25])
        self.assertEqual(len(result.attempt_errors), 2)
        self.assertEqual(list(self.output.iterdir()), folders)
        self.assertEqual(self.count('inventory_snapshots'), snapshots)
        self.assertIn('no cached report', result.reason)

    def test_unchanged_second_run_adds_no_snapshot(self):
        self.assertEqual(self.run_job().code, 0)
        count = self.count('inventory_snapshots')
        self.assertEqual(self.run_job().code, 0)
        self.assertEqual(self.count('inventory_snapshots'), count)

    def test_retry_recovers_only_after_rechecking_restored_sources(self):
        self.sync(); self.sync('bom')
        offline = self.stock.with_suffix('.offline.xlsx')
        self.stock.rename(offline)
        delays = []
        before = digest(offline), digest(self.bom)
        def restore(delay):
            delays.append(delay)
            self.assertEqual(list(self.output.iterdir()), [])
            offline.rename(self.stock)
        result = self.run_job(attempts=3, retry_delay=30, sleep=restore)
        self.assertEqual((result.code, result.attempts), (0, 2), result.reason)
        self.assertEqual(delays, [30])
        self.assertEqual(len(result.attempt_errors), 1)
        self.assertIn('no cached report', result.attempt_errors[0])
        self.assertEqual((digest(self.stock), digest(self.bom)), before)
        report = next(self.output.iterdir())
        self.assertEqual(json.loads(next(report.glob('*.json')).read_text(encoding='utf-8'))['status'], 'VERIFIED')

    def test_three_attempt_limit_records_every_failure_without_a_report(self):
        self.sync(); self.sync('bom')
        self.stock.rename(self.stock.with_suffix('.offline.xlsx'))
        delays = []
        result = self.run_job(attempts=3, retry_delay=30, sleep=delays.append)
        self.assertEqual((result.code, result.attempts), (jobs.SOURCE_ERROR, 3))
        self.assertEqual(delays, [30, 30])
        self.assertEqual(len(result.attempt_errors), 3)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_missing_or_legacy_database_is_not_created_or_upgraded(self):
        self.db.unlink()
        self.assertEqual(self.run_job().code, jobs.DATABASE_ERROR)
        self.assertFalse(self.db.exists())
        make_schema_1(self.db); before = digest(self.db)
        self.assertEqual(self.run_job().code, jobs.CONFIG_ERROR)
        self.assertEqual(digest(self.db), before)

    def test_missing_configuration_or_output_refuses_without_imports(self):
        (self.data / 'settings.json').unlink()
        self.assertEqual(self.run_job().code, jobs.CONFIG_ERROR)
        self.assertEqual(self.count('source_versions'), 0)
        self.assertEqual(jobs.run(self.data, self.base / 'missing').code, jobs.CONFIG_ERROR)

    def test_existing_wal_mode_is_not_changed_and_no_report_is_published(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('PRAGMA journal_mode=WAL')
        result = self.run_job()
        self.assertEqual(result.code, jobs.CONFIG_ERROR)
        self.assertEqual(list(self.output.iterdir()), [])
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('PRAGMA journal_mode').fetchone()[0], 'wal')

    def test_process_lock_prevents_another_cli_instance_without_tk(self):
        with jobs.run_lock(self.data):
            cli = subprocess.run([sys.executable, 'app.py', '--daily-run', str(self.output),
                                  '--data-dir', str(self.data)], capture_output=True, text=True, timeout=10)
        self.assertEqual(cli.returncode, jobs.ALREADY_RUNNING, cli.stderr)
        self.assertEqual(json.loads(cli.stdout)['code'], jobs.ALREADY_RUNNING)
        self.assertEqual(list(self.output.iterdir()), [])
        # Releasing the OS lock allows the next run; the sentinel itself does not block it.
        self.assertEqual(self.run_job().code, jobs.SUCCESS)

    def test_cli_missing_database_exits_without_importing_tk_ui(self):
        source = ("import sys,app; sys.argv=['app.py','--daily-run',sys.argv[1],'--data-dir',sys.argv[2]]; "
                  "code=app.main(); assert 'checker.ui' not in sys.modules; raise SystemExit(code)")
        cli = subprocess.run([sys.executable, '-c', source, str(self.output), str(self.base / 'not_configured')],
                             capture_output=True, text=True, timeout=10)
        self.assertEqual(cli.returncode, jobs.CONFIG_ERROR, cli.stderr)
        self.assertFalse((self.base / 'not_configured').exists())

    def test_empty_output_cli_argument_is_rejected_instead_of_starting_gui(self):
        cli = subprocess.run([sys.executable, 'app.py', '--daily-run', ''],
                             capture_output=True, text=True, timeout=5)
        self.assertEqual(cli.returncode, 2)
        self.assertIn('non-empty output folder', cli.stderr)

    def test_successful_actual_cli_exports_without_a_gui(self):
        # Preimport fixtures so the actual CLI takes its cheap UNCHANGED path (no artificial settle sleep).
        self.sync(); self.sync('bom')
        source = ("import sys,app; sys.argv=['app.py','--daily-run',sys.argv[1],'--data-dir',sys.argv[2]]; "
                  "code=app.main(); assert 'checker.ui' not in sys.modules; raise SystemExit(code)")
        cli = subprocess.run([sys.executable, '-c', source, str(self.output), str(self.data)],
                             capture_output=True, text=True, timeout=10)
        self.assertEqual(cli.returncode, 0, cli.stderr + cli.stdout)
        result = json.loads(cli.stdout)
        self.assertEqual(result['code'], 0)
        report = next(self.output.iterdir())
        self.assertEqual(json.loads(next(report.glob('*.json')).read_text(encoding='utf-8'))['status'], 'VERIFIED')

    def test_stale_generation_or_saving_failure_leaves_no_success_receipt(self):
        from checker import daily
        with patch.object(daily, 'save', side_effect=daily.DailyStale('synthetic version race')):
            result = self.run_job()
        self.assertEqual(result.code, jobs.SAVE_ERROR)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertNotEqual(json.loads((self.data / 'daily-runs.json').read_text())[-1]['code'], 0)

    def test_log_failure_preserves_published_report_path_and_original_log(self):
        log = self.data / 'daily-runs.json'; log.write_text('invalid existing log', encoding='utf-8')
        result = self.run_job()
        self.assertEqual(result.code, jobs.SAVE_ERROR)
        self.assertIsNotNone(result.report_folder)
        self.assertEqual(log.read_text(), 'invalid existing log')
        self.assertEqual(len(list(self.output.iterdir())), 1)

    def test_bounded_receipts_keep_latest_success(self):
        successful = jobs.Outcome('success', 0, 'done', 1, '2026-10-22 00:00:00.000')
        rows = [successful.__dict__] + [jobs.Outcome(str(i), 3, 'failed', 1, '2026-10-22 00:00:00.000').__dict__
                                       for i in range(205)]
        path = self.data / 'daily-runs.json'; path.write_text(json.dumps(rows), encoding='utf-8')
        jobs._record(self.data, jobs.Outcome('last', 3, 'failed', 1, '2026-10-22 00:00:00.000'))
        kept = json.loads(path.read_text())
        self.assertEqual((len(kept), kept[0]['run_id'], kept[-1]['run_id']), (201, 'success', 'last'))


class TaskDraftTests(Base):
    def test_draft_is_safe_quoted_and_has_no_side_effects(self):
        out = self.base / 'reports & daily'; out.mkdir()
        with patch('subprocess.run', side_effect=AssertionError('Must not register tasks')):
            payload = scheduling.task_xml(self.data, out, '18:05', principal='DOMAIN\\Tester',
                                          now=datetime(2026, 10, 22, 10), executable=sys.executable,
                                          prefix=(str(self.base / 'project folder' / 'app.py'),))
        root = ET.fromstring(payload); ns = {'t': scheduling.NAMESPACE}
        text = lambda path: root.find(path, ns).text
        self.assertEqual(text('.//t:LogonType'), 'InteractiveToken')
        self.assertEqual(text('.//t:RunLevel'), 'LeastPrivilege')
        self.assertEqual(text('.//t:MultipleInstancesPolicy'), 'IgnoreNew')
        self.assertEqual(text('.//t:StartWhenAvailable'), 'true')
        self.assertEqual(text('.//t:StartBoundary'), '2026-10-22T18:05:00')
        self.assertIn('"' + str(out) + '"', text('.//t:Arguments'))
        self.assertIn('--daily-run', text('.//t:Arguments'))
        self.assertIsNone(root.find('.//t:RestartOnFailure', ns))
        self.assertIn('--daily-attempts 3 --daily-retry-delay 30', text('.//t:Arguments'))
        self.assertFalse(any('password' in node.tag.lower() for node in root.iter()))

    def test_invalid_time_and_missing_paths_are_refused(self):
        for at in ('25:00', '18:61', '6:00', '18:00\nmalicious'):
            with self.assertRaises(ValueError):
                scheduling.task_xml(self.data, self.base, at)
        with self.assertRaises(ValueError):
            scheduling.task_xml(self.data, self.base / 'missing', '18:00')


class ScheduleWindowTests(SessionUiBase):
    def test_declined_draft_does_not_save_or_create_a_task(self):
        self.current_session(); self.app.open_daily()
        with patch('checker.daily_ui.filedialog.askdirectory', return_value=str(self.base)), \
             patch('tkinter.simpledialog.askstring', return_value='18:00'), \
             patch('checker.daily_ui.messagebox.askyesno', return_value=False) as confirm, \
             patch('checker.daily_ui.filedialog.asksaveasfilename', side_effect=AssertionError('Declined draft')):
            self.app.daily_window.schedule_draft()
        self.assertEqual(confirm.call_args.kwargs['default'], 'no')
        self.assertIn('no Windows task', confirm.call_args.args[1])

    def test_confirmed_draft_writes_only_xml_and_never_overwrites(self):
        self.current_session(); self.app.open_daily()
        path = self.base / 'schedule.xml'
        with patch('checker.daily_ui.filedialog.askdirectory', return_value=str(self.base)), \
             patch('tkinter.simpledialog.askstring', return_value='18:00'), \
             patch('checker.daily_ui.messagebox.askyesno', return_value=True), \
             patch('checker.daily_ui.filedialog.asksaveasfilename', return_value=str(path)), \
             patch('checker.daily_ui.messagebox.showinfo'), \
             patch('checker.daily_ui.messagebox.showerror') as error, \
             patch('subprocess.run', side_effect=AssertionError('Never installs tasks')):
            self.app.daily_window.schedule_draft()
            first = path.read_bytes(); ET.fromstring(first)
            self.app.daily_window.schedule_draft()
            self.assertTrue(error.called)
            self.assertEqual(path.read_bytes(), first)
