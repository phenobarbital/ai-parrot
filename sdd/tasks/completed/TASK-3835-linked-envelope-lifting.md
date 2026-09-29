# TASK-3835: Linked-envelope lifting + v1.0 normalization

**Feature**: FEAT-611 — A2UI Linked Surfaces E2E (parallel track)
**Spec**: `sdd/specs/a2ui-linked-e2e-parallel.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements spec §3 Module 5 and §9 S1 ("one canonical linked-surface envelope boundary"). Two of the F014 blockers that keep a linked surface from reaching the admin UI through a real agent chat live in the Python response path:

1. **Nothing lifts dict tool results.** `qs_build_linked_surface` (toolkit.py:410-413) and the M8 example TOOL return `{"a2ui_envelope": <inner CreateSurface dump>, "artifacts": [{"type": "a2ui_linked_surface", ...}]}`. `BaseBot.ask()` only lifts `InteractiveRenderResult` / `InfographicRenderResult` objects (base.py:1491, :1522), so the linked envelope never reaches `response.a2ui_envelope`.
2. **There is no v1.0 normalization.** The tool's `a2ui_envelope` is the **bare** inner CreateSurface (`surfaceId`, `components`, and so on). The client (`A2UIEnvelope = {version:"v1.0", createSurface}`, a2ui-types.ts:75-78) needs the wrapped wire form that `serialize()` emits (serialization.py:104-139).

The task also surfaces the persisted surface id. When the agent called `publish_surface` in the same turn, its dict result `{"surface_id": ...}` (ui_surfaces.py:154-158) is copied to `response.metadata["a2ui_surface_id"]`. TASK-3836 consumes it to enable the server-lane Refresh.

---

## Scope

- Add `_wrap_create_surface(envelope)` to `emission.py`. It wraps a bare CreateSurface dict as `{"version": "v1.0", "createSurface": envelope}` and is idempotent: wrapped input and non-matching input are returned unchanged. Call it from `finalize_a2ui_response` before the envelope is assigned.
- Add `BaseBot._extract_last_linked_surface_result(tool_calls)`. It returns the **wrapped** envelope from the last successful tool call whose `result` is a dict with a dict `a2ui_envelope` and at least one artifact of type `a2ui_linked_surface`, else `None`.
- Add `BaseBot._extract_last_published_surface_id(tool_calls)`. It returns the `surface_id` string of the last successful `publish_surface` tool call, else `None`.
- Hook both into `ask()` after the infographic lift, with **precedence interactive > infographic > linked**. The linked envelope is set only when neither of the other lifts ran and `response.a2ui_envelope` is still `None`.
- Tests: `test_emission_wrap_create_surface.py` covers the wrap function and the three output paths from §9 S1. `test_linked_surface_lifting.py` covers the extractor, precedence and surface id.

**NOT in scope**:
- The `conversation()` path at base.py:512-516. Only `ask()` gets the lift, but `finalize_a2ui_response` wrapping applies there automatically.
- Any change to the formatter-skip condition at base.py:1579. See the Why under the `ask()` hook block.
- The server handler (`handlers/agent.py:2804-2823` already forwards `response.metadata` verbatim for `OutputMode.A2UI`) and the UI (TASK-3836).
- Changing `QuerysourceToolkit.build_linked_surface` to emit a wrapped envelope.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/emission.py` | MODIFY | Add `_wrap_create_surface`; call it in `finalize_a2ui_response` |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | Import `_wrap_create_surface`; add the two extractors; add the linked lift + surface id in `ask()` |
| `packages/ai-parrot/tests/outputs/a2ui/test_emission_wrap_create_surface.py` | CREATE | Wrap idempotency + the direct / tool-loop / non-A2UI paths |
| `packages/ai-parrot/tests/bots/test_linked_surface_lifting.py` | CREATE | Extractor, precedence (source-level), `a2ui_surface_id` |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# base.py:21 (existing — EXTEND this exact line):
from ..outputs.a2ui.emission import finalize_a2ui_response  # FEAT-273 (TASK-1738)
# emission.py (existing, :9-13):
from __future__ import annotations
from typing import Any
from parrot.models.outputs import OutputMode

