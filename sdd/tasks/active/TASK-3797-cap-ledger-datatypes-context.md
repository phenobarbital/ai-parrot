# TASK-3797: Cap-escalation ledger — datatypes + context record/skip

**Feature**: FEAT-604 — Merge-Tier Validation Cost
**Spec**: `sdd/specs/merge-tier-validation-cost.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "M2 — the ledger learns cap escalations" + §3 Module 2. Today the
escalation ledger (`parrot-test-scope-escalations.json`) records only
`core_blobs`, so an impact-cap escalation (`select.py:177`) can never be
skipped: on a monorepo-wide merge it is the escalation that fires first and it
is re-paid in full on every merge. This task adds the ledger-side machinery:
the two new `LedgerEntry` fields (`impact_blobs`, `impacted_hash` — resolved
Open Question 1), the `ScopePlan` carrier fields (`cap_hits`, `cap_impacted`),
the widened `read_ledger` validator, and the extended writer/reader functions.
The *selection-side* use of these (select.py) is TASK-3798; the callers
(CLI/QA/supervisor) are TASK-3799/TASK-3800.

---

## Scope

- Add `impact_blobs: dict[str, str]` and `impacted_hash: str` to `LedgerEntry`
  (defaults `{}` / `""`).
- Add `cap_hits: dict[str, tuple[str, ...]]` and `cap_impacted: dict[str, str]`
  to `ScopePlan` (defaults empty) and pass-through kwargs on
  `planner.build_plan` (defaults empty — behaviour unchanged for existing callers).
- Widen `read_ledger`'s strict validator to accept the two new OPTIONAL keys
  and still drop entries with anything else; both new values type-checked
  (`impact_blobs` str→str dict, `impacted_hash` str); a record missing them
  reads as `impact_blobs={}` / `impacted_hash=""`.
- Extend `record_green_escalation(worktree, hit_dists, core_files,
  impact_files=(), impacted_hashes={})` to store impact blobs and the
  per-distribution impacted-set hash.
- Extend `pending_escalations(worktree, hits, cap_hits={}, cap_impacted={})`
  to answer for BOTH kinds in one pass: a cap-escalated distribution is
  skipped only when every recorded `impact_blobs` blob still matches AND
  `cap_impacted[dist] == entry.impacted_hash != ""`.
- Preserve the new fields when `record_green_escalation` / `record_red_run`
  rewrite untouched entries (both rebuild the whole file today with
  `{"core_blobs": ...}` only — that would silently strip the new fields).
- Tests in a NEW file `test_cap_escalation_ledger.py` (context-level only).

**NOT in scope**: any change to `select.py` (TASK-3798), to
`scripts/sdd/select_tests.py` / `nodes/qa.py` (TASK-3799), to
`sdd_coder/background.py` (TASK-3800), or to `policy.py` (TASK-3801).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py` | MODIFY | `LedgerEntry.impact_blobs`/`.impacted_hash`, `ScopePlan.cap_hits`/`.cap_impacted` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py` | MODIFY | validator + writer + `pending_escalations` for cap records |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` | MODIFY | `build_plan` pass-through kwargs `cap_hits`/`cap_impacted` |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py` | CREATE | context-level cap-ledger tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.context import (  # verified: context.py:101,114,134
    record_green_escalation,
    record_red_run,
    pending_escalations,
    read_ledger,                                        # verified: context.py:82
)
from parrot.flows.dev_loop.test_scope.datatypes import CoreHit, LedgerEntry, ScopePlan  # verified: datatypes.py:29,52,40
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py
@dataclass(frozen=True)
class ScopePlan:                                 # line 40 — stdlib-only module: dataclasses.field for dict defaults
    tier: str
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
def _blob(worktree: Path, path: str) -> str | None: ...              # line 74 (git hash-object)
def read_ledger(worktree: Path) -> dict[str, LedgerEntry]: ...       # line 82
#   validator: `if not isinstance(core_blobs, dict) or set(entry.keys()) != {"core_blobs"}:` → line 93
def record_green_escalation(worktree, hit_dists, core_files) -> None: ...  # line 101
def record_red_run(worktree, hit_dists) -> None: ...                 # line 114
def pending_escalations(worktree, hits) -> tuple[list[str], list[str]]: ...  # line 134
def _atomic_write_json(path: Path, payload: object) -> None: ...     # line 31

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py
def build_plan(targets, *, tier, worktree, policy, escalated=(), core_hits=(),
               skipped_escalations=(), notes=()) -> ScopePlan: ...   # line 46

# fixture pattern to copy (real temp git repos, no mocked git):
# packages/ai-parrot/tests/flows/dev_loop/test_scope/test_context.py
```

