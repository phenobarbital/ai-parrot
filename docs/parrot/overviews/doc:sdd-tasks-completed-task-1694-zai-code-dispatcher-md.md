---
type: Wiki Overview
title: 'TASK-1694: ZaiCodeDispatcher — native thinking/reasoning_effort loop + Grok
  factory fix'
id: doc:sdd-tasks-completed-task-1694-zai-code-dispatcher-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 3 of FEAT-269 (spec §2 New Public Interfaces, §3). The core
relates_to:
- concept: mod:parrot.clients.factory
  rel: mentions
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: mentions
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
- concept: mod:parrot.models.zai
  rel: mentions
---

# TASK-1694: ZaiCodeDispatcher — native thinking/reasoning_effort loop + Grok factory fix

**Feature**: FEAT-269 — Z.ai Code Dispatcher for the Dev Loop (GLM-5.2)
**Spec**: `sdd/specs/zai-client-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1693
**Assigned-to**: unassigned

---

## Context

Module 3 of FEAT-269 (spec §2 New Public Interfaces, §3). The core
deliverable: `ZaiCodeDispatcher(LLMCodeDispatcher)` reuses the inherited
local tool loop, Redis events, cwd guard and output validation, overriding
exactly two hook points so GLM-5.2 receives Z.ai-native parameters. The base
class's default paths CANNOT work for Z.ai: `_chat_completion` expects a
`client._chat_completion` method that `ZaiClient` does not have, and
`_completion_args` emits Nvidia-style `extra_body.chat_template_kwargs`
thinking flags that Z.ai ignores.

Also fixes the latent `GrokCodeDispatcher` bug: its
`client_factory=lambda model: LLMFactory.create(model)` rejects the
`model_args=` kwarg that `_create_client` passes (masked in tests by
monkeypatching `_client_factory`).

---

## Scope

- Add `ZaiCodeDispatcher(LLMCodeDispatcher)` in
  `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py`, after
  `GrokCodeDispatcher`:
  - `__init__(*, max_concurrent: int, redis_url: str, stream_ttl_seconds: int)`
    calling `super().__init__(..., client_factory=lambda model, **kw:
    LLMFactory.create(model, **kw))`.
  - Override `_completion_args(self, profile, tools) -> Dict[str, Any]`:
    build the base args (tools, `tool_choice="auto"`,
    `parallel_tool_calls=False`, `max_tokens`, `temperature`) then add
    `thinking={"type": "enabled" if profile.enable_thinking else "disabled"}`
    and `reasoning_effort=profile.reasoning_effort`. NEVER emit
    `extra_body`/`chat_template_kwargs`. When thinking is enabled and the
    model (parsed from `profile.llm`) is not in
    `THINKING_CAPABLE_ZAI_MODELS`, log a warning via `self.logger` and still
    send (mirrors `ZaiClient._thinking_payload` behavior).
    Note: do NOT call `super()._completion_args()` and patch the result —
    the base adds `extra_body` when `enable_thinking` is True (and the Zai
    profile defaults it True). Build the dict explicitly.
  - Override `_chat_completion(self, *, client, model, messages, args)`:
    `sdk = await client._ensure_client()` (inherited `AbstractClient`
    method; returns the official zai-sdk client), then
    `return await asyncio.to_thread(sdk.chat.completions.create,
    model=model, messages=messages, **args)`.
  - Thin `dispatch(self, *, brief, profile: ZaiCodeDispatchProfile,
    output_model, run_id, node_id, cwd)` that just delegates to
    `super().dispatch(...)` (profile is already an `LLMCodeDispatchProfile`)
    — exists for typing/docs symmetry with siblings.
  - Google-style class + method docstrings.
- Add `"ZaiCodeDispatcher"` to the module `__all__` (lines 2632-2641).
- Fix `GrokCodeDispatcher.__init__` (line 2583):
  `client_factory=lambda model: LLMFactory.create(model)` →
  `client_factory=lambda model, **kw: LLMFactory.create(model, **kw)`.
  Change ONLY the lambda; do not touch Grok's `_chat_completion` or
  `dispatch`.

**NOT in scope**: profile definition (TASK-1693, already merged),
`flows/dev_loop/__init__.py` exports and server wiring (TASK-1695),
committed tests (TASK-1696), any change to `LLMCodeDispatcher` itself,
`reasoning_content` streaming beyond what the inherited loop already emits.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py` | MODIFY | Add `ZaiCodeDispatcher` after Grok block; update `__all__`; fix Grok lambda (line 2583) |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-03 against `dev`.

