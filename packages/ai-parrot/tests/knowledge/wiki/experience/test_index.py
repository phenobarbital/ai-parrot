"""Deterministic experience-memory index regression tests."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from parrot.knowledge.wiki.experience.index import ExperienceIndex
from parrot.knowledge.wiki.experience.models import validate_event
from parrot.knowledge.wiki.project import WikiProjectConfig


def _record(event_id: str = "record") -> dict[str, object]:
    """Return a validated persisted recording event."""
    event = validate_event(
        {
            "schema_version": 1,
            "event_id": event_id,
            "kind": "lesson.recorded",
            "lesson_id": "pit-index",
            "session": "recording-session",
            "actor": "codex",
            "ts": "2026-11-13T12:00:00Z",
            "payload": {
                "draft": {
                    "trigger": {
                        "executable": "gh",
                        "subcommand": "pr edit",
                        "error_signature": "permission denied token",
                    },
                    "symptom": "Cannot edit a pull request.",
                    "solution": "Use the repository token.",
                    "fix_example": "gh pr edit 12 --base dev",
                },
                "solution_rev": "revision",
                "tier": "repo",
                "source": "authored",
            },
        }
    )
    assert event is not None
    return event.model_dump(mode="json")


def _confirmation() -> dict[str, object]:
    """Return a validated lifecycle attestation for the fixture lesson."""
    event = validate_event(
        {
            "schema_version": 1,
            "event_id": "confirmed",
            "kind": "lesson.confirmed",
            "lesson_id": "pit-index",
            "session": "review-session",
            "actor": "maintainer",
            "ts": "2026-11-13T12:01:00Z",
            "payload": {"solution_rev": "revision"},
        }
    )
    assert event is not None
    return event.model_dump(mode="json")


def _append(path: Path, *events: dict[str, object]) -> None:
    """Append fixture events as JSONL without introducing test-only parsers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events), encoding="utf-8")


@pytest.fixture
def plane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create an isolated primary checkout plane and global home."""
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    return primary / ".parrot" / "experience"


@pytest.mark.asyncio
async def test_index_rebuild_generation_publish(plane: Path) -> None:
    """Publish one complete generation and keep readers on the marked one."""
    _append(plane / "events.jsonl", _record())
    index = ExperienceIndex(plane)

    results = await asyncio.gather(index.rebuild(), index.rebuild())

    assert sorted(results) == [0, 1]
    marker = json.loads((plane / "index.json").read_text(encoding="utf-8"))
    assert (plane / "generations" / marker["generation"] / "wiki.db").is_file()
    assert "gh" in json.loads((plane / "triggers.json").read_text(encoding="utf-8"))
    fastpath = json.loads((plane / "fastpath.json").read_text(encoding="utf-8"))
    assert fastpath["inject_min_score"] == pytest.approx(0.35)
    assert (plane / "generations" / "interrupted").mkdir() is None
    assert [hit["concept_id"] for hit in await index.search("repository token")] == ["pit-index"]


@pytest.mark.asyncio
async def test_index_sources_union_dedup(plane: Path) -> None:
    """Deduplicate event identities while preserving trusted shared provenance."""
    primary = plane.parents[1]
    global_log = Path(os.environ["PARROT_HOME"]) / "experience" / "events.jsonl"
    shared_log = primary / "sdd" / "experience" / "lessons" / "definition.jsonl"
    record = _record()
    confirmation = _confirmation()
    _append(plane / "events.jsonl", record, confirmation)
    _append(global_log, record)
    _append(shared_log, record, confirmation)

    index = ExperienceIndex(plane)
    assert await index.rebuild() == 1

    triggers = json.loads((plane / "triggers.json").read_text(encoding="utf-8"))
    stub = triggers["gh"][0]
    assert stub["state"] == "confirmed"
    assert set(stub) == {
        "lesson_id",
        "state",
        "solution_rev",
        "executable",
        "subcommand",
        "error_tokens",
        "fix_executable",
        "fix_subcommand",
        "advice",
        "recording_session",
        "tier",
    }
    assert stub["recording_session"] == "recording-session"
    assert stub["tier"] == "repo"
    assert "metadata" not in triggers


@pytest.mark.asyncio
async def test_index_shared_provenance(plane: Path) -> None:
    """Mark only validated shared-directory lines as trusted attestations."""
    primary = plane.parents[1]
    _append(plane / "events.jsonl", _record(), _confirmation())
    _append(primary / "sdd" / "experience" / "lessons" / "confirmed.jsonl", _confirmation())

    index = ExperienceIndex(plane)
    assert await index.rebuild() == 1
    stub = json.loads((plane / "triggers.json").read_text(encoding="utf-8"))["gh"][0]
    assert stub["state"] == "confirmed"
    assert "&lt;" not in stub["advice"]
    assert WikiProjectConfig().experience.enabled is True


@pytest.mark.asyncio
async def test_index_source_removal_staleness(plane: Path) -> None:
    """Treat source deletion and source changes as stale-index conditions."""
    repo_log = plane / "events.jsonl"
    _append(repo_log, _record())
    index = ExperienceIndex(plane)
    assert await index.rebuild() == 1
    assert not index.is_stale()

    repo_log.unlink()
    assert index.is_stale()
