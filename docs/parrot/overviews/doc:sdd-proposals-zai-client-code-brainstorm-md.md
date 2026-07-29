---
type: Wiki Overview
title: 'Brainstorm: Z.ai Code Dispatcher for the Dev Loop (GLM-5.2)'
id: doc:sdd-proposals-zai-client-code-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The dev-loop flow (`parrot/flows/dev_loop/`) currently supports five code
relates_to:
- concept: mod:parrot.clients.factory
  rel: mentions
- concept: mod:parrot.clients.zai
  rel: mentions
- concept: mod:parrot.flows.dev_loop
  rel: mentions
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: mentions
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
- concept: mod:parrot.models.zai
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Z.ai Code Dispatcher for the Dev Loop (GLM-5.2)

**Date**: 2026-07-03
**Author**: Jesus (jlara@trocglobal.com)
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

The dev-loop flow (`parrot/flows/dev_loop/`) currently supports five code
dispatchers for its DevelopmentNode: `ClaudeCodeDispatcher`,
`CodexCodeDispatcher`, `GeminiCodeDispatcher`, `LLMCodeDispatcher`, and
`GrokCodeDispatcher`. There is no way to run the coding loop on Z.ai's GLM
models even though the framework already ships a full `ZaiClient`
(`parrot.clients.zai`) and Z.ai just released **GLM-5.2** — a 1M-context /
128K-output flagship explicitly trained for long-horizon coding-agent
scenarios (Terminal-Bench 2.1: 81.0 vs 62.0 for GLM-5.1; SWE-bench Pro 62.1).

Developers running the dev loop want to select `zai` as the development
agent (like `grok` or `nvidia` today) and get GLM-5.2's native request
surface — thinking mode (`thinking={"type": "enabled"}`) and
`reasoning_effort` — rather than the generic OpenAI-compatible fallback,
which uses Nvidia-style `extra_body.chat_template_kwargs` thinking flags
that Z.ai does not understand.

**Who is affected**: developers/operators of the dev-loop server
(`examples/dev_loop/server.py`) and any flow embedding
`DevelopmentNode` with a custom dispatcher.

## Constraints & Requirements

- Must add `ZaiCodeDispatcher` + `ZaiCodeDispatchProfile` following the
  existing dispatcher family conventions (constructor kwargs
  `max_concurrent` / `redis_url` / `stream_ttl_seconds`; `dispatch()`
  signature per the `DevLoopCodeDispatcher` Protocol, dispatcher.py:124).
- Must drive the LLM through `ZaiClient` (`parrot.clients.zai`) — never the
  raw SDK directly from the dispatcher (CONTEXT.md rule), while still using
  Z.ai's **native** request parameters (thinking, reasoning_effort).
- Reuse the `LLMCodeDispatcher` local tool loop (read_file, list_files,
  search_files, write_file, run_command with `allowed_commands` whitelist,
  `final_output`) — no duplicated agent loop.
- Turn-level `DispatchEvent` streaming to Redis (same event kinds:
  `dispatch.queued/started/message/tool_use/tool_result/completed/failed/output_invalid`).
- Thinking ON by default for GLM-5.2, tunable via the profile.
- **No SDK upgrade required** — verified: installed `zai-sdk` 0.2.3 is the
  latest on PyPI and its `Completions.create` already accepts `thinking`
  and `reasoning_effort` kwargs. GLM-5.2's docs themselves pin
  `zai-sdk==0.2.3`. (Optionally tighten the pin from `>=0.2.2` to `>=0.2.3`.)
- `glm-5.2` must be added to the `ZaiModel` enum and
  `THINKING_CAPABLE_ZAI_MODELS` (currently tops out at `glm-5.1`).
- Full wiring: dev-loop `__init__` exports, `examples/dev_loop/server.py`
  agent selection (`DEV_LOOP_DEVELOPMENT_AGENT="zai"`), tests mirroring the
  Grok test suite.
- Async-first: `zai-sdk` is synchronous — every SDK call must go through
  `asyncio.to_thread` (the pattern `ZaiClient._create_completion` already uses).
- `ZAI_API_KEY` env var required at runtime (never hardcoded).

---

## Options Explored

### Option A: Grok-style thin mapping wrapper (generic OpenAI-compatible path)