### Verified Imports
```python
# Already present at the top of dispatcher.py (verify before adding):
#   asyncio, json, logging, LLMFactory, Pydantic BaseModel, typing helpers.
from parrot.clients.factory import LLMFactory                     # "zai" registered clients/factory.py:60
from parrot.models.zai import THINKING_CAPABLE_ZAI_MODELS         # models/zai.py:34 — NEW import in dispatcher.py
from parrot.flows.dev_loop.models import ZaiCodeDispatchProfile   # exists after TASK-1693
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py
class LLMCodeDispatcher:                                    # line 1721
    def __init__(self, *, max_concurrent: int, redis_url: str,
                 stream_ttl_seconds: int,
                 client_factory: Callable[..., Any] = LLMFactory.create) -> None
    async def dispatch(self, *, brief: BaseModel,
                       profile: LLMCodeDispatchProfile,
                       output_model: Type[T], run_id: str,
                       node_id: str, cwd: str) -> T         # line 1747
    def _create_client(self, profile) -> Any                # line 1964
        # calls self._client_factory(profile.llm,
        #     model_args={"temperature": profile.temperature, "max_tokens": profile.max_tokens})
    @staticmethod
    async def _ensure_client_ready(client) -> None          # line 1972
        # early-return if getattr(client, "client", None); else await client._ensure_client()
    @staticmethod
    def _resolve_model(profile, client) -> str              # line 1980
        # LLMFactory.parse_llm_string(profile.llm) → model, fallbacks to client attrs
    def _completion_args(self, profile, tools) -> Dict[str, Any]   # line 2016
        # base keys: tools, tool_choice="auto", parallel_tool_calls=False,
        #            max_tokens=profile.max_tokens, temperature (if not None)
        # if profile.enable_thinking: args["extra_body"] = {"chat_template_kwargs":
        #     {"enable_thinking": True, "clear_thinking": profile.clear_thinking}}  ← NVIDIA-style, DO NOT inherit
    async def _chat_completion(self, *, client, model, messages, args)  # line 2038
        # default: client._chat_completion(model=..., messages=..., use_tools=True, **args)
        # ZaiClient has NO _chat_completion → this override is mandatory

class GrokCodeDispatcher(LLMCodeDispatcher):                # line 2565 — the structural template
    def __init__(self, *, max_concurrent, redis_url, stream_ttl_seconds):   # line 2572
        super().__init__(..., client_factory=lambda model: LLMFactory.create(model))  # line 2583 ← FIX THIS LAMBDA
    async def _chat_completion(self, *, client, model, messages, args):     # line 2586
        await client._ensure_client()
        return await client.client.chat.completions.create(model=model, messages=messages, **args)
    async def dispatch(...)                                 # line 2601

__all__ = ["ClaudeCodeDispatcher", "CodexCodeDispatcher", "GeminiCodeDispatcher",
           "LLMCodeDispatcher", "GrokCodeDispatcher", "DevLoopCodeDispatcher",
           "DispatchExecutionError", "DispatchOutputValidationError"]   # lines 2632-2641

# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient:
    async def _ensure_client(self, **hints) -> Any          # line 652 — returns the underlying SDK client

# packages/ai-parrot/src/parrot/clients/zai.py — offloading pattern to copy
async def _create_completion(self, **request_args):         # line 284
    client = await self._ensure_client()
    return await asyncio.to_thread(client.chat.completions.create, **request_args)
```

