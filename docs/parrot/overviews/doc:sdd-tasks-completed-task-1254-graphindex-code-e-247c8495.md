---
type: Wiki Overview
title: 'TASK-1254: Code Extractor — tree-sitter Python Parsing'
id: doc:sdd-tasks-completed-task-1254-graphindex-code-extractor-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements the **code extraction** pipeline for GraphIndex. It
  uses tree-sitter to parse Python source files and emit `UniversalNode` / `UniversalEdge`
  instances representing the structural and semantic content of a codebase. It also
  extracts rationale from docstrings a
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.knowledge.graphindex
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.extractors
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.extractors.code
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
---

# TASK-1254: Code Extractor — tree-sitter Python Parsing

**Feature**: FEAT-187 — GraphIndex — Structured Knowledge Graph Indexing
**Spec**: `sdd/specs/graphindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1253
**Assigned-to**: unassigned

---

## Context

This task implements the **code extraction** pipeline for GraphIndex. It uses tree-sitter to parse Python source files and emit `UniversalNode` / `UniversalEdge` instances representing the structural and semantic content of a codebase. It also extracts rationale from docstrings and tagged comments.

This is one of three parallel extractors (code, loader, skill) that feed into the embedding and assembly stages. It can be developed independently of the other extractors since they share no files.

Implements: Spec §3 Module 2 (Code Extractor).

---

## Scope

- Implement tree-sitter-based Python source file parsing
- Extract `Module`, `Class`, `Function` nodes as `UniversalNode` instances with `kind=NodeKind.SYMBOL`
- Extract `Rationale` nodes from docstrings and tagged comments matching configurable tag set: `NOTE`, `WHY`, `HACK`, `TODO`, `FIXME`, `XXX`
- Emit edges: `contains`, `defines`, `imports`, `calls`, `explains`
- Handle parse errors gracefully: emit nodes with `domain_tags={"parse_error": true}` and `provenance="ambiguous"`
- Support configurable tag set (allow users to extend or restrict the default set)
- Implement `.graphindexignore` support via `pathspec` for file filtering (gitignore-style patterns)
- Create the `parrot.knowledge.graphindex.extractors` sub-package

**NOT in scope**: TypeScript/Svelte parsing (v1.1), loader-based extraction, embedding, graph assembly, SKILL.md extraction

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/__init__.py` | CREATE | Extractors sub-package init with public exports |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py` | CREATE | tree-sitter Python parser, node/edge extraction, .graphindexignore support |
| `packages/ai-parrot/tests/knowledge/graphindex/test_code_extractor.py` | CREATE | Unit tests for code extractor |

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
from pydantic import BaseModel, Field
```

### New Dependencies Required
```
tree-sitter           # Python bindings for tree-sitter parser
tree-sitter-languages # Pre-built language grammars including Python
pathspec              # gitignore-style pattern matching for .graphindexignore
```

### Does NOT Exist
- ~~`parrot.knowledge.graphindex.extractors`~~ — does not exist yet; this task creates the sub-package
- ~~`parrot.parsers.tree_sitter`~~ — no existing tree-sitter integration; implement from scratch
- ~~`parrot.knowledge.graphindex.ignore`~~ — .graphindexignore handling is new code in this task

---

## Implementation Notes

### Pattern to Follow
```python
import pathspec
from tree_sitter_languages import get_parser

class CodeExtractor:
    """Extract code structure from Python source files using tree-sitter.

    Args:
        tag_set: Set of comment tags to extract as Rationale nodes.
            Defaults to {"NOTE", "WHY", "HACK", "TODO", "FIXME", "XXX"}.
        ignore_file: Path to .graphindexignore file. Defaults to None.
    """

    DEFAULT_TAGS: set[str] = {"NOTE", "WHY", "HACK", "TODO", "FIXME", "XXX"}

    def __init__(
        self,
        tag_set: set[str] | None = None,
        ignore_file: str | None = None,
    ) -> None:
        self.tag_set = tag_set or self.DEFAULT_TAGS
        self.parser = get_parser("python")
        self._ignore_spec: pathspec.PathSpec | None = None
        if ignore_file:
            self._load_ignore(ignore_file)

    async def extract(self, file_path: str, source: str) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Parse a Python source file and return nodes and edges."""
        ...

    def _parse_tree(self, source: bytes) -> ...:
        """Parse source bytes into a tree-sitter tree. Handle errors gracefully."""
        ...

    def _extract_rationale(self, node, source_uri: str) -> list[UniversalNode]:
        """Extract Rationale nodes from docstrings and tagged comments."""
        ...

    def is_ignored(self, file_path: str) -> bool:
        """Check if a file path matches .graphindexignore patterns."""
        ...
```