Clone the `GrokCodeDispatcher` pattern verbatim: a standalone
`ZaiCodeDispatchProfile` BaseModel, and `ZaiCodeDispatcher(LLMCodeDispatcher)`
whose `dispatch()` maps the profile onto an `LLMCodeDispatchProfile` with
`llm=f"zai:{profile.model}"` and calls `super().dispatch()`. Only
`_chat_completion` is overridden to call the Z.ai SDK client.

✅ **Pros:**
- Smallest possible diff (~80 lines mirroring dispatcher.py:2565–2630).
- Identical shape to an already-reviewed pattern.

❌ **Cons:**
- No native thinking support: the mapped `LLMCodeDispatchProfile.enable_thinking`
  emits Nvidia-style `extra_body.chat_template_kwargs`, which Z.ai ignores —
  GLM-5.2's headline capability would be lost or mis-sent.
- No `reasoning_effort` plumbing at all.
- Inherits a latent bug: Grok's `client_factory=lambda model:
  LLMFactory.create(model)` (dispatcher.py:2583) cannot accept the
  `model_args=` kwarg that `_create_client` (dispatcher.py:1964) passes —
  it only survives in tests because they monkeypatch `_client_factory`.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `zai-sdk` | Official Z.ai Python SDK | 0.2.3 installed == latest on PyPI |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:2565` — `GrokCodeDispatcher` as the template
- `packages/ai-parrot/src/parrot/clients/factory.py:60` — `"zai"` already registered in `LLMFactory`

---

### Option B: Native-parameter subclass — ZaiCodeDispatcher(LLMCodeDispatcher) with Z.ai request overrides ⭐

Keep the shared tool loop by subclassing `LLMCodeDispatcher`, but make the
Z.ai request surface first-class:

- `ZaiCodeDispatchProfile` **subclasses `LLMCodeDispatchProfile`**, adding
  `model: str = "glm-5.2"` (mapped to `llm="zai:glm-5.2"`),
  `enable_thinking: bool = True` (reinterpreted natively) and
  `reasoning_effort: str` (e.g. `"high"`). Because it IS an
  `LLMCodeDispatchProfile`, it flows through `super().dispatch()` unchanged —
  no per-dispatch state stashed on the shared dispatcher (concurrency-safe).
- `ZaiCodeDispatcher` overrides `_completion_args()` (dispatcher.py:2016) to
  emit `thinking={"type": "enabled"|"disabled"}` + `reasoning_effort`
  instead of the Nvidia `extra_body` block, and `_chat_completion()`
  (dispatcher.py:2038) to call the official SDK client owned by `ZaiClient`
  via `asyncio.to_thread(...)` (same pattern as
  `ZaiClient._create_completion`, clients/zai.py:284–286).
- `_ensure_client_ready` (dispatcher.py:1972) already works: `ZaiClient`
  inherits `_ensure_client()` from `AbstractClient` (base.py:652).
- Registry updates: `ZaiModel.GLM_5_2 = "glm-5.2"` + membership in
  `THINKING_CAPABLE_ZAI_MODELS` (models/zai.py:11, 34).
- Full wiring: `flows/dev_loop/__init__.py` exports, server.py `"zai"`
  branch with `DEV_LOOP_ZAI_MODEL` / `ZAI_CODE_MAX_CONCURRENT_DISPATCHES` /
  `DEV_LOOP_ZAI_ENABLE_THINKING` / `DEV_LOOP_ZAI_REASONING_EFFORT` config
  keys, tests mirroring `test_grok_code_dispatcher.py`.

✅ **Pros:**
- GLM-5.2's native thinking + reasoning_effort actually reach the API.
- Zero duplication of the agent loop, tool schemas, event streaming,
  cwd-safety guard, or output validation.
- Profile-subclass trick keeps thinking config per-dispatch without
  breaking the shared-dispatcher concurrency model.
- Fixes (rather than copies) the Grok `client_factory` lambda bug by using
  `lambda model, **kw: LLMFactory.create(model, **kw)`.

❌ **Cons:**
- Slightly unusual profile shape vs. siblings (subclass instead of
  standalone BaseModel) — mitigated by keeping the public field surface
  identical to `GrokCodeDispatchProfile` plus the two thinking fields.
