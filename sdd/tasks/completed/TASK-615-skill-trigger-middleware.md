# TASK-615: Skill Trigger Middleware

**Feature**: Agent Skill System
**Spec**: `sdd/specs/agent-skill-system.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-613, TASK-614
**Assigned-to**: unassigned

---

## Context

> Module 3 of FEAT-088. Creates the `SkillTriggerMiddleware` — a `PromptMiddleware` factory
> function that detects `/trigger` patterns at the start of user messages, strips the prefix,
> stores the activated `SkillDefinition` on the bot instance, and handles reserved `/skills`
> and `/help` triggers. See spec Section 3, Module 3.

---

## Scope

- Create `create_skill_trigger_middleware()` factory function in `parrot/memory/skills/middleware.py`
- The factory returns a `PromptMiddleware` instance whose `transform` function:
  1. Checks if message starts with `/`
  2. Extracts the trigger word (everything from `/` to first space, or end of string)
  3. If trigger matches a skill in `SkillFileRegistry`: strips prefix, sets `bot._active_skill`, returns cleaned query
  4. If trigger is `/skills` or `/help`: returns a formatted listing of available skills
  5. If trigger is unknown: passes message through unchanged (including the `/`)
- Handle edge cases:
  - `/trigger` with no text after → empty query, skill still activated
  - `/compound_name data` → correctly splits trigger from text
  - `/skills` returns formatted skill listing
- Export from `parrot/memory/skills/__init__.py`
- Write unit tests

**NOT in scope**: `_active_skill` attribute on mixin (TASK-616), prompt injection (TASK-616)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/skills/middleware.py` | CREATE | Factory function for SkillTriggerMiddleware |
| `packages/ai-parrot/src/parrot/memory/skills/__init__.py` | MODIFY | Export create_skill_trigger_middleware |
| `packages/ai-parrot/tests/unit/test_skill_trigger_middleware.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Prompt middleware infrastructure:
from parrot.bots.middleware import PromptMiddleware  # verified: middleware.py:7-20

# From TASK-613/614:
from parrot.memory.skills.models import SkillDefinition  # created in TASK-613
from parrot.memory.skills.file_registry import SkillFileRegistry  # created in TASK-614

# Standard:
from typing import Any, Dict
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/middleware.py:7-20
@dataclass
class PromptMiddleware:
    name: str
    priority: int = 0                                      # line 11
    transform: Callable[[str, Dict[str, Any]], Awaitable[str]] = None  # line 12
    enabled: bool = True                                   # line 15
    async def apply(self, query: str, context: Dict[str, Any]) -> str:  # line 17

# SkillFileRegistry (created in TASK-614):
class SkillFileRegistry:
    def get(self, trigger: str) -> Optional[SkillDefinition]: ...
    def list_skills(self) -> List[SkillDefinition]: ...
    def has_trigger(self, trigger: str) -> bool: ...
```

### Does NOT Exist
- ~~`SkillTriggerMiddleware`~~ — does not exist as a class; use factory function returning `PromptMiddleware`
- ~~`bot._active_skill`~~ — does not exist yet on any bot class; the middleware sets it via `setattr`
- ~~`PromptPipeline.context`~~ — pipeline does NOT store/share context between middleware and builder
- ~~`PromptMiddleware.bot`~~ — no bot reference on PromptMiddleware; use closure to capture bot ref

---

## Implementation Notes

### Pattern to Follow
```python
def create_skill_trigger_middleware(
    registry: SkillFileRegistry,
    bot: "AbstractBot",
    priority: int = -10,  # Run early, before other middleware
) -> PromptMiddleware:
    """Create a PromptMiddleware that detects /trigger patterns."""

    async def transform(query: str, context: Dict[str, Any]) -> str:
        if not query or not query.startswith("/"):
            return query

        # Split trigger from remaining text
        parts = query.split(None, 1)  # maxsplit=1
        trigger = parts[0]
        remaining = parts[1] if len(parts) > 1 else ""

        # Reserved triggers
        if trigger in ("/skills", "/help"):
            skills = registry.list_skills()
            if not skills:
                return "No skills available."
            listing = "\n".join(
                f"- {', '.join(s.triggers)}: {s.description}"
                for s in skills
            )
            return f"Available skills:\n{listing}"

        # Skill lookup
        skill = registry.get(trigger)
        if skill is not None:
            bot._active_skill = skill  # Set via closure reference
            return remaining

        # Unknown trigger — pass through unchanged
        return query

    return PromptMiddleware(
        name="skill_trigger",
        priority=priority,
        transform=transform,
    )
```

