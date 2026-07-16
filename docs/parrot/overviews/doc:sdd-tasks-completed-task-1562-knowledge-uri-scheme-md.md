---
type: Wiki Overview
title: 'TASK-1562: Knowledge URI Scheme'
id: doc:sdd-tasks-completed-task-1562-knowledge-uri-scheme-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `knowledge://` URI scheme provides unified cross-index addressing.
relates_to:
- concept: mod:parrot.knowledge.okf.ontology
  rel: mentions
- concept: mod:parrot.knowledge.okf.uri
  rel: mentions
---

# TASK-1562: Knowledge URI Scheme

**Feature**: FEAT-239 — GraphIndex OKF Frontmatter Projection
**Spec**: `sdd/specs/graphindex-frontmatter.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1560
**Assigned-to**: unassigned

---

## Context

The `knowledge://` URI scheme provides unified cross-index addressing.
PageIndex uses `pageindex://<tree>/<node>` and GraphIndex uses ArangoDB keys.
This task creates a shared URI module that builds and parses
`knowledge://<index_type>/<identifier>` URIs, and also handles legacy
`pageindex://` URIs.

Implements spec §3 Module 3.

---

## Scope

- Create `knowledge/okf/uri.py` with `build_uri()` and `parse_uri()`.
- `build_uri(index_type, identifier)` → `"knowledge://<index_type>/<identifier>"`.
- `parse_uri(uri)` → `(index_type, identifier)`.
- `parse_uri` must accept both `knowledge://` and legacy `pageindex://` URIs.
  For `pageindex://`, return `("pageindex", "<rest>")`.
- Raise `ValueError` for unrecognised schemes.
- Update `knowledge/okf/__init__.py` to export `build_uri` and `parse_uri`.
- Write unit tests.

**NOT in scope**: Migrating existing `pageindex://` URIs to `knowledge://`.
GraphIndex projection (TASK-1563) and builder integration (TASK-1564).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/okf/uri.py` | CREATE | URI builder/parser |
| `packages/ai-parrot/src/parrot/knowledge/okf/__init__.py` | MODIFY | Add uri exports |
| `packages/ai-parrot/tests/knowledge/okf/test_uri.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# After TASK-1560:
from parrot.knowledge.okf.ontology import ConceptType  # knowledge/okf/ontology.py

# Content-ref parsing pattern (from tests, not a function):
# packages/ai-parrot/tests/knowledge/graphindex/test_loader_extractor.py:264-268
# scheme, rest = content_ref.split("://", 1)
# tree, node_id = rest.split("/", 1)

# The _content_ref builder in loader.py:
# packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py:68
# def _content_ref(tree_name: str, node_id: str) -> str:
#     return f"pageindex://{tree_name}/{node_id}"
```

### Existing Signatures to Use
No existing URI parser module exists. This is a new leaf module with no
dependencies on other project code (only standard library).

### Does NOT Exist
- ~~`parrot.knowledge.okf.uri`~~ — does not exist yet; this task creates it
- ~~A standalone `parse_pageindex_uri()` function~~ — only inline splitting exists
- ~~`urllib.parse` for pageindex:// scheme~~ — custom schemes need manual parsing

---

## Implementation Notes

### Pattern to Follow
```python
# knowledge/okf/uri.py
_KNOWLEDGE_SCHEME = "knowledge"
_LEGACY_PAGEINDEX_SCHEME = "pageindex"
_KNOWN_SCHEMES = {_KNOWLEDGE_SCHEME, _LEGACY_PAGEINDEX_SCHEME}


def build_uri(index_type: str, identifier: str) -> str:
    """Build a knowledge:// URI."""
    if not index_type or not identifier:
        raise ValueError("index_type and identifier must be non-empty")
    return f"knowledge://{index_type}/{identifier}"


