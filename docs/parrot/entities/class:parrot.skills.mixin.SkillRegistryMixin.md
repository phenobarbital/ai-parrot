---
type: Wiki Entity
title: SkillRegistryMixin
id: class:parrot.skills.mixin.SkillRegistryMixin
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mixin to add skill registry capabilities to AbstractBot.
---

# SkillRegistryMixin

Defined in [`parrot.skills.mixin`](../summaries/mod:parrot.skills.mixin.md).

```python
class SkillRegistryMixin
```

Mixin to add skill registry capabilities to AbstractBot.

Features:

- Auto-configure skill registry
- Expose skill tools to agent
- Inject relevant skills into context
- Auto-extract skills from conversations
- File-based skill registry with eager loading
- Skill trigger middleware for /trigger patterns
- Directory discovery via :class:`~parrot.skills.loader.SkillsDirectoryLoader`
  when :attr:`skill_paths` is non-empty (FEAT-188).
- Static ``<available_skills>`` XML layer injected into system prompt via
  :func:`~parrot.skills.prompt.render_skills_prompt_layer` when
  :attr:`inject_skills_into_prompt` is ``True`` (FEAT-188).
- :class:`~parrot.skills.tools.SkillFileToolkit` registration exposing
  ``list_skill_commands`` / ``load_skill`` / ``read_skill_asset`` /
  ``save_learned_skill`` for skill discovery, on-demand body and asset
  retrieval (FEAT-188).

Usage::

    class MyAgent(SkillRegistryMixin, AbstractBot):
        enable_skill_registry = True
        skill_paths = [Path(".agent/skills/")]
        inject_skills_into_prompt = True

## Methods

- `async def save_learned_skill(self, name: str, content: str, description: str, triggers: List[str], category: str='general') -> Optional[SkillDefinition]` — Save a learned skill as a .md file and hot-add to the registry.
- `async def get_skill_context(self, query: str, max_skills: Optional[int]=None, max_tokens: Optional[int]=None) -> str` — Get relevant skills for context injection.
- `async def document_skill(self, name: str, content: str, description: str='', category: str='general', tags: Optional[List[str]]=None, triggers: Optional[List[str]]=None) -> Optional[Skill]` — Programmatically document a skill.
- `async def extract_skills_from_conversation(self, conversation: str, context: Optional[str]=None) -> Optional[Skill]` — Use LLM to extract skills from conversation.
- `async def search_skills(self, query: str, category: Optional[str]=None, max_results: int=5) -> List[Dict[str, Any]]` — Search for relevant skills.
