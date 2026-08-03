# TASK-2104: Declare toolConfiguration in promptStart so toolUse can happen

**Feature**: FEAT-408 — Nova Sonic Protocol Fidelity
**Spec**: `sdd/specs/nova-sonic-protocol-fidelity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2101
**Assigned-to**: unassigned

---

## Context

Implements spec Module 5 (gap 1) — the headline finding of the audit.
`stream_voice()` has a full `toolUse` → `_execute_tool` → `toolResult` branch,
but `promptStart` **never declares `toolConfiguration`**. Nova therefore never
emits a `toolUse` event, so that entire branch is unreachable dead code and
voice agents have silently had no tools.

Reference: `nova_sonic_tool_use.py:345-366` — `toolConfiguration.tools[]` with a
`toolSpec` per tool: `{name, description, inputSchema: {json: <schema>}}`.

---

## Scope

- Add `_build_tool_configuration() -> Optional[Dict[str, Any]]` converting the
  client's registered tools into `{"tools": [{"toolSpec": {...}}, ...]}`.
- Include it in the `promptStart` frame (via TASK-2101's `_build_prompt_start()`)
  **only when tools exist**; omit the key entirely otherwise.
- Reuse the existing schema-cleaning approach rather than inventing one (see
  Implementation Notes — resolves spec §8 open question 4 in favour of the
  Google adapter's logic, adapted).
- Tests: schema conversion, and absence of the key for tool-less clients.

**NOT in scope**: receiving `toolUse` or sending `toolResult` (TASK-2105); tool
execution semantics; changing `AbstractTool`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/nova/audio.py` | MODIFY | `_build_tool_configuration()` + wire into `promptStart` |
| `packages/ai-parrot/tests/clients/test_nova_tool_configuration.py` | CREATE | Conversion + absence tests |

---

## Codebase Contract (Anti-Hallucination)

> Line numbers verified on branch `fix/nova-sonic-bidirectional-sdk` @ `89204b9f0`.

### Verified Imports

```python
from parrot.clients.nova import NovaClient          # verified: clients/nova/__init__.py:10
from parrot.tools.abstract import AbstractTool      # verified: used by clients/live.py:236 region
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/nova/audio.py
class NovaAudio:                                     # line 125
    def _build_prompt_start(self, prompt_name: str,
                            voice_id: str) -> Dict[str, Any]: ...   # ADDED BY TASK-2101

# The tool source. NovaClient inherits tool plumbing from AbstractClient via
# BedrockConverseBase. Verify BOTH of these before use:
#   self.tool_manager          — ToolManager or None
#   self.tool_manager.all_tools()  — iterable of tool instances
# Reference use of exactly this pattern:
# packages/ai-parrot/src/parrot/clients/live.py — LiveToolAdapter._build_tool_map()
#   for tool in self.tool_manager.all_tools():
#       if hasattr(tool, 'name'): self.tool_map[tool.name] = tool

# Schema extraction, verified pattern from LiveToolAdapter._tool_to_declaration():
#   full_schema = tool.get_schema()
#   tool_name = full_schema.get('name', getattr(tool, 'name', 'unknown'))
#   tool_description = full_schema.get('description', getattr(tool, 'description', ''))
#   params_schema = full_schema.get('parameters', {}).copy()
```

### Does NOT Exist

- ~~`NovaAudio._build_tool_configuration()`~~ — **this task creates it**.
- ~~`self.tools`~~ as a plain list on the client — tools live behind
  `self.tool_manager`. Read it defensively with `getattr(self, "tool_manager", None)`;
  `NovaAudio` is a mixin and cannot assume its host wired one.
- ~~`LiveToolAdapter` for Nova~~ — that class targets Google's
  `types.FunctionDeclaration` and returns Google SDK objects. **Do not reuse it
  directly**; Nova needs plain JSON-Schema dicts. Borrow only its
  `_clean_schema_for_google()` *stripping logic* if useful.
- ~~`toolSpec.inputSchema` as a bare schema~~ — it is nested:
  `{"inputSchema": {"json": <schema>}}`. In the sample the value is a JSON
  **string**; a dict is the safer starting point — see Key Constraints.
- ~~`"toolConfiguration": {"tools": []}`~~ for tool-less sessions — spec §8 open
  question 2 assumes the key must be **absent**, matching the simple sample.

---

## Implementation Notes

### Pattern to Follow

```python
    def _build_tool_configuration(self) -> Optional[Dict[str, Any]]:
        """Build Nova Sonic's toolConfiguration from the client's tools.

        Returns:
            ``{"tools": [{"toolSpec": {...}}, ...]}``, or None when the client
            has no registered tools — in which case the caller must omit the
            ``toolConfiguration`` key from ``promptStart`` entirely rather than
            sending an empty list.
        """
        manager = getattr(self, "tool_manager", None)
        if manager is None:
            return None
        specs = []
        for tool in manager.all_tools():
            try:
                schema = tool.get_schema()
            except Exception:            # a broken tool must not kill the turn
                self.logger.warning("Skipping tool with unreadable schema: %r", tool)
                continue
            specs.append({"toolSpec": {
                "name": schema.get("name", getattr(tool, "name", "unknown")),
                "description": schema.get("description",
                                          getattr(tool, "description", "")),
                "inputSchema": {"json": schema.get("parameters", {})},
            }})
        return {"tools": specs} if specs else None
```

