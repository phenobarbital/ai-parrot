---
type: Wiki Overview
title: 'TASK-1288: SkillDefinition Model Extension — Add assets_dir Field'
id: doc:sdd-tasks-completed-task-1288-model-extension-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Composite skills (directory-based with `SKILL.md` + adjacent assets) need
  a way to
relates_to:
- concept: mod:parrot.skills.models
  rel: mentions
---

# TASK-1288: SkillDefinition Model Extension — Add assets_dir Field

**Feature**: FEAT-188 — Skills Directory Loader + PromptBuilder Integration
**Spec**: `sdd/specs/skill-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1287
**Assigned-to**: unassigned

---

## Context

Composite skills (directory-based with `SKILL.md` + adjacent assets) need a way to
track their filesystem location. This task adds an `assets_dir` field to `SkillDefinition`
so downstream components (`LoadSkillTool`, `parse_skill_directory`) can reference the
skill's asset directory.

Implements: Spec §3 Module 2 (SkillDefinition Model Extension).

---

## Scope

- Add `assets_dir: Optional[Path] = None` field to the `SkillDefinition` Pydantic model
  in `parrot/skills/models.py`.
- Add a brief docstring/Field description.
- Write a unit test confirming the field defaults to `None` and accepts a `Path`.

**NOT in scope**: `parse_skill_directory()` (TASK-1289), `LoadSkillTool` (TASK-1293).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/skills/models.py` | MODIFY | Add `assets_dir` field to `SkillDefinition` |
| `tests/unit/test_skill_models.py` | CREATE or MODIFY | Test `assets_dir` field |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.skills.models import SkillDefinition  # after TASK-1287 namespace promotion
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
```

### Existing Signatures to Use
```python
# parrot/skills/models.py (moved from parrot/memory/skills/models.py:53)
class SkillDefinition(BaseModel):
    name: str
    description: str
    triggers: List[str]
    source: SkillSource = SkillSource.AUTHORED
    priority: int = 90
    version: str = "1.0"
    category: Optional[str] = None
    template_body: str
    token_count: int
    file_path: Path
    MAX_TOKENS: ClassVar[int] = 1000
```

### Does NOT Exist
- ~~`SkillDefinition.assets_dir`~~ — does NOT exist yet. This task adds it.
- ~~`SkillDefinition.content`~~ — field is called `template_body`, NOT `content`.
- ~~`SkillDefinition.body`~~ — field is called `template_body`, NOT `body`.

---

## Implementation Notes

### Pattern to Follow
```python
# Add after `file_path: Path` in SkillDefinition:
assets_dir: Optional[Path] = Field(
    default=None,
    description="Filesystem dir for composite skills; None for single-file."
)
```

### Key Constraints
- `SkillDefinition` is a Pydantic `BaseModel` — adding an optional field with a default
  is backward-compatible (no migration needed).
- Existing serialization (`to_dict()` is not on SkillDefinition — it's a Pydantic model,
  so `.model_dump()` / `.dict()` will include the new field automatically).

---

## Acceptance Criteria

- [ ] `SkillDefinition` has `assets_dir: Optional[Path]` field
- [ ] Default is `None`
- [ ] Accepts a `Path` value when provided
- [ ] Existing tests still pass (backward compatible)
- [ ] No linting errors: `ruff check parrot/skills/models.py`

---

## Test Specification

```python
# tests/unit/test_skill_models.py
from pathlib import Path
from parrot.skills.models import SkillDefinition


def test_skill_definition_assets_dir_default():
    skill = SkillDefinition(
        name="test", description="desc", triggers=[],
        template_body="body", token_count=5, file_path=Path("/tmp/test.md"),
    )
    assert skill.assets_dir is None


def test_skill_definition_assets_dir_set():
    skill = SkillDefinition(
        name="test", description="desc", triggers=[],
        template_body="body", token_count=5, file_path=Path("/tmp/test.md"),
        assets_dir=Path("/tmp/my-skill/"),
    )
    assert skill.assets_dir == Path("/tmp/my-skill/")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/skill-registry.spec.md` for full context
2. **Check dependencies** — verify TASK-1287 is completed
3. **Verify the Codebase Contract** — confirm `SkillDefinition` still matches the signature above
4. **Implement** the field addition and tests
5. **Verify** all acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-25
**Notes**: Added assets_dir: Optional[Path] = Field(default=None, ...) to SkillDefinition. Backward compatible. 4 tests pass.

**Deviations from spec**: none
