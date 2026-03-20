"""Main application class — wires GUI and pipeline together."""

import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from . import __version__
from .config import SETTINGS_FILE, KNOWN_GAMES, GAME_DB, FUN_FILE_TO_GAME
from .executor import create_executor
from .gui import MainWindow
from .pipeline import (DecryptPipeline, ModifyPipeline,
                       check_prerequisites, export_mod_pack, import_mod_pack,
                       detect_game)
from .updater import check_for_update


# ---------------------------------------------------------------------------
# Thread-safe message types
# ---------------------------------------------------------------------------

class LogMsg:
    def __init__(self, text, level="info"):
        self.text = text
        self.level = level

class LinkMsg:
    def __init__(self, text, url):
        self.text = text
        self.url = url

class PhaseMsg:
    def __init__(self, index):
        self.index = index

class ProgressMsg:
    def __init__(self, current, total, desc=""):
        self.current = current
        self.total = total
        self.desc = desc

class DoneMsg:
    def __init__(self, success, summary):
        self.success = success
        self.summary = summary


# ---------------------------------------------------------------------------
# App controller
# ---------------------------------------------------------------------------

class App:
    """Top-level application controller."""

    def __init__(self):
        self.root = tk.Tk()
        self.msg_queue = queue.Queue()
        self.pipeline = None
        self.executor = create_executor()
        self._active_mode = "decrypt"

        # Pre-load theme preference
        saved_theme = None
        try:
            with open(SETTINGS_FILE, "r") as f:
                saved_theme = json.load(f).get("theme")
        except Exception:
            pass

        self.window = MainWindow(
            self.root,
            on_check_prereqs=self._check_prereqs,
            on_start=self._start_decrypt,
            on_cancel=self._cancel,
            on_mod_apply=self._start_modify,
            on_mod_cancel=self._cancel,
            on_theme_change=self._on_theme_change,
            initial_theme=saved_theme,
            on_install_prereqs=self._install_prereqs,
            on_import=self._start_import,
            on_export=self._start_export,
        )

        self._load_settings()
        self._poll_queue()

        self.root.title(f"BOF Asset Decryptor v{__version__}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Auto-run checks on startup
        self.root.after(500, self._check_prereqs)
        self.root.after(1500, self._check_for_update)

    def run(self):
        self.root.mainloop()

    def _on_close(self):
        self._save_settings()
        self.root.destroy()

    # ------------------------------------------------------------------
    # Queue polling
    # ------------------------------------------------------------------

    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                if isinstance(msg, LogMsg):
                    self.window.append_log(msg.text, msg.level)
                elif isinstance(msg, LinkMsg):
                    self.window.append_log_link(msg.text, msg.url)
                elif isinstance(msg, PhaseMsg):
                    self.window.set_phase(msg.index, mode=self._active_mode)
                    phases = self._phases_for_mode()
                    if msg.index < len(phases):
                        self.window.set_status(f"{phases[msg.index]}...")
                elif isinstance(msg, ProgressMsg):
                    self.window.set_progress(
                        msg.current, msg.total, msg.desc,
                        mode=self._active_mode)
                elif isinstance(msg, DoneMsg):
                    self._on_done(msg.success, msg.summary)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _phases_for_mode(self):
        from .config import DECRYPT_PHASES, MODIFY_PHASES
        if self._active_mode == "modify":
            return MODIFY_PHASES
        return DECRYPT_PHASES

    # ------------------------------------------------------------------
    # Prerequisites
    # ------------------------------------------------------------------

    def _check_prereqs(self):
        self.window.append_log("Checking prerequisites...", "info")

        def _run():
            results = check_prerequisites(self.executor)
            for name, passed, message in results:
                self.msg_queue.put(LogMsg(
                    f"  {name}: {'OK' if passed else 'MISSING'} — {message}",
                    "success" if passed else "error",
                ))
                self.root.after(0, self.window.set_prereq, name, passed, message)

            if all(p for _, p, _ in results):
                self.msg_queue.put(LogMsg("Prerequisites OK.", "success"))
            else:
                self.msg_queue.put(LogMsg(
                    "Some prerequisites are missing.", "error"))

        threading.Thread(target=_run, daemon=True).start()

    def _install_prereqs(self):
        import sys as _sys
        platform = _sys.platform

        if platform == "win32":
            self.window.append_log("Installing prerequisites in WSL...", "info")
        elif platform == "darwin":
            self.window.append_log("Installing prerequisites via Homebrew...", "info")
        else:
            self.window.append_log("Installing prerequisites...", "info")

        self.window.install_btn.configure(state=tk.DISABLED)

        def _run():
            try:
                self.executor.run("echo ok", timeout=15)
            except Exception:
                if platform == "win32":
                    msg = ("WSL2 is not available. Install Ubuntu from the "
                           "Microsoft Store or run: wsl --install -d Ubuntu")
                else:
                    msg = "Command execution failed. Check system configuration."
                self.msg_queue.put(LogMsg(msg, "error"))
                self.root.after(0, lambda: self.window.install_btn.configure(
                    state=tk.NORMAL))
                return

            # Install base packages
            if platform == "win32":
                pkg_cmd = ("apt-get update -qq && "
                           "apt-get install -y gnupg tar curl unzip xvfb 2>&1")
            elif platform == "darwin":
                pkg_cmd = "brew install gnupg curl unzip 2>&1"
            else:
                pkg_cmd = ("sudo apt-get update -qq && "
                           "sudo apt-get install -y gnupg tar curl unzip xvfb 2>&1")

            try:
                for line in self.executor.stream(pkg_cmd, timeout=300):
                    self.msg_queue.put(LogMsg(f"  {line}", "info"))
                self.msg_queue.put(LogMsg("Base packages installed.", "success"))
            except Exception as e:
                self.msg_queue.put(LogMsg(f"Package install failed: {e}", "error"))

            # GDRE Tools
            self._install_gdre_tools()

            results = check_prerequisites(self.executor)
            for name, passed, message in results:
                self.root.after(0, self.window.set_prereq, name, passed, message)

            if all(p for _, p, _ in results):
                self.msg_queue.put(LogMsg("All prerequisites installed.", "success"))
            else:
                self.msg_queue.put(LogMsg(
                    "Some prerequisites are still missing.", "error"))

            self.root.after(0, lambda: self.window.install_btn.configure(
                state=tk.NORMAL))

        threading.Thread(target=_run, daemon=True).start()

    def _install_gdre_tools(self):
        """Download and install the latest GDRE Tools binary."""
        import base64 as _b64
        import sys as _sys

        platform = _sys.platform

        # Determine which release asset suffix to look for
        if platform == "darwin":
            asset_suffix = "-macos.zip"
            binary_name = "gdre_tools"
            lib_name = "libGodotMonoDecompNativeAOT.dylib"
        else:
            asset_suffix = "-linux.zip"
            binary_name = "gdre_tools.x86_64"
            lib_name = "libGodotMonoDecompNativeAOT.so"

        _wrapper = (
            "#!/bin/bash\n"
            "export LD_LIBRARY_PATH=/opt/gdre_tools:$LD_LIBRARY_PATH\n"
            f'exec /opt/gdre_tools/{binary_name} "$@"\n'
        )
        _wrapper_b64 = _b64.b64encode(_wrapper.encode()).decode()

        self.msg_queue.put(LogMsg("Installing GDRE Tools...", "info"))
        try:
            # Fetch latest release metadata
            url_json = self.executor.run(
                "curl -sf https://api.github.com/repos/GDRETools/gdsdecomp/releases/latest",
                timeout=30,
            )
            import json as _json
            data = _json.loads(url_json)
            dl_url = None
            zip_name = None
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                if name.endswith(asset_suffix):
                    dl_url = asset["browser_download_url"]
                    zip_name = name
                    break

            if not dl_url:
                self.msg_queue.put(LogMsg(
                    f"Could not find GDRE Tools {asset_suffix} release asset.",
                    "error"))
                return

            version = data.get("tag_name", "")
            self.msg_queue.put(LogMsg(
                f"Downloading GDRE Tools {version} ({zip_name})...", "info"))

            # Download
            for line in self.executor.stream(
                f"curl -L --progress-bar {dl_url!r} -o /tmp/gdre_tools.zip 2>&1",
                timeout=300,
            ):
                if line.strip():
                    self.msg_queue.put(LogMsg(f"  {line}", "info"))

            self.msg_queue.put(LogMsg("Extracting...", "info"))

            # Use sudo for /opt on Linux, not on macOS (use mkdir -p with
            # current user on macOS, or sudo if needed)
            if platform == "darwin":
                sudo = "sudo "
            elif platform == "win32":
                sudo = ""  # WSL runs as root
            else:
                sudo = "sudo "

            # Extract and install to /opt/gdre_tools/
            self.executor.run(
                "rm -rf /tmp/gdre_extract && "
                "mkdir -p /tmp/gdre_extract && "
                "unzip -o /tmp/gdre_tools.zip -d /tmp/gdre_extract/ && "
                f"{sudo}rm -rf /opt/gdre_tools && "
                f"{sudo}mkdir -p /opt/gdre_tools && "
                f"{sudo}cp -f /tmp/gdre_extract/{binary_name} /opt/gdre_tools/ && "
                f"{sudo}cp -f /tmp/gdre_extract/gdre_tools.pck /opt/gdre_tools/ && "
                f"({sudo}cp -f /tmp/gdre_extract/{lib_name} /opt/gdre_tools/ 2>/dev/null || true) && "
                f"{sudo}chmod +x /opt/gdre_tools/{binary_name} && "
                f"echo {_wrapper_b64!r} | base64 -d | {sudo}tee /usr/local/bin/gdre_tools > /dev/null && "
                f"{sudo}chmod +x /usr/local/bin/gdre_tools && "
                "rm -rf /tmp/gdre_tools.zip /tmp/gdre_extract",
                timeout=120,
            )
            self.msg_queue.put(LogMsg(
                f"GDRE Tools {version} installed to /usr/local/bin/gdre_tools.",
                "success"))
        except Exception as e:
            self.msg_queue.put(LogMsg(
                f"GDRE Tools installation failed: {e}", "error"))

    # ------------------------------------------------------------------
    # Decrypt
    # ------------------------------------------------------------------

    def _start_decrypt(self):
        fun_path = self.window.fun_var.get().strip()
        output_path = self.window.output_var.get().strip()

        if not fun_path:
            messagebox.showwarning("Missing Input", "Please select a .fun file.")
            return
        if not os.path.isfile(fun_path):
            messagebox.showerror("File Not Found",
                f"File not found:\n{fun_path}")
            return
        if not output_path:
            messagebox.showwarning("Missing Input",
                "Please select an output folder.")
            return

        game_key = detect_game(fun_path)
        if game_key is None:
            messagebox.showerror("Unknown File",
                f"Cannot identify game from filename: "
                f"{os.path.basename(fun_path)}\n\n"
                f"Expected one of: {', '.join(FUN_FILE_TO_GAME.keys())}")
            return

        if os.path.isdir(output_path) and os.listdir(output_path):
            if not messagebox.askyesno(
                "Output Folder Not Empty",
                "The output folder already contains files.\n\n"
                "Decrypting again will overwrite existing files.\n\n"
                "Continue?",
            ):
                return

        self._save_settings()

        self._active_mode = "decrypt"
        self.window.set_running(True, mode="decrypt")
        self.window.reset_steps(mode="decrypt")

        log_cb = lambda t, l="info": self.msg_queue.put(LogMsg(t, l))
        phase_cb = lambda i: self.msg_queue.put(PhaseMsg(i))
        progress_cb = lambda c, t, d="": self.msg_queue.put(ProgressMsg(c, t, d))
        done_cb = lambda s, m: self.msg_queue.put(DoneMsg(s, m))

        self.pipeline = DecryptPipeline(
            fun_path, output_path, self.executor,
            log_cb, phase_cb, progress_cb, done_cb,
            unpack_pck=True,
        )
        threading.Thread(target=self.pipeline.run, daemon=True).start()

    # ------------------------------------------------------------------
    # Modify (re-encrypt)
    # ------------------------------------------------------------------

    def _start_modify(self):
        assets_dir = self.window.write_input_var.get().strip()
        output_fun = self.window.write_output_var.get().strip()
        game_display = self.window.write_game_var.get().strip()

        if not assets_dir:
            messagebox.showwarning("Missing Input",
                "Please select an assets folder.")
            return
        if not os.path.isdir(assets_dir):
            messagebox.showerror("Invalid Folder",
                f"Folder not found:\n{assets_dir}")
            return
        if not output_fun:
            messagebox.showwarning("Missing Input",
                "Please specify an output .fun file path.")
            return
        if not game_display:
            messagebox.showwarning("Missing Input",
                "Please select a game.")
            return

        # Parse game key from combobox text "Display Name (key)"
        game_key = None
        for key, display in KNOWN_GAMES.items():
            if f"({key})" in game_display:
                game_key = key
                break
        if game_key is None:
            messagebox.showerror("Unknown Game", "Could not identify the selected game.")
            return

        checksums_file = os.path.join(assets_dir, ".checksums.md5")
        if not os.path.isfile(checksums_file):
            messagebox.showerror("No Baseline Checksums",
                "No .checksums.md5 found in the assets folder.\n\n"
                "Decrypt the game first to generate baseline checksums.")
            return

        self._save_settings()

        self._active_mode = "modify"
        self.window.set_running(True, mode="modify")
        self.window.reset_steps(mode="modify")

        log_cb = lambda t, l="info": self.msg_queue.put(LogMsg(t, l))
        phase_cb = lambda i: self.msg_queue.put(PhaseMsg(i))
        progress_cb = lambda c, t, d="": self.msg_queue.put(ProgressMsg(c, t, d))
        done_cb = lambda s, m: self.msg_queue.put(DoneMsg(s, m))

        self.pipeline = ModifyPipeline(
            assets_dir, output_fun, game_key, self.executor,
            log_cb, phase_cb, progress_cb, done_cb,
        )
        threading.Thread(target=self.pipeline.run, daemon=True).start()

    # ------------------------------------------------------------------
    # Mod pack export / import
    # ------------------------------------------------------------------

    def _start_export(self):
        from tkinter import filedialog as fd

        assets_dir = self.window.write_input_var.get().strip()
        if not assets_dir:
            messagebox.showwarning("Missing Input",
                "Please select a mod folder first.")
            return
        if not os.path.isdir(assets_dir):
            messagebox.showerror("Invalid Folder",
                f"Folder not found:\n{assets_dir}")
            return
        if not os.path.isfile(os.path.join(assets_dir, ".checksums.md5")):
            messagebox.showerror("No Baseline Checksums",
                "No .checksums.md5 found. Decrypt the game first.")
            return

        zip_path = fd.asksaveasfilename(
            title="Save Mod Pack As",
            defaultextension=".zip",
            initialfile="bof_mod_pack.zip",
            filetypes=[("Zip files", "*.zip"), ("All files", "*.*")],
        )
        if not zip_path:
            return

        self.window.append_log("Exporting mod pack...", "info")

        def _run():
            try:
                n, path = export_mod_pack(
                    assets_dir, zip_path,
                    log_cb=lambda t, l="info": self.msg_queue.put(LogMsg(t, l)),
                    progress_cb=lambda c, t, d="": self.msg_queue.put(ProgressMsg(c, t, d)),
                )
                self.msg_queue.put(LogMsg(
                    f"Mod pack exported: {n} file(s) → {path}", "success"))
                self.root.after(0, lambda: messagebox.showinfo(
                    "Export Complete",
                    f"Mod pack saved to:\n{path}\n\n"
                    f"Contains {n} modified file(s)."))
            except Exception as e:
                self.msg_queue.put(LogMsg(f"Export failed: {e}", "error"))
                self.root.after(0, lambda: messagebox.showerror("Export Failed", str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def _start_import(self):
        from tkinter import filedialog as fd

        assets_dir = self.window.write_input_var.get().strip()
        if not assets_dir:
            messagebox.showwarning("Missing Input",
                "Please select a mod folder first.")
            return
        if not os.path.isdir(assets_dir):
            messagebox.showerror("Invalid Folder",
                f"Folder not found:\n{assets_dir}")
            return

        zip_path = fd.askopenfilename(
            title="Select Mod Pack ZIP",
            filetypes=[("Zip files", "*.zip"), ("All files", "*.*")],
        )
        if not zip_path:
            return

        if not messagebox.askyesno(
            "Import Mod Pack",
            f"Extract mod pack into:\n  {assets_dir}\n\n"
            f"Existing files with the same names will be overwritten.\n\nContinue?",
        ):
            return

        self.window.append_log("Importing mod pack...", "info")

        def _run():
            try:
                n = import_mod_pack(
                    zip_path, assets_dir,
                    log_cb=lambda t, l="info": self.msg_queue.put(LogMsg(t, l)),
                    progress_cb=lambda c, t, d="": self.msg_queue.put(ProgressMsg(c, t, d)),
                )
                self.msg_queue.put(LogMsg(
                    f"Mod pack imported: {n} file(s).", "success"))
                self.root.after(0, lambda: messagebox.showinfo(
                    "Import Complete",
                    f"Imported {n} file(s).\n\n"
                    f"Use the Write tab to rebuild and re-encrypt the .fun file."))
            except Exception as e:
                self.msg_queue.put(LogMsg(f"Import failed: {e}", "error"))
                self.root.after(0, lambda: messagebox.showerror("Import Failed", str(e)))

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Cancel / Done
    # ------------------------------------------------------------------

    def _cancel(self):
        if self.pipeline:
            self.window.append_log("Cancelling...", "error")
            self.pipeline.cancel()

    def _on_done(self, success, summary):
        is_decrypt = self._active_mode == "decrypt"
        self.window.set_running(False, mode=self._active_mode)
        if success:
            self.window.set_status("Complete!")
            title = "Decryption Complete" if is_decrypt else "Done"
            messagebox.showinfo(title, summary)
        else:
            self.window.set_status("Failed")
            title = "Decryption Failed" if is_decrypt else "Failed"
            messagebox.showerror(title, summary)

    # ------------------------------------------------------------------
    # Update check
    # ------------------------------------------------------------------

    def _check_for_update(self):
        def _run():
            result = check_for_update(__version__)
            if result:
                version, url, notes = result
                self.msg_queue.put(LogMsg(f"Update available: v{version}", "info"))
                if notes:
                    for line in notes.splitlines():
                        line = line.strip()
                        if line:
                            self.msg_queue.put(LogMsg(f"  {line}", "info"))
                self.msg_queue.put(LinkMsg(f"Download v{version}", url))
        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _load_settings(self):
        try:
            with open(SETTINGS_FILE, "r") as f:
                settings = json.load(f)
            if settings.get("fun_path"):
                self.window.fun_var.set(settings["fun_path"])
            if settings.get("output_path"):
                self.window.output_var.set(settings["output_path"])
            if settings.get("write_input_path"):
                self.window.write_input_var.set(settings["write_input_path"])
            if settings.get("write_output_path"):
                self.window.write_output_var.set(settings["write_output_path"])
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

    def _save_settings(self):
        settings = {
            "fun_path": self.window.fun_var.get().strip(),
            "output_path": self.window.output_var.get().strip(),
            "write_input_path": self.window.write_input_var.get().strip(),
            "write_output_path": self.window.write_output_var.get().strip(),
            "theme": self.window._current_theme,
        }
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, "w") as f:
                json.dump(settings, f, indent=2)
        except OSError:
            pass

    def _on_theme_change(self, theme):
        self._save_settings()
