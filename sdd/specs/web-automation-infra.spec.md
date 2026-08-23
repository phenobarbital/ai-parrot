---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
# Intentional FEAT-ID reuse: FEAT-453 was reserved by /sdd-proposal (ledger
# commit, label "web-automation-infra") for this initiative. This spec is that
# initiative's first and only deliverable, so it reuses the ID rather than
# burning a second one. Same pattern as FEAT-449/legal-norms-graph-boe.
reuse_feature_id: FEAT-453
---

# Feature Specification: Business Browser Automation — DSL stub closure, generic automation engine, and the gestoría agent

**Feature ID**: FEAT-453
**Date**: 2026-08-23
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

> **Proposal**: [`sdd/proposals/web-automation-infra.proposal.md`](../proposals/web-automation-infra.proposal.md)
> (revision 2, enrichment, overall confidence `medium`).
> **Research audit**: `sdd/state/FEAT-453/` — 11 findings, 19 queries, lint clean.

---

## 1. Motivation & Business Requirements

### Problem Statement

Spanish law obliges the author to keep his books in a cloud management product,
Hooba (`https://app.hooba.com/`), which exposes **no API of any kind**. Every
operation that matters — creating clients, registering expenses, CRM upkeep,
issuing invoices — is reachable only through a browser session. The recurring
cost is not any single operation but their aggregate: a self-employed
professional spends hours per quarter re-keying data that already exists in a
bank statement, and misses deadlines that are entirely predictable.

Research (proposal §2) established that ai-parrot already supplies almost all of
the machinery: a 27-model typed browser-action DSL, a merged composition layer
(`TemplatePlan` → `ScrapingFlow` → `FlowExecutor` with session affinity and
checkpoints), two driver backends, a Chrome DevTools MCP agent, wiki and
Obsidian toolkits, Telegram and WhatsApp channels, a credential broker with a
signed audit ledger, and Excel loaders.

**But the modern execution path is silently broken for exactly this use case.**
`executor.py::_dispatch_step` (lines 298-311) matches eight action types —
`authenticate`, `upload_file`, `wait_for_download`, `get_cookies`,
`set_cookies`, `await_human`, `await_keypress`, `await_browser_event` — logs a
warning, and **returns `True`**. Those eight are precisely the login,
file-exchange, session-persistence and human-approval primitives a bookkeeping
workflow is built from. A plan whose first step is `authenticate` proceeds
believing it is logged in and runs every subsequent step against a login page.
Against a legally-mandated accounting system, silent success is materially worse
than failure.

This is the same defect class FEAT-222 identified (its spec §1, gap 4) and fixed
for `Loop`/`Conditional` by extracting them into `advanced_actions.py`. That fix
covered two actions and left eight behind.

### Goals

- **G1** — Close the stub gap: all eight actions execute for real on the modern
  toolkit path, with the legacy `WebScrapingTool` delegating to the same shared
  implementations so no duplicate logic survives.
- **G2** — Reject malformed plans **before** the browser opens, by validating
  `ScrapingPlan.steps` against the typed `BrowserAction` union at load time.
- **G3** — Source authentication credentials from the existing
  `CredentialBroker`, never from literal values embedded in plan JSON.
- **G4** — Ship a **generic, domain-neutral** `BusinessAutomationToolkit` over
  `TemplatePlan`/`ScrapingFlow`, with a configurable external plans directory —
  so the reusable engine is public and site-specific plans stay private.
- **G5** — Gate every write with legal effect behind `await_human`; drafts may
  be assembled unattended.
- **G6** — Add Google Calendar event tools and an in-process reminder scheduler
  for the Spanish tax calendar.
- **G7** — Ingest a bank-statement Excel iteratively through a bounded,
  LLM-free `ExecutionPlan` triggered as a single tool call.
- **G8** — Give the agent a `gestoria` wiki plane mirrored into Obsidian,
  instantiating FEAT-452's merged domain-plane recipe.

### Non-Goals (explicitly out of scope)

- **Building a browser-automation DSL.** 27 typed `BrowserAction` models already
  exist (contract §6). This spec closes their execution gap; it does not author
  a language.
- **Building a WikiToolkit or ObsidianToolkit.** Both exist and are complete.
- **Building Telegram or WhatsApp transport.** Both ship. Only wiring and
  allowlist hardening are in scope.
- **Committing Hooba-specific `TemplatePlan`s, selectors, or credentials to this
  repository.** Site plans are an out-of-repo deliverable (§3, Deliverable X).
  Anonymized fixtures ship instead.
- **The Meta Cloud API WhatsApp path** (`WhatsAppAgentWrapper`). The
  personal-number whatsmeow bridge was selected (§8, resolved U2).
- **Injecting a `FederatedWikiStore` into `LLMWikiToolkit`, or auto-registering
  a namespace from agent code.** Both are explicit FEAT-452 non-goals.
- **Concurrent fan-out over one authenticated Hooba session.** FEAT-222 records
  this as deferred debt, safe in sequential mode only — acceptable for a
  single-operator workload.
- **Deriving tax deadlines from primary legal sources.** FEAT-449
  (`legal-norms-graph-boe`) builds a BOE temporal-validity graph, but it is a
  lawyer-facing, zero-LLM *article-in-force* vertical, not a filing calendar.
  It is adjacent, not a dependency. See §7 Known Risks.

---

## 2. Architectural Design

### Overview

Five layers, built strictly bottom-up. Layers 0–1 are corrections to shared
infrastructure and benefit every scraping consumer in the repo, not just this
feature. Layers 2–4 are the new capability.

**Layer 0 — DSL correctness.** Extract the eight stubbed action handlers out of
the legacy `WebScrapingTool` into a new `session_actions.py`, following the
exact shape FEAT-222 used for `advanced_actions.py`: standalone async functions
taking `AbstractDriver` plus a `dispatch_step_fn` callback for recursion.
`executor.py::_dispatch_step` calls them; `tool.py` delegates to them.

**Layer 1 — Plan integrity.** `ScrapingPlan` gains opt-in validation of its
untyped `steps: List[Dict[str, Any]]` against the discriminated `BrowserAction`
union, and `Authenticate` resolves `username`/`password` through
`CredentialBroker` instead of carrying literals.

**Layer 2 — Generic engine.** `BusinessAutomationToolkit` — an `AbstractToolkit`
holding a `FlowExecutor`, a `TemplatePlan` registry loaded from a configurable
**external plans directory**, and a submit-gate policy. It knows nothing about
Hooba; it knows about "run a named business operation with these parameters,
pausing for human confirmation before anything with legal effect".

**Layer 3 — Surrounding capabilities.** Google Calendar event tools, an
in-process reminder scheduler, and the bank-Excel `ExecutionPlan`.

**Layer 4 — Brain.** A `gestoria` wiki plane mirrored to an Obsidian folder,
instantiating FEAT-452's merged recipe.

The agent that composes all of this, and the Hooba plans it drives, live
**outside this repository** (§8, resolved: generic-public / plans-private).

### Component Diagram

