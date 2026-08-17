"""Unit tests for `parrot.flows.thales.factories` (FEAT-425 TASK-2227).

All tests are mocked — no network, no real LLM calls.
"""

from unittest.mock import AsyncMock, patch

import pytest

from parrot.flows.thales import factories
from parrot.flows.thales.models import ResearchAngle, ThalesConfig
from parrot.models.responses import AIMessage, CompletionUsage


def _angle() -> ResearchAngle:
    return ResearchAngle(angle_id="a1", title="t", question="q", rationale="r")


def _ai_message(response: str = "some finding text", metadata: dict | None = None) -> AIMessage:
    return AIMessage(
        input="prompt",
        output=response,
        response=response,
        model="test-model",
        provider="test-provider",
        usage=CompletionUsage(),
        metadata=metadata or {},
    )


class TestBuildWebAgent:
    def test_websearch_agent_flags(self):
        agent = factories.build_web_agent(angle=_angle(), config=ThalesConfig(thesis="t"))
        assert agent.use_builtin_search is True
        assert agent.contrastive_search is True
        assert agent.enable_groundedness is True


class TestBuildArxivAgent:
    def test_arxiv_agent_has_tool_and_groundedness(self):
        agent = factories.build_arxiv_agent(angle=_angle(), config=ThalesConfig(thesis="t"))
        assert agent.enable_groundedness is True
        assert "arxiv_search" in agent.tool_manager.list_tools()


class TestArxivToFindings:
    def test_arxiv_paper_to_source_claim(self):
        paper = {
            "title": "T", "authors": ["A"], "published": "2024-01-02",
            "pdf_url": "https://arxiv.org/pdf/1", "journal_ref": None,
            "summary": "s", "arxiv_id": "1", "categories": [],
            "primary_category": "cs.AI", "updated": None, "comment": None,
        }
        findings = factories.arxiv_to_findings(
            {"papers": [paper], "count": 1}, accessed_date="2026-08-17",
            config=ThalesConfig(thesis="t"),
        )
        claim = findings[0].claims[0]
        assert claim.source_tool == "arxiv_search"
        assert claim.published_date == "2024-01-02"
        assert claim.url == "https://arxiv.org/pdf/1"
        assert claim.title == "T"
        assert claim.authors == ["A"]
        assert claim.verification == "unverified"

    def test_arxiv_verification_groundedness_when_report_present(self):
        paper = {
            "title": "T", "authors": [], "published": None,
            "pdf_url": "https://arxiv.org/pdf/2", "journal_ref": None,
            "summary": "s",
        }
        findings = factories.arxiv_to_findings(
            {"papers": [paper], "count": 1}, accessed_date="2026-08-17",
            config=ThalesConfig(thesis="t"),
            groundedness_report={"score": 0.9},
        )
        assert findings[0].claims[0].verification == "groundedness"
        # missing publication date is never invented:
        assert findings[0].claims[0].published_date is None

    def test_arxiv_no_papers_yields_no_findings(self):
        findings = factories.arxiv_to_findings(
            {"papers": [], "count": 0}, accessed_date="2026-08-17",
            config=ThalesConfig(thesis="t"),
        )
        assert findings == []


class TestWebsearchToFindings:
    def test_provider_grounding_label(self):
        message = _ai_message()
        findings = factories.websearch_to_findings(
            message, accessed_date="2026-08-17", config=ThalesConfig(thesis="t"),
        )
        assert len(findings) == 1
        assert findings[0].claims[0].verification == "provider_grounding"
        assert findings[0].claims[0].source_tool == "web_search"

    def test_empty_response_yields_no_findings(self):
        message = _ai_message(response="")
        findings = factories.websearch_to_findings(
            message, accessed_date="2026-08-17", config=ThalesConfig(thesis="t"),
        )
        assert findings == []


class TestDeepResearchToFindings:
    def test_provider_grounding_label(self):
        message = _ai_message()
        findings = factories.deep_research_to_findings(
            message, accessed_date="2026-08-17", config=ThalesConfig(thesis="t"),
        )
        assert len(findings) == 1
        assert findings[0].claims[0].verification == "provider_grounding"
        assert findings[0].claims[0].source_tool == "deep_research"


class TestExtractGroundednessReport:
    def test_present(self):
        message = _ai_message(metadata={"guardrails": {"groundedness": {"score": 0.5}}})
        assert factories.extract_groundedness_report(message) == {"score": 0.5}

    def test_absent(self):
        message = _ai_message(metadata={})
        assert factories.extract_groundedness_report(message) is None


class TestBuildDeepResearchCaller:
    @pytest.mark.asyncio
    async def test_deep_research_flag_passthrough(self):
        """Caller passes deep_research=True; flag-ignoring client degrades cleanly."""
        fake_client = AsyncMock()
        fake_client.ask.return_value = _ai_message(response="bedrock-style plain answer")

        with patch.object(factories.LLMFactory, "create", return_value=fake_client):
            caller = factories.build_deep_research_caller(ThalesConfig(thesis="t"))
            result = await caller("investigate this")

        fake_client.ask.assert_awaited_once_with("investigate this", deep_research=True)
        assert result.response == "bedrock-style plain answer"

    def test_default_llm_is_google(self):
        with patch.object(factories.LLMFactory, "create", return_value=AsyncMock()) as mock_create:
            factories.build_deep_research_caller(ThalesConfig(thesis="t"))
        mock_create.assert_called_once_with(llm=factories.DEFAULT_DEEP_RESEARCH_LLM)


class TestBuildAgentRegistry:
    def test_registers_web_and_arxiv_per_angle(self):
        angles = [_angle(), ResearchAngle(angle_id="a2", title="t2", question="q2", rationale="r2")]
        registry = factories.build_agent_registry(angles, ThalesConfig(thesis="t"))
        for angle in angles:
            assert registry.get_metadata(f"thales-web-{angle.angle_id}") is not None
            assert registry.get_metadata(f"thales-arxiv-{angle.angle_id}") is not None

    def test_respects_config_sources(self):
        angles = [_angle()]
        registry = factories.build_agent_registry(
            angles, ThalesConfig(thesis="t", sources=["web"]),
        )
        assert registry.get_metadata("thales-web-a1") is not None
        assert registry.get_metadata("thales-arxiv-a1") is None
