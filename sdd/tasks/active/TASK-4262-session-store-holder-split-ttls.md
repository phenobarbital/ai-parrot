# TASK-4262: AudioSessionStore — `ActiveHolder` marker, split resume/active TTLs, marker refresh

**Feature**: FEAT-655 — Audio form active-session resume hint and split TTLs
**Spec**: `sdd/specs/audio-form-active-session-resume.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (G2, G3, G4; AC2, AC3, AC4). The one-active-session marker
`parrot:audio:active:{user_id}` stores only a bare session id, and one `ttl_seconds` (3600)
drives both the resumable snapshot and the marker. This task:

- stores a JSON `ActiveHolder` (`session_id`, `form_uid`, `tenant`) in the marker, so TASK-4263
  can tell the client *which* session blocks it;
- splits the TTLs: snapshot = `snapshot.config.resume_ttl_seconds` (fallback: store
  `resume_ttl_seconds`), marker = `active_ttl_seconds` (default 600);
- refreshes the marker on every successful snapshot save, but only when it is held by the
  saving session.

A legacy bare-string marker (written by a pre-FEAT-655 process during a rolling deploy) must
still be read, re-claimed by its own session and released (AC2).

---

## Scope

- Add `ActiveHolder` and `_parse_holder`.
- Replace the constructor's `ttl_seconds` with `resume_ttl_seconds=3600, active_ttl_seconds=600`.
- Add `_resume_ttl(snapshot)`; use it in `save()` for `expires_at` and the Lua `EX`.
- Add `_refresh_active(redis, user_id, session_id)`; call it from `save()` after a successful CAS.
- `claim_active(user_id, session_id, *, form_uid, tenant)` writes the holder JSON with `active_ttl_seconds`.
- `_release` compares `_parse_holder(...).session_id`.
- Add `active_holder(user_id)`.
- Update the existing store tests to the new constructor/claim signatures and add the §4 M1 tests.

**NOT in scope**: `api/audio_ws.py`, `audio/events.py`, `api/routes.py` (TASK-4263 — `routes.py:495` will
fail to construct the store until TASK-4263 lands; that is expected, TASK-4263 depends on this task);
docs (TASK-4264).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py` | MODIFY | holder, TTLs, refresh, `active_holder` |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_session_store.py` | MODIFY | constructor/claim updates + new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported in session_store.py:5-14
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from pydantic import BaseModel, Field
from ..core.voice import VoiceFormConfig
from ..services.partial_saves import PartialSaveStore
# tests
from parrot_formdesigner.audio.session_store import AudioSessionStore, AudioSnapshot, ResumeUnavailable, SnapshotConflict  # test_audio_session_store.py:6-11
from parrot_formdesigner.core.voice import VoiceFormConfig   # core/voice.py:50 (resume_ttl_seconds :63)
```

### Existing Signatures to Use
```python
# audio/session_store.py
AUDIO_KEY_PREFIX = "parrot:audio:"                                   # :16
class AudioSnapshot(BaseModel):                                      # :40
    config: VoiceFormConfig | None = None                            # :51
    user_id: str                                                     # :57
    saved_at: datetime | None = None; expires_at: datetime | None = None   # :59-60
def _text(value: Any) -> str | None                                  # :63
class AudioSessionStore:                                             # :70
    def __init__(self, partial_store: PartialSaveStore, *, ttl_seconds: int) -> None   # :73
    @staticmethod def _active_key(user_id: str) -> str               # :83
    async def save(self, form_uid, session_id, snapshot, *, expected_revision=None) -> int   # :86
        # :109-117  now = …; new = snapshot.model_copy(update={"revision": …, "saved_at": now,
        #           "expires_at": now + timedelta(seconds=self.ttl_seconds)});
        #           ok = await redis.eval(_CAS_SCRIPT, 1, key, raw or "", new.model_dump_json(), self.ttl_seconds)
        # :118-119  if ok: return new.revision
    async def _release(self, redis: Any, user_id: str, session_id: str) -> None   # :157-161
    async def claim_active(self, user_id: str, session_id: str) -> bool            # :173-188

# tests/formdesigner/test_audio_session_store.py
class FakeRedis: get / setex / set(key, value, nx=False, ex=None) / delete / eval   # :16-50; records TTLs in .ttls
@pytest.fixture def stores(): … return partial, AudioSessionStore(partial, ttl_seconds=60)   # :53-57
def _snap(**kw) -> AudioSnapshot                                     # :60
async def test_session_store_roundtrip_and_claim(stores)             # :64 (claim assertions :71-76)
async def test_resume_unavailable_without_redis()                    # :87 (constructor :88, claim :91)
```

