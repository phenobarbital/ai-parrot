# TASK-1711: Unit & Integration Tests for A2A and MSAgent Integrations

**Feature**: FEAT-271 — MSAgent & A2A YAML Integrations
**Spec**: `sdd/specs/msagent-a2a-integrations.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1706, TASK-1707, TASK-1708, TASK-1709, TASK-1710
**Assigned-to**: unassigned

---

## Context

This task writes the comprehensive test suite for the entire FEAT-271 integration. It covers config parsing, dispatch wiring, A2A startup, MSAgent startup, discovery registry, and security middleware. Tests use mocking to avoid requiring live services.

Implements spec §3 Module 7.

---

## Scope

- Create test file for A2A config (`tests/integrations/test_a2a_config.py`).
- Create test file for MSAgent config (`tests/integrations/test_msagent_config.py`).
- Create test file for config dispatch (`tests/integrations/test_config_dispatch.py`).
- Create test file for A2A startup (`tests/integrations/test_a2a_startup.py`).
- Create test file for MSAgent startup (`tests/integrations/test_msagent_startup.py`).
- Create test file for discovery registry (`tests/integrations/test_a2a_discovery.py`).
- Ensure all tests pass: `pytest tests/integrations/ -v`.

**NOT in scope**: E2E tests against live services, load tests, security penetration tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integrations/__init__.py` | CREATE (if missing) | Package init |
| `tests/integrations/test_a2a_config.py` | CREATE | A2AAgentConfig unit tests |
| `tests/integrations/test_msagent_config.py` | CREATE | MSAgentIntegrationConfig unit tests |
| `tests/integrations/test_config_dispatch.py` | CREATE | IntegrationBotConfig.from_dict dispatch tests |
| `tests/integrations/test_a2a_startup.py` | CREATE | A2A bot startup integration tests |
| `tests/integrations/test_msagent_startup.py` | CREATE | MSAgent bot startup integration tests |
| `tests/integrations/test_a2a_discovery.py` | CREATE | Discovery registry + directory endpoint tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Config classes
from parrot.integrations.a2a.models import A2AAgentConfig               # TASK-1706
from parrot.integrations.msagentsdk.models import MSAgentIntegrationConfig  # TASK-1707
from parrot.integrations.msagentsdk.models import MSAgentSDKConfig      # existing
from parrot.integrations.models import IntegrationBotConfig             # existing

# Test utilities
import pytest                                     # test runner
from unittest.mock import AsyncMock, MagicMock, patch  # stdlib mocking
from aiohttp import web                           # for app fixtures
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop  # aiohttp test support
```

### Existing Test Patterns
```python
# Check existing test directory structure
# tests/ — top-level test directory
# tests/integrations/ — may or may not exist yet
# Use pytest-asyncio for async tests: @pytest.mark.asyncio
```

### Does NOT Exist
- ~~`tests/integrations/`~~ — directory may not exist; create `__init__.py` if needed
- ~~`parrot.integrations.testing`~~ — no test utility module; use stdlib mocks
- ~~`IntegrationBotManager.create_test_instance()`~~ — no such factory; mock manually

---

## Implementation Notes

### Test Categories

**1. Config Unit Tests** (`test_a2a_config.py`, `test_msagent_config.py`)
- `from_dict()` with minimal input
- `from_dict()` with all fields populated
- Default values
- Env var fallback via `__post_init__` (mock `navconfig.config.get`)
- `to_msagentsdk_config()` conversion (MSAgent only)

**2. Dispatch Tests** (`test_config_dispatch.py`)
- `kind: a2a` produces `A2AAgentConfig`
- `kind: msagent` produces `MSAgentIntegrationConfig`
- Existing kinds still work
- Unknown kind is skipped/ignored
- Missing optional package (ImportError) handled gracefully

**3. Startup Integration Tests** (`test_a2a_startup.py`, `test_msagent_startup.py`)
- Mock `_get_agent()` to return a fake agent
- Mock `A2AServer` / `MSAgentSDKWrapper` to verify constructor args
- Verify discovery registry is populated
- Verify security middleware is wired when credentials set
- Verify graceful handling of `ImportError`

**4. Discovery Tests** (`test_a2a_discovery.py`)
- Registry initialized on first A2A bot
- Multiple agents registered
- `/a2a/directory` returns JSON array of cards
- Empty registry returns empty array

### Key Patterns
```python
@pytest.mark.asyncio
class TestA2AAgentConfig:
    def test_from_dict_minimal(self):
        data = {"chatbot_id": "test_agent", "kind": "a2a"}
        cfg = A2AAgentConfig.from_dict("TestAgent", data)
        assert cfg.name == "TestAgent"
        assert cfg.kind == "a2a"

    @patch("parrot.integrations.a2a.models.config")
    def test_env_var_fallback(self, mock_config):
        mock_config.get.return_value = "env-secret"
        cfg = A2AAgentConfig(name="Test", chatbot_id="test")
        assert cfg.jwt_secret == "env-secret"
```

### Key Constraints
- Use `pytest` + `pytest-asyncio` for async tests.
- Mock external dependencies (`A2AServer`, `MSAgentSDKWrapper`, `CredentialBroker`) — do not require live instances.
- Use `aiohttp.web.Application()` as fixture for app-level tests.
- Patch `navconfig.config.get` for env var fallback tests.
- Each test file should be independently runnable.

---

## Acceptance Criteria

- [ ] All config `from_dict()` test cases pass
- [ ] Dispatch tests verify all 7 kinds (telegram, msteams, whatsapp, slack, msagentsdk, a2a, msagent)
- [ ] A2A startup test verifies `A2AServer` constructor called with correct args
- [ ] MSAgent startup test verifies `MSAgentSDKWrapper` constructor called with correct args
- [ ] Discovery registry tests pass
- [ ] Env var fallback tests pass with mocked `navconfig.config`
- [ ] `to_msagentsdk_config()` conversion test passes
- [ ] All tests pass: `pytest tests/integrations/ -v`
- [ ] No linting errors: `ruff check tests/integrations/`

---

## Test Specification

This task IS the test specification — the test files themselves are the deliverable.
See Implementation Notes above for the test structure and patterns.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — ALL prior tasks (1706-1710) must be completed
3. **Read the implemented code** for each module to understand exact signatures
4. **Create test directory** if `tests/integrations/` doesn't exist
5. **Write tests** following the structure in Implementation Notes
6. **Run tests**: `pytest tests/integrations/ -v`
7. **Fix any failures** — tests must all pass
8. **Move this file** to `sdd/tasks/completed/TASK-1711-integration-tests.md`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
