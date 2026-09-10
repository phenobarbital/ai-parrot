---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: `sdd-worker` as Orchestrator of Parallel `sdd-coder` Sub-Agents

**Date**: 2026-09-10
**Author**: Jesus Lara + Claude Fable 5.1
**Status**: accepted
**Recommended Option**: Option A

---

## Problem Statement

`/sdd-spec` and `/sdd-task` already produce a task graph with explicit
precedence (`depends_on`) and a `parallel` / `parallelism_notes` hint per
task, precisely so that independent tasks can be executed concurrently. The
interactive `sdd-worker` agent (`.claude/agents/sdd-worker.md`) ignores that
graph: it topologically sorts the pending tasks and implements them **one after
another, in its own execution block**, on a single Sonnet session. When it does
"parallelise", it does so by unilaterally spawning a copy of itself through the
Claude Code `Agent` tool — an undesigned behaviour with no model diversity,
no isolation and no consolidation step.

The server-side dev-loop already solved the scheduling half of this problem
(FEAT-323 *Dev-Loop Multiple Dev Agents*): `TaskScheduler` computes
dependency-respecting waves from the per-spec index, `DevAgentPool`
dispatches a wave in parallel across heterogeneous backends with a
retry-on-a-different-worker rule, and `SubWorktreeManager` isolates each
worker in its own git worktree and merges sequentially. None of that is
reachable from an interactive Claude Code session, because the Claude Code
`Agent` tool can only launch **Anthropic** models (haiku/sonnet/opus).

**Who is affected**

- The maintainer running `/sdd-start` / `sdd-worker` interactively: features
  with 8–20 tasks take hours of wall-clock time on a single Sonnet seat, and
  all of it is billed at Sonnet rates even for mechanical tasks that FEAT-545
  deliberately shaped so that a cheaper model can execute them nearly
  verbatim (Implementation Blueprints).
- The `sdd-done` / PR review stage, which today receives no record of *which*
  model produced *which* task, so quality per model cannot be compared.

**Expectation (as stated during discovery)**

`sdd-worker` keeps running on Sonnet but becomes an **orchestrator**: it reads
the task list and its precedence, assigns each task a model from a fixed
roster of four (`bedrock:qwen3-coder`, `google:gemini-3.5-flash`,
`openai:gpt-5.3-codex-spark`, `anthropic:haiku`), determines the execution
flow (waves), dispatches `sdd-coder` sub-agents with that model + task,
consolidates each finished coder's work, runs the `code-reviewer` sub-agent
over the whole feature, applies the reviewer's fixes, and leaves the worktree
ready for `/sdd-done`. Rule 1: **never the same model for two tasks running in
parallel**.

## Constraints & Requirements

Decisions taken during the two discovery rounds are constraints for the spec:

- **C1 — Bridge (hybrid, revised after research)**: the three non-Anthropic
  coders are reached through a **local MCP server** served by `parrot
  mcp-local` (the `parrot-targeted-writer` / FEAT-543 pattern), not through
  ad-hoc Bash CLIs and not by moving the entry point to the dev-loop server.
  The **haiku seat is a native Claude Code sub-agent**: `sdd-worker` launches
  `Agent(sdd-coder, model: haiku)` itself, in the same turn as the MCP
  dispatch, so no `ClaudeCodeDispatcher`/nested session is involved. The MCP
  still owns every sub-worktree, fidelity check and merge, so consolidation
  is uniform regardless of who ran the coder. `sdd-worker` stays a Claude
  Code agent on Sonnet.
- **C1b — Gemini route**: the `gemini` CLI is **not** a usable backend (a
  binary exists on this machine but the product is corporate-only and
  deprecated in favour of Antigravity `agy`). Gemini is reached
  **in-process** through Google's OpenAI-compatible endpoint, mirroring the
  `NovaCodeDispatcher` / `BedrockMantleClient` pattern (an `OpenAIBaseClient`
  subclass with a different `base_url` + key, driven by the unchanged
  `LLMCodeDispatcher` loop). The existing `google_coding` dispatcher (`agy
  --print`, headless) is the documented fallback, not the primary route.
- **C2 — Isolation**: one **sub-worktree + child branch per task**, branched
  from the feature branch; `sdd-worker` merges them back sequentially and
  resolves conflicts itself. Coders never share a working tree.
- **C3 — Delegation is total**: every pending task is dispatched to an
  `sdd-coder`, regardless of the spec's `Delegation-eligible` marking or the
  presence of a `## Delegation Contract`. `sdd-worker` (Sonnet) writes task
  code **only** as the third and last attempt (see C4) and when applying
  `code-reviewer` fixes. The FEAT-543 `writer_generate`/`writer_apply` route
  (step b2 of the current prompt) is **replaced** in `sdd-worker`, not kept
  alongside.
- **C4 — Failure policy**: attempt 1 on the assigned model → attempt 2 on a
  **different** roster model in a fresh sub-worktree → attempt 3 by
  `sdd-worker` itself in the feature worktree. A task is never left orphaned;
  `done-with-issues` is reserved for the case where all three fail.
- **C5 — Ownership**: the coder commits **code only** (`feat(<slug>): TASK-NNN
  — <title>`) in its sub-worktree and never touches `sdd/`. `sdd-worker` owns
  all SDD state — per-spec index, `mv` to `sdd/tasks/completed/`, Completion
  Note (which records model, backend, attempts, duration and token usage).
- **C6 — Model roster & rotation rule**: the roster lives in the MCP server's
  configuration (`.parrot/mcp-toolkits.yaml`, env override), is ordered, and
  is **probed for credentials/CLI availability at server start**; unavailable
  entries are dropped from the rotation and reported. Within one parallel
  slice no model repeats; a wave larger than the available roster is chunked
  and the excess runs in the next slice. With a single available model the
  run degrades to serial. Rationale is *both* load-spreading and per-model
  quality telemetry, so every Completion Note records the model.
- **C7 — Scope**: only the interactive Claude Code `sdd-worker` changes
  behaviour. `DevelopmentNode` / `DevAgentPool` in the dev-loop are not
  re-architected. The packaged twin `_subagent_data/sdd-worker.md` is synced
  only to keep `test_subagent_parity.py` green (FEAT-547), and any new prompt
  (`sdd-coder`) ships with a twin from day one.
- **C8 — Cardinal Rules survive**: the coder prompt inherits `sdd-worker`'s
  builder-not-architect, file-fidelity and codebase-contract rules; the
  orchestrator verifies file fidelity from `git diff --name-only` before
  merging a coder branch.
- **C9 — No new blocking I/O in async contexts, Pydantic for every payload,
  `aiohttp`-only, Google-style docstrings** (CLAUDE.md).

---

## Options Explored

### Option A: "Orchestration kernel" MCP — `parrot-sdd-coder` wraps the FEAT-323 pool

A new `AbstractToolkit` (`SddCoderToolkit`) served by `parrot mcp-local
sdd-coder` and registered in `.mcp.json`. It **reuses** `TaskScheduler`,
`DevAgentPool`, `SubWorktreeManager` and `agent_builder.build_dispatcher`
wholesale, and adds the two things they lack: a **model roster with the
distinct-model rule** (chunk a wave to `len(available_roster)`, rotate the
starting model between chunks) and a **credential probe**. Deterministic
work (wave computation, model assignment, sub-worktree lifecycle, parallel
dispatch, single cross-model retry, merge, telemetry) happens in Python;
judgment (SDD state, conflict resolution, third-attempt implementation,
reviewer triage) stays in Sonnet.

Tool surface (names indicative, for the spec to fix):

