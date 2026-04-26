# Feature Specification: Claude SDK Migration & ClaudeAgentClient

**Feature ID**: FEAT-124
**Date**: 2026-04-27
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.5.x (next minor of `ai-parrot`)

---

## 1. Motivation & Business Requirements

### Problem Statement

Two distinct, related concerns motivate this work:

1. **Stale `anthropic` Python SDK pin.** `AnthropicClient`
   (`packages/ai-parrot/src/parrot/clients/claude.py`) currently depends on
   `anthropic[aiohttp]==0.61.0`. The latest published version on PyPI is
   `0.97.0` (a 36-version gap). Although the changelog shows almost no
   breaking changes affecting our usage, staying that far behind blocks
   future adoption of new beta headers, model constants, and bug fixes.

2. **No path to Claude-Code-style agent dispatch.** ai-parrot today can call
   the Claude API for completions, but it cannot delegate a *task* to a
   Claude Code agent (file-aware, bash-capable, MCP-aware). Anthropic's
   `claude-agent-sdk` (`v0.1.68`) wraps the bundled `claude` CLI as a
   subprocess and exposes `query()` / `ClaudeSDKClient`. Adding a new
   `ClaudeAgentClient` lets ai-parrot agents dispatch tasks to a Claude
   Code agent as a sub-agent, while keeping the heavy `claude` CLI binary
   off the deployment surface of installations that don't need it (via an
   optional extra).

### Goals

- **G1** — Upgrade the `anthropic` Python SDK pin from `==0.61.0` to a
  range that includes `0.97.0+` and re-validate `AnthropicClient` end-to-end
  (no behavioural regression: `ask`, `ask_stream`, `batch_ask`,
  `ask_to_image`, `invoke`, fallback model on capacity errors, 1M context
  beta).
- **G2** — Add a new `ClaudeAgentClient(AbstractClient)` that wraps
  `claude-agent-sdk>=0.1.68` and exposes `ask`, `ask_stream`, `invoke`,
  and `resume` against `query()` / `ClaudeSDKClient`.
- **G3** — Ship `claude-agent-sdk` as a *separate optional extra*
  (`ai-parrot[claude-agent]`) so the bundled CLI does not enter the base
  install surface. `AnthropicClient` (API client) and `ClaudeAgentClient`
  (CLI client) install independently.
- **G4** — Register `ClaudeAgentClient` in `LLMFactory.SUPPORTED_CLIENTS`
  under `claude-agent` / `claude-code` so existing agent code can target
  it via `LLMFactory.create("claude-agent:claude-sonnet-4-6")`.
- **G5** — Lazy-import the `claude_agent_sdk` module so the absence of the
  extra never breaks `import parrot.clients`.

### Non-Goals (explicitly out of scope)

- Replacing `parrot/integrations/mcp/` with `claude-agent-sdk`'s
  in-process MCP server (`create_sdk_mcp_server`, `@tool` decorator).
  *(Out of scope per /sdd-spec clarifications. Track separately.)*
- Implementing `batch_ask`, `ask_to_image`, `summarize_text`,
  `translate_text`, `analyze_sentiment`, `analyze_product_review`,
  or `extract_key_points` on `ClaudeAgentClient`. The SDK has no
  equivalent — these methods will `raise NotImplementedError` with a
  clear message redirecting users to `AnthropicClient`.
- Replacing `AnthropicClient`. Both clients coexist permanently;
  `AnthropicClient` remains the default for completion / vision / batch.
- Bundling or auto-installing the `claude` CLI binary. The
  `claude-agent-sdk` package bundles its own CLI; no extra packaging is
  required from ai-parrot.
- Hooks (`PreToolUse`, etc.) — defer until a concrete agent dispatch use
  case requires them.

---

## 2. Architectural Design

### Overview

The work is split into two independent, sequenceable tracks:

- **Track A — SDK upgrade**: bump `anthropic[aiohttp]` from `==0.61.0` to
  `>=0.97.0,<1.0.0` in the `anthropic` and `llms` extras of
  `packages/ai-parrot/pyproject.toml`. The breaking-change audit (see §7
  Known Risks) shows no impact on `AnthropicClient`'s actual usage; the
  upgrade should be primarily a regression-test exercise.

