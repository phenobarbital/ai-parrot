# TASK-4714: CapabilityRegistry — ResourceType.AGENT and the synchronous exact-match index (M3a)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the FEAT-070 half of spec §3 **Module 3** (resolved U3: *extend `parrot.registry.capabilities`* — add
`ResourceType.AGENT`, an exact cap-id/keyword index and locality/cost data; embedding search stays the fallback).
Gate L-S3 needs a < 5 ms deterministic lookup, which the embedding `search()` cannot give, so `find_exact` is a
synchronous dict-backed index maintained incrementally. Touches only FEAT-070 files; no Roost import.

---

## Scope

- Add `AGENT = "agent"` to `ResourceType` after `VECTOR_COLLECTION`.
- Add `_exact_index: dict[str, set[str]]` + `_by_name: dict[str, CapabilityEntry]` to `CapabilityRegistry.__init__`.
- Add `register_agent_capability()`, `unregister_agent()`, `find_exact()` before `search()`.
- Write `tests/registry/test_capability_agent_index.py` (includes a 1 000-entry < 5 ms timing check).

**NOT in scope**: `AgentRegistry` changes (TASK-4716); changing `search()`/`build_index()` behaviour (AC-10); the navigator-auth PBAC `ResourceType` (different enum)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/capabilities/models.py` | MODIFY | Add `ResourceType.AGENT` |
| `packages/ai-parrot/src/parrot/registry/capabilities/registry.py` | MODIFY | Exact index + three methods |
| `packages/ai-parrot/tests/registry/test_capability_agent_index.py` | CREATE | Unit + timing tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
from parrot.registry.capabilities.models import CapabilityEntry, ResourceType  # verified: capabilities/models.py:25,48
from parrot.registry.capabilities.registry import CapabilityRegistry          # verified: capabilities/registry.py:19
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/registry/capabilities/models.py
class ResourceType(str, Enum):                      # line 25
    DATASET = "dataset"; TOOL = "tool"; GRAPH_NODE = "graph_node"; PAGEINDEX = "pageindex"
    VECTOR_COLLECTION = "vector_collection"         # line 32 — anchor
class CapabilityEntry(BaseModel):                   # line 48 — name, description, resource_type, embedding, metadata, not_for
# packages/ai-parrot/src/parrot/registry/capabilities/registry.py  (imports: Any, Callable, Optional at line 12)
class CapabilityRegistry:                           # line 19
    def __init__(self, not_for_penalty: float = 0.5) -> None:   # line 36; last line 42: self._not_for_penalty = ...
    def register(self, entry: CapabilityEntry) -> None:         # line 46 — appends to self._entries, marks dirty
    async def search(self, query: str, top_k: int = 5, resource_types: Optional[list[ResourceType]] = None) -> list[RouterCandidate]:  # line 183
```

### Does NOT Exist
- ~~`ResourceType.AGENT` in `parrot.registry.capabilities.models` — absent today (models.py:28-32). The `ResourceType.AGENT` hits in `auth/agent_guard.py:234`, `bots/abstract.py:4423` and server handlers are `navigator_auth.abac.policies.resources.ResourceType` — never import that one here~~
- ~~`CapabilityRegistry.find_exact` / `register_agent_capability` / `unregister_agent` — created here~~
- ~~`CapabilityRegistry.unregister` — does not exist; do not add a general one~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/registry/capabilities/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/registry/capabilities/registry.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/registry/test_capability_agent_index.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/registry/capabilities/models.py#ResourceType",
    "sym:packages/ai-parrot/src/parrot/registry/capabilities/models.py#CapabilityEntry",
    "sym:packages/ai-parrot/src/parrot/registry/capabilities/registry.py#CapabilityRegistry",
    "sym:packages/ai-parrot/src/parrot/registry/capabilities/registry.py#CapabilityRegistry.search"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Entry name is `f"{agent_name}::{cap_id}"`; `metadata` carries `agent_name, cap_id, category, keywords, locality, cost, backing, kind` — TASK-4716 reads these keys.
- Index keys are lower-cased: the cap_id, its category, each keyword, and each dotted prefix of the cap_id (`hr`, `hr.people`) so `hr.people.*` globs resolve by prefix without scanning.
- `register_agent_capability` must also go through `self.register(entry)` so `search()` sees AGENT entries after an index rebuild (embedding fallback).
- `find_exact` is synchronous, does no I/O and never calls `self._embedding_fn` (AC-9).
- `unregister_agent` removes from `_entries`, both indexes, and sets `_index_dirty = True`.
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- `packages/ai-parrot/src/parrot/registry/capabilities/registry.py:46` — `register()` pattern

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Add the enum member — *why*: AGENT entries need a type distinct from TOOL.
2. Add the two index attributes at the end of `__init__`.
3. Add the three methods directly above `async def search(` — *why*: groups the sync lookup beside the async one.
4. Write tests including the timing check.

### `packages/ai-parrot/src/parrot/registry/capabilities/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    VECTOR_COLLECTION = "vector_collection"' capabilities/models.py)
# AFTER — insert below `    VECTOR_COLLECTION = "vector_collection"` (verified: capabilities/models.py:32)
    AGENT = "agent"  # FEAT-747: a registered agent's advertised capability (Roost directory)
```
**Why**: Additive enum member; existing values untouched (AC-10).

### `packages/ai-parrot/src/parrot/registry/capabilities/registry.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        self._not_for_penalty: float = not_for_penalty' capabilities/registry.py)
# AFTER — insert below `        self._not_for_penalty: float = not_for_penalty` (verified: capabilities/registry.py:42)
        # FEAT-747: synchronous exact-match index for AGENT entries (key → entry names)
        self._exact_index: dict[str, set[str]] = {}
        self._by_name: dict[str, CapabilityEntry] = {}

