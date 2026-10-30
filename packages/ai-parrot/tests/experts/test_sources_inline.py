"""Unit tests for FEAT-778 inline knowledge-source adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.experts.knowledge.budget import sha256_revision
from parrot.experts.knowledge.sources.adr import ADR_BUDGET_TOKENS, ADR_LIMIT, ADRSource
from parrot.experts.knowledge.sources.bundled import BundledSource
from parrot.experts.knowledge.sources.workspace import WorkspaceSource
from parrot.experts.loader import parse_expert_bundle
from parrot.experts.models import KnowledgeMode, KnowledgeSourceKind, KnowledgeSourceSpec
from parrot.knowledge.wiki.decisions.models import DecisionDossier, DecisionHit, DecisionLink


class CharacterCounter:
    """Deterministic counter for asserting inline layer accounting."""

    name = "characters"

    def count(self, text: str) -> int:
        """Return the text length as its token count."""
        return len(text)


class StubDecisionService:
    """Stub ADR service that records the source query contract."""

    def __init__(self, dossier: DecisionDossier) -> None:
        """Initialize the service with a fixed dossier."""
        self.dossier = dossier
        self.calls: list[tuple[str, int, int]] = []

    async def why(self, question: str, *, limit: int, budget_tokens: int) -> DecisionDossier:
        """Record the retrieval parameters and return the fixed dossier."""
        self.calls.append((question, limit, budget_tokens))
        return self.dossier


def _spec(source: KnowledgeSourceKind, *, filter_: dict[str, list[str]] | None = None) -> KnowledgeSourceSpec:
    """Build an inline source declaration for one adapter."""
    return KnowledgeSourceSpec(source=source, mode=KnowledgeMode.INLINE, filter=filter_ or {})


def _bundle(expert_bundle: Path, *, tenant: str | None = None, global_only: bool = False):
    """Parse the shared fixture and optionally create a tenant bundle view."""
    root = expert_bundle / "experts" / "sample-expert"
    bundle = parse_expert_bundle(root, tenant=tenant)
    if global_only:
        bundle = bundle.model_copy(update={"manifest": bundle.manifest.model_copy(update={"global_only": True})})
    return bundle


def _hit(
    decision_id: str,
    *,
    status: str = "accepted",
    review_status: str = "accepted",
    links: list[DecisionLink] | None = None,
) -> DecisionHit:
    """Build a minimal dossier hit with an observable revision and decision."""
    return DecisionHit(
        decision_id=decision_id,
        revision=2,
        title=f"Title {decision_id}",
        origin="documented",
        source_status=status,
        review_status=review_status,
        decision=f"Decision {decision_id}",
        applicability=links or [],
    )


@pytest.mark.asyncio
async def test_bundled_source_emits_tier1_with_revisions(expert_bundle: Path) -> None:
    """Bundled and shared Markdown files produce revisioned, counted inline layers."""
    shared_dir = expert_bundle / "shared"
    shared_dir.mkdir()
    (shared_dir / "zeta.md").write_text("Shared zeta", encoding="utf-8")
    (shared_dir / "alpha.md").write_text("Shared alpha", encoding="utf-8")
    bundle = _bundle(expert_bundle)
    counter = CharacterCounter()

    layers = await BundledSource(shared_dir).layers(_spec(KnowledgeSourceKind.BUNDLED), bundle, workspace=None, counter=counter)

    assert [(layer.layer, layer.source) for layer in layers] == [
        ("tier1_shared", "alpha.md"),
        ("tier1_shared", "zeta.md"),
        ("tier1_expert", "knowledge/method.md"),
    ]
    assert layers[-1].revision == sha256_revision((bundle.root / "knowledge" / "method.md").read_bytes())
    assert [layer.tokens for layer in layers] == [len(layer.content or "") for layer in layers]


@pytest.mark.asyncio
async def test_tenant_file_shadows_tier1(expert_bundle: Path) -> None:
    """A tenant knowledge file excludes the same-named bundle Tier-1 file."""
    bundle = _bundle(expert_bundle, tenant="acme")

    layers = await BundledSource().layers(
        _spec(KnowledgeSourceKind.BUNDLED), bundle, workspace=None, counter=CharacterCounter()
    )

    assert layers == []


@pytest.mark.asyncio
async def test_global_only_blocks_shadowing(expert_bundle: Path) -> None:
    """A global-only bundle still includes its Tier-1 file despite a tenant peer."""
    bundle = _bundle(expert_bundle, tenant="acme", global_only=True)

    layers = await BundledSource().layers(
        _spec(KnowledgeSourceKind.BUNDLED), bundle, workspace=None, counter=CharacterCounter()
    )

    assert [(layer.layer, layer.source, layer.content) for layer in layers] == [
        ("tier1_expert", "knowledge/method.md", "Use primary sources.\n")
    ]


@pytest.mark.asyncio
async def test_workspace_source_without_tenant_is_empty(expert_bundle: Path) -> None:
    """WorkspaceSource has no tenant-specific layer without a bundle tenant."""
    bundle = _bundle(expert_bundle)

    layers = await WorkspaceSource().layers(
        _spec(KnowledgeSourceKind.WORKSPACE), bundle, workspace=None, counter=CharacterCounter()
    )

    assert layers == []


@pytest.mark.asyncio
async def test_adr_source_filters_accepted_only(expert_bundle: Path) -> None:
    """Only non-rejected, accepted ADR hits produce layers across both dossier groups."""
    accepted = _hit("accepted")
    service = StubDecisionService(
        DecisionDossier(
            documented=[accepted, _hit("proposed", status="proposed"), _hit("rejected", status="rejected")],
            candidates=[_hit("superseded", status="superseded"), _hit("review-rejected", review_status="rejected")],
        )
    )
    bundle = _bundle(expert_bundle)

    layers = await ADRSource(service).layers(_spec(KnowledgeSourceKind.ADR), bundle, workspace=None, counter=CharacterCounter())

    assert [(layer.source, layer.content, layer.revision) for layer in layers] == [
        ("adr:accepted", "### Title accepted\nDecision accepted", sha256_revision(b"accepted:2"))
    ]
    assert service.calls == [(bundle.manifest.description, ADR_LIMIT, ADR_BUDGET_TOKENS)]


@pytest.mark.asyncio
async def test_adr_source_links_filter(expert_bundle: Path) -> None:
    """An ADR link filter retains hits with at least one matching target identifier."""
    matching = _hit(
        "matching",
        links=[DecisionLink(target_id="sym:match", relation="explains", provenance="asserted")],
    )
    other = _hit(
        "other",
        links=[DecisionLink(target_id="sym:other", relation="explains", provenance="asserted")],
    )
    bundle = _bundle(expert_bundle)

    layers = await ADRSource(StubDecisionService(DecisionDossier(documented=[matching, other]))).layers(
        _spec(KnowledgeSourceKind.ADR, filter_={"links": ["sym:match"]}),
        bundle,
        workspace=None,
        counter=CharacterCounter(),
    )

    assert [layer.source for layer in layers] == ["adr:matching"]
