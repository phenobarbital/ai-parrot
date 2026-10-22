---
type: feature
base_branch: dev
projects: [parrot-formdesigner]
tags: [forms, public-forms, anonymous-submission, form-designer]
---

# Feature Specification: FormDesigner public response controls

**Feature ID**: FEAT-730
**Date**: 2026-10-22
**Author**: Juan Francisco Ruffato (with Claude)
**Status**: draft
**Target version**: 1.3.x (next minor after FEAT-728)

> Cross-repo initiative, one spec per repo (decided 2026-10-22):
> **FEAT-730** (this spec, ai-parrot / parrot-formdesigner) →
> **FEAT-796** fieldsync `sdd/specs/public-forms.spec.md` →
> **FEAT-797** navigator-svelte `sdd/specs/svelte-public-forms.spec.md`.
> Decisions source: fieldsync `sdd/proposals/public-forms.brainstorm.md`
> (accepted, Option A). Deploy order: FEAT-730 (ai-parrot + ai-parrot-server
> lockstep release) → FEAT-796 → FEAT-797.

---

## 1. Motivation & Business Requirements

### Problem Statement

Admins want to build a form in the Form Designer, publish it, and share a link
that **anyone** can fill in — customers, retailer staff, event attendees —
people without a Navigator account. Google-Forms-style public forms, with the
answers landing next to the programme's other data.

FEAT-241 (`sdd/specs/formdesigner-public-forms.spec.md`, done 2026-06-16)
already gives us the auth half: `FormSchema.is_public` (`core/schema.py:483`)
makes five URLs auth-exempt (`services/public_forms.py:13-53`) and the
registry toggle/exclude-provider keeps navigator-auth's exclude list in sync
(`api/routes.py:578-680`). What is missing for a public form:

1. **No response controls.** There is no way to close a form, give it a close
   date, cap the number of responses, allow one response per person, or say
   what happens after submit. `FormSchema` has no such fields
   (`core/schema.py:466-491`).
2. **Anonymous file uploads fail.** `…/fields/{field_uid}/file-upload` is not
   one of the five exempt globs and its route is mounted `tenant="required"`
   (`api/routes.py:452-455`). Worse, the handler takes the blob tenant from a
   client header (`X-Parrot-Tenant`, `api/file_upload.py:238`) — acceptable for
   an authenticated caller, not for an anonymous one.
3. **The host app cannot see public submissions.** `submit_data` gives the
   host no hook after a successful store, so FieldSync (FEAT-796) cannot index
   a public submission into its response viewer.
4. **Generic storage ignores the tenant.** The pipeline builds the
   `FormSubmission` without `tenant` (`services/submission_pipeline.py:198-210`)
   and calls `submission_storage.store(submission)` with none
   (`services/submission_pipeline.py:259`), so `store()` falls back to the
   storage's default schema (`services/submissions.py:330`). A public
   submission for tenant `flexroc` lands in `navigator.fs_form_data` with
   `tenant` NULL — where neither a per-tenant count (this spec) nor FieldSync's
   viewer (`<tenant>.fs_form_data`) can find it. (Same root cause as the
   FieldSync ledger issue `a1878d37d660` for audio submissions.)

The fieldsync draft `public-stateless-forms.spec.md` (FEAT-315, Javier,
2026-06-09, never implemented) proposed a separate `PublicFormHandler` /
`setup_public_forms`; it predates FEAT-389/421/429 and is **superseded** by
this initiative. FEAT-241 is not superseded — this spec extends it.

### Goals

- G1. A typed, optional `FormSchema.public_access: PublicAccessConfig | None`
  block (FEAT-649 precedent: typed block, not `meta`). `None` = today's
  behaviour exactly.
- G2. Every control is optional and per-form: manual open/closed, close date,
  response cap, one-response-per-person by an author-chosen key question,
  completion action (message or https redirect). A form with none set is a
  valid "eternal, unlimited, multi-response" form.
- G3. Enforcement in `SubmissionPipeline` (every channel that uses it: REST
  `/data`, audio WS) with HTTP **409** and stable reason codes
  `form_closed` / `response_limit_reached` / `duplicate_response`.
- G4. Cap and uniqueness are **atomic per `form_uid`**: concurrent submits can
  neither exceed `max_responses` nor store a duplicate key.
- G5. `GET /api/v1/{tenant}/forms/{form_uid}/availability` so a client can
  render the closed state without submitting.
- G6. Anonymous file uploads on public forms (exempt glob + public-mode route +
  membership check unless public + server-decided blob tenant).
- G7. `setup_form_api(..., on_submitted=…)` post-submit callback with a typed
  `SubmittedEvent`, invoked by REST `/data` after a successful store.
- G8. Generic storage writes the submission to the declared URL tenant.

### Non-Goals (explicitly out of scope)

- Respondent identity layer (accounts, magic links, per-invitee tokens). The
  author adds name/email questions if they want them (brainstorm decision).
- Cookie / fingerprint de-duplication — uniqueness is by key question only.
- Opaque, revocable share tokens — v2, only if requested (brainstorm decision).
- Restricting field types on public forms — everything is allowed, author's
  responsibility (brainstorm decision).
- Response viewer, export, origin filter — FieldSync FEAT-796.
- Designer panel, share page, QR — navigator-svelte FEAT-797.
- Anonymous thumbnails (`…/fields/{field_uid}/thumbnail`) — see §8 Q3.
- response controls on forms that declare `persistence` (FEAT-457 sinks) — the
  count/uniqueness check cannot be made atomic over an arbitrary sink; the
  schema rejects that combination (Module 1).

---

## 2. Architectural Design

### Overview

`is_public` stays the **auth grant**, unchanged. `public_access` is the
**response policy** and is enforced on every pipeline submission of the form,
public or not.

Enforcement has two layers:

1. **Fail-fast (no lock):** at the very start of `SubmissionPipeline.submit`,
   before `onBeforeSubmit`, validation or any LLM plausibility call, reject a
   closed form (`accepting_responses is False` or `now >= closes_at`).