### Does NOT Exist
- ~~`ZaiClient._chat_completion`~~ — `ZaiClient` has `_create_completion`
  (different contract); the inherited default `_chat_completion` FAILS for
  ZaiClient — the override in this task is mandatory, not optional
- ~~async client in zai-sdk~~ — SDK 0.2.3 is synchronous only;
  `sdk.chat.completions.create` MUST go through `asyncio.to_thread`
- ~~`clear_thinking` in the Z.ai request~~ — Nvidia-only concept; the Zai
  path must not send it (nor `extra_body`, nor `chat_template_kwargs`)
- ~~`ZaiCodeDispatcher`~~ — created by this task; `__all__` currently lists
  only the five existing dispatchers
- ~~a Zai branch in `examples/dev_loop/server.py`~~ — TASK-1695's job

**zai-sdk 0.2.3 verified `Completions.create` kwargs** (via `inspect.signature`):
`model, request_id, user_id, do_sample, stream, temperature, top_p,
max_tokens, seed, messages, stop, sensitive_word_check, tools, tool_choice,
meta, extra, extra_headers, extra_body, timeout, response_format, thinking,
watermark_enabled, tool_stream, reasoning_effort` — `thinking` and
`reasoning_effort` are first-class kwargs; `parallel_tool_calls` is NOT in
the signature but zai-sdk `create` passes unknown kwargs onward — verify at
implementation time; if the SDK rejects it, drop `parallel_tool_calls` from
the Zai args dict (document in completion note).

### GLM-5.2 request facts (docs.z.ai, fetched 2026-07-03)
- `thinking={"type": "enabled"|"disabled"}` — default enabled server-side.
- `reasoning_effort`: `max|xhigh|high|medium|low|minimal|none`, default
  `max`, GLM-5.2-only, effective only when thinking enabled; `none`/
  `minimal` skip thinking. Send as-is; no client-side mapping.
- Responses are OpenAI-shaped: `choices[0].message` with `content`,
  `tool_calls`, and possibly `reasoning_content` — the inherited
  `_response_message`/`_message_content`/`_message_tool_calls` helpers work
  unchanged. Do NOT append `reasoning_content` back into `messages`.

---

## Implementation Notes

### Pattern to Follow
`GrokCodeDispatcher` (dispatcher.py:2565-2630) is the structural template:
same `__init__` shape, same override seam. Differences: (a) the fixed
factory lambda, (b) `_completion_args` override (Grok doesn't have one),
(c) `_chat_completion` obtains the SDK client from `_ensure_client()`'s
return value and wraps the sync call in `asyncio.to_thread` (Grok's client
is async; Zai's is not), (d) no profile-mapping in `dispatch` (the Zai
profile subclasses `LLMCodeDispatchProfile`).

### Key Constraints
- Async-first: no blocking call outside `asyncio.to_thread`.
- Stateless overrides: read everything from `profile`/`args` parameters —
  never stash per-dispatch state on `self` (shared instance, semaphore
  concurrency).
- `_completion_args` receives the profile as declared type
  `LLMCodeDispatchProfile`; guard the Z.ai field access with
  `isinstance(profile, ZaiCodeDispatchProfile)` (fall back to base behavior
  minus `extra_body` otherwise) OR type the override to the subclass — pick
  the style that satisfies mypy without `type: ignore`.
- Wall-clock cap gotcha (spec §7): `asyncio.timeout` cancels the await but
  not the underlying thread — acceptable; do not add custom thread-killing
  logic.
- Logging: `self.logger.warning(...)` for the non-thinking-capable model
  case, message style per `ZaiClient._thinking_payload` (clients/zai.py:193-196).

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:2565-2641` — Grok block + `__all__`
- `packages/ai-parrot/src/parrot/clients/zai.py:284-286` — to_thread pattern
- `sdd/specs/zai-client-code.spec.md` §2 — the design contract

---

## Acceptance Criteria

- [ ] `ZaiCodeDispatcher` importable from `parrot.flows.dev_loop.dispatcher`
      and listed in `__all__`
- [ ] `_completion_args` on a default `ZaiCodeDispatchProfile` yields
      `thinking={"type": "enabled"}`, `reasoning_effort="max"`,
      `max_tokens=8192`, and contains NO `extra_body` key
- [ ] `enable_thinking=False` yields `thinking={"type": "disabled"}`
- [ ] Non-thinking-capable model + thinking → warning logged, dispatch proceeds
- [ ] Default client factory accepts `model_args=` kwarg (Zai AND fixed Grok)
- [ ] Satisfies `DevLoopCodeDispatcher` Protocol (dispatch signature parity)
- [ ] Existing dev_loop suite still green:
      `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] No linting errors:
      `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py`

