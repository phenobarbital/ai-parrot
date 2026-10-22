---
type: feature
base_branch: dev
projects: [parrot-formdesigner]
tags: [formbuilder, llm-validation, plausibility, security, rate-limit]
---

# Feature Specification: FormBuilder LLM-validation enforcement policy + LLM quota

**Feature ID**: FEAT-728
**Date**: 2026-10-22
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.3.0

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-649 gave FormBuilder an LLM answer-plausibility layer
(`AnswerPlausibilityChecker`, `services/plausibility.py`) wired into the shared
`SubmissionPipeline`. On every non-voice channel that verdict is **purely
advisory**: a submission whose answers the model judged implausible
(`plausible=false`, or `confidence < LLMValidationConfig.threshold`) is still
persisted and answered `200`, with the report merely attached to the stored
record (`context["llm_validation"]`, `submission_pipeline.py:195-199`) and
echoed in the response body (`handlers.py:1810`). Only the audio channel acts
on it, by flagging the field and entering `Phase.REVIEW`
(`audio/engine.py:969-979`). `LLMValidationConfig.on_error` does **not** help:
it governs LLM *unavailability* only (`skip | block` → `503
PLAUSIBILITY_UNAVAILABLE`), never an implausible answer.

So a form owner who turns the feature on to keep junk out of their sink gets a
column of verdicts, not enforcement. The enforcement they expect has to be
re-implemented by every consumer of every sink, per channel.

The same layer also carries an open security gap. Public forms
(`is_public=True`) have five URLs registered as auth-exempt in navigator-auth
(`services/public_forms.py:13-52`), two of which reach the LLM:

- `POST …/forms/{form_uid}/validate` — mounted `tenant="public"`
  (`api/routes.py:417-420`); `?llm_validation=true` (or `llm_validation: true`
  in the body, `handlers.py:1157-1159`) runs one LLM call per request. This is
  ledger issue `44941ecac8cc` (`vulnerability`, minor, open).
- `POST …/forms/{form_uid}/data` — also mounted `tenant="public"`
  (`api/routes.py:426-429`), and here the check needs **no opt-in at all**: the
  handler attaches a checker whenever the form enables `llm_validation` on any
  field (`handlers.py:262-281`), so every anonymous submit spends an LLM call.
  The ledger issue does not mention this path; it was found while auditing this
  feature and is in scope here.

Neither path has a quota. There is no shared rate-limit facility in the
workspace to lean on (nearest prior art: the in-process sliding window
`_RateLimiter` in `packages/ai-parrot-server/src/parrot/handlers/voice_broadcast.py:149`).

### Goals

- A per-form enforcement policy `on_implausible: annotate | review | reject`
  on `LLMValidationConfig`, evaluated **inside `SubmissionPipeline`** so every
  channel inherits one rule.
- `annotate` is the default and is byte-for-byte today's behaviour — every
  existing form keeps working untouched.
- `review` on HTTP/A2UI: nothing stored; a `422`-class reply carrying the
  per-field verdicts, which the client clears by re-submitting with an explicit
  reconfirmation flag.
- `reject`: nothing stored, and no flag can override it.
- Audio keeps exactly today's `REVIEW` semantics under `annotate`/`review`.
- Close ledger `44941ecac8cc`: the LLM opt-in on the public `/validate` is
  ignored for unauthenticated callers, and **every** LLM-backed form call —
  public submit included — passes a sliding-window quota that answers `429`
  with `Retry-After` when exhausted.
- No LLM call is ever added to a submission that already fails deterministic
  validation, and sensitive/excluded field types stay out of the check.

### Non-Goals (explicitly out of scope)

- Judging factual correctness. The system prompt forbids it
  (`plausibility.py:160-164`) and this feature does not change that: the gate
  acts on pertinence verdicts only.
- A per-field policy override. The policy is form-level; the existing per-field
  `field.llm_validation` opt-in keeps deciding *what* is checked, the policy
  decides *what is done* — uniformly. (See §8 Q1.)
- A "held / pending submission" state. Reviewed in §3's design round and
  rejected: it would need a new status on `FormSubmission`, in every
  autonomous-persistence sink, and in the admin UI.
- A Redis-backed quota. The backend is a `Protocol` so one can be added later;
  this feature ships the in-process implementation only.
- Re-opening `on_error`. LLM-unavailability semantics (`skip`/`block`, `503`)
  are unchanged.

---

## 2. Architectural Design

### Overview

One pure classifier, one gate, one quota.

**The classifier** (`core/llm_validation.py`) answers "which answers trip the
gate?" from a `PlausibilityReport` alone — the report already carries the
`threshold` the checker used (`plausibility.py:205-207`), so the function needs
no config and no I/O. A report whose `status` is not `"ok"` flags nothing, which
keeps `skipped`/`blocked` reports on their existing paths.

**The gate** lives in `SubmissionPipeline` as `gate_for()`, a pure method that
turns `(form policy, report, ack)` into either `None` (pass) or an
`ImplausibleSubmission` exception instance. `submit()` raises it after the
plausibility step and **before** persistence, metadata enrichment, forward and
`onAfterSubmit`; `validate()`'s caller uses the same method to make the dry-run
agree with the commit. Because every channel already funnels through this
pipeline (FEAT-649 Module 9), HTTP, A2UI, Teams and audio inherit the rule
without per-channel logic.

Policy semantics, with `flagged = implausible_fields(report)`:

| Policy | `flagged` empty | `flagged` non-empty, no ack | `flagged` non-empty, ack |
|---|---|---|---|
| `annotate` (default) | store, 200 | store, 200 — *today's behaviour* | store, 200 |
| `review` | store, 200 | **refuse**, `PLAUSIBILITY_REVIEW` | store, 200 (ack recorded) |
| `reject` | store, 200 | **refuse**, `PLAUSIBILITY_REJECTED` | **refuse** — ack never bypasses |

The reconfirmation flag is read exactly where `llm_validation` is read today —
popped off the body before visit-context extraction so it can never be judged as
an undeclared field (`handlers.py:1155-1160`).

