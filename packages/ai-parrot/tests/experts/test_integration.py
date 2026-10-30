"""FEAT-778 end-to-end tests — offline: in-memory wiki, recorded CVE fixtures, stubbed LLM."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from parrot.experts.activation import activate_expert
from parrot.experts.agent import ExpertAgent
from parrot.experts.knowledge.resolver import KnowledgeResolver
from parrot.experts.knowledge.sources.bundled import BundledSource
from parrot.experts.knowledge.sources.workspace import WorkspaceSource
from parrot.experts.loader import BUNDLED_EXPERTS_DIR, parse_expert_bundle
from parrot.experts.models import KnowledgeContext, KnowledgeLayer, KnowledgeMode
from parrot.experts.registry import ExpertRegistry
from parrot.experts.policy import model_config_for
from parrot.knowledge.wiki.decisions.models import DecisionDossier, DecisionHit
from parrot.knowledge.wiki.file_store import InMemoryWikiStore
from parrot.observability.context import current_agent_name, current_seat
from parrot.registry.registry import AgentRegistry
from parrot_tools.experts import ExpertKnowledgeToolkit
from parrot_tools.security.cve import CVEToolkit
from parrot_tools.security.cve.toolkit import EPSS_URL, NVD_CVE_URL, OSV_VULN_URL


class _WikiToolkit:
    """Minimal wiki-toolkit seam backed by one isolated in-memory store."""

    def __init__(self, store: InMemoryWikiStore) -> None:
        """Initialize the fake with its shared store."""
        self.store = store

    def _store_for(self, name: str) -> InMemoryWikiStore:
        """Return the configured store for every expert namespace."""
        return self.store

    def get_tools(self) -> list[object]:
        """Expose no LLM-callable tools in these offline tests."""
        return []


class _DecisionService:
    """Small accepted-ADR reader and inferred-ADR writer for the integration seam."""

    def __init__(self) -> None:
        """Initialize with one accepted decision."""
        self.dossier = DecisionDossier(
            documented=[
                DecisionHit(
                    decision_id="accepted-1",
                    revision=1,
                    title="Accepted decision",
                    origin="documented",
                    source_status="accepted",
                    review_status="accepted",
                    decision="Accepted ADR text",
                )
            ]
        )

    async def why(self, question: str, *, limit: int, budget_tokens: int) -> DecisionDossier:
        """Return the current dossier without an LLM request."""
        return self.dossier

    async def generate(self, target: str) -> SimpleNamespace:
        """Record an unreviewed inference that ADR resolution must exclude."""
        self.dossier.candidates.append(
            DecisionHit(
                decision_id="inferred-1",
                revision=1,
                title="Inferred decision",
                origin="inferred",
                source_status="inferred",
                review_status="unreviewed",
                decision="Inferred ADR text",
            )
        )
        return SimpleNamespace(decision_ids=["inferred-1"], reused=[])


@pytest.fixture(autouse=True)
def _stub_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent expert construction from loading a provider-backed guardrail."""
    import parrot.bots.guardrails.builtin.prompt_injection as prompt_injection

    monkeypatch.setattr(prompt_injection, "_get_shared_injection_detector", lambda: MagicMock())


@pytest.fixture
def registry(tmp_path: Path) -> ExpertRegistry:
    """Build a fresh expert registry with one in-memory wiki store."""
    return ExpertRegistry(
        agent_registry=AgentRegistry(),
        agents_dir=tmp_path,
        bundled_dir=None,
        wiki_toolkit=_WikiToolkit(InMemoryWikiStore(tmp_path / "wiki")),
    )


def _prompt(agent: Any) -> str:
    """Render an already configured agent's static system prompt."""
    assert agent.prompt_builder is not None
    return agent.prompt_builder.build({})


@pytest.mark.asyncio
async def test_bundle_to_prompt_roundtrip(expert_bundle: Path, governance_dir: Path) -> None:
    """A workspace bundle flows through registry construction into rendered layers."""
    store = InMemoryWikiStore(expert_bundle / "wiki")
    registry = ExpertRegistry(
        agent_registry=AgentRegistry(),
        agents_dir=expert_bundle,
        bundled_dir=None,
        workspace=governance_dir,
        wiki_toolkit=_WikiToolkit(store),
    )

    assert await registry.load() == 1
    agent = registry.get("sample-expert")
    await agent.configure()
    prompt = _prompt(agent)

    assert "You are a sample expert." in prompt
    assert "<governance_rules>" in prompt
    assert prompt.index("## org") < prompt.index("## expert")
    assert "Use primary sources." in prompt
    assert 'revision="' in prompt


