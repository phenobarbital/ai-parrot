# TASK-4578: `live_claims` helper + superseded-claim filter in `import_events`

**Feature**: FEAT-717 — Shared-log claim conflicts (stateless audit count and superseded-claim filter)
**Spec**: `sdd/specs/fixgroup-c2982b4864f3.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Discovered-from**: `issue:fe3480881432`
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 1**. `issue:fe3480881432` reports that shared-log
claim-conflict detection is spurious: `import_events`
(`shared_log.py:165`) appends **every** newly imported `issue.claimed` event to
its returned claim list (`shared_log.py:200`), and `import_shared_log` then
compares each one against the *final* reduced `claimed_by`. A legitimate
committed history of "A claims → A unclaims → B claims" reduces to
`claimed_by = B`, so the superseded `claim(A)` is reported as a bogus A-vs-B
`ClaimConflict` and `wikitoolkit ledger import-log` prints a false
`⚠️ claim conflict` line.

This task creates the one pure predicate that defines a claim that still
stands — `live_claims()` — and applies it at the single point where
`import_events` returns its claim list. `import_shared_log`'s comparison loop
(`service.py:617-630`) is already correct once its input is filtered, so it is
**not** touched. TASK-4579 reuses the same helper for the audit count, which is
how spec G4 guarantees the two paths can never disagree.

---

## Scope

- Add `SUPERSEDING_CLAIM_KINDS` and `live_claims()` to `shared_log.py`.
- Filter `import_events`'s returned claim list through `live_claims()`.
- Add `from collections.abc import Sequence` to `shared_log.py` (not currently imported).
- Write unit tests for `live_claims()` and one service-level regression test
  proving a superseded history yields zero conflicts.

**NOT in scope**:
- `_shared_log_audit`, `audit()`, the `claim_conflicts` audit key, and the CLI
  audit line — all TASK-4579.
- `import_shared_log`'s comparison loop (`service.py:617-630`) — it needs no change.
- The reducer or the first-claim-wins resolution rule (spec G3 / FEAT-694 §8 Q1).
- `export_events`, `rotate_events`, the marker fast path, the git hooks.
- Cross-batch supersession (spec §1 Non-Goals) — the filter sees only the
  events it is handed.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py` | MODIFY | Add `Sequence` import, `SUPERSEDING_CLAIM_KINDS`, `live_claims()`; filter `import_events`'s return |
| `tests/knowledge/wiki/test_ledger_shared_log.py` | MODIFY | Unit tests for `live_claims()` |
| `tests/knowledge/wiki/test_ledger_shared_log_service.py` | MODIFY | `test_import_ignores_superseded_claim` regression test |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `04f0bc87d` (dev, 2026-10-22).

### Verified Imports

```python
# already present at the top of shared_log.py — do NOT re-add
from parrot.knowledge.wiki.ledger.events import LedgerEvent  # shared_log.py:15 (verified: events.py:103)
from parrot.knowledge.wiki.ledger.log import LedgerLog       # shared_log.py:16

# MUST be added by this task — shared_log.py imports no collections.abc names today
from collections.abc import Sequence

# test files (already present — reuse, do not re-add)
from parrot.knowledge.wiki.ledger import shared_log as sl      # test_ledger_shared_log.py:10
from parrot.knowledge.wiki.ledger.events import LedgerEvent    # test_ledger_shared_log.py:11
from parrot.knowledge.wiki.ledger.service import LedgerService # test_ledger_shared_log_service.py:12
```

### Existing Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py
class LedgerEvent(BaseModel):
    event_id: str            # line 107
    kind: LedgerEventKind    # line 108
    subject: str             # line 109  — e.g. "issue:fe3480881432"
    actor: str               # line 110
    ts: str                  # line 111
    payload: dict[str, Any]  # line 112  — a claim carries payload["claimed_by"]

