"""Two-Step Chain-of-Thought ingestion: raw content -> clean markdown.

Step 1 (lightweight model): an open-ended Chain-of-Thought analysis of
the content, returned as prose.
Step 2 (heavy model): structured markdown generation grounded on the
Step-1 analysis and the original content.

The resulting :class:`IngestedMarkdown` can then be fed to
:func:`parrot.knowledge.pageindex.md_builder.md_to_tree` to produce a subtree
ready for :func:`parrot.knowledge.pageindex.tree_ops.splice_subtree`.
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from .llm_adapter import PageIndexLLMAdapter
from .prompts import (
    INGEST_STEP1_SYSTEM,
    INGEST_STEP1_USER,
    INGEST_STEP2_SYSTEM,
    INGEST_STEP2_USER,
)


logger = logging.getLogger("parrot.knowledge.pageindex.ingest")


# Step-1 content is fed to a small/cheap model so we cap it aggressively.
_STEP1_CONTENT_LIMIT = 8000


class IngestedMarkdown(BaseModel):
    """Structured output of the Step-2 markdown generator."""

    title: str = Field(description="H1 title of the generated document")
    summary: str = Field(description="One or two sentence summary")
    markdown: str = Field(description="Well-formed markdown body")


class TwoStepIngester:
    """Drive the two-step ingest pipeline against an LLM adapter.

    Args:
        adapter: The "heavy" adapter used for Step 2 (markdown generation).
        lightweight_adapter: Optional dedicated adapter for Step 1. When
            provided, Step 1 runs against this adapter (typically wrapping
            the same client but pinned to a smaller model). When omitted,
            ``adapter`` is used for both steps.
    """

    def __init__(
        self,
        adapter: PageIndexLLMAdapter,
        lightweight_adapter: Optional[PageIndexLLMAdapter] = None,
    ):
        self._heavy = adapter
        self._light = lightweight_adapter or adapter

    async def ingest(
        self,
        content: str,
        hint: Optional[str] = None,
    ) -> IngestedMarkdown:
        """Run both steps and return the structured markdown."""
        analysis = await self._step1_analyze(content, hint)
        return await self._step2_generate(content, analysis, hint)

    async def _step1_analyze(self, content: str, hint: Optional[str]) -> str:
        prompt = INGEST_STEP1_USER.format(
            hint=hint or "(none)",
            content=content[:_STEP1_CONTENT_LIMIT],
        )
        result = await self._light.ask(
            prompt=prompt,
            system_prompt=INGEST_STEP1_SYSTEM,
            temperature=0.0,
        )
        return result or ""

    async def _step2_generate(
        self,
        content: str,
        analysis: str,
        hint: Optional[str],
    ) -> IngestedMarkdown:
        prompt = INGEST_STEP2_USER.format(
            hint=hint or "(none)",
            analysis=analysis,
            content=content,
        )
        result = await self._heavy.ask_structured(
            prompt=prompt,
            output_type=IngestedMarkdown,
            system_prompt=INGEST_STEP2_SYSTEM,
            temperature=0.0,
        )
        if isinstance(result, IngestedMarkdown):
            return result
        if isinstance(result, dict):
            return IngestedMarkdown.model_validate(result)
        raise ValueError(
            f"Step-2 ingest returned unexpected payload type: {type(result).__name__}"
        )
