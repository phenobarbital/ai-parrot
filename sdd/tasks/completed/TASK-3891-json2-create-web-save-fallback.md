# TASK-3891: JSON-2 transport — `create` falls back to `web_save` on Odoo 19 signature errors

**Feature**: FEAT-616 — OdooHelpdeskToolkit — typed helpdesk tools for the Softhealer helpdesk (Odoo 19)
**Spec**: `sdd/specs/odoo-toolkit-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:e17074affa1b`

---

## Context

Implements spec §3 **Module 1** (G5, AC1, AC19). On the staging Odoo 19 build, `POST /json/2/<model>/create`
rejects every named-argument form for models whose `create` is overridden (Softhealer helpdesk models):
`vals_list` → 422 *missing a required argument: 'values'*, `values`/`vals` → 500 *unexpected keyword argument*.
`web_save({"vals": …, "specification": {"id": {}}})` creates the record and returns `[{"id": …}]`
(live evidence `sdd/state/FEAT-616/findings/live/13_action_verification.json`). Wizard/transient models accept
the normal `create`, so the fast path must stay. Every later helpdesk task creates records through
`OdooToolkit._execute(model, "create", [vals])` and relies on this fallback.

**Ordering note**: FEAT-614 (TASK-3883) also edits `json2.py` (adds `_DOMAIN_FIRST_METHODS` before the class
and changes one branch of `_build_body`). The feature worktree is created after FEAT-614 merges, so re-run
every `grep -c` below — line numbers shift by ~12 but the anchors are unchanged.

---

## Scope

- Add `Json2Transport._is_create_signature_error(exc)` (staticmethod) and `Json2Transport._create_via_web_save(model, vals)`.
- Wrap the `create` path inside `Json2Transport.execute_kw`: try the existing body; on a matching `OdooRPCError`
  retry via `web_save`, normalising the return shape to `create`'s (`int` for one dict, `list[int]` for a list).
- One `logger.debug` line on fallback.
- Four new tests in `packages/ai-parrot/tests/test_odoo_json2_transport.py`.

**NOT in scope**: `_build_body` (FEAT-614 owns it), `get_views` mapping (`issue:f5ae793643be`), XML-RPC/JSON-RPC,
anything in `toolkit.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py` | MODIFY | fallback helpers + `execute_kw` create branch |
| `packages/ai-parrot/tests/test_odoo_json2_transport.py` | MODIFY | four new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# json2.py already imports everything needed — add NO new imports:
import asyncio, logging                                                  # verified: json2.py:12-14
from typing import Any                                                   # verified: json2.py:16
import aiohttp                                                           # verified: json2.py:18
from parrot.interfaces.odoointerface import OdooAuthenticationError, OdooConfig, OdooConnectionError, OdooRPCError, _validate_model_name   # verified: json2.py:20-26
from .base import AbstractOdooTransport                                  # verified: json2.py:28

# test file already has:
from unittest.mock import AsyncMock, MagicMock, patch                    # verified: test_odoo_json2_transport.py:7
import pytest                                                            # verified: :9
from parrot.interfaces.odoointerface import OdooAuthenticationError, OdooConfig, OdooRPCError   # verified: :27-31
from parrot_tools.odoo.transport.json2 import Json2Transport             # verified: :32
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py   (verified at b3141f286)
logger = logging.getLogger(...)                                          # module logger — grep 'logger = logging.getLogger' json2.py; if absent, use logging.getLogger(__name__) at module level
def _looks_like_ids(value: Any) -> bool:                                 # line 31
class Json2Transport(AbstractOdooTransport):                             # line 38
    async def _request_json2(self, model: str, method: str, body: dict[str, Any] | None = None) -> Any   # line 67-88
        # raises OdooRPCError(f"Odoo JSON-2 error [{resp.status}] calling {model}.{method}: {message}") at line 84
        # raises OdooAuthenticationError for 401/403; OdooConnectionError on network errors
    @staticmethod
    def _build_body(method, args, kwargs) -> dict[str, Any]              # line 90-162; "create" branch line 114-118 → {"vals_list": args[0]}
    async def execute_kw(self, model: str, method: str, args: list[Any] | None = None, kwargs: dict[str, Any] | None = None) -> Any:   # line 171-179
        body = self._build_body(method, args, kwargs)                    # line 178
        return await self._request_json2(model, method, body)            # line 179

