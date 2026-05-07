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
| `test_pdf_renderer_emits_acroform` | Module 7 | Generated PDF parses; AcroForm dict present (verifiable via `pypdf`). |
| `test_pdf_renderer_textfield_for_text` | Module 7 | `FieldType.TEXT` field → AcroForm textfield with name == `field_id`. |
| `test_pdf_renderer_unsupported_field_meta_note` | Module 7 | `FieldType.FILE` field → flat textfield placeholder + form-level meta annotation lists it. |
| `test_operations_envelope_validates` | Module 9 | Pydantic discriminator picks the right Operation subclass per `op` value. |
| `test_operations_atomic_failure_no_change` | Module 9 | Two ops where the second references a missing `field_id` → form unchanged, response 422 with `errors[1].index == 1`. |
| `test_operations_circular_depends_on_rejected` | Module 9 | After applying ops, `FormValidator.check_schema` returns errors → 422. |
| `test_operations_if_match_412` | Module 9 | `If-Match: 1.0` when registry has 1.1 → 412. |
| `test_operations_bumps_version` | Module 9 | Successful apply moves `1.0` → `1.1`. |
| `test_no_navigator_auth_fails_at_import` | Module 2 | Stub out `navigator_auth` import; `import parrot_formdesigner.api.routes` raises `ImportError`. |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_html_render_via_dispatcher` | Boot aiohttp app, `setup_form_api`, register a form, GET `/render/html` returns HTML body. |
| `test_e2e_xml_render_via_dispatcher` | Same with `/render/xml` after Wave 2a — returns XForms doc parseable by `lxml`. |
| `test_e2e_pdf_render_via_dispatcher` | Same with `/render/pdf` after Wave 2b — returns valid PDF parsable by `pypdf`. |
| `test_e2e_form_controls_endpoint` | `setup_form_api` + import builtins → `GET /api/v1/form-controls` returns N entries where N == `len(FieldType)`. |
| `test_e2e_operations_round_trip` | Boot + register form, send 3 ops (add_section, add_field, move_field), assert final form structure + version bump. |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_form() -> FormSchema:
    return FormSchema(
        form_id="test-form",
        title={"en": "Test Form"},
        sections=[
            FormSection(
                section_id="personal",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT,
                              label={"en": "Name"}, required=True),
                    FormField(field_id="email", field_type=FieldType.EMAIL,
                              label={"en": "Email"}),
                ],
            ),
        ],
    )

@pytest.fixture
async def app_with_api(aiohttp_client, sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    app = web.Application()
    setup_form_api(app, registry)
    return await aiohttp_client(app)
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `import parrot_formdesigner` does NOT import any of: `aiohttp`,
      `aiogram`, `reportlab`, `lxml`, `parrot_formdesigner.handlers.*`,
      `parrot_formdesigner.api.*`, `parrot_formdesigner.ui.*`,
      `parrot_formdesigner.renderers.*`. (Verified via `sys.modules` diff.)
- [ ] `parrot_formdesigner.handlers/` no longer exists; consumer code that
      imports `setup_form_routes` from it fails at import time.
- [ ] `parrot_formdesigner.api.routes.setup_form_api(app, registry)` mounts
      the JSON REST surface, with every route guarded by
      `navigator_auth.decorators.is_authenticated` (no fallback open mode).
- [ ] `parrot_formdesigner.ui.routes.setup_form_ui(app, registry,
      protect_pages=True)` mounts HTML + Telegram routes; Telegram routes
      remain public; HTML routes honor `protect_pages`.
- [ ] `pyproject.toml` lists `navigator-auth`, `lxml>=6.1.0`,
      `reportlab>=4.1.0` in `[project.dependencies]`. The
      `try/except ImportError` block in `routes.py` is gone.
- [ ] `GET /api/v1/forms/{form_id}/render/html` returns the HTML5 render
      with `Content-Type: text/html`.
- [ ] `GET /api/v1/forms/{form_id}/render/adaptive` returns the Adaptive
      Card JSON with `Content-Type: application/json`.
- [ ] `GET /api/v1/forms/{form_id}/render/<unknown>` returns `415` with
      body `{"supported": [...]}` listing currently registered formats.
- [ ] `GET /api/v1/forms/{form_id}/schema` and `/style` continue to work
      unchanged (contract endpoints, not render formats).
- [ ] `parrot_formdesigner.controls.registry.register_field_control` adds
      entries; `get_controls()` returns them; `controls.builtin` seeds
      every `FieldType` value.
- [ ] `GET /api/v1/form-controls` returns `{"controls": [...]}` with one
      entry per registered control, each matching the
      `FieldControlMetadata` schema.
- [ ] `GET /api/v1/forms/{form_id}/render/xml` returns a parseable XForms
      1.1 document with `xmlns:xf` declared.
- [ ] `GET /api/v1/forms/{form_id}/render/pdf` returns a fillable PDF; the
      AcroForm dict is present and parsable by `pypdf`.
- [ ] `PATCH /api/v1/forms/{form_id}/operations` with a valid envelope
      applies all ops atomically and bumps the form version.
- [ ] `PATCH /api/v1/forms/{form_id}/operations` with a failing op leaves
      the form unchanged and returns `422` with per-op error indices.
- [ ] `PATCH /api/v1/forms/{form_id}/operations` honors `If-Match` —
      mismatched version returns `412`.
- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/ -v`.
- [ ] All integration tests pass: `pytest packages/parrot-formdesigner/tests/integration/ -v`.
- [ ] CHANGELOG.md documents the breaking changes (package layout,
      `setup_form_routes` removal, hard `navigator-auth` dep).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the
