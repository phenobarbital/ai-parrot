# Brainstorm: Dev-Loop Orchestration with Claude Code Subagent Mirror

**Date**: 2026-04-27
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A — Thin Dispatcher over `ClaudeAgentClient`

---

## Problem Statement

The development feedback loop for "small operational fixes" today is entirely
manual:

1. Bug detected (typically a Flowtask YAML/JSON file producing an incorrect
   result, an integration that drifted, or a regression introduced by a
   schema change).
2. A human pulls logs from CloudWatch / Elasticsearch, identifies the cause,
   and writes a Jira ticket with reproduction steps and acceptance criteria.
3. A human writes (or stitches together from past PRs) the spec for the fix.
4. A human creates a worktree, implements the fix, runs `flowtask <task>`
   locally to verify behavior, and runs lint.
5. A human pushes the branch, opens a PR, and waits for review.

For "tonta-but-time-consuming" fixes (single-file YAML/JSON tweaks, missing
field mappings, off-by-one in a transformation, etc.) this workflow consumes
hours per ticket and gates more interesting work behind triage queue.

We already have most of the building blocks:

- **AI-Parrot agents** can read SaaS systems via toolkits (`JiraToolkit`,
  `CloudWatchTool`, `ElasticsearchTool`, `WorkdayToolkit`, `SlackToolkit`).
- **`AgentsFlow` + FSM transitions** can model the multi-step state machine.
- **`AutonomyOrchestrator` + Redis Streams** publishes events for
  observability and externally-triggered runs.
- **FEAT-124 (in progress)** is adding `ClaudeAgentClient` — a wrapper
  around `claude-agent-sdk` that exposes `ask` / `ask_stream` / `invoke` /
  `resume` against `query()` / `ClaudeSDKClient`.
- **SDD slash commands** (`/sdd-spec`, `/sdd-task`, `/sdd-done`) and
  `sdd-worker` subagent already implement the codebase-aware portion of the
  workflow when a human invokes them in Claude Code.
- **Worktree-per-feature** isolation is already supported by `sdd-task`,
  including non-colliding branch names.

What is missing is the **orchestration layer** that mirrors each AI-Parrot
node onto a Claude Code subagent dispatch:

- The AI-Parrot side owns SaaS integrations, credentials, and the flow
  state machine.
- The Claude Code side owns the codebase (read, grep, edit, run tests,
  commit) inside a controlled worktree.
- A thin dispatcher between them carries a Pydantic-validated brief, runs
  the right subagent under the right permission profile, pumps the
  stream-json output to Redis for observability, and returns a
  Pydantic-validated result.

This brainstorm explores how to build that orchestration cleanly on top of
FEAT-124 without duplicating SDK access.

---

## Constraints & Requirements

- **C1 — Build on FEAT-124, do not bypass it.** All Claude Code SDK access
  must go through `parrot.clients.ClaudeAgentClient` once it is merged.
  Any extension to that client lives in FEAT-124 (or a follow-on FEAT-124.x),
  not in this feature.
- **C2 — Five-node mirror flow.** The flow has exactly five nodes:
  `BugIntakeNode`, `ResearchNode`, `DevelopmentNode`, `QANode`,
  `DeploymentHandoffNode`. Only `ResearchNode`, `DevelopmentNode`, and
  `QANode` dispatch to Claude Code. The other two are pure AI-Parrot.
- **C3 — Fresh session per node, persistent client within node.** Between
  nodes the only carriers of state are (a) artifacts on disk in the
  worktree (spec, code, test output) and (b) the ticket in Jira.
  `ClaudeSDKClient` instances are not reused across nodes.
- **C4 — Service-account Jira credentials.** All comments, attachments, and
  transitions written by the flow use a dedicated service account
  (`flow-bot@company`), bypassing FEAT-083's OAuth 3LO flow via
  `StaticCredentialResolver`. The ticket's reporter and assignee remain
  the original human.
- **C5 — Convention over configuration for subagents.** Each node defaults
  to a named SDD subagent (`sdd-research`, `sdd-worker`, `sdd-qa`); a flag
  on the dispatch profile permits falling back to a generic session with
  an explicit `system_prompt` for one-off / debug dispatches.
- **C6 — Acceptance criteria as structured contract.** The bug brief carries
  a list of `AcceptanceCriterion` objects with a discriminated `kind`
  (`flowtask | shell | pytest | http_check`). The QA node executes them
  deterministically (subprocess + exit code), not via LLM judgment. v1
  implements `flowtask` and `shell`; the other kinds are extensible
  without flow changes.
- **C7 — Dual-stream observability with WebSocket multiplexer.** Each
  dispatch publishes its raw stream-json to a per-dispatch Redis Stream
  (`flow:{run_id}:dispatch:{node_id}`). Flow lifecycle events go to a
  separate stream (`flow:{run_id}:flow`). An aiohttp WebSocket handler
  multiplexes both for the UI; the frontend never speaks Redis.
- **C8 — Two-level concurrency control.** A global semaphore on the
  dispatcher caps concurrent Claude Code sessions
  (`CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES`, default 3). A flow-level
  semaphore on `AutonomyOrchestrator` caps concurrent flow runs
  (`FLOW_MAX_CONCURRENT_RUNS`, default 5). The two are orthogonal because
  one flow run has multiple sequential dispatches.
- **C9 — Worktree lifecycle is external to the flow.** The `ResearchNode`
  creates the worktree (via `/sdd-task` inside the Claude Code dispatch).
  Cleanup happens either (a) when the human runs the existing `sdd-done`
  command after PR merge to `main` (which itself merges to `dev`), or
  (b) automatically via an `AutonomyOrchestrator` GitHub webhook handler
  on `pull_request.closed`. The flow does not delete worktrees.
- **C10 — One human gate at the end.** The flow terminates at PR creation
  and Jira transition to "Ready to Deploy". Merging the PR is always a
  human action (the repo has voting rules that require human approvals).
