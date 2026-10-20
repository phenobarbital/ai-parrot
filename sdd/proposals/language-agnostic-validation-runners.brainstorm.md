---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [dev-loop, sdd-tooling, ai-parrot-server, admin-ui]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [test-scope, sdd-coder, validation-contract, runners, task-tier, token-budget]
---

# Brainstorm: Language-agnostic validation runners and an engine-owned task-tier gate

**Date**: 2026-10-20
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

Two gaps remain after FEAT-563 (scoped test selection) and FEAT-699 (spec-declared
validation contract, green cache, baseline-aware verdict):

1. **The task tier still burns strong-seat tokens on raw test output.** The merge
   tier (`sdd-worker` → `coder_run_validation`) and the feature tier (`/sdd-done`)
   run pytest as a background subprocess owned by `ValidationSupervisor`; the
   model only reads a verdict. The task tier does not: every `sdd-coder` seat —
   Sonnet/Opus native, Nova, Gemini, codex — runs its task's `## Validation
   Commands` through `run_command` (MCP seats, `dispatchers/llm.py`) or Bash
   (native seats, `wikitoolkit claude-hook` → `worktree_environment._scope_guard`).
   The guard only *rewrites* an over-broad pytest to the task-tier plan; the full
   pytest stdout/stderr still lands in the seat's context. Discussion on
   2026-10-20 settled that delegating test *execution* to a cheaper LLM seat
   (haiku) is the wrong fix: running tests needs no intelligence, a model
   between the process and the evidence is an integrity risk (the `agy`
   fabricated-run incident), and the model-worthy part — interpreting a failure
   — is exactly where the strong seat is wanted. The right fix is a process that
   returns a structured verdict and a gate the seat cannot skip.

2. **The whole kernel is pytest-shaped.** `test_scope` types (`PytestInvocation`,
   `TestContract.tests` as "pytest operands"), parsing (`is_pytest_invocation`,
   `is_broad_pytest`), planning (`planner._invocation` hard-codes
   `("pytest", *AGENT_FLAGS, "-m", …)`), evidence (`report.parse_junit`), the
   guard and the supervisor all assume pytest. The same SDD flow is used in
   flowtask, querysource and other repositories with Cython and Rust code, and
   this repository ships a Svelte admin UI whose tests are `vitest run`
   (`packages/ai-parrot-server/ui/package.json:14`) and a deterministic E2E gate
   (`parrot e2e run`, FEAT-581) — none of which the contract can declare, plan,
   guard or record today.

**Who is affected**: every `sdd-coder` seat (token cost per attempt), `sdd-worker`
(merge-tier blind spots for UI/E2E), `/sdd-done` (closeout evidence has no
non-pytest rows), and maintainers of sibling SDD repos (no Rust/JS validation).

---

## Constraints & Requirements

- **Kernel stays stdlib-only and path-importable.** `test_scope/__init__.py` is
  loaded as top-level `test_scope` by the system-python native hook; no Pydantic,
  no `parrot.*` imports inside the kernel. Runner adapters therefore live in the
  kernel as plain modules; the Pydantic mirror of any new model lives in
  `sdd_coder/models.py` or `test_scope/models.py` (the existing boundary).
- **Never run a full suite from an agent-issued command** (FEAT-563 rule kept).
- **Evidence is produced by a process, never narrated by a model.** The task-tier
  verdict must be recorded through the same `report.append_suite` /
  `ValidationSupervisor` path as merge/feature tiers, with an `EvidenceRef`.
- **Decided in Rounds 1–2 (2026-10-20):**
  - Hybrid execution: a seat-callable `run_validation` tool for iteration **and**
    an engine-owned task-tier gate after the attempt commits, before fidelity →
    merge; on a red gate the engine re-dispatches the **same seat** with the
    verdict as feedback, counting as an attempt; a second red follows the normal
    retry ladder.
  - Verdict shape: counts + per-failure node id + bounded traceback excerpt
    (≈30 lines), `new_red` vs `baseline_red` where a baseline exists, `cached`
    targets, no raw stdout.
  - Runners in v1: pytest (refactored into an adapter), vitest, cargo test,
    `parrot e2e run` (deterministic only, never exploration).
  - Contract **schema 2** with `runners[]`; task `## Validation Commands` stay
    plain commands and are mapped to a runner by `argv[0]` through an adapter
    registry.
  - Adapters are code in the kernel, with a per-repo extension/override hook
    (`.parrot/test_runners.toml`) so sibling repos add runners without editing
    the kernel. Sibling repos vendor `scripts/sdd/` + `test_scope` by path
    (`parrot-installer`, FEAT-633, has not landed), so the TOML is the **only**
    extension point in v1.
  - Resolved after the interview (see Open Questions): fresh-conversation
    same-seat re-dispatch; `parrot-e2e` never in the task tier; cargo parses
    stable libtest text; native guard rewrites lone commands only; excerpts
    come from junit (or the adapter's own parse); schema 1 lifts on read.
  - Native-seat Bash that runs pytest/vitest/cargo inside an attempt is
    intercepted by the guard and **rewritten to the verdict-producing path**, so
    the seat gets the verdict instead of stdout and cannot bypass evidence.
- Backward compatible with schema-1 indexes (FEAT-699 is its own first consumer:
  `sdd/tasks/index/tests-optimization-sdd-flow.json` carries a schema-1 payload).
- Hard cuts are acceptable for internal APIs (no deprecation shims), but every
  caller of a renamed kernel type must be updated in the same feature.
- Task-tier gate budget: FEAT-563 evidence put the task tier under 60 s; the gate
  must not become the slowest step of an attempt (see Open Questions for E2E).

---

## Options Explored

### Option A: Runner adapters in the kernel + engine-owned task-tier gate + seat verdict tool

The kernel gains a `test_scope/runners/` package: a `RunnerAdapter` protocol
(recognise an argv, say whether it is over-broad, build a scoped invocation
for a set of targets, name the report format, parse the report into normalized
node results) and four concrete adapters — `pytest`, `vitest`, `cargo`,
`parrot_e2e` — plus a registry that loads the built-ins and merges a per-repo
`.parrot/test_runners.toml` (extra adapters by dotted module path, per-runner
settings such as the vitest `cwd`, the cargo crate list, the E2E plan path).
`PytestInvocation` becomes a runner-tagged `Invocation`; `TestContract` schema 2
carries `runners[]`; `plan_tests` groups targets per `(runner, distribution)`
and asks each adapter for its argv; `report.parse_junit` is one of several
report parsers behind a single `RunReport` with `nodes[(id, status)]`.

A new `ValidationVerdict` (kernel dataclass + Pydantic mirror) is the only thing
a seat ever sees: status, per-runner counts, `cached`, failures with
`new_red|baseline_red|unknown` and a bounded excerpt, notes, evidence ref.

Execution surfaces:
- **Seat tool** — MCP seats get a `run_validation` function tool in
  `LLMCodeDispatcher._tool_schemas` (no args beyond an optional target subset);
  it runs the task-tier plan through the supervisor path and returns the
  verdict. Native seats need no new tool: the guard rewrite (hook and
  `run_command`) targets `scripts/sdd/select_tests.py --tier task --run
  --verdict` whose stdout *is* the verdict JSON, so a seat that types `pytest`
  still gets the verdict, never the log.
- **Engine gate** — `_consolidate` runs the task-tier validation on the
  attempt's committed diff (after fidelity, before the locked merge). Red →
  `TaskResult(outcome="validation_failed", verdict=…)`; `_run_task` re-dispatches
  the same seat once with the verdict in the dispatch prompt (alongside
  `coder_feedback`), counting the attempt; a second red follows
  `_select_retry_seat`.
- Merge and feature tiers keep working unchanged, now planning non-pytest
  runners declared in the contract (green cache and baseline remain
  pytest-only in v1; other runners gate on any red).

✅ **Pros:**
- Task tier reaches token parity with merge/feature tiers: the seat context
  holds a verdict, not a log. Savings are independent of seat obedience.
- One evidence path for all tiers and runners (`append_suite`, junit-or-parser
  → `SuiteResult.nodes`), so `/sdd-done`'s table and the ledger get UI/E2E rows.
- The guard, planner and contract become runner-agnostic once; adding a fifth
  runner is one adapter module.
- Sibling repos add runners by config, not by forking the kernel.
- Same-seat re-dispatch preserves the cheapest path to green: the seat that
  wrote the code fixes it with a precise failure list.

❌ **Cons:**
- Largest blast radius of the three options: `datatypes`, `contract`, `select`,
  `planner`, `mirror`, `report`, `guard`, `background`, `engine`, `toolkit`,
  `dispatchers/llm.py`, `worktree_environment.py`, `select_tests.py`,
  `cache_test_contract.py`, `check_task_graph.py`, prompts and docs.
- `engine.py` (198 KB) and `background.py` get another responsibility each; the
  tasks touching them must be sequential.
- Two execution surfaces (tool + gate) means two code paths to keep consistent;
  mitigated by both calling the same supervisor entry point.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `tomllib` (stdlib, Python ≥ 3.11) | parse `.parrot/test_runners.toml` | already used by `sdd_coder/lint.py` |
| `xml.etree` (stdlib) | junit parsing | already the parser in `test_scope/report.py` |
| vitest `--reporter=junit --outputFile=<path>` | UI evidence in junit | built-in vitest reporter; runs with `pnpm exec vitest run` in `packages/ai-parrot-server/ui` |
| `cargo test` (stable) | Rust evidence | stable libtest text output (`test <name> ... ok|FAILED`) parsed by the adapter; `cargo nextest` junit is an optional upgrade |
| `parrot e2e run --plan <plan> --owner-id <id>` | deterministic E2E evidence | adapter reads `e2e-verdict.json` (`results`, `counts`) — never imports `parrot.e2e` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py` — `_pytest_operands`, `is_broad_pytest`, `normalize_pytest_argv` become the pytest adapter's body.
- `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` — `_invocation`/`build_plan` become the per-runner grouping point.
- `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` — `parse_junit`, `SuiteResult.nodes`, `append_suite`, `suite_name` are the evidence spine.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` — `ValidationSupervisor.start/_plan_selection/_supervise/_record_test_results` run every tier.
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` — `_tool_schemas`, `_run_tool`, `_tool_run_command`, `_run_guarded_invocations`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` — `_scope_guard`, `_load_guard_bash` (native hook path).
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` — `_consolidate`, `_run_task`, `_select_retry_seat`, `_feedback_for`, `_write_attempt_scope`.
- `scripts/sdd/select_tests.py`, `scripts/sdd/cache_test_contract.py`, `scripts/sdd/check_task_graph.py` — CLI, index caching, lint.

---

### Option B: Seat-only verdict tool, pytest-only kernel, generic "exit-code + report file" for everything else

Keep the kernel pytest-only. Add a `run_validation` tool for seats that runs the
task's declared `## Validation Commands` verbatim (any language), captures exit
codes, and — when a command wrote a junit file to a conventional path — parses
it; otherwise the verdict is `exit_code` plus the last N lines. No engine gate;
no contract change; non-pytest commands enter only through per-task commands.

✅ **Pros:**
- Smallest diff: one dispatcher tool, one CLI flag, prompt wording.
- Covers vitest/cargo/e2e immediately in the loosest sense (they run; the
  exit code is recorded).

❌ **Cons:**
- No gate: a seat that never calls the tool merges untested code; the token
  saving depends on obedience, which the roster's weakest seats do not give.
- The merge and feature tiers stay pytest-only: the contract cannot declare UI
  or E2E targets, so `sdd-worker` and `/sdd-done` remain blind to them.
- "Last N lines of stdout" is not a verdict; baseline/new-red semantics are
  unavailable, cached rows impossible, evidence not node-level.
- Postpones the kernel refactor to a later feature that will have to touch the
  same files anyway.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| stdlib only | subprocess + junit parse | reuses `procs.run_bounded`, `report.parse_junit` |

🔗 **Existing Code to Reuse:**
- `dispatchers/llm.py:_tool_run_command` — the tool is a thin wrapper over it.
- `test_scope/contract.py:parse_validation_commands` — declared commands as-is.

---

### Option C: Fully data-driven runners (TOML per runner, no adapter code)

Every runner is a TOML entry: `match_argv0`, `broad_when` (regex over argv),
`scoped_argv` template, `report = "junit" | "json:<jq-ish path>" | "exit-code"`.
A single generic executor runs the template and a single generic parser reads
junit or a JSON path. No Python per runner.

✅ **Pros:**
- Zero code to add a runner in any repo; the kernel never changes for a new
  language.
- Easy to review: the whole behaviour is a short config file.

❌ **Cons:**
- Real report formats do not fit a template: cargo's stable output is libtest
  text (no JSON on stable), `e2e-verdict.json` nests per-scenario results, and
  "is this invocation over-broad?" needs a parser (pytest operands after
  options with values, `uv run`/env prefixes) that a regex gets wrong — exactly
  the class of bug FEAT-563 fixed in code.
- Pushes logic into string templates that cannot be unit-tested as functions.
- Still needs the engine gate and seat tool of Option A to solve problem 1.

📊 **Effort:** Medium (and High once the template language grows to cover the
real cases)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `tomllib` | runner definitions | stdlib |

🔗 **Existing Code to Reuse:**
- `test_scope/report.py:parse_junit` as the only parser.

---

### Option D (unconventional, the question that started this): a cheap "verifier seat" (haiku) runs the tests and reports

A dedicated roster seat of `kind: native, model: haiku` receives the attempt
worktree after the coder commits, runs the Validation Commands, and returns a
`DevelopmentOutput`-like summary that the engine treats as the verdict.

✅ **Pros:**
- No kernel change; works for any language a shell can run.
- The strong seat never sees test output.

❌ **Cons:**
- A model between the process and the evidence can narrate a green that did not
  happen — the precise failure mode already observed with `agy` (invented
  188-test run). Evidence integrity is the reason the supervisor exists.
- It adds a second LLM hop whose only output is a summary a junit parser
  produces deterministically, for free, with node ids.
- Still no gate semantics (new-red vs baseline), no `cached` rows, no
  contract-level view for merge/feature tiers.
- The expensive part of a failure — diagnosis — returns to the strong seat
  anyway, now with a lossy summary instead of node ids and excerpts.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:** none new.

🔗 **Existing Code to Reuse:** `engine.prepare_native`, `roster.py` native seat probe.

---

## Recommendation

**Option A** is recommended because:

- It is the only option that solves **both** problems with one mechanism: the
  verdict the seat receives, the gate the engine enforces and the rows
  `/sdd-done` renders are the same `ValidationVerdict`/`SuiteResult` produced
  by the same supervisor path, for every runner. Options B and D leave the
  merge/feature tiers pytest-only and the verdict unstructured; Option C
  re-creates in templates the argv parsing FEAT-563 had to put in code.
- The token saving does not depend on seat behaviour. The guard already
  intercepts broad pytest for both MCP (`guard_argv`) and native (`guard_bash`)
  seats; redirecting that rewrite to a verdict-producing command is a small
  change to an existing seam, and the engine gate catches whatever the seat
  skipped.
- Evidence integrity is preserved by construction: the only thing that writes a
  test row is a subprocess whose junit/report the kernel parsed. Option D is
  rejected on exactly this point.
- The refactor cost (High) is paid once; FEAT-699 landed two days ago and its
  authors' context is fresh, the files are stable (no in-flight index touches
  `test_scope/*`, `background.py`, `engine.py` or `dispatchers/llm.py` as of
  2026-10-20), and the alternative is a second pass over the same files later.