### Does NOT Exist
- ~~`LedgerEntry.impact_blobs` / `LedgerEntry.impacted_hash`~~ — this task adds them.
- ~~`ScopePlan.cap_hits` / `ScopePlan.cap_impacted`~~ — this task adds them.
- ~~a Pydantic model for the ledger~~ — `test_scope` is stdlib-only by contract
  (`test_stdlib_only.py` enforces it); use frozen dataclasses + `dataclasses.field`.
- ~~a ledger lock~~ — the ledger lives in the per-worktree git dir; no locking
  is introduced by this feature (spec §7).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py#LedgerEntry",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py#ScopePlan",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py#read_ledger",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py#record_green_escalation",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py#record_red_run",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py#pending_escalations",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py#build_plan"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Fail-open is the whole design**: an absent, malformed, unknown-key or
  wrong-typed record means RUN, never SKIP (spec §7 Patterns). An empty
  `impacted_hash` NEVER skips a cap escalation (legacy record).
- **`test_scope` is stdlib-only** (enforced by `test_stdlib_only.py`) — no new
  third-party imports.
- **On-disk backward/forward compatibility** (spec §2 Data Models): old records
  (`core_blobs` only) load with empty new fields; new records read by an OLDER
  parrot fail its strict validator and are dropped — degraded, never wrong.
  Do NOT emit the new keys when both are empty, so a pure-core record stays
  readable by older code.
- Signatures are fixed by spec §2 "New Public Interfaces" — not renegotiable.

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_context.py` — real
  temp-git-repo fixture pattern to copy for the new test file.

---

## Implementation Blueprint

### Steps (in order)
1. Add the four dataclass fields (`datatypes.py`) — *why*: everything else
   type-checks against them.
2. Widen `read_ledger` + extend the two writers (`context.py`) — *why*: the
   reader must accept what the writer emits within the same change, and the
   rewrite paths must not strip fields they don't know.
3. Extend `pending_escalations` — *why*: the single skip-decision point for
   both kinds (spec component diagram).
4. Add `build_plan` pass-through kwargs (`planner.py`) — *why*: TASK-3798's
   `select.py` needs a constructor path for the new `ScopePlan` fields.
5. Write `test_cap_escalation_ledger.py` — *why*: AC coverage for skip, re-arm,
   legacy and unknown-key behaviours.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class LedgerEntry:' …/test_scope/datatypes.py)
# REPLACE the LedgerEntry body — anchor `class LedgerEntry:` (verified: datatypes.py:52)
@dataclass(frozen=True)
class LedgerEntry:
    """Last green escalated run for one distribution."""

    distribution: str
    core_blobs: dict[str, str]  # core file path -> git blob hash
    impact_blobs: dict[str, str] = field(default_factory=dict)
    # changed file path -> git blob hash for the cap escalation that produced
    # this distribution's impacted set; {} for a pre-FEAT-604 record.
    impacted_hash: str = ""
    # sha256 over the sorted impacted-test paths that blew the cap; "" never
    # skips (fail-open to running).
```
```python
# occurrences: 1 (verified: grep -c 'class ScopePlan:' …/test_scope/datatypes.py)
# AFTER — append below the last existing ScopePlan field `notes: tuple[str, ...]` inside
# `class ScopePlan:` (verified: datatypes.py:40; `notes` is the final field, line 48)
    cap_hits: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # escalated distribution -> changed files whose impacted set blew the cap
    cap_impacted: dict[str, str] = field(default_factory=dict)
    # escalated distribution -> sha256 of its sorted impacted-test set
```
**Why**: spec §2 Data Models / §3 Module 2 skeleton. `field(default_factory=dict)`
(import `field` from `dataclasses`, already the module's only dependency) keeps
every existing constructor call site valid. Do not reorder existing fields.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'core_blobs = entry.get("core_blobs")' …/test_scope/context.py)
# REPLACE the validator block in read_ledger — anchor `core_blobs = entry.get("core_blobs")`
# (verified: context.py:92); the two lines after it change:
        core_blobs = entry.get("core_blobs")
        if not isinstance(core_blobs, dict) or not set(entry.keys()) <= {"core_blobs", "impact_blobs", "impacted_hash"}:
            return {}
        impact_blobs = entry.get("impact_blobs", {})
        impacted_hash = entry.get("impacted_hash", "")
        # FILL IN: type-check impact_blobs (str->str dict) and impacted_hash (str);
        # any violation returns {} — bounded by AC "absent/malformed/older ⇒ RUN"
        ledger[distribution] = LedgerEntry(
            distribution=distribution,
            core_blobs=dict(core_blobs),
            impact_blobs=dict(impact_blobs),
            impacted_hash=impacted_hash,
        )