- Coupled to `LLMCodeDispatcher` internals (`_completion_args`,
  `_chat_completion` hook contracts); a refactor there touches this class.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `zai-sdk` | Official Z.ai SDK (`from zai import ZaiClient`) | 0.2.3 (latest); `create()` verified to accept `thinking`, `reasoning_effort`, `tools`, `tool_choice` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:1721` — `LLMCodeDispatcher` (loop, tools, events, validation)
- `packages/ai-parrot/src/parrot/clients/zai.py:22` — `ZaiClient` (auth, `get_client()`, `_thinking_payload`, to_thread pattern)
- `packages/ai-parrot/src/parrot/models/zai.py` — `ZaiModel`, `THINKING_CAPABLE_ZAI_MODELS`
- `packages/ai-parrot/tests/flows/dev_loop/test_grok_code_dispatcher.py` — test harness (fake client + monkeypatched factory)
- `examples/dev_loop/server.py:449–540` — agent-selection branch pattern

---

### Option C: Fully standalone native loop

A self-contained `ZaiCodeDispatcher` (no inheritance) owning its own
conversation loop, tool execution, Redis streaming, and Pydantic output
validation, calling `ZaiClient` directly with full control of every Z.ai
parameter (including streamed `reasoning_content` deltas).

✅ **Pros:**
- Total freedom over the request/response cycle (token-level thinking
  streams, Z.ai-specific retries, context-cache headers later).
- Immune to `LLMCodeDispatcher` refactors.

❌ **Cons:**
- Duplicates ~500+ lines of loop/tooling/event code that must be kept in
  sync with four other dispatchers — the exact maintenance trap the
  `LLMCodeDispatcher` base was built to avoid.
- Rejected during discovery Round 3 by the author.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `zai-sdk` | Official Z.ai SDK | sync-only; every call needs thread offloading |

🔗 **Existing Code to Reuse:**
- Event models (`DispatchEvent`, models.py) and `_publish_event` pattern only.

---

### Option D (unconventional): Reuse ClaudeCodeDispatcher via Z.ai's Anthropic-compatible endpoint

Z.ai's Coding Plan exposes an Anthropic-compatible API that the `claude`
CLI can consume (`ANTHROPIC_BASE_URL` + Z.ai key). No new classes: point the
existing `ClaudeCodeDispatcher` at GLM-5.2 through environment overrides.

✅ **Pros:**
- Zero new dispatcher code; inherits the full Claude Code CLI feature set
  (real sandboxing, MCP, native file tools).
- Interesting as an ops-level escape hatch or benchmark baseline.

❌ **Cons:**
- Does not satisfy the stated requirement (`ZaiCodeDispatcher` +
  `ZaiCodeDispatchProfile` driven by `ZaiClient`).
- Couples dev-loop behavior to an external CLI's compatibility with a
  third-party endpoint; no programmatic control of thinking/reasoning_effort
  per dispatch; env mutation affects every Claude dispatch in the process.

📊 **Effort:** Low (config-only) — but off-spec

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `claude` CLI | Existing CLI runtime | already required by `ClaudeCodeDispatcher` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:145` — `ClaudeCodeDispatcher` unchanged.

---

## Recommendation

**Option B** is recommended (and matches the decisions made during
interactive discovery):

- The author explicitly wants Z.ai's **native** request surface (thinking
  mode on by default, `reasoning_effort`), which Option A silently drops —
  its generic path emits Nvidia-style `extra_body` thinking flags that Z.ai
  does not honor.
- The author equally explicitly wants the shared tool loop, turn-level
  events, and `ZaiClient` as the access layer — which rules out Option C's
  500-line duplication and Option D's CLI detour.
- The tradeoff accepted: coupling to two well-defined `LLMCodeDispatcher`
  hook points (`_completion_args`, `_chat_completion`) in exchange for zero
  loop duplication. These hooks are already the sanctioned extension seam
  (Grok uses `_chat_completion` the same way).
- Bonus: implementing the client factory correctly
  (`lambda model, **kw: LLMFactory.create(model, **kw)`) avoids the latent
  `model_args` TypeError that Grok's lambda carries.

---

## Feature Description

### User-Facing Behavior

- A dev-loop operator sets `DEV_LOOP_DEVELOPMENT_AGENT=zai` (plus
  `ZAI_API_KEY`) and the DevelopmentNode runs its coding tasks on GLM-5.2
  through Z.ai, with log line
  `"Development node using Z.ai code dispatcher (model=glm-5.2, thinking=enabled)"`.
