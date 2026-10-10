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

# Feature Specification: A2UI dialect for parrot-formdesigner (serve, export, translate FormSchema ⇄ A2UI)

**Feature ID**: FEAT-650
**Date**: 2026-10-10
**Author**: Jesus Lara
**Status**: draft
**Target version**: parrot-formdesigner 1.3.0 / ai-parrot 1.x
**Brainstorm**: `sdd/proposals/a2ui-dialect-formbuilder.brainstorm.md` (accepted, Option A)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

parrot-formdesigner (née "formbuilder") predates ai-parrot's A2UI v1.0 support,
yet the two concepts are nearly identical: a `FormSchema` is served as a JSON
document and a frontend renderer turns it into HTML controls. The dialect that
is served today — `GET /forms/{uid}` returns the raw `FormSchema` dump and
`GET /forms/{uid}/schema` returns the `JsonSchemaRenderer` output with `x-*`
extensions — is **not** A2UI, so the existing A2UI renderers (admin UI,
`ssr_html`, `interactive_html`, Adaptive Cards bridge) cannot render a
FormDesigner form natively.

FEAT-544 (merged 2026-09-10) closed the first half of the gap:
`A2UIFormRenderer` lowers a `FormSchema` into a `createSurface` envelope,
`GET /forms/{uid}/render/a2ui` serves it, and `/data` + `/validate` are
dual-wire. What is still missing — this feature — is the **dialect layer
around it**:

1. A flag that makes the form contract endpoints speak A2UI. Today a client
   must know about `/render/a2ui`; a form cannot declare "serve me as A2UI by
   default".
2. A bulk export of every form of a tenant as A2UI surfaces (library, API,
   CLI).
3. A translator from the legacy JSON-Schema dialect (what Fieldsync holds) to
   A2UI. `JsonSchemaExtractor` exists but ignores `x-section`/`x-subsection`/
   `x-placeholder`/`x-read-only`/`x-options`, so JSON Schema → FormSchema →
   A2UI silently flattens sections today.
4. The reverse direction: A2UI surface → `FormSchema`. Nothing exists.

The legacy dialect **must not change**: Fieldsync and other consumers keep
reading `FormSchema` JSON / JSON Schema exactly as today. The A2UI dialect is
additive and opt-in.

### Goals

- G1 — `FormSchema.dialect` (`json_schema` default | `a2ui`) persisted inside
  `schema_json`, editable through `PATCH`/`PUT`, cloned and versioned with the
  form. No DB migration.
- G2 — `GET /forms/{uid}/schema` resolves an *effective* dialect as
  `?dialect=` query > `Accept: application/a2ui+json` > stored `form.dialect`,
  and serves the FEAT-544 `createSurface` envelope when it is `a2ui`;
  `GET /forms` exposes each form's `dialect` and, with `?dialect=a2ui`, a
  per-form `surface_url` manifest (inline envelopes only with
  `include=surface`, capped). `?dialect=json_schema` always forces the legacy body.
  **`GET /forms/{uid}` never changes** — it is the form's identity (brainstorm
  Q2 resolution).
- G3 — `onSchemaLoaded.schema_overrides` on the A2UI path are **translated**
  into `updateComponents` / `updateDataModel` envelopes appended after the
  `createSurface`; untranslatable overrides become warnings (brainstorm Q1
  resolution).
- G4 — Bulk export through three doors over one service:
  `A2UIExportService` (library), `POST /forms/export` (NDJSON stream) and
  `parrot formdesigner export` (CLI, one file per form + report).
- G5 — JSON-Schema → A2UI by **composition** (`JsonSchemaExtractor` →
  `A2UIFormRenderer`), with the extractor's section/subsection/placeholder/
  read-only/options fidelity gaps closed so the composition is faithful.
- G6 — `A2UIExtractor`: any Basic-catalog `createSurface` → `FormSchema`, in
  strict mode (root carries `parrot_variant: "form"`) or heuristic mode
  (lossy, every loss reported). `POST /forms` becomes dual-wire for import;
  a `parrot_form_uid` that already exists answers 409 unless
  `?overwrite=true` (brainstorm Q5 resolution).
- G7 — Every produced surface passes `validate_envelope(origin=TOOL)` and
  `validate_message()`; no `Form` catalog component (dialect spec G6).
- G8 — parrot-formdesigner stays importable without the `ai-parrot` extra;
  every new module imports `parrot.outputs.a2ui` lazily and the dialect flag
  answers 415 (+`supported`) when the extra is missing.
- G9 — Round-trips are tested: `FormSchema → A2UI → FormSchema` is identity
  on expressible fields (strict mode); `FormSchema → JSON Schema → FormSchema
  → A2UI` preserves the section tree.

### Non-Goals (explicitly out of scope)

- Changing `A2UIFormRenderer`, `FIELD_LOWERING` or the `parrot_*` extension
  vocabulary (FEAT-544 stays the single lowering truth; the extractor reads
  it, never redefines it).
- Serving a surface from `GET /forms/{uid}` (resolved: raw `FormSchema` only).
- An HTTP endpoint for JSON-Schema → A2UI translation (`POST /forms/translate`)
  — library + CLI only in v1 (brainstorm Q6, decided here; see §8).
- Storing A2UI as the canonical dialect (brainstorm Option C, rejected) and a
  browser-side adapter (Option D, rejected) — see the brainstorm.
- Recovering style, snippets or lifecycle events from a JSON-Schema document
  (the dialect never encoded them).
- Mapping non-input Basic components (`Image`, `Video`, `AudioPlayer`, `Icon`,
  `Divider`, `List`, `Modal`) or non-Basic catalogs to `FieldType`s — they are
  dropped with a warning.
- Deep-merge semantics for `schema_overrides` (the shallow MVP contract of
  `apply_schema_overrides` is kept; the A2UI translation covers the same
  top-level keys).
- Admin-UI controls for the dialect flag (PATCH is the v1 surface; a toggle is
  a follow-up).

---

## 2. Architectural Design

### Overview

`FormSchema` is the pivot; A2UI becomes a **dialect** of it exactly as JSON
Schema already is. Four pieces, all inside `packages/parrot-formdesigner`,
plus one line in ai-parrot's CLI:

1. **Flag + negotiation.** `FormDialect` enum and `FormSchema.dialect` (M1).
   `api/dialect.py` (M2) owns `resolve_dialect()` (query > Accept > stored,
   with the 400/415 cases) and `render_a2ui_schema()` which produces the
   `createSurface` through the renderer registered under `"a2ui"` in
   `api/render.py` and appends envelopes translated from
   `EventResolution.schema_overrides`. `FormAPIHandler.get_schema` gains one
   branch after `onSchemaLoaded`; `list_forms` gains a `dialect` key per
   descriptor and the `?dialect=a2ui` enrichment.
2. **Export.** `services/a2ui_export.py` (M3): `A2UIExportService` over
   `FormRegistry` + a renderer, yielding `ExportedSurface` per form, never
   crossing tenants. `POST /forms/export` streams NDJSON; the CLI writes files.
3. **JSON Schema → A2UI.** `JsonSchemaExtractor` rebuilds the section tree
   from `x-section`/`x-subsection` and reads `x-placeholder`, `x-read-only`,
   `x-options`, section-level `depends_on` (M4). `services/a2ui_translate.py`
   composes extractor + renderer.
4. **A2UI → FormSchema.** `extractors/a2ui.py` (M5): `A2UIExtractor` with
   strict/heuristic modes and an `ExtractedForm` report. `POST /forms` detects
   a `createSurface` body (`a2ui_wire.is_a2ui_surface_body`) and imports it
   (M6). CLI `import` / `translate` (M7). Docs + round-trip tests (M8).

Resolved decisions carried from the brainstorm and §3 Q&A, applied here:
feature on `dev`; flag = form default + request override; export via service
+ API + CLI; composition for JSON Schema; reverse accepts any Basic surface,
lossy with warnings; only `/schema` + `/forms` honour the flag; overrides are
translated to envelopes; import conflicts are 409 unless `overwrite`.

### Component Diagram

```
                       ┌──────────────────────────── parrot-formdesigner ───────────────────────────┐
 GET /forms/{uid}/schema │  FormAPIHandler.get_schema ──▶ dispatch(onSchemaLoaded) ──▶ resolve_dialect │
 GET /forms              │        │ json_schema                         │ a2ui                        │
                         │        ▼                                     ▼                             │
                         │  JsonSchemaRenderer            api/dialect.render_a2ui_schema             │
                         │  + apply_schema_overrides        ├─ get_renderer("a2ui") → A2UIFormRenderer│
                         │                                  └─ overrides_to_envelopes → update* msgs  │
 POST /forms/export ─────┼─▶ FormAPIHandler.export_forms ──▶ A2UIExportService.export_tenant ──▶ NDJSON│
 POST /forms (surface) ──┼─▶ FormAPIHandler.create_form ──▶ a2ui_wire.is_a2ui_surface_body            │
                         │        └─▶ A2UIExtractor.extract ──▶ FormRegistry.register(persist=True)   │
 parrot formdesigner … ──┼─▶ parrot_formdesigner.cli {export | import | translate}                    │
                         │        ├─ A2UIExportService          ├─ A2UIExtractor                      │
                         │        └─ translate_jsonschema_to_a2ui = JsonSchemaExtractor ∘ A2UIFormRenderer
                         └────────────────────────────────────────────────────────────────────────────┘
 ai-parrot: parrot.cli._lazy_commands["formdesigner"] = "parrot_formdesigner.cli"
 parrot.outputs.a2ui (optional extra): CreateSurface / deserialize / validate_envelope / catalog Basic
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormSchema` (`core/schema.py:401`) | extends | `dialect: FormDialect = FormDialect.JSON_SCHEMA` after `unknown_fields` (line 475); enum next to `UnknownFieldsPolicy` (line 51); exported from `core/__init__.py` |
| `FormAPIHandler.get_schema` (`api/handlers.py:884`) | modifies | A2UI branch after `onSchemaLoaded` resolution (before `return JSONResponse(content)` at line 914) |
| `FormAPIHandler.list_forms` (`api/handlers.py:724`) | modifies | `dialect` key in descriptors; `?dialect=a2ui` enrichment capped by `A2UI_LIST_MAX` |
| `FormAPIHandler.create_form` (`api/handlers.py:1135`) | modifies | surface-body detection before the LLM-client 503 guard; import path |
| `FormAPIHandler` (new handler) | extends | `export_forms` for `POST {tp}/forms/export` |
| `setup_form_api` (`api/routes.py:192`) | extends | one `add_post` next to the clone route (line 397) |
| `api/render.py` `get_renderer("a2ui")` / `supported_formats()` | uses | the dialect layer never instantiates its own renderer |
| `api/a2ui_wire.py` | extends | `is_a2ui_surface_body()` beside `is_a2ui_request()` (line 122); `a2ui_response()` (line 275) reused for framing |
| `services/event_dispatcher.apply_schema_overrides` (line 69) | uses (JSON path) / mirrors (A2UI path) | the same top-level keys are translated by `overrides_to_envelopes` |
| `FormRegistry.get/list_forms/list_tenants/register` | uses | export iterates `list_forms(tenant=…)` after `load_from_storage`; import calls `register(persist=True, overwrite=True)` |
| `JsonSchemaExtractor` (`extractors/jsonschema.py:67`) | modifies | section tree + `x-placeholder`/`x-read-only`/`x-options`/section `depends_on` |
| `extractors/__init__.py` | extends | lazy export of `A2UIExtractor`, `ExtractedForm` |
| `parrot.cli._lazy_commands` (`parrot/cli/__init__.py:117`) | extends | `"formdesigner": "parrot_formdesigner.cli"` |
| `packages/parrot-formdesigner/pyproject.toml` | extends | `click>=8.1.7` in core `dependencies` (the CLI module is importable standalone as `python -m parrot_formdesigner.cli`; S11) |
| `packages/parrot-formdesigner/docs/a2ui-renderer.md` | extends | dialect flag, export, import, translate sections |

