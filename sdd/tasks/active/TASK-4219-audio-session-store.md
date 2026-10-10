# TASK-4219: AudioSessionStore (Redis snapshots with CAS revision, active-session claim) + PartialSaveStore.remove_keys

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4211
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 7** (resume, G9, AC16). Today `AudioSessionState` is
memory-only (`audio/models.py:179-210`) and the `PartialSaveStore` given to
`setup_form_api` never reaches the audio handler (`api/routes.py:202`, `:483-491`).
This task adds:

- `AudioSessionStore` — the audio engine's **private** snapshot under
  `parrot:audio:{form_uid}:{session_id}` with a compare-and-set `revision` (S5) and a
  one-active-session-per-user marker `parrot:audio:active:{user_id}`. It reuses the
  partial store's Redis client (`PartialSaveStore._get_redis()`, `:195`).
- `PartialSaveStore.remove_keys()` — so `cascade_clear` removes answers from the
  normal partial save that HTML `/partial` + `merge_partials` read (cross-channel
  completion). The snapshot itself is **never** exposed by `/partial` (owner decision).

---

## Scope

- Modify `services/partial_saves.py`: add `remove_keys(form_id, session_id, keys)`
  right after `delete()` — read, drop keys, re-write with refreshed TTL via
  `_redis_set`; returns the updated `PartialFormData` or `None` (no Redis / no entry).
- Create `audio/session_store.py`: `AUDIO_KEY_PREFIX`, `SnapshotConflict`,
  `ResumeUnavailable`, `AudioSnapshot`, `AudioSessionStore`
  (`__init__`, `save`, `load`, `delete`, `claim_active`).
- `save(..., expected_revision=None)`: CAS — when `expected_revision` is not None and the
  stored revision differs, raise `SnapshotConflict`; store with `revision = stored + 1`
  and TTL `ttl_seconds`; return the new revision. Without Redis: no-op, return
  `snapshot.revision`.
- `load`: `None` when absent; raise `ResumeUnavailable` when Redis is not configured.
- `claim_active(user_id, session_id)`: `SET key session_id NX EX ttl`; `True` when set or
  already held by the same `session_id`; `False` when another session holds it.
- `delete`: remove the snapshot and release the active marker if it points at this session.
- Write `test_audio_session_store.py` with a dict-backed fake Redis (`fakeredis` is NOT installed).

**NOT in scope**: resume *validation* (wrong user/tenant → `RESUME_FORBIDDEN`, changed form
→ `RESUME_STALE`, re-plan) — that is the engine's `from_snapshot` (TASK-4226); building the
snapshot from engine state (TASK-4226); wiring the store into the adapter (TASK-4227/4228).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py` | MODIFY | add `remove_keys()` after `delete()` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py` | CREATE | snapshot store |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_session_store.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.services.partial_saves import PartialSaveStore      # services/partial_saves.py:24
from parrot_formdesigner.core.partial import PartialFormData                  # core/partial.py:15 (imported by partial_saves.py:21)
```

#### Provided by dependency tasks (do not exist yet — land before this task)
```python
# TASK-4211 — audio/models.py (Phase lives in models.py per plan decision)
from parrot_formdesigner.audio.models import Phase
# TASK-4209 — core/voice.py / core/llm_validation.py
from parrot_formdesigner.core.voice import VoiceFormConfig
from parrot_formdesigner.core.llm_validation import PlausibilityReport
```

### Existing Signatures to Use
```python
# services/partial_saves.py
class PartialSaveStore:                                                       # :24
    REDIS_KEY_PREFIX = "parrot:partial:"                                      # :50
    def __init__(self, ttl_seconds: int = 3600, redis_url: str | None = None) -> None   # :52-55 ; self._ttl: timedelta ; self.logger
    async def get(self, form_id: str, session_id: str) -> PartialFormData | None        # :123
    async def delete(self, form_id: str, session_id: str) -> bool                       # :145-163
    async def close(self) -> None                                                       # :165
    async def _get_redis(self) -> Any | None                                            # :195 (None when no redis_url / redis missing)
    async def _redis_set(self, redis: Any, partial: PartialFormData) -> None            # :218 (setex with self._ttl)
