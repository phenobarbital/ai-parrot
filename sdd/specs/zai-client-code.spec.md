---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Z.ai Code Dispatcher for the Dev Loop (GLM-5.2)

**Feature ID**: FEAT-269
**Date**: 2026-07-03
**Author**: Jesus (jlara@trocglobal.com)
**Status**: draft
**Target version**: next
**Brainstorm**: `sdd/proposals/zai-client-code.brainstorm.md` (Option B accepted)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The dev-loop flow (`parrot/flows/dev_loop/`) currently supports five code
dispatchers for its DevelopmentNode: `ClaudeCodeDispatcher`,
`CodexCodeDispatcher`, `GeminiCodeDispatcher`, `LLMCodeDispatcher`, and
`GrokCodeDispatcher`. There is no way to run the coding loop on Z.ai's GLM
models even though the framework already ships a full `ZaiClient`
(`parrot.clients.zai`) and Z.ai released **GLM-5.2** — a 1M-context /
128K-output flagship explicitly trained for long-horizon coding-agent
scenarios (Terminal-Bench 2.1: 81.0 vs 62.0 for GLM-5.1; SWE-bench Pro 62.1).

Developers running the dev loop want to select `zai` as the development agent
(like `grok` or `nvidia` today) and get GLM-5.2's **native** request surface —
thinking mode (`thinking={"type": "enabled"}`) and `reasoning_effort` — rather
than the generic OpenAI-compatible fallback, whose Nvidia-style
`extra_body.chat_template_kwargs` thinking flags Z.ai does not understand.

### Goals

- Add `ZaiCodeDispatcher` + `ZaiCodeDispatchProfile` following the existing
  dispatcher family conventions (constructor kwargs `max_concurrent` /
  `redis_url` / `stream_ttl_seconds`; `dispatch()` per the
  `DevLoopCodeDispatcher` Protocol).
- Drive the LLM through `ZaiClient` (`parrot.clients.zai`) — never the raw
  SDK from the dispatcher — while sending Z.ai-native `thinking` and
  `reasoning_effort` parameters.
- Reuse the `LLMCodeDispatcher` local tool loop (read_file, list_files,
  search_files, write_file, run_command with `allowed_commands` whitelist,
  `final_output`) — zero duplicated agent-loop code.
- Turn-level `DispatchEvent` streaming to Redis with the same event kinds as
  sibling dispatchers.
- Thinking ON by default (`reasoning_effort="max"`), tunable per profile.
- Register `glm-5.2` in `ZaiModel` and `THINKING_CAPABLE_ZAI_MODELS`; bump
  `ZaiClient` class defaults (`model`, `_default_model`) to `glm-5.2`.
- Full wiring: `parrot.flows.dev_loop` exports, `examples/dev_loop/server.py`
  agent selection (`DEV_LOOP_DEVELOPMENT_AGENT=zai`), tests mirroring the
  Grok suite.
- Fix the latent `GrokCodeDispatcher.client_factory` lambda bug
  (dispatcher.py:2583 rejects the `model_args=` kwarg passed by
  `_create_client`) with a regression test.

### Non-Goals (explicitly out of scope)

- No token-level streaming of thinking deltas to the UI (turn-level events
  only — rejected during brainstorm discovery).
- No standalone/duplicated agent loop (brainstorm Option C rejected) and no
  CLI detour via Z.ai's Anthropic-compatible endpoint (brainstorm Option D
  rejected) — see `sdd/proposals/zai-client-code.brainstorm.md`.
- No `zai-sdk` upgrade: 0.2.3 (installed) is the latest on PyPI and already
  supports `thinking` + `reasoning_effort`. Only the pyproject pin is
  tightened to `>=0.2.3` for documentation value.
- No changes to `ZaiClient`'s completion/streaming/tool-loop logic — only its
  default-model class attributes change.
- No Z.ai context-caching integration (future work).

---

## 2. Architectural Design

### Overview

`ZaiCodeDispatcher` subclasses `LLMCodeDispatcher`, inheriting the semaphore,
wall-clock timeout, cwd-safety guard, local tool loop, Redis event envelope,
and Pydantic output validation. It overrides exactly two hook points:

1. **`_completion_args()`** — emits Z.ai-native
   `thinking={"type": "enabled"|"disabled"}` and `reasoning_effort=<str>`
   instead of the Nvidia-style `extra_body` block.
