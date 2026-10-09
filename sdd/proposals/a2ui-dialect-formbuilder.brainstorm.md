---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [parrot-formdesigner, ai-parrot]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [a2ui, formdesigner, dialect, export, extractor, translator]
---

# Brainstorm: A2UI dialect for parrot-formdesigner (serve, export, and translate FormSchema ⇄ A2UI)

**Date**: 2026-10-10
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

parrot-formdesigner (née "formbuilder") predates ai-parrot's A2UI v1.0 support,
yet the two concepts are nearly identical: a `FormSchema` is served as a JSON
document and a frontend "renderer" turns it into HTML controls. The dialect
that is served today — `GET /forms/{uid}` returns the raw `FormSchema` dump and
`GET /forms/{uid}/schema` returns the `JsonSchemaRenderer` output with `x-*`
extensions — is **not** A2UI, so the existing A2UI renderers (admin UI,
`ssr_html`, `interactive_html`, Adaptive Cards bridge) cannot render a
FormDesigner form natively.

FEAT-544 (merged 2026-09-10, all 8 tasks `done`) already closed the first half
of the gap: `A2UIFormRenderer` lowers a `FormSchema` into a `createSurface`
envelope, `GET /forms/{uid}/render/a2ui` serves it, and `/data` + `/validate`
are dual-wire (legacy JSON **and** A2UI `action` envelopes). What is still
missing — and what this brainstorm scopes — is the **dialect layer around it**:

1. **A flag that makes the main form endpoints speak A2UI.** Today a client
   has to know about `/render/a2ui`. Consumers that fetch `/forms/{uid}` or
   `/forms/{uid}/schema` keep getting the legacy dialect with no way to opt
   in, and a form cannot declare "serve me as A2UI by default".
2. **A bulk export.** There is no way to export every form of a tenant as
   A2UI surfaces (library, API or CLI) — only one form at a time via HTTP.
3. **A translator from the legacy JSON-Schema dialect to A2UI.** Consumers
   such as Fieldsync hold the `JsonSchemaRenderer` output (with `x-field-type`,
   `x-section`, `x-options`, …), not a `FormSchema`. `JsonSchemaExtractor`
   exists but does not read `x-section`/`x-subsection`/`x-placeholder`/
   `x-read-only`, so a JSON-Schema → FormSchema → A2UI pipeline would silently
   flatten sections today.
4. **The reverse direction: A2UI surface → `FormSchema`.** Nothing exists.
   An A2UI form authored elsewhere (an agent, another A2UI producer, a
   hand-written surface) cannot become a FormDesigner form.

The legacy dialect **must not change**: Fieldsync and other consumers keep
reading `FormSchema` JSON / JSON Schema exactly as today. The A2UI dialect is
additive and opt-in.

**Who is affected**: frontend teams that already have an A2UI renderer (they
get FormDesigner forms for free), Fieldsync (must see zero change), operators
migrating forms between systems (bulk export, A2UI import), and agents that
author forms as A2UI surfaces.

## Constraints & Requirements

- **Zero change for legacy callers.** Default dialect of every existing and
  new form stays `json_schema`; `GET /forms/{uid}` and `/schema` return
  byte-for-byte what they return today unless the caller or the form opts in.
- **Reuse FEAT-544, do not fork it.** `A2UIFormRenderer`, the `FIELD_LOWERING`
  table, `api/a2ui_wire.py`, the `form-{uid}` surface id and the `parrot_*`
  extension vocabulary are the single source of A2UI truth. The dialect layer
  calls them; it never re-implements lowering.
- **ai-parrot stays an optional extra** for parrot-formdesigner (`[ai-parrot]`
  / `[a2ui]` extras, `ai-parrot>=1.2.1`). Every new module that touches
  `parrot.outputs.a2ui` imports it lazily; when the extra is missing the
  dialect flag is rejected with a clear 415/501, exactly like the render
  dispatcher does today.
- **Produced surfaces validate** with `validate_envelope(origin=ProducerOrigin.TOOL)`
  and `validate_message()`; no `Form` catalog component (dialect spec G6).
- **Reverse extraction is lossy-with-warnings, never silent.** Every dropped
  component, inferred type or guessed section is reported in the result;
  the API import still creates the form (user decision, Round 2).
- **Both translators are deterministic and testable as round-trips**:
  `FormSchema → A2UI → FormSchema` must be identity on the fields the surface
  can express (strict mode), and `FormSchema → JSON Schema → FormSchema → A2UI`
  must preserve sections/subsections once the extractor gaps are fixed.
- Tenant isolation rules of `FormRegistry` apply to bulk export (never
  aggregate across tenants in one call; iterate `list_tenants()`).
- Multitenant security: the dialect switch must not bypass
  `enforce_membership_unless_public` or the `onBeforeOpen` lifecycle hook.

---

## Options Explored

### Option A: Dialect layer over FEAT-544 (negotiate, export, extract — all through `FormSchema`)

Treat `FormSchema` as the pivot and A2UI as a **dialect** of it, exactly as
JSON Schema already is. Four pieces, all inside parrot-formdesigner:

1. **Persisted flag + request negotiation.** New `FormSchema.dialect`
   (`FormDialect` enum: `json_schema` default, `a2ui`), stored in `schema_json`,
   patchable via the existing `PATCH /forms/{uid}` deep-merge. `GET /forms/{uid}`
   and `GET /forms/{uid}/schema` resolve the *effective* dialect as
   `?dialect=` query > `Accept: application/a2ui+json` > `form.dialect`, and
   when it is `a2ui` they delegate to the registered `"a2ui"` renderer (same
   object the render dispatcher uses) and answer `application/a2ui+json`.
   `?dialect=json_schema` always forces the legacy path, so a form flagged
   `a2ui` is still reachable by Fieldsync.
2. **Export service + API + CLI.** `A2UIExportService` (services/) wraps
   registry + renderer: `export_form()`, `export_tenant()` as an async
   iterator of `ExportedSurface(form_uid, form_id, version, envelope, warnings)`.
   `GET /forms?dialect=a2ui` adds the surface to each list entry;
   `POST /forms/export` (body: optional `form_uids`, `published_only`) streams
   NDJSON of envelopes. CLI `parrot formdesigner export --tenant X --out DIR`
   registered in `parrot.cli` `_lazy_commands` and shipped in
   parrot-formdesigner (`parrot_formdesigner/cli.py`, click group).
