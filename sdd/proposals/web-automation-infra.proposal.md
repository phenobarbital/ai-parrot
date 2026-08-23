---
id: FEAT-453
title: Hooba browser-automation agent — DSL stub closure, domain toolkit, conversational surface and gestoría wiki brain
slug: web-automation-infra
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-08-23
  summary_oneline: "Browser-automation toolkit (DSL) + autonomous agent over Hooba (no-API Spanish accounting SaaS), reachable via Telegram/WhatsApp, with wiki+Obsidian memory"
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-453/
created: 2026-08-23
updated: 2026-08-23
revision: 2 — FEAT-452 merged (PR #1209) after Q&A; F009/C11 revised, C15 added
---

# FEAT-453 — Hooba browser-automation agent

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-453/`](../state/FEAT-453/)

> **Revision 2 — 2026-08-23T10:02Z.** FEAT-452 `audio-notes-obsidian` merged to
> `dev` (PR #1209) minutes after the Q&A closed. Finding F009 is revised, claim
> C11 is restated as a merged dependency, new finding F011 and claim C15 record
> the concrete reuse contract, and one integration risk is retired. The premise
> behind the U4 answer ("wiki layer last, to avoid a parallel design") has
> dissolved; the single-feature decision stands. Overall confidence is unchanged
> at `medium` — C13 and C14 are what bound it.

---

## 0. Origin

The original request, preserved verbatim. Full source at
`sdd/state/FEAT-453/source.md`.

> Por legislación española debo utilizar un software de gestión en la nube
> llamado Hooba (`https://app.hooba.com/`) el problema es que Hooba no cuenta
> con API de ningún tipo, así que la automatización de cosas (crar clientes,
> registrar gastos, CRM, emisión de facturas) depende de interacción en
> browser, ya contamos con un DSL para WebscrapingToolkit, dos drivers selenium
> + playwright e integración con el MCP de google chrome (chrome dev tools),
> asi que se me ocurre 1.- con el mismo DSL crear un toolkit de browser
> automation (lenguaje json para definir directivas de accion como "ingresar
> credenciales, go to dashboard, click en CRM ... ") 2.- crear entonces un
> agente que con acceso a: BrowserAutomationToolkit + Chrome Dev Tools MCP +
> WikiToolkit (crear un cerebro autonomo de trabajo) + ObsidianToolkit (notas
> de trabajo) + TelegramWrapper (usar ai-parrot-integrations para exponerlo via
> telegram y poder interactuar con él y Whatsapp, le asignaré un número de
> teléfono) me permitirá hablar con un agente via telegram/whatsapp y pedirle
> que gestione operaciones como montar facturas draft, crear registros de
> clientes, crear registros de gastos, coordinar recordatorios de fechas clave
> (presentación de impuestos, etc, aquí imagino que debería integrarlo a mi
> Google Calendar), permitir subir el excel de gastos de la cuenta bancaria
> para que use un flow (un agente puede invocar un AgentsFlow como si fuera un
> tool) para procesar y regisrar iterativamente los gastos y todo ello
> generando un LLM wiki local con espejo en el Obsidian que me permite saber
> como va la gestión de mi autonomía.

**Initial signals** (extracted, not interpreted):

- **Verbs** (polarity: positive / additive): crear, automatizar, registrar,
  emitir, gestionar, coordinar, procesar, espejar. The single negation targets
  an *external* system, not our code: "Hooba no cuenta con API de ningún tipo".
- **Named entities**: Hooba (`app.hooba.com`), WebscrapingToolkit,
  BrowserAutomationToolkit, Chrome DevTools MCP, WikiToolkit, ObsidianToolkit,
  TelegramWrapper, `ai-parrot-integrations`, WhatsApp, Google Calendar,
  AgentsFlow, Selenium, Playwright.
- **Business operations**: crear clientes, registrar gastos, CRM, emisión de
  facturas draft, recordatorios de impuestos, ingesta de Excel bancario.
- **Acceptance criteria provided**: no (0).

---

## 1. Synthesis Summary

The request is to automate a Spanish legally-mandated, API-less accounting SaaS
(Hooba) through the browser, and to drive that automation conversationally from
Telegram/WhatsApp with a durable wiki + Obsidian memory. Research shows the
proposal is substantially better-supported than the source assumes: the JSON
action DSL already exists as 27 typed `BrowserAction` Pydantic models in
`packages/ai-parrot-tools/src/parrot_tools/scraping/models.py` — including
`Authenticate`, `AwaitHuman`, `UploadFile` and `WaitForDownload`; FEAT-222
already merged parameterized `TemplatePlan.bind()`, a session-affine
`ScrapingFlow` DAG and a resumable `FlowExecutor`; both drivers and a Chrome
DevTools MCP `WebAgent` are live; and the wiki tools, `ObsidianToolkit`,
Telegram/WhatsApp wrappers, `CredentialBroker` with signed audit ledger,
`ExcelLoader` and an APScheduler-based scheduler all exist. The genuinely new
work is therefore much narrower than "build a BrowserAutomationToolkit": close
the eight actions that `executor.py::_dispatch_step` silently stubs with
`return True`, validate plan steps at rest, build a Hooba-specific domain
toolkit over `TemplatePlan`/`ScrapingFlow`, add Google Calendar event tools, and
stand up a gestoría wiki plane sequenced after FEAT-452.

---

## 2. Codebase Findings

> All entries are grounded in the digests at `sdd/state/FEAT-453/findings/`.
> Each cites the finding ID(s) that justify it. **No fabricated paths or symbols.**

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py` | `BrowserAction` + 27 subclasses | 14-757 | **the JSON action DSL the source proposes to create — already typed and complete** | F001 |
| 2 | `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` | `_dispatch_step` | 251-311 | **modern dispatch path; silently stubs 8 actions with `return True`** | F002 |
| 3 | `packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py` | `_execute_step`, `_await_human` | 689-760, 2086-2172 | legacy tool holding the only real implementations of the stubbed actions | F002 |
| 4 | `packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py` | `ScrapingPlan` | 59-110 | plan value object; `steps` stored as untyped `List[Dict[str, Any]]` | F001 |
| 5 | `packages/ai-parrot-tools/src/parrot_tools/scraping/template_plan.py` | `TemplatePlan.bind`, `ParamSpec` | 72-205 | parameterized plan binding — "same flow, different invoice" primitive | F003 |
| 6 | `packages/ai-parrot-tools/src/parrot_tools/scraping/flow_models.py` | `ScrapingFlow`, `FlowNode`, `FlowResult` | 19-147 | DAG model with session affinity for login-then-operate flows | F003 |
| 7 | `packages/ai-parrot-tools/src/parrot_tools/scraping/flow_executor.py` | `FlowExecutor` | — | topological execution with per-node checkpoints (resumability) | F003 |
| 8 | `packages/ai-parrot-tools/src/parrot_tools/scraping/session_manager.py` | `SessionManager` | — | BrowserContext lifecycle, shared auth state across stages | F003 |
| 9 | `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py` | `AbstractDriver` | 37-337 | 27-method driver surface (playwright + selenium); includes `save_pdf` | F004 |
| 10 | `packages/ai-parrot/src/parrot/bots/chrome.py` | `WebAgent`, `ChromeConfig` | 15-334 | existing agent wired to `chrome-devtools-mcp`; second automation channel | F004 |
| 11 | `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` | `ExecutionPlanToolkit.plan_execute` | 62-500 | the real "agent invokes a flow as a tool" mechanism, LLM-free during execution | F005 |
| 12 | `packages/ai-parrot/src/parrot/tools/agent.py` | `AgentTool` | 52-75 | agent-as-tool wrapper; requires `AbstractBot`, so cannot wrap `AgentsFlow` | F005 |
| 13 | `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | `create_wiki_tools` + 7 wiki tools | 155-541 | the WikiToolkit the source asks for — already agent-callable | F006 |
| 14 | `packages/ai-parrot/src/parrot/tools/obsidian.py` | `ObsidianToolkit` | 78-702 | 20-tool vault CRUD / search / link-graph toolkit | F006 |
| 15 | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | `handle_document`, `_send_attachments` | 67, 300, 1461-1552, 3075-3120 | Excel upload ingress and document egress, already wired to `agent.ask(attachments=…)` | F007 |
| 16 | `packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/bridge_wrapper.py` | `WhatsAppBridgeWrapper` | 1-16 | **selected transport** — personal number via Go whatsmeow bridge | F007 |
| 17 | `packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/wrapper.py` | `WhatsAppAgentWrapper` | 37-359 | Meta Cloud API / pywa transport (business number) — not selected | F007 |
| 18 | `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | `IntegrationBotManager` | 38-272 | YAML-driven multi-channel bot startup | F007 |
| 19 | `packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py` | `BaseSchedulerCallback` | 16-168 | extension point for recurring tax-deadline reminders | F008 |
| 20 | `packages/ai-parrot/src/parrot/interfaces/google.py` | `GoogleClient.get_calendar_client` | 57-61, 688-762 | calendar OAuth scopes + service config only — **no event tools exist** | F008 |
| 21 | `packages/ai-parrot-tools/src/parrot_tools/o365/events.py` | Office365 event tools | — | the only working calendar-event tooling in the repo today | F008 |
| 22 | `packages/ai-parrot-loaders/src/parrot_loaders/excel.py` | `ExcelLoader` | — | bank-statement ingestion, per-sheet and per-row document modes | F008 |
| 23 | `packages/ai-parrot/src/parrot/auth/broker.py` | `CredentialBroker`, `_VaultStaticKeyResolver` | 51-326 | where Hooba credentials should come from | F010 |
| 24 | `packages/ai-parrot/src/parrot/security/audit_ledger.py` | audit ledger | — | signed append-only record of credential use — evidence trail for automated filings | F010 |
| 25 | `sdd/tasks/index/audio-notes-obsidian.json` | FEAT-452 task index | 1-40 | **merged** feature (PR #1209, all 6 tasks done) delivering the domain-plane + vault-mirror + Telegram-scoping pattern | F009 |
| 26 | `sdd/tasks/completed/TASK-2379-notes-wiki-plane.md` | Module 2 — separate wiki plane | 14-50 | the reuse recipe: a second plane needs its own `LLMWikiToolkit` instance, not a parameter | F011 |
| 27 | `sdd/tasks/completed/TASK-2382-register-notes-wiki-namespace.md` | Module 6 — namespace registration | 14-52 | `wikitoolkit ns add` (kind `store`/`sqlite`) is what makes a plane queryable; operator step, not agent code | F011 |
| 28 | `sdd/specs/wiki-namespaces.spec.md` | FEAT-450 wiki namespaces | — | the merged federation layer TASK-2382 consumed | F009 |

### 2.2 Constraints Discovered

- **Eight DSL actions are stubbed, not missing.** `executor.py:298-311` returns
  `True` for `authenticate`, `upload_file`, `wait_for_download`, `get_cookies`,
  `set_cookies`, `await_human`, `await_keypress`, `await_browser_event`.
  *Implication*: closing this is a prerequisite task, not an enhancement. A
  Hooba plan whose first step is `authenticate` proceeds believing it is logged
  in, running every subsequent step against a login page. Silent success against
  an accounting system is worse than failure. *Evidence*: F002

- **FEAT-222 already fixed this defect class once, partially.** Its spec §1 gap 4
  identified exactly this stub pattern for `Loop`/`Conditional` and extracted
  them into `advanced_actions.py`. The remaining eight were left behind.
  *Implication*: `advanced_actions.py` is the established extraction pattern —
  do not invent a new one. *Evidence*: F002, F003

- **Plan steps are untyped at rest.** `ScrapingPlan.steps` is
  `List[Dict[str, Any]]`; typed `BrowserAction` parsing happens only at
  execution time in the legacy tool. *Implication*: malformed plans fail
  mid-transaction. For financial writes, validate the whole plan against the
  `BrowserAction` union before opening the browser. *Evidence*: F001

- **`AgentsFlow` is not an `AbstractBot`.** It is `AgentsFlow(PersistenceMixin)`;
  `AgentTool.__init__` requires an `AbstractBot`. *Implication*: the Excel
  expense pipeline must go through `ExecutionPlanToolkit.plan_execute` (bounded,
  LLM-free, `run_id` polling) rather than a hypothetical `AgentsFlow.as_tool()`.
  *Evidence*: F005

- **Scheduling lives in `ai-parrot-server`.** *Implication*: tax-deadline
  reminders imply deploying the server distribution, not just running a bot
  process. That deployment decision is not yet made. *Evidence*: F008

- **Google Calendar has scopes but no tools.** `get_calendar_client` returns a
  config dict nothing consumes. *Implication*: calendar event tooling is
  net-new and self-contained. *Evidence*: F008

- **FEAT-452 has merged — its domain-plane pattern is a dependency to consume,
  not a race.** PR #1209 landed all six tasks on `dev`; `notes` is registered as
  a `store`-kind namespace pointing at `../../.parrot/wikis/notes`. The reuse
  contract is: a **separate `LLMWikiToolkit` instance** (a parameter change
  raises `ValueError` at `wiki/toolkit.py:1205` — its docstring says "Construct a
  separate LLMWikiToolkit for each wiki instance"), an idempotent `create_wiki()`
  bootstrap wired into `configure()`, then a one-off operator
  `wikitoolkit ns add` of kind `store`/`sqlite`. *Implication*: the collision
  risk that motivated sequencing the wiki layer last is gone; and namespace
  registration belongs in the runbook as an acceptance criterion, because
  TASK-2382 explicitly excludes auto-registering from agent code. An unregistered
  plane is *written but unqueryable*. *Evidence*: F009, F011, F006

- **Channel authorization is a financial control here.**
  `WhatsAppAgentWrapper._is_authorized(wa_id)` and `telegram/auth.py` gate who
  can talk to the bot. *Implication*: this agent can spend money and file
  tax-relevant records; the allowlist is a security boundary. *Evidence*: F007

- **Fan-out on a shared authenticated session is known deferred debt.** FEAT-222
  lists it as an explicit non-goal, safe in sequential mode only.
  *Implication*: the expense-import flow must stay sequential over one Hooba
  session. Acceptable for a single autónomo. *Evidence*: F003

### 2.3 Recent History (Relevant)

FEAT-222 landed the composition layer this proposal builds on (newest first):

| Commit | Message | Touched |
|--------|---------|---------|
| `4a7dfa3fe` | fix(scrapingflow): address FEAT-222 code review (C1/C2/H1/H2/H4/H5/M1/M3/M4/M5/L1/L2/L4) | scraping/ |
| `4fe577966` | TASK-1453 — export TemplatePlan/ScrapingFlow/FlowExecutor | `__init__.py` |
| `b34b84e09` | TASK-1452 — FlowExecutor orchestration engine | `flow_executor.py` |
| `b77764e60` | TASK-1451 — SessionManager for BrowserContext lifecycle | `session_manager.py` |
| `3bcfc71f0` | TASK-1450 — PageDriver adapter for Playwright Page | `drivers/page_driver.py` |
| `f3156b5cc` | TASK-1449 — ScrapingFlow/FlowNode/FlowResult DAG models | `flow_models.py` |
| `6e7c5adda` | TASK-1448 — TemplatePlan & ParamSpec models with `bind()` | `template_plan.py` |
| `2bbb96d7b` `33041b740` `4f3377de9` | TASK-1447/1446/1445 — extract advanced actions (Loop/Conditional/template vars) | `advanced_actions.py`, `executor.py`, `tool.py` |

`ai-parrot-integrations` activity over the last 90 days is dominated by
`agentd` and the Claude agent tool bridge — the Telegram/WhatsApp wrappers
themselves are stable, not in flux. *Evidence*: F003, F007

---

## 3. Probable Scope

### What's New

- **`HoobaToolkit`** — an `AbstractToolkit` owning a set of `TemplatePlan`s for
  the recurring operations (login, create client, register expense, draft
  invoice, download invoice PDF), composed into `ScrapingFlow`s and executed
  through `FlowExecutor`.
- **Google Calendar event tools** — `create_event` / `list_events` /
  `update_event` on the existing `GoogleClient` OAuth foundation.
- **A `gestoria` wiki plane + Obsidian folder mirror**, instantiating FEAT-452's
  now-merged recipe: a dedicated `_build_gestoria_wiki_toolkit()` with its own
  storage root, PageIndex plane and `tenant_id`, an idempotent `create_wiki()` in
  `configure()`, and a one-off operator `wikitoolkit ns add --kind store`.
- **A scheduler callback** for the Spanish tax calendar (modelo 303/130/390 and
  similar), driving both the calendar events and Telegram reminders.
- **An `ExecutionPlan`** for iterative bank-Excel expense ingestion, triggered
  as a bounded `plan_execute` tool call with `run_id` progress polling.

### What Changes

- **`scraping/executor.py::_dispatch_step`** — replace the 8-action stub branch
  with real dispatch, extracting the implementations out of `tool.py` following
  the `advanced_actions.py` pattern. *Evidence*: F002
- **`scraping/tool.py`** — delegate `authenticate` / `await_human` /
  `upload_file` / `wait_for_download` / cookie actions to the extracted module,
  eliminating the duplicate implementation. *Evidence*: F002
- **`scraping/plan.py::ScrapingPlan`** — add opt-in validation of `steps`
  against the `BrowserAction` union at load time. *Evidence*: F001
- **`scraping/models.py::Authenticate`** — source credentials through
  `parrot.auth.broker.CredentialBroker` instead of literal values in plan JSON.
  *Evidence*: F001, F010
- **`parrot/interfaces/google.py`** — promote `get_calendar_client` from a
  config dict to a usable client backing the new calendar tools. *Evidence*: F008

### What's Untouched (Non-Goals)

- Building a new browser-automation DSL — 27 typed `BrowserAction` models
  already exist (C1).
- Building a WikiToolkit or ObsidianToolkit — both exist and are complete (C6).
- Building WhatsApp or Telegram transport — both ship (C7).
- Building scheduling machinery — only a new callback is needed (C8).
- Re-implementing the domain wiki plane / vault mirror — FEAT-452 **merged** it;
  FEAT-453 instantiates the recipe for `gestoria` (C11, C15).
- Injecting a `FederatedWikiStore` into `LLMWikiToolkit`, or auto-registering the
  namespace from agent code — both explicit FEAT-452 non-goals (C15).
- Concurrent fan-out over one authenticated Hooba session — FEAT-222 deferred
  debt (C3).
- The Meta Cloud API WhatsApp path (`WhatsAppAgentWrapper`) — the personal-number
  bridge was selected instead (U2).

### Patterns to Follow

- **`advanced_actions.py` extraction** — standalone async functions taking
  `AbstractDriver` + a `dispatch_step_fn` callback, consumed by both
  `executor.py` and `tool.py`. *Evidence*: F002, F003
- **FEAT-207 shared-state toolkit** — one `AbstractToolkit` instance initialized
  with live dependencies, shared across every tool call (as `ExecutionPlanToolkit`
  and the skill toolkits do). *Evidence*: F005, F006
- **FEAT-391 lazy lifecycle hooks** (`_open`/`_close`/`auto_open`) for the
  browser session, as `ObsidianToolkit` does for the vault. *Evidence*: F006
- **`run_id` + `plan_status`/`plan_artifacts` polling** for long operations, so a
  chat turn is not held open during an expense import. *Evidence*: F005, F007
- **FEAT-452 domain-plane recipe** — a dedicated `_build_<x>_wiki_toolkit()`
  near-copy pointed at its own storage root with its own PageIndex plane and
  `tenant_id`, idempotent `create_wiki()` in `configure()`, best-effort failure
  leaving the handle `None`, then operator-side `wikitoolkit ns add`.
  *Evidence*: F011

### Integration Risks

- **Hooba DOM churn breaks every TemplatePlan at once** → `PlanRegistry`
  fingerprinting plus a scheduled smoke `ScrapingFlow` exercising login + one
  read-only navigation, alerting over Telegram *before* a real operation fails.
  *Evidence*: F003, F008
- **Unattended writes to a legally-mandated system produce wrong filings** →
  `await_human` gate (now that it actually executes) on every write with legal
  effect; the signed audit ledger records what was done and with which
  credential. Resolved posture per U5. *Evidence*: F002, F010
- **Hooba adds MFA/CAPTCHA later** → fall back to `ChromeConfig.user_data_dir`
  persistent profile plus `await_human` on session expiry. U1 confirms no MFA
  today, but this is a third-party site that can change. *Evidence*: F004, F010
- **The `gestoria` plane is built but never registered as a namespace**, silently
  accumulating accounting knowledge nobody can query → `wikitoolkit ns add` is an
  operator runbook step *and* an explicit acceptance criterion. This is precisely
  the failure TASK-2382 was written to prevent. *Evidence*: F011
- **Scope is 3-4 deliverables under one FEAT-ID** → accepted as one feature per
  U4, mitigated by task ordering rather than by splitting.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | The JSON browser-action DSL the source proposes to create already exists as 27 typed `BrowserAction` models, including `Authenticate`, `AwaitHuman`, `UploadFile`, `WaitForDownload` | F001 | high | direct read of `models.py` class list |
| C2 | `executor.py::_dispatch_step` silently stubs 8 actions with `return True`, and those 8 are precisely the login/file/HITL/session primitives this feature needs | F002 | high | direct read of the stub branch at lines 298-311 |
| C3 | FEAT-222 merged `TemplatePlan.bind`, a session-affine `ScrapingFlow` DAG, a checkpointing `FlowExecutor` and a `SessionManager` | F003 | high | files on disk plus 10 TASK commits and a code-review remediation commit |
| C4 | Selenium and Playwright implement a 27-method `AbstractDriver`, and `WebAgent` already connects `chrome-devtools-mcp` via `ChromeConfig` | F004 | high | direct read of `abstract.py`, `chrome.py:290-334`, `mcp/integration.py:1105/1476` |
| C5 | An agent triggers a flow via `ExecutionPlanToolkit.plan_execute`; `AgentsFlow` is not an `AbstractBot` so `Agent.as_tool()` cannot wrap it | F005 | high | class signature `AgentsFlow(PersistenceMixin)` vs `AgentTool.__init__(agent: AbstractBot)` |
| C6 | Seven agent-callable wiki tools and a 20-tool `ObsidianToolkit` already exist | F006 | high | direct read of `tools.py` name declarations and `obsidian.py` method list |
| C7 | Telegram and WhatsApp both ship, WhatsApp with two transports, and Telegram already forwards uploaded documents to `agent.ask(attachments=…)` | F007 | high | direct read of `manager.py` wiring, both WhatsApp wrappers, the Telegram attachment path |
| C8 | APScheduler-based scheduling with a `BaseSchedulerCallback` extension point exists, but only in `ai-parrot-server` | F008 | high | file locations plus callback class list |
| C9 | Google Calendar has declared OAuth scopes and a service-config accessor but no event tools; O365 has real calendar tooling | F008 | high | `get_calendar_client` returns a config dict with no consumer, vs `o365/events.py` |
| C10 | A `CredentialBroker` with vault resolvers, toolkit-facing credential abstractions and a KMS-signed invocation ledger already exists | F010 | high | direct read of `auth/broker.py`, `security/vault_utils.py`, `security/audit_ledger.py` |
| C11 | FEAT-452 has **merged** to `dev` (PR #1209, all 6 tasks done), delivering the domain-scoped wiki plane, FEAT-450 namespace registration, folder-scoped vault ingest and `telegram_chat_scope` | F009, F011 | high | index reads `completed_at: 2026-08-23T09:04:39Z`; `wikitoolkit ns list` shows `notes` registered and built |
| C15 | A second wiki plane requires a separate `LLMWikiToolkit` instance plus a one-off operator `wikitoolkit ns add` — `_config_for()` raises `ValueError` if `wiki_name` mismatches, and an unregistered plane is written but unqueryable | F011 | high | stated verbatim in merged TASK-2379/TASK-2382, incl. the `wiki/toolkit.py:1205` ValueError and its docstring |
| C12 | `ScrapingPlan.steps` is untyped at rest, so a malformed plan fails mid-execution rather than at load | F001 | medium | field type directly observed; the mid-execution consequence is inferred, not observed |
| C13 | Net-new work is materially narrower than the source assumes — stub closure, load-time plan validation, a Hooba domain toolkit, calendar tools, a gestoría wiki plane | F001, F002, F003, F006, F007, F008, F009 | medium | each component's existence is high-confidence, but "nothing else is missing" is an inference over the union of findings |
| C14 | Unattended browser automation against Hooba is feasible: the operator confirms `app.hooba.com` has no MFA or CAPTCHA on login | — | medium | resolved by operator answer to U1, not by codebase evidence; an unverified external assertion about a third-party site that can change |

Distribution: **12** high, **3** medium, **0** low.

> Overall confidence is held at `medium` — not averaged up — because the two
> claims that most shape the plan (C13 scope completeness, C14 external
> feasibility) are the medium ones, and neither is resolvable by more research
> on this repository.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — ¿app.hooba.com exige MFA, CAPTCHA o expira la sesión rápido?** —
  *Resolved*: Sin MFA — login desatendido. La acción `authenticate` (una vez
  desestubada) resuelve credenciales vía `CredentialBroker` y entra sola.
  *Resolves claims*: C14

- [x] **U2 — ¿Qué transporte de WhatsApp implica el número a asignar?** —
  *Resolved*: Número personal — puente whatsmeow (`WhatsAppBridgeWrapper` + el
  bridge Go). Sin cuenta Business ni aprobación de Meta.
  *Resolves claims*: C7

- [x] **U3 — ¿Google Calendar o el O365 que ya funciona?** — *Resolved*: Google
  Calendar — construir las tools. Promover `GoogleClient.get_calendar_client` a
  cliente real y añadir `create_event` / `list_events` / `update_event`.
  *Resolves claims*: C9

- [x] **U4 — ¿Dividir FEAT-453 y esperar a FEAT-452?** — *Resolved*: Una feature,
  capa wiki al final. Todo bajo FEAT-453, secuenciando el plano wiki como última
  tarea, tras el merge de FEAT-452.
  *Nota post-respuesta (2026-08-23T10:02Z)*: FEAT-452 hizo merge a `dev`
  (PR #1209) justo después de responder. La premisa que motivaba "al final" —
  evitar dos diseños paralelos de plano de dominio — ya no aplica; la capa wiki
  puede ordenarse por sus propias dependencias. **La decisión de mantenerlo como
  UNA feature se conserva.**
  *Resolves claims*: C11, C13

- [x] **U5 — ¿Nivel de autonomía para escrituras con efecto legal?** —
  *Resolved*: Borradores solos, envío siempre confirmado. El agente monta drafts
  sin intervención; todo submit con efecto legal pasa por `await_human`.
  *Resolves claims*: C2

### Unresolved (defer to spec / implementation)

- [ ] **Does the tax-reminder requirement justify deploying `ai-parrot-server`,
  or should reminders run from a lighter in-process scheduler?** — *Owner*: tbd
  *Blocks claims*: C8
  *Plausible answers*: a) deploy the server distribution · b) in-process
  APScheduler inside the bot · c) system cron invoking the agent CLI

- [ ] **Which Hooba operations get `TemplatePlan`s in the first release?** —
  *Owner*: tbd
  *Blocks claims*: C13
  *Plausible answers*: a) all five (login, cliente, gasto, factura draft,
  descarga PDF) · b) login + gasto only, proving the loop end-to-end first

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-453`** — *Rationale*: the highest-value slice — closing the
eight stubbed actions, validating plans at load, and building the Hooba domain
toolkit on `TemplatePlan`/`ScrapingFlow` — is high-confidence, precisely
localized (C1, C2, C3), and blocking everything else. Per U4 the spec stays a
single feature, with the wiki/Obsidian layer ordered as its final tasks so it
lands after FEAT-452 merges.

### Alternatives

- **`/sdd-brainstorm FEAT-453`** — if you want the full agent composition
  (browser + chat + brain + calendar) explored as one architecture with
  competing options before committing to a spec.
- **`/sdd-task FEAT-453`** — not suitable; this is far past a trivial localized fix.
- **Manual review** — not indicated; research completed without truncation and
  the synthesis linter passed on the first iteration.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-453/state.json` |
| Source (raw) | `sdd/state/FEAT-453/source.md` |
| Research plan | `sdd/state/FEAT-453/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-453/findings/F001-*.md` … `F011-*.md` (F009 revised in place; F011 added in revision 2) |
| Synthesis (JSON) | `sdd/state/FEAT-453/synthesis.json` |

**Budget consumed** (profile: `loose`):

- Files read: 24 / 100
- Grep calls: 19 / 60
- Git calls: 2 / 20
- Wall time: ~620s / 900s
- Truncated: **no**
- Synthesis lint: **passed**, 0 corrective iterations (re-linted after revision 2: **passed**)

**Revision 2 delta** (2026-08-23T10:02Z, post `git pull --no-rebase origin dev`):
FEAT-452 merged via PR #1209. F009 revised in place, F011 added (2 files read,
1 git call, 2 wiki calls). Claim C11 restated, C15 added, one integration risk
retired and one added. Overall confidence unchanged at `medium`.

**Mode determination**: `auto` → resolved to `enrichment` (source is additive;
the only negation targets an external system). Note the enrichment carries an
investigation-flavoured sub-thread: research surfaced a latent defect (C2) that
is a hard prerequisite.

**Schema note**: `sdd/templates/research_plan.schema.json` v1.0 has no
`wiki_query` / `wiki_page` / `wiki_related` in its query `type` enum, even
though the `/sdd-proposal` command mandates wiki-first research. The plan was
written with the wiki types and the divergence recorded in
`research_plan.json:meta.schema_note` — the schema is stale relative to
FEAT-403 / FEAT-450 rather than the plan being invalid.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara |
