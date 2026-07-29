---
type: Wiki Overview
title: FEAT-258 — JiraSpecialist Webhook Transition Detection
id: doc:sdd-proposals-jiraspecialist-webhooks-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The Jira webhook infrastructure already exists and is receiving events at
---

---
id: FEAT-258
title: "JiraSpecialist webhook transition detection — trigger agent actions on Jira status changes"
slug: jiraspecialist-webhooks
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-24
  summary_oneline: "Use Jira webhooks to detect ticket transitions and trigger agent actions"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-258/
created: 2026-06-24
updated: 2026-06-24
---

# FEAT-258 — JiraSpecialist Webhook Transition Detection

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — "Using the same approach as the GitHub Reviewer Agent, use
> Jira webhooks to know when a ticket is transitioned, useful to trigger things
> from the Agent"
> **Audit**: [`sdd/state/FEAT-258/`](../state/FEAT-258/)

---

## 0. Origin

> Using the same approach as the GitHub Reviewer Agent, use the Jira webhooks
> to know when a ticket is transitioned, useful to trigger things from the Agent.

**Initial signals**:
- Verbs: "transitioned", "trigger" → enrichment / new capability
- Named entities: "JiraSpecialist", "GitHub Reviewer Agent", "Jira webhooks"
- Pattern reference: GitHub Reviewer Agent webhook flow as the model to follow
- Acceptance criteria provided: no (implied: transition detection + action triggering)

---

## 1. Synthesis Summary

The Jira webhook infrastructure already exists and is receiving events at
`POST /api/v1/hooks/jira` via `JiraWebhookHook`. However, the event
classifier (`_classify_event`) only recognizes three specific status
transitions (`closed`, `ready_for_test`, plus the catch-all `updated`), and
`JiraSpecialist.handle_hook_event()` only routes three event types
(`jira.created`, `jira.assigned`, `jira.ready_for_test`). All other status
changes are classified as `"updated"` and silently ignored. This proposal
adds a new `jira.transitioned` event type emitted for **every** status change
(with `from_status` and `to_status` in the payload), a configurable
transition-to-action registry on `JiraSpecialist`, and built-in action
handlers for common use cases — mirroring how `GitHubReviewer` dispatches
webhook events to review/notify actions.

---

## 2. Codebase Findings

