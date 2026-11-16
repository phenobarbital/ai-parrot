---
type: feature
base_branch: dev
projects: [clients]
tags: [clients, groq, streaming, tool-loop]
docs:
  policy: required
  pages:
    - wiki/clients/abstract-client.md
  api_modules:
    - parrot.clients.groq.client
---

# Feature Specification: GroqClient fixes — streaming tool loop and default model

**Feature ID**: FEAT-896
**Date**: 2026-11-14
**Author**: Jesus Lara (via /sdd-fix, Claude Code)
**Status**: draft
**Target version**: next ai-parrot-client-groq release

---

## 1. Motivation & Business Requirements

### Problem Statement

Two open ledger issues against `GroqClient` (`packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py`),
drained by `/sdd-fix` as group `fixgroup:5d7789463a44`:

1. **`issue:3e76568cae48` (bug, major) — `ask_stream()` drops the model's tool calls.** `ask_stream()`
   registers tools and sends them with `tool_choice="auto"` (`client.py:797-806`) but iterates only
   `chunk.choices[0].delta.content` (`client.py:820-838`). Tool-call deltas are discarded and never
   executed, so when the model decides to call a tool the stream yields no text and the final
   `AIMessage` has an empty `output`. The code says so itself: *"For streaming, we don't handle tools in
   this version"* (`client.py:797`). FEAT-848 decided not to add a streaming capability flag and to fix
   the provider instead.

   Found while writing this spec: `ask_stream()` has no `use_tools` parameter and no `**kwargs`
   (`client.py:740-754`), but `BaseBot.ask_stream()` always passes `use_tools=` to `client.ask_stream()`
   (`bots/base.py:2150-2157`, call at `:2243`). Binding those kwargs to `GroqClient.ask_stream` raises
   `TypeError: got an unexpected keyword argument 'use_tools'`, so **every bot that streams through Groq
   fails before any request is sent**, with or without tools.

2. **`issue:9e15f2e959fe` (bug, minor) — the hardcoded default model returns 404.** `ask()`,
   `ask_stream()` and `summarize_text()` default `model=GroqModel.LLAMA_3_3_70B_VERSATILE`
   (`client.py:336`, `:743`, `:1010`). The FEAT-746 G3 live run got *"The model
   `llama-3.3-70b-versatile` does not exist or you do not have access to it."* (404), while
   `openai/gpt-oss-120b` works. The hardcoded default also ignores the model the client was
   configured with (`GroqClient(model=...)` sets `self.model`, `base.py:470`) and, when a caller passes
   `model=None` explicitly (as `BaseBot` does when it has no `_llm_model`), `None` is sent on the wire.

### Goals
- `GroqClient.ask_stream()` runs the tool loop that `ask()` runs: accumulate streamed tool-call deltas,
  execute the tools, feed the results back, and keep streaming the model's text in the next round.
- `GroqClient.ask_stream()` accepts every keyword `BaseBot.ask_stream()` sends (`use_tools`, and any
  extra keyword via `**kwargs`), so bot-driven Groq streaming works.
- `ask()`, `ask_stream()` and `summarize_text()` resolve their model as explicit > configured
  (`self.model`) > class default (`_default_model = "openai/gpt-oss-120b"`), never a hardcoded
  `llama-3.3-70b-versatile` and never `None`.
- Repair the two already-failing tests in `packages/ai-parrot/tests/test_groq_client.py`.
- Remove Groq from the "ask_stream skips the tool loop" known-gaps list in `wiki/clients/abstract-client.md`.

### Non-Goals (explicitly out of scope)
- Grok (`issue:2d16e4d75557`) and Meta Responses (`issue:3a0ea22ce45a`) streaming tool gaps — separate issues.
- Replacing Groq's `ask_stream()` with the inherited `OpenAIBaseClient.ask_stream()`: that would also
  change file handling (`_upload_file`), usage parsing (`from_openai` drops Groq timing fields), tool-schema
  normalization (`_fix_schema_for_groq`) and drop the per-chunk `ClientStreamChunkEvent`.
- Structured output while streaming (Groq does not support it; see §7).
- Removing `GroqModel.LLAMA_3_3_70B_VERSATILE` from the enum, or changing other defaults
  (`analyze_sentiment`/`analyze_product_review` → `KIMI_K2_INSTRUCT`, `_lightweight_model`, the
  structured-output fallback to `LLAMA_4_SCOUT_17B` at `client.py:399`) — none is reported broken.
