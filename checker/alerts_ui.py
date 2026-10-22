"""M3.2C Stock Alerts window: stored alerts and observed stock changes from synchronised data. Read-only display.

Two tabs share the Storage Sheet and Material ID filters:
- Alerts: the de-duplicated alerts of the files that are current in the database (alerts of other source files are
  counted and can be shown; they are never presented as recovered).
- Observed Changes: differences between synchronised versions of the current Storage file in the last 30/60/90 days
  (historical observations, not consumption, not a production-order shortage).

A session line above both tabs always says whether THIS session has re-checked the alerts; until the owning
application confirms a verified evaluation of its current generation, everything shown is "not re-checked".
Reads run on one background thread per kind (plus one pending request); only the Tk thread touches widgets, and
nothing is applied after the window is closed. Cloud Not Verified is permanent; nothing here says stock is current.
"""
from __future__ import annotations

from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk

from . import alerts
from .core import display, normalize_code
from .history_ui import side_text, signed
from .inventory_db import decode, parse_stamp
from .presentation import AMBER, BG, INK, MUTED, work_area

BANNER = "STOCK ALERTS · From synchronised Excel data · Cloud Not Verified · Thresholds and units pending business confirmation"
CAVEATS = ("OUT_OF_STOCK ≠ order shortage · LOW_STOCK is a trial · Not in stock master = unknown, not 0 · "
           "Blank ≠ 0 · Observed Change ≠ Actual Consumption")
RULES = ("Rules: OUT_OF_STOCK = recorded 0, not a proven order shortage. LOW_STOCK is a trial (LIVE STOCK < threshold of "
         "the same row; equal is not low; the shortfall is not a production requirement). Not in stock master = stock "
         "unknown, not 0. Blank ≠ 0. Threshold 0 is kept as 0 and not interpreted. Duplicate IDs are never added. Values "
         "are never converted. Observed Change ≠ Actual Consumption. M2 CHECK rules are unchanged.")
ALL, ALL_SHEETS = "All types", "All Sheets"
LABELS = {alerts.OUT_OF_STOCK: "OUT_OF_STOCK", alerts.LOW_STOCK: "LOW_STOCK",
          alerts.NOT_IN_MASTER: "NOT IN STOCK MASTER", alerts.DATA_ISSUE: "DATA_ISSUE",
          alerts.NOT_CONFIGURED: "THRESHOLD_NOT_CONFIGURED"}
CHANGE_TYPES = ("All changes", "QUANTITY_CHANGED", "ADDED", "REMOVED", "VALIDITY_CHANGED", "DUPLICATE_CHANGED")
PAGE = 200
DETAILS_HINT = "Select a row to see its source file, rows, Rack/Level, raw values and versions."


def local(text, pattern="%Y-%m-%d %H:%M"):
    moment = parse_stamp(text)
    return moment.astimezone().strftime(pattern) if moment else "—"


def raw_text(pair, status=None):
    """A stored [kind, text] value exactly as read; blank shown as (blank), never as 0."""
    if pair is None:
        return "—"
    value = decode(*pair)
    if value is None or (isinstance(value, str) and not value.strip()):
        return "(blank)"
    text = display(value)
    return text if status in (None, "VALID") else f"{text} ({status})"