- **Track B — `ClaudeAgentClient`**: introduce a new client class that
  inherits `AbstractClient`, talks to `claude_agent_sdk.query()` /
  `ClaudeSDKClient`, and translates `AssistantMessage` / `TextBlock` /
  `ToolUseBlock` / `ResultMessage` events into the existing
  `AIMessage` shape via a new `AIMessageFactory.from_claude_agent`
  static method. Subprocess-driven; no API key required (uses the
  bundled CLI's auth, falling back to `ANTHROPIC_API_KEY` when set).

### Component Diagram

```
                              ┌────────────────────────────┐
                              │  AbstractClient (base.py)  │
                              └──────────┬─────────────────┘
                                         │
                ┌────────────────────────┼────────────────────────┐
                │                        │                        │
   ┌────────────▼───────────┐  ┌─────────▼──────────┐  ┌──────────▼──────────┐
   │   AnthropicClient      │  │  ClaudeAgentClient │  │  (other clients)    │
   │   (claude.py)          │  │  (claude_agent.py) │  │                     │
   │   uses: anthropic SDK  │  │  uses: claude-     │  │                     │
   │   API: messages.create │  │  agent-sdk         │  │                     │
   │   transport: HTTP      │  │  transport:        │  │                     │
   │                        │  │  subprocess(claude)│  │                     │
   └────────────┬───────────┘  └─────────┬──────────┘  └─────────────────────┘
                │                        │
                │                        ▼
                │              ┌──────────────────────┐
                │              │ claude-agent-sdk     │
                │              │ ─ query()            │
                │              │ ─ ClaudeSDKClient    │
                │              │ ─ ClaudeAgentOptions │
                │              └─────────┬────────────┘
                │                        │
                │                        ▼
                │              ┌──────────────────────┐
                │              │  bundled `claude` CLI│
                │              │  (subprocess)        │
                │              └──────────────────────┘
                │
                ▼
     ┌────────────────────────┐
     │   Anthropic API (HTTP) │
     └────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractClient` (`clients/base.py:231`) | extends | `ClaudeAgentClient` inherits, implements `get_client`, `ask`, `ask_stream`, `resume`, `invoke`. |
| `AIMessageFactory` (`models/responses.py:572`) | extends | New static `from_claude_agent(messages, …)` mirroring `from_claude`. |
| `LLMFactory.SUPPORTED_CLIENTS` (`clients/factory.py:19`) | extends | Add `"claude-agent"` and alias `"claude-code"` mapped to `ClaudeAgentClient` via a lazy loader (mirrors `_lazy_gemma4`). |
| `pyproject.toml` extras (`packages/ai-parrot/pyproject.toml:345`,`:370`) | modifies | Bump `anthropic` pin; split `claude-agent-sdk` into its own extra. |
| `parrot.clients.__init__` (`clients/__init__.py`) | unchanged | `ClaudeAgentClient` is loaded via the factory only — no top-level export, to avoid eager-importing `claude_agent_sdk`. |

### Data Models

```python
# parrot/clients/claude_agent.py
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ClaudeAgentRunOptions(BaseModel):
    """Run-time options forwarded to claude_agent_sdk.ClaudeAgentOptions.

    Mirrors the SDK's option surface but expressed as a pydantic model
    so it round-trips through the registry / config layer.
    """
    allowed_tools: Optional[List[str]] = Field(
        default=None,
        description="Whitelist of CC tools (Read, Write, Bash, Edit, …).",
    )
    disallowed_tools: Optional[List[str]] = Field(default=None)
    permission_mode: Optional[str] = Field(
        default=None,
        description="One of 'default', 'acceptEdits', 'plan', 'bypassPermissions'.",
    )
    cwd: Optional[str] = Field(default=None, description="Working dir for the agent.")
    cli_path: Optional[str] = Field(default=None, description="Override bundled CLI.")
    system_prompt: Optional[str] = None
```

### New Public Interfaces

```python
# parrot/clients/claude_agent.py
from parrot.clients.base import AbstractClient


class ClaudeAgentClient(AbstractClient):
    """Dispatch tasks to a Claude Code agent via claude-agent-sdk.

    This client wraps the bundled `claude` CLI as a subprocess and is
    intended for ai-parrot Agents that need to delegate file-aware,
    bash-capable, tool-using work to a Claude Code sub-agent.
    """
    client_type: str = "claude_agent"
    client_name: str = "claude-agent"
    use_session: bool = False
    _default_model: str = "claude-sonnet-4-6"
    _lightweight_model: str = "claude-haiku-4-5-20251001"

    async def get_client(self) -> Any:  # returns claude_agent_sdk.ClaudeSDKClient
        ...

    async def ask(self, prompt, *, run_options: ClaudeAgentRunOptions | None = None,
                  **kwargs) -> AIMessage: ...

    async def ask_stream(self, prompt, *, run_options=None,
                         **kwargs) -> AsyncIterator[str]: ...

    async def invoke(self, prompt, *, output_type=None, **kwargs) -> InvokeResult: ...

    async def resume(self, session_id, user_input, state) -> AIMessage: ...

    # Methods that the upstream SDK does not support — explicit failure mode:
    async def batch_ask(self, requests, **kwargs):
        raise NotImplementedError(
            "ClaudeAgentClient does not support batch. "
            "Use AnthropicClient for the Messages Batches API."
        )
```

---

## 3. Module Breakdown

### Module 1: `anthropic` SDK pin upgrade
- **Path**: `packages/ai-parrot/pyproject.toml`
- **Responsibility**: Bump the `anthropic[aiohttp]` pin in the `anthropic`
  extra (line 346) and the `llms` extra (line 370) from `==0.61.0` to
  `>=0.97.0,<1.0.0`. No code changes expected in `claude.py`.
- **Depends on**: nothing.

### Module 2: AnthropicClient regression validation
- **Path**: `tests/clients/test_anthropic_*.py` (existing) + a new smoke
  test `tests/clients/test_anthropic_sdk_097.py`.
- **Responsibility**: Re-run existing `AnthropicClient` tests against
  `anthropic==0.97.0`. Verify (i) `from anthropic import RateLimitError,
  APIStatusError` still imports, (ii) `from anthropic.types import
  Message, MessageStreamEvent` still imports, (iii) `betas` parameter
  for 1M context still accepted, (iv) `messages.batches` API still
  works against a recorded fixture or live key.
- **Depends on**: Module 1.

### Module 3: `ClaudeAgentClient` core implementation
- **Path**: `packages/ai-parrot/src/parrot/clients/claude_agent.py` (new).
- **Responsibility**: Implement `ClaudeAgentClient(AbstractClient)`.
  Includes: `get_client` returning `ClaudeSDKClient`, `ask` running a
  one-shot `query()` and assembling the resulting `AssistantMessage`
  blocks into a single `AIMessage`, `ask_stream` yielding `TextBlock`
  text incrementally as the SDK streams, `invoke` for stateless
  structured output (schema-in-prompt, mirroring `AnthropicClient.invoke`),
  `resume` to continue a session, `batch_ask` raising
  `NotImplementedError`. Lazy-import `claude_agent_sdk` inside methods
  so import-time failure when the extra is missing is impossible.
- **Depends on**: Module 4 (factory method).

### Module 4: `AIMessageFactory.from_claude_agent`
- **Path**: `packages/ai-parrot/src/parrot/models/responses.py`.
- **Responsibility**: New static method that consumes a list of
  `claude_agent_sdk` message objects (`AssistantMessage`, `UserMessage`,
  `SystemMessage`, `ResultMessage`) and produces an `AIMessage`. Handles:
  text concatenation across `TextBlock`s, mapping `ToolUseBlock` to
  `ToolCall`, extracting model name from `ResultMessage`, mapping
  `stop_reason` ≈ `result.subtype` (`success` / `error_max_turns` / etc.).
- **Depends on**: nothing (pure conversion).

### Module 5: Factory registration & lazy loader
- **Path**: `packages/ai-parrot/src/parrot/clients/factory.py`.
- **Responsibility**: Add `_lazy_claude_agent()` (mirrors `_lazy_gemma4` at
  factory.py:14) that imports and returns `ClaudeAgentClient`. Register
  under keys `"claude-agent"` and alias `"claude-code"` in
  `SUPPORTED_CLIENTS` (factory.py:19). Validate that a clear error is
  raised if the user requests `claude-agent` without the extra installed.
- **Depends on**: Module 3.

### Module 6: pyproject extras restructure
- **Path**: `packages/ai-parrot/pyproject.toml`.
- **Responsibility**: Move `claude-agent-sdk>=0.1.0,!=0.1.49` from the
  `anthropic` extra (line 347) and from `llms` (line 371) into a new,
  dedicated `claude-agent` extra pinned `>=0.1.68`. The `anthropic`
  extra stays focused on the API SDK only. Update the `llms` umbrella
  extra to include `claude-agent-sdk>=0.1.68` if and only if the user
  wants the kitchen-sink. Update the top-level
  `/home/jesuslara/proyectos/navigator/ai-parrot/pyproject.toml:24`
  re-export to add `claude-agent = ["ai-parrot[claude-agent]"]`.
- **Depends on**: nothing (parallel to Module 1).

### Module 7: Unit tests for `ClaudeAgentClient`
- **Path**: `tests/clients/test_claude_agent.py` (new).
- **Responsibility**: Unit tests with `claude_agent_sdk` mocked — verify
  `ask` assembles streamed messages correctly, `ask_stream` yields
  `TextBlock` text, `batch_ask` raises `NotImplementedError`, factory
  registration resolves `LLMFactory.create("claude-agent")`, lazy import
  produces a clear error when the extra is missing (use
  `monkeypatch.setattr` on `importlib`).
- **Depends on**: Modules 3, 4, 5.

### Module 8: Example & docs
- **Path**: `examples/clients/claude_agent_example.py` (new) + a short
  section in the package README under "Optional extras".
- **Responsibility**: Demonstrate an ai-parrot `Agent` dispatching a
  task to a Claude Code agent via `ClaudeAgentClient`, including
  `ClaudeAgentRunOptions(allowed_tools=["Read", "Bash"], cwd=...)`.
- **Depends on**: Modules 3–5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_anthropic_imports_097` | M2 | `from anthropic import RateLimitError, APIStatusError, AsyncAnthropic` and `from anthropic.types import Message, MessageStreamEvent` all succeed against `anthropic==0.97.0`. |
| `test_anthropic_betas_param_passthrough` | M2 | Mocked `messages.create` receives `betas=["context-1m-2025-08-07"]` when `context_1m=True`. |
| `test_anthropic_capacity_error_detection` | M2 | `AnthropicClient._is_capacity_error` still returns `True` for `RateLimitError` and `APIStatusError(status_code=529)` against the new SDK version. |
| `test_claude_agent_init_lazy_import` | M3 | `ClaudeAgentClient()` does not import `claude_agent_sdk` at construction time. |
| `test_claude_agent_ask_assembles_text` | M3 | Mocked `query()` yielding `AssistantMessage([TextBlock("hello"), TextBlock(" world")])` produces an `AIMessage` whose `output == "hello world"`. |
| `test_claude_agent_ask_stream_yields_text` | M3 | `ask_stream` yields `"hello"` and `" world"` in order. |
| `test_claude_agent_tool_use_recorded` | M3 | `ToolUseBlock(name="Bash", input={"cmd":"ls"}, id="t1")` produces a `ToolCall` in `AIMessage.tool_calls`. |
| `test_claude_agent_batch_ask_not_implemented` | M3 | `await client.batch_ask([])` raises `NotImplementedError` with a message that mentions `AnthropicClient`. |
| `test_aimessage_factory_from_claude_agent_basic` | M4 | Pure-conversion test; no client involved. |
| `test_aimessage_factory_from_claude_agent_result_metadata` | M4 | `ResultMessage(subtype="success", num_turns=3, total_cost_usd=…)` populates `AIMessage.usage` / `stop_reason` correctly. |
| `test_factory_registers_claude_agent` | M5 | `LLMFactory.parse_llm_string("claude-agent:claude-sonnet-4-6")` returns `("claude-agent", "claude-sonnet-4-6")` and `LLMFactory.create(...)` returns a `ClaudeAgentClient` instance. |
| `test_factory_claude_agent_missing_extra_message` | M5 | When `claude_agent_sdk` is unavailable, the factory raises `ImportError` with a hint to `pip install ai-parrot[claude-agent]`. |

### Integration Tests

| Test | Description |
|---|---|
| `test_anthropic_live_smoke` | (Marked `@pytest.mark.live`) Calls `AnthropicClient().ask("ping")` against the real API on `anthropic==0.97.0`. Skipped without `ANTHROPIC_API_KEY`. |
| `test_claude_agent_live_smoke` | (Marked `@pytest.mark.live`) Runs `ClaudeAgentClient().ask("List the files in cwd")` with the bundled CLI. Skipped if the `claude` binary is unavailable. |

### Test Data / Fixtures

```python
# tests/clients/conftest.py — NEW additions
import pytest


@pytest.fixture
def fake_claude_agent_messages():
    """Mimics the message stream that claude_agent_sdk.query() yields."""
    from claude_agent_sdk.types import (
        AssistantMessage, TextBlock, ToolUseBlock, ResultMessage,
    )
    return [
        AssistantMessage(content=[TextBlock(text="hello ")]),
        AssistantMessage(content=[TextBlock(text="world")]),
        ResultMessage(subtype="success", num_turns=1, total_cost_usd=0.001),
    ]
```

---

## 5. Acceptance Criteria

- [ ] `packages/ai-parrot/pyproject.toml` pins `anthropic[aiohttp]>=0.97.0,<1.0.0` in both the `anthropic` extra and the `llms` extra.
- [ ] `claude-agent-sdk>=0.1.68` is declared **only** in a new dedicated `claude-agent` extra (and re-exported in `llms` if desired).
- [ ] All existing `tests/clients/test_anthropic_*.py` tests pass against `anthropic==0.97.0` with no source changes to `parrot/clients/claude.py`.
- [ ] `ClaudeAgentClient` lives at `packages/ai-parrot/src/parrot/clients/claude_agent.py`, inherits `AbstractClient`, and implements `ask`, `ask_stream`, `resume`, `invoke`.
- [ ] `ClaudeAgentClient.batch_ask` raises `NotImplementedError` with a message mentioning `AnthropicClient`.
- [ ] `from parrot.clients import AbstractClient` works on a fresh install **without** the `[claude-agent]` extra (no eager import of `claude_agent_sdk`).
- [ ] `LLMFactory.create("claude-agent")` returns a `ClaudeAgentClient` instance when the extra is installed; without the extra, raises `ImportError` with `pip install ai-parrot[claude-agent]` hint.
- [ ] `AIMessageFactory.from_claude_agent` exists at `parrot/models/responses.py` and converts SDK message lists into `AIMessage`.
- [ ] All new unit tests in §4 pass: `pytest tests/clients/test_claude_agent.py tests/clients/test_anthropic_sdk_097.py -v`.
- [ ] `examples/clients/claude_agent_example.py` runs end-to-end against the bundled CLI.
- [ ] No breaking changes to the existing `AnthropicClient` public API (`ask`, `ask_stream`, `batch_ask`, `ask_to_image`, `summarize_text`, `translate_text`, `analyze_sentiment`, `analyze_product_review`, `extract_key_points`, `invoke`, `resume`).
- [ ] Documentation in the package README mentions both extras: `pip install ai-parrot[anthropic]` (API client) and `pip install ai-parrot[claude-agent]` (CLI dispatch client).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every entry below is verified by `read` against current `dev` (commit `c274f55f`).

### Verified Imports

```python
# Existing — keep using these verbatim.
from parrot.clients.base import AbstractClient                         # base.py:231
from parrot.clients.base import BatchRequest, StreamingRetryConfig     # base.py:182,188
from parrot.clients import AbstractClient                              # clients/__init__.py:6
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS       # factory.py:19,38
from parrot.clients.claude import AnthropicClient, ClaudeClient        # claude.py:40,1460 (alias)
from parrot.models import (                                            # used by claude.py:20-28
    AIMessage, AIMessageFactory, ToolCall, OutputFormat,
    StructuredOutputConfig, CompletionUsage, ObjectDetectionResult,
)
from parrot.models.responses import InvokeResult                       # claude.py:29
from parrot.models.claude import ClaudeModel                           # models/claude.py:4
from parrot.exceptions import InvokeError                              # claude.py:30

# Anthropic SDK — confirmed stable across 0.61.0 → 0.97.0
from anthropic import AsyncAnthropic, RateLimitError, APIStatusError   # claude.py:17,75
from anthropic.types import Message, MessageStreamEvent                # claude.py:18

# claude-agent-sdk — to be added (NEW imports introduced by this spec)
from claude_agent_sdk import query, ClaudeSDKClient, ClaudeAgentOptions
from claude_agent_sdk import tool, create_sdk_mcp_server  # ← NOT used (MCP is non-goal)
from claude_agent_sdk.types import (
    AssistantMessage, UserMessage, SystemMessage, ResultMessage,
    TextBlock, ToolUseBlock, ToolResultBlock,
)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(ABC):                                       # line 231
    version: str = "0.1.0"                                       # line 233
    base_headers: Dict[str, str]                                 # line 234
    client_type: str = "generic"                                 # line 237
    client_name: str = "generic"                                 # line 238
    use_session: bool = False                                    # line 239
    _lightweight_model: Optional[str] = None                     # line 243
    BASIC_SYSTEM_PROMPT: str                                     # line 246
    def __init__(self, conversation_memory=None, preset=None,
                 tools=None, use_tools=False, debug=True,
                 tool_manager=None, **kwargs): ...               # line 261
    @property
    def client(self) -> Optional[Any]: ...                       # line 332
    async def _ensure_client(self, **hints) -> Any: ...          # line 410
    def _is_capacity_error(self, error: Exception) -> bool: ...  # line 575
    def _should_use_fallback(self, model, error) -> bool: ...    # line 589
    @abstractmethod
    async def get_client(self) -> Any: ...                       # line 603
    @abstractmethod
    async def ask(self, prompt, model, max_tokens=4096,
                  temperature=0.7, files=None, system_prompt=None,
                  structured_output=None, user_id=None,
                  session_id=None, tools=None, use_tools=None,
                  deep_research=False, background=False,
                  lazy_loading=False) -> MessageResponse: ...    # line 1227
    @abstractmethod
    async def ask_stream(self, prompt, model=None, …) -> AsyncIterator[str]: ...
                                                                 # line 1265
    @abstractmethod
    async def resume(self, session_id, user_input, state) -> MessageResponse: ...
                                                                 # line 1284
    async def batch_ask(self, requests) -> List[Any]:            # line 1301 (NOT abstract)
        raise NotImplementedError("Subclasses must implement batch processing.")
    @abstractmethod
    async def invoke(self, prompt, *, output_type=None,
                     structured_output=None, model=None,
                     system_prompt=None, max_tokens=4096,
                     temperature=0.0, use_tools=False,
                     tools=None) -> InvokeResult: ...            # line 1306

# packages/ai-parrot/src/parrot/clients/claude.py
class AnthropicClient(AbstractClient):                           # line 40
    version: str = "2023-06-01"                                  # line 42
    client_type: str = "anthropic"                               # line 43
    client_name: str = "claude"                                  # line 44
    use_session: bool = False                                    # line 45
    _default_model: str = "claude-sonnet-4-5"                    # line 46
    _fallback_model: str = "claude-sonnet-4.5"                   # line 47
    _lightweight_model: str = "claude-haiku-4-5-20251001"        # line 48
    def __init__(self, api_key=None, base_url="https://api.anthropic.com",
                 **kwargs): ...                                  # line 50
    async def get_client(self) -> AsyncAnthropic: ...            # line 66
    def _is_capacity_error(self, error) -> bool: ...             # line 73
    async def ask(self, prompt, …, context_1m=False) -> AIMessage: ...
                                                                 # line 82
    async def resume(self, session_id, user_input, state) -> AIMessage: ...
                                                                 # line 349
    async def ask_stream(self, prompt, …) -> AsyncIterator[str]: ... # line 456
    async def batch_ask(self, requests, context_1m=False) -> List[AIMessage]: ...
                                                                 # line 627
    async def ask_to_image(self, prompt, image, …) -> AIMessage: ... # line 749
    async def summarize_text(self, text, …) -> AIMessage: ...    # line 959
    async def translate_text(self, text, target_lang, …) -> AIMessage: ...
                                                                 # line 1035
    async def extract_key_points(self, text, num_points=5, …) -> AIMessage: ...
                                                                 # line 1124
    async def analyze_sentiment(self, text, …) -> AIMessage: ... # line 1188
    async def analyze_product_review(self, review_text, …) -> AIMessage: ...
                                                                 # line 1294
    async def invoke(self, prompt, *, output_type=None, …) -> InvokeResult: ...
                                                                 # line 1361
ClaudeClient = AnthropicClient                                   # line 1460 (alias)

# packages/ai-parrot/src/parrot/clients/factory.py
SUPPORTED_CLIENTS: dict = {"claude": AnthropicClient,
                           "anthropic": AnthropicClient, …}      # line 19
def _lazy_gemma4(): …                                            # line 14 (pattern to copy)

class LLMFactory:                                                # line 38
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]: # line 48
    @staticmethod
    def create(llm, model_args=None, tool_manager=None,
               **kwargs) -> AbstractClient: ...                  # line 70

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessageFactory:                                          # (within file)
    @staticmethod
    def from_claude(response: Dict[str, Any], input_text: str,
                    model: str, user_id=None, session_id=None,
                    turn_id=None, structured_output=None,
                    tool_calls=None) -> AIMessage: ...           # line 572

