---
type: Wiki Overview
title: 'Feature Specification: FormDesigner Edit via Tool-Based Toolkit'
id: doc:sdd-specs-formdesigner-edition-parts-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `POST /api/v1/forms/{form_id}/edit` endpoint currently serializes the
relates_to:
- concept: mod:parrot.tools.abstract
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: FormDesigner Edit via Tool-Based Toolkit

**Feature ID**: FEAT-169
**Date**: 2026-05-14
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.4.0

---

## 1. Motivation & Business Requirements

### Problem Statement

The `POST /api/v1/forms/{form_id}/edit` endpoint currently serializes the
**entire** `FormSchema` as JSON and sends it to the LLM alongside the user's
edit prompt. For large forms (100+ fields), this produces prompts of 230K+
characters, causing:

- **~3 minute latency** (161s observed for `gemini-2.5-flash` on a real form)
- **Full-form regeneration risk** — the LLM must reproduce every field verbatim,
  creating opportunities for subtle data loss or reordering
- **Token waste** — the vast majority of the form is unchanged by a typical edit
- **Retry amplification** — on validation failure, the entire conversation
  (including the full form) is re-sent up to 2 more times

Observed in production logs:
```
prompt_chars=230466  system_prompt_chars=4497  tools=0
generate_content_ms=161748.9  model=gemini-2.5-flash
```

The root cause is `CreateFormTool._build_refinement_messages()` (line 354 of
`create_form.py`) which calls `existing.model_dump_json(indent=2)` and embeds
the complete JSON into the prompt. The LLM is instructed via `_REFINEMENT_PROMPT`
(line 98) to return a "COMPLETE, valid FormSchema JSON — not a partial diff."

### Goals

- **G1**: Reduce edit latency for large forms from ~160s to <15s for typical
  single-field edits
- **G2**: Reduce token usage by ~95% for edit operations (from 230K chars to
  ~5-10K chars across multiple tool-call rounds)
- **G3**: Eliminate full-form regeneration risk — only touched fields are modified
- **G4**: Maintain backward compatibility — same HTTP contract, same response format
- **G5**: Provide a fallback path so regressions are impossible

### Non-Goals (explicitly out of scope)

- Replacing the create-new-form flow (only the edit/refinement path changes)
- Supporting non-Google LLM clients for tool-calling (can be added later)
- Adding a diff/patch UI to the frontend
- Runtime fallback-on-failure was considered but rejected in favor of a size-based
  routing strategy (small forms keep full-form, large forms use toolkit) — see
  proposal `sdd/proposals/formdesigner-edition-parts.proposal.md`

---

## 2. Architectural Design

### Overview

Replace the "send full form, get full form back" pattern with a **tool-calling
loop** where the LLM uses a small, focused toolkit of inspection and mutation
tools. The LLM never sees the full form JSON — it inspects the form structure
via read-only tools and applies surgical edits via mutation tools that wrap
the existing `operations.py` apply functions.

The toolkit exposes 12 tools:

| Tool | Category | Purpose |
|------|----------|---------|
| `get_form_summary` | inspection | Compact outline: section IDs, field IDs, labels, types (~2-5% of full JSON) |
| `get_section` | inspection | Full JSON for one section by `section_id` |
| `get_field` | inspection | Full JSON for one field by `field_id` (searches across sections/subsections) |
| `search_fields` | inspection | Search fields by label, type, or ID pattern (regex/substring) |
| `update_field` | mutation | RFC 7396 merge-patch on a single field |
| `add_field` | mutation | Add a new field to a section at optional position |
| `remove_field` | mutation | Remove a field from a section |
| `add_section` | mutation | Add a new section at optional position |
| `update_section` | mutation | Update section title/description/meta |
| `move_field` | mutation | Move a field within or across sections |
| `update_form_meta` | mutation | Update form-level title/description/meta |
| `done` | control | Signal that all edits are complete |

### Component Diagram

