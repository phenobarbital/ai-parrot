---
type: feature
base_branch: dev
---

# Feature Specification: Deterministic CreateFormTool

**Feature ID**: FEAT-388
**Date**: 2026-07-30
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x (next minor)

---

## 1. Motivation & Business Requirements

### Problem Statement

`CreateFormTool` currently routes **all** form creation through an LLM call, even
when the caller provides fully structured data (JSON schemas, Pydantic-compatible
dicts, component definitions) that could be directly mapped to a `FormSchema`
without any generation or inference.

This is wasteful in three ways:
- **Cost**: every form creation consumes LLM tokens unnecessarily when the
  structure is already known.
- **Latency**: LLM round-trips add 2–10s even for simple, well-defined forms.
- **Determinism**: LLM output is inherently non-deterministic; callers providing
  exact schemas expect exact output, not "close enough" with retry loops.

The package already has `JsonSchemaExtractor`, `PydanticExtractor`,
`YAMLExtractor`, and `FormSchema.model_validate()` — but none of these are
accessible through the tool interface.

### Goals
- Allow `CreateFormTool` to accept structured JSON input and produce a
  `FormSchema` deterministically — zero LLM calls, zero retries, zero cost.
- Support two structured input formats: standard JSON Schema (draft-07) and
  FormSchema-native JSON with convenience shortcuts.
- Support both whole-form creation and component-level assembly.
- Expand `EditToolkit` with schema-aware creation methods for individual
  components.
- Provide a reusable `FormAssembler` class usable independently of the tool.
- Fail fast with clear Pydantic `ValidationError` on invalid structured input.

### Non-Goals (explicitly out of scope)
- Changing the existing LLM-based form creation path — it stays as-is.
- LLM fallback or augmentation for incomplete structured input — rejected in
  brainstorm. See `sdd/proposals/deterministic-creationformtool.brainstorm.md`
  Option A discussion.
- YAML string input via `CreateFormTool` — `YAMLExtractor` exists but is
  file/string based; adding YAML string support to the tool input is a separate
  concern.

---

## 2. Architectural Design

### Overview

Introduce a **`FormAssembler`** class that encapsulates all deterministic form
creation: format detection, shortcut expansion, extractor delegation, and
component assembly. `CreateFormTool._execute()` detects the presence of new
optional structured input fields and delegates to `FormAssembler`, keeping the
tool layer thin. `EditToolkit` gains schema-aware creation methods that delegate
to the same `FormAssembler` logic.

**Input priority rules in CreateFormTool:**
1. If `schema` dict is provided → `FormAssembler.assemble()` (no LLM).
2. If `sections` list is provided (no `schema`) → `FormAssembler.assemble_from_sections()`.
3. If `fields` list is provided (no `schema`/`sections`) → `FormAssembler.assemble_from_fields()`.
4. If only `prompt` is provided → existing LLM path (unchanged).
5. If both `prompt` AND structured input → `ValueError`.
6. If neither → `ValueError`.

The `prompt` field in `CreateFormInput` becomes **optional** (default `None`)
but is still required when no structured input is provided — validated at
runtime in `_execute()`.