What is traded off: `engine.py`/`background.py` grow again, and the feature has
a long sequential chain through them. Accepted because the gate and the tool
reuse `ValidationSupervisor.start` rather than adding a new runner, and because
green cache and baseline stay pytest-only in v1 (non-pytest runners gate on any
red), which keeps the new adapters small.

---

## Feature Description

### User-Facing Behavior

- **Spec authors** write `### Validation Contract` with runner blocks instead
  of a flat pytest list:
  ```markdown
  ### Validation Contract
  runners:
  - kind: pytest
    tests:
    - packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py
    markers: []
  - kind: vitest
    cwd: packages/ai-parrot-server/ui
    tests:
    - src/lib/components/FormRenderer.test.ts
  - kind: cargo
    crate: packages/<dist>/rust/<crate>
    filter: <optional test-name filter>
  - kind: parrot-e2e
    plan: sdd/state/FEAT-<NNN>/e2e-plan.md
    tiers: [merge, feature]
  ```
  `/sdd-task` caches it as `test_contract: {schema: 2, runners: [...], digest}`.
  The old single-list form still parses (it becomes one pytest runner) and
  schema-1 index payloads keep loading.
- **Task authors** keep writing `## Validation Commands` as commands
  (`pytest …`, `pnpm exec vitest run …`, `cargo test -p …`, `parrot e2e run
  --plan …`); the kernel recognises the runner from `argv[0]`.