### Does NOT Exist
- ~~`ActiveHolder`~~, ~~`_parse_holder`~~, ~~`_resume_ttl`~~, ~~`_refresh_active`~~, ~~`active_holder`~~ — created here.
- ~~`AudioSessionStore.ttl_seconds`~~ after this task — gone; use `resume_ttl_seconds` / `active_ttl_seconds`.
- ~~`FakeRedis.expire`~~ / ~~`FakeRedis.ttl`~~ — the double has no expire/ttl; refresh with `set(..., ex=)`, read TTLs from `FakeRedis.ttls`.
- ~~`VoiceFormConfig.active_ttl_seconds`~~ — the marker TTL is store-level only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_session_store.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py#AudioSessionStore",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py#AudioSnapshot",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py#AudioSessionStore.save",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py#AudioSessionStore.claim_active"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every method stays best-effort exactly as today: Redis errors → `self.logger.warning`, never raise (except `load`'s `ResumeUnavailable`). `active_holder` returns None on error.
- Legacy detection: a value that does not start with `{` is a bare session id. Never `try: json.loads(...)` arbitrary input as the only test.
- `_refresh_active` keeps the stored holder value unchanged; it only re-sets the `ex`.
- No-Redis behaviour unchanged: `claim_active` → True, `active_holder` → None.

---

## Implementation Blueprint

### Steps (in order)
1. Add `ActiveHolder` + `_parse_holder` after `_text` — *why*: both claim and release need the same parse.
2. Change `__init__` — *why*: G2, two independent TTLs.
3. Add `_resume_ttl` and use it in `save()`; call `_refresh_active` after a successful CAS — *why*: AC3, AC4.
4. Rewrite `_release` and `claim_active`; add `active_holder` — *why*: AC2, holder in the marker.
5. Update the fixture/constructor calls and claim calls in the tests; add the new tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def _text(value: Any) -> str | None:' audio/session_store.py)
# AFTER — insert below the body of `_text` (ends at `return value.decode() if isinstance(value, (bytes, bytearray)) else str(value)`, :67)


class ActiveHolder(BaseModel):
    """Who holds a user's active-session slot (value of ``parrot:audio:active:{user_id}``).

    ``form_uid`` / ``tenant`` are None only for a legacy bare-string marker.
    """

    session_id: str
    form_uid: str | None = None
    tenant: str | None = None


def _parse_holder(raw: str | None) -> ActiveHolder | None:
    """JSON holder → ActiveHolder; a legacy bare session id → ActiveHolder(session_id=raw); None/'' → None."""
    if not raw:
        return None
    # FILL IN: if raw.lstrip().startswith("{") → ActiveHolder.model_validate_json(raw) (on ValidationError
    # return None); else ActiveHolder(session_id=raw) — bounded by AC2 and §7 "Legacy detection".
