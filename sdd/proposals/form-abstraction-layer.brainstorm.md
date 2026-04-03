# Brainstorm: Universal Form Abstraction Layer

**Date**: 2026-04-02
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

AI-Parrot's form system is currently tightly coupled to MS Teams. The canonical models (`FormDefinition`, `FormField`, `FormSection`) live in `parrot/integrations/dialogs/` as dataclasses, while rendering (`AdaptiveCardBuilder`), validation (`FormValidator`), orchestration (`FormOrchestrator`), and dialog presets all reside under `parrot/integrations/msteams/`. This means:

- **No reuse across platforms**: Telegram, Slack, WhatsApp, and web frontends cannot use the form system.
- **No LLM-driven form creation**: The existing `LLMFormGenerator` optimizes tool schemas but cannot create forms from natural language prompts.
- **Dataclass limitations**: The current models lack native JSON Schema export, Pydantic validation, and serialization features needed for storage and API transport.
- **No style separation**: Presentation concerns (wizard vs. single-column, field sizing) are baked into the `DialogPreset` enum and dialog implementations rather than being a separate, composable schema.

The form system needs to become a **platform-agnostic core** that any integration or frontend can consume.

## Constraints & Requirements

- Must replace existing dataclass models with Pydantic BaseModel (hard cutover, no adapter layer)
- All existing Teams consumers (FormOrchestrator, FormDialogFactory, RequestFormTool, 4 dialog presets) must be rewritten simultaneously
- v1 renderers: AdaptiveCard, HTML5 fragment, JSON Schema (structural + style)
- Validation must be platform-agnostic, co-located with schema (not in msteams/)
- FormSchema must be serializable for storage in PostgreSQL and ArangoDB
- LLM must be able to create FormSchema from natural language via a new tool
- Async-first, consistent with project patterns
- Schema extractors for: Pydantic models, Tool args_schema, YAML files, JSON Schema passthrough
- Navigator DataModel extractor is desired but not required for v1

---

## Options Explored

### Option A: Top-Level `parrot/forms/` with Schema/Style Split and Pluggable Renderers

Build a new `parrot/forms/` package as the canonical home for form schemas, validation, extraction, and rendering abstractions. The package structure:

```
parrot/forms/
├── __init__.py
├── schema.py          # FormSchema, FormField, FormSection, FieldType, etc.
├── style.py           # StyleSchema, LayoutType, FieldStyleHint
├── constraints.py     # FieldConstraints, FieldCondition, DependencyRule
├── options.py         # FieldOption, OptionsSource
├── validators.py      # FormValidator (migrated + enhanced)
├── extractors/
│   ├── __init__.py
│   ├── pydantic.py    # Pydantic model → FormSchema
│   ├── tool.py        # AbstractTool args_schema → FormSchema
│   ├── yaml.py        # YAML file → FormSchema
│   └── jsonschema.py  # JSON Schema passthrough → FormSchema
├── renderers/
│   ├── __init__.py
│   ├── base.py        # AbstractFormRenderer
│   ├── adaptive_card.py  # MS Teams Adaptive Cards
│   ├── html5.py       # HTML5 <form> fragment
│   └── jsonschema.py  # JSON Schema output (structural + style)
├── registry.py        # FormRegistry (migrated + persistence support)
├── storage.py         # PostgreSQL persistence for FormSchema
└── tools/
    ├── __init__.py
    ├── request_form.py   # RequestFormTool (migrated)
    └── create_form.py    # CreateFormTool (LLM creates forms from prompts)
```

The existing `parrot/integrations/dialogs/` models, parser, cache, and registry are **migrated** into this new package. The Teams-specific dialog presets and orchestrator remain in `msteams/` but import from `parrot/forms/`.

FormSchema and StyleSchema are separate Pydantic models. FormSchema is the canonical data definition (what the form is), StyleSchema is the presentation context (how it looks). Both serialize to JSON and can be stored independently.

Renderers implement `AbstractFormRenderer.render(form, style) -> RenderedForm` where `RenderedForm` is a union type carrying the platform-specific output (dict for Adaptive Cards, str for HTML, dict for JSON Schema).

The JSON Schema renderer produces two outputs: a structural schema (fields, sections, constraints, conditional visibility as `x-depends-on` extensions) and a style schema (layout, field sizing, theme). This is designed for frontend form-builder consumption and Svelte component generation.

