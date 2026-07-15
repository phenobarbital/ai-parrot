---
type: Wiki Entity
title: SkillsDirectoryLoader
id: class:parrot.skills.loader.SkillsDirectoryLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Discover and load skills from one or more filesystem directories.
---

# SkillsDirectoryLoader

Defined in [`parrot.skills.loader`](../summaries/mod:parrot.skills.loader.md).

```python
class SkillsDirectoryLoader
```

Discover and load skills from one or more filesystem directories.

Supports two skill layouts:

- **Single-file**: ``{dir}/{name}.md`` — a plain Markdown file with
  YAML frontmatter.
- **Composite**: ``{dir}/{name}/SKILL.md`` — a directory containing
  ``SKILL.md`` plus adjacent asset files (scripts, templates, etc.).

Failed parses are logged as warnings and skipped; the loader never
crashes on malformed input.

Args:
    paths: List of filesystem paths to scan. Paths that do not exist
        or are not directories are logged at DEBUG level and skipped.
    logger: Optional logger; if not provided, a module-level logger is
        used.

Example::

    loader = SkillsDirectoryLoader(
        paths=[Path(".agent/skills/")],
        logger=self.logger,
    )
    count = await loader.load_into(self._skill_file_registry)

## Methods

- `async def discover(self) -> List[SkillDefinition]` — Scan all configured paths and return discovered SkillDefinitions.
- `async def load_into(self, registry: SkillFileRegistry) -> int` — Discover skills and hot-add them to an existing registry.
