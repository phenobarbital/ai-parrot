# TASK-1564: Builder & Analytics Integration

**Feature**: FEAT-239 — GraphIndex OKF Frontmatter Projection
**Spec**: `sdd/specs/graphindex-frontmatter.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1563
**Assigned-to**: unassigned

---

## Context

This is the final wiring task. It integrates the projection layer (TASK-1563)
into the GraphIndex build pipeline by adding Stage 6.5 to
`GraphIndexBuilder.build()` and updating `generate_report()` to prepend OKF
frontmatter to `GRAPH_REPORT.md`. It also updates `graphindex/__init__.py`
to export projection symbols and runs the full integration test suite.

Implements spec §3 Module 6 + Module 7 (integration tests).

---

## Scope

- Insert **Stage 6.5** (projection) into `GraphIndexBuilder.build()` between
  the analytics stage (line ~231) and the return statement.
- Call `project_graph_sidecars(all_nodes, all_edges, self.output_dir,
  content_store=..., pageindex_toolkit=...)` where `content_store` is
  obtained from `self.pageindex_toolkit._content_store` if available.
- Update `generate_report()` to prepend frontmatter: call
  `project_report_frontmatter(analytics, ctx.tenant_id)` and prepend
  to the rendered markdown before writing to disk.
- Update `graphindex/__init__.py` to export: `project_graph_sidecars`,
  `project_node_sidecar`, `node_to_frontmatter_dict`, `GraphProjectionReport`.
- Add `projection_report` field to `BuildResult` (optional).
- Write integration tests.
- Run full FEAT-238 test suite to verify no regressions.

**NOT in scope**: Modifying the projection functions themselves (TASK-1563
handles that).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` | MODIFY | Add Stage 6.5 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py` | MODIFY | Prepend frontmatter in generate_report |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py` | MODIFY | Add projection exports |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py` | MODIFY | Add projection_report to BuildResult |
| `packages/ai-parrot/tests/knowledge/graphindex/test_builder_projection.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From projection module (created by TASK-1563):
from parrot.knowledge.graphindex.projection import (
    project_graph_sidecars,
    project_report_frontmatter,
    GraphProjectionReport,
)

# Existing builder imports:
from parrot.knowledge.graphindex.analytics import (
    compute_analytics,
    generate_report,
    AnalyticsResult,
    REPORT_FILENAME,
)

# Existing types:
from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, BuildResult, SourceConfig,
)

# For content store access:
from parrot.knowledge.pageindex.content_store import NodeContentStore  # line 123
# PageIndexToolkit has _content_store attribute (internal)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py
class GraphIndexBuilder:                            # line 54
    def __init__(                                   # line 94
        self,
        persistence: GraphIndexPersistence,
        embedder: GraphIndexEmbedder,
        output_dir: Path,
        ignore_file: Optional[Path] = None,
        resolution_config: Optional[ResolutionConfig] = None,
        pageindex_toolkit: Optional[PageIndexToolkit] = None,  # line 100
        signal_config: Optional[SignalRelevanceConfig] = None,
        detect_communities_enabled: bool = False,
        community_resolution: float = 1.0,
    ) -> None: ...

    # Stage 6 (analytics) at lines 221-231:
    # report_path: Optional[Path] = None
    # try:
    #     analytics = compute_analytics(assembler.graph, all_nodes, all_edges)
    #     analytics.communities = self.last_community_result
    #     report_path = generate_report(analytics, self.output_dir)
    # except Exception as exc:
    #     errors.append(f"Analytics failed: {exc}")
    #
    # Insert Stage 6.5 AFTER this block, BEFORE the return.

    async def build(self, sources: SourceConfig, ctx: TenantContext) -> BuildResult:  # line 122
    # Returns BuildResult at ~line 236

# packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py
def generate_report(                                # line 268
    analytics: AnalyticsResult,
    output_dir: Path,
    llm_polish: bool = False,
) -> Path:
    # Line 290: output_dir.mkdir(parents=True, exist_ok=True)
    # Line 293: content = _render_report(analytics)
    # Line 294: report_path.write_text(content, encoding="utf-8")
    # Line 297: return report_path

def _render_report(analytics: AnalyticsResult) -> str:  # line 300

# packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py
class BuildResult(BaseModel):                       # line 162
    tenant_id: str
    node_count: int = 0
    edge_count: int = 0
    inferred_edge_count: int = 0
    report_path: Optional[Path] = None
    errors: list[str] = Field(default_factory=list)
    # ADD: projection_report: Optional[GraphProjectionReport] = None

# packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py
# Lines 16-60: current exports. Add projection symbols.
```

### Does NOT Exist
- ~~`GraphIndexBuilder.project_sidecars()`~~ — no method; use standalone function
- ~~`BuildResult.projection_report`~~ — does not exist yet; this task adds it
- ~~`builder.py` Stage 6.5~~ — does not exist yet; this task adds it
- ~~`generate_report()` frontmatter parameter~~ — no such param; modify the function body

---

## Implementation Notes

### Pattern: Stage 6.5 insertion in build()
```python
# After Stage 6 (analytics), before the return:

