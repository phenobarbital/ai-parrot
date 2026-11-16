"""Deterministic experience-memory regression tests."""

from __future__ import annotations

import json
import os
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


def test_hook_prefers_frozen_roots_over_forged_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a frozen hook plane cannot be redirected by a writable Git marker."""
    frozen_root = tmp_path / "worktree"
    payload_cwd = frozen_root / "sub" / "nested"
    payload_cwd.mkdir(parents=True)
    foreign = tmp_path / "foreign"
    (foreign / ".git").mkdir(parents=True)
    (frozen_root / "sub" / ".git").write_text(f"gitdir: {foreign / '.git'}\n", encoding="utf-8")
    common_dir = tmp_path / "primary" / ".git"
    expected_plane = common_dir.parent / ".parrot" / "experience"
    captured: list[Path] = []

    def capture_plane(*args: object, plane_dir: Path, **kwargs: object) -> None:
        captured.append(plane_dir)

    monkeypatch.setenv(
        "PARROT_SDD_SANDBOX_ROOTS",
        os.pathsep.join((str(frozen_root), str(common_dir), str(common_dir.parent))),
    )
    monkeypatch.setattr(experience_hook, "_read_payload", lambda: {"cwd": str(payload_cwd)})
    monkeypatch.setattr(experience_hook, "handle_post", capture_plane)

    assert experience_hook.main(["--host", "claude", "--event", "post"]) == 0
    assert captured == [expected_plane]


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
    assert (
        experience_hook.command_of({"tool_name": "Bash", "tool_input": {"command": "gh pr edit 12"}}, "claude")
        == "gh pr edit 12"
    )
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
    assert (
        experience_hook.handle_post(
            {"tool_name": "Bash", "tool_input": {"command": "gh pr edit 12"}},
            host="codex",
            event="post",
            plane_dir=plane,
        )
        is None
    )


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


def test_hook_matcher_ranks_competing_stubs(tmp_path: Path) -> None:
    """Use the shared matcher ranking and published threshold in the hook."""
    plane = _plane(tmp_path)
    global_confirmed = {**_stub(), "lesson_id": "global-confirmed", "state": "confirmed", "tier": "global"}
    repo_candidate = {**_stub(), "lesson_id": "repo-candidate", "state": "candidate", "tier": "repo"}
    repo_confirmed = {**_stub(), "lesson_id": "repo-confirmed", "state": "confirmed", "tier": "repo"}
    for stub in (global_confirmed, repo_candidate, repo_confirmed):
        stub["error_tokens"] = ["permission", "denied"]
    (plane / "triggers.json").write_text(
        json.dumps({"gh": [global_confirmed, repo_candidate, repo_confirmed]}), encoding="utf-8"
    )
    (plane / "fastpath.json").write_text(json.dumps({"inject_min_score": 0.75}), encoding="utf-8")

    matcher = experience_hook._trigger_matcher(plane)

    assert matcher("gh", "pr edit", "permission denied") == repo_confirmed
    assert matcher("gh", "pr edit", "network timeout") is None


def test_hook_post_failure_redacts_token_and_truncates_large_error(tmp_path: Path) -> None:
    """Verify the hook persists only redacted, bounded command failure data."""
    plane = _plane(tmp_path)
    secret = "ghp_thisisasecretvaluethatmustnotpersist"
    command = f"gh pr edit 12 -H 'Authorization: Bearer {secret}' GH_TOKEN={secret} " + "x" * 600
    error = f"Authorization: Bearer {secret} TOKEN={secret} " + "failure " * 1000
    payload = {
        "session_id": "safe-session",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_use_id": "call-1",
        "error": error,
    }

    assert experience_hook.handle_post(payload, host="claude", event="post-failure", plane_dir=plane) is None

    event = json.loads((plane / "events.jsonl").read_text(encoding="utf-8"))
    session = next((plane / "sessions").glob("*.json"))
    stored = session.read_text(encoding="utf-8")
    assert secret not in json.dumps(event)
    assert secret not in stored
    assert len(event["payload"]["error_signature"]) <= 300
    assert len(event["payload"]["error_excerpt"]) <= 400
    pending = json.loads(stored)["pending"][0]
    assert len(pending["command"]) <= 300
    assert len(pending["error"]) <= 400


@pytest.mark.parametrize(
    ("argv", "marker", "runs"),
    [
        (["--host", "claude", "--event", "post"], "1", False),  # portable settings.json hook stands down
        (["--host", "claude", "--event", "post", "--isolated"], "1", True),  # injected isolated hook runs
        (["--host", "claude", "--event", "post"], None, True),  # ordinary session: portable hook runs
        (["--host", "codex", "--event", "post"], "1", True),  # codex/agy hooks are portable-only
    ],
)
def test_portable_claude_hook_stands_down_in_isolated_session(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], marker: str | None, runs: bool
) -> None:
    """Only the injected ``--isolated`` Claude hook handles events in a sandboxed session."""
    reads: list[int] = []

    def read_payload() -> None:
        reads.append(1)

    monkeypatch.setattr(experience_hook, "_read_payload", read_payload)
    if marker is None:
        monkeypatch.delenv(experience_hook.ISOLATED_ENV, raising=False)
    else:
        monkeypatch.setenv(experience_hook.ISOLATED_ENV, marker)

    assert experience_hook.main(argv) == 0
    assert bool(reads) is runs


def _claude_payload(command: str = "gh pr edit 12", **extra: object) -> dict[str, object]:
    """Return a Claude Bash callback payload."""
    return {"session_id": "s", "tool_name": "Bash", "tool_input": {"command": command}, **extra}


def _events(plane: Path) -> list[dict[str, object]]:
    """Read the plane's events, empty when none were appended."""
    path = plane / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_hook_outcome_claude() -> None:
    """Verify Claude success and failure outcomes come from the event, never from guesswork."""
    payload = _claude_payload(error="denied")
    assert experience_hook.outcome_of(payload, "claude", "post") == (True, "")
    assert experience_hook.outcome_of(payload, "claude", "post-failure") == (False, "denied")
    assert experience_hook.outcome_of(_claude_payload(), "claude", "post-failure") == (False, "")
    assert experience_hook.outcome_of(payload, "claude", "post-invocation") is None


