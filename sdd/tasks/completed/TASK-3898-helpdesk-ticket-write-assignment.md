# TASK-3898: Ticket write, comments, attachments and assignment tools

**Feature**: FEAT-616 — OdooHelpdeskToolkit — typed helpdesk tools for the Softhealer helpdesk (Odoo 19)
**Spec**: `sdd/specs/odoo-toolkit-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3897
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 6** (G3, AC8, AC12). Live-verified facts this task encodes: `create` goes through
`_execute` so TASK-3891's `web_save` fallback applies; `message_post` works kwargs-only and a **public**
comment (`mail.mt_comment`) reopens a Closed ticket while an internal note (`mail.mt_note`) does not;
`action_take_ticket` sets `user_id` to the caller; the reassign wizard is `create` + `action_confirm([[wid]])`;
`sh_user_ids` accepts a `[[6, 0, ids]]` write. `UpdateTicketInput` (TASK-3894) already excludes lifecycle fields.

---

## Scope

- Append to `OdooHelpdeskToolkit` (`helpdesk.py`): `create_ticket`, `update_ticket`, `add_ticket_comment`,
  `attach_to_ticket`, `assign_ticket`, `take_ticket`, `reassign_ticket`, plus private `_find_or_create_partner`.
- Append the tests to `test_odoo_helpdesk_toolkit.py`.

**NOT in scope**: transitions (TASK-3899), SLA (TASK-3900), wizards other than reassign (TASK-3901).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py` | MODIFY | append the write/assignment section |
| `packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py` | MODIFY | append tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# helpdesk.py (TASK-3897) already imports tool_schema, requires_permission, HelpdeskTicket, TicketResult, normalize_ticket, TICKET_MODEL.
# ADD to its import blocks:
from parrot_tools.odoo.models.envelopes import BinaryFieldResult                                     # verified: envelopes.py:146
from parrot_tools.odoo.models.helpdesk_envelopes import TicketAssignmentResult, TicketCommentResult   # TASK-3895
from parrot_tools.odoo.models.helpdesk_inputs import (AddTicketCommentInput, AssignTicketInput, AttachToTicketInput, CreateTicketInput,
                                                       ReassignTicketInput, TakeTicketInput, UpdateTicketInput)   # TASK-3894
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py  (verified at b3141f286)
async def create_record(self, model: str, values: dict) -> CreateResult          # line 493 — pattern: new_id = await self._execute(model, "create", [values]); then _read_one
async def attach_document(self, res_model: str, res_id: int, name: str, source: str, mimetype=None, description=None) -> BinaryFieldResult   # line 928
@requires_permission("odoo.write") @tool_schema(...)                            # decorator order used at line 491-492
# helpdesk.py (TASK-3897): TICKET_MODEL, self._resolve_ref(kind, value), self._resolve_refs, self._load_ticket(id), self._ticket_url(id), self._ensure_transport() (→ .uid)
# Live facts (spec §6): action_take_ticket [[id]] → True, sets user_id=uid; sh.helpdesk.reassign.wizard create {ticket_id, new_user_id} → [wid]; action_confirm [[wid]] → {'type': 'ir.actions.act_window_close'};
#   message_post kwargs {"body", "message_type": "comment", "subtype_xmlid": "mail.mt_note" | "mail.mt_comment", "attachment_ids"} → message id; mt_comment reopens Closed → Open.
```

### Does NOT Exist
- ~~`web_save` calls in the helpdesk layer~~ — `create` only via `self._execute(model, "create", [values])`.
- ~~`message_post` positional body~~ — kwargs only (positional would be misrouted by `_build_body`).
- ~~`UpdateTicketInput.stage` / `.assignee`~~ — excluded by AC8; `update_ticket` has no such parameters.
- ~~`res.partner` name_search~~ — partner lookup uses `search_read` on `email` (exact, case-insensitive `=ilike`) then `name =`.

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
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py#OdooToolkit.create_record",
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py#OdooToolkit.attach_document",
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py#OdooToolkit._execute"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every tool here is `@requires_permission("odoo.write")` + `@tool_schema(<Input>)`, in that order (toolkit.py:491-492).
- `create_ticket` writes only resolved ids; `tags` as `[[6, 0, ids]]`; `description` wrapped in `<p>…</p>` unless it contains `<`.
- `add_ticket_comment` defaults to internal (`mail.mt_note`) and reports `reopened` by comparing `stage_id` before/after (AC12).
- Every write tool ends with `_load_ticket` (action-then-read-back).

---

## Implementation Blueprint

### Steps (in order)
1. Add the imports and `_find_or_create_partner` — *why*: `create_ticket`'s only non-mechanical branch.
2. Add `create_ticket` and `update_ticket` — *why*: AC8 boundary is the input model; the tool just resolves refs and writes.
3. Add `add_ticket_comment` and `attach_to_ticket` — *why*: AC12.
4. Add `assign_ticket`, `take_ticket`, `reassign_ticket` — *why*: three verified server paths, one envelope.
5. Append tests.

### `packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3897: grep -c 'async def get_ticket_extra_fields' packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py)
# AFTER — append below the end of `get_ticket_extra_fields` (last method TASK-3897 added), inside the class:

    # ── Ticket writes, comments, attachments (FEAT-616 M6) ─────────────────
    async def _find_or_create_partner(self, partner_id: int | None, email: str | None, name: str | None) -> int:
        """Resolve the customer: explicit id → by email (=ilike) → by exact name → create ``res.partner``."""
        if partner_id:
            return partner_id
        # FILL IN: search_read res.partner [("email","=ilike",email)] fields ["id"] limit 1 when email; else [("name","=",name)];
        #   found → id; else create via self._execute("res.partner", "create", [{"name": name or email, "email": email}]) — spec §3 M6
        raise NotImplementedError

    @requires_permission("odoo.write")
    @tool_schema(CreateTicketInput)
    async def create_ticket(self, subject: str, partner_id: Optional[int] = None, partner_email: Optional[str] = None,
                            partner_name: Optional[str] = None, description: Optional[str] = None, category: Optional[int | str] = None,
                            sub_category: Optional[int | str] = None, priority: Optional[int | str] = None, team: Optional[int | str] = None,
                            ticket_type: Optional[int | str] = None, tags: Optional[list[int | str]] = None, assignee: Optional[int | str] = None,
                            email: Optional[str] = None, mobile_no: Optional[str] = None, person_name: Optional[str] = None,
                            due_date: Optional[str] = None, replied_status: str = "customer_replied") -> TicketResult:
        """Create a helpdesk ticket. References (category, priority, team, type, tags, assignee) accept an id or a name."""
        values: dict[str, Any] = {
            "partner_id": await self._find_or_create_partner(partner_id, partner_email, partner_name),
            "state": replied_status,
            "email_subject": subject,
        }
        if description:
            values["description"] = description if "<" in description else f"<p>{description}</p>"
        # FILL IN: for (kind, field, value) in (("category","category_id",category), ("sub_category","sub_category_id",sub_category),
        #   ("priority","priority",priority), ("team","team_id",team), ("ticket_type","ticket_type",ticket_type), ("user","user_id",assignee)):
        #   if value is not None: values[field] = await self._resolve_ref(kind, value); tags → values["tag_ids"] = [[6, 0, ids]];
        #   email/mobile_no/person_name/due_date(→"sh_due_date") copied when given — spec §3 M6
        new_id = await self._execute(TICKET_MODEL, "create", [values])
        ticket_id = int(new_id[0] if isinstance(new_id, list) else new_id)
        self.logger.info("create_ticket: created %s #%s", TICKET_MODEL, ticket_id)
        return TicketResult(ticket=await self._load_ticket(ticket_id), url=self._ticket_url(ticket_id))

    @requires_permission("odoo.write")
    @tool_schema(UpdateTicketInput)
    async def update_ticket(self, ticket_id: int, subject: Optional[str] = None, description: Optional[str] = None, comment: Optional[str] = None,
                            customer_comment: Optional[str] = None, email: Optional[str] = None, email_cc: Optional[str] = None,
                            mobile_no: Optional[str] = None, person_name: Optional[str] = None, due_date: Optional[str] = None,
                            category: Optional[int | str] = None, sub_category: Optional[int | str] = None, priority: Optional[int | str] = None,
                            team: Optional[int | str] = None, ticket_type: Optional[int | str] = None, tags: Optional[list[int | str]] = None) -> TicketResult:
        """Patch descriptive ticket fields. Stage, assignee and SLA changes have dedicated tools and are NOT accepted here."""
        patch: dict[str, Any] = {}
        # FILL IN: same mapping as create_ticket for the given (non-None) values; subject → "email_subject"; due_date → "sh_due_date";
        #   raise ValueError("nothing to update") when patch is empty — AC8
        await self._execute(TICKET_MODEL, "write", [[ticket_id], patch])
        return TicketResult(ticket=await self._load_ticket(ticket_id), url=self._ticket_url(ticket_id))

    @requires_permission("odoo.write")
    @tool_schema(AddTicketCommentInput)
    async def add_ticket_comment(self, ticket_id: int, body: str, internal: bool = True, attachment_ids: Optional[list[int]] = None) -> TicketCommentResult:
        """Post a note (internal, default) or a public comment on a ticket. A public comment may REOPEN a closed ticket; the result says so."""
        before = await self._read_one(TICKET_MODEL, ticket_id, ["stage_id"])
        kwargs: dict[str, Any] = {"body": body, "message_type": "comment", "subtype_xmlid": "mail.mt_note" if internal else "mail.mt_comment"}
        if attachment_ids:
            kwargs["attachment_ids"] = attachment_ids
        message_id = await self._execute(TICKET_MODEL, "message_post", [[ticket_id]], kwargs)
        after = await self._read_one(TICKET_MODEL, ticket_id, ["stage_id"])
        # FILL IN: message_id may be int or [int]; reopened = before["stage_id"] != after["stage_id"]; stage_after = after name — AC12
        raise NotImplementedError

    @requires_permission("odoo.write")
    @tool_schema(AttachToTicketInput)
    async def attach_to_ticket(self, ticket_id: int, name: str, source: str, mimetype: Optional[str] = None, description: Optional[str] = None) -> BinaryFieldResult:
        """Attach a file (URL or base64) to a ticket as ``ir.attachment``."""
        return await self.attach_document(res_model=TICKET_MODEL, res_id=ticket_id, name=name, source=source, mimetype=mimetype, description=description)