- **C11 — Asyncio-first, Pydantic v2, navconfig.** All new code follows the
  AI-Parrot conventions: async methods, Pydantic models for all
  contracts, configuration via `parrot.conf`.
- **C12 — Out of scope (explicit).** Retry semantics on QA failure;
  automatic PR merge or voting bypass; Telegram HITL escalation; Knative
  microservice deployment of the dispatcher; in-process MCP server
  migration; multi-repo support (single-repo only for v1).

---

## Options Explored

### Option A: Thin Dispatcher over `ClaudeAgentClient` (FEAT-124-based)

A new `parrot/flows/dev_loop/dispatcher.py` module exposes
`ClaudeCodeDispatcher`, a class that:

- Receives a `ClaudeCodeDispatchProfile` (declarative: subagent name,
  `allowed_tools`, `permission_mode`, `setting_sources`, timeout) plus a
  `cwd` (worktree path) and a Pydantic input model.
- Resolves a `ClaudeAgentClient` via `LLMFactory.create("claude-agent:...")`.
- Acquires a slot in the global `asyncio.Semaphore`.
- Calls `ClaudeAgentClient.ask_stream()` with options derived from the
  profile, iterating over the async stream.
- Each event from the stream is re-published to
  `flow:{run_id}:dispatch:{node_id}` in Redis with a structured envelope.
- The final `ResultMessage` payload is validated against the expected
  Pydantic output model and returned.
- All steps are written to `JournalWriter` for audit.

The five flow nodes (`BugIntakeNode`, `ResearchNode`, `DevelopmentNode`,
`QANode`, `DeploymentHandoffNode`) live in
`parrot/flows/dev_loop/nodes/`. Only the three middle nodes call the
dispatcher; the other two are pure AI-Parrot using `JiraToolkit` and the
existing toolkits.

A `FlowStreamMultiplexer` (aiohttp WebSocket handler) subscribes to both
Redis streams, merges them by timestamp, and projects to a unified UI
envelope.

✅ **Pros:**
- Minimal footprint on top of FEAT-124 — no parallel SDK integration.
- Clear separation: client = SDK integration, dispatcher = flow concerns.
- Other AI-Parrot agents can use `ClaudeAgentClient` directly without
  touching the dispatcher (e.g., a `PandasAgent` delegating analysis to a
  Claude Code session is a one-liner).
- Easy to test: dispatcher is pure orchestration, mock the client.
- Preserves the "convention over configuration" subagent default with a
  generic-session escape hatch as a profile flag.

❌ **Cons:**
- Hard dependency on FEAT-124 being merged (or a coordinated branch).
- A few extension points may need to be added to `ClaudeAgentClient`
  (see "Corrections/Extensions to FEAT-124" below).
- The streaming pump adds latency vs. raw stdout streaming, but it's the
  only way to get observability + multi-client UI.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `claude-agent-sdk` | Claude Code SDK transport | `>=0.1.68`, already pinned via FEAT-124's `[claude-agent]` extra |
| `pydantic` | All contracts (briefs, outputs, profiles, criteria) | `>=2.0`, parent-pinned |
| `aiohttp` | Existing WebSocket primitive for the multiplexer | Already in core deps |
| `redis.asyncio` | Streams for raw stream-json + flow events | Already in core deps |
| `pyyaml` / `tomli` | `AcceptanceCriterion` serialization in Jira ticket | Already available |

🔗 **Existing Code to Reuse:**
- `parrot/clients/claude_agent.py` (FEAT-124, in progress) — `ClaudeAgentClient`.
- `parrot/clients/factory.py` (FEAT-124) — `LLMFactory.create("claude-agent:...")`.
- `parrot/flows/...` — `AgentsFlow`, `FlowTransition`, `InteractiveDecisionNode`.
- `parrot/toolkits/jira/...` — `JiraToolkit` for ticket ops.
- `parrot/orchestrator/...` — `AutonomyOrchestrator` for the GitHub webhook handler.
- `parrot/memory/journal.py` — `JournalWriter` for audit.
- `parrot/security/...` — `PermissionContext`, `StaticCredentialResolver`.
- `parrot/conf.py` — `navconfig` settings (semaphore caps, Redis URL).

---

### Option B: Extended Subclass — `ClaudeCodeDispatchClient(ClaudeAgentClient)`

Instead of a separate dispatcher class, sub-class `ClaudeAgentClient` to
fold flow-aware concerns (subagent profile resolution, JSON schema
validation, streaming pump, semaphore) into the client itself. The flow
nodes use the subclass via `LLMFactory.create("claude-code-dispatch:...")`.

✅ **Pros:**
- Single class to maintain.
- Profile selection and SDK invocation are co-located.

❌ **Cons:**
- Couples flow concerns to the client hierarchy. `AbstractClient`
  subclasses are supposed to be transport adapters, not orchestrators.
- Breaks the symmetry with `AnthropicClient`, which is plain transport.
- A `PandasAgent` wanting raw Claude Code access now has to either use
  the parent class (confusing) or accept dispatcher overhead it doesn't need.
- Extending the registry with `claude-code-dispatch` is misleading — it's
  not a different model, it's a different *use*.

📊 **Effort:** Medium-Low (but accumulates technical debt fast)

📦 **Libraries / Tools:** same as Option A.

🔗 **Existing Code to Reuse:** same as Option A, plus would couple to
`parrot.clients.factory.LLMFactory.SUPPORTED_CLIENTS` extension.

---

### Option C: Subprocess CLI Dispatch (Bypass FEAT-124)

Spawn `claude -p --bare --output-format stream-json --json-schema <…>` as
a subprocess directly from `ClaudeCodeDispatcher`, parsing newline-delimited
JSON from stdout. No dependency on `claude-agent-sdk` or
`ClaudeAgentClient`.

✅ **Pros:**
- Zero coupling to FEAT-124 — would unblock parallel work if FEAT-124 slips.
- Smaller dependency surface (no `claude-agent-sdk` import required).
- The CLI is the source of truth — no SDK abstraction in between.

