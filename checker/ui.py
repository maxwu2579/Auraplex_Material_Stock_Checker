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
from . import binding
from .queries import overall_state, overall_times, status_text, with_known_failures
from .sync import (CHECKING, CLOUD_NOT_VERIFIED, DATABASE_UNAVAILABLE, LOCAL_VERIFIED, NOT_SYNCED, SOURCE_CHANGED,
                   SOURCE_UNAVAILABLE, STATUS_UNKNOWN, SYNC_FAILED, USING_PREVIOUS)
from .report import ReportError, default_filename, save_verified_report
from .service import CheckerService
from .presentation import BG, INK, MUTED, BLUE, RED, AMBER, Tooltip, ellipsize, work_area


ROLES = {"stock": "Storage / 库存 Excel", "bom": "BOM Excel"}
ROW_COLOURS = {SHORTAGE: RED, EXCEPTION: AMBER}  # soft red/yellow; ENOUGH is explicitly white
SHEET_GONE = "源文件更新后，所选 Sheet 不再存在/不符合表头。请 Reload Files 并重新选择。"
ROLE_NAMES = {"stock": "Storage", "bom": "BOM"}
NOTICE_TEXT = "Results are calculated from the selected BOM and current saved Storage data."
SHORT_TIME = "%Y-%m-%d %H:%M"  # compact panel; the details popup shows seconds
JOB_STATUS = {"检查材料": "Checking materials…", "启动检查": "Checking Excel sources…", "刷新 Excel": "Refreshing Excel…"}
LOCAL_COPY_NOTE = ("Local File Checked = at the Last Verified time, the database matched one version of the Excel file "
                   "on this computer. The file can change at any moment afterwards, and Google Drive may not have "
                   "downloaded newer cloud changes yet: the cloud copy is never checked (Cloud Not Verified).")
UNKNOWN_NOTE = ("The synchronisation status could not be read from the database, so no status is shown as current. "
                "Data already stored in the database is not deleted.")


def clock(seconds):
    return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M:%S")


def local_time(moment, pattern="%Y-%m-%d %H:%M:%S"):
    return moment.astimezone().strftime(pattern) if moment else "—"


