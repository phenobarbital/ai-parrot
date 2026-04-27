# TASK-858: ClaudeAgentClient Core Implementation

**Feature**: FEAT-124 — Claude SDK Migration & ClaudeAgentClient
**Spec**: `sdd/specs/claude-sdk-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-857
**Assigned-to**: unassigned

---

## Context

> Spec Module 3. This is the central deliverable: a new `ClaudeAgentClient` that
> inherits `AbstractClient` and wraps `claude-agent-sdk` to dispatch tasks to a
> Claude Code agent as a subprocess. It enables ai-parrot agents to delegate
> file-aware, bash-capable, tool-using work to Claude Code sub-agents.

---

## Scope

- Create `packages/ai-parrot/src/parrot/clients/claude_agent.py` (new file).
- Implement `ClaudeAgentClient(AbstractClient)` with:
  - `get_client()` → returns `claude_agent_sdk.ClaudeSDKClient`
  - `ask()` → runs one-shot `query()`, assembles result via `AIMessageFactory.from_claude_agent`
  - `ask_stream()` → yields text blocks incrementally as SDK streams
  - `invoke()` → stateless structured output (schema-in-prompt)
  - `resume()` → continues a session using session ID
  - `batch_ask()` → raises `NotImplementedError` with redirect to `AnthropicClient`
  - `ask_to_image()`, `summarize_text()`, `translate_text()`, etc. → raise `NotImplementedError`
- Define `ClaudeAgentRunOptions(BaseModel)` pydantic model in the same file.
- Lazy-import `claude_agent_sdk` inside methods — never at module scope.
- Use `self.logger` for all logging.

**NOT in scope**: factory registration (TASK-859), pyproject extras (TASK-860),
unit tests (TASK-861), example/docs (TASK-862).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/claude_agent.py` | CREATE | Full `ClaudeAgentClient` implementation |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports
```python
# Existing — use these verbatim
from parrot.clients.base import AbstractClient                    # base.py:231
from parrot.models import (                                       # models/__init__.py
    AIMessage, AIMessageFactory, ToolCall, CompletionUsage,
)
from parrot.models.responses import InvokeResult                  # responses.py:1009
from parrot.models.claude import ClaudeModel                      # models/claude.py:4
from parrot.exceptions import InvokeError                         # exceptions module

# claude-agent-sdk — LAZY import inside methods only
from claude_agent_sdk import query, ClaudeSDKClient, ClaudeAgentOptions
from claude_agent_sdk.types import (
    AssistantMessage, UserMessage, SystemMessage, ResultMessage,
    TextBlock, ToolUseBlock, ToolResultBlock,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(ABC):                                       # line 231
    client_type: str = "generic"                                 # line 237
    client_name: str = "generic"                                 # line 238
    use_session: bool = False                                    # line 239
    _lightweight_model: Optional[str] = None                     # line 243

    def __init__(self, conversation_memory=None, preset=None,
                 tools=None, use_tools=False, debug=True,
                 tool_manager=None, **kwargs): ...               # line 261
    @property
    def client(self) -> Optional[Any]: ...                       # line 332
    async def _ensure_client(self, **hints) -> Any: ...          # line 410
    def _is_capacity_error(self, error) -> bool: ...             # line 575
    @abstractmethod
    async def get_client(self) -> Any: ...                       # line 604
    @abstractmethod
    async def ask(self, prompt, model, max_tokens=4096,
                  temperature=0.7, ...) -> MessageResponse: ...  # line 1227
    @abstractmethod
    async def ask_stream(self, prompt, model=None, …): ...       # line 1265
    @abstractmethod
    async def resume(self, session_id, user_input, state): ...   # line 1284
    async def batch_ask(self, requests) -> List[Any]:            # line 1301 (NOT abstract)
        raise NotImplementedError(...)
    @abstractmethod
    async def invoke(self, prompt, *, output_type=None, ...): ...# line 1306

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessageFactory:                                          # line 383
    @staticmethod
    def from_claude_agent(messages, input_text, model, ...): ... # TASK-857 adds this

# packages/ai-parrot/src/parrot/clients/claude.py — reference for pattern
class AnthropicClient(AbstractClient):                           # line 40
    client_type: str = "anthropic"                               # line 43
    client_name: str = "claude"                                  # line 44
    _default_model: str = 'claude-sonnet-4-5'                    # line 46
    def __init__(self, api_key=None, base_url=..., **kwargs):
        super().__init__(**kwargs)                                # line 64
    async def get_client(self) -> AsyncAnthropic: ...            # line 66
```

