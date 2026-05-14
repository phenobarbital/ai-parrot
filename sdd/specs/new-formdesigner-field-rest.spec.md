---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: FormDesigner — `FieldType.REST` (REST-driven upload field with response-derived answer)

**Feature ID**: FEAT-170
**Date**: 2026-05-14
**Author**: jesuslara
**Status**: approved
**Target version**: parrot-formdesigner 0.5.0

> **Source of design decisions**: this spec is derived from
> `sdd/proposals/new-formdesigner-field-rest.brainstorm.md` (Recommended
> Option A). All 9 of that document's Open Questions are resolved and
> carried forward verbatim into §8 below.

---

## 1. Motivation & Business Requirements

### Problem Statement

Form designers currently have **no way to express a field whose value is the
processed response of an external operation that consumes user-supplied
content**. The closest existing primitive — `FieldType.REMOTE_RESPONSE`
(FEAT-167 Phase 3, `services/remote_response_resolver.py:66`) — is
**read-only and display-oriented**: it fetches data from the server and
shows it. It does not accept user input, cannot upload binary content,
and has no mechanism to invoke local Python code in response to a
submission.

The motivating use case is *"Subir foto para planogram compliance"*: the
user uploads a shelf photo from the form, the photo is forwarded to a
planogram-compliance REST API which returns a JSON judgement (e.g.,
`{"compliance_score": 0.86, "violations": [...]}`), and the *processed
score* becomes the answer to that question in the form submission. The
binary photo is also persisted alongside the submission for audit.

The new `FieldType.REST` must support three destinations for the upload:

1. **Remote REST API** (absolute URL, configurable auth via `AuthContext`).
2. **Internal endpoint** (strict relative path like
   `/api/v1/networkninja/photo-analyze`, prepended with the running
   aiohttp app's host — see §7 *Patterns to Follow*), reusing the inbound
   `AuthContext` Bearer cascade (`api/handlers.py:149`).
3. **In-process callback** (Python coroutine registered via a
   tenant-scoped decorator registry; parrot-formdesigner exposes a
   parametric aiohttp route at
   `POST /api/v1/forms/{form_id}/fields/{field_id}/upload` that
   dispatches to the registered callback by name).

The API response is optionally **post-processed** via a JSONPath
expression (e.g., `$.compliance_score`) and the extracted value becomes
the field answer. The original binary is persisted via a new
`AbstractBlobStorage` (S3-compatible default) and referenced by the
submission. The `display_template` config option uses **Jinja2** to
render the answer in the frontend.

This is a peer of `REMOTE_RESPONSE` (display) and `FILE`/`IMAGE` (raw
upload), **not a replacement** for either. The frontend control is an
*active uploader* whose semantic is "submit content → receive computed
answer".

### Goals

- Add **one** new `FieldType.REST` enum value (category `"advanced"`).
- Define `RestFieldSpec` as a Pydantic v2 **discriminated union** keyed
  on `mode: Literal["remote", "internal", "callback"]`, embedded in
  `FormField.meta["rest"]`. Mode-conditional required-field validation
  via `field_validator`.
- Add an `AbstractBlobStorage` abstract service plus a default
  `S3BlobStorage` implementation (aioboto3), pluggable at app
  bootstrap. Include a **stub `pre_persist_hook` interface** for
  future AV/content-scanning integration; the hook is exposed and
  callable in V1 but a no-op by default — the full AV pipeline is
  deferred to V2.
- Add a **tenant-scoped** callback registry
  (`services/callback_registry.py`) with `@register_form_callback(name,
  *, tenant=None)` and `get_form_callback(name, tenant=None)`. Callbacks
  are pre-registered Python coroutines — **no dotted-path import** from
  form JSON.
- Add `services/rest_field_resolver.py` with `RestFieldResolver.resolve(
  spec, payload, *, auth_context)` that dispatches by `mode`. Mirrors
  the `RemoteResponseResolver` aiohttp pattern (do NOT subclass).
- Register a new aiohttp route at
  `POST /api/v1/forms/{form_id}/fields/{field_id}/upload` in
  `setup_form_api()`, wrapped with the existing
  `is_authenticated + user_session` decorators
  (`api/routes.py:_wrap_auth`).
- Apply optional `response_path` extraction via `jsonpath-ng>=1.6.1`.
- Apply optional `display_template` rendering via Jinja2 (already a
  dependency at `pyproject.toml:jinja2>=3.1`). Frontend receives the
  pre-rendered string in addition to the raw answer.
- Extend `FormValidator` with one validator branch for `FieldType.REST`
  enforcing the submitted-value shape `{answer, blob_ref, status?}` and
  rejecting `status == "in_progress"` at submit time.
- Register the new type in `controls/builtin._BUILTIN_METADATA`
  (category `"advanced"`), seed an example snippet in
  `tools/field_helpers._FIELD_SCHEMA_SNIPPETS`, and add reverse
  mappings in `extractors/jsonschema.py` and `extractors/yaml.py`.
- Per-renderer registration: HTML5 native (`<RestUploader>` markup),
  JsonSchema native (object schema with `properties.answer` and
  `properties.blob_ref`), `FallbackRenderer` for PDF / XForms /
  AdaptiveCard, Telegram WebApp redirect (consistent with `SIGNATURE`).
- **Generate Frontend implementation documentation** as a build
  artifact under `packages/parrot-formdesigner/docs/frontend/rest-field.md`
  so the frontend repo can consume the contract without re-deriving it
  from the JSON Schema.
- Backwards-compatible: existing serialized forms validate and render
  unchanged. Public renderer APIs unchanged.

### Non-Goals (explicitly out of scope)

- **Frontend (separate repo) UI implementation.** The form-builder UI
  and the runtime `<RestUploader>` component live in the frontend repo
  and consume the JSON Schema + the auto-generated docs produced by
  this spec. A follow-up spec will cover frontend work.
- **Chunked / resumable uploads (tus, resumable.js)**. V1 uses a single
  multipart request — size policed via
  `FieldConstraints.max_file_size_bytes`. Video is supported but only
  within that single-request limit.
- **Per-field blob retention policy**. V1 deletes the previous
  `blob_ref` synchronously on re-upload and otherwise relies on the
  S3 bucket's lifecycle policy for long-term retention. Per-field
  retention can be added in V2.
- **Per-mode `FieldType` values (`REST_REMOTE` / `REST_INTERNAL` /
  `REST_CALLBACK`)** — rejected in brainstorm Option B (triples surface
  area for a UX-only gain).
- **Generalised `LiveFieldResolver` protocol refactor** — rejected in
  brainstorm Option C (destabilises recently-merged FEAT-167 code).
- **Plugin entry points for third-party REST modes** — the `mode`
  discriminator is a closed Literal. Same policy as FEAT-167.
- **Dotted-path callback resolution** — rejected; callbacks must be
  pre-registered. Closed allow-list owned by application bootstrap.
- **Full antivirus/content-scanning pipeline**. V1 ships the
  `pre_persist_hook` interface as a stub; full integration is deferred
  to V2.
- **Concurrent-upload locking per (submission, field)**. V1 uses
  last-write-wins. Per-field locks may be added in V2.

---

## 2. Architectural Design

### Overview

The feature ships in **one feature** across **three internal phases**.
Phasing keeps Phase 1 (infrastructure) green before any user-visible
field type appears, mirroring FEAT-167's strategy.

- **Phase 1 — Foundation services.** Three new service modules that are
  independently testable: `services/blob_storage.py`
  (`AbstractBlobStorage`, `S3BlobStorage`, `pre_persist_hook` stub),
  `services/callback_registry.py` (tenant-scoped `_CALLBACK_REGISTRY`,
  `@register_form_callback` decorator, `get_form_callback` lookup),
  and `services/rest_field_resolver.py` (`RestFieldSpec` discriminated
  union, `RestFieldResolver` dispatcher, `RestFieldResult`). No
  user-visible changes yet — no `FieldType` value, no upload route.

- **Phase 2 — Schema + field type.** Add `FieldType.REST = "rest"`,
  extend `_BUILTIN_METADATA` and `_FIELD_SCHEMA_SNIPPETS`, add the
  validator branch in `services/validators.py`, and add the extractor
  reverse-mappings. Renderers register native (HTML5, JSON Schema) or
  fallback (PDF, XForms, Adaptive Card) entries in their `_registry`
  dicts. Telegram registers a WebApp redirect entry. The `FormField`
  remains unchanged at the schema level — `RestFieldSpec` is embedded
  under `meta["rest"]` (the schema already accepts arbitrary `meta`).

- **Phase 3 — API integration.** Wire the
  `POST /api/v1/forms/{form_id}/fields/{field_id}/upload` route in
  `setup_form_api()`. Add `FormAPIHandler.handle_rest_upload` (or a
  dedicated module under `api/uploads.py`) that authenticates the
  request, parses multipart, resolves field + spec, builds
  `AuthContext`, dispatches via `RestFieldResolver`, persists the
  binary via the configured `AbstractBlobStorage`, applies JSONPath +
  Jinja2 rendering, and returns the JSON envelope. Auto-generate the
  Frontend implementation doc under `docs/frontend/rest-field.md` as
  part of the build.

### Component Diagram

```
        ┌─────────────────────────────────────┐
        │  Frontend (separate repo)           │
        │  <RestUploader> component           │
        └──────────┬──────────────────────────┘
                   │ POST /api/v1/forms/{form_id}/fields/{field_id}/upload
                   │ multipart/form-data
                   ▼
        ┌─────────────────────────────────────┐
        │  api/routes.setup_form_api          │
        │  + _wrap_auth (navigator-auth)      │
        └──────────┬──────────────────────────┘
                   │
                   ▼
        ┌─────────────────────────────────────┐
        │  FormAPIHandler.handle_rest_upload  │
        │  - load FormField from registry     │
        │  - parse multipart, MIME check      │
        │  - build AuthContext                │
        └──────────┬──────────────────────────┘
                   │ RestFieldSpec, content, AuthContext
                   ▼
        ┌─────────────────────────────────────┐
        │  RestFieldResolver.resolve          │
        │  switch on spec.mode:               │
        │    remote   → aiohttp ext URL       │
        │    internal → aiohttp <host>/path   │
        │    callback → invoke registered fn  │
        └──────────┬──────────────────────────┘
                   │ RestFieldResult(raw_value, …)
                   ▼
       ┌──────────────────────┐  ┌──────────────────────┐
       │  AbstractBlobStorage │  │  jsonpath-ng         │
       │  .put(blob, meta)    │  │  (response_path)     │
       │  pre_persist_hook    │  └──────────┬───────────┘
       │  (V1 stub)           │             │
       └──────────┬───────────┘             ▼
                  │                  ┌──────────────────┐
                  │                  │  Jinja2          │
                  │                  │  (display_template) │
                  │                  └──────────┬───────┘
                  ▼                             ▼
       blob_ref               answer + display
                  └──────────┬───────────┘
                             ▼
        JSON response: {answer, blob_ref, raw_value, display, warnings}
```

At form submission time:

```
        ┌─────────────────────────────────────┐
        │  Frontend submits form              │
        │  data[field_id] = {answer,blob_ref} │
        └──────────┬──────────────────────────┘
                   │
                   ▼
        ┌─────────────────────────────────────┐
        │  FormAPIHandler.submit_data         │
        │  + FormValidator.validate_field     │
        │  - REST branch checks               │
        │    {answer, blob_ref} shape         │
        │  - rejects status="in_progress"     │
        └──────────┬──────────────────────────┘
                   │
                   ▼
        FormSubmissionStorage.store(submission)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot_formdesigner.core.types.FieldType` | extends (additive) | +1 enum value `REST = "rest"`. |
| `parrot_formdesigner.core.schema.FormField.meta` | depends on | New `meta["rest"]: RestFieldSpec.model_dump()` convention. No schema change. |
| `parrot_formdesigner.core.constraints.FieldConstraints` | reuses | `allowed_mime_types`, `max_file_size_bytes` police upload constraints. No new fields. |
| `parrot_formdesigner.services.auth_context.AuthContext` | reuses | `resolve_for(auth_ref)` for outbound auth in `remote`/`internal` modes; same instance cascades into nested fields. |
| `parrot_formdesigner.services.validators.FormValidator` | extends | +1 branch for `FieldType.REST` (coerce + shape check + status gate). |
| `parrot_formdesigner.services.submissions.FormSubmissionStorage` | reuses | Persistence of the resolved `{answer, blob_ref}` in `FormSubmission.data`. |
| `parrot_formdesigner.controls.builtin._BUILTIN_METADATA` | extends | +1 entry: `FieldType.REST` → `category="advanced"`. |
| `parrot_formdesigner.controls.registry.register_field_control` | reuses | Called for the new type via `_seed()` side effect. |
| `parrot_formdesigner.tools.field_helpers._FIELD_SCHEMA_SNIPPETS` | extends | +1 example snippet (planogram-style). |
| `parrot_formdesigner.api.routes.setup_form_api` | extends | Mount `POST /api/v1/forms/{form_id}/fields/{field_id}/upload`. |
| `parrot_formdesigner.api.handlers.FormAPIHandler` | extends | New `handle_rest_upload` method (or extracted into `api/uploads.py`). Reuse `_build_auth_context`. |
| `parrot_formdesigner.renderers.html5.HTML5Renderer` | extends | Native `<RestUploader>` markup via `_registry`. |
| `parrot_formdesigner.renderers.jsonschema.JsonSchemaRenderer` | extends | Native object schema with `answer`/`blob_ref` properties. |
| `parrot_formdesigner.renderers.adaptive_card.AdaptiveCardRenderer` | extends | `FallbackRenderer` (no multipart in Adaptive Cards). |
| `parrot_formdesigner.renderers.pdf.PdfRenderer` | extends | `FallbackRenderer` (labelled placeholder + `RenderWarning`). |
| `parrot_formdesigner.renderers.xforms.XFormsRenderer` | extends | `FallbackRenderer` (ODK has its own upload primitives). |
| `parrot_formdesigner.renderers.telegram.TelegramFormRenderer` | extends | WebApp redirect (matches `SIGNATURE` / `TRANSFER_LIST` policy). |
| `parrot_formdesigner.extractors.jsonschema` | extends | `"rest"` ↔ `FieldType.REST`. |
| `parrot_formdesigner.extractors.yaml` | extends | `rest` ↔ `FieldType.REST`. |
| `parrot.registry` (decorator-registry idiom) | reference only | Pattern reused; **do NOT import** — callbacks live in a separate registry to avoid cross-domain coupling. |
| `packages/parrot-formdesigner/pyproject.toml` | extends | `+jsonpath-ng>=1.6.1`, `+aioboto3>=12.0`. Jinja2 already pinned. |

### Data Models

> **NOT IMPLEMENTATION — design only.**

```python
# parrot_formdesigner/services/rest_field_resolver.py — NEW

RestFieldMode = Literal["remote", "internal", "callback"]

class _RestFieldSpecBase(BaseModel):
    """Shared fields for every mode."""
    model_config = ConfigDict(extra="forbid")
    timeout_seconds: int = 30
    response_path: str | None = None          # JSONPath via jsonpath-ng
    display_template: str | None = None       # Jinja2 source
    persist_binary: bool = True
    response_schema: dict[str, Any] | None = None  # informational only

class RemoteRestFieldSpec(_RestFieldSpecBase):
    mode: Literal["remote"] = "remote"
    endpoint: str                              # absolute URL
    http_method: Literal["GET", "POST", "PUT", "PATCH"] = "POST"
    auth_ref: str | None = None

class InternalRestFieldSpec(_RestFieldSpecBase):
    mode: Literal["internal"] = "internal"
    endpoint: str                              # MUST start with "/" — see Patterns
    http_method: Literal["GET", "POST", "PUT", "PATCH"] = "POST"

class CallbackRestFieldSpec(_RestFieldSpecBase):
    mode: Literal["callback"] = "callback"
    callback_ref: str                          # key in _CALLBACK_REGISTRY

RestFieldSpec = Annotated[
    RemoteRestFieldSpec | InternalRestFieldSpec | CallbackRestFieldSpec,
    Field(discriminator="mode"),
]

class RestCallbackInput(BaseModel):
    """Payload passed to a registered callback."""
    model_config = ConfigDict(extra="forbid")
    form_id: str
    field_id: str
    session_id: str | None
    user_id: str | None
    tenant: str | None
    content_type: str
    content: Any                               # bytes for binary, str for text, dict for JSON
    extra_fields: dict[str, Any] = {}

class RestCallbackOutput(BaseModel):
    """Return value from a registered callback."""
    model_config = ConfigDict(extra="forbid")
    success: bool
    value: Any | None = None
    status_code: int | None = None
    error: str | None = None

class RestFieldResult(BaseModel):
    """Resolver output — never raises."""
    model_config = ConfigDict(extra="forbid")
    success: bool
    raw_value: Any | None = None
    answer: Any | None = None                  # post-JSONPath extraction
    blob_ref: str | None = None
    display: str | None = None                 # rendered Jinja2 output
    status_code: int | None = None
    warnings: list[str] = []                   # informational; convention: "code: detail"
    error: str | None = None
```

```python
# parrot_formdesigner/services/blob_storage.py — NEW

class BlobMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    form_id: str
    field_id: str
    submission_id: str | None = None
    tenant: str | None = None
    content_type: str
    size_bytes: int

class PrePersistContext(BaseModel):
    """Context passed to AbstractBlobStorage.pre_persist_hook in V1.

    The hook is a stub in V1 — it is invoked but the default
    implementation is a no-op pass-through. V2 will wire AV scanning here.
    """
    model_config = ConfigDict(extra="forbid")
    metadata: BlobMetadata
    content_preview: bytes | None = None       # first N bytes; None disables preview

class AbstractBlobStorage(ABC):
    """Abstract blob storage. Concrete impls: S3, GCS, local FS, etc."""

    @abstractmethod
    async def put(
        self,
        stream: AsyncIterator[bytes],
        *,
        metadata: BlobMetadata,
    ) -> str:
        """Persist a blob and return a stable blob_ref (e.g. 's3://bucket/key')."""

    @abstractmethod
    async def get(self, blob_ref: str) -> AsyncIterator[bytes]:
        """Stream a blob by ref."""

    @abstractmethod
    async def delete(self, blob_ref: str) -> None:
        """Delete a blob by ref. Idempotent — no error if missing."""

    async def pre_persist_hook(self, ctx: PrePersistContext) -> None:
        """Pre-write hook for AV/scanning. V1 default: no-op.

        Subclasses MAY raise BlobRejectedError to reject the blob.
        """
        return None

class S3BlobStorage(AbstractBlobStorage):
    """Default impl using aioboto3. Bucket + prefix from env vars."""

    def __init__(
        self,
        *,
        bucket: str | None = None,
        prefix: str = "",
        endpoint_url: str | None = None,
    ) -> None: ...
```

```python
# parrot_formdesigner/services/callback_registry.py — NEW

RestCallback = Callable[
    [RestCallbackInput, AuthContext],
    Awaitable[RestCallbackOutput],
]

# Tenant-scoped: key is (tenant_or_None, name). Tenant=None is the global
# fallback used when no tenant-specific entry exists. See §7 Patterns.
_CALLBACK_REGISTRY: dict[tuple[str | None, str], RestCallback] = {}

def register_form_callback(
    name: str,
    *,
    tenant: str | None = None,
) -> Callable[[RestCallback], RestCallback]:
    """Decorator registering a form callback.

    Tenant-scoped: pass tenant="<slug>" for tenant-specific behaviour;
    omit for a global default. Lookup falls back from tenant → global.

    Raises:
        ValueError if (tenant, name) is already registered (no override).
    """

def get_form_callback(
    name: str,
    *,
    tenant: str | None = None,
) -> RestCallback:
    """Lookup with tenant fallback to global. Raises KeyError if not found."""
```

### New Public Interfaces

```python
# parrot_formdesigner/services/rest_field_resolver.py — NEW

class RestFieldResolver:
    DEFAULT_TIMEOUT: int = 30

    def __init__(
        self,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        internal_base_url: str | None = None,
    ) -> None: ...

    async def resolve(
        self,
        spec: RestFieldSpec,
        payload: RestCallbackInput,
        *,
        auth_context: AuthContext | None = None,
        tenant: str | None = None,
    ) -> RestFieldResult:
        """Dispatch by spec.mode. Never raises — all errors flow into the result."""
```

```python
# parrot_formdesigner/api/uploads.py — NEW (or method on FormAPIHandler)

async def handle_rest_upload(request: web.Request) -> web.Response:
    """POST /api/v1/forms/{form_id}/fields/{field_id}/upload.

    Multipart-encoded. Auth: navigator-auth (is_authenticated +
    user_session). Returns JSON:

        {
            "success": bool,
            "answer": Any | None,
            "raw_value": Any | None,
            "blob_ref": str | None,
            "display": str | None,
            "warnings": list[...],
            "error": str | None,
        }
    """
```

---

## 3. Module Breakdown

Modules are ordered by dependency. Phase 1 modules (1–3) are independent
and can be implemented in parallel inside the same worktree.
Phase 2 modules (4–10) depend on the FieldType enum and Phase 1 services.
Phase 3 modules (11–13) depend on Phase 2.

### Phase 1 — Foundation services

#### Module 1: `services/blob_storage.py` (`AbstractBlobStorage` + `S3BlobStorage`)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py`
- **Responsibility**: Abstract async blob storage with default S3 impl
  using `aioboto3`. Stream-friendly `put` / `get` / `delete`. Stub
  `pre_persist_hook` (no-op in V1). `BlobMetadata`, `PrePersistContext`
  Pydantic models. Bucket/prefix/endpoint configurable via constructor;
  env-var fallback (`PARROT_BLOB_BUCKET`, `PARROT_BLOB_PREFIX`,
  `PARROT_BLOB_ENDPOINT_URL`).
- **Depends on**: none.

#### Module 2: `services/callback_registry.py` (tenant-scoped registry)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/callback_registry.py`
- **Responsibility**: `_CALLBACK_REGISTRY: dict[tuple[str | None, str], RestCallback]`,
  `@register_form_callback(name, *, tenant=None)` decorator,
  `get_form_callback(name, *, tenant=None)` with global fallback,
  `list_form_callbacks(tenant=None)` for introspection / docs generation.
  Duplicate registration raises `ValueError`.
- **Depends on**: none.

#### Module 3: `services/rest_field_resolver.py` (resolver + spec models)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/rest_field_resolver.py`
- **Responsibility**: `RemoteRestFieldSpec`, `InternalRestFieldSpec`,
  `CallbackRestFieldSpec` (Pydantic v2 discriminated union), `RestFieldSpec`
  alias, `RestCallbackInput`, `RestCallbackOutput`, `RestFieldResult`,
  `RestFieldResolver.resolve()` dispatching by `mode`. Apply `response_path`
  via `jsonpath-ng` and `display_template` via Jinja2 (sandboxed
  `jinja2.sandbox.SandboxedEnvironment` for safety). Never raises.
- **Depends on**: Modules 1, 2; existing `AuthContext`. Resolver
  warnings are emitted as `list[str]` on `RestFieldResult` (NOT
  `RenderWarning` — that model is renderer-scoped; see Patterns §7).

### Phase 2 — Schema + new field type

#### Module 4: `FieldType.REST` enum value
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py`
- **Responsibility**: Append `REST = "rest"` to the `FieldType` enum.
- **Depends on**: none (additive).

#### Module 5: `_BUILTIN_METADATA[FieldType.REST]` registration
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py`
- **Responsibility**: Add a new entry with `label="REST"`,
  `description="Upload content to a REST endpoint or callback; the API
  response becomes the field answer."`, `category="advanced"`,
  `icon="rest"`, `render_hint="upload"`, `supports_constraints=True`,
  `is_container=False`.
- **Depends on**: Module 4.

#### Module 6: Snippet seed in `tools/field_helpers.py`
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py`
- **Responsibility**: Add an example snippet under
  `_FIELD_SCHEMA_SNIPPETS[FieldType.REST.value]` showing the planogram
  use case (mode=callback, response_path=`$.compliance_score`,
  display_template, allowed_mime_types).
- **Depends on**: Module 4.

#### Module 7: Validator branch for `FieldType.REST`
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py`
- **Responsibility**: One coerce + validate branch enforcing:
  - submitted value is `{"answer": Any, "blob_ref": str | None,
    "status": str | None}`;
  - if `field.required` and (`answer is None` or value missing) → invalid;
  - if `status == "in_progress"` → reject with structured error
    `{field_id, status: "in_progress"}`;
  - `RestFieldSpec` round-trip (parse from `field.meta["rest"]`) — any
    parse error surfaces at form-design time, not runtime.
- **Depends on**: Modules 3, 4.

#### Module 8: Per-renderer registry entries
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/{html5,jsonschema,adaptive_card,pdf,xforms,telegram/renderer}.py`
- **Responsibility**:
  - HTML5: native `<RestUploader>` markup with hidden `answer` /
    `blob_ref` inputs plus a `<input type="file">` bound to the upload
    endpoint. Spinner + retry button hooks via data attributes.
  - JSON Schema: native object schema
    `{"type":"object","properties":{"answer":..., "blob_ref":{"type":["string","null"]}}}`
    plus an `x-parrot-rest` extension describing `mode`,
    `response_path`, `display_template`, and the upload URL template.
  - Adaptive Card / PDF / XForms: `FallbackRenderer` with a labelled
    placeholder + `RenderWarning(field_type="rest", renderer=…)`.
  - Telegram: WebApp redirect entry (matches `SIGNATURE` policy).
- **Depends on**: Modules 4, 5, FEAT-167 `FieldRenderer` /
  `FallbackRenderer` (`renderers/base.py`).

#### Module 9: Extractor reverse-mappings
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py`,
  `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/yaml.py`
- **Responsibility**: Add `"rest" → FieldType.REST` (yaml) and the
  corresponding JSON Schema fragment mapping. Round-trip the
  `RestFieldSpec` from `meta["rest"]`.
- **Depends on**: Module 4.

#### Module 10: `pyproject.toml` dependencies
- **Path**: `packages/parrot-formdesigner/pyproject.toml`
- **Responsibility**: Add `jsonpath-ng>=1.6.1` and `aioboto3>=12.0` to
  `dependencies`. Jinja2 already pinned at `>=3.1` — no change needed.
- **Depends on**: none.

### Phase 3 — API integration

#### Module 11: Upload route + handler
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/uploads.py` (new),
  `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`,
  `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
- **Responsibility**:
  - New module `api/uploads.py` with `handle_rest_upload(request)`
    wrapping the full pipeline.
  - Mount the route in `setup_form_api()`:
    `app.router.add_post(f"{bp}/forms/{{form_id}}/fields/{{field_id}}/upload",
    _wrap_auth(uploads.handle_rest_upload))`.
  - The handler resolves the `FormField` via `app["form_registry"]`,
    parses multipart, validates MIME / size via `field.constraints`,
    builds `AuthContext` via `_build_auth_context`, dispatches via
    `RestFieldResolver.resolve()`, persists via injected
    `AbstractBlobStorage` (looked up at `app["blob_storage"]`), and
    returns the JSON envelope.
- **Depends on**: Modules 1–7, FEAT-152 (`navigator-auth` hard dep).

#### Module 12: App bootstrap wiring
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
- **Responsibility**: Extend `setup_form_api()` signature with
  `blob_storage: AbstractBlobStorage | None = None` and
  `resolver: RestFieldResolver | None = None` kwargs. Stash both on
  the aiohttp `app` so handlers can retrieve them per request.
  Defaults: `S3BlobStorage()` and `RestFieldResolver()` constructed
  lazily on first use.
- **Depends on**: Modules 1, 3.

#### Module 13: Frontend implementation docs (auto-generated)
- **Path**: `packages/parrot-formdesigner/docs/frontend/rest-field.md`
  (output; generated by a small script under
  `packages/parrot-formdesigner/scripts/gen_frontend_docs.py`)
- **Responsibility**: Generate (and re-generate on demand) a
  human-readable doc describing the JSON Schema fragment, the upload
  endpoint contract, the response envelope shape, error codes
  (`400 in_progress`, `413 too_large`, `415 unsupported_media_type`,
  `500 callback_not_registered`, etc.), and a worked example
  (planogram compliance). The script reads the Pydantic models and the
  schema renderer's `x-parrot-rest` extension, so docs cannot drift
  from code.
- **Depends on**: Modules 3, 8, 11.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_field_type_rest_present` | 4 | `FieldType.REST.value == "rest"`. |
| `test_builtin_metadata_rest_category_advanced` | 5 | `_BUILTIN_METADATA[FieldType.REST]["category"] == "advanced"`. |
| `test_field_helpers_rest_snippet_planogram` | 6 | Snippet round-trips to a valid `FormField` with `mode="callback"`. |
| `test_validator_rest_shape_accepts_answer_blob_ref` | 7 | Submitted value `{"answer": 0.86, "blob_ref": "s3://..."}` passes. |
| `test_validator_rest_required_rejects_null_answer` | 7 | `required=True` + `answer is None` raises. |
| `test_validator_rest_rejects_status_in_progress` | 7 | Value `{"answer": null, "blob_ref": null, "status": "in_progress"}` rejected with structured error. |
| `test_rest_field_spec_discriminated_remote` | 3 | `RestFieldSpec.model_validate({"mode":"remote",...})` returns `RemoteRestFieldSpec`. |
| `test_rest_field_spec_discriminated_internal_requires_leading_slash` | 3 | `mode="internal"` with `endpoint="api/x"` raises (must start with `/`). |
| `test_rest_field_spec_discriminated_callback` | 3 | Discriminator selects `CallbackRestFieldSpec`. |
| `test_rest_field_spec_extra_forbid` | 3 | Unknown keys rejected. |
| `test_resolver_remote_dispatches_via_aiohttp` | 3 | Mock aiohttp endpoint receives the POST with body + auth headers. |
| `test_resolver_internal_prepends_base_url` | 3 | `internal_base_url="http://localhost:8080"` + `endpoint="/api/v1/x"` calls `http://localhost:8080/api/v1/x`. |
| `test_resolver_callback_invokes_registered_fn` | 3 | A registered callback is awaited; its return becomes `raw_value`. |
| `test_resolver_callback_missing_returns_error` | 3 | Unknown `callback_ref` → `RestFieldResult(success=False, error=...)` (no raise). |
| `test_resolver_jsonpath_extraction` | 3 | `response_path="$.score"` extracts `answer=0.86` from `{"score":0.86,...}`. |
| `test_resolver_jsonpath_miss_appends_warning` | 3 | A non-matching path yields `answer=None` plus `"jsonpath_miss: …"` in `RestFieldResult.warnings: list[str]`. |
| `test_resolver_display_template_jinja2` | 3 | `display_template="Score: {{ answer }}"` renders `"Score: 0.86"`. |
| `test_resolver_display_template_sandbox_blocks_unsafe` | 3 | Templates using filesystem / `os` access raise — sandboxed env. |
| `test_resolver_response_schema_miss_emits_warning_not_reject` | 3 | Response-schema validation miss → `success=True` + `"response_schema_mismatch: …"` in `result.warnings`. |
| `test_resolver_timeout_returns_error_not_raise` | 3 | aiohttp timeout → `RestFieldResult(success=False, status_code=None, error="…")`. |
| `test_blob_storage_s3_put_returns_ref` | 1 | Mocked aioboto3 client receives put_object with expected key. |
| `test_blob_storage_s3_delete_idempotent` | 1 | Deleting an absent key does not raise. |
| `test_blob_storage_pre_persist_hook_noop` | 1 | Default `pre_persist_hook` is a no-op coroutine. |
| `test_blob_storage_pre_persist_hook_reject_aborts_put` | 1 | A hook raising `BlobRejectedError` aborts the put. |
| `test_callback_registry_register_decorator` | 2 | `@register_form_callback("x")` inserts into the registry. |
| `test_callback_registry_duplicate_raises` | 2 | Re-registering the same `(tenant, name)` raises `ValueError`. |
| `test_callback_registry_tenant_fallback_to_global` | 2 | `get_form_callback("x", tenant="acme")` falls back to global `("x", None)` when no tenant-specific entry. |
| `test_callback_registry_list_for_tenant` | 2 | `list_form_callbacks(tenant="acme")` returns tenant + global entries. |
| `test_renderer_html5_native` | 8 | HTML output contains an `<input type="file">` plus hidden `answer`/`blob_ref` inputs. |
| `test_renderer_jsonschema_native` | 8 | JSON Schema contains `"x-parrot-rest"` extension with `mode`/`endpoint`/`response_path`. |
| `test_renderer_pdf_fallback_emits_warning` | 8 | PDF render produces a placeholder + `RenderWarning(field_type="rest", renderer="pdf")`. |
| `test_renderer_telegram_webapp` | 8 | Telegram renderer emits a WebApp redirect entry. |
| `test_extractor_yaml_rest_roundtrip` | 9 | YAML key `rest` ↔ `FieldType.REST` with `meta.rest` preserved. |
| `test_extractor_jsonschema_rest_roundtrip` | 9 | JSON Schema with `x-parrot-rest` extracts to a `FormField` with `meta.rest`. |
| `test_pyproject_has_jsonpath_ng_aioboto3` | 10 | Parsed `pyproject.toml` contains both dependencies with required minimums. |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_upload_remote_mode_planogram_mock` | aiohttp test server accepts POST, returns JSON `{"score": 0.86}`. Full pipeline returns `answer=0.86`, persists blob in a mocked S3, emits no warnings. |
| `test_e2e_upload_internal_mode_cascades_bearer` | Inbound `Authorization: Bearer X` cascades into the internal call; the internal endpoint asserts the header. |
| `test_e2e_upload_callback_mode_invokes_registered_fn` | A `@register_form_callback("planogram")` coroutine is awaited; its return becomes the answer. |
| `test_e2e_upload_callback_tenant_isolation` | A tenant-scoped callback wins over a global one for the same `name`. |
| `test_e2e_upload_reupload_deletes_previous_blob` | Second upload triggers synchronous delete of the first `blob_ref`. |
| `test_e2e_upload_mime_rejected_returns_415` | Disallowed MIME → 415 + no resolver call + no blob written. |
| `test_e2e_upload_too_large_returns_413` | Multipart > `max_file_size_bytes` → 413. |
| `test_e2e_submit_rejects_in_progress` | A submission with `status="in_progress"` is rejected by `submit_data` with 400 `{field_id, status: "in_progress"}`. |
| `test_e2e_form_submit_persists_answer_and_blob_ref` | After upload + submit, `FormSubmission.data[field_id] == {"answer":…, "blob_ref":…}` is in storage. |
| `test_e2e_jsonschema_doc_gen_includes_rest` | `gen_frontend_docs.py` emits `docs/frontend/rest-field.md` mentioning `FieldType.REST` and all three modes. |
| `test_e2e_backwards_compat_existing_forms` | All FEAT-167 fixtures render unchanged. No new `warnings`. |
| `test_e2e_concurrent_uploads_last_write_wins` | Two near-simultaneous uploads on the same `(form_id, field_id)` end with the *later* `blob_ref` (no lock). |

### Test Data / Fixtures

```python
# tests/fixtures/rest_field/
@pytest.fixture
def rest_callback_field() -> FormField:
    return FormField(
        field_id="planogram_photo",
        field_type=FieldType.REST,
        label="Subir foto para planogram compliance",
        required=True,
        constraints=FieldConstraints(
            allowed_mime_types=["image/jpeg", "image/png"],
            max_file_size_bytes=10 * 1024 * 1024,  # 10 MiB
        ),
        meta={
            "rest": {
                "mode": "callback",
                "callback_ref": "planogram_compliance",
                "response_path": "$.compliance_score",
                "display_template": "Compliance: {{ (answer * 100) | round }}/100",
                "persist_binary": True,
            }
        },
    )

@pytest.fixture
def rest_remote_field() -> FormField:
    return FormField(
        field_id="analyse_image",
        field_type=FieldType.REST,
        label="Analyse image",
        meta={
            "rest": {
                "mode": "remote",
                "endpoint": "https://api.vendor.test/analyse",
                "http_method": "POST",
                "auth_ref": "VENDOR_TOKEN",
                "response_path": "$.result",
            }
        },
    )

@pytest.fixture
def rest_internal_field() -> FormField:
    return FormField(
        field_id="nn_photo",
        field_type=FieldType.REST,
        label="Networkninja",
        meta={
            "rest": {
                "mode": "internal",
                "endpoint": "/api/v1/networkninja/photo-analyze",
                "http_method": "POST",
            }
        },
    )

@pytest.fixture
def mock_blob_storage(monkeypatch):
    """In-memory AbstractBlobStorage for tests."""
    ...

@pytest.fixture
async def aiohttp_planogram_server(aiohttp_server):
    """Mock vendor REST endpoint returning {'compliance_score': 0.86}."""
    ...
```

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/ -v`.
- [ ] All integration tests pass: `pytest packages/parrot-formdesigner/tests/integration/ -v`.
- [ ] `ruff check packages/parrot-formdesigner/` passes with zero warnings.
- [ ] `mypy packages/parrot-formdesigner/src/` passes with zero errors (strict where already configured).
- [ ] `FieldType.REST = "rest"` is present in `core/types.py` and registered in `controls/builtin._BUILTIN_METADATA` with `category="advanced"`.
- [ ] `RestFieldSpec` is a Pydantic v2 discriminated union with three concrete shapes (`remote` / `internal` / `callback`), each `extra="forbid"`.
- [ ] `services/rest_field_resolver.RestFieldResolver.resolve()` dispatches by `mode` and **never raises** — all errors are captured in `RestFieldResult`.
- [ ] `services/blob_storage.AbstractBlobStorage` is async, exposes `put` / `get` / `delete` / `pre_persist_hook`, and has a concrete `S3BlobStorage` default using `aioboto3` (no `boto3`, no `requests`).
- [ ] `AbstractBlobStorage.pre_persist_hook` is exposed as a hook in V1; default impl is a no-op coroutine.
- [ ] `services/callback_registry` exposes `@register_form_callback(name, *, tenant=None)` and `get_form_callback(name, *, tenant=None)`; tenant-scoped with fallback to global (`tenant=None`).
- [ ] Duplicate `(tenant, name)` registration raises `ValueError` — registrations cannot be silently overridden.
- [ ] Internal-mode `endpoint` must start with `/` (enforced by `field_validator`); the resolver prepends `internal_base_url` resolved in order: constructor arg → `PARROT_INTERNAL_BASE_URL` env var → `request.host` fallback (request-bound only) → `ConfigurationError`. Resolved host must pass the `PARROT_INTERNAL_ALLOWED_HOSTS` (or be loopback).
- [ ] Re-upload deletes the previous `blob_ref` synchronously (guaranteed cleanup); a regression test asserts this.
- [ ] `response_path` extraction uses `jsonpath-ng`; a miss yields `answer=None` plus a `"jsonpath_miss: …"` string in `RestFieldResult.warnings` (no raise).
- [ ] `display_template` is rendered via Jinja2's `SandboxedEnvironment`; templates accessing `os`/filesystem raise at render time.
- [ ] `response_schema` validation miss appends an informational warning string to `RestFieldResult.warnings` (convention `"response_schema_mismatch: <detail>"`) AND calls `logger.warning(...)`; does not hard-reject. Warning is propagated to the upload response envelope under `"warnings"`.
- [ ] `POST /api/v1/forms/{form_id}/fields/{field_id}/upload` is mounted by `setup_form_api()` and wrapped by `is_authenticated + user_session`.
- [ ] The validator branch rejects submissions whose REST field carries `status == "in_progress"` with `400 {field_id, status: "in_progress"}`.
- [ ] MIME / size checks reuse `FieldConstraints.allowed_mime_types` and `max_file_size_bytes` (no new constraint fields).
- [ ] `FormSubmission.data[field_id] == {"answer": ..., "blob_ref": "..."}` after submit (or `blob_ref=None` if `persist_binary=False`).
- [ ] All 6 renderers classify `FieldType.REST` either natively (HTML5, JsonSchema) or via `FallbackRenderer` (PDF, XForms, Adaptive Card) or as a WebApp redirect (Telegram). Each fallback appends a `RenderWarning`.
- [ ] `extractors/yaml.py` and `extractors/jsonschema.py` round-trip `FieldType.REST` and preserve `meta["rest"]`.
- [ ] `pyproject.toml` lists `jsonpath-ng>=1.6.1` and `aioboto3>=12.0`.
- [ ] `packages/parrot-formdesigner/docs/frontend/rest-field.md` is generated and contains: JSON-Schema fragment, upload endpoint contract, response envelope, error codes, and a worked planogram example.
- [ ] No regression in FEAT-167 (`FieldRenderer` / `FallbackRenderer` / `RenderWarning` / FEAT-167 field types) — their existing tests pass unchanged.
- [ ] No breaking changes to public API: external callers of `setup_form_api`, `HTML5Renderer`, `JsonSchemaRenderer`, etc. work without modification.
- [ ] Backwards-compat: 5 existing FEAT-167 form fixtures load + validate + render unchanged.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.**
> All references below were re-verified on 2026-05-14 against the `dev`
> branch tip. Implementation agents MUST use these imports / signatures
> verbatim and MUST NOT invent attributes not listed.

### Verified Imports

```python
# These imports have been confirmed to resolve on dev tip:
from parrot_formdesigner.core.types import FieldType, LocalizedString
from parrot_formdesigner.core.schema import (
    FormField, FormSection, FormSchema, RenderedForm, RenderWarning,
    SubmitAction,
)
from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.core.options import FieldOption, OptionsSource
from parrot_formdesigner.services.auth_context import AuthContext
from parrot_formdesigner.services.remote_response_resolver import (
    RemoteResponseResolver, RemoteResponseResult, RemoteResponseSpec,
)
from parrot_formdesigner.services.forwarder import (
    SubmissionForwarder, ForwardResult,
)
from parrot_formdesigner.services.submissions import (
    FormSubmission, FormSubmissionStorage,
)
from parrot_formdesigner.controls.registry import (
    register_field_control, FieldControlMetadata,
)
from parrot_formdesigner.renderers.base import (
    AbstractFormRenderer, FieldRenderer, FallbackRenderer,
)
from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.api.handlers import FormAPIHandler
# Reference idiom only — do NOT import in implementation modules:
# from parrot.registry import register_agent  # decorator-registry pattern
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py:16
class FieldType(str, Enum):
    TEXT = "text"            # line 19
    # ... 28 existing values through line 49 (FEAT-167) ...
    RANKING = "ranking"      # line 49
    # NEW (this feature): REST = "rest"

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:23
class FormField(BaseModel):
    model_config = ConfigDict(extra="forbid")              # line 47
    field_id: str                                          # line 49
    field_type: FieldType                                  # line 50
    label: LocalizedString                                 # line 51
    description: LocalizedString | None = None             # line 52
    placeholder: LocalizedString | None = None             # line 53
    required: bool = False                                 # line 54 (approx)
    default: Any = None
    read_only: bool = False
    constraints: FieldConstraints | None = None
    options: list[FieldOption] | None = None
    options_source: OptionsSource | None = None
    depends_on: DependencyRule | None = None
    children: list[FormField] | None = None
    item_template: FormField | None = None
    meta: dict[str, Any] | None = None                     # line 63
# Note: `meta["rest"]` is where RestFieldSpec.model_dump() lives. No
# new fields on FormField itself.

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:194-207
class RenderWarning(BaseModel):
    field_id: str                                          # line 201
    field_type: str                                        # line 202
    renderer: str
    reason: str

class RenderedForm(BaseModel):
    content: Any
    content_type: str
    style_output: Any | None = None
    metadata: dict[str, Any] | None = None
    warnings: list[RenderWarning] = []                     # FEAT-167

# packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py:17
class FieldConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")              # line 35
    allowed_mime_types: list[str] | None = None            # line 46
    max_file_size_bytes: int | None                        # line 47
    # ... (existing fields) ...
    # FEAT-167 additions (scale_min, scale_max, scale_step, anchor_labels)

# packages/parrot-formdesigner/src/parrot_formdesigner/services/auth_context.py:20
class AuthContext(BaseModel):
    model_config = ConfigDict(extra="forbid")              # line 37
    scheme: Literal["none", "bearer", "api_key", "custom"] # line 39
    token: str | None = None                               # line 40
    headers: dict[str, str] = {}                           # line 41
    claims: dict[str, Any] = {}                            # line 42
    def resolve_for(self, auth_ref: str | None) -> dict[str, str]: ...  # line 44

# packages/parrot-formdesigner/src/parrot_formdesigner/services/remote_response_resolver.py:24
class RemoteResponseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")              # line 39
    endpoint: str                                          # line 41
    http_method: Literal["GET", "POST"] = "POST"           # line 42
    content_field: str | None = None
    prompt: str | None = None
    auth_ref: str | None = None
    timeout_seconds: int = 30
    response_schema: dict[str, Any] | None = None
# REFERENCE shape for RestFieldSpec — do NOT subclass. RestFieldSpec is a
# discriminated union, RemoteResponseSpec is a flat BaseModel.

# packages/parrot-formdesigner/src/parrot_formdesigner/services/remote_response_resolver.py:66
class RemoteResponseResolver:
    DEFAULT_TIMEOUT: int = 30                              # line 81
    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None: ...  # line 83
    async def resolve(
        self,
        spec: RemoteResponseSpec,
        content: Any,
        *,
        auth_context: AuthContext | None = None,
    ) -> RemoteResponseResult: ...                         # line 92
# Aiohttp + ClientTimeout + try/except pattern to MIRROR in RestFieldResolver.

# packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:35
class FormSubmission(BaseModel):
    submission_id: str = Field(default_factory=...)        # line 54
    form_id: str                                           # line 58
    form_version: str | None = None
    data: dict[str, Any]                                   # line 60
    is_valid: bool
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime = Field(default_factory=...)
    tenant: str | None = None                              # line 68

# packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:71
class FormSubmissionStorage:
    async def store(
        self,
        submission: FormSubmission,
        *,
        tenant: str | None = None,
    ) -> str: ...                                          # line 177

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:33
class FormAPIHandler:
    def __init__(
        self,
        registry: FormRegistry,
        client: "AbstractClient | None" = None,
        submission_storage: "FormSubmissionStorage | None" = None,
        forwarder: "SubmissionForwarder | None" = None,
    ) -> None: ...                                         # line 51
    def _get_org_id(self, request: web.Request) -> int | None: ...      # line 100
    def _get_programs(self, request: web.Request) -> list[str]: ...     # line 128
    def _build_auth_context(self, request: web.Request) -> AuthContext: ...  # line 149
    async def submit_data(self, request: web.Request) -> web.Response: ...   # line 508

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py:70
def setup_form_api(
    app: web.Application,
    registry: FormRegistry,
    *,
    client: "AbstractClient | None" = None,
    submission_storage: "FormSubmissionStorage | None" = None,
    forwarder: "SubmissionForwarder | None" = None,
    base_path: str = "/api/v1",
) -> None: ...
# This signature MUST be extended (Module 12) with kwargs:
#   blob_storage: AbstractBlobStorage | None = None
#   resolver: RestFieldResolver | None = None

# packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py:67
_REGISTRY: dict[str, FieldControlMetadata] = {}
def register_field_control(
    field_type: FieldType | str,
    *,
    label: str,
    description: str,
    category: str,           # "basic" | "selection" | "media" | "layout" | "advanced"
    icon: str,
    snippet: dict[str, Any],
    render_hint: str,
    supports_constraints: bool,
    is_container: bool = False,
) -> None: ...                                              # line 70
# Idempotent — re-registration overwrites with a warning (lines 99-103).

# packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py:26
_BUILTIN_METADATA: dict[FieldType, dict[str, Any]] = {
    # 30 existing entries (FEAT-167 closed gaps).
    # NEW (this feature): FieldType.REST: {...}
}
def _seed() -> None: ...                                    # line 301
# Side-effect call on import (line 322).

# packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py:236
def get_form_field_schema_snippets() -> dict[str, dict[str, Any]]: ...
# _FIELD_SCHEMA_SNIPPETS dict at module level — append FieldType.REST.value.

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py
class FieldRenderer(Protocol): ...
class FallbackRenderer: ...
# FEAT-167 primitives reused for the new type.

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py:15
import jinja2
# Jinja2 already a dependency — reuse for display_template via
# SandboxedEnvironment (DO NOT use the existing Environment with autoescape=True;
# create a separate SandboxedEnvironment in services/rest_field_resolver.py).
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `RestFieldResolver` | `AuthContext.resolve_for(auth_ref)` | header lookup | `services/auth_context.py:44` |
| `RestFieldResolver` | aiohttp `ClientSession` + `ClientTimeout` | mirror of `services/remote_response_resolver.py:122-145` |
| `handle_rest_upload` | `FormAPIHandler._build_auth_context` | kwarg passed in | `api/handlers.py:149` |
| `handle_rest_upload` | `setup_form_api` | route mounted in `app.router.add_post(...)` | `api/routes.py:70-156` |
| `handle_rest_upload` | `FormRegistry` | `app["form_registry"]` lookup | `api/routes.py:94` |
| `handle_rest_upload` | `AbstractBlobStorage` | `app["blob_storage"]` lookup | new (Module 12) |
| `handle_rest_upload` | `RestFieldResolver` | `app["rest_resolver"]` lookup | new (Module 12) |
| `register_form_callback` | none — module-level registry | decorator | new (Module 2) |
| `_BUILTIN_METADATA[FieldType.REST]` | `register_field_control` | seeded by `_seed()` | `controls/builtin.py:301-318` |
| `FieldType.REST` validator branch | `FormValidator.validate_field` | branch | `services/validators.py:340+` (FEAT-167 added the dispatch ladder) |
| `S3BlobStorage` | `aioboto3.Session().client("s3")` | async context manager | new (Module 1) |
| `display_template` | `jinja2.sandbox.SandboxedEnvironment` | template render | reuse `jinja2` (already pinned `>=3.1`) |
| `response_path` | `jsonpath_ng.parse` | JSONPath evaluation | new dep |

### Does NOT Exist (Anti-Hallucination)

- ~~`FieldType.REST`~~ — does **not exist** today. This feature introduces it.
- ~~`parrot_formdesigner.services.rest_field_resolver`~~ — does **not exist**.
- ~~`parrot_formdesigner.services.blob_storage` / `AbstractBlobStorage` / `S3BlobStorage` / `BlobMetadata` / `PrePersistContext` / `BlobRejectedError`~~ — do **not exist**.
- ~~`parrot_formdesigner.services.callback_registry` / `@register_form_callback` / `get_form_callback` / `list_form_callbacks`~~ — do **not exist**.
- ~~`parrot_formdesigner.api.uploads` / `handle_rest_upload`~~ — does **not exist**.
- ~~`POST /api/v1/forms/{form_id}/fields/{field_id}/upload`~~ — the route does **not exist** today.
- ~~`setup_form_api(..., blob_storage=..., resolver=...)`~~ — these kwargs do **not exist** today. Module 12 adds them.
- ~~`app["blob_storage"]` / `app["rest_resolver"]`~~ — these keys are **not** set today.
- ~~`jsonpath-ng`~~ — **not** in `packages/parrot-formdesigner/pyproject.toml` (verified — only `pydantic`, `aiohttp`, `asyncdb`, `PyYAML`, `jinja2`, `aiogram`, `navigator-auth`, `lxml`, `reportlab`, `pycountry`). Adding it is part of Module 10.
- ~~`aioboto3` / `boto3` / `botocore`~~ — **not** in either workspace or formdesigner `pyproject.toml`. Adding `aioboto3` is part of Module 10.
- ~~Subclassing `RemoteResponseResolver` or `SubmissionForwarder`~~ — forbidden. Mirror the pattern, do not extend.
- ~~Subclassing `RemoteResponseSpec`~~ — `RestFieldSpec` is an independent discriminated union, not a child of `RemoteResponseSpec`.
- ~~Chunked / resumable uploads (tus, resumable.js)~~ — explicitly out of scope.
- ~~Dotted-path callback resolution (`callback: "myapp.callbacks.fn"`)~~ — rejected. Callbacks must be pre-registered.
- ~~`FormField.rest_spec` / `FormField.callback_ref` / `FormField.endpoint` etc. as **top-level** attributes on `FormField`~~ — do **not exist**. The spec lives entirely under `meta["rest"]`.
- ~~`OptionsSource.callback_ref`~~ — does **not exist**. `RestFieldSpec` is the carrier, not `OptionsSource`.
- ~~`AuthContext.cascade_into(field)` or similar explicit cascade method~~ — does **not exist**. Cascade is implicit by passing the same `AuthContext` kwarg into nested renderers.
- ~~Per-field blob retention policy (`meta.rest.retention_days`)~~ — out of scope for V1; S3 bucket lifecycle handles it globally.
- ~~Per-field concurrent-upload locks~~ — out of scope; V1 is last-write-wins.
- ~~Full AV/content-scanning pipeline~~ — out of scope. The `pre_persist_hook` interface exists in V1 as a stub; V2 wires the real scanner.
- ~~Frontend `<RestUploader>` component code in this repo~~ — frontend lives in a separate repo. This spec ships only the auto-generated docs that the frontend consumes.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Async everywhere.** `RestFieldResolver.resolve()`, every
  `AbstractBlobStorage.put`/`get`/`delete`, the upload handler, and the
  per-renderer registry callable for `FieldType.REST` are all `async def`.
  No `requests` / `httpx` / blocking I/O.
- **Pydantic v2 + `ConfigDict(extra="forbid")`** for every new model.
  `RestFieldSpec` uses `Annotated[..., Field(discriminator="mode")]` —
  this is the V2 idiom for discriminated unions.
- **Logging via `self.logger`** instead of `print`. Each service
  initialises `self.logger = logging.getLogger(__name__)` in `__init__`.
- **Aiohttp pattern is `RemoteResponseResolver`** (Phase 3 of FEAT-167,
  `services/remote_response_resolver.py:66-177`). Reuse the
  `ClientSession + ClientTimeout(total=...)` + `try/except` skeleton.
- **Internal-mode URL composition (NEW pattern in FEAT-170, no
  FEAT-167 precedent).** `endpoint` MUST start with `/` (validated).
  At resolve time, `internal_base_url` is prepended. Resolution order:
  1. Explicit `RestFieldResolver(internal_base_url=...)` constructor
     argument (test / DI override).
  2. `PARROT_INTERNAL_BASE_URL` env var — **primary** in production.
     Bootstrap MUST log the resolved value at startup.
  3. Last-resort fallback: `request.url.scheme + "://" + request.host`
     extracted at handler time and threaded in. Only available when the
     resolver is invoked from a request-bound code path; background
     tasks / scheduled callbacks MUST set the env var or pass the
     constructor argument.
  4. If none of the above yield a value, raise `ConfigurationError`
     on the *first* internal-mode invocation (fail fast, not silent).
  - **SSRF guardrail**: the resolved host MUST match one of:
    `localhost`, `127.0.0.1`, or a value in
    `PARROT_INTERNAL_ALLOWED_HOSTS` (comma-separated). Any other host
    rejects with `RestFieldResult(success=False, error="...")`.
- **Tenant-scoped callback registry (NEW pattern in FEAT-170).** No
  existing registry in `parrot-formdesigner` uses composite tenant
  keys; `controls/registry.py` and `services/registry.py` are
  name-only. The motivation here is **namespace shadowing** (not
  isolation): tenants can override a globally-registered callback
  name with a tenant-specific implementation. Concretely:
  - Key: `(tenant_slug_or_None, name)` where `None` is a sentinel
    (the literal Python `None`), NOT the string `"None"`. A tenant
    whose slug is literally `"None"` MUST be detected at registration
    time and rejected with `ValueError`.
  - Lookup order: `(tenant, name)` → `(None, name)` → `KeyError`.
  - Tenant slug is derived from
    `FormAPIHandler._get_programs(request)[0]` when available;
    resolvers receive `tenant` as an explicit kwarg.
  - The registry resolves *which implementation* a tenant gets; it is
    NOT an authorization layer. Per-tenant ACLs ("can this user
    invoke `compute_compliance`?") live at the handler/resolver
    boundary, not inside the registry.
- **Jinja2 `SandboxedEnvironment`** for `display_template`. Do NOT reuse
  the renderer-side `Environment(autoescape=True)` — that env trusts the
  template author and is not sandboxed.
- **Resolver/handler warnings are `list[str]` on `RestFieldResult`,
  NOT `RenderWarning`.** `RenderWarning` (defined by FEAT-167 in
  `core/schema.py`) carries a `renderer: "html5"|"pdf"|...` field and
  is meant for *renderer-side* fallbacks (PDF placeholder, Adaptive
  Card not-supported, etc.). The resolver and upload handler are a
  different layer; warnings here are *informational* strings echoed
  back to the client in the upload envelope under `"warnings"`. They
  MUST also be emitted via `self.logger.warning(...)` for ops
  visibility — both channels, not either/or. A future V2 may upgrade
  this to a structured `RestFieldWarning` model if richer client-side
  handling is needed; V1 stays simple.
  - Convention: `"<code>: <detail>"`, e.g.
    `"jsonpath_miss: $.compliance_score"`,
    `"response_schema_mismatch: missing 'violations'"`,
    `"blob_cleanup_failed: prior blob_ref=s3://… (NoSuchKey)"`.
- **JSONPath errors are warnings, not failures.** `jsonpath-ng`'s
  `parse(...).find(payload)` returns an empty list on miss; that path
  produces `answer=None` and appends
  `"jsonpath_miss: <expression>"` to `result.warnings`.
- **`response_schema` is informational.** When provided and validation
  fails (e.g. with `jsonschema.validate`), append a `"response_schema_
  mismatch: <error>"` warning; do NOT reject the response. Matches
  `REMOTE_RESPONSE` policy at `services/validators.py:556` (which uses
  `logger.warning()` for the equivalent miss).
- **Re-upload deletes the previous blob synchronously.** The handler
  reads the prior `blob_ref` from the in-progress submission state
  (or from a header echoed by the frontend) and calls
  `blob_storage.delete(prior_ref)` *after* the new blob is durably
  written but *before* the new envelope is returned. Failure to delete
  appends a `"blob_cleanup_failed: …"` warning to `result.warnings`
  but does NOT fail the request.
- **No `requests` / `httpx` / `urllib`** — `aiohttp` only, per project
  rules.
- **No new constraint fields on `FieldConstraints`** — MIME / size
  validation reuses `allowed_mime_types` and `max_file_size_bytes`
  (existing).
- **No subclassing of `RemoteResponseResolver` or
  `SubmissionForwarder`** — they are reference patterns, not base
  classes for this work.
- **No dotted-path callback resolution** — the registry is closed.

### Renderer Coverage & Fallback Policy

| FieldType | JSON Schema | HTML5 | Adaptive Card | PDF | XForms | Telegram |
|---|---|---|---|---|---|---|
| `REST` | ✓ native (`x-parrot-rest` extension) | ✓ native (multipart uploader) | fallback (placeholder + warning) | fallback (empty box + warning) | fallback (input + help note) | WebApp redirect |

Each fallback MUST append a `RenderWarning(field_id, field_type="rest",
renderer=<name>, reason=<human-readable>)`.

### Data Shapes for `FieldType.REST` (validator/storage)

| Stage | Shape |
|---|---|
| Upload request body | `multipart/form-data` with at least one binary part (or one text part) |
| Upload response | `{"success": bool, "answer": Any \| null, "raw_value": Any \| null, "blob_ref": str \| null, "display": str \| null, "warnings": [...], "error": str \| null}` |
| Form submission `data[field_id]` (valid) | `{"answer": Any, "blob_ref": str \| null}` |
| Form submission `data[field_id]` (in-flight) | `{"answer": null, "blob_ref": null, "status": "in_progress"}` → REJECTED by validator |
| Stored in `FormSubmission.data` | `{"answer": Any, "blob_ref": str \| null}` (the `status` field is stripped) |

### Known Risks / Gotchas

- **Discriminated-union complexity.** `RestFieldSpec` has three concrete
  shapes with mode-conditional required fields. Mitigation: a strong
  `field_validator` per concrete model (e.g.
  `InternalRestFieldSpec.endpoint` must start with `/`), plus per-mode
  parse tests.
- **Multipart parsing pitfalls.** Aiohttp's
  `request.multipart()` is streaming; large videos exceeding RAM if
  buffered entirely. Mitigation: pass an `AsyncIterator[bytes]` chain
  directly to `AbstractBlobStorage.put` — do NOT buffer the whole blob.
  Apply the `max_file_size_bytes` check *while* streaming (track bytes
  read; abort on overflow).
- **Re-upload delete failure.** If the new blob writes successfully but
  the prior delete fails (S3 transient error), we keep the new blob and
  append `"blob_cleanup_failed: …"` to `RestFieldResult.warnings`
  (string, not `RenderWarning` — see §7 Patterns). The orphan blob is
  reaped by bucket lifecycle policy.
- **Internal-mode loopback over HTTP.** Calling `/api/v1/...` from
  inside the same aiohttp app round-trips over HTTP (not in-process).
  Acceptable for V1 — clearer semantics + uniform middleware. A future
  optimisation can short-circuit via the aiohttp router.
- **Jinja2 sandbox false negatives.** `SandboxedEnvironment` blocks
  obvious attribute access (`__class__`, `os.system`) but does not stop
  all info disclosure (e.g. very long-running templates).
  `display_template` rendering is bounded by a per-render timeout
  (`JINJA2_DISPLAY_TIMEOUT_SECONDS=2`) — implemented via a watchdog or
  by capping `max_string_length`. Document this in the frontend doc.
- **Concurrent uploads (last-write-wins).** Without locks, two near-
  simultaneous uploads on the same `(form_id, field_id)` produce two
  blobs; the later answer overwrites in the submission payload. The
  orphan blob from the earlier upload is best-effort deleted on the
  second upload's "delete prior `blob_ref`" step (if the frontend
  echoes it). If not echoed, it's reaped by S3 lifecycle.
