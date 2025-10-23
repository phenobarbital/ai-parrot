# soap_client.py

import base64
from abc import ABC
from typing import Any, Optional, Union
from pathlib import Path
import httpx
import redis.asyncio as aioredis
from navconfig.logging import logging
from zeep import AsyncClient as ZeepAsyncClient, Settings
from zeep.transports import AsyncTransport as ZeepAsyncTransport
from ..conf import REDIS_SERVICES_URL

logging.getLogger(name='zeep').setLevel(logging.WARNING)


class NoProxyAsyncTransport(ZeepAsyncTransport):
    """
    Zeep AsyncTransport subclass that:
    - Omits 'proxies=' when building the sync httpx.Client (avoids httpx>=0.28 errors).
    - Provides the attributes Zeep expects (client, logger, _close_session).
    - Disables automatic session close in destructor to avoid AsyncClient.close errors.
    """
    def __init__(
        self,
        client: httpx.AsyncClient,
        cache: Any = None,
        timeout: float = 300,
        operation_timeout: Optional[float] = None,
        headers: dict = None,  # Agregar este parámetro
    ):
        # handshake: store async session
        self.session = client
        # Zeep sometimes references .client directly
        self.client = client
        self.cache = cache
        self._timeout = timeout
        self.operation_timeout = operation_timeout
        # prevent Zeep destructor from trying to close asyncio session
        self._close_session = False
        # provide a logger attribute Zeep expects
        self.logger = logging.getLogger("zeep.transports")
        # Store headers for debugging
        self._debug_headers = headers or {}
        self.wsdl_client = httpx.Client(
            timeout=timeout,
            headers=headers or {},  # Pasar los headers
        )

class SOAPClient(ABC):
    """
    SOAPClient

        Overview

            The SOAPClient class is a generic asynchronous base for SOAP integrations.
            It provides OAuth2 refresh_token grant, Redis caching of access_token, and
            customizable httpx.AsyncClient for Zeep. Designed for easy extension to
            specific SOAP APIs.

        .. table:: Properties
        :widths: auto

            +-------------------+----------+-----------+---------------------------------------------------------------+
            | Name              | Required | Summary                                                           |
            +-------------------+----------+-----------+---------------------------------------------------------------+
            | credentials       |   Yes    | Dict with client_id, client_secret, token_url, wsdl_path, refresh_token |
            | httpx_client      |   No     | Optionally inject a configured AsyncClient                        |
            | redis_url         |   No     | Redis DSN for token cache                                         |
            | redis_key         |   No     | Key under which to cache the access token                         |
            | timeout           |   No     | HTTP request timeout (seconds)                                    |
            +-------------------+----------+-----------+---------------------------------------------------------------+

        Returns

            This component provides an async interface to SOAP APIs, handling authentication,
            caching, and Zeep client/service setup. Subclasses should implement specific
            SOAP operations.

        Example:

        ```python
        class MyClient(SOAPClient):
            ...
        ```
    """

    def __init__(
        self,
        *,
        credentials: dict,
        httpx_client: Optional[httpx.AsyncClient] = None,
        redis_url: Optional[str] = None,
        redis_key: str = "soap:access_token",
        timeout: int = 30,
        **kwargs
    ):
        """
        :param credentials: {
            "client_id": str,
            "client_secret": str,
            "token_url": str,
            "wsdl_path": Union[str, Path],
            "refresh_token": str
        }
        :param httpx_client: optionally inject a configured AsyncClient
        :param redis_url:    Redis DSN for token cache
        :param redis_key:    key under which to cache the access token
        :param timeout:      HTTP request timeout (seconds)
        """
        # Validate credentials dict
        required = ("client_id", "client_secret", "token_url", "wsdl_path", "refresh_token")
        if (missing := [k for k in required if k not in credentials or not credentials[k]]):
            raise TypeError(f"Missing SOAP credentials: {', '.join(missing)}")

        # Stash them
        self.client_id     = credentials["client_id"]
        self.client_secret = credentials["client_secret"]
        self.token_url     = credentials["token_url"]
        # Accept Path or str, but Zeep needs a str
        self.wsdl_path = self._resolve_wsdl_path(credentials["wsdl_path"])
        self.refresh_token = credentials["refresh_token"]

        self._httpx_client = httpx_client
        # Use: 1) explicit redis_url, 2) env config (REDIS_URL), 3) fallback to localhost
        if redis_url is not None:
            self.redis_url = redis_url
        else:
            self.redis_url = REDIS_SERVICES_URL or "redis://localhost:6379/4"
        self.redis_key     = redis_key
        self.timeout       = timeout

        super().__init__(**kwargs)

        self._redis: Optional[aioredis.Redis]             = None
        self._token: Optional[str]                        = None
        self._transport: Optional[NoProxyAsyncTransport]  = None
        self._settings: Optional[Settings]                = None
        self._client: Optional[ZeepAsyncClient]           = None
        self._service: Any                                = None
        self._result: Any                                 = None

    def _resolve_wsdl_path(self, wsdl: Union[str, Path]) -> str:
        """
        Convert Path objects to strings and resolve relative paths.
        """
        return str(wsdl.resolve()) if isinstance(wsdl, Path) else str(wsdl)

    async def start(self) -> None:
        """
        1) Connect to Redis
        2) Get or refresh the bearer token
        3) Build Zeep transport, client, and bind the service
        """
        # 1) Redis
        self._redis = aioredis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True
        )

        # 2) Token
        self._token = await self._get_bearer_token()

        # 3) Zeep pieces
        self._transport = self.get_transport()
        self._settings  = self.get_settings()
        self._client    = self.get_client()
        self._service   = self.bind_service()

    async def _get_bearer_token(self) -> str:
        """
        Retrieve a cached token or perform OAuth2 refresh_token grant.
        """
        # try cache
        tok = await self._redis.get(self.redis_key)
        if tok:
            return tok

        # Basic auth header for refresh_token grant
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        headers = {
            "Authorization":    f"Basic {basic}",
            "Content-Type":     "application/x-www-form-urlencoded",
        }
        data = {
            "grant_type":       "refresh_token",
            "refresh_token":    self.refresh_token,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as http:
            resp = await http.post(self.token_url, data=data, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
            tok     = payload["access_token"]
            exp     = payload.get("expires_in", 300)

        # cache under TTL
        await self._redis.set(self.redis_key, tok, ex=exp - 10)
        return tok

    def get_transport(self) -> NoProxyAsyncTransport:
        """
        Wrap an AsyncClient in our NoProxyAsyncTransport.
        """
        client = self._httpx_client or httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=self.timeout,
        )
        return NoProxyAsyncTransport(
            client=client,
            headers={"Authorization": f"Bearer {self._token}"}
        )

    def get_settings(self) -> Settings:
        """
        Zeep settings: non-strict, support huge XML trees.
        """
        return Settings(strict=False, xml_huge_tree=True)

    def get_client(self) -> ZeepAsyncClient:
        """
        Instantiate the Zeep AsyncClient for our WSDL.
        """
        return ZeepAsyncClient(
            wsdl=self.wsdl_path,
            transport=self._transport,
            settings=self._settings,
        )

    def bind_service(self) -> Any:
        """
        Return the bound service proxy from Zeep.
        """
        return self._client.service  # type: ignore

    async def run(self, operation: str, **kwargs) -> Any:
        """
        Invoke a named SOAP operation with kwargs.
        """
        if not self._service:
            raise RuntimeError("Call start() before run()")
        method = getattr(self._service, operation, None)
        if method is None:
            raise ValueError(f"Operation '{operation}' not found in WSDL")
        res = await method(**kwargs)
        self._result = res
        return res

    async def close(self) -> None:
        """
        Cleanup HTTP session and Redis connection.
        """
        if self._transport and hasattr(self._transport, "session"):
            await self._transport.session.aclose()
        if self._redis:
            await self._redis.close()
