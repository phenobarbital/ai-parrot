# TASK-025: Integration Tests

**Feature**: FEAT-010 — TelegramCrewTransport
**Spec**: `sdd/specs/telegram-crew-transport.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-016, TASK-017, TASK-018, TASK-019, TASK-020, TASK-021, TASK-022, TASK-023, TASK-024
**Assigned-to**: claude-session

---

## Context

This task implements the integration test suite from spec Section 4. These tests verify end-to-end flows with all components wired together, using mocked Telegram API calls. They ensure the crew transport works as a cohesive system.

Implements spec Section 4, Integration Tests table.

---

## Scope

- Implement `test_crew_startup_flow` — full startup: coordinator sends pinned, agents register, pinned updated
- Implement `test_mention_to_agent_response` — simulate @mention message, verify agent.ask() called and response sent with @mention
- Implement `test_agent_to_agent_delegation` — Agent A sends @mention to Agent B, B processes and replies to A
- Implement `test_document_exchange` — Agent sends CSV document, recipient downloads and processes
- Implement `test_status_lifecycle` — Agent goes ready→busy→ready, pinned message reflects each state
- Implement `test_graceful_shutdown` — All agents unregistered, pinned updated, bot sessions closed
- Create shared test fixtures (crew_config, sample_agent_card, mock_bot, mock_agent)

**NOT in scope**: Tests against real Telegram API (those would be manual/E2E tests).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_telegram_crew/conftest.py` | CREATE | Shared fixtures for all crew tests |
| `tests/test_telegram_crew/test_integration.py` | CREATE | Integration tests |
| `tests/test_telegram_crew/__init__.py` | CREATE | Test package init |

---

## Implementation Notes

### Key Constraints
- All Telegram API calls must be mocked (no real API calls)
- Use `pytest-asyncio` for async tests
- Mark integration tests with `@pytest.mark.integration`
- Tests should verify the interaction between components, not individual component behavior
- Use the shared fixtures from spec Section 4 (Test Data / Fixtures)

### References in Codebase
- Spec Section 4 — full test specification with fixtures
- `tests/` — existing test patterns in the project

---

## Acceptance Criteria

- [ ] All 6 integration tests implemented and passing
- [ ] Shared fixtures in `conftest.py` match spec
- [ ] Tests marked with `@pytest.mark.integration`
- [ ] All tests pass: `pytest tests/test_telegram_crew/ -v -m integration`
- [ ] All unit tests still pass: `pytest tests/test_telegram_crew/ -v`

---

## Test Specification

```python
# tests/test_telegram_crew/test_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.integration
class TestCrewStartupFlow:
    @pytest.mark.asyncio
    async def test_coordinator_sends_pinned_on_start(self, crew_config):
        """Full startup: coordinator sends pinned, agents register."""
        ...

    @pytest.mark.asyncio
    async def test_agents_register_on_start(self, crew_config):
        """All configured agents appear in registry after start."""
        ...


@pytest.mark.integration
class TestMentionRouting:
    @pytest.mark.asyncio
    async def test_mention_to_agent_triggers_ask(self, crew_config, mock_agent):
        """@mention routes to correct agent.ask() call."""
        ...

    @pytest.mark.asyncio
    async def test_response_includes_sender_mention(self, crew_config, mock_agent):
        """Agent response includes @mention of the original sender."""
        ...


@pytest.mark.integration
class TestAgentDelegation:
    @pytest.mark.asyncio
    async def test_agent_to_agent(self, crew_config):
        """Agent A @mentions Agent B, B processes and replies."""
        ...


@pytest.mark.integration
class TestDocumentExchange:
    @pytest.mark.asyncio
    async def test_csv_exchange(self, crew_config):
        """Agent sends CSV, recipient downloads and processes."""
        ...


@pytest.mark.integration
class TestStatusLifecycle:
    @pytest.mark.asyncio
    async def test_ready_busy_ready(self, crew_config):
        """Agent transitions ready→busy→ready, pinned reflects changes."""
        ...


@pytest.mark.integration
class TestGracefulShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_unregisters_all(self, crew_config):
        """All agents unregistered, pinned updated, sessions closed."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/telegram-crew-transport.spec.md` for full context
2. **Check dependencies** — verify ALL tasks TASK-016 through TASK-024 are in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-025-integration-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented 9 integration tests across 6 test classes in `test_integration.py`: TestCrewStartupFlow (3 tests), TestMentionRouting (2 tests), TestAgentDelegation (1 test), TestDocumentExchange (1 test), TestStatusLifecycle (1 test), TestGracefulShutdown (1 test). All marked with `@pytest.mark.integration`. Added `integration` marker to `pytest.ini`. Created shared fixtures in `conftest.py` (8 fixtures). Full crew test suite: 155 tests pass.

**Deviations from spec**: Added 3 extra tests beyond the spec's 6 minimum (startup flow has 3 sub-tests, mention routing has 2 sub-tests) for more thorough coverage. The spec called for 6 test methods but we implemented 9 across the 6 required classes.
