"""Tests for the grounding evaluator and run→knowledge lineage linkage."""

import pytest

from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit
from parrot.knowledge.graphindex.grounding import (
    GroundingEvaluator,
    GroundingJudgement,
)
from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever
from parrot.knowledge.graphindex.schema import stable_edge_id


async def _toolkit_with_graph(tmp_path):
    tk = await build_graph_memory_toolkit(db_dir=tmp_path, agent_id="ag")
    vendor = await tk.create_concept("Vendor X", "supplies pump components")
    comp = await tk.create_concept("Component Z", "a hydraulic pump")
    incident = await tk.create_concept("Incident Y", "pump failure event")
    isolated = await tk.create_concept("Unrelated Topic", "nothing to do with it")
    await tk.link_nodes(vendor["node_id"], comp["node_id"], "references")
    await tk.link_nodes(comp["node_id"], incident["node_id"], "mentions", confidence=0.6)
    return tk, vendor["node_id"], comp["node_id"], incident["node_id"], isolated["node_id"]


def _evaluator(tk, client=None) -> GroundingEvaluator:
    retriever = GraphExpandedRetriever(
        graph=tk.graph, nodes=tk.nodes, embedder=tk.embedder
    )
    return GroundingEvaluator(retriever, client=client)


class TestGroundClaim:
    async def test_supported_claim_is_grounded_with_cited_edges(self, tmp_path):
        tk, vendor, comp, incident, _ = await _toolkit_with_graph(tmp_path)
        result = await _evaluator(tk).ground_claim(
            "Vendor X supplied the Component Z involved in Incident Y"
        )
        assert result.decision == "grounded"
        cited = {e for path in result.supported_paths for e in path}
        assert stable_edge_id(vendor, comp, "references") in cited

    async def test_unsupported_claim_returns_revise_contract(self, tmp_path):
        tk, vendor, _, _, isolated = await _toolkit_with_graph(tmp_path)
        result = await _evaluator(tk).ground_claim(
            "Vendor X caused the Unrelated Topic"
        )
        assert result.decision == "revise"
        assert result.required_evidence
        assert "Vendor X" in result.reason
        assert "Unrelated Topic" in result.reason

    async def test_unknown_entities_revise(self, tmp_path):
        tk, *_ = await _toolkit_with_graph(tmp_path)
        result = await _evaluator(tk).ground_claim(
            "The Flux Capacitor powers the Time Circuit"
        )
        assert result.decision == "revise"
        assert result.required_evidence

    async def test_contradictions_are_surfaced(self, tmp_path):
        tk, vendor, comp, incident, _ = await _toolkit_with_graph(tmp_path)
        await tk.link_nodes(incident["node_id"] if isinstance(incident, dict) else incident, vendor, "contradicts")
        result = await _evaluator(tk).ground_claim(
            "Vendor X supplied Component Z"
        )
        assert result.decision == "grounded"
        assert result.contradictions
        assert "contradicts" in result.reason or result.contradictions

    async def test_contradicts_edges_never_support(self, tmp_path):
        tk = await build_graph_memory_toolkit(db_dir=tmp_path, agent_id="ag")
        a = await tk.create_concept("Claim A", "one side")
        b = await tk.create_concept("Claim B", "other side")
        await tk.link_nodes(a["node_id"], b["node_id"], "contradicts")
        result = await _evaluator(tk).ground_claim("Claim A supports Claim B")
        assert result.decision == "revise"

    async def test_llm_judge_can_veto(self, tmp_path):
        class _VetoClient:
            async def invoke(self, prompt, *, output_type=None, **kw):
                class _R:
                    output = GroundingJudgement(
                        supported=False, reason="direction mismatch"
                    )
                return _R()

        tk, *_ = await _toolkit_with_graph(tmp_path)
        result = await _evaluator(tk, client=_VetoClient()).ground_claim(
            "Vendor X supplied Component Z"
        )
        assert result.decision == "revise"
        assert "direction mismatch" in result.reason
        assert result.supported_paths  # paths existed; semantics failed

    async def test_llm_judge_confirms(self, tmp_path):
        class _ConfirmClient:
            async def invoke(self, prompt, *, output_type=None, **kw):
                class _R:
                    output = GroundingJudgement(
                        supported=True, reason="entailed", confidence=0.9
                    )
                return _R()

        tk, *_ = await _toolkit_with_graph(tmp_path)
        result = await _evaluator(tk, client=_ConfirmClient()).ground_claim(
            "Vendor X supplied Component Z"
        )
        assert result.decision == "grounded"
        assert result.confidence == 0.9


class TestToolkitGroundClaim:
    async def test_ground_claim_tool(self, tmp_path):
        tk, vendor, comp, *_ = await _toolkit_with_graph(tmp_path)
        result = await tk.ground_claim("Vendor X supplied Component Z")
        assert result["decision"] == "grounded"
        assert result["supported_paths"]


class TestRunLineage:
    async def test_recorder_mirrors_run_and_links_produced(self, tmp_path):
        from parrot.knowledge.graphindex.factory import make_stub_tenant_context
        from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
        from parrot.knowledge.graphindex.publish import GraphPublisher
        from parrot.knowledge.graphindex.schema import (
            GraphUpdate,
            NodeKind,
            UniversalNode,
        )
        from parrot.knowledge.wiki.execution import ExecutionWikiRecorder

        ctx = make_stub_tenant_context("crew-graph")
        persistence = SQLitePersistence(tmp_path / "graph")
        publisher = GraphPublisher(persistence, ctx)
        recorder = ExecutionWikiRecorder(
            storage_dir=tmp_path / "wiki",
            crew_name="research-crew",
            publisher=publisher,
        )

        await recorder.record_run_start(
            "exec-1", "run_sequential", "investigate the pump failure"
        )
        # Simulate a knowledge write made during the run (same run_id).
        await publisher.publish(
            GraphUpdate(
                nodes=[
                    UniversalNode(
                        node_id="claim-1",
                        kind=NodeKind.CLAIM,
                        title="Pump failed due to seal wear",
                        source_uri="agent://claim/claim-1",
                    )
                ],
                agent_id="research-crew",
                run_id="exec-1",
                asserted_by="crew:research-crew",
            )
        )
        await recorder.record_run_end("exec-1", result="done")

        nodes, edges = await persistence.load_graph(ctx)
        by_id = {n.node_id: n for n in nodes}
        assert by_id["run:exec-1"].kind.value == "run"
        produced = [
            (e.source_id, e.target_id)
            for e in edges
            if e.kind.value == "produced"
        ]
        assert ("run:exec-1", "claim-1") in produced
        # The run node itself is never self-linked.
        assert ("run:exec-1", "run:exec-1") not in produced

    async def test_recorder_without_publisher_is_unchanged(self, tmp_path):
        from parrot.knowledge.wiki.execution import ExecutionWikiRecorder

        recorder = ExecutionWikiRecorder(
            storage_dir=tmp_path / "wiki", crew_name="plain-crew"
        )
        await recorder.record_run_start("exec-2", "run_sequential", "task")
        await recorder.record_run_end("exec-2", result="done")
        page = await recorder.store.get_page("run:exec-2")
        assert page is not None