### Data Models

```python
# core/schema.py (M1) — next to UnknownFieldsPolicy (line 51)
class FormDialect(str, Enum):
    """Wire dialect a form is served in by the contract endpoints."""
    JSON_SCHEMA = "json_schema"   # default — byte-for-byte today's behaviour
    A2UI = "a2ui"                 # FEAT-544 createSurface envelope

# FormSchema (line 401) gains, after unknown_fields (line 475):
#   dialect: FormDialect = FormDialect.JSON_SCHEMA   # FEAT-650

# services/a2ui_export.py (M3)
class ExportedSurface(BaseModel):
    form_uid: str
    form_id: str
    version: str
    dialect: str                      # "a2ui" | "json_schema"
    envelope: dict[str, Any] | None   # the rendered content; None when error is set
    warnings: list[str] = []          # RenderWarning messages, flattened
    error: str | None = None          # render failure — the stream never aborts

# extractors/a2ui.py (M5)
class ExtractionMode(str, Enum):
    STRICT = "strict"          # root carries parrot_variant == "form"
    HEURISTIC = "heuristic"    # any Basic surface

class DroppedComponent(BaseModel):
    component_id: str
    component: str
    reason: str                # "unsupported_component" | "not_in_basic_catalog" | "unreachable" | "no_binding"

class ExtractedForm(BaseModel):
    form: FormSchema
    mode: ExtractionMode
    warnings: list[str]
    dropped: list[DroppedComponent]

# api/dialect.py (M2)
class DialectError(Exception):
    """Carries the HTTP status + JSON payload for a dialect negotiation failure."""
    status: int                # 400 (unknown value) | 415 (a2ui unavailable)
    payload: dict[str, Any]    # {"error": …} | {"supported": [...]}
```

Wire shapes fixed by this spec:

- `GET /forms/{uid}/schema` (a2ui, no overrides): body = the `createSurface`
  envelope, `Content-Type: application/a2ui+json`. With translated overrides:
  `{"messages": [createSurface, updateComponents…, updateDataModel…]}`,
  `Content-Type: application/json` — the same framing `a2ui_wire.a2ui_response`
  already uses for `/data`. `?with_meta=true` wraps either in
  `{"content", "content_type", "warnings", "metadata"}` exactly like
  `handle_render` does (`api/render.py:215-235`).
- `GET /forms` descriptors gain `"dialect": "<stored value>"` for in-memory
  entries. With `?dialect=a2ui` each descriptor gains a **manifest** only:
  `"surface_url": "<prefix>/{tenant}/forms/{form_uid}/schema?dialect=a2ui"` —
  no rendering. Inline envelopes require `?dialect=a2ui&include=surface`, which
  adds `"surface"` + `"warnings"` per descriptor and is bounded by
  `A2UI_LIST_MAX`: more forms than that → 400
  `{"error": "too many forms for inline a2ui; use POST /forms/export", "max": N}` (S8).
- `POST /forms/export` request `{"dialect": "a2ui"|"json_schema", "form_uids": [...]?, "published_only": bool?, "locale": "en"?}`;
  response `application/x-ndjson`, one `ExportedSurface` JSON object per line.
- `POST /forms` (import) request = a v1.0 `createSurface` envelope
  (`{"version": "v1.0", "createSurface": {...}}`) or any body sent with
  `Content-Type: application/a2ui+json`; response 201
  `{"form_uid", "form_id", "url", "dialect", "import": {"mode", "warnings", "dropped"}}`;
  409 `{"error": "form already exists", "form_uid": …}` unless `?overwrite=true`;
  413 A2UI `error` envelope when the body exceeds `A2UI_MAX_BODY_BYTES`.

### New Public Interfaces

```python
# parrot_formdesigner.core
FormDialect

# parrot_formdesigner.api.dialect
A2UI_MEDIA_TYPE: str                      # "application/a2ui+json"
A2UI_LIST_MAX: int                        # env FORMDESIGNER_A2UI_LIST_MAX, default 50
def resolve_dialect(request: web.Request, form: FormSchema) -> FormDialect
async def render_a2ui_schema(form, *, locale, overrides) -> tuple[list[dict], RenderedForm, list[str]]
def overrides_to_envelopes(form, rendered, overrides, *, locale) -> tuple[list[dict], list[str]]

# parrot_formdesigner.services.a2ui_export
ExportedSurface, A2UIExportService

# parrot_formdesigner.services.a2ui_translate
async def translate_jsonschema_to_a2ui(schema, *, form_id, title, tenant, locale) -> RenderedForm

# parrot_formdesigner.extractors
A2UIExtractor, ExtractedForm, ExtractionMode, DroppedComponent   # lazy (PEP 562), like renderers.A2UIFormRenderer

# parrot_formdesigner.cli
formdesigner  (click group: export | import | translate)   → `parrot formdesigner …`
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: `FormDialect` + `FormSchema.dialect` | yes | enum shape, field position (after line 475), default, `core/__init__` export; tests mirror `test_formschema_persistence.py` | — |
| M2: dialect negotiation + `get_schema`/`list_forms` branches | yes | precedence rule, 400/415 payloads, framing via `a2ui_response`, `with_meta` mirror, `A2UI_LIST_MAX`, override translation table (§7) all fixed | — |
| M3: export service + `POST /forms/export` | yes | `ExportedSurface` model, iterator contract, NDJSON via `web.StreamResponse`, tenant rule | — |
| M4: `JsonSchemaExtractor` fidelity + `translate_jsonschema_to_a2ui` | yes | section-tree rebuild rule, `x-*` key list, fallback section id `"fields"` | — |
| M5: `A2UIExtractor` | yes | strict/heuristic mode switch, `HEURISTIC_PRIMITIVE_MAP`, checks→constraints table, drop reasons, `resolve_rule_references` tail | — |
| M6: dual-wire `POST /forms` import | yes | detection predicate, conflict policy (409/`overwrite`), 201 payload, 413 cap | — |
| M7: CLI group + lazy registration + dep | yes | click group name, three commands + options, exit codes, report file name | — |
| M8: docs + integration round-trips | yes | which doc sections, which round-trip assertions | — |

### Module 1: `FormDialect` enum + `FormSchema.dialect`
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`, `core/__init__.py`
- **Responsibility**: the persisted flag. Default keeps today's behaviour; absent key in an older `schema_json` row deserialises to the default (pydantic default, no migration).
- **Depends on**: nothing
- **Interface Skeleton**:
  ```python
  # core/schema.py  (modifies core/schema.py:51 — insert after UnknownFieldsPolicy; and :475)
  class FormDialect(str, Enum):  # same shape as UnknownFieldsPolicy, verified: core/schema.py:51
      """Wire dialect served by the contract endpoints (FEAT-650).

      JSON_SCHEMA keeps the legacy JsonSchemaRenderer body; A2UI serves the
      FEAT-544 createSurface envelope. GET /forms/{uid} ignores this flag.
      """
      JSON_SCHEMA = "json_schema"
      A2UI = "a2ui"

  class FormSchema(BaseModel):  # verified: core/schema.py:401
      # ... existing fields ...
      unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP  # verified: core/schema.py:475
      # FEAT-650 — A2UI dialect flag
      dialect: FormDialect = FormDialect.JSON_SCHEMA

  # core/__init__.py  (modifies core/__init__.py:42 and :92 — mirror the UnknownFieldsPolicy export)
  ```

### Module 2: Dialect negotiation + `get_schema` / `list_forms` branches
- **Path**: `api/dialect.py` (new), `api/handlers.py` (modifies `get_schema`, `list_forms`)
- **Responsibility**: resolve the effective dialect; render the A2UI schema through the registered renderer; translate `schema_overrides`; keep the JSON path byte-for-byte.
- **Depends on**: M1; `api/render.get_renderer` (FEAT-544); `api/a2ui_wire.a2ui_response`
- **Interface Skeleton**:
  ```python
  # api/dialect.py  (new)
  A2UI_MEDIA_TYPE = "application/a2ui+json"            # equals parrot.a2a.models.A2UI_MEDIA_TYPE, verified: api/a2ui_wire.py:88
  DIALECT_QUERY_PARAM = "dialect"
  A2UI_LIST_MAX = int(os.environ.get("FORMDESIGNER_A2UI_LIST_MAX", "50"))

  class DialectError(Exception):
      """Negotiation failure carrying ``status`` (400 | 415) and a JSON ``payload``."""
      def __init__(self, status: int, payload: dict[str, Any]) -> None: ...

  def resolve_dialect(request: web.Request, form: FormSchema) -> FormDialect:
      """Return the effective dialect: ``?dialect=`` > ``Accept`` > ``form.dialect``.

      Raises DialectError(400, {"error": ..., "supported": ["json_schema", "a2ui"]})
      for an unknown query value, and DialectError(415, {"supported": supported_formats()})
      when ``a2ui`` is required but ``get_renderer("a2ui")`` is None (extra missing).
      ``Accept`` is only consulted when the query param is absent; a wildcard or
      ``application/json`` Accept never selects a2ui.
      """

  async def render_a2ui_schema(
      form: FormSchema, *, locale: str = "en", overrides: Mapping[str, Any] | None = None,
  ) -> tuple[list[dict[str, Any]], RenderedForm, list[str]]:
      """Render ``form`` with the registered ``"a2ui"`` renderer and append translated overrides.

      Returns (envelopes, rendered, warnings): envelopes[0] is the createSurface
      (``rendered.content``); the rest come from overrides_to_envelopes.
      """

  def overrides_to_envelopes(
      form: FormSchema, rendered: RenderedForm, overrides: Mapping[str, Any], *, locale: str = "en",
  ) -> tuple[list[dict[str, Any]], list[str]]:
      """Translate shallow JSON-Schema ``schema_overrides`` into A2UI envelopes (§7 table).

      Deterministic: one updateComponents per touched component id, one
      updateDataModel per default change; keys outside the table yield a
      ``override_not_translatable:<key>`` warning and no envelope.
      """

  # api/handlers.py  (modifies api/handlers.py:884 get_schema — branch before `return JSONResponse(content)` at :914)
  class FormAPIHandler:
      async def get_schema(self, request: web.Request) -> web.Response:
          """... unchanged docstring + : A2UI dialect (FEAT-650) — when resolve_dialect() is A2UI,
          answer render_a2ui_schema() framed by a2ui_wire.a2ui_response (single envelope → a2ui media
          type; several → {"messages": [...]}); ``?with_meta=true`` mirrors handle_render."""

      # (modifies api/handlers.py:724 list_forms — descriptors gain "dialect"; ?dialect=a2ui enrichment)
      async def list_forms(self, request: web.Request) -> web.Response:
          """... + ``dialect`` per in-memory descriptor; ``?dialect=a2ui`` adds ``surface_url`` (manifest, no render);
          ``?dialect=a2ui&include=surface`` adds ``surface``/``warnings`` (≤ A2UI_LIST_MAX, else 400) — S8."""
  ```

