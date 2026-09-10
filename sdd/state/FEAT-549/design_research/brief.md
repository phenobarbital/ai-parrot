<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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

### Recommended option / probable scope
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

### Verified code anchors (paths only — open them yourself)
.claude/agents/sdd-coder.md
docs/tool-optimizations.md
examples/tool-optimizations-mcp.yaml
packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/mantle.py
packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/base.py
packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/writer.py
packages/ai-parrot/src/parrot/clients/factory.py
packages/ai-parrot/src/parrot/clients/openai_base.py
packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py
packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py
packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py
packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py
packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/nova.py
packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py
packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py
packages/ai-parrot/src/parrot/mcp/local_cli.py
packages/ai-parrot/src/parrot/mcp/toolkit_config.py
packages/ai-parrot/src/parrot/mcp/toolkit_server.py
packages/ai-parrot/src/parrot/tools/toolkit.py
packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py
sdd/tasks/index/collaborative-adversarial-spec-design.json

### Questions still open in the exploration document
- [ ] **`agy` fallback validation** — *Owner: Jesus Lara*: intended for the same spike, **not executed** — running the `agy` binary was declined in this session. The roster still declares `agent: google_coding` as the Gemini fallback and the probe detects it (`which agy` + smoke); live validation moves to the spec's spike task or to a manual `agy --help` / `agy --print` check by the user.
- [ ] Validate `agy` headless (`agy --print … --output-format stream-json`) with this account and decide whether `google_coding` stays as a fallback seat. — *Owner: Jesus Lara*
- [ ] Decide whether the `extra_content` carry-over belongs in the base `LLMCodeDispatcher._tool_call_to_openai_dict` (generic, benefits every OpenAI-compatible backend) or only in `GoogleCompatCodeDispatcher`. — *Owner: spec author*

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