**Audio parity falls out of the same rule.** `_do_submit` only reaches `Submit`
after the user confirmed the REVIEW turn, so it passes `plausibility_ack=True`
(`api/audio_ws.py:1192-1203`); `annotate` and `review` therefore behave exactly
as today, while `reject` still refuses and surfaces as an `IOFailed`.

**The quota** (`services/llm_quota.py`) is a server-side object — never
tenant-authored schema, so a form cannot raise its own limit. It keys a sliding
window on `{tenant}:{form_uid}:{identity}`, where `identity` is the
authenticated user id when there is a session and the client IP otherwise, and
is consulted immediately before any LLM call on both public-reachable paths.
Exhaustion is deliberately **not** uniform:

- policy `annotate` → the check is skipped (`status="skipped"`,
  `reason="rate_limited"`) and the submission proceeds, because under `annotate`
  the verdict never changed the outcome anyway;
- policy `review`/`reject` → `429` + `Retry-After`, nothing stored. Failing
  closed is the point: otherwise an attacker burns the quota and then walks
  garbage past a `reject` gate.
- `/validate` with the LLM opt-in → `429` + `Retry-After` regardless of policy.

For an unauthenticated caller the `/validate` opt-in is **ignored** rather than
refused: the response still comes back `200`/`422` as today, carrying
`plausibility: {"status": "skipped", "reason": "unauthenticated_opt_in"}`, so a
public renderer that always sends the flag keeps working and spends nothing. A
`403` was considered and rejected (§7).

### Component Diagram

```
HTTP / A2UI (handlers.validate, handlers.submit_data)
Audio (audio_ws._do_submit)                    Teams (renderer → submit)
        │                   │                        │
        └───────────────────┴────────────────────────┘
                            ▼
                   SubmissionPipeline
     ┌──────────────────────┼────────────────────────────────┐
     │ 1 onBeforeSubmit     │ 2 FormValidator (422)          │
     │ 3 unknown-fields     │ 4 LLMQuota.acquire() ──────────┼──→ 429 / skip
     │ 5 AnswerPlausibilityChecker.check()                   │
     │ 6 gate_for() ──→ ImplausibleSubmission (422 class) ───┼──→ review / reject
     │ 7 metadata · 8 persist · 9 forward · 10 onAfterSubmit │
     └───────────────────────────────────────────────────────┘
                            │
      implausible_fields(report)  ← pure, core/llm_validation.py
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `LLMValidationConfig` | extends | new `on_implausible` field, default `"annotate"` (`core/llm_validation.py:28`) |
| `SubmissionPipeline.submit()` | modifies | new `plausibility_ack` kwarg; raises `ImplausibleSubmission` (`services/submission_pipeline.py:119`) |
| `FormAPIHandler.validate()` | modifies | auth gate on the opt-in, quota, gate mapping (`api/handlers.py:1157`) |
| `FormAPIHandler.submit_data()` | modifies | reads ack, maps the new exception (`api/handlers.py:1767`) |
| `a2ui_wire.validation_errors()` | uses | reuses the existing A2UI per-field 422 envelope (`api/a2ui_wire.py:222`) |
| `AudioFormWS._do_submit()` | modifies | passes `plausibility_ack=True`, maps the new exception (`api/audio_ws.py:1192`) |
| `setup_form_api()` | extends | new `llm_quota` kwarg; default instance built when omitted (`api/routes.py:213`) |
| `AnswerPlausibilityChecker` | unchanged | the checker itself is not touched |

### Data Models

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py
class LLMValidationConfig(BaseModel):
    enabled: bool = False
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    on_error: Literal["skip", "block"] = "skip"
    on_implausible: Literal["annotate", "review", "reject"] = "annotate"   # NEW
    model: str | None = None
    timeout_s: float = Field(default=8.0, gt=0.0)
    max_fields: int = Field(default=50, ge=1)
    exclude_field_types: list[FieldType] = Field(default_factory=lambda: list(_DEFAULT_EXCLUDED))


# packages/parrot-formdesigner/src/parrot_formdesigner/services/llm_quota.py
class QuotaDecision(BaseModel):
    allowed: bool
    retry_after_s: int = 0
```

### New Public Interfaces

```python
from parrot_formdesigner.core.llm_validation import implausible_fields
from parrot_formdesigner.services.submission_pipeline import ImplausibleSubmission
from parrot_formdesigner.services.llm_quota import LLMQuota, LLMQuotaBackend, QuotaDecision
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: policy field + classifier | yes | field name/type/default fixed; `implausible_fields()` signature, sort order and `status != "ok"` → `[]` rule fixed | — |
| M2: pipeline gate | yes | `ImplausibleSubmission` attributes and `code` values fixed; `gate_for()` signature fixed; gate placed between the plausibility step and metadata enrichment; `onError` dispatched for `reject` only | — |
| M3: HTTP + A2UI surfacing | yes | response JSON keys, status codes and the ack flag's two spellings fixed; A2UI reuses `validation_errors()` | — |
| M4: LLM quota | no | the limiter is new code: eviction policy under adversarial key growth and the exact `identity()` fallback order are decisions the implementer must not re-open, but the pool/eviction interaction needs the thinking model's sign-off at review | — |
| M5: audio parity | yes | one kwarg plus one `except` branch; new `IOFailed` code fixed | — |
| M6: docs | yes | file path and required sections fixed | — |

### Module 1: Enforcement policy + pure classifier
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py`
- **Responsibility**: declare `on_implausible` and answer which fields trip the gate, with no I/O and no config lookup.
- **Depends on**: existing `PlausibilityReport` / `PlausibilityVerdict`
- **Interface Skeleton**:
  ```python
  # core/llm_validation.py  (modifies core/llm_validation.py:28)
  class LLMValidationConfig(BaseModel):              # verified: core/llm_validation.py:28
      """Per-form LLM plausibility settings (``FormSchema.llm_validation``)."""
      on_implausible: Literal["annotate", "review", "reject"] = "annotate"
      """What to do with an implausible answer. ``annotate`` (default) stores it
      with the verdict attached — FEAT-649 behaviour; ``review`` refuses the
      submission until the client reconfirms; ``reject`` always refuses."""

  def implausible_fields(report: PlausibilityReport) -> list[str]:
      """Field ids whose verdict trips the gate, sorted for determinism.

      A field trips when ``not verdict.plausible`` or
      ``verdict.confidence < report.threshold`` — the threshold travels on the
      report itself (set by ``AnswerPlausibilityChecker.check``,
      verified: services/plausibility.py:205-207), so no config is needed.

      Returns ``[]`` for any report whose ``status`` is not ``"ok"``: a
      ``skipped`` or ``blocked`` report must stay on its existing path
      (``on_error``), never on the gate's.
      """
  ```

