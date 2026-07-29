---
type: Wiki Entity
title: ScaffoldTemplate
id: class:parrot.models.interactive.ScaffoldTemplate
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A deterministic HTML skeleton with named slots for the enhance pass.
---

# ScaffoldTemplate

Defined in [`parrot.models.interactive`](../summaries/mod:parrot.models.interactive.md).

```python
class ScaffoldTemplate(BaseModel)
```

A deterministic HTML skeleton with named slots for the enhance pass.

The skeleton is a complete, self-contained HTML document. ``<!-- SLOT:name -->``
markers indicate where the LLM should inject content during the enhance pass;
in deterministic mode they are replaced with an empty placeholder so the
skeleton still renders standalone.

``allowed_bundles`` lists the library names (matching :attr:`LibraryEntry.name`)
a render against this template may pull. The render tool rejects any requested
library not in this list, keeping each template's attack surface explicit.

## Methods

- `def to_prompt_instruction(self) -> str` — Generate LLM prompt instructions describing this scaffold.
