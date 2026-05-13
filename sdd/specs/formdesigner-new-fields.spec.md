---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: FormDesigner — New Field Types (Shadcn-Forms compatible)

**Feature ID**: FEAT-167
**Date**: 2026-05-13
**Author**: jesuslara
**Status**: draft
**Target version**: parrot-formdesigner 0.4.0

> **Source of design decisions**: this spec is derived from
> `sdd/proposals/formdesigner-new-fields.brainstorm.md` (Recommended Option A).
> All 7 of that document's Open Questions are resolved and carried forward
> verbatim into §8 below.

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot-formdesigner` currently supports a fixed set of 20 primitive
`FieldType` values (`text`, `select`, `file`, `image`, …). These cover basic
inputs but cannot express the richer interactions that modern web UIs
(specifically shadcn-form patterns) routinely need: signature capture,
drag-and-drop image dropzones, transfer lists, ranking scales
(Likert / NPS / star ratings), location combobox, tags input, availability
picker, and data-driven fields whose options or values are resolved at
runtime against an external API (dynamic select, remote response).

Today, the only escape valve is the free-form `FormField.meta` dict, which
forces every renderer to parse meta keys independently and loses semantic
intent in the schema (an NPS score is indistinguishable from any other
integer). Two pieces of plumbing are also missing entirely:

1. **`OptionsSource` runtime** — the model exists at
   `packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py:30`
   but no service actually fetches and caches options against an API.
2. **Per-form auth context** for fields that call out to authenticated APIs
   (Dynamic Select, Remote Response). `AuthConfig` is a *schema-level*
   declaration; there is no runtime carrier for the resolved token across
   the call stack.

### Goals

- Add 10 new `FieldType` enum values for genuinely-new shapes:
  `SIGNATURE`, `DYNAMIC_SELECT`, `TRANSFER_LIST`, `REMOTE_RESPONSE`,
  `AVAILABILITY`, `LOCATION`, `TAGS`, `NPS`, `LIKERT`, `RANKING`.
- Express 2 visual variants of existing types via
  `FormField.meta.render_as`: image dropzone (`IMAGE` + `dropzone`) and
  color picker (`COLOR` + `picker`). No new enum values for these.
- Introduce a `FieldRenderer` protocol + per-renderer registry. Migrate all
  **existing** 20 `FieldType` values into the registry across HTML5,
  Adaptive Card, PDF, XForms, JSON Schema, and Telegram renderers (5 + 1).
  The public `render()` signature of each renderer stays byte-identical.
- Implement the missing runtime services:
  `AuthContext` (Pydantic model carrying resolved credentials),
  `OptionsLoader` (generic async loader for `OptionsSource` with TTL cache),
  `RemoteResponseResolver` (calls external API and stores its response as
  the field value).
- Extend `FieldConstraints` with scale-specific fields
  (`scale_min`, `scale_max`, `scale_step`, `anchor_labels`) for the ranking
  trio.
- Extend `OptionsSource` with `http_method` and `auth_ref` for Dynamic
  Select. (`value_field` / `label_field` already exist — keep those names;
  do **not** invent `value_column` / `label_column`.)
- Add `RenderedForm.warnings: list[RenderWarning]` so callers can detect
  best-effort fallback rendering for unsupported (FieldType, renderer)
  pairs.
- Backwards-compatible across the board: existing serialized forms in
  PostgreSQL (via `services/storage.py`) load, validate, and render
  unchanged. Public renderer APIs unchanged.

### Non-Goals (explicitly out of scope)

- **UI repository changes.** The frontend lives in a separate repo and
  will consume this backend's JSON Schema + controls registry. A follow-up
  spec will cover the UI implementation.
- **`AVAILABILITY` recurrence rules** (RRULE, weekly templates) — discrete
  slots only this round (resolved in brainstorm).
- **Plugin / entry-point extensibility** for third-party field types — the
  brainstorm's Option C was rejected. Field types remain owned by the
  package.
- **Memoising `REMOTE_RESPONSE` calls across resubmissions** — every
  submission re-calls the API; callers design endpoints for idempotency
  (resolved in brainstorm).
- **File / image binary storage backends.** This spec adds new field
  *types* that carry signatures and uploaded blobs; the actual binary
  storage (S3, blob service, etc.) remains delegated to the consumer, as
  today.

---

## 2. Architectural Design

### Overview

The feature ships in **one feature** across **three internal phases**.
Phasing exists so Phase 1 can land as a no-op refactor under existing tests
before any new `FieldType` value goes live — de-risking Phases 2 and 3.

- **Phase 1 — FieldRenderer registry foundation.** Introduce the
  `FieldRenderer` protocol (one signature per output target) and a private
  `_registry: dict[FieldType, FieldRenderer]` attribute per renderer.
  Migrate all **existing 20** `FieldType` values from the if/elif chains
  in `renderers/html5.py:217`, `renderers/adaptive_card.py:591`,
  `renderers/pdf.py:237`, `renderers/xforms.py`, `renderers/jsonschema.py:214`,
  and the Telegram renderer (`renderers/telegram/renderer.py:28`) into
  the registry. The public `render()` method of each renderer continues to
  exist with its current signature — internally it dispatches via
  `_registry.get(field.field_type, _fallback_renderer)`. No user-visible
  behaviour change. Existing renderer tests must pass unchanged.

- **Phase 2 — Schema + new field types.** Add 10 new `FieldType` enum
  values; extend `FieldConstraints` with `scale_min`, `scale_max`,
  `scale_step`, `anchor_labels`; extend `OptionsSource` with `http_method`
  and `auth_ref`. Implement per-type validators in `services/validators.py`,
  per-type extractor mappings in `extractors/jsonschema.py` and
  `extractors/yaml.py`, and per-type entries in each renderer's registry.
  Seed `controls/builtin.py` with `register_field_control()` calls for
  every new type. Renderers that cannot natively express a new type use a
  `FallbackRenderer` that emits a degraded representation **and** appends a
  `RenderWarning` to `RenderedForm.warnings`.

- **Phase 3 — Runtime services.** Three new modules under
  `packages/parrot-formdesigner/src/parrot_formdesigner/services/`:
  `auth_context.py` (Pydantic `AuthContext` model carrying resolved
  credentials), `options_loader.py` (`OptionsLoader` async service —
  `aiohttp` + `services/cache.py` TTL cache, single-flight per
  `(source_ref, auth_ref)` to prevent cache stampede), and
  `remote_response_resolver.py` (`RemoteResponseResolver` async service,
  mirroring `services/forwarder.py:36`'s pattern). Wire `AuthContext`
  construction into `api/handlers.py` so it is built from the inbound
  aiohttp request and passed explicitly to renderer / validator paths.
  `AuthContext` **cascades** into nested `GROUP` / `ARRAY` field renders
  without re-resolution.

### Component Diagram

```
                      ┌──────────────────────┐
                      │  aiohttp Handler     │  (api/handlers.py)
                      │  builds AuthContext  │
                      └──────────┬───────────┘
                                 │ AuthContext (kwarg)
              ┌──────────────────┼──────────────────────┐
              │                  │                       │
              ▼                  ▼                       ▼
       ┌────────────┐     ┌─────────────┐        ┌─────────────────────┐
       │ FormValid- │     │  Renderer   │        │ RemoteResponse-     │
       │   ator     │     │  (any of 6) │        │   Resolver          │
       │ (existing) │     │  uses _reg- │        │ (Phase 3 new)       │
       │            │     │  istry      │        │ aiohttp + retry     │
       └─────┬──────┘     └──────┬──────┘        └─────────────────────┘
             │                   │
             │                   │ per-field FieldRenderer
             │                   ▼
             │            ┌──────────────────────┐
             │            │  OptionsLoader       │
             │            │  (Phase 3 new)       │
             │            │  aiohttp + cache.py  │
             │            │  single-flight       │
             │            └──────────────────────┘
             │
             └──► Validator branches per new FieldType
                  (NPS/LIKERT/RANKING use scale_* constraints;
                  SIGNATURE validates SVG+PNG dict;
                  REMOTE_RESPONSE calls RemoteResponseResolver)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot_formdesigner.core.types.FieldType` | extends (additive) | +10 enum values. |
| `parrot_formdesigner.core.constraints.FieldConstraints` | extends (additive) | +`scale_min`, `scale_max`, `scale_step`, `anchor_labels`. |
| `parrot_formdesigner.core.options.OptionsSource` | extends (additive) | +`http_method`, `auth_ref`. Keep existing `value_field` / `label_field`. |
| `parrot_formdesigner.core.schema.RenderedForm` | extends (additive) | +`warnings: list[RenderWarning] = []`. |
| `parrot_formdesigner.renderers.base.AbstractFormRenderer` | extends | Public `render()` signature unchanged. Add internal `FieldRenderer` protocol + `FallbackRenderer` base. |
| `parrot_formdesigner.renderers.html5.HTML5Renderer` | refactors + extends | Migrate to registry. Add new types. |
| `parrot_formdesigner.renderers.adaptive_card.AdaptiveCardRenderer` | refactors + extends | Migrate to registry. Some new types use fallback. |
| `parrot_formdesigner.renderers.pdf.PdfRenderer` | refactors + extends | Migrate to registry. Most interactive types use fallback. |
| `parrot_formdesigner.renderers.xforms.XFormsRenderer` | refactors + extends | Migrate to registry. ODK-incompatible types use fallback. |
| `parrot_formdesigner.renderers.jsonschema.JsonSchemaRenderer` | refactors + extends | Lingua franca for UI consumers. Must support every new type natively. |
| `parrot_formdesigner.renderers.telegram.TelegramFormRenderer` | refactors + extends | Update `_INLINE_FIELD_TYPES` / `_WEBAPP_FIELD_TYPES` sets to classify new types. Migrate dispatch to registry. |
| `parrot_formdesigner.services.validators.FormValidator` | extends | One new validator branch per new `FieldType`. Also enforces scale constraints. |
| `parrot_formdesigner.services.cache.FormCache` | depends on | `OptionsLoader` reuses the existing TTL cache. |
| `parrot_formdesigner.services.forwarder.SubmissionForwarder` | reference only | `RemoteResponseResolver` mirrors its aiohttp + auth pattern. No code shared. |
| `parrot_formdesigner.extractors.jsonschema` / `extractors.yaml` | extends | Reverse mapping for new types. |
| `parrot_formdesigner.controls.builtin` | extends | One `register_field_control()` call per new type. |
| `parrot_formdesigner.api.handlers.FormAPIHandler` | extends | Build `AuthContext` from inbound request, pass to renderer/validator. |
| `pyproject.toml` (parrot-formdesigner) | extends | Add `pycountry>=23.0` dependency. |

### Data Models

```python
# New & extended Pydantic models. NOT IMPLEMENTATION — design only.

