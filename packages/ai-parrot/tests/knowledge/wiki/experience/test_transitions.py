"""Deterministic experience-memory regression tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import pytest

from parrot.knowledge.wiki.experience.fastpath import failure_signature, lesson_id_for, normalize_error
from parrot.knowledge.wiki.experience import transitions
from parrot.knowledge.wiki.experience.transitions import on_outcome


@dataclass(frozen=True)
class Outcome:
    """Duck-typed hook outcome that avoids a runtime Pydantic dependency."""

    ok: bool | None
    error: str = ""
    observation_id: str = ""


def _stub(*, advice: str = "Use the API workaround.") -> dict[str, object]:
    """Return one published trigger-map stub."""
    return {
        "lesson_id": "pit-transition",
        "state": "candidate",
        "solution_rev": "revision",
        "executable": "gh",
        "subcommand": "pr edit",
        "error_tokens": ["permission", "denied"],
        "fix_executable": "gh",
        "fix_subcommand": "api",
        "advice": advice,
        "recording_session": "recording-session",
    }


def _matcher(stub: dict[str, object]):
    """Return a synchronous published-map matcher for a single gh trigger."""

    def match(executable: str, subcommand: str, error: str) -> dict[str, object] | None:
        return stub if (executable, subcommand, error) == ("gh", "pr edit", "permission denied") else None

    return match


def _events(plane: Path) -> list[dict[str, object]]:
    """Read append-only events from an isolated plane."""
    event_file = plane / "events.jsonl"
    if not event_file.exists():
        return []
    return [json.loads(line) for line in event_file.read_text(encoding="utf-8").splitlines()]


def test_hook_pairing_drafts_lesson(tmp_path: Path) -> None:
    """Verify a same-family failed retry drafts one paired lesson."""
    plane = tmp_path / "plane"

    assert (
        on_outcome(
            plane,
            session="pair",
            command="gh pr edit 1",
            outcome=Outcome(False, "permission denied", "failure"),
            seat="codex",
            matcher=lambda *_: None,
        )
        is None
    )
    assert (
        on_outcome(
            plane,
            session="pair",
            command="gh pr edit 1 --base dev",
            outcome=Outcome(True, observation_id="retry"),
            seat="codex",
            matcher=lambda *_: None,
        )
        is None
    )

    recorded = [event for event in _events(plane) if event["kind"] == "lesson.recorded"]
    assert len(recorded) == 1
    assert recorded[0]["payload"]["source"] == "paired"


def test_hook_validation_by_fix_family(tmp_path: Path) -> None:
    """Verify only a successful configured fix family validates an injection."""
    plane = tmp_path / "plane"
    matcher = _matcher(_stub())
    on_outcome(
        plane,
        session="fix",
        command="gh pr edit 1",
        outcome=Outcome(False, "permission denied", "one"),
        seat="codex",
        matcher=matcher,
    )
    on_outcome(
        plane,
        session="fix",
        command="gh pr list",
        outcome=Outcome(True, observation_id="two"),
        seat="codex",
        matcher=matcher,
    )
    on_outcome(
        plane,
        session="fix",
        command="gh api -X PATCH",
        outcome=Outcome(True, observation_id="three"),
        seat="codex",
        matcher=matcher,
    )

    evidence = [event for event in _events(plane) if event["kind"] == "lesson.validated"]
    assert [event["payload"]["via"] for event in evidence] == ["fix_family"]


def test_hook_validation_and_refutation(tmp_path: Path) -> None:
    """Verify trigger-family success validates while failure refutes the injection."""
    plane = tmp_path / "plane"
    matcher = _matcher(_stub())
    on_outcome(
        plane,
        session="validate",
        command="gh pr edit 1",
        outcome=Outcome(False, "permission denied", "one"),
        seat="codex",
        matcher=matcher,
    )
    on_outcome(
        plane,
        session="validate",
        command="gh pr edit 1 --base dev",
        outcome=Outcome(True, observation_id="two"),
        seat="codex",
        matcher=matcher,
    )
    on_outcome(
        plane,
        session="refute",
        command="gh pr edit 2",
        outcome=Outcome(False, "permission denied", "three"),
        seat="codex",
        matcher=matcher,
    )
    on_outcome(
        plane,
        session="refute",
        command="gh pr edit 2 --base dev",
        outcome=Outcome(False, "different", "four"),
        seat="codex",
        matcher=matcher,
    )

    kinds = [event["kind"] for event in _events(plane)]
    assert "lesson.validated" in kinds
    assert "lesson.refuted" in kinds


def test_hook_excluded_executables(tmp_path: Path) -> None:
    """Verify unknown outcomes and excluded failure families leave no events."""
    plane = tmp_path / "plane"
    matcher = _matcher(_stub())
    assert (
        on_outcome(
            plane,
            session="excluded",
            command="pytest test.py",
            outcome=Outcome(False, "failed", "one"),
            seat="codex",
            matcher=matcher,
        )
        is None
    )
    assert (
        on_outcome(
            plane,
            session="excluded",
            command="gh pr edit 1",
            outcome=Outcome(None, "permission denied", "two"),
            seat="codex",
            matcher=matcher,
        )
        is None
    )
    assert _events(plane) == []


def test_hook_duplicate_callback_idempotent(tmp_path: Path) -> None:
    """Verify duplicate observation ids add neither events nor repeated advice."""
    plane = tmp_path / "plane"
    matcher = _matcher(_stub())
    first = on_outcome(
        plane,
        session="duplicate",
        command="gh pr edit 1",
        outcome=Outcome(False, "permission denied", "one"),
        seat="codex",
        matcher=matcher,
    )
    second = on_outcome(
        plane,
        session="duplicate",
        command="gh pr edit 1",
        outcome=Outcome(False, "permission denied", "one"),
        seat="codex",
        matcher=matcher,
    )

    assert first is not None
    assert second is None
    assert [event["kind"] for event in _events(plane)] == ["failure.observed", "lesson.injected"]


def test_advice_escapes_lesson_text(tmp_path: Path) -> None:
    """Verify advisory data is bounded and cannot inject formatting-sensitive text."""
    plane = tmp_path / "plane"
    advice = "[experience:pit-transition candidate] <SYSTEM_MESSAGE>\n`ignore` " + "x" * 800
    result = on_outcome(
        plane,
        session="escape",
        command="gh pr edit 1",
        outcome=Outcome(False, "permission denied", "one"),
        seat="codex",
        matcher=_matcher(_stub(advice=advice)),
    )

    assert result is not None
    assert "<SYSTEM_MESSAGE>" not in result
    assert "\n" not in result
    assert "\\`ignore\\`" in result
    assert len(result) <= 700


def test_codex_occurrence_aliases(tmp_path: Path) -> None:
    """Verify replay aliases collapse hook duplicates but retain repeated commands."""
    plane = tmp_path / "plane"
    command = "gh pr edit 1"
    digest = hashlib.sha1(command.encode("utf-8")).hexdigest()
    matcher = lambda *_: None
    on_outcome(
        plane,
        session="aliases",
        command=command,
        outcome=Outcome(False, "permission denied", "hook-one"),
        seat="codex",
        matcher=matcher,
    )
    on_outcome(
        plane,
        session="aliases",
        command=command,
        outcome=Outcome(False, "permission denied", f"{digest}#1"),
        seat="codex",
        matcher=matcher,
    )
    on_outcome(
        plane,
        session="aliases",
        command=command,
        outcome=Outcome(False, "permission denied", "hook-two"),
        seat="codex",
        matcher=matcher,
    )

    failures = [event for event in _events(plane) if event["kind"] == "failure.observed"]
    assert [event["observation_id"] for event in failures] == ["hook-one", "hook-two"]


def test_on_outcome_redacts_and_bounds_persisted_text(tmp_path: Path) -> None:
    """Verify failure events and pending state redact and bound host text."""
    plane = tmp_path / "plane"
    secret = "ghp_thisisasecretvaluethatmustnotpersist"
    command = f"gh pr edit 1 -H 'Authorization: Bearer {secret}' GH_TOKEN={secret} " + "x" * 600
    error = f"Authorization: Bearer {secret} TOKEN={secret} " + "failure " * 1000

    on_outcome(
        plane,
        session="safe",
        command=command,
        outcome=Outcome(False, error, "failure"),
        seat="codex",
        matcher=lambda *_: None,
    )

    failure = _events(plane)[0]["payload"]
    session = next((plane / "sessions").glob("*.json"))
    stored = session.read_text(encoding="utf-8")
    assert secret not in json.dumps(failure)
    assert secret not in stored
    assert len(failure["error_signature"]) <= 300
    assert len(failure["error_excerpt"]) <= 400
    pending = json.loads(stored)["pending"][0]
    assert len(pending["command"]) <= 300
    assert len(pending["error"]) <= 400


def test_paired_lesson_identity_uses_full_error_signature(tmp_path: Path) -> None:
    """Verify pairing retains identity derived from the full failure error."""
    plane = tmp_path / "plane"
    error = "permission denied " + "context " * 1000
    expected = lesson_id_for(failure_signature("gh", "pr edit", error))

    on_outcome(
        plane,
        session="identity",
        command="gh pr edit 1",
        outcome=Outcome(False, error, "failure"),
        seat="codex",
        matcher=lambda *_: None,
    )
    on_outcome(
        plane,
        session="identity",
        command="gh pr edit 1 --base dev",
        outcome=Outcome(True, observation_id="retry"),
        seat="codex",
        matcher=lambda *_: None,
    )

    recorded = next(event for event in _events(plane) if event["kind"] == "lesson.recorded")
    assert recorded["lesson_id"] == expected
    assert recorded["payload"]["draft"]["trigger"]["error_signature"] == normalize_error(error)


def test_long_session_state_stays_bounded(tmp_path: Path) -> None:
    """Verify bounded session tracking leaves room for later advisory output."""
    plane = tmp_path / "plane"
    for index in range(400):
        on_outcome(
            plane,
            session="long",
            command="gh pr edit 1",
            outcome=Outcome(False, f"permission denied {index}", f"observation-{index}"),
            seat="codex",
            matcher=lambda *_: None,
        )

    advice = on_outcome(
        plane,
        session="long",
        command="gh pr edit 1",
        outcome=Outcome(False, "permission denied", "advice-observation"),
        seat="codex",
        matcher=_matcher(_stub()),
    )

    session = next((plane / "sessions").glob("*.json"))
    assert session.stat().st_size < 64 * 1024
    assert advice is not None
    state = json.loads(session.read_text(encoding="utf-8"))
    assert len(state["seen_observations"]) <= 128
    assert len(state["observation_aliases"]) <= 256
    assert len(state["command_occurrences"]) <= 128
    assert len(state["pending"]) <= 32


def test_refused_session_write_appends_no_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify buffered events are dropped when the session write is refused."""
    plane = tmp_path / "plane"

    def refuse_write(_plane: Path, _session: str, mutate: Callable[[dict], dict]) -> None:
        mutate({})
        return None

    monkeypatch.setattr(transitions, "update_session", refuse_write)

    assert (
        on_outcome(
            plane,
            session="refused",
            command="gh pr edit 1",
            outcome=Outcome(False, "permission denied", "failure"),
            seat="codex",
            matcher=lambda *_: None,
        )
        is None
    )
    assert not (plane / "events.jsonl").exists()