> codebase. Implementation agents MUST NOT reference imports, attributes,
> or methods not listed here without first verifying via `grep` or `read`.
> Carried forward from `proposals/formdesigner-refactor.brainstorm.md`
> §"Code Context", re-verified 2026-05-07.

### Verified Imports

```python
# Confirmed working today against the package layout:
from parrot_formdesigner.core.schema import (
    FormField, FormSchema, FormSection, RenderedForm, SubmitAction,
)  # verified: packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:21,68,108,140
from parrot_formdesigner.core.types import (
    FieldType, LocalizedString,
)  # verified: packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py:16
from parrot_formdesigner.core.style import (
    StyleSchema, LayoutType, FieldStyleHint,
)
from parrot_formdesigner.renderers.base import AbstractFormRenderer
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py:14
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer
from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer
from parrot_formdesigner.services.registry import FormRegistry, FormStorage
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:105
from parrot_formdesigner.services.validators import FormValidator, ValidationResult
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py:66
from parrot_formdesigner.tools.field_helpers import (
    list_supported_form_field_types, get_form_field_schema_snippets,
)  # verified: packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py:152,158
from navigator_auth.decorators import is_authenticated, user_session
# Imported conditionally today at handlers/routes.py:32; becomes a HARD import in api/routes.py.
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:21
class FormField(BaseModel):
    model_config = ConfigDict(extra="forbid")          # line 45
    field_id: str                                       # line 47
    field_type: FieldType                               # line 48
    label: LocalizedString                              # line 49
    description: LocalizedString | None = None          # line 50
    placeholder: LocalizedString | None = None          # line 51
    required: bool = False                              # line 52
    default: Any = None                                 # line 53
    read_only: bool = False                             # line 54
    constraints: FieldConstraints | None = None         # line 55
    options: list[FieldOption] | None = None            # line 56
    options_source: OptionsSource | None = None         # line 57
    depends_on: DependencyRule | None = None            # line 58
    children: list[FormField] | None = None             # line 59
    item_template: FormField | None = None              # line 60
    meta: dict[str, Any] | None = None                  # line 61

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:68
class FormSection(BaseModel):
    section_id: str                                     # line 83
    title: LocalizedString | None = None                # line 84
    description: LocalizedString | None = None          # line 85
    fields: list[FormField]                             # line 86
    depends_on: DependencyRule | None = None            # line 87
    meta: dict[str, Any] | None = None                  # line 88

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:108
class FormSchema(BaseModel):
    form_id: str                                        # line 129
    version: str = "1.0"                                # line 130
    title: LocalizedString                              # line 131
    description: LocalizedString | None = None          # line 132
    sections: list[FormSection]                         # line 133
    submit: SubmitAction | None = None                  # line 134
    cancel_allowed: bool = True                         # line 135
    meta: dict[str, Any] | None = None                  # line 136
    created_at: datetime | None = None                  # line 137

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:140
class RenderedForm(BaseModel):
    content: Any                                        # line 150
    content_type: str                                   # line 151
    style_output: Any | None = None                     # line 152
    metadata: dict[str, Any] | None = None              # line 153

# packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py:16
class FieldType(str, Enum):
    TEXT = "text"; TEXT_AREA = "text_area"; NUMBER = "number"; INTEGER = "integer"
    BOOLEAN = "boolean"; DATE = "date"; DATETIME = "datetime"; TIME = "time"
    SELECT = "select"; MULTI_SELECT = "multi_select"; FILE = "file"; IMAGE = "image"
    COLOR = "color"; URL = "url"; EMAIL = "email"; PHONE = "phone"
    PASSWORD = "password"; HIDDEN = "hidden"; GROUP = "group"; ARRAY = "array"

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
    ) -> RenderedForm: ...                              # lines 25-46

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:105
class FormRegistry:
    def __init__(self, storage: FormStorage | None = None) -> None: ...   # line 122
    async def register(self, form: FormSchema, *, persist: bool = False,
                       overwrite: bool = True) -> None: ...               # line 135
    async def unregister(self, form_id: str) -> bool: ...                  # line 180
    async def get(self, form_id: str) -> FormSchema | None: ...            # line 203
    async def list_forms(self) -> list[FormSchema]: ...                    # line 215
    async def list_form_ids(self) -> list[str]: ...                        # line 224
    async def contains(self, form_id: str) -> bool: ...                    # line 233
    async def clear(self) -> None: ...                                     # line 245
    async def load_from_directory(self, path: str | Path, *, recursive: bool = True,
                                  overwrite: bool = False) -> int: ...    # line 250
    async def load_from_storage(self) -> int: ...                          # line 301

# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py:66
class FormValidator:
    def check_schema(self, form: FormSchema) -> list[str]: ...             # line 446
    # NOTE: check_schema currently only detects circular depends_on cycles.
    # The /operations endpoint relies on it AS-IS at step 4 of the algorithm.

# packages/parrot-formdesigner/src/parrot_formdesigner/handlers/api.py:109
class FormAPIHandler:
    def __init__(self, registry: FormRegistry, client=None,
                 submission_storage=None, forwarder=None) -> None: ...    # line 125
    async def list_forms(self, request) -> web.Response: ...               # line 224
    async def get_form(self, request) -> web.Response: ...                 # line 284
    async def get_schema(self, request) -> web.Response: ...               # line 299
    async def get_style(self, request) -> web.Response: ...                # line 315
    async def get_html(self, request) -> web.Response: ...                 # line 331  → REPLACED by render dispatcher
    async def validate(self, request) -> web.Response: ...                 # line 347
    async def create_form(self, request) -> web.Response: ...              # line 372
    async def update_form(self, request) -> web.Response: ...              # line 421  → kept (PUT)
    async def patch_form(self, request) -> web.Response: ...               # line 468  → kept (RFC 7396 PATCH)
    async def submit_data(self, request) -> web.Response: ...              # line 519
    async def load_from_db(self, request) -> web.Response: ...             # line 610

# packages/parrot-formdesigner/src/parrot_formdesigner/handlers/api.py:36
def _deep_merge(base: dict, patch: dict) -> dict: ...                      # RFC 7396 merge
def _loc_to_str(value: object) -> str | None: ...                          # line 62
def _bump_version(version: str) -> str: ...                                # line 86 — used by /operations

# packages/parrot-formdesigner/src/parrot_formdesigner/handlers/routes.py:31-35
try:
    from navigator_auth.decorators import is_authenticated, user_session   # line 32
    _AUTH_AVAILABLE = True
except ImportError:
    _AUTH_AVAILABLE = False                                                # line 35
# → REMOVED in Wave 1: hard import at module top, _AUTH_AVAILABLE flag deleted.

# packages/parrot-formdesigner/src/parrot_formdesigner/handlers/routes.py:82
def setup_form_routes(...) -> None: ...
# → REPLACED in Wave 1 by setup_form_api (api/routes.py) + setup_form_ui (ui/routes.py).

# packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py:152
def list_supported_form_field_types() -> list[str]: ...                    # line 152
def get_form_field_schema_snippets() -> dict[str, dict[str, Any]]: ...     # line 158
# Both reused as the seed for controls/builtin.py.
```

