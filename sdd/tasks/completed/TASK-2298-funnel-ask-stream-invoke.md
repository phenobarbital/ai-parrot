# TASK-2298: Single completion funnel — move ask_stream/invoke/helpers into the base, route via _chat_completion

**Feature**: FEAT-438 — OpenAI-Compatible Client Base (OpenAIBaseClient)
**Spec**: `sdd/specs/openai-compatible-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2297
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (second half) + Goal G3. Today `OpenAIClient.ask_stream()` and
`invoke()` call `client.chat.completions.create()` DIRECTLY, bypassing the
overridable `_chat_completion()` — the documented wart that forces Moonshot to
override `ask_stream`/`invoke` wholesale (moonshot.py:326/397 docstrings say
exactly this) and silently skips Nvidia's rate limiter on streams. This task
moves the remaining chat-completions surface into `OpenAIBaseClient` and makes
`_chat_completion()` the single funnel for ALL completion paths. This is the
one place where behavior deliberately changes — for subclasses that override
the funnel — and it must be named and tested, not slipped in.

---

## Scope

- Move to `OpenAIBaseClient` (from gpt.py):
  - `ask_stream()` (gpt.py:1283) chat-completions branch — reworked so the
    stream request is issued through `_chat_completion()` (add a
    `stream: bool = False` passthrough or a sibling `_chat_completion_stream()`
    that overrides can intercept; pick ONE seam and document it). Preserve the
    TASK-1175 contract: the final yield is an `AIMessage`. Preserve stream
    tool-call accumulation.
  - `invoke()` (gpt.py:2494) — reworked to route through `_chat_completion()`;
    keeps `_resolve_invoke_model()` (base.py:1832) and
    `_build_invoke_result()` (base.py:1849) usage.
  - `_encode_image_for_openai()` (gpt.py:1652), `_upload_file()` (gpt.py:322).
  - Delete gpt.py's `_with_extra_body` (base already has it from TASK-2296).
- `OpenAIClient` keeps: Responses-API stream branch (dispatched via
  `_is_responses_model` exactly as in TASK-2297), deep-research stream routing
  (:1324–1326/:1374/:1403), `parallel_tool_calls` injection (:1408, OpenAI-only
  hook from TASK-2297), structured-output model gating for Responses paths.
- Update Moonshot/Nvidia expectations? NO — subclass file changes belong to
  TASK-2300. But ADD base-level tests proving the funnel is honored using a
  test-only subclass that overrides `_chat_completion`.
- Extend parity tests: streaming yields (str chunks then final `AIMessage`),
  invoke structured output, funnel interception.

**NOT in scope**: editing moonshot.py/nvidia.py/etc. (TASK-2300); Responses API
internals (unchanged, stay in gpt.py); base.py modifications (TASK-2299).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/openai_base.py` | MODIFY | receive `ask_stream`, `invoke`, `_encode_image_for_openai`, `_upload_file`; funnel seam |
| `packages/ai-parrot/src/parrot/clients/gpt.py` | MODIFY | delete moved code; keep Responses/deep-research stream branches |
| `tests/clients/test_openai_base_parity.py` | MODIFY | add stream/invoke/funnel tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.openai_base import OpenAIBaseClient   # after TASK-2296/2297
from parrot.clients.gpt import OpenAIClient                # clients/gpt.py:84
```

### Existing Signatures to Use
```python
# clients/gpt.py (verified @ dev ab84ffff0):
async def ask_stream(self, prompt, model=None, max_tokens=None, temperature=None,
    files=None, system_prompt=None, user_id=None, session_id=None, tools=None,
    structured_output=None, deep_research=False, agent_config=None,
    vector_store_ids=None, enable_web_search=True, enable_code_interpreter=False,
    lazy_loading=False) -> AsyncIterator[Union[str, AIMessage]]        # :1283
#   tools_payload = self._prepare_tools() :1398; use_responses dispatch :1435
#   deep-research branches :1324-1326, :1374, :1403; parallel_tool_calls :1408
async def invoke(self, prompt, *, output_type=None, structured_output=None,
    model=None, system_prompt=None, max_tokens=4096, temperature=0.0,
    use_tools=False, tools=None) -> InvokeResult                        # :2494