```
**Why this shape**: spec §3 M6 fixes the value mapping and the `message_post` kwargs (verified live); `before/after` reads implement AC12 without guessing Softhealer's reply logic.

### `…/helpdesk.py` (MODIFY — continued, same append)
```python
    # ── Assignment ──────────────────────────────────────────────────────────
    async def _assignment_result(self, ticket_id: int, method_used: str) -> TicketAssignmentResult:
        ticket = await self._load_ticket(ticket_id, include_extra=False)
        return TicketAssignmentResult(ticket_id=ticket_id, assignee=ticket.user_id, additional_assignees=list(ticket.sh_user_ids or []),
                                      method_used=method_used, ticket=ticket)

    @requires_permission("odoo.write")
    @tool_schema(AssignTicketInput)
    async def assign_ticket(self, ticket_id: int, assignee: int | str, additional_assignees: Optional[list[int | str]] = None) -> TicketAssignmentResult:
        """Assign a ticket to a user (id, login or name); ``additional_assignees`` replaces the multi-user list."""
        values: dict[str, Any] = {"user_id": await self._resolve_ref("user", assignee)}
        if additional_assignees is not None:
            values["sh_user_ids"] = [[6, 0, await self._resolve_refs("user", additional_assignees)]]
        await self._execute(TICKET_MODEL, "write", [[ticket_id], values])
        return await self._assignment_result(ticket_id, "write")

    @requires_permission("odoo.write")
    @tool_schema(TakeTicketInput)
    async def take_ticket(self, ticket_id: int) -> TicketAssignmentResult:
        """Assign the ticket to the connected user (Softhealer/TROC ``action_take_ticket``)."""
        await self._execute(TICKET_MODEL, "action_take_ticket", [[ticket_id]])
        return await self._assignment_result(ticket_id, "action_take_ticket")

    @requires_permission("odoo.write")
    @tool_schema(ReassignTicketInput)
    async def reassign_ticket(self, ticket_id: int, new_assignee: int | str) -> TicketAssignmentResult:
        """Reassign through the TROC reassign wizard (``sh.helpdesk.reassign.wizard`` → ``action_confirm``)."""
        new_user = await self._resolve_ref("user", new_assignee)
        wizard = await self._execute("sh.helpdesk.reassign.wizard", "create", [{"ticket_id": ticket_id, "new_user_id": new_user}])
        wizard_id = int(wizard[0] if isinstance(wizard, list) else wizard)
        await self._execute("sh.helpdesk.reassign.wizard", "action_confirm", [[wizard_id]])
        return await self._assignment_result(ticket_id, "reassign_wizard")
