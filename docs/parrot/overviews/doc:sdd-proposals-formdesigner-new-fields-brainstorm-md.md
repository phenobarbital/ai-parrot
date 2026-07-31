---
type: Wiki Overview
title: 'Brainstorm: FormDesigner — New Field Types (Shadcn-Forms compatible)'
id: doc:sdd-proposals-formdesigner-new-fields-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The current `parrot-formdesigner` package supports a fixed set of 20 primitive
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: FormDesigner — New Field Types (Shadcn-Forms compatible)

**Date**: 2026-05-13
**Author**: jesuslara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

The current `parrot-formdesigner` package supports a fixed set of 20 primitive
`FieldType` values (`text`, `select`, `file`, `image`, …). These cover basic
inputs but cannot express the richer interactions that modern web UIs
(specifically shadcn-form patterns) routinely need: signature capture, drag-and-drop
image dropzones, transfer lists, ranking scales (Likert / NPS / star ratings),
location combobox, tags input, availability picker, and data-driven fields
whose options or values are resolved at runtime against an external API
(dynamic select, remote response).

Today, the only escape valve is the free-form `FormField.meta` dict, which
forces every renderer to parse meta keys independently and loses semantic
intent in the schema (an NPS score is indistinguishable from any other
integer). Two pieces of plumbing are also missing entirely:

1. **`OptionsSource` runtime** — the model exists at
   `packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py:30`
   but no service actually fetches and caches options against an API.
2. **Per-form auth context** for fields that call out to authenticated APIs
   (Dynamic Select, Remote Response) — `AuthConfig` is a *schema-level*
   declaration; there is no runtime carrier for the resolved token across
   the call stack.

This brainstorm scopes the **entire backend** change inside
`packages/parrot-formdesigner/` to add these field types, their validators,
their extractors, all four output renderers, and the supporting runtime
services. The UI (separate repository) is explicitly out of scope and will
be specced as a follow-up once the backend lands.

## Constraints & Requirements

- **Backend only**: changes are limited to `packages/parrot-formdesigner/`.
  UI lives in a separate repo and will consume this backend's JSON Schema +
  controls registry output.
- **Async-first**: every new service must run inside the existing asyncio
  event loop using `aiohttp` (per CLAUDE.md). No blocking I/O.
- **Pydantic models for every data structure**, `extra="forbid"` consistent
  with `FormField` at `core/schema.py:45`.
- **No secrets in the form schema**: per-form auth context is resolved at
  submission/render time from an out-of-band source (request context, secret
  store). `AuthConfig` continues to hold only declarative references.
- **Renderer coverage**: every new `FieldType` must round-trip through JSON
  Schema (extractor + renderer) and HTML5. Adaptive Card / PDF / XForms use
  best-effort fallbacks for types they cannot natively express.
- **Backwards compatibility**: existing forms (schemas already persisted in
  PostgreSQL via `services/storage.py`) must continue to load, validate, and
  render without changes. New `FieldType` values are additive only.
- **FEAT-166 (multi-origin) safety**: this feature must not regress the
  newly-merged multi-origin dispatcher. The new field types are additive at
  the schema layer; the dispatcher is unaffected.
- **Testability**: each new type ships with a unit test (validator coercion)
  and a round-trip integration test (extractor → schema → renderer).
- **Cache-friendly**: `OptionsLoader` must reuse `services/cache.py`
  (in-memory + Redis TTL) so dynamic options do not stampede external APIs.

---

## Options Explored

### Option A: Hybrid type model + per-renderer registry + new runtime services

This option matches the user's stated direction. Three layers of change:

**1. Schema layer (additive).** Extend `FieldType` with **10 new enum values**
for shapes that are genuinely new: `SIGNATURE`, `DYNAMIC_SELECT`,
`TRANSFER_LIST`, `REMOTE_RESPONSE`, `AVAILABILITY`, `LOCATION`, `TAGS`, `NPS`,
`LIKERT`, `RANKING`. Two components are variants of existing types and stay
in `meta`: image dropzone is `IMAGE` + `meta.render_as="dropzone"`; color
picker is `COLOR` + `meta.render_as="picker"`. `FieldConstraints` gains
scale-specific fields (`scale_min`, `scale_max`, `scale_step`, `anchor_labels:
dict[int, LocalizedString]`) used by the ranking trio. `OptionsSource` gains
`http_method`, `auth_ref`, and explicit `value_column` / `label_column` to
support Dynamic Select.

