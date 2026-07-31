---
type: Wiki Overview
title: 'TASK-1256: SKILL.md Extractor'
id: doc:sdd-tasks-completed-task-1256-graphindex-skill-extractor-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements the **SKILL.md extraction** pipeline for GraphIndex.
  SKILL.md files are the skill definition format used throughout AI-Parrot, containing
  YAML frontmatter with metadata (name, description, triggers, etc.) and a markdown
  body. This extractor parses those files
relates_to:
- concept: mod:parrot.knowledge.graphindex.extractors.skill
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.skills
  rel: mentions
---

# TASK-1256: SKILL.md Extractor

**Feature**: FEAT-187 — GraphIndex — Structured Knowledge Graph Indexing
**Spec**: `sdd/specs/graphindex.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1253
**Assigned-to**: unassigned

---

## Context

This task implements the **SKILL.md extraction** pipeline for GraphIndex. SKILL.md files are the skill definition format used throughout AI-Parrot, containing YAML frontmatter with metadata (name, description, triggers, etc.) and a markdown body. This extractor parses those files and emits `UniversalNode` instances with `kind=NodeKind.SKILL`.

This is the simplest of the three parallel extractors (code, loader, skill) and has no dependencies beyond the core schema from TASK-1253.

Implements: Spec §3 Module 2 (Skill Extractor).

---

## Scope

- Parse SKILL.md files (YAML frontmatter + markdown body)
- Extract frontmatter metadata fields (name, description, triggers, etc.)
- Emit `Skill` nodes (`kind=NodeKind.SKILL`) with `domain_tags` derived from frontmatter fields
- Populate `title` from frontmatter `name`, `summary` from frontmatter `description`
- Simple YAML/frontmatter parsing (no complex markdown AST needed)

**NOT in scope**: code extraction, loader extraction, embedding, graph assembly, analytics, toolkit

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/skill.py` | CREATE | SKILL.md parser and Skill node emitter |
| `packages/ai-parrot/tests/knowledge/graphindex/test_skill_extractor.py` | CREATE | Unit tests for skill extractor |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex.schema import (
    UniversalNode,       # from TASK-1253
    UniversalEdge,       # from TASK-1253 (may not emit edges, but import for interface consistency)
    NodeKind,            # DOCUMENT, SECTION, SYMBOL, CONCEPT, RATIONALE, SKILL
    Provenance,          # EXTRACTED, INFERRED, AMBIGUOUS
)
import yaml              # stdlib-compatible; PyYAML already in deps
```

### Does NOT Exist
- ~~`parrot.skills.SkillParser`~~ — no existing skill parser; implement from scratch using YAML frontmatter
- ~~`parrot.knowledge.graphindex.extractors.skill`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
import yaml
import re
from typing import Optional

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

class SkillExtractor:
    """Extract Skill nodes from SKILL.md files.

    Parses YAML frontmatter to populate node metadata and domain_tags.

    Args:
        source_uri_prefix: Optional prefix for source_uri generation.
    """

    def __init__(self, source_uri_prefix: str = "") -> None:
        self.source_uri_prefix = source_uri_prefix

    async def extract(
        self, file_path: str, content: str
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Parse a SKILL.md file and return Skill nodes.

        Args:
            file_path: Path to the SKILL.md file.
            content: Raw file content (frontmatter + body).

        Returns:
            Tuple of (nodes, edges). Edges may be empty for standalone skills.
        """
        ...

    def _parse_frontmatter(self, content: str) -> tuple[dict, str]:
        """Extract YAML frontmatter and remaining body from content.

        Returns:
            Tuple of (frontmatter_dict, body_text).
        """
        ...
```

### SKILL.md Format Reference
```markdown
---
name: my-skill
description: Short description of what this skill does
triggers:
  - "when user asks about X"
  - "before doing Y"
tags:
  - category-a
  - category-b
---

# Skill Body

Detailed instructions for the skill...
```

### Key Constraints
- Async-first, type-hinted, Google-style docstrings
- Use `yaml.safe_load()` for frontmatter parsing (security)
- Gracefully handle malformed frontmatter (log warning, skip file or emit with `provenance="ambiguous"`)
- `domain_tags` should include all frontmatter fields that are not mapped to standard `UniversalNode` fields
- `title` comes from frontmatter `name`; `summary` from frontmatter `description`
- No additional parrot dependencies beyond schema

---

## Acceptance Criteria

- [ ] Parses SKILL.md files with YAML frontmatter
- [ ] Emits `Skill` nodes with `kind=NodeKind.SKILL`
- [ ] `title` populated from frontmatter `name`
- [ ] `summary` populated from frontmatter `description`
- [ ] `domain_tags` includes frontmatter fields (triggers, tags, etc.)
- [ ] Malformed frontmatter handled gracefully (no crash)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_skill_extractor.py -v`
- [ ] Import works: `from parrot.knowledge.graphindex.extractors.skill import SkillExtractor`

---

## Test Specification

```python
import pytest
from parrot.knowledge.graphindex.extractors.skill import SkillExtractor
from parrot.knowledge.graphindex.schema import (
    UniversalNode, NodeKind, Provenance,
)

SAMPLE_SKILL = '''---
name: code-review
description: Review code changes for quality and correctness
triggers:
  - "when completing a task"
  - "before merging"
tags:
  - quality
  - workflow
---

# Code Review Skill

Detailed review instructions here.
'''

MALFORMED_SKILL = '''---
name: broken-skill
description: This frontmatter is missing the closing delimiter
triggers:
  - "something"

Body without proper frontmatter closure.
'''

NO_FRONTMATTER = '''# Just a Markdown File

No YAML frontmatter at all.
'''


class TestSkillExtractor:
    @pytest.fixture
    def extractor(self):
        return SkillExtractor()

    @pytest.mark.asyncio
    async def test_extracts_skill_node(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert len(nodes) == 1
        assert nodes[0].kind == NodeKind.SKILL

    @pytest.mark.asyncio
    async def test_title_from_name(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert nodes[0].title == "code-review"

    @pytest.mark.asyncio
    async def test_summary_from_description(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert nodes[0].summary == "Review code changes for quality and correctness"

    @pytest.mark.asyncio
    async def test_domain_tags_include_triggers(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert "triggers" in nodes[0].domain_tags
        assert len(nodes[0].domain_tags["triggers"]) == 2

    @pytest.mark.asyncio
    async def test_domain_tags_include_tags(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert "tags" in nodes[0].domain_tags
        assert "quality" in nodes[0].domain_tags["tags"]

    @pytest.mark.asyncio
    async def test_malformed_frontmatter_no_crash(self, extractor):
        nodes, edges = await extractor.extract("skills/broken.md", MALFORMED_SKILL)
        # Should not raise; may return empty or degraded node
        assert isinstance(nodes, list)

    @pytest.mark.asyncio
    async def test_no_frontmatter_no_crash(self, extractor):
        nodes, edges = await extractor.extract("skills/plain.md", NO_FRONTMATTER)
        assert isinstance(nodes, list)

    @pytest.mark.asyncio
    async def test_source_uri_set(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert nodes[0].source_uri == "skills/code-review.md"

    @pytest.mark.asyncio
    async def test_provenance_is_extracted(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert nodes[0].provenance == Provenance.EXTRACTED
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/graphindex.spec.md` for full context
2. **Check dependencies** — TASK-1253 must be completed (provides `UniversalNode`, `NodeKind`, etc.)
3. **Verify the Codebase Contract** — confirm schema imports work from TASK-1253
4. **Update status** in `sdd/tasks/index/graphindex.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1256-graphindex-skill-extractor.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
