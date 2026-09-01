"""Single-task collapse, deployment log and planner backend respect.

FEAT-486 TASK-2653 / spec §4 rows ``test_single_task_collapse``,
``test_multi_task_full_pool``, ``test_collapse_fallback_to_configured``,
``test_unreadable_index_degrades``, ``test_pool_deployment_info_log`` and
``test_planner_pool_respects_configured_backends``.

Fixtures deliberately mirror ``test_development_node.py``'s doubles
(``FakeDispatcher``, ``_write_index``) so the two modules stay readable
side by side; the pool path is driven through the real
``node.execute()`` rather than by poking private methods, so the
collapse decision is exercised where it actually runs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from parrot.flows.dev_loop.models import (
    DevAgentPoolConfig,
    DevAgentSpec,
    DevelopmentOutput,
    PlannerOutput,
    ResearchOutput,
)
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
from parrot.flows.dev_loop.nodes.planner import PlannerNode

TWO_SEATS = [
    DevAgentSpec(agent="nova", model="zai.glm-5"),
    DevAgentSpec(agent="nova", model="qwen.qwen3-coder-480b-a35b-v1:0"),
]


def _research(worktree_path: str, feat_id: str = "FEAT-486") -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-486",
        spec_path="sdd/specs/refactor-dev-flow.spec.md",
        feat_id=feat_id,
        branch_name="feat-486-refactor-dev-flow",
        worktree_path=worktree_path,
        log_excerpts=[],
    )


def _write_index(worktree_path: Path, feat_id: str, feature_slug: str, tasks: list) -> None:
    index_dir = worktree_path / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / f"{feature_slug}.json").write_text(
        json.dumps({"feature": feature_slug, "feature_id": feat_id, "tasks": tasks})
    )


class FakeDispatcher:
    """Fulfils the ``DevLoopCodeDispatcher`` Protocol; records calls."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, **_kw):
        task_id = getattr(brief, "task_id", None)
        self.calls.append((task_id, node_id, cwd))
        return DevelopmentOutput(
            files_changed=[f"{task_id}.py"],
            commit_shas=[f"sha-{task_id}"],
            summary=task_id or "",
        )


def _spec_recording_builder() -> tuple:
    """Return ``(builder, seen_specs)`` — one dispatcher per built spec."""
    seen: list[DevAgentSpec] = []

    def _builder(spec: DevAgentSpec):
        seen.append(spec)
        return FakeDispatcher(), object()

    return _builder, seen


def _planner_output(suggested: DevAgentPoolConfig | None) -> PlannerOutput:
    return PlannerOutput(
        spec_path="sdd/specs/refactor-dev-flow.spec.md",
        task_index_path="sdd/tasks/index/refactor-dev-flow.json",
        feat_id="FEAT-486",
        branch_name="feat-486-refactor-dev-flow",
        worktree_path="/tmp/wt",
        suggested_pool=suggested,
    )


