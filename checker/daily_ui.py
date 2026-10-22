"""M3.2D Daily Stock Summary window: choose a date, generate, preview and save HTML + JSON. Read-only.

Generation and saving run on one bounded worker (daily.DailyRunner: one task plus one newest waiting request); only
the Tk thread touches widgets. Each generation request has an ID: only the newest request's result is shown, so an
older, slower result can never replace the summary of a newer date or newer data. A failed generation clears the
preview. A VERIFIED preview becomes OUT OF DATE (Save disabled) as soon as the application's verification changes;
save() re-checks the database too. A database read failure is handled like every other alert/status read
failure (the application's verification is discarded; Refresh Excel restores it). Past dates and unverified data need explicit confirmation and are marked
UNVERIFIED. Nothing is delivered after the window is closed.
"""
from __future__ import annotations

from datetime import date, timedelta
import os
from pathlib import Path
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import daily
from .presentation import BG, INK, MUTED, work_area

BANNER = ("DAILY STOCK SUMMARY · From synchronised Excel data · Cloud Not Verified · "
          "Observed Change ≠ Actual Consumption")
HINT = ("Choose a date (YYYY-MM-DD, local time) and Generate. Today's summary is VERIFIED only when this program has "
        "just checked both Excel files and re-checked the stock alerts. Past dates are always UNVERIFIED: their stock "
        "and alert state cannot be reconstructed.")
RED, GREEN = "#b00020", "#3b715e"


