from __future__ import annotations

from datetime import datetime
from dataclasses import replace
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
from . import alerts, binding, cached, daily, i18n, retention, upgrade
from .queries import overall_state, overall_times, with_known_failures
from .sync import (CHECKING, CLOUD_NOT_VERIFIED, DATABASE_UNAVAILABLE, LOCAL_VERIFIED, NOT_SYNCED, SOURCE_CHANGED,
                   SOURCE_UNAVAILABLE, STATUS_UNKNOWN, SYNC_FAILED, USING_PREVIOUS)
from .report import ReportError, default_filename, save_verified_report
from .service import CheckerService
from .history_ui import HistoryWindow
from .analytics_ui import AnalyticsWindow
from .alerts_ui import AlertsWindow
from .daily_ui import DailySummaryWindow
from .assistant_language import tr as tr_assistant
from .assistant_ui import AssistantLauncher
from .home_ui import HomePage
from .presentation import BG, INK, MUTED, BLUE, RED, AMBER, Tooltip, ellipsize, work_area


ROLES = {"stock": "Storage / 库存 Excel", "bom": "BOM Excel"}
ROW_COLOURS = {SHORTAGE: RED, EXCEPTION: AMBER}  # soft red/yellow; ENOUGH is explicitly white
SHEET_GONE = "源文件更新后，所选 Sheet 不再存在/不符合表头。请 Reload Files 并重新选择。"
ROLE_NAMES = {"stock": "Storage", "bom": "BOM"}
NOTICE_TEXT = "Results are calculated from the selected BOM and current saved Storage data."
SHORT_TIME = "%Y-%m-%d %H:%M"  # compact panel; the details popup shows seconds
# Job label -> status message key (checker.i18n); any other job shows "Loading files…".
JOB_STATUS = {"检查材料": "st_checking_materials", "启动检查": "st_checking_sources", "刷新 Excel": "st_refreshing",
              "预览历史清理": "st_cleanup_preview", "清理历史数据": "st_cleanup",
              "预览数据库升级": "st_upgrade_preview", "升级数据库": "st_upgrade"}
MAINTENANCE_JOBS = ("预览历史清理", "清理历史数据", "预览数据库升级", "升级数据库")
LOCAL_COPY_NOTE = ("Local File Checked = at the Last Verified time, the database matched one version of the Excel file "
                   "on this computer. The file can change at any moment afterwards, and Google Drive may not have "
                   "downloaded newer cloud changes yet: the cloud copy is never checked (Cloud Not Verified).")
UNKNOWN_NOTE = ("The synchronisation status could not be read from the database, so no status is shown as current. "
                "Data already stored in the database is not deleted.")
# B1 shell: light-blue sidebar, white top bar and cards. Glyphs from Segoe MDL2 Assets (Windows 10/11).
SIDE_BG, SIDE_INK, SIDE_WIDE, SIDE_SLIM = "#dbeafa", "#16406b", 212, 60
ICON_FONT, GLYPH_COLLAPSE, GLYPH_EXPAND = "Segoe MDL2 Assets", "\ue76b", "\ue76c"
NAV = (("home", "\ue80f", "nav_home"), ("check", "\ue9d5", "nav_check"), ("materials", "\ue81c", "nav_materials"),
       ("alerts", "\ue7ba", "nav_alerts"), ("daily", "\ue787", "nav_daily"), ("ai", "\ue99a", "nav_ai"),
       ("settings", "\ue713", "nav_settings"))
PAGE_TITLES = {page: key for page, _glyph, key in NAV}
TREE_COLUMNS = (("code", "col_code", 170), ("description", "col_description", 245), ("required", "col_required", 85),
                ("stock", "col_stock", 110), ("shortage", "col_shortage", 85), ("result", "col_result", 100),
                ("status", "col_status", 220), ("rack", "col_rack", 64), ("level", "col_level", 64))


class SheetGone(DataReadError):
    """The selected Sheet disappeared from the re-read file during CHECK (shown with err_sheet_gone)."""

    def __init__(self):
        super().__init__(SHEET_GONE)


class InputProblem(ValueError):
    """An input that cannot be checked; carries the structured message for the dialog."""

    def __init__(self, message):
        super().__init__(message.key)
        self.message = message


def clock(seconds):
    return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M:%S")


def local_time(moment, pattern="%Y-%m-%d %H:%M:%S"):
    return moment.astimezone().strftime(pattern) if moment else "—"