- **Tenant scoping ambiguity in callback registry.** Two callbacks with
  the same `name` (one global, one tenant-scoped) — the tenant-scoped
  one wins for that tenant. Document this prominently in the registry
  module's docstring; misuse otherwise produces silent surprise.
- **FEAT-167 surfaces touched.** This feature **only consumes** FEAT-167
  primitives (`FieldRenderer`, `FallbackRenderer`, `RenderWarning`,
  `AuthContext`). It does not modify them. Verified at task-decomposition
  time.
- **No breaking changes to `setup_form_api`.** New kwargs are optional
  with sensible defaults — external consumers do not need to change
  their bootstrap code.
- **`pre_persist_hook` discoverability.** Even though the V1 default is
  a no-op, the hook is part of the public API. The Frontend doc and the
  module docstring must clearly mark it as **stable contract** so V2
  AV integrators don't reinvent the surface.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `jsonpath-ng` | `>=1.6.1` | JSONPath response-extraction (`response_path`). |
| `aioboto3` | `>=12.0` | Async S3 client for default `S3BlobStorage`. |
| `aiohttp` | already pinned | HTTP client + upload route. `>=3.9`. |
| `pydantic` | already pinned | Discriminated unions. `>=2.0`. |
| `jinja2` | already pinned | `display_template` rendering via `SandboxedEnvironment`. `>=3.1`. |
| `navigator-auth` | already pinned | Inbound auth middleware (FEAT-152). |
| `jsonschema` | `>=4.0` (test) | `response_schema` informational validation. Already in the formdesigner `test` extra. |

