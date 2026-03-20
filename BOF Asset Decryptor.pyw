"""Double-click launcher for BOF Asset Decryptor (no console window)."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _ensure_admin():
    if sys.platform != "win32":
        return
    import ctypes
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return
    except Exception:
        return
    params = " ".join(f'"{a}"' for a in sys.argv)
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, os.getcwd(), 1)
    if ret > 32:
        sys.exit(0)


_ensure_admin()

from bof_decryptor.app import App

App().run()
