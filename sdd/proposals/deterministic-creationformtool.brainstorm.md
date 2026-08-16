---
type: feature
base_branch: dev
---

# Brainstorm: Deterministic CreateFormTool

**Date**: 2026-07-30
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

`CreateFormTool` currently routes **all** form creation through an LLM call, even when
the caller provides fully structured data (JSON schemas, Pydantic-compatible dicts,
component definitions) that could be directly mapped to a `FormSchema` without any
generation or inference.

This is wasteful because:
- **Cost**: every form creation consumes LLM tokens unnecessarily when the structure is known.
- **Latency**: LLM round-trips add 2-10s even for simple, well-defined forms.
- **Determinism**: LLM output is inherently non-deterministic; callers providing exact
  schemas expect exact output, not "close enough" with retry loops.
- **Existing infrastructure unused**: the package already has `JsonSchemaExtractor`,
  `PydanticExtractor`, `YAMLExtractor`, and `FormSchema.model_validate()` — but none
  of these are accessible through the tool interface.

**Who is affected**: developers and agents building forms programmatically when the
form structure is already known (e.g., from a database schema, an API spec, or a
hand-crafted JSON definition).

## Constraints & Requirements

- Must not break existing natural-language form creation (backward compatible).
- `prompt` field must remain the primary input for LLM-driven creation.
- New structured input fields must be optional — no breaking changes to `CreateFormInput`.
- Fail fast with clear validation errors when structured input is invalid (no LLM fallback for bad schemas).
- Honor existing `persist`, `form_id`, and registry behavior identically.
- Support two structured input formats: standard JSON Schema (draft-07) and FormSchema-native JSON with shortcuts.
- Support both whole-form creation and component-level assembly via EditToolkit expansion.

---

## Options Explored

### Option A: Inline Branching in CreateFormTool

Extend `CreateFormInput` with optional `schema`, `sections`, and `fields` parameters.
Add branching logic directly in `_execute()`: if structured input is present, bypass the
LLM and use extractors / `FormSchema.model_validate()`. If only `prompt` is given,
use the existing LLM path.

✅ **Pros:**
- Minimal new code — extends existing class directly.
- Single tool interface for all form creation.
- No new abstractions to learn.

❌ **Cons:**
- `_execute()` becomes significantly more complex (already ~100 lines with refinement logic).
- Shortcut expansion logic (auto-IDs, flat-field wrapping) mixed into tool code.
- No reusable component for programmatic callers who don't want the tool wrapper.
- Hard to test format detection, shortcut expansion, and assembly independently.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | Input validation + FormSchema.model_validate | Already used |

🔗 **Existing Code to Reuse:**
- `parrot_formdesigner/extractors/jsonschema.py` — JsonSchemaExtractor.extract()
- `parrot_formdesigner/core/schema.py` — FormSchema.model_validate()

---

### Option B: FormAssembler + CreateFormTool Integration

Create a new `FormAssembler` class that handles all deterministic form creation:
format detection, shortcut expansion, extractor delegation, and component assembly.
`CreateFormTool._execute()` detects structured input and delegates to `FormAssembler`,
keeping the tool layer thin. `EditToolkit` gains schema-aware creation methods
(`add_field_from_schema`, `add_section_from_schema`) that delegate to `FormAssembler`
for individual components.

✅ **Pros:**
- Clean separation: `FormAssembler` is testable and reusable independently of the tool.
- `CreateFormTool._execute()` stays clean — one `if` branch delegates to the assembler.
- `EditToolkit` component methods naturally delegate to the same assembler logic.
- Format detection, shortcut expansion, and validation are all encapsulated in one place.
- Easy to add new input formats later (just add an extractor path in `FormAssembler`).

❌ **Cons:**
- Introduces a new class (`FormAssembler`) — small additional abstraction.
- Slightly more code than Option A for the initial implementation.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | Input validation, model_validate, model_dump | Already used |

🔗 **Existing Code to Reuse:**
- `parrot_formdesigner/extractors/jsonschema.py` — JsonSchemaExtractor for JSON Schema path
- `parrot_formdesigner/extractors/yaml.py` — YamlExtractor (potential future format)
- `parrot_formdesigner/core/schema.py` — FormSchema, FormSection, FormField model_validate
- `parrot_formdesigner/tools/edit_toolkit.py` — EditToolkit for component-level expansion
- `parrot_formdesigner/services/validators.py` — FormValidator.check_schema()

