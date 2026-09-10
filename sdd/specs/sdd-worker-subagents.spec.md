---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: `sdd-worker` as Orchestrator of Parallel `sdd-coder` Sub-Agents

**Feature ID**: FEAT-549
**Date**: 2026-09-10
**Author**: Jesus Lara (with Claude Fable 5.1)
**Status**: draft
**Target version**: ai-parrot 1.1.0 (next minor after 1.0.0) · ai-parrot-client-google 0.3.0
**Origin**: `sdd/proposals/sdd-worker-subagents.brainstorm.md` (accepted 2026-09-10, Option A)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

`/sdd-spec` and `/sdd-task` already produce a task graph with explicit
precedence (`depends_on`) and a `parallel` / `parallelism_notes` hint per task,
precisely so that independent tasks can be executed concurrently. The
interactive `sdd-worker` agent (`.claude/agents/sdd-worker.md`) ignores that
graph: it topologically sorts the pending tasks and implements them **one after
another, in its own execution block**, on a single Sonnet session. When it does
"parallelise", it does so by unilaterally spawning a copy of itself through the
Claude Code `Agent` tool — an undesigned behaviour with no model diversity, no
isolation and no consolidation step.

The server-side dev-loop already solved the scheduling half of this problem
(FEAT-323 *Dev-Loop Multiple Dev Agents*): `TaskScheduler` computes
dependency-respecting waves from the per-spec index, `DevAgentPool` dispatches a
wave in parallel across heterogeneous backends with a retry-on-a-different-worker
rule, and `SubWorktreeManager` isolates each worker in its own git worktree and
merges sequentially. None of that is reachable from an interactive Claude Code
session, because the Claude Code `Agent` tool can only launch **Anthropic**
models.

**Who is affected**

- The maintainer running `sdd-worker` interactively: features with 8–20 tasks
  take hours of wall-clock time on a single Sonnet seat, all billed at Sonnet
  rates even for mechanical tasks that FEAT-545 deliberately shaped so a cheaper
  model can execute them nearly verbatim (Implementation Blueprints).
- The `/sdd-done` / PR review stage, which receives no record of *which* model
  produced *which* task, so quality per model cannot be compared.

**Expectation**: `sdd-worker` keeps running on Sonnet but becomes an
**orchestrator**: it reads the task list and its precedence, assigns each task
a model from a fixed roster of four seats (Qwen3-Coder on Bedrock,
Gemini 3.5 Flash, GPT-5.3-codex-spark, Claude Haiku), dispatches `sdd-coder`
sub-agents with that model + task, consolidates each finished coder's work,
runs the `code-reviewer` sub-agent over the whole feature, applies the
reviewer's fixes, and leaves the worktree ready for `/sdd-done`. Rule 1:
**never the same model for two tasks running in parallel**.

### Goals

- **G1 — Parallel execution honouring precedence.** Pending tasks are executed
  in dependency-respecting waves; within a wave, tasks run concurrently in
  isolated sub-worktrees and are merged back sequentially into the feature
  branch.
- **G2 — Distinct-model rule.** No two tasks running concurrently use the same
  roster model. A wave larger than the available roster is chunked; the excess
  runs in the next chunk. One available model ⇒ serial execution (still
  delegated).
- **G3 — Heterogeneous seats from a Claude Code session.** Non-Anthropic
  coders are reached through a local MCP server (`parrot mcp-local sdd-coder`,
  the FEAT-543 `parrot-targeted-writer` pattern); the Haiku seat is a native
  Claude Code sub-agent launched by `sdd-worker` itself.
