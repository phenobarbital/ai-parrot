---
type: Wiki Overview
title: 'TASK-1563: GraphIndex Projection Layer'
id: doc:sdd-tasks-completed-task-1563-graphindex-projection-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the core implementation task. It creates the GraphIndex projection
relates_to:
- concept: mod:parrot.knowledge.graphindex.analytics
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.projection
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.knowledge.okf.frontmatter
  rel: mentions
- concept: mod:parrot.knowledge.okf.ontology
  rel: mentions
- concept: mod:parrot.knowledge.okf.uri
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.projection
  rel: mentions
---

# TASK-1563: GraphIndex Projection Layer

**Feature**: FEAT-239 — GraphIndex OKF Frontmatter Projection
**Spec**: `sdd/specs/graphindex-frontmatter.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1561, TASK-1562
**Assigned-to**: unassigned

---

## Context

This is the core implementation task. It creates the GraphIndex projection
module that maps `UniversalNode` → `ConceptFrontmatter` → `.md` sidecar files.
Each node becomes a self-describing OKF-compatible document with YAML frontmatter.
When a node has a `content_ref` pointing to PageIndex storage, the full body text
is loaded; otherwise the summary is used as body.

Implements spec §3 Module 5.

---

## Scope

- Create `graphindex/projection.py` with:
  - `NODE_KIND_TO_CONCEPT_TYPE` mapping dict.
  - `EDGE_KIND_TO_RELATION_TYPE` mapping dict.
  - `GraphProjectionReport` Pydantic model.
  - `node_to_frontmatter_dict(node, edges)` — pure function, no I/O.
  - `project_node_sidecar(node, edges, body)` — combine frontmatter + body.
  - `project_report_frontmatter(analytics, tenant_id)` — generate report frontmatter.
  - `project_graph_sidecars(nodes, edges, output_dir, content_store, pageindex_toolkit)` — async, writes files.
- Implement `content_ref` resolution: parse `pageindex://` URI, load body from
  `NodeContentStore.load()`. Fall back to summary if content_ref is absent or
  load returns None.
- Write comprehensive unit tests in `tests/knowledge/graphindex/test_projection.py`.
- Sidecars must be byte-deterministic.

**NOT in scope**: Wiring into `GraphIndexBuilder.build()` (TASK-1564),
modifying `analytics.py` (TASK-1564).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/projection.py` | CREATE | Projection module |
| `packages/ai-parrot/tests/knowledge/graphindex/test_projection.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From shared OKF package (created by TASK-1560, TASK-1561):
from parrot.knowledge.okf.ontology import ConceptType      # knowledge/okf/ontology.py
from parrot.knowledge.okf.ontology import RelationType      # knowledge/okf/ontology.py
from parrot.knowledge.okf.ontology import RelatesTo         # knowledge/okf/ontology.py
from parrot.knowledge.okf.ontology import SourceProvenance  # knowledge/okf/ontology.py
from parrot.knowledge.okf.frontmatter import project_frontmatter  # knowledge/okf/frontmatter.py
from parrot.knowledge.okf.uri import build_uri, parse_uri         # knowledge/okf/uri.py

# From GraphIndex schema:
from parrot.knowledge.graphindex.schema import UniversalNode   # graphindex/schema.py:70
from parrot.knowledge.graphindex.schema import UniversalEdge   # graphindex/schema.py:101
from parrot.knowledge.graphindex.schema import NodeKind         # graphindex/schema.py:32
from parrot.knowledge.graphindex.schema import EdgeKind         # graphindex/schema.py:52

# For content resolution:
from parrot.knowledge.pageindex.content_store import NodeContentStore  # content_store.py:123
# NodeContentStore.load(tree_name: str, node_id: str) -> Optional[str]

