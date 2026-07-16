---
type: Wiki Overview
title: 'Feature Specification: parrot-formdesigner Structural Refactor'
id: doc:sdd-specs-formdesigner-refactor-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: and JSON REST endpoints in the same package. As the package matured and started
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: parrot-formdesigner Structural Refactor

**Feature ID**: FEAT-152
**Date**: 2026-05-07
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD — Wave 1 targets `parrot-formdesigner` 0.2.0 (breaking package layout); Wave 2 capabilities ship as 0.3.x point releases.

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot-formdesigner` started as a proof of concept that bundled HTML pages
and JSON REST endpoints in the same package. As the package matured and started
to be embedded in the `navigator` ecosystem, several POC-era decisions now
violate conventions and slow down evolution:

- **Eager top-level imports**: `src/parrot_formdesigner/__init__.py` (126 LoC)
  imports every renderer, extractor, tool, service and handler at module load
  time. Importing the package pulls in `aiogram`, `aiohttp`, validators, all
  three tool classes, and renderer templates whether the consumer needs them
  or not.
- **Conditional `navigator_auth` import**: `handlers/routes.py:31-35` does
  `try/except ImportError` for `navigator_auth.decorators` and falls back to
  open routes when the package is missing. The product is no longer expected
  to run unauthenticated; navigator-auth's own `noauth` backend covers the
  dev-mode escape hatch.
- **Per-format URLs**: `/api/v1/forms/{form_id}/html` is hard-coded
  (`handlers/routes.py:153`); adding XML or PDF would mean adding a new route
  per format. There is no content negotiation and no single render dispatcher.
- **No toolbar API**: `tools/field_helpers.py` already has
  `list_supported_form_field_types()` and `get_form_field_schema_snippets()`,
  but they are only callable from Python — there is no REST helper a UI
  toolbar could consume to populate a control palette with metadata.
- **Missing renderers**: no XML output (XForms / XFA) and no PDF output
  (AcroForm-fillable). Both are real requirements for the form-designer use
  case (interoperability + offline form filling).
- **No granular edit API**: forms are edited via `PUT` (full replace) or
  `PATCH` with RFC 7396 merge semantics (`handlers/api.py:468-517`). There is
  no way to express atomic "move field", "add section", "duplicate field"
  operations from the UI without re-sending the whole form, and merge-patch
  on arrays replaces the whole list — fragile against concurrent edits.
- **HTML pages mixed with REST**: `FormPageHandler`, `templates.py`
  (457 LoC of inline HTML) and `TelegramWebAppHandler` live next to the pure
  JSON API in the same `handlers/` directory.

Affected: navigator-api consumers embedding the package, the form-designer UI
team that needs a stable control palette + edit API, and downstream agents
(MS Teams, Telegram) that need format negotiation per channel.

### Goals

- Empty `__init__.py` to package metadata only — consumers import from
  submodules (`parrot_formdesigner.core`, `parrot_formdesigner.api`, etc.).
- Split package into `parrot_formdesigner.api` (REST) and
  `parrot_formdesigner.ui` (HTML + Telegram WebApp) sub-packages, both
  shipped in the same wheel.
- Promote `navigator-auth` to a hard dependency; remove the
  `try/except ImportError` block in `handlers/routes.py`. Dev-mode runs
  delegate to navigator-auth's `NoAuth` backend on the consumer side.
- Introduce a path-param render dispatcher
  `GET /api/v1/forms/{form_id}/render/{format}` that delegates to renderers
  registered by name. `/schema` and `/style` remain dedicated routes (they
  return contract artifacts, not visual renders).
- Add an extensible **form controls registry** with metadata (icon,
  category, snippet, render hints, supports_constraints, is_container) and
  expose it via `GET /api/v1/form-controls`.
- Ship two new renderers behind the dispatcher:
  - **XForms 1.1 (W3C) export** — `application/xml`, export only.
  - **PDF AcroForm fillable** — `application/pdf`, via `reportlab`.
- Ship a transactional batched-edit endpoint
  `PATCH /api/v1/forms/{form_id}/operations` with a Pydantic-discriminated
  operations envelope (atomic; all-or-nothing).

### Non-Goals (explicitly out of scope)

- **Backwards compatibility** with the old `from parrot_formdesigner import
  setup_form_routes` import path. Consumers migrate to `setup_form_api` /
  `setup_form_ui` in lockstep.
- **XForms round-trip / parser** — V1 is export only. No XForms → FormSchema
  conversion.
- **XFA renderer** — not in V1.
- **HTML→PDF pipeline** (e.g., WeasyPrint) — V1 PDF goes through `reportlab`
  AcroForm only; the goal is a fillable PDF, not a static print.
- **Plugin / entry-point runtime** (Option C in the brainstorm) — rejected
  as over-engineering for V1; in-tree decorator-based registration is
  sufficient. See `proposals/formdesigner-refactor.brainstorm.md` Option C.
- **Big-bang single release** (Option A in the brainstorm) — rejected for
  review-fatigue and integration-risk reasons; we ship in two waves.
- Changes to `core/schema.py` (`FormSchema`, `FormField`, `FormSection`,
  `RenderedForm`) — the refactor is around them, not on them.
- Changes to `services/registry.py`, `services/submissions.py`,
  `services/forwarder.py`, or the `POST /forms/{id}/data` submissions flow.
- Moving `tools/` (Python tool classes for agents). Per Q6 below, the
  brainstorm recommendation is to keep `tools/` at the package root.

---

## 2. Architectural Design

### Overview

Two SDD waves on the same `dev` base branch:

**Wave 1 — Skeleton & policy (single sequential worktree, blocking):**

1. Split `parrot_formdesigner.api` (REST, hard-imports `navigator_auth`) and
   `parrot_formdesigner.ui` (HTML + Telegram WebApp, opt-in).
2. Empty `__init__.py` — only `__version__` + metadata. NO submodule imports.
3. Promote `navigator-auth`, `lxml`, `reportlab` to hard deps in
   `pyproject.toml`. Remove the `try/except ImportError` block.
4. Introduce the render dispatcher route
   `GET /api/v1/forms/{form_id}/render/{format}` backed by a name-keyed
   `dict[str, AbstractFormRenderer]`. V1 dispatcher initially serves `html`
   and `adaptive`; `xml` and `pdf` return `415 Unsupported Media Type` with
   `{"supported": [...]}` until Wave 2 plugs them in.
5. Define the abstract registry for form controls (`controls/registry.py`)
   and seed it with every `FieldType` enum value in `controls/builtin.py`.
   No new control types yet; the seed mirrors `_FIELD_SCHEMA_SNIPPETS`.

**Wave 2 — Independent capability tasks (parallelizable in worktrees):**

- **2a. XForms exporter** — new `renderers/xforms.py`. Plugs into the
  dispatcher under the `xml` format key.
- **2b. PDF AcroForm renderer** — new `renderers/pdf.py`. Plugs into the
  dispatcher under the `pdf` format key.
- **2c. Form controls REST endpoint** — `GET /api/v1/form-controls` backed
  by the Wave 1 registry, returning the agreed metadata shape.
- **2d. Edit operations API** —
  `PATCH /api/v1/forms/{form_id}/operations` with a Pydantic-discriminated
  operations envelope, atomic transactional semantics, optional `If-Match`
  concurrency control.

The dispatcher / registry abstractions introduced in Wave 1 are deliberately
in-tree decorator-based registration — not entry-point plugins. Promotion
to entry-point discovery is a future concern, not V1.

### Component Diagram

```
                                       ┌──────────────────────────┐
                                       │   navigator_auth         │
                                       │  (HARD dependency)        │
                                       └─────────┬────────────────┘
                                                 │ is_authenticated, user_session
                                                 ▼
