# BOF Asset Decryptor

A cross-platform GUI application for decrypting, exploring, and re-packaging game assets from **Barrels of Fun** (Kollect Fun) pinball machines — including Jim Henson's Labyrinth, Dune, and Winchester Mystery House.

## What It Does

Barrels of Fun machines distribute game updates as GPG-encrypted `.fun` files. Inside each `.fun` file is a compressed tar archive containing a Godot 4 binary with an embedded PCK (packed content). This tool:

1. **Detects** the game from the `.fun` filename and auto-selects the correct GPG passphrase
2. **Decrypts** the `.fun` file using GPG AES-256-CFB symmetric encryption
3. **Extracts** the tar archive to recover the Godot binary
4. **Decompiles** the PCK using [GDRE Tools](https://github.com/GDRETools/gdsdecomp) — recovering game scripts, textures, audio, video, and fonts in their original editable formats
5. **Re-packs** modified assets back into a `.fun` file ready to write to USB and apply to the machine
6. **Auto-reimports** modified audio and textures — when you replace a `.wav` or `.png`, the tool automatically converts it to Godot's internal format so the game actually uses your replacement
7. **Mod Packs**: Export your modified files as a shareable zip, or import mod packs from other users

## Supported Games

| Game | `.fun` file |
|------|------------|
| Jim Henson's Labyrinth | `lab.fun` |
| Dune | `dune.fun` |
| Winchester Mystery House | `winchester.fun` |

## Requirements

**Game source**: the `.fun` code update file for your game, downloaded from the BOF support portal or copied from a USB update drive.

### Windows

- **Windows 10/11** with WSL2 enabled
- **WSL2** with Ubuntu: `wsl --install`
- GPG, tar, curl, xvfb, unzip, webp (cwebp) in WSL — installed automatically via **Install Missing**
- **GDRE Tools** — automatically downloaded and installed
- The app **auto-requests Administrator privileges** on launch (required for WSL operations)

### macOS

- **macOS 12+** (Intel or Apple Silicon)
- **Homebrew** — installed automatically if missing
- GPG (`brew install gnupg`), cwebp (`brew install webp`) — installed automatically via **Install Missing**
- **GDRE Tools** — automatically downloaded and installed

### Linux

- GPG, tar, curl, unzip, xvfb, cwebp — install via your package manager
- **GDRE Tools** — automatically downloaded and installed
- Run as root or with sudo for prerequisite installation

## Installation

### Pre-built Installers (Recommended)

Download from the [Releases page](https://github.com/davidvanderburgh/bof-decryptor/releases):

| Platform | File | Notes |
|----------|------|-------|
| Windows | `BOF_Asset_Decryptor_Setup_v*.exe` | Includes bundled Python runtime |
| macOS | `BOF_Asset_Decryptor_v*.dmg` | Universal binary (Intel + Apple Silicon) |
| Linux | `BOF_Asset_Decryptor_v*.AppImage` | Portable, no install needed |

**Windows setup:**
1. Run the installer (requires Administrator)
2. Launch the app — it auto-requests elevation on startup
3. Click **Check** → if anything is missing, click **Install Missing**
4. The app downloads and installs GPG, xvfb, cwebp, and GDRE Tools automatically

The app checks for updates automatically on startup.

### Run from Source

1. Install [Python 3.10+](https://www.python.org/downloads/)
2. Clone and run:
   ```
   git clone https://github.com/davidvanderburgh/bof-decryptor.git
   cd bof-decryptor
   python -m bof_decryptor
   ```

No Python packages are required — the app uses only the standard library.

## Usage

The app has three tabs: **Decrypt**, **Write**, and **Mod Pack**.

### Decrypt Tab

Extract and decompile all game assets from a `.fun` file.

1. Browse to your `.fun` file — the game is auto-detected from the filename
2. Set an output folder for the extracted assets
3. Click **Decrypt**

| Phase | What Happens |
|-------|-------------|
| **Detect** | Identifies the game, verifies the GPG passphrase, checks system accessibility |
| **Decrypt** | GPG decrypts the `.fun` file → raw tar.gz archive |
| **Extract** | Unpacks the tar archive, recovers the Godot binary |
| **Checksums** | GDRE Tools decompiles the PCK — recovering scripts, textures, audio, video. Generates baseline checksums for mod pack change detection |
| **Cleanup** | Removes intermediate temp files |

### Write Tab

After editing assets, re-pack them into a new `.fun` file ready for USB.

1. Browse to the **original `.fun` file** (auto-populated after decrypt)
2. Browse to the **assets folder** created by the Decrypt step
3. Set an **output folder** — the `.fun` filename is auto-determined from the original
4. Click **Build .fun**

| Phase | What Happens |
|-------|-------------|
| **Decrypt** | Decrypts the original `.fun` to a temp directory (preserves exact archive structure) |
| **Patch** | Detects modified files via mtime, reimports audio/textures to Godot format, patches changes into the binary via GDRE `--pck-patch` |
| **Repack** | Re-tars with the exact same structure as the original |
| **Encrypt** | GPG-encrypts → output `.fun` file |
| **Cleanup** | Removes temp files, updates MD5 checksum in the archive |

### Asset Reimport

When you replace a source file, Godot doesn't load it directly — it loads a pre-imported cached version from `.godot/imported/`. The Write pipeline handles this automatically:

| Source file you edit | Imported format (auto-generated) | Method |
|---------------------|--------------------------------|--------|
| `.wav` | `.sample` (AudioStreamWAV) | Pure Python — byte-identical to Godot's output |
| `.ogg` | `.oggvorbisstr` (AudioStreamOggVorbis) | Pure Python — OGG packet extraction + RSRC builder |
| `.png` / `.jpg` | `.ctex` (CompressedTexture2D) | `cwebp` lossless + GST2 header from original |
| `.ogv` (video) | *(none — stored as-is)* | Direct patch, no reimport needed |

Both the source file and its imported version are patched into the binary.

### Mod Pack Tab

Share your modifications with other users without sharing the full extracted game.

**Export:** Decrypt → make changes → click **Export Mod Pack** → saves a zip of only changed files

**Import:** Decrypt your own game → click **Import Mod Pack** → use Write tab to rebuild

### Editing Assets

Edit files directly in the `pck/` subfolder using any tool:

| File type | How to edit |
|-----------|-------------|
| Audio (`.ogg`, `.wav`) | Audacity, any audio editor |
| Video (`.ogv`) | ffmpeg, Kdenlive — output must be Theora `.ogv` |
| Textures (`.png`) | Photoshop, GIMP, etc. |
| Game scripts (`.gd`) | Any text editor |
| Scenes (`.tscn`) | Godot editor (optional) |

> You only need to edit the source file — the Write pipeline automatically converts it to Godot's internal format and patches both copies.

### Installing on the Machine

1. Copy the output `.fun` file to a USB drive formatted **FAT32**
2. Open the pinball machine backbox and locate the PC
3. With the machine running, insert the USB drive into any USB port
4. The machine will update automatically. Remove the USB when prompted.

## Architecture

```
bof_decryptor/
├── __init__.py      # Version string
├── __main__.py      # Entry point, auto-elevates to admin on Windows
├── app.py           # Application controller — wires GUI ↔ pipeline via queue
├── gui.py           # Tkinter GUI with dark/light theme, 3 tabs
├── pipeline.py      # DecryptPipeline + ModifyPipeline + mod pack + reimport converters
├── config.py        # Game DB (passphrases, filenames), phase names, timeouts
├── executor.py      # Platform-aware executor (WslExecutor / MacExecutor / NativeExecutor)
└── updater.py       # Auto-update checker (GitHub releases API)
```

### Platform Executors

| Platform | Executor | How it works |
|----------|----------|-------------|
| Windows | `WslExecutor` | Runs commands via `wsl -u root -- bash -c` |
| macOS | `MacExecutor` | Runs commands natively via `bash -c` with Homebrew PATH |
| Linux | `NativeExecutor` | Runs commands directly or via sudo |

## The `.fun` File Format

```
dune.fun
└── GPG AES-256-CFB symmetric encryption (passphrase per game)
    └── tar.gz archive
        ├── GDHarvest_20260217.x86_64  (Godot binary with embedded PCK)
        ├── md5                         (MD5 checksum of the binary)
        ├── bossac                      (firmware flasher)
        ├── worm_wrangler_main.bin      (microcontroller firmware)
        ├── updated_bash_profile        (shell config)
        └── updated_updatecode          (update handler script)
```

The machine validates the `.fun` file by decrypting with its stored passphrase, then checking the `md5` file against the binary's hash. The Write pipeline updates the `md5` file after patching.

## Troubleshooting

### Prerequisites show as missing after clicking Install

- **Windows**: WSL must be able to reach the internet. If the dpkg lock is held, wait for `unattended-upgrades` to finish (the app auto-waits).
- **macOS**: Homebrew must be installed. The app installs it automatically if missing.

### GDRE Tools shows "No valid paths provided!"

The PCK path isn't accessible. If the output folder is on an external drive plugged in after WSL started, run `wsl --shutdown` and retry.

### Tar or GPG times out

All operations have a 2-hour timeout. If you're consistently hitting it, check disk space and WSL filesystem performance.

### "NO GAME CODE" on the pinball machine

The machine rejected the `.fun` file after validation. Check:
- The original `.fun` file is valid (can you decrypt it manually?)
- The `md5` file in the archive matches the binary (the Write pipeline updates this automatically)
- The USB drive is **FAT32** formatted

### macOS: Godot headless killed (exit 137)

macOS Gatekeeper kills unsigned binaries. The app ad-hoc signs Godot during install. If it still fails, run manually:
```
codesign --force --deep --sign - ~/.local/bin/godot
```

Note: Godot headless is only needed for OGG files (2 in Dune). WAV conversion is pure Python.

## Building

### Windows Installer

Requires [Inno Setup 6](https://jrsoftware.org/isinfo.php):
```powershell
cd installer
powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1
```

### macOS DMG

```bash
bash installer/build_macos.sh
```

### Linux AppImage

```bash
bash installer/build_linux.sh
```

## Versioning

Version lives in `bof_decryptor/__init__.py`. To release:

1. Bump `__version__`
2. Tag and push: `git tag v<version> && git push origin v<version>`
3. GitHub Actions builds Windows, macOS, and Linux installers and attaches them to the release

## License

MIT License. See [LICENSE](LICENSE) for details.
