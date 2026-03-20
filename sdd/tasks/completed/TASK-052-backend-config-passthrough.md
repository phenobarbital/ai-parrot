# TASK-052: Backend WebSearchAgent Config Passthrough Verification

**Feature**: WebSearchAgent Support in CrewBuilder
**Spec**: `sdd/specs/crew-websearchagent-support.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> This task implements Module 4 from the spec: verifying that the backend correctly passes WebSearchAgent-specific parameters through the agent creation pipeline.

The `CrewHandler._create_crew_from_definition` method already passes `**agent_def.config` to agent constructors. This task verifies the flow works correctly for WebSearchAgent and adds optional logging for debugging.

**Repository**: `ai-parrot`

---

## Scope

- Verify `WebSearchAgent` is registered in `BotManager` and can be retrieved via `get_bot_class("WebSearchAgent")`
- Add debug logging in `_create_crew_from_definition` when creating WebSearchAgent
- Write unit test proving config parameters pass through correctly
- Document the parameter flow in code comments

**NOT in scope**:
- Server-side prompt validation (per spec decision: done in frontend)
- Modifying WebSearchAgent itself
- Changing AgentDefinition schema

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/crew/handler.py` | MODIFY | Add debug logging for WebSearchAgent creation |
| `parrot/bots/__init__.py` | VERIFY | Ensure WebSearchAgent is exported |
| `tests/test_crew_websearchagent.py` | CREATE | Unit tests for config passthrough |

---

## Implementation Notes

### Verify Registration

Check that `WebSearchAgent` is accessible via `BotManager`:

```python
# In parrot/bots/__init__.py or similar
from parrot.bots.search import WebSearchAgent

# BotManager should be able to resolve "WebSearchAgent" → WebSearchAgent class
```

### Add Debug Logging

In `_create_crew_from_definition`:

```python
async def _create_crew_from_definition(self, crew_def: CrewDefinition) -> AgentCrew:
    agents = []
    for agent_def in crew_def.agents:
        agent_class = self.bot_manager.get_bot_class(agent_def.agent_class)

        # Debug logging for WebSearchAgent
        if agent_def.agent_class == "WebSearchAgent":
            self.logger.debug(
                f"Creating WebSearchAgent '{agent_def.name}' with config: "
                f"contrastive_search={agent_def.config.get('contrastive_search', False)}, "
                f"synthesize={agent_def.config.get('synthesize', False)}"
            )

        # ... existing creation logic
```

### Key Constraints

- Do NOT change the existing creation flow — just add logging
- The existing `**agent_def.config` unpacking should work as-is
- Tests must use mocking to avoid actual LLM calls

---

## Acceptance Criteria

- [x] `WebSearchAgent` is retrievable via `bot_manager.get_bot_class("WebSearchAgent")`
- [x] Debug logging added for WebSearchAgent creation
- [x] Unit test passes: config parameters flow to WebSearchAgent instance
- [x] No breaking changes to existing crew creation

---

## Test Specification

```python
# tests/test_crew_websearchagent.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition
from parrot.handlers.crew.handler import CrewHandler
from parrot.bots.search import WebSearchAgent


class TestWebSearchAgentCrewCreation:
    """Tests for WebSearchAgent config passthrough in CrewHandler."""

    @pytest.fixture
    def websearchagent_definition(self):
        """Fixture for WebSearchAgent crew definition."""
        return CrewDefinition(
            name="research_crew",
            execution_mode="sequential",
            agents=[
                AgentDefinition(
                    agent_id="web_search_1",
                    agent_class="WebSearchAgent",
                    name="Research Agent",
                    config={
                        "temperature": 0.0,
                        "contrastive_search": True,
                        "contrastive_prompt": "Compare $query vs: $search_results",
                        "synthesize": True,
                        "synthesize_prompt": "Summarize: $search_results"
                    },
                    tools=[],
                    system_prompt="Research assistant"
                )
            ],
            flow_relations=[],
            shared_tools=[]
        )

    @pytest.fixture
    def mock_bot_manager(self):
        """Mock BotManager that returns WebSearchAgent class."""
        manager = MagicMock()
        manager.get_bot_class.return_value = WebSearchAgent
        manager.get_tool.return_value = None
        return manager

    async def test_websearchagent_config_passthrough(
        self,
        websearchagent_definition,
        mock_bot_manager
    ):
        """Verify config parameters pass to WebSearchAgent instance."""
        handler = CrewHandler()
        handler._bot_manager = mock_bot_manager

        with patch.object(WebSearchAgent, '__init__', return_value=None) as mock_init:
            # Mock __init__ to capture arguments
            mock_init.return_value = None

            crew = await handler._create_crew_from_definition(websearchagent_definition)

            # Verify WebSearchAgent was instantiated with correct config
            mock_init.assert_called_once()
            call_kwargs = mock_init.call_args.kwargs

            assert call_kwargs.get('contrastive_search') is True
            assert call_kwargs.get('synthesize') is True
            assert '$query' in call_kwargs.get('contrastive_prompt', '')

    async def test_websearchagent_defaults(self, mock_bot_manager):
        """Verify WebSearchAgent works with minimal config."""
        minimal_def = CrewDefinition(
            name="minimal_crew",
            agents=[
                AgentDefinition(
                    agent_id="search_1",
                    agent_class="WebSearchAgent",
                    config={}  # Empty config — should use defaults
                )
            ]
        )

        handler = CrewHandler()
        handler._bot_manager = mock_bot_manager

        # Should not raise
        crew = await handler._create_crew_from_definition(minimal_def)
        assert crew is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-052-backend-config-passthrough.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-27
**Notes**:

1. **Verified WebSearchAgent export**: Already exported in `parrot/bots/__init__.py` (line 8, 17)
2. **Added debug logging**: Enhanced `_create_crew_from_definition` in `handler.py` with:
   - Debug log when creating WebSearchAgent showing contrastive_search, synthesize, and temperature
   - Updated docstring documenting the config parameters for WebSearchAgent
3. **Created comprehensive test suite**: `tests/test_crew_websearchagent.py` with 15 tests covering:
   - WebSearchAgent export verification
   - Parameter signature validation (contrastive_search, synthesize, prompts)
   - CrewDefinition model acceptance of WebSearchAgent config
   - Config dict unpacking passthrough verification
   - Default prompt existence checks

All 15 tests pass, linting clean with ruff.

**Deviations from spec**:
- Tests use dynamic module import to avoid `navigator` dependency issues in test environment
- Used `_agent` prefix for unused variables to satisfy linter
