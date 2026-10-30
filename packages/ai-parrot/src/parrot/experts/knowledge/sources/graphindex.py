"""GraphIndex (L2) retrieval handle for an expert (FEAT-778 M5)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from parrot.experts.knowledge.budget import sha256_revision
from parrot.experts.models import (ExpertBundle, KnowledgeLayer, KnowledgeMode, KnowledgeSourceKind,
                                   KnowledgeSourceSpec)
from parrot.memory.compaction.tokens import TokenCounter


class GraphIndexSource:
    """Emit a GraphIndex retrieval handle recording the intended RetrievalRequest fields."""

    kind = KnowledgeSourceKind.GRAPHINDEX

    async def layers(self, spec: KnowledgeSourceSpec, bundle: ExpertBundle, *, workspace: Path | None,
                     counter: TokenCounter) -> list[KnowledgeLayer]:
        """Return one handle-only RETRIEVAL layer (no content, zero tokens)."""
        handle: dict[str, Any] = {
            "toolkit": "graphindex",
            "scope": spec.scope,
            "workspace": str(workspace) if workspace else None,
            "budget": {"max_tokens": 4000, "max_llm_calls": 0},
        }
        return [KnowledgeLayer(layer="retrieval", source="graphindex", mode=KnowledgeMode.RETRIEVAL, tokens=0,
                               revision=sha256_revision(json.dumps(handle, sort_keys=True).encode()), handle=handle)]
