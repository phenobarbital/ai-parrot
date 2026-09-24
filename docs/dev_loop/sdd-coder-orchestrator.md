# sdd-worker as orchestrator of parallel sdd-coder seats (FEAT-549)

## What it does

`sdd-worker` reads a feature's per-spec task index, computes dependency
waves (`depends_on`), and slices each wave into chunks of at most
`len(available_roster)` tasks. Inside a chunk, every task gets a **distinct**
model seat — never the same model twice in parallel — via a local MCP
server, `parrot-sdd-coder`, plus a native Claude Code sub-agent (`sdd-coder`,
Haiku) for the seat that has no MCP dispatcher. Each task runs in its own
git sub-worktree/branch; `sdd-worker` (Sonnet) consolidates every finished
attempt — clean-status check, file-fidelity check, then merge — and owns all
SDD state (the per-spec index, task moves, Completion Notes) throughout.
Coders never touch `sdd/`.

## Install

1. **Append** the `sdd-coder:` entry of `examples/sdd-coder-mcp.yaml` under the
   `toolkits:` key of `.parrot/mcp-toolkits.yaml` (git-ignored — operator-local).
   That file usually already holds other toolkits (`bounded-source`,
   `targeted-writer`, …), so **do not `cp` the example over it** — a copy
   replaces the whole file and silently drops every other toolkit you had
   configured. When `.parrot/mcp-toolkits.yaml` does not exist yet, and only
   then, a copy is safe:
   ```bash
   # File already exists — append just the toolkit entry (everything after `toolkits:`)
   sed -n '/^toolkits:/,$p' examples/sdd-coder-mcp.yaml | tail -n +2 \
     >> .parrot/mcp-toolkits.yaml

   # File does not exist yet — a copy is fine
   cp examples/sdd-coder-mcp.yaml .parrot/mcp-toolkits.yaml
   ```
   Either way, confirm with `parrot mcp-local --list --config
   .parrot/mcp-toolkits.yaml` that `sdd-coder` **and** every toolkit you had
   before are still listed.
2. Add an entry to `.mcp.json` (also git-ignored). Use **absolute** paths and
   an explicit `cwd`: MCP hosts start servers from their own working
   directory, so a relative `--config` resolves against the host's cwd, not
   the repository:
   ```json
   "parrot-sdd-coder": {
     "command": "/abs/path/to/repo/.venv/bin/parrot",
     "args": ["mcp-local", "sdd-coder",
              "--config", "/abs/path/to/repo/.parrot/mcp-toolkits.yaml"],
     "cwd": "/abs/path/to/repo"
   }
   ```
   Claude Code reads `.mcp.json` only at startup — restart it (and approve the
   project-scoped server) before `/mcp` will show `parrot-sdd-coder`.
   Claude Code then exposes the orchestration tools as
   `mcp__parrot-sdd-coder__coder_plan` … `mcp__parrot-sdd-coder__coder_cleanup`.