The HTML5 renderer produces a `<form>` fragment with inline validation attributes, conditional visibility via `data-depends-on` attributes, and a submit handler that POSTs to the `SubmitAction` endpoint.

Schema extractors are stateless functions: `extract_from_pydantic(model) -> FormSchema`, `extract_from_tool(tool) -> FormSchema`, etc.

The `CreateFormTool` is a new agent tool that accepts a natural language prompt and returns a FormSchema. It uses the agent's LLM to generate the schema, validates it, and optionally persists it via `FormRegistry` with `persistence=True` (PostgreSQL storage).

**Migration**: The existing `FormField.from_pydantic_field()`, `FormDefinition.from_tool_schema()`, `FormDefinition.from_yaml()` logic moves into the respective extractors. The existing `AdaptiveCardBuilder` is refactored into the `AdaptiveCardRenderer`. The `FormValidator` moves from `msteams/dialogs/` to `parrot/forms/validators.py` with enhanced validation types.

Pros:
- Clean separation of concerns: schema, style, extraction, rendering, storage
- Single canonical location for all form logic
- Extractors and renderers are independently testable
- FormSchema is a Pydantic model with native JSON Schema export, validation, and serialization
- StyleSchema travels with the rendering context, not with the data definition
- JSON Schema renderer enables frontend form-builder integration and Svelte generation
- LLM form creation is a first-class tool
- Existing code is migrated, not thrown away — logic is preserved

Cons:
- Large migration surface: all Teams consumers must be rewritten simultaneously
- Significant effort due to hard cutover (no adapter layer)
- JSON Schema extensions (`x-depends-on`) are non-standard

Effort: High

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `pydantic>=2.0` | Schema models, validation, JSON Schema export | Already in project |
| `pyyaml` / `yaml_rs` | YAML form parsing | Already in project |
| `asyncpg` | PostgreSQL persistence for FormSchema | Already in project |
| `jinja2` | HTML5 template rendering for form fragments | Lightweight, mature |

Existing Code to Reuse:
- `parrot/integrations/dialogs/models.py` — FieldType enum, FormField.from_pydantic_field(), FormDefinition.from_tool_schema(), YAML parsing logic
- `parrot/integrations/dialogs/parser.py` — YAML parsing with yaml_rs/PyYAML fallback
- `parrot/integrations/dialogs/registry.py` — FormRegistry pattern (thread-safe, callbacks, directory loading)
- `parrot/integrations/dialogs/cache.py` — Caching with file watching and Redis support
- `parrot/integrations/dialogs/llm_generator.py` — LLMFormGenerator Pydantic introspection and type mapping
- `parrot/integrations/msteams/dialogs/validator.py` — FormValidator validation rules and type coercion
- `parrot/integrations/msteams/dialogs/card_builder.py` — AdaptiveCardBuilder field-to-card mapping logic
- `parrot/integrations/msteams/tools/request_form.py` — RequestFormTool flow and schema generation

---

### Option B: Extend Existing `parrot/integrations/dialogs/` In-Place

Keep the form models in their current location but convert them from dataclasses to Pydantic models. Add the StyleSchema alongside the existing models. Add renderers as submodules of `parrot/integrations/dialogs/renderers/`. Move the FormValidator from msteams into dialogs.

This is the minimal-change approach: same directory structure, less disruption, but "integrations/dialogs" remains a misleading name for what is now a core framework component.

Pros:
- Smaller diff, fewer file moves
- Existing imports change minimally (just the model types)
- Lower risk of breaking something during migration

Cons:
- "integrations/dialogs" is semantically wrong for a core form abstraction
- Mixes integration-specific code with core framework code
- No clear package boundary — easier for future developers to couple things
- Harder to package independently if forms ever become a standalone library

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `pydantic>=2.0` | Schema models | Already in project |
| `jinja2` | HTML5 rendering | Lightweight |

Existing Code to Reuse:
- Same as Option A, but files stay in place rather than moving

---

### Option C: JSON Schema as the Canonical Schema (No Custom Models)

Instead of defining custom Pydantic models for FormSchema, use raw JSON Schema as the canonical representation. Extend it with custom keywords (`x-field-type`, `x-section`, `x-depends-on`, `x-style`) to carry form-specific semantics. Extractors produce JSON Schema dicts directly. Renderers consume JSON Schema dicts.

