---
type: Wiki Overview
title: FEAT-216 — OdooFieldServiceToolkit
id: doc:sdd-proposals-odoo-fieldservice-toolkit-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The original request, preserved verbatim. Full source at
---

---
id: FEAT-216
title: OdooFieldServiceToolkit — domain @tools over OdooToolkit for OCA fieldservice route management
slug: odoo-fieldservice-toolkit
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-02
  summary_oneline: OdooFieldServiceToolkit — 8 @tools over OdooToolkit for OCA fieldservice + fieldservice_stock route management
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-216/
created: 2026-06-02
updated: 2026-06-02
---

# FEAT-216 — OdooFieldServiceToolkit

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-216/`](../state/FEAT-216/)

---

## 0. Origin

The original request, preserved verbatim. Full source at
`sdd/state/FEAT-216/source.md`.

> ## 5.a OdooFieldServiceToolkit
>
> Custom `@tool`s over the native Odoo toolkit, operating on the OCA
> `fieldservice` + `fieldservice_stock` stack. Odoo is the system of record.
>
> | Tool | Signature | Does | HITL | Source |
> |------|-----------|------|------|--------|
> | `get_today_fsos` | `(rep_id) -> list` | The rep's `fsm.order`s for today, ordered by Navigator sequence | none | Odoo |
> | `get_loading_summary` | `(rep_id, date) -> list` | Consolidated pick: product → total qty across today's outbound pickings | none | Odoo |
> | `get_kiosk` | `(location_id) -> dict` | `fsm.location` details: name, partner address, coords, planogram ref | none | Odoo |
> | `create_return_draft` | `(order_id, lines, reason, photo?) -> picking` | Draft return picking for product coming back | rep confirm | Odoo |
> | `validate_loading_pick` | `(rep_id, pin) -> result` | Validate the day's loading pick (start of route) | manager PIN | Odoo |
> | `validate_returns` | `(rep_id, pin) -> result` | Validate all draft return pickings (end of day) | manager PIN | Odoo |
> | `get_return_summary` | `(rep_id, date) -> list` | EOD: product → qty to return to warehouse (from draft return pickings) | none | Odoo |
> | `complete_fso` | `(order_id) -> stage` | Advance `fsm.order` stage when a kiosk is finished | rep confirm | Odoo |

**Initial signals** (extracted, not interpreted):
- Verbs: "extending", "custom `@tool`s over the native Odoo toolkit" → enrichment of existing toolkit.
- Named entities: `OdooToolkit`, `fsm.order`, `fsm.location`, OCA `fieldservice` / `fieldservice_stock`, outbound/return pickings, planogram.
- Components / labels: field-service route execution; kiosk/vending rep workflow.
- Acceptance criteria provided: implicit (8 tools with signatures + HITL levels).

---

## 1. Synthesis Summary

The request adds an `OdooFieldServiceToolkit` exposing 8 domain `@tool`s for the
OCA fieldservice route-execution workflow (today's orders, loading pick, kiosk
details, returns, EOD validation, stage completion). After research, this is a
thin **enrichment** layer: the existing `OdooToolkit`
(`packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py:159`) already
provides the base class, lazy transport/auth, the `_execute` RPC chokepoint,
the `@tool_schema`/`@requires_permission` decorators, and a three-module Pydantic
model layout — and `AbstractToolkit.get_tools()` auto-registers any new `async`
method as a tool. The only net-new work is FSM Pydantic models
(`fsm.order`/`fsm.location`, currently absent), the 8 tool methods, and wiring
the HITL gates onto the mature `HumanInteractionManager` stack. The recommended
path is a straightforward subclass; remaining unknowns are bounded domain
field-name mappings deferred to the spec.

---

## 2. Codebase Findings

> All entries grounded in `sdd/state/FEAT-216/findings/`. No fabricated paths.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | `OdooToolkit` | 159-221 | base class to subclass; `tool_prefix="odoo"`, lazy auth, `__init__` | F001 |
| 2 | `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | `OdooToolkit._execute` | 261-272 | RPC chokepoint for fsm/stock button methods + stage advance | F001 |
| 3 | `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | `attach_document` | 906 | binary/photo attachment helper (reused by `create_return_draft`) | F001 |
| 4 | `packages/ai-parrot/src/parrot/tools/toolkit.py` | `AbstractToolkit.get_tools` | 337-422 | reflection-based discovery — subclass methods auto-register | F002 |
| 5 | `packages/ai-parrot-tools/src/parrot_tools/odoo/models/entities.py` | `_OdooEntity`, `StockPicking` | 22, 227 | entity pattern; add `FsmOrder`/`FsmLocation` here | F004 |
| 6 | `packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py` | `_OdooBaseInput` | 111 | input-schema pattern for `@tool_schema` | F004 |
| 7 | `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | `_DEFAULT_KNOWN_MODELS` | 136-148 | known-model registry — `fsm.*` must be added | F004 |
| 8 | `packages/ai-parrot/src/parrot/tools/decorators.py` | `requires_permission`, `tool_schema` | 9, 37 | per-tool permission + schema decoration | F001, F003 |
| 9 | `packages/ai-parrot/src/parrot/human/manager.py` | `HumanInteractionManager.request_human_input` | 51 | rep-confirm HITL substrate | F003 |
| 10 | `packages/ai-parrot/src/parrot/human/models.py` | `InteractionType.APPROVAL` | 60, 66 | boolean approval decision (Telegram ✅/❌) | F003 |
| 11 | `packages/ai-parrot/src/parrot/tools/manager.py` | `ToolManager.execute_tool` | 1126 | central gating point for any approval/grant guard | F003 |
| 12 | `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` | `SqlToolkit(DatabaseToolkit)` | — | precedent: domain toolkit subclassing a base toolkit | F002 |

