"""HTTP ops handlers for AgentsFlow state checkpointing (FEAT-399, TASK-2055).

Thin HTTP layer over the `CheckpointStore` contract and
`AgentsFlow.resume()` — parses requests, calls the ephemeral/durable
stores or `resume()`, and maps exceptions to HTTP status codes. Follows
the same `BaseView` + `.configure()`/`app.router.add_view()` pattern as
`parrot.handlers.crew.execution_history_handler.CrewExecutionHistoryHandler`
(closest sibling: list / detail / action-on-id / delete over the same
kind of store-backed record).

Endpoints:
    GET    /api/v1/flows/checkpoints                 - list recoverable flows
    GET    /api/v1/flows/checkpoints/{flow_id}        - checkpoint history for a flow
    POST   /api/v1/flows/checkpoints/{flow_id}/resume - resume a flow (202, background run)
    DELETE /api/v1/flows/checkpoints/{flow_id}        - delete a flow's checkpoints (both tiers)
"""
from __future__ import annotations

import asyncio
from typing import Any

from navconfig.logging import logging
from navigator.applications.base import BaseApplication  # pylint: disable=E0611,E0401
from navigator.types import WebApp  # pylint: disable=E0611,E0401
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from parrot.bots.flows.core.checkpoint.errors import (
    CheckpointNotFoundError,
    FlowLockedError,
)
from parrot.bots.flows.core.checkpoint.store.base import CheckpointStore
from parrot.bots.flows.core.checkpoint.store.factory import get_checkpoint_store
from parrot.bots.flows.flow.flow import AgentsFlow
from parrot.conf import FLOW_CHECKPOINT_DURABLE_STORE


