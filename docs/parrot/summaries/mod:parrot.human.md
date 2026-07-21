---
type: Wiki Summary
title: parrot.human
id: mod:parrot.human
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Human-in-the-Loop (HITL) Architecture for AI-Parrot.
relates_to:
- concept: func:parrot.human.get_default_human_manager
  rel: defines
- concept: func:parrot.human.set_default_human_manager
  rel: defines
- concept: mod:parrot
  rel: references
- concept: mod:parrot.human.channels.teams
  rel: references
- concept: mod:parrot.manager
  rel: references
- concept: mod:parrot.models
  rel: references
---

# `parrot.human`

Human-in-the-Loop (HITL) Architecture for AI-Parrot.

Provides agent-level (HumanTool) and flow-level (HumanDecisionNode)
human interaction capabilities with pluggable communication channels.

## Functions

- `def set_default_human_manager(manager: Optional[HumanInteractionManager]) -> None` — Register the process-wide default HumanInteractionManager.
- `def get_default_human_manager() -> Optional[HumanInteractionManager]` — Return the process-wide default HumanInteractionManager, if any.
