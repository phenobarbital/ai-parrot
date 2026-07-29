---
type: Wiki Overview
title: 'TASK-1292: Skills Prompt Layer Factory — render_skills_prompt_layer()'
id: doc:sdd-tasks-completed-task-1292-prompt-layer-factory-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This is the Tier 1 mechanism: a static `<available_skills>` XML block injected
  into the'
relates_to:
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.skills
  rel: mentions
- concept: mod:parrot.skills.file_registry
  rel: mentions
- concept: mod:parrot.skills.models
  rel: mentions
- concept: mod:parrot.skills.prompt
  rel: mentions
---

# TASK-1292: Skills Prompt Layer Factory — render_skills_prompt_layer()

**Feature**: FEAT-188 — Skills Directory Loader + PromptBuilder Integration
**Spec**: `sdd/specs/skill-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1290
**Assigned-to**: unassigned

---

## Context

This is the Tier 1 mechanism: a static `<available_skills>` XML block injected into the
system prompt so the LLM knows which skills exist without any tool call. The factory
function reads all skills from the registry, builds the XML, and returns an immutable
`PromptLayer` with `phase=RenderPhase.CONFIGURE` (resolved once at boot, zero per-turn cost).

Implements: Spec §3 Module 6 (Skills Prompt Layer Factory).

---

## Scope

- Create `parrot/skills/prompt.py` with `render_skills_prompt_layer()`.
- Function signature: `render_skills_prompt_layer(registry: SkillFileRegistry, max_skills: int | None = None, priority: int = 45) -> PromptLayer`
- The returned `PromptLayer` has:
  - `name="available_skills"`
  - `priority` from parameter (default 45, between USER_SESSION=40 and TOOLS=50)
  - `template` containing the `<available_skills>` XML block
  - `phase=RenderPhase.CONFIGURE` (static, cached)
- Each skill entry in the XML includes name, description, and a `load_skill(name="...")` hint.
- Skills with `triggers:` get an additional "Also triggerable via: /cmd" line.
- If `max_skills` is set and the registry exceeds it, truncate.
- If the registry is empty, return a PromptLayer with an empty template string.
- Export from `parrot/skills/__init__.py`.
- Write unit tests.

**NOT in scope**: Mixin wiring (TASK-1294), LoadSkillTool (TASK-1293).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/skills/prompt.py` | CREATE | `render_skills_prompt_layer()` function |
| `parrot/skills/__init__.py` | MODIFY | Export `render_skills_prompt_layer` |
| `tests/unit/test_skills_prompt_layer.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.skills.file_registry import SkillFileRegistry  # file_registry.py:16
from parrot.skills.models import SkillDefinition            # models.py:53
from parrot.bots.prompts import PromptLayer, RenderPhase    # prompts/__init__.py
```

### Existing Signatures to Use
```python
# parrot/skills/file_registry.py
class SkillFileRegistry:
    def list_skills(self) -> List[SkillDefinition]:  # line 129

# parrot/skills/models.py
class SkillDefinition(BaseModel):
    name: str
    description: str
    triggers: List[str]

# parrot/bots/prompts/layers.py:50
@dataclass(frozen=True)
class PromptLayer:
    name: str                            # line 66
    priority: LayerPriority | int        # line 67
    template: str                        # line 68
    phase: RenderPhase = RenderPhase.REQUEST  # line 69

# parrot/bots/prompts/layers.py:35
class RenderPhase(str, Enum):
    CONFIGURE = "configure"
    REQUEST = "request"
```

### Does NOT Exist
- ~~`render_skills_prompt_layer()`~~ — does NOT exist. This task creates it.
- ~~`parrot/skills/prompt.py`~~ — file does NOT exist. This task creates it.
- ~~`AbstractPromptLayer`~~ — does NOT exist. `PromptLayer` is a frozen dataclass.
- ~~`PromptBuilder.register_layer()`~~ — method is `add()`, not `register_layer()`.

---

## Implementation Notes