### 2.2 Constraints Discovered

- **Async + `_execute` only.** All tools must be `async` and route Odoo RPC
  through `OdooToolkit._execute` (no direct SDK, no blocking I/O). Button methods
  (`button_validate`) and stage advances follow the same
  `_execute("<model>", "<method>", [[ids]])` form as `confirm_sale_order`.
  *Evidence*: F001
- **Reflection-based tool registration.** `get_tools()` turns every public
  `async def` into a tool and applies `tool_prefix` idempotently. New FSM methods
  register automatically — but so do all inherited ones (see §3 tool surface).
  *Evidence*: F002
- **FSM models are absent.** Neither `fsm.order` nor `fsm.location` has an entity
  class, and they are not in `_DEFAULT_KNOWN_MODELS`. They must be added for typed
  results and for `list_models`/permission visibility.
  *Evidence*: F004
- **Returns reuse `stock.picking`.** The `StockPicking` entity (entities.py:227)
  and `stock.picking` known-model already exist; `create_return_draft` /
  `validate_returns` build on them, and photos reuse `attach_document`.
  *Evidence*: F001, F004
- **No numeric-PIN primitive.** The repo's HITL is approval/grant based; a true
  numeric PIN check against Odoo is net-new (see §3 + §5 U1 resolution).
  *Evidence*: F003

### 2.3 Recent History (Relevant)

The Odoo toolkit + interface stack landed via `feat-054-odoo-interface` and was
extended by `feat-147-evaluate-odoo-mcp-toolkit` and a Pydantic-models branch
(`claude/odoo-toolkit-pydantic-*`). Tasks TASK-438..442 and TASK-1013/1022
(under `sdd/tasks/completed/`) built the interface, CRUD methods, and Pydantic
models. No fieldservice-specific work exists yet — this feature is greenfield on
top of a stable toolkit. *Evidence*: F001, F004

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`OdooFieldServiceToolkit(OdooToolkit)`** — new toolkit class exposing the 8
  FSM `@tool`s. Lives alongside the Odoo toolkit (e.g.
  `packages/ai-parrot-tools/src/parrot_tools/odoo/fieldservice.py`).
- **FSM Pydantic models** — `FsmOrder`, `FsmLocation` (entities), plus per-tool
  inputs (`GetTodayFsosInput`, `GetKioskInput`, `CreateReturnDraftInput`,
  `ValidateLoadingPickInput`, `ValidateReturnsInput`, `GetLoadingSummaryInput`,
  `GetReturnSummaryInput`, `CompleteFsoInput`) and result envelopes
  (`LoadingSummaryLine`, `ReturnSummaryLine`, `FsmStageResult`, ...).
- **`fsm.order` / `fsm.location` registration** in `_DEFAULT_KNOWN_MODELS`.
- **Manager-PIN verification path** — verify the `pin` argument against Odoo
  `res.users` credentials before validating pickings (see §5 U1).

### What Changes

- **`packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`::`_DEFAULT_KNOWN_MODELS`** —
  append `fsm.order` / `fsm.location`. *Evidence*: F004
- **`packages/ai-parrot-tools/src/parrot_tools/odoo/models/*`** — add FSM
  entities/inputs/envelopes following the existing three-module split.
  *Evidence*: F004
- **`packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py`** — export the
  new toolkit. *Evidence*: F001

### What's Untouched (Non-Goals)

- The transport layer (json2/jsonrpc/xmlrpc) and `_ensure_transport` auth flow.
- The generic CRUD tools and partner/sales/invoice helpers (inherited as-is).
- The HITL channel rendering (Telegram ✅/❌) — reused, not modified, for
  `rep confirm`.
- Any Odoo-side OCA module installation (assumed present on the instance).

### Patterns to Follow

- Tool method shape: `@requires_permission(...)` + `@tool_schema(<Input>)` +
  `async def`, returning a typed envelope; RPC via `self._execute(...)`.
  *Evidence*: F001