| Tool | Purpose |
|---|---|
| `coder_plan(feature, worktree)` | Re-reads the per-spec index, returns the next wave already sliced into distinct-model chunks, plus the effective roster and the entries dropped by the probe. Stateless: the index is the single source of truth. |
| `coder_run_chunk(feature, worktree, task_ids)` | For the MCP-backed seats: creates one sub-worktree/branch per task, dispatches all tasks of the chunk in parallel (one model each), retries a failure once on the next roster model, merges the successful branches sequentially into the feature branch, returns a **job id** immediately. |
| `coder_prepare_native(feature, worktree, task_id)` | For the haiku seat: creates the task's sub-worktree/branch and returns its path; `sdd-worker` then launches `Agent(sdd-coder, model: haiku)` with that cwd in the same turn as `coder_run_chunk`. |
| `coder_merge(feature, worktree, task_id)` | Fidelity check + sequential merge of one branch — used after a native (haiku) coder returns, and to re-merge a branch Sonnet had to fix. Same result vocabulary as the job API. |
| `coder_wait(job_id, timeout_seconds)` | Blocks up to the timeout (bounded, e.g. ≤ 600 s) and returns progress or the final per-task result: `merged` / `merge_conflict(branch, files)` / `failed(diagnostics)` / `fidelity_violation(unexpected_files)`. |
| `coder_status(job_id)` | Non-blocking snapshot for long tasks. |
| `coder_cleanup(feature, keep_conflicted=true)` | Removes merged sub-worktrees; conflicted ones are kept for Sonnet. |

The `sdd-coder` prompt is a new dual-sourced sub-agent definition
(`.claude/agents/sdd-coder.md` + `_subagent_data/sdd-coder.md`): task-scoped,
code-only, no SDD state, structured `DevelopmentOutput` at the end. Each
backend's dispatch profile gets `"sdd-coder"` added to its `subagent`
literal.

Roster → backend mapping (the user-facing `provider:model` strings do not map
1:1 onto working dispatchers — see *Does NOT Exist*):

| Roster entry (as requested) | `DevAgentBackend` | Dispatcher | Model id to configure | Notes |
|---|---|---|---|---|
| `bedrock:qwen3-coder` | `nova` | `NovaCodeDispatcher` (in-process loop over the OpenAI-compatible **bedrock-mantle** endpoint) | `qwen.qwen3-coder-480b-a35b-instruct` | The `bedrock:` provider key resolves to `AnthropicClient` on Bedrock, not Qwen; `bedrock-converse` exposes no `_chat_completion`, so the in-process loop cannot drive it. |
| `google:gemini-3.5-flash` | `google-compat` (**new**) | `GoogleCompatCodeDispatcher(LLMCodeDispatcher)` (**new**, Nova pattern) over a `GeminiOpenAICompatClient(OpenAIBaseClient)` (**new**) pointed at `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-3.5-flash` | `GoogleGenAIClient` speaks the native GenAI SDK and has no `_chat_completion`; the compat client is ~100 lines like `BedrockMantleClient`. Fallback: `google_coding` (`agy --print`, headless) — already a dispatcher with tests; the `agy` ban is reviewer-only. The `gemini` CLI is **not** an option (corporate-only, deprecated). |
| `openai:gpt-5.3-codex-spark` | `codex` | `CodexCodeDispatcher` (`codex exec --json`) | `gpt-5.3-codex-spark` | Model string passes through; not a known constant in the OpenAI client (`GPT5_3_CODEX` = `gpt-5.3-codex`). |
| `anthropic:haiku` | — (native) | Claude Code `Agent` tool with the new `.claude/agents/sdd-coder.md` (`model: haiku`), launched by `sdd-worker` | `haiku` (Claude Code alias) | Outside the MCP; no `LLMCodeDispatcher`, no nested session. The MCP prepares its sub-worktree (`coder_prepare_native`) and merges it afterwards (`coder_merge`). Result is the agent's final message plus `git` state in the sub-worktree, not a validated `DevelopmentOutput`. |

✅ **Pros:**
- Reuses ~1,300 lines of tested FEAT-323 code (34 pool/worktree tests) instead
  of re-implementing waves, retry and merge; only roster + probe + job API
  are new.
- The distinct-model rule, chunking and retry are **deterministic Python**,
  unit-testable without an LLM, and cannot be "forgotten" by the prompt.
- Structured per-task results (`WorkerSummary`, `DispatchLabels`, usage) feed
  the Completion Note and the summary table directly.
- Same config surface as the targeted writer (`.parrot/mcp-toolkits.yaml`,
  `parrot mcp-local`), so operators already know how to install it.
- The roster/probe module can later be reused by `DevelopmentNode` to give the
  dev-loop the same distinct-model guarantee (out of scope here).

❌ **Cons:**
- Highest effort: new toolkit, new sub-agent prompt + twin, six `subagent`
  literals to widen, `.mcp.json` + yaml + docs, and a substantial rewrite of
  `sdd-worker.md`'s Execution Loop.
- Long-running MCP tool calls: a coder task can take 10–30 min, so the tool
  surface **must** be job-based (`run` returns, `wait` polls with a bounded
  timeout) or Claude Code's MCP tool timeout will kill the call.
- The dispatchers publish telemetry to Redis; without Redis they degrade to
  warnings (verified for `LLMCodeDispatcher` and `CodexCodeDispatcher`), which
  is acceptable but noisy.
- Two dispatch paths for one chunk (MCP job + native `Agent`): the plan must
  make the split explicit and the orchestrator must call `coder_merge` for
  the native task — one more thing the prompt has to get right.
- Gemini 3 through the OpenAI-compatible endpoint requires every tool call's
  `thought_signature` (`tool_call.extra_content`) to be echoed back; the base
  `LLMCodeDispatcher` drops it when re-rendering the assistant turn, so the
  Gemini dispatcher needs one targeted override (verified live, see Spike
  evidence). Everything else the loop sends was accepted as-is.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot.mcp.toolkit_server` / `parrot mcp-local` | Serve the toolkit over stdio MCP | in-repo (FEAT-485), no new dependency |
| `openai` SDK (via `OpenAIBaseClient`) | Gemini seat through Google's OpenAI-compatible endpoint | already a dependency; new ~100-line client subclass, no new package |
| `codex` CLI | Codex seat (`CodexCodeDispatcher`) | installed locally (`~/.local/bin/codex`); probed at start |
| `agy` CLI (fallback only) | `GoogleCodingDispatcher` if the compat endpoint disappoints | installed locally (`~/.local/bin/agy`); coder use only, never reviewer |
| `aioboto3` (via `ai-parrot-client-amazon`) | `BedrockMantleClient` for the Qwen seat | already a dependency of the amazon client package |
| Claude Code `Agent` tool | haiku seat | native, no dependency |
| `redis` (optional) | dispatch event streams | best-effort, degrades to warnings |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py` — waves from the per-spec index (`TaskScheduler.from_index_file`, `next_wave`, `mark_done`, `mark_failed`).
- `packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py` — `DevAgentPool.build/run_wave`, retry on a different worker, `aggregate_outputs`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py` — `SubWorktreeManager.create/merge_sequential/cleanup` (key by task id instead of worker id).
- `packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py` — `build_dispatcher(spec, redis_url, ...)` for every roster backend (gains a `google-compat` branch).
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/nova.py` + `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/mantle.py` — the exact template for the Gemini compat dispatcher + client pair.
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` — `agy` headless dispatcher, reused as-is for the fallback seat.
- `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py` — `load_subagent_definition`, `_VALID_NAMES` (add `sdd-coder`).
- `packages/ai-parrot/src/parrot/mcp/toolkit_config.py` + `toolkit_server.py` — yaml section model and server factory.
- `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/base.py` — `OptimizationToolkitBase` (arg-model validation + `OperationResult` shaping) as the toolkit skeleton to imitate.
- `.claude/agents/sdd-worker.md` — Cardinal Rules and task-scoped mode text become the core of `sdd-coder.md`.

---

### Option B: Thin MCP — one `coder_dispatch` tool, Sonnet does the scheduling

The MCP server only exposes `coder_dispatch(task_file, backend, model, cwd)`
(async job) plus `coder_wait`. Everything else — reading the index, computing
waves, picking distinct models, `git worktree add`, merging, retrying — is
written as prose instructions in `sdd-worker.md` and executed by Sonnet with
Bash.

✅ **Pros:**
- Smallest Python surface: a thin wrapper over `build_dispatcher` +
  `dispatcher.dispatch`.
- Maximum flexibility for the orchestrator to reason about odd cases.

❌ **Cons:**
- The distinct-model rule, chunking and retry become **LLM behaviour**, i.e.
  probabilistic. This is exactly the failure mode being fixed (the current
  prompt already "decides unilaterally" to spawn itself).
- Sonnet spends its own context on `git worktree` bookkeeping and polling
  loops instead of on review and consolidation.
- No unit tests can cover the scheduling policy.
- Duplicates `TaskScheduler`/`SubWorktreeManager` logic in prose.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot.mcp.toolkit_server` | serve the thin toolkit | in-repo |
| same dispatchers as A | per-backend execution | in-repo |

