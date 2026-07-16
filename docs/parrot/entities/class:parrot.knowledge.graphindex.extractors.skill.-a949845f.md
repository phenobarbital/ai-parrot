---
type: Wiki Entity
title: SkillExtractor
id: class:parrot.knowledge.graphindex.extractors.skill.SkillExtractor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extract Skill nodes from SKILL.md files.
---

# SkillExtractor

Defined in [`parrot.knowledge.graphindex.extractors.skill`](../summaries/mod:parrot.knowledge.graphindex.extractors.skill.md).

```python
class SkillExtractor
```

Extract Skill nodes from SKILL.md files.

Parses YAML frontmatter to populate node metadata and ``domain_tags``.

Args:
    source_uri_prefix: Optional prefix prepended to file paths when
        constructing ``source_uri``.  Defaults to empty string.

## Methods

- `async def extract(self, file_path: str, content: str) -> tuple[list[UniversalNode], list[UniversalEdge]]` — Parse a SKILL.md file and return Skill nodes.
