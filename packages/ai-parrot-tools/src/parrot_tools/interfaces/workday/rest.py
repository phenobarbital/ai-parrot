"""Workday REST API client (``/ccx/api``).

Minimal async client for Workday's REST surface, sharing :class:`WorkdayConfig`
(credentials, tenant, prod/sandbox ``env`` selector) with the SOAP
``WorkdayService``. Unlike the WSDL services — which have **no** operation to
read raw time clock events — the REST API exposes them, echoing back the
client-assigned ``Time_Clock_Event_ID`` as ``reference_ID`` and the effective
``timeEntryCode`` applied to *In* events. That makes post-punch verification
possible.

Built on ``aiohttp`` per project convention; this is a from-scratch
reimplementation of the equivalent flowtask client on a different HTTP
transport, preserving its public surface verbatim.

Verified endpoints (Workday implementation tenant, 2026-07-03):

- ``GET /ccx/api/v1/{tenant}/workers?search={text}`` — worker lookup; each row
  carries ``id`` (the Workday WID) and ``descriptor``.
- ``GET /ccx/api/timeTracking/v5/{tenant}/timeClockEvents?worker={WID}`` — raw
  clock events. The ``worker`` parameter **requires a WID**; Employee_ID
  values are rejected with ``400 "not found"``.

Example::

    from parrot_tools.interfaces.workday.config import WorkdayConfig
    from parrot_tools.interfaces.workday.rest import WorkdayRestClient

    client = WorkdayRestClient(config=WorkdayConfig(env="sandbox"))
    try:
        workers = await client.find_worker("123456")
        events = await client.get_time_clock_events(workers[0]["id"])
    finally:
        await client.close()
"""

from __future__ import annotations

import base64
import logging
import time as _time
from typing import Any

import aiohttp

from parrot_tools.interfaces.workday.config import WorkdayConfig


class WorkdayRestError(RuntimeError):
    """Raised for actionable Workday REST API failures.

    Distinguishes application-level, actionable failures (e.g. a WID/Employee_ID
    mismatch) from an opaque ``aiohttp.ClientResponseError``.
    """


