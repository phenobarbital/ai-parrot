from typing import Any, Dict, List, Optional
import time
import shutil
from pathlib import Path
import shlex
from .models import BaseAction, ActionResult

# ---------- Concrete actions ----------

class RunCommand(BaseAction):
    """Run a shell command via /bin/sh -lc 'command'."""
    async def _run_impl(self) -> ActionResult:
        # Allow complex commands (with pipes, redirects) by invoking through /bin/sh -lc
        argv = ["/bin/sh", "-lc", self.cmd]
        return await self._run_subprocess(argv)

class ExecFile(BaseAction):
    """Execute a file/script via /bin/sh {file_or_cmd}."""
    async def _run_impl(self) -> ActionResult:
        # Execute a file/script via /bin/sh {file_or_cmd}
        argv = ["/bin/sh", self.cmd]
        return await self._run_subprocess(argv)

class ListFiles(BaseAction):
    """List files in a directory, optionally with flags/args."""
    async def _run_impl(self) -> ActionResult:
        # Simple 'ls' wrapper that accepts the rest of the command flags/args
        parts = shlex.split(self.cmd) if self.cmd else []
        if not parts:
            parts = ["ls", "-la"]
        elif parts[0] != "ls":
            parts = ["ls"] + parts
        argv = parts
        return await self._run_subprocess(argv)

class CheckExists(BaseAction):
    """Check if a file/directory exists."""
    async def _run_impl(self) -> ActionResult:
        started = time.time()
        target = self.cmd.strip() or "."
        p = Path(self.work_dir) / target
        exists = p.exists()
        ended = time.time()
        msg = f"EXISTS: {exists}  PATH: {str(p)}"
        return ActionResult(
            ok=True,
            exit_code=0 if exists else 1,
            stdout=msg + "\n",
            stderr="",
            started_at=started,
            ended_at=ended,
            duration=ended-started,
            cmd=f"check_exists {target}",
            work_dir=self.work_dir,
            metadata={"exists": exists, "path": str(p)},
            type="check_exists"
        )

class ReadFile(BaseAction):
    """Read a file's content, with optional max bytes and encoding."""
    async def _run_impl(self) -> ActionResult:
        started = time.time()
        parts = shlex.split(self.cmd) if self.cmd else []
        target = parts[0] if parts else ""
        p = Path(self.work_dir) / target
        stdout = ""
        stderr = ""
        ok = False
        exit_code = 1
        meta: Dict[str, Any] = {}
        try:
            data = p.read_bytes()
            meta["size"] = len(data)
            max_bytes = None
            if len(parts) > 1:
                # allow "read_file <path> --max N --encoding utf-8"
                # but also support injected settings via metadata; primary path below
                pass
            # Prefer explicit metadata carried on BaseAction via .metadata? keep simple:
            # We'll parse from self.cmd like: "file.txt"
            max_bytes = self.metadata.get("max_bytes") if hasattr(self, "metadata") else None  # not set in v1
            # Instead, ReadFile Action will be constructed with self.cmd=path, and we pass options via subclass creation
            # To keep v1 simple: rely on wrapper to limit bytes
            # (we'll set these on the instance attributes for now)
        except Exception as e:
            stderr = f"{type(e).__name__}: {e}\n"
        else:
            # attributes set by wrapper
            try:
                max_b = getattr(self, "_max_bytes", None)
                enc = getattr(self, "_encoding", "utf-8")
                if max_b is not None:
                    data = data[:int(max_b)]
                    meta["truncated_to"] = int(max_b)
                try:
                    stdout = data.decode(enc, errors="replace")
                except Exception:
                    # If decoding fails, return as raw bytes repr
                    stdout = data.decode("utf-8", errors="replace")
                    meta["encoding_used"] = "utf-8 (fallback)"
                else:
                    meta["encoding_used"] = enc
                ok = True
                exit_code = 0
            except Exception as e:
                stderr = f"{type(e).__name__}: {e}\n"

        ended = time.time()
        return ActionResult(
            ok=ok or self.ignore_errors,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            started_at=started,
            ended_at=ended,
            duration=ended-started,
            cmd=f"read_file {target}",
            work_dir=self.work_dir,
            metadata=meta,
            type="read_file"
        )

