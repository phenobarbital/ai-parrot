# Brainstorm: parrot-formdesigner-post-method

**Date**: 2026-04-23
**Author**: jesuslara
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

`parrot-formdesigner` exposes `GET /api/v1/forms/{form_id}` (+ `/schema`, `/style`, `/html`) to render
form designs, and already has a minimal `POST /api/v1/forms/{form_id}/data` endpoint that validates
a payload against the form's structural JSON schema and persists a flat JSONB row via
`FormSubmissionStorage`.

What is missing is a **first-class submission pipeline** with:
- Strong typed validation through a Pydantic model derived from the form design (static-registered
  if present, else pre-generated offline from the JSON schema at FormRegistry warm-up).
- An **operator pipeline** — ordered class-based hooks (`pre_validate`, `post_validate`, `pre_save`,
  `post_save`) attached to the form at `FormDesigner` / `FormAPIHandler` init time, allowing business
  rules and data enrichment (e.g., a `UserDetails` operator that augments the payload with session data).
- A **pluggable `FormResultStorage`** (Postgres first) using a **hybrid table**: fixed metadata columns
  (`form_id` [submission UUID], `formid` [form-type id], `form_version`, `user_id`, `org_id`, `program`,
  `client`, `status`, timestamps) + a JSONB column for the dynamic, form-specific payload.
- **Fail-fast with atomic DLQ**: if validation or any operator fails, the user gets a structured error
  but the failed attempt is persisted to a dead-letter table within the same Postgres transaction for
  debugging/retry.
- A canonical route `POST /api/v1/forms/{formid}` (distinct from the existing `/data` endpoint, which
  has different semantics and is kept for backward compatibility).

The existing `submit_data` flow cannot absorb this without breaking current callers — it is structurally
validated only, stores flat JSONB, has no operator hooks, and has no DLQ.

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

### Option A: Extend `submit_data` + retrofit `FormSubmissionStorage` in place

Modify `FormAPIHandler.submit_data` (packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:446-535)
to call a new operator pipeline between validation and save. Extend
`FormSubmissionStorage` (packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py:54-136)
by adding columns (`user_id`, `org_id`, `program`, `client`, `status`) to `form_submissions` and a
DLQ table. Keep the route at `/api/v1/forms/{form_id}/data`.

✅ **Pros:**
- Smallest diff; single route.
- Leverages existing handler and table.

❌ **Cons:**
- `/data` suffix contradicts the user's plan and makes the URL less clean.
- Schema migration on `form_submissions` is a breaking change for any existing consumer.
- Conflates two concepts (structural-only submissions + operator-pipeline submissions) in one class.
- Harder to evolve independently (e.g., different retention policies per concept).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `datamodel-code-generator` | JSON schema → Pydantic class | offline codegen at warm-up; new dep |
| `asyncpg` | Postgres driver | already used |

🔗 **Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:446-535` — `submit_data`
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py:54-136` — `FormSubmissionStorage`

---

### Option B: New parallel endpoint, new `FormResultStorage`, new `FormOperator` pipeline

Add a new canonical submission path alongside the existing one:
- New ABC `FormOperator` with async hooks `pre_validate(payload) → payload`,
  `post_validate(validated) → validated`, `pre_save(record) → record`, `post_save(record, conn) → None`.
  Each hook is optional (default no-op).
- New ABC `FormResultStorage` with `store(record, *, conn) → uuid` and `store_dlq(attempt, error, *, conn) → uuid`.
- New `PostgresFormResultStorage` with two new tables (`form_results`, `form_results_dlq`), using asyncpg
  and the same "class-level SQL constants + pool" style as `PostgresFormStorage`
  (packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:39-244).
- New handler method `FormAPIHandler.submit_result` + new route
  `POST /api/v1/forms/{form_id}` registered in `routes.py` alongside existing routes
  (packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py:146-159).
- New kwargs on `FormAPIHandler.__init__` and `setup_form_routes`:
  `operators: list[FormOperator] | None = None`, `result_storage: FormResultStorage | None = None`.
- Pydantic model resolution service: static registry `{(formid, version): Type[BaseModel]}` + a
  cache of datamodel-code-generator-produced classes, warmed at `FormRegistry.load_from_storage()`.
- First shipped operator: `UserDetails` (reads `request.user` / `request.session["session"]`,
  injects `user_id`, `org_id`, `programs` into the record metadata).

✅ **Pros:**
- Clean separation; no breaking change to existing `/data` consumers.
- URL matches the user's plan (`POST /api/v1/forms/{formid}`).
- New tables carry hybrid metadata + JSONB without migrating existing `form_submissions`.
- `FormResultStorage` has a narrow, write-only contract — easy to add non-Postgres backends later.
- Operators as classes let a single plugin subscribe to several phases and carry shared state
  across hooks (e.g., resolve user once, use it in both `post_validate` and `pre_save`).