### Does NOT Exist
- ~~`AbstractClient.complete_async`~~ — does not exist; method is `ask` (line 1227)
- ~~`claude_agent_sdk.ClaudeClient`~~ — the class is `ClaudeSDKClient`
- ~~`claude_agent_sdk.AsyncClaude`~~ — does not exist
- ~~`claude_agent_sdk.options`~~ submodule — options are `from claude_agent_sdk import ClaudeAgentOptions`
- ~~`claude_agent_sdk.batch`~~ — no batch primitive in the agent SDK
- ~~`parrot.clients.ClaudeAgentClient` re-export from `clients/__init__.py`~~ — deliberately NOT re-exported

---

## Implementation Notes

### Pattern to Follow
```python
# Mirror AnthropicClient structure (claude.py:40-64)
class ClaudeAgentClient(AbstractClient):
    client_type: str = "claude_agent"
    client_name: str = "claude-agent"
    use_session: bool = False
    _default_model: str = "claude-sonnet-4-6"
    _lightweight_model: str = "claude-haiku-4-5-20251001"

    def __init__(self, cli_path=None, **kwargs):
        self.cli_path = cli_path
        self.base_headers = {}  # no HTTP headers for subprocess transport
        super().__init__(**kwargs)

    async def get_client(self):
        from claude_agent_sdk import ClaudeSDKClient
        return ClaudeSDKClient(cli_path=self.cli_path)
```

### Key Constraints
- Use `_ensure_client()` machinery (base.py:410) — do NOT assign `self.client = ...` directly
- Lazy-import `claude_agent_sdk` inside every method that uses it
- Surface clear `ImportError("Install with: pip install ai-parrot[claude-agent]")` when import fails
- `ask()` should call `query()` (sync SDK function) wrapped in `asyncio.to_thread` or
  `loop.run_in_executor` to avoid blocking the event loop
- `ask_stream()` should yield text incrementally as `TextBlock` events arrive
- `resume()` takes a `session_id` and uses `ClaudeSDKClient` to continue a conversation
- `batch_ask()` raises `NotImplementedError` with message mentioning `AnthropicClient`
- All unsupported methods (`ask_to_image`, `summarize_text`, etc.) raise `NotImplementedError`
- `provider` for `AIMessage` construction: `"claude-agent"` (distinct from `"claude"`)

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/claude.py` — full pattern reference
- `packages/ai-parrot/src/parrot/clients/base.py:231-604` — abstract interface
- `packages/ai-parrot/src/parrot/models/responses.py:572-606` — `from_claude` pattern

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/clients/claude_agent.py` exists
- [ ] `ClaudeAgentClient` inherits `AbstractClient`
- [ ] `get_client()` returns `ClaudeSDKClient` (lazy imported)
- [ ] `ask()` calls `query()` and returns `AIMessage` via `AIMessageFactory.from_claude_agent`
- [ ] `ask_stream()` yields text strings incrementally
- [ ] `invoke()` works for stateless structured output
- [ ] `resume()` continues a session
- [ ] `batch_ask()` raises `NotImplementedError` mentioning `AnthropicClient`
- [ ] `ClaudeAgentRunOptions` pydantic model is defined
- [ ] No module-level import of `claude_agent_sdk`
- [ ] `from parrot.clients import AbstractClient` works without `[claude-agent]` extra

---

## Test Specification