---

### Option C: Strategy Pattern with Pluggable CreationStrategy

Introduce a `CreationStrategy` abstraction with concrete implementations:
`LLMCreationStrategy`, `SchemaCreationStrategy`, `ComponentCreationStrategy`.
`CreateFormTool` selects the strategy based on input and delegates entirely.

✅ **Pros:**
- Maximum extensibility — new strategies added without touching existing code.
- Each strategy is a self-contained, independently testable unit.
- Clean OOP design.

❌ **Cons:**
- Over-engineered for the actual need (two paths: LLM vs. deterministic).
- Adds 3+ new classes plus a registry/selection mechanism.
- The LLM path is already deeply integrated into CreateFormTool (system prompts, retry logic,
  toolkit edit path) — extracting it into a strategy means moving ~200 lines of tightly
  coupled code.
- Violates the project principle of not introducing abstractions beyond what the task requires.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | Input validation | Already used |

🔗 **Existing Code to Reuse:**
- Same as Option B, but reorganized into strategy classes.

---

## Recommendation

**Option B** is recommended because:

- It provides the right level of abstraction: a single `FormAssembler` class that
  encapsulates format detection, shortcut expansion, and assembly — without the
  over-engineering of a full strategy pattern.
- `CreateFormTool` stays focused: one branch for structured input (delegate to assembler),
  one branch for natural language (existing LLM path).
- `FormAssembler` is independently useful: programmatic callers (tests, scripts, other
  tools) can use it directly without instantiating an LLM client.
- The EditToolkit component methods (`add_field_from_schema`, `add_section_from_schema`)
  naturally delegate to the same assembler logic, avoiding code duplication.
- The tradeoff (one new class) is minimal compared to the clarity and testability gained.

---

## Feature Description

### User-Facing Behavior

Callers of `CreateFormTool` gain three new optional input fields:

1. **`schema`** (`dict | None`): A complete form definition as either:
   - Standard JSON Schema (draft-07) — detected by presence of `"type": "object"` and `"properties"`.
   - FormSchema-native JSON — detected by presence of `"sections"` or `"fields"` keys.
   - FormSchema-native JSON with shortcuts (auto-generated IDs, string field_types,
     flat field lists auto-wrapped in a default section).

2. **`sections`** (`list[dict] | None`): A list of section definitions to assemble
   into a form. Each section dict follows FormSection structure (with shortcuts).

3. **`fields`** (`list[dict] | None`): A flat list of field definitions. Auto-wrapped
   in a single default section.

**Input priority rules:**
- If `schema` is provided → deterministic whole-form creation (no LLM).
- If `sections` is provided (no `schema`) → deterministic assembly from sections.
- If `fields` is provided (no `schema` or `sections`) → deterministic assembly from flat fields.
- If only `prompt` is provided → existing LLM path (unchanged).
- If `schema`/`sections`/`fields` AND `prompt` → error ("provide structured data OR a prompt, not both").
- `prompt` becomes optional (but required when no structured input given).

**Shortcuts supported in FormSchema-native JSON:**
- `field_type` accepts string values (e.g., `"text"` instead of `FieldType.TEXT`).
- `field_id` auto-generated from `label` via slugification when omitted.
- `section_id` auto-generated as `"section-1"`, `"section-2"`, etc. when omitted.
- `form_id` auto-generated from `title` when omitted (same as current LLM path).
- Flat `fields` list at form level auto-wrapped in a single section.

**EditToolkit gains:**
- `add_field_from_schema(section_id, field_schema)` — create a FormField from a JSON
  schema property dict or FormSchema-native field dict, then add it.
- `add_section_from_schema(section_schema, position)` — create a FormSection from a
  section dict (with shortcuts), then add it.

### Internal Behavior

