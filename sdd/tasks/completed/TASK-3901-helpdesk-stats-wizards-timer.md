# TASK-3901: Ticket stats, merge / mass-update wizards, timesheet timer

**Feature**: FEAT-616 — OdooHelpdeskToolkit — typed helpdesk tools for the Softhealer helpdesk (Odoo 19)
**Spec**: `sdd/specs/odoo-toolkit-upgrades.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3900
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 9** (G3, AC15, AC22; design research S6/S11). Live-verified: the mass-update
wizard (`create` + `update_record([[wid]])`) moves stages; the merge wizard needs `sh_partner_id` and
`action_merge_tickets([[wid]])` returns `None`, closes the sources and fills the target's
`sh_merge_ticket_ids`; `action_ticket_start` raises *"Please Set Default Project from configuration!"* on
this tenant; `action_ticket_end` returns an `act_window` on `ticket.time.account.line` (fields `name`,
`start_date`, `end_date`, `duration`, `project_id`; button `end_ticket`). `ticket_stats` needs
`formatted_read_group` over JSON-2, which FEAT-614 fixes (the worktree is created after it merges).

---

## Scope

- Append to `OdooHelpdeskToolkit`: `ticket_stats`, `merge_tickets`, `mass_update_tickets`, `start_ticket_timer`, `stop_ticket_timer`.
- Append tests.

**NOT in scope**: changing `aggregate_records` or the transports; SLA (TASK-3900).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py` | MODIFY | append stats/wizards/timer section |
| `packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py` | MODIFY | append tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# ADD to helpdesk.py import blocks:
from parrot.interfaces.odoointerface import OdooRPCError                                                  # verified: toolkit.py:39-45 region imports it
from parrot_tools.odoo.helpdesk_normalize import normalize_stats_groups                                    # TASK-3896
from parrot_tools.odoo.models.helpdesk_envelopes import TicketStatsResult, TicketTimerResult, WizardResult # TASK-3895
from parrot_tools.odoo.models.helpdesk_inputs import (MassUpdateTicketsInput, MergeTicketsInput, StartTicketTimerInput,
                                                       StopTicketTimerInput, TicketStatsInput)             # TASK-3894
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py
async def _get_odoo_major_version(self) -> int | None                   # line 982 — >= 19 → formatted_read_group, else read_group (same rule as aggregate_records :994)
# helpdesk.py: TICKET_MODEL, self._execute, self._resolve_ref, self._closed_stage_ids() (TASK-3897), self._read_one
# Live facts (spec §6): merge wizard create {sh_helpdesk_ticket_ids [[6,0,ids]], sh_select_type "existing"|"new", sh_existing_ticket, sh_select_merge_type,
#   sh_merge_history, sh_partner_id} → [wid]; action_merge_tickets [[wid]] → None; target sh_merge_ticket_ids lists all ids, sh_merge_ticket_count = len;
#   mass update create {helpdesks_ticket_ids [[6,0,ids]], check_helpdesks_state, helpdesk_stages, check_assign_to, assign_to, check_team_id, team_id,
#   check_add_remove, followers, ticket_follower_update_type} → [wid]; update_record [[wid]] → None;
#   action_ticket_start [[id]] → raises OdooRPCError "...Set Default Project..." when unconfigured; action_ticket_end [[id]] → {"type": "ir.actions.act_window", "res_model": "ticket.time.account.line", "context"?: {...}};
#   ticket.time.account.line fields name R, start_date, end_date, duration, project_id; button end_ticket [[line_id]].
```

### Does NOT Exist
- ~~`aggregate_records` reuse for stats~~ — call `formatted_read_group` / `read_group` directly (the helpdesk normalises its own shape, S11).
- ~~`sh.helpdesk.ticket.merge.ticket.wizard.action_merge`~~ — the button is `action_merge_tickets`.
- ~~mass-update button `action_confirm`~~ — it is `update_record`.
- ~~`_DOMAIN_FIRST_METHODS` in this task~~ — provided by FEAT-614; do not add it.

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
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py#OdooToolkit._get_odoo_major_version",
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py#OdooToolkit._execute"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `ticket_stats`: ≥19 → `formatted_read_group([domain], {"groupby": [g], "aggregates": ["__count"]})`; ≤18 → `read_group([domain], {"groupby": [g], "fields": ["id:count"], "lazy": False})`; on `OdooRPCError` and `group_by == "stage_id"` → per-stage `search_count` (`source_method="search_count"`); otherwise re-raise (AC15).
- `merge_tickets` / `mass_update_tickets` are in `confirming_tools` (TASK-3897) — nothing to add here.
- Timer errors become `warnings`, never exceptions (tenant config).

---

## Implementation Blueprint

### Steps (in order)
1. Add `ticket_stats` — *why*: AC15 with the three sources.
2. Add the two wizard tools — *why*: verified create + button shapes.
3. Add the timer tools — *why*: tenant-dependent; warnings, not failures.
4. Append tests.

### `packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3900: grep -c 'async def list_ticket_alarms' packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py)
# AFTER — append below the end of `list_ticket_alarms`, inside the class:

    # ── Stats, wizards, timer (FEAT-616 M9) ─────────────────────────────────
    @tool_schema(TicketStatsInput)
    async def ticket_stats(self, group_by: str = "stage_id", only_open: bool = False, domain: Optional[list[Any]] = None,
                           created_after: Optional[str] = None, created_before: Optional[str] = None) -> TicketStatsResult:
        """Count tickets grouped by stage/team/assignee/category/priority/type (server-side aggregation; normalised across Odoo versions)."""
        clauses: list[Any] = list(domain or [])
        # FILL IN: created_after/before → ("create_date", ">=" / "<=", v); only_open → ("stage_id","not in", await self._closed_stage_ids())
        version = await self._get_odoo_major_version()
        try:
            if version is not None and version >= 19:
                rows = await self._execute(TICKET_MODEL, "formatted_read_group", [clauses], {"groupby": [group_by], "aggregates": ["__count"]})
                source = "formatted_read_group"
            else:
                rows = await self._execute(TICKET_MODEL, "read_group", [clauses], {"groupby": [group_by], "fields": ["id:count"], "lazy": False})
                source = "read_group"
        except OdooRPCError as exc:
            if group_by != "stage_id":
                raise
            self.logger.warning("ticket_stats: aggregation failed (%s); falling back to per-stage search_count", exc)
            # FILL IN: rows = [{"stage_id": [sid, row["name"]], "__count": await self._execute(TICKET_MODEL, "search_count", [clauses + [("stage_id","=",sid)]])}
            #   for sid, row in (await self._stage_map()).items()]; source = "search_count" — AC15
            rows, source = [], "search_count"
        groups = normalize_stats_groups(rows or [], group_by, source)
        return TicketStatsResult(group_by=group_by, groups=groups, total=sum(g.count for g in groups), source_method=source)

    @requires_permission("odoo.write")
    @tool_schema(MergeTicketsInput)
    async def merge_tickets(self, ticket_ids: list[int], into_ticket_id: Optional[int] = None, merged_action: str = "close",
                            merge_history: bool = True) -> WizardResult:
        """Merge tickets through the Softhealer merge wizard into ``into_ticket_id`` (or a new ticket). Requires confirmation."""
        target = into_ticket_id or ticket_ids[0]
        partner = await self._read_one(TICKET_MODEL, target, ["partner_id"])
        values: dict[str, Any] = {
            "sh_helpdesk_ticket_ids": [[6, 0, ticket_ids]], "sh_select_type": "existing" if into_ticket_id else "new",
            "sh_select_merge_type": merged_action, "sh_merge_history": merge_history,
            "sh_partner_id": partner["partner_id"][0] if partner.get("partner_id") else False,
        }
        if into_ticket_id:
            values["sh_existing_ticket"] = into_ticket_id
        wizard = await self._execute("sh.helpdesk.ticket.merge.ticket.wizard", "create", [values])
        wizard_id = int(wizard[0] if isinstance(wizard, list) else wizard)
        await self._execute("sh.helpdesk.ticket.merge.ticket.wizard", "action_merge_tickets", [[wizard_id]])
        # FILL IN: when into_ticket_id: read target ["sh_merge_ticket_count"] → applied = count >= len(ticket_ids), result_ticket_id = target;
        #   when new: search_read [("sh_merge_ticket_ids","in",ticket_ids)] order "id desc" limit 1 → result_ticket_id, applied = found — AC22
        raise NotImplementedError

    # FILL IN: mass_update_tickets(ticket_ids, stage=None, assignee=None, team=None, add_followers=None, remove_followers=None) → wizard values with the
    #   check_* flags set only for given fields (stage → check_helpdesks_state + helpdesk_stages; assignee → check_assign_to + assign_to; team → check_team_id + team_id;
    #   followers → check_add_remove + followers [[6,0,ids]] + ticket_follower_update_type "add"/"remove"), create, update_record [[wid]] → WizardResult(applied=True, message=...);
    #   start_ticket_timer(ticket_id) → try action_ticket_start [[id]] except OdooRPCError as exc → TicketTimerResult(running=False, warnings=[str(exc)]);
    #   success → read ["ticket_running","start_time"] → TicketTimerResult(running=True, started_at=...);
    #   stop_ticket_timer(ticket_id, description=None) → action_ticket_end [[id]] → act_window dict: create ticket.time.account.line
    #   {"name": description or f"Ticket {ticket_id}", "start_date": ticket.start_time, "end_date": now (UTC 'YYYY-MM-DD HH:MM:SS'), "project_id": ctx default_project_id if present}
    #   then end_ticket [[line_id]] → TicketTimerResult(running=False, duration_hours=line.duration); any OdooRPCError → warnings — spec §3 M9