```python
# Basic smoke — full tests are in TASK-861
# Verify the class can be imported and instantiated without claude_agent_sdk
# at import time (lazy import check)
def test_claude_agent_client_importable():
    from parrot.clients.claude_agent import ClaudeAgentClient
    assert ClaudeAgentClient.client_type == "claude_agent"

def test_claude_agent_run_options():
    from parrot.clients.claude_agent import ClaudeAgentRunOptions
    opts = ClaudeAgentRunOptions(allowed_tools=["Read", "Bash"], cwd="/tmp")
    assert opts.allowed_tools == ["Read", "Bash"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-857 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `AbstractClient` signatures, `AIMessageFactory.from_claude_agent` exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** the `ClaudeAgentClient` class
6. **Verify** basic import and instantiation works
7. **Move this file** to `tasks/completed/TASK-858-claude-agent-client-core.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (FEAT-124 autonomous run)
**Date**: 2026-04-27
**Notes**:
Created `packages/ai-parrot/src/parrot/clients/claude_agent.py` containing:
- `ClaudeAgentRunOptions(BaseModel)` — typed mirror of the most useful subset
  of `claude_agent_sdk.ClaudeAgentOptions` (allowed/disallowed tools, cwd,
  cli_path, permission_mode, system_prompt, model, max_turns / max_budget_usd,
  add_dirs, env, plus an `extra_options` escape hatch).
- `ClaudeAgentClient(AbstractClient)` with class-level identifiers
  `client_type="claude_agent"`, `client_name="claude-agent"`,
  `_default_model="claude-sonnet-4-6"`,
  `_lightweight_model="claude-haiku-4-5-20251001"`.
- `get_client()` builds a fresh `claude_agent_sdk.ClaudeSDKClient` (with
  default options) — caching is delegated to the inherited `_ensure_client`.
- `ask()` collects the entire `claude_agent_sdk.query()` message stream and
  hands it to `AIMessageFactory.from_claude_agent` (added in TASK-857).
- `ask_stream()` yields `TextBlock.text` chunks incrementally as
  `AssistantMessage` events arrive from `query()`.
- `invoke()` produces a stateless structured-output extraction by
  embedding the JSON schema in the prompt and parsing the assistant text
  with `_parse_structured_output`. Defaults `permission_mode="plan"` so
  invoke can never mutate the filesystem (resolving spec Open Question 5).
- `resume()` re-runs `query()` with `ClaudeAgentOptions.resume = session_id`.
- `batch_ask()` raises `NotImplementedError` with a redirect to
  `AnthropicClient` per spec.
- `ask_to_image`, `summarize_text`, `translate_text`, `analyze_sentiment`,
  `analyze_product_review`, `extract_key_points` all raise
  `NotImplementedError` with redirect messages.
- `claude_agent_sdk` is **never** imported at module scope; every method
  that uses the SDK calls `_import_sdk()` (or imports inside the function
  body) and surfaces `ImportError("Install with: pip install
  ai-parrot[claude-agent]")` when the optional extra is missing.
- Verified: `from parrot.clients.claude_agent import ClaudeAgentClient,
  ClaudeAgentRunOptions` succeeds without `claude_agent_sdk` being eagerly
  loaded into `sys.modules`.

**Deviations from spec**:
- The spec sketch in §2 of the parent feature spec defines
  `ClaudeAgentRunOptions` with seven fields; the implementation expands
  this to include `max_turns`, `max_budget_usd`, `model`,
  `fallback_model`, `add_dirs`, `env`, and `extra_options`. These are
  additive, fully-optional, and pass through to `ClaudeAgentOptions`
  unchanged — they make the typed surface useful for real agent dispatch
  scenarios (the SDK's actual `ClaudeAgentOptions` has ~30 fields).
- Per spec Open Question 5, `invoke()` defaults to `permission_mode="plan"`
  so a stateless extraction can never mutate the filesystem. Callers can
  override by passing `run_options.permission_mode`.