### Available libraries (verified in venv)

```text
fpdf       1.7.2     # not used; legacy
lxml       6.1.0     # XForms emission (Module 6)
pypdf      6.10.2    # used by tests to assert AcroForm presence
pypdfium2  5.8.0     # not needed for V1
reportlab  4.1.0     # PDF AcroForm (Module 7)
weasyprint 68.0      # not used (HTML→PDF static, can't produce AcroForm fillable)
```

### Key Attributes & Constants

- `FieldType.value` → `str` enum value, the canonical id used as registry
  key (`packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py:16-39`).
- `_FIELD_SCHEMA_SNIPPETS` → `dict[str, dict]`
  (`packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py:16-149`)
  — exposed via `get_form_field_schema_snippets()` (returns deep copy).
- `RenderedForm.content_type` → `str`, set by each renderer; the dispatcher
  passes it through to `web.Response(..., content_type=...)`.
- `FormRegistry._storage` → `FormStorage | None`; the API layer reads it to
  decide `persist=` (current pattern at `handlers/api.py:463, 514`).

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `api/render.py` dispatcher | `HTML5Renderer.render()` | dict lookup → method call | `renderers/html5.py` (extends `AbstractFormRenderer`) |
| `api/render.py` dispatcher | `AdaptiveCardRenderer.render()` | dict lookup → method call | `renderers/adaptive_card.py` |
| `controls/builtin.py` | `tools.field_helpers.get_form_field_schema_snippets()` | function call | `tools/field_helpers.py:158` |
| `api/operations.py` | `FormValidator.check_schema()` | method call | `services/validators.py:446` |
| `api/operations.py` | `FormRegistry.register(...)` | method call | `services/registry.py:135` |
| `api/operations.py` | `_bump_version()` | function call | `api/_utils.py` (migrated from `handlers/api.py:86`) |
| `api/routes.py` | `is_authenticated`, `user_session` | hard import | `navigator_auth.decorators` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AbstractFormRenderer.format_name`~~ — there is no `format_name`
  attribute today. The render dispatcher needs its own format-name
  registry (`api/render.py`); do NOT assume renderers self-identify.
- ~~`FormValidator.validate_operations`~~ — does not exist; the
  `/operations` handler must build its own per-op validation. The only
  reusable structural check is `FormValidator.check_schema()`
  (circular-dep detection).
- ~~`FormSchema.bump_version()` / `FormSchema.copy_with()`~~ — no such
  methods. Use the module-level `_bump_version` helper from
  `handlers/api.py:86` (migrated to `api/_utils.py`) and
  `model_dump()` / `model_validate()` round-trips.
- ~~`navigator_auth.NoAuth` as a Python import name~~ — the `noauth`
  backend is a navigator-auth runtime concept; it is the consumer's
  concern, NOT something this package references. The package only
  imports `is_authenticated` and `user_session` decorators.
- ~~`FormPageHandler.render_form_pdf()` / similar~~ — no PDF method
  exists today. PDF is a brand-new renderer in `renderers/pdf.py`.
- ~~`tools/field_helpers._FIELD_SCHEMA_SNIPPETS` includes `render_hint`
  metadata~~ — it does NOT today; render hints are part of the new
  controls registry, not in the existing snippets dict.
- ~~A `FieldType.SECTION` value~~ — sections are a separate model
  (`FormSection`), not a `FieldType`. Operations on sections use distinct
  ops (`add_section`, `remove_section`, `move_section`).
- ~~Existing `parrot_formdesigner.api` or `parrot_formdesigner.ui`
  modules~~ — both are NEW; today only `handlers/` exists.
- ~~`parrot_formdesigner.renderers.xforms` / `parrot_formdesigner.renderers.pdf`~~
  — neither exists today; both are NEW in Wave 2a / 2b.
- ~~`parrot_formdesigner.controls`~~ — does NOT exist today; NEW in Wave 1.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **async-first** per `CLAUDE.md` / `.agent/CONTEXT.md`. All new handlers
  are `async def` aiohttp coroutines. No blocking I/O on the event loop —
  `reportlab` PDF generation is CPU-bound but short; if profiling shows
  hot paths > 50 ms, wrap in `asyncio.to_thread`.
- **Pydantic everywhere** for structured data (`FieldControlMetadata`,
  `OperationsEnvelope`, all `Operation` subclasses, error responses).
- **Logger usage**: every handler module gets
  `self.logger = logging.getLogger(__name__)`; never `print`.
- **Renderer registration is in-tree**, not entry-point-based. Wave 1
  exports `register_renderer` so future renderers can be added in-package
  via a one-line call at module import time. Promotion to entry-point
  discovery is deferred (out of scope per Non-Goals).
- **Controls registry** mirrors the renderer pattern:
  `register_field_control` is a function called at import time by
  `controls/builtin.py`. Adding a new control type is a one-line
  registration plus snippet metadata.
- **`tools/` stays at the package root.** It hosts Python tool classes
  consumed by agents (`CreateFormTool`, `DatabaseFormTool`,
  `RequestFormTool`); the `api/` move is an HTTP-surface concern, not a
  Python-tool concern. (See §8 Q6 — brainstorm recommendation accepted as
  the working assumption.)
- **`POST /forms/{id}/data`** (submissions) and the `services/submissions.py`
  / `services/forwarder.py` pipeline are NOT touched by this refactor.

### Known Risks / Gotchas

- **Transient-incoherence window between waves.** Between Wave 1 and Wave
  2, `/render/xml` and `/render/pdf` return `415`. This is documented in
  the spec and covered by `test_render_dispatcher_unknown_format_returns_415`
  — the test asserts the supported-formats list matches what is registered.
  When Wave 2a / 2b lands, the test expectation updates. Mitigation:
  release Wave 1 with a CHANGELOG entry calling out the gap; downstream
  consumers know not to integrate XML/PDF channels yet.
- **Breaking `setup_form_routes` import.** Any consumer doing
  `from parrot_formdesigner import setup_form_routes` or
  `from parrot_formdesigner.handlers import setup_form_routes` breaks at
  import time after Wave 1 lands. Mitigation: pre-merge audit of
  `navigator-api` and other internal consumers; coordinated bump in the
  same release window.
- **`navigator-auth` becomes a hard dep.** Hosts that previously ran
  `parrot-formdesigner` without auth now MUST configure navigator-auth
  (the `NoAuth` backend covers dev mode). Mitigation: CHANGELOG section
  with the one-liner `from navigator_auth.backends.noauth import NoAuthBackend`
  recipe — verify the exact import name with the navigator-auth maintainer
  before publishing.
- **PDF AcroForm doesn't support file upload natively.** The renderer
  must emit a flat textfield placeholder for `FieldType.FILE`,
  `FieldType.IMAGE`, `FieldType.ARRAY`, `FieldType.GROUP` (containers) and
  add a form-level `meta` annotation listing unsupported fields. Test
  `test_pdf_renderer_unsupported_field_meta_note` enforces this.
- **`field_id` uniqueness within a section.** Operations like
  `add_field`, `duplicate_field`, `move_field` must check this BEFORE
  mutating the working copy; `FormValidator.check_schema()` only detects
  circular `depends_on`, not duplicate ids. The per-op validator in
  `api/operations.py` owns this check.
- **`If-Match` is opt-in.** Concurrent PATCH on the same form without
  `If-Match` is last-write-wins; this is intentional for V1. Atomicity is
  per-request, not cross-request.
- **`tools/field_helpers._FIELD_SCHEMA_SNIPPETS` is a private name.**
  `controls/builtin.py` MUST use the public
  `get_form_field_schema_snippets()` accessor (returns a deep copy), not
  the private dict directly.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navigator-auth` | (latest stable) | HARD: session auth for `api/routes.py` |
