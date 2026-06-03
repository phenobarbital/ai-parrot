"""AgentFactory helpers for the eval harness benchmarks.

FEAT-217 — TASK-1428.

These factories construct mock agents that respond to benchmark task
queries by directly mutating the ``DictStateBackend`` through the toolkit
binding layer.  All factories are hermetic: no real database, no real Jira,
no real LLM.
"""
from __future__ import annotations

import logging
from typing import Any

from parrot.eval.sandbox.state import InMemoryStateSandbox

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockDB_Bot:
    """Minimal mock agent for DB CRUD benchmark.

    When ``ask()`` is called, applies a deterministic mutation to the
    sandbox's backend based on the task query.  This stands in for a real
    ``DatabaseAgent`` in hermetic CI tests.
    """

    def __init__(self, sandbox: "InMemoryStateSandbox") -> None:
        self._sandbox = sandbox

    async def ask(self, question: str) -> Any:
        """Respond by mutating the backend according to the task query.

        Args:
            question: The task query string.

        Returns:
            A mock AIMessage with ``content``.
        """
        backend = self._sandbox._backend

        q = question.lower()

        if "insert" in q or "add" in q or "create" in q:
            # Parse: "insert an item with id 'X' and name 'Y'"
            import re
            eid_m = re.search(r"['\"]([A-Za-z0-9_-]+)['\"]", question)
            name_m = re.search(r"name ['\"]([^'\"]+)['\"]", question, re.IGNORECASE)
            eid = eid_m.group(1) if eid_m else "I-unknown"
            name = name_m.group(1) if name_m else "unknown"
            try:
                await backend.create("items", eid, {"name": name})
            except KeyError:
                await backend.update("items", eid, {"name": name})

        elif "update" in q or "set" in q or "change" in q:
            # Parse: "update item 'X' to set status to 'Y'"
            import re
            eid_m = re.search(r"item ['\"]([A-Za-z0-9_-]+)['\"]", question, re.IGNORECASE)
            status_m = re.search(r"status to ['\"]([^'\"]+)['\"]", question, re.IGNORECASE)
            if eid_m and status_m:
                eid = eid_m.group(1)
                status = status_m.group(1)
                try:
                    await backend.update("items", eid, {"status": status})
                except KeyError:
                    await backend.upsert("items", eid, {"status": status})

        elif "delete" in q or "remove" in q:
            # Parse: "delete item 'X'"
            import re
            eid_m = re.search(r"['\"]([A-Za-z0-9_-]+)['\"]", question)
            if eid_m:
                eid = eid_m.group(1)
                await backend.delete("items", eid)

        return type("AIMessage", (), {"content": f"Done: {question[:50]}"})()

    async def conversation(self, question: str, **kwargs: Any) -> Any:
        """Alias to ask() for conversational rollouts.

        Args:
            question: User message.
            kwargs: Ignored.

        Returns:
            Mock AIMessage.
        """
        return await self.ask(question)


class _MockJira_Bot:
    """Minimal mock agent for Jira triage benchmark."""

    def __init__(self, sandbox: "InMemoryStateSandbox") -> None:
        self._sandbox = sandbox

    async def ask(self, question: str) -> Any:
        """Perform Jira operations by mutating the backend.

        Args:
            question: Task query.

        Returns:
            Mock AIMessage.
        """
        backend = self._sandbox._backend
        q = question.lower()

        if "assign" in q:
            import re
            # "assign all unassigned bugs in PROJ to 'oncall'"
            assignee_m = re.search(r"to ['\"]([^'\"]+)['\"]", question, re.IGNORECASE)
            assignee = assignee_m.group(1) if assignee_m else "oncall"
            issues = await backend.list("issues")
            for issue in issues:
                if issue.get("assignee") is None:
                    await backend.update("issues", issue["_id"], {"assignee": assignee})

        elif "transition" in q or "done" in q or "close" in q:
            import re
            eid_m = re.search(r"([A-Z]+-\d+)", question)
            if eid_m:
                eid = eid_m.group(1)
                try:
                    await backend.update("issues", eid, {"status": "done"})
                except KeyError:
                    pass

        return type("AIMessage", (), {"content": f"Done: {question[:50]}"})()

    async def conversation(self, question: str, **kwargs: Any) -> Any:
        """Alias to ask().

        Args:
            question: User message.
            kwargs: Ignored.

        Returns:
            Mock AIMessage.
        """
        return await self.ask(question)


# ---------------------------------------------------------------------------
# Public AgentFactory functions
# ---------------------------------------------------------------------------


async def make_db_agent(sandbox: Any) -> Any:
    """Build a mock DB agent bound to *sandbox*.

    Args:
        sandbox: ``InMemoryStateSandbox`` instance.

    Returns:
        A ``_MockDB_Bot`` instance ready for ``SingleTurnRollout``.
    """
    # In a real integration, sandbox.bind(real_postgres_toolkit) would be called.
    # For hermetic benchmarks, the mock bot directly mutates the backend.
    return _MockDB_Bot(sandbox)


async def make_jira_agent(sandbox: Any) -> Any:
    """Build a mock Jira agent bound to *sandbox*.

    Args:
        sandbox: ``InMemoryStateSandbox`` instance.

    Returns:
        A ``_MockJira_Bot`` instance ready for ``ConversationalRollout``.
    """
    return _MockJira_Bot(sandbox)
