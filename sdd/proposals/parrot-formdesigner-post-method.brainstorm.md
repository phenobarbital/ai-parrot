# Brainstorm: parrot-formdesigner-post-method

**Date**: 2026-04-23
**Author**: jesuslara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`parrot-formdesigner` exposes `GET /api/v1/forms/{form_id}` (+ `/schema`, `/style`, `/html`) to render
form designs, and already has a minimal `POST /api/v1/forms/{form_id}/data` endpoint that validates
a payload against the form's structural JSON schema and persists a flat JSONB row via
`FormSubmissionStorage`.

**Design decision (user-confirmed 2026-04-23)**: this feature **extends the existing
`POST /api/v1/forms/{form_id}/data` endpoint and `FormSubmissionStorage`** rather than introducing
a parallel submission path. The existing endpoint already covers the "accept a JSON payload, validate,
persist" surface; what is missing is the richer pipeline on top.

What is missing is a **first-class submission pipeline** with:
- Strong typed validation through a Pydantic model derived from the form design (static-registered
  if present, else pre-generated offline from the JSON schema at FormRegistry warm-up).
- An **operator pipeline** — ordered class-based hooks (`pre_validate`, `post_validate`, `pre_save`,
  `post_save`) attached to the form at `FormDesigner` / `FormAPIHandler` init time, allowing business
  rules and data enrichment (e.g., a `UserDetails` operator that augments the payload with session data).
- A **hybrid storage schema** in `FormSubmissionStorage` (now the `FormResultStorage` ABC): fixed
  metadata columns (`submission_id` [UUID], `form_id` [form-type id], `form_version`, `user_id`,
  `org_id`, `program`, `client`, `status`, timestamps) + a JSONB column for the dynamic,
  form-specific payload. The current `form_submissions` table is flat JSONB only.
- **Fail-fast with DLQ**: if validation or any operator fails, the user gets a structured error and
  the failed attempt is persisted to a dead-letter table for debugging/retry.
- **Typed Pydantic validation** replacing (or layered on) the current structural `FormValidator`:
  static-registered model per `(form_id, version)` wins; otherwise a pre-generated model produced
  offline by `datamodel-code-generator` against the form's JSON schema.
- **Operators wired at `FormAPIHandler` init time** via new kwargs, so existing callers that don't
  pass them are unchanged.

The existing `submit_data` flow is the right spine, but it is structurally validated only, stores flat
JSONB, has no operator hooks, and has no DLQ — this feature fills that gap in place.

## Constraints & Requirements

- **Must reuse** `FormAPIHandler`, `FormRegistry`, `FormSchema`, `navigator-auth` session pattern,
  and the asyncpg/pool storage style already used by `PostgresFormStorage` and `FormSubmissionStorage`.
- **Async-first**: all operator hooks and storage calls are async.
- **Atomicity**: success-path insert and DLQ insert both run inside a single asyncpg transaction per
  request; on rollback, DLQ write happens afterward in a separate short transaction (decided in Q&A).
- **201 minimal response**: `{ form_id, formid, form_version, status, created_at }` — no payload echo.
- **Pydantic model resolution**: static-registered per `(formid, version)` wins; otherwise use a
  pre-generated class cached at FormRegistry warm-up via `datamodel-code-generator` (no per-request
  codegen).
- **Operators wired at init**: `FormAPIHandler.__init__` gains `operators: list[FormOperator]` and
  `result_storage: FormResultStorage | None` kwargs; operators are classes with optional async hook
  methods, invoked in declared order.
- **Auth**: reuse the existing `@user_session()` decorator + `request.user.organizations[0].org_id`
  and `request.session["session"]["programs"]` (already implemented in
  `FormAPIHandler._get_org_id` and `_get_programs`).
- **Scope**: write-only for this feature (no list/query API on `FormResultStorage`).
- **No LangChain**, no sync I/O in async paths, no new frameworks beyond `datamodel-code-generator`.

---

## Options Explored

### Option A: Extend `submit_data` + evolve `FormSubmissionStorage` into `FormResultStorage` (chosen)

Evolve the existing submission spine in place — same route, same handler method signature, same
storage class name — and layer the new capabilities onto it.

**Route** — keep `POST /api/v1/forms/{form_id}/data` (already registered at
packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py:159). No URL change, no
route duplication.