- **`sdd-coder` seats** see a new tool, `run_validation`, documented in the
  prompt as the way to run tests. Its result is a compact JSON verdict:
  ```json
  {"status": "failed", "tier": "task", "runners": {"pytest": {"tests": 14, "passed": 12, "failed": 2, "errors": 0, "skipped": 0, "cached": 3}},
   "failures": [{"runner": "pytest", "nodeid": "packages/…/test_select.py::test_plan_contract_mode", "verdict": "new_red",
                 "excerpt": "… last 30 lines of the failure section …"}],
   "notes": ["contract mode", "2 target(s) cached"], "evidence": "validation/FEAT-710/TASK-4600/pytest-ai-parrot-1.xml"}
  ```
  A seat that runs `pytest`, `vitest` or `cargo test` through Bash/`run_command`
  inside an attempt gets the same verdict back instead of the raw log (the
  guard rewrites the command to the verdict path; a broad command with no
  scoped targets is still blocked with the FEAT-563 message).
- **Engine gate**: after a seat commits, the engine runs the task-tier
  validation on the committed diff. A red gate re-dispatches the same seat once
  with a `## Validation verdict` block in its prompt listing the failures; the
  attempt counter advances. A second red goes to the next seat of the retry
  ladder as today. `coder_status`/`coder_wait` expose
  `outcome: validation_failed` with the verdict so `sdd-worker` can record it
  (`coder_record_feedback`) and report it.
- **`sdd-worker` / `/sdd-done`**: merge and feature plans include non-pytest
  runners declared in the contract; the closeout "Tests" table gets one row per
  `<runner>:<distribution>` suite (`vitest:admin-ui`, `cargo:<crate>`,
  `parrot-e2e:<plan>`), with `cached`/`baseline red` columns filled only for
  pytest in v1 and marked `n/a` otherwise.