### Module 2: Pipeline gate
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py`
- **Responsibility**: own the policy decision for every channel; refuse before anything is written.
- **Depends on**: Module 1
- **Interface Skeleton**:
  ```python
  # services/submission_pipeline.py  (modifies services/submission_pipeline.py:38, :119)
  __all__ = [
      "SubmissionPipeline", "SubmitOutcome", "SubmitSinkError", "ValidationFailed",
      "PlausibilityBlocked", "ImplausibleSubmission",          # verified: submission_pipeline.py:38
  ]

  class ImplausibleSubmission(Exception):
      """Gate refusal (422 class): answers flagged under a non-``annotate`` policy.

      Sibling of ``ValidationFailed`` (verified: submission_pipeline.py:55) and
      carries the same ``errors`` dict shape, so a client that already renders
      per-field validation errors renders these too.
      """

      def __init__(
          self,
          *,
          policy: Literal["review", "reject"],
          fields: list[str],
          report: PlausibilityReport,
      ) -> None:
          """``errors`` is derived here: ``{field_id: [verdict.reason or default]}``."""

      policy: Literal["review", "reject"]
      fields: list[str]
      report: PlausibilityReport
      errors: dict[str, list[str]]

      @property
      def code(self) -> str:
          """``"PLAUSIBILITY_REVIEW"`` for ``review``, ``"PLAUSIBILITY_REJECTED"`` for ``reject``."""

  class SubmissionPipeline:
      def gate_for(
          self, form: FormSchema, report: PlausibilityReport | None, *, ack: bool = False
      ) -> ImplausibleSubmission | None:
          """The gate decision for one report — pure, no I/O, safe to call twice.

          Returns ``None`` when the submission may proceed: no report, a report
          that flagged nothing, policy ``annotate``, or policy ``review`` with
          ``ack=True``. Returns the exception to raise otherwise; ``ack`` never
          clears ``reject``.
          """

      async def submit(
          self,
          form: FormSchema,
          data: dict[str, Any],
          *,
          tenant: str | None,
          user_id: str | None,
          locale: str,
          context: dict[str, Any] | None,
          extra_data: dict[str, Any] | None,
          auth_context: AuthContext | None,
          merge_session_id: str | None,
          plausibility: PlausibilityReport | None = None,
          plausibility_ack: bool = False,                      # NEW
          request: "web.Request | None" = None,
          visit_context: dict[str, Any] | None = None,
          submission_id: str | None = None,
      ) -> SubmitOutcome:
          """Commit step. Raises ValidationFailed, SubmitSinkError, PlausibilityBlocked,
          ImplausibleSubmission or FormEventAbort.

          The gate runs right after the plausibility step
          (verified: submission_pipeline.py:187-189) and before metadata
          enrichment, so a refused submission touches no sink, no forwarder and
          no ``onAfterSubmit`` handler. ``onError`` is dispatched for ``reject``
          (it is a refusal, like ``ValidationFailed``) and NOT for ``review``
          (a controlled client round-trip, like ``FormEventAbort``).
          An acknowledged ``review`` records ``acknowledged: true`` inside
          ``context["llm_validation"]`` (verified: submission_pipeline.py:197-199).
          """
  ```

### Module 3: HTTP + A2UI surfacing
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
- **Responsibility**: read the ack flag, map the gate to the wire, keep the dry-run and the commit in agreement.
- **Depends on**: Module 2
- **Interface Skeleton**:
  ```python
  # api/handlers.py  (modifies api/handlers.py:1157, :1767)
  class FormAPIHandler:
      @staticmethod
      def _plausibility_ack(request: web.Request, body: Any) -> bool:
          """Read the reconfirmation flag from ``?plausibility_ack=true`` or a body
          ``plausibility_ack: true``, popping it from the body so it is never
          reported as an unknown field — exactly how ``llm_validation`` is handled
          (verified: api/handlers.py:1157-1159).
          """

      async def validate(self, request: web.Request) -> web.Response:
          """POST …/validate — unchanged contract, plus:

          * an unauthenticated caller's LLM opt-in is ignored; the reply carries
            ``plausibility: {"status": "skipped", "reason": "unauthenticated_opt_in"}``;
          * quota exhaustion → 429 + ``Retry-After``;
          * a tripped gate → 422 ``{"is_valid": false, "code": <exc.code>,
            "errors": <exc.errors>, "plausibility": …}`` (A2UI: the same 422 via
            ``a2ui_wire.validation_errors``, verified: api/a2ui_wire.py:222).
          """

      async def submit_data(self, request: web.Request) -> web.Response:
          """POST …/data — unchanged contract, plus the ack flag, the quota, and
          ``except ImplausibleSubmission`` → 422 with the shape above.
          """
  ```

### Module 4: LLM quota
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/llm_quota.py` *(new)*
- **Responsibility**: bound every LLM-backed form call per identity and form; stay swappable.
- **Depends on**: nothing in this spec (wired by Module 3 / `setup_form_api`)
- **Interface Skeleton**:
  ```python
  # services/llm_quota.py  (new)
  class QuotaDecision(BaseModel):
      """One limiter answer."""
      allowed: bool
      retry_after_s: int = 0

  class LLMQuotaBackend(Protocol):
      """Swap-in point for a shared (e.g. Redis) limiter — see §8 Q2."""
      async def acquire(self, key: str, *, limit: int, window_s: float) -> QuotaDecision: ...

  class InProcessSlidingWindow:
      """Per-key sliding window on ``time.monotonic()``, bounded by LRU eviction.

      Per-worker state: with N gunicorn workers the effective limit is N× the
      configured one (§7). ``max_keys`` caps adversarial key growth from
      anonymous IPs; the least-recently-used key is evicted when the cap is hit.
      """
      def __init__(self, *, max_keys: int = 4096) -> None: ...
      async def acquire(self, key: str, *, limit: int, window_s: float) -> QuotaDecision: ...

  class LLMQuota:
      """Server-side quota for LLM-backed form calls. Never read from form schema."""
      def __init__(
          self,
          backend: LLMQuotaBackend | None = None,
          *,
          enabled: bool = True,
          limit: int = 10,
          window_s: float = 60.0,
          trust_forwarded_for: bool = False,
      ) -> None: ...

      def identity(self, request: web.Request) -> str:
          """Authenticated user id when a navigator session is present
          (verified: api/handlers.py:576-580), else the client IP —
          ``X-Forwarded-For``'s first hop only when ``trust_forwarded_for``.
          """

      async def acquire(self, request: web.Request, *, tenant: str | None, form_uid: str) -> QuotaDecision:
          """Charge one LLM call to ``{tenant}:{form_uid}:{identity}``.
          Always ``allowed=True`` when ``enabled`` is False.
          """
  ```
  ```python
  # api/routes.py  (modifies api/routes.py:213)
  async def setup_form_api(
      app: web.Application,
      *,
      llm_quota: "LLMQuota | None" = None,      # NEW — a default instance is built when omitted
      ...,
  ) -> None:
      """… ``llm_quota`` bounds every LLM-backed form call; pass
      ``LLMQuota(enabled=False)`` to opt out. Published as
      ``app["llm_quota"]`` beside ``app["submission_pipeline"]``."""
  ```

