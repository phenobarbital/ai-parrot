---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [ledger, shared-log, audit, claim-conflict]
---

# Feature Specification: Shared-log claim conflicts — stateless audit count and superseded-claim filter

**Feature ID**: FEAT-717
**Date**: 2026-10-22
**Author**: agent:sdd-fix (from `issue:fe3480881432`, group `fixgroup:c2982b4864f3`)
**Status**: approved
**Target version**: current

---

## 1. Motivation & Business Requirements

### Problem Statement

`issue:fe3480881432` (major, bug, discovered from `spec:FEAT-694`) records two
defects in the shared ledger event log's claim-conflict handling. Both are
confirmed still present on `dev` at `9b5810151`:

1. **The audit omits claim conflicts.** `LedgerService._shared_log_audit`
   (`service.py:676`) returns only `path`, `exists`, `local_only_events`,
   `committed_unknown_events` and `marker`. Conflicts exist *only* in the
   transient `SharedLogImportReport` returned by `import_shared_log`, which the
   git hooks discard — every ledger hook line ends in `|| true` and redirects
   its output (FEAT-694 AC12). A conflict detected during a hook-driven import
   is therefore printed to `/dev/null` and never recoverable. FEAT-694 **AC10**
   demands a conflict be "counted in `ledger audit`"; that third clause is
   unmet.

2. **Conflict detection is spurious.** `import_events`
   (`shared_log.py:165`) appends *every* newly imported `issue.claimed` event to
   `imported_claims` (`shared_log.py:200`), with no regard for later
   `issue.unclaimed` / `issue.closed` events in the same batch.
   `import_shared_log` then compares each of those claims against the *final*
   reduced `claimed_by` (`service.py:617-630`). A legitimate committed history
   of "A claims → A unclaims → B claims" reduces to `claimed_by = B`, so the
   superseded `claim(A)` is reported as a bogus A-vs-B `ClaimConflict` and the
   CLI prints a spurious `⚠️ claim conflict` line (`cli.py:3665-3669`).

Together these make the conflict signal both lossy and untrustworthy: the real
conflicts vanish into `/dev/null` while false ones are shouted at the operator.

### Goals

- G1. `ledger audit` reports a `claim_conflicts` count, recomputed **statelessly**
  from the committed log on every call — never read from a prior import report.
- G2. Only *live* claims — the last `issue.claimed` per subject that was not
  superseded by a later `issue.unclaimed`, `issue.closed` or `issue.superseded`
  in the same imported batch — can produce a `ClaimConflict`.
- G3. The existing first-claim-wins reducer is untouched: the local claimant
  stays the winner locally, exactly as FEAT-694 §8 Q1 resolved.
- G4. The superseded-claim filter is one pure, separately testable function
  shared by the import path and the audit path, so the two can never disagree.

### Non-Goals (explicitly out of scope)

