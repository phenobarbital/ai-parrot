---
type: Wiki Entity
title: SkillRegistry
id: class:parrot.skills.store.SkillRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Git-like versioned skill registry.
---

# SkillRegistry

Defined in [`parrot.skills.store`](../summaries/mod:parrot.skills.store.md).

```python
class SkillRegistry
```

Git-like versioned skill registry.

Features:
- Create/update skills with automatic versioning
- Store diffs for space efficiency
- Reconstruct any historical version
- Vector search for skill discovery
- Agent-driven skill extraction

## Methods

- `async def configure(self, extraction_llm: Optional[Any]=None, embedding_model: Optional[Any]=None) -> None` — Configure the registry.
- `async def upload_skill(self, name: str, content: str, agent_id: str, description: str='', category: Union[SkillCategory, str]=SkillCategory.GENERAL, tags: Optional[List[str]]=None, triggers: Optional[List[str]]=None, related_tools: Optional[List[str]]=None, commit_message: str='', skill_id: Optional[str]=None) -> Tuple[Skill, SkillVersion]` — Upload a new skill or new version of existing skill.
- `async def read_skill(self, skill_id: str, version: Optional[int]=None) -> str` — Read skill content, reconstructing from diffs if needed.
- `async def search_skills(self, query: str, category: Optional[SkillCategory]=None, tags: Optional[List[str]]=None, include_deprecated: bool=False, max_results: int=5) -> List[SkillSearchResult]` — Search for relevant skills.
- `async def get_skill_versions(self, skill_id: str) -> List[Dict[str, Any]]` — Get version history for a skill.
- `async def deprecate_skill(self, skill_id: str, reason: str='') -> Skill` — Mark skill as deprecated.
- `async def revoke_skill(self, skill_id: str, reason: str='') -> Skill` — Mark skill as revoked (do not use).
- `async def extract_skill_from_conversation(self, conversation: str, agent_id: str, context: Optional[str]=None) -> Optional[Tuple[Skill, SkillVersion]]` — Use LLM to extract a skill from conversation.
- `async def get_relevant_skills(self, query: str, max_skills: int=3, max_tokens: int=2000) -> str` — Get relevant skills formatted for context injection.
- `async def list_skills(self, include_deprecated: bool=False) -> List[Dict[str, Any]]` — List all skills with summary info.
- `async def cleanup(self) -> None` — Cleanup resources.
