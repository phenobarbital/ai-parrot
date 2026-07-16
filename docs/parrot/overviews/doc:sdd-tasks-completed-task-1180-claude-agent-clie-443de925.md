---
type: Wiki Overview
title: 'TASK-1180: ClaudeAgentClient `ask_stream` — Yield Final AIMessage'
id: doc:sdd-tasks-completed-task-1180-claude-agent-client-askstream-aimessage-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: ClaudeAgentClient wraps the Claude Agent SDK. Its `ask_stream` iterates over
relates_to:
- concept: mod:parrot.models
  rel: mentions
---

# TASK-1180: ClaudeAgentClient `ask_stream` — Yield Final AIMessage

**Feature**: FEAT-174 — Homologate `ask_stream` Across All LLM Clients
**Spec**: `sdd/specs/homologate-llm-clients-askstream.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1173
**Assigned-to**: unassigned

---

## Context

ClaudeAgentClient wraps the Claude Agent SDK. Its `ask_stream` iterates over
`AssistantMessage` objects and yields `TextBlock.text` strings. It does not
yield a final AIMessage. The non-streaming `ask()` method uses
`AIMessageFactory.from_claude_agent()` — the same factory should be used here.

Implements: Spec §3 Module 8.

---

## Scope

- Update `ask_stream` return type from `AsyncIterator[str]` to
  `AsyncIterator[Union[str, AIMessage]]`.
- Accumulate messages and text during streaming.
- After the streaming loop, build and yield `AIMessage` using
  `AIMessageFactory.from_claude_agent()`.

**NOT in scope**: Modifying `ask()` or `resume()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/claude_agent.py` | MODIFY | Add AIMessage yield at end of ask_stream |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models import AIMessage, AIMessageFactory  # verified: parrot/models/__init__.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/claude_agent.py:526-592
async def ask_stream(self, prompt, ...) -> AsyncIterator[str]:  # line 542 — CHANGE

# Streaming loop (lines 581-592):
async for msg in query(prompt=prompt, options=options):
    if isinstance(msg, AssistantMessage) or type(msg).__name__ == "AssistantMessage":
        for block in getattr(msg, "content", []) or []:
            if isinstance(block, TextBlock) or type(block).__name__ == "TextBlock":
                text = getattr(block, "text", "") or ""
                if text:
                    yield text

# packages/ai-parrot/src/parrot/models/responses.py:623
@staticmethod
def from_claude_agent(
    messages: List[Any],
    input_text: str,
    model: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    structured_output: Any = None
) -> AIMessage:

# packages/ai-parrot/src/parrot/models/basic.py:112
@classmethod
def from_claude_agent(cls, ...) -> "CompletionUsage":
```

### Does NOT Exist
- ~~`AIMessageFactory.from_claude_sdk()`~~ — use `from_claude_agent()`
- ~~`query.get_final_message()`~~ — the Agent SDK has no such method

---

## Implementation Notes

Collect all messages during iteration, then build AIMessage:

```python
async def ask_stream(self, ...) -> AsyncIterator[Union[str, AIMessage]]:
    ...
    all_messages = []
    async for msg in query(prompt=prompt, options=options):
        all_messages.append(msg)
        if isinstance(msg, AssistantMessage) or type(msg).__name__ == "AssistantMessage":
            for block in getattr(msg, "content", []) or []:
                if isinstance(block, TextBlock) or type(block).__name__ == "TextBlock":
                    text = getattr(block, "text", "") or ""
                    if text:
                        yield text

    # Build final AIMessage
    turn_id = str(uuid.uuid4())
    ai_message = AIMessageFactory.from_claude_agent(
        messages=all_messages,
        input_text=prompt,
        model=resolved_model,
        session_id=session_id,
        turn_id=turn_id,
    )
    yield ai_message
```

### Key Constraints
- `session_id` is passed as parameter. `resolved_model` is set at line 568.
- `uuid` is already imported in the file (used in `resume()`).
- The `del` statement at line 564 deletes unused params — do NOT use them.

---

## Acceptance Criteria

- [ ] `ClaudeAgentClient.ask_stream` return type is `AsyncIterator[Union[str, AIMessage]]`
- [ ] Final `AIMessage` is yielded with `provider="claude-agent"`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/claude_agent.py`

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_claude_agent_ask_stream_yields_aimessage():
    chunks, ai_msg = [], None
    async for chunk in client.ask_stream("test"):
        if isinstance(chunk, AIMessage):
            ai_msg = chunk
        else:
            chunks.append(chunk)
    assert ai_msg is not None
    assert ai_msg.provider == "claude-agent"
```

---

## Completion Note

Implemented 2026-05-15. Changed return type to `AsyncIterator[Union[str, AIMessage]]`.
Saved `user_id` as `saved_user_id` before the `del` statement. Accumulated all messages
in `all_messages` list during the `async for msg in query(...)` loop. Generated `turn_id`
with `uuid.uuid4()` before the loop. After the loop, yields
`AIMessageFactory.from_claude_agent(messages=all_messages, ...)`. Also removed pre-existing
unused import `asyncio`. Lint passes clean.
