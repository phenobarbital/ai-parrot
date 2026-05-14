---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: FormDesigner — `FieldType.REST` (REST-driven upload field with response-derived answer)

**Date**: 2026-05-14
**Author**: jesuslara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

Form designers currently have **no way to express a field whose value is the
processed response of an external operation that consumes user-supplied
content**. The closest existing primitive is `FieldType.REMOTE_RESPONSE`
(FEAT-167 Phase 3, `services/remote_response_resolver.py:66`) but it is
**read-only, display-oriented**: it fetches data from the server and shows
it. It does not accept user input, cannot upload binary content, and has
no mechanism to invoke local Python code.

The motivating use case is *"Subir foto para planogram compliance"*: the
user uploads a shelf photo from the form, the photo is forwarded to a
planogram-compliance REST API which returns a JSON judgement (e.g.,
`{"compliance_score": 0.86, "violations": [...]}`), and the *processed
score* becomes the answer to that question in the form submission. The
binary photo is also persisted alongside the submission for audit.

The new field type must support three destinations for the upload:

1. **Remote REST API** (absolute URL, configurable auth via `AuthContext`).
2. **Internal endpoint** (relative URL like `/api/v1/networkninja/photo-analyze`,
   reusing the inbound `AuthContext` Bearer cascade — see
   `api/handlers.py:149`).
3. **In-process callback** (Python coroutine registered via decorator;
   parrot-formdesigner exposes a paramétric aiohttp route
   `/api/v1/forms/{form_id}/{session_id}/{field_id}/upload` that dispatches
   to the callback by name).

The API response is optionally **post-processed** via JSONPath
(e.g., `$.compliance_score`) and the extracted value becomes the field
answer. The original binary is persisted via an abstract blob-storage
backend (S3-compatible default) and referenced by the submission.

This is a peer of `REMOTE_RESPONSE` (display) and `FILE`/`IMAGE` (raw
upload), not a replacement for either. The frontend control is an
*active uploader* whose semantic is "submit content → receive computed
answer".

---

## Constraints & Requirements

- **Async-first**: `aiohttp` only — no `requests` / `httpx` per project rules.
- **Pydantic v2** for all new models with `ConfigDict(extra="forbid")`.
- **Reuse `AuthContext`** (`services/auth_context.py:20`) for outbound auth
  in remote/internal modes; cascade inbound Bearer to internal endpoints.
- **Reuse `controls/registry.register_field_control`** (`controls/registry.py:70`)
  for FieldType registration — same seeding pattern as `_BUILTIN_METADATA`
  in `controls/builtin.py:26`.
- **Reuse `FormSubmissionStorage`** (`services/submissions.py:71`) to persist
  the resolved answer; new `AbstractBlobStorage` for the binary side.
- **Reuse `services/forwarder.SubmissionForwarder` pattern** (NOT subclass)
  for the aiohttp + auth dance.
- **Backwards compatible**: existing forms validate and render unchanged.
- **All 6 renderers** must classify the new type (native render in
  HTML5/JsonSchema, `FallbackRenderer` where unsupported — see
  FEAT-167 coverage matrix).
- **Validation timing**: a `required` REST field whose upload is still
  in-flight when the user submits MUST reject with a structured error
  (`{field_id: "<id>", status: "in_progress"}`); the resolver state is
  authoritative.
- **Frontend security**: the upload-dispatch endpoint is wrapped by the
  same `is_authenticated + user_session` decorators in
  `api/routes.py:_wrap_auth` (no anonymous uploads).
- **Callbacks are registered, not loaded by dotted path** — the registry
  is a closed allow-list owned by the application bootstrap. No arbitrary
  import surface from form JSON.
- **Single-request upload** in V1: multipart `Content-Type` with the binary
  as a file part. No chunked / resumable uploads. Max file size policed
  via `FieldConstraints.max_file_size_bytes` (already exists,
  `core/constraints.py:47`).

---

## Options Explored

### Option A: Single `FieldType.REST` with mode-discriminated config

A new enum value `FieldType.REST` whose behaviour is parameterised by a
`RestFieldSpec` Pydantic model embedded in `FormField.meta`. The spec
uses a tagged-union discriminator (`mode: Literal["remote", "internal",
"callback"]`) to select the upload destination.