❌ **Cons:**
- **Duplicates everything FEAT-124 is building.** Subprocess management,
  stream parsing, error handling, auth, options serialization — all of
  it is what FEAT-124 already implements.
- Diverges from the AI-Parrot pattern (every other LLM is an
  `AbstractClient`). Other parts of the codebase that want Claude Code
  dispatch would have to choose between two paths.
- Loses prompt caching, hooks, and any future SDK improvements.
- Harder to mock in tests.

📊 **Effort:** Medium-High (re-implementing what FEAT-124 already does).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| stdlib `asyncio.subprocess` | Spawn `claude` CLI | No package |
| `claude` CLI binary | Bundled by `claude-agent-sdk` package, but installed separately would also work | More fragile |

🔗 **Existing Code to Reuse:** `JournalWriter`, `AutonomyOrchestrator`,
`JiraToolkit`. The subprocess plumbing would be greenfield.

---

### Option D (Unconventional): Dispatcher as MCP Toolkit

Expose Claude Code dispatch as a tool inside an `AbstractToolkit`
(`ClaudeCodeDispatchToolkit`). Any AI-Parrot agent (not just the dev-loop
flow) can invoke a Claude Code subagent via `await
toolkit.dispatch_research(brief)` or as an LLM-callable tool. Inside the
flow, the nodes call the toolkit instead of a dispatcher class.

✅ **Pros:**
- Maximum reuse — Claude Code dispatch becomes available to any agent in
  the system (e.g., a `WebScrapingAgent` that finds a bug could trigger
  the flow itself; a `PandasAgent` could delegate code generation; etc.).
- Plays nicely with the existing toolkit registry, permissions
  (`PermissionContext`, `@requires_permission`), and the auto-discovery
  pattern in `AbstractToolkit.get_tools()`.

❌ **Cons:**
- **Wrong abstraction level.** A tool is something an LLM picks from a
  menu and calls during reasoning. A dispatch is a structural component
  of a flow node, not a runtime decision. Putting it in a toolkit lets
  any agent invoke heavy long-running sessions ad hoc, which is
  precisely what the semaphore and the explicit dev-loop scope are
  meant to prevent.
- MCP's request-response shape complicates the streaming pump — events
  produced during dispatch can't easily flow back through a single
  tool-call return.
- Permission model gets murky: who is allowed to dispatch which subagent
  with which `allowed_tools`? Today's `@requires_permission` is per-tool;
  this would need per-subagent-per-profile permission, which is more
  granular than the current resolver supports.

📊 **Effort:** High (and most of it is fighting the abstraction).

📦 **Libraries / Tools:** same as Option A, plus integration with the MCP
in-process server pattern.

🔗 **Existing Code to Reuse:** the toolkit auto-discovery, but at the cost
of conceptual coherence.

---

## Recommendation

**Option A — Thin Dispatcher over `ClaudeAgentClient`** is recommended.

Reasoning:

- It respects the layering already in the codebase: `AbstractClient`
  subclasses are transport adapters; orchestration lives elsewhere
  (`AgentsFlow`, `AutonomyOrchestrator`, dispatcher). Option B and D
  blur that line.
- It builds on FEAT-124 instead of duplicating it. If FEAT-124 needs
  small extensions (the corrections section below), those are the right
  place to put them — not in a parallel implementation (Option C) or a
  subclass that papers over them (Option B).
- The dispatcher's narrow job (profile + semaphore + stream pump +
  Pydantic validation) is well-defined and testable. The dispatcher is
  ~300 LOC of orchestration; the SDK plumbing stays in
  `ClaudeAgentClient` where it already lives.
- The convention-over-configuration subagent default is naturally
  expressed in a profile object that the dispatcher consumes; it would
  be awkward to express it as a tool argument (Option D) or a subclass
  parameter (Option B).
- It leaves the Knative path open for v2 — when it's time to scale, the
  dispatcher's interface (`async def dispatch(brief, profile) -> output`)
  is exactly the right shape for a remote service stub.

Tradeoff accepted: a hard dependency on FEAT-124 being merged before
this feature can ship. Mitigation: FEAT-124 is small (two tracks, both
described in detail in its spec), and this brainstorm coordinates the
extensions it needs (see "Corrections/Extensions to FEAT-124" below) so
both can move in parallel from the spec stage.

---

## Feature Description

### User-Facing Behavior

A human (the original Jira reporter, or a triage engineer) opens the
internal "Dev Loop" page in the AI-Parrot admin UI (Svelte 5 / SvelteKit,
nav-admin plugin). They see a form to start a new run:

- **Bug summary** (free text).
- **Affected component / Flowtask name** (autocomplete from registry).
- **Log sources to include** (multiselect: CloudWatch log group,
  Elasticsearch index, attached file).
- **Acceptance criteria** (one or more rows, each with `kind` =
  `flowtask | shell | pytest | http_check`, the command, expected exit
  code, timeout). At least one criterion is required.
- **Escalation assignee** (defaulted from Jira reporter / current user).

Submitting the form starts a flow run. The page transitions to a live
view powered by the WebSocket multiplexer:

- A SvelteFlow canvas shows the five nodes; the active node is
  highlighted, completed nodes are green, failed ones are red.
- Below the canvas, an expandable panel per node shows the live event
  stream:
  - For pure AI-Parrot nodes: tool calls, Jira API responses, log
    excerpts.
  - For Claude Code dispatch nodes: the raw stream-json events
    (assistant text, tool uses, tool results, file edits) rendered with
    the same component used in Claude Code interactive sessions.
- A toggle on each panel lets the user switch between "flow events
  only", "dispatch events only", or "both interleaved".

When the flow completes:

- **Success path**: the Jira ticket is in "Ready to Deploy", a PR has
  been opened to `main` with a structured comment summarizing the spec,
  the QA evidence (flowtask exit codes, lint output), and the diff
  stats. The page shows links to the ticket and the PR. The human is
  notified via the existing notification channel.
