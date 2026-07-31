---
type: Wiki Overview
title: 'TASK-1569: OKFToolkit Lint & Bundle Tools'
id: doc:sdd-tasks-completed-task-1569-okftoolkit-lint-bundle-tools-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extends the existing `OKFToolkit` with 3 new agent-facing tools that expose
  the
relates_to:
- concept: mod:parrot.knowledge.pageindex.okf.bundle
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.lint
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.store
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
---

# TASK-1569: OKFToolkit Lint & Bundle Tools

**Feature**: FEAT-216 — OKF Knowledge Lint & Bundle Interchange
**Spec**: `sdd/specs/FEAT-216-okf-knowledge-lint-and-bundle.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1566, TASK-1567, TASK-1568
**Assigned-to**: unassigned

---

## Context

Extends the existing `OKFToolkit` with 3 new agent-facing tools that expose the
lint engine and bundle import/export to agents. The toolkit currently has 6 read
tools (find_by_type, list_concepts, get_concept, get_related, trace_mapping, cite).
This task adds lint_knowledge_base, export_okf_bundle, and import_okf_bundle.

Implements: Spec §3 Module 5.

---

## Scope

- Extend `OKFToolkit` in `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/tools.py` with:
  - `lint_knowledge_base(stale_days: int = 90) -> dict` — wraps `lint.lint_knowledge_base()`
  - `export_okf_bundle(output_dir: str) -> dict` — wraps `bundle.export_okf_bundle()`
  - `import_okf_bundle(input_dir: str) -> dict` — wraps `bundle.import_okf_bundle()`
- Each tool is a `@tool`-decorated method that delegates to the corresponding function
- The toolkit holds `store: JSONTreeStore` as an additional constructor parameter (needed for import)
- Add tools to `get_tools()` return list
- Add tests for each toolkit tool

**NOT in scope**: implementing lint or bundle logic (those are TASK-1566, 1567, 1568).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/tools.py` | MODIFY | Add 3 new @tool methods + optional store param |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_tools.py` | MODIFY | Add tests for new tools |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.okf.lint import lint_knowledge_base, LintReport  # lint.py (TASK-1566)
from parrot.knowledge.pageindex.okf.bundle import (
    export_okf_bundle, ExportReport,
    import_okf_bundle, ImportReport,
)  # bundle.py (TASK-1567/1568)
from parrot.knowledge.pageindex.store import JSONTreeStore  # store.py
from parrot.tools import tool  # verified: parrot/tools/__init__.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/tools.py
class OKFToolkit:  # line 36
    def __init__(
        self,
        tree: dict[str, Any],
        graph: KnowledgeGraph,
        content_store: NodeContentStore,
        tree_name: str,
    ) -> None:  # line 56-67
    # self._tree, self._graph, self._content_store, self._tree_name
    # self._by_concept_id: dict[str, dict]  — flat concept_id → node lookup

    def get_tools(self) -> list:  # line 75
        # Returns list of @tool-decorated bound methods

    @tool
    def find_by_type(self, concept_type: str, query: str = "") -> list[dict]:
        """Find concepts by type, optionally filtered by query."""
        ...

    @tool
    def list_concepts(self, concept_type: str = "") -> list[dict]:
        """List all concepts, optionally filtered by type."""
        ...
```

### Does NOT Exist
- ~~`OKFToolkit.lint_knowledge_base()`~~ — does not exist yet; this task adds it
- ~~`OKFToolkit.export_okf_bundle()`~~ — does not exist yet
- ~~`OKFToolkit.import_okf_bundle()`~~ — does not exist yet
- ~~`OKFToolkit._store`~~ — does not exist yet; constructor needs `store: Optional[JSONTreeStore] = None` param

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the existing @tool pattern in tools.py
@tool
def lint_knowledge_base(self, stale_days: int = 90) -> dict:
    """Run lint checks on the knowledge base: orphans, broken links, missing concepts, stale claims."""
    from parrot.knowledge.pageindex.okf.lint import lint_knowledge_base as _lint
    report = _lint(self._graph, self._tree, self._content_store, stale_days=stale_days)
    return report.model_dump()
```

### Key Constraints
- Use lazy imports for `lint` and `bundle` modules inside each tool method to avoid circular imports
- `import_okf_bundle` needs `JSONTreeStore` — add `store: Optional[JSONTreeStore] = None` to `__init__`; raise `ValueError` if `store` is None when import tool is called
- `export_okf_bundle` needs `output_dir` as string → convert to `Path` inside the tool
- Return Pydantic model `.model_dump()` for agent-friendly dict output
- Add new tools to `get_tools()` return list

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/tools.py` — the toolkit to extend
- Existing tool pattern: `find_by_type`, `list_concepts`, etc.

---

## Acceptance Criteria

- [ ] `OKFToolkit.lint_knowledge_base()` tool works and returns dict
- [ ] `OKFToolkit.export_okf_bundle()` tool works and returns dict
- [ ] `OKFToolkit.import_okf_bundle()` tool works and returns dict
- [ ] All 3 new tools appear in `get_tools()` return list
- [ ] `import_okf_bundle` raises `ValueError` when `store` is None
- [ ] Existing OKFToolkit tests still pass
- [ ] New tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_tools.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_okf_tools.py (extend)

def test_toolkit_lint(okf_toolkit):
    result = okf_toolkit.lint_knowledge_base()
    assert "total_findings" in result
    assert "orphans" in result


def test_toolkit_export(okf_toolkit, tmp_path):
    result = okf_toolkit.export_okf_bundle(output_dir=str(tmp_path))
    assert "files_written" in result


def test_toolkit_import(okf_toolkit_with_store, sample_okf_bundle):
    result = okf_toolkit_with_store.import_okf_bundle(input_dir=str(sample_okf_bundle))
    assert "nodes_created" in result


def test_toolkit_import_no_store_raises(okf_toolkit, sample_okf_bundle):
    with pytest.raises(ValueError, match="store"):
        okf_toolkit.import_okf_bundle(input_dir=str(sample_okf_bundle))


def test_toolkit_get_tools_includes_new(okf_toolkit):
    tools = okf_toolkit.get_tools()
    tool_names = [t.__name__ for t in tools]
    assert "lint_knowledge_base" in tool_names
    assert "export_okf_bundle" in tool_names
    assert "import_okf_bundle" in tool_names
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-216-okf-knowledge-lint-and-bundle.spec.md`
2. **Check dependencies** — TASK-1566, TASK-1567, TASK-1568 must all be completed
3. **Read `tools.py`** carefully to understand the existing `@tool` pattern and `get_tools()` mechanism
4. **Implement** the 3 new tools with lazy imports
5. **Run tests**: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_tools.py -v`

---

## Completion Note

Implemented by sdd-worker on 2026-06-16.

- Added `store: Optional[JSONTreeStore] = None` parameter to `OKFToolkit.__init__`; stored as `self._store`.
- Added 3 `@tool`-decorated methods: `lint_knowledge_base`, `export_okf_bundle`, `import_okf_bundle` with lazy imports.
- Updated `get_tools()` to return 9 tools (was 6).
- Updated `test_okf_tools.py`: fixed `test_get_tools_returns_six` → `test_get_tools_returns_nine`, added `toolkit_with_store` fixture, added `TestLintKnowledgeBase` (4 tests), `TestExportOKFBundle` (5 tests), `TestImportOKFBundle` (4 tests).
- Fixed `enriched_tree` fixture to include `"tree_name": "test_tree"` so lint engine resolves valid tree_name.
- All 38 tests pass.