- Mirrors the proven `FormStorage` ABC pattern already in the codebase.

❌ **Cons:**
- Two submission endpoints live in parallel → documentation/deprecation follow-up required.
- More new files (3 services + tests + 1 operator).
- `datamodel-code-generator` is a heavier dep than runtime `pydantic.create_model()`.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `datamodel-code-generator` | JSON schema → Pydantic class (offline) | mature, PyPI, ≥0.25 |
| `asyncpg` | Postgres driver + explicit transactions | already used |
| `pydantic` ≥ 2 | Validation, typed records | already a dep |

🔗 **Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:85-116` — `FormAPIHandler.__init__` shape
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:151-198` — `_get_org_id`, `_get_programs`
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py:82-159` — `setup_form_routes`
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py:29-91` — `FormStorage` ABC pattern
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:39-244` — `PostgresFormStorage` style (class-level SQL constants + asyncpg pool)
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py:54-136` — `FormSubmissionStorage` insert pattern

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

**Option B** is recommended because:

- The new feature introduces **qualitatively different semantics** from the existing `submit_data` —
  operator pipeline, typed Pydantic validation, hybrid metadata+JSONB storage, DLQ — and a parallel
  path lets us ship these without taking a compatibility risk on a currently-used endpoint.
- It **matches the user's URL contract** (`POST /api/v1/forms/{formid}`) without any redirect gymnastics.
- It **mirrors an established pattern**: `FormResultStorage` ↔ `FormStorage` ABC,
  `PostgresFormResultStorage` ↔ `PostgresFormStorage`, "class-level SQL constants + asyncpg pool"
  insert style — reviewers already know what to look for.
- `FormSubmissionStorage` and `submit_data` stay as-is; a follow-up spec can deprecate or re-point
  them once the new flow is battle-tested. This isolates risk.
- Offline codegen via `datamodel-code-generator` at warm-up avoids per-request model construction
  cost and keeps the request path predictable.

Tradeoff accepted: two submission endpoints coexist for a window. Mitigated by (a) documenting
`/forms/{formid}` as canonical, (b) a follow-up "deprecate /data" ticket, and (c) keeping the new
handler method small so the overlap is obvious in the codebase.

---

## Feature Description

### User-Facing Behavior

- **Endpoint**: `POST /api/v1/forms/{formid}` where `formid` is the form-type identifier
  (e.g. `db-form-10-69`, already used as the path parameter for `GET /api/v1/forms/{form_id}`
  — same path parameter, different semantics depending on HTTP method).
- **Auth**: requires a valid `navigator-auth` session (same decorator stack already applied to other
  REST routes in `routes.py`).
- **Request body**: JSON object matching the form's fields.
- **Success response — 201 Created**:
  ```json
  {
    "form_id": "3e1a…-uuid",
    "formid": "db-form-10-69",
    "form_version": "1.2",
    "status": "accepted",
    "created_at": "2026-04-23T12:34:56Z"
  }
  ```
  Here `form_id` is the **per-submission UUID** and `formid` is the **form-type id** (per user Q&A).
- **Validation failure — 422 Unprocessable Entity**:
  ```json
  { "errors": [{"loc": ["field"], "msg": "...", "type": "..."}], "form_id": "<dlq-uuid>" }
  ```
  Attempt persisted to `form_results_dlq` with `stage = "validate"`.
- **Operator failure — 500 Internal Server Error** with DLQ row + correlation id.
- **Unknown formid — 404**. **Malformed JSON — 400**. **Payload too large — 413** (guardrail).

### Internal Behavior

1. **Resolve form**: `registry.get(formid) → FormSchema | None`. 404 on None.
2. **Resolve Pydantic model** via `PydanticModelResolver.resolve(formid, version)`:
   - Look up static registry first (developer-registered classes keyed by `(formid, version)`).
   - Else return cached class produced by `datamodel-code-generator` against the form's JSON schema
     (cache is populated at `FormRegistry.load_from_storage()` time; fallback is on-demand generation
     if a form was added after warm-up).
