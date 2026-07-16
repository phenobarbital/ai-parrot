---
type: Wiki Overview
title: 'TASK-1572: CodeExtractor Enhancements — mtime, sha1, lineno'
id: doc:sdd-tasks-completed-task-1572-code-extractor-enhancements-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The base `CodeExtractor` needs three backward-compatible additions so that
relates_to:
- concept: mod:parrot.knowledge.graphindex.extractors.code
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
---

# TASK-1572: CodeExtractor Enhancements — mtime, sha1, lineno

**Feature**: FEAT-240 — GraphIndex Odoo-aware Extractor + SQLite Persistence + Graph Reader
**Spec**: `sdd/specs/odoo-graphindex-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The base `CodeExtractor` needs three backward-compatible additions so that
(a) the OdooCodeExtractor can stamp line spans on all symbols and (b) the
SQLite persistence can track file staleness. These changes are independent
of TASK-1571 (schema changes) and can run in parallel.

Implements Spec §3 Module 2.

---

## Scope

- Add `mtime: Optional[float] = None` kwarg to `CodeExtractor.extract()`
- Compute `sha1` of `source` bytes and stamp it in the module node's `domain_tags`
- Stamp `mtime` in module node's `domain_tags` when provided
- Stamp `lineno` and `end_lineno` (1-based) in `_extract_class` domain_tags
- Stamp `lineno` and `end_lineno` (1-based) in `_extract_function` domain_tags
- Write tests for all three additions
- Verify backward compatibility: `extract(path, source)` without mtime still works

**NOT in scope**: OdooCodeExtractor, SQLitePersistence, builder wiring

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py` | MODIFY | Add mtime, sha1, lineno stamping |
| `packages/ai-parrot/tests/knowledge/graphindex/test_code_extractor.py` | MODIFY | Add tests for new domain_tags |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex.extractors.code import CodeExtractor  # verified: code.py:61
from parrot.knowledge.graphindex.extractors.code import _make_node_id  # verified: code.py:34
from parrot.knowledge.graphindex.extractors.code import _get_node_text # verified: code.py:48
from parrot.knowledge.graphindex.schema import UniversalNode           # verified: schema.py:71
from parrot.knowledge.graphindex.schema import UniversalEdge           # verified: schema.py:102
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py

class CodeExtractor:  # line 61
    def __init__(
        self,
        tag_set: Optional[set[str]] = None,
        ignore_file: Optional[str] = None,
    ) -> None:  # line 80

    async def extract(
        self, file_path: str, source: str,
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:  # line 95
    # MODIFY: add *, mtime: Optional[float] = None

    def _extract_class(
        self, node, file_path: str, source_bytes: bytes,
        parent_id: str, nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> str:  # line 237
    # Currently stamps: domain_tags={"symbol_type": "class"}
    # ADD: "lineno": node.start_point[0] + 1, "end_lineno": node.end_point[0] + 1

    def _extract_function(
        self, node, file_path: str, source_bytes: bytes,
        parent_id: str, nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> str:  # line 295
    # Currently stamps: domain_tags={"symbol_type": "function", "qualified_name": ...}
    # ADD: "lineno": node.start_point[0] + 1, "end_lineno": node.end_point[0] + 1
```

### Does NOT Exist
- ~~`CodeExtractor.extract(..., mtime=...)`~~ — mtime param does not exist yet
- ~~`domain_tags["sha1"]`~~ — not computed in current extract()
- ~~`domain_tags["lineno"]`~~ — not stamped in _extract_class or _extract_function
- ~~`domain_tags["end_lineno"]`~~ — not stamped in _extract_class or _extract_function

---

## Implementation Notes

### Pattern to Follow

For sha1 stamping in the module node (inside `extract()`, after reading source):
```python
import hashlib

source_bytes = source.encode("utf-8")
sha1 = hashlib.sha1(source_bytes).hexdigest()
# ... in module node domain_tags:
domain_tags={
    "symbol_type": "module",
    "sha1": sha1,
    **({"mtime": mtime} if mtime is not None else {}),
}
```

For lineno stamping (in both `_extract_class` and `_extract_function`):
```python
domain_tags={
    ...,  # existing tags
    "lineno": node.start_point[0] + 1,
    "end_lineno": node.end_point[0] + 1,
}
```

tree-sitter uses 0-based line numbers; we convert to 1-based.

### Key Constraints
- `mtime` MUST be keyword-only (after `*`) to avoid breaking positional callers
- sha1 and lineno additions are additive to domain_tags — don't remove existing keys
- All existing tests must continue to pass without modification

---

## Acceptance Criteria

- [ ] `extract(path, source)` without mtime works (backward compatible)
- [ ] `extract(path, source, mtime=1234.5)` stamps `mtime` in module node domain_tags
- [ ] Module node always has `sha1` in domain_tags
- [ ] Every class node has `lineno`/`end_lineno` in domain_tags
- [ ] Every function node has `lineno`/`end_lineno` in domain_tags
- [ ] All existing tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_code_extractor.py -v`

---

## Test Specification

```python
# Add to packages/ai-parrot/tests/knowledge/graphindex/test_code_extractor.py

async def test_extract_stamps_sha1():
    ext = CodeExtractor()
    nodes, edges = await ext.extract("test.py", "x = 1")
    module = [n for n in nodes if n.domain_tags.get("symbol_type") == "module"][0]
    assert "sha1" in module.domain_tags
    assert len(module.domain_tags["sha1"]) == 40  # full hex

async def test_extract_stamps_mtime():
    ext = CodeExtractor()
    nodes, _ = await ext.extract("test.py", "x = 1", mtime=1234.5)
    module = [n for n in nodes if n.domain_tags.get("symbol_type") == "module"][0]
    assert module.domain_tags["mtime"] == 1234.5

async def test_extract_no_mtime_by_default():
    ext = CodeExtractor()
    nodes, _ = await ext.extract("test.py", "x = 1")
    module = [n for n in nodes if n.domain_tags.get("symbol_type") == "module"][0]
    assert "mtime" not in module.domain_tags

async def test_class_has_lineno():
    ext = CodeExtractor()
    nodes, _ = await ext.extract("test.py", "class Foo:\n    pass\n")
    cls = [n for n in nodes if n.domain_tags.get("symbol_type") == "class"][0]
    assert cls.domain_tags["lineno"] == 1
    assert cls.domain_tags["end_lineno"] == 2

async def test_function_has_lineno():
    ext = CodeExtractor()
    nodes, _ = await ext.extract("test.py", "def bar():\n    pass\n")
    func = [n for n in nodes if n.domain_tags.get("symbol_type") == "function"][0]
    assert func.domain_tags["lineno"] == 1
    assert func.domain_tags["end_lineno"] == 2
```

---

## Completion Note

Added `*, mtime: Optional[float] = None` kwarg to `CodeExtractor.extract()`. Computes
`sha1 = hashlib.sha1(source_bytes).hexdigest()` and stamps it unconditionally in the
module node's `domain_tags`. Stamps `mtime` only when provided. Added `"lineno"` and
`"end_lineno"` (1-based from tree-sitter 0-based `start_point`/`end_point`) to both
`_extract_class` and `_extract_function` domain_tags. All 25 tests pass (19 existing +
6 new: sha1, mtime, no-mtime-by-default, class lineno, function lineno, backward compat).