# core/partial.py:15
class PartialFormData(BaseModel):
    form_id: str; session_id: str; data: dict[str, Any]; field_errors: dict[str, list[str]]; saved_at: AwareDatetime; expires_at: AwareDatetime
# Existing fake-Redis test pattern: packages/parrot-formdesigner/tests/test_partial_save_store.py:223-231 (fake_get / fake_setex on a mock)
```

### Does NOT Exist
- ~~`PartialSaveStore.remove_keys()`~~, ~~`audio/session_store.py`~~, ~~`AudioSessionStore`~~, ~~`AudioSnapshot`~~ — created here.
- ~~`fakeredis`~~ — not installed; use a dict-backed stub.
- ~~`PartialSaveStore.redis`~~ public attribute — use `await partial_store._get_redis()`.
- ~~Exposing the snapshot via `/partial`~~ — forbidden (AC16).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_session_store.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py#PartialSaveStore",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py#PartialSaveStore.get",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py#PartialSaveStore.delete",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py#PartialSaveStore._get_redis",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py#PartialSaveStore._redis_set",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/partial.py#PartialFormData"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Redis calls used: `get`, `setex`, `set(name, value, nx=True, ex=ttl)`, `delete`, and for CAS either a Lua `eval` or `WATCH`/`MULTI` pipeline — keep the fake stub honest about whichever you pick (document it in the test).
- All Redis errors are caught and logged (WARNING) like `PartialSaveStore` does; only `SnapshotConflict` and `ResumeUnavailable` propagate.
- Snapshot JSON via `model_dump_json()` / `model_validate_json()`; datetimes timezone-aware (UTC).
- Partial-store keys are **field_uid strings** (FEAT-393, `partial_saves.py:84-90`): `remove_keys` drops exactly the keys it is given; callers translate field_id → field_uid.

---

## Implementation Blueprint

### Steps (in order)
1. Add `remove_keys` to `PartialSaveStore` — *why*: `cascade_clear` must reach the HTML partial.
2. Create `session_store.py` — *why*: AC16 resume storage.
3. Write tests with a dict-backed fake Redis injected via `store._redis = fake` and `redis_url="redis://fake"`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    async def close(self) -> None:' services/partial_saves.py)
# BEFORE — insert above `    async def close(self) -> None:` (verified: services/partial_saves.py:165), i.e. right after delete() (:145-163)
    async def remove_keys(
        self,
        form_id: str,
        session_id: str,
        keys: Iterable[str],
    ) -> PartialFormData | None:
        """Drop answer keys (cascade_clear) and refresh the TTL like ``save()``.

        Args:
            form_id: Form identifier.
            session_id: Session identifier.
            keys: Answer keys (field_uid strings) to remove.

        Returns:
            The updated PartialFormData, or None when Redis is unavailable or no entry exists.
        """
        redis = await self._get_redis()
        if redis is None:
            return None
        existing = await self._redis_get(redis, form_id, session_id)
        if existing is None:
            return None
        drop = set(keys)
        now = datetime.now(tz=timezone.utc)
        updated = existing.model_copy(
            update={
                "data": {k: v for k, v in existing.data.items() if k not in drop},
                "saved_at": now,
                "expires_at": now + self._ttl,
            }
        )
        await self._redis_set(redis, updated)
        return updated

# AND — extend the typing import (verified: services/partial_saves.py:19 `from typing import Any`)
from typing import Any, Iterable
```
**Why**: mirrors `save()`'s TTL refresh (`:105-120`) and reuses the private helpers so the key format stays single-sourced. `delete()` is anchored by its own line too (`grep -cF '    async def delete(' → 1`, `:145`), but inserting before `close()` is the unambiguous attachment point.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py` (CREATE)
```python
"""Redis snapshot store for resumable audio form sessions (FEAT-649, Module 7)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from ..core.llm_validation import PlausibilityReport
from ..core.voice import VoiceFormConfig
from ..services.partial_saves import PartialSaveStore
from .models import Phase

AUDIO_KEY_PREFIX = "parrot:audio:"


class SnapshotConflict(Exception):
    """Stored revision differs from ``expected_revision`` (S5 compare-and-set)."""


class ResumeUnavailable(Exception):
    """Redis is not configured — resume cannot work (wire code RESUME_UNAVAILABLE)."""


class AudioSnapshot(BaseModel):
    """Private audio-engine snapshot; never exposed through /partial."""

    revision: int = 0
    form_version: str
    phase: Phase
    cursor: str | None = None
    history: list[str] = Field(default_factory=list)
    review_cursor: int = 0
    return_to_review: bool = False
    locale: str = "en"
    config: VoiceFormConfig | None = None
    blob_refs: dict[str, str] = Field(default_factory=dict)          # field_id → blob_ref
    answer_meta: dict[str, dict[str, Any]] = Field(default_factory=dict)   # field_id → {source, confidence, version, field_uid, ...}
    plausibility: PlausibilityReport | None = None                   # discarded on resume (re-run at review)
    flagged: dict[str, int] = Field(default_factory=dict)
    submission_id: str
    user_id: str
    tenant: str | None = None
    saved_at: datetime | None = None
    expires_at: datetime | None = None
```
**Why this shape**: field list is spec §3 M7 verbatim; scalar answer **values** are not in the snapshot — they live in the partial store so HTML can finish the form (AC16). `answer_meta` keeps per-answer evidence (source, confidence, version) needed to rebuild `AudioAnswer`s.

### `audio/session_store.py` (CREATE, continued — `AudioSessionStore`)
```python
class AudioSessionStore:
    """Snapshots under ``parrot:audio:{form_uid}:{session_id}`` reusing the partial store's Redis client."""

    def __init__(self, partial_store: PartialSaveStore, *, ttl_seconds: int) -> None:
        self.partial_store = partial_store
        self.ttl_seconds = ttl_seconds
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _key(form_uid: str, session_id: str) -> str:
        return f"{AUDIO_KEY_PREFIX}{form_uid}:{session_id}"

    @staticmethod
    def _active_key(user_id: str) -> str:
        return f"{AUDIO_KEY_PREFIX}active:{user_id}"

    async def save(self, form_uid: str, session_id: str, snapshot: AudioSnapshot, *, expected_revision: int | None = None) -> int:
        """Compare-and-set on ``revision``; returns the new revision; no-op without Redis."""
        redis = await self.partial_store._get_redis()
        if redis is None:
            return snapshot.revision
        now = datetime.now(tz=timezone.utc)
        # FILL IN: atomically read the stored revision (0 if absent), raise SnapshotConflict when expected_revision is not
        #   None and differs, write snapshot.model_copy(revision=stored+1, saved_at=now, expires_at=now+ttl).model_dump_json()
        #   with EX ttl_seconds; use Lua eval or WATCH/MULTI (document choice); Redis errors → log WARNING and return
        #   snapshot.revision — bounded by S5, AC16
        return snapshot.revision

    async def load(self, form_uid: str, session_id: str) -> AudioSnapshot | None:
        """Return the snapshot, None when absent; raises ResumeUnavailable without Redis."""
        redis = await self.partial_store._get_redis()
        if redis is None:
            raise ResumeUnavailable("audio session resume requires Redis")
        try:
            raw = await redis.get(self._key(form_uid, session_id))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("AudioSessionStore.load failed: %s", exc)
            return None
        return AudioSnapshot.model_validate_json(raw) if raw else None

    async def delete(self, form_uid: str, session_id: str) -> None:
        """Delete the snapshot and release the active marker held by this session."""
        # FILL IN: load (ignore ResumeUnavailable) to learn user_id; delete snapshot key; delete the active key only when its
        #   value equals session_id (bytes vs str!) — bounded by "one active session per user" (AC16)

    async def claim_active(self, user_id: str, session_id: str) -> bool:
        """SET NX ``parrot:audio:active:{user_id}``; False when another session is active."""
        redis = await self.partial_store._get_redis()
        if redis is None:
            return True   # no Redis → cannot enforce; resume is unavailable anyway
        key = self._active_key(user_id)
        if await redis.set(key, session_id, nx=True, ex=self.ttl_seconds):
            return True
        current = await redis.get(key)
        # FILL IN: decode bytes; same session_id → refresh EX and return True; else False — bounded by AC16
        return False
```
**Why this shape**: resume checks (user/tenant/form version) belong to the engine so this store stays a dumb, testable persistence layer; `timedelta` is imported for the `expires_at` computation in the FILL IN.

### FILL IN checklist
- [ ] `AudioSessionStore.save` — atomic CAS + TTL; S5
- [ ] `AudioSessionStore.delete` — snapshot + conditional marker release; AC16
- [ ] `AudioSessionStore.claim_active` — re-claim by same session; AC16
- [ ] Fake Redis stub honours `get/setex/set(nx, ex)/delete` and the CAS primitive chosen

---

## Acceptance Criteria

- [ ] Snapshot save → load → delete round-trips over a fake Redis; revision increments per save.
- [ ] `save(expected_revision=<stale>)` raises `SnapshotConflict`.
- [ ] `load` raises `ResumeUnavailable` when the partial store has no Redis; `save` is a no-op then.
- [ ] `claim_active` is NX: a second session for the same user gets `False`; the same session gets `True`; `delete` releases it.
- [ ] `PartialSaveStore.remove_keys` drops only the given keys, refreshes TTL, returns `None` without Redis; existing partial-save tests still pass.
- [ ] `ruff check` passes on touched files.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_session_store.py -q`
- `pytest packages/parrot-formdesigner/tests/test_partial_save_store.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_audio_session_store.py
import pytest

from parrot_formdesigner.audio.models import Phase
from parrot_formdesigner.audio.session_store import (AudioSessionStore, AudioSnapshot, ResumeUnavailable,
                                                     SnapshotConflict)
from parrot_formdesigner.services.partial_saves import PartialSaveStore


class FakeRedis:
    """Dict-backed stub (fakeredis is not installed)."""

    def __init__(self):
        self.kv = {}

    async def get(self, key):
        return self.kv.get(key)

    async def setex(self, key, ttl, value):
        self.kv[key] = value

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    async def delete(self, *keys):
        return sum(1 for k in keys if self.kv.pop(k, None) is not None)
    # FILL IN: the CAS primitive (eval / pipeline) mirroring production semantics


@pytest.fixture
def stores():
    partial = PartialSaveStore(redis_url="redis://fake")
    partial._redis = FakeRedis()
    return partial, AudioSessionStore(partial, ttl_seconds=60)


def _snap(**kw):
    return AudioSnapshot(form_version="1.0", phase=Phase.ASKING, submission_id="s1", user_id="u1", **kw)


async def test_session_store_roundtrip_and_claim(stores): ...     # FILL IN
async def test_snapshot_cas_conflict(stores): ...                # FILL IN
async def test_resume_unavailable_without_redis(): ...           # FILL IN: PartialSaveStore() with no url
async def test_partial_remove_keys(stores): ...                  # FILL IN
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`).
2. **Read the spec** (§3 Module 7, §5 AC16, §9 S5).
3. **Check dependencies** — TASK-4211 must be `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`.
4. **Verify the Codebase Contract** — re-run `grep -cF '    async def close(self) -> None:'` on `services/partial_saves.py` (expect 1).
5. **Update status** in the per-spec index → `"in-progress"` and commit only that file.
6. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature or path.
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only the files listed above.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4219 audio-form-interaction-workflow verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
