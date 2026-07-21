---
type: Wiki Overview
title: 'TASK-1768: CrewExecutionDocument — deterministic LLM-free consolidated document'
id: doc:sdd-tasks-completed-task-1768-crew-execution-document-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements **Module 4** of FEAT-306 — the centrepiece deliverable: a dataclass
  that assembles'
relates_to:
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends
  rel: mentions
- concept: mod:parrot.bots.flows.core.types
  rel: mentions
- concept: mod:parrot.clients
  rel: mentions
---

# TASK-1768: CrewExecutionDocument — deterministic LLM-free consolidated document

**Feature**: FEAT-306 — Crew Per-Agent Result Persistence & Deterministic Execution Document
**Spec**: `sdd/specs/crew-per-agent-result-persistence.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1765, TASK-1766
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of FEAT-306 — the centrepiece deliverable: a dataclass that assembles
every agent's result + the final crew output + the synthesis summary into one consistent,
deterministic, LLM-free document, buildable from in-process state (`from_memory`) or from the
storage backend (`from_storage`, via TASK-1766's `fetch()`), renderable as dict or Markdown.

---

## Scope

- Create `packages/ai-parrot/src/parrot/bots/flows/core/storage/document.py` with the
  `CrewExecutionDocument` dataclass exactly as specified in spec §2 Data Models:
  fields `execution_id, crew_name, method, status, output, summary, agent_results,
  execution_order, errors, total_time, timestamp, user_id, session_id, metadata`.
- `to_dict()` — JSON-serialisable; MUST be a **superset** of `FlowResult.to_dict()` keys
  (`output, summary, status, total_time, nodes, agents, responses, errors, execution_log,
  metadata`) so the consolidated `crew_executions` write does not break existing consumers.
  Take `nodes`/`agents`/`responses`/`execution_log` from the `FlowResult` passed to
  `from_memory` (store them in `metadata` or dedicated fields as needed to reproduce them).
  Adds: `execution_id`, `agent_results`, `execution_order`, `crew_name`, `method`.
- `to_markdown()` — pure string templating (NO LLM, NO imports of clients):
  1. Title + metadata table (crew, method, execution_id, status, total time, timestamp).
  2. One `## Agent: <node_name>` section per entry in `agent_results`, in `execution_order`
     order: task, result (fenced block), execution time.
  3. `## Final Result` section (the `output`).
  4. `## Summary` section (the `summary`; render `_(no summary generated)_` when empty).
  5. `## Errors` section only when `errors` is non-empty.
  Deterministic: same instance → identical string on every call.
- `from_memory(cls, *, execution_id, crew_name, method, memory, result, user_id=None,
  session_id=None)` — assembles from `ExecutionMemory` + `FlowResult`:
  - `agent_results` = `[memory.results[nid].to_dict() for nid in memory.execution_order
    if nid in memory.results]` plus any results not in execution_order appended after
    (sorted by timestamp).
  - `output/summary/status/errors/total_time/metadata` from the `FlowResult`
    (`status` → `.value` when it is a `FlowStatus` enum).
- `async from_storage(cls, storage, execution_id, *, crew_collection="crew_executions",
  agent_collection="crew_agent_results")` — fetches the crew doc (may be absent → build from
  agent docs alone; return `None` only when BOTH fetches are empty). Primary source for
  agent results is the consolidated doc's embedded `agent_results`; per-agent docs fill gaps
  (match by `node_id`), ordered by the crew doc's `execution_order`, falling back to
  per-agent `timestamp` sort.
- Re-export `CrewExecutionDocument` from `core/storage/__init__.py` (extend `__all__`).
- Unit tests in `tests/bots/flows/core/storage/test_execution_document.py` (NEW).

**NOT in scope**: crew.py wiring / `build_execution_document()` accessor (TASK-1769),
persistence methods (TASK-1767), backend changes (TASK-1766), HTTP handlers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/document.py` | CREATE | `CrewExecutionDocument` dataclass |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/__init__.py` | MODIFY | Re-export + `__all__` entry |
| `tests/bots/flows/core/storage/test_execution_document.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact references. Verify anything not listed before using it.

### Verified Imports
```python
from parrot.bots.flows.core.storage.backends import ResultStorage   # backends/__init__.py
from parrot.bots.flows.core.result import NodeResult, FlowResult    # result.py:39, 273
from parrot.bots.flows.core.types import FlowStatus                 # imported by result.py:23 as `from .types import FlowStatus`
# inside document.py use relative imports, matching memory.py:14-15 style:
#   from ..result import FlowResult
#   from .backends import ResultStorage
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/storage/memory.py
@dataclass
class ExecutionMemory(VectorStoreMixin):                 # line 19
    original_query: Optional[str]
    results: Dict[str, NodeResult]                       # line 33 — keyed by node_id (loop mode: "agent#iterationN")
    execution_order: List[str]                           # line 35 — node_ids in run order
    def get_results_by_agent(self, agent_id) -> Optional[NodeResult]   # line 79