2. **`_chat_completion()`** — obtains the official SDK client owned by
   `ZaiClient` (`await client._ensure_client()`, inherited from
   `AbstractClient`) and executes
   `asyncio.to_thread(sdk_client.chat.completions.create, ...)` — the
   sync-SDK offloading pattern already proven in
   `ZaiClient._create_completion`.

`ZaiCodeDispatchProfile` **subclasses `LLMCodeDispatchProfile`** (unlike
Grok's standalone profile) adding `model: str = "glm-5.2"` (derives
`llm="zai:glm-5.2"`), `enable_thinking: bool = True` (reinterpreted with
Z.ai semantics), and `reasoning_effort: str = "max"`. Because the profile IS
an `LLMCodeDispatchProfile`, it flows through `super().dispatch()` unchanged
and `_completion_args(profile, tools)` can read the Z.ai fields directly —
no per-dispatch state on the shared dispatcher instance (concurrency-safe
under the semaphore). It redeclares `max_tokens` with `default=8192,
le=131072` (GLM-5.2 supports 128K output and thinking tokens count toward
it).

The client factory is `lambda model, **kw: LLMFactory.create(model, **kw)`
so the `model_args=` kwarg from `_create_client` is forwarded — fixing, not
copying, the Grok lambda bug (which is also patched in this feature).

Decisions resolved in brainstorm/clarification (authoritative):
- `reasoning_effort` default **`"max"`** (API default; verified enum:
  `max, xhigh, high, medium, low, minimal, none` — `low`/`medium` map to
  `high`, `xhigh` maps to `max`, `none`/`minimal` skip thinking; the param
  only takes effect when thinking is enabled and is only supported by
  GLM-5.2).
- `max_tokens`: **default 8192, cap 131072** for the Zai profile.
- Grok `client_factory` bug: **fixed in this feature** (one line + test).
- `ZaiClient.model` / `_default_model`: **bumped to `glm-5.2`**
  (`_lightweight_model` unchanged).

### Component Diagram

```
DevelopmentNode ──dispatch(brief, profile)──→ ZaiCodeDispatcher
                                                   │ (inherits loop from LLMCodeDispatcher)
        ┌──────────────────────────────────────────┤
        │ overrides                                │ inherits
        ▼                                          ▼
 _completion_args()                       tool loop / events / validation
 thinking + reasoning_effort              read_file · list_files · search_files
        │                                 write_file · run_command · final_output
        ▼                                          │
 _chat_completion()                                ▼
   ZaiClient._ensure_client()             Redis XADD flow:{run_id}:dispatch:{node_id}
   asyncio.to_thread(                     (dispatch.queued/started/message/
     sdk.chat.completions.create)          tool_use/tool_result/completed/failed)
        │
        ▼
 zai-sdk 0.2.3 (sync) ──HTTPS──→ api.z.ai /paas/v4/chat/completions (glm-5.2)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `LLMCodeDispatcher` (`flows/dev_loop/dispatcher.py:1721`) | extends | subclass; overrides `_completion_args`, `_chat_completion`; `__all__` grows |
| `LLMCodeDispatchProfile` (`flows/dev_loop/models.py:450`) | extends | `ZaiCodeDispatchProfile` subclass with Z.ai fields |
| `ZaiClient` (`clients/zai.py:22`) | uses / modifies | dispatcher drives it via `LLMFactory`; class defaults bump to `glm-5.2` |
| `ZaiModel` / `THINKING_CAPABLE_ZAI_MODELS` (`models/zai.py`) | modifies | add `GLM_5_2 = "glm-5.2"` + thinking-capable entry |
| `LLMFactory` (`clients/factory.py:60,116`) | uses | `"zai"` already registered; factory lambda forwards `model_args` |
| `GrokCodeDispatcher` (`flows/dev_loop/dispatcher.py:2565`) | modifies | fix `client_factory` lambda to accept `**kwargs` |
| `parrot/flows/dev_loop/__init__.py` | modifies | export `ZaiCodeDispatcher`, `ZaiCodeDispatchProfile` |
| `examples/dev_loop/server.py` (`_on_startup`, 449–540) | modifies | `"zai"` branch + error-message enumeration |
| `packages/ai-parrot/pyproject.toml` | modifies | `zai-sdk>=0.2.2` → `>=0.2.3` (both extras occurrences, lines 375–388) |

No breaking public-API changes. Behavioral change (accepted): code that
instantiates `ZaiClient` without an explicit model now gets `glm-5.2`.

### Data Models

```python
# flows/dev_loop/models.py — NEW (design contract, not implementation)
class ZaiCodeDispatchProfile(LLMCodeDispatchProfile):
    """Declarative profile consumed by ``ZaiCodeDispatcher.dispatch()``.

    Subclasses LLMCodeDispatchProfile so it flows through the inherited
    dispatch loop unchanged; Z.ai-native fields are read by the
    ZaiCodeDispatcher._completion_args override.
    """
    model: str = "glm-5.2"                     # convenience; derives llm
    llm: str = "zai:glm-5.2"                   # kept in sync via validator
    enable_thinking: bool = True               # Z.ai semantics (NOT nvidia extra_body)
    reasoning_effort: Literal[
        "max", "xhigh", "high", "medium", "low", "minimal", "none"
    ] = "max"
    max_tokens: int = Field(default=8192, ge=256, le=131072)  # redeclared bound
    # inherited unchanged: subagent, sandbox, approval_policy,
    # timeout_seconds, max_turns, temperature, command_timeout_seconds,
    # allowed_commands, clear_thinking (unused by Z.ai path)
