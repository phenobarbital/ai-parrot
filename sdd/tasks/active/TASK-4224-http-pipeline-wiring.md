# TASK-4224: Wire SubmissionPipeline into submit_data/validate (llm_validation opt-in, plausibility block) and setup_form_api

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4222, TASK-4223, TASK-4221
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (HTTP wiring), goals G7/G8, AC9–AC13. TASK-4222 created `SubmissionPipeline`
as a behaviour-preserving extraction of `submit_data`'s tail; this task makes the HTTP surface
use it:
- `POST …/data` (`FormAPIHandler.submit_data`, `api/handlers.py:1498`) delegates from
  `onBeforeSubmit` onwards to `pipeline.submit()` and maps its typed errors back to today's
  responses; the 200 body gains an additive `"plausibility"` block when the form enables it.
- `POST …/validate` (`api/handlers.py:1004`) accepts an opt-in `"llm_validation": true` (body key,
  or `?llm_validation=true`) → `pipeline.validate(..., llm_validation=True)` → response gains
  `"plausibility"`; HTTP status is never affected by low confidence.
- `setup_form_api` publishes a shared pipeline as `app["submission_pipeline"]` for the audio
  adapter (consumed by TASK-4228).

**Verified fact**: `setup_form_api` ALREADY takes `client: "AbstractClient | None" = None`
(`api/routes.py:196`) and passes it to `FormAPIHandler(client=client)` (`:348-361`). No new
parameter is needed; the plausibility client is the handler's `_get_llm_client()` (`api/handlers.py:197`).

The TASK-4221 parity suite is the oracle: it must pass unchanged after this rewiring (AC9).

---

## Scope

- Add `FormAPIHandler._build_submission_pipeline(form: FormSchema | None = None) -> SubmissionPipeline`:
  built **per call** from the handler's CURRENT `self.validator`, `self._submission_storage`,
  `self._forwarder`, `self._partial_store`, `self._sink_factory` (existing tests replace
  `handler.validator` after construction — a cached pipeline would ignore that), and an
  `AnswerPlausibilityChecker(self._get_llm_client(), config=form.llm_validation or LLMValidationConfig())`
  **only when** some field of `form` resolves `llm_validation_enabled` (so disabled forms never
  instantiate the lazy GoogleGenAI client — AC10).
- `submit_data`: keep everything up to and including the `?merge_partials` merge (:1553-1663)
  and the A2UI `_reply` helper; replace the block from `# lifecycle: onBeforeSubmit` (:1665) to the
  end of the method (:1968) with one `pipeline.submit(...)` call plus exception mapping:
  `FormEventAbort` → `JSONResponse({"error": exc.user_message, "reason": exc.reason}, status=exc.status_code)`;
  `ValidationFailed` → `_reply({"is_valid": False, "errors": exc.errors}, 422)`;
  `SubmitSinkError` → `_reply({"error": str(exc)}, exc.status, headers=exc.headers)`;
  `PlausibilityBlocked` → `_reply({"error": ..., "code": "PLAUSIBILITY_UNAVAILABLE"}, 503, headers={"Retry-After": "30"})`;
  any other exception → keep today's `request["_lifecycle_user_message"]` + log + re-raise (the
  pipeline already dispatched onError).
- 200 body: today's five keys, plus `"plausibility": report.model_dump(mode="json", exclude_none=True)`
  only when a report exists (keys unchanged otherwise — parity).
- `validate`: read the opt-in, call `pipeline.validate(form, data, locale=..., auth_context=..., llm_validation=opt_in, visit_context=visit_context)`,
  keep the `__unknown__` reject handling and the A2UI dual-wire; add `"plausibility"` to the plain
  JSON body when present; for A2UI keep envelopes unchanged and FILL IN how the report rides along.
  `PlausibilityBlocked` on validate → 503 `PLAUSIBILITY_UNAVAILABLE`.
- `api/routes.py`: after `app["form_api_handler"] = handler` publish
  `app["submission_pipeline"] = handler._build_submission_pipeline()` (form-agnostic, `plausibility=None`
  — the audio engine passes its own report).
