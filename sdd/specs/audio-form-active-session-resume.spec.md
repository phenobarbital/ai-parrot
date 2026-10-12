---
type: feature
base_branch: dev
projects: [parrot-formdesigner, docs]
tags: [audio-forms, voice, session-resume, redis, ttl]
---

# Feature Specification: Audio form active-session resume hint and split TTLs

**Feature ID**: FEAT-655
**Date**: 2026-10-12
**Author**: Juan Ruffato (requested by Jesus Lara as a continuation of FEAT-649)
**Status**: draft
**Target version**: next parrot-formdesigner minor (same train as FEAT-653 / FEAT-654)
**Continues**: `sdd/specs/audio-form-interaction-workflow.spec.md` (FEAT-649, Module 7 "resume" and AC16)

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-649 enforces **one active audio session per user** with a Redis marker
`parrot:audio:active:{user_id}` (`audio/session_store.py:83`, `claim_active` at `:173`). When a
second `start_session` cannot claim it, the WebSocket answers
`{"type":"error","code":"SESSION_ACTIVE","message":"Another session is already active"}`
(`api/audio_ws.py:674,680`) and nothing else. The client cannot tell **which** session holds
the slot, so it cannot offer the obvious way out: *"Continue where you left off"* through the
resume path that already exists (`start_session{resume_session_id}` → `session_resumed`).

When this happens today:
- the server process died (deploy, pod restart, OOM) while a session was open: the `finally`
  that releases the marker (`api/audio_ws.py:392-396`) never ran, so the marker blocks the user
  for its whole TTL — **3600 s**;
- the user opens the form on a second tab or device, or after their browser storage was
  cleared (the navigator-svelte client stores the resume id per device in `localStorage`);
- the user opens a *different* form while one is unfinished (the marker is per user, not per
  form).

The navigator-svelte client treats `SESSION_ACTIVE` as fatal, so in all three cases the user
is stuck until the TTL expires.

A second defect sits in the same store: there is **one TTL for two different things**.
`AudioSessionStore(partial_store, ttl_seconds=3600)` is hard-coded in `api/routes.py:495`, and
`ttl_seconds` is used both for the snapshot that makes a session resumable (`save`, `:114,117`)
and for the active marker (`claim_active`, `:180,183`). `VoiceFormConfig.resume_ttl_seconds`
(`core/voice.py:63`, FEAT-649 spec line 211) exists but **nothing reads it**: a form author
cannot make a session resumable for longer than an hour, and making the marker shorter would
also shorten how long a session can be resumed.

### Goals

- G1. `SESSION_ACTIVE` carries the `session_id` and `form_uid` of the session that holds the
  user's slot, so a client can offer *"Continue where you left off"* through the existing
  resume path. This leaks nothing: the marker key is the requesting user's own.
- G2. Split the two TTLs: the **resume TTL** governs the snapshot, the **active TTL** governs
  the marker.
- G3. Wire `VoiceFormConfig.resume_ttl_seconds` to the snapshot TTL, per form.
- G4. Bound how long a crashed session can block the user: active TTL default **600 s**,
  refreshed on every snapshot save so a live session keeps its slot.
- G5. Document the client behaviour (`docs/audio-form-voice-modes.md`, navigator-svelte handoff).

### Non-Goals (explicitly out of scope)

- **Heartbeat, takeover and `SESSION_REPLACED`** (defect 1 of the
  `audio-form-voice-followups` brainstorm). Jesús asked for this cheap change *before* the
  heartbeat. Resuming from a second device while the first connection is still alive is not
  arbitrated here; see §7.
- **Discarding the blocking session from the new connection** ("start over instead"). The
  client can already end a session by resuming it and sending `end`. A server-side "discard"
  belongs with takeover.
- The navigator-svelte client. This spec fixes the wire contract and the docs it is built from.
- The `/partial` mirror TTL (`PartialSaveStore`, 3600 s default). Voice resume reads its
  answers from the snapshot (`AudioSnapshot.answer_meta`), not from `/partial`; see §7.
- A per-session (`start_session`) override of either TTL.

---

## 2. Architectural Design

### Overview

