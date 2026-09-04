# TASK-2836: Responses API path (MetaClient-local)

**Feature**: FEAT-526 — Meta Model API (Muse Spark) LLM Client
**Spec**: `sdd/specs/meta-llm-client.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2834
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** — the substantial engineering in this feature.

`OpenAIBaseClient` has **no** Responses API support: `_is_responses_model()`
returns `False` there unconditionally, and the docs state *"only `OpenAIClient`
has a Responses API to route to."* Meta's Responses API is the only way to reach
search grounding, tool search and reasoning replay.

**Design decision D1 (resolved, binding)**: this support lives **inside
`MetaClient`**. `OpenAIClient`'s equivalent methods (`gpt.py:353-680`) are a
**structural reference to read and mirror** — do **not** import, subclass,
extend, or modify them, and do **not** hoist anything into `OpenAIBaseClient`.
Some duplication is the accepted, reversible trade.

---

## Scope

- Add Responses-API support to `parrot/clients/meta/client.py`:
  - `_prepare_responses_args()` — map parrot's message list to Responses `input`.
  - `_responses_completion()` — call `responses.create()` and fold `output[]`.
  - Override `ask()` and `ask_stream()` to route via `use_responses`.
- Fold `output[]` items into visible text, correctly ignoring `reasoning` items.
- Map tool calls both directions on the Responses shape.
- Unit tests with a mocked SDK client.

**NOT in scope**: search grounding and `count_input_tokens()` (TASK-2837),
`tool_search` mapping (TASK-2840), live e2e (TASK-2838), and **any edit to
`gpt.py`, `openai_base.py`, or `base.py`**.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/meta/client.py` | MODIFY | Responses path |
| `tests/clients/test_meta_responses.py` | CREATE | Unit tests |

> **Codebase Contract correction (same as TASK-2833/2834/2835)**: test
> path corrected to the root `tests/clients/test_meta_responses.py`.
>
> **Additional correction discovered during implementation**: enrolling
> `MetaClient` in `WIRE_SUBCLASSES` (TASK-2835) plus this task's
> `use_responses=True` default meant the funnel-parity sweeps in
> `tests/clients/test_openai_base_parity.py` and
> `test_openai_compatible_defaults.py` started routing `MetaClient.ask()`
> to the new Responses override instead of the mocked `_chat_completion` —
> those sweeps exist to exercise the *Chat-Completions* funnel. Fixed by
> adding a `MetaClient: {"use_responses": False}` case to each file's
> `_parity_client_kwargs()`/`_client_kwargs()` helper (the established
> mechanism those files already use for BedrockMantleClient/LocalLLM/vLLM
> quirks) — both files were therefore also MODIFY, not just the two listed
> above.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.openai_base import OpenAIBaseClient   # openai_base.py:65
# AIMessage — confirm the exact import path with grep before use; it is the
# return type of OpenAIBaseClient.ask() (openai_base.py:523).
```

### STRUCTURAL REFERENCE ONLY — `OpenAIClient` (read; never import or modify)
```python
# packages/ai-parrot/src/parrot/clients/gpt.py
class OpenAIClient(OpenAIBaseClient):                                    # :86
    def _is_responses_model(self, model_str) -> bool                     # :332
    def _prepare_responses_args(self, *, messages, args)                 # :353
        #  :393 text_type = "input_text" if role in {"user","tool_user"} else "output_text"
    async def _call_responses_create(self, payloads)                     # :504
        #  :516 return await self.client.responses.create(**payload)
    async def _call_responses_stream(self, payloads)                     # :537
    async def _responses_completion(self, *, model, messages, **args)    # :567
        #  :597 output_text = getattr(resp, "output_text", None)
        #  :598-607 fallback: iterate parts, accumulate part["type"] == "output_text"
    async def ask(...)                                                   # :688
        #  :874 use_responses = self._is_responses_model(model_str)
    #  :1203 stream event type "response.output_text.delta"
```

### Base-class signatures to preserve when overriding
```python
# packages/ai-parrot/src/parrot/clients/openai_base.py
async def ask(self, prompt: str, model=None, max_tokens=None, temperature=None,
    files=None, system_prompt=None, history=None, structured_output=None,
    tools=None, use_tools=None, lazy_loading=False) -> AIMessage         # :523
async def ask_stream(...)                                                # :882
async def _chat_completion(self, model, messages, use_tools=False,
                           stream=False, **kwargs)                       # :216