- `ClientRoundEvent` emission from the streaming path (`OpenAIBaseClient.ask_stream` emits none either).
- Groq streaming usage location (`chunk.usage` vs `x_groq.usage`) — kept as today.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:ffe74a236c20b31f973e2457f92c17c6ac90da78833f625072977ae86630e9e7 evaluation_digest=sha256:049970a6d163eb9c8196e382dbcd1a5db5b31e7d5e1d425250507048c415553f rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Two changes, both confined to `GroqClient` (plus its tests and one wiki page):

**A. Model resolution (issue `9e15f2e959fe`).** `ask()`, `ask_stream()` and `summarize_text()` take
`model: Optional[Union[GroqModel, str]] = None` and resolve it with the inherited
`OpenAIBaseClient._resolve_model()` (`openai_base.py:184-201`): explicit argument > `self.model` (the
constructor's `model=`, `base.py:470`) > `self.default_model` → `_default_model = "openai/gpt-oss-120b"`
(`groq/client.py:89`). `_normalize_model()` already unwraps an `Enum` to its `.value`, so callers that pass
`GroqModel.X` keep working. The misleading class attribute `model: str = GroqModel.LLAMA_3_3_70B_VERSATILE`
(`client.py:88`, always shadowed by the instance attribute `AbstractClient.__init__` sets) becomes
`model: Optional[str] = None`. `GroqModel.LLAMA_3_3_70B_VERSATILE` stays in the enum.

**B. Streaming tool loop (issue `3e76568cae48`).** `GroqClient.ask_stream()` keeps its own implementation
(Groq specifics stay: `_prepare_groq_tools()`, `CompletionUsage.from_groq`, `top_p`, the per-chunk
`ClientStreamChunkEvent`) and gains the loop `OpenAIBaseClient.ask_stream()` already runs
(`openai_base.py:1342-1529`), with round semantics taken from Groq's own `ask()` (`client.py:486-618`):

1. **Signature.** Adds `use_tools: Optional[bool] = None` and `**kwargs`. `use_tools=None` resolves to
   `self.enable_tools or bool(tools)` (inline `tools=` imply use, since `register_tool()` does not set
   `enable_tools`, `base.py:1478-1489`). Extra keywords are accepted and ignored. When `structured_output`
   is among them and truthy, log one warning: Groq does not support structured output while streaming
   (`groq/models.py` docstring), so no `response_format` is sent.
2. **Round loop.** Up to `max_turns = 10` rounds (the same cap as `ask()`, `client.py:490`). Each round
   calls `self._chat_completion(..., stream=True)` and iterates the stream:
   - `delta.content` text is yielded at once, appended to the round text and the total text, and fires a
     `ClientStreamChunkEvent` (the chunk index keeps counting across rounds);
   - `delta.tool_calls` fragments are merged by `index` (the first fragment carries `id` + `function.name`,
     later ones append `function.arguments`) by the new static helper `_accumulate_tool_call_deltas()`;
   - `choice.finish_reason` and `chunk.usage` are captured.
3. **Tool round.** If tool calls accumulated and `finish_reason in ("tool_calls", "stop")`, the new helper
   `_execute_streamed_tool_calls()` appends one assistant message with `tool_calls` (OpenAI wire shape,
   `content` = the round text or `""`), parses each call's arguments (`self._json.loads`, falling back to
   `json_decoder`, empty string → `{}`), executes it via `self._execute_tool(name, args)`, appends one
   `{"role": "tool", ...}` message per call, and returns the `ToolCall` records. It mirrors `ask()`'s
   error handling (`client.py:539-559`): `HumanInteractionInterrupt` gets `session_id`, `messages`,
   `tool_call_id` and `agent_name` and is re-raised; any other exception becomes `tc.error` plus an
   `"Error: ..."` tool message. Unparseable arguments are recorded as a `ToolCall` error and are not executed.
4. **Next round.** It sends `tools` + `tool_choice="auto"` (+ `parallel_tool_calls=True` except for
   `GroqModel.GEMMA2_9B_IT`, as `ask()` does) while `round < max_turns - 1`. The last allowed round sends
   `tool_choice="none"` without `tools`, as `ask()` does (`client.py:576-583`). Tool calls that arrive in the
   forced final round, or with `finish_reason == "length"`, are not executed: log a warning and stop.
5. **Finish.** A round without tool calls ends the loop. Usage is the `+`-sum of each round's
   `CompletionUsage.from_groq(...)`, with `extra_usage["rounds"]` set when there was more than one round,
   as `ask()` does at `client.py:718-721`. If no round reported usage, it is a zero `CompletionUsage`, as
   today. The final `AIMessage` carries the full streamed text as `output`/`response` and
   `tool_calls=all_tool_calls`. `_emit_before_call(has_tools=...)` reports whether tools were offered
   (today hard-coded `False`, `client.py:779`). `_emit_after_call(finish_reason=...)` reports the last
   round's finish reason. Each round's `_chat_completion` failure still goes through
   `_emit_failed_call_safe` and re-raises.

### Component Diagram
```
BaseBot.ask_stream ──(prompt, model, use_tools, temperature, history, system_prompt, **)──→ GroqClient.ask_stream
                                                                                     │
          ┌──────────────────────── round r (≤ 10) ──────────────────────────────────┤
          │  _chat_completion(stream=True) ─→ chunks ─┬─ delta.content ─→ yield str + ClientStreamChunkEvent
          │                                           ├─ delta.tool_calls ─→ _accumulate_tool_call_deltas
          │                                           └─ usage / finish_reason
          │  tool calls? ─yes→ _execute_streamed_tool_calls ─→ _execute_tool ─→ tool messages ─→ round r+1
          └─ no ─→ final AIMessage(output=all text, tool_calls, usage=Σ rounds) ─→ yield
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BaseBot.ask_stream()` | caller | passes `use_tools`, `model`, `temperature`, `history`, `system_prompt` (`bots/base.py:2150-2157`); now binds |
| `OpenAIBaseClient._resolve_model()` | uses (inherited) | explicit > `self.model` > `default_model` (`openai_base.py:184`) |
| `AbstractClient._execute_tool()` | uses | `(tool_name, parameters, tool_context=None)` (`base.py:1703`) |
| `GroqClient._chat_completion()` | uses | stream funnel, unchanged (`groq/client.py:128-151`) |
| `GroqClient._prepare_groq_tools()` | uses | Groq-normalized tool payload, unchanged (`groq/client.py:264`) |
| `budget_entry` (FEAT-550) | wraps | `__init_subclass__` wraps `ask_stream` (`base.py:330-337`); it already wraps `OpenAIBaseClient.ask_stream`, which has `**kwargs` |

### Data Models
No new models. Uses `ToolCall`, `AIMessage`, `CompletionUsage` from `parrot.models` (already imported, `groq/client.py:24-31`).

### New Public Interfaces
No new public API. The `GroqClient.ask_stream()` signature gains `use_tools` and `**kwargs`. `ask()`,
`ask_stream()` and `summarize_text()` change their `model` default to `None`.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: model resolution + stale test repair | yes | `model=None` + `self._resolve_model(model)` at the 3 sites; class attr → `Optional[str] = None`; tests via `get_client` + `_ensure_client()` | — |
| M2: streaming tool loop | yes | §2 Overview B fixes round cap, tool_choice per round, helper names and signatures, error handling and usage sum | — |

### Module 1: Groq model resolution (issue `9e15f2e959fe`)
- **Path**: `packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py`; tests
  `packages/ai-parrot-client-groq/tests/unit/test_groq_default_model.py` (new) and
  `packages/ai-parrot/tests/test_groq_client.py` (repair).
- **Responsibility**: Resolve the model as explicit > configured > `_default_model` in `ask()`,
  `ask_stream()` and `summarize_text()`. Make the class attribute honest. Repair the two failing tests in
  `test_groq_client.py`, which patch a module attribute that does not exist (`parrot.clients.groq.client.AsyncGroq`)
  and assign the read-only `client.client` property. Mock with
  `client.get_client = AsyncMock(return_value=sdk_mock)` + `await client._ensure_client()`, as
  `test_groq_multiround_usage.py:84-96` does. Give the stream chunks an explicit `delta.tool_calls = None`
  and `finish_reason`, and the response mocks real `usage` numbers.
