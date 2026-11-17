"""Gate L-S3 — deterministic directory lookup under 5 ms (FEAT-747 AC-22)."""

import statistics
import time
from pathlib import Path

from parrot.bots.abstract import AbstractBot
from parrot.registry import AgentRegistry
from parrot.roost import RoostAgentConfig


class _DummyBot(AbstractBot):
    """Minimal bot class used only for registration."""


def _registry(tmp_path: Path) -> AgentRegistry:
    """Register 1 000 synthetic agents plus the HR agent."""
    registry = AgentRegistry(agents_dir=tmp_path / "agents")
    for i in range(1_000):
        registry.register(
            f"synthetic-{i}",
            _DummyBot,
            roost=RoostAgentConfig(
                capabilities=[f"domain{i % 50}.area{i}.op"],
                categories=[f"domain{i % 50}.area{i}"],
                keywords=[f"kw{i}"],
            ),
        )
    registry.register(
        "hr",
        _DummyBot,
        roost=RoostAgentConfig(
            capabilities=["hr.people.salary"],
            categories=["hr.people"],
            keywords=["salary"],
            category_hashes={"hr.people": "hash-hr-people"},
            backing="deterministic",
        ),
    )
    return registry


def test_find_capability_salary_under_5ms(tmp_path: Path) -> None:
    """``find_capability('salary')`` returns HR with its category hash; median of 20 runs < 5 ms."""
    registry = _registry(tmp_path)
    durations: list[float] = []
    matches = []
    for _ in range(20):
        start = time.perf_counter()
        matches = registry.find_capability("salary")
        durations.append(time.perf_counter() - start)

    assert [m.agent_name for m in matches] == ["hr"]
    assert matches[0].category_hash == "hash-hr-people"
    assert statistics.median(durations) < 0.005
