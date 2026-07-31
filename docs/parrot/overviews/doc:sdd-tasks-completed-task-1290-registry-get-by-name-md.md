---
type: Wiki Overview
title: 'TASK-1290: SkillFileRegistry Extension — Add get_by_name()'
id: doc:sdd-tasks-completed-task-1290-registry-get-by-name-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: currently has a private `_by_name` dict but no public accessor. This task
  adds the
relates_to:
- concept: mod:parrot.skills.file_registry
  rel: mentions
- concept: mod:parrot.skills.models
  rel: mentions
---

# TASK-1290: SkillFileRegistry Extension — Add get_by_name()

**Feature**: FEAT-188 — Skills Directory Loader + PromptBuilder Integration
**Spec**: `sdd/specs/skill-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1287
**Assigned-to**: unassigned

---

## Context

`LoadSkillTool` (TASK-1293) needs to look up skills by name. The `SkillFileRegistry`
currently has a private `_by_name` dict but no public accessor. This task adds the
missing `get_by_name()` method.

Implements: Spec §3 Module 4 (SkillFileRegistry Extension).

---

## Scope

- Add `get_by_name(self, name: str) -> Optional[SkillDefinition]` to `SkillFileRegistry`.
- The method wraps the existing `self._by_name` dict lookup.
- Write unit tests for found and not-found cases.

**NOT in scope**: `SkillsDirectoryLoader` (TASK-1291), `LoadSkillTool` (TASK-1293).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/skills/file_registry.py` | MODIFY | Add `get_by_name()` method |
| `tests/unit/test_skill_file_registry.py` | CREATE or MODIFY | Tests for name lookup |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.skills.file_registry import SkillFileRegistry  # after TASK-1287
from parrot.skills.models import SkillDefinition
```

### Existing Signatures to Use
```python
# parrot/skills/file_registry.py (moved from memory/skills/file_registry.py:16)
class SkillFileRegistry:
    def __init__(self, skills_dir: Path, learned_dir: Optional[Path] = None) -> None:
        self._by_name: Dict[str, SkillDefinition] = {}   # line 36 — private name index
    def get(self, trigger: str) -> Optional[SkillDefinition]:  # line 110 — by trigger
    def add(self, skill: SkillDefinition) -> None:             # line 121 — hot-add
    def list_skills(self) -> List[SkillDefinition]:            # line 129
    def _register(self, skill: SkillDefinition) -> None:       # line 88
```

### Does NOT Exist
- ~~`SkillFileRegistry.get_by_name()`~~ — does NOT exist. This task creates it.
- ~~`SkillFileRegistry.find()`~~ — does not exist.
- ~~`SkillFileRegistry.lookup()`~~ — does not exist.

---

## Implementation Notes

### Pattern to Follow
```python
def get_by_name(self, name: str) -> Optional[SkillDefinition]:
    """Look up a skill by its name.

    Args:
        name: The skill name as declared in frontmatter.

    Returns:
        The matching SkillDefinition or None.
    """
    return self._by_name.get(name)
```

### Key Constraints
- Follow the same style as the existing `get(trigger)` method (line 110).
- Add docstring with Args/Returns per Google style.
- This is a simple dict lookup — no async needed.

---

## Acceptance Criteria

- [ ] `registry.get_by_name("known-skill")` returns the `SkillDefinition`
- [ ] `registry.get_by_name("unknown")` returns `None`
- [ ] Method is public (no underscore prefix)
- [ ] No linting errors: `ruff check parrot/skills/file_registry.py`
- [ ] Existing tests still pass

---

## Test Specification

```python
# tests/unit/test_skill_file_registry.py
import pytest
from pathlib import Path
from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.models import SkillDefinition, SkillSource


@pytest.fixture
def registry_with_skill(tmp_path):
    registry = SkillFileRegistry(skills_dir=tmp_path)
    skill = SkillDefinition(
        name="test-skill", description="A test skill",
        triggers=["/test"], source=SkillSource.AUTHORED,
        template_body="Do the thing.", token_count=5,
        file_path=tmp_path / "test-skill.md",
    )
    registry.add(skill)
    return registry


def test_get_by_name_found(registry_with_skill):
    result = registry_with_skill.get_by_name("test-skill")
    assert result is not None
    assert result.name == "test-skill"


def test_get_by_name_not_found(registry_with_skill):
    result = registry_with_skill.get_by_name("nonexistent")
    assert result is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/skill-registry.spec.md`
2. **Check dependencies** — verify TASK-1287 is completed
3. **Verify** that `SkillFileRegistry._by_name` still exists as a private dict
4. **Implement** `get_by_name()` and tests
5. **Move this file** to `sdd/tasks/completed/`
6. **Update index** → `"done"`

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-25
**Notes**: Added get_by_name() wrapping _by_name dict. 4 tests pass.

**Deviations from spec**: none