> All entries grounded in research findings at `sdd/state/FEAT-258/findings/`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py` | `_classify_event` | 122-149 | Event classifier — hardcodes `closed`/`ready_for_test`; all other status changes fall to `"updated"` | F001 |
| 2 | `packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py` | `_handle_post` | 49-109 | Webhook POST handler — builds payload but missing `from_status`/`to_status` fields | F001 |
| 3 | `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | `handle_hook_event` | 1096-1121 | Event router — only routes 3 event types; ignores `jira.updated` | F002 |
| 4 | `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | `handle_ready_for_test` | 1405-1504 | Existing transition handler — sends Telegram notification on ready_for_test | F002 |
| 5 | `packages/ai-parrot/src/parrot/core/hooks/models.py` | `JiraWebhookConfig` | 110-118 | Config model — will need `transition_actions` field | F003 |
| 6 | `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | `handle_hook_event` | 755-773 | Reference pattern — filters events by type, guards on repository, dispatches to handler | F004 |
| 7 | `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | `setup_webhook_route` | class method | Reference pattern — webhook route setup + fan-out dispatcher for multi-agent scenarios | F004 |
| 8 | `packages/ai-parrot/src/parrot/core/hooks/base.py` | `BaseHook` | 96-182 | Hook base class — interface is sufficient, no changes needed | F005 |
| 9 | `packages/ai-parrot/src/parrot/core/hooks/manager.py` | `HookManager` | full | Event dispatch + optional EventBus dual-emit — no changes needed | F005 |

### 2.2 Constraints Discovered

- **Backward compatibility with existing handlers.** Three handlers
  (`handle_jira_ticket_created`, `handle_jira_assignment`,
  `handle_ready_for_test`) already work in production. The `ready_for_test`
  handler specifically relies on the current classification returning
  `"ready_for_test"` when the status matches. Any refactor must preserve this
  behavior.
  *Implication*: the new `"transitioned"` event should be emitted **in
  addition to** the existing specific event types, not as a replacement.
  *Evidence*: F001, F002

- **Payload structure is consumed by orchestrator.** The
  `AutonomousOrchestrator._handle_hook_event()` reads `event_type`,
  `target_type`, `target_id` from `HookEvent`. New payload fields
  (`from_status`, `to_status`) are additive and safe.
  *Evidence*: F005

- **Static method constraint on `_classify_event`.** The classifier is a
  `@staticmethod` — it cannot access instance config. To keep it static (no
  instance state = testable + predictable), the decision about which
  transitions to route must live in the consumer (`JiraSpecialist`), not the
  hook.
  *Evidence*: F001

- **GitHub Reviewer pattern uses agent-level filtering.** `GitHubReviewer`
  filters by event type AND repository in `handle_hook_event()` — the hook
  emits all PR events, and the agent decides what to act on. Same principle
  should apply: `JiraWebhookHook` emits all transitions, `JiraSpecialist`
  decides what to do.
  *Evidence*: F004

### 2.3 Recent History (Relevant)

The `jira_webhook.py` and `jira_specialist.py` files were last significantly
modified for FEAT-110 (auto-reassignment on ticket creation). The hook
infrastructure (`base.py`, `manager.py`, `models.py`) was established for the
GitHub Reviewer feature and extended for Jira in the same period. No recent
churn on these files.

---

## 3. Probable Scope

### What's New

- **`jira.transitioned` event type** — emitted by `JiraWebhookHook` for
  every status change detected in the changelog, carrying `from_status` and
  `to_status` in the payload.

- **`TransitionAction` model** — Pydantic model defining a transition→action
  mapping: `from_status` (optional wildcard), `to_status`, `action_type`
  (enum: `notify_channel`, `trigger_agent`, `call_handler`, `log`),
  `action_config` (dict with action-specific params).

- **Transition action registry** on `JiraSpecialist` — a list of
  `TransitionAction` entries (configured via `JiraWebhookConfig` or env
  var) that `handle_hook_event` consults when receiving `jira.transitioned`.

- **Built-in action handlers**:
  - `notify_channel(payload, config)` — send a formatted Telegram message
    to a configured channel (generalizes `handle_ready_for_test`).
  - `trigger_agent(payload, config)` — create an `ExecutionRequest` to
    invoke another agent with the transition context.
  - `log_transition(payload, config)` — structured log entry for audit
    trail (always runs, even without config).

### What Changes

- **`_classify_event()`** — when a status change is detected in the
  changelog, return `"transitioned"` instead of `"updated"` (except for the
  two existing special cases: `"closed"` and `"ready_for_test"` which keep
  their current classification for backward compatibility).
  *Evidence*: F001

- **`_handle_post()`** — extract `from_status` and `to_status` from the
  changelog `items` array when the event involves a status field change.
  Add both to `event_payload`.
  *Evidence*: F001

- **`handle_hook_event()`** — add a `jira.transitioned` branch that
  iterates the transition action registry, matches `(from_status,
  to_status)` against each `TransitionAction`, and invokes the
  corresponding handler.
  *Evidence*: F002

- **`JiraWebhookConfig`** — add optional `transition_actions:
  List[TransitionAction]` field (default empty list).
  *Evidence*: F003

### What's Untouched (Non-Goals)

- **Existing `jira.created` / `jira.assigned` / `jira.ready_for_test`
  handlers** — these continue to work exactly as today. The
  `ready_for_test` handler remains the canonical implementation for that
  specific transition; `jira.transitioned` is an additional, parallel event.

- **Jira-side webhook subscription management** — webhook registration in
  Jira remains manual (same as GitHub webhooks when no admin PAT is
  configured).

- **Two-way sync** — this proposal only covers Jira→Agent direction.
  Agent→Jira actions (transitions, comments) already work via `JiraToolkit`
  and are out of scope.

- **`BaseHook` / `HookManager` changes** — the existing hook infrastructure
  is sufficient.

### Patterns to Follow

- **GitHubReviewer's `handle_hook_event`** — filter by event type, guard
  on context (repository in GitHub's case, project_key in Jira's), dispatch
  to handler. *Evidence*: F004

- **`handle_ready_for_test`** as a reference for transition notification
  handlers — reads payload fields, formats a Telegram message, sends via
  wrapper. *Evidence*: F002

- **`HookEvent` + `_make_event` pattern** — the hook creates a `HookEvent`
  with `event_type=f"jira.{type}"`, enriched payload, and a human-readable
  `task` string. *Evidence*: F001, F005

### Integration Risks

- **Double-firing for `ready_for_test` / `closed`**: these transitions
  currently emit their own event type. After this change, they'll also
  trigger a `jira.transitioned` event. The consumer must ensure it doesn't
  handle the same transition twice.
  *Mitigation*: In `_classify_event`, keep returning `"ready_for_test"` /
  `"closed"` for those specific statuses (no `"transitioned"` emitted for
  them). Alternatively, emit both and let `handle_hook_event` deduplicate.
  The simpler approach (keep specific types, don't also emit transitioned)
  is recommended.

- **Wildcard transition actions matching too broadly**: a `from_status: *`
  action could fire on every status change, creating noise.
  *Mitigation*: require at least one of `from_status` or `to_status` to be
  non-wildcard. Log a warning during config validation if both are `*`.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `_classify_event` collapses all non-closed/non-ready_for_test status changes to `"updated"` | F001 | high | Direct read of code at lines 141-148 |
| C2 | `handle_hook_event` ignores `jira.updated` events (logs + returns None) | F002 | high | Direct read of code at lines 1116-1121 |
| C3 | Jira changelog includes `from`/`to` status in `items` array | F001 | high | Jira webhook payload format is documented; code already reads `toString` at line 142 |
| C4 | `GitHubReviewer.handle_hook_event` pattern is the reference architecture | F004 | high | Explicitly requested by the user; code confirms the pattern |
| C5 | Existing 3 handlers won't break if `"transitioned"` is emitted for other statuses | F001, F002 | high | They route on specific event_type strings, not on `"transitioned"` |
| C6 | `HookManager` + `AutonomousOrchestrator` require no changes | F005 | high | They're event-type agnostic — any `HookEvent` flows through |
| C7 | `TransitionAction` config can live on `JiraWebhookConfig` | F003 | medium | Config model is a Pydantic BaseModel; adding a field is safe. Alternative: env-var-based config on `JiraSpecialist.__init__` |

Distribution: **6** high, **1** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

*None — the codebase provided all necessary context.*

### Unresolved (defer to spec / implementation)

*None — all claims are high-confidence.*

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-258`** — *Rationale*: all code locations are identified with
high confidence, the pattern to follow (`GitHubReviewer`) is well-established
in this codebase, there are no architectural forks to explore, and no open
questions remain. The spec can define the `TransitionAction` model, the
classification changes, and the handler registry in detail.

### Alternatives

- **`/sdd-brainstorm FEAT-258`** — if you want to explore whether the
  action dispatch should use an `EventBus` pub/sub pattern instead of a
  direct registry, or whether transition actions should be defined in a
  YAML config file vs. Pydantic models in code.
- **`/sdd-task FEAT-258`** — not recommended; this involves changes to 3+
  files across hooks and bots, with a new model and registry — too much for
  a single task.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-258/state.json` |
| Source (raw) | `sdd/state/FEAT-258/source.md` |
| Synthesis (JSON) | `sdd/state/FEAT-258/synthesis.json` |

**Budget consumed**:
- Files read: 8 / 40
- Grep calls: 12 / 25
- Git calls: 0 / 10
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (adding new capability
to existing infrastructure, not investigating a bug).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Operator | Claude (Opus 4.6) |
