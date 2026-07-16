---
type: Wiki Entity
title: SkillRegistryToolkit
id: class:parrot.skills.tools.SkillRegistryToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Unified toolkit for the DB-backed skill registry, sharing one store.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# SkillRegistryToolkit

Defined in [`parrot.skills.tools`](../summaries/mod:parrot.skills.tools.md).

```python
class SkillRegistryToolkit(AbstractToolkit)
```

Unified toolkit for the DB-backed skill registry, sharing one store.

Every public async method becomes a tool whose name equals the method name
(no ``tool_prefix`` is applied, so ``search_skills``, ``read_skill``,
``list_skills``, ``document_skill`` and ``update_skill`` keep their
historical names). The :class:`~parrot.skills.store.SkillRegistry` and the
``agent_id`` are injected once and shared by every tool, replacing the
previous one-class-per-tool wiring.

Write tools (``document_skill``, ``update_skill``) are exposed only when
``include_write_tools`` is ``True``.

Args:
    registry: Configured DB-backed :class:`~parrot.skills.store.SkillRegistry`.
    agent_id: Agent identifier, recorded as the author of documented/updated
        skills.
    include_write_tools: When ``False``, ``document_skill`` and
        ``update_skill`` are not exposed.

## Methods

- `async def search_skills(self, query: str, category: Optional[str]=None, tags: Optional[List[str]]=None, include_deprecated: bool=False, max_results: int=5) -> ToolResult` — Search for relevant skills and patterns. Use before tackling
- `async def read_skill(self, skill_id: str, version: Optional[int]=None) -> ToolResult` — Read the full content of a skill by ID.
- `async def list_skills(self) -> ToolResult` — List all available skills with summary info.
- `async def document_skill(self, name: str, description: str, content: str, category: str='general', tags: Optional[List[str]]=None, triggers: Optional[List[str]]=None, related_tools: Optional[List[str]]=None) -> ToolResult` — Document a learned skill or pattern for future reference. Use when
- `async def update_skill(self, skill_id: str, content: str, commit_message: str='', name: Optional[str]=None, description: Optional[str]=None) -> ToolResult` — Update an existing skill with improved content. Creates a new version