```

A `model_validator` keeps `llm == f"zai:{model}"` when the caller sets only
`model` (mirrors the ergonomics of `GrokCodeDispatchProfile.model`).

### New Public Interfaces

```python
# flows/dev_loop/dispatcher.py — NEW (design contract, not implementation)
class ZaiCodeDispatcher(LLMCodeDispatcher):
    """Local coding-agent loop bound to ZaiClient / GLM-5.2 (native params)."""

    def __init__(self, *, max_concurrent: int, redis_url: str,
                 stream_ttl_seconds: int) -> None: ...
        # super().__init__(..., client_factory=lambda model, **kw:
        #                  LLMFactory.create(model, **kw))

    def _completion_args(self, profile, tools) -> Dict[str, Any]: ...
        # tools/tool_choice/max_tokens/temperature as base, PLUS
        # thinking={"type": "enabled"|"disabled"}, reasoning_effort=...
        # NEVER emits extra_body.chat_template_kwargs.
        # Warns (self.logger) when thinking requested for a model not in
        # THINKING_CAPABLE_ZAI_MODELS.

    async def _chat_completion(self, *, client, model, messages, args) -> Any: ...
        # sdk = await client._ensure_client()   (AbstractClient, base.py:652)
        # return await asyncio.to_thread(
        #     sdk.chat.completions.create, model=model, messages=messages, **args)

    async def dispatch(self, *, brief, profile: ZaiCodeDispatchProfile,
                       output_model, run_id, node_id, cwd) -> T: ...
        # thin: delegates to super().dispatch() (profile already compatible)
```

Exported from `parrot.flows.dev_loop` alongside the existing five
dispatchers and their profiles.

**Server configuration surface (new keys, `examples/dev_loop/server.py`):**

| Config key | Default | Purpose |
|---|---|---|
| `DEV_LOOP_DEVELOPMENT_AGENT` | `claude-code` | now also accepts `zai` |
| `DEV_LOOP_ZAI_MODEL` | `glm-5.2` | model for the Zai profile |
| `ZAI_CODE_MAX_CONCURRENT_DISPATCHES` | `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES` | semaphore size |
| `DEV_LOOP_ZAI_ENABLE_THINKING` | `true` | maps to `enable_thinking` |
| `DEV_LOOP_ZAI_REASONING_EFFORT` | `max` | maps to `reasoning_effort` |

---

## 3. Module Breakdown

> Modules map to Task Artifacts in Phase 2. Sequential dependency chain.

### Module 1: Z.ai model registry + client defaults
- **Path**: `packages/ai-parrot/src/parrot/models/zai.py`,
  `packages/ai-parrot/src/parrot/clients/zai.py`,
  `packages/ai-parrot/pyproject.toml`
- **Responsibility**: Add `ZaiModel.GLM_5_2 = "glm-5.2"`; add it to
  `THINKING_CAPABLE_ZAI_MODELS`; bump `ZaiClient.model` and
  `ZaiClient._default_model` to `ZaiModel.GLM_5_2.value`
  (`_lightweight_model` unchanged); tighten `zai-sdk` pin to `>=0.2.3`
  (two occurrences, pyproject lines 375–388).
- **Depends on**: none

### Module 2: ZaiCodeDispatchProfile
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/models.py`
- **Responsibility**: New profile subclassing `LLMCodeDispatchProfile` per
  §2 Data Models (model/llm sync validator, `enable_thinking=True`,
  `reasoning_effort="max"`, `max_tokens` 8192/131072 bounds).