@is_authenticated()
@user_session()
class FlowCheckpointHandler(BaseView):
    """REST API handler for the AgentsFlow checkpoint ops surface.

    No new auth mechanism — reuses the existing `is_authenticated`/
    `user_session` decorators, same as `CrewToolCatalogHandler`/
    `InfographicTalk` (spec resolved OQ5).
    """

    path: str = '/api/v1/flows/checkpoints'
    app: WebApp = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger('Parrot.FlowCheckpointHandler')
        self._store: CheckpointStore | None = None
        self._durable_store: CheckpointStore | None = None

    @property
    def store(self) -> CheckpointStore:
        """Lazily resolve the ephemeral `CheckpointStore` (env fallback)."""
        if self._store is None:
            self._store = get_checkpoint_store(None)
        return self._store

    @property
    def durable_store(self) -> CheckpointStore | None:
        """Lazily resolve the durable `CheckpointStore`, if configured."""
        if self._durable_store is None and FLOW_CHECKPOINT_DURABLE_STORE:
            self._durable_store = get_checkpoint_store(FLOW_CHECKPOINT_DURABLE_STORE)
        return self._durable_store

    @property
    def bot_manager(self):
        """Get the BotManager instance registered on the app (or None)."""
        return self.request.app.get('bot_manager')

    @classmethod
    def configure(cls, app: WebApp = None, path: str | None = None, **kwargs) -> WebApp:
        """Register routes on the aiohttp `Application`.

        Args:
            app: The aiohttp `Application` (or `BaseApplication`) to register on.
            path: Route path prefix; defaults to `cls.path`.
            **kwargs: Unused; kept for signature parity with sibling handlers.
        """
        if isinstance(app, BaseApplication):
            cls.app = app.get_app()
        elif isinstance(app, WebApp):
            cls.app = app

        if app:
            url = path or cls.path
            # Root route: list recoverable flows.
            app.router.add_view(rf"{url}", cls)
            # Action route (resume) MUST precede the bare {flow_id} route so
            # aiohttp resolves /{flow_id}/resume before the catch-all detail
            # route (same ordering discipline as CrewExecutionHistoryHandler).
            app.router.add_view(
                rf"{url}/{{flow_id}}/resume", cls
            )
            # Detail/delete route.
            app.router.add_view(rf"{url}/{{flow_id}}", cls)

    # ------------------------------------------------------------------
    # HTTP verbs
    # ------------------------------------------------------------------

    async def get(self):
        """List recoverable flows, or checkpoint history if `flow_id` is set."""
        match_params = self.match_parameters(self.request)
        flow_id = match_params.get('flow_id')
        if flow_id:
            return await self._history(flow_id)
        return await self._list()

    async def post(self):
        """Resume a flow (only action route: `{flow_id}/resume`)."""
        match_params = self.match_parameters(self.request)
        flow_id = match_params.get('flow_id')
        if not flow_id:
            return self.error(
                response={"message": "flow_id is required"}, status=400
            )
        return await self._resume(flow_id)

    async def delete(self):
        """Delete a flow's checkpoints from both tiers."""
        match_params = self.match_parameters(self.request)
        flow_id = match_params.get('flow_id')
        if not flow_id:
            return self.error(
                response={"message": "flow_id is required"}, status=400
            )
        return await self._delete(flow_id)

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    async def _list(self):
        """Handle `GET /` — list recoverable flows (`?status=` filter)."""
        qs = self.get_arguments(self.request)
        status = qs.get('status')

        try:
            flows = list(await self.store.list_flows(status=status))
            if self.durable_store is not None:
                durable_flows = await self.durable_store.list_flows(status=status)
                seen = {f["flow_id"] for f in flows}
                flows.extend(f for f in durable_flows if f["flow_id"] not in seen)
        except Exception as exc:  # noqa: BLE001 - map to a clean 500
            self.logger.error("Error listing checkpointed flows: %s", exc)
            # NOTE: navigator's BaseView.error() only maps a fixed status
            # whitelist (400/401/403/404/406/412/428) and silently
            # downgrades anything else (409, 500, ...) to 400 — use
            # json_response() directly for status codes outside that set.
            return self.json_response({"message": str(exc)}, status=500)

        return self.json_response({"flows": flows, "total": len(flows)})

    async def _history(self, flow_id: str):
        """Handle `GET /{flow_id}` — checkpoint history for a flow."""
        qs = self.get_arguments(self.request)
        try:
            limit = int(qs.get('limit', 10))
        except (TypeError, ValueError):
            return self.error(
                response={"message": "limit must be an integer"}, status=400
            )

        try:
            history = await self.store.history(flow_id, limit=limit)
            if not history and self.durable_store is not None:
                history = await self.durable_store.history(flow_id, limit=limit)
        except Exception as exc:  # noqa: BLE001 - map to a clean 500
            self.logger.error(
                "Error fetching checkpoint history for flow_id=%s: %s",
                flow_id,
                exc,
            )
            return self.json_response({"message": str(exc)}, status=500)

        if not history:
            return self.error(
                response={
                    "message": f"No checkpoints found for flow_id={flow_id!r}"
                },
                status=404,
            )

        return self.json_response(
            {
                "flow_id": flow_id,
                "history": [cp.model_dump(mode="json") for cp in history],
            }
        )

    async def _resume(self, flow_id: str):
        """Handle `POST /{flow_id}/resume` — resume via `AgentsFlow.resume()`.

        Returns 202 immediately; the resumed `run_flow()` is scheduled as a
        tracked background task (it registers itself with
        `FlowRecoveryService` automatically, same as any other checkpointed
        run — TASK-2054).
        """
        try:
            data: dict[str, Any] = await self.request.json()
        except Exception:  # noqa: BLE001 - missing/invalid body just means no options
            data = {}
        checkpoint_id = data.get("checkpoint_id")

        registry = getattr(self.bot_manager, "registry", None)
        if registry is None:
            return self.json_response(
                {"message": "AgentRegistry not available"}, status=500
            )

        try:
            flow = await AgentsFlow.resume(
                flow_id,
                checkpoint_id,
                agent_registry=registry,
                store=self.store,
                durable_store=self.durable_store,
            )
        except FlowLockedError as exc:
            # 409 is outside navigator's error() status whitelist — see the
            # NOTE in _list().
            return self.json_response({"message": str(exc)}, status=409)
        except CheckpointNotFoundError as exc:
            return self.error(response={"message": str(exc)}, status=404)
        except Exception as exc:
            self.logger.exception("Error resuming flow_id=%s", flow_id)
            return self.json_response({"message": str(exc)}, status=500)

        task = asyncio.ensure_future(flow.run_flow())
        task.add_done_callback(self._log_background_run_error)

        return self.json_response(
            {"flow_id": flow_id, "status": "accepted"}, status=202
        )

    def _log_background_run_error(self, task: asyncio.Task) -> None:
        """Done-callback that logs (instead of raising) background run errors."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self.logger.error(
                "Background resumed run_flow() raised: %s", exc, exc_info=exc
            )

    async def _delete(self, flow_id: str):
        """Handle `DELETE /{flow_id}` — delete checkpoints from both tiers."""
        try:
            await self.store.delete_flow(flow_id)
            if self.durable_store is not None:
                await self.durable_store.delete_flow(flow_id)
        except Exception as exc:  # noqa: BLE001 - map to a clean 500
            self.logger.error("Error deleting flow_id=%s: %s", flow_id, exc)
            return self.json_response({"message": str(exc)}, status=500)

        return self.json_response({"deleted": True, "flow_id": flow_id})