- **Depends on**: existing `OpenAIBaseClient._resolve_model`.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py
  class GroqClient(OpenAIBaseClient):  # verified: groq/client.py:52
      model: Optional[str] = None  # was GroqModel.LLAMA_3_3_70B_VERSATILE — verified: groq/client.py:88
      _default_model: str = "openai/gpt-oss-120b"  # unchanged — verified: groq/client.py:89

      async def ask(self, prompt: str, model: Optional[Union[GroqModel, str]] = None, ...) -> AIMessage:  # verified: :333-347
          """... model: explicit > self.model > _default_model (via self._resolve_model)."""

      async def ask_stream(self, prompt: str, model: Optional[Union[GroqModel, str]] = None, ...):  # verified: :740-754
          """(M2 extends this signature further.)"""

      async def summarize_text(self, text: str, model: Optional[Union[GroqModel, str]] = None, ...) -> AIMessage:  # verified: :1007-1016
          """... same resolution."""
  ```
  In each body, `model = model.value if isinstance(model, GroqModel) else model` (`:350`, `:764`, `:1037`)
  becomes `model = self._resolve_model(model)`. The same line at `:1110`/`:1233` (`analyze_*`, KIMI default)
  is NOT changed.

### Module 2: Groq streaming tool loop (issue `3e76568cae48`)
- **Path**: `packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py`; tests
  `packages/ai-parrot-client-groq/tests/unit/test_groq_ask_stream_tools.py` (new); docs
  `wiki/clients/abstract-client.md` (update).
- **Responsibility**: §2 Overview B. Remove Groq from the two "ask_stream skips the tool loop" known-gap
  sentences in `wiki/clients/abstract-client.md` (`:155`, `:279-280`); Grok and Meta stay listed.
- **Depends on**: Module 1 (same file; `ask_stream()`'s model resolution is M1's).
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py
  class GroqClient(OpenAIBaseClient):
      async def ask_stream(  # verified: groq/client.py:740
          self,
          prompt: str,
          model: Optional[Union[GroqModel, str]] = None,
          max_tokens: Optional[int] = None,
          temperature: float = 0.1,
          top_p: float = 0.9,
          files: Optional[List[Union[str, Path]]] = None,
          system_prompt: Optional[str] = None,
          history: Optional[Sequence[HistoryMessage]] = None,
          tools: Optional[List[dict]] = None,
          use_tools: Optional[bool] = None,
          deep_research: bool = False,
          agent_config: Optional[dict] = None,
          lazy_loading: bool = False,
          **kwargs: Any,
      ) -> AsyncIterator[Union[str, AIMessage]]:
          """Stream Groq's response, running the tool loop between rounds.

          Yields text chunks as they arrive (across all rounds), then one final AIMessage whose
          output is the full streamed text and whose tool_calls lists every executed ToolCall.
          use_tools=None → self.enable_tools or bool(tools). Extra kwargs are accepted and ignored;
          a truthy structured_output logs a warning (unsupported while streaming).
          Raises HumanInteractionInterrupt from a tool (with session/messages/tool_call_id set) and
          any _chat_completion error (after _emit_failed_call_safe).
          """

      @staticmethod
      def _accumulate_tool_call_deltas(
          accum: dict[int, dict[str, str]], deltas: Optional[Sequence[Any]]
      ) -> None:
          """Merge one chunk's delta.tool_calls into accum keyed by .index: {"id", "name", "arguments"};
          id/name are set when present, arguments fragments are concatenated. No-op for None/empty."""

      async def _execute_streamed_tool_calls(
          self, accum: dict[int, dict[str, str]], round_text: str, messages: list[dict], model: str
      ) -> list[ToolCall]:
          """Append the assistant tool_calls message and one tool message per call (sorted by index),
          execute each via self._execute_tool, and return the ToolCall records (result/error/
          execution_time set). Re-raises HumanInteractionInterrupt after annotating it."""
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_ask_defaults_to_class_default_model` | M1 | no model configured or passed → request `model == "openai/gpt-oss-120b"` |
| `test_ask_uses_configured_model` | M1 | `GroqClient(model="qwen/qwen3-32b")` → request uses it |
| `test_ask_explicit_model_wins_and_enum_unwrapped` | M1 | explicit `GroqModel.OPENAI_GPT_OSS_20B` → `"openai/gpt-oss-20b"` |
| `test_ask_explicit_none_resolves` | M1 | `model=None` → never `None` on the wire |
| `test_ask_stream_and_summarize_default_model` | M1 | same resolution for `ask_stream()` and `summarize_text()` |
| `test_groq_ask` / `test_groq_ask_stream` (repaired) | M1 | existing tests pass with the supported mocking pattern |
| `test_stream_text_only_unchanged` | M2 | no tool deltas → text chunks + final AIMessage, one SDK call |
| `test_stream_executes_tool_call_then_streams_answer` | M2 | round 1 tool call split across 2 chunks; `_execute_tool` awaited with parsed args; round 2 messages hold the assistant `tool_calls` + tool message; final output = round-2 text; `AIMessage.tool_calls` has the result |
| `test_stream_parallel_tool_calls_by_index` | M2 | two indices accumulate independently, executed in index order |
| `test_stream_use_tools_false_sends_no_tools` | M2 | no `tools`/`tool_choice` in the request |
| `test_stream_accepts_basebot_kwargs` | M2 | the exact kwargs `BaseBot.ask_stream` sends (+ an unknown kwarg) bind and run |
| `test_stream_round_cap_forces_tool_choice_none` | M2 | a model that always calls tools → 10 SDK calls, the last with `tool_choice="none"` and no `tools` |
| `test_stream_usage_sums_rounds` | M2 | usage = sum of rounds; `extra_usage["rounds"] == 2` |
| `test_stream_tool_error_fed_back` | M2 | tool raises → `ToolCall.error` set, `"Error: ..."` tool message, loop continues |
| `test_stream_human_interrupt_propagates` | M2 | `HumanInteractionInterrupt` re-raised with `tool_call_id` and `messages` |
| `test_stream_bad_arguments_not_executed` | M2 | unparseable arguments → `ToolCall.error`, `_execute_tool` not called |

