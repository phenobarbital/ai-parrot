---
type: Wiki Entity
title: FormType
id: class:parrot_formdesigner.core.schema.FormType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Discriminator for the form's structural type.
---

# FormType

Defined in [`parrot_formdesigner.core.schema`](../summaries/mod:parrot_formdesigner.core.schema.md).

```python
class FormType(str, Enum)
```

Discriminator for the form's structural type.

Attributes:
    SIMPLE: A straightforward form with a linear set of questions
        (no survey blocks). This is the default.
    PRODUCT: A form bound to one or more product programmes
        (activated via FEAT-302 ``product_bindings``).
    SURVEY: A form composed of survey-style question blocks
        (imported from ``networkninja.forms.question_blocks`` where
        ``block_type == "survey"``).