class AlertsWindow:
    def __init__(self, master, owner):
        """owner: the CheckerApp (database path, session verification state, evaluation request, upgrade)."""
        self.owner = owner
        self.database = str(owner.inventory.db_path)
        self.events = queue.Queue()
        self.closed = False
        self.loading = {"alerts": False, "changes": False}
        self.pending = {"alerts": False, "changes": False}
        self.state = None
        self.changes = None
        self.visible = {"alerts": (), "changes": ()}
        self.shown = {"alerts": 0, "changes": 0}
        self.top = top = tk.Toplevel(master)
        top.title("Stock Alerts — synchronised data")
        left, upper, width, height = work_area(top)
        top.geometry(f"{min(1240, width - 64)}x{min(740, height - 80)}+{left + 48}+{upper + 48}")
        top.minsize(min(900, width - 64), min(540, height - 80))
        top.configure(background=BG)
        top.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self.poll_id = top.after(50, self._poll)
        self.show_session_state()
        self.reload()

    # ------------------------------------------------------------------ layout
    def _build(self):
        outer = ttk.Frame(self.top, padding=(14, 8))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(5, weight=1)
        self.banner = ttk.Label(outer, text=BANNER, font=("Segoe UI", 10, "bold"), foreground="#b00020")
        self.banner.grid(row=0, sticky="w")
        self.caveats = ttk.Label(outer, text=CAVEATS, font=("Segoe UI", 9), foreground=MUTED)
        self.caveats.grid(row=1, sticky="ew", pady=(2, 4))
        self.session = ttk.Label(outer, text="", font=("Segoe UI", 9, "bold"))
        self.session.grid(row=2, sticky="ew", pady=(0, 4))
        outer.bind("<Configure>", lambda e: [w.configure(wraplength=max(200, e.width - 30))
                                             for w in (self.banner, self.caveats, self.session)])
        basis = ttk.Frame(outer)
        basis.grid(row=3, sticky="ew")
        basis.columnconfigure(0, weight=1)
        self.basis = tk.Text(basis, height=3, wrap="word", font=("Segoe UI", 9), relief="flat", background="white",
                             foreground=INK, padx=6, pady=3, state="disabled")
        self.basis.grid(row=0, column=0, sticky="ew")
        scroll = ttk.Scrollbar(basis, orient="vertical", command=self.basis.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.basis.configure(yscrollcommand=scroll.set)

        filters = ttk.Frame(outer)
        filters.grid(row=4, sticky="ew", pady=(6, 4))
        ttk.Label(filters, text="Storage Sheet", font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        self.sheet_filter = tk.StringVar(value=ALL_SHEETS)
        self.sheet_combo = ttk.Combobox(filters, textvariable=self.sheet_filter, state="readonly", width=24,
                                        values=(ALL_SHEETS,))
        self.sheet_combo.pack(side="left")
        self.sheet_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())
        ttk.Label(filters, text="Material ID contains", font=("Segoe UI", 9)).pack(side="left", padx=(12, 6))
        self.material_filter = tk.StringVar()
        self.material_entry = ttk.Entry(filters, textvariable=self.material_filter, width=18)
        self.material_entry.pack(side="left")
        self.material_entry.bind("<KeyRelease>", lambda _e: self._apply_filters())
        ttk.Button(filters, text="Close", command=self.close, padding=(10, 1)).pack(side="right")
        self.evaluate_button = ttk.Button(filters, text="Re-evaluate", command=self.evaluate, padding=(10, 1))
        self.evaluate_button.pack(side="right", padx=(0, 8))
        self.upgrade_button = ttk.Button(filters, text="Upgrade database…", command=self.upgrade, padding=(10, 1))

        self.tabs = ttk.Notebook(outer)
        self.tabs.grid(row=5, sticky="nsew")
        self.trees, self.count_labels, self.more_buttons = {}, {}, {}
        # Alerts tab
        alerts_tab = ttk.Frame(self.tabs, padding=4)
        alerts_tab.columnconfigure(0, weight=1)
        alerts_tab.rowconfigure(1, weight=1)
        bar = ttk.Frame(alerts_tab)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ttk.Label(bar, text="Type", font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        self.type_filter = tk.StringVar(value=ALL)
        self.type_combo = ttk.Combobox(bar, textvariable=self.type_filter, state="readonly", width=28,
                                       values=(ALL, *(LABELS[t] for t in alerts.TYPES)))
        self.type_combo.pack(side="left")
        self.type_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())
        self.show_resolved = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show resolved", variable=self.show_resolved,
                        command=lambda: self.reload("alerts")).pack(side="left", padx=(12, 0))
        self.show_other = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show other source files", variable=self.show_other,
                        command=self._apply_filters).pack(side="left", padx=(12, 0))
        self._table(alerts_tab, "alerts", [
            ("type", "Type", 160), ("subtype", "Issue", 150), ("material", "Material ID", 120),
            ("description", "Description", 160), ("sheet", "Storage Sheet", 120), ("row", "Row(s)", 100),
            ("stock", "LIVE STOCK (raw)", 120), ("threshold", "Threshold (raw)", 130),
            ("shortfall", "Shortfall (trial)", 110), ("file", "Source File", 160), ("note", "Note", 380),
            ("first", "First seen", 115), ("last", "Last seen", 115), ("status", "Status", 150)])
        self.tabs.add(alerts_tab, text="Alerts")
        # Observed Changes tab
        changes_tab = ttk.Frame(self.tabs, padding=4)
        changes_tab.columnconfigure(0, weight=1)
        changes_tab.rowconfigure(1, weight=1)
        bar = ttk.Frame(changes_tab)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ttk.Label(bar, text="Change", font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        self.change_filter = tk.StringVar(value=CHANGE_TYPES[0])
        self.change_combo = ttk.Combobox(bar, textvariable=self.change_filter, state="readonly", width=22,
                                         values=CHANGE_TYPES)
        self.change_combo.pack(side="left")
        self.change_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())
        self.days = tk.IntVar(value=30)
        for days in alerts.CHANGE_RANGES:
            ttk.Radiobutton(bar, text=f"{days} days", value=days, variable=self.days,
                            command=lambda: self.reload("changes")).pack(side="left", padx=(10, 0))
        self.change_note = ttk.Label(bar, text="Observed Change ≠ Actual Consumption", font=("Segoe UI", 9),
                                     foreground=MUTED)
        self.change_note.pack(side="left", padx=(12, 0))
        self._table(changes_tab, "changes", [
            ("after", "Observed at (local)", 125), ("sheet", "Sheet", 110), ("material", "Material ID", 120),
            ("type", "Change", 140), ("before_at", "Before (local)", 125), ("before", "Before stock", 130),
            ("now", "After stock", 130), ("diff", "Observed difference", 130), ("note", "Note", 380)])
        self.tabs.add(changes_tab, text="Observed Changes")

        self.details = tk.Text(outer, height=2, wrap="word", font=("Segoe UI", 9), relief="flat", background=BG,
                               foreground=MUTED, padx=0, pady=2, state="disabled")
        self.details.grid(row=6, sticky="ew", pady=(6, 0))
        self.status = tk.StringVar(value="Loading stock alerts… · Cloud Not Verified")
        self.status_label = ttk.Label(outer, textvariable=self.status, font=("Segoe UI", 9), foreground=MUTED)
        self.status_label.grid(row=7, sticky="w", pady=(4, 0))
        self._set_text(self.details, DETAILS_HINT)
        self.top.bind("<Configure>", self._fit, add="+")

    def _fit(self, event=None):
        """Small or scaled windows: the tables keep their room. The basis and details boxes give up a line each (both
        stay scrollable) and return when there is space again; the thresholds differ to avoid flapping."""
        if event is not None and event.widget is not self.top:
            return
        tables = self.tabs.winfo_height()
        line = self.basis.tk.call("font", "metrics", self.basis.cget("font"), "-linespace")
        if int(self.basis.cget("height")) == 3 and tables < 12 * line:
            self.basis.configure(height=2)
            self.details.configure(height=1)
        elif int(self.basis.cget("height")) == 2 and tables > 16 * line:
            self.basis.configure(height=3)
            self.details.configure(height=2)

    def _table(self, parent, name, columns):
        tree = ttk.Treeview(parent, columns=[c[0] for c in columns], show="headings", height=5, selectmode="browse")
        for ident, label, width in columns:
            tree.heading(ident, text=label, anchor="w")
            # never squeezed: a narrow window scrolls sideways
            tree.column(ident, width=width, minwidth=width, stretch=ident in ("note", "description"))
        tree.grid(row=1, column=0, sticky="nsew")
        y = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        y.grid(row=1, column=1, sticky="ns")
        x = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
        x.grid(row=2, column=0, sticky="ew")
        tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        tree.tag_configure("attention", background=AMBER)
        tree.tag_configure("muted", foreground=MUTED)
        tree.bind("<<TreeviewSelect>>", lambda _e, n=name: self._show_row(n))
        footer = ttk.Frame(parent)
        footer.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        footer.columnconfigure(0, weight=1)
        self.count_labels[name] = ttk.Label(footer, text="", font=("Segoe UI", 9), foreground=MUTED)
        self.count_labels[name].grid(row=0, column=0, sticky="w")
        self.more_buttons[name] = ttk.Button(footer, text="Show more", padding=(8, 1),
                                             command=lambda n=name: self._render_page(n))
        self.more_buttons[name].grid(row=0, column=1, sticky="e")
        self.more_buttons[name].grid_remove()
        self.trees[name] = tree

    @property
    def tree(self):
        return self.trees["alerts"]

    # ------------------------------------------------------------------ loading (bounded: one read per kind)
    def reload(self, kind=None):
        for name in ((kind,) if kind else ("alerts", "changes")):
            self._load(name)

    def _load(self, kind):
        if self.closed:
            return
        if self.loading[kind]:
            self.pending[kind] = True
            return
        self.loading[kind] = True
        include, days = self.show_resolved.get(), self.days.get()

        def worker():
            try:
                data = (alerts.load_state(self.database, include_resolved=include) if kind == "alerts"
                        else alerts.observed_changes_view(self.database, days))
                error = None
            except Exception as exc:
                data, error = None, exc
            self.events.put((kind, data, error))
        threading.Thread(target=worker, daemon=True, name=f"m32c-alerts-{kind}").start()

    def _poll(self):
        if self.closed:
            return
        while True:
            try:
                kind, data, error = self.events.get_nowait()
            except queue.Empty:
                break
            self.loading[kind] = False
            if self.pending[kind]:
                self.pending[kind] = False
                self._load(kind)  # a newer request arrived: show that instead of this result
            elif kind == "alerts":
                self._alerts_loaded(data, error)
            else:
                self._changes_loaded(data, error)
        self.poll_id = self.top.after(50, self._poll)

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.top.after_cancel(self.poll_id)
        except tk.TclError:
            pass
        try:
            self.top.destroy()
        except tk.TclError:
            pass
        if self.owner.alerts_window is self:
            self.owner.alerts_window = None

    def lift(self):
        self.top.deiconify()
        self.top.lift()
        self.show_session_state()
        self.reload()

    # ------------------------------------------------------------------ actions
    def evaluate(self):
        self.owner.request_alerts("manual")
        self.status.set("Evaluation requested · Cloud Not Verified")

    def upgrade(self):
        self.owner.preview_upgrade()

    # ------------------------------------------------------------------ rendering
    def show_session_state(self):
        """The owner's current verification overrides whatever was stored."""
        if self.closed:
            return
        if self.owner.alert_current:
            self.session.configure(text="Re-checked in this session: the alerts of the current files come from a "
                                        "verified evaluation of the files this program has just checked.",
                                   foreground="#3b715e")
        else:
            prefix = ("DATABASE READ FAILED · " if self.owner.alert_read_error is not None else "")
            self.session.configure(text=prefix + "NOT RE-CHECKED IN THIS SESSION — " +
                                        (self.owner.alert_reason or "unknown") +
                                        ". The alerts below are stored results of earlier evaluations and may be out "
                                        "of date; nothing is marked recovered until a verified evaluation.",
                                   foreground="#b00020")

    def _set_text(self, widget, text, error=False):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.configure(state="disabled", foreground="#b00020" if error else
                         (MUTED if widget is self.details else INK))

    def _alerts_loaded(self, state, error):
        self.state = None
        if error is not None:
            # A failed read is a database read failure for the whole session: verification and its evidence are
            # discarded (the owner re-renders this window's session line), nothing stored is deleted.
            self.owner.alert_read_failed(error)
            self.visible["alerts"] = ()
            self._clear("alerts")
            self._set_text(self.basis, "STOCK ALERTS COULD NOT BE READ — nothing is shown. Earlier alerts were "
                                       f"cleared from this window, not from the database.\n{error}", error=True)
            self.status.set("Read failed · no alerts shown · Cloud Not Verified")
            return
        self.state = state
        self.owner.alert_read_ok()
        self.show_session_state()
        if state.schema < alerts.ALERT_SCHEMA_VERSION:
            self.upgrade_button.pack(side="right", padx=(0, 8))
            self._set_text(self.basis, f"Stock alerts need a one-time upgrade of the local database (schema "
                                       f"{state.schema} → {alerts.ALERT_SCHEMA_VERSION}). Nothing changes until you "
                                       "confirm the preview; a verified backup is made first. All other functions work "
                                       "without it.")
            self.visible["alerts"] = ()
            self._clear("alerts")
            self.status.set("Upgrade required · Cloud Not Verified")
            return
        self.upgrade_button.pack_forget()
        self._set_text(self.basis, self._basis_text(state))
        self._refresh_sheets()
        self._apply_filters("alerts")
        self.status.set(f"{sum(state.active_counts.values())} active alerts for the current files"
                        f"{f' · {state.other_sources_active} of other source files' if state.other_sources_active else ''}"
                        " · from synchronised data · Cloud Not Verified")

    def _changes_loaded(self, view, error):
        self.changes = None
        if error is not None:
            self.owner.alert_read_failed(error)
            self.visible["changes"] = ()
            self._clear("changes")
            self.count_labels["changes"].configure(text=f"Observed changes could not be read; none shown: {error}",
                                                   foreground="#b00020")
            return
        self.changes = view
        self._refresh_sheets()
        self._apply_filters("changes")

    def _basis_text(self, state):
        lines = [RULES]
        done, latest = state.latest_completed, state.latest
        lines.append(f"Current files in the database: Storage {state.storage_path or '—'} · BOM {state.bom_path or '—'}.")
        if done is None:
            lines.append("No verified evaluation of these files yet. Alerts are evaluated automatically after both "
                         "Excel files are checked successfully (start-up, Refresh Excel, CHECK), from synchronised data.")
        else:
            s = done["summary"]
            stock, bom = s.get("stock_version", {}), s.get("bom_version", {})
            lines.append(f"Last verified evaluation of these files: #{done['id']} at {local(done['finished_at'])} — "
                         f"Storage v{stock.get('id')} (file modified {local(stock.get('source_modified_at'))}), "
                         f"BOM v{bom.get('id')} (file modified {local(bom.get('source_modified_at'))}). "
                         f"Storage Sheet scope: {', '.join(done['sheet_scope']) or '—'}. Cloud Not Verified.")
            for name, info in s.get("sheets", {}).items():
                t = info.get("threshold", {})
                if t.get("state") == "FOUND":
                    threshold = f"threshold column {t.get('column')} '{t.get('header')}'"
                elif t.get("state") == "AMBIGUOUS":
                    threshold = ("several threshold columns " +
                                 ", ".join(f"{c} '{h}'" for c, h in t.get("candidates", [])) + " — none chosen")
                elif t.get("state") == "NOT_CAPTURED":
                    threshold = "thresholds not captured for this version (Refresh Excel) — threshold checks not done"
                else:
                    threshold = "no MIN QTY / MIIN QTY column — threshold checks not done"
                c = info.get("counts", {})
                issues = ", ".join(f"{k} {v}" for k, v in info.get("data_issue_subtypes", {}).items())
                lines.append(
                    f"Sheet '{name}' ({info.get('storage_rows')} Storage rows; {threshold}): "
                    f"OUT_OF_STOCK {c.get(alerts.OUT_OF_STOCK, 0)} · LOW_STOCK {c.get(alerts.LOW_STOCK, 0)} · "
                    f"Not in stock master {info.get('missing_distinct_ids', 0)} distinct IDs / "
                    f"{info.get('missing_bom_rows', 0)} BOM rows / {info.get('missing_products', 0)} products · "
                    f"DATA_ISSUE {c.get(alerts.DATA_ISSUE, 0)}{f' ({issues})' if issues else ''} · "
                    f"THRESHOLD_NOT_CONFIGURED {c.get(alerts.NOT_CONFIGURED, 0)}")
            lines.append(f"BOM: {s.get('bom_products')} product Sheets, {s.get('bom_rows')} rows, "
                         f"{s.get('bom_distinct_ids')} distinct IDs; {s.get('bom_rows_without_usable_id')} rows without "
                         "a usable ID were not checked.")
        if latest is not None and (done is None or latest["id"] != done["id"]):
            reason = latest.get("error_message") or "the Excel files were not both verified"
            lines.insert(2, f"Latest evaluation attempt #{latest['id']} at {local(latest['finished_at'])} was "
                            f"{latest['outcome']}: {reason}. It changed no alert.")
        if state.other_sources_active:
            lines.append(f"{state.other_sources_active} active alerts belong to other source files: they were not "
                         "re-checked and are not recovered (Show other source files).")
        if state.total_rows > len(state.rows):
            lines.append(f"Only the first {len(state.rows)} of {state.total_rows} alerts were loaded.")
        return "\n".join(lines)

    def _refresh_sheets(self):
        names = set()
        if self.state is not None:
            names.update(r.stock_sheet for r in self.state.rows)
        if self.changes is not None:
            names.update(c.sheet for _key, c in self.changes.rows)
        self.sheet_combo.configure(values=(ALL_SHEETS, *sorted(names)))

    def _matches(self, sheet, key):
        wanted_sheet, text = self.sheet_filter.get(), normalize_code(self.material_filter.get())
        return (wanted_sheet == ALL_SHEETS or sheet == wanted_sheet) and (not text or text in (key or ""))

    def _apply_filters(self, kind=None):
        for name in ((kind,) if kind else ("alerts", "changes")):
            if name == "alerts":
                if self.state is None:
                    continue
                wanted = self.type_filter.get()
                rows = tuple(r for r in self.state.rows
                             if (wanted == ALL or LABELS[r.alert_type] == wanted)
                             and (r.in_scope or self.show_other.get() or r.status == alerts.RESOLVED)
                             and self._matches(r.stock_sheet, r.material_key))
            else:
                if self.changes is None:
                    continue
                wanted = self.change_filter.get()
                rows = tuple((key, c) for key, c in self.changes.rows
                             if (wanted == CHANGE_TYPES[0] or c.change_type == wanted) and self._matches(c.sheet, key))
            self.visible[name] = rows
            self._clear(name)
            self._render_page(name)

    def _clear(self, name):
        tree = self.trees[name]
        tree.delete(*tree.get_children())
        self.shown[name] = 0
        self.more_buttons[name].grid_remove()
        self.count_labels[name].configure(text="", foreground=MUTED)
        self._set_text(self.details, DETAILS_HINT)

    def _render_page(self, name):
        rows, start = self.visible[name], self.shown[name]
        for index in range(start, min(start + PAGE, len(rows))):
            values, tags = (self._alert_values(rows[index]) if name == "alerts" else self._change_values(*rows[index]))
            self.trees[name].insert("", "end", iid=str(index), values=values, tags=tags)
        self.shown[name] = min(start + PAGE, len(rows))
        if name == "alerts":
            total = self.state.total_rows if self.state else 0
            loaded = len(self.state.rows) if self.state else 0
        else:
            total = self.changes.total if self.changes else 0
            loaded = len(self.changes.rows) if self.changes else 0
        text = f"Showing {self.shown[name]} of {len(rows)} (filtered from {loaded} loaded"
        text += f"; {total} in total — narrow the filters)" if total > loaded else ")"
        if name == "changes" and self.changes is not None:
            text += (f" · {self.changes.days} days from {local(self.changes.window_start)} · current Storage file only"
                     + ("".join(" · " + n for n in self.changes.notes)))
        self.count_labels[name].configure(text=text)
        if self.shown[name] < len(rows):
            self.more_buttons[name].grid()
        else:
            self.more_buttons[name].grid_remove()

    @staticmethod
    def _alert_values(r):
        d = r.detail
        subtype = r.subtype if r.alert_type == alerts.DATA_ISSUE else ""
        shortfall = "—"
        if r.alert_type == alerts.NOT_IN_MASTER:
            occurrences = d.get("occurrences", [])
            description = raw_text(occurrences[0]["description"]) if occurrences else "—"
            rows = f"BOM: {d.get('bom_rows')} rows / {len(d.get('products', []))} products"
            stock, threshold = "unknown (not 0)", "—"
        elif "rows" in d:  # duplicate Storage ID: each row separately
            description = raw_text(d["rows"][0]["description"])
            rows = " | ".join(str(x["row"]) for x in d["rows"])
            stock = " | ".join(raw_text(x["stock"], x["stock_status"]) for x in d["rows"])
            threshold = " | ".join(raw_text(x["threshold"]) for x in d["rows"]) if d["rows"][0].get("threshold") else "—"
        elif isinstance(d.get("threshold"), dict):  # ambiguous threshold columns
            description, rows, stock = "—", "header", "—"
            threshold = ", ".join(f"{c} '{h}'" for c, h in d["threshold"].get("candidates", []))
        else:
            description = raw_text(d.get("description"))
            rows = str(d.get("row", "—"))
            stock = raw_text(d.get("stock"), d.get("stock_status"))
            threshold = (raw_text(d["threshold"], d.get("threshold_status")) +
                         f" [{d.get('threshold_header')}]") if d.get("threshold") else "—"
            if d.get("threshold_shortfall") is not None:
                shortfall = display(decode("decimal", d["threshold_shortfall"]))
        material = r.material_key or raw_text(d.get("code"))
        source = Path(d.get("storage_file") or "").name or "—"
        if r.status == alerts.RESOLVED:
            status, tags = f"RESOLVED {local(r.resolved_at)}", ("muted",)
        elif not r.in_scope:
            status, tags = "OTHER SOURCE · not re-checked", ("muted",)
        else:
            status = "ACTIVE"
            tags = ("attention",) if r.alert_type in (alerts.DATA_ISSUE, alerts.NOT_IN_MASTER) else ()
        return (LABELS[r.alert_type], subtype, material, description, r.stock_sheet, rows, stock, threshold, shortfall,
                source, d.get("note", ""), local(r.first_seen_at), local(r.last_seen_at), status), tags

    @staticmethod
    def _change_values(key, c):
        if c.difference is not None:
            difference = signed(c.difference)
        elif c.change_type == "QUANTITY_CHANGED" and c.source_switched:
            difference = "not comparable (source switch)"
        else:
            difference = "—"
        tags = ("attention",) if c.source_switched or c.change_type != "QUANTITY_CHANGED" else ()
        return (local(c.after_at), c.sheet, key, c.change_type, local(c.before_at),
                side_text(c.before_status, c.before_raw), side_text(c.after_status, c.after_raw), difference,
                c.note), tags

    def _show_row(self, name):
        tree = self.trees[name]
        selection = tree.selection()
        if not selection:
            return
        row = self.visible[name][int(selection[0])]
        if name == "changes":
            key, c = row
            text = (f"{c.change_type} · {key} · Sheet {c.sheet!r} · before {c.before_at or '—'} UTC from "
                    f"{c.before_path or '—'} · after {c.after_at} UTC from {c.after_path}\n{c.note}")
            self._set_text(self.details, text)
            return
        r, d = row, row.detail
        lines = [f"{LABELS[r.alert_type]}{' / ' + r.subtype if r.alert_type == alerts.DATA_ISSUE else ''} · "
                 f"Storage file {d.get('storage_file') or '—'} (v{r.stock_version_id}) · Sheet {r.stock_sheet!r}"
                 + (f" · BOM file {d.get('bom_file')} (v{r.bom_version_id})" if d.get("bom_file") else "")
                 + f" · first seen {r.first_seen_at} UTC · last seen {r.last_seen_at} UTC"
                 + ("" if r.in_scope else " · OTHER SOURCE: not re-checked, not recovered")]
        if r.alert_type == alerts.NOT_IN_MASTER:
            occurrences = d.get("occurrences", [])
            lines.append("Used in: " + "; ".join(
                f"{o['product']} (BOM Sheet {o['bom_sheet']!r}, row {o['row']}, QTY {raw_text(o['qty'])})"
                for o in occurrences[:60]) + (f"; … {len(occurrences) - 60} more" if len(occurrences) > 60 else ""))
        elif "rows" in d:
            lines.append("Rows: " + "; ".join(
                f"row {x['row']}: LIVE STOCK {raw_text(x['stock'], x['stock_status'])}, threshold {raw_text(x['threshold'])}"
                f", Rack {raw_text(x['rack'])}, Level {raw_text(x['level'])}" for x in d["rows"]))
        elif "row" in d:
            line = (f"Row {d['row']} · LIVE STOCK {raw_text(d.get('stock'), d.get('stock_status'))} · Rack "
                    f"{raw_text(d.get('rack'))} · Level {raw_text(d.get('level'))}")
            if d.get("threshold"):
                line += (f" · threshold {raw_text(d['threshold'], d.get('threshold_status'))} "
                         f"(column {d.get('threshold_column')} '{d.get('threshold_header')}')")
            if d.get("threshold_shortfall") is not None:
                line += f" · shortfall vs threshold {d['threshold_shortfall']} (trial, not a production requirement)"
            lines.append(line)
        lines.append(d.get("note", ""))
        self._set_text(self.details, "\n".join(lines))