```
**Why**: three verified server paths (write, action, wizard) behind one envelope; the wizard returns `[id]` on this build, hence the list guard.

### `packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3897: grep -c 'def test_get_ticket_loads_extra_fields_and_lifecycle' packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py)
# AFTER — append at end of file:

# ── M6: writes, comments, assignment ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_ticket_resolves_refs_and_calls_create():
    transport = _fake_transport(); tk = _make_helpdesk_toolkit(transport)
    # FILL IN: side_effect order — category search_read → [{"id": 15, "name": "Black Screen"}], priority → [{"id": 3, ...}], create → 70,
    #   then _load_ticket reads (ticket read, extra rows, stages, users/company) using ROLES_ROW/STAGES_ROWS; call create_ticket(subject="x",
    #   partner_id=2243, category="Black Screen", priority="High"); assert the create tuple == (TICKET_MODEL, "create",
    #   [{"partner_id": 2243, "state": "customer_replied", "email_subject": "x", "category_id": 15, "priority": 3}], None) and isinstance(result, TicketResult)
    ...


@pytest.mark.asyncio
async def test_create_ticket_creates_partner_when_email_unknown():
    # FILL IN: partner search_read → [] then res.partner create → 99; assert ("res.partner", "create", [{"name": "a@b.c", "email": "a@b.c"}], None) was awaited
    ...