- Domain subclassing of a base toolkit, as `SqlToolkit(DatabaseToolkit)` does.
  *Evidence*: F002
- `rep confirm` → `HumanInteractionManager.request_human_input` with
  `InteractionType.APPROVAL`. *Evidence*: F003

### Integration Risks

- **Wide tool surface.** Per the chosen design (subclass, expose all), the field
  rep's agent receives the 8 FSM tools **plus** all ~30 inherited generic CRUD
  tools (search/create/update/delete on any model). *Mitigation*: rely on
  `@requires_permission` gates + Odoo ACLs; revisit `get_tools_filtered` if the
  surface proves too broad. *Evidence*: F002
- **PIN handling.** A numeric PIN verified against Odoo is a secret crossing the
  agent boundary; it must never be logged and should be validated server-side
  only. *Evidence*: F003
- **Domain field drift.** `fsm.order` ordering field and `fsm.location` planogram
  field are instance-specific (OCA + Navigator customizations); wrong field names
  fail silently as empty results. *Evidence*: F004

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `OdooToolkit` (toolkit.py:159) is the correct base; `_execute` is the RPC path | F001 | high | direct read of class, `__init__`, `_execute`, and `confirm_sale_order` usage |
| C2 | Subclass `async def` methods auto-register as tools via reflection | F002 | high | read of `get_tools()` discovery loop (toolkit.py:413) |
| C3 | Domain toolkit subclassing is an established repo pattern | F002 | high | `SqlToolkit(DatabaseToolkit)` and siblings exist |
| C4 | `fsm.order`/`fsm.location` entities + registration must be added | F004 | high | absent from entities.py and `_DEFAULT_KNOWN_MODELS` |
| C5 | `rep confirm` is covered by existing APPROVAL HITL | F003 | high | `InteractionType.APPROVAL` + Telegram channel already built |
| C6 | Returns reuse `stock.picking` + `attach_document` | F001, F004 | high | `StockPicking` entity + known model + binary helper present |
| C7 | Manager PIN must be a net-new Odoo-credential check | F003 | medium | no PIN primitive in repo; design choice confirmed with user |
| C8 | `rep_id`→`fsm.order` link and "Navigator sequence" field names | — | low | instance/domain-specific; not in codebase |

Distribution: **6** high, **1** medium, **1** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **How should the "manager PIN" gate be implemented?** — *Resolved*: a
  **real numeric PIN verified against Odoo `res.users`** (the `pin` arg is a true
  secret checked via Odoo credentials, e.g. `check_credentials` / a `res.users`
  PIN field). This adds a new credential-check path used by
  `validate_loading_pick` / `validate_returns`. *Resolves*: C7
- [x] **Subclass vs. compose, and tool surface?** — *Resolved*: **subclass
  `OdooToolkit` and expose all** — the rep's agent gets the 8 FSM tools plus all
  inherited generic CRUD tools (least code, widest surface). *Resolves*: C2, the
  §3 "Integration Risks → wide tool surface" item

### Unresolved (defer to spec / implementation)

- [ ] **Which `fsm.order` field encodes the "Navigator sequence" ordering, and
  how does `rep_id` map to `fsm.order` (`person_id`/`user_id`) and to the day's
  outbound pickings?** — *Owner*: tbd · *Blocks*: C8 (`get_today_fsos`,
  `get_loading_summary`) · *Plausible*: a) a custom `sequence`/`x_navigator_seq`
  field · b) `person_id` on `fsm.order` joined to `hr.employee`/`res.users`.
- [ ] **Which `fsm.location` field holds the "planogram ref" returned by
  `get_kiosk`?** — *Owner*: tbd · *Blocks*: C8 (`get_kiosk`) · *Plausible*:
  a) a custom `x_planogram_id`/`planogram_ref` field · b) a related attachment
  or `ir.attachment` link.

> These two are instance-specific Odoo field mappings; pin them during
> `/sdd-spec` (Codebase Contract) or against the live instance.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-216`** — *Rationale*: localization is high-confidence (C1–C6),
the implementation path is well-precedented (C3), and the two design forks are
resolved. The spec can pin the remaining domain field names in its Codebase
Contract / Open Questions.

### Alternatives

- **`/sdd-brainstorm FEAT-216`** — only if you want to revisit the tool-surface
  decision (filtered vs. full) or the PIN mechanism as architectural options.
- **`/sdd-task FEAT-216`** — not recommended; this is multi-file (models + tools
  + registration + PIN path) and warrants a spec first.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-216/state.json` |
| Source (raw) | `sdd/state/FEAT-216/source.md` |
| Research plan | `sdd/state/FEAT-216/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-216/findings/F001..F004-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-216/synthesis.json` |

**Budget consumed**:
- Files read: 12 / 40
- Grep calls: 9 / 25
- Git calls: 1 / 10
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` ("extending …
over the native Odoo toolkit").

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | jesuslarag (via Claude) |
