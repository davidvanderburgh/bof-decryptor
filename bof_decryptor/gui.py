"""Main window GUI for BOF Asset Decryptor."""

import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog
import webbrowser

from .config import KNOWN_GAMES, DECRYPT_PHASES, MODIFY_PHASES


def _platform_font():
    if sys.platform == "win32":
        return "Segoe UI", "Consolas"
    elif sys.platform == "darwin":
        return "SF Pro Text", "Menlo"
    return "sans-serif", "monospace"


_SANS_FONT, _MONO_FONT = _platform_font()

_THEMES = {
    "dark": {
        "bg": "#2d2d2d", "fg": "#cccccc", "field_bg": "#1e1e1e",
        "select_bg": "#264f78", "accent": "#569cd6", "success": "#6a9955",
        "error": "#f44747", "timestamp": "#808080", "gray": "#808080",
        "trough": "#404040", "border": "#555555", "button": "#404040",
        "tab_selected": "#1e1e1e", "link": "#3794ff",
        "tooltip_bg": "#404040", "tooltip_fg": "#cccccc",
    },
    "light": {
        "bg": "#f5f5f5", "fg": "#1e1e1e", "field_bg": "#ffffff",
        "select_bg": "#0078d7", "accent": "#0066cc", "success": "#2e7d32",
        "error": "#c62828", "timestamp": "#757575", "gray": "#888888",
        "trough": "#d0d0d0", "border": "#bbbbbb", "button": "#e0e0e0",
        "tab_selected": "#ffffff", "link": "#0066cc",
        "tooltip_bg": "#ffffe0", "tooltip_fg": "#1e1e1e",
    },
}


class _Tooltip:
    def __init__(self, widget, text, theme_fn):
        self._widget = widget
        self.text = text
        self._theme_fn = theme_fn
        self._tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, event=None):
        c = _THEMES[self._theme_fn()]
        x = self._widget.winfo_rootx() + self._widget.winfo_width() // 2
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        self._tip.configure(background=c["tooltip_bg"])
        label = tk.Label(self._tip, text=self.text, background=c["tooltip_bg"],
                         foreground=c["tooltip_fg"], relief="solid", borderwidth=1,
                         font=(_SANS_FONT, 9), padx=6, pady=2,
                         wraplength=400, justify=tk.LEFT)
        label.pack()

    def _hide(self, event=None):
        if self._tip:
            self._tip.destroy()
            self._tip = None


