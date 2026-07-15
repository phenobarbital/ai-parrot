---
type: Wiki Entity
title: JsonSchemaRenderer
id: class:parrot.forms.renderers.jsonschema.JsonSchemaRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Renders FormSchema as a structural JSON Schema with x- extensions.
---

# JsonSchemaRenderer

Defined in [`parrot.forms.renderers.jsonschema`](../summaries/mod:parrot.forms.renderers.jsonschema.md).

```python
class JsonSchemaRenderer(AbstractFormRenderer)
```

Renders FormSchema as a structural JSON Schema with x- extensions.

The output is designed for custom frontend components that need both
the data schema and form metadata (sections, labels, dependencies).

Output format:
- content: JSON Schema dict (type=object, $schema, title, properties, required)
- style_output: StyleSchema dict (layout, field styles, etc.)
- content_type: "application/schema+json"

Extensions used:
- x-field-type: original FieldType value
- x-section: section metadata (section_id, title, description)
- x-depends-on: conditional visibility rule (serialized DependencyRule)
- x-options-source: dynamic options source configuration
- x-placeholder: placeholder text
- x-read-only: read-only flag

Example:
    renderer = JsonSchemaRenderer()
    result = await renderer.render(form_schema, style_schema)
    schema = result.content       # dict
    style = result.style_output   # dict

## Methods

- `async def render(self, form: FormSchema, style: StyleSchema | None=None, *, locale: str='en', prefilled: dict[str, Any] | None=None, errors: dict[str, str] | None=None) -> RenderedForm` — Render a FormSchema as a structural JSON Schema.