- **Failure path** (QA failed, or a node hard-errored): the ticket is
  in a "Needs Human Review" status with a comment containing the
  failure report (flowtask stdout/stderr, lint diff, files changed,
  branch name). The original assignee (or the explicit `escalation_assignee`)
  is pinged. The flow ends; no retry is attempted automatically.

In both cases, the worktree remains on disk for the human to inspect.
Cleanup happens later, on PR close (webhook handler) or when the human
runs `/sdd-done` after merging.

### Internal Behavior

#### Flow topology

```
┌──────────────────┐
│  BugIntakeNode   │   pure AI-Parrot
│  validates input │   builds BugBrief
└────────┬─────────┘
         │ BugBrief
         ▼
┌──────────────────┐                          ┌────────────────────┐
│  ResearchNode    │  AI-Parrot fetches logs, │  Claude Code       │
│                  │  creates Jira ticket,    │  sdd-research      │
│                  │  then dispatches ────────┼─►  /sdd-spec       │
│                  │                          │   /sdd-task        │
│                  │  ◄─────── ResearchOutput │  → spec, worktree  │
└────────┬─────────┘                          └────────────────────┘
         │ ResearchOutput
         ▼
┌──────────────────┐                          ┌────────────────────┐
│ DevelopmentNode  │  AI-Parrot dispatches    │  Claude Code       │
│                  │  ─────────────────────── │  sdd-worker        │
│                  │                          │  reads spec,       │
│                  │                          │  edits, commits    │
│                  │  ◄────  DevelopmentOutput│  on the branch     │
└────────┬─────────┘                          └────────────────────┘
         │ DevelopmentOutput
         ▼
┌──────────────────┐                          ┌────────────────────┐
│     QANode       │  AI-Parrot dispatches    │  Claude Code       │
│                  │  ─────────────────────── │  sdd-qa            │
│                  │                          │  runs flowtask,    │
│                  │                          │  lint, code review │
│                  │  ◄──────────── QAReport  │  read-only on code │
└────────┬─────────┘                          └────────────────────┘
         │ QAReport
         │
   ┌─────┴───────┐
   │ passed?     │
   └─┬─────────┬─┘
     │ yes     │ no
     ▼         ▼
┌──────────┐  ┌────────────────────────┐
│Deployment│  │ Failure handler        │  pure AI-Parrot
│Handoff   │  │ - attaches QAReport    │  no dispatch
│Node      │  │   evidence to ticket   │
│          │  │ - transitions to       │
│- transi- │  │   "Needs Human Review" │
│  tions   │  │ - assigns to           │
│  to      │  │   escalation_assignee  │
│  "Ready  │  │ - ends flow            │
│  to      │  └────────────────────────┘
│  Deploy" │
│- opens PR│
│- ends    │
│  flow    │
└──────────┘
```

#### `ClaudeCodeDispatcher` lifecycle (one dispatch)

1. The node calls `dispatcher.dispatch(brief, profile, output_model,
   run_id, node_id, cwd)`.
2. Dispatcher acquires the global `asyncio.Semaphore` slot. If the
   semaphore is full, the call waits; the flow's UI shows the node as
   "queued for dispatch" and the orchestrator's flow event stream emits
   a `dispatch.queued` event.
3. Dispatcher resolves a `ClaudeAgentClient` via `LLMFactory.create()`
   (per-event-loop cache as inherited from `AbstractClient`).
4. Dispatcher constructs `ClaudeAgentRunOptions` from the profile:
   `cwd=cwd`, `setting_sources=["project"]`,
   `allowed_tools=profile.allowed_tools`,
   `permission_mode=profile.permission_mode`, `system_prompt` either
   pointing to the named subagent (default) or the explicit override
   (when `profile.subagent is None`).
5. Dispatcher renders the brief as the user prompt (Pydantic
   `model_dump_json()` with a short directive header explaining the
   expected output schema). If the SDK supports `--json-schema`,
   dispatcher passes the output model's JSON schema; otherwise
   dispatcher does best-effort extraction from the final
   `ResultMessage`.
6. Dispatcher iterates over `client.ask_stream(...)`. For each event:
   - Wraps it in `DispatchEvent { kind, ts, run_id, node_id, payload }`.
   - Publishes via `XADD` to `flow:{run_id}:dispatch:{node_id}`.
   - Writes a journal entry via `JournalWriter`.
7. On the final `ResultMessage`, dispatcher parses the payload, validates
   it against `output_model`. If validation fails, dispatcher raises
   `DispatchOutputValidationError` with the raw payload attached; the
   node treats this as a node failure.
8. Releases the semaphore slot. Returns the validated output.

#### Stream multiplexer

The aiohttp WebSocket handler at `/api/flow/{run_id}/ws`:

- On connect, reads the query string for `view` (`flow|dispatch|both`,
  default `both`) and `replay` (boolean, default `true`).
- If `replay=true`, reads both Redis streams from `0` to `$` via
  `XRANGE` / `XREAD` and emits them in timestamp order.
- Then subscribes via `XREAD` with `BLOCK` to both streams and forwards
  new events as they arrive.
- The unified UI envelope is:
  `{ source: "flow"|"dispatch", node_id?, event_kind, ts, payload }`.

The frontend never imports a Redis client; it uses standard browser
WebSocket API.

#### Failure handling

- **Pre-dispatch failures** (semaphore timeout, client construction
  error, profile validation): the node fails immediately. The flow
  transitions to the failure path.
- **In-dispatch failures** (Claude Code session errors, tool errors that
  abort the session, timeout): the dispatcher catches, emits a
  `dispatch.failed` event with the error class and message, and raises
  `DispatchExecutionError`. The node fails.
