# TASK-614: Skill File Registry

**Feature**: Agent Skill System
**Spec**: `sdd/specs/agent-skill-system.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-613
**Assigned-to**: unassigned

---

## Context

> Module 2 of FEAT-088. Implements `SkillFileRegistry` — a filesystem-based skill registry
> that eagerly loads `.md` skill files from `AGENTS_DIR/{agent_id}/skills/` (authored) and
> `skills/learned/` (LLM-generated), validates them, and indexes them by trigger name.
> See spec Section 3, Module 2.

---

## Scope

- Create `SkillFileRegistry` class in `parrot/memory/skills/file_registry.py` with:
  - `__init__(self, skills_dir: Path, learned_dir: Optional[Path] = None)`
  - `async def load() -> None` — scans both directories, parses each `.md` file via `parse_skill_file()`, builds trigger→SkillDefinition dict
  - `def get(self, trigger: str) -> Optional[SkillDefinition]` — lookup by trigger name
  - `def add(self, skill: SkillDefinition) -> None` — hot-add a skill (for learned skills)
  - `def list_skills(self) -> List[SkillDefinition]` — return all loaded skills
  - `def has_trigger(self, trigger: str) -> bool` — check if trigger exists
- Handle edge cases:
  - Malformed files: log warning via `self.logger`, skip
  - Name collisions between authored and learned: log error, skip both
  - Empty directories: empty registry, no errors
  - Missing directories: no errors
- Use `asyncio.Lock` for thread-safe hot-add
- Export from `parrot/memory/skills/__init__.py`
- Write unit tests

**NOT in scope**: middleware (TASK-615), mixin integration (TASK-616), tool adaptation (TASK-617)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/skills/file_registry.py` | CREATE | SkillFileRegistry class |
| `packages/ai-parrot/src/parrot/memory/skills/__init__.py` | MODIFY | Export SkillFileRegistry |
| `packages/ai-parrot/tests/unit/test_skill_file_registry.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From TASK-613 (must be completed first):
from parrot.memory.skills.models import SkillDefinition, SkillSource  # created in TASK-613
from parrot.memory.skills.parsers import parse_skill_file  # created in TASK-613

# Standard library:
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional
```

### Existing Signatures to Use
```python
# From TASK-613 (SkillDefinition model):
class SkillDefinition(BaseModel):
    name: str
    description: str
    triggers: List[str]
    source: SkillSource
    priority: int = 90
    template_body: str
    token_count: int
    file_path: Path
    MAX_TOKENS: ClassVar[int] = 1000

# parse_skill_file (created in TASK-613):
def parse_skill_file(file_path: Path) -> SkillDefinition: ...
```

### Does NOT Exist
- ~~`SkillFileRegistry`~~ — does not exist yet; MUST be created in this task
- ~~`SkillRegistryMixin.load_from_files()`~~ — no such method
- ~~`SkillRegistryMixin._skill_file_registry`~~ — does not exist yet (TASK-616)

---

## Implementation Notes

### Pattern to Follow
```python
class SkillFileRegistry:
    """Filesystem-based skill registry with eager loading."""

    def __init__(self, skills_dir: Path, learned_dir: Optional[Path] = None) -> None:
        self.skills_dir = skills_dir
        self.learned_dir = learned_dir or skills_dir / "learned"
        self._skills: Dict[str, SkillDefinition] = {}  # trigger → skill
        self._by_name: Dict[str, SkillDefinition] = {}  # name → skill
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    async def load(self) -> None:
        """Eagerly load all .md skill files from both directories."""
        ...

    def get(self, trigger: str) -> Optional[SkillDefinition]:
        return self._skills.get(trigger)

    def add(self, skill: SkillDefinition) -> None:
        """Hot-add a skill. Used for learned skills saved during session."""
        ...

    def list_skills(self) -> List[SkillDefinition]:
        return list(self._by_name.values())

    def has_trigger(self, trigger: str) -> bool:
        return trigger in self._skills
```