def test_hook_codex_outcome_from_rollout(tmp_path: Path) -> None:
    """Verify Codex outcomes join the rollout by item id and ignore other records."""
    rollout = tmp_path / "rollout.jsonl"

    def item(identifier: str, code: int, output: str) -> str:
        return json.dumps(
            {
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "CommandExecution",
                        "id": identifier,
                        "status": "completed" if code == 0 else "failed",
                        "exit_code": code,
                        "aggregated_output": output,
                    },
                },
            }
        )

    rollout.write_text("\n".join((item("other", 0, "fine"), item("mine", 3, "boom"), "not json")) + "\n", encoding="utf-8")

    assert experience_hook.codex_outcome(rollout, "mine", max_bytes=65_536) == (False, "boom")
    assert experience_hook.codex_outcome(rollout, "other", max_bytes=65_536) == (True, "fine")
    assert experience_hook.codex_outcome(rollout, "missing", max_bytes=65_536) is None
    assert experience_hook.codex_outcome(tmp_path / "absent.jsonl", "mine", max_bytes=65_536) is None


def test_hook_unknown_outcome_records_nothing(tmp_path: Path) -> None:
    """Verify an unresolvable outcome appends no event and creates no session."""
    plane = _plane(tmp_path)
    _write_triggers(plane)
    codex = _claude_payload(tool_use_id="missing", transcript_path=str(tmp_path / "absent.jsonl"))

    assert experience_hook.handle_post(codex, host="codex", event="post", plane_dir=plane) is None
    assert experience_hook.handle_post(_claude_payload(), host="claude", event="post-invocation", plane_dir=plane) is None
    assert _events(plane) == []
    assert not (plane / "sessions").exists()


def test_hook_post_failure_injects_candidate_labeled(tmp_path: Path) -> None:
    """Verify a matching failure injects advice labelled as an unverified candidate."""
    plane = _plane(tmp_path)
    _write_triggers(plane)
    payload = _claude_payload(tool_use_id="call-1", error="denied")

    advice = experience_hook.handle_post(payload, host="claude", event="post-failure", plane_dir=plane)

    assert advice is not None
    assert advice.startswith("[experience:pit-hook candidate]")
    assert "not an instruction" in advice
    assert [event["kind"] for event in _events(plane)] == ["failure.observed", "lesson.injected"]