# Tests:
from types import SimpleNamespace
from parrot.outputs.a2ui.emission import finalize_a2ui_response, _wrap_create_surface  # _wrap_create_surface created here
from parrot.models.outputs import OutputMode                     # verified: test_emission_wiring.py:8
from parrot.models.basic import ToolCall                         # verified: models/basic.py:23
from parrot.bots.base import BaseBot                             # verified: base.py:74 (imports OK in this venv)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/basic.py:23-30
class ToolCall(BaseModel):
    id: str; name: str; arguments: Dict[str, Any]
    result: Optional[Any] = None; error: Optional[str] = None; execution_time: Optional[float] = None
# NOTE: there is NO `status` attribute on ToolCall. Success == `error is None` (same test base.py:1481).
# tool_call.result for tools/toolkits is the RAW return value: ToolResult is unwrapped at clients/base.py:1613-1620.

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):          # :93
    tool_calls: List[ToolCall]       # :157
    metadata: Dict[str, Any]         # :194 (default_factory=dict — may still be None on duck-typed responses)
    a2ui_envelope: Optional[Dict[str, Any]]  # :212

# packages/ai-parrot/src/parrot/bots/base.py
class BaseBot(AbstractBot):                                              # :74
    def _extract_last_interactive_result(self, tool_calls) -> Optional[Any]   # :867  (reversed(tool_calls), getattr(tc,"result"))
    def _extract_last_infographic_result(self, tool_calls) -> Optional[Any]   # :921-942 (same iteration pattern)
    def _finalize_infographic_response(self, response, envelope) -> Optional[str]  # :944-982
    async def ask(self, ...)                                             # :984
    #   interactive lift :1491-1504 · infographic lift :1522-1576 · formatter-skip :1579-1580
    #   A2UI branch: `elif output_mode == OutputMode.A2UI: finalize_a2ui_response(response)` :1596-1598

# packages/ai-parrot/src/parrot/outputs/a2ui/emission.py
__all__ = ["finalize_a2ui_response"]                  # :15
def finalize_a2ui_response(response: Any) -> None     # :18-45; `response.a2ui_envelope = envelope` at :41
def _surface_id(envelope: Any) -> str | None          # :48-68 (reads createSurface.surfaceId OR bare surfaceId)

# packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py
def serialize(message) -> dict[str, Any]   # :104 — returns {VERSION_FIELD: A2UI_VERSION, key: payload} == {"version": "v1.0", "createSurface": {...}}

# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py:401-413 — linked tool result shape:
#   {"a2ui_envelope": envelope.model_dump(mode="json", by_alias=True, exclude_none=True),   # BARE inner (surfaceId, components, ...)
#    "artifacts": [{"type": "a2ui_linked_surface", "surface_id", "sources", "slug", "tenant"}]}
# packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py
#   class PublishSurfaceTool: name = "publish_surface" (:73); _execute returns {"surface_id", "kind", "refreshable"} (:154-158)
```

### Does NOT Exist
- ~~`ToolCall.status`~~. Only `error` exists. The server's `getattr(t, "status", "completed")` (agent.py:2663) is a default, not a field.
- ~~Lifting of dict tool results in `bots/base.py`~~ (spec §6). This task creates it.
- ~~`response.metadata["a2ui_surface_id"]`~~ anywhere today.
- ~~A v1.0 wrapper in `finalize_a2ui_response`~~. Today it passes dicts through verbatim (:31-41).
- ~~`parrot.outputs.a2ui.emission.wrap_create_surface`~~ (public, no underscore). The name is `_wrap_create_surface`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/outputs/a2ui/emission.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/outputs/a2ui/test_emission_wrap_create_surface.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_linked_surface_lifting.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/emission.py#finalize_a2ui_response",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/emission.py#_surface_id",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py#serialize",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot._extract_last_infographic_result",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot._extract_last_interactive_result",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask",
    "sym:packages/ai-parrot/src/parrot/models/basic.py#ToolCall",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit.build_linked_surface",
    "sym:packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py#PublishSurfaceTool"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- The extractors copy the `_extract_last_infographic_result` iteration (base.py:933-942): `for tc in reversed(tool_calls): result = getattr(tc, "result", None)`. They also add `getattr(tc, "error", None) is None`, the same success test as base.py:1481.
- The tests follow `tests/unit/bots/test_basebot_infographic_dual_emit.py`. Extractors are called **unbound** as `BaseBot._extract_...(object(), tool_calls)`, so no Agent/LLM client is instantiated; `from parrot.bots.base import BaseBot` imports cleanly in this venv (verified). The `ask()` wiring is asserted at **source level** with `inspect.getsource(BaseBot.ask)`, which is the established technique (dual_emit test :111-139) because `ask()` is not unit-invocable.

### Key Constraints
- Keep the extractors free of `self`, apart from an optional `self.logger`, which you must not use: unbound calls with `object()` would break. That makes them trivially testable.
- `_wrap_create_surface` must NOT change the existing `test_emission_wiring.py` expectations. Those pass `{"messageType": "createSurface", "surfaceId": "main"}` and `{"surfaceId": "s"}` and read `resp.a2ui_envelope["surfaceId"]` directly. Hence the predicate: **dict AND no `"version"` key AND `"surfaceId"` in it AND `"components"` in it**. Neither legacy test dict has `components`, so both stay unwrapped.
- Never mutate the tool's result dict. Wrap into a new dict, because `tool_call.result` is also serialized into `response.data` (base.py:1480-1484).
- Precedence is a design call (spec §3 table: M5 is not delegation-eligible). Interactive > infographic > linked. Linked never overwrites an envelope that another lift or the LLM output already set.

### References in Codebase
- `packages/ai-parrot/tests/outputs/a2ui/test_emission_wiring.py`: `SimpleNamespace` responses for `finalize_a2ui_response`.
- `packages/ai-parrot/tests/unit/bots/test_basebot_infographic_dual_emit.py`: unbound-method + source-level patterns.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Add `_wrap_create_surface` to `emission.py` and call it in `finalize_a2ui_response`. *Why*: this is the single canonical v1.0 boundary (§9 S1), and every A2UI path already goes through it.
2. Extend the `base.py:21` import. *Why*: the extractor returns the wrapped form (skeleton contract).
3. Add the two extractors above `async def ask(`. *Why*: they sit with their siblings.
4. Insert the linked lift before `# Determine output mode` in `ask()`. *Why*: it runs after both older lifts, so precedence falls out of ordering plus the `is None` checks.
5. Write both test files and run the Validation Commands, including the two existing suites.

### `packages/ai-parrot/src/parrot/outputs/a2ui/emission.py` (MODIFY) — call site
```python
# occurrences: 1 (verified: grep -cF '    response.a2ui_envelope = envelope' packages/ai-parrot/src/parrot/outputs/a2ui/emission.py)
# BEFORE — insert above `    response.a2ui_envelope = envelope` (verified: emission.py:41)
    envelope = _wrap_create_surface(envelope)
```
**Why**: this covers every source of the envelope. That includes a pre-set `response.a2ui_envelope` (the tool-loop lift), a dict `response.output` (direct output), and the `serialize()` result, which is already wrapped and so is a no-op.

### `packages/ai-parrot/src/parrot/outputs/a2ui/emission.py` (MODIFY) — helper
```python
# occurrences: 1 (verified: grep -cF 'def _surface_id(envelope: Any) -> str | None:' packages/ai-parrot/src/parrot/outputs/a2ui/emission.py)
# BEFORE — insert above `def _surface_id(envelope: Any) -> str | None:` (verified: emission.py:48)
def _wrap_create_surface(envelope: Any) -> Any:
    """Wrap a bare CreateSurface dump as ``{"version": "v1.0", "createSurface": envelope}``.

    Idempotent: already-wrapped envelopes (any dict with ``version``), lists of sobres,
    ``None`` and dicts that are not a bare CreateSurface (no ``surfaceId`` + ``components``)
    are returned unchanged. Never mutates the input.
    """
    # FILL IN: return {"version": "v1.0", "createSurface": envelope} only when isinstance(envelope, dict)
    #   and "version" not in envelope and "surfaceId" in envelope and "components" in envelope; else return envelope
    #   — bounded by test_emission_wiring.py legacy dicts staying unwrapped (Key Constraints) and serialize() shape (:104)
```
**Why**: the skeleton is `_wrap_create_surface(envelope: dict) -> dict`. The annotation is widened to `Any` because `finalize_a2ui_response` also sees `None`/lists (FEAT-470 lists of sobres). Behaviour on dicts is exactly the skeleton's. Leave `__all__` unchanged: the helper is private, and `base.py` imports it by name.

### `packages/ai-parrot/src/parrot/bots/base.py` (MODIFY) — import
```python
# occurrences: 1 (verified: grep -cF 'from ..outputs.a2ui.emission import finalize_a2ui_response  # FEAT-273 (TASK-1738)' packages/ai-parrot/src/parrot/bots/base.py)
# REPLACE line :21 with
from ..outputs.a2ui.emission import _wrap_create_surface, finalize_a2ui_response  # FEAT-273 (TASK-1738), FEAT-611 M5
```

### `packages/ai-parrot/src/parrot/bots/base.py` (MODIFY) — extractors
```python
# occurrences: 1 (verified: grep -cF '    async def ask(' packages/ai-parrot/src/parrot/bots/base.py)
# BEFORE — insert above `    async def ask(` (verified: base.py:984)
    def _extract_last_linked_surface_result(
        self,
        tool_calls: Optional[List[Any]],
    ) -> Optional[dict]:
        """Return the v1.0-wrapped envelope of the last successful linked-surface tool result, else None.

        Matches dict results shaped ``{"a2ui_envelope": {...}, "artifacts": [{"type": "a2ui_linked_surface", ...}]}``
        — the shape of ``qs_build_linked_surface`` (toolkit.py:410-413) and the FEAT-611 example TOOL (FEAT-611 M5).
        """
        if not tool_calls:
            return None
        for tc in reversed(tool_calls):
            if getattr(tc, "error", None) is not None:
                continue
            result = getattr(tc, "result", None)
            # FILL IN: when result is a dict whose "a2ui_envelope" is a dict AND whose "artifacts" is a list containing
            #   at least one dict with type == "a2ui_linked_surface" -> return _wrap_create_surface(result["a2ui_envelope"])
            #   — bounded by: never mutate `result`; the LAST match wins (reversed); no other result types
        return None

    def _extract_last_published_surface_id(
        self,
        tool_calls: Optional[List[Any]],
    ) -> Optional[str]:
        """Return ``surface_id`` of the last successful ``publish_surface`` tool call, else None (FEAT-611 M5)."""
        if not tool_calls:
            return None
        for tc in reversed(tool_calls):
            if getattr(tc, "name", None) != "publish_surface" or getattr(tc, "error", None) is not None:
                continue
            result = getattr(tc, "result", None)
            # FILL IN: return result["surface_id"] when result is a dict and it is a non-empty str; otherwise `continue`
            #   — bounded by PublishSurfaceTool._execute return shape (ui_surfaces.py:154-158)
        return None

```
**Why**: two small `self`-free methods make unbound unit tests possible. The second method is not in the spec skeleton. It is added so the `ask()` hook stays under the block cap and so the surface id can be tested without `ask()`.

### `packages/ai-parrot/src/parrot/bots/base.py` (MODIFY) — `ask()` hook
```python
# occurrences: 2 (verified: grep -cF '# Determine output mode' packages/ai-parrot/src/parrot/bots/base.py → :512 and :1577)
# FILL IN: disambiguate — insert BEFORE the :1577 occurrence, identified by this unique 3-line context:
#                     response.output_mode = OutputMode.DEFAULT
#
#                 # Determine output mode
#                 format_kwargs = format_kwargs or {}
#                 if interactive_envelope is not None or infographic_envelope is not None:   <- unique (grep -cF → 1, :1579)
# Insert at 16-space indentation (same level as `infographic_envelope = ...` at :1522):
                # FEAT-611 M5: linked-surface lift (precedence interactive > infographic > linked).
                # Dict tool results ({"a2ui_envelope", "artifacts":[{"type":"a2ui_linked_surface"}]}) are only
                # lifted when neither typed lift ran and nothing else already set an envelope.
                if (
                    interactive_envelope is None
                    and infographic_envelope is None
                    and getattr(response, "a2ui_envelope", None) is None
                ):
                    linked_envelope = self._extract_last_linked_surface_result(getattr(response, "tool_calls", None))
                    if linked_envelope is not None:
                        response.a2ui_envelope = linked_envelope
                        self.logger.info("Linked A2UI surface lifted from tool result: surface=%s", linked_envelope["createSurface"].get("surfaceId"))
                published_surface_id = self._extract_last_published_surface_id(getattr(response, "tool_calls", None))
                if published_surface_id is not None:
                    # FILL IN: merge {"a2ui_surface_id": published_surface_id} into response.metadata without dropping keys,
                    #   tolerating metadata None (pattern: `meta = dict(getattr(response, "metadata", None) or {})` base.py:1537)
                    #   — bounded by AIMessage.metadata is Dict[str, Any] (responses.py:194)
                    pass

```
**Why**: do NOT add `linked_envelope` to the formatter-skip at :1579. The lifted envelope is **additive**, exactly like the HTML-primary infographic lane carrying `a2ui_envelope` (:1562-1563):
- `output_mode == A2UI`: the existing branch at :1596-1598 calls `finalize_a2ui_response`, which now wraps (idempotent) and sets `output_mode`.
- Any other mode: the formatter still runs and the envelope rides along. The server forwards it whenever present (agent.py:2920-2922).

Skipping the formatter would change non-A2UI output for every toolkit agent that calls `qs_build_linked_surface`. The surface id is recorded regardless of the lift, because a `publish_surface` call can follow an interactive or infographic render too.

### `packages/ai-parrot/tests/outputs/a2ui/test_emission_wrap_create_surface.py` (CREATE)
```python
"""FEAT-611 M5 / §9 S1 — finalize_a2ui_response normalizes bare CreateSurface dumps to the v1.0 wrapper."""

from __future__ import annotations

from types import SimpleNamespace

from parrot.models.outputs import OutputMode
from parrot.outputs.a2ui.emission import _wrap_create_surface, finalize_a2ui_response

BARE = {"surfaceId": "linked-activity", "components": [{"id": "root", "component": "Chart"}], "dataModel": {}}
WRAPPED = {"version": "v1.0", "createSurface": BARE}


def _resp(**kwargs) -> SimpleNamespace:
    defaults = dict(a2ui_envelope=None, output=None, response=None, output_mode=OutputMode.DEFAULT)
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_wrap_bare_create_surface() -> None:
    assert _wrap_create_surface(BARE) == WRAPPED


def test_wrap_is_idempotent() -> None:
    # FILL IN: _wrap_create_surface(WRAPPED) == WRAPPED and _wrap_create_surface(_wrap_create_surface(BARE)) == WRAPPED
    ...


def test_wrap_leaves_non_create_surface_untouched() -> None:
    # FILL IN: None, [WRAPPED], {"surfaceId": "s"}, {"messageType": "createSurface", "surfaceId": "main"} unchanged (identity or ==)
    ...


def test_finalize_wraps_bare_create_surface_direct_output() -> None:
    """Direct output: the LLM/structured path put a bare CreateSurface dict in response.output."""
    # FILL IN: resp = _resp(output=dict(BARE)); finalize -> resp.a2ui_envelope == WRAPPED; output_mode A2UI;
    #   "linked-activity" in resp.response (fallback text via _surface_id)
    ...


def test_finalize_wraps_bare_create_surface_tool_loop_output() -> None:
    """Tool-loop output: ask() pre-set response.a2ui_envelope from a tool result."""
    # FILL IN: resp = _resp(a2ui_envelope=dict(BARE), output="prose"); finalize -> a2ui_envelope == WRAPPED; output == "prose"
    ...


def test_finalize_non_a2ui_output_unchanged() -> None:
    """Non-A2UI output: a string output / non-surface dict passes through verbatim."""
    # FILL IN: resp = _resp(output="plain text") -> a2ui_envelope is None; resp2 = _resp(output={"rows": [1]}) -> a2ui_envelope == {"rows": [1]}
    #   (pre-existing verbatim dict behaviour, emission.py:31-34) — bounded by no regression vs test_emission_wiring.py
    ...
```

### `packages/ai-parrot/tests/bots/test_linked_surface_lifting.py` (CREATE)
```python
"""FEAT-611 M5 — BaseBot linked-surface lift, precedence and a2ui_surface_id (spec §4)."""

from __future__ import annotations

import inspect

import pytest

from parrot.models.basic import ToolCall

INNER = {"surfaceId": "linked-activity", "components": [{"id": "root", "component": "Chart"}], "dataModel": {}}
LINKED_RESULT = {"a2ui_envelope": INNER, "artifacts": [{"type": "a2ui_linked_surface", "surface_id": "linked-activity"}]}


def _base_bot():
    try:
        from parrot.bots.base import BaseBot
    except Exception as exc:  # noqa: BLE001 - same guard as test_basebot_infographic_dual_emit.py:71-76
        pytest.skip(f"cannot import parrot.bots.base: {exc}")
    return BaseBot


def _tc(name: str, result=None, error: str | None = None) -> ToolCall:
    return ToolCall(id=f"call-{name}", name=name, arguments={}, result=result, error=error)


def test_extract_last_linked_surface_result_wraps() -> None:
    extract = _base_bot()._extract_last_linked_surface_result
    assert extract(object(), [_tc("qs_build_linked_surface", LINKED_RESULT)]) == {"version": "v1.0", "createSurface": INNER}


def test_extract_last_linked_surface_result_ignores_non_linked() -> None:
    # FILL IN: None for: [] / None; dict without artifacts; artifacts of another type; errored call (error="boom");
    #   non-dict result — and LINKED_RESULT is not mutated (still has bare INNER) after a successful extract
    ...


def test_extract_last_linked_surface_result_last_wins() -> None:
    # FILL IN: two linked results with different surfaceId -> the later one is returned
    ...


def test_extract_last_published_surface_id() -> None:
    # FILL IN: [_tc("publish_surface", {"surface_id": "srf-1", "kind": "dashboard", "refreshable": True})] -> "srf-1";
    #   errored publish / other tool name / missing surface_id -> None
    ...


def test_ask_linked_lift_precedence_source_level() -> None:
    """ask() lifts linked only after the interactive and infographic lifts, and never over an existing envelope."""
    source = inspect.getsource(_base_bot().ask)
    # FILL IN: assert index("_extract_last_infographic_result(") < index("_extract_last_linked_surface_result(");
    #   assert "interactive_envelope is None" and "infographic_envelope is None" appear in the lift guard;
    #   assert '"a2ui_surface_id"' in source; assert the :1579 skip line is unchanged (no "linked_envelope" in it)
    ...
```
**Why**: `ask()` cannot be invoked in a unit test (dual_emit test docstring :3-8), so precedence is asserted at source level, and behaviour is covered through the unbound extractors and `finalize_a2ui_response`. Together these give the spec §4 rows `test_extract_last_linked_surface_result` and `test_finalize_wraps_bare_create_surface`, which cover direct output, tool-loop output and non-A2UI output.

### FILL IN checklist
- [ ] `emission.py::_wrap_create_surface`: the predicate; bounded by legacy test dicts staying unwrapped.
- [ ] `base.py::_extract_last_linked_surface_result`: the dict/artifact match; no mutation; last wins.
- [ ] `base.py::_extract_last_published_surface_id`: the str `surface_id` guard.
- [ ] `base.py::ask`: the `metadata` merge for `a2ui_surface_id`; remove the placeholder `pass`.
- [ ] Both test files: every `...` body.

---

## Acceptance Criteria

- [ ] A dict tool result carrying an `a2ui_linked_surface` artifact produces `response.a2ui_envelope == {"version": "v1.0", "createSurface": <inner>}` when no interactive or infographic lift ran.
- [ ] Precedence interactive > infographic > linked holds, and linked never overwrites an existing envelope.
- [ ] `finalize_a2ui_response` wraps bare CreateSurface dumps and is idempotent. `test_emission_wiring.py` still passes unchanged.
- [ ] `response.metadata["a2ui_surface_id"]` is set from the last successful `publish_surface` call.
- [ ] The formatter-skip condition at base.py:1579 is unchanged.
- [ ] `ruff check` is clean on `emission.py`, `base.py` (touched hunks) and both new test files.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/outputs/a2ui/test_emission_wrap_create_surface.py -q`
- `pytest packages/ai-parrot/tests/bots/test_linked_surface_lifting.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_emission_wiring.py -q`
- `pytest packages/ai-parrot/tests/unit/bots/test_basebot_infographic_dual_emit.py -q`

---

## Test Specification

See the two CREATE blocks above: 6 emission tests and 5 lifting tests.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**
   (`python -m scripts.sdd.ensure_worktree --slug a2ui-linked-e2e-parallel --feature-id FEAT-611`).
2. **Read the spec**, in particular §3 M5 and §9 S1.
3. **Check dependencies**: none.
4. **Verify the Codebase Contract**: re-run each `grep -cF` anchor. For the `ask()` hook, confirm that `if interactive_envelope is not None or infographic_envelope is not None:` is still unique.
5. **Update status** in `sdd/tasks/index/a2ui-linked-e2e-parallel.json` → `"in-progress"`.
6. **Implement** from the Blueprint, and complete every `# FILL IN:`.
7. **Verify** by running the Validation Commands.
8. **Commit the code**. Stage only the four files listed.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3835 a2ui-linked-e2e-parallel verified`.
10. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: SDD sub-agent (session_01CFWijXsJLATx5g6k94o1EP), sub-worktree feat-FEAT-611-sub-TASK-3835 (commit fa5b7b092, merged)
**Date**: 2026-09-28
**Notes**:
- `emission.py`: added `_wrap_create_surface` and called it in `finalize_a2ui_response`. A bare CreateSurface (no `version`, with `surfaceId` and `components`) becomes `{"version":"v1.0","createSurface":...}`. It is idempotent, and the legacy dicts in `test_emission_wiring` stay unwrapped.
- `bots/base.py`: added `_extract_last_linked_surface_result` and `_extract_last_published_surface_id`.
  - `ask()` lifts the linked envelope only when neither the interactive nor the infographic lift ran (precedence interactive > infographic > linked).
  - `a2ui_surface_id` is merged into `response.metadata`.
  - The formatter-skip condition is unchanged.
- Tests: 12 new tests. `test_emission_wiring` (8) and `test_basebot_infographic_dual_emit` (6) still pass.
- Integrated on the feature branch together with TASK-3834: 142 passed (ai-parrot linked + emission + lifting) and 23 passed (server linked E2E and handlers).
- The failures seen in wider related suites also occur on the unmodified base: `test_db_agent_structured_table_artifact` and `test_agent_a2ui_stream`. Two others are order-dependent.

**Deviations from spec**: The log line in `ask()` uses a KeyError-safe `.get("createSurface", {})`, and there is one extra no-mutation test. Cython `.so` files were symlinked in from the main checkout to run tests; they are untracked.
