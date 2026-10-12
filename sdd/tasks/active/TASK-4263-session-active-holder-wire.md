# TASK-4263: `SESSION_ACTIVE` carries the holder's ids; `Error` fields; split-TTL composition

**Feature**: FEAT-655 — Audio form active-session resume hint and split TTLs
**Spec**: `sdd/specs/audio-form-active-session-resume.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4262
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (G1, G3; AC1, AC5, AC6). With TASK-4262 the marker records who holds the
user's slot. This task puts it on the wire: when `claim_active` fails, on the fresh-start path
(`api/audio_ws.py:679`) and on the resume path (`:673`), the handler reads
`store.active_holder(user_id)` and sends

```json
{"type":"error","code":"SESSION_ACTIVE","message":"Another session is already active",
 "session_id":"…","form_uid":"…"}
```

**only when `holder.tenant == session.tenant` and `holder.form_uid` is known**. Otherwise
(different tenant, legacy holder, holder vanished) it sends today's error unchanged. It also
passes `form_uid`/`tenant` to `claim_active` and builds the store with both TTLs in
`api/routes.py:495`.

---

## Scope

- `Error` gains optional `session_id` and `form_uid` (omitted when None).
- `_send_error` gains keyword-only `session_id` / `form_uid`.
- New `_send_session_active(ws, store, session)`; both `SESSION_ACTIVE` sites call it.
- Both `claim_active` calls pass `form_uid=…, tenant=session.tenant`.
- `routes.py`: `AudioSessionStore(partial_store, resume_ttl_seconds=3600, active_ttl_seconds=600)`.
- Tests (spec §4 M2 rows): adapter tests and the routes composition test; update the
  existing `test_second_active_session_rejected`.

**NOT in scope**: the store internals (TASK-4262), docs (TASK-4264), any client, takeover /
`SESSION_REPLACED`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py` | MODIFY | `Error` optional ids |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` | MODIFY | claim kwargs, `_send_session_active`, `_send_error` kwargs |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | store constructor |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py` | MODIFY | holder on SESSION_ACTIVE tests |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_events.py` | MODIFY | `Error` wire test |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_routes.py` | MODIFY | split-TTL composition test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.audio.session_store import ActiveHolder, AudioSessionStore   # ActiveHolder created by TASK-4262
from parrot_formdesigner.audio.events import Error                                   # audio/events.py:441
from parrot_formdesigner.api.audio_ws import AudioFormWSHandler, _ConnCtx            # test_audio_ws_adapter.py:14
from parrot_formdesigner.api.routes import setup_form_api                            # test_audio_routes.py:6
from parrot_formdesigner.services.partial_saves import PartialSaveStore
```

### Existing Signatures to Use
```python
# audio/events.py:441-444
class Error(_Wire):
    type: Literal["error"] = "error"
    code: str
    message: str
# _Wire.to_wire(): model_dump(mode="json", exclude_none=True)   # :282

# api/audio_ws.py (start path, inside the start_session handler)
#   session.form_uid = form_uid ; session.tenant = declared_tenant      (~:647-650; session is AudioSessionState)
#   store = self._session_store                                         # :661
#   if start.resume_session_id: … snap = await store.load(form_uid, start.resume_session_id)   # :667
#       if not await store.claim_active(session.user_id, start.resume_session_id):            # :673
#           await self._send_error(ws, "SESSION_ACTIVE", "Another session is already active")  # :674
#           return
#   else:
#       if store is not None and not await store.claim_active(session.user_id, session.session_id):   # :679
#           await self._send_error(ws, "SESSION_ACTIVE", "Another session is already active")          # :680
#           return
async def _send_error(self, ws: web.WebSocketResponse, code: str, message: str) -> None   # :1359
#   body: try: await ws.send_json({"type": "error", "code": code, "message": message}) except Exception: pass

# api/routes.py:495
            session_store = AudioSessionStore(partial_store, ttl_seconds=3600)
# api/routes.py:~510 — app.router.add_get(f"{tp}/forms/{{form_uid}}/audio/ws", audio_handler.handle_websocket)

# AudioSessionStore (after TASK-4262)
async def claim_active(self, user_id, session_id, *, form_uid: str, tenant: str | None) -> bool
async def active_holder(self, user_id) -> ActiveHolder | None
self.resume_ttl_seconds: int ; self.active_ttl_seconds: int

