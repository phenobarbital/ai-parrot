# TASK-2066: Builder & Analytics Integration

**Feature**: FEAT-401 — Leiden Community Detection & Inter-Community Relations
**Spec**: `sdd/specs/leiden-community-detection-and-inter-community-relations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2064, TASK-2065
**Assigned-to**: unassigned

---

## Context

This task wires the Leiden algorithm and inter-community relations into the
existing GraphIndex pipeline. The builder needs a new `community_algorithm`
parameter, and analytics needs to compute and store the inter-community
graph alongside existing community data.

Implements Spec §3 Module 3.

---

## Scope

- Add `community_algorithm: str = "leiden"` parameter to
  `GraphIndexBuilder.__init__()`.
- Forward `community_algorithm` to `detect_communities(algorithm=...)`
  in the builder's Stage 4.5 block.
- Add `inter_community: Optional[InterCommunityGraph] = None` field to
  `AnalyticsResult` dataclass.
- After community detection in `compute_analytics()` (or in the builder
  after Stage 4.5), call `compute_inter_community_graph()` and store the
  result on `AnalyticsResult.inter_community`.
- Add inter-community stats to the `_render_report()` function: a new
  `## Inter-Community Relations` section in `GRAPH_REPORT.md` showing
  community pairs, edge counts, coupling ratios, and overall density.
- Write unit/integration tests.

**NOT in scope**:
- Leiden algorithm itself (TASK-2064)
- Inter-community model (TASK-2065)
- HTML export (TASK-2067)
- CLI / docs (TASK-2068)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` | MODIFY | Add `community_algorithm` param, forward to `detect_communities()` |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py` | MODIFY | Add `inter_community` field to `AnalyticsResult`, compute it, render in report |
| `packages/ai-parrot/tests/knowledge/graphindex/test_analytics.py` | MODIFY | Add inter-community field and report section tests |
| `packages/ai-parrot/tests/knowledge/graphindex/test_builder.py` | MODIFY | Add `community_algorithm` param test (if builder tests exist) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Builder
from parrot.knowledge.graphindex.builder import GraphIndexBuilder
# builder.py imports detect_communities at top level:
from parrot.knowledge.graphindex.communities import (
    CommunitiesResult,
    detect_communities,
)

# Analytics
from parrot.knowledge.graphindex.analytics import (
    AnalyticsResult,            # verified: analytics.py:155 (dataclass)
    compute_analytics,          # verified: analytics.py:188
    generate_report,            # verified: analytics.py:755
    KnowledgeGaps,              # verified: analytics.py:50
)

# Inter-community (from TASK-2065)
from parrot.knowledge.graphindex.inter_community import (
    InterCommunityGraph,
    compute_inter_community_graph,
)
```

### Existing Signatures to Use

```python
# builder.py — GraphIndexBuilder.__init__
def __init__(
    self,
    persistence: GraphIndexPersistence,
    embedder: GraphIndexEmbedder,
    output_dir: Optional[Path] = None,
    ignore_file: Optional[Path] = None,
    resolution_config: Optional[ResolutionConfig] = None,
    pageindex_toolkit: Optional[PageIndexToolkit] = None,
    signal_config: Optional[SignalRelevanceConfig] = None,
    detect_communities_enabled: bool = False,
    community_resolution: float = 1.0,
    code_extractor_class: Type = CodeExtractor,
    export_html_enabled: bool = False,
) -> None: ...

# builder.py — Stage 4.5 (approx line 195)
# self.last_community_result = detect_communities(
#     graph=assembler.graph, nodes=all_nodes,
#     resolution=self.community_resolution,
#     signal_config=self.signal_config,
#     embedder=self.embedder if self.signal_config else None,
#     write_back_to_nodes=True,
# )

