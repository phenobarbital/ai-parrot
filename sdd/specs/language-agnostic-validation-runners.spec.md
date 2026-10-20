---
type: feature
base_branch: dev
projects: [dev-loop, sdd-tooling, ai-parrot-server, admin-ui]
tags: [test-scope, sdd-coder, validation-contract, runners, task-tier, token-budget]
---

# Feature Specification: Language-agnostic validation runners and an engine-owned task-tier gate

**Feature ID**: FEAT-709
**Date**: 2026-10-20
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 0.30.0

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Two gaps remain after FEAT-563 (scoped test selection) and FEAT-699 (spec-declared
validation contract, green cache, baseline-aware verdict):

1. **The task tier still burns strong-seat tokens on raw test output.** The merge
   tier (`sdd-worker` → `coder_run_validation`) and the feature tier (`/sdd-done`)
   run pytest as a background subprocess owned by `ValidationSupervisor`; the model
   only reads a verdict. The task tier does not: every `sdd-coder` seat — Sonnet/Opus
   native, Nova, Gemini, codex — runs its task's `## Validation Commands` through
   `run_command` (MCP seats, `dispatchers/llm.py`) or Bash (native seats,
   `wikitoolkit claude-hook` → `worktree_environment._scope_guard`). The guard only
   *rewrites* an over-broad pytest to the task-tier plan; the full pytest
   stdout/stderr still lands in the seat's context. Delegating test *execution* to a
   cheaper LLM seat was rejected in the brainstorm (Option D): running tests needs no
   intelligence, a model between the process and the evidence is an integrity risk
   (the `agy` fabricated-run incident), and interpreting a failure is exactly where
   the strong seat is wanted. The right fix is a process that returns a structured
   verdict and a gate the seat cannot skip.

2. **The whole kernel is pytest-shaped.** `test_scope` types (`PytestInvocation`,
   `TestContract.tests` as "pytest operands"), parsing (`is_pytest_invocation`,
   `is_broad_pytest`), planning (`planner._invocation` hard-codes
   `("pytest", *AGENT_FLAGS, "-m", …)`), evidence (`report.parse_junit`), the guard
   and the supervisor all assume pytest. The same SDD flow is used in flowtask,
   querysource and other repositories with Cython and Rust code, and this repository
   ships a Svelte admin UI whose tests are `vitest run`
   (`packages/ai-parrot-server/ui/package.json:14`) and a deterministic E2E gate
   (`parrot e2e run`, FEAT-581) — none of which the contract can declare, plan, guard
   or record today.

### Goals

- A **runner-agnostic kernel**: a `RunnerAdapter` protocol, a registry with four
  built-in adapters (pytest, vitest, cargo, parrot-e2e) and a per-repo
  `.parrot/test_runners.toml` as the **only** extension point (sibling repos vendor
  `scripts/sdd/` + `test_scope` by path; `parrot-installer` has not landed).
- **Validation Contract schema 2** with `runners[]`; schema-1 payloads lift on read
  into one pytest runner; indexes are rewritten only when `/sdd-task` or
  `cache_test_contract.py` next touches them.