# tests/formdesigner/test_audio_ws_adapter.py: _TENANT = "t1" (:22), _form (:27), _ws (:44), _msgs (:51),
#   _handler(form, synth, stt, **kw) (:73), _boot(handler, *, start=None) (:79; match_info tenant "t1"),
#   test_second_active_session_rejected (:313; store.claim_active = AsyncMock(return_value=False))
#   resume tests use store.load = AsyncMock(...) (:327 pattern)
# tests/formdesigner/test_audio_routes.py: setup_form_api(app, registry, synthesizer=…, transcriber=…, …) (:38-49)
```

### Does NOT Exist
- ~~`Error.details`~~ — the ids are top-level optional fields.
- ~~`app["audio_handler"]`~~ — the handler is not stored on the app; reach it through the registered route handler's `__self__`.
- ~~`SESSION_REPLACED`~~ / takeover — out of scope.
- ~~`StartSession.resume_ttl_seconds`~~ — no per-session override.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_events.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_routes.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py#Error",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py#AudioFormWSHandler._send_error",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py#setup_form_api"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The tenant comparison uses `session.tenant` (set from the declared tenant on the start path), never a header.
- Ids are sent only when the holder's `tenant == session.tenant` AND `holder.form_uid` is not None.
- `message` text is unchanged in every case.
- Keep the start handler flat: each `SESSION_ACTIVE` site becomes `await self._send_session_active(ws, store, session); return`.
- Find the `form_uid` variable the start path already uses for `store.load(form_uid, …)` (`:667`) and pass that to both claims.

---

## Implementation Blueprint

### Steps (in order)
1. Extend `Error` — *why*: AC6, single wire schema for the optional ids.
2. Extend `_send_error` — *why*: the handler builds error dicts there, not from `Error`.
3. Add `_send_session_active` and wire both sites; pass `form_uid`/`tenant` to both claims — *why*: AC1.
4. Update `routes.py` — *why*: AC5.
5. Tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'class Error(_Wire):' audio/events.py)
# REPLACE the class body (:441-444) with:
class Error(_Wire):
    type: Literal["error"] = "error"
    code: str
    message: str
    session_id: str | None = None  # SESSION_ACTIVE only: the session holding the user's slot (same tenant)
    form_uid: str | None = None  # SESSION_ACTIVE only: that session's form
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    async def _send_error(' api/audio_ws.py)
# REPLACE _send_error (:1359-…) with:
    async def _send_error(
        self,
        ws: web.WebSocketResponse,
        code: str,
        message: str,
        *,
        session_id: str | None = None,
        form_uid: str | None = None,
    ) -> None:
        """Send an error message over the WebSocket.

        Args:
            ws: Active WebSocket.
            code: Machine-readable error code.
            message: Human-readable error description.
            session_id: SESSION_ACTIVE only — the session holding the user's slot.
            form_uid: SESSION_ACTIVE only — that session's form.
        """
        payload: dict[str, Any] = {"type": "error", "code": code, "message": message}
        # FILL IN: add session_id / form_uid keys only when not None (omitted otherwise, v1 parity) — AC6
        try:
            await ws.send_json(payload)
        except Exception:
            pass

    async def _send_session_active(
        self, ws: web.WebSocketResponse, store: "AudioSessionStore", session: AudioSessionState
    ) -> None:
        """SESSION_ACTIVE with the holder's ids when it belongs to the same tenant; today's error otherwise."""
        holder = await store.active_holder(session.user_id)
        # FILL IN: when holder is not None and holder.form_uid is not None and holder.tenant == session.tenant →
        # _send_error(ws, "SESSION_ACTIVE", "Another session is already active", session_id=holder.session_id,
        # form_uid=holder.form_uid); else the same call without ids — AC1.
```
Verify before writing: `grep -n 'AudioSessionState' api/audio_ws.py` (the start path's `session` is an
`AudioSessionState`; import it from `..audio.models` if it is not already imported) and that
`Any` is imported (`grep -n '^from typing' api/audio_ws.py`).

```python
# occurrences: 1 (verified: grep -cF '            if not await store.claim_active(session.user_id, start.resume_session_id):' api/audio_ws.py)
# REPLACE that line and the next two (SESSION_ACTIVE + return, :673-675) with:
            if not await store.claim_active(
                session.user_id, start.resume_session_id, form_uid=form_uid, tenant=session.tenant
            ):
                await self._send_session_active(ws, store, session)
                return

# occurrences: 1 (verified: grep -cF '            if store is not None and not await store.claim_active(session.user_id, session.session_id):' api/audio_ws.py)
# REPLACE that line and the next two (:679-681) with:
            if store is not None and not await store.claim_active(
                session.user_id, session.session_id, form_uid=form_uid, tenant=session.tenant
            ):
                await self._send_session_active(ws, store, session)
                return
```
The literal `"SESSION_ACTIVE", "Another session is already active"` appears twice today (`:674`, `:680`);
after this edit it appears only inside `_send_session_active`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '            session_store = AudioSessionStore(partial_store, ttl_seconds=3600)' api/routes.py)
            session_store = AudioSessionStore(partial_store, resume_ttl_seconds=3600, active_ttl_seconds=600)
