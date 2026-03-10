"""SharePoint webhook hook — Microsoft Graph API subscription management."""
import asyncio
import time
from typing import Any, Dict, Optional

from aiohttp import web

from .base import BaseHook
from .models import HookType, SharePointHookConfig


class SharePointHook(BaseHook):
    """Subscribes to SharePoint changes via Microsoft Graph API.

    Handles subscription creation, validation, renewal, and change
    notifications.  Requires ``azure-identity`` and ``msgraph-sdk``.
    """

    hook_type = HookType.SHAREPOINT

    def __init__(self, config: SharePointHookConfig, **kwargs) -> None:
        super().__init__(
            name=config.name,
            enabled=config.enabled,
            target_type=config.target_type,
            target_id=config.target_id,
            metadata=config.metadata,
            **kwargs,
        )
        self._config = config
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._subscription_id: Optional[str] = None
        self._renewal_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        await self._authenticate()
        await self._create_subscription()
        self._renewal_task = asyncio.create_task(self._renewal_loop())
        self.logger.info(f"SharePointHook '{self.name}' started")

    async def stop(self) -> None:
        if self._renewal_task:
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except asyncio.CancelledError:
                pass
        if self._subscription_id:
            await self._delete_subscription()
        self.logger.info(f"SharePointHook '{self.name}' stopped")

    def setup_routes(self, app: Any) -> None:
        url = self._config.url
        app.router.add_post(url, self._handle_notification)
        self.logger.info(f"SharePoint webhook route: POST {url}")

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def _authenticate(self) -> None:
        try:
            from azure.identity.aio import ClientSecretCredential
        except ImportError as exc:
            raise ImportError(
                "azure-identity is required for SharePointHook. "
                "Install with: uv pip install azure-identity"
            ) from exc

        credential = ClientSecretCredential(
            tenant_id=self._config.tenant_id,
            client_id=self._config.client_id,
            client_secret=self._config.client_secret,
        )
        token = await credential.get_token("https://graph.microsoft.com/.default")
        self._access_token = token.token
        self._token_expires_at = token.expires_on
        await credential.close()
        self.logger.debug("SharePoint authentication successful")

    async def _ensure_token(self) -> str:
        if time.time() >= self._token_expires_at - 300:
            await self._authenticate()
        return self._access_token

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    async def _create_subscription(self) -> None:
        import aiohttp
        from datetime import datetime, timedelta, timezone

        token = await self._ensure_token()
        resource = self._config.resource or self._build_resource_path()
        expiration = (
            datetime.now(timezone.utc) + timedelta(minutes=4230)
        ).isoformat()

        body = {
            "changeType": self._config.changetype,
            "notificationUrl": self._config.webhook_url,
            "resource": resource,
            "expirationDateTime": expiration,
            "clientState": self._config.client_state,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://graph.microsoft.com/v1.0/subscriptions",
                json=body,
                headers=self._headers(),
            ) as resp:
                if resp.status == 201:
                    data = await resp.json()
                    self._subscription_id = data["id"]
                    self.logger.info(
                        f"SharePoint subscription created: {self._subscription_id}"
                    )
                else:
                    text = await resp.text()
                    raise RuntimeError(
                        f"Failed to create SharePoint subscription: {resp.status} {text}"
                    )

    async def _delete_subscription(self) -> None:
        import aiohttp

        if not self._subscription_id:
            return
        await self._ensure_token()
        async with aiohttp.ClientSession() as session:
            url = f"https://graph.microsoft.com/v1.0/subscriptions/{self._subscription_id}"
            async with session.delete(url, headers=self._headers()) as resp:
                if resp.status in (200, 204):
                    self.logger.info(
                        f"SharePoint subscription deleted: {self._subscription_id}"
                    )
                else:
                    self.logger.warning(
                        f"Failed to delete subscription: {resp.status}"
                    )

    async def _renew_subscription(self) -> None:
        import aiohttp
        from datetime import datetime, timedelta, timezone

        if not self._subscription_id:
            return
        await self._ensure_token()
        expiration = (
            datetime.now(timezone.utc) + timedelta(minutes=4230)
        ).isoformat()

        async with aiohttp.ClientSession() as session:
            url = f"https://graph.microsoft.com/v1.0/subscriptions/{self._subscription_id}"
            async with session.patch(
                url,
                json={"expirationDateTime": expiration},
                headers=self._headers(),
            ) as resp:
                if resp.status == 200:
                    self.logger.info("SharePoint subscription renewed")
                else:
                    self.logger.warning(
                        f"Subscription renewal failed: {resp.status}"
                    )

    async def _renewal_loop(self) -> None:
        """Periodically renew the subscription."""
        interval = self._config.renewal_interval
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self._renew_subscription()
                except Exception as exc:
                    self.logger.error(f"Subscription renewal error: {exc}")
        except asyncio.CancelledError:
            pass

    def _build_resource_path(self) -> str:
        parts = []
        if self._config.host:
            parts.append(f"sites/{self._config.host}")
        if self._config.site_name:
            parts.append(f":/sites/{self._config.site_name}:")
        if self._config.folder_path:
            parts.append(f"drive/root:/{self._config.folder_path}")
        return "/".join(parts) if parts else "me/drive/root"

    # ------------------------------------------------------------------
    # Notification handling
    # ------------------------------------------------------------------

    async def _handle_notification(self, request: web.Request) -> web.Response:
        # Validation challenge from Graph API
        validation_token = request.query.get("validationToken")
        if validation_token:
            return web.Response(
                text=validation_token, content_type="text/plain"
            )

        try:
            data = await request.json()
            notifications = data.get("value", [])
            for notification in notifications:
                # Verify client state
                if notification.get("clientState") != self._config.client_state:
                    self.logger.warning("Client state mismatch — ignoring")
                    continue

                resource = notification.get("resource", "")
                change_type = notification.get("changeType", "")

                event = self._make_event(
                    event_type=f"sharepoint.{change_type}",
                    payload={
                        "resource": resource,
                        "change_type": change_type,
                        "subscription_id": notification.get("subscriptionId"),
                        "tenant_id": notification.get("tenantId"),
                        "client_state": notification.get("clientState"),
                    },
                    task=f"SharePoint {change_type}: {resource}",
                )
                await self.on_event(event)

            return web.Response(status=202)
        except Exception as exc:
            self.logger.error(f"SharePoint notification error: {exc}")
            return web.Response(status=500)