### Key Constraints
- Malformed files → warning + skip (never raise)
- Name collision (same name in authored + learned) → error log, skip both
- Trigger collision → error log, skip the later one
- `load()` is async for consistency even though filesystem I/O is sync
- Use `self.logger` for all warnings/errors

---

## Acceptance Criteria

- [ ] `SkillFileRegistry` loads authored `.md` files from `skills_dir`
- [ ] `SkillFileRegistry` loads learned `.md` files from `skills_dir/learned/`
- [ ] `get("/trigger")` returns correct `SkillDefinition`
- [ ] `get("/unknown")` returns `None`
- [ ] Malformed files emit warning and are skipped
- [ ] Name collisions between authored and learned emit error, both skipped
- [ ] `add()` makes skill immediately available via `get()`
- [ ] `list_skills()` returns all loaded skills
- [ ] Empty/missing directories produce empty registry, no errors
- [ ] Exported from `parrot/memory/skills/__init__.py`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_skill_file_registry.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_skill_file_registry.py
import pytest
from pathlib import Path
from parrot.memory.skills.file_registry import SkillFileRegistry
from parrot.memory.skills.models import SkillDefinition, SkillSource

VALID_SKILL = """---
name: resumen
description: Resume textos largos
triggers:
  - /resumen
---

Identifica ideas principales y genera bullet points.
"""

VALID_SKILL_2 = """---
name: traductor
description: Traduce texto
triggers:
  - /traducir
  - /translate
---

Traduce el texto al idioma solicitado.
"""


@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "learned").mkdir()
    return d


class TestSkillFileRegistry:
    @pytest.mark.asyncio
    async def test_load_authored(self, skills_dir):
        (skills_dir / "resumen.md").write_text(VALID_SKILL)
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        assert reg.get("/resumen") is not None
        assert reg.get("/resumen").source == SkillSource.AUTHORED

    @pytest.mark.asyncio
    async def test_load_learned(self, skills_dir):
        (skills_dir / "learned" / "resumen.md").write_text(VALID_SKILL)
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        skill = reg.get("/resumen")
        assert skill is not None
        assert skill.source == SkillSource.LEARNED

    @pytest.mark.asyncio
    async def test_skip_malformed(self, skills_dir):
        (skills_dir / "bad.md").write_text("no frontmatter here")
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        assert reg.list_skills() == []

    @pytest.mark.asyncio
    async def test_name_collision(self, skills_dir):
        (skills_dir / "resumen.md").write_text(VALID_SKILL)
        (skills_dir / "learned" / "resumen.md").write_text(VALID_SKILL)
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        assert reg.get("/resumen") is None  # both skipped

    @pytest.mark.asyncio
    async def test_trigger_lookup(self, skills_dir):
        (skills_dir / "traductor.md").write_text(VALID_SKILL_2)
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        assert reg.get("/traducir") is not None
        assert reg.get("/translate") is not None
        assert reg.get("/unknown") is None

    @pytest.mark.asyncio
    async def test_hot_add(self, skills_dir):
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        skill = SkillDefinition(
            name="nuevo",
            description="Test",
            triggers=["/nuevo"],
            template_body="body",
            token_count=5,
            file_path=Path("/tmp/nuevo.md"),
        )
        reg.add(skill)
        assert reg.get("/nuevo") is not None

    @pytest.mark.asyncio
    async def test_list_skills(self, skills_dir):
        (skills_dir / "resumen.md").write_text(VALID_SKILL)
        (skills_dir / "traductor.md").write_text(VALID_SKILL_2)
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        assert len(reg.list_skills()) == 2

    @pytest.mark.asyncio
    async def test_empty_dir(self, skills_dir):
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        assert reg.list_skills() == []

    @pytest.mark.asyncio
    async def test_missing_dir(self, tmp_path):
        reg = SkillFileRegistry(tmp_path / "nonexistent")
        await reg.load()
        assert reg.list_skills() == []
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agent-skill-system.spec.md` for full context
2. **Check dependencies** — verify TASK-613 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `SkillDefinition`, `SkillSource`, and `parse_skill_file` exist from TASK-613
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-614-skill-file-registry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