# parrot_formdesigner/core/types.py — extended (additive)
class FieldType(str, Enum):
    # ... 20 existing values unchanged ...
    SIGNATURE = "signature"
    DYNAMIC_SELECT = "dynamic_select"
    TRANSFER_LIST = "transfer_list"
    REMOTE_RESPONSE = "remote_response"
    AVAILABILITY = "availability"
    LOCATION = "location"
    TAGS = "tags"
    NPS = "nps"
    LIKERT = "likert"
    RANKING = "ranking"

# parrot_formdesigner/core/constraints.py — FieldConstraints extended
class FieldConstraints(BaseModel):
    # ... existing fields unchanged ...
    scale_min: int | None = None              # ge=0 enforced by validator
    scale_max: int | None = None              # gt=scale_min enforced by validator
    scale_step: int | None = None             # default=1 when scale_max set
    anchor_labels: dict[int, LocalizedString] | None = None

# parrot_formdesigner/core/options.py — OptionsSource extended
class OptionsSource(BaseModel):
    source_type: str                          # existing
    source_ref: str                           # existing (URL when source_type="endpoint")
    value_field: str = "value"                # existing — keep this name
    label_field: str = "label"                # existing — keep this name
    cache_ttl_seconds: int | None = None      # existing
    http_method: Literal["GET", "POST"] = "GET"      # NEW
    auth_ref: str | None = None                       # NEW — resolved via AuthContext

# parrot_formdesigner/core/schema.py — RenderedForm extended
class RenderWarning(BaseModel):
    field_id: str
    field_type: str             # FieldType.value
    renderer: str               # "html5" | "adaptive_card" | "pdf" | "xforms" | "jsonschema" | "telegram"
    reason: str                 # e.g. "unsupported in PDF — rendered as placeholder"

class RenderedForm(BaseModel):
    content: Any                                  # existing
    content_type: str                             # existing
    style_output: Any | None = None               # existing
    metadata: dict[str, Any] | None = None        # existing
    warnings: list[RenderWarning] = []            # NEW (default empty for backwards compat)

# parrot_formdesigner/services/auth_context.py — NEW
class AuthContext(BaseModel):
    """Runtime auth context constructed by the aiohttp handler per request.

    Distinct from core.auth.AuthConfig which is the schema-side declaration.
    AuthContext carries resolved credentials. Passed explicitly to
    OptionsLoader.fetch() / RemoteResponseResolver.resolve().
    """
    scheme: Literal["none", "bearer", "api_key", "custom"]
    token: str | None = None
    headers: dict[str, str] = {}
    claims: dict[str, Any] = {}                   # parsed JWT claims if available

    def resolve_for(self, auth_ref: str | None) -> dict[str, str]:
        """Return outbound HTTP headers for the given auth_ref, or {}."""

# parrot_formdesigner/services/remote_response_resolver.py — NEW
class RemoteResponseSpec(BaseModel):
    """Embedded in FormField.meta for REMOTE_RESPONSE fields."""
    endpoint: str
    http_method: Literal["GET", "POST"] = "POST"
    content_field: str | None = None              # other field whose value is sent
    prompt: str | None = None
    auth_ref: str | None = None
    timeout_seconds: int = 30
    response_schema: dict[str, Any] | None = None  # optional JSON Schema for response