2. **Authoritative (atomic):** when `max_responses` or `unique_key_field` is
   set, the generic store goes through a new
   `FormSubmissionStorage.store_guarded(...)` which, inside one transaction,
   takes `pg_advisory_xact_lock(hashtextextended(form_uid::text, 0))`, counts
   the form's responses, checks the key value, and INSERTs — or raises.

Rejections are **controlled flows** (like `FormEventAbort`): they raise a new
`SubmissionRejected(reason, message, field_id=None)` and are never routed
through `onError`. `submit_data` maps it to HTTP 409
`{"error", "reason", "field_id"?}`; the audio WS maps it to an `IOFailed`.

Counting rule: a "response" is a revision-chain root —
`COALESCE(root_submission_id, submission_id) = submission_id` — so revisions
written by a host (FieldSync proxy revisions) never consume the cap.

Uniqueness rule: blank/missing key value ⇒ no check. String values compare
as SQL `lower(btrim(data->>key)) = lower(btrim($value))`; non-string JSON
values compare as `data->key = $value::jsonb`.

After a successful REST `/data` store, the handler awaits the optional
`on_submitted(SubmittedEvent)` callback; any exception is logged and
swallowed (the submit already succeeded).

### Component Diagram
```
POST /{tenant}/forms/{uid}/data ──→ FormAPIHandler.submit_data
                                         │
                                         ▼
                              SubmissionPipeline.submit
                     ┌──── 1. closed? → SubmissionRejected(form_closed)
                     │     2. onBeforeSubmit → validate → plausibility
                     │     3. persist:
                     │        persistence set → sink (unchanged)
                     │        cap/key set     → storage.store_guarded (advisory lock,
                     │                          count, key check, INSERT) ─→ ResponseLimitReached /
                     │                                                        DuplicateResponse
                     │        otherwise       → storage.store(submission, tenant=tenant)
                     ▼
              409 {error, reason, field_id?}      200 → on_submitted(SubmittedEvent) (host hook)

GET /{tenant}/forms/{uid}/availability ──→ FormAPIHandler.get_availability
                                          → evaluate_open(...) + storage.count_responses(...)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormSchema` (`core/schema.py:411`) | extends | new `public_access` field + `_validate_public_access` |
| `SubmissionPipeline.submit` (`services/submission_pipeline.py:119`) | modifies | closed check, guarded store, tenant to `store()` |
| `FormSubmissionStorage` (`services/submissions.py:122`) | extends | `count_responses`, `store_guarded` |
| `FormAPIHandler.submit_data` (`api/handlers.py:1588`) | modifies | 409 mapping, `on_submitted` call |
| `FormAPIHandler` (`api/handlers.py:111`) | extends | `on_submitted` ctor param, `get_availability` |
| `setup_form_api` (`api/routes.py:192`) | modifies | `on_submitted` param, availability route, file-upload public mode |
| `public_form_paths` (`services/public_forms.py:13`) | modifies | +2 globs (7 total) |
| `handle_file_upload` (`api/file_upload.py:169`) | modifies | membership-unless-public, blob tenant |
| `AudioFormWSHandler` submit (`api/audio_ws.py:1192`) | modifies | map `SubmissionRejected` |
| FieldSync FEAT-796 | consumer | passes `on_submitted`; relies on G8 tenant write |

### Data Models
```python
# core/public_access.py (NEW) — wire keys are these snake_case names (contract)
class CompletionAction(BaseModel):
    mode: Literal["message", "redirect"] = "message"
    message: LocalizedString | None = None     # mode == "message"; None -> client default
    redirect_url: str | None = None            # required iff mode == "redirect"; https:// only

class PublicAccessConfig(BaseModel):
    accepting_responses: bool = True
    closes_at: datetime | None = None          # tz-aware; naive rejected; compared in UTC
    max_responses: int | None = Field(default=None, ge=1)
    unique_key_field: str | None = None        # a field_id of this form (validated on FormSchema)
    completion: CompletionAction | None = None

RejectionReason = Literal["form_closed", "response_limit_reached", "duplicate_response"]

class AvailabilityState(BaseModel):            # GET /availability body
    accepting: bool
    reason: Literal["form_closed", "response_limit_reached"] | None = None
    completion: CompletionAction | None = None

# api/submission_events.py (NEW)
class SubmittedEvent(BaseModel):
    submission_id: str
    form_uid: uuid.UUID
    form_id: str
    form_version: str
    tenant: str
    anonymous: bool          # AuthContext scheme == "none" at submit time
    is_public: bool          # form.is_public at submit time
    created_at: datetime     # UTC, the stored submission's created_at
```