1. **Marker value becomes a small JSON holder** instead of the bare session id:
   `{"session_id": "...", "form_uid": "...", "tenant": "..."}` (`ActiveHolder`). A legacy
   bare-string value written by a pre-FEAT-655 process is read as
   `ActiveHolder(session_id=<value>, form_uid=None, tenant=None)`, so a rolling deploy needs no
   migration: legacy markers expire on their own (≤ 1 h).
2. **`claim_active(user_id, session_id, *, form_uid, tenant)`** writes the holder. It returns
   `bool` exactly as today. Equality checks (re-claim by the same session, `_release`) compare
   `holder.session_id`. A new **`active_holder(user_id) -> ActiveHolder | None`** reads it.
3. **Two TTLs on the store**:
   `AudioSessionStore(partial_store, *, resume_ttl_seconds=3600, active_ttl_seconds=600)`.
   - `save()` uses `snapshot.config.resume_ttl_seconds` when the snapshot carries a config
     (`AudioSnapshot.config`, `session_store.py:51`, set by the engine from the effective form
     config) and the store's `resume_ttl_seconds` otherwise, for both the Redis `EX` and
     `expires_at`.
   - `claim_active` uses `active_ttl_seconds`.
   - After a successful CAS write, `save()` **refreshes the marker** (`EX active_ttl_seconds`)
     when it is still held by this `session_id` for `snapshot.user_id`. Every answer saves a
     snapshot, so an active session keeps its slot without a heartbeat. A crashed one releases
     it within `active_ttl_seconds` of its last save.
4. **WS handler**: when `claim_active` fails, on both the fresh-start (`:679`) and the resume
   (`:673`) path, the handler reads `active_holder(user_id)` and sends
   `SESSION_ACTIVE` with `session_id` and `form_uid` **only when `holder.tenant` equals the
   connection's tenant**. Otherwise (different tenant, legacy holder, holder vanished between
   the two reads) it sends the error without them, exactly as today. The `message` is
   unchanged.
5. **Wire**: `Error` gains optional `session_id: str | None` and `form_uid: str | None`
   (omitted when `None`, `_Wire.to_wire` uses `exclude_none`). `_send_error` gains the same two
   keyword-only arguments. Additive for v1 and v2 clients.
6. **Composition** (`api/routes.py:495`): `AudioSessionStore(partial_store,
   resume_ttl_seconds=3600, active_ttl_seconds=600)`. 3600 stays as the default for snapshots
   whose config is absent. Per-form values come from `resume_ttl_seconds`.

Client flow enabled (documented, not implemented here):

```
start_session{form_uid: B}  ──►  error{code: SESSION_ACTIVE, session_id: S, form_uid: A}
client: "You have an unfinished form — Continue?"  ──►  (reconnect to form A's WS)
start_session{form_uid: A, resume_session_id: S}  ──►  session_resumed …
```

### Component Diagram
```
api/routes.py ──► AudioSessionStore(partial_store, resume_ttl_seconds=3600, active_ttl_seconds=600)
                     ├── save(form_uid, session_id, snap)  EX = snap.config.resume_ttl_seconds | resume_ttl_seconds
                     │      └── refresh marker EX active_ttl_seconds when held by session_id
                     ├── claim_active(user, session, *, form_uid, tenant)  SET NX holder-JSON EX active_ttl_seconds
                     └── active_holder(user) -> ActiveHolder | None   (parses JSON or legacy bare id)
api/audio_ws.py start path
   claim_active ✗ ──► active_holder ──► same tenant? ──► _send_error(SESSION_ACTIVE, session_id=…, form_uid=…)
                                                └─ no ──► _send_error(SESSION_ACTIVE)            (today's wire)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AudioSessionStore.__init__` (`audio/session_store.py:73`) | modifies | `ttl_seconds` → `resume_ttl_seconds`, `active_ttl_seconds` |
| `AudioSessionStore.save` (`:86`) | modifies | per-snapshot resume TTL + marker refresh |
| `AudioSessionStore._release` (`:157`) / `claim_active` (`:173`) | modifies | holder JSON, compare `session_id` |
| `AudioSessionStore.active_holder` | new | reads the holder |
| `AudioSnapshot.config` (`:51`) | uses | source of `resume_ttl_seconds` |
| `VoiceFormConfig.resume_ttl_seconds` (`core/voice.py:63`) | wires | first reader |
| `AudioFormWSHandler` start path (`api/audio_ws.py:661-682`) | modifies | holder on `SESSION_ACTIVE` |
| `AudioFormWSHandler._send_error` (`:1359`) | modifies | keyword-only `session_id`, `form_uid` |
| `Error` (`audio/events.py:441`) | extends | optional `session_id`, `form_uid` |
| `setup_form_api` composition (`api/routes.py:495`) | modifies | new constructor kwargs |
| docs + handoff + CHANGELOG | modifies | see Module 3 |

