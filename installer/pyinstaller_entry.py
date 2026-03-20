"""PyInstaller entry point — uses absolute imports instead of relative."""

from bof_decryptor.app import App

if __name__ == "__main__":
    App().run()
