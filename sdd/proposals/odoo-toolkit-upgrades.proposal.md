---
id: FEAT-616
title: OdooHelpdeskToolkit — typed helpdesk tools for the Softhealer helpdesk (Odoo 19) on top of OdooToolkit
slug: odoo-toolkit-upgrades
type: feature
mode: enrichment
status: discussion
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-30
  summary_oneline: Extend OdooToolkit with an OdooHelpdeskToolkit subclass operating the Softhealer/TROC helpdesk on the Odoo 19 staging instance
overall_confidence: medium
base_branch: dev
projects: [ai-parrot-tools, ai-parrot]
tags: [odoo, helpdesk, softhealer, json2, toolkit, structured-outputs, sla]
research_state: sdd/state/FEAT-616/
created: 2026-09-30
updated: 2026-10-01
---

# FEAT-616 — OdooHelpdeskToolkit: typed helpdesk tools for the Softhealer helpdesk (Odoo 19)

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline` (slug requested: `odoo-toolkit-upgrades`)
> **Audit**: [`sdd/state/FEAT-616/`](../state/FEAT-616/)
> **ID note**: `FEAT-616` was reserved in the ledger by `reserve_ids.py` on 2026-10-01
> (the provisional `FEAT-615` used while drafting was taken by `bookstore-reindex-atomic-swap`).

---

## 0. Origin

The original request, preserved verbatim (Spanish). Full source at `sdd/state/FEAT-616/source.md`.

> En el Odoo expuesto en staging environment: https://pokemon.helpdesk.staging.trocdigital.io/
> con credenciales acequibles via ODOO_HELPDESK_URL, ODOO_HELPDESK_USER, ODOO_HELPDESK_PASSWORD
> y ODOO_HELPDESK_APIKEY hay un sistema helpdesk que debemos descubrir cual es (al parecer es un
> modulo custom de "softhealer", un partner hindú), necesitamos hacer un research sobre este
> Odoo v.19 para ampliar el OdooToolkit ya sea incorporando métodos o extendiendo con un mixin
> de OdooHelpdesk para incorporar métodos para operar con el helpdesk system (crear tickets,
> transicionar tickets, gestionar las incidencias, definir SLAs, etc), esto incluye model inputs
> para los métodos de entrada y gestión de las salidas (structured outputs)

**Initial signals** (extracted, not interpreted):
- Verbs: "ampliar", "incorporar", "extender", "operar" → additive capability (enrichment)
- Named entities: `OdooToolkit`, "OdooHelpdesk" mixin, Softhealer, Odoo 19, `ODOO_HELPDESK_*` env keys, staging URL
- Operations named: create tickets, transition tickets, manage incidents, define SLAs
- Explicit deliverable shape: Pydantic **inputs** per method and **structured outputs**
- Acceptance criteria provided: no

---

## 1. Synthesis Summary

The staging instance is Odoo 19.0 running **Softhealer Technologies' `sh_all_in_one_helpdesk`**
(19.0.0.0.1) under three TROC-owned layers (`troc_helpdesk` 19.0.1.32.0,
`dynamic_form_helpdesk`, `troc_helpdesk_dynamic_forms`); tickets are `sh.helpdesk.ticket`
records whose lifecycle is `stage_id` over five linear stages, with transitions exposed as
`action_*` server methods and SLAs modelled as `sh.helpdesk.sla` policies. The existing
`OdooToolkit` (`packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`) already provides
the transport, lazy auth, the `_execute` chokepoint, the `confirm_sale_order`
action-then-read-back pattern, and a three-module Pydantic split (`models/inputs.py`,
`models/envelopes.py`, `models/entities.py`). The repo also holds a directly applicable
precedent, FEAT-216 `OdooFieldServiceToolkit`, which resolved the same subclass-vs-mixin
question in favour of a **subclass**. We therefore propose a new
`OdooHelpdeskToolkit(OdooToolkit)` in `parrot_tools/odoo/helpdesk.py` with typed inputs,
entities and result envelopes for ticket CRUD, assignment, transitions, comments, SLA policies,
reference data, stats and wizards — sequenced after the in-flight FEAT-614 JSON-2 fix, which
edits the same files and is a prerequisite for any aggregate tool. Recommended next step:
`/sdd-spec`.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-616/findings/`. Live-instance evidence
> (read-only probes, sanitized) is under `findings/live/`. **No fabricated paths or symbols.**

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | `OdooToolkit` | 172-292 | base toolkit: `ODOO_*` config fallback, lazy auth (`_ensure_transport`), `_execute` RPC chokepoint, `_read_one`, `_get_fields_metadata` | F002 |
| 2 | `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | `_DEFAULT_KNOWN_MODELS` | 149-160 | static model list for `list_models` — no helpdesk models | F002 |
| 3 | `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | `OdooToolkit.confirm_sale_order` | 792-800 | action-then-read-back pattern (`action_confirm` with `[[id]]` → `_read_one` → entity) | F003 |
| 4 | `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | `OdooToolkit.search_records` | 406-455 | generic search + `select_smart_fields` fallback → `SearchResult` | F003 |
| 5 | `packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py` | `_OdooBaseInput` | 14-24 | base for tool input schemas (`extra="ignore"`), `OdooDomain` | F004 |
| 6 | `packages/ai-parrot-tools/src/parrot_tools/odoo/models/envelopes.py` | `CreateResult` | 52-84 | envelope conventions (`success/record/record_id/model/message`) | F004 |
| 7 | `packages/ai-parrot-tools/src/parrot_tools/odoo/models/entities.py` | `_OdooEntity` | 19-31 | entity base (`extra="allow"`, `Many2one` alias) | F004 |
| 8 | `packages/ai-parrot-tools/src/parrot_tools/odoo/models/__init__.py` | `__all__` | — | re-export point for new models | F004 |
| 9 | `packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py` | `__all__` | — | package export point for the new toolkit | F004 |
| 10 | `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py` | `Json2Transport._build_body` | 90-162 | JSON-2 positional→named mapping; `[[id]]` action calls work; `get_views` and (until FEAT-614) `read_group` family do not | F005, F021 |
| 11 | `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py` | `Json2Transport._headers` | 60-65 | bearer API key + `X-Odoo-Database` (empty accepted by staging) | F005, F012 |
| 12 | `packages/ai-parrot/src/parrot/tools/decorators.py` | `tool_schema` | 39-55 | per-tool input schema decorator | F011 |
| 13 | `packages/ai-parrot/src/parrot/tools/decorators.py` | `requires_permission` | 9-38 | permission gate (`odoo.write`) for mutating tools | F011, F003 |
| 14 | `packages/ai-parrot-tools/src/parrot_tools/odoo/smart_fields.py` | `select_smart_fields` | 1-40 | pure field scorer, reusable for default ticket fields | F011 |
| 15 | `packages/ai-parrot/tests/test_odoo_toolkit.py` | `_fake_transport` | 57-90 | AsyncMock transport fixture to reuse | F009 |
| 16 | `packages/ai-parrot-tools/src/parrot_tools/zammad.py` | `ZammadToolkit` | 141-330 | naming precedent for helpdesk-shaped tools | F008 |
| 17 | `sdd/specs/odoo-fieldservice-toolkit.spec.md` | `OdooFieldServiceToolkit` | 60-200 | approved, unimplemented precedent: subclass, three-module models, HITL gating | F007 |
| 18 | `sdd/specs/odoo-json2-domain-first-methods.spec.md` | FEAT-614 | 1-140 | in-flight change on the same files; prerequisite for stats tools | F006, F021 |

### 2.2 Constraints Discovered

- **Single RPC chokepoint.** All Odoo I/O goes through `OdooToolkit._execute`; the helpdesk
  layer must not open its own aiohttp sessions.
  *Implication*: helpdesk tools are thin wrappers = `_execute` + Pydantic validation.
  *Evidence*: F002, F005
- **Reflection-based tool discovery.** Public `async def` methods on a subclass auto-register
  as `odoo_<name>`; `@tool_schema` + docstring define the LLM schema; writes use
  `@requires_permission("odoo.write")`.
  *Implication*: private helpers must be underscore-prefixed; every tool needs a docstring.
  *Evidence*: F003, F007, F011
- **Three-module model split.** `_OdooEntity(extra=allow)`, `_OdooBaseInput(extra=ignore)`,
  envelope classes; re-exported from `models/__init__.py`.
  *Implication*: `HelpdeskTicket`, `*Input`, `*Result` follow the same split.
  *Evidence*: F004
- **Tenant lifecycle semantics.** Ticket lifecycle is `stage_id` over New(4) → Open(22) →
  Pending close(23) → Pending reminder(24) → Closed(21), chained by `sh_next_stage`; the
  required `state` field is *reply direction* (`customer_replied|staff_replied`), not
  lifecycle; stage ids are instance-specific; Softhealer's done/cancel button flags are off
  on every stage.
  *Implication*: resolve stages by name / `sh_next_stage` at runtime, never hard-code ids;
  present `state` to the LLM as `replied_status`.
  *Evidence*: F015, F016, F017
- **JSON-2 mapping limits.** `[[id]]` action calls, `search_read/search_count/read/write/
  create/name_search/fields_get` work; `get_views` is unmappable; `formatted_read_group`
  returns 422 until FEAT-614 lands.
  *Implication*: stats tools depend on FEAT-614 (or N×`search_count`); view-driven discovery
  must read `ir.ui.view.arch_db`.
  *Evidence*: F005, F021, F006
- **File overlap with FEAT-614.** FEAT-614 edits `toolkit.py`, `models/inputs.py`,
  `test_odoo_toolkit.py`.
  *Implication*: keep the helpdesk feature in new files and/or base its worktree after
  FEAT-614 merges.
  *Evidence*: F006
- **Credentials contract.** `ODOO_HELPDESK_URL/USER/PASSWORD/APIKEY` exist only in
  `env/.env` (no DATABASE key) and nothing in `packages/` reads them; `OdooToolkit` knows
  only `ODOO_*` via `parrot.conf`; JSON-2 authenticates with an empty database.
  *Implication*: new `ODOO_HELPDESK_*` conf keys (resolved, U4) with `database` optional.
  *Evidence*: F008, F002, F012
- **Tenant customisation.** TROC adds `extra_field_ids` (a `field_name → value` bag, 643
  rows), dynamic-form origin, reassign wizard, `assignee_on_leave`, webhook dedupe; 0 SLA
  policies exist on staging.
  *Implication*: SLA outputs cannot be validated end-to-end without creating a policy;
  extra fields need a generic dict projection.
  *Evidence*: F013, F015, F018, F019
- **Test conventions.** Odoo toolkit tests live in `packages/ai-parrot/tests/` with an
  AsyncMock transport and assert exact `execute_kw` tuples.
  *Evidence*: F009

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched |
|--------|------|--------|---------|---------|
| `83586b63f` | 2026-09-30 | Jesus Lara | sdd: add spec for FEAT-614 — odoo-json2-domain-first-methods | `sdd/specs/…` |
| `e3b638895` | 2026-09-30 | Jesus Lara | sdd: reserve 1 feature id(s) for odoo-json2-domain-first-methods | ledger |
| `71d835370` | 2026-06-24 | Jesus Lara | wip: dev tools | `parrot_tools/odoo` |
| `e899b9b8f` | 2026-06-16 | Jesus Lara | fix(odoo-pageindex-documentation-agent): address all code-review findings | `parrot_tools/odoo` |
| `d242c4d31` | 2026-06-16 | Jesus Lara | feat: TASK-1571 — OdooToolkit odoo-bin/odoo-cli shell functions | `parrot_tools/odoo/shell.py` |

No helpdesk-related commits exist. *Evidence*: F010

### 2.4 Live-instance discovery (what the helpdesk is)

| Aspect | Finding | Evidence |
|---|---|---|
| Server | Odoo `19.0-20260324`, JSON-2 transport, API key as bearer, db listing disabled, empty `X-Odoo-Database` accepted (uid 2241) | F012 |
| Vendor | `sh_all_in_one_helpdesk` 19.0.0.0.1 — Softhealer Technologies (OPL-1); deps mail, portal, product, resource, sale_management, purchase, account, hr_timesheet, crm, project | F013 |
| TROC layers | `troc_helpdesk` 19.0.1.32.0 (deps `data_injector_api`), `dynamic_form_helpdesk` (WebbyCrown forms → tickets), `troc_helpdesk_dynamic_forms` (NavAPI/QuerySource engine) | F013 |
| Models | `sh.helpdesk.ticket`, `sh.helpdesk.team`, `helpdesk.stages`, `helpdesk.category`, `helpdesk.subcategory`, `helpdesk.priority`, `helpdesk.sub.type`, `helpdesk.tags`, `sh.helpdesk.ticket.type`, `sh.helpdesk.sla`, `sh.helpdesk.sla.status`, `sh.helpdesk.sla.analysis`, `sh.helpdesk.ticket.stage.info`, `sh.ticket.alarm`, wizards (`sh.helpdesk.reassign.wizard`, `…mass.update.wizard`, `…merge.ticket.wizard`), TROC `sh.helpdesk.ticket.extra_fields`, `sh.helpdesk.webhook.error_dedupe`, `dynamic.form(.submission)` | F014 |
| Ticket (127 fields) | required: `state` (reply direction), `partner_id`; lifecycle `stage_id` + computed `open_boolean/done_stage_boolean/closed_stage_boolean/cancel_stage_boolean`, `close_date/close_by`, `cancel_reason`; classification `team_id/user_id/sh_user_ids/category_id/sub_category_id/ticket_type/subject_id/priority/tag_ids`; content `name/description/comment/customer_comment/email/mobile_no/person_name/attachment_ids`; SLA `sh_sla_policy_ids/sh_sla_status_ids/sh_sla_deadline/sh_due_date/sh_status`; timesheet `timehseet_ids`(sic)/`ticket_running`; links to SO/PO/invoice/lead/task/merged tickets; mail.thread + activities | F015 |
| Transitions | form buttons: `action_approve`, `action_reply`, `action_send_whatsapp`, `action_done` (Resolved), `action_closed`, `action_cancel`, `action_open` (Re-Open), `preview_ticket`; timesheet `action_ticket_start/end`; TROC `action_take_ticket`, `action_open_reassign`; server actions Mass Update / Merge; cron "Auto Close Helpdesk Ticket" (daily) | F016, F017 |
| SLA | `sh.helpdesk.sla`: `name`, `sh_team_id` (R), `sh_days/sh_hours/sh_minutes` (R), `sh_sla_target_type` (`reaching_stage|assign_to`), `sh_stage_id`, `sh_ticket_type_id`; `sh.helpdesk.sla.status` per ticket×policy (`sh_deadline`, `sh_done_sla_date`, `sh_exceeded_hours`, `sh_status`); alarms `sh.ticket.alarm` (`email|popup`); **0 policies configured** | F018 |
| Reference data | 11 kiosk-failure categories, 4 priorities, 1 type, 1 sub type, 1 subcategory, 1 team ("Compliance"), 0 tags; 42 tickets (New 22 / Open 4 / Pending close 10 / Closed 6); extra fields keyed `poke_*`, `organization_id`, `field_26` (Kiosk Number) | F016, F019 |
| ACL | API user internal, groups Helpdesk / Support Manager, Helpdesk SLA Policy, Helpdesk Ticket Alarm; CRUD all true on tickets | F020 |

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`packages/ai-parrot-tools/src/parrot_tools/odoo/helpdesk.py`** —
  `OdooHelpdeskToolkit(OdooToolkit)` (resolved U1). `tool_prefix` inherited (`odoo`) so tools
  surface as `odoo_<name>`; the spec may decide a dedicated prefix (`odoo_hd`) — see §5.
  Tool groups (resolved U2 — **all in v1**):
  - *Tickets — read*: `get_ticket`, `search_tickets`, `list_my_tickets`, `get_ticket_history`
    (stage.info lines), `get_ticket_messages` (mail.message), `get_ticket_extra_fields`.
  - *Tickets — write*: `create_ticket` (partner by id/email/name, category/priority/team/type
    by id **or** name), `update_ticket`, `add_ticket_comment` / `reply_ticket`
    (`message_post`), `attach_to_ticket` (reuses inherited `attach_document`).
  - *Assignment*: `assign_ticket` (user_id / `sh_user_ids`), `take_ticket`
    (`action_take_ticket`), `reassign_ticket` (`sh.helpdesk.reassign.wizard`).
  - *Transitions* (resolved U3 — call Softhealer `action_*` with `[[id]]`, verified on staging
    with a throwaway ticket during the spec phase): `move_ticket_to_stage` (by name or
    `sh_next_stage`), `resolve_ticket` (`action_done`), `close_ticket` (`action_closed`),
    `cancel_ticket` (`action_cancel` + `cancel_reason`), `reopen_ticket` (`action_open`),
    `approve_ticket`. Each returns a `TicketTransitionResult` (`from_stage`, `to_stage`,
    `method_used`, `warnings`).
  - *SLA*: `list_sla_policies`, `create_sla_policy`, `update_sla_policy`,
    `get_ticket_sla_status`, `list_ticket_alarms`.
  - *Reference data*: `list_stages`, `list_teams`, `list_categories`, `list_priorities`,
    `list_ticket_types`, `list_tags` (+ name→id resolution helpers, cached like
    `_fields_cache`).
  - *Stats & wizards & timesheet*: `ticket_stats` (by stage/team/user/category — depends on
    FEAT-614; interim N×`search_count`), `merge_tickets`, `mass_update_tickets`,
    `start_ticket_timer` / `stop_ticket_timer`.
- **Entities** (`models/entities.py`): `HelpdeskTicket`, `HelpdeskStage`, `HelpdeskTeam`,
  `HelpdeskCategory`, `HelpdeskPriority`, `HelpdeskTicketType`, `HelpdeskSla`,
  `HelpdeskSlaStatus`, `HelpdeskStageInfo` — all `_OdooEntity`; `HelpdeskTicket` exposes
  `replied_status` (alias of `state`), a derived `lifecycle` block (`stage_name` +
  booleans) and `extra_fields: dict[str, str]` (U5 recommendation).
- **Inputs** (`models/inputs.py`): one `_OdooBaseInput` per tool (`CreateTicketInput`,
  `SearchTicketsInput`, `MoveTicketStageInput`, `AssignTicketInput`,
  `AddTicketCommentInput`, `CreateSlaPolicyInput`, `MergeTicketsInput`, …).
- **Envelopes** (`models/envelopes.py`): `TicketResult`, `TicketListResult`,
  `TicketTransitionResult`, `TicketCommentResult`, `TicketHistoryResult`,
  `SlaPolicyResult`, `SlaStatusResult`, `HelpdeskReferenceResult`, `TicketStatsResult`.
- **Config** (resolved U4): `ODOO_HELPDESK_URL`, `ODOO_HELPDESK_USER`,
  `ODOO_HELPDESK_APIKEY` (fallback `ODOO_HELPDESK_PASSWORD`), `ODOO_HELPDESK_DATABASE`
  (optional, empty allowed for JSON-2) in `parrot.conf`, used as `OdooHelpdeskToolkit`
  constructor defaults.
- **Tests**: `packages/ai-parrot/tests/test_odoo_helpdesk_toolkit.py` (AsyncMock transport,
  exact `execute_kw` tuples, envelope classes) + a live smoke script (opt-in, env-gated).

### What Changes

- **`packages/ai-parrot-tools/src/parrot_tools/odoo/models/__init__.py`**::`__all__` —
  re-export helpdesk models. *Evidence*: F004
- **`packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py`**::`__all__` — export
  `OdooHelpdeskToolkit`. *Evidence*: F004
- **`packages/ai-parrot/src/parrot/conf.py`** — new `ODOO_HELPDESK_*` keys. *Evidence*: F008, F002
- **`packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`** — no change required;
  optional `_DEFAULT_KNOWN_MODELS` override on the subclass instead of editing the base
  (avoids the FEAT-614 overlap). *Evidence*: F002, F006, F007

### What's Untouched (Non-Goals)

- `parrot/interfaces/odoointerface.py`, `parrot/clients/base.py`.
- XML-RPC / JSON-RPC transports and `Json2Transport._build_body` beyond FEAT-614.
- Existing generic CRUD / partner / sales / invoice / shell tools (inherited as-is).
- Any Odoo-side change (Softhealer or `troc_helpdesk` modules stay untouched).
- The dynamic-form / NavAPI submission pipeline (read-only linkage only).
- Portal/website ticket creation paths (`ticket_from_portal/website`) — the toolkit creates
  backend tickets only.

### Patterns to Follow

- Subclass `OdooToolkit`; tools auto-register; all I/O via `_execute`. *Evidence*: F007, F002
- Action-then-read-back (`action_*` with `[[id]]` → `_read_one` → entity). *Evidence*: F003, F017
- Per-model default field constants + `select_smart_fields` fallback. *Evidence*: F003, F011
- `@requires_permission("odoo.write")` on every mutating tool; optional HITL
  (`confirming_tools`) for destructive transitions (cancel, merge, mass update). *Evidence*: F003, F007
- Zammad tool naming (`create_ticket`, `get_ticket`, `list_tickets`, `update_ticket`,
  `close_ticket`, `search_tickets`). *Evidence*: F008

### Integration Risks

- **Unverified `action_*` side effects** (guard flags are False on every stage of this
  tenant): mitigated by the staging verification the user authorised (U3); fallback is a
  direct `stage_id` write with explicit `close_date/close_by`. *Evidence*: F016, F017
- **File overlap with FEAT-614**: new modules only; base the worktree after FEAT-614 merges.
  *Evidence*: F006
- **Stats over JSON-2** break until FEAT-614: declare a dependency. *Evidence*: F021
- **`state` naming trap** for the LLM: expose as `replied_status`. *Evidence*: F015
- **SLA logic unobservable** (0 policies): unit-test the wire shape; live-validate after
  creating one policy on staging. *Evidence*: F018
- **Tenant-specific ids/reference data** leaking into code: resolve by name at runtime.
  *Evidence*: F016, F019

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Helpdesk = Softhealer `sh_all_in_one_helpdesk` 19.0.0.0.1 + TROC `troc_helpdesk` 19.0.1.32.0 + two dynamic-form bridges | F013 | high | read from `ir.module.module` live |
| C2 | Odoo 19.0-20260324 over JSON-2, API key as bearer, empty database header accepted | F012, F005 | high | live `context_get` + `server_info` |
| C3 | Extension point is a subclass with reflection-registered tools and `_execute` I/O | F002, F003, F007 | high | code read + FEAT-216 precedent |
| C4 | Lifecycle is `stage_id` over 5 linear stages; `state` is reply direction | F015, F016 | high | fields_get + stage rows + samples |
| C5 | Transition methods are `action_approve/reply/done/closed/cancel/open`, `action_take_ticket`, `action_open_reassign`, wizards | F017 | high | parsed from installed `ir.ui.view.arch_db` |
| C6 | Calling those `action_*` over JSON-2 with `[[id]]` yields the intended stage change | F003, F005, F016 | medium | mapping verified; effects unverified, guard flags False |
| C7 | SLA policies are `sh.helpdesk.sla`; per-ticket status is `sh.helpdesk.sla.status` | F018 | high | fields_get on both |
| C8 | `create` on `sh.helpdesk.sla` is enough to "define an SLA"; attachment to tickets is automatic | F018 | low | 0 policies on staging |
| C9 | Helpdesk models go into the entities/inputs/envelopes split; fixture is `_fake_transport` | F004, F009 | high | direct reads |
| C10 | FEAT-614 must land first for stats tools and overlaps the same files | F006, F021 | high | 422 reproduced live |
| C11 | `ODOO_HELPDESK_*` keys are unused by the framework today | F008, F002 | high | grep across packages |
| C12 | TROC extra fields + dynamic-form link are the tenant's main payload → dict projection on the entity | F019, F015 | medium | 3 sampled tickets |
| C13 | The `odoo_hd` agent using this instance lives outside this repo | F008, F006 | medium | absence in grep; ledger attribution |

Distribution: **9** high, **3** medium, **1** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Packaging: subclass, mixin, or in-place methods?** — *Resolved*: **subclass
  `OdooHelpdeskToolkit(OdooToolkit)` in `parrot_tools/odoo/helpdesk.py`** (FEAT-216 precedent,
  isolated files, no FEAT-614 overlap). *Resolves*: C3
- [x] **U2 — Tool groups in v1?** — *Resolved*: **all**: tickets read/write/transitions/comments
  + assignment (take/reassign/multi-assign) + SLA policy CRUD and per-ticket status +
  reference-data lookups + stats (after FEAT-614) + merge/mass-update wizards + timesheet
  start/stop. *Resolves*: C5, C7
- [x] **U3 — Transition semantics and staging verification?** — *Resolved*: **call
  Softhealer `action_*` with `[[id]]`; the spec phase may create and mutate one throwaway
  ticket on staging to verify effects** (stage_id write is the fallback if an action is inert).
  *Resolves*: C6, C8 (partially — SLA still needs a policy)
- [x] **U4 — Configuration contract?** — *Resolved*: **new `ODOO_HELPDESK_*` conf keys**
  (URL/USER/APIKEY, DATABASE optional and empty-allowed for JSON-2) as toolkit defaults.
  *Resolves*: C11, C2

### Unresolved (defer to spec / implementation)

- [ ] **U5 — TROC-specific payload in v1?** Expose `extra_field_ids` as `dict[str, str]` and the
  `dynamic_form_submission_id` link on `HelpdeskTicket`, or keep v1 vendor-generic? —
  *Owner*: Jesus Lara. *Recommendation*: include both **read-only** in v1 (cheap, and it is
  where the kiosk data lives). *Blocks*: C12
- [ ] **Tool prefix**: inherit `odoo` (tools appear as `odoo_create_ticket`) or set
  `tool_prefix = "odoo_hd"` / `"helpdesk"` to keep helpdesk tools distinguishable when both
  toolkits are loaded? — *Owner*: spec. *Recommendation*: inherit `odoo`, unless the
  `odoo_hd` agent loads both toolkits.
- [ ] **HITL gating**: which transitions join `confirming_tools` (cancel, merge, mass update)?
  — *Owner*: spec.
- [ ] **Softhealer method signatures**: do `action_cancel` / `action_done` open wizards or need
  `cancel_reason` set beforehand? — answered by the staging verification authorised in U3.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-616`** — *Rationale*: localization is high-confidence (C1–C5, C7, C9–C11),
