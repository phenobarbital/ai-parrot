"""
Data models for Agent Crew execution results.

Provides standardized output format for all crew execution modes.
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional, Literal, Union, Protocol
from datetime import datetime
import uuid
from dataclasses import dataclass, field
import numpy as np
from datamodel.parsers.json import json_encoder  # pylint: disable=E0611 # noqa
from .responses import AIMessage, AgentResponse


ResponseType = Union[AIMessage, AgentResponse, Any]


@dataclass
class AgentExecutionInfo:
    """Information about an agent's execution in a crew workflow."""
    agent_id: str
    """Unique identifier for the agent"""
    agent_name: str
    """Human-readable name of the agent"""
    provider: Optional[str] = None
    """LLM provider used (e.g., 'openai', 'anthropic', 'google')"""
    model: Optional[str] = None
    """Model name used (e.g., 'gpt-4', 'claude-3-opus')"""
    execution_time: float = 0.0
    """Time taken to execute this agent (seconds)"""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    """List of tool calls made by this agent"""
    status: Literal['completed', 'failed', 'pending', 'running'] = 'pending'
    """Execution status of the agent"""
    error: Optional[str] = None
    """Error message if agent failed"""
    client: Optional[str] = None
    """Concrete client class name backing the agent (if available)"""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the execution info to a plain dictionary."""

        return {
            'agent_id': self.agent_id,
            'agent_name': self.agent_name,
            'llm_provider': self.provider,
            'model': self.model,
            'execution_time': self.execution_time,
            'tool_calls': self.tool_calls,
            'status': self.status,
            'error': self.error,
            'client': self.client,
        }


@dataclass
class CrewResult:
    """
    Standardized result from crew execution.

    This dataclass provides a consistent interface across all crew execution modes
    (sequential, parallel, flow, FSM) and is compatible with OutputFormatter.

    Attributes:
        output: The final output text (alias for content)
        content: The final output text (primary field for OutputFormatter compatibility)
        response: List of raw response objects (AIMessage/AgentResponse) from each agent
        results: List of all agent outputs in execution order
        agent_ids: List of agent IDs that executed
        agents: Detailed information about each agent's execution
        execution_log: Detailed log of execution steps
        total_time: Total execution time in seconds
        status: Overall execution status
        errors: Dictionary of errors by agent_id (if any)
        metadata: Additional metadata about the execution
    """

    output: str
    response: Dict[str, ResponseType] = field(default_factory=dict)
    results: List[Any] = field(default_factory=list)
    agent_ids: List[str] = field(default_factory=list)
    agents: List[AgentExecutionInfo] = field(default_factory=list)
    """Detailed information about each agent's execution"""
    execution_log: List[Dict[str, Any]] = field(default_factory=list)
    """Detailed log of execution steps"""
    total_time: float = 0.0
    status: Literal['completed', 'partial', 'failed'] = 'completed'
    """
    Overall execution status:
    - completed: All agents succeeded
    - partial: Some agents succeeded, some failed
    - failed: All agents failed or critical error
    """
    errors: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional metadata about the execution (mode, iterations, etc.)"""

    def __str__(self) -> str:
        """String representation showing the final output."""
        return str(self.content)

    def __repr__(self) -> str:
        """Detailed representation for debugging."""
        return f"CrewResult(status={self.status}, agents={len(self.agents)}, time={self.total_time:.2f}s)"

    @property
    def content(self) -> Optional[Any]:
        """Alias for the final output content."""

        return self.output

    @property
    def final_result(self) -> Optional[Any]:
        """Compatibility alias for previous API."""

        return self.output

    @property
    def success(self) -> bool:
        """Boolean success flag for backward compatibility."""

        return self.status == "completed"

    @property
    def agent_results(self) -> Dict[str, Any]:
        """Map agent IDs to their outputs."""

        return {
            agent_id: self.results[idx]
            for idx, agent_id in enumerate(self.agent_ids)
            if idx < len(self.results)
        }

    @property
    def completed(self) -> List[str]:
        """Return agent IDs with successful execution."""
        completed_agents: List[str] = []

        for agent in self.agents:
            if isinstance(agent, AgentExecutionInfo):
                if agent.status == "completed" and agent.agent_id:
                    completed_agents.append(agent.agent_id)
            elif isinstance(agent, dict):
                agent_id = agent.get("agent_id")
                status = _normalise_agent_status(agent.get("status", ""))

                if agent_id and status == "completed":
                    completed_agents.append(agent_id)

        return completed_agents

    @property
    def failed(self) -> List[str]:
        """Return agent IDs with failed execution."""
        failed_agents: List[str] = []

        for agent in self.agents:
            if isinstance(agent, AgentExecutionInfo):
                if agent.status == "failed" and agent.agent_id:
                    failed_agents.append(agent.agent_id)
            elif isinstance(agent, dict):
                agent_id = agent.get("agent_id")
                status = _normalise_agent_status(agent.get("status", ""))

                if agent_id and status == "failed":
                    failed_agents.append(agent_id)

        return failed_agents

    @property
    def total_execution_time(self) -> float:
        """Compatibility alias for total execution time."""
        return self.total_time

    def __getitem__(self, item: str) -> Any:
        """Dictionary-style access for backward compatibility."""

        mapping = {
            "final_result": self.output,
            "output": self.output,
            "content": self.content,
            "results": self.agent_results,
            "results_list": self.results,
            "agent_results": self.agent_results,
            "agent_ids": self.agent_ids,
            "agents": [agent.to_dict() if isinstance(agent, AgentExecutionInfo) else agent for agent in self.agents],
            "errors": self.errors,
            "execution_log": self.execution_log,
            "total_time": self.total_time,
            "total_execution_time": self.total_time,
            "success": self.success,
            "status": self.status,
            "response": self.response,
            "completed": self.completed,
            "failed": self.failed,
        }

        if item in mapping:
            return mapping[item]

        raise KeyError(item)


"""Crew-related data models."""
def determine_run_status(
    success_count: int,
    failure_count: int,
) -> Literal['completed', 'partial', 'failed']:
    """Compute the overall status for a crew execution."""

    if failure_count == 0:
        return 'completed'

    return 'failed' if success_count == 0 else 'partial'

def _serialise_tool_calls(tool_calls: Any) -> List[Any]:
    """Normalise tool call structures for metadata output."""

    if not tool_calls:
        return []

    serialised: List[Any] = []

    for call in tool_calls:
        if hasattr(call, "model_dump"):
            serialised.append(call.model_dump())
        elif hasattr(call, "dict"):
            serialised.append(call.dict())
        else:
            serialised.append(call)

    return serialised


def _get_llm_info(agent: Optional[Any]) -> Dict[str, Any]:
    """Extract lightweight information about the agent LLM/client."""

    if agent is None:
        return {}

    llm_info: Dict[str, Any] = {}

    provider = getattr(agent, "use_llm", None) or getattr(agent, "provider", None)
    if provider:
        llm_info["provider"] = provider

    if (client := getattr(agent, "llm", None) or getattr(agent, "_llm", None)):
        if (model_name := getattr(client, "model", None) or getattr(client, "deployment_name", None)):
            llm_info["model"] = model_name
        llm_info.setdefault("client", client.__class__.__name__)

    return llm_info

def _normalise_agent_status(
    status: str,
) -> Literal['completed', 'failed', 'pending', 'running']:
    """Map legacy status strings to the AgentExecutionInfo status options."""

    normalised = status.lower()
    mapping = {
        'success': 'completed',
        'completed': 'completed',
        'error': 'failed',
        'failed': 'failed',
        'pending': 'pending',
        'running': 'running',
    }

    return mapping.get(normalised, 'pending')


def build_agent_metadata(
    agent_id: str,
    agent: Optional[Any],
    response: Optional[ResponseType],
    output: Optional[Any],
    execution_time: float,
    status: str,
    error: Optional[str] = None,
) -> AgentExecutionInfo:
    """Create execution metadata for an agent run."""

    model = None
    provider = None
    tool_calls: List[Any] = []

    # Prefer structured response information when available
    if isinstance(response, AgentResponse):
        ai_message = response.response if isinstance(response.response, AIMessage) else None
        model = getattr(response, 'model', None) or getattr(ai_message, 'model', None)
        provider = getattr(response, 'provider', None) or getattr(ai_message, 'provider', None)
        raw_tool_calls = (
            getattr(response, 'tool_calls', None)
            or getattr(ai_message, 'tool_calls', None)
            or []
        )
        tool_calls = _serialise_tool_calls(raw_tool_calls)
        if output is None:
            output = response.output or getattr(ai_message, 'output', None)
    elif isinstance(response, AIMessage):
        model = getattr(response, 'model', None)
        provider = getattr(response, 'provider', None)
        tool_calls = _serialise_tool_calls(getattr(response, 'tool_calls', None))
        if output is None:
            output = getattr(response, 'output', None) or getattr(response, 'content', None)
    elif response is not None:
        model = getattr(response, 'model', None)
        provider = getattr(response, 'provider', None)
        tool_calls = _serialise_tool_calls(getattr(response, 'tool_calls', None))

    llm_info = _get_llm_info(agent)
    provider = provider or llm_info.get('provider')
    model = model or llm_info.get('model')

    return AgentExecutionInfo(
        agent_id=agent_id,
        agent_name=getattr(agent, 'name', agent_id) if agent else agent_id,
        provider=provider,
        model=model,
        execution_time=execution_time,
        tool_calls=tool_calls,
        status=_normalise_agent_status(status),
        error=error,
        client=llm_info.get('client'),
    )

@dataclass
class AgentResult:
    """Captures a single agent execution with full context"""
    agent_id: str
    agent_name: str
    task: str
    result: Any
    metadata: Dict[str, Any]
    execution_time: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    parent_execution_id: Optional[str] = None  # For tracking re-executions
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_text(self) -> str:
        """Convert execution result to text for vectorization"""
        from pandas import DataFrame  # noqa F401

        result_type = type(self.result).__name__

        base_info = f"""Agent: {self.agent_name}
Task: {self.task}
Result Type: {result_type}
Execution Time: {self.execution_time}s
Timestamp: {self.timestamp.isoformat()}
        """

        if isinstance(self.result, DataFrame):
            df = self.result
            content = f"""
Shape: {df.shape[0]} rows × {df.shape[1]} columns
Columns: {', '.join(df.columns)}

Data Types:
{df.dtypes.to_string()}

Statistics:
{df.describe().to_string() if len(df) > 0 else 'No numerical data'}

Sample Data (first 10 rows):
{df.head(10).to_string()}
            """
        elif isinstance(self.result, dict):
            content = f"""
Keys: {', '.join(self.result.keys())}
Content:
{json_encoder(self.result)}
            """
        elif isinstance(self.result, list):
            content = f"""
Length: {len(self.result)} items
Item Types: {', '.join(set(type(item).__name__ for item in self.result[:100]))}
Sample Items:
{json_encoder(self.result[:10]) if len(self.result) > 0 else '[]'}
            """
        else:
            content = f"""
Content:
{str(self.result)}
            """

        return base_info + content


class VectorStoreProtocol(Protocol):
    """Protocol for vector store implementations"""
    def encode(self, texts: List[str]) -> np.ndarray:
        """Encode texts to embeddings"""
        ...