class RemoteResponseResult(BaseModel):
    success: bool
    value: Any | None = None
    status_code: int | None = None
    error: str | None = None
```

### New Public Interfaces

```python
# parrot_formdesigner/renderers/base.py — additions
class FieldRenderer(Protocol):
    """Per-target field renderer. One concrete impl per (FieldType, output)."""
    async def render(
        self,
        field: FormField,
        *,
        locale: str = "en",
        prefilled: Any = None,
        error: str | None = None,
        auth_context: AuthContext | None = None,
    ) -> Any: ...  # return type depends on output target

class FallbackRenderer:
    """Concrete fallback emitter — degraded representation + appended warning.

    Each renderer subclasses this to define what 'degraded' means for its
    target (e.g. PDF: labelled empty box; XForms: <xf:input> with a help
    note; Telegram: WebApp redirect).
    """

# parrot_formdesigner/services/options_loader.py — new
class OptionsLoader:
    DEFAULT_TIMEOUT: int = 30

    def __init__(self, cache: FormCache | None = None, timeout: int = DEFAULT_TIMEOUT) -> None: ...

    async def fetch(
        self,
        source: OptionsSource,
        *,
        auth_context: AuthContext | None = None,
    ) -> list[FieldOption]:
        """Fetch and normalise options. Cache key = (source_ref, auth_ref).
        Single-flight: concurrent calls for the same key share one request.
        Failure returns [] and logs a warning — never raises.
        """

# parrot_formdesigner/services/remote_response_resolver.py — new
class RemoteResponseResolver:
    DEFAULT_TIMEOUT: int = 30

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None: ...

    async def resolve(
        self,
        spec: RemoteResponseSpec,
        content: Any,
        *,
        auth_context: AuthContext | None = None,
    ) -> RemoteResponseResult:
        """Call the external API and return its response as the field value.
        Retry policy: caller-driven (every form submission re-invokes).
        """
```

---

## 3. Module Breakdown

Modules below are ordered by dependency. Phase 1 must complete before
Phase 2; Phase 2's schema/registry work must precede Phase 2's per-type
renderer implementations. Phase 3 services have only `AuthContext` as a
hard dependency on each other.

### Phase 1 — Foundation

#### Module 1: FieldRenderer protocol + registry skeleton
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py`
- **Responsibility**: Add `FieldRenderer` Protocol and `FallbackRenderer` base
  class. No changes to `AbstractFormRenderer.render()` signature.
- **Depends on**: none.

#### Module 2: Renderer registry — HTML5
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py`
- **Responsibility**: Add `_registry: dict[FieldType, FieldRenderer]`. Move
  each existing `if field.field_type == FieldType.X` branch (lines ~217–289)
  into a `FieldRenderer` callable registered for `X`. Public
  `HTML5Renderer.render()` unchanged. Existing tests pass unchanged.
- **Depends on**: Module 1.

#### Module 3: Renderer registry — Adaptive Card
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py`
- **Responsibility**: Same migration pattern as Module 2 (lines ~591, ~860–869).
- **Depends on**: Module 1.

#### Module 4: Renderer registry — PDF
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py`
- **Responsibility**: Same migration pattern (lines ~35–40, ~237–299).
  Preserve the existing "unsupported types → placeholder textfield" behaviour
  via `FallbackRenderer`.
- **Depends on**: Module 1.

#### Module 5: Renderer registry — XForms
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py`
- **Responsibility**: Same migration pattern.
- **Depends on**: Module 1.

#### Module 6: Renderer registry — JSON Schema
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py`
- **Responsibility**: Same migration pattern (line ~214+).
- **Depends on**: Module 1.

#### Module 7: Renderer registry — Telegram
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/telegram/renderer.py`
- **Responsibility**: Same migration pattern. The existing
  `_INLINE_FIELD_TYPES` / `_WEBAPP_FIELD_TYPES` sets become inputs to
  per-type renderer registration.
- **Depends on**: Module 1.

#### Module 8: RenderedForm.warnings + RenderWarning
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`
- **Responsibility**: Add `RenderWarning` model and `RenderedForm.warnings:
  list[RenderWarning] = []`. Default empty preserves backwards compatibility.
- **Depends on**: Module 1.

### Phase 2 — Schema additions + per-type implementations

#### Module 9: FieldType enum additions
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py`
- **Responsibility**: Append 10 new enum values: `SIGNATURE`,
  `DYNAMIC_SELECT`, `TRANSFER_LIST`, `REMOTE_RESPONSE`, `AVAILABILITY`,
  `LOCATION`, `TAGS`, `NPS`, `LIKERT`, `RANKING`.
- **Depends on**: none (additive to enum).

#### Module 10: FieldConstraints — scale fields
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py`
- **Responsibility**: Add `scale_min`, `scale_max`, `scale_step`,
  `anchor_labels` fields with `field_validator` enforcing
  `scale_max > scale_min` when both are set, and `anchor_labels` keys are
  within `[scale_min, scale_max]`.
- **Depends on**: none.

#### Module 11: OptionsSource extensions
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py`
- **Responsibility**: Add `http_method: Literal["GET", "POST"] = "GET"` and
  `auth_ref: str | None = None`. Keep existing `value_field` / `label_field`
  names. Do NOT introduce `value_column` / `label_column`.
- **Depends on**: none.

#### Module 12: Validator branches for new types
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py`
- **Responsibility**: Extend `FormValidator` with one branch per new type.
  Coercion rules per type (see §7 Data shape table). NPS/LIKERT/RANKING
  enforce scale bounds. `SIGNATURE` validates the
  `{"svg": str, "png": str}` dict shape and MIME types via
  `constraints.allowed_mime_types`. `REMOTE_RESPONSE` invokes
  `RemoteResponseResolver` (Phase 3 dependency — Module 12 will be split
  into 12a/12b at task-decomposition time, with 12b waiting for Phase 3).
- **Depends on**: Modules 9, 10, and (for `REMOTE_RESPONSE`) Phase 3 services.

#### Module 13: Per-type renderer implementations
- **Path**: spans all renderer files (Modules 2–7).
- **Responsibility**: Register one `FieldRenderer` callable per new
  `FieldType` per renderer. For unsupported pairs, register `FallbackRenderer`
  (which appends a `RenderWarning`). Renderer-coverage matrix:

  | FieldType | JSON Schema | HTML5 | Adaptive Card | PDF | XForms | Telegram |
  |---|---|---|---|---|---|---|
  | `SIGNATURE` | ✓ native | ✓ native | fallback (placeholder) | fallback (empty box) | fallback | WebApp |
  | `DYNAMIC_SELECT` | ✓ native | ✓ native | ✓ native | fallback (text input) | ✓ as `<xf:select1>` | inline/WebApp |
  | `TRANSFER_LIST` | ✓ native | ✓ native | ✓ as multi-choice | fallback (multi-line) | ✓ as `<xf:select>` | WebApp |
  | `REMOTE_RESPONSE` | ✓ native | ✓ native (read-only) | fallback | fallback | fallback | WebApp |
  | `AVAILABILITY` | ✓ native | ✓ native | fallback | fallback | fallback | WebApp |
  | `LOCATION` | ✓ native | ✓ native | ✓ as choice list | ✓ as text | ✓ as `<xf:select1>` | inline |
  | `TAGS` | ✓ native | ✓ native | ✓ as text | ✓ as text | ✓ as `<xf:input>` | WebApp |
  | `NPS` | ✓ native | ✓ native | ✓ native | ✓ as numeric input | ✓ as `<xf:range>` | inline |
  | `LIKERT` | ✓ native | ✓ native | ✓ as choice set | ✓ as numeric input | ✓ as `<xf:select1>` | inline |
  | `RANKING` | ✓ native | ✓ native | ✓ as numeric input | ✓ as numeric input | ✓ as `<xf:range>` | inline |
- **Depends on**: Modules 1–11.

#### Module 14: Extractor reverse-mappings
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py`,
  `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/yaml.py`