- **G4 — Gemini in-process seat.** A new `google-compat` backend drives Gemini
  through Google's OpenAI-compatible endpoint with the unchanged
  `LLMCodeDispatcher` loop (verified live 2026-09-10, brainstorm "Spike
  evidence"), including the Gemini 3 `thought_signature` echo requirement.
- **G5 — Deterministic policy in Python, judgment in Sonnet.** Wave
  computation, model assignment, chunking, cross-model retry, sub-worktree
  lifecycle, fidelity check and merge live in tested Python. `sdd-worker`
  keeps SDD state, conflict resolution, the third-attempt implementation and
  reviewer triage.
- **G6 — Total delegation with a bounded failure ladder.** Every pending task
  is dispatched to an `sdd-coder`; attempt 1 on the assigned seat → attempt 2
  on a *different* seat in a fresh sub-worktree → attempt 3 by `sdd-worker`
  itself. A task is never orphaned; `done-with-issues` is reserved for three
  failures.
- **G7 — Ownership split.** Coders commit **code only** in their sub-worktree
  and never touch `sdd/`; `sdd-worker` owns the per-spec index, the move to
  `sdd/tasks/completed/` and the Completion Note (model, backend, attempts,
  duration, tokens).
- **G8 — Roster as configuration.** The roster (ordered seats, `model` +
  optional `fallback_model`) lives in `.parrot/mcp-toolkits.yaml`; a startup
  probe drops seats whose credentials/CLI are missing and reports why; nothing
  is hardcoded in Python or in the prompt.
- **G9 — Telemetry per model.** Every Completion Note and the final summary
  record which seat did what, with attempts, duration and token usage, so the
  roster can be tuned over time.
- **G10 — Prompt twins stay in parity.** `sdd-worker.md` is rewritten and its
  packaged twin re-synced; the new `sdd-coder.md` ships with a twin from day
  one; `test_subagent_parity.py` stays green.

### Non-Goals (explicitly out of scope)

- **Re-architecting the dev-loop.** `DevelopmentNode` / `DevAgentPool` keep
  their FEAT-323 behaviour. The only dev-loop code touched is additive: the
  `google-compat` backend, the `"sdd-coder"` subagent name, and the new
  `sdd_coder/` package they compose. (Brainstorm Option C — dev-loop as the
  orchestrator — was rejected; see the brainstorm.)
- **`/sdd-start` single-task path.** It keeps `writer_generate` (FEAT-543).
  Offering a one-task `coder_run_chunk` from `/sdd-start` is a follow-up.
- **The `gemini` CLI backend.** `GeminiCodeDispatcher` exists but the CLI is
  unusable on this account (corporate-only, deprecated in favour of `agy`); it
  is never part of the roster.
- **Validating `agy` (`google_coding`) as a live fallback seat.** The roster
  *may* declare `agent: google_coding` and the probe detects the binary, but
  live validation is a follow-up (§8).
- **In-process adapters for the native Anthropic/Google SDK clients**
  (translating OpenAI-shaped messages to `messages.create` /
  `generate_content`). Rejected in favour of the OpenAI-compatible endpoint.
- **A `ClaudeCodeDispatcher`-based Haiku seat.** Haiku is native to Claude
  Code; no nested headless session is spawned from the MCP server.
- **Honouring the index `parallel` flag for scheduling.** `depends_on` is the
  only scheduling input (current `TaskScheduler` behaviour); `parallel` /
  `parallelism_notes` are displayed, never acted on.
- **Requiring Redis.** Dispatch telemetry to Redis is best-effort.

---

## 2. Architectural Design

### Overview

`sdd-worker` (Sonnet, Claude Code agent) becomes a **planner/consolidator
loop** around a new local MCP server, `parrot-sdd-coder`, that exposes the
FEAT-323 machinery as an "orchestration kernel":

1. **Plan.** `coder_plan(feature, worktree)` re-reads
   `sdd/tasks/index/<feature>.json` from the feature worktree through
   `TaskScheduler` (status `done` ⇒ done; anything else ⇒ pending, so the
   existing "mark all in-progress" startup step is compatible), computes the
   next wave and slices it into **chunks of at most `len(available_roster)`
   tasks**. Inside a chunk, task → seat is a bijection; the starting seat
   rotates between chunks so every model sees a mix of tasks over a feature.
   Tasks assigned to the `native` seat (Haiku) are flagged for `sdd-worker` to
   run itself. The plan also lists orphan `<feature-branch>--TASK-NNN` branches
   left by an earlier crash. The plan is **stateless**: the per-spec index is
   the single source of truth, and `sdd-worker`'s step (g) advances it.
2. **Dispatch (MCP seats).** `coder_run_chunk(feature, worktree, task_ids)`
   creates one sub-worktree + branch per task via `SubWorktreeManager`
   (keyed by task id: branch `<feature-branch>--TASK-NNN`), builds a
   `DevAgentPool` whose workers are the chunk's seats **in plan order**
   (`count=1` each), and calls `run_wave` with `cwd_for(task_id)` → the task's
   sub-worktree. Because `len(chunk) ≤ len(workers)`, `run_wave`'s
   `workers[i % len(workers)]` assignment is injective and its built-in retry
   (`_next_worker`) lands on a **different** seat by construction. The brief
   is a `TaskScopedBrief` (`task_id`, `task_file`) and every profile's
   `subagent` is `"sdd-coder"`. The call returns a **job id immediately**.
3. **Dispatch (native seat).** For a task the plan flags `native`,
   `sdd-worker` calls `coder_prepare_native(feature, worktree, task_id)` to
   get the sub-worktree path and launches `Agent(sdd-coder, model: haiku)`
   with the task file and that cwd **in the same turn** as `coder_run_chunk`,
   so the chunk really runs in parallel. When the agent returns, `sdd-worker`
   calls `coder_merge(feature, worktree, task_id)`.
4. **Consolidate.** For every finished task the kernel runs the **fidelity
   check** (`git diff --name-only <feature-branch>..<task-branch>` ⊆ files
   listed under the task's `## Files to Create / Modify`, and ∩ `sdd/` = ∅),
   then merges the branch sequentially into the feature branch. A clean merge
   ⇒ `merged`; a conflict ⇒ `git merge --abort`, branch kept, result
   `merge_conflict(branch, files)`; a fidelity failure ⇒ branch kept, result
   `fidelity_violation(unexpected_files)`; a failure after the cross-model
   retry ⇒ `failed(diagnostics)`.
5. **Wait.** `coder_wait(job_id, timeout_seconds ≤ 300)` blocks up to the
   timeout and returns the job snapshot (per-task outcome + attempts +
   usage). `sdd-worker` polls in a loop; jobs live in the server until
   `coder_cleanup`.
6. **Judgment (Sonnet).** `sdd-worker` resolves `merge_conflict` branches by
   merging manually in the feature worktree, re-runs each merged task's
   acceptance criteria (integration with sibling branches can break them),
   implements `failed` tasks itself (attempt 3, existing steps c–f), then
   performs step (g) for each task with a Completion Note that records seat,
   backend, model, attempts, duration and tokens. It loops
   `plan → run_chunk/prepare_native → wait → merge → (g)` until the plan is
   empty, runs `code-reviewer` with the neutral brief, applies 🔴/🟠 fixes,
   pushes, and prints the summary with a **per-model table**.

**Seat routing (decided in the brainstorm — not renegotiable):**

| Roster seat | Kind | `DevAgentBackend` | Dispatcher | Model id (default) |
|---|---|---|---|---|
| Qwen3-Coder on Bedrock | mcp | `nova` | `NovaCodeDispatcher` (bedrock-mantle, OpenAI-compatible) | `qwen.qwen3-coder-480b-a35b-instruct` |
| Gemini 3.5 Flash | mcp | `google-compat` (**new**) | `GoogleCompatCodeDispatcher` (**new**) over `GeminiOpenAICompatClient` (**new**) | `gemini-3.5-flash` |
| GPT-5.3-codex-spark | mcp | `codex` | `CodexCodeDispatcher` (`codex exec --json`) | `gpt-5.3-codex-spark` (fallback `gpt-5.3-codex`) |
| Claude Haiku | native | — | Claude Code `Agent` tool + `.claude/agents/sdd-coder.md` (`model: haiku`) | `haiku` |

Two facts from the brainstorm shape this table: the `bedrock:` provider key of
`LLMFactory` resolves to `AnthropicClient(backend="bedrock")`, not Qwen; and
`GoogleGenAIClient` / `AnthropicClient` / `BedrockConverseClient` expose no
`_chat_completion`, so the in-process loop cannot drive them — hence the
OpenAI-compatible endpoint for Gemini and the native sub-agent for Haiku.

**Gemini seat (verified live).** `GeminiOpenAICompatClient(OpenAIBaseClient)`
is the `BedrockMantleClient` template pointed at
`https://generativelanguage.googleapis.com/v1beta/openai/` with the key read
through `navconfig` (`config.get("GEMINI_API_KEY")`, then `GOOGLE_API_KEY`).
`GoogleCompatCodeDispatcher(LLMCodeDispatcher)` swaps `client_factory` (Nova
pattern) and adds exactly two overrides: `_completion_args` (adds
`reasoning_effort`, never `extra_body`) and `_tool_call_to_openai_dict`, which
carries the raw tool call's `extra_content` (`{"google": {"thought_signature":
…}}`) into the echoed assistant turn — Gemini 3 returns HTTP 400 without it.

### Component Diagram

```
Claude Code session (Sonnet)                       parrot-sdd-coder  (stdio MCP: `parrot mcp-local sdd-coder`)
┌───────────────────────────────────┐              ┌──────────────────────────────────────────────────────┐
│ sdd-worker.md  (orchestrator)     │  coder_plan  │ SddCoderToolkit ──► SddCoderEngine                   │
│  loop:                            │─────────────►│   ├─ RosterProbe (navconfig keys · which · smoke)    │
│   plan → dispatch → wait → merge  │ run_chunk    │   ├─ ChunkAssigner (bijection, rotating start)       │
│   → ACs → step (g) → …            │─────────────►│   ├─ TaskScheduler ◄── sdd/tasks/index/<feat>.json   │
│   → code-reviewer → fixes → push  │ prepare_nat. │   ├─ SubWorktreeManager (branch <feat>--TASK-NNN)    │
│                                   │─────────────►│   ├─ DevAgentPool.run_wave ──► build_dispatcher       │
│  Agent(sdd-coder, model: haiku)   │ wait/status  │   │      ├─ nova ──────► NovaCodeDispatcher           │
│   cwd = sub-worktree (native)     │◄─────────────│   │      ├─ google-compat ► GoogleCompatCodeDispatcher│
│                                   │ merge        │   │      └─ codex ─────► CodexCodeDispatcher          │
│                                   │─────────────►│   ├─ FidelityCheck (task file ⊆ diff, no sdd/)      │
│                                   │ cleanup      │   └─ JobTable (asyncio tasks, snapshots)             │
└───────────────────────────────────┘              └──────────────────────────────────────────────────────┘
          │ step (g): index · mv completed/ · Completion Note (seat, attempts, duration, tokens)
          ▼
   feature worktree  .claude/worktrees/feat-<ID>-<slug>/   (base for every sub-worktree, R4 check)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/flows/dev_loop/task_scheduler.py` (`TaskScheduler`, `TaskRef`) | uses (unchanged) | waves from the per-spec index; `mark_done` is not used — the index is re-read each plan |
| `parrot/flows/dev_loop/agent_pool.py` (`DevAgentPool`, `WaveResult`) | uses (unchanged) | one pool per chunk, workers in plan order, `count=1`; `run_wave` retry = different seat |
| `parrot/flows/dev_loop/worktree_manager.py` (`SubWorktreeManager`) | uses (unchanged) | keyed by `task_id` instead of `worker_id`; `merge_sequential(resolver=None)`; `cleanup(keep_on_conflict=True)` |
| `parrot/flows/dev_loop/agent_builder.py` (`build_dispatcher`) | extends | new `google-compat` branch |
| `parrot/flows/dev_loop/models/base.py` (`DevAgentBackend`, `DevAgentSpec`, `TaskScopedBrief`, `ResearchOutput`, `DevelopmentOutput`, `WorkerSummary`, `DispatchLabels`) | extends / uses | `DevAgentBackend += "google-compat"`; `TaskScopedBrief` wraps a synthetic `ResearchOutput` |
| `parrot/flows/dev_loop/dispatchers/llm.py` (`LLMCodeDispatcher`) | subclassed | `GoogleCompatCodeDispatcher` overrides `_completion_args`, `_tool_call_to_openai_dict`, `client_factory` |
| `parrot/flows/dev_loop/dispatchers/nova.py` (`NovaCodeDispatcher`) | template + roster seat | pattern for the Gemini dispatcher; Qwen seat |
| `parrot/flows/dev_loop/dispatchers/codex.py` (`CodexCodeDispatcher`) | roster seat (unchanged) | codex-spark seat |
| `parrot/flows/dev_loop/models/{llm,gemini,codex,claude,google_coding}.py` | extends | `"sdd-coder"` added to every `subagent` literal |
| `parrot/flows/dev_loop/_subagent_defs.py` + `_subagent_data/` | extends | `"sdd-coder"` in `_VALID_NAMES`; new `_subagent_data/sdd-coder.md`; re-synced `sdd-worker.md` |
| `parrot/clients/openai_base.py` (`OpenAIBaseClient`) | subclassed | `GeminiOpenAICompatClient` (in ai-parrot-client-google) |
| `parrot/clients/amazon/nova/mantle.py` (`BedrockMantleClient`) | template | shape of the compat client (142 lines, no `gpt-*` defaults) |
| `parrot/mcp/toolkit_config.py`, `toolkit_server.py`, `local_cli.py` | uses (unchanged) | `sdd-coder` section in `.parrot/mcp-toolkits.yaml`; served by `parrot mcp-local sdd-coder` |
| `parrot/tools/toolkit.py` (`AbstractToolkit`) | subclassed | `SddCoderToolkit`; `auto_open=True` wires `_open()` (probe) |
| `parrot/conf.py` (`WORKTREE_BASE_PATH`, `REDIS_URL`, `config`) | depends on | sub-worktrees under the base (R4); Redis optional; keys via `navconfig` |
| `.claude/agents/sdd-worker.md` | modifies | Execution Loop → orchestrator loop; step b2 removed; `tools:` gains the MCP tool names |
| `.claude/agents/sdd-coder.md` | new | `model: haiku`; task-scoped, code-only |
| `.mcp.json`, `.parrot/mcp-toolkits.yaml` (both git-ignored), `examples/sdd-coder-mcp.yaml` (tracked) | config | operator installs from the tracked example |
| `packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py` | extends (auto) | discovers the new twin |
| `docs/mcp-local-toolkits.md`, `docs/dev_loop/` | docs | install + roster semantics + orchestrator loop |

### Data Models

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py  (new)
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from parrot.flows.dev_loop.models import DevAgentBackend, DevelopmentOutput  # verified: models/base.py:407, :497

SeatKind = Literal["mcp", "native"]
TaskOutcome = Literal[
    "queued", "running", "merged", "merge_conflict", "failed",
    "fidelity_violation", "retry_native",
]

class RosterSeat(BaseModel):
    """One seat of the model roster (config-driven, G8)."""
    label: str                                  # e.g. "qwen", "gemini", "codex-spark", "haiku"
    kind: SeatKind = "mcp"
    backend: Optional[DevAgentBackend] = None   # required when kind == "mcp"
    model: str = ""                             # '' ⇒ backend default (agent_builder)
    fallback_model: str = ""                    # used when the probe's smoke call rejects `model`

class RosterConfig(BaseModel):
    seats: List[RosterSeat] = Field(..., min_length=1)
    wait_timeout_max_s: int = Field(default=300, ge=10, le=300)
    smoke_timeout_s: int = Field(default=60, ge=5, le=300)

class SeatProbeResult(BaseModel):
    label: str; kind: SeatKind; backend: Optional[str] = None
    available: bool; model_used: str = ""; fallback_used: bool = False; reason: str = ""

class PlannedTask(BaseModel):
    task_id: str; task_file: str; title: str = ""
    seat_label: str; native: bool = False; backend: Optional[str] = None; model: str = ""

class PlanChunk(BaseModel):
    index: int; tasks: List[PlannedTask]

class OrphanBranch(BaseModel):
    task_id: str; branch: str; worktree_path: str = ""; commits: int = 0; files: List[str] = []

class CoderPlan(BaseModel):
    feature_id: str; feature: str; feature_branch: str; index_path: str
    pending: List[str]; blocked: List[str]            # blocked = pending tasks with unsatisfied deps
    chunks: List[PlanChunk]                            # next wave, sliced
    roster: List[SeatProbeResult]; orphan_branches: List[OrphanBranch]

class AttemptRecord(BaseModel):
    attempt: int; seat_label: str; backend: str = ""; model: str = ""
    started_at: str; ended_at: str = ""; duration_s: float = 0.0
    usage: Dict[str, Any] = {}; error: str = ""

class TaskResult(BaseModel):
    task_id: str; outcome: TaskOutcome; branch: str = ""; worktree_path: str = ""
    attempts: List[AttemptRecord] = []
    conflict_files: List[str] = []; unexpected_files: List[str] = []; diagnostics: str = ""
    development_output: Optional[DevelopmentOutput] = None

class NativePrep(BaseModel):
    task_id: str; task_file: str; branch: str; worktree_path: str; seat_label: str

class CoderJob(BaseModel):
    job_id: str; feature_id: str; chunk_task_ids: List[str]
    state: Literal["running", "done", "error"]; started_at: str; ended_at: str = ""
    tasks: List[TaskResult]; error: str = ""

class CleanupReport(BaseModel):
    removed: List[str]; kept: List[str]

class CoderError(BaseModel):
    code: str; message: str; details: Dict[str, Any] = {}

class CoderResult(BaseModel):
    """Tool envelope — the `OperationResult` shape of parrot_tools, re-declared in core
    because core MUST NOT import parrot_tools (dependency direction)."""
    status: Literal["ok", "error"]; operation: str
    data: Dict[str, Any] = {}; error: Optional[CoderError] = None; elapsed_ms: int = 0
```

Error codes (`CoderError.code`, snake_case, closed set): `feature_not_found`,
`index_unreadable`, `dependency_cycle`, `worktree_outside_base`, `task_not_pending`,
`task_not_in_plan`, `seat_unavailable`, `roster_empty`, `job_not_found`,
`branch_not_found`, `dirty_feature_worktree`, `merge_conflict`, `fidelity_violation`,
`internal_error`.

### New Public Interfaces