🔗 **Existing Code to Reuse:**
- `agent_builder.build_dispatcher` and the five dispatchers — as in A.
- `.claude/agents/sdd-worker.md` — extended rather than restructured.

---

### Option C: Let the dev-loop be the orchestrator (no new MCP)

Do not build anything new for Claude Code. Configure the existing
`DevelopmentNode` pool with four distinct backends
(`DEV_LOOP_DEV_AGENTS=[{nova},{gemini},{codex},{claude-code:haiku}]`,
`DEV_LOOP_DEV_ISOLATION=isolated`) and run the feature through the dev-loop
server; the interactive `sdd-worker` is reduced to a launcher.

✅ **Pros:**
- Lowest effort: it exists today (FEAT-323 + FEAT-377), including QA,
  code-review and second-opinion nodes downstream.
- Server-side telemetry, streaming and session state come for free.

❌ **Cons:**
- Changes the entry point: requires the dev-loop server, Redis, and the
  `WorkBrief`/`ResearchOutput` shapes; not a `claude` session any more. The
  user explicitly rejected this in Round 1.
- `DevAgentPool.run_wave` assigns `i % len(workers)`, so a wave of 5 tasks
  over 4 workers **does** reuse a model — the distinct-model rule would still
  need the chunking change.
- Merge-conflict resolution is a pool dispatch (first worker, then a
  claude-code fallback), not Sonnet-in-the-loop.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `examples/dev_loop/server.py` | runs the flow | requires Redis + env |

🔗 **Existing Code to Reuse:**
- Everything under `packages/ai-parrot/src/parrot/flows/dev_loop/` unchanged.

---

### Option D (unconventional): CLI-native coders, no Python at all

`sdd-worker` shells out directly, in background Bash, to the agentic CLIs
that are installed — `codex exec`, `agy --print` (as coder) and
`claude -p --model haiku` — one per sub-worktree, each given the task file
path, and polls their output files. (The `gemini` CLI is not usable here:
corporate-only and deprecated in favour of `agy`.)

✅ **Pros:**
- Zero new Python; works the day the prompt is written.
- Each CLI already implements its own tool loop, sandboxing and auth.

❌ **Cons:**
- Four different output formats and no structured completion contract; the
  orchestrator has to parse free text to know whether a task finished.
- No probe, no retry policy, no telemetry beyond what Sonnet transcribes.
- `claude -p` inside a Claude Code session hits the nested-session guard.
- Re-implements in prose what `CodexCodeDispatcher` / `GoogleCodingDispatcher`
  / `ClaudeCodeDispatcher` already do in Python with tests.
- Qwen-on-Bedrock and Gemini-via-API have no CLI at all, so the roster
  shrinks to two plus `agy`.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `codex`, `gemini`, `agy`, `claude` CLIs | coder seats | all present on this machine; not portable |

🔗 **Existing Code to Reuse:**
- `.claude/agents/sdd-worker.md` only.

---

## Recommendation

**Option A** is recommended because:

- It is the only option that satisfies **C1, C2, C4 and C6 deterministically**.
  The distinct-model rule and the cross-model retry are policy; policy that
  lives in a prompt (Options B and D) is the very class of behaviour this
  feature exists to remove.
- It reuses the FEAT-323 machinery that already encodes the hard parts
  (cycle detection, wave computation, per-worker sub-worktrees, sequential
  merge with conflict detection, retry on a different worker, output
  aggregation). The genuinely new code is small and pure: a roster model, a
  credential probe, a chunker that enforces `len(chunk) ≤ len(roster)`, and
  a job table for the async tool API.
- It keeps Sonnet where judgment is needed — SDD state, merge conflicts, the
  third attempt, reviewer triage — and takes it out of bookkeeping.
- It preserves the interactive entry point the user asked for (unlike C) while
  leaving a clean path to give the dev-loop the same roster rule later.

**What is traded off**: effort (High) and two operational risks that the spec
must address head-on — the job-based tool API to survive MCP tool timeouts,
and the feature coverage of Google's OpenAI-compatible endpoint for the
Gemini seat. If that endpoint cannot drive the loop (tool calling, schema
quirks), the seat falls back to the existing `google_coding` (`agy`)
dispatcher or is dropped by the probe; the design does not depend on it. The
haiku seat is native to Claude Code and carries no dispatcher risk, at the
price of a second dispatch path the orchestrator must handle explicitly.

---

## Feature Description

### User-Facing Behavior

1. The operator installs the server once: adds an `sdd-coder` section to
   `.parrot/mcp-toolkits.yaml` (roster + kwargs) and a `parrot-sdd-coder`
   entry to `.mcp.json` pointing at `parrot mcp-local sdd-coder`. No secrets
   in either file; each backend uses its own credential chain.
2. They launch `sdd-worker` exactly as today (`claude --agent sdd-worker …`
   inside the feature worktree, or `Implement FEAT-NNN`).
