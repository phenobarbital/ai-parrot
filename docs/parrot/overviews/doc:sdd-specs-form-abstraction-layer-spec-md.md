---
type: Wiki Overview
title: 'Feature Specification: Universal Form Abstraction Layer'
id: doc:sdd-specs-form-abstraction-layer-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot's form system is tightly coupled to MS Teams. The canonical models
  (`FormDefinition`, `FormField`, `FormSection`) live in `parrot/integrations/dialogs/`
  as Python dataclasses, while rendering (`AdaptiveCardBuilder`), validation (`FormValidator`),
  orchestration (`FormOrc
---

# Feature Specification: Universal Form Abstraction Layer

**Feature ID**: FEAT-076
**Date**: 2026-04-02
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.0.0
**Brainstorm**: `sdd/proposals/form-abstraction-layer.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot's form system is tightly coupled to MS Teams. The canonical models (`FormDefinition`, `FormField`, `FormSection`) live in `parrot/integrations/dialogs/` as Python dataclasses, while rendering (`AdaptiveCardBuilder`), validation (`FormValidator`), orchestration (`FormOrchestrator`), and dialog presets all reside under `parrot/integrations/msteams/dialogs/`. This prevents any other integration (Telegram, Slack, WhatsApp, web frontends) from using the form system.

The dataclass-based models lack native JSON Schema export, Pydantic validation, and the serialization needed for database storage and API transport. Presentation concerns (wizard vs. single-column) are embedded in the `DialogPreset` enum rather than being a separate composable layer. There is no way for an LLM to create forms from natural language prompts.

### Goals

- Create a platform-agnostic `parrot/forms/` package as the canonical home for form schemas, validation, extraction, and rendering
- Replace dataclass-based `FormDefinition` with Pydantic-based `FormSchema` (hard cutover)
- Separate data definition (FormSchema) from presentation (StyleSchema)
- Deliver v1 renderers: AdaptiveCard, HTML5 `<form>` fragment, JSON Schema (structural + style for custom Svelte form-builder)
- Move `FormValidator` to core with enhanced validation types
- Build schema extractors for Pydantic models, Tool args_schema, YAML files, and JSON Schema passthrough
- Add `CreateFormTool` for LLM-driven form creation from natural language with iterative refinement
- Add PostgreSQL persistence for FormSchema with optional `persistence=True`
- Support i18n for field labels and descriptions in v1

### Non-Goals (explicitly out of scope)

- Navigator DataModel extractor (deferred to v2)
- Telegram, Slack, or WhatsApp renderers (deferred — only Teams + HTML5 + JSON Schema in v1)
- Client-side JavaScript in HTML5 renderer (frontend handles `data-depends-on` attributes)
- Alembic migrations (raw SQL for `form_schemas` table)
- Form analytics or usage tracking
- Visual form builder UI

---

## 2. Architectural Design

### Overview

A new top-level `parrot/forms/` package replaces `parrot/integrations/dialogs/` entirely (immediate removal). The package contains:

1. **Schema models** — Pydantic BaseModels for `FormSchema`, `FormField`, `FormSection`, `StyleSchema`, constraints, options, and conditional visibility rules. All models support i18n via `LocalizedString` fields.
2. **Extractors** — Stateless converters that produce `FormSchema` from Pydantic models, Tool args_schema, YAML files, and JSON Schema.
3. **Renderers** — `AbstractFormRenderer` with implementations for Adaptive Cards, HTML5, and JSON Schema output.
4. **Validators** — Platform-agnostic form validation migrated from msteams with enhanced types.
5. **Registry + Storage** — In-memory `FormRegistry` with optional PostgreSQL persistence.
6. **Tools** — `RequestFormTool` (migrated) and `CreateFormTool` (new, LLM-driven with iterative refinement).

The MS Teams integration (`parrot/integrations/msteams/dialogs/`) is rewritten to import from `parrot/forms/`.

### Component Diagram

```
Sources                          Core Package                      Consumers
─────────                        ────────────                      ─────────

Pydantic Model ──┐               parrot/forms/
Tool args_schema ──┤               ┌──────────────────┐
YAML file ────────┼── Extractors ──→│  FormSchema      │
JSON Schema ──────┘               │  StyleSchema      │──→ FormRegistry
                                  │  FieldConstraints │        │
LLM Prompt ───→ CreateFormTool ──→│  DependencyRule   │        ├──→ PostgreSQL
                                  └────────┬─────────┘        │     (persistence=True)
                                           │                   │
                                    FormValidator              │
                                           │                   │
                                      Renderers ◄──────────────┘
                                      ┌────┴────┐
                                      │         │
                              AdaptiveCard  HTML5  JsonSchema
                                  │         │         │
                              MS Teams    Web API    Svelte
                              Wrapper     Endpoint   Frontend
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/integrations/dialogs/` | replaces (immediate removal) | All models, parser, cache, registry migrated to `parrot/forms/` |
| `parrot/integrations/msteams/dialogs/card_builder.py` | replaces | Logic migrated to `parrot/forms/renderers/adaptive_card.py` |
| `parrot/integrations/msteams/dialogs/validator.py` | replaces | Logic migrated to `parrot/forms/validators.py` |
| `parrot/integrations/msteams/dialogs/orchestrator.py` | modifies | Imports from `parrot/forms/`, uses `FormSchema` instead of `FormDefinition` |
| `parrot/integrations/msteams/dialogs/factory.py` | modifies | Creates dialogs from `FormSchema` + `StyleSchema` |
| `parrot/integrations/msteams/dialogs/presets/*.py` | modifies | All 4 presets consume `FormSchema` instead of `FormDefinition` |
| `parrot/integrations/msteams/tools/request_form.py` | moves | Migrated to `parrot/forms/tools/request_form.py` |
| `parrot/integrations/msteams/wrapper.py` | modifies | Import paths change, `FormDefinition` → `FormSchema` |
| `parrot/tools/abstract.py` | depends on (no changes) | Extractors use `args_schema` and `get_schema()` |
| PostgreSQL | extends | New `form_schemas` table |

### Data Models

```python
# ── i18n Support ─────────────────────────────────────────────

LocalizedString = str | dict[str, str]
# Simple: "Enter your name"
# i18n:   {"en": "Enter your name", "es": "Ingrese su nombre"}


# ── Field Types ──────────────────────────────────────────────

class FieldType(str, Enum):
    TEXT = "text"
    TEXT_AREA = "text_area"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    FILE = "file"
    IMAGE = "image"
    COLOR = "color"
    URL = "url"
    EMAIL = "email"
    PHONE = "phone"
    PASSWORD = "password"
    HIDDEN = "hidden"
    GROUP = "group"       # nested field group (sub-form)
    ARRAY = "array"       # repeatable field/group


# ── Constraints ──────────────────────────────────────────────

class FieldConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_length: int | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    pattern: str | None = None
    pattern_message: LocalizedString | None = None
    min_items: int | None = None
    max_items: int | None = None
    allowed_mime_types: list[str] | None = None
    max_file_size_bytes: int | None = None


# ── Options ──────────────────────────────────────────────────

class FieldOption(BaseModel):
    value: str
    label: LocalizedString
    description: LocalizedString | None = None
    disabled: bool = False
    icon: str | None = None

class OptionsSource(BaseModel):
    source_type: str      # "endpoint", "dataset", "enum", "tool"
    source_ref: str
    value_field: str = "value"
    label_field: str = "label"
    cache_ttl_seconds: int | None = None


# ── Conditional Visibility ───────────────────────────────────

class ConditionOperator(str, Enum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    LT = "lt"
    GTE = "gte"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    IS_EMPTY = "is_empty"
    IS_NOT_EMPTY = "is_not_empty"

class FieldCondition(BaseModel):
    field_id: str
    operator: ConditionOperator
    value: Any = None

class DependencyRule(BaseModel):
    conditions: list[FieldCondition]
    logic: Literal["and", "or"] = "and"
    effect: Literal["show", "hide", "require", "disable"] = "show"


# ── Core Models ──────────────────────────────────────────────

class FormField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_id: str
    field_type: FieldType
    label: LocalizedString
    description: LocalizedString | None = None
    placeholder: LocalizedString | None = None
    required: bool = False
    default: Any = None
    read_only: bool = False
    constraints: FieldConstraints | None = None
    options: list[FieldOption] | None = None
    options_source: OptionsSource | None = None
    depends_on: DependencyRule | None = None
    children: list["FormField"] | None = None     # for GROUP
    item_template: "FormField | None" = None       # for ARRAY
    meta: dict[str, Any] | None = None

class FormSection(BaseModel):
    section_id: str
    title: LocalizedString | None = None
    description: LocalizedString | None = None
    fields: list[FormField]
    depends_on: DependencyRule | None = None
    meta: dict[str, Any] | None = None

class SubmitAction(BaseModel):
    action_type: Literal["tool_call", "endpoint", "event", "callback"]
    action_ref: str
    method: str = "POST"
    confirm_message: LocalizedString | None = None

class FormSchema(BaseModel):
    form_id: str
    version: str = "1.0"
    title: LocalizedString
    description: LocalizedString | None = None
    sections: list[FormSection]
    submit: SubmitAction | None = None
    cancel_allowed: bool = True
    meta: dict[str, Any] | None = None


# ── Style Schema ─────────────────────────────────────────────

class LayoutType(str, Enum):
    SINGLE_COLUMN = "single_column"
    TWO_COLUMN = "two_column"
    WIZARD = "wizard"
    ACCORDION = "accordion"
    TABS = "tabs"
    INLINE = "inline"

class FieldSizeHint(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    FULL = "full"

class FieldStyleHint(BaseModel):
    size: FieldSizeHint | None = None
    order: int | None = None
    css_class: str | None = None
    variant: str | None = None

class StyleSchema(BaseModel):
    layout: LayoutType = LayoutType.SINGLE_COLUMN
    field_styles: dict[str, FieldStyleHint] | None = None
    show_section_numbers: bool = False
    submit_label: LocalizedString = "Submit"
    cancel_label: LocalizedString = "Cancel"
    theme: str | None = None
    meta: dict[str, Any] | None = None
```

### New Public Interfaces

```python
# ── Extractors ───────────────────────────────────────────────

class PydanticExtractor:
    """Extract FormSchema from a Pydantic BaseModel class."""
    def extract(
        self,
        model: type[BaseModel],
        *,
        form_id: str | None = None,
        title: str | None = None,
        locale: str = "en",
    ) -> FormSchema: ...

class ToolExtractor:
    """Extract FormSchema from an AbstractTool's args_schema."""
    def extract(
        self,
        tool: AbstractTool,
        *,
        exclude_fields: set[str] | None = None,
        known_values: dict[str, Any] | None = None,
    ) -> FormSchema: ...

class YamlExtractor:
    """Extract FormSchema from a YAML file or string."""
    def extract_from_string(self, content: str) -> FormSchema: ...
    def extract_from_file(self, path: str | Path) -> FormSchema: ...

class JsonSchemaExtractor:
    """Extract FormSchema from a JSON Schema dict."""
    def extract(
        self,
        schema: dict[str, Any],
        *,
        form_id: str | None = None,
        title: str | None = None,
    ) -> FormSchema: ...


# ── Renderers ────────────────────────────────────────────────

class RenderedForm(BaseModel):
    """Output of a renderer."""
    content: Any           # dict (Adaptive Card/JSON Schema), str (HTML)
    content_type: str      # "application/json", "text/html", "application/schema+json"
    style_output: Any | None = None  # separate style JSON for JsonSchemaRenderer
    metadata: dict[str, Any] | None = None

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
    ) -> RenderedForm: ...

class AdaptiveCardRenderer(AbstractFormRenderer):
    """Render FormSchema as MS Teams Adaptive Card JSON."""
    async def render(...) -> RenderedForm: ...
    # Also supports section-by-section rendering for wizard mode:
    async def render_section(
        self,
        form: FormSchema,
        section_index: int,
        style: StyleSchema | None = None,
        *,
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
        show_back: bool = False,
        show_skip: bool = False,
    ) -> RenderedForm: ...
    async def render_summary(
        self,
        form: FormSchema,
        form_data: dict[str, Any],
        summary_text: str | None = None,
    ) -> RenderedForm: ...

class HTML5Renderer(AbstractFormRenderer):
    """Render FormSchema as <form> HTML fragment."""
    async def render(...) -> RenderedForm: ...

class JsonSchemaRenderer(AbstractFormRenderer):
    """Render FormSchema as JSON Schema (structural) + Style JSON."""
    async def render(...) -> RenderedForm: ...
    # RenderedForm.content = structural JSON Schema with x-depends-on extensions
    # RenderedForm.style_output = StyleSchema as JSON dict


# ── Validators ───────────────────────────────────────────────

class ValidationResult(BaseModel):
    is_valid: bool
    errors: dict[str, list[str]]  # field_id -> error messages
    sanitized_data: dict[str, Any]

class FormValidator:
    async def validate(
        self,
        form: FormSchema,
        data: dict[str, Any],
        *,
        locale: str = "en",
    ) -> ValidationResult: ...

    async def validate_field(
        self,
        field: FormField,
        value: Any,
        *,
        all_data: dict[str, Any] | None = None,  # for cross-field validation
        locale: str = "en",
    ) -> list[str]: ...  # list of error messages


# ── Registry + Storage ───────────────────────────────────────

class FormStorage(ABC):
    """Abstract storage backend for FormSchema persistence."""
    @abstractmethod
    async def save(self, form: FormSchema, style: StyleSchema | None = None) -> str: ...
    @abstractmethod
    async def load(self, form_id: str, version: str | None = None) -> FormSchema | None: ...
    @abstractmethod
    async def delete(self, form_id: str) -> bool: ...
    @abstractmethod
    async def list_forms(self) -> list[dict[str, str]]: ...

class PostgresFormStorage(FormStorage):
    """PostgreSQL-backed form persistence using asyncpg."""
    ...

class FormRegistry:
    """In-memory registry with optional persistent storage."""
    def __init__(self, storage: FormStorage | None = None): ...
    async def register(self, form: FormSchema, *, persist: bool = False) -> None: ...
    async def get(self, form_id: str) -> FormSchema | None: ...
    async def unregister(self, form_id: str) -> None: ...
    async def load_from_directory(self, path: str | Path) -> int: ...
    async def load_from_storage(self) -> int: ...


# ── Tools ────────────────────────────────────────────────────

class RequestFormTool(AbstractTool):
    """Meta-tool: LLM requests structured data collection via form."""
    name = "request_form"
    # Migrated from msteams, now uses FormSchema internally

class CreateFormTool(AbstractTool):
    """LLM creates a FormSchema from natural language. Supports iterative refinement."""
    name = "create_form"
    # args: prompt (str), form_id (str|None), persist (bool), refine_form_id (str|None)
    # When refine_form_id is set, loads existing form and applies modifications
```

---

## 3. Module Breakdown

### Module 1: Schema Core Models
- **Path**: `parrot/forms/schema.py`, `parrot/forms/style.py`, `parrot/forms/constraints.py`, `parrot/forms/options.py`, `parrot/forms/types.py`
- **Responsibility**: Define all Pydantic models — `FormSchema`, `FormField`, `FormSection`, `FieldType`, `FieldConstraints`, `FieldOption`, `OptionsSource`, `ConditionOperator`, `FieldCondition`, `DependencyRule`, `SubmitAction`, `StyleSchema`, `LayoutType`, `FieldSizeHint`, `FieldStyleHint`, `RenderedForm`, `LocalizedString`. Also the `parrot/forms/__init__.py` public API.
- **Depends on**: Nothing (foundation module)

### Module 2: Form Validators
- **Path**: `parrot/forms/validators.py`
- **Responsibility**: Platform-agnostic form validation. Migrates logic from `msteams/dialogs/validator.py`. Adds enhanced validation types: cross-field validation (`CROSS_FIELD` — e.g., end_date > start_date), async remote validation (`ASYNC_REMOTE` — e.g., username availability check via callback), file type validation (`FILE_TYPE` — MIME type checks), unique validation (`UNIQUE` — uniqueness via callback). Validates `DependencyRule` for circular references. Handles i18n error messages.
- **Depends on**: Module 1

### Module 3: Pydantic Extractor
- **Path**: `parrot/forms/extractors/pydantic.py`
- **Responsibility**: Introspect Pydantic BaseModel classes to produce `FormSchema`. Maps Python types to `FieldType`, extracts `Field()` metadata (description, constraints, defaults), handles `Optional`, `Literal`, `Enum`, nested models (→ `GROUP`), `list[T]` (→ `ARRAY`). Supports Pydantic v2 (`model_fields`, `model_json_schema()`). Migrates and extends logic from `FormField.from_pydantic_field()` and `LLMFormGenerator._schema_property_to_field()`.
- **Depends on**: Module 1

### Module 4: Tool Extractor
- **Path**: `parrot/forms/extractors/tool.py`
- **Responsibility**: Extract `FormSchema` from `AbstractTool.args_schema`. Delegates to Pydantic Extractor with tool-specific metadata (name, description as form title). Supports field filtering (exclude context fields, pre-filled values). Auto-selects section grouping based on field count. Migrates logic from `FormDefinition.from_tool_schema()`.
- **Depends on**: Module 1, Module 3

### Module 5: YAML Extractor
- **Path**: `parrot/forms/extractors/yaml.py`
- **Responsibility**: Parse YAML form definitions into `FormSchema`. Uses `yaml_rs` (Rust) with PyYAML fallback. Backward-compatible with existing YAML format (field name formats, validation syntax, choices). Adds support for new schema features (constraints, depends_on, i18n labels). Migrates logic from `parrot/integrations/dialogs/parser.py`.
- **Depends on**: Module 1

### Module 6: JSON Schema Extractor
- **Path**: `parrot/forms/extractors/jsonschema.py`
- **Responsibility**: Convert a standard JSON Schema dict into `FormSchema`. Maps JSON Schema types (`string`, `number`, `integer`, `boolean`, `array`, `object`) to `FieldType`. Extracts constraints (`minLength`, `maxLength`, `minimum`, `maximum`, `pattern`, `enum`). Handles `$ref` and `definitions`. Passthrough for pre-existing schemas.
- **Depends on**: Module 1

### Module 7: Adaptive Card Renderer
- **Path**: `parrot/forms/renderers/adaptive_card.py`
- **Responsibility**: Render `FormSchema` + `StyleSchema` as MS Teams Adaptive Card JSON. Migrates logic from `AdaptiveCardBuilder`. Maps `FieldType` to AC input types. Supports complete form (single card), section-by-section (wizard), summary card, and error card. Handles `StyleSchema.layout` to choose rendering mode. Handles `DependencyRule` via AC `Action.ToggleVisibility` where possible.
- **Depends on**: Module 1

### Module 8: HTML5 Renderer
- **Path**: `parrot/forms/renderers/html5.py`
- **Responsibility**: Render `FormSchema` + `StyleSchema` as an HTML `<form>` fragment. Uses Jinja2 templates. Maps `FieldType` to HTML5 input types with appropriate attributes (`required`, `minlength`, `maxlength`, `min`, `max`, `pattern`). Emits `data-depends-on` attributes for conditional visibility (frontend handles JS). Generates submit handler targeting `SubmitAction` endpoint. Supports `StyleSchema.layout` (single-column, two-column via CSS classes). i18n via `locale` parameter selecting the correct label variant.
- **Depends on**: Module 1

### Module 9: JSON Schema Renderer
- **Path**: `parrot/forms/renderers/jsonschema.py`
- **Responsibility**: Render `FormSchema` as two JSON outputs: (1) structural JSON Schema with `x-section`, `x-depends-on`, `x-field-type`, `x-options-source` extensions for rich form semantics; (2) style JSON from `StyleSchema`. Designed for consumption by custom Svelte form-builder components. The structural schema is a valid JSON Schema (fields as `properties`, constraints as standard keywords) with extensions for features that JSON Schema doesn't natively support.
- **Depends on**: Module 1

### Module 10: Form Registry
- **Path**: `parrot/forms/registry.py`
- **Responsibility**: Thread-safe in-memory registry for `FormSchema` instances. Supports registration, lookup by form_id, trigger phrase matching, directory loading (YAML). Migrates logic from `parrot/integrations/dialogs/registry.py`. Adds optional `FormStorage` backend for persistence. When `persist=True`, forms are saved to storage on register and loaded on startup.
- **Depends on**: Module 1

### Module 11: Form Cache
- **Path**: `parrot/forms/cache.py`
- **Responsibility**: In-memory cache for `FormSchema` with TTL, optional Redis backend, and file system watching for YAML auto-invalidation. Migrates logic from `parrot/integrations/dialogs/cache.py`.
- **Depends on**: Module 1, Module 10

### Module 12: PostgreSQL Form Storage
- **Path**: `parrot/forms/storage.py`
- **Responsibility**: Implements `FormStorage` using asyncpg. Table: `form_schemas(id UUID, form_id VARCHAR UNIQUE, version VARCHAR, schema_json JSONB, style_json JSONB, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ, created_by VARCHAR)`. CRUD operations. Schema creation via raw SQL (no Alembic). Handles `FormSchema.model_dump()` for serialization and `FormSchema.model_validate()` for deserialization.
- **Depends on**: Module 1, Module 10

### Module 13: RequestFormTool Migration
- **Path**: `parrot/forms/tools/request_form.py`
- **Responsibility**: Migrate `RequestFormTool` from `msteams/tools/`. Uses `ToolExtractor` to generate `FormSchema` from target tool. Returns `FormSchema` in `ToolResult` metadata with status `form_requested`. No longer Teams-specific — any integration wrapper can detect and render the form.
- **Depends on**: Module 1, Module 4, Module 10

### Module 14: CreateFormTool
- **Path**: `parrot/forms/tools/create_form.py`
- **Responsibility**: New agent tool. Accepts natural language prompt, uses the agent's LLM to generate `FormSchema` JSON. Validates output against Pydantic model (retries up to 2 times on validation failure with error feedback). Supports iterative refinement: when `refine_form_id` is provided, loads existing form from registry and applies modifications described in the prompt. Optionally persists via `FormRegistry` with `persist=True`.
- **Depends on**: Module 1, Module 2, Module 10, Module 12

### Module 15: MS Teams Integration Rewrite
- **Path**: `parrot/integrations/msteams/dialogs/` (all files)
- **Responsibility**: Rewrite all Teams consumers to use `parrot/forms/`:
  - `factory.py` — Creates dialogs from `FormSchema` + `StyleSchema` (maps `StyleSchema.layout` WIZARD/SINGLE_COLUMN to dialog presets)
  - `orchestrator.py` — Uses `FormSchema`, delegates rendering to `AdaptiveCardRenderer`
  - `presets/base.py` — `BaseFormDialog` stores `FormSchema` reference
  - `presets/simple_form.py` — Uses `AdaptiveCardRenderer.render()`
  - `presets/wizard.py` — Uses `AdaptiveCardRenderer.render_section()`
  - `presets/wizard_summary.py` — Uses `AdaptiveCardRenderer.render_summary()`

…(truncated)…
