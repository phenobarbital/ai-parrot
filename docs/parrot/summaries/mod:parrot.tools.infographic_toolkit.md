---
type: Wiki Summary
title: parrot.tools.infographic_toolkit
id: mod:parrot.tools.infographic_toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: InfographicToolkit — Frozen multi-dataset HTML infographic artifacts (FEAT-197).
relates_to:
- concept: class:parrot.tools.infographic_toolkit.InfographicRenderResult
  rel: defines
- concept: class:parrot.tools.infographic_toolkit.InfographicToolkit
  rel: defines
- concept: class:parrot.tools.infographic_toolkit.InfographicValidationError
  rel: defines
- concept: mod:parrot.bots.prompts
  rel: references
- concept: mod:parrot.models.infographic
  rel: references
- concept: mod:parrot.models.infographic_templates
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.outputs.formats
  rel: references
- concept: mod:parrot.storage.artifact_signing
  rel: references
- concept: mod:parrot.storage.artifacts
  rel: references
- concept: mod:parrot.storage.models
  rel: references
- concept: mod:parrot.template.engine
  rel: references
- concept: mod:parrot.tools._enhance_html_check
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.tools.infographic_toolkit`

InfographicToolkit — Frozen multi-dataset HTML infographic artifacts (FEAT-197).

This toolkit exposes four tools to the LLM:

    infographic_render            — Validate + render + persist.
    infographic_list_templates    — Discover available templates.
    infographic_get_template_contract — Fetch a template's positional contract.
    infographic_validate_blocks   — Dry-run block validation (no persistence).

With ``return_direct=True`` the toolkit bypasses LLM re-summarisation: the
result of ``infographic_render`` is the final agent output, consumed by
``PandasAgent.ask()``'s post-loop branch (TASK-1326).

## Classes

- **`InfographicValidationError(Exception)`** — Structured error raised by the validation pipeline.
- **`InfographicRenderResult(BaseModel)`** — Envelope returned by InfographicToolkit.render (return_direct=True).
- **`InfographicToolkit(AbstractToolkit)`** — Toolkit that produces frozen, multi-dataset HTML infographic artifacts.
