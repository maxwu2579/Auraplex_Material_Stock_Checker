"""Tk chat host. Widgets/dialogs only on Tk's thread; workers communicate through AssistantSession."""
import tkinter as tk
import hashlib
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .assistant import AssistantSession
from .assistant_language import error_text, report_state, route, tr
from .agent import ProviderFailure
from . import narrative, report_delivery
from .daily import DailyRunner
from .core import production_quantity
from .presentation import BG, BLUE, INK, MUTED, Tooltip, work_area
from .quota import notice_text

LANGUAGE_NAMES = ('Auto', 'English', '中文', 'Bahasa Melayu')
LANGUAGE_CODES = ('auto', 'en', 'zh', 'ms')
TOOLS = ('search_materials', 'search_products', 'get_stock', 'get_bom', 'estimate_requirements',
         'material_history', 'material_analysis', 'get_stock_alerts', 'data_status')
TOOL_LABELS = ('Search material IDs', 'Search product Sheets', 'Recorded stock', 'Product BOM',
               'Product shortage estimate', 'Material history', 'Material analysis', 'Recorded stock alerts',
               'Recorded sync status')


class AssistantLauncher:
    def __init__(self, app, footer, *, session=None):
        self.app, self.root = app, app.root
        database = app.inventory.db_path if app.inventory is not None else None
        self.session = session if session is not None else AssistantSession(database)
        self.closed = False
        self.surface = self.view = None
        self.mode = None
        self.language, self.preferred = 'en', 'auto'
        self.draft, self.messages, self.candidates = '', [], []
        self.last_evidence = ''
        self.report_facts = self.report_digest = self.report_basis = None
        self.report_epoch = None          # session epoch the shown preview belongs to
        self.report_narrative = None      # accepted AI text for exactly the shown facts, or None
        self.report_saved = None          # report saved from exactly the shown facts (for the e-mail draft)
        self.report_saved_for = None      # the presentation() that report was saved from
        self.report_generation = 0        # increases with every new, replaced or cleared preview
        self.delivery_jobs = {}           # request ID -> presentation() captured when the job was submitted
        self.narrative_language = None    # language of the narrative request in flight
        self.delivery = DailyRunner()     # one file task at a time; nothing queued behind it
        self.delivery_id = 0
        self.last_folder = None
        self.resize_id = None
        # Draw the robot locally; no emoji-font dependency, images, downloaded assets or external resources.
        self.button = tk.Canvas(footer, width=38, height=25, background=BLUE, highlightthickness=0,
                                cursor='hand2', takefocus=True)
        self.button.grid(row=0, column=2, padx=(10, 0), sticky='e')
        self.button.create_line(19, 3, 19, 6, fill='white', width=2)
        self.button.create_oval(17, 1, 21, 5, fill='white', outline='white')
        self.button.create_rectangle(8, 7, 30, 21, outline='white', width=2)
        for x in (13, 23):
            self.button.create_oval(x-1, 11, x+2, 14, fill='white', outline='white')
        self.button.create_line(15, 18, 24, 18, fill='white', width=1)
        self.button.bind('<Button-1>', lambda _e: self.toggle())
        self.button.bind('<Return>', lambda _e: self.toggle())
        self.button.bind('<space>', lambda _e: self.toggle())
        self.button.bind('<FocusIn>', lambda _e: self.button.configure(highlightthickness=1, highlightbackground='white'))
        self.button.bind('<FocusOut>', lambda _e: self.button.configure(highlightthickness=0))
        Tooltip(self.button, lambda: 'AI Assistant / 库存助手 / Pembantu stok — click to open or close')
        self.root.bind('<Configure>', self._resize, add='+')
        self.poll_id = self.root.after(50, self._poll)

    def _wanted_mode(self):
        scale = max(1, float(self.root.tk.call('tk', 'scaling')) / (96/72))
        return 'docked' if self.root.winfo_width() >= 1440 * scale else 'window'

    def toggle(self):
        if self.closed:
            return
        if self.surface is not None:
            self.hide()
        else:
            self._show()

    def _show(self):
        self.mode = self._wanted_mode()
        if self.mode == 'docked':
            scale = max(1, float(self.root.tk.call('tk', 'scaling')) / (96/72))
            self.surface = ttk.Frame(self.root, width=int(440*scale), padding=(4, 10, 10, 10))
            self.surface.pack(side='right', fill='y', before=self.app.outer)
            self.surface.pack_propagate(False)
            self.app.outer.pack_configure(side='left')
        else:
            self.surface = tk.Toplevel(self.root)
            self.surface.title('Auraplex · Inventory Assistant')
            left, top, width, height = work_area(self.root)
            self.surface.geometry(f'{min(720, width-32)}x{min(720, height-48)}+{left+16}+{top+16}')
            self.surface.minsize(min(480, width-32), min(420, height-48))
            self.surface.protocol('WM_DELETE_WINDOW', self.hide)
        self.view = AssistantView(self.surface, self)
        if not self.messages:
            self.append('Assistant', tr('welcome', self.language))

    def _destroy_surface(self):
        if self.view is not None:
            self.draft = self.view.input.get('1.0', 'end-1c')
            self.view.key.set('')
        if self.surface is not None:
            self.surface.destroy()
        self.surface = self.view = None
        self.app.outer.pack_configure(side='top')

    def hide(self):
        self.invalidate()
        self._destroy_surface()

    def _resize(self, event):
        if event.widget == self.root and self.surface is not None and self.resize_id is None and not self.closed:
            self.resize_id = self.root.after(120, self._adapt)

    def _adapt(self):
        self.resize_id = None
        if self.closed or self.surface is None or self.mode == self._wanted_mode():
            return
        # Rebuild the surface, preserving draft/transcript/session; only the display mode changes.
        self._destroy_surface()
        self._show()

    def invalidate(self):
        if self.closed:
            return
        meaningful = self.session.authorized or self.session.outbound or bool(self.candidates)
        self.session.invalidate()
        self.candidates = []
        self._forget_report()
        if self.view is not None:
            self.view.fill_candidates([])
            self.view.stock_combo.configure(values=())
            self.view.stock.set('')
            self.view.clear_report()
            if meaningful:
                self.append('Assistant', tr('invalidated', self.language))
            self.view.set_busy(self.session.busy)

    def append(self, speaker, text):
        self.messages.append((speaker, text))
        while len(self.messages) > 80 or sum(len(t) for _, t in self.messages) > 160_000:
            self.messages.pop(0)
        if self.view is not None:
            self.view.show_transcript()

    def _language_for(self, question):
        language, uncertain = route(question, self.language, self.preferred, self.session.protected_labels())
        self.language = language
        if uncertain:
            self.append('Assistant', tr('uncertain', language))
        return language

    def start(self, action, *, expected_epoch=None, **payload):
        if self.closed or self.session.busy:
            return False
        if self.app.busy:
            self.append('Assistant', error_text('HOST_BUSY', self.language))
            return False
        if not self.session.submit(action, self.language, expected_epoch=expected_epoch, **payload):
            return False
        if self.view is not None:
            self.view.set_busy(True)
        return True

    def send(self):
        if self.view is None or self.session.busy:
            return
        question = self.view.input.get('1.0', 'end-1c').strip()
        if not question or len(question) > 4000:
            self.append('Assistant', error_text('INVALID_QUESTION', self.language))
            return
        self._language_for(question)
        if self.start('chat', question=question):
            self.append('You', question)
            self.view.input.delete('1.0', 'end')

    def stop(self):
        self.invalidate()
        self.append('Assistant', tr('cancelled', self.language))

    def build_report(self):
        if self.view is None:
            return
        if not self.session.authorized:
            self.append('Assistant', tr('report_no_data', self.language))
            return
        period = ('daily', 'weekly')[self.view.report_period.current() == 1]
        self._forget_report()
        self.view.clear_report()
        self.start('report_preview', period=period)

    def send_report(self):
        if self.view is None or self.session.busy or self.app.busy:
            return
        if not self.session.authorized or self.report_facts is None:
            self.append('Assistant', tr('report_no_data', self.language))
            return
        if not self.session.outbound:
            self.append('Assistant', error_text('OUTBOUND_CONSENT_REQUIRED', self.language))
            return
        epoch = self.session.epoch
        basis, facts, facts_digest = self.report_basis, self.report_facts, self.report_digest
        report_language = self.language
        if self.view.report_shown_language != report_language:
            self.view.show_report(facts, report_language)  # the reviewed preview and the AI language agree
        try:
            if narrative.digest(facts) != facts_digest:
                raise ValueError('The displayed report preview has changed.')
            request_bytes = self.session.provider.preview_narrative(facts, report_language)
            request = request_bytes.decode('utf-8')
            request_sha256 = hashlib.sha256(request_bytes).hexdigest()
        except (ValueError, ProviderFailure):
            self.append('Assistant', error_text('INVALID_ARGUMENTS', self.language))
            return
        dialog = tk.Toplevel(self.root)
        dialog.title(tr('report_confirm_title', self.language))
        _, _, width, height = work_area(self.root)
        dialog.geometry(f'{min(820, width-40)}x{min(680, height-64)}')
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        ttk.Label(frame, text=tr('report_disclosure', self.language), wraplength=720,
                  foreground='#9a4d00').grid(row=0, sticky='ew', pady=(0, 8))
        request_view = tk.Text(frame, wrap='word', font=('Consolas', 9))
        request_view.insert('1.0', request)
        request_view.configure(state='disabled')
        request_view.grid(row=1, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(frame, command=request_view.yview)
        scroll.grid(row=1, column=1, sticky='ns')
        request_view.configure(yscrollcommand=scroll.set)
        answer = [False]
        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, columnspan=2, sticky='e', pady=(8, 0))
        def choose(accepted):
            answer[0] = accepted
            dialog.destroy()
        no = ttk.Button(buttons, text='No / 不允许 / Tidak', command=lambda: choose(False))
        no.pack(side='right')
        ttk.Button(buttons, text='Yes / 允许 / Ya', command=lambda: choose(True)).pack(side='right', padx=8)
        dialog.protocol('WM_DELETE_WINDOW', lambda: choose(False))
        dialog.bind('<Escape>', lambda _e: choose(False))
        dialog.bind('<Return>', lambda _e: choose(False))
        dialog.transient(self.root)
        dialog.grab_set()
        no.focus_set()
        self.root.wait_window(dialog)
        if self.closed:
            return
        if not answer[0]:
            self.append('Assistant', tr('report_declined', self.language))
            return
        if (epoch != self.session.epoch or self.app.busy or not self.session.authorized or
                not self.session.outbound or basis != self.session._authorized_basis):
            self.append('Assistant', tr('invalidated', self.language))
            return
        approval = self.session.approve_report(epoch, basis, facts_digest, report_language, request_sha256, True)
        if approval is None:
            self.append('Assistant', tr('invalidated', self.language))
            return
        self.narrative_language = report_language
        if not self.start('report_narrative', expected_epoch=epoch, approval=approval,
                          basis=basis, facts=facts, facts_digest=facts_digest, report_language=report_language,
                          request_sha256=request_sha256):
            self.session.discard_report_approval(approval)

    # ------------------------------------------------------------------ M4F delivery (local files only)
    def _forget_report(self):
        self.report_generation += 1  # whatever comes next is a different preview, even with equal facts/period
        self.report_facts = self.report_digest = self.report_basis = None
        self.report_epoch = self.report_narrative = self.report_saved = self.report_saved_for = None

    def presentation(self):
        """Immutable identity of what Save would write right now: preview generation, facts digest, data basis,
        session epoch, output language and the exact included AI text (or None). None without a preview."""
        if self.report_facts is None or self.view is None:
            return None
        ai = self.valid_narrative() if self.view.report_include_ai.get() else None
        return (self.report_generation, self.report_digest, self.report_basis, self.report_epoch,
                ai['language'] if ai else self.language,
                hashlib.sha256(ai['text'].encode('utf-8')).hexdigest() if ai else None)

    def saved_report(self):
        """The saved report an e-mail draft may attach: only one saved from exactly the current presentation."""
        current = self.presentation()
        if (self.report_saved is None or current is None or self.report_saved_for != current or
                current[3] != self.session.epoch):
            return None
        return self.report_saved

    def _capture_narrative(self, event, result):
        """Keep an AI reply only if it is the accepted interpretation of exactly the facts on screen."""
        language, self.narrative_language = self.narrative_language, None
        if (result.get('status') != 'NARRATIVE' or self.report_facts is None or event.epoch != self.session.epoch or
                event.epoch != self.report_epoch or result.get('facts_digest') != self.report_digest or
                result.get('basis') != self.report_basis or language not in narrative.LANGUAGES or
                type(result.get('narrative')) is not str or narrative.reply_problems(result['narrative'])):
            return  # rejected, failed, cancelled or stale replies are never kept
        self.report_narrative = {'text': result['narrative'], 'language': language, 'digest': self.report_digest,
                                 'basis': self.report_basis, 'epoch': event.epoch}
        self.report_saved = None

    def valid_narrative(self):
        n = self.report_narrative
        if (n is None or n['digest'] != self.report_digest or n['basis'] != self.report_basis or
                n['epoch'] != self.report_epoch or n['epoch'] != self.session.epoch):
            return None
        return n

    def _delivery_start(self, kind, action, presentation=None):
        if self.delivery.busy:
            self.append('Assistant', tr('delivery_busy', self.language))
            return False
        self.delivery_id += 1
        self.delivery_jobs = {self.delivery_id: presentation}  # only the newest job can be delivered
        self.delivery.request(self.delivery_id, kind, action)
        if self.view is not None:
            self.view.refresh_report_controls()
        return True

    def save_report(self):
        """Save the shown preview as HTML + JSON. The folder is chosen first, without any lock; the worker then
        re-checks the data basis and this session's authorisation right before publishing."""
        if self.closed or self.view is None or self.report_facts is None or not self.session.authorized:
            self.append('Assistant', tr('report_no_data', self.language))
            return
        if self.delivery.busy:
            self.append('Assistant', tr('delivery_busy', self.language))
            return
        facts, digest, basis, epoch = self.report_facts, self.report_digest, self.report_basis, self.report_epoch
        presentation = self.presentation()
        ai = self.valid_narrative() if self.view.report_include_ai.get() else None
        language = presentation[4]
        folder = filedialog.askdirectory(parent=self.surface or self.root, mustexist=True,
                                         title=tr('report_save', self.language),
                                         initialdir=self.last_folder or str(Path.home() / 'Documents'))
        if not folder or self.closed:
            return
        if (facts is not self.report_facts or epoch != self.session.epoch or self.presentation() != presentation or
                (ai is not None and self.valid_narrative() is not ai)):
            self.append('Assistant', tr('report_save_failed', self.language).format(error=report_delivery.STALE))
            return
        self.last_folder = folder
        try:
            document = report_delivery.build_document(facts, digest, basis, language,
                                                      narrative_text=ai['text'] if ai else None)
        except report_delivery.DeliveryError as exc:
            self.append('Assistant', tr('report_save_failed', self.language).format(error=exc))
            return
        session, database = self.session, self.session.tools.database
        self._delivery_start('save', lambda: report_delivery.save_report(
            document, folder, database, basis_of=session.data_basis,
            guard=lambda: session.report_guard(epoch, basis)), presentation)
        self.append('Assistant', tr('report_saving', self.language))

    def email_draft(self):
        if self.closed or self.view is None:
            return
        saved = self.saved_report()  # the handler checks too, not only the button state
        if saved is None:
            self.append('Assistant', tr('report_need_save', self.language))
            return
        self._delivery_start('eml_preview', lambda: (saved, report_delivery.default_subject(saved),
                                                     report_delivery.mail_body(saved)), self.presentation())

    def _drain_delivery(self):
        while True:
            try:
                request_id, kind, result, error = self.delivery.events.get_nowait()
            except Exception:
                break
            if request_id != self.delivery_id or self.closed:
                continue
            submitted = self.delivery_jobs.pop(request_id, None)
            current = submitted is not None and submitted == self.presentation()
            language = self.language
            if error is not None:
                detail = '\n'.join(x for x in (str(error), getattr(error, 'cleanup_warning', '')) if x)
                key = 'report_save_failed' if kind == 'save' else 'email_failed'
                self.append('Assistant', tr(key, language).format(error=detail))
                if isinstance(error, report_delivery.DeliveryStale) and kind == 'save' and current:
                    self._forget_report()  # only the preview this job belonged to; never a newer one
                    if self.view is not None:
                        self.view.clear_report()
                continue
            if kind == 'save':
                self.append('Assistant', tr('report_saved', language).format(path=result.folder))
                if current and submitted[3] == self.session.epoch:
                    self.report_saved, self.report_saved_for = result, submitted
                else:  # the files stay on disk, but they belong to an earlier preview
                    self.append('Assistant', tr('report_saved_other', language))
            elif kind == 'eml_preview':
                saved, subject, body = result
                if current and saved is self.saved_report() and self.view is not None:
                    self.root.after_idle(lambda: self._email_dialog(saved, subject, body))
            elif kind == 'eml_save':
                self.append('Assistant', tr('email_saved', language).format(path=result))
        if self.view is not None:
            self.view.refresh_report_controls()

    def _email_dialog(self, saved, subject, body):
        """Preview of the draft: editable To/Subject, read-only body and the exact attachment list."""
        if self.closed or saved is not self.saved_report():
            return
        lang = saved.language
        dialog = tk.Toplevel(self.root)
        dialog.title(tr('email_title', lang))
        _, _, width, height = work_area(self.root)
        dialog.geometry(f'{min(760, width-40)}x{min(640, height-64)}')
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(3, weight=1)
        ttk.Label(frame, text=tr('email_notice', lang), wraplength=680, foreground='#9a4d00').grid(
            row=0, column=0, columnspan=2, sticky='ew', pady=(0, 8))
        to_var, subject_var = tk.StringVar(), tk.StringVar(value=subject)
        ttk.Label(frame, text=tr('email_to', lang)).grid(row=1, column=0, sticky='w')
        ttk.Entry(frame, textvariable=to_var).grid(row=1, column=1, sticky='ew', pady=2)
        ttk.Label(frame, text=tr('email_subject', lang)).grid(row=2, column=0, sticky='w')
        ttk.Entry(frame, textvariable=subject_var).grid(row=2, column=1, sticky='ew', pady=2)
        text = tk.Text(frame, wrap='word', font=('Segoe UI', 9), height=10)
        text.insert('1.0', body)
        text.configure(state='disabled')
        text.grid(row=3, column=0, columnspan=2, sticky='nsew', pady=(6, 4))
        ttk.Label(frame, text=tr('email_attachments', lang) + ': ' + ', '.join((saved.html.name, saved.json.name)),
                  wraplength=680).grid(row=4, column=0, columnspan=2, sticky='ew')
        error = ttk.Label(frame, text='', foreground='#b00020', wraplength=680)
        error.grid(row=5, column=0, columnspan=2, sticky='ew')
        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=2, sticky='e', pady=(8, 0))

        def save():
            try:
                to = ', '.join(report_delivery.clean_addresses(to_var.get()))
                title = report_delivery.clean_subject(subject_var.get())
            except report_delivery.DeliveryError as exc:
                error.configure(text=str(exc))
                return
            path = filedialog.asksaveasfilename(parent=dialog, defaultextension='.eml', confirmoverwrite=False,
                                                filetypes=[('E-mail draft (.eml)', '*.eml')],
                                                initialdir=str(saved.folder.parent),
                                                initialfile=report_delivery.eml_name(saved),
                                                title=tr('email_save', lang))
            if not path:
                return
            dialog.destroy()
            if self.closed or saved is not self.saved_report():
                self.append('Assistant', tr('report_need_save', self.language))
                return
            self._delivery_start('eml_save', lambda: report_delivery.save_eml(
                report_delivery.build_eml(saved, to=to, subject=title), path))
        cancel = ttk.Button(buttons, text=tr('email_cancel', lang), command=dialog.destroy)
        cancel.pack(side='right')
        ttk.Button(buttons, text=tr('email_save', lang), command=save).pack(side='right', padx=8)
        dialog.bind('<Escape>', lambda _e: dialog.destroy())
        dialog.transient(self.root)
        cancel.focus_set()
        self.email_window = dialog

    def authorize_api(self):
        if self.view is None or self.session.busy or self.app.busy:
            return
        question = self.view.input.get('1.0', 'end-1c').strip()
        if not question or len(question) > 4000:
            self.append('Assistant', error_text('INVALID_QUESTION', self.language))
            return
        self._language_for(question)
        epoch = self.session.epoch
        try:
            preview = self.session.preview_request(question)
        except ProviderFailure as exc:
            self.append('Assistant', error_text(exc.code, self.language))
            return
        dialog = tk.Toplevel(self.root)
        dialog.title('DeepSeek · Outbound consent / 外发授权 / Izin penghantaran')
        _, _, width, height = work_area(self.root)
        dialog.geometry(f'{min(780, width-40)}x{min(620, height-64)}')
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        label = ttk.Label(frame, text=tr('outbound', self.language), wraplength=650)
        label.grid(row=0, sticky='ew', pady=(0, 8))
        text = tk.Text(frame, wrap='word', font=('Consolas', 9))
        text.insert('1.0', self.session.provider.disclosure + '\n\n' + preview)
        text.configure(state='disabled')
        text.grid(row=1, sticky='nsew')
        scroll = ttk.Scrollbar(frame, command=text.yview)
        scroll.grid(row=1, column=1, sticky='ns')
        text.configure(yscrollcommand=scroll.set)
        answer = [False]
        buttons = ttk.Frame(frame)
        buttons.grid(row=2, sticky='e', pady=(8, 0))
        def choose(accepted):
            answer[0] = accepted
            dialog.destroy()
        no = ttk.Button(buttons, text='No / 不允许 / Tidak', command=lambda: choose(False))
        no.pack(side='right')
        ttk.Button(buttons, text='Yes / 允许 / Ya', command=lambda: choose(True)).pack(side='right', padx=8)
        dialog.protocol('WM_DELETE_WINDOW', lambda: choose(False))
        dialog.bind('<Escape>', lambda _e: choose(False))
        dialog.transient(self.root)
        dialog.grab_set()
        no.focus_set()  # no Return binding to Yes; denied by default
        self.root.wait_window(dialog)
        if self.closed:
            return
        if self.session.allow_outbound(epoch, answer[0]) and answer[0]:
            self.append('Assistant', tr('connected', self.language))
        else:
            self.append('Assistant', tr('denied' if not answer[0] else 'invalidated', self.language))

    def local_query(self):
        view = self.view
        if view is None:
            return
        tool = TOOLS[view.tool.current()]
        text = view.local_text.get()
        if tool in ('search_materials', 'search_products'):
            # Material IDs alone are deliberately language-neutral.
            self._language_for(text)
        try:
            quantity = production_quantity(view.quantity.get())
            days = int(view.days.get())
        except ValueError:
            quantity, days = None, None
        self.start('local', tool=tool, text=text, candidate=view.selected_token(),
                   quantity=quantity, days=days, stock_sheet=view.stock.get())

    def _poll(self):
        if self.closed:
            return
        for event in self.session.drain():
            result = event.result
            if result.get('error') in ('DATABASE_READ_FAILED', 'STALE_DATA', 'STALE_SESSION'):
                self._forget_report()
                if self.view is not None:
                    self.view.clear_report()
            if event.action == 'report_preview':
                if result.get('status') == 'REPORT_PREVIEW' and self.session.authorized and not self.closed:
                    try:
                        facts = narrative.validate_facts(result['facts'])
                        if (event.epoch != self.session.epoch or result['basis'] != self.session._authorized_basis or
                                narrative.digest(facts) != result['facts_digest']):
                            raise ValueError('stale preview')
                        self._forget_report()
                        self.report_facts, self.report_digest, self.report_basis = facts, result['facts_digest'], result['basis']
                        self.report_epoch = event.epoch
                        if self.view is not None:
                            self.view.show_report(facts)
                    except (ValueError, KeyError):
                        self._forget_report()
                        if self.view is not None:
                            self.view.clear_report()
                elif result.get('error') in ('STALE_DATA', 'DATABASE_READ_FAILED'):
                    self._forget_report()
                    if self.view is not None:
                        self.view.clear_report()
            if event.action == 'report_narrative':
                self._capture_narrative(event, result)
            if event.action == 'preview_data' and result.get('status') == 'PREVIEW':
                observation = result['observation']
                lines = [tr('consent', event.language), tr('history', event.language)]
                for version in observation['provenance']['versions']:
                    lines.append(f"{version['role']}: {version['source_path']}\nv{version['id']} · imported={version['imported_at']}\nsha256={version['file_sha256']}")
                lines.append(tr('recorded_only', event.language))
                for role, state in observation['data']['recorded_states'].items():
                    lines.append(f"{role} · {state['state']} · {state['last_checked']}")
                accepted = messagebox.askyesno('Historical data / 历史资料 / Data sejarah', '\n\n'.join(lines),
                                              parent=self.surface or self.root, default='no')
                if not self.closed and event.epoch == self.session.epoch and not self.app.busy and accepted:
                    self.start('authorize', expected_epoch=event.epoch, expected_basis=result['basis'])
                elif not self.closed:
                    self.append('Assistant', tr('denied' if not accepted else 'invalidated', event.language))
                continue
            if result.get('error') == 'DATABASE_READ_FAILED' and self.app.inventory is not None:
                self.app.alert_read_failed('assistant database read failed')
            self.append('Assistant', event.reply)
            self.last_evidence = event.evidence_text
            if not self.session.authorized:
                self.candidates = []
            if 'candidates' in result:
                self.candidates = result['candidates']
            if self.view is not None:
                self.view.show_evidence()
                if 'candidates' in result or not self.session.authorized:
                    self.view.fill_candidates(self.candidates)
                if self.candidates and 'candidates' in result:
                    self.view.tabs.select(self.view.local_page)
                elif event.action == 'local':
                    self.view.tabs.select(self.view.chat_page)
                sheets = self.session.context.get('stock_sheets', ())
                self.view.stock_combo.configure(values=sheets)
                if self.view.stock.get() not in sheets:
                    self.view.stock.set('')  # no automatic selection of an assembly/storage configuration
        self._drain_delivery()
        if self.view is not None:
            self.view.set_busy(self.session.busy)
            self.view.refresh_report_controls()
            if self.report_facts is not None and self.view.report_shown_language not in (None, self.language):
                self.view.show_report(self.report_facts)  # same facts/digest; the AI language follows this preview
            for label, text in ((self.view.banner, tr('history', self.language)), (self.view.caveat, tr('caveat', self.language))):
                if label.cget('text') != text:
                    label.configure(text=text)
            state = self.session.provider.quota_status()
            info = [f"{tr('api_consent', self.language)}: {'ON' if self.session.outbound else 'OFF'} · Local: {'UNVERIFIED selected' if self.session.authorized else 'not authorized'}"]
            balance = state['balance']
            info.append(' / '.join(f"{r['currency']} {r['balance']}" for r in balance['currencies']) if balance else tr('quota_unknown', self.language))
            info.append(f"{state['checked_at'] or '—'} · {tr('due', self.language)}={state['balance_check_due']}")
            if state['last_request_usage']:
                info.append(f"{tr('usage', self.language)}: {state['last_request_usage']['total_tokens']}")
            if state['notices']:
                # Persistent canonical warning codes as well as translated, deduplicated chat notices.
                info.append(' / '.join(n['code'] for n in state['notices']))
            quota_text = ' · '.join(info)
            if self.view.quota.cget('text') != quota_text:
                self.view.quota.configure(text=quota_text)
            for notice in self.session.provider.take_notifications():
                self.append('Assistant', notice_text(notice['code'], self.language))
        if not self.closed:
            self.poll_id = self.root.after(75, self._poll)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.delivery.close()  # a running write finishes (complete or nothing); its result is not delivered
        self.session.close()
        self.root.after_cancel(self.poll_id)
        if self.resize_id is not None:
            self.root.after_cancel(self.resize_id)
        self._destroy_surface()


