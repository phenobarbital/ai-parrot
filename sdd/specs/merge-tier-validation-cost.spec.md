---
type: feature
base_branch: dev
projects: [ai-parrot, dev-loop, sdd-tooling]
tags: [test-scope, sdd-coder, validation, ledger, xdist]
---

# Feature Specification: Merge-Tier Validation Cost

**Feature ID**: FEAT-604
**Date**: 2026-09-25
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.0.7

---

## 1. Motivation & Business Requirements

### Problem Statement

A merge-tier validation in an unattended `sdd-worker` run costs whole package
suites, run serially, on every merge. Measured on the FEAT-601 worktree
(2026-09-25, before PR #1494):

```
$ python -m scripts.sdd.select_tests --worktree .claude/worktrees/feat-FEAT-601-training-agent --tier merge
→ 27 pytest invocations, 26 of them FULL package suites
  # note: ai-parrot: 347 impacted tests exceed cap 150, escalated to suite
  # escalated: ai-parrot … parrot-formdesigner   (26 distributions)
  ledger-skipped escalations: 0
```

PR #1494 fixes one of the three multipliers — the diff base is now the merged
chunk's fork point instead of the branch's whole cumulative diff against
`origin/dev`. The other two are untouched and are this feature's subject:

1. **The escalation ledger never fires under `sdd-coder`.** `pending_escalations`
   (`test_scope/context.py:134`) skips a distribution whose core-file blobs match
   a recorded green run, but the only writers of that ledger are `QANode`
   (`nodes/qa.py:618`) and `scripts/sdd/select_tests.py --run` (`:91`). The
   background `ValidationSupervisor` that actually runs merge-tier validations
   for `sdd-worker` never records anything, so `skipped_escalations` is
   permanently empty on that path: a suite that went green for unchanged content
   in the previous merge is re-paid in full on the next one.
2. **Cap escalations are not dedupable at all.** Even where the ledger does work,
   `LedgerEntry` (`datatypes.py:52`) records only `core_blobs`. An impact-cap
   escalation (`select.py:177` — `len(paths) > policy.impact_cap` → whole suite)
   leaves no record of *what content* it covered, so it can never be skipped —
   and on a monorepo-wide merge it is the escalation that fires first.
3. **Nothing runs in parallel.** `XDIST_SAFE_DISTRIBUTIONS` (`policy.py:740`) is
   an empty `frozenset()`: the FEAT-563 S3 spike never completed a
   serial-plus-2×-xdist comparison within its time budget, and the fail-safe
   default excluded every distribution. Its own comment records that `ai-parrot`
   alone extrapolates to ~2.3h for one serial pass. Every escalated suite
   therefore runs single-process, one distribution after another
   (`background.py:664`, the chained-invocation loop).

Together these turn the "changed scope" gate into a multi-hour serial sweep,
which is why merges appear to hang and why an operator learns to ignore the
gate rather than wait for it.

### Goals

- A merge-tier validation launched by `sdd-coder` records its own green
  escalations, so the existing content-keyed skip works on that path.
- An impact-cap escalation is dedupable by content, exactly like a core
  escalation, and is re-armed by any content change or red run.
- `XDIST_SAFE_DISTRIBUTIONS` is populated from real, reproducible evidence for
  at least the distributions that dominate merge-tier cost, or the spike's
  negative result is recorded so the empty set stops looking accidental.
- The cost reduction is measured against the same FEAT-601-shaped baseline, not
  asserted.

### Non-Goals (explicitly out of scope)

- Changing the diff base of a merge-tier selection — that is PR #1494, already
  in flight; this feature assumes it has landed.
- Lowering `DEFAULT_IMPACT_CAP` or trimming `CORE_PATHS`. Both are measured
  values (FEAT-563 S4); making the gate cheaper by covering less is exactly the
  trade this feature exists to avoid.
- Adding `coder_bg_wait` or any orchestration-prompt change (PR #1494).
- Parallelising *across* distributions in the supervisor. The chained,
  one-at-a-time invocation loop stays; this feature only makes an individual
  invocation able to use `-n auto`.

---

## 2. Architectural Design

### Overview

Three independent modules, in dependency order.

**M1 — the supervisor becomes a ledger writer.** `ValidationSupervisor._supervise`
already runs one invocation at a time and knows each one's exit code, but
collapses them into a single terminal outcome for the handle. It gains
per-invocation attribution: for every invocation that carries escalated targets,
a green exit records the escalation and a red exit re-arms it, reusing
`record_green_escalation` / `record_red_run` verbatim — the same contract
`select_tests.py --run` already implements (`:88-102`). No new ledger semantics,
no second write path: the supervisor simply stops being the one runner that
never reports.

**M2 — the ledger learns cap escalations.** `LedgerEntry` gains a second,
optional record kind alongside `core_blobs`: `impact_blobs`, the blob hashes of
the *changed files that produced* the impacted set for that distribution, plus
`impacted_hash`, a sha256 over that distribution's sorted impacted-test set
(resolved Open Question 1: the driving blobs alone leave the graph-staleness
hole open; the full index fingerprint — the cache is keyed by `HEAD^{tree}`,
`impact.py:187` — would make the skip fire only at a byte-identical tree, i.e.
never across merges). A cap escalation is skipped only when every driving file
still hashes to the recorded value AND the freshly computed impacted set hashes
to the recorded `impacted_hash` — `plan_tests` already holds that set at the cap
branch (`select.py:177`), so the fingerprint costs nothing to produce. Same
fail-open-to-running rule as the core path: an unreadable blob, a missing entry,
an empty `impacted_hash` or a malformed ledger means run it. `plan_tests`
records, per escalated distribution, which changed files drove the escalation
and the set hash so the writer has something to store; `pending_escalations`
answers for both kinds in one pass.

**M3 — xdist evidence.** Re-run the S3 comparison as a bounded, resumable
per-distribution job (serial baseline, then two `-n auto` runs, comparing
per-test outcomes, not just the summary line), smallest distributions first, and
add only the distributions that pass twice. Distributions that cannot complete
within the budget stay out and are recorded as such, with their measured wall
time, so the exclusion is evidence rather than silence.

Resolved Open Question 2 — budget and scope: **~2h total wall time**, covering
every distribution EXCEPT three pre-excluded ones whose exclusion is recorded
from existing evidence, not re-measured: `ai-parrot` (≈2.3h for ONE serial pass,
`artifacts/logs/feat-563-s3-xdist.md` — it stays serial and its cost is bought
down by M1/M2's dedupe instead), `ai-parrot-integrations` (deterministic hang in
`test_handle_web_app_data_routes_to_strategy`, ledger `1dbb2aac09ba` — not
comparable until fixed) and `ai-parrot-server` (~18 intermittent contention
failures when its e2e directory runs together, ledger `e21ec87c6aba` — xdist
would amplify, not settle, the comparison). Everything in scope is ≤ ~310 test
files (`ai-parrot-tools` 310, `parrot-formdesigner` 226, root `tests/` 520 —
included, it is the second-largest cost driver — then a long tail of 1–34-file
distributions), i.e. minutes per 3-run protocol.

### Component Diagram

```
ValidationSupervisor._supervise ──(per invocation outcome)──→ context.record_green_escalation
        │                                                     context.record_red_run
        │                                                              │
        ▼                                                              ▼
   plan_tests(tier="merge") ←──(skip decision)──── context.pending_escalations
        │                                                              ▲
        └──(escalation → driving changed files)───────────────────────┘
                                                              LedgerEntry
                                            core_blobs + impact_blobs + impacted_hash
policy.XDIST_SAFE_DISTRIBUTIONS ──→ planner._invocation ──→ ("-n", "auto")
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ValidationSupervisor._supervise` | extends | per-invocation outcome attribution; records to the ledger |
| `context.record_green_escalation` / `record_red_run` | uses | unchanged contract, new caller |
| `context.pending_escalations` | extends | answers for cap escalations too |
| `datatypes.LedgerEntry` | extends | optional `impact_blobs` |
| `select.plan_tests` | extends | reports which changed files drove each escalation |
| `policy.XDIST_SAFE_DISTRIBUTIONS` | data change | populated from M3's evidence |
| `scripts/sdd/select_tests.py --run` | extends | same dedupe for cap escalations |
| `nodes/qa.py::_record_green_escalations` | extends | same, for the dev-loop QA path |

### Data Models

```python
@dataclass(frozen=True)
class LedgerEntry:
    """Last green escalated run for one distribution."""

    distribution: str
    core_blobs: dict[str, str]        # core file path -> git blob hash
    impact_blobs: dict[str, str] = field(default_factory=dict)
    # changed file path -> git blob hash, for the cap escalation that produced
    # this distribution's impacted set. Empty for a pre-FEAT-604 record, which
    # therefore never skips a cap escalation (fail-open to running).
    impacted_hash: str = ""
    # sha256 over the sorted impacted-test paths that blew the cap for this
    # distribution. A cap skip requires the freshly computed set to hash to
    # this value too (Open Question 1: catches an import-graph change that
    # alters the impacted set without touching a driving file). "" (legacy or
    # core-only record) never skips a cap escalation.
```

The on-disk ledger (`parrot-test-scope-escalations.json`) keeps its current
shape for `core_blobs`; `read_ledger`'s strict validator
(`set(entry.keys()) != {"core_blobs"}` → entry dropped, `context.py:93`) is
widened to accept the new optional keys (`impact_blobs`, `impacted_hash`) and
still drop anything else. A record
written by an older parrot is read as `impact_blobs={}`; a record written by a
newer parrot and read by an older one fails that validator and is dropped, which
re-runs the escalation — degraded, never wrong.

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py
def record_green_escalation(
    worktree: Path,
    hit_dists: Sequence[str],
    core_files: Sequence[str],
    impact_files: Sequence[str] = (),
    impacted_hashes: Mapping[str, str] = {},
) -> None:
    """Store current blob hashes of core_files (and impact_files, plus the per-distribution
    impacted-set hash from `impacted_hashes`) per distribution after a green run."""


def pending_escalations(
    worktree: Path,
    hits: Sequence[CoreHit],
    cap_hits: Mapping[str, Sequence[str]] = {},
    cap_impacted: Mapping[str, str] = {},
) -> tuple[list[str], list[str]]:
    """(distributions to run, distributions skipped). A cap-escalated distribution is skipped
    only when every recorded driving-file blob matches AND `cap_impacted[dist]` (the sha256 of
    the freshly computed sorted impacted set) equals the recorded `impacted_hash`."""
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: supervisor records escalations | yes | reuse `record_green_escalation`/`record_red_run`; attribution is per invocation, mirroring `select_tests.py:88-102`; a ledger failure is logged and swallowed, never a failed validation | — |
| M2: cap-escalation dedupe | yes | `LedgerEntry.impact_blobs`; skip only when every blob matches; missing/malformed ⇒ run; `ScopePlan` carries `cap_hits: dict[str, tuple[str, ...]]` | — |
| M3: xdist evidence | no | the pass/fail criterion per distribution is a measurement judgement; budget and scope are resolved (Open Question 2): ~2h, smallest-first, `ai-parrot`/`ai-parrot-integrations`/`ai-parrot-server` pre-excluded with recorded reasons | executing the measurement is still a judgement call, not a delegable contract |

### Module 1: Supervisor records its own escalations
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py`
- **Responsibility**: attribute a per-invocation exit code to that invocation's
  escalated distribution and write the green/red ledger record, so the
  content-keyed skip works for `sdd-coder`-launched validations. Additionally
  (resolved Open Question 3): `start()` writes a selection-summary header into
  the supervised log before the first invocation —
  `# selection tier=<tier> escalated=[...] skipped_escalations=[...]` plus one
  `# note: ...` line per `plan.notes` entry — so `coder_bg_status`'s existing
  bounded log tail shows WHY a validation was cheap, with no status-schema
  change. The `# no applicable pytest invocations` message gains the same
  header, so an all-skipped empty plan is distinguishable from an empty diff.
- **Depends on**: existing `test_scope.context`; PR #1494 (merged first).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py
  #   (modifies packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py:664)
  async def _record_invocation_outcome(
      self, *, worktree: Path, invocation: "PytestInvocation", plan: "ScopePlan", exit_code: int
  ) -> None:
      """Record this invocation's escalation verdict in the per-worktree ledger.

      Green (exit 0) records the blobs that escalation covered; red re-arms it
      (`record_red_run`), exactly as `scripts/sdd/select_tests.py --run` does.
      An invocation with no escalated target records nothing. Never raises: a
      ledger failure is logged and swallowed — it degrades the NEXT selection,
      it must never fail THIS validation.
      """
  ```

### Module 2: Cap escalations become dedupable
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py`,
  `.../test_scope/datatypes.py`, `.../test_scope/select.py`
- **Responsibility**: record and honour a content key for impact-cap escalations,
  so a cap escalation that went green for unchanged content is skipped on the
  next merge.
- **Depends on**: Module 1 (otherwise nothing writes the new record on the
  `sdd-coder` path and the feature is unobservable there).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py  (modifies datatypes.py:52)
  @dataclass(frozen=True)
  class LedgerEntry:
      """Last green escalated run for one distribution."""
      distribution: str
      core_blobs: dict[str, str]
      impact_blobs: dict[str, str]   # changed file -> blob hash for a cap escalation; {} when none
      impacted_hash: str             # sha256 of the sorted impacted-test set; "" when none/legacy

  @dataclass(frozen=True)
  class ScopePlan:               # modifies datatypes.py:40
      """The per-tier selection result."""
      cap_hits: dict[str, tuple[str, ...]]
      """Escalated distribution -> the changed files whose impacted set blew the cap."""
      cap_impacted: dict[str, str]
      """Escalated distribution -> sha256 of its sorted impacted-test set (computed at select.py:177)."""

  # packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py  (modifies context.py:101, :134)
  def record_green_escalation(
      worktree: Path, hit_dists: Sequence[str], core_files: Sequence[str],
      impact_files: Sequence[str] = (), impacted_hashes: Mapping[str, str] = {}
  ) -> None:
      """Store current blob hashes of core_files and impact_files (plus the impacted-set hash)
      per distribution after a green run."""

  def pending_escalations(
      worktree: Path, hits: Sequence[CoreHit],
      cap_hits: Mapping[str, Sequence[str]] = {}, cap_impacted: Mapping[str, str] = {}
  ) -> tuple[list[str], list[str]]:
      """(to run, skipped): a cap-escalated distribution is skipped only when EVERY recorded
      driving blob still matches AND the fresh impacted-set hash equals `impacted_hash`."""
  ```

### Module 3: xdist safety evidence
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py`,
  `artifacts/logs/feat-604-xdist.md` (evidence, git-ignored — `git add -f` if committed)
- **Responsibility**: produce reproducible per-distribution evidence that
  `-n auto` yields the same per-test outcomes as a serial run, twice, and
  populate `XDIST_SAFE_DISTRIBUTIONS` with exactly the distributions that pass.
  Budget and scope per resolved Open Question 2: ~2h total, smallest-first,
  everything EXCEPT `ai-parrot` (≈2.3h per serial pass — excluded on the S3
  evidence), `ai-parrot-integrations` (deterministic hang, ledger
  `1dbb2aac09ba`) and `ai-parrot-server` (contention flakiness, ledger
  `e21ec87c6aba`); the three exclusions are RECORDED in the evidence file with
  those citations, not re-measured.
- **Depends on**: nothing (parallel with M1/M2).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py  (modifies policy.py:740)
  XDIST_SAFE_DISTRIBUTIONS: frozenset[str] = frozenset({...})
  """Measured safe under `-n auto` (same per-test outcome as serial, twice).

  Evidence: artifacts/logs/feat-604-xdist.md. A distribution is added ONLY with
  a two-run comparison of its own; one that could not complete within the
  spike's budget stays out, with its measured wall time recorded.
  """
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_supervisor_records_green_escalation` | M1 | a green escalated invocation writes the distribution's blobs |
| `test_supervisor_rearms_on_red_escalation` | M1 | a red escalated invocation drops the record (`record_red_run`) |
| `test_supervisor_records_nothing_without_escalation` | M1 | a mirror/import-only invocation writes no ledger entry |
| `test_supervisor_ledger_failure_never_fails_validation` | M1 | an unwritable ledger is logged and swallowed; the receipt stays green |
| `test_start_logs_selection_summary` | M1 | `start()` writes the `# selection …` header (escalated + skipped_escalations + notes) into the log; an all-skipped empty plan is distinguishable from an empty diff |
| `test_cap_escalation_skipped_when_blobs_match` | M2 | second selection over identical content skips the cap-escalated suite |
| `test_cap_escalation_rearmed_by_any_content_change` | M2 | touching one driving file re-runs the suite |
| `test_cap_escalation_rearmed_by_impacted_set_change` | M2 | a graph change that alters the impacted set (e.g. a new test file importing a changed module) re-runs the suite even with all driving blobs unchanged |
| `test_legacy_ledger_record_never_skips_cap` | M2 | a `core_blobs`-only record yields `impact_blobs={}` ⇒ cap escalation runs |
| `test_read_ledger_drops_unknown_keys` | M2 | an entry with an unexpected key is still dropped (fail-open to running) |
| `test_plan_reports_cap_driving_files` | M2 | `ScopePlan.cap_hits` names the changed files per escalated distribution |

### Integration Tests

| Test | Description |
|---|---|
| `test_second_merge_validation_skips_unchanged_suites` | two consecutive merge-tier validations on a temp repo: the second plans strictly fewer invocations |
| `test_red_first_run_forces_full_second_run` | a red first validation re-arms everything; the second plans the same scope |

### Test Data / Fixtures

```python
# Reuse the existing real-git fixtures rather than mocking git:
#   packages/ai-parrot/tests/flows/dev_loop/test_scope/test_context.py  (temp repos/worktrees)
#   packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py::git_sandbox_feature
# Synthetic controlled-exit children (`python -c "import sys; sys.exit(N)"`) with
# `background_module.protected_argv` monkeypatched to identity — the pattern
# test_background_validation.py already documents for nested-bwrap environments.
```

---

## 5. Acceptance Criteria

- [ ] A merge-tier validation launched through `coder_run_validation` writes an
      escalation ledger record for every escalated invocation it runs, green or red.
- [ ] A second merge-tier selection over unchanged content reports those
      distributions in `skipped_escalations` and omits their invocations.
- [ ] Any change to a file that drove a cap escalation re-arms that distribution.
- [ ] An import-graph change that alters a cap escalation's impacted set re-arms
      that distribution even when no driving file changed (`impacted_hash` mismatch).
- [ ] The supervised log for every `coder_run_validation` launch begins with a
      selection-summary header naming `escalated`, `skipped_escalations` and the
      plan notes, visible through `coder_bg_status`'s log tail.
- [ ] A red escalated run re-arms its distribution even when content is unchanged.
- [ ] A ledger that is absent, malformed, unreadable or written by an older
      version causes the escalation to RUN, never to be skipped.
- [ ] A ledger write failure never changes a validation's own outcome.
- [ ] `XDIST_SAFE_DISTRIBUTIONS` contains only distributions with a recorded
      two-run comparison in `artifacts/logs/feat-604-xdist.md`; every excluded
      distribution has a recorded reason and wall time (for the three
      pre-excluded ones — `ai-parrot`, `ai-parrot-integrations`,
      `ai-parrot-server` — the recorded reason cites the existing evidence:
      S3 log, ledger `1dbb2aac09ba`, ledger `e21ec87c6aba`).
- [ ] Measured on a FEAT-601-shaped worktree: the second consecutive merge-tier
      selection over unchanged content plans strictly fewer pytest invocations
      than the first, with the before/after numbers recorded in the PR.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope packages/ai-parrot/tests/flows/dev_loop/sdd_coder -q` passes.
- [ ] `ruff check` and `black -l 120 --check` clean on every touched file.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.flows.dev_loop.test_scope.context import (  # verified: test_scope/context.py:101,114,134
    record_green_escalation,
    record_red_run,
    pending_escalations,
)
from parrot.flows.dev_loop.test_scope.datatypes import (  # verified: test_scope/datatypes.py:29,40,52
    CoreHit,
    ScopePlan,
    LedgerEntry,
)
from parrot.flows.dev_loop.test_scope.select import changed_files, plan_tests  # verified: sdd_coder/background.py:45
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py
@dataclass(frozen=True)
class CoreHit:                                   # line 29
    path: str
    module: str
    fanin: int
    forced: bool
    distributions: tuple[str, ...]

@dataclass(frozen=True)
class ScopePlan:                                 # line 40
    tier: str                                    # "task" | "merge" | "feature"
    invocations: tuple[PytestInvocation, ...]
    escalated: tuple[str, ...]
    core_hits: tuple[CoreHit, ...]
    skipped_escalations: tuple[str, ...]
    notes: tuple[str, ...]

@dataclass(frozen=True)
class LedgerEntry:                               # line 52
    distribution: str
    core_blobs: dict[str, str]

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py
LEDGER_FILENAME: str = "parrot-test-scope-escalations.json"          # line 16
def worktree_git_dir(worktree: Path) -> Path | None: ...             # line 21
def _blob(worktree: Path, path: str) -> str | None: ...              # line 74
def read_ledger(worktree: Path) -> dict[str, LedgerEntry]: ...       # line 82
def record_green_escalation(worktree, hit_dists, core_files) -> None: ...  # line 101
def record_red_run(worktree, hit_dists) -> None: ...                 # line 114
def pending_escalations(worktree, hits) -> tuple[list[str], list[str]]: ...  # line 134

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py
def _suite_for(distribution: str, worktree: Path) -> str | None: ...  # line 66
def plan_tests(*, worktree, changed_files, tier, declared=(), policy=None) -> ScopePlan: ...  # line 122
#   cap branch: line 177  (`if len(paths) > policy.impact_cap:` → escalated.append(dist), line 178)
#   core branch: line 191 (`to_run, ledger_skipped = pending_escalations(worktree, hits)`)

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py
DEFAULT_IMPACT_CAP: int = 150                     # line 9
DEFAULT_IMPACT_DEPTH: int = 1                     # line 10
DEFAULT_CORE_FANIN_THRESHOLD: int = 50            # line 11
CORE_PATHS: tuple[str, ...] = (...)               # line 12 — 724 entries
XDIST_SAFE_DISTRIBUTIONS: frozenset[str] = frozenset()   # line 740 — EMPTY
@dataclass(frozen=True)
class ScopePolicy:                                # line 751

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py
_DEFAULT_BASE_REF = "origin/dev"                  # line 73
async def _supervise(self, *, execution_id, handle, process, log_path, deadline,
                     remaining_invocations, worktree) -> None: ...   # signature ends line 665
#   chained-invocation loop: `for invocation in remaining_invocations:` (line 669)

# scripts/sdd/select_tests.py
#   the existing green/red writer contract this feature mirrors: lines 88-102
#     is_core_escalation = any(target.reason == "core" for target in invocation.targets)   # line 91

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py
async def _record_green_escalations(...) -> None: ...   # line 618
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_record_invocation_outcome` | `context.record_green_escalation()` | function call | `test_scope/context.py:101` |
| `_record_invocation_outcome` | `context.record_red_run()` | function call | `test_scope/context.py:114` |
| `ScopePlan.cap_hits` | `pending_escalations()` | argument | `test_scope/select.py:191` |
| `LedgerEntry.impact_blobs` | `read_ledger()` validator | dict key | `test_scope/context.py:93` |
| `XDIST_SAFE_DISTRIBUTIONS` | `planner._invocation()` | membership test | `test_scope/planner.py:40` |

### Does NOT Exist (Anti-Hallucination)

- ~~`ValidationSupervisor` importing anything from `test_scope.context`~~ — it
  imports only `changed_files, plan_tests` (`background.py:45`). This is the
  defect, not an oversight to route around.
- ~~a per-invocation outcome record in `BackgroundStatus`~~ — the supervisor
  reports ONE terminal outcome per handle; per-invocation attribution is M1's job.
- ~~`ScopePlan.cap_hits` / `ScopePlan.cap_impacted`~~ — do not exist yet (M2 adds them).
- ~~`LedgerEntry.impact_blobs` / `LedgerEntry.impacted_hash`~~ — do not exist yet (M2 adds them).
- ~~`ScopePolicy.xdist_cap` / any per-distribution worker count~~ — not a field;
  `-n auto` is the only xdist form (`planner.py:40`).
- ~~a ledger entry for a `mirror`/`import` target~~ — the ledger records
  escalations only; `reason` values are `declared|core|escalated|import|mirror`
  (`planner.py:17`).

### Edit Sites (Blueprint Anchors)

Verified against: `f39a2ddc7`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | `        remaining_invocations: list["PytestInvocation"],` | `background.py:664` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | `                self._append_log, log_path, f"# $ {shlex.join(first.argv)} (distribution={first.distribution})\n"` | `background.py:589` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py` | MODIFY | `def record_green_escalation(worktree: Path, hit_dists: Sequence[str], core_files: Sequence[str]) -> None:` | `context.py:101` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py` | MODIFY | `def pending_escalations(worktree: Path, hits: Sequence[CoreHit]) -> tuple[list[str], list[str]]:` | `context.py:134` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py` | MODIFY | `class LedgerEntry:` | `datatypes.py:52` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | MODIFY | `                if len(paths) > policy.impact_cap:` | `select.py:177` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | MODIFY | `                to_run, ledger_skipped = pending_escalations(worktree, hits)` | `select.py:191` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` | MODIFY | `XDIST_SAFE_DISTRIBUTIONS: frozenset[str] = frozenset(` | `policy.py:740` | 1 |
| `scripts/sdd/select_tests.py` | MODIFY | `        is_core_escalation = any(target.reason == "core" for target in invocation.targets)` | `select_tests.py:91` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | `    async def _record_green_escalations(` | `qa.py:618` | 1 |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- The ledger is fail-open by construction: `read_ledger` returns `{}` on absent
  or malformed input so escalations re-run (`context.py:82-97`). Every new code
  path keeps that direction — an unknown, unreadable or unparsable record means
  RUN, never SKIP.
- Mirror `scripts/sdd/select_tests.py:88-102` for green/red attribution instead
  of inventing a second contract; it already encodes the R14/AC9c re-arm rule.
- The ledger lives in the per-worktree git dir (`LEDGER_FILENAME`,
  `worktree_git_dir`), so two concurrent features never share one — no locking
  is introduced by this feature.
- Async boundaries: the supervisor is async, the ledger helpers are sync file
  I/O — call them through `asyncio.to_thread`, as `qa.py:633` already does.

### Known Risks / Gotchas

- **Skipping is a correctness claim.** A cap escalation covers *impacted* tests,
  and the impacted set is derived from an import index that can itself go stale.
  Keying the skip on the driving changed files' blobs is narrower than keying it
  on the whole index; a change that alters the import graph without touching a
  driving file could in principle be skipped. Mitigation (resolved Open
  Question 1): the skip ALSO requires `impacted_hash` — the sha256 of the
  freshly recomputed sorted impacted set — to match the recorded one, so a
  graph change that matters (one that alters the impacted set) always re-arms;
  plus the merge-tier base after PR #1494 is the chunk's own diff, and the
  feature-tier gate at `/sdd-done` never dedupes.
- **`-n auto` hides ordering bugs both ways.** A suite that only passes serially
  is a real defect, but adding it to the safe set on one lucky comparison
  converts a flaky suite into a silently flaky gate. Two independent comparisons
  are the minimum, and the criterion is per-test outcome equality, not the
  summary counts.
- The S3 spike already failed once on wall time. M3 must be resumable per
  distribution and must record partial results, or it will fail the same way.
- PR #1494 changes `ValidationSupervisor.start()`'s signature (`base_ref`) and
  `run_validation`. Branch this feature AFTER it merges; the anchors above were
  verified against `f39a2ddc7`, which does not yet contain it.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pytest-xdist` | already a dev dependency | `-n auto`; M3 only measures it |

---

## 8. Open Questions

- [x] Should a cap-escalation skip also require the import index's own fingerprint
      to be unchanged, rather than only the driving files' blobs? — *Owner: Jesus Lara*
      **Resolved 2026-09-25**: neither extreme. The index's own fingerprint is the
      `HEAD^{tree}` cache key (`impact.py:187`), which changes on every commit and
      would make the skip fire only at a byte-identical tree. Instead the skip
      additionally requires `impacted_hash` — sha256 of the sorted impacted-test
      set, already in hand at the cap branch (`select.py:177`) — to match. Folded
      into M2 (`LedgerEntry.impacted_hash`, `ScopePlan.cap_impacted`).
- [x] M3 budget: how much wall time is the xdist comparison worth, and which
      distributions are in scope if the full set cannot finish? — *Owner: Jesus Lara*
      **Resolved 2026-09-25**: ~2h total, smallest-first, cheap-first scope: every
      distribution EXCEPT `ai-parrot` (≈2.3h per serial pass, S3 evidence — stays
      serial; M1/M2 dedupe buys down its cost), `ai-parrot-integrations`
      (deterministic hang, ledger `1dbb2aac09ba`) and `ai-parrot-server`
      (contention flakiness, ledger `e21ec87c6aba`). The three exclusions are
      recorded in the evidence file with citations, not re-measured.
- [x] Should `skipped_escalations` be surfaced in the `coder_bg_status` log tail,
      so an operator can see WHY a validation was cheap? — *Owner: Jesus Lara*
      **Resolved 2026-09-25**: yes, as log header lines written by `start()`
      (`# selection tier=… escalated=[…] skipped_escalations=[…]` + one line per
      plan note) — no status-schema change; the existing bounded tail surfaces it,
      and an all-skipped empty plan becomes distinguishable from an empty diff.
      Folded into M1.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: — · Status: skipped (no exploration document:
> this spec was written directly from a measured defect report, so §3b's
> accepted-brainstorm precondition never held) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- Isolation: ONE feature worktree for FEAT-604; the `sdd-coder` engine gives each
  task its own sub-worktree inside it.
- Module dependency graph: **M2 → M1** (M2's new record is only written on the
  `sdd-coder` path by M1's writer, so M2's integration test is unobservable
  without it). **M3** has no edge to either and runs concurrently.
- Shared files: `test_scope/context.py` and `test_scope/select.py` are touched by
  M2 only; `policy.py` by M3 only; `background.py` by M1 only. No file is shared
  across modules, so only M1/M2's own ordering serializes.
- Exclusive resources: M3's measurement runs are wall-clock-bound full suites —
  its tasks are `parallel: false` and must not share the machine with another
  module's test runs, or the timings are meaningless.
- Cross-feature dependencies: **PR #1494
  (`fix/sdd-coder-merge-scope-and-bg-wait`) must be merged first.**

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-25 | Jesus Lara | Initial draft — split from the merge-tier cost investigation; items 3+4 of that report (PR #1494 covers 1+2) |
| 0.2 | 2026-09-25 | Jesus Lara | Status → approved. §8 Open Questions resolved: M2 gains `impacted_hash`/`cap_impacted` (impacted-set fingerprint on cap skips); M3 budget ~2h cheap-first with ai-parrot/integrations/server pre-excluded on cited evidence; M1 gains the `start()` selection-summary log header for `coder_bg_status` |
