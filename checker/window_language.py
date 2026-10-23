"""UI-thread-only rendering of stored window messages; never schedules work or reads application data."""
import tkinter as tk
from . import i18n


class WindowLanguage:
    def __init__(self, language, resources, make_message):
        self.language = language
        self.resources = resources
        self.message = make_message
        self.labels, self.bodies, self.variables, self.headings = {}, {}, {}, {}

    def text(self, value):
        return i18n.render(value, self.language.language)

    def label(self, widget, value):
        self.labels[widget] = value
        widget.configure(text=self.text(value))

    def body(self, widget, value):
        self.bodies[widget] = value
        view = widget.yview()
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', self.text(value))
        widget.configure(state='disabled')
        if view:
            widget.yview_moveto(view[0])

    def status(self, variable, value):
        self.variables[variable._name] = (variable, value)
        variable.set(self.text(value))

    def register(self, root, trees=()):
        pending = [root]
        while pending:
            widget = pending.pop()
            try:
                value = str(widget.cget('text'))
                if not str(widget.cget('textvariable')) and value in self.resources:
                    self.labels[widget] = self.message(value)
            except tk.TclError:
                pass
            pending.extend(widget.winfo_children())
        for tree in trees:
            for column in tree['columns']:
                template = tree.heading(column, 'text')
                self.headings[(tree, column)] = self.message(template)

    def render(self):
        for widget, value in self.labels.items():
            widget.configure(text=self.text(value))
        for widget, value in self.bodies.items():
            # Do not alter the message registry while iterating it.
            view = widget.yview()
            widget.configure(state='normal')
            widget.delete('1.0', 'end')
            widget.insert('1.0', self.text(value))
            widget.configure(state='disabled')
            if view:
                widget.yview_moveto(view[0])
        for variable, value in self.variables.values():
            variable.set(self.text(value))
        for (tree, column), value in self.headings.items():
            tree.heading(column, text=self.text(value))
