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

### Constraints and goals
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

### Recommended option / probable scope
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

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
packages/ai-parrot/src/parrot/flows/dev_loop/procs.py
packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py
packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py
packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/lint.py
packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py
packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py
packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py
packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml
scripts/sdd/cache_test_contract.py
scripts/sdd/check_task_graph.py
scripts/sdd/select_tests.py

### Questions still open in the exploration document
- [ ] Task-tier gate budgets per runner (pytest 60 s, vitest 120 s, cargo 300 s assumed) and whether a timeout re-dispatches the same seat or goes straight to the ladder. — *Owner: Jesus*: not decided yet — the spec keeps the assumed defaults in `.parrot/test_runners.toml` and measures them in the FEAT-563/699 style (`artifacts/logs/`) before freezing.

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