# LedgerEventKind literal members (verified: events.py:8-14)
#   "issue.opened", "issue.claimed", "issue.acknowledged", "issue.closed",
#   "issue.superseded", "issue.unclaimed", "issue.linked"

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py
TERMINAL_ISSUE_STATUSES: frozenset[str]  # line 25 — {"closed", "superseded"}; the naming pattern to follow
def import_events(                        # line 165
    local: LedgerLog, repo_root: Path, marker: Path, *, force: bool = False
) -> tuple[SharedLogImportReport, list[LedgerEvent]]: ...
#   builds `imported_claims: list[LedgerEvent]` at line 189, appends at 200-201,
#   returns it as the tuple's second element at line 217

# tests/knowledge/wiki/test_ledger_shared_log.py — reuse these module-level helpers
def _event(kind: str, subject: str, actor: str = "agent:a", **payload: object) -> LedgerEvent:  # line 15
def _write_events(path: Path, *events: LedgerEvent) -> None:                                    # line 19

# tests/knowledge/wiki/test_ledger_shared_log_service.py
@pytest.fixture
def two_ledgers(tmp_path: Path) -> tuple[LedgerService, LedgerService, Path]:  # line 17
#   returns (local_service, foreign_service, checkout) over one temp checkout

# LedgerService methods the regression test uses (verified: service.py)
async def open_issue(...) -> str                       # used at test file line 39
async def claim(self, issue_id, claimed_by) -> bool    # used at test file line 58
async def unclaim(self, issue_id, reason, actor) -> bool   # service.py:426
async def export_shared_log(self, repo_root=None) -> SharedLogExportReport  # service.py:~580
async def import_shared_log(self, repo_root=None, *, force=False) -> SharedLogImportReport  # service.py:590
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `live_claims()` | `import_events`'s `imported_claims` | wraps the returned list | `shared_log.py:217` |
| `SUPERSEDING_CLAIM_KINDS` | `live_claims()` | membership test on `event.kind` | new |
| `live_claims()` | TASK-4579's `_shared_log_audit` | import by name (next task) | spec §2 |

### Does NOT Exist (Anti-Hallucination)

- ~~`shared_log.live_claims`~~ — this task creates it; nothing by that name exists
  (verified: `grep -rn "live_claims" packages/ tests/` → no matches).
- ~~`shared_log.SUPERSEDING_CLAIM_KINDS`~~ — created here.
- ~~`Sequence` in `shared_log.py`~~ — the module imports no `collections.abc`
  names (verified: `shared_log.py:1-27`). You must add the import.
- ~~`LedgerEvent.claimed_by`~~ — not a field; the claimant lives in
  `event.payload["claimed_by"]`.
- ~~`issue.unclaim` / `issue.claim` / `issue.reclaimed`~~ — not event kinds. The
  real kinds are listed in the signatures above.
- ~~`SharedLogImportReport.claim_conflict_count`~~ — the report has
  `claim_conflicts: list[ClaimConflict]` only (`shared_log.py:68`).
- ~~`packages/ai-parrot/tests/knowledge/wiki/`~~ — these tests live at the
  **repo root**: `tests/knowledge/wiki/`.