- Changing the conflict *resolution* rule (FEAT-694 §8 Q1 keeps "first claim in
  local log order wins"; this feature only reports).
- Cross-batch supersession. The filter is scoped to the events under
  consideration (the imported batch, or the committed files during an audit),
  matching FEAT-694's own framing. A claim whose superseding `unclaimed` was
  already known locally in an *earlier* import is out of scope.
- Editing `sdd/specs/ledger-shared-event-log.spec.md` (FEAT-694) or its
  AC10 checkbox — that spec is closed; this feature is the follow-up.
- Any change to `export_events`, `rotate_events`, the marker fast path, or the
  four git hooks.

---

## 2. Architectural Design

### Overview

One new pure helper in `shared_log.py` — `live_claims()` — becomes the single
definition of "a claim that still stands". Both consumers call it:

- `import_events` filters `imported_claims` through it before returning, so
  `import_shared_log`'s existing comparison loop needs no change at all.
- `_shared_log_audit` reads the committed files, runs the same helper, and
  compares the survivors against local issue state to produce an integer count.

`_shared_log_audit` is a blocking method dispatched with `asyncio.to_thread`
(`service.py:672`), so it cannot `await self._all_issues()`. The issue-state map
is therefore resolved in the async `audit()` and passed in as a parameter —
keeping the helper synchronous, pure with respect to I/O ordering, and stateless.

### Component Diagram

```
import_events ─┐
               ├─→ live_claims(events)  (pure, shared_log.py)
_shared_log_audit ─┘        │
                            └─→ [surviving claim events]
                                      │
import_shared_log ──→ compare vs reduced state ──→ report.claim_conflicts (list)
_shared_log_audit ──→ compare vs issues map    ──→ audit["shared_log"]["claim_conflicts"] (int)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `shared_log.import_events` | modifies | filters its returned claim list through `live_claims` |
| `LedgerService._shared_log_audit` | modifies | gains an `issues` parameter and a `claim_conflicts` key |
| `LedgerService.audit` | modifies | resolves `_all_issues()` and passes it to `_shared_log_audit` |
| `wikitoolkit ledger audit` (CLI) | modifies | prints a conflict line when the count is non-zero |
| `LedgerService.import_shared_log` | unchanged | its comparison loop is already correct once the input is filtered |

### Data Models

No new models. `ClaimConflict` (`shared_log.py:39`) and
`SharedLogImportReport` (`shared_log.py:58`) are unchanged — the audit count is
a plain `int` inside the existing `shared_log` audit dict.

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py
def live_claims(events: Sequence[LedgerEvent]) -> list[LedgerEvent]:
    """Return the ``issue.claimed`` events that still stand within ``events``.

    Walks ``events`` in order, keeping at most one claim per subject — the most
    recent one — and dropping a subject entirely when an ``issue.unclaimed`` or a terminal
    ``issue.closed`` / ``issue.superseded`` for it follows its last claim. Pure: no I/O, no mutation of
    the input. This is the ONLY definition of a live claim; the import path and
    the audit path must both route through it (G4).
    """
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: `live_claims` helper + import filter | yes | signature, ordering and supersession semantics fixed below; single insertion point | — |
| M2: stateless audit count | yes | parameter threading and dict key fixed below | — |
| M3: CLI audit line | yes | exact output string fixed below | — |
| M4: tests | yes | every test name and assertion enumerated in §4 | — |

### Module 1: `live_claims` + import-path filter
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py`
- **Responsibility**: define the live-claim predicate; apply it to the claims
  `import_events` returns.
- **Depends on**: existing `LedgerEvent` (`ledger/events.py:103`).
- **Interface Skeleton** *(signatures + docstrings only)*:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py  (modifies shared_log.py:165)
  def live_claims(events: Sequence[LedgerEvent]) -> list[LedgerEvent]:
      """Return the last un-superseded ``issue.claimed`` per subject, in claim order.

      A subject's claim is dropped when a later ``issue.unclaimed`` or a
      terminal ``issue.closed`` / ``issue.superseded`` for the same subject
      appears in ``events``; a later ``issue.claimed`` replaces an earlier one.
      """

  def import_events(
      local: LedgerLog, repo_root: Path, marker: Path, *, force: bool = False
  ) -> tuple[SharedLogImportReport, list[LedgerEvent]]:
      """Append committed unknown events to a local log, archives before the current log.

      The returned claim list contains only live claims (``live_claims``) — a
      claim superseded within the same batch is never reported as a conflict.
      """
  ```
  Ordering note: the returned list keeps *claim* order (the position of each
  surviving `issue.claimed` event in `events`), not subject-insertion order.

### Module 2: stateless audit count
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py`
- **Responsibility**: recompute the conflict count from the committed files on
  every `audit()` call.
- **Depends on**: Module 1.
- **Interface Skeleton** *(signatures + docstrings only)*:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py  (modifies service.py:672, service.py:676)
  class LedgerService:
      async def audit(self) -> dict[str, Any]:
          """Return log size, per-kind event counts, cursor lag, broken edges, and SQLite settings.

          Resolves local issue state once and hands it to ``_shared_log_audit``,
          which is blocking and cannot await.
          """

      def _shared_log_audit(self, issues: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
          """Blocking: compare the local log with the committed logical shared log.

          Adds ``claim_conflicts``: the number of live committed claims whose
          ``claimed_by`` differs from a locally ``claimed`` issue's claimant.
          Recomputed from ``shared_log_files`` on every call — never read from a
          ``SharedLogImportReport`` (G1).
          """
  ```
  The five pre-existing keys keep their exact names, types and meanings;
  `claim_conflicts` is additive.

### Module 3: CLI audit output
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- **Responsibility**: surface the count to the operator.
- **Depends on**: Module 2.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/cli.py  (modifies cli.py:3796-3803, inside ledger_audit)
  # after the existing "Shared log: …" echo, when shared["claim_conflicts"]:
  #     click.echo(f"  claim conflicts: {shared['claim_conflicts']}")
  ```
  Printed only when the count is non-zero, so a clean ledger's output is
  byte-identical to today's.

### Module 4: tests
- **Path**: `tests/knowledge/wiki/test_ledger_shared_log.py`,
  `tests/knowledge/wiki/test_ledger_shared_log_service.py`,
  `tests/knowledge/wiki/test_cli_ledger_shared_log.py`
- **Responsibility**: lock in both halves of the issue plus the no-regression cases.
- **Depends on**: Modules 1–3.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_live_claims_drops_superseded_claim` | M1 | "A claims → A unclaims → B claims" yields only B's claim |
| `test_live_claims_drops_closed_subject` | M1 | a claim followed by `issue.closed` — and, parametrized, `issue.superseded` — for the same subject yields nothing |
| `test_live_claims_keeps_last_claim_per_subject` | M1 | two consecutive claims with no unclaim yield only the later one |
| `test_live_claims_is_pure` | M1 | the input sequence is not mutated and non-claim kinds are ignored |
| `test_import_ignores_superseded_claim` | M1+M2 | `import_shared_log` reports **no** `ClaimConflict` for the "A claims, A unclaims, B claims" committed history |
| `test_import_detects_claim_conflict` | M1 | **existing test, must still pass** — a genuine concurrent claim still reports one conflict |
| `test_audit_counts_claim_conflicts` | M2 | `audit()["shared_log"]["claim_conflicts"] == 1` for a genuine conflict, computed without any prior import |
| `test_audit_claim_conflicts_ignores_superseded` | M2 | the same superseded history counts `0` |
| `test_audit_reports_shared_log_block` | M2 | **existing test, must still pass** — the five original keys are unchanged |

### Integration Tests

| Test | Description |
|---|---|
| `test_cli_audit_prints_claim_conflicts` | `wikitoolkit ledger audit` prints `claim conflicts: N` when non-zero and omits the line when zero |

### Validation Contract

tests:
- tests/knowledge/wiki/test_ledger_shared_log.py
- tests/knowledge/wiki/test_ledger_shared_log_service.py
- tests/knowledge/wiki/test_cli_ledger_shared_log.py
markers: none

### Test Data / Fixtures

The existing `two_ledgers` fixture
(`tests/knowledge/wiki/test_ledger_shared_log_service.py:17`) already builds
isolated local/foreign `LedgerService` instances over a shared temporary
checkout — reuse it verbatim; do not add a parallel fixture. A superseded
history is produced on the foreign service with
`claim()` → `unclaim()` → `claim()` before `export_shared_log(checkout)`.

---

## 5. Acceptance Criteria

- [ ] AC1. `live_claims` exists in `shared_log.py`, is pure, and drops a claim
      superseded by a later `issue.unclaimed`, `issue.closed` **or**
      `issue.superseded` for the same subject, keeping only the last live claim per subject in claim order.
- [ ] AC2. `import_events` returns only live claims, so a committed history of
      "A claims → A unclaims → B claims" produces **zero** `ClaimConflict`s and
      **no** `⚠️ claim conflict` CLI line.
- [ ] AC3. A genuine concurrent claim still produces exactly one `ClaimConflict`
      with the local claimant as `local_claimed_by` — `test_import_detects_claim_conflict`
      passes unchanged.
- [ ] AC4. `audit()["shared_log"]["claim_conflicts"]` is an `int`, recomputed
      from `shared_log_files` on every call, correct with **no** prior
      `import_shared_log` in the same process (G1 — proves statelessness).
- [ ] AC5. The five pre-existing `shared_log` audit keys (`path`, `exists`,
      `local_only_events`, `committed_unknown_events`, `marker`) are unchanged in
      name, type and value.
- [ ] AC6. `wikitoolkit ledger audit` prints `  claim conflicts: N` when the
      count is non-zero and emits no such line when it is zero.
- [ ] AC7. Both the import path and the audit path obtain their live claims from
      `live_claims` — no second, divergent copy of the predicate exists (G4,
      verifiable by `grep`).
- [ ] AC8. The reducer and the first-claim-wins resolution rule are untouched;
      the local claimant still wins locally (G3).
- [ ] AC9. `pytest tests/knowledge/wiki/test_ledger_shared_log.py tests/knowledge/wiki/test_ledger_shared_log_service.py tests/knowledge/wiki/test_cli_ledger_shared_log.py -q` passes; `ruff check` clean on the three touched source files.
- [ ] AC10. FEAT-694's AC10 is satisfied end to end: a conflict appears in the
      import report, in the `import-log` CLI output, **and** in `ledger audit`.

---

## 6. Codebase Contract

> Verified against `9b5810151` (dev, 2026-10-22).

### Verified Imports

```python
from parrot.knowledge.wiki.ledger.events import LedgerEvent  # verified: ledger/events.py:103
from parrot.knowledge.wiki.ledger.log import LedgerLog  # verified: used at shared_log.py:166
from parrot.knowledge.wiki.ledger.service import LedgerService  # verified: ledger/service.py
from parrot.knowledge.wiki.ledger.shared_log import (  # verified: ledger/shared_log.py
    MARKER_FILENAME,          # line 23
    SHARED_LOG_REL_PATH,      # line 20
    ARCHIVE_REL_DIR,          # line 21
    ClaimConflict,            # line 39
    SharedLogImportReport,    # line 58
    is_shareable,             # line 71
    read_raw_events,          # line 97
    shared_log_files,         # line 103
    read_shared_event_ids,    # line 111
    digest_files,             # line 125
    export_events,            # line 136
    import_events,            # line 165
)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py
class LedgerEvent(BaseModel):
    event_id: str   # line 107
    kind: LedgerEventKind  # line 108
    subject: str    # line 109  — e.g. "issue:fe3480881432"
    actor: str      # line 110
    ts: str         # line 111
    payload: dict[str, Any]  # line 112  — a claim carries payload["claimed_by"]

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py
class ClaimConflict(BaseModel):          # line 39
    issue_id: str                        # line 42
    local_claimed_by: str                # line 43
    foreign_claimed_by: str              # line 44
    foreign_event_id: str                # line 45

def read_raw_events(path: Path) -> list[tuple[str, LedgerEvent]]:  # line 97
def shared_log_files(repo_root: Path) -> list[Path]:               # line 103 — archives, then current
def import_events(                                                  # line 165
    local: LedgerLog, repo_root: Path, marker: Path, *, force: bool = False
) -> tuple[SharedLogImportReport, list[LedgerEvent]]: ...

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
class LedgerService:
    async def _all_issues(self) -> list[tuple[str, dict[str, Any]]]:  # line 227
    async def import_shared_log(self, repo_root: Path | None = None, *, force: bool = False) -> "SharedLogImportReport":  # line 590
    async def audit(self) -> dict[str, Any]:                          # line 646
    def _shared_log_audit(self) -> dict[str, Any]:                    # line 676
    shared_root: Path  # the checkout holding sdd/ledger; settable in tests
```

An issue state dict (from `_all_issues`) carries `status` (`"open"` /
`"claimed"` / closed) and, when claimed, `claimed_by` — verified in use at
`service.py:617-626` and `service.py:449-454`.

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `live_claims()` | `import_events`'s `imported_claims` list | filter before return | `shared_log.py:189-201,217` |
| `live_claims()` | `_shared_log_audit` | called on committed events from `shared_log_files` | `service.py:676-704` |
| `_shared_log_audit(issues)` | `audit()` | `asyncio.to_thread(self._shared_log_audit, issues)` | `service.py:672` |
| `issues` map | `LedgerService._all_issues()` | `dict(await self._all_issues())` — same idiom already used by the import path | `service.py:617` |
| `claim conflicts` line | `ledger_audit` CLI | `click.echo` after the `Shared log:` block | `cli.py:3796-3803` |

### Does NOT Exist (Anti-Hallucination)

- ~~`shared_log.live_claims`~~ — this feature creates it; nothing by that name exists today.
- ~~`SharedLogImportReport.claim_conflict_count`~~ — the report has `claim_conflicts: list[ClaimConflict]` only.
- ~~`audit()["shared_log"]["claim_conflicts"]`~~ — the key does not exist yet; `_shared_log_audit` returns exactly five keys today (`service.py:700-705`).
- ~~`LedgerService.unclaim_issue`~~ — `unclaim` lives on the service (`service.py:426`); `unclaim_issue` is `LedgerIndex`'s (`index.py:497`).
- ~~a `sym:` prefix on this issue's `about`~~ — `issue:fe3480881432`'s `about` is a bare path, which is why the fix planner reported `files: []` and fell back to the `fixgroup-…` slug. Do not "fix" the slug.
- ~~`packages/ai-parrot/tests/knowledge/wiki/`~~ — these ledger tests live at the **repo root**: `tests/knowledge/wiki/`.
- ~~`issue.unclaim` / `issue.claim`~~ — the event kinds are `issue.claimed`, `issue.unclaimed`, `issue.closed`, `issue.superseded` (verified: `ledger/events.py:9-13`).

### Edit Sites (Blueprint Anchors)

> Verified against `9b5810151`. `/sdd-task` MUST re-run each `grep -c`.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py` | MODIFY | `def import_events(` | `shared_log.py:165` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py` | MODIFY | `            if event.kind == "issue.claimed":` | `shared_log.py:200` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `            "shared_log": await asyncio.to_thread(self._shared_log_audit),` | `service.py:672` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `    def _shared_log_audit(self) -> dict[str, Any]:` | `service.py:676` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `    click.echo(f"Total events: {audit['total_events']}")` | `cli.py:3795` | 1 |
| `tests/knowledge/wiki/test_ledger_shared_log.py` | MODIFY | *(append new `live_claims` tests)* | — | — |
| `tests/knowledge/wiki/test_ledger_shared_log_service.py` | MODIFY | `async def test_audit_reports_shared_log_block(two_ledgers: tuple[LedgerService, LedgerService, Path]) -> None:` | `test_ledger_shared_log_service.py:90` | 1 |
| `tests/knowledge/wiki/test_cli_ledger_shared_log.py` | MODIFY | *(append the audit-output test)* | — | — |

---

## 7. Provenance

- Ledger issue: `issue:fe3480881432` (major, bug) — group `fixgroup:c2982b4864f3`,
  lane `sdd` ("max_severity is major"), `suggested_slug` `fixgroup-c2982b4864f3`.
- Discovered from: `spec:FEAT-694` (ledger-shared-event-log), whose per-spec
  index closed at `2026-10-16T01:36:01+00:00` — hence a new spec rather than a
  reused parent.
- Why it was missed: the issue's requirements were written into the then-active
  `TASK-4406` blueprint by commits `0d246920d9` and `2642e2198d` (2026-10-16
  15:29 local) — about twelve hours **after** TASK-4406's implementation had
  already been committed (`4715882192`, 03:26 local). The task was then closed
  `verified` carrying instructions nobody executed.