### Data Models
```python
# audio/session_store.py (new)
class ActiveHolder(BaseModel):
    """Who holds a user's active-session slot (value of parrot:audio:active:{user_id})."""
    session_id: str
    form_uid: str | None = None   # None only for a legacy bare-string marker
    tenant: str | None = None

# audio/events.py (extended)
class Error(_Wire):
    type: Literal["error"] = "error"
    code: str
    message: str
    session_id: str | None = None   # NEW — SESSION_ACTIVE only: the holder's session
    form_uid: str | None = None     # NEW — SESSION_ACTIVE only: the holder's form
```

Wire:
```json
{"type": "error", "code": "SESSION_ACTIVE", "message": "Another session is already active",
 "session_id": "6f0c…", "form_uid": "3f2a…"}
```

### New Public Interfaces
```python
class AudioSessionStore:
    def __init__(self, partial_store: PartialSaveStore, *, resume_ttl_seconds: int = 3600,
                 active_ttl_seconds: int = 600) -> None: ...
    async def claim_active(self, user_id: str, session_id: str, *, form_uid: str,
                           tenant: str | None) -> bool: ...
    async def active_holder(self, user_id: str) -> ActiveHolder | None: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: store — holder + split TTLs | yes | holder JSON shape, legacy parse rule, TTL sources, refresh rule, signatures fixed below | — |
| M2: WS + wire | yes | tenant-equality rule, Error fields, `_send_error` kwargs, composition kwargs fixed | — |
| M3: docs | yes | sections and rows listed | — |

### Module 1: Store — `ActiveHolder`, split TTLs, marker refresh
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py` (modify),
  `packages/parrot-formdesigner/tests/formdesigner/test_audio_session_store.py` (modify)
- **Responsibility**: holder encoding (JSON) with the legacy bare-id parse; `claim_active` writes
  the holder with `active_ttl_seconds`; `active_holder` reads it; `_release` compares
  `holder.session_id`; `save` takes its TTL from `snapshot.config.resume_ttl_seconds` (fallback:
  store default) and refreshes the marker held by the same session.
- **Depends on**: nothing.
- **Interface Skeleton**:
  ```python
  # audio/session_store.py
  class ActiveHolder(BaseModel):
      """Who holds a user's active-session slot. ``form_uid``/``tenant`` are None only for a legacy marker."""
      session_id: str
      form_uid: str | None = None
      tenant: str | None = None

  def _parse_holder(raw: str | None) -> ActiveHolder | None:
      """JSON holder → ActiveHolder; a non-JSON legacy value → ActiveHolder(session_id=raw); None/'' → None."""

  class AudioSessionStore:  # verified: audio/session_store.py:70
      def __init__(self, partial_store: PartialSaveStore, *, resume_ttl_seconds: int = 3600,
                   active_ttl_seconds: int = 600) -> None:  # replaces :73 (ttl_seconds)
          """``resume_ttl_seconds``: snapshot TTL when the snapshot has no config; ``active_ttl_seconds``: marker TTL."""

      def _resume_ttl(self, snapshot: AudioSnapshot) -> int:
          """``snapshot.config.resume_ttl_seconds`` when a config is present, else ``self.resume_ttl_seconds``."""

      async def save(self, form_uid: str, session_id: str, snapshot: AudioSnapshot, *,
                     expected_revision: int | None = None) -> int:  # verified: :86 — signature unchanged
          """CAS write with EX = _resume_ttl(snapshot); on success refresh the marker held by session_id."""

      async def _refresh_active(self, redis: Any, user_id: str, session_id: str) -> None:
          """Re-set the marker with EX active_ttl_seconds only when it is held by ``session_id``; best effort."""

      async def _release(self, redis: Any, user_id: str, session_id: str) -> None:  # verified: :157
          """Delete the marker when ``_parse_holder(...).session_id == session_id``."""

      async def claim_active(self, user_id: str, session_id: str, *, form_uid: str,
                             tenant: str | None) -> bool:  # replaces :173
          """SET NX holder-JSON EX active_ttl_seconds; same-session re-claim rewrites it; False when another session holds it."""

      async def active_holder(self, user_id: str) -> ActiveHolder | None:
          """Current holder of the user's slot; None without Redis, when absent, or on a Redis error."""
  ```