- ~~`LedgerEvent` ordering~~ — `LedgerEvent` is a Pydantic model and is **not**
  orderable; never `sorted()` events directly, sort by an explicit position key.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/knowledge/wiki/test_ledger_shared_log.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/knowledge/wiki/test_ledger_shared_log_service.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py#import_events",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#LedgerEvent"
  ]
}
```

---

## Implementation Notes

- **Why a dict keyed by subject**: the predicate is "the last claim per subject
  that nothing later revoked". A single ordered walk with a
  `dict[subject] -> (position, event)` gives exactly that — a later claim
  overwrites an earlier one, a later unclaim/close/supersede removes the entry.
- **Why `issue.superseded` counts as superseding**: `TERMINAL_ISSUE_STATUSES`
  (`shared_log.py:25`) already treats `closed` and `superseded` as terminal; a
  claim on a terminal issue cannot be a live conflict.
- **Why sort by position, not by `ts`**: FEAT-694 §8 Q1 explicitly rejected
  `ts`-ordered claim resolution; log order is the authority everywhere in this
  module. Keep the surviving claims in the order their claim events appeared.
- **Why only one call site changes**: `import_shared_log`'s loop is correct for
  any filtered input, so filtering at the `return` is the whole fix. Do not edit
  `service.py` in this task.

---

## Implementation Blueprint

### 1. `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'from pathlib import Path' shared_log.py)
# AFTER — insert below `from pathlib import Path` (verified: shared_log.py:10)
from collections.abc import Sequence
```

**Why**: `live_claims` takes a `Sequence[LedgerEvent]` so both a `list` (the
import path) and any other ordered sequence (the audit path) fit; the module has
no `collections.abc` import yet, so ruff would flag an undefined name.

```python
# occurrences: 1 (verified: grep -c 'TERMINAL_ISSUE_STATUSES: frozenset[str] = frozenset({"closed", "superseded"})' shared_log.py)
# AFTER — insert below `TERMINAL_ISSUE_STATUSES: frozenset[str] = frozenset({"closed", "superseded"})` (verified: shared_log.py:25)
SUPERSEDING_CLAIM_KINDS: frozenset[str] = frozenset({"issue.unclaimed", "issue.closed", "issue.superseded"})
```

**Why**: one named constant beside the existing terminal-status set, so the
supersession rule is readable and testable rather than three string literals
buried in a loop.

```python
# occurrences: 1 (verified: grep -c 'def import_events(' shared_log.py)
# BEFORE — insert above `def import_events(` (verified: shared_log.py:165)
def live_claims(events: Sequence[LedgerEvent]) -> list[LedgerEvent]:
    """Return the ``issue.claimed`` events that still stand within ``events``.

    Walks ``events`` in order, keeping at most one claim per subject — the most
    recent one — and dropping a subject entirely when a kind in
    :data:`SUPERSEDING_CLAIM_KINDS` for it follows its last claim. Pure: no I/O
    and the input is never mutated.

    This is the ONLY definition of a live claim. Both the import path
    (:func:`import_events`) and the audit path
    (``LedgerService._shared_log_audit``) route through it so they can never
    disagree about what counts as a conflict.

    Args:
        events: Ledger events in log order (archives before the current log).

    Returns:
        The surviving ``issue.claimed`` events, in the order their claim
        events appeared in ``events``.
    """
    survivors: dict[str, tuple[int, LedgerEvent]] = {}
    for position, event in enumerate(events):
        if event.kind == "issue.claimed":
            survivors[event.subject] = (position, event)
        elif event.kind in SUPERSEDING_CLAIM_KINDS:
            survivors.pop(event.subject, None)
    return [event for _, event in sorted(survivors.values(), key=lambda item: item[0])]
```

**Why**: `key=lambda item: item[0]` sorts on the integer position only —
`LedgerEvent` is a Pydantic model with no ordering, so a bare `sorted()` over the
tuples would raise `TypeError` as soon as two claims shared a position-free
comparison. `survivors.pop(..., None)` makes an unclaim for a never-claimed
subject a no-op rather than a `KeyError`.

```python
# occurrences: 1 (verified: grep -c '        imported_claims,' shared_log.py)
# REPLACE the line `        imported_claims,` (verified: shared_log.py:217)
        live_claims(imported_claims),
```

**Why**: the single point where the fix belongs — every consumer of
`import_events` now receives only live claims, so no caller can reintroduce the
spurious comparison. Keep the local accumulation as `imported_claims` so the
diff stays one line.

Also extend `import_events`'s docstring (`shared_log.py:168`) with one line:
`"""Append committed unknown events to a local log, archives before the current log.

    The returned claim list contains only live claims (:func:`live_claims`) — a
    claim superseded within the same batch is never reported as a conflict.
    """`

### 2. `tests/knowledge/wiki/test_ledger_shared_log.py` (MODIFY)

```python
# AFTER — append at end of file. Reuse the module-level `_event` helper
# (verified: test_ledger_shared_log.py:15) and the `sl` module alias (line 10).

def test_live_claims_drops_superseded_claim() -> None:
    """"A claims, A unclaims, B claims" leaves only B's claim (issue:fe3480881432)."""
    # FILL IN: build [claimed(A), unclaimed, claimed(B)] for one subject via
    #   _event("issue.claimed", "issue:1", claimed_by="task:a") etc.;
    #   assert [e.payload["claimed_by"] for e in sl.live_claims(events)] == ["task:b"]
    #   — bounded by AC1/AC2.