### Integration Tests
| Test | Description |
|---|---|
| `test_groq_multiround_usage.py` (existing) | `ask()` tool loop and usage accumulation unchanged (regression) |

### Validation Contract

tests:
- packages/ai-parrot-client-groq/tests/unit/test_groq_default_model.py
- packages/ai-parrot-client-groq/tests/unit/test_groq_ask_stream_tools.py
- packages/ai-parrot-client-groq/tests/unit/test_groq_multiround_usage.py
- packages/ai-parrot/tests/test_groq_client.py
markers: none

### Test Data / Fixtures
```python
# Reuse the pattern of test_groq_multiround_usage.py:84-96 — never patch AsyncGroq, never assign client.client.
async def _make_client(sdk_side_effect, **client_kwargs):
    client = GroqClient(api_key="fake_key", **client_kwargs)
    client.logger = MagicMock()
    sdk = MagicMock()
    sdk.chat.completions.create = AsyncMock(side_effect=sdk_side_effect)
    client.get_client = AsyncMock(return_value=sdk)
    await client._ensure_client()
    return client, sdk

def _chunk(content=None, tool_calls=None, finish_reason=None, usage=None):
    """Stream chunk with every field explicit (a bare MagicMock delta.tool_calls is truthy)."""

def _tc_delta(index, id=None, name=None, arguments=None):
    """One delta.tool_calls fragment."""

class _Stream:
    """Async-iterable over a fixed chunk list (returned by the mocked create())."""
```

---

## 5. Acceptance Criteria

- [ ] `GroqClient.ask_stream(prompt, model=None, temperature=0, history=None, system_prompt=..., use_tools=True)` binds and runs (no `TypeError`).
- [ ] When the model streams a tool call, `ask_stream()` executes it through `_execute_tool`, sends a next round with the assistant `tool_calls` + tool messages, streams that round's text, and the final `AIMessage.output` is non-empty and `AIMessage.tool_calls` lists the executed calls.
- [ ] `ask_stream()` runs at most 10 rounds; the last sends `tool_choice="none"`.
- [ ] `ask()`, `ask_stream()` and `summarize_text()` never send `llama-3.3-70b-versatile` unless the caller or the constructor chose it, and never send `model=None`; the default is `openai/gpt-oss-120b`.
- [ ] `ask()` behavior is otherwise unchanged (`test_groq_multiround_usage.py` passes unmodified).
- [ ] Every test in the §4 Validation Contract passes; `packages/ai-parrot/tests/test_groq_client.py` passes (2 failures on dev today).
- [ ] `ruff check` is clean on the changed files.
- [ ] `wiki/clients/abstract-client.md` no longer lists Groq as an `ask_stream()` tool-loop gap (`parrot sdd techwiki check`).
- [ ] No breaking change: positional/keyword callers of `ask`/`ask_stream`/`summarize_text` keep working; `GroqModel` keeps every member.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.clients.groq import GroqClient  # verified: used by tests/unit/test_groq_multiround_usage.py:19
from parrot.clients.groq.models import GroqModel  # verified: groq/client.py:34 (relative `.models`)
from parrot.core.events.lifecycle.events import ClientStreamChunkEvent  # verified: groq/client.py:772; class at core/events/lifecycle/events/client.py:148
from parrot.core.events.lifecycle.events import AfterClientCallEvent, ClientRoundEvent  # verified: test_groq_multiround_usage.py:20-23
from parrot.core.exceptions import HumanInteractionInterrupt  # verified: groq/client.py:540 (local import)
from parrot.models import AIMessage, ToolCall, CompletionUsage  # verified: groq/client.py:24-31 (relative)
```

### Existing Class Signatures
```python
# packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py
class GroqClient(OpenAIBaseClient):                                      # line 52
    tool_format: ToolFormat = ToolFormat.GROQ                            # line 87
    model: str = GroqModel.LLAMA_3_3_70B_VERSATILE                       # line 88 (shadowed per instance)
    _default_model: str = "openai/gpt-oss-120b"                          # line 89
    _default_max_tokens: int = 4095                                      # line 98
    async def _chat_completion(self, model, messages, use_tools=False, stream=False, **kwargs)  # line 128
    def _prepare_groq_tools(self) -> List[dict]                          # line 264
    async def ask(self, prompt, model=GroqModel.LLAMA_3_3_70B_VERSATILE, max_tokens=None, temperature=0.1,
                  top_p=0.9, files=None, system_prompt=None, history=None, structured_output=None,
                  tools=None, use_tools=None, use_code_interpreter=None) -> AIMessage   # line 333
    async def ask_stream(self, prompt, model=GroqModel.LLAMA_3_3_70B_VERSATILE, max_tokens=None,
                  temperature=0.1, top_p=0.9, files=None, system_prompt=None, history=None,
                  tools=None, deep_research=False, agent_config=None, lazy_loading=False)  # line 740
    async def resume(self, session_id, user_input, state) -> AIMessage   # line 881
    async def summarize_text(self, text, model=GroqModel.LLAMA_3_3_70B_VERSATILE, ...)   # line 1007

