# TASK-1985: Episodic Backend `update_metadata` + `mark_consolidated`

**Feature**: FEAT-390 — Dream Cycle — Episodic→Wiki Brain Consolidation
**Spec**: `sdd/specs/dream-cycle-brain-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. After the dream cycle distills a group of episodes into a
wiki page, it must mark those episodes as consolidated
(`metadata["consolidated_into"] = <page_id>`) so they are never re-processed
and so humans can trace an episode to its distilled page. The episodic backend
protocol has no update capability today — this task adds it to the protocol
and to all three backends, plus a store-level passthrough.

---

## Scope

- Add `async update_metadata(self, episode_ids: list[str], patch: dict[str, Any]) -> int`
  to the `AbstractEpisodeBackend` Protocol (`backends/abstract.py`), with
  docstring: merge `patch` into each episode's `metadata` dict; return the
  number of episodes actually updated; unknown ids are ignored (not an error).
- Implement it in the three backends:
  - `PgVectorBackend` (`backends/pgvector.py`) — SQL JSONB **merge**
    (`metadata = COALESCE(metadata, '{}'::jsonb) || $patch::jsonb`), single
    UPDATE with `WHERE episode_id = ANY(...)`; never full-column overwrite.
  - `RedisVectorBackend` (`backends/redis_vector.py`) — read each episode's
    stored JSON, merge the metadata dict, rewrite the field.
  - `FAISSBackend` (`backends/faiss.py`) — in-memory dict merge; ensure the
    patch survives the backend's persistence round-trip (save/load).
- Add `async mark_consolidated(self, episode_ids: list[str], page_id: str) -> int`
  to `EpisodicMemoryStore` (`store.py`) — thin passthrough calling
  `update_metadata(episode_ids, {"consolidated_into": page_id})`, guarded
  with `hasattr(self.backend, "update_metadata")` → returns 0 with a WARNING
  when the backend lacks the method (watermark-only mode, spec §7).
- Unit tests for all three backends + the store passthrough.

**NOT in scope**: dream runner logic (TASK-1986), any read-path changes
(`get_recent` already supports `since` — do not touch it), wiki code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py` | MODIFY | Add `update_metadata` to the Protocol |
| `packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py` | MODIFY | JSONB merge implementation |
| `packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py` | MODIFY | JSON rewrite implementation |
| `packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py` | MODIFY | In-memory merge + persistence |
| `packages/ai-parrot/src/parrot/memory/episodic/store.py` | MODIFY | `mark_consolidated` passthrough |
| `tests/memory/dream/test_update_metadata.py` | CREATE | Unit tests (FAISS real; pg/redis mocked) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.memory.episodic.backends.abstract import AbstractEpisodeBackend
# verified: packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py:11
from parrot.memory.episodic.models import EpisodicMemory
# verified: packages/ai-parrot/src/parrot/memory/episodic/models.py:55
from parrot.memory.episodic.store import EpisodicMemoryStore
# verified: packages/ai-parrot/src/parrot/memory/episodic/store.py:57
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py
@runtime_checkable
class AbstractEpisodeBackend(Protocol):                    # :11
    async def store(self, episode: EpisodicMemory) -> str  # :18
    async def get_recent(self, namespace_filter, limit=10,
                         since: datetime | None = None)    # :51
    async def count(self, namespace_filter) -> int         # :95

# Concrete backends (plain classes satisfying the Protocol — NOT subclasses):
#   PgVectorBackend    backends/pgvector.py:66
#   RedisVectorBackend backends/redis_vector.py:145
#   FAISSBackend       backends/faiss.py:54
# READ each backend's storage layout (how episodes/metadata are persisted)
# before implementing — do not assume column/field names beyond what you read.

# packages/ai-parrot/src/parrot/memory/episodic/models.py
class EpisodicMemory(BaseModel):                           # :55
    episode_id: str        # :65
    metadata: dict[str, Any]  # :164 — "Extensible metadata"

# packages/ai-parrot/src/parrot/memory/episodic/store.py
class EpisodicMemoryStore:                                 # :57
    def __init__(self, backend, embedding_provider=None, ...)  # :86
    # store exposes the backend; verify the attribute name (self.backend vs
    # self._backend) by reading store.py:86-105 before writing mark_consolidated.
