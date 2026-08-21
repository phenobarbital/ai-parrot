# TASK-2297: Rebase OpenAIClient — move ask/resume + shared tool loop into OpenAIBaseClient

**Feature**: FEAT-438 — OpenAI-Compatible Client Base (OpenAIBaseClient)
**Spec**: `sdd/specs/openai-compatible-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2296
**Assigned-to**: unassigned

---

## Context

Spec §3 Modules 2–3 (first half). The highest-risk move of FEAT-438: change
`OpenAIClient`'s base class to `OpenAIBaseClient` and pull the chat-completions
`ask()`/`resume()` paths — including the tool-calling loop that is currently
INLINED in `ask()` (gpt.py:947–1143) and DUPLICATED in `resume()`
(gpt.py:1190–1257) — down into the base as ONE shared implementation.
Everything OpenAI-only stays in gpt.py. Strict behavior parity (spec G2): the
extraction must be observationally identical for `OpenAIClient` users.

---

## Scope

- Change `class OpenAIClient(AbstractClient)` → `class OpenAIClient(OpenAIBaseClient)`
  (gpt.py:84). Import path `from parrot.clients.gpt import OpenAIClient` unchanged.
- Move to `OpenAIBaseClient`:
  - `_chat_completion()` (gpt.py:327) — the tenacity-wrapped
    `chat.completions.create`/`.parse` call.
  - The chat-completions branch of `ask()` (gpt.py:693) and `resume()`
    (gpt.py:1161), with the tool loop extracted into a single shared coroutine
    (suggested name `_run_tool_call_loop`) used by both. Preserve EXACTLY:
    assistant-message reconstruction with `"tool_calls"` (:953–970), per-call
    execution (:972), accumulation (:1027/:1031), lazy-tool re-preparation via
    `self._prepare_tools(filter_names=...)` (:1050), fallback handling
    (`_should_use_fallback` :920, metadata flags :1144–1147), usage
    accumulation, and final `ai_message.tool_calls = all_tool_calls`
    (:1143/:1280).
  - `batch_ask()` (gpt.py:1642 — sequential loop over `ask()`).
- Keep in `OpenAIClient` (override or stay put): Responses-API dispatch —
  `ask()` in the base calls `self._is_responses_model(...)` (base returns
  False, so the base never routes there); `OpenAIClient` keeps
  `_is_responses_model` (:344), `_prepare_responses_args` (:365),
  `_call_responses_create` (:522), `_call_responses_stream` (:555),
  `_responses_completion` (:585), deep-research routing (:351 and branches at
  :749–753/:804/:854/:878), `_normalize_model` deprecation logic (:126),
  `_apply_cache_hints` (:145), `_is_capacity_error` OpenAI-typed (:216),
  `_download_openai_file` (:244), `get_client` with `OPENAI_TIMEOUT` (:230),
  gpt-* class attrs (:92–98), and all `OpenAIModel`-defaulted helpers.
- OpenAI extension flag: `args["parallel_tool_calls"] = True` (:860, :1408) is
  OpenAI-specific — keep it applied only in `OpenAIClient` (hook or override),
  NOT unconditionally in the base.
- Write/extend parity tests proving the loop behaves identically (mocked SDK).

**NOT in scope**: `ask_stream`/`invoke`/image/file helpers (TASK-2298);
subclass rebasing (TASK-2300); base.py changes (TASK-2299).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/openai_base.py` | MODIFY | receive `_chat_completion`, `ask`, `resume`, shared tool loop, `batch_ask` |
| `packages/ai-parrot/src/parrot/clients/gpt.py` | MODIFY | rebase class; delete moved code; keep OpenAI-only overrides |
| `tests/clients/test_openai_base_parity.py` | CREATE | tool-loop parity tests (mocked SDK) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.openai_base import OpenAIBaseClient  # created by TASK-2296
from parrot.clients.base import AbstractClient           # clients/base.py:250
from parrot.models.openai import OpenAIModel, is_deprecated, get_shutoff_date, resolve_alias
    # models/openai.py:17,171,193,215 — used ONLY by gpt.py after this task
from parrot.tools.manager import ToolFormat              # tools/manager.py:47
```

### Existing Signatures to Use
```python
# clients/gpt.py (verified @ dev ab84ffff0):
class OpenAIClient(AbstractClient):                          # :84 → becomes (OpenAIBaseClient)
    async def _chat_completion(self, model: str, messages: Any, use_tools: bool = False, **kwargs)  # :327 → MOVES to base
    async def ask(self, prompt, model=None, max_tokens=None, temperature=None, files=None,
                  system_prompt=None, structured_output=None, user_id=None, session_id=None,
                  tools=None, use_tools=None, deep_research=False, background=False,
                  vector_store_ids=None, enable_web_search=True, enable_code_interpreter=False,
                  lazy_loading=False) -> AIMessage           # :693
    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage  # :1161
    async def batch_ask(self, requests) -> List[AIMessage]   # :1642
    def _resolve_model(self, model) -> str                   # :108 (base version exists after TASK-2296)
