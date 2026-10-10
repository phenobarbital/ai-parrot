# TASK-4222: SubmissionPipeline: behaviour-preserving extraction of the submit tail + plausibility step + envelope unwrap/rewrap

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4210, TASK-4220, TASK-4221
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9, goal G8, AC9. Today the audio WS bypasses `FormAPIHandler.submit_data`
(no FEAT-457 sinks, no FEAT-188 events, no forwarder, tenant lost). This task creates ONE
`SubmissionPipeline` that HTTP, A2UI and audio all call: validator → plausibility → FormSubmission
→ metadata enrichment → sink-exclusive | generic storage → forwarder → partial cleanup →
`onAfterSubmit`. It is a **behaviour-preserving extraction** of `api/handlers.py` ~:1665-1941;
the handler is NOT rewired here (TASK-4224 does that), so the parity suite of TASK-4221 stays the
oracle. This module is NOT delegation-eligible (spec §3 table): FEAT-457 sink exclusivity,
FEAT-188 event ordering and FEAT-544 A2UI envelopes must be preserved exactly.

---

## Scope

- Create `services/submission_pipeline.py` with `SubmitOutcome`, `ValidationFailed`,
  `SubmitSinkError`, `SubmissionPipeline` (`validate()` = prepare step, `submit()` = commit step).
- Move — not re-invent — the logic of `submit_data` from `onBeforeSubmit` (:1666) to the 200
  composite (:1941): onBeforeSubmit dispatch, validate, unknown-fields policy (FEAT-458), outbound
  build, `FormSubmission`, metadata enrichment, persistence (sink-exclusive or generic), forwarder,
  partial cleanup, onAfterSubmit, and the outer onError-then-reraise envelope.
- Insert the plausibility step after a passing validation: run `AnswerPlausibilityChecker.check()`
  on `unwrap_voice(sanitized_data)` when the form enables `llm_validation` and no report was passed
  in; persist the report in `FormSubmission.context["llm_validation"]`; attach each item's verdict
  to its spoken envelope (`VoiceEvidenceEnvelope.plausibility`). `PlausibilityBlocked` propagates
  (nothing stored).
- Envelope handling: validate on `unwrap_voice(data)`-compatible values (the validator learns
  envelopes in TASK-4223; the pipeline passes `data` through unchanged to `FormValidator.validate`).
- Write `test_submission_pipeline.py` (pipeline called directly, fakes for every collaborator).

**NOT in scope**: changing `api/handlers.py` / `api/routes.py` (TASK-4224); the A2UI unwrap/reply
shaping (stays in the handler); `?merge_partials` loading (stays in the handler — the pipeline only
receives `merge_session_id` for cleanup); `FormValidator` changes (TASK-4223); audio engine wiring
(TASK-4226/4227).

**Stale-branch check (spec Worktree Strategy)**: `origin/claude/form-submission-metadata-TYH8Z`
(2026-05-18) was verified at task-write time to be fully contained in `origin/dev` (its tip is
the merge-base `96e88d46d`). Re-run `git merge-base --is-ancestor origin/claude/form-submission-metadata-TYH8Z origin/dev`
before landing; if it is no longer an ancestor, stop and report.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` | CREATE | Shared validate/commit pipeline |
| `packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline.py` | CREATE | Unit tests calling the pipeline directly |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.events import FormEventAbort                      # imported at api/handlers.py:20
from parrot_formdesigner.core.schema import FormSchema, UnknownFieldsPolicy     # core/schema.py:401 ; UnknownFieldsPolicy imported at api/handlers.py:1543
from parrot_formdesigner.services.auth_context import AuthContext               # services/auth_context.py:20
from parrot_formdesigner.services.event_dispatcher import dispatch              # services/event_dispatcher.py:102
from parrot_formdesigner.services.metadata_enricher import MetadataResolutionError, enrich_submission   # imported at api/handlers.py:1544-1547 ; def :47
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage   # services/submissions.py:50, :122
from parrot_formdesigner.services.unknown_fields import ExtrasCapExceeded, enforce_extras_cap  # imported at api/handlers.py:1549
from parrot_formdesigner.services.validators import FormValidator, ValidationResult          # services/validators.py:200, :160
from parrot_formdesigner.services.sinks.base import SinkNotCapableError, SinkTargetMismatchError, SinkUnavailableError  # sinks/base.py:41, :50, :32
from parrot_formdesigner.services.sinks.mapper import flatten_submission, nest_submission     # sinks/mapper.py:142 ; nest used api/handlers.py:1853
# TYPE_CHECKING only:
from parrot_formdesigner.services.forwarder import SubmissionForwarder           # services/forwarder.py:36
from parrot_formdesigner.services.partial_saves import PartialSaveStore          # services/partial_saves.py:24
from parrot_formdesigner.services.sinks.factory import SinkFactory               # TYPE_CHECKING import at api/handlers.py:103
from aiohttp import web                                                           # web.Request for dispatch/enrich
```

