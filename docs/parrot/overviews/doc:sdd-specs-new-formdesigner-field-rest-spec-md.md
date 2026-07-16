---
type: Wiki Overview
title: 'Feature Specification: FormDesigner — `FieldType.REST` (REST-driven upload
  field with response-derived answer)'
id: doc:sdd-specs-new-formdesigner-field-rest-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Form designers currently have **no way to express a field whose value is
  the
relates_to:
- concept: mod:parrot.registry
  rel: mentions
---

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

…(truncated)…
