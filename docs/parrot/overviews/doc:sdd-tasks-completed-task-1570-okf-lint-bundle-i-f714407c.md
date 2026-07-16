---
type: Wiki Overview
title: 'TASK-1570: OKF Lint & Bundle Integration Tests'
id: doc:sdd-tasks-completed-task-1570-okf-lint-bundle-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Final integration pass for FEAT-216. Verifies end-to-end workflows:'
relates_to:
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.store
  rel: mentions
---

# TASK-1570: OKF Lint & Bundle Integration Tests

**Feature**: FEAT-216 — OKF Knowledge Lint & Bundle Interchange
**Spec**: `sdd/specs/FEAT-216-okf-knowledge-lint-and-bundle.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1566, TASK-1567, TASK-1568, TASK-1569
**Assigned-to**: unassigned

---

## Context

Final integration pass for FEAT-216. Verifies end-to-end workflows:
round-trip fidelity (export → import → verify), lint-after-import (import a
well-formed bundle then lint it), and regression tests ensuring existing OKF
tests still pass. Also updates `okf/__init__.py` exports to include all new
public symbols.

Implements: Spec §3 Module 6 + acceptance criteria verification.

---

## Scope

- Verify `okf/__init__.py` exports all new symbols: `LintFinding`, `LintReport`,
  `lint_knowledge_base`, `ExportReport`, `ImportReport`, `export_okf_bundle`,
  `import_okf_bundle`
- Write integration test: `test_round_trip_full` — build a real PageIndex tree with
  OKF enrichment, export it, import it, compare concept_ids, types, edges, bodies
- Write integration test: `test_lint_after_import` — import a well-formed OKF bundle,
  run lint, expect zero findings
- Write integration test: `test_lint_after_import_with_issues` — import a bundle with
  a broken link, run lint, expect at least 1 broken_link finding
- Run full OKF test suite to confirm no regressions

**NOT in scope**: implementing lint or bundle logic (already done).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/__init__.py` | MODIFY | Verify/add exports for lint + bundle symbols |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_integration.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All of these should be importable after TASK-1565-1569 are complete
from parrot.knowledge.pageindex.okf import (
    ConceptType,
    KnowledgeGraph,
    build_graph,
    ConceptFrontmatter,
    project_frontmatter,
    parse_frontmatter,
    project_sidecars,
    generate_index_md,
    okf_migrate,
    OKFToolkit,
    # New symbols from FEAT-216:
    LintFinding,
    LintReport,
    lint_knowledge_base,
    ExportReport,
    ImportReport,
    export_okf_bundle,
    import_okf_bundle,
)
from parrot.knowledge.pageindex.store import JSONTreeStore
from parrot.knowledge.pageindex.content_store import NodeContentStore
```

### Does NOT Exist
- ~~`test_okf_integration.py`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Key Constraints
- Integration tests must use `tmp_path` for all filesystem operations
- Use real `JSONTreeStore` and `NodeContentStore` (with `tmp_path` base) — no mocks for integration tests
- Round-trip test should check: concept_id preservation, type preservation, body content preservation, edge count (not exact edge content, since `node_id` and `resource` are regenerated)

### References in Codebase
- `packages/ai-parrot/tests/knowledge/pageindex/test_okf_*.py` — existing test patterns
- `packages/ai-parrot/tests/knowledge/pageindex/test_okf_projection.py` — pattern for tree fixture construction

---

## Acceptance Criteria

- [ ] All FEAT-216 symbols importable from `parrot.knowledge.pageindex.okf`
- [ ] Round-trip test: export → import preserves concept_ids
- [ ] Round-trip test: export → import preserves concept types
- [ ] Round-trip test: export → import preserves body content
- [ ] Lint-after-import: well-formed bundle → zero findings
- [ ] Lint-after-import: bundle with broken link → ≥ 1 broken_link finding
- [ ] All existing OKF tests still pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_*.py -v`
- [ ] Integration tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_integration.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_okf_integration.py
import pytest
from pathlib import Path
from parrot.knowledge.pageindex.okf import (
    lint_knowledge_base, export_okf_bundle, import_okf_bundle,
    KnowledgeGraph, build_graph,
)
from parrot.knowledge.pageindex.store import JSONTreeStore
from parrot.knowledge.pageindex.content_store import NodeContentStore


@pytest.fixture
def real_stores(tmp_path):
    store = JSONTreeStore(base_dir=tmp_path / "trees")
    content = NodeContentStore(base_dir=tmp_path / "content")
    return store, content


def test_round_trip_full(enriched_tree, real_stores, tmp_path):
    store, content_store = real_stores
    export_dir = tmp_path / "exported"
    export_okf_bundle(enriched_tree, "test", content_store, export_dir)
    report = import_okf_bundle(export_dir, "reimported", store, content_store)
    assert report.nodes_created >= 2
    # Verify concept_ids preserved
    ...


def test_lint_after_import_clean(sample_okf_bundle, real_stores):
    store, content_store = real_stores
    import_okf_bundle(sample_okf_bundle, "test", store, content_store)
    tree = store.load("test")
    graph = build_graph(tree, content_store.load)
    report = lint_knowledge_base(graph, tree, content_store)
    assert report.total_findings == 0


def test_lint_after_import_with_broken_link(tmp_path, real_stores):
    store, content_store = real_stores
    # Write a bundle with a broken link
    (tmp_path / "test.md").write_text(
        "---\ntype: Section\ntitle: Test\nid: test-id\n---\n"
        "See [missing](ghost.md).\n"
    )
    import_okf_bundle(tmp_path, "broken", store, content_store)
    tree = store.load("broken")
    graph = build_graph(tree, content_store.load)
    report = lint_knowledge_base(graph, tree, content_store)
    assert len(report.broken_links) >= 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-216-okf-knowledge-lint-and-bundle.spec.md`
2. **Check dependencies** — ALL prior FEAT-216 tasks must be completed
3. **Verify exports** — confirm `okf/__init__.py` exports all new symbols
4. **Implement** integration tests with real stores (no mocks)
5. **Run full OKF test suite**: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_*.py -v`

---

## Completion Note

Implemented by sdd-worker on 2026-06-16.

- Verified `okf/__init__.py` already exports all FEAT-216 symbols: `LintFinding`, `LintReport`, `lint_knowledge_base`, `ExportReport`, `ImportReport`, `export_okf_bundle`, `import_okf_bundle`.
- Updated existing `test_okf_integration.py` (rather than creating a new file — file already existed from FEAT-238 with other integration tests).
- Fixed `TestToolkitOKFToolRegistration.test_set_okf_toolkit_and_get_tools` assertion from 6 → 9 tools.
- Added `TestFeat216Exports` (7 tests), `TestRoundTripFull` (4 tests), `TestLintAfterImport` (5 tests).
- Fixtures: `two_node_tree_feat216`, `clean_bundle_feat216` (mutual refs, future timestamps), `broken_link_bundle_feat216` (ghost frontmatter edge).
- Full OKF test suite: 233 passed, 0 failures.
