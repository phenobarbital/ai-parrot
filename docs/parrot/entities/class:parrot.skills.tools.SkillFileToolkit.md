---
type: Wiki Entity
title: SkillFileToolkit
id: class:parrot.skills.tools.SkillFileToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Unified toolkit for file-based skills, sharing one ``SkillFileRegistry``.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# SkillFileToolkit

Defined in [`parrot.skills.tools`](../summaries/mod:parrot.skills.tools.md).

```python
class SkillFileToolkit(AbstractToolkit)
```

Unified toolkit for file-based skills, sharing one ``SkillFileRegistry``.

Every public async method becomes a tool whose name equals the method name
(no ``tool_prefix`` is applied, so ``load_skill``, ``read_skill_asset`` and
``save_learned_skill`` keep the historical names referenced by the
``<available_skills>`` prompt layer). The registry is injected once and
shared by every tool, replacing the previous one-class-per-tool wiring.

Tiers:

- ``list_skill_commands`` (Tier 1): live listing of every registered skill
  with its description and ``/trigger`` commands.
- ``load_skill`` (Tier 2): full skill body + asset manifest for composite
  skills.
- ``read_skill_asset`` (Tier 2): sandboxed reader for a bundled asset.
- ``save_learned_skill``: persist an LLM-authored skill for immediate use.

Args:
    file_registry: Shared
        :class:`~parrot.skills.file_registry.SkillFileRegistry`.
    learned_dir: Directory where learned skills are written. When ``None``
        the ``save_learned_skill`` tool is not exposed.
    max_asset_bytes: Truncation ceiling for ``read_skill_asset``. Defaults
        to 64 KiB.

## Methods

- `async def list_skill_commands(self) -> ToolResult` — List all available skills with their descriptions and /trigger
- `async def load_skill(self, name: str) -> ToolResult` — Load the full content of a skill from the agent's skills directory.
- `async def read_skill_asset(self, skill_name: str, asset: str) -> ToolResult` — Read the content of an asset bundled with a composite skill
- `async def save_learned_skill(self, name: str, description: str, content: str, triggers: Optional[List[str]]=None, category: str='general') -> ToolResult` — Save a new learned skill as a .md file for immediate use via /trigger.
