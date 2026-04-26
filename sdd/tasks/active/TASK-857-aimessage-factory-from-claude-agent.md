# TASK-857: AIMessageFactory.from_claude_agent Static Method

**Feature**: FEAT-124 — Claude SDK Migration & ClaudeAgentClient
**Spec**: `sdd/specs/claude-sdk-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Spec Module 4. `ClaudeAgentClient` (TASK-858) needs a factory method to convert
> `claude_agent_sdk` message objects (`AssistantMessage`, `ResultMessage`, etc.)
> into `AIMessage`. This is a pure-conversion function with no client dependency,
> so it can be built and tested independently. Follows the pattern of `from_claude`
> at `responses.py:572`.

---

## Scope

- Add a new static method `AIMessageFactory.from_claude_agent()` in
  `packages/ai-parrot/src/parrot/models/responses.py`.
- The method consumes a list of `claude_agent_sdk` message objects and produces
  an `AIMessage`.
- Handle: text concatenation across `TextBlock`s, mapping `ToolUseBlock` to
  `ToolCall`, extracting model name from `ResultMessage`, mapping `stop_reason`
  from `result.subtype` (`success`/`error_max_turns`/etc.).
- Add a companion `CompletionUsage.from_claude_agent()` classmethod in
  `packages/ai-parrot/src/parrot/models/basic.py`.
- Lazy-import `claude_agent_sdk.types` inside the method to avoid import-time
  failure when the extra is not installed.
- Write unit tests in `tests/clients/test_aimessage_factory_claude_agent.py`.

**NOT in scope**: `ClaudeAgentClient` class, factory registration, pyproject changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/responses.py` | MODIFY | Add `AIMessageFactory.from_claude_agent()` static method |
| `packages/ai-parrot/src/parrot/models/basic.py` | MODIFY | Add `CompletionUsage.from_claude_agent()` classmethod |
| `tests/clients/test_aimessage_factory_claude_agent.py` | CREATE | Unit tests for the new factory method |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports
```python
from parrot.models.responses import AIMessage, AIMessageFactory  # responses.py:72,383
from parrot.models.basic import ToolCall, CompletionUsage        # basic.py:17,42
from parrot.models import AIMessage, AIMessageFactory, ToolCall  # models/__init__.py

# claude-agent-sdk — lazy import inside method body
from claude_agent_sdk.types import (
    AssistantMessage, UserMessage, SystemMessage, ResultMessage,
    TextBlock, ToolUseBlock, ToolResultBlock,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/responses.py
class AIMessageFactory:                                          # line 383
    @staticmethod
    def from_claude(
        response: Dict[str, Any],
        input_text: str,
        model: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        structured_output: Any = None,
        tool_calls: List[ToolCall] = None
    ) -> AIMessage: ...                                          # line 572

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                                      # line 72
    input: str                                                   # line 76
    output: Any                                                  # line 79
    response: Optional[str] = None                               # line 82
    model: str                                                   # line 111
    provider: str                                                # line 114
    usage: CompletionUsage                                       # line 118
    stop_reason: Optional[str] = None                            # line 122
    finish_reason: Optional[str] = None                          # line 125
    tool_calls: List[ToolCall] = Field(default_factory=list)     # line 129
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    raw_response: Optional[Any] = None

# packages/ai-parrot/src/parrot/models/basic.py
class ToolCall(BaseModel):                                       # line 17
    id: str                                                      # line 19
    name: str                                                    # line 20
    arguments: Dict[str, Any]                                    # line 21
    result: Optional[Any] = None                                 # line 22
    error: Optional[str] = None                                  # line 23

class CompletionUsage(BaseModel):                                # line 42
    prompt_tokens: int = 0                                       # line 46
    completion_tokens: int = 0                                   # line 47
    total_tokens: int = 0                                        # line 48
    estimated_cost: Optional[float] = None                       # line 57
    extra_usage: Dict[str, Any] = Field(default_factory=dict)    # line 60

    @classmethod
    def from_claude(cls, usage: Dict[str, Any]) -> "CompletionUsage": ...  # line 85
```