A central aiohttp route — `POST /api/v1/forms/{form_id}/fields/{field_id}/upload` —
is registered at `setup_form_api()` time. The handler:

1. Authenticates the inbound request (existing `_wrap_auth`).
2. Reads the form from the registry; resolves the `field_id` and its
   `RestFieldSpec`.
3. Reads multipart body → buffers binary + form fields.
4. Builds an `AuthContext` (existing `_build_auth_context`,
   `api/handlers.py:149`).
5. Delegates to `RestFieldResolver.resolve(spec, content, ...)` which
   dispatches by `spec.mode`:
   - `remote`: aiohttp POST/GET to `spec.endpoint` with auth headers.
   - `internal`: aiohttp call to `<self_base_url>/{spec.endpoint}` with
     the inbound Bearer cascaded as `Authorization`.
   - `callback`: `await _CALLBACK_REGISTRY[spec.callback_ref](payload, ctx)`
     (in-process; no HTTP round-trip).
6. Persists the binary via `AbstractBlobStorage.put(blob, metadata)` →
   returns `blob_ref` (e.g. `s3://bucket/forms/<form_id>/<submission_id>/<field_id>`).
7. Applies optional JSONPath extraction (`spec.response_path`).
8. Returns to the frontend: `{"answer": <extracted>, "blob_ref": "<ref>",
   "raw_value": <full_response>, "warnings": [...]}`.

The frontend stores `answer` as the value of that form field. On form
submit, only `{"answer": ..., "blob_ref": ..., "ts": ...}` travels in the
submission payload — the binary is already at rest in S3.

Three new field-level config options on `RestFieldSpec`:
- `response_path: str | None` — JSONPath (`jsonpath-ng`).
- `display_template: str | None` — Jinja-style string for the frontend
  to render the answer (e.g., `"Compliance: {answer}/100"`).
- `persist_binary: bool = True` — toggle blob persistence.

✅ **Pros:**
- One enum value, one control card in the toolbar, one validator branch.
  Aligns with FEAT-167's `REMOTE_RESPONSE` precedent.
- Discriminated union keeps each mode's config tight and self-validating
  (pydantic v2 `discriminator="mode"`).
- Central dispatch endpoint is auth-uniform and easy to instrument
  (metrics, rate-limiting, antivirus hook).
- Frontend builds one component (`<RestUploader>`); branching lives in
  schema, not in UI code.
- `AbstractBlobStorage` is reusable for any future field needing blob
  persistence (audio recordings, future video chunked).
- Callback registry is a tight allow-list — no dotted-path imports from
  form JSON.

❌ **Cons:**
- `RestFieldSpec` has ~10 optional fields total (mode-dependent); requires
  a strong field_validator to reject invalid combinations
  (e.g. `mode="callback"` with `endpoint=...`).
- One large validator branch (mode dispatch) in `services/validators.py` —
  must be carefully unit-tested per mode.
- All three modes share one upload endpoint; failures in callback mode
  surface in the same place as remote-API failures (mitigation: structured
  error payload includes `mode`).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jsonpath-ng` | JSONPath response extraction | `>=1.6.1`. Standard lib; ~70KB. Used as `parse(spec.response_path).find(payload)`. |
| `aioboto3` | Async S3 client for default `S3BlobStorage` | `>=12.0`. Already common in Python AI stacks; alternative is `aiobotocore` directly. |
| `aiohttp` | HTTP client + upload dispatch endpoint | already pinned (`>=3.9`). |
| `pydantic` | `RestFieldSpec` discriminated union | already pinned (`>=2.0`). Use `Field(discriminator="mode")`. |
| `python-multipart` | Parse multipart bodies if aiohttp's built-in is insufficient | aiohttp's `request.multipart()` should suffice; this is a fallback. |

🔗 **Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/remote_response_resolver.py:66` — mirror the `aiohttp.ClientSession + ClientTimeout + try/except` pattern.
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/forwarder.py:36` — reference pattern for outbound HTTP with auth headers.
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/auth_context.py:20` — `AuthContext.resolve_for(auth_ref)` for outbound headers.
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:149` — `_build_auth_context(request)` for inbound auth extraction.
- `packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py:70` — `register_field_control()` for toolbar metadata.
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:71` — `FormSubmissionStorage.store(submission)` for persistence.
- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py` — `FieldRenderer` Protocol + `FallbackRenderer` (FEAT-167 Phase 1).
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py:70` — `setup_form_api()` to mount the new upload route under `/api/v1`.

