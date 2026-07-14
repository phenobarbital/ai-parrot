"""
REST API Handler for AgentCrew Saved Execution History (FEAT-307).

Exposes list/detail/replay/schedule/delete operations over saved crew
executions, backed by ``SavedExecutionService``.

Endpoints:
    GET    /api/v1/crew/executions                       - list executions
    GET    /api/v1/crew/executions/{execution_id}         - execution detail
    POST   /api/v1/crew/executions/{execution_id}/replay   - replay execution
    POST   /api/v1/crew/executions/{execution_id}/schedule - schedule execution
    DELETE /api/v1/crew/executions/{execution_id}         - delete execution
"""
from typing import Any, Dict, Optional

from navigator.views import BaseView
from navigator.types import WebApp  # pylint: disable=E0611,E0401
from navigator.applications.base import BaseApplication  # pylint: disable=E0611,E0401
from navconfig.logging import logging

from parrot.bots.flows.core.storage.backends import get_result_storage
from parrot.handlers.crew.models import ExecutionFilter, ScheduleRequest
from parrot.handlers.crew.saved_execution_service import SavedExecutionService


class CrewExecutionHistoryHandler(BaseView):
    """REST API Handler for saved crew execution history, replay, and scheduling.

    Thin HTTP layer over ``SavedExecutionService`` — all orchestration logic
    (storage reads, crew resolution, scheduler calls) lives in the service;
    this handler only parses requests, calls the service, and maps
    exceptions to HTTP responses.
    """

    path: str = '/api/v1/crew/executions'
    app: WebApp = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger('Parrot.CrewExecutionHistoryHandler')
        self._service: Optional[SavedExecutionService] = None

    @property
    def service(self) -> SavedExecutionService:
        """Lazily build the ``SavedExecutionService`` from app-level dependencies."""
        if self._service is None:
            app = self.request.app
            bot_manager = app.get('bot_manager')
            scheduler_manager = app.get('scheduler_manager')
            storage = get_result_storage()
            self._service = SavedExecutionService(
                storage=storage,
                bot_manager=bot_manager,
                scheduler_manager=scheduler_manager,
            )
        return self._service

    @classmethod
    def configure(cls, app: WebApp = None, path: str = None, **kwargs) -> WebApp:
        if isinstance(app, BaseApplication):
            cls.app = app.get_app()
        elif isinstance(app, WebApp):
            cls.app = app

        if app:
            # Root route: list executions
            app.router.add_view(
                r"{url}".format(url=cls.path), cls
            )
            # Action routes: replay / schedule
            app.router.add_view(
                r"{url}/{{execution_id}}/{{action:replay|schedule}}".format(url=cls.path), cls
            )
            # Detail/delete route
            app.router.add_view(
                r"{url}/{{execution_id}}".format(url=cls.path), cls
            )

    # ------------------------------------------------------------------
    # Request context helpers
    # ------------------------------------------------------------------

    def _get_tenant_user(self, source: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Extract ``(tenant, user_id)`` from query args or JSON body.

        Args:
            source: Either query args (``self.get_arguments()``) or a parsed
                JSON body dict.

        Returns:
            A ``(tenant, user_id)`` tuple. ``tenant`` defaults to ``"global"``
            (matching ``CrewHandler.get()``'s convention) — unlike
            ``CrewExecutionHandler.execute_crew()``, which requires an
            explicit tenant on POST /crews. Saved-execution history is a
            read/replay surface, not a fresh-execution surface, so
            defaulting to "global" is safe and consistent with the
            storage layer's own COALESCE(tenant, 'global') fallback.
        """
        tenant = source.get('tenant') or 'global'
        user_id = source.get('user_id')
        return tenant, user_id

    # ------------------------------------------------------------------
    # HTTP verbs
    # ------------------------------------------------------------------

    async def get(self):
        """List executions, or return execution detail if `execution_id` is set."""
        match_params = self.match_parameters(self.request)
        execution_id = match_params.get('execution_id')
        qs = self.get_arguments(self.request)
        tenant, user_id = self._get_tenant_user(qs)

        if execution_id:
            return await self._get_detail(tenant, user_id, execution_id)
        return await self._list(tenant, user_id, qs)

    async def post(self):
        """Replay or schedule a saved execution, per the `{action}` path segment."""
        match_params = self.match_parameters(self.request)
        execution_id = match_params.get('execution_id')
        action = match_params.get('action')

        if not execution_id or not action:
            return self.error(
                response={"message": "execution_id and action are required"},
                status=400,
            )

        try:
            data = await self.request.json()
        except Exception:
            data = {}
        tenant, user_id = self._get_tenant_user(data)

        if action == 'replay':
            return await self._replay(tenant, user_id, execution_id)
        if action == 'schedule':
            return await self._schedule(tenant, user_id, execution_id, data)
        return self.error(
            response={"message": f"Unknown action: {action}"},
            status=400,
        )

    async def delete(self):
        """Delete a saved execution."""
        match_params = self.match_parameters(self.request)
        execution_id = match_params.get('execution_id')
        if not execution_id:
            return self.error(
                response={"message": "execution_id is required"}, status=400
            )

        qs = self.get_arguments(self.request)
        tenant, user_id = self._get_tenant_user(qs)

        deleted = await self.service.delete_execution(tenant, user_id, execution_id)
        if not deleted:
            return self.error(
                response={"message": f"Execution '{execution_id}' not found"},
                status=404,
            )
        return self.json_response({"deleted": True, "execution_id": execution_id})

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    async def _list(self, tenant: str, user_id: Optional[str], qs: Dict[str, Any]):
        """Handle GET / — paginated list with optional filters."""
        try:
            limit = int(qs.get('limit', 20))
            offset = int(qs.get('offset', 0))
        except (TypeError, ValueError):
            return self.error(
                response={"message": "limit/offset must be integers"}, status=400
            )

        filters = ExecutionFilter(
            crew_name=qs.get('crew_name'),
            method=qs.get('method'),
            date_from=qs.get('date_from'),
            date_to=qs.get('date_to'),
        )

        try:
            items, total = await self.service.list_executions(
                tenant, user_id, filters=filters, limit=limit, offset=offset
            )
        except Exception as exc:
            self.logger.error("Error listing executions: %s", exc)
            return self.error(response={"message": str(exc)}, status=500)

        return self.json_response({
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        })

    async def _get_detail(self, tenant: str, user_id: Optional[str], execution_id: str):
        """Handle GET /{execution_id} — full execution detail."""
        try:
            record = await self.service.get_execution(tenant, user_id, execution_id)
        except Exception as exc:
            self.logger.error("Error fetching execution %s: %s", execution_id, exc)
            return self.error(response={"message": str(exc)}, status=500)

        if not record:
            return self.error(
                response={"message": f"Execution '{execution_id}' not found"},
                status=404,
            )
        return self.json_response(record)

    async def _replay(self, tenant: str, user_id: Optional[str], execution_id: str):
        """Handle POST /{execution_id}/replay."""
        try:
            result = await self.service.replay_execution(tenant, user_id, execution_id)
            return self.json_response(result)
        except ValueError as exc:
            message = str(exc)
            status = 404 if 'not found' in message or 'no longer exists' in message else 400
            return self.error(response={"message": message}, status=status)
        except Exception as exc:
            self.logger.error("Error replaying execution %s: %s", execution_id, exc)
            return self.error(response={"message": str(exc)}, status=500)

    async def _schedule(
        self,
        tenant: str,
        user_id: Optional[str],
        execution_id: str,
        data: Dict[str, Any],
    ):
        """Handle POST /{execution_id}/schedule."""
        try:
            schedule_request = ScheduleRequest(**{
                k: v for k, v in data.items() if k != 'tenant' and k != 'user_id'
            })
        except Exception as exc:
            return self.error(
                response={"message": f"Invalid schedule request: {exc}"}, status=400
            )

        try:
            schedule = await self.service.schedule_execution(
                tenant, user_id, execution_id, schedule_request
            )
            return self.json_response(schedule)
        except ValueError as exc:
            message = str(exc)
            status = 404 if 'not found' in message else 400
            return self.error(response={"message": message}, status=status)
        except Exception as exc:
            self.logger.error("Error scheduling execution %s: %s", execution_id, exc)
            return self.error(response={"message": str(exc)}, status=500)
