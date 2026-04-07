# TASK-613: Skill Definition Model & YAML Parser

**Feature**: Agent Skill System
**Spec**: `sdd/specs/agent-skill-system.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Module 1 of FEAT-088. Defines the `SkillDefinition` pydantic model, `SkillSource` enum,
> and a YAML frontmatter parser for `.md` skill files. This is the foundational data model
> that all other modules depend on. See spec Section 3, Module 1.

---

## Scope

- Add `SkillSource` enum (`AUTHORED`, `LEARNED`) to `parrot/memory/skills/models.py`
- Add `SkillDefinition` pydantic `BaseModel` to `parrot/memory/skills/models.py` with fields:
  `name`, `description`, `triggers` (List[str]), `source` (SkillSource), `priority` (int=90),
  `version` (str="1.0"), `category` (Optional[str]), `template_body` (str), `token_count` (int),
  `file_path` (Path), `MAX_TOKENS` (ClassVar[int]=1000)
- Add a `@field_validator` on `token_count` to reject values exceeding `MAX_TOKENS`
- Add a `parse_skill_file(file_path: Path) -> SkillDefinition` function that:
  - Reads a `.md` file, splits YAML frontmatter from body
  - Parses frontmatter fields into `SkillDefinition`
  - Computes token count using `tiktoken` (cl100k_base encoding)
  - Sets `source` based on whether file is in `learned/` subdirectory
- Add `python-frontmatter` to project dependencies (verify first: `uv pip list | grep frontmatter`)
- Export new symbols from `parrot/memory/skills/__init__.py`
- Write unit tests for valid parsing, missing fields, and token limit rejection

**NOT in scope**: SkillFileRegistry (TASK-614), middleware (TASK-615), mixin changes (TASK-616)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/skills/models.py` | MODIFY | Add SkillSource enum, SkillDefinition model |
| `packages/ai-parrot/src/parrot/memory/skills/parsers.py` | CREATE | parse_skill_file() function |
| `packages/ai-parrot/src/parrot/memory/skills/__init__.py` | MODIFY | Export new symbols |
| `packages/ai-parrot/tests/unit/test_skill_definition.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
# Existing models in the same file:
from parrot.memory.skills.models import SkillStatus, SkillCategory, SkillMetadata, ContentType  # verified: models.py:20-66

# For token counting:
import tiktoken  # verified: installed (0.9.0)

# For YAML frontmatter — MUST be installed first (not currently in venv):
# uv add python-frontmatter
import frontmatter  # NOT yet installed — install as part of this task

# Standard:
from pydantic import BaseModel, Field, field_validator
from pathlib import Path
from typing import List, Optional, ClassVar
from enum import Enum
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/skills/models.py:20-25
class SkillStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    REVOKED = "revoked"
    DRAFT = "draft"

# packages/ai-parrot/src/parrot/memory/skills/models.py:28-37
class SkillCategory(str, Enum):
    TOOL_USAGE = "tool_usage"
    WORKFLOW = "workflow"
    DOMAIN_KNOWLEDGE = "domain"
    ERROR_HANDLING = "error_handling"
    USER_PREFERENCE = "user_preference"
    INTEGRATION = "integration"
    OPTIMIZATION = "optimization"
    GENERAL = "general"

# packages/ai-parrot/src/parrot/memory/skills/models.py:46-66
@dataclass
class SkillMetadata:
    name: str
    description: str
    category: SkillCategory = SkillCategory.GENERAL
    tags: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)
    related_tools: List[str] = field(default_factory=list)
```

### Does NOT Exist
- ~~`SkillDefinition`~~ — does not exist yet; MUST be created in this task
- ~~`SkillSource`~~ — does not exist yet; MUST be created in this task
- ~~`parse_skill_file`~~ — does not exist yet; MUST be created in this task
- ~~`python-frontmatter`~~ — NOT installed; must `uv add python-frontmatter`
- ~~`PromptLayer.active`~~ — PromptLayer is frozen, no mutable state
- ~~`LayerPriority.SKILL`~~ — no SKILL priority in IntEnum

