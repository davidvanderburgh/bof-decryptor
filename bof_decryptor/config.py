"""Constants and configuration for BOF Asset Decryptor."""

import os
import sys

# ---------------------------------------------------------------------------
# Game database
# ---------------------------------------------------------------------------

GAME_DB = {
    "labyrinth": {
        "display": "Jim Henson's Labyrinth",
        "fun_file": "lab.fun",
        "passphrase": "funkey",
        "platform": "Arch Linux, FAST hardware, Godot 4.5 custom build",
    },
    "dune": {
        "display": "Dune",
        "fun_file": "dune.fun",
        "passphrase": "dunekey",
        "platform": "Arch Linux, FAST hardware, Godot 4.5 custom build",
    },
    "winchester": {
        "display": "Winchester Mystery House",
        "fun_file": "winchester.fun",
        "passphrase": "winchesterkey",
        "platform": "Arch Linux, FAST hardware, Godot 4.5 custom build",
    },
}

# Map .fun filename → game key for auto-detection
FUN_FILE_TO_GAME = {info["fun_file"]: key for key, info in GAME_DB.items()}

# Display names for UI
KNOWN_GAMES = {key: info["display"] for key, info in GAME_DB.items()}

# ---------------------------------------------------------------------------
# Pipeline phase names
# ---------------------------------------------------------------------------

DECRYPT_PHASES = [
    "Detect",
    "Decrypt",
    "Extract",
    "Checksums",
    "Cleanup",
]

MODIFY_PHASES = [
    "Scan",
    "Repack",
    "Pack",
    "Encrypt",
    "Cleanup",
]

# ---------------------------------------------------------------------------
# Timeouts (seconds)
# ---------------------------------------------------------------------------

GPG_DECRYPT_TIMEOUT = 600   # GPG decrypt of a ~3 GB file
TAR_EXTRACT_TIMEOUT = 300   # tar xzf of the decrypted archive
GDRE_TIMEOUT = 3600         # GDRE Tools PCK extraction (large binaries take 20-40 min)
CHECKSUM_TIMEOUT = 120
GPG_ENCRYPT_TIMEOUT = 600
TAR_PACK_TIMEOUT = 300

# ---------------------------------------------------------------------------
# Settings file location — platform-aware
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    _SETTINGS_DIR = os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), "bof_decryptor")
elif sys.platform == "darwin":
    _SETTINGS_DIR = os.path.join(
        os.path.expanduser("~/Library/Application Support"), "bof_decryptor")
else:
    _SETTINGS_DIR = os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "bof_decryptor")

SETTINGS_FILE = os.path.join(_SETTINGS_DIR, "settings.json")
