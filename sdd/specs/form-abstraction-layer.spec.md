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
  - `presets/conversational.py` — Reads fields from `FormSchema`
  - `wrapper.py` — Import paths change
- **Depends on**: Module 1, Module 2, Module 7, Module 10

### Module 16: Remove Legacy Dialogs Module
- **Path**: `parrot/integrations/dialogs/` (entire directory)
- **Responsibility**: Delete `parrot/integrations/dialogs/` entirely — `models.py`, `parser.py`, `cache.py`, `registry.py`, `llm_generator.py`, `__init__.py`. All logic has been migrated to `parrot/forms/`. Update any remaining import references.
- **Depends on**: Module 15 (all consumers rewritten first)

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_form_schema_creation` | Module 1 | Create FormSchema with sections, fields, constraints; verify model validation |
| `test_form_schema_json_roundtrip` | Module 1 | `model_dump_json()` → `model_validate_json()` produces identical schema |
| `test_localized_string_variants` | Module 1 | LocalizedString works as plain str and as dict[str, str] |
| `test_dependency_rule_serialization` | Module 1 | DependencyRule with nested conditions serializes/deserializes correctly |
| `test_field_type_coverage` | Module 1 | All FieldType enum values can be used in FormField |
| `test_style_schema_defaults` | Module 1 | StyleSchema defaults to SINGLE_COLUMN layout |
| `test_validator_required` | Module 2 | Required field with missing value fails |
| `test_validator_min_max_length` | Module 2 | String length constraints enforced |
| `test_validator_pattern` | Module 2 | Regex pattern constraint enforced |
| `test_validator_numeric_range` | Module 2 | min_value/max_value enforced |
| `test_validator_cross_field` | Module 2 | Cross-field validation (e.g., end > start) |
| `test_validator_circular_dependency` | Module 2 | Circular depends_on detected and rejected |
| `test_validator_i18n_errors` | Module 2 | Error messages respect locale parameter |
| `test_pydantic_extractor_basic` | Module 3 | Simple Pydantic model → FormSchema with correct field types |
| `test_pydantic_extractor_optional` | Module 3 | Optional fields marked as not required |
| `test_pydantic_extractor_literal` | Module 3 | Literal types become SELECT with options |
| `test_pydantic_extractor_enum` | Module 3 | Enum types become SELECT with enum values |
| `test_pydantic_extractor_nested` | Module 3 | Nested model becomes GROUP field |
| `test_pydantic_extractor_list` | Module 3 | list[T] becomes ARRAY field |
| `test_tool_extractor_basic` | Module 4 | AbstractTool → FormSchema with tool name as title |
| `test_tool_extractor_exclude_fields` | Module 4 | Context fields excluded from form |
| `test_tool_extractor_known_values` | Module 4 | Pre-filled fields excluded |
| `test_yaml_extractor_existing_format` | Module 5 | Existing YAML format parses correctly (backward compat) |
| `test_yaml_extractor_new_features` | Module 5 | New constraints, depends_on, i18n parse correctly |
| `test_yaml_extractor_yaml_rs_fallback` | Module 5 | Falls back to PyYAML when yaml_rs unavailable |
| `test_jsonschema_extractor_types` | Module 6 | JSON Schema types map to correct FieldType |
| `test_jsonschema_extractor_constraints` | Module 6 | JSON Schema constraints map to FieldConstraints |
| `test_jsonschema_extractor_refs` | Module 6 | `$ref` and `definitions` resolved |
| `test_adaptive_card_complete` | Module 7 | Full form renders as valid Adaptive Card JSON |
| `test_adaptive_card_wizard` | Module 7 | Section-by-section rendering produces correct cards |
| `test_adaptive_card_style` | Module 7 | StyleSchema.layout affects card output |
| `test_html5_form_fragment` | Module 8 | Renders valid `<form>` HTML fragment |
| `test_html5_validation_attrs` | Module 8 | HTML5 validation attributes present (required, minlength, etc.) |
| `test_html5_depends_on_attrs` | Module 8 | `data-depends-on` attributes emitted |
| `test_html5_submit_action` | Module 8 | Submit handler generated for SubmitAction |
| `test_html5_i18n` | Module 8 | Labels render in requested locale |
| `test_jsonschema_renderer_structural` | Module 9 | Produces valid JSON Schema with extensions |
| `test_jsonschema_renderer_style` | Module 9 | Style output matches StyleSchema |
| `test_registry_crud` | Module 10 | Register, get, unregister work |
| `test_registry_directory_load` | Module 10 | Loads YAML forms from directory |
| `test_storage_crud` | Module 12 | Save, load, delete, list with PostgreSQL |
| `test_storage_versioning` | Module 12 | Multiple versions of same form_id stored |
| `test_create_form_basic` | Module 14 | LLM prompt produces valid FormSchema |
| `test_create_form_refinement` | Module 14 | Iterative refinement modifies existing form |
| `test_create_form_persistence` | Module 14 | persist=True saves to registry+storage |
| `test_create_form_validation_retry` | Module 14 | Invalid LLM output triggers retry with feedback |

### Integration Tests

| Test | Description |
|---|---|
| `test_tool_to_adaptive_card` | Extract FormSchema from tool → render as Adaptive Card → validate JSON structure |
| `test_yaml_to_html5` | Load YAML → extract FormSchema → render HTML5 → validate HTML |
| `test_pydantic_to_jsonschema` | Extract from Pydantic model → render JSON Schema → validate against JSON Schema spec |
| `test_registry_with_postgres` | Register with persistence → restart registry → load from storage → form available |
| `test_create_and_render` | CreateFormTool generates form → render with each renderer → all produce valid output |
| `test_teams_orchestrator_migration` | FormOrchestrator works with new FormSchema (form request → render → submit → tool execution) |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_form_schema() -> FormSchema:
    """A representative form with multiple field types, sections, and constraints."""
    return FormSchema(
        form_id="test-form",
        title={"en": "Test Form", "es": "Formulario de Prueba"},
        sections=[
            FormSection(
                section_id="personal",
                title={"en": "Personal Info", "es": "Información Personal"},
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True,
                              constraints=FieldConstraints(min_length=2, max_length=100)),
                    FormField(field_id="email", field_type=FieldType.EMAIL, label="Email", required=True),
                    FormField(field_id="role", field_type=FieldType.SELECT, label="Role",
                              options=[FieldOption(value="admin", label="Admin"),
                                       FieldOption(value="user", label="User")]),
                ],
            ),
            FormSection(
                section_id="preferences",
                title="Preferences",
                fields=[
                    FormField(field_id="notifications", field_type=FieldType.BOOLEAN, label="Enable notifications"),
                    FormField(field_id="frequency", field_type=FieldType.SELECT, label="Frequency",
                              options=[FieldOption(value="daily", label="Daily"),
                                       FieldOption(value="weekly", label="Weekly")],
                              depends_on=DependencyRule(
                                  conditions=[FieldCondition(field_id="notifications", operator=ConditionOperator.EQ, value=True)],
                                  effect="show")),
                ],
            ),
        ],
        submit=SubmitAction(action_type="endpoint", action_ref="/api/submit"),
    )

@pytest.fixture
def sample_style_schema() -> StyleSchema:
    return StyleSchema(layout=LayoutType.WIZARD, show_section_numbers=True,
                       submit_label={"en": "Send", "es": "Enviar"})

@pytest.fixture
def sample_pydantic_model():
    class CustomerFeedback(BaseModel):
        name: str = Field(..., description="Customer name")
        email: str = Field(..., description="Contact email")
        rating: int = Field(..., ge=1, le=5, description="Rating 1-5")
        comments: str | None = Field(None, description="Additional comments")
    return CustomerFeedback
```