### Module 2: WS handler, wire and composition
- **Path**: `api/audio_ws.py`, `audio/events.py`, `api/routes.py` (modify);
  `tests/formdesigner/test_audio_ws_adapter.py` (modify)
- **Responsibility**: pass `form_uid`/`tenant` to `claim_active`; on failure read
  `active_holder` and send `SESSION_ACTIVE` with the holder ids when the tenant matches;
  `Error` and `_send_error` carry the optional ids; `routes.py` builds the store with both TTLs.
- **Depends on**: Module 1 (`claim_active` kwargs, `active_holder`, `ActiveHolder`, constructor).
- **Interface Skeleton**:
  ```python
  # audio/events.py:441
  class Error(_Wire):
      type: Literal["error"] = "error"
      code: str
      message: str
      session_id: str | None = None
      form_uid: str | None = None

  # api/audio_ws.py
  class AudioFormWSHandler:  # verified: api/audio_ws.py:228
      async def _send_error(self, ws: web.WebSocketResponse, code: str, message: str, *,
                            session_id: str | None = None, form_uid: str | None = None) -> None:  # :1359
          """Send ``{"type":"error",code,message}`` plus ``session_id``/``form_uid`` when given."""

      async def _send_session_active(self, ws: web.WebSocketResponse, store: "AudioSessionStore",
                                     session: AudioSessionState) -> None:
          """SESSION_ACTIVE with the holder's ids when ``holder.tenant == session.tenant`` and both ids are known."""

  # api/routes.py:495
  session_store = AudioSessionStore(partial_store, resume_ttl_seconds=3600, active_ttl_seconds=600)
  ```

### Module 3: Documentation
- **Path**: `docs/audio-form-voice-modes.md`,
  `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md`,
  `packages/parrot-formdesigner/CHANGELOG.md` (modify)
- **Responsibility**:
  - §10 Error Codes, `SESSION_ACTIVE` row (`:2425`): it now carries `session_id` + `form_uid`
    (same tenant only). Recovery: offer *"Continue where you left off"* →
    `start_session{form_uid, resume_session_id: session_id}` on that form's WS. Fall back to
    today's message when the ids are absent.
  - §6 `start_session` table, `resume_session_id` row (`:407`): `SESSION_ACTIVE` now carries
    the holder ids.
  - A short subsection under §7.3 (or the resume section of §9): marker vs resume TTL
    (`resume_ttl_seconds` per form; the marker lasts `active_ttl_seconds` = 600 s after the
    last save; a crashed session stops blocking within that window), and the second-device
    caveat (§7 Known Risks).
  - Handoff doc, error-code line (`:82`): note the extra ids and the recommended UI.
  - CHANGELOG: entry under the **top** `## [Unreleased]` (the file has a stale second one at `:156`).
