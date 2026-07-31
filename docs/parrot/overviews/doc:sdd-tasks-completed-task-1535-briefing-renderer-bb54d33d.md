---
type: Wiki Overview
title: 'TASK-1535: Briefing renderer & edit-before-execute re-validation'
id: doc:sdd-tasks-completed-task-1535-briefing-renderer-and-edit-revalidation-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 2. Replaces the minimal raw briefing from TASK-1534 with a
relates_to:
- concept: mod:parrot.auth.confirmation
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
---

# TASK-1535: Briefing renderer & edit-before-execute re-validation

**Feature**: FEAT-235 — HITL Tool-Call Confirmation
**Spec**: `sdd/specs/hitl-confirmation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1534
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. Replaces the minimal raw briefing from TASK-1534 with a
configurable template renderer, and adds the edit-before-execute path: when a tool
sets `allow_edit` and the channel supports forms, the guard asks an
`InteractionType.FORM` interaction seeded from the tool's `args_schema`, then
re-validates returned values against that schema (bounded by `max_edit_retries`).

---

## Scope

- In `parrot/auth/confirmation.py`, add helpers (module-level functions or private
  methods on `ConfirmationGuard`):
  - `render_briefing(tool, parameters) -> str` — format
    `tool.routing_meta.get("confirm_template")` against `{tool, params, **parameters}`
    using **safe** string formatting; on missing keys or no template, fall back to a
    raw `"<tool.name> with: k=v, k2=v2"` listing. Never use `eval`/`format_map` with
    untrusted attribute access.
  - `build_form_schema(tool, parameters) -> dict` — derive a `form_schema` for the
    FORM interaction from `tool.args_schema` (pydantic model) pre-filled with the
    current `parameters`.
  - `revalidate_edit(tool, edited: dict) -> dict` — validate `edited` against
    `tool.args_schema`; raise/return-invalid on failure.
- Wire these into `ConfirmationGuard.confirm()`:
  - Use `render_briefing` for the interaction `question`.
  - When `tool.routing_meta.get("allow_edit")` is truthy: use
    `InteractionType.FORM` with `build_form_schema`; on response, run
    `revalidate_edit`. On invalid edit, re-ask up to `config.max_edit_retries`, then
    return `allowed=False, status="cancelled"`. On valid edit, return
    `allowed=True, status="confirmed", parameters=<edited>`.
  - When `allow_edit` is falsy → keep the APPROVAL path from TASK-1534.
- Tests in `packages/ai-parrot/tests/test_confirmation_briefing.py`.

**NOT in scope**: ToolManager wiring (TASK-1536); decorator/spawn (TASK-1537);
new channel UI (out of scope entirely — reuse existing FORM rendering).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/confirmation.py` | MODIFY | briefing renderer + edit re-validation + FORM path |
| `packages/ai-parrot/tests/test_confirmation_briefing.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.human.models import InteractionType, HumanInteraction   # human/models.py:60,380
# pydantic validation of edited values against the tool schema:
from pydantic import ValidationError
```

### Existing Signatures to Use
```python
# parrot/human/models.py
class InteractionType(str, Enum): ... FORM = "form"   # line 67 (requires form_schema)
class HumanInteraction(BaseModel):                    # line 380
    interaction_type: InteractionType
    form_schema: Optional[Dict[str, Any]]             # line 390 — REQUIRED when type == FORM
    # model_validator enforces: FORM requires non-empty form_schema  # lines 433-435

# parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):           # line 81
    args_schema: Type[BaseModel]                      # tool input schema (verify exact attr name in file)
    routing_meta: Dict                                # line 140
```

### Does NOT Exist
- ~~A `briefing` helper / `render_briefing` anywhere~~ — this task CREATES it.
- ~~`HumanInteraction` accepts FORM without `form_schema`~~ — the model_validator
  REJECTS it (human/models.py:433). Always pass a non-empty `form_schema`.
- ~~`tool.input_schema`~~ — verify the real attribute name on `AbstractTool`
  (`args_schema`) before use; do not assume.

---

## Implementation Notes

### Key Constraints
- Briefing rendering must be **safe**: catch `KeyError`/`IndexError` from a
  malformed template and fall back to the raw listing; log a warning.
- `build_form_schema` must produce a `form_schema` that passes the
  `HumanInteraction` model_validator (non-empty dict).
- Re-validation uses the tool's pydantic `args_schema` — on `ValidationError`,
  re-ask (bounded) rather than executing.
- Before coding, `read` `parrot/tools/abstract.py` to confirm the exact attribute
  name for the args schema and how to instantiate/validate it.

### References in Codebase
- `parrot/human/models.py:380-440` — `HumanInteraction` + FORM validator.
- `parrot/human/channels/web.py` — how FORM payloads are rendered (read-only ref;
  do NOT modify channels).

---

## Acceptance Criteria

- [ ] `render_briefing` uses `confirm_template` when present; raw `param=value`
      fallback when absent or on a bad template (no exception escapes).
- [ ] `allow_edit` tool → FORM interaction with a non-empty `form_schema`.
- [ ] Valid edited values replace `parameters` in the decision; `status="confirmed"`.
- [ ] Invalid edit beyond `max_edit_retries` → `allowed=False, status="cancelled"`.
- [ ] Non-`allow_edit` tool still uses the APPROVAL path unchanged.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_confirmation_briefing.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/auth/confirmation.py`

---

## Test Specification
```python
# packages/ai-parrot/tests/test_confirmation_briefing.py
from parrot.auth.confirmation import render_briefing

def test_template_render(confirming_tool):
    confirming_tool.routing_meta["confirm_template"] = "Run {tool} with {params}"
    s = render_briefing(confirming_tool, {"x": 1})
    assert "Run" in s and "x" in s

def test_raw_fallback_on_bad_template(confirming_tool):
    confirming_tool.routing_meta["confirm_template"] = "{missing_key}"
    s = render_briefing(confirming_tool, {"x": 1})
    assert "x" in s  # fell back to raw listing, no exception
```

---

## Agent Instructions
1. Read spec §2/§6 + TASK-1534's guard. 2. Verify `args_schema` attr + FORM validator.
3. Index → `in-progress`. 4. Implement + verify. 5. Move to completed, index → `done`, note.

---

## Completion Note
**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-06-12
**Notes**: render_briefing, build_form_schema, revalidate_edit implemented in
confirmation.py. FORM path wired into ConfirmationGuard.confirm() alongside
APPROVAL path. max_edit_retries loop implemented. All 16 briefing tests pass.
**Deviations from spec**: none
