---
type: Wiki Entity
title: SkillFileRegistry
id: class:parrot.skills.file_registry.SkillFileRegistry
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Filesystem-based skill registry with eager loading.
---

# SkillFileRegistry

Defined in [`parrot.skills.file_registry`](../summaries/mod:parrot.skills.file_registry.md).

```python
class SkillFileRegistry
```

Filesystem-based skill registry with eager loading.

Loads .md skill files from a skills directory and an optional learned
subdirectory, validates them, and indexes by trigger name in a dict.

Args:
    skills_dir: Path to the authored skills directory.
    learned_dir: Path to the learned skills directory. Defaults to
        ``skills_dir / "learned"``.

## Methods

- `async def load(self) -> None` — Eagerly load all .md skill files from both directories.
- `def get(self, trigger: str) -> Optional[SkillDefinition]` — Look up a skill by its trigger name.
- `def get_by_name(self, name: str) -> Optional[SkillDefinition]` — Look up a skill by its name.
- `def add(self, skill: SkillDefinition) -> None` — Hot-add a skill. Used for learned skills saved during session.
- `def list_skills(self) -> List[SkillDefinition]` — Return all loaded skills.
- `def has_trigger(self, trigger: str) -> bool` — Check if a trigger is registered.