---

## 5. Acceptance Criteria

- [ ] All unit tests pass (`pytest tests/unit/forms/ -v`)
- [ ] All integration tests pass (`pytest tests/integration/forms/ -v`)
- [ ] `parrot/integrations/dialogs/` is fully removed — no imports reference it
- [ ] All 9 msteams files that imported from dialogs now import from `parrot/forms/`
- [ ] FormSchema round-trips through JSON (dump → validate → identical)
- [ ] FormSchema round-trips through PostgreSQL (save → load → identical)
- [ ] AdaptiveCardRenderer produces valid Adaptive Card JSON (schema version 1.5)
- [ ] HTML5Renderer produces valid `<form>` fragment with correct validation attributes
- [ ] JsonSchemaRenderer produces valid JSON Schema plus separate style JSON
- [ ] CreateFormTool generates valid FormSchema from natural language prompt
- [ ] CreateFormTool supports iterative refinement of existing forms
- [ ] i18n works: labels/descriptions render in requested locale across all renderers
- [ ] YAML backward compatibility: existing YAML form files parse without changes
- [ ] No breaking changes to MS Teams form functionality (orchestrator, wizard, simple form, conversational)
- [ ] DependencyRule circular references detected at validation time

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Pydantic `BaseModel` for all data structures (`ConfigDict(extra="forbid")` on fields that should reject unknown keys)
- `LocalizedString = str | dict[str, str]` — simple string for single-language, dict for i18n. Renderers resolve via locale parameter.
- Async-first for all renderers, validators, storage, and tools
- Extractors are stateless: class with `extract()` method, no stored state
- Renderers implement `AbstractFormRenderer` ABC
- Storage implements `FormStorage` ABC
- Logging via `self.logger = logging.getLogger(__name__)`
- Use `yaml_rs` with PyYAML fallback (same pattern as existing code)

