# TASK-2086: NovaCodeDispatcher — dev seat over the bedrock-mantle endpoint

**Feature**: FEAT-405 — Nova (AWS Bedrock) Dispatcher & Per-Agent Usage Report
**Spec**: `sdd/specs/novaclient-dev-loop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2084, TASK-2085
**Assigned-to**: unassigned

---

## Context

Implements **Module 3a** of the spec — the development seat. This is the only
Nova seat that needs a tool loop, and the reason the whole transport-split design
works: AWS serves MiniMax M2.5 over the **OpenAI-compatible `bedrock-mantle`
endpoint** (`https://bedrock-mantle.{region}.api.aws/v1`), which is exactly the
shape `LLMCodeDispatcher`'s loop already speaks. So this dispatcher reuses the
inherited loop — cwd-safety guard, Redis event streaming, output validation,
`SessionHost` shim — and overrides only the two completion hooks.

**Do not** attempt to drive this seat through `NovaClient`/Converse.
`BedrockConverseBase` exposes no OpenAI-shaped `_chat_completion`, so
`LLMCodeDispatcher._chat_completion` (`llm.py:369`) would raise
`DispatchExecutionError("… does not expose chat completion")` against it.

---

## Scope

- Create `dev_loop/dispatchers/nova.py` with `NovaCodeDispatcher(LLMCodeDispatcher)`.
- Override `_completion_args` to build MiniMax-appropriate args and apply the
  per-model clamp from TASK-2085.
- Override `_chat_completion` to route through an OpenAI-compatible client bound
  to the `bedrock-mantle` base URL for the configured region.
- Resolve the base URL and credentials from config
  (`DEV_LOOP_NOVA_MANTLE_BASE_URL` / region + Bedrock API key), with clear errors
  when unset.
- Override `dispatch()` only to narrow the profile type, mirroring
  `MoonshotCodeDispatcher.dispatch` (`dispatchers/moonshot.py:109`).
- Export `NovaCodeDispatcher` from `dispatchers/__init__.py`.
- Write unit tests against a mocked mantle client.

**NOT in scope**: the adversarial reviewer (TASK-2087); `DevAgentBackend` /
`build_dispatcher` / catalog wiring (TASK-2088); round-event emission
(TASK-2089 modifies the shared `llm.py` loop, not this subclass); any change to
`BedrockConverseBase` or `NovaClient`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/nova.py` | CREATE | `NovaCodeDispatcher` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/__init__.py` | MODIFY | Export `NovaCodeDispatcher` |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `DEV_LOOP_NOVA_*` config keys (base URL, region, code model) |
| `packages/ai-parrot/tests/flows/dev_loop/test_nova_dispatcher.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.clients.factory import LLMFactory                 # clients/factory.py; "nova" at line 96
from parrot.flows.dev_loop.dispatchers._shared import DispatchExecutionError, T
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
from parrot.flows.dev_loop.models import NovaCodeDispatchProfile   # added by TASK-2084
from parrot.flows.dev_loop.session_state import SessionHost
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
class LLMCodeDispatcher:                                              # line 39
    async def dispatch(self, *, brief, profile, output_model, run_id,
                       node_id, cwd, session_host=None): ...          # line 65
    async def _dispatch_loop(self, *, brief, profile, output_model,
                             run_id, node_id, stream_key, cwd): ...   # line 172
        # line 190: for turn_index in range(profile.max_turns):
    def _completion_args(self, profile, tools) -> Dict[str, Any]: ... # line 347
        # base returns: tools, tool_choice="auto", parallel_tool_calls=False,
        #               max_tokens, optional temperature, optional extra_body
    async def _chat_completion(self, *, client, model, messages,
                               args) -> Any: ...                      # line 369
        # base: method = getattr(client, "_chat_completion", None)
        #       raises DispatchExecutionError if not callable
        #       returns await method(model=..., messages=..., use_tools=True, **args)

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/moonshot.py — THE SHAPE TO COPY
class MoonshotCodeDispatcher(LLMCodeDispatcher):                      # line 18
    def __init__(self, *, max_concurrent: int, redis_url: str,
                 stream_ttl_seconds: int) -> None:                    # line 33
        super().__init__(
            max_concurrent=max_concurrent, redis_url=redis_url,
            stream_ttl_seconds=stream_ttl_seconds,
            client_factory=lambda model, **kw: LLMFactory.create(model, **kw),  # line 44
        )
    def _completion_args(self, profile, tools) -> Dict[str, Any]: ... # line 47
    async def _chat_completion(self, *, client, model, messages, args): ...  # line 82
    async def dispatch(self, *, brief, profile, output_model, run_id,
                       node_id, cwd, session_host=None) -> T: ...     # line 109

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py
T = TypeVar("T", bound=BaseModel)                                     # line 21
class DispatchExecutionError(Exception): ...                          # line 82

# packages/ai-parrot/src/parrot/clients/zai.py — configurable base_url PRECEDENT
base_url: str = "https://api.z.ai/api/paas/v4/",                      # line 35
self.base_url = base_url or config.get("ZAI_BASE_URL") or "https://..." # line 45
```

### Verified AWS Facts

```text
bedrock-mantle (OpenAI-compatible):  https://bedrock-mantle.{region}.api.aws/v1
  auth: Bedrock API key as the bearer token (OPENAI_API_KEY-style)
  MiniMax M2.5  minimax.minimax-m2.5   Chat Completions ✅  no prefix  max output  8K
  Kimi K2.5     moonshotai.kimi-k2.5   Chat Completions ✅  no prefix  max output 16K
  GLM-5         zai.glm-5              Chat Completions ✅  no prefix  max output 128K
  Anthropic models: Chat Completions ❌ — served at /anthropic/v1/messages instead
```