- A bounded, structured **`ValidationVerdict`** — counts per runner, `cached`,
  failures with `new_red | baseline_red | unknown` and a ≤30-line excerpt taken from
  junit (or the adapter's own parse) — the only thing a seat ever sees.
- **Hybrid task-tier execution**: a seat-callable `run_validation` tool for
  iteration **and** an engine-owned gate after the attempt commits (post lint
  autofix, pre merge lock, against the fork SHA). A red gate re-dispatches the
  **same seat** once in a fresh conversation seeded from the failed branch with the
  verdict, counting as an attempt; a second red follows the retry ladder.
- **Seat-proof token saving**: a native-seat Bash `pytest|vitest|cargo test` lone
  command inside an attempt is rewritten to the verdict command; an MCP-seat
  `run_command` to a runner is rewritten to the capability and returns verdict data
  only.
- Evidence is produced by a process and persisted through the supervisor and
  `ExecutionEvidenceStore` before any verdict is returned — never narrated by a model.
- Non-pytest runners gate on **any** red in v1 (no green cache, no baseline); cache
  and baseline are explicitly pytest-scoped.

### Non-Goals (explicitly out of scope)

- A haiku/LLM "verifier seat" that runs tests and reports — rejected in brainstorm
  Option D (`sdd/proposals/language-agnostic-validation-runners.brainstorm.md`).
- Green cache and baseline classification for vitest, cargo or parrot-e2e targets
  (follow-up; vitest junit nodes could feed the cache later).
- `parrot-e2e` in the task tier — never; its adapter allows `merge`/`feature` only
  and a contract that says otherwise is a validation error.
- `cargo nextest` / junit for Rust — v1 parses stable libtest text only.
- Resuming a seat's message history for the same-seat repair attempt — the repair is
  a fresh conversation (brainstorm Q2).
- Compound native Bash commands (`&&`, `;`, `$(…)`, `<<`) — the guard keeps its
  conservative allow path for them; the engine gate covers what slips through.
- `HOTFIX-*` brief ids in `ValidationSupervisor` (`_TASK_ID_RE` unchanged, as in FEAT-699).
- A Python entry-point registry for adapters (would assume an installed `parrot`).
- Relaxing the FEAT-563 rule that an agent-issued command never runs a full suite.

---

## 2. Architectural Design

### Overview

The kernel gains a `test_scope/runners/` package. A `RunnerAdapter` (stdlib
`Protocol`) knows how to recognise a normalized argv (after a shared
launcher-stripping step that understands `NAME=value` env prefixes, `uv run`,
`python -m`, `pnpm exec`, `pnpm test`/`pnpm run test`, `npx`), say whether it is
over-broad, map changed source files to its own test files (pytest and vitest only),
build one scoped `Invocation` for a group of targets, and parse that invocation's
report into a normalized `RunReport` (`nodes[(id, status)]`, per-node failure text).
`registry.load_registry(worktree)` returns the four built-ins merged with
`.parrot/test_runners.toml` — per-runner settings (`cwd`, `crate`, `plan`,
`timeout_s`, `tiers`) and optional extension adapters by dotted module path, each
imported under the kernel's own rules, checked against the protocol at load, and
failing closed with the config path when invalid.

`TestContract` becomes schema 2: `runners: tuple[RunnerContract, …]`, each with
`kind`, `targets`, `settings`, `tiers`. `contract_from_index_header` lifts a schema-1
payload into one pytest `RunnerContract`; `contract_to_header` writes schema 2. A
runner kind the registry does not know, a `tiers` entry the adapter forbids, or a
missing `cwd`/`crate`/`plan` is a `ValueError` (admission failure), never a silent
fallback and never an empty green plan.

`plan_tests` keeps its tier semantics (task = declared ∪ file-level mirror; merge /
feature = declared ∪ contract ∪ mirror; fallback mode for pytest unchanged) but every
`TestTarget` carries `runner`, grouping is per `(runner, distribution)`, and each
adapter builds its own argv (the pytest adapter keeps marker composition, `-n auto`
and `--confcutdir`). `green_cache` and `baseline` filter to `runner == "pytest"`
targets; other runners are never cached and their failures are classified `unknown`.

`ValidationSupervisor.start` accepts `tier="task"`: it diffs the attempt branch
against an explicit fork SHA, runs each invocation with its own per-runner timeout
under an overall cap, records node-level evidence per invocation, builds a
`ValidationVerdict` (new `test_scope/verdict.py`), persists it through
`ExecutionEvidenceStore.put_artifact`, and attaches the verdict to the terminal
receipt. The same path serves the merge and feature tiers, so `/sdd-done` gets
`<runner>:<distribution>` rows.

Two seat surfaces return that verdict and nothing else:
- **MCP seats**: `LLMCodeDispatcher.set_validation_runner(capability)` (same
  pattern as `set_event_registry_resolver`) binds a per-attempt capability that
  exposes only the active task; `_tool_schemas` adds a `run_validation` tool;
  `run_command` invocations the guard recognises as a runner are routed to the
  capability instead of being executed, and the tool result carries verdict data
  only. Absent capability ⇒ hard tool error. The configured runners' binaries
  (`pnpm`, `cargo`, `parrot`) are added to `allowed_commands` for the attempt.
- **Native seats**: `worktree_environment._scope_guard` rewrites a lone runner
  command to `python scripts/sdd/select_tests.py --tier task --run --verdict
  --worktree <root>`, whose stdout is the verdict JSON (log to the evidence root).

The engine gate lives in `_consolidate` after `run_lint_pass` and
`check_banned_imports` and before `_acquire_merge_lock`: it starts the task-tier
validation for the attempt worktree with `base_ref` = the fork SHA from
`_consolidate_diff_base`, waits bounded, and on `status != "passed"` returns
`TaskResult(outcome="validation_failed", validation=<verdict>)` without merging.
`_run_task` then re-dispatches the **same seat** once (`attempt + 1`, fresh
sub-worktree created from the failed attempt branch via
`SubWorktreeManager.create(worker_id, base=branch)`, verdict rendered into
`TaskScopedBrief.validation_verdict` / `NativePrep.validation_verdict`), emits one
outcome per attempt, and on a second red falls through to `_select_retry_seat`.
Validation reds are classified apart from model suspension (`_classify_and_suspend`
is not called for them).

### Component Diagram

```
spec §4 "### Validation Contract" (runners: pytest | vitest | cargo | parrot-e2e)
        │ /sdd-task → cache_test_contract.py (schema 2) · check_task_graph.py (registry-backed lint)
        ▼
per-spec index header: test_contract {schema: 2, runners[], digest}  ── schema 1 lifts on read
        │
        ▼
test_scope/runners/registry.py ◄── .parrot/test_runners.toml (settings + extension adapters)
   ├─ pytest.py   (moved helpers: operands / broad / marker composition / junit)
   ├─ vitest.py   (pnpm exec vitest run --reporter=junit)
   ├─ cargo.py    (cargo test -p <crate> … ; libtest text parser)
   └─ parrot_e2e.py (parrot e2e run --plan … ; reads e2e-verdict.json; tiers merge|feature)
        │
plan_tests(contract=…, registry=…)  → ScopePlan{invocations: Invocation(runner, distribution, argv, cwd, report_path, report_format)}
        │                     green_cache / baseline: pytest targets only
        ▼
ValidationSupervisor.start(tier=task|merge|feature, base_ref=<fork SHA>|origin/<base>)
   per-invocation timeout + overall cap → RunReport per invocation → verdict.build_verdict()
   → ExecutionEvidenceStore.put_artifact(verdict) → terminal receipt carries verdict
        │                                   ▲
        │ seat surfaces                     │ engine gate
   ┌────┴───────────────────┐        _consolidate: extract → lint → fidelity → banned imports
   │ MCP: run_validation    │          → TASK-TIER GATE → merge lock
   │   tool / run_command   │        validation_failed → _run_task: same seat, fresh worktree
   │   rewrite → capability │          from failed branch, verdict in brief → ladder on 2nd red
   │ native: Bash rewrite → │
   │   select_tests --verdict│
   └────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `test_scope/datatypes.py` | modifies | `PytestInvocation` → `Invocation`; `TestTarget.runner`; `TestContract` schema 2 + `RunnerContract`; new `RunReport`, `Failure`, `RunnerSummary`, `ValidationVerdict` |
| `test_scope/contract.py` | modifies | launcher normalisation shared; `parse_spec_contract` (both forms), `contract_from_index_header` (lift), `contract_to_header` (v2); pytest-only helpers move to `runners/pytest.py` and are re-exported |
| `test_scope/runners/` | new | protocol, registry + TOML loader, four adapters |
| `test_scope/select.py`, `planner.py`, `mirror.py` | modifies | per-`(runner, distribution)` grouping; adapters build argv; mirror per adapter |
| `test_scope/report.py` | modifies | `parse_junit` accepts non-`.py` `file` attrs and retains failure text; `RunReport` normalisation; `suite_name` → `<runner>:<distribution>[…]` |
| `test_scope/green_cache.py`, `baseline.py` | modifies | pytest-only filters (S5) |
| `test_scope/guard.py` | modifies | registry-based recognition; `GuardOutcome.action="verdict"` carrying the verdict argv |
| `test_scope/verdict.py` | new | `build_verdict`, excerpt bounding (`EXCERPT_MAX_LINES = 30`), JSON codec |
| `sdd_coder/background.py` | modifies | `tier="task"`, per-invocation timeouts, verdict on receipt, `put_artifact` |
| `sdd_coder/engine.py` | modifies | gate in `_consolidate`; same-seat repair in `_run_task`; capability binding in `_run_attempt`; `run_validation(tier="task")` |
| `sdd_coder/toolkit.py`, `sdd_coder/models.py` | modifies | `coder_run_validation(tier="task")`; `TaskOutcome` + `validation_failed`; `ValidationVerdictModel`; `RunnerConfig` on `RosterConfig` |
| `models/base.py` (`TaskScopedBrief`), `sdd_coder/models.py` (`NativePrep`) | modifies | `validation_verdict: str` rendered block |
| `worktree_manager.py` | modifies | `SubWorktreeManager.create(worker_id, *, base=None)` |
| `dispatchers/llm.py`, `models/llm.py` | modifies | `run_validation` tool, `set_validation_runner`, runner-aware `run_command` routing, `allowed_commands` extension |
| `worktree_environment.py` | modifies | `_scope_guard` rewrite to the verdict command; runner binaries on the sandbox PATH |
| `scripts/sdd/select_tests.py` | modifies | `--verdict` mode; per-runner execution; records through `report` |
| `scripts/sdd/cache_test_contract.py`, `check_task_graph.py` | modifies | schema 2 write; registry-backed lint incl. extension adapters under isolated Python |
| `sdd/templates/spec.md`, `/sdd-spec`, `/sdd-task`, `/sdd-done` docs | modifies | authoring format; closeout rows per runner |
| `.claude/agents/sdd-coder.md` + `_subagent_data/sdd-coder.md`, `sdd-worker.md`, `qa-runner.md` | modifies | tool usage, gate semantics |
| `.parrot/test_runners.toml` | new | this repo's runner config (pytest defaults, vitest cwd `packages/ai-parrot-server/ui`) |
| `.github/workflows/nightly-tests.yml` (FEAT-699) | extends | adds the UI vitest suite to the matrix |

### Data Models

```python
# test_scope/datatypes.py — stdlib dataclasses only (kernel constraint)

@dataclass(frozen=True)
class TestTarget:
    path: str
    distribution: str
    reason: str                 # "declared" | "contract" | "mirror" | "import" | "core" | "escalated"
    runner: str = "pytest"      # NEW — adapter kind

@dataclass(frozen=True)
class Invocation:               # replaces PytestInvocation (hard cut; every caller updated in-feature)
    runner: str
    distribution: str           # group key chosen by the adapter ("ai-parrot", "root", "admin-ui", "<crate>", "<plan>")
    argv: tuple[str, ...]
    targets: tuple[TestTarget, ...]
    cwd: str = "."              # repo-relative
    report_path: str = ""       # repo-relative file the runner writes; "" when stdout-parsed
    report_format: str = "junit"  # "junit" | "libtest" | "e2e-verdict" | "exit-code"
    timeout_s: int = 0          # 0 ⇒ runner default from settings

@dataclass(frozen=True)
class RunnerContract:
    kind: str
    targets: tuple[str, ...]    # adapter-specific operands (pytest/vitest paths or path::node; cargo filters; e2e: ())
    settings: Mapping[str, str] # "cwd", "crate", "plan", "markers" (comma-joined), "timeout_s" …
    tiers: tuple[str, ...]      # subset of TIERS the adapter allows

@dataclass(frozen=True)
class TestContract:
    schema: int                 # 2 (1 is lifted on read)
    runners: tuple[RunnerContract, ...]
    digest: str
    @property
    def pytest(self) -> RunnerContract | None: ...   # convenience for planner/green_cache

@dataclass(frozen=True)
class RunReport:
    runner: str
    suite: str
    tests: int; passed: int; failed: int; errors: int; skipped: int
    duration_s: float
    exit_code: int
    status: str                 # "passed" | "failed" | "timed_out" | "no_report" | "unavailable"
    nodes: tuple[tuple[str, str], ...]          # (nodeid, status)
    failure_text: Mapping[str, str]             # nodeid -> raw failure text (bounded later)
    unmapped: int = 0

@dataclass(frozen=True)
class Failure:
    runner: str
    nodeid: str
    verdict: str                # "new_red" | "baseline_red" | "unknown"
    excerpt: str                # ≤ EXCERPT_MAX_LINES lines

@dataclass(frozen=True)
class RunnerSummary:
    runner: str; suite: str
    tests: int; passed: int; failed: int; errors: int; skipped: int; cached: int
    duration_s: float; exit_code: int; status: str

@dataclass(frozen=True)
class ValidationVerdict:
    schema: int                 # 1
    status: str                 # "passed" | "failed" | "timed_out" | "unavailable" | "blocked"
    tier: str
    runners: tuple[RunnerSummary, ...]
    failures: tuple[Failure, ...]
    cached: tuple[str, ...]
    notes: tuple[str, ...]
    evidence: tuple[str, ...]   # repo-relative report paths + the EvidenceRef id when persisted
```

Index header payload (schema 2):
```json
"test_contract": {
  "schema": 2,
  "runners": [
    {"kind": "pytest", "targets": ["packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py"], "settings": {"markers": ""}, "tiers": ["task", "merge", "feature"]},
    {"kind": "vitest", "targets": ["src/lib/components/FormRenderer.test.ts"], "settings": {"cwd": "packages/ai-parrot-server/ui"}, "tiers": ["task", "merge", "feature"]},
    {"kind": "cargo", "targets": [], "settings": {"crate": "rust/<crate>"}, "tiers": ["task", "merge", "feature"]},
    {"kind": "parrot-e2e", "targets": [], "settings": {"plan": "sdd/state/FEAT-<NNN>/e2e-plan.md"}, "tiers": ["merge", "feature"]}
  ],
  "digest": "sha256:…"
}
```

`.parrot/test_runners.toml` (optional; absent ⇒ built-ins with defaults):
```toml
[runners.pytest]
timeout_s = 60
[runners.vitest]
cwd = "packages/ai-parrot-server/ui"
timeout_s = 120
[runners.cargo]
timeout_s = 300
[runners.parrot-e2e]
tiers = ["merge", "feature"]
[extensions]
# kind = "dotted.module:AdapterClass"  — imported under the kernel's stdlib-only rules, protocol-checked at load
```

Pydantic mirror (boundary only): `sdd_coder/models.py` `ValidationVerdictModel`,
`FailureModel`, `RunnerSummaryModel` with `from_kernel(verdict)`; `RunnerConfig`
(`gate_overall_timeout_s: int = 600`, `same_seat_repair: bool = True`) on `RosterConfig`.

### New Public Interfaces

See the Interface Skeletons in §3 — `RunnerAdapter`, `load_registry`,
`normalize_launcher_argv`, `plan_tests(registry=…)`, `build_verdict`,
`ValidationSupervisor.start(tier="task", …)`, `LLMCodeDispatcher.set_validation_runner`,
`SubWorktreeManager.create(base=…)`, `coder_run_validation(tier="task")`,
`select_tests.py --verdict`.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Runner protocol, registry, TOML | yes | protocol + registry signatures fixed below; fail-closed rules enumerated (S12) | |
| M2: Kernel datatypes + contract schema 2 | yes | dataclasses fixed in §2; lift rule and tier validation (S11) enumerated | |
| M3: Pytest adapter + runner-agnostic planner/select/guard | no | — | refactor interplay of tiers/modes/marker composition across five modules |
| M4: vitest / cargo / parrot-e2e adapters + report parsers | yes | argv forms, report formats and fixtures fixed (S3, S10) | |
| M5: Verdict builder + CLI `--verdict` | yes | dataclasses + JSON codec + excerpt rule fixed | |
| M6: Supervisor task tier | no | — | deadline split (S9), evidence persistence (S1), base-ref semantics |
| M7: Engine gate + same-seat repair + models | no | — | state machine in `_run_task` (S8), attempt accounting, gate placement (S2) |
| M8: Seat surfaces (dispatcher tool, run_command routing, native rewrite) | no | — | capability binding and command-boundary decisions (S4, S7) |
| M9: Authoring, caching, lint | yes | template subsection, schema-2 writer, registry-backed lint rules enumerated (S6) | |
| M10: Docs and prompts | yes | wording driven by M5–M8 semantics | |
| M11: Repo config + nightly matrix | yes | TOML content and workflow matrix entry fixed | |

### Module 1: Runner protocol, registry and TOML loader
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/__init__.py`,
  `.../runners/base.py`, `.../runners/registry.py`
- **Responsibility**: the `RunnerAdapter` protocol; the shared launcher normalisation
  (S3); `load_registry(worktree)` = built-ins ∪ `.parrot/test_runners.toml`
  (`tomllib`, stdlib); extension adapters imported by dotted path, protocol-checked at
  load, failing closed with the config path and error (S12); per-runner settings and
  default tiers.
- **Depends on**: M2 (`Invocation`, `RunReport`, `TestTarget`).
- **Interface Skeleton**:
  ```python
  # test_scope/runners/base.py  (new)
  EXCERPT_MAX_LINES: int = 30
  LAUNCHER_PREFIXES: tuple[tuple[str, ...], ...]   # ("uv","run"), ("python","-m"), ("python3","-m"), ("pnpm","exec"), ("pnpm","run"), ("npx",)

  def normalize_launcher_argv(argv: Sequence[str]) -> list[str]:
      """Strip `NAME=value` env tokens and known launcher chains; `pnpm test` ⇒ `vitest run`;
      returns the runner-headed argv. Unknown/ambiguous chains are returned unchanged."""

  class RunnerAdapter(Protocol):
      kind: str
      binaries: tuple[str, ...]           # executables the sandbox/allow-list must permit
      default_tiers: frozenset[str]       # ⊆ TIERS
      report_format: str
      def matches(self, argv: Sequence[str]) -> bool: ...
      def operands(self, argv: Sequence[str]) -> list[str] | None: ...
      def is_broad(self, argv: Sequence[str], *, worktree: Path | None) -> bool: ...
      def mirror_targets(self, changed: Sequence[str], *, worktree: Path, settings: Mapping[str, str]) -> list[str]: ...
      def distribution_of(self, target: str, *, settings: Mapping[str, str]) -> str: ...
      def invocation(self, targets: Sequence[TestTarget], *, distribution: str, worktree: Path,
                     settings: Mapping[str, str], policy: ScopePolicy, report_path: str) -> Invocation: ...
      def parse_report(self, *, report_path: Path | None, exit_code: int, stdout: str, stderr: str,
                       duration_s: float, timed_out: bool, suite: str) -> RunReport: ...
      def validate_settings(self, settings: Mapping[str, str], *, worktree: Path) -> list[str]:
          """Diagnostics (empty = ok): missing cwd/crate/plan, unknown keys."""

  # test_scope/runners/registry.py  (new)
  CONFIG_PATH: str = ".parrot/test_runners.toml"
  class RunnerRegistry:
      def __init__(self, adapters: Mapping[str, RunnerAdapter], settings: Mapping[str, Mapping[str, str]]) -> None: ...
      def adapter_for_kind(self, kind: str) -> RunnerAdapter:
          """Raises KeyError with the known kinds listed."""
      def adapter_for_argv(self, argv: Sequence[str]) -> RunnerAdapter | None:
          """Normalises the launcher chain then asks each adapter; None when no adapter matches."""
      def settings_for(self, kind: str) -> Mapping[str, str]: ...
      def tiers_for(self, kind: str) -> frozenset[str]: ...
      def timeout_for(self, kind: str) -> int: ...
      @property
      def binaries(self) -> tuple[str, ...]: ...
  def load_registry(worktree: Path) -> RunnerRegistry:
      """Built-ins ∪ TOML. Raises ValueError naming CONFIG_PATH on a malformed file, an unknown
      section, or an extension that fails import/protocol check (fail closed; never pytest-only fallback)."""
  ```

### Module 2: Kernel datatypes and contract schema 2
- **Path**: `.../test_scope/datatypes.py`, `.../test_scope/contract.py`, `.../test_scope/__init__.py`
- **Responsibility**: the dataclasses in §2 Data Models; `parse_spec_contract` for the
  flat form (lifted) and the `runners:` form; `contract_from_index_header` lifting
  schema 1 → 2 and validating kinds/tiers/settings against the registry (S11);
  `contract_to_header` writing schema 2; `contract_digest` over the normalised v2 payload.
- **Depends on**: M1 (registry for validation).
- **Interface Skeleton**:
  ```python
  # test_scope/contract.py  (modifies; anchors: TEST_CONTRACT_SCHEMA contract.py:24, parse_spec_contract :227,
  #                          contract_from_index_header :291, contract_to_header :316)
  TEST_CONTRACT_SCHEMA: int = 2
  def parse_spec_contract(spec_md: str, *, registry: RunnerRegistry | None = None) -> TestContract | None:
      """Flat `tests:`/`markers:` form ⇒ one pytest runner; `runners:` form ⇒ N runners.
      `none — fallback` ⇒ None. Raises ValueError on unknown kind, forbidden tier, malformed block."""
  def contract_from_index_header(header: Mapping[str, object], *, registry: RunnerRegistry | None = None) -> TestContract | None:
      """schema 1 ⇒ lifted to one pytest RunnerContract (digest recomputed, header left untouched);
      schema 2 ⇒ validated. Unknown schema/shape/kind/tier ⇒ ValueError (admission failure)."""
  def contract_to_header(contract: TestContract) -> dict[str, object]:
      """Always writes schema 2."""
  def lift_schema1(payload: Mapping[str, object]) -> TestContract: ...
  ```

### Module 3: Pytest adapter and runner-agnostic planner / select / mirror / guard
- **Path**: `.../test_scope/runners/pytest.py` (new), `.../test_scope/select.py`,
  `.../test_scope/planner.py`, `.../test_scope/mirror.py`, `.../test_scope/guard.py`,
  `.../test_scope/green_cache.py`, `.../test_scope/baseline.py`
- **Responsibility**: move `_pytest_operands`, `is_broad_pytest`, marker composition,
  `-n auto`, `--confcutdir`, junit argv into the pytest adapter (re-exported from
  `contract.py` for existing callers); `plan_tests(registry=…)` grouping per
  `(runner, distribution)`; mirror via `adapter.mirror_targets`; guard recognises any
  registered runner and emits `GuardOutcome(action="verdict", argvs=(<verdict argv>,))`
  for a lone broad runner command inside an attempt; `filter_cached`/`record_green`/
  `classify_failures` restricted to `runner == "pytest"` (S5).
- **Depends on**: M1, M2.
- **Interface Skeleton**:
  ```python
  # test_scope/select.py  (modifies plan_tests, verified: select.py:123)
  def plan_tests(*, worktree: Path, changed_files: Sequence[str], tier: str,
                 declared: Sequence[Sequence[str]] = (), contract: TestContract | None = None,
                 policy: ScopePolicy | None = None, registry: RunnerRegistry | None = None) -> ScopePlan:
      """registry=None ⇒ load_registry(worktree). A runner whose tiers exclude `tier` is skipped
      with a note ("<kind>: not eligible for tier <tier>") — never an error here; the error lives in
      contract validation (M2)."""

  # test_scope/planner.py  (modifies build_plan, verified: planner.py:59; _invocation :32 becomes pytest-adapter code)
  def build_plan(targets, *, tier, worktree, policy, registry: RunnerRegistry, contract=None, mode="fallback", **kw) -> ScopePlan:
      """Groups by (runner, distribution); each adapter builds its Invocation with its report_path."""

  # test_scope/guard.py  (modifies; verified: _is_pytest_argv guard.py:32, guard_argv :60, guard_bash :102)
  VERDICT_ARGV: tuple[str, ...] = ("python", "scripts/sdd/select_tests.py", "--tier", "task", "--run", "--verdict")
  def guard_argv(argv, *, worktree: Path, registry: RunnerRegistry | None = None) -> GuardOutcome:
      """allow | block (no scoped targets) | verdict (lone broad runner command inside an attempt ⇒
      argvs=(VERDICT_ARGV + ("--worktree", str(worktree)),)). `rewrite` is retired."""
  def guard_bash(command: str, *, worktree: Path) -> tuple[GuardOutcome, str | None]:
      """Lone runner command ⇒ ("verdict", "<cd root &&> python scripts/sdd/select_tests.py …");
      compounds outside the subset ⇒ allow (unchanged, brainstorm Q6)."""

  # test_scope/green_cache.py (modifies filter_cached :156, record_green :223) / baseline.py (classify_failures :156)
  #   every entry point filters `target.runner == "pytest"` / nodeid belongs to a pytest invocation; others pass through untouched.
  ```

### Module 4: vitest, cargo and parrot-e2e adapters; report parser spine
- **Path**: `.../test_scope/runners/vitest.py`, `.../runners/cargo.py`,
  `.../runners/parrot_e2e.py` (new), `.../test_scope/report.py`
- **Responsibility**: three adapters; `parse_junit` accepts non-`.py` `file`
  attributes (vitest writes `.ts`/`.svelte.ts`) and retains `<failure>`/`<error>` text
  per node (S10); libtest text parser (`test <name> ... ok|FAILED|ignored`, `failures:`
  section for excerpts); `e2e-verdict.json` reader (`results[*]`, `counts`,
  `exit_code`) without importing `parrot.e2e`; fixtures land before the spine changes.
- **Depends on**: M1, M2.
- **Interface Skeleton**:
  ```python
  # test_scope/runners/vitest.py  (new)
  class VitestAdapter:
      kind = "vitest"; binaries = ("pnpm", "vitest"); default_tiers = frozenset(TIERS); report_format = "junit"
      # matches: normalized argv[0] == "vitest" (after `pnpm exec`/`npx`/`pnpm test` normalisation)
      # invocation: ("pnpm", "exec", "vitest", "run", "--reporter=junit", f"--outputFile={report_path}", *targets), cwd=settings["cwd"]
      # is_broad: `vitest run` with no file operand
      # mirror_targets: foo.ts/foo.svelte ⇒ existing foo.test.ts / foo.spec.ts beside it (file-level only)

  # test_scope/runners/cargo.py  (new)
  class CargoAdapter:
      kind = "cargo"; binaries = ("cargo",); default_tiers = frozenset(TIERS); report_format = "libtest"
      # invocation: ("cargo", "test", "-p", settings["crate"], *targets, "--", "--test-threads=1"), cwd="."; stdout-parsed
      # is_broad: never (a crate is the unit; brainstorm Q5: stable libtest text only)
  def parse_libtest(stdout: str, *, exit_code: int, suite: str, duration_s: float, timed_out: bool) -> RunReport: ...

  # test_scope/runners/parrot_e2e.py  (new)
  class ParrotE2EAdapter:
      kind = "parrot-e2e"; binaries = ("parrot",); default_tiers = frozenset({"merge", "feature"}); report_format = "e2e-verdict"
      # invocation: ("parrot", "e2e", "run", "--plan", settings["plan"], "--owner-id", f"sdd-coder:{feature_id}"); report_path = evidence dir's e2e-verdict.json
      # validate_settings: plan file exists; tiers ⊄ {merge, feature} ⇒ diagnostic
  def parse_e2e_verdict(path: Path, *, exit_code: int, suite: str, duration_s: float, timed_out: bool) -> RunReport: ...

  # test_scope/report.py  (modifies; verified: nodeid_from_testcase report.py:111, parse_junit :146, suite_name :127, with_junit :106)
  def nodeid_from_testcase(file_attr: str | None, classname: str, name: str, *, runner: str = "pytest") -> str | None:
      """pytest: unchanged rule; other runners: `<file>::<name>` for any file attribute."""
  def parse_junit(junit_path: Path, *, suite: str, argv: tuple[str, ...], exit_code: int, duration_s: float,
                  timed_out: bool = False, runner: str = "pytest") -> RunReport:
      """Retains per-node failure text in `failure_text`."""
  def suite_name(invocation: Invocation) -> str:
      """`<runner>:<distribution>` (+ `[contract]`/`[markers]` for pytest as today)."""
  def with_report(invocation: Invocation, report_path: Path) -> tuple[str, ...]:
      """Adapter-specific report argv (pytest: `-o junit_family=xunit1 --junitxml=…`); replaces with_junit."""
  ```

### Module 5: Verdict builder and CLI `--verdict`
- **Path**: `.../test_scope/verdict.py` (new), `scripts/sdd/select_tests.py`
- **Responsibility**: `build_verdict` from `RunReport`s + baseline verdicts + cached
  targets; excerpt = last `EXCERPT_MAX_LINES` lines of the node's failure text;
  `to_json`/`from_json`; CLI `--verdict` prints only the verdict JSON (plan and logs go
  to a file under the evidence root), exit 0 passed / 1 failed / 2 usage|blocked.
- **Depends on**: M2, M4.
- **Interface Skeleton**:
  ```python
  # test_scope/verdict.py  (new)
  def build_verdict(*, tier: str, reports: Sequence[RunReport], baseline: Sequence[BaselineVerdict] = (),
                    cached: Sequence[str] = (), notes: Sequence[str] = (), evidence: Sequence[str] = ()) -> ValidationVerdict:
      """status: any timed_out ⇒ "timed_out"; any unavailable ⇒ "failed"; failures ⇒ "failed" unless every
      failure is baseline_red; else "passed". Non-pytest failures are `unknown`."""
  def excerpt_of(text: str, *, max_lines: int = EXCERPT_MAX_LINES) -> str: ...
  def verdict_to_json(verdict: ValidationVerdict) -> dict[str, object]: ...
  def verdict_from_json(payload: Mapping[str, object]) -> ValidationVerdict: ...
  def render_for_prompt(verdict: ValidationVerdict) -> str:
      """Deterministic markdown block (`## Validation verdict`) for TaskScopedBrief/NativePrep."""

  # scripts/sdd/select_tests.py  (modifies; anchors: `--json` add_argument select_tests.py:48, `if args.json:` :165)
  #   --verdict : implies --run; stdout = verdict JSON only; --log-dir <path> (default artifacts/logs/validation/)
  ```

### Module 6: Supervisor task tier
- **Path**: `.../sdd_coder/background.py`
- **Responsibility**: `start(tier="task", …)` with `base_ref` = fork SHA and
  `task_ids=[one]`; per-invocation timeout from `registry.timeout_for(kind)` under
  `timeout_seconds` as the overall cap (S9); run every invocation via the adapter's
  `cwd`/report path; `RunReport` per invocation; `build_verdict`; persist with
  `ExecutionEvidenceStore.put_artifact` (S1); verdict on the terminal receipt;
  `record_green` only when the run completed and only for pytest reports; `backend`
  label `"validation-subprocess"`.
- **Depends on**: M1–M5.
- **Interface Skeleton**:
  ```python
  # sdd_coder/background.py  (modifies; verified: start background.py:493, tier check :505, _plan_selection :753,
  #                            _record_test_results :1034, _argv_with_junit :1021, backend="pytest-subprocess" :~575)
  class ValidationSupervisor:
      async def start(self, *, feature, worktree: Path, execution_id, task_ids: list[str],
                      tier: Literal["task", "merge", "feature"], timeout_seconds: int, request_id: str,
                      base_ref: Optional[str] = None, index_path: Optional[Path] = None,
                      attempt_uid: Optional[str] = None) -> BackgroundRegistration:
          """tier="task" requires exactly one task id and an explicit base_ref (fork SHA); it plans
          declared ∪ mirror only (no contract), never touches the green cache, and records under
          `attempt_uid`."""
      async def wait_verdict(self, execution_id: str, handle: str, timeout_s: float) -> ValidationVerdict:
          """Blocks until the handle settles; returns the persisted verdict (status "timed_out" on deadline)."""
      async def _plan_selection(self, *, worktree, tier, base_ref=None, index_path=None, task_ids=(), feature_id="",
                                registry: RunnerRegistry | None = None) -> ScopePlan: ...
      async def _run_invocation(self, invocation: Invocation, *, worktree: Path, timeout_s: int, report_path: Path) -> RunReport: ...
  ```

### Module 7: Engine gate, same-seat repair and models
- **Path**: `.../sdd_coder/engine.py`, `.../sdd_coder/models.py`, `.../sdd_coder/toolkit.py`,
  `.../models/base.py`, `.../worktree_manager.py`
- **Responsibility**: gate in `_consolidate` (S2 placement); `validation_failed`
  outcome; `TaskResult.validation`; `AttemptRecord.validation_status`; same-seat
  repair in `_run_task` (S8) with `SubWorktreeManager.create(worker_id, base=branch)`;
  `TaskScopedBrief.validation_verdict` / `NativePrep.validation_verdict`;
  `coder_run_validation(tier="task")`; `RunnerConfig` on `RosterConfig`; the
  per-attempt validation capability handed to the dispatcher (M8).
- **Depends on**: M5, M6.
- **Interface Skeleton**:
  ```python
  # sdd_coder/models.py  (modifies; verified: TaskOutcome models.py:30, TaskResult :359, NativePrep :376, RosterConfig :219)
  TaskOutcome = Literal["queued", "running", "merged", "merge_conflict", "failed", "fidelity_violation",
                        "retry_native", "not_dispatched", "validation_failed"]
  class ValidationVerdictModel(BaseModel):
      schema: int; status: str; tier: str; runners: List[RunnerSummaryModel]; failures: List[FailureModel]
      cached: List[str]; notes: List[str]; evidence: List[str]
      @classmethod
      def from_kernel(cls, verdict: "ValidationVerdict") -> "ValidationVerdictModel": ...
  class RunnerConfig(BaseModel):
      gate_overall_timeout_s: int = 600
      same_seat_repair: bool = True
  class RosterConfig(BaseModel):
      runners: RunnerConfig = Field(default_factory=RunnerConfig)   # beside lint (:225) / feedback (:226)
  class TaskResult(BaseModel):
      validation: Optional[ValidationVerdictModel] = None
  class NativePrep(BaseModel):
      validation_verdict: str = ""        # render_for_prompt() output

  # models/base.py  (modifies TaskScopedBrief, verified: base.py:478)
  class TaskScopedBrief(BaseModel):
      validation_verdict: str = Field(default="", description="Rendered verdict of the previous same-seat attempt, if any.")

  # worktree_manager.py  (modifies create, verified: worktree_manager.py:143; `git worktree add -b branch path self.feature_branch` :165)
  class SubWorktreeManager:
      async def create(self, worker_id: str, *, base: Optional[str] = None) -> str:
          """base=None ⇒ feature branch (today); base=<attempt branch> ⇒ repair worktree seeded from it."""

  # sdd_coder/engine.py  (modifies; verified: run_validation engine.py:1149, _consolidate :2640,
  #                       check_banned_imports call :~2731, _acquire_merge_lock :~2740, _run_task :3642, _run_attempt :3090)
  async def run_validation(self, feature, worktree, execution_id, task_ids, tier: Literal["task", "merge", "feature"],
                           timeout_seconds, request_id, *, attempt_uid: Optional[str] = None, base_ref: Optional[str] = None) -> BackgroundRegistration: ...
  async def _task_tier_gate(self, ctx: _FeatureCtx, task: PlannedTask, *, path: str, branch: str, diff_base: str,
                            attempt_uid: str, execution_id: Optional[str]) -> ValidationVerdict:
      """Runs after lint autofix + banned-import gate, before the merge lock; base_ref = diff_base."""
  def _validation_capability(self, ctx: _FeatureCtx, task: PlannedTask, *, path: str, attempt_uid: str,
                             execution_id: Optional[str]) -> "ValidationCapability":
      """Bound to ONE task + attempt worktree; handed to the dispatcher via set_validation_runner (M8)."""
  async def _run_attempt(self, ctx, task, seat, *, attempt, job_id, execution_id=None, pool=None,
                         repair_from: Optional[str] = None, verdict: Optional[ValidationVerdict] = None) -> Tuple[...]:
      """repair_from = failed attempt branch ⇒ manager.create(..., base=repair_from); verdict rendered into the brief."""
  # _run_task: consolidate ⇒ validation_failed ∧ roster.runners.same_seat_repair ∧ not yet repaired
  #            ⇒ emit outcome for the red attempt, _run_attempt(same seat, attempt+1, repair_from=branch, verdict=…)
  #            ⇒ consolidate again ⇒ second validation_failed ⇒ treated as `err` for the existing ladder
  #            (never _classify_and_suspend for validation reds).

  # sdd_coder/toolkit.py  (modifies coder_run_validation, verified: toolkit.py:602; tier Literal :608)
  async def coder_run_validation(self, feature, worktree, execution_id, task_ids: List[str],
                                 tier: Literal["task", "merge", "feature"], timeout_seconds: int, request_id: str,
                                 attempt_uid: Optional[str] = None) -> CoderResult: ...
  ```

### Module 8: Seat surfaces — dispatcher tool, run_command routing, native rewrite
- **Path**: `.../dispatchers/llm.py`, `.../models/llm.py`, `.../worktree_environment.py`
- **Responsibility**: `ValidationCapability` protocol + `set_validation_runner`
  (S7); `run_validation` function tool; `run_command` whose argv the registry
  recognises as a runner ⇒ capability call, result = verdict data only (S4); runner
  binaries appended to `allowed_commands` for the attempt profile; native
  `_scope_guard` rewrite to the verdict command (brainstorm Q6: lone commands only);
  sandbox PATH includes the runner binaries' directories.
- **Depends on**: M3 (guard), M5 (verdict JSON), M7 (capability).
- **Interface Skeleton**:
  ```python
  # dispatchers/llm.py  (modifies; verified: set_event_registry_resolver llm.py:99, _tool_schemas :1301,
  #                      "run_command" schema :1423, _run_tool routing :1495, _tool_run_command :1894, _run_guarded_invocations :2135)
  class ValidationCapability(Protocol):
      task_id: str
      async def run(self, *, targets: Sequence[str] = ()) -> Dict[str, Any]:
          """Runs the task-tier plan (optionally narrowed to `targets` ⊆ the plan) and returns verdict JSON."""
  class LLMCodeDispatcher:
      def set_validation_runner(self, capability: Optional[ValidationCapability]) -> None: ...
      async def _tool_run_validation(self, cwd: str, args: Dict[str, Any], profile: LLMCodeDispatchProfile) -> Dict[str, Any]:
          """{"ok": bool, "verdict": {...}} — hard error {"ok": False, "error": "validation capability not bound"} when unset."""
      # _tool_run_command: registry.adapter_for_argv(argv) is not None ⇒ route to the capability (verdict only);
      #                    _run_guarded_invocations retired (its stdout/stderr merge is the leak being closed).

  # models/llm.py  (modifies allowed_commands default, verified: models/llm.py:51)
  #   default gains "pnpm", "cargo", "parrot" only when the registry declares them (engine extends the profile per attempt).

  # worktree_environment.py  (modifies; verified: _is_lone_pytest :313, _scope_guard :325, hook caller :445)
  def _is_lone_runner_command(command: str, *, registry: RunnerRegistry) -> bool: ...
  def _scope_guard(command: str, cwd: Path) -> tuple[str, str | None]:
      """("verdict", "cd <root> && python scripts/sdd/select_tests.py --tier task --run --verdict --worktree <root>") for a lone
      broad runner command inside an attempt; ("block", msg) when nothing is scoped; ("allow", None) otherwise."""
  ```

### Module 9: Authoring surface, contract caching and lint
- **Path**: `sdd/templates/spec.md`, `scripts/sdd/cache_test_contract.py`,
  `scripts/sdd/check_task_graph.py`, `.claude/commands/sdd-spec.md`,
  `.claude/commands/sdd-task.md` (+ `.agent/workflows/` and `.agents/skills/` twins)
- **Responsibility**: template `### Validation Contract` documents both forms;
  `cache_test_contract.py` writes schema 2 through `contract_to_header`;
  `check_task_graph._check_test_contract` consumes `load_registry` +
  `contract_from_index_header` (S6): unknown kind, forbidden tier, missing
  cwd/crate/plan, extension adapter failing under isolated system Python (S12),
  `real_llm` operand, task command not recognised by any adapter (warning).
- **Depends on**: M1, M2.
- **Interface Skeleton**:
  ```python
  # scripts/sdd/check_task_graph.py  (modifies; verified: _check_test_contract check_task_graph.py:309)
  def _check_test_contract(data: dict, root: Path, tasks: dict[str, _Task]) -> list[Finding]:
      """codes: test-contract-malformed, test-contract-unknown-runner, test-contract-tier-forbidden,
      test-contract-settings-invalid, test-contract-extension-invalid, test-contract-real-llm,
      test-contract-operand-missing, test-contract-task-tests-uncovered, validation-command-unrecognised (warning)."""
  # scripts/sdd/cache_test_contract.py  (modifies; verified: contract_to_header call cache_test_contract.py:70)
  ```

### Module 10: Command and agent documentation
- **Path**: `.claude/agents/sdd-coder.md`, `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md`
  (twins — both change; `.claude/` needs `git add -f`), `.claude/agents/sdd-worker.md`,
  `.claude/agents/qa-runner.md`, `.claude/commands/sdd-done.md`, `docs/dev_loop/`
- **Responsibility**: seats use `run_validation`; Bash runner commands return a
  verdict; gate semantics and same-seat repair; `/sdd-done` table rows per
  `<runner>:<distribution>` with `n/a` cache/baseline cells for non-pytest.
- **Depends on**: M5–M8 semantics frozen.

### Module 11: Repository runner config and nightly matrix
- **Path**: `.parrot/test_runners.toml` (new), `.github/workflows/nightly-tests.yml`
- **Responsibility**: this repo's config (pytest 60 s, vitest cwd
  `packages/ai-parrot-server/ui` 120 s, parrot-e2e merge/feature); nightly matrix
  gains the UI vitest suite (`pnpm install --frozen-lockfile && pnpm exec vitest run
  --reporter=junit`).
