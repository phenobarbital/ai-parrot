# TASK-1988: Unified Layer Integration — `semantic_knowledge` Retrieval

**Feature**: FEAT-390 — Dream Cycle — Episodic→Wiki Brain Consolidation
**Spec**: `sdd/specs/dream-cycle-brain-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1984
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 — the retrieval half of the feature: the brain retro-feeds
`ask()`. `UnifiedMemoryManager.get_context_for_query()` (FEAT-055) gains a
fourth parallel subsystem that searches the agent brain (and org wiki) via
`BrainStore.search()`, and `ContextAssembler` budgets it under `brain_weight`.
**Hard requirement: with `enable_brain=False` (default), behavior is
byte-identical to today — every pre-existing unified test must pass
unmodified.**

---

## Scope

- `parrot/memory/unified/models.py`:
  - `MemoryContext`: add `semantic_knowledge: str = Field(default="", ...)`;
    extend `to_prompt_string()` (models.py:43) with a section for it (render
    only when non-empty, same style as the existing sections).
  - `MemoryConfig` (models.py:78): add `enable_brain: bool = False` and
    `brain_weight: float = 0.20`. Extend the sum-to-one validator
    (models.py:145): when `enable_brain=False`, validate the existing three
    weights exactly as today; when `enable_brain=True`, validate
    episodic+skill+conversation+brain ≈ 1.0. When `enable_brain=True` and the
    caller did not override weights, default the four to
    `0.25 / 0.25 / 0.30 / 0.20` (episodic/skill/conversation/brain) — use a
    model_validator to rebalance only-when-untouched.
- `parrot/memory/unified/context.py`:
  - `ContextAssembler.assemble()` (context.py:49): accept a fourth optional
    parameter `semantic_knowledge: str = ""`; allocate its budget from
    `brain_weight` when `config.enable_brain`; keep 3-section behavior
    unchanged otherwise.
- `parrot/memory/unified/manager.py`:
  - `UnifiedMemoryManager.__init__` (manager.py:79): add
    `brain: Any | None = None, org_brain: Any | None = None` params
    (duck-typed `BrainStore`; TYPE_CHECKING import).
  - Add `async _get_brain_knowledge(self, query: str) -> str`: gather
    `brain.search(query)` and `org_brain.search(query)` (when set), join
    non-empty results with a separator; any exception → log WARNING, return
    `""` (never raise).
  - Wire into `get_context_for_query()` (manager.py:131) in the SAME parallel
    gather as the existing three retrievals; include in `_subsystems()`
    (manager.py:360) if that drives configure/cleanup.
- Extend tests: `tests/memory/dream/test_unified_brain.py` (new file — do
  NOT rewrite existing unified tests; they must pass untouched).

**NOT in scope**: mixin flags/scheduler wiring (TASK-1989), BrainStore
internals (TASK-1984), dream runner.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/unified/models.py` | MODIFY | `semantic_knowledge`, `enable_brain`, `brain_weight`, validator |
| `packages/ai-parrot/src/parrot/memory/unified/context.py` | MODIFY | Fourth section in `assemble()` |
| `packages/ai-parrot/src/parrot/memory/unified/manager.py` | MODIFY | `brain` params + `_get_brain_knowledge` + gather wiring |
| `tests/memory/dream/test_unified_brain.py` | CREATE | New tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.memory.unified import (  # eager exports, unified/__init__.py
    ContextAssembler, MemoryConfig, MemoryContext, UnifiedMemoryManager,
)
from parrot.memory.dream import BrainStore   # TASK-1984 (TYPE_CHECKING in manager)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/unified/models.py
class MemoryContext(BaseModel):               # :12
    def to_prompt_string(self) -> str: ...    # :43
