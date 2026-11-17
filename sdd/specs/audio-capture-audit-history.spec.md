---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [parrot-formdesigner]
tags: [audio-forms, audit-trail, voice, capture, compliance, formdesigner]
---

# Feature Specification: Audio capture history in the submission audit trail

**Feature ID**: FEAT-749
**Date**: 2026-10-24
**Author**: Juan Ruffato
**Status**: draft
**Target version**: next minor after parrot-formdesigner 1.3.0

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-732 (parrot-formdesigner 1.3.0) made the **validation** of a submission
reconstructable: `context["validation"]` carries the deterministic trace and
`context["llm_validation"]` carries the plausibility verdict with its effective
model. It deliberately says nothing about **how the answers were captured** by the
voice agent. The question Jesus Lara raised for FieldSync (2026-10-22) —

> "El audit trail del agente de FieldSync (su pasada de captura) — ¿queda registrado
> en algún sitio de FieldSync, o hoy solo existe el rastro del pipeline?"

— has a partial answer today:

| Capture fact | Persisted today? |
|---|---|
| Final value, raw transcript, STT confidence, `normalized_by`, `llm_confidence`, `blob_ref`, duration, `version` of the accepted answer | **Yes**, inside the voice evidence envelope in `data` (`wrap_voice`, `audio/engine.py:1312-1320`) |
| `channel`, `session_id`, `locale`, `submission_id` | **Yes**, `context` (`_submission_context`, `audio/engine.py:1321-1328`) |
| What the agent **proposed** before the user corrected it, which answers needed a confirm turn, which were rejected and re-asked, which were edited from the review screen, which were skipped | **No** — it lives in `AudioSessionState`, which `FormComplete` deletes |
| Anything about a **sensitive** field | **No, by design** (S8) — and that must not change |

For a dispute ("the rep says they never said that"), the stored envelope proves what
was **accepted**, not that the user **confirmed** it. This feature records the capture
process so it survives the session.

A second problem sits underneath: **in `submit_mode: "client"` the WebSocket persists
nothing** (`audio/events.py:110`, `api/audio_ws.py:1246-1266`). The client receives
`answers_ready{client_data, plausibility_summary}` and submits through the host's own
endpoint (FieldSync's Action submit does exactly this — FEAT-715). Whatever capture
record this feature produces must therefore travel through a client the host does not
trust. An audit record that the submitter can edit is not an audit record.

### Goals

- G1. Record an append-only **capture log** per audio session: one event per
  proposal, confirm, reject/re-ask, acceptance (with its `version`), review edit, skip
  and back-navigation.
- G2. Persist it as `context["capture"]` on server-submit, next to `validation` and
  `llm_validation`, with an explicit size cap and explicit truncation (same discipline
  as `cap_trace`).
- G3. **Sensitive fields (S8) never contribute values, transcripts or candidates** —
  only the event kind and timestamp.
- G4. Make the record **tamper-evident** when it crosses the client in client-submit
  mode, so a host can tell a record the server produced from one the client wrote.
- G5. Survive a resume: the log is part of the session snapshot, so a session resumed
  on another pod continues the same log.
- G6. Change no existing wire message or public signature in a breaking way.

### Non-Goals (explicitly out of scope)

- NG1. **Persisting the audio itself** — unchanged (`blob_ref` + `store_recordings`).
- NG2. **Reading or authorizing the audit** — that is the host's concern (FieldSync
  ships its own reader). Parrot's `/audit` endpoint (FEAT-732) is not extended here.
- NG3. **Text-mode sessions** are logged with the same events but nothing new is built
  for them; no separate text-capture feature.
- NG4. **Retention / redaction / export** — inherits the lifetime of the submission
  row, like FEAT-732 NG5.
- NG5. No change to `AudioAnswer`'s existing fields or to the voice evidence envelope.
- NG6. The deterministic and LLM validation trace (FEAT-732) is untouched.

---

## 2. Architectural Design

### Overview

**A. The capture log is engine state, not an I/O request.** `AudioFormSession` is a
pure state machine: events in, `Outbound` requests out. The log is appended inside the
engine at the points where it already decides, and carried as a new field of
`AudioSessionState` so it rides the existing snapshot/resume path. No new `Outbound`
and no new I/O.

