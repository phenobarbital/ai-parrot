# TASK-4579: Stateless `claim_conflicts` count in `ledger audit` + CLI line

**Feature**: FEAT-717 — Shared-log claim conflicts (stateless audit count and superseded-claim filter)
**Spec**: `sdd/specs/fixgroup-c2982b4864f3.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4578
**Discovered-from**: `issue:fe3480881432`
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Modules 2 and 3**. `issue:fe3480881432`'s first half: claim
conflicts live **only** in the transient `SharedLogImportReport` returned by
`import_shared_log`. Every FEAT-694 ledger git-hook line ends in `|| true` and
redirects its output (FEAT-694 AC12), so a conflict detected during a
hook-driven import is printed to `/dev/null` and is then unrecoverable —
nothing persists it and nothing recomputes it. FEAT-694 **AC10** requires a
conflict to be "counted in `ledger audit`"; `_shared_log_audit`
(`service.py:676`) returns only five keys and that clause is unmet.

This task makes `ledger audit` recompute the count **statelessly** from the
committed log on every call, using the `live_claims()` predicate TASK-4578
added — so the audit and the import path agree by construction (spec G4), and
the count is correct even in a process that never ran an import.

---

## Scope

- Thread local issue state into `_shared_log_audit` so the blocking method can
  compare claimants without awaiting.
- Add a `claim_conflicts: int` key to the `shared_log` audit dict, recomputed
  from `shared_log_files` via `live_claims()`.
- Print `  claim conflicts: N` from `wikitoolkit ledger audit` when non-zero.
- Tests for the audit count (both directions) and the CLI line.

**NOT in scope**:
- `live_claims()` itself and the `import_events` filter — TASK-4578.
- `import_shared_log` and its `ClaimConflict` list — unchanged.
- The `import-log` CLI conflict line (`cli.py:3665-3669`) — already correct.
- Renaming, retyping or re-ordering the five existing `shared_log` audit keys
  (spec AC5), or any other `audit()` key.
- Persisting conflicts to the index or the log — the fix is recomputation, not storage.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `audit()` resolves issue state; `_shared_log_audit(issues)` adds `claim_conflicts` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Print the conflict count in `ledger audit` |
| `tests/knowledge/wiki/test_ledger_shared_log_service.py` | MODIFY | Audit-count tests (conflict / superseded) |
| `tests/knowledge/wiki/test_cli_ledger_shared_log.py` | MODIFY | CLI output test |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `04f0bc87d` (dev, 2026-10-22). TASK-4578's additions are marked
> **(from TASK-4578)** — verify they landed before starting.

### Verified Imports

```python
# service.py — already imported at the top; `Mapping` MUST be added to this line
from collections.abc import Collection, Sequence  # service.py:17 → add Mapping
from typing import TYPE_CHECKING, Any             # service.py:20

# inside _shared_log_audit's local import block (service.py:678-686) — add live_claims,
# and DROP read_shared_event_ids (it becomes unused; ruff F401 otherwise)
from parrot.knowledge.wiki.ledger.shared_log import (
    MARKER_FILENAME,        # shared_log.py:23
    SHARED_LOG_REL_PATH,    # shared_log.py:20
    digest_files,           # shared_log.py:125
    is_shareable,           # shared_log.py:71
    live_claims,            # (from TASK-4578)
    read_raw_events,        # shared_log.py:97
    shared_log_files,       # shared_log.py:103
)

# cli.py — already imported, do NOT re-add
from parrot.knowledge.wiki.ledger.shared_log import shared_log_files  # used at cli.py:3798

