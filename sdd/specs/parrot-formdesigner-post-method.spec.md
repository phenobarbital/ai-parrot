# Feature Specification: Parrot FormDesigner POST Submission Pipeline

**Feature ID**: FEAT-121
**Date**: 2026-04-23
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.x (parrot-formdesigner)

> Source brainstorm: `sdd/proposals/parrot-formdesigner-post-method.brainstorm.md`
> (Recommended Option A — extend existing `/data` endpoint)

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot-formdesigner` exposes `GET /api/v1/forms/{form_id}` (+ `/schema`, `/style`, `/html`) to
render form designs, and already has a minimal `POST /api/v1/forms/{form_id}/data` endpoint
that validates payloads against the form's structural JSON schema and persists a flat JSONB row
via `FormSubmissionStorage`. That endpoint is the right spine but lacks the richer submission
semantics the platform needs:

- Strong typed validation through a Pydantic model derived from the form design (static-registered
  if present, else pre-generated offline from the JSON schema at registry warm-up).
- An **operator pipeline** — ordered, class-based async hooks (`pre_validate`, `post_validate`,
  `pre_save`, `post_save`) attached at `FormAPIHandler` init time so business rules and
  user/session enrichment (e.g. a `UserDetails` operator) can run around validation and persistence.
- A **hybrid storage schema** — fixed metadata columns (`user_id`, `org_id`, `program`, `client`,
  `status`, enrichment JSONB) alongside the existing `data JSONB` payload — so non-dynamic
  fields are queryable.
- **Fail-fast with DLQ** — failed attempts are persisted to a dead-letter table so failures can
  be debugged/retried instead of silently lost.

This feature extends the existing endpoint and storage class in place (confirmed by the user on
2026-04-23) rather than introducing a parallel submission path.

### Goals

- G1. Provide an operator pipeline `pre_validate → validate → post_validate → pre_save → store → post_save`
  wired at `FormAPIHandler.__init__` via new optional `operators=` and `pydantic_resolver=` kwargs.
- G2. Resolve a Pydantic model per `(form_id, version)` from a static registry first, then from a
  cache pre-generated offline by `datamodel-code-generator`; fall back to the current `FormValidator`
  when neither is available (preserves backward compat).
- G3. Evolve `FormSubmissionStorage` into an implementation of a new `FormResultStorage` ABC with
  `store(record, *, conn=None)` and `store_dlq(attempt, error)` methods. Extend the
  `form_submissions` table with nullable metadata columns and add a `form_submissions_dlq` sibling.
- G4. Ship a first concrete operator `UserDetails` that populates `user_id`, `org_id`, `programs`
  from the navigator-auth session.
- G5. Zero behavior change for callers that do not pass `operators=` or `pydantic_resolver=` — the
  legacy `FormValidator` path remains the default.
- G6. Atomicity: success-path insert and any in-transaction operator side-effects run under a single
  asyncpg connection/transaction; DLQ writes happen in a separate short transaction after rollback.

### Non-Goals (explicitly out of scope)

- Introducing a new route `POST /api/v1/forms/{form_id}` parallel to `/data`. Rejected in
  brainstorm Option B — see `sdd/proposals/parrot-formdesigner-post-method.brainstorm.md`.
- Read/query API on `FormResultStorage` (list, filter, paginate). Storage is write-only in v1.
- Migrating/rewriting existing rows in `form_submissions`. New columns are nullable; no data
  backfill required.
- Deprecating `FormValidator` or removing the legacy validation path. Both remain as the fallback.
- `Idempotency-Key` header support. Deferred (see §8).
- Non-Postgres backends for `FormResultStorage`. The ABC is designed to accept them later but
  only the Postgres implementation ships in v1.

---

## 2. Architectural Design

### Overview

Extend `FormAPIHandler.submit_data` in place with an opt-in operator pipeline. When either
`operators` or `pydantic_resolver` is configured at handler init, `submit_data` routes the request
through a new `_run_submission_pipeline(request, form, data, conn)` helper that:

1. Resolves a Pydantic model for the form (static registry → codegen cache → fallback to
   `FormValidator`).
2. Runs the operator pipeline around validation under a single asyncpg transaction.
3. Persists the extended `FormSubmission` (now carrying metadata + enrichment columns) via
   `FormResultStorage.store(..., conn=conn)`.
4. On any exception, rolls back the main transaction and writes a DLQ row in a separate short
   transaction, then returns a structured error response.

When neither kwarg is configured, `submit_data` keeps the current behavior byte-for-byte
(legacy `FormValidator` path), so existing deployments see no change.

### Component Diagram

```
             POST /api/v1/forms/{form_id}/data
                       │
                       ▼
             ┌─────────────────────┐
             │ FormAPIHandler      │
             │   .submit_data()    │
             └──────────┬──────────┘
                        │
          operators or pydantic_resolver set?
              ┌─────────┴─────────┐
              │ yes               │ no  (legacy path — unchanged)
              ▼                   ▼
 ┌──────────────────────┐   ┌─────────────────┐
 │ _run_submission_     │   │ FormValidator   │
 │ pipeline()           │   │   .validate()   │
 └────────┬─────────────┘   └────────┬────────┘
          │                          │
          ▼                          ▼
 ┌──────────────────────┐   ┌─────────────────┐
 │ PydanticModel-       │   │ FormSubmission  │
 │ Resolver             │   │  (flat data)    │
 └────────┬─────────────┘   └────────┬────────┘
          │                          │
          ▼                          ▼
 ┌──────────────────────┐   ┌─────────────────┐
 │ FormOperator         │   │ FormSubmission- │
 │  hooks (ordered):    │   │ Storage.store() │
 │   pre_validate       │   └─────────────────┘
 │   validate (pydantic)│
 │   post_validate      │
 │   pre_save           │
 │   store (in txn)     │
 │   post_save (in txn) │
 └────────┬─────────────┘
          │
          ▼
 ┌──────────────────────┐            on error
 │ FormSubmissionStorage│ ─────────────────────────┐
 │   .store(rec, conn=) │                          ▼
 └──────────────────────┘                 ┌──────────────────┐
          │                               │ store_dlq()      │
          ▼                               │ (separate txn)   │
    form_submissions                      │ form_submissions_dlq
    (extended schema)                     └──────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormAPIHandler` (`api.py:85-116`) | modifies `__init__` | adds `operators`, `pydantic_resolver` kwargs |
| `FormAPIHandler.submit_data` (`api.py:446-535`) | rewrites body | branches between legacy and pipeline paths; extracts `_run_submission_pipeline()` helper |
| `setup_form_routes` (`routes.py:82-159`) | modifies | forwards new kwargs to `FormAPIHandler`; no new routes |
| `FormSubmissionStorage` (`submissions.py:54-136`) | extends | implements `FormResultStorage` ABC; adds DDL columns + DLQ table; `store()` gains optional `conn=` |
| `FormSubmission` Pydantic model (`submissions.py:23-51`) | extends | optional metadata fields (`user_id`, `org_id`, `program`, `client`, `status`, `enrichment`) |
| `FormValidator` (`validators.py:66`) | preserved | still used as fallback when no typed resolver configured |
| `FormRegistry.load_from_storage` | hook | warms `PydanticModelResolver` cache via `datamodel-code-generator` |
| navigator-auth (`_get_org_id`, `_get_programs`) | reused | `UserDetails` operator reads through these helpers |

### Data Models

```python
# parrot/formdesigner/operators/base.py (new)
class OperatorContext(BaseModel):
    request: Any                         # aiohttp.web.Request (runtime-typed)
    form_schema: FormSchema
    user_id: int | None = None
    org_id: int | None = None
    programs: list[str] = Field(default_factory=list)
    scratchpad: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)