- **Depends on**: M1 (TOML schema), M4 (vitest adapter).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_normalize_launcher_argv` | M1 | env prefix, `uv run`, `python -m`, `pnpm exec`, `pnpm test`, `npx`; ambiguous chain unchanged |
| `test_registry_builtins_and_toml` | M1 | built-ins present; TOML settings/timeouts/tiers override; malformed TOML ⇒ `ValueError` naming the path |
| `test_registry_extension_fail_closed` | M1 | missing module / wrong protocol ⇒ `ValueError`; never pytest-only fallback |
| `test_contract_schema2_roundtrip` | M2 | `runners:` form ⇒ `TestContract` ⇒ header ⇒ back; digest stable |
| `test_contract_schema1_lift` | M2 | FEAT-699 payload lifts to one pytest runner; header not rewritten |
| `test_contract_tier_forbidden` | M2 | `parrot-e2e` with `task` ⇒ `ValueError` (S11) |
| `test_plan_groups_per_runner` | M3 | mixed targets ⇒ one `Invocation` per `(runner, distribution)`; pytest argv unchanged vs FEAT-699 |
| `test_guard_verdict_action` | M3 | lone broad `pytest`/`vitest run` inside an attempt ⇒ `action="verdict"`; compounds ⇒ allow |
| `test_green_cache_pytest_only` | M3 | vitest/cargo targets never dropped nor recorded (S5) |
| `test_baseline_pytest_only` | M3 | non-pytest failed nodes ⇒ `unknown` without a checkout |
| `test_parse_junit_vitest_fixture` | M4 | TS `file` attrs, nested suites, missing `file` (unmapped stays red), failure text retained (S10) |
| `test_parse_libtest_fixture` | M4 | ok/FAILED/ignored lines, `failures:` excerpts, non-zero exit without lines ⇒ `unavailable` |
| `test_parse_e2e_verdict_fixture` | M4 | `results`/`counts` mapping; missing file ⇒ `no_report` red |
| `test_build_verdict_status_rules` | M5 | timed_out > failed > passed; baseline-red-only passes; excerpt bounded to 30 lines |
| `test_select_tests_verdict_mode` | M5 | stdout is verdict JSON only; exit codes 0/1/2 |
| `test_supervisor_task_tier` | M6 | `tier="task"` admission (one id, explicit base_ref), per-invocation timeouts, partial run ⇒ `timed_out`, no green cache (S9) |
| `test_supervisor_verdict_persisted` | M6 | `put_artifact` called before the receipt; `wait_verdict` returns the stored verdict (S1) |
| `test_consolidate_gate_placement` | M7 | gate runs after lint autofix and before the merge lock; red ⇒ `validation_failed`, no merge (S2) |
| `test_run_task_same_seat_repair` | M7 | red ⇒ same seat, `attempt=2`, worktree from failed branch, verdict in brief; second red ⇒ ladder; no suspension (S8) |
| `test_worktree_manager_create_base` | M7 | `create(base=<branch>)` forks from it |
| `test_dispatcher_run_validation_tool` | M8 | tool present; unbound capability ⇒ hard error; `run_command pytest …` ⇒ capability, verdict only (S4, S7) |
| `test_native_scope_guard_verdict` | M8 | lone `pytest`/`vitest` ⇒ rewrite to the verdict command with `cd <root>`; `python` invoked (no shebang) |
| `test_check_test_contract_runners` | M9 | unknown kind, forbidden tier, missing cwd/crate/plan, extension invalid, unrecognised task command |
| `test_cache_test_contract_schema2` | M9 | writes schema 2 for both authoring forms |

### Integration Tests
| Test | Description |
|---|---|
| `test_task_tier_end_to_end_pytest` | hermetic feature worktree: attempt branch with a failing test ⇒ gate red ⇒ repair attempt ⇒ green ⇒ merged; `TaskResult.attempts` has two records with one outcome each |
| `test_merge_tier_includes_vitest_runner` | contract with a vitest runner block ⇒ merge plan carries a `vitest:admin-ui` invocation; `/sdd-done` table renders the row with `n/a` cache/baseline |
| `test_legacy_schema1_index_unchanged` | FEAT-699-style index keeps planning identically (lift on read), no rewrite |
| `test_stdlib_only_with_runners` | `test_scope` + `runners/` importable by path under isolated Python with no `parrot`/pydantic |

### Validation Contract

> Explicit pytest operands that gate this feature in ALL tiers (FEAT-699; this
> spec is written against the schema-1 authoring form, which this feature lifts).

tests:
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select_contract_mode.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_spec_contract.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_contract.py
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py
- packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py
- packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py
- tests/sdd_scripts/test_select_tests.py
- tests/sdd_scripts/test_cache_test_contract.py
- tests/sdd_scripts/test_check_task_graph.py
markers: none

### Test Data / Fixtures
```python
@pytest.fixture
def runner_fixtures(tmp_path):
    """Copies tests/flows/dev_loop/test_scope/fixtures/{vitest-junit.xml, vitest-nested.xml, vitest-nofile.xml,
    libtest-ok.txt, libtest-failed.txt, e2e-verdict.json} and a two-file fixture crate layout into tmp_path."""