┌──────────────────────────┐  setup_form_api(app, registry, ...)
│  parrot_formdesigner.api │◄──────────────────────────┐
│                          │                           │
│  routes.py               │     ┌──────────────────┐  │  (consumer aiohttp app)
│  handlers.py             │ ──► │ render dispatcher│  │
│  render.py               │     │ dict[str, AFR]   │  │
│  controls.py             │     └────────┬─────────┘  │
│  operations.py           │              │
│  _utils.py               │              ▼
└────────────┬─────────────┘     renderers/{html5,jsonschema,adaptive_card,
             │                              telegram, xforms, pdf}
             │                                ▲
             │                                │
             │      controls/registry.py ◄────┘
             │      controls/builtin.py
             │
             ▼
┌──────────────────────────┐  setup_form_ui(app, registry, ...)
│  parrot_formdesigner.ui  │◄────────────────────────────────────────────────
│                          │
│  routes.py               │     ┌──────────────────┐
│  handlers.py             │ ──► │ HTML pages       │  protect_pages opt-in
│  telegram.py             │     │ Telegram WebApp  │  (public for Telegram)
│  templates.py            │     └──────────────────┘
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐  reused unchanged
│  parrot_formdesigner     │
│  .core / .services       │
│  .extractors / .tools    │
│  .renderers (extended)   │
└──────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot_formdesigner.core.schema.FormSchema` | reused unchanged | Refactor is around it, not on it. |
| `parrot_formdesigner.services.registry.FormRegistry` | reused unchanged | Callers move; API stays. |
| `parrot_formdesigner.services.validators.FormValidator.check_schema()` | reused | `/operations` calls it post-apply to detect circular `depends_on`. |
| `parrot_formdesigner.renderers.base.AbstractFormRenderer` | extended | New `XFormsRenderer`, `PdfRenderer` subclasses. |
| `parrot_formdesigner.tools.field_helpers._FIELD_SCHEMA_SNIPPETS` | reused | Seed payload for `controls/builtin.py`. |
| `parrot_formdesigner.handlers.api.FormAPIHandler` | migrated | Methods move to `api/handlers.py`; `_deep_merge`, `_bump_version`, `_loc_to_str` move to `api/_utils.py`. |
| `parrot_formdesigner.handlers.routes._wrap_auth` | retired | Replaced by hard `is_authenticated` / `user_session` decorators in `api/routes.py`. |
| `navigator_auth.decorators.is_authenticated` / `user_session` | hard import | No more `try/except`; package fails to import if `navigator-auth` is missing. |
| `lxml.etree` | new direct use | XForms emission with namespaces. |
| `reportlab.pdfgen.canvas.Canvas` + `canvas.acroForm` | new direct use | PDF AcroForm. |
| navigator-api consumers | breaking | `setup_form_routes` splits into `setup_form_api` + `setup_form_ui`. |

### Data Models

```python
# api/render.py — dispatcher state (no new persistent model)
RENDERER_REGISTRY: dict[str, AbstractFormRenderer] = {
    "html": HTML5Renderer(...),
    "adaptive": AdaptiveCardRenderer(...),
    # Wave 2 fills in:
    # "xml": XFormsRenderer(),
    # "pdf": PdfRenderer(),
}

