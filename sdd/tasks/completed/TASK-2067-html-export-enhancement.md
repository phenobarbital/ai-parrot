# TASK-2067: HTML Export & Report Enhancement

**Feature**: FEAT-401 — Leiden Community Detection & Inter-Community Relations
**Spec**: `sdd/specs/leiden-community-detection-and-inter-community-relations.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2065, TASK-2066
**Assigned-to**: unassigned

---

## Context

This task adds inter-community relations data to the HTML export and
`graph.json` payload. The HTML export gets a collapsible summary table
panel showing community pairs, edge counts, weights, coupling ratios,
and direction arrows.

Implements Spec §3 Module 4.

---

## Scope

- Extend `GraphExportPayload` (or add a sibling structure) to include
  inter-community relations data in the serialized `graph.json`.
- Extend `build_export_payload()` to accept and serialize
  `InterCommunityGraph` data.
- Extend `export_graph()` to accept and forward `inter_community` data.
- Add a collapsible `<details>` summary table panel in `graph.html`
  with columns: Community A label, Community B label, Edges A→B,
  Edges B→A, Total Weight, Coupling Ratio. Use an arrow (→/←) to
  indicate predominant flow direction.
- Write tests for the JSON payload and HTML rendering.

**NOT in scope**:
- Force-directed meta-graph overlay (deferred to future enhancement)
- Leiden algorithm (TASK-2064)
- Inter-community model (TASK-2065)
- CLI subcommand (TASK-2068)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/export_html.py` | MODIFY | Extend payload, add table panel to HTML |
| `packages/ai-parrot/tests/knowledge/graphindex/test_export_html.py` | MODIFY | Add inter-community export tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.graphindex.export_html import (
    export_graph,               # verified: export_html.py:530
    build_export_payload,       # verified: export_html.py:208
    GraphExportPayload,         # verified: export_html.py (Pydantic model)
    GraphExportNode,            # verified: export_html.py (Pydantic model)
    GraphExportEdge,            # verified: export_html.py (Pydantic model)
    GraphExportCategory,        # verified: export_html.py (Pydantic model)
    write_graph_json,           # verified: export_html.py
    write_graph_html,           # verified: export_html.py
    _render_html,               # verified: export_html.py (private)
)

# Inter-community (from TASK-2065)
from parrot.knowledge.graphindex.inter_community import (
    InterCommunityGraph,
    InterCommunityRelation,
)
```

### Existing Signatures to Use

```python
# export_html.py — export_graph (line 530)
def export_graph(
    graph: "rustworkx.PyDiGraph",
    output_dir: Path,
    *,
    communities: Optional[Any] = None,
    analytics: Optional[Any] = None,
    god_top_k: int = 15,
    title: str = "GraphIndex Knowledge Map",
    echarts_js: Optional[str] = None,
    allow_cdn_fallback: bool = True,
) -> tuple[Path, Path]: ...

# export_html.py — build_export_payload (line 208)
def build_export_payload(
    graph: "rustworkx.PyDiGraph",
    node_to_community: ...,
    community_order: ...,
    community_labels: ...,
    community_sizes: ...,
    modularity: ...,
    god_node_ids: ...,
    god_scores: ...,
    ...
) -> GraphExportPayload: ...

# export_html.py — GraphExportPayload (Pydantic model)
class GraphExportPayload(BaseModel):
    nodes: list[GraphExportNode]
    edges: list[GraphExportEdge]
    categories: list[GraphExportCategory]
    modularity: Optional[float] = None
    # ... other fields
```

### Does NOT Exist

- ~~`GraphExportPayload.inter_community_relations`~~ — field does not exist yet
- ~~`export_graph(..., inter_community=...)`~~ — param does not exist yet
- ~~inter-community table in `_render_html`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow

```python
# export_html.py — extend GraphExportPayload:
class GraphExportPayload(BaseModel):
    # ... existing fields ...
    inter_community_relations: list[dict] = Field(default_factory=list)
    inter_community_density: Optional[float] = None

# export_html.py — extend export_graph to accept inter_community:
def export_graph(
    graph, output_dir, *,
    communities=None, analytics=None,
    inter_community=None,  # NEW: Optional[InterCommunityGraph]
    ...
): ...