### Component Diagram
```
CreateFormTool._execute()
    ├── structured input? ──→ FormAssembler ──→ FormSchema
    │                              ├── detect_format()
    │                              ├── JsonSchemaExtractor (JSON Schema path)
    │                              ├── expand_shortcuts() (native path)
    │                              └── FormSchema.model_validate()
    │
    └── prompt only? ──→ existing LLM path (unchanged)
                              ├── _build_creation_messages()
                              ├── _generate_with_retry()
                              └── _execute_toolkit_edit()

EditToolkit
    ├── add_field_from_schema(section_id, field_schema) ──→ FormAssembler.assemble_field()
    └── add_section_from_schema(section_schema, position) ──→ FormAssembler.assemble_section()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `CreateFormTool` | modifies | New optional input fields in `CreateFormInput`; branching in `_execute()` |
| `EditToolkit` | extends | New `add_field_from_schema`, `add_section_from_schema` methods |
| `JsonSchemaExtractor` | uses | Delegated to by `FormAssembler` for JSON Schema format |
| `FormSchema` | uses | `model_validate()` for native format path |
| `FormValidator` | uses | `check_schema()` for all paths (same as LLM path) |
| `FormRegistry` | uses | `persist` behavior unchanged |

### Data Models

```python
# Extended input schema — new optional fields
class CreateFormInput(BaseModel):
    prompt: str | None = Field(
        default=None,
        description="Natural language description of the form to create or modification to apply",
    )
    schema: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Complete form definition as a dict. Accepts either: "
            "(1) Standard JSON Schema (draft-07) — detected by 'type'+'properties' keys; "
            "(2) FormSchema-native JSON (with optional shortcuts like auto-generated IDs)."
        ),
    )
    sections: list[dict[str, Any]] | None = Field(
        default=None,
        description="List of section dicts to assemble into a form.",
    )
    fields: list[dict[str, Any]] | None = Field(
        default=None,
        description="Flat list of field dicts. Auto-wrapped in a single default section.",
    )
    form_id: str | None = Field(default=None)
    persist: bool = Field(default=False)
    refine_form_id: str | None = Field(default=None)
```

### New Public Interfaces

```python
class FormAssembler:
    """Deterministic form assembly from structured input.

    Handles format detection, shortcut expansion, extractor delegation,
    and component-level assembly. Usable independently of CreateFormTool.
    """

    def assemble(
        self,
        schema: dict[str, Any],
        *,
        form_id: str | None = None,
        title: str | None = None,
    ) -> FormSchema:
        """Assemble a complete FormSchema from a schema dict.

        Detects whether the input is JSON Schema (draft-07) or
        FormSchema-native JSON, then delegates accordingly.
        """
        ...

    def assemble_from_sections(
        self,
        sections: list[dict[str, Any]],
        *,
        form_id: str | None = None,
        title: str | None = None,
    ) -> FormSchema:
        """Assemble a FormSchema from a list of section dicts."""
        ...

    def assemble_from_fields(
        self,
        fields: list[dict[str, Any]],
        *,
        form_id: str | None = None,
        title: str | None = None,
        section_title: str | None = None,
    ) -> FormSchema:
        """Assemble a FormSchema from a flat list of field dicts.

        Fields are wrapped in a single default section.
        """
        ...

    def assemble_field(self, field_dict: dict[str, Any]) -> FormField:
        """Create a single FormField from a dict with shortcut expansion."""
        ...

    def assemble_section(self, section_dict: dict[str, Any]) -> FormSection:
        """Create a single FormSection from a dict with shortcut expansion."""
        ...

    def detect_format(self, schema: dict[str, Any]) -> str:
        """Detect input format: 'jsonschema' or 'native'."""
        ...

    def expand_shortcuts(self, data: dict[str, Any]) -> dict[str, Any]:
        """Expand convenience shortcuts in FormSchema-native JSON."""
        ...
```

---

## 3. Module Breakdown

### Module 1: FormAssembler
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/assembler.py`
- **Responsibility**: Format detection, shortcut expansion, extractor delegation,
  whole-form and component-level assembly. All deterministic form construction
  logic lives here.
- **Depends on**: `JsonSchemaExtractor`, `FormSchema`, `FormSection`, `FormField`,
  `FieldType` (all existing)

### Module 2: CreateFormTool Deterministic Input
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py`
- **Responsibility**: Extend `CreateFormInput` with optional `schema`, `sections`,
  `fields` parameters. Add deterministic branching in `_execute()` that delegates
  to `FormAssembler`. Make `prompt` optional.
- **Depends on**: Module 1 (FormAssembler)

### Module 3: EditToolkit Schema-Aware Methods
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py`
- **Responsibility**: Add `add_field_from_schema()` and `add_section_from_schema()`
  methods that accept raw schema dicts (with shortcuts), use `FormAssembler` to
  expand and validate them, then delegate to the existing `add_field()` /
  `add_section()` operations.
