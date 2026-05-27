---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Google GenAI client — simultaneous tool-calling + structured output

**Feature ID**: FEAT-193
**Date**: 2026-05-27
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD (next minor)
**Source proposal**: [`sdd/proposals/feat-193-google-genai-combined-tools-and-schema.proposal.md`](../proposals/feat-193-google-genai-combined-tools-and-schema.proposal.md)
**Research audit**: [`sdd/state/FEAT-193/`](../state/FEAT-193/)

---

## 1. Motivation & Business Requirements

### Problem Statement

`GoogleGenAIClient` currently runs a deliberate **two-phase flow** whenever the caller asks for both tool-calling and structured output: first a tool-using chat call, then a second `generate_content` call against `_reformat_model` that re-runs the response through `response_schema` to produce the schema-compliant JSON. This was correct historically (`packages/ai-parrot/src/parrot/clients/google/client.py:109-115` comment: *"Gemini cannot combine tools + response_schema in one call."*) and remains correct for `gemini-2.5-pro` (Google's API returns `400 Bad Request` if `response_mime_type='application/json'` is combined with `tools=` on that model).

However, newer Gemini 3.x models — confirmed via the SDK-level probe at `examples/google/test_tool_structured_output.py` — now accept `tools` + `response_mime_type` + `response_schema` in a **single** `GenerateContentConfig`. Per upstream evaluation:

- `gemini-3.1-pro-preview` — fully compatible, clean transition.
- `gemini-3.5-flash` — fully compatible, clean transition.
- `gemini-3.1-flash-lite-preview` — compatible, with caveats (SDK warnings on the function-call turn, AFC infinite-loop risk if the prompt is loose).

Forcing the two-phase fallback on these models adds **one extra LLM round-trip per tool-using call** (the reformat call against `_reformat_model = GEMINI_3_FLASH_PREVIEW`), which is pure latency and cost overhead.

### Goals

- For a configurable whitelist of model prefixes (default: `gemini-3.1-pro`, `gemini-3.5-flash`, `gemini-3.1-flash-lite`), `ask()` and `ask_stream()` apply `response_mime_type` + `response_schema` in the SAME `GenerateContentConfig` as `tools` — no deferred reformat call.
- For every other model — including `gemini-2.5-pro` and all `gemini-2.x` variants — the existing two-phase flow is preserved byte-for-byte.
- The whitelist is configurable: class-level default (overridable per subclass) and per-instance via constructor kwarg.
- A new model entry `GoogleModel.GEMINI_3_5_FLASH = "gemini-3.5-flash"` is added to the registry (Google's deprecations page confirms this is a real model — https://ai.google.dev/gemini-api/docs/deprecations).
- The example `examples/google/structured_with_tools.py` is parametrized so the user can exercise each whitelisted model.
- `gemini-3.1-flash-lite-preview` is whitelisted by default but emits a one-shot DEBUG-level log noting the upstream stability flag.

### Non-Goals (explicitly out of scope)

- Changing the existing two-phase fallback logic for older models — it stays bit-for-bit identical.
- Modifying `_reformat_model` / `_default_reformat_model` or its default value (`GEMINI_3_FLASH_PREVIEW`).
- Modifying `packages/ai-parrot/src/parrot/clients/google/analysis.py` — its specialized analysis methods (sentiment, product review, image understanding) already use single-call structured output because they do not combine with tools.
- Adding new tool-calling modes (`FunctionCallingConfigMode`) or changing the existing AUTO default.
- Touching the streaming wire protocol (combined mode still streams the chat; only the post-stream reformat call is bypassed).
- Live integration tests against the Google API in CI (mock-only tests are in scope; live tests can be added opportunistically).

---

## 2. Architectural Design

### Overview

Introduce a new capability gate `_supports_combined_tools_and_schema(model: str) -> bool` on `GoogleGenAIClient` that returns True when `model` starts with any prefix in `self._combined_call_prefixes`. The two existing two-phase gates (`client.py:2033-2048` in `ask()` and `client.py:2847-2854` in `ask_stream()`) branch on this check: when True, the schema is applied to the SAME chat-call `GenerateContentConfig` as `tools` and the deferred reformat block (`:2337-2474` in `ask()`, `:3020-3084` in `ask_stream()`) is skipped.

If the model returns malformed JSON in combined mode despite `response_schema`, the implementation falls back to the legacy two-phase reformat call (recovery branch) so reliability does not regress vs. today. Cache hints (FEAT-181), lifecycle events (FEAT-176), and conversation memory updates run on the same code path as today — combined mode changes only WHICH config keys land on the chat config, not the surrounding plumbing.

### Component Diagram

```
                                                    ┌──────────────────────────┐
                                                    │ _combined_call_prefixes  │
                                                    │ (class attr / kwarg)     │
                                                    └─────────────┬────────────┘
                                                                  │
                                                                  ▼
GoogleGenAIClient.ask()  ──┐                          ┌─ _supports_combined_tools_and_schema(model) ─┐
                           │                          │                                              │
                           ├─► capability gate ───────┤                                              │
                           │                          │                                              │
GoogleGenAIClient.ask_stream() ─┘                     ├── True  ──► single-call: tools + schema in   │
                                                      │             one GenerateContentConfig        │
                                                      │             (skip deferred reformat block)   │
                                                      │                                              │
                                                      └── False ──► EXISTING two-phase flow          │
                                                                    (tools first, then reformat call ─┘
                                                                     against _reformat_model)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `GoogleGenAIClient.ask` (`client.py:1797-2547`) | modifies the gate at `:2033-2048` and the deferred-reformat block at `:2337-2474` | adds a single capability branch; preserves all surrounding cache/event/memory plumbing |
| `GoogleGenAIClient.ask_stream` (`client.py:2649-3131`) | modifies the gate at `:2847-2854` and the post-stream reformat at `:3020-3084` | symmetric to `ask()` |
| `GoogleGenAIClient._apply_structured_output_schema` (`client.py:750-771`) | reused as-is | already idempotent; no signature change |
| `GoogleGenAIClient._is_gemini3_model` / `_requires_thinking` / `_as_model_str` (`client.py:156-204`) | reuses pattern | new helper follows the same `@staticmethod` + `_as_model_str` + `.startswith()` shape |
| `GoogleGenAIClient._reformat_model` (`client.py:115, 149-152`) | unchanged; not invoked in combined mode | remains the default for non-whitelisted models |
| `parrot.models.google.GoogleModel` (`models/google.py:9-39`) | adds `GEMINI_3_5_FLASH` enum entry | new value `"gemini-3.5-flash"` |
| `examples/google/structured_with_tools.py` | rewrites to iterate the whitelist | adds `--model` CLI flag with a default that loops the whitelist |
| FEAT-181 prompt caching | unchanged | combined-mode branch reuses `_pending_cache_segs` (`client.py:2120-2157`) |
| FEAT-176 lifecycle events | unchanged | `_emit_after_call` fires in both branches |

### Data Models

No new Pydantic models. One enum entry:

```python
# packages/ai-parrot/src/parrot/models/google.py
class GoogleModel(Enum):
    ...
    GEMINI_3_5_FLASH = "gemini-3.5-flash"   # NEW — per Google deprecations page
    ...
```

The whitelist is a `tuple[str, ...]`:

```python
# packages/ai-parrot/src/parrot/clients/google/client.py
class GoogleGenAIClient(AbstractClient):
    # Default prefixes for which tools + response_schema may be sent in a
    # single GenerateContentConfig. Override per-subclass by setting
    # this attribute, or per-instance via the constructor kwarg.
    _default_combined_call_prefixes: tuple[str, ...] = (
        "gemini-3.1-pro",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
    )
```

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/clients/google/client.py

class GoogleGenAIClient(AbstractClient):

    def __init__(
        self,
        ...,
        combined_call_prefixes: Optional[tuple[str, ...]] = None,
        **kwargs,
    ):
        ...
        # Resolve: explicit kwarg > class default
        self._combined_call_prefixes: tuple[str, ...] = (
            tuple(combined_call_prefixes)
            if combined_call_prefixes is not None
            else self._default_combined_call_prefixes
        )

    @staticmethod
    def _supports_combined_tools_and_schema(model: str, prefixes: tuple[str, ...]) -> bool:
        """True when `model` starts with any prefix in `prefixes`.

        Static so it can be called both per-instance (with `self._combined_call_prefixes`)
        and externally / in tests (with a custom tuple). Mirrors the
        `_is_gemini3_model` / `_requires_thinking` pattern at client.py:156-204.
        """
        model = GoogleGenAIClient._as_model_str(model)
        if not model:
            return False
        return any(model.startswith(p) for p in prefixes)
```

The signatures of `ask()` and `ask_stream()` themselves do NOT change — the new behaviour is internal.

---

## 3. Module Breakdown

> Two source files have changes. Tests + example are separate units.

### Module 1: `parrot.models.google` — enum addition

- **Path**: `packages/ai-parrot/src/parrot/models/google.py`
- **Responsibility**: add `GEMINI_3_5_FLASH = "gemini-3.5-flash"` to the `GoogleModel` enum. Add an analogous entry in `VertexAIModel` only if Google publishes a Vertex-shape variant (verify before adding — see §8).
- **Depends on**: nothing.

### Module 2: `parrot.clients.google.client` — capability helper + gate refactor

- **Path**: `packages/ai-parrot/src/parrot/clients/google/client.py`
- **Responsibility**:
  1. Add class attribute `_default_combined_call_prefixes` (line ~107, next to `_lightweight_model`).
  2. Accept new constructor kwarg `combined_call_prefixes` and resolve it onto `self._combined_call_prefixes` (around `client.py:147-152`, alongside `_reformat_model` resolution).
  3. Add `_supports_combined_tools_and_schema(model, prefixes)` as a new `@staticmethod` next to the existing capability helpers (`client.py:156-204`).
  4. Replace the gate at `client.py:2033-2048` so that when `_use_tools and use_structured_output and self._supports_combined_tools_and_schema(model, self._combined_call_prefixes)`, the schema is applied immediately via `_apply_structured_output_schema(generation_config, output_config)` and `structured_output_for_later` stays `None`.
  5. In the deferred-reformat block (`client.py:2337-2474`), gate the SECOND `generate_content` call behind `if structured_output_for_later …`. When combined mode is in effect, the block is skipped naturally, BUT add a new branch that calls `_parse_structured_output(assistant_response_text, output_config)` so `final_output` is the parsed Pydantic / dict result (not the raw text). If `_parse_structured_output` raises in combined mode, fall back to the two-phase reformat call (recovery path).
  6. Repeat the analogous changes in `ask_stream()` at `client.py:2847-2854` (gate) and `client.py:3020-3084` (post-stream reformat block).
  7. Update the stale comment at `client.py:109-115` to reflect the new bifurcation.
  8. When combined mode triggers for a model that starts with `gemini-3.1-flash-lite`, emit `self.logger.debug("Combined tools+schema mode on %s: upstream evaluation flagged AFC instability — monitor latency.", model)` (one-line; not warning-level — the user opted in).
- **Depends on**: Module 1 only for the enum reference in the default whitelist (the whitelist uses prefix strings, not enum values, so even this dependency is soft).

### Module 3: `examples.google.structured_with_tools` — parametrize over whitelist

- **Path**: `examples/google/structured_with_tools.py`
- **Responsibility**: accept `--model <id>` CLI flag. Default: iterate the whitelist (the three model strings) and print, per model: pass/fail, response time, `len(response.tool_calls)`, and whether `response.structured_output` is a `WeatherReport` instance. Keep the existing `WeatherReport` schema and `WeatherTool` definitions.
- **Depends on**: Module 2 (the new combined-mode behaviour is what the example exercises).

### Module 4: `tests.test_google_client` — combined-mode regression tests

- **Path**: `packages/ai-parrot/tests/test_google_client.py`
- **Responsibility**: extend the existing test file with combined-mode coverage. New test cases (mock-only, no live Google API):
  1. `test_ask_combined_mode_single_call` — whitelisted model + tools + structured_output → exactly ONE `generate_content`-equivalent call, schema lands in the chat config.
  2. `test_ask_two_phase_preserved_for_unwhitelisted` — `gemini-2.5-pro` + tools + structured_output → TWO calls (chat + reformat), schema NOT in chat config (regression of today's behaviour).
  3. `test_ask_stream_combined_mode_single_path` — streaming analogue of #1: schema applied to streaming chat config, post-stream reformat NOT invoked.
  4. `test_ask_stream_two_phase_preserved_for_unwhitelisted` — streaming analogue of #2.
  5. `test_combined_call_prefixes_kwarg_override` — passing `combined_call_prefixes=()` disables combined mode for ALL models (forces two-phase even for the default whitelist).
  6. `test_combined_mode_malformed_json_falls_back_to_reformat` — whitelisted model returns invalid JSON → recovery path calls `_reformat_model` (one extra call) so the response still parses.
  7. `test_supports_combined_tools_and_schema_helper` — pure-function unit test of the new helper across whitelisted, non-whitelisted, and edge inputs (empty string, `GoogleModel` enum).
- **Depends on**: Module 2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_supports_combined_tools_and_schema_helper` | 2 | Helper returns True for `"gemini-3.1-pro-preview"`, `"gemini-3.5-flash"`, `"gemini-3.1-flash-lite-preview"`; False for `"gemini-2.5-pro"`, `"gemini-2.0-flash"`, `""`, `None`; works when passed a `GoogleModel` enum member via `_as_model_str` normalisation. |
| `test_ask_combined_mode_single_call` | 2 | Mock `client.aio.chats.create` and `chat.send_message`. Call `ask(prompt, model="gemini-3.5-flash", structured_output=WeatherReport, use_tools=True)`. Assert exactly ONE `send_message` invocation; assert the passed `GenerateContentConfig` has both `tools` AND `response_mime_type="application/json"` AND `response_schema` set. Assert NO `client.aio.models.generate_content` call (the reformat path). |
| `test_ask_two_phase_preserved_for_unwhitelisted` | 2 | Same setup with `model="gemini-2.5-pro"`. Assert ONE `send_message` (chat) + ONE `generate_content` (reformat). Assert chat config has `tools` but NO `response_schema`. Assert reformat config has `response_schema`. |
| `test_ask_combined_mode_no_structured_output` | 2 | Whitelisted model + tools but no `structured_output`. Combined-mode path is irrelevant (no schema to apply). Assert ONE `send_message` and ZERO reformat calls (regression). |
| `test_ask_combined_mode_no_tools` | 2 | Whitelisted model + `structured_output` but no tools. Schema applied to chat config; no tools in config; ONE `send_message`, ZERO reformat. Matches today's "structured-output-only" path — must keep working. |
| `test_ask_stream_combined_mode_single_path` | 2 | Stream analogue of `test_ask_combined_mode_single_call`. Assert schema lives on the streaming chat config; assert NO post-stream `generate_content` reformat call. |
| `test_ask_stream_two_phase_preserved_for_unwhitelisted` | 2 | Stream + `gemini-2.5-pro` + tools + schema → assert post-stream reformat IS invoked. |
| `test_combined_call_prefixes_kwarg_override_empty` | 2 | `GoogleGenAIClient(combined_call_prefixes=())` → even `gemini-3.5-flash` falls back to two-phase. |
| `test_combined_call_prefixes_kwarg_override_custom` | 2 | `GoogleGenAIClient(combined_call_prefixes=("gemini-3.5-flash",))` → only that prefix triggers combined mode; `gemini-3.1-pro-preview` falls back to two-phase. |
| `test_combined_mode_malformed_json_falls_back_to_reformat` | 2 | Whitelisted model returns `"not valid json"` as `assistant_response_text`. First-pass `_parse_structured_output` fails. Recovery branch invokes the legacy reformat call (`_reformat_model`). Final `response.structured_output` is parsed successfully. |
| `test_flash_lite_debug_log_emitted_once` | 2 | Whitelisted `gemini-3.1-flash-lite-preview` + combined mode → caplog captures the DEBUG message about AFC stability. |
| `test_google_model_enum_has_gemini_3_5_flash` | 1 | `GoogleModel.GEMINI_3_5_FLASH.value == "gemini-3.5-flash"`. |
| `test_lifecycle_events_fire_in_combined_mode` | 2 | Subscribe to `AfterClientCallEvent`; run combined-mode `ask()`; assert exactly one event was emitted (matching today's count for the chat call). |

### Integration Tests

> All mock-only unless explicitly noted. Live tests are out of scope per §1 Non-Goals.

| Test | Description |
|---|---|
| `test_end_to_end_combined_ask_with_pydantic_tool_result` | Full mocked flow: prompt → tool call → tool result → final text containing schema-compliant JSON. Verify `response.tool_calls` is populated AND `response.structured_output` is a `WeatherReport` instance. |
| `test_end_to_end_two_phase_unchanged` | Regression: full mocked flow against `gemini-2.5-pro` matches today's recorded behaviour byte-for-byte. |

### Test Data / Fixtures

```python
# packages/ai-parrot/tests/test_google_client.py

@pytest.fixture
def weather_schema():
    from pydantic import BaseModel, Field
    class WeatherReport(BaseModel):
        location: str = Field(..., description="The city")
        temperature: float
        condition: str
    return WeatherReport

@pytest.fixture
def mock_gemini_chat_combined_response():
    """A mocked chat that, in a single send_message turn, returns schema-compliant JSON."""
    ...

@pytest.fixture
def mock_gemini_chat_two_phase_response():
    """A mocked chat that returns free-text on the first turn and requires the reformat path."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `GoogleModel.GEMINI_3_5_FLASH` exists and equals `"gemini-3.5-flash"`.
- [ ] `GoogleGenAIClient._supports_combined_tools_and_schema(model, prefixes)` is a `@staticmethod` returning the documented boolean.
- [ ] `GoogleGenAIClient._default_combined_call_prefixes` defaults to `("gemini-3.1-pro", "gemini-3.5-flash", "gemini-3.1-flash-lite")`.
- [ ] `GoogleGenAIClient(combined_call_prefixes=...)` overrides the default per-instance; the resolved tuple is stored on `self._combined_call_prefixes`.
- [ ] For a whitelisted model + `use_tools=True` + `structured_output=<Schema>`, `ask()` makes exactly ONE chat send_message and ZERO reformat `generate_content` calls. (Test: `test_ask_combined_mode_single_call`)
- [ ] For `"gemini-2.5-pro"` (or any non-whitelisted model) under the same inputs, `ask()` makes ONE chat send_message + ONE reformat `generate_content` — exactly today's behaviour. (Test: `test_ask_two_phase_preserved_for_unwhitelisted`)
- [ ] `ask_stream()` exhibits the same dual behaviour symmetrically (Tests: `test_ask_stream_combined_mode_single_path`, `test_ask_stream_two_phase_preserved_for_unwhitelisted`).
- [ ] When combined-mode parsing fails on malformed JSON, the recovery branch invokes the legacy reformat call and the final response still includes a valid `structured_output`. (Test: `test_combined_mode_malformed_json_falls_back_to_reformat`)
- [ ] `gemini-3.1-flash-lite-preview` in combined mode emits one DEBUG log message naming the upstream stability flag. (Test: `test_flash_lite_debug_log_emitted_once`)
- [ ] FEAT-181 prompt caching (`_pending_cache_segs`) and FEAT-176 lifecycle events (`_emit_after_call`) still fire in combined mode. (Test: `test_lifecycle_events_fire_in_combined_mode`)
- [ ] `examples/google/structured_with_tools.py` accepts `--model <id>` and, when invoked with no argument, iterates the whitelist printing pass/fail per model.
- [ ] No existing test in `packages/ai-parrot/tests/test_google_client.py` regresses (all of the current 10 tests still pass).
- [ ] The stale comment at `client.py:109-115` is updated; no other surrounding code in the same block is reorganised.
- [ ] No public API signature change to `ask()` or `ask_stream()` (kwargs only added to `__init__`).
- [ ] Documentation: a one-paragraph note in the GoogleGenAIClient docstring (or the closest equivalent) explains the combined-mode behaviour and how to override the whitelist.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Every reference below was re-verified
> against `packages/ai-parrot/src/parrot/clients/google/client.py` at HEAD on
> 2026-05-27 (3980 lines). Line numbers will shift slightly during implementation —
> rely on the symbol names, not the line numbers.

### Verified Imports

```python
# All resolve at HEAD on dev (2026-05-27).
from parrot.clients.google.client import GoogleGenAIClient   # verified
from parrot.models.google import GoogleModel                  # verified — enum
from parrot.models.outputs import StructuredOutputConfig, OutputFormat   # verified — _apply_structured_output_schema uses these
from google.genai import types                                # verified — types.Tool, types.FunctionDeclaration, types.ToolConfig, types.FunctionCallingConfig
from google.genai.types import GenerateContentConfig, ThinkingConfig, Part   # verified — used in client.py
```

### Existing Class Signatures (re-verified at HEAD)

```python
# packages/ai-parrot/src/parrot/clients/google/client.py

class GoogleGenAIClient(AbstractClient):
    client_type: str = 'google'                                   # line 103
    client_name: str = 'google'                                   # line 104
    _default_model: str = GoogleModel.GEMINI_FLASH_LATEST.value   # line 105
    _fallback_model: str = 'gemini-3.1-flash-lite-preview'        # line 106
    _model_garden: bool = False                                   # line 107
    _lightweight_model: str = "gemini-3.1-flash-lite-preview"     # line 108
    _default_reformat_model: str = GoogleModel.GEMINI_3_FLASH_PREVIEW.value  # line 115

    def __init__(
        self,
        vertexai: bool = False,
        model_garden: bool = False,
        reformat_model: Optional[Union[str, GoogleModel]] = None,
        **kwargs,
    ):                                                            # line 121
        ...
        self._reformat_model: str = self._as_model_str(reformat_model) \
            or self._default_reformat_model                       # line 151-152

    @staticmethod
    def _is_gemini3_model(model: str) -> bool:                    # line 157

    @staticmethod
    def _is_preview_model(model: str) -> bool:                    # line 169

    @staticmethod
    def _requires_thinking(model: str) -> bool:                   # line 177

    @staticmethod
    def _as_model_str(model) -> str:                              # line 193

    def _apply_structured_output_schema(
        self,
        generation_config: Dict[str, Any],
        output_config: Optional[StructuredOutputConfig]
    ) -> Optional[Dict[str, Any]]:                                # line 750

    async def ask(
        self,
        prompt: str,
        ...,
        structured_output: Union[type, StructuredOutputConfig] = None,
        ...,
    ) -> AIMessage:                                               # line 1797

    async def ask_stream(
        self,
        prompt: str,
        ...,
        structured_output: Union[type, StructuredOutputConfig] = None,
        ...,
    ):                                                            # line 2649
```

### Critical Code Locations (the gates and the reformat blocks)

| Symbol / Block | Path | Lines | What it does |
|---|---|---|---|
| Two-phase gate in `ask()` | `clients/google/client.py` | 2033-2048 | Sets `structured_output_for_later = output_config` when both tools and structured output are requested. Modify this. |
| Deferred reformat call in `ask()` | `clients/google/client.py` | 2337-2474 | Builds a SECOND `generate_content` call against `self._reformat_model`. Skip in combined mode; add recovery branch for malformed-JSON case. |
| `structured_output` no-tools branch in `ask()` | `clients/google/client.py` | 2475-2484 | Calls `_parse_structured_output` directly. Preserve. |
| Gate in `ask_stream()` | `clients/google/client.py` | 2847-2854 | Applies schema only when `not _use_tools`. Modify the condition. |
| Post-stream reformat in `ask_stream()` | `clients/google/client.py` | 3020-3084 | The streaming analogue of the reformat block. Skip in combined mode. |
| Constraint comment (stale) | `clients/google/client.py` | 109-115 | `"Gemini cannot combine tools + response_schema in one call."` — update wording. |
| FEAT-181 cache hint plumbing | `clients/google/client.py` | 2120-2157 | Must keep firing in combined-mode branch. |

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_supports_combined_tools_and_schema` | `_as_model_str` | helper call | `client.py:193` |
| `_combined_call_prefixes` constructor kwarg | `__init__` resolution block | similar to `_reformat_model` pattern | `client.py:149-152` |
| New combined-mode branch in `ask()` | `_apply_structured_output_schema` | direct method call (no signature change) | `client.py:750` |
| New combined-mode branch in `ask_stream()` | `_apply_structured_output_schema` | direct method call | `client.py:750` |
| Recovery branch (malformed JSON) | Existing reformat call code | reuse the block already at `client.py:2337-2474` (refactor as needed) | `client.py:2337-2474` |
| `GoogleModel.GEMINI_3_5_FLASH` | `_combined_call_prefixes` default | string match only (no enum coupling) | `models/google.py:18` (the line where to insert) |

### Recent History on Affected Files

From `git log --since="3 months ago" -- packages/ai-parrot/src/parrot/clients/google/`:

| Commit | Summary | Risk |
|---|---|---|
| `c6333cb5` | code-review fixes for agnostic prompt caching | low — the cache hint plumbing is the constraint we must respect |
| `1428411a` | TASK-1224 — Google/Gemini cache translator | low — same |
| `47c68d22` | TASK-1194 — EventEmitterMixin into AbstractClient | low — lifecycle events must still fire in combined mode |
| `315585ad` | fix when google pro models echo thoughts | low — affects `_requires_thinking` selection; combined mode reuses existing thinking config logic unchanged |

**No commit in the last 3 months touches the two-phase reformat gate itself** — the flow has been stable; FEAT-193 is the first re-opening of that gate.

### Does NOT Exist (Anti-Hallucination)

- ~~`GoogleModel.GEMINI_3_5_FLASH`~~ — **does not exist yet**; this spec creates it.
- ~~`GoogleGenAIClient.supports_combined_tools_and_schema`~~ (public, no underscore) — do NOT make this public; follow the underscore-prefix convention of `_is_gemini3_model` et al.
- ~~`GoogleGenAIClient._combined_call_enabled`~~ — not the chosen name; the attribute is `_combined_call_prefixes` (a tuple, not a bool).
- ~~`StructuredOutputConfig.use_combined_call`~~ — there is no such field on `StructuredOutputConfig`; capability is gated on the model, not on the output config.
- ~~`types.FunctionCallingConfigMode.COMBINED`~~ — does not exist in the Google GenAI SDK; this proposal does not introduce a new mode.
- ~~`gemini-3-flash`~~ (bare, no `-preview`) — not in the enum at HEAD. Existing entries are `gemini-3-flash-preview` and `gemini-3.5-flash` (new). Do not invent a `gemini-3-flash` identifier.
- ~~`GoogleGenAIClient.reformat()`~~ as a public method — there is no such method. The reformat logic is inline in the two reformat blocks at `:2337-2474` and `:3020-3084`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Capability helper shape**: mirror `_is_gemini3_model` and `_requires_thinking` at `client.py:156-204` — `@staticmethod`, `_as_model_str` normalisation, `.startswith()` prefix matching. *Evidence*: F003.
- **Configurable defaults pattern**: mirror how `_reformat_model` is resolved at `client.py:149-152` — class attribute (`_default_combined_call_prefixes`) + constructor kwarg (`combined_call_prefixes`) + per-instance store (`self._combined_call_prefixes`). *Evidence*: F001 (and source code at line 149-152).
- **Logging style**: use `self.logger.debug(...)` for the `gemini-3.1-flash-lite` stability note (the user opted in via U2 — do not escalate to WARNING). Keep the existing `self.logger.info("Google Gemini doesn't support tools + structured output simultaneously …")` message for the unwhitelisted fallback path. *Evidence*: F001, F004.
- **Test mocking style**: follow `test_google_ask` / `test_google_ask_stream` at `tests/test_google_client.py:8-101` — mock the chat object's methods, not the SDK at the network layer.
- **`_parse_structured_output` is the validator**: it already handles Pydantic `model_validate_json`, dict deserialization, and graceful failure (returns the input string on parse failure). Reuse it; do not write a parallel parser.

### Known Risks / Gotchas

- **`gemini-3.1-flash-lite-preview` AFC infinite-loop risk** (per upstream evaluation). *Mitigation*: keep `max_iterations` enforced in the existing chat loop (it already exists for `ask_stream` — verify the equivalent for `ask()` during implementation). Document narrowly-scoped tool definitions in the example file. *Owner: implementation.*
- **Malformed JSON in combined mode**. The model might violate `response_schema` despite the schema constraint. *Mitigation*: recovery branch invokes the legacy reformat path. Cost: one extra LLM call in the failure case, same as today's default. Net win for the success case. *Owner: implementation.*
- **Cache hint plumbing must not be broken**. FEAT-181 added `_pending_cache_segs` logic at `client.py:2120-2157`; combined mode runs through the same chat call, so cache hints must keep flowing. *Mitigation*: a test asserts the cache hint API is exercised in combined mode (or at minimum, that no exception is raised when `system_prompt` is a `List[CacheableSegment]`). *Owner: implementation.*
- **Lifecycle events parity**. FEAT-176's `_emit_after_call` must still fire on the chat-call duration in combined mode. *Mitigation*: a test subscribes to `AfterClientCallEvent` and asserts emission. *Owner: implementation.*
- **Vertex AI parity**. `_is_gemini3_model` notes that Gemini 3.x on Vertex requires `location='global'` and preview variants need `api_version='v1beta1'`. Combined-mode acceptance has NOT been independently verified on Vertex — the user's evaluation was Developer-API only. *Mitigation*: spec scopes tests to mocks; live Vertex testing is deferred (Open Question #2 below). *Owner: implementation / future.*
- **Comment-rot guard**: the stale comment at `client.py:109-115` is the kind of thing future readers will trust. Update it; do not delete it (still true for `gemini-2.5-pro`).
- **Confidence caveat**: the user's underlying SDK evaluation is described as *"partial acceptance — not 100% probado"* (proposal C11). Integration tests should exercise the new code path against each whitelisted model name (mocked) to catch any divergence the SDK introduces — but live confirmation belongs to the verification phase, not this spec.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `google-genai` | already pinned in `pyproject.toml` | SDK whose newer versions accept `tools + response_schema` simultaneously for Gemini 3.x. **Verify**: confirm the pinned SDK version is recent enough during implementation (commit `016631ee` updated google-genai recently — check the resulting version in `pyproject.toml`). |

No new packages required.

---

## 8. Open Questions

### Resolved (during proposal phase — carried forward verbatim from `sdd/state/FEAT-193/synthesis.json`)

- [x] **Is `gemini-3.5-flash` a real Google model identifier that should be added to the GoogleModel enum?** — *Resolved in proposal Q&A (U1)*: yes, it's a real Google model per https://ai.google.dev/gemini-api/docs/deprecations. *Action*: add `GEMINI_3_5_FLASH = "gemini-3.5-flash"` to the `GoogleModel` enum (Module 1) and include it in the combined-mode whitelist default.
- [x] **Should `gemini-3.1-flash-lite-preview` be included in the whitelist despite being flagged as 'compatible but unstable'?** — *Resolved in proposal Q&A (U2)*: yes — include it; the combined-mode latency/SDK-warning trade-off is accepted. *Action*: include `gemini-3.1-flash-lite` in the default whitelist; emit a DEBUG log on first use per call documenting the upstream flag (covered by acceptance criterion `test_flash_lite_debug_log_emitted_once`).
- [x] **Should the whitelist be configurable or hardcoded?** — *Resolved in proposal Q&A (U3)*: configurable preferred. *Action*: class-attribute default (`_default_combined_call_prefixes`) plus per-instance override via constructor kwarg `combined_call_prefixes`.

### Unresolved (defer to implementation)

- [ ] **Malformed-JSON failure semantics in combined mode** — *Owner*: implementation. *Recommendation from proposal*: silent fallback to the two-phase reformat call (option a). Final decision deferred to whoever implements Module 2 — but Acceptance Criterion `test_combined_mode_malformed_json_falls_back_to_reformat` encodes the recommended behaviour, so changing it requires also updating the test. *Plausible alternatives*: raise to caller and let them retry.
- [ ] **Vertex AI vs Developer API parity for combined-mode tests** — *Owner*: implementation. *Recommendation from proposal*: start with mock-only unit tests (covered by §4); add live tests against both endpoints opportunistically, gated behind credentials. Does NOT block this spec.
- [ ] **`VertexAIModel` enum addition** — *Owner*: implementation. Should `VertexAIModel` also gain a `GEMINI_3_5_FLASH` entry? Verify whether Google publishes `gemini-3.5-flash` on Vertex AI before adding. Out-of-scope for Module 1 unless verification succeeds.
- [ ] **Logging-level for `flash-lite` stability note** — *Owner*: implementation. Current spec says DEBUG (per Patterns above). If the AFC instability turns out to be common in practice, escalate to WARNING in a follow-up.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (all tasks run sequentially in one worktree).
- **Rationale**: Module 2 (the gate refactor) touches multiple closely-coupled code blocks that share state through `output_config`, `structured_output_for_later`, and the chat-call iteration loop. Splitting Modules 1-4 across worktrees would create merge friction in `client.py` with no parallelism win — Module 3 (example) and Module 4 (tests) both depend on Module 2 being merged anyway.
- **Cross-feature dependencies**: none. FEAT-193 is self-contained.
- **Suggested branch name**: `feat-193-google-genai-combined-tools-and-schema`.
- **Suggested worktree path**: `.claude/worktrees/feat-193-google-genai-combined-tools-and-schema`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-27 | Jesus Lara | Initial draft from `sdd/proposals/feat-193-google-genai-combined-tools-and-schema.proposal.md`. |