# Note: other actions can be added here, e.g., WriteFile, MoveFile, etc.
class WriteFile(BaseAction):
    """
    Writes text content to a file relative to work_dir.
    Options:
      - append: append instead of overwrite
      - make_dirs: create parent dirs
      - encoding: text encoding
    """
    def __init__(
        self,
        *,
        path: str,
        content: str,
        encoding: str = "utf-8",
        append: bool = False,
        make_dirs: bool = True,
        overwrite: bool = True,
        work_dir: Optional[str] = None,
        ignore_errors: Optional[bool] = None,
    ):
        super().__init__(type_name="write_file", work_dir=work_dir, ignore_errors=ignore_errors)
        self._path = path
        self._content = content or ""
        self._encoding = encoding or "utf-8"
        self._append = bool(append)
        self._make_dirs = bool(make_dirs)
        self._overwrite = bool(overwrite)

    async def _run_impl(self) -> ActionResult:
        started = time.time()
        target = (Path(self.work_dir) / self._path).resolve()
        ok = False
        err = ""
        meta: Dict[str, Any] = {"path": str(target)}
        try:
            parent = target.parent
            if self._make_dirs:
                parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and (not self._append) and (not self._overwrite):
                raise FileExistsError(f"Refusing to overwrite existing file: {target}")

            mode = "a" if self._append else "w"
            with open(target, mode, encoding=self._encoding, newline="") as f:
                f.write(self._content)
            ok = True
            meta["bytes_written"] = len(self._content.encode(self._encoding, errors="replace"))
            meta["encoding_used"] = self._encoding
            meta["append"] = self._append
        except Exception as e:
            err = f"{type(e).__name__}: {e}"

        ended = time.time()
        return ActionResult(
            ok=ok or self.ignore_errors,
            exit_code=0 if ok else 1,
            stdout=str(target) + ("\n" if ok else ""),
            stderr=(err + "\n") if err else "",
            started_at=started,
            ended_at=ended,
            duration=ended - started,
            cmd=f"write_file {self._path}",
            work_dir=self.work_dir,
            metadata=meta,
            type="write_file"
        )


class DeleteFile(BaseAction):
    """
    Deletes a file or directory (with optional recursion).
    Options:
      - recursive: remove directories recursively
      - missing_ok: do not error if path does not exist
    """
    def __init__(
        self,
        *,
        path: str,
        recursive: bool = False,
        missing_ok: bool = True,
        work_dir: Optional[str] = None,
        ignore_errors: Optional[bool] = None,
    ):
        super().__init__(type_name="delete_file", work_dir=work_dir, ignore_errors=ignore_errors)
        self._path = path
        self._recursive = bool(recursive)
        self._missing_ok = bool(missing_ok)

    async def _run_impl(self) -> ActionResult:
        started = time.time()
        target = (Path(self.work_dir) / self._path).resolve()
        ok = False
        err = ""
        meta: Dict[str, Any] = {"path": str(target), "recursive": self._recursive}
        try:
            if not target.exists():
                if self._missing_ok:
                    ok = True
                else:
                    raise FileNotFoundError(f"No such file or directory: {target}")
            else:
                if target.is_dir():
                    if self._recursive:
                        shutil.rmtree(target)
                        ok = True
                    else:
                        # try rmdir (only empty dir)
                        target.rmdir()
                        ok = True
                else:
                    target.unlink()
                    ok = True
        except Exception as e:
            err = f"{type(e).__name__}: {e}"

        ended = time.time()
        return ActionResult(
            ok=ok or self.ignore_errors,
            exit_code=0 if ok else 1,
            stdout=str(target) + ("\n" if ok else ""),
            stderr=(err + "\n") if err else "",
            started_at=started,
            ended_at=ended,
            duration=ended - started,
            cmd=f"delete_file {self._path}",
            work_dir=self.work_dir,
            metadata=meta,
            type="delete_file"
        )