- **Depends on**: Module 2 (names on the wire).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_claim_active_stores_holder_json` | M1 | after `claim_active("u1","s1",form_uid="f1",tenant="t1")`, `active_holder("u1") == ActiveHolder(session_id="s1", form_uid="f1", tenant="t1")`; FakeRedis TTL of the marker == `active_ttl_seconds` |
| `test_claim_active_same_session_reclaims_other_refused` | M1 | rewrite of the claim assertions in `test_session_store_roundtrip_and_claim`: same session → True, other → False, after `delete` other → True |
| `test_active_holder_legacy_bare_value` | M1 | marker set to the bare string `"s1"` → `ActiveHolder(session_id="s1", form_uid=None, tenant=None)`; `claim_active("u1","s1",…)` re-claims it; `_release` deletes it |
| `test_active_holder_absent_and_no_redis` | M1 | absent key → None; store over `PartialSaveStore()` without Redis → None (and `claim_active` → True, unchanged) |
| `test_save_uses_snapshot_resume_ttl` | M1 | snapshot with `config=VoiceFormConfig(resume_ttl_seconds=7200)` → FakeRedis TTL 7200 and `expires_at - saved_at == 7200 s`; without config → store `resume_ttl_seconds` |
| `test_save_refreshes_marker_of_same_session_only` | M1 | marker held by `sess` gets TTL reset to `active_ttl_seconds` after `save("f","sess",…)`; a marker held by `other` is untouched |
| `test_error_wire_session_ids_optional` | M2 | `Error(code="X", message="m").to_wire()` has no `session_id`/`form_uid`; with them set, both present |
| `test_second_active_session_returns_holder` | M2 | (adapter) store mock: `claim_active` False, `active_holder` → holder with same tenant → error carries `session_id` and `form_uid` |
| `test_second_active_session_other_tenant_hides_holder` | M2 | holder tenant differs (or `form_uid` None) → error has no `session_id`/`form_uid`, `message` unchanged |
| `test_resume_claim_refused_returns_holder` | M2 | `resume_session_id` path: `load` returns a snapshot, `claim_active` False → `SESSION_ACTIVE` with holder ids |
| `test_routes_builds_store_with_split_ttls` | M2 | the store built by `setup_form_api` has `resume_ttl_seconds == 3600` and `active_ttl_seconds == 600` (the handler is not stored on the app: find the router resource whose handler is the bound `AudioFormWSHandler.handle_websocket` and read `handler.__self__._session_store`; `api/routes.py:~511` registers it) |

### Integration Tests
| Test | Description |
|---|---|
| `test_audio_ws_resume_cross_channel` (existing, FEAT-649) | still passes unchanged: proves resume works with the holder-JSON marker |

### Test Data / Fixtures
```python
# test_audio_session_store.py: FakeRedis (:16) already emulates get/set(nx, ex)/delete/eval and
# records TTLs in .ttls — reuse it; extend only if a new Redis call is introduced (prefer get/set).
# test_audio_ws_adapter.py: _handler(..., session_store=store) with MagicMock/AsyncMock stores (:313 pattern).
```

---

## 5. Acceptance Criteria

- [ ] AC1. `SESSION_ACTIVE` (fresh start and resume paths) carries `session_id` and `form_uid` of
  the holding session when the holder's tenant equals the connection's tenant; otherwise the
  error is exactly today's (`type`, `code`, `message` only).
- [ ] AC2. The marker value is `ActiveHolder` JSON; a legacy bare-string marker is read as
  `ActiveHolder(session_id=<value>)`, can be re-claimed by that session and is released by it.
- [ ] AC3. The snapshot TTL (Redis `EX` and `expires_at`) is `VoiceFormConfig.resume_ttl_seconds`
  of the snapshot's config, falling back to the store's `resume_ttl_seconds`.
- [ ] AC4. The marker TTL is `active_ttl_seconds` (default 600), independent of the resume TTL,
  and every successful snapshot save refreshes it when held by the saving session (and never
  touches another session's marker).
- [ ] AC5. `api/routes.py` builds `AudioSessionStore(partial_store, resume_ttl_seconds=3600,
  active_ttl_seconds=600)`; no remaining caller passes `ttl_seconds=` to `AudioSessionStore`.
- [ ] AC6. `Error` / `_send_error` gain optional `session_id` and `form_uid`, omitted from the
  wire when unset; all other error codes are unchanged.
- [ ] AC7. Docs: §10 `SESSION_ACTIVE` row, §6 `resume_session_id` row, the TTL subsection, the
  handoff error-code line and the top `[Unreleased]` CHANGELOG entry describe the new fields,
  the recommended "Continue where you left off" flow and the second-device caveat.
- [ ] AC8. All tests in §4 pass and every existing test in `test_audio_session_store.py`,
  `test_audio_ws_adapter.py`, `test_audio_ws_v2_integration.py` and `test_audio_routes.py` passes
  after the intended constructor/claim updates; `ruff check` clean on touched files.

---

## 6. Codebase Contract

Paths relative to `packages/parrot-formdesigner/src/parrot_formdesigner/` (`P/`) unless stated.
Verified against `c2f2955a5` (dev, 2026-10-12).

### Verified Imports
```python
from parrot_formdesigner.audio.session_store import AudioSessionStore, AudioSnapshot, ResumeUnavailable, SnapshotConflict, AUDIO_KEY_PREFIX  # P/audio/session_store.py:70,40,36,32,16
from parrot_formdesigner.audio.events import Error                 # P/audio/events.py:441
from parrot_formdesigner.audio.models import AudioSessionState, Phase   # P/audio/models.py (tenant: :312)
from parrot_formdesigner.core.voice import VoiceFormConfig         # P/core/voice.py:50 (resume_ttl_seconds :63)
from parrot_formdesigner.services.partial_saves import PartialSaveStore  # P/services/partial_saves.py
```

### Existing Class Signatures
```python
# P/audio/session_store.py
AUDIO_KEY_PREFIX = "parrot:audio:"                                    # :16
class AudioSnapshot(BaseModel): ... config: VoiceFormConfig | None = None (:51); user_id: str (:57); tenant: str | None (:58); saved_at/expires_at (:59-60)
def _text(value) -> str | None                                       # :63
class AudioSessionStore:                                             # :70
    def __init__(self, partial_store, *, ttl_seconds: int) -> None   # :73
    def _key(form_uid, session_id) -> str                            # :79
    def _active_key(user_id) -> str  # f"{AUDIO_KEY_PREFIX}active:{user_id}"   :83
    async def save(self, form_uid, session_id, snapshot, *, expected_revision=None) -> int   # :86 (EX/expires_at use self.ttl_seconds :114,:117)
    async def load(self, form_uid, session_id) -> AudioSnapshot | None   # :127
    async def delete(self, form_uid, session_id, *, user_id=None) -> None   # :139
    async def _release(self, redis, user_id, session_id) -> None     # :157 (compares _text(get) == session_id :160)
    async def release_active(self, user_id, session_id) -> None      # :163
    async def claim_active(self, user_id, session_id) -> bool        # :173 (SET NX EX self.ttl_seconds :180; same-session re-set :182-183)

