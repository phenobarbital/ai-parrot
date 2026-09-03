# HOTFIX-openai-max-completion-tokens-2: `OpenAIClient` opts in — `max_completion_tokens` + fixed-temperature fragments

**Feature**: hotfix `openai-max-completion-tokens` (no Jira ticket — user decision 2026-09-03) — OpenAI `max_completion_tokens` for reasoning models *(hotfix — no `FEAT-<NNN>` reserved, FEAT-466)*
**Spec**: `sdd/specs/openai-max-completion-tokens.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: HOTFIX-openai-max-completion-tokens-1
**Assigned-to**: unassigned

---

## Context

Task 1 added the `_adapt_completion_params()` hook to the funnel but left it
switched off everywhere. This task switches it on for the **only** client
verified to need it — `OpenAIClient` (`gpt.py`) — and populates the
fixed-temperature fragment list, then proves through unit tests that all three
kwargs-assembly paths (`ask`, `ask_stream`, `invoke`) reach the SDK with the
corrected payload. Implements spec §3 Module 2.

Both halves must land together: with the token key fixed but `temperature`
still sent, `gpt-5-mini` returns a *second* 400 (spec §1, "Second, coupled
defect"). A token-only fix is the single most likely way this hotfix gets
declared done while still broken (spec §7).

---

## Scope

- In `OpenAIClient` set `_uses_max_completion_tokens = True`.
- Populate `_fixed_temperature_models` with **live-verified** fragments only.
  `("gpt-5",)` is verified (spec §1 table). `o1`, `o3`, `o4` are *expected*
  but **were not verified** — probe each with a raw
  `max_completion_tokens` + `temperature: 0.0` call before adding it; add
  none on speculation. Record every probe result (model, status, error text)
  in the Completion Note. Use fragments (`gpt-5`), never dated ids.
- Add unit tests that capture the SDK payload for `OpenAIClient` across
  **all three paths** — `ask()`, `ask_stream()`, `invoke()` — parametrized, so
  a future caller bypassing the funnel is caught:
  - `gpt-5-mini` + `temperature=0.0` + `max_tokens=64` → payload has
    `max_completion_tokens=64`, no `max_tokens`, no `temperature`.
  - `gpt-4.1` + `temperature=0.0` → payload has `max_completion_tokens`
    **and** `temperature=0.0` (OpenAI accepts the new key on non-reasoning
    models too; temperature must survive).
- Add `test_openai_client_opts_in` (`OpenAIClient._uses_max_completion_tokens is True`).
- Narrow task 1's `test_wire_subclasses_keep_defaults` sweep to exclude
  `OpenAIClient` (leave a comment naming this task).

**NOT in scope**: the Responses API path (`gpt.py:486-489` maps to
`max_output_tokens` already — leave it); changing `_default_model`
(`gpt-5-mini`) or `_lightweight_model` (`gpt-4.1`); Moonshot (task 3); live
`real_llm` tests and docs (task 4); any edit to `openai_base.py` beyond what
task 1 landed.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/gpt.py` | MODIFY | Two class-attribute overrides on `OpenAIClient` (+ a short comment citing the 400 text) |
| `tests/clients/test_openai_reasoning_params.py` | CREATE | Three-path payload tests for `OpenAIClient`, opt-in assertion |
| `tests/clients/test_openai_base_adapt_params.py` | MODIFY | Exclude `OpenAIClient` from the defaults sweep |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/main` at `feb5a5a6a` on 2026-09-03.

### Verified Imports
```python
from parrot.clients.gpt import OpenAIClient               # verified: packages/ai-parrot/src/parrot/clients/gpt.py:81
from parrot.clients.openai_base import OpenAIBaseClient   # verified: clients/openai_base.py:60
from parrot.clients.factory import LLMFactory             # verified: clients/factory.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/gpt.py
class OpenAIClient(OpenAIBaseClient):                        # line 81
    _default_model: str = "gpt-5-mini"                       # line 89  ← the broken default; DO NOT change
    _lightweight_model: str = "gpt-4.1"                      # line 91
    # gpt.py does NOT override _chat_completion (comment at line 323 says so) — the base funnel runs.
    async def ask(...)                                       # line 683 (OVERRIDES base ask)
    #   args["max_tokens"] = max_tokens or self.max_tokens   # line 863
    #   args["temperature"] = temperature                    # line 865
    #   response = await self._chat_completion(model=model_str, messages=messages, use_tools=_use_tools, **args)  # line 885
    async def ask_stream(...)                                # line 1031 (OVERRIDES base ask_stream)
    #   args["max_tokens"] = max_tokens_value                # line 1162
    #   args["temperature"] = temperature_value              # line 1166
    #   response_stream = await self._chat_completion(...)   # line 1309
    # invoke() is NOT overridden → OpenAIBaseClient.invoke at openai_base.py:1173
    #   kwargs = {"max_tokens": max_tokens, "temperature": temperature}  # openai_base.py:1227-1230
    #   response = await self._chat_completion(model=resolved_model, messages=messages, use_tools=True, **kwargs)  # :1245
    # Responses API (OUT OF SCOPE):
    #   if "max_tokens" in args: req["max_output_tokens"] = args["max_tokens"]   # lines 488-489

