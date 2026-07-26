# TASK-1914: DevLoopGraphMemory facade — opt-in GraphIndex access for dev_loop

**Feature**: FEAT-377 — Graph Engineering Hardening
**Spec**: `sdd/specs/graphindex-as-engineering-devloop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1909
**Assigned-to**: unassigned

---

## Context

Module 4 core (spec §3, G2). dev_loop and GraphIndex have zero coupling
today. This task builds the single integration surface — a facade module —
so node changes (TASK-1915) stay thin. **Decided (spec §8)**: write-back
targets the SQLite plane only in v1; no dual publish to Arango.

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/dev_loop/graph_memory.py`:
  ```python
  class DevLoopGraphMemory:
      @classmethod
      async def from_config(cls, ...) -> Optional["DevLoopGraphMemory"]:
          """None unless DEV_LOOP_GRAPH_MEMORY_PATH is configured."""
      async def build_research_context(self, brief: WorkBrief) -> Optional[str]: ...
      async def publish_run_outcome(self, run_id: str, report: QAReport | None,
                                    outcome: str, summary: str) -> Optional[CommitReceipt]: ...
      async def ground_findings(self, findings: list[str]) -> list[str]: ...
  ```
- `from_config`: reads `DEV_LOOP_GRAPH_MEMORY_PATH` (new key, unset →
  `None`); builds `SQLitePersistence` + `GraphPublisher` +
  `GraphExpandedRetriever` + `GraphContextBuilder` + `GroundingEvaluator`
  the same way `build_graph_memory_toolkit` does internally (read
  `factory.py:203-236` and mirror its construction; do NOT depend on
  `parrot_tools` — the facade needs the components, not the agent toolkit).
- `build_research_context`: `GraphContextBuilder.build(task=<brief summary>)`
  → return `GraphContext.text` (or `None` when empty); budget via
  `ContextBuildConfig(max_tokens=...)`.
- `publish_run_outcome`: construct a `GraphUpdate` with one `RUN` node, one
  `CLAIM` node per verified criterion (from `report.criterion_results` where
  `passed`), edges `PRODUCED` (run→claims), `ABOUT` (run→brief entities),
  `SUPPORTED_BY` (claim→evidence where available); `agent_id="dev-loop"`,
  `run_id=run_id`, `asserted_by=<node id>`. Call `GraphPublisher.publish()`.
  ALL exceptions caught → `logger.warning`, return `None` (degrade-never-fail).
- `ground_findings`: for each finding string, `ground_claim(...)`; keep
  findings whose `decision == "grounded"`, return the kept list (callers
  demote the rest — TASK-1915).
- Unit tests with `tmp_path` SQLite store, including the disabled-noop path.

**NOT in scope**: node wiring (TASK-1915); Arango publish; prompt changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/graph_memory.py` | CREATE | the facade |
| `packages/ai-parrot/tests/flows/dev_loop/test_graph_memory.py` | CREATE | facade unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# ALL from the graphindex package (PEP 562 lazy exports, __init__.py:63-133):
from parrot.knowledge.graphindex import (
    GraphPublisher,              # publish.py:37
    GraphUpdate, CommitReceipt,  # schema.py:226, 262 — NOT in publish.py
    GraphContextBuilder, ContextBuildConfig, GraphContext,  # context_builder.py:93,45,70
    GroundingEvaluator, GroundingResult,  # grounding.py:96,53
    NodeKind, EdgeKind, AssertionMeta, UniversalNode, UniversalEdge,
    SQLitePersistence, stable_edge_id,
)
# WRONG: from parrot.knowledge import GraphPublisher  ← knowledge/__init__.py re-exports NOTHING
```