- Tests `test_http_plausibility.py` (spec §4 `test_validate_endpoint_llm_validation_opt_in`,
  `test_submit_response_and_context_llm_validation`, integration `test_http_submit_with_plausibility_block_mode`).

**NOT in scope**: the audio WS wiring (TASK-4227/4228); `voice/optimize` (TASK-4234); any change to
`FormValidator` (TASK-4223) or the pipeline internals (TASK-4222); `parrot/clients/base.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `_build_submission_pipeline`, `submit_data` delegation, `validate` opt-in |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Publish `app["submission_pipeline"]` |
| `packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py` | CREATE | HTTP plausibility tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported in api/handlers.py
from ..core.events import FormEventAbort, FormEventName              # api/handlers.py:20
from ..core.schema import FormField, FormSchema, RenderedForm        # api/handlers.py:23
from ..services.auth_context import AuthContext                      # api/handlers.py:25
from ..services.validators import FormValidator                      # api/handlers.py:29
from . import a2ui_wire                                              # api/handlers.py:30
from navigator.responses import JSONResponse                         # api/handlers.py:19
```

#### Provided by dependency tasks (do not exist yet)
```python
from ..core.llm_validation import LLMValidationConfig, llm_validation_enabled                    # TASK-4209
from ..services.plausibility import AnswerPlausibilityChecker, PlausibilityBlocked                # TASK-4220
from ..services.submission_pipeline import SubmissionPipeline, SubmitSinkError, ValidationFailed  # TASK-4222
```

### Existing Signatures to Use
```python
# api/handlers.py
class FormAPIHandler:
    def __init__(self, registry, client=None, submission_storage=None, forwarder=None, partial_store=None, ...,
                 rbac_enforcing=False, sink_factory=None)                             # :144-160
    #   self._client :162, self._submission_storage :163, self._forwarder :164, self._sink_factory :168,
    #   self._partial_store :169, self.validator = FormValidator() :177, self.logger :178
    def _get_llm_client(self) -> "AbstractClient | None"                             # :197-215 (lazy GoogleGenAIClient)
    def _build_auth_context(self, request) -> AuthContext                            # :356
    def _extract_visit_context(self, form, body) -> tuple[dict, dict | None]          # :401
    def _extract_session_id(self, request) -> str | None                             # :469
    async def validate(self, request: web.Request) -> web.Response                   # :1004 (A2UI :1038-1054, visit ctx :1056, validator call :1057, __unknown__ :1059-1061, reply :1065-1073)
    async def submit_data(self, request: web.Request) -> web.Response                # :1498
    #   merge block ends :1663 ; "# lifecycle: onBeforeSubmit" :1665 ; final 200 _reply :1932-1941 ; method ends :1968 ;
    #   outer `try:` :1629 ; except FormEventAbort / Exception :1943-1968 (request["_lifecycle_user_message"], log, raise)
# api/routes.py
def setup_form_api(app, registry, *, client=None, submission_storage=None, forwarder=None, base_path="/api/v1",
                   blob_storage=None, resolver=None, partial_store=None, synthesizer=None, transcriber=None,
                   token_validator=None, ..., alias_registry=None, public_base_url=None, teams_renderer=None) -> None   # :192-215
#   handler = FormAPIHandler(registry=registry, client=client, ..., sink_factory=sink_factory)  # :348-361
#   app["form_api_handler"] = handler                                                           # :362
# FEAT-649 pipeline (TASK-4222):
#   SubmissionPipeline(*, validator, submission_storage, forwarder, partial_store, plausibility, sink_factory=None, logger=None)
#   await pipeline.submit(form, data, *, tenant, user_id, locale, context, extra_data, auth_context, merge_session_id,
#                         plausibility=None, request=None, visit_context=None, submission_id=None) -> SubmitOutcome
#   await pipeline.validate(form, data, *, locale, auth_context, llm_validation=False, visit_context=None) -> (ValidationResult, PlausibilityReport | None)
#   SubmitOutcome: submission_id, stored_in, forwarded, forward_status, forward_error, plausibility, validation
```

