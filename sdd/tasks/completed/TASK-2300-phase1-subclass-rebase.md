# TASK-2300: Phase-1 subclass rebase — six wire clients onto OpenAIBaseClient

**Feature**: FEAT-438 — OpenAI-Compatible Client Base (OpenAIBaseClient)
**Spec**: `sdd/specs/openai-compatible-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2298, TASK-2299
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. With the wire protocol living in `OpenAIBaseClient`
(TASK-2296–2298) and the shadowing fix in (TASK-2299), swap the base class of
the five direct `OpenAIClient` subclasses to `OpenAIBaseClient` and delete
overrides that existed only to dodge OpenAI behavior. After this task, none of
these clients can inherit a `gpt-*` default — the DeepSeek-404 bug class dies
here. `vLLMClient` keeps extending `LocalLLMClient` (unchanged relationship).

---

## Scope

Per client — change the base class `OpenAIClient` → `OpenAIBaseClient` and:

- **`OpenRouterClient`** (openrouter.py:26): keep `__init__` (:56),
  `get_client` (:80), `_chat_completion` (:116, extra_body delegation),
  `_build_provider_extra_body`, `get_generation_stats`, `list_models`.
  Its `super()` calls now resolve to the base — verify `_chat_completion`'s
  `super()._chat_completion(...)` still lands on the funnel.
- **`MoonshotClient`** (moonshot.py:88): keep `__init__`, `_sanitize_params_for_model`,
  `_capture_reasoning_content`, `_chat_completion` (:201), and the
  thinking/reasoning kwargs on `ask` (:282). DELETE the `ask_stream` (:326) and
  `invoke` (:397) bypass workarounds IF their only purpose was re-routing
  through `_chat_completion` (their docstrings say so) — preserve any
  K-series param-stripping behavior by relocating it into
  `_chat_completion`/`_sanitize_params_for_model` if needed. Update
  `tests/clients/test_moonshot_client.py` bypass-era tests DELIBERATELY
  (assert the funnel now covers streams/invoke instead of asserting the
  workaround).
- **`NvidiaClient`** (nvidia.py:207): keep everything (`__init__`, rate
  limiter, `_chat_completion` :407 create-not-parse, `ask` :473,
  `ask_stream` :527 thinking params). Verify the rate limiter now ALSO covers
  `invoke()` via the funnel (new behavior — add a test).
- **`LocalLLMClient`** (localllm.py:25): DELETE `_is_responses_model` override
  (:118) — the base already returns False. Keep `get_client` (:96),
  env-driven `__init__`, `list_models`, `health_check`,
  `_invoke_with_schema_in_prompt` and the `invoke` override (:211) ONLY if it
  does more than dodge Responses routing — read it first; if its remaining
  value is schema-in-prompt fallback, keep that part.
  Its `_lightweight_model = None` (:64) manual leak fix is now redundant —
  remove the declaration (base gives `None`).
- **`vLLMClient`** (vllm.py:35): no base-class change (extends
  `LocalLLMClient`). Verify guided_json/regex/choice paths still pass through
  the funnel; run its suite.
- **`BedrockMantleClient`** (nova/mantle.py:29): base-class swap only (its
  `__init__` was already cleaned by TASK-2299).
- Run every per-client suite; update only tests that asserted the bypass wart
  itself (name each in the Completion Note).

**NOT in scope**: Groq/Zai (TASK-2303/2304); new leak/parity suites
(TASK-2301); isinstance audit (TASK-2302).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/openrouter.py` | MODIFY | base swap |
| `packages/ai-parrot/src/parrot/clients/moonshot.py` | MODIFY | base swap + delete bypass overrides |
| `packages/ai-parrot/src/parrot/clients/nvidia.py` | MODIFY | base swap |
| `packages/ai-parrot/src/parrot/clients/localllm.py` | MODIFY | base swap + delete `_is_responses_model`, `_lightweight_model=None` |
| `packages/ai-parrot/src/parrot/clients/nova/mantle.py` | MODIFY | base swap |
| `tests/clients/test_moonshot_client.py` | MODIFY | update bypass-era tests deliberately |
| (per-client test files) | MODIFY | only where they asserted the wart |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.openai_base import OpenAIBaseClient   # after TASK-2296
from parrot.clients.gpt import OpenAIClient               # still exists, still imported by these modules today:
# openrouter.py:13, moonshot.py:66, nvidia.py:32, localllm.py:13  →  change to import openai_base
```

### Existing Signatures to Use
```python
# Verified @ dev ab84ffff0 — current override inventory:
# openrouter.py:26  OpenRouterClient(OpenAIClient)
#   :52-54 client_type/client_name "openrouter", _default_model = OpenRouterModel.DEEPSEEK_R1.value
#   :56 __init__ (base_url https://openrouter.ai/api/v1 :74, OPENROUTER_API_KEY :71, api_key re-set :78)
#   :80 get_client, :104 _build_provider_extra_body, :116 _chat_completion (delegates super)
# moonshot.py:88  MoonshotClient(OpenAIClient)
#   :129-133 attrs (KIMI_K2_6 default, MOONSHOT_V1_128K fallback, _min_cache_tokens 0)
#   :135 __init__, :154 _sanitize_params_for_model, :171 _capture_reasoning_content
#   :201 _chat_completion, :282 ask, :326 ask_stream (bypass workaround), :397 invoke (bypass workaround)
#   module-level K_SERIES_MODELS and _PARAMS_TO_STRIP exist
# nvidia.py:207  NvidiaClient(OpenAIClient)
#   :267-269 attrs (MINIMAX_M3 default); :271 __init__ (NIM base_url :292, NVIDIA_API_KEY :281,
#   SlidingWindowRateLimiter :92, NvidiaRateLimitError :64)
#   :319 _resolve_sampling, :341 _acquire_rate_limit_slot, :370 _merge_thinking_extra_body
#   :407 _chat_completion ("NIM rejects .parse()"), :473 ask, :527 ask_stream
# localllm.py:25  LocalLLMClient(OpenAIClient)
#   :60-65 attrs (_lightweight_model None :64 ← remove, _default_model "llama3.1:8b")
#   :67 __init__ (LOCAL_LLM_* env vars), :96 get_client (api_key or "no-key" :113)
#   :118 _is_responses_model (always False :131 ← delete), :132 ask, :157 ask_stream
#   :182 list_models, :197 health_check, :211 invoke, :322 _invoke_with_schema_in_prompt
# vllm.py:35  vLLMClient(LocalLLMClient) — :67-68 attrs; guided_* kwargs on ask :106 / ask_stream :215
# nova/mantle.py:29  BedrockMantleClient(OpenAIClient) — only __init__ :84 (post-TASK-2299 state)