3. **Acquire transaction**: `async with pool.acquire() as conn: async with conn.transaction():` …
4. **Pipeline (inside the transaction)**:
   - `for op in operators: payload = await op.pre_validate(payload, ctx)` — operators may mutate
     raw payload (e.g., decode legacy field names).
   - `validated = PydanticModel.model_validate(payload)` — structural + type validation.
   - `for op in operators: validated = await op.post_validate(validated, ctx)` — business rules,
     enrichment.
   - Build `FormResultRecord`:
     - metadata: `form_id=uuid4()`, `formid`, `form_version`, `user_id`, `org_id`, `program`, `client`,
       `status="submitted"`, `created_at=now(UTC)`
     - `payload` (JSONB): `validated.model_dump()`
     - `enrichment` (JSONB): collected from operator mutations that belong in a structured sidecar
       rather than the raw payload.
   - `for op in operators: record = await op.pre_save(record, ctx)`.
   - `await result_storage.store(record, conn=conn)`.
   - `for op in operators: await op.post_save(record, ctx, conn=conn)` — side effects under the same
     transaction (e.g., insert an approval-workflow row).
5. **Commit**, return 201 minimal body.
6. **On exception at any stage after step 3**: rollback the main transaction, then in a **separate
   short transaction** insert a `form_results_dlq` row containing the raw payload, the stage
   (`"pre_validate" | "validate" | "post_validate" | "pre_save" | "store" | "post_save"`), the
   exception repr, a traceback excerpt, and a correlation id; return the appropriate error response
   with the DLQ correlation id.

### Edge Cases & Error Handling

- **No Pydantic model resolvable** (no static registration AND datamodel-code-generator failed):
  500 + DLQ with `stage="model_resolve"`, `error="no_model"`.
- **Stale schema**: client submits against `form_version` V1 but registry only has V2. If static
  registry has a V1 model → accept as historical; else 422 with `code="stale_schema"` + DLQ entry.
- **User has no org / no programs**: `UserDetails` operator raises → DLQ with `stage="post_validate"`.
  (Alternatively, the operator is configurable to soft-warn; decided per operator, not globally.)
- **Storage unavailable / pool exhausted**: 503; DLQ write also fails → structured log entry only.
- **Large payload** (>configurable `max_body_size`, default 1 MB): 413 early, no pipeline invocation.
- **Operator raises non-exception cancellation** (e.g., `asyncio.CancelledError`): propagate without
  DLQ (client disconnected).
- **Duplicate submission** (same idempotency key if provided): out of scope for this feature — Open
  Question logged.

---

## Capabilities

### New Capabilities
- `form-post-endpoint`: `POST /api/v1/forms/{formid}` endpoint that runs the full submission pipeline.
- `form-operator-pipeline`: `FormOperator` ABC + sequential invocation with
  `pre_validate`/`post_validate`/`pre_save`/`post_save` async hooks and a per-request `ctx` carrying
  `request`, `form_schema`, `user`, `org_id`, `programs`, operator-shared scratchpad.
- `form-result-storage`: `FormResultStorage` ABC (write-only: `store`, `store_dlq`) plus
  `PostgresFormResultStorage` implementation.
- `form-pydantic-resolution`: `PydanticModelResolver` — static registry + offline-generated cache
  keyed by `(formid, version)`; warm-up hook on `FormRegistry.load_from_storage()`.
- `form-userdetails-operator`: first concrete `FormOperator` that reads the navigator-auth session
  and stamps `user_id`, `org_id`, `programs` onto the record metadata.

### Modified Capabilities
- None structurally — `FormAPIHandler.__init__` and `setup_form_routes` gain optional kwargs in a
  non-breaking way.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:85-116` | extends | `FormAPIHandler.__init__` gains `operators`, `result_storage`, `pydantic_resolver` kwargs |
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py` (new method) | adds | new `submit_result` coroutine handling `POST /api/v1/forms/{form_id}` |
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py:82-159` | extends | new `setup_form_routes` kwargs + new `add_post` for the canonical path |
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/` | adds | `operators.py` (ABC + ctx), `result_storage.py` (ABC), `postgres_result_storage.py` (impl), `pydantic_resolver.py` |
| `packages/parrot-formdesigner/src/parrot/formdesigner/operators/` | adds | `user_details.py` (first operator) |
| `packages/parrot-formdesigner/src/parrot/formdesigner/core/result.py` | adds | `FormResultRecord`, `DLQRecord`, `OperatorContext` Pydantic models |
| `packages/parrot-formdesigner/pyproject.toml` | adds dep | `datamodel-code-generator>=0.25` |
| Postgres DDL | adds | `form_results` (hybrid metadata + JSONB) and `form_results_dlq` tables; `initialize()` on handler wire-up |
| Existing `form_submissions` table + `submit_data` | untouched | kept as-is; follow-up spec will decide deprecation path |
| Existing `FormSubmissionStorage` | untouched | parallel class with different semantics |

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

