# TASK-1747: Factory Registration and Dependencies

**Feature**: FEAT-302 — Native Bedrock Client (Converse API) + Nova 2 Sonic
**Spec**: `sdd/specs/bedrock-client-llm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1745
**Assigned-to**: unassigned

---

## Context

Register the new `BedrockConverseClient` in the factory so it can be instantiated via `create_client("bedrock-converse")`. Also add `aioboto3` as an optional dependency in `pyproject.toml`.

Implements Spec Module 6.

---

## Scope

- Add `"bedrock-converse"` → `BedrockConverseClient` to `SUPPORTED_CLIENTS` dict in `factory.py`
- Use lazy import pattern (same as existing `_lazy_gemma4`)
- Add `aioboto3>=13.0.0` to `pyproject.toml` under a new `[bedrock-converse]` extra
- Keep existing `"bedrock"` → `AnthropicClient` mapping untouched for backward compatibility
- Add `"bedrock-converse"` to `PROVIDER_BACKEND` if needed

**NOT in scope**: BedrockConverseClient implementation (TASK-1745), NovaSonicClient, voice integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | Add lazy import and `SUPPORTED_CLIENTS` entry |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Add `bedrock-converse` extra with `aioboto3` |
| `tests/clients/test_factory_bedrock.py` | CREATE | Unit test for factory resolution |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.factory import SUPPORTED_CLIENTS, PROVIDER_BACKEND  # verified: factory.py:48, 78
```

### Existing Signatures to Use
```python
# parrot/clients/factory.py:48
SUPPORTED_CLIENTS: Dict[str, Type[AbstractClient]] = {
    "anthropic": AnthropicClient,
    "bedrock": AnthropicClient,  # FEAT-232 — keep this!
    "openai": OpenAIClient,
    # ...
}

# parrot/clients/factory.py:78
PROVIDER_BACKEND: Dict[str, str] = {
    "bedrock": "bedrock",
    "anthropic-aws": "aws",
}

# parrot/clients/factory.py:16 (lazy loader pattern)
def _lazy_gemma4():
    from parrot.clients.gemma4 import Gemma4Client
    return Gemma4Client
```

### Does NOT Exist
- ~~`SUPPORTED_CLIENTS["bedrock-converse"]`~~ — not yet; this task adds it
- ~~`aioboto3` in pyproject.toml~~ — not yet a dependency
- ~~`_lazy_bedrock_converse()`~~ — not yet; this task creates it

---

## Implementation Notes

### Lazy Import Pattern
```python
def _lazy_bedrock_converse():
    from parrot.clients.bedrock import BedrockConverseClient
    return BedrockConverseClient

# In SUPPORTED_CLIENTS:
"bedrock-converse": _lazy_bedrock_converse,
```

### pyproject.toml Change
```toml
[project.optional-dependencies]
bedrock-converse = [
    "aioboto3>=13.0.0",
]
```

### Key Constraints
- `"bedrock"` key MUST remain pointing to `AnthropicClient` (backward compat, FEAT-232)
- The lazy import avoids `ImportError` when `aioboto3` is not installed
- The existing `bedrock` extra in pyproject.toml (lines 348-353) is for `anthropic[aws]` — keep it

---

## Acceptance Criteria

- [ ] `SUPPORTED_CLIENTS["bedrock-converse"]` resolves to `BedrockConverseClient`
- [ ] `SUPPORTED_CLIENTS["bedrock"]` still resolves to `AnthropicClient` (no regression)
- [ ] `pyproject.toml` has `bedrock-converse` extra with `aioboto3>=13.0.0`
- [ ] Lazy import pattern prevents `ImportError` when `aioboto3` is not installed
- [ ] All tests pass: `pytest tests/clients/test_factory_bedrock.py -v`

---

## Test Specification

```python
# tests/clients/test_factory_bedrock.py
import pytest
from parrot.clients.factory import SUPPORTED_CLIENTS


class TestFactoryBedrockConverse:
    def test_bedrock_converse_registered(self):
        assert "bedrock-converse" in SUPPORTED_CLIENTS

    def test_bedrock_legacy_preserved(self):
        from parrot.clients.claude import AnthropicClient
        client_cls = SUPPORTED_CLIENTS["bedrock"]
        if callable(client_cls) and not isinstance(client_cls, type):
            client_cls = client_cls()
        assert client_cls is AnthropicClient or issubclass(client_cls, AnthropicClient)

    def test_lazy_import(self):
        resolver = SUPPORTED_CLIENTS["bedrock-converse"]
        if callable(resolver) and not isinstance(resolver, type):
            cls = resolver()
        else:
            cls = resolver
        assert cls.__name__ == "BedrockConverseClient"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context
2. **Verify** TASK-1745 is completed — `bedrock.py` must exist with `BedrockConverseClient`
3. **Read** `factory.py` to confirm current `SUPPORTED_CLIENTS` layout
4. **Read** `pyproject.toml` to confirm existing `bedrock` extra at lines 348-353
5. **Add** the lazy loader, factory entry, and dependency
6. **Run tests** and verify no regressions

---

## Completion Note

Added `_lazy_bedrock_converse()` (same pattern as `_lazy_gemma4()`) and a
`"bedrock-converse": _lazy_bedrock_converse` entry to `SUPPORTED_CLIENTS`
in `factory.py`, immediately after the existing `"bedrock": AnthropicClient`
entry (left untouched — verified via `test_bedrock_legacy_preserved`). No
`PROVIDER_BACKEND` entry was added: that dict only exists to inject a
`backend=` kwarg into `AnthropicClient`'s constructor for the shared-class
`"bedrock"`/`"anthropic-aws"` keys — `BedrockConverseClient` is a distinct
class with no such backend-selection concept, so nothing needed there.

Added an `aioboto3` extra to `packages/ai-parrot/pyproject.toml`.

**Naming discrepancy flagged for review**: the spec (§3 Module 6, §5
Acceptance Criteria) names this extra `bedrock-native`, but this task's own
Scope/Implementation Notes/Acceptance Criteria all explicitly say
`bedrock-converse` with `aioboto3>=13.0.0`. Followed the task file's
explicit instructions (the literal governing document for this unit of
work) — extra is named `bedrock-converse`, matching the acceptance
criterion "`pyproject.toml` has `bedrock-converse` extra with
`aioboto3>=13.0.0`" in this task file verbatim. If the `bedrock-native`
name from the spec is required for consistency with the rest of the FEAT-302
acceptance criteria, a follow-up rename (or an additional alias extra) may
be needed — noted here rather than guessing.

Created `packages/ai-parrot/tests/clients/test_factory_bedrock.py` — the
task's 3 scaffolded tests plus one additional end-to-end test
(`test_create_via_llm_factory`) that resolves `"bedrock-converse:claude-sonnet-4-5"`
through `LLMFactory.create()` and asserts a real `BedrockConverseClient`
instance is returned. All 4 pass; `ruff check` clean;
`packages/ai-parrot/pyproject.toml` parses correctly via `tomllib`; full
`tests/clients/` suite re-run shows only the 2 pre-existing, unrelated
`test_google_computer_use.py` failures — no regressions.