```
```python
# REPLACE record_green_escalation — anchor `def record_green_escalation` (occurrences: 1,
# verified: grep -c 'def record_green_escalation' …/test_scope/context.py; context.py:101)
def record_green_escalation(
    worktree: Path,
    hit_dists: Sequence[str],
    core_files: Sequence[str],
    impact_files: Sequence[str] = (),
    impacted_hashes: Mapping[str, str] = {},
) -> None:
    """Store blob hashes of core_files (and impact_files + impacted-set hash) per distribution."""
    # FILL IN: mirror the existing body — hash core_files AND impact_files with _blob(),
    # serialize EVERY LedgerEntry field of untouched entries (helper `_entry_payload(e)`
    # emitting impact_blobs/impacted_hash only when non-empty), set the hit dists' entry to
    # {"core_blobs": ..., +impact keys when provided, impacted_hash from impacted_hashes.get(dist, "")}
    # — bounded by: on-disk shape unchanged for pure-core records; never raises past the
    # existing guards (git_dir None → return).
```
```python
# occurrences: 2 (verified: grep -cF 'current = {d: {"core_blobs": dict(e.core_blobs)} for d, e in read_ledger(worktree).items()}' …/context.py)
# FILL IN: disambiguate — the SAME rebuild expression appears in record_green_escalation
# (context.py:107, below `blobs = {p: b for p in core_files ...}`) and in record_red_run
# (context.py:124, below the docstring ending `same escalation on every later plan even
# though it is currently failing.`). Replace BOTH with the shared `_entry_payload`-based
# rebuild so untouched entries keep impact_blobs/impacted_hash.
```
```python
# REPLACE pending_escalations — anchor `def pending_escalations` (occurrences: 1,
# verified: grep -c 'def pending_escalations' …/test_scope/context.py; context.py:134)
def pending_escalations(
    worktree: Path,
    hits: Sequence[CoreHit],
    cap_hits: Mapping[str, Sequence[str]] = {},
    cap_impacted: Mapping[str, str] = {},
) -> tuple[list[str], list[str]]:
    """(to run, skipped): a distribution is skipped only when EVERY recorded blob matches
    — and, for a cap escalation, the fresh impacted-set hash equals the recorded one."""
    ledger = read_ledger(worktree)
    to_run: list[str] = []
    skipped: list[str] = []
    for dist in sorted({d for h in hits for d in h.distributions} | set(cap_hits)):
        entry = ledger.get(dist)
        # FILL IN: core check — existing all-blobs-match loop over the dist's relevant
        # CoreHit paths (unchanged semantics); applies only when dist has core hits.
        # FILL IN: cap check — applies only when dist in cap_hits: every cap_hits[dist]
        # file's _blob() matches entry.impact_blobs AND entry.impacted_hash != "" AND
        # cap_impacted.get(dist) == entry.impacted_hash. A dist under BOTH kinds must
        # pass BOTH checks to be skipped — bounded by AC "skipped only when every
        # recorded blob still matches" + "empty impacted_hash never skips".
    return to_run, skipped
```
**Why**: single decision point for both escalation kinds (spec component
diagram); the rebuild-preservation fix prevents the two existing writers from
silently stripping the new fields — without it, a green core record written
AFTER a cap record would erase the cap skip.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'skipped_escalations: Sequence[str] = (),' …/test_scope/planner.py)
# AFTER — insert below `    skipped_escalations: Sequence[str] = (),` in build_plan's
# signature (verified: planner.py:54), and pass both through to the ScopePlan(...) constructor:
    cap_hits: Mapping[str, tuple[str, ...]] | None = None,
    cap_impacted: Mapping[str, str] | None = None,
```
**Why**: TASK-3798's `select.py` hands the cap data to `build_plan`; defaulting
to `None` → `{}` keeps every existing caller unchanged. Import `Mapping` from
`collections.abc` if not present.

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py` (CREATE)
```python
"""Cap-escalation ledger records (FEAT-604 M2) — context-level tests."""

from __future__ import annotations

from pathlib import Path

from parrot.flows.dev_loop.test_scope.context import (
    pending_escalations,
    read_ledger,
    record_green_escalation,
    record_red_run,
)

