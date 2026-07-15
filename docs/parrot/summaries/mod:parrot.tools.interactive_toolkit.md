---
type: Wiki Summary
title: parrot.tools.interactive_toolkit
id: mod:parrot.tools.interactive_toolkit
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: InteractiveToolkit — free-form, self-contained interactive HTML artifacts.
relates_to:
- concept: class:parrot.tools.interactive_toolkit.InteractiveToolkit
  rel: defines
- concept: class:parrot.tools.interactive_toolkit.InteractiveValidationError
  rel: defines
- concept: mod:parrot.bots.prompts
  rel: references
- concept: mod:parrot.models.infographic
  rel: references
- concept: mod:parrot.models.interactive
  rel: references
- concept: mod:parrot.storage.artifact_signing
  rel: references
- concept: mod:parrot.storage.artifacts
  rel: references
- concept: mod:parrot.storage.models
  rel: references
- concept: mod:parrot.tools._enhance_html_check
  rel: references
- concept: mod:parrot.tools.interactive.catalog_registry
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.tools.interactive_toolkit`

InteractiveToolkit — free-form, self-contained interactive HTML artifacts.

The "vibe-coding" counterpart to :class:`~parrot.tools.infographic_toolkit.InfographicToolkit`.
Where infographics constrain the LLM to typed JSON blocks rendered
deterministically, this toolkit hands the LLM a **scaffold** (a self-contained
HTML skeleton with named slots) plus a **catalog** of vetted JS libraries, and
lets it author the HTML/JS directly during an *enhance* pass. The result is the
same artifact plumbing infographics use: persisted via :class:`ArtifactStore`,
served by the public signed-URL HTML route, and locked down by the JSBundle
SRI allow-list + CSP.

Tools exposed (prefixed with ``interactive_``)::

    interactive_render            — Build skeleton + enhance + validate + persist.
    interactive_list_templates    — Discover scaffold templates.
    interactive_list_libraries    — Discover available JS libraries.
    interactive_get_scaffold      — Inspect one template's skeleton + libraries.

With ``return_direct=True`` the ``interactive_render`` result is the final agent
output (consumed by the agent post-loop), exactly like ``infographic_render``.

## Classes

- **`InteractiveValidationError(Exception)`** — Structured error raised by the interactive render pipeline.
- **`InteractiveToolkit(AbstractToolkit)`** — Toolkit producing self-contained interactive HTML artifacts.
