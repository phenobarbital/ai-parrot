# Business Automation — Operator Runbook

**Feature**: FEAT-453 — Business Browser Automation
**Audience**: the operator deploying/maintaining a `BusinessAutomationToolkit`-based
agent (the agent itself, and any site-specific plans it drives, live **outside**
this repository — see the spec's public/private seam, §2).

---

## 1. Plans-directory contract

`BusinessAutomationToolkit(plans_dir=...)` and
`PlanDirectoryStore(plans_dir)` load `BusinessOperation` / `TemplatePlan` /
`ScrapingFlow` definitions from a directory **outside this repository** —
credentials and site-specific selectors never enter version control.

File naming convention inside `plans_dir`:

| Suffix | Model |
|---|---|
| `*.operation.json` | `BusinessOperation` |
| `*.template.json` | `TemplatePlan` |
| `*.flow.json` | `ScrapingFlow` |

**The whole directory is rejected on any malformed file** — a bad
`*.operation.json` never silently disappears from the registry; the load
raises, naming the file and the reason. The loader also runs a credential
lint over every `*.template.json`: an `authenticate` step carrying a
literal `password` field rejects the load. Use `credential_provider`
(resolved through a `CredentialBroker`) instead of literal credentials in
any `Authenticate` step.

See `packages/ai-parrot-tools/tests/business_automation/fixtures/acme-books/`
for a complete, anonymized example plans directory.

## 2. Submit-gate policy (Decision D2)

Every `BusinessOperation` declares an `OperationKind`:

- `READ` — never gated.
- `DRAFT` — runs unattended (assembles, does not submit).
- `SUBMIT` — **always** gated behind a human confirmation
  (`ConfirmationGuard`, the same shipped HITL stack used everywhere else in
  this codebase — never a bespoke gate). With no `human_manager` configured,
  a SUBMIT operation is **denied** and the browser is never opened
  (fail-closed). `confirm_window_seconds` is `0` for every SUBMIT
  operation — a repeated identical submit call always re-asks; it is never
  auto-approved by a confirmation-window hit.

**Operator checklist before enabling any SUBMIT-kind operation:**

- [ ] A `HumanChannel` (e.g. Telegram) is wired and reachable.
- [ ] The channel's recipient/allowlist is configured (see §4 below for the
      WhatsApp-specific fail-closed control).
- [ ] The operation's `confirm_prompt` renders a clear, actionable briefing
      (client name, amount, or whatever the human needs to approve safely).

## 2a. Broker-backed login and mid-plan human pauses

`BusinessAutomationToolkit`'s `credential_broker`/`human_channel` constructor
parameters reach every operation's real browser session (code-review
remediation — earlier builds accepted these but never forwarded them to
`FlowExecutor`, so a `credential_provider`-backed `Authenticate` step always
failed closed regardless of configuration):

- `credential_broker`: a `CredentialBroker` (`parrot.auth.broker`). Adapted
  internally into the `(username, password)` shape `Authenticate` steps
  expect — the broker's `ResolvedCredential.secret` may be a
  `{"username", "password"}` dict, a 2-tuple, or a single opaque secret
  (used as the password with no separate username, e.g. an API key).
  `credential_user_id` (default `"gestoria"`) is the canonical identity
  passed to `broker.resolve(provider, "business_automation", user_id)` —
  this is a single-operator agent, not a multi-tenant surface, so a fixed
  identity is deliberate.
- `human_channel`: a `HumanChannel` instance for mid-plan `await_human`
  pauses (e.g. "the site is showing a CAPTCHA, please solve it"). Configure
  a **dedicated** channel instance here — do **not** reuse a channel from
  `human_manager.channels`: `exec_await_human`'s manual-wait path registers
  its own response handler on the channel, which would collide with
  `HumanInteractionManager`'s own registration on the same instance.

Without a `credential_broker`, a `credential_provider`-backed `Authenticate`
still fails closed exactly as before (Decision D2/G3 — never falls back to
literal credentials). Without a `human_channel`, `condition_type="manual"`
`await_human` steps still fail closed immediately rather than hanging.

## 3. Checkpoints and retention (Decision D3)

Checkpoints and import manifests live under:

```
${PARROT_STATE_DIR}/business_automation/checkpoints/<operation>/
```

(`$PARROT_STATE_DIR` defaults to `~/.parrot_state` when unset.) This
directory is **never** inside the Obsidian vault or any wiki storage
root — both are mirrored/ingested surfaces, and a checkpoint contains
client names and amounts extracted from an accounting system.

- Directory mode `0700`, file mode `0600`.
- Two imports of different bank statements for the same accounting
  `period` never collide: `ImportRun.statement_digest` (sha256 of the
  source Excel bytes) is baked into every import's node/working-memory
  identity.
- **Resume without duplicates**: `ExecutionPlanToolkit`'s own flow-level
  checkpointing is deliberately disabled (FEAT-399); per-row resumability
  lives in `ingest.py`'s own manifest instead. Pass
  `make_import_progress_listener(operation, digest)`'s return value as
  `ExecutionPlanToolkit(on_node_event=...)` (or compose it via
  `AgentsFlow.add_node_event_listener`) when running the plan from
  `build_import_plan()` — it records each row's completion into the
  manifest synchronously, so a process kill mid-import leaves every
  already-registered row durably marked done. Re-running
  `build_import_plan()` for the same statement afterward returns a plan
  containing only the remaining rows (`ImportPlanBundle.fully_completed`
  is `True`, `plan is None`, if every row was already done). Skipping this
  listener does not lose data — it only means a naive re-run duplicates
  rows, exactly as before this remediation.