# analytics.py — AnalyticsResult (line 155, dataclass)
@dataclass
class AnalyticsResult:
    god_nodes: list[dict] = field(default_factory=list)
    surprising_connections: list[dict] = field(default_factory=list)
    suggested_questions: list[str] = field(default_factory=list)
    communities: Optional[CommunitiesResult] = None
    knowledge_gaps: Optional[KnowledgeGaps] = None
    dismissed: Optional[DismissedInsights] = None

# analytics.py — _render_report (line ~785)
# Renders GRAPH_REPORT.md sections: God Nodes, Surprising Connections,
# Communities, Knowledge Gaps. Each section is conditional on data presence.
```

### Does NOT Exist

- ~~`GraphIndexBuilder.community_algorithm`~~ — param does not exist yet (to be added)
- ~~`AnalyticsResult.inter_community`~~ — field does not exist yet (to be added)
- ~~inter-community section in `_render_report`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow

```python
# builder.py — add community_algorithm param alongside existing community params:
def __init__(self, ..., community_algorithm: str = "leiden", ...):
    self.community_algorithm = community_algorithm

# builder.py — Stage 4.5: pass algorithm through:
self.last_community_result = detect_communities(
    graph=assembler.graph, nodes=all_nodes,
    resolution=self.community_resolution,
    algorithm=self.community_algorithm,  # NEW
    ...
)

# analytics.py — compute inter-community after community detection:
# In builder.build() after Stage 4.5, or in a helper:
if self.last_community_result is not None:
    inter_community = compute_inter_community_graph(
        assembler.graph, self.last_community_result
    )
    analytics.inter_community = inter_community

# analytics.py — _render_report new section:
# Follow the pattern of existing optional sections (Communities, Knowledge Gaps)
if analytics.inter_community is not None and analytics.inter_community.relations:
    lines.append("## Inter-Community Relations\n")
    lines.append(f"**Density**: {analytics.inter_community.density:.2%} ...")
    lines.append("| Source | Target | Edges (→) | Edges (←) | Coupling |")
    ...
```

### Key Constraints

- `AnalyticsResult` is a `@dataclass`, not a Pydantic model — add the
  field with `field(default=None)` and `Optional` typing.
- The `_render_report` function builds a list of Markdown lines. Follow
  the existing conditional-section pattern (check for `None` / empty
  before rendering).
- The builder already imports `detect_communities` at the top level —
  adding `algorithm=` is a keyword-only addition, backward compatible.
- Inter-community computation should happen in the builder (after Stage
  4.5, before analytics), since it needs both the `graph` and the
  `CommunitiesResult`. Store it on `analytics.inter_community` alongside
  `analytics.communities`.

### References in Codebase

- `builder.py` Stage 4.5 block — where `detect_communities()` is called
- `analytics.py:155` — `AnalyticsResult` dataclass definition
- `analytics.py:~785` — `_render_report()` for the report rendering pattern

---

## Acceptance Criteria

- [ ] `GraphIndexBuilder(community_algorithm="leiden")` forwards to `detect_communities(algorithm="leiden")`
- [ ] `GraphIndexBuilder(community_algorithm="louvain")` forwards to `detect_communities(algorithm="louvain")`
- [ ] Default `community_algorithm` is `"leiden"`
- [ ] `AnalyticsResult.inter_community` is populated when communities are detected
- [ ] `AnalyticsResult.inter_community` is `None` when communities are not detected
- [ ] `_render_report()` includes `## Inter-Community Relations` section when data present
- [ ] `_render_report()` omits section when `inter_community` is `None` or empty
- [ ] Report section shows community pairs, edge counts, coupling ratios, density
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_analytics.py -v`

---

## Test Specification

```python
# test_analytics.py (additions)
from parrot.knowledge.graphindex.inter_community import InterCommunityGraph

