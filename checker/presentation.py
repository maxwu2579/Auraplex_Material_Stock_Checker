"""Display helpers only; these never read, match or calculate materials."""
import tkinter as tk
from tkinter import ttk, font

# B1 light-blue workbench tokens (row colours below are unchanged).
BG, INK, MUTED, BLUE = "#eef5fc", "#132f4c", "#4b6684", "#1f6fbf"
RED, AMBER = "#fde9e7", "#fff4d6"


def ellipsize(text, pixels, font_spec, middle=False):
    face = font.Font(font=font_spec)
    if face.measure(text) <= pixels:
        return text
    for length in range(len(text) - 1, -1, -1):
        left = (length + 1) // 2
        shortened = text[:left] + "…" + (text[-(length // 2):] if length // 2 else "") if middle else text[:length] + "…"
        if face.measure(shortened) <= pixels:
            return shortened
    return "…"


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.window = self.timer = None
        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    def schedule(self, _event=None):
        self.hide()
        self.timer = self.widget.after(600, self.show)

    def show(self):
        self.timer = None
        text = self.text()
        if not text:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        ttk.Label(self.window, text=text, padding=10, wraplength=650,
                  background="#ffffff", foreground=INK, relief="solid", borderwidth=1).pack()
        self.window.update_idletasks()
        x = min(self.widget.winfo_rootx(), self.window.winfo_screenwidth() - self.window.winfo_reqwidth() - 12)
        y = min(self.widget.winfo_rooty() + self.widget.winfo_height() + 6,
                self.window.winfo_screenheight() - self.window.winfo_reqheight() - 48)
        self.window.geometry(f"+{max(0, x)}+{max(0, y)}")

    def hide(self, _event=None):
        if self.timer:
            self.widget.after_cancel(self.timer)
            self.timer = None
        if self.window:
            self.window.destroy()
            self.window = None


def fill_summary(widget, summary, details="", title="", expanded=False):
    """Read-only Text: the summary first, then the details under a title. The details stay in the widget but are
    hidden (elided) until expanded, so opening a report never starts with logs or hundreds of rows."""
    view = widget.yview()
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", summary)
    widget.tag_configure("summary_title", font=("Segoe UI", 9, "bold"))
    widget.tag_configure("details", elide=not expanded)
    if details:
        widget.insert("end", "\n\n")
        widget.insert("end", (title + "\n") if title else "", ("details", "summary_title"))
        widget.insert("end", details, ("details",))
    widget.configure(state="disabled")
    if view:
        widget.yview_moveto(view[0])


def work_area(root):
    """Use Windows' work area, including the taskbar, without changing DPI settings."""
    if root.tk.call("tk", "windowingsystem") == "win32":
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()