---

### Option B: Three separate `FieldType` values (`REST_REMOTE`, `REST_INTERNAL`, `REST_CALLBACK`)

Add three independent enum values, each with its own dedicated config
model. Each gets its own toolbar entry in `controls/builtin.py`, its own
validator branch, its own renderer entry in every renderer's `_registry`,
and its own extractor mapping.

✅ **Pros:**
- Each mode is independently typed — no discriminated-union complexity.
- The form-designer UI shows three distinct controls, making the choice
  explicit at design time.
- Per-mode evolution: e.g., `REST_REMOTE` can add OAuth flow later
  without touching the other two.

❌ **Cons:**
- **Triples surface area** across enum, controls registry, validators
  (~3× the code), renderers (6 renderers × 3 = 18 entries instead of 6),
  extractors (jsonschema + yaml × 3 = 6 mappings instead of 2), and
  documentation.
- 60–80 % of each mode's code is shared (multipart parsing, blob
  persistence, JSONPath extraction, auth handling). Forces either
  duplication or an internal helper that is essentially Option A's
  resolver — without the user-facing single-type benefit.
- Frontend has to build three near-identical components or one with
  conditional rendering — i.e. the discrimination logic resurfaces in
  the UI.
- The user explicitly rejected this in Round 1 ("Un FieldType con modos").

📊 **Effort:** Very High

📦 **Libraries / Tools:** Same as Option A.

🔗 **Existing Code to Reuse:** Same as Option A.

---

### Option C: Generalised `LiveFieldResolver` protocol

Refactor `REMOTE_RESPONSE`, `DYNAMIC_SELECT`, and the new field type into
a single mechanism: every "live" field declares a `resolver_ref` in its
config, and a shared `LiveFieldResolver` protocol owns the lifecycle.
The new field becomes one of many resolvers (`UploadResolver`,
`RemoteFetchResolver`, `OptionsResolver`).

✅ **Pros:**
- Architecturally elegant: eliminates the conceptual overlap between
  `REMOTE_RESPONSE` (fetch+display), `DYNAMIC_SELECT` (fetch+options),
  and the new `REST` (upload+process).
- Future extensibility — adding a new live behaviour means writing one
  resolver, not touching the enum.
- Could enable plugin-style resolvers in the future (rejected for the
  enum in FEAT-167, but a resolver registry is a different surface).

❌ **Cons:**
- **Significant refactor of merged code**: FEAT-167 Phase 3 just shipped.
  Retrofitting `OptionsLoader` + `RemoteResponseResolver` into a unified
  protocol invalidates many tests and migrations not yet stable in
  production.
- Scope creep: the user's ask is one new field type, not an architectural
  re-think. The single FieldType in Option A keeps the surface area
  bounded.
- Plugin-style resolver registry reopens the security/typing concerns
  the brainstorm explicitly rejected for FEAT-167 (Option C there).
- Net code added is similar to Option A, but the **change footprint** in
  already-merged code is much larger — higher regression risk.

📊 **Effort:** Very High

📦 **Libraries / Tools:** Same as Option A, plus a refactor of FEAT-167 services.

🔗 **Existing Code to Reuse:** All of FEAT-167 Phase 3 services — but
they'd be modified, not just imported.

---

## Recommendation

**Option A** is recommended because:

1. It matches the user's Round 1 preference (single `FieldType.REST` with
   mode discriminator) — a deliberate design choice, not a default.
2. It scales the surface area linearly (one new enum value, one new
   validator branch, one new renderer entry per renderer, one new
   extractor mapping per format) — the same cost as each of the
   FEAT-167 field types.
3. It establishes a reusable `AbstractBlobStorage` primitive that future
   fields (audio recording, video — V2) can adopt without re-litigating
   the binary-persistence question.
4. The callback-registry decorator pattern (`@register_form_callback`)
   mirrors `parrot.registry.register_agent` (see
   `packages/ai-parrot/src/parrot/agents/demo.py:39` and
   `parrot/registry/registry.py`) so it lands inside a familiar idiom
   for the project.