This maximizes interoperability with the JSON Schema ecosystem (react-jsonschema-form, ajv, etc.) and avoids maintaining a parallel schema format.

Pros:
- Maximum interoperability with JSON Schema tooling
- No custom schema format to learn — developers already know JSON Schema
- Pydantic models already export JSON Schema, so extraction is trivial
- Frontend form builders can consume directly

Cons:
- JSON Schema is verbose and hard to work with programmatically (deeply nested dicts)
- Custom extensions (`x-*`) are ignored by standard validators — validation logic must be custom anyway
- No type safety in Python — working with raw dicts instead of typed models
- Conditional visibility, sections, and style don't map naturally to JSON Schema
- Loses the ergonomics of Pydantic model validation, auto-completion, and documentation
- Harder to serialize/deserialize for storage (no model_validate / model_dump)

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `jsonschema` | JSON Schema validation | Standard library |
| `jinja2` | HTML5 rendering | Lightweight |

Existing Code to Reuse:
- `parrot/tools/abstract.py` — `get_schema()` already produces JSON Schema
- `parrot/integrations/dialogs/llm_generator.py` — JSON Schema type mapping

---

## Recommendation

**Option A** is recommended because:

1. **Correct architectural boundary**: Forms are a core framework concern, not an integration detail. `parrot/forms/` makes this explicit and prevents future coupling.

2. **Pydantic models over raw JSON Schema**: The ergonomics of typed models (auto-completion, validation, serialization, documentation) far outweigh the interoperability benefits of raw JSON Schema. The JSON Schema renderer covers the interop use case without sacrificing Python-side developer experience.

3. **Hard cutover is acceptable**: The Teams integration is the only consumer today. Rewriting all consumers at once avoids maintaining an adapter layer and produces a cleaner result. The migration surface is large but well-understood — the existing logic is being moved and improved, not replaced.

4. **Style separation is worth the effort**: Having FormSchema and StyleSchema as independent, composable models is the right long-term design. The same form renders differently on Teams (wizard), web (two-column), and Telegram (conversational), and the style should travel with the rendering context.

The tradeoff is higher effort and migration risk, which is acceptable given that the existing system is well-tested and the migration is primarily structural (moving code, converting dataclasses to Pydantic).

---

## Feature Description

### User-Facing Behavior

**For developers building integrations:**
- Import `from parrot.forms import FormSchema, FormField, FormSection, StyleSchema`
- Create forms programmatically via Pydantic models, extract from tool schemas, or load from YAML
- Choose a renderer: `AdaptiveCardRenderer`, `HTML5Renderer`, `JsonSchemaRenderer`
- Register forms in `FormRegistry` for lookup by ID or trigger phrases
- Optionally persist forms to PostgreSQL with `persistence=True`

**For AI agents:**
- `RequestFormTool` works as before but uses the new `FormSchema` internally
- New `CreateFormTool` accepts a natural language prompt (e.g., "create a customer feedback form with name, email, rating 1-5, and comments") and returns a validated `FormSchema`
- Agents can specify `persistence=True` to save LLM-generated forms for reuse

**For end users:**
- Forms appear in their platform's native format (Adaptive Cards in Teams, HTML forms in web, etc.)
- Validation is consistent across platforms
- Conditional visibility works everywhere (show/hide fields based on other field values)

### Internal Behavior

**Schema Layer** (`parrot/forms/schema.py`, `style.py`, `constraints.py`):
- `FormSchema` is the single source of truth for form structure. It contains sections, fields, constraints, conditional visibility rules, and submit actions.
- `StyleSchema` is an optional presentation layer. If not provided, renderers use sensible defaults.
- Both are Pydantic BaseModels with full JSON Schema export via `model_json_schema()`.

**Extraction Layer** (`parrot/forms/extractors/`):
- Stateless functions that produce `FormSchema` from various sources.
- `PydanticExtractor`: Introspects `model_fields`, `__annotations__`, `Field()` metadata to produce fields with correct types, constraints, and options.
- `ToolExtractor`: Uses `AbstractTool.args_schema` (Pydantic model) → delegates to PydanticExtractor with additional metadata (tool name, description).
- `YamlExtractor`: Parses YAML using yaml_rs/PyYAML, maps to FormSchema. Preserves backward compatibility with existing YAML format.
- `JsonSchemaExtractor`: Passthrough for pre-existing JSON Schemas, mapping JSON Schema types and constraints to FormField equivalents.