class CheckerApp:
    def __init__(self, root: tk.Tk, inventory=None, settings=None, inventory_error=None, preferences=None):
        """inventory: an InventorySync (local SQLite mirror); settings: remembered file paths. Both optional:
        without them the checker behaves exactly as v1.0.0 and touches no local data.
        preferences: an appdata.InterfacePreferences (interface language file), optional; without it English is used
        and nothing is written."""
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
        self.history_window = None   # M4A Inventory History window (read-only), at most one
        self.analytics_window = None  # M4B historical analytics, read-only and bounded
        self.assistant = None  # M4E: isolated session, no credentials/network accessed at startup
        # M3.2C stock alerts: one evaluation at a time (+1 pending), evaluated after both files verified this session.
        self.alert_gate = alerts.SessionGate()  # invalidated on every selection / sync / failure / read failure
        self.alert_runner = (alerts.AlertRunner(alerts.AlertService(inventory.db_path), self.alert_gate)
                             if inventory is not None else None)
        self.alerts_window = None
        self.daily_window = None     # M3.2D Daily Stock Summary window, at most one
        self.verified_roles = set()  # roles whose latest sync in this session verified the local file
        self.alert_sources = {}      # role -> (version ID, selected path) of that verification
        self.alert_status_events = queue.Queue()
        self.alert_schema = None     # database schema, once read
        self.alert_active = None     # ACTIVE alerts of the current files, as stored
        self.alert_current = False   # re-checked by a verified evaluation of this session, at this gate generation
        self.alert_reason = "not re-checked since this program started"
        self.alert_read_error = None  # last alert/status read failure, until a later read succeeds
        self.alert_text = "Stock Alerts"
        self.deferred_alerts = None  # an evaluation requested while a job was running
        self.cache_selection = None  # explicit opt-in for this session only; never restored from settings
        self.cache_authorized = False
        self.maintenance_message = ''
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
        # B1: interface language (labels only; never the assistant reply or report language) and page state.
        # Reading the preference file never fails and starts nothing (no sync, no AI): a bad file gives English.
        self.preferences = preferences
        language, self.preference_problem = preferences.load() if preferences is not None else ("en", None)
        self.preference_error = None
        self.language = i18n.LanguageState(language)
        # The status bar keeps the newest structured message and renders it in the current language. Only the newest
        # message exists: a switch re-renders it, it can never bring back an older job's text.
        self.status_message = i18n.Message("st_ready")
        self.status.set(self.text(self.status_message))
        self.i18n_bindings = []   # (widget, key, option, values) refreshed on every language switch
        self.wrapping = []        # labels whose wraplength follows their card width
        self.page = "home"
        self.last_check = None    # what the home card shows about the last CHECK of this session
        self._build()
        self.language.subscribe(self._language_changed)
        for var in (self.stock_name, self.product_text, self.quantity_text):
            var.trace_add("write", lambda *_: self.invalidate())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = self.root.after(50, self._poll)
        if self.alert_runner is not None:
            self._load_alert_status()
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
        style.configure("Treeview.Heading", background="#e3eefa", foreground=INK, font=("Segoe UI", 9, "bold"), padding=(8, 8))
        style.map("Treeview", background=[("selected", "#dbe9fa")], foreground=[("selected", "#163d6b")])
        style.configure("Filter.TRadiobutton", background="white", padding=(10, 5), font=("Segoe UI", 9))
        style.layout("Filter.TRadiobutton", [("Radiobutton.padding", {"sticky": "nswe", "children": [
            ("Radiobutton.label", {"sticky": "nswe"})]})])
        style.map("Filter.TRadiobutton", background=[("selected", "#dbe9fa"), ("active", "#eaf2fb")],
                  foreground=[("selected", "#174c8a")])
        # B1 shell styles
        style.configure("Top.TFrame", background="white")
        style.configure("Top.TLabel", background="white", foreground=INK)
        style.configure("TopMuted.TLabel", background="white", foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Cloud.TLabel", background="#fff0d4", foreground="#8f5200", font=("Segoe UI", 9, "bold"),
                        padding=(6, 1))
        style.configure("PageTitle.TLabel", background="white", foreground=INK, font=("Segoe UI", 14, "bold"))
        style.configure("Lang.TButton", font=("Segoe UI", 9), padding=(8, 2), background="white")
        style.configure("LangOn.TButton", font=("Segoe UI", 9, "bold"), padding=(8, 2), background="#dcebfb",
                        foreground="#185a9c")
        style.configure("Status.TFrame", background="white")
        style.configure("Status.TLabel", background="white", foreground=MUTED, font=("Segoe UI", 9))
        # The assistant docks beside self.outer (pack side=right before it); the whole B1 shell is that frame.
        self.outer = shell = tk.Frame(self.root, background=BG)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(1, weight=1)
        shell.rowconfigure(1, weight=1)
        self.controls = []
        self._build_sidebar(shell)
        self._build_topbar(shell)
        self.pages = ttk.Frame(shell)
        self.pages.grid(row=1, column=1, sticky="nsew")
        self.pages.columnconfigure(0, weight=1)
        self.pages.rowconfigure(0, weight=1)
        self.page_frames = {}
        self._build_check_page()
        self.home = HomePage(self, self.pages)
        self.page_frames["home"] = self.home.frame
        self._build_launcher_pages()
        self.footer = footer = ttk.Frame(shell, style="Status.TFrame", padding=(12, 4))
        footer.grid(row=2, column=1, sticky="ew")
        footer.columnconfigure(0, weight=1)
        # width=1: a long status is cut at its own cell instead of running under the labels beside it (full text in
        # the tooltip).
        self.status_label = ttk.Label(footer, textvariable=self.status, style="Status.TLabel", width=1)
        self.status_label.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        Tooltip(self.status_label, self.status.get)
        self.verification_label = ttk.Label(footer, text="Verification Required", style="Status.TLabel", cursor="hand2")
        self.verification_label.grid(row=0, column=1, sticky="e")
        self._tr(self.verification_label, "verification_required")
        self.assistant = AssistantLauncher(self, footer)
        Tooltip(self.verification_label, lambda: "Verification Required. BOM quantity basis, units, assembly configurations and stock availability remain unconfirmed. Results are estimates, not production approval.")
        self.root.bind("<Configure>", self._resize, add="+")
        self.show_page("home")
        self._schedule_resize()

    # ------------------------------------------------------------------ B1 shell
    def _tr(self, widget, key, option="text", **values):
        """Register a widget option for the interface language (updated on every switch)."""
        self.i18n_bindings.append((widget, key, option, values))
        widget.configure(**{option: i18n.tr(key, self.language.language, **values)})
        return widget

    def t(self, key, **values):
        return i18n.tr(key, self.language.language, **values)

    def text(self, message):
        """A structured message (or plain text) in the current interface language."""
        return i18n.render(message, self.language.language)

    def _set_status(self, message):
        self.status_message = message
        self.status.set(self.text(message))

    def _db_suffix(self):
        """' · Inventory Database: <state> — Cloud Not Verified' for the state shown now (a snapshot)."""
        return i18n.Message("st_db_suffix", state=i18n.State(self.db_overall), cloud=CLOUD_NOT_VERIFIED)

    def _render_preference(self):
        label = getattr(self, "preference_label", None)
        if label is None:
            return
        if self.preference_error is not None:
            text = self.t("pref_failed", error=self.preference_error)
        elif self.preference_problem is not None:
            text = self.t("pref_unreadable")
        else:
            text = ""
        label.configure(text=text)

    def set_language(self, language):
        """Interface language only: no Excel read, sync, AI call or permission change; inputs, results, filters and
        running jobs are untouched (the Tk variables and objects stay the same)."""
        self.language.set(language)

    def _language_changed(self, _language):
        for widget, key, option, values in list(self.i18n_bindings):
            try:
                widget.configure(**{option: self.t(key, **values)})
            except tk.TclError:
                self.i18n_bindings.remove((widget, key, option, values))
        for code, button in self.lang_buttons.items():
            button.configure(style="LangOn.TButton" if code == self.language.language else "Lang.TButton")
        self._apply_tree_headings()
        self._apply_filter_labels()
        self._render_nav()
        self.page_title.configure(text=self.t(PAGE_TITLES[self.page]))
        self._render_inventory()
        self._render_alerts()
        for role in ROLES:
            self._refresh_file_card(role)
        self.home.render()
        self.status.set(self.text(self.status_message))
        if self.preferences is not None:
            try:
                self.preferences.save(self.language.language)
                self.preference_error = self.preference_problem = None
            except OSError as exc:  # this session keeps the language; nothing else depends on the file
                self.preference_error = f"{type(exc).__name__}: {exc}"
        self._render_preference()
        self._schedule_resize()

    def _build_sidebar(self, shell):
        self.sidebar = side = tk.Frame(shell, background=SIDE_BG, width=SIDE_WIDE)
        side.grid(row=0, column=0, rowspan=3, sticky="nsw")
        side.grid_propagate(False)
        side.columnconfigure(0, weight=1)
        brand = tk.Frame(side, background=SIDE_BG)
        brand.grid(row=0, column=0, sticky="ew", padx=10, pady=(12, 10))
        tk.Label(brand, text="MSC", background=BLUE, foreground="white", font=("Segoe UI", 9, "bold"), width=4,
                 height=2).pack(side="left")
        self.brand_text = tk.Label(brand, text="Material Stock\nChecker", background=SIDE_BG, foreground=SIDE_INK,
                                   font=("Segoe UI", 10, "bold"), justify="left")
        self.brand_text.pack(side="left", padx=(8, 0))
        self.nav_items = {}
        for row, (page, glyph, key) in enumerate(NAV, 1):
            item = tk.Frame(side, background=SIDE_BG, cursor="hand2", takefocus=1, highlightthickness=1,
                            highlightbackground=SIDE_BG, highlightcolor=BLUE)
            item.grid(row=row, column=0, sticky="ew", padx=6, pady=1)
            icon = tk.Label(item, text=glyph, background=SIDE_BG, foreground=SIDE_INK, font=(ICON_FONT, 13), width=2)
            icon.pack(side="left", padx=(6, 4), pady=7)
            text = tk.Label(item, text="", background=SIDE_BG, foreground=SIDE_INK, font=("Segoe UI", 10), anchor="w")
            text.pack(side="left", fill="x", expand=True)
            for widget in (item, icon, text):
                widget.bind("<Button-1>", lambda _e, p=page: self.show_page(p))
            item.bind("<Return>", lambda _e, p=page: self.show_page(p))
            item.bind("<space>", lambda _e, p=page: self.show_page(p))
            Tooltip(item, lambda k=key, p=page: self.t(k) + ("\n" + self.alert_text if p == "alerts" else ""))
            self.nav_items[page] = (item, icon, text, key)
        side.rowconfigure(len(NAV) + 1, weight=1)
        self.collapse_item = tk.Label(side, text=GLYPH_COLLAPSE, background=SIDE_BG, foreground=SIDE_INK,
                                      font=(ICON_FONT, 11), cursor="hand2", anchor="w", padx=12, pady=8)
        self.collapse_item.grid(row=len(NAV) + 2, column=0, sticky="ew")
        self.collapse_item.bind("<Button-1>", lambda _e: self.toggle_sidebar())
        Tooltip(self.collapse_item, lambda: self.t("expand" if self.sidebar_slim else "collapse"))
        self.sidebar_user = None   # None: automatic (slim below 1100 px); True/False: the user's choice
        self.sidebar_slim = False

    def toggle_sidebar(self):
        self.sidebar_user = not self.sidebar_slim
        self._apply_sidebar()

    def _apply_sidebar(self):
        width = self.outer.winfo_width() if self.outer.winfo_width() > 1 else self.root.winfo_width()
        auto = width < 1100 * self._scale()  # the shell narrows when the assistant is docked beside it
        slim = self.sidebar_user if self.sidebar_user is not None else auto
        if slim == self.sidebar_slim and self.sidebar.winfo_reqwidth() > 1:
            return
        self.sidebar_slim = slim
        self.sidebar.configure(width=SIDE_SLIM if slim else int(SIDE_WIDE * self._scale()))
        self.brand_text.pack_forget() if slim else self.brand_text.pack(side="left", padx=(8, 0))
        for item, icon, text, key in self.nav_items.values():
            text.pack_forget() if slim else text.pack(side="left", fill="x", expand=True)
        self.collapse_item.configure(text=GLYPH_EXPAND if slim else GLYPH_COLLAPSE)

    def _scale(self):
        return max(1.0, float(self.root.tk.call("tk", "scaling")) / (96 / 72))

    def _render_nav(self):
        for page, (item, icon, text, key) in self.nav_items.items():
            active = page == self.page
            colour, ink = (BLUE, "white") if active else (SIDE_BG, SIDE_INK)
            for widget in (item, icon, text):
                widget.configure(background=colour)
            icon.configure(foreground=ink)
            label = self.t(key)
            if page == "alerts" and self.alert_active is not None and self.alert_schema is not None \
                    and self.alert_schema >= alerts.ALERT_SCHEMA_VERSION:
                # The stored count; "?" while this session has not re-checked it (details in the tooltip).
                label += f"  ({self.alert_active}{'' if self.alert_current else '?'})"
            text.configure(text=label, foreground=ink, font=("Segoe UI", 10, "bold" if active else "normal"))

    def _build_topbar(self, shell):
        self.topbar = top = ttk.Frame(shell, style="Top.TFrame", padding=(14, 8, 14, 6))
        top.grid(row=0, column=1, sticky="ew")
        top.columnconfigure(0, weight=1)
        title_row = ttk.Frame(top, style="Top.TFrame")
        title_row.grid(row=0, column=0, sticky="ew")
        self.page_title = ttk.Label(title_row, text="", style="PageTitle.TLabel")
        self.page_title.pack(side="left")
        languages = ttk.Frame(title_row, style="Top.TFrame")
        languages.pack(side="right")
        self.lang_buttons = {}
        for code in ("zh", "en", "ms"):
            button = ttk.Button(languages, text=i18n.SHORT_NAMES[code], command=lambda c=code: self.set_language(c),
                                style="LangOn.TButton" if code == self.language.language else "Lang.TButton", width=4)
            button.pack(side="left", padx=1)
            self.lang_buttons[code] = button
        Tooltip(languages, lambda: self.t("lang_note"))
        # Data bar: database status (or the permanent cloud notice without a database) and Refresh Excel.
        notice = ttk.Frame(top, style="Top.TFrame")
        notice.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        notice.columnconfigure(0, weight=1)
        self.db_panel = None
        if self.inventory is not None or self.inventory_error is not None:
            self._build_inventory_panel(notice)
        else:
            self.cloud_chip = ttk.Label(notice, text=CLOUD_NOT_VERIFIED, style="Cloud.TLabel")
            self.cloud_chip.grid(row=0, column=0, sticky="w")

    def _build_launcher_pages(self):
        """Secondary functions keep their existing windows; these pages make each one discoverable and working."""
        def page(name, intro_key):
            frame = ttk.Frame(self.pages, padding=(16, 14))
            frame.columnconfigure(0, weight=1)
            card = ttk.Frame(frame, style="Card.TFrame", padding=(16, 14))
            card.grid(row=0, column=0, sticky="ew")
            card.columnconfigure(0, weight=1)
            intro = ttk.Label(card, style="Card.TLabel", wraplength=640, justify="left")
            intro.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 10))
            self._tr(intro, intro_key)
            self.wrapping.append(intro)
            note = ttk.Label(card, style="CardMuted.TLabel")
            note.grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))
            self._tr(note, "not_covered")
            buttons = ttk.Frame(card, style="Card.TFrame")
            buttons.grid(row=1, column=0, sticky="w")
            self.page_frames[name] = frame
            return frame, buttons, note
        _f, b, _n = page("materials", "materials_intro")
        self.history_button = self._tr(ttk.Button(b, command=self.open_history, padding=(10, 5)), "open_history")
        self.history_button.pack(side="left")
        self.analytics_link = self._tr(ttk.Button(b, command=self.open_analytics, padding=(10, 5)), "open_analytics")
        self.analytics_link.pack(side="left", padx=(8, 0))
        _f, b, _n = page("alerts", "alerts_intro")
        self.alerts_button = self._tr(ttk.Button(b, command=self.open_alerts, padding=(10, 5)), "open_alerts")
        self.alerts_button.pack(side="left")
        # M3.2C entry line: the alert count of the last verified evaluation and whether it was re-checked.
        self.alerts_label = ttk.Label(b, text=self.alert_text, style="Card.TLabel", font=("Segoe UI", 9, "underline"),
                                      foreground="#95641a", cursor="hand2")
        self.alerts_label.pack(side="left", padx=(12, 0))
        self.alerts_label.bind("<Button-1>", lambda _e: self.open_alerts())
        Tooltip(self.alerts_label, lambda: "Stock Alerts (M3.2C) from synchronised Excel data. Thresholds and "
                "units pending business confirmation. Cloud Not Verified. Click to open." +
                ("" if self.alert_current else f"\nNot re-checked: {self.alert_reason}"))
        _f, b, _n = page("daily", "daily_intro")
        self.daily_link = self._tr(ttk.Button(b, command=self.open_daily, padding=(10, 5)), "open_daily")
        self.daily_link.pack(side="left")
        _f, b, note = page("ai", "ai_intro")
        self._tr(ttk.Button(b, command=self.open_ai_reports, padding=(10, 5)), "open_ai").pack(side="left")
        self._tr(note, "lang_note")  # the assistant keeps its own reply-language rules and language selector
        frame, b, note = page("settings", "cache_intro")
        note.grid_remove()  # the cache consent is a dialog of this window, not a separate window
        self.settings_cache_button = self._tr(ttk.Button(b, command=self.use_cached_data, padding=(10, 5)), "use_cache")
        self.settings_cache_button.pack(side="left")
        maintenance = ttk.Frame(frame, style="Card.TFrame", padding=(16, 14))
        maintenance.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        heading = ttk.Label(maintenance, style="Card.TLabel", font=("Segoe UI", 11, "bold"))
        heading.pack(anchor="w")
        self._tr(heading, "settings_maintenance")
        row = ttk.Frame(maintenance, style="Card.TFrame")
        row.pack(anchor="w", pady=(8, 0))
        if self.inventory is not None:
            self.maintenance_button = self._tr(ttk.Button(row, command=self.preview_cleanup, padding=(10, 5)),
                                               "local_history")
            self.maintenance_button.pack(side="left")
            self.upgrade_button = self._tr(ttk.Button(row, command=self.preview_upgrade, padding=(10, 5)), "db_upgrade")
            self.upgrade_button.pack(side="left", padx=(8, 0))
            self.controls += [(self.maintenance_button, "normal"), (self.upgrade_button, "normal"),
                              (self.settings_cache_button, "normal")]
        else:
            self._tr(ttk.Label(row, style="CardMuted.TLabel"), "needs_db").pack(anchor="w")
        language = ttk.Frame(frame, style="Card.TFrame", padding=(16, 14))
        language.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        heading = ttk.Label(language, style="Card.TLabel", font=("Segoe UI", 11, "bold"))
        heading.pack(anchor="w")
        self._tr(heading, "language")
        note = ttk.Label(language, style="CardMuted.TLabel", justify="left")
        note.pack(anchor="w", fill="x", pady=(6, 0))
        self._tr(note, "lang_note")
        self.wrapping.append(note)
        self.preference_label = ttk.Label(language, style="CardMuted.TLabel", justify="left", foreground="#8f5200")
        self.preference_label.pack(anchor="w", fill="x", pady=(4, 0))
        self.wrapping.append(self.preference_label)
        self._render_preference()
        files = ttk.Frame(frame, style="Card.TFrame", padding=(16, 14))
        files.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        heading = ttk.Label(files, style="Card.TLabel", font=("Segoe UI", 11, "bold"))
        heading.pack(anchor="w")
        self._tr(heading, "settings_files")
        row = ttk.Frame(files, style="Card.TFrame")
        row.pack(anchor="w", pady=(8, 0))
        self.settings_file_buttons = {}
        for role, key in (("stock", "storage_file"), ("bom", "bom_file")):
            button = ttk.Button(row, command=lambda r=role: self.browse(r), padding=(10, 5))
            self._tr(button, key)
            button.pack(side="left", padx=(0, 8))
            self.controls.append((button, "normal"))
            self.settings_file_buttons[role] = button

    def show_page(self, name):
        """Show one page; nothing is reloaded, re-read or recalculated."""
        if name not in self.page_frames:
            return
        self.page = name
        for key, frame in self.page_frames.items():
            if key == name:
                frame.grid(row=0, column=0, sticky="nsew")
            else:
                frame.grid_remove()
        self.page_title.configure(text=self.t(PAGE_TITLES[name]))
        self._render_nav()
        if name == "home":
            self.home.render()
        self._schedule_resize()

    def open_ai_reports(self):
        if self.assistant is None:
            return
        if self.assistant.surface is None:
            self.assistant.toggle()
        view = self.assistant.view
        if view is not None:  # the AI reports tab, found by its title in the assistant's own language
            title = tr_assistant("report_tab", self.assistant.language)
            for tab in view.tabs.tabs():
                if view.tabs.tab(tab, "text") == title:
                    view.tabs.select(tab)

    def _build_check_page(self):
        outer = self.check_page = ttk.Frame(self.pages, padding=(14, 10))
        self.page_frames["check"] = outer
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
        files = ttk.Frame(self.overview_content)
        files.grid(row=1, sticky="ew", pady=(0, 10))
        files.columnconfigure((0, 1), weight=1, uniform="files")
        for col, role in enumerate(("stock", "bom")):
            card = ttk.Frame(files, style="Card.TFrame", padding=(12, 8))
            card.grid(row=0, column=col, sticky="nsew", padx=(0, 6) if col == 0 else (6, 0))
            card.columnconfigure(0, weight=1)
            title = ttk.Label(card, text="Storage File" if role == "stock" else "BOM File", style="CardMuted.TLabel")
            title.grid(row=0, column=0, sticky="w")
            self._tr(title, "storage_file" if role == "stock" else "bom_file")
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
        self._tr(ttk.Label(selections, style="CardMuted.TLabel"), "product_id").grid(row=0, column=0, sticky="w")
        self._tr(ttk.Label(selections, style="CardMuted.TLabel"), "quantity").grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.product_combo = ttk.Combobox(selections, textvariable=self.product_text, state="normal", font=("Segoe UI", 10))
        self.product_combo.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self._bind_product_box(self.product_combo)
        self.quantity_entry = ttk.Entry(selections, textvariable=self.quantity_text, width=6, font=("Segoe UI", 10))
        self.quantity_entry.grid(row=1, column=1, padx=(12, 12), pady=(4, 0))
        self.quantity_entry.bind("<Return>", lambda _event: self.check())
        self.check_button = ttk.Button(selections, text="CHECK MATERIALS", style="Primary.TButton", command=self.check)
        self.check_button.grid(row=1, column=2, padx=(0, 8), pady=(4, 0))
        self._tr(self.check_button, "check_button")
        self.export_button = ttk.Button(selections, text="EXPORT EXCEL", command=self.export)
        self.export_button.grid(row=1, column=3, pady=(4, 0))
        self._tr(self.export_button, "export_button")
        # Multi-sheet stock selection stays explicit. Hide it for the common single-sheet case.
        self.stock_sheet_frame = ttk.Frame(selections, style="Card.TFrame")
        self.stock_sheet_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        self._tr(ttk.Label(self.stock_sheet_frame, style="CardMuted.TLabel"), "storage_sheet").pack(side="left", padx=(0, 8))
        self.stock_combo = ttk.Combobox(self.stock_sheet_frame, textvariable=self.stock_name, state="readonly")
        self.stock_combo.pack(side="left", fill="x", expand=True)
        self.stock_sheet_frame.grid_remove()
        for control, state in ((self.stock_combo, "readonly"), (self.product_combo, "normal"), (self.quantity_entry, "normal"),
                               (self.check_button, "normal"), (self.export_button, "normal")):
            self.controls.append((control, state))
        notice = ttk.Frame(outer)
        notice.grid(row=3, sticky="ew", pady=(8, 8))
        notice.columnconfigure(0, weight=1)
        self.notice_label = ttk.Label(notice, text=NOTICE_TEXT, style="Muted.TLabel")
        self.notice_label.grid(row=0, column=0, sticky="w")
        Tooltip(self.notice_label, lambda: (NOTICE_TEXT + "\n" if self.db_panel is not None else "") +
                "Review yellow Exception rows before use.\nVerification Required · " + ROW_CAVEAT)
        if self.inventory is not None:
            self.cache_button = ttk.Button(notice, text="Use Cached Data…", command=self.use_cached_data, padding=(8, 3))
            self.cache_button.grid(row=0, column=1, padx=(8, 0))
            self._tr(self.cache_button, "use_cache")
            self.controls.append((self.cache_button, "normal"))
        self.reload_button = ttk.Button(notice, text="Reload Files", command=self.reload_files, padding=(8, 3))
        self.reload_button.grid(row=0, column=2, padx=(8, 0))
        self._tr(self.reload_button, "reload")
        self.controls.append((self.reload_button, "normal"))
        self.mode_label = self.notice_label  # Permanent mode warning without an extra pinned row.
        results = ttk.Frame(outer, style="Card.TFrame", padding=8)
        results.grid(row=5, sticky="nsew")
        results.rowconfigure(1, weight=1)
        results.columnconfigure(0, weight=1)
        toolbar = ttk.Frame(results, style="Card.TFrame")
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self._tr(ttk.Label(toolbar, style="Card.TLabel", font=("Segoe UI", 11, "bold")), "results_title").pack(side="left", padx=(2, 16))
        self.filter_buttons = {}
        for value in ("All", SHORTAGE, EXCEPTION, ENOUGH):
            button = ttk.Radiobutton(toolbar, variable=self.filter_category, value=value,
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
        self.tree = ttk.Treeview(results, columns=[x[0] for x in TREE_COLUMNS], show="headings", selectmode="browse", height=4)
        for ident, key, width in TREE_COLUMNS:
            heading_width = tkfont.Font(font=("Segoe UI", 9, "bold")).measure(i18n.tr(key)) + 24
            self.tree.column(ident, width=max(width, heading_width), minwidth=heading_width, stretch=ident in ("description", "status"),
                             anchor="e" if ident in ("required", "stock", "shortage") else "w")
        self._apply_tree_headings()
        self._apply_filter_labels()
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
        self._tr(ttk.Label(self.detail_frame, style="CardMuted.TLabel"), "detail_title").grid(row=0, column=0, sticky="w")
        self._tr(ttk.Button(self.detail_frame, command=self.hide_details, padding=(6, 2)), "close_details").grid(row=0, column=1, sticky="e")
        self.details = tk.Text(self.detail_frame, height=2, wrap="word", font=("Segoe UI", 9), state="disabled",
                               background="white", foreground=INK, relief="flat", padx=0, pady=4)
        self.details.grid(row=1, column=0, columnspan=2, sticky="ew")
        scroll = ttk.Scrollbar(self.detail_frame, orient="vertical", command=self.details.yview)
        scroll.grid(row=1, column=2, sticky="ns")
        self.details.configure(yscrollcommand=scroll.set)
        self.detail_frame.grid_remove()
        self.export_feedback = ttk.Frame(outer, style="Card.TFrame", padding=8)
        self.export_feedback.grid(row=8, sticky="ew", pady=(6, 0))
        self.export_feedback.columnconfigure(0, weight=1)
        self.export_feedback_label = ttk.Label(self.export_feedback, style="CardMuted.TLabel", cursor="hand2")
        self.export_feedback_label.grid(row=0, column=0, sticky="ew")
        Tooltip(self.export_feedback_label, lambda: self.export_path.get())
        self.export_feedback_label.bind("<Button-1>", lambda _e: self.file_popup("Exported report", self.export_path.get()))
        self._tr(ttk.Button(self.export_feedback, command=self.open_export_folder), "open_folder").grid(row=0, column=1, padx=(8, 0))
        self._tr(ttk.Button(self.export_feedback, command=self.export_feedback.grid_remove), "dismiss").grid(row=0, column=2, padx=(8, 0))
        self.export_feedback.grid_remove()
        def bind_overview_scroll(widget):
            widget.bind("<MouseWheel>", lambda e: self.overview_canvas.yview_scroll(-int(e.delta / 120), "units"), add="+")
            for child in widget.winfo_children():
                bind_overview_scroll(child)
        bind_overview_scroll(self.overview)

    def _apply_tree_headings(self):
        for ident, key, _width in TREE_COLUMNS:
            self.tree.heading(ident, text=self.t(key), anchor="center")

    def _apply_filter_labels(self):
        """Filter buttons carry their counts (B1); the counts come from the shown result only."""
        for value, key in (("All", "filter_all"), (SHORTAGE, "filter_shortage"), (EXCEPTION, "filter_exception"),
                           (ENOUGH, "filter_enough")):
            count = self.summary_counts["total" if value == "All" else value].get()
            self.filter_buttons[value].configure(text=self.t(key) + ("" if count == "—" else f" {count}"))

    def _bind_product_box(self, box):
        """Product ID search for any box bound to product_text (check page and home)."""
        box.bind("<KeyRelease>", self._search)
        box.bind("<FocusIn>", lambda _event: self._search())
        box.bind("<<ComboboxSelected>>", lambda _event: self._search(reset=True))
        box.bind("<Return>", self._pick)
        Tooltip(box, lambda: self.product_text.get() or "Type part of a Product ID, then select a match.")

    def _set_product_values(self, values):
        for box in self.product_boxes():
            box.configure(values=values)

    def _set_sheet_values(self, values):
        for box in (self.stock_combo, getattr(self.home, "sheet_combo", None)):
            if box is not None:
                box.configure(values=values)

    def product_boxes(self):
        return tuple(b for b in (self.product_combo, getattr(getattr(self, "home", None), "product_combo", None)) if b)

    def _build_inventory_panel(self, notice):
        """Compact two-line 'Inventory Database' section in the notice row, beside Reload Files: always visible
        (not in the scrolling file overview) and nearly free in height, because the row is as tall as its buttons."""
        self.db_status = tk.StringVar()
        self.db_times = tk.StringVar()
        self.db_role_text = {role: tk.StringVar() for role in ROLES}
        panel = self.db_panel = ttk.Frame(notice, style="Top.TFrame")
        panel.grid(row=0, column=0, sticky="ew")
        panel.columnconfigure((0, 1), weight=1, uniform="db")
        heading = ttk.Frame(panel, style="Top.TFrame")
        heading.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.db_title_label = ttk.Label(heading, text="Inventory Database", style="TopMuted.TLabel")
        self.db_title_label.pack(side="left")
        self._tr(self.db_title_label, "db_title")
        # The status and the cloud limitation are never shortened or hidden, in any state; the times label gives way,
        # then the title. Nothing here checks the Google Drive cloud copy, so "Cloud Not Verified" is permanent.
        self.db_status_label = ttk.Label(heading, textvariable=self.db_status, style="Top.TLabel",
                                         font=("Segoe UI", 9, "bold"), cursor="hand2")
        self.db_status_label.pack(side="left", padx=(10, 0))
        self.db_cloud_label = ttk.Label(heading, text=CLOUD_NOT_VERIFIED, style="Cloud.TLabel", cursor="hand2")
        self.db_cloud_label.pack(side="left", padx=(12, 0))
        self.db_times_label = ttk.Label(heading, style="TopMuted.TLabel", cursor="hand2")
        self.db_times_label.pack(side="left", padx=(16, 0))
        self.db_times_short = ""  # compact form of db_times for narrow windows
        self.refresh_button = ttk.Button(notice, text="Refresh Excel", command=self.refresh_excel, style="Primary.TButton")
        self.refresh_button.grid(row=0, column=1, rowspan=2, sticky="e", padx=(8, 0))
        self._tr(self.refresh_button, "refresh")
        self.controls.append((self.refresh_button, "normal"))
        self.db_role_labels = {}
        for col, role in enumerate(ROLES):
            # Full text in db_role_text (details, tests); the label shows it shortened to fit its column.
            label = ttk.Label(panel, style="TopMuted.TLabel", cursor="hand2")
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
            self.db_status.set(f"{self.t('status_prefix')}: {i18n.state_text(DATABASE_UNAVAILABLE, self.language.language)}")
            self.db_times.set(self.t("db_unavailable_times"))
            self.db_times_short = self.t("click_details")
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
        language = self.language.language
        # "Cloud Not Verified" is the separate, permanent label beside it
        self.db_status.set(f"{self.t('status_prefix')}: {i18n.state_text(overall, language)}")
        self.db_status_label.configure(foreground=self._state_colour(overall))
        checked, success = overall_times(roles) if roles else (None, None)
        # A verification time is current only in the verified state; otherwise it is explicitly historical.
        verified = "last_verified" if overall == LOCAL_VERIFIED or success is None else "previously_verified"
        self.db_times.set(f"{self.t(verified)}: {local_time(success, SHORT_TIME)}  ·  "
                          f"{self.t('last_checked')}: {local_time(checked, SHORT_TIME)}")
        short = self.t(verified).removeprefix("Last ") if language == "en" else self.t(verified)
        self.db_times_short = f"{short} {local_time(success, '%m-%d %H:%M')}"
        for role in ROLES:
            info = roles.get(role)
            state = active.get(role) or (info.label if info else STATUS_UNKNOWN if overall == STATUS_UNKNOWN else NOT_SYNCED)
            text = f"{ROLE_NAMES[role]}: {i18n.state_text(state, language)}"
            if info and info.source_modified:
                text += f"  ·  {self.t('source_modified')} {local_time(info.source_modified, SHORT_TIME)}"
            self.db_role_text[role].set(text)
            self.db_role_labels[role].configure(foreground=self._state_colour(state))
        self._fit_inventory_labels()
        if getattr(self, "home", None) is not None:
            self.home._render_sources()

    def _fit_inventory_labels(self):
        panel = self.db_panel
        column = (panel.winfo_width() - 24) // 2
        for role, label in self.db_role_labels.items():
            text = self.db_role_text[role].get()
            label.configure(text=ellipsize(text, column, ("Segoe UI", 9)) if column > 60 else text)
        # The status and "Cloud Not Verified" are never shortened. The times show in full, else in compact form; when
        # even that does not fit, the "Inventory Database" title gives way before the verification time does.
        face = tkfont.Font(font=("Segoe UI", 9))
        # Requested widths include the B1 chip padding of "Cloud Not Verified" and the current font scaling.
        room = (panel.winfo_width() - tkfont.Font(font=("Segoe UI", 9, "bold")).measure(self.db_status.get())
                - self.db_cloud_label.winfo_reqwidth() - 44)
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
                kept = i18n.Message("sync_kept_unknown")
            elif info and info.has_data:
                kept = i18n.Message("sync_kept_previous", time=local_time(info.last_success))
            else:
                kept = i18n.Message("sync_kept_none")
            state = (SOURCE_UNAVAILABLE if result.outcome == "UNAVAILABLE" else
                     SOURCE_CHANGED if result.changed else SYNC_FAILED)
            if not result.recorded:
                kept = i18n.Join((kept, i18n.Message("sync_unrecorded")), "\n")
            notes.append(i18n.Message("sync_role", role=ROLE_NAMES[role], state=state, error=str(result.error), kept=kept))
        if db_error:
            notes.append(i18n.Message("sync_status_failed", error=str(db_error), state=STATUS_UNKNOWN))
        if notes:
            notes.append(i18n.Message("sync_retry"))
        # A structured note, rendered in the interface language when it is shown ("" when there is nothing to say).
        return i18n.Join(notes) if notes else ""

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
            self._set_status(i18n.Message("st_remember_failed", error=str(exc)))

    def _startup(self):
        """Restore remembered files, then check them against the database in the background."""
        remembered = self.settings.load() if self.settings is not None else {}
        for role, path in remembered.items():
            (self.stock_path if role == "stock" else self.bom_path).set(path)
            self.file_view[role]["loading"] = True
            self._refresh_file_card(role)
        self._start(lambda: {role: self._read(role, path) for role, path in remembered.items()}, self._loaded,
                    "启动检查", sync=(remembered, "startup"))

    def preview_cleanup(self):
        """Manual maintenance only. Preview, explicit No-default consent, then a separate guarded worker."""
        if self.busy:
            return
        if self.inventory is None:
            messagebox.showerror('Local History', self.t("needs_db_body"), parent=self.root)
            return
        if self._alerts_running('Local History'):
            return
        service = retention.RetentionService(self.inventory.db_path)
        def done(result):
            self.maintenance_message = ('st_cleanup_done' if result.backup else 'st_nothing_expired')
            messagebox.showinfo('Local History', self.t(self.maintenance_message) +
                                ('\nRecovery backup: ' + result.backup if result.backup else '\nNo data deleted.'),
                                parent=self.root)
        def offer(plan):
            self.maintenance_message = 'st_cleanup_preview_only'
            if plan.empty:
                messagebox.showinfo('Local History', plan.describe() + '\n\nNothing expired. No data deleted.', parent=self.root)
                return
            job = self.job
            answer = messagebox.askyesno('Confirm local history cleanup?', plan.describe() +
                                        '\n\nCreate a backup and delete ONLY these expired local records?',
                                        parent=self.root, default='no')
            if not answer or self.closed or self.busy or job != self.job:
                return
            self._start(lambda: service.apply(plan, self.cancelled), done, '清理历史数据')
        self._start(service.preview, offer, '预览历史清理')

    def open_history(self):
        """M4A: open (or bring forward) the read-only Inventory History window. Independent of CHECK, cache mode and
        maintenance: it reads the database in its own consistent read transactions and changes nothing here."""
        if self.inventory is None:
            messagebox.showerror("Inventory History", self.t("needs_db_body"), parent=self.root)
            return
        if self.history_window is not None and not self.history_window.closed:
            self.history_window.lift()
            return
        def closed(window):
            if self.history_window is window:
                self.history_window = None
        self.history_window = HistoryWindow(self.root, self.inventory.db_path, on_close=closed)

    def open_analytics(self):
        if self.inventory is None:
            messagebox.showerror('Inventory Analytics', self.t("needs_db_body"), parent=self.root)
            return
        if self.analytics_window is not None and not self.analytics_window.closed:
            self.analytics_window.lift()
            return
        def closed(window):
            if self.analytics_window is window:
                self.analytics_window = None
        self.analytics_window = AnalyticsWindow(self.root, self.inventory.db_path, on_close=closed,
                                                on_read_error=self.alert_read_failed)

    def open_daily(self):
        """M3.2D: open (or bring forward) the Daily Stock Summary window. It only reads the database."""
        if self.alert_runner is None:
            messagebox.showerror("Daily Stock Summary", self.t("needs_db_body"), parent=self.root)
            return
        if self.daily_window is not None and not self.daily_window.closed:
            self.daily_window.lift()
            return
        self.daily_window = DailySummaryWindow(self.root, self)

    def daily_session(self):
        """What this session has verified right now (Tk thread): the gate generation, the Authorization of both files,
        and whether a verified alert evaluation of that generation was confirmed."""
        authorization = self.alert_authorization()
        return daily.Session(self.alert_gate.generation, authorization,
                             bool(self.alert_current and authorization is not None), self.alert_reason)

    # ------------------------------------------------------------------ M3.2C stock alerts
    # The entry line and the window combine two things: the alerts stored in the database (counts, history) and
    # whether THIS session has verified them. Only an evaluation requested at the current gate generation, with both
    # files verified by this program and accepted as COMPLETED under the database lock, makes the alerts current.
    # Everything else (start-up, a source selection, a sync in progress or failed, a database read failure, an
    # obsolete background result) shows the stored alerts as "not re-checked" and never resolves them.
    def open_alerts(self):
        if self.alert_runner is None:
            messagebox.showerror("Stock Alerts", self.t("needs_db_body"), parent=self.root)
            return
        if self.alerts_window is not None and not self.alerts_window.closed:
            self.alerts_window.lift()
            return
        self.alerts_window = AlertsWindow(self.root, self)

    def sources_verified(self) -> bool:
        """Both files verified by this program's own latest sync in this session, and no failure seen since."""
        return (self.verified_roles == {"stock", "bom"} and not self.sync_failures
                and self.inventory_read_error is None and set(self.alert_sources) == {"stock", "bom"})

    def alert_authorization(self):
        """What this session verified, at the current gate generation; None when it cannot authorise anything."""
        if not self.sources_verified():
            return None
        return alerts.Authorization(self.alert_gate.generation,
                                    tuple((role, *self.alert_sources[role]) for role in ("stock", "bom")))

    def _invalidate_alerts(self, reason, roles=("stock", "bom"), read_failure=False):
        """A selection, sync, failure or read failure: earlier verification no longer applies.

        roles: whose verification EVIDENCE is discarded as well (not only re-stamped with a new generation). Only new
        successful source checks of those roles can authorise a verified evaluation again; a manual Re-evaluate
        cannot. A database read failure discards the evidence of both. The gate generation always moves on, so a
        running evaluation cannot publish (SessionGate.publishing is checked around its COMMIT)."""
        if self.assistant is not None:
            self.assistant.invalidate()
        if self.alert_runner is None:
            return
        for role in roles:
            self.verified_roles.discard(role)
            self.alert_sources.pop(role, None)
        self.alert_gate.invalidate()
        self.alert_current = False
        self.alert_reason = reason
        if read_failure:
            self.alert_read_error = reason
        self._render_alerts()

    def alert_read_failed(self, error):
        """Any failed read of alert/status/observed-change data (window or background): unknown, not deleted."""
        self._invalidate_alerts(f"the local database could not be read ({error})", read_failure=True)

    def alert_read_ok(self):
        """A later successful read: the data is readable again; it does not re-verify anything."""
        if self.alert_read_error is not None:
            self.alert_read_error = None
            self._render_alerts()

    def request_alerts(self, trigger):
        """Evaluate from the synchronised data on the alert worker (one at a time, one pending)."""
        if self.alert_runner is None or self.closed:
            return
        if self.busy:  # never write alerts while a job (sync, cleanup, upgrade) runs; evaluate when it ends
            self.deferred_alerts = trigger
            return
        authorization = self.alert_authorization()
        if authorization is None and self.alert_current:
            self._invalidate_alerts("the Excel files are not both verified in this session", roles=())
        self.alert_runner.request(trigger, authorization)
        self._render_alerts()

    def _alerts_running(self, title):
        """Maintenance previews wait for a running alert evaluation (it writes the database)."""
        if self.alert_runner is not None and self.alert_runner.running:
            messagebox.showinfo(title, "Stock alerts are being evaluated. Please try again in a moment.",
                                parent=self.root)
            return True
        return False

    def alert_text_now(self):
        if self.alert_schema is not None and self.alert_schema < alerts.ALERT_SCHEMA_VERSION:
            return "Stock Alerts: upgrade required"
        text = "Stock Alerts: not evaluated" if self.alert_active is None else f"Stock Alerts: {self.alert_active} active"
        if self.alert_active is not None and not self.alert_current:
            text += " · not re-checked"
        if self.alert_read_error is not None:
            text += " · database read failed"
        if self.alert_runner is not None and self.alert_runner.running:
            text += " · evaluating…"
        return text

    def _render_alerts(self):
        self.alert_text = self.alert_text_now()
        if getattr(self, "home", None) is not None:
            self._render_nav()
            self.home.render_alerts()
        if self.alert_runner is not None:
            self.alerts_label.configure(text=self.alert_text)
            if self.alerts_window is not None and not self.alerts_window.closed:
                self.alerts_window.show_session_state()

    def _load_alert_status(self):
        """Background read of the stored alert state (counts only; it can never mark alerts as re-checked)."""
        database = self.inventory.db_path

        def worker():
            try:
                self.alert_status_events.put((alerts.load_state(database, limit=0), None))
            except Exception as exc:
                self.alert_status_events.put((None, exc))
        threading.Thread(target=worker, daemon=True, name="m32c-alert-status").start()

    def _drain_alert_events(self):
        if self.alert_runner is None:
            return
        if self.deferred_alerts is not None and not self.busy:
            trigger, self.deferred_alerts = self.deferred_alerts, None
            self.request_alerts(trigger)
        changed = False
        while True:
            try:
                state, error = self.alert_status_events.get_nowait()
            except queue.Empty:
                break
            changed = True
            if error is not None:
                self.alert_read_failed(error)
            else:
                self.alert_read_ok()
                self.alert_schema = state.schema
                if state.schema >= alerts.ALERT_SCHEMA_VERSION:
                    self.alert_active = (sum(state.active_counts.values()) if state.latest_completed is not None
                                         else self.alert_active)
        refreshed = False
        while True:
            try:
                generation, result, error = self.alert_runner.events.get_nowait()
            except queue.Empty:
                break
            changed = refreshed = True
            if isinstance(error, alerts.AlertUnavailable):
                if "schema" in str(error):
                    self.alert_schema = 1
            elif error is not None and not isinstance(error, alerts.AlertStale):
                self._invalidate_alerts(f"the last evaluation failed ({error})", read_failure=True)
            elif result is not None:
                self.alert_read_ok()
                self.alert_schema = alerts.ALERT_SCHEMA_VERSION
                self.alert_active = result.active  # stored facts about the evaluated files
                current = (result.verified and self.alert_gate.valid(generation) and self.sources_verified())
                if current:
                    self.alert_current = True
                    self.alert_reason = None
                elif not self.alert_gate.valid(generation):
                    pass  # obsolete: a newer selection/sync/failure owns the state; never clear its warning
                else:
                    self.alert_current = False
                    self.alert_reason = result.reason or "the evaluation could not verify the Excel files"
        if changed:
            self._render_alerts()
            if self.alert_read_error is None:
                self.home.request()  # the stored alerts changed: the home page reads them again when it is shown
        if refreshed and self.alerts_window is not None and not self.alerts_window.closed:
            self.alerts_window.reload()

    def _note_sync(self, report):
        """After any job with a sync: record what this session verified; evaluate when both files are verified."""
        if self.alert_runner is None or report is None:
            return
        results, roles, db_error = report
        failed = []
        for role, result in results.items():
            if result.ok and result.version_id is not None:
                self.verified_roles.add(role)
                self.alert_sources[role] = (result.version_id, result.path)
            else:
                self.verified_roles.discard(role)
                self.alert_sources.pop(role, None)
                failed.append(f"{ROLE_NAMES[role]}: {result.error or result.outcome}")
        if db_error:
            failed.append(f"database status could not be read: {db_error}")
        if failed:
            self._invalidate_alerts("synchronisation failed (" + "; ".join(failed) + ")",
                                    roles=("stock", "bom") if db_error else (), read_failure=bool(db_error))
        elif results and self.sources_verified():
            self.request_alerts("sync")

    def preview_upgrade(self):
        """Explicit upgrade to the alert schema: read-only preview, No-default consent, backed-up guarded worker."""
        if self.busy or self.inventory is None or self._alerts_running("Database upgrade"):
            return
        database = self.inventory.db_path

        def done(backup):
            self.maintenance_message = "st_upgraded"
            self._invalidate_alerts("the local database was upgraded")
            messagebox.showinfo("Database upgrade", "Local database upgraded.\nRecovery backup: " + backup +
                                "\n\nThe current Excel files will now be read again (thresholds are captured if they "
                                "were not stored yet); until then alerts are not re-checked.", parent=self.root)
            self._load_alert_status()
            if self.stock_path.get() or self.bom_path.get():
                self.root.after_idle(self.refresh_excel)

        def offer(plan):
            self.maintenance_message = "st_upgrade_preview_only"
            job = self.job
            answer = messagebox.askyesno("Upgrade local database?", plan.describe() +
                                         "\n\nCreate a backup and upgrade the local database now?",
                                         parent=self.root, default="no")
            if not answer or self.closed or self.busy or job != self.job:
                return
            self._start(lambda: upgrade.apply(plan, self.cancelled), done, "升级数据库")
        self._start(lambda: upgrade.preview(database), offer, "预览数据库升级")

    def use_cached_data(self):
        """Read-only preview on a worker; only an affirmative, current dialog enables historical mode."""
        if self.busy:
            return
        if self.inventory is None:
            messagebox.showerror("Cache unavailable", self.t("needs_db_body"), parent=self.root)
            return
        database = self.inventory.db_path
        def offer(snapshot):
            job = self.job
            accepted = messagebox.askyesno("Use historical cached data?", snapshot.describe() +
                "\n\n仅用于历史试算。不是生产批准。使用上述两个缓存版本？", parent=self.root, default="no")
            if not accepted or self.busy or job != self.job:
                return
            self.cache_selection = snapshot
            self.cache_authorized = True
            self.stock_path.set(snapshot.stock.path)
            self.bom_path.set(snapshot.bom.path)
            self._stock_loaded(snapshot.stock)
            self._bom_loaded(snapshot.bom)
            self.mode_label.configure(text=cached.LABEL + " · Cloud Not Verified", foreground="#b00020")
            for role in ROLES:
                self.file_view[role]["locks"] = ()
                self.file_status[role].set(snapshot.describe())
                self._refresh_file_card(role)
        self._start(lambda: cached.load(database), offer, "读取历史缓存")

    def _leave_cache(self, clear=False):
        if self.cache_selection is None:
            return
        self.cache_selection = None
        self.cache_authorized = False
        self.mode_label.configure(text=self.t("notice"), foreground=MUTED)
        if clear:
            for role in ROLES:
                self._clear_role(role)
        for role in ROLES:
            self._refresh_file_card(role)

    def _check_cached(self, selected, count):
        if not self.cache_authorized:
            messagebox.showerror(binding.OUTDATED, self.t("err_cache_expired"), parent=self.root)
            return
        snapshot = self.cache_selection
        def action():
            cached.verify(snapshot)
            product = self.service.find_product(snapshot.bom, selected['bom'])
            sheet = self.service.find_stock_sheet(snapshot.stock, selected['stock'])
            if product is None or sheet is None:
                raise cached.CacheError("Select an existing cached product and Storage sheet.")
            result = check_materials(product, sheet, count)
            cached.verify(snapshot)
            return result, cached.CacheBinding(snapshot, time.time())
        def done(data):
            self.render_result(*data)
        self._start(action, done, "检查历史缓存")

    def refresh_excel(self):
        """Check both sources for updates, synchronise changed files and refresh what is shown. Never writes Excel."""
        if self.busy:
            return
        self._leave_cache()
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
            self._apply_sidebar()
            # Reserve the table and pinned actions; only the file overview can scroll.
            other = self._fixed_height()
            if self.db_panel is not None and self._compact_inventory(other):
                self.root.update_idletasks()
                other = self._fixed_height()
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
        for label in self.wrapping:
            room = label.master.winfo_width() - 40  # inside the card padding
            if room > 100 and int(str(label.cget("wraplength") or 0)) != room:
                label.configure(wraplength=room)
        self.home.fit()
        width = max(100, self.check_page.winfo_width() - 190)
        notice = cached.LABEL if self.cache_selection else self.t("notice")
        if self.db_panel is None:
            self.notice_label.configure(text=notice, wraplength=width)
        else:  # one line beside the buttons of its row; the full sentence is in the tooltip
            row = self.notice_label.master
            room = row.winfo_width() - sum(w.winfo_reqwidth() + 8 for w in row.grid_slaves(row=0) if w is not self.notice_label)
            self.notice_label.configure(text=ellipsize(notice, max(60, room - 8), ("Segoe UI", 9)))
        if self.export_path.get():
            self.export_feedback_label.configure(text=ellipsize(self.export_path.get(), width - 180, ("Segoe UI", 9), middle=True))

    def _fixed_height(self):
        """Height of everything on the check page and around it except the file overview and the table."""
        return (self.topbar.winfo_reqheight() + self.footer.winfo_reqheight() + self.check_page.winfo_reqheight()
                - self.overview.winfo_reqheight() - self.tree.winfo_reqheight())

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
        view["name"].configure(text=ellipsize(Path(path).name if path else self.t("choose_workbook"), name_width, ("Segoe UI", 10, "bold")))
        view["path"].configure(text=ellipsize(str(Path(path).parent) if path else ".xlsx / .xlsm", width, ("Segoe UI", 9), middle=True))
        view["button"].configure(text=self.t("change") if path else self.t("browse"))
        if book:
            status = (f"{cached.LABEL} · Imported {clock(book.loaded_at)}" if self.cache_selection else
                      self.t("card_loaded", saved=clock(book.fingerprint[2] / 1e9), loaded=clock(book.loaded_at)))
        else:
            status = (self.t("card_loading") if view["loading"] else self.t("card_failed") if path else
                      self.t("card_not_loaded"))
        view["status"].configure(text=ellipsize(status, width, ("Segoe UI", 9)))
        if view["locks"] and book:
            view["warning"].configure(text=self.t("card_locked"))
            view["warning"].grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
        else:
            view["warning"].grid_remove()
        if getattr(self, "home", None) is not None:
            self.home._render_sources()
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
                messagebox.showerror(self.t("title_open_folder"), str(exc), parent=self.root)

    def _detail_text(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def invalidate(self):
        self.result = None
        self.result_binding = None
        self.export_feedback.grid_remove()
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

    @property
    def result_exportable(self):
        if isinstance(self.result_binding, cached.CacheBinding):
            return (self.result is not None and self.result_binding.valid and self.cache_authorized
                    and self.cache_selection is not None
                    and self.result_binding.snapshot.token == self.cache_selection.token
                    and self._export_sources() == {v.role: v.path for v in self.cache_selection.versions})
        return self.result_current

    def _show_result_state(self):
        if self.result is None or self.result_binding is None:
            self.result_state_label.configure(text="", foreground=MUTED, font=("Segoe UI", 9))
        elif isinstance(self.result_binding, cached.CacheBinding):
            self.result_state_label.configure(text=cached.LABEL if self.result_exportable else binding.OUTDATED,
                                              foreground="#b00020", font=("Segoe UI", 9, "bold"))
        elif self.result_binding.current:
            when = datetime.fromtimestamp(self.result_binding.checked_at).strftime("%H:%M:%S")
            self.result_state_label.configure(text=f"Local Sources Verified {when}", foreground="#3b715e",
                                              font=("Segoe UI", 9))
        else:
            changed = " & ".join(binding.ROLE_NAMES[r] for r in self.result_binding.changed)
            self.result_state_label.configure(text=f"{binding.OUTDATED} · {changed} changed", foreground="#b00020",
                                              font=("Segoe UI", 9, "bold"))
        if not self.busy:  # an outdated result can never be exported
            self.export_button.configure(state="normal" if self.result is None or self.result_exportable else "disabled")
        self._apply_filter_labels()
        if getattr(self, "home", None) is not None:
            self.home.render_check()

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
        self._set_status(i18n.Message(JOB_STATUS.get(label, "st_loading")))
        sync = sync if self.inventory is not None else None
        if not sync and self.assistant is not None:
            self.assistant.invalidate()
        if sync:
            self.sync_active = {role: CHECKING for role, path in sync[0].items() if path}
            self._render_inventory()
            self._invalidate_alerts("the Excel files are being checked again",
                                    roles=tuple(role for role, path in sync[0].items() if path))
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
        self._drain_alert_events()
        self.home.drain()
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
            self._note_sync(report)
            # Every outcome, failures included, shows the current database state (and its cloud limitation).
            db_suffix = self._db_suffix() if report is not None and self.db_panel is not None else ""
            if isinstance(error, retention.RetentionError):
                if isinstance(error, retention.RetentionReadError):
                    self.inventory_roles = {}
                    self.inventory_read_error = str(error)
                    self._render_inventory()
                    self.alert_read_failed(error)
                    if self.cache_selection is not None:
                        self.cache_authorized = False
                        self.mode_label.configure(text=cached.LABEL + ' · Reselect required', foreground='#b00020')
                self._set_status(i18n.Message("st_maintenance_failed", cloud=CLOUD_NOT_VERIFIED))
                messagebox.showerror('Local History', str(error), parent=self.root)
            elif isinstance(error, upgrade.UpgradeError):
                # Refused or rolled back: the database stays schema 1 and every loaded file stays as it was.
                self._set_status(i18n.Message("st_upgrade_failed", cloud=CLOUD_NOT_VERIFIED))
                messagebox.showerror('Database upgrade', str(error), parent=self.root)
            elif error is not None:
                if isinstance(error, cached.CacheError) and self.cache_selection is not None:
                    self.cache_authorized = False
                    self.mode_label.configure(text=cached.LABEL + " · Reselect required", foreground="#b00020")
                if isinstance(error, cached.CacheReadError):
                    self.inventory_roles = {}
                    self.inventory_read_error = str(error)
                    self._render_inventory()
                    self.alert_read_failed(error)
                    db_suffix = self._db_suffix()
                # Unexpected failure of the whole action: nothing loaded can be trusted, so clear everything.
                for role in ROLES:
                    self.file_view[role]["loading"] = False
                    self._clear_role(role)
                self.invalidate()
                self._set_status(i18n.Message("st_failed_reload", db=db_suffix))
                messagebox.showerror(self.t("title_failed"),
                                     self.text(i18n.Join((i18n.Message("err_unexpected", error=str(error)), sync_note))),
                                     parent=self.root)
            else:
                # A callback returns text when a file failed; it has already cleared only that file.
                problem = callback(data)
                if self.closed:
                    return
                if job != self.job:  # a modal confirmation may have started a new, guarded worker
                    self.poll_id = self.root.after(50, self._poll)
                    return
                if problem:
                    self.invalidate()
                    self._set_status(i18n.Message("st_failed_card", db=db_suffix))
                    messagebox.showerror(self.t("title_failed"), self.text(i18n.Join((problem, sync_note))),
                                         parent=self.root)
                else:
                    # Every value is a snapshot of this job's outcome: re-rendering never re-derives it.
                    if label in MAINTENANCE_JOBS:
                        status = i18n.Message("st_maintenance", message=i18n.Message(self.maintenance_message),
                                              cloud=CLOUD_NOT_VERIFIED)
                    elif self.cache_selection is not None:
                        status = i18n.Message("st_cache_mode", label=cached.LABEL)
                    elif self.result and not self.result_current:
                        status = i18n.Message("st_outdated_during_check", outdated=binding.OUTDATED,
                                              attempts=self.result_binding.attempts)
                    elif self.result:
                        status = i18n.Message("st_checked", count=len(self.result.rows), seconds=f"{elapsed:.2f}")
                    elif label == "启动检查" and self.stock_book is None and self.bom_book is None:
                        status = i18n.Message("st_ready")
                    else:
                        materials = sum(len(s.materials) for s in self.stock_book.stock_sheets) if self.stock_book else 0
                        products = len(self.bom_book.products) if self.bom_book else 0
                        status = i18n.Message("st_loaded", materials=materials, products=products)
                    self._set_status(i18n.Join((status, db_suffix), ""))
                    if sync_note:
                        # The Excel result is valid; only the local database copy could not be updated.
                        messagebox.showwarning(self.t("db_title"), self.text(sync_note), parent=self.root)
        self.poll_id = self.root.after(50, self._poll)

    def browse(self, role):
        path = filedialog.askopenfilename(parent=self.root, title=self.t("title_choose_stock" if role == "stock" else "title_choose_bom"),
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
            self._set_product_values(())
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
            detail = i18n.Message("err_sheet_gone") if isinstance(error, SheetGone) else str(error)
            return i18n.Message("err_role_failed", role=i18n.Message("role_" + role), error=detail)
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
        errors = [e for e in errors if e]
        return i18n.Join(errors) if errors else ""

    def load_file(self, role, path):
        if self.busy:
            return
        self._leave_cache(clear=True)
        (self.stock_path if role == "stock" else self.bom_path).set(path)
        self.file_view[role]["loading"] = True
        self._clear_role(role)
        self._start(lambda: {role: self._read(role, path)}, self._loaded, "读取所选文件", sync=({role: path}, "selected"))

    def _stock_loaded(self, book, previous=""):
        self.stock_book = book
        names = tuple(s.name for s in book.stock_sheets)
        self._set_sheet_values(names)
        if len(names) > 1:
            self.stock_sheet_frame.grid()
        else:
            self.stock_sheet_frame.grid_remove()
        self.stock_name.set(previous if previous in names else names[0] if len(names) == 1 else "")
        self._detail_text("库存表头识别：" + "; ".join(f"{s.name!r} 第{s.header_row}行 / {len(s.materials)}条材料" for s in book.stock_sheets)
                          + "\n" + "\n".join(book.notes))

    def _bom_loaded(self, book, previous=""):
        self.bom_book = book
        self._set_product_values(tuple(p.display_name for p in book.products))
        selected = next((p for p in book.products if p.sheet_name == previous), None)
        self.product_text.set(selected.display_name if selected else "")
        self._detail_text(f"识别 {len(book.products)} 个 Product ID（来自含材料的 BOM Sheet）。请输入搜索并选择其中一个。\n" + "\n".join(book.notes))

    def _search(self, _event=None, reset=False):
        if self.bom_book is not None:
            products = self.bom_book.products if reset or select_product(self.bom_book.products, self.product_text.get()) else search_products(self.bom_book.products, self.product_text.get())
            self._set_product_values(tuple(p.display_name for p in products))

    def _pick(self, _event=None):
        """Enter in the Product ID box: take the only candidate, or open the list when there are several."""
        if self.bom_book is None or select_product(self.bom_book.products, self.product_text.get()):
            return
        matches = search_products(self.bom_book.products, self.product_text.get())
        self._set_product_values(tuple(p.display_name for p in matches))
        box = _event.widget if _event is not None and _event.widget in self.product_boxes() else self.product_combo
        if len(matches) == 1:
            self.product_text.set(matches[0].display_name)
            box.icursor("end")
        elif matches:
            box.event_generate("<Down>")

    def reload_files(self, force=True, trigger="reload", label="强制重新读取"):
        if self.busy:
            return
        self._leave_cache()
        paths = {"stock": self.stock_path.get(), "bom": self.bom_path.get()}
        product = select_product(self.bom_book.products, self.product_text.get()) if self.bom_book else None
        previous = {"stock": self.stock_name.get(), "bom": product.sheet_name if product else ""}
        if not any(paths.values()):
            messagebox.showerror(self.t("title_no_files"), self.t("err_no_files"), parent=self.root)
            return
        self._start(lambda: {role: self._read(role, path, force=force) for role, path in paths.items() if path},
                    lambda outcomes: self._loaded(outcomes, previous), label,
                    sync=({role: path for role, path in paths.items() if path}, trigger))

    def check(self, trigger="check"):
        if self.busy:
            return
        try:
            try:
                production_quantity(self.quantity_text.get())
            except ValueError as exc:  # the rule and its own wording stay in checker.core; shown as the detail
                raise InputProblem(i18n.Message("err_quantity", detail=str(exc))) from exc
            if self.stock_book is None or self.bom_book is None:
                raise InputProblem(i18n.Message("err_files_first"))
            product = select_product(self.bom_book.products, self.product_text.get())
            if product is None:
                matches = search_products(self.bom_book.products, self.product_text.get()) if self.product_text.get().strip() else ()
                self._set_product_values(tuple(p.display_name for p in matches or self.bom_book.products))
                raise InputProblem(i18n.Message(
                    "err_product", text=self.product_text.get(),
                    matches=i18n.Message("err_product_matches", count=len(matches)) if matches else
                    i18n.Message("err_product_none")))
            if not any(s.name == self.stock_name.get() for s in self.stock_book.stock_sheets):
                raise InputProblem(i18n.Message("err_sheet"))
        except InputProblem as exc:
            self.invalidate()
            messagebox.showerror(self.t("title_input"), self.text(exc.message), parent=self.root)
            return
        if trigger == "check":
            self.show_page("check")  # the result appears on the shortage check page; Refresh stays where it is
        paths = {"stock": self.stock_path.get(), "bom": self.bom_path.get()}
        selected = {"stock": self.stock_name.get(), "bom": product.sheet_name}
        count = production_quantity(self.quantity_text.get())
        if self.cache_selection is not None:
            self._check_cached(selected, count)
            return
        def action():
            outcomes = {role: self._read(role, path) for role, path in paths.items()}
            stock, bom = outcomes["stock"][0], outcomes["bom"][0]
            if stock is None or bom is None:
                return outcomes, None
            sheet = self.service.find_stock_sheet(stock, selected["stock"])
            chosen = self.service.find_product(bom, selected["bom"])
            if sheet is None:
                outcomes["stock"] = (None, (), SheetGone(), False)
            if chosen is None:
                outcomes["bom"] = (None, (), SheetGone(), False)
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
        self.last_check = dict(result=result, product=result.product.display_name, quantity=result.production_count,
                               time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                               counts={c: result.category_count(c) for c in (SHORTAGE, EXCEPTION, ENOUGH)})
        if isinstance(bound, cached.CacheBinding):
            self.summary.set(cached.LABEL + "\n" + self.summary.get())
        elif bound is not None and not bound.current:
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
            messagebox.showerror(self.t("title_no_export"), self.t("err_no_result"), parent=self.root)
            return
        if not self._verify_export_sources():
            return
        result, bound, job = self.result, self.result_binding, self.job
        name = default_filename(self.result.product.display_name, self.result.production_count, datetime.now())
        if isinstance(bound, cached.CacheBinding):
            name = 'UNVERIFIED_' + name
        # No overwrite prompt: an existing file is never replaced, a numbered name is used instead.
        path = filedialog.asksaveasfilename(parent=self.root, title=self.t("title_export"), defaultextension=".xlsx",
                                           filetypes=[("Excel (.xlsx)", "*.xlsx")], initialfile=name, confirmoverwrite=False)
        if path:
            if self.result is not result or self.result_binding is not bound or self.job != job:
                messagebox.showerror(self.t("title_changed"), self.t("err_result_changed"), parent=self.root)
                return
            self.write_export(path)

    def _refuse_outdated_export(self, detail=""):
        if isinstance(self.result_binding, cached.CacheBinding):
            messagebox.showerror(binding.OUTDATED, self.t("err_cache_outdated", detail=detail), parent=self.root)
            return
        messagebox.showerror(binding.OUTDATED, self.t("err_outdated", detail="\n" + detail if detail else ""),
                             parent=self.root)

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
        self._set_status(i18n.Message("st_export_outdated", outdated=binding.OUTDATED, detail=status_detail,
                                      cloud=CLOUD_NOT_VERIFIED))
        self._refuse_outdated_export(detail)

    def _verify_export_sources(self):
        if isinstance(self.result_binding, cached.CacheBinding):
            try:
                if not self.result_exportable:
                    raise cached.CacheError('Cached result is outdated or its selected sources changed.')
                cached.verify(self.result_binding.snapshot)
            except cached.CacheError as exc:
                self._cache_export_failed(exc)
                return False
            return True
        if not self.result_current:
            self._refuse_outdated_export()
            return False
        try:
            binding.verify_export(self.result_binding, self._export_sources())
        except binding.ExportVerificationError as exc:
            self._export_verification_failed(exc)
            return False
        return True

    def _cache_export_failed(self, exc):
        self.cache_authorized = False
        self.mode_label.configure(text=cached.LABEL + " · Reselect required", foreground="#b00020")
        self.result_binding = replace(self.result_binding, valid=False)
        self._show_result_state()
        self.export_feedback.grid_remove()
        if isinstance(exc, cached.CacheReadError):
            self.inventory_roles = {}
            self.inventory_read_error = str(exc)
            self._render_inventory()
            self.alert_read_failed(exc)
        if not self.summary.get().startswith(binding.OUTDATED):
            self.summary.set(binding.OUTDATED + '\n' + self.summary.get())
        detail = '\n'.join(x for x in (str(exc), getattr(exc, 'cleanup_warning', '')) if x)
        self._set_status(i18n.Message("st_cache_export_failed", outdated=binding.OUTDATED, label=cached.LABEL,
                                      cloud=CLOUD_NOT_VERIFIED))
        self._refuse_outdated_export(detail)

    def write_export(self, path):
        """Save the current result as a new .xlsx. Returns the path written, or None if refused or failed."""
        if self.busy or self.result is None or self.stock_book is None or self.bom_book is None:
            return None
        if not self.result_exportable:
            if isinstance(self.result_binding, cached.CacheBinding):
                self._cache_export_failed(cached.CacheError('Cached result or selected sources are outdated.'))
            else:
                self._refuse_outdated_export()
            return None
        try:
            if isinstance(self.result_binding, cached.CacheBinding):
                written = cached.save(path, self.result, self.stock_book, self.bom_book, self.result_binding)
            else:
                written = save_verified_report(path, self.result, self.stock_book, self.bom_book,
                                               self.result_binding, self._export_sources())
        except cached.CacheError as exc:
            self._cache_export_failed(exc)
            return None
        except binding.ExportVerificationError as exc:
            self._export_verification_failed(exc)
            return None
        except (ReportError, OSError) as exc:
            detail = "\n".join(part for part in (str(exc), getattr(exc, "cleanup_warning", "")) if part)
            message = (i18n.Message("err_write", path=path, detail=detail) if isinstance(exc, OSError) else
                       i18n.Message("err_export", detail=detail))
            messagebox.showerror(self.t("title_export_failed"), self.text(message), parent=self.root)
            return None
        self.export_path.set(str(written))
        self.hide_details()
        self.export_feedback.grid()
        self._resize()
        self._set_status(i18n.Message("st_cache_exported", label=cached.LABEL)
                         if isinstance(self.result_binding, cached.CacheBinding) else i18n.Message("st_exported"))
        return written

    def close(self):
        self.closed = True
        self.cancelled.set()
        if self.assistant is not None:
            self.assistant.close()
        if self.history_window is not None:
            self.history_window.close()
        if self.analytics_window is not None:
            self.analytics_window.close()
        if self.alert_runner is not None:
            self.alert_runner.close()  # a running evaluation finishes its transaction; nothing is delivered
        if self.alerts_window is not None:
            self.alerts_window.close()
        if self.daily_window is not None:
            self.daily_window.close()
        self.root.after_cancel(self.poll_id)
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
        self.root.destroy()