@pytest.mark.asyncio
class TestSingleTaskCollapse:
    """Spec G3: one TASK- in the index ⇒ exactly one sub-agent."""

    async def test_single_task_collapses_to_first_suggested(self, tmp_path, caplog):
        _write_index(
            tmp_path,
            "FEAT-486",
            "refactor-dev-flow",
            [{"id": "TASK-1", "status": "pending", "depends_on": []}],
        )
        builder, seen = _spec_recording_builder()
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(agents=TWO_SEATS),
            dispatcher_builder=builder,
        )
        ctx = {
            "run_id": "r1",
            "research_output": _research(str(tmp_path)),
            # The planner suggests the SECOND configured backend — the
            # collapse rule must honour the suggestion, not just take
            # `pool_cfg.agents[0]`.
            "planner_output": _planner_output(
                DevAgentPoolConfig(agents=[TWO_SEATS[1]])
            ),
        }
        with caplog.at_level(logging.INFO):
            await node.execute(ctx)

        assert len(seen) == 1
        assert seen[0].agent == "nova"
        assert seen[0].model == "qwen.qwen3-coder-480b-a35b-v1:0"
        assert seen[0].count == 1
        assert "collapsing" in caplog.text
        assert "planner suggested_pool" in caplog.text

    async def test_collapse_fallback_to_configured_spec(self, tmp_path, caplog):
        """No usable ``suggested_pool`` ⇒ first configured spec."""
        _write_index(
            tmp_path,
            "FEAT-486",
            "refactor-dev-flow",
            [{"id": "TASK-1", "status": "pending", "depends_on": []}],
        )
        builder, seen = _spec_recording_builder()
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(agents=TWO_SEATS),
            dispatcher_builder=builder,
        )
        with caplog.at_level(logging.INFO):
            await node.execute(
                {"run_id": "r1", "research_output": _research(str(tmp_path))}
            )

        assert len(seen) == 1
        assert seen[0].model == "zai.glm-5"
        assert "configured pool" in caplog.text

    async def test_empty_suggested_pool_falls_back(self, tmp_path):
        _write_index(
            tmp_path,
            "FEAT-486",
            "refactor-dev-flow",
            [{"id": "TASK-1", "status": "pending", "depends_on": []}],
        )
        builder, seen = _spec_recording_builder()
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(agents=TWO_SEATS),
            dispatcher_builder=builder,
        )
        await node.execute(
            {
                "run_id": "r1",
                "research_output": _research(str(tmp_path)),
                "planner_output": _planner_output(None),
            }
        )
        assert len(seen) == 1
        assert seen[0].model == "zai.glm-5"

    async def test_multi_task_deploys_full_pool(self, tmp_path):
        _write_index(
            tmp_path,
            "FEAT-486",
            "refactor-dev-flow",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
            ],
        )
        builder, seen = _spec_recording_builder()
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(agents=TWO_SEATS),
            dispatcher_builder=builder,
        )
        await node.execute(
            {
                "run_id": "r1",
                "research_output": _research(str(tmp_path)),
                "planner_output": _planner_output(
                    DevAgentPoolConfig(agents=[TWO_SEATS[1]])
                ),
            }
        )
        assert [s.model for s in seen] == [
            "zai.glm-5",
            "qwen.qwen3-coder-480b-a35b-v1:0",
        ]

    async def test_collapse_never_grows_a_single_seat_pool(self, tmp_path, caplog):
        """An already-single-slot config is returned untouched, silently."""
        _write_index(
            tmp_path,
            "FEAT-486",
            "refactor-dev-flow",
            [{"id": "TASK-1", "status": "pending", "depends_on": []}],
        )
        builder, seen = _spec_recording_builder()
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(agents=[TWO_SEATS[0]]),
            dispatcher_builder=builder,
        )
        with caplog.at_level(logging.INFO):
            await node.execute(
                {"run_id": "r1", "research_output": _research(str(tmp_path))}
            )
        assert len(seen) == 1
        assert "collapsing" not in caplog.text

    async def test_collapse_preserves_isolation_mode(self, tmp_path):
        _write_index(
            tmp_path,
            "FEAT-486",
            "refactor-dev-flow",
            [{"id": "TASK-1", "status": "pending", "depends_on": []}],
        )
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(agents=TWO_SEATS, isolation_mode="isolated"),
            dispatcher_builder=_spec_recording_builder()[0],
        )
        collapsed = node._collapse_for_single_task(
            {},
            DevAgentPoolConfig(agents=TWO_SEATS, isolation_mode="isolated"),
            _FakeScheduler(1),
            _research(str(tmp_path)),
        )
        assert collapsed.isolation_mode == "isolated"
        assert len(collapsed.agents) == 1

    async def test_unreadable_index_degrades_as_today(self, tmp_path, caplog):
        """No index at all ⇒ the pre-FEAT-486 warning + single-agent path.

        The collapse rule must never run here: it needs a readable
        scheduler, and ``execute()`` returns via ``_execute_single``
        before reaching it. The single-agent path's own pre-existing
        behaviour — honouring the FIRST declared spec through
        ``dispatcher_builder`` (``development.py:536-550``) — is
        unchanged, so exactly ONE spec is built and no collapse log is
        emitted.
        """
        builder, seen = _spec_recording_builder()
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(agents=TWO_SEATS),
            dispatcher_builder=builder,
        )
        with caplog.at_level(logging.INFO):
            await node.execute(
                {"run_id": "r1", "research_output": _research(str(tmp_path))}
            )
        assert "No readable per-spec task index" in caplog.text
        assert "degrading to single-agent" in caplog.text
        # Degradation, not collapse — neither FEAT-486 log fired.
        assert "collapsing" not in caplog.text
        assert "Deploying" not in caplog.text
        assert [s.model for s in seen] == ["zai.glm-5"]