---

## Implementation Notes

### Pattern to Follow
```python
# Follow existing enum pattern in models.py
class SkillSource(str, Enum):
    """Origin of the skill."""
    AUTHORED = "authored"
    LEARNED = "learned"

# Follow Pydantic BaseModel pattern
class SkillDefinition(BaseModel):
    """Parsed skill from a .md file with YAML frontmatter."""
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

    @field_validator("token_count")
    @classmethod
    def validate_token_count(cls, v: int) -> int:
        if v > cls.MAX_TOKENS:
            raise ValueError(f"Skill body exceeds {cls.MAX_TOKENS} token limit ({v} tokens)")
        return v
```

### Key Constraints
- Use `tiktoken` with `cl100k_base` encoding for token counting
- YAML frontmatter parsing via `python-frontmatter` library
- Skill body is everything after the YAML frontmatter separator `---`
- `source` is auto-detected: if file_path contains `/learned/` → LEARNED, else AUTHORED

---

## Acceptance Criteria

- [ ] `SkillSource` enum with AUTHORED and LEARNED values
- [ ] `SkillDefinition` model validates all required fields
- [ ] Token count exceeding 1000 raises `ValidationError`
- [ ] `parse_skill_file()` correctly parses valid `.md` skill files
- [ ] `parse_skill_file()` raises on missing required frontmatter fields
- [ ] `python-frontmatter` dependency added to project
- [ ] New symbols exported from `parrot/memory/skills/__init__.py`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_skill_definition.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_skill_definition.py
import pytest
from pathlib import Path
from parrot.memory.skills.models import SkillSource, SkillDefinition
from parrot.memory.skills.parsers import parse_skill_file


VALID_SKILL_MD = """---
name: resumen
description: Resume textos largos en bullet points
triggers:
  - /resumen
source: authored
---

Cuando el usuario solicite un resumen:
1. Identifica las ideas principales
2. Genera bullet points (max 7)
3. Manten el tono original
"""


class TestSkillSource:
    def test_authored_value(self):
        assert SkillSource.AUTHORED == "authored"

    def test_learned_value(self):
        assert SkillSource.LEARNED == "learned"


class TestSkillDefinition:
    def test_valid_definition(self):
        sd = SkillDefinition(
            name="resumen",
            description="Resume textos",
            triggers=["/resumen"],
            template_body="Do X",
            token_count=10,
            file_path=Path("/tmp/resumen.md"),
        )
        assert sd.name == "resumen"
        assert sd.source == SkillSource.AUTHORED
        assert sd.priority == 90

    def test_token_limit_exceeded(self):
        with pytest.raises(Exception, match="token limit"):
            SkillDefinition(
                name="big",
                description="Too big",
                triggers=["/big"],
                template_body="x" * 5000,
                token_count=1500,
                file_path=Path("/tmp/big.md"),
            )

    def test_missing_required_fields(self):
        with pytest.raises(Exception):
            SkillDefinition(name="x")


class TestParseSkillFile:
    def test_parse_valid_file(self, tmp_path):
        f = tmp_path / "resumen.md"
        f.write_text(VALID_SKILL_MD)
        skill = parse_skill_file(f)
        assert skill.name == "resumen"
        assert "/resumen" in skill.triggers
        assert skill.token_count > 0
        assert skill.source == SkillSource.AUTHORED

    def test_parse_learned_file(self, tmp_path):
        learned = tmp_path / "learned"
        learned.mkdir()
        f = learned / "skill.md"
        f.write_text(VALID_SKILL_MD)
        skill = parse_skill_file(f)
        assert skill.source == SkillSource.LEARNED

    def test_parse_missing_fields(self, tmp_path):
        f = tmp_path / "bad.md"
        f.write_text("---\nname: x\n---\nbody")
        with pytest.raises(Exception):
            parse_skill_file(f)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agent-skill-system.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Install dependency**: `source .venv/bin/activate && uv add python-frontmatter`
5. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-613-skill-definition-model.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