- **Depends on**: Module 1 (FormAssembler)

### Module 4: Tests
- **Path**: `packages/parrot-formdesigner/tests/unit/test_assembler.py`,
  `packages/parrot-formdesigner/tests/unit/test_create_form_deterministic.py`,
  `packages/parrot-formdesigner/tests/unit/test_edit_toolkit_schema.py`
- **Responsibility**: Unit tests for all new functionality.
- **Depends on**: Modules 1, 2, 3

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_assemble_from_jsonschema` | Module 1 | JSON Schema dict → FormSchema with correct field types |
| `test_assemble_from_native` | Module 1 | FormSchema-native JSON → FormSchema via model_validate |
| `test_assemble_from_native_with_shortcuts` | Module 1 | Auto-generated IDs, string field_types, flat fields |
| `test_detect_format_jsonschema` | Module 1 | Detects `{"type":"object","properties":...}` as JSON Schema |
| `test_detect_format_native` | Module 1 | Detects `{"sections":...}` or `{"fields":...}` as native |
| `test_expand_shortcuts_field_id_from_label` | Module 1 | label "First Name" → field_id "first_name" |
| `test_expand_shortcuts_section_id_auto` | Module 1 | Missing section_id → "section-1", "section-2" |
| `test_expand_shortcuts_string_field_type` | Module 1 | "text" string → FieldType.TEXT enum |
| `test_assemble_from_sections` | Module 1 | List of section dicts → FormSchema |
| `test_assemble_from_fields` | Module 1 | Flat field list → single-section FormSchema |
| `test_assemble_field` | Module 1 | Single field dict with shortcuts → FormField |
| `test_assemble_section` | Module 1 | Single section dict with shortcuts → FormSection |
| `test_assemble_invalid_schema_fails_fast` | Module 1 | Bad input raises ValidationError immediately |
| `test_assemble_unknown_field_type_fails` | Module 1 | Unknown type string raises ValidationError |
| `test_execute_with_schema` | Module 2 | CreateFormTool with schema input → deterministic result |
| `test_execute_with_sections` | Module 2 | CreateFormTool with sections input → deterministic result |
| `test_execute_with_fields` | Module 2 | CreateFormTool with fields input → deterministic result |
| `test_execute_prompt_unchanged` | Module 2 | Prompt-only input still uses LLM path |
| `test_execute_prompt_and_schema_error` | Module 2 | Both prompt+schema → ValueError |
| `test_execute_neither_prompt_nor_schema` | Module 2 | No input → ValueError |
| `test_execute_schema_with_persist` | Module 2 | Deterministic form with persist=True → registered |
| `test_add_field_from_schema` | Module 3 | EditToolkit adds field from raw dict with shortcuts |
| `test_add_section_from_schema` | Module 3 | EditToolkit adds section from raw dict with shortcuts |
| `test_add_field_from_schema_invalid` | Module 3 | Invalid field dict returns error dict |

### Integration Tests
| Test | Description |
|---|---|
| `test_roundtrip_jsonschema_assemble` | JSON Schema → FormAssembler → FormSchema → JsonSchemaRenderer → compare |
| `test_deterministic_vs_native_equivalence` | Same form built via native shortcuts and explicit FormSchema produce identical output |

### Test Data / Fixtures
```python
@pytest.fixture
def sample_jsonschema():
    return {
        "type": "object",
        "title": "Customer Feedback",
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "email": {"type": "string", "format": "email"},
            "rating": {"type": "integer", "minimum": 1, "maximum": 5},
            "comments": {"type": "string", "maxLength": 500},
        },
        "required": ["name", "email", "rating"],
    }

