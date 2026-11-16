"""Deterministic experience-memory fastpath regression tests."""

from __future__ import annotations

import json
import multiprocessing
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_best_trigger_prefers_repo_then_confirmed_at_equal_score(tmp_path: Path) -> None:
    """Rank same-score matches by repository tier, then confirmation state."""
    stubs = [
        {
            "lesson_id": "global-confirmed",
            "state": "confirmed",
            "tier": "global",
            "executable": "gh",
            "subcommand": "pr edit",
            "error_tokens": ["permission", "denied"],
        },
        {
            "lesson_id": "repo-candidate",
            "state": "candidate",
            "tier": "repo",
            "executable": "gh",
            "subcommand": "pr edit",
            "error_tokens": ["permission", "denied"],
        },
        {
            "lesson_id": "repo-confirmed",
            "state": "confirmed",
            "tier": "repo",
            "executable": "gh",
            "subcommand": "pr edit",
            "error_tokens": ["permission", "denied"],
        },
    ]

    match = fastpath.best_trigger(stubs, "gh", "pr edit", "permission denied", min_score=0.35)

    assert match is not None
    assert match["lesson_id"] == "repo-confirmed"


def test_best_trigger_empty_or_low_similarity_signature_does_not_match(tmp_path: Path) -> None:
    """Reject empty signatures and matches below the configured threshold."""
    common = {"state": "confirmed", "executable": "gh", "subcommand": "pr edit"}
    empty = {**common, "lesson_id": "empty", "error_tokens": []}
    low_similarity = {**common, "lesson_id": "low", "error_tokens": ["permission", "denied"]}

    assert fastpath.best_trigger([empty], "gh", "pr edit", "network timeout", min_score=0.35) is None
    assert fastpath.best_trigger([low_similarity], "gh", "pr edit", "network timeout", min_score=0.35) is None


def test_redact_masks_secrets(tmp_path: Path) -> None:
    """Verify common credential forms never remain in redacted text."""
    secret = "ghp_abcdefghijklmnopqrstuvwxyz123456 Bearer very-secret https://user:pass@example.test API_KEY=value"
    result = fastpath.redact(secret)
    assert "ghp_" not in result
    assert "very-secret" not in result
    assert "user:pass" not in result
    assert "API_KEY=value" not in result
    assert result.count("[REDACTED]") == 4


def test_redact_covers_password_flags_basic_auth_json_and_aws_keys(tmp_path: Path) -> None:
    """Mask documented credential forms while preserving redaction idempotence."""
    secret = (
        '--password "secret with spaces" -pSECRET '
        'Authorization: Basic dXNlcjpwYXNz {"api_key": "quoted api key"} AKIAIOSFODNN7EXAMPLE'
    )

    result = fastpath.redact(secret)

    for value in ("secret with spaces", "SECRET", "dXNlcjpwYXNz", "quoted api key", "AKIAIOSFODNN7EXAMPLE"):
        assert value not in result
    assert "--password [REDACTED]" in result
    assert "-p[REDACTED]" in result
    assert "Authorization: Basic [REDACTED]" in result
    assert '"api_key": "[REDACTED]"' in result
    assert result == fastpath.redact(result)


def test_redact_short_password_flag_needs_a_token_boundary() -> None:
    """Mask a standalone ``-pVALUE`` token but leave ``-p`` inside words and long flags alone."""
    assert fastpath.redact("git-pull origin main") == "git-pull origin main"
    assert fastpath.redact("git log --pretty=oneline") == "git log --pretty=oneline"
    assert fastpath.redact("mysql -uroot -pSECRET db") == "mysql -uroot -p[REDACTED] db"


def test_redact_basic_auth_keeps_the_closing_quote() -> None:
    """Mask an unquoted Basic credential inside a quoted header without eating the quote."""
    assert (
        fastpath.redact('curl -H "Authorization: Basic dXNlcjpwYXNz" https://example.test')
        == 'curl -H "Authorization: Basic [REDACTED]" https://example.test'
    )
    assert fastpath.redact("curl -H 'Authorization: Basic dXNlcjpwYXNz'") == "curl -H 'Authorization: Basic [REDACTED]'"


