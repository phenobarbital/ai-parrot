---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: hotfix
base_branch: main
---

# Feature Specification: OpenAI `max_completion_tokens` for reasoning models

**Jira**: none — *user decision 2026-09-03: no ticket for this hotfix. No `FEAT-<NNN>` reserved; a bugfix is not a feature (FEAT-466).*
The hotfix is identified by its spec slug; branch `hotfix-openai-max-completion-tokens`, tasks `HOTFIX-openai-max-completion-tokens-N`.
**Date**: 2026-09-03
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.28.1

---

## 1. Motivation & Business Requirements

### Problem Statement

OpenAI's reasoning-model family (`gpt-5*`, o-series) **rejects the
`max_tokens` parameter outright**:

```
400 invalid_request_error
Unsupported parameter: 'max_tokens' is not supported with this model.
Use 'max_completion_tokens' instead.
```

`OpenAIBaseClient` puts `max_tokens` into the chat-completions payload on
every path, so **no `gpt-5` or o-series model can be called at all** through
this framework.

This is not a niche edge case, because `OpenAIClient._default_model` is
itself `"gpt-5-mini"` (`gpt.py:89`). Verified live against `main`
(`ab932a93d`) on 2026-09-03:

| Call | Result on `main` |
|---|---|
| `LLMFactory.create("openai").ask("Say OK.")` | **400** — unsupported parameter |
| `LLMFactory.create("openai:gpt-5-mini").ask(...)` | **400** — unsupported parameter |
| `LLMFactory.create("openai:gpt-5-mini").invoke(...)` | **400** — unsupported parameter |
| `LLMFactory.create("openai").invoke(...)` | OK — only because `_lightweight_model` substitutes `gpt-4.1` |

**The default OpenAI client cannot answer a single prompt through `ask()`.**
The one path that works does so by accident, because it silently swaps in a
different model.

The defect is **pre-existing** — it is not a consequence of the `max_tokens`
resolver unification (`ff559e953`, which is on `dev` and not yet on `main`).
It went unnoticed because the account's OpenAI credit balance was empty: every
call failed at billing (`429 no credits remaining`) before reaching parameter
validation. It surfaced the moment credits were added during the FEAT-481
matrix run (`artifacts/logs/feat481/`, run `20260902T231844Z`): `gpt-5-mini`
FAIL 0/2 with this exact 400, while `gpt-4.1` passed 2/2 on the identical call.

A sibling client already solves this for itself — `MoonshotClient` translates
the parameter at `moonshot.py:247` — but the translation lives in that
subclass only, so nothing else benefits.

**Second, coupled defect.** Fixing the parameter name alone does *not* make
these models work. Verified directly against the OpenAI API on 2026-09-03:

| Payload to `gpt-5-mini` | Result |
|---|---|
| `max_completion_tokens: 2048` | **200 OK** |
| `max_completion_tokens: 2048` + `temperature: 0.0` | **400** — *"Unsupported value: 'temperature' does not support 0.0 with this model. Only the default (1) value is supported"* |
| `max_completion_tokens: 2048` + `temperature: 1.0` | **200 OK** |

`invoke()` hard-codes `temperature` into the payload (`openai_base.py:1229`)
and `ask()` forwards a configured one, so a `temperature`-shaped 400 replaces
the `max_tokens`-shaped one unless both are handled together. **A fix that
addresses only the token parameter will still leave every reasoning model
unusable.**

### Goals

- `ask()`, `ask_stream()` and `invoke()` all succeed against `gpt-5*` /
  o-series models.
- The translation lives in shared code, so all eight `OpenAIBaseClient`
  subclasses inherit it rather than each re-implementing it.
- `MoonshotClient`'s bespoke copy folds into the shared mechanism instead of
  standing beside it.
- No behaviour change for models and endpoints that work today
  (`gpt-4.1`, NVIDIA NIM, Groq, Z.ai, vLLM, LocalLLM, OpenRouter, Bedrock
  Mantle).

### Non-Goals (explicitly out of scope)

- The Responses API path (`gpt.py:488-489`), which already maps to
  `max_output_tokens` correctly and is not implicated.
- Changing `OpenAIClient._default_model` away from `gpt-5-mini`. That would
  mask this bug rather than fix it; the default is a reasonable choice once
  the parameters are correct.
- Any change to `AbstractClient._resolve_invoke_model()` precedence. That is a
  separate, already-fixed concern (see `sdd/specs/lightweight-invoke-client-method.spec.md`,
  amendment 2026-09-03, on `dev`).