#### Provided by dependency tasks (do not exist yet)
```python
from parrot_formdesigner.core.voice_answer import VoiceEvidenceEnvelope, is_voice_envelope, unwrap_voice   # TASK-4210
from parrot_formdesigner.core.llm_validation import PlausibilityReport, llm_validation_enabled            # TASK-4209
from parrot_formdesigner.services.plausibility import AnswerPlausibilityChecker, PlausibilityBlocked      # TASK-4220
```

### Existing Signatures to Use
```python
# services/event_dispatcher.py:102
async def dispatch(event, *, form, request: web.Request, tenant: str | None, auth_context: Any,
                   payload=None, schema_dump=None, error=None) -> EventResolution
#   docstring: "the dispatcher itself does not read [request]" — handlers may; pass the real request when one exists.
# services/metadata_enricher.py:47
async def enrich_submission(*, request: "web.Request", form, submission, answers: dict, auth_context) -> tuple[dict, dict]
# services/validators.py:221
async def validate(self, form, data, *, locale="en", auth_context=None, location_vars=None, visit_context=None) -> ValidationResult
# services/submissions.py:50 FormSubmission(submission_id, form_uid, form_id, form_version, data, is_valid, created_at,
#   tenant: str|None, user_id: str|None, locale: str|None, context: dict|None, extra_data: dict|None, ...)
# services/submissions.py:313 async def store(self, submission, *, tenant: str | None = None) -> str
# services/forwarder.py:61 async def forward(self, data: dict[str, Any], submit_action: SubmitAction) -> ForwardResult(success, status_code, error)
# services/partial_saves.py:145 async def delete(self, form_id: str, session_id: str) -> bool
# sink protocol (api/handlers.py:1850-1858): sink = await sink_factory.get(form, tenant=tenant);
#   await sink.ensure_target(form); payload = nest_submission(form, s) if sink.family == "document" else flatten_submission(form, s);
#   await sink.write(submission, payload)
# Status mapping today (api/handlers.py:1859-1870): SinkUnavailableError → 503 + {"Retry-After": "30"};
#   SinkTargetMismatchError → 422; SinkNotCapableError → 501 — each after a best-effort onError dispatch.
```