- Retention: **90 days**, then **archive-and-alert** — `sweep_checkpoint_retention()`
  (`parrot.scheduler.inprocess`) moves aged-out checkpoints to an
  `archive/` subdirectory and notifies the configured `HumanChannel`. It
  **never** deletes silently. Confirm reconciliation (rows imported vs.
  registrations completed) before removing anything from the archive
  by hand.

## 4. WhatsApp channel — a financial control, not a convenience

When the agent exposes any `OperationKind.SUBMIT` operation over the
WhatsApp bridge (`WhatsAppBridgeConfig`), `allowed_numbers` **must** be a
non-empty allowlist. An empty allowlist with SUBMIT operations exposed is
a fail-closed condition — the bridge refuses to start rather than accept
financial-write commands from an unauthenticated sender. See TASK-2397 /
`packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/bridge_config.py`.

**This is a security boundary, not a UX nicety.** `WhatsAppBridgeWrapper.__init__()`
detects whether the bound agent has a registered `BusinessAutomationToolkit`
exposing at least one `OperationKind.SUBMIT` operation (walking the agent's
`ToolManager`, the same way `ToolManager.cleanup_toolkits()` already does);
if so, and `allowed_numbers` is empty/`None`, construction raises `ValueError`
naming the wrapper's `name`/`chatbot_id` — the operator sees exactly which
config is unsafe, instead of the bridge silently accepting instructions from
any WhatsApp number. Bots with no SUBMIT-kind operations exposed are
completely unaffected — the permissive "empty = all" default from before
TASK-2397 is preserved for them.

**Install `ai-parrot-integrations[business-automation]`.** The detection
above imports `parrot_tools.business_automation` (a deferred, guarded
import — `ai-parrot-tools` is not a hard dependency of
`ai-parrot-integrations`, matching the "satellites depend only on core"
convention). If `ai-parrot-tools` is not installed, the check cannot see
any `BusinessAutomationToolkit` and therefore cannot detect a SUBMIT
operation — which is safe *only* because a `BusinessAutomationToolkit`
cannot exist without that package installed in the first place. Still,
**always install this extra** when running a `BusinessAutomationToolkit`-backed
agent over WhatsApp, so this is a verified guarantee rather than an
accident of the deployment's package set:

```bash
pip install "ai-parrot-integrations[business-automation]"
```

Numbers (both the configured allowlist and each incoming sender) are
normalized to digits-only before comparison
(`WhatsAppBridgeConfig.normalized_allowed_numbers`) — `+34 600 11 22 33` and
`34600112233` are the same allowlist entry.

## 5. The `gestoria` wiki plane — one-off registration step

`build_gestoria_wiki()` (`parrot_tools.business_automation.memory`)
constructs a **dedicated** `LLMWikiToolkit` instance for the `gestoria`
plane: its own storage root, its own PageIndex authoring plane, its own
GraphIndex tenant (`tenant_id="gestoria"`). Building the plane does **not**
make it queryable — an unregistered namespace silently accumulates
knowledge that `wikitoolkit query` can never surface (the exact failure
FEAT-452's TASK-2382 was written to prevent).

**This is deliberately an operator step, never agent code** (FEAT-452
non-scope: no code in this repository auto-registers a namespace).

### One-time setup

```bash
# Registers the gestoria storage root as a queryable namespace.
wikitoolkit ns add gestoria --kind store \
  --path "${GESTORIA_WIKI_STORAGE_DIR:-$HOME/.parrot/wikis/gestoria}"

# Verify registration:
wikitoolkit ns list
# → should list "gestoria" alongside any other registered planes.
```

### Seeding and verifying the plane

After the agent has recorded at least one operation (via
`record_operation_page()`), confirm the plane is actually queryable:

```bash
wikitoolkit query --ns gestoria "register_expense"
# → should return the seeded operation-record page(s).
```

If this returns nothing after operations have run, the namespace was
never registered — repeat the `wikitoolkit ns add` step above. Do **not**
attempt to fix this by adding registration code to the agent; that is an
explicit non-goal (see FEAT-452, and this task's own Codebase Contract).

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `GESTORIA_WIKI_NAME` | `gestoria` | Wiki/namespace name |
| `GESTORIA_WIKI_STORAGE_DIR` | `~/.parrot/wikis/gestoria` | Storage root (distinct from every other wiki plane) |
| `GESTORIA_FOLDER` | `gestoria` | Obsidian vault subfolder for the mirror |
| `GESTORIA_WIKI_LLM` | inherits `WIKI_MODEL` or `anthropic:claude-haiku-4-5` | PageIndex authoring-plane model |

## 6. Google Calendar reminders

`InProcessScheduler` (`parrot.scheduler.inprocess`, reactivating the core
`scheduler` extra by deliberate FEAT-453/Decision D1 exception) schedules
tax-calendar reminders via `schedule_tax_reminder()`. Supply your own
`TaxDeadline` instances from your own AEAT-calendar source of truth — this
repository does not hardcode Spanish filing dates (FEAT-449 is adjacent,
not authoritative, for deadlines).

## 7. Scheduled canary (`SmokeCheck`, Decision D4)

Register one `SmokeCheck` per site against a `READ`-kind operation (e.g. a
login + dashboard read). `register_smoke()` refuses at registration time
— before any job is scheduled — to accept a `DRAFT` or `SUBMIT` operation;
a canary must never write. A failing canary alerts over the configured
channel, naming the operation, the failing node, and the error — so DOM
drift on the target site is caught before a real write fails half-way.

The Hooba (or equivalent) canary *plan* itself is out of repo (Deliverable
X) — only the mechanism ships here.
