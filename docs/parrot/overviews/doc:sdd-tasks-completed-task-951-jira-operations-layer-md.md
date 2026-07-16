---
type: Wiki Overview
title: 'TASK-951: Extract JIRA_OPERATIONS_LAYER from monolithic prompt'
id: doc:sdd-tasks-completed-task-951-jira-operations-layer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The existing `JIRA_SPECIALIST_PROMPT` is a ~310-line monolithic string constant
relates_to:
- concept: mod:parrot.bots.prompts.domain_layers
  rel: mentions
- concept: mod:parrot.bots.prompts.layers
  rel: mentions
---

# TASK-951: Extract JIRA_OPERATIONS_LAYER from monolithic prompt

**Feature**: FEAT-139 — Jira Analyst System Prompt Hardening
**Spec**: `sdd/specs/jira-analyst-systemprompt-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-950
**Assigned-to**: unassigned

---

## Context

The existing `JIRA_SPECIALIST_PROMPT` is a ~310-line monolithic string constant
in `jira_specialist.py` (lines 152-461). To migrate JiraSpecialist to the
composable `PromptBuilder` system, the operational rules (standup flow, assignment
intake, interaction patterns, cancellation rule, fresh-turn rule, ask_human
examples) must be extracted into a `PromptLayer`.

This task creates `JIRA_OPERATIONS_LAYER` — a `CUSTOM`-priority layer containing
the full operational prompt text. The text is preserved as-is; it is just moved
from a monolithic string into a composable layer.

Implements spec Module 2 (JIRA_OPERATIONS_LAYER).

---

## Scope

- Extract the full operational rules from `JIRA_SPECIALIST_PROMPT` (lines 152-461)
  into a new `JIRA_OPERATIONS_LAYER` PromptLayer in `domain_layers.py`
- The layer text must preserve ALL existing prompt content:
  - Default posture ("act, then report")
  - Fresh-turn rule
  - Cancellation rule (hard stop)
  - Mandatory human interaction rules
  - Daily standup flow (morning, mid-day, assignment intake, EOD)
  - Escalation rules
  - `ask_human` interaction type examples and heuristic
  - General behavior rules
- Register in `_DOMAIN_LAYERS` dict
- Write unit tests verifying key rules are present

**NOT in scope**: JiraSpecialist migration (TASK-952), modifying the prompt text
content, adding new rules.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` | MODIFY | Add JIRA_OPERATIONS_LAYER + register |
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | READ ONLY | Source of JIRA_SPECIALIST_PROMPT text — do NOT modify yet |
| `packages/ai-parrot/tests/test_jira_operations_layer.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase
# verified: packages/ai-parrot/src/parrot/bots/prompts/layers.py:22,35,50

from parrot.bots.prompts.domain_layers import get_domain_layer
# verified: packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:183
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/prompts/layers.py
class LayerPriority(IntEnum):  # line 22
    CUSTOM = 80

class RenderPhase(str, Enum):  # line 35
    CONFIGURE = "configure"

@dataclass(frozen=True)
class PromptLayer:  # line 50
    name: str
    priority: LayerPriority | int
    template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None

# packages/ai-parrot/src/parrot/bots/jira_specialist.py
# Source text to extract (lines 152-461):
JIRA_SPECIALIST_PROMPT = """\
You are **JiraSpecialist**, an autonomous agent that manages Jira tickets
and runs the daily standup on behalf of the engineering team. ...
"""
# This is the FULL text to be moved into the layer template.

# packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py
_DOMAIN_LAYERS: Dict[str, PromptLayer] = { ... }  # line 172
```

### Does NOT Exist
- ~~`JIRA_OPERATIONS_LAYER`~~ — does not exist yet; this task creates it
- ~~`LayerPriority.JIRA`~~ — no such enum member; use `LayerPriority.CUSTOM` (= 80)
- ~~`PromptBuilder.jira()`~~ — no Jira-specific factory method

---

## Implementation Notes

### Pattern to Follow
```python
# The operations layer wraps the full JIRA_SPECIALIST_PROMPT text
# in XML tags at CUSTOM priority
JIRA_OPERATIONS_LAYER = PromptLayer(
    name="jira_operations",
    priority=LayerPriority.CUSTOM,
    phase=RenderPhase.CONFIGURE,
    template="""<jira_operations>
... (full text from JIRA_SPECIALIST_PROMPT lines 152-461) ...
</jira_operations>""",
)
```

### Key Constraints
- Use `RenderPhase.CONFIGURE` — content is static
- Priority must be `LayerPriority.CUSTOM` (= 80)
- The prompt text contains `$` characters in code examples (e.g., `$date`).
  Since `PromptLayer` uses `string.Template.safe_substitute()`, any `$word`
  patterns in the text that are NOT intended as template variables will be
  left as-is by `safe_substitute` (it only replaces known keys). However,
  to be safe, escape any `$` that should be literal by doubling it (`$$`),
  OR verify that no `$word` in the prompt matches a context variable name.
  The safest approach: read the existing configure context keys
  (name, role, goal, backstory, rationale, etc. from `abstract.py:876-896`)
  and ensure no prompt text accidentally matches.