class MainWindow:
    """Single-window tkinter GUI with Decrypt, Write, and Mod Pack tabs."""

    def __init__(self, root, on_check_prereqs, on_start, on_cancel,
                 on_mod_apply=None, on_mod_cancel=None,
                 on_theme_change=None, initial_theme=None,
                 on_install_prereqs=None,
                 on_import=None, on_export=None):
        self.root = root
        self._on_check_prereqs = on_check_prereqs
        self._on_start = on_start
        self._on_cancel = on_cancel
        self._on_mod_apply = on_mod_apply
        self._on_mod_cancel = on_mod_cancel
        self._on_theme_change = on_theme_change
        self._on_install_prereqs = on_install_prereqs
        self._on_import = on_import
        self._on_export = on_export

        root.geometry("760x880")
        root.minsize(680, 620)

        # Set window icon
        if sys.platform == "win32":
            icon_path = os.path.join(os.path.dirname(__file__), "icon.ico")
            if os.path.isfile(icon_path):
                try:
                    root.iconbitmap(icon_path)
                except tk.TclError:
                    pass
        else:
            icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
            if os.path.isfile(icon_path):
                try:
                    icon_img = tk.PhotoImage(file=icon_path)
                    root.iconphoto(True, icon_img)
                    self._icon_img = icon_img
                except tk.TclError:
                    pass

        self._start_time = None
        self._timer_id = None
        self._current_theme = initial_theme or self._detect_system_theme()
        self._prereq_state = {}

        # Public tk vars
        self.fun_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.write_input_var = tk.StringVar()
        self.write_output_var = tk.StringVar()
        self.write_game_var = tk.StringVar()
        self.modify_input_var = tk.StringVar()  # alias used by app.py for export

        self._build_ui()
        self._init_phase_steps()
        self._apply_theme(self._current_theme)

        # sync modify_input_var with write_input_var
        self.write_input_var.trace_add("write",
            lambda *_: self.modify_input_var.set(self.write_input_var.get()))

    @staticmethod
    def _detect_system_theme():
        if sys.platform == "win32":
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                )
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                winreg.CloseKey(key)
                return "light" if value else "dark"
            except Exception:
                return "light"
        elif sys.platform == "darwin":
            try:
                import subprocess as sp
                r = sp.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                           capture_output=True, text=True, timeout=5)
                return "dark" if "Dark" in r.stdout else "light"
            except Exception:
                return "light"
        else:
            try:
                import subprocess as sp
                r = sp.run(["gsettings", "get", "org.gnome.desktop.interface",
                            "color-scheme"],
                           capture_output=True, text=True, timeout=5)
                return "dark" if "dark" in r.stdout.lower() else "light"
            except Exception:
                return "light"

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = self.root

        # Top bar: title + theme toggle
        top_bar = ttk.Frame(root)
        top_bar.pack(fill=tk.X, padx=10, pady=(8, 0))
        ttk.Label(top_bar, text="BOF Asset Decryptor",
                  font=(_SANS_FONT, 13, "bold")).pack(side=tk.LEFT)
        self._theme_btn = ttk.Button(top_bar, text="", width=3,
                                     command=self._toggle_theme)
        self._theme_btn.pack(side=tk.RIGHT)

        # Prerequisites section
        prereq_frame = ttk.LabelFrame(root, text="Prerequisites")
        prereq_frame.pack(fill=tk.X, padx=10, pady=(8, 0))
        self._prereq_indicators = {}
        self._prereq_inner = ttk.Frame(prereq_frame)
        self._prereq_inner.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, pady=4)
        btn_frame = ttk.Frame(prereq_frame)
        btn_frame.pack(side=tk.RIGHT, padx=4, pady=4)
        ttk.Button(btn_frame, text="Check",
                   command=self._on_check_prereqs).pack(side=tk.TOP, fill=tk.X)
        self.install_btn = ttk.Button(btn_frame, text="Install Missing",
                                      command=self._on_install_prereqs)
        self.install_btn.pack(side=tk.TOP, fill=tk.X, pady=(2, 0))

        # Tabs
        self._notebook = ttk.Notebook(root)
        self._notebook.pack(fill=tk.X, expand=False, padx=10, pady=(8, 0))

        self._tab_decrypt = ttk.Frame(self._notebook)
        self._tab_write = ttk.Frame(self._notebook)
        self._tab_modpack = ttk.Frame(self._notebook)

        self._notebook.add(self._tab_decrypt, text="  Decrypt  ")
        self._notebook.add(self._tab_write, text="  Write  ")
        self._notebook.add(self._tab_modpack, text="  Mod Pack  ")

        self._build_decrypt_tab()
        self._build_write_tab()
        self._build_modpack_tab()

        # Phase steps + progress bar + status (below tabs)
        status_frame = ttk.Frame(root)
        status_frame.pack(fill=tk.X, padx=10, pady=(4, 0))

        # Decrypt phases row (shown when Decrypt tab active)
        self._decrypt_phases_frame = ttk.Frame(status_frame)
        self._decrypt_phases_frame.pack(fill=tk.X)
        # Write phases row (shown when Write tab active)
        self._write_phases_frame = ttk.Frame(status_frame)
        # (not packed yet — shown on tab switch)

        self._progress_bar = ttk.Progressbar(status_frame, mode="determinate",
                                             maximum=100)
        self._progress_bar.pack(fill=tk.X, pady=(4, 2))

        status_row = ttk.Frame(status_frame)
        status_row.pack(fill=tk.X)
        self._status_label = ttk.Label(status_row, text="Ready",
                                       font=(_SANS_FONT, 9))
        self._status_label.pack(side=tk.LEFT)
        self._elapsed_label = ttk.Label(status_row, text="",
                                        font=(_SANS_FONT, 9))
        self._elapsed_label.pack(side=tk.RIGHT)

        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Log output
        log_frame = ttk.LabelFrame(root, text="Log")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 8))

        self._log_text = tk.Text(log_frame, wrap=tk.WORD,
                                 font=(_MONO_FONT, 9),
                                 state=tk.DISABLED, height=12)
        log_scroll = ttk.Scrollbar(log_frame, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._log_text.pack(fill=tk.BOTH, expand=True)

        self._log_text.tag_configure("info", foreground="")
        self._log_text.tag_configure("success", foreground="#6a9955")
        self._log_text.tag_configure("error", foreground="#f44747")
        self._log_text.tag_configure("ts", foreground="#808080")
        self._log_text.tag_configure("link", foreground="#3794ff",
                                     underline=True)

    def _build_decrypt_tab(self):
        f = self._tab_decrypt
        pad = {"padx": 10, "pady": 4}

        # .fun file
        row = ttk.Frame(f)
        row.pack(fill=tk.X, **pad)
        ttk.Label(row, text=".fun File:", width=14, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.fun_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Browse...",
                   command=self._browse_fun).pack(side=tk.LEFT, padx=(4, 0))

        # Game badge (auto-detected)
        self._game_badge = ttk.Label(f, text="", font=(_SANS_FONT, 9, "italic"))
        self._game_badge.pack(anchor=tk.W, padx=24, pady=(0, 2))
        self.fun_var.trace_add("write", self._update_game_badge)

        # Output folder
        row2 = ttk.Frame(f)
        row2.pack(fill=tk.X, **pad)
        ttk.Label(row2, text="Output Folder:", width=14, anchor=tk.W).pack(
            side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.output_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row2, text="Browse...",
                   command=self._browse_output).pack(side=tk.LEFT, padx=(4, 0))

        # Warn if output folder not empty
        self._decrypt_warn = ttk.Label(f, text="", foreground="#f44747",
                                       font=(_SANS_FONT, 9))
        self._decrypt_warn.pack(anchor=tk.W, padx=24)
        self.output_var.trace_add("write", self._check_output_warn)

        # Action buttons
        btn_row = ttk.Frame(f)
        btn_row.pack(fill=tk.X, padx=10, pady=(8, 4))
        self._decrypt_btn = ttk.Button(btn_row, text="Decrypt",
                                       command=self._on_start)
        self._decrypt_btn.pack(side=tk.LEFT)
        self._cancel_btn = ttk.Button(btn_row, text="Cancel",
                                      command=self._on_cancel, state=tk.DISABLED)
        self._cancel_btn.pack(side=tk.LEFT, padx=(6, 0))


    def _build_write_tab(self):
        f = self._tab_write
        pad = {"padx": 10, "pady": 4}

        ttk.Label(f, text="Re-pack modified assets into a .fun file for USB install.",
                  font=(_SANS_FONT, 9, "italic")).pack(anchor=tk.W, **pad)

        # Assets folder
        row = ttk.Frame(f)
        row.pack(fill=tk.X, **pad)
        ttk.Label(row, text="Assets Folder:", width=16, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.write_input_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Browse...",
                   command=self._browse_write_input).pack(side=tk.LEFT, padx=(4, 0))
        _Tooltip(row, "The folder produced by Decrypt — contains GDCraze.x86_64 "
                 "and .checksums.md5.", lambda: self._current_theme)

        # Output .fun file
        row2 = ttk.Frame(f)
        row2.pack(fill=tk.X, **pad)
        ttk.Label(row2, text="Output .fun File:", width=16, anchor=tk.W).pack(
            side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.write_output_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row2, text="Browse...",
                   command=self._browse_write_output).pack(side=tk.LEFT, padx=(4, 0))

        # Game selection
        row3 = ttk.Frame(f)
        row3.pack(fill=tk.X, **pad)
        ttk.Label(row3, text="Game:", width=16, anchor=tk.W).pack(side=tk.LEFT)
        game_options = [f"{info} ({key})" for key, info in KNOWN_GAMES.items()]
        self._write_game_cb = ttk.Combobox(
            row3, textvariable=self.write_game_var,
            values=game_options, state="readonly", width=40)
        self._write_game_cb.pack(side=tk.LEFT)

        # Warning
        self._write_warn = ttk.Label(f, text="", foreground="#f44747",
                                     font=(_SANS_FONT, 9))
        self._write_warn.pack(anchor=tk.W, padx=24)

        # Action buttons
        btn_row = ttk.Frame(f)
        btn_row.pack(fill=tk.X, padx=10, pady=(8, 4))
        self._mod_btn = ttk.Button(btn_row, text="Build .fun",
                                   command=self._on_mod_apply)
        self._mod_btn.pack(side=tk.LEFT)
        self._mod_cancel_btn = ttk.Button(btn_row, text="Cancel",
                                          command=self._on_mod_cancel,
                                          state=tk.DISABLED)
        self._mod_cancel_btn.pack(side=tk.LEFT, padx=(6, 0))


        # Install instructions
        note_frame = ttk.LabelFrame(f, text="How to Install")
        note_frame.pack(fill=tk.X, padx=10, pady=(8, 4))
        note = ("1. Copy the output .fun file to a USB drive formatted FAT32.\n"
                "2. Open the pinball machine backbox and locate the PC.\n"
                "3. With the machine running, insert the USB drive into any USB port.\n"
                "4. The machine will update automatically. Remove the USB when prompted.")
        ttk.Label(note_frame, text=note, font=(_SANS_FONT, 9),
                  justify=tk.LEFT, wraplength=600).pack(
            anchor=tk.W, padx=8, pady=6)

    def _build_modpack_tab(self):
        f = self._tab_modpack
        pad = {"padx": 10, "pady": 6}

        ttk.Label(f, text="Share or apply mod packs — zips containing only "
                  "your modified files.",
                  font=(_SANS_FONT, 9, "italic")).pack(anchor=tk.W, **pad)

        # Folder
        row = ttk.Frame(f)
        row.pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(row, text="Mod Folder:", width=12, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.write_input_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Browse...",
                   command=self._browse_write_input).pack(side=tk.LEFT, padx=(4, 0))

        sep = ttk.Separator(f, orient=tk.HORIZONTAL)
        sep.pack(fill=tk.X, padx=10, pady=8)

        export_frame = ttk.LabelFrame(f, text="Export Mod Pack")
        export_frame.pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(export_frame,
                  text="Create a zip of only your modified files to share with others.",
                  font=(_SANS_FONT, 9)).pack(anchor=tk.W, padx=8, pady=(4, 2))
        ttk.Button(export_frame, text="Export Mod Pack...",
                   command=self._on_export).pack(anchor=tk.W, padx=8, pady=(2, 6))

        import_frame = ttk.LabelFrame(f, text="Import Mod Pack")
        import_frame.pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(import_frame,
                  text="Apply a mod pack zip from another user into your mod folder.",
                  font=(_SANS_FONT, 9)).pack(anchor=tk.W, padx=8, pady=(4, 2))
        ttk.Button(import_frame, text="Import Mod Pack...",
                   command=self._on_import).pack(anchor=tk.W, padx=8, pady=(2, 6))

    def _build_phase_steps(self, parent, phases, mode):
        """Build a row of phase step labels inside parent."""
        labels = []
        for name in phases:
            lbl = ttk.Label(parent, text=f"○ {name}", font=(_SANS_FONT, 8))
            lbl.pack(side=tk.LEFT, padx=(0, 12))
            labels.append(lbl)
        if mode == "decrypt":
            self._decrypt_phase_labels = labels
        else:
            self._modify_phase_labels = labels

    def _init_phase_steps(self):
        """Populate phase rows after layout is complete."""
        self._build_phase_steps(self._decrypt_phases_frame, DECRYPT_PHASES, "decrypt")
        self._build_phase_steps(self._write_phases_frame, MODIFY_PHASES, "modify")

    def _on_tab_changed(self, event=None):
        idx = self._notebook.index(self._notebook.select())
        if idx == 1:  # Write tab
            self._decrypt_phases_frame.pack_forget()
            self._write_phases_frame.pack(fill=tk.X, before=self._progress_bar)
        else:
            self._write_phases_frame.pack_forget()
            self._decrypt_phases_frame.pack(fill=tk.X, before=self._progress_bar)

    # ------------------------------------------------------------------
    # Browse helpers
    # ------------------------------------------------------------------

    def _browse_fun(self):
        path = filedialog.askopenfilename(
            title="Select .fun file",
            filetypes=[("BOF update files", "*.fun"), ("All files", "*.*")],
        )
        if path:
            self.fun_var.set(path)

    def _browse_output(self):
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_var.set(path)

    def _browse_write_input(self):
        path = filedialog.askdirectory(title="Select assets folder")
        if path:
            self.write_input_var.set(path)

    def _browse_write_output(self):
        path = filedialog.asksaveasfilename(
            title="Save .fun file as",
            defaultextension=".fun",
            filetypes=[("BOF update files", "*.fun"), ("All files", "*.*")],
        )
        if path:
            self.write_output_var.set(path)

    # ------------------------------------------------------------------
    # Dynamic UI state
    # ------------------------------------------------------------------

    def _update_game_badge(self, *_):
        from .pipeline import detect_game
        path = self.fun_var.get().strip()
        if not path:
            self._game_badge.configure(text="")
            return
        key = detect_game(path)
        if key:
            display = KNOWN_GAMES.get(key, key)
            self._game_badge.configure(text=f"Game detected: {display}")
        else:
            self._game_badge.configure(text="Unknown game")

    def _check_output_warn(self, *_):
        path = self.output_var.get().strip()
        if path and os.path.isdir(path) and os.listdir(path):
            self._decrypt_warn.configure(
                text="Output folder is not empty — existing files may be overwritten.")
        else:
            self._decrypt_warn.configure(text="")

    # ------------------------------------------------------------------
    # Prerequisite indicators
    # ------------------------------------------------------------------

    def set_prereq(self, name, passed, message=""):
        c = _THEMES[self._current_theme]
        if name not in self._prereq_state:
            lbl = ttk.Label(self._prereq_inner,
                            font=(_SANS_FONT, 9),
                            padding=(4, 2))
            lbl.pack(side=tk.LEFT, padx=2)
            self._prereq_state[name] = lbl
            _Tooltip(lbl, message or name, lambda: self._current_theme)
        lbl = self._prereq_state[name]
        icon = "✓" if passed else "✗"
        color = c["success"] if passed else c["error"]
        lbl.configure(text=f"[{icon}] {name}", foreground=color)

    # ------------------------------------------------------------------
    # Log output
    # ------------------------------------------------------------------

    def append_log(self, text, level="info"):
        import time as _time
        ts = _time.strftime("%H:%M:%S")
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.insert(tk.END, f"[{ts}] ", "ts")
        self._log_text.insert(tk.END, text + "\n", level)
        self._log_text.configure(state=tk.DISABLED)
        self._log_text.see(tk.END)

    def append_log_link(self, text, url):
        import time as _time
        ts = _time.strftime("%H:%M:%S")
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.insert(tk.END, f"[{ts}] ", "ts")
        tag = f"link_{id(url)}"
        self._log_text.tag_configure(tag, foreground=_THEMES[self._current_theme]["link"],
                                     underline=True)
        self._log_text.tag_bind(tag, "<Button-1>",
                                lambda e, u=url: webbrowser.open(u))
        self._log_text.tag_bind(tag, "<Enter>",
                                lambda e: self._log_text.configure(cursor="hand2"))
        self._log_text.tag_bind(tag, "<Leave>",
                                lambda e: self._log_text.configure(cursor=""))
        self._log_text.insert(tk.END, text + "\n", tag)
        self._log_text.configure(state=tk.DISABLED)
        self._log_text.see(tk.END)

    # ------------------------------------------------------------------
    # Progress + phases
    # ------------------------------------------------------------------

    def set_phase(self, index, mode="decrypt"):
        labels = (self._decrypt_phase_labels if mode == "decrypt"
                  else self._modify_phase_labels)
        c = _THEMES[self._current_theme]
        for i, lbl in enumerate(labels):
            name = lbl.cget("text").lstrip("○● ").split()[-1] if lbl.cget("text") else ""
            if i < index:
                lbl.configure(text=f"● {name}", foreground=c["success"])
            elif i == index:
                lbl.configure(text=f"● {name}", foreground=c["accent"])
            else:
                lbl.configure(text=f"○ {name}", foreground=c["gray"])

    def reset_steps(self, mode="decrypt"):
        from .config import DECRYPT_PHASES, MODIFY_PHASES
        phases = DECRYPT_PHASES if mode == "decrypt" else MODIFY_PHASES
        labels = (self._decrypt_phase_labels if mode == "decrypt"
                  else self._modify_phase_labels)
        c = _THEMES[self._current_theme]
        for lbl, name in zip(labels, phases):
            lbl.configure(text=f"○ {name}", foreground=c["gray"])
        self._progress_bar["value"] = 0

    def set_progress(self, current, total, desc="", mode="decrypt"):
        if total > 0:
            self._progress_bar.configure(mode="determinate")
            self._progress_bar["value"] = int(100 * current / total)
        else:
            self._progress_bar.configure(mode="indeterminate")
            self._progress_bar.start(12)
        if desc:
            self.set_status(desc)

    def set_status(self, text):
        self._status_label.configure(text=text)

    # ------------------------------------------------------------------
    # Running state
    # ------------------------------------------------------------------

    def set_running(self, running, mode="decrypt"):
        import time as _time
        if running:
            self._decrypt_btn.configure(state=tk.DISABLED)
            self._cancel_btn.configure(state=tk.NORMAL)
            self._mod_btn.configure(state=tk.DISABLED)
            self._mod_cancel_btn.configure(state=tk.NORMAL)
            self._start_time = _time.time()
            self._tick_timer()
        else:
            self._decrypt_btn.configure(state=tk.NORMAL)
            self._cancel_btn.configure(state=tk.DISABLED)
            self._mod_btn.configure(state=tk.NORMAL)
            self._mod_cancel_btn.configure(state=tk.DISABLED)
            self._progress_bar.stop()
            self._progress_bar.configure(mode="determinate")
            if self._timer_id:
                self.root.after_cancel(self._timer_id)
                self._timer_id = None
            self._elapsed_label.configure(text="")

    def _tick_timer(self):
        import time as _time
        if self._start_time is not None:
            elapsed = int(_time.time() - self._start_time)
            m, s = divmod(elapsed, 60)
            self._elapsed_label.configure(text=f"{m:02d}:{s:02d}")
        self._timer_id = self.root.after(1000, self._tick_timer)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _toggle_theme(self):
        new_theme = "light" if self._current_theme == "dark" else "dark"
        self._apply_theme(new_theme)
        if self._on_theme_change:
            self._on_theme_change(new_theme)

    def _apply_theme(self, theme):
        c = _THEMES[theme]
        self._current_theme = theme

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=c["bg"], foreground=c["fg"],
                        fieldbackground=c["field_bg"], bordercolor=c["border"],
                        troughcolor=c["trough"], selectbackground=c["select_bg"],
                        selectforeground="#ffffff", insertcolor=c["fg"])
        style.configure("TFrame", background=c["bg"])
        style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        style.configure("TLabelframe", background=c["bg"], foreground=c["fg"])
        style.configure("TLabelframe.Label", background=c["bg"], foreground=c["fg"])
        style.configure("TButton", background=c["button"], foreground=c["fg"])
        style.map("TButton",
                  background=[("active", c["accent"]), ("pressed", c["accent"])],
                  foreground=[("active", "#ffffff"), ("pressed", "#ffffff")])
        style.configure("TCheckbutton", background=c["bg"], foreground=c["fg"])
        style.map("TCheckbutton", background=[("active", c["bg"])])
        style.configure("TEntry", fieldbackground=c["field_bg"], foreground=c["fg"])
        style.configure("TCombobox", fieldbackground=c["field_bg"],
                        foreground=c["fg"], background=c["button"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", c["field_bg"])],
                  foreground=[("readonly", c["fg"])],
                  background=[("readonly", c["button"])])
        self.root.option_add("*TCombobox*Listbox.background", c["field_bg"])
        self.root.option_add("*TCombobox*Listbox.foreground", c["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["select_bg"])
        style.configure("TNotebook", background=c["bg"], bordercolor=c["border"])
        style.configure("TNotebook.Tab", background=c["button"], foreground=c["fg"],
                        padding=(10, 4))
        style.map("TNotebook.Tab",
                  background=[("selected", c["tab_selected"]),
                               ("active", c["accent"])],
                  foreground=[("selected", c["fg"]), ("active", "#ffffff")])
        style.configure("Horizontal.TProgressbar",
                        troughcolor=c["trough"], background=c["accent"])
        style.configure("TSeparator", background=c["border"])

        # Tk (non-ttk) widgets
        self.root.configure(background=c["bg"])
        self._log_text.configure(
            background=c["field_bg"], foreground=c["fg"],
            insertbackground=c["fg"],
            selectbackground=c["select_bg"],
        )
        self._log_text.tag_configure("info", foreground=c["fg"])
        self._log_text.tag_configure("success", foreground=c["success"])
        self._log_text.tag_configure("error", foreground=c["error"])
        self._log_text.tag_configure("ts", foreground=c["timestamp"])
        self._log_text.tag_configure("link", foreground=c["link"])

        # Theme toggle button
        if theme == "dark":
            self._theme_btn.configure(text="☀", style="Sun.TButton")
        else:
            self._theme_btn.configure(text="☽", style="Moon.TButton")

        icon_style = {"background": c["bg"], "borderwidth": 0, "relief": "flat"}
        style.configure("Sun.TButton", font=(_SANS_FONT, 14), padding=(4, 0),
                        foreground="#e6a817", **icon_style)
        style.map("Sun.TButton", background=[("active", c["button"])])
        style.configure("Moon.TButton", font=(_SANS_FONT, 14), padding=(4, 0),
                        foreground="#7b9fd4", **icon_style)
        style.map("Moon.TButton", background=[("active", c["button"])])

        # Windows title bar color
        if sys.platform == "win32":
            try:
                import ctypes
                DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                value = ctypes.c_int(1 if theme == "dark" else 0)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    ctypes.windll.user32.GetForegroundWindow(),
                    DWMWA_USE_IMMERSIVE_DARK_MODE,
                    ctypes.byref(value),
                    ctypes.sizeof(value),
                )
            except Exception:
                pass