# controls/registry.py
class FieldControlMetadata(BaseModel):
    type: str                      # FieldType.value or extension type id
    label: str
    description: str
    category: str                  # "basic" | "selection" | "media" | "layout" | ...
    icon: str                      # icon hint (consumer-defined glyph name)
    snippet: dict[str, Any]        # JSON Schema snippet seed
    render_hint: str               # "input" | "select" | "container" | ...
    supports_constraints: bool
    is_container: bool = False

# api/operations.py — Pydantic discriminated union
class _OpBase(BaseModel):
    op: str

class AddSection(_OpBase):
    op: Literal["add_section"]
    section: FormSection
    position: int | None = None

class AddField(_OpBase):
    op: Literal["add_field"]
    section_id: str
    field: FormField
    position: int | None = None

class MoveField(_OpBase):
    op: Literal["move_field"]
    from_: dict        # alias "from" — {"section_id": str, "field_id": str}
    to: dict           # {"section_id": str, "position": int}

class RemoveField(_OpBase):
    op: Literal["remove_field"]
    section_id: str
    field_id: str

class UpdateField(_OpBase):
    op: Literal["update_field"]
    section_id: str
    field_id: str
    patch: dict[str, Any]   # RFC 7396 merge applied to a single FormField

class UpdateSectionMeta(_OpBase):
    op: Literal["update_section_meta"]
    section_id: str
    patch: dict[str, Any]

