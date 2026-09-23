# TASK-3638: Tool-Call Delegate documentation

**Feature**: FEAT-590 — Tool-Call Delegate
**Spec**: `sdd/specs/tool-call-delegate.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3632, TASK-3633, TASK-3635
**Assigned-to**: unassigned

---

## Context

Spec Module 9 (docs half), AC16. This is the user-facing guide to the delegate
node, plus a pointer from the existing execution-plan toolkit doc.

---

## Scope

- Write `docs/execution_plan/tool-call-delegate.md`, covering:
  - what the delegate is and is not (not an `AbstractClient`; two verbs)
  - when to use it vs `PlanToolNode` vs `AgentNode` (the §1 table)
  - node shape (with a **valid** `for_each` example: `{artifacts.<id>}` + `select`)
  - the accept gate and its verdicts, including `unscored`
  - `min_confidence` guidance for fine-tuned backends (leave it unset)
  - `on_reject` semantics (escalation is terminal in v1)
  - side-effect policy (`delegate_safe` + node flag + host flag)
  - configuring backends (`LlamaCppDelegate`, `NeedleDelegate`, `ai-parrot[needle]`)
  - toolkit kwargs (`delegates`, `delegate_trace_sink`, `allow_delegate_side_effects`)
  - trace collection (`JsonlTraceSink`, redaction, caps)
  - limitations (no repair of delegate nodes, no standalone use in v1)
- Add a short "Delegate nodes" section to `docs/toolkits/execution_plan_toolkit.md` linking to the new page.

**NOT in scope**: code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/execution_plan/tool-call-delegate.md` | CREATE | User guide |
| `docs/toolkits/execution_plan_toolkit.md` | MODIFY | Link section |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
Document only what exists after TASK-3625..3635. Before writing, confirm each named symbol with `grep`:
`DelegatePlanNode` fields (TASK-3626); verdicts in `delegate/protocol.py` (TASK-3627);
`ExecutionPlanToolkit` kwargs (TASK-3635); backend constructors in
`packages/ai-parrot/src/parrot/bots/flows/plan/delegate/llamacpp.py` (TASK-3632) and
`packages/ai-parrot/src/parrot/bots/flows/plan/delegate/needle.py` (TASK-3633).

### Does NOT Exist
- ~~`docs/execution_plan/`~~: the directory does not exist yet; create it.
- ~~A `llamacpp` extra~~: don't document one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/execution_plan/tool-call-delegate.md", "action": "CREATE"},
    {"path": "docs/toolkits/execution_plan_toolkit.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Grep every symbol you will name — *why*: docs must not describe APIs that drifted during implementation.
2. Write the guide with the headings below — *why*: AC16's checklist maps one-to-one onto them.
3. Append the link section to the toolkit doc.

### `docs/execution_plan/tool-call-delegate.md` (CREATE)
```markdown
# Tool-Call Delegate (FEAT-590)
## What it is (and is not)
## When to use it — PlanToolNode vs DelegateToolNode vs AgentNode
## Node shape
## The accept gate (verdicts: declined, unknown_tool, invalid_args, side_effect_denied, low_confidence, unscored, guard_false, input_too_long, backend_error)
## on_reject: fail | retry_backend | escalate
## Side-effect policy
## Backends: LlamaCppDelegate · NeedleDelegate (`ai-parrot[needle]`)
## Toolkit configuration
## Traces and fine-tuning data
## Limitations (v1)
<!-- FILL IN every section; one runnable-looking config example using real kwargs -->
```

### `docs/toolkits/execution_plan_toolkit.md` (MODIFY)
```markdown
# APPEND at end of file (320 lines at cc6caa6da):
## Delegate nodes
Plans may include `"type": "delegate"` nodes that let a tiny local model pick one tool call at run
time. See [Tool-Call Delegate](../execution_plan/tool-call-delegate.md).
```

### FILL IN checklist
- [ ] Every guide section

---

## Acceptance Criteria

- [ ] AC16: every topic listed in Scope is covered
- [ ] Every symbol or kwarg named in the docs exists (grep-checked)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py -q`

> Docs task: this is only a smoke check that the toolkit the docs describe still passes its suite.
> The real check is AC16 (every named symbol grep-verified).

---

## Test Specification

None (documentation).

---

## Agent Instructions

Standard.

---

## Completion Note

*(Agent fills this in when done)*