- **Responsibility**: Round-trip support for new types via JSON Schema
  (e.g. `{"type": "string", "format": "signature"}` ↔ `FieldType.SIGNATURE`)
  and YAML keys (`signature`, `dynamic_select`, …).
- **Depends on**: Modules 9, 10, 11.

#### Module 15: Controls registry seeding
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py`
- **Responsibility**: Call `register_field_control()` for each new type with
  appropriate `category` (`"media"` for SIGNATURE/dropzone variant;
  `"selection"` for DYNAMIC_SELECT/TRANSFER_LIST/LOCATION/TAGS;
  `"advanced"` for REMOTE_RESPONSE/AVAILABILITY/NPS/LIKERT/RANKING).
- **Depends on**: Module 9.

#### Module 16: pycountry dependency + LOCATION reference data
- **Path**: `packages/parrot-formdesigner/pyproject.toml`,
  `packages/parrot-formdesigner/src/parrot_formdesigner/core/_location_data.py` (NEW)
- **Responsibility**: Add `pycountry>=23.0` to dependencies. Create a thin
  wrapper that exposes country code / name / flag emoji / dial code so
  validators and the JSON Schema extractor can validate `LOCATION` values.
- **Depends on**: Module 9.

### Phase 3 — Runtime services

#### Module 17: AuthContext model
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/auth_context.py` (NEW)
- **Responsibility**: Define `AuthContext` Pydantic model. Document
  cascade behaviour: parent context flows into nested GROUP/ARRAY fields.
  `AuthContext.resolve_for(auth_ref)` returns outbound HTTP headers.
- **Depends on**: none.

#### Module 18: OptionsLoader service
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/options_loader.py` (NEW)
- **Responsibility**: Async loader. `aiohttp.ClientSession` + `services/cache.py`
  TTL cache (key = `(source_ref, auth_ref)`). Single-flight per key to
  prevent stampede (an asyncio `Event` + in-flight dict). Failure (timeout,
  5xx, auth rejection) returns `[]` and logs a warning. Reused by both
  `SELECT` (when `options_source` set) and `DYNAMIC_SELECT`.
- **Depends on**: Modules 11, 17.

#### Module 19: RemoteResponseResolver service
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/remote_response_resolver.py` (NEW)
- **Responsibility**: Mirrors `SubmissionForwarder` pattern. Sends
  `(content, prompt)` to `spec.endpoint` with `auth_context` resolved
  headers. Returns `RemoteResponseResult`. Retries on every form
  submission (caller responsibility for endpoint idempotency).
- **Depends on**: Module 17.

#### Module 20: API handler integration — build AuthContext
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
- **Responsibility**: Construct `AuthContext` from the inbound aiohttp
  request (Authorization header, session, or middleware-provided
  attribute). Pass to `FormValidator` and renderers via kwarg. Cascade is
  automatic — renderers thread `auth_context` to nested field renderers.
- **Depends on**: Modules 17, 18, 19.

