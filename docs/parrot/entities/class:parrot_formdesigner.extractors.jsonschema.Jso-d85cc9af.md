---
type: Wiki Entity
title: JsonSchemaExtractor
id: class:parrot_formdesigner.extractors.jsonschema.JsonSchemaExtractor
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Converts JSON Schema dicts into FormSchema instances.
---

# JsonSchemaExtractor

Defined in [`parrot_formdesigner.extractors.jsonschema`](../summaries/mod:parrot_formdesigner.extractors.jsonschema.md).

```python
class JsonSchemaExtractor
```

Converts JSON Schema dicts into FormSchema instances.

Supports:
- JSON Schema type mapping (string/number/integer/boolean/array/object)
- JSON Schema format mapping (email/uri/date/date-time/time)
- Constraint extraction (minLength, maxLength, minimum, maximum, pattern)
- $ref and $defs/$definitions resolution
- enum values as SELECT options
- required array for field requiredness
- oneOf/anyOf union types (first non-null type wins)
- Nested object properties as GROUP fields

Example:
    extractor = JsonSchemaExtractor()
    schema_dict = MyModel.model_json_schema()
    form = extractor.extract(schema_dict, title="My Form")

## Methods

- `def extract(self, schema: dict[str, Any], *, form_id: str | None=None, title: str | None=None) -> FormSchema` — Convert a JSON Schema dict into a FormSchema.
