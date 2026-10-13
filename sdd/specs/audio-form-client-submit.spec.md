---
type: feature
base_branch: dev
projects: [parrot-formdesigner, docs]
tags: [audio-forms, voice, submission, client-submit]
---

# Feature Specification: Audio form client-submit mode (voice collects, the host submits)

**Feature ID**: FEAT-656
**Date**: 2026-10-12
**Author**: Juan Ruffato
**Status**: approved
**Target version**: next parrot-formdesigner minor, in ONE voice release with FEAT-653/654/655 (Juan, 2026-10-12: "todo sale junto"); FieldSync FEAT-715 and navigator-svelte FEAT-711..714 ship with it
**Continues**: FEAT-649 (`sdd/specs/audio-form-interaction-workflow.spec.md`)
**Consumers**: navigator-svelte FEAT-714 (rep voice forms, Rep Mode) and FieldSync FEAT-715
(execution Action submit accepts voice evidence envelopes).

---

## 1. Motivation & Business Requirements

### Problem Statement
The audio WebSocket always persists the answers itself on `review_confirm`:
`on_review_confirm` → `Submit` (`audio/engine.py:905-929`) → `_do_submit` →
`SubmissionPipeline.submit` (`api/audio_ws.py:1065-1108`) → `FormComplete{submission_id}`. That
is right for a standalone form (admin Fill page), but FieldSync reps fill forms **as part of an
execution Action**, whose submit endpoint does much more than store a submission: store/visit
context enforcement, GPS + GeoIP, `client_request_id` idempotency, the revision chain, the
submission index row and the dashboard event, all offline-capable. A voice submission today is an
unlinked record that skips all of it, and `start_session` (`extra="forbid"`) cannot even carry an
Action id. Re-implementing the Action path behind the WebSocket would duplicate
`SubmitActionService`. Decision (Juan, 2026-10-12, option A): **voice is an input method; the host
submits**.