```

### Tests
```python
# test_audio_events.py — append
def test_error_wire_session_ids_optional():
    from parrot_formdesigner.audio.events import Error

    assert set(Error(code="X", message="m").to_wire()) == {"type", "code", "message"}
    # FILL IN: with session_id="s", form_uid="f" both keys present with those values — AC6


# test_audio_ws_adapter.py — inside the class holding test_second_active_session_rejected (:313)
    async def test_second_active_session_returns_holder(self, synth, stt) -> None:
        from parrot_formdesigner.audio.session_store import ActiveHolder

        store = MagicMock()
        store.claim_active = AsyncMock(return_value=False)
        store.active_holder = AsyncMock(return_value=ActiveHolder(session_id="old", form_uid="fA", tenant=_TENANT))
        h = _handler(_form("a"), synth, stt, session_store=store)
        ws, ctx = await _boot(h)
        err = _msgs(ws)[0]
        assert err["code"] == "SESSION_ACTIVE" and err["session_id"] == "old" and err["form_uid"] == "fA"
        # FILL IN: claim_active was awaited with form_uid=… and tenant=_TENANT keywords; ctx.engine is None — AC1

    async def test_second_active_session_other_tenant_hides_holder(self, synth, stt) -> None:
        # FILL IN: holder tenant "other" (and a second case with form_uid=None) → error keys == {"type","code","message"} — AC1
        ...

    async def test_resume_claim_refused_returns_holder(self, synth, stt) -> None:
        # FILL IN: store.load returns a valid AudioSnapshot (reuse the resume tests' snapshot pattern), claim_active False,
        # active_holder same tenant → SESSION_ACTIVE with the holder ids on start={"protocol_version": 2, "resume_session_id": "old"} — AC1
        ...
# ALSO update test_second_active_session_rejected: add `store.active_holder = AsyncMock(return_value=None)`
# (a MagicMock attribute is not awaitable) and keep its assertions.


# test_audio_routes.py — inside the WS-route test class (:32)
    def test_routes_builds_store_with_split_ttls(self) -> None:
        # FILL IN: setup_form_api(app, registry, transcriber=MagicMock(), partial_store=PartialSaveStore());
        # find the route whose path contains "/audio/ws"; handler = route.handler (bound method) →
        # handler.__self__._session_store has resume_ttl_seconds == 3600 and active_ttl_seconds == 600 — AC5
        ...
```

### FILL IN checklist
- [ ] `_send_error` optional keys — AC6
- [ ] `_send_session_active` tenant rule — AC1
- [ ] adapter tests (3 new + 1 updated) — AC1
- [ ] `Error` wire test — AC6
- [ ] routes composition test — AC5

---

## Acceptance Criteria

- [ ] `SESSION_ACTIVE` (fresh start and resume) carries the holder's `session_id`/`form_uid` only for the same tenant with a known form; otherwise today's error (AC1)
- [ ] `routes.py` builds the store with `resume_ttl_seconds=3600, active_ttl_seconds=600`; `grep -rn 'ttl_seconds=' packages/parrot-formdesigner/src | grep AudioSessionStore` is empty (AC5)
- [ ] `Error` / `_send_error` optional ids omitted when unset (AC6)
- [ ] Existing tests in `test_audio_ws_adapter.py`, `test_audio_ws_v2_integration.py`, `test_audio_routes.py` pass (AC8)
- [ ] `ruff check` clean on touched files

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_events.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_routes.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py -q`

---

## Test Specification

See the blueprint test block above (spec §4, M2 rows). `test_audio_ws_resume_cross_channel`
(`test_audio_ws_v2_integration.py:429`) must keep passing unchanged: it proves resume works with the
JSON marker end to end.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-active-session-resume --feature-id FEAT-655 --spec sdd/specs/audio-form-active-session-resume.spec.md --index sdd/tasks/index/audio-form-active-session-resume.json`)
2. **Read the spec** (§2 Overview 4–6, §3 Module 2, §5 AC1/AC5/AC6/AC8, §7)
3. **Check dependencies** — TASK-4262 must be `"done"`
4. **Verify the Codebase Contract** — re-run every `grep -c`; 0 means STOP and report drift
5. **Update status** → `"in-progress"` and commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** — Validation Commands with `-p no:xdist`, one file at a time
8. **Commit the code** — stage only the files listed above
9. **Close** with `scripts/sdd/close_task.sh TASK-4263 audio-form-active-session-resume verified`
10. **Fill in the Completion Note** and commit

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
