"""Command channel to a headless child (spec §3 Module 6; S4 token in both modes)."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Protocol

from aiohttp import ClientConnectorError, ClientSession, ClientTimeout, UnixConnector

from parrot.flows.dev_loop.commands import CancelRunRequest, ResolveGateRequest  # verified: commands.py:46,64
from parrot.integrations.devloop.models import BridgeResult

_STATUS_REASON = {404: "not_found", 409: "already_resolved", 401: "unauthorized"}


class RunCommandChannel(Protocol):
    """Inbound command path to one run. A Redis implementation may replace this later (brainstorm Option B)."""

    async def resolve_gate(
        self,
        run_id: str,
        gate_id: str,
        *,
        resolution: str,
        resolved_by: str,
        comment: str = "",
        answers: Optional[dict] = None,
    ) -> BridgeResult: ...

    async def cancel(self, run_id: str, *, requested_by: str) -> BridgeResult: ...

    async def probe(self) -> bool: ...


class LoopbackRestChannel:
    """``RunCommandChannel`` over the child's ``register_command_routes`` (Unix socket or 127.0.0.1 TCP)."""

    def __init__(self, endpoint: str, *, token: str, timeout: float = 10.0) -> None:
        self._endpoint = endpoint
        self._token = token
        self._timeout = ClientTimeout(total=timeout)
        self.logger = logging.getLogger(__name__)

    def _session(self) -> ClientSession:
        headers = {"Authorization": f"Bearer {self._token}"}
        if self._endpoint.startswith("unix://"):
            return ClientSession(
                connector=UnixConnector(path=self._endpoint[len("unix://") :]),
                headers=headers,
                timeout=self._timeout,
            )
        return ClientSession(headers=headers, timeout=self._timeout)

    def _url(self, path: str) -> str:
        base = "http://localhost" if self._endpoint.startswith("unix://") else self._endpoint
        return f"{base}{path}"

    async def _post(self, path: str, body: dict) -> BridgeResult:
        """POST ``body`` to ``path``; maps every outcome to a ``BridgeResult``, never raises."""
        try:
            async with self._session() as session:
                async with session.post(self._url(path), json=body) as resp:
                    if resp.status == 200:
                        return BridgeResult(ok=True, status=200)
                    if resp.status == 400:
                        try:
                            data = await resp.json()
                        except Exception:  # noqa: BLE001 - malformed error body, still a 400
                            data = {}
                        return BridgeResult(ok=False, status=400, reason=data.get("error", "invalid_body"))
                    reason = _STATUS_REASON.get(resp.status, "")
                    return BridgeResult(ok=False, status=resp.status, reason=reason)
        except (ClientConnectorError, asyncio.TimeoutError, OSError) as exc:
            self.logger.debug("devloop bridge unreachable at %s: %s", self._endpoint, exc)
            return BridgeResult(ok=False, status=0, reason="unreachable")

    async def resolve_gate(
        self,
        run_id: str,
        gate_id: str,
        *,
        resolution: str,
        resolved_by: str,
        comment: str = "",
        answers: Optional[dict] = None,
    ) -> BridgeResult:
        """POST the existing gate-resolve contract to the child."""
        body = ResolveGateRequest(
            resolution=resolution, resolved_by=resolved_by, comment=comment, answers=dict(answers or {})
        ).model_dump()
        return await self._post(f"/runs/{run_id}/gates/{gate_id}/resolve", body)

    async def cancel(self, run_id: str, *, requested_by: str) -> BridgeResult:
        """POST the existing cancel contract to the child."""
        return await self._post(f"/runs/{run_id}/cancel", CancelRunRequest(requested_by=requested_by).model_dump())

    async def probe(self) -> bool:
        """Any HTTP response (even 401/404) means the child is listening.

        Returns:
            ``True`` when the endpoint answers at all; ``False`` on a
            connection error (used by re-attach, AC13).
        """
        try:
            async with self._session() as session:
                async with session.get(self._url("/")):
                    return True
        except (ClientConnectorError, asyncio.TimeoutError, OSError):
            return False
