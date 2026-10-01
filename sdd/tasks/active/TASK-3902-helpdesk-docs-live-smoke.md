# TASK-3902: Documentation and env-gated live smoke

**Feature**: FEAT-616 — OdooHelpdeskToolkit — typed helpdesk tools for the Softhealer helpdesk (Odoo 19)
**Spec**: `sdd/specs/odoo-toolkit-upgrades.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3891, TASK-3901
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 10** (AC20). The doc is the operator-facing contract: every tool, the tenant
caveats (`state` ≠ lifecycle, no-op actions when company roles are unset, public comments reopen, timer
needs a default project) and the "one Odoo toolkit per agent" rule. The smoke replays the staging
verification end-to-end with the real toolkit and deletes everything it creates; it is a script, never a
pytest module.

---

## Scope

- Create `docs/tools/odoo-helpdesk.md`.
- Create `examples/odoo/helpdesk_live_smoke.py` (gated by `ODOO_HELPDESK_LIVE=1`).
- Run the smoke once against staging; record the outcome in the Completion Note.

**NOT in scope**: any change under `packages/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/tools/odoo-helpdesk.md` | CREATE | operator documentation |
| `examples/odoo/helpdesk_live_smoke.py` | CREATE | opt-in live replay |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# examples/odoo/helpdesk_live_smoke.py
import asyncio, os, sys
from parrot_tools.odoo import OdooHelpdeskToolkit                        # exported by TASK-3897
from parrot.interfaces.odoointerface import OdooError                    # verified: toolkit.py:39-45 region
```

### Existing Signatures to Use
```python
# OdooHelpdeskToolkit (TASK-3897–3901) public tools: create_ticket, get_ticket, search_tickets, take_ticket, reassign_ticket, add_ticket_comment,
#   close_ticket, reopen_ticket, resolve_ticket, move_ticket_to_stage, create_sla_policy, get_ticket_sla_status, mass_update_tickets, merge_tickets, ticket_stats,
#   list_helpdesk_stages/teams/categories/priorities, list_ticket_types, list_helpdesk_tags; inherited delete_record(model, record_id) (toolkit.py:564) for cleanup; stop() (toolkit.py:273).
# Constructor defaults from ODOO_HELPDESK_* (parrot.conf, TASK-3892); database may be "" for JSON-2.
# docs/ layout: check `ls docs/tools/` — create the directory if absent (mkdocs.yml nav is NOT edited by this task).
```

