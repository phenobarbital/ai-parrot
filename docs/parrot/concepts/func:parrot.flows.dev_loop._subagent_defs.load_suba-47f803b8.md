---
type: Concept
title: load_subagent_definition()
id: func:parrot.flows.dev_loop._subagent_defs.load_subagent_definition
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the system-prompt body of an SDD subagent.
---

# load_subagent_definition

```python
def load_subagent_definition(name: str) -> str
```

Return the system-prompt body of an SDD subagent.

Args:
    name: One of ``"sdd-research"``, ``"sdd-worker"``, ``"sdd-qa"``,
        ``"sdd-codereview"``.

Returns:
    The Markdown body of the subagent definition with the YAML
    frontmatter stripped.

Raises:
    ValueError: If ``name`` is not one of the three known subagents.
    FileNotFoundError: If the package-bundled data file is missing
        (indicates a packaging error).
