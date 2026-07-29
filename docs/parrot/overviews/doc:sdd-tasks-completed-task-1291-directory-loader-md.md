---
type: Wiki Overview
title: 'TASK-1291: SkillsDirectoryLoader — Filesystem Discovery'
id: doc:sdd-tasks-completed-task-1291-directory-loader-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the core discovery mechanism for FEAT-188. The `SkillsDirectoryLoader`
  scans
relates_to:
- concept: mod:parrot.skills
  rel: mentions
- concept: mod:parrot.skills.file_registry
  rel: mentions
- concept: mod:parrot.skills.loader
  rel: mentions
- concept: mod:parrot.skills.models
  rel: mentions
- concept: mod:parrot.skills.parsers
  rel: mentions
---

# TASK-1291: SkillsDirectoryLoader — Filesystem Discovery

**Feature**: FEAT-188 — Skills Directory Loader + PromptBuilder Integration
**Spec**: `sdd/specs/skill-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1289, TASK-1290
**Assigned-to**: unassigned

---

## Context

This is the core discovery mechanism for FEAT-188. The `SkillsDirectoryLoader` scans
configured filesystem paths and discovers both single-file (`.md`) and composite
(`dir/SKILL.md`) skills. It uses `parse_skill_file()` (existing) and
`parse_skill_directory()` (TASK-1289) for parsing, then hot-adds discovered skills
to a `SkillFileRegistry` via `load_into()`.

Implements: Spec §3 Module 5 (SkillsDirectoryLoader).

---

## Scope

- Create `parrot/skills/loader.py` with the `SkillsDirectoryLoader` class.
- `__init__(paths: list[Path], logger: Logger | None = None)` — resolves and stores paths.
- `async discover() -> list[SkillDefinition]` — scans all paths, returns discovered skills.
  Supports both `{dir}/{name}.md` (single-file) and `{dir}/{name}/SKILL.md` (composite).
  Logs warnings on parse failure; never crashes.
- `async load_into(registry: SkillFileRegistry) -> int` — discovers and hot-adds to registry.
  Returns count of successfully loaded skills.
- Export from `parrot/skills/__init__.py`.
- Write comprehensive unit tests.

**NOT in scope**: Prompt layer creation (TASK-1292), mixin wiring (TASK-1294).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/skills/loader.py` | CREATE | `SkillsDirectoryLoader` class |
| `parrot/skills/__init__.py` | MODIFY | Export `SkillsDirectoryLoader` |
| `tests/unit/test_skills_directory_loader.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.skills.parsers import parse_skill_file       # parsers.py:33
from parrot.skills.parsers import parse_skill_directory   # added by TASK-1289
from parrot.skills.file_registry import SkillFileRegistry # file_registry.py:16
from parrot.skills.models import SkillDefinition          # models.py:53
from pathlib import Path
from logging import Logger
```

### Existing Signatures to Use
```python
# parrot/skills/parsers.py
def parse_skill_file(file_path: Path) -> SkillDefinition:  # line 33
    # Raises: ValueError, ValidationError, FileNotFoundError

# parrot/skills/parsers.py (added by TASK-1289)
def parse_skill_directory(skill_dir: Path) -> SkillDefinition:
    # Raises: FileNotFoundError

# parrot/skills/file_registry.py
class SkillFileRegistry:
    def add(self, skill: SkillDefinition) -> None:  # line 121 — hot-add
```

### Does NOT Exist
- ~~`SkillsDirectoryLoader`~~ — does NOT exist. This task creates it.
- ~~`parrot/skills/loader.py`~~ — file does NOT exist. This task creates it.

---

## Implementation Notes

### Pattern to Follow
```python
class SkillsDirectoryLoader:
    def __init__(self, paths: list[Path], logger: Logger | None = None):
        self._paths = [Path(p).expanduser().resolve() for p in paths]
        self._logger = logger

    async def discover(self) -> list[SkillDefinition]:
        skills: list[SkillDefinition] = []
        for base in self._paths:
            if not base.exists() or not base.is_dir():
                if self._logger:
                    self._logger.debug("Skills path not found: %s", base)
                continue
            for entry in sorted(base.iterdir()):
                try:
                    if entry.is_file() and entry.suffix == ".md":
                        skills.append(parse_skill_file(entry))
                    elif entry.is_dir() and (entry / "SKILL.md").exists():
                        skills.append(parse_skill_directory(entry))
                except Exception as e:
                    if self._logger:
                        self._logger.warning(
                            "Failed to parse skill at %s: %s", entry, e
                        )
        return skills

    async def load_into(self, registry: SkillFileRegistry) -> int:
        skills = await self.discover()
        loaded = 0
        for s in skills:
            try:
                registry.add(s)
                loaded += 1
            except Exception as e:
                if self._logger:
                    self._logger.warning(
                        "Failed to register skill %s: %s", s.name, e
                    )
        return loaded
```