# packages/ai-parrot/src/parrot/models/claude.py
class ClaudeModel(Enum):                                         # line 4
    OPUS_4_6     = "claude-opus-4-6"                             # line 13
    SONNET_4_6   = "claude-sonnet-4-6"                           # line 14
    OPUS_4_5     = "claude-opus-4-5-20251101"                    # line 17
    HAIKU_4_5    = "claude-haiku-4-5-20251001"                   # line 18
    SONNET_4_5   = "claude-sonnet-4-5-20250929"                  # line 19
    OPUS_4_1     = "claude-opus-4-1-20250805"                    # line 22
    SONNET_4     = "claude-sonnet-4-20250514"                    # line 24
    SONNET_3_7   = "claude-3-7-sonnet-20250219"                  # line 27
    HAIKU_3_5    = "claude-3-5-haiku-20241022"                   # line 28
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ClaudeAgentClient` | `AbstractClient.__init__` | inherited `super().__init__(**kwargs)` | `clients/base.py:261` |
| `ClaudeAgentClient.get_client` | `claude_agent_sdk.ClaudeSDKClient` | direct instantiation inside method | upstream API |
| `ClaudeAgentClient.ask` | `AIMessageFactory.from_claude_agent` (NEW) | static call | `models/responses.py` (to add) |
| `LLMFactory.SUPPORTED_CLIENTS["claude-agent"]` | `_lazy_claude_agent` (NEW) | callable factory | `clients/factory.py:14` (pattern) |
| `pyproject [claude-agent]` extra | top-level `pyproject.toml` re-export | `claude-agent = ["ai-parrot[claude-agent]"]` | `pyproject.toml:24` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AbstractClient.complete_async`~~ — does not exist; the base method is `complete` (`base.py:627`).
- ~~`anthropic.AsyncAnthropic.responses`~~ — there is no `responses` namespace; we use `messages.create`, `messages.stream`, `messages.batches`.
- ~~`from anthropic.types import StreamEvent`~~ — the actual type is `MessageStreamEvent` (`claude.py:18`).
- ~~`claude_agent_sdk.ClaudeClient`~~ — the class is `ClaudeSDKClient`. There is no `ClaudeClient` exported.
- ~~`claude_agent_sdk.AsyncClaude`~~ — does not exist.
- ~~`claude_agent_sdk.options`~~ submodule — options are imported as `from claude_agent_sdk import ClaudeAgentOptions` (top-level).
- ~~`claude_agent_sdk.batch`~~ — there is no batch primitive in the agent SDK.
- ~~`AIMessageFactory.from_anthropic`~~ — the existing factory method is `from_claude` (`models/responses.py:572`). We will mirror it as `from_claude_agent` (NOT `from_anthropic_sdk` or `from_agent_sdk`).
- ~~`parrot.clients.ClaudeAgentClient` re-export from `clients/__init__.py`~~ — we deliberately do **not** re-export to keep `claude_agent_sdk` lazy.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Per-loop client cache**: Use the inherited `AbstractClient._ensure_client()` machinery (`base.py:410`). Implement `get_client()` returning the SDK client; do not assign `self.client = …` directly (it raises `AttributeError`, see `base.py:362`).
- **Lazy import of optional deps**: Mirror `_lazy_gemma4` (`factory.py:14`). Inside `ClaudeAgentClient` methods, do `from claude_agent_sdk import …` at function scope, never at module scope. Surface a clear `ImportError("Install with: pip install ai-parrot[claude-agent]")` when the import fails.
- **AIMessage construction**: Always go through `AIMessageFactory.from_claude_agent` (new). Do not construct `AIMessage` ad-hoc — the factory normalizes provider, usage, stop_reason, raw_response.
- **Logger**: Use `self.logger` (configured in `AbstractClient.__init__` at `base.py:298`). No `print`.
- **Pydantic models**: `ClaudeAgentRunOptions` is a `BaseModel`, not a `dataclass`, for parity with `BatchRequest` upgrade trajectory and registry round-tripping.
- **Pin style**: Use `>=0.97.0,<1.0.0` for `anthropic` (allow patch + minor within the 0.x series) and `>=0.1.68` for `claude-agent-sdk` (drop the `!=0.1.49` exclusion since 0.1.68 already moves past it).