- Optional config: `DEV_LOOP_ZAI_MODEL` (default `glm-5.2`),
  `ZAI_CODE_MAX_CONCURRENT_DISPATCHES` (falls back to
  `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES`), `DEV_LOOP_ZAI_ENABLE_THINKING`
  (default `true`), `DEV_LOOP_ZAI_REASONING_EFFORT` (default `high`).
- Programmatic users import `ZaiCodeDispatcher` / `ZaiCodeDispatchProfile`
  from `parrot.flows.dev_loop` and pass them as `development_dispatcher` /
  `development_profile`, exactly like the Grok pair.
- The streaming UI shows the same turn-level event timeline as other
  local-loop dispatchers (queued → started → message/tool_use/tool_result…
  → completed).
- An invalid `DEV_LOOP_DEVELOPMENT_AGENT` error message now enumerates
  `'zai'` among the valid values.

### Internal Behavior

1. `ZaiCodeDispatcher(max_concurrent=…, redis_url=…, stream_ttl_seconds=…)`
   subclasses `LLMCodeDispatcher`, passing a client factory that resolves
   `"zai:<model>"` through `LLMFactory` (which already maps `"zai"` →
   `ZaiClient`, factory.py:60) and **forwards `model_args`**.
2. `ZaiCodeDispatchProfile` subclasses `LLMCodeDispatchProfile` with
   `model="glm-5.2"`, `enable_thinking=True`, `reasoning_effort="high"`;
   a validator/derivation sets `llm=f"zai:{model}"`. Public fields stay
   aligned with `GrokCodeDispatchProfile` (sandbox, approval_policy,
   timeout_seconds, max_turns, max_tokens, temperature,
   command_timeout_seconds, allowed_commands).
3. `dispatch()` delegates to `super().dispatch()` unchanged — semaphore,
   wall-clock timeout, cwd guard, and event envelope all inherited.
4. Overridden `_completion_args()` builds the standard tools/tool_choice/
   max_tokens/temperature args, then adds Z.ai-native
   `thinking={"type": "enabled"|"disabled"}` and `reasoning_effort` —
   never the Nvidia `extra_body` block. It warns (via
   `THINKING_CAPABLE_ZAI_MODELS`) if thinking is requested on a non-capable
   model, mirroring `ZaiClient._thinking_payload` (clients/zai.py:184).
5. Overridden `_chat_completion()` ensures the official SDK client exists
   (`await client._ensure_client()` — inherited from `AbstractClient`,
   base.py:652) and executes
   `asyncio.to_thread(sdk_client.chat.completions.create, model=…,
   messages=…, **args)` — the sync-SDK offloading pattern already proven in
   `ZaiClient._create_completion` (clients/zai.py:284–286).
6. Response parsing (`_response_message`, `_message_content`,
   `_message_tool_calls`) is inherited — zai-sdk returns OpenAI-shaped
   `choices[0].message` objects with `tool_calls`. If the message carries
   `reasoning_content`, it is surfaced as a `dispatch.message` payload field
   (truncated) but **excluded** from the transcript appended back to
   `messages`.
7. Model registry: `ZaiModel.GLM_5_2 = "glm-5.2"` added and included in
   `THINKING_CAPABLE_ZAI_MODELS` so both the dispatcher and the existing
   `ZaiClient.ask()` paths recognize it.

### Edge Cases & Error Handling

- **Missing `ZAI_API_KEY`**: `ZaiClient.__init__` raises `ValueError`
  eagerly (clients/zai.py:40–44) — surfaces as `dispatch.failed` with a
  clear message; server startup with agent `zai` should fail fast.
- **Thinking on a non-capable model** (e.g. operator overrides model to
  `glm-4-32b-0414-128k`): warn and still send the payload (matches
  `ZaiClient._thinking_payload` behavior) — Z.ai ignores it server-side.
- **max_turns exhaustion / timeout / invalid final payload**: inherited
  `DispatchExecutionError` / `DispatchOutputValidationError` semantics,
  already evented and tested in the base class.
- **Sync SDK blocking**: all SDK calls offloaded via `asyncio.to_thread`;
  the event loop is never blocked (async-first rule).
