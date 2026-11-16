"""Behavioral acceptance tests for Atomic review commit, concurrency and replay."""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Empty
from typing import Any

import pytest

from parrot.memory.dynamics.export import ExportError, export_reviews
from parrot.memory.dynamics.models import ReviewCommand, ReviewReceipt
from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.episodic.models import EpisodicMemory, MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore


def _episode(episode_id: str, *, expires_at: datetime | None = None) -> EpisodicMemory:
    """Build one deterministic episode for an isolated database."""
    return EpisodicMemory(
        episode_id=episode_id,
        tenant_id="tenant-a",
        agent_id="agent-a",
        user_id="user-a",
        session_id="session-a",
        situation=f"Situation for {episode_id}",
        action_taken="completed the action",
        outcome="success",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        expires_at=expires_at,
    )


def _command(
    episode_id: str,
    *,
    outcome_id: str,
    outcome_revision: int = 0,
    expected_revision: int = 0,
    exposure_id: str = "exposure-a",
) -> ReviewCommand:
    """Build a validated runtime review command without synthetic evidence."""
    scope = {
        "tenant_id": "tenant-a",
        "agent_id": "agent-a",
        "user_id": "user-a",
        "session_id": "session-a",
        "turn_id": "turn-a",
        "identity_provenance": "runtime_derived",
    }
    return ReviewCommand.model_validate(
        {
            "ref": {
                "namespace": {
                    "tenant_id": "tenant-a",
                    "agent_id": "agent-a",
                    "user_id": "user-a",
                    "session_id": "session-a",
                },
                "kind": "episode",
                "memory_id": episode_id,
                "content_version": "v1",
            },
            "signal": {
                "outcome_id": outcome_id,
                "outcome_revision": outcome_revision,
                "observed_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
                "scope": scope,
                "evidence_ref": "coder-review/v1/execution/task/attempt",
                "source": "coder_engine",
                "outcome": "success",
                "first_attempt": True,
                "correction_count": 0,
                "passed_check_ids": ("storage-check",),
            },
            "exposure_id": exposure_id,
            "expected_revision": expected_revision,
        }
    )


async def _seed(path: Path, episodes: list[EpisodicMemory]) -> None:
    """Create the database and persist the requested episodes before workers start."""
    backend = SQLiteEpisodeBackend(path)
    await backend.configure()
    try:
        for episode in episodes:
            await backend.store(episode)
    finally:
        await backend.close()


def _apply_in_child(path: str, command_data: dict[str, Any], result_queue: Any) -> None:
    """Apply one command in a fresh process and return only its serializable receipt."""

    async def _run() -> None:
        backend = SQLiteEpisodeBackend(Path(path))
        await backend.configure()
        try:
            receipt = await backend.apply_review(ReviewCommand.model_validate(command_data))
            result_queue.put(receipt.model_dump(mode="json"))
        finally:
            await backend.close()

    try:
        asyncio.run(_run())
    except BaseException as exc:  # pragma: no cover - surfaced by the parent assertion
        result_queue.put({"error": repr(exc)})
        raise


def _run_processes(path: Path, commands: list[ReviewCommand]) -> list[ReviewReceipt]:
    """Run independent backend instances concurrently and collect their receipts."""
    context = mp.get_context("spawn")
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_apply_in_child,
            args=(str(path), command.model_dump(mode="json"), result_queue),
        )
        for command in commands
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(30)
        assert process.exitcode == 0

    results: list[ReviewReceipt] = []
    for _ in processes:
        try:
            result = result_queue.get(timeout=5)
        except Empty as exc:  # pragma: no cover - diagnostic guard for a crashed child
            raise AssertionError("review worker did not return a receipt") from exc
        assert "error" not in result, result
        results.append(ReviewReceipt.model_validate(result))
    return results