**Handler** — rewrite the body of `FormAPIHandler.submit_data`
(packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:446-535) to:
1. Resolve the typed Pydantic model via a new `PydanticModelResolver` (static registry first,
   `datamodel-code-generator`-produced cache second). Fall back to the current `FormValidator` when
   neither is available, preserving today's behavior.
2. Run the operator pipeline around Pydantic validation (`pre_validate` → validate →
   `post_validate` → build record → `pre_save` → `store` → `post_save`).
3. On any failure, short-circuit to DLQ and return a structured error.
4. Return the existing 200-shape response ({`submission_id`, `is_valid`, `forwarded`, …}), extended
   with additional enrichment fields populated by operators.

**Storage** — promote `FormSubmissionStorage`
(packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py:54-136) to implement
a new `FormResultStorage` ABC (write-only interface: `store(record, *, conn)`, `store_dlq(attempt, error)`).
Extend the `form_submissions` table via additive migration with new columns
(`user_id`, `org_id`, `program`, `client`, `status`, `enrichment JSONB`); the existing `data JSONB`
column keeps the dynamic payload. All new columns are nullable so existing rows remain valid. Add
a sibling `form_submissions_dlq` table for failed attempts.

**Operators** — new ABC `FormOperator` in `parrot/formdesigner/operators/` with four optional async
hooks. Wired via new kwargs on `FormAPIHandler.__init__` and `setup_form_routes`:
`operators: list[FormOperator] | None = None`, `pydantic_resolver: PydanticModelResolver | None = None`.
First concrete operator: `UserDetails` — reads `request.user` / `request.session["session"]` and
stamps `user_id`, `org_id`, `programs` onto record metadata.

**Pydantic resolution** — offline codegen via `datamodel-code-generator` (new dep) at
`FormRegistry.load_from_storage()` warm-up; static registry overrides for developer-authored models.

**Backward compatibility** —
- Callers that don't pass `operators=` and `pydantic_resolver=` see no behavior change: the handler
  falls back to the current `FormValidator` path.
- The existing `FormSubmission` Pydantic model (packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py:23-51)
  gains the new metadata fields as optional (`Field(default=None)`); old callers serializing the
  model get the same JSON they do today.
- Existing `form_submissions` rows migrate in place (add-column, no data rewrite).

✅ **Pros:**
- Single canonical submission path, matching user's direction.
- Zero route duplication, no 307 redirect games.
- Reuses `FormSubmissionStorage`'s connection management, SQL style, and init hook.
- Existing consumers of `/data` keep working (new kwargs default to None ⇒ old behavior).
- Smaller surface of new files than a parallel-module split.

❌ **Cons:**
- Single additive DDL migration on `form_submissions` (ALTER TABLE ADD COLUMN … NULL) — low risk
  but still touches production data.
- `submit_data` body grows; mitigated by extracting a `_run_submission_pipeline()` helper.
- `FormSubmission` model picks up optional fields that are "only filled when operators run" — some
  mental overhead for readers.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `datamodel-code-generator` | JSON schema → Pydantic class (offline) | new dep, ≥0.25 |
| `asyncpg` | Postgres driver + explicit transactions | already used |
| `pydantic` ≥ 2 | Validation + typed records | already a dep |