```
Layer 0 ── session_actions.py  (NEW, mirrors advanced_actions.py)
           exec_authenticate · exec_upload_file · exec_wait_for_download
           exec_get_cookies · exec_set_cookies · exec_await_human
           exec_await_keypress · exec_await_browser_event
                  ▲                              ▲
                  │ called by                    │ delegated by
           executor.py::_dispatch_step      tool.py::_execute_step
           (stub branch DELETED)            (duplicates DELETED)

Layer 1 ── ScrapingPlan.validate_steps()  →  BrowserAction union
           Authenticate  ──resolve()──→  CredentialBroker ──→ AuditLedger

Layer 2 ── BusinessAutomationToolkit(AbstractToolkit)
           ├── TemplatePlanStore   ← external plans dir (private, configurable)
           ├── FlowExecutor        (FEAT-222, unmodified)
           │     └── SessionManager → BrowserContext per session label
           └── SubmitGate          → await_human before legal-effect writes

Layer 3 ── GoogleCalendarToolkit          ReminderScheduler (core, in-process)
           create/list/update_event       tax-calendar callbacks
           ExecutionPlanToolkit.plan_execute → AgentsFlow  (bank-Excel ingest)

Layer 4 ── gestoria wiki plane (own LLMWikiToolkit instance)
           └── `wikitoolkit ns add --kind store`  (OPERATOR step, once)
           └── Obsidian folder mirror ← ObsidianToolkit

  ── out of repo ──
  GestoriaAgent  +  hooba/*.template.json  (private plans, 5 operations)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `executor.py::_dispatch_step` | **modifies** | stub branch (lines 298-311) replaced with real dispatch |
| `tool.py::_execute_step` | **modifies** | 8 handlers delegate to `session_actions`; duplicates removed |
| `ScrapingPlan` | extends | adds opt-in `validate_steps()`; field types unchanged |
| `Authenticate` | extends | adds broker-backed credential resolution; literal fields retained for back-compat |
| `AbstractToolkit` | extends | `BusinessAutomationToolkit` subclasses it, `auto_open=True` |
| `FlowExecutor` | **uses, unmodified** | constructed by the toolkit with `templates=` from the plans dir |
| `SessionManager` | uses, unmodified | session affinity comes free via `FlowNode.session` |
| `CredentialBroker` | uses | `resolve(provider, surface, user)` at action time |
| `ConfirmationGuard` | uses | primary SUBMIT gate at the tool-call boundary (D2) |
| `HumanInteractionManager` | uses | injected into the guard; `None` ⇒ fail-closed |
| `HumanChannel` / `TelegramHumanChannel` | uses | mid-plan `await_human` reaches Telegram (D2) |
| `ToolManager.set_confirmation_guard()` | uses | wiring point for the guard |
| `AuditLedger` | uses | credential-use trail for automated filings |
| `ExecutionPlanToolkit` | uses, unmodified | `plan_execute` for the bank-Excel ingest |
| `ExcelLoader` | uses, unmodified | `output_mode="row"` for per-transaction Documents |
| `GoogleClient` | **modifies** | `get_calendar_client()` promoted from config dict to live client |
| `parrot.scheduler` (core) | **modifies** | reactivates the `scheduler` extra — see §7 Decision D1 |
| `LLMWikiToolkit` | uses | second instance for the `gestoria` plane |
| `ObsidianToolkit` | uses, unmodified | vault mirror |
| `WhatsAppBridgeWrapper` | uses, unmodified | `allowed_numbers` allowlist as a financial control |
| `TelegramAgentWrapper` | uses, unmodified | `handle_document` already forwards uploads as `attachments` |

### Data Models

```python
# parrot_tools/business_automation/models.py  (NEW)

class OperationKind(str, Enum):
    """Whether an operation has legal effect, which decides the submit gate."""
    READ = "read"            # never gated
    DRAFT = "draft"          # unattended — assembles, does not submit
    SUBMIT = "submit"        # ALWAYS gated behind await_human


class BusinessOperation(BaseModel):
    """One named, parameterized business operation backed by a ScrapingFlow."""
    name: str
    description: str
    kind: OperationKind
    flow_ref: str                          # ScrapingFlow name in the plans dir
    params: list[ParamSpec] = Field(default_factory=list)
    confirm_prompt: str | None = None      # shown to the human at the gate


# NOTE: there is deliberately NO bespoke gate-decision model here.
# The SUBMIT gate reuses the existing HITL stack — `ConfirmationDecision`
# (auth/confirmation.py) and `InteractionResult` (parrot/human/models.py).
# See §7 Decision D2.


class ImportRun(BaseModel):
    """Discriminates one bank-statement import from another so two legitimate
    imports with identical logical params never share a checkpoint token."""
    statement_digest: str                  # sha256 of the source Excel bytes
    period: str                            # e.g. "2026-Q1"
    started_at: datetime
```

### New Public Interfaces

```python
# parrot_tools/scraping/session_actions.py  (NEW — mirrors advanced_actions.py)
async def exec_authenticate(
    driver: AbstractDriver,
    action: Authenticate,
    dispatch_step_fn: DispatchStepFn,
    *,
    credential_resolver: CredentialResolverFn | None = None,
    timeout: int = 30,
) -> bool: ...

async def exec_await_human(
    driver: AbstractDriver,
    action: AwaitHuman,
    *,
    channel: HumanChannel | None = None,   # parrot.human — NOT a bespoke notifier (D2)
) -> bool: ...

async def exec_upload_file(driver: AbstractDriver, action: UploadFile) -> bool: ...
async def exec_wait_for_download(driver: AbstractDriver, action: WaitForDownload) -> bool: ...
async def exec_get_cookies(driver: AbstractDriver, action: GetCookies) -> dict[str, Any]: ...
async def exec_set_cookies(driver: AbstractDriver, action: SetCookies) -> bool: ...
async def exec_await_keypress(driver: AbstractDriver, action: AwaitKeyPress) -> bool: ...
async def exec_await_browser_event(driver: AbstractDriver, action: AwaitBrowserEvent) -> bool: ...


# parrot_tools/scraping/plan.py  (EXTENDS existing ScrapingPlan)
class ScrapingPlan(BaseModel):
    def validate_steps(self, *, strict: bool = True) -> list[BrowserAction]:
        """Parse `steps` into typed BrowserActions, raising on the first invalid
        step. Called by the toolkit BEFORE a driver is created."""


# parrot_tools/business_automation/toolkit.py  (NEW)
class BusinessAutomationToolkit(AbstractToolkit):
    auto_open = True

    def __init__(
        self,
        plans_dir: str | Path,
        browser: Any | None = None,
        credential_broker: CredentialBroker | None = None,
        human_manager: HumanInteractionManager | None = None,   # HITL — D2
        checkpoint_dir: Path | None = None,
        **kwargs: Any,
    ) -> None: ...

    async def list_operations(self) -> dict[str, Any]: ...
    async def describe_operation(self, name: str) -> dict[str, Any]: ...
    async def run_operation(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...
    async def resume_operation(self, run_id: str, resume_from: str | None = None) -> dict[str, Any]: ...


# parrot_tools/google/calendar.py  (NEW)
class GoogleCalendarToolkit(AbstractToolkit):
    async def create_event(self, summary: str, start: str, end: str, **kw) -> dict[str, Any]: ...
    async def list_events(self, time_min: str, time_max: str, **kw) -> dict[str, Any]: ...
    async def update_event(self, event_id: str, **kw) -> dict[str, Any]: ...


# parrot/scheduler/inprocess.py  (NEW in CORE — see §7 Decision D1)
class InProcessScheduler:
    """Lightweight APScheduler wrapper for agent processes that must schedule
    work WITHOUT deploying ai-parrot-server. Deliberately does NOT shadow
    `AgentSchedulerManager`, which stays satellite-only."""
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def add_cron(self, name: str, cron: str, callback: Callable[..., Awaitable[Any]]) -> str: ...


# parrot_tools/business_automation/smoke.py  (NEW — mechanism only; D4)
class SmokeCheck(BaseModel):
    """Scheduled canary: runs one READ-kind operation and alerts on failure,
    so DOM churn is discovered before a real write fails."""
    operation: str                         # must resolve to OperationKind.READ
    cron: str
    alert_channel: str = "telegram"
```

---

## 3. Module Breakdown

### Module 1: `session_actions` extraction
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/session_actions.py` (new)
- **Responsibility**: Standalone async implementations of the eight stubbed
  actions, lifted from `tool.py`'s methods (`_handle_authentication`:1841,
  `_await_human`:2086, `_await_keypress`:2175, `_wait_for_download`:2202,
  `_upload_file`:2336, `_get_cookies`:1807, `_set_cookies`:1826,
  `_await_browser_event`:1913). Signature shape mirrors `advanced_actions.py`.
