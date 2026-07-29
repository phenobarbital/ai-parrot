---
type: Wiki Summary
title: parrot.core.tools.handoff
id: mod:parrot.core.tools.handoff
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handoff Tool implementation for Parrot Core.
relates_to:
- concept: class:parrot.core.tools.handoff.HandoffTool
  rel: defines
- concept: class:parrot.core.tools.handoff.HandoffToolSchema
  rel: defines
- concept: mod:parrot.core.exceptions
  rel: references
- concept: mod:parrot.human.models
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.core.tools.handoff`

Handoff Tool implementation for Parrot Core.

.. deprecated::
    Use :class:`parrot.human.tool.HumanTool` with ``policy_id`` for tiered
    escalation.  ``HandoffTool`` is kept for backward compatibility and will
    be removed in a future release.

## Classes

- **`HandoffToolSchema(AbstractToolArgsSchema)`** — Arguments for the HandoffTool.
- **`HandoffTool(AbstractTool)`** — Tool for handing off task execution to a human user.