5. Tradeoff explicitly accepted: the cross-mode validator (Option A) is
   a single bigger branch instead of three smaller ones (Option B); the
   net code is less, and integration with FEAT-167 services (`AuthContext`,
   `RemoteResponseResolver` aiohttp pattern) is direct.
6. Avoids the destabilisation risk of Option C in recently-merged code.

What we're trading off:
- A slightly larger validator branch and a discriminated `RestFieldSpec`
  model with mode-conditional required fields. Mitigated by Pydantic v2's
  `Field(..., discriminator="mode")` plus explicit per-mode tests.
- A new (modest) S3 dependency (`aioboto3`) and a new JSONPath
  dependency (`jsonpath-ng`). Both are stable, widely used, and the
  alternatives (raw bytes in PG; dotted-path extraction) were considered
  inferior in Round 1.

---

## Feature Description

### User-Facing Behavior

A form designer adds a "REST" control to a form section. In the form-builder
UI they pick a mode (`remote` / `internal` / `callback`), fill in the
relevant config (endpoint URL or callback name, auth_ref, response_path,
display_template, allowed_mime_types via `constraints`), and save.

When a respondent opens the form, the REST field is rendered as an
**uploader** (file input or text area depending on accepted MIME types).
On file selection or text submission:

1. The frontend sends a `multipart/form-data` POST to
   `/api/v1/forms/{form_id}/fields/{field_id}/upload` with the inbound
   user's Bearer token.
2. The frontend shows a spinner — the field is in `uploading` state.
3. The backend processes the upload (see Internal Behavior), then returns
   `{answer, blob_ref, raw_value, warnings}`.
4. The frontend renders `display_template` (or the raw `answer` if no
   template) and stores `answer` as the field value (internally stores
   `blob_ref` too).
5. The field becomes editable again (the user can re-upload to overwrite).
6. If the upload fails (5xx, timeout, MIME rejected), the field stays
   empty; the frontend shows an inline error + retry button. No
   `blob_ref` is persisted on failure.

When the user clicks "submit form":
- If any REST field is still `uploading`, the submit button is disabled
  (frontend gate) AND the backend rejects with
  `400 {field_id, status: "in_progress"}` (defense in depth).
- The submission payload includes `field_data[<field_id>] = {answer,
  blob_ref, ts}`.

### Internal Behavior

The new module `services/rest_field_resolver.py` houses:

- `RestFieldMode = Literal["remote", "internal", "callback"]`
- `RestFieldSpec` — discriminated-union Pydantic model
  (`mode: RestFieldMode`, `endpoint: str | None`, `http_method`,
  `auth_ref`, `callback_ref: str | None`, `response_path: str | None`,
  `display_template: str | None`, `timeout_seconds: int = 30`,
  `persist_binary: bool = True`, `response_schema: dict | None`).
- `RestFieldResult` — `success`, `answer`, `raw_value`, `blob_ref`,
  `status_code`, `error`.
- `RestFieldResolver` — async dispatcher with per-mode branches.

A new module `services/blob_storage.py` defines:

- `AbstractBlobStorage` (ABC) with `async put(stream, *, metadata) -> str`
  returning a `blob_ref`, and `async get(blob_ref) -> AsyncIterator[bytes]`,
  `async delete(blob_ref) -> None`.
- `S3BlobStorage(AbstractBlobStorage)` — default impl using `aioboto3`,
  envelope-encrypts metadata, bucket/prefix from env vars
  (`PARROT_BLOB_BUCKET`, `PARROT_BLOB_PREFIX`).

A new module `services/callback_registry.py` defines:

- `_CALLBACK_REGISTRY: dict[str, RestCallback]`
- `RestCallback = Callable[[RestCallbackInput, AuthContext], Awaitable[RestCallbackOutput]]`
- `@register_form_callback("name")` — decorator that inserts into
  `_CALLBACK_REGISTRY` and refuses duplicate names.

A new aiohttp handler (`api/handlers.py::handle_rest_upload` or its own
module) mounted at `POST /api/v1/forms/{form_id}/fields/{field_id}/upload`:

1. `_wrap_auth` → session authenticated.
2. Load form from registry; resolve `field_id` → `FormField` →
   `RestFieldSpec` from `field.meta["rest"]`.
