# TASK-4221: Golden parity tests pinning today's submit_data behaviour (sinks, generic storage, events order, forwarder, partial cleanup)

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 and §7 "Behaviour-preserving extraction first": before a single line of the
hot submit path (`api/handlers.py` `submit_data`, ~:1665-1941) moves into `SubmissionPipeline`
(TASK-4222/4224), a golden test suite must pin today's observable behaviour. These tests run
against the CURRENT `FormAPIHandler.submit_data` and must keep passing, unchanged, after
TASK-4224 rewires the handler (they are the parity oracle for AC9 and
`test_submission_pipeline_parity_with_submit_data`).

---

## Scope

- Write `test_submission_pipeline_parity.py` exercising `FormAPIHandler.submit_data` through a
  mocked `web.Request` (pattern `tests/unit/test_submit_path_branch.py`, `tests/integration/test_lifecycle_events_submit.py`).
- Pin, as golden assertions:
  1. **Sink-exclusive path** (FEAT-457): form with `persistence` → `sink.ensure_target` then `sink.write`, `submission_storage.store` never awaited; tabular → `flatten_submission` payload, document family → `nest_submission`.
  2. **Generic path**: no `persistence` → `submission_storage.store(submission)` awaited once with the `FormSubmission` (assert `form_uid`, `form_id`, `form_version == form.version`, `data == sanitized_data`, `is_valid`, `extra_data`).
  3. **Sink error mapping**: `SinkUnavailableError` → 503 + `Retry-After: 30`; `SinkTargetMismatchError` → 422; `SinkNotCapableError` → 501; nothing persisted; `onError` dispatched.
  4. **Lifecycle event order** (FEAT-188): record the sequence of dispatched events — success path `["onBeforeSubmit", "onAfterSubmit"]`; validation failure `["onBeforeSubmit", "onError"]` and 422 `{"is_valid": False, "errors": ...}`; `FormEventAbort` from `onBeforeSubmit` returns its status and is NOT routed to `onError`.
  5. **Forwarder**: endpoint submit action → `forwarder.forward(outbound, form.submit)` awaited once; response carries `forwarded`, `forward_status`, `forward_error`; failure still 200.
  6. **Partial merge + cleanup**: `?merge_partials=true` with a session id → cached partial merged (submitted wins), `partial_store.delete(str(form_uid), session_id)` awaited after success, NOT awaited on 422.
  7. **Unknown-fields policy** (FEAT-458): `reject` → 422 `errors["__unknown__"]`; `keep` → `extra_data` stored and outbound flat-merged; `drop` → extras discarded.
  8. **Response body** golden: exact key set `{"submission_id", "is_valid", "forwarded", "forward_status", "forward_error"}`.
  9. **A2UI branch** (FEAT-544): an A2UI action envelope → `a2ui_wire.confirmation` shape on 200 and `validation_errors` envelopes on 422 (reuse the request shape from `tests/unit/api/test_submit_a2ui.py`).
- Assertions must target OBSERVABLE behaviour (calls, call order, response status/body), never
  private helpers that TASK-4224 will delete.