# parrot/formdesigner/services/submissions.py (extended — existing fields preserved)
class FormSubmission(BaseModel):
    submission_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    form_id: str
    form_version: str
    data: dict[str, Any]
    is_valid: bool
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # NEW fields (all optional, default None / empty)
    user_id: int | None = None
    org_id: int | None = None
    program: str | None = None
    client: str | None = None
    status: str | None = None          # e.g. "submitted", "accepted"
    enrichment: dict[str, Any] | None = None


# parrot/formdesigner/services/result_storage.py (new)
class FormResultStorage(ABC):
    @abstractmethod
    async def store(
        self,
        submission: FormSubmission,
        *,
        conn: "asyncpg.Connection | None" = None,
    ) -> str: ...

    @abstractmethod
    async def store_dlq(
        self,
        form_id: str,
        form_version: str,
        raw_payload: dict[str, Any],
        stage: str,
        error: str,
        traceback: str,
        correlation_id: str,
    ) -> str: ...
```

### New Public Interfaces

```python
# parrot/formdesigner/operators/base.py
class FormOperator(ABC):
    """Base class for class-based form submission operators.

    All hooks are optional (default no-op). Operators are invoked in the
    order declared at FormAPIHandler init. Each hook is async.
    """

    async def pre_validate(
        self, payload: dict[str, Any], ctx: OperatorContext
    ) -> dict[str, Any]:
        return payload

    async def post_validate(
        self, validated: BaseModel, ctx: OperatorContext
    ) -> BaseModel:
        return validated

    async def pre_save(
        self, submission: FormSubmission, ctx: OperatorContext
    ) -> FormSubmission:
        return submission

    async def post_save(
        self,
        submission: FormSubmission,
        ctx: OperatorContext,
        *,
        conn: "asyncpg.Connection",
    ) -> None:
        return None


# parrot/formdesigner/operators/user_details.py
class UserDetails(FormOperator):
    """Populate user/org/program fields from the navigator-auth session."""
    async def post_validate(self, validated, ctx): ...  # inject ids into ctx.scratchpad
    async def pre_save(self, submission, ctx):        ...  # stamp submission metadata


