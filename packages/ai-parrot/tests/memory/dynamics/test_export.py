"""Behavioral acceptance tests for committed review export archives."""

from __future__ import annotations

import json
import os
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from parrot.memory.dynamics import export as export_module
from parrot.memory.dynamics.cli import register_memory_commands
from parrot.memory.dynamics.export import ExportError, export_reviews
from parrot.memory.dynamics.models import Grade, MemoryParameters, ReviewCommand
from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.episodic.models import EpisodicMemory, MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore

_CLOCK = datetime(2026, 1, 3, tzinfo=timezone.utc)
_PARAMETERS = MemoryParameters(
    algorithm="fsrs-6",
    time_policy="days-v1",
    parameter_id="episodic-neutral-v1",
    provenance="test-export",
)


def _namespace(*, tenant_id: str = "tenant-a") -> MemoryNamespace:
    """Build a stable namespace for one isolated test store."""
    return MemoryNamespace(tenant_id=tenant_id, agent_id="agent-a", user_id="user-a", session_id="session-a")


def _episode(namespace: MemoryNamespace, episode_id: str = "episode-a") -> EpisodicMemory:
    """Build an episode which a real review command can reference."""
    return EpisodicMemory(
        episode_id=episode_id,
        tenant_id=namespace.tenant_id,
        agent_id=namespace.agent_id,
        user_id=namespace.user_id,
        session_id=namespace.session_id,
        room_id=namespace.room_id,
        crew_id=namespace.crew_id,
        model_id=namespace.model_id,
        situation="Validate the archive",
        action_taken="Ran the scoped test",
        outcome="success",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _command(
    namespace: MemoryNamespace,
    *,
    outcome_id: str,
    expected_revision: int,
    episode_id: str = "episode-a",
) -> ReviewCommand:
    """Build a validated durable review command for the seeded episode."""
    return ReviewCommand.model_validate(
        {
            "ref": {
                "namespace": namespace.model_dump(mode="json"),
                "kind": "episode",
                "memory_id": episode_id,
                "content_version": "v1",
            },
            "signal": {
                "outcome_id": outcome_id,
                "outcome_revision": 0,
                "observed_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
                "scope": {
                    **namespace.model_dump(mode="json"),
                    "turn_id": "turn-a",
                    "identity_provenance": "runtime_derived",
                },
                "evidence_ref": f"coder-review/v1/execution/task/{outcome_id}",
                "source": "coder_engine",
                "outcome": "success",
                "first_attempt": True,
                "correction_count": 0,
                "passed_check_ids": ("export-check",),
            },
            "exposure_id": f"exposure-{outcome_id}",
            "expected_revision": expected_revision,
        }
    )


async def _seed_store(path: Path, namespace: MemoryNamespace) -> tuple[SQLiteEpisodeBackend, EpisodicMemoryStore]:
    """Create a real SQLite store with two committed reviews of one memory version."""
    backend = SQLiteEpisodeBackend(path)
    await backend.configure()
    await backend.store(_episode(namespace))
    assert (
        await backend.apply_review(
            _command(namespace, outcome_id="outcome-a", expected_revision=0),
            grade=Grade.GOOD,
            parameters=_PARAMETERS,
        )
    ).status == "applied"
    assert (
        await backend.apply_review(
            _command(namespace, outcome_id="outcome-b", expected_revision=1),
            grade=Grade.GOOD,
            parameters=_PARAMETERS,
        )
    ).status == "applied"
    return backend, EpisodicMemoryStore(backend, default_ttl_days=0)


@pytest.mark.asyncio
async def test_two_reviews_same_version_survive_and_export_is_deterministic(tmp_path: Path) -> None:
    """Export both committed outcomes in stable backend order with an injected clock."""
    namespace = _namespace()
    backend, store = await _seed_store(tmp_path / "reviews.sqlite", namespace)
    try:
        first_path = tmp_path / "first.json"
        second_path = tmp_path / "second.json"
        first = await export_reviews(namespace=namespace, destination=first_path, store=store, clock=lambda: _CLOCK)
        second = await export_reviews(namespace=namespace, destination=second_path, store=store, clock=lambda: _CLOCK)

        archive = json.loads(first_path.read_text(encoding="utf-8"))
        assert first_path.read_bytes() == second_path.read_bytes()
        assert first["content_hash"] == second["content_hash"]
        assert first["record_count"] == 2
        assert [review["command"]["signal"]["outcome_id"] for review in archive["reviews"]] == [
            "outcome-a",
            "outcome-b",
        ]
        assert archive["exported_at"] == _CLOCK.isoformat()
        assert archive["provenance"] == {
            "backend": "SQLiteEpisodeBackend",
            "table": "reviews",
            "persisted_fields": ["command", "apply_revision", "recorded_at"],
            "optional_record_fields": [
                "grade",
                "before",
                "after",
                "parameter_id",
                "memory_error_signature",
            ],
        }
        assert [review["record"]["parameter_id"] for review in archive["reviews"]] == [
            "episodic-neutral-v1",
            "episodic-neutral-v1",
        ]

        real_clock_path = tmp_path / "real-clock.json"
        before = datetime.now(timezone.utc)
        await export_reviews(namespace=namespace, destination=real_clock_path, store=store)
        after = datetime.now(timezone.utc)
        exported_at = datetime.fromisoformat(json.loads(real_clock_path.read_text(encoding="utf-8"))["exported_at"])
        assert exported_at.tzinfo is not None
        assert before <= exported_at <= after
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_scope_excludes_other_namespace_and_archive_replays_without_double_apply(tmp_path: Path) -> None:
    """Replay validated archived commands into a fresh store without changing the source."""
    namespace = _namespace()
    other_namespace = _namespace(tenant_id="tenant-b")
    backend, store = await _seed_store(tmp_path / "source.sqlite", namespace)
    try:
        await backend.store(_episode(other_namespace, episode_id="other-episode"))
        assert (
            await backend.apply_review(
                _command(other_namespace, outcome_id="other", expected_revision=0, episode_id="other-episode")
            )
        ).status == "applied"
        destination = tmp_path / "archive.json"
        await export_reviews(namespace=namespace, destination=destination, store=store, clock=lambda: _CLOCK)
        archive = json.loads(destination.read_text(encoding="utf-8"))
        assert len(archive["reviews"]) == 2
        commands = [ReviewCommand.model_validate(review["command"]) for review in archive["reviews"]]
        assert all("record" in review for review in archive["reviews"])
        stripped_archive = json.loads(json.dumps(archive))
        for review in stripped_archive["reviews"]:
            review.pop("record")
        stripped_commands = [ReviewCommand.model_validate(review["command"]) for review in stripped_archive["reviews"]]

        replay_backend = SQLiteEpisodeBackend(tmp_path / "replay.sqlite")
        await replay_backend.configure()
        try:
            await replay_backend.store(_episode(namespace))
            receipts = [await replay_backend.apply_review(command) for command in commands]
            assert [receipt.status for receipt in receipts] == ["applied", "applied"]
            assert [receipt.apply_revision for receipt in receipts] == [1, 2]
            assert [(await backend.apply_review(command)).status for command in commands] == ["duplicate", "duplicate"]
            replay_export = await export_reviews(
                namespace=namespace,
                destination=tmp_path / "replay.json",
                store=EpisodicMemoryStore(replay_backend, default_ttl_days=0),
                clock=lambda: _CLOCK,
            )
            assert replay_export["record_count"] == 2
            replay_archive = json.loads((tmp_path / "replay.json").read_text(encoding="utf-8"))
            assert [review["dedupe_key"] for review in replay_archive["reviews"]] == [
                review["dedupe_key"] for review in archive["reviews"]
            ]
            assert all("record" not in review for review in replay_archive["reviews"])
        finally:
            await replay_backend.close()

        stripped_backend = SQLiteEpisodeBackend(tmp_path / "stripped-replay.sqlite")
        await stripped_backend.configure()
        try:
            await stripped_backend.store(_episode(namespace))
            stripped_receipts = [await stripped_backend.apply_review(command) for command in stripped_commands]
            assert [receipt.status for receipt in stripped_receipts] == ["applied", "applied"]
            assert [receipt.apply_revision for receipt in stripped_receipts] == [1, 2]
        finally:
            await stripped_backend.close()
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_write_failure_leaves_store_and_directory_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed atomic replace keeps durable reviews and removes the unique temporary file."""
    namespace = _namespace()
    backend, store = await _seed_store(tmp_path / "reviews.sqlite", namespace)
    destination = tmp_path / "archive.json"
    try:
        original_replace = os.replace

        def fail_replace(source: Path, target: Path) -> None:
            raise OSError("replace failed")

        monkeypatch.setattr(export_module.os, "replace", fail_replace)
        with pytest.raises(ExportError, match="replace failed"):
            await export_reviews(namespace=namespace, destination=destination, store=store, clock=lambda: _CLOCK)
        assert not list(tmp_path.glob(".archive.json.*.tmp"))
        assert len(await store.list_reviews(namespace)) == 2

        monkeypatch.setattr(export_module.os, "replace", original_replace)
        result = await export_reviews(namespace=namespace, destination=destination, store=store, clock=lambda: _CLOCK)
        assert result["record_count"] == 2
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_missing_or_incapable_store_fails_without_writing(tmp_path: Path) -> None:
    """Never create a placeholder archive when review listing is unavailable."""
    namespace = _namespace()
    destination = tmp_path / "archive.json"
    with pytest.raises(ValueError, match="configured episodic store"):
        await export_reviews(namespace=namespace, destination=destination)
    incapable_store = EpisodicMemoryStore(object())
    with pytest.raises(RuntimeError, match="has no list_reviews capability"):
        await export_reviews(namespace=namespace, destination=destination, store=incapable_store)
    assert not destination.exists()


@pytest.mark.asyncio
async def test_legacy_reviews_export_without_a_fabricated_record(tmp_path: Path) -> None:
    """Legacy direct review calls remain replayable and omit record metadata."""
    namespace = _namespace()
    backend = SQLiteEpisodeBackend(tmp_path / "legacy.sqlite")
    await backend.configure()
    try:
        await backend.store(_episode(namespace))
        assert (
            await backend.apply_review(_command(namespace, outcome_id="legacy", expected_revision=0))
        ).status == "applied"
        destination = tmp_path / "legacy.json"
        await export_reviews(
            namespace=namespace,
            destination=destination,
            store=EpisodicMemoryStore(backend, default_ttl_days=0),
            clock=lambda: _CLOCK,
        )
        assert "record" not in json.loads(destination.read_text(encoding="utf-8"))["reviews"][0]
    finally:
        await backend.close()


def test_cli_exports_store_contents(tmp_path: Path) -> None:
    """The Click command opens the configured real store and exports its committed reviews."""
    namespace = _namespace()
    database_path = tmp_path / "reviews.sqlite"

    async def seed() -> None:
        backend, _ = await _seed_store(database_path, namespace)
        await backend.close()

    asyncio.run(seed())
    root = click.Group()
    register_memory_commands(root)
    output = tmp_path / "cli.json"
    result = CliRunner().invoke(
        root,
        [
            "memory",
            "--storage-path",
            str(database_path),
            "--tenant-id",
            namespace.tenant_id,
            "--agent-id",
            namespace.agent_id,
            "--user-id",
            namespace.user_id or "",
            "--session-id",
            namespace.session_id or "",
            "export-reviews",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    cli_archive = json.loads(output.read_text(encoding="utf-8"))
    assert cli_archive["reviews"]

    async def library_export() -> dict[str, object]:
        backend = SQLiteEpisodeBackend(database_path)
        await backend.configure()
        try:
            library_output = tmp_path / "library.json"
            await export_reviews(
                namespace=namespace,
                destination=library_output,
                store=EpisodicMemoryStore(backend, default_ttl_days=0),
                clock=lambda: _CLOCK,
            )
            return json.loads(library_output.read_text(encoding="utf-8"))
        finally:
            await backend.close()

    assert cli_archive["reviews"] == asyncio.run(library_export())["reviews"]