- **`reasoning_content` growth**: thinking output is not fed back into the
  conversation, keeping the transcript within budget on long loops.
- **max_tokens ceiling**: profile inherits `le=32768`; GLM-5.2 supports up
  to 128K output — whether to raise the bound is an open question below.

---

## Capabilities

### New Capabilities
- `zai-client-code`: Z.ai GLM-5.2 code dispatcher for the dev loop —
  `ZaiCodeDispatcher` + `ZaiCodeDispatchProfile` with native thinking and
  reasoning-effort support, model-registry update, and dev-loop server wiring.

### Modified Capabilities
- (none — `sdd/specs/` has no existing spec owning dispatcher.py's LLM-loop
  family; changes to `examples/dev_loop/server.py` are additive wiring.)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py` | extends | new `ZaiCodeDispatcher`; `__all__` update |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` | extends | new `ZaiCodeDispatchProfile` (subclass of `LLMCodeDispatchProfile`) |
| `packages/ai-parrot/src/parrot/models/zai.py` | modifies | add `GLM_5_2` enum member + thinking-capable set entry |
| `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` | modifies | export the new pair |
| `examples/dev_loop/server.py` | modifies | `"zai"` branch in `_on_startup` agent selection + error-message enum |
| `packages/ai-parrot/tests/flows/dev_loop/` | extends | `test_zai_code_dispatcher.py` (mirror Grok suite) + `test_server_repo_wiring.py::test_server_zai_agent_startup` |
| `packages/ai-parrot/pyproject.toml` | optional | tighten `zai-sdk>=0.2.2` → `>=0.2.3` (no functional need; 0.2.3 already satisfies `>=0.2.2`) |
| `parrot/clients/zai.py` (`ZaiClient`) | depends on | no changes required — verified surface below |

No breaking changes; the feature is purely additive.

---

## Code Context

### User-Provided Code

```python
# Source: user-provided (discovery Round 3 — approved design sketch)
class ZaiCodeDispatcher(LLMCodeDispatcher):
    async def _chat_completion(self, *, client, model, messages, args):
        # native zai-sdk call via ZaiClient's official client
        # + thinking={"type": "enabled"} when profile.enable_thinking
        return await asyncio.to_thread(
            client.client.chat.completions.create,
            model=model, messages=messages,
            thinking=self._thinking_param(), **args)
    # thinking blocks parsed → DispatchEvent(reasoning)
```
*(Note: final design routes thinking/reasoning_effort through an
`_completion_args` override instead of dispatcher instance state, so the
shared dispatcher stays concurrency-safe.)*

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py
class DevLoopCodeDispatcher(Protocol):                      # line 124
    async def dispatch(self, *, brief, profile, output_model,
                       run_id, node_id, cwd) -> T: ...      # line 127

class LLMCodeDispatcher:                                    # line 1721
    def __init__(self, *, max_concurrent: int, redis_url: str,
                 stream_ttl_seconds: int,
                 client_factory: Callable[..., Any] = LLMFactory.create) -> None
    async def dispatch(self, *, brief: BaseModel,
                       profile: LLMCodeDispatchProfile,
                       output_model: Type[T], run_id: str,
                       node_id: str, cwd: str) -> T         # line 1747
    def _create_client(self, profile) -> Any                # line 1964
        # calls self._client_factory(profile.llm, model_args={temperature, max_tokens})
    async def _ensure_client_ready(client) -> None          # line 1972 (staticmethod)
        # checks getattr(client, "client", None); falls back to client._ensure_client()
    def _resolve_model(profile, client) -> str              # line 1980 (staticmethod)
    def _initial_messages(profile, brief, output_model)     # line 1992
    def _completion_args(profile, tools) -> Dict[str, Any]  # line 2016
        # enable_thinking → extra_body={"chat_template_kwargs": {...}}  (NVIDIA-style — must be overridden for Z.ai)
    async def _chat_completion(*, client, model, messages, args)  # line 2038
        # default expects client._chat_completion(...) — ZaiClient does NOT have that method
    def _tool_schemas(output_model)                         # line 2056
    async def _run_tool(*, tool_name, tool_args, cwd, profile)    # line 2167

