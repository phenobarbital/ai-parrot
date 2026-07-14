---
type: Wiki Entity
title: EditToolkit
id: class:parrot_formdesigner.tools.edit_toolkit.EditToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit exposing FormSchema inspection and mutation as LLM-callable tools.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# EditToolkit

Defined in [`parrot_formdesigner.tools.edit_toolkit`](../summaries/mod:parrot_formdesigner.tools.edit_toolkit.md).

```python
class EditToolkit(AbstractToolkit)
```

Toolkit exposing FormSchema inspection and mutation as LLM-callable tools.

The toolkit manages a deep copy of the FormSchema as its working state.
Inspection tools read from this copy; mutation tools modify it via the
operations.py apply functions (reusing all existing validation logic).

The LLM never sees the full form JSON — it uses ``get_form_summary`` to
understand the structure, inspection tools to examine specific elements,
and mutation tools to apply targeted changes.  When all edits are complete
the LLM calls ``done`` and the caller retrieves the updated form via the
``form`` property.

Usage::

    toolkit = EditToolkit(form)
    tools = toolkit.get_tools()           # List[AbstractTool]
    # Pass tools to GoogleGenAIClient.ask(tools=tools, use_tools=True, ...)
    updated_form = toolkit.form           # Retrieve after done() is called

## Methods

- `def form(self) -> FormSchema` — Current state of the working copy after all mutations.
- `def is_done(self) -> bool` — True after the LLM has called the ``done`` tool.
- `async def get_form_summary(self) -> dict` — Return a compact outline of the form structure.
- `async def get_section(self, section_id: str) -> dict` — Return the full JSON for a single section by section_id.
- `async def get_field(self, field_id: str) -> dict` — Return the full JSON for a single field by field_id.
- `async def search_fields(self, query: str, field_type: str | None=None) -> list[dict]` — Search for fields matching a label substring, type, or ID pattern.
- `async def update_field(self, section_id: str, field_id: str, patch: dict) -> dict` — Apply an RFC 7396 merge-patch to a single field.
- `async def add_field(self, section_id: str, field: dict, position: int | None=None) -> dict` — Add a new field to a section at an optional position.
- `async def remove_field(self, section_id: str, field_id: str) -> dict` — Remove a field from a section.
- `async def add_dependency(self, field_id: str, rule: dict) -> dict` — Set or replace the ``depends_on`` rule on a field.
- `async def update_dependency(self, field_id: str, patch: dict) -> dict` — Merge-patch the existing ``depends_on`` rule on a field.
- `async def remove_dependency(self, field_id: str) -> dict` — Clear the ``depends_on`` rule from a field.
- `async def add_post_dependency(self, field_id: str, post: dict) -> dict` — Append a :class:`PostDependency` to a field's ``post_depends`` list.
- `async def remove_post_dependency(self, field_id: str, target: str) -> dict` — Remove a specific post-dependency (by target field_id) from a field.
- `async def add_section(self, section: dict, position: int | None=None) -> dict` — Add a new section to the form at an optional position.
- `async def update_section(self, section_id: str, patch: dict) -> dict` — Apply an RFC 7396 merge-patch to a section's ``meta`` dict.
- `async def move_field(self, from_section: str, field_id: str, to_section: str, position: int | None=None) -> dict` — Move a field within or across sections.
- `async def update_form_meta(self, patch: dict) -> dict` — Apply an RFC 7396 merge-patch to the form-level ``meta`` dict.
- `async def update_form_title(self, title: str) -> dict` — Update the form title.
- `async def update_form_description(self, description: str | None) -> dict` — Update the form description.
- `async def update_section_title(self, section_id: str, title: str) -> dict` — Update a section's title (rename a section).
- `async def done(self) -> dict` — Signal that all edits are complete.
- `def get_tool_definitions(self) -> list` — Return the list of AbstractTool instances for all 12 toolkit tools.
- `async def execute_tool(self, tool_name: str, arguments: dict) -> dict` — Execute a toolkit tool by name.
