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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