class WorkdayRestClient:
    """Async client for Workday's ``/ccx/api`` REST endpoints (aiohttp-based).

    Uses the same OAuth *refresh-token* grant as ``SOAPClient`` (no Redis
    dependency — the bearer token is cached in-memory until shortly before
    expiry). Host and credentials come from :class:`WorkdayConfig`, so the
    ``WORKDAY_ENV`` prod/sandbox selector applies here too.

    Args:
        config: Explicit credentials / tenant. ``None`` → ``WorkdayConfig()``
            (conf fallbacks + ``WORKDAY_ENV``).
        timeout: HTTP timeout in seconds (default 30).
        time_tracking_version: REST version segment for the timeTracking
            service (default ``"v5"`` — the version available on this tenant;
            ``v6`` returned 400 when probed).
    """

    def __init__(
        self,
        *,
        config: WorkdayConfig | None = None,
        timeout: int = 30,
        time_tracking_version: str = "v5",
    ) -> None:
        self.config = config or WorkdayConfig()
        self.timeout = timeout
        self.time_tracking_version = time_tracking_version
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._session: aiohttp.ClientSession | None = None
        self._logger = logging.getLogger("parrot_tools.interfaces.workday.rest")

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Lazily create (or recreate, if closed) the shared client session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    async def close(self) -> None:
        """Close the underlying aiohttp session, if one was opened."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        """REST base: ``{workday_url}/ccx/api`` (env-aware host)."""
        return f"{self.config.resolved_workday_url.rstrip('/')}/ccx/api"

    def set_token(self, token: str, expires_in: int = 300) -> None:
        """Reuse an externally obtained bearer token (e.g. from the SOAP flow).

        Args:
            token: A valid Workday OAuth access token.
            expires_in: Seconds the token remains valid (default 300).
        """
        self._token = token
        self._token_expires_at = _time.monotonic() + max(expires_in - 10, 0)

    async def get_token(self) -> str:
        """Return a cached bearer token, refreshing via OAuth when expired.

        Performs the same ``refresh_token`` grant as ``SOAPClient`` (Basic auth
        with client_id/client_secret against ``token_url``).

        Returns:
            A valid access token.
        """
        if self._token and _time.monotonic() < self._token_expires_at:
            return self._token

        cid = self.config.resolved_client_id
        secret = self.config.resolved_client_secret
        basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        session = await self._ensure_session()
        async with session.post(
            self.config.resolved_token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.config.resolved_refresh_token,
            },
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        ) as resp:
            resp.raise_for_status()
            payload = await resp.json()

        self.set_token(payload["access_token"], int(payload.get("expires_in", 300)))
        self._logger.debug(
            "Workday REST token refreshed (env=%s)", self.config.resolved_env
        )
        return self._token  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Core GET
    # ------------------------------------------------------------------

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        """Perform an authenticated GET against ``{base_url}{path}``.

        A ``401`` despite a cached token triggers exactly ONE re-authentication
        (the cached token is discarded and a fresh one obtained); a second
        ``401`` propagates as an ``aiohttp.ClientResponseError``.

        Args:
            path: Path below ``/ccx/api`` (must start with ``/``).
            params: Optional query parameters.

        Returns:
            The parsed JSON body.

        Raises:
            aiohttp.ClientResponseError: on non-2xx responses.
        """
        token = await self.get_token()
        url = f"{self.base_url}{path}"
        session = await self._ensure_session()

        resp = await session.get(
            url, params=params or {}, headers={"Authorization": f"Bearer {token}"}
        )
        if resp.status == 401:
            resp.close()
            # Cached token was rejected — re-authenticate exactly once.
            self._token = None
            self._token_expires_at = 0.0
            token = await self.get_token()
            resp = await session.get(
                url, params=params or {}, headers={"Authorization": f"Bearer {token}"}
            )
        async with resp:
            resp.raise_for_status()
            return await resp.json()

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    async def find_worker(self, search: str, *, limit: int = 20) -> list[dict]:
        """Search workers; each result carries ``id`` (WID) and ``descriptor``.

        Args:
            search: Free-text search (name; associate/employee id support is
                tenant-dependent — verify before relying on it).
            limit: Max results (default 20).

        Returns:
            List of worker dicts (empty when no match).
        """
        payload = await self.get(
            f"/v1/{self.config.resolved_tenant}/workers",
            {"search": search, "limit": limit},
        )
        return payload.get("data", [])

    async def get_time_clock_events(
        self, worker_wid: str, *, limit: int = 100, **criteria: Any
    ) -> list[dict]:
        """Return the raw time clock events of a worker.

        Each event carries ``reference_ID`` (the client-assigned
        ``Time_Clock_Event_ID`` when the event was created via
        ``Put_Time_Clock_Events``), ``dateTime`` (UTC ISO), ``eventType``,
        ``comment``, ``timeZone``, and — on *In* events of time-tracking
        eligible workers — the effective ``timeEntryCode``.

        Args:
            worker_wid: The worker's Workday WID (NOT an Employee_ID — the
                REST API rejects those).
            limit: Max events returned (default 100).
            **criteria: Additional query parameters forwarded verbatim.

        Returns:
            List of event dicts (empty when the worker has none).

        Raises:
            WorkdayRestError: Workday rejected the request with ``400`` —
                the actionable, most common cause being an Employee_ID passed
                where a WID is required.
        """
        params: dict[str, Any] = {"worker": worker_wid, "limit": limit, **criteria}
        try:
            payload = await self.get(
                f"/timeTracking/{self.time_tracking_version}/"
                f"{self.config.resolved_tenant}/timeClockEvents",
                params,
            )
        except aiohttp.ClientResponseError as exc:
            if exc.status == 400:
                raise WorkdayRestError(
                    f"Workday rejected worker={worker_wid!r} for timeClockEvents "
                    "(HTTP 400). The 'worker' parameter requires a Workday WID, "
                    "not an Employee_ID — resolve the WID first via find_worker()."
                ) from exc
            raise
        return payload.get("data", [])

    async def find_time_clock_event(
        self, worker_wid: str, reference_id: str
    ) -> dict | None:
        """Locate one clock event by its client-assigned ``reference_ID``.

        Convenience for punch verification: after ``Put_Time_Clock_Events``
        succeeds, the event is visible here within ~1 s (verified live).

        Args:
            worker_wid: The worker's Workday WID.
            reference_id: The ``Time_Clock_Event_ID`` sent on the Put.

        Returns:
            The matching event dict, or ``None`` when not (yet) present.
        """
        for event in await self.get_time_clock_events(worker_wid):
            if event.get("reference_ID") == reference_id:
                return event
        return None