The append points are the engine's own funnels, not scattered call sites:

| Event | Appended in |
|---|---|
| `proposed` (low-confidence speech awaiting confirm) | `_request_confirm` |
| `confirmed` / `rejected` | `on_confirm` |
| `accepted` (carries the new `version`, `source`, STT confidence, `normalized_by`, `llm_confidence`) | `_accept` — the single acceptance funnel |
| `edited` (re-answered from the review) | `on_review_edit` → next `_accept` |
| `skipped` / `back` | `on_skip`, `on_back` |

**B. Sensitive fields log the shape, never the content.** For a field where
`is_sensitive(field)` holds, an event keeps `kind`, `field_id`, `version`, `at` and
nothing else — no candidate value, no transcript, no confidences that could fingerprint
the answer. The same predicate `snapshot()` already uses
(`audio/engine.py:1148`) decides this.

**C. Detail follows the form's existing `audit_trail.detail`.** No second knob:
`off` → no log is kept (a form with auditing off pays nothing and the snapshot is
unchanged); `summary` (default) → per-field counts and the final acceptance's
provenance; `full` → every event. This keeps one place where an operator chooses how
much evidence a form retains, and keeps FEAT-732's guarantee that switching one audit
off cannot switch another off.

**D. Server-submit: write it into `context`.** `_submission_context()` gains
`"capture": <capped log>`; the pipeline already merges `context` into the stored
`FormSubmission.context` (`services/submission_pipeline.py`), so no pipeline change is
needed beyond the cap.

**E. Client-submit: sign it.** In client mode the engine returns the log inside
`answers_ready` as a **signed envelope** — the capped log plus an HMAC computed
server-side over a canonical serialization and bound to `session_id`, `submission_id`
and `form_uid`. The host forwards it opaquely with its own submit; a verifier helper
exposed by parrot lets the host mark the stored record `verified: true|false` without
re-deriving anything. Two designs were considered:

| | Signed envelope (chosen) | Server-held record |
|---|---|---|
| Tamper evidence | HMAC; client can drop it but not edit it | Strong — the client never holds it |
| New storage | None | A durable store keyed by `session_id` beyond the Redis snapshot TTL |
| Host coupling | Host forwards one extra opaque field | Host must join on `session_id` later |
| Failure mode | Record can be **omitted** by the client (host sees "absent", can refuse) | Record can be **missing** if the store lags |

The signed envelope is chosen because it needs no new durable storage in parrot; its
known weakness (omission) is detectable by the host and is documented as a risk (R3).
If the maintainer prefers the server-held design, only Module 3 changes.

**F. Cap and truncation.** The log is capped before it is merged or signed, with an
explicit `truncated: true` and `omitted_events` count — a short log is never mistaken
for a complete one. The cap default is resolved per detail level, like FEAT-732's
`DEFAULT_MAX_BYTES`.

### Component Diagram

```
AudioFormSession (state machine)
  ├─ _request_confirm ──┐
  ├─ on_confirm ────────┤
  ├─ _accept ───────────┤ append(CaptureEvent)  ──→ AudioSessionState.capture_log
  ├─ on_review_edit ────┤                               │
  └─ on_skip / on_back ─┘                               ├─→ snapshot()/resume (G5)
                                                        │
  _submit()  [server mode] ──→ cap_capture() ──→ context["capture"] ──→ FormSubmission.context
  _answers_ready() [client mode] ──→ cap_capture() ──→ sign_capture() ──→ answers_ready{capture}
                                                                   │ (client forwards opaquely)
                                                  host: verify_capture(envelope) → verified bool
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AudioFormSession._accept` / `on_confirm` / `_request_confirm` / `on_skip` / `on_back` / `on_review_edit` | modifies | append one event each; no change to control flow |
| `AudioSessionState` | extends | new `capture_log` field; `extra="forbid"` means the model must declare it |
| `AudioSnapshot` / `AudioFormSession.snapshot()` / `from_snapshot()` | extends | the log round-trips; older snapshots without it must still load (empty log) |
| `AudioFormSession._submission_context()` | modifies | adds `"capture"` |
| `AudioFormSession` client-mode completion → `AnswersReady` event | extends | adds an optional signed `capture` field |
| `FormSchema.audit_trail` (`AuditTrailConfig.detail`) | reads | decides `off`/`summary`/`full` and the cap |
| `core/audit_trail.py` | extends | a `CaptureLog` model and its cap beside `ValidationTrace` |
| `SubmissionPipeline.submit` | uses | already merges `context`; unchanged |
| `AudioFormSession.on_submit_done` | uses | clears the log with the rest of the session on `FormComplete` |

