"""Legacy knowledge-base list as a retrieval handle — the U5 fold-in (FEAT-778 M5)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from parrot.experts.knowledge.budget import sha256_revision
from parrot.experts.models import (ExpertBundle, KnowledgeLayer, KnowledgeMode, KnowledgeSourceKind,
                                   KnowledgeSourceSpec)
from parrot.memory.compaction.tokens import TokenCounter


class LegacyKBSource:
    """Expose a bot's legacy knowledge bases as a retrieval handle; the search stays in the bot.

    Args:
        bot: The bot whose `knowledge_bases` list is described.
    """

    kind = KnowledgeSourceKind.KB

    def __init__(self, bot: Any) -> None:
        self.bot = bot

    async def layers(self, spec: KnowledgeSourceSpec, bundle: ExpertBundle, *, workspace: Path | None,
                     counter: TokenCounter) -> list[KnowledgeLayer]:
        """Return one handle-only RETRIEVAL layer, or `[]` when the bot has no knowledge bases."""
        kbs = list(getattr(self.bot, "knowledge_bases", None) or [])
        if not kbs:
            return []
        kbs.sort(key=lambda kb: getattr(kb, "priority", 0), reverse=True)
        handle: dict[str, Any] = {"toolkit": "kb", "names": [kb.name for kb in kbs]}
        return [KnowledgeLayer(layer="retrieval", source="kb", mode=KnowledgeMode.RETRIEVAL, tokens=0,
                               revision=sha256_revision(json.dumps(handle, sort_keys=True).encode()), handle=handle)]
