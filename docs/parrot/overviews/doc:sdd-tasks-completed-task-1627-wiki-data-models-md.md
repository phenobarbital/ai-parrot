---
type: Wiki Overview
title: 'TASK-1627: Wiki Data Models'
id: doc:sdd-tasks-completed-task-1627-wiki-data-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation task — defines all Pydantic data models used across the wiki feature.
relates_to:
- concept: mod:parrot.knowledge.wiki
  rel: mentions
- concept: mod:parrot.knowledge.wiki.models
  rel: mentions
---

# TASK-1627: Wiki Data Models

**Feature**: FEAT-260 — LLM Wiki: Persistent Knowledge Base with PageIndex + GraphIndex
**Spec**: `sdd/specs/llmwiki-pageindex-graphindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation task — defines all Pydantic data models used across the wiki feature.
Implements Spec §2 Data Models. Every subsequent task imports from this module.

---

## Scope

- Implement `WikiPageCategory` enum (summary, entity, concept, comparison,
  overview, synthesis, answer)
- Implement `WikiConfig` model (wiki_name, storage_dir, source_dir,
  page_categories, search_weights, lightweight_model, model)
- Implement `SourceManifestEntry` model (source_id, source_uri, file_hash,
  mtime, ingested_at, pages_generated, status)
- Implement `WikiSearchResult` model (node_id, title, score, source,
  snippet, category)
- Implement `WikiLintReport` model (okf_report, orphan_sources,
  stale_sources, uncovered_sources, cross_ref_issues, total_issues)
- Write unit tests for all models

**NOT in scope**: OKF enum extensions (TASK-1628), toolkit (TASK-1633)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py` | CREATE | Empty init, will be populated in TASK-1635 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/models.py` | CREATE | All Pydantic models |
| `tests/knowledge/wiki/__init__.py` | CREATE | Test package init |
| `tests/knowledge/wiki/test_models.py` | CREATE | Unit tests for models |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pydantic import BaseModel, Field  # standard pydantic
from typing import Optional
from pathlib import Path
from enum import Enum
```

### Existing Signatures to Use

```python
# No existing signatures needed — this task creates new models only.
# Models follow the same Pydantic pattern used throughout ai-parrot.
```

### Does NOT Exist

- ~~`parrot.knowledge.wiki`~~ — does not exist yet; this task creates it
- ~~`parrot.knowledge.wiki.models`~~ — does not exist yet
- ~~`WikiConfig`~~ — does not exist yet
- ~~`WikiPageCategory`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow

```python
# Follow the same Pydantic model pattern as graphindex/schema.py
from pydantic import BaseModel, Field
from enum import Enum

class WikiPageCategory(str, Enum):
    SUMMARY = "summary"
    ENTITY = "entity"
    # ...
```

### Key Constraints

- All models must use strict type hints
- Use `Field(default_factory=...)` for mutable defaults
- WikiConfig.search_weights must validate that values sum to ~1.0
- All fields must have descriptions via Field or docstrings

---

## Acceptance Criteria

- [ ] All 5 models implemented with complete type hints
- [ ] WikiConfig validates search_weights
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_models.py -v`
- [ ] Import works: `from parrot.knowledge.wiki.models import WikiConfig`

---

## Test Specification

```python
import pytest
from parrot.knowledge.wiki.models import (
    WikiPageCategory, WikiConfig, SourceManifestEntry,
    WikiSearchResult, WikiLintReport,
)

class TestWikiPageCategory:
    def test_all_categories_exist(self):
        assert len(WikiPageCategory) == 7

class TestWikiConfig:
    def test_defaults(self, tmp_path):
        config = WikiConfig(wiki_name="test", storage_dir=tmp_path)
        assert config.search_weights == {"pageindex": 0.6, "graphindex": 0.4}
        assert len(config.page_categories) == 7

class TestSourceManifestEntry:
    def test_serialization(self):
        entry = SourceManifestEntry(
            source_id="src-001", source_uri="/path/to/doc.md",
            file_hash="abc123", mtime=1234567890.0,
            ingested_at="2026-01-01T00:00:00Z", pages_generated=["p1"]
        )
        data = entry.model_dump()
        assert data["source_id"] == "src-001"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/llmwiki-pageindex-graphindex.spec.md` §2 Data Models
2. **Check dependencies** — none; this is the first task
3. **Create** `packages/ai-parrot/src/parrot/knowledge/wiki/` directory
4. **Implement** all models in `models.py`
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-1627-wiki-data-models.md`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
