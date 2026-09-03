# HOTFIX-openai-max-completion-tokens-1: `_adapt_completion_params()` hook on `OpenAIBaseClient`

**Feature**: hotfix `openai-max-completion-tokens` (no Jira ticket — user decision 2026-09-03) — OpenAI `max_completion_tokens` for reasoning models *(hotfix — no `FEAT-<NNN>` reserved, FEAT-466)*
**Spec**: `sdd/specs/openai-max-completion-tokens.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

OpenAI reasoning models (`gpt-5*`, o-series) reject `max_tokens` with a 400
(`Use 'max_completion_tokens' instead`) and reject any non-default
`temperature`. `OpenAIBaseClient` sends both on every path, so the framework's
**default** OpenAI client (`_default_model = "gpt-5-mini"`) cannot answer a
single `ask()` today (spec §1).

`ask()`, `ask_stream()` and `invoke()` each assemble their own kwargs but all
funnel through `OpenAIBaseClient._chat_completion()` (FEAT-438). This task adds
one protected hook at that funnel so the rewrite happens once, opt-in per
client. It implements spec §3 Module 1 and is the prerequisite for the OpenAI
and Moonshot opt-ins (tasks 2 and 3).

---

## Scope

- Add two class attributes to `OpenAIBaseClient`:
  - `_uses_max_completion_tokens: bool = False`
  - `_fixed_temperature_models: tuple[str, ...] = ()`
- Add `_adapt_completion_params(self, model: str, kwargs: dict[str, Any]) -> dict[str, Any]`
  that returns a **new** mapping where:
  - if `_uses_max_completion_tokens` and `"max_tokens" in kwargs` → key renamed to
    `max_completion_tokens` (same value); no key is added when neither is present.
  - if the resolved `model` matches any fragment in `_fixed_temperature_models`
    (case-insensitive substring) → `temperature` is **dropped** (never coerced to 1.0).
  - the flag off + empty tuple → returned mapping equals the input (no-op).
- Call the hook from `_chat_completion()` before the SDK dispatch, so every
  caller (including `stream=True`) goes through it.
- Log at `debug` level when a rename or a drop happens (`self.logger`).
- Write unit tests for the hook (see Test Specification), plus a parametrized
  sweep asserting every wire subclass still has the defaults
  (`_uses_max_completion_tokens is False`, `_fixed_temperature_models == ()`) —
  this is the guard for the "byte-identical payload" acceptance criterion for
  Nvidia/Groq/Z.ai/LocalLLM/OpenRouter/Mantle. Tasks 2 and 3 will
  deliberately *remove* `OpenAIClient` and `MoonshotClient` from that sweep.

**NOT in scope**: enabling the flag on any client (tasks 2, 3); the Responses
API path in `gpt.py`; anything about *which number* `max_tokens` carries
(`_resolve_invoke_max_tokens` is untouched); docs (task 4); live tests (task 4).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/openai_base.py` | MODIFY | Add the two attributes + `_adapt_completion_params()`; call it in `_chat_completion()` |
| `tests/clients/test_openai_base_adapt_params.py` | CREATE | Unit tests for the hook + default sweep over wire subclasses |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/main` at `feb5a5a6a` on 2026-09-03. Re-check line
> numbers before editing.

### Verified Imports
```python
from parrot.clients.openai_base import OpenAIBaseClient   # verified: packages/ai-parrot/src/parrot/clients/openai_base.py:60
from parrot.clients.gpt import OpenAIClient               # verified: clients/gpt.py:81
from parrot.clients.groq import GroqClient                # verified: clients/groq.py:50
from parrot.clients.zai import ZaiClient                  # verified: clients/zai.py:22
from parrot.clients.nvidia import NvidiaClient            # verified: clients/nvidia.py:207 (spec says 222 — stale)
from parrot.clients.moonshot import MoonshotClient        # verified: clients/moonshot.py:74
from parrot.clients.localllm import LocalLLMClient        # verified: clients/localllm.py:26
from parrot.clients.openrouter import OpenRouterClient    # verified: clients/openrouter.py:26
from parrot.clients.nova.mantle import BedrockMantleClient # verified: clients/nova/mantle.py:32
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/openai_base.py
class OpenAIBaseClient(AbstractClient):                                   # line 60
    async def _chat_completion(                                           # line 205
        self, model: str, messages: Any, use_tools: bool = False,
        stream: bool = False, **kwargs
    ) -> Any:
        from openai import APIConnectionError, APIError, RateLimitError   # line 239
        retry_policy = AsyncRetrying(...)                                 # line 241
        if use_tools:                                                     # line 247
            method = self.client.chat.completions.create
        else:
            method = getattr(self.client.chat.completions, "parse", self.client.chat.completions.create)
        if stream:                                                        # line 251
            kwargs["stream"] = True
        async for attempt in retry_policy:                                # line 253
            with attempt:
                return await method(model=model, messages=messages, **kwargs)
    # ↑ insert `kwargs = self._adapt_completion_params(model, kwargs)` right
    #   after the `stream` handling and before the retry loop.

    # The three kwargs-assembly sites that reach the funnel (do NOT edit them):
    #   ask()        line 514 → args["max_tokens"] = max_tokens or self.max_tokens   (634)
    #                           args["temperature"] = temperature                     (636)
    #   ask_stream() line 895 → args["max_tokens"] = max_tokens_value                 (1000)
    #                           args["temperature"] = temperature_value               (1004)
    #   invoke()     line 1173 → kwargs = {"max_tokens": max_tokens, "temperature": temperature}  (1227-1230)