# occurrences: 1 (verified: grep -c '    async def search(' capabilities/registry.py)
# BEFORE — insert above `    async def search(` (verified: capabilities/registry.py:183)
    def register_agent_capability(self, agent_name: str, cap_id: str, *, keywords: Sequence[str] = (),
                                  category: Optional[str] = None, locality: int = 3, cost: float = 1.0,
                                  backing: str = "llm_backed", kind: str = "local",
                                  metadata: Optional[dict[str, Any]] = None) -> None:
        """Register one AGENT entry (``name=f"{agent_name}::{cap_id}"``) and index it exactly."""
        # FILL IN: build CapabilityEntry(resource_type=ResourceType.AGENT, description=cap_id + keywords),
        #          self.register(entry), then index keys per Key Constraints (replace an existing same-name entry)
        raise NotImplementedError

    def unregister_agent(self, agent_name: str) -> int:
        """Drop every AGENT entry of *agent_name*; return the count removed."""
        raise NotImplementedError  # FILL IN

    def find_exact(self, query: str, *, resource_types: Optional[list[ResourceType]] = None,
                   limit: int = 10) -> list[CapabilityEntry]:
        """Embedding-free lookup: exact cap_id, glob (``hr.people.*``), category or keyword (case-insensitive)."""
        # FILL IN: glob ⇒ strip trailing ".*" and look up the prefix key, then fnmatch-filter cap_ids; stable order
        raise NotImplementedError
```
**Why**: Also add `Sequence` to the `from typing import ...` line (line 12) and `import fnmatch` — the only new imports.

### FILL IN checklist
- [ ] `register_agent_capability` body — bounded by Key Constraints (metadata keys are a TASK-4716 contract)
- [ ] `unregister_agent`, `find_exact` — bounded by AC-9 / AC-10
- [ ] tests — exact, glob, keyword, unregister, search() unchanged, 1 000 entries < 5 ms

---

## Acceptance Criteria

- [ ] `ResourceType.AGENT == 'agent'`; the five existing members are unchanged
- [ ] `find_exact('hr.people.salary')`, `find_exact('hr.people.*')` and `find_exact('salary')` return the entry
- [ ] `find_exact` never touches the embedding function and answers in < 5 ms over 1 000 entries
- [ ] Existing tests `tests/registry/test_capability_registry.py` and `test_capability_models.py` stay green
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/registry/capabilities/models.py packages/ai-parrot/src/parrot/registry/capabilities/registry.py packages/ai-parrot/tests/registry/test_capability_agent_index.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot/tests/registry/test_capability_agent_index.py -q`
- `pytest packages/ai-parrot/tests/registry/test_capability_registry.py -q`
- `pytest packages/ai-parrot/tests/registry/test_capability_models.py -q`

---

## Test Specification

```python
import time

from parrot.registry.capabilities.models import ResourceType
from parrot.registry.capabilities.registry import CapabilityRegistry


def test_agent_member():
    assert ResourceType.AGENT.value == "agent"


def test_find_exact_capid_glob_keyword():
    reg = CapabilityRegistry()
    reg.register_agent_capability("hr-agent", "hr.people.salary", keywords=["salary", "pay"], category="hr.people")
    for q in ("hr.people.salary", "hr.people.*", "SALARY", "hr.people"):
        assert [e.metadata["agent_name"] for e in reg.find_exact(q)] == ["hr-agent"]


def test_unregister_agent():
    reg = CapabilityRegistry()
    reg.register_agent_capability("a", "x.y")
    assert reg.unregister_agent("a") == 1 and reg.find_exact("x.y") == []


def test_lookup_under_5ms():
    reg = CapabilityRegistry()
    for i in range(1000):
        reg.register_agent_capability(f"a{i}", f"cat{i % 50}.cap{i}", keywords=[f"kw{i}"])
    reg.register_agent_capability("hr-agent", "hr.people.salary", keywords=["salary"])
    t0 = time.perf_counter(); reg.find_exact("salary"); assert (time.perf_counter() - t0) < 0.005
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug local-inter-agent --feature-id FEAT-747 --spec sdd/specs/local-inter-agent.spec.md --index sdd/tasks/index/local-inter-agent.json`)
2. **Read the spec** at `sdd/specs/local-inter-agent.spec.md` (§2 Data Models and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/local-inter-agent.json`
4. **Verify the Codebase Contract** — re-run `grep -c` on every MODIFY anchor before editing; a count that
   differs means the anchor moved, `0` means stop and report
5. **Update status** in the index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`, never rename
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4714 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (FEAT-747 execution 0b6f3a52)
**Date**: 2026-10-26
**Notes**: AGENT enum member, exact-match index, register_agent_capability/unregister_agent/find_exact + tests (6 passed; existing capability tests green). Same conftest-operand artefact in merge-tier run (123 passed on real targets).
Seat: gpt-5.6-sol then gpt-5.6-terra (codex) both returned empty_delivery; attempt 3 implemented by the orchestrator (sdd-worker).

**Deviations from spec**: Modified `packages/ai-parrot/tests/registry/test_capability_models.py` (not in the task's file list): its `test_has_five_members`/`test_values` pinned the enum at 5 members and necessarily break when ResourceType.AGENT is added; updated to 6/`agent`. The task's AC 'existing tests stay green' contradicts its own file list otherwise.