def test_append_event_follows_a_log_rotated_before_it_takes_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never append into a sealed segment: reopen the fresh active log after a rotation."""
    plane = tmp_path / "plane"
    active = plane / fastpath.EVENTS_FILE
    sealed = plane / "events-1-sealed.jsonl"
    assert fastpath.append_event(plane, {"n": 1})
    original_lock = fastpath.lock_exclusive
    locked: list[int] = []

    def rotate_then_lock(descriptor: int, timeout_s: float) -> bool:
        if not locked:
            os.replace(active, sealed)
        locked.append(descriptor)
        return original_lock(descriptor, timeout_s)

    monkeypatch.setattr(fastpath, "lock_exclusive", rotate_then_lock)

    assert fastpath.append_event(plane, {"n": 2})
    assert len(locked) == 2
    assert sealed.read_bytes() == b'{"n":1}\n'
    assert active.read_bytes() == b'{"n":2}\n'


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
    """Verify malformed indexes fail closed."""
    plane = tmp_path / "plane"
    plane.mkdir()
    (plane / fastpath.TRIGGERS_FILE).write_text('{"gh":[{"lesson_id":"pit-1"}]}', encoding="utf-8")
    assert fastpath.load_triggers(plane, max_bytes=1024) == {"gh": [{"lesson_id": "pit-1"}]}
    (plane / fastpath.TRIGGERS_FILE).write_text("{broken", encoding="utf-8")
    assert fastpath.load_triggers(plane, max_bytes=1024) == {}

    assert fastpath.resolve_plane_dir(tmp_path / "outside") is None


def test_resolve_plane_dir_rejects_forged_gitdir_marker(tmp_path: Path) -> None:
    """Verify a marker cannot point the plane at another checkout's Git directory."""
    foreign = tmp_path / "foreign"
    (foreign / ".git").mkdir(parents=True)
    (foreign / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    forged = tmp_path / "forged"
    forged.mkdir()
    (forged / ".git").write_text(f"gitdir: {foreign / '.git'}\n", encoding="utf-8")

    assert fastpath.resolve_plane_dir(forged) is None


def test_worktree_uses_primary_plane(tmp_path: Path) -> None:
    """Verify a genuine linked worktree outside the managed tree uses the primary plane."""
    primary = tmp_path / "primary"
    primary.mkdir()
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "Test"],
        ["git", "commit", "--allow-empty", "-qm", "initial"],
    ):
        subprocess.run(command, cwd=primary, capture_output=True, check=True)

    worktree = tmp_path / "linked"
    subprocess.run(
        ["git", "worktree", "add", "-b", "linked", str(worktree)], cwd=primary, capture_output=True, check=True
    )

    assert fastpath.resolve_plane_dir(worktree) == primary / fastpath.EXPERIENCE_DIR


def test_append_event_never_raises(tmp_path: Path) -> None:
    """Verify unserializable, oversize and unwritable appends return False instead of raising."""
    plane = tmp_path / "plane"
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    assert fastpath.append_event(plane, {"bad": object()}) is False
    assert fastpath.append_event(plane, {"bad": {1, 2}}) is False
    assert fastpath.append_event(blocker / "plane", {"event_id": "x"}) is False
    assert fastpath.append_event(plane, {"text": "x" * (fastpath.MAX_EVENT_BYTES + 1)}) is False
    assert not (plane / fastpath.EVENTS_FILE).exists()


def test_session_file_name_is_hashed(tmp_path: Path) -> None:
    """Verify a hostile session key maps to one stable hashed single-component file name."""
    plane = tmp_path / "plane"
    hostile = "../../etc/passwd/../session"
    path = fastpath.session_file(plane, hostile)

    assert path.parent == plane / fastpath.SESSIONS_DIR
    assert path.name != hostile
    assert "/" not in path.name and ".." not in path.name
    assert path.suffix == ".json"
    assert len(path.stem) == 16 and all(char in "0123456789abcdef" for char in path.stem)
    assert path == fastpath.session_file(plane, hostile)
    assert path != fastpath.session_file(plane, hostile + "x")


def test_load_hook_limits_defaults_and_published_values(tmp_path: Path) -> None:
    """Verify hook limits fall back to defaults and accept only bounded, validated values."""
    plane = tmp_path / "plane"
    plane.mkdir()
    defaults = fastpath.load_hook_limits(plane)
    assert defaults["advice_cooldown_seconds"] == 600
    assert defaults["max_session_pending"] == 32

    (plane / "fastpath.json").write_text(
        json.dumps(
            {
                "inject_min_score": 0.8,
                "advice_cooldown_seconds": 5,
                "max_session_pending": 3,
                "max_transcript_tail_bytes": 4096,
                "pairing_excluded_executables": ["make"],
            }
        ),
        encoding="utf-8",
    )
    limits = fastpath.load_hook_limits(plane)
    assert limits["inject_min_score"] == 0.8
    assert limits["advice_cooldown_seconds"] == 5
    assert limits["max_session_pending"] == 3
    assert limits["max_transcript_tail_bytes"] == 4096
    assert tuple(limits["pairing_excluded_executables"]) == ("make",)

    (plane / "fastpath.json").write_text(
        json.dumps(
            {
                "inject_min_score": 7,
                "advice_cooldown_seconds": -1,
                "max_session_pending": True,
                "max_transcript_tail_bytes": 10**12,
                "pairing_excluded_executables": [1],
            }
        ),
        encoding="utf-8",
    )
    assert fastpath.load_hook_limits(plane) == defaults
    (plane / "fastpath.json").write_text("{broken", encoding="utf-8")
    assert fastpath.load_hook_limits(plane) == defaults


def test_is_repo_local_command_rule(tmp_path: Path) -> None:
    """Verify scoped, relative and repository-contained absolute commands route to the repo tier."""
    root = tmp_path / "repo"
    assert fastpath.is_repo_local_command(root, "gh", ["src/a.py"]) is True
    assert fastpath.is_repo_local_command(root, "./scripts/check") is True
    assert fastpath.is_repo_local_command(root, "../tool") is True
    assert fastpath.is_repo_local_command(root, str(root / "bin" / "tool") + " --flag") is True
    assert fastpath.is_repo_local_command(root, "/usr/bin/gh") is False
    assert fastpath.is_repo_local_command(root, str(root / "bin" / "tool")) is True
    assert fastpath.is_repo_local_command(None, str(root / "bin" / "tool")) is False
    assert fastpath.is_repo_local_command(root, "gh") is False