### Module 3: `A2UIExportService` + `POST /forms/export`
- **Path**: `services/a2ui_export.py` (new), `api/handlers.py` (new `export_forms`), `api/routes.py`
- **Responsibility**: bulk export over the registry; NDJSON streaming; per-form error isolation; tenant isolation.
- **Depends on**: `FormRegistry` (`services/registry.py:240`), `api/render.get_renderer`, `JsonSchemaRenderer` (for `dialect=json_schema`)
- **Interface Skeleton**:
  ```python
  # services/a2ui_export.py  (new)
  class ExportedSurface(BaseModel): ...   # §2 Data Models

  class A2UIExportService:
      """Export FormSchemas as A2UI surfaces (or JSON Schema) one tenant at a time."""
      def __init__(
          self, registry: FormRegistry, *,                     # FormRegistry verified: services/registry.py:240
          renderer: AbstractFormRenderer | None = None,        # None → api.render.get_renderer("a2ui"); RuntimeError if unavailable
          locale: str = "en",
      ) -> None: ...
      async def export_form(self, form_uid: uuid.UUID, *, tenant: str) -> ExportedSurface:
          """Render one form; a renderer exception becomes ``error`` (never raises)."""
      async def export_tenant(
          self, tenant: str, *, form_uids: Sequence[uuid.UUID] | None = None, published_only: bool = False,
      ) -> AsyncIterator[ExportedSurface]:
          """Yield every form of ``tenant``: ALWAYS ``await registry.load_from_storage(tenant=tenant)`` first when
          ``registry.storage is not None`` so DB-only forms are included (the in-memory view is a cache, S7), then
          ``registry.list_forms(tenant=tenant)``. ``published_only`` keeps forms whose ``published_version`` is not None
          (verified: core/schema.py:469). Never aggregates across tenants."""
      # NO export_all_tenants(): FormRegistry.list_tenants() only knows hydrated in-memory buckets and PostgresFormStorage
      # resolves one tenant schema per call, so a cross-tenant sweep would silently miss tenants (S7). Callers pass tenants explicitly.

  # api/handlers.py  (adds export_forms after get_schema's neighbour get_style, api/handlers.py:916)
  class FormAPIHandler:
      async def export_forms(self, request: web.Request) -> web.Response:
          """POST /api/v1/{tenant}/forms/export — NDJSON stream of ExportedSurface (web.StreamResponse,
          Content-Type application/x-ndjson). 400 on unknown dialect / malformed body; 415 when a2ui is
          requested without the extra. Tenant comes from the route; the body cannot override it."""

  # api/routes.py  (modifies api/routes.py:397 — add the sibling route right after the clone route)
  app.router.add_post(f"{tp}/forms/export", _wrap_auth(handler.export_forms))
  ```

### Module 4: `JsonSchemaExtractor` fidelity + `translate_jsonschema_to_a2ui`
- **Path**: `extractors/jsonschema.py` (modifies), `services/a2ui_translate.py` (new)
- **Responsibility**: make JSON Schema → FormSchema faithful to what `JsonSchemaRenderer` emits, then compose with the FEAT-544 renderer.
- **Depends on**: M1 (none functionally); `renderers/jsonschema.py` vocabulary (read-only)
- **Interface Skeleton**:
  ```python
  # extractors/jsonschema.py  (modifies extractors/jsonschema.py:86 extract — section-tree rebuild; :176 _property_to_field)
  class JsonSchemaExtractor:
      def extract(self, schema: dict[str, Any], *, form_id: str | None = None, title: str | None = None) -> FormSchema:
          """... + FEAT-650: properties carrying ``x-section`` are grouped into FormSection(section_id, title,
          description, depends_on ← x-section-depends-on) in first-seen order; ``x-subsection`` nests a
          FormSubsection (depends_on ← x-subsection-depends-on). Properties without ``x-section`` fall into the
          legacy ``"fields"`` section (today's behaviour, unchanged for Pydantic/OpenAPI input)."""
      def _property_to_field(self, *, name, prop, required, root_schema) -> FormField:
          """... + reads ``x-placeholder`` → placeholder, ``x-read-only`` → read_only,
          ``x-options`` [{value,label,disabled?}] → options (preferred over bare ``enum`` AND over ``items.enum`` for
          array-typed MULTI_SELECT/TAGS properties, which today lose their options entirely — S4), ``default`` → default,
          ``description`` → description."""

  # services/a2ui_translate.py  (new)
  async def translate_jsonschema_to_a2ui(
      schema: dict[str, Any], *, form_id: str | None = None, title: str | None = None,
      tenant: str | None = None, locale: str = "en", renderer: AbstractFormRenderer | None = None,
  ) -> RenderedForm:
      """JsonSchemaExtractor().extract(...) → (tenant stamped on the FormSchema) → A2UIFormRenderer.render(...).
      Raises RuntimeError when the ``ai-parrot`` extra is missing (same message as api/a2ui_wire._a2ui_ns)."""
  ```

### Module 5: `A2UIExtractor`
- **Path**: `extractors/a2ui.py` (new), `extractors/__init__.py` (lazy export)
- **Responsibility**: `createSurface` → `FormSchema`, strict or heuristic, with a complete loss report.
- **Depends on**: FEAT-544 vocabulary (`renderers/a2ui.py` `field_id_from_pointer_token`, `FIELD_LOWERING`), `parrot.outputs.a2ui` (lazy)
- **Interface Skeleton**:
  ```python
  # extractors/a2ui.py  (new)
  HEURISTIC_PRIMITIVE_MAP: dict[str, FieldType]   # §7 table; keyed "TextField", "TextField:longText", "TextField:number", "TextField:obscured", "CheckBox", "ChoicePicker", "ChoicePicker:multipleSelection", "Slider", "DateTimeInput:date", "DateTimeInput:time", "DateTimeInput:datetime"
  CHECK_FUNCTION_TO_CONSTRAINT: dict[str, str]    # "required"→required, "regex"→pattern, "length"→min/max_length, "numeric"→min/max_value, "email"→FieldType.EMAIL

  class ExtractionMode(str, Enum): ...
  class DroppedComponent(BaseModel): ...
  class ExtractedForm(BaseModel): ...

  A2UI_MAX_COMPONENTS = int(os.environ.get("A2UI_MAX_IMPORT_COMPONENTS", "2000"))   # S6
  A2UI_MAX_DEPTH = int(os.environ.get("A2UI_MAX_IMPORT_DEPTH", "32"))              # S6

  class A2UIExtractor:
      """Convert an A2UI v1.0 createSurface into a FormSchema (strict or heuristic)."""
      def __init__(self, *, default_section_id: str = "fields", max_components: int = A2UI_MAX_COMPONENTS,
                   max_depth: int = A2UI_MAX_DEPTH) -> None: ...
      def extract(
          self, surface: dict[str, Any] | str | bytes | Any, *,
          form_id: str | None = None, title: str | None = None, tenant: str | None = None,
      ) -> ExtractedForm:
          """Parse with parrot.outputs.a2ui.serialization.deserialize (verified: serialization.py:155) and read
          ``message.create_surface`` (alias ``createSurface``, verified: models.py:695-718); run validate_envelope(origin=TOOL)
          first so DUPLICATE_ID / MISSING_ROOT / DANGLING_CHILD / UNKNOWN_COMPONENT surface as ValueError(details) before any
          walk (S6); enforce max_components (ValueError) and max_depth (ValueError); a cycle met during the walk drops the
          revisited component with reason "cycle" and warns; require a ``root`` component, pick STRICT when root.metadata.extensions.parrot_variant == "form"
          else HEURISTIC, walk children from root, and return ExtractedForm. Never raises on unsupported content —
          only on a non-createSurface payload (ValueError) or a missing root (ValueError). Output passes through
          core.resolution.resolve_rule_references (verified: extractors/jsonschema.py:20,141)."""
      def _walk(self, surface: Any) -> Iterator[tuple[Any, list[str]]]:
          """Depth-first from root yielding (component, ancestor_ids); unreachable components → dropped("unreachable")."""
      def _field_from_component(self, component: Any, *, mode: ExtractionMode, data_model: dict[str, Any]) -> FormField | None:
          """Strict: parrot_field_id/parrot_field_type/parrot_read_only drive identity+type; a missing extension is a
          warning and falls back to the heuristic rule for that component. Heuristic: HEURISTIC_PRIMITIVE_MAP; field_id from
          the ``value`` binding path (field_id_from_pointer_token, verified: renderers/a2ui.py:92) else component id."""

  # extractors/__init__.py  (modifies extractors/__init__.py:10 — add PEP 562 lazy export like renderers/__init__.py:27-41)
  ```

### Module 6: Dual-wire `POST /forms` import
- **Path**: `api/a2ui_wire.py` (adds `is_a2ui_surface_body`), `api/handlers.py` (modifies `create_form`)
- **Responsibility**: accept a surface body, import through M5, persist, report.
- **Depends on**: M5, M1; `FormRegistry.register` (`services/registry.py:466`), `FormAlreadyExistsError` (line 51)
- **Interface Skeleton**:
  ```python
  # api/a2ui_wire.py  (modifies api/a2ui_wire.py:122 — add after is_a2ui_request)
  def is_a2ui_surface_body(request: web.Request, body: Any) -> bool:
      """True when Content-Type is application/a2ui+json OR body is {"version": "v1.0", "createSurface": {...}}.
      Must not import parrot.outputs.a2ui (same rule as is_a2ui_request, verified: api/a2ui_wire.py:14-16)."""

  # api/handlers.py  (modifies api/handlers.py:1135 create_form — surface branch BEFORE the LLM-client 503 guard, after _rbac_shadow_gate)
  class FormAPIHandler:
      async def create_form(self, request: web.Request) -> web.Response:
          """... + FEAT-650: a surface body is imported via _import_a2ui_surface; the legacy prompt path is untouched."""
      async def _import_a2ui_surface(self, request: web.Request, body: dict[str, Any], *, tenant: str) -> web.Response:
          """413 over A2UI_MAX_BODY_BYTES (A2UI error envelope); the surface must pass deserialize() + validate_message() +
          validate_envelope(origin=TOOL) else 422 {"error": "invalid surface", "details": [...]} (S5); then
          A2UIExtractor().extract(body, tenant=tenant);
          409 when registry.get(form.form_uid, tenant) exists and ?overwrite is not truthy (also on
          FormAlreadyExistsError); else registry.register(form, persist=True, overwrite=True, tenant=tenant) and 201
          {"form_uid","form_id","url","dialect","import":{mode,warnings,dropped}}. On overwrite, version is bumped with
          api._utils._bump_version (verified: api/_utils.py:61)."""
  ```