# packages/ai-parrot/src/parrot/clients/openai_base.py (landed by task 1)
class OpenAIBaseClient(AbstractClient):
    _uses_max_completion_tokens: bool = False
    _fixed_temperature_models: tuple[str, ...] = ()
    def _adapt_completion_params(self, model: str, kwargs: dict[str, Any]) -> dict[str, Any]: ...
```

```python
# Test scaffolding to reuse
# tests/unit/test_openai_invoke.py:25 — `_make_client()` builds an OpenAIClient
#   via __new__ with the attributes invoke() touches (model, _lightweight_model,
#   _fallback_model, logger, _tool_manager, _json, _clients_by_loop, _locks_by_loop).
# tests/conftest.py:122 — `bind_sdk_client(monkeypatch)` fixture; see its use at
#   tests/unit/test_openai_invoke.py:46-47 (`mock_openai_client`).
# tests/clients/test_openai_compatible_defaults.py:235 — `_ASK_PAYLOAD_ROSTER` and
#   the following `test_ask_payload_model_never_leaks_gpt` show how an ask()
#   payload is captured with a fake `chat.completions.create`.
```

### Does NOT Exist
- ~~`OpenAIClient._chat_completion()`~~ — not overridden in `gpt.py`; the base funnel runs
- ~~`OpenAIClient.invoke()`~~ — not overridden; `OpenAIBaseClient.invoke` is what runs
- ~~`AbstractClient._model_output_cap()`~~ — not on `main`
- ~~`AbstractClient._resolve_max_tokens()`~~ — `dev`-only; on `main` it is `_resolve_invoke_max_tokens()` (`base.py:1778`) and `invoke()` calls it at `openai_base.py:1216`. Do not touch the number resolution.
- ~~a `reasoning_effort` parameter on `OpenAIClient`~~ — exists only on `MoonshotClient`
- ~~`packages/ai-parrot/tests/clients/test_structured_output_live_matrix.py`~~ — the spec cites this as the live-test pattern; **it is not on `main`**. Live gating lives in `packages/ai-parrot/tests/conftest.py:16` (task 4).

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot/src/parrot/clients/gpt.py — inside OpenAIClient, next to _default_model
#: OpenAI rejects ``max_tokens`` on gpt-5*/o-series
#: ("Unsupported parameter: 'max_tokens' ... Use 'max_completion_tokens' instead")
#: and accepts ``max_completion_tokens`` on every chat-completions model.
_uses_max_completion_tokens: bool = True
#: Reasoning models only honour the default temperature
#: ("Unsupported value: 'temperature' does not support 0.0 with this model").
#: Fragments, not dated ids — each one live-verified before being added.
_fixed_temperature_models: tuple[str, ...] = ("gpt-5",)   # extend ONLY with probed fragments
```

