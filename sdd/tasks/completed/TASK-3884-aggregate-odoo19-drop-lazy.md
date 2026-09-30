# TASK-3884: `aggregate_records` — stop sending `lazy` to Odoo 19 `formatted_read_group`

**Feature**: FEAT-614 — Odoo JSON-2 — map domain-first ORM methods (`read_group` family)
**Spec**: `sdd/specs/odoo-json2-domain-first-methods.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 2** (goal G3; AC4–AC6).

Odoo 19's `formatted_read_group(domain, groupby=(), aggregates=(), having=(),
offset=0, limit=None, order=None)` has **no `lazy` parameter** (verified upstream,
`odoo/odoo@19.0 addons/web/models/models.py:802-811`). JSON-2 forwards the body as
keyword arguments, so today's `"lazy": lazy` in the Odoo 19 branch of
`aggregate_records` makes the call fail even after TASK-3883 maps the domain.
The Odoo 16–18 `read_group` branch accepts `lazy` and must keep sending it.

---

## Scope

- Remove `"lazy": lazy,` from the Odoo 19+ `kwargs` dict in `aggregate_records` (only that dict).
- When `lazy` is `True` on the Odoo 19+ branch, emit one `self.logger.debug` line saying it is ignored.
- Amend the `lazy` bullet of the `aggregate_records` docstring.
- Amend the `AggregateRecordsInput.lazy` Field description.
- Amend one existing toolkit test and add two new ones.

**NOT in scope**:
- The `having` parameter (TASK-3885, which depends on this task).
- The Odoo 16–18 `read_group` branch (unchanged, AC5).
- `json2.py` (TASK-3883).
- Normalising `read_group` vs `formatted_read_group` result shapes (spec Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY | Odoo 19 kwargs, debug log, docstring |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py` | MODIFY | `lazy` Field description |
| `packages/ai-parrot/tests/test_odoo_toolkit.py` | MODIFY | amend 1 test, add 2 tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No new imports in any file.
# toolkit.py already has: from typing import Any, Literal, Optional   # verified: toolkit.py:26
# toolkit.py logger: self.logger = logging.getLogger(__name__)       # verified: toolkit.py:241
# test_odoo_toolkit.py already has:
from unittest.mock import AsyncMock, MagicMock                        # verified: test_odoo_toolkit.py:13
import pytest                                                         # verified: :15
from parrot_tools.odoo.toolkit import OdooToolkit                     # verified: :53
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py
class OdooToolkit(AbstractToolkit):                                   # line 172
    async def _get_odoo_major_version(self) -> int | None:            # line 982 — reads transport.version()["server_serie"]
    @tool_schema(AggregateRecordsInput)                               # line 993
    async def aggregate_records(self, model: str, group_by: list[str], measures: Optional[list[str]] = None,
                                domain: Optional[list[Any]] = None, lazy: bool = False, limit: Optional[int] = None,
                                offset: int = 0, order: Optional[str] = None) -> AggregateResult:   # lines 994-1004
        # line 1017: "            lazy: When True, only the first group_by level is resolved."   (docstring)
        # line 1040: domain = domain or []
        # line 1041: odoo_version = await self._get_odoo_major_version()
        # line 1042: use_formatted = odoo_version is not None and odoo_version >= 19
        # lines 1046-1049 (Odoo 19 dict):   kwargs: dict[str, Any] = {"groupby": group_by, "lazy": lazy}
        # line 1058: groups = await self._execute(model, "formatted_read_group", [domain], kwargs)
        # lines 1062-1066 (Odoo ≤18 dict):  kwargs = {"groupby": group_by, "fields": ..., "lazy": lazy}   ← KEEP
        # line 1073: groups = await self._execute(model, "read_group", [domain], kwargs)

# packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py
class AggregateRecordsInput(_OdooBaseInput):                          # line 259
    lazy: bool = Field(default=False, description="Use lazy grouping (only first group_by level resolved)")  # lines 279-282

