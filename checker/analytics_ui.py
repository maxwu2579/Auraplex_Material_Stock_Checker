"""M4B read-only analysis window; one running task + one replaceable pending task, no worker Tk calls."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk

from . import analytics
from .core import display
from .daily import DailyRunner
from .history import HistoryReadError
from .presentation import BG, MUTED, work_area

PAGE = 200


def number(value):
    return 'unknown' if value is None else display(value)


class AnalyticsWindow:
    def __init__(self, master, database, on_close=None, on_read_error=None):
        self.database = str(database)
        self.on_close, self.on_read_error = on_close, on_read_error
        self.closed = False
        self.runner = DailyRunner()
        self.generation = 0
        self.cancel = threading.Event()
        self.result = None
        self.shown = 0
        self.top = top = tk.Toplevel(master)
        top.title('Inventory Analytics — Historical / UNVERIFIED')
        left, upper, width, height = work_area(top)
        top.geometry(f'{min(1200, width-60)}x{min(720, height-70)}+{left+30}+{upper+30}')
        top.minsize(min(900, width-60), min(540, height-70))
        top.configure(background=BG)
        top.protocol('WM_DELETE_WINDOW', self.close)
        self._build()
        self.poll_id = top.after(50, self._poll)

    def _build(self):
        outer = ttk.Frame(self.top, padding=(12, 8))
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(5, weight=1)
        self.heading = ttk.Label(outer, text='Inventory Analytics · HISTORICAL / UNVERIFIED',
                                 font=('Segoe UI', 11, 'bold'))
        self.heading.grid(row=0, sticky='w')
        self.banner = ttk.Label(outer, text='Not current stock · Cloud Not Verified',
                               font=('Segoe UI', 10, 'bold'), foreground='#b00020')
        self.banner.grid(row=1, sticky='w')
        caveat = ttk.Label(outer, text=analytics.CAVEAT, font=('Segoe UI', 9), foreground=MUTED)
        caveat.grid(row=2, sticky='ew', pady=(2, 4))
        outer.bind('<Configure>', lambda e: caveat.configure(wraplength=max(200, e.width-25)))
        controls = ttk.Frame(outer)
        controls.grid(row=3, sticky='ew')
        controls.columnconfigure((3, 5), weight=1)
        self.days = tk.StringVar(value='30')
        self.material_text = tk.StringVar()
        self.sheet = tk.StringVar()
        self.minimum_days = tk.StringVar(value='30')
        self.low_movement = tk.StringVar(value='0')
        self.percent = tk.StringVar(value='50')
        ttk.Label(controls, text='Days').grid(row=0, column=0, sticky='w')
        ttk.Combobox(controls, textvariable=self.days, values=('30','60','90'), state='readonly', width=4).grid(row=0, column=1, padx=4)
        ttk.Label(controls, text='Material ID contains').grid(row=0, column=2, padx=(8, 4))
        ttk.Entry(controls, textvariable=self.material_text, width=12).grid(row=0, column=3, sticky='ew')
        ttk.Label(controls, text='Sheet (blank = all)').grid(row=0, column=4, padx=(8, 4))
        self.sheet_combo = ttk.Combobox(controls, textvariable=self.sheet, width=12)
        self.sheet_combo.grid(row=0, column=5, sticky='ew')
        rules = ttk.Frame(controls)
        rules.grid(row=1, column=0, columnspan=6, sticky='ew', pady=(5, 2))
        for label, variable, width in (('Min span days',self.minimum_days,4),
                                      ('Low movement ≤',self.low_movement,7), ('Large change ≥ %',self.percent,5)):
            ttk.Label(rules, text=label, font=('Segoe UI',9)).pack(side='left', padx=(0, 4))
            ttk.Entry(rules, textvariable=variable, width=width, font=('Segoe UI',9)).pack(side='left', padx=(0, 10))
        ttk.Button(rules, text='Analyze', command=self.query, padding=(8, 1)).pack(side='left', padx=(0, 6))
        ttk.Button(rules, text='Stop', command=self.stop, padding=(8, 1)).pack(side='left')
        self.coverage = tk.Text(outer, height=3, wrap='word', font=('Segoe UI',9), relief='flat')
        self.coverage.grid(row=4, sticky='ew', pady=4)
        self._text(self.coverage, 'Choose a range and optional exact Sheet / partial Material ID, then Analyze. '
                   'The displayed thresholds are adjustable review heuristics, not confirmed business rules.')
        frame = ttk.Frame(outer)
        frame.grid(row=5, sticky='nsew')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        columns = ('Material ID','Sheet','Source file','Last observed UTC','Last observed qty','State','Span days','Movement*','Net*','Signals')
        self.tree = ttk.Treeview(frame, columns=columns, show='headings', selectmode='browse', height=6)
        for name, width in zip(columns,(135,110,180,165,130,105,85,100,100,320)):
            self.tree.heading(name,text=name)
            self.tree.column(name,width=width,minwidth=60,stretch=False)
        self.tree.grid(row=0,column=0,sticky='nsew')
        y = ttk.Scrollbar(frame,orient='vertical',command=self.tree.yview)
        y.grid(row=0,column=1,sticky='ns')
        x = ttk.Scrollbar(frame,orient='horizontal',command=self.tree.xview)
        x.grid(row=1,column=0,sticky='ew')
        self.tree.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        self.tree.bind('<<TreeviewSelect>>', self._selected)
        self.details = tk.Text(outer,height=3,wrap='word',font=('Segoe UI',9),relief='flat')
        self.details.grid(row=6,sticky='ew',pady=(4,0))
        self._text(self.details,'Select a row for timestamps, source versions, raw values, Rack/Level and limitations.')
        footer = ttk.Frame(outer)
        footer.grid(row=7,sticky='ew',pady=(4,0))
        footer.columnconfigure(0,weight=1)
        self.status = tk.StringVar(value='Historical observations only · Cloud Not Verified')
        ttk.Label(footer,textvariable=self.status,font=('Segoe UI',9)).grid(row=0,column=0,sticky='w')
        self.more = ttk.Button(footer,text='Show more',command=self._page,padding=(8,1),state='disabled')
        self.more.grid(row=0,column=1,padx=(6,0))
        ttk.Button(footer,text='Close',command=self.close,padding=(8,1)).grid(row=0,column=2,padx=(6,0))
        for variable in (self.days,self.material_text,self.sheet,self.minimum_days,self.low_movement,self.percent):
            variable.trace_add('write',self._edited)
        self.top.bind('<Configure>',self._fit,add='+')

    def _fit(self,event=None):
        if event is not None and event.widget is not self.top:
            return
        line = int(self.top.tk.call('font','metrics',self.coverage.cget('font'),'-linespace'))
        if self.tree.winfo_height() < line*6:
            self.coverage.configure(height=2)
            self.details.configure(height=2)
        elif self.tree.winfo_height() > line*12:
            self.coverage.configure(height=3)
            self.details.configure(height=3)

    @staticmethod
    def _text(widget,text):
        widget.configure(state='normal')
        widget.delete('1.0','end')
        widget.insert('1.0',text)
        widget.configure(state='disabled')

    def _clear(self):
        self.result = None
        self.shown = 0
        self.tree.delete(*self.tree.get_children())
        self.more.configure(state='disabled')
        self._text(self.details,'No selected result.')

    def _edited(self,*_):
        if self.closed:
            return
        self.generation += 1
        self.cancel.set()
        self._clear()
        self._text(self.coverage,'Options changed; previous analysis discarded. Analyze again.')
        self.status.set('Options changed · Analyze again · Cloud Not Verified')

    def query(self):
        if self.closed:
            return
        self._edited()
        try:
            days = int(self.days.get())
            policy = analytics.Policy(int(self.minimum_days.get()),self.low_movement.get(),self.percent.get())
            if days not in analytics.RANGES:
                raise ValueError('Choose 30, 60 or 90 days.')
        except (ValueError,analytics.AnalyticsError) as exc:
            self.status.set('Invalid options')
            self._text(self.coverage,str(exc))
            return
        generation = self.generation
        cancel = self.cancel = threading.Event()
        database, sheet, text = self.database, self.sheet.get() or None, self.material_text.get()
        self.status.set('Analyzing… · Cloud Not Verified')
        self._text(self.coverage,'Reading one consistent historical database view…')
        self.runner.request(generation,'analysis',lambda:analytics.analyze(database,days,sheet,text,policy=policy,cancel=cancel))

    def stop(self):
        self._edited()
        if not self.closed:
            self.status.set('Cancelled · no result shown · Cloud Not Verified')
            self._text(self.coverage,'Analysis cancelled. No result is shown.')

    def _poll(self):
        if self.closed:
            return
        try:
            while True:
                generation,kind,result,error = self.runner.events.get_nowait()
                if generation != self.generation:
                    continue
                if error is not None:
                    self._clear()
                    self.status.set('QUERY FAILED · no result shown · Cloud Not Verified')
                    self._text(self.coverage,str(error))
                    if isinstance(error,HistoryReadError) and self.on_read_error is not None:
                        self.on_read_error(error)
                    continue
                self.result = result
                self.sheet_combo.configure(values=('',*result.sheet_names))
                summary = (f'{len(result.materials)} material/source groups · {result.snapshots_in_window} snapshots in window · '
                           f'{result.start} → {result.evaluated_at} UTC\n'
                           f'Rules: span ≥ {result.policy.minimum_days} days, movement ≤ {result.policy.low_movement}, '
                           f'large step ≥ {result.policy.large_change_percent}%. Unkeyed historical rows excluded: {result.unkeyed_rows}.\n'
                           '* Movement sums comparable intervals only; net is unknown across gaps. ')
                self._text(self.coverage,summary+' '.join(result.notes))
                self._page()
        except queue.Empty:
            pass
        self.poll_id = self.top.after(50,self._poll)

    def _page(self):
        if self.closed or self.result is None:
            return
        rows = self.result.materials
        for index in range(self.shown,min(self.shown+PAGE,len(rows))):
            row=rows[index]
            last=row.observations[-1]
            self.tree.insert('', 'end',iid=str(index),values=(row.material_key,row.sheet,Path(row.source_path).name,
                             last.observed_at,number(last.value),last.state,f'{row.window_span_days:.2f}',number(row.movement),
                             number(row.net_change),', '.join(row.signals) or 'No heuristic signal'))
        self.shown=min(self.shown+PAGE,len(rows))
        self.more.configure(state='normal' if self.shown<len(rows) else 'disabled')
        self.status.set(f'Showing {self.shown}/{len(rows)} groups · Historical / UNVERIFIED · Cloud Not Verified')

    def _selected(self,_event=None):
        if self.result is None or not self.tree.selection():
            return
        row=self.result.materials[int(self.tree.selection()[0])]
        text=(f'{row.source_path} · Sheet {row.sheet!r} · Material {row.material_key} · '
              f'Description {row.observations[-1].description!r}\n'
              f'{len(row.observations)} observations · {row.comparable_intervals} comparable / {row.changed_intervals} changed intervals · '
              f'longest / trailing unchanged {row.longest_unchanged_days:.2f} / {row.trailing_unchanged_days:.2f} days · '
              f'largest step {number(row.largest_step)} · '
              f'large steps {row.large_change_count}\n'+' '.join(row.notes)+'\n')
        text+='\n'.join(f'{p.observed_at} UTC · v{p.version_id} / snapshot {p.snapshot_id} '
                        f'{"BEFORE WINDOW · " if p.reference else ""}{p.state} · rows {p.rows} · raw {p.raw_quantities!r} · '
                        f'Rack {p.racks!r} · Level {p.levels!r}' for p in row.observations)
        self._text(self.details,text)

    def lift(self):
        self.top.deiconify()
        self.top.lift()

    def close(self):
        if self.closed:
            return
        self.closed=True
        self.cancel.set()
        self.runner.close()
        try:
            while True:
                self.runner.events.get_nowait()
        except queue.Empty:
            pass
        self.top.after_cancel(self.poll_id)
        self.top.destroy()
        if self.on_close is not None:
            self.on_close(self)
