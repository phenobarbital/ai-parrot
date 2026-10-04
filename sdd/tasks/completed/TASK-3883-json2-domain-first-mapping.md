# TASK-3883: JSON-2 transport — map domain-first ORM methods

**Feature**: FEAT-614 — Odoo JSON-2 — map domain-first ORM methods (`read_group` family)
**Spec**: `sdd/specs/odoo-json2-domain-first-methods.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:c32c408ded92`

---

## Context

Implements spec §3 **Module 1** (goals G1, G2; AC1–AC3).

`Json2Transport._build_body` has no mapping for `formatted_read_group` /
`read_group`. With the toolkit's default empty domain `[]`, the call falls into
the generic tail, where `_looks_like_ids([])` is `True`, so the domain is sent as
`ids: []` and Odoo 19 answers HTTP 422 "missing a required argument: domain".
That is ledger issue `c32c408ded92`. A non-empty domain raises a client-side
`OdooRPCError` instead. Both go away once the whole domain-first family is routed
through the existing `domain` branch.

---

## Scope

- Add the module-level constant `_DOMAIN_FIRST_METHODS` to `json2.py`, between
  `_looks_like_ids` and `class Json2Transport`.
- Change the condition of the existing `search`/`search_read`/`search_count`
  branch in `_build_body` to `if method in _DOMAIN_FIRST_METHODS:`. Keep its body
  exactly as it is.
- Extend the `_build_body` docstring with the domain-first contract.
- Add four tests to `test_odoo_json2_transport.py`.

**NOT in scope**:
- Changing `_looks_like_ids` (spec §1 Non-Goals, §8 resolved question).
- Anything in `toolkit.py` or `inputs.py` (TASK-3884, TASK-3885).
- XML-RPC / JSON-RPC transports.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py` | MODIFY | add `_DOMAIN_FIRST_METHODS`, use it in `_build_body` |
| `packages/ai-parrot/tests/test_odoo_json2_transport.py` | MODIFY | four new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# json2.py already imports everything it needs — add NO new imports.
from typing import Any                                                   # verified: json2.py:16
from parrot.interfaces.odoointerface import OdooRPCError                 # verified: json2.py:20-26 (import block)

# test_odoo_json2_transport.py already has these:
from unittest.mock import AsyncMock, MagicMock, patch                    # verified: test_odoo_json2_transport.py:7
import pytest                                                            # verified: :9
from parrot.interfaces.odoointerface import OdooAuthenticationError, OdooConfig, OdooRPCError  # verified: :27-31
from parrot_tools.odoo.transport.json2 import Json2Transport             # verified: :32
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py
def _looks_like_ids(value: Any) -> bool:                                 # line 31 — [] → True (all() over empty)
class Json2Transport(AbstractOdooTransport):                             # line 38
    @staticmethod
    def _build_body(method: str, args: list[Any] | None, kwargs: dict[str, Any] | None) -> dict[str, Any]:  # lines 89-94
        # line 96:  args = args or []
        # line 97:  body = dict(kwargs or {})
        # line 99:  if method in {"search", "search_read", "search_count"}:
        # line 100:     if len(args) > 1:
        # line 101:         raise OdooRPCError(f"JSON-2 transport cannot map positional args for method {method!r}.")
        # line 102:     body.setdefault("domain", args[0] if args else [])
        # line 103:     return body
    async def execute_kw(self, model, method, args=None, kwargs=None) -> Any:  # line 172 → _build_body → _request_json2
    # _request_json2 POSTs to f"{config.url}/json/2/{model}/{method}" with json=body   # line 66-78

# packages/ai-parrot/tests/test_odoo_json2_transport.py
def _config(**overrides) -> OdooConfig:                                  # line 35
def _mock_aiohttp_response(body, status: int = 200):                     # line 47 — returns a MagicMock session; .post is a MagicMock
# pattern (line 84-96):
#   with patch("aiohttp.ClientSession", return_value=session):
#       result = await transport.execute_kw(...)
#   url = session.post.call_args.args[0]
#   body = session.post.call_args.kwargs["json"]
```