# Tool loop anchors: while getattr(result, "tool_calls", None): :947; assistant msg :953-970;
#   exec loop :972; accumulate :1027/:1031; lazy re-prepare :1050; final assign :1143
# resume() duplicate loop :1190-1257, final assign :1280
# Fallback: self._should_use_fallback(model_str, e) :920; metadata :1144-1147
# Responses→ChatCompletions shim classes _ToolCall/_Fn/_Msg :628-685 (OpenAI-only, stays in gpt.py)
# use_responses dispatch: :882 (ask) — in the base this becomes `if self._is_responses_model(model_str): ...`
#   and the base's False makes the branch dead for non-OpenAI subclasses
# parallel_tool_calls injection :860 — OpenAI extension, keep OpenAI-only

# clients/base.py (inherited helpers the moved code calls — do NOT reimplement):
    def _prepare_tools(self, filter_names=None) -> List[Dict]        # :1388
    async def _prepare_conversation_context(self, prompt, files, user_id, session_id,
        system_prompt, stateless=False)                              # :1976
    def _should_use_fallback(self, model, error) -> bool             # :926
    def _build_response_format_from(self, output_config)             # :2604 (stays on AbstractClient — spec §8 default)
    def _oai_normalize_schema(self, schema, *, force_required_all=True) -> dict  # :2557
```

### Does NOT Exist
- ~~a pre-existing `_run_tool_call_loop`~~ — the loop is inline today; this task creates the shared method.
- ~~a dedicated message-shaping method on OpenAIClient~~ — message dicts are built inline in `ask()` (:756 area); keep them inline in the moved code or extract minimally, but do not invent `_build_messages` on the base with different semantics (ZaiClient has its own unrelated `_build_messages`, zai.py:106).
- ~~`OpenAIClient._make_openai_strict_tool`~~ — lives on `AbstractClient` (base.py:1294); called from `_prepare_tools`, not from the moved code directly.
- ~~structured-output model gating in the base~~ — `STRUCTURED_OUTPUT_COMPATIBLE_MODELS` (gpt.py:55-80) is OpenAI-only; the base must not import or consult it.

---

## Implementation Notes

### Pattern to Follow
- Mechanical move with named exceptions: any intentional difference between old
  inline code and the shared loop must be listed in the Completion Note and
  covered by a test. Default = byte-equivalent behavior.
- The base `ask()` should dispatch: `if self._is_responses_model(model_str):
  return await self._responses_ask_path(...)` — implement the OpenAI-only path
  as an `OpenAIClient` method the base calls only when the hook returns True
  (a `NotImplementedError` guard in the base is acceptable).

### Key Constraints
- `pytest` full run after the move — existing suites
  `packages/ai-parrot/tests/test_openai_client.py`, `tests/clients/test_openai_fallback.py`,
  `tests/unit/test_openai_invoke.py`, `tests/clients/test_openai_compatible_defaults.py`
  must pass unmodified.
- gpt.py still declares: `tool_format = ToolFormat.OPENAI` may move to the base
  (TASK-2296 already declares it there) — remove the now-redundant gpt.py:91
  declaration.
- No behavioral change for `OpenAIClient` users: same payloads, same
  deprecation warnings, same Responses routing.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/gpt.py:693-1160` — ask() to extract from.
- `packages/ai-parrot/src/parrot/clients/gpt.py:1161-1281` — resume() duplicate loop.
- `sdd/specs/openai-compatible-clients.spec.md` §7 Known Risks — tool-loop risk list.

---

## Acceptance Criteria

- [ ] `OpenAIClient.__mro__` includes `OpenAIBaseClient`
- [ ] `ask()`/`resume()` tool loop is ONE shared implementation in the base (no duplicate in gpt.py)
- [ ] Lazy-tool re-preparation, fallback metadata, usage accumulation, final `tool_calls` assignment preserved (parity tests)
- [ ] Responses-API/deep-research routing still works on `OpenAIClient` and is unreachable from the base alone
- [ ] `parallel_tool_calls` only injected for `OpenAIClient`
- [ ] Existing OpenAI suites pass unmodified: `pytest packages/ai-parrot/tests/test_openai_client.py tests/clients/test_openai_fallback.py tests/unit/test_openai_invoke.py tests/clients/test_openai_compatible_defaults.py -v`
- [ ] `ruff check` clean on both modified modules

---

## Test Specification

```python
# tests/clients/test_openai_base_parity.py (seed — extend as needed)
import pytest
from parrot.clients.gpt import OpenAIClient
from parrot.clients.openai_base import OpenAIBaseClient


def test_openai_client_extends_base():
    assert issubclass(OpenAIClient, OpenAIBaseClient)


async def test_tool_loop_executes_and_accumulates(mock_openai_sdk):
    """Two-round tool call: loop executes tools, accumulates usage,
    sets final AIMessage.tool_calls — identical to pre-refactor behavior."""
    ...


async def test_fallback_metadata_preserved(mock_openai_sdk):
    """Capacity error on primary → fallback model retried once, metadata flags set."""
    ...


async def test_lazy_loading_reprepares_tools(mock_openai_sdk):
    """lazy_loading=True re-prepares tools with filter_names after search_tools call."""
    ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2296 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/openai-compatible-clients.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2297-rebase-openaiclient-tool-loop.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