| `lxml` | `>=6.1.0` | XForms emission (Module 6) — already in venv |
| `reportlab` | `>=4.1.0` | PDF AcroForm (Module 7) — already in venv |
| `pydantic` | `>=2.0` | Operations envelope discriminated union — already a hard dep |
| `aiohttp` | (existing) | HTTP server — already a hard dep |
| `pypdf` | `>=6.0` | TEST-ONLY: assert AcroForm presence in PDF output |

---

## Worktree Strategy

- **Default isolation unit: mixed.**
- **Wave 1 (per-spec, single sequential worktree)**:
  Modules 1, 2, 3, 4, 5, 10 — all share files (`__init__.py`,
  `pyproject.toml`, `handlers/` deletion, new `api/` + `ui/` + `controls/`
  packages). Cannot be parallelized.
  Worktree: `.claude/worktrees/feat-152-formdesigner-refactor` from `dev`.
- **Wave 2 (per-task, four parallel worktrees off `dev`)**:
  - 2a `xforms-renderer` (Module 6) — `renderers/xforms.py`.
  - 2b `pdf-renderer` (Module 7) — `renderers/pdf.py`.
  - 2c `controls-rest` (Module 8) — `api/controls.py` + tests.
  - 2d `edit-operations` (Module 9) — `api/operations.py` + tests.
  - All four touch disjoint files; only registry-level wiring at
    boot-time (`api/render.py` `register_renderer(...)` calls) is shared,
    and that is additive.