def parse_uri(uri: str) -> tuple[str, str]:
    """Parse a knowledge:// or legacy pageindex:// URI.

    Returns (index_type, identifier).
    """
    if "://" not in uri:
        raise ValueError(f"Invalid URI (no scheme): {uri}")
    scheme, rest = uri.split("://", 1)
    if scheme == _KNOWLEDGE_SCHEME:
        # knowledge://graphindex/node-123 → ("graphindex", "node-123")
        idx_type, _, identifier = rest.partition("/")
        if not idx_type or not identifier:
            raise ValueError(f"Malformed knowledge URI: {uri}")
        return (idx_type, identifier)
    elif scheme == _LEGACY_PAGEINDEX_SCHEME:
        # pageindex://tree/node → ("pageindex", "tree/node")
        return ("pageindex", rest)
    else:
        raise ValueError(f"Unrecognised URI scheme: {scheme}")
```

### Key Constraints
- Pure functions, no I/O, no external dependencies.
- Must handle edge cases: empty strings, missing `://`, unknown schemes.
- The `pageindex://` legacy format keeps the full `tree/node` as the identifier
  (do NOT split further — callers know the format).
- `knowledge://` URIs split on the FIRST `/` after the scheme to get index_type.

---

## Acceptance Criteria

- [ ] `build_uri("graphindex", "node-1")` → `"knowledge://graphindex/node-1"`
- [ ] `parse_uri("knowledge://graphindex/node-1")` → `("graphindex", "node-1")`
- [ ] `parse_uri("knowledge://pageindex/tree/concept-id")` → `("pageindex", "tree/concept-id")`
- [ ] `parse_uri("pageindex://tree/node")` → `("pageindex", "tree/node")`
- [ ] `parse_uri("http://example.com")` raises `ValueError`
- [ ] `parse_uri("garbage")` raises `ValueError`
- [ ] `build_uri("", "x")` raises `ValueError`
- [ ] Round-trip: `parse_uri(build_uri("graphindex", "x"))` → `("graphindex", "x")`
- [ ] All tests pass: `pytest tests/knowledge/okf/test_uri.py -v`

---

## Test Specification

```python
# tests/knowledge/okf/test_uri.py
import pytest
from parrot.knowledge.okf.uri import build_uri, parse_uri


class TestBuildUri:
    def test_basic(self):
        assert build_uri("graphindex", "node-1") == "knowledge://graphindex/node-1"

    def test_with_slashes_in_id(self):
        assert build_uri("pageindex", "tree/concept") == "knowledge://pageindex/tree/concept"

    def test_empty_index_type_raises(self):
        with pytest.raises(ValueError):
            build_uri("", "node-1")

    def test_empty_identifier_raises(self):
        with pytest.raises(ValueError):
            build_uri("graphindex", "")


class TestParseUri:
    def test_knowledge_scheme(self):
        assert parse_uri("knowledge://graphindex/node-1") == ("graphindex", "node-1")

    def test_knowledge_with_nested_id(self):
        assert parse_uri("knowledge://pageindex/tree/concept") == ("pageindex", "tree/concept")

    def test_legacy_pageindex(self):
        assert parse_uri("pageindex://my-tree/my-node") == ("pageindex", "my-tree/my-node")

    def test_unknown_scheme_raises(self):
        with pytest.raises(ValueError, match="Unrecognised URI scheme"):
            parse_uri("http://example.com")

    def test_no_scheme_raises(self):
        with pytest.raises(ValueError):
            parse_uri("garbage-no-scheme")


class TestRoundTrip:
    def test_build_then_parse(self):
        uri = build_uri("graphindex", "sym-builder-abc")
        idx_type, identifier = parse_uri(uri)
        assert idx_type == "graphindex"
        assert identifier == "sym-builder-abc"
```

---

## Agent Instructions

When you pick up this task:

1. **Verify TASK-1560 is complete** — the `parrot/knowledge/okf/` package must exist
2. **Create `uri.py`** as a standalone leaf module (no project imports needed)
3. **Update `__init__.py`** to export `build_uri` and `parse_uri`
4. **Run tests** and verify all pass
5. **Commit and update index**

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-06-16
**Notes**: Created `parrot/knowledge/okf/uri.py` with `build_uri()` and `parse_uri()`.
Handles both `knowledge://` and legacy `pageindex://` schemes. Updated `__init__.py`.
All 17 tests pass.

**Deviations from spec**: None.