### New Public Interfaces
```python
setup_form_api(app, registry, *, ..., on_submitted: SubmittedCallback | None = None) -> None
SubmittedCallback = Callable[[SubmittedEvent], Awaitable[None]]

GET  /api/v1/{tenant}/forms/{form_uid}/availability -> 200 AvailabilityState | 403 | 404
POST /api/v1/{tenant}/forms/{form_uid}/data         -> 409 {"error", "reason", "field_id"?} (new status)
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Schema block | yes | models + validators fixed in §2 Data Models and the skeleton | — |
| M2: Guarded storage | yes | advisory xact lock on `hashtextextended(form_uid::text, 0)`; root-only count; SQL compare rules in §2 | — |
| M3: Pipeline enforcement | yes | order fixed in §2 Overview; exceptions fixed in skeleton | — |
| M4: HTTP surface | yes | 409 body, availability body, route modes, 7 globs fixed | — |
| M5: Post-submit callback | yes | `SubmittedEvent` fields fixed by the cross-repo contract | — |
| M6: Docs | yes | — | — |

### Module 1: Public-access schema block
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/public_access.py` (new); modifies `core/schema.py`, `core/__init__.py`
- **Responsibility**: Typed response policy + pure open/closed evaluation; `FormSchema` field and cross-field validation.
- **Depends on**: existing `LocalizedString` (`core/types.py`)
- **Interface Skeleton**:
  ```python
  # core/public_access.py (new)
  from .types import LocalizedString  # verified: core/schema.py:25 imports it from .types

  class CompletionAction(BaseModel):
      """What the respondent sees after a successful submit."""
      mode: Literal["message", "redirect"] = "message"
      message: LocalizedString | None = None
      redirect_url: str | None = None
      @model_validator(mode="after")
      def _validate_redirect(self) -> "CompletionAction":
          """mode=="redirect" requires redirect_url; redirect_url must be an absolute https:// URL
          with a host (rejects http:, javascript:, data:, relative). Raises ValueError."""

  class PublicAccessConfig(BaseModel):
      """Per-form response policy (FormSchema.public_access). None on the form = no policy."""
      accepting_responses: bool = True
      closes_at: datetime | None = None
      max_responses: int | None = Field(default=None, ge=1)
      unique_key_field: str | None = None
      completion: CompletionAction | None = None
      @field_validator("closes_at")
      @classmethod
      def _require_tz(cls, v: datetime | None) -> datetime | None:
          """Reject naive datetimes; normalize to UTC."""

  RejectionReason = Literal["form_closed", "response_limit_reached", "duplicate_response"]

  class AvailabilityState(BaseModel):
      """Body of GET …/availability."""
      accepting: bool
      reason: Literal["form_closed", "response_limit_reached"] | None = None
      completion: CompletionAction | None = None

  def evaluate_open(config: PublicAccessConfig | None, *, now: datetime) -> Literal["form_closed"] | None:
      """Return "form_closed" when accepting_responses is False or now >= closes_at, else None.
      None config -> None (open)."""

  def normalize_key_value(value: Any) -> Any | None:
      """Return None for blank/missing (None, "", whitespace-only, [] , {}), else the value
      (strings returned stripped). Used to decide whether the uniqueness check runs."""

  # core/schema.py (modifies — after line 491)
  class FormSchema(BaseModel):  # verified: core/schema.py:411
      llm_validation: LLMValidationConfig | None = None  # verified: core/schema.py:491
      # FEAT-730 — public response controls (typed block, not meta)
      public_access: PublicAccessConfig | None = None
      @model_validator(mode="after")
      def _validate_public_access(self) -> "FormSchema":
          """When public_access.unique_key_field is set it must name a field_id yielded by
          iter_all_fields() (top-level layout fields — the keys present at the top level of
          submission data) whose field_type is not GROUP/ARRAY/FILE/IMAGE/IMAGE_DROPZONE/
          MULTI_UPLOAD/SIGNATURE. When public_access sets max_responses or unique_key_field,
          persistence must be None (counting is only atomic over FormSubmissionStorage).
          Raises ValueError naming the offending field."""
  ```

### Module 2: Guarded storage
- **Path**: modifies `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py`
- **Responsibility**: Root-only response count and an atomic "check cap + key, then insert" store.
- **Depends on**: existing `FormSubmissionStorage` (`services/submissions.py:122`)
- **Interface Skeleton**:
  ```python
  # services/submissions.py (modifies — new exceptions near FormSubmission, methods after store() :313)
  class ResponseLimitReached(Exception):
      """store_guarded refused: the form already has >= max_responses root responses."""

  class DuplicateResponse(Exception):
      """store_guarded refused: another response has the same key value."""
      field_id: str

  class FormSubmissionStorage:  # verified: services/submissions.py:122
      async def count_responses(self, form_uid: uuid.UUID, *, tenant: str | None = None) -> int:
          """Count revision-chain roots for form_uid in the tenant's table:
          COALESCE(root_submission_id, submission_id) = submission_id. Tenant resolution as store()."""

      async def store_guarded(
          self,
          submission: FormSubmission,
          *,
          tenant: str | None = None,
          max_responses: int | None = None,
          unique_key_field: str | None = None,
          unique_value: Any | None = None,
      ) -> str:
          """One connection, one transaction: pg_advisory_xact_lock(hashtextextended(form_uid::text, 0));
          if max_responses: count roots, raise ResponseLimitReached when count >= max_responses;
          if unique_key_field and unique_value is not None: raise DuplicateResponse when a row of the
          same form_uid matches (str: lower(btrim(data->>key)) = lower(btrim($v)); else data->key = $v::jsonb);
          then INSERT exactly as store() (same _insert_sql / parameter order). Returns submission_id."""
  ```

### Module 3: Pipeline enforcement
- **Path**: modifies `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py`
- **Responsibility**: Fail-fast closed check; guarded store when the policy needs it; stamp the URL tenant on the generic store; translate storage refusals into `SubmissionRejected`.
- **Depends on**: M1, M2
- **Interface Skeleton**:
  ```python
  # services/submission_pipeline.py (modifies :38 __all__, adds class, modifies submit() :119)
  __all__ = [..., "SubmissionRejected"]  # verified: submission_pipeline.py:38

  class SubmissionRejected(Exception):
      """Response-policy refusal (HTTP 409). Controlled flow — never dispatched to onError."""
      def __init__(self, reason: RejectionReason, message: str, *, field_id: str | None = None) -> None: ...
      reason: RejectionReason
      field_id: str | None

  class SubmissionPipeline:  # verified: submission_pipeline.py:72
      async def submit(self, form, data, *, tenant, ...) -> SubmitOutcome:  # verified: :119
          """(1) evaluate_open(form.public_access, now=utcnow()) == "form_closed" -> raise
          SubmissionRejected("form_closed") BEFORE onBeforeSubmit (anchor :137 / :146).
          (2) unchanged validate / plausibility / metadata.
          (3) FormSubmission gets tenant=tenant (anchor :206 block) and the generic branch
          (:258-260) calls store(submission, tenant=tenant) — or, when public_access sets
          max_responses or unique_key_field, store_guarded(...) with
          unique_value = normalize_key_value(data[unique_key_field]).
          ResponseLimitReached -> SubmissionRejected("response_limit_reached");
          DuplicateResponse -> SubmissionRejected("duplicate_response", field_id=key).
          If the policy needs counting and submission_storage is None -> SubmitSinkError(status=501).
          SubmissionRejected is re-raised untouched by the outer except (:309)."""
  ```