# packages/ai-parrot/src/parrot/bots/flows/core/result.py
@dataclass
class FlowResult:                                        # line 273
    output: Any; responses: Dict[str, Any]; summary: str  # summary may be ""
    nodes: List[NodeExecutionInfo]; execution_log: List[Dict[str, Any]]
    total_time: float; status: FlowStatus; errors: Dict[str, str]
    metadata: Dict[str, Any]                             # line 312
    def to_dict(self) -> Dict[str, Any]                  # line 454 — REFERENCE for the superset keys:
        # {"output", "summary", "status", "total_time", "nodes", "agents",
        #  "responses", "errors", "execution_log", "metadata"}   (lines 474-489)

# NodeResult.to_dict() — created by TASK-1765; verify present in result.py before starting.
# ResultStorage.fetch(collection, execution_id) -> list[dict] — created by TASK-1766;
#   verify present in backends/base.py before starting.

# packages/ai-parrot/src/parrot/bots/flows/core/storage/__init__.py — current __all__:
#   ["ExecutionMemory", "VectorStoreMixin", "PersistenceMixin", "SynthesisMixin", "synthesize_results"]
```

### Does NOT Exist
- ~~`CrewExecutionDocument`~~ / ~~`core/storage/document.py`~~ — THIS TASK creates them.
- ~~`ExecutionMemory.to_dict()`~~ — does not exist; `get_snapshot()` (memory.py:134) exists
  but STRINGIFIES results — do NOT use it; iterate `memory.results` + `NodeResult.to_dict()`.
- ~~`FlowResult.execution_id`~~ — no such field; the crew-level id lives in
  `FlowResult.metadata["execution_id"]` (stamped by TASK-1769).
- ~~Pydantic BaseModel for this document~~ — use a dataclass (consistency with result.py).
- ~~`datetime.now()` for `timestamp` default~~ — timestamp is a REQUIRED float field set by
  callers; no implicit clock in the dataclass (keeps construction deterministic/testable).
- ~~Any LLM/client import~~ — document.py must not import from `parrot.clients` at all.

---

## Implementation Notes

### Pattern to Follow
```python
# Dataclass + hand-built to_dict, same style as result.py FlowResult (lines 272-489).
# Markdown assembly: build a list[str] of sections, "\n\n".join(...) at the end.
def to_markdown(self) -> str:
    lines: list[str] = [f"# Crew Execution Report — {self.crew_name}", ...]
    for agent in self._ordered_agent_results():
        lines.append(f"## Agent: {agent.get('node_name', agent.get('node_id', '?'))}")
        ...
    return "\n\n".join(lines)
```

### Key Constraints
- ZERO LLM involvement — pure data transformation; determinism is an acceptance criterion.
- `to_dict()` output must survive `json.dumps(..., default=str)`.
- `from_storage` is `async` (awaits `storage.fetch`); `from_memory` is sync.
- Fenced result blocks in Markdown: guard against results containing triple backticks
  (use `~~~` fences or escape) — a result must not break the document structure.
- Google-style docstrings + strict type hints; `logging.getLogger(__name__)` if logging needed.

### References in Codebase
- `result.py:454-489` — `FlowResult.to_dict()` (superset baseline).
- `result.py:39-72` — NodeResult fields available in each `agent_results` entry.
- `tests/bots/flows/core/storage/test_persistence_mixin.py:11-25` — `_FakeStorage` pattern to
  copy for the `from_storage` tests (implement `fetch` on the fake).

---

## Acceptance Criteria

- [ ] `to_dict()` contains every key of `FlowResult.to_dict()` plus `execution_id`, `agent_results`, `execution_order`, `crew_name`, `method`
- [ ] `to_markdown()` returns identical strings on repeated calls; contains one section per agent in execution order, final result, and summary
- [ ] `from_memory()` orders `agent_results` by `execution_order` with timestamp fallback for stragglers
- [ ] `from_storage()` joins crew doc + agent docs by execution_id; works when the consolidated doc is missing (crash case); returns `None` when nothing found
- [ ] No import of any LLM client in document.py
- [ ] `from parrot.bots.flows.core.storage import CrewExecutionDocument` works
- [ ] All tests pass: `pytest tests/bots/flows/core/storage/test_execution_document.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/core/storage/document.py`

---

## Test Specification

```python
# tests/bots/flows/core/storage/test_execution_document.py
import json
import pytest
from parrot.bots.flows.core.result import FlowResult, NodeResult
from parrot.bots.flows.core.storage import CrewExecutionDocument, ExecutionMemory