### Goals
- G1. `start_session.submit_mode: "server" | "client"` (default `"server"`, today's behaviour).
- G2. In `"client"` mode, `review_confirm` runs the same **deterministic validation** (and the
  plausibility rules already applied before submit), but **persists nothing**; it replies
  `answers_ready{data, plausibility_summary}` and completes the session (snapshot and active
  marker released, as after `form_complete`).
- G3. `data` is exactly what the pipeline would have stored: validator `sanitized_data` with voice
  evidence envelopes (FEAT-488/649 shape, `blob_ref` to the stored recording) and plausibility
  verdicts attached to the envelopes.
- G4. Validation failures keep today's voice UX: `validation_errors` + re-ask the first failing field.

### Non-Goals (explicitly out of scope)
- Linking anything to an Action inside parrot (host concern; FEAT-714/715).
- Changing `"server"` mode; v1 clients (client mode requires `protocol_version: 2`).
- Deferring recording uploads: recordings are still stored at answer time when
  `store_recordings` is on, so `blob_ref`s are valid when the host submits. Orphan blobs from
  abandoned sessions behave as today.

---

## 2. Architectural Design

### Overview
1. **Wire.** `StartSession.submit_mode: Literal["server","client"] = "server"` (`audio/events.py:93`).
   New outbound `AnswersReady(_Wire)`: `type: "answers_ready"`, `data: dict[str, Any]`,
   `plausibility_summary: dict[str, Any] | None = None`. It joins `WireMessage`.
   `"client"` with `protocol_version < 2` → `Error(INVALID_MESSAGE, "submit_mode client requires protocol v2")`.
2. **State.** `AudioSessionState.submit_mode` (`audio/models.py`, `extra="forbid"` model) set in
   `on_start`; carried in `AudioSnapshot` so a resumed session keeps its mode.
3. **Engine.** Unchanged up to `Submit`: `on_review_confirm` still emits `Submit(data, context)`.
   `on_submit_done` gains one branch: when `ev.outcome` has `client_data`, emit
   `AnswersReady(data=outcome["client_data"], plausibility_summary=…)`, set `completed=True`,
   `phase=COMPLETE`. The `errors` branch (re-ask) is shared.
4. **Adapter.** `_do_submit` (`api/audio_ws.py:1065`): when `ctx.state.submit_mode == "client"` call
   `pipeline.validate(form, data, locale, auth_context, llm_validation=False)` (plausibility already
   ran in the engine before `Submit`) and, if valid, return
   `SubmitDone(outcome={"client_data": pipeline.attach_verdicts(result.sanitized_data, state.plausibility)})`;
   if invalid, `SubmitDone(outcome={"errors": result.errors})`. `SubmissionPipeline._attach_verdicts`
   becomes public `attach_verdicts` (rename; one internal caller). No `on_before/after_submit`
   hooks run (nothing is submitted).
5. **Lifecycle.** `_autosave` already releases a `COMPLETE` session (`_release_session`), so the
   snapshot and the active marker go away exactly as after `form_complete`.
6. **Sensitive answers.** `data` includes sensitive values the client typed in this same
   connection (they are needed by the host submit; they are never spoken or recorded, S8).
   `answers_ready` is never logged.

### Data Models
```python
class StartSession(_Inbound):            # audio/events.py:93
    ...
    submit_mode: Literal["server", "client"] = "server"

class AnswersReady(_Wire):               # new, next to FormComplete (:428)
    type: Literal["answers_ready"] = "answers_ready"
    data: dict[str, Any]
    plausibility_summary: dict[str, Any] | None = None
```
Wire:
```json
{"type":"answers_ready","data":{"qty":{"answer":520,"transcript":"five hundred twenty","blob_ref":"voice-…","…":"…"},"email":"a@b.co"},"plausibility_summary":null}
```

---

## 3. Module Breakdown
| Module | Path | Responsibility | Depends on |
|---|---|---|---|
| M1 Wire + state | `audio/events.py`, `audio/models.py`, `audio/session_store.py` (snapshot field) | `submit_mode`, `AnswersReady`, v2 guard | — |
| M2 Engine branch | `audio/engine.py` (`on_start`, `on_submit_done`, snapshot/resume) | client branch, resume keeps mode | M1 |
| M3 Adapter + pipeline | `api/audio_ws.py` `_do_submit`, `services/submission_pipeline.py` (`attach_verdicts`) | validate-only path | M1, M2 |
| M4 Docs | `docs/audio-form-voice-modes.md`, svelte handoff, CHANGELOG (top `[Unreleased]`) | contract + host guidance (submit the `data` through your own endpoint; idempotency is the host's) | M3 |

---

## 4. Test Specification
| Test | Module | Description |
|---|---|---|
| `start_session submit_mode default server` / `client requires v2` | M1 | |
| `answers_ready wire` | M1 | `to_wire()` shape; joins the outbound union |
| `engine client branch emits AnswersReady and completes` | M2 | `on_submit_done({"client_data":…})` → `AnswersReady`, phase COMPLETE |
| `engine errors branch unchanged in client mode` | M2 | re-asks first failing field |
| `resume keeps submit_mode` | M2 | snapshot → `from_snapshot` → mode preserved |
| `adapter client mode never calls pipeline.submit` | M3 | pipeline mock: `validate` awaited, `submit` not; `answers_ready` sent; no `form_complete` |
| `client data carries envelopes and verdicts` | M3 | spoken NUMBER → envelope with `blob_ref`; plausibility verdict attached |
| `client mode invalid → validation_errors` | M3 | |
| `server mode unchanged` | M3 | existing `form_complete` tests pass |
| v2 integration `test_audio_ws_client_submit` | M3 | full session in client mode → `answers_ready`, nothing stored (fake storage untouched), snapshot released |

---

## 5. Acceptance Criteria
- [ ] AC1. `submit_mode` defaults to `"server"`; every existing test passes unchanged.
- [ ] AC2. In client mode nothing is persisted (no pipeline `submit`, no storage write, no hooks); the client receives `answers_ready` with validator-sanitized data, voice envelopes (`blob_ref`) and plausibility verdicts.
- [ ] AC3. Validation errors in client mode re-ask the first failing field exactly like server mode.
- [ ] AC4. After `answers_ready` the snapshot and the active marker are released; a resumed client-mode session stays in client mode.
- [ ] AC5. `"client"` with protocol v1 is rejected with `INVALID_MESSAGE`.
- [ ] AC6. Docs describe the mode, the payload and the host's responsibilities (submit, idempotency, linking).

---

## 6. Codebase Contract
Verified on ai-parrot `origin/dev` (2026-10-12). `P/` = `packages/parrot-formdesigner/src/parrot_formdesigner/`.
```python
# P/audio/events.py
class StartSession(_Inbound): type; form_uid; locale="en"; protocol_version=1; prefetch=True; resume_session_id; stt_confirm_threshold; tts_backend; tts_voice; tts_mime_format; auto_advance   # :93-105
class SubmitDone(_Inbound)            # :207
class _Wire(BaseModel) … to_wire()     # :281
class ValidationErrors(_Wire)          # :414
class FormComplete(_Wire): submission_id: str; answers; stored_in; plausibility_summary   # :428-433
class Submit(_IORequest)               # :491
WireMessage union … FormComplete, SessionEnded, Error, Pong   # ~:500-524 ; IORequest :525 ; Outbound :526
# P/audio/engine.py
def on_start(self, ev: StartSession)   # :169 (sets state.locale / protocol_version)
def on_review_confirm(self, ev)        # :905 ; _submit() :925-929 (Submit(data=self._submission_data(), context=…))
def on_submit_done(self, ev: SubmitDone)   # ~:1104 (errors branch + FormComplete)
def _submission_data(self)             # wrap_voice(scalars, …)  ~:1140
# P/api/audio_ws.py
if isinstance(item, Submit): return await self._do_submit(ctx, item)   # :822-823
async def _do_submit(self, ctx, item: Submit) -> "InboundEvent"         # :1065-1108
# P/services/submission_pipeline.py
async def validate(self, form, data, *, locale, auth_context, llm_validation=False, visit_context=None) -> tuple[ValidationResult, PlausibilityReport | None]   # :100
async def submit(...)                  # :119
def _attach_verdicts(self, data, report)   # :324 (→ public attach_verdicts)
```
### Does NOT Exist
- ~~`submit_mode`~~, ~~`AnswersReady`~~, ~~public `attach_verdicts`~~ — added here.
- ~~any Action / activity / event id in parrot~~ — and none is added.
- ~~a "submit later" message from the client~~ — the host submits over its own HTTP endpoint.

## 7. Implementation Notes & Constraints
- `AudioSessionState` and `AudioSnapshot` are `extra="forbid"` / validated: add the field to both and to the snapshot round-trip.
- Keep `_do_submit` flat (Rule 4): put the client branch in `_do_client_submit`.
- FEAT-653/654/655 touch the same files; land after them and rebase.

## 8. Open Questions
- [x] Include sensitive values in `answers_ready`? — *Decided*: yes; they were typed by the same client on this connection and the host submit needs them. Never logged.
- [ ] Should client mode also emit a cheap `session_ended` after `answers_ready`? Proposal: no; `answers_ready` is terminal like `form_complete`. — *Owner: Jesús*

## Worktree Strategy
One feature worktree; M2 → M1, M3 → M1/M2, M4 → M3. Lands after FEAT-653 → 654 → 655.

## Revision History
| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-12 | Juan Ruffato | Initial draft — option A for rep voice forms (voice collects, host submits) |
| 0.2 | 2026-10-12 | Juan Ruffato | Approved (Juan) |
