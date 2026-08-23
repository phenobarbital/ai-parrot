"""Flow Primitives — Result Models.

Provides ``FlowResult`` (replacing ``CrewResult``) and ``NodeExecutionInfo``
(replacing ``AgentExecutionInfo``) as the canonical result models for both
orchestration engines.

Also provides ``NodeResult`` (replacing ``AgentResult``) as the unified
per-node execution record for ``ExecutionMemory`` and FAISS vectorization.

All backward-compatible aliases are preserved so existing code importing
``CrewResult`` / ``AgentExecutionInfo`` continues to work via re-exports
in ``parrot.models.crew`` (wired up in TASK-920).

``AgentResult`` stays in ``parrot.models.crew`` for any remaining consumers.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, TYPE_CHECKING

from .types import FlowStatus

if TYPE_CHECKING:
    # Avoid a hard import cycle: infographic_toolkit imports from parrot.models.*,
    # not from bots.flows.core.result — this is import-safe, but kept lazy/forward
    # to keep FlowResult's module import light. (FEAT-308)
    from parrot.tools.infographic_toolkit import InfographicRenderResult

# ResponseType alias — mirrors the one in parrot.models.crew
try:
    from parrot.models.responses import AIMessage, AgentResponse  # noqa: F401
    ResponseType = Any  # Union[AIMessage, AgentResponse, Any] but avoids heavy import
except ImportError:
    ResponseType = Any


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _serialise_result_value(value: Any) -> Any:
    """Recursively serialise a value into a JSON-safe representation.

    Used by ``NodeResult.to_dict()`` to guarantee the returned dict always
    survives ``json.dumps(d, default=str)``, regardless of what the node
    produced (``DataFrame``, arbitrary object, nested dict/list, etc.).
    This function MUST NOT raise for any input.

    Args:
        value: Arbitrary value produced by a node's execution.

    Returns:
        A JSON-safe value: primitives pass through, dict/list are
        recursively serialised, ``pandas.DataFrame`` becomes a bounded
        string preview, and everything else falls back to ``str()``.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {str(k): _serialise_result_value(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_serialise_result_value(v) for v in value]

    try:
        from pandas import DataFrame  # noqa: F401  (lazy import)

        if isinstance(value, DataFrame):
            return (
                f"DataFrame {value.shape[0]}x{value.shape[1]} "
                f"cols=[{', '.join(map(str, value.columns))}]\n"
                f"{value.head(10).to_string()}"
            )
    except ImportError:
        pass

    try:
        return str(value)
    except Exception:  # noqa: BLE001 - to_dict() must never raise
        return "<unserialisable value>"


# ---------------------------------------------------------------------------
# NodeResult (replaces AgentResult for all flow-internal usage)
# ---------------------------------------------------------------------------


@dataclass
class NodeResult:
    """Per-node execution record for storage and vectorization.

    Replaces ``AgentResult`` (``parrot.models.crew``) for all flow-internal
    usage. Uses node-centric naming (``node_id``/``node_name``) while
    providing backward-compat ``agent_id``/``agent_name`` property aliases.

    The ``to_text()`` method produces rich text suitable for FAISS
    vectorization, handling ``DataFrame``, ``dict``, ``list``, and plain
    string results.

    Args:
        node_id: Unique identifier for this node's execution.
        node_name: Human-readable name of the node/agent.
        task: The task/prompt string given to the node.
        result: The result value produced by the node.
        ai_message: Optional raw AI message from the LLM.
        metadata: Arbitrary additional metadata dict.
        execution_time: Wall-clock time for this execution (seconds).
        timestamp: UTC timestamp of this execution record.
        parent_execution_id: If this is a re-execution, the parent's ID.
        execution_id: Unique ID for this execution record (auto-generated).
    """

    node_id: str
    node_name: str
    task: str
    result: Any
    ai_message: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    parent_execution_id: Optional[str] = None
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # ── Backward-compat aliases ──────────────────────────────────────────

    @property
    def agent_id(self) -> str:
        """Alias for ``node_id`` (backward compat with ``AgentResult.agent_id``)."""
        return self.node_id

    @property
    def agent_name(self) -> str:
        """Alias for ``node_name`` (backward compat with ``AgentResult.agent_name``)."""
        return self.node_name

    # ── Vectorization support ────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain, JSON-safe dictionary.

        Never raises, regardless of what ``result`` holds (``DataFrame``,
        arbitrary object, dict, list, etc.). ``ai_message`` is deliberately
        excluded — it is a raw LLM object and not JSON-safe.

        Returns:
            Dictionary with node identity, task, safely-serialised result,
            metadata, timing, and correlation ids.
        """
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            # Backward-compat aliases in output dict
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "task": self.task,
            "result": _serialise_result_value(self.result),
            "metadata": _serialise_result_value(self.metadata),
            "execution_time": self.execution_time,
            "timestamp": self.timestamp.isoformat(),
            "parent_execution_id": self.parent_execution_id,
            "execution_id": self.execution_id,
        }

    def to_text(self) -> str:
        """Convert execution result to rich text for FAISS vectorization.

        Handles ``pandas.DataFrame``, ``dict``, ``list``, and plain string
        results.  ``DataFrame`` is imported lazily to avoid a hard dependency.

        Returns:
            Formatted string describing the node's execution.
        """
        result_type = type(self.result).__name__

        base_info = (
            f"Agent: {self.node_name}\n"
            f"Task: {self.task}\n"
            f"Result Type: {result_type}\n"
            f"Execution Time: {self.execution_time}s\n"
            f"Timestamp: {self.timestamp.isoformat()}\n        "
        )

        try:
            from pandas import DataFrame  # noqa: F401  (lazy import)

            if isinstance(self.result, DataFrame):
                df = self.result
                content = (
                    f"\nShape: {df.shape[0]} rows × {df.shape[1]} columns\n"
                    f"Columns: {', '.join(df.columns)}\n\n"
                    f"Data Types:\n{df.dtypes.to_string()}\n\n"
                    f"Statistics:\n"
                    f"{df.describe().to_string() if len(df) > 0 else 'No numerical data'}\n\n"
                    f"Sample Data (first 10 rows):\n{df.head(10).to_string()}\n            "
                )
                return base_info + content
        except ImportError:
            pass

        if isinstance(self.result, dict):
            try:
                from datamodel.parsers.json import json_encoder  # type: ignore[import]
                content = (
                    f"\nKeys: {', '.join(str(k) for k in self.result.keys())}\n"
                    f"Content:\n{json_encoder(self.result)}\n            "
                )
            except ImportError:
                import json
                content = (
                    f"\nKeys: {', '.join(str(k) for k in self.result.keys())}\n"
                    f"Content:\n{json.dumps(self.result, default=str)}\n            "
                )
            return base_info + content

        if isinstance(self.result, list):
            try:
                from datamodel.parsers.json import json_encoder  # type: ignore[import]
                sample = json_encoder(self.result[:10]) if self.result else "[]"
            except ImportError:
                import json
                sample = json.dumps(self.result[:10], default=str) if self.result else "[]"
            item_types = set(type(item).__name__ for item in self.result[:100])
            content = (
                f"\nLength: {len(self.result)} items\n"
                f"Item Types: {', '.join(item_types)}\n"
                f"Sample Items:\n{sample}\n            "
            )
            return base_info + content

        content = f"\nContent:\n{str(self.result)}\n            "
        return base_info + content


# ---------------------------------------------------------------------------
# Helpers (copied/adapted from parrot.models.crew)
# ---------------------------------------------------------------------------

def determine_run_status(
    success_count: int,
    failure_count: int,
) -> Literal["completed", "partial", "failed"]:
    """Compute the overall status for a crew/flow execution.

    Args:
        success_count: Number of nodes that completed successfully.
        failure_count: Number of nodes that failed.

    Returns:
        - ``"completed"`` if no failures (including the ``(0, 0)`` case where
          no nodes ran — callers that consider an empty run an error should
          check ``success_count > 0`` themselves).
        - ``"failed"`` if no successes (all nodes failed).
        - ``"partial"`` if there are both successes and failures.
    """
    if failure_count == 0:
        return "completed"
    return "failed" if success_count == 0 else "partial"


# ---------------------------------------------------------------------------
# NodeExecutionInfo (replaces AgentExecutionInfo)
# ---------------------------------------------------------------------------


@dataclass
class NodeExecutionInfo:
    """Execution metadata for a single node in a flow/crew run.

    Primary fields use node-centric naming (``node_id``, ``node_name``).
    Backward-compatible aliases (``agent_id``, ``agent_name``) are provided
    as ``@property`` accessors so existing code continues to work.

    Mirrors all fields of ``parrot.models.crew.AgentExecutionInfo``.
    """

    node_id: str
    """Unique identifier for this node instance in the graph."""

    node_name: str
    """Human-readable name (usually the agent's name)."""

    provider: Optional[str] = None
    """LLM provider (e.g., ``'openai'``, ``'anthropic'``)."""

    model: Optional[str] = None
    """Model name (e.g., ``'gpt-4'``, ``'claude-3-opus'``)."""

    execution_time: float = 0.0
    """Wall-clock time for this node's execution (seconds)."""

    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    """List of tool-call records made during execution."""

    status: Literal["completed", "failed", "pending", "running"] = "pending"
    """Execution status."""

    error: Optional[str] = None
    """Error message if the node failed."""

    client: Optional[str] = None
    """Concrete client class name backing the node's agent."""

    usage: Optional[Dict[str, Any]] = None
    """Token usage and timing information from the LLM."""

    # ── Backward-compatible aliases ──────────────────────────────────────

    @property
    def agent_id(self) -> str:
        """Alias for ``node_id`` (backward compatibility with AgentExecutionInfo)."""
        return self.node_id

    @property
    def agent_name(self) -> str:
        """Alias for ``node_name`` (backward compatibility with AgentExecutionInfo)."""
        return self.node_name

    # ── Serialisation ────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain JSON-serialisable dictionary.

        Returns:
            Dictionary with all fields including backward-compat aliases.
        """
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            # Backward-compat aliases in output dict
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "provider": self.provider,
            "model": self.model,
            "execution_time": self.execution_time,
            "tool_calls": self.tool_calls,
            "status": self.status,
            "error": self.error,
            "client": self.client,
            "usage": self.usage,
        }


# ---------------------------------------------------------------------------
# FlowResult (replaces CrewResult)
# ---------------------------------------------------------------------------


@dataclass
class FlowResult:
    """Standardised result from a flow/crew execution.

    Provides a consistent interface across all execution modes (sequential,
    parallel, flow, FSM).

    Primary field is ``nodes`` (list of ``NodeExecutionInfo``).
    Backward-compatible property ``agents`` is an alias for ``nodes`` so
    existing code using ``CrewResult.agents`` continues to work.

    ``status`` uses ``FlowStatus`` enum; its string values match the literals
    previously used in ``CrewResult`` (``"completed"``, ``"partial"``,
    ``"failed"``).
    """

    output: Any
    """Final output from the workflow.

    **Shape contract (normative, FEAT-447 G4).** ``output`` is deliberately
    polymorphic, and its shape is decided by how many *leaf* nodes the run
    actually executed (see ``AgentsFlow._aggregate_result``):

    * **Exactly one executed leaf** -> the leaf's own **scalar** output (the
      node's answer, already unwrapped from its envelope). This is the common
      case: a linear or converging graph, and every ``AgentCrew`` run.
    * **A fan-out (two or more executed leaves)** -> a
      ``dict[node_id, Any]`` mapping each leaf's node_id to its scalar output.
    * **No executed leaf** (empty or fully-failed run) -> ``None``.

    Consumers that must not branch on shape should read
    :attr:`node_results` instead, which is *always* a
    ``dict[node_id, scalar]`` for every node, not just the leaves.

    This polymorphism is intentional and pinned by tests; it is not a bug to
    "fix", and there is no plural ``outputs`` field.
    """

    responses: Dict[str, Any] = field(default_factory=dict)
    """Mapping of node IDs → raw response objects."""

    summary: str = ""
    """Optional LLM-synthesised summary of results."""

    nodes: List[NodeExecutionInfo] = field(default_factory=list)
    """Execution metadata for each node (primary field, was ``agents`` in CrewResult)."""

    execution_log: List[Dict[str, Any]] = field(default_factory=list)
    """Detailed log of execution steps."""

    total_time: float = 0.0
    """Total wall-clock time for the run (seconds)."""

    status: FlowStatus = FlowStatus.COMPLETED
    """Overall execution status (uses FlowStatus enum)."""

    errors: Dict[str, str] = field(default_factory=dict)
    """Mapping of node IDs → error messages."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional metadata (mode, iterations, etc.)."""

    infographic: Optional["InfographicRenderResult"] = None
    """Multi-tab infographic artifact populated by
    ``AgentCrew._finalize_infographic`` when ``generate_infographic=True``
    (FEAT-308). ``None`` by default and on any render/synthesis failure.
    Kept as the LAST field to preserve existing positional/keyword
    construction and ``build_*`` helpers."""

    # ── __setattr__ override (preserve summary contract) ─────────────────

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "summary" and value is not None and not isinstance(value, str):
            value = str(value)
        super().__setattr__(name, value)

    # ── String representations ────────────────────────────────────────────

    def __str__(self) -> str:
        return str(self.output) if self.output is not None else ""

    def __repr__(self) -> str:
        return (
            f"FlowResult(status={self.status!r}, "
            f"nodes={len(self.nodes)}, "
            f"time={self.total_time:.2f}s)"
        )

    # ── Primary computed properties ───────────────────────────────────────

    @property
    def content(self) -> Optional[Any]:
        """Alias for ``output`` (OutputFormatter compatibility).

        Inherits :attr:`output`'s shape contract verbatim: a **scalar** when
        the run had a single executed leaf, a ``dict[node_id, Any]`` on a
        fan-out, ``None`` when nothing produced a result.
        """
        return self.output

    @property
    def final_result(self) -> Optional[Any]:
        """Compatibility alias for previous API.

        Inherits :attr:`output`'s shape contract verbatim: a **scalar** when
        the run had a single executed leaf, a ``dict[node_id, Any]`` on a
        fan-out, ``None`` when nothing produced a result.
        """
        return self.output

    @property
    def success(self) -> bool:
        """True when ``status == FlowStatus.COMPLETED``."""
        return self.status == FlowStatus.COMPLETED

    @property
    def node_results(self) -> Dict[str, Any]:
        """Map node IDs to their scalar output values.

        Handles both response shapes the two executors store in
        ``responses``, so callers get a scalar answer either way (FEAT-447 G4):

        * ``AgentCrew`` stores ``AgentResponse`` objects -> read ``.output``.
        * ``AgentsFlow`` stores the ``AgentNode.execute()`` envelope dict
          (``{"response", "output", "execution_time", "prompt"}``) -> read
          the ``"output"`` key. Before FEAT-447 these fell through to the
          ``else`` branch and callers received the whole envelope.

        Anything else is returned as-is, and ``None`` stays ``None``. This is
        a read-only projection: ``self.responses`` is never mutated.

        Returns:
            Mapping of node_id -> scalar output. Never an envelope dict.
        """
        result: Dict[str, Any] = {}
        for node_id, resp in self.responses.items():
            if resp is None:
                result[node_id] = None
            # The envelope check must be explicit: a dict has no `.output`
            # attribute, so it would otherwise fall through to `else` and
            # leak the whole mapping to the caller.
            elif isinstance(resp, dict) and "output" in resp:
                result[node_id] = resp["output"]
            elif hasattr(resp, "output"):
                result[node_id] = resp.output
            else:
                result[node_id] = resp
        return result

    @property
    def completed(self) -> List[str]:
        """Node IDs with ``status == 'completed'``."""
        completed_nodes: List[str] = []
        for node in self.nodes:
            if isinstance(node, NodeExecutionInfo):
                if node.status == "completed" and node.node_id:
                    completed_nodes.append(node.node_id)
            elif isinstance(node, dict):
                node_id = node.get("node_id") or node.get("agent_id")
                if node_id and node.get("status") == "completed":
                    completed_nodes.append(node_id)
        return completed_nodes

    @property
    def failed(self) -> List[str]:
        """Node IDs with ``status == 'failed'``."""
        failed_nodes: List[str] = []
        for node in self.nodes:
            if isinstance(node, NodeExecutionInfo):
                if node.status == "failed" and node.node_id:
                    failed_nodes.append(node.node_id)
            elif isinstance(node, dict):
                node_id = node.get("node_id") or node.get("agent_id")
                if node_id and node.get("status") == "failed":
                    failed_nodes.append(node_id)
        return failed_nodes

    @property
    def total_execution_time(self) -> float:
        """Compatibility alias for ``total_time``."""
        return self.total_time

    # ── Backward-compat aliases (CrewResult → FlowResult) ────────────────

    @property
    def agents(self) -> List[NodeExecutionInfo]:
        """Alias for ``nodes`` (backward compat with ``CrewResult.agents``)."""
        return self.nodes

    @property
    def agent_results(self) -> Dict[str, Any]:
        """Alias for ``node_results`` (backward compat with ``CrewResult.agent_results``)."""
        return self.node_results

    # ── Dictionary-style access ───────────────────────────────────────────

    def __getitem__(self, item: str) -> Any:
        """Dictionary-style access for backward compatibility.

        Args:
            item: Key name.

        Returns:
            Value for the given key.

        Raises:
            KeyError: If key is not recognised.
        """
        mapping = {
            "final_result": self.output,
            "output": self.output,
            "content": self.content,
            "node_results": self.node_results,
            "agent_results": self.agent_results,  # backward compat
            "nodes": [
                n.to_dict() if isinstance(n, NodeExecutionInfo) else n
                for n in self.nodes
            ],
            "agents": [  # backward compat
                n.to_dict() if isinstance(n, NodeExecutionInfo) else n
                for n in self.nodes
            ],
            "errors": self.errors,
            "execution_log": self.execution_log,
            "total_time": self.total_time,
            "total_execution_time": self.total_time,
            "success": self.success,
            "status": self.status,
            "responses": self.responses,
            "completed": self.completed,
            "failed": self.failed,
            "summary": self.summary,
        }
        if item in mapping:
            return mapping[item]
        raise KeyError(item)

    # ── Serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-serialisable dictionary.

        Returns:
            Dictionary containing all essential fields.
        """
        serialised_nodes = [
            n.to_dict() if isinstance(n, NodeExecutionInfo) else n
            for n in self.nodes
        ]

        serialised_responses: Dict[str, Any] = {}
        for node_id, resp in self.responses.items():
            if resp is None:
                serialised_responses[node_id] = None
            elif hasattr(resp, "output"):
                serialised_responses[node_id] = str(resp.output) if resp.output is not None else None
            else:
                serialised_responses[node_id] = str(resp)

        return {
            "output": (
                self.output
                if isinstance(self.output, (str, int, float, bool, type(None), list, dict))
                else str(self.output)
            ),
            "summary": self.summary,
            "status": self.status.value if isinstance(self.status, FlowStatus) else self.status,
            "total_time": self.total_time,
            "nodes": serialised_nodes,
            "agents": serialised_nodes,  # backward compat
            "responses": serialised_responses,
            "errors": self.errors,
            "execution_log": self.execution_log,
            "metadata": self.metadata,
            "infographic": (
                self.infographic.model_dump()
                if self.infographic is not None and hasattr(self.infographic, "model_dump")
                else self.infographic
            ),
        }


# ---------------------------------------------------------------------------
# build_node_metadata (adapted from build_agent_metadata)
# ---------------------------------------------------------------------------


def _serialise_tool_calls(tool_calls: Any) -> List[Any]:
    """Normalise tool-call structures for metadata output."""
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


def _normalise_status(
    status: str,
) -> Literal["completed", "failed", "pending", "running"]:
    """Map legacy status strings to NodeExecutionInfo status values."""
    mapping = {
        "success": "completed",
        "completed": "completed",
        "error": "failed",
        "failed": "failed",
        "pending": "pending",
        "running": "running",
    }
    return mapping.get(status.lower(), "pending")


#: Maximum number of envelope layers ``_unwrap_response`` will peel. Real
#: envelopes are one level deep (``AgentNode.execute()``); the cap only exists
#: so a self-referential or maliciously nested mapping cannot recurse forever.
_MAX_UNWRAP_DEPTH: int = 5


def _unwrap_response(response: Optional[Any], _depth: int = 0) -> Optional[Any]:
    """Normalise a node/agent return value to its metadata-bearing object.

    ``AgentNode.execute()`` returns an *envelope* dict
    (``{"response", "output", "execution_time", "prompt"}`` --
    ``core/node.py``) rather than the ``AgentResponse`` itself, while
    ``AgentCrew`` passes the ``AgentResponse`` directly. This helper collapses
    the former to the latter and leaves the latter untouched, so
    :func:`build_node_metadata` sees a single shape from both executors and
    the two cannot drift apart again (FEAT-447 G5).

    A mapping is treated as an envelope **only** when it carries a
    ``"response"`` key; a plain ``{"output": ...}`` dict is returned unchanged.
    The function is intentionally total: it never raises, and on anything
    unexpected it returns its input unchanged so ``build_node_metadata``
    degrades exactly as it did before FEAT-447.

    Args:
        response: Any node/agent return value (envelope dict,
            ``AgentResponse``, ``AIMessage``, ``str``, ``None``, or an
            arbitrary user object).
        _depth: Internal recursion guard; callers should not pass it.

    Returns:
        The metadata-bearing object, or ``response`` unchanged.
    """
    if _depth >= _MAX_UNWRAP_DEPTH:
        return response
    try:
        if isinstance(response, dict) and "response" in response:
            return _unwrap_response(response["response"], _depth + 1)
    except Exception:  # noqa: BLE001 — defensive: arbitrary user objects
        return response
    return response


def build_node_metadata(
    node_id: str,
    agent: Optional[Any],
    response: Optional[Any],
    output: Optional[Any],
    execution_time: float,
    status: str,
    error: Optional[str] = None,
) -> NodeExecutionInfo:
    """Create execution metadata for a node run.

    Mirrors ``build_agent_metadata()`` from ``parrot.models.crew`` but
    returns a ``NodeExecutionInfo`` instead of ``AgentExecutionInfo``.

    ``response`` is first normalised through :func:`_unwrap_response`, so both
    the bare ``AgentResponse`` an ``AgentCrew`` passes and the envelope dict an
    ``AgentNode`` returns yield the same metadata (FEAT-447 G1/G5).

    Args:
        node_id: Unique identifier for this node instance.
        agent: The agent object (used to extract name/provider/model/client).
        response: Raw response object from the agent, or the envelope dict
            returned by ``AgentNode.execute()``.
        output: Extracted output value. Passed through untouched -- it is
            *not* unwrapped, so ``NodeExecutionInfo`` semantics are unchanged.
        execution_time: Wall-clock time for the execution.
        status: Status string (normalised to allowed literals).
        error: Error message if execution failed.

    Returns:
        Populated ``NodeExecutionInfo`` instance.
    """
    # FEAT-447: collapse an AgentNode envelope to its AgentResponse *before*
    # the isinstance ladder below; crew's bare AgentResponse passes through
    # unchanged, so crew behaviour is bit-identical.
    response = _unwrap_response(response)

    model: Optional[str] = None
    provider: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    tool_calls: List[Any] = []

    # Extract metadata from structured response types
    try:
        from parrot.models.responses import AIMessage, AgentResponse

        if isinstance(response, AgentResponse):
            ai_message = (
                response.response if isinstance(response.response, AIMessage) else None
            )
            model = getattr(response, "model", None) or getattr(ai_message, "model", None)
            provider = getattr(response, "provider", None) or getattr(ai_message, "provider", None)
            raw_tc = (
                getattr(response, "tool_calls", None)
                or getattr(ai_message, "tool_calls", None)
                or []
            )
            tool_calls = _serialise_tool_calls(raw_tc)
            if output is None:
                output = response.output or getattr(ai_message, "output", None)
            usage_obj = getattr(ai_message, "usage", None) or getattr(response, "usage", None)
            if usage_obj:
                usage = usage_obj.model_dump() if hasattr(usage_obj, "model_dump") else usage_obj
        elif isinstance(response, AIMessage):
            model = getattr(response, "model", None)
            provider = getattr(response, "provider", None)
            tool_calls = _serialise_tool_calls(getattr(response, "tool_calls", None))
            if output is None:
                output = getattr(response, "output", None) or getattr(response, "content", None)
            usage_obj = getattr(response, "usage", None)
            if usage_obj:
                usage = usage_obj.model_dump() if hasattr(usage_obj, "model_dump") else usage_obj
        elif response is not None:
            model = getattr(response, "model", None)
            provider = getattr(response, "provider", None)
            tool_calls = _serialise_tool_calls(getattr(response, "tool_calls", None))
    except ImportError:
        # If response types are unavailable, use whatever attrs exist
        if response is not None:
            model = getattr(response, "model", None)
            provider = getattr(response, "provider", None)

    # Fall back to agent attributes
    client: Optional[str] = None
    if agent is not None:
        provider = provider or getattr(agent, "use_llm", None) or getattr(agent, "provider", None)
        if client_obj := getattr(agent, "llm", None) or getattr(agent, "_llm", None):
            model = model or getattr(client_obj, "model", None)
            # FEAT-447: revive the declared-but-never-assigned `client` field.
            # `agent.llm` is normally an AbstractClient instance; before
            # `configure()` it can still hold the raw config (a str/dict), and
            # a bare type name there would be noise rather than information.
            if not isinstance(client_obj, (str, bytes, dict, list, tuple)):
                client = type(client_obj).__name__

    node_name = getattr(agent, "name", node_id) if agent is not None else node_id

    return NodeExecutionInfo(
        node_id=node_id,
        node_name=node_name,
        provider=provider,
        model=model,
        execution_time=execution_time,
        tool_calls=tool_calls,
        status=_normalise_status(status),
        error=error,
        client=client,
        usage=usage,
    )
