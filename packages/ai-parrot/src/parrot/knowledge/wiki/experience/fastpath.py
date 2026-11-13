"""Bounded, standard-library-only helpers for the experience hook fast path."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import shlex
import stat
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

EXPERIENCE_DIR = Path(".parrot") / "experience"
EVENTS_FILE = "events.jsonl"
TRIGGERS_FILE = "triggers.json"
SESSIONS_DIR = "sessions"
MAX_EVENT_BYTES = 4096

_MAX_SESSION_BYTES = 64 * 1024
_LOCK_POLL_SECONDS = 0.01
_AGY_EXIT_CODE_RE = re.compile(r"^Command exited with code (\d+)\.$")
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_ABSOLUTE_PATH_RE = re.compile(r"(?:(?:[A-Za-z]:)?/)[^\s:'\"`]+")
_TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"
)
_HEX_RE = re.compile(r"\b[0-9a-fA-F]{7,}\b")
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_BEARER_RE = re.compile(r"\b(Bearer\s+)([^\s,;]+)", re.IGNORECASE)
_URL_CREDENTIALS_RE = re.compile(r"(\w+://)([^\s/@:]+):[^\s/@]+@")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASS|KEY|AUTH|CREDENTIAL)[A-Za-z0-9_]*)=([^\s&;]+)",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,}|sk-[A-Za-z0-9_-]{8,}|xox[baprs]-[A-Za-z0-9-]{8,})\b")
_LONG_SECRET_RE = re.compile(r"\b(?:[0-9a-fA-F]{24,}|[A-Za-z0-9+/]{32,}={0,2})\b")


def safe_open(path: Path, flags: int) -> int | None:
    """Open a regular file without following links or blocking on special files.

    Args:
        path: File to open.
        flags: Flags passed to :func:`os.open`.

    Returns:
        An open descriptor for a regular file, or ``None`` when opening is unsafe or fails.
    """
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags | nofollow | nonblock, 0o600)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            return None
    except OSError:
        try:
            os.close(descriptor)
        except OSError:
            pass
        return None
    return descriptor


def session_file(plane_dir: Path, session_key: str) -> Path:
    """Return the hashed, single-component session path for ``session_key``.

    Args:
        plane_dir: Repository experience plane.
        session_key: Opaque host session identifier.

    Returns:
        The deterministic JSON session-file path.
    """
    digest = hashlib.sha1(session_key.encode("utf-8")).hexdigest()[:16]  # noqa: S324 - stable identity, not security
    return plane_dir / SESSIONS_DIR / f"{digest}.json"


def update_session(
    plane_dir: Path,
    session_key: str,
    mutate: Callable[[dict], dict],
    *,
    timeout_s: float = 1.0,
) -> dict | None:
    """Apply ``mutate`` under a stable advisory lock and atomically replace a session file.

    Args:
        plane_dir: Repository experience plane.
        session_key: Opaque host session identifier.
        mutate: Function which receives and returns a JSON-object session state.
        timeout_s: Maximum wait for the per-session lock.

    Returns:
        The updated state, or ``None`` when the state is unsafe, invalid, too large, or locked.
    """
    sessions_dir = plane_dir / SESSIONS_DIR
    if not _ensure_directory(plane_dir) or not _ensure_directory(sessions_dir):
        return None

    target = session_file(plane_dir, session_key)
    lock_path = target.with_suffix(".lock")
    lock_descriptor = safe_open(lock_path, os.O_RDWR | os.O_CREAT)
    if lock_descriptor is None:
        return None

    acquired = False
    try:
        deadline = time.monotonic() + max(timeout_s, 0.0)
        while True:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN) or time.monotonic() >= deadline:
                    return None
                time.sleep(_LOCK_POLL_SECONDS)

        current = _read_session(target)
        if current is None:
            return None
        try:
            updated = mutate(dict(current))
        except Exception:
            return None
        if not isinstance(updated, dict):
            return None
        try:
            payload = json.dumps(updated, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError):
            return None
        if len(payload) > _MAX_SESSION_BYTES:
            return None
        if not _atomic_write(target, payload):
            return None
        return updated
    finally:
        if acquired:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(lock_descriptor)
        except OSError:
            pass


def agy_exit_code(tool_output: str) -> int | None:
    """Read agy's host header exit code without accepting command-output spoofing.

    Args:
        tool_output: Full tool step text emitted by agy.

    Returns:
        The header exit code, or ``None`` when it is absent or malformed.
    """
    for line in tool_output.splitlines():
        if line == "Command output:":
            break
        match = _AGY_EXIT_CODE_RE.fullmatch(line)
        if match is not None:
            return int(match.group(1))
    return None


def leading_command(command: str) -> tuple[str, str]:
    """Return the executable and up-to-two-word subcommand of the first real segment.

    Args:
        command: Shell command as reported by a host.

    Returns:
        A pair of executable basename and subcommand, or empty strings when unparseable.
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return "", ""
    return _leading_tokens(tokens)