### Does NOT Exist
- ~~`pytest` markers for the smoke~~ — it must not be collected: the file lives under `examples/`, not `tests/`.
- ~~credentials in the repo~~ — the script reads the environment only.
- ~~`docs/tools/odoo.md`~~ — verify with `ls docs/tools/`; link to whatever Odoo toolkit doc exists, otherwise none.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/tools/odoo-helpdesk.md", "action": "CREATE"},
    {"path": "examples/odoo/helpdesk_live_smoke.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- The smoke creates at most: 2 tickets, 1 SLA policy; every id it creates is deleted in a `finally` (inherited `delete_record`), and it prints what it deleted.
- `examples/` may be git-ignored for some paths — check `git check-ignore -v examples/odoo/helpdesk_live_smoke.py`; use `git add -f` if needed and say so in the Completion Note.
- Never log credentials.

---

## Implementation Blueprint

### Steps (in order)
1. Write the doc — *why*: AC20 lists what it must contain.
2. Write the smoke script — *why*: reproducible evidence for future tenants.
3. Run it once with `ODOO_HELPDESK_LIVE=1` — *why*: closes the loop on the spec's live checks.

### `docs/tools/odoo-helpdesk.md` (CREATE)
```markdown
# OdooHelpdeskToolkit — Softhealer helpdesk on Odoo 19

`OdooHelpdeskToolkit(OdooToolkit)` (`parrot_tools.odoo.helpdesk`) adds helpdesk tools for Softhealer's
`sh_all_in_one_helpdesk` on top of the generic Odoo toolkit. Tools are prefixed `odoo_` and every inherited
`OdooToolkit` tool is exposed too.

> **One Odoo toolkit per agent.** Both classes register `odoo_*` names; loading them together raises a
> tool-name collision in `ToolManager`. Load only `OdooHelpdeskToolkit` (it is a superset). To narrow the
> surface, subclass and set `exclude_tools`.

## Configuration
`ODOO_HELPDESK_URL`, `ODOO_HELPDESK_USER`, `ODOO_HELPDESK_APIKEY` (preferred) or `ODOO_HELPDESK_PASSWORD`,
`ODOO_HELPDESK_DATABASE` (optional; empty lets JSON-2 infer it), `ODOO_HELPDESK_TIMEOUT`, `ODOO_HELPDESK_VERIFY_SSL`.
These never fall back to the generic `ODOO_*` keys.

## Tools
<!-- FILL IN: one table per group (reference data / tickets read / tickets write / assignment / transitions / SLA / stats & wizards / timer)
     with columns Tool · Input model · Result · Notes — names verbatim from helpdesk.py; mark cancel/merge/mass-update as "requires confirmation" — AC20 -->

## Tenant caveats (verified on staging, 2026-10-01)
- `state` is the reply direction (`customer_replied` / `staff_replied`), exposed as `replied_status`; the lifecycle is `stage_id` (+ `lifecycle` block).
- Stage roles live on `res.company` (`new/reopen/done/cancel/close_stage_id`). When `done_stage_id` / `cancel_stage_id` are unset, `action_done` /
  `action_cancel` are no-ops: `resolve_ticket` / `cancel_ticket` return `applied=False` with a warning. `close_ticket` always works.
- A **public** comment (`internal=False`) reopens a closed ticket when the company's "stage change when staff replied" setting is on; internal notes never do.
- `reopen_ticket` writes the stage directly when `action_open` does nothing (reported as `method_used="stage_write"`).
- `start_ticket_timer` needs a default project configured on the tenant; otherwise it returns `running=False` and a warning.
- JSON-2 `create` is rejected by Odoo 19 for helpdesk models; the transport falls back to `web_save` transparently.
```
**Why**: AC20's three required contents (tools, caveats, one-toolkit rule) are the section headings; the tools table is filled from the final method list so it cannot drift.

### `examples/odoo/helpdesk_live_smoke.py` (CREATE)
```python
"""Live smoke for OdooHelpdeskToolkit against a REAL Odoo (opt-in: ODOO_HELPDESK_LIVE=1).

Replays the FEAT-616 staging verification: create → take → close → note → public comment → reassign → mass update →
SLA policy → stats → merge, and DELETES every record it created. Never run under pytest.
"""
from __future__ import annotations

import asyncio
import os
import sys

from parrot.interfaces.odoointerface import OdooError
from parrot_tools.odoo import OdooHelpdeskToolkit


async def main() -> int:
    if os.environ.get("ODOO_HELPDESK_LIVE") != "1":
        print("skipped: set ODOO_HELPDESK_LIVE=1 (and ODOO_HELPDESK_*) to run against a real instance")
        return 0
    tk = OdooHelpdeskToolkit()
    created: list[tuple[str, int]] = []
    try:
        stages = await tk.list_helpdesk_stages()
        print("stages:", [i.name for i in stages.items])
        t1 = await tk.create_ticket(subject="[FEAT-616 smoke] ticket 1", partner_email="smoke@example.invalid", partner_name="FEAT-616 smoke")
        created.append(("sh.helpdesk.ticket", t1.ticket.id))
        # FILL IN: take_ticket, close_ticket (assert applied), add_ticket_comment(internal=True → not reopened), add_ticket_comment(internal=False → print reopened),
        #   reopen_ticket, second ticket + mass_update_tickets(stage="Open"), create_sla_policy(team=<first team name>, hours=1, stage="Closed") (append to created),
        #   get_ticket_sla_status, ticket_stats(), merge_tickets([t2, t1], into_ticket_id=t1) — print each result's key fields — spec §3 M10
        return 0
    except OdooError as exc:
        print("FAILED:", exc)
        return 1
    finally:
        for model, rid in reversed(created):
            try:
                await tk.delete_record(model=model, record_id=rid)
                print("deleted", model, rid)
            except OdooError as exc:  # keep going — leave nothing behind
                print("!! could not delete", model, rid, exc)
        await tk.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```
**Why**: the `finally` cleanup and the env gate are the two non-negotiables; the sequence mirrors the evidence files so a future tenant can be compared line by line.

### FILL IN checklist
- [ ] doc tools table; bounded by the final method list in `helpdesk.py`
- [ ] smoke sequence; bounded by spec §3 M10 and "delete everything"
- [ ] one live run recorded in the Completion Note

---

## Acceptance Criteria

- [ ] AC20 (spec): doc exists with all tools, caveats and the one-toolkit rule; the smoke ran once with all created records deleted.
- [ ] `ruff check examples/odoo/helpdesk_live_smoke.py` clean; `pytest --collect-only -q examples/odoo/helpdesk_live_smoke.py` collects nothing (no test functions).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_odoo_json2_transport.py -q` — the `create` fallback the smoke depends on
- `pytest packages/ai-parrot/tests/test_odoo_toolkit.py -q` — base toolkit regression gate (the helpdesk suite is TASK-3897–3901's gate; the smoke itself is manual evidence)

---

## Test Specification

No new unit tests; the live smoke is manual evidence.

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug odoo-toolkit-upgrades --feature-id FEAT-616`.
2. **Read the spec** (§3 M10, §7).
3. **Check dependencies** — TASK-3891 and TASK-3901 `done`.
4. **Verify the Codebase Contract** — `ls docs/tools/ examples/odoo/ 2>/dev/null`; `git check-ignore -v examples/odoo/helpdesk_live_smoke.py`.
5. **Update status** in the per-spec index → `"in-progress"`, commit only that file.
6. **Implement** from the blueprint.
7. **Verify** — Validation Commands; run the smoke once (`ODOO_HELPDESK_LIVE=1`).
8. **Commit the code** — only the two new files (`git add -f` if git-ignored; say so).
9. **Close the task** — `scripts/sdd/close_task.sh TASK-3902 odoo-toolkit-upgrades verified`.
10. **Fill in the Completion Note** with the smoke output summary (ids created and deleted), then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
