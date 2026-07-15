---
type: Concept
title: discover_skills_in_dir()
id: func:parrot.skills.parsers.discover_skills_in_dir
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Discover single-file and composite skills in a directory (non-recursive).
---

# discover_skills_in_dir

```python
def discover_skills_in_dir(directory: Path, logger: logging.Logger=_LOGGER, exclude_names: Iterable[str]=()) -> List[SkillDefinition]
```

Discover single-file and composite skills in a directory (non-recursive).

Implements the per-directory contract shared by Claude Code, Cursor and
Gemini: a directory entry is a skill if it is either a single ``.md`` file
or a subdirectory containing a ``SKILL.md`` entry point.

- **Single-file**: ``{directory}/{name}.md`` → :func:`parse_skill_file`.
- **Composite**: ``{directory}/{name}/SKILL.md`` → :func:`parse_skill_directory`.

Entries are iterated in sorted order for deterministic discovery. Entries
whose name appears in ``exclude_names`` are skipped (e.g. the reserved
``learned`` subdirectory). Non-``.md`` files and directories lacking a
``SKILL.md`` are silently ignored. Malformed skills are logged as warnings
and skipped so one bad skill never aborts discovery.

Args:
    directory: Directory to scan. Returns an empty list if it does not
        exist or is not a directory.
    logger: Logger for malformed-skill warnings.
    exclude_names: Entry names to skip (matched against ``entry.name``).

Returns:
    List of successfully parsed :class:`~parrot.skills.models.SkillDefinition`.
