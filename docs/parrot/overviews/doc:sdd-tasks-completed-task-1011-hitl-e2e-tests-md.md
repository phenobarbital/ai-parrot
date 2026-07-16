---
type: Wiki Overview
title: 'TASK-1011: End-to-end integration tests for web HITL flow'
id: doc:sdd-tasks-completed-task-1011-hitl-e2e-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements the three end-to-end integration tests that exercise
  the full web HITL flow from agent invocation through user response (§4 Integration
  Tests in the spec). These tests use a real `HumanInteractionManager` wired to Redis
  and a fake `UserSocketManager` to verif
relates_to:
- concept: mod:parrot.agents.demo
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.clients.google
  rel: mentions
- concept: mod:parrot.core.exceptions
  rel: mentions
- concept: mod:parrot.handlers.user
  rel: mentions
- concept: mod:parrot.handlers.web_hitl
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
- concept: mod:parrot.utils
  rel: mentions
---

# TASK-1011: End-to-end integration tests for web HITL flow

**Feature**: FEAT-146 — web-hitl-and-demo-agent
**Spec**: `sdd/specs/web-hitl-and-demo-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-1005, TASK-1006, TASK-1007, TASK-1010
**Assigned-to**: unassigned

---

## Context

This task implements the three end-to-end integration tests that exercise the full web HITL flow from agent invocation through user response (§4 Integration Tests in the spec). These tests use a real `HumanInteractionManager` wired to Redis and a fake `UserSocketManager` to verify that agents, tools, the channel, and the HTTP endpoint all work together.

These tests provide confidence that the entire feature is working as designed.

---

## Scope

- Create `packages/ai-parrot/tests/handlers/test_web_hitl_integration.py` (or add to existing `test_web_hitl.py`).
- Implement three integration tests:
  1. `test_e2e_human_tool_over_web` — agent calls WebHumanTool, channel emits payload, HTTP POST resolves, agent returns value.
  2. `test_e2e_handoff_tool_over_web` — agent calls BookFlightTool with bad date, raises `HumanInteractionInterrupt`, shows interrupt propagates correctly.
  3. `test_e2e_demo_agent_full_flight` — run the registered `hitl_demo` agent end-to-end against a mocked Google client, including one HumanTool round-trip.
- Test fixtures:
  - `fake_user_socket_manager` — records all `notify_channel` calls.
  - `in_memory_manager` — HumanInteractionManager using fakeredis.
  - `web_hitl_app` — aiohttp app with WebHumanChannel + HITLResponseHandler mounted, authenticated user pre-installed.
- Add Google-style docstrings and clear assertions.

**NOT in scope**:
- Unit tests for individual components (covered by per-task tests in TASK-1003–1010).
- Frontend testing (out of scope per spec §1 Non-Goals).
- Suspend/resume mode (`request_human_input_async`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/handlers/test_web_hitl_integration.py` | CREATE | Three end-to-end integration tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
import fakeredis.aioredis
from parrot.handlers.web_hitl import (                                          # (from previous tasks)
    WebHumanChannel,
    WebHumanTool,
    HITLResponseHandler,
    setup_web_hitl,
)
from parrot.human import (                                                      # parrot/human/__init__.py
    HumanInteractionManager,
    HumanTool,
    set_default_human_manager,
    get_default_human_manager,
)
from parrot.human.models import (                                               # parrot/human/models.py
    HumanInteraction,
    HumanResponse,
    InteractionType,
)
from parrot.handlers.user import UserSocketManager                              # parrot/handlers/user.py
from parrot.bots import Agent
from parrot.agents.demo import HITLDemoAgent                                    # (created in TASK-1010)
from parrot.core.exceptions import HumanInteractionInterrupt                    # parrot/core/exceptions.py
from parrot.clients.google import GoogleClient                                  # (for mocking)
```

### Existing Signatures to Use

```python
# parrot/human/manager.py
class HumanInteractionManager:
    async def request_human_input(
        self, interaction: HumanInteraction, channel: str = "telegram",
    ) -> InteractionResult: ...
    async def receive_response(self, response: HumanResponse) -> None: ...

# parrot/handlers/user.py
class UserSocketManager:
    async def notify_channel(
        self, channel_name: str, message: Dict[str, Any],
    ) -> bool: ...

