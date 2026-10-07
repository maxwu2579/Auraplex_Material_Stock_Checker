"""Windows entry point. Source workbooks are never saved."""
import tkinter as tk
import argparse
import json
import sys
from pathlib import Path

from checker import ui
from checker.ui import CheckerApp

VERSION = "1.0.0"


def self_test(root, app, storage, bom, output_dir):
    """Packaging check: drive one load / search / check / export with the given (synthetic) workbooks, then exit.

    Writes self_test.json to output_dir because a windowed executable has no console. Not used in normal operation."""
    output = Path(output_dir)
    errors, report = [], {"version": VERSION, "frozen": bool(getattr(sys, "frozen", False)), "executable": sys.executable,
                          "ui_module": ui.__file__, "passed": False}
    ui.messagebox.showerror = lambda title, text, **kw: errors.append(f"{title}: {text}")  # a modal box would block the check
    steps = [("stock", storage), ("bom", bom)]

    def finish():
        report["errors"] = errors
        (output / "self_test.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        app.close()

    def step():
        try:
            if app.busy:
                return root.after(30, step)
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
            else:
                result = app.result
                report["window"] = [root.winfo_width(), root.winfo_height()]
                report["counts"] = {c: result.category_count(c) for c in ("SHORTAGE", "EXCEPTION", "ENOUGH")} if result else None
                report["rows"] = [[*app.tree.item(i, "values"), app.tree.item(i, "tags")[0]] for i in app.tree.get_children()]
                written = app.write_export(str(output / "self_test_report.xlsx")) if result else None
                report["export"] = str(written) if written else None
                report["passed"] = bool(result and written and not errors)
                return finish()
            root.after(30, step)
        except Exception as exc:  # the check itself failed; record it instead of leaving a window open
            errors.append(repr(exc))
            finish()

    root.after(200, step)


def main():
    parser = argparse.ArgumentParser(description="Material requirement and stock checker (read-only)")
    parser.add_argument("--smoke-test", action="store_true", help="Create the UI hidden and exit; no files selected")
    parser.add_argument("--self-test", nargs=3, metavar=("STORAGE", "BOM", "OUTPUT_DIR"),
                        help="Packaging check with synthetic workbooks; writes self_test.json and a report to OUTPUT_DIR")
    args = parser.parse_args()
    root = tk.Tk()
    if args.smoke_test:
        root.withdraw()
    app = CheckerApp(root)
    if args.smoke_test:
        root.after(150, app.close)
    if args.self_test:
        self_test(root, app, *args.self_test)
    root.mainloop()
    if args.smoke_test and sys.stdout is not None:
        print("M0 launcher / Tkinter initialization: PASS")


if __name__ == "__main__":
    main()
