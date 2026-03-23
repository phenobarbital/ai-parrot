"""IMAP watchdog hook — async email monitoring with optional tagged filtering."""
import asyncio
from typing import Optional

from .base import BaseHook
from .models import HookType, IMAPHookConfig


class IMAPWatchdogHook(BaseHook):
    """Monitors an IMAP mailbox for new emails using aioimaplib.

    Supports basic auth and XOAUTH2.  Optional tagged-email filtering
    (plus-addressing) when ``config.tag`` is set.
    """

    hook_type = HookType.IMAP_WATCHDOG

    def __init__(self, config: IMAPHookConfig, **kwargs) -> None:
        super().__init__(
            name=config.name,
            enabled=config.enabled,
            target_type=config.target_type,
            target_id=config.target_id,
            metadata=config.metadata,
            **kwargs,
        )
        self._config = config
        self._client = None
        self._poll_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._stop_event.clear()
        await self._connect()
        self._poll_task = asyncio.create_task(self._poll_loop())
        self.logger.info(f"IMAPWatchdogHook '{self.name}' started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        await self._disconnect()
        self.logger.info(f"IMAPWatchdogHook '{self.name}' stopped")

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def _connect(self) -> None:
        try:
            from aioimaplib import IMAP4_SSL, IMAP4
        except ImportError as exc:
            raise ImportError(
                "aioimaplib is required for IMAPWatchdogHook. "
                "Install with: uv pip install aioimaplib"
            ) from exc

        cfg = self._config
        if cfg.use_ssl:
            self._client = IMAP4_SSL(host=cfg.host, port=cfg.port)
        else:
            self._client = IMAP4(host=cfg.host, port=cfg.port)

        await self._client.wait_hello_from_server()

        if cfg.authmech == "XOAUTH2":
            await self._xoauth2_login()
        else:
            await self._client.login(cfg.user, cfg.password)

        await self._client.select(cfg.mailbox)
        self.logger.debug(f"IMAP connected to {cfg.host}:{cfg.port}")

    async def _xoauth2_login(self) -> None:
        """Authenticate using XOAUTH2 mechanism (e.g. Azure/O365)."""
        cfg = self._config
        # Build the XOAUTH2 string per RFC 7628
        auth_string = f"user={cfg.user}\x01auth=Bearer {cfg.password}\x01\x01"
        result = await self._client.authenticate("XOAUTH2", lambda _: auth_string)
        if result.result != "OK":
            raise ConnectionError(f"XOAUTH2 login failed: {result}")

    async def _disconnect(self) -> None:
        if self._client:
            try:
                await self._client.logout()
            except Exception:
                pass
            self._client = None

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Periodically search the mailbox for matching emails."""
        cfg = self._config
        while not self._stop_event.is_set():
            try:
                criteria = self._build_search_criteria()
                self.logger.debug(f"IMAP search: {criteria}")
                result, data = await self._client.search(criteria)
                if result == "OK" and data and data[0]:
                    email_ids = data[0].split()
                    if email_ids:
                        self.logger.info(
                            f"Found {len(email_ids)} matching email(s)"
                        )
                        for email_id in email_ids:
                            await self._process_email(email_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.error(f"IMAP poll error: {exc}")
                try:
                    await self._disconnect()
                    await self._connect()
                except Exception as reconnect_exc:
                    self.logger.error(f"IMAP reconnect failed: {reconnect_exc}")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=cfg.interval,
                )
                break  # stop_event was set
            except asyncio.TimeoutError:
                pass  # interval elapsed, poll again

    def _build_search_criteria(self) -> str:
        parts = []
        for key, value in self._config.search.items():
            if value is None:
                parts.append(key)
            else:
                parts.append(f'({key} "{value}")')
        # Tagged email filtering
        if self._config.tag:
            tagged = self._get_tagged_address()
            parts.append(f'(TO "{tagged}") UNSEEN')
        return " ".join(parts) if parts else "UNSEEN"

    def _get_tagged_address(self) -> str:
        if self._config.alias_address:
            return self._config.alias_address
        user, domain = self._config.user.split("@")
        return f"{user}+{self._config.tag}@{domain}"

    async def _process_email(self, email_id: bytes) -> None:
        """Fetch email structure and emit a HookEvent."""
        status, data = await self._client.fetch(
            email_id.decode(), "(BODYSTRUCTURE ENVELOPE)"
        )
        if status != "OK":
            return

        # Mark as seen if tagged
        if self._config.tag:
            await self._client.store(
                email_id.decode(), "+FLAGS", "\\Seen"
            )

        event = self._make_event(
            event_type="email.received",
            payload={
                "email_id": email_id.decode(),
                "mailbox": self._config.mailbox,
                "structure": str(data) if data else "",
                "tagged": bool(self._config.tag),
            },
            task=f"New email received in {self._config.mailbox}",
        )
        await self.on_event(event)
