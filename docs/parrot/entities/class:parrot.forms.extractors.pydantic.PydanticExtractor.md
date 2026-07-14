---
type: Wiki Entity
title: PydanticExtractor
id: class:parrot.forms.extractors.pydantic.PydanticExtractor
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extracts FormSchema from Pydantic v2 BaseModel classes.
---

# PydanticExtractor

Defined in [`parrot.forms.extractors.pydantic`](../summaries/mod:parrot.forms.extractors.pydantic.md).

```python
class PydanticExtractor
```

Extracts FormSchema from Pydantic v2 BaseModel classes.

Introspects model fields using Pydantic v2's model_fields API and
maps Python type annotations to FormField/FieldType values.

Supported mappings:
- str -> TEXT
- int -> INTEGER
- float -> NUMBER
- bool -> BOOLEAN
- datetime.datetime -> DATETIME
- datetime.date -> DATE
- datetime.time -> TIME
- Optional[T] -> required=False, type of T
- Literal["a", "b"] -> SELECT with options
- Enum subclass -> SELECT with enum values
- nested BaseModel -> GROUP with children
- list[T] -> ARRAY with item_template

Example:
    extractor = PydanticExtractor()
    schema = extractor.extract(MyModel, title="My Form")

## Methods

- `def extract(self, model: type[BaseModel], *, form_id: str | None=None, title: str | None=None, locale: str='en') -> FormSchema` — Introspect a Pydantic model and produce a FormSchema.