class MemoryConfig(BaseModel):                # :78
    enable_episodic: bool                     # :86
    enable_skills: bool                       # :90
    enable_conversation: bool                 # :94
    max_context_tokens: int                   # :100
    episodic_weight: float                    # :119
    skill_weight: float                       # :125
    conversation_weight: float                # :131
    def _weights_sum_to_one(self) -> MemoryConfig:  # :145 (model_validator)
    # validator message currently lists the three weights — extend, don't break

# packages/ai-parrot/src/parrot/memory/unified/context.py
class ContextAssembler:                       # :17
    def __init__(self, config: MemoryConfig | None = None)  # :41
    def assemble(self, episodic_warnings, relevant_skills, conversation)  # :49
    def _fill_section(self, text, budget) -> tuple[str, int]  # :150
    def _fill_conversation(self, text, budget) -> tuple[str, int]  # :165

# packages/ai-parrot/src/parrot/memory/unified/manager.py
class UnifiedMemoryManager:                   # :49
    def __init__(self, namespace, conversation_memory=None, episodic_store=None,
                 skill_registry=None, config=None, cross_domain_router=None)  # :79
    async def get_context_for_query(...)      # :131 — READ the gather block
    async def _get_episodic_warnings(self, query) -> str   # :202 — degrade pattern
    def _subsystems(self) -> list[tuple[str, Any]]         # :360

# packages/ai-parrot/src/parrot/memory/dream/brain.py (TASK-1984)
class BrainStore:
    async def search(self, query, top_k=5, max_tokens=600) -> str  # "" on empty/error
```

### Does NOT Exist
- ~~`UnifiedMemoryManager.get_context()`~~ — the method is `get_context_for_query()`
- ~~`MemoryContext.brain_knowledge`~~ — the new field is named `semantic_knowledge`
- ~~a `BrainRetriever` class~~ — retrieval is a private manager method
  `_get_brain_knowledge()`, not a new public class
- ~~`ContextAssembler.assemble(**sections dict)`~~ — it takes positional/keyword
  string params; extend the signature, don't redesign it

---

## Implementation Notes

### Pattern to Follow
Copy the degrade-not-raise shape of `_get_episodic_warnings` (manager.py:202):
try/except → `logger.warning(...)` → return `""`. Wire the new coroutine into
the SAME `asyncio.gather` used by the existing three (read
`get_context_for_query` body first — match its structure exactly).

### Key Constraints
- **Zero breaking changes**: default `MemoryConfig()` must still validate;
  `assemble()` called with three args must behave identically;
  `UnifiedMemoryManager` constructed without `brain` must behave identically.
- Existing validator error message/behavior for 3-weight configs preserved.
- `semantic_knowledge` section renders only when non-empty (match
  `to_prompt_string()`'s existing conditional style — read models.py:43-77).
- Brain search failures must not delay the context beyond the gather (no
  retries in the retrieval path).

### References in Codebase
- `packages/ai-parrot/src/parrot/memory/unified/manager.py:131-230` — gather + degrade idioms
- Existing unified tests (locate with `pytest --collect-only -q | grep unified`
  or `wikitoolkit query "unified memory tests"`) — regression baseline

---

## Acceptance Criteria

- [ ] `MemoryConfig()` (defaults) validates and behaves exactly as before
- [ ] `enable_brain=True` default weights: 0.25/0.25/0.30/0.20, sum-to-one enforced
- [ ] `assemble()` with 4 sections budgets `semantic_knowledge` at `brain_weight`
- [ ] `get_context_for_query()` queries brain in parallel; result lands in
      `MemoryContext.semantic_knowledge` and `to_prompt_string()`
- [ ] Brain raising → empty section, WARNING, context still produced
- [ ] Org brain results merged when configured
- [ ] ALL pre-existing unified tests pass unmodified
- [ ] New tests pass: `pytest tests/memory/dream/test_unified_brain.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/unified/`

---

## Test Specification

```python
# tests/memory/dream/test_unified_brain.py
import pytest
from parrot.memory.unified import ContextAssembler, MemoryConfig, UnifiedMemoryManager