**2. Renderer layer (refactor + extend).** Introduce a
`FieldRenderer` protocol per output target (HTML5, Adaptive Card, PDF,
XForms, JSON Schema). Each renderer keeps a `dict[FieldType, FieldRenderer]`
registry. **Migrate all 20 existing types** plus the 10 new types into the
registry, so the if/elif chains in `renderers/html5.py:217`,
`renderers/adaptive_card.py:591`, `renderers/pdf.py:237`, and
`renderers/xforms.py` disappear in favour of a single dispatch. Unsupported
(FieldType, renderer) pairs fall back to a degraded representation (e.g.
PDF renders `SIGNATURE` as a labeled empty box; `DYNAMIC_SELECT` renders as
a text input in PDF with the source URL annotated). The fallback policy is
codified in a `FallbackRenderer` per renderer.

**3. Runtime services layer (new).** Three new services under
`packages/parrot-formdesigner/src/parrot_formdesigner/services/`:

- `auth_context.py` — `AuthContext` Pydantic model carrying resolved
  credentials (`scheme`, `token`, `headers`, `claims`). Constructed by the
  aiohttp request handler and passed explicitly to downstream services.
  Distinct from `AuthConfig` (which is declarative, lives in the schema).
- `options_loader.py` — `OptionsLoader` service. Given an `OptionsSource` +
  `AuthContext`, fetches via `aiohttp.ClientSession`, normalises rows to
  `list[FieldOption]` using `value_column`/`label_column`, and caches via
  `services/cache.py` for `cache_ttl_seconds`. Reused by both `SELECT`
  (when `options_source` is set) and `DYNAMIC_SELECT`.
- `remote_response_resolver.py` — `RemoteResponseResolver` service. Mirrors
  `SubmissionForwarder` (`services/forwarder.py:36`). Given a
  `RemoteResponseSpec` (URL + method + content + optional prompt) and an
  `AuthContext`, calls the API and returns the response as the field's value.
  Invoked before submission by the form runtime, not by the user typing.

Validation lives in `services/validators.py:205`, extended with one branch
per new type. Extractors (`extractors/jsonschema.py`, `extractors/yaml.py`)
gain reverse-mapping for new types. The controls registry
(`controls/registry.py:70`) auto-seeds each new type via
`controls/builtin.py`.

Shipping plan: **three internal phases inside one feature**:

- **Phase 1** — `FieldRenderer` protocol + registry + migrate existing 20 types.
  No behaviour change; pure refactor under existing tests.
- **Phase 2** — Schema additions (10 new `FieldType` values, scale constraints,
  extended `OptionsSource`), validators, extractors, controls registry seed,
  per-type renderer implementations across HTML5/JSON Schema first, then
  Adaptive Card / PDF / XForms with fallbacks.
- **Phase 3** — Runtime services (`AuthContext`, `OptionsLoader`,
  `RemoteResponseResolver`) + handler wiring + integration tests against a
  mock aiohttp test server.

✅ **Pros:**
- Matches the user's decisions exactly (verified through Round 1+2 Q&A).
- Single dispatch pattern across all renderers — no "two patterns" footprint.
- Each new field type has explicit, greppable semantics (`FieldType.NPS`,
  not `meta.render_as=="nps"`); downstream analytics / submission
  forwarders can branch on type meaningfully.
- `OptionsLoader` is reusable: today's static `SELECT` + `options_source`
  starts working automatically, even without `DYNAMIC_SELECT`.
- Phasing means Phase 1 can merge independently as a no-op refactor with
  full regression coverage, de-risking Phases 2 and 3.

❌ **Cons:**
- Large surface area: ~10 enum additions × 5 renderers + 4 renderer
  refactors + 3 new services + validator/extractor changes. Phase 1 alone
  touches every renderer file.
- New `FieldRenderer` protocol is a new abstraction every contributor must
  learn; if-elif is duck-simple to grep.
- Best-effort fallback for unsupported (FieldType, renderer) pairs means
  PDF/XForms output for `SIGNATURE`/`DYNAMIC_SELECT`/`REMOTE_RESPONSE` is
  degraded — users may be surprised. We need clear documentation per type
  declaring which renderers fully support it.

📊 **Effort:** High (estimated 25–35 SDD tasks across three phases).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | HTTP client for `OptionsLoader` and `RemoteResponseResolver` | Already a project dep; pattern in `services/forwarder.py:36` |
| `pydantic` (>=2) | All new data models (`AuthContext`, `RemoteResponseSpec`, extended `OptionsSource`, extended `FieldConstraints`) | Already pinned in `pyproject.toml`; consistent with `core/schema.py` `extra="forbid"` |
| `redis.asyncio` | Backing store for `OptionsLoader` TTL cache | Already used in `services/cache.py` |
| `pycountry` (NEW) | Reference data for `LOCATION` field (ISO 3166 country codes + names) | ~26 KB; well-maintained. Adopted (see Open Questions). Added to `packages/parrot-formdesigner/pyproject.toml` in Phase 2. |

