# TASK-3899: Transition tools with verified post-conditions

**Feature**: FEAT-616 — OdooHelpdeskToolkit — typed helpdesk tools for the Softhealer helpdesk (Odoo 19)
**Spec**: `sdd/specs/odoo-toolkit-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3898
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 7** (G3, AC9, AC10, AC11; design research S7). Live-verified on staging:
`action_closed` works from any stage (sets `close_date`, `close_by`, adds a stage-history line);
`action_done`, `action_open`, `action_cancel`, `action_approve` return `null` and change **nothing** because
the company's `done_stage_id` / `cancel_stage_id` are unset (`reopen_stage_id` is set and `action_open`
still did nothing). Writing `stage_id` works and also records history. Hence: every transition tool
computes `applied` from a post-condition read; only `reopen_ticket` (documented second step) and
`move_ticket_to_stage` (explicit) write `stage_id`.

---

## Scope

- Append to `OdooHelpdeskToolkit`: private `_transition(...)`, tools `close_ticket`, `reopen_ticket`, `resolve_ticket`,
  `approve_ticket`, `cancel_ticket`, `move_ticket_to_stage`.
- Append tests.

**NOT in scope**: assignment (TASK-3898), wizards (TASK-3901), any base-toolkit change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py` | MODIFY | append the transitions section |
| `packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py` | MODIFY | append tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# ADD to helpdesk.py import blocks:
from parrot_tools.odoo.models.helpdesk_envelopes import TicketTransitionResult                     # TASK-3895
from parrot_tools.odoo.models.helpdesk_inputs import (ApproveTicketInput, CancelTicketInput, CloseTicketInput, MoveTicketToStageInput,
                                                       ReopenTicketInput, ResolveTicketInput)    # TASK-3894
```

### Existing Signatures to Use
```python
# helpdesk.py (TASK-3897/3898): TICKET_MODEL; self._execute; self._read_one(model, id, fields); self._load_ticket(id, include_extra=False);
#   self._resolve_ref("stage", value); self._stage_map() → {id: {"name", ...}}; self._company_stage_config() → {"new","reopen","done","cancel","close",...: id|None};
#   self.add_ticket_comment(ticket_id, body, internal=True)  (TASK-3898)
# TicketTransitionResult(ticket_id, action, applied, method_used: "action"|"stage_write"|"none", from_stage, to_stage, warnings, ticket)   # TASK-3895
# Live facts (spec §6): action_closed [[id]] → None, stage → close role, close_date set; action_done/open/cancel/approve [[id]] → None, no change;
#   write [[id], {"stage_id": X}] → True; an act_window dict return means "opened a wizard".
```

### Does NOT Exist
- ~~a `fallback` inside `resolve_ticket` / `approve_ticket` / `cancel_ticket`~~ — forbidden (AC10).
- ~~`action_reopen`~~ — the Softhealer method is `action_open`.
- ~~`helpdesk.stages.is_close` / `fold`~~ — closed-ness comes from company roles (`_company_stage_config`).
- ~~Softhealer `action_cancel(reason)` signature~~ — `cancel_reason` is written first, then `action_cancel([[id]])` with no kwargs.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py#OdooToolkit._execute",
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py#OdooToolkit._read_one"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `applied` = stage changed, or (action is `action_closed` and `close_date` became set). Never assume.
- A dict return whose `type == "ir.actions.act_window"` → warning "action opened a wizard; not applied", `applied=False`.
- `expected_stage` mismatch → `ValueError` **before** any RPC beyond the initial read.
- Only `reopen_ticket` and `move_ticket_to_stage` issue a `write` of `stage_id`; `reopen_ticket` only after `action_open` produced no change (AC11).
- `cancel_ticket` is in `confirming_tools` (TASK-3897) — no extra code here.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_transition` — *why*: one driver enforces AC9 for all six tools.
2. Add the six tools — *why*: each is a two-line call into the driver with its documented semantics.
3. Append tests — *why*: AC10/AC11 are "no write" / "one write" assertions on the mock.

