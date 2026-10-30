"""Tests for deterministic domain-expert knowledge resolution (FEAT-778 M4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.experts.knowledge.budget import knowledge_budget
from parrot.experts.knowledge.resolver import KnowledgeResolver, LAYER_ORDER
from parrot.experts.models import (
    ExpertBundle,
    ExpertManifest,
    KnowledgeLayer,
    KnowledgeMode,
    KnowledgeSourceKind,
    KnowledgeSourceSpec,
)


class CharacterCounter:
    """Deterministic counter used by the resolver tests."""

    name = "characters"

    def count(self, text: str) -> int:
        """Return the character count.

        Args:
            text: Content to count.

        Returns:
            Number of characters in ``text``.
        """
        return len(text)


class FakeSource:
    """Fixed source adapter for resolver tests."""

    def __init__(self, kind: KnowledgeSourceKind, layers: list[KnowledgeLayer]) -> None:
        """Initialize the fake source.

        Args:
            kind: Source kind the adapter accepts.
            layers: Fixed layers returned for each matching specification.
        """
        self.kind = kind
        self._layers = layers

    async def layers(
        self,
        spec: KnowledgeSourceSpec,
        bundle: ExpertBundle,
        *,
        workspace: Path | None,
        counter: CharacterCounter,
    ) -> list[KnowledgeLayer]:
        """Return fixed layers.

        Args:
            spec: Declared source specification.
            bundle: Expert bundle being resolved.
            workspace: Optional workspace root.
            counter: Resolver token counter.

        Returns:
            A copy of the fixed layers.
        """
        return list(self._layers)


class FakeBot:
    """Duck-typed future KB hook owner."""

    async def _legacy_build_kb_context(
        self,
        question: str,
        user_id: str | None,
        session_id: str | None,
        ctx: object | None,
    ) -> tuple[str, dict[str, str]]:
        """Return a stable KB context.

        Args:
            question: User question.
            user_id: Requesting user identifier.
            session_id: Requesting session identifier.
            ctx: Request context.

        Returns:
            A fixed context and metadata mapping.
        """
        return f"KB: {question}", {"existing": "value"}


def _layer(
    layer: str,
    source: str,
    *,
    tokens: int,
    mode: KnowledgeMode = KnowledgeMode.INLINE,
) -> KnowledgeLayer:
    """Build a revisioned layer for a fake source."""
    return KnowledgeLayer(
        layer=layer,
        source=source,
        mode=mode,
        revision=f"revision-{source}",
        tokens=tokens,
        content=source if mode is KnowledgeMode.INLINE else None,
        handle={"source": source} if mode is KnowledgeMode.RETRIEVAL else None,
    )


def _bundle(tmp_path: Path) -> ExpertBundle:
    """Build a valid expert bundle declaring the fake source kinds."""
    return ExpertBundle(
        manifest=ExpertManifest(
            name="sample-expert",
            display_name="Sample Expert",
            description="Resolver test bundle",
            knowledge=[
                KnowledgeSourceSpec(source=KnowledgeSourceKind.WIKI, mode=KnowledgeMode.RETRIEVAL),
                KnowledgeSourceSpec(source=KnowledgeSourceKind.BUNDLED, mode=KnowledgeMode.INLINE),
                KnowledgeSourceSpec(source=KnowledgeSourceKind.ADR, mode=KnowledgeMode.INLINE),
            ],
        ),
        root=tmp_path,
        identity_dir=tmp_path / "identity",
    )


@pytest.mark.asyncio
async def test_resolver_layer_order_is_fixed(tmp_path: Path) -> None:
    """Resolver output follows the fixed layer order despite source registration order."""
    resolver = KnowledgeResolver(
        [
            FakeSource(KnowledgeSourceKind.WIKI, [_layer("retrieval", "wiki", tokens=0, mode=KnowledgeMode.RETRIEVAL)]),
            FakeSource(KnowledgeSourceKind.ADR, [_layer("adr", "adr", tokens=1)]),
            FakeSource(KnowledgeSourceKind.BUNDLED, [_layer("tier1_expert", "bundle", tokens=1)]),
        ],
        counter=CharacterCounter(),
    )

    context = await resolver.resolve(_bundle(tmp_path), None, None, model="claude-x")

    assert [layer.layer for layer in context.layers] == ["rules", "tier1_expert", "adr", "retrieval"]
    assert all(layer.revision for layer in context.layers)
    assert [LAYER_ORDER.index(layer.layer) for layer in context.layers] == sorted(
        LAYER_ORDER.index(layer.layer) for layer in context.layers
    )


@pytest.mark.asyncio
async def test_resolver_trims_methodology_before_tier2_never_rules(tmp_path: Path) -> None:
    """Trimming drops tier-one methodology before later tiers and preserves rules."""
    resolver = KnowledgeResolver(
        [
            FakeSource(
                KnowledgeSourceKind.BUNDLED,
                [
                    _layer("tier1_shared", "shared", tokens=4),
                    _layer("tier1_expert", "expert", tokens=3),
                    _layer("tier2_shared", "tenant", tokens=2),
                    _layer("tier2_expert", "private", tokens=2),
                ],
            ),
            FakeSource(KnowledgeSourceKind.ADR, [_layer("adr", "decision", tokens=2)]),
            FakeSource(KnowledgeSourceKind.WIKI, []),
        ],
        counter=CharacterCounter(),
    )

    context = await resolver.resolve(_bundle(tmp_path), None, None, model="claude-x", budget_tokens=8)

    assert [layer.layer for layer in context.trimmed] == ["tier1_shared", "tier1_expert"]
    assert [layer.layer for layer in context.layers] == ["rules", "tier2_shared", "tier2_expert", "adr"]
    assert context.layers[0].layer == "rules"
    assert sum(layer.tokens for layer in context.layers if layer.mode is KnowledgeMode.INLINE) <= 8


@pytest.mark.asyncio
async def test_resolver_is_deterministic(tmp_path: Path) -> None:
    """Same resolver inputs produce byte-identical serialized contexts."""
    resolver = KnowledgeResolver(
        [
            FakeSource(KnowledgeSourceKind.WIKI, [_layer("retrieval", "wiki", tokens=0, mode=KnowledgeMode.RETRIEVAL)]),
            FakeSource(KnowledgeSourceKind.BUNDLED, [_layer("tier1_expert", "bundle", tokens=2)]),
            FakeSource(KnowledgeSourceKind.ADR, [_layer("adr", "adr", tokens=2)]),
        ],
        counter=CharacterCounter(),
    )
    bundle = _bundle(tmp_path)

    first = await resolver.resolve(bundle, "research", None, model="claude-x")
    second = await resolver.resolve(bundle, "research", None, model="claude-x")

    assert first.model_dump_json() == second.model_dump_json()


def test_knowledge_budget_from_model_window() -> None:
    """Claude model windows yield the specified fixed knowledge fraction."""
    assert knowledge_budget("claude-x") == int(200_000 * 0.15)


@pytest.mark.asyncio
async def test_has_handle_and_search_kb(tmp_path: Path) -> None:
    """The resolver reports registered handles and tags legacy KB metadata."""
    resolver = KnowledgeResolver(
        [FakeSource(KnowledgeSourceKind.KB, []), FakeSource(KnowledgeSourceKind.WIKI, [])],
        counter=CharacterCounter(),
    )

    kb_context, metadata = await resolver.search_kb(FakeBot(), "What changed?", user_id="user", session_id="session")

    assert resolver.has_handle("kb")
    assert not resolver.has_handle("bookstore")
    assert kb_context == "KB: What changed?"
    assert metadata == {"existing": "value", "knowledge_source": "resolver:kb"}


@pytest.mark.asyncio
async def test_invalidate_clears_cache(tmp_path: Path) -> None:
    """Invalidation clears the last successfully resolved context."""
    resolver = KnowledgeResolver([FakeSource(KnowledgeSourceKind.WIKI, [])], counter=CharacterCounter())

    await resolver.resolve(_bundle(tmp_path), None, None, model="claude-x")
    resolver.invalidate()

    assert resolver.last_context is None