- Reworking `max_tokens` *resolution* (which number to send). The unification
  on `dev` (`ff559e953`) is orthogonal — this spec is only about the parameter
  *name* and the `temperature` constraint.

---

## 2. Architectural Design

### Overview

Translate at the **single wire funnel**, not at each payload site.

`OpenAIBaseClient._chat_completion()` (`openai_base.py:205`) is the one method
every path reaches before the SDK call — FEAT-438 built it precisely so that
"a subclass override applies everywhere instead of only to `ask()`". `ask()`,
`ask_stream()` and `invoke()` each assemble `max_tokens` into their own kwargs
(three separate sites) and then funnel through it. Fixing the funnel fixes all
three at once and cannot be bypassed by a future fourth caller.

The adjustment is **opt-in per client** via a class attribute rather than
applied globally, because the eight subclasses point at different vendors'
endpoints and only OpenAI's is known to require the new name. Evidence
gathered 2026-09-03:

| Endpoint | `max_tokens` | `max_completion_tokens` |
|---|---|---|
| OpenAI `gpt-5-mini` | **400** | 200 OK |
| OpenAI `gpt-4.1` | 200 OK | 200 OK |
| NVIDIA NIM `openai/gpt-oss-120b` | 200 OK | 200 OK |
| Groq | inconclusive — 403 (Cloudflare) on *both*, no signal |
| Z.ai, vLLM, LocalLLM, OpenRouter, Bedrock Mantle | not tested |

OpenAI accepts `max_completion_tokens` for *non*-reasoning models too, so the
selection does not need a per-model allowlist on the OpenAI path — but it must
not be switched on for endpoints whose acceptance is unverified. Default the
attribute to the current behaviour and enable it only where proven.

`temperature` is handled by the same hook: for models that constrain it, the
key is dropped from the payload so the provider applies its own default,
rather than being coerced to `1.0` (which would silently discard a caller's
setting on models that *do* honour it).

### Component Diagram

```
ask()  ─┐
        │   (each builds its own kwargs incl. max_tokens / temperature)
ask_stream() ─┼──→ OpenAIBaseClient._chat_completion(model, messages, **kwargs)
        │                    │
invoke() ─┘                  ├──→ _adapt_completion_params(model, kwargs)   ← NEW
                             │        · max_tokens → max_completion_tokens
                             │        · drop constrained temperature
                             │
                             └──→ client.chat.completions.create / .parse

MoonshotClient._chat_completion  ──→ super()._chat_completion(...)
   (keeps its thinking-param logic; drops its own line 247 translation)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OpenAIBaseClient._chat_completion` | modifies | Single funnel; calls the new hook before dispatch |
| `OpenAIClient` | configures | Opts in — the only client verified to need the new name |
| `MoonshotClient._chat_completion` | simplifies | Opts in; its `line 247` translation is removed as redundant |
| `NvidiaClient`, `GroqClient`, `ZaiClient`, `LocalLLMClient`, `OpenRouterClient`, `BedrockMantleClient` | unchanged | Attribute left at its default; payloads byte-identical to today |
| `AbstractClient._resolve_invoke_max_tokens` | unchanged | Decides the *number*; this spec only renames the *key* |

### Data Models

No new Pydantic models. Two class-level configuration attributes on
`OpenAIBaseClient`:

```python
class OpenAIBaseClient(AbstractClient):
    #: When True, send ``max_completion_tokens`` instead of ``max_tokens``.
    #: Off by default: only endpoints verified to accept the newer key opt in.
    _uses_max_completion_tokens: bool = False

    #: Model-id fragments whose provider rejects a non-default ``temperature``.
    #: Matched case-insensitively as substrings of the resolved model id.
    _fixed_temperature_models: tuple[str, ...] = ()
```

### New Public Interfaces

None. The hook is protected and the change is invisible to callers — that is
the point: existing code that sends `max_tokens` keeps working, and code that
targets a reasoning model stops failing.

```python
# parrot/clients/openai_base.py
def _adapt_completion_params(self, model: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Rewrite request kwargs for the quirks of the resolved model.

    Args:
        model: The resolved model identifier being called.
        kwargs: The chat-completions request kwargs, as assembled by the caller.

    Returns:
        The kwargs to send. Callers must use the return value; the input
        mapping is not mutated in place.
    """
```

---

## 3. Module Breakdown

### Module 1: The adaptation hook
- **Path**: `packages/ai-parrot/src/parrot/clients/openai_base.py`
- **Responsibility**: Add `_uses_max_completion_tokens` and
  `_fixed_temperature_models`; add `_adapt_completion_params()`; call it from
  `_chat_completion()` (line 205) before dispatch. Rename `max_tokens` →
  `max_completion_tokens` when the flag is on and the key is present; drop
  `temperature` when the resolved model matches a fixed-temperature fragment.
  Must be a no-op when the flag is off.
