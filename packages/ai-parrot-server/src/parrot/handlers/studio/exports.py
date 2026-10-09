"""``GET {prefix}/exports/{export_tenant}/{agent}/{export_id}/{filename}`` — download of a Studio export (PA-12).

An export is readable only by a caller of the tenant that owns its partition (the first key segment). Anything else —
another tenant, an unknown or expired export, a crafted key (``..``, separators), no store configured — is ONE
``404``: the route never says 403, so it cannot be used to find out what another tenant stored.
"""

from __future__ import annotations

from aiohttp import web
from navigator_auth.decorators import is_authenticated, user_session

from parrot.storage.exports import InvalidExportKey, parse_export_key, safe_filename

from ._base import StudioBaseView
from .access import StudioTenantRequired
from .models import StudioError


@is_authenticated()
@user_session()
class StudioExportDownloadHandler(StudioBaseView):
    """Authorises the caller's tenant against the export's partition, then serves the file as an attachment."""

    def _not_found(self) -> web.Response:
        return self.json_response(StudioError(message="Export not found.", code="not_found").model_dump(), status=404)

    async def get(self):
        info = self.request.match_info
        key = "/".join(info.get(name, "") for name in ("export_tenant", "agent", "export_id", "filename"))
        try:
            parse_export_key(key)  # a crafted segment (``..``, separators, hidden or altered names) is just a 404
        except InvalidExportKey:
            return self._not_found()
        store = self.request.app.get("artifact_store")
        if store is None or not hasattr(store, "get_export"):
            return self._not_found()
        try:
            part = await self._studio_partition()
        except StudioTenantRequired:
            return self._not_found()
        export = await store.get_export(key, tenant=part.tenant)
        if export is None:
            return self._not_found()
        name = safe_filename(export.filename)
        return web.Response(
            body=export.data,
            content_type=export.content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{name}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
