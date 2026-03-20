"""Entry point: python -m bof_decryptor"""

import sys


def _ensure_admin():
    """On Windows, re-launch as Administrator if not already elevated."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return
    except Exception:
        return

    import os
    params = " ".join(f'"{a}"' for a in sys.argv)
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, os.getcwd(), 1)
    if ret > 32:
        sys.exit(0)


if __name__ == "__main__":
    _ensure_admin()
    from .app import App
    App().run()
