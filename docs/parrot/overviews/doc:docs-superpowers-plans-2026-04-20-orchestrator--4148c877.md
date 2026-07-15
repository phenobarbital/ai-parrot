---
type: Wiki Overview
title: OrchestratorAgent AIMessage Preservation — Implementation Plan
id: doc:docs-superpowers-plans-2026-04-20-orchestrator-aimessage-preservation-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Create `packages/ai-parrot/tests/test_agent_result_ai_message.py`:'
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage
  rel: mentions
- concept: mod:parrot.models.basic
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
- concept: mod:parrot.tools.agent
  rel: mentions
---

# OrchestratorAgent AIMessage Preservation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve full AIMessage responses from specialist agents through the orchestration layer, enabling pass-through and synthesis modes so the frontend receives rich data (charts, tables, artifacts) without loss.

**Architecture:** `AgentResult` gains an `ai_message` field as a side-channel. `AgentTool._execute()` captures the full AIMessage there while still returning strings to the LLM. `OrchestratorAgent` overrides `ask()` to inspect the side-channel after the tool-calling loop and either passes through the specialist's AIMessage directly (single agent with rich data) or merges data from multiple agents into a `{agent_name: data}` dictionary.

**Tech Stack:** Python 3.11+, Pydantic, dataclasses, pytest, pytest-asyncio, unittest.mock

**Design Spec:** `docs/superpowers/specs/2026-04-20-orchestrator-aimessage-preservation-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/crew.py` | Modify | Add `ai_message` field to `AgentResult` |
| `packages/ai-parrot/src/parrot/tools/agent.py` | Modify | Capture AIMessage in `_execute()`, store in `AgentResult.ai_message` |
| `packages/ai-parrot/src/parrot/bots/orchestration/agent.py` | Modify | Registry integration, custom `ask()`, pass-through/synthesis |
| `packages/ai-parrot/tests/test_agent_result_ai_message.py` | Create | Unit tests for AgentResult.ai_message field |
| `packages/ai-parrot/tests/test_agent_tool_ai_message.py` | Create | Unit tests for AgentTool AIMessage capture |
| `packages/ai-parrot/tests/test_orchestrator_agent.py` | Create | Unit tests for OrchestratorAgent pass-through/synthesis/registry |

---

### Task 1: Add `ai_message` field to AgentResult

**Files:**
- Modify: `packages/ai-parrot/src/parrot/models/crew.py:386-397`
- Test: `packages/ai-parrot/tests/test_agent_result_ai_message.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/ai-parrot/tests/test_agent_result_ai_message.py`:

```python
"""Tests for AgentResult.ai_message field."""
import pytest
from parrot.models.crew import AgentResult
from parrot.models.responses import AIMessage
from parrot.models.basic import CompletionUsage


def _make_ai_message(**overrides) -> AIMessage:
    """Create a minimal AIMessage for testing."""
    defaults = {
        "input": "test question",
        "output": "test answer",
        "model": "test-model",
        "provider": "test",
        "usage": CompletionUsage(),
        "metadata": {},
    }
    defaults.update(overrides)
    return AIMessage(**defaults)


class TestAgentResultAIMessage:
    """Verify ai_message field on AgentResult."""

    def test_ai_message_defaults_to_none(self):
        result = AgentResult(
            agent_id="agent1",
            agent_name="Agent One",
            task="do something",
            result="text output",
            metadata={},
            execution_time=1.0,
        )
        assert result.ai_message is None

    def test_ai_message_stores_full_aimessage(self):
        msg = _make_ai_message(
            data={"revenue": [100, 200, 300]},
            code="df.sum()",
            artifacts=[{"type": "sql", "content": "SELECT *"}],
        )
        result = AgentResult(
            agent_id="agent1",
            agent_name="Agent One",
            task="do something",
            result="text output",
            ai_message=msg,
            metadata={},
            execution_time=1.0,
        )
        assert result.ai_message is msg
        assert result.ai_message.data == {"revenue": [100, 200, 300]}
        assert result.ai_message.code == "df.sum()"
        assert len(result.ai_message.artifacts) == 1

    def test_to_text_still_uses_result_not_ai_message(self):
        msg = _make_ai_message(output="rich output with data")
        result = AgentResult(
            agent_id="agent1",
            agent_name="Agent One",
            task="do something",
            result="simple text",
            ai_message=msg,
            metadata={},
            execution_time=1.0,
        )
        text = result.to_text()
        assert "simple text" in text
        assert "rich output with data" not in text

    def test_backward_compatible_without_ai_message(self):
        result = AgentResult(
            agent_id="agent1",
            agent_name="Agent One",
            task="do something",
            result="text output",
            metadata={"key": "value"},
            execution_time=1.5,
        )
        assert result.result == "text output"
        assert result.ai_message is None
        assert result.metadata == {"key": "value"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_agent_result_ai_message.py -v`