class TestMemoryConfigBrain:
    def test_legacy_three_weight_validation_intact(self): ...
    def test_enable_brain_rebalanced_defaults(self): ...
    def test_enable_brain_custom_weights_must_sum_to_one(self): ...


class TestAssemblerFourSections:
    def test_semantic_knowledge_budgeted(self): ...
    def test_three_section_call_unchanged(self): ...


class TestManagerBrainRetrieval:
    async def test_brain_queried_in_parallel(self, manager_with_stub_brain): ...
    async def test_brain_failure_degrades(self, manager_with_broken_brain): ...
    async def test_org_brain_merged(self, manager_with_two_brains): ...
    async def test_no_brain_configured_noop(self, manager_without_brain): ...
```

Stub brain: object with `async search(query, **kw) -> str`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1984 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — READ `get_context_for_query` and
   `to_prompt_string` bodies before editing; locate existing unified tests
   and run them FIRST as a baseline
4. **Update status** in `sdd/tasks/index/dream-cycle-brain-consolidation.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1988-unified-brain-retrieval.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-31
**Notes**: Ran the pre-existing `packages/ai-parrot/tests/memory/unified/`
suite FIRST as a baseline (86 passed) before touching any code, then
again after implementing (still 86/86, unmodified files). `MemoryContext`
gained `semantic_knowledge` + a `<brain_knowledge>` section in
`to_prompt_string()` (rendered only when non-empty, matching the existing
conditional style). `MemoryConfig` gained `enable_brain`/`brain_weight`;
the validator branches on `enable_brain`: False keeps the original
3-weight sum-to-one check byte-for-byte; True adds `brain_weight` to the
sum and — using `model_fields_set` to detect whether the caller touched
ANY of the four weight fields — rebalances untouched defaults to
0.25/0.25/0.30/0.20 before validating. `ContextAssembler.assemble()` gained
a 4th `semantic_knowledge` parameter (default `""`) budgeted from
`brain_weight` at priority 3 (between skills and conversation, so
conversation keeps its "gets whatever's left" role); empty-string calls
are mathematically identical to the pre-existing 3-arg formula since
`_fill_section("", budget)` always returns `("", 0)` regardless of the
computed budget. `UnifiedMemoryManager` gained `brain`/`org_brain`
constructor params (`Optional[BrainStore]`, `BrainStore` imported only
under `TYPE_CHECKING` to avoid a hard dependency on the dream package) and
a private `_get_brain_knowledge()` copying `_get_episodic_warnings`'s
degrade-not-raise shape exactly; wired into the same `asyncio.gather` as
the other three retrievals; both `brain`/`org_brain` added to
`_subsystems()` for symmetry (currently a no-op since `BrainStore` exposes
neither `configure()` nor `cleanup()`, but this future-proofs the wiring
per the task's conditional wording). 11 new tests in
`tests/memory/dream/test_unified_brain.py` cover legacy validation,
rebalanced defaults, custom-weight sum enforcement, 4-section budgeting,
3-arg-call byte-identical behavior, parallel brain query, brain failure
degradation, org-brain merge, no-brain no-op, and subsystem
presence/absence. `ruff check` clean on every line I touched (pre-existing
`Optional[X]` style in the rest of `manager.py`'s constructor signature —
which I matched for the two new params rather than diverging — is flagged
by a newer UP045 rule but is unrelated pre-existing debt across all 5
sibling parameters, left untouched per no-scope-creep).

**Deviations from spec**: none — all listed acceptance criteria verified:
default `MemoryConfig()` unchanged, `enable_brain=True` rebalances to
0.25/0.25/0.30/0.20, `assemble()` budgets the 4th section at
`brain_weight`, `get_context_for_query()` queries brain in the parallel
gather with results landing in `semantic_knowledge`/`to_prompt_string()`,
brain failures degrade to an empty section without raising, org-brain
results merge, and all 86 pre-existing unified tests pass unmodified.