- **Output validation failures** (the subagent returned text that
  doesn't match the expected Pydantic schema): the dispatcher logs the
  raw payload to the journal, emits `dispatch.output_invalid`, and
  raises. The node fails.
- **QA business-logic failure** (the dispatch succeeded but the
  `QAReport.passed` is `False`): not a dispatch failure — the node
  returns successfully and the flow takes the failure-path transition.
- **Node hard-error inside a flow** (any of the above): the failure
  handler at the flow level publishes `flow.failed` to the flow stream
  with the structured error, transitions the Jira ticket, and the flow
  ends.

### Edge Cases & Error Handling

- **Worktree already exists** (e.g., a previous run left a stale one
  for the same FEAT-id): `ResearchNode` detects this and either
  (a) reuses it if the branch is empty/clean, or (b) fails with a clear
  message instructing the human to run cleanup. v1 chooses (b) — fail
  fast, no automatic recovery.
- **Jira ticket creation succeeded but `sdd-spec` dispatch failed**:
  the partial state (ticket exists, no spec) is recovered by the
  failure handler, which adds a comment to the ticket explaining the
  failure and transitions to "Needs Human Review". Idempotency is not
  attempted (no retry).
- **Acceptance criteria list is empty**: `BugIntakeNode` rejects the
  brief at validation time. The form on the UI prevents submission;
  the node-level check is a defense-in-depth.
- **`AcceptanceCriterion.command` contains shell injection patterns**:
  the QA dispatch runs the command in the Claude Code subagent, which
  is itself bounded by `allowed_tools=["Bash(...)"]` patterns. The
  brief-level validator additionally rejects criteria where the
  command pattern doesn't match an allowlist (e.g., `flowtask`,
  `pytest`, specific lint tools). Operators can extend the allowlist
  via `navconfig`.
- **PR creation fails after QA passed** (e.g., GitHub API error, branch
  conflict with `main`): `DeploymentHandoffNode` retries once with
  backoff; if still failing, transitions the ticket to a "Deployment
  Blocked" status with the error attached and ends the flow. The human
  fixes the PR manually.
- **Concurrent runs collide on Jira ticket** (extremely unlikely
  because each run creates its own ticket, but possible if a human
  manually associates two runs to the same ticket): the
  `JiraToolkit.add_comment` writes are append-only and order-preserving;
  no special handling required.
- **Dispatch produces no `ResultMessage`** (the session ended before
  emitting structured output): treated as output validation failure;
  the raw transcript is attached to the journal and the node fails.
- **Stream consumer (UI) disconnects mid-flow**: the streams are
  durable in Redis (with TTL of 7 days, configurable). The user can
  reload the page and replay.
- **The flow run is killed mid-dispatch** (process restart, OOM):
  there is no resume in v1. The orchestrator marks the run as
  "abandoned"; the worktree remains; a human picks up.

---

## Capabilities

### New Capabilities
- `dev-loop-orchestration`: the `AgentsFlow` definition, the five nodes,
  the Pydantic models (`BugBrief`, `ResearchOutput`, `DevelopmentOutput`,
  `QAReport`), and the `AcceptanceCriterion` discriminated union.
- `claude-code-dispatcher`: the `ClaudeCodeDispatcher` class, the
  `ClaudeCodeDispatchProfile` model, the global semaphore, the streaming
  pump.
- `flow-stream-multiplexer`: the aiohttp WebSocket handler, the unified
  envelope schema, the replay logic.
- `worktree-cleanup-webhook`: the `AutonomyOrchestrator` handler for
  GitHub `pull_request.closed` events that calls the existing cleanup
  command.

### Modified Capabilities
- `claude-agent-client` (FEAT-124): may need extensions
  (`ClaudeAgentRunOptions.cwd`, named subagent invocation, JSON schema
  output). See "Corrections/Extensions to FEAT-124" below.
- `agents-flow`: no requirement changes if the existing `AgentsFlow`
  already supports per-node async work and structured payload passing.
  To be confirmed during /sdd-spec codebase research.