### Does NOT Exist
- ~~`services/submission_pipeline.py`~~, ~~`SubmissionPipeline`~~, ~~`SubmitOutcome`~~, ~~`ValidationFailed`~~ — created here.
- ~~`ValidationResult.plausibility`~~ — the report is returned beside the result, never inside it.
- ~~A request-free `dispatch()`~~ — `request` is a required keyword; see Deviations below.
- ~~`FormSubmission.llm_validation`~~ — the report goes in `context["llm_validation"]`.
- ~~`SinkFactory` constructed by the pipeline~~ — it is injected.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler.submit_data",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/event_dispatcher.py#dispatch",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/metadata_enricher.py#enrich_submission",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#FormValidator.validate",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py#FormSubmission",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py#FormSubmissionStorage.store",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/forwarder.py#SubmissionForwarder.forward",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py#PartialSaveStore.delete",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py#flatten_submission",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py#nest_submission"
  ]
}
```

---

## Implementation Notes

### Deviations from the spec skeleton (forced by verified code — record them in the Completion Note)
The spec's `SubmissionPipeline.__init__`/`submit()` skeleton omits three collaborators the real
submit tail needs. Add them as **keyword-only, defaulted** parameters (additive, so the skeleton's
calls stay valid):
1. `sink_factory: "SinkFactory | None" = None` on `__init__` — FEAT-457 sink-exclusive persistence
   needs it (`api/handlers.py:1846-1850`).
2. `request: "web.Request | None" = None` on `submit()` — `dispatch()` and `enrich_submission()`
   take a `request` (`event_dispatcher.py:102`, `metadata_enricher.py:47`). The HTTP handler passes
   its request; the audio adapter passes the WebSocket upgrade request.
3. `visit_context: dict[str, Any] | None = None` on `validate()`/`submit()` — forwarded to
   `FormValidator.validate(visit_context=...)` exactly as `submit_data` does (:1685).

### Key Constraints
- Preserve order exactly: onBeforeSubmit → validate (422 + onError) → unknown-fields (reject/keep/drop)
  → **plausibility** → FormSubmission → enrich (422 `_metadata` + onError) → persist → forward →
  partial cleanup → onAfterSubmit. Plausibility sits after every deterministic 422 so a
  deterministically invalid submission never costs an LLM call.
- `FormEventAbort` from onBeforeSubmit propagates unchanged (never routed to onError).
- Any other unexpected exception: best-effort onError dispatch, then re-raise (outer envelope :1943-1968).
- The pipeline returns data/raises typed errors; it NEVER builds HTTP responses (callers shape HTTP/WS).
- Generic storage call stays `await storage.store(submission)` — today's call passes no `tenant`
  kwarg; set `submission.tenant = tenant` only if the parity suite (TASK-4221) still passes; otherwise
  leave tenant handling identical and note it.
- `PlausibilityBlocked` (on_error=block) propagates before anything is stored (AC13).
- `self.logger = logging.getLogger(__name__)`; never log answer values.

### References in Codebase
- `api/handlers.py:1498-1968` — the code being extracted (read it in full first).
- `packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline_parity.py` (TASK-4221) — the oracle.

---

## Implementation Blueprint

### Steps (in order)
1. Re-run the TASK-4221 parity suite on the base — *why*: confirm the oracle is green before extracting.
2. Write the models/errors block — *why*: TASK-4224 and TASK-4227 map these exceptions to HTTP/WS.
3. Write `validate()` (prepare) then `submit()` (commit) by MOVING the handler logic, keeping comments that explain FEAT-457/458/188 decisions — *why*: behaviour preservation.
4. Write unit tests calling the pipeline directly with fakes — *why*: the audio channel has no HTTP request shape.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` (CREATE — models & errors)
```python
"""Shared submission pipeline for HTTP, A2UI and audio (FEAT-649 Module 9).

Behaviour-preserving extraction of ``FormAPIHandler.submit_data``'s tail
(validate → plausibility → persist → forward → cleanup → events), so every channel reaches
the same sinks, lifecycle events and forwarder.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict

from ..core.events import FormEventAbort
from ..core.llm_validation import PlausibilityReport, llm_validation_enabled
from ..core.schema import FormSchema, UnknownFieldsPolicy
from ..core.voice_answer import VoiceEvidenceEnvelope, is_voice_envelope, unwrap_voice
from .auth_context import AuthContext
from .event_dispatcher import dispatch
from .metadata_enricher import MetadataResolutionError, enrich_submission
from .plausibility import AnswerPlausibilityChecker, PlausibilityBlocked
from .submissions import FormSubmission, FormSubmissionStorage
from .unknown_fields import ExtrasCapExceeded, enforce_extras_cap
from .validators import FormValidator, ValidationResult

if TYPE_CHECKING:
    from aiohttp import web

    from .forwarder import SubmissionForwarder
    from .partial_saves import PartialSaveStore
    from .sinks.factory import SinkFactory

__all__ = ["SubmissionPipeline", "SubmitOutcome", "SubmitSinkError", "ValidationFailed", "PlausibilityBlocked"]


class SubmitOutcome(BaseModel):
    """Composite result of a committed submission."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    submission_id: str
    stored_in: Literal["sink", "generic", "none"]
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    plausibility: PlausibilityReport | None = None
    validation: ValidationResult


class ValidationFailed(Exception):
    """Deterministic rejection (422 class). ``errors`` is the exact dict submit_data returns today."""

    def __init__(self, errors: dict[str, Any]) -> None:
        super().__init__(f"Validation failed: {errors}")
        self.errors = errors


class SubmitSinkError(Exception):
    """Sink failure already reported via onError; carries today's HTTP mapping."""

    def __init__(self, message: str, *, status: int, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.headers = headers or {}
```
**Why**: callers translate `ValidationFailed`/`SubmitSinkError`/`PlausibilityBlocked`/`FormEventAbort`
into their wire shape; keeping status codes on the exception preserves the 503/422/501 mapping.