🔗 **Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:85-116` — `FormAPIHandler.__init__` (add kwargs here)
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:151-198` — `_get_org_id`, `_get_programs` (reused by `UserDetails` operator)
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:446-535` — `submit_data` (rewrite in place)
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py:82-159` — `setup_form_routes` (add kwargs)
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py:54-136` — `FormSubmissionStorage` (promote to `FormResultStorage` impl, add columns + DLQ SQL)
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py:29-91` — `FormStorage` ABC pattern (mirror for `FormResultStorage`)
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:39-244` — `PostgresFormStorage` style (class-level SQL constants + asyncpg pool)

---

### Option B: Parallel new endpoint + new `FormResultStorage` module (rejected)

Add a new `POST /api/v1/forms/{form_id}` route alongside `/data`, with a brand-new `FormResultStorage`
ABC, `PostgresFormResultStorage` implementation, new `form_results` + `form_results_dlq` tables,
and a new `submit_result` handler method. Existing `/data` + `FormSubmissionStorage` stay untouched.

✅ **Pros:**
- Zero schema migration on `form_submissions`.
- Clear separation of "legacy structural submission" vs. "pipeline submission".

❌ **Cons:**
- Two submission endpoints with overlapping responsibilities — maintenance and docs burden.
- User confirmed they want the existing flow extended, not paralleled — this option contradicts
  the design decision.
- Higher net churn (more new files, more tests, two code paths to keep in sync).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `datamodel-code-generator` | JSON schema → Pydantic class (offline) | new dep |
| `asyncpg` | Postgres driver | already used |

🔗 **Existing Code to Reuse:**
- Same references as Option A, plus new `form_results` tables in its own module.

---

### Option C: Replace `submit_data` with unified pipeline + one-shot migration

Migrate `form_submissions` to a new hybrid `form_results` table, move the route from
`/api/v1/forms/{form_id}/data` to `/api/v1/forms/{form_id}` (307 redirect for compatibility),
and rewrite `submit_data` to use the new operator pipeline and `FormResultStorage`.
Deprecate `FormSubmissionStorage`.

✅ **Pros:**
- Single canonical path from day one.
- No parallel flows to maintain.
- Cleaner long-term architecture.

❌ **Cons:**
- Data migration risk: every row in `form_submissions` must be re-shaped into the hybrid schema.
- 307 redirect still forces clients that POST to `/data` to follow redirects with bodies — some
  HTTP clients drop the body on 307s.
- Larger blast radius for one PR; harder to isolate regressions.
- Blocks existing `/data` traffic during migration window.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `datamodel-code-generator` | JSON schema → Pydantic | new dep |
| `asyncpg` | Postgres + migration script | already used |

🔗 **Existing Code to Reuse:**
- All of Option B's references, plus:
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py` — schema-migration target

---

## Recommendation

**Option A** is recommended (confirmed by user on 2026-04-23) because:

- The existing `POST /api/v1/forms/{form_id}/data` endpoint plus `FormSubmissionStorage` already
  cover the submission spine. The new capabilities (operator pipeline, typed Pydantic validation,
  hybrid metadata+JSONB schema, DLQ) are **layered on top** rather than replicated in parallel.
- A single canonical submission path is simpler to document, maintain, and reason about.
- The additive DDL migration (`ALTER TABLE form_submissions ADD COLUMN … NULL`) is low-risk:
  existing rows stay valid, existing callers see no behavior change.
- New kwargs on `FormAPIHandler.__init__` default to `None` — callers that don't opt into operators
  or typed resolution continue to get today's `FormValidator`-based flow.
- Offline codegen via `datamodel-code-generator` at `FormRegistry.load_from_storage()` avoids
  per-request model construction cost.

Tradeoff accepted: `submit_data` picks up an operator-pipeline branch, making it the busiest method
in `api.py`. Mitigation — extract a `_run_submission_pipeline(request, form, data, conn)` helper
so `submit_data` remains a thin router between the legacy path and the pipeline path.

---

## Feature Description

### User-Facing Behavior

- **Endpoint** (unchanged): `POST /api/v1/forms/{form_id}/data` — where `form_id` is the form-type id
  (e.g. `db-form-10-69`), matching the current aiohttp route parameter name. No URL change.
- **Auth**: requires a valid `navigator-auth` session (same `_wrap_auth(api.submit_data)` already in
  `routes.py:159`).
- **Request body**: JSON object matching the form's fields.
- **Success response** — keeps the current 200 shape, extended (all new fields optional so old
  clients are unaffected):
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
  (The existing `submission_id` / `form_id` naming is preserved to avoid breaking consumers; the
  user-preferred terminology clash is called out in Open Questions and deferred to spec time.)