class UpdateFormMeta(_OpBase):
    op: Literal["update_form_meta"]
    patch: dict[str, Any]

class DuplicateField(_OpBase):
    op: Literal["duplicate_field"]
    from_: dict             # {"section_id": str, "field_id": str}
    as_field_id: str

Operation = Annotated[
    Union[AddSection, AddField, MoveField, RemoveField, UpdateField,
          UpdateSectionMeta, UpdateFormMeta, DuplicateField],
    Field(discriminator="op"),
]

class OperationsEnvelope(BaseModel):
    operations: list[Operation]
```

### New Public Interfaces

```python
# parrot_formdesigner/api/routes.py
def setup_form_api(
    app: web.Application,
    registry: FormRegistry,
    *,
    client=None,
    submission_storage=None,
    forwarder=None,
    base_path: str = "/api/v1",
) -> None:
    """Mount the JSON REST surface. HARD-imports navigator_auth decorators."""

# parrot_formdesigner/ui/routes.py
def setup_form_ui(
    app: web.Application,
    registry: FormRegistry,
    *,
    base_path: str = "",
    protect_pages: bool = True,
) -> None:
    """Mount HTML pages + Telegram WebApp routes. Opt-in by host app."""

# parrot_formdesigner/controls/registry.py
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
) -> None: ...

def get_controls() -> list[FieldControlMetadata]: ...
def iter_controls() -> Iterator[FieldControlMetadata]: ...

# parrot_formdesigner/api/render.py
def register_renderer(format_key: str, renderer: AbstractFormRenderer) -> None: ...
def get_renderer(format_key: str) -> AbstractFormRenderer | None: ...
def supported_formats() -> list[str]: ...
```

---

## 3. Module Breakdown

> Wave numbers indicate the implementation wave. Wave 2 modules depend on
> Wave 1 landing first; within Wave 2, the four capability modules are
> mutually independent.

### Module 1: `parrot_formdesigner/__init__.py` (rewrite — Wave 1)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/__init__.py`
- **Responsibility**: Expose `__version__`, `__title__`, `__description__`,
  `__author__`, `__author_email__`, `__license__`. NO submodule imports, NO
  re-exports of `FormSchema` / `FieldType` / handlers / renderers.
- **Depends on**: nothing (top-level metadata only).

### Module 2: `parrot_formdesigner/api/` (new — Wave 1)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/`
  - `__init__.py` — exports `setup_form_api`.
  - `_utils.py` — `_deep_merge`, `_loc_to_str`, `_bump_version` (verbatim
    copies from `handlers/api.py:36-103`).
  - `handlers.py` — `FormAPIHandler` migrated from `handlers/api.py:108-679`.
    The `get_html` method is **removed**; render goes through the dispatcher.
  - `render.py` — render dispatcher: `dict[str, AbstractFormRenderer]`,
    `register_renderer`, `get_renderer`, `supported_formats`,
    `_handle_render(request)` aiohttp handler.
  - `controls.py` — `_handle_form_controls(request)` returning
    `{"controls": [...]}`. Wave 1 stub may return `[]` until Wave 2 wires
    builtins; **decision deferred** — current spec says Wave 1 wires the
    seed at startup so the endpoint returns the full FieldType list from
    day one (Wave 2 only adds new controls).
  - `operations.py` — Wave 1 stubs out the route returning `501 Not
    Implemented`; Wave 2 (Module 7) replaces the body with the real handler.
  - `routes.py` — `setup_form_api(app, registry, **kwargs)`. HARD imports
    `from navigator_auth.decorators import is_authenticated, user_session`.