### Key Constraints
- Factory function pattern — closure captures `registry` and `bot` references
- The bot reference is used to set `_active_skill` attribute (not thread-safe, acceptable per spec)
- Priority should be low (e.g., -10) so this middleware runs before others
- `/skills` and `/help` are reserved — they return a listing, NOT activate a skill
- Unknown triggers pass through unchanged (the `/` is preserved)

---

## Acceptance Criteria

- [ ] `/resumen doc Q4` → strips prefix, sets `bot._active_skill`, returns `"doc Q4"`
- [ ] Normal message passes through unchanged
- [ ] `/unknown text` passes through unchanged (including `/`)
- [ ] `/resumen` with no text → empty query, skill still activated
- [ ] `/skills` returns formatted skill listing
- [ ] `/help` returns formatted skill listing
- [ ] `/analisis_financiero data` correctly splits trigger from text
- [ ] Exported from `parrot/memory/skills/__init__.py`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_skill_trigger_middleware.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_skill_trigger_middleware.py
import pytest
from unittest.mock import MagicMock
from pathlib import Path
from parrot.memory.skills.middleware import create_skill_trigger_middleware
from parrot.memory.skills.models import SkillDefinition, SkillSource
from parrot.memory.skills.file_registry import SkillFileRegistry


@pytest.fixture
def sample_skill():
    return SkillDefinition(
        name="resumen",
        description="Resume textos",
        triggers=["/resumen"],
        template_body="Genera bullet points",
        token_count=10,
        file_path=Path("/tmp/resumen.md"),
    )


@pytest.fixture
def compound_skill():
    return SkillDefinition(
        name="analisis_financiero",
        description="Analisis financiero",
        triggers=["/analisis_financiero"],
        template_body="Analiza datos financieros",
        token_count=10,
        file_path=Path("/tmp/analisis.md"),
    )


@pytest.fixture
async def registry_with_skills(tmp_path, sample_skill, compound_skill):
    reg = SkillFileRegistry(tmp_path)
    await reg.load()
    reg.add(sample_skill)
    reg.add(compound_skill)
    return reg


@pytest.fixture
def mock_bot():
    return MagicMock()


class TestSkillTriggerMiddleware:
    @pytest.mark.asyncio
    async def test_detects_trigger(self, registry_with_skills, mock_bot):
        mw = create_skill_trigger_middleware(registry_with_skills, mock_bot)
        result = await mw.apply("/resumen doc Q4", {})
        assert result == "doc Q4"
        assert mock_bot._active_skill.name == "resumen"

    @pytest.mark.asyncio
    async def test_no_trigger(self, registry_with_skills, mock_bot):
        mw = create_skill_trigger_middleware(registry_with_skills, mock_bot)
        result = await mw.apply("normal message", {})
        assert result == "normal message"

    @pytest.mark.asyncio
    async def test_unknown_trigger(self, registry_with_skills, mock_bot):
        mw = create_skill_trigger_middleware(registry_with_skills, mock_bot)
        result = await mw.apply("/unknown text", {})
        assert result == "/unknown text"

    @pytest.mark.asyncio
    async def test_trigger_only(self, registry_with_skills, mock_bot):
        mw = create_skill_trigger_middleware(registry_with_skills, mock_bot)
        result = await mw.apply("/resumen", {})
        assert result == ""
        assert mock_bot._active_skill.name == "resumen"

    @pytest.mark.asyncio
    async def test_reserved_skills(self, registry_with_skills, mock_bot):
        mw = create_skill_trigger_middleware(registry_with_skills, mock_bot)
        result = await mw.apply("/skills", {})
        assert "resumen" in result.lower()
        assert "Available" in result or "available" in result

    @pytest.mark.asyncio
    async def test_compound_name(self, registry_with_skills, mock_bot):
        mw = create_skill_trigger_middleware(registry_with_skills, mock_bot)
        result = await mw.apply("/analisis_financiero data Q1", {})
        assert result == "data Q1"
        assert mock_bot._active_skill.name == "analisis_financiero"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agent-skill-system.spec.md` for full context
2. **Check dependencies** — verify TASK-613 and TASK-614 are in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `PromptMiddleware` signature, `SkillFileRegistry`, `SkillDefinition`
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-615-skill-trigger-middleware.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