```
User: "Change phone label to Mobile Number"
       │
       ▼
  edit_form() handler (handlers.py)
       │
       ▼
  CreateFormTool._execute()
       │
       ├── form size < threshold? ──→ _build_refinement_messages() (existing path)
       │
       └── form size ≥ threshold? ──→ _execute_toolkit_edit() (NEW)
              │
              ▼
         EditToolkit(form)
              │
              ▼
         GoogleGenAIClient.ask(
           prompt=user_edit_request,
           tools=toolkit_tools,        ← NEW: tool dicts from EditToolkit
           use_tools=True,
           stateless=True,
           max_iterations=15
         )
              │
              ▼
         Multi-turn tool-call loop:
           1. LLM calls get_form_summary()     → compact outline
           2. LLM calls get_field("phone")     → one field JSON
           3. LLM calls update_field(...)       → applies patch
           4. LLM calls done()                 → loop ends
              │
              ▼
         Return updated FormSchema
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `CreateFormTool` | modified | New `_execute_toolkit_edit()` method; `_execute()` routes to it for large forms |
| `GoogleGenAIClient.ask()` | uses (unchanged) | Pass `tools` + `use_tools=True` + `stateless=True` |
| `operations.py` apply functions | wraps | Mutation tools delegate to `_apply_update_field`, `_apply_add_field`, etc. |
| `FormSchema` / `FormSection` / `FormField` | reads/mutates | Toolkit holds a working copy; inspection tools read from it, mutation tools modify it |
| `FormAPIHandler.edit_form()` | unchanged | No changes needed — routes through `CreateFormTool.execute()` as before |
| `FormValidator` | uses | Post-edit validation before returning |

### Data Models

```python
# No new Pydantic models needed for the HTTP contract.
# Internal toolkit state:
class EditToolkit:
    """Manages a working copy of FormSchema during an edit session."""
    _form: FormSchema          # deep copy, mutated in place
    _tools: list[dict]         # tool definitions for GoogleGenAIClient
    _tool_handlers: dict[str, Callable]  # name → handler mapping
```

### New Public Interfaces

```python
# parrot_formdesigner/tools/edit_toolkit.py