- **Depends on**: `core`, `services.registry`, `services.validators`,
  `renderers.*` (read-only — for dispatcher seed), `controls.registry`,
  `navigator_auth.decorators`.

### Module 3: `parrot_formdesigner/ui/` (new — Wave 1)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/ui/`
  - `__init__.py` — exports `setup_form_ui`.
  - `handlers.py` — `FormPageHandler` migrated from
    `handlers/forms.py` verbatim.
  - `telegram.py` — `TelegramWebAppHandler` migrated from
    `handlers/telegram.py` verbatim.
  - `templates.py` — moved from `handlers/templates.py` verbatim.
  - `routes.py` — `setup_form_ui(app, registry, *, protect_pages=True)`.
    Telegram routes registered without auth (public by design — Telegram
    can hit them); HTML pages honor `protect_pages` via `_page_wrap`.
- **Depends on**: `core`, `services.registry`, `renderers.html5`,
  `renderers.telegram`. The optional `_page_wrap` does a **runtime** auth
  check by calling `navigator_auth.decorators` — same hard-import policy
  as `api/`.

### Module 4: `parrot_formdesigner/controls/` (new — Wave 1)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/controls/`
  - `registry.py` — module-level dict + `register_field_control`,
    `get_controls`, `iter_controls`. Pydantic `FieldControlMetadata`.
  - `builtin.py` — at import time, calls `register_field_control` once per
    `FieldType` value; metadata seeded from
    `tools.field_helpers._FIELD_SCHEMA_SNIPPETS` plus per-type
    `category` / `icon` / `render_hint` / `is_container` constants encoded
    in `builtin.py`.
- **Depends on**: `core.types.FieldType`,
  `tools.field_helpers.get_form_field_schema_snippets`.

### Module 5: `parrot_formdesigner/pyproject.toml` (modify — Wave 1)
- **Path**: `packages/parrot-formdesigner/pyproject.toml`
- **Responsibility**: Promote `navigator-auth`, `lxml` (>=6.1.0),
  `reportlab` (>=4.1.0) from optional / transitive to required
  `[project.dependencies]`. Bump `version` to `0.2.0`.
- **Depends on**: nothing.

### Module 6: `parrot_formdesigner/renderers/xforms.py` (new — Wave 2a)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py`
- **Responsibility**: `XFormsRenderer(AbstractFormRenderer)`. Maps
  `FormSchema` → XForms 1.1 (W3C) using `lxml.etree`. Sections become
  `<xf:group>`, fields become `<xf:input>`, `<xf:select1>`, `<xf:upload>`,
  etc. Returns `RenderedForm(content=<xml-bytes>,
  content_type="application/xml")`. V1 emits structural model + UI bindings
  only; constraint expression mapping is a follow-up (see §8 Q5).
- **Depends on**: `core.schema`, `renderers.base`, `lxml.etree`.
- **Wires into**: `api/render.py` registry under key `"xml"`.

### Module 7: `parrot_formdesigner/renderers/pdf.py` (new — Wave 2b)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py`
- **Responsibility**: `PdfRenderer(AbstractFormRenderer)`. Uses
  `reportlab.pdfgen.canvas.Canvas` + `canvas.acroForm` to emit a fillable
  PDF. Layout: vertical single-column with section headers and
  label-above-input blocks. Field type mapping per brainstorm
  (`text/email/url/phone/password → textfield`, `boolean → checkbox`,
  `select → choice`, `multi_select → listbox`, `date → textfield`,
  `hidden → hidden field`, `file/image/array/group → flat textfield
  placeholder + form-level meta note`). Returns
  `RenderedForm(content=<pdf-bytes>, content_type="application/pdf")`.
- **Depends on**: `core.schema`, `renderers.base`,
  `reportlab.pdfgen.canvas`.
- **Wires into**: `api/render.py` registry under key `"pdf"`.

