---
type: Wiki Overview
title: 'TASK-1085: Concept Embedding Pipeline'
id: doc:sdd-tasks-completed-task-1085-concept-embedding-pipeline-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.stores.postgres import PgVectorStore # verified: postgres.py:58'
relates_to:
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.knowledge.ontology.concept_embedding
  rel: mentions
- concept: mod:parrot.stores.postgres
  rel: mentions
---

# TASK-1085: Concept Embedding Pipeline

**Feature**: FEAT-159 — Concept-Document Authority Layer
**Spec**: `sdd/specs/concept-document-authority.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1087
**Assigned-to**: unassigned

---

## Context

> Module 2 of the spec. Creates the `ConceptEmbeddingPipeline` — a content-hash-based idempotent
> embedding sync that writes Concept embeddings into the shared `concepts` PgVector namespace with
> `tenant_id` metadata. The pipeline reads `MergedOntology.entities["Concept"].instances`, diffs
> against an on-disk hash cache, and only embeds changed/new concepts.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/ontology/concept_embedding.py` with:
  - `ConceptEmbeddingPipeline` class with `__init__(vector_store, embedder, ontology_dir, schema, table)`.
  - `async def sync(tenant_id, concepts) -> ConceptSyncResult` method.
  - Content hash: `sha256(label + sorted(synonyms) + description)` per Concept.
  - Hash cache at `{ontology_dir}/.concept_hashes/{tenant_id}.json` — atomic writes (tmpfile + rename).
  - Embeds changed/new Concepts via `PgVectorStore.add_documents()` with `metadata` including `tenant_id`.
  - Deletes removed Concepts scoped by `metadata_filters={"tenant_id": tenant_id, "concept_id": concept_id}`.
- Create `ConceptSyncResult` frozen dataclass.
- Write comprehensive unit tests.

**NOT in scope**: Integrating into `TenantOntologyManager.resolve()` (TASK-1086), the PgVectorStore metadata_filters extension for `add_documents` (TASK-1087), the hybrid resolver (TASK-1088).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/concept_embedding.py` | CREATE | ConceptEmbeddingPipeline + ConceptSyncResult |
| `packages/ai-parrot/tests/knowledge/test_concept_embedding.py` | CREATE | Unit tests for the pipeline |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.stores.postgres import PgVectorStore  # verified: postgres.py:58
from parrot.clients.abstract_client import AbstractClient  # base class for all LLM/embedding clients
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/stores/postgres.py:58
class PgVectorStore(AbstractStore):
    def __init__(self, table=None, schema='public', ...):  # line 63
    async def add_documents(self, documents, table=None, schema=None, ...):  # line 588
        # Does NOT currently accept metadata_filters — TASK-1087 adds this.
        # Until TASK-1087 lands, the pipeline can add documents with metadata={'tenant_id': ...}
        # but cannot scope upsert deletes. The delete path needs TASK-1087.

    async def similarity_search(self, query, table=None, schema=None,
                                 metadata_filters=None, ...):  # line 741
        # ALREADY has metadata_filters for search (scalar equality).
        # TASK-1087 extends it with list/IN support.
```

### Does NOT Exist
- ~~`PgVectorStore.add_documents()` accepting `metadata_filters`~~ — does NOT exist today; TASK-1087 adds it
- ~~A `concepts` PgVector namespace/table~~ — does NOT exist; created on first pipeline run
- ~~`ConceptEmbeddingPipeline`~~ — does NOT exist; this task creates it
- ~~`MergedOntology.entities["Concept"].instances`~~ — structure depends on how `MergedOntology` stores entity instances. Verify the actual attribute name via `grep` or `read`.

---

## Implementation Notes

### Pattern to Follow
```python
import hashlib
import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class ConceptSyncResult:
    added: int
    updated: int
    removed: int
    unchanged: int
    duration_ms: int

class ConceptEmbeddingPipeline:
    def __init__(self, vector_store, embedder, ontology_dir, schema="ontology", table="concepts"):
        self._vector_store = vector_store
        self._embedder = embedder
        self._ontology_dir = Path(ontology_dir)
        self._schema = schema
        self._table = table
        self.logger = logging.getLogger(__name__)

    def _content_hash(self, label, synonyms, description):
        content = label + "".join(sorted(synonyms or [])) + (description or "")
        return hashlib.sha256(content.encode()).hexdigest()

    def _load_hash_cache(self, tenant_id):
        cache_path = self._ontology_dir / ".concept_hashes" / f"{tenant_id}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text())
        return {}

    def _save_hash_cache(self, tenant_id, hashes):
        cache_dir = self._ontology_dir / ".concept_hashes"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{tenant_id}.json"
        # Atomic write
        fd, tmp = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
        try:
            with open(fd, "w") as f:
                json.dump(hashes, f)
            Path(tmp).replace(cache_path)
        except:
            Path(tmp).unlink(missing_ok=True)
            raise
```

### Key Constraints
- Must be async throughout — `sync()` is `async def`.
- Content hash is `sha256(label + sorted(synonyms) + description)`.
- Atomic file writes for hash cache (tmpfile + rename) to avoid corruption.
- Each embedded concept row must include `metadata={"tenant_id": tenant_id, "concept_id": concept_id}`.
- The `concepts` table is shared across tenants; isolation is by metadata.
- Cap multi-tenant operations: pipeline processes one tenant at a time.
- Logger: `self.logger = logging.getLogger(__name__)`.

### References in Codebase
- `packages/ai-parrot/src/parrot/stores/postgres.py` — PgVectorStore for embedding storage
- `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` — MergedOntology structure

---

## Acceptance Criteria

- [ ] `ConceptEmbeddingPipeline` class exists at the specified path
- [ ] `ConceptSyncResult` dataclass with `added`, `updated`, `removed`, `unchanged`, `duration_ms`
- [ ] First run with 5 Concepts → `added=5, updated=0, removed=0`; hash cache written
- [ ] Re-run with identical concepts → `added=0, updated=0, removed=0, unchanged=5`; no embedding calls
- [ ] Synonym change on one concept → `updated=1`; hash cache reflects new hash
- [ ] Removed concept → corresponding rows deleted; `removed=1`
- [ ] Two tenants with overlapping concept_ids → non-overlapping rows in shared namespace
- [ ] Hash cache uses atomic writes (tmpfile + rename)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/test_concept_embedding.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/test_concept_embedding.py
import pytest
from parrot.knowledge.ontology.concept_embedding import (
    ConceptEmbeddingPipeline,
    ConceptSyncResult,
)


class TestConceptEmbeddingPipeline:
    async def test_first_run_all_added(self, tmp_path):
        """5 Concepts, no hash cache → all 5 embedded, hash cache written."""

    async def test_no_change_no_embedding(self, tmp_path):
        """Re-run with identical concepts → unchanged=5; no embedding calls made."""

    async def test_synonym_changed_re_embedded(self, tmp_path):
        """Add a synonym to one concept → only that concept re-embedded (updated=1)."""

    async def test_concept_removed(self, tmp_path):
        """Remove a concept → corresponding rows deleted; removed=1."""

    async def test_tenant_isolation(self, tmp_path):
        """Two tenants with overlapping concept_ids produce non-overlapping rows."""

    def test_content_hash_deterministic(self):
        """Same inputs produce same hash regardless of synonym order."""

    def test_atomic_cache_write(self, tmp_path):
        """Hash cache file is written atomically (no partial writes)."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1087 is in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/concept-document-authority.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1085-concept-embedding-pipeline.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