```
**Why this shape**: `ticket_stats` follows `aggregate_records`' version split (toolkit.py:994) but normalises at the helpdesk boundary (S11); wizard values are the live-verified dicts; timer tools surface tenant configuration problems as warnings so an agent can explain them instead of crashing.

### `packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3900: grep -c 'def test_list_ticket_alarms_envelope' packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py)
# AFTER — append at end of file:

# ── M9: stats, wizards, timer ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ticket_stats_odoo19_formatted_read_group():
    transport = _fake_transport(); tk = _make_helpdesk_toolkit(transport)
    transport.execute_kw.side_effect = [[{"stage_id": [4, "New"], "__count": 22}, {"stage_id": False, "__count": 1}]]
    result = await tk.ticket_stats()
    assert transport.execute_kw.await_args.args == (TICKET_MODEL, "formatted_read_group", [[]], {"groupby": ["stage_id"], "aggregates": ["__count"]})
    assert [(g.key, g.count) for g in result.groups] == [(4, 22), (None, 1)] and result.total == 23 and result.source_method == "formatted_read_group"


# FILL IN: test_ticket_stats_odoo17_read_group (transport.version → "17.0"; method read_group, kwargs {"groupby": ["stage_id"], "fields": ["id:count"], "lazy": False}),
#   test_ticket_stats_fallback_search_count (formatted_read_group raises OdooRPCError → stages read + one search_count per stage; source_method "search_count"),
#   test_merge_tickets_wizard_calls (create values incl. sh_partner_id and sh_existing_ticket; action_merge_tickets [[1]]; applied from sh_merge_ticket_count),
#   test_mass_update_tickets_wizard_calls (check_helpdesks_state True + helpdesk_stages 22; update_record [[2]]),
#   test_start_ticket_timer_surfaces_config_error_as_warning (execute_kw raises OdooRPCError("...Set Default Project...") → running False, warning contains "Default Project")
```
**Why**: `_fake_transport().version` returns serie `19.0` by default (copy of `test_odoo_toolkit.py:70-76`), so the Odoo 19 path is the default and the 17 path overrides `transport.version.return_value`.

### FILL IN checklist
- [ ] `ticket_stats` clauses + fallback rows; bounded by AC15
- [ ] `merge_tickets` result assembly; bounded by AC22
- [ ] `mass_update_tickets`, `start_ticket_timer`, `stop_ticket_timer`; bounded by spec §3 M9
- [ ] five test bodies

---

## Acceptance Criteria

- [ ] AC15, AC22 (spec).
- [ ] `merge_tickets` and `mass_update_tickets` are `@requires_permission("odoo.write")` and appear in `confirming_tools`.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py -q`

---

## Test Specification

See the blueprint (six tests).

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug odoo-toolkit-upgrades --feature-id FEAT-616`.
2. **Read the spec** (§3 M9, §6 live facts, §7 "Timer needs Default Project").
3. **Check dependencies** — TASK-3900 `done`; FEAT-614 merged in `dev` (needed for the live stats path only).
4. **Verify the Codebase Contract** — re-run the two `grep -c` anchors; confirm `_get_odoo_major_version` line in `toolkit.py`.
5. **Update status** in the per-spec index → `"in-progress"`, commit only that file.
6. **Implement** from the blueprint; remove every `raise NotImplementedError`.
7. **Verify** — Validation Commands.
8. **Commit the code** — only the two listed files.
9. **Close the task** — `scripts/sdd/close_task.sh TASK-3901 odoo-toolkit-upgrades verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

**Completed by**: sdd-worker (FEAT-616)
**Date**: 2026-10-01
**Notes**: gpt-5.6-terra (codex): helpdesk.py additions + tests; test_odoo_*.py 220 passed. Diff reviewed vs contract; task tests run with `pytest --noconftest` (repo conftest broken by pre-existing venv issue); merge-tier sweep red on unrelated failures, accepted by user.

**Deviations from spec**: none | describe if any
