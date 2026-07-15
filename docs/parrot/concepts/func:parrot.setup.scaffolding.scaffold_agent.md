---
type: Concept
title: scaffold_agent()
id: func:parrot.setup.scaffolding.scaffold_agent
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Scaffold a new Agent Python file from the ``agent.py.tpl`` template.
---

# scaffold_agent

```python
def scaffold_agent(agent_config: object, cwd: Path) -> Path
```

Scaffold a new Agent Python file from the ``agent.py.tpl`` template.

Writes the rendered file to ``AGENTS_DIR/<module_name>.py``,
creating the directory if necessary.

Args:
    agent_config: ``AgentConfig`` instance with ``name``,
        ``agent_id``, and ``provider_config.llm_string`` set.
    cwd: Project root (unused directly; ``AGENTS_DIR`` is resolved
        from ``parrot.conf``).

Returns:
    Absolute ``Path`` of the created agent ``.py`` file.
