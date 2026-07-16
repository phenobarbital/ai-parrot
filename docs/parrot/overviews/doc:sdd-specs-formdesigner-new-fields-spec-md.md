---
type: Wiki Overview
title: 'Feature Specification: FormDesigner — New Field Types (Shadcn-Forms compatible)'
id: doc:sdd-specs-formdesigner-new-fields-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: inputs but cannot express the richer interactions that modern web UIs
---

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

…(truncated)…