# packages/ai-parrot/src/parrot/clients/openai_base.py
class OpenAIBaseClient(AbstractClient):
    def _normalize_model(self, model: Any) -> str                        # line 168 (Enum → .value)
    def _resolve_model(self, model: Any | None) -> str                   # line 184 (explicit > self.model > default_model; ValueError if none)
    async def ask_stream(...)                                            # line 1229 (reference loop :1342-1529)

# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient:
    def __init__(self, preset=None, tools=None, use_tools=False, debug=True, tool_manager=None, **kwargs)  # line 460
        self.model = kwargs.get("model", None)                           # line 470
        self.enable_tools = use_tools                                    # line 542
    def default_model(self) -> str  (property)                           # line 1263
    def register_tool(self, tool=None, name=None, description=None, input_schema=None, function=None)  # line 1478 (does NOT set enable_tools)
    def register_tools(self, tools)                                      # line 1491 (sets enable_tools)
    async def _execute_tool(self, tool_name: str, parameters: Dict[str, Any], tool_context=None) -> Any  # line 1703

# packages/ai-parrot/src/parrot/models/basic.py
class CompletionUsage:
    def from_groq(cls, usage) -> "CompletionUsage"                       # line 136 (keeps completion/prompt/queue/total_time)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ask_stream` round | `GroqClient._chat_completion(stream=True)` | method call | `groq/client.py:809` |
