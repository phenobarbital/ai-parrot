---
type: Wiki Entity
title: ClaudeIntegrationConfig
id: class:parrot.knowledge.wiki.project.ClaudeIntegrationConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Settings for the Claude Code integration.
---

# ClaudeIntegrationConfig

Defined in [`parrot.knowledge.wiki.project`](../summaries/mod:parrot.knowledge.wiki.project.md).

```python
class ClaudeIntegrationConfig(BaseModel)
```

Settings for the Claude Code integration.

Attributes:
    nudge_cooldown_seconds: Minimum seconds between two hook
        nudges, so search-heavy turns are not spammed.
    nudge_tools: Tool names the PreToolUse nudge applies to.