# tests — already present
from parrot.knowledge.wiki.cli import ledger                       # test_cli_ledger_shared_log.py:11
from parrot.knowledge.wiki.ledger.service import LedgerService     # both test files
from click.testing import CliRunner                                # test_cli_ledger_shared_log.py:9
from unittest.mock import AsyncMock, MagicMock, patch              # test_cli_ledger_shared_log.py:7
```

### Existing Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
class LedgerService:
    shared_root: Path  # the checkout holding sdd/ledger; reassigned directly in tests
    async def _all_issues(self) -> list[tuple[str, dict[str, Any]]]:  # line 227
        """Return ``(issue_id, state)`` for every decodable issue page."""
    async def audit(self) -> dict[str, Any]:                          # line 646
    def _shared_log_audit(self) -> dict[str, Any]:                    # line 676 — gains `issues`

# audit()'s body, for the insertion points (verified: service.py:646-674)
#   648:  offset, last_event_id = await self.store.read_cursor()
#   663:  broken_edges = broken_row[0] if broken_row else 0
#   665:  return {
#   672:      "shared_log": await asyncio.to_thread(self._shared_log_audit),

# _shared_log_audit's current body (verified: service.py:676-705)
#   678-686: local import block from shared_log
#   688: files = shared_log_files(self.shared_root)
#   689: committed = read_shared_event_ids(files)
#   690: local_events = read_raw_events(Path(self.log.path))
#   691: local = {event.event_id for _, event in local_events if is_shareable(event)}
#   692: all_local_ids = {event.event_id for _, event in local_events}
#   693-699: marker_state resolution
#   700-705: the five-key return dict

# the issue-state dict shape (verified in use at service.py:617-626 and 449-454)
#   state["status"] in ("open", "claimed", "closed", ...); state["claimed_by"] when claimed

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py
def shared_log_files(repo_root: Path) -> list[Path]:               # line 103 — archives, then current
def read_raw_events(path: Path) -> list[tuple[str, LedgerEvent]]:  # line 97
def read_shared_event_ids(files: list[Path]) -> set[str]:          # line 111 — == {ids from read_raw_events over files}
def live_claims(events: Sequence[LedgerEvent]) -> list[LedgerEvent]:  # (from TASK-4578)

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py — ledger_audit (verified: cli.py:3787-3812)
#   3795: click.echo(f"Total events: {audit['total_events']}")
#   3796: shared = audit.get("shared_log")
#   3797: if shared:
#   3798:     archive_count = max(0, len(shared_log_files(service.shared_root)) - int(shared["exists"]))
#   3799-3803: the single "Shared log: …" click.echo(...)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `issues` map | `LedgerService._all_issues()` | `dict(await self._all_issues())` — the idiom the import path already uses | `service.py:617` |
| `_shared_log_audit(issues)` | `audit()` | `asyncio.to_thread(self._shared_log_audit, issues)` | `service.py:672` |
| `live_claims()` | `_shared_log_audit` | called on the committed events of `shared_log_files` | TASK-4578 |
| `claim conflicts` line | `ledger_audit` | `click.echo` after the `Shared log:` block | `cli.py:3799-3803` |

### Does NOT Exist (Anti-Hallucination)

- ~~`audit()["shared_log"]["claim_conflicts"]`~~ — this task creates the key;
  `_shared_log_audit` returns exactly five keys today (`service.py:700-705`).
- ~~`Mapping` in `service.py`~~ — line 17 imports only `Collection, Sequence`
  from `collections.abc`. You must add it.
- ~~`LedgerService.get_claim_conflicts` / `.claim_conflicts`~~ — no such
  attribute or method.
- ~~`SharedLogImportReport` in the audit path~~ — the count must **not** be read
  from an import report (that is the bug: spec G1). Recompute every call.
- ~~`await` inside `_shared_log_audit`~~ — it is a **blocking** method run via
  `asyncio.to_thread` (`service.py:672`). It cannot await `_all_issues()`;
  that is precisely why `issues` is a parameter.
- ~~`LedgerService.unclaim_issue`~~ — `unclaim` is the service method
  (`service.py:426`); `unclaim_issue` belongs to `LedgerIndex` (`index.py:497`).
- ~~`packages/ai-parrot/tests/knowledge/wiki/`~~ — these tests live at the
  **repo root**: `tests/knowledge/wiki/`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/knowledge/wiki/test_ledger_shared_log_service.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/knowledge/wiki/test_cli_ledger_shared_log.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.audit",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService._shared_log_audit",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py#live_claims"
  ]
}
```