### Module 7: CLI `parrot formdesigner {export | import | translate}`
- **Path**: `parrot_formdesigner/cli.py` (new), `packages/ai-parrot/src/parrot/cli/__init__.py` (one entry), `packages/parrot-formdesigner/pyproject.toml` (click)
- **Responsibility**: operator doors over M3/M4/M5 without the HTTP server.
- **Depends on**: M3, M4, M5
- **Interface Skeleton**:
  ```python
  # parrot_formdesigner/cli.py  (new) — pattern: parrot/cli/toolkits.py:26 (`@click.group(name="toolkits")`)
  @click.group(name="formdesigner")
  def formdesigner() -> None:
      """FormDesigner dialect tools (FEAT-650)."""

  @formdesigner.command("export")
  # --dialect [a2ui|json_schema] (default a2ui) --tenant TEXT (required; repeatable — each tenant is exported explicitly, S7)
  # --form-uid UUID (multiple) --published-only --locale TEXT --out DIR (required) --dsn TEXT (env FORMDESIGNER_DSN)
  def export(...) -> None:
      """Write <out>/<form_id>-<form_uid>.<dialect>.json per form + <out>/export-report.json
      {exported, failed, warnings}. Exit 0; exit 1 when any form failed; exit 2 on config errors.
      Builds PostgresFormStorage(dsn=...) (verified: services/storage.py:102) + FormRegistry(storage=...)
      (verified: services/registry.py:275)."""

  @formdesigner.command("import")
  # SURFACE path --tenant TEXT (required) --form-id TEXT --overwrite --dry-run --dsn TEXT
  def import_surface(...) -> None:
      """A2UIExtractor().extract(file) → print ExtractedForm report (JSON); without --dry-run, register(persist=True);
      409-equivalent exit 3 when the form exists and --overwrite is absent."""

  @formdesigner.command("translate")
  # SCHEMA path --from [json_schema] --to [a2ui] --form-id --tenant --locale --out FILE
  def translate(...) -> None:
      """translate_jsonschema_to_a2ui(...) → write/print the envelope + warnings to stderr."""

  # parrot/cli/__init__.py  (modifies parrot/cli/__init__.py:117 — one entry after "toolkits")
  #   "formdesigner": "parrot_formdesigner.cli",   # FEAT-650 — ships in parrot-formdesigner
  # When parrot-formdesigner is not installed, LazyGroup's import failure must surface as a clean click error naming the
  # install hint (`pip install parrot-formdesigner`) — verify LazyGroup's missing-module behaviour (parrot/cli/__init__.py:~60-100)
  # at task time and add the hint there if it is a bare ImportError (S11). `cli.py` also exposes `main()` for `python -m`.
  ```

### Module 8: Docs + integration round-trips
- **Path**: `packages/parrot-formdesigner/docs/a2ui-renderer.md` (extends), `packages/parrot-formdesigner/tests/integration/test_a2ui_dialect_roundtrip.py` (new)
- **Responsibility**: document the dialect flag, negotiation precedence, export/import/translate; prove G9.
- **Depends on**: M1–M7
- **Interface Skeleton**: n/a (docs + tests; see §4).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `tests/unit/core/test_form_dialect.py::test_default_json_schema` | M1 | `FormSchema(...)` without the key → `FormDialect.JSON_SCHEMA`; `model_validate_json` of a pre-FEAT-650 dump still loads |
| `…::test_dialect_roundtrips_and_clones` | M1 | `model_dump_json` → `model_validate_json` keeps `a2ui`; `FormRegistry.clone` path preserves it |
| `tests/unit/api/test_dialect_negotiation.py::test_precedence_query_over_accept_over_stored` | M2 | all 8 combinations of (query, Accept, stored) resolve per G2 |
| `…::test_unknown_query_400` / `…::test_a2ui_unavailable_415` | M2 | `DialectError` payloads; 415 lists `supported_formats()` |
| `…::test_get_schema_legacy_unchanged` | M2 | without override on a `json_schema` form the body is byte-identical to today (golden fixture) |
| `…::test_get_schema_a2ui_single_envelope` / `…::test_get_schema_a2ui_with_overrides_messages` | M2 | media type + framing; `validate_message()` on every envelope |
| `…::test_private_form_membership_enforced_on_a2ui` / `…::test_onschemaloaded_abort_json_regardless_of_dialect` / `…::test_public_form_a2ui_without_session` | M2 | membership + lifecycle semantics are identical under both dialects; aborts keep the JSON error body (S10) |
| `…::test_overrides_translation_table` | M2 | each §7 table row produces the specified envelope; unknown key → warning, no envelope |
| `tests/unit/api/test_list_forms_dialect.py` | M2 | descriptor `dialect`; `?dialect=a2ui` adds `surface_url` only (no render call); `&include=surface` adds `surface`; > `A2UI_LIST_MAX` → 400 (S8) |
| `tests/unit/services/test_a2ui_export.py` | M3 | `export_tenant` yields one `ExportedSurface` per form, never crosses tenants, isolates a raising renderer as `error` |
| `tests/unit/api/test_export_forms.py` | M3 | NDJSON framing, `published_only`, `form_uids` filter, `dialect=json_schema`, 400/415 |
| `tests/unit/extractors/test_jsonschema_sections.py` | M4 | `JsonSchemaRenderer` output with 2 sections + 1 subsection → extractor rebuilds the tree; `x-placeholder`/`x-read-only`/`x-options` round-trip; Pydantic input still yields the `"fields"` section |
| `tests/unit/services/test_a2ui_translate.py` | M4 | composition returns a `RenderedForm` whose surface passes `validate_envelope(origin=TOOL)`; missing extra → `RuntimeError` |
| `tests/unit/extractors/test_a2ui_extractor.py::test_strict_roundtrip_identity` | M5 | `A2UIFormRenderer.render(form)` → `extract` → equal `field_id`/`field_type`/section ids/required/constraints for every `FIELD_LOWERING` primitive ≠ notice/hidden |
| `…::test_strict_missing_extension_warns` | M5 | stripping `parrot_field_type` from one component → warning + heuristic fallback for that field only |
| `…::test_heuristic_basic_surface` | M5 | hand-written surface (Card/Column/TextField/ChoicePicker/Slider/DateTimeInput/CheckBox/Button) → expected FieldTypes, constraints from checks, sections from Cards, Tabs → sections |
| `…::test_heuristic_drops_unsupported` | M5 | Image/Video/Divider/unknown-catalog components → `dropped` with reasons; no raise |
| `…::test_rejects_non_surface` | M5 | an `action` envelope → `ValueError` |
| `…::test_graph_safety` | M5 | duplicate ids / dangling child / two roots → `ValueError` with details; cycle → dropped + warning; > `max_components` or > `max_depth` → `ValueError` (S6) |
| `tests/unit/api/test_import_a2ui.py` | M6 | detection predicate; 201 payload; 409 vs `?overwrite=true`; 413; 422 on a surface failing `validate_envelope` (S5); import reaches the extractor with NO LLM client configured (the 503 guard is after the branch, S5); imported `parrot_tenant` ≠ route tenant → route tenant wins; legacy `{"prompt"}` body still hits the LLM path |
| `tests/unit/test_cli.py` | M7 | click `CliRunner`: `export` writes files + report (repeated `--tenant`), `import --dry-run` prints the report, `translate` writes an envelope; missing `ai-parrot` extra → exit 2 with message; `python -m parrot_formdesigner.cli --help` works (S11) |
| `packages/ai-parrot/tests/cli/test_formdesigner_lazy.py` | M7 | `cli._lazy_commands["formdesigner"] == "parrot_formdesigner.cli"`; with the module import patched to fail, `parrot formdesigner` exits non-zero with the install hint (S11) |

### Integration Tests
| Test | Description |
|---|---|
| `tests/integration/test_a2ui_dialect_roundtrip.py::test_form_to_a2ui_to_form` | register → `GET /schema?dialect=a2ui` → `POST /forms` (surface, `overwrite=true`) → `GET /forms/{uid}` equals the original on expressible fields |
| `…::test_jsonschema_to_a2ui_preserves_sections` | `GET /schema` (json) → `translate_jsonschema_to_a2ui` → surface has one `Card` per section with the right `parrot_section_id`s |
| `…::test_export_then_import_tenant` | `POST /forms/export` NDJSON → each line imported into a second tenant → counts match, no cross-tenant leak |
| `…::test_fieldsync_golden_unchanged` | golden `GET /schema` body of a fixture form is byte-identical before/after the feature (default dialect) |

