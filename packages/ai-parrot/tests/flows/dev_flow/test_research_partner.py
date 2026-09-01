"""Unit tests for the research-partner contracts (FEAT-482 Module 1).

Covers ``parrot.flows.dev_flow.research_partner`` (models, ABC, factory)
and the backend selector triad in ``parrot.flows.dev_loop.catalog``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot import conf
from parrot.flows.dev_flow.research_partner import (
    AbstractResearchPartner,
    BedrockResearchPartner,
    ComplementaryFindings,
    ResearchFinding,
    ResearchFindings,
    ResearchPartnerFactory,
    resolve_backend_model,
)
from parrot.flows.dev_loop.catalog import (
    RESEARCH_PARTNER_BACKENDS,
    resolve_research_partner_backend,
)
from pydantic import BaseModel


class _FakeBrief(BaseModel):
    title: str = "fake"


class _FakeMessage:
    """Minimal AIMessage stand-in — only ``structured_output`` is read."""

    def __init__(self, structured_output):
        self.structured_output = structured_output


def _make_client_mock(structured_output):
    client = MagicMock()
    client.register_tools = MagicMock()
    client.ask = AsyncMock(return_value=_FakeMessage(structured_output))
    return client


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
    getter = lambda key, fallback=None: ("codex" if key == "DEV_FLOW_RESEARCH_PARTNER" else fallback)
    with pytest.raises(ValueError, match="gpt"):
        resolve_research_partner_backend(getter)


def test_resolve_research_partner_backend_selects_gpt():
    getter = lambda key, fallback=None: ("gpt" if key == "DEV_FLOW_RESEARCH_PARTNER" else fallback)
    assert resolve_research_partner_backend(getter) == "gpt"


def test_resolve_research_partner_backend_selects_nova():
    getter = lambda key, fallback=None: ("nova" if key == "DEV_FLOW_RESEARCH_PARTNER" else fallback)
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


def test_resolve_backend_model_shared_between_partner_and_coordinator():
    """Code-review follow-up: this is the single source of truth for the
    backend->model mapping, used by both BedrockResearchPartner and
    ComplementaryResearchCoordinator."""
    assert resolve_backend_model("gpt") == conf.DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL
    assert resolve_backend_model("nova") == conf.DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL


def test_get_backend_resolves_gpt():
    """Code-review follow-up: get_backend() must see RESEARCH_PARTNER_BACKENDS
    too, not just BACKENDS — "gpt" has no build_dispatcher branch but is a
    real, selectable research-partner backend."""
    from parrot.flows.dev_loop.catalog import get_backend

    backend = get_backend("gpt")
    assert backend is not None
    assert backend.id == "gpt"
    assert "research_partner" in backend.roles


def test_backends_for_role_research_partner_lists_both():
    from parrot.flows.dev_loop.catalog import backends_for_role

    ids = {b.id for b in backends_for_role("research_partner")}
    assert ids == {"gpt", "nova"}


def test_catalog_payload_surfaces_research_partner_role():
    from parrot.flows.dev_loop.catalog import catalog_payload

    getter = lambda key, fallback=None: fallback
    payload = catalog_payload(getter)
    assert payload["research_partner_backend"] == ""
    assert set(payload["roles"]["research_partner"]) == {"gpt", "nova"}
    assert "gpt" in {b["id"] for b in payload["backends"]}


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


class TestBedrockResearchPartner:
    """FEAT-482 Module 2 — one implementation, two Bedrock transports."""

    async def test_gpt_partner_uses_mantle_client(self, tmp_path):
        """Default backend builds BedrockMantleClient; no OPENAI_API_KEY read."""
        client = _make_client_mock(ResearchFindings(summary="ok"))
        with (
            patch(
                "parrot.flows.dev_flow.research_partner.BedrockMantleClient",
                return_value=client,
            ) as mock_mantle,
            patch("parrot.flows.dev_flow.research_partner.NovaClient") as mock_nova,
        ):
            partner = BedrockResearchPartner(backend="gpt")
            findings = await partner.research(
                brief=_FakeBrief(),
                question="what is the shape of X?",
                cwd=str(tmp_path),
                run_id="run-1",
                node_id="node-1",
            )
        mock_mantle.assert_called_once_with(model=conf.DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL)
        mock_nova.assert_not_called()
        assert findings.summary == "ok"

    async def test_nova_partner_uses_converse_client(self, tmp_path):
        """nova backend builds NovaClient and passes thinking_budget."""
        client = _make_client_mock(ResearchFindings(summary="ok"))
        with (
            patch(
                "parrot.flows.dev_flow.research_partner.NovaClient",
                return_value=client,
            ) as mock_nova,
            patch("parrot.flows.dev_flow.research_partner.BedrockMantleClient") as mock_mantle,
        ):
            partner = BedrockResearchPartner(backend="nova")
            await partner.research(
                brief=_FakeBrief(),
                question="q",
                cwd=str(tmp_path),
                run_id="run-1",
                node_id="node-1",
            )
        mock_mantle.assert_not_called()
        mock_nova.assert_called_once_with(model=conf.DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL)
        _, kwargs = client.ask.call_args
        assert kwargs["thinking_budget"] == conf.DEV_FLOW_RESEARCH_PARTNER_THINKING_BUDGET

    async def test_both_backends_share_one_call_shape(self, tmp_path):
        """Both invoke ask(use_tools=True, structured_output=ResearchFindings)
        with the toolkit registered — no per-transport branching in the call."""
        for backend, client_attr in (("gpt", "BedrockMantleClient"), ("nova", "NovaClient")):
            client = _make_client_mock(ResearchFindings(summary="ok"))
            with patch(
                f"parrot.flows.dev_flow.research_partner.{client_attr}",
                return_value=client,
            ):
                partner = BedrockResearchPartner(backend=backend)
                await partner.research(
                    brief=_FakeBrief(),
                    question="q",
                    cwd=str(tmp_path),
                    run_id="run-1",
                    node_id="node-1",
                )
            _, kwargs = client.ask.call_args
            assert kwargs["use_tools"] is True
            assert kwargs["structured_output"] is ResearchFindings
            client.register_tools.assert_called_once()

    async def test_reasoning_knob_is_backend_appropriate(self, tmp_path):
        """thinking_budget only on Converse; effort only on mantle."""
        gpt_client = _make_client_mock(ResearchFindings(summary="ok"))
        with patch(
            "parrot.flows.dev_flow.research_partner.BedrockMantleClient",
            return_value=gpt_client,
        ):
            partner = BedrockResearchPartner(backend="gpt")
            await partner.research(brief=_FakeBrief(), question="q", cwd=str(tmp_path), run_id="r", node_id="n")
        _, gpt_kwargs = gpt_client.ask.call_args
        assert "thinking_budget" not in gpt_kwargs

        nova_client = _make_client_mock(ResearchFindings(summary="ok"))
        with patch(
            "parrot.flows.dev_flow.research_partner.NovaClient",
            return_value=nova_client,
        ):
            partner = BedrockResearchPartner(backend="nova")
            await partner.research(brief=_FakeBrief(), question="q", cwd=str(tmp_path), run_id="r", node_id="n")
        _, nova_kwargs = nova_client.ask.call_args
        assert "thinking_budget" in nova_kwargs

    async def test_effort_set_warns_when_unused_on_gpt(self, tmp_path, monkeypatch, caplog):
        """Code-review follow-up: an operator who changes EFFORT away from
        its default should be warned it has no effect on the mantle path."""
        import logging

        monkeypatch.setattr(conf, "DEV_FLOW_RESEARCH_PARTNER_EFFORT", "low")
        client = _make_client_mock(ResearchFindings(summary="ok"))
        with (
            patch(
                "parrot.flows.dev_flow.research_partner.BedrockMantleClient",
                return_value=client,
            ),
            caplog.at_level(logging.WARNING),
        ):
            partner = BedrockResearchPartner(backend="gpt")
            await partner.research(brief=_FakeBrief(), question="q", cwd=str(tmp_path), run_id="r", node_id="n")
        assert any("DEV_FLOW_RESEARCH_PARTNER_EFFORT" in r.message for r in caplog.records)

    async def test_effort_default_does_not_warn(self, tmp_path, caplog):
        import logging

        client = _make_client_mock(ResearchFindings(summary="ok"))
        with (
            patch(
                "parrot.flows.dev_flow.research_partner.BedrockMantleClient",
                return_value=client,
            ),
            caplog.at_level(logging.WARNING),
        ):
            partner = BedrockResearchPartner(backend="gpt")
            await partner.research(brief=_FakeBrief(), question="q", cwd=str(tmp_path), run_id="r", node_id="n")
        assert not any("DEV_FLOW_RESEARCH_PARTNER_EFFORT" in r.message for r in caplog.records)

    async def test_prompt_excludes_primary_reasoning(self, tmp_path):
        """NEUTRALITY GUARD: prompt carries brief/root/question and none of the
        primary seat's framing, hypotheses, or preferred conclusion."""
        client = _make_client_mock(ResearchFindings(summary="ok"))
        brief = _FakeBrief(title="add caching to the ideation node")
        with patch(
            "parrot.flows.dev_flow.research_partner.BedrockMantleClient",
            return_value=client,
        ):
            partner = BedrockResearchPartner(backend="gpt")
            await partner.research(
                brief=brief,
                question="What are the risks of adding caching here?",
                cwd=str(tmp_path),
                run_id="r",
                node_id="n",
            )
        prompt_arg = client.ask.call_args[0][0]
        assert str(tmp_path) in prompt_arg
        assert "What are the risks of adding caching here?" in prompt_arg
        assert "add caching to the ideation node" in prompt_arg  # the brief itself
        for banned in ("I believe", "my hypothesis", "the answer is", "you should conclude"):
            assert banned not in prompt_arg

    async def test_no_write_tool_registered(self, tmp_path):
        """Registered toolkit exposes no write-shaped tool."""
        client = _make_client_mock(ResearchFindings(summary="ok"))
        with patch(
            "parrot.flows.dev_flow.research_partner.BedrockMantleClient",
            return_value=client,
        ):
            partner = BedrockResearchPartner(backend="gpt")
            await partner.research(brief=_FakeBrief(), question="q", cwd=str(tmp_path), run_id="r", node_id="n")
        (registered_tools,), _ = client.register_tools.call_args
        tool_names = {t.name for t in registered_tools}
        assert tool_names, "toolkit registered no tools at all"
        banned_substrings = ("apply_patch", "run_command", "write_file", "write")
        for name in tool_names:
            assert not any(bad in name.lower() for bad in banned_substrings), name

    def test_disabled_backend_raises(self):
        with pytest.raises(ValueError, match="disabled or misconfigured"):
            BedrockResearchPartner(backend="")

    def test_registered_under_both_factory_names(self):
        assert ResearchPartnerFactory.create("gpt", backend="gpt").backend == "gpt"
        assert ResearchPartnerFactory.create("nova", backend="nova").backend == "nova"

    def test_direct_construction_still_rejects_anthropic_model(self, monkeypatch):
        """Code-review follow-up (defense-in-depth): constructing the
        partner directly with an explicit backend= bypasses
        resolve_research_partner_backend() entirely, so _build_client()
        must independently re-validate the resolved model."""
        monkeypatch.setattr(
            conf, "DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL", "us.anthropic.claude-opus-5"
        )
        partner = BedrockResearchPartner(backend="nova")
        with pytest.raises(ValueError, match="(?s)decorrel.*400|400.*decorrel"):
            partner._build_client()