### Does NOT Exist
- ~~`setup_form_api(..., llm_client=...)`~~ — the parameter is `client` and already exists (`api/routes.py:196`).
- ~~`app["submission_pipeline"]`~~ — created here.
- ~~`FormAPIHandler.pipeline` attribute~~ — use `_build_submission_pipeline()` per call (tests patch `handler.validator`).
- ~~`ValidationResult.plausibility`~~ — report travels beside the result.
- ~~`POST …/voice/optimize`~~ — TASK-4234.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler.submit_data",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler.validate",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler._get_llm_client",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler._build_auth_context",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler._extract_visit_context",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py#setup_form_api"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Parity first** (AC9): run `test_submission_pipeline_parity.py` (TASK-4221) before and after;
  plus the existing suites listed in Validation Commands — they patch `handler.validator`,
  `handler._submission_storage`, `handler._sink_factory` after construction, which is why the
  pipeline is built per call.
- Response keys on the success path are unchanged when no report exists; `"plausibility"` is additive.
- Low confidence never changes status (AC12); only `PlausibilityBlocked` (LLM failure under
  `on_error=block`) produces 503 (AC13).
- `request["_lifecycle_user_message"]` behaviour on unexpected exceptions is preserved — the
  pipeline dispatched `onError` but cannot reach the request's mapping; FILL IN how the
  user_message surfaces (e.g. a returned attribute on the re-raised exception) without dispatching onError twice.
- `parrot.clients` stays lazy (AC21).

---

## Implementation Blueprint

### Steps (in order)
1. Run the parity suite on the base — *why*: confirm the oracle is green.
2. Add `_build_submission_pipeline` after `_get_llm_client` — *why*: single construction point.
3. Rewire `submit_data` from `# lifecycle: onBeforeSubmit` to the end — *why*: one pipeline for every channel.
4. Add the opt-in to `validate` — *why*: pre-submit plausibility block (AC12).
5. Publish `app["submission_pipeline"]` in `setup_form_api` — *why*: TASK-4228 hands it to the audio adapter.
6. Write `test_http_plausibility.py` and re-run the parity suite — *why*: AC9–AC13.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — pipeline factory)
```python
# occurrences: 1 (verified: grep -c '    def _get_llm_client(self) -> "AbstractClient | None":' api/handlers.py)
# AFTER — insert below the body of `    def _get_llm_client(self) -> "AbstractClient | None":` (verified: api/handlers.py:197-215)
    def _build_submission_pipeline(self, form: FormSchema | None = None) -> "SubmissionPipeline":
        """Build the shared submit pipeline from the handler's CURRENT collaborators (FEAT-649).

        Built per call on purpose: tests (and hosts) replace ``self.validator`` /
        ``self._submission_storage`` / ``self._sink_factory`` after construction. A plausibility
        checker is attached only when ``form`` enables ``llm_validation`` on some field, so a
        disabled form never instantiates the lazy LLM client.
        """
        from ..core.llm_validation import LLMValidationConfig, llm_validation_enabled
        from ..services.plausibility import AnswerPlausibilityChecker
        from ..services.submission_pipeline import SubmissionPipeline

        checker = None
        if form is not None and any(llm_validation_enabled(form, f) for f in form.iter_fields_recursive()):
            checker = AnswerPlausibilityChecker(
                self._get_llm_client(), config=form.llm_validation or LLMValidationConfig()
            )
        return SubmissionPipeline(
            validator=self.validator,
            submission_storage=self._submission_storage,
            forwarder=self._forwarder,
            partial_store=self._partial_store,
            plausibility=checker,
            sink_factory=self._sink_factory,
            logger=self.logger,
        )
```
**Why**: local imports keep module import cost and cycles unchanged (handlers.py already uses this pattern).
Add `from ..services.submission_pipeline import SubmissionPipeline` under the existing `if TYPE_CHECKING:` block (:92-107) for the annotation.