**Rendering Layer** (`parrot/forms/renderers/`):
- `AbstractFormRenderer.render(form, style) -> RenderedForm` — async method.
- `AdaptiveCardRenderer`: Produces Adaptive Card JSON (dict). Maps FieldType to AC input types. Handles sections as separate cards (wizard mode) or single card. Migrated from `AdaptiveCardBuilder`.
- `HTML5Renderer`: Produces `<form>` HTML fragment (str). Uses Jinja2 templates. Includes inline validation attributes (`required`, `minlength`, `pattern`), `data-depends-on` attributes for conditional visibility, and a submit handler targeting the `SubmitAction` endpoint.
- `JsonSchemaRenderer`: Produces two JSON documents — structural schema (fields, sections, constraints, conditional visibility as `x-depends-on` extensions) and style schema (layout, field sizing, theme). Designed for frontend form-builder consumption and Svelte component generation.

**Validation Layer** (`parrot/forms/validators.py`):
- Migrated from `msteams/dialogs/validator.py`.
- Validates form submissions against `FormSchema` constraints.
- Enhanced validation types beyond current set:
  - `UNIQUE` — field value must be unique (requires external check callback)
  - `CUSTOM_REGEX` — named regex patterns (e.g., phone formats per locale)
  - `RANGE` — combined min/max for numeric fields
  - `FILE_TYPE` — MIME type validation for file uploads
  - `CROSS_FIELD` — validation rules that reference other fields (e.g., "end_date must be after start_date")
  - `ASYNC_REMOTE` — server-side async validation (e.g., "check if username is available")
- Returns `ValidationResult` with field-level errors and sanitized data.

**Storage Layer** (`parrot/forms/storage.py`):
- PostgreSQL persistence for FormSchema via asyncpg.
- Table: `form_schemas(id, form_id, version, schema_json, style_json, created_at, updated_at, created_by)`
- CRUD operations: `save()`, `load()`, `list()`, `delete()`, `find_by_form_id()`
- FormRegistry integration: when `persistence=True`, forms are saved to DB and loaded into registry on startup.

**Tool Layer** (`parrot/forms/tools/`):
- `RequestFormTool`: Migrated from msteams. When an agent needs structured input, it calls this tool with a target tool name. The tool extracts FormSchema from the target tool's args_schema, applies known values, and returns the schema for rendering.
- `CreateFormTool`: New tool. Accepts a natural language prompt. Uses the agent's LLM to generate a FormSchema JSON, validates it against the Pydantic model, optionally persists it, and returns it for rendering or storage.

**Integration Points:**
- `parrot/integrations/msteams/` imports from `parrot/forms/` instead of `parrot/integrations/dialogs/`
- Dialog presets (Simple, Wizard, WizardSummary, Conversational) consume `FormSchema` instead of `FormDefinition`
- `FormOrchestrator` uses `FormSchema` and delegates rendering to `AdaptiveCardRenderer`
- Future integrations (Telegram, Slack, web) import the appropriate renderer

### Edge Cases & Error Handling

- **Invalid FormSchema from LLM**: `CreateFormTool` validates the LLM-generated JSON against the `FormSchema` Pydantic model. If validation fails, it retries with error feedback (up to 2 retries), then returns a clear error.
- **Missing renderer for platform**: If no renderer is registered for a platform, raise `FormRenderError` with a message suggesting available renderers.
- **Circular dependencies in conditional visibility**: Validate `DependencyRule` references at schema creation time — reject circular `depends_on` chains.
- **Empty sections**: Sections with zero visible fields (all hidden by conditions) are skipped by renderers.
- **Unknown FieldType in renderer**: Renderers must handle unknown field types gracefully by falling back to a text input with a warning log.
- **Storage failures**: PostgreSQL save failures are logged and raised — forms still work in-memory via FormRegistry, persistence is best-effort if configured.
- **YAML backward compatibility**: The YAML extractor must continue to accept the existing YAML format used by current forms. New features (constraints, depends_on) use new YAML keys.
- **Large forms**: HTML5 renderer must handle forms with 50+ fields without performance degradation. Consider lazy rendering for wizard mode.

