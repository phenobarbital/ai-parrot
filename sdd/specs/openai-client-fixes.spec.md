---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-client-openai]
tags: [clients, openai, bugfix]
---

# Feature Specification: OpenAI client fixes — `max_completion_tokens` and fixed `temperature` for reasoning models

**Feature ID**: FEAT-770
**Discovered-from**: `issue:d641d02cf6b5`
**Date**: 2026-10-30
**Author**: Jesus Lara
**Status**: approved
**Supersedes**: `sdd/specs/openai-max-completion-tokens.spec.md` (hotfix spec of 2026-09-03,
approved but never decomposed or implemented; its paths `clients/gpt.py` / `clients/moonshot.py`
predate the client package split). This spec keeps that design and re-anchors it on the current tree.

---

## 1. Motivation & Business Requirements

### Problem Statement

OpenAI's reasoning-model family (`gpt-5*`, o-series) rejects `max_tokens` on Chat Completions:

```
400 invalid_request_error — Unsupported parameter: 'max_tokens' is not supported with this model.
Use 'max_completion_tokens' instead.
```

`OpenAIClient`'s own default model is `gpt-5-mini`
(`packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py`, `_default_model` /
`model`), so **`OpenAIClient().ask("…")` fails on every call**. Reproduced on `dev` 2026-10-30 while
running the FEAT-746 G4 spike, which now pins `gpt-4.1-mini` as a workaround.

The only guard is in `OpenAIClient.ask()`: `if model_str != "gpt-5-nano": args["max_tokens"] = …`,
which covers one model id of the whole family. `ask_stream()`, `OpenAIBaseClient.ask()` /
`ask_stream()` / `invoke()`, `OpenAIClient.ask_to_image()` (default `gpt-5-mini`) and
`OpenAIClient.image_identification()` all send `max_tokens` unconditionally.

**Coupled defect** (verified against the API 2026-09-03, see superseded spec §1): with the key fixed,
`gpt-5-mini` still returns 400 for any `temperature` other than the default 1 —
*"'temperature' does not support 0.0 with this model"*. `invoke()` hard-codes `temperature=0.0`, and
`ask()` forwards a configured temperature, so fixing only the key leaves those paths broken.

### Goals

- `ask()`, `ask_stream()`, `invoke()`, `ask_to_image()` and `image_identification()` on `OpenAIClient`
  succeed against `gpt-5*` / o-series models.
- The rewrite lives in the shared `OpenAIBaseClient._chat_completion()` funnel, so no current or future
  caller of the funnel can bypass it.
- Payloads for every other `OpenAIBaseClient` subclass (Nvidia, OpenRouter, vLLM/LocalLLM, Bedrock
  Mantle, Groq, Z.ai) stay byte-identical to today.

### Non-Goals (explicitly out of scope)

- `MoonshotClient`: it overrides `_chat_completion` completely (never calls `super()`) and already
  translates the key itself. Folding it into the shared hook is a refactor, not this bug.