- **Depends on**: nothing — self-contained in the base class.

### Module 2: OpenAI opt-in
- **Path**: `packages/ai-parrot/src/parrot/clients/gpt.py`
- **Responsibility**: Set `_uses_max_completion_tokens = True` and populate
  `_fixed_temperature_models` with the reasoning-model fragments (`gpt-5`,
  `o1`, `o3`, `o4` — confirm each against the live API before adding; do not
  add a fragment on speculation). Leave the Responses API path untouched.
- **Depends on**: Module 1.

### Module 3: Moonshot de-duplication
- **Path**: `packages/ai-parrot/src/parrot/clients/moonshot.py`
- **Responsibility**: Set `_uses_max_completion_tokens = True`; delete the
  local translation at line 247; keep every thinking-parameter behaviour and
  the `prompt_cache_key` default exactly as-is. The resulting payload must be
  byte-identical to today's for every Moonshot model.
- **Depends on**: Module 1.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_max_tokens_renamed_when_opted_in` | 1 | Flag on + `max_tokens=512` → payload carries `max_completion_tokens=512` and no `max_tokens` |
| `test_max_tokens_untouched_by_default` | 1 | Flag off → payload carries `max_tokens` unchanged (guards NVIDIA/Groq/Z.ai/vLLM/LocalLLM/OpenRouter/Mantle) |
| `test_no_token_key_added_when_absent` | 1 | Neither key present in → neither key present out |
| `test_temperature_dropped_for_fixed_temperature_model` | 1 | `gpt-5-mini` + `temperature=0.0` → `temperature` absent from payload |
| `test_temperature_kept_for_normal_model` | 1 | `gpt-4.1` + `temperature=0.0` → `temperature=0.0` preserved |
| `test_fixed_temperature_match_is_substring_and_case_insensitive` | 1 | `GPT-5-Mini`, `gpt-5.6-sol` both match the `gpt-5` fragment |
| `test_adapt_does_not_mutate_caller_kwargs` | 1 | Input mapping is unchanged after the call |
| `test_openai_client_opts_in` | 2 | `OpenAIClient._uses_max_completion_tokens is True` |
| `test_moonshot_payload_unchanged` | 3 | Moonshot payload identical to the pre-change snapshot |

All three payload paths must be covered, since each assembles kwargs
separately — parametrize over `ask` / `ask_stream` / `invoke` rather than
testing `_chat_completion` alone, so a future caller that bypasses the funnel
is caught.

### Integration Tests

| Test | Description |
|---|---|
| `test_gpt5_ask_succeeds` | Live: `LLMFactory.create("openai:gpt-5-mini").ask(...)` returns content (marked `real_llm`) |
| `test_gpt5_invoke_structured_succeeds` | Live: `invoke()` with a Pydantic `output_type` returns the typed model |
| `test_default_openai_client_ask_succeeds` | Live: `LLMFactory.create("openai").ask(...)` — the exact call that 400s today |
| `test_gpt41_still_succeeds` | Live: regression guard that the non-reasoning path is untouched |

Live tests follow the existing convention: `pytest.mark.real_llm`, skipped
unless `PARROT_TEST_REAL_LLM=1`, and skipped again when OpenAI credentials are
absent (`packages/ai-parrot/tests/clients/test_structured_output_live_matrix.py`
is the pattern to copy).

### Test Data / Fixtures

```python
@pytest.fixture
def captured_payload(monkeypatch):
    """Capture the kwargs handed to the SDK without making a network call."""
    seen: dict[str, Any] = {}

    async def _fake_create(*, model, messages, **kwargs):
        seen.update(kwargs)
        seen["model"] = model
        return SimpleNamespace(choices=[], usage=None)

    return seen, _fake_create