### Module 4: HTTP surface (409, availability, exempt paths, anonymous file upload, audio WS)
- **Path**: modifies `api/handlers.py`, `api/routes.py`, `services/public_forms.py`, `api/file_upload.py`, `api/audio_ws.py`
- **Responsibility**: Expose the policy over HTTP and let anonymous respondents upload files to public forms.
- **Depends on**: M1, M2, M3
- **Interface Skeleton**:
  ```python
  # api/handlers.py (modifies)
  class FormAPIHandler:  # verified: api/handlers.py:111
      async def submit_data(self, request) -> web.Response:  # verified: :1588
          """New except arm next to the submit-side PlausibilityBlocked (:1789, 2nd occurrence):
          SubmissionRejected -> _reply({"error": msg, "reason": reason, ["field_id": id]}, status=409)."""
      async def get_availability(self, request: web.Request) -> web.Response:
          """GET /{tenant}/forms/{form_uid}/availability. Resolve form like get_form (:944-958):
          404 missing, _assert_form_tenant, enforce_membership_unless_public. Then
          AvailabilityState(accepting, reason, completion=public_access.completion):
          form_closed via evaluate_open; response_limit_reached when max_responses set and
          submission_storage.count_responses(form_uid, tenant=tenant) >= max_responses.
          public_access None -> {"accepting": true, "reason": null, "completion": null}."""

  # api/routes.py (modifies, after the /data route :426-429)
  app.router.add_get(f"{tp}/forms/{{form_uid}}/availability",
                     _wrap_auth(handler.get_availability, tenant="public"))
  # file-upload route :452-455 becomes tenant="public":
  _wrap_auth(file_upload_module.handle_file_upload, tenant="public")

  # services/public_forms.py (modifies :47-53) — returns SEVEN globs:
  def public_form_paths(form_uid: str, tenant: str, base_path: str = "/api/v1") -> list[str]:
      """…existing five + f"{base}/availability" + f"{base}/fields/*/file-upload"."""

  # api/file_upload.py (modifies handle_file_upload :169)
  async def handle_file_upload(request: web.Request) -> web.Response:
      """After the form is resolved (:210, 1st occurrence): enforce_membership_unless_public(request,
      form, tenant) — a private form keeps requiring tenant membership now that the route is
      public-mode. Blob tenant (:238): an anonymous caller (no authenticated session) ALWAYS uses
      the declared URL tenant; X-Parrot-Tenant is honoured only for authenticated callers."""

  # api/audio_ws.py (modifies the submit except chain, 2nd PlausibilityBlocked occurrence :1207)
  except SubmissionRejected as exc:
      return IOFailed(type="_io_failed", request=item.type, code=exc.reason.upper(), detail=str(exc))
  ```

### Module 5: Post-submit callback
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/submission_events.py` (new); modifies `api/handlers.py`, `api/routes.py`, `api/__init__.py` (export)
- **Responsibility**: Typed host hook after a successful REST `/data` store.
- **Depends on**: M3 (tenant-stamped store)
- **Interface Skeleton**:
  ```python
  # api/submission_events.py (new)
  class SubmittedEvent(BaseModel):
      """Emitted after a successful REST /data store. Never on rejection or failure."""
      submission_id: str
      form_uid: uuid.UUID
      form_id: str
      form_version: str
      tenant: str
      anonymous: bool
      is_public: bool
      created_at: datetime
  SubmittedCallback = Callable[[SubmittedEvent], Awaitable[None]]

  # api/routes.py — setup_form_api (verified: :192), new kwarg after teams_renderer (:214)
  def setup_form_api(..., teams_renderer=None, on_submitted: SubmittedCallback | None = None) -> None:
      """Passes on_submitted to FormAPIHandler (construction :348-361)."""

  # api/handlers.py — FormAPIHandler.__init__ (verified: :145), new kwarg after sink_factory (:158)
  def __init__(self, ..., sink_factory=None, on_submitted: SubmittedCallback | None = None) -> None: ...
  # submit_data, just before `return _reply(body_out, status=200)` (:1811):
  #   when self._on_submitted is set and outcome.stored_in != "none": await it with
  #   SubmittedEvent(anonymous=_auth_ctx.scheme == "none", is_public=form.is_public,
  #   created_at=<stored submission created_at>, ...); any exception -> logger.warning, swallowed.
  ```
  `SubmitOutcome` (`services/submission_pipeline.py:41`) gains `created_at: datetime | None = None`
  so the handler can report the stored timestamp without re-reading storage.

### Module 6: Documentation
- **Path**: `docs/formdesigner-public-form-controls.md` (new)
- **Responsibility**: Author-facing description of `public_access`, the 409 codes, `/availability`, the seven exempt globs, `on_submitted`, and the deploy note (host must pass `on_submitted`; existing public forms need nothing).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_public_access_defaults_none` | M1 | `FormSchema` without the block round-trips with `public_access is None` |
| `test_redirect_requires_https` | M1 | `http:`, `javascript:`, relative, missing URL on redirect mode → ValueError |
| `test_closes_at_naive_rejected` | M1 | naive datetime rejected; aware normalized to UTC |
| `test_unique_key_must_exist_and_be_scalar` | M1 | unknown field_id / GROUP / FILE key → ValueError |
| `test_cap_with_persistence_rejected` | M1 | `max_responses` + `persistence` → ValueError |
| `test_evaluate_open` | M1 | manual close, past/future `closes_at`, None config |
| `test_public_form_paths_seven` | M4 | 7 globs incl. availability and `fields/*/file-upload` |
| `test_submit_closed_before_validation` | M3 | closed form → `SubmissionRejected("form_closed")`, validator and plausibility never called, onError not dispatched |
| `test_generic_store_receives_tenant` | M3 | `store`/`store_guarded` called with the URL tenant (mutation: drop the kwarg → RED) |
| `test_limit_maps_to_rejection` / `test_duplicate_maps_to_rejection` | M3 | storage exceptions → reason codes; `field_id` set for duplicate |
| `test_submit_data_409_body` | M4 | 409 body shape for each reason |
| `test_availability_states` | M4 | open / closed / limit / no block; private form anonymous → 403/404 like get_form |
| `test_file_upload_anonymous_public` | M4 | public form, no session → 200; header `X-Parrot-Tenant` ignored |
| `test_file_upload_private_requires_member` | M4 | private form on public-mode route → TenantForbidden |
| `test_audio_ws_rejection_ioFailed` | M4 | `SubmissionRejected` → `IOFailed(code="FORM_CLOSED")` |
| `test_on_submitted_called_once` | M5 | success → one `SubmittedEvent` with `anonymous`/`is_public`; rejection → not called |
| `test_on_submitted_error_swallowed` | M5 | callback raises → still 200 |