# P/api/audio_ws.py
class AudioFormWSHandler:                                            # :228
    # handle_websocket: web.WebSocketResponse(heartbeat=30.0, …) :330; finally → _autosave(final) :389, release_active :392-396
    # start path: session.form_uid = form_uid; session.tenant = declared_tenant (~:647-650)
    #   resume: store.load :667 → claim_active(session.user_id, start.resume_session_id) :673 → SESSION_ACTIVE :674
    #   fresh:  claim_active(session.user_id, session.session_id) :679 → SESSION_ACTIVE :680
    #   RESUME_STALE/FORBIDDEN → store.release_active(...) :692-696
    async def _save_snapshot(self, ws, ctx, snap) -> None            # :1148 (RESUME_CONFLICT on SnapshotConflict)
    async def _autosave(self, ctx, *, final=False) -> None           # :1162
    async def _send_error(self, ws, code: str, message: str) -> None # :1359 (ws.send_json({"type":"error","code":…,"message":…}))

# P/audio/events.py:441
class Error(_Wire): type: Literal["error"]; code: str; message: str
# _Wire.to_wire() -> model_dump(mode="json", exclude_none=True)     # :282

# P/api/routes.py:495
            session_store = AudioSessionStore(partial_store, ttl_seconds=3600)

# P/core/voice.py:63
    resume_ttl_seconds: int = Field(default=3600, ge=1)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ActiveHolder` | Redis marker value | JSON in `parrot:audio:active:{user_id}` | `session_store.py:83` |
| `_resume_ttl` | `AudioSnapshot.config.resume_ttl_seconds` | attribute | `session_store.py:51`, `core/voice.py:63` |
| `_send_session_active` | `AudioSessionStore.active_holder` | call | new |

### Does NOT Exist (Anti-Hallucination)
- ~~`AudioSessionStore.active_holder`~~, ~~`ActiveHolder`~~, ~~`_refresh_active`~~, ~~`_resume_ttl`~~, ~~`_send_session_active`~~ — created here.
- ~~`AudioSessionStore.ttl_seconds` after this feature~~ — replaced by `resume_ttl_seconds` / `active_ttl_seconds`.
- ~~`Error.details`~~ — the two ids are top-level optional fields, not a nested dict.
- ~~`StartSession.resume_ttl_seconds`~~ / ~~`AudioSessionConfig.resume_ttl_seconds`~~ — no per-session override.
- ~~`SESSION_REPLACED`~~, ~~heartbeat / takeover messages~~ — out of scope (future spec).
- ~~`redis.expire` in `FakeRedis`~~ — the test double has only `get`/`setex`/`set(nx, ex)`/`delete`/`eval`; refresh with `set(..., ex=)`.

### Edit Sites (Blueprint Anchors)
Verified against `c2f2955a5`.

| File | Action | Anchor (verbatim) | path:NN | occurrences |
|---|---|---|---|---|
| `P/audio/session_store.py` | MODIFY | `    def __init__(self, partial_store: PartialSaveStore, *, ttl_seconds: int) -> None:` | `:73` | 1 |
| `P/audio/session_store.py` | MODIFY | `                        "expires_at": now + timedelta(seconds=self.ttl_seconds),` | `:114` | 1 |
| `P/audio/session_store.py` | MODIFY | `                ok = await redis.eval(_CAS_SCRIPT, 1, key, raw or "", new.model_dump_json(), self.ttl_seconds)` | `:117` | 1 |
| `P/audio/session_store.py` | MODIFY | `        if _text(await redis.get(akey)) == session_id:` | `:160` | 1 |
| `P/audio/session_store.py` | MODIFY | `    async def claim_active(self, user_id: str, session_id: str) -> bool:` | `:173` | 1 |
| `P/api/audio_ws.py` | MODIFY | `            if not await store.claim_active(session.user_id, start.resume_session_id):` | `:673` | 1 |
| `P/api/audio_ws.py` | MODIFY | `            if store is not None and not await store.claim_active(session.user_id, session.session_id):` | `:679` | 1 |
| `P/api/audio_ws.py` | MODIFY | `                await self._send_error(ws, "SESSION_ACTIVE", "Another session is already active")` — **2 occurrences** (:674, :680): disambiguate by the preceding `claim_active` line | `:674,:680` | 2 |
| `P/api/audio_ws.py` | MODIFY | `    async def _send_error(` | `:1359` | 1 |
| `P/audio/events.py` | MODIFY | `class Error(_Wire):` | `:441` | 1 |
| `P/api/routes.py` | MODIFY | `            session_store = AudioSessionStore(partial_store, ttl_seconds=3600)` | `:495` | 1 |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_session_store.py` | MODIFY | `    return partial, AudioSessionStore(partial, ttl_seconds=60)` | `:57` | 1 |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_session_store.py` | MODIFY | `    store = AudioSessionStore(PartialSaveStore(), ttl_seconds=60)` | `:88` | 1 |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py` | MODIFY | `    async def test_second_active_session_rejected(self, synth, stt) -> None:` | `:313` | 1 |
| `docs/audio-form-voice-modes.md` | MODIFY | `` | `SESSION_ACTIVE` | Another live session already holds this user's session slot | No | Close the other session | `` | `:2425` | 1 |
| `docs/audio-form-voice-modes.md` | MODIFY | `` | `resume_session_id` | string \| null | `null` | `` (row prefix) | `:407` | 1 |
| `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` | MODIFY | `` `SESSION_ACTIVE`, `RESUME_FORBIDDEN` `` (inside the error-code line) | `:82` | 1 |
| `packages/parrot-formdesigner/CHANGELOG.md` | MODIFY | `## [Unreleased]` — **2 occurrences** (:5, :156); use the top one (after "All notable changes …") | `:5` | 2 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Keep every store method best-effort exactly like today: Redis errors are logged with
  `self.logger.warning` and never raise (except `load`'s `ResumeUnavailable`).
- Holder JSON via `ActiveHolder.model_dump_json()` / `model_validate_json`; a value that does
  not start with `{` is a legacy bare id. Do not `try/except` around a JSON parse of arbitrary
  input without that prefix check: a session id is not JSON.
- Refresh the marker with `get` + `set(key, value, ex=active_ttl_seconds)` (same non-atomic
  pattern as the same-session re-claim at `:182-183`); keep the stored holder value as is.
- `_send_session_active` keeps the start path flat (Rule 4 budgets): both call sites become
  one line.

### Known Risks / Gotchas
- **Second device while the first is alive.** With the ids exposed, *"Continue"* from device B
  re-claims the marker (same `session_id` → allowed, `:182-183`) while device A's connection
  may still be open. Both now drive one session; the snapshot CAS (`_save_snapshot`,
  `RESUME_CONFLICT`) guarantees integrity: the connection that loses the next save closes.
  That is safe but abrupt. Proper arbitration (`SESSION_REPLACED`, takeover) is the heartbeat
  spec, next in the roadmap. Document the caveat (AC7).
- **Idle longer than `active_ttl_seconds`.** The marker is only refreshed on saves. A user idle
  on one question for > 10 min loses exclusivity: a second session can start. Snapshots are
  keyed per session, so nothing is corrupted; the one-session rule is just not enforced during
  that window. Acceptable until the heartbeat exists.
- **`/partial` mirror outlives / dies before the voice snapshot.** Voice resume reads answers
  from `AudioSnapshot.answer_meta`, so `resume_ttl_seconds > 3600` works for voice. The HTTP
  `/partial` mirror keeps `PartialSaveStore`'s own TTL (3600 s default), so finishing over HTTP
  after an hour loses the mirrored scalars. Out of scope; mention in the TTL subsection.
- **Rolling deploy.** Old processes write bare-id markers; new ones read them (AC2). New
  processes write JSON; an old process reading it compares `_text(...) == session_id` → False,
  so an old process cannot release a new-format marker; it expires within `active_ttl_seconds`.
  Acceptable for one deploy window.
- **FieldSync test comment.** `fieldsync/tests/fieldsync/test_audio_ws_handshake.py:194` says
  the marker lasts an hour; the code there only deletes the key, so it keeps working. Update
  the comment in FieldSync when bumping parrot-formdesigner.
- **Tenant comparison.** `AudioSessionState.tenant` is set from the declared tenant on the start
  path (`session.tenant = declared_tenant`); compare against that, never a header.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | none |

---

## 8. Open Questions

- [x] Q1. Active-marker TTL default — *Decided 2026-10-12 (Juan)*: **600 s**, refreshed on every
  snapshot save. A crashed session stops blocking within 10 min of its last answer, and the
  ids in `SESSION_ACTIVE` let the user resume immediately instead of waiting.
- [x] Q2. Return the holder ids across tenants? — *Decided*: no. Only when the holder's tenant
  equals the connection's tenant (resume would be `RESUME_FORBIDDEN` anyway, and it avoids
  telling one tenant's page about another tenant's form).
- [x] Q3. Same spec or an amendment of FEAT-649? — *Decided*: a new FEAT that **continues**
  FEAT-649 (header `Continues:`). FEAT-649's task index is closed, and appending tasks to a
  completed feature is not allowed by `/sdd-task`.
- [ ] Q4. Should FEAT-654's svelte follow-up and this one share one navigator-svelte spec
  ("Continue where you left off" + barge-in + vad-web)? — *Owner: Juan* (not blocking this spec).

---

## 9. Design Research Cross-Check

Model: — · Status: skipped (no accepted brainstorm or proposal for this slug; requirement
came directly from Jesús on 2026-10-12)

| # | Suggestion | Disposition | Reason | Landed in |
|---|---|---|---|---|

---

## Worktree Strategy

- **Isolation**: one feature worktree (`.claude/worktrees/feat-FEAT-655-audio-form-active-session-resume`,
  from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree.
- **Module dependency graph**: M2 → M1 (`claim_active` kwargs, `active_holder`, `ActiveHolder`,
  constructor kwargs); M3 → M2 (documents the wire fields).
- **Shared files**: none between modules.
- **Exclusive resources**: none.
- **Cross-feature dependencies**: FEAT-653 and FEAT-654 also modify `api/audio_ws.py` and
  `audio/events.py` in other regions (`_segment_kind`, `_do_synthesize`, `AudioSegment`,
  post-processing). Order of landing: FEAT-653 → FEAT-654 → FEAT-655. The later branch rebases on
  `origin/dev` before `/sdd-done`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-12 | Juan Ruffato | Initial draft — continuation of FEAT-649 requested by Jesús (holder ids on SESSION_ACTIVE, split marker/resume TTLs, wire resume_ttl_seconds) |