class _FakeScheduler:
    """Minimal stand-in exposing only what the collapse rule reads."""

    def __init__(self, task_count: int) -> None:
        self._tasks = {f"TASK-{i}": object() for i in range(1, task_count + 1)}

    def next_wave(self):
        return []


@pytest.mark.asyncio
class TestPoolDeploymentLog:
    """Spec G4: the deployment must be visible at INFO."""

    async def test_deployment_info_log_lists_workers(self, tmp_path, caplog):
        _write_index(
            tmp_path,
            "FEAT-486",
            "refactor-dev-flow",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
            ],
        )
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(agents=TWO_SEATS),
            dispatcher_builder=_spec_recording_builder()[0],
        )
        with caplog.at_level(logging.INFO):
            await node.execute(
                {"run_id": "r1", "research_output": _research(str(tmp_path))}
            )

        assert "Deploying 2 dev sub-agent(s)" in caplog.text
        assert "w1=nova:zai.glm-5" in caplog.text
        assert "w2=nova:qwen.qwen3-coder-480b-a35b-v1:0" in caplog.text

    async def test_log_names_backend_default_for_empty_model(self, tmp_path, caplog):
        _write_index(
            tmp_path,
            "FEAT-486",
            "refactor-dev-flow",
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": []},
            ],
        )
        node = DevelopmentNode(
            dispatcher=MagicMock(),
            pool_config=DevAgentPoolConfig(
                agents=[DevAgentSpec(agent="claude-code", count=2)]
            ),
            dispatcher_builder=_spec_recording_builder()[0],
        )
        with caplog.at_level(logging.INFO):
            await node.execute(
                {"run_id": "r1", "research_output": _research(str(tmp_path))}
            )
        assert "w1=claude-code:<backend default>" in caplog.text


class TestPlannerPoolBackends:
    """Spec Module 3(c): stop hardcoding ``DevAgentSpec(agent='claude-code')``."""

    def test_resolve_pool_claude_code_fallback(self):
        node = PlannerNode(dispatcher=MagicMock())
        specs = node._derive_specs(3)
        assert len(specs) == 1
        assert specs[0].agent == "claude-code"
        assert specs[0].count == 3

    def test_resolve_pool_respects_configured_backends(self):
        node = PlannerNode(
            dispatcher=MagicMock(),
            development_pool_config=DevAgentPoolConfig(agents=TWO_SEATS),
        )
        specs = node._derive_specs(2)
        assert [(s.agent, s.model, s.count) for s in specs] == [
            ("nova", "zai.glm-5", 1),
            ("nova", "qwen.qwen3-coder-480b-a35b-v1:0", 1),
        ]

    def test_width_one_uses_only_the_first_configured_backend(self):
        node = PlannerNode(
            dispatcher=MagicMock(),
            development_pool_config=DevAgentPoolConfig(agents=TWO_SEATS),
        )
        specs = node._derive_specs(1)
        assert len(specs) == 1
        assert specs[0].model == "zai.glm-5"
        assert specs[0].count == 1

    def test_remainder_goes_to_the_first_backend(self):
        node = PlannerNode(
            dispatcher=MagicMock(),
            development_pool_config=DevAgentPoolConfig(agents=TWO_SEATS),
        )
        specs = node._derive_specs(3)
        assert [s.count for s in specs] == [2, 1]

    def test_derived_counts_always_sum_to_the_requested_width(self):
        node = PlannerNode(
            dispatcher=MagicMock(),
            development_pool_config=DevAgentPoolConfig(agents=TWO_SEATS),
        )
        for width in range(1, 8):
            assert sum(s.count for s in node._derive_specs(width)) == width

    def test_configured_specs_are_not_mutated(self):
        configured = DevAgentPoolConfig(agents=TWO_SEATS)
        node = PlannerNode(
            dispatcher=MagicMock(), development_pool_config=configured
        )
        node._derive_specs(5)
        assert [s.count for s in configured.agents] == [1, 1]