#### Module 21: Validator branch wiring for REMOTE_RESPONSE
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py`
- **Responsibility**: Complete the deferred sub-task of Module 12: the
  `REMOTE_RESPONSE` validator branch invokes `RemoteResponseResolver.resolve()`
  and stores the result as the field value before further validation.
- **Depends on**: Modules 12, 19.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_field_renderer_protocol_minimal` | 1 | `FieldRenderer` protocol + `FallbackRenderer` instantiate; `FallbackRenderer` appends a `RenderWarning`. |
| `test_html5_registry_dispatch_existing_types` | 2 | All 20 existing `FieldType` values render via registry identical to pre-migration baseline (snapshot tests). |
| `test_adaptive_card_registry_dispatch_existing_types` | 3 | Same as above for Adaptive Card. |
| `test_pdf_registry_dispatch_existing_types` | 4 | Same as above for PDF. |
| `test_xforms_registry_dispatch_existing_types` | 5 | Same as above for XForms. |
| `test_jsonschema_registry_dispatch_existing_types` | 6 | Same as above for JSON Schema. |
| `test_telegram_registry_dispatch_existing_types` | 7 | Same as above for Telegram (inline / WebApp classification preserved). |
| `test_rendered_form_warnings_default_empty` | 8 | `RenderedForm()` defaults `warnings=[]`; existing call sites unaffected. |
| `test_field_type_enum_has_new_values` | 9 | All 10 new enum values present and have stable string aliases. |
| `test_field_constraints_scale_validator_rejects_inverted_range` | 10 | `scale_max < scale_min` raises ValidationError. |
| `test_field_constraints_anchor_labels_in_bounds` | 10 | Anchor label keys outside `[scale_min, scale_max]` raise. |
| `test_options_source_http_method_default_get` | 11 | New `OptionsSource` defaults `http_method="GET"`. |
| `test_options_source_auth_ref_optional` | 11 | `auth_ref` is optional; legacy schemas without it deserialize unchanged. |
| `test_validator_signature_accepts_svg_png_dict` | 12 | `SIGNATURE` accepts `{"svg": "...", "png": "..."}` and rejects bare strings. |
| `test_validator_nps_clamps_to_0_10` | 12 | `NPS` coerces 11→ValidationError, "5"→5, -1→ValidationError. |
| `test_validator_likert_uses_scale_bounds` | 12 | `LIKERT` enforces `constraints.scale_min..scale_max`. |
| `test_validator_ranking_default_5_stars` | 12 | `RANKING` with no scale set defaults to 0..5. |
| `test_validator_tags_returns_list_of_strings` | 12 | `TAGS` accepts `"a,b,c"`, `["a","b","c"]`, both yield `["a","b","c"]`. |
| `test_validator_availability_rejects_overlapping_slots` | 12 | Two overlapping `(start,end)` slots raise unless `meta.allow_overlap=True`. |
| `test_validator_location_rejects_unknown_iso_code` | 12 | `LOCATION` with `"XX"` raises; `"ES"`, `"VE"`, `"US"` pass. |
| `test_renderer_fallback_emits_warning` | 13 | PDF rendering of `SIGNATURE` produces a placeholder + appends `RenderWarning(field_type="signature", renderer="pdf", reason=...)`. |
| `test_renderer_coverage_matrix` | 13 | Each (FieldType, renderer) pair from §3 Module 13 produces either native output or a fallback with a warning. No silent fallbacks. |
| `test_extractor_yaml_signature_roundtrip` | 14 | YAML key `signature` extracts to `FieldType.SIGNATURE` and re-emits unchanged. |
| `test_extractor_jsonschema_dynamic_select_roundtrip` | 14 | JSON Schema → `FieldType.DYNAMIC_SELECT` with `options_source` preserved. |
| `test_controls_registry_has_all_new_types` | 15 | `get_controls()` returns 30 entries (20 existing + 10 new). |
| `test_pycountry_dependency_resolves_es` | 16 | Wrapper returns ISO-2 `ES` → name `"Spain"`, flag `"🇪🇸"`, dial code `+34`. |
| `test_auth_context_resolve_for_known_ref` | 17 | `AuthContext` returns Bearer header for matching `auth_ref`. |
| `test_auth_context_resolve_for_unknown_ref` | 17 | Returns `{}` and logs warning — does not raise. |
| `test_options_loader_fetch_uses_value_label_fields` | 18 | Mocked aiohttp returns `[{"id":1,"name":"A"}]`; loader returns `[FieldOption(value="1", label="A")]` when `value_field=id`, `label_field=name`. |
| `test_options_loader_cache_hit_within_ttl` | 18 | Second call within TTL does not hit aiohttp. |
| `test_options_loader_single_flight` | 18 | Two concurrent calls for the same `(source_ref, auth_ref)` share one in-flight request. |
| `test_options_loader_failure_returns_empty` | 18 | Mocked 500 response yields `[]` (no raise). |
| `test_remote_response_resolver_posts_content` | 19 | Mocked endpoint receives `{"content": ..., "prompt": ...}` and returns the API value. |
| `test_remote_response_resolver_retries_on_resubmit` | 19 | Two sequential `.resolve()` calls hit the mock endpoint twice (no memoisation). |
| `test_remote_response_resolver_failure_returns_error` | 19 | Mocked 500 yields `RemoteResponseResult(success=False, error=...)`. |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_yaml_to_html5_signature` | YAML schema with `signature` → FormSchema → HTML5 render → assert canvas + hidden inputs for svg/png. |
| `test_e2e_jsonschema_to_html5_dynamic_select` | JSON Schema with `dynamic_select` + `options_source` → HTML5 render fetches options via mocked aiohttp. |
| `test_e2e_yaml_to_pdf_with_warnings` | YAML form mixing 5 new types → PDF render → assert `RenderedForm.warnings` lists each degraded field. |
| `test_e2e_form_submission_with_remote_response` | Mock aiohttp server → form submission triggers `RemoteResponseResolver` → resolved value stored as field value. |
| `test_e2e_authcontext_cascade_into_group` | Nested GROUP field whose child needs `auth_ref` resolves via parent's `AuthContext`. |
| `test_e2e_backwards_compat_existing_forms` | Load 5 existing form fixtures from `tests/fixtures/legacy/` → validate + render with all 6 renderers → no failures, no new warnings. |
| `test_e2e_optionsloader_with_select_field` | Existing `SELECT` field with `options_source` (no `DYNAMIC_SELECT` involved) → options now fetched via `OptionsLoader` rather than left empty. |

### Test Data / Fixtures

```python
# tests/fixtures/new_field_types/
@pytest.fixture
def signature_field() -> FormField:
    return FormField(
        field_id="sig",
        field_type=FieldType.SIGNATURE,
        label="Signature",
        constraints=FieldConstraints(
            allowed_mime_types=["image/svg+xml", "image/png"],
            max_file_size_bytes=1_048_576,
        ),
    )

@pytest.fixture
def nps_field() -> FormField:
    return FormField(
        field_id="recommend",
        field_type=FieldType.NPS,
        label="How likely are you to recommend us?",
        constraints=FieldConstraints(scale_min=0, scale_max=10),
    )

@pytest.fixture
def dynamic_select_field() -> FormField:
    return FormField(
        field_id="assignee",
        field_type=FieldType.DYNAMIC_SELECT,
        label="Assignee",
        options_source=OptionsSource(
            source_type="endpoint",
            source_ref="https://api.example.test/users",
            value_field="id",
            label_field="full_name",
            http_method="GET",
            auth_ref="TEST_JWT",
            cache_ttl_seconds=300,
        ),
    )

@pytest.fixture
def mock_auth_context() -> AuthContext:
    return AuthContext(
        scheme="bearer",
        token="test-token",
        headers={"Authorization": "Bearer test-token"},
        claims={"sub": "user-1"},
    )

@pytest.fixture
async def aiohttp_mock_server(aiohttp_server):
    """Lightweight aiohttp test server for OptionsLoader/RemoteResponseResolver."""
    # ... aiohttp_server fixture from pytest-aiohttp ...
```

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/ -v`
- [ ] All integration tests pass: `pytest packages/parrot-formdesigner/tests/integration/ -v`
- [ ] `ruff check packages/parrot-formdesigner/` passes with zero warnings.
- [ ] `mypy packages/parrot-formdesigner/src/` passes with zero errors (strict mode where already configured).
- [ ] Phase 1 commits are independently green — every existing form fixture
      renders byte-identical across all 6 renderers before vs. after the
      registry migration (snapshot-based assertion).
- [ ] All 10 new `FieldType` values are present in `core/types.py` and
      have a `register_field_control()` entry in `controls/builtin.py`.
- [ ] `FieldConstraints` carries `scale_min`, `scale_max`, `scale_step`,
      `anchor_labels` with validators enforcing ordering and bounds.
- [ ] `OptionsSource` carries `http_method` and `auth_ref`; existing
      schemas without these fields deserialize unchanged.
- [ ] `RenderedForm.warnings` exists; renders with no fallback produce
      `warnings == []`; renders with degraded types produce one
      `RenderWarning` per degraded field.
- [ ] `AbstractFormRenderer.render()` and each concrete renderer's
      `render()` method retains its current public signature byte-identical
      (verified by a signature-import test using `inspect.signature`).
- [ ] `AuthContext`, `OptionsLoader`, `RemoteResponseResolver` exist under
      `services/`, are async, use `aiohttp` (no `requests` / `httpx`), and
      reuse `services/cache.py` for TTL caching where applicable.
- [ ] `OptionsLoader` single-flight: a regression test asserts two
      concurrent calls for the same `(source_ref, auth_ref)` make exactly
      one outbound HTTP request.