3. Validate `field.constraints.allowed_mime_types` and
   `max_file_size_bytes` against the multipart part headers.
4. Read multipart parts → `content` (binary or text) + `extra_fields`.
5. Build `AuthContext` from request.
6. Construct `RestCallbackInput(content_type, content, extra_fields,
   form_id, field_id, session_id, user_id, ...)`.
7. `await RestFieldResolver.resolve(spec, payload, auth_context)`.
8. If `spec.persist_binary` and resolver returned success → call
   `blob_storage.put(...)` → set `blob_ref` on the result.
9. Apply JSONPath: `parse(spec.response_path).find(raw_value)` → `answer`.
10. Return JSON `{answer, blob_ref, raw_value, warnings}`.

The validator branch for `FieldType.REST` checks:
- Submitted value is `{answer: any, blob_ref: str | null}` — not a bare
  string or upload payload.
- If `field.required` and value missing or `answer is None` → invalid.
- If submission carries `status="in_progress"` sentinel → reject with
  the structured error described above.
- `response_path` (if present) is a syntactically valid JSONPath at
  schema-validation time (caught early by `RestFieldSpec`'s
  `field_validator`).

### Edge Cases & Error Handling

- **Multipart with no file part** → `400 {error: "no content"}`.
- **MIME mismatch vs `constraints.allowed_mime_types`** → `400` with
  expected vs actual; no blob persisted; no resolver call.
- **File exceeds `max_file_size_bytes`** → `413 Payload Too Large`; the
  resolver is not invoked.
- **Remote endpoint timeout / 5xx** → resolver returns
  `RestFieldResult(success=False, error=...)`; no blob persisted; frontend
  shows retry.
- **Callback raises** → caught, wrapped in `RestFieldResult(success=False,
  error=str(exc))`. Stack trace logged at `WARNING`.
- **JSONPath misses (no match)** → `answer = None` and a `RenderWarning`
  is appended; `raw_value` still returned so the frontend can show context.
- **Concurrent re-upload** → second upload supersedes the first; the
  previous `blob_ref` is best-effort deleted (the cleanup happens
  fire-and-forget; durability of deletion is **NOT** guaranteed —
  callers needing strict cleanup should not rely on this).
- **In-flight upload at submit time** → the validator inspects a
  per-submission `_pending_uploads: set[str]` (or the frontend tags the
  value with `status: "uploading"`), and rejects.
- **Form deleted while upload in flight** → handler returns `410 Gone`;
  blob (if already written) is orphaned and reaped by retention policy.
- **Callback not in registry** → handler returns `500` with a clear
  error referencing the missing `callback_ref`. The form definition is
  considered malformed.
- **Internal mode loopback** → `endpoint` is treated as a path; concatenated
  with `self.base_url`. If the endpoint maps to the same aiohttp app, the
  request goes out-and-back over HTTP (not in-process). Acceptable for V1;
  a future optimisation can short-circuit via the aiohttp router.

---

## Capabilities

### New Capabilities
- `formdesigner-field-rest`: new `FieldType.REST` with mode-discriminated
  config (remote / internal / callback), JSONPath response extraction,
  blob-persistence via abstract storage, and an `@register_form_callback`
  decorator registry.

