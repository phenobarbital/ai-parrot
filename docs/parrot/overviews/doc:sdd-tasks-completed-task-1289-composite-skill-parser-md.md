---
type: Wiki Overview
title: 'TASK-1289: Composite Skill Parser — parse_skill_directory()'
id: doc:sdd-tasks-completed-task-1289-composite-skill-parser-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Composite skills are stored as directories with a `SKILL.md` entry point
  plus adjacent
relates_to:
- concept: mod:parrot.skills
  rel: mentions
- concept: mod:parrot.skills.models
  rel: mentions
- concept: mod:parrot.skills.parsers
  rel: mentions
---

# TASK-1289: Composite Skill Parser — parse_skill_directory()

**Feature**: FEAT-188 — Skills Directory Loader + PromptBuilder Integration
**Spec**: `sdd/specs/skill-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1288
**Assigned-to**: unassigned

---

## Context

Composite skills are stored as directories with a `SKILL.md` entry point plus adjacent
asset files (scripts, examples, templates). This task adds `parse_skill_directory()` as a
companion to the existing `parse_skill_file()`, reusing the same frontmatter parser and
setting the `assets_dir` field added in TASK-1288.

Implements: Spec §3 Module 3 (Composite Skill Parser).

---

## Scope

- Add `parse_skill_directory(skill_dir: Path) -> SkillDefinition` to `parrot/skills/parsers.py`.
- The function parses `{skill_dir}/SKILL.md` via existing `parse_skill_file()`.
- Sets `skill.assets_dir = skill_dir` on the returned `SkillDefinition`.
- Raises `FileNotFoundError` if `SKILL.md` is missing in the directory.
- Export from `parrot/skills/__init__.py`.
- Write unit tests covering valid composite, missing SKILL.md, and inherited fields.

**NOT in scope**: `SkillsDirectoryLoader` (TASK-1291), which calls this function.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/skills/parsers.py` | MODIFY | Add `parse_skill_directory()` function |
| `parrot/skills/__init__.py` | MODIFY | Export `parse_skill_directory` |
| `tests/unit/test_skill_parsers.py` | CREATE or MODIFY | Tests for composite parsing |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.skills.parsers import parse_skill_file   # verified: parsers.py:33
from parrot.skills.models import SkillDefinition      # verified: models.py:53
from pathlib import Path
```

### Existing Signatures to Use
```python
# parrot/skills/parsers.py:33 (moved from memory/skills/parsers.py)
def parse_skill_file(file_path: Path) -> SkillDefinition:
    """Parse a .md skill file with YAML frontmatter into a SkillDefinition.
    Raises: ValueError, ValidationError, FileNotFoundError
    """

# parrot/skills/models.py — SkillDefinition (after TASK-1288)
class SkillDefinition(BaseModel):
    name: str
    description: str
    triggers: List[str]
    source: SkillSource = SkillSource.AUTHORED
    template_body: str
    token_count: int
    file_path: Path
    assets_dir: Optional[Path] = None   # added by TASK-1288
```

### Does NOT Exist
- ~~`parse_skill_directory()`~~ — does NOT exist yet. This task creates it.
- ~~`SkillDefinition.content`~~ — field is called `template_body`.

---

## Implementation Notes

### Pattern to Follow
```python
def parse_skill_directory(skill_dir: Path) -> SkillDefinition:
    """Parse a composite skill: {dir}/SKILL.md plus adjacent asset files."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(
            f"Missing SKILL.md in composite skill directory: {skill_dir}"
        )
    skill = parse_skill_file(skill_md)
    skill.assets_dir = skill_dir
    return skill
```

### Key Constraints
- `SkillDefinition` is a Pydantic BaseModel. Setting `skill.assets_dir` after construction
  works if the model is not frozen. Verify this — if frozen, pass `assets_dir` in
  `parse_skill_file` or use `model_copy(update=...)`.
- The function delegates ALL frontmatter parsing to `parse_skill_file()` — no duplication.

---

## Acceptance Criteria

- [ ] `parse_skill_directory(valid_dir)` returns `SkillDefinition` with `assets_dir` set
- [ ] `parse_skill_directory(dir_without_skill_md)` raises `FileNotFoundError`
- [ ] Frontmatter fields (name, description, triggers) are correctly parsed
- [ ] Exported from `parrot.skills`: `from parrot.skills import parse_skill_directory`
- [ ] No linting errors: `ruff check parrot/skills/parsers.py`

---

## Test Specification

```python
# tests/unit/test_skill_parsers.py
import pytest
from pathlib import Path
from parrot.skills.parsers import parse_skill_directory


@pytest.fixture
def composite_skill_dir(tmp_path):
    skill_dir = tmp_path / "extract-pdf"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: extract-pdf\ndescription: Extract tables from PDF\n"
        "triggers: []\n---\nUse camelot to extract tables."
    )
    (skill_dir / "script.py").write_text("# extraction script")
    return skill_dir


def test_parse_skill_directory_valid(composite_skill_dir):
    skill = parse_skill_directory(composite_skill_dir)
    assert skill.name == "extract-pdf"
    assert skill.description == "Extract tables from PDF"
    assert skill.assets_dir == composite_skill_dir


def test_parse_skill_directory_missing_skill_md(tmp_path):
    empty_dir = tmp_path / "no-skill"
    empty_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="Missing SKILL.md"):
        parse_skill_directory(empty_dir)


def test_parse_skill_directory_inherits_fields(composite_skill_dir):
    skill = parse_skill_directory(composite_skill_dir)
    assert skill.template_body == "Use camelot to extract tables."
    assert skill.file_path == composite_skill_dir / "SKILL.md"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/skill-registry.spec.md` for full context
2. **Check dependencies** — verify TASK-1288 is completed (assets_dir field exists)
3. **Verify** that `parse_skill_file` still has the expected signature
4. **Check** whether `SkillDefinition` allows post-construction field assignment or needs `model_copy`
5. **Implement** and test
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-25
**Notes**: parse_skill_directory() added to parsers.py. Exported from __init__.py. SkillDefinition is not frozen so skill.assets_dir = skill_dir works post-construction. 6 tests pass.

**Deviations from spec**: none
