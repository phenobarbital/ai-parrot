---
type: Wiki Overview
title: 'TASK-946: Register and re-export Jira layers'
id: doc:sdd-tasks-completed-task-946-register-and-export-jira-layers-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 3** of FEAT-138. Wires the two new layers from
relates_to:
- concept: mod:parrot.bots.prompts
  rel: mentions
---

# TASK-946: Register and re-export Jira layers

**Feature**: FEAT-138 — jira_analyst_systemprompt_hardening
**Spec**: `sdd/specs/jira_analyst_systemprompt_hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-944, TASK-945
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of FEAT-138. Wires the two new layers from
TASK-944 / TASK-945 into the domain-layer registry and the public
`parrot.bots.prompts` package surface so that
`get_domain_layer("jira_workflow")` and `get_domain_layer("jira_grounding")`
resolve, and so that callers can `from parrot.bots.prompts import
JIRA_WORKFLOW_LAYER, JIRA_GROUNDING_LAYER`.

---

## Scope

- Add `"jira_workflow": JIRA_WORKFLOW_LAYER` and
  `"jira_grounding": JIRA_GROUNDING_LAYER` entries to the
  `_DOMAIN_LAYERS` dict in `domain_layers.py`.
- Re-export both constants from
  `packages/ai-parrot/src/parrot/bots/prompts/__init__.py`, alongside
  the existing `STRICT_GROUNDING_LAYER` re-export.

**NOT in scope**: the layer definitions themselves (TASK-944 / TASK-945),
wiring into `JiraSpecialist` (TASK-947).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` | MODIFY | Extend `_DOMAIN_LAYERS` |
| `packages/ai-parrot/src/parrot/bots/prompts/__init__.py` | MODIFY | Re-export both layers |
| `packages/ai-parrot/tests/test_domain_layer_registry.py` | CREATE | Tests for `get_domain_layer` resolution |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/bots/prompts/__init__.py:30-37
from .domain_layers import (
    DATAFRAME_CONTEXT_LAYER,
    SQL_DIALECT_LAYER,
    COMPANY_CONTEXT_LAYER,
    CREW_CONTEXT_LAYER,
    STRICT_GROUNDING_LAYER,
    get_domain_layer,
)
# JIRA_WORKFLOW_LAYER and JIRA_GROUNDING_LAYER must be added to this
# import block in this task.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:172
_DOMAIN_LAYERS: Dict[str, PromptLayer] = {
    "dataframe_context": DATAFRAME_CONTEXT_LAYER,
    "sql_dialect": SQL_DIALECT_LAYER,
    "company_context": COMPANY_CONTEXT_LAYER,
    "crew_context": CREW_CONTEXT_LAYER,
    "strict_grounding": STRICT_GROUNDING_LAYER,
    "knowledge_scope": KNOWLEDGE_SCOPE_LAYER,
    "rag_grounding": RAG_GROUNDING_LAYER,
}
# Add: "jira_workflow", "jira_grounding"

# packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:183
def get_domain_layer(name: str) -> PromptLayer:
    """Look up a registered domain layer by name."""
    if name not in _DOMAIN_LAYERS:
        raise KeyError(...)
    return _DOMAIN_LAYERS[name]
```

### Does NOT Exist

- ~~`register_domain_layer()`~~ — there is no public registration API;
  edit `_DOMAIN_LAYERS` directly.
- ~~`get_domain_layer("jira")`~~ — registry keys are
  `"jira_workflow"` and `"jira_grounding"`, not `"jira"`.
- ~~`JIRA_DOMAIN_LAYERS` aggregate~~ — does not exist; do not invent it.

---

## Implementation Notes

### Pattern to Follow

Single-line additions to the existing dict literal and the existing
import block. No new functions.

### Key Constraints

- Keep alphabetical or logical grouping consistent with the existing
  registry style.
- Do NOT remove or rename existing entries.

### References in Codebase

- `domain_layers.py:172-180` — registry definition.
- `prompts/__init__.py:30-37` — re-export block.

---

## Acceptance Criteria

- [ ] `get_domain_layer("jira_workflow")` returns `JIRA_WORKFLOW_LAYER`.
- [ ] `get_domain_layer("jira_grounding")` returns `JIRA_GROUNDING_LAYER`.
- [ ] `from parrot.bots.prompts import JIRA_WORKFLOW_LAYER, JIRA_GROUNDING_LAYER`
      succeeds.
- [ ] No existing entries in `_DOMAIN_LAYERS` were removed or renamed
      (regression-test the previous keys).
- [ ] `pytest packages/ai-parrot/tests/test_domain_layer_registry.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/prompts/` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_domain_layer_registry.py
import pytest
from parrot.bots.prompts import (
    get_domain_layer,
    JIRA_WORKFLOW_LAYER,
    JIRA_GROUNDING_LAYER,
    STRICT_GROUNDING_LAYER,
)


def test_jira_workflow_layer_resolves():
    assert get_domain_layer("jira_workflow") is JIRA_WORKFLOW_LAYER


def test_jira_grounding_layer_resolves():
    assert get_domain_layer("jira_grounding") is JIRA_GROUNDING_LAYER


def test_existing_layers_still_resolve():
    # Regression: the new entries must not displace existing ones.
    assert get_domain_layer("strict_grounding") is STRICT_GROUNDING_LAYER
    for name in ("dataframe_context", "sql_dialect", "company_context",
                 "crew_context", "knowledge_scope", "rag_grounding"):
        assert get_domain_layer(name) is not None


def test_unknown_layer_raises():
    with pytest.raises(KeyError):
        get_domain_layer("not_a_layer")
```

---

## Agent Instructions

1. Verify TASK-944 and TASK-945 are in `sdd/tasks/completed/`.
2. Update index → `"in-progress"`.
3. Add the two registry entries and the two re-exports.
4. Run the test; verify ACs.
5. Move file to `completed/`; update index → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