3. Credentials (none live in the yaml — see `examples/sdd-coder-mcp.yaml`'s
   own header comment):
   - `nova` (Qwen3-Coder on Bedrock Mantle): `BEDROCK_MANTLE_API_KEY` or
     `AWS_NOVA_API_KEY`.
   - `google-compat` (Gemini via Google's OpenAI-compatible endpoint):
     `GEMINI_API_KEY` or `GOOGLE_API_KEY`. **Both are read via `navconfig`
     from `env/.env` — they are NOT read from `os.environ` directly.** If
     you export them as plain shell env vars but never put them in
     `env/.env`, the seat is dropped as unavailable.
   - `codex` (GPT-5.3-codex-spark): the `codex` CLI's own login; the probe
     only checks the binary is on `PATH`.
   - `haiku` (native seat): no credentials — a Claude Code sub-agent
     (`.claude/agents/sdd-coder.md`), never an MCP dispatch.
4. `parrot mcp-local --list` should show `sdd-coder` among the servable
   toolkits.

## The roster

### Per-delivery correction feedback

At each coder handoff, the worker records confirmed code-review defects with
`coder_record_feedback`, including corrections it fixed immediately. Sources
are reviewed `fix(...) TASK-N review fixes` commits or verified review findings;
engine lint/autofixes are excluded. Repo-wide facts belong in conventions or
the task's Codebase Contract, not in one model's feedback. Model-specific
behavior defects carry task/attempt/backend/actual-model attribution, a stable
pattern slug, evidence, required correction, and regression verification.

The engine validates attribution against issued attempts. Native preparation
returns its model and unique attempt ID; MCP attribution uses `resolved_model`
when available. Feedback recording after a server restart cannot authenticate
old attempts: retain those records as NOT recorded in the Completion Note.
Already persisted feedback remains available across restarts and worktrees.

The shared SDD ledger stores these as `insight.recorded` events in the
`coder_feedback` category. They never become open work or merge blockers.
Replay deduplicates by backend/model/task/attempt/pattern, counts occurrences
in the active window, and ranks matching files/components before other lessons
from that model. Every MCP attempt (including retries) refreshes its brief;
the worker forwards `coder_prepare_native.coder_feedback` into the native prompt.

Configure `kwargs.feedback` alongside `kwargs.roster`:

```yaml
feedback:
  enabled: true
  max_tokens: 1800
  max_age_days: 90
```

Expired patterns stop being injected but remain durable. A new confirmed
occurrence reactivates the pattern; repeating a recording call does not.
Token budgets use the wiki's estimator, not a provider-specific tokenizer.
Retrieval failures produce an explicit unavailable notice. Use explicit model
names: unknown defaults cannot retrieve personal history, and dispatchers that
internally switch models may receive context for the configured model. Such
attempts are excluded from the known-exposure comparison.

After EVERY completed handoff review, call `coder_record_review` with identity,
`review_evidence`, and `fix_commits` (full SHAs, or `[]` for a clean delivery).
The engine verifies reachable `fix(...) TASK-N review fixes` commit subjects
and attaches observed feedback exposure. Count reviewer fixes for both repo
and model defects; do not count lint commits. Re-recording a completed review
updates its measurement without double-counting the attempt or commit.

`coder_feedback_report` reports correction commits per reviewed task by
backend/model and exposure, with sample sizes and mean injected tokens.
`feedback.enabled: false` supports collecting a baseline while still recording
reviews and lessons. Missing historical reviews are not inferred as zero fixes.
Comparison is descriptive: task difficulty can differ between cohorts, so
the report alone does not prove feedback caused an improvement. The worker's
review evidence remains the authority for completeness and defect attribution.

Restart the local MCP server to expose the three feedback/review tools after
updating the package. No model calls or model-weight changes are involved.

### Seat configuration

The roster is pure configuration (`kwargs.roster` in the yaml) — no model
id, backend, or provider key appears in Python or in either the
`sdd-worker`/`sdd-coder` prompts:

| label | kind | backend | model | fallback_model |
|---|---|---|---|---|
| `qwen` | mcp | `nova` | `qwen.qwen3-coder-480b-a35b-instruct` | — |
| `gemini` | mcp | `google-compat` | `gemini-3.5-flash` | — |
| `codex-spark` | mcp | `codex` | `gpt-5.3-codex-spark` | `gpt-5.3-codex` |
| `haiku` | native | — | `haiku` | — |

A **probe** runs on the very first tool call (`coder_plan` — there is no
server startup hook to run it earlier) and decides which seats are actually
usable right now: missing credentials/CLI drop an `mcp` seat with a
`reason`; a native seat is always available. When a seat's primary `model`
is rejected by an optional smoke check, its `fallback_model` is tried next
and the switch is reported (`fallback_used=True`). Dropped seats are never
silently skipped — `coder_plan`'s response lists every seat with its
availability and reason, and `sdd-worker` prints it.

## The loop

`sdd-worker`'s "## Orchestrator Loop (FEAT-549)" section runs, per wave. Every
step below carries the SAME `execution_id` — one UUID generated once per
worker invocation and reused across every chunk, retry, native agent, review
and cleanup call (see "Execution lifecycle and suspension policy" below):

0. **Begin execution.** Generate one UUID and call `coder_begin_execution(feature,
   worktree, execution_id)` before any plan or probe — it reads durable
   suspension history and applies recent exclusions first. If the tool is
   unavailable or returns an error, fall back to the sequential loop.
1. `coder_plan(feature, worktree, execution_id)`. Print the plan: roster
   availability (including any excluded/suspended models with their reason and
   remaining cooldown), one line per chunk (task → seat), `blocked` ids, and
   every orphan branch.
2. Dispatch the **first** chunk in **one message**: `coder_run_chunk(...,
   execution_id)` for every non-native task id, and — for each `native: true`
   task — `coder_prepare_native(task_id, execution_id)` followed by
   `Agent(subagent_type="sdd-coder", model="haiku", …)` in the same message.
   This is the only way the native seat actually runs in parallel with the
   MCP seats.
3. Poll `coder_wait(job_id, timeout_seconds=90)` until `state != "running"`.
   `timeout_seconds` is clamped to **300 s** server-side regardless of what
   is requested — a timeout never leaves a job unresolved: it simply
   returns the current `"running"` snapshot, and jobs persist until
   `coder_cleanup` runs. The 90-second client poll leaves margin below Claude
   Code's 120-second foreground MCP-call limit. Do not pair `coder_wait` with
   `coder_status` in the same message: the server now runs every `tools/call`
   as its own task (a read-only call is never queued behind a wait or a merge),
   so the second call is not blocked — it is simply a wasted poll.

   **Why the server is concurrent.** Until this change the stdio server awaited
   each request inline, so one handler stuck in an unbounded `git`/`ruff` child
   or waiting on the merge lock pinned every later call, and Claude Code's
   30-minute stdio idle timeout (`CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`) then
   killed them one by one — "the engine is unresponsive, even `coder_status`".
   Three guards close that: `tools/call` handlers are independent tasks and a
   host `notifications/cancelled` cancels the matching one; every engine-owned
   subprocess runs through `parrot.flows.dev_loop.procs.run_bounded` (own
   process group, `stdin=DEVNULL`, a wall-clock cap, headless `git_env()`); and
   `coder_merge` waits at most `MERGE_LOCK_TIMEOUT_S` for the feature-worktree
   merge lock before failing with `merge_busy` (retry later) instead of hanging.
4. Consolidate every task by outcome (see below), running acceptance
   criteria for every `merged` task before recording it. A `not_dispatched`
   task stays pending (never treated as completed); a `plan_stale` task is
   replanned without consuming an attempt. Report a confirmed native failure
   or critical review defect via `coder_suspend_model(execution_id, attempt_uid,
   reason, evidence_ref)` — this never means a live native child stopped.
5. `coder_cleanup(keep_conflicted=true, execution_id)`, then repeat from step 1
   until the plan's `chunks` and `pending` are both empty. An empty `chunks`
   list with pending tasks remaining is never completion.
6. **End execution.** Call `coder_end_execution(execution_id)` only once
   admitted work has settled and persistence succeeds (refuses with
   `execution_busy` otherwise). Then continue to "## Completion": code
   review, push, and the summary — extended with a per-model table for this
   feature.

### Inspection and compact projection (FEAT-584)

Prefer `coder_task_context` and `coder_delivery_report` for known task/delivery chains. For genuinely independent source queries, use one bounded-source `source_inspect_batch` call (at most eight operations, concurrency four); it is read-only and never a shell escape.

`coder_plan`, `coder_wait`, and `coder_status` retain `response_mode="full"` as their public default. The worker may explicitly request `"compact"`, but must recover mandatory evidence/pages with `coder_read_artifact` before dispatch, validation, merge, or acceptance. Compact output never changes routing, coverage, ownership, retry, fidelity, or the 90-second client poll.

The durable evidence store behind `compact` views, `coder_read_artifact`, `coder_record_native_observation` and review checkpoints is **always bound** — it does not depend on `DEV_LOOP_CODER_TELEMETRY`. Its root is `SDD_CODER_TELEMETRY_DIR` when set, otherwise `<main checkout>/artifacts/logs/sdd-coder-usage` derived via git; an explicit root that is relative or lands under the worktree base still fails engine construction. Only when no root can be derived at all does the engine start without a store and log a warning, and every dependent call then reports `evidence_persistence_failed`.

### Review boundary and compaction (FEAT-584)

After settlement: persist checkpoint; request at most one supported between-turn compaction; record its actual receipt; reload/validate the checkpoint; start a fresh independent reviewer. Do not compact per task/tool, inside a tool call, while work is live, or by invoking `/compact` through Bash.

`pre_review_compaction="auto"` is a policy request, not a host/context capability assertion. Record `skipped`, `unsupported`, `failed`, or unsettled `in_progress` explicitly; never blindly retry an unsettled receipt. Check installation diagnostics against the actual worktree, but never treat them as a capability handshake. Parent compaction is not evidence of native-child compaction.

The [SDD execution optimization](sdd-execution-optimization.md) guide records the current no-default decision. API defaults and host limits above remain unchanged until the concrete host driver, real receipt/review continuation, and controlled pilot provide sufficient evidence.

## Outcomes

| Outcome | Meaning | `sdd-worker` does |
|---|---|---|
| `merged` | Clean merge, fidelity passed | Run the task's acceptance criteria in this worktree, then step (g) with a Completion Note ending `Seat: … Backend: … Model: … Attempts: … Duration: … Tokens: …` from `attempts[*]` |
| `merge_conflict` | Content conflict against the feature branch | Resolve manually in this worktree, commit, call `coder_merge` again |
| `engine_busy` (error) | Another state-changing `coder_*` call held the toolkit's exclusive slot for more than 300 s (read-only calls never take it) | Retry the call once the other one returns |
| `merge_busy` (error) | Another consolidation held the feature-worktree merge lock for more than `MERGE_LOCK_TIMEOUT_S` (120 s) | Let the running job settle (`coder_wait`), then call `coder_merge` again |
| `fidelity_violation` | The coder touched orchestrator-owned SDD state (`sdd/tasks/`, `sdd/ledger/` — even if the task declares it) or a file not on its task's list, **or** its diff adds a banned import (`diagnostics` starts with `BannedImport:`) | Treated as `failed` — never merged by hand |
| `failed` | Both attempts (assigned seat, then a different seat) errored | Attempt 3 is `sdd-worker`'s own: implement the task itself (Fallback loop steps c–f), then (g) |
| `failed` + `diagnostics` starting `empty_delivery:` | The seat produced **no file change** (no commit, nothing in the tree, no declared file under an ignored path). On the MCP path the engine already ran the retry ladder (an empty attempt is a failed attempt, retried on another seat); from `coder_merge` (native path) the branch was not merged | Treat as `failed`: attempt 3 is `sdd-worker`'s, or re-dispatch once via `coder_run_chunk` when the classification is `standard` |
| `not_dispatched` | The task lost its seat (suspended/exhausted) before admission | Task stays pending — no synthetic attempt is recorded; replan or fall back |
| `plan_stale` | The cached plan's pool generation moved on since it was computed | Replan; the rejection does not consume an attempt |

Every task gets at most two coder attempts before `sdd-worker` takes over —
a task is never permanently orphaned.

## Branches & worktrees

Each attempt gets its own branch and sub-worktree:
`<feature_branch>--<TASK-NNN>-a<attempt>` under
`<WORKTREE_BASE_PATH>/<feature_branch>--pool/<TASK-NNN>-a<attempt>/`.
Orphan branches (left by an earlier crash, or a `fidelity_violation` that
was never adopted) are **listed** by every `coder_plan` call and **never
auto-merged** — `sdd-worker` decides per orphan whether to `coder_merge` it
or drop it with `coder_cleanup`.

## Complexity Routing (FEAT-561)

Task complexity is classified deterministically before dispatch using five signal families.
The classification drives model eligibility: **complex** and **unknown** tasks require explicit
strong-model candidates (`gpt-5.6-terra` or `sonnet-5`); standard tasks use the configured
roster rotation. This prevents weak models from being assigned to complex code changes.

### Scoring system

Five signal families, each rated 0–2 points (inclusive at thresholds):

| Signal | 0 points | 1 point | 2 points | Notes |
|---|---|---|---|---|
| Max existing cyclomatic complexity (C901) | 0–10 | 11–20 | ≥21 | Ruff C901 from MODIFY files only |
| Distinct impacted symbols, depth ≤2 | 0–9 | 10–29 | ≥30 | Static graph estimate; excludes inferred edges |
| Weighted file scope: CREATE + 2×MODIFY | 0–3 | 4–7 | ≥8 | Module (parent directory) count normalized |
| Distinct parent directories | 0–1 | 2 | ≥3 | CREATE or MODIFY actions |
| Task acceptance criteria | 0–4 | 5–7 | ≥8 | Checkbox items only; nested/fenced excluded |
| Transitive downstream tasks | 0–1 | 2–4 | ≥5 | From per-spec index; deduplicated |

**Hard triggers for complex classification** (any of):
- Total points ≥5
- Maximum existing cyclomatic complexity ≥21
- Blast radius (impacted symbols) ≥30
- Transitive downstream task count ≥5

**Classification outcomes**:
- **Complex**: meets any hard trigger OR all measurements are known and total ≥5
- **Standard**: all applicable measurements known, no hard trigger met, total <5
- **Unknown**: any required measurement missing/unavailable (e.g., Ruff error, wiki query failure)

Unknown tasks also require strong-model candidates until evidence is available.

### Routing rules

- **Standard tasks** use normal roster rotation (round-robin by label).
- **Complex/unknown tasks** route only to explicitly configured candidates:
  - `gpt-5.6-terra` (MCP seat backed by codex)
  - `sonnet-5` (native seat or explicit Claude configuration)
- If the configured seat is unavailable or already occupied in a chunk, the task blocks
  with error code `complex_model_unavailable` (not a dependency block); other ready
  tasks continue independently.
- Retries and fallbacks preserve the strong-model restriction: a failed strong coder
  cannot be retried through a weak seat.
- Exclusive tasks and ordering are preserved; one seat per chunk, never fill a gap
  with an ineligible coder.

### Model identity mapping

`complexity` is `SddCoderToolkit`'s own top-level kwarg (a sibling of `roster`,
forwarded to `RosterConfig.complexity` / `ComplexityPolicy` — the toolkit has
no separate `policy` kwarg). Field names follow
`ComplexityPolicy.strong_models: Tuple[StrongModelIdentity, ...]`
(`canonical_model`, `backend`, `model` — there is no `seat_label`); the actual
seat a candidate dispatches through is decided by matching `(backend, model)`
against the `roster` list, not by naming a seat directly:

