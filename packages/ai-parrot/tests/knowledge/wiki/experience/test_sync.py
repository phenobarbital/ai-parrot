"""Deterministic experience-memory synchronization regression tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from parrot.knowledge.wiki.experience import sync
from parrot.knowledge.wiki.experience.fastpath import append_event
from parrot.knowledge.wiki.experience.graduation import graduate
from parrot.knowledge.wiki.experience.index import ExperienceIndex
from parrot.knowledge.wiki.experience.models import LessonDraft, LessonTrigger, validate_event
from parrot.knowledge.wiki.experience.service import ExperienceService
from parrot.knowledge.wiki.ledger.service import LedgerService


def _event(
    kind: str,
    lesson_id: str,
    payload: dict[str, object],
    *,
    sequence: int,
    session: str | None = None,
) -> dict[str, object]:
    """Build one canonical event mapping with deterministic time."""
    event = validate_event(
        {
            "schema_version": 1,
            "event_id": "",
            "kind": kind,
            "lesson_id": lesson_id,
            "session": session or f"session-{sequence}",
            "actor": "agent:test",
            "ts": f"2026-11-13T12:{sequence // 60:02d}:{sequence % 60:02d}Z",
            "payload": payload,
        }
    )
    assert event is not None
    return event.model_dump(mode="json")


def _record(
    lesson_id: str,
    solution_rev: str,
    *,
    sequence: int,
    tier: str = "repo",
    solution: str = "Use the supported command.",
) -> dict[str, object]:
    """Build one canonical authored lesson definition."""
    return _event(
        "lesson.recorded",
        lesson_id,
        {
            "draft": {
                "trigger": {
                    "executable": "gh",
                    "subcommand": "pr edit",
                    "error_signature": f"project cards unsupported {lesson_id}",
                    "error_excerpt": "project cards unsupported",
                    "command_example": "gh pr edit 12 --base dev",
                },
                "symptom": "The command rejects project-card fields.",
                "solution": solution,
                "fix_example": "gh api graphql",
                "scope_paths": [],
            },
            "solution_rev": solution_rev,
            "tier": tier,
            "source": "authored",
        },
        sequence=sequence,
        session=f"record-{lesson_id}",
    )


def _append(plane: Path, *events: dict[str, object]) -> None:
    """Append canonical events to one repository plane."""
    for event in events:
        assert append_event(plane, event)


def _write_shared(path: Path, *events: dict[str, object]) -> None:
    """Write one immutable shared fixture file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for event in events
        ),
        encoding="utf-8",
    )


