"""Best-effort feature completion receipts and host desktop delivery (stdlib only)."""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Mapping, Sequence
import uuid

logger = logging.getLogger(__name__)
DESKTOP_KEYS = ("PATH", "HOME", "DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR")
MAX_PAYLOAD_BYTES = 64 * 1024
_STATE_MODE = 0o600
_CACHE_MODE = 0o700
_UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _warn(message: str) -> None:
    """Log one concise operational warning without untrusted data."""
    logger.warning("worker notification: %s", message)


def _regular(path: Path, mode: int | None = None) -> bool:
    """Return whether ``path`` is a non-symlink regular file of an optional mode."""
    try:
        value = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(value.st_mode) and not path.is_symlink() and (mode is None or stat.S_IMODE(value.st_mode) == mode)
    )


def _cache(path: Path) -> Path | None:
    """Validate an existing cache directory allocated with a canonical UUID4 name."""
    try:
        value = path.lstat()
        resolved = path.resolve(strict=True)
        parsed = uuid.UUID(path.name)
    except (OSError, ValueError):
        return None
    if path.is_symlink() or not stat.S_ISDIR(value.st_mode) or stat.S_IMODE(value.st_mode) != _CACHE_MODE:
        return None
    return resolved if _UUID4.fullmatch(path.name) and parsed.version == 4 and str(parsed) == path.name else None