- **Depends on**: Module 1 (imports `ZaiModel` default value)

### Module 3: ZaiCodeDispatcher + Grok factory fix
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py`
- **Responsibility**: New `ZaiCodeDispatcher(LLMCodeDispatcher)` per §2 New
  Public Interfaces; add to `__all__`; fix
  `GrokCodeDispatcher.__init__` client factory to
  `lambda model, **kw: LLMFactory.create(model, **kw)` (line 2583).
- **Depends on**: Module 2

### Module 4: Package exports + dev-loop server wiring
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py`,
  `examples/dev_loop/server.py`
- **Responsibility**: Export the new pair; add `"zai"` branch to
  `_on_startup` agent selection (config keys per §2 table, log line
  `"Development node using Z.ai code dispatcher (model=%s, thinking=%s)"`);
  extend the invalid-agent `RuntimeError` message to include `'zai'`.
- **Depends on**: Module 3

### Module 5: Test suite
- **Path**: `packages/ai-parrot/tests/flows/dev_loop/test_zai_code_dispatcher.py`,
  `packages/ai-parrot/tests/flows/dev_loop/test_server_repo_wiring.py`,
  `packages/ai-parrot/tests/flows/dev_loop/test_grok_code_dispatcher.py`
- **Responsibility**: Zai dispatcher unit tests (mirror the Grok harness:
  fake client + monkeypatched `_client_factory`), Z.ai-native completion-args
  assertions, server startup test, Grok factory regression test.
- **Depends on**: Modules 1–4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_zai_profile_defaults` | 2 | model=glm-5.2, llm=zai:glm-5.2, enable_thinking=True, reasoning_effort=max, max_tokens=8192 |
| `test_zai_profile_model_syncs_llm` | 2 | setting `model="glm-5.1"` yields `llm="zai:glm-5.1"` |
| `test_zai_profile_max_tokens_bounds` | 2 | accepts 131072; rejects 131073 and <256 |
| `test_zai_completion_args_native_thinking` | 3 | args contain `thinking={"type": "enabled"}` + `reasoning_effort="max"`, and NO `extra_body` |
| `test_zai_completion_args_thinking_disabled` | 3 | `enable_thinking=False` → `thinking={"type": "disabled"}` |
| `test_zai_thinking_warns_non_capable_model` | 3 | thinking + non-capable model logs a warning, still dispatches |
| `test_zai_dispatch_runs_tool_loop_and_validates_final_output` | 3 | mirror of Grok test: tool loop → final_output → validated Pydantic result |
| `test_zai_text_json_final_output_is_supported` | 3 | mirror of Grok test |
| `test_zai_invalid_final_tool_payload_raises_validation_error` | 3 | mirror of Grok test |
| `test_zai_cwd_outside_worktree_base_rejected` | 3 | mirror of Grok test |
| `test_zai_client_factory_forwards_model_args` | 3 | default factory lambda accepts `model_args=` without TypeError |
| `test_grok_client_factory_forwards_model_args` | 3 | regression: fixed Grok lambda accepts `model_args=` |
| `test_glm_5_2_in_enum_and_thinking_capable` | 1 | `ZaiModel.GLM_5_2.value == "glm-5.2"` and set membership |
| `test_zai_client_default_model_is_glm_5_2` | 1 | `ZaiClient.model == ZaiClient._default_model == "glm-5.2"` |

### Integration Tests

| Test | Description |
|---|---|
| `test_server_zai_agent_startup` | `DEV_LOOP_DEVELOPMENT_AGENT=zai` builds `ZaiCodeDispatcher` + `ZaiCodeDispatchProfile` (mirror `test_server_grok_agent_startup`, test_server_repo_wiring.py:158) |
| `test_server_invalid_agent_lists_zai` | invalid agent RuntimeError message includes `'zai'` |

### Test Data / Fixtures

```python
# Mirror packages/ai-parrot/tests/flows/dev_loop/test_grok_code_dispatcher.py:107-119
# _FakeZaiClient: exposes ._ensure_client() -> fake sdk with
#   .chat.completions.create(**kwargs) recording call kwargs and returning
#   OpenAI-shaped responses (choices[0].message with content/tool_calls).
# monkeypatch.setattr(disp, "_client_factory", _client_factory)
# Reuse existing `brief` fixture pattern from conftest.py in the same dir.
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `ZaiCodeDispatcher` and `ZaiCodeDispatchProfile` exist, are exported
      from `parrot.flows.dev_loop`, and satisfy the `DevLoopCodeDispatcher`
      Protocol (`dispatch(*, brief, profile, output_model, run_id, node_id,
      cwd)`).