class AssistantView:
    def __init__(self, parent, host):
        self.host = host
        self._busy, self._wrap_width = None, None
        self.wrapped = []
        frame = ttk.Frame(parent, padding=8)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)
        header = ttk.Frame(frame)
        header.grid(row=0, sticky='ew')
        ttk.Label(header, text='Inventory Assistant', font=('Segoe UI', 12, 'bold')).pack(side='left')
        ttk.Button(header, text='×', width=2, command=host.hide, padding=(6, 1)).pack(side='right')
        self.language_combo = ttk.Combobox(header, values=LANGUAGE_NAMES, state='readonly', width=14)
        self.language_combo.current(LANGUAGE_CODES.index(host.preferred))
        self.language_combo.pack(side='right', padx=6)
        self.language_combo.bind('<<ComboboxSelected>>', self._language)
        self.banner = ttk.Label(frame, text=tr('history', host.language), foreground='#9a4d00', font=('Segoe UI', 9, 'bold'), wraplength=400)
        self.banner.grid(row=1, sticky='ew', pady=(6, 2))
        permissions = ttk.Frame(frame)
        permissions.grid(row=2, sticky='ew', pady=(3, 6))
        self.history_button = ttk.Button(permissions, text='Select historical data…', command=lambda: host.start('preview_data'), padding=(6, 3))
        self.history_button.pack(side='left')
        self.ai_button = ttk.Button(permissions, text='AI permission…', command=host.authorize_api, padding=(6, 3))
        self.ai_button.pack(side='left', padx=4)
        ttk.Button(permissions, text='Disconnect', command=host.stop, padding=(6, 3)).pack(side='right')
        self.tabs = ttk.Notebook(frame)
        self.tabs.grid(row=3, sticky='nsew')
        chat = ttk.Frame(self.tabs, padding=4)
        self.chat_page = chat
        chat.columnconfigure(0, weight=1)
        chat.rowconfigure(0, weight=1)
        self.transcript = tk.Text(chat, wrap='word', font=('Segoe UI', 10), state='disabled', width=28, height=5,
                                  background='white', foreground=INK, relief='flat', padx=9, pady=7)
        self.transcript.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(chat, command=self.transcript.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.transcript.configure(yscrollcommand=scroll.set)
        self.transcript.tag_configure('speaker', foreground=BLUE, font=('Segoe UI', 10, 'bold'))
        self.input = tk.Text(chat, height=3, wrap='word', font=('Segoe UI', 10), width=20, relief='solid', borderwidth=1)
        self.input.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(6, 4))
        self.input.insert('1.0', host.draft)
        self.input.bind('<Return>', self._enter)
        self.input.bind('<Shift-Return>', lambda _e: None)
        commands = ttk.Frame(chat)
        commands.grid(row=2, column=0, columnspan=2, sticky='ew')
        self.send_button = ttk.Button(commands, text='Send', command=host.send, padding=(10, 3))
        self.send_button.pack(side='right')
        self.stop_button = ttk.Button(commands, text='Stop', command=host.stop, padding=(10, 3))
        self.stop_button.pack(side='right', padx=5)
        self.quick = ttk.Combobox(commands, values=('Stock lookup', 'Low stock', 'History', 'Product shortage'), state='readonly', width=17)
        self.quick.set('Quick questions…')
        self.quick.pack(side='left')
        self.quick.bind('<<ComboboxSelected>>', self._quick)
        self.tabs.add(chat, text='Chat')
        self._local_tab()
        self._settings_tab()
        self._report_tab()
        evidence = ttk.Frame(self.tabs)
        evidence.columnconfigure(0, weight=1)
        evidence.rowconfigure(1, weight=1)
        evidence_note = ttk.Label(evidence, text='Local canonical evidence · original source values · no API export', wraplength=400)
        evidence_note.grid(row=0, sticky='ew')
        self.wrapped.append(evidence_note)
        self.evidence = tk.Text(evidence, wrap='none', font=('Consolas', 9), state='disabled', width=28, height=5)
        self.evidence.grid(row=1, sticky='nsew')
        y = ttk.Scrollbar(evidence, command=self.evidence.yview)
        y.grid(row=1, column=1, sticky='ns')
        x = ttk.Scrollbar(evidence, orient='horizontal', command=self.evidence.xview)
        x.grid(row=2, sticky='ew')
        self.evidence.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        self.tabs.add(evidence, text='Evidence')
        self.caveat = ttk.Label(frame, text=tr('caveat', host.language), foreground=MUTED, font=('Segoe UI', 8), wraplength=400)
        self.caveat.grid(row=4, sticky='ew', pady=(5, 2))
        self.quota = ttk.Label(frame, text='', foreground='#905919', font=('Segoe UI', 8), wraplength=400)
        self.quota.grid(row=5, sticky='ew')
        frame.bind('<Configure>', lambda e: self._wrap(e.width))
        self.show_transcript()
        self.show_evidence()
        self.fill_candidates(host.candidates)
        self.set_busy(host.session.busy)

    def _report_tab(self):
        page = ttk.Frame(self.tabs, padding=5)
        self.report_page = page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        intro = ttk.Label(page, text=tr('report_intro', self.host.language), wraplength=380)
        intro.grid(row=0, column=0, sticky='ew', pady=(0, 6))
        self.wrapped.append(intro)
        controls = ttk.Frame(page)
        controls.grid(row=1, column=0, sticky='ew', pady=(0, 5))
        ttk.Label(controls, text=tr('report_period', self.host.language)).pack(side='left')
        self.report_period = ttk.Combobox(controls,
                                          values=(tr('daily', self.host.language), tr('weekly', self.host.language)),
                                          state='readonly', width=10)
        self.report_period.current(0)
        self.report_period.pack(side='left', padx=4)
        self.report_build_button = ttk.Button(controls, text=tr('report_build', self.host.language),
                                              command=self.host.build_report, padding=(6, 3))
        self.report_build_button.pack(side='left', padx=(3, 0))
        self.report_send_button = ttk.Button(controls, text=tr('report_send', self.host.language),
                                             command=self.host.send_report, padding=(6, 3))
        self.report_send_button.pack(side='right')
        self.report_shown_language = None  # language of the rendered preview; re-rendered after a switch
        self.report_preview = tk.Text(page, wrap='word', font=('Segoe UI', 9), width=30, height=5,
                                      background='white', foreground=INK, relief='flat', padx=8, pady=6,
                                      state='disabled')
        self.report_preview.grid(row=2, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(page, command=self.report_preview.yview)
        scroll.grid(row=2, column=1, sticky='ns')
        self.report_preview.configure(yscrollcommand=scroll.set)
        delivery = ttk.Frame(page)
        delivery.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(5, 0))
        self.report_include_ai = tk.BooleanVar(value=False)
        self.report_ai_check = ttk.Checkbutton(delivery, text=tr('report_include_ai', self.host.language),
                                               variable=self.report_include_ai)
        self.report_ai_check.pack(side='left')
        self.report_email_button = ttk.Button(delivery, text=tr('report_email', self.host.language),
                                              command=self.host.email_draft, padding=(6, 3))
        self.report_email_button.pack(side='right')
        self.report_save_button = ttk.Button(delivery, text=tr('report_save', self.host.language),
                                             command=self.host.save_report, padding=(6, 3))
        self.report_save_button.pack(side='right', padx=4)
        self.report_ai_note = ttk.Label(page, text='', foreground=MUTED, font=('Segoe UI', 8), wraplength=380)
        self.report_ai_note.grid(row=4, column=0, columnspan=2, sticky='ew')
        self.wrapped.append(self.report_ai_note)
        self.tabs.add(page, text=tr('report_tab', self.host.language))

    def _wrap(self, width):
        if width == self._wrap_width:
            return
        self._wrap_width = width
        for label in (self.banner, self.caveat, self.quota):
            label.configure(wraplength=max(180, width-16))
        for label in self.wrapped:
            label.configure(wraplength=max(180, width-48))

    def _enter(self, event):
        if event.state & 1:
            return None
        self.host.send()
        return 'break'

    def _language(self, _event=None):
        self.host.preferred = LANGUAGE_CODES[self.language_combo.current()]
        if self.host.preferred != 'auto':
            self.host.language = self.host.preferred

    def _quick(self, _event=None):
        index = self.quick.current()
        prompts = {
            'en': ('How much stock is recorded for ', 'Show low stock alerts', 'Show material history for ', 'Estimate product shortage for '),
            'zh': ('帮我查询库存，编号 ', '查询低库存提醒', '查询材料历史，编号 ', '查询产品试算缺口，产品 '),
            'ms': ('Berapa baki stok bagi ', 'Tunjuk amaran stok rendah', 'Tunjuk sejarah bahan bagi ', 'Anggar kekurangan produk bagi ')}
        self.input.delete('1.0', 'end')
        self.input.insert('1.0', prompts[self.host.language][index])
        self.input.focus_set()

    def _local_tab(self):
        local = ttk.Frame(self.tabs, padding=5)
        self.local_page = local
        local.columnconfigure(1, weight=1)
        local.rowconfigure(5, weight=1)
        intro = ttk.Label(local, text='Offline tools · exact IDs / original Sheets', wraplength=350)
        intro.grid(row=0, column=0, columnspan=3, sticky='ew')
        self.wrapped.append(intro)
        ttk.Label(local, text='Action').grid(row=1, column=0, sticky='w', pady=3)
        self.tool = ttk.Combobox(local, values=TOOL_LABELS, state='readonly', width=20)
        self.tool.current(0)
        self.tool.grid(row=1, column=1, columnspan=2, sticky='ew')
        self.local_text = tk.StringVar()
        ttk.Label(local, text='Search text').grid(row=2, column=0, sticky='w')
        ttk.Entry(local, textvariable=self.local_text).grid(row=2, column=1, sticky='ew')
        self.local_button = ttk.Button(local, text='Run', command=self.host.local_query, padding=(8, 3))
        self.local_button.grid(row=2, column=2, padx=(4, 0))
        options = ttk.Frame(local)
        options.grid(row=3, column=0, columnspan=3, sticky='ew', pady=4)
        options.columnconfigure(1, weight=1)
        ttk.Label(options, text='Storage Sheet').grid(row=0, column=0, sticky='w')
        self.stock = tk.StringVar()
        self.stock_combo = ttk.Combobox(options, textvariable=self.stock, state='readonly', width=12,
                                       values=self.host.session.context.get('stock_sheets', ()))
        self.stock_combo.grid(row=0, column=1, sticky='ew', padx=4)
        self.quantity = tk.StringVar(value='1')
        self.days = tk.StringVar(value='30')
        ttk.Label(options, text='Qty').grid(row=1, column=0, sticky='w')
        ttk.Entry(options, textvariable=self.quantity, width=9).grid(row=1, column=1, sticky='w', padx=4)
        ttk.Combobox(options, textvariable=self.days, values=('30', '60', '90'), state='readonly', width=5).grid(row=1, column=2)
        hint = ttk.Label(local, text='Select a real row, then choose a lookup action.', wraplength=350)
        hint.grid(row=4, column=0, columnspan=3, sticky='ew')
        self.wrapped.append(hint)
        self.candidate_tree = ttk.Treeview(local, columns=('kind', 'id', 'sheet'), show='headings', height=3, selectmode='browse')
        for ident, width in (('kind', 70), ('id', 130), ('sheet', 150)):
            self.candidate_tree.heading(ident, text=ident)
            self.candidate_tree.column(ident, width=width, minwidth=50)
        self.candidate_tree.grid(row=5, column=0, columnspan=3, sticky='nsew')
        y = ttk.Scrollbar(local, command=self.candidate_tree.yview)
        y.grid(row=5, column=3, sticky='ns')
        x = ttk.Scrollbar(local, orient='horizontal', command=self.candidate_tree.xview)
        x.grid(row=6, column=0, columnspan=3, sticky='ew')
        self.candidate_tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        self.candidate_tree.bind('<<TreeviewSelect>>', self._selected)
        self.tabs.add(local, text='Local tools')

    def _selected(self, _event=None):
        token = self.selected_token()
        match = next((r for r in self.host.candidates if r['token'] == token), None)
        if match:
            self.tool.current(2 if match['kind'] == 'material' else 3)

    def selected_token(self):
        selected = self.candidate_tree.selection()
        return selected[0] if selected else None

    def fill_candidates(self, rows):
        selected = self.selected_token()
        self.candidate_tree.delete(*self.candidate_tree.get_children())
        for candidate in rows:
            row = candidate['row']
            self.candidate_tree.insert('', 'end', iid=candidate['token'], values=(candidate['kind'], row.get('material_id', row['sheet']), repr(row['sheet'])))
        if selected and self.candidate_tree.exists(selected):
            self.candidate_tree.selection_set(selected)

    def _settings_tab(self):
        frame = ttk.Frame(self.tabs, padding=10)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)
        intro = ttk.Label(frame, text='DeepSeek · deepseek-flash\nOpening this tab does not read/send a key. Keys use your Windows vault; no plaintext fallback.', wraplength=350)
        intro.grid(row=0, sticky='ew')
        self.wrapped.append(intro)
        self.key = tk.StringVar()
        self.key_entry = ttk.Entry(frame, textvariable=self.key, show='•')
        self.key_entry.grid(row=1, sticky='ew', pady=8)
        buttons = ttk.Frame(frame)
        buttons.grid(row=2, sticky='ew')
        self.save_key = ttk.Button(buttons, text='Save key', command=self._save_key, padding=(6, 3))
        self.save_key.pack(side='left')
        self.delete_key = ttk.Button(buttons, text='Remove key…', command=self._delete_key, padding=(6, 3))
        self.delete_key.pack(side='left', padx=6)
        ttk.Button(frame, text='Recheck balance on next Send', command=self._balance, padding=(6, 3)).grid(row=3, sticky='w', pady=10)
        self.limits = tk.Text(frame, height=3, wrap='word', font=('Segoe UI', 9), relief='flat', width=20, background=BG)
        self.limits.insert('1.0', 'Defaults: USD ≤ 1.00 / CNY ≤ 5.00 independently.\n10 chat attempts per authorized session.\nBalance is an observation; no remaining-Token estimate.\nOnly the next authorized Send checks balance.\nStop / close / Refresh revoke both permissions.\nTranscript: memory only, last 80 entries / 160k chars.')
        self.limits.configure(state='disabled')
        self.limits.grid(row=4, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(frame, command=self.limits.yview)
        scroll.grid(row=4, column=1, sticky='ns')
        self.limits.configure(yscrollcommand=scroll.set)
        self.tabs.add(frame, text='Settings')

    def _save_key(self):
        if self.host.session.busy:
            return
        key = self.key.get()
        self.key.set('')
        self.host.start('save_key', key=key)

    def _delete_key(self):
        epoch = self.host.session.epoch
        if not self.host.session.busy and messagebox.askyesno('Remove stored API key?', 'Remove only this application\'s current-user key?',
                                                             parent=self.host.surface, default='no'):
            if epoch == self.host.session.epoch:
                self.host.start('delete_key', expected_epoch=epoch)

    def _balance(self):
        self.host.session.provider.request_balance_refresh()
        self.host.append('Assistant', tr('armed', self.host.language))

    def show_transcript(self):
        self.transcript.configure(state='normal')
        self.transcript.delete('1.0', 'end')
        for speaker, text in self.host.messages:
            self.transcript.insert('end', speaker + '\n', 'speaker')
            self.transcript.insert('end', text + '\n\n')
        self.transcript.configure(state='disabled')
        self.transcript.see('end')

    def show_evidence(self):
        self.evidence.configure(state='normal')
        self.evidence.delete('1.0', 'end')
        text = self.host.last_evidence
        self.evidence.insert('1.0', text[:200_000] + ('\n[DISPLAY TRUNCATED]' if len(text) > 200_000 else ''))
        self.evidence.configure(state='disabled')

    def set_busy(self, busy):
        if self._busy == busy:
            return
        self._busy = busy
        for button in (self.send_button, self.local_button, self.history_button, self.ai_button, self.save_key,
                       self.delete_key, self.report_build_button, self.report_send_button):
            button.configure(state='disabled' if busy else 'normal')
        self.stop_button.configure(state='normal' if busy else 'disabled')
        self.refresh_report_controls()

    def refresh_report_controls(self):
        busy = self.host.session.busy or self.host.app.busy
        self.report_build_button.configure(state='normal' if self.host.session.authorized and not busy else 'disabled')
        can_send = (self.host.session.authorized and self.host.session.outbound and
                    self.host.report_facts is not None and not busy)
        self.report_send_button.configure(state='normal' if can_send else 'disabled')
        writing = self.host.delivery.busy
        has_report = self.host.session.authorized and self.host.report_facts is not None
        self.report_save_button.configure(state='normal' if has_report and not writing else 'disabled')
        self.report_email_button.configure(state='normal' if self.host.saved_report() is not None and not writing
                                           else 'disabled')
        ai = self.host.valid_narrative() if has_report else None
        if ai is None and self.report_include_ai.get():
            self.report_include_ai.set(False)  # an invalid or stale AI text can never be ticked in
        self.report_ai_check.configure(state='normal' if ai is not None and not writing else 'disabled')
        note = (tr('report_ai_ready', self.host.language).format(language=narrative.LANGUAGES[ai['language']])
                if ai is not None else tr('report_no_ai', self.host.language) if has_report else '')
        if self.report_ai_note.cget('text') != note:
            self.report_ai_note.configure(text=note)

    def clear_report(self):
        self.report_shown_language = None
        self.report_preview.configure(state='normal')
        self.report_preview.delete('1.0', 'end')
        self.report_preview.configure(state='disabled')
        self.refresh_report_controls()

    def show_report(self, facts, language=None):
        """Render validated facts in the given (default: current) language. Rendering never changes the facts, their
        digest or any approval; a re-render after a language switch uses exactly the same facts."""
        lang = language or self.host.language
        t = lambda key, **values: tr(key, lang).format(**values)
        unknown = tr('rp_unknown', lang)
        lines = [t('rp_title', period=tr('daily' if facts['period'] == 'DAILY' else 'weekly', lang)),
                 t('rp_generated', value=facts['generated_utc'])]
        for title, period in (('rp_current', facts['current_period']), ('rp_previous', facts['previous_period'])):
            if period is None:
                continue
            lines += ['', f"{tr(title, lang)}: {period['window']['start_local']} → {period['window']['end_local']}",
                      t('rp_stats', coverage=report_state(period['coverage'], lang), snapshots=period['snapshots'],
                        attempts=period['stock_sync_attempts'], checks=period['successful_stock_checks'],
                        events=period['observed_change_events'], ids=period['distinct_material_ids'])]
            for kind, count in period['changes_by_type'].items():
                lines.append(t('rp_type', kind=kind, events=count['events'], ids=count['distinct_material_ids']))
        comparison = facts['comparison']
        lines += ['', t('rp_comparison', status=report_state(comparison['status'], lang))]
        if comparison['change_event_delta_by_type'] is not None:
            for kind, delta in comparison['change_event_delta_by_type'].items():
                lines.append(t('rp_delta', kind=kind, delta=unknown if delta is None else f'{delta:+d}'))
        alerts = facts['recorded_alerts']
        lines += ['', t('rp_alerts', status=report_state(alerts['status'], lang), value=alerts['evaluated_utc'] or unknown)]
        if alerts['counts_by_type'] is None:
            lines.append(tr('rp_alerts_unknown', lang))
        else:
            lines.extend(f"  {kind}: {count}" for kind, count in alerts['counts_by_type'].items())
        lines += ['', tr('rp_sync', lang)]
        for role, sync in facts['latest_sync_attempts'].items():
            lines.append(f"  {role}: {sync['outcome']} · {sync['finished_utc'] or unknown}")
        quality = facts['data_quality']
        lines += ['', tr('rp_quality', lang)]
        if quality['latest_retained_storage'] is None:
            lines.append(tr('rp_storage_unknown', lang))
        else:
            lines.append(tr('rp_storage', lang))
            lines.extend(f"    {name}: {count}" for name, count in quality['latest_retained_storage'].items())
        for role, counts in quality['recorded_issue_rows'].items():
            for name, count in counts.items():
                lines.append(t('rp_issue', role=role, name=name, count=unknown if count is None else count))
        lines += [''] + tr('rp_limits', lang).split('\n')
        self.report_preview.configure(state='normal')
        self.report_preview.delete('1.0', 'end')
        self.report_preview.insert('1.0', '\n'.join(lines))
        self.report_preview.configure(state='disabled')
        self.report_shown_language = lang
        self.refresh_report_controls()