- **Cross-feature dependencies**:
  - `form-designer-edition` (existing PUT/PATCH endpoint): coexists. The
    new `/operations` endpoint is additive; `update_form` (PUT) and
    `patch_form` (RFC 7396) remain available.
  - `formdesigner-authentication`: this refactor supersedes any
    optional-auth code still in flight there.
- **Hint to `/sdd-task`**: decompose Wave 1 as a single sequence in one
  worktree; emit Wave 2 as four independent task groups, each in its own
  worktree off `dev` (created AFTER Wave 1 merges).

---

## 8. Open Questions

> Resolved (`[x]`) — carried forward verbatim from the brainstorm. None at
> spec-creation time; all six brainstorm Open Questions remained `[ ]`.
>
> Unresolved (`[ ]`) — must be resolved before or during implementation.

- [x] **Q1 — `If-Match` concurrency in V1**: Should
      `PATCH /api/v1/forms/{id}/operations` support optional `If-Match`
      concurrency control in V1, or is last-write-wins sufficient until
      the designer UI lands? — *Owner: Jesus Lara*
      *Brainstorm guidance: optional support is included in the
      Architectural Design above ("Optional optimistic concurrency").
      If V1 ships without it, `test_operations_if_match_412` is removed
      from the AC list.*: optimistic concurrency