@pytest.mark.asyncio
async def test_tenant_overlay_changes_knowledge_not_rules(expert_bundle: Path, governance_dir: Path) -> None:
    """A tenant view shadows Tier-1 text while retaining the identical rule chain."""
    bundle_root = expert_bundle / "experts" / "sample-expert"
    manifest_path = bundle_root / "expert.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + "  - {source: workspace, mode: inline}\n", encoding="utf-8"
    )
    global_bundle = parse_expert_bundle(bundle_root)
    tenant_bundle = parse_expert_bundle(bundle_root, tenant="acme")
    resolver = KnowledgeResolver([BundledSource(), WorkspaceSource()])

    global_context = await resolver.resolve(global_bundle, None, governance_dir, model="test")
    tenant_context = await resolver.resolve(tenant_bundle, None, governance_dir, model="test")

    assert global_context.inline_text("rules") == tenant_context.inline_text("rules")
    assert "Use primary sources." in global_context.inline_text("tier1_expert")
    assert "Use Acme primary sources." in tenant_context.inline_text("tier2_expert")
    assert "Use primary sources." not in tenant_context.inline_text("tier1_expert")


@pytest.mark.asyncio
async def test_adr_consume_then_propose() -> None:
    """Accepted ADRs resolve inline, while newly inferred ADRs remain unreviewed."""
    decisions = _DecisionService()
    manifest = parse_expert_bundle(BUNDLED_EXPERTS_DIR / "cve-analyst").manifest
    context = KnowledgeContext(
        expert=manifest.name,
        budget_tokens=100,
        layers=[
            KnowledgeLayer(
                layer="retrieval",
                source="wiki",
                mode=KnowledgeMode.RETRIEVAL,
                revision="wiki",
                handle={"wiki_name": "expert-cve-analyst"},
            )
        ],
    )
    toolkit = ExpertKnowledgeToolkit(context, manifest, decisions=decisions)

    accepted = await decisions.why("cve", limit=10, budget_tokens=3000)
    assert accepted.documented[0].decision == "Accepted ADR text"
    proposal = await toolkit.propose_adr("dependency-policy", "Keep releases safe")
    next_dossier = await decisions.why("cve", limit=10, budget_tokens=3000)

    assert proposal["origin"] == "inferred"
    assert proposal["review_status"] == "unreviewed"
    assert [item.decision_id for item in next_dossier.documented] == ["accepted-1"]
    assert all(item.review_status != "accepted" for item in next_dossier.candidates)


@pytest.mark.asyncio
async def test_concurrent_activations_do_not_share_builders(expert_bundle: Path) -> None:
    """Concurrent activation scopes retain each expert's attribution and builder instance."""
    bundle = parse_expert_bundle(expert_bundle / "experts" / "sample-expert")
    resolver = KnowledgeResolver([BundledSource()])
    model_config = model_config_for(bundle.manifest.tier)
    first = ExpertAgent(bundle, resolver=resolver, model_config=model_config, toolkits=[], allowed_tools=[])
    second = ExpertAgent(bundle, resolver=resolver, model_config=model_config, toolkits=[], allowed_tools=[])
    await asyncio.gather(first.configure(), second.configure())

    async def observe(agent: Any, stage: str) -> tuple[str | None, str | None]:
        """Capture context-local attribution after an async scheduling boundary."""
        async with activate_expert(agent, run_id=stage, stage=stage):
            await asyncio.sleep(0)
            return current_agent_name.get(), current_seat.get()

    first_observation, second_observation = await asyncio.gather(observe(first, "research"), observe(second, "review"))
    assert first_observation == ("sample-expert", "research.sample-expert")
    assert second_observation == ("sample-expert", "review.sample-expert")
    assert first.prompt_builder is not second.prompt_builder