- **Validation failure — 422 Unprocessable Entity** (today's 422 shape extended with DLQ id):
  ```json
  { "is_valid": false, "errors": [...], "dlq_id": "<uuid>" }
  ```
  Attempt persisted to `form_submissions_dlq` with `stage = "validate"`.
- **Operator failure — 500** with `{ "error": "...", "dlq_id": "<uuid>" }`.
- **Unknown form_id — 404** (current behavior). **Malformed JSON — 400** (current behavior).
  **Payload too large — 413** (new guardrail).

### Internal Behavior

Operators-enabled flow (when `operators` or `pydantic_resolver` kwargs are provided):

1. **Resolve form**: `registry.get(form_id) → FormSchema | None`. 404 on None (existing behavior).
2. **Parse JSON**: 400 on `JSONDecodeError` (existing behavior).
3. **Resolve Pydantic model** via `PydanticModelResolver.resolve(form_id, form.version)`:
   - Static registry first (developer-registered classes keyed by `(form_id, version)`).
   - Else pre-generated class produced by `datamodel-code-generator` against the form's JSON schema
     (cache is populated at `FormRegistry.load_from_storage()`; lazy generation on cache miss).
   - If no model can be resolved, fall back to the current `FormValidator` path (keeps backward
     compatibility).
4. **Acquire transaction**: `async with self._submission_storage._pool.acquire() as conn: async with conn.transaction():` …
5. **Pipeline** (inside the transaction, operator order as declared at init):
   - `for op in operators: payload = await op.pre_validate(payload, ctx)` — mutate raw payload.
   - `validated = PydanticModel.model_validate(payload)` — strict typed validation.
   - `for op in operators: validated = await op.post_validate(validated, ctx)` — business rules.
   - Build `FormSubmission` (extended): `submission_id=uuid4()`, `form_id`, `form_version`,
     `data=validated.model_dump()`, `user_id`, `org_id`, `program`, `client`, `status="submitted"`,
     `enrichment={…}`, `created_at=now(UTC)`.
   - `for op in operators: submission = await op.pre_save(submission, ctx)`.
   - `await self._submission_storage.store(submission, conn=conn)` — `store()` gains an optional
     `conn=` kwarg so callers can share the transaction; default path (None) reproduces current
     behavior.
   - `for op in operators: await op.post_save(submission, ctx, conn=conn)` — in-transaction side
     effects (see Open Question about `post_save` scope).
6. **Forwarder** (existing) — if the form declares an endpoint submit action and a forwarder is
   configured, forward the sanitized data after commit (unchanged).
7. **Commit**, return the extended 200 body.
8. **On exception after step 4**: rollback the main transaction, then in a **separate short
   transaction** insert a `form_submissions_dlq` row containing raw payload, stage
   (`"pre_validate" | "validate" | "post_validate" | "pre_save" | "store" | "post_save"`), error
   repr, traceback excerpt, correlation id; return the appropriate error response with `dlq_id`.

Legacy flow (no `operators` and no `pydantic_resolver`) — identical to current `submit_data`:
structural `FormValidator`, flat `FormSubmission.store()`, existing 200/422 shapes. Zero change
for existing deployments.

### Edge Cases & Error Handling

- **No Pydantic model resolvable** (no static registration AND codegen failed): fall back to the
  current `FormValidator` path (preserves backward compat) and log a warning. If the form has
  required operators configured, raise → DLQ with `stage="model_resolve"`.
- **Stale schema**: client submits against `form_version` V1 but registry only has V2. If static
  registry has a V1 model → accept as historical; else 422 with `code="stale_schema"` + DLQ entry.
- **User has no org / no programs**: `UserDetails` operator raises → DLQ with `stage="post_validate"`.
  (Operator can be configured to soft-warn instead of fail — per-operator setting.)
- **Storage unavailable / pool exhausted**: 503; DLQ write also fails → structured log entry only.
- **Large payload** (>configurable `max_body_size`, default 1 MB): 413 early, no pipeline invocation.
- **Operator raises `asyncio.CancelledError`**: propagate without DLQ (client disconnected).
- **Duplicate submission** (same idempotency key if provided): out of scope for this feature — see
  Open Questions.
- **Legacy callers** (no operators configured): behave exactly like today — same 200 body, same
  `form_submissions` row shape (new columns are NULL).

---

## Capabilities

### New Capabilities
- `form-operator-pipeline`: `FormOperator` ABC + sequential invocation with
  `pre_validate`/`post_validate`/`pre_save`/`post_save` async hooks and a per-request `OperatorContext`
  carrying `request`, `form_schema`, `user`, `org_id`, `programs`, operator-shared scratchpad.
- `form-result-storage`: `FormResultStorage` ABC (write-only: `store(record, *, conn)`,
  `store_dlq(attempt, error)`). `FormSubmissionStorage` is promoted to implement this ABC and is
  extended with new columns + DLQ table.
- `form-pydantic-resolution`: `PydanticModelResolver` — static registry + offline-generated cache
  keyed by `(form_id, version)`; warm-up hook on `FormRegistry.load_from_storage()`.
- `form-userdetails-operator`: first concrete `FormOperator` that reads the navigator-auth session
  and stamps `user_id`, `org_id`, `programs` onto the record metadata.

### Modified Capabilities
- `form-submission-storage` (existing `FormSubmissionStorage` / `form_submissions` table) — schema
  extended with nullable metadata columns + `enrichment JSONB`; sibling DLQ table added; `store()`
  gains an optional `conn=` kwarg.
- Existing `POST /api/v1/forms/{form_id}/data` endpoint — flow extended with the operator pipeline
  when `operators` or `pydantic_resolver` kwargs are provided at handler init; legacy behavior
  preserved otherwise.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:85-116` | modifies | `FormAPIHandler.__init__` gains `operators: list[FormOperator] \| None = None` and `pydantic_resolver: PydanticModelResolver \| None = None` kwargs (both optional, backward-compatible) |
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:446-535` | modifies | `submit_data` rewritten to branch between legacy `FormValidator` path and new operator-pipeline path; helper `_run_submission_pipeline()` extracted |
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py:82-159` | modifies | `setup_form_routes` gains matching optional kwargs; no new routes added |
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py:23-136` | modifies | `FormSubmission` gains optional metadata fields (`user_id`, `org_id`, `program`, `client`, `status`, `enrichment`); `FormSubmissionStorage` implements new `FormResultStorage` ABC, DDL adds columns (nullable) + `form_submissions_dlq` table; `store()` accepts optional `conn=` for shared transaction |
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/result_storage.py` | adds | `FormResultStorage` ABC (write-only interface) |
| `packages/parrot-formdesigner/src/parrot/formdesigner/operators/__init__.py` | adds | `FormOperator` ABC + `OperatorContext` Pydantic model |
| `packages/parrot-formdesigner/src/parrot/formdesigner/operators/user_details.py` | adds | `UserDetails` operator (first concrete operator) |
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/pydantic_resolver.py` | adds | `PydanticModelResolver` with static registry + codegen cache |
| `packages/parrot-formdesigner/pyproject.toml` | modifies | adds `datamodel-code-generator>=0.25` dependency |
| Postgres DDL on `form_submissions` | additive migration | `ALTER TABLE form_submissions ADD COLUMN user_id …, org_id …, program …, client …, status …, enrichment JSONB`; `CREATE TABLE form_submissions_dlq …` |
| Existing `FormValidator` path | preserved | still used as fallback when no typed resolver/operators configured |

---

## Code Context

### User-Provided Code

None. The user's request was prose-only (see the `/sdd-brainstorm` invocation).

### Verified Codebase References

#### Classes & Signatures

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
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:151-177
def _get_org_id(self, request: web.Request) -> int | None:
    user = getattr(request, "user", None)
    if user and user.organizations:
        try:
            return int(user.organizations[0].org_id)
        except (TypeError, ValueError):
            return None
    return None
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:179-198
def _get_programs(self, request: web.Request) -> list[str]:
    session = getattr(request, "session", None)
    if session is None:
        return []
    userinfo = session.get("session", {})
    return userinfo.get("programs", [])
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:446-535 (existing POST /data)
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
    # …forwarder path, then 200 JSON…
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
# packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py:54-136
class FormSubmissionStorage:
    CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS form_submissions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            submission_id VARCHAR(255) NOT NULL UNIQUE,
            form_id VARCHAR(255) NOT NULL,
            form_version VARCHAR(50) NOT NULL,
            data JSONB NOT NULL,
            is_valid BOOLEAN NOT NULL DEFAULT TRUE,
            forwarded BOOLEAN NOT NULL DEFAULT FALSE,
            forward_status INTEGER,
            forward_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_form_submissions_form_id ON form_submissions(form_id);
    """
    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self.logger = logging.getLogger(__name__)
    async def initialize(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(self.CREATE_TABLE_SQL)
    async def store(self, submission: FormSubmission) -> str:
        async with self._pool.acquire() as conn:
            await conn.execute(self.INSERT_SQL, submission.submission_id, …)
        return submission.submission_id
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:107-133
class FormSchema(BaseModel):
    form_id: str                  # this is the form-TYPE id (user's "formid")
    version: str = "1.0"          # form_version
    title: LocalizedString
    description: LocalizedString | None = None
    sections: list[FormSection]
    submit: SubmitAction | None = None
    cancel_allowed: bool = True
    meta: dict[str, Any] | None = None
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py:146-159 (existing API routes)
app.router.add_post(f"{p}/api/v1/forms",                 _wrap_auth(api.create_form))
app.router.add_get (f"{p}/api/v1/forms",                 _wrap_auth(api.list_forms))
app.router.add_post(f"{p}/api/v1/forms/from-db",         _wrap_auth(api.load_from_db))
app.router.add_get (f"{p}/api/v1/forms/{{form_id}}",     _wrap_auth(api.get_form))
app.router.add_get (f"{p}/api/v1/forms/{{form_id}}/schema", _wrap_auth(api.get_schema))
app.router.add_get (f"{p}/api/v1/forms/{{form_id}}/style",  _wrap_auth(api.get_style))
app.router.add_get (f"{p}/api/v1/forms/{{form_id}}/html",   _wrap_auth(api.get_html))
app.router.add_post(f"{p}/api/v1/forms/{{form_id}}/validate", _wrap_auth(api.validate))
app.router.add_put (f"{p}/api/v1/forms/{{form_id}}",     _wrap_auth(api.update_form))
app.router.add_patch(f"{p}/api/v1/forms/{{form_id}}",    _wrap_auth(api.patch_form))
app.router.add_post(f"{p}/api/v1/forms/{{form_id}}/data",_wrap_auth(api.submit_data))
# NEW route (this feature):
# app.router.add_post(f"{p}/api/v1/forms/{{form_id}}",   _wrap_auth(api.submit_result))
```

#### Verified Imports

```python
# All confirmed to work in the current tree:
from parrot.formdesigner.handlers.api import FormAPIHandler
from parrot.formdesigner.handlers.routes import setup_form_routes
from parrot.formdesigner.services.registry import FormRegistry, FormStorage
from parrot.formdesigner.services.storage import PostgresFormStorage
from parrot.formdesigner.services.submissions import FormSubmission, FormSubmissionStorage
from parrot.formdesigner.core.schema import FormSchema
```

#### Key Attributes & Constants

- `FormSchema.form_id` → `str` (form-type id, e.g. `"db-form-10-69"`)
  (packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:108)
- `FormSchema.version` → `str` (default `"1.0"`)
  (packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:109)
- `FormSubmission.submission_id` → `str` (UUID, current naming — will become `form_id` in the new
  result record per user-preferred terminology)
  (packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py:38-41)
- navigator-auth user context: `request.user.organizations[0].org_id`, `request.session["session"]["programs"]`
  (packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:167-170, 197-198)

### Does NOT Exist (Anti-Hallucination)

- ~~`FormResultStorage`~~ ABC — does NOT exist; will be created. `FormSubmissionStorage` will implement it.
- ~~`FormOperator` / `OperatorContext`~~ — NOT in the codebase; will be created.
- ~~`PydanticModelResolver`~~ — NOT in the codebase; will be created.
- ~~`UserDetails` operator~~ — NOT in the codebase; first concrete operator to ship.
- ~~`form_submissions_dlq` table~~ — does NOT exist; DDL is part of this feature.
- ~~`datamodel-code-generator` dependency~~ — NOT in `packages/parrot-formdesigner/pyproject.toml`; must be added.
- ~~New route `POST /api/v1/forms/{form_id}` (without `/data`)~~ — **not added**. This feature keeps
  the existing `POST /api/v1/forms/{form_id}/data` route and extends `submit_data` in place.
- ~~Hybrid metadata + JSONB submission table~~ — current `form_submissions` is flat JSONB only;
  this feature adds metadata columns via `ALTER TABLE`.
- ~~Per-form Pydantic model registry~~ — no `(form_id, version) → Type[BaseModel]` registry exists
  today; only the structural `FormValidator` (`self.validator` in `FormAPIHandler`), which remains
  as the fallback path.
- ~~DLQ / dead-letter pattern anywhere in `parrot-formdesigner`~~ — NOT present today.
- ~~Terminology `formid` as a field name in existing code~~ — current code uses `form_id` for the
  form-type id and `submission_id` for the per-submission UUID. The user's preferred terminology
  (`formid` = type, `form_id` = submission UUID) is **not adopted in code** for this feature to
  avoid a rename churn — see Open Questions.

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. The feature decomposes into (a) `FormOperator` ABC +
  `OperatorContext`, (b) `FormResultStorage` ABC, (c) `FormSubmissionStorage` extension (DDL + DLQ +
  `conn=` kwarg), (d) `PydanticModelResolver` + warm-up, (e) `UserDetails` operator,
  (f) `submit_data` rewrite + handler wiring. Pieces (a)–(e) are mostly independent of each other;
  (f) is the convergence point and depends on all of them.
- **Cross-feature independence**: Light conflict risk with `formdesigner-navigator-api-integration`
  (both edit `api.py`). Coordinate by keeping `__init__` kwarg additions stable and rewriting
  `submit_data` as an isolated method. No conflict with `form-abstraction-layer` or
  `formbuilder-database` (they edit `core/` and `services/registry.py`, not handlers or
  `submissions.py`).
- **Recommended isolation**: `per-spec`.
- **Rationale**: `submit_data` and `FormSubmissionStorage` are both edited — serializing in one
  worktree avoids conflicts on the DDL migration + handler rewrite and keeps the whole change
  reviewable in one PR. Matches the AI-Parrot worktree policy (`CLAUDE.md`).

---

## Open Questions

- [x] **Design**: parallel new endpoint vs. extend existing `/data` — *Owner: jesuslara*: **Extend
      the existing endpoint.** `POST /api/v1/forms/{form_id}/data` + `FormSubmissionStorage` stay as
      the canonical submission path; operators, DLQ, typed Pydantic, and metadata columns are layered
      on top via optional `__init__` kwargs. (Confirmed 2026-04-23.)
- [ ] Terminology: user's preferred convention is `formid` = form-type id, `form_id` = submission UUID,
      but the codebase uses `form_id` for the type and `submission_id` for the UUID. Current draft
      keeps codebase terminology (no rename) to avoid churn across `FormSchema`, `FormSubmission`,
      match-info parameters, and route paths. Confirm. — *Owner: jesuslara*
- [ ] Schema migration strategy: `ALTER TABLE form_submissions ADD COLUMN … NULL` at `initialize()`
      time (idempotent, current pattern), or require an out-of-band migration tool (alembic /
      manual SQL script)? — *Owner: jesuslara*
- [ ] Default operator catalog to ship in v1: `UserDetails` only, or also `ProgramContext`,
      `OrgContext`, `AuditTrail`? — *Owner: jesuslara*
- [ ] DLQ retention: default window (7d? 30d?) and whether to ship a cleanup task or leave to ops. — *Owner: jesuslara*
- [ ] Max body size guardrail: default (1 MB?), and enforced at aiohttp level (`client_max_size`)
      or inside the handler? — *Owner: jesuslara*
- [ ] Pydantic model warm-up trigger: at `FormRegistry.load_from_storage()` time, at first-submission
      lazily per `(form_id, version)`, or both? — *Owner: jesuslara*
- [ ] Idempotency: should the endpoint support an `Idempotency-Key` header (deduplication on retry)?
      Out of scope for v1 or in-scope? — *Owner: jesuslara*
- [ ] Does `post_save` run **inside** the main transaction (side-effect failures abort the save) or
      **after commit** (fire-and-forget)? Current draft assumes *inside* the transaction. — *Owner: jesuslara*
- [ ] Static Pydantic model registration API: decorator (`@register_form_model("db-form-10-69", "1.2")`),
      explicit kwarg on `FormAPIHandler.__init__` (`pydantic_models={(id, ver): Model}`), or both? — *Owner: jesuslara*
- [ ] Response body shape when operators run: stick with today's extended-200 shape (as drafted) or
      switch to 201 Created with a minimal body `{submission_id, form_id, form_version, status, created_at}`
      (closer to user's earlier stated preference)? — *Owner: jesuslara*
