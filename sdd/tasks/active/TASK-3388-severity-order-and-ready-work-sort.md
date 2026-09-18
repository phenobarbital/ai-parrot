# TASK-3388: Canonical `SEVERITY_ORDER` in `events.py` and severity-sorted `ready_work()`

**Feature**: FEAT-572 — `/sdd-fix` Ledger-Driven Fix Lane
**Spec**: `sdd/specs/sdd-fix-ledger-lane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3387
**Assigned-to**: unassigned

---

## Context

Spec §1 Problem 1 ("No severity ordering"), §2 Data Models and §3 Module 2, adopted from
design-research finding **S6**. `LedgerService.ready_work()` returns rows in SQLite row
order, and `ledger ready`, `/sdd-next` and the MCP `ledger_ready` tool print that order
verbatim — a `low` "leftover comment" prints above a `major` session leak.

The ordering must be defined **once**, beside the `IssueSeverity` Literal it orders, so the
planner (TASK-3389), `ready_work()`, the CLI and the MCP tool all share one key. Putting it
in the planner alone would leave the operator-facing path with the very defect this feature
exists to fix.

Depends on TASK-3387 only because both tasks edit `events.py` (file-overlap serialization);
nothing here uses `issue.unclaimed`.

---

## Scope

- Add `SEVERITY_ORDER: Final[dict[IssueSeverity, int]]` to `events.py` directly below the
  `IssueStatus` Literal, with a docstring stating it is the single definition.
- Sort `LedgerService.ready_work()` output by `(SEVERITY_ORDER[severity], issue_id)`; the
  filter predicate is unchanged. Unknown severities sort last.
- Tests: order is total and canonical; `ready_work()` is severity-ordered with `issue_id`
  ties; `ledger ready` (CLI) inherits the order through a real service.

**NOT in scope**: `unclaim()` / `close_issue(resolved_by=)` / `feature_index_status()`
(TASK-3391); the planner (TASK-3389); any `cli.py` change — the CLI test here exercises the
*existing* `ledger ready` command unmodified.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py` | MODIFY | `Final` import + `SEVERITY_ORDER` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | import `SEVERITY_ORDER`; sort in `ready_work()` |
| `tests/knowledge/wiki/test_ledger_events.py` | MODIFY | `test_severity_order_is_total_and_canonical` |
| `tests/knowledge/wiki/test_ledger_service.py` | MODIFY | `test_ready_work_is_severity_ordered` |
| `tests/knowledge/wiki/test_cli_ledger.py` | MODIFY | `test_ledger_ready_cli_prints_severity_order` (real service) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.events import IssueSeverity, LedgerEvent   # verified: ledger/events.py:22,83
from parrot.knowledge.wiki.ledger.service import LedgerService              # verified: ledger/service.py:96
from parrot.knowledge.wiki.ledger.index import LedgerIndex                  # verified: ledger/index.py:85
from parrot.knowledge.wiki.ledger.log import LedgerLog                      # verified: ledger/log.py
from parrot.knowledge.wiki.ledger.store import LedgerStore                  # verified: ledger/store.py
from parrot.knowledge.wiki.store import SQLitePragmaPolicy                  # verified: tests/knowledge/wiki/test_ledger_service.py:14
from parrot.knowledge.wiki.cli import ledger                                # verified: tests/knowledge/wiki/test_cli_ledger.py:17 (click group)
from click.testing import CliRunner                                         # verified: test_cli_ledger.py:15
from typing import Final, get_args                                          # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py
from typing import Any, Literal                                                # line 4  ← becomes `Any, Final, Literal`
IssueSeverity = Literal["critical", "major", "minor", "low"]                  # line 22
IssueStatus = Literal["open", "claimed", "closed", "superseded"]              # line 23  ← SEVERITY_ORDER goes right below

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
from parrot.knowledge.wiki.ledger.events import (                             # lines 20-25
    IssueKind,                                                                # 21
    IssueOpenedPayload,                                                       # 22
    LedgerEvent,                                                              # 23
    compute_issue_id,                                                         # 24
)
def _issue_dict(issue_id: str, state: dict[str, Any]) -> dict[str, Any]:      # 78 — keys incl. "severity", "issue_id"
class LedgerService:
    async def ready_work(self, kind: IssueKind | None = None) -> list[dict[str, Any]]:  # 199
        await self._sync_best_effort()                                        # 201
        issues = await self._all_issues()                                     # 202
        return [ _issue_dict(issue_id, state) for issue_id, state in issues
                 if state.get("status") == "open" and (kind is None or state.get("kind") == kind) ]  # 203-207
    async def open_issue(self, title, body, kind="bug", severity: str = "minor", discovered_from="", about=None, actor="agent:sdd") -> str  # 166