- **Sibling repos**: a `.parrot/test_runners.toml` declares which built-in
  runners apply, their settings, and optional extra adapters by module path.

### Internal Behavior

1. **Kernel refactor (stdlib-only).**
   - `test_scope/runners/base.py`: `RunnerAdapter` protocol — `kind`,
     `matches(argv) -> bool`, `operands(argv) -> list[str] | None`,
     `is_broad(argv, worktree) -> bool`, `invocation(targets, *, worktree,
     settings, report_path) -> Invocation`, `parse_report(path, exit_code, …)
     -> RunReport`, `tiers` (default all three; `parrot-e2e` defaults to
     merge+feature).
   - `test_scope/runners/registry.py`: built-ins + `.parrot/test_runners.toml`
     merge; `adapter_for_argv`, `adapter_for_kind`.
   - `datatypes.py`: `Invocation(runner, distribution, argv, targets, cwd,
     report_path)` replaces `PytestInvocation`; `TestContract(schema=2,
     runners=(RunnerContract(kind, targets, settings), …), digest)`;
     `ValidationVerdict`, `Failure` dataclasses.
   - `contract.py`: `parse_spec_contract` accepts both forms;
     `contract_from_index_header` accepts schema 1 (lifted into one pytest
     runner) and 2; `contract_to_header` writes 2; the pytest-specific helpers
     move into `runners/pytest.py` and are re-exported for the guard.
   - `select.py`/`planner.py`: targets carry `runner`; grouping is per
     `(runner, distribution)`; each adapter builds its argv; the marker
     composition and `-n auto`/`--confcutdir` logic stay inside the pytest
     adapter.
   - `report.py`: `RunReport` normalisation; `parse_junit` serves pytest,
     vitest and playwright; `runners/cargo.py` parses libtest text;
     `runners/parrot_e2e.py` parses `e2e-verdict.json` (`results[*].status`,
     `counts`) without importing `parrot.e2e`.
   - `guard.py`: `_is_pytest_argv` → `registry.adapter_for_argv`; the rewrite
     target becomes the verdict command (see 3).
   - `verdict.py`: builds `ValidationVerdict` from `RunReport`s + baseline
     verdicts + cached targets; excerpt extraction bounded to 30 lines per
     failure, from the junit `<failure>` text or the adapter's captured block.
2. **Supervisor task tier.** `ValidationSupervisor.start(tier="task",
   task_ids=[one], base_ref=<feature branch>, attempt_uid=…)`: the task tier
   diffs the attempt branch against the feature branch (the same `base_ref`
   `_write_attempt_scope` records), plans with the task's declared commands ∪
   file-level mirror (FEAT-699 task-tier rule), runs each invocation via
   `run_bounded` with the adapter's report path, records through
   `_record_test_results` under the attempt's task id, and settles the handle
   with the verdict attached to the receipt. `_TASK_ID_RE` stays as is (brief
   ids remain out of scope, as in FEAT-699).
3. **Verdict command.** `scripts/sdd/select_tests.py --tier task --run
   --verdict` prints only the verdict JSON (log to a file under the evidence
   root). Both guard surfaces rewrite to it: `worktree_environment._scope_guard`
   (native hook) and `LLMCodeDispatcher._run_guarded_invocations` (MCP), the
   latter returning the parsed verdict as the tool result rather than
   stdout/stderr.
4. **Seat tool.** `_tool_schemas` adds `run_validation` (`{targets?: [str]}`);
   `_run_tool` routes it to a `validation_runner` callable the engine injects
   into the dispatch context (the dispatcher never imports the engine). The
   callable wraps `ValidationSupervisor.start(tier="task")` + wait, bounded by
   the profile's `command_timeout_seconds`, and returns the verdict dict.
   Native seats keep their tool list (`Read, Write, Edit, MultiEdit, Bash,
   Glob, Grep`); their Bash path is covered by 3.
5. **Engine gate.** In `_consolidate`, after the fidelity gate on the committed
   diff and before the locked merge: start the task-tier validation for the
   attempt branch, wait (bounded), and on `status != passed` return
   `TaskResult(outcome="validation_failed", verdict=…)` without merging.
   `_run_task`: on `validation_failed`, if the attempt's seat has not yet been
   re-dispatched for a validation red, dispatch it again in a fresh
   sub-worktree seeded from the failed attempt branch, with the verdict
   rendered into the prompt next to `coder_feedback`; otherwise fall through to
   `_select_retry_seat`. `AttemptRecord` gains `validation` (verdict summary),
   `CoderResult` projections expose it.
6. **Contract caching and lint.** `cache_test_contract.py` writes schema 2;
   `check_task_graph.py` validates each runner block (kind registered, operand
   files exist for pytest/vitest, crate dir exists for cargo, plan file exists
   for `parrot-e2e`, `real_llm` still forbidden, `tiers` ⊆ `TIERS`).
7. **Docs and prompts.** `.claude/agents/sdd-coder.md` and its twin
   `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md`
   (both must change — see memory "sdd-worker prompt: two suites" for the
   `git add -f` gotcha), `sdd-worker.md`, `qa-runner.md`, `/sdd-done`,
   `sdd/templates/spec.md`, `docs/dev_loop/`.

### Edge Cases & Error Handling

- **Unknown runner in a contract** → `contract_from_index_header` raises
  (`ValueError`, admission failure) exactly like a malformed schema; never a
  silent fallback.
- **Runner declared but binary missing** (`pnpm`, `cargo`, `parrot`) →
  invocation result `status: "unavailable"`, verdict `failed` with a note;
  the gate fails closed (a declared runner that cannot run is a red, not a
  skip). The lint flags it before `/sdd-start` when the binary is resolvable
  at lint time.
- **Task-tier gate timeout** → verdict `timed_out`, treated as red; the
  re-dispatch prompt says so. The budget is per runner and configurable in
  `.parrot/test_runners.toml` (default: pytest 60 s, vitest 120 s, cargo 300 s;
  `parrot-e2e` never runs in the task tier by default).
- **Seat calls `run_validation` before committing** → it runs against the
  working tree (that is the iteration use); the engine gate re-runs on the
  committed diff, so an uncommitted green cannot leak.
- **Seat ignores the tool and runs `pytest` by Bash** → rewritten to the
  verdict command; a broad command with no scoped targets is blocked
  (`BLOCK_MESSAGE` unchanged). Compound commands outside the supported subset
  remain allowed as today (`guard_bash` conservative path) — the engine gate
  still covers them.