@pytest.mark.asyncio
async def test_eight_process_zero_loss(tmp_path: Path) -> None:
    """Verify eight isolated processes preserve unique writes and converge duplicates/CAS."""
    path = tmp_path / "eight-process.sqlite"
    episodes = [_episode(f"episode-{index}") for index in range(8)]
    episodes.extend([_episode("episode-duplicate"), _episode("episode-cas")])
    await _seed(path, episodes)

    unique = _run_processes(
        path,
        [_command(episode.episode_id, outcome_id=f"outcome-{index}") for index, episode in enumerate(episodes[:8])],
    )
    assert [receipt.status for receipt in unique] == ["applied"] * len(episodes[:8])

    duplicate_command = _command("episode-duplicate", outcome_id="same-outcome")
    duplicate = _run_processes(path, [duplicate_command] * 8)
    assert sorted(receipt.status for receipt in duplicate) == ["applied"] + ["duplicate"] * 7

    cas = _run_processes(
        path,
        [_command("episode-cas", outcome_id=f"cas-outcome-{index}", outcome_revision=index) for index in range(8)],
    )
    assert sorted(receipt.status for receipt in cas) == ["applied"] + ["stale_revision"] * 7

    backend = SQLiteEpisodeBackend(path)
    await backend.configure()
    try:
        assert await backend.count({"tenant_id": "tenant-a"}) == 10
        cursor = await backend._db.execute("SELECT COUNT(*) FROM reviews")
        assert (await cursor.fetchone())[0] == 10
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_duplicate_and_payload_conflict(tmp_path: Path) -> None:
    """Verify duplicate, payload conflict and pre-commit rollback semantics."""
    path = tmp_path / "dedupe.sqlite"
    await _seed(path, [_episode("episode-1"), _episode("episode-2")])
    backend = SQLiteEpisodeBackend(path)
    await backend.configure()
    try:
        command = _command("episode-1", outcome_id="outcome-1")
        first = await backend.apply_review(command)
        duplicate = await backend.apply_review(command)
        conflict = await backend.apply_review(_command("episode-1", outcome_id="outcome-1", exposure_id="other"))
        assert first.status == "applied"
        assert duplicate.status == "duplicate"
        assert conflict.status == "conflict"

        assert backend._db is not None
        await backend._db.execute(
            "CREATE TRIGGER reject_review BEFORE INSERT ON reviews "
            "WHEN NEW.outcome_id = 'rollback' BEGIN SELECT RAISE(ABORT, 'forced review failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="forced review failure"):
            await backend.apply_review(_command("episode-2", outcome_id="rollback"))
        cursor = await backend._db.execute("SELECT COUNT(*) FROM reviews WHERE outcome_id = 'rollback'")
        assert (await cursor.fetchone())[0] == 0
        await backend._db.execute("DROP TRIGGER reject_review")
        assert (await backend.apply_review(_command("episode-2", outcome_id="rollback"))).status == "applied"
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_crash_before_and_after_commit(tmp_path: Path) -> None:
    """Verify rollback before commit and duplicate replay after a lost acknowledgement."""
    path = tmp_path / "crash-replay.sqlite"
    await _seed(path, [_episode("episode-1")])
    backend = SQLiteEpisodeBackend(path)
    await backend.configure()
    try:
        command = _command("episode-1", outcome_id="crash-before-commit")
        assert backend._db is not None
        await backend._db.execute("BEGIN IMMEDIATE")
        await backend._db.execute(
            "INSERT INTO memory_state (ref_key, apply_revision, state, updated_at) VALUES (?, ?, ?, ?)",
            ("uncommitted", 1, "{}", "now"),
        )
        await backend.close()

        reopened = SQLiteEpisodeBackend(path)
        await reopened.configure()
        try:
            assert (await reopened.apply_review(command)).status == "applied"
            await reopened.close()
        finally:
            if reopened._db is not None:
                await reopened.close()

        replayed = SQLiteEpisodeBackend(path)
        await replayed.configure()
        try:
            receipt = await replayed.apply_review(command)
            assert receipt.status == "duplicate"
            assert receipt.apply_revision == 1
        finally:
            await replayed.close()
    finally:
        if backend._db is not None:
            await backend.close()


@pytest.mark.asyncio
async def test_archive_replay_after_export_failure(tmp_path: Path) -> None:
    """Verify review evidence remains replayable after episode TTL cleanup and export failure."""
    path = tmp_path / "archive.sqlite"
    expired = datetime.now(timezone.utc) - timedelta(days=1)
    await _seed(path, [_episode("episode-1", expires_at=expired)])
    command = _command("episode-1", outcome_id="archived-outcome")

    backend = SQLiteEpisodeBackend(path)
    await backend.configure()
    try:
        assert (await backend.apply_review(command)).status == "applied"
        # A real failed export (the destination directory does not exist) is reported and loses nothing.
        namespace = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a", user_id="user-a", session_id="session-a")
        store = EpisodicMemoryStore(backend, default_ttl_days=0)
        destination = path.parent / "missing-directory" / "reviews.json"
        with pytest.raises(ExportError):
            await export_reviews(namespace=namespace, destination=destination, store=store)
        assert not destination.exists()
        assert await backend.delete_expired() == 1
        cursor = await backend._db.execute("SELECT payload FROM reviews WHERE dedupe_key = ?", (command.dedupe_key,))
        row = await cursor.fetchone()
        assert row is not None
        archive = json.loads(row[0])
        assert archive["signal"]["evidence_ref"] == "coder-review/v1/execution/task/attempt"
        # Once the destination is usable, the same committed review is exported after the TTL cleanup.
        exported = destination.parent
        exported.mkdir()
        result = await export_reviews(namespace=namespace, destination=destination, store=store)
        assert result["record_count"] == 1
        assert json.loads(destination.read_text(encoding="utf-8"))["reviews"][0]["dedupe_key"] == command.dedupe_key
    finally:
        await backend.close()

    reopened = SQLiteEpisodeBackend(path)
    await reopened.configure()
    try:
        assert (await reopened.apply_review(command)).status == "duplicate"
    finally:
        await reopened.close()