### Module 5: Audio parity
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py`
- **Responsibility**: keep today's REVIEW semantics, and surface `reject` instead of swallowing it.
- **Depends on**: Module 2
- **Interface Skeleton**:
  ```python
  # api/audio_ws.py  (modifies api/audio_ws.py:1192)
  class AudioFormWS:
      async def _do_submit(self, ctx: "_ConnCtx", item: Submit) -> "InboundEvent":
          """Submit through the SubmissionPipeline … now with
          ``plausibility_ack=True``: reaching ``Submit`` means the user already
          confirmed the REVIEW turn, so ``annotate``/``review`` behave exactly as
          today. ``except ImplausibleSubmission`` → ``IOFailed(code=exc.code)``,
          added BEFORE the broad ``except Exception`` that would otherwise report
          it as ``SUBMIT_FAILED`` (verified: api/audio_ws.py:1208-1213).
          """
  ```

### Module 6: Documentation
- **Path**: `docs/formdesigner-llm-validation-enforcement.md` *(new)*
- **Responsibility**: the policy matrix, the wire shapes, the quota knobs, and the two documented gotchas (multi-worker quota, voice client-submit needing the ack).
- **Depends on**: Modules 1–5

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_on_implausible_defaults_to_annotate` | M1 | an existing form's config parses with `on_implausible == "annotate"` |
| `test_implausible_fields_flags_not_plausible` | M1 | `plausible=false` trips regardless of confidence |
| `test_implausible_fields_flags_below_threshold` | M1 | `confidence < report.threshold` trips; `== threshold` does not |
| `test_implausible_fields_empty_for_skipped_and_blocked` | M1 | non-`ok` status flags nothing |
| `test_gate_for_annotate_always_passes` | M2 | flagged fields + `annotate` → `None` |
| `test_gate_for_review_without_ack_raises` | M2 | returns `ImplausibleSubmission(code="PLAUSIBILITY_REVIEW")` with per-field `errors` |
| `test_gate_for_review_with_ack_passes` | M2 | `ack=True` → `None` |
| `test_gate_for_reject_ignores_ack` | M2 | `ack=True` still returns `code="PLAUSIBILITY_REJECTED"` |
| `test_submit_reject_stores_nothing` | M2 | no sink write, no forward, no `onAfterSubmit` |
| `test_submit_review_dispatches_no_on_error` | M2 | `onError` fires for `reject`, not for `review` |
| `test_submit_ack_records_acknowledged` | M2 | `context["llm_validation"]["acknowledged"] is True` |
| `test_quota_allows_under_limit` | M4 | `limit` calls pass, the next is denied with `retry_after_s > 0` |
| `test_quota_window_slides` | M4 | a monotonic-clock jump past `window_s` re-allows |
| `test_quota_identity_prefers_session_user` | M4 | session present → user id; absent → `request.remote` |
| `test_quota_forwarded_for_only_when_trusted` | M4 | `X-Forwarded-For` ignored unless `trust_forwarded_for` |
| `test_quota_evicts_lru_at_max_keys` | M4 | key map never exceeds `max_keys` |
| `test_quota_disabled_always_allows` | M4 | `enabled=False` short-circuits |

### Integration Tests

| Test | Description |
|---|---|
| `test_submit_review_422_then_ack_200` | the full client round-trip: 422 `PLAUSIBILITY_REVIEW` with verdicts, re-submit with `plausibility_ack=true` → 200 and stored |
| `test_submit_reject_422_never_stored` | `reject` refuses both with and without the ack flag; storage untouched |
| `test_annotate_low_confidence_keeps_200` | regression: today's behaviour survives (mirrors `TestValidateOptIn::test_low_confidence_keeps_200`) |
| `test_validate_dry_run_agrees_with_submit` | `/validate` returns the same code/errors the commit would |
| `test_validate_a2ui_review_envelopes` | A2UI surface gets per-field `error` envelopes + `updateDataModel` at 422 |
| `test_ack_flag_not_reported_as_unknown_field` | `plausibility_ack` in the body never lands in `extra_data` under `unknown_fields=reject` |
| `test_anonymous_validate_opt_in_ignored_no_llm_call` | unauthenticated `?llm_validation=true` → no LLM call, `reason="unauthenticated_opt_in"` |
| `test_authenticated_validate_opt_in_runs_once` | authenticated opt-in still works, one call, quota charged |
| `test_public_submit_quota_429_under_enforcing_policy` | quota exhausted + `review`/`reject` → 429 + `Retry-After`, nothing stored |
| `test_public_submit_quota_skips_under_annotate` | quota exhausted + `annotate` → 200, `status="skipped"`, `reason="rate_limited"` |
| `test_audio_review_confirm_still_submits` | voice REVIEW → confirm → stored, under `review` |
| `test_audio_reject_surfaces_io_failed` | voice + `reject` with a flagged answer → `IOFailed(code="PLAUSIBILITY_REJECTED")`, not `SUBMIT_FAILED` |