### Test Data / Fixtures
```python
# tests/unit/conftest.py additions (or module-local): a FormSchema with 2 sections (one with a subsection),
# fields covering TEXT, TEXT_AREA, NUMBER, BOOLEAN, DATE, SELECT, MULTI_SELECT, EMAIL, HIDDEN, NPS;
# `pytest.importorskip("parrot.outputs.a2ui")` on every A2UI-dependent test (pattern: tests/unit/renderers/test_a2ui_export.py:12).
# API tests build the app like tests/unit/api/test_render_dispatcher.py (aiohttp web.Application + FormRegistry fixture).
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1 — `FormSchema.dialect` exists, defaults to `json_schema`, survives `model_dump_json`/`model_validate_json`, PATCH deep-merge, clone and version snapshots; a pre-FEAT-650 `schema_json` row loads unchanged.
- [ ] AC2 — `GET /forms/{uid}/schema` with no override on a default form returns a body byte-identical to the pre-feature golden fixture (Fieldsync guarantee). `GET /forms/{uid}` keeps its code path untouched; its body gains exactly ONE additive key, `"dialect": "json_schema"` (same precedent as `is_public`/`unknown_fields`, which also appear with their defaults) — a golden test pins that the diff against the pre-feature body is that single key and nothing else (S1).
- [ ] AC3 — Precedence `?dialect=` > `Accept: application/a2ui+json` > stored is enforced; `?dialect=json_schema` forces the legacy body even on an `a2ui` form; unknown value → 400; `a2ui` without the extra → 415 with `supported`.
- [ ] AC4 — On the A2UI path the response is a `createSurface` (single, `application/a2ui+json`) or `{"messages": [...]}` when overrides were translated; every envelope passes `validate_message()`; the surface passes `validate_envelope(origin=TOOL)`; `?with_meta=true` mirrors `handle_render`.
- [ ] AC5 — Every §7 override-translation row is covered by a test; untranslatable keys produce `override_not_translatable:<key>` warnings and never an envelope.
- [ ] AC6 — `A2UIExportService.export_tenant` never yields a form from another tenant, isolates renderer failures as `error` rows, and `POST /forms/export` streams NDJSON with one line per form.
- [ ] AC7 — `parrot formdesigner export --tenant T [--tenant U] --out DIR` writes one file per form plus `export-report.json` (DB-only forms included via `load_from_storage`); `import` honours `--dry-run`/`--overwrite`; `translate` writes a validating envelope; `parrot --help` lists `formdesigner` without importing parrot-formdesigner eagerly, and `parrot formdesigner` without the satellite installed fails with an install hint (S7, S11).
- [ ] AC8 — `JsonSchemaExtractor` rebuilds sections/subsections from `x-section`/`x-subsection` (incl. section/subsection-level `depends_on`) and reads `x-placeholder`, `x-read-only`, `x-options` (single AND array-typed properties, label + disabled state), `default`, `description`; Pydantic/OpenAPI input without `x-section` still yields the single `"fields"` section. A fixture-based round-trip test (`FormSchema` → `JsonSchemaRenderer` → `JsonSchemaExtractor`) asserts every emitted `x-*` extension listed in §6 is either reconstructed or named in a documented loss list (S4).
- [ ] AC9 — Strict round-trip is identity on the **strict projection** (§7) — `form_uid`, `form_id`, `version`, `tenant`, form title/description, `section_id`/`subsection_id` + titles (ids come from the `sec-<id>`/`sub-<id>` components, so empty sections survive), and per field `field_id`, `field_uid`, `field_type`, `label`, `required`, `read_only`, `placeholder` (TextField only), `options`, `default`, the constraints expressible as checks — for every `FIELD_LOWERING` entry whose primitive is not `notice`/`hidden`. Attributes outside the projection (field/section `description`, `options_source`, `relation`, `depends_on`, `post_depends`, `meta`, `persistence`, `events`, …) are documented as not round-trippable; strict mode emits one `strict_projection_only` warning stating that. No claim beyond the projection (S3).
- [ ] AC10 — Heuristic extraction of a generic Basic surface never raises on *content*; every unsupported/unreachable component appears in `dropped` with a reason; duplicate inferred `field_id`s are suffixed and warned. Structural defects (duplicate ids, dangling children, multiple roots, cycles beyond the drop rule, > `A2UI_MAX_COMPONENTS`, > `A2UI_MAX_DEPTH`) raise `ValueError` with details and map to 422 at the API / exit 3 in the CLI (S6).
- [ ] AC11 — `POST /forms` with a surface body imports it (201 with `import` report); an existing `parrot_form_uid` → 409 unless `?overwrite=true`; bodies over `A2UI_MAX_BODY_BYTES` → 413; the legacy `{"prompt"}` body behaviour is unchanged.
- [ ] AC12 — `import parrot_formdesigner`, `parrot_formdesigner.extractors`, `.api`, `.services` succeed without `ai-parrot` installed (AST test like `test_a2ui_export.py::test_package_import_does_not_import_ai_parrot_eagerly` extended to the new modules).
- [ ] AC13 — `packages/parrot-formdesigner/docs/a2ui-renderer.md` documents the flag, precedence, export/import/translate and the loss rules.
- [ ] AC15 — Negotiated `GET /schema` enforces membership for private forms and honours `onSchemaLoaded` aborts identically under both dialects, with the JSON error body (tests in §4, S10).
- [ ] AC14 — `ruff check` clean; all new tests pass with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src`; no change to `renderers/a2ui.py`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
from parrot_formdesigner.renderers import A2UIFormRenderer, AbstractFormRenderer, JsonSchemaRenderer  # renderers/__init__.py:21-41 (A2UIFormRenderer lazy, PEP 562)
from parrot_formdesigner.renderers.a2ui import FIELD_LOWERING, field_pointer, field_id_from_pointer_token  # renderers/a2ui.py:198, 75, 92
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer      # renderers/jsonschema.py:301 (handlers.py:24 imports it this way)
from parrot_formdesigner.extractors import JsonSchemaExtractor, JSONSchemaExtractor, PydanticExtractor, ToolExtractor, YamlExtractor  # extractors/__init__.py:8-11
from parrot_formdesigner.core.resolution import resolve_rule_references     # extractors/jsonschema.py:20
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection, RenderedForm  # core/schema.py:65, 401, 229, 153, (RenderedForm imported by renderers/base.py:10)
from parrot_formdesigner.core.constraints import FieldConstraints            # extractors/jsonschema.py:13
from parrot_formdesigner.core.options import FieldOption, OptionsSource      # extractors/jsonschema.py:18
from parrot_formdesigner.core.types import FieldType                          # core/types.py:16
from parrot_formdesigner.core import UnknownFieldsPolicy                      # core/__init__.py:42, 92 (pattern for FormDialect)
from parrot_formdesigner.api import a2ui_wire                                 # api/handlers.py:30
from parrot_formdesigner.api.render import get_renderer, register_renderer, supported_formats  # api/render.py:104, 91, 109
from parrot_formdesigner.api.tenant import declared_tenant, enforce_membership_unless_public, requires_tenant  # api/tenant.py:166, 189, 100
from parrot_formdesigner.api._utils import _bump_version, _deep_merge, _loc_to_str  # api/_utils.py:61, 11, 37 (handlers.py:31)
from parrot_formdesigner.services.event_dispatcher import apply_schema_overrides, dispatch  # services/event_dispatcher.py:69, 102 (handlers.py:27)
from parrot_formdesigner.services.registry import FormAlreadyExistsError, FormRegistry, FormStorage  # services/registry.py:51, 240, 63
from parrot_formdesigner.services.storage import PostgresFormStorage         # services/storage.py:69
from parrot_formdesigner.core.events import EventResolution, FormEventAbort  # core/events.py:182, 213
from navigator.responses import JSONResponse                                  # api/handlers.py:19
# ai-parrot (OPTIONAL extra — import lazily, inside functions):
from parrot.outputs.a2ui.models import CreateSurface, Component, ComponentMetadata, Extensions, UpdateComponents, UpdateDataModel  # models.py:446, 400, 364, 341, 473, 490
from parrot.outputs.a2ui.serialization import deserialize, serialize         # serialization.py:155, 104
from parrot.outputs.a2ui.runtime.models import A2UIErrorCode, error_envelope # a2ui_wire.py:98
from parrot.outputs.a2ui.catalog import validate_envelope, validate_message  # catalog/__init__.py:743, 458
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, ProducerOrigin  # catalog/base.py:53, 99
from parrot.a2a.models import A2UI_MEDIA_TYPE                                 # a2ui_wire.py:88 (value "application/a2ui+json")
import click                                                                  # parrot/cli/toolkits.py:14 (ai-parrot pins click>=8.1.7, pyproject.toml:139)
```

### Existing Class Signatures
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class UnknownFieldsPolicy(str, Enum): ...                                   # line 51
class FormField(BaseModel):                                                  # line 65
    field_uid: uuid.UUID; field_id: str; field_type: FieldType; label: LocalizedString   # lines 123-126
    description; placeholder: LocalizedString | None; required: bool = False; default: Any = None
    read_only: bool = False; constraints: FieldConstraints | None; options: list[FieldOption] | None
    options_source; depends_on; post_depends; children; item_template; relation; meta; content_type
    accept_content_types; answer_envelope                                    # lines 127-143
class FormSubsection(BaseModel):                                             # line 153
    subsection_uid; subsection_id: str; title; description; fields: list[FormField]; depends_on; meta
SectionItem = Union[FormField, FormSubsection]                               # line 226
class FormSection(BaseModel):                                                # line 229
    section_uid; section_id: str; title; description; fields: list[SectionItem]; depends_on: DependencyRule | None; meta
class FormSchema(BaseModel):                                                 # line 401
    form_uid: uuid.UUID = Field(default_factory=uuid.uuid4)                  # line 453
    form_id: str; version: str = "1.0"; sections: list[FormSection]; cancel_allowed: bool = True   # 454-460
    created_at; tenant: str | None = None; metadata; form_type; product_bindings; published_version  # 462-469
    is_public: bool = False                                                  # line 471
    persistence: FormPersistenceConfig | None = None                         # line 473
    unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP           # line 475  ← dialect goes right after
    def iter_all_fields(self) -> Iterator[FormField]                         # line 477
    def iter_fields_recursive(self) -> Iterator[FormField]                   # line 490

# core/constraints.py — class FieldConstraints (BaseModel)
    min_length, max_length: int | None; min_value, max_value: float | None; step; pattern: str | None
    pattern_message; min_items, max_items; allowed_mime_types; max_file_size_bytes; max_inline_size_bytes   # lines 44-56

# renderers/base.py
class AbstractFormRenderer(ABC):                                             # line 58
    @abstractmethod
    async def render(self, form: FormSchema, style: StyleSchema | None = None, *, locale: str = "en",
                     prefilled: dict[str, Any] | None = None, errors: dict[str, str] | None = None) -> RenderedForm   # line 69

# renderers/a2ui.py
DEFAULT_SUBMIT_URL_TEMPLATE = "/api/v1/{tenant}/forms/{form_uid}/data"     # line 42
class A2UIFieldLowering(BaseModel): primitive: Literal["TextField","CheckBox","ChoicePicker","Slider","DateTimeInput","notice","hidden"]; props; check_functions   # line 154
FIELD_LOWERING: dict[FieldType, A2UIFieldLowering]                           # line 198 (module assert covers every FieldType, line 261)
def _extensions(m, **values) -> ComponentMetadata                            # line 281
class A2UIFormRenderer(AbstractFormRenderer):                                # line 294
    RENDERER_NAME = "a2ui"                                                   # line 309
    def __init__(self, *, submit_url_template: str = DEFAULT_SUBMIT_URL_TEMPLATE, catalog_id: str | None = None)  # line 311
    async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None) -> RenderedForm   # line 330
# component ids emitted: "root" (469), "root-title" (377), "root-description" (389), "root-status" (414),
#   "root-submit-label"/"root-submit" (423/427), "root-cancel-label"/"root-cancel" (450/454), "root-actions" (465), f"f-{field.field_id}" (649)
# root extensions: parrot_variant="form", parrot_form_uid, parrot_form_id, parrot_form_version, parrot_tenant, parrot_submit_url (474-479)
# field extensions: parrot_field_id, parrot_field_uid, parrot_field_type, parrot_section_id, parrot_subsection_id, parrot_read_only (634-642)
# tenant = form.tenant or _DEFAULT_TENANT (361); surface_id = f"form-{form.form_uid}" (484)

# renderers/jsonschema.py — JsonSchemaRenderer (line 301) emits per property:
#   x-field-type (359, 493) · x-section {section_id,title,description} / x-subsection {subsection_id,title,description} (432-447)
#   x-section-depends-on (435, 446) · x-subsection-depends-on (437) · x-options [{value,label}] (564, 577)
#   x-options-source (552, 588) · x-relation (559) · x-depends-on (609) · x-post-depends (613)
#   x-placeholder (617) · x-read-only (622) · x-parrot-rest (649) · x-content-type/x-accept-content-types/x-answer-envelope (674-678)

# extractors/jsonschema.py
class JsonSchemaExtractor:                                                   # line 67
    def extract(self, schema: dict[str, Any], *, form_id: str | None = None, title: str | None = None) -> FormSchema   # line 86
        # fields: list[FormField] = []  (line 114) → FormSchema(sections=[FormSection(section_id="fields", ...)]) (126-134) → resolve_rule_references(form) (141)
    def _property_to_field(self, *, name, prop, required, root_schema) -> FormField   # line 176 (label = prop["title"] 211; enum → options 232-236)
    def _map_type(self, prop) -> FieldType                                   # line 390 (x-field-type at 411)
    def _extract_constraints(self, prop) -> FieldConstraints                 # line 437

# api/render.py
async def handle_render(request) -> web.Response                             # line 165 (415 {"supported": supported_formats()} at 183-186; locale query 211; with_meta 215-235)
def register_renderer(format_key, renderer) -> None                          # line 91
def get_renderer(format_key) -> AbstractFormRenderer | None                  # line 104
def supported_formats() -> list[str]                                         # line 109

# api/a2ui_wire.py
A2UI_MAX_BODY_BYTES = int(os.environ.get("A2UI_MAX_DATA_MODEL_BYTES", str(1024 * 1024)))   # line 39
def _a2ui_ns() -> Any                                                        # line 77 (lazy namespace; ns.A2UI_MEDIA_TYPE at 107)
def is_a2ui_request(request, body) -> bool                                   # line 122
def unwrap_action(form, body) -> A2UIActionSubmission                        # line 164
def validation_errors(surface_id, errors) -> list[dict]                      # line 222
def confirmation(surface_id, result, *, message="Form submitted.") -> list[dict]   # line 248
def a2ui_response(envelopes: list[dict], *, status: int) -> web.Response     # line 275 (1 → a2ui media type; else {"messages": [...]})

# api/handlers.py — class FormAPIHandler
    async def list_forms(self, request) -> web.Response                      # line 724 (descriptors dict 764-800; `forms = sorted(descriptors.values(), key=lambda d: d["form_id"] or "")` then `return JSONResponse({"forms": forms})`)
    async def get_form(self, request) -> web.Response                        # line 847 (UNCHANGED by this feature)
    async def get_schema(self, request) -> web.Response                      # line 884 (schema_renderer.render 895; dispatch onSchemaLoaded 898-910; apply_schema_overrides 912-913; `return JSONResponse(content)` 914)
    async def get_style(self, request) -> web.Response                       # line 916
    async def create_blank_form(self, request) -> web.Response               # line 1075
    async def create_form(self, request) -> web.Response                     # line 1135 (_rbac_shadow_gate "create_form" 1138; LLM 503 guard 1142-1146; body parse 1148-1150; prompt required 1152-1154; create_tool.execute(prompt=..., persist=True) 1164; 201-style payload {"form_uid","title","url"} 1181-1190)
    async def update_form(self, request) -> web.Response                     # line 1329 (version bump via _bump_version 1358)
    async def patch_form(self, request) -> web.Response                      # line 1396 (merged = _deep_merge(existing.model_dump(), body) 1425)
    self.registry: FormRegistry; self.schema_renderer: JsonSchemaRenderer; self._get_tenant(request); self._assert_form_tenant(form, tenant); self._build_auth_context(request)

# api/routes.py
_TENANT_MODES = ("required", "public", "none")                               # line 81
def _wrap_auth(handler, *, tenant: str = "required")                         # line 84
def setup_form_api(app, registry, *, client=None, submission_storage=None, forwarder=None, ...)   # line 192
# routes: GET {tp}/forms (375) · POST {tp}/forms (376) · POST {tp}/forms/from-db (377) · POST {tp}/forms/blank (381)
#   GET {tp}/forms/{form_uid} tenant="public" (385) · PATCH (390) · POST .../clone (397) · GET .../schema tenant="public" (401)
#   GET .../render/{format} (408) · POST .../validate (414) · POST .../data (418)

# services/event_dispatcher.py
def apply_schema_overrides(base: dict[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]   # line 69 (shallow, top-level keys only)
async def dispatch(event, *, form, request, tenant, auth_context, payload=None, schema_dump=None, error=None) -> EventResolution   # line 102
# core/events.py: class EventResolution(BaseModel): schema_overrides: Mapping[str, Any] | None = None   # lines 182, 203

# services/registry.py
class FormStorage(ABC):  async def load(...) (95); async def list_forms(self, *, tenant=None) -> list[dict] (130 — summary dicts)   # line 63
class FormRegistry:                                                          # line 240
    def __init__(self, storage: FormStorage | None = None, app=None, default_tenant: str = "navigator", require_tenant: bool = True)   # line 275
    async def register(self, form, *, persist: bool = False, overwrite: bool = True, tenant: str | None = None) -> None   # line 466 (FormAlreadyExistsError on slug clash with a different form_uid)
    async def get(self, form_uid: uuid.UUID, *, tenant=None) -> FormSchema | None   # line 976 (read-through from storage on miss)
    async def list_forms(self, *, tenant=None) -> list[FormSchema]            # line 1102 (never cross-tenant)
    async def list_tenants(self) -> list[str]                                 # line 1197
    async def load_from_storage(self, *, tenant=None) -> int                  # line 1320
# services/storage.py
class PostgresFormStorage(FormStorage):                                      # line 69
    def __init__(self, pool=None, dsn: str | None = None, schema=DEFAULT_SCHEMA, table_name=DEFAULT_TABLE, tenant=None, min_size=2, ...)   # line 102
    async def list_forms(self, *, tenant=None) -> list[dict]                  # line 642

# parrot.outputs.a2ui (ai-parrot)
class Component(BaseModel): id; component; catalog_id(alias catalogId); child; children; weight; accessibility; checks: list[CheckRule] | None; action; metadata: ComponentMetadata | None   # models.py:400-417
class CreateSurface(A2UIMessageBase): surface_id(alias surfaceId); catalog_id; send_data_model; components: list[Component]; data_model(alias dataModel); metadata   # models.py:446-470
class UpdateComponents(A2UIMessageBase): surface_id; components: list[Component]   # models.py:473-487
class UpdateDataModel(A2UIMessageBase): surface_id; path: str | None; value: Any    # models.py:490-506
class CheckRule(BaseModel): condition: FunctionCall | DataBinding; message: str | None   # models.py:272-288
SurfaceMetadata = ComponentMetadata                                          # models.py:378
def deserialize(data: dict | str | bytes) -> A2UIAgentMessage | A2UIRendererMessage | list[A2UIAgentMessage]   # serialization.py:155
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin=ProducerOrigin.TOOL, surface_catalog_id=None) -> None   # catalog/__init__.py:743
def validate_message(message) -> None                                        # catalog/__init__.py:458
# catalog/basic: inputs.py — Button(child, action) 46 · TextField(label, value, placeholder, variant) 66 · CheckBox(label, value) 81
#   ChoiceOption(label, value) 91 · ChoicePicker(label, variant, options, value, displayStyle, filterable) 100 · Slider(label, min, max, value, steps) 120
#   DateTimeInput(value, enableDate, enableTime, min, max, label) 136 · layout.py __all__ Card, Column, Divider, List, Modal, Row, TabItem, Tabs (21)
#   media.py __all__ AudioPlayer, Icon, IconSvgPath, Image, Text, Video (21) · functions.py check names: required, regex, length, numeric, email (85-89)

# parrot/cli/__init__.py
@click.group(cls=LazyGroup) def cli()                                        # line 103
cli._lazy_commands = {... "toolkits": "parrot.cli.toolkits", ...}            # line 117 (entries for other distributions: "manuals": "parrot_tools.procedures.cli", "e2e": "parrot.e2a.cli" pattern at 124-128)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FormSchema.dialect` | `FormAPIHandler.patch_form` | `_deep_merge(existing.model_dump(), body)` then `FormSchema.model_validate` | `api/handlers.py:1425` |
| `resolve_dialect` | `FormAPIHandler.get_schema` | called after `dispatch("onSchemaLoaded")`, before `return JSONResponse(content)` | `api/handlers.py:898-914` |
| `render_a2ui_schema` | `api.render.get_renderer("a2ui")` | `renderer.render(form, locale=locale)` | `api/render.py:104`, `renderers/a2ui.py:330` |
| `render_a2ui_schema` | `a2ui_wire.a2ui_response` | framing of 1 vs N envelopes | `api/a2ui_wire.py:275` |
| `overrides_to_envelopes` | `A2UIFormRenderer._lower_field` | re-lower a patched `FormField` copy for `properties.<id>` overrides (private method — the task pins the call; if renamed the task fails loudly, never guesses) | `renderers/a2ui.py:606` |
| `A2UIExportService.export_tenant` | `FormRegistry.load_from_storage` / `list_forms` | `await registry.load_from_storage(tenant=t)` when `registry.storage is not None`, then `list_forms(tenant=t)` | `services/registry.py:1320, 1102` |
| `export_forms` | `setup_form_api` | `app.router.add_post(f"{tp}/forms/export", _wrap_auth(handler.export_forms))` | `api/routes.py:397` |
| `JsonSchemaExtractor.extract` (sections) | `JsonSchemaRenderer._build_structural_schema` | reads `x-section`/`x-subsection` dicts it emits | `renderers/jsonschema.py:432-447` |
| `translate_jsonschema_to_a2ui` | `JsonSchemaExtractor.extract` → `A2UIFormRenderer.render` | composition | `extractors/jsonschema.py:86`, `renderers/a2ui.py:330` |
| `A2UIExtractor.extract` | `parrot.outputs.a2ui.serialization.deserialize` | parse, then `message.create_surface` (alias `createSurface`) must be a `CreateSurface` | `serialization.py:155`, `models.py:695-718` |
| `A2UIExtractor._field_from_component` | `renderers/a2ui.py` vocabulary | `parrot_field_id`/`parrot_field_type`/… extension keys; `field_id_from_pointer_token` | `renderers/a2ui.py:634-642, 92` |
| `_import_a2ui_surface` | `FormRegistry.get` / `register` | conflict check then `register(form, persist=True, overwrite=True, tenant=tenant)` | `services/registry.py:976, 466` |
| `is_a2ui_surface_body` | `FormAPIHandler.create_form` | branch after `_rbac_shadow_gate`, before the LLM 503 guard | `api/handlers.py:1138-1146` |
| `parrot_formdesigner.cli.formdesigner` | `parrot.cli.LazyGroup` | `_lazy_commands["formdesigner"]` | `parrot/cli/__init__.py:117` |

