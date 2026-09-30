# TASK-3885: `aggregate_records` — expose Odoo 19 `having`

**Feature**: FEAT-614 — Odoo JSON-2 — map domain-first ORM methods (`read_group` family)
**Spec**: `sdd/specs/odoo-json2-domain-first-methods.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3884
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 3** (goal G6; AC11–AC13). The spec owner resolved §8
at approval: "yes, expose having".

Odoo 19's `formatted_read_group` accepts `having`, a domain whose "fields" are the
aggregates (e.g. `[["__count", ">", 5]]` or `[["amount_total:sum", ">", 1000]]`).
It filters groups after aggregation, server-side. `read_group` (Odoo ≤ 18) has no
`having`; silently dropping the filter there would hand the LLM wrong groups, so
the toolkit raises `ValueError` instead.

This task edits the same Odoo 19 kwargs dict TASK-3884 reshapes, so it runs after
it. **All line numbers below are from before TASK-3884** (verified at `a3e89c96b`).
TASK-3884 shifts `toolkit.py` lines after ~1046 by about +5, so locate by the
quoted anchors and re-run every `grep -c`.

---

## Scope

- Add `having: Optional[list[Any]] = None` as the **last** parameter of `aggregate_records`.
- Document `having` in the docstring and extend its `Raises:` entry.
- Raise `ValueError` before any RPC when `having` is non-empty and the server is not Odoo 19+ (including unknown version).
- On Odoo 19+, put a non-empty `having` into the `formatted_read_group` kwargs.
- Add `having: Optional[OdooDomain] = None` to `AggregateRecordsInput`.
- Add three tests.

**NOT in scope**:
- Client-side validation of `having` terms (spec §3 M3 decision: Odoo validates them).
- Any transport change — JSON-2 forwards kwargs as-is.
- `lazy` handling (TASK-3884).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY | `having` param, version guard, kwargs, docstring |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py` | MODIFY | `having` Field |
| `packages/ai-parrot/tests/test_odoo_toolkit.py` | MODIFY | three new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No new imports in any file.
# toolkit.py: from typing import Any, Literal, Optional                 # verified: toolkit.py:26
# inputs.py:  OdooDomain = list[Any]                                    # verified: inputs.py:16 (module-level alias, same file)
#             Optional / Field already imported and used in AggregateRecordsInput (inputs.py:271-285)
# test_odoo_toolkit.py: pytest, _fake_transport (line 58), _make_toolkit (line 84)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py   (pre-TASK-3884 line numbers)
class OdooToolkit(AbstractToolkit):                                     # line 172
    @tool_schema(AggregateRecordsInput)                                 # line 993 — schema drives the LLM-facing params
    async def aggregate_records(self, model, group_by, measures=None, domain=None, lazy=False,
                                limit=None, offset=0, order=None) -> AggregateResult:   # lines 994-1004
        # line 1020: "            order: Sort order string."                           (docstring Args, last entry)
        # line 1026: "            ValueError: When an unsupported aggregator name is used."   (docstring Raises)
        # line 1041: odoo_version = await self._get_odoo_major_version()    → int | None
        # line 1042: use_formatted = odoo_version is not None and odoo_version >= 19
        # line 1056-1057 (Odoo 19 branch): if order: kwargs["order"] = order
        # line 1058: groups = await self._execute(model, "formatted_read_group", [domain], kwargs)

# packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py
OdooDomain = list[Any]                                                  # line 16
class AggregateRecordsInput(_OdooBaseInput):                            # line 259
    order: Optional[str] = Field(default=None, description="Sort order for groups")   # line 285 — last field

