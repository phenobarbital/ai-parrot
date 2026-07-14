"""CrewExecutionDocument — deterministic, LLM-free consolidated execution record.

Assembles every agent's result + the final crew output + the (already
generated) synthesis summary into one consistent document, buildable from
in-process state (``from_memory``) or reconstructed from the storage
backend (``from_storage``). Both ``to_dict()`` and ``to_markdown()`` make
ZERO LLM calls — pure, deterministic data transformation.

This module MUST NOT import from ``parrot.clients`` or any LLM SDK.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..result import FlowResult
from ..types import FlowStatus
from .backends import ResultStorage
from .memory import ExecutionMemory

_JSON_SAFE_PRIMITIVES = (str, int, float, bool, type(None), list, dict)


def _json_safe(value: Any) -> Any:
    """Coerce *value* into a JSON-safe representation.

    Mirrors the exact coercion used by ``FlowResult.to_dict()`` for its
    ``output`` field, so ``CrewExecutionDocument`` stays a true superset.

    Args:
        value: Arbitrary value (typically ``FlowResult.output``).

    Returns:
        The value unchanged when it is already JSON-safe, else ``str(value)``.
    """
    return value if isinstance(value, _JSON_SAFE_PRIMITIVES) else str(value)


def _fence_for(text: str) -> str:
    """Pick a Markdown fence that does not collide with *text*'s content.

    Args:
        text: Content that will be wrapped in a fenced code block.

    Returns:
        Triple backticks, or triple tildes when the text already contains
        triple backticks (so the document structure is never broken).
    """
    return "~~~" if "```" in text else "```"


@dataclass
class CrewExecutionDocument:
    """Deterministic, LLM-free consolidated record of one crew execution.

    Superset of ``FlowResult.to_dict()``: every key produced by that method
    is also present in ``CrewExecutionDocument.to_dict()``, plus
    ``execution_id``, ``agent_results``, ``execution_order``, ``crew_name``,
    and ``method``.
    """

    execution_id: str
    crew_name: str
    method: str
    status: str
    output: Any
    summary: str
    agent_results: List[Dict[str, Any]]
    execution_order: List[str]
    errors: Dict[str, str]
    total_time: float
    timestamp: float
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ── Serialisation ────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dictionary.

        Returns:
            Dictionary that is a superset of ``FlowResult.to_dict()``'s
            keys (``output``, ``summary``, ``status``, ``total_time``,
            ``nodes``, ``agents``, ``responses``, ``errors``,
            ``execution_log``, ``metadata``), plus ``execution_id``,
            ``agent_results``, ``execution_order``, ``crew_name``, ``method``.
        """
        extra = self.metadata.get("_flow_extra", {}) if isinstance(self.metadata, dict) else {}
        metadata_out = {
            k: v for k, v in self.metadata.items() if k != "_flow_extra"
        }
        return {
            "execution_id": self.execution_id,
            "crew_name": self.crew_name,
            "method": self.method,
            "output": _json_safe(self.output),
            "summary": self.summary,
            "status": self.status,
            "total_time": self.total_time,
            "agent_results": self.agent_results,
            "execution_order": self.execution_order,
            "errors": self.errors,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "nodes": extra.get("nodes", []),
            "agents": extra.get("agents", []),
            "responses": extra.get("responses", {}),
            "execution_log": extra.get("execution_log", []),
            "metadata": metadata_out,
        }

    def to_markdown(self) -> str:
        """Render a complete, deterministic Markdown report.

        Pure string templating — no LLM calls, no network access. Calling
        this method repeatedly on the same instance always yields an
        identical string.

        Returns:
            Markdown document: title + metadata table, one section per
            agent (in ``execution_order``), the final result, the summary,
            and an errors section when ``errors`` is non-empty.
        """
        ts_iso = datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat()
        sections: List[str] = [
            f"# Crew Execution Report — {self.crew_name}",
            (
                "| Field | Value |\n"
                "|---|---|\n"
                f"| Execution ID | {self.execution_id} |\n"
                f"| Method | {self.method} |\n"
                f"| Status | {self.status} |\n"
                f"| Total Time | {self.total_time:.3f}s |\n"
                f"| Timestamp | {ts_iso} |"
            ),
        ]

        for agent in self.agent_results:
            node_name = agent.get("node_name") or agent.get("node_id", "?")
            task = agent.get("task", "")
            result_text = str(agent.get("result", ""))
            exec_time = agent.get("execution_time", 0.0)
            fence = _fence_for(result_text)
            sections.append(
                f"## Agent: {node_name}\n\n"
                f"**Task:** {task}\n\n"
                f"**Execution Time:** {exec_time}s\n\n"
                f"**Result:**\n{fence}\n{result_text}\n{fence}"
            )

        output_text = str(self.output)
        output_fence = _fence_for(output_text)
        sections.append(
            f"## Final Result\n\n{output_fence}\n{output_text}\n{output_fence}"
        )

        summary_text = self.summary if self.summary else "_(no summary generated)_"
        sections.append(f"## Summary\n\n{summary_text}")

        if self.errors:
            err_lines = "\n".join(f"- **{k}**: {v}" for k, v in self.errors.items())
            sections.append(f"## Errors\n\n{err_lines}")

        return "\n\n".join(sections)

    # ── Construction ─────────────────────────────────────────────────────

    @classmethod
    def from_memory(
        cls,
        *,
        execution_id: str,
        crew_name: str,
        method: str,
        memory: "ExecutionMemory",
        result: "FlowResult",
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> "CrewExecutionDocument":
        """Assemble the document from in-process state (LLM-free).

        Args:
            execution_id: Crew-level execution id (uuid4, generated by the
                caller at the start of the run).
            crew_name: Name of the crew that ran.
            method: Execution method name (e.g. ``"run_sequential"``).
            memory: The ``ExecutionMemory`` populated during the run.
            result: The ``FlowResult`` produced by the run.
            user_id: Optional user identifier.
            session_id: Optional session identifier.

        Returns:
            A fully assembled ``CrewExecutionDocument``.
        """
        remaining = [
            nid for nid in memory.results if nid not in memory.execution_order
        ]
        remaining.sort(key=lambda nid: memory.results[nid].timestamp)
        all_ids = list(memory.execution_order) + remaining
        agent_results = [
            memory.results[nid].to_dict() for nid in all_ids if nid in memory.results
        ]

        status = (
            result.status.value
            if isinstance(result.status, FlowStatus)
            else result.status
        )
        flow_dict = result.to_dict()
        metadata = dict(result.metadata)
        metadata["_flow_extra"] = {
            "nodes": flow_dict.get("nodes", []),
            "agents": flow_dict.get("agents", []),
            "responses": flow_dict.get("responses", {}),
            "execution_log": flow_dict.get("execution_log", []),
        }

        return cls(
            execution_id=execution_id,
            crew_name=crew_name,
            method=method,
            status=status,
            output=result.output,
            summary=result.summary,
            agent_results=agent_results,
            execution_order=list(memory.execution_order),
            errors=dict(result.errors),
            total_time=result.total_time,
            timestamp=time.time(),
            user_id=user_id,
            session_id=session_id,
            metadata=metadata,
        )

    @classmethod
    async def from_storage(
        cls,
        storage: "ResultStorage",
        execution_id: str,
        *,
        crew_collection: str = "crew_executions",
        agent_collection: str = "crew_agent_results",
    ) -> Optional["CrewExecutionDocument"]:
        """Reconstruct the document from the storage backend.

        The consolidated ``crew_executions`` document (when present) is the
        primary source for ``agent_results``; standalone
        ``crew_agent_results`` documents fill in any agent missing from the
        consolidated doc (e.g. a crash-interrupted run that never wrote the
        consolidated doc). Agents are ordered by the consolidated doc's
        ``execution_order``, falling back to per-agent doc timestamps for
        stragglers.

        Args:
            storage: The ``ResultStorage`` backend to read from.
            execution_id: Crew-level execution id to reconstruct.
            crew_collection: Collection holding the consolidated document.
            agent_collection: Collection holding standalone per-agent docs.

        Returns:
            The reconstructed document, or ``None`` when nothing is found
            in either collection.
        """
        try:
            crew_docs = await storage.fetch(crew_collection, execution_id)
        except NotImplementedError:
            crew_docs = []
        try:
            agent_docs = await storage.fetch(agent_collection, execution_id)
        except NotImplementedError:
            agent_docs = []

        if not crew_docs and not agent_docs:
            return None

        # _save_result() nests the persisted document's own to_dict() under
        # the outer "result" key (persistence.py:96-98) — unwrap it, falling
        # back to the raw fetched doc for storages that saved it flat.
        crew_raw = crew_docs[0] if crew_docs else {}
        crew_doc = crew_raw.get("result", crew_raw) if isinstance(crew_raw, dict) else {}

        embedded: Dict[str, Dict[str, Any]] = {
            entry.get("node_id"): entry
            for entry in crew_doc.get("agent_results", [])
            if isinstance(entry, dict) and entry.get("node_id")
        }

        # Fill gaps from standalone per-agent docs (_save_agent_result()
        # nests NodeResult.to_dict() under "result" too).
        for doc in agent_docs:
            node_id = doc.get("node_id")
            if not node_id or node_id in embedded:
                continue
            payload = doc.get("result")
            if isinstance(payload, dict):
                payload = dict(payload)
                payload.setdefault("node_id", node_id)
            else:
                payload = {"node_id": node_id, "result": payload}
            embedded[node_id] = payload

        execution_order = crew_doc.get("execution_order", [])
        ordered_ids = [nid for nid in execution_order if nid in embedded]
        stragglers = [nid for nid in embedded if nid not in ordered_ids]
        stragglers.sort(key=lambda nid: embedded[nid].get("timestamp") or "")
        all_ids = ordered_ids + stragglers
        agent_results = [embedded[nid] for nid in all_ids]

        if crew_doc:
            # to_dict() flattens the "_flow_extra" metadata bucket (nodes/
            # agents/responses/execution_log) into top-level keys (see
            # to_dict() above) — re-nest them so a round-tripped to_dict()
            # reproduces the same superset shape as from_memory().
            metadata = dict(crew_doc.get("metadata", {}))
            metadata["_flow_extra"] = {
                "nodes": crew_doc.get("nodes", []),
                "agents": crew_doc.get("agents", []),
                "responses": crew_doc.get("responses", {}),
                "execution_log": crew_doc.get("execution_log", []),
            }
            return cls(
                execution_id=execution_id,
                crew_name=crew_doc.get("crew_name", "unknown"),
                method=crew_doc.get("method", "unknown"),
                status=crew_doc.get("status", "unknown"),
                output=crew_doc.get("output"),
                summary=crew_doc.get("summary", ""),
                agent_results=agent_results,
                execution_order=execution_order,
                errors=crew_doc.get("errors", {}),
                total_time=crew_doc.get("total_time", 0.0),
                timestamp=crew_doc.get("timestamp", time.time()),
                user_id=crew_doc.get("user_id"),
                session_id=crew_doc.get("session_id"),
                metadata=metadata,
            )

        # Crash-interrupted run: no consolidated doc — build a minimal
        # document purely from the standalone per-agent docs.
        first_agent = agent_docs[0] if agent_docs else {}
        return cls(
            execution_id=execution_id,
            crew_name=first_agent.get("crew_name", "unknown"),
            method=first_agent.get("method", "unknown"),
            status="partial",
            output=None,
            summary="",
            agent_results=agent_results,
            execution_order=all_ids,
            errors={},
            total_time=0.0,
            timestamp=time.time(),
            user_id=None,
            session_id=None,
            metadata={},
        )
