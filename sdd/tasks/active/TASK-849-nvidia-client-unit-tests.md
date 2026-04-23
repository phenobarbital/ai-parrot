# TASK-849: Unit tests for NvidiaClient

**Feature**: FEAT-122 — Nvidia Client
**Spec**: `sdd/specs/nvidia-client.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-847, TASK-848
**Assigned-to**: unassigned

---

## Context

Write unit tests for `NvidiaClient` covering initialization, env-var
fallback for `NVIDIA_API_KEY`, the `enable_thinking` `extra_body`
merge helper, and factory registration. No live Nvidia calls — mock
where needed.

Implements Module 4 of the spec (§3 Module Breakdown) and maps to §4
Test Specification (Unit Tests table).

---

## Scope

- Create `packages/ai-parrot/tests/test_nvidia_client.py`.
- Implement the 11 unit tests listed in spec §4 Test Specification.
- Live integration tests (`test_completion_e2e_kimi`, `test_streaming_e2e_glm_reasoning`)
  are listed in §4 Integration Tests but are OUT OF SCOPE here — they
  require a live `NVIDIA_API_KEY`. Leave placeholders skipped via
  `pytest.mark.skipif(not os.getenv("NVIDIA_API_KEY"), reason=...)`.

**NOT in scope**:
- Live network tests in CI.
- Testing the parent `OpenAIClient` — already covered by
  `packages/ai-parrot/tests/test_openai_client.py`.
- Testing AsyncOpenAI internals.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/test_nvidia_client.py` | CREATE | Unit tests for `NvidiaClient` and factory registration |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Under-test
from parrot.clients.nvidia import NvidiaClient       # created by TASK-847
from parrot.models.nvidia import NvidiaModel         # created by TASK-846
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS   # modified by TASK-848

# Pytest / mocking
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/gpt.py:90
class OpenAIClient(AbstractClient):
    client_type: str = 'openai'
    model: str = OpenAIModel.GPT4_TURBO.value
    _default_model: str = 'gpt-4o-mini'
    def __init__(self, api_key=None, base_url="https://api.openai.com/v1", **kwargs): ...
    async def get_client(self) -> AsyncOpenAI: ...
```

Reference test layout (mirror it):
```python
# packages/ai-parrot/tests/test_openrouter_client.py (abbreviated)
@pytest.fixture
def client():
    return OpenRouterClient(api_key="test-key-123", ...)

class TestOpenRouterClientInit:
    def test_default_base_url(self, client):
        assert client.base_url == "https://openrouter.ai/api/v1"
    def test_client_type(self, client):
        assert client.client_type == "openrouter"
    def test_api_key_stored(self, client):
        assert client.api_key == "test-key-123"
    ...
```

### Does NOT Exist
- ~~`NvidiaClient.list_models`~~ — not implemented in this spec; do NOT test.
- ~~A separate `NvidiaUsage` class~~ — non-goal per spec §1.
- ~~`pytest.mark.nvidia`~~ — not a registered marker; use `skipif` instead.
- ~~`parrot.testing.llm_fixtures`~~ — no such package; use `conftest.py`
  fixtures or define locally.

---

## Implementation Notes

### Pattern to Follow
Mirror `packages/ai-parrot/tests/test_openrouter_client.py` — class-based
grouping (`TestNvidiaClientInit`, `TestNvidiaThinkingHelper`,
`TestNvidiaFactory`), pytest fixtures at module top, no network.

### Required tests (all must be implemented)

| Test method | Class | Description |
|---|---|---|
| `test_client_init_explicit_key` | `TestNvidiaClientInit` | `NvidiaClient(api_key="x")` stores `"x"` as `client.api_key`. |
| `test_client_init_env_fallback` | `TestNvidiaClientInit` | With `api_key=None`, client falls back to `config.get("NVIDIA_API_KEY")`. Patch `parrot.clients.nvidia.config.get` to return `"env-nvidia-key"`. |
| `test_client_base_url` | `TestNvidiaClientInit` | `client.base_url == "https://integrate.api.nvidia.com/v1"`. |
| `test_client_type_and_name` | `TestNvidiaClientInit` | `client.client_type == "nvidia"` and `client.client_name == "nvidia"`. |
| `test_default_model` | `TestNvidiaClientInit` | `NvidiaClient._default_model == NvidiaModel.KIMI_K2_INSTRUCT_0905.value`. |
| `test_enable_thinking_injects_extra_body` | `TestNvidiaThinkingHelper` | Calling `_merge_thinking_extra_body(None, True, False)` returns a dict with `chat_template_kwargs == {"enable_thinking": True, "clear_thinking": False}`. |
| `test_enable_thinking_preserves_existing_extra_body` | `TestNvidiaThinkingHelper` | `_merge_thinking_extra_body({"k": 1, "chat_template_kwargs": {"other": 1}}, True, True)` keeps `"k"` and `"other"` keys and adds the thinking flags. |
| `test_enable_thinking_default_off` | `TestNvidiaThinkingHelper` | `_merge_thinking_extra_body(None, False, False)` returns `None`; `_merge_thinking_extra_body({"k":1}, False, True)` returns `{"k":1}` unchanged. |
| `test_nvidia_model_enum_values` | `TestNvidiaModelEnum` | All 9 listed slugs are present and their `.value` matches the exact strings in the spec. |
| `test_factory_registration` | `TestNvidiaFactory` | `SUPPORTED_CLIENTS["nvidia"] is NvidiaClient`; `LLMFactory.create("nvidia:moonshotai/kimi-k2-thinking")` returns an `NvidiaClient` with `model == "moonshotai/kimi-k2-thinking"`. |
| `test_factory_default_model` | `TestNvidiaFactory` | `LLMFactory.create("nvidia")` returns an `NvidiaClient` instance (model is not set explicitly; `_default_model` kicks in at call time). |

### Fixture sketch
```python
import pytest
from unittest.mock import patch