```

```python
# occurrences: 1 (verified: grep -cF '    def __init__(self, partial_store: PartialSaveStore, *, ttl_seconds: int) -> None:' audio/session_store.py)
# REPLACE __init__ (:73-76) with:
    def __init__(
        self, partial_store: PartialSaveStore, *, resume_ttl_seconds: int = 3600, active_ttl_seconds: int = 600
    ) -> None:
        """``resume_ttl_seconds``: snapshot TTL when the snapshot has no config; ``active_ttl_seconds``: marker TTL."""
        self.partial_store = partial_store
        self.resume_ttl_seconds = resume_ttl_seconds
        self.active_ttl_seconds = active_ttl_seconds
        self.logger = logging.getLogger(__name__)

    def _resume_ttl(self, snapshot: AudioSnapshot) -> int:
        """``snapshot.config.resume_ttl_seconds`` when a config is present, else the store default."""
        return snapshot.config.resume_ttl_seconds if snapshot.config is not None else self.resume_ttl_seconds
```

```python
# save(): occurrences 1 each —
#   grep -cF '                        "expires_at": now + timedelta(seconds=self.ttl_seconds),' audio/session_store.py
#   grep -cF '                ok = await redis.eval(_CAS_SCRIPT, 1, key, raw or "", new.model_dump_json(), self.ttl_seconds)' audio/session_store.py
# Compute `ttl = self._resume_ttl(snapshot)` once before the retry loop and use it in both places:
                        "expires_at": now + timedelta(seconds=ttl),
                ok = await redis.eval(_CAS_SCRIPT, 1, key, raw or "", new.model_dump_json(), ttl)
                if ok:
                    await self._refresh_active(redis, snapshot.user_id, session_id)
                    return new.revision
```

```python
# occurrences: 1 (verified: grep -cF '        if _text(await redis.get(akey)) == session_id:' audio/session_store.py)
# REPLACE _release body line (:160) with:
        holder = _parse_holder(_text(await redis.get(akey)))
        if holder is not None and holder.session_id == session_id:
            await redis.delete(akey)

    async def _refresh_active(self, redis: Any, user_id: str, session_id: str) -> None:
        """Re-set the marker with EX ``active_ttl_seconds`` only when held by ``session_id``; best effort."""
        # FILL IN: read raw = _text(await redis.get(self._active_key(user_id))); when _parse_holder(raw)
        # has session_id == session_id → await redis.set(key, raw, ex=self.active_ttl_seconds) (keep the
        # stored value, incl. legacy); any exception → self.logger.warning(...), never raise — AC4.
```

```python
# occurrences: 1 (verified: grep -cF '    async def claim_active(self, user_id: str, session_id: str) -> bool:' audio/session_store.py)
# REPLACE claim_active (:173-188) with:
    async def claim_active(self, user_id: str, session_id: str, *, form_uid: str, tenant: str | None) -> bool:
        """SET NX the holder JSON with EX ``active_ttl_seconds``; the same session re-claims (and rewrites) it.

        Returns False when another session holds the slot. Without Redis it cannot enforce → True.
        """
        redis = await self.partial_store._get_redis()
        if redis is None:
            return True
        key = self._active_key(user_id)
        value = ActiveHolder(session_id=session_id, form_uid=form_uid, tenant=tenant).model_dump_json()
        try:
            if await redis.set(key, value, nx=True, ex=self.active_ttl_seconds):
                return True
            holder = _parse_holder(_text(await redis.get(key)))
            if holder is not None and holder.session_id == session_id:
                await redis.set(key, value, ex=self.active_ttl_seconds)
                return True
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("AudioSessionStore.claim_active failed: %s", exc)
            return True
        return False

    async def active_holder(self, user_id: str) -> ActiveHolder | None:
        """Current holder of the user's slot; None without Redis, when absent, or on a Redis error."""
        # FILL IN: redis = await self.partial_store._get_redis(); None → None; try get + _parse_holder;
        # except → logger.warning and None — bounded by AC1 consumer (TASK-4263) and §7 best-effort rule.
