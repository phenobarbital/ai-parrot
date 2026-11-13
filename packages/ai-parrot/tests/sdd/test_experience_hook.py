"""Deterministic experience-memory regression tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.sdd.scripts import experience_hook


def _plane(tmp_path: Path) -> Path:
    """Create an isolated checkout and return its experience plane."""
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    plane = root / ".parrot" / "experience"
    plane.mkdir(parents=True)
    return plane


def _stub() -> dict[str, object]:
    """Return one published trigger stub for a command failure."""
    return {
        "lesson_id": "pit-hook",
        "state": "candidate",
        "solution_rev": "r1",
        "executable": "gh",
        "subcommand": "pr edit",
        "error_tokens": ["denied"],
        "fix_executable": "gh",
        "fix_subcommand": "api",
        "advice": "Use the API workaround.",
        "recording_session": "other-session",
    }


def _write_triggers(plane: Path) -> None:
    """Publish one bounded trigger map in an isolated plane."""
    (plane / "triggers.json").write_text(json.dumps({"gh": [_stub()]}), encoding="utf-8")


def test_hook_envelopes_per_host(tmp_path: Path) -> None:
    """Verify hook envelopes per host."""
    plane = _plane(tmp_path)
    advice = "Check the workaround."
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(
        json.dumps(
            {
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "CommandExecution",
                        "id": "codex-call",
                        "status": "failed",
                        "exit_code": 2,
                        "aggregated_output": "permission denied",
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert experience_hook.render(advice, host="claude", event="post") == {
        "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": advice},
        "suppressOutput": True,
    }
    assert experience_hook.render(advice, host="claude", event="post-failure") == {
        "hookSpecificOutput": {"hookEventName": "PostToolUseFailure", "additionalContext": advice},
        "suppressOutput": True,
    }
    assert experience_hook.render(advice, host="codex", event="post") == {
        "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": advice}
    }
    assert experience_hook.render(advice, host="agy", event="post") == {}
    assert experience_hook.render(advice, host="agy", event="post-invocation") == {
        "injectSteps": [{"systemMessage": {"systemMessage": advice}}]
    }
    assert experience_hook.command_of(
        {"tool_name": "Bash", "tool_input": {"command": "gh pr edit 12"}}, "claude"
    ) == "gh pr edit 12"
    assert experience_hook.outcome_of(
        {"tool_name": "Bash", "tool_input": {"command": "gh pr edit 12"}, "error": "denied"},
        "claude",
        "post-failure",
    ) == (False, "denied")
    assert experience_hook.outcome_of(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr edit 12"},
            "tool_use_id": "codex-call",
            "transcript_path": str(rollout),
        },
        "codex",
        "post",
    ) == (False, "permission denied")
    assert experience_hook.handle_post(
        {"tool_name": "Bash", "tool_input": {"command": "gh pr edit 12"}},
        host="codex",
        event="post",
        plane_dir=plane,
    ) is None


def test_hook_session_key_includes_agent_id(tmp_path: Path) -> None:
    """Verify hook session key includes agent id."""
    _plane(tmp_path)
    payload = {"session_id": "parent-session", "agent_id": "child-a"}

    assert experience_hook.session_of(payload, {}) == "parent-session/child-a"
    assert experience_hook.session_of({"conversationId": "agy-session"}, {}) == "agy-session"
    assert experience_hook.session_of(payload, {"PARROT_EXPERIENCE_SESSION": "pinned"}) == "pinned/child-a"
    assert experience_hook.session_of({}, {}) == "unknown"


def test_hook_agy_outcome_from_transcript(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify hook agy outcome from transcript."""
    plane = _plane(tmp_path)
    _write_triggers(plane)
    transcript = tmp_path / "agy.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "step_index": 2,
                "type": "GENERIC",
                "content": "Command exited with code 2.\n\nCommand output:\npermission denied",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("PARROT_EXPERIENCE_SESSION", raising=False)
    post_payload = {
        "conversationId": "agy-session",
        "stepIdx": 2,
        "toolCall": {"name": "run_command", "args": {"CommandLine": "gh pr edit 12"}},
    }

    assert experience_hook.handle_post(post_payload, host="agy", event="post", plane_dir=plane) is None
    advice = experience_hook.handle_post_invocation(
        {"conversationId": "agy-session", "transcriptPath": str(transcript)}, plane_dir=plane
    )

    assert advice is not None
    assert experience_hook.render(advice, host="agy", event="post-invocation") == {
        "injectSteps": [{"systemMessage": {"systemMessage": advice}}]
    }
    events = (plane / "events.jsonl").read_text(encoding="utf-8")
    assert "failure.observed" in events
    assert experience_hook.agy_outcome(transcript, 2, max_bytes=1024) == (False, "permission denied")


def test_hook_budget_overflow_is_noop(tmp_path: Path) -> None:
    """Verify hook budget overflow is noop."""
    plane = _plane(tmp_path)
    (plane / "triggers.json").write_bytes(b"x" * (262_144 + 1))
    payload = {
        "session_id": "session",
        "tool_name": "Bash",
        "tool_input": {"command": "gh pr edit 12"},
        "tool_use_id": "call-1",
        "error": "permission denied",
    }

    assert experience_hook.handle_post(payload, host="claude", event="post-failure", plane_dir=plane) is None
    assert not (plane / "events.jsonl").exists()
