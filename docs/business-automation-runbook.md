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