class DailySummaryWindow:
    def __init__(self, master, owner, today=None):
        """owner: the CheckerApp (database path, alert gate, daily_session()). today: test hook for the local date."""
        self.owner = owner
        self.database = str(owner.inventory.db_path)
        self.gate = owner.alert_gate
        self.today = today or date.today
        self.runner = daily.DailyRunner()
        self.closed = False
        self.request_id = 0
        self.latest_generate = 0     # only this generation request's result may be shown
        self.requested = None        # (request ID, date, allow_unverified) of the newest generation
        self.saving = None           # request ID of a running save
        self.summary = None
        self.stale = None            # reason the shown preview may no longer be saved
        self.saved = None
        self.last_folder = None
        self.top = top = tk.Toplevel(master)
        top.title("Daily Stock Summary")
        left, upper, width, height = work_area(top)
        top.geometry(f"{min(1100, width - 64)}x{min(720, height - 80)}+{left + 56}+{upper + 56}")
        top.minsize(min(760, width - 64), min(480, height - 80))
        top.configure(background=BG)
        top.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self.poll_id = top.after(50, self._poll)

    # ------------------------------------------------------------------ layout
    def _build(self):
        outer = ttk.Frame(self.top, padding=(14, 8))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)
        self.banner = ttk.Label(outer, text=BANNER, font=("Segoe UI", 10, "bold"), foreground=RED)
        self.banner.grid(row=0, sticky="w")
        self.hint = ttk.Label(outer, text=HINT, font=("Segoe UI", 9), foreground=MUTED)
        self.hint.grid(row=1, sticky="ew", pady=(2, 6))
        bar = ttk.Frame(outer)
        bar.grid(row=2, sticky="ew")
        ttk.Label(bar, text="Report date", font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        self.date_text = tk.StringVar(value=self.today().isoformat())
        self.date_entry = ttk.Entry(bar, textvariable=self.date_text, width=12)
        self.date_entry.pack(side="left")
        self.date_entry.bind("<Return>", lambda _e: self.generate())
        ttk.Button(bar, text="◀", width=3, command=lambda: self.shift(-1)).pack(side="left", padx=(4, 0))
        ttk.Button(bar, text="Today", command=self.set_today, padding=(6, 1)).pack(side="left", padx=(2, 0))
        ttk.Button(bar, text="▶", width=3, command=lambda: self.shift(1)).pack(side="left", padx=(2, 0))
        self.generate_button = ttk.Button(bar, text="Generate", command=self.generate, padding=(10, 1))
        self.generate_button.pack(side="left", padx=(12, 0))
        self.state = ttk.Label(outer, text="No summary generated yet.", font=("Segoe UI", 9, "bold"),
                               foreground=MUTED)
        self.state.grid(row=3, sticky="ew", pady=(6, 4))
        outer.bind("<Configure>", lambda e: [w.configure(wraplength=max(200, e.width - 30))
                                             for w in (self.banner, self.hint, self.state)])
        frame = ttk.Frame(outer)
        frame.grid(row=4, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.preview = tk.Text(frame, wrap="word", font=("Consolas", 9), relief="flat", background="white",
                               foreground=INK, padx=8, pady=6, state="disabled")
        self.preview.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.preview.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.preview.configure(yscrollcommand=scroll.set)
        # Save / Open / Close on their own row: they stay visible in a narrow window (packed before the status text).
        footer = ttk.Frame(outer)
        footer.grid(row=5, sticky="ew", pady=(6, 0))
        ttk.Button(footer, text="Close", command=self.close, padding=(10, 1)).pack(side="right")
        ttk.Button(footer, text="Schedule draft…", command=self.schedule_draft, padding=(8, 1)).pack(side="right",
                                                                                                    padx=(0, 8))
        self.open_button = ttk.Button(footer, text="Open saved report", command=self.open_saved, padding=(10, 1),
                                      state="disabled")
        self.open_button.pack(side="right", padx=(0, 8))
        self.save_button = ttk.Button(footer, text="Save HTML + JSON…", command=self.save, padding=(10, 1),
                                      state="disabled")
        self.save_button.pack(side="right", padx=(0, 8))
        self.status = tk.StringVar(value="Cloud Not Verified")
        ttk.Label(footer, textvariable=self.status, font=("Segoe UI", 9), foreground=MUTED).pack(side="left",
                                                                                                fill="x")
        self.date_text.trace_add("write", lambda *_: self._refresh_state())

    # ------------------------------------------------------------------ date
    def selected_date(self):
        try:
            return date.fromisoformat(self.date_text.get().strip())
        except ValueError:
            return None

    def shift(self, days):
        day = self.selected_date() or self.today()
        target = day + timedelta(days=days)
        if target <= self.today():
            self.date_text.set(target.isoformat())

    def set_today(self):
        self.date_text.set(self.today().isoformat())

    # ------------------------------------------------------------------ generate
    def generate(self):
        if self.closed:
            return
        if self.saving is not None:
            self.status.set("Saving… wait until the files are written · Cloud Not Verified")
            return
        day = self.selected_date()
        if day is None:
            self.status.set("Enter the date as YYYY-MM-DD · Cloud Not Verified")
            return
        if day > self.today():
            self.status.set(f"{day} is in the future; choose today or an earlier date · Cloud Not Verified")
            return
        session = self.owner.daily_session()
        reasons = []
        if day != self.today():
            reasons.append(f"{day} is a past date: its stock and alert state cannot be reconstructed")
        if session.authorization is None:
            reasons.append(session.reason or "the Excel files were not both verified in this session")
        elif not session.alert_current:
            reasons.append("the stock alerts were not re-checked in this session" +
                           (f" ({session.reason})" if session.reason else ""))
        allow = False
        if reasons:
            if not self._confirm_unverified(day, reasons):
                return
            session = self.owner.daily_session()  # the dialog may have taken a while
            allow = True
        self._request(day, session, allow)

    def _confirm_unverified(self, day, reasons) -> bool:
        answer = messagebox.askyesno(
            "Generate UNVERIFIED summary?",
            f"The summary for {day} cannot be verified:\n\n- " + "\n- ".join(reasons) +
            "\n\nIt would be marked UNVERIFIED in the preview, the file names and the report. Historical observations "
            "stay historical; nothing is presented as current stock.\n\nGenerate an UNVERIFIED summary?",
            parent=self.top, default="no")
        return bool(answer) and not self.closed

    def _request(self, day, session, allow):
        self.request_id += 1
        self.latest_generate = self.request_id
        self.requested = (self.request_id, day, allow)
        if self.summary is not None:
            self.stale = "a newer summary is being generated"
        database, gate = self.database, self.gate
        self.runner.request(self.request_id, "generate",
                            lambda: daily.generate(database, day, session, gate=gate, allow_unverified=allow))
        self.status.set(f"Generating the summary for {day}… · Cloud Not Verified")
        self._refresh_state()

    # ------------------------------------------------------------------ save
    def schedule_draft(self):
        """Generate a reviewable XML file only. Never imports/enables tasks or asks for Windows credentials."""
        from tkinter import simpledialog
        from .scheduling import task_xml
        if self.closed or self.runner.busy:
            return
        output = filedialog.askdirectory(parent=self.top, title="Choose the scheduled daily-report folder",
                                         mustexist=True)
        if not output or self.closed:
            return
        at = simpledialog.askstring('Daily schedule draft', 'Local daily time (HH:MM, e.g. 18:00):',
                                   initialvalue='18:00', parent=self.top)
        if at is None or self.closed:
            return
        try:
            payload = task_xml(Path(self.database).parent, output, at)
        except (ValueError, OSError) as exc:
            messagebox.showerror('Schedule draft', str(exc), parent=self.top)
            return
        if not messagebox.askyesno('Save schedule draft only?',
            f'Daily at {at} (local time), output:\n{output}\n\n'
            'This exports XML only; no Windows task will be registered or enabled.\n'
            'The current user must be logged in, with both source files available.\n'
            'Each run tries at most 3 times, 30 seconds apart; no Windows restart loop.\n'
            'No password is stored. Missed schedules request one delayed run of the current day; '
            'historical daily stock states are not reconstructed. On battery power the task waits.\n'
            'Requires the explicitly upgraded database and previously selected Storage/BOM paths.\n\n'
            'Save the draft for review?', parent=self.top, default='no') or self.closed:
            return
        path = filedialog.asksaveasfilename(parent=self.top, title='Save new Task Scheduler XML (draft only)',
                                          initialfile='Auraplex_Daily_Summary.xml', defaultextension='.xml',
                                          filetypes=[('Task Scheduler XML', '*.xml')], confirmoverwrite=False)
        if not path or self.closed:
            return
        try:
            with open(path, 'xb') as stream:
                stream.write(payload)
        except OSError as exc:
            messagebox.showerror('Schedule draft not saved', str(exc), parent=self.top)
            return
        messagebox.showinfo('Draft saved — no task installed', str(path) +
                            '\nReview/import with Windows Task Scheduler only when ready. '
                            'No task has been created or enabled.', parent=self.top)

    def can_save(self) -> bool:
        return (self.summary is not None and self.stale is None and self.saving is None and not self.runner.busy
                and self.selected_date() is not None and self.selected_date().isoformat() == self.summary.report_date)

    def save(self):
        if self.closed or not self.can_save():
            return
        summary = self.summary
        folder = filedialog.askdirectory(parent=self.top, title="Save the Daily Stock Summary (HTML + JSON) in…",
                                         initialdir=self.last_folder or str(_documents()), mustexist=True)
        if not folder or self.closed:
            return
        if self.summary is not summary or not self.can_save():
            messagebox.showerror("Summary changed", "The summary changed or became out of date while the folder was "
                                 "chosen. Generate it again.", parent=self.top)
            return
        self.last_folder = folder
        self.request_id += 1
        self.saving = self.request_id
        database, gate = self.database, self.gate
        self.runner.request(self.request_id, "save", lambda: daily.save(summary, folder, database, gate=gate))
        self.status.set("Saving… · Cloud Not Verified")
        self._refresh_state()

    def open_saved(self):
        if self.saved is not None and self.saved.html.exists():
            try:
                os.startfile(str(self.saved.html))  # the default browser; the file has no external resources
            except OSError as exc:
                messagebox.showerror("Open report", str(exc), parent=self.top)

    # ------------------------------------------------------------------ results (Tk thread only)
    def _poll(self):
        if self.closed:
            return
        while True:
            try:
                request_id, kind, result, error = self.runner.events.get_nowait()
            except queue.Empty:
                break
            if kind == "generate":
                self._generated(request_id, result, error)
            else:
                self._saved(request_id, result, error)
            if self.closed:
                return
        self._check_stale()
        self.poll_id = self.top.after(50, self._poll)

    def _generated(self, request_id, summary, error):
        if request_id != self.latest_generate:
            return  # superseded by a newer request: never shown
        _rid, day, _allow = self.requested
        if error is not None:
            self.summary, self.stale = None, None
            self._set_preview("")
            if isinstance(error, daily.ConfirmationRequired):
                self.state.configure(text="Not generated: this summary would be UNVERIFIED and needs confirmation.",
                                     foreground=RED)
                self.top.after_idle(lambda: self._confirm_after(request_id, day, error.reasons))
            else:
                if isinstance(error, daily.DailyReadError):
                    self.owner.alert_read_failed(error)  # as every alert/status read: verification is discarded
                self.state.configure(text=f"GENERATION FAILED for {day} — no summary is shown: {error}",
                                     foreground=RED)
                self.status.set("Generation failed · Cloud Not Verified")
            self._refresh_buttons()
            return
        self.summary, self.stale, self.saved = summary, None, None
        self._set_preview(daily.render_text(summary))
        self.status.set(f"Summary {summary.report_id[:8]} for {summary.report_date} generated · "
                        f"{summary.status} · Cloud Not Verified")
        self._refresh_state()

    def _confirm_after(self, request_id, day, reasons):
        if self.closed or request_id != self.latest_generate:
            return
        if self._confirm_unverified(day, reasons) and request_id == self.latest_generate:
            self._request(day, self.owner.daily_session(), True)
        else:
            self.status.set("Not generated · Cloud Not Verified")

    def _saved(self, request_id, saved, error):
        if request_id != self.saving:
            return
        self.saving = None
        if error is not None:
            if isinstance(error, (daily.DailyStale, daily.DailyReadError)):
                self.stale = str(error)
            if isinstance(error, daily.DailyReadError):
                self.owner.alert_read_failed(error)
            self.status.set("Not saved · Cloud Not Verified")
            self._refresh_state()
            detail = "\n\n".join(x for x in (str(error), getattr(error, "cleanup_warning", "")) if x)
            messagebox.showerror("Daily Stock Summary not saved", detail, parent=self.top)
            return
        self.saved = saved
        self.status.set(f"Saved report folder {saved.folder} ({saved.html.name}, {saved.json.name}) · Cloud Not Verified")
        self._refresh_state()

    def _check_stale(self):
        """A VERIFIED preview stops being saveable once the application's verification has changed."""
        s = self.summary
        if s is None or self.stale is not None or not s.verified:
            return
        if not self.gate.valid(s.generation) or not self.owner.alert_current:
            self.stale = ("this program's verification changed after generation (selection, sync, failure or "
                          "database read failure)")
            self._refresh_state()

    # ------------------------------------------------------------------ rendering
    def _set_preview(self, text):
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("end", text)
        self.preview.configure(state="disabled")

    def _refresh_state(self):
        if self.closed:
            return
        s = self.summary
        if s is not None:
            if self.stale is not None:
                text, colour = f"OUT OF DATE — {s.status} summary for {s.report_date}: {self.stale}. Generate again.", RED
            elif self.selected_date() is None or self.selected_date().isoformat() != s.report_date:
                text, colour = f"Preview is for {s.report_date}, not the selected date. Generate again to save.", RED
            elif s.verified:
                text, colour = (f"VERIFIED summary for {s.report_date} — this program checked both Excel files and "
                                "re-checked the alerts in this session · Cloud Not Verified"), GREEN
            else:
                text, colour = (f"UNVERIFIED summary for {s.report_date} (generated after your confirmation) · "
                                "Cloud Not Verified"), RED
            self.state.configure(text=text, foreground=colour)
        elif self.runner.busy:
            self.state.configure(text="Generating…", foreground=MUTED)
        self._refresh_buttons()

    def _refresh_buttons(self):
        if self.closed:
            return
        self.save_button.configure(state="normal" if self.can_save() else "disabled")
        self.open_button.configure(state="normal" if self.saved is not None else "disabled")

    # ------------------------------------------------------------------ lifecycle
    def lift(self):
        self.top.deiconify()
        self.top.lift()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.runner.close()  # a running task finishes (a save publishes completely or not at all); nothing delivered
        try:
            self.top.after_cancel(self.poll_id)
        except tk.TclError:
            pass
        try:
            self.top.destroy()
        except tk.TclError:
            pass
        if self.owner.daily_window is self:
            self.owner.daily_window = None


def _documents() -> Path:
    documents = Path.home() / "Documents"
    return documents if documents.is_dir() else Path.home()