# For analytics type (report frontmatter):
from parrot.knowledge.graphindex.analytics import AnalyticsResult  # analytics.py:48
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py
class UniversalNode(BaseModel):                     # line 70
    node_id: str                                    # line 71
    kind: NodeKind                                  # line 72
    title: str                                      # line 73
    source_uri: str                                 # line 74
    content_ref: Optional[str] = None               # line 75
    summary: Optional[str] = None                   # line 76
    domain_tags: dict = Field(default_factory=dict) # line 78
    parent_id: Optional[str] = None                 # line 79

class UniversalEdge(BaseModel):                     # line 101
    source_id: str                                  # line 102
    target_id: str                                  # line 103
    kind: EdgeKind                                  # line 104

class NodeKind(str, Enum):                          # line 32
    DOCUMENT = "document"
    SECTION = "section"
    SYMBOL = "symbol"
    CONCEPT = "concept"
    RATIONALE = "rationale"
    SKILL = "skill"

class EdgeKind(str, Enum):                          # line 52
    CONTAINS = "contains"
    REFERENCES = "references"
    DEFINES = "defines"
    MENTIONS = "mentions"
    EXPLAINS = "explains"

# project_frontmatter() expects a dict with these keys:
# - node["concept_id"] (REQUIRED)
# - node.get("type", "Section")
# - node.get("title", "")
# - node.get("node_id", "")
# - node.get("summary", "")
# - node.get("categories", []) or node.get("tags", [])
# - node.get("timestamp", "")
# - node.get("relates_to")
# - node.get("source")

# content_ref parsing pattern:
# "pageindex://tree-name/node-id"
# scheme, rest = uri.split("://", 1)
# tree_name, node_id = rest.split("/", 1)

# NodeContentStore (content_store.py)
# def load(self, tree_name: str, node_id: str) -> Optional[str]:  # line 123

# flatten_concept_id_for_filename (projection.py:55)
# from parrot.knowledge.pageindex.okf.projection import flatten_concept_id_for_filename
```

### Does NOT Exist
- ~~`GraphIndexBuilder.project_sidecars()`~~ — no such method; this task creates standalone functions
- ~~`ConceptFrontmatter.from_universal_node()`~~ — no such factory
- ~~`parrot.knowledge.graphindex.projection`~~ — does not exist yet; this task creates it
- ~~A standalone URI parser function~~ — `parse_uri()` created by TASK-1562

---

## Implementation Notes

### Pattern to Follow: node_to_frontmatter_dict
```python
def node_to_frontmatter_dict(
    node: UniversalNode,
    edges: list[UniversalEdge],
) -> dict:
    """Convert UniversalNode + outgoing edges into the dict format
    expected by project_frontmatter()."""
    outgoing = [e for e in edges if e.source_id == node.node_id]
    relates_to = [
        {
            "concept": e.target_id,
            "rel": EDGE_KIND_TO_RELATION_TYPE[e.kind].value,
        }
        for e in outgoing
        if e.kind in EDGE_KIND_TO_RELATION_TYPE
    ]
    return {
        "concept_id": node.node_id,   # maps to ConceptFrontmatter.id
        "type": NODE_KIND_TO_CONCEPT_TYPE[node.kind].value,
        "title": node.title,
        "node_id": node.node_id,
        "summary": node.summary or node.title,
        "categories": sorted(node.domain_tags.get("categories", [])),
        "timestamp": node.domain_tags.get("timestamp", ""),
        "relates_to": relates_to,
        "source": {"document": node.source_uri} if node.source_uri else None,
    }
```

### Pattern to Follow: content_ref resolution
```python
def _resolve_body(
    node: UniversalNode,
    content_store: Optional[NodeContentStore],
) -> str:
    """Resolve full body from content_ref, or fall back to summary."""
    if node.content_ref and content_store:
        try:
            idx_type, rest = parse_uri(node.content_ref)
            if idx_type == "pageindex":
                tree_name, node_id = rest.split("/", 1)
                body = content_store.load(tree_name, node_id)
                if body:
                    return body
        except (ValueError, Exception):
            pass  # fall through to summary
    return node.summary or node.title or ""