@pytest.fixture
def sample_native_with_shortcuts():
    return {
        "title": "Customer Feedback",
        "sections": [
            {
                "title": "Contact Info",
                "fields": [
                    {"label": "Full Name", "field_type": "text", "required": True},
                    {"label": "Email", "field_type": "email", "required": True},
                ],
            },
            {
                "title": "Feedback",
                "fields": [
                    {"label": "Rating", "field_type": "nps"},
                    {"label": "Comments", "field_type": "text_area"},
                ],
            },
        ],
    }

@pytest.fixture
def sample_flat_fields():
    return [
        {"label": "Name", "field_type": "text", "required": True},
        {"label": "Age", "field_type": "integer"},
        {"label": "Agree to Terms", "field_type": "boolean"},
    ]
```

---

## 5. Acceptance Criteria

- [ ] `CreateFormTool` accepts a `schema` dict and returns a valid `FormSchema` without any LLM call
- [ ] `CreateFormTool` accepts a `sections` list and assembles a valid `FormSchema` without LLM
- [ ] `CreateFormTool` accepts a `fields` list and assembles a valid single-section `FormSchema` without LLM
- [ ] Existing `prompt`-only path continues to work identically (backward compatible)
- [ ] Providing both `prompt` and `schema`/`sections`/`fields` raises `ValueError`
- [ ] Providing neither `prompt` nor structured input raises `ValueError`
- [ ] JSON Schema (draft-07) input is auto-detected and routed through `JsonSchemaExtractor`
- [ ] FormSchema-native JSON with shortcuts is auto-detected and expanded correctly
- [ ] Shortcut expansion: `field_id` auto-generated from `label` when omitted
- [ ] Shortcut expansion: `section_id` auto-generated sequentially when omitted
- [ ] Shortcut expansion: string `field_type` values accepted (e.g., `"text"` → `FieldType.TEXT`)
- [ ] Shortcut expansion: `form_id` auto-generated from `title` when omitted
- [ ] Invalid structured input raises `ValidationError` immediately (no LLM fallback)
- [ ] `persist=True` works identically for deterministic path as for LLM path
- [ ] `FormValidator.check_schema()` runs on deterministic output (circular dependency detection)
- [ ] `EditToolkit.add_field_from_schema()` creates a field from a raw dict with shortcuts
- [ ] `EditToolkit.add_section_from_schema()` creates a section from a raw dict with shortcuts
- [ ] `FormAssembler` is usable independently of `CreateFormTool` (no LLM client required)
- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/ -v`
- [ ] No breaking changes to existing `CreateFormTool` public API

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
# These imports have been confirmed to work:
from parrot_formdesigner.extractors import JsonSchemaExtractor   # extractors/__init__.py:7
from parrot_formdesigner.extractors import PydanticExtractor      # extractors/__init__.py:8
from parrot_formdesigner.extractors import YamlExtractor          # extractors/__init__.py:10
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField  # core/schema.py
from parrot_formdesigner.core.types import FieldType              # core/types.py
from parrot_formdesigner.tools.edit_toolkit import EditToolkit    # tools/edit_toolkit.py
from parrot_formdesigner.services.validators import FormValidator  # services/validators.py
from parrot_formdesigner.services.registry import FormRegistry    # tools/create_form.py:33
from parrot.tools.abstract import AbstractTool, ToolResult        # tools/create_form.py:28
from parrot_formdesigner.core.constraints import FieldConstraints, DependencyRule, PostDependency  # core/constraints.py
from parrot_formdesigner.core.options import FieldOption, OptionsSource  # core/options.py
```

### Existing Class Signatures
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py
class CreateFormInput(BaseModel):  # line 223
    prompt: str = Field(...)                           # line 233
    form_id: str | None = Field(default=None)          # line 238
    persist: bool = Field(default=False)                # line 242
    refine_form_id: str | None = Field(default=None)   # line 245

class CreateFormTool(AbstractTool):  # line 259
    name: str = "create_form"
    args_schema = CreateFormInput
    MAX_RETRIES = 2
    def __init__(self, client: Any, registry: FormRegistry | None = None,
                 model: str | None = None, *, tenant: str | None = None,
                 **kwargs: Any) -> None:  # line 296
    async def _execute(self, prompt: str, form_id: str | None = None,
                       persist: bool = False, refine_form_id: str | None = None,
                       **kwargs: Any) -> ToolResult:  # line 318

# packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py
class JsonSchemaExtractor:  # line 64
    def extract(self, schema: dict[str, Any], *, form_id: str | None = None,
                title: str | None = None) -> FormSchema:  # line 83

# packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py
class EditToolkit(AbstractToolkit):  # line 50
    exclude_tools: tuple[str, ...] = ("execute_tool",)  # line 72
    def __init__(self, form: FormSchema, **kwargs: Any) -> None:  # line 74
    @property
    def form(self) -> FormSchema:  # line 91
    @property
    def is_done(self) -> bool:  # line 96
    async def add_field(self, section_id: str, field: dict,
                        position: int | None = None) -> dict:  # line 321
    async def add_section(self, section: dict,
                          position: int | None = None) -> dict:  # line 596

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormField(BaseModel):  # line 43
    field_id: str
    field_type: FieldType
    label: LocalizedString
    required: bool = False

class FormSection(BaseModel):  # line 127
    section_id: str
    title: LocalizedString | None
    fields: list[SectionItem]  # SectionItem = Union[FormField, FormSubsection]

class FormSchema(BaseModel):  # line 267
    form_id: str
    title: LocalizedString
    sections: list[FormSection]
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FormAssembler.assemble()` | `JsonSchemaExtractor.extract()` | method call (JSON Schema path) | `extractors/jsonschema.py:83` |
| `FormAssembler.assemble()` | `FormSchema.model_validate()` | class method call (native path) | `core/schema.py:267` (Pydantic BaseModel) |
| `FormAssembler.assemble_field()` | `FormField.model_validate()` | class method call | `core/schema.py:43` |
| `FormAssembler.assemble_section()` | `FormSection.model_validate()` | class method call | `core/schema.py:127` |
| `CreateFormTool._execute()` | `FormAssembler.assemble*()` | method call (new branch) | N/A (new code) |
| `CreateFormTool._execute()` | `FormValidator.check_schema()` | method call (existing) | `services/validators.py` |
| `EditToolkit.add_field_from_schema()` | `FormAssembler.assemble_field()` | method call | N/A (new code) |
| `EditToolkit.add_section_from_schema()` | `FormAssembler.assemble_section()` | method call | N/A (new code) |