---

## Implementation Notes

- **Why `issues` becomes a parameter**: `_shared_log_audit` is dispatched with
  `asyncio.to_thread` because it does blocking file I/O. It therefore cannot
  `await self._all_issues()`. Resolving the map in the async `audit()` and
  passing it down keeps the method synchronous and keeps the SQLite read on the
  event loop's own connection, where every other read in `audit()` already is.
- **Why reuse `read_raw_events` instead of `read_shared_event_ids`**: the count
  needs the committed *events*, not just their ids, and
  `read_shared_event_ids(files)` is by definition the ids of exactly those
  events (`shared_log.py:111`). Reading the files once and deriving both the id
  set and the claim list keeps the audit's cost unchanged — it does not add a
  second pass over the log. Drop the now-unused import.
- **Why "non-zero only" in the CLI**: a clean ledger's `audit` output stays
  byte-identical to today's, so no existing output test breaks and the line is
  pure signal when it appears.
- **Why the count can differ from `len(report.claim_conflicts)`**: the audit
  compares *all* committed live claims against local state, while an import
  report only covers the claims that batch newly added. Both use the same
  predicate; neither is wrong. Do not assert equality between them.

---

## Implementation Blueprint

### 1. `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'from collections.abc import Collection, Sequence' service.py)
# REPLACE the line `from collections.abc import Collection, Sequence` (verified: service.py:17)
from collections.abc import Collection, Mapping, Sequence
```

**Why**: `_shared_log_audit`'s new parameter is annotated `Mapping[str, dict[str, Any]]`
— read-only is the honest type, since the method must never mutate caller state.

```python
# occurrences: 1 (verified: grep -c '        broken_edges = broken_row[0] if broken_row else 0' service.py)
# AFTER — insert below `        broken_edges = broken_row[0] if broken_row else 0` (verified: service.py:663)
        issues = dict(await self._all_issues())
```

**Why**: resolve the issue state on the event loop, before the blocking
hand-off — this is the same `dict(await self._all_issues())` idiom
`import_shared_log` already uses at `service.py:617`, so there is one way to get
this map, not two.

```python
# occurrences: 1 (verified: grep -c '"shared_log": await asyncio.to_thread(self._shared_log_audit),' service.py)
# REPLACE the line `            "shared_log": await asyncio.to_thread(self._shared_log_audit),` (verified: service.py:672)
            "shared_log": await asyncio.to_thread(self._shared_log_audit, issues),
```

**Why**: `asyncio.to_thread` forwards positional arguments to the callable, so
the blocking method receives the already-resolved map.

```python
# occurrences: 1 (verified: grep -c '    def _shared_log_audit(self) -> dict[str, Any]:' service.py)
# REPLACE the signature + docstring at `    def _shared_log_audit(self) -> dict[str, Any]:` (verified: service.py:676)
    def _shared_log_audit(self, issues: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
        """Blocking: compare the local log with the committed logical shared log.

        Args:
            issues: ``{issue_id: state}`` resolved by :meth:`audit` — this method
                cannot await, so local state is passed in.

        Returns:
            The five drift/marker keys plus ``claim_conflicts``: the number of
            live committed claims whose claimant differs from a locally
            ``claimed`` issue's claimant. Recomputed from the committed files on
            every call and NEVER read from a ``SharedLogImportReport``, which the
            git hooks discard (FEAT-694 AC10, AC12).
        """
```

```python
# In the local import block (verified: service.py:678-686): add `live_claims,`
# in alphabetical position and REMOVE `read_shared_event_ids,` — it becomes unused.

# occurrences: 1 (verified: grep -c '        committed = read_shared_event_ids(files)' service.py)
# REPLACE the line `        committed = read_shared_event_ids(files)` (verified: service.py:689)
        committed_events = [event for path in files for _, event in read_raw_events(path)]
        committed = {event.event_id for event in committed_events}
```

**Why**: one pass over the committed files now yields both the id set the
existing drift keys need and the event list `live_claims` needs. The id set is
identical to what `read_shared_event_ids(files)` returned, so the four existing
drift values are unchanged (AC5).

```python
# occurrences: 1 (verified: grep -c '        return {' service.py within _shared_log_audit — see line 700)
# AFTER — insert below the marker_state resolution and BEFORE `        return {` (verified: service.py:700)
        conflicts = 0
        for event in live_claims(committed_events):
            state = issues.get(event.subject)
            if state is not None and state.get("status") == "claimed" and state.get("claimed_by") != event.payload.get(
                "claimed_by"
            ):
                conflicts += 1
```

**Why**: the same three-part predicate `import_shared_log` uses at
`service.py:618` — the issue exists locally, is still claimed, and the claimant
differs — but counted over every live committed claim rather than one import
batch. `live_claims` is what keeps a superseded claim from inflating the count.

```python
# AFTER — add as the last entry of the returned dict (verified: service.py:700-705)
            "claim_conflicts": conflicts,
```

**Why**: additive. The five existing keys keep their names, order and values
(AC5), so no existing consumer or test changes.

### 2. `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'f"committed-unknown events: {shared[\'committed_unknown_events\']} · marker: {shared[\'marker\']}"' cli.py)
# AFTER — insert below the closing `)` of the "Shared log: …" click.echo, still inside `if shared:` (verified: cli.py:3799-3803)
        if shared.get("claim_conflicts"):
            click.echo(f"  claim conflicts: {shared['claim_conflicts']}")
