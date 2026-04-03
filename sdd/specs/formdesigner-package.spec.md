# Feature Specification: FormDesigner Package

**Feature ID**: FEAT-079
**Date**: 2026-04-03
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.0.0

---

## 1. Motivation & Business Requirements

### Problem Statement

All form-related functionality (schema models, tools, extractors, renderers, validators,
registry, storage, cache, and HTTP handlers) currently lives inside the `ai-parrot` core
package at `parrot/forms/`. This creates tight coupling:

- Consumers like `parrot/integrations/msteams/` import directly from `parrot.forms`.
- The example form server (`examples/forms/form_server.py`) embeds ~500 lines of HTTP
  handler logic, CSS, and HTML that should be a reusable module.
- There is no standalone HTTP service for form creation, rendering, and validation that
  other projects or microservices can consume independently.
- Natural-language form generation (LLM-driven) is buried in an example, not exposed as a
  first-class handler.

### Goals

1. **Extract** all form functionality into a new standalone package `parrot-formdesigner`
   that can be installed and used independently from `ai-parrot`.
2. **Create HTTP handlers** (aiohttp-based) for serving HTML5 forms, JSON Schema forms
   (structural + style), form validation, and natural-language form generation — mirroring
   the capabilities of `examples/forms/form_server.py` but as production-quality,
   reusable handler classes.
3. **Provide a REST API module** with endpoints for:
   - `POST /api/forms` — create form from natural language prompt
   - `GET /api/forms` — list registered forms
   - `GET /api/forms/{id}` — get form schema (JSON)
   - `GET /api/forms/{id}/schema` — get JSON Schema (structural)
   - `GET /api/forms/{id}/style` — get style schema
   - `GET /api/forms/{id}/html` — render HTML5 form
   - `POST /api/forms/{id}/validate` — validate submission data
   - `POST /api/forms/from-db` — load form from database definition
4. **Update imports** in `ai-parrot` consumers (`parrot/integrations/`, examples) to use
   the new package, keeping backward-compatible re-exports from `parrot.forms`.
5. **Package as installable** via `pyproject.toml` with `uv add parrot-formdesigner`.

### Non-Goals (explicitly out of scope)

- Rewriting the core schema models, extractors, or renderers — they move as-is.
- Adding new renderer types (e.g., React, Vue) — that's a separate feature.
- Database migration tooling — `PostgresFormStorage` moves unchanged.
- Authentication/authorization on the REST API — handled at the integration layer.
- Frontend SPA or JavaScript framework — HTML is server-rendered.

---

## 2. Architectural Design

### Overview

Create a new Python package `parrot-formdesigner` under `packages/parrot-formdesigner/`
following the same monorepo layout as `packages/ai-parrot/`. The package namespace is
`parrot.formdesigner` to avoid collision with the existing `parrot.forms` (which becomes
a thin re-export shim).

The package structure separates concerns into:
- **Core**: Schema models, types, constraints, options, style (moved from `parrot/forms/`)
- **Tools**: CreateFormTool, DatabaseFormTool, RequestFormTool
- **Extractors**: Pydantic, Tool, YAML, JSON Schema extractors
- **Renderers**: HTML5, AdaptiveCard, JsonSchema renderers
- **Services**: Validator, Registry, Cache, Storage
- **Handlers**: aiohttp HTTP handlers and REST API router setup

### Component Diagram

```
parrot-formdesigner (new package)
├── parrot/formdesigner/
│   ├── core/          ← schema, types, constraints, options, style
│   ├── tools/         ← CreateFormTool, DatabaseFormTool, RequestFormTool
│   ├── extractors/    ← pydantic, tool, yaml, jsonschema
│   ├── renderers/     ← html5, adaptive_card, jsonschema
│   ├── services/      ← validator, registry, cache, storage
│   └── handlers/      ← HTTP handlers + REST API routes
│       ├── forms.py       ← HTML form serving (render, submit, gallery)
│       ├── api.py         ← JSON REST API (CRUD, validate, NL create)
│       └── routes.py      ← Route registration helper
│
ai-parrot (existing package)
├── parrot/forms/      ← becomes thin re-export shim
│   └── __init__.py    ← re-exports from parrot.formdesigner.*
└── parrot/integrations/msteams/  ← imports unchanged (via shim)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.forms` | re-export shim | Backward compatibility — imports continue to work |
| `parrot.tools.abstract.AbstractTool` | dependency | Tools inherit from AbstractTool |
| `parrot.clients.factory.LLMFactory` | dependency | CreateFormTool uses LLM clients |
| `parrot/integrations/msteams/` | consumer | Imports via `parrot.forms` shim or directly |
| `examples/forms/form_server.py` | replaced by | Simplified to use `parrot.formdesigner.handlers` |
| `asyncdb` | external dep | DatabaseFormTool + PostgresFormStorage |
| `aiohttp` | external dep | HTTP handlers |

