# TASK-4894: Adapt OpenAI completion params — `max_completion_tokens` + fixed `temperature`

**Feature**: FEAT-770 — OpenAI client fixes
**Spec**: `sdd/specs/openai-client-fixes.spec.md`
**Discovered-from**: `issue:d641d02cf6b5`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §1–§3 Module 1. `OpenAIClient()`'s default model `gpt-5-mini` rejects `max_tokens` (400) and any
non-default `temperature` (400). Add one protected hook in the shared `_chat_completion` funnel,
opt `OpenAIClient` in, and route the two direct SDK calls in `OpenAIClient` through the funnel.

---

## Scope

- `OpenAIBaseClient`: class attributes `_uses_max_completion_tokens: bool = False`,
  `_fixed_temperature_prefixes: tuple[str, ...] = ()`; method `_adapt_completion_params(model, kwargs)`
  returning a new dict; call it as the first statement of `_chat_completion`.
- `OpenAIClient`: `_uses_max_completion_tokens = True`,
  `_fixed_temperature_prefixes = ("gpt-5", "o1", "o3", "o4")`.
- `OpenAIClient.ask_to_image` and `OpenAIClient.image_identification`: replace
  `await self.client.chat.completions.create(...)` with
  `await self._chat_completion(model=..., messages=..., use_tools=True, ...)` (same kwargs).
- New unit tests (spec §4).

**NOT in scope**: `MoonshotClient`, Responses-API args, the `gpt-5-nano` guard in `OpenAIClient.ask()`,
`_default_model`.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot/src/parrot/clients/openai_base.py` | MODIFY |
| `packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py` | MODIFY |
| `packages/ai-parrot-client-openai/tests/unit/test_openai_completion_params.py` | CREATE |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.openai_base import OpenAIBaseClient
from parrot.clients.openai import OpenAIClient
```

### Existing Signatures
```python
class OpenAIBaseClient(AbstractClient):                                   # openai_base.py:73
    async def _chat_completion(self, model: str, messages: Any, use_tools: bool = False,
                               stream: bool = False, **kwargs) -> Any:    # openai_base.py:228
    async def invoke(..., temperature: float = 0.0, ...)                  # openai_base.py:1526
class OpenAIClient(OpenAIBaseClient):
    async def ask_to_image(...)            # direct chat.completions.create, client.py:1531
    async def image_identification(...)    # direct chat.completions.create, client.py:2048
```
`OpenAIBaseClient(api_key="x", base_url="http://x")` instantiates (no abstract methods).

### Does NOT Exist
- `_adapt_completion_params`, `_uses_max_completion_tokens`, `_fixed_temperature_prefixes` (created here).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/clients/openai_base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-openai/tests/unit/test_openai_completion_params.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/openai_base.py#OpenAIBaseClient._chat_completion",
    "sym:packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py#OpenAIClient.ask_to_image",
    "sym:packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py#OpenAIClient.image_identification"
  ]
}
```

---

## Implementation Notes

- Never mutate the input dict: `ask()` reuses `args` for capacity-fallback retries and tool rounds.
- A `max_tokens` of `None` produces no cap key at all.
- If both keys are present, the explicit `max_completion_tokens` wins and `max_tokens` is dropped.
- Prefix match on `model.lower()`; never substring (avoid matching inside unrelated ids).
- The hook must run before the budgeted-scope branch so `_chat_completion_budgeted` sees adapted kwargs.

---

## Acceptance Criteria

- [ ] Spec §5 criteria hold.
- [ ] `ruff check` clean on the changed files.

## Validation Commands
- `pytest packages/ai-parrot-client-openai/tests/unit/test_openai_completion_params.py -q`
- `pytest packages/ai-parrot/tests/test_openai_client.py -q`

---

## Test Specification

See spec §4 Unit Tests. Capture wire kwargs by replacing `client.client` with a `MagicMock` whose
`chat.completions.create` / `.parse` are `AsyncMock`s returning a minimal response.

---

## Agent Instructions

Implement exactly the scope above inside the FEAT-770 worktree; run tests with
`PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-openai/src`.

---

## Completion Note

**Completed**: 2026-10-30 — verified. Implementing commit `08655037b`.

- `OpenAIBaseClient`: `_uses_max_completion_tokens` / `_fixed_temperature_prefixes` (inert defaults) and
  `_adapt_completion_params`, run as the first statement of `_chat_completion` (before the budgeted branch).
- `OpenAIClient` opts in (`gpt-5`, `o1`, `o3`, `o4`); `ask_to_image` and `image_identification` now call
  `_chat_completion(use_tools=True)` instead of the SDK directly.
- Tests: 14 new in `test_openai_completion_params.py`, all pass. Validation Contract: 201 passed; the 8 failures
  (`test_openai_client.py` ×4 — assigns the loop-local `client.client`; `test_vllm_client.py` list_models ×3;
  `test_nvidia_client.py` live kimi e2e) fail identically on unmodified `dev` 5879b0ade — pre-existing, not touched.
- Live check 2026-10-30 against the OpenAI API on this tree: `OpenAIClient().ask(temperature=0.2)` (default
  `gpt-5-mini`) and `invoke(model="gpt-5-mini")` both returned "OK" (both 400'd before).
- `ruff --fix` also rewrote 3 unrelated pre-existing lines in `client.py`; reverted to keep scope. Remaining
  `ASYNC240` at `client.py` image_identification is pre-existing.

Resolves `issue:d641d02cf6b5`.
