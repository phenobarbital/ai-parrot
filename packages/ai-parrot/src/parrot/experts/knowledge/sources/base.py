"""The protocol every knowledge source adapter implements (FEAT-778 M5)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from parrot.experts.models import ExpertBundle, KnowledgeLayer, KnowledgeSourceKind, KnowledgeSourceSpec
from parrot.memory.compaction.tokens import TokenCounter


@runtime_checkable
class KnowledgeSource(Protocol):
    """Produce the layers of one knowledge-source kind for one bundle."""

    kind: KnowledgeSourceKind

    async def layers(
        self,
        spec: KnowledgeSourceSpec,
        bundle: ExpertBundle,
        *,
        workspace: Path | None,
        counter: TokenCounter,
    ) -> list[KnowledgeLayer]:
        """Return inline content or retrieval handles for one source specification."""
        ...