```yaml
complexity:
  strong_models:
    - {canonical_model: gpt-5.6-terra, backend: codex, model: gpt-5.6-terra}
    - {canonical_model: sonnet-5, backend: native, model: sonnet-5}
```

An earlier, orphaned `policy: {strong_model_candidates: [{..., seat_label}]}` draft
of this same config was committed directly to `dev` (84fa5d78a, no spec/task) before
this feature landed; `SddCoderToolkit.__init__` never had a `policy` kwarg, so that
shape was inert. Superseded by the `complexity:` block above.

**Operator responsibility**: An operator may maintain a local identity mapping that
connects the canonical candidate (e.g., `sonnet-5`) to the exact provider model ID
deployed in their environment. Example mapping (operator-maintained, not in spec):

```
canonical: sonnet-5       → deployed: Claude-Sonnet-5-20260916
canonical: gpt-5.6-terra  → deployed: gpt-5.6-terra-2025-09
```

**Important**: Never silently equate `sonnet`, `haiku` or other aliases with `sonnet-5`.
The candidate names are fixed by policy; aliases are not validated as equivalents.
If an operator's environment does not have an exact match for a canonical candidate,
that candidate is unavailable and tasks remain blocked (no silent degradation).

### Evidence and artifacts

Before each dispatch, `coder_plan` collects pre-dispatch measurements and produces
a `ComplexityAssessment` containing:

- Classification (complex/standard/unknown)
- Total and per-component points
- Reason codes (hard trigger matched, e.g., `max_cc_≥21`)
- All raw metric values (C901 max, symbol count, file scope, etc.)
- Assessment ID (SHA-256 of canonical JSON)

Assessments are persisted to
`artifacts/sdd-coder/complexity/<feature-id>/<task-id>/<assessment-id>.json`
before dispatch; an audit write failure blocks that task. Displayed to `sdd-worker`
in the plan output, and referenced in attempt telemetry.

**Freshness**: Measurements are recomputed at planning time. Before dispatch,
task/index/policy/target file hashes and repository HEAD are revalidated. If any
change is detected, planning returns `error.code: complexity_plan_stale` instead of
proceeding with stale assignments — the orchestrator must request an explicit new plan.
This prevents silent assignment changes mid-feature.

### Collector behavior and limits

Evidence collection is asynchronous and bounded:

- **Ruff C901**: Runs in isolation with C901-only rules, ignores repo config, no caching.
  Exit code 2, malformed JSON, or syntax errors make that measurement unknown.
- **Wiki blast radius**: Depth-limited to 2 hops via `wikitoolkit symbols blast … --depth 2`.
  Missing graph revision tokens mean results are snapshots, not atomic. Failed queries or
  truncation are unknown, with the observed count retained as a lower bound.
