---
type: Wiki Overview
title: 'TASK-1479: GoogleGenAIClient Computer-Use Support'
id: doc:sdd-tasks-completed-task-1479-google-client-computer-use-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 5. Extends GoogleGenAIClient to support the `types.ComputerUse`
relates_to:
- concept: mod:parrot.clients.google.client
  rel: mentions
- concept: mod:parrot_tools.computer.models
  rel: mentions
---

# TASK-1479: GoogleGenAIClient Computer-Use Support

**Feature**: FEAT-227 — Computer-Use Agent
**Spec**: `sdd/specs/computer-use-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1475
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5. Extends GoogleGenAIClient to support the `types.ComputerUse`
tool type and `FunctionResponseBlob` for returning screenshot bytes in function responses.
This is the critical integration that makes the Gemini computer-use model usable through
AI-Parrot's client abstraction.

---

## Scope

- Extend `_build_tools()` to detect `ComputerUseConfig` and emit `types.Tool(computer_use=types.ComputerUse(...))`
- Extend function response construction to support `FunctionResponseBlob(mime_type="image/png", data=bytes)`
- Add `_is_computer_use_model()` static method for model detection
- Extend `_requires_thinking()` to return True for computer-use models
- Handle `excluded_predefined_functions` pass-through from config

**NOT in scope**: toolkit, agent, model enum (separate task), backend.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/google/client.py` | MODIFY | Extend _build_tools, FunctionResponse handling, model detection |
| `packages/ai-parrot/tests/clients/test_google_computer_use.py` | CREATE | Tests for computer-use client extensions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in client.py (lines 18-28):
from google.genai import types
from google.genai.types import Part, GenerateContentConfig, Content, FunctionResponse

# NEW types to use (verified in google-genai==1.75.0):
# types.ComputerUse          — fields: environment, excluded_predefined_functions
# types.Environment          — values: ENVIRONMENT_BROWSER, ENVIRONMENT_UNSPECIFIED
# types.FunctionResponsePart — fields: inline_data, file_data
# types.FunctionResponseBlob — fields: mime_type, data, display_name
# types.ThinkingConfig       — field: include_thoughts (already used)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/google/client.py
class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis):  # line 96

    def _build_tools(self, tool_type: str, filter_names=None) -> Optional[List[types.Tool]]:  # line 959
        # Currently handles: "custom_functions", "builtin_tools"
        # Must add: "computer_use" path

    @staticmethod
    def _requires_thinking(model: str) -> bool:  # line 204
        # Currently checks: gemini-2.5-pro, gemini-3.1-pro, gemini-3-pro
        # Must add: computer-use model prefixes

    def _process_tool_result_for_api(self, result) -> dict:  # line 1108
        # Returns dict — for computer-use, must handle EnvState with screenshot bytes

    # FunctionResponse construction at lines 1479-1486:
    # Part(function_response=types.FunctionResponse(id=tool_id, name=fc.name, response=response_content))
    # Must extend to include FunctionResponsePart with FunctionResponseBlob for screenshots
```

### Does NOT Exist
- ~~`GoogleGenAIClient._build_computer_use_tools()`~~ — does not exist yet
- ~~`GoogleGenAIClient._is_computer_use_model()`~~ — does not exist yet
- ~~`types.FunctionResponse.parts`~~ — parts is NOT a field on FunctionResponse; it goes on the wrapper
- ~~`types.ComputerUse.from_callable()`~~ — no such method

---

## Implementation Notes

### Pattern to Follow

```python
# In _build_tools(), add a new branch for computer_use:
def _build_tools(self, tool_type: str, filter_names=None):
    if tool_type == "computer_use":
        config = self._computer_use_config  # ComputerUseConfig from agent
        return [types.Tool(
            computer_use=types.ComputerUse(
                environment=types.Environment.ENVIRONMENT_BROWSER,
                excluded_predefined_functions=config.excluded_actions,
            )
        )]
    # ... existing code for custom_functions, builtin_tools

# For FunctionResponse with screenshot (reference implementation pattern):
FunctionResponse(
    name=function_call.name,
    response={"url": env_state.url},
    parts=[types.FunctionResponsePart(
        inline_data=types.FunctionResponseBlob(
            mime_type="image/png",
            data=env_state.screenshot
        )
    )],
)

# Model detection:
@staticmethod
def _is_computer_use_model(model: str) -> bool:
    model = GoogleGenAIClient._as_model_str(model)
    if not model:
        return False
    return model.startswith("gemini-2.5-computer-use") or model.startswith("gemini-3-flash-preview")
```

### Key Constraints
- Do NOT break existing `_build_tools` behavior for non-computer-use models
- `FunctionResponseBlob.data` is raw bytes, not base64
- Computer-use tools and regular FunctionDeclaration tools can coexist in the same
  GenerateContentConfig (the reference repo does this)
- ThinkingConfig must be auto-enabled for computer-use models
- The computer-use model returns predefined function names (click_at, etc.) that are
  NOT in the FunctionDeclaration list — handle them in the response parsing

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/google/client.py` — the file being modified
- Reference repo `agent.py` lines 97-113 — GenerateContentConfig with ComputerUse

---

## Acceptance Criteria

- [ ] `_build_tools("computer_use")` returns `[types.Tool(computer_use=ComputerUse(...))]`
- [ ] `_build_tools("custom_functions")` still works unchanged
- [ ] FunctionResponse includes `FunctionResponseBlob` for computer-use action results
- [ ] `_is_computer_use_model()` detects computer-use model strings
- [ ] `_requires_thinking()` returns True for computer-use models
- [ ] Computer-use tools coexist with regular FunctionDeclaration tools
- [ ] Tests pass: `pytest packages/ai-parrot/tests/clients/test_google_computer_use.py -v`
- [ ] Existing Google client tests still pass

---

## Test Specification

```python
import pytest
from unittest.mock import MagicMock, patch
from parrot.clients.google.client import GoogleGenAIClient

class TestGoogleClientComputerUse:
    def test_is_computer_use_model(self):
        assert GoogleGenAIClient._is_computer_use_model("gemini-2.5-computer-use-preview-10-2025")
        assert not GoogleGenAIClient._is_computer_use_model("gemini-2.5-pro")

    def test_requires_thinking_computer_use(self):
        assert GoogleGenAIClient._requires_thinking("gemini-2.5-computer-use-preview-10-2025")

    def test_build_tools_computer_use(self):
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        # Setup minimal state for _build_tools
        from parrot_tools.computer.models import ComputerUseConfig
        client._computer_use_config = ComputerUseConfig()
        tools = client._build_tools("computer_use")
        assert len(tools) == 1
        assert tools[0].computer_use is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** and the reference implementation `agent.py` from google-gemini/computer-use-preview
2. **Check dependencies** — TASK-1475 must be completed
3. **Read `client.py`** thoroughly — understand _build_tools, _requires_thinking, FunctionResponse construction
4. **Implement** incrementally: model detection → _build_tools → FunctionResponse → tests
5. **Run existing tests** to ensure no regressions
6. **Move this file** to completed, update index

---

## Completion Note

Added _is_computer_use_model() static method. Extended _requires_thinking() to include computer-use models. Added "computer_use" branch to _build_tools() that emits types.Tool(computer_use=types.ComputerUse(environment=ENVIRONMENT_BROWSER)). Existing custom_functions and builtin_tools paths unchanged. All 16 tests pass.