- **Depends on**: existing `advanced_actions.py` pattern; `drivers/abstract.py`

### Module 2: Modern dispatch + legacy delegation
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py`,
  `.../scraping/tool.py`
- **Responsibility**: Delete the `return True` stub branch (executor.py:298-311)
  and dispatch to Module 1. Rewrite the eight `tool.py` handlers as thin
  delegations so exactly one implementation exists.
- **Depends on**: Module 1

### Module 3: Load-time plan validation
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py`,
  `.../scraping/models.py`
- **Responsibility**: A discriminated union over the 27 `BrowserAction`
  subclasses keyed on `action`, plus `ScrapingPlan.validate_steps()`. Opt-in so
  no existing caller breaks.
- **Depends on**: none (parallel with Module 1)

### Module 4: Broker-backed `Authenticate`
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/session_actions.py`,
  `.../scraping/models.py`
- **Responsibility**: `Authenticate` gains `credential_provider: str | None`.
  When set, `exec_authenticate` resolves via `CredentialBroker` and never reads
  the literal `username`/`password` fields. Resolution is audit-ledgered.
- **Depends on**: Modules 1, 3

### Module 5: `BusinessAutomationToolkit`
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py` (new package)
- **Responsibility**: The generic engine — operation registry, `FlowExecutor`
  wiring, `run_id` bookkeeping, `auto_open` browser lifecycle, and SUBMIT
  gating **via the existing HITL stack** (`ConfirmationGuard` +
  `HumanInteractionManager`), not a bespoke gate. Marks `run_operation` as a
  confirmation tool through `routing_meta` when the resolved operation is
  `OperationKind.SUBMIT`, and sets `confirm_window_seconds=0` for it so a
  repeated submit is never auto-approved by a window hit (D2).
  Contains **no** Hooba identifiers.
- **Depends on**: Modules 2, 3, 4

### Module 6: External plans directory contract
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/business_automation/store.py` (new)
- **Responsibility**: Load `BusinessOperation` + `TemplatePlan` + `ScrapingFlow`
  definitions from a configurable directory outside the repo; schema-validate on
  load; hot-reload on change. Ships anonymized fixtures under
  `packages/ai-parrot-tools/tests/business_automation/fixtures/`.
- **Depends on**: Module 5

### Module 7: Google Calendar tools
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/google/calendar.py` (new),
  `packages/ai-parrot/src/parrot/interfaces/google.py` (modify)
- **Responsibility**: Promote `get_calendar_client()` (google.py:760-762) from
  returning a config dict to returning a usable client; build
  `create_event`/`list_events`/`update_event` on it.
- **Depends on**: none (parallel)

### Module 8: In-process scheduler in core
- **Path**: `packages/ai-parrot/src/parrot/scheduler/inprocess.py` (new),
  `packages/ai-parrot/pyproject.toml` (reactivate the `scheduler` extra)
- **Responsibility**: A lightweight APScheduler wrapper usable without deploying
  ai-parrot-server, plus tax-calendar reminder callbacks and the `SmokeCheck`
  runner (D4). **Must not shadow**
  the satellite-delegating `__getattr__` in `parrot/scheduler/__init__.py` —
  `AgentSchedulerManager` and friends stay satellite-only.
  See §7 **Decision D1** for why this partially reverses FEAT-203.
- **Depends on**: Module 7 (reminders write calendar events)

### Module 9: Bank-Excel expense ingestion
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/business_automation/ingest.py` (new)
- **Responsibility**: Build an `ExecutionPlan` that iterates `ExcelLoader`
  row-mode Documents and invokes the `register_expense` operation per row, run
  via `ExecutionPlanToolkit.plan_execute` so the loop costs no LLM tokens.
  Progress surfaced through `plan_status`/`plan_artifacts`.
  **Must inject `ImportRun.statement_digest` into `flow.global_params`** so the
  checkpoint token discriminates two legitimate imports with identical logical
  parameters (D3) — otherwise the second import resumes the first's checkpoint
  and silently skips every row.
- **Depends on**: Module 5

### Module 10: `gestoria` wiki plane + Obsidian mirror
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/business_automation/memory.py` (new)
- **Responsibility**: Instantiate FEAT-452's recipe — a dedicated
  `LLMWikiToolkit` with its own storage root, PageIndex plane and `tenant_id`;
  idempotent `create_wiki()`; Obsidian folder mirror. Namespace registration is
  an **operator runbook step**, not agent code (§5 AC-14).
- **Depends on**: Module 5