No other new dependencies.

---

## 8. Open Questions

> All 9 questions from the brainstorm are resolved. Listed here as `[x]`
> with the resolved answer for audit trail. Implementation agents must
> treat these as binding decisions.

- [x] `controls/builtin.py` category for `FieldType.REST` —
  *Resolved in brainstorm*: `"advanced"`. The live API call places
  this in the same conceptual bucket as `REMOTE_RESPONSE`
  (also `"advanced"`).
- [x] Internal-mode URL composition —
  *Resolved (refined at spec-validation 2026-05-14)*: strict path
  (must start with `/`). **No FEAT-167 precedent for internal vs
  external dispatch** — this is a new pattern in FEAT-170. Resolution
  order for `internal_base_url`: **(1)** constructor argument,
  **(2) `PARROT_INTERNAL_BASE_URL` env var (PRIMARY in production)**,
  **(3) `request.host` fallback only when request-bound**,
  **(4) fail-fast with `ConfigurationError`** if none. SSRF guard:
  resolved host must be `localhost`/`127.0.0.1` or in
  `PARROT_INTERNAL_ALLOWED_HOSTS`. See §7 *Patterns to Follow*.
- [x] Callback registry scoping —
  *Resolved (refined at spec-validation 2026-05-14)*: **tenant-scoped
  with namespace-shadowing semantics**. Key is `(tenant_slug_or_None,
  name)` where `None` is the literal Python sentinel (a tenant slug
  equal to the string `"None"` is rejected at registration). Lookup
  falls back from `(tenant, name)` → `(None, name)` → `KeyError`.
  **This is a new pattern** in `parrot-formdesigner` — no existing
  registry uses composite tenant keys; `controls/registry.py:67` and
  `services/registry.py` are name-only. The motivation is **per-tenant
  override**, not isolation (an ACL would not provide override
  semantics). Authorisation (who-may-invoke) is NOT part of the
  registry — it lives at the handler/resolver boundary.