### Validation Contract

tests:
- packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py
- packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline_parity.py
- packages/parrot-formdesigner/tests/formdesigner/test_plausibility_enforcement.py
- packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_http.py
- packages/parrot-formdesigner/tests/formdesigner/test_audio_plausibility_policy.py
- packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_review_resume.py
- packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py
- packages/parrot-formdesigner/tests/unit/services/test_llm_quota.py
- packages/parrot-formdesigner/tests/unit/test_llm_validation_policy.py
- packages/parrot-formdesigner/tests/unit/test_core_models.py
- packages/parrot-formdesigner/tests/unit/api/test_submit_unknown_fields.py
- packages/parrot-formdesigner/tests/unit/api/test_validate_a2ui.py
- packages/parrot-formdesigner/tests/unit/api/test_submit_a2ui.py
- packages/parrot-formdesigner/tests/unit/api/test_setup_form_api.py
- packages/parrot-formdesigner/tests/unit/api/test_route_tenant_coverage.py
markers: none

### Test Data / Fixtures

```python
# Reuse the FEAT-649 harness verbatim — verified:
# packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py:25-60
#   class FakeLLM            — records ask(), returns a PlausibilityBatch or raises
#   def _form(cfg)           — one-field form carrying an LLMValidationConfig
#   def _request(body)       — MagicMock request (query, headers, json())
#   fixture make_handler     — FormAPIHandler with a FakeLLM + in-memory storage
# New fixtures needed:
@pytest.fixture
def frozen_clock(monkeypatch):
    """Monotonic clock the limiter tests advance by hand (no sleeps)."""

@pytest.fixture
def anon_request():
    """_request() variant with no ``session`` key — the public-form shape."""
```

---

## 5. Acceptance Criteria

- [ ] AC1 — `LLMValidationConfig.on_implausible` exists with the literal values `annotate | review | reject` and default `"annotate"`; a config dict written before this feature still validates.
- [ ] AC2 — `implausible_fields()` is pure (no I/O, no config argument), flags `not plausible` or `confidence < report.threshold`, returns `[]` for any report whose `status != "ok"`, and returns a sorted list.
- [ ] AC3 — With `on_implausible="annotate"`, every pre-existing behaviour is unchanged: implausible answers are stored, answered `200`, and the report still arrives in `context["llm_validation"]` and in the response body. `TestValidateOptIn::test_low_confidence_keeps_200` passes untouched.
- [ ] AC4 — `SubmissionPipeline.gate_for()` returns `None` for: no report, nothing flagged, `annotate`, or `review` with `ack=True`; and an `ImplausibleSubmission` otherwise. `ack=True` never clears `reject`.
- [ ] AC5 — A tripped gate raises **before** metadata enrichment, persistence, forwarding and `onAfterSubmit`: no sink write, no generic-storage write, no forward attempt, no `onAfterSubmit` dispatch.
- [ ] AC6 — `onError` is dispatched for a `reject` refusal and is **not** dispatched for a `review` refusal.
- [ ] AC7 — `POST …/data` answers `422` with `{"is_valid": false, "code": "PLAUSIBILITY_REVIEW"|"PLAUSIBILITY_REJECTED", "errors": {<field_id>: [<reason>]}, "plausibility": {…}}`; re-submitting with `plausibility_ack=true` (query or body) stores under `review` and still refuses under `reject`.
- [ ] AC8 — `plausibility_ack` is popped from the body before visit-context extraction and never appears in `extra_data`, including under `unknown_fields=reject`.
- [ ] AC9 — On an A2UI submit/validate the refusal is delivered through `a2ui_wire.validation_errors()` at `422`, one `error` envelope per flagged field plus the trailing `updateDataModel`.
- [ ] AC10 — `POST …/validate` reports the same `code`/`errors` the commit would produce for the same payload and policy.
- [ ] AC11 — An unauthenticated caller's `llm_validation` opt-in on `/validate` performs **zero** LLM calls and the reply carries `plausibility.status == "skipped"` with `reason == "unauthenticated_opt_in"`; an authenticated caller's opt-in still runs exactly one call.
- [ ] AC12 — Every LLM-backed path (public submit included) charges `LLMQuota.acquire()` before the call. Exhaustion gives `429` + `Retry-After` under `review`/`reject` and on the `/validate` opt-in, and a skipped report (`reason="rate_limited"`) + `200` under `annotate`. Nothing is stored on a `429`.
- [ ] AC13 — `InProcessSlidingWindow` never holds more than `max_keys` keys and uses a monotonic clock (tests advance it; no `sleep`).
- [ ] AC14 — A form schema cannot influence the quota: `LLMQuota` reads only `setup_form_api` arguments, never `FormSchema`/`LLMValidationConfig`. `app["llm_quota"]` is published.
- [ ] AC15 — Audio: with `review` the REVIEW-then-confirm flow still stores (`plausibility_ack=True`); with `reject` a flagged answer yields `IOFailed(code="PLAUSIBILITY_REJECTED")`, never `SUBMIT_FAILED`.
- [ ] AC16 — No LLM call is made for a submission that fails deterministic validation, and `eligible_fields`' exclusions (sensitive, `read_only`, excluded types) are unchanged.
- [ ] AC17 — `docs/formdesigner-llm-validation-enforcement.md` documents the policy matrix, the wire shapes, the quota knobs, the multi-worker gotcha and the voice client-submit ack requirement.
- [ ] AC18 — Ledger `44941ecac8cc` is closed with `--resolved-by` pointing at this feature's merge commit.
- [ ] AC19 — `ruff check` clean on every touched file; the Validation Contract above passes.

---

## 6. Codebase Contract