@pytest.fixture
def feature_worktree_with_attempt(tmp_path):
    """Hermetic git repo + feature worktree + attempt sub-worktree whose branch carries one failing pytest node,
    a per-spec index with a schema-2 contract (pytest + vitest blocks) and a `.parrot/test_runners.toml`;
    reuses the hermetic-root fixture from tests/flows/dev_loop/sdd_coder/conftest.py."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `test_scope/runners/` ships `RunnerAdapter`, `load_registry` and the pytest,
      vitest, cargo, parrot-e2e adapters; `test_stdlib_only` passes with the package
      imported by path under isolated system Python.
- [ ] `.parrot/test_runners.toml` is the only extension point: settings, timeouts,
      tiers and extension adapters load from it; a malformed file or an invalid
      extension fails closed naming the path (never a pytest-only fallback).
- [ ] `TestContract` schema 2 round-trips; a schema-1 header lifts on read without
      being rewritten; `cache_test_contract.py` writes schema 2 for both authoring forms.
- [ ] A runner block with an unknown kind, a forbidden tier (`parrot-e2e` + `task`),
      or missing `cwd`/`crate`/`plan` is a contract validation error with a
      diagnostic in `check_task_graph.py` and an admission failure in the supervisor —
      never an empty green plan.
- [ ] Plans group per `(runner, distribution)`; pytest invocations are byte-identical
      to FEAT-699 output for a pytest-only contract (regression test).
- [ ] Green cache and baseline operate on pytest targets only; non-pytest failures are
      `unknown` and gate; no non-pytest target is ever recorded green.
- [ ] `parse_junit` maps non-`.py` testcases and retains failure text; libtest and
      `e2e-verdict.json` parsers pass their fixtures; a missing report or an
      unmapped failure stays red.
- [ ] `ValidationVerdict` carries counts per runner, `cached`, failures with
      `new_red|baseline_red|unknown` and a ≤30-line excerpt from junit (or the
      adapter parse); `select_tests.py --verdict` prints only that JSON.
- [ ] `ValidationSupervisor.start(tier="task")` admits exactly one task id with an
      explicit base_ref, applies per-invocation timeouts under the overall cap, marks
      only unfinished invocations `timed_out`, keeps finished evidence, never writes
      the green cache on a partial run, and persists the verdict via
      `ExecutionEvidenceStore.put_artifact` before settling the receipt.
- [ ] `_consolidate` runs the task-tier gate after lint autofix and the banned-import
      gate, before the merge lock, against the fork SHA; a red verdict returns
      `validation_failed` with the verdict and nothing is merged.
- [ ] A red gate re-dispatches the same seat once (fresh sub-worktree seeded from the
      failed branch, verdict rendered in the brief, `attempt + 1`, its own outcome
      emission); a second red follows `_select_retry_seat`; validation reds never
      trigger `_classify_and_suspend`.
- [ ] MCP seats see a `run_validation` tool; an unbound capability is a hard tool
      error; a `run_command` the registry recognises as a runner returns verdict data
      only (no stdout/stderr); the attempt profile allows the configured runner
      binaries.
- [ ] A native-seat lone `pytest|vitest|cargo test` Bash command inside an attempt is
      rewritten to `python scripts/sdd/select_tests.py … --verdict`; compounds keep the
      conservative allow path (documented).
- [ ] `coder_run_validation` accepts `tier="task"` (+ `attempt_uid`); `/sdd-done`
      renders one row per `<runner>:<distribution>` with `n/a` cache/baseline for
      non-pytest; the nightly matrix runs the UI vitest suite.
- [ ] Both `sdd-coder.md` twins, `sdd-worker.md`, `qa-runner.md` and `/sdd-done` docs
      describe the tool, the gate and the repair rule.
- [ ] All §4 tests pass; `ruff check` clean on touched files; the task-tier gate on
      the FEAT-699 replay stays under the pytest budget in `.parrot/test_runners.toml`
      (evidence in `artifacts/logs/`).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor** (verified 2026-10-20 at `7dd48d3c2`;
> paths relative to `packages/ai-parrot/src/parrot/flows/dev_loop/` unless noted;
> brainstorm Code Context re-verified — unchanged since `a5e1b59f2`)

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope import (      # test_scope/__init__.py:7-33 — stdlib-only, never Pydantic
    AttemptContext, BaselineVerdict, CoreHit, GreenCacheEntry, LedgerEntry, PytestInvocation, ScopePlan,
    TestContract, TestTarget, VALIDATION_HEADING, changed_files, contract_from_index_header,
    deepest_existing_dir, distribution_of, is_broad_pytest, is_pytest_invocation,
    parse_validation_commands, parse_spec_contract, plan_tests, prune_nested,
    pytest_file_targets, pytest_target_for, pytest_targets,
)
from parrot.flows.dev_loop.test_scope.guard import GuardOutcome, guard_argv     # dispatchers/llm.py:59
from parrot.flows.dev_loop.test_scope.select import changed_files, plan_tests    # sdd_coder/background.py
from parrot.flows.dev_loop.test_scope.contract import contract_from_index_header, load_index_header, parse_validation_commands
from parrot.flows.dev_loop.test_scope import green_cache, baseline
from parrot.flows.dev_loop.procs import run_bounded                            # sdd_coder/lint.py:25
from parrot.flows.dev_loop.sdd_coder.models import LintConfig, LintReport      # sdd_coder/lint.py:26
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedback, CoderFeedbackReceipt, CoderFeedbackStore  # engine.py:35
import tomllib                                                                 # stdlib; sdd_coder/lint.py:22 already uses it
```

### Existing Class Signatures
```python
# test_scope/datatypes.py
class TestTarget:                      # line 11 — path, distribution, reason
class PytestInvocation:                # line 22 — distribution, argv, targets   (→ Invocation, hard cut)
class ScopePlan:                       # line 42 — tier, invocations, escalated, core_hits, skipped_escalations, notes, cap_hits, cap_impacted, mode="fallback", cached=()
class TestContract:                    # line 66 — schema (only 1), tests, markers, digest
class BaselineVerdict:                 # line 87 — nodeid, status, detail
class AttemptContext:                  # line 106 — tier, task_id, task_file, base_ref

# test_scope/contract.py
VALIDATION_HEADING = "## Validation Commands"        # line 14
SPEC_CONTRACT_HEADING = "### Validation Contract"    # line 23
TEST_CONTRACT_SCHEMA: int = 1                        # line 24
def env_prefix_of(argv) -> list[str]                 # line 29
def strip_env_prefix(argv) -> list[str]              # line 39
def _strip_uv_run_prefix(argv) -> list[str]          # line 50
def normalize_pytest_argv(argv) -> list[str]         # line 66
def parse_validation_commands(task_md) -> list[list[str]]   # line 71
def _pytest_operands(argv) -> list[str] | None       # line 91
def is_pytest_invocation(argv) -> bool               # line 141
def is_broad_pytest(argv, *, worktree=None) -> bool  # line 151
def contract_digest(tests, markers) -> str           # line 173
def parse_spec_contract(spec_md) -> TestContract | None            # line 227
def contract_from_index_header(header) -> TestContract | None      # line 291 — raises ValueError
def contract_to_header(contract) -> dict[str, object]              # line 316
def load_index_header(index_path: Path) -> dict[str, object]       # line 326

# test_scope/select.py
def changed_files(worktree: Path, base_ref: str) -> list[str]      # line 20
def plan_tests(*, worktree, changed_files, tier, declared=(), contract=None, policy=None) -> ScopePlan   # line 123
#   line 148: `if tier != "task" and contract is not None:` — contract operands enter here (task tier excluded)

# test_scope/planner.py
PER_DIST_EXTRA_ARGS = ("--confcutdir", "{worktree}")             # line 13
OVERRIDE_MARKER_EXPRESSION = "not real_llm"                      # line 18
def marker_expression_for(targets, *, contract, policy) -> str   # line 21
def _invocation(distribution, targets, *, worktree, policy, marker_expression=None) -> PytestInvocation  # line 32
#   line 56: argv = ("pytest", *AGENT_FLAGS, "-m", expression, *xdist, *extra, *kept_paths)
def build_plan(targets, *, tier, worktree, policy, escalated=(), core_hits=(), skipped_escalations=(), cap_hits=None, cap_impacted=None, notes=(), contract=None, mode="fallback") -> ScopePlan  # line 59

# test_scope/policy.py
AGENT_MARKER_EXPRESSION = "not e2e and not real_llm and not integration"   # line 7
AGENT_FLAGS = ("-q", "--tb=short", "-p", "no:cacheprovider", "-o", "log_cli=false")  # line 8
TIERS = ("task", "merge", "feature")                 # line 78
class ScopePolicy:                                   # line 82 — xdist_safe :89, marker_expression :100

# test_scope/mirror.py
def pytest_targets(files, worktree_path) -> list[str]          # line 10
def pytest_target_for(path, worktree_path) -> str | None       # line 38
def pytest_file_targets(files, worktree_path) -> list[str]     # line 84
def pytest_file_target_for(path, worktree_path) -> str | None  # line 89
def prune_nested(targets: set[str]) -> list[str]               # line 154
def distribution_of(path: str) -> str                          # line 166

# test_scope/guard.py
BLOCK_MESSAGE: str                                   # line 15
class GuardOutcome: action ("allow"|"rewrite"|"block"), argvs, message   # line 24
def _is_pytest_argv(argv) -> bool                    # line 32
def _task_plan(worktree: Path) -> ScopePlan | None   # line 44
def guard_argv(argv, *, worktree: Path) -> GuardOutcome                       # line 60
def guard_bash(command: str, *, worktree: Path) -> tuple[GuardOutcome, str | None]   # line 102

# test_scope/report.py
class SuiteResult:                                   # line 37 — suite, tests, passed, failed, errors, skipped, duration_s, exit_code, argv, status, nodes=(), unmapped=0, baseline=()
class TaskTestRecord:                                # line 56
def junit_path_for(feature_id, task_id, suite, ordinal) -> Path          # line 88
def with_junit(invocation: PytestInvocation, junit_path: Path) -> tuple[str, ...]   # line 106 — appends "-o junit_family=xunit1 --junitxml=…"
def nodeid_from_testcase(file_attr, classname, name) -> str | None        # line 111 — returns None unless file_attr.endswith(".py")
def suite_name(invocation: PytestInvocation) -> str  # line 127
def parse_junit(junit_path, *, suite, argv, exit_code, duration_s, timed_out=False) -> SuiteResult   # line 146
def append_suite(...)                                # line 257
def append_cached(...)                               # line 307
def render_markdown(records, task_ids, *, final_head, rerun, rerun_skip_reason) -> str   # line 420

# test_scope/green_cache.py
def cache_namespace(*, feature_id, base_ref, contract_digest) -> str   # line 38
def _is_cacheable(target: str) -> bool               # line 49 — `.py` only
def filter_cached(worktree, plan, *, namespace, ...) -> tuple[ScopePlan, tuple[str, ...]]   # line 156
def record_green(...)                                # line 223

# test_scope/baseline.py
def prepare_baseline_checkout(*, worktree, base_ref, scratch) -> Path   # line 45
def classify_failures(*, repo_root, base_ref, failed_nodeids, timeout_s) -> tuple[BaselineVerdict, ...]   # line 156
def gate_failed(verdicts) -> bool                    # line 204

# sdd_coder/background.py
_TASK_ID_RE = re.compile(r"^TASK-\d{1,5}$")          # line 76
_DEFAULT_BASE_REF = "origin/dev"                     # line 86
class ValidationSupervisor:                          # line 442
    async def start(self, *, feature, worktree: Path, execution_id, task_ids: list[str], tier: Literal["merge","feature"], timeout_seconds, request_id, base_ref=None, index_path=None) -> BackgroundRegistration   # line 493
    #   line 505: `if tier not in ("merge", "feature"):`  — tier admission
    #   line ~575: BackgroundRegistration(..., kind="validation", authority="supervisor", backend="pytest-subprocess", ...)
    async def _plan_selection(self, *, worktree, tier, base_ref=None, index_path=None, task_ids=(), feature_id="") -> ScopePlan   # line 753
    async def _supervise(...)                        # line 868
    def _argv_with_junit(feature_id, task_id, invocation, ordinal, *, enabled=True)   # line 1021 (static)
    async def _record_test_results(self, *, worktree, feature_id, task_ids, invocation, junit_path, exit_code, duration_s, timed_out, tier, base_ref, deadline) -> Optional[SuiteResult]   # line 1034

# sdd_coder/engine.py
class _FeatureCtx:                                   # line 225 — worktree, feature_id, feature, feature_branch, index_path, spec_path, base_branch
async def _consolidate_diff_base(feature_branch, branch, *, cwd) -> str   # line 167 (module-level)
async def run_validation(self, feature, worktree, execution_id, task_ids, tier: Literal["merge","feature"], timeout_seconds, request_id) -> BackgroundRegistration   # line 1149
async def _write_attempt_scope(self, worktree_path, task_id, task_file, base_ref) -> None   # line 2016
async def prepare_native(...)                        # line 2046 — returns NativePrep(coder_feedback=feedback_context, ...)
async def _feedback_for(self, ctx, task, backend, model) -> str   # line 2319
async def _consolidate(self, ctx, manager, task, *, branch, path, lock_timeout_s=None) -> TaskResult   # line 2640
#   extraction `_commit_declared_changes` → `_consolidate_diff_base` → fidelity → `run_lint_pass` → `check_banned_imports` (line ~2731) → `async with self._acquire_merge_lock(lock_timeout_s):` (line ~2740) → merge_sequential
async def _run_attempt(self, ctx, task, seat, *, attempt, job_id, execution_id=None, pool=None) -> Tuple[AttemptRecord, Optional[DevelopmentOutput], str, SubWorktreeManager, str, str]   # line 3090
#   line ~3228: await manager.create(self._worker_id(task.task_id, attempt, execution_id))
#   line ~3237-3245: dispatcher.dispatch(brief=TaskScopedBrief(research=…, task_id=…, task_file=…, coder_feedback=feedback_context), …)
async def _select_retry_seat(...)                    # line 3598
async def _run_task(self, ctx, task, seat, *, job_id, execution_id=None, pool=None) -> TaskResult   # line 3642
#   line ~3689: `result = await self._consolidate(ctx, manager, task, branch=branch, path=path)` (first, inside `if not err`)
#   line ~3822: `result = await self._consolidate(...)` (second, after the ladder)  — occurrence count 2 (see Edit Sites)
async def run_chunk(...)                             # line 3842

# sdd_coder/models.py
TaskOutcome = Literal["queued","running","merged","merge_conflict","failed","fidelity_violation","retry_native","not_dispatched"]   # line 30
class RosterSeat(BaseModel):                         # line 143
class LintConfig(BaseModel):                         # line 175
class RosterConfig(BaseModel):                       # line 219 — lint: LintConfig (:225), feedback: FeedbackConfig (:226)
class AttemptRecord(BaseModel):                      # line 312 — attempt (1..3), seat_label, backend, model, started_at, ended_at, duration_s, usage, error, attempt_uid
class TaskResult(BaseModel):                         # line 359 — task_id, outcome, branch, worktree_path, attempts, conflict_files, unexpected_files, diagnostics, development_output, lint, native_retry
class NativePrep(BaseModel):                         # line 376 — task_id, task_file, branch, worktree_path, seat_label, model, attempt_uid, coder_feedback, assessment_id, execution_id, bg_handle
class CoderResult(BaseModel):                        # line 542

# sdd_coder/toolkit.py
async def coder_run_validation(self, feature, worktree, execution_id, task_ids: List[str], tier: Literal["merge","feature"], timeout_seconds: int, request_id: str) -> CoderResult   # line 602 — `exclusive=True`

# sdd_coder/evidence.py
class ExecutionEvidenceStore:                        # line 154
    async def put_artifact(self, execution_id: str, payload: BaseModel) -> EvidenceRef   # line 170

# sdd_coder/lint.py
LINT_TIMEOUT_S = 300.0                               # line 29
def resolve_bin(name: str) -> Optional[str]          # line 41

# models/base.py
class TaskScopedBrief(BaseModel):                    # line 478 — research, task_id, coder_feedback (:488), task_file
class DevelopmentOutput(BaseModel):                  # line 520

# models/llm.py
class LLMCodeDispatchProfile: allowed_commands: List[str]   # line 51 — default list includes "pytest" (:55), not pnpm/cargo/parrot

# dispatchers/llm.py
class LLMCodeDispatcher:                             # line 67
    def set_event_registry_resolver(self, resolver) -> None   # line 99 — the injection pattern M8 mirrors
    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None, labels=None) -> T   # line 129
    def _tool_schemas(self, output_model) -> List[Dict[str, Any]]   # line 1301 — "run_command" entry :1423, "final_output" :1453
    async def _run_tool(self, *, tool_name, tool_args, cwd, profile, ...)   # line 1474 — `if tool_name == "run_command":` :1495
    async def _tool_run_command(self, cwd, args, profile) -> Dict[str, Any]   # line 1894 — allowed_commands check :1904, guard_argv :1945
    async def _run_guarded_invocations(self, argvs, *, cwd, timeout, hint) -> Dict[str, Any]   # line 2135 — merges stdout/stderr (the leak)

# worktree_manager.py
class SubWorktreeManager:
    async def create(self, worker_id: str) -> str    # line 143 — `git worktree add -b <branch> <path> self.feature_branch` (:165)

# worktree_environment.py
def command_policy_error(cwd: Path, argv) -> str | None   # line 102 — only `uv` is policed here
def _load_guard_bash() -> Any                        # line 294
def _is_lone_pytest(command: str) -> bool            # line 313
def _scope_guard(command: str, cwd: Path) -> tuple[str, str | None]   # line 325 — caller :445 (`action, value = _scope_guard(command, cwd)`)

# procs.py
async def run_bounded(argv, *, cwd=None, timeout_s=DEFAULT_SUBPROCESS_TIMEOUT_S, env=None) -> Tuple[int, str, str]   # line 92

# packages/ai-parrot-server/src/parrot/e2e/runner.py — NOT importable from the kernel; the adapter reads the file
_VERDICT_NAME = "e2e-verdict.json"; _POINTER_NAME = "latest.json"   # lines 46-47
async def run_plan(plan_path: Path, *, worktree: Path, owner_id: str) -> E2EVerdict   # line 66
# packages/ai-parrot-server/src/parrot/e2e/models.py
class E2EVerdict(_E2EBaseModel):                     # line 504 — results, counts, argv, exit_code, selected_node_ids, collected_node_ids
# packages/ai-parrot-server/src/parrot/e2e/cli.py
@e2e.command("run") --plan <path> --owner-id <id>    # lines 392-396

# scripts/sdd/select_tests.py
parser.add_argument("--tier", required=True, choices=("task","merge","feature"))   # line 33
parser.add_argument("--run", action="store_true") / ("--json", ...)   # lines 47-48
def main(argv=None) -> int                           # line 111 — `if args.json:` :165; per-invocation loop :~205
# scripts/sdd/cache_test_contract.py
def main(argv=None) -> int                           # line 45 — `contract_to_header` call :70
# scripts/sdd/check_task_graph.py
def _check_validation_contract(tasks, root, required) -> list[Finding]   # line 234 (FEAT-563 flag — untouched)
def _check_test_contract(data, root, tasks) -> list[Finding]             # line 309 — duplicates `_pytest_operands` (to remove, S6)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `RunnerRegistry.adapter_for_argv` | `guard.guard_argv` / `guard_bash` | replaces `_is_pytest_argv` | `guard.py:32,60,102` |
| `RunnerAdapter.invocation` | `planner.build_plan` | per-`(runner, distribution)` group | `planner.py:59` |
| `RunnerAdapter.parse_report` | `ValidationSupervisor._record_test_results` | replaces direct `parse_junit` | `background.py:1034` |
| `build_verdict` | `ValidationSupervisor._supervise` → `ExecutionEvidenceStore.put_artifact` | persisted before receipt | `background.py:868`, `evidence.py:170` |
| `_task_tier_gate` | `SddCoderEngine._consolidate` | after `check_banned_imports`, before `_acquire_merge_lock` | `engine.py:~2731-2740` |
| same-seat repair | `SddCoderEngine._run_task` | after first `_consolidate` returns `validation_failed` | `engine.py:~3689` |
| `SubWorktreeManager.create(base=…)` | `_run_attempt` | `manager.create(worker_id, base=repair_from)` | `engine.py:~3228`, `worktree_manager.py:143` |
| `ValidationCapability` | `LLMCodeDispatcher.set_validation_runner` | mirrors `set_event_registry_resolver` | `llm.py:99` |
| `_tool_run_validation` | `_run_tool` routing | new `elif tool_name == "run_validation"` | `llm.py:1495` |
| verdict command | `worktree_environment._scope_guard` | rewrite value | `worktree_environment.py:325,445` |
| schema-2 lint | `check_task_graph._check_test_contract` | `load_registry` + `contract_from_index_header` | `check_task_graph.py:309` |

### Does NOT Exist (Anti-Hallucination)
- ~~`test_scope/runners/`~~, ~~`test_scope/verdict.py`~~, ~~`RunnerAdapter`~~, ~~`RunnerRegistry`~~, ~~`load_registry`~~, ~~`normalize_launcher_argv`~~ — new in M1/M5.
- ~~`Invocation`~~, ~~`RunnerContract`~~, ~~`RunReport`~~, ~~`Failure`~~, ~~`RunnerSummary`~~, ~~`ValidationVerdict`~~, ~~`TestTarget.runner`~~ — new in M2.
- ~~`TestContract.runners` / `.pytest`~~ — today `tests` + `markers` only; ~~`TEST_CONTRACT_SCHEMA == 2`~~ — it is 1.
- ~~`GuardOutcome.action == "verdict"`~~ — only `allow | rewrite | block`.
- ~~`ValidationSupervisor.start(tier="task")`~~, ~~`wait_verdict`~~, ~~`attempt_uid` kwarg~~ — tier Literal is `merge | feature`.
- ~~`coder_run_validation(tier="task")`~~ — same Literal in `toolkit.py:608`.
- ~~`TaskOutcome "validation_failed"`~~, ~~`TaskResult.validation`~~, ~~`RosterConfig.runners` / `RunnerConfig`~~, ~~`ValidationVerdictModel`~~ — not in `sdd_coder/models.py`.
- ~~`TaskScopedBrief.validation_verdict`~~, ~~`NativePrep.validation_verdict`~~.
- ~~`SubWorktreeManager.create(..., base=…)`~~ — `create(self, worker_id)` only; always forks `self.feature_branch`.
- ~~`LLMCodeDispatcher.set_validation_runner`~~, ~~`_tool_run_validation`~~, ~~`ValidationCapability`~~, ~~a `run_validation` entry in `_tool_schemas`~~.
- ~~`pnpm`, `cargo`, `parrot` in `LLMCodeDispatchProfile.allowed_commands` defaults~~ — `pytest` is listed, those are not.
- ~~a shebang on `scripts/sdd/select_tests.py`~~ — line 1 is the module docstring; always invoke through `python`.
- ~~`select_tests.py --verdict` / `--log-dir`~~ — modes today are `--json` and `--run`.
- ~~`parse_junit` for non-`.py` files~~ — `nodeid_from_testcase` returns None for them (report.py:113); ~~failure text retention~~ — only `(nodeid, status)` is kept.
- ~~`green_cache` / `baseline` awareness of runners~~ — `.py`-only filters, pytest-only re-runs.
- ~~`tests/ui/_vitest.py`~~ — no vitest wrapper exists; ~~`Cargo.toml` in this repo~~ — none (cargo adapter tested against a fixture crate layout).
- ~~`parrot.e2e` importable from the kernel~~ — lives in `ai-parrot-server`, Pydantic-based; read `e2e-verdict.json` from disk only.
- ~~`.parrot/test_runners.toml`~~ — new in M11.
- ~~`_subagent_data/sdd-coder.md` tool list with MCP tools~~ — `Read, Write, Edit, MultiEdit, Bash, Glob, Grep` only; native seats stay that way.

### Edit Sites (Blueprint Anchors)

Verified against: `7dd48d3c2`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/base.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/pytest.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/vitest.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/cargo.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/parrot_e2e.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/verdict.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py` | MODIFY | `class PytestInvocation:` | `datatypes.py:22` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py` | MODIFY | `class TestContract:` | `datatypes.py:66` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py` | MODIFY | `TEST_CONTRACT_SCHEMA: int = 1` | `contract.py:24` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py` | MODIFY | `def parse_spec_contract(` | `contract.py:227` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py` | MODIFY | `def contract_from_index_header(` | `contract.py:291` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py` | MODIFY | `def contract_to_header(` | `contract.py:316` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py` | MODIFY | `from .select import changed_files, plan_tests` | `__init__.py:33` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | MODIFY | `def plan_tests(` | `select.py:123` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | MODIFY | `    if tier != "task" and contract is not None:` | `select.py:148` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` | MODIFY | `def _invocation(` | `planner.py:32` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` | MODIFY | `    argv = ("pytest", *AGENT_FLAGS, "-m", expression, *xdist, *extra, *kept_paths)` | `planner.py:56` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` | MODIFY | `def build_plan(` | `planner.py:59` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py` | MODIFY | `def pytest_file_target_for(path: str, worktree_path: str) -> str \| None:` | `mirror.py:89` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py` | MODIFY | `def _is_pytest_argv(` | `guard.py:32` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py` | MODIFY | `def guard_argv(` | `guard.py:60` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py` | MODIFY | `def guard_bash(` | `guard.py:102` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` | MODIFY | `class SuiteResult:` | `report.py:37` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` | MODIFY | `def with_junit(` | `report.py:106` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` | MODIFY | `def nodeid_from_testcase(file_attr: str \| None, classname: str, name: str) -> str \| None:` | `report.py:111` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` | MODIFY | `def suite_name(` | `report.py:127` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` | MODIFY | `def parse_junit(` | `report.py:146` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py` | MODIFY | `def _is_cacheable(target: str) -> bool:` | `green_cache.py:49` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py` | MODIFY | `def classify_failures(` | `baseline.py:156` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | `    async def start(` | `background.py:493` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | `        if tier not in ("merge", "feature"):` | `background.py:505` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | `            backend="pytest-subprocess",` | `background.py:~575` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | `    async def _plan_selection(` | `background.py:753` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | `    def _argv_with_junit(` | `background.py:1021` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | `    async def _record_test_results(` | `background.py:1034` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `    async def run_validation(` | `engine.py:1149` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `        violations = await check_banned_imports(path, changed)` | `engine.py:~2731` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `        async with self._acquire_merge_lock(lock_timeout_s):` | `engine.py:~2740` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `            result = await self._consolidate(ctx, manager, task, branch=branch, path=path)` (12-space indent, inside `if not err:` in `_run_task`; the 8-space-indent twin at `:~3822` is the post-ladder call) | `engine.py:~3689` | 1 (the 8-space variant has 2 incl. this one as substring — match with leading spaces) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `                    coder_feedback=feedback_context,` | `engine.py:~3242` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `            await self._write_attempt_scope(path, task.task_id, task.task_file, ctx.feature_branch)` — 2 occurrences: `prepare_native` (~2162, preceded by `path = await manager.create(worker_id)`) and `_run_attempt` (~3229, preceded by `await manager.create(self._worker_id(task.task_id, attempt, execution_id))`) | `engine.py:~2162,~3229` | 2 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `    async def _select_retry_seat(` | `engine.py:3598` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | `TaskOutcome = Literal[` | `models.py:30` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | `class RosterConfig(BaseModel):` | `models.py:219` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | `class TaskResult(BaseModel):` | `models.py:359` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | `class NativePrep(BaseModel):` | `models.py:376` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` | MODIFY | `    async def coder_run_validation(` | `toolkit.py:602` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` | MODIFY | `        tier: Literal["merge", "feature"],` | `toolkit.py:608` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` | MODIFY | `class TaskScopedBrief(BaseModel):` | `base.py:478` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py` | MODIFY | `    allowed_commands: List[str] = Field(` | `llm.py:51` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py` | MODIFY | `    async def create(self, worker_id: str) -> str:` | `worktree_manager.py:143` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` | MODIFY | `    def set_event_registry_resolver(self, resolver: Callable[[str], Optional["EventRegistry"]]) -> None:` | `llm.py:99` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` | MODIFY | `                "run_command",` | `llm.py:1423` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` | MODIFY | `            if tool_name == "run_command":` | `llm.py:1495` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` | MODIFY | `    async def _tool_run_command(` | `llm.py:1894` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` | MODIFY | `    async def _run_guarded_invocations(` | `llm.py:2135` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` | MODIFY | `def _is_lone_pytest(` | `worktree_environment.py:313` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` | MODIFY | `def _scope_guard(` | `worktree_environment.py:325` | 1 |
| `scripts/sdd/select_tests.py` | MODIFY | `    parser.add_argument("--json", action="store_true")` | `select_tests.py:48` | 1 |
| `scripts/sdd/select_tests.py` | MODIFY | `    if args.json:` | `select_tests.py:165` | 1 |
| `scripts/sdd/cache_test_contract.py` | MODIFY | `    value = contract_mod.contract_to_header(contract) if contract is not None else None` | `cache_test_contract.py:70` | 1 |
| `scripts/sdd/check_task_graph.py` | MODIFY | `def _check_test_contract(` | `check_task_graph.py:309` | 1 |
| `sdd/templates/spec.md` | MODIFY | `### Validation Contract` | `spec.md` | 1 |
| `.claude/agents/sdd-coder.md` | MODIFY | ``- Run exactly the commands listed under your task file's `## Validation Commands`.`` | `sdd-coder.md:175` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md` | MODIFY | ``- Run exactly the commands listed under your task file's `## Validation Commands`.`` | `_subagent_data/sdd-coder.md` | 1 |
| `.parrot/test_runners.toml` | CREATE | — | — | — |
| `.github/workflows/nightly-tests.yml` | MODIFY | `(unverified — check before use)` matrix entry list | — | — |

- Anchors marked `~NNN` were read in context on `7dd48d3c2`; `/sdd-task` re-runs `grep -c` for every row.
- The two `_write_attempt_scope` call sites and the two `_consolidate` calls in `_run_task` are
  disambiguated by indentation and the preceding line quoted in the anchor cell.

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- Kernel stays stdlib-only and path-importable (`test_scope/__init__.py:1-5`);
  `runners/` and `verdict.py` obey the same rule; Pydantic mirrors live in
  `sdd_coder/models.py` / `test_scope/models.py` only.
- Hard cuts, no shims: `PytestInvocation` → `Invocation`, `with_junit` →
  `with_report`, `TestContract.tests/markers` → `runners`; every in-repo caller is
  updated in the same feature (memory "no external consumers; hard cuts OK").
- Dependency injection into the dispatcher mirrors `set_event_registry_resolver`
  (`llm.py:99`): the dispatcher never imports the engine.
- Every supervisor kernel call goes through `asyncio.to_thread` (existing style in
  `background.py`); subprocesses through `asyncio.create_subprocess_exec` with the
  adapter's `cwd` and per-invocation timeout.
- Evidence first: a verdict exists only after `put_artifact`; the receipt links it;
  `report.append_suite` keeps per-task records as today.
- Guard philosophy unchanged: a broken guard never breaks a seat (`guard_argv` /
  `_scope_guard` keep their `except Exception: allow` envelopes).
- Both `sdd-coder.md` twins change together (`git add -f .claude/...`); memory
  "sdd-worker prompt: two suites".

### Known Risks / Gotchas
- **Gate base ref (S2)**: `_write_attempt_scope` records the *moving* feature branch
  name; the gate must pass the fork SHA from `_consolidate_diff_base` as `base_ref`,
  or a sibling merge changes what "changed" means mid-run.
- **Repair worktree (S8)**: `SubWorktreeManager.create` forks `self.feature_branch`;
  the repair attempt needs `base=<failed branch>` or the seat starts from a tree
  without its own commits. The repair branch must still merge-base cleanly with the
  feature branch (`_consolidate_diff_base` already covers a branch that advanced).
- **Launcher chains (S3)**: `pnpm test` runs `vitest run` via `package.json`; the
  normaliser maps it, but a repo whose `test` script is not vitest must configure
  `[runners.vitest] test_script = false` to disable that mapping (setting added in M1).
- **Command allow-list (S4)**: `allowed_commands` is enforced *before* the guard
  (`llm.py:1904`); runner binaries must be appended per attempt or the seat gets a
  policy error instead of a verdict. `select_tests.py` has no shebang — always
  `python scripts/sdd/select_tests.py`.
- **Deadlines (S9)**: one `timeout_seconds` today covers chained invocations;
  per-runner budgets are open (§8 Q4) — defaults are placeholders measured before
  freezing; a partial run must never populate the green cache.
- **Non-pytest reds are `unknown`** and gate (S5); a seat may chase a pre-existing
  vitest red. The verdict note says "no baseline for <runner>" so the seat knows.
- **`parse_junit` `.py` rule** (report.py:113) silently drops vitest nodes today —
  fixtures land first (S10) so the change is observable.
- **Seat vs gate double run**: a seat that calls `run_validation` and then commits
  triggers the gate again; the task tier never uses the green cache, so this is a
  deliberate second run, bounded by the same budget.
- **Native hook environment**: the rewritten command runs inside Bubblewrap with
  `PYTHONPATH` set to `packages/*/src`; `pnpm`/`cargo`/`parrot` must resolve on the
  sandbox PATH (`protected_argv`) — extend the PATH bind, not the allow-list only.
- **Attempt counter**: `AttemptRecord.attempt` is `le=3`; red → same-seat repair →
  ladder uses attempts 1/2/3 exactly; a fourth is impossible by model validation.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `tomllib` | stdlib (Python ≥ 3.11) | `.parrot/test_runners.toml` |
| `xml.etree` | stdlib | junit parsing (pytest, vitest) |
| vitest | repo-pinned in `packages/ai-parrot-server/ui/package.json` | `--reporter=junit --outputFile` (built-in reporter) |
| `cargo` | stable toolchain | libtest text output; no nightly flags |
| `parrot e2e` CLI | `ai-parrot-server` (FEAT-581) | writes `e2e-verdict.json`; invoked as a subprocess only |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] How do sibling repos consume the kernel? — *Resolved in brainstorm*: vendored copy for now (`parrot-installer`, FEAT-633, has not landed); `.parrot/test_runners.toml` is the only extension point in v1; no entry-point registry, nothing assuming an installed `parrot`.
- [x] Same-seat re-dispatch: fresh conversation or resumed history? — *Resolved in brainstorm*: fresh conversation + verdict; ordinary `_run_attempt` on the same seat in a fresh sub-worktree seeded from the failed branch; no dispatcher message persistence.
- [x] Should `parrot-e2e` ever run in the task tier? — *Resolved in brainstorm*: no; adapter `default_tiers = {merge, feature}`; a contract that lists `task` is a validation error (S11 tightened "lint warns" into "fails").
- [ ] Per-runner task-tier timeout budgets (pytest 60 s, vitest 120 s, cargo 300 s assumed) and whether a gate timeout re-dispatches the same seat or goes straight to the ladder — *Owner: Jesus*. Spec stance until decided: defaults live in `.parrot/test_runners.toml`, measured in `artifacts/logs/` before freezing; a `timed_out` verdict is treated like any red (same-seat repair first).
- [x] Cargo adapter: stable libtest text or `cargo nextest`? — *Resolved in brainstorm*: stable libtest text (`test <name> ... ok|FAILED|ignored` + `failures:` section); nextest/junit later.
- [x] Native Bash guard scope — *Resolved in brainstorm*: lone commands only; compounds keep today's conservative handling; the engine gate covers them.
- [x] Verdict excerpt source — *Resolved in brainstorm*: junit (`<failure>`/`<error>` text, last 30 lines); runners without junit use the adapter's own parse under the same bound; pytest junit omits captured stdout/stderr by default, which is desired.
- [x] Schema-2 migration — *Resolved in brainstorm*: lift on read; indexes rewritten only when `/sdd-task` or `cache_test_contract.py` next touches them; no one-shot migration commit.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.162.1) · Status: completed
> · Transcript: `sdd/state/FEAT-709/design_research/`
> Every `affected_paths` entry passed repository containment and `test -e`; factual claims were
> spot-checked in the source (see `triage.md`).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make verdict execution a first-class supervisor receipt (architecture) | CONFIRM | One supervisor-owned run-and-verdict path for the seat tool and the engine gate; verdict persisted via `ExecutionEvidenceStore.put_artifact` before it is returned | §2 Overview, M6 |
| S2 | Validate the immutable attempt tree before acquiring the merge lock (architecture) | CONFIRM | Gate placed after lint autofix + banned-import gate, before `_acquire_merge_lock`, diffing against the fork SHA from `_consolidate_diff_base` | M7, §7 Gotchas |
| S3 | Match normalized command chains, not only argv[0] (api) | CONFIRM | Shared `normalize_launcher_argv` handles env prefixes, `uv run`, `python -m`, `pnpm exec/run/test`, `npx`; ambiguous chains rejected | M1, M3, M4 |
| S4 | Resolve the guard bypass and verdict-command mismatch (risk) | CONFIRM | Runner binaries appended to `allowed_commands`; native rewrite invokes `python scripts/sdd/select_tests.py` (no shebang); rewritten commands return verdict data only; compounds stay allowed and are covered by the gate | M8, §7 Gotchas |
| S5 | Make cache and baseline behavior explicitly runner-scoped (architecture) | CONFIRM | pytest-only filters in `green_cache`/`baseline`; non-pytest failures `unknown` and gating | M3, M5, §5 |
| S6 | Centralize runner validation in the kernel checker (api) | CONFIRM | `check_task_graph` and `cache_test_contract` consume the registry + contract loader; duplicated operand parsing removed | M9 |
| S7 | Inject a capability into the dispatcher instead of importing the engine (api) | CONFIRM | `set_validation_runner` mirrors `set_event_registry_resolver`; capability bound per attempt to one task; absent ⇒ hard tool error | M8 |
| S8 | Add an explicit validation-retry state machine (architecture) | CONFIRM | `validation_failed` outcome, `TaskResult.validation`, repair worktree from the failed branch, one outcome per attempt, no suspension for validation reds | M7 |
| S9 | Separate per-runner deadlines from the plan deadline (risk) | CONFIRM | Per-invocation timeout + overall cap; only unfinished invocations `timed_out`; finished evidence kept; no green cache on partial runs | M6, §8 Q4 |
| S10 | Add runner-specific evidence fixtures before changing the parser spine (testing) | CONFIRM | Fixtures for TS junit, nested suites, missing `file`, libtest, e2e JSON, missing report, truncation land in the first M4 task; `parse_junit` accepts non-`.py` and keeps failure text | M4, §4 |
| S11 | Enforce runner tier eligibility at admission (api) | CONFIRM | Forbidden tier is a contract validation error with a diagnostic, never an empty green plan | M2, M9, §5 |
| S12 | Constrain TOML adapter loading to the stdlib kernel contract (risk) | CONFIRM | Extensions imported under kernel rules, protocol-checked at load, lint re-checks under isolated Python; fail closed naming the config path | M1, M9 |

Summary: **12** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree (`feat-FEAT-709-language-agnostic-validation-runners`);
  the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (evidence in §3 "Depends on"):
  - M1 → M2 (`RunnerAdapter.invocation` returns `Invocation`; registry validates `RunnerContract.tiers`) — these two land first, together or M2 first.
  - M3 → M1, M2 (planner/guard/select consume the registry and `Invocation`).
  - M4 → M1, M2 (adapters implement the protocol; `report.py` returns `RunReport`).
  - M5 → M2, M4 (`build_verdict` consumes `RunReport`; CLI runs adapters).
  - M6 → M1–M5 (supervisor runs invocations and builds the verdict).
  - M7 → M5, M6 (gate waits on the supervisor; models mirror the verdict).
  - M8 → M3 (guard), M5 (verdict JSON), M7 (`ValidationCapability` from the engine).
  - M9 → M1, M2 (lint/caching use registry + contract).
  - M10 → M5–M8 semantics frozen (docs only).
  - M11 → M1 (TOML schema), M4 (vitest adapter) — independent of M6–M8.
  M4, M5, M9 and M11 have no edge between them and run concurrently once M1+M2 land.
- **Shared files** (tasks serialized): `test_scope/contract.py` (M2, M3 re-exports),
  `test_scope/report.py` (M4 parser spine, M5 suite naming), `sdd_coder/engine.py`
  (M7 gate, M7 repair, M8 capability binding — three tasks, one chain),
  `sdd_coder/models.py` (M7 outcome/verdict models, M7 `RunnerConfig`),
  `dispatchers/llm.py` (M8 tool + routing — one task), both `sdd-coder.md` twins (M10).
- **Exclusive resources**: none (no extension rebuild, lockfile or migration); the
  nightly workflow edit (M11) is a single-file change pushed via SSH per memory
  "push workflow files needs SSH".
- **Cross-feature dependencies**: FEAT-699 merged (base); FEAT-703 (`TASK-4460`
  active, `scripts/sdd/check_e2e_closeout.py`) reads the same `e2e-verdict.json` but
  touches no shared file; FEAT-633 (spec rev 0.3) plans `worktree_environment.py`
  edits — the `_scope_guard` task must rebase-check against it before merging.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-20 | Jesus Lara (with Claude) | Initial draft from the accepted brainstorm + codex design research (12/12 confirmed) |