- [x] Blob deletion on re-upload —
  *Resolved (refined at spec-validation 2026-05-14)*: synchronous
  delete of the previous `blob_ref` after the new blob is durably
  written. Failure appends `"blob_cleanup_failed: <detail>"` to
  `RestFieldResult.warnings` (string, not `RenderWarning` — see Q5
  refinement above) and does not fail the request.
- [x] `response_schema` validation miss —
  *Resolved (refined at spec-validation 2026-05-14)*: informational
  only — do **not** hard-reject. Implementation: append a string
  warning (convention: `"response_schema_mismatch: <detail>"`) to
  `RestFieldResult.warnings: list[str]` AND call
  `self.logger.warning(...)`. **Do NOT use the FEAT-167 `RenderWarning`
  model** — that class is renderer-scoped (its `renderer` field is
  `"html5"|"pdf"|"adaptive_card"|...`, not `"resolver"`). The earlier
  brainstorm wording conflated two distinct layers; this resolution
  fixes it. The string-list shape mirrors how `validators.py:556`
  handles the equivalent miss for `REMOTE_RESPONSE` (logger.warning
  + no rejection); the new piece is propagating the warning into the
  HTTP response envelope so the frontend can surface it.
- [x] Concurrent uploads on the same `(form_id, field_id)` —
  *Resolved in brainstorm*: **last-write-wins**, no per-field lock in
  V1.