@pytest.mark.parametrize("terminal_kind", ["issue.closed", "issue.superseded"])
def test_live_claims_drops_closed_subject(terminal_kind: str) -> None:
    """A claim revoked by a terminal event for the same subject does not survive."""
    # FILL IN: [claimed, <terminal_kind>] for one subject → sl.live_claims(...) == []
    #   — bounded by AC1 (SUPERSEDING_CLAIM_KINDS covers both terminal kinds).


def test_live_claims_keeps_last_claim_per_subject() -> None:
    """Two claims with no revocation between them collapse to the later one."""
    # FILL IN: [claimed(A), claimed(B)] for one subject → exactly one survivor,
    #   claimed_by == "task:b" (last claim wins) — bounded by AC1.


def test_live_claims_is_pure_and_ignores_other_kinds() -> None:
    """Non-claim kinds are ignored, multiple subjects are independent, input is untouched."""
    # FILL IN: mix issue.opened / issue.linked / issue.acknowledged with claims on
    #   TWO subjects; assert both subjects' live claims come back in claim order,
    #   and that the input list is unchanged (compare to a pre-built copy)
    #   — bounded by AC1/AC7.
```

**Why**: these four tests pin the predicate itself, independently of any I/O, so
TASK-4579 can rely on it without re-testing the semantics. `pytest` is already
imported in this file (line 8).

### 3. `tests/knowledge/wiki/test_ledger_shared_log_service.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'async def test_import_detects_claim_conflict(two_ledgers: tuple[LedgerService, LedgerService, Path]) -> None:' test_ledger_shared_log_service.py)
# AFTER — insert below the body of `test_import_detects_claim_conflict` (verified: test_ledger_shared_log_service.py:55-71)

async def test_import_ignores_superseded_claim(two_ledgers: tuple[LedgerService, LedgerService, Path]) -> None:
    """A committed "A claims, A unclaims, B claims" history reports no conflict (issue:fe3480881432)."""
    local, foreign, checkout = two_ledgers
    # FILL IN: on `foreign`, open the issue, then claim("task:a") → unclaim(reason, actor)
    #   → claim("task:b"); export_shared_log(checkout). On `local`, open the same issue
    #   (same title/body ⇒ same deterministic issue id, as test_import_detects_claim_conflict
    #   relies on) and claim("task:b") so the final claimants AGREE.
    #   Then: report = await local.import_shared_log(checkout)
    #   assert report.claim_conflicts == []
    #   — bounded by AC2. Before the fix this reported a bogus task:a-vs-task:b conflict.
```

**Why**: the unit tests prove the predicate; this proves the predicate is
actually *wired into* the import path — the exact regression the ledger issue
describes. Keep `test_import_detects_claim_conflict` untouched directly above it;
it is the AC3 guard that the filter did not over-correct.

### Steps (in order)

1. Add the `Sequence` import — do it first, because the new function's
   annotation depends on it and ruff fails the file otherwise.
2. Add `SUPERSEDING_CLAIM_KINDS` beside `TERMINAL_ISSUE_STATUSES` — the
   constant is referenced by `live_claims`, so it must precede it.
3. Add `live_claims()` above `import_events` — because `import_events` calls it
   and module-level definition order keeps the file readable top-down.
4. Replace `imported_claims,` with `live_claims(imported_claims),` at the
   return, and extend the `import_events` docstring — this is the behavioural fix.
5. Write the four `live_claims` unit tests, then the service regression test.
6. Run the Validation Commands. `test_import_detects_claim_conflict` MUST still
   pass — if it fails, the filter is dropping genuine conflicts (AC3 violation),
   not just superseded ones.
7. `ruff check` the three files.

### FILL IN checklist

- [ ] `from collections.abc import Sequence` added (step 1)
- [ ] `SUPERSEDING_CLAIM_KINDS` with all three kinds (AC1)
- [ ] `live_claims()` complete, pure, position-ordered (AC1, AC7)
- [ ] `import_events` returns `live_claims(imported_claims)` + docstring line (AC2)
- [ ] four `live_claims` unit tests
- [ ] `test_import_ignores_superseded_claim` (AC2)
- [ ] `test_import_detects_claim_conflict` still passes unmodified (AC3)

---

## Acceptance Criteria

- [ ] `live_claims()` exists in `shared_log.py`, is pure (no I/O, input not
      mutated), keeps only the last claim per subject, and drops a subject whose
      claim is followed by `issue.unclaimed`, `issue.closed` or
      `issue.superseded` (spec AC1).
- [ ] `import_events` returns only live claims, so a superseded committed
      history produces **zero** `ClaimConflict`s (spec AC2).
- [ ] `test_import_detects_claim_conflict` passes unmodified — a genuine
      concurrent claim still yields exactly one conflict with the local claimant
      as `local_claimed_by` (spec AC3).
- [ ] The reducer and the first-claim-wins rule are untouched; no change to
      `service.py` or `cli.py` in this task (spec AC8).
- [ ] `ruff check` clean on the three touched files.

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_ledger_shared_log.py -q`
- `pytest tests/knowledge/wiki/test_ledger_shared_log_service.py -q`

