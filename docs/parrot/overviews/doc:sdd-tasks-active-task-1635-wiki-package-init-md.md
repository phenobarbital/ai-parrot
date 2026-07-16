---
type: Wiki Overview
title: 'TASK-1635: Wiki Package Init + Exports'
id: doc:sdd-tasks-active-task-1635-wiki-package-init-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Finalizes the wiki package's `__init__.py` with all public exports and
relates_to:
- concept: mod:parrot.knowledge.wiki
  rel: mentions
---

# TASK-1635: Wiki Package Init + Exports

**Feature**: FEAT-260 — LLM Wiki: Persistent Knowledge Base with PageIndex + GraphIndex
**Spec**: `sdd/specs/llmwiki-pageindex-graphindex.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1627, TASK-1633
**Assigned-to**: unassigned

---

## Context

Finalizes the wiki package's `__init__.py` with all public exports and
ensures the package is importable as `from parrot.knowledge.wiki import ...`.
Implements Spec §3 Module 9.

---

## Scope

- Populate `packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py` with
  all public symbols:
  - From models: WikiConfig, WikiPageCategory, SourceManifestEntry,
    WikiSearchResult, WikiLintReport
  - From toolkit: LLMWikiToolkit
  - From sources: SourceCollectionManager
  - From bookkeeper: WikiBookkeeper
  - From search: WikiCombinedSearch
  - From ingest: WikiIngestOrchestrator, IngestReport
- Add `__all__` list
- Write import smoke test

**NOT in scope**: Any implementation changes to the modules themselves

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py` | MODIFY | Add all exports |
| `tests/knowledge/wiki/test_package_init.py` | CREATE | Import smoke test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Follow the same pattern as pageindex/__init__.py (exports 20+ symbols)
# and graphindex/__init__.py (exports enums, models, components)
```

### Does NOT Exist

- ~~`parrot.knowledge.wiki.__all__`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py
from .models import (
    WikiConfig,
    WikiPageCategory,
    SourceManifestEntry,
    WikiSearchResult,
    WikiLintReport,
)
from .toolkit import LLMWikiToolkit
from .sources import SourceCollectionManager
from .bookkeeper import WikiBookkeeper
from .search import WikiCombinedSearch
from .ingest import WikiIngestOrchestrator, IngestReport

__all__ = [
    "WikiConfig", "WikiPageCategory", "SourceManifestEntry",
    "WikiSearchResult", "WikiLintReport", "LLMWikiToolkit",
    "SourceCollectionManager", "WikiBookkeeper", "WikiCombinedSearch",
    "WikiIngestOrchestrator", "IngestReport",
]
```

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.wiki import LLMWikiToolkit` works
- [ ] `from parrot.knowledge.wiki import WikiConfig` works
- [ ] All symbols in `__all__` are importable
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_package_init.py -v`

---

## Test Specification

```python
import pytest

class TestWikiPackageInit:
    def test_import_toolkit(self):
        from parrot.knowledge.wiki import LLMWikiToolkit
        assert LLMWikiToolkit is not None

    def test_import_config(self):
        from parrot.knowledge.wiki import WikiConfig
        assert WikiConfig is not None

    def test_all_exports(self):
        import parrot.knowledge.wiki as wiki
        for name in wiki.__all__:
            assert hasattr(wiki, name), f"Missing export: {name}"
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — TASK-1627 and TASK-1633 must be completed
2. **Update** the `__init__.py` with all exports
3. **Verify** all imports work in a clean Python session

---

## Completion Note

*(Agent fills this in when done)*