- **Non-pytest runner red on baseline too** → v1 has no baseline for vitest/
  cargo/e2e; the verdict marks those failures `unknown` and gates. Noted in the
  verdict so the seat does not chase a pre-existing red blindly; green-cache
  and baseline for vitest are follow-ups.
- **Same-seat re-dispatch when the seat is suspended/busy** (FEAT-559 pool) →
  skip straight to `_select_retry_seat`, recording why.
- **Two seats validating concurrently** → the supervisor already serialises
  per worktree (`exclusive=True` on the toolkit call); the attempt sub-worktree
  is the unit, so parallel attempts of different tasks do not contend.
- **Schema-1 index on a branch that predates this feature** → loads as a
  single pytest runner; `/sdd-task --refresh-contract` (or
  `cache_test_contract.py`) rewrites to schema 2 on the next run.
- **`parrot-e2e` in a repo without `ai-parrot-server`** → adapter resolves the
  `parrot` binary; absent → `unavailable` as above.

---

## Capabilities

### New Capabilities
- `validation-runner-adapters`: kernel-level runner protocol, registry, and
  the pytest/vitest/cargo/parrot-e2e adapters with per-repo TOML extension.
- `validation-contract-schema-2`: multi-runner `test_contract` payload, parser,
  caching and lint, with schema-1 lift.
- `validation-verdict`: bounded, structured verdict model and the
  `select_tests.py --verdict` command.
- `task-tier-validation-gate`: engine-owned post-commit gate with same-seat
  re-dispatch and verdict feedback.
- `seat-run-validation-tool`: dispatcher function tool and guard rewrite to the
  verdict path for MCP and native seats.

### Modified Capabilities
- `scoped-test-selection` (FEAT-563): guard and planner become runner-agnostic.
- `tests-optimization-sdd-flow` (FEAT-699): contract schema, task-tier rule,
  closeout table rows per runner.
- `sdd-worker-subagents` (FEAT-549): attempt lifecycle gains `validation_failed`
  and the same-seat retry rule.
- `sdd-done-tests` (FEAT-695): table rendering for non-pytest suites.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `test_scope/datatypes.py` | modifies | `PytestInvocation` → `Invocation`; `TestContract` schema 2; new `ValidationVerdict`, `Failure`, `RunReport` |
| `test_scope/contract.py` | modifies | runner-aware parse/cache; pytest helpers move to `runners/pytest.py` |
| `test_scope/runners/` | new | protocol, registry, 4 adapters, TOML loader |
| `test_scope/select.py`, `planner.py`, `mirror.py` | modifies | per-runner grouping; mirror only for pytest/vitest (file-level) |
| `test_scope/report.py` | modifies | `RunReport` normalisation; suite naming `<runner>:<dist>` |
| `test_scope/guard.py` | modifies | adapter-based detection; rewrite to the verdict command |
| `test_scope/verdict.py` | new | verdict builder + excerpt bounding |
| `sdd_coder/background.py` | modifies | `tier="task"` admission, attempt-scoped base ref, verdict on receipt |
| `sdd_coder/engine.py` | modifies | gate in `_consolidate`; same-seat re-dispatch in `_run_task`; `validation_runner` injection for dispatch |
| `sdd_coder/toolkit.py`, `models.py` | modifies | `coder_run_validation(tier="task")`; Pydantic `ValidationVerdictModel`; `validation_failed` outcome |
| `dispatchers/llm.py` | modifies | `run_validation` tool; guarded invocations return the verdict |
| `worktree_environment.py` | modifies | `_scope_guard` rewrite target; runner binaries on the sandbox PATH |
| `scripts/sdd/select_tests.py` | modifies | `--verdict` output mode; runner flags |
| `scripts/sdd/cache_test_contract.py`, `check_task_graph.py` | modifies | schema 2 write + lint |
| `.parrot/test_runners.toml` | new (optional) | per-repo runner config; absent ⇒ built-ins with defaults |
| `sdd/templates/spec.md`, `/sdd-spec`, `/sdd-task`, `/sdd-done` docs | modifies | authoring format, table columns |
| `.claude/agents/sdd-coder.md` + `_subagent_data/sdd-coder.md`, `sdd-worker.md`, `qa-runner.md` | modifies | tool usage, gate semantics |
| `.github/workflows/nightly-tests.yml` (FEAT-699) | extends (optional) | add the UI vitest suite to the nightly matrix |
| Breaking changes | internal only | `PytestInvocation` rename, `TestContract.tests` field removal; all in-repo callers updated in-feature |

---

## Code Context

### User-Provided Code

_None — all decisions were taken through the Round 0–2 interview on 2026-10-20._

### Verified Codebase References
(verified 2026-10-20 on `dev` @ `a5e1b59f2`; paths relative to `packages/ai-parrot/src/parrot/flows/dev_loop/` unless noted)