```

### Key Constraints
- `project_frontmatter()` requires `"concept_id"` key — map `node.node_id` to it.
- Use `build_uri("graphindex", node.node_id)` for the `resource` field
  in frontmatter. The `project_frontmatter()` function builds the resource
  from `tree_name` — pass `"graphindex"` as tree_name.
- Sort tags alphabetically for byte-determinism.
- `project_graph_sidecars()` writes to `output_dir / "nodes" / f"{filename}.md"`.
  Create the `nodes/` subdirectory.
- Use `flatten_concept_id_for_filename()` for sidecar filenames.

### References in Codebase
- `pageindex/okf/projection.py` — pattern for project_sidecars (line 131)
- `pageindex/okf/frontmatter.py:96` — project_frontmatter interface
- `graphindex/extractors/loader.py:68` — _content_ref format
- `pageindex/content_store.py:123` — NodeContentStore.load()

---

## Acceptance Criteria

- [ ] `node_to_frontmatter_dict()` correctly maps all 6 NodeKind values
- [ ] `node_to_frontmatter_dict()` falls back to title when summary is None
- [ ] `project_node_sidecar()` produces frontmatter + body
- [ ] Sidecars are byte-deterministic (same input → same output)
- [ ] `project_graph_sidecars()` writes files to `output_dir/nodes/`
- [ ] content_ref resolution loads full body from NodeContentStore
- [ ] Falls back to summary when content_ref is absent or unresolvable
- [ ] `project_report_frontmatter()` returns valid YAML with type=Document
- [ ] `GraphProjectionReport` model has correct fields
- [ ] All tests pass: `pytest tests/knowledge/graphindex/test_projection.py -v`

---

## Test Specification

```python
# tests/knowledge/graphindex/test_projection.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, NodeKind, EdgeKind,
)
from parrot.knowledge.graphindex.projection import (
    node_to_frontmatter_dict,
    project_node_sidecar,
    project_graph_sidecars,
    project_report_frontmatter,
    NODE_KIND_TO_CONCEPT_TYPE,
    EDGE_KIND_TO_RELATION_TYPE,
    GraphProjectionReport,
)
from parrot.knowledge.okf.ontology import ConceptType
from parrot.knowledge.okf.frontmatter import parse_frontmatter


@pytest.fixture
def symbol_node():
    return UniversalNode(
        node_id="sym-builder-abc",
        kind=NodeKind.SYMBOL,
        title="GraphIndexBuilder",
        source_uri="file:///builder.py",
        summary="Orchestrates the build pipeline.",
        domain_tags={"categories": ["python", "builder"]},
    )


@pytest.fixture
def doc_node_with_content_ref():
    return UniversalNode(
        node_id="doc-readme-xyz",
        kind=NodeKind.DOCUMENT,
        title="README",
        source_uri="file:///README.md",
        content_ref="pageindex://docs/readme-node",
        summary="Project docs.",
    )


@pytest.fixture
def sample_edges():
    return [
        UniversalEdge(
            source_id="sym-builder-abc",
            target_id="doc-readme-xyz",
            kind=EdgeKind.REFERENCES,
        ),
    ]


class TestNodeToFrontmatterDict:
    def test_maps_symbol_type(self, symbol_node, sample_edges):
        d = node_to_frontmatter_dict(symbol_node, sample_edges)
        assert d["type"] == "Symbol"
        assert d["concept_id"] == "sym-builder-abc"

    def test_maps_all_node_kinds(self):
        for kind in NodeKind:
            node = UniversalNode(
                node_id=f"test-{kind.value}",
                kind=kind,
                title="Test",
                source_uri="file:///test",
            )
            d = node_to_frontmatter_dict(node, [])
            assert d["type"] == NODE_KIND_TO_CONCEPT_TYPE[kind].value

    def test_summary_fallback_to_title(self):
        node = UniversalNode(
            node_id="no-summary",
            kind=NodeKind.CONCEPT,
            title="Fallback Title",
            source_uri="file:///test",
            summary=None,
        )
        d = node_to_frontmatter_dict(node, [])
        assert d["summary"] == "Fallback Title"

    def test_relates_to_from_edges(self, symbol_node, sample_edges):
        d = node_to_frontmatter_dict(symbol_node, sample_edges)
        assert len(d["relates_to"]) == 1
        assert d["relates_to"][0]["concept"] == "doc-readme-xyz"
        assert d["relates_to"][0]["rel"] == "references"


