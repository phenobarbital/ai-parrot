---
type: Wiki Summary
title: parrot.skills.store
id: mod:parrot.skills.store
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: SkillRegistry - Git-like versioned skill/knowledge store.
relates_to:
- concept: class:parrot.skills.store.SkillRegistry
  rel: defines
- concept: func:parrot.skills.store.apply_unified_diff
  rel: defines
- concept: func:parrot.skills.store.compute_unified_diff
  rel: defines
- concept: func:parrot.skills.store.create_skill_registry
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.skills.models
  rel: references
- concept: mod:parrot.utils.faiss_logging
  rel: references
---

# `parrot.skills.store`

SkillRegistry - Git-like versioned skill/knowledge store.

Provides:
- Skill CRUD with automatic versioning
- Unified diff storage for efficiency
- Vector search for skill discovery
- Auto-extraction of skills from conversations

## Classes

- **`SkillRegistry`** — Git-like versioned skill registry.

## Functions

- `def compute_unified_diff(old_content: str, new_content: str, context_lines: int=3) -> str` — Compute unified diff between two versions.
- `def apply_unified_diff(base_content: str, diff_content: str) -> str` — Apply unified diff to reconstruct content.
- `def create_skill_registry(namespace: str, persistence_path: Optional[str]=None, redis_url: Optional[str]=None, **kwargs) -> SkillRegistry` — Factory function for SkillRegistry.