- [x] `display_template` syntax —
  *Resolved in brainstorm*: full **Jinja2** (already a dep). Rendered
  with `SandboxedEnvironment` and a per-render timeout.
- [x] AV/content-scanning hook —
  *Resolved in brainstorm*: ship a **stub interface** in V1 (the
  `pre_persist_hook` on `AbstractBlobStorage`, no-op by default). Full
  AV pipeline is deferred to V2.
- [x] Frontend coordination —
  *Resolved in brainstorm*: same approach as FEAT-167 (frontend lives
  in a separate repo, UI work is a follow-up spec). **Additional
  decision**: this spec ships an auto-generated documentation
  artefact at `packages/parrot-formdesigner/docs/frontend/rest-field.md`
  describing the contract so the frontend repo can implement against
  it without re-deriving from JSON Schema.

No unresolved questions remain at spec-time. Should any open question
emerge during `/sdd-task` decomposition or implementation, it must be
added below with an owner and answered before the task it blocks can
proceed.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`. All 13 modules run sequentially
  in one feature worktree at
  `.claude/worktrees/feat-170-formdesigner-field-rest/`.
- **Rationale**: Like FEAT-167, the changes touch central files:
  the `FieldType` enum, `_BUILTIN_METADATA`, every renderer's
  `_registry` dict, `services/validators.py`, both extractors,
  `api/routes.py`, and `pyproject.toml`. Parallel worktrees would
  conflict on these files at every task boundary. The three Phase 1
  service modules (`blob_storage`, `callback_registry`,
  `rest_field_resolver`) are mutually independent and *could* be
  developed in parallel sub-worktrees once their interfaces are
  agreed — but with ~3 tasks at stake the worktree overhead outweighs
  the speedup. Recommend sequential within the same worktree unless
  the implementer prefers otherwise.
- **Cross-feature dependencies**: None. FEAT-167 (FieldRenderer registry,
  AuthContext, RemoteResponseResolver, RenderWarning) is merged on
  `dev`. No other in-flight spec touches `packages/parrot-formdesigner/`
  (verified against `sdd/specs/` index on 2026-05-14).
- **Base branch**: `dev` (this is a `feature`, not a `hotfix`).
- **Worktree creation** (run from the main repo working tree on `dev`):
  ```bash
  git worktree add -b feat-170-formdesigner-field-rest \
    .claude/worktrees/feat-170-formdesigner-field-rest HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-14 | jesuslara | Initial draft from `new-formdesigner-field-rest.brainstorm.md` (Option A). All 9 brainstorm open questions resolved and carried forward. |
| 0.2 | 2026-05-14 | jesuslara | Spec-validation pass against codebase. Refinements: (Q2) Internal-mode URL composition explicitly marked as new in FEAT-170; env-var precedence reversed (`PARROT_INTERNAL_BASE_URL` primary, `request.host` fallback only when request-bound); fail-fast `ConfigurationError` + SSRF allow-list `PARROT_INTERNAL_ALLOWED_HOSTS`. (Q3) Callback registry marked as new pattern; motivation reframed as namespace-shadowing (not isolation); `None` sentinel rule and ACL-vs-registry boundary clarified. (Q5) `RestFieldResult.warnings` retyped to `list[str]` (with `"code: detail"` convention) — `RenderWarning` reuse rejected as a layer leak (its `renderer` field is renderer-scoped); warnings emitted both via `logger.warning(...)` AND propagated into the upload-response envelope. |