#   builds response_format via self._build_response_format_from(...) :2550
def _encode_image_for_openai(self, image, low_quality=False) -> Dict    # :1652
async def _upload_file(self, file_path, purpose="fine-tune") -> None    # :322

# clients/base.py (inherited — call, do not reimplement):
def _resolve_invoke_model(self, model=None) -> str                      # :1832
def _build_invoke_result(self, output, output_type, model, usage, raw_response=None, ...)  # :1849
def _prepare_tools(self, filter_names=None) -> List[Dict]               # :1388
def _build_response_format_from(self, output_config)                    # :2604

# Known wart being fixed (evidence):
# moonshot.py:326 ask_stream docstring — OpenAIClient.ask_stream "calls
#   self.client.chat.completions.create() directly and never routes through the
#   overridden _chat_completion()"
# moonshot.py:397 invoke docstring — same for invoke()
# nvidia.py:407 _chat_completion — "NIM rejects the OpenAI SDK's parse() shortcut"
```

### Does NOT Exist
- ~~`_chat_completion_stream` today~~ — if you choose the sibling-seam design, this task creates it; otherwise a `stream=` kwarg on `_chat_completion` is the seam. Do not create both.
- ~~`OpenAIClient.embed()`~~ — no embedding surface; do not add one.
- ~~a streaming Responses path in the base~~ — `_call_responses_stream` (gpt.py:555) is OpenAI-only and stays in gpt.py.
- ~~tests asserting today's bypass~~ in the OpenAI suites — but Moonshot's suite HAS bypass-era tests (`tests/clients/test_moonshot_client.py`: ask_stream K-series safety, invoke guard). Do NOT touch them here; TASK-2300 updates them deliberately.

---

## Implementation Notes

### Pattern to Follow
- Funnel seam design: prefer ONE overridable coroutine through which every
  wire call flows. Moonshot/Nvidia currently override
  `_chat_completion(self, model, messages, use_tools=False, **kwargs)` — keep
  that exact signature workable so TASK-2300 needs no signature migration.

### Key Constraints
- TASK-1175 contract: `ask_stream` final yield is an `AIMessage` (existing
  test coverage in OpenAI suites — keep green).
- `OpenAIClient` observable behavior unchanged (its own `_chat_completion` is
  the default implementation — routing through it is a no-op for OpenAI).
- Full test run required (`pytest`), plus targeted:
  `packages/ai-parrot/tests/test_openai_client.py`, `tests/unit/test_openai_invoke.py`,
  `tests/unit/test_invoke_helpers.py`.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/gpt.py:1283-1640` — ask_stream to move.
- `packages/ai-parrot/src/parrot/clients/gpt.py:2494-2579` — invoke to move.
- `sdd/specs/openai-compatible-clients.spec.md` §2 Overview (funnel), §7 Risks.

---

## Acceptance Criteria

- [ ] A test-only subclass overriding `_chat_completion` observes calls from `ask`, `ask_stream`, AND `invoke`
- [ ] `ask_stream` still yields str chunks then a final `AIMessage` (TASK-1175)
- [ ] `invoke` still returns `InvokeResult` with structured output support
- [ ] `_with_extra_body` exists only once (in the base)
- [ ] `pytest packages/ai-parrot/tests/test_openai_client.py tests/unit/test_openai_invoke.py tests/clients/test_openai_base_parity.py -v` green
- [ ] `ruff check` clean on modified modules

---

## Test Specification

```python
# tests/clients/test_openai_base_parity.py (additions)
class _FunnelSpy(OpenAIBaseClient):
    """Records every _chat_completion call."""
    ...

async def test_ask_routes_via_funnel(mock_openai_sdk): ...
async def test_ask_stream_routes_via_funnel(mock_openai_sdk): ...
async def test_invoke_routes_via_funnel(mock_openai_sdk): ...
async def test_ask_stream_final_yield_is_aimessage(mock_openai_sdk): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2297 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/openai-compatible-clients.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2298-funnel-ask-stream-invoke.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
