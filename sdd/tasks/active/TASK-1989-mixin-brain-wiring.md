# TASK-1989: LongTermMemoryMixin Wiring, Exports, Integration Test & Docs

**Feature**: FEAT-390 — Dream Cycle — Episodic→Wiki Brain Consolidation
**Spec**: `sdd/specs/dream-cycle-brain-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1987, TASK-1988
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 — the last mile. A single opt-in surface
(`LongTermMemoryMixin`) turns the whole feature on: constructing the
`BrainStore`(s), `DreamCycleRunner`, and `DreamScheduler` at configure time,
handing the brain to `UnifiedMemoryManager`, and stopping the scheduler at
cleanup. Also: public exports, the end-to-end integration test, and docs.

---

## Scope

- `parrot/memory/unified/mixin.py` — new class attributes (same style as the
  existing flags at mixin.py:46-57):
  `enable_brain: bool = False`, `dream_interval_hours: float = 24.0`,
  `dream_importance_threshold: int = 5`, `brain_storage_dir: str | None = None`,
  `brain_promote_to_org: bool = False`, `org_promotion_cycles: int = 3`.
- Extend `_configure_long_term_memory()` (mixin.py:63): when
  `enable_long_term_memory and enable_brain`:
  1. Resolve storage dir: `brain_storage_dir` or default
     `~/.parrot/brains/<agent_id>` (expand + mkdir; spec §8 open question —
     this default is the decision, document it).
  2. Build `BrainStore(dir, wiki_name=f"brain-{agent_id}", asserted_by=f"agent:{agent_id}")`;
     when `brain_promote_to_org`: org store at `<dir>/../org-<org_id>` with
     `wiki_name=f"org-{org_id}"` (org_id from the namespace).
  3. Build `DreamConfig(importance_threshold=..., org_promotion_cycles=...)`
     from the flags; `DreamCycleRunner(episodic_store, brain, namespace,
     llm_client=<reflection/agent LLM if available else None>, org_brain=...)`.
  4. Pass `brain`/`org_brain` into the `UnifiedMemoryManager` constructor
     (extended in TASK-1988) and set `config.enable_brain=True`.
  5. `DreamScheduler(runner, state_path=<dir>/dream_state.json,
     interval_hours=dream_interval_hours)` → `await scheduler.start()`.
  6. Store as `self._dream_scheduler`; all failures degrade (WARNING, agent
     continues without brain — same as the existing mixin error handling).
- Add scheduler shutdown: extend the mixin's existing cleanup path (read
  mixin.py fully; if no cleanup hook exists, add `async def
  _cleanup_long_term_memory()` and call `scheduler.stop()` there) — verify
  how `UnifiedMemoryManager.cleanup()` (manager.py:116) is invoked today and
  mirror that.
- Exports: `parrot/memory/dream/__init__.py` final public API
  (`BrainStore, DreamConfig, DreamCycleReport, DreamCycleRunner,
  DreamScheduler, DreamState, DistilledKnowledge, load_state, save_state`);
  add `dream` re-exports to `parrot/memory/__init__.py` ONLY if that file
  already re-exports `unified`/`episodic` symbols (read it first — follow its
  existing convention, do not invent one).
- Integration tests `tests/memory/dream/test_integration.py`:
  - `test_dream_end_to_end` — FAISS episodic + tmpdir brain: record episodes
    → `run_now()` → page in brain wiki → `get_context_for_query()` on a
    similar query returns distilled knowledge in `semantic_knowledge`.
  - `test_dream_crash_recovery` — simulate crash mid-cycle (state saved with
    `running=True` after archive) → rerun → no duplicate pages, marks converge.
  - `test_mixin_brain_disabled_noop` / `test_mixin_brain_lifecycle`.
  - Interop check: open the brain `wiki.db` with `SQLiteWikiStore` directly
    and find the page (spec acceptance criterion).
- Docs: create `docs/dream-cycle.md` (what it is, flags, lifecycle, catch-up,
  promotion; link `docs/llm-wiki.md`); add a "Read next" link in
  `docs/llm-wiki.md`.

**NOT in scope**: changes to `AbstractBot`/`parrot/bots/` (explicit spec
non-goal), CLI entry point, working-memory integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/unified/mixin.py` | MODIFY | Brain flags + build/start/stop wiring |
| `packages/ai-parrot/src/parrot/memory/dream/__init__.py` | MODIFY | Final exports |
| `packages/ai-parrot/src/parrot/memory/__init__.py` | MODIFY (maybe) | Re-exports only if conventional — read first |
| `tests/memory/dream/test_integration.py` | CREATE | End-to-end + lifecycle tests |
| `docs/dream-cycle.md` | CREATE | Feature doc |
| `docs/llm-wiki.md` | MODIFY | Cross-link |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.memory.unified.mixin import LongTermMemoryMixin
# verified: packages/ai-parrot/src/parrot/memory/unified/mixin.py:21
from parrot.memory.dream import (
    BrainStore, DreamConfig, DreamCycleRunner, DreamScheduler,
)  # TASK-1983/1984/1986/1987
from parrot.knowledge.wiki import SQLiteWikiStore  # interop test; store.py:420
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/unified/mixin.py
class LongTermMemoryMixin:                            # :21
    enable_long_term_memory: bool = False             # :46 (flag block :46-57)
    _memory_manager: Optional[UnifiedMemoryManager]   # runtime state
    async def _configure_long_term_memory(self) -> None   # :63
        # builds MemoryConfig(max_context_tokens=..., episodic_max_warnings=...,
        # skill_max_context=..., skill_auto_extract=...) — read :63-118 fully
    async def get_memory_context(...)                 # :119
    async def _post_response_memory_hook(...)         # :154