class CopyFile(BaseAction):
    """
    Copy a file or directory.
    - If source is a directory, set recursive=True to copy its tree.
    - overwrite=True will replace an existing destination.
    - make_dirs=True will create the destination parent directory.
    """
    def __init__(
        self,
        *,
        src: str,
        dest: str,
        recursive: bool = False,
        overwrite: bool = True,
        make_dirs: bool = True,
        work_dir: Optional[str] = None,
        ignore_errors: Optional[bool] = None,
    ):
        super().__init__(type_name="copy_file", work_dir=work_dir, ignore_errors=ignore_errors)
        self._src = src
        self._dest = dest
        self._recursive = bool(recursive)
        self._overwrite = bool(overwrite)
        self._make_dirs = bool(make_dirs)

    async def _run_impl(self) -> ActionResult:
        started = time.time()
        src_p = (Path(self.work_dir) / self._src).resolve()
        dest_p = (Path(self.work_dir) / self._dest).resolve()
        ok = False
        err = ""
        meta = {
            "src": str(src_p),
            "dest": str(dest_p),
            "recursive": self._recursive,
            "overwrite": self._overwrite,
        }
        try:
            if not src_p.exists():
                raise FileNotFoundError(f"Source not found: {src_p}")

            if self._make_dirs:
                dest_p.parent.mkdir(parents=True, exist_ok=True)

            if dest_p.exists():
                if not self._overwrite:
                    raise FileExistsError(f"Destination exists (overwrite=False): {dest_p}")
                # Remove existing dest to mimic replace
                if dest_p.is_dir() and not src_p.is_dir():
                    shutil.rmtree(dest_p)
                elif dest_p.is_file():
                    dest_p.unlink()

            if src_p.is_dir():
                if not self._recursive:
                    raise IsADirectoryError(f"Source is directory; set recursive=True to copy: {src_p}")
                # shutil.copytree requires dest not exist (we removed above if overwrite)
                shutil.copytree(src_p, dest_p)
            else:
                # copy2 preserves metadata
                shutil.copy2(src_p, dest_p)

            ok = True
        except Exception as e:
            err = f"{type(e).__name__}: {e}"

        ended = time.time()
        return ActionResult(
            ok=ok or self.ignore_errors,
            exit_code=0 if ok else 1,
            stdout=(str(dest_p) + "\n") if ok else "",
            stderr=(err + "\n") if err else "",
            started_at=started,
            ended_at=ended,
            duration=ended - started,
            cmd=f"copy_file {self._src} -> {self._dest}",
            work_dir=self.work_dir,
            metadata=meta,
            type="copy_file"
        )


class MoveFile(BaseAction):
    """
    Move/rename a file or directory.
    - recursive flag is accepted for parity (moving dirs is allowed by default).
    - overwrite=True will replace an existing destination.
    - make_dirs=True will create the destination parent directory.
    """
    def __init__(
        self,
        *,
        src: str,
        dest: str,
        recursive: bool = True,
        overwrite: bool = True,
        make_dirs: bool = True,
        work_dir: Optional[str] = None,
        ignore_errors: Optional[bool] = None,
    ):
        super().__init__(type_name="move_file", work_dir=work_dir, ignore_errors=ignore_errors)
        self._src = src
        self._dest = dest
        self._recursive = bool(recursive)
        self._overwrite = bool(overwrite)
        self._make_dirs = bool(make_dirs)

    async def _run_impl(self) -> ActionResult:
        started = time.time()
        src_p = (Path(self.work_dir) / self._src).resolve()
        dest_p = (Path(self.work_dir) / self._dest).resolve()
        ok = False
        err = ""
        meta = {
            "src": str(src_p),
            "dest": str(dest_p),
            "recursive": self._recursive,
            "overwrite": self._overwrite,
        }
        try:
            if not src_p.exists():
                raise FileNotFoundError(f"Source not found: {src_p}")

            if self._make_dirs:
                dest_p.parent.mkdir(parents=True, exist_ok=True)

            if dest_p.exists():
                if not self._overwrite:
                    raise FileExistsError(f"Destination exists (overwrite=False): {dest_p}")
                # Remove destination before move (ensures replace semantics)
                if dest_p.is_dir():
                    shutil.rmtree(dest_p)
                else:
                    dest_p.unlink()

            # shutil.move handles both files and directories
            shutil.move(str(src_p), str(dest_p))
            ok = True
        except Exception as e:
            err = f"{type(e).__name__}: {e}"

        ended = time.time()
        return ActionResult(
            ok=ok or self.ignore_errors,
            exit_code=0 if ok else 1,
            stdout=(str(dest_p) + "\n") if ok else "",
            stderr=(err + "\n") if err else "",
            started_at=started,
            ended_at=ended,
            duration=ended - started,
            cmd=f"move_file {self._src} -> {self._dest}",
            work_dir=self.work_dir,
            metadata=meta,
            type="move_file"
        )
