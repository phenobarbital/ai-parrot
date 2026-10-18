---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [dev-loop, sdd-tooling, ci]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [test-selection, validation-contract, sdd-done, sdd-worker, ci]
---

# Brainstorm: Tests Optimization in the SDD Flow (spec-declared validation contract)

**Date**: 2026-10-18
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: A + B (spec-declared Validation Contract with a cross-merge green cache)

---

## Problem Statement

`sdd-worker` (merge tier, after every chunk merge), every `sdd-coder` seat
(task tier) and `/sdd-done` (feature tier re-run and lint-fix checks) each run
pytest through the FEAT-563 test-scope kernel. For a real feature the
accumulated cost is very large. `/sdd-done` for FEAT-698
(`feat-FEAT-698-sdd-brief-hotfix-flow`, 15 tasks, PR #1715) reported:

```
Suite      Tests   Passed  Failed  Skipped  Errors  Duration
ai-parrot  11096   10948   100     48       0       1302.67s
root       176     176     0       0        0       36.56s
Total (per-task invocation totals)  11272 ... 1339.24s
re-run skipped (15 tasks > 10)
```

**What actually happened (measured 2026-10-18, this brainstorm):** the full
suite was *never* run, and no escalation fired. Reproducing the plans on the
FEAT-698 tip (`d7e03cb93`) against its fork point (`49806c49f`) with
`python -m scripts.sdd.select_tests --tier merge|feature --no-ledger --json`:

| tier | escalated | core_hits | cap_hits | ai-parrot targets | ai-parrot tests collected |
|---|---|---|---|---|---:|
| merge (cumulative diff) | [] | [] | {} | 22 files/dirs (mirror + depth-1 import) | **2990** |
| feature | [] | [] | {} | 1 dir: `packages/ai-parrot/tests/flows/dev_loop` | **2562** |

None of FEAT-698's 47 changed files is in `CORE_PATHS`. The 11,096 figure is
the **sum of 15 per-chunk merge-tier runs** (≈740 tests / ≈87 s each) that
re-executed largely the *same* `flows/dev_loop` tests over and over. The
feature-tier plan picks a whole test *directory* because the mirror rule
(`mirror.deepest_existing_dir`) walks up to the deepest existing tests dir.

So the root causes are:

1. **Breadth by heuristic** — mirror (directory-level) + depth-1 import
   impact select thousands of tests that the feature's author never declared
   relevant. Nothing lets the spec say "these are the integration tests that
   matter for this feature".
2. **Redundancy across merges** — each merge re-runs tests whose test file and
   imported source are unchanged since a previous green run in the same
   feature. The FEAT-604 escalation ledger dedupes only *suite escalations*,
   not ordinary selected tests.
3. **Verdict noise** — ~100 tests are red on the `dev` baseline; they fail every
   merge and every feature run, so a red table does not mean the feature broke
   anything.
4. **No real safety net** — `.github/workflows/ci.yml` runs only the repo-root
   `tests/` (`--ignore=tests/tools`); **no `packages/*/tests` runs in CI at
   all**, and `e2e.yml` is nightly e2e only. Narrowing local selection without
   a net would hide regressions.

Affected: everyone running `sdd-worker` / `/sdd-done` (wall clock, tokens in
seat outputs, retry multipliers) and reviewers reading an always-red table.

## Constraints & Requirements

- Decisions from discovery (2026-10-18):
  - Flow: `type: feature`, `base_branch: dev`.
  - The spec-declared set **replaces** heuristic escalation/breadth when present;
    full-suite runs move out of the local SDD loop.
  - Applies to **all** phases: task (`sdd-coder`), merge (`sdd-worker`),
    feature (`/sdd-done`), and `qa-runner` / autopilot QA.
  - Expressed as **both** explicit pytest paths/nodeids **and** optional markers.
  - Merge tier = the chunk's tasks' `## Validation Commands` ∪ the spec contract
    (no import-impact selection when a contract exists).
  - When a spec declares **no** contract: bounded fallback — tasks' own tests +
    file-level direct (depth-1) importers, **never** escalate to a whole suite;
    a note in the report says so.
  - **Dedupe across merges is in scope**: a test file already green in this
    feature, whose own blob and imported-source blobs are unchanged, is skipped.
  - **Baseline-aware verdict**: the gate fails only on tests that pass on
    `origin/<base_branch>` and fail on the branch (new reds).
  - Safety net: a **nightly full-suite workflow on `dev`** covering every
    `packages/*/tests`.
- Targets: merge-tier validation **< 2 min**, `/sdd-done` feature tier **< 5 min**.
- Deterministic, stdlib-only kernel (the `test_scope` package is imported by
  path from the system-python native hook — no Pydantic in `__init__`).
- Backward compatible: specs/task files written before this feature keep
  working (fallback path); the guard (`guard.py`) keeps rewriting broad pytest.
- Never run a full suite from an agent-issued command (unchanged FEAT-563 rule).

---

## Options Explored

### Option A: Spec-declared Validation Contract (authoritative selection)

`/sdd-spec` gains a mandatory-but-skippable `### Validation Contract`
subsection in §4 (Test Specification) listing the feature's critical
integration tests as explicit pytest operands (`path` or `path::node`) plus
optional marker names. `/sdd-task` caches the contract into the per-spec index
header (like `type`/`base_branch`) and makes each task's `## Validation
Commands` reference its own tests. The kernel's `plan_tests()` gains a
`contract` input: when present, merge = chunk tasks' declared tests ∪
contract; feature = all tasks' declared tests ∪ contract; mirror is used only
at **file** level (a changed `foo.py` → an existing `test_foo.py`), never a
directory; no impact selection, no core/cap suite escalation. Without a
contract, the bounded fallback applies. `check_task_graph.py` lints that every
contract operand exists.

✅ **Pros:**
- Puts the decision where the knowledge is — the spec author knows which
  integration paths the feature touches.
- Deterministic, reviewable, diffable; plans shrink from thousands to
  tens/hundreds of tests.
- Same contract drives all four phases → one source of truth.

❌ **Cons:**
- Quality depends on the spec author; an under-declared contract silently
  narrows coverage (mitigated by the nightly net and file-level mirror).
- Does not remove re-execution of the same declared tests on every merge.
- Touches several command/agent docs (`sdd-spec`, `sdd-task`, `sdd-done`,
  `sdd-worker`, `qa-runner`) plus their `.agent/` twins.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pytest` | runner | 9.1.1 installed; `-m` marker expressions, nodeid operands |
| `pytest-xdist` | parallelism | 3.3.1 installed; only for `XDIST_SAFE_DISTRIBUTIONS` (ai-parrot is NOT in it) |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` — `plan_tests()` tier entry point (extend with `contract`)
- `.../test_scope/contract.py` — `parse_validation_commands()`, `_pytest_operands()` (reuse to parse contract operands)
- `.../test_scope/mirror.py` — `pytest_target_for()` (restrict to file level)
- `scripts/sdd/check_task_graph.py` — `_check_validation_contract()` (extend to the spec contract)
- `sdd/templates/spec.md` §4 — add the subsection next to "Integration Tests"

---

### Option B: Content-addressed green cache across merges (dedupe)

Extend the FEAT-604 ledger idea from "suite escalations" to **every selected
test file**: after a green (or baseline-red-only) run, record per test file a
key = hash(test file blob, conftest chain blobs, blobs of the source modules
it imports at depth ≤ N via `ImportIndex`, marker expression, Python version).
On the next merge in the same feature, a selected test whose key matches is
skipped and reported as `cached`. Stored in the worktree git dir next to the
existing escalation ledger (`context.py`). No spec change.

✅ **Pros:**
- Directly removes the 15× re-execution measured on FEAT-698, whatever the
  selection rule is.
- Zero author burden; pure kernel change; reuses `ImportIndex` and blob helpers.

❌ **Cons:**
- Alone it does not shrink breadth: the first merge still runs ~3k tests, the
  feature tier still runs a directory.
- Key correctness matters: dynamic imports, fixtures in shared conftests, data
  files and env-driven behavior can invalidate a cache hit; depth bound is a
  tradeoff (FEAT-620 showed transitive closure saturates).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| stdlib `hashlib`, `json` | key + store | same style as `LedgerEntry.impacted_hash` |

🔗 **Existing Code to Reuse:**
- `.../test_scope/context.py` — `read_ledger()`, `record_green_escalation()`, `pending_escalations()`, `_blob()`, `_atomic_write_json()`
- `.../test_scope/impact.py` — `ImportIndex.load_or_build()`, `_expand_modules()`
- `.../test_scope/report.py` — `parse_junit()` (per-file outcome to decide what is green)

---

### Option C: Coverage-guided selection (pytest-testmon) — unconventional

Replace import heuristics with **measured** dependency data: `pytest-testmon`
records which source lines/blocks each test executed and, on later runs,
selects only tests whose executed code changed. A shared testmon database
would be seeded by the nightly run on `dev` and copied into each worktree.

✅ **Pros:**
- Most precise selection available; catches dynamic imports heuristics miss.
- Naturally dedupes across merges (unchanged code ⇒ test deselected).

❌ **Cons:**
- New dependency, sqlite DB per worktree, coverage overhead (~1.3–2×) on every
  recording run; ai-parrot suite is not xdist-safe, so seeding is slow.
- DB staleness across branches and the shared editable `.venv` (main-checkout
  code is what gets traced — see the worktree `PYTHONPATH` caveat) make it
  fragile in this repo's multi-worktree setup.
- Opaque to reviewers; conflicts with the "deterministic, declared" FEAT-563
  philosophy and with `guard.py` rewriting.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pytest-testmon` | coverage-based test selection | 2.x; NOT installed; needs `coverage` |

🔗 **Existing Code to Reuse:**
- `.github/workflows/e2e.yml` — nightly workflow pattern for seeding

---

### Option D: Defer breadth to closeout (merge = owned tests only)

Keep heuristics but move them: merge tier runs **only** the merged tasks'
`## Validation Commands`; the impact/mirror breadth runs **once** at
`/sdd-done` (feature tier), in the background, always (drop the `> 10 tasks`
skip).

✅ **Pros:**
- Smallest change; immediate large win on merge-tier wall clock.

❌ **Cons:**
- `/sdd-done` still pays ~2.5k+ tests (misses the < 5 min target); late
  discovery of breakage after all merges are done.
- No author input, no dedupe, no baseline awareness.

📊 **Effort:** Low

🔗 **Existing Code to Reuse:**
- `.../test_scope/select.py` — tier branches in `plan_tests()`
- `.../test_scope/report.py` — `should_rerun()` / `RERUN_TASK_THRESHOLD`

---

## Recommendation

**Option A, combined with Option B's cache**, plus two cross-cutting pieces the
discovery made mandatory: a baseline-aware verdict and a nightly full-suite net.

- A fixes **breadth** (the 2,990 / 2,562 plans) by letting the spec name what
  matters, and by demoting mirror to file level; B fixes **redundancy** (15×
  re-runs) with no author burden. Each alone misses a target: A without B still
  re-runs the contract every merge; B without A still pays ~3k tests on the
  first merge and the directory at closeout.
- C is the most precise but adds a stateful, opaque dependency that fights the
  multi-worktree + shared-venv setup; it stays a possible future replacement
  for the fallback heuristic, not for the contract.
- D is the cheap interim, but it misses the `/sdd-done` target and adds no
  signal quality.

What we trade off: local runs no longer prove "nothing else in the package
broke". That guarantee moves to the nightly full-suite workflow (new), which
today does not exist for `packages/*/tests` at all — so the net actually
*improves* coverage of package suites versus today, just later (≤ 24 h).

---

## Feature Description

### User-Facing Behavior

- **Spec authors** (`/sdd-spec`) get a `### Validation Contract` subsection in
  §4 with two lists: `tests:` (pytest operands — file or `file::node`) and
  `markers:` (optional, e.g. a feature marker). `/sdd-spec` proposes an initial
  contract from the Module Breakdown + existing tests and the human edits it.
  An empty contract is allowed but explicit (`none — fallback`).
- **`/sdd-task`** copies the contract into the per-spec index header and makes
  every task's `## Validation Commands` list that task's own test files.
- **`sdd-coder` / `sdd-worker` / `qa-runner`** see much shorter plans; plain
  `select_tests` output shows each target's reason (`declared`, `contract`,
  `mirror-file`, `import-fallback`) and `cached` skips.