# packages/ai-parrot/src/parrot/memory/unified/manager.py
class UnifiedMemoryManager:
    def __init__(..., brain=None, org_brain=None)     # extended by TASK-1988
    async def cleanup(self) -> None                   # :116

# packages/ai-parrot/src/parrot/memory/episodic/models.py:214
class MemoryNamespace(BaseModel):  # org_id + agent_id available for wiki names
```

### Does NOT Exist
- ~~hooks in `parrot/bots/` for the dream cycle~~ — mixin-only wiring
- ~~`LongTermMemoryMixin.cleanup()`~~ — verify the actual cleanup path by
  reading mixin.py + how agents call `UnifiedMemoryManager.cleanup()`; do not
  assume a method name without reading
- ~~`self.llm` guaranteed on the mixin~~ — the mixin is bot-agnostic; obtain a
  distill LLM client defensively (`getattr(self, "_llm", None)` or the
  reflection engine's client if the episodic store exposes one — READ what is
  actually available; `llm_client=None` heuristic fallback is acceptable v1)

---

## Implementation Notes

### Pattern to Follow
Mirror the existing `_configure_long_term_memory` structure exactly
(mixin.py:63-118): flag guard → try/except → build config → WARNING +
continue on failure. The brain block is additive inside the same method.

### Key Constraints
- MRO-safe: the mixin stays framework-agnostic — no imports from
  `parrot.bots`.
- `enable_brain=False` → literally zero new objects constructed.
- All new construction failures degrade (agent boots without brain).
- Integration tests run offline: no API keys (heuristic distill path), FAISS
  + SQLite in tmpdir.
- Docs follow the tone/structure of `docs/llm-wiki.md`.

### References in Codebase
- `packages/ai-parrot/src/parrot/memory/unified/mixin.py` — the file being extended
- `docs/llm-wiki.md` — doc style + "Read next" section to cross-link

---

## Acceptance Criteria

- [ ] `enable_brain=False` (default): no scheduler/brain constructed; full
      existing `pytest tests/ -k "unified or episodic"` suite passes unmodified
- [ ] `enable_brain=True`: configure builds brain(+org) store, runner,
      scheduler; scheduler started; cleanup stops it
- [ ] `test_dream_end_to_end` passes offline (record → run_now → page →
      `get_context_for_query` returns it in `semantic_knowledge`)
- [ ] `test_dream_crash_recovery` passes (idempotent convergence)
- [ ] Brain `wiki.db` opens with `SQLiteWikiStore` and the page is found (interop)
- [ ] `docs/dream-cycle.md` created; `docs/llm-wiki.md` cross-linked
- [ ] All tests pass: `pytest tests/memory/dream/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/`

---

## Test Specification

```python
# tests/memory/dream/test_integration.py
import pytest
from parrot.knowledge.wiki import SQLiteWikiStore
from parrot.memory.dream import BrainStore, DreamCycleRunner, DreamScheduler


class TestEndToEnd:
    async def test_dream_end_to_end(self, faiss_store, tmp_path):
        """episodes → run_now() → brain page → semantic_knowledge in context."""

    async def test_dream_crash_recovery(self, faiss_store, tmp_path):
        """stale running lock + rerun → no duplicate pages, marks converge."""

    async def test_brain_db_interop(self, tmp_path):
        """wiki.db written by BrainStore opens with SQLiteWikiStore."""


class TestMixinLifecycle:
    async def test_brain_disabled_noop(self): ...
    async def test_brain_lifecycle_start_stop(self, tmp_path): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1987 and TASK-1988 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — READ mixin.py:63-190 and
   `parrot/memory/__init__.py` before editing
4. **Update status** in `sdd/tasks/index/dream-cycle-brain-consolidation.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1989-mixin-brain-wiring.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