🔗 **Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/forwarder.py:36` — `SubmissionForwarder` is the template for `RemoteResponseResolver` (aiohttp session, timeout, auth header resolution).
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/cache.py` — in-memory + Redis TTL cache for `OptionsLoader`.
- `packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py:70` — `register_field_control()` is the toolbar registration API; one call per new type seeds the UI catalog.
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/auth.py` — existing `AuthConfig.resolve()` is the schema-side analogue; `AuthContext` is the runtime counterpart.
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py:205` — existing dispatch table is the pattern Phase 2 validators slot into.

---

### Option B: Meta-only extension (no new `FieldType` values)

Keep `FieldType` frozen at its current 20 values. Every new component is
expressed as an existing type + a `meta.render_as` discriminator:
`SIGNATURE` = `IMAGE` + `meta.render_as="signature"`; `NPS` = `INTEGER` +
`meta.render_as="nps"` + `meta.scale={...}`; `DYNAMIC_SELECT` = `SELECT` +
existing `options_source`; `TRANSFER_LIST` = `MULTI_SELECT` +
`meta.render_as="transfer"`; etc. Each renderer learns to read
`meta.render_as` and switch on it; validators do the same. No enum changes.

✅ **Pros:**
- Smallest schema change. Existing serialized forms are unaffected. Tooling
  that branches on `FieldType` keeps working unchanged.
- No registry refactor strictly necessary — renderers can keep if/elif on
  `FieldType` and add a nested switch on `meta.render_as`.
- Easy to retrofit: third parties can extend their forms with custom
  `meta.render_as` values without modifying the package.

❌ **Cons:**
- Loses semantic clarity. `INTEGER` and `NPS` are the same type in the
  schema; analytics, submission forwarders, and downstream services cannot
  distinguish them without parsing `meta`.
- Validation rules buried in `meta` are typo-prone — there is no Pydantic
  enforcement that `meta.scale_min` exists when `meta.render_as="nps"`.
- Renderer dispatch becomes a two-level switch (`FieldType` then
  `meta.render_as`); the if/elif chains grow rather than shrink.
- Controls registry must invent synthetic keys for the toolbar — there is no
  natural `FieldType` to register against.

📊 **Effort:** Medium-low for the schema; medium for the renderers (every
renderer gets a second dispatch layer).

📦 **Libraries / Tools:** Same as Option A minus the registry; no new deps.

🔗 **Existing Code to Reuse:** Same as Option A.

---

### Option C: Full plugin model (entry-point-driven field types)

Move every field type — existing 20 plus new 10 — out of the enum entirely
and into a plugin registry. `FieldType` becomes a string newtype rather than
an enum. Each type is declared by an `AbstractFieldType` class registered
via Python entry points (`pyproject.toml: [project.entry-points.
"parrot_formdesigner.field_types"]`) or an in-process decorator. The class
owns its validator, renderer fns per output, JSON Schema mapping, YAML key,
and controls metadata. Adding a new type means writing one self-contained
class; no core enum or renderer changes.

✅ **Pros:**
- Maximum extensibility. Third parties (or other internal packages) can
  ship custom field types without forking `parrot-formdesigner`.
- Single-responsibility per field type: one class owns everything about
  `SIGNATURE`, including its renderer fns and validation.
- Cleanest long-term home if the field-type surface continues to grow.

❌ **Cons:**
- Largest refactor by far. Every existing call site that compares against
  `FieldType.X` (validators, renderers, extractors, controls registry,
  tests) must be rewritten. High regression risk.
- `FieldType` as a string newtype weakens IDE/type-checker support
  (`field.field_type == "signature"` vs `FieldType.SIGNATURE`).
- Entry-point discovery has subtle import-order and packaging pitfalls;
  introduces a runtime dependency on a registry being populated before any
  form is loaded.
- Way out of proportion to the immediate need. The new types are a known,
  bounded list; we don't need third-party extensibility today.

📊 **Effort:** Very High (estimated 50+ tasks; likely 2–3 features worth).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `importlib.metadata` (stdlib) | Entry-point discovery | No extra dep |

🔗 **Existing Code to Reuse:** Most existing code is rewritten, not reused.

---

## Recommendation

**Option A** is recommended because:

1. **It matches every architectural choice the user already endorsed** in
   the discovery rounds: hybrid type model (new `FieldType` for genuinely
   new shapes, `meta` for variants of existing types), per-renderer
   registry with full migration of existing types, explicit `AuthContext`
   passed as a kwarg, distinct enum values for `NPS`/`LIKERT`/`RANKING`,
   `FieldConstraints` extension for scale config, and shipping in three
   internal phases.