- **`/sdd-done`** test table gains columns/rows for *new reds vs baseline*,
  *known baseline reds*, and *cached (skipped, unchanged since green)*. The
  final feature-tier re-run becomes cheap enough to always run (the
  `> 10 tasks` skip is revisited — Open Question).
- **Maintainers** get a nightly workflow on `dev` running every package suite;
  new reds vs the previous nightly are surfaced (issue/ledger — Open Question).

### Internal Behavior

1. **Contract source.** Parsed from the spec's `### Validation Contract`
   (same parsing style as `contract.parse_validation_commands`), cached by
   `/sdd-task` into the per-spec index header (`validation_contract`), read by
   the kernel from the index — the kernel never parses the spec at runtime.
2. **Selection (`plan_tests`).**
   - task: declared (task Validation Commands) ∪ file-level mirror. Unchanged
     semantics except mirror no longer returns a directory.
   - merge: chunk tasks' declared ∪ contract ∪ file-level mirror. With a
     contract: no impact selection, no core/cap suite escalation. Without one:
     + depth-1 direct importers at file level, capped; cap overflow → note,
     not a suite.
   - feature: all tasks' declared ∪ contract ∪ file-level mirror.
   - Markers become an extra invocation per distribution (`-m <marker>` over the
     distribution's tests root), intersected with the agent marker expression.
3. **Green cache (B).** After a run, per test file whose tests are all
   green-or-known-baseline-red, record its content key in the worktree git dir.
   Before a run, drop cached-and-unchanged files from the plan (report them).
   The feature tier at `/sdd-done` may bypass the cache (Open Question) so the
   closeout table is a real end-to-end run of the contract.
4. **Baseline-aware verdict.** On failure, re-run **only the failed nodeids**
   on `origin/<base_branch>` (a detached temporary checkout or the
   main-checkout code), classify each as *new red* (passes on base) or
   *baseline red*. The gate fails only on new reds. Cost is proportional to the
   number of failures, not to the suite.
5. **Enforcement.** `guard.py` keeps rewriting broad agent pytest to the task
   plan; `coder_run_validation` keeps admitting only the selector's plan — both
   now pick up the contract automatically through `plan_tests`.
6. **Nightly net.** New `.github/workflows/nightly-tests.yml` (cron, `dev`):
   all `packages/*/tests` + root `tests/`, agent marker expression excluded
   markers aside; artifact = junit + a red-set summary for comparison.

### Edge Cases & Error Handling

- Contract operand missing on disk → `check_task_graph.py` error at `/sdd-task`
  time; at runtime → note + skip operand (never silently broaden).
- Contract present but a task changes a `CORE_PATHS` module → still no suite
  escalation locally; the plan notes "core change — covered by nightly"
  (decision: contract replaces escalation).
- Legacy specs / briefs (FEAT-698 `/sdd-brief` hotfixes have no spec §4) →
  fallback path; brief template may optionally carry a contract later.
- Cache invalidation: conftest change, `pyproject` pytest options change,
  marker expression change, or Python version change ⇒ whole cache invalid.
- Baseline re-run cannot build the base (e.g. the Cython `parrot.utils.types`
  `.so` exists only in the main checkout) → classify as *unknown*, treat as a
  failure, and say so in the report — never as baseline red.
- Flaky tests (pass on retry) → reported as flaky, not new red; Open Question
  whether to retry once.
- Contract-declared test that is itself marked `integration`/`e2e` (excluded by
  `AGENT_MARKER_EXPRESSION`) → explicit inclusion must override the exclusion
  for contract operands, or be lint-flagged (Open Question).

---

## Capabilities

### New Capabilities
- `spec-validation-contract`: §4 `### Validation Contract` in specs, cached in the per-spec index, linted.
- `test-green-cache`: content-addressed per-test-file skip of unchanged-and-green tests across merges within a feature.
- `baseline-aware-verdict`: failures re-run on `origin/<base>`; gate on new reds only; report split.
- `nightly-package-suites`: scheduled full run of every `packages/*/tests` on `dev`.

### Modified Capabilities
- `scoped-test-selection` (FEAT-563): tier semantics — contract-aware, file-level mirror, no suite escalation when a contract exists, bounded fallback.
- `merge-tier-validation-cost` (FEAT-604): ledger generalised from escalations to per-file green records.
- `test-scope-impact-tech-debt` (FEAT-620): core detection demoted to a report note when a contract exists.
- `sdd-done-tests` (FEAT-695): table columns (new red / baseline red / cached) and the re-run rule.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/flows/dev_loop/test_scope/select.py` | modifies | `plan_tests()` gains contract input + file-level mirror + fallback |
| `parrot/flows/dev_loop/test_scope/mirror.py` | modifies | file-level resolution mode (no directory walk-up for merge/feature) |
| `parrot/flows/dev_loop/test_scope/context.py` / `datatypes.py` | extends | green-cache records next to `LedgerEntry` |
| `parrot/flows/dev_loop/test_scope/report.py` | modifies | baseline classification, cached rows, re-run rule |
| `parrot/flows/dev_loop/sdd_coder/engine.py` / `toolkit.py` | depends on | `run_validation` / `coder_run_validation` pass task ids → contract via index |
| `scripts/sdd/select_tests.py`, `scripts/sdd/test_report.py` | modifies | CLI flags/output for contract, cache, baseline |
| `scripts/sdd/check_task_graph.py` | extends | lint contract operands |
| `sdd/templates/spec.md`, `.claude/commands/sdd-spec.md`, `sdd-task.md`, `sdd-done.md` (+ `.agent/` twins) | modifies | new subsection; index caching; table |
| `.claude/agents/sdd-worker.md`, `qa-runner.md`, `sdd-coder.md` | modifies | wording: contract-driven plans |
| `.github/workflows/nightly-tests.yml` | new | full package suites on `dev` |
| per-spec index schema (`sdd/tasks/index/*.json`) | extends | header `validation_contract` (optional field) |

No breaking change: every new field is optional and the fallback preserves
today's behaviour minus suite escalation.

---

## Code Context

### User-Provided Code

```text
# Source: user-provided (/sdd-done output for FEAT-698)
Suite    Tests    Passed    Failed    Skipped    Errors    Duration
ai-parrot ❌    11096    10948    100    48    0    1302.67s
root    176    176    0    0    0    36.56s
Total (per-task invocation totals) ❌    11272    11124    100    48    0    1339.24s
re-run skipped (15 tasks > 10)
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py:132
def plan_tests(
    *,
    worktree: Path,
    changed_files: Sequence[str],
    tier: str,
    declared: Sequence[Sequence[str]] = (),
    policy: ScopePolicy | None = None,
) -> ScopePlan:
    """task=declared∪mirror (no escalation); merge=mirror∪impact∪core (cap→escalate);
    feature=declared∪mirror∪core; core escalations deduped by the ledger."""
# select.py:23  def changed_files(worktree: Path, base_ref: str) -> list[str]
# select.py:100 def _declared_targets(declared, notes, *, worktree) -> list[str]
# select.py (merge branch): impact cap → `notes.append(f"{dist}: {n} impacted tests exceed cap {cap}, escalated to suite")`

# From .../test_scope/datatypes.py:42
@dataclass(frozen=True)
class ScopePlan:
    tier: str  # "task" | "merge" | "feature"
    invocations: tuple[PytestInvocation, ...]
    escalated: tuple[str, ...]
    core_hits: tuple[CoreHit, ...]
    skipped_escalations: tuple[str, ...]
    notes: tuple[str, ...]
    cap_hits: Mapping[str, tuple[str, ...]]
    cap_impacted: Mapping[str, str]

# datatypes.py:63
@dataclass(frozen=True)
class LedgerEntry:
    distribution: str
    core_blobs: dict[str, str]
    impact_blobs: dict[str, str] = field(default_factory=dict)
    impacted_hash: str = ""
# datatypes.py:11 TestTarget, :22 PytestInvocation, :31 CoreHit, :73 AttemptContext(tier, task_id, task_file, base_ref, ...)

# From .../test_scope/policy.py
AGENT_MARKER_EXPRESSION = "not e2e and not real_llm and not integration"   # line 7
DEFAULT_IMPACT_CAP = 150          # line 9
DEFAULT_IMPACT_DEPTH = 1          # line 10
DEFAULT_CORE_FANIN_THRESHOLD = 30 # line 15
CORE_PATHS: tuple[str, ...]       # line 16, 29 entries, regenerated by scripts/sdd/regen_core_paths.py
XDIST_SAFE_DISTRIBUTIONS          # ai-parrot is NOT a member
TIERS = ("task", "merge", "feature")
@dataclass(frozen=True)
class ScopePolicy: impact_cap, impact_depth, core_fanin_threshold, core_paths, xdist_safe,
                   escalate_foreign_dists=False, marker_expression

# From .../test_scope/contract.py
VALIDATION_HEADING = "## Validation Commands"                      # line 10
def parse_validation_commands(task_md: str) -> list[list[str]]     # line 63
def is_broad_pytest(argv, *, worktree=None) -> bool                # line 143

# From .../test_scope/mirror.py
def pytest_targets(files: Sequence[str], worktree_path: str) -> list[str]        # line 10
def pytest_target_for(path: str, worktree_path: str) -> str | None               # line 38
def deepest_existing_dir(tests_root: str, subdirs: tuple[str, ...], worktree_path: str) -> str  # line 84 — the directory walk-up

# From .../test_scope/impact.py
class ImportIndex:  # line 112; build() :121, load_or_build() :172
def impacted_tests(index, changed, *, worktree, depth) -> list[str]   # line 234
def detect_core(index, changed, *, policy) -> list[CoreHit]          # line 264

# From .../test_scope/context.py
def read_ledger(worktree: Path) -> dict[str, LedgerEntry]           # line 82
def record_green_escalation(...)                                    # line 124
def record_red_run(worktree: Path, hit_dists: Sequence[str]) -> None # line 150
def pending_escalations(worktree, hits, cap_hits={}, cap_impacted={}) -> tuple[list[str], list[str]]  # line 170

# From .../test_scope/report.py
RERUN_TASK_THRESHOLD = 10                                   # line 30
def append_suite(...)                                       # line 186
def load_records(feature_id: str) -> tuple[dict[str, TaskTestRecord], list[str]]  # line 235
def should_rerun(task_count: int) -> bool                   # line 258
def render_markdown(...)                                    # line 289

# From packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:1149
async def run_validation(self, feature: str, worktree: str, execution_id: str,
                         task_ids: List[str], tier: Literal["merge", "feature"],
                         timeout_seconds: int, request_id: str) -> BackgroundRegistration
# From .../sdd_coder/toolkit.py:602
async def coder_run_validation(self, feature, worktree, execution_id, task_ids,
                               tier: Literal["merge", "feature"], timeout_seconds, request_id) -> CoderResult

# From scripts/sdd/check_task_graph.py:225
def _check_validation_contract(tasks: dict[str, _Task], root: Path, required: bool) -> list[Finding]
```

#### Verified Imports
```python
from parrot.flows.dev_loop.test_scope import (  # test_scope/__init__.py:7-10
    AttemptContext, CoreHit, LedgerEntry, PytestInvocation, ScopePlan, TestTarget,
    VALIDATION_HEADING, changed_files, is_broad_pytest, parse_validation_commands,
    plan_tests, pytest_target_for, pytest_targets,
)
# NOTE: test_scope/__init__.py is stdlib-only and imported BY PATH as top-level
# `test_scope` from the native hook and scripts/sdd/*.py — never import models.py (Pydantic) there.
```

#### Key Attributes & Constants
- `/sdd-done` feature tier call: `.claude/commands/sdd-done.md:171` and re-run `:272-285` (`decide-rerun`, `timeout -k 10 1800 … --tier feature`)
- `sdd-worker` merge tier: `.claude/agents/sdd-worker.md:361-363` (`coder_run_validation(... tier="merge")`) and fallback `:537-538` (`select_tests --tier merge … --run`)
- `qa-runner` already forbids the whole suite: `.claude/agents/qa-runner.md:64`
- CI: `.github/workflows/ci.yml` "Run core tests" → `uv run pytest tests/ -q --tb=short --ignore=tests/tools --continue-on-collection-errors` (root `tests/` only)
- Markers registered in `packages/ai-parrot/pyproject.toml:1049` (`real_llm`, `integration`, `e2e` auto-marked by directory via `pytest_collection_modifyitems` in `packages/ai-parrot/tests/conftest.py:19`, `tests/conftest.py:20`); root `pyproject.toml` uses `--strict-markers` → any new feature marker must be registered
- Spec template §4 "Test Specification" at `sdd/templates/spec.md:134` (Unit / Integration / Fixtures / E2E Scenarios) — the new subsection goes here
- Installed: `pytest 9.1.1`, `pytest-xdist 3.3.1`

### Does NOT Exist (Anti-Hallucination)
- ~~`### Validation Contract` in `sdd/templates/spec.md`~~ — no spec-level test selection section exists
- ~~`validation_contract` in per-spec index headers~~ — not a field today
- ~~a per-test-file green cache~~ — the ledger (`LedgerEntry`) records only distribution *escalations*
- ~~baseline-red classification in `report.py`~~ — failures are counted raw
- ~~a CI job running `packages/*/tests`~~ — `ci.yml` runs root `tests/` only; `e2e.yml` is nightly e2e only
- ~~`pytest-testmon`~~ — not installed, not in any `pyproject.toml`
- ~~`ai-parrot` in `XDIST_SAFE_DISTRIBUTIONS`~~ — it is excluded (FEAT-604 evidence `artifacts/logs/feat-604-xdist.md`)

---

## Parallelism Assessment

- **Internal parallelism**: Medium. Independent tracks: (1) spec template +
  `/sdd-spec`/`/sdd-task` docs + index field + `check_task_graph` lint;
  (2) kernel selection changes (`select.py`, `mirror.py`); (3) green cache
  (`context.py`, `datatypes.py`); (4) baseline verdict + table (`report.py`,
  `test_report.py`, `sdd-done.md`); (5) nightly workflow. Tracks 2–4 all touch
  `test_scope/` and `select_tests.py` → must be sequenced or carefully
  file-partitioned.
- **Cross-feature independence**: conflicts possible with anything touching
  `parrot/flows/dev_loop/test_scope/`, `sdd_coder/engine.py`, or
  `.claude/commands/sdd-done.md` (FEAT-698 just changed `sdd-done.md` and the
  `sdd_coder` engine — merged 2026-10-18). Check open PRs before `/sdd-task`.
- **Recommended isolation**: `mixed` — the nightly workflow and the doc/template
  track can run in their own worktrees; kernel tracks stay sequential in the
  feature worktree.
- **Rationale**: the kernel is a small, tightly coupled package with shared
  datatypes; the workflow and templates have no code overlap with it.

---

## Open Questions

- [ ] Where does the contract live canonically: spec §4 body subsection (parsed) or spec frontmatter key (like `e2e:`)? Recommendation: body subsection for authors + cached index field for the kernel — *Owner: Jesus Lara*
- [ ] Should the `/sdd-done` feature tier bypass the green cache so the closeout table is a fresh end-to-end run of the contract? — *Owner: Jesus Lara*
- [ ] Once the feature tier is cheap, drop `RERUN_TASK_THRESHOLD` (> 10 tasks ⇒ skip) or raise it? — *Owner: Jesus Lara*
- [ ] Contract operands under `integration/` dirs are excluded by `AGENT_MARKER_EXPRESSION`: should an explicit contract operand override the exclusion? — *Owner: Jesus Lara*
- [ ] Nightly new reds: open a GitHub issue, or write a `wikitoolkit ledger` issue (needs a commit from CI)? — *Owner: Jesus Lara*
- [ ] Baseline re-run location: temporary detached checkout of `origin/<base>` (Cython `.so` missing there) vs main-checkout code — which is trustworthy enough? — *Owner: Jesus Lara*
- [ ] Should `/sdd-brief` (hotfix/fix briefs, FEAT-698) also carry an optional contract? — *Owner: Jesus Lara*
- [ ] Retry-once for flaky tests before classifying as new red? — *Owner: Jesus Lara*
- [x] Flow type and base — *Owner: Jesus Lara*: `feature` on `dev`.
- [x] Role of the spec list — *Owner: Jesus Lara*: replaces heuristic escalation; full suite only outside the local loop.
- [x] Phases — *Owner: Jesus Lara*: task, merge, feature, qa-runner/autopilot.
- [x] Format — *Owner: Jesus Lara*: explicit paths/nodeids and optional markers.
- [x] No contract — *Owner: Jesus Lara*: bounded fallback (own tests + file-level depth-1 importers, no suite escalation, noted).
- [x] Merge tier with a contract — *Owner: Jesus Lara*: chunk tasks' tests ∪ contract.
- [x] Dedupe across merges — *Owner: Jesus Lara*: in scope.
- [x] Baseline reds — *Owner: Jesus Lara*: gate on new reds vs `origin/<base>`.
- [x] Safety net — *Owner: Jesus Lara*: nightly full suite on `dev` (CI covers no package suites today).
- [x] Targets — *Owner: Jesus Lara*: merge < 2 min, `/sdd-done` < 5 min.