def _memory_with(*node_ids):
    mem = ExecutionMemory(original_query="q")
    for nid in node_ids:
        mem.results[nid] = NodeResult(node_id=nid, node_name=nid.upper(), task=f"t-{nid}", result=f"r-{nid}")
        mem.execution_order.append(nid)
    return mem


class TestFromMemory:
    def test_ordering_follows_execution_order(self):
        doc = CrewExecutionDocument.from_memory(
            execution_id="E1", crew_name="c", method="run_sequential",
            memory=_memory_with("a", "b"), result=FlowResult(output="final", summary="s"),
        )
        assert [a["node_id"] for a in doc.agent_results] == ["a", "b"]

    def test_to_dict_superset_of_flowresult(self):
        fr = FlowResult(output="final", summary="s")
        doc = CrewExecutionDocument.from_memory(
            execution_id="E1", crew_name="c", method="run_sequential",
            memory=_memory_with("a"), result=fr)
        assert set(fr.to_dict()) <= set(doc.to_dict())
        json.dumps(doc.to_dict(), default=str)


class TestMarkdown:
    def test_deterministic(self):
        doc = ...  # as above
        assert doc.to_markdown() == doc.to_markdown()

    def test_sections_present(self):
        md = doc.to_markdown()
        assert "## Agent: A" in md and "## Final Result" in md and "## Summary" in md


class TestFromStorage:
    async def test_join_by_execution_id(self, fake_storage): ...
    async def test_missing_consolidated_doc_uses_agent_docs(self, fake_storage): ...
    async def test_returns_none_when_empty(self, fake_storage):
        assert await CrewExecutionDocument.from_storage(fake_storage, "nope") is None
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1765 and TASK-1766 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/crew-per-agent-result-persistence.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1768-crew-execution-document.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-14
**Notes**: Created `CrewExecutionDocument` dataclass in the new
`core/storage/document.py`, re-exported from `core/storage/__init__.py`.
`to_dict()` stores the `FlowResult`-only fields (`nodes`, `agents`,
`responses`, `execution_log`) under a private `metadata["_flow_extra"]`
key populated in `from_memory()`, and unpacks them back to top-level keys
in `to_dict()` so the output is a verified superset of
`FlowResult.to_dict()`. `to_markdown()` is pure string templating (backtick
collision guarded via a `~~~` fallback fence) and is byte-identical across
repeated calls on the same instance. `from_memory()` orders `agent_results`
by `memory.execution_order` with stragglers (results absent from
`execution_order`) appended after, sorted by `NodeResult.timestamp`.

`from_storage()` correctly unwraps the nesting that
`PersistenceMixin._save_result()` / `._save_agent_result()` apply (both
nest the passed object's `to_dict()` output under an outer `"result"` key
— verified by re-reading `persistence.py:92-101` from TASK-1767): the
consolidated `crew_executions` doc's own `to_dict()` shape is read from
`crew_raw["result"]` (falling back to the raw doc for storages that saved
flat), and per-agent `crew_agent_results` docs contribute their
`NodeResult.to_dict()` from `doc["result"]` to fill any `node_id` missing
from the consolidated doc's embedded `agent_results` — exactly the
crash-interrupted-run case from spec §7. Returns `None` only when both
`fetch()` calls come back empty; catches `NotImplementedError` from
backends that don't implement `fetch()` yet (treated as empty).

15 new tests in `tests/bots/flows/core/storage/test_execution_document.py`
covering ordering, straggler handling, dict superset, enum status
conversion, markdown determinism/sections/backtick-guard, and all 3
`from_storage` paths (join, agent-docs-only, gap-filling). All 15 pass;
full storage suite (67 tests, excluding the 3 pre-existing-broken files
already flagged in TASK-1766) still green; `ruff check` clean. No import
of `parrot.clients` or any LLM SDK (asserted by test).

**Deviations from spec**: none — the "nested under `result`" unwrapping
in `from_storage()` was not explicitly spelled out in this task's Scope
text but is required by the actual `_save_result`/`_save_agent_result`
document shapes (verified in TASK-1767); flagging here for visibility
since TASK-1769's wiring will produce documents in exactly this shape.