Expected: FAIL — `AgentResult.__init__() got an unexpected keyword argument 'ai_message'`

- [ ] **Step 3: Add ai_message field to AgentResult**

In `packages/ai-parrot/src/parrot/models/crew.py`, modify the `AgentResult` dataclass. Add the `ai_message` field **after** `result` and **before** `metadata` (dataclass field ordering requires defaults after non-defaults):

```python
@dataclass
class AgentResult:
    """Captures a single agent execution with full context"""
    agent_id: str
    agent_name: str
    task: str
    result: Any
    ai_message: Optional['AIMessage'] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    parent_execution_id: Optional[str] = None
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
```

Note: `metadata` and `execution_time` must become keyword-with-default fields because `ai_message` (with a default) now precedes them. This is a dataclass ordering requirement. All existing callers already pass `metadata=` and `execution_time=` as keyword arguments (verified in `AgentTool._execute()` at line 263-275 and in `crew.py`'s `build_agent_metadata`), so this is backward compatible.

Add the `Optional` import if not already present (it is — line 1 of crew.py has it).

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_agent_result_ai_message.py -v`

Expected: 4 tests PASS

- [ ] **Step 5: Run existing tests to verify no regressions**

Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_execution_memory_integration.py -v`

Expected: All existing tests PASS (backward compatible change)

- [ ] **Step 6: Commit**

```bash
git add packages/ai-parrot/src/parrot/models/crew.py packages/ai-parrot/tests/test_agent_result_ai_message.py
git commit -m "feat(models): add ai_message field to AgentResult for AIMessage preservation"
```

---

### Task 2: Capture AIMessage in AgentTool._execute()

**Files:**
- Modify: `packages/ai-parrot/src/parrot/tools/agent.py:248-286`
- Test: `packages/ai-parrot/tests/test_agent_tool_ai_message.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/ai-parrot/tests/test_agent_tool_ai_message.py`:

```python
"""Tests for AgentTool capturing AIMessage in execution_memory."""
import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock
from parrot.tools.agent import AgentTool
from parrot.models.responses import AIMessage, AgentResponse
from parrot.models.basic import CompletionUsage
from parrot.bots.flows.core.storage import ExecutionMemory  # updated: parrot.bots.flow deleted in FEAT-196


def _make_ai_message(**overrides) -> AIMessage:
    defaults = {
        "input": "test question",
        "output": "test answer",
        "model": "test-model",
        "provider": "test",
        "usage": CompletionUsage(),
        "metadata": {},
    }
    defaults.update(overrides)
    return AIMessage(**defaults)


def _make_mock_agent(name: str = "TestAgent", response=None):
    agent = AsyncMock()
    agent.name = name
    agent.role = "test role"
    agent.goal = "test goal"
    agent.capabilities = None
    if response is not None:
        agent.conversation = AsyncMock(return_value=response)
    return agent


class TestAgentToolAIMessageCapture:

    @pytest.mark.asyncio
    async def test_captures_ai_message_from_ask(self):
        msg = _make_ai_message(
            data={"revenue": [100, 200]},
            artifacts=[{"type": "sql", "content": "SELECT *"}],
        )
        agent = _make_mock_agent(response=msg)
        memory = ExecutionMemory(original_query="test")
        tool = AgentTool(agent=agent, execution_memory=memory)

        result = await tool._execute(question="What is revenue?")

        assert isinstance(result, str)
        stored = memory.results.get("TestAgent")
        assert stored is not None
        assert stored.ai_message is msg
        assert stored.ai_message.data == {"revenue": [100, 200]}

    @pytest.mark.asyncio
    async def test_captures_ai_message_from_agent_response(self):
        inner_msg = _make_ai_message(data={"profit": 42})
        agent_response = MagicMock(spec=AgentResponse)
        agent_response.content = "profit is 42"
        agent_response.output = "profit is 42"
        agent_response.response = inner_msg
        agent = _make_mock_agent(response=agent_response)
        memory = ExecutionMemory(original_query="test")
        tool = AgentTool(agent=agent, execution_memory=memory)

        await tool._execute(question="What is profit?")

        stored = memory.results["TestAgent"]
        assert stored.ai_message is inner_msg
        assert stored.ai_message.data == {"profit": 42}

    @pytest.mark.asyncio
    async def test_ai_message_is_none_for_string_response(self):
        agent = _make_mock_agent(response="plain text response")
        memory = ExecutionMemory(original_query="test")
        tool = AgentTool(agent=agent, execution_memory=memory)

        await tool._execute(question="Hello")

        stored = memory.results["TestAgent"]
        assert stored.ai_message is None
        assert stored.result == "plain text response"

    @pytest.mark.asyncio
    async def test_still_returns_string_to_caller(self):
        msg = _make_ai_message(
            output="text for LLM",
            data={"big": "payload"},
        )
        agent = _make_mock_agent(response=msg)
        memory = ExecutionMemory(original_query="test")
        tool = AgentTool(agent=agent, execution_memory=memory)

        result = await tool._execute(question="test")

        assert isinstance(result, str)
        assert "payload" not in result

    @pytest.mark.asyncio
    async def test_no_execution_memory_no_error(self):
        msg = _make_ai_message(data={"x": 1})
        agent = _make_mock_agent(response=msg)
        tool = AgentTool(agent=agent, execution_memory=None)

        result = await tool._execute(question="test")

        assert isinstance(result, str)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_agent_tool_ai_message.py -v`

Expected: `test_captures_ai_message_from_ask` and `test_captures_ai_message_from_agent_response` FAIL because `AgentResult` is constructed without `ai_message`.

- [ ] **Step 3: Modify AgentTool._execute() to capture AIMessage**

In `packages/ai-parrot/src/parrot/tools/agent.py`, make two changes inside `_execute()`:

**3a.** After the agent call (after line 246), before the content extraction block (line 251), add AIMessage capture:

```python
            # Preserve full AIMessage for orchestrator side-channel
            full_ai_message = None
            if isinstance(response, AIMessage):
                full_ai_message = response
            elif isinstance(response, AgentResponse):
                inner = getattr(response, 'response', None)
                if isinstance(inner, AIMessage):
                    full_ai_message = inner
```

**3b.** In the `AgentResult` construction (around line 263), add the `ai_message` kwarg:

```python
                agent_result = AgentResult(
                    agent_id=self.agent.name,
                    agent_name=self.agent.name,
                    task=question,
                    result=result,
                    ai_message=full_ai_message,
                    metadata={
                        "user_id": user_id,
                        "session_id": session_id,
                        "call_count": self.call_count,
                        "result_type": type(result).__name__
                    },
                    execution_time=execution_time
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_agent_tool_ai_message.py -v`

Expected: 5 tests PASS

- [ ] **Step 5: Run existing tests for regressions**

Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_execution_memory_integration.py packages/ai-parrot/tests/test_agent_result_ai_message.py -v`

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add packages/ai-parrot/src/parrot/tools/agent.py packages/ai-parrot/tests/test_agent_tool_ai_message.py
git commit -m "feat(tools): capture full AIMessage in AgentTool execution memory"
```

---

### Task 3: OrchestratorAgent Registry Integration

**Files:**
- Modify: `packages/ai-parrot/src/parrot/bots/orchestration/agent.py:1-29`
- Test: `packages/ai-parrot/tests/test_orchestrator_agent.py` (create, partial — registry tests only)

- [ ] **Step 1: Write the failing tests**

Create `packages/ai-parrot/tests/test_orchestrator_agent.py`:

```python
"""Tests for OrchestratorAgent enhancements."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.bots.orchestration.agent import OrchestratorAgent
from parrot.models.responses import AIMessage
from parrot.models.basic import CompletionUsage


def _make_ai_message(**overrides) -> AIMessage:
    defaults = {
        "input": "test",
        "output": "test answer",
        "model": "test-model",
        "provider": "test",
        "usage": CompletionUsage(),
        "metadata": {},
    }
    defaults.update(overrides)
    return AIMessage(**defaults)


def _make_mock_agent(name: str):
    agent = MagicMock()
    agent.name = name
    agent.role = f"{name} role"
    agent.goal = f"{name} goal"
    agent.capabilities = None
    agent.is_configured = True
    agent.tool_manager = MagicMock()
    return agent


class TestRegistryIntegration:

    @pytest.mark.asyncio
    @patch("parrot.bots.orchestration.agent.agent_registry")
    async def test_add_agent_by_name_resolves_from_registry(self, mock_registry):
        mock_agent = _make_mock_agent("finance_pokemon")
        mock_registry.get_instance = AsyncMock(return_value=mock_agent)

        orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)
        orchestrator.agent_tools = {}
        orchestrator.specialist_agents = {}
        orchestrator._llm = None
        orchestrator.tool_manager = MagicMock()
        orchestrator.logger = MagicMock()

        await orchestrator.add_agent_by_name("finance_pokemon")

        mock_registry.get_instance.assert_awaited_once_with("finance_pokemon")
        assert "finance_pokemon" in orchestrator.specialist_agents

    @pytest.mark.asyncio
    @patch("parrot.bots.orchestration.agent.agent_registry")
    async def test_add_agent_by_name_raises_on_not_found(self, mock_registry):
        mock_registry.get_instance = AsyncMock(return_value=None)

        orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)
        orchestrator.agent_tools = {}
        orchestrator.specialist_agents = {}
        orchestrator.logger = MagicMock()

        with pytest.raises(ValueError, match="not found in registry"):
            await orchestrator.add_agent_by_name("nonexistent_agent")

    @pytest.mark.asyncio
    @patch("parrot.bots.orchestration.agent.agent_registry")
    async def test_add_agent_by_name_with_custom_tool_name(self, mock_registry):
        mock_agent = _make_mock_agent("finance_epson")
        mock_registry.get_instance = AsyncMock(return_value=mock_agent)

        orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)
        orchestrator.agent_tools = {}
        orchestrator.specialist_agents = {}
        orchestrator._llm = None
        orchestrator.tool_manager = MagicMock()
        orchestrator.logger = MagicMock()

        await orchestrator.add_agent_by_name(
            "finance_epson",
            tool_name="epson_data",
            description="Epson financial data"
        )

        assert "epson_data" in orchestrator.agent_tools
        assert orchestrator.agent_tools["epson_data"].description == "Epson financial data"

    def test_agent_names_stored_as_pending(self):
        with patch("parrot.bots.orchestration.agent.BasicAgent.__init__", return_value=None):
            orchestrator = OrchestratorAgent(
                name="TestOrch",
                agent_names=["agent_a", "agent_b"],
            )
            orchestrator.agent_tools = {}
            orchestrator.specialist_agents = {}
            assert orchestrator._pending_agent_names == ["agent_a", "agent_b"]

    def test_agent_names_defaults_to_empty(self):
        with patch("parrot.bots.orchestration.agent.BasicAgent.__init__", return_value=None):
            orchestrator = OrchestratorAgent(name="TestOrch")
            orchestrator.agent_tools = {}
            orchestrator.specialist_agents = {}
            assert orchestrator._pending_agent_names == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_orchestrator_agent.py::TestRegistryIntegration -v`

Expected: FAIL — `agent_registry` not imported in `orchestration/agent.py`, `add_agent_by_name` not defined, `_pending_agent_names` not defined.

- [ ] **Step 3: Implement registry integration**

In `packages/ai-parrot/src/parrot/bots/orchestration/agent.py`:

**3a.** Add import at top:

```python
from ...registry import agent_registry
```

**3b.** Modify `__init__` to accept `agent_names`:

```python
    def __init__(
        self,
        name: str = "OrchestratorAgent",
        orchestration_prompt: str = None,
        agent_names: Optional[List[str]] = None,
        **kwargs
    ):
        super().__init__(name=name, **kwargs)
        self.agent_tools: Dict[str, AgentTool] = {}
        self.specialist_agents: Dict[str, Union[BasicAgent, AbstractBot]] = {}
        self._pending_agent_names: List[str] = agent_names or []
        if orchestration_prompt:
            self.system_prompt_template = orchestration_prompt
        else:
            self._set_default_orchestration_prompt()
```

**3c.** Modify `configure()` to resolve pending names:

```python
    async def configure(self, app=None) -> None:
        await super().configure(app)
        for name in self._pending_agent_names:
            await self.add_agent_by_name(name)
        await self.register_specialist_agents()
```

**3d.** Add `add_agent_by_name()` method after `add_agent()`:

```python
    async def add_agent_by_name(
        self,
        agent_name: str,
        tool_name: str = None,
        description: str = None,
        **kwargs
    ) -> None:
        """Resolve an agent by name from AgentRegistry and add it as a specialist."""
        agent = await agent_registry.get_instance(agent_name)
        if agent is None:
            raise ValueError(
                f"Agent '{agent_name}' not found in registry"
            )
        if not getattr(agent, 'is_configured', False):
            await agent.configure(app=getattr(self, '_app', None))
        self.add_agent(
            agent=agent,
            tool_name=tool_name,
            description=description,
            **kwargs
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_orchestrator_agent.py::TestRegistryIntegration -v`

Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/ai-parrot/src/parrot/bots/orchestration/agent.py packages/ai-parrot/tests/test_orchestrator_agent.py
git commit -m "feat(orchestration): add registry integration to OrchestratorAgent"
```

---

### Task 4: OrchestratorAgent Pass-through Mode

**Files:**
- Modify: `packages/ai-parrot/src/parrot/bots/orchestration/agent.py`
- Test: `packages/ai-parrot/tests/test_orchestrator_agent.py` (append to existing)

- [ ] **Step 1: Write the failing tests**

Append to `packages/ai-parrot/tests/test_orchestrator_agent.py`:

```python
from parrot.models.crew import AgentResult
from parrot.bots.flows.core.storage import ExecutionMemory  # updated: parrot.bots.flow deleted in FEAT-196


class TestPassthroughMode:

    def _make_orchestrator(self):
        orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)
        orchestrator.agent_tools = {}
        orchestrator.specialist_agents = {}
        orchestrator._llm = None
        orchestrator.tool_manager = MagicMock()
        orchestrator.logger = MagicMock()
        return orchestrator

    def test_is_passthrough_eligible_with_data(self):
        orchestrator = self._make_orchestrator()
        specialist_msg = _make_ai_message(data={"revenue": [100]})
        memory = ExecutionMemory(original_query="test")
        memory.results["agent_a"] = AgentResult(
            agent_id="agent_a",
            agent_name="Agent A",
            task="test",
            result="text",
            ai_message=specialist_msg,
            metadata={},
            execution_time=1.0,
        )
        orchestrator._execution_memory = memory
        orch_response = _make_ai_message()
        assert orchestrator._is_passthrough_eligible(orch_response) is True

    def test_is_passthrough_eligible_with_artifacts(self):
        orchestrator = self._make_orchestrator()
        specialist_msg = _make_ai_message(
            artifacts=[{"type": "sql", "content": "SELECT *"}]
        )
        memory = ExecutionMemory(original_query="test")
        memory.results["agent_a"] = AgentResult(
            agent_id="agent_a",
            agent_name="Agent A",
            task="test",
            result="text",
            ai_message=specialist_msg,
            metadata={},
            execution_time=1.0,
        )
        orchestrator._execution_memory = memory
        assert orchestrator._is_passthrough_eligible(_make_ai_message()) is True

    def test_is_passthrough_eligible_with_code(self):
        orchestrator = self._make_orchestrator()
        specialist_msg = _make_ai_message(code="df.sum()")
        memory = ExecutionMemory(original_query="test")
        memory.results["agent_a"] = AgentResult(
            agent_id="agent_a",
            agent_name="Agent A",
            task="test",
            result="text",
            ai_message=specialist_msg,
            metadata={},
            execution_time=1.0,
        )
        orchestrator._execution_memory = memory
        assert orchestrator._is_passthrough_eligible(_make_ai_message()) is True

    def test_not_passthrough_eligible_text_only(self):
        orchestrator = self._make_orchestrator()
        specialist_msg = _make_ai_message()  # no data, no artifacts, no code
        memory = ExecutionMemory(original_query="test")
        memory.results["agent_a"] = AgentResult(
            agent_id="agent_a",
            agent_name="Agent A",
            task="test",
            result="text",
            ai_message=specialist_msg,
            metadata={},
            execution_time=1.0,
        )
        orchestrator._execution_memory = memory
        assert orchestrator._is_passthrough_eligible(_make_ai_message()) is False

…(truncated)…
