---
type: Wiki Overview
title: 'Brainstorm: Dev-Loop Orchestration with Claude Code Subagent Mirror'
id: doc:sdd-proposals-dev-loop-orchestration-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The development feedback loop for "small operational fixes" today is entirely
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.clients.claude_agent
  rel: mentions
- concept: mod:parrot.clients.factory
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.flows
  rel: mentions
- concept: mod:parrot.flows.dev_loop
  rel: mentions
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: mentions
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes
  rel: mentions
- concept: mod:parrot.flows.dev_loop.streaming
  rel: mentions
- concept: mod:parrot.memory
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
- concept: mod:parrot.security
  rel: mentions
---

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

…(truncated)…