class CheckerApp:
    def __init__(self, root: tk.Tk, inventory=None, settings=None, inventory_error=None):
        """inventory: an InventorySync (local SQLite mirror); settings: remembered file paths. Both optional:
        without them the checker behaves exactly as v1.0.0 and touches no local data."""
        self.root = root
        self.service = CheckerService()
        self.inventory, self.settings, self.inventory_error = inventory, settings, inventory_error
        self.inventory_events = queue.Queue()
        self.inventory_roles = {}  # role -> RoleFreshness, from the database
        self.inventory_read_error = None  # set when the last status read failed: nothing is shown as current
        self.sync_active = {}      # role -> CHECKING / SYNCING while a check is running
        self.job = 0               # id of the newest background job; events of any other job are stale
        self.sync_failures = {}    # role -> failed SyncResult seen by this program; beats older SQLite records
        self.stock_book = self.bom_book = self.result = None
        self.result_binding = None # binding.SourceBinding of the shown result: which source versions it belongs to
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
        if self.inventory is not None or self.settings is not None:
            self._startup()

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
        self.notice_label = ttk.Label(notice, text=NOTICE_TEXT, style="Muted.TLabel")
        self.notice_label.grid(row=0, column=0, sticky="w")
        Tooltip(self.notice_label, lambda: (NOTICE_TEXT + "\n" if self.db_panel is not None else "") +
                "Review yellow Exception rows before use.\nVerification Required · " + ROW_CAVEAT)
        self.reload_button = ttk.Button(notice, text="Reload Files", command=self.reload_files)
        self.reload_button.grid(row=0, column=1, padx=(8, 0))
        self.controls.append((self.reload_button, "normal"))
        self.db_panel = None
        if self.inventory is not None or self.inventory_error is not None:
            self._build_inventory_panel(notice)
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
        # Which source versions the shown result belongs to: "Local Sources Verified …" or OUTDATED / RECHECK REQUIRED.
        self.result_state_label = ttk.Label(toolbar, text="", style="CardMuted.TLabel", cursor="hand2")
        self.result_state_label.pack(side="right", padx=(8, 2))
        Tooltip(self.result_state_label, lambda: self.result_binding.describe() if self.result_binding else "")
        self.result_state_label.bind("<Button-1>", lambda _e: self.result_binding and
                                     self.file_popup("CHECK result · source versions", self.result_binding.describe()))
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

    def _build_inventory_panel(self, notice):
        """Compact two-line 'Inventory Database' section in the notice row, beside Reload Files: always visible
        (not in the scrolling file overview) and nearly free in height, because the row is as tall as its buttons."""
        self.db_status = tk.StringVar()
        self.db_times = tk.StringVar()
        self.db_role_text = {role: tk.StringVar() for role in ROLES}
        panel = self.db_panel = ttk.Frame(notice)
        panel.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        panel.columnconfigure((0, 1), weight=1, uniform="db")
        heading = ttk.Frame(panel)
        heading.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.db_title_label = ttk.Label(heading, text="Inventory Database", style="Muted.TLabel")
        self.db_title_label.pack(side="left")
        # The status and the cloud limitation are never shortened or hidden, in any state; the times label gives way,
        # then the title. Nothing here checks the Google Drive cloud copy, so "Cloud Not Verified" is permanent.
        self.db_status_label = ttk.Label(heading, textvariable=self.db_status, font=("Segoe UI", 9, "bold"), cursor="hand2")
        self.db_status_label.pack(side="left", padx=(10, 0))
        self.db_cloud_label = ttk.Label(heading, text=CLOUD_NOT_VERIFIED, style="Muted.TLabel", foreground="#95641a",
                                        cursor="hand2")
        self.db_cloud_label.pack(side="left", padx=(12, 0))
        self.db_times_label = ttk.Label(heading, style="Muted.TLabel", cursor="hand2")
        self.db_times_label.pack(side="left", padx=(16, 0))
        self.db_times_short = ""  # compact form of db_times for narrow windows
        self.refresh_button = ttk.Button(notice, text="Refresh Excel", command=self.refresh_excel)
        self.refresh_button.grid(row=0, column=1, rowspan=2, sticky="e", padx=(8, 0))
        self.reload_button.grid_configure(column=2, rowspan=2)
        self.controls.append((self.refresh_button, "normal"))
        self.db_role_labels = {}
        for col, role in enumerate(ROLES):
            # Full text in db_role_text (details, tests); the label shows it shortened to fit its column.
            label = ttk.Label(panel, style="Muted.TLabel", cursor="hand2")
            label.grid(row=1, column=col, sticky="ew", pady=(2, 0), padx=(0, 12))
            self.db_role_labels[role] = label
        panel.bind("<Configure>", lambda _e: self._fit_inventory_labels())
        for label in (self.db_status_label, self.db_cloud_label, self.db_times_label, *self.db_role_labels.values()):
            Tooltip(label, self._inventory_details)
            label.bind("<Button-1>", lambda _e: self.file_popup("Inventory Database", self._inventory_details()))
        self._render_inventory()

    def _render_inventory(self):
        """UI thread only. Shows database state; previously synchronised data is never shown as freshly synchronised."""
        if self.db_panel is None:
            return
        if self.inventory is None:
            self.db_overall = DATABASE_UNAVAILABLE
            self.db_status.set(f"Status: {DATABASE_UNAVAILABLE}")
            self.db_times.set("Excel checks still work; nothing is stored locally. Click for details.")
            self.db_times_short = "Click for details."
            for role in ROLES:
                self.db_role_text[role].set(f"{ROLE_NAMES[role]}: —")
            self._fit_inventory_labels()
            return
        roles, active = self.inventory_roles, self.sync_active
        if self.inventory_read_error is not None and not active:
            # Fail closed: nothing read before the failure is shown as the current status or time.
            overall, roles = STATUS_UNKNOWN, {}
        elif roles:
            overall = overall_state(roles, active)
        else:
            overall = CHECKING if active else NOT_SYNCED
        self.db_overall = overall
        self.db_status.set(f"Status: {overall}")  # "Cloud Not Verified" is the separate, permanent label beside it
        self.db_status_label.configure(foreground=self._state_colour(overall))
        checked, success = overall_times(roles) if roles else (None, None)
        # A verification time is current only in the verified state; otherwise it is explicitly historical.
        verified = "Last Verified" if overall == LOCAL_VERIFIED or success is None else "Previously Verified"
        self.db_times.set(f"{verified}: {local_time(success, SHORT_TIME)}  ·  Last Checked: {local_time(checked, SHORT_TIME)}")
        self.db_times_short = f"{verified.removeprefix('Last ')} {local_time(success, '%m-%d %H:%M')}"
        for role in ROLES:
            info = roles.get(role)
            state = active.get(role) or (info.label if info else STATUS_UNKNOWN if overall == STATUS_UNKNOWN else NOT_SYNCED)
            text = f"{ROLE_NAMES[role]}: {state}"
            if info and info.source_modified:
                text += f"  ·  Source File Modified {local_time(info.source_modified, SHORT_TIME)}"
            self.db_role_text[role].set(text)
            self.db_role_labels[role].configure(foreground=self._state_colour(state))
        self._fit_inventory_labels()

    def _fit_inventory_labels(self):
        panel = self.db_panel
        column = (panel.winfo_width() - 24) // 2
        for role, label in self.db_role_labels.items():
            text = self.db_role_text[role].get()
            label.configure(text=ellipsize(text, column, ("Segoe UI", 9)) if column > 60 else text)
        # The status and "Cloud Not Verified" are never shortened. The times show in full, else in compact form; when
        # even that does not fit, the "Inventory Database" title gives way before the verification time does.
        face = tkfont.Font(font=("Segoe UI", 9))
        room = (panel.winfo_width() - tkfont.Font(font=("Segoe UI", 9, "bold")).measure(self.db_status.get())
                - face.measure(self.db_cloud_label.cget("text")) - 44)
        title = face.measure(self.db_title_label.cget("text")) + 10
        full, short = self.db_times.get(), self.db_times_short or self.db_times.get()
        if panel.winfo_width() <= 1 or face.measure(full) <= room - title:
            show_title, text = True, full  # (not laid out yet: the next <Configure> fits it)
        elif face.measure(short) <= room - title:
            show_title, text = True, short
        else:
            show_title, text = False, ellipsize(short, max(room, 0), ("Segoe UI", 9))
        if show_title != bool(self.db_title_label.winfo_manager()):
            if show_title:
                self.db_title_label.pack(side="left", before=self.db_status_label)
            else:
                self.db_title_label.pack_forget()
        self.db_status_label.pack_configure(padx=(10 if show_title else 0, 0))
        self.db_times_label.configure(text=text)

    @staticmethod
    def _state_colour(state):
        if state.startswith((SYNC_FAILED, SOURCE_UNAVAILABLE, STATUS_UNKNOWN)):
            return "#b00020"
        if state.startswith((USING_PREVIOUS, SOURCE_CHANGED)):
            return "#95641a"
        return INK if state.startswith(LOCAL_VERIFIED) else MUTED

    def _inventory_details(self):
        if self.inventory is None:
            return "Inventory database unavailable.\n" + (self.inventory_error or "")
        lines = [f"Database: {self.inventory.db_path}", LOCAL_COPY_NOTE,
                 "Last Verified = the last time the database matched the local file (imported, or checked and "
                 "unchanged). Overall time = the older of the two files.", ""]
        if self.inventory_read_error is not None and not self.sync_active:
            return "\n".join(lines + [f"Status: {STATUS_UNKNOWN}", UNKNOWN_NOTE, f"Error: {self.inventory_read_error}"])
        for role in ROLES:
            info = self.inventory_roles.get(role)
            lines.append(f"{ROLE_NAMES[role]}: {self.sync_active.get(role) or (info.label if info else NOT_SYNCED)}")
            if info:
                verified = "Last Verified" if info.state == LOCAL_VERIFIED else "Previously Verified (historical)"
                lines += [f"  Last Checked: {local_time(info.last_checked)}",
                          f"  {verified}: {local_time(info.last_success)}",
                          f"  Data in database from: {info.data_path or '— (none yet)'}",
                          f"  Source File Modified: {local_time(info.source_modified)} · imported {local_time(info.data_imported)}"]
                if info.last_error and info.state != LOCAL_VERIFIED:
                    lines.append(f"  Last error ({info.last_run_path}): {info.last_error}")
                if info.unrecorded:
                    lines.append("  This failure could not be written to the database; it is shown from this session.")
        return "\n".join(lines)

    def _show_inventory(self, report):
        """UI thread. Apply a finished sync; returns warning text for failed sources, or ''."""
        results, roles, db_error = report
        self.sync_active = {}
        # The in-memory results are authoritative for this attempt: a failure is remembered until this program
        # verifies that role again, even if it could not be written to SQLite (recorded=False) and the database
        # still holds an older success.
        for role, result in results.items():
            if result.ok:
                self.sync_failures.pop(role, None)
            else:
                self.sync_failures[role] = result
        # Fail closed: a failed status read replaces, never keeps, what was shown before.
        self.inventory_roles = with_known_failures(roles, self.sync_failures) if roles is not None else {}
        self.inventory_read_error = None if roles is not None else (db_error or "unknown error")
        self._render_inventory()
        notes = []
        for role, result in results.items():
            if result.ok:
                continue
            info = self.inventory_roles.get(role)
            if self.inventory_read_error is not None:
                kept = "无法读取数据库同步状态：不能确认此前同步的数据及其时间。数据库中已有的数据不会被删除。"
            elif info and info.has_data:
                kept = (f"数据库保留此前同步的数据（Previously Verified {local_time(info.last_success)}，历史时间），"
                        "但当前未验证，未显示为新同步。")
            else:
                kept = "数据库中没有该文件此前的数据。"
            state = (SOURCE_UNAVAILABLE if result.outcome == "UNAVAILABLE" else
                     SOURCE_CHANGED if result.changed else SYNC_FAILED)
            notes.append(f"Inventory Database · {ROLE_NAMES[role]}: {state}\n"
                         f"{result.error}\n{kept}" + ("" if result.recorded else "\n（本次失败未能写入数据库记录。）"))
        if db_error:
            notes.append(f"Inventory Database 状态读取失败：{db_error}\n"
                         f"状态显示为 {STATUS_UNKNOWN}；此前显示的状态已清除，不能视为数据库与源文件一致。")
        if notes:
            notes.append("修正后点击 Refresh Excel 重试。")
        return "\n\n".join(notes)

    def _shared_parse(self, path, role):
        """Worker thread. The sync reuses the checker's own parse of the same file version (no second parse)."""
        return self.service.cache.read(path, role, cancelled=self.cancelled)

    def _sync_sources(self, paths, trigger, job):
        """Worker thread. Synchronise the database; returns (results, freshness, error) for the UI thread.

        Freshness is read after sync_all's final re-check of the files, so it is what is displayed next."""
        progress = lambda role, state: self.inventory_events.put((job, role, state))  # never touches Tk
        results = self.inventory.sync_all(paths, trigger, parse=self._shared_parse, progress=progress)
        try:
            return results, self.inventory.freshness(), None
        except Exception as exc:
            return results, None, str(exc)

    def _remember(self, role, path):
        if self.settings is None or not path:
            return
        try:
            self.settings.remember(role, path)
        except OSError as exc:
            self.status.set(f"Could not remember the selected file for next start: {exc}")

    def _startup(self):
        """Restore remembered files, then check them against the database in the background."""
        remembered = self.settings.load() if self.settings is not None else {}
        for role, path in remembered.items():
            (self.stock_path if role == "stock" else self.bom_path).set(path)
            self.file_view[role]["loading"] = True
            self._refresh_file_card(role)
        self._start(lambda: {role: self._read(role, path) for role, path in remembered.items()}, self._loaded,
                    "启动检查", sync=(remembered, "startup"))

    def refresh_excel(self):
        """Check both sources for updates, synchronise changed files and refresh what is shown. Never writes Excel."""
        if self.busy:
            return
        if self.result is not None:
            self.check(trigger="manual")  # same Product ID, quantity and Storage sheet, recalculated from the files
        else:
            self.reload_files(force=False, trigger="manual", label="刷新 Excel")

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
            if self.db_panel is not None and self._compact_inventory(other):
                self.root.update_idletasks()
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
        if self.db_panel is None:
            self.notice_label.configure(wraplength=width)
        else:  # one line beside Refresh Excel; the full sentence is in the tooltip
            self.notice_label.configure(text=ellipsize(NOTICE_TEXT, width - self.refresh_button.winfo_reqwidth() - 8,
                                                       ("Segoe UI", 9)))
        if self.export_path.get():
            self.export_feedback_label.configure(text=ellipsize(self.export_path.get(), width - 180, ("Segoe UI", 9), middle=True))

    def _compact_inventory(self, other):
        """Short window: hide the per-file database line (still in the tooltip and details) so the table keeps its
        room. Decided from the height with the line shown, so it cannot oscillate. Returns True if it changed."""
        labels = tuple(self.db_role_labels.values())
        shown = bool(labels[0].winfo_manager())
        line = max(label.winfo_reqheight() for label in labels) + 2
        compact = self.root.winfo_height() - (other + (0 if shown else line)) - 130 < 90
        if compact != shown:
            return False
        for label in labels:
            label.grid_remove() if compact else label.grid()
        return True

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
        self.result_binding = None
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        self.summary.set("输入或文件选择已变化，需重新 CHECK · Verification Required")
        self._detail_text("选择结果行查看来源和原始值。")
        self.hide_details()
        for value in self.summary_counts.values():
            value.set("—")
        self._show_result_state()

    @property
    def result_current(self) -> bool:
        """The shown result was confirmed after calculation; export requires a new local source check."""
        return self.result is not None and self.result_binding is not None and self.result_binding.current

    def _show_result_state(self):
        if self.result is None or self.result_binding is None:
            self.result_state_label.configure(text="", foreground=MUTED, font=("Segoe UI", 9))
        elif self.result_binding.current:
            when = datetime.fromtimestamp(self.result_binding.checked_at).strftime("%H:%M:%S")
            self.result_state_label.configure(text=f"Local Sources Verified {when}", foreground="#3b715e",
                                              font=("Segoe UI", 9))
        else:
            changed = " & ".join(binding.ROLE_NAMES[r] for r in self.result_binding.changed)
            self.result_state_label.configure(text=f"{binding.OUTDATED} · {changed} changed", foreground="#b00020",
                                              font=("Segoe UI", 9, "bold"))
        if not self.busy:  # an outdated result can never be exported
            self.export_button.configure(state="normal" if self.result is None or self.result_current else "disabled")

    def _set_busy(self, busy):
        self.busy = busy
        for control, state in self.controls:
            control.configure(state="disabled" if busy else state)
        self.root.configure(cursor="watch" if busy else "")
        if not busy:
            self._show_result_state()

    def _start(self, action, callback, label, sync=None, verify=None):
        """Run action (and then the database sync, if any) on one worker thread; the result returns via _poll.

        sync = (paths by role, trigger). The sync runs after the action so it reuses the same parse of each file.
        verify(data, report, attempt) -> (data, retry): run after the sync; retry=True repeats the whole action +
        sync, at most binding.CHECK_ATTEMPTS times (a source that changed while being checked)."""
        if self.busy:
            return
        self.invalidate()
        self._set_busy(True)
        self.job += 1
        job = self.job  # events carry it: a response from an older job can never overwrite a newer status
        self.status.set(JOB_STATUS.get(label, "Loading files…"))
        sync = sync if self.inventory is not None else None
        if sync:
            self.sync_active = {role: CHECKING for role, path in sync[0].items() if path}
            self._render_inventory()
        def worker():
            started = time.perf_counter()
            for attempt in range(1, (binding.CHECK_ATTEMPTS if verify else 1) + 1):
                try:
                    data, error = action(), None
                except Exception as exc:
                    data, error = None, exc
                report = None
                if sync and not self.cancelled.is_set():
                    try:
                        report = self._sync_sources(*sync, job)
                    except Exception as exc:  # defensive: sync_role already contains source and database failures
                        report = ({}, None, f"{type(exc).__name__}: {exc}")
                if verify is None or error is not None or self.cancelled.is_set():
                    break
                data, retry = verify(data, report, attempt)
                if not retry:
                    break
            self.events.put((job, callback, data, error, time.perf_counter() - started, report, label))
        threading.Thread(target=worker, daemon=True, name="m0-excel-reader").start()

    def _poll(self):
        if self.closed:
            return
        while True:  # progress of a running sync (worker thread → queue → here, the Tk thread)
            try:
                job, role, state = self.inventory_events.get_nowait()
            except queue.Empty:
                break
            if self.busy and job == self.job:
                self.sync_active[role] = state
                self._render_inventory()
        try:
            job, callback, data, error, elapsed, report, label = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            if job != self.job:  # stale: a newer job owns the UI state
                self.poll_id = self.root.after(50, self._poll)
                return
            self._set_busy(False)
            sync_note = self._show_inventory(report) if report is not None else ""
            # Every outcome, failures included, shows the current database state (and its cloud limitation).
            db_suffix = (f" · Inventory Database: {status_text(self.db_overall)}"
                         if report is not None and self.db_panel is not None else "")
            if error is not None:
                # Unexpected failure of the whole action: nothing loaded can be trusted, so clear everything.
                for role in ROLES:
                    self.file_view[role]["loading"] = False
                    self._clear_role(role)
                self.invalidate()
                self.status.set("Read / check failed · Reload Files to retry." + db_suffix)
                messagebox.showerror("读取/检查失败", "\n\n".join(x for x in (str(error), sync_note) if x), parent=self.root)
            else:
                # A callback returns text when a file failed; it has already cleared only that file.
                problem = callback(data)
                if problem:
                    self.invalidate()
                    self.status.set("Read / check failed · Click the file card for details." + db_suffix)
                    messagebox.showerror("读取/检查失败", "\n\n".join(x for x in (problem, sync_note) if x), parent=self.root)
                else:
                    if self.result and not self.result_current:
                        status = (f"{binding.OUTDATED} · the source changed while being checked "
                                  f"({self.result_binding.attempts} attempts); export disabled. Click CHECK again.")
                    elif self.result:
                        status = f"Checked {len(self.result.rows)} materials in {elapsed:.2f}s · Local Sources Verified"
                    elif label == "启动检查" and self.stock_book is None and self.bom_book is None:
                        status = "Ready · Choose Storage and BOM files."
                    else:
                        materials = sum(len(s.materials) for s in self.stock_book.stock_sheets) if self.stock_book else 0
                        products = len(self.bom_book.products) if self.bom_book else 0
                        status = f"Loaded {materials} storage rows · {products} products"
                    self.status.set(status + db_suffix)
                    if sync_note:
                        # The Excel result is valid; only the local database copy could not be updated.
                        messagebox.showwarning("Inventory Database", sync_note, parent=self.root)
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
        self._remember(role, path)  # only a file that loaded successfully is remembered for the next start
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
        self._start(lambda: {role: self._read(role, path)}, self._loaded, "读取所选文件", sync=({role: path}, "selected"))

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

    def reload_files(self, force=True, trigger="reload", label="强制重新读取"):
        if self.busy:
            return
        paths = {"stock": self.stock_path.get(), "bom": self.bom_path.get()}
        product = select_product(self.bom_book.products, self.product_text.get()) if self.bom_book else None
        previous = {"stock": self.stock_name.get(), "bom": product.sheet_name if product else ""}
        if not any(paths.values()):
            messagebox.showerror("未选择文件", "请先 Browse 选择文件。", parent=self.root)
            return
        self._start(lambda: {role: self._read(role, path, force=force) for role, path in paths.items() if path},
                    lambda outcomes: self._loaded(outcomes, previous), label,
                    sync=({role: path for role, path in paths.items() if path}, trigger))

    def check(self, trigger="check"):
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
        def verify(data, report, attempt):
            """Worker thread, after the sync: does the result belong to the versions confirmed after it?"""
            outcomes, result = data
            if result is None:
                return (outcomes, None, None), False
            bound = binding.bind({role: outcomes[role][0] for role in ROLES}, report[0] if report else {}, attempt)
            return (outcomes, result, bound), not bound.current  # changed: repeat read, calculation and sync
        def done(data):
            outcomes, result, bound = data if len(data) == 3 else (*data, None)
            problem = self._loaded(outcomes, selected)
            if result is not None and not problem:
                self.render_result(result, bound)
            return problem
        self._start(action, done, "检查材料", sync=(paths, trigger), verify=verify)

    def render_result(self, result, bound=None):
        """bound: the binding.SourceBinding of the calculation. Without a current binding the result is shown as
        not verified and cannot be exported."""
        self.invalidate()
        self.result, self.result_binding = result, bound
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
        if bound is not None and not bound.current:
            self.summary.set(f"{binding.OUTDATED}\n" + self.summary.get())
        self._detail_text("")
        self.hide_details()
        self._show_result_state()

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
        if self.busy:
            return
        if self.result is None:
            messagebox.showerror("没有可导出的结果", "请先 CHECK。输入或文件变化后旧结果不会被导出。", parent=self.root)
            return
        if not self._verify_export_sources():
            return
        result, bound, job = self.result, self.result_binding, self.job
        name = default_filename(self.result.product.display_name, self.result.production_count, datetime.now())
        # No overwrite prompt: an existing file is never replaced, a numbered name is used instead.
        path = filedialog.asksaveasfilename(parent=self.root, title="导出为新的 Excel 报告", defaultextension=".xlsx",
                                           filetypes=[("Excel (.xlsx)", "*.xlsx")], initialfile=name, confirmoverwrite=False)
        if path:
            if self.result is not result or self.result_binding is not bound or self.job != job:
                messagebox.showerror("结果已变化", "选择导出位置期间 CHECK 结果已变化，请重新发起导出。", parent=self.root)
                return
            self.write_export(path)

    def _refuse_outdated_export(self, detail=""):
        messagebox.showerror(binding.OUTDATED,
                             "此结果不能确认属于当前的本机 Storage / BOM 文件版本（源文件已变化或无法复核），不能导出为有效报告。"
                             "请重新 CHECK。" + ("\n" + detail if detail else ""), parent=self.root)

    def _export_sources(self):
        return {"stock": self.stock_path.get(), "bom": self.bom_path.get()}

    def _export_verification_failed(self, exc):
        self.result_binding = exc.binding
        self._show_result_state()
        self.export_button.configure(state="disabled")
        self.export_feedback.grid_remove()
        if not self.summary.get().startswith(binding.OUTDATED):
            self.summary.set(binding.OUTDATED + "\n" + self.summary.get())
        detail = "\n".join(part for part in (str(exc), getattr(exc, "cleanup_warning", "")) if part)
        status_detail = detail.replace("\n", " · ")
        self.status.set(f"{binding.OUTDATED} · {status_detail} · {CLOUD_NOT_VERIFIED}")
        self._refuse_outdated_export(detail)

    def _verify_export_sources(self):
        if not self.result_current:
            self._refuse_outdated_export()
            return False
        try:
            binding.verify_export(self.result_binding, self._export_sources())
        except binding.ExportVerificationError as exc:
            self._export_verification_failed(exc)
            return False
        return True

    def write_export(self, path):
        """Save the current result as a new .xlsx. Returns the path written, or None if refused or failed."""
        if self.busy or self.result is None or self.stock_book is None or self.bom_book is None:
            return None
        if not self.result_current:
            self._refuse_outdated_export()
            return None
        try:
            written = save_verified_report(path, self.result, self.stock_book, self.bom_book,
                                           self.result_binding, self._export_sources())
        except binding.ExportVerificationError as exc:
            self._export_verification_failed(exc)
            return None
        except (ReportError, OSError) as exc:
            detail = "\n".join(part for part in (str(exc), getattr(exc, "cleanup_warning", "")) if part)
            if isinstance(exc, OSError):
                detail = f"无法写入 {path}\n{detail}"
            messagebox.showerror("导出失败", detail, parent=self.root)
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
