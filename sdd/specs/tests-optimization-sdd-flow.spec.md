---
type: feature
base_branch: dev
projects: [dev-loop, sdd-tooling, ci]
tags: [test-selection, validation-contract, sdd-done, sdd-worker, ci]
---

# Feature Specification: Tests Optimization in the SDD Flow (spec-declared Validation Contract)

**Feature ID**: FEAT-699
**Date**: 2026-10-18
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 0.30.0

---

## 1. Motivation & Business Requirements

### Problem Statement

`sdd-worker` (merge tier, after every chunk merge), every `sdd-coder` seat
(task tier) and `/sdd-done` (feature tier re-run and lint-fix checks) each run
pytest through the FEAT-563 test-scope kernel. For a real feature the
accumulated cost is very large. `/sdd-done` for FEAT-698 (15 tasks, PR #1715)
reported 11,272 test executions over ~22 minutes of pytest wall clock — yet
the full suite was *never* run and no escalation fired. Reproducing the plans
on the FEAT-698 tip showed the merge tier selecting **2,990** tests per merge
(directory mirror + depth-1 import impact) and the feature tier **2,562**
(a whole `tests/flows/dev_loop` directory). The root causes, measured
2026-10-18:

1. **Breadth by heuristic** — directory-level mirror + depth-1 import impact
   select thousands of tests the feature's author never declared relevant.
   Nothing lets the spec say "these are the integration tests that matter".
2. **Redundancy across merges** — each merge re-runs tests whose test file and
   imported sources are unchanged since a previous green run in the same
   feature (15× re-execution on FEAT-698). The FEAT-604 ledger dedupes only
   *suite escalations*, not ordinary selected tests.
3. **Verdict noise** — ~100 tests are red on the `dev` baseline; they fail
   every run, so a red table does not mean the feature broke anything.
4. **No real safety net** — `.github/workflows/ci.yml` runs only the repo-root
   `tests/`; **no `packages/*/tests` suite runs in CI at all**. Narrowing
   local selection without a net would hide regressions.

### Goals

- A spec-declared **Validation Contract** (explicit pytest operands +
  optional markers) that **replaces** heuristic breadth and suite escalation
  in all four phases: task (`sdd-coder`), merge (`sdd-worker`), feature
  (`/sdd-done`), and `qa-runner`/autopilot QA.
- **Bounded fallback** when no contract exists: tasks' own tests +
  file-level direct (depth-1) importers — never a whole suite, always noted.
- **Green cache**: a test file already green in this feature, whose own blob
  and dependency fingerprint are unchanged, is skipped and reported `cached`.
- **Baseline-aware verdict**: the gate fails only on tests that pass on
  `origin/<base_branch>` and fail on the branch (*new reds*).
- **Nightly full-suite safety net** on `dev` covering every
  `packages/*/tests` + root `tests/` — coverage that does not exist today.
- Targets: merge-tier validation **< 2 min**; `/sdd-done` feature tier
  **< 5 min**.
- Deterministic, stdlib-only kernel (`test_scope/__init__.py` is imported by
  path from the system-python native hook — no Pydantic there).
- Backward compatible: specs/tasks/indexes written before this feature keep
  working via the fallback path; `guard.py` keeps rewriting broad pytest.

### Non-Goals (explicitly out of scope)

- **Coverage-guided selection (`pytest-testmon`)** — rejected in brainstorm
  Option C (stateful, opaque, fights the multi-worktree shared-venv setup);
  see `sdd/proposals/tests-optimization-sdd-flow.brainstorm.md`.
- **Per-PR CI for package suites** — the net is nightly, not per-push.
- **`/sdd-brief` (hotfix/fix) flows** — briefs keep today's behaviour plus
  the bounded fallback; no contract field in brief indexes in v1.
  `ValidationSupervisor` accepts only `TASK-*` ids today (design research
  S10); extending contracts to `HOTFIX-*` flows is follow-up work.
- Changing the FEAT-563 rule that an agent-issued command may never run a
  full suite — it is preserved, not relaxed.
- Removing the FEAT-604 escalation ledger — it stays for legacy/fallback
  plans; the green cache is a sibling store, not a replacement.

---

## 2. Architectural Design

### Overview

The feature's spec becomes the authority on what must be tested. Spec §4
gains a `### Validation Contract` subsection listing explicit pytest
operands (`path` or `path::nodeid`) and optional registered marker names;
an empty contract is allowed but must be explicit (`none — fallback`).
`/sdd-task` parses it once and caches it into the per-spec index header as a
**versioned structured payload** (`test_contract`, distinct from the existing
FEAT-563 `validation_contract: "required"` lint flag — a verified naming
collision), so the kernel never parses the spec at runtime and a malformed
payload fails closed rather than silently falling back (design research S3).

Contract presence is an **explicit selector mode** in `plan_tests()` (S1):

- **contract mode** (a `test_contract` header exists): task tier = task's
  declared commands ∪ file-level mirror; merge tier = chunk tasks' declared
  ∪ contract ∪ file-level mirror; feature tier = all tasks' declared ∪
  contract ∪ file-level mirror. No import-impact selection, no core/cap
  suite escalation — a `CORE_PATHS` change becomes a plan note
  ("core change — covered by nightly").
- **fallback mode** (no contract): tasks' declared ∪ file-level mirror ∪
  depth-1 direct importers at file level, capped; cap overflow → note,
  never a suite.

Mirror resolution becomes file-level everywhere (`foo.py` → an existing
`test_foo.py`); the `deepest_existing_dir` directory walk-up is no longer
used by tier planning. Marker composition moves into the invocation planner:
an explicitly declared contract operand overrides the `integration`/`e2e`
exclusions in `AGENT_MARKER_EXPRESSION` (declaring it IS the opt-in), while
`real_llm` is never overridden and is lint-flagged (decision at spec
kickoff; S4).

Two cross-cutting mechanisms make the verdict cheap and honest:

- **Green cache** (new `green_cache.py`): after a run, each test file whose
  nodes are all green-or-known-baseline-red records a content key (test
  blob, conftest chain, depth≤1 imported source blobs, execution manifest,
  marker expression, Python version). Unchanged keys are dropped from later
  plans and reported `cached`. The store is feature-scoped, versioned, and
  lock-protected (S6, S7); evidence is **node-level** junit data, failing
  closed to a miss when mapping is unavailable (S5). The feature tier at
  `/sdd-done` bypasses the cache by default so the closeout table is a real
  end-to-end run (`--use-cache` is the explicit opt-in; S9).
- **Baseline-aware verdict** (new `baseline.py`): on failure, only the
  failed nodeids are re-run inside a temporary detached checkout of
  `origin/<base_branch>` prepared by an explicit, tested contract that
  copies the compiled Cython artifacts (e.g. `parrot.utils.types` `.so`)
  from the main checkout (decision at kickoff; S8). Each failure is
  classified *new red* (passes on base) / *baseline red* / *unknown*
  (unbuildable baseline ⇒ treated as failure, said so in the report). The
  gate fails only on new reds.

The safety net is a new nightly workflow on `dev` running an explicit
matrix of every `packages/*/tests` suite plus root `tests/`, uploading
junit + a red-set summary artifact per distribution; it never mutates the
repository (S12).

### Component Diagram

```
spec §4 "### Validation Contract"
        │  /sdd-task (parse once, lint via check_task_graph)
        ▼
per-spec index header: test_contract {schema, tests[], markers[], digest}
        │ read by
        ▼
plan_tests(contract=…) ── mode: contract | fallback
   │            │
   │            ├─ mirror.py (file-level only)
   │            ├─ impact.py (fallback mode only, depth-1, capped)
   │            └─ planner.py (per-invocation marker composition)
   ▼
ScopePlan ──► green_cache.filter_cached() ──► runner (CLI --run / supervisor)
   callers: scripts/sdd/select_tests.py · guard._task_plan ·
            ValidationSupervisor._plan_selection (engine run_validation)
                                   │ junit (node-level)
                                   ▼
             report.py ◄── baseline.classify_failures() (temp checkout of
             (new-red / baseline-red / cached / unknown rows)   origin/<base>)

.github/workflows/nightly-tests.yml (matrix: every packages/*/tests + root)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `plan_tests()` (`test_scope/select.py:132`) | extends | gains `contract:` input and the two selector modes |
| `pytest_target_for()` (`test_scope/mirror.py:38`) | modifies | file-level resolution; tier planning stops calling `deepest_existing_dir` (`mirror.py:84`) |
| invocation planner (`test_scope/planner.py:42`) | modifies | per-invocation marker composition replaces the unconditional `-m AGENT_MARKER_EXPRESSION` |
| `ValidationSupervisor._plan_selection` (`sdd_coder/background.py:718-728`) | modifies | today calls `plan_tests` with **no** `declared` (verified) — must pass chunk/feature declared commands + contract |
| `run_validation` (`sdd_coder/engine.py:1149`) / `coder_run_validation` (`sdd_coder/toolkit.py:602`) | uses | index already re-read per call (`_resolve_feature`, `engine.py:1487-1544`); contract rides the header |
| `guard._task_plan` (`test_scope/guard.py:44`) | modifies | passes the contract so rewritten broad pytest matches the plan |
| escalation ledger (`test_scope/context.py`) | extends | green-cache store lives beside it, same atomic-write style + locking |
| `parse_junit` / `render_markdown` (`test_scope/report.py`) | modifies | node-level statuses; new table columns (new red / baseline red / cached) |
| `scripts/sdd/select_tests.py`, `scripts/sdd/test_report.py` | modifies | CLI flags and rendering for contract, cache, baseline |
| `scripts/sdd/check_task_graph.py:225` | extends | contract operand lint (exists on disk, `real_llm` flag, malformed payload) |
| per-spec index header (`sdd/tasks/index/*.json`) | extends | new optional `test_contract` object — the existing `validation_contract: "required"` string is a DIFFERENT field and stays untouched |
| `.github/workflows/` | new | `nightly-tests.yml` |

### Data Models

```python
# test_scope/datatypes.py — stdlib dataclasses only (kernel constraint)

@dataclass(frozen=True)
class TestContract:
    """Normalized spec-declared validation contract (index header `test_contract`)."""
    schema: int                 # payload version; unknown version ⇒ fail closed
    tests: tuple[str, ...]      # pytest operands: repo-relative path or path::nodeid
    markers: tuple[str, ...]    # registered marker names (never real_llm)
    digest: str                 # sha256 of the normalized payload (cache namespace input)

@dataclass(frozen=True)
class GreenCacheEntry:
    """One cached-green test file within a feature's worktree."""
    test_file: str              # repo-relative
    key: str                    # sha256(test blob, conftest chain, dep blobs ≤ depth 1,
                                #        execution manifest, marker expr, python x.y)
    recorded_at: str            # UTC ISO-8601

@dataclass(frozen=True)
class BaselineVerdict:
    nodeid: str
    status: str                 # "new_red" | "baseline_red" | "unknown" | "flaky"
    detail: str = ""            # e.g. why the baseline was unbuildable
```

Index header payload (written by `/sdd-task`, read by the kernel):

```json
"test_contract": {
  "schema": 1,
  "tests": ["packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py", "…::test_node"],
  "markers": [],
  "digest": "sha256:…"
}
```

### New Public Interfaces

See the Interface Skeletons in §3 — `parse_spec_contract()`,
`plan_tests(contract=…)`, `green_cache.filter_cached()/record_green()`,
`baseline.classify_failures()`, and the `select_tests.py` flags
(`--use-cache`/`--fresh`, `--baseline/--no-baseline`).

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Authoring surface | yes | subsection format + index payload fixed below; doc edits are mechanical | |
| M2: Contract model & lint | yes | dataclass + parser signatures fixed; fail-closed rules enumerated | |
| M3: Selector modes | no | — | interplay of tiers/modes/marker composition needs the thinking model |
| M4: Green cache | no | — | key composition and fail-closed edges are correctness-critical |
| M5: Baseline verdict | no | — | checkout preparation contract and unknown-handling are new ground |
| M6: Entry-point wiring | yes | all call sites verified with line anchors; signatures fixed | |
| M7: Command/agent docs | yes | wording changes driven by M3–M6 semantics | |
| M8: Nightly workflow | yes | matrix enumerated; artifact names fixed | |

### Module 1: Authoring surface (template + command docs)
- **Path**: `sdd/templates/spec.md`, `.claude/commands/sdd-spec.md`,
  `.claude/commands/sdd-task.md` (+ twins `.agent/workflows/sdd-spec.md`,
  `.agent/workflows/sdd-task.md`, `.agents/skills/sdd-spec/`, `.agents/skills/sdd-task/`)
- **Responsibility**: add the `### Validation Contract` subsection to spec §4
  (between "### Integration Tests" and "### Test Data / Fixtures");
  `/sdd-spec` proposes an initial contract from the Module Breakdown +
  existing tests; `/sdd-task` caches it into the index header and makes each
  task's `## Validation Commands` list that task's own test files.
- **Depends on**: M2 (payload format).
- **Interface Skeleton** *(authoring format — the template subsection)*:
  ```markdown
  ### Validation Contract

  > Explicit pytest operands that gate this feature in ALL tiers (FEAT-699).
  > `none — fallback` is allowed but must be written out. Never `real_llm` tests.

  tests:
  - packages/<dist>/tests/path/test_file.py
  - packages/<dist>/tests/path/test_file.py::test_node
  markers:
  - <registered-marker>   # optional
  ```

### Module 2: Contract model, parsing, index cache & lint
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py`,
  `.../test_scope/contract.py`, `scripts/sdd/check_task_graph.py`
- **Responsibility**: `TestContract` dataclass; parse the spec subsection;
  read/validate the index header payload (unknown `schema` or malformed
  payload ⇒ `None` + hard note, never silent fallback — S3); lint operands.
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # test_scope/datatypes.py  (modifies; anchor class LedgerEntry: datatypes.py:63)
  @dataclass(frozen=True)
  class TestContract: ...        # fields as in §2 Data Models

  # test_scope/contract.py  (modifies contract.py; parse_validation_commands verified: contract.py:63)
  SPEC_CONTRACT_HEADING: str = "### Validation Contract"
  def parse_spec_contract(spec_md: str) -> TestContract | None:
      """Parse §4's subsection. Returns None for an explicit `none — fallback`;
      raises ValueError on a malformed subsection (fail closed)."""
  def contract_from_index_header(header: Mapping[str, object]) -> TestContract | None:
      """Validate the cached `test_contract` payload. Unknown schema/shape ⇒
      raises ValueError — callers surface it, never downgrade to fallback silently."""

  # scripts/sdd/check_task_graph.py  (extends; anchor _check_validation_contract: check_task_graph.py:225)
  def _check_test_contract(index: Mapping[str, object], root: Path) -> list[Finding]:
      """Error: operand file missing on disk, real_llm-marked operand, malformed payload.
      Warning: contract declared but a task's own tests not in any operand's files."""
  ```

### Module 3: Selector modes (contract-aware kernel)
- **Path**: `.../test_scope/select.py`, `.../test_scope/mirror.py`,
  `.../test_scope/planner.py`, `.../test_scope/policy.py`
- **Responsibility**: the two explicit selector modes (S1); file-level mirror;
  per-invocation marker composition with the override-except-`real_llm` rule
  (S4); fallback mode bounded (cap ⇒ note, never suite).
- **Depends on**: M2 (`TestContract`).
- **Interface Skeleton**:
  ```python
  # test_scope/select.py  (modifies plan_tests, verified: select.py:132)
  def plan_tests(*, worktree: Path, changed_files: Sequence[str], tier: str,
                 declared: Sequence[Sequence[str]] = (),
                 contract: TestContract | None = None,
                 policy: ScopePolicy | None = None) -> ScopePlan:
      """contract mode: declared∪contract∪file-mirror, no impact, no escalation
      (CORE_PATHS hit ⇒ note). fallback mode: declared∪file-mirror∪depth-1
      file-level importers, capped ⇒ note. Mirror never returns a directory."""

  # test_scope/mirror.py  (modifies; pytest_target_for verified: mirror.py:38)
  def pytest_file_target_for(path: str, worktree_path: str) -> str | None:
      """File-level only: src file → existing test_<name>.py, else None.
      deepest_existing_dir (mirror.py:84) is no longer called by tier planning."""

  # test_scope/planner.py  (modifies the invocation builder, anchor planner.py:42)
  def marker_expression_for(targets: Sequence[str], *, contract: TestContract | None,
                            policy: ScopePolicy) -> str:
      """Per-invocation composition: contract-declared operands drop the
      `not integration` / `not e2e` clauses; `not real_llm` is always kept."""
  ```

### Module 4: Green cache
- **Path**: `.../test_scope/green_cache.py` (new), `.../test_scope/context.py`,
  `.../test_scope/report.py`
- **Responsibility**: content-addressed per-test-file skip across merges in a
  feature; node-level evidence (S5); invalidation beyond imports via an
  execution manifest — conftest chain, `pyproject` pytest options, marker
  expression, Python `x.y` — unknown inputs ⇒ miss (S6); feature-scoped,
  versioned, lock-protected store beside the escalation ledger (S7).
- **Depends on**: M3 (plan shape), M2 (contract digest in the namespace).
- **Interface Skeleton**:
  ```python
  # test_scope/green_cache.py  (new file)
  def cache_namespace(*, feature_id: str, base_ref: str, contract_digest: str) -> str:
      """Store key prefix; any component change invalidates the whole namespace."""
  def filter_cached(worktree: Path, plan: ScopePlan, *, namespace: str) -> tuple[ScopePlan, tuple[str, ...]]:
      """Drop cached-and-unchanged test files from the plan; returns (plan, cached_files).
      Node-mapping unavailable for a file ⇒ that file is NEVER dropped (fail closed)."""
  def record_green(worktree: Path, *, namespace: str, junit_nodes: Mapping[str, str],
                   baseline_reds: Collection[str]) -> None:
      """Record files whose nodes are all green-or-baseline-red. Lock-protected
      read-modify-write (same pattern as report.py's lock)."""

  # test_scope/report.py  (modifies parse_junit, verified: report.py:111)
  def parse_junit(...) -> SuiteResult:
      """Extended: retains canonical per-node statuses, not only aggregates."""
  ```

### Module 5: Baseline-aware verdict
- **Path**: `.../test_scope/baseline.py` (new), `.../test_scope/report.py`,
  `scripts/sdd/test_report.py`
- **Responsibility**: re-run only failed nodeids on `origin/<base_branch>` in
  a temporary detached checkout prepared by an explicit contract (git
  worktree + copy compiled `.so` artifacts from the main checkout — no such
  mechanism exists in lifecycle code today, S8); classify new-red /
  baseline-red / unknown / flaky; gate on new reds only; render the split.
- **Depends on**: M4's node-level junit evidence.
- **Interface Skeleton**:
  ```python
  # test_scope/baseline.py  (new file)
  def prepare_baseline_checkout(*, repo_root: Path, base_ref: str, scratch: Path) -> Path:
      """Detached `git worktree add` of base_ref + copy compiled artifacts
      (parrot/utils/*.so) from repo_root. Raises BaselineUnavailable when the
      checkout cannot be made runnable (callers classify affected nodes `unknown`)."""
  def classify_failures(*, repo_root: Path, base_ref: str,
                        failed_nodeids: Sequence[str], timeout_s: int) -> tuple[BaselineVerdict, ...]:
      """Run ONLY failed_nodeids on the baseline checkout. unknown ⇒ failure.
      Cost is proportional to failures, never to the suite."""

  # test_scope/report.py  (modifies render_markdown, verified: report.py:289)
  def render_markdown(...) -> str:
      """Table gains: new red / baseline red / cached / unknown columns-rows;
      the verdict line states the gate = new reds (+ unknowns) only."""
  ```

### Module 6: Entry-point wiring (CLI, supervisor, guard)
- **Path**: `scripts/sdd/select_tests.py`, `scripts/sdd/test_report.py`,
  `.../sdd_coder/background.py`, `.../sdd_coder/engine.py`,
  `.../sdd_coder/toolkit.py`, `.../test_scope/guard.py`
- **Responsibility**: every validation entry point loads the index header
  once and passes `declared` + `contract` into `plan_tests` (S2 — today
  `ValidationSupervisor._plan_selection` at `background.py:728` passes
  neither); CLI flags: `--use-cache/--fresh` (feature tier defaults fresh,
  S9), `--baseline/--no-baseline`; `guard._task_plan` passes the contract.
- **Depends on**: M2–M5.
- **Interface Skeleton**:
  ```python
  # sdd_coder/background.py  (modifies _plan_selection, verified: background.py:718-728)
  async def _plan_selection(self, *, worktree: Path, tier: str, base_ref: str,
                            task_ids: Sequence[str]) -> ScopePlan:
      """Reads the per-spec index: declared = the tasks' Validation Commands;
      contract = contract_from_index_header(header). Passes both to plan_tests."""

  # scripts/sdd/select_tests.py  (modifies main; anchor --tier add_argument: select_tests.py:32)
  #   new flags: --use-cache / --fresh (fresh is the default for --tier feature),
  #              --baseline / --no-baseline (default on when --run and failures occur),
  #              --index <per-spec index> (explicit header source; default: resolve like the engine)
  ```

### Module 7: Command & agent documentation
- **Path**: `.claude/commands/sdd-done.md`, `.claude/agents/sdd-worker.md`,
  `.claude/agents/qa-runner.md`, `.claude/agents/sdd-coder.md` (+ the
  `.agent/workflows/` and `_subagent_data/` twins where they exist)
- **Responsibility**: `/sdd-done` table documents the new columns and the
  always-fresh closeout run; revisit the `RERUN_TASK_THRESHOLD` skip (§8);
  `sdd-worker`/`qa-runner`/`sdd-coder` wording: contract-driven plans,
  `cached` rows, new-red gate.
- **Depends on**: M3–M6 semantics frozen.

### Module 8: Nightly package-suite workflow
- **Path**: `.github/workflows/nightly-tests.yml` (new)
- **Responsibility**: cron on `dev`; an **explicit matrix** enumerating every
  `packages/*/tests` tree + root `tests/`, each installing its distribution's
  required extras; junit + red-set summary artifact per distribution; the
  workflow fails on new reds vs the previous nightly artifact; it never
  mutates the repository (no ledger commits from CI — S12).
- **Depends on**: nothing in M2–M6 (independent track).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_parse_spec_contract_roundtrip` | M2 | subsection → `TestContract`; explicit `none — fallback` → `None` |
| `test_contract_from_index_fail_closed` | M2 | unknown `schema` / malformed payload raises, never silent fallback |
| `test_check_test_contract_lint` | M2 | missing operand file = error; `real_llm` operand = error; legacy `validation_contract: "required"` untouched |
| `test_plan_contract_mode_no_escalation` | M3 | contract present + `CORE_PATHS` change ⇒ note, no suite, no impact targets |
| `test_plan_fallback_bounded` | M3 | no contract: depth-1 file-level importers, cap ⇒ note, never a directory/suite |
| `test_mirror_file_level_only` | M3 | changed `foo.py` → `test_foo.py` or nothing; never a directory |
| `test_marker_override_composition` | M3 | declared integration/e2e operand runs; `not real_llm` always kept |
| `test_green_cache_key_and_invalidation` | M4 | conftest / pyproject options / marker expr / python version change ⇒ miss |
| `test_green_cache_fail_closed` | M4 | missing node mapping ⇒ file never dropped |
| `test_green_cache_concurrent_writes` | M4 | two writers, lock held: no lost entries (S7) |
| `test_baseline_classification` | M5 | new-red vs baseline-red vs unknown; unknown gates as failure |
| `test_baseline_unbuildable_checkout` | M5 | `BaselineUnavailable` ⇒ all affected nodes `unknown`, report says why |
| `test_report_columns` | M5 | render shows new red / baseline red / cached / unknown |

### Integration Tests
| Test | Description |
|---|---|
| `test_supervisor_passes_declared_and_contract` | `ValidationSupervisor._plan_selection` feeds task declarations ∪ contract into `plan_tests` (closes the verified `background.py:728` gap, S2/S11) |
| `test_second_merge_uses_cache` | two merge-tier runs in one feature: second plan reports the unchanged green file as `cached` |
| `test_feature_tier_fresh_by_default` | `--tier feature` ignores the cache unless `--use-cache` (S9) |
| `test_guard_rewrites_to_contract_plan` | `guard._task_plan` output matches the contract-mode plan |
| `test_legacy_index_fallback` | index without `test_contract`: fallback mode + explicit note, behaviour otherwise unchanged |
| `test_branch_only_test_on_baseline` | a test file that exists only on the branch classifies as new red, not unknown (S11) |

### Test Data / Fixtures
```python
@pytest.fixture
def feature_worktree(tmp_path):
    """Hermetic git repo + worktree with a per-spec index carrying a
    test_contract header, two task files with Validation Commands, and a
    fake origin/<base> ref for baseline classification."""
```

### Validation Contract

> Explicit pytest operands that gate this feature in ALL tiers (FEAT-699 —
> this spec is its own first consumer).

tests:
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py
- tests/sdd_scripts/test_check_task_graph.py
markers: none

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `sdd/templates/spec.md` §4 carries the `### Validation Contract`
      subsection; `/sdd-spec` proposes one; empty is explicit, never implied.
- [ ] `/sdd-task` caches the contract as the versioned `test_contract` index
      header object; the FEAT-563 `validation_contract: "required"` flag is
      untouched and still honoured by `check_task_graph.py`.
- [ ] `check_task_graph.py` errors on a contract operand missing from disk,
      on a `real_llm`-marked operand, and on a malformed payload.
- [ ] With a contract: merge plan = chunk tasks' declared ∪ contract ∪
      file-level mirror — zero import-impact targets, zero suite escalations,
      `CORE_PATHS` hits demoted to a note (asserted by tests).
- [ ] Without a contract: bounded fallback (file-level depth-1 importers,
      cap ⇒ note), never a directory or suite, and the plan says so.
- [ ] Mirror returns only files in tier planning, never a directory.
- [ ] A contract operand under `integration/`/`e2e` runs (exclusion
      overridden per invocation); `not real_llm` is always preserved.
- [ ] Second merge-tier run in a feature skips unchanged green test files and
      reports them `cached`; conftest/pyproject/marker/python changes
      invalidate; concurrent writers lose nothing.
- [ ] Gate verdict = new reds (+ unknowns) only; baseline reds are reported
      but do not fail the gate; baseline cost ∝ number of failures.
- [ ] `/sdd-done` feature tier runs fresh by default (`--use-cache` opt-in)
      and its table shows new red / baseline red / cached / unknown.
- [ ] `ValidationSupervisor._plan_selection` passes task declarations and the
      contract into `plan_tests` (gap at `background.py:728` closed).
- [ ] `.github/workflows/nightly-tests.yml` runs every `packages/*/tests` +
      root `tests/` nightly on `dev`, uploads junit + red-set artifacts per
      distribution, and never pushes/commits to the repository.
- [ ] Replaying the FEAT-698 plans with a representative contract yields a
      merge-tier run < 2 min and a feature-tier run < 5 min (evidence in
      `artifacts/logs/`).
- [ ] Legacy specs/indexes keep working (fallback mode) — no breaking change;
      `test_scope/__init__.py` remains stdlib-only importable by path.
- [ ] All §4 tests pass; `ruff check` clean on touched files.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor** (verified 2026-10-18 at `4754028cb`;
> line numbers re-checked, all `grep -c` occurrence counts = 1 unless noted)

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope import (  # test_scope/__init__.py:7-10
    AttemptContext, CoreHit, LedgerEntry, PytestInvocation, ScopePlan, TestTarget,
    VALIDATION_HEADING, changed_files, is_broad_pytest, parse_validation_commands,
    plan_tests, pytest_target_for, pytest_targets,
)
from parrot.flows.dev_loop.test_scope.select import changed_files, plan_tests  # background.py:48 does this
from parrot.flows.dev_loop.task_scheduler import TaskScheduler, iter_index_files  # engine.py:53
# NOTE: test_scope/__init__.py is stdlib-only and imported BY PATH as top-level
# `test_scope` from the native hook and scripts/sdd/*.py — never import Pydantic there.
```

### Existing Class Signatures
```python
# test_scope/select.py
def changed_files(worktree: Path, base_ref: str) -> list[str]:                      # line 23
def _declared_targets(declared, notes, *, worktree) -> list[str]:                   # line 100
def plan_tests(*, worktree, changed_files, tier, declared=(), policy=None) -> ScopePlan:  # line 132

# test_scope/mirror.py
def pytest_targets(files: Sequence[str], worktree_path: str) -> list[str]:          # line 10
def pytest_target_for(path: str, worktree_path: str) -> str | None:                 # line 38
def deepest_existing_dir(tests_root, subdirs, worktree_path) -> str:                # line 84 — the directory walk-up to retire from tier planning

# test_scope/planner.py — invocation builder
# line 42: argv = ("pytest", *AGENT_FLAGS, "-m", policy.marker_expression, *xdist, *extra, *kept_paths)
#   ^ the unconditional marker injection M3 replaces with per-invocation composition

# test_scope/policy.py
AGENT_MARKER_EXPRESSION: str = "not e2e and not real_llm and not integration"       # line 7
DEFAULT_IMPACT_CAP: int = 150                                                       # line 9
DEFAULT_IMPACT_DEPTH: int = 1                                                       # line 10
CORE_PATHS: tuple[str, ...]                                                         # line 16 (FEAT-620, regenerated by scripts/sdd/regen_core_paths.py)
class ScopePolicy:                                                                  # line 82 (impact_cap :85, impact_depth :86, marker_expression :100)

# test_scope/datatypes.py
class PytestInvocation:  # line 22
class ScopePlan:         # line 42 (tier, invocations, escalated, core_hits, skipped_escalations, notes, cap_hits, cap_impacted)
class LedgerEntry:       # line 63 (distribution, core_blobs, impact_blobs, impacted_hash)
class AttemptContext:    # line 73

# test_scope/context.py
def _atomic_write_json(path: Path, payload: object) -> None:                        # line 31
def _blob(worktree: Path, path: str) -> str | None:                                 # line 74
def read_ledger(worktree: Path) -> dict[str, LedgerEntry]:                          # line 82
def record_green_escalation(...):                                                   # line 124
def record_red_run(worktree: Path, hit_dists: Sequence[str]) -> None:               # line 150
def pending_escalations(...) -> tuple[list[str], list[str]]:                        # line 170 — UNLOCKED read-modify-write today (S7)

# test_scope/report.py
RERUN_TASK_THRESHOLD = 10                                                           # line 30
def parse_junit(...):                                                               # line 111 — aggregates only today (S5)
def append_suite(...):                                                              # line 186
def load_records(feature_id: str) -> tuple[dict[str, TaskTestRecord], list[str]]:   # line 235
def should_rerun(task_count: int) -> bool:                                          # line 258 (return task_count <= RERUN_TASK_THRESHOLD :260)
def render_markdown(...):                                                           # line 289

# test_scope/contract.py
VALIDATION_HEADING: str = "## Validation Commands"                                  # line 10
def parse_validation_commands(task_md: str) -> list[list[str]]:                     # line 63
def is_broad_pytest(argv, *, worktree=None) -> bool:                                # line 143

# test_scope/impact.py
class ImportIndex:                                                                  # line 112 (load_or_build :172)
def impacted_tests(index, changed, *, worktree, depth) -> list[str]:                # line 234
def detect_core(index, changed, *, policy) -> list[CoreHit]:                        # line 264

# test_scope/guard.py
def _task_plan(worktree: Path) -> ScopePlan | None:                                 # line 44 (calls plan_tests at :54)
def guard_argv(argv, *, worktree) -> GuardOutcome:                                  # line 62
def guard_bash(command, *, worktree) -> tuple[GuardOutcome, str | None]:            # line 99

# sdd_coder/background.py
class ValidationSupervisor:                                                         # line 435
#   line 579: plan = await self._plan_selection(worktree=worktree, tier=tier, base_ref=base_ref)
async def _plan_selection(self, ...):                                               # line 718
#   line 728: return await asyncio.to_thread(plan_tests, worktree=worktree, changed_files=changed, tier=tier)
#   ^ passes NO declared and NO contract today — the S2 gap M6 closes

# sdd_coder/engine.py
async def run_validation(self, feature, worktree, execution_id, task_ids,
                         tier: Literal["merge", "feature"], timeout_seconds, request_id):  # line 1149
# _resolve_feature: engine.py:1487-1544 — matches per-spec/brief index headers via iter_index_files

# sdd_coder/toolkit.py
async def coder_run_validation(self, feature, worktree, execution_id, task_ids,
                               tier, timeout_seconds, request_id) -> CoderResult:   # line 602

# scripts/sdd/select_tests.py — argparse: --tier :32, --base :33, --task-file :34,
#   --worktree :35, --run :36, --json :37, --feature :38, --report-task :39, --no-ledger :40; main :56
# scripts/sdd/test_report.py — decide-rerun --index :36, render :39-41; main :73
# scripts/sdd/check_task_graph.py
def _check_validation_contract(tasks, root, required) -> list[Finding]:             # line 225
#   call site :425: required = data.get("validation_contract") == VALIDATION_CONTRACT
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `TestContract` | `plan_tests()` | new `contract=` kwarg | `select.py:132` |
| `contract_from_index_header` | `ValidationSupervisor._plan_selection` | header read before planning | `background.py:718-728` |
| `marker_expression_for` | invocation builder | replaces unconditional `-m` | `planner.py:42` |
| `green_cache` store | escalation-ledger storage style | `_atomic_write_json` + lock | `context.py:31` |
| `classify_failures` | `render_markdown` table | `BaselineVerdict` rows | `report.py:289` |
| contract in guard rewrites | `guard._task_plan` | pass contract to `plan_tests` | `guard.py:44,54` |
| `/sdd-done` fresh closeout | final re-run command | new `--fresh`/`--use-cache` flags | `.claude/commands/sdd-done.md:294-296` |

### Does NOT Exist (Anti-Hallucination)
- ~~`### Validation Contract` in `sdd/templates/spec.md`~~ — §4 today is Unit /
  Integration / Fixtures / E2E only (`spec.md:134-155`)
- ~~`test_contract` index header field~~ — new in this feature. **BUT
  `validation_contract` DOES exist** (`"required"` string, FEAT-563 lint flag,
  e.g. `sdd/tasks/index/sql-schema-plane.json:10`, read at
  `check_task_graph.py:425`) — the brainstorm's "does not exist" entry was
  wrong; do NOT overload it, do NOT rename it.
- ~~`test_scope/green_cache.py`, `test_scope/baseline.py`~~ — new files; the
  ledger (`LedgerEntry`) records only distribution escalations today
- ~~node-level statuses in `parse_junit`~~ — aggregates only today
- ~~a `.so`-copy mechanism in `worktree_environment.py`/`worktree_manager.py`~~ —
  verified absent (S8); baseline prep must build it
- ~~any CI job running `packages/*/tests`~~ — `ci.yml` runs root `tests/` only;
  `e2e.yml` is nightly e2e only
- ~~`pytest-testmon`~~ — not installed, not in any `pyproject.toml`
- ~~`ai-parrot` in `XDIST_SAFE_DISTRIBUTIONS`~~ — excluded (FEAT-604 evidence)
- ~~`HOTFIX-*` support in `ValidationSupervisor`~~ — only `TASK-*` ids are
  accepted (S10); briefs are out of scope in v1

### Edit Sites (Blueprint Anchors)

Verified against: `4754028cb` (dev, 2026-10-18). `/sdd-task` MUST re-run the
`grep -c` for every row it uses. All occurrence counts verified = 1.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | MODIFY | `def plan_tests(` | `select.py:132` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py` | MODIFY | `def pytest_target_for(path: str, worktree_path: str) -> str \| None:` | `mirror.py:38` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` | MODIFY | `argv = ("pytest", *AGENT_FLAGS, "-m", policy.marker_expression, *xdist, *extra, *kept_paths)` | `planner.py:42` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py` | MODIFY | `class LedgerEntry:` | `datatypes.py:63` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py` | MODIFY | `def parse_validation_commands(task_md: str) -> list[list[str]]:` | `contract.py:63` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py` | MODIFY | `def pending_escalations(` | `context.py:170` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` | MODIFY | `RERUN_TASK_THRESHOLD = 10` | `report.py:30` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py` | MODIFY | `def _task_plan(worktree: Path) -> ScopePlan \| None:` | `guard.py:44` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | `return await asyncio.to_thread(plan_tests, worktree=worktree, changed_files=changed, tier=tier)` | `background.py:728` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `async def run_validation(` | `engine.py:1149` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` | MODIFY | `async def coder_run_validation(` | `toolkit.py:602` | 1 |
| `scripts/sdd/select_tests.py` | MODIFY | `parser.add_argument("--tier", required=True, choices=("task", "merge", "feature"))` | `select_tests.py:32` | 1 |
| `scripts/sdd/test_report.py` | MODIFY | `decide_rerun.add_argument("--index", required=True, type=Path)` | `test_report.py:36` | 1 |
| `scripts/sdd/check_task_graph.py` | MODIFY | `def _check_validation_contract(` | `check_task_graph.py:225` | 1 |
| `sdd/templates/spec.md` | MODIFY | `### Integration Tests` | `spec.md:142` | 1 |
| `.claude/commands/sdd-task.md` | MODIFY | `"validation_contract": "required",` | `sdd-task.md:301` | 1 |
| `.claude/commands/sdd-done.md` | MODIFY | `DECISION=$(python -m scripts.sdd.test_report decide-rerun --index "$IDX")` | `sdd-done.md:287` | 1 |
| `.claude/agents/sdd-worker.md` | MODIFY | `tier="merge"` | `sdd-worker.md:383` | 1 |
| `.claude/agents/qa-runner.md` | MODIFY | `# Never run the whole suite here — CI owns full-suite and e2e runs.` | `qa-runner.md:64` | 1 |
| `.github/workflows/nightly-tests.yml` | CREATE | — | — | — |

Twins (`.agent/workflows/sdd-spec.md`, `sdd-task.md`, `sdd-done.md`;
`.agents/skills/sdd-*`; `_subagent_data/` prompt copies where they exist) are
edited alongside their `.claude/` counterparts — remember `git add -f` for
anything under a `templates/` path (global `.gitignore` rule).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Kernel stays **stdlib-only dataclasses** (`datatypes.py` style) — it is
  imported by path from the system-python native hook; no Pydantic imports
  reachable from `test_scope/__init__.py`.
- Storage: `_atomic_write_json` (`context.py:31`) plus the file-lock pattern
  already used by `report.py` for every read-modify-write (S7).
- Baseline checkout via `git worktree add --detach` under the feature
  worktree's git dir; always `git worktree remove` in a `finally:`.
- Marker names must be registered (`--strict-markers` in the root
  `pyproject.toml`; `real_llm`/`integration`/`e2e` registered at
  `packages/ai-parrot/pyproject.toml:1049-…`, auto-marked by directory via
  `pytest_collection_modifyitems` in `packages/ai-parrot/tests/conftest.py:19`
  and `tests/conftest.py:20`).
- Docs: every `.claude/` command/agent edit lands in its `.agent/`/
  `.agents/` twin in the same task.

### Known Risks / Gotchas
- **Naming collision (verified)**: `validation_contract: "required"` already
  means "tasks must declare Validation Commands" (FEAT-563). The new field is
  `test_contract`; touching the old one breaks `check_task_graph.py:425`.
- **Under-declared contracts** silently narrow local coverage — mitigations:
  file-level mirror still runs, `check_task_graph` warns when a task's own
  tests are absent from the contract, and the nightly net catches the rest
  (≤ 24 h late, which is the accepted trade).
- **Cache false positives**: dynamic imports, data files, env-driven
  behaviour. Key includes an execution manifest; anything unresolvable ⇒
  miss; whole-namespace invalidation on conftest/pyproject/marker/python
  changes (S6). Node-mapping unavailable ⇒ file never dropped (S5).
- **Baseline checkout cannot be built** (compiled `.so` only in the main
  checkout; no copy mechanism exists today — S8): classify `unknown`,
  treated as failure, stated in the report — never as baseline red.
- **Worktree shared-venv caveat**: baseline and plan runs must set
  `PYTHONPATH=packages/<dist>/src` exactly as today's selector does; never
  `uv sync` inside a worktree.
- **`ValidationSupervisor` id validation**: only `TASK-*` — briefs excluded
  (v1 non-goal, S10); the fallback path covers them.
- **Flaky tests**: v1 classifies a branch-failure that passes on baseline
  re-run of the same nodeid as new red; retry-once is an open question (§8).
- **Nightly cost**: ai-parrot is not xdist-safe; the matrix must budget
  (~25 min for the ai-parrot suite alone at FEAT-698 rates) and set
  per-distribution timeouts.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pytest` | 9.1.1 (installed) | runner; nodeid operands, `-m` expressions |
| `pytest-xdist` | 3.3.1 (installed) | only for `XDIST_SAFE_DISTRIBUTIONS` in the nightly matrix |
| — | — | no new runtime dependencies (stdlib `hashlib`/`json` for the cache) |

---

## 8. Open Questions

- [x] Contract canonical location — *Resolved at spec kickoff (user)*: §4 body
  subsection for authors + cached `test_contract` index header for the kernel.
- [x] Baseline re-run location — *Resolved at spec kickoff (user)*: temporary
  detached checkout of `origin/<base>` with compiled `.so` copied from the
  main checkout; unbuildable ⇒ unknown = failure.
- [x] Marker-exclusion override — *Resolved at spec kickoff (user)*: explicit
  contract operands override `integration`/`e2e`; `real_llm` never, lint-flagged.
- [x] `/sdd-done` cache bypass — *Resolved at spec time (design research S9)*:
  feature tier runs fresh by default; `--use-cache` is the explicit opt-in.
- [x] `/sdd-brief` contracts — *Resolved at spec time (design research S10)*:
  excluded from v1; briefs keep the bounded fallback (`ValidationSupervisor`
  accepts only `TASK-*` ids today).
- [x] Nightly red handling, mechanism half — *Resolved at spec time (S12)*:
  the workflow fails on new reds vs the previous nightly artifact and never
  commits to the repo; CI-side `wikitoolkit ledger` writes are ruled out.
- [ ] Nightly new reds *notification*: open a GitHub issue automatically, or
  leave the red workflow as the signal? — *Owner: Jesus Lara*
- [ ] `RERUN_TASK_THRESHOLD` (`report.py:30`): once the feature tier is cheap,
  drop the `> 10 tasks ⇒ skip` rule entirely or raise it? (M7 implements
  whatever is decided; default if undecided at `/sdd-task` time: drop it —
  the fresh closeout run is the point of the feature.) — *Owner: Jesus Lara*
- [ ] Retry-once for flaky tests before classifying as new red? (v1: no
  retry; a `flaky` status exists in `BaselineVerdict` for forward
  compatibility.) — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the accepted
> brainstorm. Model: `gpt-5.6-luna` (codex-cli 0.162.1, reasoning high) ·
> Status: completed · Transcript: `sdd/state/FEAT-699/design_research/`
> All 12 `affected_paths` sets verified repo-contained and existing; the three
> strongest evidence claims (background.py:728, sdd-done.md:296, planner.py:42)
> were independently re-verified before acceptance.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Contract presence = explicit selector mode (architecture) | CONFIRM | Matches decided replacement semantics; testable | §2 Overview, M3 |
| S2 | Route contract through every validation entry point (architecture) | CONFIRM | Verified gap: `_plan_selection` passes no declarations today | §2, M6 |
| S3 | Versioned structured index payload, fail closed (api) | CONFIRM | Independently found the `validation_contract` collision | §2 Data Models, M2 |
| S4 | Per-invocation marker composition (api) | CONFIRM | `planner.py:42` would deselect declared integration tests | M3 |
| S5 | Node-level junit evidence for cache/baseline (risk) | CONFIRM | aggregates-only today ⇒ misclassification; fail closed | M4/M5, §7 |
| S6 | Cache invalidation beyond imports (risk) | CONFIRM | execution manifest + unknown ⇒ miss | M4, §7 |
| S7 | Feature-scoped, lock-protected cache (architecture) | CONFIRM | unlocked RMW loses entries under parallel validations | M4 |
| S8 | Baseline runner as explicit subsystem (risk) | CONFIRM | verified: no `.so`-copy mechanism in lifecycle code | M5 |
| S9 | Feature closeout fresh by default (alternative) | CONFIRM | `--no-ledger` would not bypass a green cache | M6/M7, §8 |
| S10 | Brief-flow scope mismatch (risk) | CONFIRM | adopted the exclusion branch for v1 | §1 Non-Goals, §7, §8 |
| S11 | E2E acceptance tests before narrowing (testing) | CONFIRM | folded into §4 integration rows | §4 |
| S12 | Nightly = explicit matrix, no repo mutation from CI (alternative) | CONFIRM | per-dist extras, artifacts; rules out CI ledger writes | M8, §8 |

Summary: **12** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-699; the `sdd-coder` engine
  gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M2 → (nothing) — defines `TestContract` + parsing/lint.
  - M3 → M2 (imports `TestContract` from `datatypes.py`).
  - M4 → M3 (filters `ScopePlan`), M2 (contract digest in the namespace).
  - M5 → M4 (node-level `parse_junit` evidence in `report.py`).
  - M6 → M2–M5 (wires them into CLI/supervisor/guard).
  - M7 → M3–M6 (documents frozen semantics).
  - M1 → M2 (payload format in the template examples) — doc-only otherwise.
  - M8 → none (independent track; expected to run concurrently with all).
- **Shared files** (their tasks get serialized): `datatypes.py` (M2, M4, M5 —
  all new dataclasses SHOULD land in M2's task to avoid this),
  `report.py` (M4 cached rows + M5 baseline columns), `select_tests.py` and
  `test_report.py` (M6), `contract.py` (M2, M3's marker helper if placed
  there — prefer `planner.py`).
- **Exclusive resources**: none (no extension rebuilds, no lockfile, no
  migrations). The nightly workflow file is additive.
- **Cross-feature dependencies**: FEAT-698 (sdd-brief) is merged (PR #1715) —
  its `sdd-done.md` and `sdd_coder/engine.py` edits are in the base; re-grep
  anchors at `/sdd-task` time. Check open PRs touching
  `parrot/flows/dev_loop/test_scope/` before decomposition.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-18 | Jesus Lara (with Claude) | Initial draft from accepted brainstorm + codex design research (12/12 confirmed) |
