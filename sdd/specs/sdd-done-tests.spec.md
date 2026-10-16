---
type: feature
base_branch: dev
projects: [sdd-tooling, dev-loop]
tags: [sdd-done, test-reporting, pull-request, sdd-coder, evidence]
---

# Feature Specification: sdd-done test-results table

**Feature ID**: FEAT-695
**Date**: 2026-10-16
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: next minor
**Source**: `sdd/proposals/sdd-done-tests.proposal.md` (accepted) · research `sdd/state/FEAT-695/`

---

## 1. Motivation & Business Requirements

### Problem Statement
sdd-coder seats and the sdd-worker fallback lane run tests for every task, and
sometimes the whole spec's test set. None of that reaches the PR that
`/sdd-done` opens: the body only says "`<N>/<total> tasks verified`". The
evidence is lost in three places:
- `/sdd-done` deliberately skips tests (`sdd-done.md:145`).
- sdd-coder validation records keep only `outcome` and `exit_code`
  (`background.py`), with no counts.
- Counts survive only as free-text "N passed" in about 29% of Completion Notes,
  and their scope varies.

Reviewers have no visible test metric when approving a spec.

### Goals
- G1: every pytest invocation run by the SDD selector (CLI `select_tests --run` and
  `coder_run_validation`) produces a **structured** count record: passed / failed /
  skipped / errors / duration, per suite.
- G2: those records are written per task to a **temporary** location and
  aggregated by `/sdd-done`.
- G3: the PR body opened by `/sdd-done` **always** carries a test table built from
  the aggregate of what every task executed: one row per suite plus a Total row.
- G4: `/sdd-done` additionally re-runs the feature tier against the final HEAD
  **iff** the feature has ≤ 10 tasks. This is a deterministic rule computed from
  the per-spec index, and its result is shown as an extra column.
- G5: failures are **reported, never blocking**. The PR is opened regardless.

### Non-Goals (explicitly out of scope)
- CI changes, coverage %, mutation scores.
- The E2E gate (§4.6 of `/sdd-done`) stays separate and untouched.
- Making test results durable or committed. The records are throwaway by design
  (proposal Q2).
- Blocking the PR on red tests (proposal Q2: report only).

---

## 2. Architectural Design