the subclass-vs-mixin fork is resolved with an in-repo precedent, and the remaining unknowns
are bounded product decisions the spec can pin. The spec must (a) declare a dependency on
FEAT-614, (b) include the staging verification task for `action_*` semantics and one SLA
policy. The FEAT id is already reserved (`FEAT-616`) — `/sdd-spec` must not reserve another.

### Alternatives

- **`/sdd-brainstorm FEAT-616`** — only if the mixin route is reconsidered (e.g. to share
  helpdesk tools with a future fieldservice toolkit).
- **`/sdd-task FEAT-616`** — not suitable: multi-module, ~30 tools, new models and conf keys.
- **Manual review** — the live audit under `sdd/state/FEAT-616/findings/live/` if the tenant
  changes (module versions, stages) before the spec is written.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-616/state.json` |
| Source (raw) | `sdd/state/FEAT-616/source.md` |
| Research plan | `sdd/state/FEAT-616/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-616/findings/F001-*.md` … `F021-*.md` |
| Live evidence (sanitized JSON) | `sdd/state/FEAT-616/findings/live/*.json` |
| Synthesis (JSON) | `sdd/state/FEAT-616/synthesis.json` |
| Synthesis reasoning | not persisted |

**Budget consumed** (profile `default`):
- Files read: 17 / 40
- Grep calls: 8 / 25
- Git calls: 2 / 10
- Live RPC calls (outside the profile): ≈45, all read-only
- Wall time: ≈1500s / 300s — exceeded because live-instance discovery is not part of the
  budget profile; every planned query ran, so **truncated: no**
- Mode determination: `auto` → `enrichment` (additive verbs: "ampliar", "incorporar", "extender")
- Plan gate: executed autonomously; review gate + Q&A held with the user (4/5 unknowns answered)

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (with Claude Fable 5.1) |