### Module 11: Channel wiring and allowlist hardening
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/bridge_config.py` (modify),
  docs
- **Responsibility**: Document and test `allowed_numbers` as a **financial**
  control, not a convenience. Fail closed when the allowlist is empty in a
  configuration that exposes SUBMIT-kind operations.
- **Depends on**: Module 5

### Deliverable X (OUT OF REPO — tracked, not implemented here)
- **Path**: private plans directory consumed by Module 6
- **Contents**: five Hooba `BusinessOperation`s — `login`, `create_client`,
  `register_expense`, `draft_invoice`, `download_invoice_pdf` — with their
  `TemplatePlan`s and selectors, plus the Hooba `SmokeCheck` plan (a READ-kind
  login + dashboard navigation), which needs real credentials and real
  selectors and therefore cannot live in this repo (D4).
- **Why out of repo**: §8, resolved — the engine is public, site plans are not.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_exec_authenticate_form_flow` | M1 | Form login fills both selectors and submits |
| `test_exec_authenticate_enter_on_username` | M1 | Multi-step login presses Enter after username |
| `test_exec_await_human_selector_condition` | M1 | Returns when the target selector appears |
| `test_exec_await_human_timeout` | M1 | Returns False after `timeout`, does not hang |
| `test_exec_upload_file_multiple` | M1 | `multiple_files=True` uses `file_paths` |
| `test_exec_wait_for_download_pattern` | M1 | Matches `filename_pattern`, honours `move_to` |
| `test_cookies_roundtrip` | M1 | `get_cookies` → `set_cookies` restores a session |
| `test_dispatch_no_longer_returns_true_for_stubs` | M2 | **Regression**: none of the 8 types hit a `return True` path |
| `test_legacy_tool_delegates_to_session_actions` | M2 | `tool.py` handlers call the shared fns (no duplicate logic) |
| `test_validate_steps_rejects_unknown_action` | M3 | Unknown `action` raises before any driver is built |
| `test_validate_steps_rejects_missing_required_field` | M3 | `UploadFile` without `file_path` raises |
| `test_authenticate_prefers_broker_over_literals` | M4 | With `credential_provider` set, literal fields are ignored |
| `test_authenticate_never_logs_secrets` | M4 | Password never appears in log records |
| `test_submit_gate_blocks_submit_kind` | M5 | `OperationKind.SUBMIT` routes through `ConfirmationGuard.confirm()` |
| `test_submit_gate_skips_draft_kind` | M5 | `DRAFT` runs unattended, guard returns `not_required` |
| `test_submit_gate_fails_closed_without_human_manager` | M5 | `human_manager=None` ⇒ decision `cancelled`, browser never opened |
| `test_submit_gate_window_disabled` | M5 | Two identical submits ask twice — no `confirm_window_seconds` hit |
| `test_await_human_manual_requires_channel` | M1 | `condition_type="manual"` with no `HumanChannel` fails closed |
| `test_await_human_notifies_channel` | M1 | DOM-condition pause also emits `send_notification()` |
| `test_checkpoint_token_differs_per_statement` | M9 | Same period + different statement digest ⇒ different checkpoint file |
| `test_checkpoint_permissions` | M9 | Checkpoint dir 0700, files 0600 |
| `test_plans_dir_schema_validation` | M6 | Malformed operation file rejected at load |
| `test_calendar_create_event` | M7 | Builds a valid Calendar v3 insert body |
| `test_inprocess_scheduler_does_not_shadow_satellite` | M8 | `parrot.scheduler.AgentSchedulerManager` still resolves via `__getattr__` |
| `test_ingest_plan_one_node_per_row` | M9 | N rows → N `register_expense` nodes |
| `test_gestoria_plane_uses_own_storage_root` | M10 | Distinct `storage_dir` from the default wiki |
| `test_bridge_fails_closed_on_empty_allowlist` | M11 | Empty `allowed_numbers` + SUBMIT ops → refuse to start |

### Integration Tests

| Test | Description |
|---|---|
| `test_authenticated_flow_end_to_end` | Against a local fixture site: login → navigate → extract, asserting the session survives across `FlowNode`s |
| `test_stub_regression_full_plan` | A plan using all 8 formerly-stubbed actions completes with real effects, not silent success |
| `test_expense_import_resumes_from_checkpoint` | Kill mid-import, `resume_from` continues without re-registering earlier rows |
| `test_submit_gate_end_to_end` | A SUBMIT operation pauses, receives approval, then completes |

### Test Data / Fixtures

```python
@pytest.fixture
def fixture_plans_dir(tmp_path: Path) -> Path:
    """Anonymized plans dir — a generic 'acme-books' site, never Hooba."""

@pytest.fixture
def local_fixture_site(aiohttp_server):
    """Static login + dashboard + form pages so auth/upload/download tests
    never touch a third-party site."""

@pytest.fixture
def fake_broker() -> CredentialBroker:
    """Broker whose single resolver returns deterministic test credentials."""
```

> **No test may contact `app.hooba.com`.** Every browser test runs against the
> local fixture site.

---

## 5. Acceptance Criteria

- [ ] **AC-1** — `grep -n "return True" packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` shows no stub-branch survivor for the eight action types.
- [ ] **AC-2** — All eight actions execute for real on the modern toolkit path (`test_stub_regression_full_plan` passes).
- [ ] **AC-3** — `tool.py` contains no duplicate implementation of the eight actions; each handler is a delegation.
- [ ] **AC-4** — `ScrapingPlan.validate_steps()` rejects an unknown action type and a missing required field, before any driver is constructed.
- [ ] **AC-5** — With `credential_provider` set, `Authenticate` resolves through `CredentialBroker` and the literal `username`/`password` fields are never read.
- [ ] **AC-6** — No test or log emits a credential value (`test_authenticate_never_logs_secrets`).
- [ ] **AC-7** — `BusinessAutomationToolkit` contains zero occurrences of "hooba" (case-insensitive) — the engine is domain-neutral.
- [ ] **AC-8** — Every `OperationKind.SUBMIT` operation is gated by `ConfirmationGuard.confirm()`; every `DRAFT` runs unattended.
- [ ] **AC-8a** — With `human_manager=None` a SUBMIT operation is **denied** and no browser is opened (fail-closed).
- [ ] **AC-8b** — `confirm_window_seconds` is 0 for SUBMIT operations: two identical submits prompt twice.
- [ ] **AC-8c** — A mid-plan `await_human` with `condition_type="manual"` and no `HumanChannel` fails closed rather than blocking forever.
- [ ] **AC-9** — The plans directory loads from a path outside the repository and schema-validates on load.
- [ ] **AC-10** — Google Calendar `create_event` / `list_events` / `update_event` work against a mocked Calendar v3 client.
- [ ] **AC-11** — `parrot.scheduler.AgentSchedulerManager` still resolves through the satellite `__getattr__` after Module 8 lands (no shadowing regression).
- [ ] **AC-12** — A bank-statement Excel of N rows produces N expense registrations, and a mid-run kill resumes without duplicates.
- [ ] **AC-12a** — Two imports with identical `period` but different statement bytes produce **different** checkpoint files (no cross-resume).
- [ ] **AC-12b** — The checkpoint directory is 0700 and its files 0600, and is located outside both the Obsidian vault and any wiki storage root.
- [ ] **AC-13** — The `gestoria` plane uses a storage root distinct from the default wiki, and `create_wiki()` is idempotent across restarts.
- [ ] **AC-14** — The operator runbook documents the one-off `wikitoolkit ns add` for the `gestoria` plane, and `wikitoolkit query --ns gestoria` returns a seeded page.
- [ ] **AC-15** — The WhatsApp bridge refuses to start with an empty `allowed_numbers` when SUBMIT-kind operations are exposed.
- [ ] **AC-16** — All unit tests pass (`pytest packages/ai-parrot-tools/tests/ -v`).
- [ ] **AC-17** — All integration tests pass, none contacting `app.hooba.com`.
- [ ] **AC-18** — No breaking change to `WebScrapingToolkit`'s public API; existing scraping tests pass unchanged.
- [ ] **AC-19** — Documentation updated: plans-directory contract, submit-gate policy, operator runbook.
- [ ] **AC-20** — A `SmokeCheck` on a READ-kind operation runs on schedule and alerts on failure (verified against the fixture site).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Every entry below was read directly
> from source during this spec's research pass on `dev` at merge commit for
> PR #1204/#1205/#1206/#1207/#1209. Line numbers are as of that state.

### Verified Imports