class EditToolkit:
    """Toolkit exposing FormSchema inspection + mutation as LLM-callable tools."""

    def __init__(self, form: FormSchema) -> None:
        """Create toolkit with a deep copy of the form."""

    @property
    def form(self) -> FormSchema:
        """Current state of the working copy."""

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return tool dicts in the format expected by GoogleGenAIClient."""

    async def execute_tool(self, tool_name: str, arguments: dict) -> dict:
        """Execute a toolkit tool by name. Called by the tool-call loop."""

    # Inspection tools (return data to LLM):
    def get_form_summary(self) -> dict: ...
    def get_section(self, section_id: str) -> dict: ...
    def get_field(self, field_id: str) -> dict: ...
    def search_fields(self, query: str, field_type: str | None = None) -> list[dict]: ...

    # Mutation tools (modify working copy, return confirmation):
    def update_field(self, section_id: str, field_id: str, patch: dict) -> dict: ...
    def add_field(self, section_id: str, field: dict, position: int | None = None) -> dict: ...
    def remove_field(self, section_id: str, field_id: str) -> dict: ...
    def add_section(self, section: dict, position: int | None = None) -> dict: ...
    def update_section(self, section_id: str, patch: dict) -> dict: ...
    def move_field(self, from_section: str, field_id: str, to_section: str, position: int | None = None) -> dict: ...
    def update_form_meta(self, patch: dict) -> dict: ...
    def done(self) -> dict: ...
```

---

## 3. Module Breakdown

### Module 1: EditToolkit

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py`
- **Responsibility**: Implements the 12-tool toolkit that wraps FormSchema
  inspection and mutation operations. Manages a working copy of the form.
  Provides tool definitions in the format expected by `GoogleGenAIClient`.
- **Depends on**: `parrot_formdesigner.core.schema` (FormSchema, FormField,
  FormSection, FormSubsection), `parrot_formdesigner.api.operations` (apply functions)

### Module 2: CreateFormTool Toolkit Integration

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py`
- **Responsibility**: Add `_execute_toolkit_edit()` method to `CreateFormTool`.
  Route to toolkit path when `refine_form_id` is set and form exceeds a size
  threshold. Build the system prompt for toolkit mode. Handle the `done` signal
  and return the updated `FormSchema`.
- **Depends on**: Module 1 (EditToolkit)

### Module 3: Tests

- **Path**: `packages/parrot-formdesigner/tests/test_edit_toolkit.py`
- **Responsibility**: Unit tests for EditToolkit (inspection tools, mutation
  tools, error handling, edge cases). Integration test with a mock LLM client
  that simulates the tool-calling loop.
- **Depends on**: Module 1, Module 2

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_get_form_summary_returns_compact_outline` | Module 1 | Summary includes section/field IDs, labels, types but no full field details |
| `test_get_form_summary_includes_subsections` | Module 1 | Summary correctly represents FormSubsection structure |
| `test_get_section_by_id` | Module 1 | Returns full section JSON for valid section_id |
| `test_get_section_not_found` | Module 1 | Returns error for invalid section_id |
| `test_get_field_by_id` | Module 1 | Finds field across sections and subsections |
| `test_get_field_not_found` | Module 1 | Returns error for invalid field_id |
| `test_search_fields_by_label` | Module 1 | Substring match on field labels |
| `test_search_fields_by_type` | Module 1 | Filter by field_type |
| `test_search_fields_by_pattern` | Module 1 | Regex match on field_id |
| `test_update_field_merge_patch` | Module 1 | RFC 7396 merge-patch updates only specified keys |
| `test_update_field_preserves_unmentioned_keys` | Module 1 | Keys not in patch remain unchanged |
| `test_add_field_appends` | Module 1 | New field added at end of section |
| `test_add_field_at_position` | Module 1 | New field inserted at specified index |
| `test_remove_field_by_id` | Module 1 | Field removed from section |
| `test_add_section` | Module 1 | New section appended |
| `test_update_section_meta` | Module 1 | Section title/description updated |
| `test_move_field_across_sections` | Module 1 | Field moved from one section to another |
| `test_update_form_meta` | Module 1 | Form-level title/description updated |
| `test_done_returns_final_form` | Module 1 | Done tool returns success signal |
| `test_tool_definitions_format` | Module 1 | `get_tool_definitions()` returns valid dicts |
| `test_execute_tool_dispatches_correctly` | Module 1 | `execute_tool()` routes to correct handler |
| `test_working_copy_isolation` | Module 1 | Mutations don't affect the original FormSchema |
| `test_toolkit_routing_large_form` | Module 2 | Forms above threshold use toolkit path |
| `test_toolkit_routing_small_form` | Module 2 | Forms below threshold use existing full-form path |

### Integration Tests

| Test | Description |
|---|---|
| `test_toolkit_edit_with_mock_llm` | Simulates a multi-turn tool-call loop: LLM calls get_form_summary → get_field → update_field → done |
| `test_fallback_on_toolkit_failure` | If toolkit edit exhausts max_iterations without done, falls back to full-form path |

### Test Data / Fixtures

```python
@pytest.fixture
def large_form() -> FormSchema:
    """A FormSchema with 100+ fields across multiple sections."""
    ...

@pytest.fixture
def small_form() -> FormSchema:
    """A FormSchema with 5 fields (below toolkit threshold)."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `EditToolkit` class exists at `parrot_formdesigner/tools/edit_toolkit.py`
      with all 12 tools implemented
- [ ] `get_form_summary()` returns a compact outline that is ≤5% the size of
      `form.model_dump_json()` for a 100-field form
- [ ] Mutation tools delegate to `operations.py` apply functions where applicable
      (`add_field`, `remove_field`, `move_field`, `add_section`,
      `update_form_meta`, `update_section_meta`)
- [ ] `update_field()` implements RFC 7396 merge-patch semantics (keys present
      in patch override; keys absent are preserved; `null` removes)
- [ ] `CreateFormTool._execute()` routes to `_execute_toolkit_edit()` when
      `refine_form_id` is set and the form exceeds the size threshold
      (configurable, default: >10 fields or >20K chars serialized)
- [ ] `_execute_toolkit_edit()` calls `GoogleGenAIClient.ask()` with
      `tools=toolkit.get_tool_definitions()`, `use_tools=True`,
      `stateless=True`
- [ ] The HTTP contract is unchanged: `POST /api/v1/forms/{form_id}/edit`
      with `{"prompt": "..."}` returns `{"form_id", "title", "url"}`
