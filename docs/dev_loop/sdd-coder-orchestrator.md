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
   Claude Code then exposes the seven tools as
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

`sdd-worker`'s "## Orchestrator Loop (FEAT-549)" section runs, per wave:

0. `coder_plan(feature, worktree)` — if the tool is unavailable or returns
   `error.code: roster_empty`, fall back to the sequential loop (any other
   error code is a STOP condition).
1. Print the plan: roster availability, one line per chunk (task → seat),
   `blocked` ids, and every orphan branch.
2. Dispatch the **first** chunk in **one message**: `coder_run_chunk` for
   every non-native task id, and — for each `native: true` task —
   `coder_prepare_native` followed by `Agent(subagent_type="sdd-coder",
   model="haiku", …)` in the same message. This is the only way the native
   seat actually runs in parallel with the MCP seats.
3. Poll `coder_wait(job_id, timeout_seconds=120)` until `state != "running"`.
   `timeout_seconds` is clamped to **300 s** server-side regardless of what
   is requested — a timeout never leaves a job unresolved: it simply
   returns the current `"running"` snapshot, and jobs persist until
   `coder_cleanup` runs. **Never call `coder_status` or anything else in
   the same message as `coder_wait`** — the stdio MCP server handles
   requests strictly sequentially, so a second call in the same turn would
   queue behind the blocking wait instead of running concurrently.
4. Consolidate every task by outcome (see below), running acceptance
   criteria for every `merged` task before recording it.
5. `coder_cleanup(keep_conflicted=true)`, then repeat from step 1 until the
   plan's `chunks` and `pending` are both empty.
6. Continue to "## Completion": code review, push, and the summary —
   extended with a per-model table for this feature.

## Outcomes

| Outcome | Meaning | `sdd-worker` does |
|---|---|---|
| `merged` | Clean merge, fidelity passed | Run the task's acceptance criteria in this worktree, then step (g) with a Completion Note ending `Seat: … Backend: … Model: … Attempts: … Duration: … Tokens: …` from `attempts[*]` |
| `merge_conflict` | Content conflict against the feature branch | Resolve manually in this worktree, commit, call `coder_merge` again |
| `fidelity_violation` | The coder touched `sdd/` or a file not on its task's list | Treated as `failed` — never merged by hand |
| `failed` | Both attempts (assigned seat, then a different seat) errored | Attempt 3 is `sdd-worker`'s own: implement the task itself (Fallback loop steps c–f), then (g) |

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
   - `DEV_LOOP_CODER_TELEMETRY=true` (master switch, default False)
   - `DEV_LOOP_CODER_LEDGER=true` (bind the observational ledger, default True)
   - `SDD_CODER_TELEMETRY_DIR=/absolute/path` (durable dir, "" = derive from main checkout)

2. Run features normally with `parrot sdd-worker <feature>` — every attempt
   writes one append-only JSONL row per turn plus one outcome row.

3. Analyze with `python scripts/analyze_sdd_coder_usage.py --root <telemetry_dir>`
   to get consumption percentiles and budget recommendations.

Dataset schema (joins on `attempt_uid`):
| Row kind | Key fields | Description |
|---|---|---|
| `turn` | `seat_label`, `turn`, `ledger_input_tokens`, `ledger_output_tokens` | Per-turn token counts from the budget ledger |
| `outcome` | `seat_label`, `status`, `duration_s`, `provider_input_tokens`, `provider_output_tokens` | Final outcome with provider-reported totals |

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
- **`task_already_running`** — a job already owns that task id; check
  `coder_status(job_id)` rather than re-dispatching. If the server
  restarted mid-job, the branch/worktree persists and surfaces as an orphan
  on the next `coder_plan`.
- **`dirty_task_worktree`** — the coder left uncommitted or untracked
  changes; nothing is merged until the branch is clean.
- **Redis warnings** — dispatch telemetry to Redis is best-effort; a single
  startup warning when `REDIS_URL` is unreachable is expected and harmless.
  Set `REDIS_URL` to enable live event streams.

## Related

- Spec: `sdd/specs/sdd-worker-subagents.spec.md`
- Brainstorm: `sdd/proposals/sdd-worker-subagents.brainstorm.md`
- The FEAT-323 dev-loop pool (`DevAgentPool`/`TaskScheduler`/
  `SubWorktreeManager`) this kernel composes but does not replace.
- `docs/mcp-local-toolkits.md` — the local MCP toolkit mechanism this
  server is an instance of.