### Known Risks / Gotchas

- **R1 — Hidden API drift in `anthropic` 0.62 → 0.97**. Changelog lists only Python 3.8 drop and a query-param `array_format` change as breaking. Mitigation: run the existing `tests/clients/test_anthropic_*.py` suite against the new pin before merging Module 1; do not skip Module 2.
- **R2 — `claude_agent_sdk` requires the `claude` CLI at runtime**. The package bundles a CLI, but Docker images that strip `node_modules` / use minimal base images may break it. Mitigation: document the constraint in the README; the example must include a CLI-availability check.
- **R3 — `claude-agent-sdk` versions `<0.1.49` had a bug excluded by the existing `!=0.1.49` marker (`pyproject.toml:347`). This spec replaces both pin entries with `>=0.1.68`, which already moves past the excluded version. Verify no consumer pins `claude-agent-sdk` separately.
- **R4 — Subprocess auth**. `claude-agent-sdk` uses CLI auth, *not* `ANTHROPIC_API_KEY` directly. CI environments need `claude auth` to have been run, or `ANTHROPIC_API_KEY` set as fallback (CLI honors it). The integration test must be marked `@pytest.mark.live` and skipped when neither is available.
- **R5 — Mixed message-type vocab**. `anthropic.types.Message` and `claude_agent_sdk.types.AssistantMessage` are different shapes. Do **not** unify them; convert at the factory boundary.
- **R6 — Factory-time ImportError vs runtime**. `LLMFactory.create("claude-agent")` calls `_lazy_claude_agent()` which imports the SDK. If the user requests it without the extra, the error must come at `create()` time with an actionable hint, not later at `client.ask()` time with a confusing `ModuleNotFoundError`.
- **R7 — Extras restructure can break existing installs**. Some downstream consumers may currently install `ai-parrot[anthropic]` and rely on `claude-agent-sdk` coming with it. Module 6 removes that side effect. Mitigation: announce the change in the changelog of the next release; the `llms` umbrella keeps the convenience.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `anthropic[aiohttp]` | `>=0.97.0,<1.0.0` | Latest 0.x, supports current beta headers and model constants. Currently at `0.61.0`. |
| `claude-agent-sdk` | `>=0.1.68` | Wraps `claude` CLI for `ClaudeAgentClient`. Already declared (older range) at `pyproject.toml:347,371`; this spec moves it to a dedicated `claude-agent` extra. |
| `pydantic` | `>=2.0` (already pinned via parent) | `ClaudeAgentRunOptions` model. |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (sequential tasks in one worktree).
- The two tracks (SDK upgrade + new client) are technically independent
  but small enough that the overhead of two worktrees outweighs the
  parallelism benefit. Recommended single worktree:

  ```bash
  git worktree add -b feat-124-claude-sdk-migration \
    .claude/worktrees/feat-124-claude-sdk-migration HEAD
  ```