# parrot/formdesigner/services/pydantic_resolver.py
class PydanticModelResolver:
    def __init__(
        self,
        static_models: dict[tuple[str, str], type[BaseModel]] | None = None,
    ) -> None: ...

    async def warm_up(self, registry: FormRegistry) -> None:
        """Pre-generate Pydantic classes for every (form_id, version) in the registry."""

    async def resolve(
        self, form_id: str, version: str, schema: FormSchema
    ) -> type[BaseModel] | None:
        """Return a Pydantic class for the form, or None if codegen fails."""


# parrot/formdesigner/handlers/api.py — FormAPIHandler.__init__ extension
class FormAPIHandler:
    def __init__(
        self,
        registry: FormRegistry,
        client: "AbstractClient | None" = None,
        submission_storage: "FormSubmissionStorage | None" = None,
        forwarder: "SubmissionForwarder | None" = None,
        *,
        operators: list[FormOperator] | None = None,          # NEW
        pydantic_resolver: PydanticModelResolver | None = None, # NEW
    ) -> None: ...


# parrot/formdesigner/handlers/routes.py — setup_form_routes extension
def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client: "AbstractClient | None" = None,
    prefix: str = "",
    protect_pages: bool = True,
    submission_storage: "FormSubmissionStorage | None" = None,
    forwarder: "SubmissionForwarder | None" = None,
    operators: list["FormOperator"] | None = None,             # NEW
    pydantic_resolver: "PydanticModelResolver | None" = None,   # NEW
) -> None: ...
```

### DDL (additive migration, run at `FormSubmissionStorage.initialize()`)

```sql
-- Extend existing form_submissions (all new columns nullable — no backfill required)
ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS user_id INTEGER;
ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS org_id INTEGER;
ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS program VARCHAR(255);
ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS client VARCHAR(255);
ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS status VARCHAR(50);
ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS enrichment JSONB;
CREATE INDEX IF NOT EXISTS idx_form_submissions_user_id  ON form_submissions(user_id);
CREATE INDEX IF NOT EXISTS idx_form_submissions_org_id   ON form_submissions(org_id);
CREATE INDEX IF NOT EXISTS idx_form_submissions_program  ON form_submissions(program);

