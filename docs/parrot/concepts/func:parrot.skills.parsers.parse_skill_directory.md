---
type: Concept
title: parse_skill_directory()
id: func:parrot.skills.parsers.parse_skill_directory
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Parse a composite skill: ``{dir}/SKILL.md`` plus adjacent asset files.'
---

# parse_skill_directory

```python
def parse_skill_directory(skill_dir: Path) -> SkillDefinition
```

Parse a composite skill: ``{dir}/SKILL.md`` plus adjacent asset files.

A composite skill is a directory containing a ``SKILL.md`` entry point
(parsed via :func:`parse_skill_file`) and zero or more adjacent asset
files (scripts, templates, examples). The ``assets_dir`` field on the
returned :class:`~parrot.skills.models.SkillDefinition` is set to the
directory path so downstream components can enumerate assets.

Args:
    skill_dir: Path to the skill directory (must contain ``SKILL.md``).

Returns:
    Parsed and validated SkillDefinition with ``assets_dir`` set to
    ``skill_dir``.

Raises:
    FileNotFoundError: If ``SKILL.md`` is absent in ``skill_dir``.
    ValueError: If required frontmatter fields are missing from
        ``SKILL.md``.
    ValidationError: If the skill fails Pydantic validation.