def _read(path: Path, mode: int | None = _STATE_MODE) -> object | None:
    """Read a bounded JSON document without following a symlink."""
    if not _regular(path, mode):
        return None
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_PAYLOAD_BYTES + 1)
        if len(raw) > MAX_PAYLOAD_BYTES:
            return None
        return json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _write(path: Path, document: Mapping[str, object]) -> bool:
    """Atomically replace a JSON state file with mode 0600."""
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        os.fchmod(descriptor, _STATE_MODE)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        return True
    except OSError:
        return False
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _root(worktree: Path) -> Path | None:
    """Return ``worktree`` only when it is exactly the current Git top-level."""
    try:
        root = worktree.resolve(strict=True)
        git = shutil.which("git", path=os.defpath)
        if git is None:
            return None
        result = subprocess.run(
            [git, "rev-parse", "--show-toplevel"], cwd=root, capture_output=True, text=True, timeout=2
        )
        candidate = Path(result.stdout.strip()).resolve(strict=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return root if result.returncode == 0 and candidate == root else None


def _head(worktree: Path) -> str | None:
    """Return the validated current Git HEAD hash."""
    try:
        git = shutil.which("git", path=os.defpath)
        if git is None:
            return None
        result = subprocess.run([git, "rev-parse", "HEAD"], cwd=worktree, capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    head = result.stdout.strip()
    return head if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", head) else None


def _index(worktree: Path, slug: str) -> tuple[Path, str] | None:
    """Resolve the only permitted index path without allowing worktree escape."""
    relative = Path("sdd") / "tasks" / "index" / f"{slug}.json"
    candidate = worktree / relative
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(worktree)
    except (OSError, ValueError):
        return None
    return (resolved, relative.as_posix()) if not candidate.is_symlink() and _regular(candidate) else None


def _context(cache: Path) -> dict[str, object] | None:
    """Load a strict version-1 context and validate its worktree and index identity."""
    document = _read(cache / "notify-context.json")
    required = {"schema_version", "launch_id", "feature_id", "slug", "worktree", "index", "desktop_env"}
    if not isinstance(document, dict) or set(document) != required or type(document.get("schema_version")) is not int:
        return None
    if document["schema_version"] != 1 or any(
        not isinstance(document.get(key), str) or not document[key]
        for key in required - {"schema_version", "desktop_env"}
    ):
        return None
    desktop = document["desktop_env"]
    if document["launch_id"] != cache.name or not isinstance(desktop, dict):
        return None
    if any(key not in DESKTOP_KEYS or not isinstance(value, str) for key, value in desktop.items()):
        return None
    worktree = _root(Path(document["worktree"]))
    expected = _index(worktree, document["slug"]) if worktree else None
    if (
        worktree is None
        or str(worktree) != document["worktree"]
        or expected is None
        or document["index"] != expected[1]
    ):
        return None
    data = _read(expected[0], None)
    return document if isinstance(data, dict) and data.get("feature_id") == document["feature_id"] else None


def configure_notification(cache: Path, *, worktree: Path, env: Mapping[str, str]) -> str | None:
    """Write validated launch context and return a quoted Stop command."""
    cache = _cache(cache)
    feature_id, slug, desktop_raw = (
        env.get("PARROT_SDD_NOTIFY_FEATURE"),
        env.get("PARROT_SDD_NOTIFY_SLUG"),
        env.get("PARROT_SDD_NOTIFY_DESKTOP"),
    )
    if cache is None or not isinstance(feature_id, str) or not feature_id or not isinstance(slug, str) or not slug:
        _warn("invalid launch state")
        return None
    try:
        desktop = json.loads(desktop_raw) if isinstance(desktop_raw, str) else None
    except json.JSONDecodeError:
        desktop = None
    root = _root(worktree)
    index = _index(root, slug) if root else None
    data = _read(index[0], None) if index else None
    if (
        not isinstance(desktop, dict)
        or any(key not in DESKTOP_KEYS or not isinstance(value, str) for key, value in desktop.items())
        or index is None
        or not isinstance(data, dict)
        or data.get("feature_id") != feature_id
    ):
        _warn("invalid notification metadata")
        return None
    context: dict[str, object] = {
        "schema_version": 1,
        "launch_id": cache.name,
        "feature_id": feature_id,
        "slug": slug,
        "worktree": str(root),
        "index": index[1],
        "desktop_env": desktop,
    }
    if not _write(cache / "notify-context.json", context):
        _warn("could not save launch context")
        return None
    return shlex.join(
        [str(Path(sys.executable).resolve()), "-S", str(Path(__file__).resolve()), "--hook", "--cache", str(cache)]
    )


def record_completion(env: Mapping[str, str]) -> bool:
    """Atomically record eligible feature completion in the existing session cache."""
    value = env.get("PARROT_SDD_CACHE_DIR")
    cache = _cache(Path(value)) if isinstance(value, str) else None
    context = _context(cache) if cache else None
    if cache is None or context is None:
        _warn("invalid completion state")
        return False
    worktree = Path(context["worktree"])
    index = _index(worktree, str(context["slug"]))
    data = _read(index[0], None) if index else None
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if (
        not isinstance(tasks, list)
        or not tasks
        or any(not isinstance(task, dict) or task.get("status") != "done" for task in tasks)
    ):
        _warn("feature tasks are incomplete")
        return False
    head = _head(worktree)
    if head is None:
        _warn("could not read Git head")
        return False
    receipt: dict[str, object] = {
        "schema_version": 1,
        "launch_id": context["launch_id"],
        "feature_id": context["feature_id"],
        "worktree": context["worktree"],
        "head": head,
    }
    if not _write(cache / "notify-complete.json", receipt):
        _warn("could not save completion receipt")
        return False
    return True


def _receipt(cache: Path, context: Mapping[str, object]) -> bool:
    """Return whether a strict receipt matches context and the current Git HEAD."""
    document = _read(cache / "notify-complete.json")
    required = {"schema_version", "launch_id", "feature_id", "worktree", "head"}
    if (
        not isinstance(document, dict)
        or set(document) != required
        or type(document.get("schema_version")) is not int
        or document["schema_version"] != 1
    ):
        return False
    if any(not isinstance(document.get(key), str) or not document[key] for key in required - {"schema_version"}):
        return False
    if any(document[key] != context[key] for key in ("launch_id", "feature_id", "worktree")):
        return False
    root = _root(Path(document["worktree"]))
    return root is not None and _head(root) == document["head"]


def _claim_attempt(cache: Path) -> bool:
    """Exclusively create the persistent delivery-attempt marker before sending."""
    try:
        descriptor = os.open(cache / "notify-attempted", os.O_WRONLY | os.O_CREAT | os.O_EXCL, _STATE_MODE)
    except OSError:
        return False
    os.close(descriptor)
    return True


def handle_stop(payload: Mapping[str, object], *, cache: Path) -> None:
    """Attempt one notification for a valid Stop and receipt without propagating errors."""
    try:
        if payload.get("hook_event_name") != "Stop" or payload.get("background_tasks") or payload.get("session_crons"):
            return
        cache = _cache(cache)
        context = _context(cache) if cache else None
        if cache is None or context is None or not _receipt(cache, context) or not _claim_attempt(cache):
            return
        desktop = context["desktop_env"]
        assert isinstance(desktop, dict)
        notify_send = shutil.which("notify-send", path=desktop.get("PATH", os.defpath))
        if not notify_send:
            return
        title = f"SDD work completed: {context['feature_id']}"
        body = (
            f"{html.escape(str(context['slug']))}\n{html.escape(str(context['worktree']))}\nClaude Code remains open."
        )
        subprocess.run(
            [notify_send, "--urgency=normal", "--app-name=AI-Parrot SDD", title, body],
            env=desktop,
            shell=False,
            timeout=3,
            check=False,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        _warn("delivery failed")


class _QuietArgumentParser(argparse.ArgumentParser):
    """Argparse parser that leaves malformed hook invocation output empty."""

    def error(self, message: str) -> None:
        """Convert parser errors into the helper's concise warning path."""
        raise ValueError(message)


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch internal modes, returning zero for operational failures."""
    parser = _QuietArgumentParser(add_help=False)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--complete", action="store_true")
    modes.add_argument("--hook", action="store_true")
    parser.add_argument("--cache")
    try:
        arguments = parser.parse_args(argv)
        if arguments.complete:
            if arguments.cache is not None:
                raise ValueError
            record_completion(os.environ)
        elif arguments.cache is not None:
            raw = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1)
            payload = json.loads(raw.decode("utf-8")) if len(raw) <= MAX_PAYLOAD_BYTES else None
            if not isinstance(payload, dict):
                raise ValueError
            handle_stop(payload, cache=Path(arguments.cache))
        else:
            raise ValueError
    except (SystemExit, OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        _warn("invalid helper input")
    except Exception:
        _warn("helper operation failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
