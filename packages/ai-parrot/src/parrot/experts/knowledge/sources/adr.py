"""Accepted ADRs as inline knowledge (FEAT-778 M5, consumer side)."""

from __future__ import annotations

from pathlib import Path

from parrot.experts.knowledge.budget import sha256_revision
from parrot.experts.models import ExpertBundle, KnowledgeLayer, KnowledgeMode, KnowledgeSourceKind, KnowledgeSourceSpec
from parrot.knowledge.wiki.decisions.service import DecisionService
from parrot.memory.compaction.tokens import TokenCounter

ADR_BUDGET_TOKENS = 3000
ADR_LIMIT = 10


class ADRSource:
    """Produce inline accepted, non-rejected ADR layers from ``DecisionService.why``."""

    kind = KnowledgeSourceKind.ADR

    def __init__(self, service: DecisionService) -> None:
        """Initialize the source with an injected decision service.

        Args:
            service: Service that retrieves ADR dossiers.
        """
        self.service = service

    async def layers(
        self,
        spec: KnowledgeSourceSpec,
        bundle: ExpertBundle,
        *,
        workspace: Path | None,
        counter: TokenCounter,
    ) -> list[KnowledgeLayer]:
        """Return filtered ADR hits as one inline layer per decision.

        Args:
            spec: ADR filtering declaration.
            bundle: Expert bundle whose description is the ADR query.
            workspace: Unused optional workspace root, required by the source protocol.
            counter: Token counter for emitted text.

        Returns:
            Accepted ADR layers matching the optional link filter.
        """
        dossier = await self.service.why(bundle.manifest.description, limit=ADR_LIMIT, budget_tokens=ADR_BUDGET_TOKENS)
        allowed_statuses = set(spec.filter.get("status", ["accepted"]))
        target_links = set(spec.filter.get("links", []))
        layers: list[KnowledgeLayer] = []
        for hit in [*dossier.documented, *dossier.candidates]:
            if hit.source_status not in allowed_statuses or hit.review_status == "rejected":
                continue
            if target_links and not any(link.target_id in target_links for link in hit.applicability):
                continue
            content = f"### {hit.title}\n{hit.decision}"
            layers.append(
                KnowledgeLayer(
                    layer="adr",
                    source=f"adr:{hit.decision_id}",
                    mode=KnowledgeMode.INLINE,
                    revision=sha256_revision(f"{hit.decision_id}:{hit.revision}".encode()),
                    tokens=counter.count(content),
                    content=content,
                )
            )
        return layers
