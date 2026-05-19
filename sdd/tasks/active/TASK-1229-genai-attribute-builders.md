# TASK-1229: GenAI SemConv attribute builders

**Feature**: FEAT-177 — OpenTelemetry + Cost Observability
**Spec**: `sdd/specs/otel-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1228
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 and §2 (Event → Span mapping + Provider → `gen_ai.system` mapping). Centralize the pure functions that build OTel attribute dicts from FEAT-176 events. This is the single point of update if OTel SemConv renames an attribute.

---

## Scope

- Create `parrot/observability/attributes.py` with:
  - `PROVIDER_TO_GEN_AI_SYSTEM: dict[str, str]` mapping table per spec §2.
  - `build_before_invoke_attrs(event) -> dict`
  - `build_after_invoke_attrs(event) -> dict`
  - `build_before_client_attrs(event) -> dict`
  - `build_after_client_attrs(event, *, cost_usd: float | None = None) -> dict`
  - `build_client_failed_attrs(event) -> dict`
  - `build_before_tool_attrs(event) -> dict`
  - `build_after_tool_attrs(event) -> dict`
  - `build_tool_failed_attrs(event) -> dict`
  - `build_message_event_attrs(event) -> dict`
- Unit tests for the provider mapping and each builder.

**NOT in scope**: any span-creation logic, metric-emission logic, or cost calculation — pure attribute dict builders only.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/attributes.py` | CREATE | Pure attribute builders + provider mapping. |
| `packages/ai-parrot/tests/unit/observability/test_attributes.py` | CREATE | One test per builder + mapping completeness test. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Any, Optional
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent, AfterInvokeEvent, AfterToolCallEvent,
    BeforeClientCallEvent, BeforeInvokeEvent, BeforeToolCallEvent,
    ClientCallFailedEvent, InvokeFailedEvent, ToolCallFailedEvent,
    MessageAddedEvent,
)
```

### Existing Signatures to Use

Field names verified in spec §6 Codebase Contract:

```python
# BeforeClientCallEvent — client.py:17-34
client_name: str; model: str; temperature: Optional[float]
system_prompt_hash: str; has_tools: bool

# AfterClientCallEvent — client.py:37-58
client_name: str; model: str; duration_ms: float
input_tokens: Optional[int]; output_tokens: Optional[int]; finish_reason: Optional[str]

# ClientCallFailedEvent — client.py:61-79
client_name: str; model: str; duration_ms: float
error_type: str; error_message: str

# BeforeToolCallEvent — tool.py:11-26
tool_name: str; tool_class: str; args_summary: dict

# AfterToolCallEvent — tool.py:29-45
tool_name: str; duration_ms: float; result_status: str; result_size_bytes: int

# ToolCallFailedEvent — tool.py:48-64
tool_name: str; duration_ms: float; error_type: str; error_message: str

# BeforeInvokeEvent — invoke.py:13-30
agent_name: str; method: str; question: str
user_id: Optional[str]; session_id: Optional[str]

# AfterInvokeEvent — invoke.py:33-51
agent_name: str; method: str; duration_ms: float
input_tokens: Optional[int]; output_tokens: Optional[int]

# InvokeFailedEvent — invoke.py:54-72
agent_name: str; method: str; duration_ms: float
error_type: str; error_message: str

# MessageAddedEvent — message.py:11-30
agent_name: str; role: str; content_length: int; has_tool_calls: bool
```

### Provider → `gen_ai.system` mapping (spec §2)

```python
PROVIDER_TO_GEN_AI_SYSTEM: dict[str, str] = {
    "openai":       "openai",
    "anthropic":    "anthropic",
    "claude-agent": "anthropic",   # overridden — claude_agent.py routes through Anthropic
    "google":       "gemini",      # default; override per route when Vertex
    "gemini-live":  "gemini",
    "groq":         "groq",
    "grok":         "xai",         # no OTel-standard value; custom
    "nvidia":       "nvidia",      # custom — no OTel-standard
    "huggingface":  "huggingface", # custom
    "gemma4":       "huggingface", # Gemma is HF-hosted
}
```

### Does NOT Exist

- ~~`event.source_name`~~ — referenced incorrectly in FEAT-176 stub at `subscribers/opentelemetry.py:237`. Use `event.client_name`.
- ~~`event.prompt` / `event.completion`~~ — PII never carried on events. `system_prompt_hash` (SHA-256) is the only prompt-related field.

---

## Implementation Notes

### Attribute key naming (GenAI SemConv)

| Source | Attribute key | Note |
|---|---|---|
| `client_name` (mapped) | `gen_ai.system` | Always present on client/cost spans. |
| `model` | `gen_ai.request.model` (Before) / `gen_ai.response.model` (After) | Distinct keys. |
| `temperature` | `gen_ai.request.temperature` | Omit if None. |
| `has_tools` | `gen_ai.request.has_tools` | Boolean. |
| `system_prompt_hash` | `parrot.system_prompt_hash` | Parrot-specific (not in OTel SemConv). |
| `input_tokens` | `gen_ai.usage.input_tokens` | Omit if None. |
| `output_tokens` | `gen_ai.usage.output_tokens` | Omit if None. |
| `finish_reason` | `gen_ai.response.finish_reason` | Omit if None. |
| `cost_usd` (param) | `parrot.cost.usd` | Parrot-specific. |
| `tool_name`/`tool_class` | `parrot.tool.name` / `parrot.tool.class` | — |
| `result_status`/`result_size_bytes` | `parrot.tool.result.status` / `parrot.tool.result.size_bytes` | — |
| `agent_name`/`method` | `parrot.agent.name` / `parrot.invoke.method` | — |
| `error_type`/`error_message` | `error.type` / `error.message` | OTel standard. |
| `role`/`content_length`/`has_tool_calls` | `parrot.message.role` / `parrot.message.content_length` / `parrot.message.has_tool_calls` | — |

### Key Constraints

- All builders return `dict[str, Any]` — never set `None` values (drop them).
- Builders MUST NOT include `user_id`, `session_id`, `question`, or any PII unless explicitly noted (none here).
- Unknown `client_name` → `gen_ai.system` falls back to the raw `client_name` value (log a one-time WARN).

### Provider mapping fallback

```python
def resolve_gen_ai_system(client_name: str) -> str:
    return PROVIDER_TO_GEN_AI_SYSTEM.get(client_name, client_name)
