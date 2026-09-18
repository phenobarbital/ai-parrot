"""S2 gate tests: fast single-process contract checks (always) + full multi-process matrix (PARROT_SPIKE_FULL=1)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from . import harness
from .sqlite_prototype import ReviewCommand, SQLiteEpisodeBackend
from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome, EpisodicMemory

FULL = os.environ.get("PARROT_SPIKE_FULL") == "1"


def _episode(**overrides) -> EpisodicMemory:
    defaults = dict(
        agent_id="agent-1",
        tenant_id="default",
        situation="user asked to summarize a report",
        action_taken="called summarize_tool",
        outcome=EpisodeOutcome.SUCCESS,
        category=EpisodeCategory.TOOL_EXECUTION,
        lesson_learned="always chunk long reports before summarizing",
    )
    defaults.update(overrides)
    return EpisodicMemory(**defaults)


@pytest.fixture
async def backend(tmp_path):
    be = SQLiteEpisodeBackend(tmp_path / "episodes.sqlite")
    await be.configure()
    yield be
    await be.close()


async def test_duplicate_review_is_duplicate(backend) -> None:
    episode = _episode()
    await backend.store(episode)
    command = ReviewCommand(
        outcome_id="outcome-1",
        outcome_revision=1,
        episode_id=episode.episode_id,
        grade=1,
        expected_apply_revision=0,
        new_state={"fsrs": {"stability": 1.0}},
    )

    first = await backend.apply_review(command)
    assert first.result == "applied"
    assert first.apply_revision == 1

    second = await backend.apply_review(command)
    assert second.result == "duplicate"
    # apply_revision is unchanged by the duplicate call.
    assert second.apply_revision == 1


async def test_stale_revision_rejected(backend) -> None:
    episode = _episode()
    await backend.store(episode)

    first_command = ReviewCommand(
        outcome_id="outcome-A",
        outcome_revision=1,
        episode_id=episode.episode_id,
        grade=1,
        expected_apply_revision=0,
        new_state={"fsrs": {"stability": 1.0}},
    )
    first = await backend.apply_review(first_command)
    assert first.result == "applied"
    assert first.apply_revision == 1

    # A second reviewer computed its expected revision against the same stale
    # snapshot (expected_apply_revision=0) instead of the just-applied one.
    stale_command = ReviewCommand(
        outcome_id="outcome-B",
        outcome_revision=1,
        episode_id=episode.episode_id,
        grade=2,
        expected_apply_revision=0,
        new_state={"fsrs": {"stability": 2.0}},
    )
    second = await backend.apply_review(stale_command)
    assert second.result == "stale_revision"
    # State still reflects only the first, accepted, application.
    assert second.apply_revision == 1


async def test_model_id_filter_before_top_k(backend) -> None:
    for i in range(3):
        await backend.store(
            _episode(
                embedding=[1.0, 0.0, 0.0],
                metadata={"model_id": "openai:gpt-4o"},
                situation=f"situation-a-{i}",
            )
        )
    for i in range(3):
        await backend.store(
            _episode(
                embedding=[1.0, 0.0, 0.0],
                metadata={"model_id": "anthropic:claude"},
                situation=f"situation-b-{i}",
            )
        )

    results = await backend.search_similar(
        embedding=[1.0, 0.0, 0.0],
        namespace_filter={"agent_id": "agent-1", "model_id": "openai:gpt-4o"},
        top_k=1,
        score_threshold=0.0,
    )
    assert len(results) == 1
    assert results[0].metadata["model_id"] == "openai:gpt-4o"

    count = await backend.count({"agent_id": "agent-1", "model_id": "anthropic:claude"})
    assert count == 3


async def test_imported_rows_survive_delete_expired(backend) -> None:
    imported = _episode(expires_at=None, metadata={"source": "feedback_import"})
    expired = _episode(expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    await backend.store(imported)
    await backend.store(expired)

    deleted = await backend.delete_expired()
    assert deleted == 1

    remaining = await backend.get_recent({"agent_id": "agent-1"}, limit=10)
    remaining_ids = {ep.episode_id for ep in remaining}
    assert imported.episode_id in remaining_ids
    assert expired.episode_id not in remaining_ids


async def test_lexical_search_without_embeddings(backend) -> None:
    target = _episode(
        situation="the deploy pipeline broke because of a missing kubeconfig secret",
        action_taken="rotated the kubeconfig secret",
        lesson_learned="always verify kubeconfig secret presence before a deploy",
    )
    distractor = _episode(situation="unrelated billing question", action_taken="answered billing FAQ")
    await backend.store(target)
    await backend.store(distractor)

    results = await backend.search_text("kubeconfig", namespace_filter={"agent_id": "agent-1"}, top_k=5)
    assert len(results) >= 1
    assert results[0].episode_id == target.episode_id
    for result in results:
        assert 0.0 <= result.score <= 1.0


@pytest.mark.skipif(not FULL, reason="set PARROT_SPIKE_FULL=1 to run the 8-process matrix and write REPORT.md")
def test_full_matrix_writes_report(tmp_path) -> None:
    results = [harness.run_workload(w, tmp_path) for w in harness.default_matrix()]
    harness.write_report(
        results,
        commands=[
            "PARROT_SPIKE_FULL=1 python3 -m pytest "
            "packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/test_s2_harness.py"
            "::test_full_matrix_writes_report -q > artifacts/logs/feat-571-s2-<ts>.log 2>&1"
        ],
    )
    # Only the sqlite arm is required to converge with zero lost writes — that IS the G2 gate.
    # The faiss arm is the comparison/control: its lost writes and non-convergence under concurrent
    # processes are the expected, documented evidence (spec §6 C5), not a test failure.
    for result in results:
        for arm_result in result["arms"].values():
            if arm_result.get("arm") == "sqlite":
                assert arm_result["lost_writes"] == 0
                assert arm_result["converged"] is True
