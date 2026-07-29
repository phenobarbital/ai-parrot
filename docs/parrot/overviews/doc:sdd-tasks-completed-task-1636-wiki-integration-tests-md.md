---
type: Wiki Overview
title: 'TASK-1636: Wiki Integration Tests'
id: doc:sdd-tasks-completed-task-1636-wiki-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: End-to-end integration tests that verify the full wiki pipeline works as
  a
relates_to:
- concept: mod:parrot.knowledge.wiki
  rel: mentions
- concept: mod:parrot.knowledge.wiki.models
  rel: mentions
---

# TASK-1636: Wiki Integration Tests

**Feature**: FEAT-260 — LLM Wiki: Persistent Knowledge Base with PageIndex + GraphIndex
**Spec**: `sdd/specs/llmwiki-pageindex-graphindex.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1627, TASK-1628, TASK-1629, TASK-1630, TASK-1631, TASK-1632, TASK-1633, TASK-1634, TASK-1635
**Assigned-to**: unassigned

---

## Context

End-to-end integration tests that verify the full wiki pipeline works as a
whole. Tests the golden paths: ingest → query, reingest, combined search
ranking, and lint detection. Implements Spec §3 Module 10 and §4.

---

## Scope

- Write integration tests for:
  - `test_end_to_end_ingest_query` — ingest a markdown source → query →
    verify answer references source content
  - `test_ingest_reingest_cycle` — ingest → modify source → reingest →
    verify pages updated
  - `test_combined_search_ranking` — ingest multiple sources → combined
    search → verify ranking uses both indexes
  - `test_lint_detects_issues` — create wiki with orphan pages → lint →
    verify issues reported
- Fixtures: mock LLM adapters (no real API calls), temp directories for
  wiki storage, sample markdown source files

**NOT in scope**: Performance benchmarks, multi-tenant tests, real LLM calls

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/knowledge/wiki/test_integration.py` | CREATE | Integration tests |
| `tests/knowledge/wiki/conftest.py` | CREATE | Shared fixtures |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki import (
    LLMWikiToolkit, WikiConfig, WikiPageCategory,
    SourceCollectionManager, WikiBookkeeper,
    WikiCombinedSearch, WikiIngestOrchestrator,
)
from parrot.knowledge.wiki.models import WikiLintReport
```

### Does NOT Exist

- ~~`parrot.knowledge.wiki.testing`~~ — no test helpers module; use pytest fixtures
- ~~`LLMWikiToolkit.from_config`~~ — no factory method; construct with explicit deps

---

## Implementation Notes

### Key Constraints

- All tests must work WITHOUT real LLM API calls (mock adapters)
- Use `tmp_path` fixture for all file operations
- Use `pytest-asyncio` for async tests
- Tests should be independent — no shared state between tests
- Integration tests live in the same `tests/knowledge/wiki/` directory

### References in Codebase

- Spec §4 Test Specification — defines the 4 integration test scenarios
- Spec §4 Test Data / Fixtures — defines `wiki_config` and `sample_source` fixtures

---

## Acceptance Criteria

- [ ] 4 integration tests implemented per Spec §4
- [ ] All tests pass without real LLM calls
- [ ] Tests use `tmp_path` for isolation
- [ ] `conftest.py` provides reusable fixtures
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_integration.py -v`
- [ ] Full test suite passes: `pytest tests/knowledge/wiki/ -v`

---

## Test Specification

```python
import pytest
from parrot.knowledge.wiki import LLMWikiToolkit, WikiConfig

@pytest.fixture
def wiki_config(tmp_path):
    return WikiConfig(wiki_name="test-wiki", storage_dir=tmp_path / "wiki-storage")

@pytest.fixture
def sample_sources(tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "article1.md").write_text("# Neural Networks\n\nA neural network is a computational model...")
    (sources / "article2.md").write_text("# Deep Learning\n\nDeep learning extends neural networks...")
    return sources

class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_ingest_then_query(self, wiki_config, sample_sources):
        # Setup toolkit with mocked LLM adapters
        # Ingest article1.md
        # Query "what is a neural network"
        # Verify answer references source content
        pass

    @pytest.mark.asyncio
    async def test_reingest_updated_source(self, wiki_config, sample_sources):
        # Ingest article1.md
        # Modify article1.md
        # Reingest
        # Verify pages updated
        pass

    @pytest.mark.asyncio
    async def test_combined_search_uses_both_indexes(self, wiki_config, sample_sources):
        # Ingest both articles
        # Search "neural networks deep learning"
        # Verify results from both PageIndex and GraphIndex
        pass

    @pytest.mark.asyncio
    async def test_lint_reports_issues(self, wiki_config):
        # Create wiki
        # Manually create orphan state
        # Run lint
        # Verify issues detected
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/llmwiki-pageindex-graphindex.spec.md` §4
2. **Check dependencies** — ALL previous tasks must be completed
3. **Create** `conftest.py` with shared fixtures first
4. **Implement** all 4 integration tests
5. **Run** the full test suite: `pytest tests/knowledge/wiki/ -v`
6. **Verify** all acceptance criteria

---

## Completion Note

Completed by sdd-worker on 2026-06-26.

Created two files:
- `tests/knowledge/wiki/conftest.py` — shared fixtures: `wiki_config`, `sample_source`,
  `sample_sources`, `mock_pi`, `mock_gi`, `mock_okf`, `wiki_toolkit`; all use
  `tmp_path` for isolation; no real LLM calls.
- `tests/knowledge/wiki/test_integration.py` — `TestEndToEnd` class with 4 async tests:
  `test_end_to_end_ingest_query`, `test_ingest_reingest_cycle`,
  `test_combined_search_ranking`, `test_lint_reports_issues`.

All 4 integration tests pass.  Full suite: 158/158 tests pass.
`pytest tests/knowledge/wiki/ -v` confirms all acceptance criteria met.
