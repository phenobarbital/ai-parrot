"""Unit tests for `parrot.flows.thales.runner.ThalesRunner` (FEAT-425 TASK-2231).

Fully mocked: no network, no real LLM, no real ArtifactStore/AgentsFlow run.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from parrot.flows.thales.models import (
    Bibliography,
    Finding,
    ResearchAngle,
    ResearchDeck,
)
from parrot.flows.thales.nodes.deck_builder import DROPPED_DECK_SENTINEL
from parrot.flows.thales.runner import ThalesRunner


def _angle(angle_id: str = "a0") -> ResearchAngle:
    return ResearchAngle(angle_id=angle_id, title="t", question="q", rationale="r")


def _deck_json(angle_id: str = "a0") -> str:
    deck = ResearchDeck(
        angle=_angle(angle_id),
        findings=[Finding(text="finding", claims=[])],
        tools_used=["web"],
    )
    return deck.model_dump_json()


def _mock_flow_result(responses: dict) -> SimpleNamespace:
    return SimpleNamespace(responses=responses)


@pytest.fixture
def runner() -> ThalesRunner:
    return ThalesRunner(
        thesis="remote work increases regional inequality",
        num_decks=10,
        artifact_store=None,
    )


class TestThalesRunnerRun:
    @pytest.mark.asyncio
    async def test_run_logs_projected_call_count_and_builds_result(self, runner, caplog):
        angles = [_angle(f"a{i}") for i in range(10)]
        angles_json = json.dumps([a.model_dump(mode="json") for a in angles])

        responses = {f"deck-{a.angle_id}": _deck_json(a.angle_id) for a in angles}
        responses.update({f"slide-render-{a.angle_id}": f"<section>{a.angle_id}</section>" for a in angles})
        responses["exec_summary"] = "a synthesized summary"
        responses["bibliography"] = Bibliography().model_dump_json()
        responses["final_document"] = json.dumps({
            "final_document": {"kind": "final_html", "artifact_id": None, "url": None, "path": None},
            "final_pdf": None,
            "warnings": [],
        })
        responses["infographic"] = None

        with (
            patch("parrot.flows.thales.runner.LLMFactory") as mock_factory,
            patch("parrot.flows.thales.runner.PlannerNode") as mock_planner_cls,
            patch("parrot.flows.thales.runner.assemble_thales_flow") as mock_assemble,
        ):
            mock_factory.create.return_value = AsyncMock()
            mock_planner = AsyncMock()
            mock_planner.execute.return_value = angles_json
            mock_planner_cls.return_value = mock_planner

            mock_flow = AsyncMock()
            mock_flow.run_flow.return_value = _mock_flow_result(responses)
            mock_assemble.return_value = mock_flow

            with caplog.at_level("INFO"):
                result = await runner.run()

        assert len(result.decks) == 10
        assert result.executive_summary == "a synthesized summary"
        assert any("projected research calls" in msg for msg in caplog.messages)

    @pytest.mark.asyncio
    async def test_all_decks_dropped_raises(self, runner):
        angles = [_angle("a0")]
        angles_json = json.dumps([a.model_dump(mode="json") for a in angles])
        dropped = json.dumps({DROPPED_DECK_SENTINEL: True, "angle_id": "a0", "failed_sources": ["web"]})
        responses = {"deck-a0": dropped}

        with (
            patch("parrot.flows.thales.runner.LLMFactory") as mock_factory,
            patch("parrot.flows.thales.runner.PlannerNode") as mock_planner_cls,
            patch("parrot.flows.thales.runner.assemble_thales_flow") as mock_assemble,
        ):
            mock_factory.create.return_value = AsyncMock()
            mock_planner = AsyncMock()
            mock_planner.execute.return_value = angles_json
            mock_planner_cls.return_value = mock_planner

            mock_flow = AsyncMock()
            mock_flow.run_flow.return_value = _mock_flow_result(responses)
            mock_assemble.return_value = mock_flow

            with pytest.raises(RuntimeError, match="every research angle's deck was dropped"):
                await runner.run()

    @pytest.mark.asyncio
    async def test_partial_drop_produces_warning_not_abort(self, runner):
        angles = [_angle("a0"), _angle("a1")]
        angles_json = json.dumps([a.model_dump(mode="json") for a in angles])
        dropped = json.dumps({DROPPED_DECK_SENTINEL: True, "angle_id": "a0", "failed_sources": ["web"]})
        responses = {
            "deck-a0": dropped,
            "deck-a1": _deck_json("a1"),
            "slide-render-a1": "<section>a1</section>",
            "exec_summary": "summary",
            "bibliography": Bibliography().model_dump_json(),
            "final_document": json.dumps({
                "final_document": {"kind": "final_html"}, "final_pdf": None, "warnings": [],
            }),
            "infographic": None,
        }

        with (
            patch("parrot.flows.thales.runner.LLMFactory") as mock_factory,
            patch("parrot.flows.thales.runner.PlannerNode") as mock_planner_cls,
            patch("parrot.flows.thales.runner.assemble_thales_flow") as mock_assemble,
        ):
            mock_factory.create.return_value = AsyncMock()
            mock_planner = AsyncMock()
            mock_planner.execute.return_value = angles_json
            mock_planner_cls.return_value = mock_planner

            mock_flow = AsyncMock()
            mock_flow.run_flow.return_value = _mock_flow_result(responses)
            mock_assemble.return_value = mock_flow

            result = await runner.run()

        assert len(result.decks) == 1
        assert any("dropped" in w for w in result.warnings)


class TestThalesRunnerManifest:
    @pytest.mark.asyncio
    async def test_manifest_written_to_output_dir(self, tmp_path):
        runner = ThalesRunner(
            thesis="t", num_decks=10, output_dir=tmp_path, artifact_store=None,
        )
        angles = [_angle("a0")]
        angles_json = json.dumps([a.model_dump(mode="json") for a in angles])
        responses = {
            "deck-a0": _deck_json("a0"),
            "slide-render-a0": "<section>a0</section>",
            "exec_summary": "summary",
            "bibliography": Bibliography().model_dump_json(),
            "final_document": json.dumps({
                "final_document": {"kind": "final_html"}, "final_pdf": None, "warnings": [],
            }),
            "infographic": None,
        }

        with (
            patch("parrot.flows.thales.runner.LLMFactory") as mock_factory,
            patch("parrot.flows.thales.runner.PlannerNode") as mock_planner_cls,
            patch("parrot.flows.thales.runner.assemble_thales_flow") as mock_assemble,
        ):
            mock_factory.create.return_value = AsyncMock()
            mock_planner = AsyncMock()
            mock_planner.execute.return_value = angles_json
            mock_planner_cls.return_value = mock_planner

            mock_flow = AsyncMock()
            mock_flow.run_flow.return_value = _mock_flow_result(responses)
            mock_assemble.return_value = mock_flow

            result = await runner.run()

        assert result.manifest_path is not None
        assert result.manifest_path.exists()
        assert (tmp_path / "deck-a0.json").exists()
        assert (tmp_path / "slide-a0.html").exists()


class TestThalesRunnerProgressListener:
    def test_add_progress_listener_forwards_events(self, runner):
        received = []
        runner.add_progress_listener(lambda event, node_id, info: received.append((event, node_id)))
        runner._on_node_event("node_started", "planner", {})
        assert received == [("node_started", "planner")]