# tests/knowledge/wiki/test_ledger_service.py
@pytest.fixture ledger_service(tmp_path) -> LedgerService   # line 17-29: LedgerStore(tmp/.parrot/ledger/ledger.db, wiki_name="ledger",
                                                            #   sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0)); LedgerLog; LedgerIndex; shared_root=tmp_path
class TestOpenReadyClaim:                                   # line 63 — add the new test inside this class
    async def test_ready_work_filters_by_kind(self, ledger_service)  # 75

# tests/knowledge/wiki/test_cli_ledger.py
@pytest.fixture runner() -> CliRunner                       # 22
@pytest.fixture mock_ledger_service(tmp_path) -> MagicMock  # 28  (NOT used by the new test — it needs a real service)
def test_ledger_ready_lists_issues(runner, mock_ledger_service)  # 176-196: pattern
    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = runner.invoke(ledger, ["ready"])
# last test in file: def test_ledger_audit_command(...)      # 401
# cli.py ledger_ready prints: f"{issue['issue_id']} [{issue['severity']}] {issue['title']} ({issue['kind']})"  # cli.py:2690
```

### Does NOT Exist
- ~~`SEVERITY_ORDER`~~ anywhere in `ledger/` — this task creates the ONLY definition. Never
  define a second copy in `service.py`, `cli.py`, `tools.py` or the planner.
- ~~`ready_work(sort=...)` / `order_by` parameter~~ — the sort is unconditional.
- ~~`claimed_by` filtering in `ready_work()`~~ — the predicate tests `status == "open"` only;
  it is correct because `_apply_issue_claimed` flips `status`. **Do not "fix" it.**
- ~~a `ledger ready --sort` flag~~ — no CLI change in this task.
- ~~`IssueSeverity` as an Enum~~ — it is a `Literal`; iterate members with `typing.get_args`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_events.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_service.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_cli_ledger.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#IssueSeverity",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.ready_work",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.open_issue",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#_issue_dict",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger_ready"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Ordering `ready_work()` changes existing output** (spec §7). Any existing test that
  asserted row order must be updated, not worked around. `test_ready_work_filters_by_kind`
  compares sets/ids — check it still passes as written.
- Unknown severity (a row with a future value) sorts **last** via
  `SEVERITY_ORDER.get(sev, len(SEVERITY_ORDER))` — the ledger must not crash on a field it
  does not recognise.
- Tie-break on `issue_id` makes the output deterministic (S2 depends on it downstream).
- The CLI test must use a **real** `LedgerService` (wired like the `ledger_service` fixture)
  — a mock returning pre-sorted rows would prove nothing.
- Run with `PYTHONPATH=packages/ai-parrot/src` inside a worktree.

### References in Codebase
- `tests/knowledge/wiki/test_ledger_service.py:17-29` — fixture to copy into the CLI test.
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2681-2695` — `ledger_ready`, unchanged consumer.

---

## Implementation Blueprint