### `services/submission_pipeline.py` (CREATE — constructor & prepare step)
```python
class SubmissionPipeline:
    """Validate → plausibility → persist → forward → cleanup → events, for every channel."""

    def __init__(
        self,
        *,
        validator: FormValidator,
        submission_storage: "FormSubmissionStorage | None",
        forwarder: "SubmissionForwarder | None",
        partial_store: "PartialSaveStore | None",
        plausibility: AnswerPlausibilityChecker | None,
        sink_factory: "SinkFactory | None" = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.validator = validator
        self.submission_storage = submission_storage
        self.forwarder = forwarder
        self.partial_store = partial_store
        self.plausibility = plausibility
        self.sink_factory = sink_factory
        self.logger = logger or logging.getLogger(__name__)

    def _plausibility_enabled(self, form: FormSchema) -> bool:
        """True when any field resolves llm_validation on (field override or form default)."""
        return any(llm_validation_enabled(form, f) for f in form.iter_fields_recursive())

    async def validate(
        self,
        form: FormSchema,
        data: dict[str, Any],
        *,
        locale: str,
        auth_context: AuthContext | None,
        llm_validation: bool = False,
        visit_context: dict[str, Any] | None = None,
    ) -> tuple[ValidationResult, PlausibilityReport | None]:
        """Prepare step: deterministic validation, then plausibility only when valid and requested."""
        result = await self.validator.validate(
            form, data, locale=locale, auth_context=auth_context, visit_context=visit_context
        )
        report: PlausibilityReport | None = None
        if llm_validation and result.is_valid and self.plausibility is not None and self._plausibility_enabled(form):
            report = await self.plausibility.check(form, unwrap_voice(result.sanitized_data), locale=locale)
        return result, report
```
**Why**: `validate()` is the pure prepare step the audio engine runs at REVIEW (S2) and the
`/validate` opt-in uses (TASK-4224). Disabled forms never reach the checker (AC10).

