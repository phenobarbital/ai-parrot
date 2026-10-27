# TASK-4756: Document `materialize_widget` for frontend and agent authors

**Feature**: FEAT-757 — Materialize a chat turn as a linked widget
**Spec**: `sdd/specs/materialize-turn-linked-widget.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4754
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 and AC8. The point of the feature is that a frontend stops crafting prompts, so the call must be
documented where frontend developers look: the AgentDashboard reference §8.6 (agent functions from the renderer)
and the linked-surfaces guide. Agent authors also need the opt-in registration snippet (Q4, resolved).

---

## Scope

- Add a `#### Materializing an inline answer (`materialize_widget`, FEAT-757)` subsection to
  `docs/frontend/agentdashboard-a2ui-reference.md` §8.6, covering the `callAgentFunction` call (with `catalogId` set),
  the args table, the four statuses with their reasons, and the "fall back to a snapshot pin" rule.
- Add a `## 3b. Materializing a chat turn` section to `docs/outputs/a2ui-linked-surfaces.md`, covering what the tool
  reads (the turn's `qs_execute_slug` invocation and the on-screen envelope), the `NEUTRAL_TOOLS` rule, and the
  agent-side registration snippet.

**NOT in scope**: code or tests; editing any other doc section; the NAV-10382 Jira reply.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/frontend/agentdashboard-a2ui-reference.md` | MODIFY | New subsection under §8.6 |
| `docs/outputs/a2ui-linked-surfaces.md` | MODIFY | New §3b before §4 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.materialize_widget import MaterializeWidgetTool   # created by TASK-4754 — use in the snippet
```

### Existing Signatures to Use
```text
docs/frontend/agentdashboard-a2ui-reference.md:972   "### 8.6 Actions and agent functions from the renderer"  (1 occurrence)
docs/frontend/agentdashboard-a2ui-reference.md:980   "### 8.7 Pinned-surfaces sidebar and sharing"            (next heading)
docs/outputs/a2ui-linked-surfaces.md:149             "## 4. Refresh policy and snapshots"                     (1 occurrence)
Pin route documented in the reference: POST /api/v1/ui/surfaces {kind, title, envelope, ...}; callAgentFunction
responses: agentFunctionResponse.value or an error envelope (reference §8.6).
```
Take the arg names, status/reason strings and `NEUTRAL_TOOLS` members from the **merged code** of TASK-4753 and
TASK-4754 (`parrot/outputs/a2ui/linked/materialize.py`, `parrot_tools/materialize_widget.py`), not from this file.

### Does NOT Exist
- ~~a `/pin` skill~~ — not shipped (spec NG6); do not document one.
- ~~an HTTP route for materialization~~ — none (NG5); it is an agent function / tool only.
- ~~an LLM re-ask mode~~ — none (Q1).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/frontend/agentdashboard-a2ui-reference.md", "action": "MODIFY"},
    {"path": "docs/outputs/a2ui-linked-surfaces.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Re-run `grep -c` for both anchors (counts must still be 1) — *why*: the docs move often; a changed count means
   the anchor drifted, so stop and report.
2. Insert the reference subsection just before `### 8.7 Pinned-surfaces sidebar and sharing` — *why*: it belongs to
   §8.6, and inserting before the next heading keeps §8.6's existing bullets intact.
3. Insert the linked-surfaces section just before `## 4. Refresh policy and snapshots`.

### `docs/frontend/agentdashboard-a2ui-reference.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^### 8.6 Actions and agent functions from the renderer' docs/frontend/agentdashboard-a2ui-reference.md) -->
<!-- BEFORE — insert above `### 8.7 Pinned-surfaces sidebar and sharing` (verified: :980) -->
#### Materializing an inline answer (`materialize_widget`, FEAT-757)

"Keep this fresh" on an inline chart/table/KPI: send a `callAgentFunction` for `materialize_widget` (catalogId set to
the surface catalog) with `{turn_id, session_id, envelope, pin}`, where `envelope` is the bubble's `a2ui_envelope`.
No prompt and no LLM turn: the agent rebuilds the same widget bound to the query that produced the turn.

<!-- FILL IN: args table (turn_id, envelope, session_id, title, pin, snapshot) and a statuses table
     (materialized / already_linked / snapshot_only / not_materializable, each with its reasons) — taken from the merged
     code. State the rule: on snapshot_only, pin the bubble's envelope as-is with POST /api/v1/ui/surfaces (kind widget). -->
```
**Why**: frontend developers look in §8.6 for anything they invoke through `callAgentFunction`.

### `docs/outputs/a2ui-linked-surfaces.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^## 4. Refresh policy and snapshots' docs/outputs/a2ui-linked-surfaces.md) -->
<!-- BEFORE — insert above `## 4. Refresh policy and snapshots` (verified: :149) -->
## 3b. Materializing a chat turn (FEAT-757)

<!-- FILL IN: what is read (the turn's last completed qs_execute_slug invocation; the on-screen root component),
     the NEUTRAL_TOOLS rule (any other tool in the turn -> snapshot_only), ownership (caller's user + session),
     and the opt-in registration snippet:
         agent.tool_manager.register_tool(MaterializeWidgetTool(bot=agent))
     next to QuerysourceToolkit and (for pin=True) PublishSurfaceTool. -->
```
**Why**: agent authors read the linked-surfaces guide, and registration is opt-in (Q4), so the snippet is required.

### FILL IN checklist
- [ ] reference §8.6 args and statuses tables, plus the snapshot-pin rule
- [ ] linked-surfaces §3b origin rules and registration snippet

---

## Acceptance Criteria

- [ ] Both sections exist with names and reason strings matching the merged code (spec AC8)
- [ ] No other section of either doc changed
- [ ] `pytest packages/ai-parrot/tests/outputs/a2ui/test_linked_docs.py` still passes (it checks the linked docs)

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/test_linked_docs.py -q`

---

## Test Specification

No new tests: this task changes only docs. The existing docs test in the Validation Commands guards the
linked-surfaces document.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug materialize-turn-linked-widget --feature-id FEAT-757`)
2. **Read the spec** for full context.
3. **Check dependencies**: TASK-4754 must be `done`.
4. **Verify the anchors** (step 1 above).
5. **Update status** → `"in-progress"`, commit only the index file.
6. **Implement** the two insertions.
7. **Verify** with the Validation Commands.
8. **Commit the docs**, staging only the two files.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4756 materialize-turn-linked-widget verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