| `_execute_streamed_tool_calls` | `AbstractClient._execute_tool` | method call | `base.py:1703` |
| model resolution | `OpenAIBaseClient._resolve_model` | inherited method | `openai_base.py:184` |
| caller | `BaseBot.ask_stream` → `client.ask_stream(**llm_kwargs)` | kwargs | `bots/base.py:2150-2157`, `:2243` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.clients.groq.client.AsyncGroq`~~ — `AsyncGroq` is imported only under `TYPE_CHECKING` and inside `get_client()`; `patch("parrot.clients.groq.client.AsyncGroq")` raises `AttributeError` (why `test_groq_client.py` fails today).
- ~~Assigning `client.client = ...`~~ — `AbstractClient.client` is a loop-local property; use `get_client` + `_ensure_client()`.
- ~~`GroqClient._accumulate_stream_tool_calls`~~ — that name exists only on `ZaiClient` (`zai/client.py:585`); Groq's new helper is `_accumulate_tool_call_deltas`.
- ~~`supports_stream_tool_loop`~~ / any streaming capability flag — rejected by FEAT-848.
- ~~`GroqClient._run_tool_call_loop`~~ — `OpenAIBaseClient._run_tool_call_loop` exists (`openai_base.py:513`) but Groq's `ask()` does not use it; do not refactor `ask()` onto it here.

### Edit Sites (Blueprint Anchors)

Verified against: `9883cfa86d`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py` | MODIFY (M1) | `    model: str = GroqModel.LLAMA_3_3_70B_VERSATILE` followed by `    _default_model: str = "openai/gpt-oss-120b"` | `client.py:88-89` | 4 (anchor) / 1 (with next line) |
| `packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py` | MODIFY (M1) | `    async def ask(` … `        model: str = GroqModel.LLAMA_3_3_70B_VERSATILE,` … `        model = model.value if isinstance(model, GroqModel) else model` | `client.py:333`, `:336`, `:350` | 1 / 4 / 5 |
| `packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py` | MODIFY (M1, M2) | `    async def ask_stream(` (signature `:740-754`, model line `:764`, `has_tools=False,` `:779`, tools block `:797-806`, stream loop `async for chunk in response_stream:` `:820`, final AIMessage `:843-879`) | `client.py:740` | 1 |
| `packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py` | MODIFY (M1) | `    async def summarize_text(` … `        model = model.value if isinstance(model, GroqModel) else model` | `client.py:1007`, `:1037` | 1 / 5 |
| `packages/ai-parrot/tests/test_groq_client.py` | MODIFY (M1) | `with patch("parrot.clients.groq.client.AsyncGroq") as mock_groq_cls:` / `def mock_stream_chunk(text):` | `test_groq_client.py:11`, `:57`, `:48` | 2 / 1 |
| `packages/ai-parrot-client-groq/tests/unit/test_groq_default_model.py` | CREATE (M1) | — | — | — |
| `packages/ai-parrot-client-groq/tests/unit/test_groq_ask_stream_tools.py` | CREATE (M2) | — | — | — |
| `wiki/clients/abstract-client.md` | MODIFY (M2) | `Known gaps are tracked as ledger issues (Groq, Grok, Meta Responses API).` / ``may skip the tool loop `ask()` runs — Groq,`` | `abstract-client.md:155`, `:279` | 1 / 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Round semantics (cap 10, last round `tool_choice="none"` without `tools`, `parallel_tool_calls` except
  Gemma, argument parsing, interrupt annotation) copy Groq's own `ask()` (`client.py:486-618`); delta
  accumulation copies `OpenAIBaseClient.ask_stream()` (`openai_base.py:1426-1440`).
- Keep the lifecycle calls already in `ask_stream()` (`_emit_before_call`, `ClientStreamChunkEvent`,
  `_emit_failed_call_safe`, `_emit_after_call`).
- No memory writes (FEAT-524): `AbstractBot.save_conversation_turn` is the single writer.
- `self.logger`, Google docstrings, type hints, 120 columns, `ruff check` clean.

### Known Risks / Gotchas
- **Behavior change for `use_tools=None` direct callers:** today tools go out whenever any are registered.
  Now they go out only if `enable_tools` is set or inline `tools=` were passed. `BaseBot` always passes
  `use_tools` explicitly, so bots are unaffected.
- **Behavior change for model defaults:** a client constructed with `model=X` now uses `X` in
  `ask()`/`ask_stream()`/`summarize_text()` where it used to silently use llama-3.3. This is the fix, but
  it is a visible change.
- **Mocks:** `MagicMock().delta.tool_calls` is truthy. Every stream-chunk mock must set
  `delta.tool_calls = None` and `finish_reason`. Usage mocks need real ints (`CompletionUsage` validates).
- **Structured output while streaming** is unsupported by Groq. It is logged and ignored, never sent.
- **Groq stream usage** may arrive in `x_groq.usage` rather than `chunk.usage`. That is unchanged and out of scope.
- `parrot/clients/base.py` and `openai_base.py` are NOT modified.

### External Dependencies
None new (`groq` SDK already a dependency of `ai-parrot-client-groq`).

---

## Decisions

