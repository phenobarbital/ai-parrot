"""Autonomous Data-Analyst Agent — demo agent definition.

This module defines :class:`AutonomousAnalystAgent`, a ``BasicAgent`` subclass
that showcases the AI-Parrot *autonomous harness* end-to-end:

* **Working Memory Toolkit** — the agent accumulates intermediate DataFrames /
  results across turns (and across heartbeat ticks) via the ``wm_*`` tools,
  instead of re-deriving everything each call.
* **Spawn sub-agents** — the agent can delegate a bounded analysis to an
  ephemeral sub-agent (created → run → discarded) through ``spawn_sub_agent``.
* **Grants** — a mutating "publish report" capability is marked
  ``requires_grant`` so the harness gates it behind a Telegram approval window.

The agent is intentionally tool-rich but model-light: it relies on Gemini
(the AI-Parrot default) for reasoning and on deterministic toolkits for the
heavy lifting, which keeps the demo cheap and reproducible.

See ``service.py`` for how this agent is wired into the autonomous harness
(heartbeat + ledger + orchestrator + operator commands) and ``README.md`` for
deployment.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, List, Optional

from parrot.bots.agent import BasicAgent
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.working_memory import WorkingMemoryToolkit

if TYPE_CHECKING:  # pragma: no cover - typing only
    from parrot.manager import BotManager

logger = logging.getLogger("demo.autonomous_analyst")

# Tools the parent agent is willing to lend to an ephemeral sub-agent.
# The SpawnSubAgentTool intersects the LLM-requested subset with this allowlist
# (defence in depth — a sub-agent can never exceed the parent's grant).
SUBAGENT_ALLOWED_TOOLS: List[str] = [
    "wm_get_result",
    "wm_search_stored",
    "wm_compute_and_store",
    "python_repl",
]

ANALYST_SYSTEM_PROMPT = """\
You are an autonomous Data Analyst running as an always-on service.

Operating principles:
- Use the Working Memory tools (wm_*) to STORE intermediate results
  (DataFrames, computed aggregates, findings) under stable keys, and to
  RECALL them on later turns instead of recomputing. Treat working memory as
  your scratchpad that survives across heartbeat ticks.
- For a bounded, self-contained sub-analysis, delegate to an ephemeral
  sub-agent with `spawn_sub_agent` (it is created, runs one task, and is
  destroyed). Pass it only the tools it needs.
- "Publishing" a report is a sensitive action: it requires an explicit
  human approval (a grant). Call `publish_report` only when you have a final
  result worth sending; the harness will ask the operator to approve it.
- Be concise. When you finish a heartbeat cycle with nothing actionable,
  say so briefly.
"""


class PublishReportTool(AbstractTool):
    """A *mutating* capability that 'publishes' a finalized analysis.

    In the demo this just records the report into working memory and returns a
    confirmation, but it is flagged ``requires_grant`` so FEAT-211's
    ``GrantGuard`` intercepts it in ``ToolManager.execute_tool`` and asks the
    operator to approve (opening a bounded automation window). It stands in for
    any real side-effecting action (post to a dashboard, email a stakeholder,
    write to a warehouse table, etc.).
    """

    name: str = "publish_report"
    description: str = (
        "Publish a finalized analysis report to stakeholders. "
        "This is a sensitive action and requires human approval."
    )

    def __init__(self, **kwargs: Any) -> None:
        # routing_meta["requires_grant"] is what the GrantGuard keys on. The
        # grant_scope groups related sensitive actions under one approval.
        super().__init__(
            routing_meta={
                "requires_grant": True,
                "grant_scope": "analyst:publish",
            },
            **kwargs,
        )

    async def _execute(self, *, title: str, body: str, **_: Any) -> ToolResult:
        logger.info("publish_report: PUBLISHING report %r (%d chars)", title, len(body))
        return ToolResult(
            status="success",
            result={"published": True, "title": title, "chars": len(body)},
            metadata={"tool_name": self.name},
        )


class AutonomousAnalystAgent(BasicAgent):
    """A data-analyst agent wired for the autonomous harness.

    Args:
        bot_manager: The server ``BotManager``. Required so the agent can spawn
            ephemeral sub-agents through its lifecycle (FEAT-208). When omitted
            (e.g. unit tests) the spawn tool is simply not attached.
        chatbot_id: Stable id used as the key in ``BotManager._bots`` and in the
            Telegram config (``chatbot_id``) so the integration can resolve this
            exact instance.
    """

    def __init__(
        self,
        *,
        bot_manager: Optional["BotManager"] = None,
        chatbot_id: str = "autonomous-analyst",
        **kwargs: Any,
    ) -> None:
        self._bot_manager = bot_manager
        super().__init__(
            name="AutonomousAnalyst",
            agent_id="autonomous_analyst",
            chatbot_id=chatbot_id,
            use_llm="google",  # Gemini — the AI-Parrot default
            system_prompt=ANALYST_SYSTEM_PROMPT,
            use_tools=True,
            **kwargs,
        )

    def agent_tools(self) -> List[AbstractTool]:
        """Attach the demo's toolkits/tools.

        Invoked by ``BasicAgent.__init__`` (agent.py:132). ``answer_memory`` is
        auto-injected into the WorkingMemoryToolkit by the base class.
        """
        tools: List[AbstractTool] = []

        # 1. Working Memory Toolkit — intermediate result store (wm_* tools).
        tools.extend(
            WorkingMemoryToolkit(session_id=self.agent_id).get_tools()
        )

        # 2. The sensitive, grant-gated publish action.
        tools.append(PublishReportTool())

        # 3. Spawn-ephemeral-sub-agent tool (only when a BotManager is available).
        if self._bot_manager is not None:
            # Imported lazily: SpawnSubAgentTool lives in core but needs the
            # server's BotManager to drive the ephemeral lifecycle.
            from parrot.tools.spawn import SpawnSubAgentTool

            tools.append(
                SpawnSubAgentTool(
                    bot_manager=self._bot_manager,
                    owner_id=f"agent:{self.agent_id}",
                    allowed_tools=SUBAGENT_ALLOWED_TOOLS,
                )
            )
        else:
            logger.warning(
                "AutonomousAnalystAgent: no BotManager provided — "
                "spawn_sub_agent tool will NOT be attached."
            )

        return tools