class GrokCodeDispatcher(LLMCodeDispatcher):                # line 2565
    # __init__ passes client_factory=lambda model: LLMFactory.create(model)   # line 2583
    #   ⚠ LATENT BUG: _create_client passes model_args= kwarg; this lambda rejects it.
    async def _chat_completion(...)                         # line 2586
    async def dispatch(...)  # maps GrokCodeDispatchProfile → LLMCodeDispatchProfile, super().dispatch()
```

```python
# From packages/ai-parrot/src/parrot/flows/dev_loop/models.py
class LLMCodeDispatchProfile(BaseModel):                    # line 450
    subagent: Literal["sdd-worker"] = "sdd-worker"
    llm: str = "nvidia:moonshotai/kimi-k2-instruct-0905"
    sandbox: Literal["workspace-write"] = "workspace-write"
    approval_policy: Literal["never"] = "never"
    timeout_seconds: int    # default 1800, ge=60, le=7200
    max_turns: int          # default 24, ge=1, le=100
    max_tokens: int         # default 4096, ge=256, le=32768
    temperature: float      # default 0.0
    command_timeout_seconds: int   # default 300
    allowed_commands: List[str]    # git, uv, pytest, python, python3, rg, ls, pwd, cat, sed, find
    enable_thinking: bool = False  # NVIDIA chat_template_kwargs semantics
    clear_thinking: bool = False

class GrokCodeDispatchProfile(BaseModel):                   # line 490
    model: str = "grok-build-0.1"  # + same operational fields, no thinking fields
```

```python
# From packages/ai-parrot/src/parrot/clients/zai.py
class ZaiClient(AbstractClient):                            # line 22
    client_type: str = "zai"
    model: str = ZaiModel.GLM_5_1.value                     # line 27 — default model is glm-5.1 today
    _default_model: str = ZaiModel.GLM_5_1.value            # line 28
    def __init__(self, api_key=None,
                 base_url="https://api.z.ai/api/paas/v4/",
                 timeout=None, max_retries=None, **kwargs)  # line 32
        # raises ValueError if no api_key and no ZAI_API_KEY env   # lines 40-44
    async def get_client(self) -> Any                       # line 54 — builds official `zai.ZaiClient`
    def _thinking_payload(self, model, thinking, deep_thinking)   # line 184
        # returns {"type": "enabled"|"disabled"} dict; warns if model not thinking-capable
    async def _create_completion(self, **request_args)      # line 284
        # client = await self._ensure_client()
        # return await asyncio.to_thread(client.chat.completions.create, **request_args)
```

```python
# From packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient:
    async def _ensure_client(self, **hints) -> Any          # line 652 — inherited by ZaiClient
```

```python
# From packages/ai-parrot/src/parrot/models/zai.py
class ZaiModel(str, Enum):                                  # line 4
    GLM_5_1 = "glm-5.1"                                     # line 11 — newest member today
    ...
THINKING_CAPABLE_ZAI_MODELS = frozenset({...})              # line 34 — includes glm-5.1, NOT glm-5.2
```

```python
# From packages/ai-parrot/src/parrot/clients/factory.py
CLIENT_REGISTRY includes "zai": ZaiClient                   # line 60
LLMFactory.parse_llm_string("zai:glm-5.2") -> ("zai", "glm-5.2")   # line 94
LLMFactory.create(llm, model_args=None, tool_manager=None, **kwargs)  # line 116
```

```python
# From examples/dev_loop/server.py (agent selection in _on_startup, lines 449-540)
development_agent = conf.config.get("DEV_LOOP_DEVELOPMENT_AGENT", fallback="claude-code")
# branches: "codex" | "gemini" | "nvidia"/"llm" | "grok" | default "claude-code"
# each builds <X>CodeDispatcher(max_concurrent=…, redis_url=…, stream_ttl_seconds=…) + profile
# final else raises RuntimeError enumerating valid agent names  → must add 'zai'
```

#### Verified Imports
```python
from parrot.clients.zai import ZaiClient                     # packages/ai-parrot/src/parrot/clients/zai.py:22
from parrot.clients.factory import LLMFactory                # registry "zai" at factory.py:60
from parrot.models.zai import ZaiModel, THINKING_CAPABLE_ZAI_MODELS
from parrot.flows.dev_loop.dispatcher import LLMCodeDispatcher, GrokCodeDispatcher

…(truncated)…