### `api/handlers.py` (MODIFY — submit_data delegation)
```python
# occurrences: 1 (verified: grep -c '            # lifecycle: onBeforeSubmit — may mutate payload or abort' api/handlers.py)
# REPLACE from `            # lifecycle: onBeforeSubmit — may mutate payload or abort` (verified: api/handlers.py:1665)
# through the end of submit_data's outer `except Exception as exc:` block (:1968) with:
            from ..services.plausibility import PlausibilityBlocked
            from ..services.submission_pipeline import SubmitSinkError, ValidationFailed

            pipeline = self._build_submission_pipeline(form)
            try:
                outcome = await pipeline.submit(
                    form,
                    data,
                    tenant=tenant,
                    user_id=None,  # FILL IN: today's submit_data sets no user_id — keep None unless parity allows — bounded by AC9
                    locale=request.query.get("locale", "en") if hasattr(request.query, "get") else "en",
                    context=None,
                    extra_data=None,
                    auth_context=_auth_ctx,
                    merge_session_id=_merge_session_id if merge_partials else None,
                    request=request,
                    visit_context=visit_context,
                )
            except FormEventAbort as exc:
                return JSONResponse({"error": exc.user_message, "reason": exc.reason}, status=exc.status_code)
            except ValidationFailed as exc:
                return _reply({"is_valid": False, "errors": exc.errors}, status=422)
            except SubmitSinkError as exc:
                return _reply({"error": str(exc)}, status=exc.status, headers=exc.headers or None)
            except PlausibilityBlocked as exc:
                return _reply(
                    {"error": f"Answer plausibility check unavailable: {exc.reason}", "code": "PLAUSIBILITY_UNAVAILABLE"},
                    status=503,
                    headers={"Retry-After": "30"},
                )
            body: dict[str, Any] = {
                "submission_id": outcome.submission_id,
                "is_valid": True,
                "forwarded": outcome.forwarded,
                "forward_status": outcome.forward_status,
                "forward_error": outcome.forward_error,
            }
            if outcome.plausibility is not None:
                body["plausibility"] = outcome.plausibility.model_dump(mode="json", exclude_none=True)
            return _reply(body, status=200)
        # FILL IN: keep the outer `try:` opened at :1629 (auth ctx + merge) and an `except Exception` that
        #          preserves request["_lifecycle_user_message"] + logger.exception + raise WITHOUT a second onError
        #          dispatch (the pipeline already dispatched it) — bounded by TASK-4221 parity / FEAT-188 ordering
```
**Why**: everything before onBeforeSubmit (tenant, A2UI unwrap, visit context, partial merge) stays
in the handler because it is HTTP-specific; everything after is the shared pipeline. Check that the
locale default matches what `self.validator.validate` received before (it was the validator default `"en"`).

### `api/handlers.py` (MODIFY — validate opt-in)
```python
# occurrences: 1 (verified: grep -cxF '        result = await self.validator.validate(form, data, visit_context=visit_context)' api/handlers.py)
# REPLACE `        result = await self.validator.validate(form, data, visit_context=visit_context)` (verified: api/handlers.py:1057) with:
        from ..services.plausibility import PlausibilityBlocked

        llm_opt_in = request.query.get("llm_validation", "").lower() == "true"
        if isinstance(body, dict) and body.pop("llm_validation", None) is True:
            llm_opt_in = True
        # FILL IN: pop "llm_validation" BEFORE _extract_visit_context(form, body) (move this block above :1054)
        #          so the flag is never reported as an unknown field — bounded by FEAT-458 reject semantics
        #          (anchor `        data, visit_context = self._extract_visit_context(form, body)` is NOT unique — 2 occurrences, :1056 and :1620;
        #          use the one inside validate, directly above the validator call)
        pipeline = self._build_submission_pipeline(form if llm_opt_in else None)
        try:
            result, plausibility = await pipeline.validate(
                form, data, locale="en", auth_context=None, llm_validation=llm_opt_in, visit_context=visit_context
            )
        except PlausibilityBlocked as exc:
            return JSONResponse(
                {"error": f"Answer plausibility check unavailable: {exc.reason}", "code": "PLAUSIBILITY_UNAVAILABLE"},
                status=503,
                headers={"Retry-After": "30"},
            )
