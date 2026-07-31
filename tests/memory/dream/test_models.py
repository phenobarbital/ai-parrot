"""Unit tests for parrot.memory.dream.models (TASK-1983)."""
from parrot.memory.dream import (
    DistilledKnowledge,
    DreamConfig,
    DreamCycleReport,
    DreamState,
    load_state,
    save_state,
)


def test_dream_config_defaults():
    cfg = DreamConfig()
    assert cfg.importance_threshold == 5
    assert cfg.max_groups_per_cycle == 20
    assert cfg.org_promotion_cycles == 3
    assert cfg.similarity_threshold == 0.75
    assert cfg.distill_model == "gemini-3.1-flash-lite"
    assert cfg.startup_jitter_seconds == 60
    assert cfg.failure_backoff_divisor == 4


def test_dream_state_roundtrip(tmp_path):
    state = DreamState(
        agent_id="a1", cycles_completed=2, reinforcement_counts={"mem-abc": 1}
    )
    path = tmp_path / "dream_state.json"
    save_state(state, path)
    loaded = load_state(path, agent_id="a1")
    assert loaded == state


def test_load_state_missing_file(tmp_path):
    loaded = load_state(tmp_path / "nope.json", agent_id="a1")
    assert loaded.agent_id == "a1"
    assert loaded.cycles_completed == 0


def test_load_state_corrupt_file(tmp_path):
    path = tmp_path / "dream_state.json"
    path.write_text("{not json", encoding="utf-8")
    loaded = load_state(path, agent_id="a1")
    assert loaded.agent_id == "a1"


def test_save_state_atomic_no_tmp_leftover(tmp_path):
    state = DreamState(agent_id="a2")
    path = tmp_path / "dream_state.json"
    save_state(state, path)
    assert path.exists()
    assert not (tmp_path / "dream_state.json.tmp").exists()


def test_distilled_knowledge_defaults():
    dk = DistilledKnowledge(title="t", body="b")
    assert dk.category == "lesson"
    assert dk.confidence == 0.5


def test_dream_cycle_report_defaults():
    from datetime import UTC, datetime

    report = DreamCycleReport(started_at=datetime.now(UTC))
    assert report.episodes_collected == 0
    assert report.pages_written == []
    assert report.aborted is False