3. **JSON-Schema → A2UI by composition.** A thin
   `translate_jsonschema_to_a2ui(schema_dict, *, form_uid, tenant, …)` helper
   that runs `JsonSchemaExtractor.extract()` then `A2UIFormRenderer.render()`.
   The real work is **closing the extractor's fidelity gaps** so the
   composition is faithful: read `x-section`/`x-subsection` (rebuild the
   section tree instead of one flat `"fields"` section), `x-placeholder`,
   `x-read-only`, `x-options` (labels, not only `enum` values),
   `x-section-depends-on`/`x-subsection-depends-on`.
4. **A2UI → FormSchema extractor.** `A2UIExtractor` in `extractors/`
   (same shape as `JsonSchemaExtractor`): accepts a `createSurface` envelope
   (dict / JSON / `CreateSurface`), walks from `root`, and returns
   `ExtractedForm(form, warnings, dropped, mode)`. Two modes chosen
   automatically: **strict** when the root carries `parrot_variant: "form"`
   (identity, types, sections come from `parrot_*` extensions; a missing
   extension is a warning, never a guess), **heuristic** for any Basic
   surface (Card → section, nested Column/Row inside a Card → subsection,
   `TextField` variant → TEXT/TEXT_AREA/NUMBER/PASSWORD, `CheckBox` →
   BOOLEAN, `ChoicePicker` → SELECT / MULTI_SELECT, `Slider` → NUMBER with
   min/max constraints, `DateTimeInput` → DATE/TIME/DATETIME by
   `enableDate`/`enableTime`, `checks` → `FieldConstraints`, `{"path": …}`
   bindings → `field_id`, submit `Button` → `cancel_allowed`/ignored,
   Image/Video/AudioPlayer/Icon/Divider/List/Modal → dropped with a warning,
   Tabs → one section per TabItem). `POST /forms` becomes dual-wire: a body
   that is a v1.0 `createSurface` envelope (or `Content-Type:
   application/a2ui+json`) is imported through the extractor and registered;
   the legacy `{"prompt": …}` body is untouched.

✅ **Pros:**
- One lowering table, one extension vocabulary, one wire module — everything
  FEAT-544 fixed stays fixed here.
- Legacy dialect provably untouched (default + explicit `?dialect=json_schema`).
- The extractor gap fixes improve *every* JSON-Schema consumer, not only A2UI.
- Export and import are symmetric, so round-trip tests are cheap and strong.
- CLI reuses the existing `parrot` lazy-group mechanism; no new entry point.

❌ **Cons:**
- Fidelity of JSON-Schema → A2UI is capped by what `x-*` extensions carry;
  anything the JSON Schema dialect never encoded (style, snippets, lifecycle
  events) cannot be recovered.
- Heuristic extraction of generic surfaces is inherently lossy; needs honest
  documentation of what it infers.
- `get_form`/`get_schema` grow a branch each (lifecycle semantics for
  `onSchemaLoaded.schema_overrides` on the A2UI path need a decision).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ai-parrot>=1.2.1` (optional extra) | `parrot.outputs.a2ui` models, `deserialize`, `validate_envelope`, catalog | already the FEAT-544 pin; stays optional |
| `pydantic` v2 | `FormDialect`, `ExportedSurface`, `ExtractedForm` models | already a dependency |
| `click` | `parrot formdesigner` group | already used by `parrot.cli` |
| `aiohttp` | NDJSON streaming for `POST /forms/export` | already the HTTP stack |

🔗 **Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py` — `A2UIFormRenderer`, `FIELD_LOWERING`, `field_pointer`/`field_id_from_pointer_token`, `_extensions`.
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` — `get_renderer("a2ui")`, `supported_formats()`, the optional-extra seeding pattern.
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py` — `is_a2ui_request`, `a2ui_response`, `_a2ui_ns` lazy import pattern, `A2UI_MAX_BODY_BYTES`.
- `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py` — `JsonSchemaExtractor` (shape to mirror; gaps to fix).
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py` — `FormRegistry.get/list_forms/list_tenants/register`.
- `packages/ai-parrot/src/parrot/cli/__init__.py` — `cli._lazy_commands` registration.

---

### Option B: Direct wire-to-wire translators (JSON Schema ⇄ A2UI without `FormSchema`)

Two standalone modules that operate on dicts: `jsonschema_to_a2ui()` reads the
JSON Schema dialect (`x-field-type`, `x-section`, …) and emits Basic components
directly; `a2ui_to_jsonschema()` does the inverse. `FormSchema` is only touched
by a third adapter when something must be persisted. The flag and export pieces
are the same as Option A but call these translators.

✅ **Pros:**
- Works for consumers that only ever hold the JSON Schema document; no
  `FormSchema` reconstruction step and no extractor fidelity concerns.
- Translator is pure and side-effect free; trivially unit-testable with
  fixture JSON.

❌ **Cons:**
- **Second lowering table.** `FieldType` → Basic primitive mapping would live
  twice (FEAT-544 `FIELD_LOWERING` and the new translator) and drift.
- The `x-*` extensions are a looser contract than `FormSchema`; the translator
  re-implements type inference that `JsonSchemaExtractor` already has.
- Still needs an A2UI → `FormSchema` path for import, so Option A's extractor
  is built anyway; Option B is strictly more code.
- Round-trip guarantees are weaker (three representations, no pivot).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ai-parrot` (optional) | A2UI models + validation | same as A |
| `jsonschema` | validate the JSON-Schema input before translating | already an optional test extra in formdesigner |

🔗 **Existing Code to Reuse:**
- `renderers/jsonschema.py` — the `x-*` vocabulary to read (`x-field-type`, `x-section`, `x-options`, `x-depends-on`, …).
- `renderers/a2ui.py` — only as a *reference* for the lowering rules (would be duplicated).