```
**Why**: spec §2 Overview items 1–3 and §3 M1 skeleton (signatures fixed). Re-claim rewrites the
value so a legacy marker becomes JSON once its own session reconnects.

### `packages/parrot-formdesigner/tests/formdesigner/test_audio_session_store.py` (MODIFY)
```python
# occurrences: 1 each —
#   grep -cF '    return partial, AudioSessionStore(partial, ttl_seconds=60)' …  → AudioSessionStore(partial, resume_ttl_seconds=60, active_ttl_seconds=30)
#   grep -cF '    store = AudioSessionStore(PartialSaveStore(), ttl_seconds=60)' … → AudioSessionStore(PartialSaveStore())
# Every claim_active(...) call in this file gains `form_uid="f", tenant="t1"` keywords.

async def test_claim_active_stores_holder_json(stores):
    from parrot_formdesigner.audio.session_store import ActiveHolder

    partial, store = stores
    assert await store.claim_active("u1", "s1", form_uid="f1", tenant="t1") is True
    assert await store.active_holder("u1") == ActiveHolder(session_id="s1", form_uid="f1", tenant="t1")
    # FILL IN: partial._redis.ttls["parrot:audio:active:u1"] == 30 (active TTL) — AC4


async def test_active_holder_legacy_bare_value(stores):
    partial, store = stores
    partial._redis.kv["parrot:audio:active:u1"] = "s1"
    # FILL IN: active_holder → ActiveHolder(session_id="s1", form_uid=None, tenant=None);
    # claim_active("u1","s1",form_uid="f",tenant="t1") is True and rewrites JSON; release_active("u1","s1") deletes it — AC2


async def test_active_holder_absent_and_no_redis(stores):
    # FILL IN: absent → None; AudioSessionStore(PartialSaveStore()).active_holder("u1") → None — §7
    ...


async def test_save_uses_snapshot_resume_ttl(stores):
    from parrot_formdesigner.core.voice import VoiceFormConfig

    partial, store = stores
    await store.save("f", "sess", _snap(config=VoiceFormConfig(resume_ttl_seconds=7200)))
    assert partial._redis.ttls["parrot:audio:f:sess"] == 7200
    # FILL IN: loaded.expires_at - loaded.saved_at == 7200 s; a snapshot without config → 60 (store default) — AC3


async def test_save_refreshes_marker_of_same_session_only(stores):
    # FILL IN: claim for "sess", set ttls[marker]=1, save("f","sess",_snap()) → ttls[marker]==30;
    # with the marker held by "other", save("f","sess",…) leaves it (value and ttl) untouched — AC4
    ...
```

### FILL IN checklist
- [ ] `_parse_holder` JSON vs legacy — AC2
- [ ] `_refresh_active` body — AC4
- [ ] `active_holder` body — AC1 consumer
- [ ] five test bodies — AC2, AC3, AC4

---

## Acceptance Criteria

- [ ] Marker value is `ActiveHolder` JSON; legacy bare value readable, re-claimable and releasable by its session (AC2)
- [ ] Snapshot TTL = `snapshot.config.resume_ttl_seconds`, fallback store `resume_ttl_seconds` (AC3)
- [ ] Marker TTL = `active_ttl_seconds`; each successful save refreshes it only for the saving session (AC4)
- [ ] All tests in `test_audio_session_store.py` pass; `ruff check` clean on touched files

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_session_store.py -q`

---

## Test Specification

See the blueprint test block above (spec §4, M1 rows).

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-active-session-resume --feature-id FEAT-655 --spec sdd/specs/audio-form-active-session-resume.spec.md --index sdd/tasks/index/audio-form-active-session-resume.json`)
2. **Read the spec** (§2 Overview 1–3, §3 Module 1, §5 AC2–AC4, §7)
3. **Check dependencies** in `sdd/tasks/index/audio-form-active-session-resume.json`
4. **Verify the Codebase Contract** — re-run every `grep -c`; a changed count means re-locate; 0 means STOP and report drift
5. **Update status** → `"in-progress"` and commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Commands with `-p no:xdist`, one file at a time
8. **Commit the code** — stage only the files listed above
9. **Close** with `scripts/sdd/close_task.sh TASK-4262 audio-form-active-session-resume verified`
10. **Fill in the Completion Note** and commit

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