### Modified Capabilities
*(none — purely additive to parrot-formdesigner)*

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot_formdesigner.core.types.FieldType` | extends | +1 enum value `REST = "rest"`. |
| `parrot_formdesigner.core.schema.FormField.meta` | depends on | New `meta["rest"]: RestFieldSpec.model_dump()` convention. No schema change. |
| `parrot_formdesigner.controls.builtin._BUILTIN_METADATA` | extends | +1 entry: `FieldType.REST` → `category="media"` or `"advanced"` (TBD §Open Questions). |
| `parrot_formdesigner.tools.field_helpers._FIELD_SCHEMA_SNIPPETS` | extends | +1 example snippet (planogram-style). |
| `parrot_formdesigner.services.validators.FormValidator` | extends | +1 branch: coerce + validate submitted value shape `{answer, blob_ref}`. |
| `parrot_formdesigner.services.rest_field_resolver` | **new** | `RestFieldSpec`, `RestFieldResolver`, `RestFieldResult`, `RestCallbackInput`, `RestCallbackOutput`. |
| `parrot_formdesigner.services.blob_storage` | **new** | `AbstractBlobStorage` + `S3BlobStorage` default. |
| `parrot_formdesigner.services.callback_registry` | **new** | `_CALLBACK_REGISTRY`, `@register_form_callback`. |
| `parrot_formdesigner.api.routes.setup_form_api` | extends | Mounts `POST /api/v1/forms/{form_id}/fields/{field_id}/upload`. |
| `parrot_formdesigner.api.handlers` | extends | New `handle_rest_upload` method on `FormAPIHandler` (or extracted to its own module). |
| `parrot_formdesigner.renderers.html5.HTML5Renderer` | extends | +1 entry in `_registry`: `<RestUploader>`-flavoured HTML/JS. |
| `parrot_formdesigner.renderers.jsonschema.JsonSchemaRenderer` | extends | +1 native mapping (`type=object` with `properties: {answer, blob_ref}`). |
| `parrot_formdesigner.renderers.adaptive_card.AdaptiveCardRenderer` | extends | `FallbackRenderer` (Adaptive Card has no multipart upload). |
| `parrot_formdesigner.renderers.pdf.PdfRenderer` | extends | `FallbackRenderer` (labelled placeholder). |
| `parrot_formdesigner.renderers.xforms.XFormsRenderer` | extends | `FallbackRenderer` (ODK has its own upload semantics). |
| `parrot_formdesigner.renderers.telegram.TelegramFormRenderer` | extends | WebApp redirect (consistent with `SIGNATURE` policy). |
| `parrot_formdesigner.extractors.jsonschema` | extends | +1 mapping `"rest"` ↔ `FieldType.REST`. |
| `parrot_formdesigner.extractors.yaml` | extends | +1 mapping `rest`. |
| `packages/parrot-formdesigner/pyproject.toml` | extends | `+jsonpath-ng>=1.6.1`, `+aioboto3>=12.0`. |

No breaking changes to public APIs. No FEAT-167 surfaces modified
(only consumed).

---

## Code Context

### User-Provided Code

*The user did not paste code snippets — only narrative requirements. The
key user statements preserved verbatim:*

> "necesitamos un nuevo Field Type para formularios que permita desde el
> frontend a los usuarios enviar el contenido (sea texto, imágenes o
> videos) a una API REST"
>
> "ya sea remota (con autenticación configurable), interna (ya el backend
> compartirá el jwt token de ai-parrot) con la URL relative + method
> (GET, POST, etc) o incluso un aiohttp handler que se levanta al uso"
>
> "/api/v1/forms/{form_id}/{identificador de current session}/{field id}
> y el contenido es procesado por un 'callback' function al que hace
> referencia en la configuración del form"
>
> "la respuesta de la API puede opcionalmente ser 'procesada' (quedarse
> con una parte del JSON response) y convertirse en 'la respuesta' de
> esta pregunta"
>
> "Subir foto para planogram compliance"

### Verified Codebase References

#### Classes & Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py:16
class FieldType(str, Enum):
    TEXT = "text"
    # ... 29 existing values through line 49 ...
    # NEW (this feature): REST = "rest"

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:23
class FormField(BaseModel):
    model_config = ConfigDict(extra="forbid")              # line 47
    field_id: str                                          # line 49
    field_type: FieldType                                  # line 50
    label: LocalizedString                                 # line 51
    # ... 9 more fields ...
    meta: dict[str, Any] | None = None                     # line 63
    # ↑ This is where RestFieldSpec.model_dump() lives under key "rest".

# packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py:17
class FieldConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")              # line 35
    allowed_mime_types: list[str] | None = None            # line 46
    max_file_size_bytes: int | None                        # line 47
    # ↑ Already supports the upload constraints needed.

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
    content_field: str | None = None                       # line 43
    prompt: str | None = None                              # line 44
    auth_ref: str | None = None                            # line 45
    timeout_seconds: int = 30                              # line 46
    response_schema: dict[str, Any] | None = None          # line 47
# ↑ Reference shape for RestFieldSpec — do NOT subclass; the discriminator
#   means RestFieldSpec is a sibling, not a child.

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
# ↑ Aiohttp + AuthContext.resolve_for pattern to mirror in RestFieldResolver.

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:33
class FormAPIHandler:
    def __init__(self, registry, client=None,
                 submission_storage=None, forwarder=None) -> None: ...  # line 51
    def _build_auth_context(self, request: web.Request) -> AuthContext: ...  # line 149
    async def submit_data(self, request: web.Request) -> web.Response: ...   # line 508
# ↑ Reuse _build_auth_context verbatim.

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
# ↑ This is where the new upload route is registered.

# packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py:36
class FieldControlMetadata(BaseModel): ...
_REGISTRY: dict[str, FieldControlMetadata] = {}            # line 67
def register_field_control(
    field_type: FieldType | str,
    *,
    label: str,
    description: str,
    category: str,
    icon: str,
    snippet: dict[str, Any],
    render_hint: str,
    supports_constraints: bool,
    is_container: bool = False,
) -> None: ...                                              # line 70

# packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:71
class FormSubmissionStorage:
    async def store(
        self,
        submission: FormSubmission,
        *,
        tenant: str | None = None,
    ) -> str: ...                                          # line 177

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py
class FieldRenderer(Protocol): ...
class FallbackRenderer: ...
# ↑ FEAT-167 Phase 1 primitives — reused for the new type's per-renderer
#   registration.

# packages/ai-parrot/src/parrot/registry/registry.py
# - AgentRegistry, register_agent — DECORATOR pattern to mirror for
#   @register_form_callback. Confirmed via:
#   packages/ai-parrot/src/parrot/agents/demo.py:39
#       from parrot.registry import register_agent
#       @register_agent(name="hitl_demo", at_startup=False)
```

