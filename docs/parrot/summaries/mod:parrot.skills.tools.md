---
type: Wiki Summary
title: parrot.skills.tools
id: mod:parrot.skills.tools
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SkillRegistry Tools for AI-Parrot Agents.
relates_to:
- concept: class:parrot.skills.tools.DocumentSkillArgs
  rel: defines
- concept: class:parrot.skills.tools.LoadSkillArgs
  rel: defines
- concept: class:parrot.skills.tools.ReadSkillAssetArgs
  rel: defines
- concept: class:parrot.skills.tools.ReadSkillToolArgs
  rel: defines
- concept: class:parrot.skills.tools.SaveLearnedSkillArgs
  rel: defines
- concept: class:parrot.skills.tools.SkillFileToolkit
  rel: defines
- concept: class:parrot.skills.tools.SkillRegistryToolkit
  rel: defines
- concept: class:parrot.skills.tools.UpdateSkillArgs
  rel: defines
- concept: func:parrot.skills.tools.create_skill_tools
  rel: defines
- concept: mod:parrot.skills.models
  rel: references
- concept: mod:parrot.skills.parsers
  rel: references
- concept: mod:parrot.skills.store
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.decorators
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.skills.tools`

SkillRegistry Tools for AI-Parrot Agents.

Provides tools that agents can use to:
- Document learned skills/patterns
- Search for relevant skills
- Read skill content
- Update existing skills
- Save learned skills as .md files for immediate /trigger activation

Tools are grouped into two toolkits, each initialized once with its shared
dependency:

- :class:`SkillRegistryToolkit` — DB-backed registry (search/read/list/
  document/update), sharing a :class:`~parrot.skills.store.SkillRegistry`.
- :class:`SkillFileToolkit` — file-based skills (list_commands/load/read_asset/
  save_learned), sharing a
  :class:`~parrot.skills.file_registry.SkillFileRegistry`.

## Classes

- **`DocumentSkillArgs(BaseModel)`** — Arguments for documenting a new skill.
- **`UpdateSkillArgs(BaseModel)`** — Arguments for updating an existing skill.
- **`ReadSkillToolArgs(BaseModel)`** — Arguments for reading a skill.
- **`SkillRegistryToolkit(AbstractToolkit)`** — Unified toolkit for the DB-backed skill registry, sharing one store.
- **`SaveLearnedSkillArgs(BaseModel)`** — Arguments for saving a learned skill as a .md file.
- **`LoadSkillArgs(BaseModel)`** — Arguments for loading a skill's full content on demand.
- **`ReadSkillAssetArgs(BaseModel)`** — Arguments for reading a bundled asset of a composite skill.
- **`SkillFileToolkit(AbstractToolkit)`** — Unified toolkit for file-based skills, sharing one ``SkillFileRegistry``.

## Functions

- `def create_skill_tools(registry: SkillRegistry, agent_id: str, include_write_tools: bool=True, file_registry: Optional['SkillFileRegistry']=None, learned_dir: Optional[Path]=None) -> List[AbstractTool]` — Create skill registry tools for an agent.