- [ ] `RemoteResponseResolver` retries on every submission: a test asserts
      two `.resolve()` calls make two outbound requests (no memoisation).
- [ ] `AuthContext` cascades into nested `GROUP` / `ARRAY` field renders
      without re-resolution — integration test in `test_e2e_authcontext_cascade_into_group`.
- [ ] `pycountry>=23.0` is in `packages/parrot-formdesigner/pyproject.toml`
      and the `LOCATION` validator rejects unknown ISO codes.
- [ ] `SIGNATURE` field submissions are validated as
      `{"svg": str, "png": str}` with MIME types listed in
      `constraints.allowed_mime_types`.
- [ ] No regression in the FEAT-166 multi-origin dispatcher
      (`AbstractFormService`, `FormServiceRegistry`,
      `NetworkninjaFormService`, `DatabaseFormTool`) — their existing
      tests pass unchanged.
- [ ] No breaking changes to public API: any external caller that imports
      `HTML5Renderer`, `AdaptiveCardRenderer`, `PdfRenderer`,
      `XFormsRenderer`, `JsonSchemaRenderer`, or `TelegramFormRenderer`
      and calls `.render(form, …)` works without modification.
- [ ] Documentation updated: each new field type has a usage example in
      `packages/parrot-formdesigner/docs/` (one page per type, ~30 lines each).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.**
> All references below were re-verified on 2026-05-13 against the `dev`
> branch tip. Implementation agents MUST use these imports / signatures
> verbatim and MUST NOT invent attributes not listed.

### Verified Imports

