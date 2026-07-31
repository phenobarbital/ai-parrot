---
type: Wiki Overview
title: 'TASK-1132: Integrate EditToolkit into CreateFormTool'
id: doc:sdd-tasks-completed-task-1132-createformtool-toolkit-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: TASK-1131 creates the `EditToolkit` class with 12 tools. This task wires
  it
relates_to:
- concept: mod:parrot.tools.abstract
  rel: mentions
---

# TASK-1132: Integrate EditToolkit into CreateFormTool

**Feature**: FEAT-169 — FormDesigner Edit via Tool-Based Toolkit
**Spec**: `sdd/specs/formdesigner-edition-parts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1131
**Assigned-to**: unassigned

---

## Context

TASK-1131 creates the `EditToolkit` class with 12 tools. This task wires it
into `CreateFormTool` so that large-form edit requests are routed through the
toolkit-based tool-calling loop instead of the full-form regeneration path.

Implements Spec §3 Module 2 (CreateFormTool Toolkit Integration).

---

## Scope

- Add a new method `_execute_toolkit_edit()` to `CreateFormTool` that:
  1. Creates an `EditToolkit` instance with the existing `FormSchema`
  2. Builds a toolkit-specific system prompt instructing the LLM to use inspection
     tools first, then mutation tools, then call `done()`
  3. Calls `self._client.ask()` with `tools=toolkit.get_tool_definitions()`,
     `use_tools=True`, `stateless=True`
  4. After the LLM calls `done()`, returns the updated `FormSchema`
- Modify `CreateFormTool._execute()` to route to `_execute_toolkit_edit()` when:
  - `refine_form_id` is set (edit mode)
  - The form exceeds the size threshold (>10 fields OR >20K chars serialized)
- Implement fallback: if `_execute_toolkit_edit()` fails (max iterations exhausted
  without `done()`, exception), fall back to the existing `_build_refinement_messages()`
  path
- Add a `_TOOLKIT_SYSTEM_PROMPT` constant with instructions for the LLM

**NOT in scope**:
- The EditToolkit class itself (TASK-1131)
- Tests (TASK-1133)
- Changes to `FormAPIHandler.edit_form()` (no changes needed)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py` | MODIFY | Add `_execute_toolkit_edit()`, modify `_execute()` routing, add `_TOOLKIT_SYSTEM_PROMPT` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already imported in create_form.py:
from parrot_formdesigner.core.schema import FormSchema
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py (top imports)

# New import to add:
from parrot_formdesigner.tools.edit_toolkit import EditToolkit
# verified: will exist after TASK-1131

from parrot.tools.abstract import AbstractTool, ToolResult
# verified: packages/ai-parrot/src/parrot/tools/abstract.py:71, :36
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py

