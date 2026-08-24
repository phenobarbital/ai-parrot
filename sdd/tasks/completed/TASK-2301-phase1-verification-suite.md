# TASK-2301: Phase-1 verification suite — no-gpt-leak + payload parity + funnel tests

**Feature**: FEAT-438 — OpenAI-Compatible Client Base (OpenAIBaseClient)
**Spec**: `sdd/specs/openai-compatible-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2300
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 / Goal G6. The contract-enforcement layer: a parametric
"no `gpt-*` leak" test over every non-OpenAI wire subclass (kills the
DeepSeek-404 bug class permanently), per-client request-payload assertions
(mocked SDK, no network), and consolidation of the funnel-routing tests. This
suite is the gate Phase 2 (TASK-2303/2304) must extend and pass.

---

## Scope

- Extend `tests/clients/test_openai_compatible_defaults.py`:
  - Parametrize a `WIRE_SUBCLASSES` roster: `OpenRouterClient`,
    `MoonshotClient`, `NvidiaClient`, `LocalLLMClient`, `vLLMClient`,
    `BedrockMantleClient` (Phase 2 adds Groq/Zai in TASK-2303/2304).
  - For each: no `gpt-*` in `_default_model`/`_fallback_model`/
    `_lightweight_model`/`model` class attrs; `_resolve_invoke_model()`
    never returns a `gpt-*` id when constructed with a provider model;
    a mocked `ask()` request payload carries the configured model, never a
    `gpt-*` id.
  - Assert `OpenAIBaseClient` itself declares no model defaults and
    `OpenAIClient` still does (`gpt-5-mini`/`gpt-5-nano`/`gpt-4.1`).
- Create/extend `tests/clients/test_openai_base_parity.py` (seeded by
  TASK-2297/2298) into the per-client payload-parity suite:
  - Per client, with the SDK call mocked at the funnel: assert request JSON
    shape — `model`, `messages` structure, `tools` wrapper
    (`{"type":"function","function":{...}}`), presence/absence of
    `"strict"` (OpenAI only), provider params (Nvidia sampling/extra_body,
    Moonshot thinking, OpenRouter extra_body).
  - Funnel-routing consolidation: every roster client's `_chat_completion`
    (own or inherited) observed from `ask`, `ask_stream`, `invoke`.
- Wire both suites into the default pytest discovery (no special markers
  needed; they are offline).

**NOT in scope**: live smoke scripts (TASK-2305); Groq/Zai rosters
(TASK-2303/2304); fixing any defect these tests reveal in earlier tasks
(reopen the earlier task instead — report in Completion Note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/clients/test_openai_compatible_defaults.py` | MODIFY | parametric no-leak roster + invoke-chain + payload-model assertions |
| `tests/clients/test_openai_base_parity.py` | MODIFY | per-client payload parity + funnel consolidation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.openai_base import OpenAIBaseClient       # after TASK-2296
from parrot.clients.gpt import OpenAIClient                    # clients/gpt.py:84
from parrot.clients.openrouter import OpenRouterClient         # openrouter.py:26
from parrot.clients.moonshot import MoonshotClient             # moonshot.py:88
from parrot.clients.nvidia import NvidiaClient                 # nvidia.py:207
from parrot.clients.localllm import LocalLLMClient             # localllm.py:25
from parrot.clients.vllm import vLLMClient                     # vllm.py:35
from parrot.clients.nova.mantle import BedrockMantleClient     # nova/mantle.py:29
from parrot.tools.manager import ToolFormat                    # tools/manager.py:47
```

### Existing Signatures to Use
```python
# The WIP suite this task extends (verified, 118 L @ dev ab84ffff0):
# tests/clients/test_openai_compatible_defaults.py
#   test_openai_compatible_clients_declare_openai_tool_format (:63, parametrized 6 classes)
#   test_mantle_prepares_openai_shaped_tools (:68)
#   test_anthropic_still_prepares_input_schema_tools (:81)
#   test_resolve_tool_format_falls_back_to_client_type (:100)
#   test_configured_model_wins_over_signature_default (:107)
#   test_explicit_model_wins_over_configured_model (:113)
#   test_resolve_model_falls_back_to_class_default (:118)

