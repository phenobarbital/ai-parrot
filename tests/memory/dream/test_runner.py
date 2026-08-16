"""Unit tests for DreamCycleRunner (TASK-1986)."""
import json
import sys
from datetime import UTC, datetime, timedelta

import pytest

# Worktree environment gotcha (unrelated to this task, see TASK-1985's
# completion note): force a fresh re-import of the FAISS backend so a
# stale `_FAISS_AVAILABLE=False` cached during an earlier conftest.py
# import race doesn't poison this test module.
sys.modules.pop("parrot.memory.episodic.backends.faiss", None)

from parrot.memory.dream import BrainStore, DreamConfig, DreamCycleRunner, DreamState
from parrot.memory.episodic.backends.faiss import FAISSBackend
from parrot.memory.episodic.models import (
    EpisodeCategory,
    EpisodeOutcome,
    EpisodicMemory,
    MemoryNamespace,
)
from parrot.memory.episodic.store import EpisodicMemoryStore


def _make_episode(**overrides) -> EpisodicMemory:
    defaults = {
        "agent_id": "test-agent",
        "situation": "did a thing",
        "action_taken": "did it",
        "outcome": EpisodeOutcome.SUCCESS,
        "importance": 1,
    }
    defaults.update(overrides)
    return EpisodicMemory(**defaults)


class FakeEmbeddingProvider:
    """Deterministic embedding stub: text containing "GROUP_A" -> [1, 0],
    everything else -> [0, 1]."""

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "GROUP_A" in t else [0.0, 1.0] for t in texts]


class BrokenEmbeddingProvider:
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding backend unavailable")


class StubLLMClient:
    """Returns a canned response shaped like an AIMessage with .response text."""

    def __init__(self, response_text: str):
        self._response_text = response_text

    async def ask(self, **kwargs):
        return _FakeAIMessage(self._response_text)


class _FakeAIMessage:
    def __init__(self, text: str):
        self.response = text
        self.to_text = text