### Does NOT Exist (Anti-Hallucination)
- ~~`FormDesigner` class~~ — "FormDesigner" is the package name only, not a Python class
- ~~`FormAssembler`~~ — does not exist yet; this spec creates it
- ~~`CreateFormInput.schema`~~ — does not exist yet; only `prompt`, `form_id`, `persist`, `refine_form_id`
- ~~`EditToolkit.add_field_from_schema()`~~ — does not exist yet
- ~~`EditToolkit.add_section_from_schema()`~~ — does not exist yet
- ~~`FormSchema.from_json_schema()`~~ — no such class method; use `JsonSchemaExtractor.extract()`
- ~~`AbstractExtractor` base class~~ — extractors do not share a common base class
- ~~`CreateFormTool.assemble()`~~ — no such method; deterministic logic lives in `FormAssembler`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Use `FormSchema.model_validate()` / `FormField.model_validate()` / `FormSection.model_validate()` for
  Pydantic validation — do not construct models by hand from individual fields.
- Follow the existing `_slugify()` function in `create_form.py` for ID generation from labels.
- Follow the existing `EditToolkit.add_field()` pattern (line 321) for the new
  `add_field_from_schema()` — validate via `FormField.model_validate()`, then delegate
  to `_apply_add_field`.
- `FormAssembler` should be a plain class with no async methods (all operations are
  synchronous Pydantic validation and dict manipulation).