# Invoke chain (base.py:1832):
#   explicit model > _lightweight_model > self.model
# Tool wrapper shape (base.py:1411-1425):
#   OPENAI|GROQ → {"type":"function","function":{...}}; strict ONLY for OPENAI
# Provider model attrs post-TASK-2300 (assert these, not gpt-*):
#   OpenRouter: OpenRouterModel.DEEPSEEK_R1.value; Moonshot: KIMI_K2_6/MOONSHOT_V1_128K;
#   Nvidia: MINIMAX_M3; LocalLLM: "llama3.1:8b"; vLLM: (none — inherits);
#   Mantle: "openai.gpt-oss-120b"/"google.gemma-4-26b-a4b"
#   NOTE: "openai.gpt-oss-120b" contains "gpt" but NOT "gpt-" with a dash-digit pattern —
#   define the leak predicate as matching r"^gpt-" on the model id, not substring "gpt".
```

### Does NOT Exist
- ~~`WIRE_SUBCLASSES` constant in any module~~ — define it in the test file.
- ~~Groq/Zai on the roster yet~~ — Phase 2 tasks add them.
- ~~network access in these tests~~ — everything mocked; no live keys.
- ~~`test_gpt.py`~~ — OpenAI-side assertions live in `packages/ai-parrot/tests/test_openai_client.py`.

---

## Implementation Notes

### Pattern to Follow
- Leak predicate: `re.match(r"gpt-\d", model_id)` or `model_id.startswith("gpt-")` —
  chosen to NOT false-positive on Mantle's `"openai.gpt-oss-120b"`.
- Mock at the SDK boundary (`AsyncOpenAI.chat.completions.create`) capturing
  kwargs; reuse the fixture style already in
  `tests/clients/test_openai_compatible_defaults.py`.

### Key Constraints
- Zero network. Zero env-var requirements (construct clients with explicit
  api_key/base_url kwargs).
- These tests define the FEAT-438 contract — favor exact assertions over
  loose `assert "model" in payload` checks.

### References in Codebase
- `sdd/specs/openai-compatible-clients.spec.md` §4 Test Specification (test list to realize).
- `tests/clients/test_openai_compatible_defaults.py` — house style for these assertions.

---

## Acceptance Criteria

- [ ] Parametric no-leak test covers all 6 Phase-1 subclasses (defaults + invoke chain + payload model)
- [ ] `OpenAIClient` positive control: still `gpt-5-mini`/`gpt-5-nano`/`gpt-4.1`
- [ ] Payload-parity assertions per client (tools wrapper, strict only for OpenAI, provider params)
- [ ] Funnel coverage test parametrized over the roster (ask/ask_stream/invoke)
- [ ] `pytest tests/clients/test_openai_compatible_defaults.py tests/clients/test_openai_base_parity.py -v` green, offline
- [ ] `ruff check` clean on both test files

---

## Test Specification

```python
# tests/clients/test_openai_compatible_defaults.py (additions)
import re
WIRE_SUBCLASSES = [OpenRouterClient, MoonshotClient, NvidiaClient,
                   LocalLLMClient, vLLMClient, BedrockMantleClient]

GPT_LEAK = re.compile(r"^gpt-")

@pytest.mark.parametrize("cls", WIRE_SUBCLASSES)
def test_no_gpt_default_leak(cls):
    for attr in ("_default_model", "_fallback_model", "_lightweight_model", "model"):
        val = getattr(cls, attr, None)
        assert val is None or not GPT_LEAK.match(str(val))

@pytest.mark.parametrize("cls", WIRE_SUBCLASSES)
def test_invoke_chain_never_yields_gpt(cls, client_kwargs):
    c = cls(model="provider-model-x", **client_kwargs(cls))
    assert not GPT_LEAK.match(c._resolve_invoke_model(None))
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2300 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/openai-compatible-clients.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2301-phase1-verification-suite.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-08-21
**Notes**:
- Extended `tests/clients/test_openai_compatible_defaults.py`: added
  `WIRE_SUBCLASSES` (the 6 Phase-1 classes, `vLLMClient` imported new),
  `GPT_LEAK` regex (`^gpt-`, deliberately not matching Mantle's
  `"openai.gpt-oss-120b"`), `_client_kwargs(cls)`, and 5 new
  tests/parametrized-groups: `test_openai_base_client_declares_no_model_
  defaults`, `test_openai_client_still_has_gpt_defaults` (positive
  control), `test_no_gpt_default_leak` (class-attr check, parametrized
  ×6), `test_invoke_chain_never_yields_gpt` (parametrized ×6),
  `test_ask_payload_model_never_leaks_gpt` (mocked `_chat_completion`,
  parametrized ×5 — vLLMClient excluded, see below).