```

```python
# tests/clients/test_openai_base.py:15 — the instantiation pattern for the base class
class _Stub(OpenAIBaseClient):
    """Minimal concrete subclass for instantiation (abstract methods stubbed)."""
    async def get_client(self): ...
    async def ask(self, *args, **kwargs): ...
    async def ask_stream(self, *args, **kwargs): ...
    async def resume(self, *args, **kwargs): ...
    async def invoke(self, *args, **kwargs): ...

# tests/clients/test_openai_compatible_defaults.py:49 — WIRE_SUBCLASSES roster
#   (parametrized with ids=lambda c: c.__name__ at lines 179/189) — reuse this
#   list for the defaults sweep rather than hand-typing the eight classes.
# tests/conftest.py:122 — `bind_sdk_client(monkeypatch)` fixture for attaching a
#   fake SDK client to a parrot client instance.
```

### Does NOT Exist
- ~~`OpenAIBaseClient._adapt_completion_params()`~~ — **this task creates it**
- ~~`OpenAIBaseClient._uses_max_completion_tokens`~~ — this task creates it
- ~~`OpenAIBaseClient._fixed_temperature_models`~~ — this task creates it
- ~~`AbstractClient._model_output_cap()`~~ — **not on `main`** (spec §7 cites it
  as the fragment-matching pattern to mirror; it does not exist in
  `clients/base.py` on `origin/main`). Write the substring match inline:
  `any(frag.lower() in model.lower() for frag in self._fixed_temperature_models)`.
- ~~`AbstractClient._resolve_max_tokens()`~~ — exists only on `dev` (`ff559e953`);
  on `main` the resolver is `_resolve_invoke_max_tokens()` (`clients/base.py:1778`).
  Do not write against the `dev` shape.
- ~~`OpenAIBaseClient._normalize_completion_kwargs`~~ / any other name for the
  hook — use exactly `_adapt_completion_params`.

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot/src/parrot/clients/openai_base.py — inside OpenAIBaseClient
#: When True, send ``max_completion_tokens`` instead of ``max_tokens``.
#: Off by default: only endpoints verified to accept the newer key opt in.
_uses_max_completion_tokens: bool = False

#: Model-id fragments whose provider rejects a non-default ``temperature``.
#: Matched case-insensitively as substrings of the resolved model id.
_fixed_temperature_models: tuple[str, ...] = ()

def _adapt_completion_params(self, model: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Rewrite request kwargs for the quirks of the resolved model.

    Args:
        model: The resolved model identifier being called.
        kwargs: The chat-completions request kwargs, as assembled by the caller.

    Returns:
        The kwargs to send. Callers must use the return value; the input
        mapping is not mutated in place.
    """
    adapted = dict(kwargs)
    if self._uses_max_completion_tokens and "max_tokens" in adapted:
        adapted["max_completion_tokens"] = adapted.pop("max_tokens")
    lowered = (model or "").lower()
    if "temperature" in adapted and any(
        frag.lower() in lowered for frag in self._fixed_temperature_models
    ):
        adapted.pop("temperature")
    return adapted
```