```

**Why**: `.get` keeps the CLI tolerant of an older audit dict (remote/proxied
callers), and the truthiness test means a zero count prints nothing — so the
clean-ledger output stays byte-identical and only a real conflict adds a line.
Mind the indentation: this sits inside `if shared:` at 8 spaces, with the
`click.echo` at 12.

### 3. `tests/knowledge/wiki/test_ledger_shared_log_service.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'async def test_audit_reports_shared_log_block(two_ledgers: tuple[LedgerService, LedgerService, Path]) -> None:' test_ledger_shared_log_service.py)
# AFTER — append below the body of `test_audit_reports_shared_log_block` (verified: test_ledger_shared_log_service.py:90-105)

async def test_audit_counts_claim_conflicts(two_ledgers: tuple[LedgerService, LedgerService, Path]) -> None:
    """A genuine divergent claim is counted by audit with no prior import (issue:fe3480881432)."""
    local, foreign, checkout = two_ledgers
    # FILL IN: mirror test_import_detects_claim_conflict's setup — local opens + claims
    #   "task:local"; foreign opens the same issue + claims "task:foreign";
    #   foreign.export_shared_log(checkout); then `local.shared_root = checkout`
    #   (the pattern used by test_audit_reports_shared_log_block:97).
    #   Call `await local.audit()` WITHOUT calling import_shared_log first —
    #   that is what proves the count is stateless (AC4).
    #   assert audit["shared_log"]["claim_conflicts"] == 1


async def test_audit_claim_conflicts_ignores_superseded(
    two_ledgers: tuple[LedgerService, LedgerService, Path]
) -> None:
    """A superseded committed claim history counts zero conflicts."""
    # FILL IN: foreign claims "task:a" → unclaim → claims "task:b", exports; local opens
    #   the same issue and claims "task:b" so the live claimants agree;
    #   local.shared_root = checkout; audit()["shared_log"]["claim_conflicts"] == 0
    #   — bounded by AC4 + spec AC2 (same predicate as the import path).


async def test_audit_preserves_existing_shared_log_keys(
    two_ledgers: tuple[LedgerService, LedgerService, Path]
) -> None:
    """The five pre-existing keys keep their names and values when the new key is added."""
    # FILL IN: assert set(audit["shared_log"]) == {"path", "exists", "local_only_events",
    #   "committed_unknown_events", "marker", "claim_conflicts"} and that the five
    #   originals still match test_audit_reports_shared_log_block's expectations
    #   — bounded by AC5.