# Stage 6.5: OKF Projection
projection_report = None
if self.output_dir:
    try:
        content_store = None
        if self.pageindex_toolkit:
            content_store = self.pageindex_toolkit._content_store
        projection_report = await project_graph_sidecars(
            all_nodes,
            all_edges,
            self.output_dir,
            content_store=content_store,
        )
        logger.info(
            "Stage 6.5 complete: %d nodes projected",
            projection_report.nodes_projected,
        )
    except Exception as exc:
        logger.error("Projection stage failed: %s", exc)
        errors.append(f"Projection failed: {exc}")
```

### Pattern: Frontmatter in generate_report()
```python
# In generate_report(), after _render_report():
content = _render_report(analytics)
# Prepend report frontmatter
fm = project_report_frontmatter(analytics, tenant_id="default")
content = fm + "\n" + content
report_path.write_text(content, encoding="utf-8")
```

Note: `generate_report()` does not currently receive a `tenant_id`. Either:
(a) add it as a parameter, or (b) use `"default"` as a reasonable fallback.
Option (a) is cleaner — add `tenant_id: str = "default"` parameter.

### Key Constraints
- Stage 6.5 must be in a try/except like Stage 6, so projection failures
  don't crash the entire build.
- Only run projection if `self.output_dir` is set (same guard as analytics).
- `_content_store` is an internal attribute of PageIndexToolkit — access
  it defensively with `getattr(self.pageindex_toolkit, '_content_store', None)`.
- The `build()` method is async but `generate_report()` is sync. The
  `project_graph_sidecars()` call must be awaited.

### References in Codebase
- `builder.py:221-231` — Stage 6 pattern to follow
- `analytics.py:268-297` — generate_report to modify
- `schema.py:162` — BuildResult to extend
- `graphindex/__init__.py:16-60` — exports to update

---

## Acceptance Criteria

- [ ] `GraphIndexBuilder.build()` calls `project_graph_sidecars()` when output_dir is set
- [ ] Build skips projection when output_dir is not configured
- [ ] Projection failure does not crash the build (error logged, appended to errors)
- [ ] `GRAPH_REPORT.md` starts with OKF YAML frontmatter (`---\ntype: Document\n...---\n`)
- [ ] `BuildResult` has optional `projection_report` field
- [ ] `graphindex/__init__.py` exports projection symbols
- [ ] `generate_report()` accepts optional `tenant_id` parameter
- [ ] All FEAT-238 tests still pass
- [ ] Integration tests pass: `pytest tests/knowledge/graphindex/test_builder_projection.py -v`

---

## Test Specification

```python
# tests/knowledge/graphindex/test_builder_projection.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, NodeKind, EdgeKind, BuildResult,
)
from parrot.knowledge.graphindex.analytics import (
    generate_report, AnalyticsResult,
)
from parrot.knowledge.okf.frontmatter import parse_frontmatter


class TestGenerateReportFrontmatter:
    def test_report_has_frontmatter(self, tmp_path):
        analytics = AnalyticsResult()
        path = generate_report(analytics, tmp_path)
        content = path.read_text()
        assert content.startswith("---\n")
        assert "type: Document" in content

    def test_report_frontmatter_parseable(self, tmp_path):
        analytics = AnalyticsResult()
        path = generate_report(analytics, tmp_path)
        content = path.read_text()
        # Extract frontmatter portion
        fm = parse_frontmatter(content)
        assert fm.title == "Knowledge Graph Report"


class TestBuildResultProjectionField:
    def test_projection_report_optional(self):
        result = BuildResult(tenant_id="test")
        assert result.projection_report is None

    def test_projection_report_populated(self):
        from parrot.knowledge.graphindex.projection import GraphProjectionReport
        report = GraphProjectionReport(output_dir="/tmp/test")
        result = BuildResult(
            tenant_id="test",
            projection_report=report,
        )
        assert result.projection_report.output_dir == "/tmp/test"


class TestBuildSkipsProjectionWithoutOutputDir:
    """Verify projection is only called when output_dir is set."""

    @pytest.mark.asyncio
    async def test_no_output_dir_no_projection(self):
        # This would be tested by mocking the builder or checking
        # that no nodes/ directory is created
        pass  # Integration test requires full builder setup
```

---

## Agent Instructions

When you pick up this task:

1. **Verify TASK-1563 is complete** — `graphindex/projection.py` must exist
2. **Read builder.py** carefully — understand the stage structure
3. **Insert Stage 6.5** after Stage 6, following the same try/except pattern
4. **Modify generate_report()** to prepend frontmatter
5. **Add projection_report to BuildResult** in schema.py
6. **Update __init__.py exports**
7. **Run full test suite**: `pytest tests/knowledge/ -v`
8. **Commit and update index**

---

## Completion Note

*(Agent fills this in when done)*
