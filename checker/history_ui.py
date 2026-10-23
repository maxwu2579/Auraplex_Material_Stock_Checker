"""M4A Inventory History window: read-only historical observations for one exact Material ID.

Queries run on worker threads and return through a queue; only this module's Tk thread touches widgets. Each search
and each query carries a generation number: a slower, older response can never replace a newer one, and nothing is
delivered after the window is closed. Work is bounded per kind of request (see `_Lane`): typing or clicking fast never
starts a thread per request, a superseded query stops cooperatively, and closing the window starts nothing more. The banner "HISTORICAL OBSERVATIONS · Not current stock · Cloud Not Verified"
is permanent; this window never shows "Local Sources Verified".
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk

from . import history
from .core import display
from .inventory_db import parse_stamp
from .presentation import AMBER, BG, INK, MUTED, work_area

ALL_SHEETS = "All Sheets (shown separately)"
PAGE = 200                 # rows rendered per batch; the rest stay in memory until "Show more"
SEARCH_DELAY_MS = 250
STATUS_TEXT = {"VALID": "VALID", "BLANK": "BLANK — not 0", "INVALID": "INVALID — not converted"}
DETAILS_HINT = "Select a row to see its source file, Sheet, row and version."


def local(text, pattern="%Y-%m-%d %H:%M"):
    moment = parse_stamp(text)
    return moment.astimezone().strftime(pattern) if moment else "—"


def stock_text(status, raw):
    if status == "BLANK" or raw is None:
        return "(blank)"
    return display(raw)


def side_text(status, raw):
    """One side of an observed change, exactly as recorded."""
    if status is None:
        return "absent"
    if status == "DUPLICATE":
        return "DUPLICATE: " + " | ".join("(blank)" if v is None else display(v) for v in raw)
    value = stock_text(status, raw[0] if raw else None)
    return value if status == "VALID" else f"{value} ({STATUS_TEXT.get(status, status)})"


class _Lane:
    """Bounded background work for one kind of request (Storage Sheets, search or query); Tk thread only.

    The newest request is the only current one. It cancels the running job cooperatively and starts at once, unless an
    earlier cancelled job is still finishing; then it waits as the single pending request, which a newer request
    replaces. A lane therefore never runs more than LIMIT threads (the current job and one finishing) and holds at most
    one pending request, however fast the user types or clicks. Threads are never killed."""
    LIMIT = 2

    def __init__(self, kind, start):
        self.kind, self.start = kind, start   # start(kind, generation, action, cancel) runs one worker thread
        self.active = []                      # cancel events of the running jobs, oldest first
        self.pending = None                   # (generation, action) waiting for a free thread
        self.started = 0

    def submit(self, generation, action):
        self.cancel_running()
        self.pending = (generation, action)
        self._next()

    def finished(self, cancel):
        if cancel in self.active:
            self.active.remove(cancel)
        self._next()

    def stop(self):
        """Nothing pending starts any more; running jobs are asked to stop."""
        self.pending = None
        self.cancel_running()

    def cancel_running(self):
        for cancel in self.active:
            cancel.set()

    def _next(self):
        if self.pending is None or len(self.active) >= self.LIMIT:
            return
        (generation, action), self.pending = self.pending, None
        cancel = threading.Event()
        self.active.append(cancel)
        self.started += 1
        self.start(self.kind, generation, action, cancel)


def signed(text):
    try:
        value = Decimal(text)
    except (InvalidOperation, TypeError):
        return str(text)
    return ("+" if value > 0 else "") + display(value)


class HistoryWindow:
    def __init__(self, master, database, on_close=None):
        self.database = str(database)
        self.on_close = on_close
        self.events = queue.Queue()
        self.closed = False
        self.query_gen = self.search_gen = 0
        self.selected_key = None
        self.result = None
        self.candidates = []
        self.shown = {"records": 0, "changes": 0}
        self._search_job = None
        self.lanes = {kind: _Lane(kind, self._start) for kind in ("sheets", "search", "query")}
        self.top = top = tk.Toplevel(master)
        top.title("Inventory History — Historical Observations")
        left, upper, width, height = work_area(top)
        top.geometry(f"{min(1200, width - 64)}x{min(720, height - 80)}+{left + 40}+{upper + 40}")
        top.minsize(min(900, width - 64), min(540, height - 80))
        top.configure(background=BG)
        top.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self.poll_id = top.after(50, self._poll)
        self._run("sheets", 0, lambda: history.list_sheets(self.database))

    # ------------------------------------------------------------------ layout
    def _build(self):
        top = self.top
        outer = ttk.Frame(top, padding=(14, 10))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)
        self.banner = ttk.Label(outer, text=history.summary_line(), font=("Segoe UI", 11, "bold"), foreground="#b00020")
        self.banner.grid(row=0, sticky="w")
        self.caveats = ttk.Label(outer, text=" · ".join(history.CAVEATS), style="Muted.TLabel", foreground=MUTED,
                                 font=("Segoe UI", 9))
        self.caveats.grid(row=1, sticky="ew", pady=(2, 8))
        outer.bind("<Configure>", lambda e: self.caveats.configure(wraplength=max(200, e.width - 30)))

        # Two compact rows, so the result tables keep most of a 960×600 window:
        #   Material ID [entry] [Search]      Storage Sheet [combo]
        #   [candidates, 3 lines        ]     Range (•) 30 ( ) 60 ( ) 90   [Query]
        controls = ttk.Frame(outer)
        controls.grid(row=2, sticky="ew")
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="Material ID", font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.search_text = tk.StringVar()
        self.search_entry = ttk.Entry(controls, textvariable=self.search_text, font=("Segoe UI", 10))
        self.search_entry.grid(row=0, column=1, sticky="ew")
        self.search_entry.bind("<KeyRelease>", self._schedule_search)
        self.search_entry.bind("<Return>", lambda _e: self.search())
        ttk.Button(controls, text="Search", command=self.search, padding=(8, 1)).grid(row=0, column=2, padx=(6, 0))
        self.candidate_list = tk.Listbox(controls, height=3, exportselection=False, font=("Segoe UI", 9),
                                         activestyle="none", background="white", foreground=INK)
        self.candidate_list.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.candidate_list.bind("<<ListboxSelect>>", self._picked)
        self.candidate_note = ttk.Label(controls, text="Type part of a Material ID, then select one exact ID.",
                                        font=("Segoe UI", 9), foreground=MUTED)
        self.candidate_note.grid(row=2, column=0, columnspan=3, sticky="w")
        self.selected_label = ttk.Label(controls, text="Selected: —", font=("Segoe UI", 10, "bold"))
        self.selected_label.grid(row=2, column=3, sticky="e", padx=(14, 0))

        sheet_row = ttk.Frame(controls)
        sheet_row.grid(row=0, column=3, sticky="e", padx=(14, 0))
        ttk.Label(sheet_row, text="Storage Sheet", font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        self.sheet = tk.StringVar(value=ALL_SHEETS)
        self.sheet_combo = ttk.Combobox(sheet_row, textvariable=self.sheet, state="readonly", values=(ALL_SHEETS,),
                                        width=26)
        self.sheet_combo.pack(side="left")
        self.sheet_combo.bind("<<ComboboxSelected>>", lambda _e: self.query(auto=True))
        range_row = ttk.Frame(controls)
        range_row.grid(row=1, column=3, sticky="ne", padx=(14, 0), pady=(4, 0))
        ttk.Label(range_row, text="Range", font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        self.days = tk.IntVar(value=30)
        self.range_buttons = {}
        for days in history.RANGES:
            button = ttk.Radiobutton(range_row, text=f"{days} days", value=days, variable=self.days,
                                     command=lambda: self.query(auto=True))
            button.pack(side="left", padx=(0, 6))
            self.range_buttons[days] = button
        self.query_button = ttk.Button(range_row, text="Query", command=self.query, padding=(10, 1))
        self.query_button.pack(side="left", padx=(6, 0))

        state = ttk.Frame(outer)
        state.grid(row=3, sticky="ew", pady=(6, 6))
        state.columnconfigure(0, weight=1)
        self.coverage = tk.Text(state, height=3, wrap="word", font=("Segoe UI", 9), relief="flat", background="white",
                                foreground=INK, padx=6, pady=3, state="disabled")
        self.coverage.grid(row=0, column=0, sticky="ew")
        scroll = ttk.Scrollbar(state, orient="vertical", command=self.coverage.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.coverage.configure(yscrollcommand=scroll.set)

        self.tabs = ttk.Notebook(outer)
        self.tabs.grid(row=4, sticky="nsew")
        records = [("when", "Snapshot (local time)", 150), ("code", "Material ID", 110), ("description", "Description", 160),
                   ("stock", "Stock (raw)", 90), ("status", "Data Status", 230), ("rack", "Rack", 55),
                   ("level", "Level", 55), ("sheet", "Sheet", 100), ("row", "Row", 50), ("file", "Source File", 150),
                   ("version", "Version", 60)]
        changes = [("after", "Observed at (local)", 130), ("sheet", "Sheet", 100), ("type", "Change", 140),
                   ("before_at", "Before (local)", 130), ("before", "Before stock", 130), ("now", "After stock", 130),
                   ("diff", "Observed difference", 130), ("note", "Note", 360)]
        self.trees, self.more_buttons, self.count_labels = {}, {}, {}
        for name, title, columns in (("records", "Records", records), ("changes", "Observed Changes", changes)):
            frame = ttk.Frame(self.tabs, padding=4)
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)
            tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=6, selectmode="browse")
            for ident, label, width in columns:
                tree.heading(ident, text=label, anchor="w")
                # Never squeezed below the normal width: a narrow window scrolls sideways instead of hiding the
                # Data Status (BLANK / INVALID / DUPLICATE) or the observed-difference columns.
                tree.column(ident, width=width, minwidth=width, stretch=ident in ("description", "status", "note"))
            tree.grid(row=0, column=0, sticky="nsew")
            y = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
            y.grid(row=0, column=1, sticky="ns")
            x = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
            x.grid(row=1, column=0, sticky="ew")
            tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
            tree.tag_configure("attention", background=AMBER)
            tree.tag_configure("reference", foreground=MUTED)
            tree.bind("<<TreeviewSelect>>", lambda _e, n=name: self._show_row(n))
            footer = ttk.Frame(frame)
            footer.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
            footer.columnconfigure(0, weight=1)
            self.count_labels[name] = ttk.Label(footer, text="", font=("Segoe UI", 9), foreground=MUTED)
            self.count_labels[name].grid(row=0, column=0, sticky="w")
            self.more_buttons[name] = ttk.Button(footer, text="Show more", padding=(8, 1),
                                                 command=lambda n=name: self._render_page(n))
            self.more_buttons[name].grid(row=0, column=1, sticky="e")
            self.more_buttons[name].grid_remove()
            self.tabs.add(frame, text=title)
            self.trees[name] = tree
        # Fixed two lines (scrollable), so selecting a row never takes height from the tables.
        self.details = tk.Text(outer, height=2, wrap="word", font=("Segoe UI", 9), relief="flat", background=BG,
                               foreground=MUTED, padx=0, pady=2, state="disabled")
        self.details.grid(row=5, sticky="ew", pady=(6, 0))
        self._set_details(DETAILS_HINT)
        self.status = tk.StringVar(value="Select a Material ID · " + history.summary_line())
        footer = ttk.Frame(outer)
        footer.grid(row=6, sticky="ew", pady=(4, 0))
        footer.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(footer, textvariable=self.status, font=("Segoe UI", 9), foreground=MUTED)
        self.status_label.grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Close", command=self.close, padding=(10, 2)).grid(row=0, column=1, sticky="e")
        top.bind("<Configure>", self._fit, add="+")

    def _fit(self, event=None):
        """Small or scaled windows: the result tables keep their room. The coverage and details boxes give up a line
        each (both stay scrollable) and return when there is space again; the thresholds differ to avoid flapping."""
        if event is not None and event.widget is not self.top:
            return
        tables = self.tabs.winfo_height()
        line = self.coverage.tk.call("font", "metrics", self.coverage.cget("font"), "-linespace")
        if int(self.coverage.cget("height")) == 3 and tables < 12 * line:
            self.coverage.configure(height=2)
            self.details.configure(height=1)
        elif int(self.coverage.cget("height")) == 2 and tables > 16 * line:
            self.coverage.configure(height=3)
            self.details.configure(height=2)

    # ------------------------------------------------------------------ worker plumbing
    def _run(self, kind, generation, action):
        self.lanes[kind].submit(generation, action)

    def _start(self, kind, generation, action, cancel):
        def worker():
            try:
                with history.cancellable(cancel):
                    data, error = action(), None
            except Exception as exc:  # delivered to the Tk thread; never touches widgets here
                data, error = None, exc
            self.events.put((kind, generation, cancel, data, error))
        threading.Thread(target=worker, daemon=True, name=f"m4a-history-{kind}").start()

    def _poll(self):
        if self.closed:
            return
        while True:
            try:
                kind, generation, cancel, data, error = self.events.get_nowait()
            except queue.Empty:
                break
            self.lanes[kind].finished(cancel)  # frees the thread slot; the pending request (if any) starts now
            if kind == "sheets":
                self._sheets_loaded(data, error)
            elif kind == "search" and generation == self.search_gen:
                self._candidates_loaded(data, error)
            elif kind == "query" and generation == self.query_gen:
                self._result_loaded(data, error)
            # anything else is a stale response: a newer request owns the window
        self.poll_id = self.top.after(50, self._poll)

    def close(self):
        if self.closed:
            return
        self.closed = True  # late worker responses stay in the queue and are never applied
        for lane in self.lanes.values():
            lane.stop()  # no pending request starts after closing; running reads stop at their next check
        for job in (self.poll_id, self._search_job):
            if job is not None:
                try:
                    self.top.after_cancel(job)
                except tk.TclError:
                    pass
        try:
            self.top.destroy()
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close(self)

    def lift(self):
        self.top.deiconify()
        self.top.lift()
        self.search_entry.focus_set()

    # ------------------------------------------------------------------ sheets
    def _sheets_loaded(self, names, error):
        if error is not None:
            self.status.set(f"Storage Sheets could not be read: {error} · {history.summary_line()}")
            return
        self.sheet_combo.configure(values=(ALL_SHEETS, *names))

    # ------------------------------------------------------------------ search
    def _schedule_search(self, event=None):
        if event is not None and event.keysym in ("Return", "Up", "Down", "Tab"):
            return
        if self._search_job is not None:
            self.top.after_cancel(self._search_job)
        self._search_job = self.top.after(SEARCH_DELAY_MS, self.search)

    def search(self):
        self._search_job = None
        if self.closed:
            return
        self.search_gen += 1
        generation, text = self.search_gen, self.search_text.get()
        self.candidates = []
        self.candidate_list.delete(0, "end")
        if not text.strip():
            self.lanes["search"].stop()  # an earlier search is no longer wanted
            self.candidate_note.configure(text="Type part of a Material ID, then select one exact ID.", foreground=MUTED)
            return
        self.candidate_note.configure(text="Searching…", foreground=MUTED)
        self._run("search", generation, lambda: history.search_materials(self.database, text))

    def _candidates_loaded(self, data, error):
        self.candidate_list.delete(0, "end")
        self.candidates = []
        if error is not None:
            self.candidate_note.configure(text=f"Search failed; no candidates shown: {error}", foreground="#b00020")
            return
        found, more = data
        self.candidates = found
        for c in found:
            description = display(c.description) if c.in_current else "(not in the current Storage version)"
            self.candidate_list.insert("end", f"{c.key}    {description}")
        if not found:
            note = "No Material ID in Storage history contains this text. Similar IDs are never merged."
        else:
            note = (f"{len(found)} matching IDs" + (f" (first {len(found)} shown; type more)" if more else "") +
                    ". Select one exact ID; similar IDs stay separate.")
        self.candidate_note.configure(text=note, foreground=MUTED)

    def _picked(self, _event=None):
        selection = self.candidate_list.curselection()
        if not selection or selection[0] >= len(self.candidates):
            return
        self.select(self.candidates[selection[0]].key)

    def select(self, key):
        """Choose one exact Material ID (as listed) and query it."""
        self.selected_key = key
        self.selected_label.configure(text=f"Selected: {key}")
        self.query()

    # ------------------------------------------------------------------ query
    def query(self, auto=False):
        if self.closed:
            return
        if self.selected_key is None:
            if not auto:
                self.status.set("Select a Material ID from the list first · " + history.summary_line())
            return
        self.query_gen += 1
        generation = self.query_gen
        key, days = self.selected_key, self.days.get()
        sheet = None if self.sheet.get() == ALL_SHEETS else self.sheet.get()
        self._clear("Querying…")  # the previous result is gone before the new one is requested
        self.status.set(f"Querying {key} · {days} days · {history.summary_line()}")
        self._run("query", generation, lambda: history.material_history(self.database, key, days, sheet))

    def _clear(self, message):
        self.result = None
        for name, tree in self.trees.items():
            children = tree.get_children()
            if children:
                tree.delete(*children)
            self.shown[name] = 0
            self.more_buttons[name].grid_remove()
            self.count_labels[name].configure(text="")
        self.tabs.tab(0, text="Records")
        self.tabs.tab(1, text="Observed Changes")
        self._set_coverage(message, error=False)
        self._set_details(DETAILS_HINT)

    def _set_details(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("end", text)
        self.details.configure(state="disabled")

    def _set_coverage(self, text, error):
        self.coverage.configure(state="normal")
        self.coverage.delete("1.0", "end")
        self.coverage.insert("end", text)
        self.coverage.configure(state="disabled", foreground="#b00020" if error else INK)

    def _result_loaded(self, result, error):
        if error is not None:
            self._clear("")
            self._set_coverage(f"QUERY FAILED — no history is shown. Earlier results were cleared.\n{error}", error=True)
            self.status.set("Query failed · no results shown · " + history.summary_line())
            return
        self.result = result
        c = result.coverage
        scope = result.sheet if result.sheet is not None else "all Sheets, each shown separately"
        lines = [f"{history.HISTORICAL} for {result.material_key} · {scope} · last {c.days} days "
                 f"({local(c.window_start)} → {local(c.evaluated_at)} local time). "
                 f"{c.snapshots_in_window} Storage snapshot(s) in the window. "
                 + ("Full window covered by history." if c.covers_full_window else "Window NOT fully covered by history.")]
        lines.extend(c.notes)
        if not result.total_rows and not result.total_changes:
            lines.append("No history for this Material ID in this range. Nothing is assumed; missing is not 0.")
        if result.truncated:
            lines.append(f"Only the first {len(result.rows)} of {result.total_rows} records and {len(result.changes)} "
                         f"of {result.total_changes} changes were loaded. Choose a Sheet or a shorter range.")
        lines.append(history.OBSERVED_CHANGE_CAVEAT)
        self._set_coverage("\n".join(lines), error=False)
        self.tabs.tab(0, text=f"Records ({result.total_rows})")
        self.tabs.tab(1, text=f"Observed Changes ({result.total_changes})")
        self._render_page("records")
        self._render_page("changes")
        self.status.set(f"{history.HISTORICAL} loaded {local(c.evaluated_at, '%H:%M:%S')} · {history.NOT_CURRENT} · "
                        "Cloud Not Verified")

    def _render_page(self, name):
        if self.result is None:
            return
        items = self.result.rows if name == "records" else self.result.changes
        tree, start = self.trees[name], self.shown[name]
        for index in range(start, min(start + PAGE, len(items))):
            values, tags = (self._record_values if name == "records" else self._change_values)(items[index])
            tree.insert("", "end", iid=str(index), values=values, tags=tags)
        self.shown[name] = min(start + PAGE, len(items))
        total = self.result.total_rows if name == "records" else self.result.total_changes
        text = f"Showing {self.shown[name]} of {len(items)} loaded"
        if total > len(items):
            text += f" ({total} in total; the rest were not loaded — narrow the query)"
        self.count_labels[name].configure(text=text)
        if self.shown[name] < len(items):
            self.more_buttons[name].grid()
        else:
            self.more_buttons[name].grid_remove()

    @staticmethod
    def _record_values(r):
        when = ("Before window · " if r.reference else "") + local(r.observed_at)
        version = f"v{r.version_id}"
        name = Path(r.source_path).name
        if r.kind == history.NOT_RETAINED:
            return (when, "—", "—", "unknown", "NOT RETAINED — values unknown", "—", "—", r.sheet or "—", "—",
                    name, version), ("attention",)
        if r.kind == history.ABSENT:
            return (when, "—", "—", "—", "NOT PRESENT — not 0", "—", "—", r.sheet or "all", "—", name,
                    version), ("reference",) if r.reference else ()
        status = STATUS_TEXT.get(r.status, r.status)
        if r.duplicates > 1:
            status += f" · DUPLICATE ×{r.duplicates} — not added"
        tags = ("attention",) if r.status != "VALID" or r.duplicates > 1 else ()
        if r.reference:
            tags += ("reference",)
        return (when, display(r.code), display(r.description), stock_text(r.status, r.quantity), status,
                display(r.rack), display(r.level), r.sheet, r.row_no, name, version), tags

    @staticmethod
    def _change_values(c):
        if c.difference is not None:
            difference = signed(c.difference)
        elif c.change_type == "QUANTITY_CHANGED" and c.source_switched:
            difference = "not comparable (source switch)"
        else:
            difference = "—"
        tags = ("attention",) if c.source_switched or c.change_type != "QUANTITY_CHANGED" else ()
        return (local(c.after_at), c.sheet, c.change_type, local(c.before_at), side_text(c.before_status, c.before_raw),
                side_text(c.after_status, c.after_raw), difference, c.note), tags

    def _show_row(self, name):
        tree = self.trees[name]
        selection = tree.selection()
        if not selection or self.result is None:
            return
        index = int(selection[0])
        if name == "records":
            r = self.result.rows[index]
            text = (f"Snapshot {r.snapshot_id} · Storage version v{r.version_id} · synchronised {local(r.observed_at, '%Y-%m-%d %H:%M:%S')}"
                    f" ({r.observed_at} UTC){' · BEFORE WINDOW (start state)' if r.reference else ''}\n"
                    f"Source: {r.source_path} · Sheet {r.sheet!r} · Row {r.row_no if r.row_no is not None else '—'}"
                    + (f" · raw quantity {r.quantity!r}" if r.kind == history.RECORD else "")
                    + (f"\n{r.note}" if r.note else ""))
        else:
            c = self.result.changes[index]
            text = (f"{c.change_type} · Sheet {c.sheet!r} · before {c.before_at or '—'} UTC from {c.before_path or '—'}"
                    f"\nafter {c.after_at} UTC from {c.after_path}\n{c.note}")
        self._set_details(text)