### Key Constraints
- Methods are `async` for consistency with the codebase even though filesystem I/O is sync.
- `sorted(base.iterdir())` ensures deterministic discovery order.
- NEVER crash on parse failure — log warning and continue.
- Skip non-`.md` files and non-skill directories silently.
- Path resolution via `.expanduser().resolve()` handles `~` and relative paths.

---

## Acceptance Criteria

- [ ] Discovers single-file `.md` skills from a directory
- [ ] Discovers composite `dir/SKILL.md` skills from a directory
- [ ] Discovers mixed layouts in the same directory
- [ ] Non-existent path: logs debug, skips, no crash
- [ ] Malformed skill file: logs warning, skips, continues with others
- [ ] `load_into()` returns correct count of loaded skills
- [ ] `load_into()` hot-adds discovered skills to the registry
- [ ] Exported: `from parrot.skills import SkillsDirectoryLoader`
- [ ] No linting errors: `ruff check parrot/skills/loader.py`

---

## Test Specification

```python
# tests/unit/test_skills_directory_loader.py
import pytest
from pathlib import Path
from parrot.skills.loader import SkillsDirectoryLoader
from parrot.skills.file_registry import SkillFileRegistry


@pytest.fixture
def skill_dir(tmp_path):
    # Single-file skill
    (tmp_path / "summarize.md").write_text(
        "---\nname: summarize\ndescription: Summarize text\n"
        "triggers:\n  - /resumen\n---\nSummarize the input."
    )
    # Composite skill
    composite = tmp_path / "extract-pdf"
    composite.mkdir()
    (composite / "SKILL.md").write_text(
        "---\nname: extract-pdf\ndescription: Extract tables\n"
        "triggers: []\n---\nExtract tables from PDF."
    )
    (composite / "script.py").write_text("# script")
    # Non-skill file (should be ignored)
    (tmp_path / "README.txt").write_text("ignore me")
    return tmp_path


@pytest.fixture
def malformed_dir(tmp_path):
    (tmp_path / "bad.md").write_text("no frontmatter here")
    (tmp_path / "good.md").write_text(
        "---\nname: good\ndescription: A good skill\n"
        "triggers: []\n---\nBody."
    )
    return tmp_path


@pytest.mark.asyncio
async def test_discover_single_file(skill_dir):
    loader = SkillsDirectoryLoader(paths=[skill_dir])
    skills = await loader.discover()
    names = {s.name for s in skills}
    assert "summarize" in names


@pytest.mark.asyncio
async def test_discover_composite(skill_dir):
    loader = SkillsDirectoryLoader(paths=[skill_dir])
    skills = await loader.discover()
    names = {s.name for s in skills}
    assert "extract-pdf" in names


@pytest.mark.asyncio
async def test_discover_mixed(skill_dir):
    loader = SkillsDirectoryLoader(paths=[skill_dir])
    skills = await loader.discover()
    assert len(skills) == 2


@pytest.mark.asyncio
async def test_discover_nonexistent_path():
    loader = SkillsDirectoryLoader(paths=[Path("/nonexistent/path")])
    skills = await loader.discover()
    assert skills == []


@pytest.mark.asyncio
async def test_discover_skips_malformed(malformed_dir):
    loader = SkillsDirectoryLoader(paths=[malformed_dir])
    skills = await loader.discover()
    assert len(skills) == 1
    assert skills[0].name == "good"


@pytest.mark.asyncio
async def test_load_into_registry(skill_dir):
    loader = SkillsDirectoryLoader(paths=[skill_dir])
    registry = SkillFileRegistry(skills_dir=skill_dir)
    count = await loader.load_into(registry)
    assert count == 2
    assert len(registry.list_skills()) == 2
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/skill-registry.spec.md`
2. **Check dependencies** — verify TASK-1289 and TASK-1290 are completed
3. **Verify** `parse_skill_file`, `parse_skill_directory`, and `SkillFileRegistry.add` signatures
4. **Create** `parrot/skills/loader.py` and tests
5. **Export** from `parrot/skills/__init__.py`
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-25
**Notes**: Created loader.py with SkillsDirectoryLoader. Exported from __init__.py. 9 tests pass including single-file, composite, mixed, nonexistent path, and malformed file cases.

**Deviations from spec**: none | describe if any
