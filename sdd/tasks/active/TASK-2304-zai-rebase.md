# TASK-2304: Phase 2 — rebase ZaiClient onto OpenAIBaseClient (native zai SDK retained)

**Feature**: FEAT-438 — OpenAI-Compatible Client Base (OpenAIBaseClient)
**Spec**: `sdd/specs/openai-compatible-clients.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2301
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 / Goal G4. `ZaiClient` (1,024 lines) carries the heaviest
wire-protocol duplication in the codebase: its own message shaping, tool loop,
stream accumulation, response→AIMessage conversion, and structured-output
builder. Rebase it onto `OpenAIBaseClient`, deleting the duplication, while
**keeping the official `zai` SDK** behind `get_client()` (spec-time decision).
Unlike Groq, the `zai` SDK does NOT mirror the OpenAI async SDK — its
completion/stream calls stay behind subclass overrides of the funnel seam.
**Strict payload parity gates every deletion — never silently normalize.**

---

## Scope

- `class ZaiClient(AbstractClient)` → `class ZaiClient(OpenAIBaseClient)`
  (zai.py:22).
- Declare `tool_format` explicitly: today `client_type="zai"` falls through
  the map to `ToolFormat.ANTHROPIC`, but base `_prepare_tools()` was never
  called — Zai built its own OpenAI-shaped tools via `_prepare_zai_tools`
  (:132). Post-rebase the inherited `ToolFormat.OPENAI` is CORRECT (Zai's API
  takes the function wrapper) — verify against `_prepare_zai_tools`' output
  and pin with a payload test before relying on it. Decide strict-tools:
  if Z.ai rejects `"strict"`, override to a non-strict path (compare with how
  base.py:1420 gates strict to `ToolFormat.OPENAI` — if OPENAI implies strict
  and Z.ai rejects it, this needs a hook or `ToolFormat.GROQ`-style handling;
  surface the finding, don't guess).
- Keep: `__init__` (:32, ZAI_API_KEY/ZAI_BASE_URL, base_headers),
  `get_client()` returning the official `zai` client (:54–67),
  `_thinking_payload` (:184) and the `thinking`/`deep_thinking` kwargs on
  `ask`, model attrs (:27–30 incl. `_lightweight_model` GLM_4_5_FLASH_FREE),
  the funnel-seam overrides adapting the zai SDK (`_create_completion` :284,
  `_stream_completion` :536 — rework them INTO the base's
  `_chat_completion`/stream seam signatures from TASK-2298), and
  usage extraction if `AIMessageFactory.from_openai()` cannot parse zai
  responses (`_usage_from_response` :204 — verify before deleting).
- Delete in favor of base implementations, parity-gated per deletion:
  `_normalize_content`/`_normalize_messages`/`_build_messages` (:73–131),
  `_prepare_zai_tools` (:132; callers :425/:633/:863/:999),
  `_prepare_structured_output_format` (:160),
  `_response_to_dict`/`_message_to_dict`/`_create_ai_message` (:222–283),
  `_parse_tool_arguments`/`_run_tool_loop` (:288–349),
  `_next_stream_item`/`_accumulate_stream_tool_calls` (:505–535), and the
  reimplemented `ask` (:350), `ask_stream` (:559), `resume` (:797),
  `invoke` (:926).
- Keep `embed()` (:1022, raises NotImplementedError) as-is.
- Extend TASK-2301's suites: ZaiClient into `WIRE_SUBCLASSES`; payload parity
  with the zai SDK mocked at the funnel seam; thinking-payload preservation
  test; keep `packages/ai-parrot/tests/test_zai_client.py` (174 L) green
  (update only internals-pinning tests — name each).

**NOT in scope**: swapping to `AsyncOpenAI` (rejected); GroqClient (TASK-2303);
adding a real `embed()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/zai.py` | MODIFY | rebase + delete duplicated wire code + SDK seam overrides |
| `tests/clients/test_openai_compatible_defaults.py` | MODIFY | add ZaiClient to roster |
| `tests/clients/test_openai_base_parity.py` | MODIFY | Zai payload parity (zai SDK mocked) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.zai import ZaiClient                  # zai.py:22
from parrot.clients.openai_base import OpenAIBaseClient   # after TASK-2296
# SDK: `from zai import ZaiClient as OfficialZaiClient` — lazy import at zai.py:56
```