### Key Constraints
- **Return a copy, never mutate** — `ask()` reuses its `args` dict for the
  fallback retry at `openai_base.py:641-652`; mutating in place would make the
  second call see already-renamed keys.
- Must be a strict no-op when the flag is off and the tuple is empty — the
  six non-opted-in clients must produce byte-identical payloads.
- `NvidiaClient` (`nvidia.py:407`) and `MoonshotClient` (`moonshot.py:187`)
  override `_chat_completion` **without** calling `super()`, so the base hook
  call will not run for them. That is correct for this task (neither opts in
  here); task 3 wires Moonshot explicitly.
- Google-style docstring + strict type hints; `self.logger.debug(...)` on rename/drop.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/moonshot.py:246-247` — the existing
  one-off translation this hook generalises
- `docs/clients/openai-compatible.md` §"The Funnel Contract" (line 168) — why the funnel is the right seam

---

## Acceptance Criteria

- [ ] `_uses_max_completion_tokens` and `_fixed_temperature_models` exist on `OpenAIBaseClient` with the documented defaults
- [ ] `_adapt_completion_params()` exists, is called from `_chat_completion()` for both `stream=False` and `stream=True`
- [ ] Flag on + `max_tokens=512` → SDK receives `max_completion_tokens=512` and no `max_tokens`
- [ ] Flag off → SDK receives `max_tokens` unchanged; no `max_completion_tokens`
- [ ] Neither key present → neither key present out
- [ ] Model matching a fragment + `temperature=0.0` → `temperature` absent; non-matching model keeps `temperature=0.0`
- [ ] Fragment match is substring + case-insensitive (`GPT-5-Mini`, `gpt-5.6-sol` both match `gpt-5`)
- [ ] The caller's kwargs mapping is unchanged after the call
- [ ] Sweep: every class in `WIRE_SUBCLASSES` has `_uses_max_completion_tokens is False` and `_fixed_temperature_models == ()` (tasks 2/3 will exclude their classes)
- [ ] All tests pass: `pytest tests/clients/test_openai_base_adapt_params.py tests/clients/test_openai_base.py tests/clients/test_openai_compatible_defaults.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/openai_base.py` clean
- [ ] No public API change

---

## Test Specification

```python
# tests/clients/test_openai_base_adapt_params.py
from types import SimpleNamespace
from typing import Any

import pytest
from parrot.clients.openai_base import OpenAIBaseClient
from tests.clients.test_openai_compatible_defaults import WIRE_SUBCLASSES


class _Stub(OpenAIBaseClient):
    """Concrete stand-in (mirrors tests/clients/test_openai_base.py::_Stub)."""
    async def get_client(self): ...
    async def ask(self, *a, **k): ...
    async def ask_stream(self, *a, **k): ...
    async def resume(self, *a, **k): ...
    async def invoke(self, *a, **k): ...


class _OptedIn(_Stub):
    _uses_max_completion_tokens = True
    _fixed_temperature_models = ("gpt-5",)


@pytest.fixture
def captured_payload():
    """Capture the kwargs handed to the SDK without a network call."""
    seen: dict[str, Any] = {}

    async def _fake_create(*, model, messages, **kwargs):
        seen.update(kwargs)
        seen["model"] = model
        return SimpleNamespace(choices=[], usage=None)

    return seen, _fake_create


def test_max_tokens_renamed_when_opted_in():
    c = _OptedIn.__new__(_OptedIn)
    out = c._adapt_completion_params("gpt-4.1", {"max_tokens": 512})
    assert out == {"max_completion_tokens": 512}


def test_max_tokens_untouched_by_default():
    c = _Stub.__new__(_Stub)
    assert c._adapt_completion_params("any", {"max_tokens": 512}) == {"max_tokens": 512}


def test_no_token_key_added_when_absent():
    c = _OptedIn.__new__(_OptedIn)
    out = c._adapt_completion_params("gpt-5-mini", {"messages_extra": 1})
    assert "max_tokens" not in out and "max_completion_tokens" not in out


