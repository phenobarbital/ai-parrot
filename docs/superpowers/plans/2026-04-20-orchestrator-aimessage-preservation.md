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
from parrot.bots.flow.storage.memory import ExecutionMemory


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
from parrot.bots.flow.storage.memory import ExecutionMemory


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

    def test_not_passthrough_eligible_no_ai_message(self):
        orchestrator = self._make_orchestrator()
        memory = ExecutionMemory(original_query="test")
        memory.results["agent_a"] = AgentResult(
            agent_id="agent_a",
            agent_name="Agent A",
            task="test",
            result="text",
            ai_message=None,
            metadata={},
            execution_time=1.0,
        )
        orchestrator._execution_memory = memory
        assert orchestrator._is_passthrough_eligible(_make_ai_message()) is False

    def test_build_passthrough_response(self):
        orchestrator = self._make_orchestrator()
        specialist_msg = _make_ai_message(
            output="Q4 revenue is $1M",
            data={"revenue": [1000000]},
            code="df['revenue'].sum()",
        )
        orch_response = _make_ai_message(
            input="What is Q4 revenue for Pokemon?",
            output="Here is the Q4 revenue...",
        )
        orch_response.session_id = "session-123"
        orch_response.turn_id = "turn-456"

        agent_results = {
            "pokemon_finance": AgentResult(
                agent_id="pokemon_finance",
                agent_name="pokemon_finance",
                task="Q4 revenue",
                result="Q4 revenue is $1M",
                ai_message=specialist_msg,
                metadata={},
                execution_time=1.0,
            )
        }

        result = orchestrator._build_passthrough_response(orch_response, agent_results)

        assert result is specialist_msg
        assert result.data == {"revenue": [1000000]}
        assert result.code == "df['revenue'].sum()"
        assert result.session_id == "session-123"
        assert result.turn_id == "turn-456"
        assert result.input == "What is Q4 revenue for Pokemon?"
        assert result.metadata["orchestrated"] is True
        assert result.metadata["mode"] == "passthrough"
        assert result.metadata["routed_to"] == "pokemon_finance"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_orchestrator_agent.py::TestPassthroughMode -v`

Expected: FAIL — `_is_passthrough_eligible`, `_build_passthrough_response`, `_execution_memory` not defined.

- [ ] **Step 3: Implement pass-through helpers**

In `packages/ai-parrot/src/parrot/bots/orchestration/agent.py`, add these imports at the top:

```python
from ...models.responses import AIMessage
from ...models.crew import AgentResult
```

Then add these methods to `OrchestratorAgent`:

```python
    def _init_execution_memory(self, question: str):
        """Create fresh execution memory and wire it to all AgentTools."""
        from ...bots.flow.storage.memory import ExecutionMemory
        self._execution_memory = ExecutionMemory(original_query=question)
        for agent_tool in self.agent_tools.values():
            agent_tool.execution_memory = self._execution_memory

    def _collect_agent_results(self) -> Dict[str, AgentResult]:
        """Get all agent results from the current execution."""
        return dict(self._execution_memory.results)

    def _is_passthrough_eligible(self, response: AIMessage) -> bool:
        """Check if response should pass through the specialist's AIMessage directly.

        Pass-through when exactly 1 agent was called and its AIMessage
        contains rich content (data, artifacts, images, or code).
        """
        agent_result = list(self._execution_memory.results.values())[0]
        if agent_result.ai_message is None:
            return False
        specialist = agent_result.ai_message
        return bool(
            specialist.data is not None
            or specialist.artifacts
            or specialist.images
            or specialist.code
        )

    def _build_passthrough_response(
        self,
        orchestrator_response: AIMessage,
        agent_results: Dict[str, AgentResult]
    ) -> AIMessage:
        """Return the specialist's AIMessage with orchestrator session metadata."""
        agent_result = list(agent_results.values())[0]
        specialist_msg = agent_result.ai_message
        specialist_msg.session_id = orchestrator_response.session_id
        specialist_msg.turn_id = orchestrator_response.turn_id
        specialist_msg.input = orchestrator_response.input
        specialist_msg.metadata = {
            **specialist_msg.metadata,
            "orchestrated": True,
            "mode": "passthrough",
            "routed_to": agent_result.agent_name,
        }
        return specialist_msg
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_orchestrator_agent.py::TestPassthroughMode -v`

Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/ai-parrot/src/parrot/bots/orchestration/agent.py packages/ai-parrot/tests/test_orchestrator_agent.py
git commit -m "feat(orchestration): add pass-through mode helpers to OrchestratorAgent"
```

