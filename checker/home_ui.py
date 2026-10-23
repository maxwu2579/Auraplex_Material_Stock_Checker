"""B1 home page: stock overview and alerts. Display only.

Everything shown comes from the owning CheckerApp (its result, binding, inventory state) or from alerts.load_state.
Tiles only group stored alert rows for display; they do not evaluate anything. A state that is not known (no
database, upgrade required, read failure, no evaluation of the current files, loading) is shown as unknown, never 0.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk

from . import alerts, binding, cached
from .alerts_ui import AlertsWindow
from .core import ENOUGH, EXCEPTION, SHORTAGE
from .i18n import state_text
from .presentation import AMBER, BG, MUTED, Tooltip
from .sync import (CHECKING, LOCAL_VERIFIED, NOT_SYNCED, SOURCE_CHANGED, SOURCE_UNAVAILABLE, STATUS_UNKNOWN,
                   SYNC_FAILED, SYNCING, USING_PREVIOUS)

TILES = (("zero", "tile_zero"), ("low", "tile_low"), ("blank", "tile_blank"), ("invalid", "tile_invalid"),
         ("dup", "tile_dup"), ("missing", "tile_missing"), ("threshold", "tile_threshold"), ("other", "tile_other"))
SUBTYPE_TILES = {"BLANK_STOCK": "blank", "INVALID_STOCK": "invalid", "DUPLICATE_STOCK_ID": "dup"}
TYPE_TILES = {alerts.OUT_OF_STOCK: "zero", alerts.LOW_STOCK: "low", alerts.NOT_IN_MASTER: "missing",
              alerts.NOT_CONFIGURED: "threshold"}
COLUMNS = (("type", "col_type", 150), ("subtype", "col_subtype", 120), ("material", "col_code", 120),
           ("description", "col_description", 180), ("sheet", "col_sheet", 100), ("rows", "col_rows", 70),
           ("stock", "col_raw_stock", 110), ("threshold", "col_threshold", 120), ("status", "col_alert_status", 110))
GOOD, WARN, BAD = "#1d7148", "#8f5200", "#b42318"
# The database's overall state (checker.queries.overall_state) -> its explanation; nothing is decided here.
BANNERS = {LOCAL_VERIFIED: "banner_ok", NOT_SYNCED: "banner_not_synced", CHECKING: "banner_checking",
           SYNCING: "banner_checking", STATUS_UNKNOWN: "banner_unknown", USING_PREVIOUS: "banner_previous",
           SYNC_FAILED: "banner_failed", SOURCE_UNAVAILABLE: "banner_failed", SOURCE_CHANGED: "banner_failed"}
QUIET_BANNERS = ("banner_ok", "banner_checking", "banner_not_synced")


def tile_of(row):
    """Display grouping of one stored alert row; every row belongs to exactly one tile."""
    if row.alert_type == alerts.DATA_ISSUE:
        return SUBTYPE_TILES.get(row.subtype, "other")
    return TYPE_TILES.get(row.alert_type, "other")


class HomePage:
    def __init__(self, app, master):
        self.app = app
        self.state = None        # last AlertState read for the home page, or None
        self.loading = False
        self.wanted = True       # a read is wanted when the page is visible and nothing writes
        self.events = queue.Queue()
        self.tile = tk.StringVar(value="")
        # The page scrolls only when the window is too short for the cards and a few alert rows (small windows,
        # large fonts); otherwise the alert table takes the remaining height.
        self.frame = outer = ttk.Frame(master)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(outer, background=BG, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scroll = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.scroll.grid(row=0, column=1, sticky="ns")
        self.scroll.grid_remove()
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.content = frame = ttk.Frame(self.canvas, padding=(14, 10))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        self.window = self.canvas.create_window(0, 0, anchor="nw", window=frame)
        self.canvas.bind("<Configure>", lambda _e: self.fit())
        frame.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._build_cards(frame)
        self._build_alerts(frame)
        self._bind_wheel(frame)

    def _bind_wheel(self, widget):
        if widget is not self.tree:
            widget.bind("<MouseWheel>", self._wheel, add="+")
            for child in widget.winfo_children():
                self._bind_wheel(child)

    def _wheel(self, event):
        if self.scroll.winfo_ismapped():
            self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def _grid_tiles(self, columns):
        """Four tiles per row on wide pages, two on narrow ones, so "unknown" is never cut off."""
        if columns == self.tile_columns:
            return False
        self.tile_columns = columns
        for column in range(4):
            self.tile_frame.columnconfigure(column, weight=1 if column < columns else 0,
                                            uniform="tiles" if column < columns else "")
        for index, (button, _key) in enumerate(self.tiles.values()):
            button.grid(row=index // columns, column=index % columns, sticky="ew", padx=2, pady=2)
        return True

    def fit(self):
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if width <= 1:
            return
        self._fit_counts()
        if self._grid_tiles(4 if width >= 1000 * self.app._scale() else 2):
            self.app._schedule_resize()  # the page height changed: fit again once it is laid out
        need = self.content.winfo_reqheight()
        self.canvas.itemconfigure(self.window, width=width, height=max(height, need))
        if need > height:
            self.scroll.grid()
        else:
            self.scroll.grid_remove()
            self.canvas.yview_moveto(0)

    # ------------------------------------------------------------------ layout
    def _card(self, parent, key):
        card = ttk.Frame(parent, style="Card.TFrame", padding=(14, 10))
        title = ttk.Label(card, style="Card.TLabel", font=("Segoe UI", 11, "bold"))
        title.grid(row=0, column=0, columnspan=4, sticky="w")
        self.app._tr(title, key)
        return card

    def _build_cards(self, frame):
        app = self.app
        cards = ttk.Frame(frame)
        cards.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        cards.columnconfigure((0, 1), weight=1, uniform="home")
        quick = self._card(cards, "quick_check")
        quick.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        quick.columnconfigure(0, weight=1)
        app._tr(ttk.Label(quick, style="CardMuted.TLabel"), "product_id").grid(row=1, column=0, sticky="w", pady=(6, 0))
        app._tr(ttk.Label(quick, style="CardMuted.TLabel"), "quantity").grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
        self.product_combo = ttk.Combobox(quick, textvariable=app.product_text, state="normal", font=("Segoe UI", 10))
        self.product_combo.grid(row=2, column=0, sticky="ew")
        app._bind_product_box(self.product_combo)
        self.quantity_entry = ttk.Entry(quick, textvariable=app.quantity_text, width=6, font=("Segoe UI", 10))
        self.quantity_entry.grid(row=2, column=1, padx=(8, 8))
        self.quantity_entry.bind("<Return>", lambda _e: app.check())
        self.check_button = ttk.Button(quick, style="Primary.TButton", command=app.check)
        self.check_button.grid(row=2, column=2)
        app._tr(self.check_button, "check_button")
        self.sheet_row = ttk.Frame(quick, style="Card.TFrame")
        self.sheet_row.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        app._tr(ttk.Label(self.sheet_row, style="CardMuted.TLabel"), "storage_sheet").pack(side="left", padx=(0, 8))
        self.sheet_combo = ttk.Combobox(self.sheet_row, textvariable=app.stock_name, state="readonly")
        self.sheet_combo.pack(side="left", fill="x", expand=True)
        self.sheet_row.grid_remove()
        self.hint = ttk.Label(quick, style="CardMuted.TLabel", justify="left")
        self.hint.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        app.wrapping.append(self.hint)
        app.controls += [(self.product_combo, "normal"), (self.quantity_entry, "normal"), (self.check_button, "normal"),
                         (self.sheet_combo, "readonly")]
        last = self.last_card = self._card(cards, "last_check")
        last.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        last.columnconfigure(0, weight=1)
        self.last_product = ttk.Label(last, style="Card.TLabel", font=("Segoe UI", 10, "bold"))
        self.last_product.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.last_meta = ttk.Label(last, style="CardMuted.TLabel")
        self.last_meta.grid(row=2, column=0, columnspan=3, sticky="w")
        counts = self.counts_frame = ttk.Frame(last, style="Card.TFrame")
        counts.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.count_columns = None
        self.last_counts = {}
        for key, colour in ((SHORTAGE, BAD), (EXCEPTION, WARN), (ENOUGH, GOOD)):
            label = ttk.Label(counts, style="Card.TLabel", font=("Segoe UI", 10, "bold"), foreground=colour)
            self.last_counts[key] = label
        self._fit_counts()
        counts.bind("<Configure>", lambda _e: self._fit_counts())
        self.last_state = ttk.Label(last, style="CardMuted.TLabel", justify="left")
        self.last_state.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        app.wrapping.append(self.last_state)
        buttons = ttk.Frame(last, style="Card.TFrame")
        buttons.grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.open_button = app._tr(ttk.Button(buttons, command=lambda: app.show_page("check"), padding=(8, 3)),
                                   "open_result")
        self.open_button.pack(side="left")
        self.again_button = app._tr(ttk.Button(buttons, command=app.check, padding=(8, 3)), "check_again")
        self.again_button.pack(side="left", padx=(8, 0))
        app.controls.append((self.again_button, "normal"))

    def _fit_counts(self):
        """Wrap complete counters to the card width instead of clipping the last number."""
        width = self.counts_frame.winfo_width()
        labels = list(self.last_counts.values())
        gap = max(8, round(10 * self.app._scale()))
        columns = 1
        for candidate in (3, 2):
            rows = (labels[i:i + candidate] for i in range(0, len(labels), candidate))
            if all(sum(label.winfo_reqwidth() for label in row) + gap * (len(row) - 1) <= width
                   for row in rows):
                columns = candidate
                break
        if columns == self.count_columns:
            return
        self.count_columns = columns
        for column in range(3):
            self.counts_frame.columnconfigure(column, weight=1 if column < columns else 0)
        for index, label in enumerate(labels):
            column = index % columns
            label.grid(row=index // columns, column=column, sticky="w",
                       padx=(0, gap if column < columns - 1 else 0))

    def _build_alerts(self, frame):
        app = self.app
        card = self._card(frame, "alerts_title")
        card.grid(row=1, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(4, weight=1)
        head = ttk.Frame(card, style="Card.TFrame")
        head.grid(row=0, column=1, columnspan=3, sticky="e")
        self.clear_button = app._tr(ttk.Button(head, command=lambda: self.select_tile(""), padding=(8, 3)), "clear_filter")
        self.clear_button.pack(side="right")
        self.open_alerts_button = app._tr(ttk.Button(head, command=app.open_alerts, padding=(8, 3)), "open_alerts")
        self.open_alerts_button.pack(side="right", padx=(0, 8))
        self.alert_state = ttk.Label(card, style="CardMuted.TLabel", justify="left")
        self.alert_state.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        app.wrapping.append(self.alert_state)
        tiles = ttk.Frame(card, style="Card.TFrame")
        tiles.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        self.tile_frame, self.tile_columns = tiles, 0
        self.tiles = {}
        for name, key in TILES:
            button = ttk.Radiobutton(tiles, variable=self.tile, value=name, style="Filter.TRadiobutton",
                                     command=lambda n=name: self.select_tile(n))
            self.tiles[name] = (button, key)
        self._grid_tiles(4)
        self.overlap = ttk.Label(card, style="CardMuted.TLabel", justify="left")
        self.overlap.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(4, 4))
        app.wrapping.append(self.overlap)
        table = ttk.Frame(card, style="Card.TFrame")
        table.grid(row=4, column=0, columnspan=4, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in COLUMNS], show="headings", selectmode="browse", height=3)
        for ident, _key, width in COLUMNS:
            self.tree.column(ident, width=width, minwidth=60, stretch=ident in ("description", "type"))
        self.tree.grid(row=0, column=0, sticky="nsew")
        y = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        y.grid(row=0, column=1, sticky="ns")
        x = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        x.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        self.tree.tag_configure("attention", background=AMBER)
        self.tree.tag_configure("muted", foreground=MUTED)
        self.tree.bind("<Double-1>", lambda _e: app.open_alerts())
        Tooltip(self.tree, lambda: alerts.PENDING_CONFIRMATION)
        sources = ttk.Frame(frame, style="Card.TFrame", padding=(14, 6))
        sources.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        sources.columnconfigure(1, weight=1)
        title = ttk.Label(sources, style="Card.TLabel", font=("Segoe UI", 10, "bold"))
        title.grid(row=0, column=0, sticky="nw", padx=(0, 12))
        app._tr(title, "sources")
        self.source_lines = ttk.Label(sources, style="CardMuted.TLabel", justify="left")
        self.source_lines.grid(row=0, column=1, sticky="ew")
        self.source_note = ttk.Label(sources, style="CardMuted.TLabel", justify="left")
        self.source_note.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        app.wrapping.append(self.source_note)

    # ------------------------------------------------------------------ alert data (read-only, background)
    def request(self):
        """Ask for a fresh read of the stored alerts; it starts when the page is visible and nothing writes."""
        self.wanted = True

    def drain(self):
        """UI thread, from the owner's poll."""
        app = self.app
        while True:
            try:
                generation, state, error = self.events.get_nowait()
            except queue.Empty:
                break
            self.loading = False
            if error is not None:
                self.state = None
                app.alert_read_failed(error)  # fail closed for the whole session, as the Stock Alerts window does
            elif generation != app.alert_gate.generation:
                # Started before a selection, sync or read failure: it must not clear that newer state (for example
                # the read-failure flag). Discard it and read again when allowed.
                self.state, self.wanted = None, True
            else:
                self.state = state
                app.alert_read_ok()
            self.render_alerts()
        runner = app.alert_runner
        if (self.wanted and not self.loading and runner is not None and app.page == "home" and not app.busy
                and not runner.running and not app.closed):
            self.wanted, self.loading = False, True
            database, generation = app.inventory.db_path, app.alert_gate.generation

            def worker():
                try:
                    self.events.put((generation, alerts.load_state(database, include_other_sources=False), None))
                except Exception as exc:
                    self.events.put((generation, None, exc))
            threading.Thread(target=worker, daemon=True, name="b1-home-alerts").start()
            self.render_alerts()

    def select_tile(self, name):
        self.tile.set(name)
        self._fill()

    # ------------------------------------------------------------------ rendering (no reads, no calculation)
    def render(self):
        self.render_check()
        self.render_alerts()
        self._render_sources()

    def render_check(self):
        """The quick check and last-check cards (cheap: called on every input change)."""
        self._render_quick()
        self._render_last()

    def _render_quick(self):
        app = self.app
        book = app.stock_book
        names = tuple(s.name for s in book.stock_sheets) if book else ()
        self.sheet_combo.configure(values=names)
        self.sheet_row.grid() if len(names) > 1 else self.sheet_row.grid_remove()
        self.hint.configure(text=app.t("quick_hint") if app.result is not None else
                            app.t("quick_hint") + "\n" + app.t("no_product_yet"))

    def _render_last(self):
        app, last = self.app, self.app.last_check
        if last is None:
            self.last_product.configure(text=app.t("last_none"))
            self.last_meta.configure(text="")
            for label in self.last_counts.values():
                label.configure(text="")
            self.last_state.configure(text=app.t("trial_note"), foreground=MUTED)
            self.open_button.state(["disabled"])
            return
        live = app.result is not None and app.result is last["result"]
        bound = app.result_binding if live else None
        self.last_product.configure(text=f"{last['product']}  ×  {last['quantity']}")
        self.last_meta.configure(text=f"{app.t('checked_at')}: {last['time']}")
        for key, label in self.last_counts.items():
            label.configure(text=f"{key} {last['counts'][key]}" if live else f"{key} —")
        if not live:
            text, colour = app.t("state_recheck"), BAD
        elif isinstance(bound, cached.CacheBinding):
            text, colour = (app.t("state_cached") if app.result_exportable else app.t("state_outdated")), BAD
        elif bound is not None and bound.current:
            when = datetime.fromtimestamp(bound.checked_at).strftime("%Y-%m-%d %H:%M:%S")
            text, colour = app.t("state_bound", time=when), MUTED
        else:
            text, colour = app.t("state_outdated"), BAD
        self.last_state.configure(text=f"{app.t('basis')}: {text}\n{app.t('trial_note')}", foreground=colour)
        self.open_button.state(["!disabled"] if live else ["disabled"])
        self._fit_counts()

    def _known(self):
        """None when alert counts are unknown (with the reason key), else the state to show."""
        app, state = self.app, self.state
        if app.alert_runner is None:
            return None, "alerts_no_db"
        if app.alert_read_error is not None:
            return None, "alerts_read_failed"
        if (app.alert_schema is not None and app.alert_schema < alerts.ALERT_SCHEMA_VERSION) or (
                state is not None and state.schema < alerts.ALERT_SCHEMA_VERSION):
            return None, "alerts_upgrade"
        if state is None:
            return None, "alerts_loading"
        if state.latest_completed is None:
            return None, "alerts_not_evaluated"
        return state, None

    def render_alerts(self):
        app = self.app
        state, reason = self._known()
        counts = {name: 0 for name, _key in TILES}
        if state is not None:
            for row in state.rows:
                counts[tile_of(row)] += 1
        partial = state is not None and state.total_rows > len(state.rows)
        for name, (button, key) in self.tiles.items():
            if state is None:
                value = app.t("alerts_unknown")
            else:
                value = f"{counts[name]}+" if partial else str(counts[name])
            button.configure(text=f"{app.t(key)}  {value}")
            button.state(["disabled"] if state is None else ["!disabled"])
        if state is None:
            text = app.t(reason)
            self.alert_state.configure(text=text, foreground=BAD if reason != "alerts_loading" else MUTED)
            self.overlap.configure(text="")
            self.tile.set("")
        else:
            current = app.alert_current
            text = app.t("alerts_rechecked" if current else "alerts_stored") + " " + app.t("alerts_threshold_note")
            self.alert_state.configure(text=text, foreground=MUTED if current else WARN)
            total = state.total_rows
            if total == 0:
                note = app.t("alerts_none")
            elif partial:
                note = app.t("alerts_overlap_partial", n=total, k=len(state.rows))
            else:
                materials = {r.material_key if r.material_key is not None else ("row", r.stock_sheet, id(r))
                             for r in state.rows}
                note = app.t("alerts_overlap", n=total, m=len(materials))
            self.overlap.configure(text=note)
        for ident, key, _width in COLUMNS:
            self.tree.heading(ident, text=app.t(key))
        self._fill()

    def _fill(self):
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        state, _reason = self._known()
        if state is None:
            return
        chosen = self.tile.get()
        for index, row in enumerate(state.rows):
            if chosen and tile_of(row) != chosen:
                continue
            values, tags = AlertsWindow._alert_values(row)
            # type, subtype, material, description, sheet, rows, stock, threshold, status (codes untranslated)
            self.tree.insert("", "end", iid=str(index), values=(*values[:8], values[13]), tags=tags)

    def _render_sources(self):
        app = self.app
        lines = []
        for role, path in (("stock", app.stock_path.get()), ("bom", app.bom_path.get())):
            info = app.inventory_roles.get(role)
            state = app.sync_active.get(role) or (info.label if info else None)
            name = Path(path).name if path else app.t("not_selected")
            text = f"{binding.ROLE_NAMES[role]}: {name}"
            if app.db_panel is not None and app.inventory is not None:
                text += f"  ·  {state_text(state, app.language.language) if state else '—'}"
            lines.append(text)
        self.source_lines.configure(text="\n".join(lines))
        overall = getattr(app, "db_overall", None) or NOT_SYNCED
        if app.cache_selection is not None:
            key = "banner_cache"
        elif app.inventory is None:
            key = "banner_no_db"
        else:
            key = BANNERS.get(overall, "banner_previous")
        self.source_note.configure(text=app.t(key), foreground=MUTED if key in QUIET_BANNERS else WARN)