- Do NOT strip the first line "You are **JiraSpecialist**..." — this moves
  to the layer. The IDENTITY_LAYER provides the generic identity; the
  operations layer provides the Jira-specific identity and instructions.
- Wrap in `<jira_operations>...</jira_operations>` XML tags
- Register as `"jira_operations"` in `_DOMAIN_LAYERS`

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/jira_specialist.py:152-461` — source text
- `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:172` — registry
- `packages/ai-parrot/src/parrot/bots/abstract.py:876-896` — configure context keys

---

## Acceptance Criteria

- [ ] `JIRA_OPERATIONS_LAYER` is defined in `domain_layers.py`
- [ ] Layer name is `"jira_operations"`, priority is 80, phase is CONFIGURE
- [ ] Template contains ALL existing operational rules from `JIRA_SPECIALIST_PROMPT`
- [ ] Fresh-turn rule is present in template
- [ ] Cancellation rule is present in template
- [ ] Mandatory human interaction rules are present
- [ ] Daily standup flow is present
- [ ] ask_human interaction examples are present
- [ ] Layer is registered in `_DOMAIN_LAYERS` dict
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_jira_operations_layer.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_jira_operations_layer.py
import pytest
from parrot.bots.prompts.domain_layers import (
    JIRA_OPERATIONS_LAYER,
    get_domain_layer,
)
from parrot.bots.prompts.layers import LayerPriority, RenderPhase


class TestJiraOperationsLayer:
    def test_layer_exists(self):
        assert JIRA_OPERATIONS_LAYER is not None

    def test_layer_name(self):
        assert JIRA_OPERATIONS_LAYER.name == "jira_operations"

    def test_layer_priority(self):
        assert JIRA_OPERATIONS_LAYER.priority == LayerPriority.CUSTOM

    def test_layer_phase(self):
        assert JIRA_OPERATIONS_LAYER.phase == RenderPhase.CONFIGURE

    def test_layer_renders(self):
        rendered = JIRA_OPERATIONS_LAYER.render({})
        assert rendered is not None
        assert "jira_operations" in rendered

    def test_fresh_turn_rule(self):
        rendered = JIRA_OPERATIONS_LAYER.render({})
        assert "Fresh-turn rule" in rendered or "fresh, standalone task" in rendered

    def test_cancellation_rule(self):
        rendered = JIRA_OPERATIONS_LAYER.render({})
        assert "Cancellation rule" in rendered or "Operación cancelada" in rendered

    def test_mandatory_human_interaction(self):
        rendered = JIRA_OPERATIONS_LAYER.render({})
        assert "Mandatory human interaction" in rendered or "Never close" in rendered

    def test_standup_flow(self):
        rendered = JIRA_OPERATIONS_LAYER.render({})
        assert "Daily standup" in rendered or "Morning check-in" in rendered

    def test_ask_human_examples(self):
        rendered = JIRA_OPERATIONS_LAYER.render({})
        assert "ask_human" in rendered
        assert "single_choice" in rendered

    def test_registered_in_domain_layers(self):
        layer = get_domain_layer("jira_operations")
        assert layer is JIRA_OPERATIONS_LAYER
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jira-analyst-systemprompt-hardening.spec.md` for full context
2. **Check dependencies** — verify TASK-950 is in `tasks/completed/`
3. **Read the source text** — `read` `jira_specialist.py` lines 152-461 to get the
   exact `JIRA_SPECIALIST_PROMPT` content. Copy it VERBATIM into the layer template.
4. **Verify the Codebase Contract** — confirm imports and `_DOMAIN_LAYERS` location
5. **Check for `$` conflicts** — scan the prompt text for `$word` patterns and compare
   against configure context keys from `abstract.py:876-896`
6. **Update status** in `tasks/.index.json` → `"in-progress"`
7. **Implement** following the scope and notes above
8. **Verify** all acceptance criteria are met
9. **Move this file** to `tasks/completed/TASK-951-jira-operations-layer.md`
10. **Update index** → `"done"`
11. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker agent (Claude Sonnet)
**Date**: 2026-05-01
**Notes**: Added `JIRA_OPERATIONS_LAYER` as a `PromptLayer` in `domain_layers.py`
with `name="jira_operations"`, `priority=LayerPriority.CUSTOM` (80),
`phase=RenderPhase.CONFIGURE`. The full `JIRA_SPECIALIST_PROMPT` text was
embedded verbatim in the template wrapped in `<jira_operations>...</jira_operations>`.
No `$word` template conflicts were found in the prompt text. Registered as
`"jira_operations"` in `_DOMAIN_LAYERS`. 16/16 unit tests pass.

**Deviations from spec**: none