### Data Models

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/audit_trail.py  (extended)

class CaptureEventKind(str, Enum):
    """Stable kinds — a published contract, persisted and read back by auditors.
    Values are never renamed."""

    PROPOSED = "proposed"      # low-confidence speech awaiting a confirm turn
    CONFIRMED = "confirmed"
    REJECTED = "rejected"      # user discarded the candidate; the question is re-asked
    ACCEPTED = "accepted"      # the single acceptance funnel; carries the version
    EDITED = "edited"          # re-answered from the review screen
    SKIPPED = "skipped"
    BACK = "back"


class CaptureEvent(BaseModel):
    """One step of the capture pass.  Sensitive fields carry only kind/field/version/at."""

    kind: CaptureEventKind
    field_id: str
    at: datetime
    version: int | None = None
    source: Literal["text", "speech", "selection"] | None = None
    stt_confidence: float | None = None
    normalized_by: Literal["rules", "llm"] | None = None
    llm_confidence: float | None = None
    # full detail only, never for a sensitive field:
    candidate: Any | None = None
    transcript: str | None = None


class CaptureLog(BaseModel):
    """Capped, serializable capture record for one session."""

    capture_schema: int = 1
    session_id: str
    submission_id: str
    form_uid: str
    detail: AuditDetail
    started_at: datetime | None = None
    resumed_count: int = 0
    events: list[CaptureEvent] = Field(default_factory=list)
    truncated: bool = False
    omitted_events: int = 0


class SignedCapture(BaseModel):
    """Client-mode envelope: the capped log plus a server-side HMAC."""

    log: dict[str, Any]
    alg: Literal["hmac-sha256"] = "hmac-sha256"
    kid: str
    sig: str
```

### New Public Interfaces

```python
# services/capture_audit.py  (new)
def cap_capture(log: CaptureLog, *, max_bytes: int) -> dict[str, Any]: ...
def sign_capture(log: dict[str, Any], *, key: bytes, kid: str,
                 session_id: str, submission_id: str, form_uid: str) -> SignedCapture: ...
def verify_capture(signed: SignedCapture | dict[str, Any], *, keys: Mapping[str, bytes],
                   session_id: str, submission_id: str, form_uid: str) -> bool: ...
```

`verify_capture` is the only part a host calls; it never raises on a malformed or
foreign envelope — it returns `False`.

---

## 3. Module Breakdown

### Module 1: Capture models and cap
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/audit_trail.py`, `services/capture_audit.py` (new)
- **Responsibility**: `CaptureEventKind`, `CaptureEvent`, `CaptureLog`, `cap_capture`; default caps per detail level.
- **Depends on**: FEAT-732 `AuditDetail`, `AuditTrailConfig`.

