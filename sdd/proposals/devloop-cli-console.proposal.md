---
id: FEAT-374
title: parrot devloop — interactive CLI console for dispatching dev-loop flows
slug: devloop-cli-console
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-07-24
  summary_oneline: CLI console (parrot devloop) to dispatch dev-loop AgentCrew flows interactively from the terminal
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-374/
created: 2026-07-24
updated: 2026-07-24
---

# FEAT-374 — `parrot devloop`: interactive CLI console for dev-loop flows

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-374/`](../state/FEAT-374/)

---

## 0. Origin

The original request, preserved verbatim at `sdd/state/FEAT-374/source.md`:

> Currently the flow "dev-loop" will work only for a UI with websockets, the
> idea of this proposal is build a CLI console (like `Claude Code` CLI) for
> invoking a dev-loop flow via console, a rich console using a library for
> user interaction in console will be very useful, the idea is: user can send
> the instruct for dispatching a dev-loop flow via the cli, the cli can use a
> pydantic structured input for asks to the user details about jira ticket
> (if any), description or path of proposal/brainstorm to be develop,
> agentcrew flow will be dispatched interactively in cli console, the cli
> console command can be installed (like others) in `parrot devloop`.

**Initial signals** (extracted, not interpreted):
- Verbs: "build", "invoke", "dispatch", "ask", "install" → new feature (CLI front-end)
- Named entities: "dev-loop", "websockets", "Claude Code CLI", "rich console", "pydantic structured input", "Jira ticket", "proposal/brainstorm", "AgentCrew", "`parrot devloop`"
- Components / labels: dev-loop flow subsystem, `parrot` CLI
- Acceptance criteria provided: no

---

## 1. Synthesis Summary

Build `parrot devloop` — a Rich + prompt_toolkit interactive console registered
in the existing `LazyGroup` CLI (`packages/ai-parrot/src/parrot/cli/__init__.py`)
— that collects a `WorkBrief` via pydantic-driven prompts (including
`existing_issue_key`, the "Jira ticket if any"), dispatches an **embedded,
in-process** dev-loop run through `DevLoopRunner`
(`packages/ai-parrot/src/parrot/flows/dev_loop/runner.py`), renders the live
envelope stream as a scrolling Rich Live console, and answers HITL gates
interactively via `DevLoopRunner.resolve_gate`. Every hard primitive already
exists: `WorkBrief` carries per-field descriptions usable to auto-generate the
wizard, the FEAT-322 session-state layer provides sequenced envelopes +
snapshot rebuild, and the `parrot agent` REPL (console-cli-agents) provides
the exact CLI architecture to mirror. v1 also covers listing/attaching to runs
and revision-mode runs (`RevisionBrief` via `DevLoopRunner.run_revision`).

*(Note: one technicality vs the source text — the dev-loop is an
`AgentsFlow`-based DAG under `parrot/flows/dev_loop/`, not an `AgentCrew`;
"AgentCrew flow" in the origin reads as shorthand for the orchestrated flow.)*

---

## 2. Codebase Findings

> Grounded in `sdd/state/FEAT-374/findings/`. No fabricated paths or symbols.

### 2.1 Localization

| # | Path | Symbol | Role | Evidence |
|---|------|--------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | `DevLoopRunner` | complete programmatic surface: `run()`, `run_revision()`, `resolve_gate()`, `cancel_run()`, `get_host()`, `registry_state()`, `active_runs()` | F002 |
| 2 | `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` | `WorkBrief`, `RevisionBrief` | pydantic structured input to collect interactively; `existing_issue_key` = the "Jira ticket (if any)" | F003 |
| 3 | `packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py` | `FlowStreamMultiplexer` | the current WS-only read surface (Redis fan-in, `view=state`) — the coupling this feature breaks free of | F004 |
| 4 | `packages/ai-parrot/src/parrot/flows/dev_loop/commands.py` | `register_command_routes` | REST write surface (gate resolve / cancel) — not needed in embedded mode, kept as reference | F004 |
| 5 | `packages/ai-parrot/src/parrot/cli/__init__.py` | `cli._lazy_commands` | registration point: add `"devloop": "parrot.cli.devloop"`; installs via existing `[project.scripts] parrot = parrot.cli:cli` | F005 |
| 6 | `packages/ai-parrot/src/parrot/cli/` | `agent_repl` / `repl` / `renderer` / `commands` / `loaders` | architecture template from console-cli-agents: Click entry + Rich renderer + SlashCommandDispatcher | F005 |
| 7 | `packages/ai-parrot/src/parrot/human/cli_companion.py` | `HITLCompanion` | precedent for Rich-rendered interactive HITL answering in a terminal | F006 |
| 8 | `examples/dev_loop/server.py` + `static/index.html` | — | the only current UI host (aiohttp + vanilla-JS WS client); `quickstart.py` is one-shot, non-interactive | F004 |

### 2.2 Constraints Discovered

- **Console deps already core.** `rich>=13.0`, `click>=8.1.7`,
  `prompt_toolkit>=3.0` are core dependencies of `ai-parrot`; `textual` is
  not. The chosen Rich-Live style adds **zero** dependencies.
  *Evidence*: F005
- **`models.py` is import-cheap.** Zero internal deps beyond pydantic — the
  wizard can build and validate a `WorkBrief` without booting the flow stack,
  Redis, or LLM clients. *Evidence*: F003
- **Embedded mode has real prerequisites.** Per `examples/dev_loop/README.md`
  real-mode: Redis, the `claude` CLI, Jira credentials, `WORKTREE_BASE_PATH`.
  The CLI must preflight these and fail with actionable messages.
  *Evidence*: F001, F004
- **Bind only to stable surfaces.** The dispatcher internals are hot
  (FEAT-322/323 landed in the last 4 months). The CLI must consume
  `DevLoopRunner` + SessionHost envelopes only — never dispatcher internals.
  *Evidence*: F007, F002
- **Gate semantics are already strict.** TTLs (`gate_ttl_for`), arbitration,
  409-on-double-resolve, expiry sweep — the CLI renders and resolves; it must
  not re-implement gate logic. *Evidence*: F006

### 2.3 Recent History (Relevant)

| When | What | Where |
|------|------|-------|
| last 4 months | FEAT-322 agent-host-protocol-session-state (TASK-1849..1856): SessionHost, dual-publish, HITL gates, `view=state`, REST commands, e2e reconnect tests | `flows/dev_loop/` (merge `e5d23c782`) |
| last 4 months | FEAT-323 dev-loop-multiple-dev-agents (TASK-1859..1864): dev-agent pool, sub-worktrees, scheduler | `flows/dev_loop/` |
| ~2 months | console-cli-agents (TASK-1136 CLI command wiring, `35e17ccca`), `parrot generate-keys` | `parrot/cli/` |

Dev-loop is under active development; the CLI package itself is low-churn and
additive. *Evidence*: F007

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`parrot.cli.devloop`** — Click command module (`parrot devloop`), lazy-registered.
- **Pydantic prompt engine** — a *generic*, reusable model→interactive-wizard
  engine (reads `model_fields` descriptions, defaults, `Literal` choices,
  required-ness; nested lists like `acceptance_criteria` handled via typed
  sub-prompts), instantiated for `WorkBrief` and `RevisionBrief` (resolved U2).
- **Run console renderer** — scrolling Rich Live view (Claude-Code-like) of
  SessionHost envelopes: node lifecycle, dispatch events, gate panels
  (resolved U4). Interactive gate resolution + cancel (Ctrl-C → confirm →
  `cancel_run`).
- **Run catalogue subcommands** — list active runs (`registry_state()` /
  `active_runs()`) and attach to one; revision-mode entry point
  (`run_revision` with a `RevisionBrief` wizard) (resolved U3).
- **Preflight check** — validate embedded-mode prerequisites (Redis reachable,
  `claude` CLI on PATH, Jira creds present) before dispatch.

### What Changes

- **`packages/ai-parrot/src/parrot/cli/__init__.py`::`cli._lazy_commands`** —
  add `"devloop": "parrot.cli.devloop"`. *Evidence*: F005

### What's Untouched (Non-Goals)

- **No remote/server client in v1** (resolved U1: embedded only). The WS
  multiplexer + REST command routes stay UI-only; no new REST run-start
  endpoint is added.
- **No changes to `flows/dev_loop/`** — runner, models, session-state, and
  gates are consumed as-is.
- **No `textual` dependency** — Rich Live + prompt_toolkit only.
- **No new flow topology** — the eight-node flow and revision flow are used
  unmodified.

### Patterns to Follow

- `parrot agent` REPL structure: Click entry (`agent_repl.py`), engine
  (`repl.py`), Rich renderer (`renderer.py`), `SlashCommandDispatcher`
  (`commands.py`). *Evidence*: F005
- `HITLCompanion` for interactive question/gate rendering in Rich.
  *Evidence*: F006
- `examples/dev_loop/quickstart.py` for correct embedded wiring of
  `build_dev_loop_flow` + `DevLoopRunner`. *Evidence*: F001, F004

### Integration Risks

- **Cross-process attach is limited in embedded mode.** `registry_state()` is
  in-memory per-process; "attach to an existing run" from a *new* CLI process
  can only rebuild from the Redis `flow:{run_id}:actions` stream / persisted
  snapshot. The spec must define how far v1 attach goes (same-process vs
  Redis-rebuild). *Evidence*: F002, F004, F006
- **Blocking prompts in an async loop.** The console must not block the event
  loop while a run streams (prompt_toolkit async APIs / `patch_stdout`).
  *Evidence*: F005 (agent REPL already solves streaming+input coexistence)
- **Embedded prerequisites drift.** Real-mode needs (Jira package, Redis,
  `claude` CLI) evolve with dev-loop FEATs; keep preflight table in one
  module. *Evidence*: F001, F007

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Registration = one `_lazy_commands` entry + one module; installs as `parrot devloop` | F005 | high | direct read of `cli/__init__.py` + `[project.scripts]` |
| C2 | `WorkBrief.model_fields` (descriptions, defaults, Literals) suffices to auto-generate the wizard | F003 | high | live introspection of the model |
| C3 | `DevLoopRunner.run/run_revision/resolve_gate/cancel_run` is sufficient for full interactive control in embedded mode | F002 | high | API outline read; REST layer is a thin adapter over the same methods |
| C4 | Proposal/brainstorm *path* input maps onto `WorkBrief.description` (file contents inlined) — no model change | F003 | medium | description is free-form long text; not yet validated with a real run |
| C5 | Cross-process re-attach requires Redis stream/snapshot rebuild (registry is per-process memory) | F002, F004 | medium | inferred from runner docstrings + FEAT-322 reconnect tests |
| C6 | Embedded mode works from any checkout given Redis + `claude` CLI + Jira creds | F001 | low | asserted by examples README; not exercised in this research |

Distribution: **3** high, **2** medium, **1** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1: Attach mode for v1?** — *Resolved*: "Embedded only — in-process
  `DevLoopRunner`; no remote server client in v1." *Resolves*: H1 scope
- [x] **U2: Generic vs hand-written wizard?** — *Resolved*: "Generic engine —
  reusable pydantic-model→interactive-prompt engine, instantiated for
  WorkBrief/RevisionBrief." *Resolves*: C2
- [x] **U3: Run scope?** — *Resolved*: "Everything incl. revision — new runs,
  list/attach, and RevisionBrief revision-mode runs in v1." *Resolves*: H1 scope
- [x] **U4: Console style?** — *Resolved*: "Rich Live scrolling console
  (Claude-Code-like); no textual dependency." *Resolves*: C1 constraint

### Unresolved (defer to spec / implementation)

- [ ] **How far does "attach" go in embedded-only v1?** — *Owner*: tbd
  *Blocks claims*: C5
  *Plausible answers*: a) same-process only (list runs started in this console
  session) · b) Redis-rebuild attach to runs started by any process, via
  `flow:{run_id}:actions` + persisted snapshot
- [ ] **Wizard UX for `acceptance_criteria` and `log_sources` lists** —
  *Owner*: tbd — *Plausible answers*: a) optional "add another?" loop of typed
  sub-forms · b) accept a YAML/JSON file path · c) both

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-374`** — *Rationale*: localization is high-confidence and
single-hypothesis; scope decisions (U1–U4) are resolved. Likely 5–7 tasks:
prompt engine, devloop command + wiring, run renderer, gate interaction,
catalogue/attach, revision mode, tests.

### Alternatives

- **`/sdd-brainstorm FEAT-374`** — only if the attach-semantics question (C5)
  should be explored as an architectural fork first.
- **Manual review** — not indicated; research completed within budget.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-374/state.json` |
| Source (raw) | `sdd/state/FEAT-374/source.md` |
| Research plan | `sdd/state/FEAT-374/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-374/findings/F001-*.md` … `F007-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-374/synthesis.json` |

**Budget consumed** (profile: default):
- Files read: 12 / 40
- Grep calls: 10 / 25
- Git calls: 2 / 10
- Wiki queries: 8 (free)
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (new CLI front-end
over an existing, well-understood subsystem; no defect to investigate).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara + Claude (Fable 5) |