#### Classes & Signatures
```python
# test_scope/datatypes.py
class TestTarget:                                    # line 11 — path, distribution, reason ("declared"|"mirror"|"import"|"core"|"escalated"; planner also uses "contract")
class PytestInvocation:                              # line 22 — distribution, argv (starts with "pytest"), targets
class ScopePlan:                                     # line 42 — tier, invocations, escalated, core_hits, skipped_escalations, notes, cap_hits, cap_impacted, mode="fallback", cached=()
class TestContract:                                  # line 66 — schema: int (only 1), tests, markers, digest
class GreenCacheEntry:                               # line 78
class BaselineVerdict:                               # line 87 — nodeid, status ("new_red"|"baseline_red"|"unknown"|"flaky"), detail
class LedgerEntry:                                   # line 96
class AttemptContext:                                # line 106 — tier, task_id, task_file, base_ref

# test_scope/contract.py
VALIDATION_HEADING = "## Validation Commands"        # line 14
SPEC_CONTRACT_HEADING = "### Validation Contract"    # line 23
TEST_CONTRACT_SCHEMA: int = 1                        # line 24
def env_prefix_of(argv) -> list[str]                 # line 29
def strip_env_prefix(argv) -> list[str]              # line 39
def normalize_pytest_argv(argv) -> list[str]         # line 66
def parse_validation_commands(task_md: str) -> list[list[str]]   # line 71
def _pytest_operands(argv) -> list[str] | None       # line 91
def is_pytest_invocation(argv) -> bool               # line 141
def is_broad_pytest(argv, *, worktree=None) -> bool  # line 151
def contract_digest(tests, markers) -> str           # line 173
def parse_spec_contract(spec_md: str) -> TestContract | None     # line 227
def contract_from_index_header(header) -> TestContract | None    # line 291 — raises ValueError on shape/schema/digest
def contract_to_header(contract) -> dict[str, object]            # line 316
def load_index_header(index_path: Path) -> dict[str, object]     # line 326

# test_scope/select.py
def changed_files(worktree: Path, base_ref: str) -> list[str]    # line 20
def plan_tests(*, worktree, changed_files, tier, declared=(), contract=None, policy=None) -> ScopePlan   # line 123

# test_scope/planner.py
PER_DIST_EXTRA_ARGS = ("--confcutdir", "{worktree}")             # line 13
OVERRIDE_MARKER_EXPRESSION = "not real_llm"                      # line 18
def marker_expression_for(targets, *, contract, policy) -> str   # line 21
def _invocation(distribution, targets, *, worktree, policy, marker_expression=None) -> PytestInvocation  # line 32 — argv = ("pytest", *AGENT_FLAGS, "-m", expr, *xdist, *extra, *paths)
def build_plan(targets, *, tier, worktree, policy, escalated=(), core_hits=(), skipped_escalations=(), cap_hits=None, cap_impacted=None, notes=(), contract=None, mode="fallback") -> ScopePlan  # line 59

# test_scope/policy.py
AGENT_MARKER_EXPRESSION = "not e2e and not real_llm and not integration"   # line 7
AGENT_FLAGS = ("-q", "--tb=short", "-p", "no:cacheprovider", "-o", "log_cli=false")  # line 8
TIERS = ("task", "merge", "feature")                 # line 78
class ScopePolicy:                                   # line 82 — xdist_safe (:89), marker_expression (:100)

# test_scope/guard.py
BLOCK_MESSAGE: str                                   # line 15
class GuardOutcome: action ("allow"|"rewrite"|"block"), argvs, message   # line 24
def _is_pytest_argv(argv) -> bool                    # line 32
def _task_plan(worktree: Path) -> ScopePlan | None   # line 44 — reads AttemptContext, plans tier="task"
def guard_argv(argv, *, worktree: Path) -> GuardOutcome          # line 60
def guard_bash(command: str, *, worktree: Path) -> tuple[GuardOutcome, str | None]   # line 102

# test_scope/report.py
class SuiteResult:                                   # line 37 — suite, tests, passed, failed, errors, skipped, duration_s, exit_code, argv, status, nodes=(), unmapped=0, baseline=()
class TaskTestRecord:                                # line 56 — feature_id, task_id, head_sha, base_ref, tier, source, recorded_at, attempts, suites, notes, cached
def junit_path_for(feature_id, task_id, suite, ordinal) -> Path  # line 88
def with_junit(invocation: PytestInvocation, junit_path: Path) -> tuple[str, ...]   # line 106
def suite_name(invocation: PytestInvocation) -> str  # line 127
def parse_junit(junit_path, *, suite, argv, exit_code, duration_s, timed_out=False) -> SuiteResult   # line 146
def append_suite(...)                                # line 257
def append_cached(...)                               # line 307
def render_markdown(records, task_ids, *, final_head, rerun, rerun_skip_reason) -> str   # line 420

# test_scope/baseline.py
def classify_failures(*, repo_root, base_ref, failed_nodeids, timeout_s) -> tuple[BaselineVerdict, ...]   # line 156
def gate_failed(verdicts) -> bool                    # line 204

# test_scope/green_cache.py
def cache_namespace(*, feature_id, base_ref, contract_digest) -> str   # line 38
def filter_cached(worktree, plan, *, namespace) -> tuple[ScopePlan, tuple[str, ...]]   # line 156
def record_green(...)                                # line 223

# sdd_coder/background.py
_TASK_ID_RE = re.compile(r"^TASK-\d{1,5}$")          # line 76
_DEFAULT_BASE_REF = "origin/dev"                     # line 86
class ValidationSupervisor:                          # line 442
    async def start(self, *, feature, worktree: Path, execution_id, task_ids: list[str], tier: Literal["merge","feature"], timeout_seconds, request_id, base_ref=None, index_path=None) -> BackgroundRegistration   # line 493
    async def _plan_selection(...)                   # line 753
    async def _supervise(...)                        # line 868
    async def _record_test_results(...)              # line 1034

# sdd_coder/engine.py
async def run_validation(self, feature, worktree, execution_id, task_ids, tier: Literal["merge","feature"], timeout_seconds, request_id) -> BackgroundRegistration   # line 1149
async def record_native_observation(...)             # line 1240
async def _write_attempt_scope(self, worktree_path, task_id, task_file, base_ref) -> None   # line 2016 — writes AttemptContext(tier="task", …)
async def prepare_native(...)                        # line 2046
async def _feedback_for(self, ctx, task, backend, model) -> str   # line 2319
async def _consolidate(self, ctx, manager, task, *, branch, path, lock_timeout_s=None) -> TaskResult   # line 2640 — "extract+commit declared work -> fidelity (committed diff only) -> locked merge"
async def _run_attempt(self, ctx, task, seat, *, attempt, job_id, execution_id=None, pool=None) -> Tuple[AttemptRecord, Optional[DevelopmentOutput], str, SubWorktreeManager, str, str]   # line 3090
async def _select_retry_seat(...)                    # line 3598
async def _run_task(...)                             # line 3642
async def run_chunk(...)                             # line 3842

# sdd_coder/toolkit.py
async def coder_run_validation(self, feature, worktree, execution_id, task_ids: List[str], tier: Literal["merge","feature"], timeout_seconds: int, request_id: str) -> CoderResult   # line 602 — calls engine.run_validation with exclusive=True

# sdd_coder/models.py
class RosterSeat(BaseModel):                         # line 143 — kind "mcp"|"native"; native ⇒ backend None
class SeatProbeResult(BaseModel):                    # line 232

# sdd_coder/lint.py
LINT_TIMEOUT_S = 300.0                               # line 29
def resolve_bin(name: str) -> Optional[str]          # line 41 — PATH then sys.executable's bin dir

# sdd_coder/fidelity.py
PROTECTED_SDD_PREFIXES = ("sdd/tasks/", "sdd/ledger/")   # line 22
class FidelityReport(BaseModel)                      # line 32

# dispatchers/llm.py
class LLMCodeDispatcher:                             # line 67
    def _tool_schemas(self, output_model) -> List[Dict[str, Any]]   # line 1301 — read_file, list_files, search_files, edit_file, write_file, apply_patch, run_command, final_output
    async def _run_tool(self, *, tool_name, tool_args, cwd, profile, ...)   # line 1474
    async def _tool_run_command(self, cwd, args, profile) -> Dict[str, Any]   # line 1894 — guard_argv at 1945; block → stderr; rewrite → _run_guarded_invocations
    async def _run_guarded_invocations(self, argvs, *, cwd, timeout, hint) -> Dict[str, Any]   # line 2135

# worktree_environment.py
def command_policy_error(cwd: Path, argv) -> str | None   # line 102
def _load_guard_bash() -> Any                        # line 294 — package import or path import of test_scope.guard
def _is_lone_pytest(command: str) -> bool            # line 313
def _scope_guard(command: str, cwd: Path) -> tuple[str, str | None]   # line 324 — ("allow"|"rewrite"|"block", payload)

# procs.py
async def run_bounded(argv, *, cwd=None, timeout_s=DEFAULT_SUBPROCESS_TIMEOUT_S, env=None) -> Tuple[int, str, str]   # line 92

# models/base.py
class DevelopmentOutput(BaseModel):                  # line 520 — files_changed (required), commit_shas, summary

# packages/ai-parrot-server/src/parrot/e2e/runner.py
async def run_plan(plan_path: Path, *, worktree: Path, owner_id: str) -> E2EVerdict   # line 66
_VERDICT_NAME = "e2e-verdict.json"; _POINTER_NAME = "latest.json"   # lines 46-47
# packages/ai-parrot-server/src/parrot/e2e/models.py
class E2EVerdict(_E2EBaseModel):                     # line 504 — schema_version, feature_id, run_id, policy, selected_node_ids, collected_node_ids, results, counts, argv, exit_code
# packages/ai-parrot-server/src/parrot/e2e/cli.py
@e2e.command("run")   --plan <path> (required) --owner-id <id>   # lines 392-396
@e2e.command("verify") --plan <path>                              # line 429

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py
class CoderFeedback(BaseModel):                      # line 24 — task_id (TASK-\d{1,5}), attempt_uid, backend, model, …
```