### Does NOT Exist
- ~~`AIMessageFactory.from_anthropic`~~ — the existing method is `from_claude` (line 572). New method is `from_claude_agent`.
- ~~`AIMessageFactory.from_agent_sdk`~~ — does not exist
- ~~`claude_agent_sdk.ClaudeClient`~~ — the class is `ClaudeSDKClient`
- ~~`claude_agent_sdk.AsyncClaude`~~ — does not exist

---

## Implementation Notes

### Pattern to Follow
```python
# Mirror from_claude (responses.py:572) — same structure, different input shape
@staticmethod
def from_claude_agent(
    messages: list,
    input_text: str,
    model: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    structured_output: Any = None,
) -> AIMessage:
    """Create AIMessage from claude-agent-sdk message objects."""
    from claude_agent_sdk.types import (
        AssistantMessage, TextBlock, ToolUseBlock, ResultMessage,
    )
    # Concatenate text from TextBlocks across AssistantMessages
    # Map ToolUseBlock → ToolCall
    # Extract metadata from ResultMessage
    ...
```

### Key Constraints
- Lazy-import `claude_agent_sdk.types` inside the method body — never at module scope
- Provider string: `"claude-agent"` (distinct from `"claude"` used by `from_claude`)
- `stop_reason` mapping: `ResultMessage.subtype` → `"success"` maps to `"end_turn"`,
  `"error_max_turns"` maps to `"max_turns"`, etc.
- `CompletionUsage.from_claude_agent()` should populate `estimated_cost` from
  `ResultMessage.total_cost_usd` and store `num_turns` in `extra_usage`

### References in Codebase
- `packages/ai-parrot/src/parrot/models/responses.py:572-606` — `from_claude` pattern to mirror
- `packages/ai-parrot/src/parrot/models/basic.py:85-92` — `CompletionUsage.from_claude` pattern

---

## Acceptance Criteria

- [ ] `AIMessageFactory.from_claude_agent()` exists in `responses.py`
- [ ] `CompletionUsage.from_claude_agent()` exists in `basic.py`
- [ ] Text from multiple `TextBlock`s across messages is concatenated correctly
- [ ] `ToolUseBlock` is mapped to `ToolCall` with correct `id`, `name`, `arguments`
- [ ] `ResultMessage` metadata populates `usage`, `stop_reason`, `model`
- [ ] Lazy import — method works when SDK is present, raises clear error when absent
- [ ] `pytest tests/clients/test_aimessage_factory_claude_agent.py -v` passes

---

## Test Specification

```python
# tests/clients/test_aimessage_factory_claude_agent.py
import pytest
from unittest.mock import MagicMock


class TestAIMessageFactoryFromClaudeAgent:
    def test_basic_text_assembly(self):
        """Text from multiple AssistantMessage/TextBlocks concatenated."""
        from parrot.models.responses import AIMessageFactory
        # Mock claude_agent_sdk.types objects
        # Verify output == "hello world"

    def test_tool_use_mapped_to_tool_call(self):
        """ToolUseBlock produces a ToolCall in AIMessage.tool_calls."""
        from parrot.models.responses import AIMessageFactory
        # Verify ToolCall.id, name, arguments

    def test_result_metadata_extracted(self):
        """ResultMessage populates usage and stop_reason."""
        from parrot.models.responses import AIMessageFactory
        # Verify usage.estimated_cost, stop_reason, num_turns in extra_usage

    def test_empty_message_list(self):
        """Empty messages list produces empty-output AIMessage."""
        from parrot.models.responses import AIMessageFactory
        # Verify graceful handling

    def test_provider_is_claude_agent(self):
        """Provider field is 'claude-agent', not 'claude'."""
        from parrot.models.responses import AIMessageFactory
        # Verify provider == "claude-agent"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none (pure conversion)
3. **Verify the Codebase Contract** — confirm `AIMessageFactory` and `CompletionUsage` signatures
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** `from_claude_agent` and `CompletionUsage.from_claude_agent`
6. **Write and run tests**: `pytest tests/clients/test_aimessage_factory_claude_agent.py -v`
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-857-aimessage-factory-from-claude-agent.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