```python
# These imports have been confirmed to resolve:
from parrot_formdesigner.core.types import FieldType, LocalizedString
from parrot_formdesigner.core.schema import (
    FormField, FormSection, FormSchema, RenderedForm, SubmitAction,
)
from parrot_formdesigner.core.constraints import (
    FieldConstraints, DependencyRule, ConditionOperator, FieldCondition,
)
from parrot_formdesigner.core.options import FieldOption, OptionsSource
from parrot_formdesigner.core.auth import (
    AuthConfig, NoAuth, BearerAuth, ApiKeyAuth,
)
from parrot_formdesigner.renderers.base import AbstractFormRenderer
from parrot_formdesigner.services.forwarder import (
    SubmissionForwarder, ForwardResult,
)
from parrot_formdesigner.controls.registry import (
    register_field_control, FieldControlMetadata, get_controls, iter_controls,
)
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py:16
class FieldType(str, Enum):
    """Supported form field types."""
    TEXT = "text"            # line 19
    TEXT_AREA = "text_area"  # line 20
    NUMBER = "number"        # line 21
    INTEGER = "integer"      # line 22
    BOOLEAN = "boolean"      # line 23
    DATE = "date"            # line 24
    DATETIME = "datetime"    # line 25
    TIME = "time"            # line 26
    SELECT = "select"        # line 27
    MULTI_SELECT = "multi_select"  # line 28
    FILE = "file"            # line 29
    IMAGE = "image"          # line 30
    COLOR = "color"          # line 31
    URL = "url"              # line 32
    EMAIL = "email"          # line 33
    PHONE = "phone"          # line 34
    PASSWORD = "password"    # line 35
    HIDDEN = "hidden"        # line 36
    GROUP = "group"          # line 37
    ARRAY = "array"          # line 38

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:21
class FormField(BaseModel):
    model_config = ConfigDict(extra="forbid")              # line 45
    field_id: str                                          # line 47
    field_type: FieldType                                  # line 48
    label: LocalizedString                                 # line 49
    description: LocalizedString | None = None             # line 50
    placeholder: LocalizedString | None = None             # line 51
    required: bool = False                                 # line 52
    default: Any = None                                    # line 53
    read_only: bool = False                                # line 54
    constraints: FieldConstraints | None = None            # line 55
    options: list[FieldOption] | None = None               # line 56
    options_source: OptionsSource | None = None            # line 57
    depends_on: DependencyRule | None = None               # line 58
    children: list[FormField] | None = None                # line 59
    item_template: FormField | None = None                 # line 60
    meta: dict[str, Any] | None = None                     # line 61

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:145
class RenderedForm(BaseModel):
    content: Any                                           # line 155
    content_type: str                                      # line 156
    style_output: Any | None = None                        # line 157
    metadata: dict[str, Any] | None = None                 # line 158
    # NEW (Module 8): warnings: list[RenderWarning] = []

# packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py:17
class FieldConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")              # line 35
    min_length: int | None                                 # line 37
    max_length: int | None                                 # line 38
    min_value: float | None = None                         # line 39
    max_value: float | None = None                         # line 40
    step: float | None = None                              # line 41
    pattern: str | None = None                             # line 42
    pattern_message: LocalizedString | None = None         # line 43
    min_items: int | None                                  # line 44
    max_items: int | None                                  # line 45
    allowed_mime_types: list[str] | None = None            # line 46
    max_file_size_bytes: int | None                        # line 47
    # NEW (Module 10): scale_min, scale_max, scale_step, anchor_labels

# packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py:30
class OptionsSource(BaseModel):
    source_type: str                                       # line 41
    source_ref: str                                        # line 42
    value_field: str = "value"                             # line 43
    label_field: str = "label"                             # line 44
    cache_ttl_seconds: int | None = None                   # line 45
    # NEW (Module 11): http_method, auth_ref

# packages/parrot-formdesigner/src/parrot_formdesigner/core/auth.py:145
AuthConfig = NoAuth | BearerAuth | ApiKeyAuth
# - NoAuth.resolve() -> dict[str, str]          (returns {})       line 68
# - BearerAuth.resolve() -> dict[str, str]      (reads token_env)  line 95
# - ApiKeyAuth.resolve() -> dict[str, str]      (reads key_env)    line 131

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py:14
class AbstractFormRenderer(ABC):
    @abstractmethod
    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm: ...                                 # lines 25–46
# SIGNATURE MUST STAY BYTE-IDENTICAL.

# packages/parrot-formdesigner/src/parrot_formdesigner/services/forwarder.py:36
class SubmissionForwarder:
    DEFAULT_TIMEOUT: int = 30                              # line 50
    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None: ...  # line 52
    # async def forward(self, data, submit_action) -> ForwardResult
# Reference pattern for RemoteResponseResolver — do NOT subclass.

# packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py:70
def register_field_control(
    field_type: FieldType | str,
    *,
    label: str,
    description: str,
    category: str,            # "basic" | "selection" | "media" | "layout" | "advanced"
    icon: str,
    snippet: dict[str, Any],
    render_hint: str,
    supports_constraints: bool,
    is_container: bool = False,
) -> None: ...
# Idempotent — re-registration overwrites with a warning.

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/telegram/renderer.py:28
_INLINE_FIELD_TYPES = {FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.BOOLEAN, FieldType.HIDDEN}
_WEBAPP_FIELD_TYPES = {FieldType.TEXT, FieldType.TEXT_AREA, FieldType.NUMBER, FieldType.INTEGER,
                       FieldType.DATE, FieldType.DATETIME, FieldType.TIME, FieldType.EMAIL,
                       FieldType.URL, FieldType.PHONE, FieldType.PASSWORD, FieldType.COLOR,
                       FieldType.FILE, FieldType.IMAGE, ...}
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FieldRenderer` protocol | `AbstractFormRenderer.render()` | private `_registry` dispatch | `renderers/base.py:14` (public signature unchanged) |
| `RenderWarning`, `RenderedForm.warnings` | renderer output path | append-on-fallback | `core/schema.py:145` |
| 10 new `FieldType` values | `FormField.field_type` | enum extension | `core/schema.py:48`, `core/types.py:16` |
| `FieldConstraints.scale_*` | `FormValidator` (NPS/LIKERT/RANKING branches) | constraint check | `services/validators.py:205` |
| `OptionsSource.http_method`, `.auth_ref` | `OptionsLoader.fetch()` | fetch parameters | `core/options.py:30` |
| `AuthContext` | `OptionsLoader.fetch()`, `RemoteResponseResolver.resolve()`, `FormValidator`, renderers | kwarg | new module — Phase 3 |
| `OptionsLoader` | `services/cache.py` (TTL cache), `aiohttp.ClientSession` | cache + fetch | `services/cache.py` (existing) |
| `RemoteResponseResolver` | `aiohttp.ClientSession`, `AuthContext.resolve_for()` | fetch + auth headers | mirror pattern of `services/forwarder.py:36` |
| `api/handlers.FormAPIHandler` | `AuthContext` constructor | request → kwarg | extends existing handlers |
| `controls/builtin.py` | `register_field_control()` | one call per new type | `controls/registry.py:70` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AuthContext`~~ — does **not exist** today. Phase 3 Module 17 introduces
  `parrot_formdesigner.services.auth_context.AuthContext`. **Do not import
  it before Phase 3.** Distinct from existing `AuthConfig` (`core/auth.py`).
- ~~`OptionsLoader`~~ — does **not exist** today. Phase 3 Module 18 introduces
  `parrot_formdesigner.services.options_loader.OptionsLoader`.
- ~~`RemoteResponseResolver`~~ / ~~`RemoteResponseSpec`~~ / ~~`RemoteResponseResult`~~
  — do **not exist** today. Phase 3 Module 19 introduces them under
  `parrot_formdesigner.services.remote_response_resolver`.
- ~~`FieldRenderer` protocol~~ / ~~`FallbackRenderer` class~~ —
  do **not exist** today. Phase 1 Module 1 introduces them under
  `parrot_formdesigner.renderers.base`.
- ~~`RenderWarning`~~ — does **not exist** today. Phase 1 Module 8
  introduces it under `parrot_formdesigner.core.schema`.
- ~~`OptionsSource.http_method`~~ / ~~`OptionsSource.auth_ref`~~ — not on
  the model today. Phase 2 Module 11 adds them.
- ~~`OptionsSource.value_column`~~ / ~~`OptionsSource.label_column`~~ —
  these names do **NOT exist** and must **NOT** be introduced. The
  existing model uses `value_field` / `label_field`. Keep those names.
- ~~`FieldConstraints.scale_min` / `scale_max` / `scale_step` / `anchor_labels`~~
  — not on the model today. Phase 2 Module 10 adds them.
- ~~`FieldType.IMAGE_DROPZONE`~~ / ~~`FieldType.COLOR_PICKER`~~ — do **NOT**
  add these as enum values. Image dropzone is `FieldType.IMAGE` +
  `meta.render_as="dropzone"`; color picker is `FieldType.COLOR` +
  `meta.render_as="picker"`.
- ~~Plugin entry points (`parrot_formdesigner.field_types`)~~ — rejected
  in brainstorm. Field types remain a closed enum owned by this package.
- ~~`pycountry` is already a dep~~ — it is **not**. Module 16 adds it.
- ~~`requests` / `httpx`~~ — forbidden by project rules. Use `aiohttp` only.
- ~~Memoising `REMOTE_RESPONSE` responses across submissions~~ — resolved
  in brainstorm as **retry every time**. Do not introduce a cache here.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Async everywhere.** `OptionsLoader.fetch()`, `RemoteResponseResolver.resolve()`,
  every new `FieldRenderer` callable, and every validator branch is
  `async def`. No `requests` / `httpx` / blocking I/O.
- **Pydantic for every data structure.** New models use
  `ConfigDict(extra="forbid")` matching the existing
  `FormField` convention (`core/schema.py:45`).
- **Logging via `self.logger`**, not `print`. Each service constructs
  `self.logger = logging.getLogger(__name__)` in `__init__`.
- **aiohttp pattern is `SubmissionForwarder`** (`services/forwarder.py:36`).
  Reuse the `ClientSession` lifecycle + `ClientTimeout(total=...)` shape.
- **Cache via `services/cache.py`** for `OptionsLoader`. Do not introduce a
  new caching primitive.
- **Single-flight in `OptionsLoader`** using an `asyncio.Event` per
  in-flight key. Concurrent callers `await` the same Event.
- **Registry registration in renderer `__init__`** — each renderer
  populates its `_registry` dict during `__init__` (not at module import
  time), so subclasses can override before any render call.
- **FieldRenderer dispatch is `_registry.get(field.field_type, self._fallback)`** —
  always supply a fallback; never let a `KeyError` propagate.

### Renderer Coverage & Fallback Policy

Renderers that cannot natively express a new `FieldType` MUST:
1. Register a `FallbackRenderer` instance for that type in their `_registry`.
2. The fallback emits a renderer-appropriate degraded representation
   (e.g. PDF: a labelled empty box; XForms: a `<xf:input>` with a help note;
   Telegram: WebApp mode redirect; Adaptive Card: a `TextBlock` placeholder).
3. The fallback appends a `RenderWarning` to the `RenderedForm.warnings`
   list — never silently swallows. The warning must include `field_id`,
   `field_type`, `renderer`, and a human-readable `reason`.

The coverage matrix in §3 Module 13 is the authoritative spec for which
pairs are native vs fallback.

### Data Shapes for New Field Types (validator/storage)

| FieldType | Submitted shape | Storage notes |
|---|---|---|
| `SIGNATURE` | `{"svg": str, "png": str}` | SVG is canonical strokes; PNG is preview/embed. Both MIME types validated. |
| `DYNAMIC_SELECT` | `str` (selected option's `value`) | Same shape as `SELECT`. |
| `TRANSFER_LIST` | `list[str]` | Same shape as `MULTI_SELECT`. |
| `REMOTE_RESPONSE` | Whatever the API returns | Optionally validated against `RemoteResponseSpec.response_schema`. |
| `AVAILABILITY` | `list[{"start": datetime, "end": datetime}]` | Discrete slots only — no RRULE. |
| `LOCATION` | `str` (ISO 3166 alpha-2, e.g. `"ES"`) | Validated against `pycountry`. |
| `TAGS` | `list[str]` | Accept comma-string at validation entry; coerce to list. |
| `NPS` | `int 0..10` | Enforce `scale_min=0`, `scale_max=10`. |
| `LIKERT` | `int scale_min..scale_max` | `scale_*` required in `constraints`. |
| `RANKING` | `int 0..scale_max` | Default `scale_max=5` if absent. |

### Known Risks / Gotchas

- **Phase 1 silent regression risk.** Migrating ~20 existing field-type
  branches per renderer is mechanically tedious; a missed branch produces a
  silent fallback. Mitigation: snapshot test every existing fixture across
  every renderer before/after migration; require byte-equal output.
- **`RenderedForm.warnings` default-empty additive field is a Pydantic
  schema change.** Strict equality comparisons (e.g.
  `rendered == RenderedForm(content=..., content_type=...)`) in downstream
  consumer tests may now fail. Mitigation: ship release notes; the field
  defaults to `[]`, so `model_dump(exclude_defaults=True)` is unchanged.
- **`AuthContext` cascade for nested fields.** When a `GROUP` contains a
  `DYNAMIC_SELECT`, the renderer must thread `auth_context` to the nested
  field renderer. The registry dispatch helper takes `auth_context` as a
  kwarg so the cascade is automatic — but each renderer's nested-render
  code path must remember to pass it down. Add an explicit test
  (`test_e2e_authcontext_cascade_into_group`).
- **`OptionsLoader` cache stampede.** Without single-flight, the first
  user to open a form triggers N concurrent fetches when there are N
  `DYNAMIC_SELECT` fields. Single-flight per `(source_ref, auth_ref)` is
  mandatory, not optional.
- **`REMOTE_RESPONSE` re-submission side-effects.** We retry every
  submission. Endpoints with side-effects (e.g. "submit transcript to
  AI for summary, then bill") must be designed for idempotency. The spec
  surfaces this expectation; documentation should warn users.
- **`pycountry` adds ~26 KB to the package.** Acceptable per brainstorm
  decision; offline reference is preferred to a network lookup.
- **JSON Schema extractor backwards compatibility.** Existing extractors
  must continue to round-trip old field types unchanged. New types add
  *additional* mappings; they do not modify existing ones. Verified by
  `test_e2e_backwards_compat_existing_forms`.
- **FEAT-166 (multi-origin) interaction.** The recently-merged multi-origin
  dispatcher (`AbstractFormService`, `FormServiceRegistry`,
  `NetworkninjaFormService`, `DatabaseFormTool`) sits *above* the field-type
  layer. This feature does not touch its files. Verified by running its
  existing test suite unchanged at every merge.
- **Telegram renderer field-type sets.** The existing
  `_INLINE_FIELD_TYPES` and `_WEBAPP_FIELD_TYPES` sets must each gain
  classifications for the 10 new types. Module 7 task must update both.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pycountry` | `>=23.0` | ISO 3166 reference data for `LOCATION` field. |