```

**Why**: `test_audit_counts_claim_conflicts` is the AC4 proof and must not call
`import_shared_log` — an import would make the test pass even if the count were
read from a report, which is the bug. `test_audit_reports_shared_log_block`
directly above stays untouched as the AC5 guard.

### 4. `tests/knowledge/wiki/test_cli_ledger_shared_log.py` (MODIFY)

```python
# AFTER — append at end of file. Follow the existing MagicMock(spec=LedgerService)
# + patch("parrot.knowledge.wiki.cli.LedgerService.from_root") pattern
# (verified: test_cli_ledger_shared_log.py:24-29).

def test_cli_audit_prints_claim_conflicts(tmp_path: Path, monkeypatch) -> None:
    """`ledger audit` prints the conflict count when non-zero and omits it at zero."""
    # FILL IN: build a MagicMock(spec=LedgerService) whose `audit` is an AsyncMock
    #   returning a full audit dict (log_size_bytes, event_counts, total_events,
    #   cursor_offset, cursor_lag_events, broken_edges, sqlite, and a shared_log
    #   block carrying claim_conflicts=2); set `service.shared_root = tmp_path`
    #   because cli.py:3798 calls shared_log_files(service.shared_root).
    #   Invoke CliRunner().invoke(ledger, ["audit"]) under the from_root patch and
    #   assert "claim conflicts: 2" in result.output.
    #   Then re-invoke with claim_conflicts=0 and assert "claim conflicts" NOT in output
    #   — bounded by AC6.
    #   Note: ledger_audit is decorated @remote_cli.remote_aware(proxied=False), so
    #   monkeypatch "parrot.knowledge.wiki.remote_cli.remote_or_none" to
    #   (None, None, None) exactly as test_cli_export_log_stage_runs_git_add:17 does.
```

**Why**: a mocked service keeps this a pure CLI-rendering test — the counting
logic is already covered by the service tests, and the `remote_aware` decorator
must be neutralized or the command short-circuits to a remote call.

### Steps (in order)

1. **Verify TASK-4578 landed**: `grep -n "def live_claims" packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py`
   must hit. If not, stop — this task depends on it.
2. Add `Mapping` to the `collections.abc` import (step 1 of the file edits),
   because the new signature references it.
3. Change `_shared_log_audit`'s signature and docstring, then its body
   (import block, `committed_events`, the conflict loop, the new dict key) —
   signature first so the body is written against the final parameter list.
4. Change `audit()`: add `issues = ...` then pass it to `to_thread`. Do this
   **after** step 3, so the method never exists in a state where callers pass an
   argument it does not accept.
5. Add the CLI line.
6. Write the three service tests and the CLI test.
7. Run the Validation Commands; `test_audit_reports_shared_log_block` and
   `test_import_detects_claim_conflict` MUST still pass.
8. `ruff check` the four files — confirm `read_shared_event_ids` was removed
   from the local import block (F401) and that `Mapping` is used.

### FILL IN checklist

- [ ] `Mapping` added to `service.py:17`
- [ ] `_shared_log_audit(self, issues: Mapping[...])` + docstring (AC4)
- [ ] local import block: `live_claims` in, `read_shared_event_ids` out
- [ ] `committed_events` single pass; `committed` derived from it (AC5)
- [ ] conflict loop + `"claim_conflicts": conflicts` key (AC4)
- [ ] `audit()` resolves `issues` and forwards it (AC4)
- [ ] CLI line, non-zero only (AC6)
- [ ] three service tests + one CLI test
- [ ] `test_audit_reports_shared_log_block` passes unmodified (AC5)

---

## Acceptance Criteria

- [ ] `audit()["shared_log"]["claim_conflicts"]` is an `int`, recomputed from
      `shared_log_files` on every call, and correct with **no** prior
      `import_shared_log` in the same process (spec AC4 — statelessness).
- [ ] A superseded committed history counts `0`; a genuine divergent claim
      counts `1` (spec AC2/AC4, via `live_claims`).
- [ ] The five pre-existing `shared_log` keys are unchanged in name, type and
      value; `test_audit_reports_shared_log_block` passes unmodified (spec AC5).
- [ ] `wikitoolkit ledger audit` prints `  claim conflicts: N` when non-zero and
      emits no such line when zero (spec AC6).
- [ ] The audit path gets its live claims from `live_claims()` — no second copy
      of the predicate (spec AC7, verifiable by `grep -rn "issue.unclaimed"`).
- [ ] FEAT-694 AC10 is satisfied end to end: import report, `import-log` CLI
      output, **and** `ledger audit` (spec AC10).
- [ ] `ruff check` clean on the four touched files.

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_ledger_shared_log_service.py -q`
- `pytest tests/knowledge/wiki/test_cli_ledger_shared_log.py -q`
- `pytest tests/knowledge/wiki/test_ledger_shared_log.py -q`