#### Verified Imports

```python
# These imports have been confirmed to resolve on the dev branch tip:
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.schema import (
    FormField, FormSection, FormSchema, RenderedForm, SubmitAction,
)
from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.services.auth_context import AuthContext
from parrot_formdesigner.services.remote_response_resolver import (
    RemoteResponseResolver, RemoteResponseResult, RemoteResponseSpec,
)
from parrot_formdesigner.services.forwarder import (
    SubmissionForwarder, ForwardResult,
)
from parrot_formdesigner.services.submissions import (
    FormSubmissionStorage, FormSubmission,
)
from parrot_formdesigner.controls.registry import (
    register_field_control, FieldControlMetadata, _REGISTRY,
)
from parrot_formdesigner.renderers.base import (
    FieldRenderer, FallbackRenderer,
)
from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot.registry import register_agent  # decorator-registry idiom to mirror
```

#### Key Attributes & Constants

- `FieldType.value` — string alias used as the YAML/JSON-schema discriminator (`packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py:16-49`).
- `AuthContext.resolve_for(auth_ref) -> dict[str, str]` — outbound HTTP headers for a given `auth_ref` (`services/auth_context.py:44`).
- `_REGISTRY` (`controls/registry.py:67`) is the **single global control registry** — registration is idempotent (re-registration overwrites with a warning at line 99-103).
- `FormAPIHandler._build_auth_context` builds bearer/api_key cascades; reuse, do not duplicate (`api/handlers.py:149-188`).
- `FormSubmission.data: dict[str, Any]` (`services/submissions.py:60-69`) — this is where `{answer, blob_ref}` lands per field at submit time.

### Does NOT Exist (Anti-Hallucination)

- ~~`FieldType.REST`~~ — does **not exist** today. This feature introduces it.
- ~~`parrot_formdesigner.services.rest_field_resolver`~~ — does **not exist**.
- ~~`parrot_formdesigner.services.blob_storage` / `AbstractBlobStorage` / `S3BlobStorage`~~ — do **not exist**.
- ~~`parrot_formdesigner.services.callback_registry` / `@register_form_callback`~~ — do **not exist**. The closest decorator-registry idiom is `parrot.registry.register_agent` — copy its shape, do **not** import it.
- ~~`POST /api/v1/forms/{form_id}/fields/{field_id}/upload`~~ — the route does **not exist** today. `api/routes.py:setup_form_api` will register it.
- ~~`jsonpath-ng`~~ — **not** in `pyproject.toml` today (verified). Adding it is part of this feature.
- ~~`aioboto3` / `boto3` / `botocore`~~ — **not** in `pyproject.toml` of `packages/parrot-formdesigner`. Adding `aioboto3` is part of this feature.
- ~~Subclassing `RemoteResponseResolver` or `SubmissionForwarder`~~ — forbidden. Mirror the pattern, do not extend.
- ~~Chunked / resumable uploads (tus, resumable.js)~~ — explicitly out of scope for V1 (Round 1 chose single-request multipart).
- ~~Dotted-path callback resolution (`callback: "myapp.callbacks.fn"`)~~ — rejected. Callbacks must be pre-registered.
- ~~Plugin entry points for third-party REST modes~~ — out of scope. The `mode` discriminator is a closed Literal (`"remote" | "internal" | "callback"`).
- ~~Per-field blob retention policy~~ — not modelled in V1. The S3 bucket lifecycle policy handles retention globally.

