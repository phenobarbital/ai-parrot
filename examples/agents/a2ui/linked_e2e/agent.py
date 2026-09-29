"""EpsonLinkedAgent — FEAT-611 M9 example agent: QuerysourceToolkit + Epson dashboard TOOL + publish_surface."""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

from parrot.auth.context import _pctx_var
from parrot.auth.permission import build_principal_context
from parrot.bots import Agent
from parrot.bots.mixins.infographic_authoring import InfographicAuthoringMixin
from parrot.tools import tool
from parrot_tools.querysource.toolkit import QuerysourceToolkit
from parrot_tools.ui_surfaces import PublishSurfaceTool

HERE = Path(__file__).resolve().parent
AGENT_NAME = "epson_linked"
logger = logging.getLogger("examples.a2ui.linked_e2e.agent")


def _load_dashboard_tool():
    """Load the sibling dashboard_tool.py by path (examples/ is not a package)."""
    spec = importlib.util.spec_from_file_location("linked_e2e_dashboard_tool", HERE / "dashboard_tool.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EpsonLinkedAgent(InfographicAuthoringMixin, Agent):
    """Emits Epson linked surfaces (qs_build_linked_surface / build_epson_activity_dashboard) and publishes them."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("name", AGENT_NAME)
        kwargs.setdefault("agent_id", AGENT_NAME)
        super().__init__(**kwargs)

    async def ask(self, *args: Any, **kwargs: Any) -> Any:
        """Run ``ask`` with the caller's PermissionContext bound to ``_pctx_var`` for the tool loop.

        AgentTalk passes the authenticated session's ``user_id`` (never an LLM value) but no
        ``permission_context``; the dashboard TOOL needs a pctx to pass the data-plane guard. The
        ContextVar is task-local, so concurrent requests never share it. No identity → no pctx →
        the TOOL fails closed (AuthorizationRequired) when a guard is configured.
        """
        pctx = kwargs.get("permission_context") or _pctx_var.get()
        user_id = kwargs.get("user_id")
        if pctx is None and user_id:
            pctx = build_principal_context(str(user_id), channel="agent_chat")
        token = _pctx_var.set(pctx)
        try:
            return await super().ask(*args, **kwargs)
        finally:
            _pctx_var.reset(token)

    def agent_tools(self) -> list:
        """QuerysourceToolkit + dashboard TOOL closure + PublishSurfaceTool(bot=self)."""
        dashboard = _load_dashboard_tool()
        agent = self

        @tool(name="build_epson_activity_dashboard")
        async def build_epson_activity_dashboard(
            firstdate: str = "FDOM",
            lastdate: str = "TODAY",
            programs: list[str] | None = None,
            snapshot: bool = True,
        ) -> dict:
            """Compose the Epson activity dashboard (KPIs, visits-by-day bar, attainment table, date + program filters)."""
            if isinstance(programs, str):  # the generated schema types list[str] | None as a string
                programs = [p.strip() for p in programs.split(",") if p.strip()] or None
            pctx = _pctx_var.get()  # bound by ask(); None → the TOOL fails closed when a guard exists (§9 S4)
            guard = getattr(agent, "_dataplane_guard", None)  # read lazily: BotManager injects it at startup
            if guard is not None and pctx is None:
                logger.warning("build_epson_activity_dashboard: guard configured but no caller pctx — failing closed")
            return await dashboard.build_epson_activity_dashboard(
                firstdate, lastdate, programs, snapshot, pctx=pctx, guard=guard
            )

        # ToolManager.register_tools does not accept an AbstractToolkit instance ("Unsupported tool type",
        # tools/manager.py:985-1014) — register the toolkit's generated tools instead.
        return [
            *super().agent_tools(),
            *QuerysourceToolkit().get_tools(),
            build_epson_activity_dashboard,
            PublishSurfaceTool(bot=self),
        ]
