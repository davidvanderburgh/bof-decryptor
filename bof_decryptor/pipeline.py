"""Decrypt and modify pipelines for BOF Asset Decryptor."""

import hashlib
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import zipfile

from .config import (
    GAME_DB, FUN_FILE_TO_GAME, DECRYPT_PHASES, MODIFY_PHASES,
    GPG_DECRYPT_TIMEOUT, TAR_EXTRACT_TIMEOUT, GDRE_TIMEOUT,
    CHECKSUM_TIMEOUT, GPG_ENCRYPT_TIMEOUT, TAR_PACK_TIMEOUT,
)
from .executor import CommandError

CHECKSUMS_FILE = ".checksums.md5"
GODOT_VERSION = "4.4.1"
if sys.platform == "darwin":
    GODOT_HEADLESS_PATH = os.path.expanduser("~/.local/bin/godot")
else:
    GODOT_HEADLESS_PATH = f"/opt/Godot_v{GODOT_VERSION}-stable_linux.x86_64"


def _parse_import_remap(import_file_path):
    """Parse a Godot .import file and return the dest path (relative to pck root).

    Returns None if the file doesn't exist or has no remap path.
    """
    if not os.path.isfile(import_file_path):
        return None
    try:
        with open(import_file_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("path="):
                    path = line.split("=", 1)[1].strip('"').strip("'")
                    if path.startswith("res://"):
                        path = path[len("res://"):]
                    return path
    except Exception:
        pass
    return None

class _nullctx:
    """No-op context manager."""
    def __enter__(self): return self
    def __exit__(self, *exc): pass


class PipelineError(Exception):
    def __init__(self, phase, message):
        self.phase = phase
        self.message = message
        super().__init__(message)


class _BasePipeline:
    def __init__(self, log_cb, phase_cb, progress_cb, done_cb):
        self._log = log_cb
        self._phase_cb = phase_cb
        self._progress = progress_cb
        self._done = done_cb
        self._cancelled = False
        self.log_link = None  # optional: fn(text, url)

    def cancel(self):
        self._cancelled = True

    def _check_cancel(self):
        if self._cancelled:
            raise PipelineError("Cancelled", "Operation cancelled by user.")

    def _set_phase(self, index):
        self._phase_cb(index)

    def _poll_file_progress(self, wsl_path, expected_bytes, label=""):
        """Return a context manager that polls a WSL file's size in a
        background thread and updates the progress bar as a percentage
        of *expected_bytes*.  Stops automatically on ``__exit__``."""
        parent = self
        stop = threading.Event()

        def _poll():
            while not stop.is_set():
                try:
                    out = parent.executor.run(
                        f"stat -f%z {wsl_path!r} 2>/dev/null || stat -c%s {wsl_path!r} 2>/dev/null || echo 0",
                        timeout=5,
                    ).strip()
                    cur = int(out)
                except Exception:
                    cur = 0
                if expected_bytes > 0:
                    pct = min(int(100 * cur / expected_bytes), 99)
                    parent._progress(pct, 100,
                                     f"{label} {pct}%" if label else f"{pct}%")
                stop.wait(1.0)

        class _Ctx:
            def __enter__(self_ctx):
                self_ctx._t = threading.Thread(target=_poll, daemon=True)
                self_ctx._t.start()
                return self_ctx
            def __exit__(self_ctx, *exc):
                stop.set()
                self_ctx._t.join(timeout=3)

        return _Ctx()

    def _resolve_gpg(self):
        """Return full path to gpg, ensuring it's found even in macOS .app bundles."""
        # 1. On macOS/Linux: check common paths directly from Python (no bash)
        if sys.platform != "win32":
            for candidate in [
                "/opt/homebrew/bin/gpg",
                "/usr/local/bin/gpg",
                "/usr/local/MacGPG2/bin/gpg",
                "/opt/local/bin/gpg",
                "/usr/bin/gpg",
            ]:
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    return candidate

        # 2. Ask the executor (goes through bash/WSL)
        try:
            path = self.executor.run(
                "command -v gpg 2>/dev/null || which gpg 2>/dev/null",
                timeout=10,
            ).strip()
            if path and path != "gpg":
                return path
        except Exception:
            pass
        return "gpg"  # last resort

    def _godot_headless_prefix(self):
        """Return the shell prefix to invoke Godot 4 headlessly."""
        if sys.platform == "darwin":
            # Clear quarantine in case it wasn't cleared during install
            return (
                f"xattr -cr '{GODOT_HEADLESS_PATH}' 2>/dev/null; "
                f"GODOT_SILENCE_ROOT_WARNING=1 '{GODOT_HEADLESS_PATH}' --headless "
            )
        return (
            "DISPLAY= WAYLAND_DISPLAY= "
            "GODOT_SILENCE_ROOT_WARNING=1 "
            f"xvfb-run -a {GODOT_HEADLESS_PATH} --headless "
        )

    def _gdre_prefix(self):
        """Return the shell prefix to invoke GDRE Tools headlessly."""
        if sys.platform == "darwin":
            install_dir = os.path.expanduser("~/.local/share/gdre_tools")
            return (
                "GODOT_SILENCE_ROOT_WARNING=1 "
                f"'{install_dir}/Godot RE Tools' --headless "
            )
        # Linux / WSL: needs xvfb for headless display
        return (
            "DISPLAY= WAYLAND_DISPLAY= "
            "GODOT_SILENCE_ROOT_WARNING=1 "
            "LD_LIBRARY_PATH=/opt/gdre_tools "
            "xvfb-run -a /opt/gdre_tools/gdre_tools.x86_64 --headless "
        )

    def run(self):
        raise NotImplementedError


def check_prerequisites(executor):
    """Check that gpg is available in the executor environment.

    Returns a list of (name, passed, message) tuples.
    """
    results = []

    # Executor availability
    ok, msg = executor.check_available()
    executor_name = type(executor).__name__
    if "Wsl" in executor_name:
        label = "WSL2"
    elif "Mac" in executor_name:
        label = "macOS"
    else:
        label = "System"
    results.append((label, ok, msg))

    if not ok:
        return results

    # gpg — check common paths directly from Python first (avoids bash PATH issues)
    gpg_path = None
    if sys.platform != "win32":
        for candidate in [
            "/opt/homebrew/bin/gpg", "/usr/local/bin/gpg",
            "/usr/local/MacGPG2/bin/gpg", "/opt/local/bin/gpg", "/usr/bin/gpg",
        ]:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                gpg_path = candidate
                break
    if gpg_path:
        results.append(("gpg", True, gpg_path))
    else:
        try:
            executor.run("gpg --version > /dev/null 2>&1", timeout=10)
            gpg_path = executor.run(
                "command -v gpg 2>/dev/null || which gpg 2>/dev/null || echo gpg",
                timeout=10,
            ).strip()
            results.append(("gpg", True, gpg_path))
        except Exception:
            if sys.platform == "darwin":
                msg = "Not found — install with: brew install gnupg"
            else:
                msg = "Not found — install with: apt-get install gnupg"
            results.append(("gpg", False, msg))

    # tar
    try:
        executor.run("tar --version > /dev/null 2>&1", timeout=10)
        results.append(("tar", True, "available"))
    except Exception:
        results.append(("tar", False, "Not found — install with: apt-get install tar"))

    # gdre_tools (optional — for Godot PCK extraction)
    try:
        local_bin = os.path.expanduser("~/.local/bin/gdre_tools")
        path = executor.run(
            f"which gdre_tools 2>/dev/null || "
            f"(test -x '{local_bin}' && echo '{local_bin}') || "
            f"echo MISSING",
            timeout=10,
        ).strip()
        if "MISSING" in path or not path:
            results.append(("gdre_tools", False,
                            "Optional — click Install Missing to download automatically"))
        else:
            results.append(("gdre_tools", True, path.strip()))
    except Exception:
        results.append(("gdre_tools", False,
                        "Optional — click Install Missing to download automatically"))

    # godot (for audio reimport during Write)
    try:
        executor.run(f"test -x {GODOT_HEADLESS_PATH}", timeout=5)
        results.append(("godot", True, GODOT_HEADLESS_PATH))
    except Exception:
        results.append(("godot", False,
                        "Optional — click Install Missing to download automatically"))

    # cwebp (for texture reimport during Write)
    try:
        executor.run("cwebp -version > /dev/null 2>&1", timeout=5)
        results.append(("cwebp", True, "available"))
    except Exception:
        results.append(("cwebp", False,
                        "Optional — click Install Missing to download automatically"))

    return results


def detect_game(fun_path):
    """Return the game key for a given .fun file path, or None if unknown."""
    filename = os.path.basename(fun_path).lower()
    return FUN_FILE_TO_GAME.get(filename)


def export_mod_pack(assets_folder, zip_path, log_cb=None, progress_cb=None):
    """Package only modified files (per .checksums.md5) into a zip.

    Returns (num_changed, zip_path).
    """
    checksums_file = os.path.join(assets_folder, CHECKSUMS_FILE)
    if not os.path.isfile(checksums_file):
        raise FileNotFoundError(f"No {CHECKSUMS_FILE} found in {assets_folder}")

    baseline = {}
    with open(checksums_file, "r") as f:
        for line in f:
            line = line.strip()
            if "\t" in line:
                path, md5 = line.rsplit("\t", 1)
                baseline[path] = md5

    changed = []
    for rel_path, orig_md5 in baseline.items():
        abs_path = os.path.join(assets_folder, rel_path)
        if not os.path.isfile(abs_path):
            continue
        current_md5 = _md5_file(abs_path)
        if current_md5 != orig_md5:
            changed.append(rel_path)

    if not changed:
        raise ValueError("No modified files found. Modify some files first.")

    if log_cb:
        log_cb(f"Packing {len(changed)} modified file(s)...", "info")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, rel_path in enumerate(changed):
            abs_path = os.path.join(assets_folder, rel_path)
            zf.write(abs_path, rel_path)
            if progress_cb:
                progress_cb(i + 1, len(changed), rel_path)

    return len(changed), zip_path


def import_mod_pack(zip_path, assets_folder, log_cb=None, progress_cb=None):
    """Extract a mod pack zip into the assets folder. Returns number of files."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        if log_cb:
            log_cb(f"Importing {len(names)} file(s)...", "info")
        for i, name in enumerate(names):
            zf.extract(name, assets_folder)
            if progress_cb:
                progress_cb(i + 1, len(names), name)
    return len(names)


def _md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _generate_checksums(folder, log_cb, progress_cb):
    """Walk folder and write .checksums.md5. Returns file count."""
    files = []
    for dirpath, _, filenames in os.walk(folder):
        for fn in filenames:
            if fn.startswith("."):
                continue
            abs_path = os.path.join(dirpath, fn)
            rel_path = os.path.relpath(abs_path, folder).replace("\\", "/")
            files.append((rel_path, abs_path))

    checksums_path = os.path.join(folder, CHECKSUMS_FILE)
    with open(checksums_path, "w") as out:
        for i, (rel_path, abs_path) in enumerate(files):
            md5 = _md5_file(abs_path)
            out.write(f"{rel_path}\t{md5}\n")
            if progress_cb:
                progress_cb(i + 1, len(files), rel_path)

    if log_cb:
        log_cb(f"Checksums written for {len(files)} file(s).", "success")
    return len(files)


# ---------------------------------------------------------------------------
# Decrypt pipeline
# ---------------------------------------------------------------------------

class DecryptPipeline(_BasePipeline):
    """GPG decrypt a .fun file and extract the Godot binary (and optionally unpack PCK)."""

    def __init__(self, fun_path, output_dir, executor,
                 log_cb, phase_cb, progress_cb, done_cb,
                 unpack_pck=False):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.fun_path = fun_path
        self.output_dir = output_dir
        self.executor = executor
        self.unpack_pck = unpack_pck
        self._tmp_dir = None

    def run(self):
        try:
            self._run()
        except PipelineError as e:
            self._done(False, e.message)
        except Exception as e:
            self._done(False, f"Unexpected error: {e}")

    def _run(self):
        # Phase 0 — Detect
        self._set_phase(0)
        self._log("Detecting game...", "info")
        game_key = detect_game(self.fun_path)
        if game_key is None:
            raise PipelineError("Detect",
                f"Unrecognised file: {os.path.basename(self.fun_path)}\n"
                f"Expected one of: {', '.join(FUN_FILE_TO_GAME.keys())}")
        game_info = GAME_DB[game_key]
        self._log(f"Game detected: {game_info['display']}", "success")
        self._check_cancel()

        # Verify output path is accessible from executor
        os.makedirs(self.output_dir, exist_ok=True)
        ok, msg = self.executor.check_path_accessible(self.output_dir)
        if not ok:
            raise PipelineError("Detect", msg)

        passphrase = game_info["passphrase"]
        fun_wsl = self.executor.to_exec_path(self.fun_path)
        out_wsl = self.executor.to_exec_path(self.output_dir)
        gpg_bin = self._resolve_gpg()
        self._log(f"Using gpg: {gpg_bin}", "info")

        # Phase 1 — Decrypt
        self._set_phase(1)
        self._log(f"Decrypting {os.path.basename(self.fun_path)} with GPG...", "info")
        self._progress(0, 100, "GPG decrypting...")

        fun_size = os.path.getsize(self.fun_path)
        tmp_tar_wsl = f"/tmp/bof_{game_key}.tar.gz"
        try:
            with self._poll_file_progress(tmp_tar_wsl, fun_size, "Decrypting..."):
                self.executor.run(
                    f"{gpg_bin} --batch --yes --passphrase={passphrase!r} "
                    f"--decrypt --output {tmp_tar_wsl!r} {fun_wsl!r} 2>&1",
                    timeout=GPG_DECRYPT_TIMEOUT,
                )
        except CommandError as e:
            raise PipelineError("Decrypt",
                f"GPG decryption failed:\n{e.output}\n\n"
                f"Check that the .fun file is not corrupted.")
        self._log("GPG decryption complete.", "success")
        self._check_cancel()

        # Phase 2 — Extract tar
        self._set_phase(2)
        self._log("Extracting archive...", "info")
        self._progress(0, 100, "Extracting tar.gz...")

        # Get compressed size to estimate extraction progress.
        # Uncompressed is typically ~2x the .tar.gz; we poll du -sb on the
        # output directory vs that estimate.
        tar_size = 0
        try:
            tar_size = int(self.executor.run(
                f"stat -f%z {tmp_tar_wsl!r} 2>/dev/null || stat -c%s {tmp_tar_wsl!r} 2>/dev/null || echo 0",
                timeout=10,
            ).strip())
        except Exception:
            pass
        estimated_uncompressed = tar_size * 2 if tar_size else 0

        tmp_extract_wsl = f"/tmp/bof_{game_key}_extracted"
        try:
            self.executor.run(
                f"rm -rf {tmp_extract_wsl!r} && mkdir -p {tmp_extract_wsl!r}",
                timeout=30,
            )
            with self._poll_file_progress(
                tmp_extract_wsl, estimated_uncompressed, "Extracting..."
            ) if estimated_uncompressed else _nullctx():
                self.executor.run(
                    f"tar -xzf {tmp_tar_wsl!r} -C {tmp_extract_wsl!r} 2>&1",
                    timeout=TAR_EXTRACT_TIMEOUT,
                )
        except CommandError as e:
            raise PipelineError("Extract", f"Archive extraction failed:\n{e.output}")

        # List extracted contents
        try:
            contents = self.executor.run(
                f"ls -lh {tmp_extract_wsl!r}", timeout=10
            ).strip()
            for line in contents.split("\n"):
                if line.strip():
                    self._log(f"  {line.strip()}", "info")
        except Exception:
            pass

        self._log("Archive extracted.", "success")
        self._check_cancel()

        # Copy extracted files to output directory
        self._log(f"Copying to output folder...", "info")
        try:
            self.executor.run(
                f"cp -r {tmp_extract_wsl!r}/. {out_wsl!r}/ 2>&1",
                timeout=120,
            )
        except CommandError as e:
            raise PipelineError("Extract", f"Copy to output failed:\n{e.output}")

        # Find the Godot binary
        binary_name = ""
        try:
            binary_name = self.executor.run(
                f"find {out_wsl!r} -name '*.x86_64' -type f | head -1",
                timeout=15,
            ).strip()
            if binary_name:
                size = self.executor.run(
                    f"du -h {binary_name!r} | cut -f1", timeout=10
                ).strip()
                self._log(f"Godot binary: {os.path.basename(binary_name)} ({size})",
                          "success")
        except Exception:
            pass

        # Optional: unpack PCK with GDRE Tools
        if self.unpack_pck:
            self._set_phase(2)  # still in extract phase visually
            self._log("Unpacking Godot PCK with GDRE Tools...", "info")
            self._progress(0, 100, "Starting...")
            try:
                pck_out = f"{out_wsl}/pck"
                binary_wsl = binary_name if binary_name else f"{out_wsl}/GDCraze.x86_64"
                gdre_prefix = self._gdre_prefix()

                # GDRE outputs phase progress as "Phase name... [===] XX%" separated
                # by \r (not \n), so we split each streamed line on \r and parse.
                # Phases mapped to overall 0-100%:
                # Poll the Windows-side pck folder in a background thread.
                # We parse "Verified X files" from GDRE output to set the extraction
                # total; the export phase writes additional converted files beyond that.
                pck_win = os.path.join(self.output_dir, "pck")
                os.makedirs(pck_win, exist_ok=True)
                baseline = sum(len(fs) for _, _, fs in os.walk(pck_win))
                _stop_poll = threading.Event()
                _last_count = [0]
                _extract_done = [False]
                _extract_snap = [0]   # file count at moment extraction finishes
                _LOG_EVERY = 500

                def _poll_pck():
                    prev_logged = 0
                    while not _stop_poll.is_set():
                        raw = sum(len(fs) for _, _, fs in os.walk(pck_win))
                        count = max(0, raw - baseline)
                        _last_count[0] = count
                        if _extract_done[0]:
                            converted = max(0, count - _extract_snap[0])
                            self._progress(0, 0,
                                           f"Converting resources... {converted} converted")
                            if converted - prev_logged >= _LOG_EVERY and converted > 0:
                                prev_logged = (converted // _LOG_EVERY) * _LOG_EVERY
                                self._log(f"  {converted} resources converted...", "info")
                        else:
                            self._progress(0, 0, f"Extracting... {count} files")
                            if count - prev_logged >= _LOG_EVERY and count > 0:
                                prev_logged = (count // _LOG_EVERY) * _LOG_EVERY
                                self._log(f"  {count} files extracted...", "info")
                        _stop_poll.wait(1.0)

                poll_thread = threading.Thread(target=_poll_pck, daemon=True)
                poll_thread.start()

                # Stream --recover; parse key lines to drive progress state
                _extracted_re = re.compile(r'Extracted (\d+) files')
                _skip = ("Godot Engine", "input_file", "Input files", "GDRE Tools",
                         "Ubuntu", "Loading import", "Loading GDScript",
                         "Reading PCK", "Extracting files", "Exporting resources",
                         "Reading folder", "Generating filesystem")
                try:
                    for raw in self.executor.stream(
                        f"mkdir -p {pck_out!r} && "
                        f"{gdre_prefix} --recover={binary_wsl!r} --output={pck_out!r} 2>&1",
                        timeout=GDRE_TIMEOUT,
                    ):
                        for chunk in raw.split('\r'):
                            chunk = chunk.strip()
                            if not chunk:
                                continue
                            em = _extracted_re.search(chunk)
                            if em:
                                _extract_done[0] = True
                                _extract_snap[0] = _last_count[0]
                                self._log(f"  {chunk}", "info")
                                self._log("  Converting resources to source formats"
                                          " (decompiling scripts, textures → PNG, etc.)...",
                                          "info")
                                continue
                            if any(chunk.startswith(s) for s in _skip):
                                continue
                            if any(tag in chunk for tag in ("ERROR", "WARN")):
                                self._log(f"  {chunk}", "warning")
                            else:
                                self._log(f"  {chunk}", "info")
                finally:
                    _stop_poll.set()
                    poll_thread.join(timeout=2)

                final = _last_count[0]
                self._progress(100, 100, f"{final} files extracted")
                self._log(f"PCK unpacked to pck/ subfolder ({final} files).",
                          "success")
            except CommandError as e:
                self._log(
                    f"GDRE Tools failed (PCK may still be usable as binary): {e.output}",
                    "error")

        # Phase 3 — Checksums
        self._set_phase(3)
        self._log("Generating baseline checksums...", "info")
        _generate_checksums(self.output_dir, self._log,
                            lambda c, t, d: self._progress(c, t, d))
        self._check_cancel()

        # Phase 4 — Cleanup
        self._set_phase(4)
        self._log("Cleaning up temporary files...", "info")
        try:
            self.executor.run(
                f"rm -rf {tmp_tar_wsl!r} {tmp_extract_wsl!r} 2>/dev/null; true",
                timeout=30,
            )
        except Exception:
            pass
        self._log("Cleanup complete.", "success")

        self._done(True,
            f"{game_info['display']} decrypted successfully.\n\n"
            f"Output: {self.output_dir}\n\n"
            f"Game assets extracted to the pck/ subfolder.")


# ---------------------------------------------------------------------------
# Modify (re-encrypt) pipeline
# ---------------------------------------------------------------------------

class ModifyPipeline(_BasePipeline):
    """Patch modified assets into a copy of the original .fun file."""

    def __init__(self, original_fun, assets_dir, output_fun_path, game_key,
                 executor, log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.original_fun = original_fun
        self.assets_dir = assets_dir
        self.output_fun_path = output_fun_path
        self.game_key = game_key
        self.executor = executor

    # ------------------------------------------------------------------
    # Asset reimport helpers
    # ------------------------------------------------------------------

    def _reimport_assets(self, changed_pck, pck_dir, pck_dir_wsl):
        """For changed source files with .import sidecars, regenerate the
        imported version and return additional relative paths to patch."""
        _IMPORTABLE = (".wav", ".ogg", ".png", ".jpg", ".jpeg")
        audio_jobs = []    # (rel_source, dest_rel, ext)
        texture_jobs = []  # (rel_source, dest_rel)

        for rel in changed_pck:
            lower = rel.lower()
            if not any(lower.endswith(ext) for ext in _IMPORTABLE):
                continue
            import_file = os.path.join(pck_dir, rel + ".import")
            dest_rel = _parse_import_remap(import_file)
            if not dest_rel:
                continue
            # Verify original imported file exists (we need its header for textures)
            dest_abs = os.path.join(pck_dir, dest_rel)
            if not os.path.isfile(dest_abs):
                self._log(f"  Warning: imported file missing: {dest_rel}", "error")
                continue
            if lower.endswith((".wav", ".ogg")):
                audio_jobs.append((rel, dest_rel, "wav" if lower.endswith(".wav") else "ogg"))
            else:
                texture_jobs.append((rel, dest_rel))

        extra = []
        if audio_jobs:
            self._reimport_audio(audio_jobs, pck_dir, pck_dir_wsl)
            extra.extend(d for _, d, _ in audio_jobs)
        if texture_jobs:
            self._reimport_textures(texture_jobs, pck_dir, pck_dir_wsl)
            extra.extend(d for _, d in texture_jobs)
        return extra

    def _reimport_audio(self, jobs, pck_dir, pck_dir_wsl):
        """Convert wav/ogg source files to Godot .sample/.oggvorbisstr using
        Godot 4 headless."""
        import base64 as _b64

        gdscript = r'''extends SceneTree

func _init():
    var args = OS.get_cmdline_user_args()
    var i = 0
    while i + 1 < args.size():
        var src = args[i]
        var dst = args[i + 1]
        if src.ends_with(".ogg"):
            _convert_ogg(src, dst)
        elif src.ends_with(".wav"):
            _convert_wav(src, dst)
        i += 2
    quit()

func _convert_ogg(src: String, dst: String):
    var stream = AudioStreamOggVorbis.load_from_file(src)
    if stream == null:
        printerr("Cannot load OGG: ", src)
        return
    var err = ResourceSaver.save(stream, dst)
    print("OK " + dst if err == OK else "FAIL " + dst)

func _convert_wav(src: String, dst: String):
    var file = FileAccess.open(src, FileAccess.READ)
    if not file:
        printerr("Cannot open WAV: ", src)
        return
    var buf = file.get_buffer(file.get_length())
    file.close()
    var channels = buf.decode_u16(22)
    var sample_rate = buf.decode_u32(24)
    var bits = buf.decode_u16(34)
    # Find data chunk
    var pos = 12
    var data_start = -1
    var data_size = 0
    while pos < buf.size() - 8:
        var cid = buf.slice(pos, pos + 4).get_string_from_ascii()
        var csz = buf.decode_u32(pos + 4)
        if cid == "data":
            data_start = pos + 8
            data_size = csz
            break
        pos += 8 + csz
        if csz % 2 == 1:
            pos += 1
    if data_start < 0:
        printerr("No data chunk in WAV: ", src)
        return
    var stream = AudioStreamWAV.new()
    stream.format = AudioStreamWAV.FORMAT_16_BITS if bits == 16 else AudioStreamWAV.FORMAT_8_BITS
    stream.mix_rate = sample_rate
    stream.stereo = (channels == 2)
    stream.data = buf.slice(data_start, data_start + data_size)
    var err = ResourceSaver.save(stream, dst)
    print("OK " + dst if err == OK else "FAIL " + dst)
'''
        script_path = "/tmp/bof_convert.gd"
        b64 = _b64.b64encode(gdscript.encode()).decode()
        self.executor.run(
            f"echo {b64!r} | base64 -d > {script_path}",
            timeout=10,
        )

        # Build args: src1 dst1 src2 dst2 ...
        args_parts = []
        for rel_src, dest_rel, _ in jobs:
            src_wsl = f"{pck_dir_wsl}/{rel_src}"
            # Write the reimported file directly into the user's pck dir
            dst_wsl = f"{pck_dir_wsl}/{dest_rel}"
            args_parts.append(f"'{src_wsl}' '{dst_wsl}'")

        godot = self._godot_headless_prefix()
        self._log(f"  Reimporting {len(jobs)} audio file(s) via Godot...", "info")
        self._log(f"    Using: {GODOT_HEADLESS_PATH}", "info")
        cmd = (
            f"{godot} --script {script_path} -- "
            f"{' '.join(args_parts)} 2>&1"
        )
        try:
            output = self.executor.run(cmd, timeout=300)
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("OK "):
                    self._log(f"    {line}", "success")
                else:
                    self._log(f"    {line}", "info")
        except CommandError as e:
            self._log(f"  Audio reimport failed (exit {e.returncode}):", "error")
            for line in (e.output or "").splitlines():
                line = line.strip()
                if line:
                    self._log(f"    {line}", "error")

        # Verify each converted file was actually written
        failed = set()
        for rel_src, dest_rel, ext in jobs:
            dest_abs = os.path.join(pck_dir, dest_rel)
            src_abs = os.path.join(pck_dir, rel_src)
            src_mtime = os.path.getmtime(src_abs)
            if not os.path.isfile(dest_abs) or os.path.getmtime(dest_abs) < src_mtime:
                self._log(f"    WARNING: reimport failed for {rel_src}", "error")
                failed.add(dest_rel)
        # Remove failed entries so they don't get patched with stale data
        jobs[:] = [(s, d, e) for s, d, e in jobs if d not in failed]

    def _reimport_textures(self, jobs, pck_dir, pck_dir_wsl):
        """Convert png/jpg source files to Godot .ctex using cwebp + GST2 header."""
        import base64 as _b64
        import struct as _struct

        self._log(f"  Reimporting {len(jobs)} texture(s)...", "info")
        for rel_src, dest_rel in jobs:
            dest_abs = os.path.join(pck_dir, dest_rel)

            # Read original ctex header (everything before the RIFF/WebP data)
            try:
                with open(dest_abs, "rb") as f:
                    orig_data = f.read()
                riff_offset = orig_data.find(b"RIFF")
                if riff_offset < 0:
                    self._log(f"    Skipping {rel_src}: ctex not WebP-based", "error")
                    continue
                header = bytearray(orig_data[:riff_offset])
            except Exception as e:
                self._log(f"    Skipping {rel_src}: {e}", "error")
                continue

            # Convert source image to WebP lossless, get size, assemble ctex
            src_wsl = f"{pck_dir_wsl}/{rel_src}"
            dest_wsl = self.executor.to_exec_path(dest_abs)
            tmp_webp = "/tmp/bof_tex.webp"
            header_b64 = _b64.b64encode(bytes(header)).decode()

            try:
                # cwebp convert + assemble in one shot
                self.executor.run(
                    f"cwebp -lossless -quiet '{src_wsl}' -o {tmp_webp} 2>&1",
                    timeout=60,
                )
                # Get WebP size and update the length field in the header
                webp_size = int(self.executor.run(
                    f"stat -f%z {tmp_webp} 2>/dev/null || stat -c%s {tmp_webp}",
                    timeout=5,
                ).strip())
                _struct.pack_into("<I", header, len(header) - 4, webp_size)
                header_b64 = _b64.b64encode(bytes(header)).decode()

                # Write header + WebP data to the imported ctex file
                self.executor.run(
                    f"echo {header_b64!r} | base64 -d > '{dest_wsl}' && "
                    f"cat {tmp_webp} >> '{dest_wsl}'",
                    timeout=30,
                )
                self._log(f"    OK {dest_rel}", "info")
            except CommandError as e:
                self._log(f"    Failed {rel_src}: {e.output}", "error")

    def run(self):
        try:
            self._run()
        except PipelineError as e:
            self._done(False, e.message)
        except Exception as e:
            self._done(False, f"Unexpected error: {e}")

    def _run(self):
        game_info = GAME_DB[self.game_key]
        passphrase = game_info["passphrase"]
        game_key = self.game_key
        gpg_bin = self._resolve_gpg()
        self._log(f"Using gpg: {gpg_bin}", "info")

        fun_wsl = self.executor.to_exec_path(self.original_fun)
        out_fun_wsl = self.executor.to_exec_path(self.output_fun_path)
        tmp_tar_wsl = f"/tmp/bof_{game_key}_mod.tar.gz"
        tmp_dir_wsl = f"/tmp/bof_{game_key}_repack"

        # Phase 0 — Decrypt original .fun → tar.gz → extract to temp dir
        self._set_phase(0)
        self._log(f"Decrypting original {os.path.basename(self.original_fun)}...",
                  "info")
        self._progress(0, 100, "Decrypting original...")

        fun_size = os.path.getsize(self.original_fun)
        try:
            with self._poll_file_progress(tmp_tar_wsl, fun_size, "Decrypting..."):
                self.executor.run(
                    f"{gpg_bin} --batch --yes --passphrase={passphrase!r} "
                    f"--decrypt --output {tmp_tar_wsl!r} {fun_wsl!r} 2>&1",
                    timeout=GPG_DECRYPT_TIMEOUT,
                )
        except CommandError as e:
            raise PipelineError("Decrypt",
                f"GPG decryption failed:\n{e.output}\n\n"
                f"Check that the original .fun file is valid.")
        self._log("Original decrypted.", "success")

        # Extract tar to temp dir (preserves original structure)
        self._progress(0, 100, "Extracting original...")
        try:
            self.executor.run(
                f"rm -rf {tmp_dir_wsl!r} && mkdir -p {tmp_dir_wsl!r} && "
                f"tar -xzf {tmp_tar_wsl!r} -C {tmp_dir_wsl!r} 2>&1",
                timeout=TAR_EXTRACT_TIMEOUT,
            )
        except CommandError as e:
            raise PipelineError("Decrypt",
                f"tar extract failed:\n{e.output}")
        self._log("Original extracted to temp dir.", "success")
        self._check_cancel()

        # Phase 1 — Patch: find changed PCK files and patch the binary
        self._set_phase(1)

        pck_dir = os.path.join(self.assets_dir, "pck")
        has_pck = os.path.isdir(pck_dir)

        # Find the Godot binary in the temp extract
        binary_wsl = ""
        try:
            binary_wsl = self.executor.run(
                f"find {tmp_dir_wsl!r} -name '*.x86_64' -type f | head -1",
                timeout=15,
            ).strip()
        except Exception:
            pass
        if not binary_wsl:
            raise PipelineError("Patch",
                "No Godot binary (.x86_64) found in the extracted archive.")

        self._log(f"Binary: {os.path.basename(binary_wsl)}", "info")

        # Detect changed PCK files by mtime
        changed_pck = []
        if has_pck:
            export_log = os.path.join(pck_dir, "gdre_export.log")
            baseline_mtime = (os.path.getmtime(export_log)
                              if os.path.isfile(export_log) else 0)

            _skip_names = {"gdre_export.log", ".DS_Store", "Thumbs.db", "desktop.ini"}
            for root, _dirs, files in os.walk(pck_dir):
                if ".autoconverted" in root:
                    continue
                for fname in files:
                    if fname in _skip_names:
                        continue
                    abs_path = os.path.join(root, fname)
                    if os.path.getmtime(abs_path) > baseline_mtime:
                        rel = os.path.relpath(abs_path, pck_dir).replace("\\", "/")
                        changed_pck.append(rel)

        if changed_pck:
            self._log(f"Found {len(changed_pck)} modified source file(s):", "info")
            for f in changed_pck[:20]:
                self._log(f"  {f}", "info")
            if len(changed_pck) > 20:
                self._log(f"  ... and {len(changed_pck) - 20} more", "info")

            # Reimport: for files with .import sidecars, regenerate the
            # imported version (.sample, .oggvorbisstr, .ctex) so Godot
            # picks up the change at runtime.
            pck_dir_wsl = self.executor.to_exec_path(pck_dir)
            self._log("Reimporting assets for Godot...", "info")
            self._progress(0, 0, "Reimporting assets...")
            extra = self._reimport_assets(changed_pck, pck_dir, pck_dir_wsl)
            if extra:
                self._log(f"Reimported {len(extra)} imported asset(s)", "success")
                changed_pck.extend(extra)

            self._log(f"Patching {len(changed_pck)} file(s) into binary...", "info")
            self._progress(0, 100, "Patching PCK...")

            pck_dir_wsl = self.executor.to_exec_path(pck_dir)
            tmp_binary_wsl = f"/tmp/bof_{game_key}_patched.x86_64"
            gdre_prefix = self._gdre_prefix()

            # Write patch args to a temp script to avoid quoting / arg-length limits
            import base64 as _b64
            patch_script = f"/tmp/bof_{game_key}_patch.sh"
            script_lines = [
                "#!/bin/bash",
                "set -e",
                f'{gdre_prefix} \\',
                f"  --pck-patch={binary_wsl!r} \\",
                f"  --output={tmp_binary_wsl!r} \\",
                f"  --embed={binary_wsl!r} \\",
            ]
            for i, rel in enumerate(changed_pck):
                local_path = f"{pck_dir_wsl}/{rel}"
                cont = " \\" if i < len(changed_pck) - 1 else ""
                script_lines.append(
                    f"  --patch-file='{local_path}=res://{rel}'{cont}"
                )
            script_b64 = _b64.b64encode(
                ("\n".join(script_lines) + "\n").encode()
            ).decode()

            self.executor.run(
                f"echo {script_b64!r} | base64 -d > {patch_script} && "
                f"chmod +x {patch_script}",
                timeout=30,
            )

            try:
                for chunk in self.executor.stream(
                    f"bash {patch_script} 2>&1", timeout=GDRE_TIMEOUT
                ):
                    for part in chunk.split("\r"):
                        part = part.strip()
                        if not part:
                            continue
                        pct_match = re.search(r'(\d+)%', part)
                        if pct_match:
                            pct = int(pct_match.group(1))
                            self._progress(pct, 100, f"Patching... {pct}%")
                        elif part:
                            self._log(f"  {part}", "info")
            except CommandError as e:
                raise PipelineError("Patch",
                    f"GDRE patch failed:\n{e.output}\n\n"
                    f"Make sure GDRE Tools is installed and the changed files "
                    f"are valid Godot assets.")

            # Replace binary in the temp extract with the patched one
            try:
                self.executor.run(
                    f"mv -f {tmp_binary_wsl!r} {binary_wsl!r} && "
                    f"chmod +x {binary_wsl!r}",
                    timeout=600,
                )
            except CommandError as e:
                raise PipelineError("Patch",
                    f"Failed to replace binary:\n{e.output}")

            # Update the md5 checksum file to match the patched binary
            binary_basename = os.path.basename(binary_wsl)
            try:
                self.executor.run(
                    f"cd {tmp_dir_wsl!r} && "
                    f"md5sum {binary_basename!r} > md5",
                    timeout=120,
                )
                self._log("Updated md5 checksum.", "info")
            except CommandError:
                self._log("Warning: could not update md5 file.", "error")

            self._log("Binary patched.", "success")
        else:
            self._log("No modified PCK files — using original binary.", "info")
        self._check_cancel()

        # Phase 2 — Repack: re-tar the temp dir (same structure as original)
        self._set_phase(2)
        self._log("Repacking archive...", "info")
        self._progress(0, 100, "Creating tar.gz...")

        repack_tar_wsl = f"/tmp/bof_{game_key}_repack.tar.gz"
        try:
            # Use * glob (not .) to avoid ./ prefix and ./ directory entry,
            # matching the original tar structure exactly.
            self.executor.run(
                f"cd {tmp_dir_wsl!r} && "
                f"tar -czf {repack_tar_wsl!r} * 2>&1",
                timeout=TAR_PACK_TIMEOUT,
            )
        except CommandError as e:
            raise PipelineError("Repack", f"tar repack failed:\n{e.output}")

        # Get tar size for encrypt progress
        tar_bytes = 0
        try:
            out = self.executor.run(
                f"stat -f%z {repack_tar_wsl!r} 2>/dev/null || "
                f"stat -c%s {repack_tar_wsl!r} 2>/dev/null || echo 0",
                timeout=10,
            ).strip()
            tar_bytes = int(out)
            size_h = self.executor.run(
                f"du -h {repack_tar_wsl!r} | cut -f1", timeout=10
            ).strip()
            self._log(f"Archive created ({size_h}).", "success")
        except Exception:
            self._log("Archive created.", "success")
        self._check_cancel()

        # Phase 3 — Encrypt: GPG encrypt → output .fun
        self._set_phase(3)
        self._log(f"Encrypting to {os.path.basename(self.output_fun_path)}...", "info")
        self._progress(0, 100, "GPG encrypting...")

        os.makedirs(os.path.dirname(self.output_fun_path) or ".", exist_ok=True)
        try:
            with self._poll_file_progress(
                out_fun_wsl, tar_bytes, "Encrypting..."
            ) if tar_bytes else _nullctx():
                self.executor.run(
                    f"{gpg_bin} --batch --yes --passphrase={passphrase!r} "
                    f"--symmetric --cipher-algo AES256 "
                    f"--output {out_fun_wsl!r} {repack_tar_wsl!r} 2>&1",
                    timeout=GPG_ENCRYPT_TIMEOUT,
                )
        except CommandError as e:
            raise PipelineError("Encrypt", f"GPG encryption failed:\n{e.output}")
        self._log("GPG encryption complete.", "success")
        self._check_cancel()

        # Phase 4 — Cleanup
        self._set_phase(4)
        try:
            self.executor.run(
                f"rm -rf {tmp_tar_wsl!r} {tmp_dir_wsl!r} {repack_tar_wsl!r} "
                f"/tmp/bof_{game_key}_patch.sh /tmp/bof_convert.gd "
                f"/tmp/bof_tex.webp 2>/dev/null; true",
                timeout=30,
            )
        except Exception:
            pass
        self._log("Cleanup complete.", "success")

        self._done(True,
            f"{game_info['display']} re-packed successfully.\n\n"
            f"Output: {self.output_fun_path}\n\n"
            f"Copy this .fun file to a USB drive (FAT32) and insert it "
            f"into the machine to install the update.")