---

## Parallelism Assessment

- **Internal parallelism**: Low. Like FEAT-167, the changes touch central
  files: `FieldType` enum, `_BUILTIN_METADATA`, every renderer's `_registry`,
  `services/validators.py`, both extractors. Splitting tasks across
  worktrees would conflict at almost every task boundary. The three
  *new* service modules (`rest_field_resolver`, `blob_storage`,
  `callback_registry`) are independent and *could* be developed in
  parallel sub-worktrees once their interfaces are agreed — but with
  ~3 tasks at stake the worktree overhead outweighs the speedup.
- **Cross-feature independence**: No conflicts. FEAT-167 is merged on
  `dev`. No other in-flight spec touches `packages/parrot-formdesigner/`
  (verified against `sdd/specs/`). FEAT-145's per-spec index isolates
  task state cleanly.
- **Recommended isolation**: `per-spec` — single worktree at
  `.claude/worktrees/feat-<NNN>-formdesigner-field-rest/`, tasks executed
  sequentially.
- **Rationale**: Same logic as FEAT-167's Phase 1 — the Phase-1-equivalent
  here is "wire the new FieldType + multipart endpoint through every
  renderer / validator / extractor" and it touches every central file.
  Sequential is safer; parallel buys nothing.

---

## Open Questions

- [ ] Should the `controls/builtin.py` `category` for `FieldType.REST`
      be `"media"` (because uploads are media-flavoured) or `"advanced"`
      (because the live API call is in the same conceptual bucket as
      `REMOTE_RESPONSE`)? — *Owner: jesuslara*
- [ ] Internal-mode URL composition: should `spec.endpoint` be a strict
      path (`/api/v1/...`) and we prepend the aiohttp app's host, or
      do we expose an environment variable `PARROT_INTERNAL_BASE_URL`
      so the value is centralized? — *Owner: jesuslara*
- [ ] Should the callback registry be **tenant-scoped** or global? A
      global registry is simpler; a tenant-scoped one matches the
      multi-tenant model of `FormSubmissionStorage.tenant`. — *Owner: jesuslara*
- [ ] On re-upload, should the previous `blob_ref` be deleted
      synchronously (slower upload, guaranteed cleanup) or marked for
      lifecycle expiry (faster, eventually consistent)? — *Owner: jesuslara*
- [ ] If `spec.response_schema` is provided, is a validation miss a
      hard reject (HTTP 422) or a `RenderWarning` (informational)?
      `REMOTE_RESPONSE` treats it as informational; consistency
      suggests the same. — *Owner: jesuslara*
- [ ] Concurrent uploads per submission: should there be a per-field
      lock so the same `field_id` can't have two in-flight uploads
      from the same session? V1 default would be **last-write-wins**
      (no lock) — confirm. — *Owner: jesuslara*
- [ ] `display_template` syntax: simple `{var}` substitution, full
      Jinja2 (already a dep), or just plain text with no interpolation
      and let the frontend do the rendering? — *Owner: jesuslara*
- [ ] Antivirus / content scanning hook before blob persistence:
      out-of-scope for V1 or a stub interface (`AbstractBlobStorage.put`
      with optional pre-write hook)? — *Owner: jesuslara*
- [ ] Frontend (separate repo) coordination: do we need to publish a
      JSON Schema fragment for `RestFieldSpec` so the form-builder UI
      can render the config panel? FEAT-167 left UI work for a
      follow-up spec — same approach here. — *Owner: jesuslara*