### Known Risks / Gotchas

- **Hard cutover risk**: All 9+ msteams files change simultaneously. Mitigation: comprehensive tests for each dialog preset before removing legacy module.
- **Adaptive Card backward compatibility**: Current `AdaptiveCardBuilder` has specific card structure expectations in the Teams wrapper. Mitigation: `AdaptiveCardRenderer` output must match existing card structure for equivalent inputs.
- **i18n complexity**: Adding `LocalizedString` to every label/description field increases schema verbosity. Mitigation: Plain `str` works as-is (no dict required), so existing usage patterns are unaffected.
- **LLM form generation quality**: LLM may produce invalid or suboptimal FormSchema JSON. Mitigation: Pydantic validation with retry (up to 2 retries with error feedback), plus structured output prompting.
- **Circular dependency detection**: Naive cycle detection in `DependencyRule` may miss transitive cycles. Mitigation: Build directed graph of field dependencies, run topological sort, reject on cycle.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.0` | Schema models, validation, JSON Schema export |
| `pyyaml` | `>=6.0` | YAML parsing fallback (yaml_rs preferred) |
| `asyncpg` | `>=0.29` | PostgreSQL persistence |
| `jinja2` | `>=3.1` | HTML5 form template rendering |

---

## 7. Open Questions

All resolved during brainstorm — no open questions remain.

---

## Worktree Strategy

- **Isolation unit**: mixed
- **Parallelism plan**:
  - **Sequential first**: Module 1 (Schema Core Models) must be completed before anything else — it's the foundation.
  - **Parallel batch 1** (after Module 1): Modules 2, 3, 5, 6, 7, 8, 9, 10, 11 can all be developed in parallel — they depend only on Module 1.
  - **Parallel batch 2** (after batch 1): Modules 4, 12, 13, 14 — depend on extractors and/or registry.
  - **Sequential last**: Module 15 (MS Teams rewrite) depends on Modules 1, 2, 7, 10. Module 16 (legacy removal) depends on Module 15.
- **Cross-feature dependencies**: None. `parrot/integrations/dialogs/` is not being modified by other in-flight features.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-02 | Jesus Lara | Initial draft from brainstorm |