### Pattern to Follow
```python
from parrot.bots.prompts import PromptLayer, RenderPhase
from .file_registry import SkillFileRegistry


def render_skills_prompt_layer(
    registry: SkillFileRegistry,
    max_skills: int | None = None,
    priority: int = 45,
) -> PromptLayer:
    """Build a static PromptLayer with an <available_skills> XML index."""
    skills = registry.list_skills()
    if not skills:
        return PromptLayer(
            name="available_skills",
            priority=priority,
            template="",
            phase=RenderPhase.CONFIGURE,
        )

    if max_skills and len(skills) > max_skills:
        skills = skills[:max_skills]

    lines = ["<available_skills>"]
    for s in skills:
        lines.append(f'  <skill name="{s.name}">')
        lines.append(f"    {s.description}")
        lines.append(f'    Load with: load_skill(name="{s.name}")')
        if s.triggers:
            lines.append(f"    Also triggerable via: {', '.join(s.triggers)}")
        lines.append("  </skill>")
    lines.append("</available_skills>")

    return PromptLayer(
        name="available_skills",
        priority=priority,
        template="\n".join(lines),
        phase=RenderPhase.CONFIGURE,
    )
```

### Key Constraints
- `PromptLayer` is frozen — construct it once with all data.
- `phase=RenderPhase.CONFIGURE` makes the layer static (resolved once, cached).
- XML owns structure, Markdown owns content (project convention).
- Priority 45 is between `USER_SESSION` (40) and `TOOLS` (50).

---

## Acceptance Criteria

- [ ] Empty registry → returns PromptLayer with empty template
- [ ] Non-empty registry → XML block contains skill names and descriptions
- [ ] Skills with triggers → include "Also triggerable via" line
- [ ] `max_skills` truncates when set
- [ ] PromptLayer has `phase=RenderPhase.CONFIGURE`
- [ ] PromptLayer has `name="available_skills"`
- [ ] Exported: `from parrot.skills import render_skills_prompt_layer`
- [ ] No linting errors: `ruff check parrot/skills/prompt.py`

---

## Test Specification

```python
# tests/unit/test_skills_prompt_layer.py
import pytest
from pathlib import Path
from parrot.skills.prompt import render_skills_prompt_layer
from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.models import SkillDefinition, SkillSource
from parrot.bots.prompts import RenderPhase


@pytest.fixture
def populated_registry(tmp_path):
    registry = SkillFileRegistry(skills_dir=tmp_path)
    registry.add(SkillDefinition(
        name="summarize", description="Summarize text",
        triggers=["/resumen"], source=SkillSource.AUTHORED,
        template_body="Summarize.", token_count=3, file_path=tmp_path / "s.md",
    ))
    registry.add(SkillDefinition(
        name="extract-pdf", description="Extract tables from PDF",
        triggers=[], source=SkillSource.AUTHORED,
        template_body="Extract.", token_count=3, file_path=tmp_path / "e.md",
    ))
    return registry


def test_render_empty_registry(tmp_path):
    registry = SkillFileRegistry(skills_dir=tmp_path)
    layer = render_skills_prompt_layer(registry)
    assert layer.template == ""
    assert layer.phase == RenderPhase.CONFIGURE


def test_render_basic(populated_registry):
    layer = render_skills_prompt_layer(populated_registry)
    assert "<available_skills>" in layer.template
    assert 'name="summarize"' in layer.template
    assert 'name="extract-pdf"' in layer.template
    assert layer.name == "available_skills"


def test_render_trigger_hint(populated_registry):
    layer = render_skills_prompt_layer(populated_registry)
    assert "Also triggerable via: /resumen" in layer.template
    # extract-pdf has no triggers — no hint line
    lines = layer.template.split("\n")
    extract_section = [l for l in lines if "extract-pdf" in l or "Extract tables" in l]
    for line in extract_section:
        assert "triggerable" not in line


def test_render_max_entries(populated_registry):
    layer = render_skills_prompt_layer(populated_registry, max_skills=1)
    assert layer.template.count("<skill ") == 1


def test_render_phase_is_configure(populated_registry):
    layer = render_skills_prompt_layer(populated_registry)
    assert layer.phase == RenderPhase.CONFIGURE
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/skill-registry.spec.md`
2. **Check dependencies** — verify TASK-1290 is completed
3. **Verify** `PromptLayer` constructor and `RenderPhase.CONFIGURE` are available
4. **Create** `parrot/skills/prompt.py` and tests
5. **Export** from `parrot/skills/__init__.py`
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-25
**Notes**: Created prompt.py with render_skills_prompt_layer(). XML block with skill entries, trigger hints, load_skill() hints. 11 tests pass.

**Deviations from spec**: none | describe if any
