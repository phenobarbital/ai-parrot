---
id: F002
title: FormSchema — the service's return contract
source_queries: [Q002]
---

`packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` defines
the canonical Pydantic model the service must produce.

```python
class FormSchema(BaseModel):
    form_id: str
    version: str = "1.0"
    title: LocalizedString
    description: LocalizedString | None = None
    sections: list[FormSection]
    submit: SubmitAction | None = None
    cancel_allowed: bool = True
    meta: dict[str, Any] | None = None
    created_at: datetime | None = None
    tenant: str | None = None
```
(lines 108-142)

Supporting types in the same module:
- `FormField` (21-65) — self-referential, supports GROUP children and ARRAY templates.
- `FormSection` (68-88) — `section_id`, `title`, `fields`, optional `depends_on`.
- `SubmitAction` (91-105) — currently unused by `DatabaseFormTool` flow.

Implication: `AbstractFormService.build_form_schema()` must return a
`FormSchema` instance — not a dict — so callers can rely on Pydantic
validation as the contract boundary.