from parrot.clients.nvidia import NvidiaClient
from parrot.models.nvidia import NvidiaModel


@pytest.fixture
def client():
    return NvidiaClient(api_key="test-key-123")


@pytest.fixture
def env_key(monkeypatch):
    """Patch navconfig.config.get so NvidiaClient() (no api_key) picks up a fake key."""
    from parrot.clients import nvidia as nvidia_mod
    original = nvidia_mod.config.get

    def fake_get(key, default=None):
        if key == "NVIDIA_API_KEY":
            return "env-nvidia-key"
        return original(key, default) if default is not None else original(key)

    monkeypatch.setattr(nvidia_mod.config, "get", fake_get)
    return "env-nvidia-key"
```

### Key Constraints
- No live HTTP: patch or avoid `AsyncOpenAI` calls. The init tests do
  NOT need to construct the SDK client (`get_client` is lazy); they only
  construct `NvidiaClient(...)` and assert attribute state.
- `_merge_thinking_extra_body` is a `@staticmethod`, so tests can call it
  on the class directly: `NvidiaClient._merge_thinking_extra_body(...)`.
- Tests must not require `NVIDIA_API_KEY` to be present in the environment.
  For the `env_key` fixture, patch `config.get`, not `os.environ`.
- Keep all tests synchronous (`def test_...`). None of the listed tests
  need `asyncio` — the client constructor is sync and the helper is sync.
- Run with: `pytest packages/ai-parrot/tests/test_nvidia_client.py -v`.

### References in Codebase
- `packages/ai-parrot/tests/test_openrouter_client.py` — direct template.
- `packages/ai-parrot/tests/conftest.py` — baseline fixtures.

---

## Acceptance Criteria

- [ ] File `packages/ai-parrot/tests/test_nvidia_client.py` exists.
- [ ] All 11 tests listed above are implemented.
- [ ] `pytest packages/ai-parrot/tests/test_nvidia_client.py -v` passes with 11 tests collected and 0 failures.
- [ ] No test requires network access or a real `NVIDIA_API_KEY`.
- [ ] No test mutates global state without cleanup (use `monkeypatch`).
- [ ] No linting errors: `ruff check packages/ai-parrot/tests/test_nvidia_client.py`.

---

## Test Specification

The tests listed above ARE the specification. Implement them exactly.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** — TASK-847 and TASK-848 must be in `tasks/completed/`.
3. **Verify the Codebase Contract** — before writing tests:
   - `read packages/ai-parrot/src/parrot/clients/nvidia.py` to confirm the
     `NvidiaClient` signature and `_merge_thinking_extra_body` helper shape.
   - `read packages/ai-parrot/src/parrot/models/nvidia.py` to confirm the
     enum members match the spec.
   - `read packages/ai-parrot/src/parrot/clients/factory.py` to confirm
     the `"nvidia"` key is registered.
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID.
5. **Implement** the 11 tests. Keep them tight — no over-parameterization.
6. **Run** `pytest packages/ai-parrot/tests/test_nvidia_client.py -v` and
   confirm all pass.
7. **Verify** all acceptance criteria are met.
8. **Move this file** to `tasks/completed/TASK-849-nvidia-client-unit-tests.md`.
9. **Update index** → `"done"`.
10. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