```python
# scraping engine — all exported from the package __init__
from parrot_tools.scraping import (
    WebScrapingToolkit,      # verified: scraping/__init__.py:2,41
    TemplatePlan, ParamSpec, # verified: scraping/__init__.py:28,76
    ScrapingFlow, FlowNode, FlowResult,  # verified: scraping/__init__.py:29,78
    FlowExecutor,            # verified: scraping/__init__.py:30,81
    SessionManager,          # verified: scraping/__init__.py:32,83
)
from parrot_tools.scraping.drivers.abstract import AbstractDriver   # verified: drivers/abstract.py:37+
from parrot_tools.scraping.executor import execute_plan_steps        # verified: executor.py:42
from parrot_tools.scraping.plan import ScrapingPlan                  # verified: plan.py:59
from parrot_tools.scraping.advanced_actions import (                 # verified: advanced_actions.py
    exec_loop,               # line 229
    exec_conditional,        # line 313
    substitute_template_vars,# line 102
)
from parrot.tools.toolkit import AbstractToolkit                     # verified: tools/toolkit.py:216
from parrot.auth.broker import CredentialBroker                      # verified: auth/broker.py:326
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit             # verified: wiki/toolkit.py:54
from parrot.tools.obsidian import ObsidianToolkit                    # verified: tools/obsidian.py:78
from parrot_loaders.excel import ExcelLoader                         # verified: parrot_loaders/excel.py:21

# HITL stack (Decision D2) — do NOT reinvent any of this
from parrot.human import (
    HumanChannel,                # verified: human/__init__.py:31 (re-export of channels/base.py:47)
    HumanInteractionManager,     # verified: human/__init__.py:33 (manager.py)
    HumanTool,                   # verified: human/__init__.py:34
    HumanDecisionNode,           # verified: human/__init__.py:35
    WaitStrategy, InteractionType, InteractionStatus, TimeoutAction,
    HumanInteraction, HumanResponse, InteractionResult, Severity,  # verified: human/__init__.py:18-29
)
from parrot.human.channels import ChannelRegistry           # verified: human/channels/__init__.py:16
# TelegramHumanChannel is LAZY (PEP 562) — contributed by ai-parrot-integrations:
#   parrot.human.TelegramHumanChannel  → ".channels.telegram"   (human/__init__.py:40)
from parrot.auth.confirmation import ConfirmationGuard      # verified: auth/confirmation.py:378
```

### Existing Class Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py
async def execute_plan_steps(                       # line 42
    driver: AbstractDriver,
    plan: Optional[ScrapingPlan] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    selectors: Optional[List[Dict[str, Any]]] = None,
    config: Optional[DriverConfig] = None,
    base_url: Optional[str] = None,
) -> ScrapingResult: ...
async def _dispatch_step(...)                       # line 229
# THE DEFECT — lines 298-311:
#   elif action_type in ("get_cookies", "set_cookies", "authenticate",
#                        "await_human", "await_keypress", "await_browser_event",
#                        "upload_file", "wait_for_download"):
#       logger.warning("Action '%s' requires the full WebScrapingTool; skipping...")
#       return True

# packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py — the real implementations
async def _get_cookies(self, action: GetCookies) -> Dict[str, Any]:   # line 1807
async def _set_cookies(self, action: SetCookies) -> bool:             # line 1826
async def _handle_authentication(self, action: Authenticate):         # line 1841
async def _await_browser_event(self, action: AwaitBrowserEvent) -> bool:  # line 1913
async def _await_human(self, action: AwaitHuman):                     # line 2086
async def _await_keypress(self, action: AwaitKeyPress):               # line 2175
async def _wait_for_download(self, action: WaitForDownload) -> bool:  # line 2202
async def _upload_file(self, action: UploadFile) -> bool:             # line 2336
# dispatch site: `elif action_type == 'authenticate':` line 747

# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py
class BrowserAction(BaseModel, ABC):                # line 14
    def get_action_type(self) -> str: ...           # line 24
class Authenticate(BrowserAction):                  # line 478
    method: Literal["form","basic","oauth","custom"] = "form"
    username: Optional[str] = None                  # ← literal secret today
    password: Optional[str] = None                  # ← literal secret today
    username_selector: str = "#username"
    enter_on_username: bool = False
    password_selector: str = "#password"
    submit_selector: str = 'input[type="submit"], button[type="submit"]'
    custom_steps: Optional[List[BrowserAction]] = None
class AwaitHuman(BrowserAction):                    # line 514
    target: Optional[str] = None
    condition_type: Literal["selector","url_contains","title_contains","manual"] = "selector"
    message: str = "Waiting for human intervention..."
    timeout: int = 300
class WaitForDownload(BrowserAction):               # line 612
    filename_pattern: Optional[str] = None
    download_path: Optional[str] = None
    timeout: int = 60
    move_to: Optional[str] = None
    delete_after: bool = False
class UploadFile(BrowserAction):                    # line 633
    selector: str
    file_path: str
    wait_after_upload: Optional[str] = None
    wait_timeout: int = 10
    multiple_files: bool = False
    file_paths: Optional[List[str]] = None
class ScrapingStep: ...                             # line 758

# packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py
class ScrapingPlan(BaseModel):                      # line 59
    url: str; objective: str
    steps: List[Dict[str, Any]]                     # UNTYPED at rest — G2 targets this
    selectors: Optional[List[Dict[str, Any]]] = None
    browser_config: Optional[Dict[str, Any]] = None
    fingerprint: str = ""

# packages/ai-parrot-tools/src/parrot_tools/scraping/flow_models.py
class FlowNode(BaseModel):                          # line 19
    id: str; plan_ref: str
    inputs: Dict[str, str] = {}
    session: str = "default"
    on_error: Literal["abort","skip","retry"] = "abort"
    max_retries: int = 3
class ScrapingFlow(BaseModel):                      # line 39
    name: str; description: str = ""
    nodes: List[FlowNode] = Field(min_length=1)
    global_params: Dict[str, Any] = {}
class FlowResult(BaseModel): ...                    # line 147

# packages/ai-parrot-tools/src/parrot_tools/scraping/flow_executor.py
class FlowExecutor:                                 # line 40
    def __init__(self, browser, registry=None, config=None, concurrency=1,
                 checkpoint_dir=None, logger=None, templates=None) -> None: ...   # line 58
    async def run(self, flow: ScrapingFlow, params=None, resume_from=None) -> FlowResult: ...  # line 338

# packages/ai-parrot-tools/src/parrot_tools/scraping/session_manager.py
class SessionManager:                               # line 21
    async def get_context(self, session: str) -> Any: ...       # line 46
    async def new_page(self, session: str) -> Any: ...          # line 65
    def precompute_last_use(self, topo_order) -> Dict[str,str]: # line 70
    async def close_if_last(self, session: str, node_id: str) -> None: ...  # line 87
    async def close_all(self) -> None: ...                      # line 102

# packages/ai-parrot-tools/src/parrot_tools/scraping/template_plan.py
class TemplatePlan(BaseModel):                      # line 103
    name: str; objective_template: str; url_template: str
    params: List[ParamSpec] = []
    steps_template: List[Dict[str, Any]] = []
    def bind(self, **kwargs: Any) -> ScrapingPlan: ...           # line 205

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                         # line 216
    auto_open: bool = False                         # line 310
    def __init__(self, **kwargs): ...               # line 312
    async def _open(self) -> None: ...              # line 388
    async def _close(self) -> None: ...             # line 404
    def get_tools(...): ...                         # line 484

# packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py
class ExecutionPlanToolkit(AbstractToolkit):        # line 62
    async def plan_execute(self, objective=None, plan_name=None, params=None) -> ToolResult: ...  # line 432
    async def plan_validate(self, objective=None, plan_name=None, params=None) -> ToolResult: ... # line 462
    async def plan_status(self, run_id: str) -> ToolResult: ...  # line 385
    async def plan_artifacts(self, run_id: str) -> ToolResult: ...# line 408

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):              # line 54
    async def create_wiki(self, wiki_name: str, description: Optional[str] = None) -> dict[str, Any]: ...  # line 544
    def _config_for(self, wiki_name: str) -> WikiConfig:         # line 1378  ← RE-VERIFIED, see note
#   Raises ValueError ONLY when the name is neither the configured wiki NOR a
#   registered FEAT-450 namespace:
#       if wiki_name != self._config.wiki_name and not self._is_namespace(wiki_name):
#   Docstring: "The config object is per-toolkit, so a namespace resolves to the
#   SAME config — namespace dispatch is a *store* concern, handled by
#   _store_for / _search_for."

# packages/ai-parrot/src/parrot/tools/obsidian.py
class ObsidianToolkit(AbstractToolkit):             # line 78
    def __init__(self, vault_path=None, backend: Literal["local","rest"]="local",
                 vault=None, allowed_operations=None, **backend_kwargs) -> None: ...  # line 127

# packages/ai-parrot/src/parrot/auth/broker.py
class CredentialBroker:                             # line 326
    #   result = await broker.resolve(provider, surface, user)   (docstring usage)
class _VaultStaticKeyResolver(CredentialResolver): ...  # line 276

# packages/ai-parrot/src/parrot/interfaces/google.py
DEFAULT_SCOPES['calendar'] = [...calendar, .readonly, .events]   # lines 57-61
'calendar': 'v3'                                                  # line 720
async def get_calendar_client(self, version: str = 'v3') -> Dict[str, Any]:  # line 760
    return {'service': 'calendar', 'version': version}            # line 762  ← config dict, NOT a client

# packages/ai-parrot-loaders/src/parrot_loaders/excel.py
class ExcelLoader(AbstractLoader):                  # line 21
    output_mode: Literal["sheet","row"] = "sheet"   # line 56

# packages/ai-parrot/src/parrot/auth/confirmation.py
class ConfirmationGuard:                            # line 378
    """The Governor: asks a human to confirm each marked tool call.
    Wired into ToolManager via set_confirmation_guard(), invoked in
    execute_tool() AFTER the grant check and BEFORE tool.execute().
    Lifecycle: non-confirmation tool -> allow; within confirm_window_seconds
    for same args_hash -> allow; NO human_manager -> DENY (fail-closed,
    'cancelled'); else build briefing -> ask HITL -> map to decision."""
    def __init__(self, store: ConfirmationWindowStore,
                 human_manager: Optional["HumanInteractionManager"] = None,
                 config: Optional[ConfirmationConfig] = None) -> None: ...  # line 401
    async def confirm(self, *, tool: "AbstractTool", parameters: dict,
                      permission_context: Optional["PermissionContext"] = None
                      ) -> ConfirmationDecision: ...                        # line 418

# packages/ai-parrot/src/parrot/human/channels/base.py
class HumanChannel(ABC):                            # line 47
    async def start(self) -> None: ...              # line 83
    async def stop(self) -> None: ...               # line 90
    async def send_interaction(...) -> ...          # line 100
    async def send_notification(...) -> ...         # line 119
    async def cancel_interaction(...) -> ...        # line 132
    async def register_response_handler(...) -> ... # line 151
    async def register_cancel_handler(...) -> ...   # line 162

# packages/ai-parrot-tools/src/parrot_tools/scraping/flow_executor.py — checkpoints (D3)
def _checkpoint_token(global_params: Dict[str, Any]) -> str:   # line 271
    #   sha256(json.dumps(global_params, sort_keys=True))[:8]
    #   "Distinct parameter sets get distinct checkpoint files ... while an
    #    identical parameter set resolves deterministically — which is what
    #    resume_from relies on."   <-- THE HAZARD D3 addresses
def _checkpoint_path(self, flow, token) -> Optional[Path]:     # line 282
    #   {checkpoint_dir}/{flow.name}.{token}.checkpoint.json
async def _write_checkpoint(self, flow, token, node_results) -> Optional[str]:  # line 290
    #   Persists ONLY result.extracted_data (bs_soup not serializable,
    #   content too large). Resumed nodes expose extracted_data only.

# packages/ai-parrot-integrations/.../whatsapp/bridge_config.py
class WhatsAppBridgeConfig:                         # line 9
    name: str; chatbot_id: str
    bridge_url: str = "http://localhost:8765"
    allowed_numbers: Optional[List[str]] = None     # line 31  ← financial control