### Does NOT Exist (Anti-Hallucination)
- ~~`FormDialect`~~, ~~`FormSchema.dialect`~~ — added by M1.
- ~~`parrot_formdesigner.api.dialect`~~, ~~`resolve_dialect`~~, ~~`render_a2ui_schema`~~, ~~`overrides_to_envelopes`~~ — added by M2.
- ~~`parrot_formdesigner.services.a2ui_export`~~ / ~~`A2UIExportService`~~ / ~~`ExportedSurface`~~ — added by M3 (`tests/unit/renderers/test_a2ui_export.py` only tests the lazy re-export of the renderer).
- ~~`parrot_formdesigner.services.a2ui_translate`~~ / ~~`translate_jsonschema_to_a2ui`~~ — added by M4.
- ~~`parrot_formdesigner.extractors.a2ui`~~ / ~~`A2UIExtractor`~~ / ~~`ExtractedForm`~~ — added by M5.
- ~~`a2ui_wire.is_a2ui_surface_body`~~ — added by M6; `is_a2ui_request` only detects `action` envelopes.
- ~~`FormAPIHandler.export_forms`~~, ~~`FormAPIHandler._import_a2ui_surface`~~, ~~`POST /forms/export`~~ — added by M3/M6.
- ~~`parrot_formdesigner/cli.py`~~, ~~`[project.scripts]` in parrot-formdesigner~~ — the package has no CLI; the `parrot` entry point is `parrot.cli:cli` in ai-parrot (`packages/ai-parrot/pyproject.toml:200`).
- ~~`?dialect=` query param~~, ~~`Accept: application/a2ui+json` negotiation~~ — not implemented anywhere today; only `/render/{format}` serves A2UI.
- ~~`POST /forms` accepting a `FormSchema` or surface body~~ — today it is LLM-prompt only (`body["prompt"]` required, 503 without client).
- ~~`JsonSchemaExtractor` reading `x-section` / `x-subsection` / `x-section-depends-on` / `x-subsection-depends-on` / `x-placeholder` / `x-read-only` / `x-options`~~ — it does not (verified by grep over `extractors/jsonschema.py`); every extracted form has one `"fields"` section.
- ~~`A2UIFormRenderer.accepts_tenant`~~ — no such attribute; `handle_render` only passes `tenant` to renderers that declare it (`api/render.py:48`); the A2UI renderer derives tenant from `form.tenant` (`renderers/a2ui.py:361`).
- ~~`FormStorage.list_forms()` returning `FormSchema` objects~~ — returns summary dicts (`services/registry.py:130`, `storage.py:642`).
- ~~`parrot.outputs.a2ui.builders.build_form()` as the backend~~ — FEAT-544 composes components directly; the dialect layer must not route through `builders`.
- ~~A `Form` catalog component~~ — forbidden (dialect spec G6).
- ~~A `/forms/{uid}/a2ui` sibling route~~ — rejected in FEAT-544 (U1).
- ~~A reserved-segment list for `form_uid` path params~~ — the FEAT-429 guard (`api/tenant.py`, `tests/unit/api/test_reserved_segment_guard.py`) protects **tenant** slugs only; `POST /forms/export` is a literal sibling like `/forms/blank` and `/forms/from-db` (`api/routes.py:377-381`).
- ~~`docs/formdesigner/` at the repo root~~ — formdesigner docs live in `packages/parrot-formdesigner/docs/`.

### Edit Sites (Blueprint Anchors)

Verified against: `e0d88994a` (dev, 2026-10-10)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | `class UnknownFieldsPolicy(str, Enum):` | `core/schema.py:51` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | `    unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP` | `core/schema.py:475` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` | MODIFY | `    UnknownFieldsPolicy,` (import block) and `    "UnknownFieldsPolicy",` (`__all__`) | `core/__init__.py:42`, `:92` | 1 each |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/dialect.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `        return JSONResponse(content)` (end of `get_schema`; preceded by `content = apply_schema_overrides(content, dict(resolution.schema_overrides))`) | `api/handlers.py:914` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `        forms = sorted(descriptors.values(), key=lambda d: d["form_id"] or "")` (end of `list_forms`) | `api/handlers.py:825` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `    async def get_style(self, request: web.Request) -> web.Response:` (insert `export_forms` before it) | `api/handlers.py:916` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `    async def create_form(self, request: web.Request) -> web.Response:` | `api/handlers.py:1135` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | `    app.router.add_post(f"{tp}/forms/{{form_uid}}/clone", _wrap_auth(handler.clone_form))` | `api/routes.py:397` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py` | MODIFY | `def is_a2ui_request(request: web.Request, body: Any) -> bool:` | `api/a2ui_wire.py:122` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_export.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_translate.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py` | MODIFY | `        fields: list[FormField] = []` | `extractors/jsonschema.py:114` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py` | MODIFY | `        return resolve_rule_references(form)` | `extractors/jsonschema.py:141` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py` | MODIFY | `        # Handle enum → SELECT` (inside `_property_to_field`) | `extractors/jsonschema.py:231` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/a2ui.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/__init__.py` | MODIFY | `from .yaml import YAMLExtractor, YamlExtractor` | `extractors/__init__.py:10` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/cli.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | `    "toolkits": "parrot.cli.toolkits",` | `parrot/cli/__init__.py:117` | 1 |
| `packages/parrot-formdesigner/pyproject.toml` | MODIFY | `dependencies = [` (core dependency list — `click` is added here, S11) | `pyproject.toml:33` | 1 |
| `packages/parrot-formdesigner/docs/a2ui-renderer.md` | MODIFY | `## Usage` | `docs/a2ui-renderer.md:33` | 1 |
| `packages/parrot-formdesigner/tests/integration/test_a2ui_dialect_roundtrip.py` | CREATE | — | — | — |

- `/sdd-task` MUST re-run `grep -c` for every row (all anchors above were pinned by `grep -n` at `e0d88994a`; counts are 1 everywhere).

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- **Lazy A2UI imports everywhere.** New modules copy `api/a2ui_wire._a2ui_ns()` (line 77) — import `parrot.outputs.a2ui.*` inside functions, raise `RuntimeError("… requires the 'ai-parrot' extra")` with the same wording. Predicates (`is_a2ui_surface_body`, `resolve_dialect`) must work without the extra.
- **Dialect precedence** (G2): `request.query.get("dialect")` → if present must be a `FormDialect` value (else 400); else `Accept` header contains `application/a2ui+json` (exact media type, no wildcard match) → A2UI; else `form.dialect`. A2UI requested + `get_renderer("a2ui") is None` → 415 `{"supported": supported_formats()}` (same payload as `handle_render`, `api/render.py:183-186`).
- **Override translation table** (`overrides_to_envelopes`, deterministic, order of keys as in `overrides`):

  | `schema_overrides` key | Envelope(s) | Notes |
  |---|---|---|
  | `title` (str) | `updateComponents` replacing `root-title` (`Text`) | if the surface has no `root-title`, add it as the first child of `root` via one `updateComponents` for `root` + the new `Text` |
  | `description` (str) | `updateComponents` replacing `root-description` | same create-if-missing rule |
  | `properties.<field_id>.title` / `.description` / `.x-placeholder` / `.x-read-only` / `.x-options` / `.enum` | one `updateComponents` with the re-lowered component(s) for `f-<field_id>` (`A2UIFormRenderer._lower_field` on a patched copy of the `FormField`) | unknown `<field_id>` → warning `override_unknown_field:<id>` |
  | `properties.<field_id>.default` | `updateDataModel{path: "/answers/<escaped id>", value}` | plus the re-lowered component when the primitive binds `value` literally |
  | `required` (list[str]) | re-lower every field whose `required` changes; one `updateComponents` with all of them | fields not in the surface → warning |
  | anything else (`$schema`, `type`, `additionalProperties`, `x-*` at top level, …) | none | warning `override_not_translatable:<key>` |

  All emitted envelopes carry `surfaceId = f"form-{form.form_uid}"` and are `serialize()`d dicts; each passes `validate_message()` in tests.
- **NDJSON streaming**: `web.StreamResponse(status=200, headers={"Content-Type": "application/x-ndjson"})`, `await resp.prepare(request)`, one `json.dumps(item.model_dump(mode="json")) + "\n"` per `ExportedSurface`; renderer exceptions are caught per form in the service (never in the handler).
- **Heuristic primitive map** (`A2UIExtractor`, Basic catalog only):

  | Component (variant / flags) | `FieldType` | Extras |
  |---|---|---|
  | `TextField` / `TextField:shortText` | `TEXT` | `placeholder` ← `placeholder` |
  | `TextField:longText` | `TEXT_AREA` | |
  | `TextField:number` | `NUMBER` | |
  | `TextField:obscured` | `PASSWORD` | |
  | `CheckBox` | `BOOLEAN` | |
  | `ChoicePicker` (single) | `SELECT` | `options` ← `options[{label,value}]` |
  | `ChoicePicker:multipleSelection` | `MULTI_SELECT` | |
  | `Slider` | `NUMBER` | `constraints.min_value/max_value` ← `min`/`max`; `step` ← `(max-min)/steps` when `steps` |
  | `DateTimeInput` enableDate & !enableTime | `DATE` | `constraints` from `min`/`max` are not expressible → warning |
  | `DateTimeInput` !enableDate & enableTime | `TIME` | |
  | `DateTimeInput` both | `DATETIME` | |
  | `Button` whose `action.event.name == "form.submit"` / `"form.cancel"` | — | `cancel_allowed` ← presence of a cancel button; not a field |
  | `Card` | section | title ← first `Text` child; `Column`/`Row` nested in a `Card` with its own leading `Text` → `FormSubsection` |
  | `Tabs` / `TabItem` | one section per `TabItem` | warning `tabs_flattened` |
  | `Text` immediately preceding an input with no `label` | that input's `label` | brainstorm Q4 default — see §8 |
  | `Image`, `Video`, `AudioPlayer`, `Icon`, `Divider`, `List`, `Modal`, any non-Basic component | dropped | `DroppedComponent(reason="unsupported_component" | "not_in_basic_catalog")` |

  `checks` → constraints: `required` → `required=True`; `regex(pattern)` → `constraints.pattern`; `length(min,max)` → `min_length/max_length`; `numeric(min,max)` → `min_value/max_value`; `email` → `field_type=EMAIL` (when on a `TextField`). `field_id` = last token of the `value` binding path (`field_id_from_pointer_token`), else the component id with a leading `f-` stripped; collisions get `_2`, `_3` … and a warning. Strict mode uses `parrot_field_type` directly and only validates that `FIELD_LOWERING[field_type].primitive == component.component` (mismatch → warning, extension wins).