- Use `FieldType` enum values directly for type validation — Pydantic handles
  string-to-enum coercion automatically.

### Shortcut Expansion Rules
The `expand_shortcuts()` method must handle:

| Shortcut | Expansion | Example |
|---|---|---|
| Missing `field_id` | Slugify `label` → snake_case | `"First Name"` → `"first_name"` |
| Missing `section_id` | Sequential `"section-1"`, `"section-2"` | — |
| Missing `form_id` | Slugify `title` (same as `_slugify()` in create_form.py) | `"Customer Feedback"` → `"customer-feedback"` |
| String `field_type` | Passed to Pydantic as-is (FieldType enum validates strings) | `"text"` → `FieldType.TEXT` |
| Top-level `fields` list (no `sections`) | Wrap in `[{"section_id": "main", "fields": [...]}]` | — |

### Format Detection Rules
`detect_format()` must distinguish between two dict formats:

| Criterion | Detected as |
|---|---|
| Has `"type": "object"` AND `"properties"` key | `"jsonschema"` |
| Has `"sections"` or `"fields"` key | `"native"` |
| Neither | Attempt `"native"` (let Pydantic validate and fail fast) |

### Known Risks / Gotchas
- **`prompt` becoming optional**: The existing `prompt: str = Field(...)` must change to
  `prompt: str | None = Field(default=None)`. This is a Pydantic schema change that
  could affect LLM tool-calling if the LLM sees the updated tool description. Mitigated
  by keeping the description clear about when prompt is needed.
- **Pydantic field name `schema`**: `schema` is a reserved name in Pydantic v1 but
  NOT in v2. Since the project uses Pydantic v2, this is safe. However, if it causes
  issues, use `form_schema` as the field name with `alias="schema"`.
- **Circular dependencies in deterministic input**: Users providing structured JSON
  could create circular `depends_on` references. `FormValidator.check_schema()` catches
  this (same as LLM path), but the error is reported in metadata, not raised — matching
  existing behavior.
- **ID collision in shortcuts**: Auto-generated `field_id` from `label` could collide
  if two fields have the same label. `FormAssembler` should append a numeric suffix
  (`"name"`, `"name_2"`) when a collision is detected.
- **LocalizedString support**: `FormSchema` already accepts both `str` and `dict[str, str]`
  for `LocalizedString` fields (title, label, etc.). The shortcut format should pass
  through whatever the caller provides — Pydantic handles the union validation.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.0` | Already used — model_validate, BaseModel, Field |

No new external dependencies required.

---

## 8. Open Questions

- [ ] Should `FormAssembler` live at `parrot_formdesigner/assembler.py` (top-level module) or inside `parrot_formdesigner/tools/assembler.py` (alongside the tools)? — *Owner: Jesus*
- [ ] Should the `parrot/forms/` re-export shim (in `ai-parrot` core) also expose `FormAssembler`, or keep it exclusive to `parrot-formdesigner`? — *Owner: Jesus*
- [ ] Should the Pydantic field name be `schema` (works in v2) or `form_schema` with alias to avoid any future naming issues? — *Owner: Jesus*

---

## Worktree Strategy

- **Default isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Tasks have a clear dependency chain (Module 1 → Module 2 + Module 3 → Module 4).
  The feature touches a small number of files in a single package (`parrot-formdesigner`).
  Sequential execution avoids coordination overhead with no significant time penalty.
- **Cross-feature dependencies**: None — the modified files (`create_form.py`,
  `edit_toolkit.py`) are not under active development in other features.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-30 | Jesus Lara | Initial draft from brainstorm |