# packages/ai-parrot/tests/test_odoo_toolkit.py
def _fake_transport(uid: int = 1) -> MagicMock:                       # line 58 — execute_kw/version are AsyncMock; default version 19.0
def _make_toolkit(transport: MagicMock | None = None) -> OdooToolkit: # line 84
async def test_aggregate_records_calls_formatted_read_group_for_odoo_19():   # line 700 — amend its final assertions
async def test_aggregate_records_rejects_invalid_aggregator():        # line 753 — insert new tests BEFORE it
```

### Does NOT Exist
- ~~`OdooToolkit._build_aggregate_kwargs()` / `_read_group_kwargs()`~~ — no helper; edit the branch in place.
- ~~`formatted_read_group(..., lazy=...)`~~ — Odoo 19 has no `lazy` there.
- ~~`caplog` assertions elsewhere in this test module~~ — do not assert on the debug log; assert on kwargs.
- ~~`packages/ai-parrot-tools/tests/test_odoo_toolkit.py`~~ — the test lives in `packages/ai-parrot/tests/`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/test_odoo_toolkit.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py#OdooToolkit.aggregate_records",
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py#OdooToolkit._get_odoo_major_version",
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py#AggregateRecordsInput"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The `"lazy": lazy,` line occurs **twice** in `toolkit.py` (1048 and 1065). Remove only the Odoo 19 one (inside the `if use_formatted:` block).
- Log with `%s` formatting, never an f-string: `self.logger.debug("...%s", odoo_version)`.
- `aggregate_records` signature unchanged (AC9).

---

## Implementation Blueprint

### Steps (in order)
1. Edit the Odoo 19 kwargs dict and add the debug log — *why*: Odoo 19 rejects unknown kwargs over JSON-2 (AC4).
2. Amend the docstring `lazy` bullet — *why*: the tool description the LLM reads must be honest (AC6).
3. Amend the `lazy` Field description — *why*: same, for the JSON schema (AC6).
4. Amend and add tests — *why*: pin AC4 and AC5.
5. Run the Validation Commands.

### `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` (MODIFY — Odoo 19 kwargs)
```python
# occurrences: 2 for '"lazy": lazy,' (verified: grep -c) — disambiguated by 3-line context below (toolkit.py:1046-1049)
# REPLACE:
            kwargs: dict[str, Any] = {
                "groupby": group_by,
                "lazy": lazy,
            }
# WITH:
            # formatted_read_group (Odoo 19+) has no ``lazy`` parameter — sending it is rejected.
            kwargs: dict[str, Any] = {
                "groupby": group_by,
            }
            if lazy:
                self.logger.debug(
                    "aggregate_records: lazy=True ignored — formatted_read_group (Odoo %s) has no lazy mode",
                    odoo_version,
                )
```
**Why**: spec §3 M2 fixes both the removal and the exact log message. The `else:` branch (Odoo ≤18) is untouched.

### `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` (MODIFY — docstring)
```python
# occurrences: 1 (verified: grep -c '            lazy: When True, only the first group_by level is resolved.' toolkit.py) — line 1017
# REPLACE that one line WITH:
            lazy: When True, only the first group_by level is resolved.
                Honoured on Odoo 16-18 (``read_group``) only; Odoo 19+
                ``formatted_read_group`` has no lazy mode and the flag is
                ignored (a debug log line records that).
```

### `packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'description="Use lazy grouping (only first group_by level resolved)",' inputs.py) — line 281
# REPLACE WITH:
        description="Use lazy grouping (only first group_by level resolved). Odoo 16-18 only; ignored on Odoo 19+.",
```

### `packages/ai-parrot/tests/test_odoo_toolkit.py` (MODIFY — amend existing test)
```python
# occurrences: 1 (verified: grep -c 'async def test_aggregate_records_calls_formatted_read_group_for_odoo_19():') — line 700
# In that test, REPLACE its last three lines:
    # Verify formatted_read_group was called (second call)
    calls = transport.execute_kw.call_args_list
    assert any("formatted_read_group" in str(c) for c in calls)