### Data Models

All existing Pydantic models move unchanged:

```python
# Core models (from parrot.forms → parrot.formdesigner.core)
FormSchema, FormField, FormSection, SubmitAction, RenderedForm
StyleSchema, LayoutType, FieldSizeHint, FieldStyleHint
FieldType, LocalizedString
FieldConstraints, ConditionOperator, FieldCondition, DependencyRule
FieldOption, OptionsSource

# Validator models
FormValidator, ValidationResult

# Registry / Storage
FormRegistry, FormStorage, PostgresFormStorage, FormCache
```

### New Public Interfaces

```python
# parrot.formdesigner.handlers.routes
def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry,
    renderer: AbstractFormRenderer | None = None,
    validator: FormValidator | None = None,
    create_tool: CreateFormTool | None = None,
    db_form_tool: DatabaseFormTool | None = None,
    prefix: str = "",
) -> None:
    """Register all form handler routes on an aiohttp Application.

    Args:
        app: The aiohttp Application to register routes on.
        registry: FormRegistry instance for form storage.
        renderer: HTML5 renderer (defaults to HTML5Renderer).
        validator: Form validator (defaults to FormValidator).
        create_tool: Optional LLM form creation tool.
        db_form_tool: Optional database form loading tool.
        prefix: URL prefix for all routes (e.g., "/formdesigner").
    """


# parrot.formdesigner.handlers.api — JSON REST API handlers
class FormAPIHandler:
    """Handles JSON REST API requests for form CRUD, validation, and NL generation."""

    async def create_form(self, request: web.Request) -> web.Response: ...
    async def list_forms(self, request: web.Request) -> web.Response: ...
    async def get_form(self, request: web.Request) -> web.Response: ...
    async def get_schema(self, request: web.Request) -> web.Response: ...
    async def get_style(self, request: web.Request) -> web.Response: ...
    async def get_html(self, request: web.Request) -> web.Response: ...
    async def validate_form(self, request: web.Request) -> web.Response: ...
    async def load_from_db(self, request: web.Request) -> web.Response: ...


# parrot.formdesigner.handlers.forms — HTML page handlers
class FormPageHandler:
    """Handles HTML page requests for form rendering, submission, and gallery."""

    async def index(self, request: web.Request) -> web.Response: ...
    async def gallery(self, request: web.Request) -> web.Response: ...
    async def render_form(self, request: web.Request) -> web.Response: ...
    async def submit_form(self, request: web.Request) -> web.Response: ...
```

---

## 3. Module Breakdown

### Module 1: Package Scaffold & Core Models

- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/core/`
- **Responsibility**: Set up the new package (`pyproject.toml`, namespace package config)
  and move core schema models: `schema.py`, `types.py`, `constraints.py`, `options.py`,
  `style.py`.
- **Depends on**: None (leaf module)
- **Files**:
  - `packages/parrot-formdesigner/pyproject.toml`
  - `packages/parrot-formdesigner/src/parrot/formdesigner/__init__.py`
  - `packages/parrot-formdesigner/src/parrot/formdesigner/core/__init__.py`
  - `packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py`
  - `packages/parrot-formdesigner/src/parrot/formdesigner/core/types.py`
  - `packages/parrot-formdesigner/src/parrot/formdesigner/core/constraints.py`
  - `packages/parrot-formdesigner/src/parrot/formdesigner/core/options.py`
  - `packages/parrot-formdesigner/src/parrot/formdesigner/core/style.py`

### Module 2: Extractors

- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/extractors/`
- **Responsibility**: Move all extractor modules that generate FormSchema from external
  sources (Pydantic models, tool schemas, YAML definitions, JSON Schema).
- **Depends on**: Module 1 (core models)
- **Files**:
  - `extractors/__init__.py`
  - `extractors/pydantic.py`
  - `extractors/tool.py`
  - `extractors/yaml.py`
  - `extractors/jsonschema.py`

### Module 3: Renderers

- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/`
- **Responsibility**: Move all renderer modules that convert FormSchema to output formats
  (HTML5, Adaptive Cards, JSON Schema).
- **Depends on**: Module 1 (core models)
- **Files**:
  - `renderers/__init__.py`
  - `renderers/base.py`
  - `renderers/html5.py`
  - `renderers/adaptive_card.py`
  - `renderers/jsonschema.py`

### Module 4: Services (Validator, Registry, Cache, Storage)

- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/services/`
- **Responsibility**: Move validation, registry, caching, and PostgreSQL storage modules.
- **Depends on**: Module 1 (core models)
- **Files**:
  - `services/__init__.py`
  - `services/validators.py`
  - `services/registry.py`
  - `services/cache.py`
  - `services/storage.py`

### Module 5: Tools

- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/tools/`
- **Responsibility**: Move form creation tools (CreateFormTool, DatabaseFormTool,
  RequestFormTool). These depend on `AbstractTool` from `ai-parrot` core — the
  dependency is declared in `pyproject.toml`.
- **Depends on**: Module 1 (core), Module 4 (services), `ai-parrot` (AbstractTool)
- **Files**:
  - `tools/__init__.py`
  - `tools/create_form.py`
  - `tools/database_form.py`
  - `tools/request_form.py`

### Module 6: HTTP Handlers & REST API

- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/`
- **Responsibility**: Production-quality HTTP handlers extracted from
  `examples/forms/form_server.py` plus new REST API endpoints for JSON Schema and
  style schema serving. Includes route registration helper.
- **Depends on**: Module 1 (core), Module 3 (renderers), Module 4 (services), Module 5 (tools)
- **Files**:
  - `handlers/__init__.py`
  - `handlers/forms.py` — `FormPageHandler` (HTML pages: index, gallery, render, submit)
  - `handlers/api.py` — `FormAPIHandler` (JSON API: CRUD, validate, schema, style, NL create, DB load)
  - `handlers/routes.py` — `setup_form_routes()` helper
  - `handlers/templates.py` — CSS and HTML page shell (extracted from form_server.py)

### Module 7: Package Exports & Re-export Shim

- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/__init__.py` and
  `packages/ai-parrot/src/parrot/forms/__init__.py`
- **Responsibility**: Define clean public API for `parrot.formdesigner` and update
  `parrot.forms.__init__` to re-export from `parrot.formdesigner` for backward
  compatibility.
- **Depends on**: Modules 1-6
- **Files**:
  - `packages/parrot-formdesigner/src/parrot/formdesigner/__init__.py`
  - `packages/ai-parrot/src/parrot/forms/__init__.py` (updated)

### Module 8: Update Consumers & Examples

- **Path**: Various
- **Responsibility**: Update `examples/forms/form_server.py` to use
  `parrot.formdesigner.handlers.setup_form_routes()` (drastically simplified).
  Update MS Teams integration imports if beneficial (optional — shim handles it).
  Move existing tests to new package test directory.
- **Depends on**: Module 7
- **Files**:
  - `examples/forms/form_server.py` (simplified)
  - `packages/parrot-formdesigner/tests/` (moved from `packages/ai-parrot/tests/unit/forms/`)

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_core_models` | Module 1 | All existing schema/style/constraints tests pass under new package |
| `test_extractors` | Module 2 | Pydantic, tool, YAML, JSON Schema extractor tests |
| `test_renderers` | Module 3 | HTML5, Adaptive Card, JSON Schema renderer tests |
| `test_services` | Module 4 | Validator, registry, cache, storage tests |
| `test_tools` | Module 5 | CreateFormTool, DatabaseFormTool, RequestFormTool tests |
| `test_api_handler_create` | Module 6 | POST /api/forms creates form from prompt |
| `test_api_handler_list` | Module 6 | GET /api/forms returns registered forms |
| `test_api_handler_get_schema` | Module 6 | GET /api/forms/{id}/schema returns JSON Schema |
| `test_api_handler_get_style` | Module 6 | GET /api/forms/{id}/style returns style schema |
| `test_api_handler_get_html` | Module 6 | GET /api/forms/{id}/html returns rendered HTML |
| `test_api_handler_validate` | Module 6 | POST /api/forms/{id}/validate validates submission |
| `test_api_handler_from_db` | Module 6 | POST /api/forms/from-db loads from database |
| `test_page_handler_index` | Module 6 | GET / returns landing page HTML |
| `test_page_handler_gallery` | Module 6 | GET /gallery lists forms |
| `test_page_handler_render` | Module 6 | GET /forms/{id} renders form HTML |
| `test_page_handler_submit` | Module 6 | POST /forms/{id} validates and responds |
| `test_backward_compat` | Module 7 | `from parrot.forms import FormSchema` still works |
| `test_setup_routes` | Module 6 | `setup_form_routes()` registers all expected routes |