- **Timeouts & failures**: Collection for a single task has a total budget; if exceeded,
  that measurement becomes unknown. The task is still planned, classified as unknown,
  and routed via strong-model candidates.

Never turn an unavailable tool (e.g., wiki down, Ruff missing) into a fabricated zero.
Unknown measurements preserve evidence state and block is reported clearly.

### Example output from `coder_plan`

```
Complexity routing:
  TASK-001: complex (assessment_id=abc123, max_cc=25, blast=35, score=6) → [gpt-5.6-terra]
  TASK-002: standard (assessment_id=def456, max_cc=8, blast=5, scope=2, score=2) → [qwen, gemini]
  TASK-003: unknown (assessment_id=ghi789, max_cc=unknown, blast=unknown) → [gpt-5.6-terra, sonnet-5]
  
  Blocked (complex_model_unavailable):
    TASK-004: strong-model candidate gpt-5.6-terra unavailable (offline)
    TASK-005: strong-model candidate sonnet-5 unavailable (already in chunk with TASK-006)
```

The worker displays this evidence and does NOT bypass a `complex_model_unavailable` block
through fallback or self-implementation. Complex/unknown tasks without an available seat
are reported and the feature waits for model availability.

## Conventions & lint backstop (FEAT-553)

Every MCP seat receives the repo's coder rules (`.agent/rules/codebase-conventions.md`
— one consolidated file covering Python, Cython, Rust and the Svelte admin UI — via
`parrot.flows.conventions.load_project_conventions`) inline in its prompt, right after
the `sdd-coder` body. The native seat reads the same file from `.claude/rules/`. Prompts are advisory; the guarantee is ruff rule `TID251`
(`ruff.toml`, `[lint.flake8-tidy-imports.banned-api]`): `requests`, `httpx`, `starlette`,
`fastapi`, `uvicorn` and every `langchain*`/`langgraph`/`langsmith` import fail
`ruff check`, and the engine runs the same check after every attempt (attempt error →
retry on another seat) and again at the merge boundary (`fidelity_violation`, also for
native tasks and re-merges).

## Telemetry

> **A coding attempt's cumulative token budget is measured in MILLIONS.** A
> 60-turn attempt whose history grows to ~148k tokens consumes ~4.7M cumulative
> tokens (~5.1M if every turn saturates `max_tokens`), because the full history
> is re-sent every turn and the MCP roster path runs at `max_turns=60`
> (`agent_builder.py:134`), not the profile default of 24. `token_budget` is
> NOT a context-window setting: 200,000 would kill every attempt around turn 11.
> Measurements: `artifacts/logs/sdd-coder-count-input-overhead-20260912.md`.

To collect and analyze token usage:

1. Enable telemetry by setting these environment variables:
   - `DEV_LOOP_CODER_TELEMETRY=true` (master switch for the usage-row sink, default False; the durable evidence store is bound regardless)
   - `DEV_LOOP_CODER_LEDGER=true` (bind the observational ledger, default True)
   - `SDD_CODER_TELEMETRY_DIR=/absolute/path` (durable dir, "" = derive from main checkout)

2. Run features normally with `parrot sdd-worker <feature>` — every attempt
   writes exactly one `attempt` row when it returns (success or failure),
   plus one or more `outcome` rows from `_run_task`/`merge()` (a
   `merge_conflict` followed by a repaired `merge()` legitimately produces
   two `outcome` rows for the same attempt; the highest `event_seq` wins).

3. Analyze with `python scripts/analyze_sdd_coder_usage.py --root <telemetry_dir>`
   to get consumption percentiles and budget recommendations.

