---
type: Concept
title: create_skill_tools()
id: func:parrot.skills.tools.create_skill_tools
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create skill registry tools for an agent.
---

# create_skill_tools

```python
def create_skill_tools(registry: SkillRegistry, agent_id: str, include_write_tools: bool=True, file_registry: Optional['SkillFileRegistry']=None, learned_dir: Optional[Path]=None) -> List[AbstractTool]
```

Create skill registry tools for an agent.

Thin factory that instantiates the two skill toolkits and concatenates
their generated tools.

Args:
    registry: Configured SkillRegistry (DB-backed).
    agent_id: Agent identifier string.
    include_write_tools: If ``True``, include the ``document_skill`` /
        ``update_skill`` write tools from :class:`SkillRegistryToolkit`.
    file_registry: Optional :class:`~parrot.skills.file_registry.SkillFileRegistry`
        for file-based tools. When provided, the file-based tools from
        :class:`SkillFileToolkit` (``load_skill``, ``read_skill_asset`` and,
        when ``learned_dir`` is set, ``save_learned_skill``) are included.
    learned_dir: Path to the learned skills directory, required to expose
        the ``save_learned_skill`` tool.

Returns:
    List of :class:`~parrot.tools.abstract.AbstractTool` instances.