### Integration Tests
| Test | Description |
|---|---|
| `test_store_guarded_cap_concurrent` | real Postgres: 20 concurrent `store_guarded` with `max_responses=5` → exactly 5 rows, 15 `ResponseLimitReached` |
| `test_store_guarded_unique_concurrent` | real Postgres: concurrent same key (`"A@x.com "` vs `"a@X.com"`) → exactly 1 row |
| `test_count_responses_roots_only` | revision rows (root_submission_id ≠ submission_id) do not count |

Postgres integration tests follow the existing pattern of the package's
storage tests (skip cleanly when no DSN is configured, never silently pass).

### Validation Contract

tests:
- packages/parrot-formdesigner/tests/unit/test_public_access_schema.py
- packages/parrot-formdesigner/tests/unit/services/test_public_forms.py
- packages/parrot-formdesigner/tests/unit/services/test_submission_pipeline_public_access.py
- packages/parrot-formdesigner/tests/unit/api/test_public_form_controls_http.py
- packages/parrot-formdesigner/tests/unit/api/test_file_upload_public.py
- packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_public_access.py
- packages/parrot-formdesigner/tests/integration/test_store_guarded.py
markers: none

### Test Data / Fixtures
```python
@pytest.fixture
def controlled_form() -> FormSchema:
    """is_public=True, one TEXT 'email' field, public_access(max_responses=5, unique_key_field='email')."""
```

---

## 5. Acceptance Criteria

- [ ] AC1 — A form with `public_access = None` behaves byte-for-byte as before (existing public-form, pipeline and file-upload tests green).
- [ ] AC2 — `accepting_responses=false` or `now >= closes_at` ⇒ `POST …/data` returns 409 `reason=form_closed`, no LLM call, nothing stored.
- [ ] AC3 — With `max_responses=N`, the (N+1)th root response returns 409 `response_limit_reached`, including under concurrency (integration test); revisions never count.
- [ ] AC4 — With `unique_key_field`, a second response with the same normalized value returns 409 `duplicate_response` + `field_id`; a blank value is never checked.
- [ ] AC5 — `GET …/availability` returns `{accepting, reason, completion}` and is auth-exempt for public forms; a private form answers exactly like `GET …/forms/{form_uid}` (403/404).
- [ ] AC6 — `public_form_paths` returns 7 globs; both the toggle callback and the exclude provider register them (no code change needed beyond the helper).
- [ ] AC7 — An anonymous caller can upload to an upload field of a public form; the blob lands under the declared URL tenant regardless of `X-Parrot-Tenant`; a private form still requires membership.
- [ ] AC8 — Generic-storage submissions from the pipeline are written to `<URL tenant>.<table>` with `tenant` set.
- [ ] AC9 — `setup_form_api(on_submitted=cb)` calls `cb` exactly once per successful REST `/data` store with the contract's `SubmittedEvent`; never on 4xx/5xx; a raising callback never changes the response.
- [ ] AC10 — `CompletionAction.redirect_url` accepts only absolute `https://` URLs.
- [ ] AC11 — Docs page added; package version bumped; ai-parrot-server released in lockstep.

---

## 6. Codebase Contract

> Verified against ai-parrot `dev` @ `d5f75d3e2` (2026-10-22). Paths are
> relative to `packages/parrot-formdesigner/src/parrot_formdesigner/` unless
> stated.

### Verified Imports
```python
from parrot_formdesigner.core.schema import FormSchema              # core/schema.py:411
from parrot_formdesigner.core.types import FieldType, LocalizedString  # core/schema.py:25
from parrot_formdesigner.core.llm_validation import LLMValidationConfig  # typed-block precedent, core/llm_validation.py:28
from parrot_formdesigner.services.public_forms import public_form_paths  # services/public_forms.py:13
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage  # :50, :122
from parrot_formdesigner.services.submission_pipeline import (
    SubmissionPipeline, SubmitOutcome, SubmitSinkError, ValidationFailed, PlausibilityBlocked,
)  # __all__ at services/submission_pipeline.py:38
from parrot_formdesigner.core.tenant import declared_tenant, enforce_membership_unless_public  # core/tenant.py:166, :189
from parrot_formdesigner.services.auth_context import AuthContext   # services/auth_context.py:20
from parrot_formdesigner.api import setup_form_api                  # used by fieldsync/forms.py:116
```

