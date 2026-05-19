# TASK-1262: Pipeline Builder — GraphIndexBuilder Orchestrator

**Feature**: FEAT-187 — GraphIndex — Structured Knowledge Graph Indexing
**Spec**: `sdd/specs/graphindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1254, TASK-1255, TASK-1256, TASK-1257, TASK-1258, TASK-1259, TASK-1260, TASK-1261
**Assigned-to**: unassigned

---

## Context

The `GraphIndexBuilder` is the top-level orchestrator that wires together all 6 pipeline stages into a coherent build process. It is the primary entry point for both full reindex and incremental per-document refresh. This task integrates every preceding module — extractors, embeddings, graph assembly, resolution, persistence, and analytics — into a single callable interface.

This is the integration task and depends on ALL prior GraphIndex tasks being complete.

Implements: Spec §3 Pipeline Orchestrator, §4 Incremental Refresh.

---

## Scope

- Implement `GraphIndexBuilder` class orchestrating all 6 stages in sequence:
  1. Extraction (TASK-1254/1255/1256 — extractors run concurrently)
  2. Embedding (TASK-1257 — FAISS index construction)
  3. Graph assembly (TASK-1258 — rustworkx PyDiGraph)
  4. Cross-domain resolution (TASK-1259 — inferred edges)
  5. Persistence (TASK-1260 — ArangoDB + pgvector)
  6. Analytics + Report (TASK-1261 — centrality, report)
- Provide `build(sources, ctx)` for full reindex
- Provide `ingest_document(uri, ctx)` for incremental per-document refresh:
  - Re-run stages 1-5 for the changed document only
  - Diff-and-merge replaces the document's slice atomically
- Support `.graphindexignore` via `pathspec` library for file exclusion
- Provide `regenerate_report(ctx)` for on-demand report refresh (lazy, not automatic on incremental)
- Extractors run concurrently in stage 1 via `asyncio.gather`
- Write unit tests for the builder orchestration

**NOT in scope**: Flowtask integration (TASK-1264), toolkit (TASK-1263), file-watcher-based change detection (v2), automatic report regeneration on incremental

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` | CREATE | GraphIndexBuilder orchestrator: build(), ingest_document(), regenerate_report() |
| `packages/ai-parrot/tests/knowledge/graphindex/test_builder.py` | CREATE | Unit tests for builder orchestration |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All stage modules created by prior tasks:
from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, SourceConfig, BuildResult, IngestResult,
)
# Extractors (TASK-1254, TASK-1255, TASK-1256):
# from parrot.knowledge.graphindex.extractors.document import DocumentExtractor
# from parrot.knowledge.graphindex.extractors.code import CodeExtractor
# from parrot.knowledge.graphindex.extractors.concept import ConceptExtractor

# Embedding (TASK-1257):
# from parrot.knowledge.graphindex.embed import build_faiss_index

# Assembly (TASK-1258):
# from parrot.knowledge.graphindex.assemble import assemble_graph

# Resolution (TASK-1259):
# from parrot.knowledge.graphindex.resolve import resolve_cross_domain

# Persistence (TASK-1260):
# from parrot.knowledge.graphindex.persist import GraphIndexPersistence

# Analytics (TASK-1261):
# from parrot.knowledge.graphindex.analytics import compute_analytics, generate_report

from parrot.knowledge.ontology.schema import TenantContext
import pathspec  # for .graphindexignore support
```

### Does NOT Exist
- ~~file-watcher-based change detection~~ — v2; incremental is explicit via `ingest_document()`
- ~~automatic report regeneration on incremental~~ — report regeneration is lazy/explicit via `regenerate_report()`
- ~~`GraphIndexBuilder.watch()`~~ — no file-watching in v1
- ~~`pathspec` in current dependencies~~ — may need to be added to pyproject.toml (TASK-1264 handles this)

---

## Implementation Notes

### Pattern to Follow
```python
import asyncio
import logging
from pathlib import Path
from typing import Optional