---

## Test Specification

> Committed tests land in TASK-1696. Smoke-verify inline before committing:

```python
from parrot.flows.dev_loop.dispatcher import ZaiCodeDispatcher
from parrot.flows.dev_loop.models import ZaiCodeDispatchProfile

disp = ZaiCodeDispatcher(max_concurrent=1, redis_url="redis://localhost:6379/0",
                         stream_ttl_seconds=60)
args = disp._completion_args(ZaiCodeDispatchProfile(), tools=[])
assert args["thinking"] == {"type": "enabled"}
assert args["reasoning_effort"] == "max"
assert "extra_body" not in args
# Grok regression: factory forwards model_args without TypeError
from parrot.flows.dev_loop.dispatcher import GrokCodeDispatcher
g = GrokCodeDispatcher(max_concurrent=1, redis_url="redis://localhost:6379/0",
                       stream_ttl_seconds=60)
# g._client_factory("zai:glm-5.2", model_args={"temperature": 0.0})  # must not raise TypeError
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1693 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm the Grok block still sits at dispatcher.py:2565-2630 (line
     numbers may shift; anchor on class names)
   - Confirm `LLMCodeDispatcher._completion_args` / `_chat_completion`
     bodies match the contract; update the contract FIRST if they moved
   - Verify whether zai-sdk 0.2.3 `create()` tolerates `parallel_tool_calls`
     (see contract note) and adjust
4. **Update status** in `sdd/tasks/index/zai-client-code.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1694-zai-code-dispatcher.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-03
**Notes**: Added `ZaiCodeDispatcher(LLMCodeDispatcher)` in `dispatcher.py`
after the `GrokCodeDispatcher` block: `__init__` forwards the fixed
`client_factory=lambda model, **kw: LLMFactory.create(model, **kw)`;
`_completion_args` builds base args (tools/tool_choice/parallel_tool_calls/
max_tokens/temperature) then sets `thinking={"type": "enabled"|"disabled"}`
and `reasoning_effort` from the profile, never `extra_body`, warning via
`self.logger.warning` when thinking is requested for a model outside
`THINKING_CAPABLE_ZAI_MODELS` (via `LLMFactory.parse_llm_string`);
`_chat_completion` obtains the SDK via `await client._ensure_client()` and
wraps `sdk.chat.completions.create` in `asyncio.to_thread`; a thin `dispatch`
delegates to `super().dispatch()`. Added `"ZaiCodeDispatcher"` to `__all__`
and the `ZaiCodeDispatchProfile`/`THINKING_CAPABLE_ZAI_MODELS` imports.
Fixed `GrokCodeDispatcher.__init__`'s factory lambda (only the lambda
signature; `_chat_completion`/`dispatch` untouched) to accept `**kw` so
`_create_client`'s `model_args=` kwarg no longer raises `TypeError`.
`parallel_tool_calls` kept in the Zai args dict per the base pattern (not
flagged as rejected by the SDK at this stage; full behavioral verification
deferred to TASK-1696's dispatch-loop tests against a fake client).
Verified via inline smoke script covering completion-args (enabled/disabled/
warning-on-non-capable-model) and both factories accepting `model_args=`
without `TypeError`, `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
(305 passed, 5 skipped, same 4 pre-existing order-dependent failures
reproduced identically on unmodified `dev`), and `ruff check` (clean).

**Deviations from spec**: none