### Existing Signatures to Use
```python
# clients/zai.py (verified @ dev ab84ffff0, 1024 L):
class ZaiClient(AbstractClient):                               # :22
    client_type: str = "zai"                                   # :25
    model: str = ZaiModel.GLM_5_2.value                        # :27
    _default_model: str = ZaiModel.GLM_5_2.value               # :28
    _lightweight_model: str = ZaiModel.GLM_4_5_FLASH_FREE.value  # :29
    def __init__(self, api_key=None, base_url="https://api.z.ai/api/paas/v4/",
                 timeout=None, max_retries=None, **kwargs)     # :32 (ZAI_API_KEY :40 raises ValueError :42; ZAI_BASE_URL :45; base_headers :49-52)
    async def get_client(self) -> Any                          # :54 (OfficialZaiClient(api_key, base_url, timeout?, max_retries?) :67)
    def _thinking_payload(...)                                 # :184 → KEEP (provider-real)
    def _usage_from_response(self, response) -> CompletionUsage  # :204 → verify before deleting
    async def _create_completion(self, **request_args) -> Any  # :284 → becomes funnel-seam override
    async def _stream_completion(self, **request_args)         # :536 → becomes stream-seam override
    def _next_stream_item(self, iterator) -> tuple[bool, Any]  # :505 (zai SDK iteration may be sync-wrapped — inspect body)
    async def ask(self, prompt, model=None, ..., thinking=None, deep_thinking=False, **_)  # :350 → DELETE (keep thinking via override/hook)
    async def ask_stream(...)                                  # :559 → DELETE
    async def resume(...)                                      # :797 → DELETE
    async def invoke(...)                                      # :926 → DELETE
    async def embed(self, *args, **kwargs)                     # :1022 raises NotImplementedError → KEEP
# Deletion set (duplicated wire): :73-131 message shaping, :132 _prepare_zai_tools,
#   :160 _prepare_structured_output_format, :222-283 response→AIMessage,
#   :288-349 tool loop, :505-535 stream accumulation

# Funnel seam this task plugs into (created by TASK-2298):
#   OpenAIBaseClient._chat_completion(self, model, messages, use_tools=False, **kwargs)
#   + the stream seam TASK-2298 chose (sibling method or stream= kwarg) — READ openai_base.py first
```

### Does NOT Exist
- ~~an async-native guarantee on the official `zai` SDK~~ — inspect `_create_completion`/`_stream_completion` bodies (:284/:536) for how sync/async is handled today and preserve it.
- ~~`AIMessageFactory.from_zai()`~~ — verify how the base converts responses; if the base path assumes OpenAI SDK response objects, the Zai seam must adapt zai responses to that shape (or keep `_create_ai_message` locally) — decided by parity tests, not assumption.
- ~~`ToolFormat.ZAI`~~ — no such member; the choice is OPENAI (inherited) vs an explicit override.
- ~~strict-tools acceptance by Z.ai~~ — UNVERIFIED; test/verify before shipping strict payloads (see Scope).

---

## Implementation Notes

### Pattern to Follow
- Same migration order as TASK-2303: rebase with all overrides intact → green;
  delete one duplication at a time behind parity tests; roster addition last.
- The zai SDK seam is the interesting part: keep it as thin overrides of the
  TASK-2298 funnel seam so ALL shared logic (messages, tools, loop,
  accumulation) comes from the base.

### Key Constraints
- Thinking payloads (`thinking`/`deep_thinking`) must survive — dedicated test.
- `ZAI_API_KEY` missing still raises `ValueError` (existing behavior :42).
- Full `pytest` run; zero network.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/moonshot.py:201` — provider `_chat_completion` override injecting provider params (pattern for the zai seam).
- `sdd/specs/openai-compatible-clients.spec.md` §2 Phase-2, §7 Risks (Zai SDK seam).

---

## Acceptance Criteria

- [ ] `ZaiClient(OpenAIBaseClient)`; `get_client()` still returns the official zai client (test asserts)
- [ ] Duplicated wire code deleted; shared base drives messages/tools/loop/stream
- [ ] Thinking payload preserved (test); `embed()` still raises NotImplementedError
- [ ] Tool-format decision verified with a payload test (wrapper shape + strict handling documented)
- [ ] ZaiClient added to `WIRE_SUBCLASSES`; no-leak + funnel tests green
- [ ] `pytest packages/ai-parrot/tests/test_zai_client.py tests/clients/test_openai_compatible_defaults.py tests/clients/test_openai_base_parity.py -v` green
- [ ] Full `pytest` run green; `ruff check` clean

---

## Test Specification

```python
# tests/clients/test_openai_base_parity.py (additions)
async def test_zai_keeps_native_sdk(): ...
async def test_zai_thinking_payload_preserved(mock_zai_sdk): ...
async def test_zai_tools_payload_shape(mock_zai_sdk): ...
async def test_zai_stream_final_yield_is_aimessage(mock_zai_sdk): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2301 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/openai-compatible-clients.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2304-zai-rebase.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