# packages/ai-parrot/tests/test_odoo_json2_transport.py
def _config(**overrides) -> OdooConfig                                   # line 35
def _mock_aiohttp_response(body, status: int = 200)                      # line 47 — MagicMock session whose .post returns an async context manager
# existing create test: test_execute_kw_create_maps_values_to_vals_list   # line 116-125 (fast path; must keep passing)
# last test: test_json2_unauthorized_maps_to_authentication_error         # line 162
```

### Does NOT Exist
- ~~`Json2Transport.create()` / `.web_save()` public helpers~~ — only `execute_kw` and the private `_create_via_web_save`.
- ~~a `web_save` branch in `_build_body`~~ — the fallback calls `_request_json2` directly with a hand-built body.
- ~~retry on `OdooAuthenticationError` / `OdooConnectionError`~~ — only `OdooRPCError` matching the predicate is retried.
- ~~`_DOMAIN_FIRST_METHODS`~~ — exists only after FEAT-614 merges; this task does not touch or need it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_odoo_json2_transport.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py#Json2Transport.execute_kw",
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py#Json2Transport._request_json2",
    "sym:packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py#Json2Transport._build_body"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Fast path byte-identical: `create` still sends `{"vals_list": args[0]}` first (AC1, existing test `:116`).
- Predicate is message-based and narrow: `"calling <model>.create"` **and** (`"missing a required argument"` or `"unexpected keyword argument"`). Anything else re-raises unchanged (AC1).
- One `web_save` call per dict; return `int` for a dict input, `list[int]` for a list input.
- `black` 120, `ruff check` clean.

---

## Implementation Blueprint

### Steps (in order)
1. Add the two private helpers inside `Json2Transport`, right above `execute_kw` — *why*: keeps the fallback next to the only call site.
2. Rewrite `execute_kw` so that only `method == "create"` gets the try/except — *why*: no other method may be retried (S7-style safety).
3. Append the four tests after the last test — *why*: the two 4xx/5xx variants are the exact staging symptoms.
4. Run the Validation Commands.

### `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def execute_kw(' packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py)
# BEFORE — insert above `    async def execute_kw(` (verified: json2.py:171 at b3141f286; re-grep after FEAT-614)

    @staticmethod
    def _is_create_signature_error(exc: OdooRPCError) -> bool:
        """True when Odoo rejected a JSON-2 ``create`` because of its argument name (422/500)."""
        text = str(exc)
        if ".create:" not in text:
            return False
        return "missing a required argument" in text or "unexpected keyword argument" in text

    async def _create_via_web_save(self, model: str, vals: dict[str, Any] | list[dict[str, Any]]) -> int | list[int]:
        """Create through ``web_save`` (one call per dict) and return ``create``'s id shape."""
        records = vals if isinstance(vals, list) else [vals]
        ids: list[int] = []
        for record in records:
            result = await self._request_json2(model, "web_save", {"vals": record, "specification": {"id": {}}})
            # FILL IN: extract the id from `result` — web_save returns [{"id": <int>, ...}]; raise OdooRPCError
            #   with a clear message when the shape is unexpected — bounded by AC1
            ids.append(int(result[0]["id"]))
        return ids if isinstance(vals, list) else ids[0]

# REPLACE the body of execute_kw (json2.py:171-179) WITH:
    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        body = self._build_body(method, args, kwargs)
        if method != "create":
            return await self._request_json2(model, method, body)
        try:
            return await self._request_json2(model, method, body)
        except OdooRPCError as exc:
            if not self._is_create_signature_error(exc):
                raise
            logger.debug("JSON-2 create rejected for %s (%s); retrying via web_save", model, exc)
            return await self._create_via_web_save(model, body["vals_list"])
```
**Why this shape**: spec §3 M1 fixes the predicate, the `web_save` body and the return normalisation. `body["vals_list"]` is what `_build_body`'s create branch produced (json2.py:117), so the same values reach `web_save`. If `json2.py` has no module-level `logger`, add `logger = logging.getLogger(__name__)` after the imports (verify with `grep -n 'getLogger' json2.py` first).

### `packages/ai-parrot/tests/test_odoo_json2_transport.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def test_json2_unauthorized_maps_to_authentication_error():' packages/ai-parrot/tests/test_odoo_json2_transport.py)
# AFTER — append at end of file, below the end of that test (verified: test_odoo_json2_transport.py:162)


def _session_with_responses(responses):
    """Session whose successive .post() calls yield (status, body) pairs in order."""
    # FILL IN: build a MagicMock session like _mock_aiohttp_response (line 47) but with a side_effect that
    #   pops the next (status, body) pair on each post() — bounded by the existing helper's shape
    ...


@pytest.mark.asyncio
async def test_execute_kw_create_falls_back_to_web_save_on_missing_argument():
    session = _session_with_responses([
        (422, {"message": "missing a required argument: 'values'"}),
        (200, [{"id": 70}]),
    ])
    transport = Json2Transport(_config())
    with patch("aiohttp.ClientSession", return_value=session):
        result = await transport.execute_kw("sh.helpdesk.ticket", "create", [{"partner_id": 1}], None)
    assert result == 70
    urls = [c.args[0] for c in session.post.call_args_list]
    assert urls[0].endswith("/json/2/sh.helpdesk.ticket/create")
    assert urls[1].endswith("/json/2/sh.helpdesk.ticket/web_save")
    assert session.post.call_args_list[1].kwargs["json"] == {"vals": {"partner_id": 1}, "specification": {"id": {}}}


@pytest.mark.asyncio
async def test_execute_kw_create_falls_back_on_unexpected_keyword():
    # FILL IN: first response (500, {"message": "HelpdeskTags.create() got an unexpected keyword argument 'vals'"}),
    #   second (200, [{"id": 5}]); assert result == 5 and two posts — AC1
    ...


@pytest.mark.asyncio
async def test_execute_kw_create_list_uses_one_web_save_per_record():
    # FILL IN: args [[{"name": "a"}, {"name": "b"}]] → responses 422, then (200,[{"id":1}]), (200,[{"id":2}]);
    #   assert result == [1, 2] and three posts — AC1
    ...


@pytest.mark.asyncio
async def test_execute_kw_create_does_not_retry_other_errors():
    # FILL IN: single response (422, {"message": "Invalid field 'x' on 'res.partner'"}); pytest.raises(OdooRPCError);
    #   assert exactly one post — AC1
    ...
```
**Why**: the two message variants are verbatim from staging; the list case pins the "one `web_save` per dict" rule; the last test proves the predicate is narrow. Replace every `...` with a real body.

### FILL IN checklist
- [ ] `json2.py::_create_via_web_save` — unexpected `web_save` shape raises `OdooRPCError`; bounded by AC1
- [ ] `json2.py` module `logger` — reuse the existing one or add `logging.getLogger(__name__)`
- [ ] `_session_with_responses` helper — ordered `(status, body)` side effects
- [ ] three `...` test bodies — AC1

---

## Acceptance Criteria

- [ ] AC1 (spec): fallback on 422/500 signature errors, `int`/`list[int]` return, other errors re-raised, existing test `:116` untouched and passing.
- [ ] AC19 (spec): `issue:e17074affa1b` claimed at `/sdd-start` (`wikitoolkit ledger claim`), closed by `/sdd-done`.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_odoo_json2_transport.py -q`

Run from the worktree with `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src`.

---

## Test Specification

See the blueprint: four new tests plus the whole existing module green.

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug odoo-toolkit-upgrades --feature-id FEAT-616` (only after FEAT-614 is merged into `dev`).
2. **Read the spec** (§2 rule 2, §3 M1, §6).
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — re-run each `grep -c`; if the `create` branch of `_build_body` moved, re-locate `execute_kw`.
5. **Update status** in `sdd/tasks/index/odoo-toolkit-upgrades.json` → `"in-progress"`, commit only that file; `wikitoolkit ledger claim issue:e17074affa1b`.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands.
8. **Commit the code** — only the two listed files.
9. **Close the task** — `scripts/sdd/close_task.sh TASK-3891 odoo-toolkit-upgrades verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

**Completed by**: sdd-worker (FEAT-616)
**Date**: 2026-10-01
**Notes**: gpt-5.6-terra (codex) via sdd-coder; diff reviewed against contract. Tests NOT runnable locally (venv: parrot.utils is not a package, pre-existing); merge-tier sweep red on unrelated failures, accepted as pre-existing by user.

**Deviations from spec**: none | describe if any
