---
type: Wiki Summary
title: parrot.models.infographic_templates
id: mod:parrot.models.infographic_templates
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Infographic Template Definitions.
relates_to:
- concept: class:parrot.models.infographic_templates.BlockSpec
  rel: defines
- concept: class:parrot.models.infographic_templates.InfographicTemplate
  rel: defines
- concept: class:parrot.models.infographic_templates.InfographicTemplateRegistry
  rel: defines
- concept: mod:parrot.models.infographic
  rel: references
---

# `parrot.models.infographic_templates`

Infographic Template Definitions.

Templates define the expected block sequence for an infographic,
allowing users to select a pre-built layout and get deterministic
structure from the LLM output.

Each template specifies:
    - An ordered list of block specs (type + constraints)
    - A description used in the LLM prompt
    - Optional theme defaults

Users can also define custom templates programmatically.

## Classes

- **`BlockSpec(BaseModel)`** — Specification for a single block slot in a template.
- **`InfographicTemplate(BaseModel)`** — Defines the structure and block order for an infographic layout.
- **`InfographicTemplateRegistry`** — Registry of available infographic templates.