### Key Constraints
- Async-first, type-hinted, Google-style docstrings
- Parse errors must NOT crash the pipeline — emit degraded nodes instead
- tree-sitter `get_parser("python")` is synchronous but fast; wrap in async interface
- `.graphindexignore` uses the same syntax as `.gitignore` (via `pathspec`)
- Every extracted node must have a valid `source_uri` pointing to the original file
- Module nodes are top-level; Class/Function are children via `contains` edges
- `imports` edges connect Module nodes; `calls` edges connect Function nodes
- `explains` edges link Rationale nodes to the symbol they document

---

## Acceptance Criteria

- [ ] tree-sitter parses Python source files and extracts Module, Class, Function nodes
- [ ] Rationale nodes extracted from docstrings and tagged comments (NOTE, WHY, HACK, TODO, FIXME, XXX)
- [ ] Edges emitted: contains, defines, imports, calls, explains
- [ ] Parse errors handled gracefully with `domain_tags={"parse_error": true}` and `provenance="ambiguous"`
- [ ] Tag set is configurable (can add/remove tags)
- [ ] `.graphindexignore` filtering works with gitignore-style patterns via pathspec
- [ ] Extractors sub-package created with proper `__init__.py`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_code_extractor.py -v`
- [ ] Import works: `from parrot.knowledge.graphindex.extractors.code import CodeExtractor`

---

## Test Specification

```python
import pytest
from parrot.knowledge.graphindex.extractors.code import CodeExtractor
from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, NodeKind, EdgeKind, Provenance,
)

SAMPLE_PYTHON = '''
"""Module docstring."""
import os

class MyClass:
    """Class docstring."""

    def my_method(self, x: int) -> str:
        # NOTE: This is a design rationale
        return str(x)

def standalone_func():
    """Standalone function."""
    # TODO: Implement this
    pass
'''

class TestCodeExtractor:
    @pytest.fixture
    def extractor(self):
        return CodeExtractor()

    @pytest.mark.asyncio
    async def test_extracts_module_node(self, extractor):
        nodes, edges = await extractor.extract("test.py", SAMPLE_PYTHON)
        module_nodes = [n for n in nodes if n.kind == NodeKind.SYMBOL and n.domain_tags.get("symbol_type") == "module"]
        assert len(module_nodes) == 1

    @pytest.mark.asyncio
    async def test_extracts_class_and_function(self, extractor):
        nodes, edges = await extractor.extract("test.py", SAMPLE_PYTHON)
        symbol_nodes = [n for n in nodes if n.kind == NodeKind.SYMBOL]
        titles = {n.title for n in symbol_nodes}
        assert "MyClass" in titles
        assert "my_method" in titles
        assert "standalone_func" in titles

    @pytest.mark.asyncio
    async def test_extracts_rationale_from_tagged_comments(self, extractor):
        nodes, edges = await extractor.extract("test.py", SAMPLE_PYTHON)
        rationale_nodes = [n for n in nodes if n.kind == NodeKind.RATIONALE]
        assert len(rationale_nodes) >= 2  # NOTE + TODO

    @pytest.mark.asyncio
    async def test_emits_contains_edges(self, extractor):
        nodes, edges = await extractor.extract("test.py", SAMPLE_PYTHON)
        contains_edges = [e for e in edges if e.kind == EdgeKind.CONTAINS]
        assert len(contains_edges) > 0

    @pytest.mark.asyncio
    async def test_emits_explains_edges(self, extractor):
        nodes, edges = await extractor.extract("test.py", SAMPLE_PYTHON)
        explains_edges = [e for e in edges if e.kind == EdgeKind.EXPLAINS]
        assert len(explains_edges) > 0

    @pytest.mark.asyncio
    async def test_parse_error_graceful(self, extractor):
        nodes, edges = await extractor.extract("bad.py", "def broken(")
        error_nodes = [n for n in nodes if n.domain_tags.get("parse_error")]
        assert len(error_nodes) > 0
        assert error_nodes[0].provenance == Provenance.AMBIGUOUS

    def test_custom_tag_set(self):
        extractor = CodeExtractor(tag_set={"CUSTOM", "SPECIAL"})
        assert extractor.tag_set == {"CUSTOM", "SPECIAL"}

    def test_graphindexignore(self, tmp_path):
        ignore_file = tmp_path / ".graphindexignore"
        ignore_file.write_text("*.pyc\n__pycache__/\n")
        extractor = CodeExtractor(ignore_file=str(ignore_file))
        assert extractor.is_ignored("module.pyc") is True
        assert extractor.is_ignored("module.py") is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/graphindex.spec.md` for full context
2. **Check dependencies** — TASK-1253 must be completed (provides `UniversalNode`, `UniversalEdge`, etc.)
3. **Verify the Codebase Contract** — confirm schema imports work from TASK-1253
4. **Update status** in `sdd/tasks/index/graphindex.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1254-graphindex-code-extractor.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