class TestInterCommunityIntegration:
    def test_analytics_inter_community_field(self):
        """AnalyticsResult.inter_community populated when communities present."""
        # Build a small graph, run compute_analytics with communities
        analytics = AnalyticsResult()
        analytics.inter_community = InterCommunityGraph(
            relations=[], community_count=2,
            connected_pairs=0, total_possible_pairs=1, density=0.0
        )
        assert analytics.inter_community is not None

    def test_report_inter_community_section(self):
        """_render_report includes ## Inter-Community Relations."""
        # Build analytics with inter_community data
        report = _render_report(analytics)
        assert "## Inter-Community Relations" in report

    def test_report_no_inter_community_section_when_empty(self):
        """_render_report omits section when no inter-community data."""
        analytics = AnalyticsResult()
        report = _render_report(analytics)
        assert "## Inter-Community Relations" not in report
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2064 and TASK-2065 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `InterCommunityGraph` exists (from TASK-2065)
4. **Update status** in the per-spec index → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2066-builder-analytics-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-01
**Notes**: Added `community_algorithm: str = "leiden"` to
`GraphIndexBuilder.__init__()`, stored as `self.community_algorithm`,
forwarded as `detect_communities(..., algorithm=self.community_algorithm)`
in Stage 4.5. Added `inter_community: Optional["InterCommunityGraph"] = None`
field to `AnalyticsResult` (with a lazy try/except import mirroring the
existing `CommunitiesResult` pattern, so `analytics.py` stays importable
without FEAT-401's `inter_community.py` — though that module has no
optional deps itself, only Leiden does). In `builder.py` Stage 6, right
after `analytics.communities = self.last_community_result`, added a call
to `compute_inter_community_graph(assembler.graph, self.last_community_result)`
storing the result on `analytics.inter_community` (guarded by
`is not None`, matching the Implementation Notes' directive that this
computation belongs in the builder, not `compute_analytics()`, since it
needs both the graph and the partition). Added a new
`## Inter-Community Relations` section to `_render_report()` (guarded on
`inter_community is not None and .relations` non-empty, positioned after
`## Communities` and before `## Knowledge Gaps`), rendering density and a
markdown table (source/target label, directed/reverse edge counts,
directed/reverse weights, coupling ratio).

Added 7 new tests to `test_analytics.py` (`TestInterCommunityIntegration`)
covering: default-None field, field population, report section rendering
(labels + coupling ratio + density), section omission when `None` or
empty, and a full `generate_report()` file-write round trip. Added 5 new
tests to `test_builder.py` (`TestCommunityAlgorithmParam`) covering:
default `"leiden"`, `"louvain"` override, forwarding to
`detect_communities(algorithm=...)` (verified via mock), and
`compute_inter_community_graph()` being called/not-called depending on
`detect_communities_enabled`.

Environment note: this worktree is missing several compiled Cython
extensions under `parrot.utils.*` (`.so` build artifacts are gitignored,
not checked into git) — `test_builder.py` could not even be *collected*
here without them, confirmed pre-existing via `git stash` (same failure
on the unmodified file). Temporarily copied the missing `.so` files from
the main repo checkout into the worktree (gitignored, not committed) to
unblock local verification; also discovered — and worked around locally
with `pytest --import-mode=importlib` — a separate pre-existing pytest
module-name collision between this worktree's and the main repo's
identically-pathed `test_builder.py` (default "prepend" import mode
computes the same dotted module name for both, silently reusing whichever
copy pytest already had cached). Both issues are pre-existing repo/tooling
gaps, not introduced by this task, and are out of scope to fix here. With
those two local workarounds, ALL touched test files pass in full:
`test_analytics.py` (73), `test_communities.py` (53 — including the 2
`TestBuilderIntegration` tests that failed before due to the same missing
`.so`), `test_inter_community.py` (13), `test_builder.py` (21). `ruff
check` on all 4 touched files shows only pre-existing findings (BLE001
blind-exception on the pipeline's existing per-stage try/except pattern,
plus 3 pre-existing F841 unused-variable fixtures in `test_analytics.py`)
— all confirmed via `git stash` to predate this task.

**Deviations from spec**: none.
