---
type: Wiki Summary
title: parrot_formdesigner.controls.registry
id: mod:parrot_formdesigner.controls.registry
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Form-control registry.
relates_to:
- concept: class:parrot_formdesigner.controls.registry.FieldControlMetadata
  rel: defines
- concept: func:parrot_formdesigner.controls.registry.get_controls
  rel: defines
- concept: func:parrot_formdesigner.controls.registry.iter_controls
  rel: defines
- concept: func:parrot_formdesigner.controls.registry.register_field_control
  rel: defines
- concept: mod:parrot_formdesigner.core.types
  rel: references
---

# `parrot_formdesigner.controls.registry`

Form-control registry.

Extending the toolbar:

    from parrot_formdesigner.controls import register_field_control

    register_field_control(
        "rich_text",
        label="Rich Text",
        description="Rich text editor",
        category="advanced",
        icon="rich-text",
        snippet={"type": "string", "format": "rich-text"},
        render_hint="rich",
        supports_constraints=True,
    )

Call this once at consumer startup, before ``setup_form_api(app, registry)``
is called (or any time before the first request — the seed and
extensions live in the same module-level dict).

## Classes

- **`FieldControlMetadata(BaseModel)`** — Metadata describing a single form-control entry for the toolbar.

## Functions

- `def register_field_control(field_type: FieldType | str, *, label: str, description: str, category: str, icon: str, snippet: dict[str, Any], render_hint: str, supports_constraints: bool, is_container: bool=False, supported_operators: list[str] | None=None, supported_effects: list[str] | None=None, supported_operations: list[str] | None=None) -> None` — Register (or overwrite) a control entry in the toolbar registry.
- `def get_controls() -> list[FieldControlMetadata]` — Return all registered controls in registration order.
- `def iter_controls() -> Iterator[FieldControlMetadata]` — Yield registered controls in registration order.