- [x] **Q2 — Deprecate existing PUT/PATCH endpoints?** Do the existing
      PUT (`api.update_form`) and RFC-7396 PATCH (`api.patch_form`)
      endpoints stay alongside the new `/operations`, or do we deprecate
      them in V1? — *Owner: Jesus Lara*
      *Brainstorm recommendation: keep both — full replace and
      merge-patch have different use cases (config imports, admin tools)
      than granular UI edits. This is the working assumption in §1
      Goals / Non-Goals.*: stay, keep both.
- [x] **Q3 — Telegram WebApp template split**: `templates.py` is a
      457 LoC monolith of inline HTML. Stay monolithic in `ui/templates.py`
      or split per-page? Pure organizational, no behavior change. —
      *Owner: Jesus Lara*: stay.
      *Brainstorm guidance: defer; Wave 1 moves the file verbatim.*
- [x] **Q4 — PDF V1 scope for fields not natively expressible in
      AcroForm**: For `FieldType.FILE`, `FieldType.IMAGE`,
      `FieldType.ARRAY`, `FieldType.GROUP` — annotate with a "fill out
      elsewhere" textfield, or omit entirely? — *Owner: Jesus Lara*
      *Brainstorm recommendation (encoded in Module 7 + AC): flat
      textfield placeholder + form-level `meta` note listing unsupported
      fields. Document in CHANGELOG.*: ok with recommendation.
- [x] **Q5 — XForms V1 constraint binds**: Include `<xf:bind>` constraint
      expressions derived from `FieldConstraints` in V1, or only emit
      structural model + UI bindings? More semantic XForms is a longer
      task. — *Owner: Jesus Lara*
      *Brainstorm recommendation (encoded in Module 6): structural only
      in V1; constraint mapping is a follow-up.*: include
- [x] **Q6 — `parrot_formdesigner.tools/` placement**: Belong under
      `api/tools/`, stay at root, or move to a separate `agents/`
      sub-package? — *Owner: Jesus Lara*
      *Brainstorm recommendation (encoded in §1 Non-Goals + §7 Patterns):
      stay at root. The `api/` move is about HTTP, not Python tools.*: stay at root.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-07 | Jesus Lara | Initial draft from `proposals/formdesigner-refactor.brainstorm.md` (Recommended Option B). |
