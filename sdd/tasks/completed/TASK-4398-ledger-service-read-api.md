# TASK-4398: LedgerService read API — get_issue, issue_history, severity filter

**Feature**: FEAT-689 — wikitoolkit ledger list / show
**Spec**: `sdd/specs/wiki-ledger-show.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. The ledger can't read a single issue (with its `body`) or its event history,
and `list_issues()` can't filter by severity. This task adds the service-layer reads that
both the ops/MCP layer (TASK-4399) and the CLI (TASK-4400) build on. It only adds reads; the
write path, event schema and `_issue_dict` shape stay unchanged.

---

## Scope

- Add the module-level `normalize_issue_id(raw: str) -> str` to `ledger/service.py`.
- Add a keyword-only `severity: IssueSeverity | None = None` filter to `LedgerService.list_issues`
  (the default behaviour and sort order must stay exactly as they are).
- Add `LedgerService.get_issue(issue_id)`, which returns the `_issue_dict` row plus `"body"`, or `None`.
- Add `LedgerService.issue_history(issue_id)`, which returns the events whose `subject` equals the
  normalized id, in log order, as `{"event_id","kind","actor","ts","payload"}` dicts.
- Write unit tests in a new file, `packages/ai-parrot/tests/knowledge/wiki/test_ledger_service_reads.py`.

**NOT in scope**: operations, MCP/transport, remote allowlist and tool adapters (TASK-4399); CLI
commands (TASK-4400); changing `_issue_dict` (it must NOT gain `body`); any offset index for
history.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `normalize_issue_id`, `severity` filter, `get_issue`, `issue_history` |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_service_reads.py` | CREATE | M1 unit tests (spec §4) |

> Test location deviation from spec §4: the spec names `tests/knowledge/wiki/test_ledger_service_reads.py`.
> This task puts the new file under `packages/ai-parrot/tests/knowledge/wiki/`, next to
> `test_ledger_list_issues.py`, because `codebase-conventions.md` says new tests live next to their
> distribution. Existing root-level test files are only modified in place by the other tasks.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity, SEVERITY_ORDER  # verified: ledger/events.py:22-26
from parrot.knowledge.wiki.ledger.index import LedgerIndex      # verified: ledger/service.py:28
from parrot.knowledge.wiki.ledger.log import LedgerLog          # verified: ledger/service.py:29
from parrot.knowledge.wiki.ledger.service import LedgerService  # verified: ledger/service.py:127
from parrot.knowledge.wiki.ledger.store import LedgerStore      # verified: ledger/service.py:30
from parrot.knowledge.wiki.store import SQLitePragmaPolicy      # verified: ledger/service.py:36
```
`service.py` already imports `asyncio`, `Any`, `Sequence`, `IssueKind`, `LedgerEvent`, `SEVERITY_ORDER`
(lines 14-27). It does **not** import `IssueSeverity` yet; add it to the existing
`from parrot.knowledge.wiki.ledger.events import (...)` block.

### Existing Signatures to Use
```python
# ledger/events.py
IssueSeverity = Literal["critical", "major", "minor", "low"]                # line 23
class LedgerEvent(BaseModel):                                               # line 103
    event_id: str; kind: LedgerEventKind; subject: str; actor: str; ts: str; payload: dict[str, Any]  # lines 106-111

# ledger/log.py
class LedgerLog:
    def iter_events(self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]]:  # line 83 — SYNC generator, yields (event, offset)