### Module 2: Engine capture log
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py`, `audio/models.py`
- **Responsibility**: `AudioSessionState.capture_log`; append at the funnels in §2.A; S8 stripping; `off` keeps nothing.
- **Depends on**: Module 1.

### Module 3: Snapshot round-trip
- **Path**: `audio/session_store.py` (`AudioSnapshot`), `audio/engine.py` (`snapshot`, `from_snapshot`, resume path)
- **Responsibility**: the log survives resume; a snapshot written before this feature loads with an empty log; `resumed_count` increments.
- **Depends on**: Module 2.

### Module 4: Server-submit persistence
- **Path**: `audio/engine.py` (`_submission_context`)
- **Responsibility**: `context["capture"]` = capped log; absent when detail is `off`.
- **Depends on**: Modules 1–2.

### Module 5: Client-submit signed envelope
- **Path**: `services/capture_audit.py`, `audio/events.py` (`AnswersReady`), `api/audio_ws.py` (`_do_client_submit`), setup kwargs for the signing key
- **Responsibility**: sign on `answers_ready`; `verify_capture`; key id rotation; no key configured → the envelope is omitted and `capture_unsigned` is logged once, never a failed session.
- **Depends on**: Modules 1–2.

### Module 6: Documentation
- **Path**: `packages/parrot-formdesigner/docs/…` (the FEAT-732 audit-trail page), `version.py`
- **Responsibility**: document the capture block, the event table, the S8 guarantee and the signing contract; version bump.
- **Depends on**: Modules 1–5.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_cap_capture_truncates_explicitly` | 1 | over-cap log → `truncated: true`, `omitted_events` > 0, header intact |
| `test_cap_capture_tiny_cap_degrades_to_header` | 1 | cap too small for events → minimal header, never raises |
| `test_accept_appends_version_and_provenance` | 2 | accepted event carries `version`, `source`, STT and LLM confidences |
| `test_reanswer_bumps_version_and_logs_edit` | 2 | review edit → `edited` then `accepted` with `version + 1` |
| `test_confirm_and_reject_are_logged` | 2 | low-confidence → `proposed`, then `confirmed` or `rejected` |
| `test_sensitive_field_logs_shape_only` | 2 | sensitive field: no candidate, transcript or confidences, in any detail level (mutation: remove the guard → red) |
| `test_audit_off_keeps_no_log` | 2 | `audit_trail.detail == off` → empty log, snapshot unchanged |
| `test_snapshot_roundtrip_keeps_log` | 3 | resume on a fresh session continues the same log, `resumed_count` + 1 |
| `test_old_snapshot_loads_with_empty_log` | 3 | snapshot without the field → empty log, no error |
| `test_sign_verify_roundtrip` | 5 | signed envelope verifies with the right key |
| `test_verify_rejects_edited_log` | 5 | one changed event → `False` |
| `test_verify_rejects_foreign_session` | 5 | envelope replayed against another `session_id`/`submission_id`/`form_uid` → `False` |
| `test_verify_never_raises` | 5 | malformed input → `False` |

### Integration Tests
| Test | Description |
|---|---|
| `test_server_submit_persists_capture_context` | full session via the WS → stored `FormSubmission.context["capture"]` present and capped |
| `test_client_submit_returns_signed_capture` | `submit_mode: "client"` → `answers_ready` carries a verifiable `capture` |
| `test_sensitive_answer_end_to_end` | a sensitive field is absent from the stored context, the snapshot and the signed envelope |

### Validation Contract

tests:
- packages/parrot-formdesigner/tests/unit/test_capture_audit.py
- packages/parrot-formdesigner/tests/formdesigner/test_audio_capture_log.py
- packages/parrot-formdesigner/tests/formdesigner/test_audio_capture_submit.py
markers: none

