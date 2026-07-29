---
type: Wiki Overview
title: 'TASK-1641: Integration Tests'
id: doc:sdd-tasks-completed-task-1641-msagentsdk-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task creates the comprehensive test suite for the MS Agent SDK integration.
relates_to:
- concept: mod:parrot.integrations.models
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.agent
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.models
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.wrapper
  rel: mentions
---

# TASK-1641: Integration Tests

**Feature**: FEAT-259 — Microsoft Copilot Agent SDK Integration
**Spec**: `sdd/specs/microsoft-copilot-agent-sdk.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1637, TASK-1638, TASK-1639, TASK-1640
**Assigned-to**: unassigned

---

## Context

This task creates the comprehensive test suite for the MS Agent SDK integration.
It covers unit tests for all components (config, bridge, wrapper, manager
dispatch) and an integration test for the end-to-end message flow.

Implements: Spec §3 Module 6 (Tests) + §4 (Test Specification).

---

## Scope

- Create test directory `tests/integrations/test_msagentsdk/`.
- Create `conftest.py` with shared fixtures.
- Create `test_models.py` — config model unit tests.
- Create `test_agent.py` — bridge agent unit tests.
- Create `test_wrapper.py` — wrapper unit tests.
- Create `test_manager_registration.py` — config dispatch + manager tests.
- Create `test_integration.py` — end-to-end message flow test with mocked SDK.
- Ensure all tests pass: `pytest tests/integrations/test_msagentsdk/ -v`.

**NOT in scope**: Implementation code changes (all done in prior tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integrations/test_msagentsdk/__init__.py` | CREATE | Test package init |
| `tests/integrations/test_msagentsdk/conftest.py` | CREATE | Shared fixtures |
| `tests/integrations/test_msagentsdk/test_models.py` | CREATE | Config model tests |
| `tests/integrations/test_msagentsdk/test_agent.py` | CREATE | Bridge agent tests |
| `tests/integrations/test_msagentsdk/test_wrapper.py` | CREATE | Wrapper tests |
| `tests/integrations/test_msagentsdk/test_manager_registration.py` | CREATE | Manager dispatch tests |
| `tests/integrations/test_msagentsdk/test_integration.py` | CREATE | End-to-end flow test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Components under test (all created in prior tasks)
from parrot.integrations.msagentsdk.models import MSAgentSDKConfig
from parrot.integrations.msagentsdk.agent import ParrotM365Agent
from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper
from parrot.integrations.models import IntegrationBotConfig

# Test framework
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop  # if needed
```

### Does NOT Exist

- ~~`parrot.integrations.msagentsdk.testing`~~ — no test utilities module; use standard mocking
- ~~`microsoft_agents.testing`~~ — no official test utilities; mock TurnContext/Activity directly

---

## Implementation Notes

### Fixtures Strategy

Use `conftest.py` for shared fixtures:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def msagentsdk_config():
    from parrot.integrations.msagentsdk.models import MSAgentSDKConfig
    return MSAgentSDKConfig(
        name="TestCopilotBot",
        chatbot_id="test_agent",
        anonymous_auth=True,
    )


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.ask = AsyncMock(return_value=MagicMock(content="Test response"))
    return bot


@pytest.fixture
def mock_activity_message():
    return {
        "type": "message",
        "text": "Hello, agent!",
        "from": {"id": "user-123", "name": "Test User"},
        "conversation": {"id": "conv-456"},
        "channelId": "webchat",
        "serviceUrl": "https://test.botframework.com/",
        "id": "activity-789",
    }


@pytest.fixture
def mock_turn_context():
    ctx = AsyncMock()
    ctx.activity = MagicMock()
    ctx.activity.type = "message"
    ctx.activity.text = "Hello, agent!"
    ctx.activity.from_property = MagicMock(id="user-123", name="Test User")
    ctx.activity.conversation = MagicMock(id="conv-456")
    ctx.activity.recipient = MagicMock(id="bot-789")
    ctx.activity.members_added = None
    ctx.send_activity = AsyncMock()
    return ctx
```

### Key Constraints

- All tests must work WITHOUT the `microsoft-agents-*` packages installed
  (mock all SDK types). This ensures CI doesn't need Azure SDK deps.
- Use `@pytest.mark.asyncio` for all async test methods.
- Use `patch` to mock lazy imports inside the wrapper/bridge.
- Test the config dispatch in `IntegrationBotConfig.from_dict()` to ensure
  `kind: msagentsdk` produces the correct config type.

### Test Coverage Matrix

| Component | Happy path | Edge cases | Error handling |
|---|---|---|---|
| Config model | from_dict, env fallback | missing fields, anonymous | invalid chatbot_id |
| Bridge agent | message → ask → response | empty text, None text, no from_property | ask() raises exception |
| Wrapper | route registration | safe_id with spaces | adapter.process() fails |
| Manager dispatch | kind == msagentsdk | unknown kind ignored | missing required fields |
| Integration | POST → response | malformed JSON | timeout |

---

## Acceptance Criteria

- [ ] All unit tests pass: `pytest tests/integrations/test_msagentsdk/ -v`
- [ ] Config model tests cover `from_dict`, env var fallback, defaults
- [ ] Bridge agent tests cover message, conversationUpdate, empty text, unknown type
- [ ] Wrapper tests cover route registration
- [ ] Manager dispatch tests cover config parsing and validation
- [ ] Tests run without `microsoft-agents-*` installed (all SDK types mocked)
- [ ] No linting errors: `ruff check tests/integrations/test_msagentsdk/`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/microsoft-copilot-agent-sdk.spec.md` for full context
2. **Check dependencies** — verify TASK-1637 through TASK-1640 are all completed
3. **Read the implementation** — review the actual code created in prior tasks
4. **Write tests** that match the actual implementation (not just the spec scaffolds)
5. **Run tests**: `pytest tests/integrations/test_msagentsdk/ -v`
6. **Move this file** to `sdd/tasks/completed/TASK-1641-msagentsdk-tests.md`
7. **Update index** → `"done"`

---

## Completion Note

Implemented by sdd-worker on 2026-06-25.

Created:
- `tests/integrations/__init__.py` — package init
- `tests/integrations/test_msagentsdk/__init__.py` — test package init
- `tests/integrations/test_msagentsdk/conftest.py` — shared fixtures
- `tests/integrations/test_msagentsdk/test_models.py` — 9 tests for `MSAgentSDKConfig`
- `tests/integrations/test_msagentsdk/test_agent.py` — 13 tests for `ParrotM365Agent`
- `tests/integrations/test_msagentsdk/test_wrapper.py` — 7 tests for `MSAgentSDKWrapper`
- `tests/integrations/test_msagentsdk/test_manager_registration.py` — 9 tests for manager dispatch
- `tests/integrations/test_msagentsdk/test_integration.py` — 4 end-to-end tests

Result: 42/42 tests pass.

All tests use mocked `microsoft_agents.*` SDK so they run without the optional dependency installed.
Test command: `PYTHONPATH=".claude/worktrees/feat-259-microsoft-copilot-agent-sdk/packages/ai-parrot-integrations/src:$PYTHONPATH" pytest tests/integrations/test_msagentsdk/ -v`