def normalize_error(text: str) -> str:
    """Remove unstable and sensitive portions of error text.

    Args:
        text: Error text collected from a host tool result.

    Returns:
        Stable whitespace-collapsed text, limited to 300 characters.
    """
    normalized = redact(text)
    normalized = _ABSOLUTE_PATH_RE.sub(" ", normalized)
    normalized = _TIMESTAMP_RE.sub(" ", normalized)
    normalized = _HEX_RE.sub(" ", normalized)
    normalized = _NUMBER_RE.sub(" ", normalized)
    return " ".join(normalized.split())[:300]


def redact(text: str) -> str:
    """Mask common secret-bearing values before persistence.

    Args:
        text: Arbitrary host-provided text.

    Returns:
        Text with secret values replaced by ``[REDACTED]``.
    """
    redacted = _BEARER_RE.sub(r"\1[REDACTED]", text)
    redacted = _URL_CREDENTIALS_RE.sub(r"\1[REDACTED]@", redacted)
    redacted = _SECRET_ASSIGNMENT_RE.sub(r"\1=[REDACTED]", redacted)
    redacted = _TOKEN_RE.sub("[REDACTED]", redacted)
    return _LONG_SECRET_RE.sub("[REDACTED]", redacted)


def failure_signature(executable: str, subcommand: str, error: str) -> str:
    """Build a stable failure signature.

    Args:
        executable: Leading executable basename.
        subcommand: Parsed command family.
        error: Host-reported error text.

    Returns:
        The normalized signature.
    """
    return f"{executable}|{subcommand}|{normalize_error(error)}"


def lesson_id_for(signature: str) -> str:
    """Return the deterministic lesson identifier for a signature.

    Args:
        signature: Normalized failure signature.

    Returns:
        ``pit-`` plus the signature SHA-1 prefix.
    """
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]  # noqa: S324 - stable identity, not security
    return f"pit-{digest}"


def resolve_plane_dir(cwd: Path) -> Path | None:
    """Resolve a checkout or linked worktree to its shared experience plane.

    Args:
        cwd: Directory inside a Git checkout.

    Returns:
        The shared ``.parrot/experience`` directory, or ``None`` outside Git.
    """
    try:
        current = cwd.resolve()
    except OSError:
        return None
    candidates = (current, *current.parents) if current.is_dir() else current.parents
    temporary_root = Path(tempfile.gettempdir()).resolve()
    for candidate in candidates:
        if candidate == temporary_root:
            break
        git_marker = candidate / ".git"
        try:
            marker_info = git_marker.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return None
        if stat.S_ISLNK(marker_info.st_mode):
            return None
        if stat.S_ISDIR(marker_info.st_mode):
            common_dir = git_marker
        elif stat.S_ISREG(marker_info.st_mode):
            git_dir = _git_dir_from_file(git_marker, candidate)
            if git_dir is None:
                return None
            common_dir = _common_git_dir(git_dir)
            if common_dir is None:
                return None
        else:
            return None
        return common_dir.parent / EXPERIENCE_DIR
    return None


