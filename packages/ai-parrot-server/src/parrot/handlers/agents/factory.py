"""HTTP handler for the AgentFactoryOrchestrator.

Endpoint shape:

    POST /api/v1/agents/factory
        body: {description, clone_from?, hints?, category?, auto_approve?}
        returns: FactoryResult-as-JSON

The handler picks up the ``HumanInteractionManager`` from
``request.app["human_manager"]``. If absent, a stub manager that
auto-approves every gate is used — handy for scripted / CI runs.

For real interactive flows, the host application must register the manager
beforehand (typically wiring a ``WebHumanChannel`` or telegram channel).

IMPORTANT: auto_approve=true is restricted to authenticated users with
factory:admin role to prevent registry tampering via unvalidated API calls.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from aiohttp import web
from navigator.responses import JSONResponse
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated
from navigator_session import get_session
from navigator_auth.conf import AUTH_SESSION_OBJECT

from parrot.bots.factory import (
    AgentFactoryOrchestrator,
    FactoryRequest,
    FactoryResult,
)
from parrot.human.channels import HumanChannel
from parrot.human.manager import HumanInteractionManager
from parrot.human.models import (
    HumanInteraction,
    HumanResponse,
    InteractionType,
)


logger = logging.getLogger("Parrot.Handlers.AgentFactory")


class _AutoApproveChannel(HumanChannel):
    """Channel that resolves every interaction inline with ``value="confirm"``.

    Used for headless / scripted factory runs (CI, tests, API clients that
    pre-approved through their own UI). Not meant for production HITL.
    """

    channel_type = "auto_approve"

    def __init__(self) -> None:
        self._on_response = None
        self._on_cancel = None

    async def register_response_handler(self, callback) -> None:
        self._on_response = callback

    async def register_cancel_handler(self, callback) -> None:
        self._on_cancel = callback

    async def send_interaction(
        self,
        interaction: HumanInteraction,
        recipient: str,
    ) -> bool:
        if self._on_response is None:
            return False
        await self._on_response(
            HumanResponse(
                interaction_id=interaction.interaction_id,
                respondent=recipient,
                response_type=interaction.interaction_type,
                value=(
                    True
                    if interaction.interaction_type == InteractionType.APPROVAL
                    else "confirm"
                ),
            )
        )
        return True

    async def send_notification(self, recipient: str, message: str) -> None:  # noqa: ARG002
        return None

    async def cancel_interaction(
        self,
        interaction_id: str,
        recipient: str,
    ) -> None:  # noqa: ARG002
        return None


def build_auto_approve_manager() -> HumanInteractionManager:
    """Construct a manager whose only channel auto-approves every gate."""
    channel = _AutoApproveChannel()
    manager = HumanInteractionManager(channels={"auto_approve": channel})
    return manager


@is_authenticated()
class AgentFactoryHandler(BaseView):
    """POST /api/v1/agents/factory — create a new agent via the factory."""

    async def post(self) -> web.Response:
        request = self.request
        try:
            payload: Dict[str, Any] = await request.json()
        except Exception:
            payload = {}

        if "description" not in payload:
            return JSONResponse(
                {"status": "error", "message": "description is required"},
                status=400,
            )

        try:
            factory_request = FactoryRequest(**{
                k: v
                for k, v in payload.items()
                if k in {"description", "clone_from", "hints"}
            })
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {"status": "error", "message": f"invalid request: {exc}"},
                status=400,
            )

        category = payload.get("category", "general")
        auto_approve = bool(payload.get("auto_approve", False))
        use_llm = payload.get("use_llm", "google")
        llm = payload.get("llm")

        if auto_approve:
            # Verify caller has factory:admin role to prevent registry tampering
            session = get_session(request, AUTH_SESSION_OBJECT)
            user_roles = getattr(session, "roles", []) if session else []
            if "factory:admin" not in user_roles:
                logger.warning(
                    "Unauthorized auto_approve attempt by user with roles: %s",
                    user_roles,
                )
                return JSONResponse(
                    {
                        "status": "error",
                        "message": "auto_approve requires factory:admin role",
                    },
                    status=403,
                )
            logger.info(
                "HITL bypassed via auto_approve=true by authenticated user "
                "with factory:admin role"
            )

        human_manager: HumanInteractionManager | None = request.app.get("human_manager")
        if auto_approve or human_manager is None:
            human_manager = build_auto_approve_manager()
            await human_manager.startup()
            human_channel = "auto_approve"
        else:
            human_channel = payload.get("human_channel", "web")

        orchestrator = AgentFactoryOrchestrator(
            human_manager=human_manager,
            human_channel=human_channel,
            human_targets=payload.get("human_targets") or ["api_user"],
            use_llm=use_llm,
            llm=llm,
            category=category,
        )

        try:
            result: FactoryResult = await orchestrator.run(factory_request)
        except Exception as exc:  # noqa: BLE001
            logger.exception("AgentFactory run failed")
            return JSONResponse(
                {"status": "error", "message": str(exc)},
                status=500,
            )

        return JSONResponse(
            result.model_dump(mode="json", exclude_none=True),
            status=200 if result.status.value == "success" else 202,
        )