### `packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3898: grep -c 'async def reassign_ticket' packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py)
# AFTER — append below the end of `reassign_ticket`, inside the class:

    # ── Transitions (FEAT-616 M7): action first, post-condition verified ───
    async def _transition(self, ticket_id: int, action: str, *, expected_stage: int | None = None,
                          fallback_stage: int | None = None, pre_write: dict[str, Any] | None = None) -> TicketTransitionResult:
        """Run ``action`` on the ticket, re-read it and report whether anything changed.

        ``fallback_stage`` (only reopen/move use it) is written ONLY when the action changed nothing and is
        reported as ``method_used="stage_write"`` with a warning — never silently.
        """
        before = await self._read_one(TICKET_MODEL, ticket_id, ["stage_id", "close_date"])
        from_id = before["stage_id"][0] if before.get("stage_id") else None
        if expected_stage is not None and from_id != expected_stage:
            raise ValueError(f"Ticket {ticket_id} is in stage {before.get('stage_id')!r}, expected id {expected_stage}")
        warnings: list[str] = []
        if pre_write:
            await self._execute(TICKET_MODEL, "write", [[ticket_id], pre_write])
        method_used: str = "none"
        if action:
            result = await self._execute(TICKET_MODEL, action, [[ticket_id]])
            if isinstance(result, dict) and result.get("type") == "ir.actions.act_window":
                warnings.append(f"{action} opened a wizard ({result.get('res_model')}); not applied")
        after = await self._read_one(TICKET_MODEL, ticket_id, ["stage_id", "close_date"])
        applied = after.get("stage_id") != before.get("stage_id") or (action == "action_closed" and bool(after.get("close_date")) and not before.get("close_date"))
        if applied:
            method_used = "action"
        elif action:
            warnings.append(f"{action} produced no change on this instance (company stage role not configured?)")
        if not applied and fallback_stage is not None:
            # FILL IN: write {"stage_id": fallback_stage}; re-read `after`; applied = stage changed; method_used = "stage_write";
            #   warnings.append("stage written directly") — AC11
            ...
        ticket = await self._load_ticket(ticket_id, include_extra=False)
        return TicketTransitionResult(ticket_id=ticket_id, action=action or "write", applied=applied, method_used=method_used,
                                      from_stage=before["stage_id"][1] if before.get("stage_id") else None,
                                      to_stage=after["stage_id"][1] if after.get("stage_id") else None, warnings=warnings, ticket=ticket)

    @requires_permission("odoo.write")
    @tool_schema(CloseTicketInput)
    async def close_ticket(self, ticket_id: int, comment: Optional[str] = None) -> TicketTransitionResult:
        """Close a ticket (Softhealer ``action_closed``: sets close_date/close_by, moves to the company close stage). Optional internal note first."""
        if comment:
            await self.add_ticket_comment(ticket_id, comment, internal=True)
        return await self._transition(ticket_id, "action_closed")

    @requires_permission("odoo.write")
    @tool_schema(ReopenTicketInput)
    async def reopen_ticket(self, ticket_id: int, to_stage: Optional[int | str] = None) -> TicketTransitionResult:
        """Reopen: ``action_open`` first; if it changes nothing, the stage is written directly (reported as stage_write)."""
        roles = await self._company_stage_config()
        # FILL IN: target = resolve(to_stage) if given else roles["reopen"] or await self._resolve_ref("stage", "Open") — spec §3 M7
        target = 0
        return await self._transition(ticket_id, "action_open", fallback_stage=target)

    @requires_permission("odoo.write")
    @tool_schema(ResolveTicketInput)
    async def resolve_ticket(self, ticket_id: int) -> TicketTransitionResult:
        """Mark resolved (Softhealer ``action_done``). No fallback: if the company has no done stage the result says applied=False."""
        result = await self._transition(ticket_id, "action_done")
        # FILL IN: if (await self._company_stage_config()).get("done") is None: result.warnings.append("done stage not configured on company; action_done cannot apply")
        return result

    # FILL IN: approve_ticket → _transition(ticket_id, "action_approve") (no fallback);
    #   cancel_ticket(ticket_id, reason) → _transition(ticket_id, "action_cancel", pre_write={"cancel_reason": reason}) + "cancel stage not configured" warning when roles["cancel"] is None (AC10);
    #   move_ticket_to_stage(ticket_id, stage, expected_current_stage=None) → target = resolve("stage", stage); expected = resolve when given;
    #   _transition(ticket_id, "", expected_stage=expected, fallback_stage=target) with action "" meaning "no action, write only" — method_used must be "stage_write"