#### Verified Imports
```python
from parrot.flows.dev_loop.test_scope import (      # test_scope/__init__.py:7-33 (stdlib-only; never Pydantic)
    AttemptContext, BaselineVerdict, CoreHit, GreenCacheEntry, LedgerEntry, PytestInvocation, ScopePlan,
    TestContract, TestTarget, VALIDATION_HEADING, changed_files, contract_from_index_header,
    deepest_existing_dir, distribution_of, is_broad_pytest, is_pytest_invocation,
    parse_validation_commands, parse_spec_contract, plan_tests, prune_nested,
    pytest_file_targets, pytest_target_for, pytest_targets,
)
from parrot.flows.dev_loop.test_scope.guard import GuardOutcome, guard_argv   # dispatchers/llm.py:59
from parrot.flows.dev_loop.test_scope.select import changed_files, plan_tests  # sdd_coder/background.py
from parrot.flows.dev_loop.test_scope.contract import contract_from_index_header, load_index_header, parse_validation_commands
from parrot.flows.dev_loop.test_scope import green_cache, baseline
from parrot.flows.dev_loop.procs import run_bounded                          # sdd_coder/lint.py:25
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedback, CoderFeedbackReceipt, CoderFeedbackStore   # sdd_coder/engine.py:35
```

#### Key Attributes & Constants
- `ScopePlan.mode` → `"contract" | "fallback"`; `ScopePlan.cached` → dropped targets (`datatypes.py:53-54`).
- `SuiteResult.nodes` → `tuple[(nodeid, status)]`, `SuiteResult.baseline` → `tuple[(nodeid, verdict)]` (`report.py:50-52`).
- `policy.TIERS` → `("task", "merge", "feature")` (`policy.py:78`); the supervisor's `tier` Literal is only `"merge" | "feature"` (`background.py:500`).
- Index header today: `sdd/tasks/index/tests-optimization-sdd-flow.json` carries `test_contract: {schema: 1, tests: [5 pytest operands], markers: [], digest: "sha256:…"}` and `validation_contract: "required"` (a different, FEAT-563 lint flag — keep untouched).
- UI test command: `packages/ai-parrot-server/ui/package.json:14` → `"test": "vitest run"`; config `packages/ai-parrot-server/ui/vitest.config.ts`, setup `vitest-setup.ts`; package manager is `pnpm`.
- Native hook wiring: `.claude/settings.json` PreToolUse `Grep|Glob|Read|Bash` → `.venv/bin/wikitoolkit claude-hook` (`knowledge/wiki/entry.py:18` `HOOK_ARGV = ["claude-hook"]`).
- Native `sdd-coder` tool list: `Read, Write, Edit, MultiEdit, Bash, Glob, Grep` (`.claude/agents/sdd-coder.md:26`-equivalent; twin `_subagent_data/sdd-coder.md:15`).
- Roster seats (`parrot/mcp/_toolkit_templates/sdd-coder.yaml:13-29`): qwen/gemini/codex-spark (mcp), haiku/opus/sonnet (native), gpt-5.6-terra/-sol (mcp strong).
- Repo config dir `.parrot/` exists (`mcp-toolkits.yaml`, `wiki.json`, `ledger/`, …) — the natural home for `test_runners.toml`.