class TestProjectNodeSidecar:
    def test_contains_frontmatter_and_body(self, symbol_node, sample_edges):
        sidecar = project_node_sidecar(symbol_node, sample_edges, "Body text here.")
        assert sidecar.startswith("---\n")
        assert "Body text here." in sidecar

    def test_byte_determinism(self, symbol_node, sample_edges):
        s1 = project_node_sidecar(symbol_node, sample_edges, "Body")
        s2 = project_node_sidecar(symbol_node, sample_edges, "Body")
        assert s1 == s2

    def test_parseable_frontmatter(self, symbol_node, sample_edges):
        sidecar = project_node_sidecar(symbol_node, sample_edges, "Body")
        fm = parse_frontmatter(sidecar)
        assert fm.type == ConceptType.SYMBOL
        assert fm.id == "sym-builder-abc"


class TestProjectGraphSidecars:
    @pytest.mark.asyncio
    async def test_writes_files(self, symbol_node, sample_edges, tmp_path):
        report = await project_graph_sidecars(
            [symbol_node], sample_edges, tmp_path,
        )
        assert report.nodes_projected == 1
        assert (tmp_path / "nodes").is_dir()
        assert len(list((tmp_path / "nodes").glob("*.md"))) == 1

    @pytest.mark.asyncio
    async def test_content_ref_resolution(
        self, doc_node_with_content_ref, tmp_path,
    ):
        mock_store = MagicMock()
        mock_store.load.return_value = "Full body from PageIndex."
        report = await project_graph_sidecars(
            [doc_node_with_content_ref], [], tmp_path,
            content_store=mock_store,
        )
        files = list((tmp_path / "nodes").glob("*.md"))
        content = files[0].read_text()
        assert "Full body from PageIndex." in content


class TestProjectReportFrontmatter:
    def test_produces_valid_yaml(self):
        from parrot.knowledge.graphindex.analytics import AnalyticsResult
        analytics = AnalyticsResult()
        fm = project_report_frontmatter(analytics, "test-tenant")
        assert fm.startswith("---\n")
        assert fm.endswith("---\n")
        assert "type: Document" in fm
```

---

## Agent Instructions

When you pick up this task:

1. **Verify TASK-1561 and TASK-1562 are complete**
2. **Read `project_frontmatter()` source** to understand the exact dict contract
3. **Implement mapping functions first** (pure, testable)
4. **Then implement sidecar writing** (async, file I/O)
5. **Test content_ref resolution** with mocked NodeContentStore
6. **Verify byte-determinism** — run the same input twice, compare output
7. **Commit and update index**

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-06-16
**Notes**: Created `graphindex/projection.py` with all required functions and
`GraphProjectionReport` model. All 33 tests pass. content_ref resolution via
`NodeContentStore.load()` implemented with graceful fallback to summary/title.
Byte-determinism verified (same input → same output). Cython .so files needed
to be copied from main repo to worktree for tests to run (pre-existing worktree
environment issue, not a code issue).

**Deviations from spec**: The `build_uri()` import was removed from projection.py
since `project_frontmatter()` builds the resource URI internally using the
tree_name="graphindex" parameter (produces `pageindex://graphindex/<node_id>`
as the resource URI). The `project_report_frontmatter()` function builds its
resource via the node dict's concept_id passed to project_frontmatter() rather
than via a direct build_uri() call.

---

*(Agent fills this in when done)*
