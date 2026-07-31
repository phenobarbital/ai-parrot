---
type: Wiki Overview
title: 'TASK-1137: Integration Tests'
id: doc:sdd-tasks-completed-task-1137-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.cli.agent_repl import cli # NEW (TASK-1136)'
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.cli.agent_repl
  rel: mentions
- concept: mod:parrot.cli.commands
  rel: mentions
- concept: mod:parrot.cli.loaders
  rel: mentions
- concept: mod:parrot.cli.renderer
  rel: mentions
- concept: mod:parrot.cli.repl
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
---

# TASK-1137: Integration Tests

**Feature**: FEAT-168 — Console CLI Agents
**Spec**: `sdd/specs/console-cli-agents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1131, TASK-1132, TASK-1133, TASK-1134, TASK-1135, TASK-1136
**Assigned-to**: unassigned

---

## Context

> Final task for FEAT-168: comprehensive integration tests that validate the
> full pipeline from Click command through agent loading, REPL interaction,
> slash commands, and response rendering.  Also consolidates unit test fixtures
> into a shared `conftest.py`.

---

## Scope

- Create `packages/ai-parrot/tests/cli/__init__.py`
- Create `packages/ai-parrot/tests/cli/conftest.py` with shared fixtures
- Create or consolidate integration tests:
  - `test_standalone_agent_roundtrip` — load agent → configure → ask → AIMessage
  - `test_repl_slash_tools` — REPL with mocked input → `/tools` → output
  - `test_click_command_list` — `parrot agent --list` end-to-end
  - `test_click_command_agent` — `parrot agent test_bot` with mocked REPL input
  - `test_export_roundtrip` — send queries → `/export` → verify JSON
  - `test_clear_resets_session` — `/clear` → verify new session_id
  - `test_stream_toggle` — `/stream` → verify config change
- Ensure all unit tests from prior tasks pass together
- Verify `pytest packages/ai-parrot/tests/cli/ -v` runs cleanly

**NOT in scope**: new features, refactoring of implementation modules

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/cli/__init__.py` | CREATE | Test package init |
| `packages/ai-parrot/tests/cli/conftest.py` | CREATE | Shared fixtures |
| `packages/ai-parrot/tests/cli/test_integration.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.cli.agent_repl import cli              # NEW (TASK-1136)
from parrot.cli.loaders import StandaloneAgentLoader, AgentLoadError  # NEW (TASK-1133)
from parrot.cli.repl import AgentREPL, REPLConfig  # NEW (TASK-1135)
from parrot.cli.renderer import ResponseRenderer   # NEW (TASK-1132)
from parrot.cli.commands import SlashCommandDispatcher  # NEW (TASK-1134)
from parrot.bots.abstract import AbstractBot       # bots/abstract.py:146
from parrot.models.outputs import OutputMode       # outputs.py:39
from parrot.models.responses import AIMessage      # responses.py:72
```

### Does NOT Exist
- ~~`AbstractBot.history`~~ — use `repl.history` (list of `ConversationTurn`)
- ~~`OutputMode.CONSOLE`~~ — use `TERMINAL`
- ~~`AgentRegistry.list_agents()`~~ — iterate `_registered_agents`

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot/tests/cli/conftest.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.bots.abstract import AbstractBot
from parrot.models.responses import AIMessage
from parrot.models.outputs import OutputMode

@pytest.fixture
def mock_agent():
    agent = AsyncMock(spec=AbstractBot)
    agent.name = "test_agent"
    agent.get_available_tools.return_value = ["MathTool", "WebSearch"]
    agent.get_tools_count.return_value = 2
    agent.has_tools.return_value = True
    agent.ask.return_value = MagicMock(spec=AIMessage)
    agent.ask.return_value.output = "Test response"
    agent.ask.return_value.tool_calls = []
    agent.ask.return_value.output_mode = OutputMode.TERMINAL
    return agent

@pytest.fixture
def repl_config():
    from parrot.cli.repl import REPLConfig
    return REPLConfig(agent_name="test_agent", streaming=False)
```

### Key Constraints
- Use `click.testing.CliRunner` for command-level tests
- Use `pytest-asyncio` for async test methods
- Mock `agent_registry` and `prompt_toolkit.PromptSession` for isolation
- Integration tests should NOT require a running server or real LLM

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/tests/cli/conftest.py` provides shared fixtures
- [ ] All integration tests pass: `pytest packages/ai-parrot/tests/cli/ -v`
- [ ] Click command tests cover `--list`, agent loading, and error cases
- [ ] REPL interaction tests cover slash commands and query dispatch
- [ ] Export test verifies JSON output
- [ ] No test depends on a running server or real LLM API key
- [ ] No linting errors: `ruff check packages/ai-parrot/tests/cli/`

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/test_integration.py
import pytest
from click.testing import CliRunner
from unittest.mock import AsyncMock, patch, MagicMock


class TestCLIIntegration:
    def test_list_shows_agents(self):
        runner = CliRunner()
        # Mock registry with 2 agents
        ...

    async def test_full_roundtrip(self, mock_agent, repl_config):
        # Load agent → create REPL → send query → check response
        ...

    async def test_export_creates_file(self, mock_agent, repl_config, tmp_path):
        # Run conversation → /export → verify file content
        ...

    async def test_clear_new_session(self, mock_agent, repl_config):
        # Track session_id → /clear → verify changed
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Verify all prior tasks (TASK-1131 through TASK-1136) are completed**
2. **Read all implementation files** in `packages/ai-parrot/src/parrot/cli/`
3. **Collect and consolidate** any unit tests from prior tasks into the test package
4. **Write integration tests** covering the full pipeline
5. **Run** `pytest packages/ai-parrot/tests/cli/ -v` and ensure all pass

---

## Completion Note

Completed 2026-05-13. Created `tests/cli/__init__.py`, `tests/cli/conftest.py`
with shared fixtures (mock_agent, repl_config, renderer, mock_agent_response,
response_with_tools), and `tests/cli/test_integration.py` with 28 tests covering:
ResponseRenderer (5 tests), SlashCommandDispatcher (4 tests), REPLConfig (2 tests),
StandaloneAgentLoader (4 tests), AgentREPL.send() (3 tests), slash commands async
(5 tests including /clear, /tools, /stream, /quit, /exit), /export roundtrip (2 tests),
and Click CLI command (3 tests). All 28 tests pass. 1 non-blocking warning about
AsyncMock coroutine in tools test (does not affect test results).
