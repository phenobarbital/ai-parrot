---
type: Wiki Overview
title: 'TASK-945: Add JIRA_GROUNDING_LAYER (anti-hallucination)'
id: doc:sdd-tasks-completed-task-945-jira-grounding-layer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 2** of FEAT-138. Adds the Jira-specific
relates_to:
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.bots.prompts.layers
  rel: mentions
---

# TASK-945: Add JIRA_GROUNDING_LAYER (anti-hallucination)

**Feature**: FEAT-138 — jira_analyst_systemprompt_hardening
**Spec**: `sdd/specs/jira_analyst_systemprompt_hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of FEAT-138. Adds the Jira-specific
anti-hallucination layer that hardens `JiraSpecialist` against the
observed failure modes when Gemini-3-Flash receives empty or error
responses from `JiraToolkit` (field fabrication on miss, cross-ticket
field bleeding, apology-then-fabricate loop, phantom IDs / dates).

The layer is the **counterpart** of the existing `STRICT_GROUNDING_LAYER`
(which targets pandas/data-analysis flows) and complements
`JIRA_WORKFLOW_LAYER` (TASK-944).

---

## Scope

- Add a new module-level constant `JIRA_GROUNDING_LAYER: PromptLayer`
  in `domain_layers.py` immediately after `STRICT_GROUNDING_LAYER`.
- Phase: `RenderPhase.CONFIGURE`. Priority: `LayerPriority.BEHAVIOR - 5`
  (= 65), the same slot used by `STRICT_GROUNDING_LAYER` — they are
  mutually exclusive per agent.
- Template body (English-only) MUST include verbatim:
  - The sentinel `No results found for <KEY|JQL>.` for `status="not_found"`
    and `status="empty"`.
  - The sentinel `Jira lookup failed: <message>.` for unexpected toolkit
    errors.
  - A "no apology-then-fabricate" rule explicitly forbidding the loop.
  - A "no cross-ticket bleed" rule: never reuse fields from a prior
    tool call's result for a different issue key — re-call the tool.
  - A "tool-output is authoritative" rule: every field (key, summary,
    status, reporter, assignee, dates, labels, components, accountId,
    comments, history) MUST come from a tool call made in the current
    turn.
- The most load-bearing rules ("never fabricate", on-empty phrase, on-error
  phrase) MUST appear in the **first paragraph** so they survive truncation
  by Gemini-3-Flash.

**NOT in scope**: registering the layer in `_DOMAIN_LAYERS` (TASK-946),
exporting from `prompts/__init__.py` (TASK-946), wiring into
`JiraSpecialist` (TASK-947). The workflow content is in TASK-944.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` | MODIFY | Add `JIRA_GROUNDING_LAYER` constant |
| `packages/ai-parrot/tests/test_jira_grounding_layer.py` | CREATE | Unit test verifying rendering and required phrases |

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
# packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:67
STRICT_GROUNDING_LAYER = PromptLayer(
    name="strict_grounding",
    priority=LayerPriority.BEHAVIOR - 5,  # = 65
    phase=RenderPhase.CONFIGURE,
    template="""<grounding_policy>
    ... pandas/dataframe-oriented rules ...
</grounding_policy>""",
)
# Pattern reference. Do NOT modify this layer in this task.

# packages/ai-parrot/src/parrot/bots/prompts/layers.py:22
class LayerPriority(IntEnum):
    BEHAVIOR = 70    # JIRA_GROUNDING_LAYER uses BEHAVIOR - 5 = 65
    CUSTOM = 80