---

### Task 5: OrchestratorAgent Synthesis Mode

**Files:**
- Modify: `packages/ai-parrot/src/parrot/bots/orchestration/agent.py`
- Test: `packages/ai-parrot/tests/test_orchestrator_agent.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `packages/ai-parrot/tests/test_orchestrator_agent.py`:

```python
class TestSynthesisMode:

    def _make_orchestrator(self):
        orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)
        orchestrator.agent_tools = {}
        orchestrator.specialist_agents = {}
        orchestrator._llm = None
        orchestrator.tool_manager = MagicMock()
        orchestrator.logger = MagicMock()
        return orchestrator

    def test_build_synthesis_merges_data_per_agent(self):
        orchestrator = self._make_orchestrator()
        orch_response = _make_ai_message(
            output="Pokemon margin 32%, Epson margin 28%",
        )

        agent_results = {
            "pokemon_finance": AgentResult(
                agent_id="pokemon_finance",
                agent_name="pokemon_finance",
                task="margins",
                result="32%",
                ai_message=_make_ai_message(data={"margin": 0.32}),
                metadata={},
                execution_time=1.0,
            ),
            "epson_finance": AgentResult(
                agent_id="epson_finance",
                agent_name="epson_finance",
                task="margins",
                result="28%",
                ai_message=_make_ai_message(data={"margin": 0.28}),
                metadata={},
                execution_time=1.0,
            ),
        }

        result = orchestrator._build_synthesis_response(orch_response, agent_results)

        assert result is orch_response
        assert result.output == "Pokemon margin 32%, Epson margin 28%"
        assert result.data == {
            "pokemon_finance": {"margin": 0.32},
            "epson_finance": {"margin": 0.28},
        }
        assert result.metadata["orchestrated"] is True
        assert result.metadata["mode"] == "synthesis"
        assert set(result.metadata["agents_consulted"]) == {"pokemon_finance", "epson_finance"}

    def test_build_synthesis_merges_artifacts_with_attribution(self):
        orchestrator = self._make_orchestrator()
        orch_response = _make_ai_message()

        agent_results = {
            "agent_a": AgentResult(
                agent_id="agent_a",
                agent_name="agent_a",
                task="task",
                result="text",
                ai_message=_make_ai_message(
                    artifacts=[{"type": "sql", "content": "SELECT a"}]
                ),
                metadata={},
                execution_time=1.0,
            ),
            "agent_b": AgentResult(
                agent_id="agent_b",
                agent_name="agent_b",
                task="task",
                result="text",
                ai_message=_make_ai_message(
                    artifacts=[{"type": "sql", "content": "SELECT b"}]
                ),
                metadata={},
                execution_time=1.0,
            ),
        }

        result = orchestrator._build_synthesis_response(orch_response, agent_results)

        assert len(result.artifacts) == 2
        assert result.artifacts[0]["source_agent"] == "agent_a"
        assert result.artifacts[1]["source_agent"] == "agent_b"

    def test_build_synthesis_skips_agents_without_ai_message(self):
        orchestrator = self._make_orchestrator()
        orch_response = _make_ai_message()

        agent_results = {
            "agent_a": AgentResult(
                agent_id="agent_a",
                agent_name="agent_a",
                task="task",
                result="text",
                ai_message=_make_ai_message(data={"x": 1}),
                metadata={},
                execution_time=1.0,
            ),
            "agent_b": AgentResult(
                agent_id="agent_b",
                agent_name="agent_b",
                task="task",
                result="text only",
                ai_message=None,
                metadata={},
                execution_time=1.0,
            ),
        }

        result = orchestrator._build_synthesis_response(orch_response, agent_results)

        assert result.data == {"agent_a": {"x": 1}}

    def test_build_synthesis_no_data_leaves_response_data_unchanged(self):
        orchestrator = self._make_orchestrator()
        orch_response = _make_ai_message()

        agent_results = {
            "agent_a": AgentResult(
                agent_id="agent_a",
                agent_name="agent_a",
                task="task",
                result="text",
                ai_message=_make_ai_message(),  # no data
                metadata={},
                execution_time=1.0,
            ),
        }

        result = orchestrator._build_synthesis_response(orch_response, agent_results)

        assert result.data is None
        assert result.metadata["mode"] == "synthesis"

    def test_build_synthesis_merges_source_documents(self):
        orchestrator = self._make_orchestrator()
        orch_response = _make_ai_message()

        from parrot.models.responses import SourceDocument
        doc_a = SourceDocument(source="db_a", filename="report_a.csv")
        doc_b = SourceDocument(source="db_b", filename="report_b.csv")

        agent_results = {
            "agent_a": AgentResult(
                agent_id="agent_a",
                agent_name="agent_a",
                task="task",
                result="text",
                ai_message=_make_ai_message(source_documents=[doc_a]),
                metadata={},
                execution_time=1.0,
            ),
            "agent_b": AgentResult(
                agent_id="agent_b",
                agent_name="agent_b",
                task="task",
                result="text",
                ai_message=_make_ai_message(source_documents=[doc_b]),
                metadata={},
                execution_time=1.0,
            ),
        }

        result = orchestrator._build_synthesis_response(orch_response, agent_results)

        assert len(result.source_documents) == 2
        sources = [d.source for d in result.source_documents]
        assert "db_a" in sources
        assert "db_b" in sources
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_orchestrator_agent.py::TestSynthesisMode -v`

Expected: FAIL — `_build_synthesis_response` not defined.

- [ ] **Step 3: Implement synthesis mode**

Add to `OrchestratorAgent` in `packages/ai-parrot/src/parrot/bots/orchestration/agent.py`:

```python
    def _build_synthesis_response(
        self,
        orchestrator_response: AIMessage,
        agent_results: Dict[str, AgentResult]
    ) -> AIMessage:
        """Merge data from multiple agents into the orchestrator's response."""
        merged_data = {}
        merged_artifacts = []
        merged_sources = []

        for agent_name, agent_result in agent_results.items():
            if agent_result.ai_message is None:
                continue
            msg = agent_result.ai_message
            if msg.data is not None:
                merged_data[agent_name] = msg.data
            for artifact in (msg.artifacts or []):
                merged_artifacts.append({
                    **artifact,
                    "source_agent": agent_name,
                })
            merged_sources.extend(msg.source_documents or [])

        if merged_data:
            orchestrator_response.data = merged_data
        if merged_artifacts:
            orchestrator_response.artifacts = merged_artifacts
        if merged_sources:
            orchestrator_response.source_documents = merged_sources

        orchestrator_response.metadata = {
            **orchestrator_response.metadata,
            "orchestrated": True,
            "mode": "synthesis",
            "agents_consulted": list(agent_results.keys()),
        }
        return orchestrator_response
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_orchestrator_agent.py::TestSynthesisMode -v`

Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/ai-parrot/src/parrot/bots/orchestration/agent.py packages/ai-parrot/tests/test_orchestrator_agent.py
git commit -m "feat(orchestration): add synthesis mode to OrchestratorAgent"
```