-- New sibling DLQ table
CREATE TABLE IF NOT EXISTS form_submissions_dlq (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    correlation_id VARCHAR(255) NOT NULL UNIQUE,
    form_id VARCHAR(255) NOT NULL,
    form_version VARCHAR(50) NOT NULL,
    raw_payload JSONB NOT NULL,
    stage VARCHAR(50) NOT NULL,
    error TEXT NOT NULL,
    traceback TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_form_submissions_dlq_form_id ON form_submissions_dlq(form_id);
```

### Response Contract

The endpoint keeps its current 200-shape for backward compatibility (brainstorm's drafted
decision; a `[ ]` OQ covers the alternative 201-minimal shape). Operator-enabled responses are
the same shape with additional optional fields:

```json
{
  "submission_id": "3e1a…-uuid",
  "form_id": "db-form-10-69",
  "form_version": "1.2",
  "is_valid": true,
  "forwarded": false,
  "forward_status": null,
  "forward_error": null,
  "status": "accepted",
  "operators_applied": ["UserDetails"]
}
```

Error responses:
- `400` — malformed JSON (unchanged).
- `404` — unknown `form_id` (unchanged).
- `413` — payload too large (new; configurable at aiohttp `client_max_size`).
- `422` — `{"is_valid": false, "errors": [...], "dlq_id": "<uuid>"}` on validation failure.
- `500` — `{"error": "...", "dlq_id": "<uuid>"}` on operator or storage failure.
- `503` — storage unavailable (DLQ write also failed → structured log only).

---

## 3. Module Breakdown

> These map directly to Task Artifacts generated by `/sdd-task`.

### Module 1: `FormResultStorage` ABC
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/services/result_storage.py` (new)
- **Responsibility**: Write-only storage interface — `store(record, *, conn=None)` and
  `store_dlq(...)`. Mirrors the `FormStorage` ABC pattern in `services/registry.py:29-91`.
- **Depends on**: `FormSubmission` model from Module 2.

### Module 2: `FormSubmission` + `FormSubmissionStorage` extension
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py` (extend)
- **Responsibility**:
  - Add nullable metadata fields (`user_id`, `org_id`, `program`, `client`, `status`,
    `enrichment`) to `FormSubmission`.
  - Make `FormSubmissionStorage` implement `FormResultStorage`.
  - Extend `initialize()` with additive `ALTER TABLE ADD COLUMN IF NOT EXISTS` and the DLQ DDL.
  - Add `store()` overload for `conn=` (share caller's transaction) plus `store_dlq()` method.
  - Update `INSERT_SQL` to include new columns (nullable).
- **Depends on**: Module 1.

### Module 3: `FormOperator` ABC + `OperatorContext`
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/operators/base.py` (new)
- **Responsibility**: Abstract operator with four optional async hooks; `OperatorContext`
  Pydantic model carrying per-request state and operator-shared scratchpad.
- **Depends on**: `FormSchema`, `FormSubmission`.

### Module 4: `UserDetails` operator
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/operators/user_details.py` (new)
- **Responsibility**: First concrete `FormOperator` implementation. Reads
  `request.user.organizations[0].org_id` and `request.session["session"]["programs"]`
  (reusing the helpers at `api.py:151-198`), stamps the resulting `user_id`, `org_id`,
  `programs` onto `submission` in `pre_save`.
- **Depends on**: Module 3, navigator-auth session conventions.

### Module 5: `PydanticModelResolver`
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/services/pydantic_resolver.py` (new)
- **Responsibility**: Static registry `{(form_id, version): type[BaseModel]}` + cache of classes
  produced offline by `datamodel-code-generator`. Exposes `warm_up(registry)` to pre-generate
  classes at `FormRegistry.load_from_storage()` time; `resolve(form_id, version, schema)` for
  per-request lookup with lazy on-demand generation on cache miss.
- **Depends on**: `datamodel-code-generator` package, `FormSchema`.

### Module 6: `FormAPIHandler.submit_data` rewrite + `_run_submission_pipeline`
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py` (extend)
- **Responsibility**:
  - Add `operators` and `pydantic_resolver` kwargs to `__init__`.
  - Rewrite `submit_data` body to branch between the legacy `FormValidator` path and the new
    pipeline path. The legacy branch must remain byte-compatible with today's behavior.
  - Implement `_run_submission_pipeline(request, form, data, conn)` — acquires a connection
    from the storage pool, opens a transaction, runs all operator hooks + pydantic validation,
    invokes `FormResultStorage.store(..., conn=conn)`, rolls back on error and writes to DLQ
    via a separate short transaction.
  - Assemble the extended response body.
- **Depends on**: Modules 1–5.

### Module 7: `setup_form_routes` + DI wiring
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py` (extend)
- **Responsibility**: Forward new `operators`, `pydantic_resolver` kwargs to
  `FormAPIHandler(...)` at construction. No new routes added.
- **Depends on**: Module 6.

### Module 8: Dependency addition
- **Path**: `packages/parrot-formdesigner/pyproject.toml` (extend)
- **Responsibility**: Add `datamodel-code-generator>=0.25` to project dependencies.
- **Depends on**: —

### Module 9: Tests
- **Path**: `packages/parrot-formdesigner/tests/` (new + extended)
- **Responsibility**: Unit tests per module + an integration test that exercises the full
  pipeline end-to-end using a real Postgres (asyncpg) fixture. Legacy-path regression test
  to prove zero behavior change when no operators are configured.
- **Depends on**: Modules 1–7.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_form_result_storage_abc_contract` | 1 | `FormResultStorage` exposes `store()` and `store_dlq()` abstract methods |
| `test_submission_model_new_fields_optional` | 2 | `FormSubmission(submission_id=..., form_id=..., form_version=..., data={}, is_valid=True)` still validates (all new fields default None) |
| `test_submission_storage_alters_table_idempotently` | 2 | `initialize()` on an already-extended table is a no-op; on an empty DB creates both table and DLQ |
| `test_submission_storage_store_accepts_shared_conn` | 2 | `store(sub, conn=conn)` uses the provided connection and does not acquire a new one |
| `test_submission_storage_store_dlq_writes_row` | 2 | A DLQ row is inserted with correlation_id, stage, error, traceback |
| `test_form_operator_default_hooks_noop` | 3 | `FormOperator()` default hooks return inputs unchanged |
| `test_operator_context_pydantic_validates` | 3 | `OperatorContext` accepts the expected fields incl. `arbitrary_types_allowed` for `request` |
| `test_user_details_stamps_submission` | 4 | Given a mock request with `user.organizations[0].org_id=42` and `session["session"]["programs"]=["a"]`, `pre_save` sets `submission.org_id=42`, `submission.programs=["a"]` |
| `test_pydantic_resolver_static_registry_wins` | 5 | If `(form_id, version)` is in `static_models`, `resolve()` returns it without invoking codegen |
| `test_pydantic_resolver_codegen_cache_hit` | 5 | After `warm_up(registry)`, a subsequent `resolve()` returns the cached generated class |
| `test_pydantic_resolver_codegen_lazy_on_miss` | 5 | On cache miss, `resolve()` invokes `datamodel-code-generator` and caches the result |
| `test_submit_data_legacy_path_unchanged` | 6 | When `operators=None, pydantic_resolver=None`, response body matches current shape byte-for-byte against a golden fixture |
| `test_submit_data_pipeline_invokes_operator_hooks_in_order` | 6 | A fake operator records the order `pre_validate → validate → post_validate → pre_save → store → post_save` |
| `test_submit_data_pipeline_rolls_back_on_operator_error` | 6 | `pre_save` raising → no row in `form_submissions`, DLQ row with `stage="pre_save"` present, response is 500 with `dlq_id` |
| `test_submit_data_422_on_validation_error_with_dlq_id` | 6 | Invalid payload → 422 `{"is_valid": false, "errors": ..., "dlq_id": ...}` and DLQ row with `stage="validate"` |
| `test_submit_data_404_unknown_form` | 6 | Returns 404 without invoking pipeline (existing behavior preserved) |
| `test_setup_form_routes_forwards_new_kwargs` | 7 | `FormAPIHandler` receives the `operators` and `pydantic_resolver` passed to `setup_form_routes` |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_pipeline_success_postgres` | Real `asyncpg` pool + ephemeral DB; POST valid payload to `/api/v1/forms/{form_id}/data` with `operators=[UserDetails()]`; asserts 200, row in `form_submissions` with metadata columns populated, no DLQ row |
| `test_end_to_end_pipeline_failure_writes_dlq_postgres` | Same fixture; operator `post_validate` raises; asserts 500 response, no row in `form_submissions`, exactly one row in `form_submissions_dlq` with correct `stage`/`error` |
| `test_end_to_end_legacy_path_postgres` | Call `setup_form_routes` without `operators`/`pydantic_resolver`; submit payload; assert today's response shape and flat-JSONB row (no new metadata fields set) |
| `test_pydantic_resolver_warmup_against_real_registry` | Loads a handful of form schemas into a `FormRegistry`, runs `resolver.warm_up(registry)`, asserts every `(form_id, version)` is cacheable and resolvable |
| `test_alter_table_migration_idempotent_postgres` | Run `storage.initialize()` twice; assert no error and column set stable |

### Test Data / Fixtures

```python
# packages/parrot-formdesigner/tests/conftest.py (extend)

@pytest.fixture
async def pg_pool() -> AsyncIterator["asyncpg.Pool"]:
    """Ephemeral asyncpg pool against test Postgres. Resets schema per session."""
    ...

@pytest.fixture
async def form_registry(pg_pool) -> FormRegistry:
    """Registry seeded with a minimal FormSchema (db-form-test-01, version '1.0')."""
    ...

@pytest.fixture
def mock_request_with_session():
    """aiohttp.web.Request mock exposing
       request.user.organizations[0].org_id=42,
       request.session['session']['programs']=['alpha'],
       request.match_info={'form_id': 'db-form-test-01'}."""
    ...

@pytest.fixture
def recording_operator() -> FormOperator:
    """Operator that appends the hook name to ctx.scratchpad['trace'] for order assertions."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/ -v`
- [ ] All integration tests pass: `pytest packages/parrot-formdesigner/tests/integration/ -v`
- [ ] `FormResultStorage` ABC exists and `FormSubmissionStorage` implements it (subclass check passes).
- [ ] `FormSubmission` gains `user_id`, `org_id`, `program`, `client`, `status`, `enrichment`
      fields, all optional, all default None.
- [ ] `FormSubmissionStorage.initialize()` runs idempotently on a pre-v1 `form_submissions` table
      (adds columns; creates `form_submissions_dlq`) and on a fresh DB.
- [ ] `FormSubmissionStorage.store(sub, conn=conn)` uses the provided connection without
      acquiring a new one from the pool.
- [ ] `FormOperator` ABC is in `parrot/formdesigner/operators/base.py` with four optional
      async hooks returning inputs unchanged by default.
- [ ] `UserDetails` operator stamps `user_id`, `org_id`, `program` from the navigator-auth
      session in `pre_save`.
- [ ] `PydanticModelResolver.warm_up(registry)` pre-generates a Pydantic class for every
      `(form_id, version)` using `datamodel-code-generator`; subsequent `resolve()` calls hit the cache.
- [ ] `FormAPIHandler.__init__` and `setup_form_routes` accept `operators` and
      `pydantic_resolver` kwargs, both optional with default None.
- [ ] When both kwargs are None, `submit_data` behaves byte-for-byte identically to the current
      implementation (golden fixture comparison in unit test).
- [ ] When operators are configured, hooks fire in the documented order
      (`pre_validate → validate → post_validate → pre_save → store → post_save`) and the main
      INSERT happens under the same asyncpg transaction as `pre_save`/`post_save`.
- [ ] On any failure after `_run_submission_pipeline()` begins, the main transaction is rolled
      back and a `form_submissions_dlq` row with correlation id, stage, error, and traceback is
      inserted in a separate short transaction.
- [ ] `datamodel-code-generator>=0.25` is declared in `packages/parrot-formdesigner/pyproject.toml`.
- [ ] No new route is added (only `POST /api/v1/forms/{form_id}/data` continues to serve submissions).
- [ ] No breaking change to the existing 200-response shape — all new fields are additive.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** All references below were verified on
> 2026-04-23 against commit-dev HEAD. Implementation tasks MUST NOT reference anything
> outside this contract without verifying first.

### Verified Imports

```python
# All confirmed to resolve in the current tree
from parrot.formdesigner.handlers.api import FormAPIHandler
from parrot.formdesigner.handlers.routes import setup_form_routes
from parrot.formdesigner.services.registry import FormRegistry, FormStorage
from parrot.formdesigner.services.storage import PostgresFormStorage
from parrot.formdesigner.services.submissions import FormSubmission, FormSubmissionStorage
from parrot.formdesigner.services.validators import FormValidator, ValidationResult
from parrot.formdesigner.core.schema import FormSchema
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:85-116
class FormAPIHandler:
    def __init__(
        self,
        registry: FormRegistry,
        client: "AbstractClient | None" = None,
        submission_storage: "FormSubmissionStorage | None" = None,
        forwarder: "SubmissionForwarder | None" = None,
    ) -> None:
        self.registry = registry
        self._client = client
        self._submission_storage = submission_storage
        self._forwarder = forwarder
        self.html_renderer = HTML5Renderer()
        self.schema_renderer = JsonSchemaRenderer()
        self.validator = FormValidator()
        self.logger = logging.getLogger(__name__)
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:151-198
def _get_org_id(self, request: web.Request) -> int | None:
    user = getattr(request, "user", None)
    if user and user.organizations:
        try:
            return int(user.organizations[0].org_id)
        except (TypeError, ValueError):
            return None
    return None

def _get_programs(self, request: web.Request) -> list[str]:
    session = getattr(request, "session", None)
    if session is None:
        return []
    userinfo = session.get("session", {})
    return userinfo.get("programs", [])
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:446-535 (to be extended)
async def submit_data(self, request: web.Request) -> web.Response:
    form_id = request.match_info["form_id"]
    form = await self.registry.get(form_id)
    if form is None:
        return web.json_response({"error": f"Form '{form_id}' not found"}, status=404)
    data = await request.json()
    result = await self.validator.validate(form, data)
    if not result.is_valid:
        return web.json_response({"is_valid": False, "errors": result.errors}, status=422)
    submission = FormSubmission(
        submission_id=str(uuid.uuid4()),
        form_id=form_id,
        form_version=form.version,
        data=result.sanitized_data,
        is_valid=True,
        created_at=datetime.now(timezone.utc),
    )
    if self._submission_storage is not None:
        await self._submission_storage.store(submission)
    # …forwarder branch, then 200 JSON…
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py:82-125
def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client: "AbstractClient | None" = None,
    prefix: str = "",
    protect_pages: bool = True,
    submission_storage: "FormSubmissionStorage | None" = None,
    forwarder: "SubmissionForwarder | None" = None,
) -> None: ...
# Route already registered at line 159:
# app.router.add_post(f"{p}/api/v1/forms/{{form_id}}/data", _wrap_auth(api.submit_data))
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py:23-136
class FormSubmission(BaseModel):
    submission_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    form_id: str                       # form-TYPE id (e.g., "db-form-10-69")
    form_version: str
    data: dict[str, Any]
    is_valid: bool
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class FormSubmissionStorage:
    CREATE_TABLE_SQL = """..."""
    INSERT_SQL = """..."""
    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self.logger = logging.getLogger(__name__)
    async def initialize(self) -> None: ...
    async def store(self, submission: FormSubmission) -> str: ...
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py:29-91
class FormStorage(ABC):
    @abstractmethod
    async def save(self, form: FormSchema, style: StyleSchema | None = None) -> str: ...
    @abstractmethod
    async def load(self, form_id: str, version: str | None = None) -> FormSchema | None: ...
    @abstractmethod
    async def delete(self, form_id: str) -> bool: ...
    @abstractmethod
    async def list_forms(self) -> list[dict[str, str]]: ...
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py:55-103
class ValidationResult(BaseModel):
    is_valid: bool
    errors: dict[str, list[str]]
    sanitized_data: dict[str, Any]

class FormValidator:
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
    async def validate(
        self,
        form: FormSchema,
        data: dict[str, Any],
        *,
        locale: str = "en",
    ) -> ValidationResult: ...
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:107-133
class FormSchema(BaseModel):
    form_id: str                  # form-TYPE id (existing convention in the codebase)
    version: str = "1.0"
    title: LocalizedString
    description: LocalizedString | None = None
    sections: list[FormSection]
    submit: SubmitAction | None = None
    cancel_allowed: bool = True
    meta: dict[str, Any] | None = None
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FormResultStorage` | `FormSubmissionStorage` | `FormSubmissionStorage` declares `FormResultStorage` as base class | `services/submissions.py:54` (new base) |
| `FormOperator` hooks | `FormAPIHandler._run_submission_pipeline` | sequential `await op.<hook>(...)` | `handlers/api.py:446-535` (rewrite) |
| `UserDetails.pre_save` | `_get_org_id`, `_get_programs` | reuses helper methods via `ctx.request` | `handlers/api.py:151-198` |
| `PydanticModelResolver.warm_up` | `FormRegistry.load_from_storage` | called at application startup after registry load | `services/registry.py` (registry loader) |
| `FormSubmissionStorage.store(sub, conn=)` | asyncpg transaction | `async with conn.transaction(): await conn.execute(INSERT_SQL, ...)` | `services/submissions.py:109-136` |
| `FormSubmissionStorage.store_dlq` | asyncpg | separate `async with pool.acquire() as c: async with c.transaction():` — decoupled from main txn | new method |

### Does NOT Exist (Anti-Hallucination)

- ~~`FormResultStorage`~~ class — does NOT exist; this feature creates it as a new ABC.
- ~~`FormOperator` / `OperatorContext`~~ — do NOT exist; new in this feature.
- ~~`PydanticModelResolver`~~ — does NOT exist; new in this feature.
- ~~`UserDetails`~~ operator class — does NOT exist; new in this feature.
- ~~`form_submissions_dlq`~~ table — does NOT exist; new DDL in this feature.
- ~~Columns `user_id`, `org_id`, `program`, `client`, `status`, `enrichment` on `form_submissions`~~
  — do NOT exist today; added by this feature via `ALTER TABLE ADD COLUMN IF NOT EXISTS`.
- ~~Route `POST /api/v1/forms/{form_id}` (without `/data`)~~ — not added by this feature.
  Only `POST /api/v1/forms/{form_id}/data` is used.
- ~~`FormSubmission.submission_id` renamed to `form_id`~~ — NOT renamed. Existing naming
  (`submission_id` = UUID, `form_id` = form-type id) is preserved to avoid cross-package churn
  (see §8 terminology open question).
- ~~`datamodel-code-generator` dependency~~ — NOT declared in `packages/parrot-formdesigner/pyproject.toml`
  at start of this feature; must be added.
- ~~`FormAPIHandler._run_submission_pipeline`~~ — does NOT exist today; extracted as a new helper.
- ~~`store()` method accepting `conn=` kwarg~~ — today's `store()` does not accept it; signature
  changes additively in this feature.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Async-first throughout.** All operator hooks and storage methods are `async def`.
- **asyncpg connection + transaction style**: `async with pool.acquire() as conn: async with conn.transaction(): await conn.execute(SQL, ...)` — matches the pattern already used by
  `FormSubmissionStorage.store()` and `PostgresFormStorage.save()`.
- **Class-level SQL constants** on any storage class (`CREATE_TABLE_SQL`, `INSERT_SQL`,
  `INSERT_DLQ_SQL`, `ALTER_SQL`) — matches `PostgresFormStorage`
  (`services/storage.py:39-244`) and the existing `FormSubmissionStorage`
  (`services/submissions.py:54-136`).
- **ABC mirroring `FormStorage`** for `FormResultStorage`: four short abstract methods,
  no concrete default implementations.
- **Pydantic v2** for every new data model (`OperatorContext`, etc.) — use `ConfigDict` for
  `arbitrary_types_allowed` where a model carries the aiohttp `Request`.
- **`self.logger`** for all logging — never `print`.
- **Optional kwargs default to `None`** on `FormAPIHandler.__init__` and `setup_form_routes` —
  keyword-only (after `*`) so the positional signature remains unchanged.
- **Operators-in-transaction**: `pre_save`, `store`, and `post_save` share the same asyncpg
  `Connection` via the explicit `conn=` kwarg. `pre_validate` / `post_validate` run before the
  connection is acquired (they operate on the payload/validated model, not the DB).
- **DDL is additive and idempotent**: `ALTER TABLE … ADD COLUMN IF NOT EXISTS` + `CREATE TABLE IF NOT EXISTS`.
  No data migration, no row rewrite.
- **Legacy path must stay byte-compatible**: the golden-fixture unit test is the contract.

### Known Risks / Gotchas

- **`submit_data` gets busier.** Mitigation: factor the new flow into `_run_submission_pipeline()`
  and keep `submit_data` as a thin router between the legacy branch and the pipeline branch.
- **`FormSubmission` picks up optional fields that are `None` for legacy callers.** Readers may
  wonder why a field exists when not used. Keep the docstring explicit about when each field is
  populated (operators vs. legacy).
- **`datamodel-code-generator` is a heavy dep.** Mitigation: invoke only at warm-up + cache
  misses; never per request; treat codegen failure as non-fatal (fall back to `FormValidator`).
- **DDL migration on a live DB**: `ALTER TABLE ADD COLUMN NULL` is metadata-only on PostgreSQL
  (no row rewrite) but still takes an ACCESS EXCLUSIVE lock briefly. Run on a low-traffic window
  or split into statements executed serially inside `initialize()`.
- **DLQ write after rollback** is a separate transaction — if the DB is completely unavailable,
  both writes fail. In that case, log a structured error with the correlation id; the client
  gets 503. This is acceptable loss; the endpoint is not a guaranteed-delivery queue.
- **`post_save` inside transaction** means operator side-effects that touch external systems
  (HTTP calls, message queues) block the DB transaction. Document this clearly in the
  `FormOperator` docstring; it's the reason `post_save` receives `conn=` explicitly.
- **Terminology**: user prefers `formid` (type) vs. `form_id` (submission UUID); codebase uses
  the opposite. Spec keeps codebase terminology to avoid a disruptive rename — revisit in OQ.
- **aiohttp `client_max_size` gotcha**: aiohttp enforces payload limits at framework level, so
  the 413 case is handled there rather than inside `submit_data`. Document in the handler
  docstring so integrators know where to raise the limit.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `datamodel-code-generator` | `>=0.25` | Pre-generate Pydantic classes from form JSON schema (offline, at warm-up) |
| `asyncpg` | already in-tree | Postgres driver + transactions (shared `conn=` pattern) |
| `pydantic` | `>=2` | Typed validation + operator-context model (already in-tree) |

---

## 8. Open Questions

> Resolved items (`[x]`) carry forward decisions made in the brainstorm; unresolved items (`[ ]`)
> are still open and may be addressed at implementation time unless they block a task.

- [x] Design: parallel new endpoint vs. extend existing `/data` — *Resolved in brainstorm*:
      **Extend the existing endpoint.** `POST /api/v1/forms/{form_id}/data` +
      `FormSubmissionStorage` remain the canonical submission path; operators, DLQ, typed
      Pydantic, and metadata columns are layered on top via optional `__init__` kwargs.
      (Confirmed 2026-04-23.)
- [ ] Terminology: user's preferred convention is `formid` = form-type id, `form_id` = submission
      UUID, but the codebase uses `form_id` for the type and `submission_id` for the UUID. Spec
      keeps codebase terminology (no rename) to avoid churn across `FormSchema`, `FormSubmission`,
      match-info parameters, and route paths — confirm this stays the working assumption. — *Owner: jesuslara*
- [ ] Schema migration strategy: `ALTER TABLE form_submissions ADD COLUMN … NULL` inside
      `initialize()` (idempotent, current pattern) vs. an out-of-band migration tool
      (alembic / manual SQL). Spec assumes the in-`initialize()` approach. — *Owner: jesuslara*
- [ ] Default operator catalog to ship in v1: `UserDetails` only (current spec), or also
      `ProgramContext`, `OrgContext`, `AuditTrail`? — *Owner: jesuslara*
- [ ] DLQ retention window (7 d? 30 d?) and whether to ship a cleanup task or leave it to ops. — *Owner: jesuslara*
- [ ] Max body size guardrail: default (1 MB?) and whether enforced via aiohttp
      `client_max_size` (framework-level) or inside the handler. — *Owner: jesuslara*
- [ ] Pydantic model warm-up trigger: at `FormRegistry.load_from_storage()` (eager), at
      first-submission lazy per `(form_id, version)`, or both? Spec assumes **both** (eager warm-up
      + lazy on cache miss). — *Owner: jesuslara*
- [ ] `Idempotency-Key` header support (deduplication on retry). Out of scope for v1, revisit later. — *Owner: jesuslara*
- [ ] `post_save` runs **inside** the main transaction (current spec) so side-effect failures
      abort the save. Confirm this is desired over a fire-and-forget post-commit semantic. — *Owner: jesuslara*
- [ ] Static Pydantic model registration API: decorator (`@register_form_model("db-form-10-69", "1.2")`),
      explicit kwarg on `PydanticModelResolver` (`static_models={(id, ver): Model}` — current
      spec), or both? — *Owner: jesuslara*
- [ ] Response body shape when operators run: today's extended-200 (current spec) or switch to
      201 Created with a minimal body `{submission_id, form_id, form_version, status, created_at}`? — *Owner: jesuslara*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`.
- **Rationale**: Multiple modules converge on `FormAPIHandler.__init__`, `submit_data`, and the
  `FormSubmissionStorage` DDL/INSERT statements. Running tasks sequentially in one worktree
  avoids merge conflicts on these shared files and keeps the full wiring reviewable in one PR.
- **Task ordering**: Module 1 → Module 2 → Module 3 → Module 5 → Module 4 → Module 6 → Module 7 →
  Module 8 → Module 9 (tests can be written alongside each module and merged at the end).
- **Cross-feature dependencies**:
  - **Light conflict risk** with `formdesigner-navigator-api-integration` (also edits `api.py`) —
    coordinate via non-overlapping `__init__` kwarg additions and keep `submit_data` edits to the
    body of the existing method.
  - No conflict with `form-abstraction-layer` or `formbuilder-database` (they edit `core/` and
    `services/registry.py` schemas, not handlers or `submissions.py`).
- **Worktree creation** (per `CLAUDE.md`):
  ```bash
  git checkout dev && git pull origin dev
  git worktree add -b feat-121-parrot-formdesigner-post-method \
    .claude/worktrees/feat-121-parrot-formdesigner-post-method HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-23 | Jesus Lara | Initial draft from brainstorm (recommended Option A — extend existing `/data` endpoint) |
