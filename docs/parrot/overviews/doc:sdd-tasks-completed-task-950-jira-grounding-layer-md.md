---
type: Wiki Overview
title: 'TASK-950: Define JIRA_GROUNDING_LAYER anti-hallucination prompt layer'
id: doc:sdd-tasks-completed-task-950-jira-grounding-layer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundational task for FEAT-139. The core problem is that JiraSpecialist
relates_to:
- concept: mod:parrot.bots.prompts.domain_layers
  rel: mentions
- concept: mod:parrot.bots.prompts.layers
  rel: mentions
---

# TASK-950: Define JIRA_GROUNDING_LAYER anti-hallucination prompt layer

**Feature**: FEAT-139 — Jira Analyst System Prompt Hardening
**Spec**: `sdd/specs/jira-analyst-systemprompt-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-139. The core problem is that JiraSpecialist
(using gemini-3-flash-preview) hallucinates invented Jira tickets when tool calls
return empty results, errors, or when the connection is down. The codebase already
has `STRICT_GROUNDING_LAYER` for data-analysis agents and `RAG_GROUNDING_LAYER` for
RAG agents — this task creates the equivalent for Jira tool-using agents.

Implements spec Module 1 (JIRA_GROUNDING_LAYER).

---

## Scope

- Define `JIRA_GROUNDING_LAYER` as a `PromptLayer` in `domain_layers.py`
- The layer must contain anti-hallucination rules specific to Jira:
  1. Never invent ticket keys, summaries, statuses, assignees, dates, or comments
  2. Tool output is the ONLY source of truth for Jira data
  3. Empty/error tool results → explicit "no data available" response
  4. `authorization_required` status → surface the auth URL to user, never continue from memory
  5. Connection failures → report the error plainly, never substitute cached/remembered data
  6. Never reuse ticket data from prior conversation turns unless the tool re-fetched it
  7. If asked about a ticket and no tool call was made, call the tool first
- Register the layer in the `_DOMAIN_LAYERS` dictionary
- Write unit tests

**NOT in scope**: JiraSpecialist migration (TASK-952), operations layer (TASK-951),
JiraToolkit error hardening (TASK-953).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` | MODIFY | Add JIRA_GROUNDING_LAYER + register in _DOMAIN_LAYERS |
| `packages/ai-parrot/tests/test_jira_grounding_layer.py` | CREATE | Unit tests for the new layer |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase
# verified: packages/ai-parrot/src/parrot/bots/prompts/layers.py:22,35,50

from parrot.bots.prompts.domain_layers import STRICT_GROUNDING_LAYER
# verified: packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:67

from parrot.bots.prompts.domain_layers import get_domain_layer
# verified: packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:183
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/prompts/layers.py
class LayerPriority(IntEnum):  # line 22
    IDENTITY = 10
    PRE_INSTRUCTIONS = 15
    SECURITY = 20
    KNOWLEDGE = 30
    USER_SESSION = 40
    TOOLS = 50
    OUTPUT = 60
    BEHAVIOR = 70
    CUSTOM = 80

class RenderPhase(str, Enum):  # line 35
    CONFIGURE = "configure"
    REQUEST = "request"

@dataclass(frozen=True)
class PromptLayer:  # line 50
    name: str
    priority: LayerPriority | int
    template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    required_vars: frozenset[str] = field(default_factory=frozenset)
    def render(self, context: Dict[str, Any]) -> Optional[str]:  # line 69

# packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py
# Pattern to follow — STRICT_GROUNDING_LAYER (line 67):
STRICT_GROUNDING_LAYER = PromptLayer(
    name="strict_grounding",
    priority=LayerPriority.BEHAVIOR - 5,       # = 65
    phase=RenderPhase.CONFIGURE,
    template="""<grounding_policy>...</grounding_policy>""",
)

