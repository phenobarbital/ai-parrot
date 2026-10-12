"""Server-managed constructor inputs shared by every Studio route that assigns a toolkit to a live agent."""

from __future__ import annotations

from uuid import UUID

from parrot.tools.host_hooks import STUDIO_TOOLKIT_PARAM_HOOK, run_toolkit_param_hook, split_exclude_tools
from parrot.tools.server_params import constructor_server_params
from parrot.tools.tooling_policy import ToolingSubject, ToolParamRefused

from .models import StudioError


class _ToolkitAssignError(Exception):
    """Raised by the per-toolkit assignment helpers; mapped to a response
    by the handler."""

    def __init__(self, status: int, code: str, message: str, details: dict | None = None) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


class _ServerManagedAssignMixin:
    """Fills the constructor params the server owns and refuses a client value for them (FEAT-622 M4)."""

    def _server_managed_inputs(self, cls: type, params: dict) -> dict:
        """Constructor values the server fills (``source="app"`` from ``request.app``); refuses a client value (422)."""
        declared = getattr(cls, "server_managed_params", None) or {}
        sent = sorted(set(params) & set(declared))
        if sent:
            raise _ToolkitAssignError(
                422, "server_managed", f"Server-managed parameters cannot be set: {', '.join(sent)}",
                details={"params": sent},
            )
        app = self.request.app
        return {
            name: app[declared[name].key]
            for name in constructor_server_params(cls)
            if declared[name].source == "app" and app.get(declared[name].key) is not None
        }

    async def _assign_subject(self, bot, user) -> ToolingSubject:
        """Who a live assignment is for (the host parameter hook's ``subject``; phase ``attach``)."""
        part = await self._studio_partition()
        try:
            agent_id = UUID(str(getattr(bot, "chatbot_id", "")))
        except ValueError:
            agent_id = None
        return ToolingSubject(tenant=part.tenant, agent_id=agent_id, actor=user.user_id, phase="attach")

    def _host_params(self, slug: str, params: dict, subject: ToolingSubject | None) -> tuple[dict, tuple[str, ...]]:
        """The host toolkit-parameter hook (PA-9) over ``params``: ``(final params, forced exclude_tools)``.

        A refusal is the ``422 tooling_not_permitted`` / ``tool_params_not_permitted`` response with
        ``details.params``; without a registered hook the params are returned unchanged.
        """
        hook = self.request.app.get(STUDIO_TOOLKIT_PARAM_HOOK)
        if hook is None or subject is None:
            return dict(params), ()
        try:
            return split_exclude_tools(run_toolkit_param_hook(hook, slug, params, subject))
        except ToolParamRefused as exc:
            raise _ToolkitAssignError(
                422, exc.code, str(exc), details={"reason": exc.reason, "item": exc.item, "params": exc.params}
            ) from exc

    def _managed_toolkit_params(self, entries: list, resolve) -> list[dict | None]:
        """Final constructor params per toolkit entry (``None`` when ``resolve`` finds no class).

        Raises ``_ToolkitAssignError`` (422 ``server_managed``) at the first client-supplied server-managed key, so
        a refused request registers nothing.
        """
        final: list[dict | None] = []
        for entry in entries:
            cls = resolve(entry.slug)
            final.append(None if cls is None else {**entry.params, **self._server_managed_inputs(cls, entry.params)})
        return final

    def _assign_refusal(self, exc: _ToolkitAssignError):
        """The Studio error response (with ``details``) of an assignment refusal."""
        body = StudioError(message=exc.message, code=exc.code, details=exc.details)
        return self.json_response(body.model_dump(), status=exc.status)