@pytest.mark.asyncio
async def test_fresh_install_loads_both_cve_experts(tmp_path: Path) -> None:
    """A fresh workspace loads and seeds both packaged CVE expert namespaces."""
    store = InMemoryWikiStore(tmp_path / "wiki")
    registry = ExpertRegistry(
        agent_registry=AgentRegistry(),
        agents_dir=tmp_path,
        bundled_dir=BUNDLED_EXPERTS_DIR,
        wiki_toolkit=_WikiToolkit(store),
    )

    assert await registry.load() == 2
    assert registry.names() == ["cve-analyst", "cve-remediation"]
    assert {item.name for item in registry.agent_registry.get_bots_by_tag("origin:bundled")} == {
        "cve-analyst",
        "cve-remediation",
    }
    for name in registry.names():
        agent = registry.get(name)
        await agent.configure()
        prompt = _prompt(agent)
        assert agent.knowledge_context is not None
        assert "<governance_rules>" in prompt
        assert "<expert_knowledge>" in prompt
        assert any(
            layer.source == f"wiki:expert-{name}" and layer.handle["documents"] > 0
            for layer in agent.knowledge_context.layers
        )


@pytest.mark.asyncio
async def test_cve_analyst_download_then_resolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A recorded CVE download increments the analyst wiki handle on the next resolve."""
    store = InMemoryWikiStore(tmp_path / "wiki")
    registry = ExpertRegistry(
        agent_registry=AgentRegistry(),
        agents_dir=tmp_path,
        bundled_dir=BUNDLED_EXPERTS_DIR,
        wiki_toolkit=_WikiToolkit(store),
    )
    assert await registry.load() == 2
    analyst = registry.get("cve-analyst")
    toolkit = CVEToolkit(store_resolver=lambda _: store, sources_dir=tmp_path / "sources", enrich_epss=True)
    fixture_dir = Path(__file__).parents[3] / "ai-parrot-tools" / "tests" / "security" / "cve" / "fixtures"
    cve_id = "CVE-2026-98432"
    routes = {
        OSV_VULN_URL.format(cve_id=cve_id): (200, json.loads((fixture_dir / f"osv_{cve_id}.json").read_text())),
        NVD_CVE_URL.format(cve_id=cve_id): (200, json.loads((fixture_dir / f"nvd_{cve_id}.json").read_text())),
        EPSS_URL.format(cve_id=cve_id): (200, json.loads((fixture_dir / f"epss_{cve_id}.json").read_text())),
    }

    async def recorded_get_json(url: str, **_: Any) -> tuple[int, dict[str, Any]]:
        """Return the task's recorded CVE responses without opening a socket."""
        return routes[url]

    monkeypatch.setattr(toolkit, "_get_json", recorded_get_json)
    before = await analyst.knowledge_resolver.resolve(
        analyst.bundle, None, analyst.workspace, model=analyst.model_config.model
    )
    async with activate_expert(analyst, run_id="run-cve", stage="research"):
        receipt = await toolkit.download_cve(cve_id)
    after = await analyst.knowledge_resolver.resolve(
        analyst.bundle, None, analyst.workspace, model=analyst.model_config.model
    )

    assert receipt["concept_id"] == f"expert-cve-analyst/cve/{cve_id}"
    assert next(layer for layer in after.layers if layer.source == "wiki:expert-cve-analyst").handle["documents"] == (
        next(layer for layer in before.layers if layer.source == "wiki:expert-cve-analyst").handle["documents"] + 1
    )


@pytest.mark.asyncio
async def test_expert_with_kb_request_time_knowledge(expert_bundle: Path) -> None:
    """Observe the current boundary: request-time KB content is not a static rendered expert layer."""
    store = InMemoryWikiStore(expert_bundle / "wiki")
    registry = ExpertRegistry(
        agent_registry=AgentRegistry(),
        agents_dir=expert_bundle,
        bundled_dir=None,
        wiki_toolkit=_WikiToolkit(store),
    )
    assert await registry.load() == 1
    agent = registry.get("sample-expert")
    await agent.configure()

    request_time_kb = "REQUEST_TIME_KB_SENTINEL"
    assert request_time_kb not in _prompt(agent)