- The Responses API path (`_prepare_responses_args`), which already maps to `max_output_tokens`.
- Changing `OpenAIClient._default_model`, or which max-tokens *number* is resolved.
- The `gpt-5-nano` special case in `OpenAIClient.ask()` (it omits the cap entirely; harmless once the
  hook exists, and removing it would change that model's behaviour).

---

## 2. Architectural Design

### Overview

Rewrite at the single wire funnel. `OpenAIBaseClient._chat_completion()` is the one method every chat
path reaches before the SDK call (FEAT-438 G3). A protected hook, `_adapt_completion_params(model,
kwargs)`, runs as its **first statement** — before the budgeted-scope branch — so both the plain and
the `_chat_completion_budgeted` paths receive adapted kwargs (`_chat_completion_budgeted` already reads
the cap from `max_completion_tokens` when present).

The behaviour is opt-in per client via two class attributes, because the subclasses target other
vendors whose acceptance of `max_completion_tokens` is unverified. Only `OpenAIClient` opts in. OpenAI
accepts `max_completion_tokens` for non-reasoning models too, so on `OpenAIClient` the rename is
unconditional; the temperature drop applies only to model ids starting with a configured prefix.
Temperature is **dropped** (provider default applies), never coerced to 1.0.

The two `OpenAIClient` methods that call `self.client.chat.completions.create` directly
(`ask_to_image`, `image_identification`) are routed through `self._chat_completion(..., use_tools=True)`
— `use_tools=True` keeps them on `.create`, as today.

### Component Diagram

```
OpenAIClient.ask / ask_stream / resume ─┐
OpenAIBaseClient.ask / ask_stream / invoke ─┼─→ OpenAIBaseClient._chat_completion(model, messages, **kwargs)
OpenAIClient.ask_to_image / image_identification ─┘        │
                                                         ├─→ _adapt_completion_params(model, kwargs)  ← NEW
                                                         │      · max_tokens → max_completion_tokens (opt-in)
                                                         │      · drop temperature for fixed-temperature models
                                                         ├─→ _chat_completion_budgeted (scope active)
                                                         └─→ client.chat.completions.create / .parse
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OpenAIBaseClient._chat_completion` | modifies | calls the hook first |
| `OpenAIBaseClient` | extends | two class attributes + hook method |
| `OpenAIClient` | configures / modifies | opts in; two direct SDK calls routed through the funnel |
| other `OpenAIBaseClient` subclasses | unchanged | attributes at their inert defaults |
| `MoonshotClient._chat_completion` | unchanged | full override, out of scope |

### Data Models

No new models. Class attributes on `OpenAIBaseClient`:

```python
_uses_max_completion_tokens: bool = False
_fixed_temperature_prefixes: tuple[str, ...] = ()
```

`OpenAIClient` sets `_uses_max_completion_tokens = True` and
`_fixed_temperature_prefixes = ("gpt-5", "o1", "o3", "o4")` (matched case-insensitively as prefixes of
the resolved model id).

### New Public Interfaces

None. `_adapt_completion_params` is protected:

```python
def _adapt_completion_params(self, model: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``kwargs`` rewritten for the quirks of ``model``."""
```

It never mutates its input (callers reuse their `args` dict for fallback retries and tool rounds).

---

## 3. Module Breakdown

### Module 1: Completion-parameter adaptation (TASK-4894)

- `packages/ai-parrot/src/parrot/clients/openai_base.py` — attributes, `_adapt_completion_params`,
  call at the top of `_chat_completion`.
- `packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py` — opt-in attributes; route
  `ask_to_image` and `image_identification` through `_chat_completion(use_tools=True)`.
- `packages/ai-parrot-client-openai/tests/unit/test_openai_completion_params.py` — new tests.

---

## 4. Test Specification

### Unit Tests

| Test | Asserts |
|---|---|
| `test_adapt_renames_and_drops_temperature_for_gpt5` | `OpenAIClient`, `gpt-5-mini`: `max_completion_tokens` set, no `max_tokens`, no `temperature` |
| `test_adapt_keeps_temperature_for_gpt41` | `OpenAIClient`, `gpt-4.1`: renamed, `temperature` kept |
| `test_adapt_is_inert_on_base_client` | plain `OpenAIBaseClient`: kwargs returned equal to input |
| `test_adapt_does_not_mutate_input` | caller dict unchanged |
| `test_adapt_drops_none_max_tokens` | `max_tokens=None` produces no cap key |
| `test_ask_default_model_payload` | `OpenAIClient().ask()` wire kwargs use `max_completion_tokens` |
| `test_invoke_gpt5_drops_temperature` | `invoke(model="gpt-5-mini")` wire kwargs have no `temperature` |
| `test_ask_to_image_routes_through_funnel` | `ask_to_image` wire kwargs use `max_completion_tokens` |

### Validation Contract

runners:
- kind: pytest
  tests:
  - packages/ai-parrot-client-openai/tests/unit/test_openai_completion_params.py
  - packages/ai-parrot/tests/test_openai_client.py
  - packages/ai-parrot/tests/test_prompt_caching_openai.py
  - packages/ai-parrot-client-openai/tests/unit/test_openai_multiround_usage.py
  - packages/ai-parrot/tests/test_nvidia_client.py
  - packages/ai-parrot/tests/test_openrouter_client.py
  - packages/ai-parrot/tests/test_vllm_client.py
  - packages/ai-parrot/tests/clients/test_bedrock_mantle.py
  - packages/ai-parrot/tests/unit/clients/test_invoke_telemetry.py
  - packages/ai-parrot/tests/unit/clients/test_token_budget.py
  markers: none

### Test Data / Fixtures

Wire kwargs are captured by replacing `client.client` with a `MagicMock` whose
`chat.completions.create` / `.parse` are `AsyncMock`s returning a minimal chat-completion response.
No live API calls.

---

## 5. Acceptance Criteria

- [ ] `OpenAIClient` sends `max_completion_tokens` (never `max_tokens`) on every Chat Completions call.
- [ ] `OpenAIClient` omits `temperature` for model ids starting with `gpt-5`, `o1`, `o3`, `o4`, and keeps it otherwise.
- [ ] `ask_to_image` and `image_identification` reach the SDK through `_chat_completion`.
- [ ] Other `OpenAIBaseClient` subclasses' payloads are unchanged (Validation Contract tests pass).
- [ ] The hook does not mutate the caller's kwargs.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.clients.openai_base import OpenAIBaseClient   # packages/ai-parrot/src/parrot/clients/openai_base.py
from parrot.clients.openai import OpenAIClient            # packages/ai-parrot-client-openai/src/parrot/clients/openai/__init__.py
```

### Existing Class Signatures

```python
class OpenAIBaseClient(AbstractClient):                                  # openai_base.py:73
    async def _chat_completion(self, model: str, messages: Any, use_tools: bool = False,
                               stream: bool = False, **kwargs) -> Any:   # openai_base.py:228
    async def _chat_completion_budgeted(...)                             # openai_base.py:334 (reads max_completion_tokens)
    async def invoke(..., max_tokens: int | None = None, temperature: float = 0.0, ...)  # openai_base.py:1526

class OpenAIClient(OpenAIBaseClient):                                    # client.py
    _default_model: str = "gpt-5-mini"
    async def ask(...)                                                   # client.py:697 (gpt-5-nano guard L875)
    async def ask_to_image(..., model: str = "gpt-5-mini", ...)          # direct create() at client.py:1531
    async def image_identification(...)                                  # direct create() at client.py:2048
```

### Does NOT Exist

- `OpenAIBaseClient._adapt_completion_params`, `_uses_max_completion_tokens`, `_fixed_temperature_prefixes` — created by this spec.
