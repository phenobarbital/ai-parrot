---
type: Wiki Overview
title: 'TASK-944: Add JIRA_WORKFLOW_LAYER (decompose legacy prompt)'
id: doc:sdd-tasks-completed-task-944-jira-workflow-layer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 1** of FEAT-138. Carries forward the workflow rules
relates_to:
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.bots.prompts.layers
  rel: mentions
---

# TASK-944: Add JIRA_WORKFLOW_LAYER (decompose legacy prompt)

**Feature**: FEAT-138 — jira_analyst_systemprompt_hardening
**Spec**: `sdd/specs/jira_analyst_systemprompt_hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of FEAT-138. Carries forward the workflow rules
embedded in the legacy `JIRA_SPECIALIST_PROMPT` (sections: *Default
posture*, *Fresh-turn rule*, *Cancellation rule*, *Mandatory human
interaction*, *Daily standup flow*, *Mid-day blockers*, *Assignment
intake*, *End-of-day wrap*, *Escalation*) into a single composable
`PromptLayer` instance. **English-only** — any non-English phrasing in
the legacy prompt must be rewritten in English when copied.

This is the foundation layer that `JiraSpecialist` will install via
`PromptBuilder` once Module 3 wires the registry and Module 4 migrates
the agent.

---

## Scope

- Add a new module-level constant `JIRA_WORKFLOW_LAYER: PromptLayer` in
  `domain_layers.py`.
- Phase: `RenderPhase.CONFIGURE`. Priority: `LayerPriority.PRE_INSTRUCTIONS + 5`
  (renders after identity/security but before knowledge).
- Template body: re-write each section of `JIRA_SPECIALIST_PROMPT`
  (`packages/ai-parrot/src/parrot/bots/jira_specialist.py:152-461`) in
  English, preserving every behavioural rule. The template wraps the
  body in a single XML tag, e.g. `<jira_workflow>...</jira_workflow>`.
- The layer must NOT include any anti-hallucination rules — those live
  in `JIRA_GROUNDING_LAYER` (TASK-945).

**NOT in scope**: registering the layer in `_DOMAIN_LAYERS` (TASK-946),
exporting from `prompts/__init__.py` (TASK-946), wiring into
`JiraSpecialist` (TASK-947), removing the legacy literal (TASK-947).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` | MODIFY | Add `JIRA_WORKFLOW_LAYER` constant |
| `packages/ai-parrot/tests/test_jira_workflow_layer.py` | CREATE | Unit test verifying layer renders and contains expected sections |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/bots/prompts/layers.py:14-19
from parrot.bots.prompts.layers import (
    PromptLayer,
    LayerPriority,
    RenderPhase,
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/prompts/layers.py:22
class LayerPriority(IntEnum):
    IDENTITY = 10
    PRE_INSTRUCTIONS = 15        # ← +5 puts JIRA_WORKFLOW_LAYER at 20 (before SECURITY)
    SECURITY = 20                # NOTE: workflow at 20 collides with SECURITY; use 16 instead
    KNOWLEDGE = 30
    USER_SESSION = 40
    TOOLS = 50
    OUTPUT = 60
    BEHAVIOR = 70
    CUSTOM = 80

# packages/ai-parrot/src/parrot/bots/prompts/layers.py:35
class RenderPhase(str, Enum):
    CONFIGURE = "configure"
    REQUEST = "request"

# packages/ai-parrot/src/parrot/bots/prompts/layers.py:50
@dataclass(frozen=True)
class PromptLayer:
    name: str
    priority: LayerPriority | int
    template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    required_vars: frozenset[str] = field(default_factory=frozenset)
    def render(self, context: Dict[str, Any]) -> Optional[str]:           # line 69
    def partial_render(self, context: Dict[str, Any]) -> PromptLayer:     # line 83
```

```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py:152-461
JIRA_SPECIALIST_PROMPT: str  # legacy ~310-line monolithic template — source for the
                              # workflow content this task carries forward (English-only).
                              # Fully removed in TASK-947; do NOT modify it here.
```

### Does NOT Exist

- ~~`PromptLayer.workflow_template()`~~ — no factory; build the constant directly.
- ~~`LayerPriority.WORKFLOW`~~ — not a member; use `PRE_INSTRUCTIONS + 1` (= 16)
  to slot strictly after PRE_INSTRUCTIONS (15) and strictly before SECURITY (20).
- ~~`get_domain_layer("jira_workflow")`~~ — registration happens in TASK-946,
  not here.

---

## Implementation Notes

### Pattern to Follow

Copy the shape of `STRICT_GROUNDING_LAYER`
(`packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:67-102`):
frozen dataclass instance, XML tag wrapping the body, explicit `phase`
and `priority`, single multi-line string template.

### Key Constraints

- Priority slot: use `LayerPriority.PRE_INSTRUCTIONS + 1` (= 16). `+5`
  collides with `SECURITY = 20`; the spec's "+5" was a sketch — pick a
  value that respects the existing ordering.
- Phase: `CONFIGURE`. The workflow text contains no per-request
  variables.
- English-only: any Spanish/non-English phrasing in
  `JIRA_SPECIALIST_PROMPT` (greetings, form questions, cancellation
  text, escalation messages) is rewritten in English.
- Preserve every behavioural rule: cancellation hard-stop, fresh-turn
  rule, mandatory HITL for closes / mass ops / missing fields, daily
  standup flow, assignment intake form, EOD wrap, escalation timing.
- Do NOT include the sentinel phrases `No results found for <KEY>` or
  `Jira lookup failed: <message>` — those belong to TASK-945.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:67-102` — `STRICT_GROUNDING_LAYER` pattern.
- `packages/ai-parrot/src/parrot/bots/prompts/layers.py:115-126` — `IDENTITY_LAYER` for an XML-tagged CONFIGURE-phase example.
- `packages/ai-parrot/src/parrot/bots/jira_specialist.py:152-461` — source content (legacy prompt).

---

## Acceptance Criteria

- [ ] `JIRA_WORKFLOW_LAYER` exists in `domain_layers.py` as a
      `PromptLayer` instance with `name="jira_workflow"`,
      `phase=RenderPhase.CONFIGURE`, `priority=LayerPriority.PRE_INSTRUCTIONS + 1`.
- [ ] Layer renders without missing-var errors when given an empty
      context.
- [ ] Layer body contains English headings for every section present in
      `JIRA_SPECIALIST_PROMPT` (Default posture / Fresh-turn rule /
      Cancellation rule / Mandatory human interaction / Daily standup /
      Mid-day blockers / Assignment intake / End-of-day wrap / Escalation).
- [ ] Layer body contains **no** non-English text and **no**
      anti-hallucination sentinel phrases.
- [ ] `pytest packages/ai-parrot/tests/test_jira_workflow_layer.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_jira_workflow_layer.py
import pytest
from parrot.bots.prompts import (
    JIRA_WORKFLOW_LAYER, PromptLayer, LayerPriority, RenderPhase,
)


def test_jira_workflow_layer_metadata():
    assert isinstance(JIRA_WORKFLOW_LAYER, PromptLayer)
    assert JIRA_WORKFLOW_LAYER.name == "jira_workflow"
    assert JIRA_WORKFLOW_LAYER.phase == RenderPhase.CONFIGURE
    assert int(JIRA_WORKFLOW_LAYER.priority) > int(LayerPriority.PRE_INSTRUCTIONS)
    assert int(JIRA_WORKFLOW_LAYER.priority) < int(LayerPriority.SECURITY)


def test_jira_workflow_layer_renders():
    rendered = JIRA_WORKFLOW_LAYER.render({})
    assert rendered is not None
    assert "<jira_workflow>" in rendered
    assert "</jira_workflow>" in rendered


@pytest.mark.parametrize("section_keyword", [
    "default posture", "fresh-turn", "cancellation",
    "mandatory human", "daily standup", "mid-day",
    "assignment intake", "end-of-day", "escalation",
])
def test_jira_workflow_layer_covers_section(section_keyword):
    rendered = JIRA_WORKFLOW_LAYER.render({}).lower()
    assert section_keyword in rendered, (
        f"Section '{section_keyword}' missing from JIRA_WORKFLOW_LAYER"
    )


def test_jira_workflow_layer_is_english_only():
    rendered = JIRA_WORKFLOW_LAYER.render({})
    forbidden = ["Operación", "Sin respuesta", "¿Aceptas", "Mil disculpas",
                 "No encontré", "Hubo un error consultando"]
    for phrase in forbidden:
        assert phrase not in rendered, f"non-English / sentinel leak: {phrase!r}"
```

---

## Agent Instructions

When you pick up this task:

1. Read the spec for full context (sections 1, 2 Overview, 3 Module 1, 7 Patterns).
2. Re-read `JIRA_SPECIALIST_PROMPT` at `jira_specialist.py:152-461`.
3. Verify `PromptLayer` / `LayerPriority` / `RenderPhase` signatures still
   match the contract above (`grep` or `read`).
4. Update status in `sdd/tasks/.index.json` → `"in-progress"`.
5. Implement.
6. Run the test, verify all ACs pass.
7. Move file to `sdd/tasks/completed/` and update index → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