class CreateFormTool(AbstractTool):                              # line 197
    name: str = "create_form"                                    # line 213
    MAX_RETRIES = 2                                              # line 222

    def __init__(
        self,
        client: Any,                                             # stored as self._client
        registry: FormRegistry | None = None,                    # stored as self._registry
        model: str | None = None,                                # stored as self._model
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
        # Lines 274-292: refinement path
        # Line 279: existing = await self._registry.get(refine_form_id)
        # Line 285: messages = self._build_refinement_messages(existing, prompt)
        # Line 290: form = await self._generate_with_retry(messages, effective_form_id)

    def _build_refinement_messages(
        self,
        existing: FormSchema,
        prompt: str,
    ) -> list[dict[str, str]]:                                   # line 354
        # Line 364: existing_json = existing.model_dump_json(indent=2)

    async def _call_llm(
        self,
        messages: list[dict[str, str]],
    ) -> str:                                                    # line 374
        # Line 389-405: uses self._client.ask() with stateless=True
        # Line 403-404: passes self._model if set
```

```python
# packages/ai-parrot/src/parrot/clients/google/client.py

class GoogleGenAIClient(AbstractClient):
    async def ask(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = None,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,           # ← pass toolkit tools here
        use_tools: Optional[bool] = None,                        # ← set True
        stateless: bool = False,                                 # ← set True
        max_iterations: int = 15,                                # ← default is fine
        **kwargs
    ) -> AIMessage:                                              # line 1724

    # Tool registration flow (lines 1882-1895):
    # When tools=list is passed:
    #   1. Each item is registered via self.register_tool(tool)  # line 1884
    #   2. _build_tools("custom_functions") builds types.Tool    # line 1895
    # Items can be AbstractTool instances.
```

```python
# EditToolkit interface (created by TASK-1131):
class EditToolkit:
    def __init__(self, form: FormSchema) -> None: ...
    @property
    def form(self) -> FormSchema: ...
    def get_tool_definitions(self) -> list[AbstractTool]: ...
```

### Does NOT Exist

- ~~`CreateFormTool._execute_toolkit_edit()`~~ — does not exist yet (this task creates it)
- ~~`CreateFormTool.toolkit`~~ — not a real attribute
- ~~`GoogleGenAIClient.ask_with_tools()`~~ — not a method; use `ask()` with `tools=` param
- ~~`self._client.completion_with_tools()`~~ — not a method
- ~~`FormSchema.field_count`~~ — no such property; count manually via `sum(len(list(s.iter_fields())) for s in form.sections)`

---

## Implementation Notes

### Pattern to Follow

The existing `_execute()` method at line 254 already has a branching structure:
- Lines 274-292 handle refinement (when `refine_form_id` is set)
- Lines 293-332 handle new form creation

Add the toolkit routing INSIDE the refinement branch, before the existing
`_build_refinement_messages()` call:

```python
# Inside _execute(), within the refine_form_id branch:
if refine_form_id:
    existing = await self._registry.get(refine_form_id)
    # ... existing validation ...

    # NEW: Route large forms through toolkit
    if self._should_use_toolkit(existing):
        try:
            form = await self._execute_toolkit_edit(existing, prompt)
            if form is not None:
                # ... persist and return (same logic as existing path) ...
        except Exception as exc:
            self.logger.warning("Toolkit edit failed, falling back: %s", exc)
            # Fall through to existing path below

    # EXISTING: Full-form path (unchanged)
    messages = self._build_refinement_messages(existing, prompt)
    form = await self._generate_with_retry(messages, effective_form_id)
```

### _should_use_toolkit() helper

```python
def _should_use_toolkit(self, form: FormSchema) -> bool:
    """Check if the form is large enough to benefit from toolkit editing."""
    field_count = sum(len(list(s.iter_fields())) for s in form.sections)
    if field_count > 10:
        return True
    serialized_size = len(form.model_dump_json())
    return serialized_size > 20_000
```

### _TOOLKIT_SYSTEM_PROMPT

The system prompt should instruct the LLM to:
1. Start by calling `get_form_summary()` to understand the form structure
2. Use `get_field()` or `search_fields()` to inspect specific elements
3. Use mutation tools to make the requested changes
4. Call `done()` when all edits are complete
5. Never try to return the entire form as text

### Key Constraints

- The `ask()` call MUST use `stateless=True` (no conversation memory)
- Pass `self._model` if set (same as existing `_call_llm` does at line 403-404)
- The toolkit system prompt replaces `_REFINEMENT_PROMPT` for the toolkit path
- After `done()` is called, extract the updated form from `toolkit.form`
- If the LLM response indicates all iterations were used without `done()`,
  treat as failure and fall back

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py` — main file to modify
- `packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py` — EditToolkit (TASK-1131)
- `packages/ai-parrot/src/parrot/clients/google/client.py:1724` — `ask()` signature

---

## Acceptance Criteria

- [ ] `_execute_toolkit_edit()` method exists on `CreateFormTool`
- [ ] `_should_use_toolkit()` returns True for forms with >10 fields OR >20K chars
- [ ] `_execute()` routes to toolkit path for large forms, full-form path for small forms
- [ ] Toolkit path calls `self._client.ask()` with `tools=`, `use_tools=True`, `stateless=True`
- [ ] `_TOOLKIT_SYSTEM_PROMPT` constant instructs LLM on toolkit usage pattern
- [ ] Fallback: if toolkit fails, falls back to `_build_refinement_messages()` path
- [ ] HTTP contract unchanged: `edit_form()` handler works without modification
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py`

---

## Test Specification

> Tests are in TASK-1133. This task should produce code that will pass those tests.

```python
# Minimal verification during development
from parrot_formdesigner.tools.create_form import CreateFormTool

# Verify _should_use_toolkit exists and works
tool = CreateFormTool(client=mock_client)
assert hasattr(tool, '_should_use_toolkit')
assert hasattr(tool, '_execute_toolkit_edit')
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-edition-parts.spec.md` for full context
2. **Check dependencies** — verify TASK-1131 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists
   - Confirm `CreateFormTool._execute()` still has the structure described above
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/formdesigner-edition-parts.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1132-createformtool-toolkit-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-14
**Notes**: Added _execute_toolkit_edit(), _should_use_toolkit(), and _TOOLKIT_SYSTEM_PROMPT to CreateFormTool. Modified _execute() to route all refine_form_id edits through toolkit with fallback to full-form path.

**Deviations from spec**: Per spec Q3, _should_use_toolkit() always returns True (no threshold routing). The _execute() branching routes ALL refine_form_id edits through toolkit; _should_use_toolkit() is kept for testing and future configuration hooks but is not called in the main flow.