class FlakyLLMClient:
    """Fails distill on the first call (malformed JSON), succeeds after."""

    def __init__(self) -> None:
        self.call_count = 0

    async def ask(self, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            return _FakeAIMessage("not json")
        return _FakeAIMessage(
            json.dumps(
                {"title": "T2", "body": "B2", "category": "lesson", "confidence": 0.9}
            )
        )


@pytest.fixture
def namespace() -> MemoryNamespace:
    return MemoryNamespace(agent_id="test-agent")


@pytest.fixture
def backend() -> FAISSBackend:
    return FAISSBackend(dimension=4)


@pytest.fixture
def episodic_store(backend) -> EpisodicMemoryStore:
    return EpisodicMemoryStore(backend=backend)


@pytest.fixture
def brain(tmp_path) -> BrainStore:
    return BrainStore(tmp_path / "brain", wiki_name="brain-test-agent")


async def _seed(backend: FAISSBackend, episodes: list[EpisodicMemory]) -> None:
    for ep in episodes:
        await backend.store(ep)


class TestCollect:
    async def test_eligibility_threshold_or_lesson(self, episodic_store, backend, namespace, brain):
        low_no_lesson = _make_episode(importance=1, lesson_learned=None)
        low_with_lesson = _make_episode(importance=1, lesson_learned="learned it")
        high_no_lesson = _make_episode(importance=8, lesson_learned=None)
        await _seed(backend, [low_no_lesson, low_with_lesson, high_no_lesson])

        runner = DreamCycleRunner(episodic_store, brain, namespace)
        collected = await runner._collect(DreamState(agent_id="test-agent"))

        ids = {ep.episode_id for ep in collected}
        assert low_no_lesson.episode_id not in ids
        assert low_with_lesson.episode_id in ids
        assert high_no_lesson.episode_id in ids

    async def test_skips_consolidated(self, episodic_store, backend, namespace, brain):
        already_done = _make_episode(importance=8, metadata={"consolidated_into": "mem-x"})
        pending = _make_episode(importance=8)
        await _seed(backend, [already_done, pending])

        runner = DreamCycleRunner(episodic_store, brain, namespace)
        collected = await runner._collect(DreamState(agent_id="test-agent"))

        ids = {ep.episode_id for ep in collected}
        assert already_done.episode_id not in ids
        assert pending.episode_id in ids

    async def test_respects_watermark(self, episodic_store, backend, namespace, brain):
        old = _make_episode(importance=8, created_at=datetime.now(UTC) - timedelta(days=2))
        new = _make_episode(importance=8, created_at=datetime.now(UTC))
        await _seed(backend, [old, new])

        watermark = datetime.now(UTC) - timedelta(days=1)
        runner = DreamCycleRunner(episodic_store, brain, namespace)
        collected = await runner._collect(DreamState(agent_id="test-agent", last_run=watermark))

        ids = {ep.episode_id for ep in collected}
        assert old.episode_id not in ids
        assert new.episode_id in ids


class TestCluster:
    async def test_groups_by_embedding_similarity(self, namespace, brain):
        fake_store = EpisodicMemoryStore(
            backend=FAISSBackend(dimension=4), embedding_provider=FakeEmbeddingProvider()
        )
        runner = DreamCycleRunner(fake_store, brain, namespace)
        eps = [
            _make_episode(situation="GROUP_A case one", lesson_learned="l1"),
            _make_episode(situation="GROUP_A case two", lesson_learned="l2"),
            _make_episode(situation="other case", lesson_learned="l3"),
        ]
        groups = await runner._cluster(eps)
        assert len(groups) == 2
        sizes = sorted(len(g) for g in groups)
        assert sizes == [1, 2]

    async def test_fallback_category_grouping(self, episodic_store, namespace, brain):
        runner = DreamCycleRunner(episodic_store, brain, namespace)
        eps = [
            _make_episode(category=EpisodeCategory.TOOL_EXECUTION, related_tools=["jira"]),
            _make_episode(category=EpisodeCategory.TOOL_EXECUTION, related_tools=["jira"]),
            _make_episode(category=EpisodeCategory.DECISION, related_tools=[]),
        ]
        groups = await runner._cluster(eps)
        assert len(groups) == 2
        sizes = sorted(len(g) for g in groups)
        assert sizes == [1, 2]

    async def test_group_cap_defers_excess(self, episodic_store, namespace, brain):
        config = DreamConfig(max_groups_per_cycle=2)
        runner = DreamCycleRunner(episodic_store, brain, namespace, config=config)
        eps = [
            _make_episode(category=EpisodeCategory.TOOL_EXECUTION, related_tools=[f"tool{i}"])
            for i in range(5)
        ]
        groups = await runner._cluster(eps)
        assert len(groups) == 5  # all formed
        assert len(groups[: config.max_groups_per_cycle]) == 2  # only 2 processed


class TestDistill:
    async def test_llm_json_contract(self, episodic_store, namespace, brain):
        canned = json.dumps(
            {"title": "T", "body": "B", "category": "lesson", "confidence": 0.9}
        )
        runner = DreamCycleRunner(
            episodic_store, brain, namespace, llm_client=StubLLMClient(canned)
        )
        group = [_make_episode(lesson_learned="l1")]
        result = await runner._distill(group)
        assert result.title == "T"
        assert result.confidence == 0.9

    async def test_malformed_json_skips_group(self, episodic_store, namespace, brain):
        runner = DreamCycleRunner(
            episodic_store, brain, namespace, llm_client=StubLLMClient("not json")
        )
        group = [_make_episode(lesson_learned="l1")]
        with pytest.raises(ValueError):
            await runner._distill(group)

    async def test_heuristic_fallback_no_llm(self, episodic_store, namespace, brain):
        runner = DreamCycleRunner(episodic_store, brain, namespace, llm_client=None)
        group = [_make_episode(lesson_learned="always check X")]
        result = await runner._distill(group)
        assert "always check X" in result.body
        assert result.category == "lesson"

    async def test_low_confidence_becomes_note(self, episodic_store, backend, namespace, brain):
        canned = json.dumps(
            {"title": "T", "body": "B", "category": "lesson", "confidence": 0.1}
        )
        runner = DreamCycleRunner(
            episodic_store, brain, namespace, llm_client=StubLLMClient(canned)
        )
        ep = _make_episode(importance=8, lesson_learned="l1")
        await _seed(backend, [ep])

        report = await runner.run_cycle(DreamState(agent_id="test-agent"))
        assert report.pages_written
        page = await brain._store.get_page(report.pages_written[0], include_body=False)
        assert page["category"] == "note"


class TestCycle:
    async def test_watermark_never_skips_a_failed_group(
        self, episodic_store, backend, namespace, brain
    ):
        """Regression (Codex review, FEAT-390): a later group succeeding must
        not advance the watermark past an earlier group that failed to
        distill — otherwise the failed group's episodes would never be
        retried, since future `_collect(since=...)` calls would exclude
        them."""
        t_old = datetime.now(UTC) - timedelta(hours=2)
        t_new = datetime.now(UTC) - timedelta(hours=1)
        old_ep = _make_episode(
            importance=8,
            category=EpisodeCategory.TOOL_EXECUTION,
            related_tools=["a"],
            created_at=t_old,
        )
        new_ep = _make_episode(
            importance=8,
            category=EpisodeCategory.DECISION,
            related_tools=[],
            created_at=t_new,
        )
        await _seed(backend, [old_ep, new_ep])

        flaky = FlakyLLMClient()
        runner = DreamCycleRunner(episodic_store, brain, namespace, llm_client=flaky)
        state = DreamState(agent_id="test-agent")
        report = await runner.run_cycle(state)

        assert report.groups_skipped == 1
        assert report.groups_distilled == 1
        assert state.last_run is not None
        assert state.last_run < t_old

    async def test_idempotent_two_runs(self, episodic_store, backend, namespace, brain):
        ep = _make_episode(importance=8, lesson_learned="always check X")
        await _seed(backend, [ep])

        runner = DreamCycleRunner(episodic_store, brain, namespace)
        state = DreamState(agent_id="test-agent")
        report1 = await runner.run_cycle(state)
        assert len(report1.pages_written) == 1

        report2 = await runner.run_cycle(state)
        assert report2.episodes_collected == 0
        assert report2.pages_written == []

    async def test_watermark_advances_to_newest_consolidated(self, episodic_store, backend, namespace, brain):
        t1 = datetime.now(UTC) - timedelta(hours=2)
        t2 = datetime.now(UTC) - timedelta(hours=1)
        ep1 = _make_episode(importance=8, lesson_learned="lesson1", created_at=t1)
        ep2 = _make_episode(importance=8, lesson_learned="lesson2", created_at=t2)
        await _seed(backend, [ep1, ep2])

        runner = DreamCycleRunner(episodic_store, brain, namespace)
        state = DreamState(agent_id="test-agent")
        await runner.run_cycle(state)

        assert state.last_run is not None
        assert abs((state.last_run - t2).total_seconds()) < 1

    async def test_promotion_after_n_cycles(self, episodic_store, backend, namespace, brain, tmp_path):
        org_brain = BrainStore(tmp_path / "org", wiki_name="org-test")
        config = DreamConfig(org_promotion_cycles=2)
        runner = DreamCycleRunner(
            episodic_store, brain, namespace, org_brain=org_brain, config=config
        )
        state = DreamState(agent_id="test-agent")

        for i in range(2):
            ep = _make_episode(
                importance=8,
                lesson_learned="always check X",
                situation="did a thing",
                action_taken="did it",
            )
            await backend.store(ep)
            report = await runner.run_cycle(state)

        assert report.pages_promoted
        assert state.promoted_pages

    async def test_store_failure_aborts_clean(self, episodic_store, backend, namespace):
        class BrokenBrain:
            async def remember(self, *a, **kw):
                raise RuntimeError("wiki store unavailable")

        ep = _make_episode(importance=8, lesson_learned="l1")
        await _seed(backend, [ep])

        runner = DreamCycleRunner(episodic_store, BrokenBrain(), namespace)
        state = DreamState(agent_id="test-agent")
        report = await runner.run_cycle(state)

        assert report.aborted is True
        assert state.last_run is None