- [ ] Requests to Z.ai carry native `thinking={"type": ...}` and
      `reasoning_effort`; the Nvidia `extra_body.chat_template_kwargs` block
      is never sent by the Zai path.
- [ ] Thinking defaults ON with `reasoning_effort="max"`; both tunable via
      profile; profile `max_tokens` default 8192, cap 131072.
- [ ] All Z.ai SDK calls go through `ZaiClient`'s ensured official client via
      `asyncio.to_thread` — no blocking I/O in async context, no raw SDK
      instantiation in the dispatcher.
- [ ] The dispatcher reuses the inherited tool loop and emits the standard
      turn-level event kinds to Redis (`dispatch.queued/started/message/
      tool_use/tool_result/completed/failed/output_invalid`).
- [ ] `ZaiModel.GLM_5_2` exists, is in `THINKING_CAPABLE_ZAI_MODELS`, and
      `ZaiClient.model`/`_default_model` are `"glm-5.2"`.
- [ ] `examples/dev_loop/server.py` accepts
      `DEV_LOOP_DEVELOPMENT_AGENT=zai` with the §2 config keys and rejects
      unknown agents with a message that includes `'zai'`.
- [ ] Grok `client_factory` lambda fixed; regression test proves
      `model_args=` is forwarded for both Grok and Zai factories.
- [ ] `zai-sdk` pin tightened to `>=0.2.3`; no other dependency changes.
- [ ] No breaking changes to existing public API (additive only; the
      documented exception is the accepted `ZaiClient` default-model bump).
- [ ] All new unit + integration tests pass:
      `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
      — and the pre-existing dev-loop suite stays green.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All references below re-verified on 2026-07-03 against `dev`.

### Verified Imports

```python
from parrot.clients.zai import ZaiClient                     # packages/ai-parrot/src/parrot/clients/zai.py:22
from parrot.clients.factory import LLMFactory                # "zai" registered at clients/factory.py:60
from parrot.models.zai import ZaiModel, THINKING_CAPABLE_ZAI_MODELS   # models/zai.py:4,34
from parrot.flows.dev_loop.dispatcher import (
    LLMCodeDispatcher,                                       # dispatcher.py:1721
    GrokCodeDispatcher,                                      # dispatcher.py:2565
    DispatchExecutionError, DispatchOutputValidationError,
)
from parrot.flows.dev_loop.models import (
    LLMCodeDispatchProfile,                                  # models.py:450
    GrokCodeDispatchProfile,                                 # models.py:490
)
from zai import ZaiClient as OfficialZaiClient               # zai-sdk 0.2.3 (installed == latest on PyPI)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py
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
        # calls self._client_factory(profile.llm,
        #     model_args={"temperature": ..., "max_tokens": ...})
    @staticmethod
    async def _ensure_client_ready(client) -> None          # line 1972
        # returns early if getattr(client, "client", None); else awaits client._ensure_client()
    @staticmethod
    def _resolve_model(profile, client) -> str              # line 1980
        # LLMFactory.parse_llm_string(profile.llm) → model part, with client fallbacks
    def _initial_messages(profile, brief, output_model)     # line 1992
    def _completion_args(profile, tools) -> Dict[str, Any]  # line 2016
        # base: tools, tool_choice="auto", parallel_tool_calls=False, max_tokens, temperature
        # enable_thinking → extra_body={"chat_template_kwargs": {...}}  ← NVIDIA-style; MUST be overridden for Z.ai
    async def _chat_completion(*, client, model, messages, args)   # line 2038
        # default expects client._chat_completion(...) — ZaiClient does NOT have that method → override required
    def _tool_schemas(output_model)                         # line 2056
    async def _run_tool(*, tool_name, tool_args, cwd, profile)     # line 2167

