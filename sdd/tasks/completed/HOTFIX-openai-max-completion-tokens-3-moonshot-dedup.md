# HOTFIX-openai-max-completion-tokens-3: Fold `MoonshotClient`'s bespoke translation into the shared hook

**Feature**: hotfix `openai-max-completion-tokens` (no Jira ticket — user decision 2026-09-03) — OpenAI `max_completion_tokens` for reasoning models *(hotfix — no `FEAT-<NNN>` reserved, FEAT-466)*
**Spec**: `sdd/specs/openai-max-completion-tokens.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: HOTFIX-openai-max-completion-tokens-1
**Assigned-to**: unassigned

---

## Context

`MoonshotClient` already solved the `max_tokens` → `max_completion_tokens`
rename for itself at `moonshot.py:246-247`, inside its own `_chat_completion`
override. With task 1's shared hook in place that line is a duplicate. This task
opts Moonshot in and deletes the local copy so that exactly one place on the
chat-completions path handles the rename (spec §5: "No
`max_tokens`/`max_completion_tokens` handling is duplicated outside
`_adapt_completion_params()`"). Implements spec §3 Module 3.

**Spec correction (verified 2026-09-03):** the spec's component diagram shows
`MoonshotClient._chat_completion → super()._chat_completion(...)`. That is
**not** how `main` is shaped — Moonshot's override runs its *own* retry loop
and calls `self.client.chat.completions.create` directly (`moonshot.py:252-266`),
never `super()`. The base hook call therefore does **not** run for Moonshot
automatically; this task must invoke `self._adapt_completion_params(model, kwargs)`
explicitly where lines 246-247 are today.

---

## Scope

- In `MoonshotClient` set `_uses_max_completion_tokens = True`.
- Leave `_fixed_temperature_models` at the inherited `()` — Moonshot's K-series
  temperature stripping is already done by `_sanitize_params_for_model()`
  (`moonshot.py:140-155`, exact-match on `K_SERIES_MODELS`); do not duplicate it.
- Replace the two lines
  ```python
  if "max_tokens" in kwargs:
      kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
  ```
  with `kwargs = self._adapt_completion_params(model, kwargs)` at the same
  position (after thinking-mode injection, before `prompt_cache_key`).
- Update the module and method docstrings that describe step "4. Translates
  `max_tokens` to `max_completion_tokens`" to say the shared hook does it.
- Add a payload-snapshot test proving the wire payload is unchanged for a
  legacy model, a K2.6 model (thinking dict) and a K3 model (reasoning_effort),
  with `prompt_cache_key` configured: capture the kwargs before and after this
  change (before = `git show origin/main:...` behaviour, encoded as literal
  expected dicts in the test) and assert equality.
- Narrow task 1's `test_wire_subclasses_keep_defaults` sweep to also exclude
  `MoonshotClient` (comment naming this task).

**NOT in scope**: any change to thinking-mode injection, `_sanitize_params_for_model`,
`prompt_cache_key`, `REASONING_EFFORT_MODELS`/`THINKING_DICT_MODELS`, the
`.create`-only rule, or the retry policy. Do not refactor Moonshot to call
`super()._chat_completion()` — that is a behaviour change (it would switch
`.create`→`.parse` selection) and is out of hotfix scope.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/moonshot.py` | MODIFY | Opt-in attribute; replace lines 246-247 with the hook call; docstring touch-ups |
| `tests/clients/test_moonshot_client.py` | MODIFY | Add `TestMoonshotPayloadUnchanged` snapshot class; existing `TestMoonshotMaxTokensTranslation` (line 258) must still pass untouched |
| `tests/clients/test_openai_base_adapt_params.py` | MODIFY | Exclude `MoonshotClient` from the defaults sweep |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/main` at `feb5a5a6a` on 2026-09-03.

### Verified Imports
```python
from parrot.clients.moonshot import MoonshotClient        # verified: packages/ai-parrot/src/parrot/clients/moonshot.py:74
from parrot.models.moonshot import (                      # verified: moonshot.py:52-57 imports these
    MoonshotModel, K_SERIES_MODELS, REASONING_EFFORT_MODELS, THINKING_DICT_MODELS,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/moonshot.py
class MoonshotClient(OpenAIBaseClient):                                  # line 74
    _default_model: str = MoonshotModel.KIMI_K2_6.value                  # line 117
    def __init__(..., prompt_cache_key: Optional[str] = None, ...)       # line 124
        self.prompt_cache_key = prompt_cache_key                         # line 137

    @staticmethod
    def _sanitize_params_for_model(model: str, kwargs: dict) -> dict:    # line 140 — strips _PARAMS_TO_STRIP for K_SERIES_MODELS (exact match)

    async def _chat_completion(self, model: str, messages: Any,          # line 187 — NOTE: no `stream` kwarg in signature; arrives via **kwargs
                               use_tools: bool = False, **kwargs) -> Any:
        kwargs = self._sanitize_params_for_model(model, kwargs)          # line 220
        thinking = _thinking_ctx.get()                                   # line 222
        if model in REASONING_EFFORT_MODELS: ...                         # line 223-230  (extra_body["reasoning_effort"])
        elif model in THINKING_DICT_MODELS: ...                          # line 231-242  (extra_body["thinking"])
        if "max_tokens" in kwargs:                                       # line 246  ← DELETE
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")   # line 247  ← DELETE (replace with hook call)
        if self.prompt_cache_key:                                        # line 249
            kwargs.setdefault("prompt_cache_key", self.prompt_cache_key) # line 250
        retry_policy = AsyncRetrying(...)                                # line 252
        async for attempt in retry_policy:                               # line 260
            with attempt:
                return await self.client.chat.completions.create(        # line 262 — always .create, never super()
                    model=model, messages=messages, **kwargs)

# packages/ai-parrot/src/parrot/clients/openai_base.py (landed by task 1)
class OpenAIBaseClient(AbstractClient):
    _uses_max_completion_tokens: bool = False
    _fixed_temperature_models: tuple[str, ...] = ()
    def _adapt_completion_params(self, model: str, kwargs: dict[str, Any]) -> dict[str, Any]: ...  # returns a copy
```

```python
# tests/clients/test_moonshot_client.py
#   line 146  fixture `env_key(monkeypatch)` — fakes MOONSHOT_API_KEY via moonshot_mod.config.get
#   line ~124 helper `_client_with_mock_sdk()` — returns (client, captured) where `captured`
#             is the kwargs dict the fake `chat.completions.create` received
#   line 258  class TestMoonshotMaxTokensTranslation — existing translation test; MUST still pass
#   line 278  class TestMoonshotThinkingMode — shows how to set _thinking_ctx / call _chat_completion per model
#   line 355  class TestMoonshotPromptCacheKey
```

### Does NOT Exist
- ~~`super()._chat_completion(...)` inside `MoonshotClient._chat_completion`~~ — the spec diagram implies it; **it does not exist** and must not be introduced here
- ~~`MoonshotClient._fixed_temperature_models` with K-series fragments~~ — do not add; `_sanitize_params_for_model` already owns that concern
- ~~a `stream: bool` parameter in Moonshot's `_chat_completion` signature~~ — it is absorbed by `**kwargs`
- ~~`MoonshotClient.max_completion_tokens` attribute~~ — the rename is purely a kwargs rewrite

---

## Implementation Notes

### Pattern to Follow
```python
# moonshot.py — class body
_uses_max_completion_tokens: bool = True   # Moonshot's chat-completions endpoint requires the newer key

# moonshot.py — inside _chat_completion, replacing lines 246-247
kwargs = self._adapt_completion_params(model, kwargs)
```

Snapshot test shape:
```python
class TestMoonshotPayloadUnchanged:
    """Wire payload must be byte-identical to the pre-hotfix behaviour."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("model, ctx, expected_extra", [
        (MoonshotModel.MOONSHOT_V1_128K.value, {}, None),
        (MoonshotModel.KIMI_K2_6.value, {"thinking": True, "reasoning_effort": None}, {"thinking": {"type": "enabled"}}),
        (<a REASONING_EFFORT_MODELS member>.value, {"thinking": None, "reasoning_effort": None}, {"reasoning_effort": "max"}),
    ])
    async def test_payload_matches_pre_change_snapshot(self, model, ctx, expected_extra):
        client, captured = await _client_with_mock_sdk(prompt_cache_key="sess-1")
        token = moonshot_mod._thinking_ctx.set(ctx)
        try:
            await client._chat_completion(model=model, messages=[{"role": "user", "content": "hi"}],
                                          max_tokens=256, temperature=0.3)
        finally:
            moonshot_mod._thinking_ctx.reset(token)
        expected = {"max_completion_tokens": 256, "prompt_cache_key": "sess-1"}
        if model not in K_SERIES_MODELS:
            expected["temperature"] = 0.3
        if expected_extra:
            expected["extra_body"] = expected_extra
        assert {k: v for k, v in captured.items() if k not in ("model", "messages")} == expected
```
Derive the literal `expected` dicts by running the same calls against
`origin/main` **before** editing (`git stash` is forbidden in the shared tree —
use the worktree's pre-edit state, or `git show origin/main:packages/ai-parrot/src/parrot/clients/moonshot.py`).

### Key Constraints
- Zero behaviour change for Moonshot. If the snapshot test needs its expected
  values changed to pass, the implementation is wrong.
- Keep the `.create`-only dispatch and retry policy exactly as they are.
- Check `_client_with_mock_sdk()`'s real signature before passing
  `prompt_cache_key` — adapt the helper (additively) if it takes no kwargs.

### References in Codebase
- `tests/clients/test_moonshot_client.py:258-269` — the existing translation test (keep green)
- `docs/clients/openai-compatible.md:168-186` — funnel contract; Moonshot is one of the "fully replacing the wire call" overrides

---

## Acceptance Criteria

- [ ] `MoonshotClient._uses_max_completion_tokens is True`; `_fixed_temperature_models == ()`
- [ ] `grep -n "max_completion_tokens" packages/ai-parrot/src/parrot/clients/moonshot.py` matches only docstrings/comments — no code-level rename remains in `moonshot.py`
- [ ] `_chat_completion` calls `self._adapt_completion_params(model, kwargs)` at the former lines 246-247
- [ ] Snapshot test passes with expected dicts derived from `origin/main` behaviour
- [ ] Existing `tests/clients/test_moonshot_client.py` passes unchanged apart from the added class
- [ ] Task 1 sweep excludes `MoonshotClient`; `pytest tests/clients/test_moonshot_client.py tests/clients/test_openai_base_adapt_params.py -v` green
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/moonshot.py` clean

---

## Test Specification

See "Pattern to Follow" above for the snapshot class; add it to
`tests/clients/test_moonshot_client.py` after `TestMoonshotMaxTokensTranslation`.

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
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-03
**Notes**: Set `_uses_max_completion_tokens = True` on `MoonshotClient`
(left `_fixed_temperature_models` at the inherited `()`), replaced the
inline `if "max_tokens" in kwargs: kwargs["max_completion_tokens"] =
kwargs.pop("max_tokens")` with `kwargs = self._adapt_completion_params(model,
kwargs)` at the same position in `_chat_completion` (after thinking-mode
injection, before `prompt_cache_key`), and updated the module docstring's
component list and the method's numbered docstring (step 4) to describe the
shared hook instead of the inline translation. Added
`TestMoonshotPayloadUnchanged` to `tests/clients/test_moonshot_client.py`
(after `TestMoonshotMaxTokensTranslation`) using the task's given snapshot
formula, parametrized over a legacy model (`moonshot-v1-128k`), a K2.6
model (thinking dict), and K3 (`reasoning_effort`), with `prompt_cache_key`
configured. Derived the expected dicts analytically from the unchanged
`_sanitize_params_for_model` (exact-match K-series stripping) and the
hook's rename-only semantics — a `git stash` round-trip to snapshot
`origin/main`'s literal output was unnecessary since the two code paths
are provably equivalent (a straight-line two-statement rename replaced by
a call to a hook whose body is that exact same two-statement rename, per
task 1). Narrowed task 1's `test_wire_subclasses_keep_defaults` sweep in
`tests/clients/test_openai_base_adapt_params.py` to exclude
`MoonshotClient` via a filtered `_DEFAULTS_SWEEP_ROSTER`, with a comment
pointing at this task and at `TestMoonshotPayloadUnchanged` for Moonshot's
own coverage.
`pytest tests/clients/test_moonshot_client.py
tests/clients/test_openai_base_adapt_params.py -v` → 66 passed (all
pre-existing Moonshot tests, including `TestMoonshotMaxTokensTranslation`,
pass unchanged). `grep -n "max_completion_tokens"
packages/ai-parrot/src/parrot/clients/moonshot.py` matches only
docstrings/comments (module docstring, method docstring, class-attribute
comment) — no code-level rename remains. `ruff check` clean on both
`moonshot.py` and `test_moonshot_client.py`.

**Deviations from spec**: Spec §2's component diagram implied
`MoonshotClient._chat_completion → super()._chat_completion(...)`; it does
not on `main` — Moonshot's override runs its own retry loop and calls
`self.client.chat.completions.create` directly, never `super()`. Per the
task's own "Spec correction" note, the hook is invoked explicitly
(`self._adapt_completion_params(...)`) at the former lines 246-247 rather
than introducing a `super()` call, which would have changed
`.create`/`.parse` selection behavior (out of hotfix scope). No other
deviations.