```

> **Contract note — a stale reference corrected.** The merged FEAT-452
> `TASK-2379` artifact cites `_config_for` at `wiki/toolkit.py:1205` and states
> that passing another wiki name "will raise". Re-verification puts it at
> **line 1378**, and the FEAT-450 merge made the guard conditional: a
> *registered namespace* name no longer raises. A separate storage **plane**
> still requires its own `LLMWikiToolkit` instance; a namespace **query** does
> not. Module 10 must follow the corrected behaviour, not the task doc.

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `session_actions.exec_*` | `AbstractDriver` | method calls | `drivers/abstract.py:37-337` |
| `executor._dispatch_step` | `session_actions.exec_*` | direct call, replaces stub | `executor.py:298-311` |
| `tool._execute_step` | `session_actions.exec_*` | delegation | `tool.py:689-760` |
| `exec_authenticate` | `CredentialBroker.resolve()` | await call | `auth/broker.py:326` |
| `BusinessAutomationToolkit` | `FlowExecutor.run()` | await call | `flow_executor.py:338` |
| `BusinessAutomationToolkit` | `TemplatePlan.bind()` | call | `template_plan.py:205` |
| `BusinessAutomationToolkit` | `AbstractToolkit._open/_close` | override | `tools/toolkit.py:388,404` |
| `ingest.py` | `ExecutionPlanToolkit.plan_execute()` | await call | `execution_plan/toolkit.py:432` |
| `ingest.py` | `ExcelLoader(output_mode="row")` | constructor | `parrot_loaders/excel.py:56` |
| `memory.py` | `LLMWikiToolkit.create_wiki()` | await call | `wiki/toolkit.py:544` |
| `calendar.py` | `GoogleClient.get_calendar_client()` | await call | `interfaces/google.py:760` |

### Does NOT Exist (Anti-Hallucination)

Verified absent across `packages/*/src` on the current `dev`:

- ~~`HoobaToolkit`~~ — no such class anywhere. This spec does **not** create one in-repo.
- ~~`BrowserAutomationToolkit`~~ — the proposal's working name; the real deliverable is `BusinessAutomationToolkit` (Module 5).
- ~~`GoogleCalendarToolkit`~~, ~~`create_event`~~, ~~`list_events`~~ — **zero** hits. `parrot_tools/google/` contains only `base.py`, `places.py`, `tools.py` (search / places / maps); `grep -ci calendar` on `google/tools.py` returns **0**.
- ~~`AgentsFlow.as_tool()`~~ — does not exist. `AgentsFlow` is `AgentsFlow(PersistenceMixin)` (`flow/flow.py:217`), **not** an `AbstractBot`; `AgentTool.__init__` requires `AbstractBot` (`tools/agent.py:52`). Only `Agent.as_tool()` exists (`bots/agent.py:961`). Use `ExecutionPlanToolkit.plan_execute` instead.
- ~~`apscheduler` in ai-parrot core~~ — the extra is **commented out** at `packages/ai-parrot/pyproject.toml:254`; `parrot/scheduler/__init__.py` is a lazy satellite shim. Module 8 changes this deliberately — see §7 Decision D1.
- ~~a `gestoria` wiki namespace~~ — `wikitoolkit ns list` shows only `notes`. Module 10 + AC-14 create it.
- ~~`SubmitGateFn`~~, ~~`SubmitGateDecision`~~, ~~`NotifierFn`~~ — these appeared in this spec's **first draft** and were **removed at v0.2**. They duplicated the shipped HITL stack. Use `ConfirmationGuard`, `HumanInteractionManager`, `HumanChannel`, `ConfirmationDecision` and `InteractionResult` instead (Decision D2). Do not resurrect them.

---

## 7. Implementation Notes & Constraints

### Decision D1 — Reactivating `apscheduler` in core partially reverses FEAT-203

FEAT-203 deliberately moved task scheduling out of `ai-parrot` into
`ai-parrot-server[scheduler]`; the core extra is commented out
(`pyproject.toml:253-254`, *"use ai-parrot-server[scheduler] instead"*) and
`parrot/scheduler/__init__.py` is a shim that lazily loads
`AgentSchedulerManager` from the satellite.

The alternative — depending on the `ai-parrot-server` package without deploying
its HTTP layer — was offered and **not** chosen. The operator's decision is to
reactivate the extra and provide a lightweight in-process scheduler in core, so
an agent process can schedule reminders without taking a dependency on the
server distribution at all.

Constraints this imposes on Module 8:
- The new class is `InProcessScheduler` in `parrot/scheduler/inprocess.py`. It
  **must not** be named or exported such that it shadows `AgentSchedulerManager`,
  `ScheduleType`, `schedule`, `schedule_daily_report` or
  `schedule_weekly_report` — those five stay satellite-delegated through the
  existing `__getattr__`. AC-11 tests exactly this.
- The reactivated extra must pin the same version the satellite uses
  (`apscheduler==3.11.2`) to avoid a split-brain dependency.
- `packages/ai-parrot/pyproject.toml` must carry a comment explaining that this
  reverses part of FEAT-203 by decision, referencing FEAT-453, so the next
  reader does not "fix" it back.

### Decision D2 — The SUBMIT gate reuses the shipped HITL stack; no bespoke gate

This spec's first draft invented `SubmitGateFn` / `SubmitGateDecision` /
`NotifierFn`. They duplicate machinery that already ships, and are removed.

The gate is **two-tier**, because the human is in Telegram and not watching Chrome:

1. **Tool-call boundary (primary).** `ConfirmationGuard` (`auth/confirmation.py:378`)
   is wired into `ToolManager` via `set_confirmation_guard()` and fires in
   `execute_tool()` after the grant check, before `tool.execute()`. Module 5
   marks `run_operation` as a confirmation tool via `routing_meta` when the
   resolved operation is `OperationKind.SUBMIT`. The guard renders a briefing
   of the bound parameters and asks over HITL. **It fails closed**: with no
   `human_manager` the decision is `cancelled` — which is exactly the posture a
   financial write needs, and it means the gate cannot be bypassed by omitting
   configuration.
   - **`confirm_window_seconds` MUST be 0 for SUBMIT operations.** The guard's
     normal behaviour allows a repeat call with the same `args_hash` inside the
     window without re-asking. For "issue this invoice" that would silently
     approve a duplicate filing. AC-8b tests it.
2. **Mid-plan (secondary).** `exec_await_human` takes an injected
   `HumanChannel` (resolved through `ChannelRegistry`; `TelegramHumanChannel` is
   contributed lazily by ai-parrot-integrations). `condition_type="manual"` has
   no DOM condition to poll and therefore **requires** a channel — with none it
   fails closed rather than blocking for its 300s timeout. The DOM-based
   condition types keep polling but also emit `send_notification()` so the
   operator learns the browser is waiting.

### Decision D3 — Checkpoint location, discrimination and retention

Grounded in `flow_executor.py:271-315`: the checkpoint path is
`{checkpoint_dir}/{flow.name}.{token}.checkpoint.json` where `token` is
`sha256(global_params)[:8]`, and only `extracted_data` is persisted.

- **Location**: `${PARROT_STATE_DIR}/business_automation/checkpoints/<operation>/`.
  Not `/tmp` — a quarterly import may span days and must survive a reboot. Not
  the plans directory — plans are read-only and may be version-controlled.
- **Discrimination (the hazard)**: the token is derived from parameters *only*.
  Two legitimate imports of different statements for the same period would
  produce the **same** token, so the second would resume the first's checkpoint
  and skip every row it thinks is done. Module 9 therefore injects
  `ImportRun.statement_digest` into `global_params`. AC-12a tests it.
- **Retention**: a checkpoint for a financial import is a record of what was
  already written to Hooba. Deleting it early causes **duplicate expense
  registration** on the next resume. Delete only after the run reports success
  *and* reconciliation confirms the row count. Otherwise keep, bounded at
  **90 days** (a quarterly cycle plus margin), then archive-and-alert — never
  silently drop.
- **Confidentiality**: checkpoints contain client names and amounts extracted
  from an accounting system. Directory `0700`, files `0600`, and the path MUST
  lie outside the Obsidian vault and every wiki storage root — both of those
  are mirrored/ingested surfaces. AC-12b tests it.

### Decision D4 — The smoke check splits along the same public/private seam

The *mechanism* is generic and public: `SmokeCheck` in
`business_automation/smoke.py`, run by Module 8's scheduler, asserting a
READ-kind operation still succeeds and alerting over the configured channel.
The *plan it runs* needs real credentials and real Hooba selectors, so the Hooba
smoke plan is part of Deliverable X. This is the same seam already chosen for
the engine and its plans, applied consistently. The repo tests the mechanism
against the local fixture site (AC-20).

### Patterns to Follow

- **`advanced_actions.py` extraction shape** (Module 1) — standalone async
  functions taking `AbstractDriver` plus a `dispatch_step_fn` callback for
  recursion, consumed by both `executor.py` and `tool.py`. This is the pattern
  FEAT-222 established for `exec_loop`/`exec_conditional`; do not invent another.
- **FEAT-207 shared-state toolkit** — one `AbstractToolkit` instance initialized
  with live dependencies, shared across every tool call.
- **FEAT-391 lazy lifecycle** — `auto_open=True` with `_open`/`_close` for the
  browser session, exactly as `ObsidianToolkit` does for the vault.
- **`run_id` + status polling** — long operations return a `run_id` immediately
  so a Telegram turn is never held open, mirroring `ExecutionPlanToolkit`.
- **FEAT-452 domain-plane recipe** (Module 10) — dedicated
  `_build_<x>_wiki_toolkit()` with its own storage root, PageIndex plane and
  `tenant_id`; idempotent `create_wiki()` in `configure()`; best-effort failure
  leaving the handle `None`; then operator-side `wikitoolkit ns add`.
- **Async-first, Pydantic-modelled, `self.logger`** — project defaults.

### Known Risks / Gotchas

- **`return True` on an unimplemented action is the whole bug.** When writing
  Module 2, resist any "log and continue" fallback. An unknown action must fail
  the step, not pass it. A regression here is invisible in production and
  corrupts accounting records.
- **Hooba DOM churn breaks every TemplatePlan at once.** Mitigation: a scheduled
  smoke `ScrapingFlow` that logs in and performs one read-only navigation,
  alerting over Telegram *before* a real operation fails.
- **Hooba could add MFA/CAPTCHA at any time.** U1 confirms none today, but it is
  a third-party site. Fallback path: `ChromeConfig.user_data_dir` persistent
  profile plus `await_human` on session expiry.
- **Credentials must never enter plan JSON.** `Authenticate.username`/`password`
  remain literal fields for back-compat; the plans directory must be lint-checked
  to ensure they are absent (AC-5/AC-6).
- **Sequential only.** FEAT-222 records fan-out over a shared authenticated
  session as deferred debt. Keep `FlowExecutor(concurrency=1)` for any flow whose
  nodes share a `session` label.
- **FEAT-449 is adjacent, not a source of truth for deadlines.** It models BOE
  *article text in force on a date* with zero LLM involvement — a lawyer's
  question. Filing-calendar dates are an AEAT-calendar concern. Do not wire
  Module 8's reminders to FEAT-449's graph on the assumption it knows when
  modelo 303 is due; it does not.
- **A confirmation window is a duplicate-filing hazard.** `ConfirmationGuard`
  allows a repeat call with the same `args_hash` inside `confirm_window_seconds`
  without re-asking. Convenient for a read tool, dangerous for "issue invoice".
  Set it to 0 for SUBMIT (D2).
- **Checkpoint tokens key on parameters only.** Re-importing a different
  statement for the same period collides unless a content digest is in
  `global_params` (D3). The symptom is silent: rows are skipped, not errored.
- **The plane can be built but unqueryable.** An unregistered `gestoria`
  namespace silently accumulates knowledge nobody can retrieve — the exact
  failure FEAT-452's TASK-2382 was written to prevent. AC-14 guards it.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `apscheduler` | `==3.11.2` | Module 8 in-process scheduler; pinned to the satellite's version (Decision D1) |
| `google-api-python-client` | existing | Module 7 Calendar v3 — already used by `interfaces/google.py` |
| `playwright` | existing | driver backend, unchanged |
| *(none new for Modules 1-6, 9-11)* | — | the engine reuses what is already installed |

---

## 8. Open Questions

### Resolved (carried forward from the proposal and this spec's Q&A)

- [x] **Does `app.hooba.com` enforce MFA/CAPTCHA?** — *Resolved (proposal U1)*: No MFA — unattended login. `authenticate` resolves credentials via `CredentialBroker` and signs in on its own. → drives Module 4, §7 risk.
- [x] **Which WhatsApp transport?** — *Resolved (proposal U2)*: Personal number via the Go whatsmeow bridge (`WhatsAppBridgeWrapper`). Not the Meta Cloud API path. → drives Module 11, §1 Non-Goals.
- [x] **Google Calendar or O365?** — *Resolved (proposal U3)*: Build the Google Calendar tools; promote `get_calendar_client()` to a real client. → drives Module 7.
- [x] **Split FEAT-453, and wait for FEAT-452?** — *Resolved (proposal U4)*: One feature; wiki layer ordered last. *Post-answer note*: FEAT-452 merged (PR #1209), so the layer is no longer blocked — the ordering is now a preference, not a constraint. → drives §3 module order.
- [x] **Autonomy for legally-effective writes?** — *Resolved (proposal U5)*: Drafts unattended; every submit gated behind `await_human`. → drives `OperationKind`, Module 5, AC-8.
- [x] **Where does the Hooba toolkit live?** — *Resolved (this spec)*: Generic engine public in `parrot_tools/business_automation/`; Hooba plans private, outside the repo, loaded from a configurable directory. → drives Modules 5/6, Deliverable X, AC-7/AC-9.
- [x] **Scheduler deployment shape?** — *Resolved (this spec)*: In-process APScheduler in the bot process, **reactivating the core extra** rather than depending on `ai-parrot-server`. Explicitly acknowledged as a partial reversal of FEAT-203. → drives Module 8, Decision D1, AC-11.
- [x] **Which Hooba operations in v1?** — *Resolved (this spec)*: All five — `login`, `create_client`, `register_expense`, `draft_invoice`, `download_invoice_pdf`. → drives Deliverable X, fixtures.

- [x] **What is the submit-gate transport?** — *Resolved (v0.2, Decision D2)*:
  reuse the shipped HITL stack. `ConfirmationGuard` gates `run_operation` at the
  tool-call boundary (fail-closed, `confirm_window_seconds=0`); `exec_await_human`
  takes an injected `HumanChannel` for mid-plan pauses. The draft's
  `SubmitGateFn`/`SubmitGateDecision`/`NotifierFn` are **deleted** — they
  duplicated `ConfirmationDecision` and `InteractionResult`.
- [x] **Where does the checkpoint directory live, and what is its retention?** —
  *Resolved (v0.2, Decision D3)*:
  `${PARROT_STATE_DIR}/business_automation/checkpoints/<operation>/`, 0700/0600,
  outside the vault and every wiki root. Kept until the run is reconciled, bounded
  at 90 days, then archive-and-alert. `ImportRun.statement_digest` goes into
  `global_params` so two imports never share a token.
- [x] **Should the smoke-test flow live in this repo or with the private plans?**
  — *Resolved (v0.2, Decision D4)*: split along the existing seam — `SmokeCheck`
  mechanism public (Module 8 + `smoke.py`), the Hooba smoke plan private
  (Deliverable X). Tested in-repo against the fixture site.

### Unresolved

None. All questions are resolved; the spec is approved for decomposition.

---

## Worktree Strategy

**Isolation unit**: `per-spec` — all tasks run sequentially in one worktree.

Rationale: Modules 1-4 all touch `scraping/` (two of them the same two files),
so parallel worktrees would conflict immediately. Modules 5-11 depend on the
corrected engine. The one genuinely independent module is **Module 7** (Google
Calendar), which touches only `google/` and `interfaces/google.py` — it may be
lifted into a parallel worktree if wall-clock matters, but the coordination cost
is unlikely to pay off for a single operator.

```bash
git worktree add -b feat-453-web-automation-infra \
  .claude/worktrees/feat-453-web-automation-infra HEAD
```

**Cross-feature dependencies**: none blocking. FEAT-450 (wiki namespaces) and
FEAT-452 (audio-notes-obsidian) are both **merged** to `dev` and are consumed,
not awaited. FEAT-449 (legal-norms-graph-boe) is merged but adjacent — not a
dependency.

**Suggested task order**: M1 → M2 → M3 → M4 → M5 → M6 → M9 → M7 → M8 → M10 → M11.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-23 | Jesus Lara | Initial draft from FEAT-453 proposal rev 2; 8 resolved questions carried forward; Decision D1 recorded |
| 0.2 | 2026-08-23 | Jesus Lara | Resolved all 3 open questions (D2 HITL reuse, D3 checkpoints, D4 smoke split); removed invented `SubmitGateFn`/`SubmitGateDecision`/`NotifierFn` in favour of the shipped HITL stack; +6 acceptance criteria, +8 tests; **status → approved** |