# Per-client suites (run all):
#   packages/ai-parrot/tests/test_openrouter_client.py (257 L), test_nvidia_client.py (769 L),
#   test_localllm_client.py (210 L), test_vllm_client.py (748 L)
#   tests/clients/test_moonshot_client.py (13 test classes — bypass-era: ask_stream K-series safety, invoke guard)
#   packages/ai-parrot/tests/clients/test_bedrock_mantle.py (241 L)
#   tests/clients/test_openai_compatible_defaults.py (parametrized over these six classes)
```

### Does NOT Exist
- ~~`tool_format` declarations on any of these six modules~~ — inherited from the base; do not add.
- ~~`_default_model` on vLLMClient~~ / ~~`_fallback_model`/`_lightweight_model` on OpenRouter/Nvidia~~ — not declared; after the swap they resolve to `None` → `self.model`. Do NOT invent values.
- ~~Responses-API support on any of these providers~~ — the base's `_is_responses_model() == False` makes it unreachable; none of these clients may re-enable it.
- ~~`OpenAIModel` imports in these modules~~ — none import it today; keep it that way.

---

## Implementation Notes

### Pattern to Follow
- One commit per client is acceptable, or one commit for the whole task —
  but test-run between swaps to localize breakage.
- Read each override's body BEFORE deleting: the rule is "delete only what the
  funnel now provides"; anything provider-real relocates, never vanishes.

### Key Constraints
- Existing suites pass without weakened assertions — only bypass-era tests may
  change, and each change must be named in the Completion Note.
- No new behavior beyond: (a) funnel coverage extending to streams/invoke on
  Moonshot/Nvidia/OpenRouter, (b) leak-proof defaults.

### References in Codebase
- `sdd/specs/openai-compatible-clients.spec.md` §2 Phase-1 rebase, §7 Risks.
- TASK-2298's funnel tests — the seam these swaps rely on.

---

## Acceptance Criteria

- [ ] All five modules import/extend `OpenAIBaseClient`; `vLLMClient` untouched relationship
- [ ] `isinstance(NvidiaClient(...), OpenAIClient)` is now False (audited in TASK-2302)
- [ ] LocalLLM `_is_responses_model` override and `_lightweight_model=None` declaration deleted
- [ ] Moonshot bypass overrides deleted; K-series guards still enforced (tests prove)
- [ ] Nvidia rate limiter observed on `invoke()` path (new test)
- [ ] All per-client suites green: `pytest packages/ai-parrot/tests/test_openrouter_client.py packages/ai-parrot/tests/test_nvidia_client.py packages/ai-parrot/tests/test_localllm_client.py packages/ai-parrot/tests/test_vllm_client.py tests/clients/test_moonshot_client.py packages/ai-parrot/tests/clients/test_bedrock_mantle.py tests/clients/test_openai_compatible_defaults.py -v`
- [ ] Full `pytest` run green
- [ ] `ruff check` clean on modified modules

---

## Test Specification

```python
# additions to existing suites (illustrative):
def test_moonshot_stream_routes_via_chat_completion(mock_sdk):
    """Post-rebase: MoonshotClient._chat_completion sees ask_stream calls."""
    ...