### Does NOT Exist
- ~~`Json2Transport._DOMAIN_FIRST_METHODS`~~ — the constant is **module-level**, not a class attribute.
- ~~`Json2Transport.read_group()` / `.formatted_read_group()`~~ — no per-method helpers; everything goes through `execute_kw` → `_build_body`.
- ~~`packages/ai-parrot-tools/tests/test_odoo_json2_transport.py`~~ — the test lives in `packages/ai-parrot/tests/`.
- ~~a `session` pytest fixture~~ — tests build the session inline with `_mock_aiohttp_response(...)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/test_odoo_json2_transport.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py#_looks_like_ids",
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py#Json2Transport._build_body",
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py#Json2Transport.execute_kw"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The search family (`search`, `search_read`, `search_count`) must behave exactly as before (AC3); the existing tests at `test_odoo_json2_transport.py:80-146` must pass unmodified.
- Keep `setdefault`: an explicit `kwargs["domain"]` still wins over the positional one.
- `black` line length 120; `ruff check` clean.

---

## Implementation Blueprint

### Steps (in order)
1. Insert `_DOMAIN_FIRST_METHODS` after `_looks_like_ids` — *why*: a single declared set means the next domain-first method is a one-line addition (G2).
2. Replace the branch condition at `json2.py:99` — *why*: this branch runs before the generic `_looks_like_ids` tail, so `[]` can never be misrouted to `ids` again (AC1).
3. Extend the `_build_body` docstring — *why*: documents the contract the tests pin.
4. Append the four tests — *why*: the empty-domain test is the regression for the ledger's exact 422.
5. Run the Validation Commands.

### `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py` (MODIFY — constant)
```python
# occurrences: 1 (verified: grep -c 'def _looks_like_ids(value: Any) -> bool:' json2.py)
# AFTER — insert below the end of `_looks_like_ids` (its last line is
#   `    return isinstance(value, list) and all(isinstance(item, int) for item in value)`, json2.py:35),
#   i.e. before the two blank lines preceding `class Json2Transport(AbstractOdooTransport):` (json2.py:38)


#: ORM methods whose first positional ``execute_kw`` argument is a search domain.
#: ``Json2Transport._build_body`` maps ``args[0]`` of these to the JSON-2 ``domain`` key.
_DOMAIN_FIRST_METHODS: frozenset[str] = frozenset({
    "search",
    "search_read",
    "search_count",
    "read_group",
    "formatted_read_group",
    "web_read_group",
    "formatted_read_grouping_sets",
})
```
**Why this shape**: spec §3 M1 fixes the name, the module level and the exact membership. Do not add or drop methods.

### `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py` (MODIFY — branch + docstring)
```python
# occurrences: 1 (verified: grep -c 'if method in {"search", "search_read", "search_count"}:' json2.py)
# REPLACE line 99:
        if method in {"search", "search_read", "search_count"}:
# WITH:
        if method in _DOMAIN_FIRST_METHODS:
# (lines 100-103 — the branch body — stay byte-identical)

# occurrences: 1 — REPLACE the docstring at json2.py:95
        """Translate legacy ``execute_kw`` args into JSON-2 named arguments."""
# WITH:
        """Translate legacy ``execute_kw`` args into JSON-2 named arguments.

        Domain-first methods (``_DOMAIN_FIRST_METHODS``) map ``args[0]`` (an
        empty list when absent) to ``body["domain"]``; more than one positional
        argument raises ``OdooRPCError``.
        """
```
**Why**: the body is already correct for the search family; only the membership changes.

### `packages/ai-parrot/tests/test_odoo_json2_transport.py` (MODIFY — new tests)
```python
# occurrences: 1 (verified: grep -c 'async def test_execute_kw_unsupported_positional_args_raise_rpc_error():' test file)
# AFTER — insert below the end of that test (its last line is
#   `        await transport.execute_kw("res.partner", "custom_method", ["x"], None)`, line 145),
#   before the `@pytest.mark.asyncio` of test_version_uses_web_version_endpoint_and_normalizes_response (line 148)


