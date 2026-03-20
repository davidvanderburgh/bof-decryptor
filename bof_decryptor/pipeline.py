"""Decrypt and modify pipelines for BOF Asset Decryptor."""

import hashlib
import os
import re
import shutil
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

    def run(self):
        raise NotImplementedError


def check_prerequisites(executor):
    """Check that gpg is available in the executor environment.

    Returns a list of (name, passed, message) tuples.
    """
    results = []

    # Executor availability (WSL2 on Windows)
    ok, msg = executor.check_available()
    results.append(("WSL2" if hasattr(executor, "to_exec_path") and
                    "wsl" in type(executor).__name__.lower() else "System",
                    ok, msg))

    if not ok:
        return results

    # gpg
    try:
        out = executor.run("gpg --version 2>&1 | head -1", timeout=10).strip()
        results.append(("gpg", True, out or "available"))
    except Exception:
        results.append(("gpg", False, "Not found — install with: apt-get install gnupg"))

    # tar
    try:
        executor.run("tar --version 2>&1 | head -1", timeout=10)
        results.append(("tar", True, "available"))
    except Exception:
        results.append(("tar", False, "Not found — install with: apt-get install tar"))

    # gdre_tools (optional — for Godot PCK extraction)
    try:
        path = executor.run(
            "which gdre_tools 2>/dev/null || echo MISSING", timeout=10
        ).strip()
        if "MISSING" in path or not path:
            results.append(("gdre_tools", False,
                            "Optional — click Install Missing to download automatically"))
        else:
            results.append(("gdre_tools", True, path.strip()))
    except Exception:
        results.append(("gdre_tools", False,
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

        # Phase 1 — Decrypt
        self._set_phase(1)
        self._log(f"Decrypting {os.path.basename(self.fun_path)} with GPG...", "info")
        self._progress(0, 0, "GPG decrypting...")

        tmp_tar_wsl = f"/tmp/bof_{game_key}.tar.gz"
        try:
            self.executor.run(
                f"gpg --batch --yes --passphrase={passphrase!r} "
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
        self._progress(0, 0, "Extracting tar.gz...")

        tmp_extract_wsl = f"/tmp/bof_{game_key}_extracted"
        try:
            self.executor.run(
                f"rm -rf {tmp_extract_wsl!r} && "
                f"mkdir -p {tmp_extract_wsl!r} && "
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
                gdre_prefix = (
                    "DISPLAY= WAYLAND_DISPLAY= "
                    "GODOT_SILENCE_ROOT_WARNING=1 "
                    "LD_LIBRARY_PATH=/opt/gdre_tools "
                    "xvfb-run -a /opt/gdre_tools/gdre_tools.x86_64 --headless "
                )

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
    """Re-pack a modified Godot binary back into a .fun file."""

    def __init__(self, assets_dir, output_fun_path, game_key, executor,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.assets_dir = assets_dir
        self.output_fun_path = output_fun_path
        self.game_key = game_key
        self.executor = executor

    def run(self):
        try:
            self._run()
        except PipelineError as e:
            self._done(False, e.message)
        except Exception as e:
            self._done(False, f"Unexpected error: {e}")

    def _run(self):
        game_info = GAME_DB[self.game_key]

        # Phase 0 — Scan for changes
        self._set_phase(0)
        self._log("Scanning for modified files...", "info")

        checksums_file = os.path.join(self.assets_dir, CHECKSUMS_FILE)
        if not os.path.isfile(checksums_file):
            raise PipelineError("Scan",
                f"No {CHECKSUMS_FILE} found.\n"
                f"Decrypt the game first to generate baseline checksums.")

        baseline = {}
        with open(checksums_file, "r") as f:
            for line in f:
                line = line.strip()
                if "\t" in line:
                    path, md5 = line.rsplit("\t", 1)
                    baseline[path] = md5

        changed = []
        for rel_path, orig_md5 in baseline.items():
            abs_path = os.path.join(self.assets_dir, rel_path)
            if not os.path.isfile(abs_path):
                continue
            if _md5_file(abs_path) != orig_md5:
                changed.append(rel_path)

        if not changed:
            raise PipelineError("Scan",
                "No modified files detected.\n"
                "Modify the Godot binary or other files first.")

        self._log(f"Found {len(changed)} modified file(s):", "info")
        for f in changed:
            self._log(f"  {f}", "info")
        self._check_cancel()

        assets_wsl = self.executor.to_exec_path(self.assets_dir)
        out_fun_wsl = self.executor.to_exec_path(self.output_fun_path)
        passphrase = game_info["passphrase"]
        game_key = self.game_key

        # Phase 1 — Pack tar.gz
        self._set_phase(1)
        self._log("Packing archive...", "info")
        self._progress(0, 0, "Creating tar.gz...")

        tmp_tar_wsl = f"/tmp/bof_{game_key}_mod.tar.gz"
        try:
            self.executor.run(
                f"cd {assets_wsl!r} && "
                f"tar -czf {tmp_tar_wsl!r} "
                f"--exclude='.checksums.md5' "
                f"--exclude='*.tar.gz' "
                f"--exclude='*.fun' "
                f". 2>&1",
                timeout=TAR_PACK_TIMEOUT,
            )
        except CommandError as e:
            raise PipelineError("Pack", f"tar failed:\n{e.output}")

        size_out = ""
        try:
            size_out = self.executor.run(
                f"du -h {tmp_tar_wsl!r} | cut -f1", timeout=10
            ).strip()
        except Exception:
            pass
        self._log(f"Archive created{f' ({size_out})' if size_out else ''}.", "success")
        self._check_cancel()

        # Phase 2 — GPG encrypt
        self._set_phase(2)
        self._log(f"Encrypting to {os.path.basename(self.output_fun_path)}...", "info")
        self._progress(0, 0, "GPG encrypting...")

        os.makedirs(os.path.dirname(self.output_fun_path) or ".", exist_ok=True)
        try:
            self.executor.run(
                f"gpg --batch --yes --passphrase={passphrase!r} "
                f"--symmetric --cipher-algo AES256 "
                f"--output {out_fun_wsl!r} {tmp_tar_wsl!r} 2>&1",
                timeout=GPG_ENCRYPT_TIMEOUT,
            )
        except CommandError as e:
            raise PipelineError("Encrypt", f"GPG encryption failed:\n{e.output}")
        self._log("GPG encryption complete.", "success")
        self._check_cancel()

        # Phase 3 — Cleanup
        self._set_phase(3)
        try:
            self.executor.run(
                f"rm -f {tmp_tar_wsl!r} 2>/dev/null; true", timeout=15
            )
        except Exception:
            pass
        self._log("Cleanup complete.", "success")

        self._done(True,
            f"{game_info['display']} re-packed successfully.\n\n"
            f"Output: {self.output_fun_path}\n\n"
            f"Copy this .fun file to a USB drive (FAT32) and insert it "
            f"into the machine to install the update.")
