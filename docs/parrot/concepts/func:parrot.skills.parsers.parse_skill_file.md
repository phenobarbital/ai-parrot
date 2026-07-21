---
type: Concept
title: parse_skill_file()
id: func:parrot.skills.parsers.parse_skill_file
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse a .md skill file with YAML frontmatter into a SkillDefinition.
---

# parse_skill_file

```python
def parse_skill_file(file_path: Path) -> SkillDefinition
```

Parse a .md skill file with YAML frontmatter into a SkillDefinition.

Args:
    file_path: Path to the .md file.

Returns:
    Parsed and validated SkillDefinition.

Raises:
    ValueError: If required frontmatter fields are missing.
    ValidationError: If the skill fails Pydantic validation (e.g., token limit).
    FileNotFoundError: If the file does not exist.