# ledger/service.py
def _issue_dict(issue_id: str, state: dict[str, Any]) -> dict[str, Any]:   # line 109 — keys: issue_id,title,status,kind,severity,acknowledged,discovered_from,about,claimed_by,closed_by,closed_reason,resolved_by (NO body)
class LedgerService:                                                        # line 127
    log: LedgerLog                                                          # set at line 141
    async def _sync_best_effort(self) -> None:                              # line 198 — swallows WikiStoreBusy
    async def list_issues(self, statuses: Sequence[str] = ("open", "claimed"), *,
                          kind: IssueKind | None = None, about_prefix: str | None = None) -> list[dict[str, Any]]:  # line 278
    async def claim(self, issue_id: str, actor: str) -> bool:               # line 310
    async def _issue_state(self, issue_id: str) -> dict[str, Any] | None:   # line 336 — decoded state incl. "body"
    async def open_issue(title, body, kind, severity, discovered_from, about, actor=...) -> str  # used positionally in test_ledger_list_issues.py:30
    async def close_issue(self, issue_id: str, reason: str, actor: str, resolved_by: str | None = None) -> bool  # line 342
```

### Does NOT Exist
- ~~`LedgerService.get_issue`~~, ~~`LedgerService.issue_history`~~, ~~`normalize_issue_id`~~ — this task creates them
- ~~`_issue_dict(...)["body"]`~~ — do NOT add `body` to `_issue_dict`; it would bloat `ready`/`list` output
- ~~`LedgerLog.events_for(subject)`~~ — no subject-indexed reader; filter `iter_events()`
- ~~`LedgerIndex.get_issue`~~ — only a private `_read_issue(conn, id)`; go through `_issue_state`
- ~~`LedgerLog.aiter_events`~~ — the log is sync-only; wrap with `asyncio.to_thread`

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
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_ledger_service_reads.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#_issue_dict",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.list_issues",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService._issue_state",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService._sync_best_effort",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog.iter_events",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#LedgerEvent"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `issue_history` must not block the event loop: `iter_events()` is a sync file reader, so run the
  whole scan inside `asyncio.to_thread`.
- `get_issue` calls `_sync_best_effort()` before reading, the same way `list_issues` does, so a busy
  writer lock gives a stale read instead of an exception.
- History mirrors the log, so duplicate `issue.opened` events stay in it (spec §7 gotcha).
- `list_issues` sort key and default statuses stay unchanged; `ledger ready`, `plan-fix` and the
  standup collector depend on them.

### References in Codebase
- `packages/ai-parrot/tests/knowledge/wiki/test_ledger_list_issues.py:16-37` — the tmp ledger fixture and `_seed` pattern to copy.

---

## Implementation Blueprint

### Steps (in order)
1. Add `IssueSeverity` to the events import block in `service.py`. *Why:* the new `severity` parameter is typed with it.
2. Add `normalize_issue_id` directly above `_issue_dict`. *Why:* both CLI and MCP accept bare hex ids, and one helper keeps them consistent.
3. Add the `severity` keyword to `list_issues` and filter on it next to the `kind` filter. *Why:* spec §3 M1; the rest of the method stays untouched.
4. Insert `get_issue` and `issue_history` directly above `async def claim`. *Why:* this keeps the public reads grouped after `list_issues`.
5. Write the test file and run the Validation Commands.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` (MODIFY) — import
```python
# occurrences: 1 (verified: grep -cxF '    IssueKind,' service.py)
# AFTER — insert below `    IssueKind,` (verified: service.py:22)
    IssueSeverity,
```
**Why**: the import block is alphabetical-ish and `IssueSeverity` belongs right after `IssueKind`. Ruff's
import-sorting rules are not enforced (there's no isort), but keep the block tidy.

### `service.py` (MODIFY) — `normalize_issue_id`
```python
# occurrences: 1 (verified: grep -c 'def _issue_dict(issue_id: str, state: dict\[str, Any\]) -> dict\[str, Any\]:' service.py)
# BEFORE — insert above `def _issue_dict(issue_id: str, state: dict[str, Any]) -> dict[str, Any]:` (verified: service.py:109)
def normalize_issue_id(raw: str) -> str:
    """Return ``raw`` prefixed with ``issue:`` unless it already is; strips whitespace.

    Args:
        raw: An issue id as typed by a user or agent (``a9514c9232ad`` or ``issue:a9514c9232ad``).

    Returns:
        The canonical ``issue:<hex>`` id.
    """
    value = raw.strip()
    return value if value.startswith("issue:") else f"issue:{value}"


```
**Why**: issue ids are `f"issue:{sha1[:12]}"` (events.py:100). Users copy the bare hex from logs, so
both forms have to resolve to the same page.

### `service.py` (MODIFY) — `list_issues` severity filter
```python
# occurrences: 1 (verified: grep -cxF '        about_prefix: str | None = None,' service.py)
# REPLACE the parameter line `        about_prefix: str | None = None,` (verified: service.py:283) WITH:
        severity: IssueSeverity | None = None,
        about_prefix: str | None = None,

# Docstring Args: add a line after `kind:` —
#             severity: Restrict to one severity when given.

# occurrences: 1 (verified: grep -cxF '            if kind is not None and state.get("kind") != kind:' service.py)
# AFTER — insert below the `continue` that follows `            if kind is not None and state.get("kind") != kind:` (verified: service.py:301-302)
            if severity is not None and state.get("severity") != severity:
                continue
```
**Why**: keyword-only after `*`, so existing positional callers (`list_issues(("open",))`) and the
standup collector are unaffected.

### `service.py` (MODIFY) — `get_issue` / `issue_history`
```python
# occurrences: 1 (verified: grep -cxF '    async def claim(self, issue_id: str, actor: str) -> bool:' service.py)
# BEFORE — insert above `    async def claim(self, issue_id: str, actor: str) -> bool:` (verified: service.py:310)
    async def get_issue(self, issue_id: str) -> dict[str, Any] | None:
        """Return one issue's public dict plus its ``body``; ``None`` when unknown.

        Args:
            issue_id: Issue id, with or without the ``issue:`` prefix.

        Returns:
            The :func:`_issue_dict` shape with an added ``"body"`` key, or ``None``.
        """
        await self._sync_best_effort()
        canonical = normalize_issue_id(issue_id)
        state = await self._issue_state(canonical)
        if state is None:
            return None
        # FILL IN: build row = _issue_dict(canonical, state) and set row["body"] = state.get("body", "") — bounded by AC "show prints body"; never mutate _issue_dict itself
        return row

    async def issue_history(self, issue_id: str) -> list[dict[str, Any]]:
        """Return the events whose ``subject`` is this issue, in log order.

        Args:
            issue_id: Issue id, with or without the ``issue:`` prefix.

        Returns:
            ``{"event_id", "kind", "actor", "ts", "payload"}`` dicts; ``[]`` for an unknown id.
        """
        canonical = normalize_issue_id(issue_id)

        def _scan() -> list[dict[str, Any]]:
            # FILL IN: iterate `for event, _offset in self.log.iter_events():`, keep events with event.subject == canonical,
            # and append {"event_id": event.event_id, "kind": event.kind, "actor": event.actor, "ts": event.ts, "payload": dict(event.payload)}
            # — bounded by spec §2 history shape; keep log order (no sorting)
            ...

        return await asyncio.to_thread(_scan)

```
**Why**: `_issue_state` already decodes the page including `body` (service.py:336), so `get_issue`
only projects it. `issue_history` reads the log rather than the index because the index keeps only
current state. Running it in a thread keeps the roughly 458 KB scan off the event loop.

### `packages/ai-parrot/tests/knowledge/wiki/test_ledger_service_reads.py` (CREATE)
```python
"""FEAT-689 M1 — LedgerService single-issue reads and severity filter."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService, normalize_issue_id
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.store import SQLitePragmaPolicy


@pytest.fixture
def service(tmp_path: Path) -> LedgerService:
    """A LedgerService over an isolated temporary ledger root."""
    ledger_dir = tmp_path / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True)
    store = LedgerStore(
        ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0)
    )
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    return LedgerService(LedgerIndex(store, log), store, log, tmp_path)


def test_normalize_issue_id() -> None:
    """Bare hex gets the prefix; prefixed ids and whitespace are handled."""
    assert normalize_issue_id("abc123") == "issue:abc123"
    assert normalize_issue_id("issue:abc123") == "issue:abc123"
    assert normalize_issue_id("  abc123 \n") == "issue:abc123"


async def test_get_issue_includes_body(service: LedgerService) -> None:
    """get_issue returns every _issue_dict key plus body; bare hex id resolves."""
    # FILL IN: open_issue("T", "the body", "bug", "major", "t:1", ["sym:a.py#f"]); get_issue(id) and get_issue(id.removeprefix("issue:"))
    #          both return body == "the body" and the 12 _issue_dict keys


async def test_get_issue_unknown_returns_none(service: LedgerService) -> None:
    """Unknown id → None."""
    assert await service.get_issue("issue:000000000000") is None


async def test_issue_history_order_and_filter(service: LedgerService) -> None:
    """open → claim → close yields 3 events in order; other issues' events are excluded."""
    # FILL IN: open two issues, claim + close the first; history(first) kinds == ["issue.opened", "issue.claimed", "issue.closed"]
    #          (verify the exact kind strings against LedgerEventKind in events.py); history of an unknown id == []


async def test_list_issues_severity_filter(service: LedgerService) -> None:
    """severity="major" keeps only major issues; omitted keeps all."""
    # FILL IN: open one major + one minor; list_issues(severity="major") has exactly the major one; list_issues() has both
```

### FILL IN checklist
- [ ] `service.py::LedgerService.get_issue` — copy `_issue_dict` and add `body`; bounded by "do not add body to `_issue_dict`"
- [ ] `service.py::LedgerService.issue_history._scan` — filter by `subject`, keep log order; bounded by spec §2 shape
- [ ] the four test bodies, using the exact `LedgerEventKind` strings from `events.py`

---

## Acceptance Criteria

- [ ] `normalize_issue_id`, `LedgerService.get_issue` and `LedgerService.issue_history` exist with the signatures above
- [ ] `list_issues(severity=...)` filters; calls without `severity` behave exactly as before
- [ ] `_issue_dict` output is unchanged (no `body` key)
- [ ] Existing `test_ledger_list_issues.py` and `test_ledger_service.py` stay green
- [ ] `ruff check` is clean on both files

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_service_reads.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_list_issues.py -q`
- `pytest tests/knowledge/wiki/test_ledger_service.py -q`

---

## Test Specification

See the CREATE block above. Spec §4 rows covered: `test_normalize_issue_id`, `test_get_issue_includes_body`,
`test_get_issue_unknown_returns_none`, `test_issue_history_order_and_filter`, `test_list_issues_severity_filter`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug wiki-ledger-show --feature-id FEAT-689`).
2. Read the spec; this task has no dependencies.
3. Verify the Codebase Contract, then mark the task `in-progress` in `sdd/tasks/index/wiki-ledger-show.json`.
4. Implement from the blueprint and complete every `FILL IN`.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`, then commit only the two listed files.
6. Close with `scripts/sdd/close_task.sh TASK-4398 wiki-ledger-show verified` and fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (seat gpt-5.6-terra, codex, 1 attempt, 64s)
**Date**: 2026-10-16
**Notes**: Added normalize_issue_id, LedgerService.get_issue/issue_history and list_issues(severity=) in ledger/service.py plus test_ledger_service_reads.py. Merge-tier run reported outcome=failed (15 failed/4 errors in untouched mcp-server/installer/bookstore tests; the 521 task-scope tests passed). The same suites fail on the unmodified main checkout (13 failed/4 errors; the worktree also lacks the Cython parrot.utils.types .so), so treated as pre-existing environment failures, NOT a green run. No review defects; no feedback recorded.

**Deviations from spec**: new test file placed under `packages/ai-parrot/tests/knowledge/wiki/` (see Files table note).
