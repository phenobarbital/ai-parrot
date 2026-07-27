# TASK-1956: Route `clients/live.py` tool execution through the real pipeline

**Feature**: FEAT-380 — Tool Result Compression Pipeline
**Spec**: `sdd/specs/tool-result-compression.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1952
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7, Q4 resolved. `parrot/clients/live.py:401` calls the
**private** `tool._execute()`, bypassing `AbstractTool.execute()` entirely.
The consequence is worse than a missing compression stage: this route has **no
permission checks, no credential broker, no redaction, no lifecycle events and
no standardized `ToolResult`**.

Q4 resolved this as **full routing in this feature**: replace the private call
with the real pipeline, restoring all four protections plus compression in one
wiring change.

`voice_text` and `display_data` keep their special handling — they are
extracted **after** the pipeline from the uncompressed `ToolResult` fields and
are NEVER compressed. Regression risk on the voice path is accepted and
covered by dedicated tests.

---

## Scope

- Replace the `hasattr(tool, '_execute')` / `await tool._execute(**tool_args)`
  branch (live.py ~397-401) with a call that goes through the pipeline —
  `AbstractTool.execute()` at minimum, and `ToolManager.execute_tool()` where
  the live client has a manager available.
- Preserve the plain-callable branch (`hasattr(tool, '__call__')`) unchanged;
  it is not an `AbstractTool` and has no pipeline to route through.
- Preserve the `voice_text` / `display_data` handling at live.py:416-437,
  reading them from the **uncompressed `ToolResult` fields**, after the
  pipeline. Neither field is ever passed to a codec.
- Handle the statuses `AbstractTool.execute()` can now return that the old
  private call never produced — in particular `status == "forbidden"`
  (abstract.py L559-569 can return it before `_execute` is ever reached) and
  `status == "error"`. Map them to the existing
  `{"error": ...}` `FunctionResponse` shape; do not leak an exception into
  the live session.
- Keep the `(types.FunctionResponse, Optional[Dict[str, Any]])` return
  contract intact — callers at live.py:924/956-957 and 1227/1252-1255
  propagate `display_data` into message metadata and must keep working.

**NOT in scope**:
- Redesigning the live client's session/tool-map wiring beyond what routing
  requires.
- Any change to `parrot/tools/manager.py` → TASK-1952/1953 own that file.
- Adding compression-specific behavior to the voice path — the requirement is
  the opposite: it must be untouched.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/live.py` | MODIFY | Replace `tool._execute()` with pipeline routing; preserve voice/display handling |
| `packages/ai-parrot/tests/clients/test_live_tool_routing.py` | CREATE | Unit tests including `test_live_voice_fields_never_compressed` |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against HEAD `024c21d44` on 2026-07-27.
> **Path mapping**: `parrot/...` means `packages/ai-parrot/src/parrot/...`.

### Verified Imports

```python
from parrot.tools import AbstractTool, ToolResult
    # re-export tools/__init__.py:142-143; __all__ entries 216-219
```

### Existing Signatures to Use

**VERBATIM — `parrot/clients/live.py`, the code to change:**

```python
async def execute_tool(                                        # line 367
    self,
    function_call: Any,
    context: Optional[Dict[str, Any]] = None
) -> tuple[types.FunctionResponse, Optional[Dict[str, Any]]]:
    ...
    # Execute the tool
    if hasattr(tool, '_execute'):
        # AbstractTool
        result = await tool._execute(**tool_args)              # line 401 ← THE BYPASS
    elif hasattr(tool, '__call__'):
        # Callable
        called = tool(**tool_args)
        if inspect.iscoroutine(called):
            result = await called
        else:
            result = called
    else:
        return types.FunctionResponse(
            name=tool_name, id=tool_id,
            response={"error": f"Tool '{tool_name}' is not executable"}
        )

    # Handle ToolResult from AbstractTool                       # lines 416-437
    display_data = None
    if isinstance(result, ToolResult):                          # line 419
        if result.status == "success":
            if result.display_data:
                display_data = result.display_data
            if result.voice_text:
                response_data = {"output": result.voice_text}
            elif isinstance(result.result, dict):
                response_data = result.result
            elif isinstance(result.result, str):
                response_data = {"output": result.result}
            else:
                response_data = {"output": str(result.result) if result.result else "Success"}
        else:
            response_data = {"error": result.error or "Unknown error"}
    else:
        ...
```

```python
# parrot/tools/abstract.py:126
class AbstractTool(EventEmitterMixin, ABC):
    return_direct: bool = False                       # line 144
    async def execute(self, *args, **kwargs) -> ToolResult: ...  # line 527
    # execute() handles _permission_context/_resolver/_broker and CAN return
    # status='forbidden' before reaching _execute (lines 559-569).
    async def _execute(self, **kwargs) -> Any: ...    # abstract, line 293

# parrot/tools/abstract.py:91
class ToolResult(BaseModel):
    status: str = "success"
    result: Any
    error: Optional[str] = None
    metadata: Dict[str, Any]
    voice_text: Optional[str] = None                  # line 109
    display_data: Optional[Dict[str, Any]] = None     # line 110
    @property
    def spoken_content(self) -> str: ...              # line 113
    @property
    def has_display_content(self) -> bool: ...        # line 120

# parrot/tools/manager.py:1379 — the pipeline entry point
async def execute_tool(
    self, tool_name: str, parameters: Dict[str, Any],
    permission_context: Optional["PermissionContext"] = None,
) -> Any: ...
```