---

## Capabilities

### New Capabilities
- `form-schema-core`: Canonical FormSchema, FormField, FormSection, StyleSchema Pydantic models with full JSON Schema export
- `form-extractors`: Schema extractors for Pydantic models, Tool args_schema, YAML files, JSON Schema passthrough
- `form-renderers`: AbstractFormRenderer with AdaptiveCard, HTML5, and JSON Schema implementations
- `form-validators`: Platform-agnostic form validation with enhanced validation types (cross-field, async remote, file type)
- `form-storage`: PostgreSQL persistence for FormSchema with CRUD operations
- `form-create-tool`: LLM-powered form creation from natural language prompts
- `form-registry-persistence`: FormRegistry with optional database-backed persistence

### Modified Capabilities
- `msteams-forms`: Rewrite all Teams form consumers (dialog presets, orchestrator, factory, card builder) to use `parrot/forms/` instead of `parrot/integrations/dialogs/`
- `request-form-tool`: Migrate RequestFormTool to use FormSchema, move to `parrot/forms/tools/`

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/integrations/dialogs/` | replaces | Entire module migrated to `parrot/forms/`; old module deprecated/removed |
| `parrot/integrations/msteams/dialogs/` | modifies | Dialog presets, orchestrator, factory rewritten to consume FormSchema |
| `parrot/integrations/msteams/tools/request_form.py` | moves | Migrated to `parrot/forms/tools/request_form.py` |
| `parrot/integrations/msteams/wrapper.py` | modifies | Import paths change, FormDefinition → FormSchema |
| `parrot/tools/abstract.py` | depends on | Extractors use `args_schema` and `get_schema()` — no changes needed |
| `parrot/integrations/msteams/dialogs/card_builder.py` | replaces | Logic migrated to `parrot/forms/renderers/adaptive_card.py` |
| `parrot/integrations/msteams/dialogs/validator.py` | replaces | Logic migrated to `parrot/forms/validators.py` |
| Database (PostgreSQL) | extends | New `form_schemas` table for persistent form storage |

---

## Parallelism Assessment

- **Internal parallelism**: High. The feature decomposes into largely independent subsystems:
  - Schema models (schema.py, style.py, constraints.py) — foundation, must be first
  - Extractors (pydantic, tool, yaml, jsonschema) — independent of each other, depend only on schema models
  - Renderers (adaptive_card, html5, jsonschema) — independent of each other, depend only on schema models
  - Validators — depends only on schema models
  - Storage — depends only on schema models
  - Tools (request_form, create_form) — depend on schema + extractors + registry
  - Teams migration — depends on schema + renderers + validators
- **Cross-feature independence**: No conflicts with in-flight specs. The `parrot/integrations/dialogs/` module is not being modified by other features.
- **Recommended isolation**: `mixed` — schema models are the foundation (sequential first task), then extractors, renderers, validators, and storage can be parallelized across worktrees. Teams migration and tools are final sequential tasks.
- **Rationale**: The schema models are a hard dependency for everything else, but once they exist, the extractors, renderers, validators, and storage have no interdependencies and can be developed in parallel.

---

## Open Questions

- [x] Should the HTML5 renderer include client-side JavaScript for conditional visibility, or rely on the consuming frontend to handle `data-depends-on` attributes? — *Owner: Jesus Lara*: rely on frontend to handle the `data-depends-on` attributes.
- [x] What PostgreSQL table schema and migration strategy for `form_schemas`? Use alembic or raw SQL? — *Owner: Jesus Lara*: RAW SQL.
- [x] Should `CreateFormTool` support iterative refinement (e.g., "add a phone field to that form") or only one-shot creation? — *Owner: Jesus Lara*: iterative refinement.
- [x] Should the JSON Schema renderer output be compatible with a specific form-builder library (e.g., react-jsonschema-form, formly, or custom Svelte)? — *Owner: Jesus Lara*: Custom svelte for now.
- [x] What is the deprecation/removal timeline for `parrot/integrations/dialogs/`? Immediate removal or keep as deprecated alias for one release? — *Owner: Jesus Lara*: Immediate removal.
- [x] Should FormSchema support i18n (field labels/descriptions in multiple languages) in v1 or defer? — *Owner: Jesus Lara*: support i18n on v1 directly.