@pytest.mark.asyncio
async def test_update_ticket_rejects_lifecycle_fields():
    tk = _make_helpdesk_toolkit()
    import inspect
    assert not {"stage", "assignee", "user_id", "stage_id"} & set(inspect.signature(tk.update_ticket).parameters)   # AC8
    with pytest.raises(ValueError, match="nothing to update"):
        await tk.update_ticket(ticket_id=1)


@pytest.mark.asyncio
async def test_add_ticket_comment_reports_reopen():
    transport = _fake_transport(); tk = _make_helpdesk_toolkit(transport)
    transport.execute_kw.side_effect = [[{"id": 1, "stage_id": [21, "Closed"]}], [2268], [{"id": 1, "stage_id": [22, "Open"]}]]
    result = await tk.add_ticket_comment(ticket_id=1, body="hi", internal=False)
    assert result.reopened is True and result.message_id == 2268 and result.stage_after == "Open"
    call = transport.execute_kw.await_args_list[1]
    assert call.args[:3] == (TICKET_MODEL, "message_post", [[1]]) and call.args[3]["subtype_xmlid"] == "mail.mt_comment"


# FILL IN: test_take_assign_reassign_call_tuples — take: ("sh.helpdesk.ticket","action_take_ticket",[[1]],None); assign: write {"user_id": 2103,
#   "sh_user_ids": [[6,0,[2241]]]}; reassign: wizard create {"ticket_id": 1, "new_user_id": 2103} then ("sh.helpdesk.reassign.wizard","action_confirm",[[3]],None)
```
**Why**: exact call tuples are the contract; `test_add_ticket_comment_reports_reopen` pins the live-verified reopen behaviour (AC12). Import `TICKET_MODEL` from `parrot_tools.odoo.helpdesk` at the append point.

### FILL IN checklist
- [ ] `_find_or_create_partner` lookup chain; bounded by spec §3 M6
- [ ] `create_ticket` / `update_ticket` value mapping; bounded by AC8 and spec §3 M6
- [ ] `add_ticket_comment` result assembly; bounded by AC12
- [ ] three test `FILL IN`s + `test_take_assign_reassign_call_tuples`

---

## Acceptance Criteria

- [ ] AC8, AC12 (spec).
- [ ] Every mutating tool carries `@requires_permission("odoo.write")`.
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
2. **Read the spec** (§2 Overview, §3 M6, §6 live facts).
3. **Check dependencies** — TASK-3897 `done`.
4. **Verify the Codebase Contract** — re-run the `grep -c` anchors on `helpdesk.py` and the test module.
5. **Update status** in the per-spec index → `"in-progress"`, commit only that file.
6. **Implement** from the blueprint; remove every `raise NotImplementedError`.
7. **Verify** — Validation Commands.
8. **Commit the code** — only the two listed files.
9. **Close the task** — `scripts/sdd/close_task.sh TASK-3898 odoo-toolkit-upgrades verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

**Completed by**: sdd-worker (FEAT-616)
**Date**: 2026-10-01
**Notes**: gpt-5.6-terra (codex): helpdesk toolkit tools (helpdesk.py) + tests; test_odoo_*.py 205 passed. Diff reviewed vs contract; task tests run with `pytest --noconftest` (repo conftest broken by pre-existing venv issue); merge-tier sweep red on unrelated failures, accepted by user.

**Deviations from spec**: none | describe if any