Dataset schema (`<FEAT-ID>.jsonl`, one file per feature, joined on `attempt_uid`):
| Row kind | Key fields | Description |
|---|---|---|
| `attempt` | `seat_label`, `backend`, `duration_s`, `turns`, `terminal`, `turn_series`, `provider_input_tokens`, `provider_output_tokens`, `ledger_input_tokens`, `ledger_output_tokens`, `ledger_settled_estimate_input_tokens`, `calibration_eligible` | Terminal per-attempt telemetry — provider usage AND the ledger's estimated admission side by side, plus the full `turn_series` |
| `outcome` | `event_seq`, `outcome`, `conflict_file_count`, `unexpected_file_count` | One event per attempt outcome (`merged`, `failed`, `merge_conflict`, ...); the highest `event_seq` per `attempt_uid` is effective |

Note: The `gemini` seat records provider totals only, with no `ledger_*` fields,
because `GeminiOpenAICompatClient` defines no budget adapter, so that seat serves
as the unbudgeted comparison baseline.

## Troubleshooting

- **`roster_empty`** — every configured seat failed its probe; check the
  reasons `coder_plan` printed (missing key, missing CLI). `sdd-worker`
  falls back to the sequential loop.
- **HTTP 400 "Function call is missing a thought_signature"** — a
  regression in `GoogleCompatCodeDispatcher._tool_call_to_openai_dict`'s
  `extra_content` carry-over. Guarded by the opt-in live test:
  `pytest -m live packages/ai-parrot/tests/flows/dev_loop/test_google_compat_live.py`
  (needs `GEMINI_API_KEY`/`GOOGLE_API_KEY`).
- **`seat_busy`** (from `coder_prepare_native`) — the native model is still
  reserved by the task in `held_by_task_id`; a native reservation is released
  only by that task's `coder_merge`. Merge it first, then prepare the next task.
  The engine reports this immediately instead of waiting (a wait here parked
  the whole server on 2026-09-24: the releasing `coder_merge` could never be
  read while the stdio loop was serving requests one at a time — the loop now
  dispatches each request as its own task).
- **`task_already_running`** — a job already owns that task id; check
  `coder_status(job_id)` rather than re-dispatching. If the server
  restarted mid-job, the branch/worktree persists and surfaces as an orphan
  on the next `coder_plan`.
- **uncommitted coder deliveries** — a sandboxed seat has `.git` read-only by
  design and cannot commit; the engine extracts the task's **declared** files
  itself and commits them on the attempt branch (`_commit_declared_changes`,
  FEAT-587 / `ed267c217`). There is no `dirty_task_worktree` rejection. A file
  the coder produced but the task does not declare is never merged and never
  dropped: it surfaces as `fidelity_violation` with `unexpected_files` and the
  `undeclared_files_left_uncommitted` diagnostic.
- **Redis warnings** — dispatch telemetry to Redis is best-effort; a single
  startup warning when `REDIS_URL` is unreachable is expected and harmless.
  Set `REDIS_URL` to enable live event streams.
- **`LLM code dispatch exceeded max_turns=…`** — the in-process seats' library default is 40 turns
  (`LLMCodeDispatchProfile.max_turns`, FEAT-553); the roster path sets 60 via `build_dispatcher`
  (`DEV_LOOP_LLM_MAX_TURNS`). The effective value is in the `dispatch.completed` payload.

## Execution lifecycle and suspension policy

Each `sdd-worker` invocation owns one execution pool identified by a UUID. The
worker generates this ID at startup and propagates it to every MCP call and
native Agent prompt. The pool spans all chunks, retries, native agents, reviews
and cleanup for that execution.

**Begin execution:** Call `coder_begin_execution(feature, worktree, execution_id)`
before any plan or probe. This reads durable suspension history and applies
recent exclusions before probing eligible models. The configured roster remains
immutable; exclusions and reasons are exposed separately.

**Suspension triggers:**
- Dispatch timeout (including wrapped `TimeoutError`)
- Dispatch exception/nonzero CLI exit/provider unavailable
- Invalid `DevelopmentOutput` or exhausted unsuccessful delivery
- Dirty delivery or file-fidelity violation attributable to coder
- Worker confirms a critical code-review defect

**Suspension semantics:**
- First qualifying failure removes the model from that execution's pool.
- Suspension is durably recorded with validated attribution, reason, timestamp
  and fixed expiry (default 1800 seconds from failure observation).
- A new execution excludes all unexpired matching records before any probe.
- Cooldown expiry only affects new executions; duplicate begin/record/replay
  does not refresh expiry or clear local bans.
- Active pools remain independent; another execution's cleanup cannot mutate them.
- No native or MCP child is cancelled merely because its model was suspended;
  reservations settle explicitly.

**End execution:** Call `coder_end_execution(execution_id)` only after admitted
work settles and persistence succeeds. Keep `recovery_required` blocked until
completion/termination evidence is available.

**Configuration:**
```yaml
kwargs:
  suspension:
    cooldown_seconds: 1800
    history_max_tokens: 1200
```

**Migration:** Existing worktrees without execution IDs continue to work via
the sequential fallback loop. New executions require explicit begin/use/end
and visible exclusions. Coordinate MCP/worker upgrade by restarting the local
server after updating the package.