```
CreateFormTool._execute()
    ├── if schema/sections/fields provided:
    │   ├── validate: no prompt+schema conflict
    │   ├── FormAssembler.assemble(input) → FormSchema
    │   ├── FormValidator.check_schema(form) → circular dep errors
    │   ├── optionally persist to registry
    │   └── return ToolResult with form
    └── if only prompt provided:
        └── existing LLM path (unchanged)

FormAssembler.assemble(input)
    ├── detect_format(input) → "jsonschema" | "native" | "sections" | "fields"
    ├── if jsonschema: JsonSchemaExtractor.extract(schema)
    ├── if native: expand_shortcuts(schema) → FormSchema.model_validate()
    ├── if sections: expand_sections(sections) → FormSchema(sections=...)
    ├── if fields: wrap_in_section(fields) → FormSchema(sections=[default])
    └── validate result via FormSchema Pydantic validation (fail fast)

FormAssembler.assemble_field(field_dict) → FormField
    ├── expand_shortcuts(field_dict)
    └── FormField.model_validate(expanded)

FormAssembler.assemble_section(section_dict) → FormSection
    ├── expand_shortcuts for section + its fields
    └── FormSection.model_validate(expanded)
```

### Edge Cases & Error Handling

- **Invalid schema**: Pydantic `ValidationError` raised immediately — no retry, no LLM fallback.
  The error message includes the exact validation failure path.
- **Unknown field_type string**: `ValidationError` listing the invalid type and accepted values.
- **Missing required fields** (e.g., no `label` on a field without `field_id`): `ValidationError`.
- **Both prompt and schema provided**: Explicit `ValueError("Provide either 'prompt' for LLM
  generation or structured input (schema/sections/fields), not both")`.
- **Neither prompt nor structured input**: `ValueError("Either 'prompt' or structured input
  (schema/sections/fields) is required")`.
- **Circular dependencies in structured input**: Detected by `FormValidator.check_schema()`,
  reported in `metadata["circular_dependency_errors"]` (same as LLM path).
- **JSON Schema with $ref**: Resolved by `JsonSchemaExtractor._resolve_ref()` (existing logic).
- **Empty sections/fields lists**: `ValidationError` from FormSchema (sections must be non-empty).

---

## Capabilities

### New Capabilities
- `deterministic-form-creation`: Accept structured JSON input in CreateFormTool to build
  FormSchema without LLM calls.
- `form-assembler`: Standalone FormAssembler class for programmatic form construction
  with format detection and shortcut expansion.
- `schema-aware-edit-toolkit`: EditToolkit methods for adding fields/sections from schema dicts.

### Modified Capabilities
- `create-form-tool`: Extended input schema (new optional fields), backward compatible.
- `edit-toolkit`: New schema-aware creation methods alongside existing mutation tools.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot_formdesigner/tools/create_form.py` | modifies | New optional inputs in CreateFormInput, branching in _execute |
| `parrot_formdesigner/tools/edit_toolkit.py` | extends | New add_field_from_schema, add_section_from_schema methods |
| `parrot_formdesigner/assembler.py` (NEW) | new | FormAssembler class |
| `parrot_formdesigner/extractors/jsonschema.py` | depends on | Used by FormAssembler for JSON Schema path |
| `parrot_formdesigner/core/schema.py` | depends on | FormSchema.model_validate for native path |
| `parrot_formdesigner/services/validators.py` | depends on | FormValidator.check_schema for all paths |

No breaking changes. No new external dependencies. No deployment changes.

---

## Code Context

### User-Provided Code
No code snippets provided by the user.

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py:224
class CreateFormInput(BaseModel):
    prompt: str = Field(...)                      # line 233
    form_id: str | None = Field(default=None)     # line 238
    persist: bool = Field(default=False)           # line 242
    refine_form_id: str | None = Field(default=None)  # line 245

# From packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py:259
class CreateFormTool(AbstractTool):
    name: str = "create_form"
    args_schema = CreateFormInput
    MAX_RETRIES = 2
    def __init__(self, client: Any, registry: FormRegistry | None = None,
                 model: str | None = None, *, tenant: str | None = None, **kwargs: Any) -> None:
    async def _execute(self, prompt: str, form_id: str | None = None,
                       persist: bool = False, refine_form_id: str | None = None, **kwargs: Any) -> ToolResult:

# From packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py:64
class JsonSchemaExtractor:
    def extract(self, schema: dict[str, Any], *, form_id: str | None = None,
                title: str | None = None) -> FormSchema:  # line 83

# From packages/parrot-formdesigner/src/parrot_formdesigner/extractors/yaml.py
class YamlExtractor:
    def extract(self, content: str) -> FormSchema:
    def extract_from_string(self, content: str) -> FormSchema:
    def extract_from_file(self, path: str | Path) -> FormSchema:

# From packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py:50
class EditToolkit(AbstractToolkit):
    exclude_tools: tuple[str, ...] = ("execute_tool",)
    def __init__(self, form: FormSchema, **kwargs: Any) -> None:  # line 74
    @property
    def form(self) -> FormSchema:  # line 91
    @property
    def is_done(self) -> bool:  # line 96

# From packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:267
class FormSchema(BaseModel):
    form_id: str
    title: LocalizedString
    sections: list[FormSection]
    # ... (full model with model_validate support)

# From packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:127
class FormSection(BaseModel):
    section_id: str
    title: LocalizedString | None
    fields: list[SectionItem]  # SectionItem = Union[FormField, FormSubsection]

# From packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:43
class FormField(BaseModel):
    field_id: str
    field_type: FieldType
    label: LocalizedString
    required: bool = False
    # ... (full model)
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot_formdesigner.extractors import JsonSchemaExtractor  # extractors/__init__.py:7
from parrot_formdesigner.extractors import PydanticExtractor     # extractors/__init__.py:8
from parrot_formdesigner.extractors import YamlExtractor         # extractors/__init__.py:10
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField  # core/schema.py
from parrot_formdesigner.core.types import FieldType             # core/types.py
from parrot_formdesigner.tools.edit_toolkit import EditToolkit   # tools/edit_toolkit.py
from parrot_formdesigner.services.validators import FormValidator  # services/validators.py
from parrot.tools.abstract import AbstractTool, ToolResult       # tools/create_form.py:28
```