# FILL IN: copy the temp-git-repo fixture pattern from test_context.py (real git init +
# commit, never mocked git) — bounded by spec §4 Test Data ("reuse the existing real-git
# fixtures rather than mocking git").


def test_cap_escalation_skipped_when_blobs_and_hash_match(tmp_path: Path) -> None:
    """Green cap record + identical content + identical impacted hash ⇒ skipped."""
    # FILL IN: record via record_green_escalation(..., impact_files=[f], impacted_hashes={dist: h});
    # assert pending_escalations(wt, [], cap_hits={dist: [f]}, cap_impacted={dist: h}) skips dist.


def test_cap_escalation_rearmed_by_any_content_change(tmp_path: Path) -> None:
    """Touching one driving file ⇒ dist returns to to_run."""


def test_cap_escalation_rearmed_by_impacted_hash_change(tmp_path: Path) -> None:
    """Same blobs, different cap_impacted hash ⇒ runs (AC: impacted_hash mismatch re-arms)."""


def test_legacy_ledger_record_never_skips_cap(tmp_path: Path) -> None:
    """A core_blobs-only record reads as impact_blobs={} / impacted_hash='' ⇒ cap runs."""


def test_read_ledger_drops_unknown_keys(tmp_path: Path) -> None:
    """An entry with an unexpected key is dropped entirely (fail-open to running)."""


def test_red_run_preserves_other_entries_new_fields(tmp_path: Path) -> None:
    """record_red_run on dist A must not strip dist B's impact_blobs/impacted_hash."""
```
**Why**: mirrors spec §4's M2 unit-test table plus the rebuild-preservation
regression this task introduces.

### FILL IN checklist
- [ ] `context.py::read_ledger` — type-check the two new keys; any violation → `{}`; bounded by AC "absent/malformed/older ⇒ RUN"
- [ ] `context.py::_entry_payload` (new module-private helper) — serialize a `LedgerEntry` omitting empty new keys; bounded by on-disk compat (spec §2)
- [ ] `context.py::record_green_escalation` — hash impact_files, store per-dist `impacted_hash`; bounded by spec §2 New Public Interfaces
- [ ] `context.py::record_red_run` + green rewrite — preserve untouched entries' new fields (2 sites, see disambiguation block)
- [ ] `context.py::pending_escalations` — dual check; both-kinds dist passes both; bounded by AC list
- [ ] `planner.py::build_plan` — pass-through into `ScopePlan(...)`
- [ ] test bodies per docstrings

---

## Acceptance Criteria

- [ ] `LedgerEntry` and `ScopePlan` carry the four new fields with safe defaults
- [ ] A `core_blobs`-only (legacy) record never skips a cap escalation
- [ ] A record with an unknown key is dropped (fail-open); the two new keys are accepted
- [ ] Cap skip requires blob match AND non-empty `impacted_hash` equality
- [ ] `record_red_run`/`record_green_escalation` preserve untouched entries' new fields
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py packages/ai-parrot/tests/flows/dev_loop/test_scope/test_context.py -q` passes
- [ ] `ruff check` and `black -l 120 --check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_context.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py -q`

---

## Test Specification

See the CREATE block above — six named tests with docstrings are the scaffold;
bodies are FILL IN. Reuse `test_context.py`'s real-git tmp fixture pattern.

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code; if anything drifted, update the contract FIRST
4. **Update status** in the per-spec index → `"in-progress"`
5. **Implement** from the Implementation Blueprint; never change a fixed signature or path
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (seat `gpt-5.6-terra` via parrot-sdd-coder MCP)
**Date**: 2026-09-25
**Notes**: `LedgerEntry.impact_blobs`/`.impacted_hash`, `ScopePlan.cap_hits`/`.cap_impacted`,
`read_ledger`'s widened validator, and the extended `record_green_escalation`/
`pending_escalations` signatures landed in `datatypes.py`/`context.py`/`planner.py`.
New `test_cap_escalation_ledger.py` adds 6 context-level tests. Feature's own declared
test scope (`test_scope` + `sdd_coder`) now 618 passed (was 612 before this task). ruff
clean on all 4 touched/created files. The merge-tier validation gate for this chunk
again went red (24 failed / 28 errors, `ai-parrot-integrations`) — same confirmed
environmental cause as TASK-3801 (missing playwright chromium binary + pre-existing,
unrelated Telegram/Slack/Matrix flakiness; failed-count dropped 31→24 between runs with
no code change in between, consistent with flakiness, not a regression from this diff).
**Deviations from spec**: none