def test_hook_advice_cooldown(tmp_path: Path) -> None:
    """Verify the published advice cooldown suppresses a repeat injection of the same lesson."""
    plane = _plane(tmp_path)
    _write_triggers(plane)
    (plane / "fastpath.json").write_text(json.dumps({"advice_cooldown_seconds": 3600}), encoding="utf-8")

    def fail(identifier: str) -> str | None:
        return experience_hook.handle_post(
            _claude_payload(tool_use_id=identifier, error="denied"), host="claude", event="post-failure", plane_dir=plane
        )

    assert fail("one") is not None
    assert fail("two") is None  # refutes the open injection
    assert fail("three") is None  # re-injected inside the published cooldown


def test_hook_published_knobs_change_hook_behaviour(tmp_path: Path) -> None:
    """Verify a rebuilt non-default fastpath.json changes cooldown, pending bound and exclusions."""
    plane = _plane(tmp_path)
    _write_triggers(plane)
    (plane / "fastpath.json").write_text(
        json.dumps({"advice_cooldown_seconds": 1, "max_session_pending": 1, "pairing_excluded_executables": ["make"]}),
        encoding="utf-8",
    )

    for index in range(3):
        experience_hook.handle_post(
            _claude_payload("make test", tool_use_id=f"m{index}", error="boom"),
            host="claude",
            event="post-failure",
            plane_dir=plane,
        )
    assert _events(plane) == []  # "make" is excluded by the published knob

    for index in range(3):
        experience_hook.handle_post(
            _claude_payload(f"gh pr list {index}", tool_use_id=f"g{index}", error=f"boom {index}"),
            host="claude",
            event="post-failure",
            plane_dir=plane,
        )
    state = json.loads(next((plane / "sessions").glob("*.json")).read_text(encoding="utf-8"))
    assert len(state["pending"]) == 1  # bounded by the published max_session_pending


def test_hook_never_rebuilds_or_graduates(tmp_path: Path) -> None:
    """Verify the hook writes only events and sessions, never the published index or graduation files."""
    plane = _plane(tmp_path)
    _write_triggers(plane)
    before = (plane / "triggers.json").read_bytes()

    experience_hook.handle_post(
        _claude_payload(tool_use_id="c", error="denied"), host="claude", event="post-failure", plane_dir=plane
    )

    assert (plane / "triggers.json").read_bytes() == before
    assert {entry.name for entry in plane.iterdir()} <= {"triggers.json", "events.jsonl", "sessions"}
    assert not (plane / "fastpath.json").exists()


def test_hook_never_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify every failure path exits zero so an advisory hook cannot block its host."""

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(experience_hook, "_read_payload", explode)
    assert experience_hook.main(["--host", "claude", "--event", "post"]) == 0
    assert experience_hook.main(["--host", "unknown", "--event", "post"]) == 0
    assert experience_hook.main([]) == 0

    monkeypatch.setattr(experience_hook, "_read_payload", lambda: {"cwd": str(tmp_path / "nowhere")})
    monkeypatch.setattr(experience_hook, "handle_post", explode)
    assert experience_hook.main(["--host", "claude", "--event", "post"]) == 0


def test_hook_agy_unreadable_transcript_defers_to_replay(tmp_path: Path) -> None:
    """Verify an unreadable agy transcript records nothing and leaves the step for replay."""
    plane = _plane(tmp_path)
    _write_triggers(plane)
    post = {
        "conversationId": "agy-session",
        "stepIdx": 4,
        "toolCall": {"name": "run_command", "args": {"CommandLine": "gh pr edit 12"}},
    }

    assert experience_hook.handle_post(post, host="agy", event="post", plane_dir=plane) is None
    advice = experience_hook.handle_post_invocation(
        {"conversationId": "agy-session", "transcriptPath": str(tmp_path / "missing.jsonl")}, plane_dir=plane
    )

    assert advice is None
    assert _events(plane) == []