def test_nvidia_rate_limit_covers_invoke(mock_sdk):
    """Rate limiter slot acquired on invoke() — funnel coverage."""
    ...

def test_localllm_never_routes_responses(mock_sdk):
    """No override needed: base _is_responses_model is False."""
    ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2298 and TASK-2299 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/openai-compatible-clients.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2300-phase1-subclass-rebase.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-08-21
**Notes**:
- **OpenRouterClient**: trivial base swap (`OpenAIClient` → `OpenAIBaseClient`);
  `__init__`, `get_client`, `_build_provider_extra_body`,
  `_chat_completion` (extra_body delegation), `get_generation_stats`,
  `list_models` all kept unchanged.
- **BedrockMantleClient**: trivial base swap only, as anticipated (its
  `__init__` was already cleaned by TASK-2299). Updated a stale comment
  referencing "OpenAIClient.__init__" to describe the base-class-agnostic
  mechanism instead.
- **LocalLLMClient**: base swap; deleted the now-redundant
  `_is_responses_model` override (base already returns `False`) and the
  `_lightweight_model = None` class-attr declaration (base already
  provides `None`). Kept `get_client`, env-driven `__init__`,
  `ask`/`ask_stream` (real model-defaulting value), `list_models`,
  `health_check`, `invoke`/`_invoke_with_schema_in_prompt` (real
  schema-in-prompt fallback value, calls the SDK directly — NOT rerouted
  through the funnel; that's TASK-2298's completed scope, not
  requested here for this override).
- **NvidiaClient**: base swap; kept everything scoped (rate limiter,
  `_chat_completion` create-not-parse, `ask`/`ask_stream` thinking/sampling
  params). **Found and fixed a real bug surfaced by the rebase**: since
  TASK-2298 already made `ask_stream()` route through `_chat_completion`
  (the funnel), `NvidiaClient.ask_stream()`'s pre-emptive
  `await self._acquire_rate_limit_slot()` call — written when
  `ask_stream()` still bypassed the funnel — would now double-count every
  streamed call against the 40 rpm free-tier quota (slot reserved once
  manually, once again inside `_chat_completion`). Removed the redundant
  manual call; updated the stale docstring/error-message claims about the
  bypass. Added `test_invoke_consumes_a_slot` (required by acceptance
  criteria) proving the rate limiter now also covers `invoke()` (no
  override needed — inherited from `OpenAIBaseClient`, which routes
  through `_chat_completion`). Updated 3 bypass-era tests that patched
  `parrot.clients.gpt.OpenAIClient.ask_stream` (no longer in Nvidia's MRO,
  so the patch was a silent no-op) to mock the SDK level instead via
  `get_client()` — `test_ask_stream_consumes_a_slot`,
  `test_ask_stream_not_throttled_when_free_tier_off`,
  `test_stream_still_works_without_sampling_params`.