```
An override **must** keep the base signature so the funnel-parity sweep in
`tests/clients/test_openai_base_parity.py` continues to pass.

### LIVE-VERIFIED Responses wire shape (2026-09-04, `muse-spark-1.3-contributor`)
```
POST /v1/responses  -> 200
top-level keys: background, completed_at, created_at, error, id,
  incomplete_details, instructions, max_output_tokens, model, object, output,
  parallel_tool_calls, reasoning, service_tier, status, store, temperature,
  tool_choice, tools, top_logprobs, top_p, truncation, usage

status == "completed"
output == [ {type: "reasoning", ...}, {type: "message", content:[{text: "pong"}]} ]
usage == {"input_tokens": 12, "input_tokens_details": {"cached_tokens": 0},
          "output_tokens": 153,
          "output_tokens_details": {"reasoning_tokens": 142},
          "total_tokens": 165}
```
Output item `type` values observed live: `reasoning`, `message`,
`web_search_call`. Documented additionally: `tool_search_call`,
`tool_search_output`, `function_call`.

Output-token param is **`max_output_tokens`** on Responses (vs `max_tokens` on
Chat Completions).

### Does NOT Exist
- ~~`from .openai_base import ...`~~ inside `clients/meta/client.py` — the module
  is one level deeper under the FEAT-523 folder convention; use
  `from ..openai_base import OpenAIBaseClient`. A single-dot import will fail.
- ~~`OpenAIBaseClient._responses_completion`~~, ~~`._prepare_responses_args`~~,
  ~~`._call_responses_create`~~, ~~`._call_responses_stream`~~ — **NOT on the
  base.** Only on `OpenAIClient`. Importing them from the base will `AttributeError`.
- ~~`response.output_text` as a wire field~~ — it is an **OpenAI-SDK-computed
  convenience property**, absent from the raw JSON (verified live). Using
  `AsyncOpenAI` gives it for free; never assume it in a raw-HTTP path or when
  asserting on a mocked dict.
- ~~`response.choices`~~ — the Responses API has **no `choices` array**. Reading
  `resp.choices[0].message.content` will fail.
- ~~`tool_choice: "required"` / `"none"` / named~~ — HTTP 400. Only `"auto"`.
- ~~`logprobs: true`~~ — HTTP 400; Muse Spark is a reasoning model.
- ~~`reasoning_content` as usable thinking output~~ — redacted to empty for
  external keys.

---

## Implementation Notes

### Key Constraints

1. **`use_responses` gates the routing.** When `True` (default), `ask()` and
   `ask_stream()` route to the Responses path; when `False`, delegate to
   `super().ask(...)` / `super().ask_stream(...)` unchanged.
2. **Fold `output[]` correctly.** Concatenate text only from items whose
   `type == "message"`. **Skip `reasoning` items** — their content is empty for
   external keys, and treating them as text yields blank output.
3. **Prefer the SDK's `output_text`, but keep a fallback.** Mirror `gpt.py:597-607`:
   `getattr(resp, "output_text", None)`, then fold `output[]` manually.
4. **Use `max_output_tokens`, not `max_tokens`**, on this path, and default it
   **high** — Muse Spark spent 142 of 153 output tokens on reasoning for a
   one-word answer. A small budget truncates visible text to empty.
5. **Never send `tool_choice` other than `"auto"`** and never send `logprobs`.
6. **Do not modify `gpt.py` / `openai_base.py` / `base.py`.** D1 is binding; a
   PR touching those files fails review.
7. Async throughout; `self.logger`; Google-style docstrings.

---

## Acceptance Criteria

- [ ] `MetaClient(use_responses=True).ask("...")` routes to `responses.create`.
- [ ] `MetaClient(use_responses=False).ask("...")` routes to the inherited
      Chat Completions funnel (`_chat_completion`).
- [ ] Folding concatenates `message` items and **ignores `reasoning`** items.
- [ ] Folding prefers `output_text` when the SDK provides it.
- [ ] `max_output_tokens` (not `max_tokens`) is sent on the Responses path.
- [ ] `ask()`/`ask_stream()` keep the base signatures; parity sweep still passes.
- [ ] `gpt.py`, `openai_base.py`, `base.py` are **unmodified** (`git diff` clean).
- [ ] Tests pass: `pytest packages/ai-parrot/tests/clients/test_meta_responses.py -v`
- [ ] `pytest tests/clients/test_openai_base_parity.py -v` still fully passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/meta/client.py` clean.

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.clients.meta import MetaClient