### Integration Tests

| Test | Description |
|---|---|
| `test_nlp_form_e2e` | Create form from prompt via API, retrieve schema, render HTML, validate submission |
| `test_db_form_e2e` | Load form from DB via API, render, validate |
| `test_msteams_import_compat` | MS Teams dialog imports work unchanged |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_form_schema() -> FormSchema:
    """A minimal valid FormSchema for testing."""
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        fields=[
            FormField(name="name", field_type=FieldType.TEXT, label="Name"),
            FormField(name="email", field_type=FieldType.EMAIL, label="Email"),
        ],
    )

@pytest.fixture
def app_with_routes(sample_form_schema) -> web.Application:
    """aiohttp Application with form routes registered."""
    app = web.Application()
    registry = FormRegistry()
    setup_form_routes(app, registry=registry)
    return app
```

---

## 5. Acceptance Criteria

- [ ] `parrot-formdesigner` installs independently: `uv pip install -e packages/parrot-formdesigner`
- [ ] All existing `parrot.forms` unit tests pass under the new package location
- [ ] `from parrot.forms import FormSchema, CreateFormTool, ...` still works (re-export shim)
- [ ] REST API serves JSON Schema (structural + style) for any registered form
- [ ] REST API serves rendered HTML5 for any registered form
- [ ] REST API creates forms from natural language prompts
- [ ] REST API loads forms from database definitions
- [ ] REST API validates form submissions and returns structured errors
- [ ] `setup_form_routes()` enables one-line integration into any aiohttp app
- [ ] `examples/forms/form_server.py` reduced to <50 lines using `setup_form_routes()`
- [ ] MS Teams integration (`parrot/integrations/msteams/`) works unchanged
- [ ] No breaking changes to existing public API
- [ ] All new handler tests pass (`pytest tests/ -v`)

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Use `src/` layout matching `packages/ai-parrot/` structure
- Namespace package: `parrot` namespace shared between `ai-parrot` and `parrot-formdesigner`
  via implicit namespace packages (no `__init__.py` in `parrot/` directory)
- Async-first design throughout — all handlers are `async def`
- Pydantic models for all request/response data
- Comprehensive logging with `self.logger` in handler classes
- aiohttp `web.RouteTableDef` or manual `app.router.add_*` for route registration

### Known Risks / Gotchas

- **Namespace package collision**: Both packages define modules under `parrot.*`.
  Must use implicit namespace packages (PEP 420) — no `__init__.py` at the `parrot/`
  level in either package. Verify editable installs work together.
- **Circular dependency risk**: `parrot-formdesigner` tools depend on `AbstractTool`
  from `ai-parrot`, but `ai-parrot` re-exports from `parrot-formdesigner`. The
  re-export shim must use lazy imports to avoid circular import at module load.
- **Test migration**: Moving tests requires updating import paths and CI config.
  Keep both locations temporarily during transition if needed.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.0` | All schema models |
| `aiohttp` | `>=3.9` | HTTP handlers |
| `asyncdb` | `>=2.0` | DatabaseFormTool + PostgresFormStorage |
| `ai-parrot` | `>=0.9` | AbstractTool base class (optional dependency for tools) |

---

## 7. Open Questions

- [x] Should the tools subpackage remain in `ai-parrot` (since they depend on `AbstractTool`) and only core + handlers move to `parrot-formdesigner`? This would eliminate the circular dependency. — *Owner: Jesus Lara*: Methods for Form Creation and Form creation from DB will be moved to new package, but tools in ai-parrot will be thin-client of those methods (and remain in ai-parrot)
- [x] Should the package name be `parrot-formdesigner` or `parrot-forms`? The latter is simpler but the namespace `parrot.forms` is already used. — *Owner: Jesus Lara*: `parrot-formdesigner` avoid the clash with existing namespace.
- [x] Should the re-export shim emit deprecation warnings to encourage migration to direct imports? — *Owner: Jesus Lara*: No, this is a non-production feature, we don't need deprecation warnings.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all tasks run sequentially in one worktree.
- **Reason**: Every module depends on the package scaffold (Module 1), and the re-export
  shim (Module 7) must be tested against all moved modules. Sequential execution avoids
  merge conflicts in `__init__.py` files and import paths.
- **Cross-feature dependencies**: None — FEAT-076 and FEAT-078 are already completed.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-03 | Jesus Lara | Initial draft |