### Overview
A stdlib-only **reporting kernel** lives next to the existing test-scope kernel
(`parrot/flows/dev_loop/test_scope/report.py`). Before each `PytestInvocation` is
executed, it appends `--junitxml=<tmp file>`. After the run, it parses that junit
file into a `SuiteResult` (suite = the invocation's `distribution`). It then
appends the result to a per-task JSON record under the report root:

```
<report_root>/<FEAT-ID>/<TASK-ID>.json        # default report_root: /tmp/claude-<uid>/sdd-tests
```

Both executors use it:
- `scripts/sdd/select_tests.py --run`, with new flags `--feature FEAT-<NNN>` and
  `--report-task TASK-<NNN>`. This is the sdd-worker fallback lane and `/sdd-done`.
- `ValidationSupervisor` (the `coder_run_validation` MCP tool). It already
  receives `feature` and `task_ids`, so it writes one record per task id.

A new CLI `scripts/sdd/test_report.py` does two things:
- `decide-rerun` prints `rerun` or `skip`, using the deterministic rule:
  `len(index["tasks"]) <= 10`.
- `render` aggregates every task record (plus an optional `rerun` record) into
  the Markdown table that `/sdd-done` pastes into the PR body.

A task with no record (tmp wiped, other machine, pre-feature task) is shown as
"no data". It never fails the command.

### Component Diagram
```
select_tests --run ─┐                         ┌─> <root>/<FEAT>/<TASK>.json
                    ├─> test_scope.report ────┤
ValidationSupervisor┘   (junit → SuiteResult) └─> <root>/<FEAT>/_rerun.json (sdd-done)
                                                          │
/sdd-done §4.7 ── test_report.py decide-rerun / render ───┘──> PR body "## Tests"
```

### Integration Points
| Existing | Change | Verified at |
|---|---|---|
| `select_tests.main()` run loop | append junit arg, record `SuiteResult` per invocation | `scripts/sdd/select_tests.py:108` |
| `ValidationSupervisor` spawn + `_record_invocation_outcome` | same, per invocation, written for every `task_ids` entry | `background.py:595`, `:757`, `:785` |
| `/sdd-done` §4 note + new §4.7 + §5 report line + §9.2 PR body | replace "skipped" note, add step, add table | `sdd-done.md:145`, `:180`, `:280`, `:560` |
| Codex twin `.agents/skills/sdd-done/SKILL.md` | mirror the same steps | `SKILL.md:197` |
| sdd-worker fallback lane (both twins) | pass `--feature/--report-task` | `sdd-worker.md:538` |

### Data Models (stdlib dataclasses — the kernel must stay Pydantic-free)
```python
@dataclass(frozen=True)
class SuiteResult:
    suite: str            # PytestInvocation.distribution ("ai-parrot", "root", …)
    tests: int            # junit total
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_s: float
    exit_code: int
    argv: tuple[str, ...] # exact pytest argv (incl. marker expression) that produced it
    status: str           # "ok" | "failed" | "timed_out" | "no_junit" | "report_parse_error" | "selection_error"

@dataclass(frozen=True)
class TaskTestRecord:
    feature_id: str
    task_id: str          # "TASK-NNN" | "_rerun"
    head_sha: str         # worktree HEAD when the run started
    base_ref: str         # selector base ref used for the plan
    tier: str             # task | merge | feature
    source: str           # "select_tests" | "coder_run_validation"
    attempts: int         # how many runs were recorded for this task (latest kept per suite)
    recorded_at: str      # ISO-8601 UTC
    suites: tuple[SuiteResult, ...]
```

### New Public Interfaces
- `parrot.flows.dev_loop.test_scope.report` (functions in §3 M1).
- CLI flags: `select_tests.py --feature`, `--report-task`.
- CLI `python -m scripts.sdd.test_report {decide-rerun,render}`.

---

## 3. Module Breakdown

#### Delegation-eligible modules
| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 report kernel | yes | skeleton below; stdlib only (`xml.etree`, `json`, `dataclasses`); atomic write via temp+`os.replace` | — |
| M2 select_tests wiring | yes | flags + call sites fixed below | — |
| M3 ValidationSupervisor wiring | yes | calls M1 at the two spawn sites + outcome hook | — |
| M4 test_report CLI | yes | subcommands + output format fixed in §2/§5 | — |
| M5 /sdd-done + twins + sdd-worker prompt | yes | text edits at the anchors in §6 | — |

### Module 1: Report kernel
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` (new)
- **Responsibility**: junit injection/parsing, record (de)serialization, report-root resolution, aggregation + Markdown rendering.
- **Depends on**: `test_scope.datatypes.PytestInvocation` (verified `datatypes.py:22`)
- **Interface Skeleton**:
  ```python
  REPORT_ROOT_ENV = "SDD_TEST_REPORT_DIR"
  RERUN_TASK_THRESHOLD = 10
  RERUN_RECORD = "_rerun"

  def report_root() -> Path:
      """$SDD_TEST_REPORT_DIR, else /tmp/claude-<uid>/sdd-tests (bound into the bwrap sandbox)."""
  def junit_path_for(feature_id: str, task_id: str, suite: str, ordinal: int) -> Path:
      """<root>/<feature>/junit/<task>--<suite>--<ordinal>.xml — unique per invocation (never shared)."""
  def with_junit(invocation: PytestInvocation, junit_path: Path) -> tuple[str, ...]:
      """Return a NEW argv with --junitxml=<junit_path>; never mutates invocation.argv."""
  def parse_junit(junit_path: Path, *, suite: str, exit_code: int, duration_s: float,
                  timed_out: bool = False) -> SuiteResult:
      """Sum <testsuite> counters; missing/unparseable file -> status 'no_junit' with zero counts."""
  def append_suite(feature_id: str, task_id: str, result: SuiteResult, *, head_sha: str,
                   tier: str, source: str) -> Path:
      """Merge into <root>/<feature>/<task>.json (same suite replaced, last write wins); atomic; flock-guarded."""
  def load_records(feature_id: str) -> dict[str, TaskTestRecord]:
      """All records of a feature, keyed by task id; corrupt files are skipped and reported in notes."""
  def should_rerun(task_count: int) -> bool:
      """task_count <= RERUN_TASK_THRESHOLD."""
  def render_markdown(records: dict[str, TaskTestRecord], task_ids: list[str],
                      *, rerun: TaskTestRecord | None, rerun_skip_reason: str | None) -> str:
      """'## Tests' section: per-suite rows (aggregate) + Total + optional re-run column + <details> per task."""
  ```
  Never write any I/O failure to stderr as fatal. Recording is best-effort and only logs a warning: it must never change a test run's exit code.

### Module 2: `select_tests.py` wiring
- **Path**: `scripts/sdd/select_tests.py` (modify)
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  parser.add_argument("--feature", default=None)      # after line 36 (--json)
  parser.add_argument("--report-task", default=None)  # TASK-NNN or "_rerun"
  parser.add_argument("--no-ledger", action="store_true")  # skip record_red_run/record_green_escalation (lines 115/123)
  # run loop (line 108): when both set → argv = report.with_junit(...); time the run;
  # report.append_suite(..., source="select_tests", tier=args.tier)
  ```
  When `--feature`/`--report-task` are absent, behaviour and argv are byte-identical to today.
  `--no-ledger` makes the run report-only: the escalation ledger (`kernel.context.record_red_run` / `record_green_escalation`, `select_tests.py:115`, `:123`) is not touched. `/sdd-done`'s re-run always passes it, so a closeout run never changes future selection state.
  An empty plan (no invocations) with `--report-task` set writes a record with zero suites and a `selection_error` note, instead of writing nothing.

### Module 3: `ValidationSupervisor` wiring
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` (modify)
- **Depends on**: M1
- **Contract**: at both `create_subprocess_exec` sites (595, 757), spawn the junit-augmented argv. In `_record_invocation_outcome` (785), or a sibling hook called next to it, parse the junit file and `append_suite` once per `task_ids` entry with `source="coder_run_validation"`. A timed-out invocation produces `status="timed_out"`. `feature` must be the FEAT id. If the passed `feature` is a slug, resolve it through the per-spec index header (`feature_id`).

### Module 4: `test_report` CLI
- **Path**: `scripts/sdd/test_report.py` (new); tests `tests/sdd_scripts/test_test_report.py` (new)
- **Interface**:
  ```
  python -m scripts.sdd.test_report decide-rerun --index sdd/tasks/index/<slug>.json
      → prints "rerun" or "skip (<N> tasks > 10)"; exit 0
  python -m scripts.sdd.test_report render --index <idx> [--out <file>]
      → Markdown "## Tests" section on stdout/file; exit 0 even with failures/no data
  ```
  It loads the kernel by path, the same way `select_tests.py:_load_kernel` does, and never runs `import parrot`.

### Module 5: Command text — `/sdd-done`, Codex twin, sdd-worker twins
- `.claude/commands/sdd-done.md`:
  - Replace the §4 "intentionally skipped" note.
  - Add **§4.7 Test Report**, between §4.6 and §5:
    1. Run `decide-rerun`.
    2. If the result is `rerun`, run the following in the background, wrapped in a process-level `timeout -k 10 <budget>`:
       `select_tests --tier feature --base origin/<base> --worktree "$WT" $(printf -- '--task-file %s ' <every task file from the per-spec index>) --feature FEAT-<ID> --report-task _rerun --no-ledger --timeout 300 --run`.
       Passing every task file means the run covers the union of all declared Validation Commands, not just mirror/core targets. A process timeout records `timed_out` and is non-blocking.
    3. Run `render --out "$WT/../.sdd-tests-FEAT-<ID>.md"`, or another tmp path.
  - Add a `Tests:` line to the §5 report.
  - Insert the rendered section into the §9.2 PR body, between `## Tasks` and the footer, and into the hotfix manual body.
- `.agents/skills/sdd-done/SKILL.md` **and** `.agent/workflows/sdd-done.md` (third mirror; its own "intentionally skipped" note is at `:124`, its PR body at `:440`): the same steps.
- The `gh` fallback (no `gh` / unauthenticated) and the hotfix manual command print `--body-file <rendered file>` instead of a placeholder body.
- `.claude/agents/sdd-worker.md` **and** `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md`: the fallback-lane `select_tests` line gains `--feature FEAT-<NNN> --report-task TASK-<NNN>`.

---

## 4. Test Specification

### Unit Tests (`packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py`, `tests/sdd_scripts/test_test_report.py`)
| Test | Asserts |
|---|---|
| `test_with_junit_does_not_mutate` | original argv unchanged, new argv ends with `--junitxml=…` |
| `test_parse_junit_counts` | fixture junit (pass/fail/error/skip) → exact counts |
| `test_parse_junit_missing_file` | `status="no_junit"`, zeros, no raise |
| `test_append_suite_replaces_same_suite` | re-run of same suite overwrites, other suites kept |
| `test_append_suite_atomic_concurrent` | two processes appending → valid JSON with both suites |
| `test_report_root_env_override` | `SDD_TEST_REPORT_DIR` wins; default under `/tmp/claude-<uid>` |
| `test_should_rerun_threshold` | 10 → True, 11 → False |
| `test_render_aggregates_by_suite` | 2 tasks × same suite → summed row; Total row correct |
| `test_render_no_data_tasks` | missing record → listed as "no data", no exception |
| `test_render_rerun_column` / `_skip_reason` | rerun column present, or "re-run skipped (N tasks > 10)" |
| `test_render_failures_marked` | failed>0 → ❌ in row, exit still 0 |
| `test_select_tests_flags_absent_is_identical` | no `--feature` → argv byte-identical (regression) |
| `test_select_tests_records` | with flags + a stub pytest writing junit → record written |
| `test_supervisor_records_per_task` | `ValidationSupervisor` with 2 task_ids → 2 records |
| `test_decide_rerun_cli` | index with 10/11 tasks → `rerun` / `skip (11 tasks > 10)` |

| `test_parse_junit_malformed` | bad XML → `report_parse_error`, zero counts, no raise |
| `test_parse_junit_xdist` | junit written under `-n 2` → counts equal the serial run |
| `test_junit_paths_unique_per_invocation` | 2 distributions → 2 distinct junit files |
| `test_empty_plan_selection_error` | no invocations + `--report-task` → record with `selection_error` |
| `test_no_ledger_skips_escalation_ledger` | `--no-ledger` → `record_red_run`/`record_green_escalation` not called (`tests/sdd_scripts/test_select_tests.py`) |
| `test_render_retries_not_double_counted` | same task+suite recorded twice → counted once (latest), `attempts=2` |
| `test_render_stale_marking` | `head_sha` ≠ final HEAD → "stale" |
| `test_supervisor_timeout_status` | timed-out invocation → `timed_out` (`test_background_validation.py`) |

Mirror parity: extend `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py` (and/or `tests/sdd_scripts/test_command_twin_parity.py`). All three `/sdd-done` mirrors must mention `test_report render` and `--no-ledger`, and both sdd-worker twins must mention `--report-task`.

---

## 5. Acceptance Criteria
- [ ] AC1: `select_tests --run --feature F --report-task T` writes `<root>/F/T.json` with one `SuiteResult` per invocation. Without those flags, behaviour is unchanged.
- [ ] AC2: `coder_run_validation` writes one record per `task_ids` entry with `source="coder_run_validation"`.
- [ ] AC3: The re-run decision is deterministic. ≤ 10 tasks in the per-spec index → re-run; > 10 → no re-run, and the PR states `re-run skipped (<N> tasks > 10)`.
- [ ] AC4: The PR body opened by `/sdd-done` (feature PR and the hotfix manual body) contains a `## Tests` table. The table has one row per suite (aggregate of all task records) with tests / passed / failed / skipped / errors / duration, plus a **Total** row. When a re-run happened, it has a "final HEAD re-run" column.
- [ ] AC5: The per-task breakdown appears in a collapsible `<details>` block. Tasks with no record are listed as "no data", and records whose `head_sha` ≠ the final HEAD are marked "stale".
- [ ] AC6: Red tests never block. `/sdd-done` still opens the PR, and `render`/`decide-rerun` exit 0.
- [ ] AC7: Recording failures (unwritable root, bad junit) never change a test run's exit code.
- [ ] AC8: Records live only under the report root (tmp). Nothing new is committed or written into the worktree.
- [ ] AC9: The kernel stays stdlib-only (importable by path, no `parrot`/pydantic import).
- [ ] AC10: All three `/sdd-done` mirrors (`.claude/commands`, `.agents/skills`, `.agent/workflows`) and both sdd-worker twins are updated; the parity tests pass.
- [ ] AC12: The closeout re-run passes every task file of the per-spec index plus `--no-ledger`. A re-run never mutates the escalation ledger.
- [ ] AC13: Every record carries `head_sha`, `base_ref` and the exact `argv`. Retries of the same task+suite count once (latest), with `attempts` shown. The Total row is labelled "per-task invocation totals — a test run by several tasks is counted once per task".
- [ ] AC11: All tests in §4 pass; `ruff check` is clean on touched files.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope import PytestInvocation, ScopePlan, changed_files, plan_tests  # test_scope/__init__.py:7-10
from parrot.flows.dev_loop.test_scope.select import changed_files, plan_tests  # background.py:46
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py
@dataclass(frozen=True)
class PytestInvocation:                       # line 22
    distribution: str                         # line 25
    argv: tuple[str, ...]  # starts with "pytest"   line 26
    targets: tuple[TestTarget, ...]

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py
def _invocation(distribution, targets, *, worktree, policy) -> PytestInvocation   # line 27; argv built line 42

# scripts/sdd/select_tests.py
def _load_kernel() -> ModuleType   # line 20 — imports test_scope by path, never `import parrot`
def _build_parser()                # line 29; --tier/--base/--task-file/--worktree/--run/--json/--timeout
def main(argv=None) -> int         # line 52; run loop: subprocess.run(argv, cwd=worktree) line 108

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py
_DEFAULT_BASE_REF = "origin/dev"   # line 74
class ValidationSupervisor:        # line 430
    async def start(self, *, feature: str, worktree: Path, execution_id: str, task_ids: list[str],
                    tier: Literal["merge","feature"], timeout_seconds: int, request_id: str,
                    base_ref: Optional[str] = None) -> BackgroundRegistration   # line 487
    async def _supervise(..., remaining_invocations, first_invocation, plan, worktree) -> None  # ~line 725
    async def _record_invocation_outcome(self, *, worktree, invocation, plan, exit_code: int) -> None  # line 785
    async def _await_one(...)      # line 816
# record fields: outcome Literal[completed|failed|timed_out|cancelled] line 190; exit_code line 191

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
class CoderRunValidationArgs(_Args):   # line 740 — feature: str, task_ids: List[str], tier, timeout_seconds, request_id
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `report.with_junit` | `PytestInvocation.argv` | new argv tuple | `datatypes.py:26` |
| `report.append_suite` | `select_tests.main` run loop | call after `subprocess.run` | `select_tests.py:108` |
| `report.append_suite` | `ValidationSupervisor._record_invocation_outcome` | call per task id | `background.py:785` |
| `test_report render` | `/sdd-done` §9.2 PR body | `$(cat <file>)` in heredoc | `sdd-done.md:560` |

### Does NOT Exist (Anti-Hallucination)
- ~~any pass/fail **count** field in sdd-coder evidence~~ — `TaskCompletionEvidence` (`optimization_models.py:205`) has `validation_refs`/`completion_facts` only. It is consumed by `scripts/sdd/finalize_task.py` (validates refs, renders a facts table). This feature does NOT extend it (results are tmp-only by decision; see §9 S1/S5).
- ~~junit/`--junitxml` handling anywhere in `test_scope/` or `select_tests.py`~~ — none.
- ~~`DevelopmentOutput.test_results`~~ — `models/base.py:510` has no test fields.
- ~~`scripts/sdd/test_report.py`, `test_scope/report.py`~~ — created by this feature.
- ~~a §4.7 in `/sdd-done`~~ — today the steps go §4.6 → §5.

### Edit Sites (Blueprint Anchors)
Verified against: `4c4ced166`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py` | CREATE | — | — | — |
| `scripts/sdd/test_report.py` | CREATE | — | — | — |
| `tests/sdd_scripts/test_test_report.py` | CREATE | — | — | — |
| `scripts/sdd/select_tests.py` | MODIFY | `    parser.add_argument("--json", action="store_true")` | `:36` | 1 |
| `scripts/sdd/select_tests.py` | MODIFY | `        result = subprocess.run(argv, cwd=worktree)` | `:108` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | `process = await asyncio.create_subprocess_exec(` (2 sites: `process =` and `next_process =`) | `:595`, `:757` | 2 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | `    async def _record_invocation_outcome(` | `:785` | 1 |
| `.claude/commands/sdd-done.md` | MODIFY | `**Note:** Test validation is intentionally skipped here` | `:145` | 1 |
| `.claude/commands/sdd-done.md` | MODIFY | `### 4.6. Verify E2E Evidence (FEAT-581)` (insert §4.7 before §5) | `:180` | 1 |
| `.claude/commands/sdd-done.md` | MODIFY | `E2E: <policy> — <status> (gate_satisfied: <bool>)` | `:280` | 1 |
| `.claude/commands/sdd-done.md` | MODIFY | `<N>/<total> tasks verified.` | `:560` | 1 |
| `.agent/workflows/sdd-done.md` | MODIFY | `**Note:** Test validation is intentionally skipped here` + `gh pr create \` | `:124`, `:440` | 1, 1 |
| `tests/sdd_scripts/test_select_tests.py` | MODIFY | (append tests) | — | — |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py` | MODIFY | (append tests) | — | — |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py` | MODIFY | (append mirror assertions) | — | — |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | ``    - If feature and no `--merge`, run `gh pr create --base <base_branch> --head <branch>`.`` | `:197` | 1 |
| `.claude/agents/sdd-worker.md` | MODIFY | ``--task-file sdd/tasks/active/TASK-<NNN>-<slug>.md --run > artifacts/logs/merge-tests-TASK-<NNN>.log 2>&1` `` | `:538` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | same line as above (twin) | `:538` | 1 |
| `tests/sdd_scripts/test_command_twin_parity.py` | MODIFY | (unverified — check before use) | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `select_tests.py:_load_kernel()`: the script side never imports `parrot`.
- Atomic publish = temp file + `os.replace`, guarded by `fcntl.flock` (same pattern as `sdd_coder/evidence.py`).
- `background.py` uses `self.logger`/module `logger`, never `print`. The CLIs keep the existing `# noqa: T201` convention.
- Twins: edit `.claude/...` and `.agents/...` / `_subagent_data/...` together (`git add -f` where git-ignored).

### Known Risks / Gotchas
- **bwrap private `/tmp`**: the sandbox mounts private temporary storage, except Claude Code's scratchpad root `/tmp/claude-<uid>`. A plain `$TMPDIR` default would lose sandboxed fallback-lane records. Hence the default root is `/tmp/claude-<uid>/sdd-tests`, and `SDD_TEST_REPORT_DIR` overrides it for other hosts.
- **Tmp is lossy by design**: a reboot, another machine, or tasks implemented before this feature → "no data" rows. This is accepted (proposal Q2). The re-run column, when present, is the authoritative number.
- **Stale records**: task records come from task-time HEADs. Merges and the §4.5 lint pass change the code afterwards, so rows whose `head_sha` ≠ the final HEAD are marked stale.
- **xdist (`-n auto`)**: junitxml works with xdist (the controller writes the file). Do not use `--junit-prefix`.
- **Timeouts**: a timed-out supervisor invocation has no complete junit → `status="timed_out"` with whatever counts were flushed (often zero).
- **Re-run cost**: bounded by the ≤ 10-task rule and run as a background Bash call (foreground calls cap at 120 s). It uses `--timeout` per test as in FEAT-617.
- **Overlapping suites**: several tasks often run the same test modules, so the aggregate is a sum of per-task invocations, not unique test cases. It is labelled as such (AC13). Only the re-run column is a unique-case count at the final HEAD.
- **Ledger side effects**: an unflagged `select_tests --run` updates the escalation ledger. The closeout re-run must pass `--no-ledger` (AC12).
- **PR body size**: per-task details go inside `<details>`. GitHub's limit (65 536 chars) is far above 10–40 tasks × a few suites.

### External Dependencies
None. stdlib `xml.etree.ElementTree`, `json`, `fcntl`, `dataclasses`. pytest's `--junitxml` is built in.

---

## 8. Open Questions
- [x] Data source — *Resolved in proposal*: both. Per-task recorded runs (aggregated) plus an authoritative feature-tier re-run in `/sdd-done`.
- [x] Do red tests block the PR? — *Resolved in proposal*: no, report only.
- [x] Table granularity — *Resolved in proposal*: per suite + Total row (per-task in `<details>`).
- [x] Re-run on large specs — *Resolved in proposal*: deterministic. Re-run only when the per-spec index has ≤ 10 tasks; > 10 → no re-run, and the table always shows the per-task aggregate.
- [x] Where per-task results live — *Resolved in proposal*: a temporary artifact under tmp. Spec detail: `/tmp/claude-<uid>/sdd-tests/<FEAT>/<TASK>.json`, because of the bwrap private-`/tmp` constraint (§7).

---

## Worktree Strategy
- Isolation: one feature worktree; the sdd-coder engine gives each task a sub-worktree.
- Module graph: M2 → M1, M3 → M1, M4 → M1 (all import `test_scope.report`). M5 depends on M2 (flag names) and M4 (CLI names). M2, M3 and M4 run concurrently after M1.
- Shared files: none between modules (M5 owns all `.md` edits).
- Exclusive resources: none.
- Cross-feature dependencies: none. Re-grep `sdd-done.md` anchors at task time (it changed on dev on 2026-10-16: `4f81859a9`).

---

## 9. Design Research Cross-Check
Model: gpt-5.6-luna · Status: completed · transcript `sdd/state/FEAT-695/design_research/`

| # | Suggestion | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Typed, versioned result model in `TaskCompletionEvidence` | REJECT | Results are tmp-only by user decision. A typed stdlib `SuiteResult`/`TaskTestRecord` with explicit statuses covers the zero/unknown/failed distinction. | §2 Data Models |
| S2 | Per-invocation junit paths, not one shared path | CONFIRM | Verified: `select_tests.py:108` runs one subprocess per distribution. | §3 M1 `junit_path_for` |
| S3 | Pass every task file to the closeout feature run | CONFIRM | Verified: declared targets come only from `--task-file` (`select_tests.py` main). | §3 M5, AC12 |
| S4 | Bind reports to head_sha/base_ref/argv | CONFIRM | Needed for stale marking. | §2 Data Models, AC13 |
| S5 | Persist via `ExecutionEvidenceStore` durably | REJECT | Contradicts the resolved decision: results are a temporary artifact under tmp. | — |
| S6 | Closeout run must not mutate the escalation ledger | CONFIRM | Verified: `select_tests.py:115`/`:123`. | §3 M2 `--no-ledger`, AC12 |
| S7 | Explicit timeout/parse/selection states; process timeout | CONFIRM | `--timeout` is per-test only. | §2 statuses, §3 M5 `timeout -k` |
| S8 | Retry/overlap semantics before totals | CONFIRM | Latest per task+suite, `attempts`, labelled totals. | AC13, §7 |
| S9 | Adversarial parser/closeout tests | CONFIRM | — | §4 |
| S10 | Use selector cost signals instead of a 10-task cutoff | REJECT | The user explicitly chose a deterministic task-count rule. Its "say not_run with reason" part was already in AC3. | — |
| S11 | Cover the third mirror `.agent/workflows/sdd-done.md`; fallback prints the real body | CONFIRM | Verified: the file exists, with a note at `:124`. | §3 M5, AC10 |
