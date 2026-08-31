"""Unit tests for the research-partner contracts (FEAT-482 Module 1).

Covers ``parrot.flows.dev_flow.research_partner`` (models, ABC, factory)
and the backend selector triad in ``parrot.flows.dev_loop.catalog``.
"""

from __future__ import annotations

import pytest
from parrot.flows.dev_flow.research_partner import (
    AbstractResearchPartner,
    ComplementaryFindings,
    ResearchFinding,
    ResearchFindings,
    ResearchPartnerFactory,
)
from parrot.flows.dev_loop.catalog import (
    RESEARCH_PARTNER_BACKENDS,
    resolve_research_partner_backend,
)
from pydantic import BaseModel


class _FakeBrief(BaseModel):
    title: str = "fake"


class _FakePartner(AbstractResearchPartner):
    partner_name = "fake"

    async def research(
        self,
        *,
        brief,
        question,
        cwd,
        run_id,
        node_id,
        session_host=None,
    ) -> ResearchFindings:
        return ResearchFindings(summary="ok")


def test_resolve_research_partner_backend_default_disabled():
    """Unset config => partner disabled, no work performed."""
    getter = lambda key, fallback=None: fallback
    assert resolve_research_partner_backend(getter) == ""


def test_resolve_research_partner_backend_rejects_unknown():
    """Invalid value raises ValueError naming gpt/nova."""
    getter = lambda key, fallback=None: (
        "codex" if key == "DEV_FLOW_RESEARCH_PARTNER" else fallback
    )
    with pytest.raises(ValueError, match="gpt"):
        resolve_research_partner_backend(getter)


def test_resolve_research_partner_backend_selects_gpt():
    getter = lambda key, fallback=None: (
        "gpt" if key == "DEV_FLOW_RESEARCH_PARTNER" else fallback
    )
    assert resolve_research_partner_backend(getter) == "gpt"


def test_resolve_research_partner_backend_selects_nova():
    getter = lambda key, fallback=None: (
        "nova" if key == "DEV_FLOW_RESEARCH_PARTNER" else fallback
    )
    assert resolve_research_partner_backend(getter) == "nova"


def test_partner_rejects_anthropic_model():
    """us.anthropic.claude-opus-5 refused; message names decorrelation AND the 400."""

    def getter(key, fallback=None):
        if key == "DEV_FLOW_RESEARCH_PARTNER":
            return "nova"
        if key == "DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL":
            return "us.anthropic.claude-opus-5"
        return fallback

    with pytest.raises(ValueError, match="(?s)decorrel.*400|400.*decorrel"):
        resolve_research_partner_backend(getter)


def test_partner_rejects_bare_claude_prefixed_model():
    def getter(key, fallback=None):
        if key == "DEV_FLOW_RESEARCH_PARTNER":
            return "gpt"
        if key == "DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL":
            return "claude-opus-5"
        return fallback

    with pytest.raises(ValueError, match="(?s)decorrel.*400|400.*decorrel"):
        resolve_research_partner_backend(getter)


def test_abstract_partner_is_advisory():
    assert AbstractResearchPartner.advisory is True


def test_factory_registers_and_creates():
    """register() then create() returns the registered class."""
    ResearchPartnerFactory.register("fake-partner-test")(_FakePartner)
    partner = ResearchPartnerFactory.create("fake-partner-test")
    assert isinstance(partner, _FakePartner)


def test_factory_create_unknown_raises_naming_available():
    with pytest.raises(ValueError, match="Unknown research partner backend"):
        ResearchPartnerFactory.create("does-not-exist")


@pytest.mark.asyncio
async def test_fake_partner_research_returns_findings():
    partner = _FakePartner()
    findings = await partner.research(
        brief=_FakeBrief(),
        question="what is the shape of X?",
        cwd="/tmp",
        run_id="run-1",
        node_id="node-1",
    )
    assert isinstance(findings, ResearchFindings)
    assert findings.summary == "ok"


def test_research_finding_field_shapes():
    finding = ResearchFinding(id="F1", title="t", detail="d")
    assert finding.evidence == []
    assert finding.confidence == "medium"


def test_research_findings_default_lists_empty():
    findings = ResearchFindings(summary="s")
    assert findings.findings == []
    assert findings.options_considered == []
    assert findings.could_not_determine == []
    assert findings.sources_examined == []


def test_research_partner_backends_catalog_surfaces_both_ids():
    ids = {b.id for b in RESEARCH_PARTNER_BACKENDS}
    assert ids == {"gpt", "nova"}
    for backend in RESEARCH_PARTNER_BACKENDS:
        assert "research_partner" in backend.roles


def test_complementary_findings_requires_findings_and_rendered():
    findings = ComplementaryFindings(
        backend="nova",
        model="us.amazon.nova-2-lite-v1:0",
        findings=ResearchFindings(summary="s"),
        rendered="# rendered",
        duration_ms=12.5,
    )
    assert findings.document_path == ""
    assert findings.degraded is False