```python
# parrot.flows.dev_loop.sdd_coder  (new package, core)
from parrot.flows.dev_loop.sdd_coder import SddCoderToolkit, SddCoderEngine, RosterConfig, RosterProbe, ChunkAssigner

# MCP tools exposed by SddCoderToolkit (Claude Code names: mcp__parrot-sdd-coder__<tool>)
coder_plan(feature: str, worktree: str) -> CoderResult[data=CoderPlan]
coder_run_chunk(feature: str, worktree: str, task_ids: list[str]) -> CoderResult[data=CoderJob]   # returns immediately
coder_prepare_native(feature: str, worktree: str, task_id: str) -> CoderResult[data=NativePrep]
coder_merge(feature: str, worktree: str, task_id: str) -> CoderResult[data=TaskResult]
coder_wait(job_id: str, timeout_seconds: int = 120) -> CoderResult[data=CoderJob]    # timeout_seconds ≤ 300
coder_status(job_id: str) -> CoderResult[data=CoderJob]
coder_cleanup(feature: str, worktree: str, keep_conflicted: bool = True) -> CoderResult[data=CleanupReport]

# Gemini seat
from parrot.clients.google import GeminiOpenAICompatClient            # provider key "google-compat"
from parrot.flows.dev_loop import GoogleCompatCodeDispatcher, GoogleCompatCodeDispatchProfile
DevAgentBackend  # += "google-compat"
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: `sdd_coder/models.py` | yes | Pydantic models exactly as in §2 Data Models; closed error-code set; no logic | — |
| M2: `sdd_coder/roster.py` | yes | `RosterProbe` + `ChunkAssigner` signatures in §3; probe rules per backend fixed in §7; pure functions, injectable `config_getter`/`which`/`smoke` | — |
| M3: Gemini compat seat (client + profile + dispatcher + backend) | yes | Copies `BedrockMantleClient` / `NovaCodeDispatcher` verbatim; the two overrides are specified line-by-line (§3 M3, §7) | — |
| M4: `sdd_coder/engine.py` | **no** | Composes pool/worktrees/jobs; branch-naming, job lifecycle and merge/fidelity ordering are fixed, but the asyncio job table and error mapping need judgment | thinking model implements |
| M5: `sdd_coder/toolkit.py` + config/example + `.mcp.json` docs | yes | Thin `AbstractToolkit` over `SddCoderEngine`; one method per tool; `CoderResult` envelope; yaml section shape fixed in §7 | — |
| M6: `sdd-coder` prompt + twin + `_VALID_NAMES` + subagent literals | yes | Prompt content derived from `sdd-worker.md` task-scoped mode (sections named in §3 M6); literal edits are one-line | — |
| M7: `sdd-worker.md` orchestrator rewrite + twin sync | **no** | Replaces the Execution Loop with the loop in §2 Overview; prose quality and completeness of STOP conditions need the thinking model | thinking model implements |
| M8: Tests (unit + git-sandbox integration) | yes | Test names and fixtures fixed in §4 | — |
| M9: Docs | yes | Files and sections fixed in §3 M9 | — |

### Module 1: Data models — `sdd_coder/models.py`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` (new) + `sdd_coder/__init__.py` (new)
- **Responsibility**: every Pydantic payload of the kernel (§2 Data Models), the closed error-code set, and the `CoderResult` tool envelope.
- **Depends on**: `parrot.flows.dev_loop.models` (`DevAgentBackend`, `DevelopmentOutput`).
- **Interface Skeleton**: exactly the §2 Data Models block. `__init__.py` re-exports `SddCoderToolkit`, `SddCoderEngine`, `RosterConfig`, `RosterSeat`, `RosterProbe`, `ChunkAssigner`, `CoderPlan`, `CoderJob`, `TaskResult`, `CoderResult`. **Import discipline** (verified: `agent_pool.py` module docstring): import from `parrot.flows.dev_loop.models` / `.agent_pool` / `.task_scheduler` / `.worktree_manager` / `.agent_builder` **submodules**, never from the `parrot.flows.dev_loop` package, to avoid the documented partial-initialisation cycle.

### Module 2: Roster probe + chunk assigner — `sdd_coder/roster.py`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py` (new)
- **Responsibility**: (a) probe each configured seat for availability (credentials via `navconfig`, CLI presence, optional smoke call, `fallback_model` switch); (b) slice a wave into chunks with a task→seat bijection and rotating start; (c) pick the retry seat.
- **Depends on**: M1; `parrot.conf.config` (navconfig); `shutil.which`; `parrot.flows.dev_loop.task_scheduler.TaskRef`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py  (new)
  from parrot import conf                                  # verified: parrot/conf.py (config = navconfig.config)
  from parrot.flows.dev_loop.task_scheduler import TaskRef  # verified: task_scheduler.py:25

  SmokeFn = Callable[[RosterSeat, str], Awaitable[bool]]   # (seat, model_id) -> reachable?

  class RosterProbe:
      """Decides which configured seats are usable right now (G8)."""
      def __init__(self, *, config_getter: Callable[..., Any] = conf.config.get,
                   which: Callable[[str], Optional[str]] = shutil.which,
                   smoke: Optional[SmokeFn] = None, smoke_timeout_s: int = 60) -> None: ...
      async def probe(self, roster: RosterConfig) -> List[SeatProbeResult]:
          """One result per seat, in roster order. Never raises; a seat whose check
          throws is reported unavailable with the exception text as `reason`.
          Rules per backend are fixed in §7 "Probe rules"."""

  def available_seats(roster: RosterConfig, results: List[SeatProbeResult]) -> List[RosterSeat]:
      """Seats with available=True, in roster order, with `model` replaced by `model_used`."""

  class ChunkAssigner:
      """Distinct-model chunking (G2). Stateful only for the rotating start index."""
      def __init__(self, seats: List[RosterSeat]) -> None: ...   # raises ValueError on empty
      def assign(self, wave: List[TaskRef], task_files: Dict[str, str]) -> List[PlanChunk]:
          """Deterministic: tasks sorted by id; chunk k holds tasks [k*n:(k+1)*n] with n=len(seats);
          task j of a chunk gets seats[(start + j) % n]; `start` advances by len(chunk) after each
          chunk so consecutive chunks begin on different seats. Never assigns one seat twice in a chunk."""
      def retry_seat(self, failed_label: str, exclude: Set[str]) -> Optional[RosterSeat]:
          """Next seat after `failed_label` in roster order not in `exclude`; None if none left."""
  ```

### Module 3: Gemini OpenAI-compatible seat (`google-compat`)
- **Path**: `packages/ai-parrot-client-google/src/parrot/clients/google/openai_compat.py` (new), `packages/ai-parrot-client-google/src/parrot/clients/google/__init__.py` (modifies lines 1–7), `packages/ai-parrot-client-google/pyproject.toml` (modifies entry points, lines 25–27), `packages/ai-parrot/src/parrot/flows/dev_loop/models/google_compat.py` (new), `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_compat.py` (new), `models/base.py:407` (`DevAgentBackend`), `agent_builder.py:135-262` (new branch), `models/__init__.py` + `dispatchers/__init__.py` + `flows/dev_loop/__init__.py` (exports).
- **Responsibility**: drive Gemini through Google's OpenAI-compatible endpoint with the unchanged `LLMCodeDispatcher` loop; honour the Gemini 3 `thought_signature` echo.
- **Depends on**: `OpenAIBaseClient`, `LLMCodeDispatcher`, `LLMCodeDispatchProfile`, `NovaCodeDispatcher` (template only).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-client-google/src/parrot/clients/google/openai_compat.py  (new; template: amazon/nova/mantle.py:35-142)
  from ..openai_base import OpenAIBaseClient            # verified: parrot/clients/openai_base.py:66 (class), :89 (__init__(api_key, base_url, **kwargs))
  from navconfig import config                           # verified: google/client.py:189 uses config.get("GOOGLE_API_KEY")

  GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

  class GeminiOpenAICompatClient(OpenAIBaseClient):
      """Gemini via Google's OpenAI-compatible endpoint. Carries NO _default_model /
      _fallback_model / _lightweight_model (same rule as BedrockMantleClient, mantle.py:35)."""
      def __init__(self, api_key: str | None = None, base_url: str | None = None, **kwargs) -> None:
          """key = api_key or config.get("GEMINI_API_KEY") or config.get("GOOGLE_API_KEY");
          raises ValueError naming both keys when none resolves. base_url defaults to GEMINI_OPENAI_BASE_URL."""

  # google/__init__.py: add `from .openai_compat import GeminiOpenAICompatClient` + __all__ entry
  # pyproject.toml [project.entry-points."parrot.clients"]: google-compat = "parrot.clients.google:GeminiOpenAICompatClient"

  # packages/ai-parrot/src/parrot/flows/dev_loop/models/google_compat.py  (new; template: models/nova.py:93)
  class GoogleCompatCodeDispatchProfile(LLMCodeDispatchProfile):   # verified: models/llm.py:10
      model: str = "gemini-3.5-flash"
      llm: str = "google-compat:gemini-3.5-flash"
      reasoning_effort: Literal["none", "low", "medium", "high"] = "none"
      # `enable_thinking` MUST stay False: extra_body.chat_template_kwargs is silently ignored by Google's layer.

  # packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_compat.py  (new; template: dispatchers/nova.py:66-140)
  class GoogleCompatCodeDispatcher(LLMCodeDispatcher):            # verified: dispatchers/llm.py:51
      def __init__(self, *, max_concurrent: int, redis_url: str, stream_ttl_seconds: int) -> None:
          """super().__init__(..., client_factory=self._create_compat_client)."""
      def _create_compat_client(self, llm: str, *, model_args: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Any:
          """LLMFactory.parse_llm_string(llm) -> model; returns GeminiOpenAICompatClient(model=..., temperature/max_tokens from model_args)."""
      def _completion_args(self, profile: LLMCodeDispatchProfile, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
          """super()._completion_args minus any `extra_body`, plus `reasoning_effort` from the profile."""   # verified: llm.py:949
      def _tool_call_to_openai_dict(self, call: Any, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
          """super() dict + `extra_content` copied verbatim from `call` when present (object attr or dict key).
          Required: Gemini 3 answers HTTP 400 'Function call is missing a thought_signature' otherwise."""  # verified: llm.py:2237

  # models/base.py:407  DevAgentBackend = Literal[..., "nova", "google-compat"]
  # agent_builder.py (after the `nova` branch, line ~253):
  #   if spec.agent == "google-compat": dispatcher = GoogleCompatCodeDispatcher(**common);
  #       profile = GoogleCompatCodeDispatchProfile(llm=f"google-compat:{model}", model=model, max_turns=llm_max_turns,
  #                 reasoning_effort=config_getter("DEV_LOOP_GOOGLE_COMPAT_REASONING_EFFORT", "none"))
  #       with model = spec.model or config_getter("DEV_LOOP_GOOGLE_COMPAT_MODEL", "gemini-3.5-flash")
  ```

