"""Windows entry point. Source workbooks are never saved."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

from checker.appdata import InterfacePreferences, Settings, default_data_dir
from checker.inventory_db import DatabaseError
from checker.sync import LOCAL_VERIFIED, InventorySync

VERSION = "1.1.0.dev0"
SELF_TEST_TIMEOUT_MS = 180_000   # Tk timer (not a hard deadline): an unfinished self-test is then failed and closed
# --self-test exit codes: 0 passed, 1 ran but did not pass (or did not finish), 2 OUTPUT_DIR or self_test.json unusable
SELF_TEST_FAILED, SELF_TEST_UNWRITABLE = 1, 2


def say(text):
    """A windowed executable has no console: stderr may be None."""
    if sys.stderr is not None:
        print(text, file=sys.stderr)


def open_local_data(data_dir):
    """Remembered paths and the local inventory database. A database problem never stops the Excel checker."""
    data_dir = Path(data_dir)
    settings = Settings(data_dir / "settings.json")
    try:
        return InventorySync(data_dir / "inventory.db", app_version=VERSION), settings, None
    except DatabaseError as exc:
        return None, settings, str(exc)


def self_test(root, app, storage, bom, output_dir):
    """Packaging check: drive one load / search / check / export / Refresh Excel with the given (synthetic) workbooks,
    then exit.

    Writes self_test.json to output_dir because a windowed executable has no console. Not used in normal operation.
    Returns {"code": ...}, filled in when the check finishes: the window is closed even if self_test.json cannot be
    written. SELF_TEST_TIMEOUT_MS is a Tk timer, not a hard process deadline: it cannot fire while a Tk callback is
    blocked, and a non-daemon export worker in an uninterruptible step keeps the process alive until that step ends."""
    from checker import ui
    output = Path(output_dir)
    outcome, exporting = {"code": None}, []
    errors, report = [], {"version": VERSION, "frozen": bool(getattr(sys, "frozen", False)), "executable": sys.executable,
                          "ui_module": ui.__file__, "passed": False}
    ui.messagebox.showerror = lambda title, text, **kw: errors.append(f"{title}: {text}")  # a modal box would block the check
    ui.messagebox.showwarning = lambda title, text, **kw: errors.append(f"{title}: {text}")
    steps = [("stock", storage), ("bom", bom)]

    def database():
        if app.inventory is None:
            return {"error": app.inventory_error}
        connection = app.inventory.connect()
        try:
            count = lambda sql: connection.execute(sql).fetchone()[0]
            return {"path": str(app.inventory.db_path),
                    "states": {role: info.state for role, info in app.inventory_roles.items()},
                    "source_versions": count("SELECT count(*) FROM source_versions"),
                    "snapshots": count("SELECT count(*) FROM inventory_snapshots"),
                    "runs": [tuple(r) for r in connection.execute("SELECT role, trigger, outcome FROM sync_runs ORDER BY id")]}
        finally:
            connection.close()

    def finish():
        if outcome["code"] is not None:
            return
        report["errors"] = errors
        try:
            (output / "self_test.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            outcome["code"] = 0 if report["passed"] else SELF_TEST_FAILED
        except (OSError, TypeError, ValueError) as exc:
            outcome["code"] = SELF_TEST_UNWRITABLE
            say(f"Self-test result could not be written to {output / 'self_test.json'}: {type(exc).__name__}: {exc}")
        finally:
            try:
                app.close()
            except Exception:  # the window must go away whatever happened
                root.destroy()

    def timeout():
        errors.append(f"Self-test did not finish within {SELF_TEST_TIMEOUT_MS // 1000} s")
        finish()

    def step():
        try:
            if app.busy:
                return root.after(30, step)
            if "database_at_start" not in report:
                report["database_at_start"] = database()
            if steps:
                role, path = steps.pop(0)
                app.load_file(role, path)
            elif app.result is None and "product_id" not in report:
                ids = list(app.product_combo["values"])
                report["product_ids"] = ids
                app.product_text.set(ids[0][:4].lower())  # partial, other letter case
                app._search()
                report["search_candidates"] = list(app.product_combo["values"])
                app.check()                                # partial text alone must be refused
                report["partial_text_refused"] = app.result is None and not app.busy and len(errors) == 1
                errors.clear()
                report["product_id"] = ids[0]
                app.product_text.set(ids[0])
                app.quantity_text.set("10")
                app.check()
            elif "export_started" not in report:
                result = app.result
                report["window"] = [root.winfo_width(), root.winfo_height()]
                report["counts"] = {c: result.category_count(c) for c in ("SHORTAGE", "EXCEPTION", "ENOUGH")} if result else None
                report["rows"] = [[*app.tree.item(i, "values"), app.tree.item(i, "tags")[0]] for i in app.tree.get_children()]
                report["result_verified"] = app.result_current  # bound to the confirmed Storage/BOM versions
                # The background export holds app.busy; the next steps wait for it above.
                exporting.append(app.start_export(str(output / "self_test_report.xlsx")) if result else None)
                report["export_started"] = exporting[0] is not None
            elif "export" not in report:
                task = exporting[0]
                report["export"] = str(task.written) if task is not None and task.accepted else None
                report["database_before_refresh"] = database()
                app.refresh_excel()                        # unchanged files: no new version, no new snapshot
            else:
                before, after = report["database_before_refresh"], database()
                report["database_after_refresh"] = after
                report["inventory_status"] = app.db_status.get() if app.db_panel is not None else None
                report["cloud_notice"] = (app.db_cloud_label.cget("text") if app.db_panel is not None
                                          and app.db_cloud_label.winfo_manager() else None)
                report["refresh_unchanged"] = (app.inventory is not None and after["snapshots"] == before["snapshots"]
                                               and after["source_versions"] == before["source_versions"]
                                               and [r[2] for r in after["runs"][-2:]] == ["UNCHANGED", "UNCHANGED"])
                report["passed"] = bool(app.result and report["result_verified"] and report["export"] and not errors
                                        and report["refresh_unchanged"] and report["cloud_notice"] == "Cloud Not Verified"
                                        and set(after["states"].values()) == {LOCAL_VERIFIED})
                return finish()
            root.after(30, step)
        except (Exception, sqlite3.Error) as exc:  # the check itself failed; record it instead of leaving a window open
            errors.append(repr(exc))
            finish()

    root.after(200, step)
    root.after(SELF_TEST_TIMEOUT_MS, timeout)
    return outcome


def main():
    parser = argparse.ArgumentParser(description="Material requirement and stock checker (read-only)")
    parser.add_argument("--smoke-test", action="store_true",
                        help="Create the UI hidden and exit; no files selected and no local data used unless --data-dir")
    parser.add_argument("--self-test", nargs=3, metavar=("STORAGE", "BOM", "OUTPUT_DIR"),
                        help="Packaging check with synthetic workbooks; writes self_test.json and a report to OUTPUT_DIR")
    parser.add_argument("--data-dir", help="Folder for the local inventory database and remembered paths "
                                           r"(default %%LOCALAPPDATA%%\Auraplex\MaterialStockChecker; "
                                           "self-test default OUTPUT_DIR\\appdata)")
    parser.add_argument("--daily-run", metavar="OUTPUT_DIR",
                        help="Unattended daily run: verify remembered Excel files, evaluate and save HTML/JSON; no UI")
    parser.add_argument("--daily-attempts", type=int, choices=(1, 2, 3), default=1,
                        help="Bounded unattended attempts (default 1; schedule drafts explicitly request 3)")
    parser.add_argument("--daily-retry-delay", type=float, default=5,
                        help="Seconds between unattended attempts, 0–30 (default 5)")
    args = parser.parse_args()
    if args.daily_run is not None:
        if args.smoke_test or args.self_test:
            parser.error('--daily-run cannot be combined with GUI smoke/self-test')
        if not args.daily_run.strip():
            parser.error('--daily-run requires a non-empty output folder')
        from checker.jobs import run
        outcome = run(args.data_dir or default_data_dir(), args.daily_run,
                      attempts=args.daily_attempts, retry_delay=args.daily_retry_delay)
        if sys.stdout is not None:
            print(json.dumps(outcome.__dict__, ensure_ascii=True))  # machine-readable on Windows console code pages
        return outcome.code
    if args.self_test:
        # Created on demand inside the given folder only; never another folder, never the real application data.
        output = Path(args.self_test[2])
        try:
            output.mkdir(parents=True, exist_ok=True)
            if not output.is_dir():
                raise NotADirectoryError(f"not a folder: {output}")
        except (OSError, ValueError) as exc:
            say(f"Self-test OUTPUT_DIR is unusable: {output}: {type(exc).__name__}: {exc}")
            return SELF_TEST_UNWRITABLE
    import tkinter as tk
    from checker.ui import CheckerApp
    root = tk.Tk()
    if args.smoke_test:
        root.withdraw()
    data_dir = args.data_dir or (Path(args.self_test[2]) / "appdata" if args.self_test else
                                 None if args.smoke_test else default_data_dir())
    inventory, settings, error = open_local_data(data_dir) if data_dir else (None, None, None)
    # The interface language has its own file beside settings.json; reading it never blocks start-up.
    preferences = InterfacePreferences(Path(data_dir) / "interface.json") if data_dir else None
    app = CheckerApp(root, inventory=inventory, settings=settings, inventory_error=error, preferences=preferences)
    if args.smoke_test:
        root.after(150, app.close)
    outcome = self_test(root, app, *args.self_test) if args.self_test else None
    root.mainloop()
    if args.smoke_test and sys.stdout is not None:
        print("M0 launcher / Tkinter initialization: PASS" + (f" · inventory database: {'OK' if inventory else error}"
                                                              if data_dir else ""))
    if outcome is not None:  # a window closed before the check finished counts as a failure
        return SELF_TEST_FAILED if outcome["code"] is None else outcome["code"]


if __name__ == "__main__":
    raise SystemExit(main())