# _render_html — add a collapsible table panel after the graph:
# <details class="inter-community-panel">
#   <summary>Inter-Community Relations (N pairs)</summary>
#   <table>
#     <tr><th>Community A</th><th>Community B</th><th>→</th><th>←</th>...
#   </table>
# </details>
```

### Key Constraints

- The HTML is self-contained (strict CSP, no external resources). The
  table uses inline CSS only.
- `graph.json` must remain backward-compatible — the new fields are
  additive (empty list / null defaults).
- The builder calls `export_graph()` at Stage 6.6 — pass
  `inter_community` from the analytics result there.
- Follow the existing `communities` param pattern in `export_graph()` —
  use `getattr` duck-typing rather than importing `InterCommunityGraph`
  at the top level, to keep the import optional.

### References in Codebase

- `export_html.py:530` — `export_graph()` adapts communities/analytics
- `export_html.py:208` — `build_export_payload()` builds the serialized data
- `builder.py` Stage 6.6 — calls `export_graph()`

---

## Acceptance Criteria

- [ ] `graph.json` includes `inter_community_relations` array when data present
- [ ] `graph.json` has empty array when no inter-community data
- [ ] `graph.html` shows a collapsible inter-community table when data present
- [ ] Table columns: Community A, Community B, Edges →, Edges ←, Weight, Coupling
- [ ] Table is hidden when no inter-community relations exist
- [ ] No regression in existing HTML export tests
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_export_html.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/graphindex/export_html.py`

---

## Test Specification

```python
# test_export_html.py (additions)

class TestInterCommunityExport:
    def test_export_json_inter_community(self):
        """graph.json payload includes inter-community relations."""
        # Build graph with communities and inter-community data
        # Call export_graph → read graph.json
        import json
        data = json.loads(json_path.read_text())
        assert "inter_community_relations" in data
        assert len(data["inter_community_relations"]) > 0

    def test_export_json_no_inter_community(self):
        """graph.json has empty array when no inter-community data."""
        # Export without inter_community param
        data = json.loads(json_path.read_text())
        assert data.get("inter_community_relations", []) == []

    def test_export_html_has_table(self):
        """graph.html contains inter-community table panel."""
        html = html_path.read_text()
        assert "inter-community" in html.lower()
        assert "<table" in html
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2065 and TASK-2066 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `InterCommunityGraph` exists and `AnalyticsResult.inter_community` field exists
4. **Update status** in the per-spec index → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2067-html-export-enhancement.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-01
**Notes**: Added `inter_community_relations: list[dict]` and
`inter_community_density: Optional[float]` fields to `GraphExportPayload`
(additive defaults, backward-compatible). Extended
`build_export_payload()` with matching optional params, passed through
verbatim (stays pure, no `inter_community` import). Extended
`export_graph()` with an `inter_community: Optional[Any] = None` param,
adapted via `getattr` duck-typing (per the Implementation Notes
constraint — never imports `InterCommunityGraph` at module level) into
plain dicts for the payload. Added a collapsible `<details
id="interCommunityPanel" style="display:none">` table panel to the
`_HTML_TEMPLATE` body (6 columns: Community A, Community B, Edges →,
Edges ←, Weight, Coupling — plus a → / ← direction arrow prefixed onto
the Community B cell per the scope's "direction arrow" requirement) and
a small IIFE in the existing `<script>` block that populates the table
from `GRAPH.inter_community_relations` and reveals the panel
(`display:block`) only when relations is non-empty — reusing the
template's existing `esc()` HTML-escaper (hoisted function declaration)
rather than duplicating it. Verified end-to-end with a manual
`export_graph()` smoke test (real `InterCommunityGraph` → `graph.json` +
`graph.html`) before writing the test suite. Added 7 tests to
`test_export_html.py`: payload field defaults/population, JSON
round-trip with/without inter-community data, HTML table-panel markup
presence, the hidden-by-default static markup, `getattr` duck-typing
(via a bare `SimpleNamespace`, not the real Pydantic model, to prove no
import-time coupling), and a no-regression check on the pre-FEAT-401
call signature. All 25 tests in the file pass (18 pre-existing + 7 new);
`ruff check` shows only pre-existing `RUF059` (unused unpacked
fixture-tuple variables — a convention already used 30+ times in this
file) findings, confirmed via `git stash` to predate this task; my own
new tests were written to avoid adding to that count.

**Deviations from scope (flagged, not silently done)**: `builder.py`
Stage 6.6 (`export_graph(... )` call) is NOT wired to pass
`analytics.inter_community` through, even though this task's
Implementation Notes say "The builder calls `export_graph()` at Stage
6.6 — pass `inter_community` from the analytics result there." The
task's own **Files to Create/Modify** table lists only
`export_html.py` + `test_export_html.py` — NOT `builder.py`. Per
Cardinal Rule 2 (File Fidelity), I did not touch `builder.py`. This
means the full pipeline does not yet auto-populate the HTML/JSON
inter-community panel end-to-end from a real `build()` call; the new
`export_graph(inter_community=...)` parameter works correctly when
called directly (as `wikitoolkit`/agents or a future task would), and
is covered by tests, but the one-line `builder.py` wiring
(`inter_community=analytics.inter_community` alongside the existing
`communities=self.last_community_result` kwarg) is left for a follow-up
task or an explicit scope correction — flagging per Cardinal Rule 4
rather than silently expanding this task's file list.