| `aiohttp` | already pinned | HTTP client for `OptionsLoader` and `RemoteResponseResolver` — reuses existing project dep. |
| `redis.asyncio` | already pinned | Backing store for `services/cache.py` reused by `OptionsLoader`. |
| `pydantic` | `>=2` | New models — already pinned. |

No other new dependencies.

---

## 8. Open Questions

> All questions from the brainstorm are resolved. Listed here as `[x]`
> with the resolved answer for audit trail. Implementation agents must
> treat these as binding decisions.

- [x] `SIGNATURE` storage format — *Resolved in brainstorm*: Both SVG
  stroke path (canonical data) + rendered PNG (preview). Validator accepts
  both MIME types (`image/svg+xml`, `image/png`); submitted value is the
  dict `{"svg": "<path d=...>", "png": "<base64-or-url>"}`.
- [x] `AVAILABILITY` data model — *Resolved in brainstorm*: Discrete slots
  only. Submitted value is `list[{start: datetime, end: datetime}]`. No
  RRULE support in this feature.
- [x] `LOCATION` reference data source — *Resolved in brainstorm*: Adopt
  `pycountry` as a new dependency in
  `packages/parrot-formdesigner/pyproject.toml`. Offline, no network
  dependency at form-render time.
- [x] `FieldRenderer` registry migration backwards compatibility —
  *Resolved in brainstorm*: Keep `render()` signature byte-identical.
  The `FieldRenderer` registry is internal-only (private `_registry`
  attribute on each renderer). External callers see no API change.
- [x] `AuthContext` propagation in nested fields — *Resolved in
  brainstorm*: Cascade. Parent `AuthContext` flows into nested
  `GROUP`/`ARRAY` field rendering and validation without re-resolution.
- [x] `REMOTE_RESPONSE` retry / idempotency policy — *Resolved in
  brainstorm*: Retry on every submission. Callers concerned about
  duplicate side-effects design their endpoints for idempotency (e.g. a
  content-hash `Idempotency-Key` header).
- [x] Fallback policy display — *Resolved in brainstorm*: Explicit
  warnings channel. Add `RenderedForm.warnings: list[RenderWarning] = []`.
  Each degraded (FieldType, renderer) pair appends a warning with
  `field_id`, `field_type`, `renderer`, `reason`.

No unresolved questions remain at spec-time. Should any open question
emerge during `/sdd-task` decomposition or implementation, it must be
added below with an owner and answered before the task it blocks can
proceed.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`. All tasks run sequentially in
  one feature worktree at `.claude/worktrees/feat-167-formdesigner-new-fields/`.
- **Rationale**: The Phase 1 registry migration touches every renderer
  file (`renderers/html5.py`, `adaptive_card.py`, `pdf.py`, `xforms.py`,
  `jsonschema.py`, `telegram/renderer.py`). Phase 2 then adds entries to
  the same `_registry` dicts and to `services/validators.py`,
  `extractors/jsonschema.py`, `extractors/yaml.py`. Parallel worktrees
  would conflict on these central files at every task boundary.
- **Phase 3 sub-parallelism (optional)**: `OptionsLoader` and
  `RemoteResponseResolver` are independent modules with only `AuthContext`
  as a shared dependency. They *could* be implemented in parallel
  sub-worktrees once `AuthContext` lands. With ~3–4 tasks at stake, the
  overhead of a second worktree likely outweighs the speedup — recommend
  sequential within the same worktree unless the implementer prefers
  otherwise.
- **Cross-feature dependencies**: None. FEAT-166 (multi-origin) is
  already merged and operates above the field-type layer. No in-flight
  specs touch `packages/parrot-formdesigner/`.
- **Base branch**: `dev` (this is a `feature`, not a `hotfix`).
- **Worktree creation** (run from main repo working tree on `dev`):
  ```bash
  git worktree add -b feat-167-formdesigner-new-fields \
    .claude/worktrees/feat-167-formdesigner-new-fields HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-13 | jesuslara | Initial draft from `formdesigner-new-fields.brainstorm.md` (Option A). All 7 brainstorm open questions resolved and carried forward. |