### Existing Class Signatures
```python
# core/schema.py
class FormSchema(BaseModel):                                   # line 411
    is_public: bool = False                                    # line 483
    persistence: FormPersistenceConfig | None = None           # line 485
    voice: VoiceFormConfig | None = None                       # line 489
    llm_validation: LLMValidationConfig | None = None          # line 491
    def iter_all_fields(self) -> Iterator[FormField]           # line 493 (top-level layout fields)
    def iter_fields_recursive(self) -> Iterator[FormField]
    @model_validator(mode="after") def _validate_persistence(self) -> FormSchema  # line 587

# services/public_forms.py
def public_form_paths(form_uid: str, tenant: str, base_path: str = "/api/v1") -> list[str]  # line 13; 5 globs :47-53

# services/submissions.py
class FormSubmission(BaseModel):  # line 50 — tenant: str | None = None (:108), root_submission_id, revision
class FormSubmissionStorage:      # line 122
    def _resolve_schema(self, tenant: str | None) -> str        # line 163
    def _qualified(self, tenant: str | None) -> str             # line 170
    def _insert_sql(self, tenant: str | None) -> str            # line 260
    async def store(self, submission: FormSubmission, *, tenant: str | None = None) -> str  # line 313
    # store(): effective_tenant = tenant if tenant is not None else submission.tenant  (line 330)
    # self._pool.acquire() (line 333); table has submission_id UNIQUE, form_uid, data JSONB,
    # root_submission_id, revision, created_at (DDL lines 188-212)

# services/submission_pipeline.py
class SubmitOutcome(BaseModel)       # line 41
class SubmitSinkError(Exception)     # line 63 — (message, *, status, headers=None)
class SubmissionPipeline:            # line 72
    async def submit(self, form, data, *, tenant: str | None, user_id, locale, context, extra_data,
                     auth_context, merge_session_id, plausibility=None, request=None,
                     visit_context=None, submission_id=None) -> SubmitOutcome   # line 119
    # auth = auth_context or AuthContext(scheme="none")          line 137
    # onBeforeSubmit dispatch                                    line 146
    # FormSubmission(...) built WITHOUT tenant                   lines 198-210
    # generic branch: await self.submission_storage.store(submission)   line 259
    # outer except re-raises (FormEventAbort, ValidationFailed, SubmitSinkError, PlausibilityBlocked)  line 309

# api/handlers.py
class FormAPIHandler:                                           # line 111
    def __init__(self, registry, client=None, submission_storage=None, forwarder=None,
                 partial_store=None, org_graph_service=None, project_service=None,
                 rbac_service=None, workday_adapter=None, venue_service=None,
                 rbac_enforcing=False, sink_factory=None) -> None   # line 145
    def _get_tenant(self, request) -> str                         # line 367 (URL-declared tenant)
    def _build_auth_context(self, request) -> AuthContext         # line 453 (defaults scheme="none")
    async def get_form(self, request) -> web.Response             # line 944 (404 / _assert_form_tenant / enforce_membership_unless_public)
    async def submit_data(self, request) -> web.Response          # line 1588
    # pipeline.submit(... tenant=tenant, user_id=None ...)         line 1769
    # except PlausibilityBlocked (submit copy)                     line 1789
    # return _reply(body_out, status=200)                          line 1811

# api/routes.py
def _wrap_auth(handler, *, tenant: str = "required")              # line 84 — modes required|public|none
def setup_form_api(app, registry, *, ..., teams_renderer=None) -> None   # line 192 (last kwarg :214)
# handler = FormAPIHandler(...)                                   lines 348-361
# app["submission_pipeline"] = handler._build_submission_pipeline()  line 365
# tp = f"{bp}/{{tenant}}"                                          line 375
# /data route, tenant="public"                                     lines 426-429
# file-upload route, tenant="required" (default)                   lines 452-455
# toggle callback / exclude provider use public_form_paths          lines 578-680

# api/file_upload.py
async def handle_file_upload(request) -> web.Response            # line 169
# form = await registry.get(form_uid, tenant=tenant)              line 210 (1st of 2)
# blob_tenant = request.headers.get("X-Parrot-Tenant") or tenant  line 238

# api/audio_ws.py
# outcome = await self._pipeline_for().submit(...)                line 1192
# except PlausibilityBlocked as exc: -> IOFailed(...)             line 1207 (2nd of 2)

# core/tenant.py
def enforce_membership_unless_public(request, form, tenant) -> None  # line 189 (returns when form.is_public)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PublicAccessConfig` | `FormSchema` | new field after `llm_validation` | `core/schema.py:491` |
| closed check | `SubmissionPipeline.submit` | before `onBeforeSubmit` | `submission_pipeline.py:137-148` |
| `store_guarded` | generic branch | replaces `store(submission)` when policy needs it | `submission_pipeline.py:258-260` |
| `SubmissionRejected` → 409 | `submit_data` | new except arm | `api/handlers.py:1789` |
| `get_availability` | router | `_wrap_auth(..., tenant="public")` | `api/routes.py:426-429` |
| 7 globs | navigator-auth exclusions | `public_form_paths` | `services/public_forms.py:47-53` |
| `on_submitted` | `FormAPIHandler` | ctor kwarg via `setup_form_api` | `api/routes.py:348-361` |
| FieldSync FEAT-796 | `setup_form_api(on_submitted=…)` | kwarg | fieldsync `fieldsync/forms.py:123-130` |

### Does NOT Exist (Anti-Hallucination)
- ~~`FormSchema.public_access` / `closes_at` / `max_responses` / any response control~~ — none exist.
- ~~`FormSubmissionStorage.count_responses` / `store_guarded` / any count or uniqueness query~~ — store() is a bare INSERT; reads are `get_submission` (:420) and `list_revisions` (:442) only.
- ~~`SubmissionRejected`, `SubmittedEvent`, `on_submitted`~~ — new in this spec.
- ~~a post-submit host hook in `setup_form_api`~~ — the only after-submit seam is the per-form `onAfterSubmit` lifecycle binding (`submission_pipeline.py:288-297`), configured per form, not by the host.
- ~~`/availability` route~~ — does not exist.
- ~~`PublicFormHandler`, `setup_public_forms`~~ — proposed by fieldsync's FEAT-315 draft, never built.
- ~~`/api/v1/t/{tenant}/…`~~ — `/t/` removed by FEAT-429; prefix is `{bp}/{tenant}` (`api/routes.py:375`).
- ~~anonymous thumbnails~~ — `…/thumbnail` stays authenticated (§8 Q3).
- ~~Response-control enforcement on FieldSync's execution submit~~ — FieldSync's execution path writes `submission_storage.store(..., tenant=…)` directly (fieldsync `fieldsync/domains/execution/services.py:645`), not through `SubmissionPipeline`.

