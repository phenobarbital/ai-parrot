<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

Original request:
> En el Odoo expuesto en staging environment: https://pokemon.helpdesk.staging.trocdigital.io/
> con credenciales acequibles via ODOO_HELPDESK_URL, ODOO_HELPDESK_USER, ODOO_HELPDESK_PASSWORD
> y ODOO_HELPDESK_APIKEY hay un sistema helpdesk que debemos descubrir cual es (al parecer es un
> modulo custom de "softhealer", un partner hindú), necesitamos hacer un research sobre este
> Odoo v.19 para ampliar el OdooToolkit ya sea incorporando métodos o extendiendo con un mixin
> de OdooHelpdesk para incorporar métodos para operar con el helpdesk system (crear tickets,
> transicionar tickets, gestionar las incidencias, definir SLAs, etc), esto incluye model inputs
> para los métodos de entrada y gestión de las salidas (structured outputs)

### Constraints and goals
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

Decisions already taken by the owner:
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

Live-instance facts:
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

### Recommended option / probable scope
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

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py
packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py
packages/ai-parrot-tools/src/parrot_tools/odoo/models/envelopes.py
packages/ai-parrot-tools/src/parrot_tools/odoo/models/entities.py
packages/ai-parrot-tools/src/parrot_tools/odoo/models/__init__.py
packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py
packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py
packages/ai-parrot/src/parrot/tools/decorators.py
packages/ai-parrot-tools/src/parrot_tools/odoo/smart_fields.py
packages/ai-parrot/tests/test_odoo_toolkit.py
packages/ai-parrot-tools/src/parrot_tools/zammad.py
sdd/specs/odoo-fieldservice-toolkit.spec.md
sdd/specs/odoo-json2-domain-first-methods.spec.md

### Questions still open in the exploration document
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

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