---

### Task 6: OrchestratorAgent Custom ask() — Wiring It Together

**Files:**
- Modify: `packages/ai-parrot/src/parrot/bots/orchestration/agent.py`
- Test: `packages/ai-parrot/tests/test_orchestrator_agent.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `packages/ai-parrot/tests/test_orchestrator_agent.py`:

```python
from parrot.tools.agent import AgentTool


class TestOrchestratorAsk:

    def _make_orchestrator_with_tools(self):
        orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)
        orchestrator.agent_tools = {}
        orchestrator.specialist_agents = {}
        orchestrator._llm = None
        orchestrator.tool_manager = MagicMock()
        orchestrator.logger = MagicMock()
        return orchestrator

    @pytest.mark.asyncio
    async def test_ask_passthrough_single_agent_with_data(self):
        orchestrator = self._make_orchestrator_with_tools()

        specialist_msg = _make_ai_message(
            output="Revenue is $1M",
            data={"revenue": [1000000]},
        )

        # Mock super().ask() to simulate the LLM calling one agent tool
        orch_response = _make_ai_message(
            input="What is Pokemon revenue?",
            output="Here is the revenue data",
        )
        orch_response.session_id = "s1"
        orch_response.turn_id = "t1"

        # We need to simulate execution_memory being populated during super().ask()
        async def fake_super_ask(question, **kwargs):
            orchestrator._execution_memory.results["pokemon_finance"] = AgentResult(
                agent_id="pokemon_finance",
                agent_name="pokemon_finance",
                task=question,
                result="Revenue is $1M",
                ai_message=specialist_msg,
                metadata={},
                execution_time=1.0,
            )
            return orch_response

        # Add a mock agent tool so _init_execution_memory wires it
        mock_agent = _make_mock_agent("pokemon_finance")
        mock_tool = AgentTool(agent=mock_agent)
        orchestrator.agent_tools["pokemon_finance"] = mock_tool

        with patch.object(
            OrchestratorAgent.__bases__[0], "ask",
            side_effect=fake_super_ask
        ):
            result = await orchestrator.ask("What is Pokemon revenue?")

        assert result is specialist_msg
        assert result.data == {"revenue": [1000000]}
        assert result.metadata["mode"] == "passthrough"
        assert result.session_id == "s1"

    @pytest.mark.asyncio
    async def test_ask_synthesis_multiple_agents(self):
        orchestrator = self._make_orchestrator_with_tools()

        pokemon_msg = _make_ai_message(data={"margin": 0.32})
        epson_msg = _make_ai_message(data={"margin": 0.28})

        orch_response = _make_ai_message(
            input="Compare margins",
            output="Pokemon 32% vs Epson 28%",
        )
        orch_response.session_id = "s1"
        orch_response.turn_id = "t1"

        async def fake_super_ask(question, **kwargs):
            orchestrator._execution_memory.results["pokemon_finance"] = AgentResult(
                agent_id="pokemon_finance",
                agent_name="pokemon_finance",
                task=question,
                result="32%",
                ai_message=pokemon_msg,
                metadata={},
                execution_time=1.0,
            )
            orchestrator._execution_memory.results["epson_finance"] = AgentResult(
                agent_id="epson_finance",
                agent_name="epson_finance",
                task=question,
                result="28%",
                ai_message=epson_msg,
                metadata={},
                execution_time=1.0,
            )
            return orch_response

        mock_agent_a = _make_mock_agent("pokemon_finance")
        mock_agent_b = _make_mock_agent("epson_finance")
        orchestrator.agent_tools["pokemon_finance"] = AgentTool(agent=mock_agent_a)
        orchestrator.agent_tools["epson_finance"] = AgentTool(agent=mock_agent_b)

        with patch.object(
            OrchestratorAgent.__bases__[0], "ask",
            side_effect=fake_super_ask
        ):
            result = await orchestrator.ask("Compare margins")

        assert result is orch_response
        assert result.output == "Pokemon 32% vs Epson 28%"
        assert result.data == {
            "pokemon_finance": {"margin": 0.32},
            "epson_finance": {"margin": 0.28},
        }
        assert result.metadata["mode"] == "synthesis"

    @pytest.mark.asyncio
    async def test_ask_no_agents_called_returns_base_response(self):
        orchestrator = self._make_orchestrator_with_tools()

        orch_response = _make_ai_message(output="I don't know")

        async def fake_super_ask(question, **kwargs):
            return orch_response

        with patch.object(
            OrchestratorAgent.__bases__[0], "ask",
            side_effect=fake_super_ask
        ):
            result = await orchestrator.ask("Something unrelated")

        assert result is orch_response
        assert result.data is None

    @pytest.mark.asyncio
    async def test_ask_init_execution_memory_wires_all_tools(self):
        orchestrator = self._make_orchestrator_with_tools()

        mock_agent_a = _make_mock_agent("agent_a")
        mock_agent_b = _make_mock_agent("agent_b")
        tool_a = AgentTool(agent=mock_agent_a)
        tool_b = AgentTool(agent=mock_agent_b)
        orchestrator.agent_tools["agent_a"] = tool_a
        orchestrator.agent_tools["agent_b"] = tool_b

        orchestrator._init_execution_memory("test query")

        assert tool_a.execution_memory is orchestrator._execution_memory
        assert tool_b.execution_memory is orchestrator._execution_memory
        assert orchestrator._execution_memory.original_query == "test query"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_orchestrator_agent.py::TestOrchestratorAsk -v`

Expected: FAIL — `OrchestratorAgent.ask` not overridden yet.

- [ ] **Step 3: Implement custom ask()**

Add to `OrchestratorAgent` in `packages/ai-parrot/src/parrot/bots/orchestration/agent.py`:

```python
    async def ask(self, question: str, **kwargs) -> AIMessage:
        """Ask with automatic pass-through or synthesis based on agent responses.

        Delegates to super().ask() which runs the LLM tool-calling loop.
        After completion, inspects execution_memory to determine if the
        response should be passed through from a single specialist or
        synthesized from multiple.
        """
        self._init_execution_memory(question)
        response = await super().ask(question, **kwargs)
        agent_results = self._collect_agent_results()

        if not agent_results:
            return response

        if len(agent_results) == 1 and self._is_passthrough_eligible(response):
            return self._build_passthrough_response(response, agent_results)

        return self._build_synthesis_response(response, agent_results)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_orchestrator_agent.py::TestOrchestratorAsk -v`

Expected: 4 tests PASS

- [ ] **Step 5: Run ALL orchestrator tests together**

Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_orchestrator_agent.py -v`

Expected: All 20 tests PASS (5 registry + 6 passthrough + 5 synthesis + 4 ask)

- [ ] **Step 6: Run broader regression check**

Run: `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_agent_result_ai_message.py packages/ai-parrot/tests/test_agent_tool_ai_message.py packages/ai-parrot/tests/test_orchestrator_agent.py packages/ai-parrot/tests/test_execution_memory_integration.py -v`

Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add packages/ai-parrot/src/parrot/bots/orchestration/agent.py packages/ai-parrot/tests/test_orchestrator_agent.py
git commit -m "feat(orchestration): implement custom ask() with pass-through and synthesis modes"
```

---

## Summary

| Task | What it delivers | Tests |
|---|---|---|
| 1 | `AgentResult.ai_message` field | 4 unit tests |
| 2 | `AgentTool` captures AIMessage in execution memory | 5 unit tests |
| 3 | Registry integration (`add_agent_by_name`, `agent_names`) | 5 unit tests |
| 4 | Pass-through mode helpers | 6 unit tests |
| 5 | Synthesis mode helper | 5 unit tests |
| 6 | Custom `ask()` wiring everything together | 4 unit tests |
| **Total** | | **29 unit tests** |
