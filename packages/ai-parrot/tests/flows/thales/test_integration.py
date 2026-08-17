"""Integration tests for the "Thales" research flow (FEAT-425 TASK-2233).

Everything is mocked — no network, no real LLM, no real Redis; the
ArtifactStore and InfographicToolkit are `AsyncMock`s (no real DB/S3).
Exercises the full `ThalesRunner.run()` pipeline (spec §4 Integration
Tests): e2e happy path (both persistence surfaces), partial-source
degradation, and (see `TestCheckpointResume`'s docstring for an important,
verified limitation) checkpoint persistence.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from parrot.flows.thales.runner import ThalesRunner

from .conftest import FakeAgent, FakeClient, make_arxiv_message, make_web_message


def _patch_research_agents(monkeypatch, *, dateless_angle_id: str = "a0", fail_angle_id: str | None = None):
    """Patch `build_web_agent`/`build_arxiv_agent` to return `FakeAgent`s."""
    import parrot.flows.thales.definition as definition_module

    def fake_build_web_agent(angle, config):
        return FakeAgent(make_web_message, angle.angle_id, fail=(angle.angle_id == fail_angle_id))

    def fake_build_arxiv_agent(angle, config):
        return FakeAgent(
            lambda aid: make_arxiv_message(aid, dateless=(aid == dateless_angle_id)),
            angle.angle_id,
        )

    monkeypatch.setattr(definition_module, "build_web_agent", fake_build_web_agent)
    monkeypatch.setattr(definition_module, "build_arxiv_agent", fake_build_arxiv_agent)


@pytest.mark.asyncio
class TestThalesE2EMockedLLM:
    async def test_thales_e2e_mocked_llm(self, tmp_path, mock_research_outputs, monkeypatch):
        """Full run with mocked LLM/tool responses: thesis -> >=10 decks ->
        slides -> document (+pdf if available) -> infographic; manifest complete.

        Exercises BOTH persistence surfaces (spec AC: "all persisted via
        ArtifactStore AND mirrored under output_dir") with a fake
        ArtifactStore, and a fake InfographicToolkit so the infographic
        actually populates rather than gracefully degrading to None.
        """
        _patch_research_agents(monkeypatch)

        fake_store = AsyncMock()
        fake_store.get_public_url.return_value = "https://example.com/artifact"

        # A plain JSON-serializable dict — ThalesResult.infographic is typed
        # Optional[Any] specifically so it can carry the toolkit's real
        # InfographicRenderResult without this models package importing
        # toolkit machinery; a dict here keeps manifest.json serializable.
        fake_toolkit = AsyncMock()
        fake_toolkit.render_template.return_value = {"artifact_id": "infographic-1"}

        with (
            patch("parrot.flows.thales.runner.LLMFactory") as runner_llm_factory,
            patch("parrot.flows.thales.factories.LLMFactory") as factories_llm_factory,
        ):
            client = FakeClient(num_angles=10)
            runner_llm_factory.create.return_value = client
            factories_llm_factory.create.return_value = client

            runner = ThalesRunner(
                thesis="open-source flight stacks bridge LATAM engineering talent",
                output_dir=tmp_path,
                artifact_store=fake_store,
                infographic_toolkit=fake_toolkit,
            )
            result = await runner.run()

        # >=10 decks (num_decks floor).
        assert len(result.decks) >= 10

        # Every Finding carries >=1 SourceClaim with source_tool + verification set.
        for deck in result.decks:
            for finding in deck.findings:
                assert finding.claims, "every finding must carry at least one claim"
                for claim in finding.claims:
                    assert claim.source_tool
                    assert claim.verification in ("groundedness", "provider_grounding", "unverified")

        # Bibliography: dedupe (all arxiv papers share one URL) + "n.d." for the dateless angle.
        assert len(result.bibliography.entries) >= 1
        assert any("n.d." in entry for entry in result.bibliography.entries)

        # Executive summary + infographic (toolkit configured this time).
        assert result.executive_summary
        assert result.infographic is not None

        # ArtifactStore persistence: N slide refs + final document ref carry real URLs.
        assert len(result.slides) == len(result.decks)
        for slide_ref in result.slides:
            assert slide_ref.artifact_id is not None
            assert slide_ref.url == "https://example.com/artifact"
        assert result.final_document.artifact_id is not None
        assert result.final_document.url == "https://example.com/artifact"
        assert fake_store.save_artifact.await_count >= len(result.decks) * 2  # deck + slide, at least

        # output_dir mirroring: manifest.json + per-angle deck/slide files.
        assert result.manifest_path is not None
        assert result.manifest_path.exists()
        manifest = json.loads(result.manifest_path.read_text())
        assert manifest["thesis"] == runner.config.thesis
        assert len(manifest["decks"]) == len(result.decks)

        for deck in result.decks:
            assert (tmp_path / f"deck-{deck.angle.angle_id}.json").exists()
            assert (tmp_path / f"slide-{deck.angle.angle_id}.html").exists()

        assert not result.warnings or all("weasyprint" in w for w in result.warnings)


@pytest.mark.asyncio
class TestThalesPartialSources:
    async def test_thales_partial_sources(self, tmp_path, mock_research_outputs, monkeypatch):
        """sources=["web", "arxiv"] (deep disabled) -> run succeeds; decks
        cite only web+arxiv.
        """
        _patch_research_agents(monkeypatch)

        with (
            patch("parrot.flows.thales.runner.LLMFactory") as runner_llm_factory,
            patch("parrot.flows.thales.factories.LLMFactory") as factories_llm_factory,
        ):
            client = FakeClient(num_angles=10)
            runner_llm_factory.create.return_value = client
            factories_llm_factory.create.return_value = client

            runner = ThalesRunner(
                thesis="t",
                sources=["web", "arxiv"],
                output_dir=tmp_path,
                artifact_store=None,
            )
            result = await runner.run()

        tools = {
            claim.source_tool
            for deck in result.decks
            for finding in deck.findings
            for claim in finding.claims
        }
        assert "deep_research" not in tools
        assert tools <= {"web_search", "arxiv_search"}
        assert len(result.decks) >= 10


@pytest.mark.asyncio
class TestCheckpointResume:
    """Checkpoint persistence during a Thales run.

    **Verified limitation (reported, not silently worked around):**
    `AgentsFlow.resume(flow_id, checkpoint_id, *, agent_registry, ...)`
    reconstructs its graph via `cls.from_definition(checkpoint.definition,
    agent_registry=agent_registry)` with **no `node_factories` parameter at
    all** (confirmed by reading `resume()`'s body, `flow/flow.py`).
    `_materialize_nodes()`'s generic fallback for a node type with no
    registered factory is `cls(node_id=nid, dependencies=deps,
    successors=succs)` — which cannot supply Thales's custom node types'
    additional REQUIRED fields (`angle`, `config`, `client`, `agent`,
    `store`, `toolkit`, ...), so it would raise a Pydantic
    `ValidationError` while materializing EVERY node (not just incomplete
    ones — `_materialize_nodes()` does not distinguish). Fixing this would
    mean adding `node_factories` support to `AgentsFlow.resume()` itself —
    an engine change spec §5's own acceptance criteria forbid ("No changes
    to `flow.py`, `crew.py`, `abstract.py`, or any existing public API").

    This test therefore verifies what IS true and checkable offline: a
    Thales run with `checkpoint=True` persists progress to its
    `CheckpointStore` as nodes complete (the FEAT-399 contract Thales
    actually relies on for "long Deep Research runs are resumable" is the
    persistence half, not a proven `resume()` round-trip for this node
    shape). Full `AgentsFlow.resume()` support is reported as an open gap,
    not ticked as met, in this task's Completion Note and spec §5.
    """

    async def test_checkpoint_is_written_during_a_run(
        self, tmp_path, mock_research_outputs, monkeypatch, patched_checkpoint_store,
    ):
        _patch_research_agents(monkeypatch)

        with (
            patch("parrot.flows.thales.runner.LLMFactory") as runner_llm_factory,
            patch("parrot.flows.thales.factories.LLMFactory") as factories_llm_factory,
        ):
            client = FakeClient(num_angles=10)
            runner_llm_factory.create.return_value = client
            factories_llm_factory.create.return_value = client

            runner = ThalesRunner(thesis="t", output_dir=tmp_path, artifact_store=None)
            result = await runner.run()

        assert len(result.decks) >= 10
        # The checkpointer wrote at least one checkpoint for this run's flow_id.
        assert runner.run_id in patched_checkpoint_store.puts
