"""Reload paths (legacy ``reload_agent`` and database-mode ``manager.studio.reload``) as a mixin."""

from __future__ import annotations



from parrot.manager.manager import AgentNotFoundError, AgentReloadError

from ..storage.models import (
    StudioAgentKey,
    StudioStorageUnavailable,
)


class _StudioAgentReloadMixin:
    """``_legacy_reload`` / ``_db_reload`` / ``_studio_reload`` of ``StudioAgentReloadHandler``."""

    async def _legacy_reload(self):
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("agents", "astudio:agents:reload")) is not None:
            return denied

        name = self.request.match_info.get("name")
        if not name:
            return self._error("Agent name is required.", status=400, code="missing_name")

        manager = self._manager()
        if manager is None:
            return self._error("BotManager unavailable.", status=503, code="unavailable")

        try:
            result = await manager.reload_agent(name)
        except AgentNotFoundError as exc:
            return self._error(str(exc), status=404, code="not_found")
        except AgentReloadError as exc:
            return self._error(str(exc), status=422, code="reload_failed")
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error(
                "Studio: reload of agent '%s' failed unexpectedly: %s",
                name,
                exc,
                exc_info=True,
            )
            return self._error("Internal server error.", status=500, code="internal_error")

        return self.json_response(result.model_dump(), status=200)

    async def _db_reload(self, storage, part):
        """Studio row → ``manager.studio.reload``; a GLOBAL name that is not a Studio row takes the legacy path."""
        name, rec = await self._studio_name_lookup(storage, part)
        if rec is None and part.tenant is None:
            return await self._legacy_reload()
        if (denied := await self._require_author()) is not None:
            return denied
        if not name:
            return self._error("Agent name is required.", status=400, code="missing_name")
        if (refused := self._refuse_expected_version(self.request.query)) is not None:
            return refused
        if rec is None:
            return self._not_found("agent", name)
        if (denied := await self._studio_authorize(rec, name, manage=False)) is not None:
            return denied
        return await self._studio_reload(StudioAgentKey(part.tenant, name))

    async def _studio_reload(self, key: StudioAgentKey):
        """``manager.studio.reload`` with the legacy error mapping (404 / 422)."""
        runtime = getattr(self._manager(), "studio", None)
        if runtime is None:
            raise StudioStorageUnavailable("studio runtime is not installed")
        try:
            result = await runtime.reload(key)
        except AgentNotFoundError as exc:
            return self._error(str(exc), status=404, code="not_found")
        except AgentReloadError as exc:
            return self._error(str(exc), status=422, code="reload_failed")
        return self.json_response(result.model_dump(), status=200)
