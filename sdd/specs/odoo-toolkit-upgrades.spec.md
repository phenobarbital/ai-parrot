---
type: feature
base_branch: dev
projects: [ai-parrot-tools, ai-parrot]
tags: [odoo, helpdesk, softhealer, json2, toolkit, structured-outputs, sla]
---

# Feature Specification: OdooHelpdeskToolkit — typed helpdesk tools for the Softhealer helpdesk (Odoo 19)

**Feature ID**: FEAT-616
**Date**: 2026-10-01
**Author**: Jesus Lara (with Claude Fable 5.1)
**Status**: draft
**Target version**: next `ai-parrot-tools` minor release (with a matching `ai-parrot` patch for the conf keys and the JSON-2 fix)

> Source proposal: `sdd/proposals/odoo-toolkit-upgrades.proposal.md` (accepted 2026-10-01)
> Research audit: `sdd/state/FEAT-616/` — 21 findings, sanitized live evidence under `findings/live/`
> (`13_action_verification.json`, `14_wizard_verification.json` are the staging write-verification runs
> authorised in proposal U3: three throwaway tickets, ids 69/70/71, all deleted).
> Ledger: opens `issue:e17074affa1b` (major, JSON-2 `create` broken on Odoo 19) — resolved by M1;
> `issue:f5ae793643be` (minor, `get_views` unmappable) stays open, out of scope.
> Depends on: **FEAT-614** (`odoo-json2-domain-first-methods`) — must merge first (§Worktree Strategy).

---

## 1. Motivation & Business Requirements

### Problem Statement

The staging helpdesk (`pokemon.helpdesk.staging`, Odoo `19.0-20260324`, JSON-2 transport) runs
**Softhealer Technologies' `sh_all_in_one_helpdesk` 19.0.0.0.1** under three TROC-owned layers
(`troc_helpdesk` 19.0.1.32.0, `dynamic_form_helpdesk`, `troc_helpdesk_dynamic_forms`). Tickets are
`sh.helpdesk.ticket` records (127 fields); their lifecycle is `stage_id` over five linear stages
(New → Open → Pending close → Pending reminder → Closed, chained by `helpdesk.stages.sh_next_stage`),
transitions are exposed as `action_*` server methods, SLAs are `sh.helpdesk.sla` policies with
per-ticket `sh.helpdesk.sla.status` rows, and the tenant's form payload lives in
`sh.helpdesk.ticket.extra_fields` (`field_name → value`).

The generic `OdooToolkit` exposes raw CRUD over any model but no helpdesk-shaped tools, so the
existing `odoo_hd` agent must push fragile domain knowledge (model names, stage ids, the
`state`-is-not-lifecycle trap, which `action_*` actually does something) into prompts. Two toolkit
defects surfaced during the staging verification and block the feature outright:

1. **`create` over JSON-2 is broken on this Odoo 19 build** for models whose `create` is overridden
   (every Softhealer helpdesk model): `vals_list` → 422 *missing a required argument: 'values'*;
   `values` → 500 *unexpected keyword argument 'values'*; `vals` → same for `helpdesk.tags`.
   `web_save(vals, specification)` creates the record and returns `[{"id": …}]` (F-live 13).
2. `formatted_read_group` over JSON-2 → 422 until FEAT-614 lands (F021).

### Goals

- **G1.** `OdooHelpdeskToolkit(OdooToolkit)` in `parrot_tools/odoo/helpdesk.py` — all helpdesk
  tools auto-registered as `odoo_<name>`, every Odoo call through the inherited `_execute`.
- **G2.** Typed **inputs** (`_OdooBaseInput` subclasses, one per tool, stage/team/category/priority/
  type/tags accepted by id **or** name) and typed **structured outputs** (`_OdooEntity` entities +
  result envelopes) for every tool.
- **G3.** Tool groups, all in v1 (proposal U2): tickets read / write / comments; assignment
  (take / assign / reassign / multi-assign); transitions (action-first with verified
  post-conditions); SLA policy CRUD + per-ticket SLA status + alarms; reference-data lookups;
  stats; merge and mass-update wizards; timesheet timer.
- **G4.** Dedicated configuration `ODOO_HELPDESK_*` (proposal U4) that **never** falls back to the
  generic `ODOO_*` keys and allows an empty database for JSON-2 (design research S2).
- **G5.** JSON-2 `create` works again on Odoo 19: `Json2Transport.execute_kw(model, "create", [vals])`
  falls back to `web_save` when the server rejects the `create` signature (ledger
  `issue:e17074affa1b`), for every caller, not only the helpdesk.
- **G6.** Tenant-agnostic behaviour: stage ids, categories and teams are resolved by name at
  runtime; nothing from the Pokémon tenant is hard-coded.
- **G7.** TROC payload exposed read-only (proposal U5): `HelpdeskTicket.extra_fields: dict[str, str]`
  and `dynamic_form_submission_id`, through a pure normalisation boundary (S8).
- **G8.** HITL: `cancel_ticket`, `merge_tickets`, `mass_update_tickets` require confirmation, as a
  union with the inherited shell confirmations (S10).
- **G9.** Unit coverage with the existing AsyncMock transport pattern, no network; plus an env-gated
  live smoke that re-runs the staging verification (throwaway ticket, throwaway SLA policy —
  both authorised, both deleted).

### Non-Goals (explicitly out of scope)

- Restricting the inherited tool surface or using a distinct prefix — **rejected by the owner**
  (spec Q&A 2026-10-01, design research S3/S4): prefix stays `odoo`, all inherited tools are
  exposed (FEAT-216 precedent). Consequence recorded in §7: an agent loads either `OdooToolkit`
  or `OdooHelpdeskToolkit`, never both.
- Mapping `get_views` over JSON-2 (`issue:f5ae793643be` stays open); view archs are read via
  `ir.ui.view.search_read` when needed.
- Any change to `Json2Transport._build_body`'s domain-first mapping (FEAT-614 owns it), to
  XML-RPC / JSON-RPC transports, to `parrot/interfaces/odoointerface.py` or `parrot/clients/base.py`.
- Odoo-side changes (Softhealer or `troc_helpdesk` modules), the dynamic-form / NavAPI submission
  pipeline (read-only linkage only), portal/website ticket creation paths.
