"""Unit tests for `parrot.flows.thales.nodes` fan-in nodes (FEAT-425 TASK-2230).

All external dependencies (ArtifactStore, InfographicToolkit, synthesis
client) are mocked — no network, no real LLM.
"""

import json
from unittest.mock import AsyncMock

import pytest
from parrot.flows.thales.models import (
    Bibliography,
    Finding,
    ResearchAngle,
    ResearchDeck,
    SourceClaim,
)
from parrot.flows.thales.nodes.bibliography import BibliographyNode, format_apa
from parrot.flows.thales.nodes.deck_builder import DROPPED_DECK_SENTINEL
from parrot.flows.thales.nodes.document import FinalDocumentNode
from parrot.flows.thales.nodes.infographic import InfographicNode
from parrot.flows.thales.nodes.summary import ExecSummaryNode


def _claim(**kw):
    base = dict(
        url="https://x/a", accessed_date="2026-08-17",
        source_tool="web_search", verification="provider_grounding",
    )
    return SourceClaim(**{**base, **kw})


def _angle(angle_id: str = "a1") -> ResearchAngle:
    return ResearchAngle(angle_id=angle_id, title="t", question="q", rationale="r")


def _deck(**kw) -> ResearchDeck:
    base = dict(angle=_angle(), findings=[], tools_used=[], failed_sources=[])
    return ResearchDeck(**{**base, **kw})


class TestFormatApa:
    def test_bibliography_apa_dedupe(self):
        bib = format_apa([_claim(), _claim()])  # duplicate URL
        assert len(bib.entries) == 1

    def test_bibliography_nd_for_missing_date(self):
        bib = format_apa([_claim(title="T", publisher="P", published_date=None)])
        assert "n.d." in bib.entries[0] and "20" not in bib.entries[0].split("n.d.")[0]

    def test_bibliography_deterministic_order(self):
        a = _claim(url="https://x/a", title="A")
        b = _claim(url="https://x/b", title="B")
        assert format_apa([a, b]).entries == format_apa([b, a]).entries

    def test_bibliography_with_authors(self):
        claim = _claim(
            url="https://x/c", title="Some Paper", authors=["Doe, J."],
            published_date="2024-05-01", publisher="Journal X",
        )
        bib = format_apa([claim])
        assert "Doe, J. (2024)." in bib.entries[0]
        assert "Journal X." in bib.entries[0]

    def test_empty_claims_yields_empty_bibliography(self):
        bib = format_apa([])
        assert bib.entries == []
        assert bib.claims == []


class TestBibliographyNode:
    @pytest.mark.asyncio
    async def test_collects_claims_from_all_decks(self):
        deck1 = _deck(
            angle=_angle("a1"),
            findings=[Finding(text="f1", claims=[_claim(url="https://x/1")])],
        )
        deck2 = _deck(
            angle=_angle("a2"),
            findings=[Finding(text="f2", claims=[_claim(url="https://x/2")])],
        )
        deps = {"deck-a1": deck1.model_dump_json(), "deck-a2": deck2.model_dump_json()}
        node = BibliographyNode(node_id="bibliography")
        result = await node.execute(ctx=None, deps=deps)
        bib = Bibliography.model_validate_json(result)
        assert len(bib.entries) == 2

    @pytest.mark.asyncio
    async def test_skips_dropped_deck_sentinel(self):
        dropped = json.dumps({DROPPED_DECK_SENTINEL: True, "angle_id": "a1", "failed_sources": ["web"]})
        deps = {"deck-a1": dropped}
        node = BibliographyNode(node_id="bibliography")
        result = await node.execute(ctx=None, deps=deps)
        bib = Bibliography.model_validate_json(result)
        assert bib.entries == []


class TestExecSummaryNode:
    @pytest.mark.asyncio
    async def test_produces_summary_from_mocked_decks(self, monkeypatch):
        async def fake_synthesize_results(ctx, result):
            assert len(result.responses) == 2
            return "a synthesized summary"

        import parrot.flows.thales.nodes.summary as summary_module
        monkeypatch.setattr(summary_module, "synthesize_results", fake_synthesize_results)

        node = ExecSummaryNode(node_id="exec_summary")
        deps = {"deck-a1": "deck one content", "deck-a2": "deck two content"}
        result = await node.execute(ctx=object(), deps=deps)
        assert result == "a synthesized summary"


