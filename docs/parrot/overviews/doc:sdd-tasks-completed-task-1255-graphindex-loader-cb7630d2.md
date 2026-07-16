---
type: Wiki Overview
title: 'TASK-1255: Loader-Based Extractor — ai-parrot-loaders + PageIndex Integration'
id: doc:sdd-tasks-completed-task-1255-graphindex-loader-extractor-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements the **loader-based extraction** pipeline for GraphIndex.
  It bridges ai-parrot's existing loader ecosystem and PageIndex hierarchical indexing
  system to produce `UniversalNode` / `UniversalEdge` instances from documents (PDF,
  Markdown, DOCX, audio/video transc
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.extractors.loader
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
---

# TASK-1255: Loader-Based Extractor — ai-parrot-loaders + PageIndex Integration

**Feature**: FEAT-187 — GraphIndex — Structured Knowledge Graph Indexing
**Spec**: `sdd/specs/graphindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1253
**Assigned-to**: unassigned

---

## Context

This task implements the **loader-based extraction** pipeline for GraphIndex. It bridges ai-parrot's existing loader ecosystem and PageIndex hierarchical indexing system to produce `UniversalNode` / `UniversalEdge` instances from documents (PDF, Markdown, DOCX, audio/video transcripts, web pages, etc.).

Hierarchical content (documents with headings/sections) is routed through `build_page_index` / `md_to_tree` to produce Section nodes carrying PageIndex metadata. Flat content (transcripts, plain text) produces a single Document node.

This is one of three parallel extractors (code, loader, skill) that feed into the embedding and assembly stages.

Implements: Spec §3 Module 2 (Loader Extractor).

---

## Scope

- Accept any ai-parrot-loaders `AbstractLoader` instance
- Route **hierarchical content** (PDF, MD, DOCX with headings, ebook) through `build_page_index` / `md_to_tree`:
  - Emit `Section` nodes carrying PageIndex metadata: `node_id`, `start_index`, `end_index`, `summary`
  - Build `contains` edges for parent-child section relationships
- Route **flat content** (audio/video transcript, plain web) to a single `Document` node with `domain_tags={"flat": true}`
- Detect hierarchical vs flat content via a loader-type mapping or content probing (no `loader.is_hierarchical()` exists)
- Handle loader failures gracefully: log the error and skip the document
- `PageIndexLLMAdapter` is required for hierarchical path — make it an optional dependency with fallback to first-N-chars summary when unavailable
- Create the `loader.py` module in the extractors sub-package

**NOT in scope**: SKILL.md extraction, embedding, code extraction, graph assembly, analytics

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py` | CREATE | Loader-based extractor with PageIndex integration and flat content fallback |
| `packages/ai-parrot/tests/knowledge/graphindex/test_loader_extractor.py` | CREATE | Unit tests for loader extractor |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex.schema import (
    UniversalNode,       # from TASK-1253
    UniversalEdge,       # from TASK-1253
    NodeKind,            # DOCUMENT, SECTION, SYMBOL, CONCEPT, RATIONALE, SKILL
    EdgeKind,            # CONTAINS, REFERENCES, DEFINES, MENTIONS, EXPLAINS
    Provenance,          # EXTRACTED, INFERRED, AMBIGUOUS
)
from parrot.pageindex import (
    build_page_index,    # builds hierarchical index from markdown
    md_to_tree,          # parses markdown into tree structure
    PageIndexLLMAdapter, # LLM-powered summary generation for sections
    PageIndexNode,       # node in the page index tree
)
# from parrot_loaders import <loader>
# AbstractLoader._load(source) -> List[Document]
# Document has page_content (str) and metadata (dict)
```

### Does NOT Exist
- ~~`loader.is_hierarchical()`~~ — no method to detect hierarchical content; must detect via loader-type mapping or content probing
- ~~`AbstractClient.embed()`~~ — embeddings are NOT this task's concern; use `parrot.embeddings.EmbeddingModel` in a separate stage
- ~~`parrot.knowledge.graphindex.extractors.loader`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Loader types known to produce hierarchical content
HIERARCHICAL_LOADERS: set[str] = {"PDFLoader", "MarkdownLoader", "DOCXLoader", "EpubLoader"}

class LoaderExtractor:
    """Extract document structure from ai-parrot-loaders output.

    Routes hierarchical content through PageIndex for section-level
    extraction, and flat content to a single Document node.

    Args:
        llm_adapter: Optional PageIndexLLMAdapter for section summaries.
            If None, falls back to first-N-chars summary.
        summary_length: Number of characters for fallback summary.
    """

    def __init__(
        self,
        llm_adapter: Optional["PageIndexLLMAdapter"] = None,
        summary_length: int = 200,
    ) -> None:
        self.llm_adapter = llm_adapter
        self.summary_length = summary_length

    async def extract(
        self, loader, source: str
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Run loader, detect content type, and extract nodes/edges."""
        try:
            documents = await loader._load(source)
        except Exception as exc:
            logger.error("Loader failed for %s: %s", source, exc)
            return [], []
        ...

    def _is_hierarchical(self, loader) -> bool:
        """Detect if loader produces hierarchical content."""
        return type(loader).__name__ in HIERARCHICAL_LOADERS

    async def _extract_hierarchical(
        self, documents, source_uri: str
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Route through build_page_index / md_to_tree for section nodes."""
        ...

    def _extract_flat(
        self, documents, source_uri: str
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Emit a single Document node with domain_tags={"flat": true}."""
        ...

    def _fallback_summary(self, text: str) -> str:
        """First-N-chars summary when LLM adapter is unavailable."""
        return text[:self.summary_length].strip()
```

### Key Constraints
- Async-first, type-hinted, Google-style docstrings
- Loader failures must NOT crash the pipeline — log and return empty lists
- PageIndexLLMAdapter is optional — code must work without it using fallback summaries
- Section nodes must carry PageIndex metadata in `domain_tags`: `node_id`, `start_index`, `end_index`
- Section summaries go in the `summary` field of `UniversalNode`
- Flat content produces exactly one `Document` node per loader invocation
- `contains` edges connect parent sections to child sections in the hierarchy

---

## Acceptance Criteria

- [ ] Accepts any ai-parrot-loaders `AbstractLoader` instance
- [ ] Hierarchical content routed through `build_page_index` / `md_to_tree` producing Section nodes
- [ ] Section nodes carry PageIndex metadata: `node_id`, `start_index`, `end_index`, `summary`
- [ ] Flat content produces a single Document node with `domain_tags={"flat": true}`
- [ ] Loader failures handled gracefully (log + skip, no crash)
- [ ] Works without `PageIndexLLMAdapter` (fallback to first-N-chars summary)
- [ ] `contains` edges emitted for parent-child section relationships
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_loader_extractor.py -v`
- [ ] Import works: `from parrot.knowledge.graphindex.extractors.loader import LoaderExtractor`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.knowledge.graphindex.extractors.loader import LoaderExtractor
from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, NodeKind, EdgeKind,
)


class FakeDocument:
    def __init__(self, page_content: str, metadata: dict | None = None):
        self.page_content = page_content
        self.metadata = metadata or {}


class TestLoaderExtractor:
    @pytest.fixture
    def extractor(self):
        return LoaderExtractor()

    @pytest.fixture
    def extractor_with_llm(self):
        adapter = MagicMock()
        return LoaderExtractor(llm_adapter=adapter)

    @pytest.mark.asyncio
    async def test_flat_content_single_document_node(self, extractor):
        loader = AsyncMock()
        loader._load = AsyncMock(return_value=[FakeDocument("Plain text transcript.")])
        type(loader).__name__ = "AudioLoader"
        nodes, edges = await extractor.extract(loader, "audio.mp3")
        doc_nodes = [n for n in nodes if n.kind == NodeKind.DOCUMENT]
        assert len(doc_nodes) == 1
        assert doc_nodes[0].domain_tags.get("flat") is True

    @pytest.mark.asyncio
    async def test_hierarchical_content_section_nodes(self, extractor):
        loader = AsyncMock()
        loader._load = AsyncMock(return_value=[
            FakeDocument("# Heading 1\nContent\n## Heading 2\nMore content")
        ])
        type(loader).__name__ = "MarkdownLoader"
        nodes, edges = await extractor.extract(loader, "doc.md")
        section_nodes = [n for n in nodes if n.kind == NodeKind.SECTION]
        assert len(section_nodes) > 0

    @pytest.mark.asyncio
    async def test_hierarchical_emits_contains_edges(self, extractor):
        loader = AsyncMock()
        loader._load = AsyncMock(return_value=[
            FakeDocument("# Parent\n## Child\nContent")
        ])
        type(loader).__name__ = "MarkdownLoader"
        nodes, edges = await extractor.extract(loader, "doc.md")
        contains_edges = [e for e in edges if e.kind == EdgeKind.CONTAINS]
        assert len(contains_edges) > 0

    @pytest.mark.asyncio
    async def test_loader_failure_returns_empty(self, extractor):
        loader = AsyncMock()
        loader._load = AsyncMock(side_effect=RuntimeError("File not found"))
        nodes, edges = await extractor.extract(loader, "missing.pdf")
        assert nodes == []
        assert edges == []

    @pytest.mark.asyncio
    async def test_fallback_summary_without_llm_adapter(self, extractor):
        assert extractor.llm_adapter is None
        summary = extractor._fallback_summary("A" * 300)
        assert len(summary) <= 200

    def test_is_hierarchical_detection(self, extractor):
        pdf_loader = MagicMock()
        type(pdf_loader).__name__ = "PDFLoader"
        assert extractor._is_hierarchical(pdf_loader) is True

        audio_loader = MagicMock()
        type(audio_loader).__name__ = "AudioLoader"
        assert extractor._is_hierarchical(audio_loader) is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/graphindex.spec.md` for full context
2. **Check dependencies** — TASK-1253 must be completed (provides `UniversalNode`, `UniversalEdge`, etc.)
3. **Verify the Codebase Contract** — confirm schema imports and PageIndex imports work
4. **Update status** in `sdd/tasks/index/graphindex.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1255-graphindex-loader-extractor.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