def test_temperature_dropped_for_fixed_temperature_model():
    c = _OptedIn.__new__(_OptedIn)
    assert "temperature" not in c._adapt_completion_params("gpt-5-mini", {"temperature": 0.0})


def test_temperature_kept_for_normal_model():
    c = _OptedIn.__new__(_OptedIn)
    assert c._adapt_completion_params("gpt-4.1", {"temperature": 0.0})["temperature"] == 0.0


@pytest.mark.parametrize("model", ["GPT-5-Mini", "gpt-5.6-sol", "openai/gpt-5"])
def test_fixed_temperature_match_is_substring_and_case_insensitive(model):
    c = _OptedIn.__new__(_OptedIn)
    assert "temperature" not in c._adapt_completion_params(model, {"temperature": 0.2})


def test_adapt_does_not_mutate_caller_kwargs():
    c = _OptedIn.__new__(_OptedIn)
    src = {"max_tokens": 5, "temperature": 0.0}
    c._adapt_completion_params("gpt-5-mini", src)
    assert src == {"max_tokens": 5, "temperature": 0.0}


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_chat_completion_routes_through_hook(captured_payload, stream):
    """The funnel applies the hook on both the plain and the streaming path."""
    seen, fake = captured_payload
    c = _OptedIn.__new__(_OptedIn)
    c.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake)))
    await c._chat_completion("gpt-5-mini", [], use_tools=True, stream=stream,
                             max_tokens=64, temperature=0.0)
    assert seen["max_completion_tokens"] == 64
    assert "max_tokens" not in seen and "temperature" not in seen


@pytest.mark.parametrize("cls", WIRE_SUBCLASSES, ids=lambda c: c.__name__)
def test_wire_subclasses_keep_defaults(cls):
    """Guards the byte-identical-payload criterion for non-opted-in clients."""
    assert cls._uses_max_completion_tokens is False
    assert cls._fixed_temperature_models == ()
```

> The last test is expected to be narrowed by tasks 2 and 3 (exclude
> `OpenAIClient` / `MoonshotClient`). Leave a comment pointing at them.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — before writing ANY code confirm the line
   anchors above still hold on your branch (`grep -n "async def _chat_completion" packages/ai-parrot/src/parrot/clients/openai_base.py`)
4. **Update status** in `sdd/tasks/index/openai-max-completion-tokens.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-03
**Notes**: Added `_uses_max_completion_tokens` / `_fixed_temperature_models`
class attributes and `_adapt_completion_params()` to `OpenAIBaseClient`,
called from `_chat_completion()` right after the `stream` handling and
before the retry loop, so both `stream=False` and `stream=True` callers
route through it. Created `tests/clients/test_openai_base_adapt_params.py`
with the full unit suite from the task's Test Specification, importing
`WIRE_SUBCLASSES` from `test_openai_compatible_defaults.py` for the
defaults sweep (unfiltered — `OpenAIClient` was never a member of that
list; task 3 will narrow it to exclude `MoonshotClient`).
`pytest tests/clients/test_openai_base_adapt_params.py
tests/clients/test_openai_base.py tests/clients/test_openai_compatible_defaults.py -v`
→ 65 passed. `ruff check` clean on both files.

**Deviations from spec**: The task's "Scope" bullet said to
`self.logger.debug(...)` on rename/drop, but its own "Pattern to Follow"
reference implementation omits any logging call, and the Test
Specification instantiates the client via `.__new__()` (no `__init__`,
so no `self.logger`) for every non-async test — adding the debug calls
made those tests fail with `AttributeError: '_OptedIn' object has no
attribute 'logger'`. Followed the Pattern to Follow code verbatim (no
logging) since it is unambiguous and matches the given Test
Specification; flagging the inconsistency here per the "when in doubt,
note it" rule rather than guessing. Also updated
`test_chat_completion_routes_through_hook` to bind the fake SDK via the
`bind_sdk_client` fixture (`tests/conftest.py:122`) instead of direct
`c.client = ...` assignment — direct assignment now raises
`AttributeError` under `AbstractClient`'s loop-local `client` property
(FEAT-112), which postdates the task's `feb5a5a6a` Codebase Contract
snapshot.