### Module 4: Orchestration engine — `sdd_coder/engine.py`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (new), `sdd_coder/fidelity.py` (new), `sdd_coder/jobs.py` (new)
- **Responsibility**: plan / run_chunk / prepare_native / merge / wait / status / cleanup over `TaskScheduler`, `SubWorktreeManager`, `DevAgentPool`, `build_dispatcher`; fidelity check; asyncio job table; orphan-branch discovery.
- **Depends on**: M1, M2, M3 (for the `google-compat` backend to be buildable); FEAT-323 modules unchanged.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py  (new)
  class FidelityReport(BaseModel):
      ok: bool; expected: List[str]; changed: List[str]; unexpected: List[str]; sdd_touched: List[str]

  def parse_task_files(task_md: str) -> List[str]:
      """Repo-relative paths listed under '## Files to Create / Modify' of a TASK file
      (heading verified: sdd/templates/task.md:33); backtick-quoted first token of each bullet."""
  def check_fidelity(expected: List[str], changed: List[str]) -> FidelityReport:
      """ok ⇔ changed ⊆ expected and no changed path starts with 'sdd/'."""

  # packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py  (new)
  class JobTable:
      """In-memory registry of running/finished CoderJob snapshots (one MCP server process)."""
      def create(self, feature_id: str, task_ids: List[str], runner: Callable[[], Awaitable[List[TaskResult]]]) -> CoderJob: ...
      def get(self, job_id: str) -> CoderJob: ...                       # raises KeyError → job_not_found
      async def wait(self, job_id: str, timeout_s: float) -> CoderJob:  # returns snapshot even on timeout (state stays "running")
      def snapshot(self, job_id: str) -> CoderJob: ...

  # packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py  (new)
  from parrot.flows.dev_loop.task_scheduler import TaskScheduler        # verified: task_scheduler.py:53, from_index_file :88, next_wave :176
  from parrot.flows.dev_loop.agent_pool import DevAgentPool, WaveResult  # verified: agent_pool.py:135, build :155, run_wave :435
  from parrot.flows.dev_loop.worktree_manager import SubWorktreeManager, SubWorktreeMergeError  # verified: worktree_manager.py:75, :41
  from parrot.flows.dev_loop.agent_builder import build_dispatcher       # verified: agent_builder.py:135
  from parrot.flows.dev_loop.models import (DevAgentPoolConfig, DevAgentSpec, ResearchOutput, DevelopmentOutput)  # verified: models/base.py:438, :412, :340-379, :497

  class SddCoderEngine:
      """Stateless-by-design kernel: every call re-reads the per-spec index from `worktree`."""
      def __init__(self, *, roster: RosterConfig, probe: Optional[RosterProbe] = None,
                   redis_url: Optional[str] = None, worktree_base_path: Optional[str] = None,
                   dispatcher_builder: Callable[..., Any] = build_dispatcher,
                   stream_ttl_seconds: int = 3600) -> None: ...
      async def open(self) -> None:
          """Runs the probe once and caches `self.seats` (available_seats). Idempotent."""
      async def plan(self, feature: str, worktree: str) -> CoderPlan:
          """Resolve feature (index header match, same order as sdd-worker.md §1), TaskScheduler.from_index_file,
          next_wave → ChunkAssigner.assign; orphan branches = `git branch --list '<feature_branch>--TASK-*'` minus running jobs.
          Raises CoderFailure(code) for feature_not_found / index_unreadable / dependency_cycle / worktree_outside_base / roster_empty."""
      async def run_chunk(self, feature: str, worktree: str, task_ids: List[str]) -> CoderJob:
          """Validates task_ids ⊆ current plan's first chunk's mcp tasks (task_not_in_plan otherwise); creates sub-worktrees
          (SubWorktreeManager.create(task_id)); builds a pool with the chunk's seats IN PLAN ORDER (count=1, isolation 'isolated');
          registers a JobTable job whose runner awaits pool.run_wave(...) then _consolidate() per task; returns immediately."""
      async def prepare_native(self, feature: str, worktree: str, task_id: str) -> NativePrep:
          """Sub-worktree for a `native` planned task; branch <feature_branch>--<task_id>."""
      async def merge(self, feature: str, worktree: str, task_id: str) -> TaskResult:
          """_consolidate() for one branch: fidelity check → merge_sequential(resolver=None) on that branch only.
          Used for native tasks and for re-merging after Sonnet fixed a conflict."""
      async def wait(self, job_id: str, timeout_seconds: int) -> CoderJob:
          """min(timeout_seconds, roster.wait_timeout_max_s); never raises on timeout."""
      def status(self, job_id: str) -> CoderJob: ...
      async def cleanup(self, feature: str, worktree: str, keep_conflicted: bool = True) -> CleanupReport: ...
      # internals (names fixed so tasks can reference them):
      def _research_for(self, *, feature_id: str, spec_path: str, feature_branch: str, worktree_path: str, repo_path: str, base_branch: str) -> ResearchOutput:
          """Synthetic ResearchOutput(jira_issue_key="", log_excerpts=[]) — TaskScopedBrief requires one."""
      async def _consolidate(self, manager: SubWorktreeManager, task_id: str, task_file: str) -> TaskResult: ...
      def _labels_for(self, task: PlannedTask) -> DispatchLabels: ...   # seat="sdd-coder.<label>"

  class CoderFailure(Exception):
      def __init__(self, code: str, message: str, **details: Any) -> None: ...
  ```

### Module 5: MCP toolkit + configuration — `sdd_coder/toolkit.py`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` (new), `examples/sdd-coder-mcp.yaml` (new, tracked), `docs/mcp-local-toolkits.md` (modifies: new section), operator-local `.parrot/mcp-toolkits.yaml` + `.mcp.json` (git-ignored — documented, not committed)
- **Responsibility**: expose the engine as seven MCP tools with the `CoderResult` envelope; map `CoderFailure` → `status="error"`; `_open()` runs the probe.
- **Depends on**: M4.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py  (new)
  from parrot.tools.toolkit import AbstractToolkit   # verified: parrot/tools/toolkit.py:206; __init__(**kwargs) :321; _open lifecycle (FEAT-391)

  class SddCoderToolkit(AbstractToolkit):
      """`parrot mcp-local sdd-coder` — orchestration kernel for the interactive sdd-worker (FEAT-549)."""
      llm_dependent_tools: frozenset = frozenset()     # verified attr: toolkit.py:294 — no tool needs section.llm
      def __init__(self, *, roster: List[Dict[str, Any]] | RosterConfig, redis_url: Optional[str] = None,
                   worktree_base_path: Optional[str] = None, **kwargs: Any) -> None:
          """kwargs come verbatim from the yaml `kwargs:` block (toolkit_server.py:113-117). auto_open=True."""
      async def _open(self) -> None: ...                # engine.open() — probe once
      async def coder_plan(self, feature: str, worktree: str) -> CoderResult: ...
      async def coder_run_chunk(self, feature: str, worktree: str, task_ids: List[str]) -> CoderResult: ...
      async def coder_prepare_native(self, feature: str, worktree: str, task_id: str) -> CoderResult: ...
      async def coder_merge(self, feature: str, worktree: str, task_id: str) -> CoderResult: ...
      async def coder_wait(self, job_id: str, timeout_seconds: int = 120) -> CoderResult: ...
      async def coder_status(self, job_id: str) -> CoderResult: ...
      async def coder_cleanup(self, feature: str, worktree: str, keep_conflicted: bool = True) -> CoderResult: ...
  ```
  ```yaml
  # examples/sdd-coder-mcp.yaml  (new, tracked) — copy into .parrot/mcp-toolkits.yaml
  toolkits:
    sdd-coder:
      class: parrot.flows.dev_loop.sdd_coder.toolkit.SddCoderToolkit
      kwargs:
        roster:
          - {label: qwen,        kind: mcp,    backend: nova,          model: qwen.qwen3-coder-480b-a35b-instruct}
          - {label: gemini,      kind: mcp,    backend: google-compat, model: gemini-3.5-flash}
          - {label: codex-spark, kind: mcp,    backend: codex,         model: gpt-5.3-codex-spark, fallback_model: gpt-5.3-codex}
          - {label: haiku,       kind: native, model: haiku}
  ```
  `.mcp.json` entry (operator-local): `"parrot-sdd-coder": {"command": "<venv>/bin/parrot", "args": ["mcp-local", "sdd-coder", "--config", ".parrot/mcp-toolkits.yaml"]}`. Claude Code exposes the tools as `mcp__parrot-sdd-coder__coder_plan` … `mcp__parrot-sdd-coder__coder_cleanup`.

### Module 6: `sdd-coder` sub-agent prompt + registrations
- **Path**: `.claude/agents/sdd-coder.md` (new), `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md` (new, byte-identical), `_subagent_defs.py:49-57` (`_VALID_NAMES`), `models/llm.py:18`, `models/gemini.py:22`, `models/codex.py:18`, `models/claude.py:18-27`, `models/google_coding.py:21` (subagent literals).
- **Responsibility**: the task-scoped, code-only coder prompt used by every seat (MCP dispatchers load it via `load_subagent_definition("sdd-coder")`; Claude Code loads the repo twin natively with `model: haiku`).
- **Depends on**: none (content derives from `.claude/agents/sdd-worker.md` lines 37–67 Cardinal Rules, 77–106 Task-Scoped Mode, 207–282 steps a–f).
- **Interface Skeleton** (markdown contract):
  ```markdown
  ---
  name: sdd-coder
  description: Task-scoped SDD coder. Implements exactly ONE task in the given sub-worktree, commits code only, never touches sdd/.
  model: haiku
  color: green
  permissionMode: bypassPermissions
  tools: Read, Write, Edit, MultiEdit, Bash, Glob, Grep        # NO Agent tool
  ---
  Sections (in order): Cardinal Rules (verbatim from sdd-worker) · Input (task_file, cwd = sub-worktree, feature branch) ·
  Steps a) read task b) verify Codebase Contract c) implement d) verification checklist e) run this task's acceptance tests
  f) commit `feat(<feature-slug>): TASK-<NNN> — <title>` (listed files only) · Forbidden: editing anything under sdd/,
  marking tasks, touching other tasks · Output: final message = single DevelopmentOutput JSON (files_changed from git) ·
  STOP conditions (same as sdd-worker).
  ```
  Literal edits: add `"sdd-coder"` to each `subagent` `Literal[...]` listed above and to `_VALID_NAMES`. `test_subagent_parity.py` (auto-parametrised over `_subagent_data/*.md`, line 42–44) then covers the twin without changes.

### Module 7: `sdd-worker.md` orchestrator loop + twin sync
- **Path**: `.claude/agents/sdd-worker.md` (modifies), `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` (full-file sync)
- **Responsibility**: replace "## Execution Loop" (lines 207–313) with the orchestrator loop of §2 Overview; delete step b2 (lines 229–251); add the MCP tool names to `tools:` (line 23); extend "## Completion" summary (lines 315–371) with the per-model table; keep Cardinal Rules, Startup Sequence, Task-Scoped Mode (still used by the dev-loop pool), Structured Output Contract and STOP conditions.
- **Depends on**: M5 (tool names), M6 (agent name).
- **Interface Skeleton** (markdown contract):
  ```markdown
  tools: Read, Write, Edit, MultiEdit, Bash, Glob, Grep, Agent, mcp__parrot-sdd-coder__coder_plan, mcp__parrot-sdd-coder__coder_run_chunk,
         mcp__parrot-sdd-coder__coder_prepare_native, mcp__parrot-sdd-coder__coder_merge, mcp__parrot-sdd-coder__coder_wait,
         mcp__parrot-sdd-coder__coder_status, mcp__parrot-sdd-coder__coder_cleanup

  ## Orchestrator Loop (FEAT-549)
  0. If `coder_plan` is unavailable (server missing) → print a warning and run the legacy sequential loop (kept as "## Fallback: Sequential Loop").
  1. plan = coder_plan(feature, worktree). Print roster (available/dropped + reasons), chunks with seat per task, orphan branches.
  2. For the FIRST chunk: in ONE message call coder_run_chunk(mcp task ids) AND, for each native task, coder_prepare_native then Agent(sdd-coder, model: haiku, cwd=<path>, prompt=<task_file>).
  3. Poll coder_wait(job_id, 120) until state != running. For native tasks, after the Agent returns call coder_merge.
  4. Per task outcome: merged → run its acceptance criteria in the feature worktree → step (g) with Completion Note fields
     `Seat / Backend / Model / Attempts / Duration / Tokens`; merge_conflict → resolve manually in the feature worktree, commit, coder_merge again;
     fidelity_violation → treat as failed; failed → attempt 3 yourself (steps c–f) in the feature worktree, then (g).
  5. coder_cleanup(keep_conflicted=true). Repeat from 1 until plan.chunks is empty and plan.pending is empty.
  6. Completion: code-reviewer neutral brief (unchanged) → fixes → push → summary + per-model table
     (seat · tasks · retries · failures · wall-clock · tokens).
  ```
  Deleted: "### b2) Delegated implementation" and its checklist line ("Delegated patch hunks were all reviewed before writer_apply?"). Twin: `cp .claude/agents/sdd-worker.md packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md`.

### Module 8: Tests
- **Path**: `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/` (new: `test_roster.py`, `test_fidelity.py`, `test_jobs.py`, `test_engine.py`, `test_toolkit.py`), `packages/ai-parrot/tests/flows/dev_loop/test_google_compat_dispatcher.py` (new), `packages/ai-parrot-client-google/tests/test_openai_compat_client.py` (new)
- **Responsibility**: §4 tables. Reuse the `git_sandbox` fixture pattern (`test_worktree_manager.py:36-37`) for engine/merge paths; fake dispatchers (no network) for the pool.
- **Depends on**: M1–M7.
- **Interface Skeleton**: n/a (tests; names fixed in §4).

### Module 9: Documentation
- **Path**: `docs/dev_loop/sdd-coder-orchestrator.md` (new), `docs/mcp-local-toolkits.md` (modifies: "sdd-coder" section after the tool-optimizations one), `.agent/CONTEXT.md` (modifies: one paragraph under "What Lives Where → flows/dev_loop")
- **Responsibility**: install steps (yaml + `.mcp.json`), roster semantics (distinct-model rule, chunking, fallback_model, probe reasons), the orchestrator loop, the Gemini `thought_signature` gotcha, the `GEMINI_API_KEY`-via-navconfig note.
- **Depends on**: M5, M7.
- **Interface Skeleton**: n/a (docs).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_roster_config_requires_backend_for_mcp` | M1 | `RosterSeat(kind="mcp", backend=None)` fails validation; `kind="native"` needs none |
| `test_coder_result_error_codes_closed_set` | M1 | every `CoderError.code` emitted by the engine is in the documented set |
| `test_probe_drops_seat_without_key` | M2 | fake `config_getter` returning `None` for `GEMINI_API_KEY`/`GOOGLE_API_KEY` ⇒ gemini unavailable with reason naming both keys |
| `test_probe_codex_requires_binary` | M2 | fake `which("codex") is None` ⇒ unavailable "CLI not found" |
| `test_probe_native_always_available` | M2 | `kind="native"` never probed, always available |
| `test_probe_switches_to_fallback_model` | M2 | smoke returns False for `model`, True for `fallback_model` ⇒ `model_used=fallback`, `fallback_used=True` |
| `test_probe_never_raises` | M2 | smoke raising ⇒ seat unavailable, reason = exception text |
| `test_assign_distinct_seats_per_chunk` | M2 | property test over 1–20 tasks × 1–4 seats: no seat repeats in a chunk; `len(chunk) ≤ len(seats)` |
| `test_assign_rotates_start_between_chunks` | M2 | 5 tasks over 4 seats: chunk 2 starts on seat index 1 |
| `test_assign_single_seat_is_serial` | M2 | 1 seat ⇒ every chunk has exactly one task |
| `test_retry_seat_is_different` | M2 | `retry_seat("qwen", exclude={"qwen"})` ≠ qwen; returns None when all excluded |
| `test_compat_client_key_resolution` | M3 | `GeminiOpenAICompatClient()` uses `GEMINI_API_KEY`, then `GOOGLE_API_KEY`, else `ValueError`; default base_url fixed |
| `test_compat_client_has_no_model_defaults` | M3 | `_default_model`/`_fallback_model`/`_lightweight_model` absent (mirrors mantle rule) |
| `test_compat_profile_defaults` | M3 | `llm == "google-compat:gemini-3.5-flash"`, `reasoning_effort == "none"`, `enable_thinking is False` |
| `test_compat_dispatcher_carries_extra_content` | M3 | `_tool_call_to_openai_dict(call_with_extra_content)` output contains `extra_content` verbatim; without it, no key |
| `test_compat_dispatcher_completion_args` | M3 | no `extra_body`, has `reasoning_effort`, keeps `tools`/`tool_choice`/`parallel_tool_calls`/`max_tokens` |
| `test_build_dispatcher_google_compat` | M3 | `build_dispatcher(DevAgentSpec(agent="google-compat"))` returns the new pair with env-driven model default |
| `test_parse_task_files_from_template_section` | M4 | parses `## Files to Create / Modify` bullets with backticked paths; ignores prose |
| `test_fidelity_rejects_unexpected_and_sdd` | M4 | changed ⊄ expected ⇒ `ok=False`, `unexpected` filled; any `sdd/` path ⇒ `sdd_touched` |
| `test_job_wait_returns_snapshot_on_timeout` | M4 | `wait(timeout=0.01)` on a slow runner returns `state="running"` without raising |
| `test_job_unknown_id` | M4 | `get("nope")` ⇒ `KeyError` mapped to `job_not_found` by the toolkit |
| `test_toolkit_exposes_seven_tools` | M5 | `get_tools()` names == the seven `coder_*` tools; no private method exposed |
| `test_toolkit_maps_failure_to_error_result` | M5 | `CoderFailure("feature_not_found")` ⇒ `CoderResult(status="error", error.code=...)` |
| `test_toolkit_wait_caps_timeout` | M5 | `coder_wait(timeout_seconds=900)` is clamped to `wait_timeout_max_s` (300) |
| `test_valid_names_include_sdd_coder` | M6 | `load_subagent_definition("sdd-coder")` returns a body containing "DevelopmentOutput" |
| `test_subagent_literals_accept_sdd_coder` | M6 | each profile class accepts `subagent="sdd-coder"` |
| `test_prompt_parity[sdd-coder]` / `[sdd-worker]` | M6/M7 | existing parametrised parity test passes for both twins |
| `test_worker_prompt_has_orchestrator_loop` | M7 | packaged `sdd-worker` body contains "## Orchestrator Loop" and no "writer_generate" |
| `test_worker_prompt_tools_list_mcp_names` | M7 | repo frontmatter `tools:` lists all seven `mcp__parrot-sdd-coder__*` names |

### Integration Tests
| Test | Description |
|---|---|
| `test_engine_plan_from_real_index` (git sandbox) | temp repo + feature branch + per-spec index with 5 tasks (2 waves) ⇒ plan has correct chunks for a 3-seat roster (2 chunks in wave 1) and `blocked` lists the dependent tasks |
| `test_engine_run_chunk_merges_clean_branches` | fake dispatchers write the listed files and commit; job ends `done`; every task `merged`; feature branch contains the commits; sub-worktrees removed by `cleanup` |
| `test_engine_retry_on_other_seat_then_failed` | fake dispatcher for seat A always raises; run_wave retries on seat B (fake succeeds) ⇒ `attempts` has 2 records with different seats; a second failure ⇒ outcome `failed` |
| `test_engine_fidelity_violation_keeps_branch` | fake coder touches an unlisted file ⇒ `fidelity_violation`, branch kept, feature branch unchanged |
| `test_engine_merge_conflict_reported_and_aborted` | two branches editing the same line ⇒ second is `merge_conflict`, base worktree clean (`git status --porcelain` empty), branch listed in `kept` |
| `test_engine_native_prepare_then_merge` | `prepare_native` creates the branch; a scripted commit in that worktree; `merge` ⇒ `merged` |
| `test_engine_orphans_listed_not_merged` | a stale `<feature>--TASK-0001` branch exists ⇒ appears in `plan.orphan_branches`; feature branch untouched |
| `test_engine_rejects_worktree_outside_base` | `worktree` not under `worktree_base_path` ⇒ `worktree_outside_base` |
| `test_mcp_local_serves_sdd_coder` | `create_toolkit_mcp_server("sdd-coder", config_path=examples/sdd-coder-mcp.yaml)` builds and lists the seven tools (no network; probe injected as no-op) |
| `test_gemini_compat_live_roundtrip` (**opt-in**, `-m live`, needs `GEMINI_API_KEY`) | one `read_file` tool call + tool-result echo through `GoogleCompatCodeDispatcher` primitives succeeds (guards the `thought_signature` fix against regressions) |

### Test Data / Fixtures
```python
@pytest.fixture
async def git_sandbox(tmp_path):        # reuse the shape of tests/flows/dev_loop/test_worktree_manager.py:36-37
    """Temp repo with `dev` + `feat-FEAT-549-demo` branches, a per-spec index (5 tasks: 3 independent,
    2 depending on the first), and TASK files with '## Files to Create / Modify' sections."""

@pytest.fixture
def three_seat_roster() -> RosterConfig:
    return RosterConfig(seats=[RosterSeat(label="a", backend="nova"), RosterSeat(label="b", backend="google-compat"),
                               RosterSeat(label="c", backend="codex")])

@pytest.fixture
def fake_dispatcher_builder():
    """(DevAgentSpec) -> (FakeDispatcher, profile). FakeDispatcher.dispatch(brief, profile, cwd, ...) writes the
    task's listed files in `cwd`, commits, and returns a DevelopmentOutput; configurable to raise or to touch extra files."""

@pytest.fixture
def noop_probe() -> RosterProbe:
    return RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/usr/bin/" + b, smoke=None)
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC-1 (G1)** In the git-sandbox integration test, a 5-task index with 2 waves is executed as 2 waves; wave-1 tasks run concurrently (fake dispatcher records overlapping start/end) and are merged sequentially into the feature branch.
- [ ] **AC-2 (G2)** `ChunkAssigner.assign` never assigns one seat twice within a chunk for any wave size 1–20 and roster size 1–4 (property test), and a wave larger than the roster is split into consecutive chunks with rotating start.
- [ ] **AC-3 (G3)** `parrot mcp-local sdd-coder --config examples/sdd-coder-mcp.yaml` starts and lists exactly the seven `coder_*` tools; `.claude/agents/sdd-worker.md` `tools:` names all seven as `mcp__parrot-sdd-coder__<tool>`.
- [ ] **AC-4 (G4)** `GoogleCompatCodeDispatcher._tool_call_to_openai_dict` preserves `extra_content`; `build_dispatcher(agent="google-compat")` returns the new dispatcher/profile; the opt-in live test performs one full tool round-trip against `gemini-3.5-flash` without HTTP 400.
- [ ] **AC-5 (G5)** The probe, chunker, fidelity check, job table and merge policy are covered by unit/integration tests that run without any LLM or network.
- [ ] **AC-6 (G6)** A seat failure is retried exactly once on a different seat (`attempts[1].seat_label != attempts[0].seat_label`); a second failure yields `outcome="failed"` with diagnostics, and `sdd-worker.md` instructs attempt 3 by the orchestrator.
- [ ] **AC-7 (G7)** A coder branch touching any `sdd/` path or a file not listed in the task is reported `fidelity_violation` and never merged; the `sdd-coder` prompt forbids editing `sdd/`.
- [ ] **AC-8 (G8)** No model id, roster or provider key appears in Python or in either prompt; seats come only from the yaml `kwargs.roster`; a seat without credentials/CLI is dropped with a reason and `sdd-worker` prints it.
- [ ] **AC-9 (G8)** A rejected primary model id switches to `fallback_model` in the probe and is reported (`fallback_used=True`).
- [ ] **AC-10 (G9)** `TaskResult.attempts[*]` carries seat, backend, model, duration and usage; `sdd-worker.md` step (g) writes them into the Completion Note and the final summary prints a per-model table.
- [ ] **AC-11 (G10)** `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -v` passes for `sdd-worker` and `sdd-coder`.
- [ ] **AC-12** `coder_wait` clamps to 300 s and returns a `running` snapshot on timeout; jobs survive until `coder_cleanup`.
- [ ] **AC-13** A merge conflict leaves the feature worktree clean (`git status --porcelain` empty), keeps the task branch, and is reported with the conflicting files.
- [ ] **AC-14** Orphan `<feature>--TASK-NNN` branches are listed by `coder_plan` and never merged automatically.
- [ ] **AC-15** Redis absent ⇒ one startup warning, no per-event noise, dispatch still completes (verified with the fake dispatcher + a bogus `redis_url`).
- [ ] **AC-16** `pytest packages/ai-parrot/tests/flows/dev_loop -v` passes with no regressions in the FEAT-323 suites (`test_agent_pool.py`, `test_task_scheduler.py`, `test_worktree_manager.py`, `test_pool_wiring.py`).
- [ ] **AC-17** `docs/dev_loop/sdd-coder-orchestrator.md` and the `docs/mcp-local-toolkits.md` section exist and document install, roster semantics, the loop, and the `thought_signature` / `navconfig` gotchas.
- [ ] **AC-18** `ruff check` and `mypy` pass on every new/modified Python file.
- [ ] **AC-19** No file under `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/` is modified (dev-loop path untouched, non-goal).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All anchors re-verified on `dev@a4dc8acf8` (2026-09-10); code files are
> unchanged since the brainstorm's `5bf8906a7`.

### Verified Imports
```python
from parrot.flows.dev_loop.task_scheduler import TaskRef, TaskScheduler                 # verified: task_scheduler.py:25, :53
from parrot.flows.dev_loop.agent_pool import DevAgentPool, PoolWorker, WaveResult, aggregate_outputs   # verified: agent_pool.py:135, :101, :119, :574
from parrot.flows.dev_loop.worktree_manager import SubWorktreeManager, SubWorktreeMergeError, MergeReport  # verified: worktree_manager.py:75, :41, :57
from parrot.flows.dev_loop.agent_builder import build_dispatcher                          # verified: agent_builder.py:135
from parrot.flows.dev_loop.models import (DevAgentBackend, DevAgentSpec, DevAgentPoolConfig, TaskScopedBrief,
                                          ResearchOutput, DevelopmentOutput, WorkerSummary, DispatchLabels,
                                          LLMCodeDispatchProfile, NovaCodeDispatchProfile)   # verified: models/base.py:407,412,438,458,340,497,481,763; models/__init__.py:76,80
from parrot.flows.dev_loop.dispatchers import (DevLoopCodeDispatcher, DispatchExecutionError,
                                               DispatchOutputValidationError, LLMCodeDispatcher, NovaCodeDispatcher)  # verified: dispatchers/__init__.py:28,33,37-47
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher                       # verified: dispatchers/llm.py:51
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition                 # verified: _subagent_defs.py:86
from parrot.mcp.toolkit_config import ToolkitSection, MCPToolkitsConfig, load_toolkits_config   # verified: toolkit_config.py:19, :79, :105
from parrot.mcp.toolkit_server import create_toolkit_mcp_server                           # verified: toolkit_server.py:29
from parrot.tools.toolkit import AbstractToolkit                                          # verified: parrot/tools/toolkit.py:206
from parrot.clients.factory import LLMFactory                                             # verified: clients/factory.py:163
from parrot.clients.openai_base import OpenAIBaseClient                                   # verified: clients/openai_base.py:66 (absolute form of the relative import used by mantle.py:12)
from parrot.clients.google import GoogleGenAIClient, GeminiLiveClient, GoogleModel        # verified: google/__init__.py:1-3
from parrot import conf                                                                   # verified: conf.WORKTREE_BASE_PATH :829, conf.REDIS_URL :298, conf.config (navconfig)
from navconfig import config                                                              # verified: used at google/client.py:189
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py
class TaskRef(BaseModel):                                   # line 25: id, title="", status, depends_on=[], file=""
class TaskScheduler:                                        # line 53
    def __init__(self, tasks: List[TaskRef]) -> None        # line 64 — status=="done" → done set, ANY other status → pending set
    @classmethod
    def from_index_file(cls, path: Path) -> Optional["TaskScheduler"]   # line 88 — None when unreadable; ValueError on depends_on cycle
    def next_wave(self) -> List[TaskRef]                    # line 176 — pending with all deps in done; unordered
    def mark_done(self, task_id: str) -> None               # line 194
    def mark_failed(self, task_id: str) -> None             # line 203 — propagates `skipped` transitively
    def pending(self) / failed() / skipped() / done() -> List[TaskRef]   # lines 246-258

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py
INTERNAL_ERROR_PREFIX = "internal error:"                   # line 50
class PoolWorker:                                           # line 101 — worker_id: str, spec: DevAgentSpec, dispatcher, profile
class WaveResult:                                           # line 119 — completed: Dict[str, DevelopmentOutput], failed: List[str], worker_summaries: List[WorkerSummary]
class DevAgentPool:                                         # line 135
    def __init__(self, *, config: DevAgentPoolConfig, workers: List[PoolWorker], pool_max: int)     # line 138
    @classmethod
    def build(cls, config: DevAgentPoolConfig,
              dispatcher_builder: Callable[[DevAgentSpec], Tuple[DevLoopCodeDispatcher, BaseModel]],
              pool_max: int) -> "DevAgentPool"              # line 155 — workers named development.w1..wN in declared order
    def _next_worker(self, failed_worker: PoolWorker) -> PoolWorker   # line 198 — (idx+1) % len(workers); same worker when only one
    async def run_wave(self, tasks: List[TaskRef], *, research: ResearchOutput, run_id: str,
                       cwd_for: Callable[[str], str], escalate: bool = False,
                       session_host: Optional[Any] = None) -> WaveResult   # line 435 — assignment tasks[i] -> workers[i % len(workers)]
def aggregate_outputs(results: List[WaveResult], incomplete: List[str]) -> DevelopmentOutput   # line 574

# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py
Resolver = Callable[[str, str], Awaitable[bool]]             # line 39
class SubWorktreeMergeError(Exception)                       # line 41 — .branch, .worktree_path, .stderr
class MergeReport(BaseModel)                                 # line 57 — merged, conflicts_resolved, kept_for_inspection: List[str]
class SubWorktreeManager:                                    # line 75
    def __init__(self, *, base_worktree: str, feature_branch: str, worktree_base_path: str)   # line 78
    @staticmethod
    def _branch_suffix(worker_id: str) -> str                # line 134 — replaces "." with "-"
    async def create(self, worker_id: str) -> str            # line 146 — branch f"{feature_branch}--{suffix}", path <base>/<feature_branch>--pool/<suffix>; raises SubWorktreeMergeError
    async def merge_sequential(self, *, resolver: Optional[Resolver] = None) -> MergeReport   # line 181 — resolver None ⇒ `git merge --abort` then raise SubWorktreeMergeError; branch kept
    async def refresh_all(self) -> None                      # line 264
    async def cleanup(self, *, keep_on_conflict: bool = True) -> None   # line 297 — `git worktree remove --force` + prune; skips conflicted when keep_on_conflict

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py
ConfigGetter = Callable[..., Any]                            # line 63
ENV_LLM_MAX_TURNS = "DEV_LOOP_LLM_MAX_TURNS"; DEFAULT_LLM_MAX_TURNS = 60   # lines 131-132
def build_dispatcher(spec: DevAgentSpec, *, redis_url: str, max_concurrent: int, stream_ttl_seconds: int,
                     config_getter: ConfigGetter = _default_config_getter) -> Tuple[DevLoopCodeDispatcher, BaseModel]   # line 135
    # branches: claude-code :177, codex :184, gemini :191, nvidia :198, grok :215, zai :223, moonshot :235, google_coding :246, nova :253; raise ValueError :262

# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class ResearchOutput(BaseModel):                             # line ~340 — jira_issue_key, spec_path, feat_id, branch_name, worktree_path: str (Field(...));
                                                             #   repo_path: str = "" (:377), log_excerpts: List[str] = [] (:387), base_branch: str = "" (:391)
DevAgentBackend = Literal["claude-code","codex","gemini","nvidia","grok","zai","moonshot","google_coding","nova"]   # line 407
class DevAgentSpec(BaseModel):        # line 412 — agent: DevAgentBackend; model: str = ""; count: int = 1; escalation_model: str = ""
class DevAgentPoolConfig(BaseModel):  # line 438 — agents: List[DevAgentSpec] (min 1); isolation_mode: Literal["shared","isolated"] = "shared"
class TaskScopedBrief(BaseModel):     # line 458 — research: ResearchOutput; task_id: str; task_file: str = ""
class WorkerSummary(BaseModel):       # line 481 — worker_id, agent, model, tasks_completed, tasks_failed, summary
class DevelopmentOutput(BaseModel):   # line 497 — files_changed: List[str]; commit_shas: List[str]; summary: str; incomplete_tasks=[]; worker_summaries=[]
class DispatchLabels(BaseModel):      # line 763 — task_id="", task_title="", task_file="", seat="", agent, model ...

# Dispatch profiles — `subagent` literals to widen with "sdd-coder"
class LLMCodeDispatchProfile(BaseModel):      # models/llm.py:10 — subagent: Literal["sdd-worker"] (:18); llm: str = "nvidia:minimaxai/minimax-m3" (:19);
                                              #   max_turns (:23), max_tokens (:24), temperature (:25), parallel_tool_calls (:27), allowed_commands (:53-77), enable_thinking (:78), clear_thinking
class NovaCodeDispatchProfile(LLMCodeDispatchProfile)   # models/nova.py:93 — model: str = "minimax.minimax-m2.5" (:102); llm = "nova:minimax.minimax-m2.5" (:110)
class GeminiCodeDispatchProfile(BaseModel):   # models/gemini.py:15 — subagent Literal["sdd-worker"] (:22); model "auto" (:23)
class CodexCodeDispatchProfile(BaseModel):    # models/codex.py:10 — subagent Literal["sdd-worker","sdd-secondopinion"] (:18); model "gpt-5.5" (:19)
class ClaudeCodeDispatchProfile(BaseModel):   # models/claude.py:10 — subagent Optional[Literal[6 names]] (:18-27)
class GoogleCodingDispatchProfile(BaseModel)  # models/google_coding.py — subagent Literal[6 names] (:21)

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
class LLMCodeDispatcher:                      # line 51
    def __init__(self, *, max_concurrent: int, redis_url: str, stream_ttl_seconds: int,
                 client_factory: Callable[..., Any] = LLMFactory.create) -> None      # line 60
    async def dispatch(self, *, brief: BaseModel, profile: LLMCodeDispatchProfile, output_model: Type[T], run_id: str,
                       node_id: str, cwd: str, session_host=None, labels=None) -> T   # line 113 — enforces cwd under conf.WORKTREE_BASE_PATH (:2132)
    def _create_client(self, profile, *, run_id=None) -> Any                          # line 846 — self._client_factory(profile.llm, model_args={temperature, max_tokens})
    def _initial_messages(self, profile, brief, output_model, *, cwd="") -> List[Dict]  # line 891 — system prompt embeds load_subagent_definition(profile.subagent) (:899)
    def _completion_args(self, profile, tools) -> Dict[str, Any]                      # line 949 — tools, tool_choice="auto", parallel_tool_calls, max_tokens, temperature, extra_body (only if enable_thinking)
    async def _chat_completion(self, *, client, model, messages, args) -> Any        # line 973 — requires client._chat_completion(model=, messages=, use_tools=True, **args)
    def _tool_schemas(self, output_model) -> List[Dict]                               # line 1123 — read_file/list_files/search_files/edit_file/write_file/apply_patch/run_command/final_output
    def _response_message / _message_content / _message_tool_calls / _tool_call_id / _tool_call_name   # lines 2143-2175 (staticmethods)
    def _parse_tool_arguments(cls, call) -> Tuple[Optional[Dict], str]                # line 2176 — accepts dict OR JSON string arguments
    def _tool_call_to_openai_dict(self, call: Any, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]   # line 2237 — returns ONLY {id, type, function}
    def _finish_reason(response) -> str                                               # line 2270
    async def _publish_event(...)                                                     # line ~2386 — Redis failure ⇒ warning, never raises

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/nova.py   (TEMPLATE for M3)
class NovaCodeDispatcher(LLMCodeDispatcher):          # line 66
    def __init__(self, *, max_concurrent, redis_url, stream_ttl_seconds)   # line 78 — super().__init__(client_factory=self._create_mantle_client)
    def _create_mantle_client(self, llm: str, *, model_args=None, **kwargs) -> Any   # line 91 — BedrockMantleClient(api_key=..., base_url=..., **init_params)

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/mantle.py   (TEMPLATE for M3 client; 142 lines)
class BedrockMantleClient(OpenAIBaseClient):          # line 35 — intentionally no _default_model/_fallback_model/_lightweight_model
    def __init__(self, api_key: str | None = None, base_url: str | None = None, region: str | None = None, **kwargs)   # line 103
# pyproject entry points: bedrock-mantle = "parrot.clients.amazon:BedrockMantleClient" (amazon/pyproject.toml:28)

# packages/ai-parrot/src/parrot/clients/openai_base.py
class OpenAIBaseClient(AbstractClient):               # line 66 — comment :77 "Intentionally NO _default_model / _fallback_model / _lightweight_model"
    def __init__(self, api_key: str | None = None, base_url: str | None = None, **kwargs)   # line 89-92
    async def _chat_completion(self, model: str, messages: Any, use_tools: bool = False, stream: bool = False, **kwargs) -> Any   # line 216 — chat.completions.create/parse with tenacity retry

# packages/ai-parrot-client-google
class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis)   # google/client.py:101 — NO _chat_completion; api_key = kwargs.pop("api_key", config.get("GOOGLE_API_KEY")) (:189)
class GoogleModel(Enum): GEMINI_3_5_FLASH = "gemini-3.5-flash"              # google/models.py:11, :27
# google/__init__.py:1-3 imports GoogleGenAIClient, GeminiLiveClient, GoogleModel, VertexAIModel; __all__ at :7
# google/pyproject.toml:25-27  [project.entry-points."parrot.clients"] google = ...GoogleGenAIClient ; gemini-live = ...GeminiLiveClient

# packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py
_VALID_NAMES: frozenset[str] = frozenset({"sdd-research","sdd-worker","sdd-qa","sdd-codereview","sdd-secondopinion","sdd-planner","sdd-feedback"})   # lines 49-57
def load_subagent_definition(name: str) -> str        # line 86 — ValueError on unknown name (:105); reads _subagent_data/<name>.md (:108); strips frontmatter

# packages/ai-parrot/src/parrot/mcp/toolkit_config.py
class ToolkitSection(BaseModel):    # line 19 — class_path (alias "class"), enabled=True, kwargs={}, include, exclude, llm, llm_kwargs, env
class MCPToolkitsConfig(BaseModel): # line 79 — toolkits: dict[str, ToolkitSection]
BUILTIN_TOOLKITS                    # line 89 — scraping, browsing, memory (file sections merge over these)
def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig   # line 105
# packages/ai-parrot/src/parrot/mcp/toolkit_server.py
def create_toolkit_mcp_server(name: str, root: Path = Path.cwd(), **overrides) -> StdioMCPServer   # line 29
    # section.llm → LLMFactory.create(section.llm, **section.llm_kwargs) (:99-105) else drop toolkit_cls.llm_dependent_tools (:107)
    # toolkit = toolkit_cls(**dict(section.kwargs) [+ llm_client]) (:113-117); tools = toolkit.get_tools() (:121); include/exclude filters (:125+)
# packages/ai-parrot/src/parrot/mcp/local_cli.py — @click.command("mcp-local") name [--config] [--include] [--exclude] [--list]; registered in parrot/cli/__init__.py:117

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):         # line 206 — llm_dependent_tools: frozenset = frozenset() (:294); __init__(self, **kwargs) (:321); get_tools (:486); _generate_tools (:539)
                                    #   FEAT-391 lifecycle hooks: _open()/_close()/_ensure_open(), auto_open/_opened/_open_lock (see .agent/CONTEXT.md)

# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:                   # line 163 — parse_llm_string(llm) -> (provider, model|None) (:174); list_providers() (:215); create(llm, model_args=None, tool_manager=None, **kwargs) (:257)
PROVIDER_BACKEND = {"bedrock": "bedrock", "anthropic-aws": "aws"}   # line 157 — `bedrock:` ⇒ AnthropicClient(backend="bedrock")

# packages/ai-parrot/src/parrot/conf.py
WORKTREE_BASE_PATH: str             # line 829 — default BASE_DIR/.claude/worktrees; dispatchers reject cwd outside it (R4)
REDIS_URL                           # line 298 — config.get("REDIS_URL", fallback=redis://host:port/db)
```

### Existing File Anchors (markdown — edit anchors, verified 2026-09-10)
- `.claude/agents/sdd-worker.md`: frontmatter `model: sonnet` (:20), `tools:` (:23); "## ⛔ CARDINAL RULES" (:37); "## Task-Scoped Mode (FEAT-323)" (:77); "## Startup Sequence" (:108); "## Execution Loop" (:207); "### b2) Delegated implementation" (:229-251); "### c) Implement" (:253); "### g) Update SDD State" (:283); "## Completion" (:315); "## Structured Output Contract" (:373); "## STOP Conditions" (:404). 414 lines. Byte-identical twin at `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` (FEAT-547 done, TASK-3106).
- `sdd/templates/task.md`: "## Files to Create / Modify" (:33) — the heading `parse_task_files` reads.
- `packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py`: `_NO_REPO_TWIN` (:26); `_package_prompts()` auto-discovers `_subagent_data/*.md` (:38-40); `test_prompt_parity` (:44).
- `packages/ai-parrot/tests/flows/dev_loop/test_worktree_manager.py`: `git_sandbox` fixture (:36-37), helpers `_run_git` (:16), `_write_and_commit` (:30).
- `examples/tool-optimizations-mcp.yaml`: the `targeted-writer:` section shape (class / llm / llm_kwargs / kwargs) to mirror in `examples/sdd-coder-mcp.yaml`.
- `.gitignore`: `.parrot/` (:407) and `.mcp.json` (:389) are ignored — the tracked artefact is `examples/sdd-coder-mcp.yaml`.

### Spike evidence — Gemini OpenAI-compatible endpoint (verified live 2026-09-10; brainstorm "Spike evidence")
| Check | Result |
|---|---|
| `models.list()` on `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-3-flash-preview`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.6-flash`, `gemini-3.8-flash` |
| `chat.completions.create(tools=<read_file,list_files schemas of llm.py>, tool_choice="auto", parallel_tool_calls=True, temperature=0.0, max_tokens=512)` | `finish_reason="tool_calls"`, 2 tool calls in one turn, JSON-string arguments, `usage` populated |
| `+ reasoning_effort="none"` | accepted |
| `additionalProperties: false`, `minimum`, `maximum`, `default` in schemas | accepted unchanged |
| echo assistant turn as `{id,type,function}` (today's `_tool_call_to_openai_dict`) | **HTTP 400** "Function call is missing a thought_signature in functionCall parts" |
| echo with `extra_content` carried over (`{"google": {"thought_signature": "<base64>"}}` lives on each `tool_call`, not on the message) | OK, `finish_reason="stop"` |
| key location | `GEMINI_API_KEY` is in `env/.env`, loaded by `navconfig`; **not** in `os.environ` |

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SddCoderEngine.plan` | `TaskScheduler.from_index_file(...).next_wave()` | call | `task_scheduler.py:88, :176` |
| `SddCoderEngine.run_chunk` | `SubWorktreeManager.create(task_id)` | call (worker_id := task_id) | `worktree_manager.py:146` |
| `SddCoderEngine.run_chunk` | `DevAgentPool.build(DevAgentPoolConfig(agents=[DevAgentSpec(agent=seat.backend, model=seat.model)...], isolation_mode="isolated"), dispatcher_builder=partial(build_dispatcher, redis_url=..., max_concurrent=1, stream_ttl_seconds=...), pool_max=len(chunk))` then `.run_wave(tasks, research=..., run_id=job_id, cwd_for=...)` | call | `agent_pool.py:155, :435`; `agent_builder.py:135` |
| `SddCoderEngine._consolidate` | `SubWorktreeManager.merge_sequential(resolver=None)` | call; `SubWorktreeMergeError` ⇒ `merge_conflict` | `worktree_manager.py:181` |
| `SddCoderEngine.cleanup` | `SubWorktreeManager.cleanup(keep_on_conflict=...)` | call | `worktree_manager.py:297` |
| `GoogleCompatCodeDispatcher` | `LLMCodeDispatcher.__init__(client_factory=...)` | subclass | `dispatchers/llm.py:60` |
| `GoogleCompatCodeDispatcher._tool_call_to_openai_dict` | overrides base | method override (+`extra_content`) | `dispatchers/llm.py:2237` |
| `GeminiOpenAICompatClient` | `OpenAIBaseClient.__init__(api_key, base_url, **kwargs)` | subclass | `clients/openai_base.py:89` |
| `build_dispatcher` (`google-compat` branch) | `GoogleCompatCodeDispatcher` / `GoogleCompatCodeDispatchProfile` | new `if spec.agent == ...` after `nova` | `agent_builder.py:253-262` |
| `SddCoderToolkit` | `AbstractToolkit` (`get_tools`, `_open`) | subclass | `parrot/tools/toolkit.py:206, :486` |
| `parrot mcp-local sdd-coder` | `create_toolkit_mcp_server("sdd-coder", ...)` → `toolkit_cls(**section.kwargs)` | yaml `kwargs.roster` | `toolkit_server.py:113-117` |
| every seat dispatcher | `load_subagent_definition("sdd-coder")` | `profile.subagent` | `llm.py:899`, `codex.py:351`, `google_coding.py:323`, `_subagent_defs.py:86` |
| Claude Code native seat | `Agent(subagent_type="sdd-coder", model="haiku")` reading `.claude/agents/sdd-coder.md` | Claude Code agent loader | agent frontmatter `model:` (convention verified across `.claude/agents/*.md`) |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.flows.dev_loop.sdd_coder`~~ (package, `SddCoderToolkit`, `SddCoderEngine`, `RosterProbe`, `ChunkAssigner`, `JobTable`, `check_fidelity`, `CoderResult`) — all NEW in this feature.
- ~~`GeminiOpenAICompatClient`~~, ~~`GoogleCompatCodeDispatcher`~~, ~~`GoogleCompatCodeDispatchProfile`~~, ~~provider key `google-compat`~~, ~~`DevAgentBackend` value `"google-compat"`~~ — NEW; the Google package registers only `google` and `gemini-live`; no module references `generativelanguage.googleapis.com/v1beta/openai/`.
- ~~`"sdd-coder"`~~ — not in `_VALID_NAMES`, not in any `subagent` literal, no `.claude/agents/sdd-coder.md`, no `_subagent_data/sdd-coder.md`.
- ~~`parrot mcp-local sdd-coder`~~, ~~`.parrot/mcp-toolkits.yaml` in the repo~~, ~~`parrot-sdd-coder` / `parrot-targeted-writer` in the committed `.mcp.json`~~ — `.mcp.json` and `.parrot/` are git-ignored; only `examples/tool-optimizations-mcp.yaml` exists today.
- ~~`bedrock:qwen3-coder`~~ as a working `llm` string — `bedrock:` ⇒ `AnthropicClient(backend="bedrock")` (factory.py:157). Qwen is `nova` (bedrock-mantle id `qwen.qwen3-coder-480b-a35b-instruct`) or `bedrock-converse:qwen3-coder-480b-a35b`. ~~`qwen3-coder`~~ bare alias does not exist (only `qwen3-coder-480b-a35b`, amazon/models.py:130).
- ~~`gpt-5.3-codex-spark`~~ as a known constant — OpenAI client defines `GPT5_3_CODEX = "gpt-5.3-codex"` only (openai/models.py:33); the spark id is a passthrough string, hence `fallback_model`.
- ~~`_chat_completion` on `AnthropicClient`, `GoogleGenAIClient`, `BedrockConverseClient`, `NovaClient`~~ — only `OpenAIBaseClient` subclasses have it (openai_base.py:216); `LLMCodeDispatcher.dispatch` raises `DispatchExecutionError("... does not expose chat completion")` otherwise.
- ~~A generic `"openai"` / `"anthropic"` / `"google"` `DevAgentBackend`~~ — `build_dispatcher` knows nine literals; `nvidia` is the only in-process `LLMCodeDispatcher` route besides `nova`/`grok`/`zai`/`moonshot` subclasses.
- ~~`DevAgentPool.run_wave` guaranteeing distinct models~~ — assignment is `workers[i % len(workers)]`; distinctness holds only when `len(tasks) ≤ len(workers)` (the chunker enforces this).
- ~~`TaskScheduler` honouring the index `parallel` flag~~ — `depends_on` only.
- ~~`SubWorktreeManager` per-task API~~ — keyed by `worker_id`; this feature passes the task id as that key.
- ~~`DevAgentSpec.provider` / `.llm` / `.label`~~ — fields are `agent`, `model`, `count`, `escalation_model`.
- ~~`LLMCodeDispatcher._tool_call_to_openai_dict` carrying `extra_content`~~ — it returns only `{id, type, function}` (llm.py:2237-2269); the Gemini override adds it.
- ~~`extra_body.chat_template_kwargs` having any effect on Google's compat layer~~ — silently ignored; use `reasoning_effort`.
- ~~`OperationResult` importable from core~~ — it lives in `parrot_tools.tool_optimizations.models` (ai-parrot-tools); core must not import `parrot_tools` (dependency direction). `CoderResult` re-declares the shape.
- ~~A usable `gemini` CLI route~~ — `GeminiCodeDispatcher` exists (`dispatchers/gemini.py`) but the CLI is corporate-only/deprecated on this account; never in the roster.
- ~~`ClaudeCodeDispatcher` in this design~~ — not used; Haiku is a native Claude Code sub-agent.
- ~~`.claude/agents/*.md` with `model: haiku`~~ — none today (all `sonnet`, `product-analyst` is `opus`); `sdd-coder.md` is the first.
- ~~`MCP_TOOL_TIMEOUT` / `MCP_TIMEOUT`~~ configured in repo or user settings — not present; the ≤ 300 s `coder_wait` cap avoids depending on them.
- ~~`tests/mcp/test_toolkit_config.py`, `tests/mcp/test_toolkit_server.py`~~ — cited by `docs/tool-optimizations.md` but not present under `packages/*/tests` at this commit.
- ~~`GEMINI_API_KEY` in `os.environ`~~ — it is loaded from `env/.env` by `navconfig`; probes must use `conf.config.get(...)`.

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- **Nova/Mantle pattern for the Gemini seat**: copy `dispatchers/nova.py:66-140` and `amazon/nova/mantle.py:35-142` structurally; change only endpoint, key resolution, defaults, and add the two overrides. No `gpt-*`/`claude-*` defaults on the compat client (FEAT-438 lesson recorded in nova.py's docstring).
- **Submodule-direct imports inside `flows/dev_loop`** (agent_pool.py module docstring): the `sdd_coder` package imports `.models`, `.agent_pool`, `.task_scheduler`, `.worktree_manager`, `.agent_builder` directly, never `from parrot.flows.dev_loop import ...`, to avoid the partial-initialisation cycle.
- **Lazy provider imports in core** (FEAT-523 AC-3, see nova.py:59-64): `GoogleCompatCodeDispatcher` imports `GeminiOpenAICompatClient` inside `_create_compat_client`, never at module scope.
- **Toolkit conventions**: `AbstractToolkit` public `async def` methods become tools; keep helpers underscore-prefixed; `_open()` for the probe with `auto_open=True` (FEAT-391 names are reserved — do not redefine them for other purposes).
- **Result envelope**: every tool returns `CoderResult`; `status="error"` for domain failures (`CoderFailure` codes), MCP `isError` only for argument rejection/crashes (same split as `OperationResult`).
- **Pool per chunk, workers in plan order, `count=1`, `pool_max=len(chunk)`**: this is what makes `run_wave`'s modulo assignment equal the plan's bijection and its retry land on a different seat. Never build one pool for the whole feature.
- **Branch naming**: `<feature_branch>--<TASK-NNN>` via `SubWorktreeManager.create(task_id)`; sub-worktree path `<WORKTREE_BASE_PATH>/<feature_branch>--pool/<TASK-NNN>` — inside the R4 base by construction.
- **Synthetic `ResearchOutput`**: `jira_issue_key=""`, `spec_path=<index header spec>`, `feat_id`, `branch_name=<feature_branch>`, `worktree_path=<sub-worktree>`, `repo_path=<feature worktree>`, `log_excerpts=[]`, `base_branch=<index header>`.
- **Prompts**: `sdd-coder.md` reuses `sdd-worker.md`'s exact wording for Cardinal Rules and steps a–f (copy, then delete what does not apply); both prompts end with a byte-for-byte `cp` to `_subagent_data/`.
- **Probe rules** (M2, fixed): `nova` ⇒ `config.get("BEDROCK_MANTLE_API_KEY") or config.get("AWS_NOVA_API_KEY")` present (names verified: mantle.py:110); `google-compat` ⇒ `config.get("GEMINI_API_KEY") or config.get("GOOGLE_API_KEY")`; `codex` ⇒ `which("codex")`; `google_coding` ⇒ `which("agy")`; `native` ⇒ always available. When `smoke` is provided it runs once per mcp seat with `model`, then `fallback_model` on failure; `smoke_timeout_s` bounds each call.
- **Google-style docstrings, strict typing, Pydantic v2, `self.logger`, `aiohttp`-only** (CLAUDE.md).

### Known Risks / Gotchas
- **Gemini 3 `thought_signature` (verified)**: without the `extra_content` carry-over every second turn of the loop fails with HTTP 400. The override is mandatory, and the opt-in live test guards it. Follow-up §8 decides whether the base class should carry `extra_content` for every backend.
- **Google's compat layer silently ignores unknown params**: `extra_body.chat_template_kwargs` never reaches the model; thinking is controlled by `reasoning_effort` (`"none"` default). `parallel_tool_calls` is accepted or ignored — either way parallel calls were observed.
- **Native Haiku seat has no validated output**: Claude Code returns free text; the prompt demands a `DevelopmentOutput` JSON, but `coder_merge` treats git as the truth (Q2). An empty branch is a failure and follows the ladder.
- **Two dispatch paths per chunk**: the orchestrator must issue `coder_run_chunk` and the native `Agent` call in the same message for real parallelism, and must remember `coder_merge` for the native task. The prompt states this in one numbered step; the summary table exposes any task without a merge.
- **MCP tool timeouts**: `coder_wait` ≤ 300 s; jobs persist in the server process. If the server dies, branches/sub-worktrees persist on disk and appear as orphans (Q6).
- **`sdd-worker.md` `tools:` whitelist**: without the `mcp__parrot-sdd-coder__*` names the agent cannot call the server at all (verified convention: `sdd-ideation.md:44` lists `mcp__wikitoolkit__*`). AC-3 checks it.
- **Startup step §2 of `sdd-worker` marks every task `in-progress`**: compatible with `TaskScheduler` (non-`done` ⇒ pending), but the engine must not treat `in-progress` as "running elsewhere".
- **Redis**: `_publish_event` degrades to warnings per event; the engine passes `conf.REDIS_URL` and pre-checks reachability once at `open()` to emit a single warning (AC-15). Verified tolerant: `llm.py:~2400`, `codex.py:616`.
- **Model ids drift** (`gemini-3.8-flash` already exists; codex-spark may be unavailable): handled by `fallback_model` + probe, never by code changes.
- **Cross-feature**: FEAT-523 (PEP-420 respec, worktree pending) may touch `dispatchers/*.py`/`models/*.py`; edits here are additive one-liners plus new files — low conflict surface, but rebase the feature branch onto `dev` before `/sdd-done` if FEAT-523 merges first.
- **`agy` unvalidated**: the roster example does not include `google_coding`; operators may add it after the §8 follow-up.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `openai` (SDK) | already installed (3.3.1 in this venv) | `OpenAIBaseClient` → Gemini compat endpoint |
| `navconfig` | already a dependency | key resolution (`config.get`) |
| `redis` | optional, already a dependency | best-effort dispatch telemetry |
| `codex` CLI | operator-installed (0.153.4 here) | codex-spark seat |
| `aioboto3` (via ai-parrot-client-amazon) | already a dependency | Qwen seat (`BedrockMantleClient`) |
| Claude Code `Agent` tool | host feature | native Haiku seat |
| `hypothesis` (tests) | if present in dev deps; else parametrised loops | property test for the chunker (AC-2) |

No new runtime dependency is introduced.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

Resolved in brainstorm (carried forward; decision trail):

- [x] Feature or hotfix, and base branch? — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] How does Sonnet reach non-Anthropic coders? — *Resolved in brainstorm*: a local MCP server (`parrot mcp-local`, targeted-writer pattern) wrapping the ai-parrot dispatchers; not Bash CLIs, not the dev-loop server. Revised after research: haiku is a native Claude Code sub-agent (`Agent(sdd-coder, model: haiku)`), not an MCP seat.
- [x] How is Gemini reached, given the `gemini` CLI is unusable? — *Resolved in brainstorm*: in-process via Google's OpenAI-compatible endpoint, Nova/Mantle pattern; `google_coding` (`agy`) is the fallback, not the primary route.
- [x] Isolation between parallel coders? — *Resolved in brainstorm*: one sub-worktree + child branch per task, merged sequentially by `sdd-worker`.
- [x] Why "never the same model in parallel"? — *Resolved in brainstorm*: load-spreading across providers and per-model quality telemetry; rotating assignment recorded in the Completion Note.
- [x] Does the dev-loop `DevelopmentNode` path change too? — *Resolved in brainstorm*: no; only the interactive `sdd-worker`, twin synced for parity.
- [x] Relationship to FEAT-543 Delegation Contracts / eligibility table? — *Resolved in brainstorm*: `sdd-coder` handles every task without exception; `writer_generate` is no longer `sdd-worker`'s delegation route.
- [x] Failure policy? — *Resolved in brainstorm*: retry once on a different roster model, then `sdd-worker` implements it itself; never orphaned.
- [x] Commit / SDD-state ownership? — *Resolved in brainstorm*: coder commits code only in its sub-worktree; `sdd-worker` owns index, task move and Completion Note.
- [x] Where does the roster live and what if a provider lacks credentials? — *Resolved in brainstorm*: MCP server config with startup probe; unavailable entries skipped with a warning; single model ⇒ serial.
- [x] Exact backend/model ids for the four seats? — *Resolved in brainstorm*: config + probe with a declared `fallback_model` per entry; nothing hardcoded.
- [x] Gemini OpenAI-compatible endpoint coverage? — *Resolved in brainstorm*: verified live 2026-09-10; works with the loop's schemas/kwargs; `thought_signature` must be echoed via `extra_content`; `reasoning_effort` instead of `extra_body`.
- [x] Native haiku result contract? — *Resolved in brainstorm*: `DevelopmentOutput` JSON required by the prompt; `coder_merge` reconciles against git; missing JSON is a reporting defect, not fatal.
- [x] Job API bounds? — *Resolved in brainstorm*: `coder_wait` ≤ 300 s, idempotent; jobs live until `coder_cleanup`; no `MCP_TOOL_TIMEOUT` dependency.
- [x] Where the toolkit package lives? — *Resolved in brainstorm*: all in core, `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/`.
- [x] Semantics of the index `parallel` flag? — *Resolved in brainstorm*: advisory; `depends_on` only.
- [x] Redis for dispatch telemetry? — *Resolved in brainstorm*: optional via `conf.REDIS_URL`; one startup warning; recommended, never required.
- [x] Recovery after an MCP server crash mid-chunk? — *Resolved in brainstorm*: orphans listed by `coder_plan`; adoption only via explicit `coder_merge`; deletion via `coder_cleanup`.
- [x] Should the coder run the task's acceptance criteria itself? — *Resolved in brainstorm*: yes, both coder (in sub-worktree) and orchestrator (after merge).
- [x] `/sdd-start` interactive single-task path? — *Resolved in brainstorm*: out of scope; follow-up.

Still open:

- [ ] **Q1 — `agy` fallback validation**: confirm headless `agy --print … --output-format stream-json --json-schema …` works with this account (running the binary was declined in the brainstorm session) and decide whether `google_coding` is added to the example roster. Not blocking: the probe detects the binary and the seat is opt-in. — *Owner: Jesus Lara*
- [ ] **Q2 — Where the `extra_content` carry-over lives**: only in `GoogleCompatCodeDispatcher._tool_call_to_openai_dict` (this spec's default) or in the base `LLMCodeDispatcher` for every OpenAI-compatible backend (benefits future Gemini-like providers; touches shared code). Decide during M3; default stays subclass-only. — *Owner: spec author / implementer*
- [ ] **Q3 — Live test gating**: marker name and CI policy for `test_gemini_compat_live_roundtrip` (`-m live`, skipped without `GEMINI_API_KEY`). — *Owner: implementer*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: **skipped (model probe failed for gpt-5.6-luna (rc=124) — 120 s probe timeout)**
> · Transcript: `sdd/state/FEAT-549/design_research/` (probe `run.json` + `skip_reason.txt` only)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated. The pass can be re-run
manually (`codex exec … --output-schema sdd/templates/design_research.schema.json`
over `sdd/proposals/sdd-worker-subagents.brainstorm.md`) and folded into this
section before `Status: approved` if desired; it is optional and never blocking
(FEAT-545).

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree
  `.claude/worktrees/feat-FEAT-549-sdd-worker-subagents`, tasks sequential.
- **Recommended task order**: M1 → M2 → M3 → M4 → M5 → M6 → M7 → M8 → M9.
  M3 (Gemini seat) is independent of M1/M2 and *could* run in parallel; M6 and
  M7 depend on the tool names fixed by M5 and the agent name fixed by M6; the
  literal widenings (M6) and M3 both touch `flows/dev_loop/models/` — keep them
  in one worktree to avoid a parity/literal collision.
- **Parallelizable tasks** (if `/sdd-task` marks them `parallel: true`): M3
  (client + dispatcher + backend) vs. M1+M2 (models + roster) — disjoint files.
- **Cross-feature dependencies**: none must merge first. Watch FEAT-523
  (`dispatchers/*.py`, `models/*.py` renames) — rebase before `/sdd-done` if it
  lands earlier. FEAT-545 and FEAT-547 are already on `dev`.
- **Ironically**: this feature is the one that will make `per-spec` cheap for
  every later spec.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-10 | Jesus Lara + Claude Fable 5.1 | Initial draft from accepted brainstorm (Option A); design research skipped (probe timeout) |