### Edit Sites (Blueprint Anchors)

Verified against: `d5f75d3e2`. Paths under `packages/parrot-formdesigner/src/parrot_formdesigner/` unless they start with `packages/` or `docs/`.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `core/public_access.py` | CREATE | — | — | — |
| `core/schema.py` | MODIFY | `from .voice import VoiceFormConfig` | `core/schema.py:27` | 1 |
| `core/schema.py` | MODIFY | `    llm_validation: LLMValidationConfig \| None = None` | `core/schema.py:491` | 1 |
| `core/schema.py` | MODIFY | `    def _validate_persistence(self) -> FormSchema:` | `core/schema.py:587` | 1 |
| `core/__init__.py` | MODIFY | `from .llm_validation import (` | `core/__init__.py:60` | 1 |
| `core/__init__.py` | MODIFY | `    "LLMValidationConfig",` | `core/__init__.py:94` | 1 |
| `services/submissions.py` | MODIFY | `    async def store(` | `services/submissions.py:313` | 1 |
| `services/submission_pipeline.py` | MODIFY | `__all__ = ["SubmissionPipeline", "SubmitOutcome", "SubmitSinkError", "ValidationFailed", "PlausibilityBlocked"]` | `:38` | 1 |
| `services/submission_pipeline.py` | MODIFY | `        auth = auth_context or AuthContext(scheme="none")` | `:137` | 1 |
| `services/submission_pipeline.py` | MODIFY | `                created_at=datetime.now(timezone.utc),` | `:206` | 1 |
| `services/submission_pipeline.py` | MODIFY | `                await self.submission_storage.store(submission)` | `:259` | 1 |
| `services/public_forms.py` | MODIFY | `        f"{base}/validate",` | `:52` | 1 |
| `api/submission_events.py` | CREATE | — | — | — |
| `api/handlers.py` | MODIFY | `        sink_factory: "SinkFactory \| None" = None,` | `:158` | 1 |
| `api/handlers.py` | MODIFY | 3 lines, submit copy: `        except PlausibilityBlocked as exc:` / `            return _reply(` / `                {"error": f"Answer plausibility check unavailable: {exc.reason}", "code": "PLAUSIBILITY_UNAVAILABLE"},` | `:1789-1791` | 2 (bare line; `/validate` copy at `:1166` returns `JSONResponse`) |
| `api/handlers.py` | MODIFY | `        return _reply(body_out, status=200)` | `:1811` | 1 |
| `api/handlers.py` | MODIFY | `    async def get_form(self, request: web.Request) -> web.Response:` (insert `get_availability` after get_form) | `:944` | 1 |
| `api/routes.py` | MODIFY | `    teams_renderer: "AbstractFormRenderer \| None" = None,` | `:214` | 1 |
| `api/routes.py` | MODIFY | `        sink_factory=sink_factory,` | `:360` | 1 |
| `api/routes.py` | MODIFY | `        _wrap_auth(handler.submit_data, tenant="public"),` | `:428` | 1 |
| `api/routes.py` | MODIFY | `        _wrap_auth(file_upload_module.handle_file_upload),` | `:454` | 1 |
| `api/file_upload.py` | MODIFY | 2 lines: `    form = await registry.get(form_uid, tenant=tenant)` / `    if form is None:` inside `handle_file_upload` | `:210-211` | 2 (bare line; other copy at `:647`) |
| `api/file_upload.py` | MODIFY | `    blob_tenant: str \| None = request.headers.get("X-Parrot-Tenant") or tenant` | `:238` | 1 |
| `api/audio_ws.py` | MODIFY | 2 lines: `        except PlausibilityBlocked as exc:` / `            return IOFailed(type="_io_failed", request=item.type, code="PLAUSIBILITY_UNAVAILABLE", detail=exc.reason)` | `:1207-1208` | 2 (bare line; other copy at `:1157`) |
| `api/__init__.py` | MODIFY | `__all__ = ["setup_form_api"]` (add `SubmittedEvent`) | `api/__init__.py:24` | 1 |
| `packages/parrot-formdesigner/tests/unit/test_public_access_schema.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/tests/unit/services/test_public_forms.py` | MODIFY | `from parrot_formdesigner.services.public_forms import public_form_paths` | `test_public_forms.py:15` | 1 |
| `packages/parrot-formdesigner/tests/unit/services/test_submission_pipeline_public_access.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/tests/unit/api/test_public_form_controls_http.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/tests/unit/api/test_file_upload_public.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_public_access.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/tests/integration/test_store_guarded.py` | CREATE | — | — | — |
| `docs/formdesigner-public-form-controls.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Typed config block in its own `core/<name>.py` module, exported from `core/__init__.py` — copy `core/llm_validation.py` / `LLMValidationConfig`.
- Advisory lock idiom already in the monorepo: `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))` inside `async with conn.transaction()` (`packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py:355-359`).
- Controlled-flow exceptions bypass `onError` exactly like `FormEventAbort` (`api/handlers.py:1782-1784`).
- All SQL identifiers via the existing `_qualified()` / `validate_identifier` helpers; the key name is a bind parameter (`data->>$n`), never interpolated.

### Known Risks / Gotchas
- **Tenant write change (G8) is a behaviour change.** Non-public authenticated REST `/data` callers that today land in the default schema will land in `<tenant>.<table>`. The host must have provisioned that table (FieldSync's execution path already writes there — fieldsync `execution/services.py:645`). `store()` does not auto-create tables: a missing per-tenant table becomes a 5xx instead of a silent mis-filed row. See §8 Q1.
- **`anonymous` is derived from `AuthContext.scheme == "none"`** (contract). A caller authenticated only by a session cookie, with no `Authorization` header and no `request["auth_context"]`, is also reported `anonymous=True` (`_build_auth_context` defaults, `api/handlers.py:453-480`). Hosts using `on_submitted` should also check `is_public`. §8 Q2.
- **Response-control enforcement covers pipeline channels only** (REST `/data`, audio WS). A host that writes `submission_storage.store()` directly (FieldSync execution) is not subject to `public_access`; its rows still count toward `max_responses` and uniqueness because they share the table.
- **Uniqueness normalization is SQL `lower(btrim())` on both sides**, not Python `casefold()`: identical for ASCII and most scripts, differs only for special-case folds (e.g. `ß`). Chosen so the comparison happens inside the locked transaction without a second normalized column.
- **Legacy rows:** submissions already filed in the default schema (`navigator.fs_form_data`, tenant NULL) are not migrated and are invisible to `count_responses` for a tenant. Existing public forms with no `public_access` are unaffected.
- **FEAT-728 overlap.** FEAT-728 (`formbuilder-llm-validation-enforcement`, approved, 7 tasks pending) edits the same `submission_pipeline.py`, `api/handlers.py` submit block (`:1767`, `:1789-1791`, `:1810`), `api/routes.py:428` and `api/audio_ws.py:1192`. Land FEAT-730 after FEAT-728 merges (or rebase onto it); `/sdd-task` must re-grep every anchor.
- **Closed check precedes `onBeforeSubmit`**, so a lifecycle handler can never "reopen" a closed form by rewriting the payload.
- **Exempt-path glob `fields/*/file-upload`** relies on navigator-auth's fnmatch, where `*` also matches `/`; harmless here because the route table bounds the shape, but do not reuse the glob for a looser prefix.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `navigator-auth` | `>=0.20.11` (already required) | `register_exclusions` / `add_exclude_provider` |
| PostgreSQL | ≥ 11 | `hashtextextended` |

---

## 8. Open Questions

- [x] Who authors public forms? — *Resolved in brainstorm*: admins, in the existing Form Designer.
- [x] How is the respondent identified? — *Resolved in brainstorm*: not our concern; the author adds questions (name/email) if needed.
- [x] Which response controls in v1? — *Resolved in brainstorm*: open/close, close date, response cap, one-per-person, thank-you/redirect — all optional per form.
- [x] How is "one response per person" enforced? — *Resolved in brainstorm*: author picks a question as unique key; backend rejects duplicates.
- [x] Which field types are allowed in public forms? — *Resolved in brainstorm*: all, author's responsibility.
- [x] Link format? — *Resolved in brainstorm*: v1 keeps `/share/form/{tenant}/{form_uid}` (svelte); opaque token only if requested later.
- [x] Typed block or `meta`? — *Resolved (contract 2026-10-22)*: typed `public_access`, FEAT-649 precedent.
- [ ] Q1. G8 (tenant-stamped generic store): are there non-FieldSync hosts calling REST `/data` whose per-tenant `fs_form_data` table does not exist? If so, gate G8 behind a `setup_form_api` flag instead of changing it unconditionally. — *Owner: Jesús Lara*
- [ ] Q2. Should `SubmittedEvent.anonymous` be derived from the navigator session (no authenticated user) rather than `AuthContext.scheme`? The contract fixes `scheme == "none"`; changing it needs FEAT-796 to agree. — *Owner: Juan*
- [x] Q3. Anonymous thumbnails — *Resolved 2026-10-22 (Juan)*: `…/thumbnail` stays authenticated. The share page (navigator-svelte FEAT-797 M4) shows a LOCAL preview of the picked file and never requests `thumbnail_url`; the admin sees the photo through FieldSync's authenticated viewer.
- [ ] Q4. Upload abuse ceiling for anonymous callers (size/count per request) beyond the field's own `constraints` — reuse the field config (current plan) or add a public cap? — *Owner: Juan*
- [x] Q5. How do photo/file answers travel from the share page? — *Resolved 2026-10-22 (Juan)*: upload first — the share page uploads each file on pick to `…/fields/{field_uid}/file-upload` (FEAT-460 design, opened anonymously by M4 of this spec) through a same-origin SvelteKit proxy, and sends parrot's `FileEnvelope` (`data_url` stripped) in `/data`. The inline-base64 path of FEAT-357 is retired for the share page. M4's anonymous file-upload is therefore REQUIRED for v1, not optional.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (not run for cross-repo split; contract fixed by fieldsync FEAT-796 brainstorm) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree for FEAT-730; the `sdd-coder` engine gives each task its own sub-worktree.
- **Module dependency graph**:
  - M3 → M1 (imports `PublicAccessConfig`, `evaluate_open`, `normalize_key_value`) and M3 → M2 (`store_guarded`, `ResponseLimitReached`, `DuplicateResponse`).
  - M4 → M1/M2/M3 (`AvailabilityState`, `count_responses`, `SubmissionRejected`).
  - M5 → M3 (`SubmitOutcome.created_at`, tenant-stamped store).
  - M1 and M2 have no edge between them → concurrent. M6 last.
- **Shared files**: `api/handlers.py` (M4, M5), `api/routes.py` (M4, M5), `services/submission_pipeline.py` (M3, M5 — `SubmitOutcome.created_at`) → their tasks serialize.
- **Exclusive resources**: none (no migration — `store_guarded` uses existing columns; version bump + lockstep ai-parrot-server release at the end).
- **Cross-feature dependencies**: FEAT-728 should merge first (same submit block). Downstream: fieldsync FEAT-796 and navigator-svelte FEAT-797 consume this release.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-22 | Juan Francisco Ruffato (with Claude) | Initial draft from fieldsync brainstorm `public-forms` (Option A) and the cross-repo contract |
| 0.2 | 2026-10-22 | Juan Francisco Ruffato (with Claude) | Q3/Q5 resolved: share page uploads first through anonymous `/file-upload`; thumbnails stay authenticated |