### Does NOT Exist

- ~~`parrot.flows.dev_loop.dispatchers.nova`~~ / ~~`NovaCodeDispatcher`~~ — this task creates them
- ~~`BedrockConverseBase._chat_completion(...)`~~ — **does not exist**. `NovaClient` exposes `ask()`/`ask_stream()`/`invoke()`/`resume()` in Converse shape only. Driving the dev seat through `NovaClient` WILL raise `DispatchExecutionError`
- ~~Chat Completions for Anthropic models on Bedrock~~ — not supported; a Claude dev seat must use the existing `claude-code` backend
- ~~`NovaClient(...)` as the dev-seat client~~ — the dev seat uses an OpenAI-compatible client pointed at `bedrock-mantle`, NOT `NovaClient`
- ~~A `nova` branch in `build_dispatcher`~~ — TASK-2088 adds it; `agent_builder.py:210` still raises `ValueError` for unknown backends
- ~~`extra_body.chat_template_kwargs`~~ — an Nvidia-only concept the base `_completion_args` emits (`llm.py:359-365`); MiniMax does not use it, so the override must not emit it

---

## Implementation Notes

### Pattern to Follow

`MoonshotCodeDispatcher` (`dispatchers/moonshot.py:18-129`) is the precedent:
subclass, inject a `client_factory` in `__init__`, override exactly
`_completion_args` and `_chat_completion`, and re-declare `dispatch()` only to
narrow the profile type.

```python
class NovaCodeDispatcher(LLMCodeDispatcher):
    """Local coding-agent loop bound to Bedrock via the bedrock-mantle endpoint.

    Extends ``LLMCodeDispatcher`` to reuse the inherited local tool loop, Redis
    event streaming, cwd-safety guard and output validation, while overriding
    the completion hooks so requests route through an OpenAI-compatible client
    pointed at ``https://bedrock-mantle.{region}.api.aws/v1``.
    """
```

### Key Constraints

- **Never emit `extra_body.chat_template_kwargs`** — Nvidia-only.
- Apply the per-model clamp from TASK-2085 when setting `max_tokens`.
- Resolve the bare model id with `LLMFactory.parse_llm_string(profile.llm)`
  (`moonshot.py:69` precedent) before clamping or sending.
- Fail with a clear `DispatchExecutionError` when the mantle base URL or the
  Bedrock API key is unset — name the missing config key.
- async throughout; `self.logger`, never `print`.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/moonshot.py` — the shape to copy
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/zai.py` — a second example
- `packages/ai-parrot/src/parrot/clients/zai.py:35,45` — configurable `base_url` precedent
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:172-240` — the inherited loop this reuses

---

## Acceptance Criteria

- [ ] `from parrot.flows.dev_loop.dispatchers import NovaCodeDispatcher` works
- [ ] `NovaCodeDispatcher` subclasses `LLMCodeDispatcher` and overrides only
      `_completion_args`, `_chat_completion` and `dispatch`
- [ ] `_completion_args` targets the `bedrock-mantle` base URL and emits **no**
      `extra_body`/`chat_template_kwargs`
- [ ] `max_tokens` is clamped per-model (MiniMax → 8192) via TASK-2085's helper
- [ ] A dispatch against a mocked mantle client completes and validates its
      `output_model`
- [ ] Missing base URL or API key raises `DispatchExecutionError` naming the config key
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_nova_dispatcher.py -v` passes
- [ ] `ruff check` + `mypy` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_nova_dispatcher.py
import pytest
from pydantic import BaseModel
from parrot.flows.dev_loop.dispatchers import NovaCodeDispatcher
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
from parrot.flows.dev_loop.models import NovaCodeDispatchProfile


class _Out(BaseModel):
    summary: str


@pytest.fixture
def dispatcher():
    return NovaCodeDispatcher(max_concurrent=1, redis_url="redis://localhost:6379/0",
                              stream_ttl_seconds=60)


class TestNovaCodeDispatcher:
    def test_subclasses_llm_dispatcher(self, dispatcher):
        assert isinstance(dispatcher, LLMCodeDispatcher)

    def test_completion_args_have_no_nvidia_extra_body(self, dispatcher):
        args = dispatcher._completion_args(NovaCodeDispatchProfile(), tools=[])
        assert "extra_body" not in args

    def test_completion_args_clamp_minimax(self, dispatcher):
        profile = NovaCodeDispatchProfile(model="minimax.minimax-m2.5", max_tokens=32_768)
        args = dispatcher._completion_args(profile, tools=[])
        assert args["max_tokens"] == 8_192

    async def test_chat_completion_rejects_client_without_hook(self, dispatcher):
        from parrot.flows.dev_loop.dispatchers._shared import DispatchExecutionError
        class NoHook: ...
        with pytest.raises(DispatchExecutionError, match="chat completion"):
            await dispatcher._chat_completion(client=NoHook(), model="m",
                                              messages=[], args={})
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 Overview + Component Diagram, Module 3)
2. **Check dependencies** — verify TASK-2084 and TASK-2085 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `LLMCodeDispatcher._completion_args` / `_chat_completion` line numbers and shapes
   - Confirm `MoonshotCodeDispatcher`'s `client_factory` injection still reads as at `moonshot.py:44`
   - **Confirm `BedrockConverseBase` still has no `_chat_completion`** before considering any Converse route
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/novaclient-dev-loop.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2086-nova-code-dispatcher.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