### Module 8: `parrot_formdesigner/api/controls.py` payload finalization (Wave 2c)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/controls.py`
- **Responsibility**: Wave 1 wires the endpoint with the seeded registry;
  Wave 2c locks in the response shape and adds tests against the
  contract: `{"controls": [{...FieldControlMetadata...}, ...]}`. If Wave 1
  ships an empty placeholder body, Wave 2c is the implementation; if Wave 1
  ships the full body, Wave 2c is the contract test + any added control
  types.
- **Depends on**: Module 4 (controls registry).

### Module 9: `parrot_formdesigner/api/operations.py` (new — Wave 2d)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py`
- **Responsibility**: `PatchOperationsHandler`. Validates
  `OperationsEnvelope` (Pydantic discriminated union). Applies operations
  in-memory to a working copy. On any per-op failure, abort with `422` and
  `{"errors": [{"index": i, "op": op_name, "message": ...}]}`. Calls
  `FormValidator.check_schema(working_copy)` after the last op; on
  structural errors abort with `422`. Bumps version (`_bump_version`),
  calls `registry.register(working_copy, persist=True, overwrite=True)`,
  returns the new full `FormSchema`. Optional optimistic concurrency:
  honours `If-Match: <version>` (returns `412` on mismatch).
- **Depends on**: `core.schema`, `services.registry`, `services.validators`,
  `api/_utils._bump_version`, `api/_utils._deep_merge` (for `update_field`,
  `update_section_meta`, `update_form_meta`).
- **Wires into**: `api/routes.py` under
  `PATCH /api/v1/forms/{form_id}/operations`.

### Module 10: `parrot_formdesigner/handlers/` (delete — Wave 1)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/handlers/`
- **Responsibility**: Folder is deleted after content is split into `api/`
  and `ui/`. Any consumer doing
  `from parrot_formdesigner.handlers import setup_form_routes` breaks at
  import time — intentional, breaking change documented in CHANGELOG.
- **Depends on**: Modules 2 + 3 must be in place first.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_init_imports_metadata_only` | Module 1 | Importing `parrot_formdesigner` does NOT import `aiohttp`, `aiogram`, `reportlab`, `lxml`, or any submodule. Asserts via `sys.modules` snapshot diff. |
| `test_setup_form_api_mounts_routes` | Module 2 | `setup_form_api(app, registry)` mounts the documented route table; routes carry `is_authenticated` decorator. |
| `test_render_dispatcher_unknown_format_returns_415` | Module 2 | `GET /api/v1/forms/{id}/render/foo` → 415 with `{"supported": [...]}` body. |
| `test_render_dispatcher_html_delegates` | Module 2 | `GET /api/v1/forms/{id}/render/html` → HTML5Renderer.render() called; response Content-Type: text/html. |
| `test_render_dispatcher_adaptive_delegates` | Module 2 | Same for `adaptive`. |
| `test_register_renderer_overwrites` | Module 2 | `register_renderer("xml", X)` is idempotent. |
| `test_setup_form_ui_telegram_unauth` | Module 3 | `/forms/{id}/telegram` route registered without auth (public). |
| `test_setup_form_ui_html_protect_pages_true` | Module 3 | When `protect_pages=True`, HTML page routes go through `_page_wrap`. |
| `test_register_field_control_basic` | Module 4 | `register_field_control(FieldType.TEXT, ...)` adds to registry; `get_controls()` returns it. |
| `test_builtin_seeds_every_field_type` | Module 4 | After `import parrot_formdesigner.controls.builtin`, every `FieldType` value has an entry. |
| `test_form_controls_endpoint_payload_shape` | Module 8 | `GET /api/v1/form-controls` returns `{"controls": [{...}]}` matching `FieldControlMetadata`. |
| `test_xforms_renderer_emits_xf_namespace` | Module 6 | Output XML declares `xmlns:xf="http://www.w3.org/2002/xforms"`. |
| `test_xforms_renderer_section_to_group` | Module 6 | Each `FormSection` → `<xf:group>` with section_id as `id` attribute. |
| `test_xforms_renderer_select_to_select1` | Module 6 | `FieldType.SELECT` → `<xf:select1>` with one `<xf:item>` per option. |

…(truncated)…