# _DOMAIN_LAYERS registry (line 172):
_DOMAIN_LAYERS: Dict[str, PromptLayer] = {
    "dataframe_context": DATAFRAME_CONTEXT_LAYER,
    "sql_dialect": SQL_DIALECT_LAYER,
    "company_context": COMPANY_CONTEXT_LAYER,
    "crew_context": CREW_CONTEXT_LAYER,
    "strict_grounding": STRICT_GROUNDING_LAYER,
    "knowledge_scope": KNOWLEDGE_SCOPE_LAYER,
    "rag_grounding": RAG_GROUNDING_LAYER,
}
```

### Does NOT Exist
- ~~`JIRA_GROUNDING_LAYER`~~ — does not exist yet; this task creates it
- ~~`LayerPriority.GROUNDING`~~ — no such enum member; use `LayerPriority.BEHAVIOR - 5` (= 65)
- ~~`PromptLayer.jira_grounding`~~ — not a method; layers are module-level constants

---

## Implementation Notes

### Pattern to Follow
```python
# Follow STRICT_GROUNDING_LAYER at domain_layers.py:67-102
# Same structure: PromptLayer with XML-tagged template, CONFIGURE phase, priority 65
JIRA_GROUNDING_LAYER = PromptLayer(
    name="jira_grounding",
    priority=LayerPriority.BEHAVIOR - 5,
    phase=RenderPhase.CONFIGURE,
    template="""<jira_grounding_policy>
## Jira Anti-Hallucination Rules
1. **Ticket data**: ...
...
</jira_grounding_policy>""",
)
```

### Key Constraints
- Use `RenderPhase.CONFIGURE` — content is static, no `$variable` placeholders
- Priority must be `LayerPriority.BEHAVIOR - 5` (= 65) to match existing grounding layers
- Template must be wrapped in XML tags (`<jira_grounding_policy>...</jira_grounding_policy>`)
- Keep the template concise — target < 400 words
- Rules must be written in English (LLMs understand English system instructions regardless of output language)
- Add entry to `_DOMAIN_LAYERS` dict as `"jira_grounding": JIRA_GROUNDING_LAYER`

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:67-102` — STRICT_GROUNDING_LAYER pattern
- `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:126-167` — RAG_GROUNDING_LAYER pattern
- `packages/ai-parrot/src/parrot/bots/prompts/layers.py:50-111` — PromptLayer dataclass

---

## Acceptance Criteria

- [ ] `JIRA_GROUNDING_LAYER` is defined in `domain_layers.py`
- [ ] Layer name is `"jira_grounding"`, priority is 65, phase is CONFIGURE
- [ ] Template contains rules for: no invented tickets, tool-only data source, empty result handling, auth failure handling, connection failure handling
- [ ] Layer is registered in `_DOMAIN_LAYERS` dict
- [ ] `get_domain_layer("jira_grounding")` returns the layer
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_jira_grounding_layer.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_jira_grounding_layer.py
import pytest
from parrot.bots.prompts.domain_layers import (
    JIRA_GROUNDING_LAYER,
    get_domain_layer,
)
from parrot.bots.prompts.layers import LayerPriority, RenderPhase


class TestJiraGroundingLayer:
    def test_layer_exists(self):
        assert JIRA_GROUNDING_LAYER is not None

    def test_layer_name(self):
        assert JIRA_GROUNDING_LAYER.name == "jira_grounding"

    def test_layer_priority(self):
        assert JIRA_GROUNDING_LAYER.priority == LayerPriority.BEHAVIOR - 5

    def test_layer_phase(self):
        assert JIRA_GROUNDING_LAYER.phase == RenderPhase.CONFIGURE

    def test_layer_renders(self):
        rendered = JIRA_GROUNDING_LAYER.render({})
        assert rendered is not None
        assert "jira_grounding_policy" in rendered

    def test_anti_hallucination_rules_present(self):
        rendered = JIRA_GROUNDING_LAYER.render({})
        assert "ticket" in rendered.lower() or "issue" in rendered.lower()
        assert "tool" in rendered.lower()
        assert "invent" in rendered.lower() or "fabricat" in rendered.lower()

    def test_auth_failure_rule_present(self):
        rendered = JIRA_GROUNDING_LAYER.render({})
        assert "authorization" in rendered.lower() or "auth" in rendered.lower()

    def test_registered_in_domain_layers(self):
        layer = get_domain_layer("jira_grounding")
        assert layer is JIRA_GROUNDING_LAYER
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jira-analyst-systemprompt-hardening.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm `_DOMAIN_LAYERS` dict is still at `domain_layers.py:172`
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-950-jira-grounding-layer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker agent (Claude Sonnet)
**Date**: 2026-05-01
**Notes**: Added `JIRA_GROUNDING_LAYER` as a `PromptLayer` in `domain_layers.py`
with priority 65 (BEHAVIOR - 5), RenderPhase.CONFIGURE, and no condition.
The layer template covers: no invented tickets, tool-only data source, empty
result handling, auth failure handling (authorization_required), connection
failure handling, no prior-turn data reuse, and uncertainty resolution.
Registered as `"jira_grounding"` in `_DOMAIN_LAYERS`. 13/13 unit tests pass.

**Deviations from spec**: none