**Operator inspection:** no dedicated CLI subcommand exists for this feature.
Durable suspension records are `insight.recorded` events (category
`coder_suspension`) in the same shared-repository ledger
`coder_feedback`/`coder_review` already use (`<shared_root>/.parrot/ledger/events.jsonl`,
resolved via `parrot.knowledge.wiki.ledger.service.LedgerService.from_root`) —
read it with `parrot.knowledge.wiki.ledger.coder_suspensions.CoderSuspensionStore`
(`recent()`/`for_execution()`) the same way the engine itself does. Execution
snapshots are NOT in the ledger: they are per-worktree JSON files at
`<worktree>/.sdd-coder/executions/<uuid>.json` (git-ignored, written by the
engine's `_write_execution_snapshot`/`_read_execution_snapshot`); inspect one
directly or via `coder_status`. In tests, force expiry by advancing the
injected fake clock past `expires_at`; never shorten a real suspension by
rewriting a durable timestamp.

**Troubleshooting:**
- `execution_scope_mismatch`: ensure feature/worktree match the original begin call.
- `persistence_degraded`: check ledger permissions; retry idempotently at next status/end.
- `recovery_required`: establish completion/termination before cleanup/end; never assume
  a lost native child exited.
- `suspension_history_unavailable`: fall back to sequential worker loop; do not probe
  under an invented empty history.

## Scoped test selection (FEAT-563)

Cost is proportional to blast radius: a leaf change pays the mirror of directories; a core change
pays the suites of every distribution importing it — once. Full suite and e2e run only in CI.

| Tier | Where | Selection |
|---|---|---|
| `task` | every sdd-coder attempt (guard) | task `## Validation Commands` ∪ mirror; never escalates |
| `merge` | sdd-worker after each merge | mirror ∪ import-impact ∪ core escalation (ledger-deduped) |
| `feature` | qa-runner, QANode, `/sdd-done` | mirror ∪ all Validation Commands ∪ core escalation |

### CLI

```bash
python -m scripts.sdd.select_tests --tier {task,merge,feature} [--base origin/dev] \
    [--task-file sdd/tasks/active/TASK-NNN-x.md] [--worktree <path>] [--run] [--json]
```

Exit codes: `0` — every invocation passed (or, without `--run`, the plan printed cleanly);
`1` — an invocation failed; `2` — usage error, or an empty plan on the `task` tier (a task with
no `## Validation Commands` and no mirrored test directory has nothing to run). `--run` also
records green core escalations in the per-worktree escalation ledger so later tiers skip paying
for the same content twice. `--json` prints the `ScopePlanModel` (tiers, invocations, targets with
their `declared`/`mirror`/`core`/`escalated` reason, `core_hits`, `skipped_escalations`) without
running anything.

### Guard (task tier only)

The kernel is inert everywhere except inside an sdd-coder attempt: `coder_prepare_native`/the
engine's `_run_attempt` write an `AttemptContext` (tier, task id/file, base ref) to
`parrot-test-scope.json` in the **per-worktree** git admin dir (`git rev-parse
--absolute-git-dir` — not the shared common dir, so concurrent attempts never collide). Its mere
presence is what activates `guard_argv`/`guard_bash` (`test_scope/guard.py`) for that attempt;
outside an attempt (no context file) every guard call is a no-op. When the attempt issues a
pytest invocation broader than its task plan (no path, `tests/`, `packages/<dist>/tests`, or
similar), the guard either **rewrites** it to the task-tier plan (MCP seats via
`dispatchers/llm.py`'s `_run_guarded_invocations`, and the native Claude hook in
`worktree_environment.py`) or, when the plan is empty, **blocks** it outright. A codex seat
cannot have its argv rewritten transparently, so `parrot_tools.tool_optimizations.hooks.py`
(wired through `.codex/hooks.json` + `scripts/sdd/codex_hook.sh`) **denies** the call instead,
returning the scoped command the seat should run in its place.

### Core detection and escalation

A changed source module is *core* when its transitive source fan-in — every source module that
imports it, directly or indirectly, found by one AST pass over the worktree
(`test_scope/impact.py`'s `ImportIndex`/`source_fanin`) — is `≥ DEFAULT_CORE_FANIN_THRESHOLD`
(50), or its path is listed in `CORE_PATHS` (the manual override for AST-under-counted dynamic
imports/registries/the `parrot.tools.<x>` ↔ `parrot_tools.<x>` meta_path redirect — measured by
the TASK-3318 spike; see `artifacts/logs/feat-563-core-fanin.tsv`). A core hit escalates the
**package suite** of every distribution that (transitively) imports the changed module — never
the whole repo — and only on the `merge` and `feature` tiers; the `task` tier never escalates,
so a single sdd-coder attempt stays fast regardless of what it touches.

> **Cost callout (code review, 2026-09-17).** `CORE_PATHS` currently has 724 measured entries,
> and the two files the spec itself uses as worked examples — `clients/base.py` and
> `bots/abstract.py` — both escalate to ~25 of the repo's ~26 distributions (near-total-repo).
> Spec R13 anticipates this cost class for exactly these two files and names the escalation
> ledger plus a future xdist spike as mitigations; the ledger pays it once per core-file content
> (see below), but `XDIST_SAFE_DISTRIBUTIONS` still ships empty (S3), so the *first* hit per
> distinct content is a large serial run. If this magnitude proves too costly in practice, the
> options are: raise `DEFAULT_CORE_FANIN_THRESHOLD` above 50, re-run the S4 measurement with a
> narrower `CORE_PATHS` curation pass, or land an xdist-safety spike for the highest-cost
> distributions — not something to change unilaterally without new measurement evidence.

### Escalation ledger

Because a core escalation can be expensive, it is paid **once per content**: `record_
green_escalation`/`pending_escalations` (`test_scope/context.py`) key each distribution's
escalation by the git **blob hash** of the core file that triggered it, in
`parrot-test-scope-escalations.json` (per-worktree git admin dir, alongside the attempt context).
A green run for a given blob hash is skipped on later tiers; a changed blob hash (new content) or
a red run re-arms the escalation. A missing or malformed ledger is treated as **empty** — the
kernel always fails open to "run the escalation again", never silently skips one because its
bookkeeping was unreadable.

### Agent flags and marker expression

Every kernel-built pytest invocation applies `AGENT_FLAGS` (`-q --tb=short -p no:cacheprovider -o
log_cli=false`) and the marker expression `AGENT_MARKER_EXPRESSION = "not e2e and not real_llm and
not integration"` (`-m`), so agent-run tiers never pull in the suites CI alone owns.

### xdist allowlist

`XDIST_SAFE_DISTRIBUTIONS` (`test_scope/policy.py`) is the set of distributions proven safe under
`-n auto` (same per-test outcome as serial, twice). It is currently **empty**: the FEAT-563 S3
spike (`artifacts/logs/feat-563-s3-xdist.md`) could not complete a full serial-vs-xdist comparison
for any distribution within its time budget (`ai-parrot` alone extrapolates to ~2.3h for one
serial pass), and spec R7 ("either proven or excluded") makes the fail-safe default exclude every
distribution until new evidence lands. Add an entry only with a fresh comparison log.

### Codex operator config inheritance (R3b)

Codex **development** dispatches (`CodexCodeDispatchProfile`) no longer pass
`--ignore-user-config`, so the operator's `~/.codex/config.toml` — including its
`hooks.json`-driven `PreToolUse` hook — applies, which is what lets the codex-seat scope guard
above fire at all. Codex **review** profiles (`CodexCodeReviewProfile`,
`CodexAdversarialReviewProfile`) still pass `--ignore-user-config` and stay pinned: a review's
model/sandbox/approval must never vary with the operator's local config.

## Related

- Spec: `sdd/specs/sdd-worker-subagents.spec.md`
- Brainstorm: `sdd/proposals/sdd-worker-subagents.brainstorm.md`
- The FEAT-323 dev-loop pool (`DevAgentPool`/`TaskScheduler`/
  `SubWorktreeManager`) this kernel composes but does not replace.
- `docs/mcp-local-toolkits.md` — the local MCP toolkit mechanism this
  server is an instance of.
## Shared environment protection

Task agents may read and execute the main checkout's Python environment, but
must never install, uninstall, recreate, or repair files in it. Use installed
tools directly or `uv run --no-sync`. Dependency declarations may be changed
within task scope with `uv add --no-sync` / `uv remove --no-sync`. For installation,
create a real task-local environment and pass its interpreter explicitly to
`uv pip install --python .task-venv/bin/python ...`, or report the requirement
to the main-checkout operator for controlled installation.

`worktree_environment.py` builds the shared Bubblewrap runner used by all
in-process dispatcher subprocesses, including patch application. Native Claude
`sdd-worker` and `sdd-coder` definitions wrap Bash via `PreToolUse`; programmatic
Claude dispatch also injects these hooks because prompt loading strips YAML
frontmatter. Direct file-tool writes into shared environments, including symlink
aliases, are rejected. Codex workers must retain their host's workspace sandbox
and must not grant writable access to the shared environment.

The runner exposes the host filesystem read-only, with writable mounts for the
checkout and common Git directory and private `/tmp`. Claude Code's scratchpad
root (`/tmp/claude-<uid>`) is bound back over the private `/tmp`, so a seat's
session scratchpad survives from one Bash call to the next instead of vanishing
with each command. Shared environments remain
read-only even when inside a writable checkout. Child scripts inherit these
mounts; package-manager allowlists are only early feedback. Task package source
directories are prepended to `PYTHONPATH` so tests exercise the task checkout.

Linux hosts require Bubblewrap (`bwrap`) and permission to create its namespaces.
A missing executable or namespace failure stops the command; there is no
unsandboxed fallback. Nested container deployments must permit Bubblewrap or
provide a compatible execution host. Other CLI backends need equivalent host
filesystem protection; prompts alone are not a security boundary. This does not
isolate network services or untrusted tools running in external MCP processes.