#### Key Attributes & Constants
- `JsonSchemaExtractor._TYPE_MAP` → `dict[str, FieldType]` (extractors/jsonschema.py:25) — 6 entries
- `JsonSchemaExtractor._FORMAT_MAP` → `dict[str, FieldType]` (extractors/jsonschema.py:35) — 18 entries
- `EditToolkit.exclude_tools` → `tuple[str, ...]` (tools/edit_toolkit.py:72)

### Does NOT Exist (Anti-Hallucination)
- ~~`FormDesigner` class~~ — "FormDesigner" is only the package name (`parrot-formdesigner`), not a Python class
- ~~`FormAssembler`~~ — does not exist yet; this brainstorm proposes creating it
- ~~`CreateFormInput.schema`~~ — the input schema does not have a `schema` field; `prompt` is the only content input
- ~~`EditToolkit.add_field_from_schema()`~~ — does not exist; toolkit only has `add_field(section_id, field, position)`
- ~~`FormSchema.from_json_schema()`~~ — no such class method; use `JsonSchemaExtractor.extract()` instead
- ~~`AbstractExtractor` base class~~ — extractors do not share a common base class

---

## Parallelism Assessment

- **Internal parallelism**: Yes — three independent workstreams:
  1. `FormAssembler` class (format detection, shortcut expansion, assembly logic)
  2. `CreateFormTool` input schema + `_execute` branching
  3. `EditToolkit` schema-aware methods
  However, (2) and (3) both depend on (1), so true parallelism is limited.
- **Cross-feature independence**: No conflicts with in-flight specs. The files modified
  (`create_form.py`, `edit_toolkit.py`) are not under active development in other features.
- **Recommended isolation**: `per-spec` (all tasks sequential in one worktree)
- **Rationale**: Tasks have a clear dependency chain (assembler first, then tool + toolkit
  integration). The feature touches a small number of files in a single package, and
  component assembly depends on the assembler being complete. Sequential execution in
  one worktree avoids coordination overhead.

---

## Open Questions

- [ ] Should `FormAssembler` live at `parrot_formdesigner/assembler.py` (top-level module) or inside `parrot_formdesigner/tools/assembler.py` (alongside the tools)? — *Owner: Jesus*
- [ ] Should the shortcut format support i18n labels (`{"en": "Name", "es": "Nombre"}`) or only plain strings for the deterministic path? — *Owner: Jesus*
- [ ] Should the `parrot/forms/` re-export shim (in `ai-parrot` core) also expose `FormAssembler`, or keep it exclusive to `parrot-formdesigner`? — *Owner: Jesus*