---

### Option C (unconventional): Make A2UI the stored dialect

Store the A2UI `createSurface` envelope in `schema_json` (or a sibling
`surface_json` column) as the canonical representation and derive
`FormSchema` on load through the new extractor. Serving A2UI becomes a
pass-through; serving JSON Schema becomes extract + render.

✅ **Pros:**
- The "A2UI-native" promise is literal: what is stored is what A2UI renderers
  consume; no render step on the hot path.
- Forces the extractor to be complete, which benefits import quality.

❌ **Cons:**
- A2UI cannot express everything `FormSchema` carries (persistence config,
  unknown-field policy, lifecycle events, options sources, REST/relation
  specs, snippets, product bindings…). Storing A2UI as canonical would lose
  them or require an ever-growing `parrot_*` side-channel.
- Migration of every stored form, every storage backend (Postgres,
  autonomous storage, Redis cache, form versions) and every tool that reads
  `schema_json` — directly contradicts "do not break Fieldsync".
- Validation (`services/validators.py`) and the whole rule engine operate on
  `FormSchema`; they would run on a derived object.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncpg` | new column / migration | idempotent DDL pattern of `storage.py` |

🔗 **Existing Code to Reuse:**
- `services/storage.py` — `PostgresFormStorage` DDL/upsert (would change).
- `services/form_version.py` — version snapshots (would change).

---

### Option D (unconventional): Browser-side adapter only

Ship a JavaScript adapter in `ai-parrot-visualizations` that converts the
legacy JSON-Schema dialect into an A2UI surface **in the client**, leaving the
backend untouched.

✅ **Pros:**
- Zero backend risk; no new endpoints, no persisted flag.

❌ **Cons:**
- Only helps browsers that load that adapter; `ssr_html`, Adaptive Cards and
  any non-JS A2UI renderer get nothing.
- Duplicates `FIELD_LOWERING` in TypeScript; two sources of truth across
  languages.
- Provides no reverse direction (A2UI → `FormSchema`) and no bulk export,
  so it does not meet the stated scope.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Svelte 5 / TypeScript | adapter in the bundled UI | `packages/ai-parrot-server/ui/` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py` — host renderer.

---

## Recommendation

**Option A** is recommended because:

- It keeps **one lowering table and one extension vocabulary** (FEAT-544's),
  so A2UI output is identical whether a form is rendered via `/render/a2ui`,
  served through the dialect flag, exported in bulk, or produced from a
  JSON-Schema document. Option B would inevitably drift.
- The user's Round-2 decisions map onto it directly: persisted form default +
  per-request override, export through service **and** API **and** CLI,
  JSON-Schema → A2UI by composition, lossy-with-warnings extractor with a
  dual-wire `POST /forms` import.
- Fixing `JsonSchemaExtractor`'s `x-section`/`x-placeholder`/`x-read-only`/
  `x-options` gaps is a small, well-bounded change that pays off beyond this
  feature.
- What we trade off: fidelity of JSON-Schema → A2UI is capped by the `x-*`
  extensions (style/snippets/events are not recoverable from JSON Schema),
  and heuristic extraction of generic surfaces will always need human review.
  Both are acceptable because the legacy path and the strict round-trip path
  remain exact, and the lossy paths report exactly what they lost.

Option C is rejected outright (contradicts the no-break constraint). Option D
does not satisfy the scope.

---

## Feature Description

### User-Facing Behavior

- **Form flag.** A `FormSchema` gains `dialect: "json_schema" | "a2ui"`
  (default `json_schema`). It is visible in `GET /forms/{uid}`, editable with
  `PATCH /forms/{uid}` (`{"dialect": "a2ui"}`) and `PUT`, cloned with the form,
  and carried by version snapshots. Nothing changes for forms that never set
  it.
- **Serving.** For `GET /api/v1/{tenant}/forms/{uid}` and `GET …/schema`:
  - `?dialect=a2ui` or `Accept: application/a2ui+json` → the response is the
    FEAT-544 `createSurface` envelope with `Content-Type: application/a2ui+json`
    (identical to `/render/a2ui`).
  - `?dialect=json_schema` → the legacy body, always, even for a form whose
    stored `dialect` is `a2ui`.
  - no override → the form's stored `dialect` decides.
  - `?dialect=<unknown>` → 400; `a2ui` requested while the `ai-parrot` extra
    is not installed → 415 listing `supported_formats()` (same shape as the
    render dispatcher's 415). The public route (`tenant="public"`) honours the
    same rules; membership enforcement and `onBeforeOpen` run before any
    rendering.
  - `GET /forms` (list) accepts `?dialect=a2ui` and adds a `surface` key to
    every entry (and `warnings` when non-empty); it is capped by the existing
    list pagination/limits.
- **Bulk export.**
  - `POST /api/v1/{tenant}/forms/export` with
    `{"dialect": "a2ui", "form_uids": [...]?, "published_only": bool?}` →
    `application/x-ndjson` stream, one line per form:
    `{"form_uid", "form_id", "version", "envelope", "warnings"}`. Forms that
    fail to render are emitted as `{"form_uid", "error"}` lines, never abort
    the stream.
  - CLI: `parrot formdesigner export --dialect a2ui --tenant <slug>
    [--form-uid …] [--published-only] --out <dir> [--dsn …]` writes one
    `<form_id>-<form_uid>.a2ui.json` per form plus an `export-report.json`
    (counts, warnings, errors). `--dialect json_schema` is accepted for
    symmetry (uses `JsonSchemaRenderer`).
- **JSON-Schema → A2UI.** Library helper
  `translate_jsonschema_to_a2ui(schema: dict, *, form_id, tenant, locale) ->
  RenderedForm`; CLI `parrot formdesigner translate --from json_schema --to a2ui
  <file>`; no HTTP endpoint in v1 (the stored forms already go through
  `FormSchema`).
- **A2UI → FormSchema (import).**
  - Library: `A2UIExtractor().extract(envelope, *, form_id=None, tenant=None)
    -> ExtractedForm` with `.form`, `.warnings`, `.dropped` (component ids +
    reason), `.mode` (`strict` | `heuristic`).
  - `POST /api/v1/{tenant}/forms` with `Content-Type: application/a2ui+json`
    or a body whose top level is `{"version": "v1.0", "createSurface": {...}}`
    → extract, register (persist like the LLM path does), respond 201 with the
    created `FormSchema` and an `import` block `{mode, warnings, dropped}`.
    Legacy `{"prompt": …}` bodies are unchanged.
  - CLI: `parrot formdesigner import <surface.json> --tenant … [--dry-run]`
    prints the `FormSchema` and the import report; without `--dry-run` it
    persists through the registry.

### Internal Behavior

- **Dialect resolution** lives in one helper (`api/dialect.py`):
  `resolve_dialect(request, form) -> FormDialect` applying query > Accept >
  stored, raising the 400/415 cases. `get_form`/`get_schema` call it after
  tenant/membership/`onBeforeOpen`, and when it returns `a2ui` they delegate
  to `get_renderer("a2ui")` with `locale` and `tenant` (exactly what
  `handle_render` does) and return via `a2ui_wire.a2ui_response`-style
  content type. The `onSchemaLoaded` hook still fires on the `/schema` route;
  `schema_overrides` apply only to the JSON-Schema body (A2UI path logs a
  warning if overrides are present — see Open Questions).
- **`A2UIExportService`** (services/) takes `registry: FormRegistry` and
  `renderer: AbstractFormRenderer` (defaults to `get_renderer("a2ui")`);
  `export_tenant(tenant, *, form_uids=None, published_only=False, locale="en")`
  iterates `registry.list_forms(tenant=…)` (after `load_from_storage` when the
  registry is backed by Postgres) and yields `ExportedSurface`. Never crosses
  tenants. The HTTP handler streams it; the CLI builds a registry from a DSN
  (`PostgresFormStorage`) and drains it to files.
- **JSON-Schema composition** is `JsonSchemaExtractor.extract` →
  `A2UIFormRenderer.render`, with the extractor extended to rebuild
  sections/subsections from `x-section`/`x-subsection` metadata, map
  `x-placeholder`, `x-read-only`, `x-options` labels and the
  `x-section-depends-on`/`x-subsection-depends-on` rules.
- **`A2UIExtractor`** parses with `deserialize()` (accepting a dict, str or
  bytes), requires a `createSurface` with a `root` component, and walks the
  component graph. In strict mode `parrot_form_uid/form_id/form_version/
  tenant` seed the `FormSchema` and each input's
  `parrot_field_id/field_type/section_id/subsection_id` drive placement and
  typing (the `FIELD_LOWERING` table is consulted in reverse only to validate
  that the primitive matches the declared `FieldType`). In heuristic mode a
  deterministic rule table maps Basic primitives to `FieldType`, `checks` to
  `FieldConstraints`, bindings to `field_id` (last pointer token, unescaped via
  `field_id_from_pointer_token`) and literal `value`s to `default_value`.
  Unknown/unsupported components are recorded in `dropped` and skipped; a
  surface with no inputs still yields an empty-section form plus a warning.
  Output passes through `resolve_rule_references` like every extractor.
- **CLI** is a click group in `parrot_formdesigner/cli.py`, registered as
  `"formdesigner": "parrot_formdesigner.cli"` in `parrot.cli._lazy_commands`;
  failure to import parrot-formdesigner yields the same "command unavailable"
  behaviour the lazy group already has for optional distributions.

### Edge Cases & Error Handling

- Form stored with `dialect: a2ui` but `ai-parrot` extra missing on the
  server → `GET` without override returns 415 + `supported` list; the admin
  can still fetch it with `?dialect=json_schema`. Setting `dialect: a2ui` via
  PATCH/PUT when the extra is missing is **allowed** (data, not behaviour) but
  logged.
- `Accept: application/a2ui+json` alongside `?dialect=json_schema` → query
  wins (explicit beats negotiated).
- Export of a form whose renderer degrades fields → the surface is still
  emitted with `warnings` (never dropped); a form that raises inside
  `render()` is emitted as an `error` line / listed in the report.
- Import of a surface whose `surfaceId` is `form-<uuid>` and whose
  `parrot_form_uid` already exists in the tenant → 409 unless
  `?overwrite=true` (mirrors `FormRegistry.register(overwrite=…)`).
- Import of a surface with no submit `Button` → allowed, warning
  `no_submit_button`; with a submit `Button` whose `context.submit_url`
  points to another tenant → warning, URL is not persisted (FormDesigner
  regenerates it at render time).
- Duplicate `field_id`s inferred from two components → second one is suffixed
  (`<id>_2`) and reported; `FormSchema`'s own uniqueness validator remains the
  final gate.
- Legacy pre-v1.0 envelopes (`"messageType"`) are accepted through
  `deserialize`'s compat path with its `DeprecationWarning` surfaced as an
  import warning.
- Oversized import bodies are capped with `A2UI_MAX_BODY_BYTES` (413 A2UI
  error), reusing the wire module's constant.

---

## Capabilities

### New Capabilities
- `formdesigner-form-dialect-flag`: `FormSchema.dialect` + request negotiation on `GET /forms/{uid}`, `/schema`, `/forms`.
- `formdesigner-a2ui-export`: `A2UIExportService`, `POST /forms/export` NDJSON stream, `parrot formdesigner export` CLI.
- `formdesigner-jsonschema-to-a2ui`: composition helper + `JsonSchemaExtractor` fidelity fixes (`x-section`, `x-subsection`, `x-placeholder`, `x-read-only`, `x-options`, section-level `depends_on`).
- `formdesigner-a2ui-extractor`: `A2UIExtractor` (strict + heuristic modes), `ExtractedForm` report, dual-wire `POST /forms` import, `parrot formdesigner import|translate` CLI.

### Modified Capabilities
- `a2ui-form-output-renderer` (FEAT-544): consumed, not changed — the renderer becomes the engine behind the dialect flag and the export; `test_a2ui_renderer.py` invariants (surface id, `parrot_*` keys) become the strict-mode extractor's contract.
- `formbuilder-list-created-forms` (FEAT-148): `GET /forms` grows the optional `?dialect=a2ui` enrichment.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot_formdesigner/core/schema.py` (`FormSchema`) | extends | new `dialect: FormDialect` field (default `json_schema`); new enum next to `UnknownFieldsPolicy` |
| `parrot_formdesigner/api/handlers.py` (`get_form`, `get_schema`, `list_forms`, `create_form`) | modifies | dialect branch; dual-wire create; new `export_forms` handler |
| `parrot_formdesigner/api/routes.py` | extends | `POST {tp}/forms/export` route (tenant `required`) |
| `parrot_formdesigner/api/dialect.py` | new | `resolve_dialect`, Accept/query parsing, 400/415 envelopes |
| `parrot_formdesigner/api/a2ui_wire.py` | extends | `is_a2ui_surface_body()` (detect `createSurface` for import) alongside `is_a2ui_request()` |
| `parrot_formdesigner/services/a2ui_export.py` | new | `A2UIExportService`, `ExportedSurface` |
| `parrot_formdesigner/extractors/a2ui.py` + `extractors/__init__.py` | new / extends | `A2UIExtractor`, `ExtractedForm`; lazy `parrot.outputs.a2ui` import |
| `parrot_formdesigner/extractors/jsonschema.py` | modifies | section tree + `x-placeholder`/`x-read-only`/`x-options` fidelity |
| `parrot_formdesigner/cli.py` | new | click group `formdesigner` (export / import / translate) |
| `parrot/cli/__init__.py` (`ai-parrot`) | extends | one `_lazy_commands` entry |
| `packages/parrot-formdesigner/pyproject.toml` | extends | `click` dependency (if not already transitive) |
| `packages/parrot-formdesigner/docs/a2ui-renderer.md` | extends | dialect flag, export, import sections |
| Fieldsync / legacy consumers | none | default dialect unchanged; `?dialect=json_schema` guarantees the legacy body |

No breaking changes. No new mandatory dependencies. No DB migration (the
field lives inside the `schema_json` JSONB document; absent key → default).

---

## Code Context

### User-Provided Code

_None — the user provided a prose description only._

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py:294-345
class A2UIFormRenderer(AbstractFormRenderer):
    RENDERER_NAME: ClassVar[str] = "a2ui"                                   # line 309
    def __init__(self, *, submit_url_template: str = DEFAULT_SUBMIT_URL_TEMPLATE,
                 catalog_id: str | None = None) -> None: ...                 # line 311
    async def render(self, form: FormSchema, style: StyleSchema | None = None, *,
                     locale: str = "en", prefilled: dict[str, Any] | None = None,
                     errors: dict[str, str] | None = None) -> RenderedForm: ...  # line 330
    def _lower_section(...)   # line 507
    def _lower_field(...)     # line 606  (table-driven via FIELD_LOWERING)
    def _lower_checks(...)    # line 727
    def _seed_data_model(...) # line 813

# From renderers/a2ui.py:154-171, 198-262
class A2UIFieldLowering(BaseModel):
    primitive: Literal["TextField", "CheckBox", "ChoicePicker", "Slider", "DateTimeInput", "notice", "hidden"]
    props: dict[str, Any] = Field(default_factory=dict)
    check_functions: tuple[str, ...] = ()
FIELD_LOWERING: dict[FieldType, A2UIFieldLowering]   # covers every FieldType; module-level assert at line 261

# From renderers/a2ui.py:75, 92, 281
def field_pointer(field_id: str) -> str: ...                 # "/answers/<escaped>"
def field_id_from_pointer_token(token: str) -> str: ...
def _extensions(m: Any, **values: Any) -> Any: ...           # ComponentMetadata(extensions=Extensions(values))
# Root Column extensions (line 470-482): parrot_variant="form", parrot_form_uid, parrot_form_id,
#   parrot_form_version, parrot_tenant, parrot_submit_url; surface_id = f"form-{form.form_uid}" (line 484)
# Field extensions (lines 634-642): parrot_field_id, parrot_field_uid, parrot_field_type,
#   parrot_section_id, parrot_subsection_id, parrot_read_only; notices: parrot_role (lines 652, 718, 724)

# From packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py:58-83
class AbstractFormRenderer(ABC):
    @abstractmethod
    async def render(self, form: FormSchema, style: StyleSchema | None = None, *,
                     locale: str = "en", prefilled: dict[str, Any] | None = None,
                     errors: dict[str, str] | None = None) -> RenderedForm: ...

# From packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:401-475
class FormSchema(BaseModel):
    form_uid: uuid.UUID = Field(default_factory=uuid.uuid4)   # line 453
    form_id: str                                             # line 454
    version: str = "1.0"                                     # line 455
    sections: list[FormSection]                              # line 458
    cancel_allowed: bool = True                              # line 460
    created_at: datetime | None = None                       # line 462
    tenant: str | None = None                                # line 463
    metadata: list[FormMetadataField] | None = None          # line 464
    form_type: FormType = FormType.SIMPLE                    # line 467
    published_version: str | None = None                     # line 469
    is_public: bool = False                                  # line 471
    persistence: FormPersistenceConfig | None = None         # line 473
    unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP   # line 475
    def iter_all_fields(self) -> Iterator[FormField]: ...    # line 477
    def iter_fields_recursive(self) -> Iterator[FormField]: ...  # line 490
class UnknownFieldsPolicy(str, Enum): ...                    # line 51 — pattern for the new FormDialect enum
class FormField(BaseModel): ...                              # line 65
class FormSection(BaseModel): ...                            # line 229

# From packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py:16-70
class FieldType(str, Enum): TEXT, TEXT_AREA, NUMBER, INTEGER, BOOLEAN, DATE, DATETIME, TIME, SELECT,
    MULTI_SELECT, FILE, IMAGE, COLOR, URL, EMAIL, PHONE, PASSWORD, HIDDEN, GROUP, ARRAY, SIGNATURE,
    DYNAMIC_SELECT, TRANSFER_LIST, REMOTE_RESPONSE, AVAILABILITY, LOCATION, TAGS, NPS, LIKERT, RANKING,
    REST, AUDIO, FORMULA, SEARCH, MASKED, COLOR_PICKER, EMOJI, CRON, TREE_SELECT, SIGNATURE_PAD,
    CREDIT_CARD, IMAGE_DROPZONE, MULTI_UPLOAD, AI_CAPTURE, PLACE

# From packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py:67-142
class JsonSchemaExtractor:
    def extract(self, schema: dict[str, Any], *, form_id: str | None = None,
                title: str | None = None) -> FormSchema: ...   # line 86 — builds ONE FormSection("fields")
    def _property_to_field(self, *, name, prop, required, root_schema) -> FormField: ...  # line 176
    def _map_type(self, prop: dict[str, Any]) -> FieldType: ...   # line 390 (reads x-field-type at 411)
    def _extract_constraints(self, prop) -> FieldConstraints: ... # line 437
# Reads: x-parrot-rest (206), x-options-source (239), x-relation (253), x-depends-on (291),
#   x-post-depends (300), x-content-type (315), x-accept-content-types (322), x-answer-envelope (336).
# Does NOT read: x-section, x-subsection, x-section-depends-on, x-subsection-depends-on,
#   x-placeholder, x-read-only, x-options (labels).  ← fidelity gaps to close.

# From packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py
class JsonSchemaRenderer(AbstractFormRenderer): ...          # line 301
# Emits: x-field-type (359, 493), x-section / x-subsection (432-443), x-section-depends-on (435, 446),
#   x-subsection-depends-on (437), x-options-source (552, 588), x-relation (559), x-options (564, 577),
#   x-depends-on (609), x-post-depends (613), x-placeholder (617), x-read-only (622),
#   x-parrot-rest (649), x-content-type (674), x-accept-content-types (676), x-answer-envelope (678)

# From packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
class FormAPIHandler:
    async def list_forms(self, request) -> web.Response: ...     # line 724
    async def get_form(self, request) -> web.Response: ...       # line 847 — model_dump(mode="json", exclude_none=True) at 878
    async def get_schema(self, request) -> web.Response: ...     # line 884 — self.schema_renderer.render(form) at 895; onSchemaLoaded + schema_overrides
    async def create_blank_form(self, request) -> web.Response: ...  # line 1075
    async def create_form(self, request) -> web.Response: ...    # line 1135 — LLM prompt path; 503 when no client; body["prompt"] required
    async def update_form(self, request) -> web.Response: ...    # line 1329 — full FormSchema body, form_uid must match
    async def patch_form(self, request) -> web.Response: ...     # line 1396 — merged = _deep_merge(existing.model_dump(), body) at 1425
    async def load_from_db(self, request) -> web.Response: ...   # line 1970
# Helpers used by get_form/get_schema: extract_form_uid, self._get_tenant, self.registry.get(form_uid, tenant=…),
#   self._assert_form_tenant, enforce_membership_unless_public(request, form, tenant), dispatch("onBeforeOpen", …)

# From packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py
async def handle_render(request: web.Request) -> web.Response: ...  # line 165 — registry = request.app["form_registry"]; locale = query "locale"; passes tenant when renderer.accepts_tenant
def register_renderer(format_key: str, renderer: AbstractFormRenderer) -> None: ...  # line 91
def get_renderer(format_key: str) -> AbstractFormRenderer | None: ...                 # line 104
def supported_formats() -> list[str]: ...                                              # line 109
# "a2ui" seeded only when importlib.util.find_spec("parrot.outputs.a2ui") is not None (lines 79-88)

# From packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py
A2UI_MAX_BODY_BYTES = int(os.environ.get("A2UI_MAX_DATA_MODEL_BYTES", str(1024 * 1024)))  # line 39
class A2UIActionSubmission(BaseModel): ...                                     # line 42
class A2UIWireError(Exception): ...                                            # line 61
def _a2ui_ns() -> Any: ...                                                     # line 77 — lazy import namespace
def is_a2ui_request(request: web.Request, body: Any) -> bool: ...              # line 122 — Content-Type OR {"version":"v1.0","action":…}
def unwrap_action(form: FormSchema, body: dict[str, Any]) -> A2UIActionSubmission: ...  # line 164
def a2ui_response(envelopes: list[dict[str, Any]], *, status: int) -> web.Response: ... # line 275

# From packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
# GET  {tp}/forms                         → handler.list_forms          (line 375)
# POST {tp}/forms                         → handler.create_form         (line 376)
# GET  {tp}/forms/{form_uid}              → handler.get_form  (tenant="public" mount)   (line 385)
# PATCH {tp}/forms/{form_uid}             → handler.patch_form          (line 390)
# GET  {tp}/forms/{form_uid}/schema       → handler.get_schema (tenant="public" mount)  (line 401)
# GET  {tp}/forms/{form_uid}/render/{format} → handle_render            (line 408)
# _TENANT_MODES = ("required", "public", "none")                        (line 81)

# From packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormStorage(ABC):                                                        # line 63
    async def load(...)                                                        # line 95
    async def list_forms(self, *, tenant: str | None = None) -> list[dict[str, Any]]: ...  # line 130
class FormRegistry:                                                            # line 240
    async def register(self, form: FormSchema, *, persist: bool = False, overwrite: bool = True,
                       tenant: str | None = None) -> None: ...                  # line 466
    async def get(self, form_uid: uuid.UUID, *, tenant: str | None = None) -> FormSchema | None: ...  # line 976
    async def list_forms(self, *, tenant: str | None = None) -> list[FormSchema]: ...  # line 1102 — never cross-tenant
    async def list_tenants(self) -> list[str]: ...                             # line 1197
    async def load_from_storage(self, *, tenant: str | None = None) -> int: ...  # line 1320

# From packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py
class PostgresFormStorage(FormStorage): ...                                    # line 69 — schema_json JSONB (FormSchema.model_dump_json())
    async def list_forms(self, *, tenant: str | None = None) -> list[dict[str, Any]]: ...  # line 642 — summary dicts only

# From packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class Extensions(RootModel[dict[str, Any]]): ...                               # line 341
class ComponentMetadata(BaseModel): extensions: Extensions | None = None       # line 364
SurfaceMetadata = ComponentMetadata                                            # line 378
class Component(BaseModel):                                                    # line 400
    id: str; component: str; catalog_id: str | None (alias catalogId); child: str | None;
    children: ChildList | None; weight: float | None; accessibility; checks: list[CheckRule] | None;
    action: Action | None; metadata: ComponentMetadata | None                  # lines 408-417
class CreateSurface(A2UIMessageBase):                                          # line 446
    surface_id: str (alias surfaceId); catalog_id: str | None (alias catalogId);
    send_data_model: bool = False (alias sendDataModel); components: list[Component];
    data_model: dict[str, Any] (alias dataModel); metadata: SurfaceMetadata | None   # lines 465-470
class ActionMessage(A2UIMessageBase): ...                                      # line 585
class ErrorMessage(A2UIMessageBase): ...                                       # line 648
class A2UIAgentMessage(BaseModel): ...                                         # line 695
class A2UIRendererMessage(BaseModel): ...                                      # line 740

# From packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py
def serialize(message: Serializable) -> dict[str, Any]: ...                    # line 104
def deserialize(data: dict[str, Any] | str | bytes) -> A2UIAgentMessage | A2UIRendererMessage | list[A2UIAgentMessage]: ...  # line 155 — legacy "messageType" normalised via compat
def to_jsonl(...)  # line 201 ; def iter_jsonl(text: str)  # line 215

# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
def validate_message(message: A2UIAgentMessage | A2UIRendererMessage) -> None: ...   # line 458
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin: ProducerOrigin = ProducerOrigin.TOOL,
                      surface_catalog_id: str | None = None) -> None: ...     # line 743
# catalog/base.py: DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1" (line 53); class ProducerOrigin (line 99)
# catalog/basic/__init__.py: BASIC_CATALOG_ID (line 44)

# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/inputs.py
class Button(Checkable, Component): child: str; action: Action                 # line 46
class TextField(Checkable, Component): label: DynamicString; value; placeholder   # line 66 (+ variant prop)
class CheckBox(Checkable, Component): label; value: DynamicBoolean             # line 81
class ChoiceOption(BaseModel): label: DynamicString; value: str               # line 91
class ChoicePicker(Checkable, Component): label; options: list[ChoiceOption]; value: DynamicStringList;
    display_style ("checkbox"|"chips", alias displayStyle); filterable          # line 100 (+ variant prop at 113)
class Slider(Checkable, Component): label; min: float = 0; max: float; value: DynamicNumber; steps   # line 120
class DateTimeInput(Checkable, Component): value; enable_date (enableDate); enable_time (enableTime); min; max; label  # line 136
# basic/layout.py __all__: Card, Column, Divider, List, Modal, Row, TabItem, Tabs   (line 21)
# basic/media.py  __all__: AudioPlayer, Icon, IconSvgPath, Image, Text, Video        (line 21)

# From packages/ai-parrot/src/parrot/cli/__init__.py:103-135
@click.group(cls=LazyGroup)
def cli(): ...
cli._lazy_commands = {"setup": "parrot.setup.cli", ..., "toolkits": "parrot.cli.toolkits",
                      "manuals": "parrot_tools.procedures.cli", "e2e": "parrot.e2e.cli", ...}
# packages/ai-parrot/src/parrot/cli/toolkits.py:26 — `@click.group(name="toolkits")` is the pattern for a new group
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot_formdesigner.renderers import A2UIFormRenderer, AbstractFormRenderer, JsonSchemaRenderer  # renderers/__init__.py (A2UIFormRenderer lazy via PEP 562, line 27-41)
from parrot_formdesigner.renderers.a2ui import FIELD_LOWERING, field_pointer, field_id_from_pointer_token
from parrot_formdesigner.extractors import JsonSchemaExtractor, JSONSchemaExtractor, PydanticExtractor, ToolExtractor, YamlExtractor  # extractors/__init__.py:8-11
from parrot_formdesigner.core.resolution import resolve_rule_references   # extractors/jsonschema.py:20
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, RenderedForm
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.api import a2ui_wire                              # handlers.py:30
from parrot_formdesigner.api.render import get_renderer, register_renderer, supported_formats
from parrot_formdesigner.services.registry import FormRegistry, FormStorage
from parrot_formdesigner.services.storage import PostgresFormStorage
from parrot.outputs.a2ui.models import CreateSurface, Component, ComponentMetadata, Extensions   # a2ui_wire.py:89
from parrot.outputs.a2ui.serialization import deserialize, serialize                           # a2ui_wire.py:99
from parrot.outputs.a2ui.runtime.models import A2UIErrorCode, error_envelope                  # a2ui_wire.py:98
from parrot.outputs.a2ui.catalog import validate_envelope, validate_message
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, ProducerOrigin
```

#### Key Attributes & Constants
- `A2UIFormRenderer.RENDERER_NAME` → `"a2ui"` (renderers/a2ui.py:309)
- Surface id convention → `f"form-{form.form_uid}"` (renderers/a2ui.py:484; checked by `a2ui_wire._surface_mismatch`, line 153)
- Root extension keys → `parrot_variant, parrot_form_uid, parrot_form_id, parrot_form_version, parrot_tenant, parrot_submit_url` (renderers/a2ui.py:474-479)
- Field extension keys → `parrot_field_id, parrot_field_uid, parrot_field_type, parrot_section_id, parrot_subsection_id, parrot_read_only` (renderers/a2ui.py:634-642)
- `RenderedForm.content_type` for A2UI → `"application/a2ui+json"` (FEAT-544 spec §2; `a2ui_wire.a2ui_response` sets the same header)
- `A2UI_MAX_BODY_BYTES` → env `A2UI_MAX_DATA_MODEL_BYTES`, default 1 MiB (api/a2ui_wire.py:39)
- `_TENANT_MODES` → `("required", "public", "none")` (api/routes.py:81); `get_form`/`get_schema`/`handle_render` are mounted `tenant="public"`
- parrot-formdesigner extras → `ai-parrot = ["ai-parrot>=1.2.1"]` and alias `a2ui` (pyproject.toml:53-59)
- Existing tests to extend → `tests/unit/renderers/test_a2ui_renderer.py`, `test_a2ui_field_lowering.py`, `test_a2ui_export.py` (lazy-export only), `tests/unit/api/test_render_dispatcher.py`, `test_a2ui_wire.py`, `test_submit_a2ui.py`, `tests/unit/extractors/test_extractor_roundtrip.py`, `tests/integration/test_a2ui_form_cycle.py`
- Docs to extend → `packages/parrot-formdesigner/docs/a2ui-renderer.md`

### Does NOT Exist (Anti-Hallucination)
- ~~`FormSchema.dialect`~~ / ~~`FormDialect`~~ — do not exist yet (this feature adds them).
- ~~`parrot_formdesigner.extractors.a2ui`~~ / ~~`A2UIExtractor`~~ — no reverse extractor exists.
- ~~`parrot_formdesigner.services.a2ui_export`~~ / ~~`A2UIExportService`~~ — no bulk export exists; `test_a2ui_export.py` only tests the lazy re-export of `A2UIFormRenderer`.
- ~~`parrot_formdesigner/cli.py`~~ and ~~`[project.scripts]` in parrot-formdesigner~~ — the package has no CLI; `parrot` CLI lives in ai-parrot (`parrot.cli:cli`).
- ~~`POST /forms/export`~~, ~~`?dialect=` query param~~, ~~`application/a2ui+json` handling on `GET /forms/{uid}`~~ — not implemented; only `/render/{format}` serves A2UI today.
- ~~`POST /forms` accepting a `FormSchema` or surface body~~ — today `create_form` is **LLM-prompt only** (`body["prompt"]` required, 503 without client); structured creation goes through `PUT /forms/{uid}`, `POST /forms/blank`, `POST /forms/from-db`.
- ~~`JsonSchemaExtractor` reading `x-section` / `x-subsection` / `x-placeholder` / `x-read-only`~~ — it does not; every extracted form has a single `"fields"` section.
- ~~`FormStorage.list_forms()` returning `FormSchema` objects~~ — it returns summary dicts; full schemas come from `FormRegistry.list_forms()` after `load_from_storage()`.
- ~~`docs/formdesigner/`~~ at repo root — formdesigner docs live in `packages/parrot-formdesigner/docs/`.
- ~~`Form` catalog component~~ — forbidden by the A2UI dialect spec (G6); forms are compositions.
- ~~`parrot.outputs.a2ui.builders.build_form()` as the renderer backend~~ — FEAT-544's renderer composes components directly; do not route through `builders` for the dialect layer.
- ~~A `/forms/{uid}/a2ui` sibling route~~ — rejected in FEAT-544 (U1); keep dual-wire on existing routes.

---

## Parallelism Assessment

- **Internal parallelism**: four largely independent lanes once the
  `FormDialect` enum + `FormSchema.dialect` field land first (a tiny opener):
  (a) `api/dialect.py` + `get_form`/`get_schema`/`list_forms` negotiation;
  (b) `services/a2ui_export.py` + `POST /forms/export` + CLI `export`;
  (c) `JsonSchemaExtractor` fidelity fixes + `translate_jsonschema_to_a2ui`
  + CLI `translate`; (d) `extractors/a2ui.py` + dual-wire `POST /forms` + CLI
  `import`. Lanes (a), (b), (d) all edit `api/handlers.py` (different
  handlers) and (b)+(c)+(d) all touch `cli.py` — serialise the handler/CLI
  edits or give each lane its own handler/sub-module and merge last.
- **Cross-feature independence**: no in-flight formdesigner spec is open
  (FEAT-551 msteams renderer is `done`; its worktree is stale but merged).
  FEAT-640 formdesigner-venue-tables (draft) touches `services/` tables, not
  the API handlers or renderers. `parrot/cli/__init__.py` is shared with
  every feature that registers a CLI group (one-line additive change).
- **Recommended isolation**: `mixed` — one feature worktree; the opener
  (enum + field + tests) is sequential, then lanes (b)/(c)/(d) can run as
  parallel coder sub-worktrees, with (a) and the handler/CLI wiring merged
  last.
- **Rationale**: the pieces share only `FormSchema.dialect` and the FEAT-544
  renderer (read-only); conflicts concentrate in `api/handlers.py` and
  `cli.py`, which are cheap to merge if each lane adds a distinct handler /
  subcommand module.

---

## Open Questions

- [ ] `onSchemaLoaded.schema_overrides` on the A2UI path of `GET /schema`: ignore with a logged warning (proposed), or translate overrides into `updateComponents`/`updateDataModel` envelopes appended to the response? — *Owner: Jesus Lara*
- [ ] Should `GET /forms/{uid}` (raw `FormSchema`) honour the dialect flag at all, or only `GET /forms/{uid}/schema` + `/forms`? Serving a surface from the "raw schema" URL may confuse tooling that expects `form_uid` at the top level. — *Owner: Jesus Lara*
- [ ] Bulk export granularity: `POST /forms/export` NDJSON stream (proposed) vs a single JSON array response; and should the CLI also support `--all-tenants` (iterating `list_tenants()`)? — *Owner: Jesus Lara*
- [ ] Heuristic extractor: when a generic surface has a `Text` immediately before an input with no `label`, use it as the field label (proposed) or keep it as a section description? — *Owner: Jesus Lara*
- [ ] Import conflict policy: 409 on existing `parrot_form_uid` unless `?overwrite=true` (proposed), or always mint a new `form_uid` and keep the imported one in `metadata`? — *Owner: Jesus Lara*
- [ ] Should `translate_jsonschema_to_a2ui` get an HTTP endpoint in v1 (`POST /forms/translate`), or stay library + CLI only (proposed)? — *Owner: Jesus Lara*
- [ ] `click` is a transitive dependency of parrot-formdesigner today only through `ai-parrot`; declare it explicitly in the `ai-parrot`/`a2ui` extra or make the CLI module import it lazily? — *Owner: implementer*