# and in the plain-JSON reply (verified anchor `            {"is_valid": is_valid, "errors": errors},` :1071, occurrences: 1):
#   build `payload = {"is_valid": is_valid, "errors": errors}`; add
#   `payload["plausibility"] = plausibility.model_dump(mode="json", exclude_none=True)` when plausibility is not None.
# FILL IN: A2UI branch — keep today's envelopes; decide whether the report is attached (spec: "plausibility in the
#          envelope data") using a2ui_wire helpers only — bounded by FEAT-544 envelope contract (no new envelope types)
```
**Why**: `auth_context=None` reproduces today's `validate` call exactly (it passes none). The flag
is opt-in so a legacy caller makes zero LLM calls (AC10/AC12).

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    app\["form_api_handler"\] = handler' api/routes.py)
# AFTER — insert below `    app["form_api_handler"] = handler` (verified: api/routes.py:362)
    # FEAT-649: one shared, form-agnostic SubmissionPipeline for non-HTTP channels (audio WS).
    # plausibility=None here — the audio engine runs its own check at REVIEW and passes the report in.
    app["submission_pipeline"] = handler._build_submission_pipeline()
```
**Why**: TASK-4228 passes this instance to `AudioFormWSHandler(pipeline=...)` so audio reaches the same sinks/events/forwarder.

### FILL IN checklist
- [ ] `submit_data` — `user_id` value, outer exception envelope without double onError; bounded by AC9 / TASK-4221
- [ ] `validate` — pop the flag before visit-context extraction; A2UI report attachment; bounded by FEAT-458 / FEAT-544
- [ ] tests — see Test Specification

---

## Acceptance Criteria

- [ ] TASK-4221's `test_submission_pipeline_parity.py` passes unchanged (AC9).
- [ ] Existing submit suites pass unchanged (see Validation Commands).
- [ ] `POST …/validate` without the flag makes zero LLM calls; with `"llm_validation": true` the body gains `"plausibility"`; status depends only on deterministic validity (AC12).
- [ ] `POST …/data` on a form with `llm_validation.enabled` returns `"plausibility"` and the stored submission has `context["llm_validation"]` (AC12).
- [ ] `on_error="block"` + unavailable client → 503 `PLAUSIBILITY_UNAVAILABLE`, nothing stored; `skip` → 200 with `status: "skipped"` (AC13).
- [ ] Disabled forms never call `_get_llm_client()` on submit/validate (AC10).
- [ ] `app["submission_pipeline"]` is a `SubmissionPipeline` after `setup_form_api`.
- [ ] `ruff check` passes on `api/handlers.py` and `api/routes.py` (AC21).

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline_parity.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_submit_path_branch.py -q`
- `pytest packages/parrot-formdesigner/tests/integration/test_lifecycle_events_submit.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_submit_unknown_fields.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_submit_a2ui.py -q`
- `pytest packages/parrot-formdesigner/tests/test_submit_merge.py -q`
- `pytest packages/parrot-formdesigner/tests/test_store_context_http.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_setup_form_api.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.llm_validation import LLMValidationConfig
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.submissions import FormSubmissionStorage


class FakeLLM:
    """Records ask(); returns a PlausibilityBatch-shaped object or raises."""
    # FILL IN: same contract as the TASK-4220 FakeClient


@pytest.fixture
def make_handler():
    # FILL IN: FormAPIHandler(registry=mock_registry, client=FakeLLM(...), submission_storage=mock_storage);
    #          request mock copied from tests/unit/test_submit_path_branch.py:72
    ...


class TestValidateOptIn:
    async def test_no_flag_no_llm_call(self, make_handler): ...
    async def test_flag_returns_plausibility_block(self, make_handler): ...
    async def test_low_confidence_keeps_200(self, make_handler): ...

class TestSubmitPlausibility:
    async def test_response_and_context_llm_validation(self, make_handler): ...
    async def test_disabled_form_never_builds_client(self, make_handler): ...   # _get_llm_client not called

class TestBlockMode:
    async def test_block_unavailable_503_nothing_stored(self, make_handler): ...
    async def test_skip_unavailable_200_skipped(self, make_handler): ...

class TestRoutes:
    def test_app_submission_pipeline_published(self): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** at the path listed above (§3 Module 9, AC9–AC13, §7 Known Risks "Hot-path refactor")
3. **Check dependencies** — TASK-4221, TASK-4222, TASK-4223 must be `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`
4. **Verify the Codebase Contract** — re-read `api/handlers.py:1004-1074` and `:1498-1968`; re-run every `grep -c` anchor; confirm TASK-4222's final signatures
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
7. **Verify** — run ALL Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4224 audio-form-interaction-workflow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