class TestFinalDocumentNode:
    @pytest.mark.asyncio
    async def test_persists_html_and_pdf_when_weasyprint_present(self, monkeypatch):
        import parrot.flows.thales.nodes.document as document_module

        async def fake_render_document(slides_html, bibliography, *, title):
            return "<html>doc</html>"

        monkeypatch.setattr(document_module, "render_document", fake_render_document)
        monkeypatch.setattr(document_module, "rasterize_pdf", lambda html: b"%PDF-fake")

        store = AsyncMock()
        store.get_public_url.return_value = "https://example.com/artifact"

        node = FinalDocumentNode(
            node_id="final_document", store=store,
            user_id="u1", agent_id="thales", session_id="s1",
            slide_node_ids=["slide-a1"],
        )
        deps = {"slide-a1": "<section>slide</section>", "bibliography": Bibliography().model_dump_json()}
        result = await node.execute(ctx=None, deps=deps)
        payload = json.loads(result)

        assert payload["final_document"]["kind"] == "final_html"
        assert payload["final_pdf"]["kind"] == "final_pdf"
        assert payload["warnings"] == []
        assert store.save_artifact.await_count == 2

    @pytest.mark.asyncio
    async def test_missing_weasyprint_yields_none_ref_and_warning(self, monkeypatch):
        import parrot.flows.thales.nodes.document as document_module

        async def fake_render_document(slides_html, bibliography, *, title):
            return "<html>doc</html>"

        monkeypatch.setattr(document_module, "render_document", fake_render_document)
        monkeypatch.setattr(document_module, "rasterize_pdf", lambda html: None)

        store = AsyncMock()
        store.get_public_url.return_value = "https://example.com/artifact"

        node = FinalDocumentNode(
            node_id="final_document", store=store,
            user_id="u1", agent_id="thales", session_id="s1",
            slide_node_ids=["slide-a1"],
        )
        deps = {"slide-a1": "<section>slide</section>", "bibliography": Bibliography().model_dump_json()}
        result = await node.execute(ctx=None, deps=deps)
        payload = json.loads(result)

        assert payload["final_pdf"] is None
        assert any("weasyprint" in w for w in payload["warnings"])
        assert store.save_artifact.await_count == 1

    @pytest.mark.asyncio
    async def test_no_store_configured_degrades_gracefully(self, monkeypatch):
        """No ArtifactStore injected (store=None) -> bare ArtifactRefs, no crash.

        Regression test (found via TASK-2233 integration testing): a real
        end-to-end run with ``artifact_store=None`` used to raise
        ``AttributeError: 'NoneType' object has no attribute 'save_artifact'``.
        """
        import parrot.flows.thales.nodes.document as document_module

        async def fake_render_document(slides_html, bibliography, *, title):
            return "<html>doc</html>"

        monkeypatch.setattr(document_module, "render_document", fake_render_document)
        monkeypatch.setattr(document_module, "rasterize_pdf", lambda html: b"%PDF-fake")

        node = FinalDocumentNode(
            node_id="final_document", store=None,
            user_id="u1", agent_id="thales", session_id="s1",
            slide_node_ids=["slide-a1"],
        )
        deps = {"slide-a1": "<section>slide</section>", "bibliography": Bibliography().model_dump_json()}
        result = await node.execute(ctx=None, deps=deps)
        payload = json.loads(result)

        assert payload["final_document"] == {"kind": "final_html", "artifact_id": None, "url": None, "path": None}
        assert payload["final_pdf"] == {"kind": "final_pdf", "artifact_id": None, "url": None, "path": None}

    @pytest.mark.asyncio
    async def test_mirrors_to_output_dir_independent_of_store(self, monkeypatch, tmp_path):
        """Code-review fix regression: the final document (+ pdf) must be
        mirrored under `output_dir` even with NO ArtifactStore configured
        — previously only reachable via ArtifactStore, silently dropped
        in the documented output_dir-only configuration.
        """
        import parrot.flows.thales.nodes.document as document_module

        async def fake_render_document(slides_html, bibliography, *, title):
            return "<html>doc</html>"

        monkeypatch.setattr(document_module, "render_document", fake_render_document)
        monkeypatch.setattr(document_module, "rasterize_pdf", lambda html: b"%PDF-fake")

        node = FinalDocumentNode(
            node_id="final_document", store=None,
            user_id="u1", agent_id="thales", session_id="s1",
            slide_node_ids=["slide-a1"], output_dir=tmp_path,
        )
        deps = {"slide-a1": "<section>slide</section>", "bibliography": Bibliography().model_dump_json()}
        result = await node.execute(ctx=None, deps=deps)
        payload = json.loads(result)

        assert (tmp_path / "final-document.html").read_text() == "<html>doc</html>"
        assert (tmp_path / "final-document.pdf").read_bytes() == b"%PDF-fake"
        assert payload["final_document"]["path"] == str(tmp_path / "final-document.html")
        assert payload["final_pdf"]["path"] == str(tmp_path / "final-document.pdf")
        # No store configured -> no artifact_id/url, only the mirrored path.
        assert payload["final_document"]["artifact_id"] is None
        assert payload["final_pdf"]["artifact_id"] is None


class TestInfographicNode:
    @pytest.mark.asyncio
    async def test_degrades_to_none_on_toolkit_failure(self):
        toolkit = AsyncMock()
        toolkit.render_template.side_effect = RuntimeError("boom")

        node = InfographicNode(node_id="infographic", toolkit=toolkit)
        result = await node.execute(ctx=None, deps={"exec_summary": "summary text"})

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_render_result_on_success(self):
        toolkit = AsyncMock()
        toolkit.render_template.return_value = "a-render-result"

        node = InfographicNode(node_id="infographic", toolkit=toolkit)
        deps = {"exec_summary": "summary text", "deck-a1": "deck json"}
        result = await node.execute(ctx=None, deps=deps)

        assert result == "a-render-result"
        _, kwargs = toolkit.render_template.call_args
        assert kwargs["data"]["executive_summary"] == "summary text"
        assert kwargs["data"]["decks"] == ["deck json"]