### Test Data / Fixtures
```python
# Scripted AudioFormSession event sequences (the engine is a pure state machine —
# no WebSocket needed for the unit level): start → low-confidence transcript →
# confirm | reject → accept → review edit → submit. A form fixture with one
# sensitive field (is_sensitive(field) is True) and audit_trail.detail parametrized.
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1. A server-submit voice session stores `context["capture"]` with one event per proposal, confirm, reject, acceptance, edit, skip and back, in order.
- [ ] AC2. An accepted event records the answer `version`, so a re-answer is visible as `version` 2 following `version` 1.
- [ ] AC3. For a sensitive field no stored, snapshotted or signed event contains a value, candidate, transcript or confidence.
- [ ] AC4. `audit_trail.detail == "off"` produces no `capture` block and an unchanged snapshot.
- [ ] AC5. A resumed session continues the same log; a pre-feature snapshot still resumes.
- [ ] AC6. A client-submit session returns a signed `capture`; `verify_capture` is `True` for it and `False` for any edited, replayed-elsewhere or malformed envelope.
- [ ] AC7. An over-cap log stores `truncated: true` and `omitted_events`; it never fails the submit.
- [ ] AC8. No existing wire message loses or renames a field; `AudioAnswer` and the voice envelope are unchanged.
- [ ] AC9. Each new assertion in the Validation Contract was mutation-checked — revert the code, see it red.

---

## 6. Codebase Contract

> Verified against `origin/dev` @ `e3d2d3734` (2026-10-24); re-checked 2026-10-25: no change to the audio engine, `audio_ws.py`, `audit_trail.py` or the pipeline since then.

### Verified Imports
```python
from parrot_formdesigner.core.audit_trail import AuditDetail, AuditTrailConfig, ValidationTrace  # core/audit_trail.py:110-124
from parrot_formdesigner.core.voice import is_sensitive                                          # audio/engine.py:489 uses it
```

### Existing Class Signatures
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py
class AudioFormSession:
    def _request_confirm(self, evidence, value, transcript, match, alternatives): ...   # :477
    def _accept(self, field_id, value, *, source, confidence=None, raw=None, matched=None,
                evidence=None, normalized_by=None, llm_confidence=None) -> list[Outbound]:  # :551
        # "Single acceptance funnel": bumps version = prev.version + 1 (:566)
    def on_confirm(self, ev: ConfirmAnswer) -> list[Outbound]: ...                      # :722
    def on_skip(self, ev: SkipQuestion) -> list[Outbound]: ...                          # :771
    def on_back(self, ev: GoBack) -> list[Outbound]: ...                                # :788
    def on_review_edit(self, ev: ReviewEdit) -> list[Outbound]: ...                     # :1089
    def snapshot(self) -> AudioSnapshot: ...                                            # :1135  (sensitive: value/raw_transcript set to None at :1148)
    def _submission_context(self) -> dict[str, Any]: ...                                # :1321  {channel, session_id, locale, submission_id}
    def _submission_data(self) -> dict[str, Any]: ...                                   # :1312  wrap_voice(...) — sensitive answers are plain scalars

# packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py
class AudioSessionState(BaseModel):   # model_config = ConfigDict(extra="forbid")  (:262ff)
    answers, history, plan, phase, plausibility, flagged, submission_id, submit_mode, ...

# packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py
class AnswersReady(...):  type: Literal["answers_ready"]                                # :458
# audio/events.py:110 — submit_mode: Literal["server","client"] = "server"  # "client": answers_ready, nothing persisted

# packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py
async def _do_client_submit(self, ctx, item) -> InboundEvent: ...                       # :1246 (validate only, persist nothing)
async def _do_submit(self, ctx, item) -> InboundEvent: ...                              # server path via SubmissionPipeline.submit(context=item.context)

# packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py
class AudioSnapshot(BaseModel): ...                                                      # :40
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `CaptureLog` append | `AudioFormSession._accept` | direct call before returning `AnswerAccepted` | `engine.py:551` |
| `context["capture"]` | `FormSubmission.context` | `_submission_context()` → `Submit(context=…)` → `SubmissionPipeline.submit(context=…)` | `engine.py:1084-1086`, `audio_ws.py:1203` |
| `SignedCapture` | `answers_ready` | `_do_client_submit` outcome | `audio_ws.py:1264-1266` |
| detail / cap | `FormSchema.audit_trail` | `AuditTrailConfig.detail`, `.effective_max_bytes` | `core/audit_trail.py:110-121` |

### Does NOT Exist (Anti-Hallucination)
- ~~`AudioSessionState.capture_log`~~ — does not exist yet (this feature adds it).
- ~~`context["capture"]`~~ — nothing writes it today; `_submission_context` carries only four keys.
- ~~a capture/event history in `AudioSessionState`~~ — `history` is only the ordered visited `field_id`s for back-navigation, with no values or timestamps.
- ~~`parrot_formdesigner.services.capture_audit`~~ — new module.
- ~~HMAC / signing of any session output~~ — nothing in `audio/` signs anything today.
- ~~a public helper to build/cap the FEAT-732 trace outside `SubmissionPipeline`~~ — `_new_collector`/`_capped_trace` are private; unrelated to this feature, noted so a host does not assume one.

### Edit Sites (Blueprint Anchors)

Verified against: `e3d2d3734`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py` | MODIFY | `    def _accept(` | `engine.py:551` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py` | MODIFY | `    def on_confirm(` | `engine.py:722` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py` | MODIFY | `    def _request_confirm(` | `engine.py:477` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py` | MODIFY | `    def snapshot(` | `engine.py:1135` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py` | MODIFY | `    def _submission_context(` | `engine.py:1321` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py` | MODIFY | `    def on_skip(` | `engine.py:771` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py` | MODIFY | `    def on_review_edit(` | `engine.py:1089` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` | MODIFY | `class AudioSessionState(BaseModel):` | `models.py:262` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/session_store.py` | MODIFY | `class AudioSnapshot(BaseModel):` | `session_store.py:40` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py` | MODIFY | `    type: Literal["answers_ready"] = "answers_ready"` | `events.py:458` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` | MODIFY | `    async def _do_client_submit(` | `audio_ws.py:1246` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/audit_trail.py` | MODIFY | `class AuditTrailConfig(BaseModel):` | `audit_trail.py:110` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/capture_audit.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/tests/unit/test_capture_audit.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_capture_log.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_capture_submit.py` | CREATE | — | — | — |

`engine.py` is 1,332 lines: the appends must be one plain call each into a small
collaborator (e.g. a `CaptureRecorder` owned by the session), not new branches in the
funnels — `_accept` is the single acceptance funnel and must stay readable.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror FEAT-732: explicit collector object owned by the session (no `ContextVar`), stable enum values as a published contract, cap *before* merge, explicit truncation metadata, a minimal-header fallback instead of a failed submit.
- The engine stays pure: appending to the log is state mutation, never an `Outbound`.
- Reuse `is_sensitive` — do not introduce a second sensitivity predicate.

### Known Risks / Gotchas
- **R1 — S8 is the regression to fear.** The snapshot already had to special-case sensitive answers; a new log is a new place to leak them. AC3 and its mutation test are the guard.
- **R2 — `AudioSessionState` is `extra="forbid"`.** Field added to the state and to `AudioSnapshot`; an older snapshot must still validate.
- **R3 — Omission in client-submit.** A client can drop the signed envelope. The host sees "absent" and decides; this spec does not try to make omission impossible.
- **R4 — Key management.** The signing key and `kid` come from host configuration; a missing key degrades to "no envelope + one warning", never a failed session. Rotation is by `kid` with a verify-keys map.
- **R5 — Size.** A long voice session with `full` detail can be large; the per-level cap and `truncated` flag are required, and the snapshot (Redis) grows with the log.
- **R6 — PII.** `full` detail stores transcripts of non-sensitive fields only; retention is the host's submission-row lifetime (NG4).
- **R7 — Clock.** `at` is server time (the engine's clock), never client-supplied.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (none) | — | `hmac` / `hashlib` / `json` from the standard library |

---

## 8. Open Questions

- [x] **Q1 — Feature ID.** Reserved as FEAT-749 on 2026-10-25 so both specs can be reviewed together.
- [ ] **Q2 — Signed envelope vs server-held record** for client-submit (§2.E). The envelope needs no new storage; a server-held record is stronger against omission but needs a durable store. — *Owner: Jesus Lara*
- [ ] **Q3 — Where the signing key lives** (host kwargs like the existing audio setup kwargs, or a parrot setting). — *Owner: Jesus Lara / host*
- [ ] **Q4 — Does `summary` need per-field counts only, or also the final acceptance's provenance?** The spec assumes the latter; the envelope already holds most of it. — *Owner: Jesus Lara*
- [ ] **Q5 — Text-mode sessions**: log them with the same events (assumed, NG3) or not at all? — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

Not run for this draft. The design leans on FEAT-732's own cross-checked decisions
(explicit collector, stable enum ids, cap-before-merge); the one genuinely new decision
is Q2, and it is stated as an open question rather than settled here.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-24 | Juan Ruffato | Draft written against `origin/dev` @ `e3d2d3734`; no Feature ID reserved |