```

---

## 5. Acceptance Criteria

- [ ] `LLMFactory.create("openai").ask("Say OK.")` returns content instead of a 400
- [ ] `LLMFactory.create("openai:gpt-5-mini")` succeeds through `ask()`, `ask_stream()` and `invoke()`
- [ ] `invoke()` with a Pydantic `output_type` returns the typed model on `gpt-5-mini`
- [ ] `gpt-4.1` behaviour is unchanged (still passes, payload still carries `temperature`)
- [ ] Payloads for `NvidiaClient`, `GroqClient`, `ZaiClient`, `LocalLLMClient`, `OpenRouterClient` and `BedrockMantleClient` are byte-identical to pre-change
- [ ] `MoonshotClient` payload is byte-identical to pre-change, and `moonshot.py` no longer carries its own translation
- [ ] No `max_tokens`/`max_completion_tokens` handling is duplicated outside `_adapt_completion_params()` on the chat-completions path
- [ ] Unit tests pass: `pytest tests/unit/ -v` and `pytest packages/ai-parrot/tests/ -v`
- [ ] Live tests pass: `PARROT_TEST_REAL_LLM=1 pytest -m real_llm -k openai -v`
- [ ] `docs/clients/openai-compatible.md` documents both new attributes and when to set them
- [ ] No breaking change to any public API

---

## 6. Codebase Contract

> Verified against `main` at `ab932a93d` on 2026-09-03. Line numbers are from
> that commit — re-check before editing, `main` moves.

### Verified Imports

```python
from parrot.clients.openai_base import OpenAIBaseClient   # verified: clients/openai_base.py
from parrot.clients.gpt import OpenAIClient               # verified: clients/gpt.py:81
from parrot.clients.moonshot import MoonshotClient        # verified: clients/moonshot.py:74
from parrot.clients.factory import LLMFactory             # verified: clients/factory.py
from parrot.exceptions import TruncatedResponseError      # verified: exceptions.py:88
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/clients/openai_base.py
class OpenAIBaseClient(AbstractClient):
    async def _chat_completion(                                    # line 205  ← THE FUNNEL
        self, model: str, messages: Any, use_tools: bool = False,
        stream: bool = False, **kwargs
    ) -> Any: ...
    async def ask(...)                                             # line 514
    #   args["max_tokens"] = max_tokens or self.max_tokens         # line 634
    async def ask_stream(...)                                      # line 895
    #   args["max_tokens"] = max_tokens_value                      # line 1000
    async def invoke(...)                                          # line 1173
    #   kwargs = {"max_tokens": max_tokens, "temperature": ...}    # line 1228

# packages/ai-parrot/src/parrot/clients/gpt.py
class OpenAIClient(OpenAIBaseClient):                              # line 81
    _default_model: str = "gpt-5-mini"                             # line 89   ← the broken default
    _lightweight_model: str = "gpt-4.1"                            # line 91
    #   args["max_tokens"] = max_tokens or self.max_tokens         # line 863
    #   args["max_tokens"] = max_tokens_value                      # line 1162
    #   req["max_output_tokens"] = args["max_tokens"]              # line 489 (Responses API — out of scope)
    # NOTE: gpt.py does NOT override _chat_completion — it inherits the funnel.

