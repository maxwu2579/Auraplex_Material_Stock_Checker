from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from .core import (DataReadError, ENOUGH, EXCEPTION, ROW_CAVEAT, SHORTAGE, check_materials, display,
                   production_quantity, search_products, select_product)
from .report import ReportError, default_filename, save_report
from .service import CheckerService
from .presentation import BG, INK, MUTED, BLUE, RED, AMBER, Tooltip, ellipsize, work_area


ROLES = {"stock": "Storage / 库存 Excel", "bom": "BOM Excel"}
ROW_COLOURS = {SHORTAGE: RED, EXCEPTION: AMBER}  # soft red/yellow; ENOUGH is explicitly white
SHEET_GONE = "源文件更新后，所选 Sheet 不再存在/不符合表头。请 Reload Files 并重新选择。"


def clock(seconds):
    return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M:%S")


class CheckerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.service = CheckerService()
        self.stock_book = self.bom_book = self.result = None
        self.busy = False
        self.closed = False
        self.cancelled = threading.Event()
        self.events = queue.Queue()
        self.stock_path = tk.StringVar()
        self.bom_path = tk.StringVar()
        self.stock_name = tk.StringVar()
        self.product_text = tk.StringVar()
        self.quantity_text = tk.StringVar(value="1")
        self.filter_category = tk.StringVar(value="All")
        self.summary_counts = {key: tk.StringVar(value="—") for key in ("total", SHORTAGE, EXCEPTION, ENOUGH)}
        self.file_view = {}
        self.export_path = tk.StringVar()
        self.row_detail_window = None
        self.file_status = {"stock": tk.StringVar(value="尚未选择 Storage 工作簿（.xlsx / .xlsm）"),
                            "bom": tk.StringVar(value="尚未选择 BOM 工作簿（.xlsx / .xlsm）")}
        self.file_labels = {}
        self.status = tk.StringVar(value="Ready · Choose Storage and BOM files.")
        self.summary = tk.StringVar(value="尚未检查 · Verification Required")
        self._resize_job = None
        self._build()
        for var in (self.stock_name, self.product_text, self.quantity_text):
            var.trace_add("write", lambda *_: self.invalidate())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = self.root.after(50, self._poll)

    def _build(self):
        self.root.title("Material Requirement & Stock Checker")
        left, top, width, height = work_area(self.root)
        self.root.geometry(f"{min(1280, width - 32)}x{min(800, height - 48)}+{left + 16}+{top + 16}")
        self.root.minsize(min(960, width - 32), min(580, height - 48))
        self.root.configure(background=BG)
        style = ttk.Style(self.root)
        style.theme_use("clam")  # built-in; reliable row colours and button states on Windows
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Section.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Card.TFrame", background="white")
        style.configure("Card.TLabel", background="white")
        style.configure("CardMuted.TLabel", background="white", foreground=MUTED, font=("Segoe UI", 9))
        style.configure("File.TLabel", background="white", font=("Segoe UI", 10, "bold"))
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 7), background="white", borderwidth=1)
        style.configure("Primary.TButton", background=BLUE, foreground="white", font=("Segoe UI", 10, "bold"), padding=(16, 9))
        style.map("Primary.TButton", background=[("disabled", "#dfe5ed"), ("pressed", "#174c8a"), ("active", "#3274bc")],
                  foreground=[("disabled", "#8793a2"), ("!disabled", "white")])
        style.configure("TCombobox", padding=5, font=("Segoe UI", 10))
        style.configure("TEntry", padding=5)
        self.root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))
        style.configure("Treeview", background="white", fieldbackground="white", foreground=INK,
                        font=("Segoe UI", 9), rowheight=max(30, int(float(self.root.tk.call("tk", "scaling")) * 19)), borderwidth=0)
        style.configure("Treeview.Heading", background="#eaf0f5", foreground=INK, font=("Segoe UI", 9, "bold"), padding=(8, 8))
        style.map("Treeview", background=[("selected", "#dbe9fa")], foreground=[("selected", "#163d6b")])
        style.configure("Filter.TRadiobutton", background=BG, padding=(10, 5), font=("Segoe UI", 9))
        style.layout("Filter.TRadiobutton", [("Radiobutton.padding", {"sticky": "nswe", "children": [
            ("Radiobutton.label", {"sticky": "nswe"})]})])
        style.map("Filter.TRadiobutton", background=[("selected", "#dbe9fa"), ("active", "#eaf0f5")],
                  foreground=[("selected", "#174c8a")])
        self.outer = outer = ttk.Frame(self.root, padding=(16, 12))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(5, weight=1)
        self.overview = ttk.Frame(outer)
        self.overview.grid(row=0, sticky="ew")
        self.overview.columnconfigure(0, weight=1)
        self.overview_canvas = tk.Canvas(self.overview, background=BG, highlightthickness=0, height=1)
        self.overview_canvas.grid(row=0, column=0, sticky="ew")
        self.overview_scroll = ttk.Scrollbar(self.overview, orient="vertical", command=self.overview_canvas.yview)
        self.overview_scroll.grid(row=0, column=1, sticky="ns")
        self.overview_canvas.configure(yscrollcommand=self.overview_scroll.set)
        self.overview_content = ttk.Frame(self.overview_canvas)
        self.overview_content.columnconfigure(0, weight=1)
        self.overview_window = self.overview_canvas.create_window(0, 0, anchor="nw", window=self.overview_content)
        self.overview_canvas.bind("<Configure>", lambda e: self.overview_canvas.itemconfigure(self.overview_window, width=e.width))
        self.overview_content.bind("<Configure>", lambda _e: self.overview_canvas.configure(scrollregion=self.overview_canvas.bbox("all")))
        heading = ttk.Frame(self.overview_content)
        heading.grid(row=0, sticky="ew", pady=(0, 12))
        ttk.Label(heading, text="Material Requirement & Stock Checker", style="Title.TLabel").pack(anchor="w")
        ttk.Label(heading, text="Check material requirements against current stock.", style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
        files = ttk.Frame(self.overview_content)
        files.grid(row=1, sticky="ew", pady=(0, 12))
        files.columnconfigure((0, 1), weight=1, uniform="files")
        self.controls = []
        for col, role in enumerate(("stock", "bom")):
            card = ttk.Frame(files, style="Card.TFrame", padding=(12, 8))
            card.grid(row=0, column=col, sticky="nsew", padx=(0, 6) if col == 0 else (6, 0))
            card.columnconfigure(0, weight=1)
            ttk.Label(card, text="Storage File" if role == "stock" else "BOM File", style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
            button = ttk.Button(card, text="Browse…", command=lambda r=role: self.browse(r))
            button.grid(row=0, column=1, rowspan=2, sticky="ne", padx=(12, 0))
            name = ttk.Label(card, text="Choose an Excel workbook", style="File.TLabel", cursor="hand2")
            name.grid(row=1, column=0, sticky="ew", pady=(4, 0))
            path = ttk.Label(card, text=".xlsx / .xlsm", style="CardMuted.TLabel", cursor="hand2")
            path.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
            status = ttk.Label(card, text="Not loaded", style="CardMuted.TLabel", cursor="hand2")
            status.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))
            warning = ttk.Label(card, text="", style="CardMuted.TLabel", foreground="#95641a")
            # Empty warning consumes no vertical space; visible only for an owner file.
            self.file_view[role] = dict(card=card, name=name, path=path, status=status, warning=warning, button=button, locks=(), loading=False)
            self.file_labels[role] = status
            self.controls.append((button, "normal"))
            for label in (name, path, status, warning):
                Tooltip(label, lambda r=role: self._file_details(r))
                label.bind("<Button-1>", lambda _e, r=role: self.file_details(r))
            card.bind("<Configure>", lambda _e, r=role: self._refresh_file_card(r))
        selections = ttk.Frame(outer, style="Card.TFrame", padding=(12, 8))
        selections.grid(row=2, sticky="ew")
        selections.columnconfigure(0, weight=1)
        ttk.Label(selections, text="Product ID", style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(selections, text="Quantity", style="CardMuted.TLabel").grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.product_combo = ttk.Combobox(selections, textvariable=self.product_text, state="normal", font=("Segoe UI", 10))
        self.product_combo.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.product_combo.bind("<KeyRelease>", self._search)
        self.product_combo.bind("<FocusIn>", lambda _event: self._search())
        self.product_combo.bind("<<ComboboxSelected>>", lambda _event: self._search(reset=True))
        self.product_combo.bind("<Return>", self._pick)
        Tooltip(self.product_combo, lambda: self.product_text.get() or "Type part of a Product ID, then select a match.")
        self.quantity_entry = ttk.Entry(selections, textvariable=self.quantity_text, width=6, font=("Segoe UI", 10))
        self.quantity_entry.grid(row=1, column=1, padx=(12, 12), pady=(4, 0))
        self.quantity_entry.bind("<Return>", lambda _event: self.check())
        self.check_button = ttk.Button(selections, text="CHECK MATERIALS", style="Primary.TButton", command=self.check)
        self.check_button.grid(row=1, column=2, padx=(0, 8), pady=(4, 0))
        self.export_button = ttk.Button(selections, text="EXPORT EXCEL", command=self.export)
        self.export_button.grid(row=1, column=3, pady=(4, 0))
        # Multi-sheet stock selection stays explicit. Hide it for the common single-sheet case.
        self.stock_sheet_frame = ttk.Frame(selections, style="Card.TFrame")
        self.stock_sheet_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Label(self.stock_sheet_frame, text="Storage Sheet", style="CardMuted.TLabel").pack(side="left", padx=(0, 8))
        self.stock_combo = ttk.Combobox(self.stock_sheet_frame, textvariable=self.stock_name, state="readonly")
        self.stock_combo.pack(side="left", fill="x", expand=True)
        self.stock_sheet_frame.grid_remove()
        for control, state in ((self.stock_combo, "readonly"), (self.product_combo, "normal"), (self.quantity_entry, "normal"),
                               (self.check_button, "normal"), (self.export_button, "normal")):
            self.controls.append((control, state))
        notice = ttk.Frame(outer)
        notice.grid(row=3, sticky="ew", pady=(8, 10))
        notice.columnconfigure(0, weight=1)
        self.notice_label = ttk.Label(notice, text="Results are calculated from the selected BOM and current saved Storage data.", style="Muted.TLabel")
        self.notice_label.grid(row=0, column=0, sticky="w")
        Tooltip(self.notice_label, lambda: "Review yellow Exception rows before use.\nVerification Required · " + ROW_CAVEAT)
        self.reload_button = ttk.Button(notice, text="Reload Files", command=self.reload_files)
        self.reload_button.grid(row=0, column=1, padx=(8, 0))
        self.controls.append((self.reload_button, "normal"))
        summary = ttk.Frame(outer)
        summary.grid(row=4, sticky="ew", pady=(0, 12))
        for col, (key, title, hint, colour) in enumerate((("total", "Total Materials", "Material rows", INK),
                 (SHORTAGE, "Shortage", "Needs stock", "#a53432"), (EXCEPTION, "Exceptions", "Check data", "#95641a"),
                 (ENOUGH, "Enough", "Sufficient stock", "#3b715e"))):
            summary.columnconfigure(col, weight=1, uniform="summary")
            card = ttk.Frame(summary, style="Card.TFrame", padding=(12, 6))
            card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 4, 0 if col == 3 else 4))
            ttk.Label(card, text=title, style="CardMuted.TLabel").pack(anchor="w")
            line = ttk.Frame(card, style="Card.TFrame")
            line.pack(fill="x", pady=(2, 0))
            ttk.Label(line, textvariable=self.summary_counts[key], style="Card.TLabel", font=("Segoe UI", 18, "bold"), foreground=colour).pack(side="left")
            ttk.Label(line, text=hint, style="CardMuted.TLabel").pack(side="left", padx=(10, 0))
        results = ttk.Frame(outer, style="Card.TFrame", padding=8)
        results.grid(row=5, sticky="nsew")
        results.rowconfigure(1, weight=1)
        results.columnconfigure(0, weight=1)
        toolbar = ttk.Frame(results, style="Card.TFrame")
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(toolbar, text="Material Results", style="Card.TLabel", font=("Segoe UI", 11, "bold")).pack(side="left", padx=(2, 16))
        self.filter_buttons = {}
        for label, value in (("All", "All"), ("Shortage", SHORTAGE), ("Exceptions", EXCEPTION), ("Enough", ENOUGH)):
            button = ttk.Radiobutton(toolbar, text=label, variable=self.filter_category, value=value,
                                     style="Filter.TRadiobutton", command=self._fill_tree)
            button.pack(side="left", padx=2)
            self.filter_buttons[value] = button
            self.controls.append((button, "normal"))
        columns = [("code", "Material ID", 170), ("description", "Description", 245), ("required", "Required", 85),
                   ("stock", "Stock", 110), ("shortage", "Shortage", 85), ("result", "Result", 100),
                   ("status", "Data Status", 220), ("rack", "Rack", 64), ("level", "Level", 64)]
        self.tree = ttk.Treeview(results, columns=[x[0] for x in columns], show="headings", selectmode="browse", height=4)
        for ident, label, width in columns:
            self.tree.heading(ident, text=label, anchor="center")
            heading_width = tkfont.Font(font=("Segoe UI", 9, "bold")).measure(label) + 24
            self.tree.column(ident, width=max(width, heading_width), minwidth=heading_width, stretch=ident in ("description", "status"),
                             anchor="e" if ident in ("required", "stock", "shortage") else "w")
        self.tree.grid(row=1, column=0, sticky="nsew")
        y = ttk.Scrollbar(results, orient="vertical", command=self.tree.yview)
        y.grid(row=1, column=1, sticky="ns")
        x = ttk.Scrollbar(results, orient="horizontal", command=self.tree.xview)
        x.grid(row=2, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        for category, colour in ROW_COLOURS.items():
            self.tree.tag_configure(category, background=colour)
        self.tree.tag_configure(ENOUGH, background="white")
        self.tree.bind("<<TreeviewSelect>>", self.show_details)
        self.detail_frame = ttk.Frame(outer, style="Card.TFrame", padding=(10, 6))
        self.detail_frame.grid(row=6, sticky="ew", pady=(8, 0))
        self.detail_frame.columnconfigure(0, weight=1)
        ttk.Label(self.detail_frame, text="Selected Material · Source & Data", style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(self.detail_frame, text="Close details", command=self.hide_details, padding=(6, 2)).grid(row=0, column=1, sticky="e")
        self.details = tk.Text(self.detail_frame, height=2, wrap="word", font=("Segoe UI", 9), state="disabled",
                               background="white", foreground=INK, relief="flat", padx=0, pady=4)
        self.details.grid(row=1, column=0, columnspan=2, sticky="ew")
        scroll = ttk.Scrollbar(self.detail_frame, orient="vertical", command=self.details.yview)
        scroll.grid(row=1, column=2, sticky="ns")
        self.details.configure(yscrollcommand=scroll.set)
        self.detail_frame.grid_remove()
        footer = ttk.Frame(outer)
        footer.grid(row=7, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(footer, textvariable=self.status, style="Muted.TLabel")
        self.status_label.grid(row=0, column=0, sticky="w")
        self.verification_label = ttk.Label(footer, text="Verification Required", style="Muted.TLabel", cursor="hand2")
        self.verification_label.grid(row=0, column=1, sticky="e")
        Tooltip(self.verification_label, lambda: "Verification Required. BOM quantity basis, units, assembly configurations and stock availability remain unconfirmed. Results are estimates, not production approval.")
        self.export_feedback = ttk.Frame(outer, style="Card.TFrame", padding=8)
        self.export_feedback.grid(row=8, sticky="ew", pady=(6, 0))
        self.export_feedback.columnconfigure(0, weight=1)
        self.export_feedback_label = ttk.Label(self.export_feedback, style="CardMuted.TLabel", cursor="hand2")
        self.export_feedback_label.grid(row=0, column=0, sticky="ew")
        Tooltip(self.export_feedback_label, lambda: self.export_path.get())
        self.export_feedback_label.bind("<Button-1>", lambda _e: self.file_popup("Exported report", self.export_path.get()))
        ttk.Button(self.export_feedback, text="Open Folder", command=self.open_export_folder).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(self.export_feedback, text="Dismiss", command=self.export_feedback.grid_remove).grid(row=0, column=2, padx=(8, 0))
        self.export_feedback.grid_remove()
        self.root.bind("<Configure>", self._resize, add="+")
        def bind_overview_scroll(widget):
            widget.bind("<MouseWheel>", lambda e: self.overview_canvas.yview_scroll(-int(e.delta / 120), "units"), add="+")
            for child in widget.winfo_children():
                bind_overview_scroll(child)
        bind_overview_scroll(self.overview)
        self._schedule_resize()

    def _schedule_resize(self):
        if self._resize_job is None and not self.closed:
            def run():
                self._resize_job = None
                self._resize()
            self._resize_job = self.root.after_idle(run)

    def _resize(self, event=None):
        if event is not None and event.widget != self.root:
            return
        if getattr(self, "_resizing", False):
            return
        self._resizing = True
        try:
            self.root.update_idletasks()
            # Reserve the table and pinned actions; only the title/file overview can scroll.
            other = self.outer.winfo_reqheight() - self.overview.winfo_reqheight() - self.tree.winfo_reqheight()
            available = max(90, self.root.winfo_height() - other - 130)
            natural = self.overview_content.winfo_reqheight()
            target = min(natural, available)
            if int(self.overview_canvas.cget("height")) != target:
                self.overview_canvas.configure(height=target)
                self._schedule_resize()
            if natural > available:
                self.overview_scroll.grid()
            else:
                self.overview_scroll.grid_remove()
                self.overview_canvas.yview_moveto(0)
        finally:
            self._resizing = False
        width = max(100, self.root.winfo_width() - 190)
        self.notice_label.configure(wraplength=width)
        if self.export_path.get():
            self.export_feedback_label.configure(text=ellipsize(self.export_path.get(), width - 180, ("Segoe UI", 9), middle=True))

    def _file_details(self, role):
        path = (self.stock_path if role == "stock" else self.bom_path).get()
        book = self.stock_book if role == "stock" else self.bom_book
        return path + "\n" + self.file_status[role].get() + ("\n" + "\n".join(book.notes) if book else "")

    def file_popup(self, title, text):
        window = tk.Toplevel(self.root)
        window.title(title)
        window.transient(self.root)
        window.geometry("760x280")
        box = tk.Text(window, wrap="word", font=("Segoe UI", 10), padx=16, pady=12)
        box.pack(side="left", fill="both", expand=True)
        box.insert("1.0", text)
        box.configure(state="disabled")
        scroll = ttk.Scrollbar(window, command=box.yview)
        scroll.pack(side="right", fill="y")
        box.configure(yscrollcommand=scroll.set)
        return window

    def file_details(self, role):
        self.file_popup("Storage File Details" if role == "stock" else "BOM File Details", self._file_details(role))

    def _refresh_file_card(self, role):
        view = self.file_view[role]
        path = (self.stock_path if role == "stock" else self.bom_path).get()
        book = self.stock_book if role == "stock" else self.bom_book
        width = max(40, view["card"].winfo_width() - 24)
        name_width = max(40, width - view["button"].winfo_reqwidth() - 12)
        view["name"].configure(text=ellipsize(Path(path).name if path else "Choose an Excel workbook", name_width, ("Segoe UI", 10, "bold")))
        view["path"].configure(text=ellipsize(str(Path(path).parent) if path else ".xlsx / .xlsm", width, ("Segoe UI", 9), middle=True))
        view["button"].configure(text="Change…" if path else "Browse…")
        if book:
            status = f"Loaded · Saved {clock(book.fingerprint[2] / 1e9)} · Loaded {clock(book.loaded_at)}"
        else:
            status = "Loading…" if view["loading"] else "Load failed · Click for details" if path else "Not loaded"
        view["status"].configure(text=ellipsize(status, width, ("Segoe UI", 9)))
        if view["locks"] and book:
            view["warning"].configure(text="File may currently be open in Excel")
            view["warning"].grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
        else:
            view["warning"].grid_remove()
        self._schedule_resize()

    def hide_details(self):
        self.detail_frame.grid_remove()
        if self.row_detail_window is not None:
            if self.row_detail_window.winfo_exists():
                self.row_detail_window.destroy()
            self.row_detail_window = None
        self._schedule_resize()

    def open_export_folder(self):
        if self.export_path.get():
            try:
                os.startfile(str(Path(self.export_path.get()).parent))
            except OSError as exc:
                messagebox.showerror("Open Folder failed", str(exc), parent=self.root)

    def _detail_text(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def invalidate(self):
        self.result = None
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        self.summary.set("输入或文件选择已变化，需重新 CHECK · Verification Required")
        self._detail_text("选择结果行查看来源和原始值。")
        self.hide_details()
        for value in self.summary_counts.values():
            value.set("—")

    def _set_busy(self, busy):
        self.busy = busy
        for control, state in self.controls:
            control.configure(state="disabled" if busy else state)
        self.root.configure(cursor="watch" if busy else "")

    def _start(self, action, callback, label):
        if self.busy:
            return
        self.invalidate()
        self._set_busy(True)
        self.status.set("Checking materials…" if label == "检查材料" else "Loading files…")
        def worker():
            started = time.perf_counter()
            try:
                data = action()
                self.events.put((callback, data, None, time.perf_counter() - started))
            except Exception as exc:
                self.events.put((callback, None, exc, time.perf_counter() - started))
        threading.Thread(target=worker, daemon=True, name="m0-excel-reader").start()

    def _poll(self):
        if self.closed:
            return
        try:
            callback, data, error, elapsed = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self._set_busy(False)
            if error is not None:
                # Unexpected failure of the whole action: nothing loaded can be trusted, so clear everything.
                for role in ROLES:
                    self.file_view[role]["loading"] = False
                    self._clear_role(role)
                self.invalidate()
                self.status.set("Read / check failed · Reload Files to retry.")
                messagebox.showerror("读取/检查失败", str(error), parent=self.root)
            else:
                # A callback returns text when a file failed; it has already cleared only that file.
                problem = callback(data)
                if problem:
                    self.invalidate()
                    self.status.set("Read / check failed · Click the file card for details.")
                    messagebox.showerror("读取/检查失败", problem, parent=self.root)
                else:
                    if self.result:
                        self.status.set(f"Checked {len(self.result.rows)} materials in {elapsed:.2f}s")
                    else:
                        materials = sum(len(s.materials) for s in self.stock_book.stock_sheets) if self.stock_book else 0
                        products = len(self.bom_book.products) if self.bom_book else 0
                        self.status.set(f"Loaded {materials} storage rows · {products} products")
        self.poll_id = self.root.after(50, self._poll)

    def browse(self, role):
        path = filedialog.askopenfilename(parent=self.root, title="选择库存 Excel" if role == "stock" else "选择 BOM Excel",
                                         filetypes=[("Excel (.xlsx / .xlsm)", "*.xlsx *.xlsm"), ("All files", "*.*")])
        if path:
            self.load_file(role, path)

    def _clear_role(self, role):
        if role == "stock":
            self.stock_book = None
            self.stock_name.set("")
            self.stock_combo.configure(values=())
            self.stock_sheet_frame.grid_remove()
        else:
            self.bom_book = None
            self.product_text.set("")
            self.product_combo.configure(values=())
        self._refresh_file_card(role)

    def _read(self, role, path, force=False):
        """Worker thread. One file's outcome, so a failure cannot discard the other file."""
        parsed = self.service.cache.parse_count
        try:
            book, locks = self.service.load(path, role, force=force, cancelled=self.cancelled)
            return book, locks, None, self.service.cache.parse_count == parsed
        except Exception as exc:
            return None, (), exc, False

    def _apply(self, role, outcome, previous=""):
        """UI thread. Show one file's outcome and status; returns error text if it failed."""
        book, locks, error, reused = outcome
        self.file_view[role]["loading"] = False
        label, now = self.file_labels[role], clock(time.time())
        path = self.stock_path.get() if role == "stock" else self.bom_path.get()
        if error is not None:
            self._clear_role(role)
            self.file_status[role].set(f"✖ {Path(path).name} · 未加载（{now} 读取失败）。修正后点击 Reload Files 重试；另一文件不受影响。")
            label.configure(foreground="#b00020")
            self.file_view[role]["locks"] = ()
            self._refresh_file_card(role)
            return f"{ROLES[role]}：{error}"
        (self._stock_loaded if role == "stock" else self._bom_loaded)(book, previous)
        text = (f"{Path(book.path).name} · 文件保存时间 {clock(book.fingerprint[2] / 1e9)} · 成功加载 {clock(book.loaded_at)} · "
                f"{now} 刷新检查：" + ("文件未变化，沿用已加载数据" if reused else "已从文件重新读取"))
        if locks:
            text += (f"\n⚠ 发现 Excel 占用标记文件 {'、'.join(locks)}：此工作簿正在或曾在 Excel 中打开。"
                     "本工具只显示最后一次保存的内容；该标记不能证明存在未保存的修改。")
        self.file_status[role].set(text)
        label.configure(foreground=MUTED)
        self.file_view[role]["locks"] = locks
        self._refresh_file_card(role)
        return None

    def _loaded(self, outcomes, previous=None):
        previous = previous or {}
        errors = [self._apply(role, outcomes[role], previous.get(role, "")) for role in ROLES if role in outcomes]
        return "\n\n".join(e for e in errors if e)

    def load_file(self, role, path):
        if self.busy:
            return
        (self.stock_path if role == "stock" else self.bom_path).set(path)
        self.file_view[role]["loading"] = True
        self._clear_role(role)
        self._start(lambda: {role: self._read(role, path)}, self._loaded, "读取所选文件")

    def _stock_loaded(self, book, previous=""):
        self.stock_book = book
        names = tuple(s.name for s in book.stock_sheets)
        self.stock_combo.configure(values=names)
        if len(names) > 1:
            self.stock_sheet_frame.grid()
        else:
            self.stock_sheet_frame.grid_remove()
        self.stock_name.set(previous if previous in names else names[0] if len(names) == 1 else "")
        self._detail_text("库存表头识别：" + "; ".join(f"{s.name!r} 第{s.header_row}行 / {len(s.materials)}条材料" for s in book.stock_sheets)
                          + "\n" + "\n".join(book.notes))

    def _bom_loaded(self, book, previous=""):
        self.bom_book = book
        self.product_combo.configure(values=tuple(p.display_name for p in book.products))
        selected = next((p for p in book.products if p.sheet_name == previous), None)
        self.product_text.set(selected.display_name if selected else "")
        self._detail_text(f"识别 {len(book.products)} 个 Product ID（来自含材料的 BOM Sheet）。请输入搜索并选择其中一个。\n" + "\n".join(book.notes))

    def _search(self, _event=None, reset=False):
        if self.bom_book is not None:
            products = self.bom_book.products if reset or select_product(self.bom_book.products, self.product_text.get()) else search_products(self.bom_book.products, self.product_text.get())
            self.product_combo.configure(values=tuple(p.display_name for p in products))

    def _pick(self, _event=None):
        """Enter in the Product ID box: take the only candidate, or open the list when there are several."""
        if self.bom_book is None or select_product(self.bom_book.products, self.product_text.get()):
            return
        matches = search_products(self.bom_book.products, self.product_text.get())
        self.product_combo.configure(values=tuple(p.display_name for p in matches))
        if len(matches) == 1:
            self.product_text.set(matches[0].display_name)
            self.product_combo.icursor("end")
        elif matches:
            self.product_combo.event_generate("<Down>")

    def reload_files(self):
        paths = {"stock": self.stock_path.get(), "bom": self.bom_path.get()}
        product = select_product(self.bom_book.products, self.product_text.get()) if self.bom_book else None
        previous = {"stock": self.stock_name.get(), "bom": product.sheet_name if product else ""}
        if not any(paths.values()):
            messagebox.showerror("未选择文件", "请先 Browse 选择文件。", parent=self.root)
            return
        self._start(lambda: {role: self._read(role, path, force=True) for role, path in paths.items() if path},
                    lambda outcomes: self._loaded(outcomes, previous), "强制重新读取")

    def check(self):
        if self.busy:
            return
        try:
            production_quantity(self.quantity_text.get())
            if self.stock_book is None or self.bom_book is None:
                raise ValueError("请先成功读取库存与 BOM 文件。未加载的文件可在修正后点击 Reload Files 重试。")
            product = select_product(self.bom_book.products, self.product_text.get())
            if product is None:
                matches = search_products(self.bom_book.products, self.product_text.get()) if self.product_text.get().strip() else ()
                self.product_combo.configure(values=tuple(p.display_name for p in matches or self.bom_book.products))
                raise ValueError(f"“{self.product_text.get()}” 不是一个已选定的 Product ID。" +
                                 (f"有 {len(matches)} 个匹配项，请从下拉列表中选择一个。" if matches else
                                  "BOM 中没有匹配的 Product ID；请从下拉列表选择实际存在的产品。") +
                                 "部分名称、虚构名称或歧义名称不能检查。")
            if not any(s.name == self.stock_name.get() for s in self.stock_book.stock_sheets):
                raise ValueError("请选择实际库存 Sheet；多个库存 Sheet 不会自动合并。")
        except ValueError as exc:
            self.invalidate()
            messagebox.showerror("输入待修正", str(exc), parent=self.root)
            return
        paths = {"stock": self.stock_path.get(), "bom": self.bom_path.get()}
        selected = {"stock": self.stock_name.get(), "bom": product.sheet_name}
        count = production_quantity(self.quantity_text.get())
        def action():
            outcomes = {role: self._read(role, path) for role, path in paths.items()}
            stock, bom = outcomes["stock"][0], outcomes["bom"][0]
            if stock is None or bom is None:
                return outcomes, None
            sheet = self.service.find_stock_sheet(stock, selected["stock"])
            chosen = self.service.find_product(bom, selected["bom"])
            if sheet is None:
                outcomes["stock"] = (None, (), DataReadError(SHEET_GONE), False)
            if chosen is None:
                outcomes["bom"] = (None, (), DataReadError(SHEET_GONE), False)
            return outcomes, check_materials(chosen, sheet, count) if sheet and chosen else None
        def done(data):
            outcomes, result = data
            problem = self._loaded(outcomes, selected)
            if result is not None and not problem:
                self.render_result(result)
            return problem
        self._start(action, done, "检查材料")

    def render_result(self, result):
        self.invalidate()
        self.result = result
        self.filter_category.set("All")
        self._fill_tree()
        self.summary.set(
            f"Product ID: {result.product.display_name}    Production Quantity: {result.production_count}    "
            f"Total Material Rows: {len(result.rows)}\n"
            f"SHORTAGE: {result.category_count(SHORTAGE)}    EXCEPTION: {result.category_count(EXCEPTION)}    "
            f"ENOUGH: {result.category_count(ENOUGH)}    Total calculated shortage rows: {result.calculated_shortage_rows}"
            "（含按库存 0 试算的 EXCEPTION 行）\n"
            f"ESTIMATED / UNVERIFIED · Verification Required：{ROW_CAVEAT}")
        self.summary_counts["total"].set(str(len(result.rows)))
        for category in (SHORTAGE, EXCEPTION, ENOUGH):
            self.summary_counts[category].set(str(result.category_count(category)))
        self._detail_text("")
        self.hide_details()

    def _stock_text(self, r):
        if r.stock_used is None:
            return "—"
        return display(r.stock_used) + (" (assumed)" if r.stock_assumed else "")

    def _fill_tree(self):
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        self.hide_details()
        if self.result is None:
            return
        for i in self.result.sorted_order:  # SHORTAGE, EXCEPTION, ENOUGH; Material ID ascending
            r = self.result.rows[i]
            if self.filter_category.get() != "All" and r.category != self.filter_category.get():
                continue
            values = (display(r.bom.code), display(r.bom.description), display(r.required), self._stock_text(r),
                      display(r.shortage), r.category, r.data_status,
                      " | ".join(display(s.rack) for s in r.stock) or "—", " | ".join(display(s.level) for s in r.stock) or "—")
            # iid is the index into result.rows (BOM order), so details work whatever the display order.
            self.tree.insert("", "end", iid=str(i), values=values, tags=(r.category,))

    def show_details(self, _event=None):
        selected = self.tree.selection()
        if not selected or self.result is None:
            self.hide_details()
            return
        r = self.result.rows[int(selected[0])]
        lines = [f"Material ID: {display(r.bom.code)} · Description: {display(r.bom.description)}",
                 f"{r.category} · {r.data_status} · Required={display(r.required)} · Stock={self._stock_text(r)} · Shortage={display(r.shortage)}"
                 f" · BOM QTY 原值={display(r.bom.quantity)}",
                 f"BOM: {r.bom.source.path} | Sheet={r.bom.source.sheet!r} | 行={r.bom.source.row}",
                 f"装配段（未确认配置）: {r.bom.section or '未标明'}"]
        lines.extend(f"STOCK: {s.source.path} | Sheet={s.source.sheet!r} | 行={s.source.row} | 原始数量={display(s.quantity)} | 位置={s.rack}/{s.level}" for s in r.stock)
        lines.append("说明: " + (" ".join(r.issues) or "无逐行问题") + " " + ROW_CAVEAT)
        self.hide_details()
        self._detail_text("\n".join(lines))
        self.detail_frame.grid()
        self._schedule_resize()
        if self.root.winfo_viewable():
            self._resize()
            self.root.update_idletasks()
            if self.tree.winfo_height() < 96 or self.detail_frame.winfo_rooty() + self.detail_frame.winfo_height() > self.root.winfo_rooty() + self.root.winfo_height() - 24:
                # A compact window uses a nonmodal detail window instead of squeezing the table away.
                self.hide_details()
                self.row_detail_window = self.file_popup("Selected Material · Source & Data", "\n".join(lines))

    def export(self):
        if self.result is None:
            messagebox.showerror("没有可导出的结果", "请先 CHECK。输入或文件变化后旧结果不会被导出。", parent=self.root)
            return
        name = default_filename(self.result.product.display_name, self.result.production_count, datetime.now())
        # No overwrite prompt: an existing file is never replaced, a numbered name is used instead.
        path = filedialog.asksaveasfilename(parent=self.root, title="导出为新的 Excel 报告", defaultextension=".xlsx",
                                           filetypes=[("Excel (.xlsx)", "*.xlsx")], initialfile=name, confirmoverwrite=False)
        if path:
            self.write_export(path)

    def write_export(self, path):
        """Save the current result as a new .xlsx. Returns the path written, or None if refused or failed."""
        if self.result is None or self.stock_book is None or self.bom_book is None:
            return None
        try:
            written = save_report(path, self.result, self.stock_book, self.bom_book)
        except ReportError as exc:
            messagebox.showerror("导出失败", str(exc), parent=self.root)
            return None
        except OSError as exc:
            messagebox.showerror("导出失败", f"无法写入 {path}\n{exc}", parent=self.root)
            return None
        self.export_path.set(str(written))
        self.hide_details()
        self.export_feedback.grid()
        self._resize()
        self.status.set("Report exported successfully.")
        return written

    def close(self):
        self.closed = True
        self.cancelled.set()
        self.root.after_cancel(self.poll_id)
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
        self.root.destroy()
