"""Synthetic, visible M2.1 preview. No production workbook is accessed."""
import argparse
import json
from pathlib import Path
import tkinter as tk

from checker.ui import CheckerApp
from tests.fixtures import workbook, stock_rows, bom_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scale', type=float, default=1)
    parser.add_argument('--size', default='1280x700')
    args = parser.parse_args()
    base = Path('test-artifacts/m21/preview-inputs').resolve()
    base.mkdir(parents=True, exist_ok=True)
    long_code = 'DEMO-210-MATERIAL-LONG-ID-WITH-REVISION-07-MIR-K'
    storage = workbook(base / 'Storage Demo.xlsx', [('Stock', stock_rows([
        (long_code, 2), ('MOTOR-SV-400W', 120), ('TEXT-STOCK', '0+10'), ('DUP-LOCATION', 5), ('DUP-LOCATION', 9),
        *[(f'FASTENER-{n:03}', 0 if n % 3 == 0 else 100) for n in range(1, 25)]
    ]))])
    data = bom_rows([(long_code, 3), ('MOTOR-SV-400W', 2), ('TEXT-STOCK', 1), ('DUP-LOCATION', 1), ('MISSING-PART', 1),
                     *[(f'FASTENER-{n:03}', 1) for n in range(1, 25)]])
    data[22]['E'] = 'Long description: precision machined stainless steel mounting bracket with left / right assembly variants'
    bom = workbook(base / 'BOM Demo.xlsx', [('DEMO-115-PREVIEW ', data)])
    (base / '~$Storage Demo.xlsx').write_bytes(b'synthetic owner marker')
    root = tk.Tk()
    root.tk.call('tk', 'scaling', 96 / 72 * args.scale)
    app = CheckerApp(root)
    root.title(f'Material Requirement & Stock Checker · Synthetic Preview {args.scale:.0%}')
    root.geometry(args.size + '+0+0')
    steps = [('stock', storage), ('bom', bom)]

    def prepare():
        if app.busy:
            root.after(30, prepare)
        elif steps:
            role, path = steps.pop(0)
            app.load_file(role, str(path))
            root.after(30, prepare)
        elif app.result is None:
            app.product_combo.current(0)
            app.quantity_text.set('10')
            app.check()
            root.after(30, record)

    def record():
        if app.busy:
            root.after(30, record)
            return
        root.update_idletasks()
        metrics = {'scale': args.scale, 'window': [root.winfo_width(), root.winfo_height()],
                   'check': [app.check_button.winfo_rootx(), app.check_button.winfo_rooty(), app.check_button.winfo_width(), app.check_button.winfo_height()],
                   'table_height': app.tree.winfo_height(), 'result_rows': len(app.result.rows)}
        (base.parent / f'preview_{int(args.scale*100)}_geometry.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')

    root.after(60, prepare)
    root.mainloop()


if __name__ == '__main__':
    main()