def _read_events(path: Path) -> list[dict[str, object]]:
    """Read exported JSONL fixture events."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _checkout(tmp_path: Path, name: str) -> tuple[Path, Path]:
    """Create an isolated primary checkout and repository plane."""
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    plane = root / ".parrot" / "experience"
    plane.mkdir(parents=True)
    return root, plane


def test_sync_global_moves_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Copy each global definition and its evidence once without changing IDs."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    _, plane = _checkout(tmp_path, "primary")
    global_definition = _record("pit-global", "rev-global", sequence=1, tier="global")
    global_evidence = _event(
        "lesson.validated",
        "pit-global",
        {"solution_rev": "rev-global", "via": "trigger_family"},
        sequence=2,
    )
    repo_definition = _record("pit-repo", "rev-repo", sequence=3)
    repo_evidence = _event(
        "lesson.validated",
        "pit-repo",
        {"solution_rev": "rev-repo", "via": "trigger_family"},
        sequence=4,
    )
    _append(plane, global_definition, global_evidence, repo_definition, repo_evidence)

    assert sync.sync_global(plane) == 2
    assert sync.sync_global(plane) == 0

    copied = _read_events(sync.global_plane_dir() / "events.jsonl")
    assert [event["event_id"] for event in copied] == [
        global_definition["event_id"],
        global_evidence["event_id"],
    ]


def test_export_shared_redacted_definitions_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Export redacted definitions and derived state, never raw evidence."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    root, plane = _checkout(tmp_path, "primary")
    lesson_id = "pit-redacted"
    solution_rev = "rev-redacted"
    definition = _record(
        lesson_id,
        solution_rev,
        sequence=1,
        solution="Use TOKEN=ghp_abcdefghijklmnop with the supported command.",
    )
    injected = _event(
        "lesson.injected",
        lesson_id,
        {"solution_rev": solution_rev, "state_at_injection": "candidate"},
        sequence=2,
    )
    validations = [
        _event(
            "lesson.validated",
            lesson_id,
            {"solution_rev": solution_rev, "via": "trigger_family"},
            sequence=sequence,
        )
        for sequence in (3, 4)
    ]
    refutation = _event(
        "lesson.refuted",
        lesson_id,
        {"solution_rev": solution_rev, "via": "trigger_family"},
        sequence=5,
    )
    _append(plane, definition, injected, *validations, refutation)

    exported = sync.export_shared(plane, root)

    assert exported is not None
    events = _read_events(exported)
    assert {event["kind"] for event in events} == {"lesson.recorded", "lesson.confirmed"}
    assert not ({"lesson.injected", "lesson.validated", "lesson.refuted"} & {event["kind"] for event in events})
    assert "ghp_abcdefghijklmnop" not in exported.read_text(encoding="utf-8")
    assert "[REDACTED]" in exported.read_text(encoding="utf-8")
    assert sync.shared_event_ids(root) == {event["event_id"] for event in events}
    assert sync.export_shared(plane, root) is None


@pytest.mark.asyncio
async def test_export_carries_quarantine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Export quarantine after confirmation so a fresh clone derives quarantine."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    root, plane = _checkout(tmp_path, "primary")
    lesson_id = "pit-quarantine"
    solution_rev = "rev-quarantine"
    definition = _record(lesson_id, solution_rev, sequence=1)
    validations = [
        _event(
            "lesson.validated",
            lesson_id,
            {"solution_rev": solution_rev, "via": "trigger_family"},
            sequence=sequence,
        )
        for sequence in (2, 3)
    ]
    _append(plane, definition, *validations)
    confirmed_export = sync.export_shared(plane, root)
    assert confirmed_export is not None
    confirmed_bytes = confirmed_export.read_bytes()

    refutations = [
        _event(
            "lesson.refuted",
            lesson_id,
            {"solution_rev": solution_rev, "via": "trigger_family"},
            sequence=sequence,
        )
        for sequence in (4, 5)
    ]
    _append(plane, *refutations)
    quarantined_export = sync.export_shared(plane, root)

    assert quarantined_export is not None
    assert quarantined_export != confirmed_export
    assert confirmed_export.read_bytes() == confirmed_bytes
    assert [event["kind"] for event in _read_events(quarantined_export)] == ["lesson.quarantined"]

    fresh, fresh_plane = _checkout(tmp_path, "fresh")
    for source in (root / sync.SHARED_DIR).glob("*.jsonl"):
        destination = fresh / sync.SHARED_DIR / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    index = ExperienceIndex(fresh_plane)
    assert await index.rebuild() == 1
    triggers = json.loads((fresh_plane / "triggers.json").read_text(encoding="utf-8"))
    assert triggers["gh"][0]["state"] == "quarantined"


def test_export_creates_new_file_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Create immutable incremental files and no file when no data remains."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    root, plane = _checkout(tmp_path, "primary")
    first_definition = _record("pit-first", "rev-first", sequence=1)
    _append(plane, first_definition)
    first_export = sync.export_shared(plane, root)
    assert first_export is not None
    first_bytes = first_export.read_bytes()

    second_definition = _record("pit-second", "rev-second", sequence=2)
    _append(plane, second_definition)
    second_export = sync.export_shared(plane, root)

    assert second_export is not None
    assert second_export != first_export
    assert first_export.read_bytes() == first_bytes
    assert [event["event_id"] for event in _read_events(second_export)] == [second_definition["event_id"]]
    assert sync.export_shared(plane, root) is None
    assert len(list((root / sync.SHARED_DIR).glob("*.jsonl"))) == 2

    empty_root, empty_plane = _checkout(tmp_path, "empty")
    assert sync.export_shared(empty_plane, empty_root) is None
    assert not (empty_root / sync.SHARED_DIR).exists()


def test_export_filename_is_content_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the canonical full-content digest as the immutable file name."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    first_root, first_plane = _checkout(tmp_path, "first")
    second_root, second_plane = _checkout(tmp_path, "second")
    definition = _record("pit-digest", "rev-digest", sequence=1)
    _append(first_plane, definition)
    _append(second_plane, definition)

    first_export = sync.export_shared(first_plane, first_root)
    second_export = sync.export_shared(second_plane, second_root)

    assert first_export is not None
    assert second_export is not None
    assert first_export.read_bytes() == second_export.read_bytes()
    expected = hashlib.sha256(first_export.read_bytes()).hexdigest()[:16]
    assert first_export.name == second_export.name == f"{expected}.jsonl"


def test_register_namespace_absolute(tmp_path: Path) -> None:
    """Register the primary absolute store from an external linked worktree."""
    primary = tmp_path / "primary"
    external = tmp_path / "external-worktree"
    gitdir = primary / ".git" / "worktrees" / "external"
    gitdir.mkdir(parents=True)
    external.mkdir()
    (external / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    config_path = primary / ".parrot" / "wiki.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "wiki_name": "preserved",
                "namespaces": {"other": {"store": "/srv/other"}},
                "custom": {"preserve": True},
            }
        ),
        encoding="utf-8",
    )

    assert sync.register_namespace(external)
    assert not sync.register_namespace(external)

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["wiki_name"] == "preserved"
    assert config["custom"] == {"preserve": True}
    assert config["namespaces"]["other"] == {"store": "/srv/other"}
    assert config["namespaces"]["experience"] == {"store": str((primary / ".parrot" / "experience").resolve())}


@pytest.mark.asyncio
async def test_export_carries_graduation_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Preserve the deterministic issue identity and owning ledger from graduate."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    root, plane = _checkout(tmp_path, "primary")
    service = ExperienceService.from_root(root)
    ledger = LedgerService.from_dir(root / ".parrot" / "ledger")
    lesson_id = await service.record(
        LessonDraft(
            trigger=LessonTrigger(
                executable="gh",
                subcommand="pr edit",
                error_signature="project cards unsupported graduation",
            ),
            symptom="The command rejects project-card fields.",
            solution="Use the supported command.",
            fix_example="gh api graphql",
            scope_paths=["src/release.py"],
        ),
        session="recording",
        source="authored",
    )
    assert lesson_id
    await service.refresh()
    lesson = await service.get_lesson(lesson_id)
    assert lesson is not None
    confirmation = _event(
        "lesson.confirmed",
        lesson.lesson_id,
        {"solution_rev": lesson.solution_rev},
        sequence=1,
        session="review",
    )
    _write_shared(root / sync.SHARED_DIR / "reviewed.jsonl", confirmation)
    for sequence in range(service.config.graduate_hits):
        _append(
            plane,
            _event(
                "lesson.injected",
                lesson.lesson_id,
                {"solution_rev": lesson.solution_rev, "state_at_injection": "confirmed"},
                sequence=10 + sequence,
                session=f"hit-{sequence % service.config.graduate_sessions}",
            ),
        )
    await service.refresh()

    assert await graduate(service, ledger, ledger_name=root.name) == [lesson.lesson_id]
    await service.refresh()
    graduated_lesson = await service.get_lesson(lesson.lesson_id)
    assert graduated_lesson is not None
    assert graduated_lesson.issue_id

    exported = sync.export_shared(plane, root)
    assert exported is not None
    graduated_events = [event for event in _read_events(exported) if event["kind"] == "lesson.graduated"]
    assert len(graduated_events) == 1
    assert graduated_events[0]["payload"] == {
        "solution_rev": graduated_lesson.solution_rev,
        "issue_id": graduated_lesson.issue_id,
        "ledger": root.name,
    }