class GrokCodeDispatcher(LLMCodeDispatcher):                # line 2565
    # __init__ passes client_factory=lambda model: LLMFactory.create(model)   # line 2583
    #   ⚠ BUG (fixed by this feature): rejects the model_args= kwarg from _create_client
    async def _chat_completion(...)                         # line 2586
    async def dispatch(...)                                 # line 2601 — maps profile → LLMCodeDispatchProfile
# __all__ at end of file lists the five dispatchers + errors               # lines 2632-2641
```

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models.py
class LLMCodeDispatchProfile(BaseModel):                    # line 450
    subagent: Literal["sdd-worker"] = "sdd-worker"
    llm: str = "nvidia:moonshotai/kimi-k2-instruct-0905"
    sandbox: Literal["workspace-write"] = "workspace-write"
    approval_policy: Literal["never"] = "never"
    timeout_seconds: int   # default 1800, ge=60, le=7200
    max_turns: int         # default 24, ge=1, le=100
    max_tokens: int        # default 4096, ge=256, le=32768  ← Zai subclass redeclares (8192 / le=131072)
    temperature: float     # default 0.0, ge=0.0, le=2.0
    command_timeout_seconds: int  # default 300, ge=1, le=3600
    allowed_commands: List[str]   # git, uv, pytest, python, python3, rg, ls, pwd, cat, sed, find
    enable_thinking: bool = False # NVIDIA chat_template_kwargs semantics in base class
    clear_thinking: bool = False

class GrokCodeDispatchProfile(BaseModel):                   # line 490
    model: str = "grok-build-0.1"  # + same operational fields; no thinking fields
```

```python
# packages/ai-parrot/src/parrot/clients/zai.py
class ZaiClient(AbstractClient):                            # line 22
    client_type: str = "zai"
    model: str = ZaiModel.GLM_5_1.value                     # line 27 — this feature bumps to GLM_5_2
    _default_model: str = ZaiModel.GLM_5_1.value            # line 28 — this feature bumps to GLM_5_2
    _lightweight_model: str = ZaiModel.GLM_4_5_FLASH_FREE.value   # line 29 — unchanged
    def __init__(self, api_key=None,
                 base_url="https://api.z.ai/api/paas/v4/",
                 timeout=None, max_retries=None, **kwargs)  # line 32
        # raises ValueError without api_key / ZAI_API_KEY env       # lines 40-44
    async def get_client(self) -> Any                       # line 54 — builds official zai.ZaiClient
    def _thinking_payload(self, model, thinking, deep_thinking)    # line 184
        # → {"type": "enabled"|"disabled"}; warns if model not in THINKING_CAPABLE_ZAI_MODELS
    async def _create_completion(self, **request_args)      # line 284
        # client = await self._ensure_client()
        # return await asyncio.to_thread(client.chat.completions.create, **request_args)

# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient:
    async def _ensure_client(self, **hints) -> Any          # line 652 — inherited by ZaiClient
```

```python
# packages/ai-parrot/src/parrot/models/zai.py
class ZaiModel(str, Enum):                                  # line 4
    GLM_5_1 = "glm-5.1"                                     # line 11 — newest member today; GLM_5_2 added by this feature
THINKING_CAPABLE_ZAI_MODELS = frozenset({...})              # line 34 — includes glm-5.1; glm-5.2 added by this feature

# packages/ai-parrot/src/parrot/clients/factory.py
# CLIENT registry includes "zai": ZaiClient                 # line 60
LLMFactory.parse_llm_string("zai:glm-5.2") → ("zai", "glm-5.2")   # line 94
LLMFactory.create(llm, model_args=None, tool_manager=None, **kwargs)  # line 116
```