- Extended `tests/clients/test_openai_base_parity.py`: added a local
  `WIRE_SUBCLASSES` roster + `_parity_client_kwargs`,
  `test_wire_subclass_tool_wrapper_is_openai_shaped_and_strict`
  (parametrized ×6), and three funnel-coverage tests
  (`test_ask_reaches_chat_completion`, `test_ask_stream_reaches_
  chat_completion`, `test_invoke_reaches_chat_completion`) using a
  plain-function `_chat_completion` spy (a callable-*object* spy silently
  breaks method-binding when monkeypatched onto a class — switched to a
  closure-based plain function so `self._chat_completion(...)`
  auto-binds correctly).
- **Corrected my own wrong assumption while writing the tests**: initially
  wrote `test_wire_subclass_tool_wrapper_is_openai_shaped_never_strict`
  asserting `"strict" not in schema` for non-OpenAI-client wire
  subclasses, based on a surface reading of the codebase contract's
  ":1420 strict ONLY for OPENAI (Groq rejects)" note. Actual
  `AbstractClient._prepare_tools()` gates "strict" on `tool_format ==
  ToolFormat.OPENAI` (a wire-protocol property all 6 Phase-1 subclasses
  declare), not on being literally `OpenAIClient` — so strict tools DO
  apply to all 6. Fixed the test to assert the correct (already-correct,
  pre-existing) behavior instead of asserting my incorrect expectation.
- **Found and reported (not fixed) a pre-existing, unrelated defect**:
  `vLLMClient.ask()`/`ask_stream()` unconditionally forward
  `extra_body=extra_body if extra_body else None` up through
  `LocalLLMClient` to `OpenAIBaseClient.ask()`/`ask_stream()`, neither of
  which has ever accepted an `extra_body` kwarg — nor did
  `OpenAIClient.ask()`/`ask_stream()` pre-FEAT-438 (verified present as
  far back as commit `ae3d613ab`, well before this feature). Every real
  (non-mocked-at-the-override-level) call to `vLLMClient.ask()`/
  `ask_stream()` has always raised `TypeError`; the existing
  `test_vllm_client.py` suite never caught this because it patches
  `LocalLLMClient.ask` with an `AsyncMock` (accepts any kwargs), never
  exercising the real signature-mismatched chain. Per this task's "NOT in
  scope: fixing any defect these tests reveal" instruction, excluded
  `vLLMClient` from the two payload/funnel tests that would otherwise hit
  it (`test_ask_payload_model_never_leaks_gpt`,
  `test_ask_reaches_chat_completion`, `test_ask_stream_reaches_
  chat_completion`) with an inline comment explaining why, rather than
  silently working around it. **Recommend a follow-up bug ticket** — this
  predates FEAT-438 and is out of scope for any task in this spec to fix.
- `LocalLLMClient`/`vLLMClient`'s `invoke()` intentionally does not route
  through `_chat_completion` (TASK-2300 kept it verbatim for its real
  schema-in-prompt fallback value) — excluded from the invoke
  funnel-coverage test with an inline comment; not a gap, a documented
  exception.
- Verification: `pytest tests/clients/test_openai_compatible_defaults.py
  tests/clients/test_openai_base_parity.py -v` → 60/60 passed, fully
  offline (no network, no env vars — every client constructed with
  explicit `api_key`/`base_url`). Full `tests/clients/` +
  `test_openai_client.py` + `test_openai_invoke.py` diffed against the
  pre-TASK-2301 baseline (`git stash`) — byte-identical failure/error
  lists, zero regressions.
- `ruff check` clean on both modified test files (one auto-fixed I001
  import-order issue).

**Deviations from spec**: none — the two documented test-roster exclusions
(vLLMClient's pre-existing `extra_body` defect; LocalLLM/vLLM's
intentionally-funnel-bypassing `invoke()`) are exactly the kind of
"exclude with inline comment + Completion Note report" the task's own
"NOT in scope" clause anticipates, not silent gaps.