---

## Test Specification

```python
# tests/knowledge/wiki/test_ledger_shared_log_service.py  (append after line 105)
# - test_audit_counts_claim_conflicts              (no import first — AC4)
# - test_audit_claim_conflicts_ignores_superseded
# - test_audit_preserves_existing_shared_log_keys  (AC5)

# tests/knowledge/wiki/test_cli_ledger_shared_log.py  (append)
# - test_cli_audit_prints_claim_conflicts          (AC6, both directions)
```

Run with `PYTHONPATH=packages/ai-parrot/src` from inside the feature worktree —
the shared `.venv` is editable-installed against the main checkout, so a bare
`pytest` would import the wrong branch.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug fixgroup-c2982b4864f3 --feature-id FEAT-717`)
2. **Read the spec** at `sdd/specs/fixgroup-c2982b4864f3.spec.md` (§2 and §3 Modules 2–3)
3. **Check dependencies** — `TASK-4578` must be `"done"` in
   `sdd/tasks/index/fixgroup-c2982b4864f3.json`
4. **Verify the Codebase Contract** before writing any code, including that
   `live_claims` exists
5. **Update status** in `sdd/tasks/index/fixgroup-c2982b4864f3.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
   marker and never change a signature the blueprint fixes
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the four files this task lists
9. **Close the task**: `scripts/sdd/close_task.sh TASK-4579 fixgroup-c2982b4864f3 verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: Claude Opus 5 (`/sdd-fix issue:fe3480881432`, SDD lane)
**Date**: 2026-10-22
**Notes**: `audit()` now resolves `dict(await self._all_issues())` and forwards it
to `_shared_log_audit(issues)`, which stays blocking (it runs under
`asyncio.to_thread` and cannot await). The committed files are read once:
`committed_events` feeds both the existing id-set drift keys and `live_claims()`,
so `read_shared_event_ids` is no longer imported there and the five pre-existing
keys keep their names, order and values. `cli.py` prints `  claim conflicts: N`
only when non-zero.

Four new service tests (`test_audit_counts_claim_conflicts` — which deliberately
never calls `import_shared_log`, the AC4 statelessness proof;
`..._ignores_superseded`; `..._zero_when_claimants_agree`;
`test_audit_preserves_existing_shared_log_keys` for AC5) plus
`test_cli_audit_prints_claim_conflicts` covering both output directions.

Verified as a genuine red test: with `live_claims(committed_events)` temporarily
replaced by an unfiltered claim list, `test_audit_claim_conflicts_ignores_superseded`
fails `assert 1 == 0` while the other audit tests still pass — so the audit path
really does depend on the shared predicate (AC7), not just on the new key existing.

Evidence: targeted run (`test_ledger_shared_log.py`,
`test_ledger_shared_log_service.py`, `test_cli_ledger_shared_log.py`) → 27 passed;
the whole `tests/knowledge/wiki/` suite → **2079 passed, 11 skipped** in 150.93s;
`ruff check` and `black --check --line-length 120` clean on all six files the
feature touched (all six were clean on `origin/dev` too, so the lint backlog did
not grow).

**Deviations from spec**: none. One mechanical note: `black` rewrapped three new
test signatures in `test_ledger_shared_log_service.py` (one collapsed to a single
line, one gained a trailing comma) — formatting only, no behavioural change.