### Key Constraints

- **Omit, don't empty.** `promptStart` must not carry `toolConfiguration` at all
  when there are no tools.
- The JSON-string-vs-dict question for `inputSchema.json` is spec §8 open
  question 2's sibling and is **unverified against the live service**. Implement
  the dict form, but keep the serialization in one place so it can be switched to
  `json.dumps(...)` in one edit. Record which you chose in the Completion Note.
- Tools cannot be confirmed working without Bedrock model access — spec §7 marks
  this as residual risk. Do not claim tool calling works; claim the frame is
  declared correctly.
- Strip JSON-Schema keys Nova may reject the same way the Google adapter does
  (`additionalProperties`, `$defs`, `title`, …) — but **do not** uppercase type
  names; that is a Google-specific requirement.

### References in Codebase

- `packages/ai-parrot/src/parrot/clients/live.py` — `LiveToolAdapter`
  (`_build_tool_map`, `_tool_to_declaration`, `_clean_schema_for_google`): the
  verified pattern for reading tools and their schemas.
- `nova_sonic_tool_use.py:345-366` (AWS sample) — the authoritative frame shape.

---

## Acceptance Criteria

- [ ] `promptStart` carries `toolConfiguration.tools[]` when the client has tools.
- [ ] Each entry is `{"toolSpec": {"name", "description", "inputSchema": {"json": …}}}`.
- [ ] `name`/`description`/schema are derived from the tool's `get_schema()`.
- [ ] `promptStart` has **no** `toolConfiguration` key when the client has no
      tools or no `tool_manager`.
- [ ] A tool whose `get_schema()` raises is skipped with a warning, not fatal.
- [ ] All existing tests pass: `pytest packages/ai-parrot/tests/clients/ -k "nova or bedrock" -q`
- [ ] No AWS access required.
- [ ] Completion Note records whether `inputSchema.json` was sent as a dict or a
      JSON string, so the live-verification follow-up knows what to check.

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_nova_tool_configuration.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.clients.nova import NovaClient
from parrot.tools import tool


@tool
def get_weather(location: str) -> str:
    """Get the current weather for a location."""
    return f"sunny in {location}"


class TestToolConfiguration:
    def test_returns_none_without_tool_manager(self):
        client = NovaClient(model="nova-2-sonic", region="us-east-1")
        client.tool_manager = None
        assert client._build_tool_configuration() is None

    def test_returns_none_with_no_tools(self):
        client = NovaClient(model="nova-2-sonic", region="us-east-1")
        client.tool_manager = MagicMock(all_tools=MagicMock(return_value=[]))
        assert client._build_tool_configuration() is None

    def test_builds_tool_spec_from_schema(self):
        client = NovaClient(model="nova-2-sonic", region="us-east-1")
        fake = MagicMock()
        fake.get_schema.return_value = {
            "name": "get_weather",
            "description": "Get the current weather for a location.",
            "parameters": {"type": "object",
                           "properties": {"location": {"type": "string"}}},
        }
        client.tool_manager = MagicMock(all_tools=MagicMock(return_value=[fake]))

        config = client._build_tool_configuration()
        spec = config["tools"][0]["toolSpec"]
        assert spec["name"] == "get_weather"
        assert spec["description"].startswith("Get the current weather")
        assert "json" in spec["inputSchema"]

    def test_tool_with_broken_schema_is_skipped(self):
        client = NovaClient(model="nova-2-sonic", region="us-east-1")
        broken = MagicMock()
        broken.get_schema.side_effect = RuntimeError("boom")
        client.tool_manager = MagicMock(all_tools=MagicMock(return_value=[broken]))
        assert client._build_tool_configuration() is None

    def test_prompt_start_omits_key_when_no_tools(self):
        client = NovaClient(model="nova-2-sonic", region="us-east-1")
        client.tool_manager = None
        frame = client._build_prompt_start("p", "matthew")
        assert "toolConfiguration" not in frame["event"]["promptStart"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2101 is in `sdd/tasks/completed/`
   (`_build_prompt_start()` must exist)
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `self.tool_manager` and `all_tools()` exist on a constructed `NovaClient`
   - Confirm the `get_schema()` shape by reading `LiveToolAdapter._tool_to_declaration`
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/nova-sonic-protocol-fidelity.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2104-tool-configuration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
**`inputSchema.json` sent as**: dict | JSON string

**Deviations from spec**: none | describe if any