### Existing Signatures to Use
```python
# publish.py:47,90,140
class GraphPublisher:
    def __init__(self, persistence: Any, ctx: TenantContext) -> None: ...
    async def publish(self, update: GraphUpdate) -> CommitReceipt: ...
    async def revert_commit(self, commit_id: str) -> dict[str, Any]: ...

# schema.py:250-259 — GraphUpdate fields:
#   nodes: list[UniversalNode]; edges: list[UniversalEdge]
#   removed_edges: list[tuple[str,str,str]]; removed_nodes: list[str]
#   agent_id: str (REQUIRED); run_id: Optional[str]; asserted_by: str (REQUIRED)
#   source: Optional[str]; reason: Optional[str]; op: str = "publish"

# context_builder.py:104-108, 251-255
class GraphContextBuilder:
    def __init__(self, retriever: GraphExpandedRetriever,
                 entity_resolver: Optional[object] = None) -> None: ...
    async def build(self, task: str,
                    config: Optional[ContextBuildConfig] = None) -> GraphContext: ...
# GraphContext.text / .truncated / .cited_edge_ids  (line 70)

# grounding.py:108-113, 204
class GroundingEvaluator:
    def __init__(self, retriever: GraphExpandedRetriever,
                 client: Optional[Any] = None, max_hops: int = 2) -> None: ...
    async def ground_claim(self, claim: str) -> GroundingResult: ...
# GroundingResult.decision: Literal["grounded", "revise"]  (line 74)

# factory.py:203-236 — construction recipe to MIRROR (not import the toolkit):
async def build_graph_memory_toolkit(db_dir, tenant_id="default", agent_id="agent",
    run_id=None, embedder=None, client=None, dimension=DEFAULT_DIMENSION) -> "GraphIndexToolkit":
# also available: make_stub_tenant_context(tenant_id) (factory.py:45),
#                 HashingGraphEmbedder(dimension) (factory.py:118)

# dev_loop models:
# QAReport (models.py:487-511), CriterionResult (475), WorkBrief (138)
```

### Does NOT Exist
- ~~`GraphPublisher.commit()`~~ — the method is `publish(update)`
- ~~`from parrot.knowledge import <anything>`~~ — package `__init__` is docstring-only
- ~~`DEV_LOOP_GRAPH_MEMORY_PATH`~~ — this task declares it (unset → facade disabled)
- ~~`parrot/flows/dev_loop/graph_memory.py`~~ — this task creates it; nothing imports graphindex from dev_loop today
- ~~`GraphExpandedRetriever` import path~~ — *(unverified — it is referenced by constructor signatures but was not in the harvested `__all__` list; check `graphindex/retriever.py` and the package exports before importing; use whatever `factory.py` uses)*

---

## Implementation Notes

### Key Constraints
- IMPORT CYCLE HAZARD: `agent_pool.py`'s note warns that importing the
  `parrot.flows.dev_loop` package mid-init raises; if `graph_memory.py` is
  imported by nodes, import graphindex lazily INSIDE methods or at module
  level from the graphindex package only (never back into dev_loop's own
  package `__init__`).
- Degrade-never-fail: `publish_run_outcome` and `ground_findings` must never
  raise into the caller — warning + `None`/passthrough respectively.
- `TenantContext`: use `make_stub_tenant_context("default")` unless config
  provides a tenant (follow `factory.py`).
- Async throughout; Pydantic for any new config model; `self.logger`.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py` — the construction recipe
- `packages/ai-parrot/src/parrot/knowledge/graphindex/mixin.py` — `GraphMemoryMixin` shows the same components composed for bots (context injection pattern at `_build_graph_context`, line 158)

---

## Acceptance Criteria

- [ ] `DEV_LOOP_GRAPH_MEMORY_PATH` unset → `from_config` returns `None`
- [ ] `publish_run_outcome` writes a revertable commit (verify via `revert_commit` round-trip on tmp SQLite)
- [ ] RUN + CLAIM nodes and PRODUCED/ABOUT edges present in the persisted update
- [ ] Publish failure (e.g. closed store) → warning, returns `None`, no raise
- [ ] `ground_findings` keeps "grounded", drops "revise"
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_graph_memory.py -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/` clean

---

## Test Specification

```python
@pytest.fixture
def tmp_graph_memory(tmp_path):
    """SQLitePersistence-backed DevLoopGraphMemory at tmp_path/'graph.db'."""

async def test_from_config_disabled_returns_none(monkeypatch): ...
async def test_publish_run_outcome_commit_and_revert(tmp_graph_memory): ...
async def test_publish_failure_degrades_to_warning(tmp_graph_memory, caplog): ...
async def test_ground_findings_filters_revise(tmp_graph_memory): ...
```

---

## Agent Instructions

1. **Read the spec** for full context
2. **Check dependencies** — TASK-1909 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code (especially the *(unverified)* retriever import)
4. **Update status** in `sdd/tasks/index/graphindex-as-engineering-devloop.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