```
**Why this shape**: `_transition` is the S7 contract in code — one read before, one after, `applied` from evidence, wizard detection, and the fallback only where the tool's documented semantics say so. `move_ticket_to_stage` reuses the driver with an empty action so the post-condition and envelope stay identical.

### `packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3898: grep -c 'def test_take_assign_reassign_call_tuples' packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py)
# AFTER — append at end of file:

# ── M7: transitions ──────────────────────────────────────────────────────────

def _stage_reads(before, after, close_before=False, close_after=False):
    return [[{"id": 1, "stage_id": before, "close_date": close_before}], [{"id": 1, "stage_id": after, "close_date": close_after}]]


@pytest.mark.asyncio
async def test_close_ticket_applied_via_action():
    transport = _fake_transport(); tk = _make_helpdesk_toolkit(transport)
    reads = _stage_reads([22, "Open"], [21, "Closed"], False, "2026-09-30 22:37:43")
    transport.execute_kw.side_effect = [reads[0], None, reads[1]] + ["<FILL IN: _load_ticket responses>"]
    # FILL IN: complete the side_effect with the _load_ticket reads (ticket, stages, user, company); call close_ticket(1);
    #   assert result.applied and result.method_used == "action" and awaited tuple (TICKET_MODEL, "action_closed", [[1]], None)
    ...


@pytest.mark.asyncio
async def test_resolve_ticket_noop_reports_not_applied():
    # FILL IN: reads Open→Open, action_done → None; assert applied False, method_used "none", a warning mentioning "no change",
    #   and NO execute_kw call with method "write" — AC10
    ...


@pytest.mark.asyncio
async def test_reopen_ticket_falls_back_to_stage_write():
    # FILL IN: reads Closed→Closed after action_open, then write → True, then re-read Open; assert exactly ONE write call
    #   == (TICKET_MODEL, "write", [[1], {"stage_id": 22}], None), method_used == "stage_write", applied True — AC11
    ...


@pytest.mark.asyncio
async def test_move_ticket_to_stage_expected_stage_mismatch_raises_before_rpc():
    transport = _fake_transport(); tk = _make_helpdesk_toolkit(transport)
    transport.execute_kw.side_effect = [STAGES_ROWS, [{"id": 1, "stage_id": [4, "New"], "close_date": False}]]
    with pytest.raises(ValueError, match="expected"):
        await tk.move_ticket_to_stage(ticket_id=1, stage=22, expected_current_stage=22)
    assert not any(c.args[1] == "write" for c in transport.execute_kw.await_args_list)


# FILL IN: test_cancel_ticket_writes_reason_then_action — call order: read, write {"cancel_reason": "dup"}, action_cancel, read; no stage write — AC10
```
**Why**: the assertions are on the mock's call list, which is the only way to prove AC10 ("no write") and AC11 ("exactly one write, after the action").

### FILL IN checklist
- [ ] `_transition` fallback branch; bounded by AC11
- [ ] `reopen_ticket` target resolution; bounded by spec §3 M7
- [ ] `resolve_ticket` warning, `approve_ticket`, `cancel_ticket`, `move_ticket_to_stage`; bounded by AC9–AC11
- [ ] five test bodies

---

## Acceptance Criteria

- [ ] AC9, AC10, AC11 (spec).
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py -q`

---

## Test Specification

See the blueprint (five tests).

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug odoo-toolkit-upgrades --feature-id FEAT-616`.
2. **Read the spec** (§2 rule 1, §3 M7, §7 "Tenant no-op actions").
3. **Check dependencies** — TASK-3898 `done`.
4. **Verify the Codebase Contract** — re-run the two `grep -c` anchors.
5. **Update status** in the per-spec index → `"in-progress"`, commit only that file.
6. **Implement** from the blueprint.
7. **Verify** — Validation Commands.
8. **Commit the code** — only the two listed files.
9. **Close the task** — `scripts/sdd/close_task.sh TASK-3899 odoo-toolkit-upgrades verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