- [ ] If the toolkit edit fails (max iterations exhausted without `done()`),
      the system falls back to the existing full-form refinement path
- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/test_edit_toolkit.py -v`
- [ ] No breaking changes to existing form creation or small-form editing
- [ ] Inspection tools use `section.iter_fields()` for field traversal (supports
      `FormSubsection`)

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# FormDesigner core schema
from parrot_formdesigner.core.schema import (
    FormSchema, FormSection, FormField, FormSubsection, SectionItem
)
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py

# Operations apply functions
from parrot_formdesigner.api.operations import (
    _apply_add_section,      # line 205
    _apply_add_field,        # line 214
    _apply_move_field,       # line 225
    _apply_remove_field,     # line 263
    _apply_update_field,     # line 271
    _apply_update_section_meta,  # line 286
    _apply_update_form_meta,     # line 302
    _apply_duplicate_field,      # line 315
    _DISPATCH,               # line 341
)
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py

# Operation models
from parrot_formdesigner.api.operations import (
    AddSection, AddField, MoveField, RemoveField, UpdateField,
    UpdateSectionMeta, UpdateFormMeta, DuplicateField,
)
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py (lines 52-134)

# Tool base
from parrot.tools.abstract import AbstractTool, ToolResult
# verified: packages/ai-parrot/src/parrot/tools/abstract.py:71, :24

# Validator
from parrot_formdesigner.services.validators import FormValidator
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py:66

# GoogleGenAIClient (for type hints and understanding the ask() interface)
# NOT imported by edit_toolkit.py — CreateFormTool already holds the client reference
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py

class CreateFormTool(AbstractTool):                              # line 197
    name: str = "create_form"                                    # line 213
    MAX_RETRIES = 2                                              # line 222

    def __init__(
        self,
        client: Any,
        registry: FormRegistry | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> None:                                                   # line 224

    async def _execute(
        self,
        prompt: str,
        form_id: str | None = None,
        persist: bool = False,
        refine_form_id: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:                                             # line 254

    def _build_refinement_messages(
        self,
        existing: FormSchema,
        prompt: str,
    ) -> list[dict[str, str]]:                                   # line 354

    async def _call_llm(
        self,
        messages: list[dict[str, str]],
    ) -> str:                                                    # line 374

    async def _generate_with_retry(
        self,
        messages: list[dict[str, str]],
        form_id: str | None,
    ) -> FormSchema | None:                                      # line 415
```