```python
# examples/dev_loop/server.py — _on_startup agent selection (lines 449-540)
development_agent = conf.config.get("DEV_LOOP_DEVELOPMENT_AGENT", fallback="claude-code").strip().lower()
# branches: "codex" | "gemini" | "nvidia"/"llm" | "grok" | default "claude-code"
# each: <X>CodeDispatcher(max_concurrent=conf.config.getint("<X>_CODE_MAX_CONCURRENT_DISPATCHES",
#           fallback=conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES),
#       redis_url=redis_url, stream_ttl_seconds=conf.FLOW_STREAM_TTL_SECONDS) + profile + logger.info
# final elif raises RuntimeError enumerating valid names  ← must add 'zai'
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ZaiCodeDispatcher.__init__` | `LLMFactory.create` | `client_factory=lambda model, **kw: LLMFactory.create(model, **kw)` | `clients/factory.py:116` |
| `ZaiCodeDispatcher._chat_completion` | `ZaiClient._ensure_client()` | inherited `AbstractClient` method | `clients/base.py:652` |
| `ZaiCodeDispatcher._chat_completion` | `sdk.chat.completions.create` | `asyncio.to_thread` (sync SDK) | pattern at `clients/zai.py:284-286` |
| `ZaiCodeDispatcher._completion_args` | `THINKING_CAPABLE_ZAI_MODELS` | membership check for warning | `models/zai.py:34` |
| `ZaiCodeDispatchProfile` | `LLMCodeDispatchProfile` | Pydantic subclass | `flows/dev_loop/models.py:450` |
| server `"zai"` branch | `ZaiCodeDispatcher` + profile | mirrors Grok branch | `examples/dev_loop/server.py:516-530` |
| tests | fake client + `monkeypatch.setattr(disp, "_client_factory", ...)` | Grok harness pattern | `tests/flows/dev_loop/test_grok_code_dispatcher.py:107-119` |

**zai-sdk 0.2.3 verified call surface** (`inspect.signature` of
`zai.api_resource.chat.completions.Completions.create`):
`model, request_id, user_id, do_sample, stream, temperature, top_p,
max_tokens, seed, messages, stop, sensitive_word_check, tools, tool_choice,
meta, extra, extra_headers, extra_body, timeout, response_format, thinking,
watermark_enabled, tool_stream, reasoning_effort`.

**GLM-5.2 API facts** (docs.z.ai/guides/llm/glm-5.2 + chat-completion API
reference, fetched 2026-07-03): model id `"glm-5.2"`; context 1M; max output
128K; `thinking={"type": "enabled"|"disabled"}` (default enabled);
`reasoning_effort` enum `max|xhigh|high|medium|low|minimal|none`, default
`max`, GLM-5.2-only, effective only with thinking enabled (`low`/`medium`→
`high`, `xhigh`→`max`, `none`/`minimal` skip thinking); OpenAI-shaped
responses with `choices[0].message.tool_calls` and `reasoning_content`.

### Does NOT Exist (Anti-Hallucination)

- ~~`ZaiModel.GLM_5_2`~~ — not in the enum yet (created by Module 1)
- ~~`ZaiCodeDispatcher` / `ZaiCodeDispatchProfile`~~ — created by Modules 2–3
- ~~`ZaiClient._chat_completion`~~ — `ZaiClient` has `_create_completion`
  (different name/contract); the base `LLMCodeDispatcher._chat_completion`
  default path FAILS for ZaiClient and must be overridden
- ~~`zai` CLI binary~~ — no CLI runtime like `codex`/`gemini`; this is a
  local-loop dispatcher
- ~~async client in zai-sdk~~ — SDK 0.2.3 is synchronous only; wrap calls in
  `asyncio.to_thread`
- ~~`DEV_LOOP_ZAI_MODEL` / `ZAI_CODE_MAX_CONCURRENT_DISPATCHES` /
  `DEV_LOOP_ZAI_ENABLE_THINKING` / `DEV_LOOP_ZAI_REASONING_EFFORT`~~ —
  config keys introduced by Module 4
- ~~dispatcher registry in `flows/dev_loop/config.py` or `factories.py`~~ —
  agent selection lives ONLY in `examples/dev_loop/server.py:_on_startup`;
  `factories.py` merely threads a pre-built dispatcher into nodes
- ~~top-level `/parrot/` sources~~ — the repo-root `parrot/` directory is a
  stale build artifact (compiled files); live sources are under
  `packages/ai-parrot/src/parrot/`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first: every zai-sdk call via `asyncio.to_thread` (pattern:
  `ZaiClient._create_completion`, clients/zai.py:284–286). Never block the
  event loop.
- Subclass-and-override at the sanctioned seam: only `_completion_args` and
  `_chat_completion` (plus a thin `dispatch` for typing); everything else
  inherited (pattern: `GrokCodeDispatcher`, dispatcher.py:2565–2630).
- Pydantic profiles with `Field` bounds and Google-style docstrings
  (pattern: `LLMCodeDispatchProfile`, models.py:450).
- `self.logger` for the thinking-capability warning (pattern:
  `ZaiClient._thinking_payload`, clients/zai.py:184).