# WITH:
    # FILL IN: assert transport.execute_kw.await_args.args == ("sale.order", "formatted_read_group", [[]], {"groupby": ["state"]})
    #   — exact args: domain [] positional, no "lazy" key (AC4). Check the mock's call shape first:
    #   OdooToolkit._execute calls transport.execute_kw(model, method, args, kwargs) positionally (toolkit.py:292).
```

### `packages/ai-parrot/tests/test_odoo_toolkit.py` (MODIFY — new tests)
```python
# occurrences: 1 (verified: grep -c 'async def test_aggregate_records_rejects_invalid_aggregator():') — line 753
# BEFORE — insert above the `@pytest.mark.asyncio` decorating that test (line 752)


@pytest.mark.asyncio
async def test_aggregate_records_odoo_19_ignores_lazy_flag():
    """Odoo 19+ formatted_read_group has no lazy mode: the flag is not sent."""
    transport = _fake_transport()
    transport.version.return_value = {"server_serie": "19.0", "server_version": "19.0"}
    toolkit = _make_toolkit(transport)
    transport.execute_kw.side_effect = [[{"state": "sale", "__count": 2}]]

    await toolkit.aggregate_records(model="sale.order", group_by=["state"], lazy=True)

    # FILL IN: take (model, method, args, kwargs) from transport.execute_kw.await_args.args;
    #   assert method == "formatted_read_group" and "lazy" not in kwargs — AC4


@pytest.mark.asyncio
async def test_aggregate_records_odoo_17_still_sends_lazy():
    """Odoo 16-18 read_group keeps receiving lazy."""
    # FILL IN: version "17.0", lazy=True; assert method == "read_group" and kwargs["lazy"] is True — AC5
    ...

```
**Why**: follows the neighbouring tests' `_fake_transport` + `side_effect` pattern exactly. Replace the `...` stub; none may remain.

### FILL IN checklist
- [ ] amended `test_aggregate_records_calls_formatted_read_group_for_odoo_19` — exact `await_args`; AC4
- [ ] `test_aggregate_records_odoo_19_ignores_lazy_flag` — assertions; AC4
- [ ] `test_aggregate_records_odoo_17_still_sends_lazy` — full body; AC5

---

## Acceptance Criteria

- [ ] AC4 (spec): on Odoo ≥ 19, `execute_kw(model, "formatted_read_group", [domain], kwargs)` with `"lazy" not in kwargs`; `lazy=True` produces one debug line.
- [ ] AC5 (spec): on Odoo ≤ 18, `read_group` still gets `kwargs["lazy"] == lazy` and `kwargs["fields"]` as today.
- [ ] AC6 (spec): docstring and `AggregateRecordsInput.lazy` description say `lazy` is ignored on Odoo 19+.
- [ ] AC9 (spec): `aggregate_records` signature unchanged.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py` is clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/test_odoo_toolkit.py -q`

Run from the worktree with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src`.

---

## Test Specification

See the blueprint. Existing tests `test_aggregate_records_calls_read_group_for_odoo_16_18` (line 674) and
`test_aggregate_records_allows_empty_group_by_global_aggregation` (line 723) must pass unmodified.

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug odoo-json2-domain-first-methods --feature-id FEAT-614`
2. **Read the spec** (§3 Module 2, §5, §6).
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — re-run each `grep -c` in the blueprint.
5. **Update status** in `sdd/tasks/index/odoo-json2-domain-first-methods.json` → `"in-progress"`, commit only that file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — run the Validation Commands.
8. **Commit the code** — stage only the three listed files.
9. **Close the task** — `scripts/sdd/close_task.sh TASK-3884 odoo-json2-domain-first-methods verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sonnet (native)
**Date**: 2026-09-30
**Notes**: Odoo 19+ branch of `aggregate_records` no longer sends `lazy` (debug log when lazy=True); docstring/Field description updated; tests added. 64 tests pass (scratch copy, same env caveat).

**Deviations from spec**: none