### Steps (in order)
1. Add `Final` to the typing import and `SEVERITY_ORDER` below `IssueStatus` — *why*: the constant must sit beside the Literal it orders (S6) and be importable by `service.py` and the planner.
2. Import `SEVERITY_ORDER` in `service.py` and sort inside `ready_work()` — *why*: every consumer (`ledger ready`, `/sdd-next`, MCP `ledger_ready`) inherits the order for free.
3. Add the three tests; run the three files — *why*: the CLI test proves the operator path is fixed, not just the service.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'from typing import Any, Literal' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py)
# REPLACE the line `from typing import Any, Literal` (verified: events.py:4) with:
from typing import Any, Final, Literal
```
```python
# occurrences: 1 (verified: grep -cF 'IssueStatus = Literal["open", "claimed", "closed", "superseded"]' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py)
# AFTER — insert below that line (verified: events.py:23), one blank line between
SEVERITY_ORDER: Final[dict[IssueSeverity, int]] = {"critical": 0, "major": 1, "minor": 2, "low": 3}
"""Canonical severity order, most urgent first (FEAT-572, design research S6).

Defined HERE, beside the Literal it orders, so ``LedgerService.ready_work()``,
the fix planner, ``wikitoolkit ledger ready`` and the MCP ``ledger_ready`` tool
all share one key. Never redefine it in a consumer — import it.
"""
```
**Why this shape**: a `Final` mapping keyed by the Literal gives `mypy` the same member set as
`IssueSeverity`; the docstring is the guard against a second copy appearing later.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    LedgerEvent,' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py)
# AFTER — insert below `    LedgerEvent,` in the events import block (verified: service.py:23)
    SEVERITY_ORDER,
```
```python
# occurrences: 1 (verified: grep -cF 'if state.get("status") == "open" and (kind is None or state.get("kind") == kind)' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py)
# REPLACE the whole `return [ ... ]` comprehension of ready_work (verified: service.py:203-207) with:
        rows = [
            _issue_dict(issue_id, state)
            for issue_id, state in issues
            if state.get("status") == "open" and (kind is None or state.get("kind") == kind)
        ]
        rows.sort(key=lambda row: (SEVERITY_ORDER.get(row["severity"], len(SEVERITY_ORDER)), row["issue_id"]))
        return rows
# and REPLACE the docstring on line 200 with:
        """Return unclaimed, open issues sorted by ``(SEVERITY_ORDER, issue_id)``.

        The filter predicate is unchanged; only the ordering is new (FEAT-572 S6).
        ``ledger ready``, ``/sdd-next`` and the MCP ``ledger_ready`` tool inherit it.
        """
```
**Why**: the predicate is untouched (spec: "Do not 'fix' it"); `.get(..., len(...))` keeps a
future severity from raising; the `issue_id` tie-break is what makes plans byte-deterministic.

### `tests/knowledge/wiki/test_ledger_events.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def test_insight_recorded_payload():' tests/knowledge/wiki/test_ledger_events.py)
# AFTER — append at end of file (TASK-3387 already appended three tests below :98; add after those).
# Extend the import block with `IssueSeverity, SEVERITY_ORDER` (and `from typing import get_args` if TASK-3387 did not add it).


def test_severity_order_is_total_and_canonical():
    members = get_args(IssueSeverity)
    assert set(SEVERITY_ORDER) == set(members), "every IssueSeverity member must have a rank"
    assert sorted(SEVERITY_ORDER, key=SEVERITY_ORDER.__getitem__) == ["critical", "major", "minor", "low"]
    assert sorted(SEVERITY_ORDER.values()) == list(range(len(members)))
```

### `tests/knowledge/wiki/test_ledger_service.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'class TestOpenReadyClaim:' tests/knowledge/wiki/test_ledger_service.py)
# INSIDE class TestOpenReadyClaim (verified: :63), add as its last method (after test_claim_delegates_to_index, :86-91)
    async def test_ready_work_is_severity_ordered(self, ledger_service):
        """critical → major → minor → low, ties broken by issue_id (S6)."""
        for sev in ("low", "critical", "minor", "major"):
            await ledger_service.open_issue(title=f"{sev} issue", body="b", severity=sev, discovered_from="task:TASK-1")
        # FILL IN: open two more "minor" issues with distinct titles, then assert
        #   [r["severity"] for r in rows] == ["critical", "major", "minor", "minor", "minor", "low"]
        #   and the three minor issue_ids appear in ascending order — bounded by AC "ties by issue_id"