# Upstream (read-only reference): odoo/odoo@19.0 addons/web/models/models.py:802-811
# def formatted_read_group(self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None)
```

### Does NOT Exist
- ~~`read_group(..., having=...)`~~ — Odoo ≤ 18 `read_group` has no `having`; hence the `ValueError`.
- ~~`OdooToolkit._validate_having()`~~ — no such helper; do not add one (no client-side validation).
- ~~`AggregateResult.having`~~ — the result envelope is unchanged.
- ~~`SAFE_DOMAIN_OPERATORS` checks on `having`~~ — that set belongs to `build_domain` (toolkit.py:1087); do not apply it here.

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
- `having` must be the last parameter so no existing caller breaks (AC9, AC13).
- The guard runs **after** `use_formatted` is computed and **before** either branch calls `_execute` (AC12: no RPC).
- `[]` and `None` are both "no having" on every version (AC11).

---

## Implementation Blueprint

### Steps (in order)
1. Add the `having` parameter to the signature — *why*: keyword-compatible extension (AC13).
2. Document it and extend `Raises:` — *why*: the docstring is the LLM-facing description.
3. Add the version guard after `use_formatted` — *why*: fail before any RPC on Odoo ≤ 18 (AC12).
4. Forward `having` in the Odoo 19 kwargs — *why*: AC11.
5. Add the `having` Field — *why*: `@tool_schema(AggregateRecordsInput)` exposes params through this model (AC13).
6. Add tests; run the Validation Commands.

### `toolkit.py` (MODIFY — signature)
```python
# occurrences: 2 for '        order: Optional[str] = None,' (also in search_records, toolkit.py:414)
#   — disambiguated by the 2-line context (toolkit.py:1003-1004):
# REPLACE:
        order: Optional[str] = None,
    ) -> AggregateResult:
# WITH:
        order: Optional[str] = None,
        having: Optional[list[Any]] = None,
    ) -> AggregateResult:
```

### `toolkit.py` (MODIFY — docstring)
```python
# occurrences: 1 (verified: grep -c '            order: Sort order string.' toolkit.py) — line 1020
# AFTER — insert below it:
            having: Optional domain over the aggregates, filtering groups after
                aggregation (e.g. ``[["__count", ">", 5]]`` or
                ``[["amount_total:sum", ">", 1000]]``). Odoo 19+ only.

# occurrences: 1 (verified: grep -c '            ValueError: When an unsupported aggregator name is used.' toolkit.py) — line 1026
# REPLACE WITH:
            ValueError: When an unsupported aggregator name is used, or when a
                non-empty ``having`` is given and the server is not Odoo 19+.
```

### `toolkit.py` (MODIFY — guard)
```python
# occurrences: 1 (verified: grep -c '        use_formatted = odoo_version is not None and odoo_version >= 19' toolkit.py) — line 1042
# AFTER — insert below it:
        if having and not use_formatted:
            # read_group (Odoo <= 18) has no ``having``; dropping it would return unfiltered groups.
            raise ValueError(
                f"having requires Odoo 19+ (formatted_read_group); detected Odoo {odoo_version}. "
                "Filter the returned groups instead."
            )
```

### `toolkit.py` (MODIFY — Odoo 19 kwargs)
```python
# occurrences: 1 (verified: grep -c '                kwargs["order"] = order' toolkit.py) — line 1057 pre-TASK-3884
# AFTER — insert below it (still inside the `if use_formatted:` block, before the formatted_read_group _execute call):
            if having:
                kwargs["having"] = having
```

### `inputs.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'order: Optional[str] = Field(default=None, description="Sort order for groups")' inputs.py) — line 285
# AFTER — insert below it:
    having: Optional[OdooDomain] = Field(
        default=None,
        description=(
            "Odoo 19+ only. Domain over the aggregates to filter groups, e.g. "
            "[['__count', '>', 5]] or [['amount_total:sum', '>', 1000]]. "
            "Each aggregate referenced must also be listed in measures (except __count)."
        ),
    )
```

### `test_odoo_toolkit.py` (MODIFY — new tests)
```python
# occurrences: 1 (verified: grep -c '# ── Phase 1: Domain Builder' test_odoo_toolkit.py) — line 768
# BEFORE — insert above that section comment (after test_aggregate_records_rejects_invalid_aggregator):