3. `sdd-worker` prints a **dispatch plan** before touching code:

   ```
   Roster (available 4/4): nova:qwen3-coder-480b · google-compat:gemini-3.5-flash · codex:gpt-5.3-codex-spark · native:haiku
   Wave 1 (3 tasks, 1 chunk): TASK-3101→qwen  TASK-3102→gemini  TASK-3103→codex-spark
   Wave 2 (5 tasks, 2 chunks): [3104→haiku(native) 3105→qwen 3106→gemini 3107→codex-spark] [3108→haiku(native)]
   Wave 3 (1 task): TASK-3109→qwen
   ```

   Dropped roster entries are named with the probe reason ("codex: CLI not
   found", "nova: no AWS credentials", "google-compat: GEMINI_API_KEY unset").
   Tasks marked `native` are the ones `sdd-worker` will run itself through
   the Claude Code `Agent` tool.
4. While coders run, `sdd-worker` reports per-task progress as each
   `coder_wait` returns (merged / retrying on `<model>` / conflict / failed).
5. After every merged task, `sdd-worker` runs that task's acceptance
   criteria in the feature worktree, updates the per-spec index, moves the
   task file, and writes a Completion Note that includes:
   `Model: nova:qwen.qwen3-coder-480b-a35b-instruct · Attempts: 1 · Duration:
   07m12s · Tokens: in 41k / out 9k`.
6. When the index has no pending tasks, `sdd-worker` invokes `code-reviewer`
   with the neutral brief (unchanged), applies 🔴/🟠 fixes itself, pushes,
   and prints the completion summary — now with a **per-model table**
   (tasks, retries, failures, wall-clock) — and the usual "Next: `/sdd-done`".

### Internal Behavior

- **Plan**: `coder_plan` reads `sdd/tasks/index/<feature>.json` from the
  feature worktree through `TaskScheduler` (status `done` is done, everything
  else is pending — so `sdd-worker`'s existing "mark all in-progress" step is
  compatible), computes the next wave, and slices it into chunks of at most
  `len(available_roster)` tasks. Model assignment inside a chunk is a
  bijection onto the roster; the starting index rotates between chunks so
  that, over a feature, every model sees a mix of tasks.
- **Dispatch (MCP seats)**: `coder_run_chunk` builds one `DevAgentSpec` per
  MCP-backed roster entry (`count=1`), materialises them through
  `build_dispatcher` (`nova`, `google-compat`, `codex`), and runs
  `DevAgentPool.run_wave` over the chunk with `cwd_for(task_id)` pointing at a
  fresh sub-worktree created by `SubWorktreeManager.create(task_id)` (branch
  `<feature-branch>--TASK-NNN`). Because the chunk never exceeds the pool
  size, `run_wave`'s `i % len(workers)` assignment is already injective, and
  its built-in retry (`_next_worker`) is by construction a *different* model.
  The brief is a `TaskScopedBrief` whose `task_file` names the task
  artifact; the profile's `subagent` is `sdd-coder`.
- **Dispatch (native seat)**: for the task the plan assigns to `haiku`,
  `sdd-worker` calls `coder_prepare_native` to get the sub-worktree path, then
  launches `Agent(sdd-coder, model: haiku)` with the task file and that cwd
  **in the same turn** as `coder_run_chunk`, so the chunk really runs in
  parallel. When the agent returns, `sdd-worker` calls `coder_merge` so the
  fidelity check and merge follow the same path as the MCP seats. A retry of
  a native failure goes to the next MCP model via a one-task
  `coder_run_chunk`; a retry of an MCP failure may land on haiku only when
  the pool has no other model left, in which case the MCP reports
  `retry_native` and `sdd-worker` performs it.
- **Gemini in-process**: `GoogleCompatCodeDispatcher` subclasses
  `LLMCodeDispatcher` and swaps `client_factory` for a
  `GeminiOpenAICompatClient(OpenAIBaseClient)` bound to Google's
  OpenAI-compatible base URL with `GEMINI_API_KEY`/`GOOGLE_API_KEY` read via
  `navconfig` — the `NovaCodeDispatcher` + `BedrockMantleClient` pattern
  verbatim, plus one override: `_tool_call_to_openai_dict` carries the raw
  tool call's `extra_content` (Gemini 3 `thought_signature`) into the echoed
  assistant turn. The loop, tool schemas, cwd guard and output validation
  are inherited unchanged (verified live, see Spike evidence).
- **Consolidate**: for each successful task the toolkit checks file fidelity
  (`git diff --name-only <feature>..<branch>` ⊆ files listed in the task, and
  ∩ `sdd/` = ∅), then `merge_sequential(resolver=None)`: clean merges are
  fast-forwarded into the feature branch; a conflict aborts that one merge,
  keeps the branch, and is reported as `merge_conflict`. Everything is
  returned through the job record.
- **Judgment (Sonnet)**: `sdd-worker` resolves reported conflicts in the
  feature worktree and commits; re-runs the task's acceptance criteria after
  merge; on a `failed` after the cross-model retry it implements the task
  itself (attempt 3, existing steps c–f); then performs step (g) for that
  task. It loops `coder_plan → coder_run_chunk → coder_wait → (g)` until the
  plan is empty, then runs the reviewer.
- **Prompts**: `sdd-coder.md` is `sdd-worker.md`'s task-scoped mode made
  primary, minus everything about SDD state and the feature-level loop, plus
  the `DevelopmentOutput` contract (`files_changed` from git, never memory).
  `sdd-worker.md`'s Execution Loop is replaced by the orchestrator loop; step
  b2 (`writer_generate`) is removed; Cardinal Rules and the Completion section
  stay. Both files keep byte-parity twins under `_subagent_data/`.

### Edge Cases & Error Handling

- **Roster shrinks to one** (probe drops three) → every chunk has one task;
  the run is serial but still delegated; the summary says so.
- **Roster empty** → `coder_plan` returns `roster_unavailable` for all four;
  `sdd-worker` falls back to today's sequential Sonnet loop and flags it in
  the summary. It does not abort.
- **Wave larger than roster** → chunked; later chunks wait for earlier ones to
  merge (so a chunk always branches from the latest feature head).
- **Cycle in `depends_on`** → `TaskScheduler` raises `ValueError`; STOP
  condition, reported verbatim.
- **Coder touched unlisted files or `sdd/`** → branch is not merged, result
  `fidelity_violation` with the file list; counts as a failure for retry
  purposes.
- **Merge conflict** → branch preserved, base worktree left clean
  (`merge --abort`), Sonnet merges manually; `coder_cleanup` never deletes a
  conflicted branch unless told to.
- **Coder "succeeds" but acceptance tests fail after merge** → treated as a
  failure of that attempt; the next attempt starts from the merged head with
  the diagnostics in the brief.
- **MCP tool timeout** → `coder_wait` is bounded (≤ 600 s) and idempotent;
  jobs live in the server process until `coder_cleanup`; if the server dies
  mid-job the sub-worktrees and branches persist on disk and `coder_plan`
  lists orphan `--TASK-NNN` branches for Sonnet to adopt or delete.
- **Redis absent** → dispatch telemetry degrades to warnings (existing
  behaviour); dispatch still completes.
- **Native haiku agent returns without a usable report** (no
  `DevelopmentOutput` validation exists on this path) → `sdd-worker` derives
  the result from git in the sub-worktree (`git log`, `git diff --name-only`)
  and `coder_merge` applies the same fidelity check; an empty branch is a
  failure and follows the retry policy.
- **Gemini tool round-trip without `thought_signature`** → 400 from the
  endpoint (verified). `GoogleCompatCodeDispatcher` overrides
  `_tool_call_to_openai_dict` to carry the raw call's `extra_content`; the
  probe's smoke dispatch includes one full tool round-trip so a regression
  here drops the seat (or swaps it for `google_coding`/`agy`) instead of
  failing mid-task.
- **Roster entry whose primary model id is rejected** (e.g. codex-spark not
  enabled on the account) → the probe switches to the entry's declared
  `fallback_model` and reports it; with no fallback the entry is dropped.
- **Feature worktree not under `WORKTREE_BASE_PATH`** → the dispatchers'
  existing R4 check rejects the cwd; `coder_plan` reports it up-front.

---

## Capabilities

### New Capabilities
- `sdd-coder-mcp-toolkit`: `SddCoderToolkit` (roster, probe, chunker, job
  table) served as `parrot-sdd-coder` via `parrot mcp-local`, reusing the
  FEAT-323 scheduler/pool/worktree modules.
- `model-roster-assignment`: ordered roster model + distinct-model chunking +
  rotating start index + cross-model retry mapping; pure, unit-tested.
- `sdd-coder-subagent-prompt`: new dual-sourced `sdd-coder.md` (repo +
  packaged twin), task-scoped, code-only, `DevelopmentOutput` contract; the
  repo copy carries `model: haiku` so the same definition serves as the native
  Claude Code sub-agent.
- `gemini-openai-compat-seat`: `GeminiOpenAICompatClient(OpenAIBaseClient)`
  (provider key `google-compat`) + `GoogleCompatCodeDispatcher(LLMCodeDispatcher)`
  + `GoogleCompatCodeDispatchProfile` + `DevAgentBackend` value, mirroring the
  Nova/Mantle pair.
- `sdd-worker-orchestrator-loop`: rewritten Execution Loop in
  `sdd-worker.md` (plan → dispatch → wait → consolidate → SDD state →
  review → fixes), with per-model summary.

### Modified Capabilities
- `dev-loop-multiple-dev-agents` (FEAT-323): `"sdd-coder"` added to every
  dispatch profile's `subagent` literal and to `_VALID_NAMES`; no behaviour
  change for the dev-loop path.
- `sdd-delegation-workflow` (FEAT-543): `sdd-worker`'s step b2 removed
  (targeted writer no longer the delegation route *from sdd-worker*;
  `/sdd-start`'s interactive branch is untouched).
- `sdd-worker-prompt-twin-sync` (FEAT-547): parity test now also covers
  `sdd-coder`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `.claude/agents/sdd-worker.md` | modifies | Execution Loop → orchestrator loop; b2 removed; summary gains per-model table |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | modifies (sync) | byte-parity twin |
| `.claude/agents/sdd-coder.md` + `_subagent_data/sdd-coder.md` | new | dual-sourced coder prompt |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py` | extends | `_VALID_NAMES += "sdd-coder"` |
| `flows/dev_loop/models/{llm,gemini,codex,claude,google_coding}.py` | extends | widen `subagent` literals |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/` (new package, core) | new | `SddCoderToolkit` (MCP tools), roster + `fallback_model`, credential probe (via `navconfig`), chunker, job table, arg/result models — decided Q3: all in core next to the FEAT-323 modules it composes |
| `flows/dev_loop/task_scheduler.py`, `agent_pool.py`, `worktree_manager.py`, `agent_builder.py` | depends on | consumed unchanged; sub-worktree keyed by task id |
| `packages/ai-parrot-client-google/src/parrot/clients/google/openai_compat.py` (new) + entry point `google-compat` | new | `GeminiOpenAICompatClient(OpenAIBaseClient)`, template `amazon/nova/mantle.py` |
| `flows/dev_loop/dispatchers/google_compat.py` + `models/google_compat.py` (new) | new | `GoogleCompatCodeDispatcher(LLMCodeDispatcher)` + profile, template `dispatchers/nova.py` |
| `flows/dev_loop/models/base.py` (`DevAgentBackend`) + `agent_builder.build_dispatcher` | extends | add `"google-compat"` |
| `flows/dev_loop/dispatchers/google_coding.py` | depends on (fallback) | unchanged |
| `.parrot/mcp-toolkits.yaml` (new in repo) + `.mcp.json` | config | `sdd-coder` section; `parrot-sdd-coder` server entry |
| `docs/mcp-local-toolkits.md`, `docs/dev_loop/` | docs | install + roster semantics |
| `packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py` | extends | auto-discovers the new twin |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/` (new) | tests | roster/chunker/probe/job API; git sandbox for merge paths; Gemini compat dispatcher `extra_content` carry-over |
| `conf.WORKTREE_BASE_PATH` | depends on | feature + sub-worktrees must live under it (R4) |

No breaking change for external consumers; internal hard cuts are acceptable
(no deprecation shims).

---

## Code Context

### User-Provided Code

_None — the user provided the target flow in prose (see Problem Statement)._

### Verified Codebase References

All references verified on `dev@5bf8906a7` (2026-09-10).

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py
class TaskRef(BaseModel):                                   # line 25
    id: str; title: str = ""; status: str; depends_on: List[str]; file: str = ""
class TaskScheduler:                                        # line 53
    def __init__(self, tasks: List[TaskRef]) -> None        # line 64  (status=="done" → done, else pending)
    @classmethod
    def from_index_file(cls, path: Path) -> Optional["TaskScheduler"]   # line 88
    @classmethod
    def from_worktree(...)                                  # line 121
    def next_wave(self) -> List[TaskRef]                    # line 176
    def mark_done(self, task_id: str) -> None               # line 194
    def mark_failed(self, task_id: str) -> None             # line 203 (propagates skipped)
    def pending(self) / failed() / skipped() / done() -> List[TaskRef]   # lines 246-258

# From packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py
class PoolWorker:                                           # line 101 (worker_id, spec, dispatcher, profile)
class WaveResult:                                           # line 119
class DevAgentPool:                                         # line 135
    def __init__(self, *, config: DevAgentPoolConfig, workers: List[PoolWorker], pool_max: int)  # line 138
    @classmethod
    def build(cls, config: DevAgentPoolConfig,
              dispatcher_builder: Callable[[DevAgentSpec], Tuple[DevLoopCodeDispatcher, BaseModel]],
              pool_max: int) -> "DevAgentPool"              # line 155
    def _next_worker(self, failed_worker: PoolWorker) -> PoolWorker   # line 198 (wraps to the NEXT worker)
    async def run_wave(self, tasks: List[TaskRef], *, research: ResearchOutput, run_id: str,
                       cwd_for: Callable[[str], str], escalate: bool = False,
                       session_host: Optional[Any] = None) -> WaveResult   # line 435
        # assignment: tasks[i] -> workers[i % len(workers)]  (line ~480)
def aggregate_outputs(results: List[WaveResult], incomplete: List[str]) -> DevelopmentOutput   # line 574

# From packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py
class SubWorktreeMergeError(Exception)                      # line 41
class MergeReport(BaseModel)                                # line 57
class SubWorktreeManager:                                   # line 75
    def __init__(self, *, base_worktree: str, feature_branch: str, worktree_base_path: str)   # line 78
    async def create(self, worker_id: str) -> str            # line 146  branch f"{feature_branch}--{suffix}",
                                                             #   path WORKTREE_BASE/<feature_branch>--pool/<suffix>
    async def merge_sequential(self, *, resolver: Optional[Resolver] = None) -> MergeReport   # line 181
    async def refresh_all(self) -> None                      # line 264
    async def cleanup(self, *, keep_on_conflict: bool = True) -> None   # line 297
Resolver = Callable[[str, str], Awaitable[bool]]             # line 39

# From packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py
def build_dispatcher(spec: DevAgentSpec, *, redis_url: str, max_concurrent: int,
                     stream_ttl_seconds: int, config_getter: ConfigGetter = _default_config_getter
                     ) -> Tuple[DevLoopCodeDispatcher, BaseModel]   # line 135
    # backends: claude-code(177) codex(184) gemini(191) nvidia(198) grok(215) zai(223)
    #           moonshot(235) google_coding(246) nova(253)

# From packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
DevAgentBackend = Literal["claude-code","codex","gemini","nvidia","grok","zai","moonshot","google_coding","nova"]  # line 407
class DevAgentSpec(BaseModel):        # line 412: agent: DevAgentBackend; model: str=""; count: int=1; escalation_model: str=""
class DevAgentPoolConfig(BaseModel):  # line 438: agents: List[DevAgentSpec]; isolation_mode: Literal["shared","isolated"]="shared"
class TaskScopedBrief(BaseModel):     # line 458: research: ResearchOutput; task_id: str; task_file: str=""
class WorkerSummary(BaseModel):       # line 481: worker_id, agent, model, tasks_completed, tasks_failed, summary
class DevelopmentOutput(BaseModel):   # line 497: files_changed, commit_shas, summary, incomplete_tasks, worker_summaries
class DispatchLabels(BaseModel):      # line 763: task_id, task_title, task_file, seat, agent, model ...

# Dispatch profiles — every `subagent` literal must gain "sdd-coder"
class LLMCodeDispatchProfile(BaseModel):     # models/llm.py:10   subagent: Literal["sdd-worker"] (line 18); llm: str (19)
class NovaCodeDispatchProfile(LLMCodeDispatchProfile)   # models/nova.py:93  model default "minimax.minimax-m2.5", llm "nova:<model>"
class GeminiCodeDispatchProfile(BaseModel):  # models/gemini.py:15 subagent: Literal["sdd-worker"] (22); model: str="auto" (23)
class CodexCodeDispatchProfile(BaseModel):   # models/codex.py:10  subagent: Literal["sdd-worker","sdd-secondopinion"] (18); model="gpt-5.5" (19)
class ClaudeCodeDispatchProfile(BaseModel):  # models/claude.py:10 subagent: Optional[Literal[...6 names]] (18-27)
class GoogleCodingDispatchProfile(BaseModel) # models/google_coding.py: subagent Literal[...6 names] (line 21)

# From packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
class LLMCodeDispatcher:                     # line 51
    def __init__(self, *, max_concurrent: int, redis_url: str, stream_ttl_seconds: int,
                 client_factory: Callable[..., Any] = LLMFactory.create)   # line 60
    async def dispatch(self, *, brief: BaseModel, profile: LLMCodeDispatchProfile, output_model: Type[T],
                       run_id: str, node_id: str, cwd: str, session_host=None, labels=None) -> T   # line 113
    async def _chat_completion(self, *, client, model, messages, args)   # line 973 — requires client._chat_completion
    async def _publish_event(...)             # line ~2386 — Redis failure → warning, never raises

# From packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/nova.py  — TEMPLATE for the Gemini seat
class NovaCodeDispatcher(LLMCodeDispatcher):          # line 66
    def __init__(self, *, max_concurrent, redis_url, stream_ttl_seconds)   # line 78 → super().__init__(client_factory=self._create_mantle_client)
    def _create_mantle_client(self, llm: str, *, model_args=None, **kwargs) -> Any   # line 91 → BedrockMantleClient(api_key=..., base_url=..., model=...)
# From packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/mantle.py  (142 lines total)
class BedrockMantleClient(OpenAIBaseClient):          # line 35 — no _default_model/_fallback_model/_lightweight_model
    def __init__(self, api_key: str | None = None, base_url: str | None = None, region: str | None = None, **kwargs)   # line 103
# From packages/ai-parrot/src/parrot/clients/openai_base.py
class OpenAIBaseClient(AbstractClient):
    def __init__(self, api_key: str | None = None, base_url: str | None = None, **kwargs)   # line 89-92
    async def _chat_completion(self, model, messages, use_tools=False, stream=False, **kwargs)   # line 216 → self.client.chat.completions.create/parse

# From packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py  — FALLBACK seat, exists today
class GoogleCodingDispatcher:                          # line ~49: "agy --print ... --output-format stream-json" (headless)
    def __init__(..., agy_bin: str = "agy", ...)       # line 64; resolves via shutil.which (line 75)
# tests: packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py

# From packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py
_VALID_NAMES: frozenset[str]                 # line ~50: research, worker, qa, codereview, secondopinion, planner, feedback
def load_subagent_definition(name: str) -> str   # line 86 — reads ONLY _subagent_data/<name>.md

# From packages/ai-parrot/src/parrot/mcp/toolkit_config.py
class ToolkitSection(BaseModel):             # line 19: class_path(alias "class"), enabled, kwargs, include, exclude, llm, llm_kwargs, env
class MCPToolkitsConfig(BaseModel):          # line 79: toolkits: dict[str, ToolkitSection]
BUILTIN_TOOLKITS                             # line 89: scraping, browsing, memory
def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig   # line 105

# From packages/ai-parrot/src/parrot/mcp/toolkit_server.py
def create_toolkit_mcp_server(name: str, root: Path = Path.cwd(), **overrides) -> StdioMCPServer   # line 29
    # section.llm → LLMFactory.create(section.llm, **section.llm_kwargs)  (lines 99-105)

# From packages/ai-parrot/src/parrot/mcp/local_cli.py
@click.command("mcp-local")  # `parrot mcp-local <name> [--config] [--include] [--exclude] [--list]`
# registered lazily in parrot/cli/__init__.py:117  "mcp-local": "parrot.mcp.local_cli"

# From packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/base.py
class OptimizationToolkitBase(AbstractToolkit):   # line 33  arg_models: dict[str, type[BaseModel]]; __init__(*, repo_root, policy=None, **kw)
# From packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/writer.py
class TargetedWriterToolkit(OptimizationToolkitBase):   # line 194; _open (262) _close (267)
    async def writer_generate(self, task_path: str) -> OperationResult   # line 280
    async def writer_apply(self, artifact_id: str, reviewed_sha256: str) -> OperationResult   # line 584
# From packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC)                   # line 206

# From packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:                            # line 163
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]   # line 174
    @staticmethod
    def list_providers() -> Dict[str, str]    # line 215
    @staticmethod
    def create(llm: str, model_args=None, tool_manager=None, **kwargs) -> AbstractClient   # line 257
PROVIDER_BACKEND = {"bedrock": "bedrock", "anthropic-aws": "aws"}   # line 157 — `bedrock:` ⇒ AnthropicClient(backend="bedrock")
```

#### Verified Imports
```python
from parrot.flows.dev_loop.task_scheduler import TaskRef, TaskScheduler
from parrot.flows.dev_loop.agent_pool import DevAgentPool, PoolWorker, WaveResult, aggregate_outputs
from parrot.flows.dev_loop.worktree_manager import SubWorktreeManager, SubWorktreeMergeError, MergeReport
from parrot.flows.dev_loop.agent_builder import build_dispatcher
from parrot.flows.dev_loop.models import (DevAgentSpec, DevAgentPoolConfig, DevelopmentOutput,
                                          DispatchLabels, ResearchOutput, TaskScopedBrief, WorkerSummary)
from parrot.flows.dev_loop.dispatchers import DevLoopCodeDispatcher, DispatchExecutionError, DispatchOutputValidationError
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition
from parrot.mcp.toolkit_config import ToolkitSection, MCPToolkitsConfig, load_toolkits_config
from parrot.mcp.toolkit_server import create_toolkit_mcp_server
from parrot.tools.toolkit import AbstractToolkit
from parrot_tools.tool_optimizations.base import OptimizationToolkitBase
from parrot_tools.tool_optimizations.models import OperationResult, OperationError, StepResult
from parrot.clients.factory import LLMFactory
from parrot import conf   # conf.WORKTREE_BASE_PATH  (parrot/conf.py:828-829, default BASE_DIR/.claude/worktrees)
```

#### Key Attributes & Constants
- `DevAgentBackend` literal (models/base.py:407) — the only backends `build_dispatcher` accepts.
- `conf.WORKTREE_BASE_PATH` → `str` (parrot/conf.py:829) — dispatchers reject any `cwd` outside it (R4).
- Model ids known to the client packages:
  - `AnthropicModel.HAIKU_4_5 = "claude-haiku-4-5-20251001"` (ai-parrot-client-anthropic/.../anthropic/models.py:27)
  - `GoogleModel.GEMINI_3_5_FLASH = "gemini-3.5-flash"` (ai-parrot-client-google/.../google/models.py:27)
  - `OpenAIModel.GPT5_3_CODEX = "gpt-5.3-codex"` (ai-parrot-client-openai/.../openai/models.py:33)
  - Bedrock alias `"qwen3-coder-480b-a35b" → "qwen.qwen3-coder-480b-a35b-v1:0"` (ai-parrot-client-amazon/.../amazon/models.py:130, enum line 386); bedrock-mantle id is the suffix-less `qwen.qwen3-coder-480b-a35b-instruct` (comment at models.py:127-129).
- Registered provider keys in this venv (`LLMFactory.list_providers()`): `anthropic, anthropic-aws, bedrock, bedrock-converse, bedrock-mantle, claude, claude-agent, claude-code, codex-agent, codex-code, gemini-live, gemma4, google, grok, groq, hf, kimi, llamacpp, local, localllm, mantle, meta, meta-muse, moonshot, muse, nova, nvidia, ollama, openai, openai-codex, openrouter, transformers, vllm, xai, z.ai, zai`.
- Clients that implement `_chat_completion` (required by `LLMCodeDispatcher`): `OpenAIBaseClient` (parrot/clients/openai_base.py:216) and subclasses (openai, nvidia, groq, vllm, openrouter, zai, moonshot). **Not** anthropic, google, bedrock-converse.
- Per-spec index task fields (verified on `sdd/tasks/index/collaborative-adversarial-spec-design.json`): `id, title, slug, status, priority, effort, depends_on, parallel, parallelism_notes, assigned_to, started_at, completed_at, file, feature, feature_id, spec, verification`. Header fields include `dev_isolation` and `worktree_strategy` (both `null` today).
- Existing tests to extend/mirror: `packages/ai-parrot/tests/flows/dev_loop/{test_agent_pool.py, test_pool_models.py, test_pool_wiring.py, test_task_scheduler.py, test_worktree_manager.py, test_subagent_parity.py}`. `test_prompt_parity` auto-discovers every `_subagent_data/*.md` and requires a `.claude/agents/<name>.md` twin unless the name is in `_NO_REPO_TWIN` (line 26).
- Installed CLIs on this machine: `codex` (`~/.local/bin/codex`), `agy` (`~/.local/bin/agy`), `claude` (`~/.local/bin/claude`). A `gemini` binary exists at `/usr/bin/gemini` but is **not usable** (corporate-only product, deprecated in favour of `agy`) — do not plan on `GeminiCodeDispatcher`.
- Claude Code `Agent` tool accepts a per-call `model` override (`sonnet` / `opus` / `haiku`) and agent definitions carry a `model:` frontmatter key; no `.claude/agents/*.md` uses `model: haiku` today (all are `sonnet`, `product-analyst` is `opus`).
- FEAT-547 (`sdd-worker` twin sync) is **done** (TASK-3106 `done`), so `sdd-worker.md` and its twin are in parity on `dev` today.

### Spike evidence — Gemini OpenAI-compatible endpoint (2026-09-10)

Live smoke test from this repo's venv (`openai` SDK 3.3.1, key read via
`navconfig` `config.get("GEMINI_API_KEY")`, base URL
`https://generativelanguage.googleapis.com/v1beta/openai/`), using the
dispatcher's real `read_file`/`list_files` schemas:

| Check | Result |
|---|---|
| `models.list()` | serves `gemini-3-flash-preview`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.6-flash`, `gemini-3.8-flash` |
| `chat.completions.create(tools=…, tool_choice="auto", parallel_tool_calls=True, temperature=0.0, max_tokens=512)` on `gemini-3.5-flash` | `finish_reason="tool_calls"`, **two** tool calls in one turn, arguments as JSON strings, `usage` populated |
| same + `reasoning_effort="none"` | accepted, same shape |
| schema with `additionalProperties: false`, `minimum`, `maximum`, `default` | accepted unchanged (no need for `_fix_tool_schema`-style rewriting) |
| tool round-trip echoing the assistant turn as the minimal `{id,type,function}` dict (today's `_tool_call_to_openai_dict`) | **400** `Function call is missing a thought_signature in functionCall parts` |
| round-trip echoing `message.model_dump(exclude_none=True)` verbatim | OK, `finish_reason="stop"` |
| round-trip with the minimal dict **plus** the raw call's `extra_content` field | OK — this is the minimal fix |

Where the signature lives: `choices[0].message.tool_calls[i].extra_content
== {"google": {"thought_signature": "<opaque base64>"}}`; the message object
itself carries no extra fields. Google's compat doc states that parameters it
does not know are "silently ignored by the compatibility layer" and that
Gemini 3 "supports OpenAI compatibility for thought signatures in chat
completion APIs"; the function-calling doc adds "Only a subset of the OpenAPI
schema is supported" and "the API may reject very large or deeply nested
schemas" (not hit by the dispatcher's flat schemas). The key is **not** in the
process environment — it is loaded from `env/.env` by `navconfig`, so the
roster probe must use `navconfig.config.get(...)`, never `os.environ`.

### Does NOT Exist (Anti-Hallucination)
- ~~`bedrock:qwen3-coder`~~ as a working `llm` string — the `bedrock` provider key resolves to `AnthropicClient(backend="bedrock")` (factory.py:157); Qwen on Bedrock is reached via `nova`/`bedrock-mantle` (`qwen.qwen3-coder-480b-a35b-instruct`) or `bedrock-converse:qwen3-coder-480b-a35b`.
- ~~`qwen3-coder`~~ bare alias — only `qwen3-coder-480b-a35b` exists (amazon/models.py:130); `qwen3-coder-30b` appears only in a context-window table (bedrock.py:1692).
- ~~`gpt-5.3-codex-spark`~~ as a known constant — the OpenAI client only defines `GPT5_3_CODEX = "gpt-5.3-codex"`; the spark id is a passthrough string whose acceptance by Codex CLI must be smoke-tested.
- ~~`"sdd-coder"`~~ — not in `_VALID_NAMES`, not in any profile's `subagent` literal, no `.claude/agents/sdd-coder.md`, no `_subagent_data/sdd-coder.md`.
- ~~`parrot mcp-local sdd-coder`~~ / ~~`parrot-sdd-coder` in `.mcp.json`~~ — no such toolkit or server entry.
- ~~`.parrot/mcp-toolkits.yaml`~~ in the repo — only `examples/tool-optimizations-mcp.yaml` exists; `.parrot/` currently holds `wiki*`, `graph/`, `crew_wiki/`.
- ~~`parrot-targeted-writer` in `.mcp.json`~~ — FEAT-543's server is documented but **not registered** in the committed `.mcp.json` (only wikitoolkit, parrot-browsing, parrot-memory, parrot-scraping).
- ~~`LLMCodeDispatcher` driving `AnthropicClient` / `GoogleGenAIClient` / `BedrockConverseClient`~~ — none expose `_chat_completion`; `dispatch` raises `DispatchExecutionError("... does not expose chat completion")`.
- ~~A generic `"openai"` / `"anthropic"` / `"google"` `DevAgentBackend`~~ — `build_dispatcher` only knows the nine literals; `nvidia` is the sole in-process `LLMCodeDispatcher` route.
- ~~`DevAgentPool.run_wave` guaranteeing distinct models~~ — assignment is `workers[i % len(workers)]`; distinctness holds only when `len(tasks) ≤ len(workers)` (the chunker enforces this).
- ~~`TaskScheduler` honouring the index `parallel` flag~~ — it uses `depends_on` only; `parallel`/`parallelism_notes` are advisory hints written by `/sdd-task`.
- ~~`SubWorktreeManager` per-task API~~ — it is keyed by `worker_id`; reusing it per task means passing the task id as the key (branch `<feature>--TASK-NNN`).
- ~~`DevAgentSpec.provider`~~ / ~~`DevAgentSpec.llm`~~ — the fields are `agent`, `model`, `count`, `escalation_model`.
- ~~`google-compat` provider key / `GeminiOpenAICompatClient` / `GoogleCompatCodeDispatcher`~~ — none exist; the Google package registers only `google` and `gemini-live` (pyproject entry points), and no module in the repo references `generativelanguage.googleapis.com/v1beta/openai/`.
- ~~A working `gemini` CLI route (`GeminiCodeDispatcher`)~~ — the dispatcher class exists (`dispatchers/gemini.py`) but the CLI is not usable on this account; treat the backend as unavailable.
- ~~`ClaudeCodeDispatcher` in this design~~ — not used; the haiku seat is a native Claude Code sub-agent, so no nested-session scrubbing is needed.
- ~~`MCP_TOOL_TIMEOUT` / `MCP_TIMEOUT`~~ in repo or user settings — not configured anywhere; Claude Code defaults apply.
- ~~`tests/mcp/test_toolkit_config.py`, `tests/mcp/test_toolkit_server.py`~~ — referenced by `docs/tool-optimizations.md` but not found under `packages/*/tests` at this commit; do not cite them as existing.

---

## Parallelism Assessment

- **Internal parallelism**: three largely disjoint lanes — (1) Python: roster/probe/chunker models + `SddCoderToolkit` + tests; (2) prompts: `sdd-coder.md` + twin, `sdd-worker.md` rewrite + twin sync; (3) config/docs: yaml section, `.mcp.json`, `docs/`. Lane 2 depends on the final tool names from lane 1, and the `subagent` literal widening (small edits in `flows/dev_loop/models/*.py`) is shared by both, so full independence is not real.
- **Cross-feature independence**: FEAT-545 and FEAT-547 are complete on `dev`; FEAT-543's `/sdd-start` branch is untouched. Potential overlap with in-flight dev-loop work that edits `flows/dev_loop/models/*.py` or `dispatchers/claude.py` (FEAT-523 PEP-420 respec worktree is pending) — the edits here are one-line literal widenings and an env scrub, low conflict surface.
- **Recommended isolation**: `per-spec` (single worktree, tasks sequential), with the Python-lane tasks ordered first so the prompt tasks can reference verified tool names.
- **Rationale**: the feature is tightly coupled around one contract (tool names + result shapes + `subagent` name); splitting it across worktrees would only buy an hour or two and would risk the parity test and the literal edits colliding. Ironically the feature under design is the thing that will make `per-spec` cheap.

---

## Open Questions

Resolved during discovery (carried forward for `/sdd-spec`):

- [x] Feature or hotfix, and base branch? — *Owner: Jesus Lara*: `type: feature`, `base_branch: dev`.
- [x] How does Sonnet reach non-Anthropic coders? — *Owner: Jesus Lara*: a local MCP server (`parrot mcp-local`, targeted-writer pattern) wrapping the ai-parrot dispatchers; not Bash CLIs, not the dev-loop server. **Revised after research**: haiku is a native Claude Code sub-agent (`Agent(sdd-coder, model: haiku)`), not an MCP seat.
- [x] How is Gemini reached, given the `gemini` CLI is unusable? — *Owner: Jesus Lara*: in-process via Google's OpenAI-compatible endpoint, Nova/Mantle pattern (new `OpenAIBaseClient` subclass + `LLMCodeDispatcher` subclass); `google_coding` (`agy`) is the fallback, not the primary route.
- [x] Isolation between parallel coders? — *Owner: Jesus Lara*: one sub-worktree + child branch per task, merged sequentially by `sdd-worker`.
- [x] Why "never the same model in parallel"? — *Owner: Jesus Lara*: both load-spreading across providers and per-model quality telemetry; assignment is rotating and recorded in the Completion Note.
- [x] Does the dev-loop `DevelopmentNode` path change too? — *Owner: Jesus Lara*: no; only the interactive `sdd-worker`, twin synced for parity.
- [x] Relationship to FEAT-543 Delegation Contracts / eligibility table? — *Owner: Jesus Lara*: `sdd-coder` handles every task without exception; `writer_generate` is no longer `sdd-worker`'s delegation route.
- [x] Failure policy? — *Owner: Jesus Lara*: retry once on a different roster model, then `sdd-worker` implements it itself; never orphaned.
- [x] Commit / SDD-state ownership? — *Owner: Jesus Lara*: coder commits code only in its sub-worktree; `sdd-worker` owns index, task move and Completion Note.
- [x] Where does the roster live and what if a provider lacks credentials? — *Owner: Jesus Lara*: MCP server config with startup probe; unavailable entries skipped with a warning; single model ⇒ serial.

Resolved in the 2026-09-10 review round (Q1–Q11):

- [x] **Exact backend/model ids for the four seats** — *Owner: Jesus Lara*: config + probe with a declared fallback. Each roster entry in the yaml carries `model` and an optional `fallback_model` (e.g. `gpt-5.3-codex-spark` → `gpt-5.3-codex`); the startup probe makes a smoke call, switches to the fallback when the primary id fails, and reports the switch. Nothing hardcoded in Python.
- [x] **Gemini OpenAI-compatible endpoint coverage** — *Owner: Claude*: **verified live on 2026-09-10** (see "Spike evidence" under Code Context). `gemini-3.5-flash` is served; the loop's exact tool schemas (`additionalProperties: false`, `minimum`/`maximum`, `default`) are accepted; `tool_choice="auto"`, `parallel_tool_calls=True`, `temperature`, `max_tokens` and `reasoning_effort="none"` all succeed and two tool calls come back in one turn. **One blocker found and solved**: Gemini 3 requires the `thought_signature` of every tool call to be echoed back; it travels in `tool_call.extra_content.google.thought_signature`, and `LLMCodeDispatcher._tool_call_to_openai_dict` (llm.py:2237) drops it → 400. `GoogleCompatCodeDispatcher` must carry `extra_content` over when re-rendering the assistant turn (carrying only that field is sufficient — variant C passed). Unknown kwargs are silently ignored by the layer, so `extra_body.chat_template_kwargs` (only set when `enable_thinking=True`) is harmless but useless; use `reasoning_effort` instead.
- [ ] **`agy` fallback validation** — *Owner: Jesus Lara*: intended for the same spike, **not executed** — running the `agy` binary was declined in this session. The roster still declares `agent: google_coding` as the Gemini fallback and the probe detects it (`which agy` + smoke); live validation moves to the spec's spike task or to a manual `agy --help` / `agy --print` check by the user.
- [x] **Native haiku result contract** — *Owner: Jesus Lara*: `sdd-coder.md` requires the agent to end with the `DevelopmentOutput` JSON (same contract as the MCP seats); `sdd-worker` parses it, but `coder_merge` reconciles `files_changed` against `git diff --name-only` exactly as `DevelopmentNode` does. A missing or invalid JSON is not fatal when git shows valid commits; it is logged as a reporting defect.
- [x] **Job API bounds** — *Owner: Claude*: `coder_wait` timeout ≤ 300 s, idempotent, jobs live in the server until `coder_cleanup`; `sdd-worker` polls in a loop. No dependency on `MCP_TOOL_TIMEOUT` or any Claude Code setting.
- [x] **Where the toolkit package lives** — *Owner: Jesus Lara*: everything in core, `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/` (toolkit, roster, probe, chunker, job table, arg/result models), next to the FEAT-323 modules it composes. Rationale: it is SDD tooling over dev-loop internals, not an external-API wrapper (the `parrot_tools` rule targets those), it avoids `ai-parrot-tools` importing dev-loop internals, and `DevelopmentNode` can reuse the roster later.
- [x] **Semantics of the index `parallel` flag** — *Owner: Jesus Lara*: advisory. `depends_on` is the only scheduling input (current `TaskScheduler` behaviour); `parallel`/`parallelism_notes` are displayed in the plan but never change assignment. Two independent tasks that must not run together declare a dependency.
- [x] **Redis for dispatch telemetry** — *Owner: Jesus Lara*: optional. The toolkit passes `conf.REDIS_URL` when set; if Redis is unreachable it logs one warning at startup (not one per event) and per-task telemetry still flows through `WorkerSummary`/usage in the job result. Redis is documented as recommended, never required.
- [x] **Recovery after an MCP server crash mid-chunk** — *Owner: Claude*: `coder_plan` lists orphan `<feature>--TASK-NNN` branches with their state (commits, diff vs feature); adoption is explicit via `coder_merge(task_id)` (fidelity + merge) or deletion via `coder_cleanup`. No automatic merge of unsupervised work.
- [x] **Should the coder run the task's acceptance criteria itself** — *Owner: Jesus Lara*: yes, both. The coder runs its task's pytest/ruff in its sub-worktree (the loop already allows `pytest`/`ruff`/`mypy`); `sdd-worker` re-runs them after merge because integration with sibling branches can break them.
- [x] **`/sdd-start` interactive single-task path** — *Owner: Jesus Lara*: out of scope; `/sdd-start` keeps `writer_generate` (FEAT-543). Follow-up: offer a one-task `coder_run_chunk` from `/sdd-start` once the MCP is proven.

Follow-ups (not blocking the spec):

- [ ] Validate `agy` headless (`agy --print … --output-format stream-json`) with this account and decide whether `google_coding` stays as a fallback seat. — *Owner: Jesus Lara*
- [ ] Decide whether the `extra_content` carry-over belongs in the base `LLMCodeDispatcher._tool_call_to_openai_dict` (generic, benefits every OpenAI-compatible backend) or only in `GoogleCompatCodeDispatcher`. — *Owner: spec author*
