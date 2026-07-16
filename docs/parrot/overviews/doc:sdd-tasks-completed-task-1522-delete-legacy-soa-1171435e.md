---
type: Wiki Overview
title: 'TASK-1522: Delete the legacy SOAP routing block'
id: doc:sdd-tasks-completed-task-1522-delete-legacy-soap-routing-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 3** — the payoff. With all `wd_*` methods (incl. payroll,
  after
relates_to:
- concept: mod:parrot_tools.workday.tool
  rel: mentions
---

# TASK-1522: Delete the legacy SOAP routing block

**Feature**: FEAT-233 — Workday Composable-Only WSDL Routing
**Spec**: `sdd/specs/workday-composable-only-wsdl-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1521
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** — the payoff. With all `wd_*` methods (incl. payroll, after
TASK-1521) delegating to the composable, the legacy WSDL-routing scaffolding is dead
code. Remove it so the composable is the single WSDL-routing source of truth — the
end-state Jesus asked for (`self.wsdl_paths` no longer makes sense).

---

## Scope

Delete from `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py`:
- `class WorkdaySOAPClient(SOAPClient)` (tool.py:413) and its SOAP-building helpers.
- `self.wsdl_paths` (built tool.py:517-543; read tool.py:609/618) — and the whole
  `wsdl_paths`/`WORKDAY_WSDL_PATHS` population + HUMAN_RESOURCES fallback in `__init__`.
- `self._clients` (tool.py:546), `self.soap_client` (tool.py:551).
- `_get_client_for_service` (tool.py:585), `_get_client_for_method` (tool.py:635).
- `class WorkdayService(str, Enum)` (tool.py:98) and `METHOD_TO_SERVICE_MAP` (tool.py:110).

Reconcile:
- `wd_start` (tool.py:565): remove the legacy `self.soap_client = await
  self._get_client_for_service(primary_service)` (tool.py:576); start should rely on
  lazy `_get_composable` only (or be a no-op/light init). Keep its public return/behavior.
- `wd_close` (tool.py:684): remove the `self._clients` teardown loop (tool.py:686-688);
  keep the `_composables` teardown (tool.py:689-691).
- Remove now-unused imports (`SOAPClient`, `Enum`, `PurePath` if only used here, etc.).

**NOT in scope:** changing any `wd_*` method body (done in TASK-1521); the composable.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py` | MODIFY | delete legacy block; reconcile `wd_start`/`wd_close`; prune imports |
| `packages/ai-parrot-tools/tests/workday/test_legacy_removed.py` | CREATE | assert legacy symbols gone + toolkit still works |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use / Delete
```python
# packages/ai-parrot-tools/src/parrot_tools/workday/tool.py  (DELETE unless noted)
class WorkdayService(str, Enum):                       # line 98   DELETE (enum: PAYROLL/HUMAN_RESOURCES/ABSENCE_MANAGEMENT)
METHOD_TO_SERVICE_MAP = { ... }                        # line 110  DELETE
class WorkdaySOAPClient(SOAPClient): ...               # line 413  DELETE
class WorkdayToolkit(AbstractToolkit):
    self.wsdl_paths: Dict[WorkdayService, str]         # line 517  DELETE (built 517-543; read 609/618)
    self._clients: Dict[WorkdayService, WorkdaySOAPClient]  # line 546  DELETE
    self.soap_client: Optional[WorkdaySOAPClient]      # line 551  DELETE
    async def wd_start(self) -> str: ...               # line 565  KEEP (remove legacy-client create at 576)
    async def _get_client_for_service(...): ...        # line 585  DELETE
    async def _get_client_for_method(...): ...         # line 635  DELETE
    async def _get_composable(self, operation_type): ...  # line 656  KEEP (the only path)
    async def wd_close(self) -> None: ...              # line 684  KEEP (remove _clients loop 686-688; keep _composables 689-691)

# KEEP — these are NOT legacy and must remain:
#   the composable import alias WorkdayComposable (tool.py:75)
#   GetPayrollBalancesInput/GetPayrollResultsInput/GetCompanyPaymentDatesInput (303/323/343)
#   all wd_* tool methods (now composable-delegating)
```

### Integration Points
| Action | Verify nothing references it after deletion | Check |
|---|---|---|
| delete `WorkdayService` enum + `METHOD_TO_SERVICE_MAP` | `grep -n "WorkdayService\b\|METHOD_TO_SERVICE_MAP" tool.py` (only the composable alias remains) | tool.py |
| delete `wsdl_paths`/`_clients`/`WorkdaySOAPClient`/`_get_client_for_*` | `grep` returns empty in tool.py | tool.py |

### Does NOT Exist (after this task)
- ~~`WorkdaySOAPClient`, `WorkdayToolkit.wsdl_paths`, `WorkdayToolkit._clients`, `WorkdayService(str, Enum)`, `METHOD_TO_SERVICE_MAP`~~ — removed by this task.
- NOTE: the composable `WorkdayService(SOAPClient)` (imported as `WorkdayComposable`) is a DIFFERENT symbol and **stays**.

---

## Implementation Notes

### Key Constraints
- Run ONLY after TASK-1521 — deleting `wsdl_paths`/`_clients` before payroll migrates breaks the 3 methods.
- Preserve `wd_start`/`wd_close` public behavior (no signature change).
- After deletion, the full FEAT-230 + FEAT-233 test suite must still pass.
- Watch for orphaned imports (`Enum`, `SOAPClient`, `PurePath`) — remove if unused.

### Known Risks / Gotchas
- `wd_start` may be relied upon to "warm up" a client; ensure the composable's lazy
  per-op start still satisfies callers (composables start on first `_get_composable`).

### References in Codebase
- The 22 already-composable methods confirm the toolkit works without the legacy path.

---

## Acceptance Criteria

- [ ] `WorkdaySOAPClient`, `wsdl_paths`, `_clients`, `soap_client`, `WorkdayService` enum, `METHOD_TO_SERVICE_MAP`, `_get_client_for_service`, `_get_client_for_method` are removed (`grep` empty in tool.py).
- [ ] `wd_start` / `wd_close` operate only on `_composables`.
- [ ] No orphaned imports; `ruff check` clean.
- [ ] Full suite passes: `pytest packages/ai-parrot-tools/tests/workday -v` (FEAT-230 + FEAT-233).
- [ ] No breaking change to the public `wd_*` API.

---

## Test Specification
```python
# packages/ai-parrot-tools/tests/workday/test_legacy_removed.py
import parrot_tools.workday.tool as wt


def test_legacy_symbols_removed():
    assert not hasattr(wt, "WorkdaySOAPClient")
    assert not hasattr(wt, "METHOD_TO_SERVICE_MAP")
    # WorkdayService enum gone (only the composable alias WorkdayComposable remains)
    tk = wt.WorkdayToolkit()
    assert not hasattr(tk, "wsdl_paths")
    assert not hasattr(tk, "_clients")
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 3, §6, §7 risks). 2. **Check deps** — TASK-1521 completed.
3. **Verify the Codebase Contract** (confirm no live references before deleting).
4. **Update status** → in-progress. 5. **Implement** (delete + reconcile + prune imports).
6. **Verify** criteria (incl. full suite). 7. **Move** to completed; **update index** → done.
8. **Fill Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <id>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