```yaml
schema_version: 1
document_id: groq-client-fixes
entries:
  - id: groq-ask-stream-runs-tool-loop
    statement: GroqClient.ask_stream() runs its own streaming tool loop — it accumulates delta.tool_calls by index, executes them through _execute_tool, streams the next round, caps at 10 rounds with tool_choice "none" on the last — and accepts use_tools plus extra keyword arguments; it does not delegate to OpenAIBaseClient.ask_stream().
    relation: requires
    about: [clients]
    targets:
      - file:packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py
    contradicts: []
    supersedes: []
    rationale: "Implements FEAT-848's tool-loop-flag-is-declarative decision (fix the provider, no streaming flag) while keeping Groq's tool-schema normalization, timing-aware usage and per-chunk events."
    rejected_alternatives:
      - "Inherit OpenAIBaseClient.ask_stream() — it uploads files through the OpenAI files API, parses usage with from_openai (drops Groq timing fields), skips _fix_schema_for_groq and emits no ClientStreamChunkEvent."
  - id: groq-model-resolution-chain
    statement: GroqClient ask(), ask_stream() and summarize_text() resolve their model through OpenAIBaseClient._resolve_model() (explicit, then the configured self.model, then _default_model "openai/gpt-oss-120b"); none of them hardcodes a GroqModel default.
    relation: requires
    about: [clients]
    targets:
      - file:packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py
    contradicts: []
    supersedes: []
    rationale: "llama-3.3-70b-versatile returns 404, and a hardcoded default ignored the model the client was configured with."
    rejected_alternatives:
      - "Swap the hardcoded default for another hardcoded model — repeats the failure when that model is retired and still ignores self.model."
```

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:ffe74a236c20b31f973e2457f92c17c6ac90da78833f625072977ae86630e9e7 evaluation_digest=sha256:049970a6d163eb9c8196e382dbcd1a5db5b31e7d5e1d425250507048c415553f rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- `possible-supersession` [advisory]; waived_by: not recorded; participants: adr:spec:groq-client-fixes#groq-ask-stream-runs-tool-loop@1, adr:spec:groq-client-fixes#groq-model-resolution-chain@1; scope: file:packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py; message: adr:spec:groq-client-fixes#groq-ask-stream-runs-tool-loop and adr:spec:groq-client-fixes#groq-model-resolution-chain share targets and about without an explicit link

Diagnostics:
- none

Coverage:
- Subsystems: clients
- Unmapped tags: groq, streaming, tool-loop
- Targets resolved: 1/1
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "clients"
    ],
    "targets_resolved": 1,
    "targets_total": 1,
    "unmapped_tags": [
      "groq",
      "streaming",
      "tool-loop"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:049970a6d163eb9c8196e382dbcd1a5db5b31e7d5e1d425250507048c415553f",
  "exit_code": 0,
  "findings": [
    {
      "blocking": false,
      "fingerprint": "sha256:eb2c63eb3f949fea30ed71945dc7936acdbbf69d93301ee619e4135d13bfba64",
      "kind": "possible-supersession",
      "message": "adr:spec:groq-client-fixes#groq-ask-stream-runs-tool-loop and adr:spec:groq-client-fixes#groq-model-resolution-chain share targets and about without an explicit link",
      "participants": [
        {
          "decision_id": "adr:spec:groq-client-fixes#groq-ask-stream-runs-tool-loop",
          "revision": 1
        },
        {
          "decision_id": "adr:spec:groq-client-fixes#groq-model-resolution-chain",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "file:packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py"
      ],
      "waived_by": null
    }
  ],
  "input_digest": "sha256:ffe74a236c20b31f973e2457f92c17c6ac90da78833f625072977ae86630e9e7",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:1f99d332d3190c534162183baa8217ad2d04ec6546d180e027385d6a6e99af01",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Delegate to `OpenAIBaseClient.ask_stream()` or keep Groq's own loop? — *Resolved in spec*: keep Groq's own loop (see Decisions, rejected alternative).
- [x] Default for `use_tools=None` in streaming? — *Resolved in spec*: `self.enable_tools or bool(tools)`.
- [ ] Should `ask()` later move onto `OpenAIBaseClient._run_tool_call_loop()` so Groq has one loop? — *Owner: maintainers* (not needed for this fix).

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; spec authored from ledger issues by /sdd-fix)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/clients/abstract-client.md` — update: drop Groq from the `ask_stream()` tool-loop known-gap lists (`:155`, `:279-280`).
- **API modules**:
  - `parrot.clients.groq.client`

---

## Worktree Strategy

- **Isolation**: one feature worktree (`feat-FEAT-896-groq-client-fixes`); the sdd-coder engine gives each task its own sub-worktree.
- **Module dependency graph**: M2 → M1 — both modify `groq/client.py`, and M2's `ask_stream()` builds on M1's model resolution at `:764`.
- **Shared files**: `packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py` (M1, M2) — serialized.
- **Exclusive resources**: none.
- **Cross-feature dependencies**: none (FEAT-848 is merged).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-14 | Jesus Lara (via /sdd-fix) | Initial draft from ledger group fixgroup:5d7789463a44 |