**NOT in scope**: any change to `api/handlers.py` or any source file; the new pipeline itself
(TASK-4222); plausibility assertions (TASK-4224 adds those in `test_http_plausibility.py`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline_parity.py` | CREATE | Golden parity suite for `submit_data` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import parrot_formdesigner.api.handlers as handlers_module                      # used by tests/unit/test_submit_path_branch.py:11
from parrot_formdesigner.api.handlers import FormAPIHandler                      # api/handlers.py (class FormAPIHandler; __init__ :144)
from parrot_formdesigner.core.persistence import FormPersistenceConfig, SinkCapability   # core/persistence.py
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection   # core/schema.py:65, :401, :229
from parrot_formdesigner.core.types import FieldType                             # core/types.py:16
from parrot_formdesigner.core.events import EventResolution, FormEventAbort, FormEventBinding, FormEventsConfig  # used by tests/integration/test_lifecycle_events_submit.py:18-23
from parrot_formdesigner.services.event_registry import _clear_event_registry_for_tests, register_form_event     # same file :25-28
from parrot_formdesigner.services.registry import FormRegistry                   # services/registry.py:240
from parrot_formdesigner.services.sinks.base import (                            # used by tests/unit/test_submit_path_branch.py:19-23
    AbstractSubmissionSink, SinkNotCapableError, SinkTargetMismatchError, SinkUnavailableError,
)
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage   # services/submissions.py:50, :122
from parrot_formdesigner.services.validators import FormValidator, ValidationResult          # services/validators.py:200, :160
from parrot_formdesigner.services.forwarder import ForwardResult, SubmissionForwarder        # services/forwarder.py:22, :36
from parrot_formdesigner.services.partial_saves import PartialSaveStore                      # services/partial_saves.py:24
```

### Existing Signatures to Use
```python
# api/handlers.py:144-160
FormAPIHandler.__init__(self, registry, client=None, submission_storage=None, forwarder=None, partial_store=None,
                        org_graph_service=None, project_service=None, rbac_service=None, workday_adapter=None,
                        venue_service=None, rbac_enforcing=False, sink_factory=None)
#   attributes set: self.validator = FormValidator() (:177), self._submission_storage, self._forwarder,
#   self._sink_factory, self._partial_store — existing tests REPLACE handler.validator after construction.
async def submit_data(self, request: web.Request) -> web.Response          # :1498
#   query merge flag: request.query.get("merge_partials", "").lower() == "true" (:1638)
#   session id: self._extract_session_id(request) (:469) — reads request["session"].get("id") when "session" in request
#   partial get: await self._partial_store.get(str(form_uid), session_id); remapped via _remap_partial_to_field_ids (:502)
#   dispatch("onBeforeSubmit"|"onError"|"onAfterSubmit", form=, request=, tenant=, auth_context=, payload=|error=)
#   sinks: sink = await self._sink_factory.get(form, tenant=tenant); await sink.ensure_target(form); await sink.write(submission, payload) (:1850-1858)
#   generic: await self._submission_storage.store(submission)  (no tenant kwarg passed today) (:1872)
#   forward: await self._forwarder.forward(outbound, form.submit) when form.submit.action_type == "endpoint" (:1887-1888)
#   cleanup: await self._partial_store.delete(str(form_uid), _merge_session_id) (:1902)
#   200 body keys: submission_id, is_valid, forwarded, forward_status, forward_error (:1934-1939)
# services/forwarder.py:61  async def forward(self, data: dict[str, Any], submit_action: SubmitAction) -> ForwardResult
# services/forwarder.py:22  ForwardResult(success: bool, status_code: int | None = None, error: str | None = None)
# services/partial_saves.py:145  async def delete(self, form_id: str, session_id: str) -> bool
# services/event_dispatcher.py:102  async def dispatch(event, *, form, request, tenant, auth_context, payload=None, schema_dump=None, error=None) -> EventResolution
```

### Does NOT Exist
- ~~`SubmissionPipeline`~~ — not yet (TASK-4222); this suite must NOT import it.
- ~~`fakeredis`~~ — not installed; mock `PartialSaveStore` with `MagicMock(spec=PartialSaveStore)` + `AsyncMock`.
- ~~`FormSubmissionStorage.store(..., tenant=...)` called by `submit_data`~~ — today it is called with the submission only; pin THAT.
- ~~A shared fixture module for submit tests~~ — copy the minimal helpers (`_make_request`, `_FakeSink`, `_FakeSinkFactory`) into this file.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline_parity.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler.submit_data",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/event_dispatcher.py#dispatch",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/forwarder.py#SubmissionForwarder.forward",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py#PartialSaveStore.delete",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py#FormSubmissionStorage.store"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Request/handler helpers: `packages/parrot-formdesigner/tests/unit/test_submit_path_branch.py:72-148`.
- Lifecycle recording: `packages/parrot-formdesigner/tests/integration/test_lifecycle_events_submit.py:34-120`
  (`register_form_event("<form_id>.<event>")` + `FormEventsConfig(...=FormEventBinding(handler_ref=...))`,
  autouse fixture calling `_clear_event_registry_for_tests()`).
- Event ORDER: register a recording handler for each of the three events and append `ctx.event`.
- A2UI request shape: `packages/parrot-formdesigner/tests/unit/api/test_submit_a2ui.py`.

### Key Constraints
- Test only through `submit_data` + collaborator mocks — TASK-4224 replaces the internals and
  this file must pass unchanged afterwards.
- Use the REAL `FormValidator` for at least the generic path and the unknown-fields cases (so
  sanitisation is pinned), mocked validators elsewhere are fine.
- No network, no DB, no Redis.

---

## Implementation Blueprint

### Steps (in order)
1. Copy the helper block below and the fake sink/factory from `test_submit_path_branch.py` — *why*: the suite must be self-contained.
2. Write one test class per golden behaviour (1–9 in Scope) — *why*: each maps to an invariant TASK-4222 must preserve.
3. Run the suite against the current code; every test must pass NOW — *why*: it is an oracle, not a spec of new behaviour.

### `packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline_parity.py` (CREATE)
```python
"""Golden parity suite for FormAPIHandler.submit_data (FEAT-649 TASK-4221).

Pins today's observable submit behaviour so the SubmissionPipeline extraction (TASK-4222/4224)
can be proven behaviour-preserving. Must pass before AND after the extraction, unchanged.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.events import EventResolution, FormEventAbort, FormEventBinding, FormEventsConfig
from parrot_formdesigner.core.persistence import FormPersistenceConfig, SinkCapability
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.event_registry import _clear_event_registry_for_tests, register_form_event
from parrot_formdesigner.services.forwarder import ForwardResult, SubmissionForwarder
from parrot_formdesigner.services.partial_saves import PartialSaveStore
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.sinks.base import (
    AbstractSubmissionSink, SinkNotCapableError, SinkTargetMismatchError, SinkUnavailableError,
)
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage

_TENANT = "test-tenant"
_FORM_UID = "11111111-1111-1111-1111-111111111111"
_RESPONSE_KEYS = {"submission_id", "is_valid", "forwarded", "forward_status", "forward_error"}


@pytest.fixture(autouse=True)
def _clear_events():
    yield
    _clear_event_registry_for_tests()


def _make_request(body: dict | None = None, *, query: dict | None = None, session_id: str | None = None) -> MagicMock:
    """Mocked aiohttp request (pattern tests/unit/test_submit_path_branch.py:72)."""
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": _FORM_UID}
    req.method = "POST"
    req.headers = {}
    req.query = query or {}
    req.content_length = None
    # _extract_session_id (api/handlers.py:469) reads request["session"].get("id") when "session" in request
    nav_session = {"id": session_id} if session_id else None
    req.__contains__ = MagicMock(side_effect=lambda key: key == "session" and nav_session is not None)
    req.__getitem__ = MagicMock(side_effect=lambda key: nav_session if key == "session" else (_ for _ in ()).throw(KeyError(key)))
    req.__setitem__ = MagicMock()
    req.json = AsyncMock(return_value=body if body is not None else {"comment": "great"})
    req.get = MagicMock(side_effect=lambda key, default=None: _TENANT if key == "tenant" else default)
    req.session = {"session": {"programs": [_TENANT]}}
    # FILL IN: confirm _build_auth_context / _get_tenant tolerate this mock (they do for
    #          test_submit_path_branch.py) — bounded by "never patch handler internals"
    return req


def _record_events(form_id: str, sink: list[str]) -> FormEventsConfig:
    """Register recording handlers for the three submit events and return the binding config."""
    for event in ("onBeforeSubmit", "onError", "onAfterSubmit"):
        @register_form_event(f"{form_id}.{event}")
        async def _h(ctx, _event=event):  # noqa: ANN001
            sink.append(ctx.event)
            return EventResolution()
    return FormEventsConfig(
        onBeforeSubmit=FormEventBinding(handler_ref=f"{form_id}.onBeforeSubmit"),
        onError=FormEventBinding(handler_ref=f"{form_id}.onError"),
        onAfterSubmit=FormEventBinding(handler_ref=f"{form_id}.onAfterSubmit"),
    )

# FILL IN: _make_form(...), _FakeSink/_FakeSinkFactory (copy from test_submit_path_branch.py:85-126),
#          _make_handler(form, *, storage=None, sink_factory=None, forwarder=None, partial_store=None)
#          — bounded by "FormAPIHandler.__init__ kwargs listed in the Codebase Contract"
```
**Why this shape**: the helpers replicate existing, proven request mocks so the suite needs no
new fixtures; the event recorder pins FEAT-188 ordering by observation.

### `test_submission_pipeline_parity.py` (CREATE, continued — test classes)
```python
class TestSinkExclusive: ...        # FILL IN: Scope item 1 (tabular flatten vs document nest; store never awaited)
class TestGenericStorage: ...       # FILL IN: Scope item 2 (FormSubmission fields pinned)
class TestSinkErrorMapping: ...     # FILL IN: Scope item 3 (503+Retry-After / 422 / 501; onError recorded; nothing stored)
class TestLifecycleOrder: ...       # FILL IN: Scope item 4 (success / validation-failure / abort sequences)
class TestForwarder: ...            # FILL IN: Scope item 5 (forward awaited once with (outbound, form.submit); failure → 200)
class TestPartialMergeCleanup: ...  # FILL IN: Scope item 6 (merge precedence; delete only on success)
class TestUnknownFields: ...        # FILL IN: Scope item 7 (reject / keep / drop)
class TestResponseShape: ...        # FILL IN: Scope item 8 (exact _RESPONSE_KEYS)
class TestA2UIBranch: ...           # FILL IN: Scope item 9 (confirmation / validation_errors envelopes)
```
**Why**: one class per invariant gives TASK-4224 a precise failure signal if the extraction drifts.

### FILL IN checklist
- [ ] `_make_request` — confirm the mock satisfies auth/tenant helpers; bounded by "never patch handler internals"
- [ ] helpers `_make_form`, `_FakeSink`, `_FakeSinkFactory`, `_make_handler`; bounded by the contract
- [ ] the nine test classes; bounded by Scope items 1–9 (observable behaviour only)

---

## Acceptance Criteria

- [ ] All nine behaviours in Scope are asserted and the suite passes against the CURRENT `submit_data` (no source changes in this task).
- [ ] No import of `SubmissionPipeline` or any FEAT-649 symbol.
- [ ] No private handler helper is asserted directly (only calls on injected collaborators, events and responses).
- [ ] `ruff check packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline_parity.py` passes.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline_parity.py -q`

---

## Test Specification

The file IS the test specification (see blueprint). Minimum case list:

```python
class TestSinkExclusive:
    async def test_tabular_flatten_and_store_never_called(self): ...
    async def test_document_family_uses_nest(self): ...
class TestGenericStorage:
    async def test_store_called_once_with_submission(self): ...
class TestSinkErrorMapping:
    async def test_unavailable_503_retry_after(self): ...
    async def test_mismatch_422(self): ...
    async def test_not_capable_501(self): ...
class TestLifecycleOrder:
    async def test_success_sequence(self): ...          # ["onBeforeSubmit", "onAfterSubmit"]
    async def test_validation_failure_sequence(self): ...  # ["onBeforeSubmit", "onError"], 422
    async def test_abort_not_routed_to_onerror(self): ...
class TestForwarder:
    async def test_forward_called_and_reported(self): ...
    async def test_forward_failure_still_200(self): ...
class TestPartialMergeCleanup:
    async def test_merge_submitted_wins_and_delete_on_success(self): ...
    async def test_no_delete_on_422(self): ...
class TestUnknownFields:
    async def test_reject_422_unknown(self): ...
    async def test_keep_stores_extra_data(self): ...
    async def test_drop_discards(self): ...
class TestResponseShape:
    async def test_exact_keys(self): ...
class TestA2UIBranch:
    async def test_confirmation_envelope(self): ...
    async def test_validation_errors_envelope(self): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** at the path listed above (§3 Module 9, §7 "Behaviour-preserving extraction first", AC9)
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — read `api/handlers.py:1498-1968` in full before writing assertions
5. **Update status** in `sdd/tasks/index/audio-form-interaction-workflow.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the blueprint, complete every `# FILL IN:` marker
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`; every test must pass against today's code
8. **Commit the code** — stage only the file this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4221 audio-form-interaction-workflow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