### Does NOT Exist

- ~~A second bypass of `AbstractTool.execute()` elsewhere in `parrot/clients/`~~
  — `live.py:401` is the one. Verify with
  `grep -rn "_execute(" packages/ai-parrot/src/parrot/clients/` before
  assuming your change is complete.
- ~~`isinstance(result, ToolResult)` being reliably `True` today~~ — at
  live.py:419 it is **rarely** True, because `_execute()` returns a raw `Any`.
  After your change it should normally be `True`; the `else` branch stays as
  the fallback for the plain-callable path.
- ~~Compression of `voice_text`/`display_data`~~ — explicitly forbidden. They
  are `ToolResult` fields, not the payload; the pipeline compresses
  `result.result` only.
- ~~`ToolManager` guaranteed to be present on the live client~~ — verify how
  `self.tool_map` is populated and whether a manager is reachable; if not,
  route through `AbstractTool.execute()` and document the choice.

---

## Implementation Notes

### Pattern to Follow

```python
if isinstance(tool, AbstractTool):
    result = await tool.execute(**tool_args)     # permissions, broker, redaction, events
elif hasattr(tool, '__call__'):
    ...                                          # unchanged
```

Then the existing 416-437 block keeps working unchanged, because `result` is
now reliably a `ToolResult` — read `voice_text` / `display_data` straight off
it, never off the compressed payload.

### Key Constraints

- **The voice path is the regression risk.** `voice_text` is what the user
  hears; if compression ever touches it, the feature ships a user-visible
  defect. The test `test_live_voice_fields_never_compressed` is the gate.
- `status == "forbidden"` is a NEW reachable outcome on this path. It must
  produce a clean `{"error": ...}` response, not an exception and not a
  silent success.
- Prefer `isinstance(tool, AbstractTool)` over `hasattr(tool, '_execute')` —
  the `hasattr` check is what let the private call look reasonable.
- Do not change the tuple return contract; downstream code at live.py:924,
  956-957, 1227, 1252-1255 depends on it.
- Keep the trusted-context injection above (the loop overwriting
  LLM-provided args with `context` values) exactly as is — it is a security
  control.

### References in Codebase

- `parrot/tools/abstract.py:527` — `execute()`, the method being restored to
  the call path.
- `parrot/tools/manager.py:1379` — `execute_tool()`, the full pipeline.

---

## Acceptance Criteria

- [ ] `grep -n "_execute(" packages/ai-parrot/src/parrot/clients/live.py`
      returns no direct private tool call.
- [ ] `test_live_voice_fields_never_compressed`: `voice_text` and
      `display_data` reach the live handler byte-identical to what the tool
      emitted, even when `result.result` was compressed.
- [ ] Permissions are enforced on the live route: a tool returning
      `status='forbidden'` produces `{"error": ...}` and never executes.
- [ ] The plain-callable branch behaves exactly as before.
- [ ] The `(FunctionResponse, display_data)` return contract is unchanged;
      existing live tests pass.
- [ ] Lifecycle events are now emitted for live tool calls (they were not
      before).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/clients/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/live.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_live_tool_routing.py
import pytest
from parrot.tools import AbstractTool, ToolResult


class VoiceTool(AbstractTool):
    name = "voice_tool"
    async def _execute(self, **kwargs):
        return ToolResult(
            result=[{"a": i, "b": None} for i in range(500)],
            voice_text="Here are your five hundred rows.",
            display_data={"chart": "bar", "series": [1, 2, 3]},
        )


class TestLiveRouting:
    async def test_live_voice_fields_never_compressed(self, live_client):
        resp, display = await live_client.execute_tool(_call("voice_tool"))
        assert resp.response["output"] == "Here are your five hundred rows."
        assert display == {"chart": "bar", "series": [1, 2, 3]}

    async def test_goes_through_execute_not_private(self, live_client, monkeypatch):
        seen = []
        orig = AbstractTool.execute
        async def spy(self, *a, **k):
            seen.append(self.name)
            return await orig(self, *a, **k)
        monkeypatch.setattr(AbstractTool, "execute", spy)
        await live_client.execute_tool(_call("voice_tool"))
        assert seen == ["voice_tool"]

    async def test_forbidden_returns_error_response(self, live_client, forbidden_tool):
        resp, display = await live_client.execute_tool(_call("forbidden_tool"))
        assert "error" in resp.response
        assert display is None

    async def test_plain_callable_branch_unchanged(self, live_client):
        resp, _ = await live_client.execute_tool(_call("plain_callable"))
        assert resp.response == {"output": "ok"}

    async def test_return_contract_is_tuple(self, live_client):
        out = await live_client.execute_tool(_call("voice_tool"))
        assert isinstance(out, tuple) and len(out) == 2
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 7, Q4, §6 live.py facts).
2. **Check dependencies** — TASK-1952 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `live.py:367-440` and confirm
   line anchors; also check whether a `ToolManager` is reachable from the live
   client before choosing between `execute_tool()` and `tool.execute()`.
4. **Update status** in `sdd/tasks/index/tool-result-compression.json`.
5. **Implement** per scope.
6. **Verify** acceptance criteria — run the full live-client test suite, not
   just the new file.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** — state explicitly which routing target you
   used and why.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