@pytest.mark.asyncio
async def test_execute_kw_formatted_read_group_maps_domain_and_kwargs():
    session = _mock_aiohttp_response([{"team_id": [1, "Support"], "__count": 3}])
    transport = Json2Transport(_config())

    with patch("aiohttp.ClientSession", return_value=session):
        await transport.execute_kw(
            "sh.helpdesk.ticket",
            "formatted_read_group",
            [[("stage_id.name", "=", "New")]],
            {"groupby": ["team_id"], "aggregates": ["id:count"]},
        )

    url = session.post.call_args.args[0]
    body = session.post.call_args.kwargs["json"]
    assert url == "https://odoo.example.com/json/2/sh.helpdesk.ticket/formatted_read_group"
    # FILL IN: assert body == {"domain": [("stage_id.name", "=", "New")], "groupby": ["team_id"], "aggregates": ["id:count"]} — AC1


@pytest.mark.asyncio
async def test_execute_kw_read_group_maps_domain_and_kwargs():
    # FILL IN: same shape as above for model "sale.order", method "read_group",
    #   args [[("state", "=", "sale")]], kwargs {"groupby": ["state"], "fields": ["state", "amount_total:sum"], "lazy": False};
    #   assert URL ends with "/json/2/sale.order/read_group" and body == {"domain": [...], **kwargs} — AC2
    ...


@pytest.mark.asyncio
async def test_execute_kw_domain_first_empty_domain_is_sent_as_domain_not_ids():
    # FILL IN: execute_kw("sh.helpdesk.ticket", "formatted_read_group", [[]], {"groupby": ["stage_id"]});
    #   assert body["domain"] == [] and "ids" not in body — regression for ledger c32c408ded92 (AC1)
    ...


@pytest.mark.asyncio
async def test_execute_kw_domain_first_rejects_extra_positional_args():
    session = _mock_aiohttp_response([])
    transport = Json2Transport(_config())

    with patch("aiohttp.ClientSession", return_value=session):
        with pytest.raises(OdooRPCError):
            await transport.execute_kw("sale.order", "read_group", [[], ["state"], ["state"]], None)

    # FILL IN: assert session.post was never called — AC2 ("before any HTTP call")
```
**Why**: reuses the neighbouring tests' mock pattern verbatim; no new fixtures. Replace each `...` stub with a real body — none may remain.

### FILL IN checklist
- [ ] `test_execute_kw_formatted_read_group_maps_domain_and_kwargs` — exact body equality; AC1
- [ ] `test_execute_kw_read_group_maps_domain_and_kwargs` — full test body incl. `lazy` passthrough; AC2
- [ ] `test_execute_kw_domain_first_empty_domain_is_sent_as_domain_not_ids` — `domain == []`, no `ids`; AC1
- [ ] `test_execute_kw_domain_first_rejects_extra_positional_args` — `session.post.assert_not_called()`; AC2

---

## Acceptance Criteria

- [ ] AC1 (spec): `formatted_read_group` with `[D]` → body `{**K, "domain": D}` for `D = []` and non-empty `D`; never an `ids` key.
- [ ] AC2 (spec): same for `read_group`, `web_read_group`, `formatted_read_grouping_sets`; >1 positional raises `OdooRPCError` before any HTTP call.
- [ ] AC3 (spec): existing search-family tests pass unmodified.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py` is clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/test_odoo_json2_transport.py -q`

Run from the worktree with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src`.

---

## Test Specification

See the four tests in the blueprint. All existing tests in the module must still pass.

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug odoo-json2-domain-first-methods --feature-id FEAT-614`
2. **Read the spec** (§3 Module 1, §5, §6).
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — re-run each `grep -c` in the blueprint.
5. **Update status** in `sdd/tasks/index/odoo-json2-domain-first-methods.json` → `"in-progress"`, commit only that file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — run the Validation Commands.
8. **Commit the code** — stage only the two listed files.
9. **Close the task** — `scripts/sdd/close_task.sh TASK-3883 odoo-json2-domain-first-methods verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: gpt-5.6-terra (codex, MCP seat)
**Date**: 2026-09-30
**Notes**: Added module-level `_DOMAIN_FIRST_METHODS` and routed `_build_body` through it; 4 new transport tests. 64 tests pass (run from scratch copy: in-repo conftest fails locally on `parrot.utils` import, pre-existing env issue).

**Deviations from spec**: none
