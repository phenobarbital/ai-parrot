"""Deterministic, budgeted knowledge resolution for an expert (FEAT-778 M4)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final, Sequence

from parrot.experts.knowledge.budget import knowledge_budget
from parrot.experts.knowledge.sources.base import KnowledgeSource
from parrot.experts.models import ExpertBundle, KnowledgeContext, KnowledgeLayer, KnowledgeMode
from parrot.experts.rules import resolve_chain, rules_to_layer
from parrot.memory.compaction.tokens import TokenCounter, get_default_counter

LAYER_ORDER: Final[tuple[str, ...]] = (
    "rules",
    "tier1_shared",
    "tier1_expert",
    "tier2_shared",
    "tier2_expert",
    "adr",
    "stage_input",
    "retrieval",
)
TRIM_ORDER: Final[tuple[str, ...]] = ("tier1_shared", "tier1_expert", "adr", "tier2_shared", "tier2_expert")


class KnowledgeResolver:
    """Pure resolver over injected sources with a cached context for the KB hook."""

    def __init__(self, sources: Sequence[KnowledgeSource], *, counter: TokenCounter | None = None) -> None:
        """Initialize the resolver.

        Args:
            sources: Source adapters eligible to resolve manifest entries.
            counter: Token counter for rules and source adapters.
        """
        self._sources = list(sources)
        self._counter = counter or get_default_counter()
        self.last_context: KnowledgeContext | None = None
        self.logger = logging.getLogger(__name__)

    async def resolve(
        self,
        expert: ExpertBundle,
        stage: str | None,
        workspace: Path | None,
        *,
        model: str | None,
        budget_tokens: int | None = None,
    ) -> KnowledgeContext:
        """Resolve ordered layers and trim inline content to the budget.

        Rules and stage input layers remain available even when they exceed the
        budget, because neither layer is eligible for trimming.

        Args:
            expert: Bundle whose declared sources are resolved.
            stage: Optional stage name associated with the context.
            workspace: Optional governance workspace root.
            model: Active model name used to derive the default budget.
            budget_tokens: Explicit budget overriding the model-derived budget.

        Returns:
            A deterministically ordered, budgeted knowledge context.
        """
        budget = budget_tokens if budget_tokens is not None else knowledge_budget(model)
        layers: list[KnowledgeLayer] = [rules_to_layer(resolve_chain(workspace, expert), self._counter)]
        for spec in expert.manifest.knowledge:
            for source in self._sources:
                if source.kind == spec.source:
                    layers.extend(await source.layers(spec, expert, workspace=workspace, counter=self._counter))

        layers.sort(key=lambda layer: (LAYER_ORDER.index(layer.layer), layer.source))
        trimmed: list[KnowledgeLayer] = []

        while sum(layer.tokens for layer in layers if layer.mode is KnowledgeMode.INLINE) > budget:
            removed = False
            for layer_name in TRIM_ORDER:
                for index in range(len(layers) - 1, -1, -1):
                    if layers[index].layer == layer_name:
                        trimmed.append(layers.pop(index))
                        removed = True
                        break
                if removed:
                    break
            if not removed:
                self.logger.warning("Knowledge context exceeds its budget but contains only untrimmable layers")
                break

        ctx = KnowledgeContext(
            expert=expert.manifest.name,
            stage=stage,
            budget_tokens=budget,
            layers=layers,
            trimmed=trimmed,
        )
        self.last_context = ctx
        return ctx

    def has_handle(self, kind: str) -> bool:
        """Return whether a source of the requested kind is registered.

        Args:
            kind: Serialized knowledge source kind.

        Returns:
            ``True`` when a matching source adapter is registered.
        """
        return any(source.kind.value == kind for source in self._sources)

    async def search_kb(
        self,
        bot: Any,
        question: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        ctx: Any = None,
    ) -> tuple[str, dict[str, Any]]:
        """Run the bot's legacy KB search and tag its metadata.

        Args:
            bot: Bot providing the future legacy KB hook.
            question: Question to search.
            user_id: Optional requesting user identifier.
            session_id: Optional requesting session identifier.
            ctx: Optional request context.

        Returns:
            The KB context and metadata tagged with the resolver source.
        """
        kb_context, metadata = await bot._legacy_build_kb_context(question, user_id, session_id, ctx)
        metadata["knowledge_source"] = "resolver:kb"
        return kb_context, metadata

    def invalidate(self) -> None:
        """Drop the cached context after knowledge-base registration."""
        self.last_context = None