Live probe (run once, do **not** commit; paste results into the Completion Note):
```bash
source .venv/bin/activate
python - <<'PY'
import asyncio, os
from openai import AsyncOpenAI
async def probe(model):
    c = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        await c.chat.completions.create(model=model, messages=[{"role":"user","content":"Say OK."}],
                                        max_completion_tokens=32, temperature=0.0)
        return model, "200 accepts temperature"
    except Exception as e:  # noqa: BLE001
        return model, str(e)[:160]
async def main():
    for m in ["gpt-5-mini", "o1-mini", "o3-mini", "o4-mini", "gpt-4.1"]:
        print(*await probe(m), sep=" → ")
asyncio.run(main())
PY
```
A `400 ... temperature` result ⇒ add that family's fragment. A model-not-found
or billing error ⇒ **no evidence**, do not add (spec §7 "Empty credit balances
hide parameter bugs").

### Key Constraints
- Do not touch `_default_model`. Making the default work is the whole point.
- The three-path test must go through the real `ask()` / `ask_stream()` /
  `invoke()` bodies with a fake SDK, not through `_chat_completion` directly.
  For `ask_stream`, the fake `create` must return an async iterator (see how
  `tests/clients/test_openai_base_parity.py` or `tests/clients/test_openai_fallback.py`
  fake streaming, if either does; otherwise yield zero chunks and assert on the
  captured kwargs only).
- Python 3.10-compatible syntax (match the file).

### References in Codebase
- `tests/unit/test_openai_invoke.py` — client construction + `invoke()` mocking
- `tests/clients/test_openai_compatible_defaults.py:235-260` — ask() payload capture

---

## Acceptance Criteria

- [ ] `OpenAIClient._uses_max_completion_tokens is True`
- [ ] `OpenAIClient._fixed_temperature_models` contains `"gpt-5"` and only live-verified fragments; probe results recorded in the Completion Note
- [ ] For each of `ask()`, `ask_stream()`, `invoke()`: `gpt-5-mini` payload has `max_completion_tokens`, lacks `max_tokens` and `temperature`
- [ ] For each of the three paths: `gpt-4.1` payload keeps `temperature`
- [ ] Responses API path unchanged (`git diff` shows no edit near `gpt.py:486-489`)
- [ ] `_default_model` still `"gpt-5-mini"`
- [ ] Task 1 sweep narrowed; `pytest tests/clients/test_openai_base_adapt_params.py tests/clients/test_openai_reasoning_params.py tests/unit/test_openai_invoke.py tests/clients/test_openai_compatible_defaults.py -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/gpt.py` clean

---

## Test Specification

```python
# tests/clients/test_openai_reasoning_params.py
import pytest
from parrot.clients.gpt import OpenAIClient


def test_openai_client_opts_in():
    assert OpenAIClient._uses_max_completion_tokens is True
    assert "gpt-5" in OpenAIClient._fixed_temperature_models


PATHS = ["ask", "ask_stream", "invoke"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS)
async def test_gpt5_payload_uses_max_completion_tokens_and_drops_temperature(path, openai_payload_capture):
    """Each kwargs-assembly site reaches the SDK with the corrected payload."""
    client, seen, run = openai_payload_capture(model="gpt-5-mini")
    await run(path, max_tokens=64, temperature=0.0)
    assert seen["max_completion_tokens"] == 64
    assert "max_tokens" not in seen
    assert "temperature" not in seen


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS)
async def test_gpt41_payload_keeps_temperature(path, openai_payload_capture):
    client, seen, run = openai_payload_capture(model="gpt-4.1")
    await run(path, max_tokens=64, temperature=0.0)
    assert seen["max_completion_tokens"] == 64
    assert seen["temperature"] == 0.0
```

`openai_payload_capture` is a local fixture in the same file: build the client
as `tests/unit/test_openai_invoke.py::_make_client` does, attach a fake
`chat.completions` whose `create`/`parse` record kwargs (return a minimal
response with one `choices[0].message.content = "OK"` for `ask`/`invoke`, an
empty async iterator for `ask_stream`), and expose `run(path, **kw)` that
awaits `client.ask(...)`, drains `client.ask_stream(...)`, or awaits
`client.invoke(...)`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — HOTFIX-openai-max-completion-tokens-1 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm line anchors on your branch
4. **Update status** in `sdd/tasks/index/openai-max-completion-tokens.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below (include the probe table)

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-03
**Notes**: Set `_uses_max_completion_tokens = True` and
`_fixed_temperature_models = ("gpt-5",)` on `OpenAIClient`, with a comment
citing the two 400 error texts. Added
`tests/clients/test_openai_reasoning_params.py` with `test_openai_client_opts_in`
plus a three-path (`ask`/`ask_stream`/`invoke`) parametrized payload-capture
suite using the `bind_sdk_client` fixture (real `__init__`, fake
`chat.completions.create` distinguishing streaming vs. non-streaming by the
`stream` kwarg) — this exercises the real method bodies through the actual
`_chat_completion` funnel, not a monkeypatched shortcut. Did not touch
`tests/clients/test_openai_base_adapt_params.py`: `OpenAIClient` was never a
member of `WIRE_SUBCLASSES` (verified by reading
`test_openai_compatible_defaults.py` before editing), so there was nothing
to narrow for this task.
`pytest tests/clients/test_openai_base_adapt_params.py
tests/clients/test_openai_reasoning_params.py tests/unit/test_openai_invoke.py
tests/clients/test_openai_compatible_defaults.py -v` → 71 passed. `ruff check
packages/ai-parrot/src/parrot/clients/gpt.py` reports one PRE-EXISTING,
unrelated finding (`F401 InvokeResult imported but unused` at line 24,
confirmed via `git diff` to already exist before this task's edit) — not
fixed, out of scope (Cardinal Rule 5). `ruff check
tests/clients/test_openai_reasoning_params.py` clean. Responses API path
(`gpt.py:486-489` per spec numbering) untouched — `git diff` shows only the
two new class attributes.

**Probe results** (model → status): **No live probe was performed.**
`OPENAI_API_KEY` is not set in this environment/session (verified: `env |
grep -i openai` empty, no `.env` with real credentials in the worktree or
main repo root). Per the task's explicit instruction ("probe each ... before
adding; add none on speculation") and spec §7 ("empty credit balances /
missing credentials produce no evidence"), `o1`/`o3`/`o4` fragments were
**not** added. `_fixed_temperature_models` is limited to `("gpt-5",)`,
which is already live-verified per the spec's own §1/§2 evidence tables
(captured 2026-09-03 by the spec's author, prior to this task). This open
question (spec §8, bullet 2) remains open for a future session with live
credentials.

**Deviations from spec**: The task's literal Test Specification used
`temperature=0.0` for both the "dropped" and "kept" parametrized cases.
`OpenAIClient.ask()` has a pre-existing, unrelated bug: `if temperature:
args["temperature"] = temperature` (gpt.py) is a truthiness check, so an
explicit `temperature=0.0` is *never* forwarded into the request args for
`ask()` specifically — on every model, today, independent of this hotfix.
(`ask_stream()` and `invoke()` correctly use `is not None`.) Testing with
`0.0` would have made `test_gpt41_payload_keeps_temperature[ask]` fail for
a reason unrelated to `_adapt_completion_params()`, and would have made
`test_gpt5_payload_uses_max_completion_tokens_and_drops_temperature[ask]`
pass for the wrong reason (temperature never reaching the hook at all,
rather than the hook dropping it). Used `temperature=0.2`/`0.5`
(non-zero) instead, which correctly isolates the hook's behavior across
all three paths without touching the unrelated `ask()` bug — fixing that
bug is out of this hotfix's scope per the spec's Non-Goals and this
task's "NOT in scope" list (no edit to `gpt.py` beyond the two
attributes). Flagging it here rather than silently reinterpreting the
test, per the "when in doubt, note it" rule.