> Verified against `932cf8fdc` (dev, 2026-10-22).

### Verified Imports

```python
from parrot_formdesigner.core.llm_validation import (          # verified: core/__init__.py:60-64
    LLMValidationConfig,                                        # verified: core/llm_validation.py:28
    PlausibilityReport,                                         # verified: core/llm_validation.py:62
    PlausibilityVerdict,                                        # verified: core/llm_validation.py:39
    llm_validation_enabled,                                     # verified: core/llm_validation.py:73
)
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection   # verified: core/schema.py:152, :491
from parrot_formdesigner.core.types import FieldType            # verified: core/llm_validation.py:13
from parrot_formdesigner.core.voice import is_sensitive         # verified: services/plausibility.py:24
from parrot_formdesigner.core.voice_answer import unwrap_voice  # verified: services/submission_pipeline.py:20
from parrot_formdesigner.services.plausibility import (
    AnswerPlausibilityChecker,                                  # verified: services/plausibility.py:169
    PlausibilityBlocked,                                        # verified: services/plausibility.py:49
    PlausibilityBatch,                                          # verified: services/plausibility.py:41
    eligible_fields,                                            # verified: services/plausibility.py:84
)
from parrot_formdesigner.services.submission_pipeline import (
    SubmissionPipeline,                                         # verified: services/submission_pipeline.py:72
    SubmitOutcome,                                              # verified: services/submission_pipeline.py:41
    SubmitSinkError,                                            # verified: services/submission_pipeline.py:63
    ValidationFailed,                                           # verified: services/submission_pipeline.py:55
)
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage  # verified: services/submission_pipeline.py:26
from parrot_formdesigner.services.auth_context import AuthContext   # verified: services/auth_context.py:21
from parrot_formdesigner.api import a2ui_wire                   # verified: api/handlers.py:1180-1183
from parrot_formdesigner.api.routes import setup_form_api       # verified: api/routes.py:213
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py
class LLMValidationConfig(BaseModel):                    # line 28
    enabled: bool = False                                # line 31
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)  # line 32
    on_error: Literal["skip", "block"] = "skip"          # line 33
    model: str | None = None                             # line 34
    timeout_s: float = Field(default=8.0, gt=0.0)        # line 35
    max_fields: int = Field(default=50, ge=1)            # line 36
    exclude_field_types: list[FieldType]                 # line 37

class PlausibilityVerdict(BaseModel):                    # line 39
    plausible: bool                                      # line 42
    confidence: float = Field(ge=0.0, le=1.0)            # line 43
    reason: str                                          # line 44

class PlausibilityReport(BaseModel):                     # line 62
    status: Literal["ok", "skipped", "blocked"]          # line 65
    reason: str | None = None                            # line 66
    model: str | None = None                             # line 67
    threshold: float                                     # line 68
    latency_ms: int | None = None                        # line 69
    items: dict[str, PlausibilityVerdict]                # line 70

def llm_validation_enabled(form: FormSchema, field: FormField) -> bool:   # line 73

# packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py
class PlausibilityBlocked(Exception):                    # line 49
    reason: str                                          # line 53
class AnswerPlausibilityChecker:                         # line 169
    def __init__(self, client: "AbstractClient | None", *, config: LLMValidationConfig) -> None:  # line 172
    config: LLMValidationConfig                          # line 174
    async def check(self, form: FormSchema, scalars: dict[str, Any], *, locale: str,
                    fields: set[str] | None = None) -> PlausibilityReport:   # line 177
def eligible_fields(form: FormSchema, scalars: dict[str, Any], cfg: LLMValidationConfig, *,
                    only: set[str] | None = None) -> list[FormField]:        # line 84

# packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py
class SubmitOutcome(BaseModel):                          # line 41
    submission_id: str                                   # line 46
    stored_in: Literal["sink", "generic", "none"]        # line 47
    plausibility: PlausibilityReport | None = None       # line 51
    validation: ValidationResult                         # line 52
class ValidationFailed(Exception):                       # line 55
    errors: dict[str, Any]                               # line 60
class SubmissionPipeline:                                # line 72
    def _plausibility_enabled(self, form: FormSchema) -> bool:    # line 96
    async def validate(self, form, data, *, locale, auth_context,
                       llm_validation: bool = False, visit_context=None
                       ) -> tuple[ValidationResult, PlausibilityReport | None]:   # line 100
    async def submit(self, form, data, *, tenant, user_id, locale, context, extra_data,
                     auth_context, merge_session_id, plausibility=None, request=None,
                     visit_context=None, submission_id=None) -> SubmitOutcome:    # line 119
    def attach_verdicts(self, data: dict[str, Any], report: PlausibilityReport | None) -> dict[str, Any]:  # line 324

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
class FormAPIHandler:
    def _get_llm_client(self) -> "AbstractClient | None":         # line 198
    def _build_submission_pipeline(self, form: FormSchema | None = None) -> "SubmissionPipeline":  # line 262
    def _build_auth_context(self, request: web.Request) -> AuthContext:   # line 453
    def _extract_session_id(self, request) -> str | None:  # session read at line 577: `if "session" in request:`
    async def validate(self, request: web.Request) -> web.Response:      # opt-in at line 1157
    async def submit_data(self, request: web.Request) -> web.Response:   # pipeline built at line 1767

# packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py
def validation_errors(surface_id: str, errors: dict[str, list[str] | str]) -> list[dict[str, Any]]:  # line 222
def a2ui_response(envelopes, status: int = 200): ...   # verified in use: api/handlers.py:1181-1183

# packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py
class AudioFormWS:
    async def _do_submit(self, ctx: "_ConnCtx", item: Submit) -> "InboundEvent":   # line 1183
    def _pipeline_for(self) -> SubmissionPipeline                                   # used at line 1192
    async def _do_client_submit(self, ctx, item) -> "InboundEvent":                 # validate-only, persists nothing

# packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py
def public_form_paths(form_uid: str, tenant: str, base_path: str = "/api/v1") -> list[str]:  # line 13
    # returns the five auth-exempt globs, including …/data and …/validate
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `implausible_fields()` | `PlausibilityReport.items` / `.threshold` | attribute read | `core/llm_validation.py:62-70` |
| `SubmissionPipeline.gate_for()` | `form.llm_validation.on_implausible` | attribute read | `core/schema.py:491` |
| gate raise site | the plausibility step in `submit()` | inserted directly after | `services/submission_pipeline.py:187-189` |
| ack recording | `ctx["llm_validation"]` | dict write | `services/submission_pipeline.py:197-199` |
| `_plausibility_ack()` | the `llm_validation` flag handling | same pop-before-extract pattern | `api/handlers.py:1155-1160` |
| 422 mapping (HTTP) | `ValidationFailed`'s 422 reply | sibling `except` branch | `api/handlers.py:1786-1787` |
| 422 mapping (A2UI) | `a2ui_wire.validation_errors()` | function call | `api/a2ui_wire.py:222` |
| `LLMQuota.identity()` | navigator session | `"session" in request` | `api/handlers.py:576-580` |
| quota charge (validate) | the opt-in branch | call before `pipeline.validate(...)` | `api/handlers.py:1157-1164` |
| quota charge (submit) | the checker attachment | call before `pipeline.submit(...)` | `api/handlers.py:1767-1769` |
| `app["llm_quota"]` | `setup_form_api` stash | `_stash_without_clobbering` | `api/routes.py:308-309` |
| audio ack | `_pipeline_for().submit(...)` | new kwarg | `api/audio_ws.py:1192-1203` |

### Does NOT Exist (Anti-Hallucination)

- ~~`LLMValidationConfig.on_implausible`~~ — this feature adds it; `on_error` (`core/llm_validation.py:33`) is a different knob and governs LLM unavailability only.
- ~~`parrot_formdesigner.services.llm_quota`~~ — new module in M4; there is **no** rate-limit facility anywhere in `parrot_formdesigner`.
- ~~`PlausibilityReport.flagged` / `.implausible`~~ — not fields on the model; flagging is computed by `implausible_fields()`.
- ~~`PlausibilityReport.status == "rejected"`~~ — the literal is only `"ok" | "skipped" | "blocked"` (`core/llm_validation.py:65`); the gate uses an exception, it does not add a status.
- ~~`AnswerPlausibilityChecker.enforce()`~~ / ~~`.threshold`~~ — the checker exposes `check()` and `config` only (`services/plausibility.py:169-177`).
- ~~`FormField.llm_validation_policy`~~ — no per-field policy (Non-Goal); only `field.llm_validation: bool | None` exists (`core/schema.py:153`).
- ~~`AuthContext.is_authenticated`~~ / ~~`.user_id`~~ — `AuthContext` carries *outbound* credentials (`scheme/token/headers/claims`, `services/auth_context.py:40-44`); it says nothing about whether the caller is authenticated.
- ~~`FormSubmission.status`~~ — no held/pending state exists (Non-Goal).
- ~~`parrot.handlers.voice_broadcast._RateLimiter`~~ — exists (`packages/ai-parrot-server/.../voice_broadcast.py:149`) but is private, in another distribution, and MUST NOT be imported; it is prior art to mirror, not a dependency.
- ~~`requests` / `httpx`~~ — banned repo-wide; `aiohttp` only.

### Edit Sites (Blueprint Anchors)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` | MODIFY | `    on_error: Literal["skip", "block"] = "skip"` | `core/llm_validation.py:33` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` | MODIFY | `def llm_validation_enabled(form: FormSchema, field: FormField) -> bool:` | `core/llm_validation.py:73` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` | MODIFY | `__all__ = ["SubmissionPipeline", "SubmitOutcome", "SubmitSinkError", "ValidationFailed", "PlausibilityBlocked"]` | `services/submission_pipeline.py:38` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` | MODIFY | `                plausibility = await self.plausibility.check(form, unwrap_voice(result.sanitized_data), locale=locale)` | `services/submission_pipeline.py:189` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` | MODIFY | `            stored_data = self.attach_verdicts(result.sanitized_data, plausibility)` | `services/submission_pipeline.py:195` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `        llm_opt_in = request.query.get("llm_validation", "").lower() == "true"` | `api/handlers.py:1157` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `            payload["plausibility"] = plausibility.model_dump(mode="json", exclude_none=True)` | `api/handlers.py:1186` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `        pipeline = self._build_submission_pipeline(form)` | `api/handlers.py:1767` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | 3 lines — the **submit** copy only: `        except PlausibilityBlocked as exc:` / `            return _reply(` / `                {"error": f"Answer plausibility check unavailable: {exc.reason}", "code": "PLAUSIBILITY_UNAVAILABLE"},` | `api/handlers.py:1789-1791` | 2 (bare line; the `/validate` copy is at `:1166` and returns `JSONResponse`, not `_reply`) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `            body_out["plausibility"] = outcome.plausibility.model_dump(mode="json", exclude_none=True)` | `api/handlers.py:1810` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | `        _wrap_auth(handler.validate, tenant="public"),` | `api/routes.py:419` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | `        _wrap_auth(handler.submit_data, tenant="public"),` | `api/routes.py:428` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` | MODIFY | `            outcome = await self._pipeline_for().submit(` | `api/audio_ws.py:1192` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/llm_quota.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/tests/formdesigner/test_plausibility_enforcement.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_http.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_plausibility_policy.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/tests/unit/services/test_llm_quota.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/tests/unit/test_llm_validation_policy.py` | CREATE | — | — | — |
| `docs/formdesigner-llm-validation-enforcement.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Pydantic v2 for every model; `Literal[...]` for the policy, never a bare `str`.
- Async-first; the limiter uses `time.monotonic()` and an `asyncio.Lock`, never `time.sleep`.
- `self.logger` only — never `print`. Never log answer values: the plausibility
  code deliberately logs only exception *types*
  (`services/plausibility.py:196-197`); keep that discipline, verdict reasons
  included.
- `aiohttp` only (`requests`/`httpx` are banned, enforced by ruff TID251).
- Minimal diffs: the gate is one pure method plus one raise site. Do not
  restructure `submit()`'s try/except, and do not touch
  `AnswerPlausibilityChecker`.
- New exception goes in `__all__`; `PlausibilityBlocked` is already re-exported
  from the pipeline module (`services/submission_pipeline.py:38`) — mirror that.

### Known Risks / Gotchas

- **Per-worker quota.** `InProcessSlidingWindow` state lives in one gunicorn
  worker, so N workers allow up to N× the configured limit. Accepted for v1 and
  documented; the `LLMQuotaBackend` Protocol is the seam for a shared backend.
- **Proxies collapse identities.** Behind a reverse proxy every anonymous
  `request.remote` is the proxy's IP, turning the per-identity bucket into a
  per-form global bucket. Hence `trust_forwarded_for` — off by default, because
  trusting a client-settable header would let an attacker mint unlimited
  identities. Document both failure directions.
- **Unbounded key growth** is the limiter's own attack surface: anonymous IPs
  are attacker-chosen. `max_keys` + LRU eviction is mandatory, not an
  optimization.
- **The broad `except Exception` in `_do_submit`** (`api/audio_ws.py:1208-1213`)
  will swallow `ImplausibleSubmission` into `SUBMIT_FAILED` unless the new
  branch is added *above* it. Same hazard in `_do_client_submit`'s
  `except Exception`.
- **Voice client-submit mode** persists nothing (`_do_client_submit`) and hands
  the data to the client, which then POSTs `…/data` itself. Under `review` that
  POST must carry `plausibility_ack=true` or it will be refused even though the
  user already reconfirmed by voice. Documentation-only in this feature — the
  client already receives `plausibility_summary`; no wire change to the
  audio-form-client-submit contract.
- **Dry-run / commit drift.** `/validate` and `/data` must call the same
  `gate_for()`. If one of them re-implements the comparison, a client can be
  told `200` and then refused — the exact class of bug AC10 exists to catch.
- **`threshold` comparison is strict `<`.** `confidence == threshold` passes.
  This mirrors the audio engine (`audio/engine.py:975`); diverging would make
  voice and HTTP disagree on the same verdict.
- **Rejected alternative: `403` for the anonymous opt-in.** It would break
  public renderers that always send `llm_validation=true` and turn a cost
  problem into an availability one. Ignoring the flag with an explicit
  `reason="unauthenticated_opt_in"` costs nothing and stays self-documenting.
- **Rejected alternative: quota keyed on form only.** One abusive IP would then
  deny a whole public form's legitimate traffic.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | No new dependency. `pydantic`, `aiohttp` and stdlib `collections`/`time` are already in `parrot-formdesigner`. |

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-728
  (`.claude/worktrees/feat-FEAT-728-formbuilder-llm-validation-enforcement`,
  created from `origin/dev` by the implementing lane); the `sdd-coder` engine
  gives each task its own sub-worktree inside it.
- **Module dependency graph** (evidence in parentheses):
  - M2 → M1 — the gate imports `implausible_fields` and reads
    `on_implausible` (`core/llm_validation.py`).
  - M3 → M2 — the handlers catch `ImplausibleSubmission` and call `gate_for()`.
  - M5 → M2 — the audio path passes the new `plausibility_ack` kwarg and
    catches the same exception.
  - M4 → none — the quota is standalone code; only its *wiring* touches
    `api/handlers.py` and `api/routes.py`.
  - M6 → M1–M5 — documentation lands last.
  - M1 and M4 have no edge between them and are expected to run concurrently.
- **Shared files** (their tasks serialize):
  - `api/handlers.py` — M3 (gate mapping, ack flag) and M4 (quota wiring).
  - No other file is touched by more than one module.
- **Exclusive resources**: none. No extension rebuild, no lockfile change, no
  migration — the feature adds one module, one Pydantic field and five edit
  sites, so every task is `parallel: true` except the `api/handlers.py` pair
  above.
- **Cross-feature dependencies**: none. FEAT-649 is merged (per-spec index
  `sdd/tasks/index/audio-form-interaction-workflow.json`, 27/27 `done`,
  completed 2026-10-11), which is this feature's entire substrate.

---

## 8. Open Questions

- [x] How should `review` surface on HTTP/A2UI? — *Resolved by the user, 2026-10-22*: a `422`-class reply carrying the per-field verdicts and a `PLAUSIBILITY_REVIEW` code, nothing stored; the client clears it by re-submitting with an explicit reconfirmation flag. The "held/pending submission" variant was rejected for the storage/sink/admin-UI surface it would add.
- [x] Which answers trip the gate? — *Resolved by the user, 2026-10-22*: any eligible field with `plausible=false` or `confidence < threshold`, matching what the voice engine already flags (`audio/engine.py:975`).
- [x] How is the public-endpoint gap closed? — *Resolved by the user, 2026-10-22*: require auth for the LLM opt-in **and** a sliding-window limiter over every LLM-backed path, public submit included, answering `429` + `Retry-After`.
- [x] Where does limiter state live? — *Resolved by the user, 2026-10-22*: in-process, behind a `Protocol` extension point so a Redis backend can be added later without respecifying.
- [x] Q1 — Is the policy per-form only, or overridable per field? — *Assumption stated by Claude and accepted, 2026-10-22*: per-form only. `field.llm_validation` keeps deciding *what* is checked; the policy decides *what is done*, uniformly. Revisit only if a real form needs mixed strictness.
- [ ] Q2 — Default quota values: `limit=10` per `window_s=60` per `{tenant, form_uid, identity}` is a guess, not a measurement. Confirm against a real public form's traffic before release, and decide whether authenticated callers deserve a higher limit than anonymous ones. — *Owner: Jesus Lara*
- [ ] Q3 — Should `reject` also be enforced for the voice channel's `on_error="block"` + `PLAUSIBILITY_UNAVAILABLE` path, where today the engine re-asks instead of refusing? Out of scope here (the gate only acts on `status == "ok"` reports), but the two policies now coexist and the interaction deserves a decision. — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec).
> Model: `n/a` · Status: skipped (no exploration document — this spec was authored
> directly from a code audit of the FEAT-649 surface, with its four design
> decisions taken interactively with the user; §3b's precondition requires an
> `accepted` brainstorm/proposal or an intake run, neither of which exists)
> · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.