- ~~`FormResultStorage`~~ — class does NOT exist; will be created by this feature.
- ~~`FormOperator` / `FormPipeline`~~ — NOT in the codebase; will be created.
- ~~`PydanticModelResolver`~~ — NOT in the codebase.
- ~~`UserDetails` operator~~ — NOT in the codebase.
- ~~`form_results` / `form_results_dlq` tables~~ — do NOT exist; DDL is part of this feature.
- ~~`datamodel-code-generator` dependency~~ — NOT in `packages/parrot-formdesigner/pyproject.toml`; must be added.
- ~~`POST /api/v1/forms/{form_id}` (without `/data`)~~ — route does NOT exist yet; only GET/PUT/PATCH
  handlers are registered on that exact path. The existing POST is on `/api/v1/forms/{form_id}/data`.
- ~~Hybrid metadata + JSONB submission table~~ — current `form_submissions` is flat JSONB only.
- ~~Per-form Pydantic model registry~~ — there is no `(formid, version) → Type[BaseModel]` registry; only the
  structural `FormValidator` (`self.validator` in `FormAPIHandler`).
- ~~`DLQ` / dead-letter pattern anywhere in `parrot-formdesigner`~~ — NOT present; new for this feature.
- ~~Terminology `formid` as a field name in existing code~~ — current code uses `form_id` for the
  form-type id and `submission_id` for the per-submission UUID. The user's preferred terminology
  (`formid` = type, `form_id` = submission UUID) is **new and intentionally differs** — see Open Questions.

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. The feature decomposes into several independent-ish pieces —
  (a) `FormOperator` ABC + `OperatorContext`, (b) `FormResultStorage` ABC + `FormResultRecord`,
  (c) `PostgresFormResultStorage` + DDL, (d) `PydanticModelResolver` + warm-up, (e) `UserDetails`
  operator, (f) handler method + route wiring. However, they all **converge on
  `FormAPIHandler.__init__` and `setup_form_routes`**, so a tasks-in-parallel split would invite
  merge conflicts on those two files.
- **Cross-feature independence**: Minimal conflict with other in-flight work. The
  `formdesigner-navigator-api-integration` brainstorm also touches `api.py` — coordinate by keeping
  the new handler method additive and not re-ordering existing methods. No conflict with
  `form-abstraction-layer` or `formbuilder-database` (they touch `core/` and `services/registry.py`
  schemas, not handlers).
- **Recommended isolation**: `per-spec`.
- **Rationale**: Tasks share a small convergence zone (`api.py` `__init__` kwargs, `routes.py`
  registration, `pyproject.toml` dep add). Serializing tasks in one worktree eliminates merge
  churn, keeps the whole wiring reviewable in one PR, and matches the AI-Parrot convention
  (`CLAUDE.md` worktree policy).

---

## Open Questions

- [ ] Terminology clash: user's convention is `formid` = form-type id, `form_id` = submission UUID,
      but the existing codebase uses `form_id` for the type and `submission_id` for the UUID. Should
      the new module follow the user's terminology (and rename in `FormResultRecord` only) or adopt
      the existing convention for consistency across the package? — *Owner: jesuslara*
- [ ] Deprecation path for `POST /api/v1/forms/{form_id}/data` + `FormSubmissionStorage`: keep
      indefinitely, mark deprecated in docs, or re-point to the new pipeline in a follow-up spec? — *Owner: jesuslara*
- [ ] Default operator catalog to ship in v1: `UserDetails` only, or also `ProgramContext`,
      `OrgContext`, `AuditTrail`? — *Owner: jesuslara*
- [ ] DLQ retention: default retention window (7d? 30d?) and whether to ship a cleanup task or
      leave it to ops. — *Owner: jesuslara*
- [ ] Max body size guardrail: default (1 MB?), and is this enforced at aiohttp level (`client_max_size`)
      or inside the handler? — *Owner: jesuslara*
- [ ] Pydantic model warm-up trigger: at `FormRegistry.load_from_storage()` time, at first-submission
      per `(formid, version)` lazily, or both? — *Owner: jesuslara*
- [ ] Idempotency: should the endpoint support an `Idempotency-Key` header (deduplication on retry)?
      Out of scope for v1 or in-scope? — *Owner: jesuslara*
- [ ] Does `post_save` run **inside** the main transaction (so side-effect failures abort the save)
      or **after commit** (fire-and-forget side effects)? Current draft assumes *inside* the
      transaction — confirm this matches the user's intent for operators that call external systems. — *Owner: jesuslara*
- [ ] Static Pydantic model registration API: decorator (`@register_form_model("db-form-10-69", "1.2")`),
      explicit kwarg on `FormAPIHandler.__init__` (`pydantic_models={(id, ver): Model}`), or both? — *Owner: jesuslara*