- `nav-admin`: new page registration for the dev-loop UI.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot.clients.ClaudeAgentClient` (FEAT-124) | depends on + may extend | Hard dependency. May need `cwd`, subagent name, JSON-schema fields on `ClaudeAgentRunOptions`. |
| `parrot.clients.LLMFactory` | depends on | Uses `LLMFactory.create("claude-agent:...")`. |
| `parrot.flows.AgentsFlow` | depends on + extends | New flow definition lives in `parrot/flows/dev_loop/`. |
| `parrot.toolkits.JiraToolkit` | depends on | Used by `BugIntakeNode`, `ResearchNode`, `DeploymentHandoffNode`, failure handler. Service-account credentials via `StaticCredentialResolver`. |
| `parrot.toolkits.CloudWatchTool` / `ElasticsearchTool` | depends on | Used by `ResearchNode` for log fetching. |
| `parrot.orchestrator.AutonomyOrchestrator` | depends on + extends | Hosts the flow runs, the GitHub webhook handler, and publishes flow events. |
| `parrot.memory.JournalWriter` | depends on | Audit log for every dispatch. |
| `parrot.security.PermissionContext` / `StaticCredentialResolver` | depends on | Service-account Jira credentials. |
| `parrot.conf` (`navconfig`) | extends | New settings: `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES`, `FLOW_MAX_CONCURRENT_RUNS`, `FLOW_BOT_JIRA_ACCOUNT_ID`, `WORKTREE_BASE_PATH`, `FLOW_STREAM_TTL_SECONDS`. |
| `nav-admin` (Svelte/SvelteKit) | extends | New `dev-loop` plugin: form page + live flow page. |
| `pyproject.toml` | extends | The `dev-loop-orchestration` capability requires `[claude-agent]` extra (transitive via FEAT-124). |
| GitHub repo settings | depends on | Webhook configured to send `pull_request.closed` events to `AutonomyOrchestrator`. |

### Corrections/Extensions to FEAT-124

These are points to verify/coordinate with FEAT-124 before this spec is
finalized. None of them block FEAT-124's current scope; they may
warrant a small follow-on (FEAT-124.1) or be folded into FEAT-124 if not
yet implemented.

1. **`ClaudeAgentRunOptions.cwd`** — the dispatcher needs to point each
   session at a worktree directory. `claude_agent_sdk.ClaudeAgentOptions`
   supports this upstream. Verify that `ClaudeAgentRunOptions` exposes it
   (or add it).
2. **Named subagent invocation** — `setting_sources=["project"]` already
   loads filesystem subagents (`.claude/agents/*.md`). The dispatcher
   needs an explicit way to *select* a subagent for a session. Three
   possibilities, in order of preference:
   - `claude_agent_sdk` exposes `agents=` programmatic subagent
     definition in recent versions (`>=0.1.5x`). Verify and expose via
     `ClaudeAgentRunOptions`.
   - Otherwise, set the `system_prompt` to a directive that names the
     subagent (less robust, depends on prompt convention).
   - Worst case, use a slash-command invocation in the user prompt
     (most fragile, last resort).
3. **JSON-schema structured output** — the CLI supports
   `--output-format json --json-schema <path>`. The SDK should expose
   this; if it does, `ClaudeAgentRunOptions` should accept a
   `response_schema: dict | type[BaseModel]` field. If not, dispatcher
   does best-effort parsing of the final `ResultMessage`.
4. **Hooks** — FEAT-124 explicitly defers hooks. The dispatcher does
   *not* require hooks for v1 — `ask_stream` already emits
   `AssistantMessage` / `ToolUseBlock` / `ToolResultBlock` events,
   which is enough for the streaming pump. Hooks become attractive only
   if we later need to enforce per-tool policy at execution time inside
   a session (e.g., reject a `Write` to a path outside the worktree).
   Track as a future enhancement.

---

## Code Context

### User-Provided Code

The following is the relevant excerpt from FEAT-124's spec (the Claude
Agent SDK Migration). It is the foundation this brainstorm builds on.

```python
# Source: packages/ai-parrot/src/parrot/clients/claude_agent.py (TO BE CREATED by FEAT-124)
# From FEAT-124 spec §2 "Architectural Design" and §7 "Implementation Notes":

class ClaudeAgentClient(AbstractClient):
    """
    Wraps `claude-agent-sdk` (>=0.1.68) for ai-parrot agents that need to
    dispatch tasks to Claude Code agents.

    Uses subprocess transport via the bundled `claude` CLI.
    Inherits AbstractClient (per FEAT-124 Open Question resolution).
    """

    # Inherited per-loop client cache from AbstractClient._ensure_client
    # (base.py:410). Do NOT assign self.client = ... directly.

    async def get_client(self):
        # Lazy import — `claude_agent_sdk` is in the [claude-agent] extra:
        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
        # ...

    async def ask(self, prompt: str, **kwargs) -> AIMessage: ...
    async def ask_stream(self, prompt: str, **kwargs): ...    # async iterator
    async def invoke(self, prompt: str, **kwargs) -> AIMessage: ...
    async def resume(self, session_id: str, prompt: str, **kwargs) -> AIMessage: ...

    # Methods that have no SDK equivalent raise NotImplementedError with a
    # message redirecting to AnthropicClient:
    async def batch_ask(self, *args, **kwargs): raise NotImplementedError(...)
    async def ask_to_image(self, *args, **kwargs): raise NotImplementedError(...)


# Source: packages/ai-parrot/src/parrot/clients/factory.py (FEAT-124)
class LLMFactory:
    SUPPORTED_CLIENTS = {
        # ...existing entries...
        "claude-agent": _lazy_claude_agent,    # NEW
        "claude-code":  _lazy_claude_agent,    # alias
    }

    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]: ...   # base.py:48
    @staticmethod
    def create(llm, model_args=None, tool_manager=None,
               **kwargs) -> AbstractClient: ...                        # base.py:70


# Source: packages/ai-parrot/src/parrot/models/responses.py:572
class AIMessageFactory:
    @staticmethod
    def from_claude(response, input_text, model, ...) -> AIMessage:    # line 572
        ...

    # NEW per FEAT-124:
    @staticmethod
    def from_claude_agent(...) -> AIMessage:
        ...
```

### Verified Codebase References

> ⚠️ **Note**: The references below are from the FEAT-124 spec's
> verified codebase research (where Jesus already verified file paths
> and line numbers in his repo). Additional references for this
> brainstorm's new components must be verified during /sdd-spec
> codebase research; placeholders are marked accordingly.

#### Classes & Signatures

```python
# From FEAT-124 spec — verified by Jesus during /sdd-spec for FEAT-124:

# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(...):
    # __init__ at base.py:261
    # logger configured at base.py:298
    # client direct-assignment guard raises AttributeError at base.py:362
    # _ensure_client per-loop cache at base.py:410
    # complete() method at base.py:627

# packages/ai-parrot/src/parrot/clients/factory.py
# _lazy_gemma4 pattern at factory.py:14 (template for _lazy_claude_agent)

# packages/ai-parrot/src/parrot/models/claude.py:4
class ClaudeModel(Enum):
    OPUS_4_6     = "claude-opus-4-6"        # line 13
    SONNET_4_6   = "claude-sonnet-4-6"      # line 14
    OPUS_4_5     = "claude-opus-4-5-20251101"  # line 17
    HAIKU_4_5    = "claude-haiku-4-5-20251001" # line 18
    SONNET_4_5   = "claude-sonnet-4-5-20250929" # line 19
    OPUS_4_1     = "claude-opus-4-1-20250805"   # line 22
    SONNET_4     = "claude-sonnet-4-20250514"   # line 24
    SONNET_3_7   = "claude-3-7-sonnet-20250219" # line 27
    HAIKU_3_5    = "claude-3-5-haiku-20241022"  # line 28
```

#### To Verify During /sdd-spec

The following are referenced in this brainstorm but require codebase
verification during /sdd-spec for this feature. The verifying agent
must record exact file paths and line numbers.

- `parrot.flows.AgentsFlow` — class location, node registration API,
  `FlowTransition` shape, support for `InteractiveDecisionNode`, hook
  lifecycle methods if any.
- `parrot.toolkits.AbstractToolkit` — `_pre_execute` / `_post_execute`
  lifecycle hooks (mentioned in FEAT-083 spec; verify status).
- `parrot.toolkits.jira.JiraToolkit` — exact method signatures for
  `add_comment`, `transition_issue`, `attach_file`, including
  `accountId` handling per FEAT-083.
- `parrot.orchestrator.AutonomyOrchestrator` — API for registering
  webhook handlers, scheduling flow runs, and publishing to Redis
  Streams. Existing webhook handler pattern (HMAC validation).
- `parrot.memory.JournalWriter` — write API and entry shape.
- `parrot.security.PermissionContext`, `StaticCredentialResolver` —
  exact constructors and how to wire a service account.
- `parrot.conf` / `navconfig` — pattern for adding new settings.
- `nav-admin` plugin system — entry points, route registration,
  WebSocket endpoint registration.

#### Verified Imports

```python
# From FEAT-124 (verified):
from parrot.clients import AbstractClient                # base.py
from parrot.clients import LLMFactory                    # factory.py
from parrot.models.responses import AIMessage, AIMessageFactory   # responses.py:572

# Will be available once FEAT-124 merges:
from parrot.clients.claude_agent import ClaudeAgentClient        # to be created
# Note: per FEAT-124 design, ClaudeAgentClient is deliberately NOT
# re-exported from parrot.clients.__init__ to keep claude_agent_sdk lazy.

# To be verified during /sdd-spec:
from parrot.flows import AgentsFlow, FlowTransition
from parrot.toolkits.jira import JiraToolkit
from parrot.orchestrator import AutonomyOrchestrator
from parrot.memory import JournalWriter
from parrot.security import PermissionContext, StaticCredentialResolver
from parrot.conf import settings as parrot_settings
```

### Does NOT Exist (Anti-Hallucination)

These are things that might seem like they should exist, given the
discussion, but DO NOT — the implementing agent must NOT assume them.

- ~~`parrot.flows.dev_loop`~~ — does not exist; this brainstorm proposes
  creating it.
- ~~`parrot.flows.dev_loop.dispatcher.ClaudeCodeDispatcher`~~ — to be
  created.
- ~~`parrot.flows.dev_loop.dispatcher.ClaudeCodeDispatchProfile`~~ — to
  be created.
- ~~`parrot.flows.dev_loop.models.BugBrief`~~,
  ~~`ResearchOutput`~~, ~~`DevelopmentOutput`~~, ~~`QAReport`~~,
  ~~`AcceptanceCriterion`~~ — all to be created.
- ~~`parrot.flows.dev_loop.nodes.BugIntakeNode`~~,
  ~~`ResearchNode`~~, ~~`DevelopmentNode`~~, ~~`QANode`~~,
  ~~`DeploymentHandoffNode`~~ — all to be created.
- ~~`parrot.flows.dev_loop.streaming.FlowStreamMultiplexer`~~ — to be
  created.
- ~~`.claude/agents/sdd-research.md`~~, ~~`sdd-qa.md`~~ — the existing
  SDD setup has `sdd-worker`. Two new subagents must be added (in the
  Claude Code project config, not in the AI-Parrot codebase).
- ~~`AcceptanceCriterion.kind == "regex_match"`~~ /
  ~~`"output_match"`~~ / others — v1 only implements `flowtask` and
  `shell`. Other kinds are extensible without flow changes but are NOT
  in the v1 scope.
- ~~`ClaudeCodeDispatcher.retry()`~~ — explicitly out of scope.
- ~~`ClaudeAgentClient.dispatch_subagent(...)`~~ — the dispatcher does
  not extend the client class. Subagent selection happens via
  `ClaudeAgentRunOptions` (or the workaround if those fields don't
  exist yet — see "Corrections/Extensions to FEAT-124").
- ~~Auto-PR-merge / voting bypass~~ — the flow stops at PR creation. A
  human always merges.
- ~~Telegram HITL escalation~~ — out of scope for v1; tracked separately.
- ~~Knative microservice for the dispatcher~~ — out of scope for v1.
- ~~In-process MCP server migration~~ — already declared out of scope
  by FEAT-124; remains out of scope here.
- ~~Multi-repo support~~ — v1 is single-repo.

---

## Parallelism Assessment

- **Internal parallelism**: **Yes**, the feature decomposes into
  reasonably independent modules:
  1. `parrot/flows/dev_loop/models.py` (Pydantic contracts) — no deps;
     can start day one.
  2. `parrot/flows/dev_loop/dispatcher.py` — depends on (1) and on
     FEAT-124 being merged or available on a coordinated branch.
  3. `parrot/flows/dev_loop/nodes/*.py` (five nodes) — depend on (1)
     and (2). The five nodes themselves are mostly independent of each
     other and could be split across worktrees, but they share the
     same models module so a single worktree is simpler.
  4. `parrot/flows/dev_loop/streaming.py` (multiplexer) — depends on
     (1) only; can be developed in parallel with (2) and (3).
  5. `parrot/flows/dev_loop/flow.py` (the `AgentsFlow` definition that
     wires the nodes together) — depends on (3).
  6. `nav-admin` plugin (UI) — depends on (4)'s WebSocket envelope
     schema only; otherwise independent.
  7. `AutonomyOrchestrator` GitHub webhook handler — depends on the
     existing handler-registration pattern; otherwise independent.
  8. SDD subagent files (`sdd-research.md`, `sdd-qa.md`) — independent
     of the AI-Parrot code; live in the Claude Code project config,
     not the AI-Parrot repo.

- **Cross-feature independence**: Hard dependency on **FEAT-124**
  (`ClaudeAgentClient`). Soft dependency on **FEAT-083** (Jira OAuth
  3LO) — this feature uses `StaticCredentialResolver` directly, but
  benefits from the `CredentialResolver` abstraction shipped by
  FEAT-083. No conflict expected. No shared files with other in-flight
  specs (to verify during /sdd-spec).

- **Recommended isolation**: **mixed**.
  - Core code (models + dispatcher + nodes + streaming + flow) in one
    worktree as a `per-spec` group, since they share imports and tight
    contracts.
  - The nav-admin UI plugin can live in a separate worktree once the
    multiplexer's envelope schema is locked.
  - The webhook handler is a small change to `AutonomyOrchestrator`
    that can also be its own worktree.

- **Rationale**: The five core modules iterate together (changes to a
  Pydantic model ripple to the dispatcher and the nodes). Splitting
  them across worktrees would create constant rebase pain. The UI and
  webhook are decoupled enough — and small enough — to live in their
  own worktrees once the contracts they consume are stable.

---

## Open Questions

- [x] Should the dispatcher be a class (Option A) or a subclass of
  `ClaudeAgentClient` (Option B), or expose dispatch as an MCP toolkit
  (Option D)? — *Owner: Jesus*: Option A — class. Rationale: respects
  layering (clients are transports, dispatchers orchestrate), keeps
  `ClaudeAgentClient` reusable for non-flow agents.
- [x] Do we use named subagents (`sdd-research`, `sdd-worker`,
  `sdd-qa`) by default, or always pass an explicit system prompt?
  — *Owner: Jesus*: Convention over configuration — `sdd-*` subagents
  by default; profile flag (`subagent: str | None = None`) permits
  generic-session fallback with explicit `system_prompt_override`.
- [x] One Redis stream per run, or one for flow events + one per
  dispatch? — *Owner: Jesus*: Two streams (flow + per-dispatch) in
  Redis to preserve raw stream-json; an aiohttp WebSocket multiplexer
  reconciles them for the UI. Frontend never speaks Redis.
- [x] Worktree cleanup — flow's responsibility or external? — *Owner:
  Jesus*: External. Two paths: human runs the existing `sdd-done`
  command (which merges to `dev`); or `AutonomyOrchestrator` listens
  for GitHub `pull_request.closed` and runs cleanup automatically.
- [x] Concurrency control — global semaphore? Two levels? — *Owner:
  Jesus*: Two-level. Global semaphore on dispatcher
  (`CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES`, default 3) plus flow-level
  semaphore on `AutonomyOrchestrator` (`FLOW_MAX_CONCURRENT_RUNS`,
  default 5). Orthogonal because one flow has multiple sequential
  dispatches.
- [x] Jira identity — service account or OAuth-as-user? — *Owner:
  Jesus*: Service account (`flow-bot@company`) via
  `StaticCredentialResolver`, bypassing FEAT-083 OAuth 3LO. Ticket
  reporter and assignee remain the original human; only comments,
  attachments, and transitions are written by the bot.
- [x] Failure path — retry, or hand off to human? — *Owner: Jesus*:
  Hand off to human. No retry semantics in v1. Failure handler
  attaches the QAReport (or error context) to the ticket, transitions
  to "Needs Human Review", and pings the original assignee.
- [x] Acceptance criteria — single command, or list with discriminated
  kinds? — *Owner: Jesus*: List of `AcceptanceCriterion` with
  discriminated `kind` (v1: `flowtask`, `shell`; v2+: `pytest`,
  `http_check`). The QA node executes them deterministically; LLM
  judgment is not the gate.
- [x] PR creation — flow auto-merges or stops at PR open? — *Owner:
  Jesus*: Stops at PR open. Repo has voting rules requiring human
  approvals; flow never bypasses them.

### Still Open (require codebase verification or further decision)

- [ ] **Subagent invocation mechanism in `ClaudeAgentClient`** — does
  `ClaudeAgentRunOptions` accept a programmatic subagent reference, or
  must the dispatcher use a `system_prompt` directive / slash command?
  Verify in FEAT-124 implementation; if missing, file as a follow-on
  (FEAT-124.1) before this feature can ship. — *Owner: Jesus + the
  agent doing /sdd-spec for this feature*.
- [ ] **`ClaudeAgentRunOptions.cwd`** — verify exposed or add. — *Owner:
  Jesus*.
- [ ] **JSON-schema structured output via `ClaudeAgentRunOptions`** —
  is it exposed? If not, dispatcher does best-effort `ResultMessage`
  parsing for v1 and we add structured output as a v2 enhancement. —
  *Owner: Jesus*.
- [ ] **`AcceptanceCriterion.command` allowlist** — what is the v1
  allowlist? Proposed minimum: `flowtask`, `pytest`, `ruff`, `mypy`,
  `pylint`. Should be configurable via `navconfig` per environment. —
  *Owner: Jesus*.
- [ ] **Worktree base path collision** — does `sdd-task` already use a
  unique-per-FEAT directory naming scheme that prevents collision when
  two flows for the same FEAT run concurrently (which shouldn't happen
  but might)? Verify during /sdd-spec; if not, add a flow-level lock
  on `FEAT-{ticket_id}`. — *Owner: agent doing /sdd-spec*.
- [ ] **`AgentsFlow` async support and structured payload passing** —
  does the existing `AgentsFlow` carry typed payloads between nodes,
  or do we need a thin wrapper? Verify during /sdd-spec. — *Owner:
  agent doing /sdd-spec*.
- [ ] **`AutonomyOrchestrator` GitHub webhook pattern** — is HMAC
  validation already implemented (mentioned in user memories), and
  what is the exact handler-registration API? Verify during /sdd-spec.
  — *Owner: agent doing /sdd-spec*.
- [ ] **`AbstractToolkit._pre_execute` / `_post_execute`** — these are
  mentioned in FEAT-083; are they merged yet, and do the `JiraToolkit`
  calls in this flow rely on them? — *Owner: agent doing /sdd-spec*.
- [ ] **Stream TTL** — what is a reasonable default for replay window?
  Proposed: 7 days. Should be configurable. — *Owner: Jesus*.
- [ ] **Flow run identifier scheme** — are `run_id`s already issued by
  `AutonomyOrchestrator`, or does this feature mint them? — *Owner:
  agent doing /sdd-spec*.