```python
# packages/ai-parrot/src/parrot/clients/google/client.py

class GoogleGenAIClient(AbstractClient):
    async def ask(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
        use_thinking: Optional[bool] = None,
        stateless: bool = False,
        deep_research: bool = False,
        file_search_store_names: Optional[List[str]] = None,
        lazy_loading: bool = False,
        max_iterations: int = 15,
        **kwargs
    ) -> AIMessage:                                              # line 1724

    # Tool registration flow (lines 1882-1895):
    # When tools=list[dict] is passed to ask():
    #   1. Each dict is registered via self.register_tool(tool)     # line 1884
    #   2. _build_tools("custom_functions") converts to types.Tool  # line 1895
    # This means toolkit tools need to be AbstractTool instances
    # OR registered as tool dicts that _build_tools can handle.

    async def _handle_stateless_function_calls(
        self,
        response,
        model: str,
        contents: List,
        config,
        all_tool_calls: List[ToolCall],
        original_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:                                                    # line 728
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py

class FormSchema(BaseModel):
    form_id: str                                                 # line 143
    version: str = "1.0"                                         # line 144
    title: LocalizedString                                       # line 145
    description: LocalizedString | None = None                   # line 146
    sections: list[FormSection] = Field(default_factory=list)    # line 147
    meta: dict[str, Any] | None = None                           # line 148

class FormSection(BaseModel):
    section_id: str                                              # line 115
    title: LocalizedString                                       # line 116
    description: LocalizedString | None = None                   # line 117
    fields: list[SectionItem] = Field(default_factory=list)      # line 123
    depends_on: DependsOn | None = None                          # line 124
    meta: dict[str, Any] | None = None                           # line 125

    def iter_fields(self) -> Iterator[FormField]:                # line 127
        """Yield every FormField, flattening through FormSubsection items."""

class FormField(BaseModel):
    field_id: str                                                # line 23
    field_type: FieldType                                        # line 24
    label: LocalizedString                                       # line 25
    # ... many more attributes

class FormSubsection(BaseModel):
    subsection_id: str                                           # line 72
    title: LocalizedString                                       # line 73
    fields: list[FormField] = Field(default_factory=list)        # line 76

SectionItem = Union[FormField, FormSubsection]                   # line 98
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py

# Operation Pydantic models (lines 52-134):
class AddSection(BaseModel):
    section: FormSection
    position: int | None = None

class AddField(BaseModel):
    section_id: str
    field: FormField
    position: int | None = None

class MoveField(BaseModel):
    from_: dict = Field(alias="from")  # {section_id, field_id}
    to: dict                           # {section_id, position?}

class RemoveField(BaseModel):
    section_id: str
    field_id: str

class UpdateField(BaseModel):
    section_id: str
    field_id: str
    patch: dict                        # RFC 7396 merge-patch

class UpdateSectionMeta(BaseModel):
    section_id: str
    patch: dict

class UpdateFormMeta(BaseModel):
    patch: dict

class DuplicateField(BaseModel):
    section_id: str
    field_id: str
    as_field_id: str

# Apply functions — all pure, operate on deep copy, raise OperationError:
def _apply_add_section(form: FormSchema, op: AddSection) -> FormSchema:    # line 205
def _apply_add_field(form: FormSchema, op: AddField) -> FormSchema:        # line 214
def _apply_move_field(form: FormSchema, op: MoveField) -> FormSchema:      # line 225
def _apply_remove_field(form: FormSchema, op: RemoveField) -> FormSchema:  # line 263
def _apply_update_field(form: FormSchema, op: UpdateField) -> FormSchema:  # line 271
def _apply_update_section_meta(form: FormSchema, op: UpdateSectionMeta) -> FormSchema:  # line 286
def _apply_update_form_meta(form: FormSchema, op: UpdateFormMeta) -> FormSchema:        # line 302
def _apply_duplicate_field(form: FormSchema, op: DuplicateField) -> FormSchema:         # line 315

_DISPATCH: dict[str, Any] = {                                   # line 341
    "add_section": _apply_add_section,
    "add_field": _apply_add_field,
    "move_field": _apply_move_field,
    "remove_field": _apply_remove_field,
    "update_field": _apply_update_field,
    "update_section_meta": _apply_update_section_meta,
    "update_form_meta": _apply_update_form_meta,
    "duplicate_field": _apply_duplicate_field,
}
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py

class FormAPIHandler:                                            # line 38
    def __init__(
        self,
        registry: FormRegistry,
        client: "AbstractClient | None" = None,
        submission_storage: "FormSubmissionStorage | None" = None,
        forwarder: "SubmissionForwarder | None" = None,
    ) -> None:                                                   # line 50

    def _get_llm_client(self) -> "AbstractClient | None":        # line 76

    async def edit_form(self, request: web.Request) -> web.Response:  # line 294
        # Calls: self._create_tool.execute(prompt=prompt, refine_form_id=form_id, persist=True)
        # No changes needed here — routing happens inside CreateFormTool._execute()
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `EditToolkit.__init__()` | `FormSchema.model_copy(deep=True)` | deep copy for working state | `schema.py` (Pydantic BaseModel) |
| `EditToolkit.update_field()` | `_apply_update_field()` | wraps apply function | `operations.py:271` |
| `EditToolkit.add_field()` | `_apply_add_field()` | wraps apply function | `operations.py:214` |
| `EditToolkit.remove_field()` | `_apply_remove_field()` | wraps apply function | `operations.py:263` |
| `EditToolkit.move_field()` | `_apply_move_field()` | wraps apply function | `operations.py:225` |
| `EditToolkit.add_section()` | `_apply_add_section()` | wraps apply function | `operations.py:205` |
| `EditToolkit.update_section()` | `_apply_update_section_meta()` | wraps apply function | `operations.py:286` |

…(truncated)…