- **Strict projection** (what `A2UIFormRenderer` emits and `A2UIExtractor` strict mode can therefore recover, S3): root extensions (`parrot_form_uid`, `parrot_form_id`, `parrot_form_version`, `parrot_tenant`), `root-title`/`root-description` Texts, `sec-<section_id>` Cards + `sec-<section_id>-title` Texts, `sub-<subsection_id>` Columns + `sub-<subsection_id>-title` Texts (`renderers/a2ui.py:544-598`), per-field `parrot_field_id/_uid/_type/_section_id/_subsection_id/_read_only`, `label`, `placeholder` (TextField, line 679), `options`, `checks`, and the `dataModel.answers` default. Everything else is outside the projection and is NOT reconstructed — the renderer is not extended to carry it (FEAT-544 stays frozen; a `parrot_*` side-channel for descriptions/dependencies is a follow-up).
- **Tenant stamping**: import and translate set `FormSchema.tenant` from the route/CLI tenant, never from `parrot_tenant` in the surface (cross-tenant surfaces import into the caller's tenant; `parrot_submit_url` is discarded — the renderer regenerates it).
- **Tests without the extra**: every A2UI test starts with `pytest.importorskip("parrot.outputs.a2ui")`; AST import-hygiene test extended to `api/dialect.py`, `services/a2ui_export.py`, `services/a2ui_translate.py`, `extractors/a2ui.py`, `cli.py`.
- Conventions: Google docstrings, strict typing, `self.logger`/module `logger`, no `print` (click `echo` is the CLI output channel), 120 cols, `ruff` clean.

### Known Risks / Gotchas
- **Golden Fieldsync body.** The only way to prove AC2 is a committed golden fixture of `GET /schema` for a representative form captured *before* M2 lands; the task that adds the A2UI branch must add the golden test first (red/green).
- **`get_schema` is mounted `tenant="public"`.** The A2UI branch runs after `enforce_membership_unless_public` and after `onSchemaLoaded`; it must not add a code path that answers before those checks (S2). Lifecycle aborts (`FormEventAbort`) and tenant/membership failures keep today's JSON error bodies and status codes regardless of the negotiated dialect — negotiation happens after them, so no A2UI `error` envelope is ever produced by `get_schema`/`list_forms` (S10).
- **`list_forms` enrichment cost.** `?dialect=a2ui` alone is a manifest (`surface_url`, zero renders); inline envelopes need `include=surface`, are O(N) renders and are bounded by `A2UI_LIST_MAX` (default 50) with a 400 pointing to the export endpoint (S8).
- **`A2UIAgentMessage.create_surface`** (alias `createSurface`, `models.py:695-718`) is the attribute the extractor reads after `deserialize()`; `None` means the payload is not a surface → `ValueError`.
- **Private `_lower_field` dependency.** `overrides_to_envelopes` re-lowers single fields through `A2UIFormRenderer._lower_field` (`renderers/a2ui.py:606`). It is private; the task pins the exact call and its test fails loudly if FEAT-544 renames it. Alternative (rejected): re-render the whole form and diff — non-deterministic ids are not an issue (ids are `f-<field_id>`), but it doubles render cost for a rare path.
- **Import of a surface with `sendDataModel` literal values.** `dataModel.answers.*` literals are mapped to `FormField.default`; `errors`/`submission` subtrees are ignored.
- **Legacy pre-v1.0 envelopes.** `deserialize` normalises them with a `DeprecationWarning`; the extractor surfaces it as warning `legacy_envelope_normalised`.
- **CLI DSN handling.** `--dsn`/`FORMDESIGNER_DSN` is required for `export`/`import` (not for `translate`); the CLI must `await storage.close()` (`services/storage.py:380`) before exit.
- **Reserved slugs.** `POST /forms/export` is a literal sibling of `/forms/blank`; the FEAT-429 guard concerns tenant slugs, so a tenant named `export` is already rejected by that guard — nothing new to add.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `ai-parrot` (optional extra `ai-parrot`/`a2ui`) | `>=1.2.1` | `parrot.outputs.a2ui` models, `deserialize`, `validate_envelope`, Basic catalog — already the FEAT-544 pin |
| `click` | `>=8.1.7` | `parrot formdesigner` group; declared in parrot-formdesigner core `dependencies` (today only transitive via ai-parrot) so `python -m parrot_formdesigner.cli` works standalone (S11) |
| `pydantic` | v2 (existing) | `FormDialect`, `ExportedSurface`, `ExtractedForm` |
| `aiohttp` | existing | `web.StreamResponse` NDJSON |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Which GET routes honour the dialect flag? — *Resolved in brainstorm*: only `/schema` and `/forms`. `GET /forms/{uid}` ALWAYS returns the raw `FormSchema` (it is the form's identity, used by PUT/PATCH/clone/admin UI).
- [x] `onSchemaLoaded.schema_overrides` on the A2UI path of `GET /schema`? — *Resolved in brainstorm*: translate them — the A2UI response is a `createSurface` followed by `updateComponents`/`updateDataModel` envelopes derived from the overrides; overrides that cannot be mapped to a component are reported as warnings. (§7 translation table.)
- [x] Import conflict policy — *Resolved in brainstorm*: 409 unless `?overwrite=true` (CLI `--overwrite`), same contract as `FormRegistry.register(overwrite=...)`; with overwrite the form is replaced and its version bumped.
- [x] Bulk export granularity + `--all-tenants` — *Decided in spec*: `POST /forms/export` streams NDJSON (never a single array); the HTTP endpoint is single-tenant (route tenant); the CLI takes `--tenant` repeatably and there is NO `--all-tenants` in v1 because `FormRegistry.list_tenants()` is a cache view and `PostgresFormStorage` is per-tenant-schema (codex S7). — *Owner: Jesus Lara (confirm on review)*
- [x] Heuristic extractor: `Text` immediately before an unlabeled input — *Decided in spec*: used as that input's `label` (§7 table); a `Text` that is the first child of a `Card` is the section title instead. — *Owner: Jesus Lara (confirm on review)*
- [x] HTTP endpoint for JSON-Schema → A2UI translation in v1? — *Decided in spec*: no; library + CLI only (Non-Goals). — *Owner: Jesus Lara (confirm on review)*
- [x] `click` dependency placement — *Resolved via codex S11*: core `dependencies` of parrot-formdesigner, so `parrot_formdesigner.cli` is importable standalone and the `parrot` lazy entry is a thin, cleanly-failing integration.
- [ ] Should `GET /forms` include `dialect` for DB-only rows (requires a `registry.get()` per row) or only for in-memory entries (proposed)? — *Owner: implementer (M2)*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: completed (codex-cli 0.160.0, reasoning high, 11 suggestions, every `affected_path` verified inside the repo)
> · Transcript: `sdd/state/FEAT-650/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Keep the persisted dialect out of legacy response serialization (api) | CONFIRM (partial) | The one additive key on `GET /forms/{uid}` follows the `is_public`/`unknown_fields` precedent, so the proposed "omit when default" projection is REJECTED as a special case; the golden byte-level test for old persisted forms is adopted and pins that the diff is exactly that key. `/schema` is unaffected (JsonSchemaRenderer builds its own structure). | §5 AC2 |
| S2 | Centralize dialect negotiation after authorization and before rendering (architecture) | CONFIRM | Matches M2: `resolve_dialect` runs after membership + `onSchemaLoaded`, no new early-return path; override handling is defined (translate). | §3 M2, §7 Known Risks |
| S3 | Define a real strict-round-trip fidelity boundary (architecture) | CONFIRM | The renderer does not emit descriptions/dependencies/options_source; sections are recoverable via `sec-<id>`/`sub-<id>` ids. The spec now names the exact strict projection and forbids claims beyond it; the renderer stays frozen (follow-up for a `parrot_*` side-channel). | §5 AC9, §7 Strict projection |
| S4 | Test JSON-Schema round trips against every emitted extension (testing) | CONFIRM | `items.enum`+`x-options` for array-typed props, `default`, `description`, disabled options and both dependency levels were missing from M4; added to the extractor contract and to AC8 with a fixture round-trip. | §3 M4, §5 AC8 |
| S5 | Separate createSurface import detection from action detection (api) | CONFIRM | Already a distinct predicate and branch before the 503 guard; adds `validate_message` + `validate_envelope(origin=TOOL)` → 422 on invalid surfaces and a test that import works with no LLM client. | §3 M6, §4 |
| S6 | Make extraction graph-safe and resource-bounded (risk) | CONFIRM | `validate_envelope` runs before any walk (duplicate ids, dangling children, missing root), cycles are dropped+warned, `A2UI_MAX_IMPORT_COMPONENTS`/`A2UI_MAX_IMPORT_DEPTH` added. | §3 M5, §5 AC10 |
| S7 | Do not build bulk export on the cache-only registry view (architecture) | CONFIRM | `export_tenant` now always hydrates from storage first; `export_all_tenants`/`--all-tenants` removed (list_tenants is a cache view, storage is per-tenant-schema); `published_only` defined on `published_version`. | §3 M3/M7, §8 |
| S8 | Avoid embedding full surfaces in list descriptors (alternative) | CONFIRM | `?dialect=a2ui` on the list is now a manifest (`surface_url`); inline envelopes only with `include=surface`, capped by `A2UI_LIST_MAX`. | §2 wire shapes, §3 M2 |
| S9 | Preserve explicit failure semantics when the extra is absent (risk) | CONFIRM | Already designed: 400 (unknown dialect) vs 415 (`a2ui` unavailable), never a silent legacy fallback; CLI exit 2. Recorded explicitly. | §7 Patterns, §5 AC3 |
| S10 | Add lifecycle, authorization and error-path tests for negotiated GETs (testing) | CONFIRM | Added tests for private-form membership, `onSchemaLoaded` abort and public access under both dialects; abort bodies stay JSON. | §4, §5 AC15 |
| S11 | Treat the CLI as an optional integration with explicit dependency ownership (alternative) | CONFIRM | `click` moves to parrot-formdesigner core deps, `cli.py` gets `main()`, the lazy entry must fail with an install hint; resolves the open `click` question. | §3 M7, §7 External Dependencies, §8 |

Summary: **11** confirmed (S1 partial: projection rejected, test adopted) · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree (`feat-FEAT-650-a2ui-dialect-formbuilder`, from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (evidence in parentheses):
  - M2 → M1 (`resolve_dialect` returns `FormDialect`; `get_schema` reads `form.dialect`).
  - M6 → M5 (`_import_a2ui_surface` calls `A2UIExtractor.extract`), M6 → M1 (201 payload echoes `form.dialect`).
  - M4b (`translate_jsonschema_to_a2ui`) → M4a (extractor fidelity) — same module, one task chain.
  - M7 → M3, M4, M5 (CLI commands call the three services).
  - M8 → M1–M7 (docs + integration round-trips).
  - M3 has no edge to M1/M2/M4/M5 (export only needs the registry and the FEAT-544 renderer) — runs concurrently with them. (`export_all_tenants` was removed per S7; nothing depends on it.) M5 has no edge to M1–M4 — runs concurrently.
- **Shared files** (tasks serialized on them): `api/handlers.py` (M2 `get_schema`/`list_forms`, M3 `export_forms`, M6 `create_form`), `api/a2ui_wire.py` (M6 only), `extractors/__init__.py` (M5 only), `core/schema.py` (M1 only), `cli.py` (M7 only — three commands may be one task or three serialized tasks).
- **Exclusive resources**: none (no extension rebuild, no lockfile regeneration — the `click` extra edit is declarative; `uv lock` is not run inside the worktree).
- **Cross-feature dependencies**: none open. FEAT-544 (`a2ui-form-output-renderer`) and FEAT-551 (`msteams-formdesigner-renderer`) are merged. FEAT-640 (`formdesigner-venue-tables`, draft) touches `services/` tables only. The one-line `parrot/cli/__init__.py` edit is shared with any concurrent feature registering a CLI group — trivial merge.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-10 | Jesus Lara | Initial draft from accepted brainstorm (Option A); §3 Q&A resolutions folded in; codex design research (11 suggestions) triaged into §2–§8 |