@pytest.mark.asyncio
async def test_aggregate_records_odoo_19_forwards_having():
    """A non-empty having is sent to formatted_read_group on Odoo 19+."""
    transport = _fake_transport()
    transport.version.return_value = {"server_serie": "19.0", "server_version": "19.0"}
    toolkit = _make_toolkit(transport)
    transport.execute_kw.side_effect = [[{"state": "sale", "amount_total:sum": 5000.0}]]
    having = [["amount_total:sum", ">", 1000]]

    await toolkit.aggregate_records(
        model="sale.order", group_by=["state"], measures=["amount_total:sum"], having=having
    )

    # FILL IN: unpack (model, method, args, kwargs) from transport.execute_kw.await_args.args;
    #   assert method == "formatted_read_group" and kwargs["having"] == having — AC11


@pytest.mark.asyncio
async def test_aggregate_records_odoo_19_omits_empty_having():
    """None and [] send no having key."""
    # FILL IN: version 19.0; call twice (having=None, having=[]) with a fresh side_effect each time;
    #   assert "having" not in kwargs for both calls — AC11
    ...


@pytest.mark.asyncio
async def test_aggregate_records_having_rejected_before_odoo_19():
    """read_group has no having: raise instead of returning unfiltered groups."""
    transport = _fake_transport()
    transport.version.return_value = {"server_serie": "17.0", "server_version": "17.0"}
    toolkit = _make_toolkit(transport)

    with pytest.raises(ValueError, match="having requires Odoo 19"):
        await toolkit.aggregate_records(
            model="sale.order", group_by=["state"], having=[["__count", ">", 5]]
        )

    # FILL IN: assert transport.execute_kw.await_count == 0 — AC12 (no RPC)

```
**Why**: same helper pattern as the neighbouring aggregate tests. Replace the `...` stub; none may remain.

### FILL IN checklist
- [ ] `test_aggregate_records_odoo_19_forwards_having` — kwargs assertion; AC11
- [ ] `test_aggregate_records_odoo_19_omits_empty_having` — full body; AC11
- [ ] `test_aggregate_records_having_rejected_before_odoo_19` — no-RPC assertion; AC12

---

## Acceptance Criteria

- [ ] AC11 (spec): non-empty `having` on Odoo ≥ 19 → `kwargs["having"] == having`; `[]`/`None` → no `having` key.
- [ ] AC12 (spec): on Odoo ≤ 18 or unknown version, non-empty `having` raises `ValueError` matching "having requires Odoo 19+", with no `execute_kw` call.
- [ ] AC13 (spec): `AggregateRecordsInput.having: Optional[OdooDomain] = None`; `having` is the last parameter of `aggregate_records`.
- [ ] AC7/AC8 (spec): `test_odoo_toolkit.py` passes; `ruff check` on `toolkit.py` and `inputs.py` is clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/test_odoo_toolkit.py -q`
- `pytest packages/ai-parrot/tests/test_odoo_json2_transport.py -q`

Run from the worktree with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src`.

---

## Test Specification

See the blueprint. TASK-3884's tests and all pre-existing aggregate tests must still pass.

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug odoo-json2-domain-first-methods --feature-id FEAT-614`
2. **Read the spec** (§3 Module 3, §5, §6).
3. **Check dependencies** — TASK-3884 must be `"done"` in the index.
4. **Verify the Codebase Contract** — re-run each `grep -c`; line numbers shifted after TASK-3884.
5. **Update status** in `sdd/tasks/index/odoo-json2-domain-first-methods.json` → `"in-progress"`, commit only that file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — run the Validation Commands.
8. **Commit the code** — stage only the three listed files.
9. **Close the task** — `scripts/sdd/close_task.sh TASK-3885 odoo-json2-domain-first-methods verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