def append_event(plane_dir: Path, record: Mapping[str, Any]) -> bool:
    """Append one bounded JSON event and synchronously flush it to disk.

    Args:
        plane_dir: Repository experience plane.
        record: JSON-serializable event mapping.

    Returns:
        ``True`` after a complete durable append, otherwise ``False``.
    """
    try:
        payload = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError):
        return False
    if len(payload) > MAX_EVENT_BYTES or not _ensure_directory(plane_dir):
        return False
    descriptor = safe_open(plane_dir / EVENTS_FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
    if descriptor is None:
        return False
    try:
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        return True
    except OSError:
        return False
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def load_triggers(plane_dir: Path, *, max_bytes: int) -> dict[str, list[dict[str, Any]]]:
    """Load a bounded, trusted-shape trigger index without following special files.

    Args:
        plane_dir: Repository experience plane.
        max_bytes: Largest accepted serialized trigger index.

    Returns:
        Executable-keyed lesson stubs, or an empty dictionary for absent or malformed input.
    """
    if max_bytes < 0:
        return {}
    descriptor = safe_open(plane_dir / TRIGGERS_FILE, os.O_RDONLY)
    if descriptor is None:
        return {}
    try:
        if os.fstat(descriptor).st_size > max_bytes:
            return {}
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > max_bytes:
            return {}
        parsed = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    if not isinstance(parsed, dict):
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    for executable, stubs in parsed.items():
        if not isinstance(executable, str) or not isinstance(stubs, list) or not all(isinstance(stub, dict) for stub in stubs):
            return {}
        result[executable] = [dict(stub) for stub in stubs]
    return result


def _ensure_directory(path: Path) -> bool:
    """Create and verify one non-symlink directory.

    Args:
        path: Directory to create or verify.

    Returns:
        ``True`` only for a real directory.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _read_session(path: Path) -> dict | None:
    """Read one bounded JSON-object session without following a link.

    Args:
        path: Session-file path.

    Returns:
        Its object state, an empty object for a missing file, or ``None`` when invalid.
    """
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {}
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    descriptor = safe_open(path, os.O_RDONLY)
    if descriptor is None:
        return None
    try:
        if os.fstat(descriptor).st_size > _MAX_SESSION_BYTES:
            return None
        payload = os.read(descriptor, _MAX_SESSION_BYTES + 1)
        if len(payload) > _MAX_SESSION_BYTES:
            return None
        parsed = json.loads(payload.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _atomic_write(path: Path, payload: bytes) -> bool:
    """Write a replacement session file and publish it atomically.

    Args:
        path: Session-file destination.
        payload: Complete serialized JSON object.

    Returns:
        Whether the replacement was published.
    """
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    descriptor = safe_open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    if descriptor is None:
        return False
    try:
        _write_all(descriptor, payload)
        os.fsync(descriptor)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    try:
        os.replace(temporary, path)
        return True
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _write_all(descriptor: int, payload: bytes) -> None:
    """Write all bytes to an already-open descriptor.

    Args:
        descriptor: Writable file descriptor.
        payload: Bytes to write.
    """
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("short write")
        offset += written


def _leading_tokens(tokens: list[str]) -> tuple[str, str]:
    """Parse a tokenized command's first executable segment.

    Args:
        tokens: Shell tokens.

    Returns:
        Parsed executable and subcommand.
    """
    index = 0
    while index < len(tokens):
        if tokens[index] in {"&&", ";", "||", "|"}:
            index += 1
            continue
        if tokens[index] == "cd":
            index = _next_segment(tokens, index)
            continue
        while index < len(tokens) and _ASSIGNMENT_RE.match(tokens[index]):
            index += 1
        if index >= len(tokens):
            return "", ""
        token = tokens[index]
        basename = Path(token).name
        if basename in {"bash", "sh", "dash", "zsh"}:
            shell_command = _shell_command(tokens[index + 1 :])
            return leading_command(shell_command) if shell_command is not None else ("", "")
        if basename == "env":
            index = _skip_env(tokens, index + 1)
            continue
        if basename == "sudo":
            index = _skip_sudo(tokens, index + 1)
            continue
        if basename == "timeout":
            index = _skip_timeout(tokens, index + 1)
            continue
        if basename == "uv" and index + 1 < len(tokens) and tokens[index + 1] == "run":
            index = _skip_uv_run(tokens, index + 2)
            continue
        if basename == "rtk":
            index += 1
            continue
        if not basename or basename.startswith("-"):
            return "", ""
        subcommand_parts: list[str] = []
        for value in tokens[index + 1 :]:
            if value in {"&&", ";", "||", "|"} or value.startswith("-"):
                break
            if _ASSIGNMENT_RE.match(value):
                continue
            subcommand_parts.append(value)
            if len(subcommand_parts) == 2:
                break
        return basename, " ".join(subcommand_parts)
    return "", ""


def _next_segment(tokens: list[str], index: int) -> int:
    """Find the first token after a command separator."""
    while index < len(tokens) and tokens[index] not in {"&&", ";", "||", "|"}:
        index += 1
    return index + 1


def _shell_command(tokens: list[str]) -> str | None:
    """Extract a shell ``-c`` command string from shell arguments."""
    for index, token in enumerate(tokens):
        if token == "--":
            return None
        if token == "-c" or (token.startswith("-") and "c" in token[1:]):
            return tokens[index + 1] if index + 1 < len(tokens) else None
    return None


def _skip_env(tokens: list[str], index: int) -> int:
    """Skip environment assignments and options after ``env``."""
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1
        if token.startswith("-") or _ASSIGNMENT_RE.match(token):
            index += 1
            continue
        return index
    return index


def _skip_sudo(tokens: list[str], index: int) -> int:
    """Skip known sudo options and their values."""
    options_with_values = {"-C", "-c", "-g", "-h", "-p", "-r", "-t", "-u", "--chdir", "--group", "--host", "--prompt", "--role", "--type", "--user"}
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1
        if token in options_with_values:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return index
    return index


def _skip_timeout(tokens: list[str], index: int) -> int:
    """Skip timeout options and its duration argument."""
    options_with_values = {"-k", "-s", "--kill-after", "--signal"}
    while index < len(tokens) and tokens[index].startswith("-"):
        option = tokens[index]
        index += 2 if option in options_with_values else 1
    return index + 1 if index < len(tokens) else index


def _skip_uv_run(tokens: list[str], index: int) -> int:
    """Skip common ``uv run`` options before its command."""
    options_with_values = {"--with", "--with-editable", "--python", "--project", "--directory", "--isolated", "--env-file"}
    while index < len(tokens) and tokens[index].startswith("-"):
        option = tokens[index]
        index += 2 if option in options_with_values else 1
    return index


def _git_dir_from_file(marker: Path, root: Path) -> Path | None:
    """Resolve the gitdir named by a regular worktree marker file."""
    descriptor = safe_open(marker, os.O_RDONLY)
    if descriptor is None:
        return None
    try:
        content = os.read(descriptor, 8192).decode("utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    prefix = "gitdir:"
    if not content.startswith(prefix):
        return None
    value = content[len(prefix) :].strip()
    if not value:
        return None
    try:
        return (root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    except OSError:
        return None


def _common_git_dir(git_dir: Path) -> Path | None:
    """Resolve a linked worktree's common Git directory."""
    common_file = git_dir / "commondir"
    try:
        info = common_file.lstat()
    except FileNotFoundError:
        return git_dir
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    descriptor = safe_open(common_file, os.O_RDONLY)
    if descriptor is None:
        return None
    try:
        value = os.read(descriptor, 8192).decode("utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    if not value:
        return None
    try:
        return (git_dir / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    except OSError:
        return None