### `services/submission_pipeline.py` (CREATE — commit step, head)
```python
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
        request: "web.Request | None" = None,
        visit_context: dict[str, Any] | None = None,
        submission_id: str | None = None,
    ) -> SubmitOutcome:
        """Commit step. Raises ValidationFailed, SubmitSinkError, PlausibilityBlocked or FormEventAbort."""
        auth = auth_context or AuthContext(scheme="none")

        async def _on_error(exc: BaseException, where: str) -> None:
            try:
                await dispatch("onError", form=form, request=request, tenant=tenant, auth_context=auth, error=exc)
            except Exception:
                self.logger.exception("onError handler raised during %s", where)

        try:
            # FILL IN: onBeforeSubmit dispatch + payload replacement, verbatim from api/handlers.py:1665-1682
            #          (FormEventAbort re-raised to the caller, never routed to onError) — bounded by TASK-4221 TestLifecycleOrder
            # FILL IN: validate (self.validator.validate(..., visit_context=visit_context)); on failure
            #          await _on_error(...) then raise ValidationFailed(result.errors) — bounded by api/handlers.py:1685-1703
            # FILL IN: unknown-fields policy reject/keep/drop + extras cap, verbatim from :1712-1761, raising
            #          ValidationFailed({"__unknown__": [...]}) where submit_data returns 422 — bounded by TASK-4221 TestUnknownFields
            # FILL IN: plausibility — when `plausibility` is None and self.plausibility and self._plausibility_enabled(form):
            #          plausibility = await self.plausibility.check(form, unwrap_voice(result.sanitized_data), locale=locale);
            #          PlausibilityBlocked propagates (nothing stored) — bounded by AC12/AC13
            ...
        except (FormEventAbort, ValidationFailed, SubmitSinkError, PlausibilityBlocked):
            raise
        except Exception as exc:
            await _on_error(exc, "submit")
            raise
```
**Why**: a single outer envelope reproduces :1943-1968 (onError then re-raise) while letting the
typed, already-reported failures through untouched.

### `services/submission_pipeline.py` (CREATE — commit step, tail; inside the same `try`)
```python
            # FILL IN: outbound = {**result.sanitized_data, **extras} if extras else result.sanitized_data   (:1770)
            stored_data = self._attach_verdicts(result.sanitized_data, plausibility)
            ctx = dict(context or {})
            if plausibility is not None:
                ctx["llm_validation"] = plausibility.model_dump(mode="json")
            submission = FormSubmission(
                submission_id=submission_id or str(uuid.uuid4()),
                form_uid=form.form_uid,
                form_id=form.form_id,
                form_version=form.version,
                data=stored_data,
                is_valid=True,
                created_at=datetime.now(timezone.utc),
                extra_data=extras or None,
                context=ctx or None,
            )
            # FILL IN: metadata enrichment verbatim from :1786-1814 (MetadataResolutionError → _on_error then
            #          raise ValidationFailed({"_metadata": str(exc)})) — bounded by parity
            # FILL IN: persistence verbatim from :1821-1878 — sink-exclusive when form.persistence is set
            #          (SinkUnavailableError → SubmitSinkError(status=503, headers={"Retry-After": "30"}),
            #          SinkTargetMismatchError → 422, SinkNotCapableError → 501, each after _on_error; never fall back
            #          to generic storage); else generic store(submission); else debug log — bounded by FEAT-457 / AC9
            # FILL IN: forwarder (:1885-1898), partial cleanup on merge_session_id (:1900-1914),
            #          onAfterSubmit with {**submission.data, **extras} (:1922-1930) — bounded by TASK-4221 parity
            # FILL IN: return SubmitOutcome(submission_id=..., stored_in=..., forwarded=..., forward_status=...,
            #          forward_error=..., plausibility=plausibility, validation=result)

    def _attach_verdicts(self, data: dict[str, Any], report: PlausibilityReport | None) -> dict[str, Any]:
        """Copy each verdict into its spoken envelope (``VoiceEvidenceEnvelope.plausibility``); scalars untouched."""
        if report is None or not report.items:
            return data
        out = dict(data)
        for field_id, verdict in report.items.items():
            value = out.get(field_id)
            if is_voice_envelope(value):
                # FILL IN: rebuild via VoiceEvidenceEnvelope.model_validate(value) with plausibility=verdict and
                #          store .model_dump(mode="json") — bounded by AC8/AC12 (plain VoiceAnswerEnvelope TEXT answers stay valid)
                ...
        return out
```
**Why**: `context["llm_validation"]` and envelope verdicts are the two persisted homes of the
report (AC12); everything else is moved code.