```

### `tests/knowledge/wiki/test_cli_ledger.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def test_ledger_audit_command(' tests/knowledge/wiki/test_cli_ledger.py)
# AFTER — append below the whole test_ledger_audit_command function (verified: :401-408).
# Add imports at top: `import asyncio`; LedgerIndex, LedgerLog, LedgerStore, SQLitePragmaPolicy (see Verified Imports).


def _real_ledger_service(tmp_path: Path) -> LedgerService:
    """Real service on tmp_path — mirrors tests/knowledge/wiki/test_ledger_service.py::ledger_service."""
    ledger_dir = tmp_path / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True)
    store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0))
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    return LedgerService(LedgerIndex(store, log), store, log, tmp_path)


def test_ledger_ready_cli_prints_severity_order(runner: CliRunner, tmp_path: Path) -> None:
    """`ledger ready` inherits ready_work()'s canonical order (S6) — no CLI change needed."""
    service = _real_ledger_service(tmp_path)
    asyncio.run(service.open_issue(title="Low first in log", body="b", severity="low", discovered_from="task:TASK-1"))
    asyncio.run(service.open_issue(title="Major second in log", body="b", severity="major", discovered_from="task:TASK-1"))
    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = runner.invoke(ledger, ["ready"])
    assert result.exit_code == 0
    # FILL IN: assert result.output.index("[major]") < result.output.index("[low]") — bounded by AC S6
```
**Why**: the service test pins the contract; the CLI test proves the *operator path* changed
without touching `cli.py`, which is exactly the S6 argument.

### FILL IN checklist
- [ ] `test_ledger_service.py::TestOpenReadyClaim::test_ready_work_is_severity_ordered` — tie-break assertions; bounded by "ties by issue_id"
- [ ] `test_cli_ledger.py::test_ledger_ready_cli_prints_severity_order` — output-index assertion; bounded by S6
- [ ] import blocks in the three test files

---

## Acceptance Criteria

- [ ] `SEVERITY_ORDER` is defined exactly once in the codebase, in `ledger/events.py` below `IssueStatus` (`grep -rn "SEVERITY_ORDER *[:=]" packages/ tests/` shows one definition).
- [ ] `ready_work()` returns `critical → major → minor → low`, ties by `issue_id`; filter predicate unchanged.
- [ ] `ledger ready` prints severity-ordered output with **no** change to `cli.py`.
- [ ] Unknown severity values sort last and do not raise.
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_ledger_events.py tests/knowledge/wiki/test_ledger_service.py tests/knowledge/wiki/test_cli_ledger.py -v`
- [ ] `ruff check` and `black --check -l 120` clean on `events.py` and `service.py`.

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_ledger_events.py -q`
- `pytest tests/knowledge/wiki/test_ledger_service.py -q`
- `pytest tests/knowledge/wiki/test_cli_ledger.py -q`

---

## Test Specification

```python
def test_severity_order_is_total_and_canonical(): ...                   # test_ledger_events.py
class TestOpenReadyClaim:
    async def test_ready_work_is_severity_ordered(self, ledger_service): ...   # test_ledger_service.py
def test_ledger_ready_cli_prints_severity_order(runner, tmp_path): ...  # test_cli_ledger.py (real service)
```

---

## Agent Instructions

1. **Read the spec** (§2 Data Models, §3 Module 2, §7 "Ordering `ready_work()` changes existing output").
2. **Check dependencies** — TASK-3387 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — every anchor's occurrence count must still be 1.
4. **Update status** in `sdd/tasks/index/sdd-fix-ledger-lane.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `FILL IN`.
6. **Verify** the Validation Commands (`PYTHONPATH=packages/ai-parrot/src` in a worktree).
7. **Move this file** to `sdd/tasks/completed/TASK-3388-severity-order-and-ready-work-sort.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
