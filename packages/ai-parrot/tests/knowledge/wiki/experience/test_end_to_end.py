"""Deterministic experience-memory regression tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.flows.dev_loop.experience import ExperienceInterceptor
from parrot.knowledge.wiki.experience.models import LessonDraft, LessonTrigger, validate_event
from parrot.knowledge.wiki.experience.service import ExperienceService


def _root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str = "primary") -> tuple[Path, Path]:
    """Create an isolated checkout and its repository experience plane."""
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    plane = root / ".parrot" / "experience"
    plane.mkdir(parents=True)
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    return root, plane


def _draft() -> LessonDraft:
    """Return the authored workaround for the motivating GitHub CLI failure."""
    return LessonDraft(
        trigger=LessonTrigger(
            executable="gh",
            subcommand="pr edit",
            error_signature="Projects classic is no longer supported",
            error_excerpt="Projects classic is no longer supported",
            command_example="gh pr edit 12 --base dev",
        ),
        symptom="The pull-request edit command rejects project fields.",
        solution="Use gh api -X PATCH for the same pull-request update.",
        fix_example="gh api -X PATCH repos/acme/widgets/pulls/12",
    )


async def _command(
    interceptor: ExperienceInterceptor,
    argv: list[str],
    *,
    ok: bool,
    error: str = "",
) -> list[str]:
    """Send one structured command result through the production interceptor."""
    return await interceptor.after(
        "run_command",
        {"argv": argv},
        {"ok": ok, "exit_code": 0 if ok else 1, "stderr": error},
    )


def _linked_worktree(primary: Path, external: Path) -> None:
    """Create a minimal linked-worktree git layout outside the primary checkout."""
    gitdir = primary / ".git" / "worktrees" / "external"
    gitdir.mkdir(parents=True)
    external.mkdir()
    (external / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_gh_pr_edit_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Promote an authored ``gh api`` workaround and retire it terminally."""
    root, plane = _root(tmp_path, monkeypatch)
    service = ExperienceService.from_root(root)

    session_a = ExperienceInterceptor(session="session-a", cwd=str(root), seat="nova")
    assert (
        await _command(session_a, ["gh", "pr", "edit", "12"], ok=False, error="Projects classic is no longer supported")
        == []
    )
    lesson_id = await service.record(_draft(), session="session-a", source="authored", seat="nova")
    assert lesson_id
    await service.refresh()
    candidate = await service.get_lesson(lesson_id)
    assert candidate is not None and candidate.state == "candidate"

    for session in ("session-b", "session-c"):
        interceptor = ExperienceInterceptor(session=session, cwd=str(root), seat="nova")
        advice = await _command(
            interceptor,
            ["gh", "pr", "edit", "12"],
            ok=False,
            error="Projects classic is no longer supported",
        )
        assert len(advice) == 1
        assert "candidate" in advice[0] and "Unverified note" in advice[0]
        assert (
            await _command(
                interceptor,
                ["gh", "api", "-X", "PATCH", "repos/acme/widgets/pulls/12"],
                ok=True,
            )
            == []
        )

    await service.refresh()
    confirmed = await service.get_lesson(lesson_id)
    assert confirmed is not None and confirmed.state == "confirmed"
    briefing = await service.brief("Update pull request", ["src/release.py"])
    assert lesson_id in briefing and "gh api -X PATCH" in briefing

    external = tmp_path / "external-worktree"
    _linked_worktree(root, external)
    session_d = ExperienceInterceptor(session="session-d", cwd=str(external), seat="nova")
    advice = await _command(
        session_d,
        ["gh", "pr", "edit", "12"],
        ok=False,
        error="Projects classic is no longer supported",
    )
    assert len(advice) == 1 and "confirmed" in advice[0]
    assert (plane / "events.jsonl").exists()

    await service.refresh()
    assert await service.retire(lesson_id, reason="The CLI supports project fields now.")
    await service.refresh()
    retired = await service.get_lesson(lesson_id)
    assert retired is not None and retired.state == "retired"
    assert (
        await service.match_failure("gh pr edit 12", "Projects classic is no longer supported", session="session-e")
        is None
    )


@pytest.mark.asyncio
async def test_shared_log_feeds_fresh_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Deduplicate shared definitions and honor a later shared quarantine."""
    source, source_plane = _root(tmp_path, monkeypatch, "source")
    source_service = ExperienceService.from_root(source)
    lesson_id = await source_service.record(_draft(), session="source-session", source="authored")
    assert lesson_id
    recorded = json.loads((source_plane / "events.jsonl").read_text(encoding="utf-8").splitlines()[0])
    solution_rev = recorded["payload"]["solution_rev"]
    confirmation = validate_event(
        {
            "schema_version": 1,
            "event_id": "",
            "kind": "lesson.confirmed",
            "lesson_id": lesson_id,
            "session": "maintainer-session",
            "actor": "maintainer",
            "ts": "2026-11-15T12:00:00Z",
            "payload": {"solution_rev": solution_rev},
        }
    )
    quarantine = validate_event(
        {
            "schema_version": 1,
            "event_id": "",
            "kind": "lesson.quarantined",
            "lesson_id": lesson_id,
            "session": "maintainer-session",
            "actor": "maintainer",
            "ts": "2026-11-15T12:01:00Z",
            "payload": {"solution_rev": solution_rev},
        }
    )
    assert confirmation is not None and quarantine is not None

    fresh, _ = _root(tmp_path, monkeypatch, "fresh")
    shared = fresh / "sdd" / "experience" / "lessons"
    shared.mkdir(parents=True)
    (shared / "definition.jsonl").write_text(
        "\n".join(
            json.dumps(event, sort_keys=True, separators=(",", ":"))
            for event in (recorded, confirmation.model_dump(mode="json"))
        )
        + "\n",
        encoding="utf-8",
    )
    (shared / "duplicate.jsonl").write_text(
        json.dumps(recorded, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    fresh_service = ExperienceService.from_root(fresh)
    await fresh_service.refresh()
    lessons = await fresh_service.list_lessons()
    assert len(lessons) == 1 and lessons[0].lesson_id == lesson_id and lessons[0].state == "confirmed"

    with (shared / "quarantine.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(quarantine.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n")
    await fresh_service.refresh()
    quarantined = await fresh_service.get_lesson(lesson_id)
    assert quarantined is not None and quarantined.state == "quarantined"