```

### Does NOT Exist
- ~~`AbstractEpisodicBackend`~~ — the Protocol is `AbstractEpisodeBackend` (no "ic")
- ~~`AbstractEpisodeBackend.update_metadata`~~ — this task CREATES it
- ~~`EpisodicMemoryStore.mark_consolidated`~~ — this task CREATES it
- ~~`backend.update(...)` / `backend.upsert(...)`~~ — no generic update method exists

---

## Implementation Notes

### Pattern to Follow
Read each backend's existing write method (`store()`) to learn its storage
layout, then implement the smallest possible update path in the same idiom
(same connection helpers, same key naming, same serialization).

### Key Constraints
- **PgVector**: JSONB merge with `||`, parameterized query — concurrent-writer
  safe; return the UPDATE row count.
- **Redis**: only rewrite the metadata portion of the stored record; keep
  vector/index fields untouched.
- **FAISS**: after merging, trigger whatever persistence the backend already
  does (read how it saves to `persistence_path`) so the patch survives reload.
- All three: unknown episode_ids are silently skipped; return count of real
  updates; never raise on empty `episode_ids` (return 0).
- `mark_consolidated`: WARNING (not error) when backend lacks the method.

### References in Codebase
- `packages/ai-parrot/src/parrot/memory/episodic/backends/*.py` — storage layouts
- Existing episodic tests under `tests/` for backend fixture patterns (FAISS
  offline, pg/redis mocked)

---

## Acceptance Criteria

- [ ] Protocol updated; `isinstance(backend, AbstractEpisodeBackend)` still
      passes for all three backends (runtime_checkable)
- [ ] FAISS: patch merges and survives persistence round-trip
- [ ] PgVector: generated SQL is a JSONB merge (assert in mock), returns count
- [ ] Redis: metadata JSON rewritten, other fields untouched
- [ ] `EpisodicMemoryStore.mark_consolidated` returns 0 + WARNING for a
      backend without `update_metadata`
- [ ] All tests pass: `pytest tests/memory/dream/test_update_metadata.py -v`
- [ ] Existing episodic tests still pass (no regression):
      `pytest tests/ -k episodic -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/episodic/`

---

## Test Specification

```python
# tests/memory/dream/test_update_metadata.py
import pytest
from parrot.memory.episodic.backends.faiss import FAISSBackend
from parrot.memory.episodic.models import EpisodicMemory
from parrot.memory.episodic.store import EpisodicMemoryStore


class TestFAISSUpdateMetadata:
    async def test_patch_merged(self, faiss_backend_with_episodes):
        backend, ids = faiss_backend_with_episodes
        n = await backend.update_metadata(ids[:2], {"consolidated_into": "mem-x"})
        assert n == 2

    async def test_unknown_ids_ignored(self, faiss_backend_with_episodes):
        backend, _ = faiss_backend_with_episodes
        assert await backend.update_metadata(["nope"], {"k": "v"}) == 0

    async def test_survives_persistence(self, tmp_path):
        """Patch, save, reload — metadata still patched."""


class TestStoreMarkConsolidated:
    async def test_passthrough(self, faiss_store):
        ...  # mark_consolidated → episodes carry consolidated_into

    async def test_backend_without_method(self):
        """Backend lacking update_metadata → returns 0, logs WARNING."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none (parallel with TASK-1984)
3. **Verify the Codebase Contract** — READ each backend's storage layout first
4. **Update status** in `sdd/tasks/index/dream-cycle-brain-consolidation.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1985-episodic-update-metadata.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-30
**Notes**: Added `update_metadata(episode_ids, patch) -> int` to
`AbstractEpisodeBackend` and implemented it in all three backends after
reading each one's storage layout first: PgVector uses a single
parameterized `UPDATE ... SET metadata = COALESCE(metadata, '{}'::jsonb)
|| $1::jsonb WHERE episode_id = ANY($2::uuid[])` (JSONB merge, never a
full-column overwrite); Redis reads+merges the `metadata` HASH field only
(vector/other fields untouched); FAISS merges the in-memory
`EpisodicMemory.metadata` dict and triggers `save()` when persistence is
configured. `EpisodicMemoryStore.mark_consolidated()` is a thin passthrough
guarded by `hasattr(self._backend, "update_metadata")`, returning 0 +
WARNING for backends lacking it (watermark-only mode). 12 new unit tests
pass (FAISS real incl. a save/reload persistence round-trip; PgVector/Redis
mocked; Protocol conformance; store passthrough + bare-backend fallback).
`ruff check` clean on every line I added (pre-existing lint debt elsewhere
in these files — BLE001/UP017/PYI034/etc. on code I did not touch — was
left as-is, out of scope). Regression-checked the real, pre-existing
episodic suite: `pytest packages/ai-parrot/tests/memory/episodic/ -v` →
72 passed, 0 failures.

**Deviations from spec**: (1) The AC's literal command
`pytest tests/ -k episodic -v` matches zero tests — the actual pre-existing
episodic backend/store tests live under `packages/ai-parrot/tests/memory/
episodic/` (this task's own per-spec convention places NEW dream-cycle
tests under the top-level `tests/memory/dream/`, matching TASK-1983/1984,
but the pre-existing episodic suite was never there). Ran the real
regression suite at its actual location instead (72/72 passed — see
Notes). (2) Discovered and worked around a pre-existing, unrelated
worktree environment gotcha while writing `test_update_metadata.py`: the
repo-root `conftest.py`'s Cython-extension stub for the uncompiled
`parrot.utils.types` (`SafeDict`) is injected partway through its own
execution; if an earlier line in that same `conftest.py` transitively
imports `parrot.memory.episodic.backends.faiss` first, that module's
`import faiss` fails against the not-yet-stubbed `parrot.utils`, and
`_FAISS_AVAILABLE=False` gets permanently cached in `sys.modules` for the
rest of the pytest session — breaking EVERY test that instantiates
`FAISSBackend`, independent of any code in this task (reproduced with
`git stash` on a clean checkout). Added a one-line, test-file-scoped
`sys.modules.pop("parrot.memory.episodic.backends.faiss", None)` at the
top of `test_update_metadata.py` (before the `FAISSBackend` import) to
force a fresh re-import once the stub is guaranteed present — this does
NOT touch `conftest.py` or any file outside this task's list. Flagging
for visibility: `packages/ai-parrot/tests/test_episodic_memory.py` (a
pre-existing file, untouched by this task) fails to even collect under
its own sub-rootdir (`packages/ai-parrot/pyproject.toml`) for the same
underlying reason — the fix-up root `conftest.py` isn't an ancestor of
that rootdir resolution, so `parrot.utils.types` is never stubbed there
at all. This is pre-existing worktree tooling debt, not a regression from
this task.