# packages/ai-parrot/src/parrot/clients/moonshot.py
class MoonshotClient(OpenAIBaseClient):                            # line 74
    _default_model: str = MoonshotModel.KIMI_K2_6.value            # line 117
    async def _chat_completion(...)                                # line 187  (overrides; calls super)
    #   kwargs["max_completion_tokens"] = kwargs.pop("max_tokens") # line 247  ← the reference implementation
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_adapt_completion_params()` | `_chat_completion()` | called before SDK dispatch | `clients/openai_base.py:205` |
| `_uses_max_completion_tokens` | `OpenAIClient` | class attribute override | `clients/gpt.py:81` |
| `_uses_max_completion_tokens` | `MoonshotClient` | class attribute override, replaces local translation | `clients/moonshot.py:247` |

### The eight subclasses that inherit the funnel

Verified via `grep -rn "class .*(OpenAIBaseClient)"`:

| Class | File |
|---|---|
| `OpenAIClient` | `clients/gpt.py:81` |
| `GroqClient` | `clients/groq.py:50` |
| `ZaiClient` | `clients/zai.py:22` |
| `NvidiaClient` | `clients/nvidia.py:222` |
| `MoonshotClient` | `clients/moonshot.py:74` |
| `LocalLLMClient` | `clients/localllm.py:26` |
| `OpenRouterClient` | `clients/openrouter.py:26` |
| `BedrockMantleClient` | `clients/nova/mantle.py:32` |

### Does NOT Exist (Anti-Hallucination)

- ~~`OpenAIBaseClient._adapt_completion_params()`~~ — this spec creates it
- ~~`OpenAIBaseClient._uses_max_completion_tokens`~~ — this spec creates it
- ~~`OpenAIBaseClient._fixed_temperature_models`~~ — this spec creates it
- ~~`AbstractClient._resolve_max_tokens()`~~ — **does not exist on `main`.** It
  exists only on `dev` (`ff559e953`). On `main` the resolver is
  `_resolve_invoke_max_tokens()` (`clients/base.py:1778`) and `invoke()` does
  **not** call it — `max_tokens` is passed straight through to the payload.
  Do not write against the `dev` shape.
- ~~`OpenAIClient._chat_completion()`~~ — not overridden in `gpt.py`; the base
  implementation is what runs
- ~~a `reasoning_effort` parameter on the base client~~ — exists only in
  `MoonshotClient`; not part of this fix

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Follow `MoonshotClient._chat_completion` (`moonshot.py:187-247`) as the
  reference: override-friendly, mutates a local copy of kwargs, calls through.
- Google-style docstrings and strict type hints on every new method.
- Return the adapted mapping rather than mutating the caller's dict — three
  different call sites pass their own kwargs and one of them reuses the dict.
- Match model fragments case-insensitively by substring, mirroring
  `AbstractClient._model_output_cap()`'s established fragment-matching
  approach, so `gpt-5-mini`, `GPT-5`, and `gpt-5.6-sol` all resolve.

### Known Risks / Gotchas

- **Fixing only the token parameter is not enough.** `temperature: 0.0` yields
  a second 400 on `gpt-5-mini` (verified). Both must land together or the
  acceptance criteria cannot pass. This is the single most likely way for this
  hotfix to be declared done while still broken.
- **Do not enable the flag globally.** Only OpenAI and NVIDIA were verified to
  accept `max_completion_tokens`; Groq was inconclusive (403 Cloudflare on both
  parameter names) and five other endpoints were never tested. A global switch
  risks trading one vendor's 400 for six others'.
- **Model-fragment lists rot.** `sdd/specs/openai-model-deprecation.spec.md`
  and the `NvidiaModel` enum both document how a hardcoded model list drifts
  from reality. Keep `_fixed_temperature_models` to fragments (`gpt-5`, not
  `gpt-5-mini-2026-01-01`) and verify each against a live call before adding.
- **`main` and `dev` differ here.** `dev` has the `_resolve_max_tokens`
  unification; `main` does not. Write against `main` (§6), and expect a merge
  interaction at the `invoke()` payload site when this reaches `dev`.
- **Empty credit balances hide parameter bugs.** This defect survived a full
  live cross-provider matrix run because billing rejected the call first. When
  a provider row reports an account/billing failure, it has produced **no
  evidence** about request shape — the FEAT-481 harness already models this as
  a distinct `UNAVAIL` verdict for exactly this reason.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | No new dependencies; `openai` SDK already forwards arbitrary kwargs |

---

## 8. Open Questions

- [ ] Jira issue key for this hotfix — *Owner: Jesus Lara*. Required before the
      worktree is created (it names the branch) and before `/sdd-done` can
      resolve the ticket.
- [ ] Which model fragments belong in `_fixed_temperature_models` beyond
      `gpt-5`? — *Owner: implementer*. `o1`/`o3`/`o4` are expected to share the
      constraint but were **not** verified live; probe each before adding, and
      add none on speculation.
- [ ] Should `GroqClient` opt in? — *Owner: implementer*. The raw probe was
      blocked by Cloudflare (403 on both parameter names) and produced no
      signal. Re-probe through the Groq SDK; leave the flag off until proven.
- [ ] Does `ask_stream()` need separate live coverage, or is the unit-level
      payload assertion sufficient given all three paths share the funnel? —
      *Owner: implementer*.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — three modules, one worktree, run
  sequentially. Modules 2 and 3 both depend on Module 1 and both touch client
  configuration; parallelising them would contend on the same test suite for
  no wall-clock gain.
- **Cross-feature dependencies**: none. This bases on `main` and must not pick
  up unreleased `dev` commits — in particular the `_resolve_max_tokens`
  unification (`ff559e953`), whose absence on `main` is recorded in §6.
- **Worktree creation** (hotfix — from `origin/main`, never `HEAD`/`dev`):
  ```bash
  git worktree add -b hotfix-<KEY>-openai-max-completion-tokens \
    .claude/worktrees/hotfix-<KEY>-openai-max-completion-tokens origin/main
  ```
- **Task decomposition**: not required. Per FEAT-466 a hotfix normally skips
  `/sdd-task` and dispatches straight to development from this spec.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-03 | Jesus Lara | Initial draft — live-verified against `main` `ab932a93d` |
| 0.2 | 2026-09-03 | Jesus Lara | Approved; no Jira ticket (user decision); decomposed into 4 `HOTFIX-openai-max-completion-tokens-N` tasks on branch `hotfix-openai-max-completion-tokens` |