### FILL IN checklist
- [ ] onBeforeSubmit + abort passthrough — bounded by TASK-4221 lifecycle tests
- [ ] validate + `ValidationFailed` — bounded by :1685-1703
- [ ] unknown-fields policy — bounded by TASK-4221 TestUnknownFields
- [ ] plausibility step (skip when report passed in / disabled) — bounded by AC10, AC12, AC13
- [ ] outbound, enrichment, persistence, forwarder, cleanup, onAfterSubmit, `SubmitOutcome` — bounded by parity (AC9)
- [ ] `_attach_verdicts` envelope rebuild — bounded by AC8
- [ ] tests — see Test Specification

---

## Acceptance Criteria

- [ ] `SubmissionPipeline.submit()` reproduces `submit_data`'s side effects for: sink-exclusive (store never called), generic path, sink error statuses (503+Retry-After / 422 / 501), lifecycle order, forwarder, partial cleanup, unknown-fields policy (AC9).
- [ ] With plausibility enabled, exactly one `check()` per submit; report in `submission.context["llm_validation"]`; spoken envelopes carry `plausibility`; low confidence still commits (AC12).
- [ ] A report passed by the caller (audio) is used as-is — no second LLM call (AC11).
- [ ] `on_error="block"` + failing checker → `PlausibilityBlocked`, nothing stored (AC13).
- [ ] Disabled forms → zero checker calls (AC10).
- [ ] The TASK-4221 parity suite still passes (handler unchanged in this task).
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` passes; no `parrot.clients` import (AC21).

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline_parity.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline.py
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot_formdesigner.core.llm_validation import LLMValidationConfig, PlausibilityReport, PlausibilityVerdict
from parrot_formdesigner.services.plausibility import PlausibilityBlocked
from parrot_formdesigner.services.submission_pipeline import (
    SubmissionPipeline, SubmitSinkError, ValidationFailed,
)
from parrot_formdesigner.services.submissions import FormSubmissionStorage
from parrot_formdesigner.services.validators import FormValidator


@pytest.fixture
def pipeline_factory():
    # FILL IN: build SubmissionPipeline with real FormValidator, MagicMock(spec=FormSubmissionStorage) store,
    #          optional fake sink factory / forwarder / partial store / fake checker (records check() calls)
    ...


class TestCommit:
    async def test_generic_store_called_once(self, pipeline_factory): ...
    async def test_sink_exclusive_never_generic(self, pipeline_factory): ...
    async def test_sink_unavailable_maps_503(self, pipeline_factory): ...   # SubmitSinkError.status == 503, headers Retry-After
    async def test_validation_failed_raises_and_stores_nothing(self, pipeline_factory): ...
    async def test_partial_cleanup_on_merge_session(self, pipeline_factory): ...

class TestPlausibility:
    async def test_disabled_form_no_check(self, pipeline_factory): ...
    async def test_report_in_context_and_envelope(self, pipeline_factory): ...
    async def test_passed_report_not_rechecked(self, pipeline_factory): ...
    async def test_block_raises_nothing_stored(self, pipeline_factory): ...
    async def test_low_confidence_still_commits(self, pipeline_factory): ...

class TestPrepare:
    async def test_validate_without_flag_no_llm(self, pipeline_factory): ...
    async def test_validate_with_flag_returns_report(self, pipeline_factory): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** at the path listed above (§3 Module 9, §7 Patterns/Risks, AC9–AC13)
3. **Check dependencies** — TASK-4210, TASK-4220, TASK-4221 must be `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`
4. **Verify the Codebase Contract** — read `api/handlers.py:1498-1968` in full; confirm TASK-4210/4220 names; run the stale-branch ancestor check in Scope
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4222 audio-form-interaction-workflow verified`
10. **Fill in the Completion Note** below (record the three additive parameters), then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