- SLA *assignment logic* (which policies attach to a ticket is Softhealer's job); the toolkit
  creates/updates policies and reads statuses.
- Normalising `read_group` vs `formatted_read_group` inside `AggregateResult` (FEAT-614 non-goal);
  this spec normalises **only** at the helpdesk `TicketStatsResult` boundary (S11).

---

## 2. Architectural Design

### Overview

`OdooHelpdeskToolkit(OdooToolkit)` is a subclass (proposal U1, FEAT-216 precedent) living in its own
module. `AbstractToolkit.get_tools()` discovers every public `async def` by reflection, so the ~35
helpdesk methods register automatically as `odoo_<name>` next to the inherited tools; every Odoo
call goes through `OdooToolkit._execute`, so the transport (JSON-2 on Odoo 19, XML-RPC on 14–18)
stays invisible to the helpdesk layer.

Five design rules, all live-verified on staging (`sdd/state/FEAT-616/findings/live/13_*`, `14_*`):

1. **Action-first transitions with verified post-conditions (S7).** `close_ticket` calls
   `action_closed` (works from any stage, sets `close_date`/`close_by`, writes a stage-history line);
   `resolve_ticket`, `cancel_ticket`, `approve_ticket` call `action_done` / `action_cancel` /
   `action_approve` and, because those are **no-ops on this tenant** (guard flags off on every
   stage), return `TicketTransitionResult(applied=False, warnings=[…])` instead of pretending.
   `reopen_ticket` calls `action_open` and, when the stage did not change, performs its
   *documented* second step — `write({"stage_id": <"Open" by name>})`, reported as
   `method_used="stage_write"`. `move_ticket_to_stage` is the explicit stage write (also
   history-preserving: every `write` of `stage_id` produced a `sh.helpdesk.ticket.stage.info` line).
2. **Create via `web_save` on JSON-2 (G5).** Fixed once in `Json2Transport.execute_kw`: a `create`
   that the server rejects with a signature error (422/500 whose message contains
   `required argument` or `unexpected keyword argument`) is retried as
   `web_save({"vals": vals, "specification": {"id": {}}})` and normalised back to `create`'s
   return shape (int for one dict, `list[int]` for a list). Wizard models (`TransientModel`,
   no override) keep the fast path — verified: `sh.helpdesk.reassign.wizard.create` works as is.
3. **Name resolution is deterministic (S5).** `_resolve_ref(model, value)` accepts an int (used
   verbatim) or a str: exact `name =` match first, then unique `name ilike`; several candidates
   or none raise `ValueError` listing them. Results are cached per instance (`_ref_cache`), like
   `_fields_cache`.
4. **Explicit patch inputs (S9).** `UpdateTicketInput` lists the writable descriptive fields;
   lifecycle (`stage_id`), assignment (`user_id`, `sh_user_ids`) and SLA fields are not accepted
   there — they have dedicated tools. The raw escape hatch remains the inherited `update_record`.
5. **Normalisation boundary (S8).** `helpdesk_normalize.py` is pure (no I/O): it folds
   `extra_fields` rows into `dict[str, str]`, derives `lifecycle` from `stage_id` + the computed
   booleans, exposes `state` as `replied_status`, and leaves raw fields in place (`extra="allow"`).

Comments: `add_ticket_comment` uses `message_post` (kwargs-only, works over JSON-2). A **public
comment (`mail.mt_comment`) reopens a Closed ticket to Open; an internal note (`mail.mt_note`) does
not** — the result reports `reopened: bool`, and the input defaults to internal notes.

### Component Diagram

```
Agent (odoo_hd)
   │ tool calls: odoo_create_ticket / odoo_close_ticket / odoo_create_sla_policy / …
   ▼
OdooHelpdeskToolkit(OdooToolkit)                      parrot_tools/odoo/helpdesk.py   (M5–M9)
   ├── reference data + _resolve_ref cache            ──┐
   ├── ticket read / write / comments                   │ every call
   ├── assignment (action_take_ticket, reassign wizard) │
   ├── transitions (action_* → verify → TicketTransitionResult)
   ├── SLA (sh.helpdesk.sla / .sla.status / sh.ticket.alarm)
   └── stats / merge / mass-update / timer             ──┘
   │                        │
   │  normalize_ticket()    │  Pydantic: helpdesk_inputs / helpdesk_entities / helpdesk_envelopes (M3)
   ▼                        ▼
helpdesk_normalize.py (M4, pure)     OdooToolkit._execute(model, method, args, kwargs)   toolkit.py:283
                                          │
                                          ▼
                             Json2Transport.execute_kw                         json2.py:171
                               ├─ create → POST /json/2/<model>/create {vals_list}
                               │     └─ on signature error → POST …/web_save {vals, specification:{id:{}}}   (M1)
                               ├─ [[id]] action calls → {ids}
                               └─ kwargs-only (message_post, name_search) → body = kwargs
                                          │
                                          ▼
                                   Odoo 19 — sh.helpdesk.ticket, helpdesk.stages, sh.helpdesk.sla, …
Config: ODOO_HELPDESK_URL / USER / APIKEY|PASSWORD / DATABASE(optional)   parrot/conf.py (M2)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OdooToolkit` (`toolkit.py:172`) | extends (subclass) | inherits transport, lazy auth, `_execute`, `_read_one`, `_get_fields_metadata`, `_record_url`, all tools |
| `OdooToolkit._execute` (`toolkit.py:283`) | uses | single RPC path for every helpdesk call |
| `OdooToolkit.list_models` (`toolkit.py:373`) | overrides | iterates the module constant, so the subclass overrides the method (S1) |
| `OdooToolkit.confirming_tools` (`toolkit.py:194`) | extends (union) | `cancel_ticket`, `merge_tickets`, `mass_update_tickets` (S10) |
| `OdooToolkit.attach_document` (`toolkit.py:928`) | uses | `attach_to_ticket` delegates with `res_model="sh.helpdesk.ticket"` |
| `Json2Transport.execute_kw` (`json2.py:171`) | modifies | `create` → `web_save` fallback (M1) |
| `AbstractToolkit.get_tools` (`parrot/tools/toolkit.py:494`) | uses (reflection) | auto-registers the new public async methods with prefix `odoo` |
| `tool_schema` / `requires_permission` (`decorators.py:39` / `:9`) | uses | every tool; writes carry `odoo.write` |
| `select_smart_fields` (`smart_fields.py`) | uses | default field list when `fields` omitted in `search_tickets` |
| `parrot.conf` (`conf.py:811-817`) | extends | `ODOO_HELPDESK_*` keys next to the `ODOO_*` block |
| `models/__init__.py`, `odoo/__init__.py` | extends | re-exports |

### Data Models

New Pydantic models live in three sibling modules under `parrot_tools/odoo/models/` (not appended
to `inputs.py` / `entities.py` / `envelopes.py`, to stay clear of FEAT-614's edits to `inputs.py`)
and are re-exported from `models/__init__.py`.

```python
# models/helpdesk_entities.py — all subclass _OdooEntity (extra="allow", Many2one alias)
class HelpdeskLifecycle(BaseModel):
    stage_id: Optional[int]; stage_name: Optional[str]
    is_closed: bool; is_cancelled: bool; is_done: bool; can_reopen: bool   # from closed_stage_boolean/cancel_stage_boolean/done_stage_boolean/open_boolean
    next_stage_id: Optional[int]; next_stage_name: Optional[str]           # from helpdesk.stages.sh_next_stage (when stages were fetched)

class HelpdeskTicket(_OdooEntity):
    name, description, comment, customer_comment, email, email_cc, email_subject, mobile_no, person_name: Optional[str]
    partner_id, stage_id, team_id, team_head, user_id, category_id, sub_category_id, ticket_type, subject_id, priority, company_id: Optional[Many2one]
    sh_user_ids, tag_ids, sh_sla_policy_ids, sh_sla_status_ids, sh_ticket_alarm_ids, attachment_ids: Optional[list[int]]
    priority_new: Optional[str]                    # legacy 1–6 selection kept verbatim
    replied_status: Optional[str] = Field(alias="state")     # 'customer_replied' | 'staff_replied' — NOT lifecycle
    open_boolean, done_stage_boolean, closed_stage_boolean, cancel_stage_boolean, reopen_stage_boolean, done_button_boolean, cancel_button_boolean: Optional[bool]
    close_date, close_by, cancel_date, cancel_by, cancel_reason, replied_date, sh_due_date, sh_sla_deadline, sh_status, create_date, write_date: verbatim types
    ticket_from_portal, ticket_from_website, ticket_running: Optional[bool]
    dynamic_form_submission_id: Optional[Many2one]
    extra_fields: dict[str, str] = {}              # derived (M4) from sh.helpdesk.ticket.extra_fields
    lifecycle: Optional[HelpdeskLifecycle] = None  # derived (M4)

class HelpdeskStage(_OdooEntity):      name, sequence, is_done_button_visible, is_cancel_button_visible, sh_next_stage: Many2one, sh_group_ids, mail_template_ids
class HelpdeskTeam(_OdooEntity):       name, team_head: Many2one, team_members: list[int], category_ids: list[int], sh_resource_calendar_id, alias_name
class HelpdeskCategory(_OdooEntity):   name, sequence, team_id, company_id, is_helpdesk_manager
class HelpdeskSubcategory(_OdooEntity): name, parent_category_id
class HelpdeskPriority(_OdooEntity):   name, sequence, color
class HelpdeskTicketType(_OdooEntity): name, sla_count
class HelpdeskTag(_OdooEntity):        name, color
class HelpdeskStageInfo(_OdooEntity):  stage_task_id, stage_name, date_in, date_out, date_in_by, date_out_by, day_diff, time_diff, total_time_diff
class HelpdeskSla(_OdooEntity):        name, sh_team_id, sh_days, sh_hours, sh_minutes, sh_sla_target_type, sh_stage_id, sh_ticket_type_id, company_id, sla_ticket_count
class HelpdeskSlaStatus(_OdooEntity):  sh_ticket_id, sh_sla_id, sh_sla_stage_id, sh_deadline, sh_done_sla_date, sh_exceeded_hours, sh_status, sh_create_date
class HelpdeskTicketAlarm(_OdooEntity): name, type ('email'|'popup'), sh_remind_before, sh_reminder_unit
class HelpdeskMessage(BaseModel):      id, date, author_id: Many2one, message_type, subtype: Optional[str], body: str, is_internal: bool
```

```python
# models/helpdesk_inputs.py — all subclass _OdooBaseInput; `Ref = Union[int, str]` = id or name
class TicketIdInput(_OdooBaseInput):            ticket_id: int = Field(..., ge=1)
class GetTicketInput(TicketIdInput):            include_extra_fields: bool = True; include_history: bool = False
class SearchTicketsInput(_OdooBaseInput):       query: Optional[str] (name/subject/email ilike); stage: Optional[Ref]; team: Optional[Ref]; assignee: Optional[Ref] (res.users by id/login/name); category: Optional[Ref]; priority: Optional[Ref]; ticket_type: Optional[Ref]; partner_id: Optional[int]; created_after / created_before: Optional[str] (ISO); only_open: bool = False (excludes closed/cancel stages); domain: Optional[OdooDomain] (extra clauses AND-ed); fields: Optional[list[str]]; limit: int = 50 (≤ 500); offset: int = 0; order: str = "id desc"
class ListMyTicketsInput(_OdooBaseInput):       only_open: bool = True; limit: int = 50
class GetTicketHistoryInput(TicketIdInput)
class GetTicketMessagesInput(TicketIdInput):    limit: int = 20; include_notifications: bool = False
class GetTicketExtraFieldsInput(TicketIdInput)
class CreateTicketInput(_OdooBaseInput):        partner_id: Optional[int]; partner_email: Optional[str]; partner_name: Optional[str] (one of the three required — validator); subject: str; description: Optional[str]; category: Optional[Ref]; sub_category: Optional[Ref]; priority: Optional[Ref]; team: Optional[Ref]; ticket_type: Optional[Ref]; tags: Optional[list[Ref]]; assignee: Optional[Ref]; email: Optional[str]; mobile_no: Optional[str]; person_name: Optional[str]; due_date: Optional[str]; replied_status: Literal["customer_replied","staff_replied"] = "customer_replied"
class UpdateTicketInput(TicketIdInput):         subject, description, comment, customer_comment, email, email_cc, mobile_no, person_name, due_date: Optional[str]; category, sub_category, priority, team, ticket_type: Optional[Ref]; tags: Optional[list[Ref]]  # NO stage / user / sla fields (S9)
class AddTicketCommentInput(TicketIdInput):     body: str; internal: bool = True; attachment_ids: Optional[list[int]]
class AttachToTicketInput(TicketIdInput):       name: str; source: str; mimetype: Optional[str]; description: Optional[str]
class AssignTicketInput(TicketIdInput):         assignee: Ref; additional_assignees: Optional[list[Ref]] (→ sh_user_ids, replace)
class TakeTicketInput(TicketIdInput)
class ReassignTicketInput(TicketIdInput):       new_assignee: Ref
class MoveTicketToStageInput(TicketIdInput):    stage: Ref; expected_current_stage: Optional[Ref]
class CloseTicketInput(TicketIdInput):          comment: Optional[str] (posted as internal note before closing)
class ReopenTicketInput(TicketIdInput):         to_stage: Ref = "Open"
class ResolveTicketInput(TicketIdInput); class ApproveTicketInput(TicketIdInput)
class CancelTicketInput(TicketIdInput):         reason: str (written to cancel_reason before action_cancel)
class ListSlaPoliciesInput(_OdooBaseInput):     team: Optional[Ref]; ticket_type: Optional[Ref]; limit: int = 50
class CreateSlaPolicyInput(_OdooBaseInput):     name: str; team: Ref; days: int = 0; hours: int = 0; minutes: int = 0 (validator: total > 0); target_type: Literal["reaching_stage","assign_to"] = "reaching_stage"; stage: Optional[Ref] (required when reaching_stage); ticket_type: Optional[Ref]
class UpdateSlaPolicyInput(_OdooBaseInput):     sla_id: int; name, days, hours, minutes, target_type, stage, ticket_type: Optional (same types)
class GetTicketSlaStatusInput(TicketIdInput)
class ListTicketAlarmsInput(_OdooBaseInput):    limit: int = 50
class ListReferenceInput(_OdooBaseInput):       limit: int = 100  (shared by list_helpdesk_stages / teams / categories / priorities / ticket_types / tags)
class TicketStatsInput(_OdooBaseInput):         group_by: Literal["stage_id","team_id","user_id","category_id","priority","ticket_type"] = "stage_id"; only_open: bool = False; domain: Optional[OdooDomain]; created_after / created_before: Optional[str]
class MergeTicketsInput(_OdooBaseInput):        ticket_ids: list[int] (≥ 2); into_ticket_id: Optional[int] (None → new ticket); merged_action: Literal["close","cancel","done","remove","do_nothing"] = "close"; merge_history: bool = True
class MassUpdateTicketsInput(_OdooBaseInput):   ticket_ids: list[int] (≥ 1); stage: Optional[Ref]; assignee: Optional[Ref]; team: Optional[Ref]; add_followers / remove_followers: Optional[list[int]]  (validator: at least one change)
class StartTicketTimerInput(TicketIdInput); class StopTicketTimerInput(TicketIdInput): description: Optional[str]
```

```python
# models/helpdesk_envelopes.py
class HelpdeskReferenceItem(BaseModel):  id: int; name: str; extra: dict[str, Any] = {}
class HelpdeskReferenceResult(BaseModel): kind: str (model name); items: list[HelpdeskReferenceItem]; total: int
class TicketResult(BaseModel):            ticket: HelpdeskTicket; url: str; model: str = "sh.helpdesk.ticket"
class TicketListResult(BaseModel):        tickets: list[HelpdeskTicket]; total: int; limit: int; offset: int; fields: list[str]; metadata: Optional[FieldSelectionMetadata]
class TicketHistoryResult(BaseModel):     ticket_id: int; lines: list[HelpdeskStageInfo]; total: int
class TicketMessagesResult(BaseModel):    ticket_id: int; messages: list[HelpdeskMessage]; total: int
class TicketExtraFieldsResult(BaseModel): ticket_id: int; fields: dict[str, str]; labels: dict[str, str]; count: int
class TicketTransitionResult(BaseModel):  ticket_id: int; action: str; applied: bool; method_used: Literal["action","stage_write","none"]; from_stage: Optional[str]; to_stage: Optional[str]; warnings: list[str] = []; ticket: HelpdeskTicket
class TicketCommentResult(BaseModel):     ticket_id: int; message_id: int; internal: bool; reopened: bool; stage_after: Optional[str]
class TicketAssignmentResult(BaseModel):  ticket_id: int; assignee: Optional[Many2one]; additional_assignees: list[int]; method_used: str; ticket: HelpdeskTicket
class SlaPolicyResult(BaseModel):         policy: HelpdeskSla; url: str
class SlaPolicyListResult(BaseModel):     policies: list[HelpdeskSla]; total: int
class SlaStatusResult(BaseModel):         ticket_id: int; overall_status: Optional[str]; deadline: Optional[str]; statuses: list[HelpdeskSlaStatus]
class TicketAlarmListResult(BaseModel):   alarms: list[HelpdeskTicketAlarm]; total: int
class StatsGroup(BaseModel):              key: Optional[int | str]; label: str; count: int
class TicketStatsResult(BaseModel):       group_by: str; groups: list[StatsGroup]; total: int; source_method: str ("formatted_read_group" | "read_group" | "search_count")
class WizardResult(BaseModel):            wizard_model: str; wizard_id: int; ticket_ids: list[int]; applied: bool; result_ticket_id: Optional[int]; message: str
class TicketTimerResult(BaseModel):       ticket_id: int; running: bool; started_at: Optional[str]; duration_hours: Optional[float]; warnings: list[str] = []
```

### New Public Interfaces

```python
# parrot_tools/odoo/helpdesk.py
from parrot_tools.odoo import OdooHelpdeskToolkit          # re-exported from parrot_tools/odoo/__init__.py

toolkit = OdooHelpdeskToolkit()                              # defaults from ODOO_HELPDESK_* (never ODOO_*)
toolkit = OdooHelpdeskToolkit(url=..., username=..., password=<api key>, database="", protocol="json2")
tools = toolkit.get_tools()                                  # odoo_create_ticket, odoo_close_ticket, … + every inherited odoo_* tool

# parrot_tools/odoo/helpdesk_normalize.py (pure)
normalize_ticket(record: dict, extra_rows: list[dict] | None, stages: dict[int, dict] | None) -> HelpdeskTicket
extra_fields_to_dict(rows: list[dict]) -> tuple[dict[str, str], dict[str, str]]     # (values, labels)
lifecycle_from_record(record: dict, stages: dict[int, dict] | None) -> HelpdeskLifecycle
normalize_stats_groups(groups: list[dict], group_by: str, source_method: str) -> list[StatsGroup]
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: JSON-2 `create` → `web_save` fallback | yes | error predicate, body shape, return normalisation and test names fixed below | — |
| M2: `ODOO_HELPDESK_*` conf + isolated `__init__` | yes | key names, precedence (APIKEY over PASSWORD), `is None` resolution, no `ODOO_*` fallback | — |
| M3: helpdesk models (entities / inputs / envelopes) | yes | every class and field listed in §2 Data Models; exports listed in §6 | — |
| M4: `helpdesk_normalize.py` | yes | four pure functions with contracts below | — |
| M5: toolkit core (class, known models, resolvers, reference data, ticket read) | yes | method names, resolver rules, field constants fixed below | — |
| M6: ticket write + comments + assignment | yes | `web_save`-safe create through `_execute`, explicit patch, `message_post` kwargs, wizard shape verified live | — |
| M7: transitions | yes | action → verify → result contract fixed; fallback only in `reopen_ticket` | — |
| M8: SLA + alarms | yes | model fields verified live (`sh.helpdesk.sla`, `.sla.status`, `sh.ticket.alarm`) | — |
| M9: stats + wizards + timer | yes | both group shapes, wizard method names verified live (`action_confirm`, `update_record`, `action_merge_tickets`, `end_ticket`) | — |
| M10: docs + live smoke | yes | file paths and env gate fixed | — |

M1–M4 are independent of each other; M5 needs M2+M3+M4; M6–M9 each need M5 and edit the same two
files (`helpdesk.py`, `test_odoo_helpdesk_toolkit.py`) so their tasks serialise; M10 needs all.

### Module 1: JSON-2 `create` → `web_save` fallback
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py`
  (+ tests in `packages/ai-parrot/tests/test_odoo_json2_transport.py`)
- **Responsibility**: make `execute_kw(model, "create", [vals])` succeed on Odoo 19 builds whose
  `create` wrapper rejects the JSON-2 named argument (ledger `issue:e17074affa1b`).
- **Depends on**: nothing new. Must be implemented **after FEAT-614 merges** (same file, adjacent code).
- **Decisions**:
  - Fast path unchanged: `_build_body("create", [vals])` still sends `{"vals_list": vals}` (works for
    `TransientModel`s and any model without an override — verified on the reassign / mass-update wizards).
  - Fallback predicate `_is_create_signature_error(exc: OdooRPCError) -> bool`: message contains
    `"calling <model>.create"` **and** (`"missing a required argument"` or
    `"unexpected keyword argument"`). Network errors and 401/403 are never retried.
  - Fallback body: `{"vals": <one dict>, "specification": {"id": {}}}` per record; a list input is
    sent as one `web_save` per dict (Odoo's `web_save` takes one `vals`). Return: `int` when the
    caller passed a dict, `list[int]` when it passed a list — identical to `create`'s RPC shape.
  - One `self.logger.debug("JSON-2 create rejected for %s (%s); retrying via web_save", model, exc)`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py  (modifies json2.py:171-179)
  class Json2Transport(AbstractOdooTransport):                                  # verified: json2.py:38
      @staticmethod
      def _is_create_signature_error(exc: OdooRPCError) -> bool:
          """True when Odoo rejected a JSON-2 ``create`` because of its argument name (422/500)."""

      async def _create_via_web_save(self, model: str, vals: dict[str, Any] | list[dict[str, Any]]) -> int | list[int]:
          """Create through ``web_save`` (one call per dict) and return ``create``'s id shape."""

      async def execute_kw(self, model: str, method: str, args: list[Any] | None = None, kwargs: dict[str, Any] | None = None) -> Any:   # verified: json2.py:171
          """Translate ``execute_kw`` to JSON-2; ``create`` falls back to ``web_save`` on a signature error."""
  ```
- **Tests to add** (`test_odoo_json2_transport.py`, after `test_json2_unauthorized_maps_to_authentication_error`, `:162`):

  | Test | Asserts |
  |---|---|
  | `test_execute_kw_create_falls_back_to_web_save_on_missing_argument` | first POST `…/create` → 422 "missing a required argument: 'values'"; second POST `…/web_save` with `{"vals": {...}, "specification": {"id": {}}}`; returns `int` |
  | `test_execute_kw_create_falls_back_on_unexpected_keyword` | 500 "unexpected keyword argument 'vals'" → same fallback |
  | `test_execute_kw_create_list_uses_one_web_save_per_record` | list of 2 dicts → two `web_save` calls, returns `[id1, id2]` |
  | `test_execute_kw_create_does_not_retry_other_errors` | 422 "Invalid field 'x'" → raised as is, no `web_save` call |
  | `test_execute_kw_create_maps_values_to_vals_list` (existing, `:116`) | must keep passing (fast path unchanged) |

### Module 2: `ODOO_HELPDESK_*` configuration and isolated construction
- **Path**: `packages/ai-parrot/src/parrot/conf.py`, `packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py` (constructor only; the rest of the class is M5)
- **Responsibility**: dedicated credentials for the helpdesk instance that never leak into, or from, the generic `ODOO_*` keys (S2).
- **Depends on**: nothing.
- **Decisions**:
  - Keys (matching the names already in `env/.env`): `ODOO_HELPDESK_URL`, `ODOO_HELPDESK_USER`,
    `ODOO_HELPDESK_PASSWORD`, `ODOO_HELPDESK_APIKEY`, plus new optional `ODOO_HELPDESK_DATABASE`
    (default `""` — JSON-2 infers the database), `ODOO_HELPDESK_TIMEOUT` (int, default 30),
    `ODOO_HELPDESK_VERIFY_SSL` (bool, default True). Inserted after `conf.py:817`.
  - Password precedence: explicit `password` arg → `ODOO_HELPDESK_APIKEY` → `ODOO_HELPDESK_PASSWORD`.
  - Resolution uses `is None` checks (an explicit `""` database stays `""`). `ODOO_URL` /
    `ODOO_DATABASE` / `ODOO_USERNAME` / `ODOO_PASSWORD` are **never** read by this class.
  - Because `OdooToolkit.__init__` (`toolkit.py:230-235`) applies `value or ODOO_*`, the subclass
    calls `super().__init__(transport=transport, protocol=protocol, **kwargs)` with the resolved
    strings **and then rebuilds `self.config = OdooConfig(...)`** from its own values, so an empty
    database can never be replaced by `ODOO_DATABASE`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/conf.py  (insert after conf.py:817 `ODOO_VERIFY_SSL = …`)
  # ── Odoo Helpdesk (Softhealer sh_all_in_one_helpdesk, dedicated instance) ──
  ODOO_HELPDESK_URL = config.get("ODOO_HELPDESK_URL", fallback=None)
  ODOO_HELPDESK_USER = config.get("ODOO_HELPDESK_USER", fallback=None)
  ODOO_HELPDESK_PASSWORD = config.get("ODOO_HELPDESK_PASSWORD", fallback=None)
  ODOO_HELPDESK_APIKEY = config.get("ODOO_HELPDESK_APIKEY", fallback=None)
  ODOO_HELPDESK_DATABASE = config.get("ODOO_HELPDESK_DATABASE", fallback="")
  ODOO_HELPDESK_TIMEOUT = config.getint("ODOO_HELPDESK_TIMEOUT", fallback=30)
  ODOO_HELPDESK_VERIFY_SSL = config.getboolean("ODOO_HELPDESK_VERIFY_SSL", fallback=True)

  # packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py  (new)
  class OdooHelpdeskToolkit(OdooToolkit):                                      # OdooToolkit verified: toolkit.py:172
      """Helpdesk tools for Softhealer ``sh_all_in_one_helpdesk`` on top of :class:`OdooToolkit`."""
      def __init__(self, url: str | None = None, database: str | None = None, username: str | None = None,
                   password: str | None = None, timeout: int | None = None, verify_ssl: bool | None = None,
                   protocol: Protocol = "auto", transport: AbstractOdooTransport | None = None, **kwargs: Any) -> None:
          """Resolve every value from the argument, else ``ODOO_HELPDESK_*``; never from ``ODOO_*``.
          ``password`` falls back to ``ODOO_HELPDESK_APIKEY`` then ``ODOO_HELPDESK_PASSWORD``; ``database`` may be ``""``."""
  ```
- **Tests** (`test_odoo_helpdesk_toolkit.py`): `test_init_uses_helpdesk_keys_not_generic_odoo_keys` (monkeypatch both key sets; assert `config.url/database/username/password`), `test_init_keeps_empty_database_when_generic_database_is_set`, `test_init_prefers_apikey_over_password`, `test_init_explicit_args_win`.

### Module 3: helpdesk models
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_entities.py`,
  `…/models/helpdesk_inputs.py`, `…/models/helpdesk_envelopes.py`; modifies `…/models/__init__.py`
- **Responsibility**: the Pydantic layer listed in §2 Data Models, following the existing conventions
  (`_OdooEntity` extra=allow, `_OdooBaseInput` extra=ignore, `Field(..., description=…)` on every input field).
- **Depends on**: nothing new (imports `_OdooEntity`, `Many2one` from `entities.py`; `_OdooBaseInput`,
  `OdooDomain` from `inputs.py`; `FieldSelectionMetadata` from `envelopes.py`).
- **Decisions**: `Ref = Union[int, str]` is defined once in `helpdesk_inputs.py` with the description
  "Odoo id, or the record's name (resolved server-side; ambiguous names are rejected)". Validators:
  `CreateTicketInput` requires one of `partner_id` / `partner_email` / `partner_name`;
  `CreateSlaPolicyInput` requires `days+hours+minutes > 0` and `stage` when `target_type == "reaching_stage"`;
  `MassUpdateTicketsInput` requires at least one change. `HelpdeskTicket.replied_status` uses
  `Field(default=None, alias="state")` with `populate_by_name=True` (inherited).
- **Interface Skeleton**: the class list in §2 Data Models is the contract (names and field sets are
  not renegotiable); `models/__init__.py` re-exports every class and adds them to `__all__`.
- **Tests** (`packages/ai-parrot/tests/test_odoo_helpdesk_models.py`): round-trip of a live-shaped
  ticket dict (fixture from `findings/live/13_action_verification.json`, first `ticket` snapshot),
  validator rejections, `replied_status` alias, `models.__init__` exports.

### Module 4: normalisation boundary
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk_normalize.py`
  (+ tests `packages/ai-parrot/tests/test_odoo_helpdesk_normalize.py`)
- **Responsibility**: pure functions (no I/O, no async) that turn wire dicts into the derived fields (S8).
- **Depends on**: M3.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk_normalize.py  (new)
  def extra_fields_to_dict(rows: list[dict[str, Any]] | None) -> tuple[dict[str, str], dict[str, str]]:
      """Fold ``sh.helpdesk.ticket.extra_fields`` rows (``field_name``, ``name`` label, ``value``) into
      ``(values, labels)``. ``False``/``None`` values become ``""``; duplicate ``field_name`` keeps the last row;
      rows lacking ``field_name`` are skipped; a non-list input yields ``({}, {})``."""

  def lifecycle_from_record(record: dict[str, Any], stages: dict[int, dict[str, Any]] | None = None) -> HelpdeskLifecycle:
      """Derive the lifecycle block from ``stage_id`` (``[id, name]`` | ``False``) and the computed booleans
      (missing → ``False``); ``next_stage_*`` come from ``stages[stage_id]["sh_next_stage"]`` when given."""

  def normalize_ticket(record: dict[str, Any], extra_rows: list[dict[str, Any]] | None = None,
                       stages: dict[int, dict[str, Any]] | None = None) -> HelpdeskTicket:
      """Build a :class:`HelpdeskTicket` preserving every raw field, adding ``extra_fields`` and ``lifecycle``."""

  def normalize_stats_groups(groups: list[dict[str, Any]], group_by: str, source_method: str) -> list[StatsGroup]:
      """Map ``read_group`` (``<group_by>_count`` / ``__count``) and ``formatted_read_group`` (``__count``)
      rows to ``StatsGroup``; a ``False`` group key becomes ``key=None, label="(none)"``."""
  ```
- **Tests**: missing / `False` / list / malformed shapes for each function; both stats shapes.

### Module 5: toolkit core — class, known models, resolvers, reference data, ticket read
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py`; modifies `parrot_tools/odoo/__init__.py`
  (+ tests `packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py`)
- **Responsibility**: everything the other helpdesk modules build on.
- **Depends on**: M2, M3, M4.
- **Decisions**:
  - `tool_prefix` inherited (`"odoo"`); tools surface as `odoo_get_ticket`, … (owner decision).
  - `confirming_tools = OdooToolkit.confirming_tools | frozenset({"cancel_ticket", "merge_tickets", "mass_update_tickets"})` (S10).
  - `_HELPDESK_KNOWN_MODELS: tuple[tuple[str, str], ...]` = the 13 non-wizard models of F014;
    `list_models` is overridden to iterate `_HELPDESK_KNOWN_MODELS + _DEFAULT_KNOWN_MODELS` with the
    same `check_access_rights` loop (S1).
  - `_TICKET_DEFAULT_FIELDS` (class constant, ~45 names = the `HelpdeskTicket` wire fields);
    `_TICKET_LIST_FIELDS` (compact, ~15) used by `search_tickets` when `fields` is omitted.
  - `_REF_MODELS`: `{"stage": ("helpdesk.stages", "name"), "team": ("sh.helpdesk.team", "name"),
    "category": ("helpdesk.category", "name"), "sub_category": ("helpdesk.subcategory", "name"),
    "priority": ("helpdesk.priority", "name"), "ticket_type": ("sh.helpdesk.ticket.type", "name"),
    "tag": ("helpdesk.tags", "name"), "user": ("res.users", "name"), "sla": ("sh.helpdesk.sla", "name")}`.
    `user` also matches `login` exactly before `name`.
  - Resolver: int → returned as is; str → `search_read([(field, "=", value)])` exact; if none,
    `ilike`; exactly one match → id (cached in `_ref_cache[(model, value)]`); zero → `ValueError(f"No {kind} named {value!r}")`;
    several → `ValueError` listing `name (id)` candidates. Never `name_search` (S5).
  - `_stage_map()` returns `{id: {"name", "sequence", "sh_next_stage"}}` (cached, used by lifecycle and transitions).
  - `_load_ticket(ticket_id, include_extra=True, include_history=False) -> HelpdeskTicket` = `_read_one`
    with `_TICKET_DEFAULT_FIELDS` + `extra_fields` rows + `normalize_ticket`.
  - `only_open` domain: `("stage_id.name", "not in", [closed-like stage names])` where closed-like =
    stages whose id is `stage_id` of tickets having `closed_stage_boolean`/`cancel_stage_boolean`… — **decided simpler**:
    `only_open` excludes stages named `Closed` **or** flagged `sh_next_stage == False` (last stage); documented in the tool docstring.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py  (new)
  _HELPDESK_KNOWN_MODELS: tuple[tuple[str, str], ...]
  class OdooHelpdeskToolkit(OdooToolkit):                                      # verified: toolkit.py:172
      confirming_tools: frozenset = OdooToolkit.confirming_tools | frozenset({...})   # base verified: toolkit.py:194
      _TICKET_DEFAULT_FIELDS: list[str]; _TICKET_LIST_FIELDS: list[str]; _REF_MODELS: dict[str, tuple[str, str]]
      async def _resolve_ref(self, kind: str, value: int | str) -> int:  """Id or unique name → id; raises ValueError."""
      async def _resolve_refs(self, kind: str, values: list[int | str]) -> list[int]
      async def _stage_map(self) -> dict[int, dict[str, Any]]
      async def _load_ticket(self, ticket_id: int, include_extra: bool = True) -> HelpdeskTicket
      async def _extra_rows(self, ticket_id: int) -> list[dict[str, Any]]
      def _ticket_url(self, ticket_id: int) -> str                              # uses _record_url verified: toolkit.py:295

      async def list_models(self) -> ModelsResult:                                # overrides toolkit.py:373
          """List helpdesk + core models with the connected user's ACLs."""
      @tool_schema(ListReferenceInput) async def list_helpdesk_stages(self, limit: int = 100) -> HelpdeskReferenceResult: """Stages ordered by sequence, with next-stage and button flags in ``extra``."""
      @tool_schema(ListReferenceInput) async def list_helpdesk_teams(self, limit: int = 100) -> HelpdeskReferenceResult
      @tool_schema(ListReferenceInput) async def list_helpdesk_categories(self, limit: int = 100) -> HelpdeskReferenceResult   # includes subcategories under extra["subcategories"]
      @tool_schema(ListReferenceInput) async def list_helpdesk_priorities(self, limit: int = 100) -> HelpdeskReferenceResult
      @tool_schema(ListReferenceInput) async def list_ticket_types(self, limit: int = 100) -> HelpdeskReferenceResult
      @tool_schema(ListReferenceInput) async def list_helpdesk_tags(self, limit: int = 100) -> HelpdeskReferenceResult
      @tool_schema(GetTicketInput) async def get_ticket(self, ticket_id: int, include_extra_fields: bool = True, include_history: bool = False) -> TicketResult
      @tool_schema(SearchTicketsInput) async def search_tickets(self, query=None, stage=None, team=None, assignee=None, category=None, priority=None, ticket_type=None, partner_id=None, created_after=None, created_before=None, only_open=False, domain=None, fields=None, limit=50, offset=0, order="id desc") -> TicketListResult
      @tool_schema(ListMyTicketsInput) async def list_my_tickets(self, only_open: bool = True, limit: int = 50) -> TicketListResult   # user_id == transport.uid OR uid in sh_user_ids
      @tool_schema(GetTicketHistoryInput) async def get_ticket_history(self, ticket_id: int) -> TicketHistoryResult
      @tool_schema(GetTicketMessagesInput) async def get_ticket_messages(self, ticket_id: int, limit: int = 20, include_notifications: bool = False) -> TicketMessagesResult
      @tool_schema(GetTicketExtraFieldsInput) async def get_ticket_extra_fields(self, ticket_id: int) -> TicketExtraFieldsResult

  # packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py  (modifies __init__.py:22-28 import block and :30-38 __all__)
  from .helpdesk import OdooHelpdeskToolkit
  ```
- **Tests**: `execute_kw` call tuples for every read tool; resolver exact/ilike/ambiguous/miss;
  `list_models` includes `sh.helpdesk.ticket`; `confirming_tools` superset of the base set and the
  three names; `get_tools()` names include `odoo_get_ticket` and the inherited `odoo_search_records`.

### Module 6: ticket write, comments, attachments, assignment
- **Path**: `helpdesk.py` (+ `test_odoo_helpdesk_toolkit.py`)
- **Depends on**: M5 (and M1 for JSON-2 creates to work live).
- **Decisions**:
  - `create_ticket`: partner resolution — `partner_id` verbatim; else `res.partner` by `email =`;
    else by exact name; else create the partner (`res.partner.create` — goes through the same
    `create` fallback) with `name`/`email`. Values written: `partner_id`, `state` (=`replied_status`),
    `email_subject`, `description` (html-escaped paragraph unless it already contains `<`),
    resolved `category_id`, `sub_category_id`, `priority`, `team_id`, `ticket_type`, `tag_ids`
    (`[[6, 0, ids]]`), `user_id`, `email`, `mobile_no`, `person_name`, `sh_due_date`.
    Call: `self._execute("sh.helpdesk.ticket", "create", [values])` — never `web_save` directly
    (the transport owns the fallback). Returns `TicketResult` from `_load_ticket`.
  - `update_ticket`: explicit patch (S9) → `write([[id], values])`; refs resolved; `tags` replaces.
  - `add_ticket_comment`: `message_post([[id]], {"body", "message_type": "comment",
    "subtype_xmlid": "mail.mt_note" if internal else "mail.mt_comment", "attachment_ids"})`; the
    result compares `stage_id` before/after → `reopened`.
  - `attach_to_ticket` → inherited `attach_document(res_model="sh.helpdesk.ticket", …)`.
  - `assign_ticket`: `write({"user_id": id, "sh_user_ids": [[6,0,ids]]})` (verified: `sh_user_ids` write works);
    `take_ticket`: `action_take_ticket([[id]])` (verified: sets `user_id` = uid); `reassign_ticket`:
    `sh.helpdesk.reassign.wizard.create([{"ticket_id", "new_user_id"}])` then `action_confirm([[wizard_id]])`
    (verified: returns `act_window_close`, `user_id` changes). All return `TicketAssignmentResult`.
- **Interface Skeleton**:
  ```python
  @requires_permission("odoo.write") @tool_schema(CreateTicketInput) async def create_ticket(self, subject: str, partner_id=None, partner_email=None, partner_name=None, description=None, category=None, sub_category=None, priority=None, team=None, ticket_type=None, tags=None, assignee=None, email=None, mobile_no=None, person_name=None, due_date=None, replied_status="customer_replied") -> TicketResult
  @requires_permission("odoo.write") @tool_schema(UpdateTicketInput) async def update_ticket(self, ticket_id: int, **patch) -> TicketResult      # explicit keyword params in code, not **patch
  @requires_permission("odoo.write") @tool_schema(AddTicketCommentInput) async def add_ticket_comment(self, ticket_id: int, body: str, internal: bool = True, attachment_ids=None) -> TicketCommentResult
  @requires_permission("odoo.write") @tool_schema(AttachToTicketInput) async def attach_to_ticket(self, ticket_id: int, name: str, source: str, mimetype=None, description=None) -> BinaryFieldResult
  @requires_permission("odoo.write") @tool_schema(AssignTicketInput) async def assign_ticket(self, ticket_id: int, assignee: int | str, additional_assignees=None) -> TicketAssignmentResult
  @requires_permission("odoo.write") @tool_schema(TakeTicketInput) async def take_ticket(self, ticket_id: int) -> TicketAssignmentResult
  @requires_permission("odoo.write") @tool_schema(ReassignTicketInput) async def reassign_ticket(self, ticket_id: int, new_assignee: int | str) -> TicketAssignmentResult
  ```
- **Tests**: exact `execute_kw` tuples (create values, write patch, `message_post` kwargs, wizard
  create + `action_confirm`), `reopened=True` when the mocked read-back moves Closed → Open,
  `UpdateTicketInput` rejects `stage_id`/`user_id`.

### Module 7: transitions
- **Path**: `helpdesk.py` (+ tests)
- **Depends on**: M5.
- **Decisions** (S7, live-verified):
  - Common driver `_transition(ticket_id, action, expected_stage=None) -> TicketTransitionResult`:
    read stage before; optional `expected_stage` mismatch → `ValueError` before any call; call
    `self._execute("sh.helpdesk.ticket", action, [[ticket_id]])`; re-read; `applied = stage changed
    or (action == "action_closed" and close_date set)`; `method_used="action"` when applied else
    `"none"` with warning `f"{action} produced no change on this instance (stage guard flags may be off)"`.
    A dict return with `type == "ir.actions.act_window"` is recorded as warning "action opened a wizard; not applied".
  - `close_ticket(ticket_id, comment=None)`: optional internal note, then `action_closed`.
  - `resolve_ticket` → `action_done`; `approve_ticket` → `action_approve`; **no fallback**.
  - `cancel_ticket(ticket_id, reason)`: `write({"cancel_reason": reason})` then `action_cancel`;
    no fallback; HITL-confirmed.
  - `reopen_ticket(ticket_id, to_stage="Open")`: `action_open`; if not applied →
    `write({"stage_id": resolve(to_stage)})`, `method_used="stage_write"`, warning
    "action_open was a no-op; stage written directly".
  - `move_ticket_to_stage(ticket_id, stage, expected_current_stage=None)`: explicit `write`,
    `method_used="stage_write"`, `applied` = post-condition.
- **Interface Skeleton**:
  ```python
  async def _transition(self, ticket_id: int, action: str, *, expected_stage: int | None = None, fallback_stage: int | None = None) -> TicketTransitionResult
  @requires_permission("odoo.write") @tool_schema(CloseTicketInput) async def close_ticket(self, ticket_id: int, comment: str | None = None) -> TicketTransitionResult
  @requires_permission("odoo.write") @tool_schema(ReopenTicketInput) async def reopen_ticket(self, ticket_id: int, to_stage: int | str = "Open") -> TicketTransitionResult
  @requires_permission("odoo.write") @tool_schema(ResolveTicketInput) async def resolve_ticket(self, ticket_id: int) -> TicketTransitionResult
  @requires_permission("odoo.write") @tool_schema(ApproveTicketInput) async def approve_ticket(self, ticket_id: int) -> TicketTransitionResult
  @requires_permission("odoo.write") @tool_schema(CancelTicketInput) async def cancel_ticket(self, ticket_id: int, reason: str) -> TicketTransitionResult
  @requires_permission("odoo.write") @tool_schema(MoveTicketToStageInput) async def move_ticket_to_stage(self, ticket_id: int, stage: int | str, expected_current_stage: int | str | None = None) -> TicketTransitionResult
  ```
- **Tests**: applied/not-applied paths, `expected_stage` mismatch raises before RPC, `reopen_ticket`
  fallback issues exactly one `write`, `resolve_ticket` never writes `stage_id`, wizard-return warning.

### Module 8: SLA policies, status, alarms
- **Path**: `helpdesk.py` (+ tests)
- **Depends on**: M5.
- **Decisions**: `create_sla_policy` → `sh.helpdesk.sla.create([{"name", "sh_team_id", "sh_days",
  "sh_hours", "sh_minutes", "sh_sla_target_type", "sh_stage_id", "sh_ticket_type_id"}])`;
  `update_sla_policy` → `write`; `list_sla_policies` → `search_read` (filters by team/type);
  `get_ticket_sla_status` → `sh.helpdesk.sla.status.search_read([("sh_ticket_id", "=", id)])` +
  ticket `sh_status`/`sh_sla_deadline` → `SlaStatusResult`; `list_ticket_alarms` → `sh.ticket.alarm`.
  No `delete_sla_policy` in v1 (inherited `delete_record` covers it).
- **Interface Skeleton**:
  ```python
  @tool_schema(ListSlaPoliciesInput) async def list_sla_policies(self, team=None, ticket_type=None, limit: int = 50) -> SlaPolicyListResult
  @requires_permission("odoo.write") @tool_schema(CreateSlaPolicyInput) async def create_sla_policy(self, name: str, team: int | str, days: int = 0, hours: int = 0, minutes: int = 0, target_type: str = "reaching_stage", stage=None, ticket_type=None) -> SlaPolicyResult
  @requires_permission("odoo.write") @tool_schema(UpdateSlaPolicyInput) async def update_sla_policy(self, sla_id: int, **patch) -> SlaPolicyResult   # explicit keyword params in code
  @tool_schema(GetTicketSlaStatusInput) async def get_ticket_sla_status(self, ticket_id: int) -> SlaStatusResult
  @tool_schema(ListTicketAlarmsInput) async def list_ticket_alarms(self, limit: int = 50) -> TicketAlarmListResult
  ```
- **Tests**: create values (refs resolved), validator paths, status envelope from two mocked rows.
  **Live** (task-level, authorised 2026-10-01): create one policy on team "Compliance"
  (`reaching_stage` → "Closed", 1 hour), create a throwaway ticket, read its `sh_sla_status_ids`,
  delete both; record the observed status shape in the Completion Note.

### Module 9: stats, merge / mass-update wizards, timer
- **Path**: `helpdesk.py` (+ tests)
- **Depends on**: M5; **FEAT-614** for `formatted_read_group` over JSON-2.
- **Decisions**:
  - `ticket_stats`: Odoo ≥ 19 → `formatted_read_group([domain], {"groupby": [group_by], "aggregates": ["__count"]})`;
    ≤ 18 → `read_group([domain], {"groupby": [group_by], "fields": ["id:count"], "lazy": False})`;
    on `OdooRPCError` from either → per-stage `search_count` fallback **only when `group_by == "stage_id"`**,
    `source_method="search_count"`; rows normalised by `normalize_stats_groups` (S11).
  - `merge_tickets`: `sh.helpdesk.ticket.merge.ticket.wizard.create([{"sh_helpdesk_ticket_ids": [[6,0,ids]],
    "sh_select_type": "existing"|"new", "sh_existing_ticket", "sh_select_merge_type", "sh_merge_history"}])`
    then `action_merge_tickets([[wizard_id]])`; HITL-confirmed.
  - `mass_update_tickets`: wizard `create` with `helpdesks_ticket_ids [[6,0,ids]]` + `check_helpdesks_state`/`helpdesk_stages`,
    `check_assign_to`/`assign_to`, `check_team_id`/`team_id`, `check_add_remove`/`followers`/`ticket_follower_update_type`;
    then `update_record([[wizard_id]])` (verified live); HITL-confirmed.
  - `start_ticket_timer` → `action_ticket_start([[id]])`; the tenant error *"Please Set Default Project
    from configuration!"* is caught and returned as `TicketTimerResult(running=False, warnings=[…])`.
    `stop_ticket_timer` → `action_ticket_end([[id]])` returns an `act_window` on
    `ticket.time.account.line`; the tool creates that record (`name`, `start_date`, `end_date`,
    `project_id` from the action context when present) and calls `end_ticket([[line_id]])`
    (button verified); result carries `duration_hours`.
- **Interface Skeleton**:
  ```python
  @tool_schema(TicketStatsInput) async def ticket_stats(self, group_by: str = "stage_id", only_open: bool = False, domain=None, created_after=None, created_before=None) -> TicketStatsResult
  @requires_permission("odoo.write") @tool_schema(MergeTicketsInput) async def merge_tickets(self, ticket_ids: list[int], into_ticket_id: int | None = None, merged_action: str = "close", merge_history: bool = True) -> WizardResult
  @requires_permission("odoo.write") @tool_schema(MassUpdateTicketsInput) async def mass_update_tickets(self, ticket_ids: list[int], stage=None, assignee=None, team=None, add_followers=None, remove_followers=None) -> WizardResult
  @requires_permission("odoo.write") @tool_schema(StartTicketTimerInput) async def start_ticket_timer(self, ticket_id: int) -> TicketTimerResult
  @requires_permission("odoo.write") @tool_schema(StopTicketTimerInput) async def stop_ticket_timer(self, ticket_id: int, description: str | None = None) -> TicketTimerResult
  ```
- **Tests**: both group shapes + fallback; wizard create values and follow-up call tuples; timer
  error surfaced as warning, not raised.

### Module 10: documentation and live smoke
- **Path**: `docs/tools/odoo-helpdesk.md` (new), `examples/odoo/helpdesk_live_smoke.py` (new)
- **Depends on**: M1–M9.
- **Decisions**: the smoke is gated by `ODOO_HELPDESK_LIVE=1`, reads `ODOO_HELPDESK_*`, and replays
  the verification sequence of `findings/live/13_*`/`14_*` (create → take → close → note → public
  comment → reassign wizard → mass update → SLA policy → delete everything it created). It never
  runs under pytest. The doc lists every tool, the tenant facts (`state` ≠ lifecycle, no-op actions,
  public comment reopens), and the "one Odoo toolkit per agent" rule.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_execute_kw_create_falls_back_to_web_save_on_missing_argument` | M1 | 422 signature error → `web_save`, int returned |
| `test_execute_kw_create_falls_back_on_unexpected_keyword` | M1 | 500 variant |
| `test_execute_kw_create_list_uses_one_web_save_per_record` | M1 | list → `[id, id]` |
| `test_execute_kw_create_does_not_retry_other_errors` | M1 | unrelated 422 re-raised, no second POST |
| `test_init_uses_helpdesk_keys_not_generic_odoo_keys` | M2 | conf isolation |
| `test_init_keeps_empty_database_when_generic_database_is_set` | M2 | `database=""` survives `ODOO_DATABASE` |
| `test_init_prefers_apikey_over_password` | M2 | precedence |
| `test_helpdesk_ticket_roundtrip_live_shape` | M3 | live-shaped dict validates; `replied_status` alias |
| `test_create_ticket_input_requires_partner_ref` / `test_create_sla_policy_input_validators` / `test_mass_update_input_requires_change` | M3 | validators |
| `test_models_init_exports_helpdesk_classes` | M3 | `parrot_tools.odoo.models.__all__` |
| `test_extra_fields_to_dict_shapes` | M4 | missing / False / dup / malformed |
| `test_lifecycle_from_record_flags_and_next_stage` | M4 | booleans + `sh_next_stage` |
| `test_normalize_stats_groups_both_shapes` | M4 | `read_group` vs `formatted_read_group` |
| `test_resolve_ref_exact_ilike_ambiguous_missing` | M5 | resolver contract + cache |
| `test_list_models_includes_helpdesk_models` | M5 | S1 |
| `test_confirming_tools_is_union_with_base` | M5 | S10 |
| `test_get_tools_registers_helpdesk_and_inherited_tools` | M5 | prefix `odoo`, names present |
| `test_search_tickets_builds_domain_and_uses_list_fields` | M5 | domain assembly incl. `only_open` |
| `test_get_ticket_loads_extra_fields_and_lifecycle` | M5 | two RPCs, normalised result |
| `test_create_ticket_resolves_refs_and_calls_create` | M6 | values dict exact |
| `test_create_ticket_creates_partner_when_email_unknown` | M6 | partner path |
| `test_update_ticket_rejects_lifecycle_fields` | M6 | S9 |
| `test_add_ticket_comment_reports_reopen` | M6 | Closed → Open after public comment |
| `test_take_assign_reassign_call_tuples` | M6 | action / write / wizard |
| `test_close_ticket_applied_via_action` | M7 | `method_used="action"` |
| `test_resolve_ticket_noop_reports_not_applied` | M7 | S7 |
| `test_reopen_ticket_falls_back_to_stage_write` | M7 | one `write`, `method_used="stage_write"` |
| `test_move_ticket_to_stage_expected_stage_mismatch_raises_before_rpc` | M7 | guard |
| `test_cancel_ticket_writes_reason_then_action` | M7 | order of calls |
| `test_create_sla_policy_values` / `test_get_ticket_sla_status_envelope` | M8 | |
| `test_ticket_stats_odoo19_formatted_read_group` / `_odoo17_read_group` / `_fallback_search_count` | M9 | S11 |
| `test_merge_tickets_wizard_calls` / `test_mass_update_tickets_wizard_calls` | M9 | |
| `test_start_ticket_timer_surfaces_config_error_as_warning` | M9 | |

### Integration Tests
| Test | Description |
|---|---|
| `examples/odoo/helpdesk_live_smoke.py` (manual, `ODOO_HELPDESK_LIVE=1`, never under pytest) | Replays the staging verification end-to-end incl. one throwaway SLA policy; every created record is deleted; outcome recorded in the M8/M9/M10 Completion Notes |

### Test Data / Fixtures
```python
# reuse verbatim from packages/ai-parrot/tests/test_odoo_toolkit.py
_fake_transport(uid=1)         # verified: test_odoo_toolkit.py:57  (execute_kw / version / authenticate are AsyncMock)
_make_toolkit(transport)       # verified: test_odoo_toolkit.py:83 — helpdesk tests define _make_helpdesk_toolkit(transport) the same way
transport.execute_kw.side_effect = [...]   # ordered responses per RPC (pattern used at test_odoo_toolkit.py:700+)
# live-shaped ticket fixture: first "ticket" snapshot in sdd/state/FEAT-616/findings/live/13_action_verification.json
# JSON-2 tests reuse _config() and _mock_aiohttp_response() — verified: test_odoo_json2_transport.py:35 / :47
```

No E2E surface (FEAT-581): the `e2e` frontmatter key and the E2E Scenarios subsection are intentionally omitted.

---

## 5. Acceptance Criteria

- [ ] AC1. `Json2Transport.execute_kw(model, "create", [dict])` returns an `int` after a 422/500 signature rejection by retrying `web_save` with `{"vals": dict, "specification": {"id": {}}}`; a list input returns `list[int]`; any other error is re-raised unchanged; the existing fast-path test at `test_odoo_json2_transport.py:116` still passes.
- [ ] AC2. `parrot.conf` exposes `ODOO_HELPDESK_URL/USER/PASSWORD/APIKEY/DATABASE/TIMEOUT/VERIFY_SSL`; `OdooHelpdeskToolkit()` with no args builds `OdooConfig` from them only.
- [ ] AC3. With `ODOO_DATABASE="prod"` in the environment and `ODOO_HELPDESK_DATABASE=""`, `OdooHelpdeskToolkit().config.database == ""`.
- [ ] AC4. Every class in §2 Data Models exists in the three `helpdesk_*` modules and is importable from `parrot_tools.odoo.models`; `OdooHelpdeskToolkit` is importable from `parrot_tools.odoo`.
- [ ] AC5. `OdooHelpdeskToolkit().get_tools()` yields tool names prefixed `odoo_` for all helpdesk methods **and** every inherited `OdooToolkit` tool; `tool_prefix == "odoo"`.
- [ ] AC6. `list_models()` returns the 13 helpdesk models of `_HELPDESK_KNOWN_MODELS` plus the base ten.
- [ ] AC7. `confirming_tools ⊇ OdooToolkit.confirming_tools ∪ {"cancel_ticket", "merge_tickets", "mass_update_tickets"}` and the generated tools carry `routing_meta["requires_confirmation"]` for those three.
- [ ] AC8. `UpdateTicketInput` has no `stage`, `stage_id`, `user_id`, `assignee`, `sh_user_ids` or `sh_sla_*` field; `update_ticket` never writes them.
- [ ] AC9. Every transition tool returns `TicketTransitionResult` with `applied` computed from a post-condition read, never assumed.
- [ ] AC10. `resolve_ticket`, `approve_ticket`, `cancel_ticket` issue no `write` of `stage_id` under any outcome.
- [ ] AC11. `reopen_ticket` writes `stage_id` **only** after `action_open` produced no change, and reports `method_used="stage_write"` with a warning.
- [ ] AC12. `add_ticket_comment` defaults to `mail.mt_note` and reports `reopened=True` when the stage changed after a `mail.mt_comment` post.
- [ ] AC13. Reference names are resolved through `search_read` (exact, then `ilike`); ambiguous or unknown names raise `ValueError` naming the candidates before any write.
- [ ] AC14. `HelpdeskTicket.extra_fields` is a `dict[str, str]` built from `sh.helpdesk.ticket.extra_fields` rows; `lifecycle` is derived; raw fields are preserved.
- [ ] AC15. `ticket_stats` normalises both `read_group` and `formatted_read_group` shapes into `StatsGroup` rows and falls back to per-stage `search_count` only for `group_by="stage_id"`.
- [ ] AC16. `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src pytest packages/ai-parrot/tests/test_odoo_json2_transport.py packages/ai-parrot/tests/test_odoo_helpdesk_models.py packages/ai-parrot/tests/test_odoo_helpdesk_normalize.py packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py packages/ai-parrot/tests/test_odoo_toolkit.py -q` passes with no network.
- [ ] AC17. `ruff check` is clean on every file in §6 Edit Sites; no `requests`/`httpx`/LangChain imports.
- [ ] AC18. No public signature of `OdooToolkit`, `Json2Transport._build_body`, or any existing model changes.
- [ ] AC19. Ledger `issue:e17074affa1b` is claimed at `/sdd-start` of M1 and closed by `/sdd-done FEAT-616` with `--resolved-by spec:FEAT-616`.
- [ ] AC20. `docs/tools/odoo-helpdesk.md` exists and documents every tool, the tenant caveats (§7) and the one-toolkit-per-agent rule; the live smoke ran once against staging with all created records deleted (recorded in the Completion Notes).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against commit `b3141f286` (dev, 2026-10-01). `/sdd-task` re-runs every `grep -c`.
> Live-instance facts (model and field names) verified against `pokemon.helpdesk.staging`
> (Odoo 19.0-20260324) on 2026-09-30/10-01 — evidence in `sdd/state/FEAT-616/findings/live/`.

### Verified Imports
```python
from parrot_tools.odoo.toolkit import OdooToolkit, _DEFAULT_KNOWN_MODELS, _model_to_dict   # verified: toolkit.py:172 / :149 / :163
from parrot_tools.odoo import OdooToolkit, OdooError, OdooRPCError                             # verified: odoo/__init__.py:22-28
from parrot.interfaces.odoointerface import OdooConfig, OdooRPCError, OdooAuthenticationError, OdooConnectionError, OdooError   # verified: odoointerface.py:55 (OdooConfig); toolkit.py:39-45 & json2.py:20-26 import them
from parrot_tools.odoo.transport.base import AbstractOdooTransport                            # verified: transport/base.py:11
from parrot_tools.odoo.transport.detect import Protocol                                       # verified: detect.py:29  (Literal["auto","json2","jsonrpc","xmlrpc"])
from parrot_tools.odoo.transport.json2 import Json2Transport, _looks_like_ids                 # verified: json2.py:38 / :31
from parrot_tools.odoo.models.entities import _OdooEntity, Many2one                           # verified: entities.py:22 / :19
from parrot_tools.odoo.models.inputs import _OdooBaseInput, OdooDomain                        # verified: inputs.py:19 / :16
from parrot_tools.odoo.models.envelopes import FieldSelectionMetadata, ModelsResult, ModelInfo, ModelOperations, BinaryFieldResult   # verified: envelopes.py:14 / :44 / :36 / :27 / :146
from parrot_tools.odoo.smart_fields import select_smart_fields                                # verified: toolkit.py:138
from parrot.tools.decorators import tool_schema, requires_permission                          # verified: decorators.py:39 / :9 (toolkit.py:46-47)
from parrot.tools.toolkit import AbstractToolkit                                              # verified: toolkit.py:48
from parrot.conf import ODOO_URL, ODOO_DATABASE, ODOO_USERNAME, ODOO_PASSWORD, ODOO_TIMEOUT, ODOO_VERIFY_SSL   # verified: conf.py:812-817
from pydantic import BaseModel, ConfigDict, Field, model_validator                            # pydantic v2 (inputs.py:11)
```

### Existing Class Signatures
```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py
_DEFAULT_KNOWN_MODELS: tuple[tuple[str, str], ...]                     # line 149-160 (10 core models, no helpdesk)
class OdooToolkit(AbstractToolkit):                                     # line 172
    tool_prefix = "odoo"                                                # line 191
    confirming_tools: frozenset = frozenset({"odoo_shell_install_module", "odoo_shell_upgrade_module", "odoo_cli_command"})   # line 194-200
    def __init__(self, url=None, database=None, username=None, password=None, timeout=None, verify_ssl=None,
                 protocol: Protocol = "auto", transport: AbstractOdooTransport | None = None, **kwargs) -> None   # line 202-213
        # line 230-235: self.config = OdooConfig(url=url or ODOO_URL or "", database=database or ODOO_DATABASE or "", ...)  ← `or` fallback (S2)
        # line 237-241: self.protocol, self._transport, self._auth_lock, self._fields_cache, self.logger
    async def _ensure_transport(self) -> AbstractOdooTransport          # line 245
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None   # line 268 (auth only when url+database+username truthy)
    async def _execute(self, model: str, method: str, args: list[Any] | None = None, kwargs: dict[str, Any] | None = None) -> Any   # line 283-292
    @staticmethod
    def _record_url(base_url: str, model: str, record_id: int) -> str   # line 294-297
    async def _read_one(self, model: str, record_id: int, fields: list[str] | None = None) -> dict[str, Any]   # line 299-309
    async def _get_fields_metadata(self, model: str) -> dict[str, Any]  # line 312-322 (cached in self._fields_cache)
    async def list_models(self) -> ModelsResult                         # line 373-390 (iterates module-level _DEFAULT_KNOWN_MODELS)
    async def search_records(self, model, domain=None, fields=None, limit=100, offset=0, order=None) -> SearchResult   # line 406-455
    async def create_record(self, model: str, values: dict[str, Any]) -> CreateResult   # line 493-506 → _execute(model, "create", [values])
    async def attach_document(self, res_model: str, res_id: int, name: str, source: str, mimetype=None, description=None) -> BinaryFieldResult   # line 928
    async def _get_odoo_major_version(self) -> int | None               # line 982
    async def aggregate_records(...) -> AggregateResult                  # line 994 (FEAT-614 amends it; do not touch here)

# packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py
def _looks_like_ids(value: Any) -> bool                                 # line 31
class Json2Transport(AbstractOdooTransport):                            # line 38
    name: str = "json2"                                                 # line 41
    def _headers(self) -> dict[str, str]                                # line 60-65  (bearer password + X-Odoo-Database; "" accepted by staging)
    async def _request_json2(self, model: str, method: str, body: dict[str, Any] | None = None) -> Any   # line 67-88; raises OdooRPCError(f"Odoo JSON-2 error [{status}] calling {model}.{method}: {message}") at :84, OdooAuthenticationError for 401/403
    @staticmethod
    def _build_body(method: str, args, kwargs) -> dict[str, Any]        # line 90-162; "create" branch :114-118 → {"vals_list": args[0]}; kwargs-only → body = kwargs (:156-157)
    async def authenticate(self) -> int                                 # line 164-169 (res.users.context_get)
    async def execute_kw(self, model, method, args=None, kwargs=None) -> Any   # line 171-179

# packages/ai-parrot/src/parrot/interfaces/odoointerface.py
class OdooConfig(BaseModel):                                            # line 55
    url: str; database: str; username: str; password: str; timeout: int = 30; verify_ssl: bool = True   # line 67-72 (database is `str` — "" is valid)

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    exclude_tools: tuple[str, ...] = ()                                 # line 240 (opt-out hook, documented in §7; not used by this feature)
    confirming_tools: frozenset = frozenset()                           # line 272
    def get_tools(self, ...)                                            # line 494; skips names starting with "_" (:555) and non-coroutines (:578); prefix rule :540-552
    # line 694-699: confirmation is matched on the UNPREFIXED method name (`method_name in self.confirming_tools`)

# packages/ai-parrot/src/parrot/tools/manager.py
    # line 806-811: raises on tool-name collision when the tool comes from a prefixed toolkit (→ one Odoo toolkit per agent)

# packages/ai-parrot/src/parrot/tools/decorators.py
def requires_permission(*permissions: str)                              # line 9  (sets obj._required_permissions)
def tool_schema(schema: Type[BaseModel], description: Optional[str] = None)   # line 39 (sets func._args_schema, func._tool_description)

# packages/ai-parrot-tools/src/parrot_tools/odoo/models/entities.py
Many2one = Union[tuple[int, str], list[Any], bool, None]                # line 19
class _OdooEntity(BaseModel): model_config = ConfigDict(extra="allow", populate_by_name=True); id; display_name   # line 22-30
# packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py
OdooDomain = list[Any]                                                  # line 16
class _OdooBaseInput(BaseModel): model_config = ConfigDict(extra="ignore", protected_namespaces=())   # line 19-22
# packages/ai-parrot-tools/src/parrot_tools/odoo/models/envelopes.py
class FieldSelectionMetadata(BaseModel)                                 # line 14
class ModelOperations / ModelInfo / ModelsResult                        # line 27 / 36 / 44
class BinaryFieldResult                                                 # line 146

# packages/ai-parrot/src/parrot/conf.py
ODOO_URL … ODOO_VERIFY_SSL                                              # line 812-817 (config.get / getint / getboolean pattern)

# packages/ai-parrot/tests/test_odoo_toolkit.py
def _fake_transport(uid: int = 1) -> MagicMock                          # line 57-80
def _make_toolkit(transport: MagicMock | None = None) -> OdooToolkit    # line 83
# packages/ai-parrot/tests/test_odoo_json2_transport.py
def _config(**overrides) -> OdooConfig                                  # line 35
_mock_aiohttp_response(...)                                             # line 47; last test: test_json2_unauthorized_maps_to_authentication_error at :162
```

### Live-verified Odoo facts (staging, Softhealer + TROC)
```
Models: sh.helpdesk.ticket, sh.helpdesk.team, helpdesk.stages, helpdesk.category, helpdesk.subcategory, helpdesk.priority,
        helpdesk.sub.type, helpdesk.tags, sh.helpdesk.ticket.type, sh.helpdesk.sla, sh.helpdesk.sla.status, sh.helpdesk.sla.analysis,
        sh.helpdesk.ticket.stage.info, sh.ticket.alarm, sh.helpdesk.ticket.extra_fields, sh.helpdesk.reassign.wizard,
        sh.helpdesk.ticket.mass.update.wizard, sh.helpdesk.ticket.merge.ticket.wizard, ticket.time.account.line
Ticket required non-readonly: state (selection customer_replied|staff_replied), partner_id
Stages (name → sh_next_stage): New→Open→Pending close→Pending reminder→Closed(None); helpdesk.stages has NO fold/is_close fields
Ticket methods verified over JSON-2 with [[id]]: action_take_ticket (sets user_id), action_closed (→ Closed, close_date, history line),
        action_done / action_open / action_cancel / action_approve (return null, NO change on this tenant),
        action_ticket_start (raises "Please Set Default Project from configuration!"), action_ticket_end (returns act_window on ticket.time.account.line)
write stage_id → works, creates a sh.helpdesk.ticket.stage.info line; write sh_user_ids [[6,0,ids]] → works
message_post kwargs {body, message_type:"comment", subtype_xmlid:"mail.mt_comment"|"mail.mt_note"} → returns message id; mt_comment REOPENS a Closed ticket (→ Open), mt_note does not
Wizards: reassign — create {ticket_id,new_user_id} then action_confirm [[wid]] → {'type':'ir.actions.act_window_close'}, user_id changes;
         mass update — create {helpdesks_ticket_ids [[6,0,ids]], check_helpdesks_state, helpdesk_stages} then update_record [[wid]] → None, stage changes;
         merge — button action_merge_tickets (shape only, not exercised); timer line — button end_ticket
create over JSON-2: sh.helpdesk.ticket / helpdesk.tags reject vals_list, values and vals (422/500); web_save {vals, specification:{id:{}}} → [{id, ...}]
         wizard models (TransientModel) accept the normal create → returns [id]
SLA: sh.helpdesk.sla {name R, sh_team_id R, sh_days/sh_hours/sh_minutes R, sh_sla_target_type reaching_stage|assign_to, sh_stage_id, sh_ticket_type_id}; 0 policies on staging
ticket.time.account.line: {name R, start_date, end_date, duration, company_id, project_id}
API user: internal; groups Helpdesk / Support Manager, Helpdesk SLA Policy, Helpdesk Ticket Alarm; CRUD all True on the ticket
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `OdooHelpdeskToolkit` | `OdooToolkit.__init__` | `super().__init__(...)` then `self.config = OdooConfig(...)` | `toolkit.py:202-241` |
| every helpdesk tool | `OdooToolkit._execute` | `await self._execute(model, method, args, kwargs)` | `toolkit.py:283` |
| `_load_ticket` | `OdooToolkit._read_one` | `await self._read_one("sh.helpdesk.ticket", id, fields)` | `toolkit.py:299` |
| `attach_to_ticket` | `OdooToolkit.attach_document` | direct call with `res_model="sh.helpdesk.ticket"` | `toolkit.py:928` |
| `list_models` override | `_DEFAULT_KNOWN_MODELS`, `ModelsResult` | same loop as base | `toolkit.py:373-390` |
| `Json2Transport.execute_kw` (M1) | `_request_json2`, `OdooRPCError` | catch + retry `web_save` | `json2.py:67-88`, `:171-179` |
| `create_ticket` | `Json2Transport` fallback | `_execute("sh.helpdesk.ticket", "create", [values])` | `toolkit.py:283` → `json2.py:171` |
| conf keys | `parrot.conf` loader | `config.get / getint / getboolean` | `conf.py:812-817` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot_tools.odoo.helpdesk`~~, ~~`OdooHelpdeskToolkit`~~, ~~`OdooHelpdeskMixin`~~ — created by this feature (M5); no mixin is created.
- ~~`parrot_tools/odoo/fieldservice.py`~~, ~~`OdooFieldServiceToolkit`~~ — FEAT-216 was never implemented; do not import it.
- ~~`ODOO_HELPDESK_*` in `parrot.conf`~~ — added by M2; today only the env file has them.
- ~~`OdooToolkit.known_models`~~ / ~~`self._DEFAULT_KNOWN_MODELS`~~ — the constant is module-level; a class attribute would be ignored (S1).
- ~~`Json2Transport._build_body` mapping for `get_views`, `name_search`, `web_save`~~ — none; `name_search`/`message_post` work only kwargs-only; `web_save` is called by M1's fallback through `_request_json2`.
- ~~`_DOMAIN_FIRST_METHODS`~~ — belongs to FEAT-614; it exists only once FEAT-614 merges; this feature neither adds nor relies on it except via `ticket_stats`.
- ~~`helpdesk.stages.fold` / `is_close`~~, ~~`sh.helpdesk.ticket.extra_fields.field_label` / `field_type`~~, ~~`base.automation`~~ — not present on the instance (500 / 404 observed).
- ~~`sh.helpdesk.ticket.action_done` moving the ticket~~ on this tenant — verified no-op; never assume it applied.
- ~~`OdooToolkit.get_tools_filtered(exclude=…)` for narrowing the helpdesk surface~~ — rejected by the owner; not used.
- ~~`AbstractToolkit.tool_prefix = "odoo_hd"`~~ — rejected by the owner; prefix stays `odoo`.
- ~~`requests`, `httpx`, `langchain*`~~ — banned (`ruff` TID251).

### Edit Sites (Blueprint Anchors)

Verified against: `b3141f286`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py` | MODIFY (M1: add `_is_create_signature_error`, `_create_via_web_save` before, and the fallback inside `execute_kw`) | `    async def execute_kw(` | `json2.py:171` | 1 |
| `packages/ai-parrot/tests/test_odoo_json2_transport.py` | MODIFY (M1: append tests after the last test) | `async def test_json2_unauthorized_maps_to_authentication_error():` | `test_odoo_json2_transport.py:162` | 1 |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY (M2: insert the helpdesk block after this line) | `ODOO_VERIFY_SSL = config.getboolean("ODOO_VERIFY_SSL", fallback=True)` | `conf.py:817` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_entities.py` | CREATE (M3) | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_inputs.py` | CREATE (M3) | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/models/helpdesk_envelopes.py` | CREATE (M3) | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/models/__init__.py` | MODIFY (M3: add `from .helpdesk_entities import (...)` etc. after the inputs import block; extend `__all__`) | `    AttachDocumentInput,` (import block) / `    "AttachDocumentInput",` (`__all__`) | `models/__init__.py:33` / `:108` | 1 / 1 |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk_normalize.py` | CREATE (M4) | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py` | CREATE (M5; M6–M9 append sections) | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py` | MODIFY (M5: add `from .helpdesk import OdooHelpdeskToolkit` after the toolkit import block; add to `__all__`) | `    OdooToolkit,` (import) / `    "OdooToolkit",` (`__all__`) | `odoo/__init__.py:27` / `:31` | 1 / 1 |
| `packages/ai-parrot/tests/test_odoo_helpdesk_models.py` | CREATE (M3) | — | — | — |
| `packages/ai-parrot/tests/test_odoo_helpdesk_normalize.py` | CREATE (M4) | — | — | — |
| `packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py` | CREATE (M2/M5; M6–M9 append) | — | — | — |
| `docs/tools/odoo-helpdesk.md` | CREATE (M10) | — | — | — |
| `examples/odoo/helpdesk_live_smoke.py` | CREATE (M10) | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Subclass `OdooToolkit`; public `async def` = tool; private helpers underscore-prefixed; every tool
  has a docstring (it is the LLM description) and a `@tool_schema(<Input>)`; every mutating tool
  carries `@requires_permission("odoo.write")` (as `confirm_sale_order`, `toolkit.py:792`).
- Action-then-read-back (`toolkit.py:792-800`), extended with the post-condition contract of §3 M7.
- All Odoo I/O via `self._execute`; `create` **always** through `_execute(model, "create", [vals])`
  so the M1 fallback applies on every transport; never call `web_save` from the helpdesk layer.
- Per-model default field constants (`_TICKET_DEFAULT_FIELDS`) as `_SALE_ORDER_DEFAULT_FIELDS` (`toolkit.py:746`);
  `select_smart_fields` fallback only when the caller passes an explicit empty field list.
- Logging via `self.logger` (`toolkit.py:241`); no `print`.
- Tests: `_fake_transport` + ordered `execute_kw.side_effect`; assert the exact `(model, method, args, kwargs)` tuple.
- `black` line-length 120, `ruff check` clean, Google docstrings, strict type hints.

### Known Risks / Gotchas
- **One Odoo toolkit per agent.** `OdooHelpdeskToolkit` inherits every `odoo_*` tool under the same
  prefix; registering it together with a plain `OdooToolkit` raises a name collision in `ToolManager`
  (`manager.py:806-811`). The `odoo_hd` agent must load only the helpdesk toolkit. Deployments that
  want a narrower surface set `exclude_tools` (`parrot/tools/toolkit.py:240`) on a subclass — a
  one-line opt-out, deliberately not the default (owner decision, S3).
- **`state` is reply direction, not lifecycle.** Exposed as `replied_status`; lifecycle comes from
  `stage_id` + booleans. Never filter "open tickets" on `state`.
- **Tenant no-op actions.** `action_done/open/cancel/approve` do nothing on this tenant (stage guard
  flags off). Tools report `applied=False`; only `reopen_ticket`/`move_ticket_to_stage` write the stage.
- **Public comments reopen closed tickets** (`mail.mt_comment`); the comment tool defaults to
  internal notes and reports `reopened`.
- **JSON-2 `create` on Odoo 19** rejects models with an overridden `create`; the M1 fallback is
  message-based (`required argument` / `unexpected keyword argument`) and must never retry
  auth/network errors or unrelated 422s.
- **FEAT-614 overlap.** `json2.py` and `test_odoo_json2_transport.py` are edited by both features;
  this worktree is created **after** FEAT-614 merges (Worktree Strategy). `ticket_stats` needs it.
- **Stage ids differ per tenant** (4/22/23/24/21 on staging). Resolve by name; cache per instance.
- **SLA behaviour is unobservable without a policy**; the M8 live check creates and deletes one
  (authorised). SLA status computation timing is Softhealer's — document what was observed.
- **Timer needs "Default Project"** on the tenant; `start_ticket_timer` surfaces the error as a
  warning instead of raising.
- **Base `_pre_execute` skips eager auth when `database == ""`** (`toolkit.py:268-271`); the lazy
  `_ensure_transport` inside `_execute` still authenticates, so JSON-2 with an empty database works
  (verified). Do not "fix" `_pre_execute`.
- `sh.helpdesk.ticket.timehseet_ids` is misspelled in Odoo — keep the wire name.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aiohttp` | existing | JSON-2 transport (unchanged) |
| `pydantic` | `>=2` (existing) | models |
| — | — | no new dependency |

---

## 8. Open Questions

- [x] **Subclass, mixin or in-place methods?** — *Resolved in proposal (U1)*: subclass `OdooHelpdeskToolkit(OdooToolkit)` in `parrot_tools/odoo/helpdesk.py`.
- [x] **Tool groups in v1?** — *Resolved in proposal (U2)*: all groups (tickets, assignment, SLA, reference data, stats, wizards, timesheet).
- [x] **Transition semantics / staging verification?** — *Resolved in proposal (U3)*: call Softhealer `action_*` with `[[id]]`; throwaway tickets authorised — **done** (ids 69/70/71, deleted), results in §6 Live-verified facts.
- [x] **Configuration contract?** — *Resolved in proposal (U4)*: new `ODOO_HELPDESK_*` conf keys, database optional/empty.
- [x] **TROC payload in v1?** — *Resolved in spec Q&A 2026-10-01 (U5)*: yes, read-only `extra_fields` dict + `dynamic_form_submission_id` via the normaliser.
- [x] **Tool surface and prefix?** — *Resolved in spec Q&A 2026-10-01*: prefix `odoo`, expose everything (FEAT-216); one Odoo toolkit per agent.
- [x] **HITL set?** — *Resolved in spec Q&A 2026-10-01*: `cancel_ticket`, `merge_tickets`, `mass_update_tickets`, unioned with the inherited shell confirmations.
- [x] **Throwaway SLA policy on staging?** — *Resolved in spec Q&A 2026-10-01*: yes, one policy with immediate deletion (M8 live check).
- [x] **Where do the helpdesk models live?** — *Resolved by the spec author*: three sibling modules (`helpdesk_entities/inputs/envelopes.py`) re-exported from `models/__init__.py`, to avoid FEAT-614's edits to `inputs.py`.
- [x] **Where is the JSON-2 `create` fix?** — *Resolved by the spec author*: in `Json2Transport.execute_kw` (M1) so every caller benefits; the helpdesk never calls `web_save` itself.
- [ ] **`only_open` definition** (§3 M5): stages named `Closed` or last in the `sh_next_stage` chain. Confirm at implementation against a second tenant if one exists — *Owner: implementer (M5 Completion Note)*.
- [ ] **Merge wizard live check**: `action_merge_tickets` was not exercised on staging (shape only). The M9 task runs it once on two throwaway tickets — *Owner: M9 task*.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted proposal** (never over this spec).
> Model: `gpt-5.6-luna` (codex-cli 0.157.0, reasoning high) · Status: completed (11 suggestions, 2026-09-30T22:35–22:39Z)
> · Transcript: `sdd/state/FEAT-616/design_research/`
> Every `affected_paths` entry passed repository containment and `test -e`.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make known-model registration polymorphic (architecture) | CONFIRM | verified: `list_models` iterates the module constant (`toolkit.py:376`); the subclass overrides `list_models` | §3 M5, AC6 |
| S2 | Prevent helpdesk credentials from falling through to generic `ODOO_*` (risk) | CONFIRM | verified: `value or ODOO_*` at `toolkit.py:230-233`; subclass rebuilds `self.config` with `is None` semantics | §3 M2, AC2–AC3 |
| S3 | Do not expose unrestricted inherited CRUD by default (risk) | REJECT | owner decision (spec Q&A): expose all, prefix `odoo`; `exclude_tools` documented as opt-out | §7 Known Risks |
| S4 | Choose a distinct prefix when both toolkits may coexist (architecture) | REJECT | verified collision at `manager.py:806-811`; owner kept `odoo` → hard rule "one Odoo toolkit per agent" | §7, AC5 |
| S5 | Add an explicit JSON-2 mapping for name resolution (api) | CONFIRM (as design rule) | `name_search` works kwargs-only (live); resolvers use `search_read` exact-then-`ilike` — no transport change | §3 M5, AC13 |
| S6 | Treat wizard calls as transport-specific contracts (api) | CONFIRM (verified) | reassign and mass-update wizards verified live over JSON-2; merge left to the M9 live check | §3 M9, §8 |
| S7 | Do not silently convert action failure into direct stage writes (risk) | CONFIRM | post-condition contract; only `reopen_ticket`/`move_ticket_to_stage` write `stage_id`, reported | §3 M7, AC9–AC11 |
| S8 | Normalize derived helpdesk output before Pydantic validation (api) | CONFIRM | pure `helpdesk_normalize.py` with shape tests | §3 M4, AC14 |
| S9 | Constrain ticket write payloads (api) | CONFIRM | explicit `UpdateTicketInput`; lifecycle/assignment/SLA excluded | §3 M6, AC8 |
| S10 | Union helpdesk HITL rules with inherited confirmations (risk) | CONFIRM | verified unprefixed-name matching (`parrot/tools/toolkit.py:694-699`); union set | §3 M5, AC7 |
| S11 | Test stable stats envelopes across Odoo 19 and legacy shapes (testing) | CONFIRM | `normalize_stats_groups` + fixtures for both shapes | §3 M4/M9, AC15 |

Summary: **9** confirmed · **2** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-616-odoo-toolkit-upgrades` (from `origin/dev`,
  created by `/sdd-start` **after FEAT-614 has merged into `dev`**); the `sdd-coder` engine gives
  each task its own sub-worktree inside it.
- **Module dependency graph** (edge = import or same-file precedence, with evidence):
  - M1 (json2 fallback) — no edges; concurrent with M2/M3/M4.
  - M2 (conf + `__init__`) — no edges; concurrent.
  - M3 (models) — no edges; concurrent.
  - M4 → M3 (imports `HelpdeskTicket`, `HelpdeskLifecycle`, `StatsGroup`).
  - M5 → M2, M3, M4 (constructor, models, `normalize_ticket`); M5 creates `helpdesk.py`.
  - M6, M7, M8, M9 → M5 (append to `helpdesk.py` and `test_odoo_helpdesk_toolkit.py`); M9 → M4 (`normalize_stats_groups`).
  - M10 → M1–M9.
- **Shared files** (tasks serialised): `helpdesk.py` and `test_odoo_helpdesk_toolkit.py` (M5–M9);
  `models/__init__.py` (M3 only); `odoo/__init__.py` (M5 only); `json2.py` + its test (M1 only).
- **Exclusive resources**: none (no extension rebuild, no lockfile, no migration).
- **Cross-feature dependencies**: **FEAT-614** must be merged first (edits `json2.py`, `toolkit.py`,
  `inputs.py`, `test_odoo_json2_transport.py`, `test_odoo_toolkit.py`; `ticket_stats` relies on its
  `_DOMAIN_FIRST_METHODS` mapping).
- **Live checks** (M8, M9, M10) need `ODOO_HELPDESK_*` from the environment; they are opt-in,
  never part of `pytest`, and every record they create is deleted in a `finally`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-01 | Jesus Lara / Claude Fable 5.1 | Initial draft from the accepted proposal, the staging write-verification and the codex design research |