LIVE_SHAPE = {   # captured from a real 200 response
    "status": "completed",
    "output": [
        {"type": "reasoning", "content": []},
        {"type": "message", "content": [{"type": "output_text", "text": "pong"}]},
    ],
    "usage": {"input_tokens": 12, "output_tokens": 153,
              "output_tokens_details": {"reasoning_tokens": 142}},
}


class TestMetaResponses:
    def test_fold_ignores_reasoning_items(self):
        client = MetaClient(api_key="k")
        assert client._fold_output(LIVE_SHAPE["output"]) == "pong"

    def test_fold_concatenates_multiple_message_items(self):
        client = MetaClient(api_key="k")
        out = [{"type": "message", "content": [{"type": "output_text", "text": "a"}]},
               {"type": "message", "content": [{"type": "output_text", "text": "b"}]}]
        assert client._fold_output(out) == "ab"

    async def test_use_responses_true_calls_responses_create(self, monkeypatch):
        client = MetaClient(api_key="k", use_responses=True)
        sdk = MagicMock()
        sdk.responses.create = AsyncMock(return_value=MagicMock(**LIVE_SHAPE))
        monkeypatch.setattr(client, "get_client", AsyncMock(return_value=sdk))
        await client.ask("ping")
        sdk.responses.create.assert_awaited()

    async def test_use_responses_false_uses_chat_funnel(self, monkeypatch):
        client = MetaClient(api_key="k", use_responses=False)
        funnel = AsyncMock()
        monkeypatch.setattr(client, "_chat_completion", funnel)
        await client.ask("ping")
        funnel.assert_awaited()

    async def test_sends_max_output_tokens_not_max_tokens(self, monkeypatch):
        ...  # assert payload key is max_output_tokens
```

---

## Agent Instructions

1. Read the spec (§2 Overview, §3 Module 3, §6, §7) **and** `gpt.py:353-680`
   as a structural reference — reading only, no edits there.
2. Confirm TASK-2834 is in `sdd/tasks/completed/`.
3. Verify the Codebase Contract before writing code.
4. Implement, test, verify acceptance criteria — including that the three
   shared files are untouched.
5. Move to `sdd/tasks/completed/`, set `done` in the index, fill the note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-04
**Notes**: Added `_fold_output()`, `_extract_tool_calls()`,
`_prepare_responses_args()`, `_responses_completion()`, and `ask()`/
`ask_stream()` overrides to `MetaClient`. `_responses_completion()` adapts
the Responses result to a Chat-Completions-shaped
`_ResponsesCompatResult`/`_Choice`/`_Message`/`_ToolCall` (mirroring
`gpt.py`'s `_CompatResp`/`_Choice`/`_Msg` — structural reference only, no
import/subclass), which lets `ask()` reuse the inherited generic
`_run_tool_call_loop` unchanged for a full tool-calling round trip on the
Responses path (verified in `test_tool_calling_round_trip`). `ask_stream()`
streams text deltas via `client.responses.stream()` for the Responses path
but — documented explicitly in its docstring — does NOT run a mid-stream
tool-calling loop (use `ask()` for that); this is a deliberate, bounded
simplification, not an oversight. `max_output_tokens` (not `max_tokens`)
is used on the wire; `tool_choice` is always forced to `"auto"`. 16/16 new
unit tests pass; the full `tests/clients/` suite shows zero regressions
(the 12 pre-existing failures in Anthropic/Google fallback tests are
reproducible identically on the pre-TASK-2836 commit — confirmed via
`git stash`). `gpt.py`, `openai_base.py`, `base.py` are unmodified
(`git diff --stat` empty for all three). `ruff` clean on all changed files.
**Deviations from spec**: (1) test-path correction, same as prior tasks;
(2) `MetaClient`'s `use_responses=True` default meant it began routing
`ask()` away from `_chat_completion` inside the two shared funnel-parity
test files (`test_openai_base_parity.py`, `test_openai_compatible_defaults.py`)
once enrolled in `WIRE_SUBCLASSES` (TASK-2835) — fixed via a
`MetaClient: {"use_responses": False}` case in each file's existing
per-client kwargs helper, the same mechanism already used for
BedrockMantleClient/LocalLLM/vLLM. Both files are therefore MODIFY for
this task too, beyond the two originally listed. (3) `_run_tool_call_loop`
is called without `initial_duration_ms`/`on_round` (both have safe
defaults on the base) — telemetry round-events are not emitted for the
Responses path; noted as a gap for a follow-up if observability parity
with Chat Completions is later required.