- **Cross-feature dependencies**: none. The closest related branch is
  the recent FEAT-123 fileinterface migration (already merged into `dev`
  at `c274f55f`); this spec does not interact with that work.
- **Task ordering inside the worktree** (proposed):
  1. Module 1 (pin bump) → Module 2 (regression tests) — Track A complete.
  2. Module 4 (factory method) → Module 3 (client) → Module 5 (registration) → Module 7 (tests) → Module 6 (extras restructure) → Module 8 (example/docs) — Track B complete.

---

## 8. Open Questions

- [x] Should `ClaudeAgentClient` inherit `AbstractClient` or sit outside the client hierarchy? — *Resolved by /sdd-spec clarification (2026-04-27)*: inherit `AbstractClient`. Methods that have no SDK equivalent (`batch_ask`, `ask_to_image`, the analytic helpers) raise `NotImplementedError` with a redirect message to `AnthropicClient`. Rationale: the user explicitly framed the use case as *"ai-parrot agents dispatching tasks to Claude Code agents"* — that requires plug-in compatibility with the agent registry and `LLMFactory`.
- [x] Should `claude-agent-sdk` ship in the base install or as an extra? — *Resolved by /sdd-spec clarification (2026-04-27)*: dedicated `[claude-agent]` extra, not bundled with `[anthropic]`. Rationale: deployment-environment limitations (the bundled CLI is heavyweight; not all consumers want it).
- [x] Should this spec also migrate `parrot/integrations/mcp/` to `claude-agent-sdk`'s in-process MCP server? — *Resolved by /sdd-spec clarification (2026-04-27)*: explicitly **out of scope**. Track separately.
- [ ] Which `permission_mode` default should `ClaudeAgentClient` use? `default` is safest; `acceptEdits` matches our autonomous `sdd-worker` pattern but is risky as a library default. — *Owner: Jesus*. *Decidable during implementation; not a blocker for the spec.*
- [ ] Should `ClaudeAgentClient.invoke` (lightweight stateless) override `permission_mode='plan'` to forbid file writes for one-shot extractions? — *Owner: Jesus*. *Decidable during implementation.*
- [ ] Is there a Compose / Docker base image where the bundled `claude` CLI from `claude-agent-sdk` is **known not to work**? If yes, document it in the README. — *Owner: Jesus*.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-27 | Jesus Lara | Initial draft from /sdd-spec scaffold (no prior brainstorm). Carries forward four user clarifications: (a)+(c) scope, extras-only install, MCP out of scope, AbstractClient inheritance. |