- Test harness: fake client + `monkeypatch.setattr(disp, "_client_factory",
  ...)` (pattern: test_grok_code_dispatcher.py:107–119).
- Never hardcode secrets — `ZAI_API_KEY` via environment only.

### Known Risks / Gotchas

- **Missing `ZAI_API_KEY`**: `ZaiClient.__init__` raises `ValueError`
  eagerly (clients/zai.py:40–44). With agent `zai`, server startup fails
  fast; in-loop failures surface as `dispatch.failed` events.
- **Thinking on a non-capable model** (operator overrides `model`): log a
  warning and still send — Z.ai ignores unknown thinking payloads
  server-side (mirrors `ZaiClient._thinking_payload` behavior).
- **`reasoning_effort` semantics**: only honored by GLM-5.2 and only when
  thinking is enabled; `none`/`minimal` silently skip thinking — do not
  "helpfully" strip the param for other models, match server-side mapping.
- **`reasoning_content` growth**: thinking output must NOT be appended back
  into the `messages` transcript (budget/echo risk); it may be surfaced
  (truncated) in `dispatch.message` payloads.
- **Do not touch `clear_thinking`/`extra_body`** in the Zai path — the
  inherited field exists but Nvidia semantics do not apply.
- **`ZaiClient` default-model bump blast radius**: existing ZaiClient users
  without an explicit model silently move from glm-5.1 to glm-5.2
  (accepted decision; release notes should mention cost/latency change).
- **Grok fix**: change ONLY the lambda signature
  (`lambda model, **kw: LLMFactory.create(model, **kw)`); do not alter
  Grok's `_chat_completion` or profile mapping.
- **`asyncio.timeout` wall-clock cap** (dispatcher.py: dispatch) still
  bounds a to_thread'd SDK call's await, but the underlying thread cannot be
  interrupted — long Z.ai hangs hold a worker thread until the SDK's own
  timeout fires. Pass `ZaiClient(timeout=...)`-level SDK timeouts if needed.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `zai-sdk` | `>=0.2.3` (installed 0.2.3 == latest on PyPI) | official SDK; `create()` verified to accept `thinking`, `reasoning_effort`, `tools`, `tool_choice` — **no upgrade needed**, pin tightened for documentation value |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Does GLM-5.2 require a `zai-sdk` upgrade? — *Resolved in brainstorm*:
  No. Installed 0.2.3 is the latest on PyPI, the GLM-5.2 docs pin 0.2.3, and
  `Completions.create` already accepts `thinking` + `reasoning_effort`.
  Pyproject pin tightened to `>=0.2.3` for documentation value.
- [x] Allowed `reasoning_effort` values? — *Resolved during spec research
  (docs.z.ai chat-completion API reference)*: enum
  `max|xhigh|high|medium|low|minimal|none`, default `max`, GLM-5.2-only,
  effective only when thinking is enabled; `low`/`medium`→`high`,
  `xhigh`→`max`, `none`/`minimal` skip thinking.
- [x] Default `reasoning_effort` for the coding loop? — *Resolved by user
  (spec clarification)*: `"max"` (matches API default and docs' coding
  showcase).
- [x] Profile `max_tokens` bounds? — *Resolved by user (spec clarification)*:
  default 8192, cap 131072 (thinking tokens count toward output budget).
- [x] Fix the Grok `client_factory` lambda `model_args` TypeError here or
  separately? — *Resolved by user (spec clarification)*: fix in this feature
  (one line + regression test, same file already touched).
- [x] Bump `ZaiClient.model`/`_default_model` to glm-5.2? — *Resolved by
  user (spec clarification)*: yes, bump both (accepted blast radius:
  ZaiClient users without explicit model move to glm-5.2);
  `_lightweight_model` unchanged.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one
  worktree (`.claude/worktrees/feat-269-zai-client-code`, branched from
  `dev`).
- **Rationale**: Modules 1→5 form a tight dependency chain concentrated in
  `flows/dev_loop/dispatcher.py` and `flows/dev_loop/models.py`; parallel
  worktrees would only create merge conflicts for no wall-clock gain.
- **Cross-feature dependencies**: none — no in-flight spec owns
  `flows/dev_loop/dispatcher.py` or `models/zai.py` (recent dev-loop
  features FEAT-253/FEAT-268 are merged into `dev`).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-03 | Jesus + Claude | Initial draft from brainstorm (Option B) with all open questions resolved |
