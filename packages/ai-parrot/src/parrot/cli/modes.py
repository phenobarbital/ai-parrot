"""UI mode resolution and per-user CLI state paths for ``parrot agent`` (FEAT-573 M2)."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field  # verified: parrot/cli/repl.py:18

logger = logging.getLogger(__name__)
_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


class UIMode(str, Enum):
    """Presentation mode requested on the command line."""

    AUTO = "auto"
    INLINE = "inline"
    TUI = "tui"


class UIModeError(ValueError):
    """Raised when an explicitly requested mode cannot run on this terminal."""


class SessionPointer(BaseModel):
    """Last conversation session used with an agent (for ``--session last``)."""

    agent_name: str
    last_session_id: str
    updated_at: datetime = Field(default_factory=datetime.now)


def is_interactive(*, stdin_isatty: bool, stdout_isatty: bool) -> bool:
    """True when both streams are TTYs; False selects batch/line mode."""
    return bool(stdin_isatty and stdout_isatty)


def resolve_ui_mode(requested: UIMode, *, stdin_isatty: bool, stdout_isatty: bool, term: Optional[str]) -> UIMode:
    """Resolve ``AUTO`` to ``INLINE`` or ``TUI``; pass ``INLINE``/``TUI`` through.

    Raises:
        UIModeError: when ``TUI`` is requested explicitly but the streams are not both TTYs
            (or ``TERM`` is ``dumb``).
    """
    tui_capable = (
        is_interactive(stdin_isatty=stdin_isatty, stdout_isatty=stdout_isatty) and (term or "").lower() != "dumb"
    )
    if requested is UIMode.AUTO:
        return UIMode.TUI if tui_capable else UIMode.INLINE
    if requested is UIMode.TUI:
        if not tui_capable:
            raise UIModeError(
                "Explicit --ui tui requires an interactive terminal (both stdin and stdout must be "
                "TTYs and TERM must not be 'dumb'); use --ui inline instead."
            )
        return UIMode.TUI
    return UIMode.INLINE


def cli_state_dir() -> Path:
    """``$PARROT_HOME`` or ``~/.parrot`` (wiki/project.py:1009 convention) + ``cli``; created ``0o700``."""
    raw = os.environ.get("PARROT_HOME") or "~/.parrot"
    path = Path(raw).expanduser() / "cli"
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def agent_slug(agent_name: str) -> str:
    """Filesystem-safe slug: lowercase, ``[^a-z0-9._-]`` → ``_``, no leading dots."""
    slug = _SLUG_RE.sub("_", agent_name.lower())
    slug = re.sub(r"_+", "_", slug)
    slug = slug.lstrip(".")
    return slug or "agent"


def history_path(agent_name: str) -> Path:
    """``cli_state_dir()/history/<slug>.txt`` (prompt_toolkit FileHistory format); file mode ``0o600`` when present."""
    parent = cli_state_dir() / "history"
    parent.mkdir(parents=True, exist_ok=True)
    os.chmod(parent, 0o700)
    path = parent / f"{agent_slug(agent_name)}.txt"
    if path.exists():
        os.chmod(path, 0o600)
    return path


def load_session_pointer(agent_name: str) -> Optional[SessionPointer]:
    """Read ``cli_state_dir()/sessions/<slug>.json``; ``None`` when absent or invalid."""
    path = cli_state_dir() / "sessions" / f"{agent_slug(agent_name)}.json"
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return SessionPointer.model_validate(data)
    except (OSError, ValueError) as exc:
        logger.debug("No usable session pointer for %s: %s", agent_name, exc)
        return None


def save_session_pointer(agent_name: str, session_id: str) -> None:
    """Atomic write (tmp + ``os.replace``) of the pointer file, mode ``0o600``."""
    parent = cli_state_dir() / "sessions"
    parent.mkdir(parents=True, exist_ok=True)
    os.chmod(parent, 0o700)
    pointer = SessionPointer(agent_name=agent_name, last_session_id=session_id)
    target = parent / f"{agent_slug(agent_name)}.json"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=parent, delete=False) as tmp_file:
        tmp_file.write(pointer.model_dump_json())
        tmp_path = Path(tmp_file.name)
    try:
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    os.chmod(target, 0o600)
