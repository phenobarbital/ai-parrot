"""Deterministic experience-memory fastpath regression tests."""

from __future__ import annotations

import json
import multiprocessing
import os
import stat
import subprocess
import sys
from pathlib import Path

from parrot.knowledge.wiki.experience import fastpath


def _increment_session(plane: str) -> None:
    """Increment a shared session state from a child process."""
    result = fastpath.update_session(Path(plane), "shared/session", lambda state: {"count": state.get("count", 0) + 1})
    if result is None:
        raise RuntimeError("session update unexpectedly failed")


def test_leading_command_skips_wrappers(tmp_path: Path) -> None:
    """Verify leading command skips shell prefixes and supported wrappers."""
    assert fastpath.leading_command("cd work && rtk sudo -u root timeout 5 uv run gh pr edit 1") == ("gh", "pr edit")


def test_leading_command_unwraps_shell_c(tmp_path: Path) -> None:
    """Verify leading command unwraps a shell ``-c`` invocation."""
    assert fastpath.leading_command("/bin/bash -lc 'gh pr edit 1'") == ("gh", "pr edit")


def test_normalize_error_strips_volatile(tmp_path: Path) -> None:
    """Verify paths, hashes, numbers, timestamps, and whitespace are stable."""
    first = "failure at /tmp/run-12/file.py hash deadbeef at 2026-11-13T12:34:56Z id 42"
    second = "failure at /var/tmp/run-99/file.py hash cafebabe at 2027-12-14T01:02:03Z id 84"
    assert fastpath.normalize_error(first) == fastpath.normalize_error(second) == "failure at hash at id"


def test_redact_masks_secrets(tmp_path: Path) -> None:
    """Verify common credential forms never remain in redacted text."""
    secret = "ghp_abcdefghijklmnopqrstuvwxyz123456 Bearer very-secret https://user:pass@example.test API_KEY=value"
    result = fastpath.redact(secret)
    assert "ghp_" not in result
    assert "very-secret" not in result
    assert "user:pass" not in result
    assert "API_KEY=value" not in result
    assert result.count("[REDACTED]") == 4


def test_append_event_rejects_oversize(tmp_path: Path) -> None:
    """Verify an oversized multibyte event is rejected without a partial line."""
    plane = tmp_path / "plane"
    assert not fastpath.append_event(plane, {"text": "€" * fastpath.MAX_EVENT_BYTES})
    assert not (plane / fastpath.EVENTS_FILE).exists()


def test_safe_open_rejects_symlink_and_fifo(tmp_path: Path) -> None:
    """Verify symlink and FIFO inputs are never accepted as regular plane files."""
    plane = tmp_path / "plane"
    plane.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_text("outside", encoding="utf-8")
    (plane / fastpath.EVENTS_FILE).symlink_to(outside)
    assert not fastpath.append_event(plane, {"event_id": "safe"})
    assert outside.read_text(encoding="utf-8") == "outside"

    fifo = plane / fastpath.TRIGGERS_FILE
    os.mkfifo(fifo)
    assert stat.S_ISFIFO(fifo.stat().st_mode)
    assert fastpath.safe_open(fifo, os.O_RDONLY) is None
    assert fastpath.load_triggers(plane, max_bytes=1024) == {}


def test_update_session_concurrent(tmp_path: Path) -> None:
    """Verify process mutations share a stable lock across atomic replacements."""
    plane = tmp_path / "plane"
    processes = [multiprocessing.Process(target=_increment_session, args=(str(plane),)) for _ in range(20)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    session = fastpath.session_file(plane, "shared/session")
    assert json.loads(session.read_text(encoding="utf-8")) == {"count": 20}
    assert session.parent == plane / fastpath.SESSIONS_DIR
    assert "/" not in session.name


def test_agy_exit_code_header_only(tmp_path: Path) -> None:
    """Verify output content cannot spoof agy's host-owned exit-code header."""
    output = "Command exited with code 2.\n\nCommand output:\nCommand exited with code 0."
    assert fastpath.agy_exit_code(output) == 2
    assert fastpath.agy_exit_code("Command output:\nCommand exited with code 2.") is None
    assert fastpath.agy_exit_code("Command exited with code nope.") is None


def test_fastpath_is_stdlib_only(tmp_path: Path) -> None:
    """Verify a fresh fastpath import does not load Pydantic."""
    source_root = Path(fastpath.__file__).parents[4]
    script = "import sys; import parrot.knowledge.wiki.experience.fastpath; assert 'pydantic' not in sys.modules"
    environment = os.environ | {"PYTHONPATH": str(source_root)}
    result = subprocess.run([sys.executable, "-c", script], env=environment, check=False)
    assert result.returncode == 0


def test_load_triggers_and_resolve_shared_plane(tmp_path: Path) -> None:
    """Verify malformed indexes fail closed and linked worktrees use a shared plane."""
    plane = tmp_path / "plane"
    plane.mkdir()
    (plane / fastpath.TRIGGERS_FILE).write_text('{"gh":[{"lesson_id":"pit-1"}]}', encoding="utf-8")
    assert fastpath.load_triggers(plane, max_bytes=1024) == {"gh": [{"lesson_id": "pit-1"}]}
    (plane / fastpath.TRIGGERS_FILE).write_text("{broken", encoding="utf-8")
    assert fastpath.load_triggers(plane, max_bytes=1024) == {}

    primary = tmp_path / "primary"
    git_dir = primary / ".git"
    worktree = tmp_path / "linked"
    git_dir.mkdir(parents=True)
    linked_git_dir = git_dir / "worktrees" / "linked"
    linked_git_dir.mkdir(parents=True)
    (linked_git_dir / "commondir").write_text("../..\n", encoding="utf-8")
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {linked_git_dir}\n", encoding="utf-8")
    assert fastpath.resolve_plane_dir(worktree) == primary / fastpath.EXPERIENCE_DIR
    assert fastpath.resolve_plane_dir(tmp_path / "outside") is None