- **MoonshotClient**: base swap; deleted the `ask_stream()` K-series
  temperature-neutralization workaround and the entire `invoke()`
  override — both existed solely to compensate for `ask_stream()`/
  `invoke()` bypassing `_chat_completion()` (documented in the module's
  former "KNOWN LIMITATIONS" note). Now that both route through the
  funnel (TASK-2298), this module's own `_chat_completion` override
  already strips `temperature` (and the other fixed sampling params) for
  K-series models — so K-series `invoke()` calls now **succeed** instead
  of raising `ValueError`. Kept `_sanitize_params_for_model`,
  `_capture_reasoning_content`, `_chat_completion`, and the
  `thinking`/`reasoning_effort` context-var propagation in `ask`/
  `ask_stream` (real provider value, not bypass workarounds). Rewrote
  `TestMoonshotAskStreamKSeriesSafety` → `TestMoonshotAskStreamFunnelCoverage`
  and `TestMoonshotInvokeGuard` → `TestMoonshotInvokeViaFunnel` to prove
  the new (better) behavior end-to-end via a real mocked-SDK client
  instead of asserting the removed workarounds. Fixed 6 other tests that
  patched `parrot.clients.gpt.OpenAIClient.ask`/`ask_stream`/`invoke`
  (silently no-op post-rebase) to patch `parrot.clients.openai_base.
  OpenAIBaseClient` instead.
- **vLLMClient**: untouched relationship (still extends `LocalLLMClient`,
  itself now on `OpenAIBaseClient`); its own suite passes unmodified.
- **OpenRouterClient test suite**: `test_inherits_openai_client` asserted
  `isinstance(client, OpenAIClient)` — the literal wart this whole feature
  removes. Renamed to `test_inherits_openai_base_client`, now asserting
  `isinstance(client, OpenAIBaseClient)` AND `not isinstance(client,
  OpenAIClient)` (Module 7's audit target, confirmed here for this one
  client). Fixed 3 tests patching `parrot.clients.gpt.OpenAIClient.
  _chat_completion` (no longer in OpenRouter's MRO) to patch
  `parrot.clients.openai_base.OpenAIBaseClient._chat_completion` instead.
- Verification: `tests/clients/test_openai_compatible_defaults.py`
  (parametrized over all six classes) passes unmodified (12/12).
  `tests/clients/test_moonshot_client.py` (45/45),
  `packages/ai-parrot/tests/test_openrouter_client.py` (32/32),
  `packages/ai-parrot/tests/test_nvidia_client.py`, `test_localllm_client.py`,
  `test_vllm_client.py`, `packages/ai-parrot/tests/clients/
  test_bedrock_mantle.py` — diffed failure/error lists against the
  pre-TASK-2300 baseline (`git stash`) are **byte-identical** (21
  pre-existing, unrelated failures: a `MagicMock().model_dump()`/
  `hasattr` gotcha affecting every mocked `ask()` response across
  Nvidia/OpenRouter's fallback suites, `list_models`/`health_check`
  connection-error gaps, one Bedrock-Mantle delegation test) — zero
  regressions. Ran the full 124-file client-touching corpus (~1470 tests,
  installed `pytest-timeout` transiently per TASK-2299's established
  practice) — diffed against the TASK-2298 baseline: **zero test-identity
  differences** (only MagicMock repr memory addresses differ in two
  unrelated Google error-log lines).
- `ruff check`: `nova/mantle.py` clean; `localllm.py`/`moonshot.py`/
  `nvidia.py`/`openrouter.py` pre-existing violation counts unchanged
  (confirmed via `git stash`); the two test files with genuinely new
  content (`test_nvidia_client.py`, `tests/clients/test_moonshot_client.py`)
  also unchanged; `test_openrouter_client.py` had one new I001 (import
  order in my added test) — fixed, back to its 1 pre-existing violation.

**Deviations from spec**: none in scope — the Nvidia rate-limiter
double-acquire fix was not explicitly named in the task's Scope bullet for
NvidiaClient, but follows directly from its own "read each override's
body BEFORE deleting: delete only what the funnel now provides" guidance
and from the acceptance criterion requiring `invoke()` rate-limit coverage
to be proven; leaving the double-acquire in place would have been a
correctness regression the rebase itself introduced.