```

### Does NOT Exist

- ~~Modifying `STRICT_GROUNDING_LAYER`~~ — out of scope; create a
  separate layer instead.
- ~~A localised `JIRA_GROUNDING_LAYER_EN`~~ — does NOT exist; the
  layer is English-only by design (see Open Question 2 resolution in
  the spec).
- ~~`PromptLayer.error_template()`~~ — no factory; use the constructor.
- ~~Sentinel phrases in Spanish~~ — Q2 locks them as English: "No
  results found for <KEY>" and "Jira lookup failed: <message>".

---

## Implementation Notes

### Pattern to Follow

Copy the shape of `STRICT_GROUNDING_LAYER`
(`packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:67-102`):
frozen dataclass instance, XML tag wrapping the body, explicit `phase`
and `priority`.

### Suggested Template Skeleton

```python
JIRA_GROUNDING_LAYER = PromptLayer(
    name="jira_grounding",
    priority=LayerPriority.BEHAVIOR - 5,
    phase=RenderPhase.CONFIGURE,
    template="""<jira_grounding_policy>
Use ONLY data returned by Jira tool calls in the current turn.
Never fabricate ticket fields. On a missing result, reply
"No results found for <KEY|JQL>." and stop. On a tool error,
reply "Jira lookup failed: <message>." and stop.

## Anti-Hallucination Rules (Jira)
1. Tool output is authoritative: every ticket field — key, summary,
   status, reporter, assignee, dates, labels, components, accountId,
   comments, history — MUST come from a tool call made in this turn.
2. Empty / not_found results: if a tool returns
   `status="empty"` or `status="not_found"`, reply literally
   `No results found for <KEY|JQL>.` and stop. Do NOT retry the same
   tool with cosmetic input variations.
3. Errors: if a tool returns `status="error"` or raises, reply
   `Jira lookup failed: <message>.` and stop. Do NOT apologise + emit
   a fabricated answer.
4. No cross-ticket bleed: never reuse fields from a prior tool call's
   result when answering about a different issue key — re-call the tool.
5. No invented identifiers: never invent issue keys, accountIds,
   displayNames, project keys, dates, or comment IDs.
6. No apology-then-fabricate loop: when corrected by the user, re-call
   the relevant tool. Do NOT produce a second answer that replaces one
   fabrication with another.
</jira_grounding_policy>""",
)
```

### Key Constraints

- Layer must be a frozen dataclass instance (the `PromptLayer` is
  `@dataclass(frozen=True)`).
- No `condition`: the layer always renders for any agent that adds it.
- No `required_vars`: the template has no `$` placeholders.

### References in Codebase

- `domain_layers.py:67-102` — `STRICT_GROUNDING_LAYER` pattern.
- `domain_layers.py:126-167` — `RAG_GROUNDING_LAYER` for another
  mutually-exclusive grounding layer at the same priority slot.

---

## Acceptance Criteria

- [ ] `JIRA_GROUNDING_LAYER` exists in `domain_layers.py` with
      `name="jira_grounding"`, `phase=RenderPhase.CONFIGURE`,
      `priority == int(LayerPriority.BEHAVIOR) - 5`.
- [ ] `JIRA_GROUNDING_LAYER.render({})` returns a string containing
      the verbatim phrases `No results found for` and `Jira lookup failed`.
- [ ] First paragraph of the rendered text contains all three
      load-bearing rules (no fabrication, on-empty phrase, on-error phrase).
- [ ] Layer body is English-only.
- [ ] `pytest packages/ai-parrot/tests/test_jira_grounding_layer.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_jira_grounding_layer.py
from parrot.bots.prompts import (
    JIRA_GROUNDING_LAYER, PromptLayer, LayerPriority, RenderPhase,
)


def test_jira_grounding_layer_metadata():
    assert isinstance(JIRA_GROUNDING_LAYER, PromptLayer)
    assert JIRA_GROUNDING_LAYER.name == "jira_grounding"
    assert JIRA_GROUNDING_LAYER.phase == RenderPhase.CONFIGURE
    assert int(JIRA_GROUNDING_LAYER.priority) == int(LayerPriority.BEHAVIOR) - 5


def test_jira_grounding_layer_contains_sentinel_phrases():
    rendered = JIRA_GROUNDING_LAYER.render({})
    assert "No results found for" in rendered
    assert "Jira lookup failed" in rendered


def test_jira_grounding_layer_load_bearing_rules_in_first_paragraph():
    rendered = JIRA_GROUNDING_LAYER.render({})
    first_paragraph = rendered.split("\n\n", 1)[0].lower()
    assert "fabricate" in first_paragraph or "fabrication" in first_paragraph
    assert "no results found" in first_paragraph
    assert "jira lookup failed" in first_paragraph


def test_jira_grounding_layer_is_english_only():
    rendered = JIRA_GROUNDING_LAYER.render({})
    forbidden = ["No encontré", "Hubo un error", "disculpa", "consultando"]
    for phrase in forbidden:
        assert phrase not in rendered
```

---

## Agent Instructions

1. Read the spec sections 1 (Problem Statement), 3 Module 2, 7 Patterns.
2. Verify `PromptLayer`, `LayerPriority`, `RenderPhase`, and the
   existing `STRICT_GROUNDING_LAYER` against the contract above.
3. Update index → `"in-progress"`.
4. Implement.
5. Run the test; verify ACs.
6. Move file to `sdd/tasks/completed/`; update index → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