class GraphIndexBuilder:
    """Orchestrates the full GraphIndex pipeline.

    Wires together extraction, embedding, assembly, resolution,
    persistence, and analytics into build() and ingest_document() flows.
    """

    def __init__(
        self,
        persistence: GraphIndexPersistence,
        output_dir: Path,
        ignore_file: Optional[Path] = None,
    ):
        self.persistence = persistence
        self.output_dir = output_dir
        self.logger = logging.getLogger(__name__)
        self._ignore_spec = self._load_ignore(ignore_file)

    def _load_ignore(self, ignore_file: Optional[Path]) -> Optional[pathspec.PathSpec]:
        """Load .graphindexignore patterns."""
        if ignore_file and ignore_file.exists():
            return pathspec.PathSpec.from_lines("gitwildmatch", ignore_file.read_text().splitlines())
        return None

    async def build(self, sources: SourceConfig, ctx: TenantContext) -> BuildResult:
        """Full reindex: run all 6 stages sequentially (extractors concurrent)."""
        # Stage 1: Extract (concurrent)
        doc_nodes, code_nodes, concept_nodes = await asyncio.gather(
            self._extract_documents(sources, ctx),
            self._extract_code(sources, ctx),
            self._extract_concepts(sources, ctx),
        )
        all_nodes = doc_nodes + code_nodes + concept_nodes
        # Stage 2-6: sequential
        ...

    async def ingest_document(self, uri: str, ctx: TenantContext) -> IngestResult:
        """Incremental: re-process a single document and replace its slice."""
        ...

    async def regenerate_report(self, ctx: TenantContext) -> Path:
        """On-demand report refresh from persisted graph state."""
        ...
```

### Key Constraints
- Async-first, type-hinted, Google-style docstrings
- Extractors MUST run concurrently via `asyncio.gather` in stage 1
- Stages 2-6 run sequentially (each depends on previous output)
- `.graphindexignore` uses `pathspec` with `gitwildmatch` pattern
- `ingest_document` must call `persistence.replace_document_slice()` for atomicity
- `regenerate_report` is a separate explicit call, not triggered by `ingest_document`

---

## Acceptance Criteria

- [ ] `build()` executes all 6 stages in correct order
- [ ] Extractors run concurrently in stage 1
- [ ] `ingest_document()` processes single document and replaces its slice atomically
- [ ] `.graphindexignore` support via pathspec works correctly
- [ ] `regenerate_report()` generates report on demand
- [ ] Report is NOT automatically regenerated on `ingest_document()`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_builder.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.knowledge.graphindex.schema import SourceConfig, BuildResult, IngestResult

class TestGraphIndexBuilder:
    async def test_build_runs_all_stages(self):
        """build() must call all 6 stages in order."""
        # Setup: mock all stage functions
        # Assert: all called, in correct order

    async def test_extractors_run_concurrently(self):
        """Stage 1 extractors must run via asyncio.gather."""
        # Setup: mock extractors with timing
        # Assert: extractors started concurrently, not sequentially

    async def test_ingest_document_replaces_slice(self):
        """ingest_document() calls replace_document_slice for atomicity."""
        # Setup: mock persistence
        # Assert: replace_document_slice called with correct document URI

    async def test_graphindexignore_excludes_files(self):
        """Files matching .graphindexignore patterns are excluded from indexing."""
        # Setup: .graphindexignore with "*.log" pattern
        # Assert: .log files not passed to extractors

    async def test_regenerate_report_explicit(self):
        """regenerate_report() generates report without re-running pipeline."""
        # Setup: mock analytics
        # Assert: compute_analytics and generate_report called, no extractors

    async def test_ingest_does_not_regenerate_report(self):
        """ingest_document() must NOT trigger report regeneration."""
        # Setup: mock everything
        # Assert: generate_report NOT called during ingest_document
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/graphindex.spec.md` for full context
2. **Check dependencies** — ALL prior GraphIndex tasks (TASK-1254 through TASK-1261) must be done
3. **Verify the Codebase Contract** — confirm all stage module interfaces match expectations
4. **Update status** in `sdd/tasks/index/graphindex.json` -> `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1262-graphindex-builder.md`
8. **Update index** -> `"done"`

---

## Completion Note

*(Agent fills this in when done)*