### Does NOT Exist (Anti-Hallucination)
- ~~`tests/ui/_vitest.py`~~ — no vitest wrapper exists in the main checkout (the only `vitest` mention under `scripts/sdd` is a regex in `insight.py:99`).
- ~~`Cargo.toml` anywhere in this repository~~ — no Rust crate here; the cargo adapter is for sibling repos and must be testable with a fixture crate.
- ~~`coder_run_validation(tier="task")`~~ / ~~`ValidationSupervisor.start(tier="task")`~~ — both Literals are `"merge" | "feature"` today.
- ~~`run_validation` function tool in `LLMCodeDispatcher._tool_schemas`~~ — tools are read_file, list_files, search_files, edit_file, write_file, apply_patch, run_command, final_output.
- ~~`test_scope/runners/`~~, ~~`test_scope/verdict.py`~~, ~~`ValidationVerdict`~~, ~~`RunReport`~~, ~~`Invocation`~~ — new in this feature.
- ~~`.parrot/test_runners.toml`~~ — new, optional.
- ~~`select_tests.py --verdict`~~ — today's output modes are `--json` plan and `--run` log.
- ~~a same-seat retry rule in `_select_retry_seat`~~ — the ladder skips `kind: native` and moves to the next seat (ledger issue `569e81756247`).
- ~~`TaskResult.outcome == "validation_failed"`~~ — not an outcome today.
- ~~guard recognition of `vitest` / `cargo test` / `parrot e2e`~~ — `_is_pytest_argv` and `_is_lone_pytest` only know `pytest`/`python -m pytest`.
- ~~`parrot.e2e` importable from the kernel~~ — it lives in `ai-parrot-server` and uses Pydantic; the adapter must parse `e2e-verdict.json` from disk only.
- ~~green cache / baseline for non-pytest runners~~ — out of v1 (nodes from vitest junit could feed the cache later).

---

## Parallelism Assessment

- **Internal parallelism**: three lanes exist. (1) Kernel lane — `test_scope/runners/*`, `datatypes`, `contract`, `select`/`planner`, `report`, `verdict`, `guard`, `select_tests.py`, lint/cache scripts — is one sequential chain inside `test_scope` but independent of the engine. (2) Execution lane — `background.py` task tier → `engine.py` gate and same-seat retry → `toolkit.py`/`models.py` projections → `dispatchers/llm.py` tool → `worktree_environment.py` rewrite — strictly sequential on `engine.py`/`background.py`. (3) Docs/prompts/templates/nightly — parallel to both once the verdict shape is frozen. Lanes 1 and 2 meet at the `ValidationVerdict`/`Invocation` types, so the kernel datatypes task must land first.
- **Cross-feature independence**: no active per-spec index touches `test_scope/*`, `sdd_coder/engine.py`, `sdd_coder/background.py` or `dispatchers/llm.py` (checked 2026-10-20). Adjacent: FEAT-703 (`TASK-4460` active, `scripts/sdd/check_e2e_closeout.py`) reads the same `e2e-verdict.json`; FEAT-633 (spec rev 0.3) plans changes to `worktree_environment.py` — coordinate the `_scope_guard` edit. FEAT-708's worktree exists but touches `sdd-proposal` research only.
- **Recommended isolation**: `mixed` — one feature worktree; kernel-lane tasks may fan out to pool sub-worktrees per module once `datatypes` lands; execution-lane tasks run sequentially in the main feature worktree; docs lane fans out.
- **Rationale**: the two heavy files (`engine.py`, `background.py`) dominate merge risk and must be edited by one coder at a time, while adapters are small, self-contained modules with their own fixtures (junit samples, libtest text, a fixture crate, an `e2e-verdict.json`) that parallelise well.

---

## Open Questions

- [x] How do flowtask/querysource consume the kernel — vendored `scripts/sdd/` + `test_scope` by path, or an installed `ai-parrot` dependency? — *Owner: Jesus*: **vendored copy for now** (`parrot-installer`, FEAT-633, has not landed). Consequence: `.parrot/test_runners.toml` is the **only** extension point in v1 (adapters by dotted module path resolved relative to the vendored `test_scope`); no Python entry-point registry, nothing that assumes an installed `parrot` distribution.
- [x] Same-seat re-dispatch: fresh conversation or resumed history? — *Owner: Jesus*: **fresh conversation + verdict**. The re-dispatch is an ordinary `_run_attempt` on the same seat, in a fresh sub-worktree seeded from the failed attempt branch, with the verdict rendered into the prompt beside `coder_feedback`; no dispatcher message persistence.
- [x] Should `parrot-e2e` ever run in the task tier? — *Owner: Jesus*: **no**. The adapter's default `tiers` is `(merge, feature)`; the task tier ignores `parrot-e2e` runner blocks even if a contract lists `task` (lint warns).
- [ ] Task-tier gate budgets per runner (pytest 60 s, vitest 120 s, cargo 300 s assumed) and whether a timeout re-dispatches the same seat or goes straight to the ladder. — *Owner: Jesus*: not decided yet — the spec keeps the assumed defaults in `.parrot/test_runners.toml` and measures them in the FEAT-563/699 style (`artifacts/logs/`) before freezing.
- [x] Cargo adapter: stable libtest text or `cargo nextest`? — *Owner: Jesus*: **stable libtest text** (`test <name> ... ok|FAILED|ignored` lines + the `failures:` section for excerpts). nextest/junit is a later, optional upgrade.
- [x] Guard scope for native Bash. — *Owner: Jesus*: **lone commands only** — rewrite a single `pytest|vitest|cargo test` invocation (what `_is_lone_pytest` does today, generalised through the adapter registry); compound commands keep today's conservative `guard_bash` handling, and the engine gate covers whatever slips through.
- [x] Where does the verdict excerpt come from? — *Owner: Claude (spec)*: **junit**, recommended for three reasons: (1) the supervisor already runs every pytest invocation with `--junitxml` (`_argv_with_junit`, `with_junit`) and `--tb=short`, so the `<failure>` body *is* the short traceback with no second capture; (2) junit is node-level, so the excerpt is attached to the exact failing `nodeid` and the same mapping feeds baseline classification and the green cache; (3) vitest (`--reporter=junit`) and playwright produce the same shape, so one bounding rule (last 30 lines of `<failure>`/`<error>` text) serves three runners. Caveats the spec must state: pytest's junit omits captured stdout/stderr unless `-o junit_logging=…`, which is the desired behaviour (excerpt = traceback, never log); runners without junit (cargo, `parrot-e2e`) take their excerpt from the adapter's own parse (libtest `failures:` block, `results[*].detail`), bounded by the same rule.
- [x] Schema-2 migration of existing indexes. — *Owner: Jesus*: **lift on read**. `contract_from_index_header` accepts schema 1 and returns the schema-2 shape (one pytest runner); indexes are rewritten to schema 2 only when `/sdd-task` or `cache_test_contract.py` next touches them. No one-shot migration commit.
