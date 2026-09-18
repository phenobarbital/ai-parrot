"""Unit tests for parrot.cli.modes (FEAT-573 TASK-3401)."""
from __future__ import annotations

import os
import stat

import pytest  # verified: packages/ai-parrot/tests/cli/test_integration.py:14

from parrot.cli.modes import (
    SessionPointer, UIMode, UIModeError, agent_slug, cli_state_dir, history_path,
    is_interactive, load_session_pointer, resolve_ui_mode, save_session_pointer,
)


@pytest.fixture
def parrot_home(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize(
    ("requested", "stdin", "stdout", "term", "expected"),
    [
        (UIMode.AUTO, True, True, "xterm-256color", UIMode.TUI),
        (UIMode.AUTO, True, True, "dumb", UIMode.INLINE),
        (UIMode.AUTO, False, True, "xterm", UIMode.INLINE),
        (UIMode.AUTO, True, False, "xterm", UIMode.INLINE),
        (UIMode.AUTO, True, True, None, UIMode.TUI),
        (UIMode.INLINE, True, True, "xterm", UIMode.INLINE),
        (UIMode.TUI, True, True, "xterm", UIMode.TUI),
    ],
)
def test_resolve_ui_mode_matrix(requested, stdin, stdout, term, expected) -> None:
    assert resolve_ui_mode(requested, stdin_isatty=stdin, stdout_isatty=stdout, term=term) is expected


def test_explicit_tui_on_non_tty_raises() -> None:
    with pytest.raises(UIModeError):
        resolve_ui_mode(UIMode.TUI, stdin_isatty=False, stdout_isatty=True, term="xterm")


def test_state_paths_honour_parrot_home_and_perms(parrot_home) -> None:
    d = cli_state_dir()
    assert d == parrot_home / "cli"
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
    save_session_pointer("My Agent!", "sess-1")
    p = parrot_home / "cli" / "sessions" / "my_agent_.json"
    assert p.exists() and stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert history_path("My Agent!") == parrot_home / "cli" / "history" / "my_agent_.txt"


def test_session_pointer_roundtrip_and_invalid_json(parrot_home) -> None:
    save_session_pointer("a", "s1")
    ptr = load_session_pointer("a")
    assert isinstance(ptr, SessionPointer) and ptr.last_session_id == "s1"
    (parrot_home / "cli" / "sessions" / "a.json").write_text("{not json", encoding="utf-8")
    assert load_session_pointer("a") is None
    assert load_session_pointer("never-saved") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", "agent"),
        ("..hidden", "hidden"),
        ("A/B", "a_b"),
    ],
)
def test_agent_slug_edge_cases(raw, expected) -> None:
    assert agent_slug(raw) == expected


def test_is_interactive() -> None:
    assert is_interactive(stdin_isatty=True, stdout_isatty=True) is True
    assert is_interactive(stdin_isatty=True, stdout_isatty=False) is False
    assert is_interactive(stdin_isatty=False, stdout_isatty=False) is False