2. **Phase 1 de-risks Phases 2 and 3.** The registry migration is a pure
   refactor under existing tests — if it regresses, we catch it before any
   new field type lands. Phases 2 and 3 then build on a clean foundation.
3. **It preserves semantic clarity** where it matters. `FieldType.NPS` and
   `FieldType.LIKERT` are meaningful to downstream consumers; analytics
   pipelines, submission forwarders, and (eventually) the separate UI repo
   all benefit from typed enum values rather than meta-dict introspection.
4. **It avoids over-engineering.** Option C's plugin model is what we'd
   want if third parties were shipping their own field types — they aren't,
   and the maintenance burden of entry-point discovery dwarfs the actual
   problem. Option B trades a smaller schema change for a worse runtime
   model and is rejected on the same grounds.

The honest trade-off accepted: Phase 1 touches every renderer and is a
sizeable refactor with no user-visible payoff on its own. We pay that cost
upfront for a cleaner foundation. The fallback policy for unsupported
(FieldType, renderer) pairs adds documentation burden — each new type must
declare which renderers fully support it vs degrade.

---

## Feature Description

### User-Facing Behavior

A form author (today: a Python/JSON Schema writer; soon: the UI repo
consuming the controls registry) gains 10 new `FieldType` values:

| `FieldType` | Purpose | Storage shape |
|---|---|---|
| `SIGNATURE` | Capture a handwritten signature | Image blob (PNG) + optional SVG stroke path |
| `DYNAMIC_SELECT` | Single-select whose options come from an authenticated API | Single string (selected option's `value`) |
| `TRANSFER_LIST` | Multi-select with explicit "available" / "selected" lists | `list[str]` (same shape as `MULTI_SELECT`) |
| `REMOTE_RESPONSE` | Field whose value is produced by an API call against user-supplied content | Whatever the API returns (typed by `RemoteResponseSpec.response_schema`) |
| `AVAILABILITY` | Calendar-driven date/time slot picker | `list[{start: datetime, end: datetime}]` |
| `LOCATION` | Country/region combobox with flag + dial-code metadata | ISO 3166 alpha-2 country code (e.g. `"ES"`) |
| `TAGS` | Free-form list of short string tokens | `list[str]` |
| `NPS` | Net Promoter Score (0–10 with red→green gradient) | `int 0..10` |
| `LIKERT` | Labeled agreement scale (Strongly Disagree → Strongly Agree) | `int` within `scale_min..scale_max` |
| `RANKING` | Star rating (0–N stars, configurable max) | `int 0..scale_max` |

Two visual variants are expressed via `meta.render_as` on existing types:

- `IMAGE` + `meta.render_as="dropzone"` — drag-and-drop image upload UI.
- `COLOR` + `meta.render_as="picker"` — full color picker (palette + hex
  input) rather than the default HTML5 `<input type="color">`.

For authoring **Dynamic Select**, the author writes:

```yaml
- field_id: assignee
  field_type: dynamic_select
  label: Assignee
  options_source:
    source_type: endpoint
    source_ref: https://api.example.com/users
    http_method: GET
    value_column: id
    label_column: full_name
    auth_ref: TENANT_X_JWT          # resolved at runtime via AuthContext
    cache_ttl_seconds: 300
```

For authoring **Remote Response**, the author writes:

```yaml
- field_id: ai_summary
  field_type: remote_response
  label: AI-generated summary
  meta:
    content_field: raw_text         # other field whose value is sent
    prompt: "Summarise the following text in two sentences."
    endpoint: https://api.example.com/summarise
    http_method: POST
    auth_ref: TENANT_X_JWT
```

### Internal Behavior

**Schema → validation flow** (form submission path):

1. The aiohttp handler receives a submission and constructs an
   `AuthContext` from the inbound request (header, session, or middleware).
2. `FormValidator` (`services/validators.py`) iterates fields:
   - For new types, the per-type validator coerces the submitted value
     (e.g. `NPS` clamps to 0–10, `SIGNATURE` validates MIME type + size).
   - For `REMOTE_RESPONSE` fields, the validator calls
     `RemoteResponseResolver.resolve(field, content, auth_context)` and
     stores the API's response as the field's submitted value.
3. Validated payload is forwarded via existing `SubmissionForwarder`.

**Schema → render flow** (form render path):

1. The aiohttp handler constructs an `AuthContext` from the request.
2. The chosen renderer (HTML5 / Adaptive Card / PDF / XForms / JSON Schema)
   iterates fields, dispatching each through its `FieldRenderer` registry.
3. For fields with an `OptionsSource`, the renderer asks `OptionsLoader.
   fetch(options_source, auth_context)` — cached by `cache_ttl_seconds`.
4. Renderers fall back to a degraded representation for (FieldType,
   renderer) pairs they cannot natively express, emitting a placeholder +
   warning metadata that the host can surface to the user.

**Controls registry**: each new `FieldType` self-registers via
`register_field_control()` in `controls/builtin.py`, so the
`GET /api/v1/form-controls` endpoint surfaces them to authoring tools
(including the future UI) automatically.

### Edge Cases & Error Handling

- **`AuthContext` missing** when a field needs one (`DYNAMIC_SELECT`,
  `REMOTE_RESPONSE`, or any `OptionsSource` with `auth_ref`): the
  loader/resolver raises a typed `AuthContextRequiredError`. Renderers
  surface this as a render warning (do not fail the whole form).
- **`OptionsLoader` fetch failure** (timeout, 5xx, auth rejection): returns
  an empty option list and logs a warning; the field renders with a
  "Options unavailable" placeholder. The schema is not considered invalid.
- **`RemoteResponseResolver` failure**: the submission fails with a
  per-field error message (consistent with existing validation errors). The
  resolver never silently swallows; the form is re-displayed with the user's
  other inputs preserved.
- **`SIGNATURE` size cap**: per-field `max_file_size_bytes` (existing
  constraint at `core/constraints.py:47`) is enforced; default 1 MB.
- **`AVAILABILITY` slot overlap**: validator rejects overlapping
  `(start, end)` slots unless `meta.allow_overlap=True`.
- **`LOCATION` unknown country code**: validator rejects ISO codes not in
  the reference set (whether bundled via `pycountry` or our own table).
- **`NPS`/`LIKERT`/`RANKING` out-of-range submission**: validator clamps to
  `scale_min..scale_max` and emits a field-level warning.
- **PDF rendering of `SIGNATURE` / `DYNAMIC_SELECT` / `REMOTE_RESPONSE`**:
  falls back to a labeled empty box / text input / placeholder respectively.
  `RenderedForm.warnings` carries an entry per degraded field so callers
  can detect lossy rendering.
- **Cache stampede on `OptionsLoader`**: single-flight per (source_ref,
  auth_ref) tuple — concurrent fetches for the same key share one
  in-flight request. Implementation note for Phase 3.
- **Existing forms in the database**: fully unaffected. `FieldType` is an
  additive change; existing rows continue to deserialize unchanged because
  Pydantic enum membership is widened, never narrowed.

---

## Capabilities

### New Capabilities
- `formdesigner-field-renderer-registry`: per-renderer `FieldRenderer`
  protocol + registry, replacing the if/elif dispatch in HTML5, Adaptive
  Card, PDF, XForms, and JSON Schema renderers.
- `formdesigner-new-field-types`: schema additions (10 new `FieldType`
  values, scale-related `FieldConstraints` fields, extended `OptionsSource`)
  plus validators, extractors, and per-type renderer implementations.
- `formdesigner-auth-context`: runtime `AuthContext` model + handler-side
  construction conventions, passed explicitly to downstream services.
- `formdesigner-options-loader`: generic async `OptionsLoader` service with
  TTL caching for `OptionsSource`, used by both static `SELECT` (when
  `options_source` is set) and `DYNAMIC_SELECT`.
- `formdesigner-remote-response`: `RemoteResponseResolver` service +
  `RemoteResponseSpec` schema model, invoked during submission to populate
  `REMOTE_RESPONSE` field values from external APIs.

### Modified Capabilities
- (none — this feature does not change existing capability specs; it adds
  new ones. The renderer registry migration is captured by the new
  `formdesigner-field-renderer-registry` capability rather than amending
  individual renderer specs.)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py:16` | extends | Add 10 new `FieldType` enum values. Additive only. |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py:17` | extends | Add `scale_min`, `scale_max`, `scale_step`, `anchor_labels` to `FieldConstraints`. Optional fields; existing schemas unaffected. |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py:30` | extends | Add `http_method`, `value_column`, `label_column`, `auth_ref` to `OptionsSource`. |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:21` | unchanged interface | `FormField` already has `meta`, `constraints`, `options_source`; no new top-level fields needed. |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py:217` | refactors + extends | If/elif dispatch replaced by `FieldRenderer` registry. New types added. |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py:591` | refactors + extends | Same. Some new types use fallback. |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py:237` | refactors + extends | Same. Most interactive types fall back. |

…(truncated)…
