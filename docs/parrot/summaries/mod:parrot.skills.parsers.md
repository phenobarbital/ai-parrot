---
type: Wiki Summary
title: parrot.skills.parsers
id: mod:parrot.skills.parsers
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Skill file parser for .md files with YAML frontmatter.
relates_to:
- concept: func:parrot.skills.parsers.discover_skills_in_dir
  rel: defines
- concept: func:parrot.skills.parsers.parse_skill_directory
  rel: defines
- concept: func:parrot.skills.parsers.parse_skill_file
  rel: defines
- concept: mod:parrot.skills.models
  rel: references
---

# `parrot.skills.parsers`

Skill file parser for .md files with YAML frontmatter.

Parses skill definitions from markdown files that follow the format:
---
name: resumen
description: Resume textos largos en bullet points
triggers:
  - /resumen
source: authored
---

<skill instructions body>

## Functions

- `def parse_skill_file(file_path: Path) -> SkillDefinition` — Parse a .md skill file with YAML frontmatter into a SkillDefinition.
- `def parse_skill_directory(skill_dir: Path) -> SkillDefinition` — Parse a composite skill: ``{dir}/SKILL.md`` plus adjacent asset files.
- `def discover_skills_in_dir(directory: Path, logger: logging.Logger=_LOGGER, exclude_names: Iterable[str]=()) -> List[SkillDefinition]` — Discover single-file and composite skills in a directory (non-recursive).