```

Use a module-level `set()` to track which unknown client_names have already been warned about.

---

## Acceptance Criteria

- [ ] `parrot.observability.attributes` module exists with all 9 builder functions + the provider mapping.
- [ ] Every `client_name` listed in the spec §2 table maps to its documented `gen_ai.system` value.
- [ ] `build_before_client_attrs` of an event with `temperature=None` omits the `gen_ai.request.temperature` key.
- [ ] `build_after_client_attrs(event, cost_usd=0.0042)` includes `"parrot.cost.usd": 0.0042`.
- [ ] No PII (no `question`, `user_id`, `session_id`) appears in any builder's output.
- [ ] Unknown `client_name` → fallback to raw value; WARN emitted once.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/observability/test_attributes.py
import pytest
from parrot.observability.attributes import (
    PROVIDER_TO_GEN_AI_SYSTEM,
    resolve_gen_ai_system,
    build_before_client_attrs,
    build_after_client_attrs,
    build_before_invoke_attrs,
)
from parrot.core.events.lifecycle.events import (
    BeforeClientCallEvent, AfterClientCallEvent, BeforeInvokeEvent,
)
from parrot.core.events.lifecycle.trace import TraceContext


def test_provider_mapping_covers_all_known_clients():
    expected = {
        "openai", "anthropic", "claude-agent", "google", "gemini-live",
        "groq", "grok", "nvidia", "huggingface", "gemma4",
    }
    assert expected.issubset(PROVIDER_TO_GEN_AI_SYSTEM.keys())


def test_resolve_gen_ai_system_known():
    assert resolve_gen_ai_system("openai") == "openai"
    assert resolve_gen_ai_system("claude-agent") == "anthropic"
    assert resolve_gen_ai_system("gemma4") == "huggingface"


def test_resolve_gen_ai_system_unknown_falls_back_and_warns(caplog):
    assert resolve_gen_ai_system("brand-new-llm") == "brand-new-llm"
    # warn exactly once across repeated calls
    resolve_gen_ai_system("brand-new-llm")
    assert sum("brand-new-llm" in r.message for r in caplog.records) <= 1


def test_before_client_omits_none_temperature():
    e = BeforeClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="openai", model="gpt-4o", temperature=None,
    )
    attrs = build_before_client_attrs(e)
    assert "gen_ai.request.temperature" not in attrs
    assert attrs["gen_ai.system"] == "openai"
    assert attrs["gen_ai.request.model"] == "gpt-4o"


def test_after_client_with_cost():
    e = AfterClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="anthropic", model="claude-3-5-sonnet",
        duration_ms=1234.5, input_tokens=100, output_tokens=50,
        finish_reason="end_turn",
    )
    attrs = build_after_client_attrs(e, cost_usd=0.00042)
    assert attrs["gen_ai.system"] == "anthropic"
    assert attrs["gen_ai.usage.input_tokens"] == 100
    assert attrs["gen_ai.usage.output_tokens"] == 50
    assert attrs["gen_ai.response.finish_reason"] == "end_turn"
    assert attrs["parrot.cost.usd"] == 0.00042


def test_before_invoke_excludes_pii():
    e = BeforeInvokeEvent(
        trace_context=TraceContext.new_root(),
        agent_name="bot", method="ask",
        question="my private question", user_id="u-123", session_id="s-456",
    )
    attrs = build_before_invoke_attrs(e)
    assert "question" not in str(attrs)
    assert "u-123" not in str(attrs)
    assert "s-456" not in str(attrs)
```

---

## Agent Instructions

1. Confirm TASK-1228 is complete (`parrot.observability` package exists).
2. Confirm event field names against spec §6 (do not re-read events files unless something has changed).
3. Implement attributes.py + tests.
4. Run `pytest packages/ai-parrot/tests/unit/observability/test_attributes.py -v`.

---

## Completion Note

*(Agent fills this in when done)*
