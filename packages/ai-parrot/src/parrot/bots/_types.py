"""Shared structural types for the ``parrot.bots`` package.

This module is intentionally dependency-free (stdlib ``typing`` only) so it
can be imported by any agent without pulling in heavy machinery, and — most
importantly — without ever importing server-side packages
(``parrot.autonomous`` / ``ai-parrot-server``). Core must not import server.
"""
from typing import Any, Optional, Protocol


class AgentDispatcher(Protocol):
    """Duck-typed async callable that dispatches a named agent.

    Any object exposing a matching ``__call__`` shape satisfies this
    protocol structurally — no inheritance coupling is required.
    ``AutonomousOrchestrator.execute_agent`` (``ai-parrot-server``) already
    satisfies this shape, so it can be wired in via
    ``jira_specialist.set_agent_dispatcher(orchestrator.execute_agent)``
    without core ever importing the server package.
    """

    async def __call__(
        self,
        agent_name: str,
        task: str,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Any: ...