---

## Test Specification

```python
# tests/knowledge/wiki/test_ledger_shared_log.py  (append)
# - test_live_claims_drops_superseded_claim
# - test_live_claims_drops_closed_subject  (parametrized: issue.closed, issue.superseded)
# - test_live_claims_keeps_last_claim_per_subject
# - test_live_claims_is_pure_and_ignores_other_kinds

# tests/knowledge/wiki/test_ledger_shared_log_service.py  (append after line 71)
# - test_import_ignores_superseded_claim
```

Run with `PYTHONPATH=packages/ai-parrot/src` from inside the feature worktree —
the shared `.venv` is editable-installed against the main checkout, so a bare
`pytest` would import the wrong branch.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug fixgroup-c2982b4864f3 --feature-id FEAT-717`)
2. **Read the spec** at `sdd/specs/fixgroup-c2982b4864f3.spec.md` (§2 and §3 Module 1)
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code; fix the contract
   first if anything moved
5. **Update status** in `sdd/tasks/index/fixgroup-c2982b4864f3.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
   marker and never change a signature the blueprint fixes
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the three files this task lists
9. **Close the task**: `scripts/sdd/close_task.sh TASK-4578 fixgroup-c2982b4864f3 verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: Claude Opus 5.5 (`/sdd-fix issue:fe3480881432`, SDD lane)
**Date**: 2026-10-22
**Notes**: `SUPERSEDING_CLAIM_KINDS` + `live_claims()` added to `shared_log.py`;
`import_events` returns `live_claims(imported_claims)` (one-line behavioural
change at the return). Six new unit tests for the predicate
(`test_live_claims_*`, one parametrized over `issue.closed` / `issue.superseded`)
plus `test_import_ignores_superseded_claim` at the service level.

Verified as a genuine red test: with the filter temporarily removed, the new
service test fails with exactly the bug the issue describes —
`ClaimConflict(local_claimed_by='task:b', foreign_claimed_by='task:a')` for the
revoked claim — while `test_import_detects_claim_conflict` still passes. With the
filter restored both pass.

Evidence: `pytest tests/knowledge/wiki/test_ledger_shared_log.py -q` → 15 passed;
`test_ledger_shared_log_service.py -q` → 5 passed; the whole shared-log selection
(`-k "shared_log or import_log or export_log or rotate_log"`) → 32 passed;
`ruff check` and `black --check --line-length 120` clean on all three files
(both were clean on `origin/dev` too, so the backlog did not grow).

**Deviations from spec**: two cosmetic ones, no behavioural difference.
1. `from collections.abc import Sequence` was placed in sorted position (before
   `from datetime import ...`) rather than literally below `from pathlib import
   Path` as the blueprint wrote — ruff's `I` family is not selected in
   `ruff.toml`, so either position lints clean; sorted reads better.
2. `test_live_claims_drops_superseded_claim`'s docstring was reworded because the
   blueprint's version began with a quote character (`""""A claims, ...`), which
   `black` reformats to a quad-quote with a space. Same meaning.