# aiohttp test fixtures
def aiohttp_client(loop): ...  # pytest-aiohttp fixture
def aiohttp_server(loop): ...  # pytest-aiohttp fixture
```

### Does NOT Exist

- No new signatures; tests use existing components.

---

## Implementation Notes

### Pattern to Follow

Use pytest-aiohttp fixtures (`aiohttp_client`) for spinning up a test application with the HITL stack mounted. Follow patterns from `parrot/tests/handlers/test_agent.py` if it exists.

Key test flow:
1. Set up a fake `UserSocketManager` that records `notify_channel` calls.
2. Create a `HumanInteractionManager` with fakeredis backend.
3. Mount `WebHumanChannel` and `HITLResponseHandler` on the app.
4. Create an agent with `WebHumanTool`.
5. Invoke the agent's `ask(...)` method.
6. Assert that the channel recorded the question.
7. Simulate the user's HTTP POST to `/agents/hitl/respond` with the answer.
8. Assert that the agent resumed and returned the answer.

### Key Constraints

- Integration tests should use a real `HumanInteractionManager` (not mocked) to exercise the full flow.
- Use `fakeredis.aioredis` for Redis backend to avoid dependency on a running Redis server.
- Assertions should verify not just success, but the exact messages passed between components.
- All tests are `async`.

---

## Acceptance Criteria

- [ ] `test_e2e_human_tool_over_web` exists and passes.
- [ ] `test_e2e_handoff_tool_over_web` exists and passes.
- [ ] `test_e2e_demo_agent_full_flight` exists and passes.
- [ ] All three tests are marked as async/integration.
- [ ] Test fixtures `fake_user_socket_manager`, `in_memory_manager`, `web_hitl_app` are defined.
- [ ] All tests verify the exact payload shapes per spec §2 Data Models.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/handlers/test_web_hitl_integration.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/tests/handlers/test_web_hitl_integration.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/handlers/test_web_hitl_integration.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web
import fakeredis.aioredis
from parrot.handlers.web_hitl import (
    WebHumanChannel,
    WebHumanTool,
    HITLResponseHandler,
    setup_web_hitl,
)
from parrot.human import HumanInteractionManager, set_default_human_manager
from parrot.human.models import InteractionType, ChoiceOption, HumanResponse
from parrot.handlers.user import UserSocketManager
from parrot.agents.demo import HITLDemoAgent
from parrot.core.exceptions import HumanInteractionInterrupt


@pytest.fixture
def fake_user_socket_manager():
    """Records every notify_channel call and exposes them for assertions."""
    manager = MagicMock(spec=UserSocketManager)
    manager.notify_channel = AsyncMock(return_value=True)
    manager.channel_subscriptions = {}
    return manager


@pytest.fixture
async def in_memory_manager(fake_user_socket_manager):
    """HumanInteractionManager wired to a fakeredis instance."""
    redis = await fakeredis.aioredis.create_redis_pool()
    channel = WebHumanChannel(socket_manager=fake_user_socket_manager)
    manager = HumanInteractionManager(
        channels={"web": channel},
        redis_url="redis://localhost",  # fakeredis
    )
    # Monkeypatch the redis pool for testing
    manager.redis = redis
    await manager.startup()
    set_default_human_manager(manager)
    yield manager
    redis.close()
    await redis.wait_closed()


@pytest.fixture
async def web_hitl_app(aiohttp_client, fake_user_socket_manager, in_memory_manager):
    """aiohttp app with WebHumanChannel + HITLResponseHandler mounted."""
    app = web.Application()
    app['user_socket_manager'] = fake_user_socket_manager
    
    # Register the HITL endpoint
    app.router.add_view('/api/v1/agents/hitl/respond', HITLResponseHandler)
    
    # Create a test client with an authenticated session
    client = await aiohttp_client(app)
    client.session = {"user_id": "test_user"}
    return client


class TestWebHITLIntegration:
    @pytest.mark.asyncio
    async def test_e2e_human_tool_over_web(self, web_hitl_app, in_memory_manager, fake_user_socket_manager):
        """E2E: agent calls WebHumanTool, channel emits, POST responds, agent resumes."""
        # 1. Create a stub agent with WebHumanTool
        # 2. Invoke the agent
        # 3. Assert the channel recorded the question
        # 4. POST the response to /agents/hitl/respond
        # 5. Assert the agent resumed with the answer
        pass

    @pytest.mark.asyncio
    async def test_e2e_handoff_tool_over_web(self, web_hitl_app, in_memory_manager):
        """E2E: BookFlightTool raises HumanInteractionInterrupt on bad date."""
        # 1. Agent calls BookFlightTool with a malformed date
        # 2. Assert HumanInteractionInterrupt propagates out
        # 3. Verify the agent's resume hook can re-enter
        pass

    @pytest.mark.asyncio
    async def test_e2e_demo_agent_full_flight(self, web_hitl_app, in_memory_manager, fake_user_socket_manager):
        """E2E: run hitl_demo agent end-to-end with mocked Google client."""
        # 1. Instantiate HITLDemoAgent
        # 2. Mock the Google LLM client with canned tool calls
        # 3. Run agent.ask(...) and verify it completes
        # 4. Assert the channel recorded interactions for destination and date
        # 5. Verify the channel recorded the BookFlightTool call
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-hitl-and-demo-agent.spec.md` for full context
2. **Check dependencies** — verify TASK-1005, TASK-1006, TASK-1007, TASK-1010 are in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm imports and existing test patterns in `parrot/tests/handlers/`
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — write the three integration tests with real managers and full agent invocation
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1011-hitl-e2e-tests.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-05
**Notes**: Created 9 integration tests in `packages/ai-parrot/tests/human/test_web_hitl_integration.py`
covering the three required E2E scenarios. Used a `_FakeRedis` dict-backed store instead of
fakeredis (not installed in venv) to avoid external dependencies. All 9 tests pass.

**Deviations from spec**: File placed in `tests/human/` instead of `tests/handlers/` because
the handlers conftest has a pre-existing import failure (`parrot.utils.types` Cython module missing
in the worktree's Python path). The tests cover all three required scenarios plus additional
sub-tests for completeness. The three required test method names
(`test_e2e_human_tool_over_web`, `test_e2e_handoff_tool_*`, `test_e2e_demo_agent_*`)
are all present as specified.
