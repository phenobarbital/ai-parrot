"""Odoo ERP interface via JSON-RPC 2.0.

Provides an async-first interface to Odoo v16+ for reading and writing
business data (partners, invoices, products, inventory, etc.) through
the standard JSON-RPC 2.0 endpoint.
"""
from __future__ import annotations

import re
from typing import Any, Optional
from pydantic import BaseModel, Field
import aiohttp
from navconfig.logging import logging

from parrot.conf import (
    ODOO_URL,
    ODOO_DATABASE,
    ODOO_USERNAME,
    ODOO_PASSWORD,
    ODOO_TIMEOUT,
    ODOO_VERIFY_SSL,
)


# ── Exceptions ───────────────────────────────────────────────────────────────

class OdooError(Exception):
    """Base exception for Odoo JSON-RPC errors."""


class OdooAuthenticationError(OdooError):
    """Raised when authentication fails (invalid credentials or False uid)."""


class OdooRPCError(OdooError):
    """Raised when Odoo returns a JSON-RPC error response."""

    def __init__(self, message: str, error_data: dict[str, Any] | None = None) -> None:
        """Initialize OdooRPCError.

        Args:
            message: Human-readable error message.
            error_data: Raw error dict from the JSON-RPC response.
        """
        super().__init__(message)
        self.error_data = error_data or {}


class OdooConnectionError(OdooError):
    """Raised on network or connection failures."""


# ── Pydantic Models ───────────────────────────────────────────────────────────

class OdooConfig(BaseModel):
    """Configuration for Odoo JSON-RPC connection.

    Attributes:
        url: Odoo instance base URL (e.g., https://myodoo.com).
        database: Odoo database name.
        username: Odoo login username.
        password: Odoo login password or API key.
        timeout: Request timeout in seconds.
        verify_ssl: Whether to verify SSL certificates.
    """

    url: str = Field(..., description="Odoo instance URL")
    database: str = Field(..., description="Odoo database name")
    username: str = Field(..., description="Odoo login username")
    password: str = Field(..., description="Odoo login password or API key")
    timeout: int = Field(default=30, description="Request timeout in seconds")
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")


class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 request payload.

    Attributes:
        jsonrpc: Protocol version, always "2.0".
        method: RPC method, always "call" for Odoo.
        id: Request identifier.
        params: Service, method, and args to dispatch.
    """

    jsonrpc: str = "2.0"
    method: str = "call"
    id: int = 1
    params: dict[str, Any]


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 response payload.

    Attributes:
        jsonrpc: Protocol version.
        id: Request identifier matching the request.
        result: Successful result payload (None if error).
        error: Error details dict (None on success).
    """

    jsonrpc: str
    id: int
    result: Any = None
    error: Optional[dict[str, Any]] = None


# ── Model-name validation ─────────────────────────────────────────────────────

_MODEL_NAME_RE = re.compile(r"^[a-z_][a-z0-9_.]*$")


def _validate_model_name(model: str) -> None:
    """Validate an Odoo model name to prevent injection.

    Args:
        model: Odoo model name (e.g., "res.partner").

    Raises:
        ValueError: If the model name contains invalid characters.
    """
    if not _MODEL_NAME_RE.match(model):
        raise ValueError(
            f"Invalid Odoo model name: {model!r}. "
            "Must match ^[a-z_][a-z0-9_.]*$"
        )


# ── OdooInterface ─────────────────────────────────────────────────────────────

class OdooInterface:
    """Async interface for Odoo ERP via JSON-RPC 2.0.

    Supports Odoo v16+ (Community and Enterprise).

    Attributes:
        config: Validated connection configuration.
        uid: Cached user ID after successful authentication.
        logger: Logger instance.

    Example:
        async with OdooInterface(
            url="https://myodoo.com",
            database="mydb",
            username="admin",
            password="secret",
        ) as odoo:
            await odoo.authenticate()
            partners = await odoo.search_read(
                "res.partner",
                domain=[("is_company", "=", True)],
                fields=["name", "email", "phone"],
                limit=10,
            )
    """

    def __init__(
        self,
        url: str | None = None,
        database: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: int | None = None,
        verify_ssl: bool | None = None,
    ) -> None:
        """Initialize OdooInterface.

        Falls back to ``parrot.conf`` values when parameters are not provided.

        Args:
            url: Odoo instance base URL.
            database: Odoo database name.
            username: Odoo login username.
            password: Odoo login password or API key.
            timeout: Request timeout in seconds (default 30).
            verify_ssl: Verify SSL certificates (default True).

        Raises:
            ValueError: If required parameters are missing both from kwargs
                and from ``parrot.conf``.
        """
        self.config = OdooConfig(
            url=url or ODOO_URL or "",
            database=database or ODOO_DATABASE or "",
            username=username or ODOO_USERNAME or "",
            password=password or ODOO_PASSWORD or "",
            timeout=timeout if timeout is not None else ODOO_TIMEOUT,
            verify_ssl=verify_ssl if verify_ssl is not None else ODOO_VERIFY_SSL,
        )
        self.uid: int | None = None
        self._session: aiohttp.ClientSession | None = None
        self.logger = logging.getLogger("OdooInterface")

    # ── Session Management ────────────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        """Lazily create and return the aiohttp ClientSession.

        Returns:
            An active ``aiohttp.ClientSession`` configured with timeout and SSL.
        """
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            connector = aiohttp.TCPConnector(ssl=self.config.verify_ssl)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
            )
        return self._session

    async def close(self) -> None:
        """Close the underlying aiohttp session explicitly."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ── Context Manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> "OdooInterface":
        """Enter the async context manager, creating the HTTP session.

        Returns:
            Self, ready for use.
        """
        await self._get_session()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the async context manager, closing the HTTP session.

        Args:
            exc_type: Exception type, if any.
            exc_val: Exception value, if any.
            exc_tb: Exception traceback, if any.
        """
        await self.close()

    # ── JSON-RPC Core ─────────────────────────────────────────────────────────

    async def _jsonrpc_call(
        self,
        service: str,
        method: str,
        args: list[Any],
    ) -> Any:
        """Build and dispatch a JSON-RPC 2.0 request.

        Args:
            service: Odoo service name ("common" or "object").
            method: Method to invoke on the service (e.g., "login", "execute_kw").
            args: Positional arguments for the method.

        Returns:
            The ``result`` field from the JSON-RPC response.

        Raises:
            OdooConnectionError: On network or HTTP errors.
            OdooRPCError: If the response contains an ``error`` field.
        """
        payload = JsonRpcRequest(
            params={
                "service": service,
                "method": method,
                "args": args,
            }
        ).model_dump()

        url = f"{self.config.url.rstrip('/')}/jsonrpc"
        session = await self._get_session()

        try:
            async with session.post(url, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except aiohttp.ClientError as exc:
            raise OdooConnectionError(
                f"Network error contacting Odoo at {url}: {exc}"
            ) from exc

        if "error" in data and data["error"] is not None:
            error = data["error"]
            raise OdooRPCError(
                f"Odoo RPC error [{error.get('code', '?')}]: "
                f"{error.get('message', 'Unknown error')}",
                error_data=error,
            )

        return data.get("result")

    # ── Authentication ────────────────────────────────────────────────────────

    async def authenticate(self) -> int:
        """Authenticate with Odoo and cache the user ID.

        Returns:
            The authenticated user ID (uid).

        Raises:
            OdooAuthenticationError: If credentials are invalid (uid is False/None).
            OdooRPCError: If Odoo returns a JSON-RPC error during login.
            OdooConnectionError: On network failures.
        """
        self.logger.info(
            "Authenticating to Odoo db=%r as user=%r",
            self.config.database,
            self.config.username,
        )
        uid = await self._jsonrpc_call(
            "common",
            "login",
            [self.config.database, self.config.username, self.config.password],
        )

        if not uid:
            raise OdooAuthenticationError(
                f"Authentication failed for user {self.config.username!r} "
                f"on database {self.config.database!r}."
            )

        self.uid = int(uid)
        self.logger.info("Authenticated successfully, uid=%d", self.uid)
        return self.uid

    # ── execute_kw ────────────────────────────────────────────────────────────

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Execute any Odoo model method via ``execute_kw``.

        Automatically authenticates on the first call if ``uid`` is not set.

        Args:
            model: Odoo model technical name (e.g., "res.partner").
            method: Method to call on the model (e.g., "search_read").
            args: Positional arguments for the model method.
            kwargs: Keyword arguments for the model method.

        Returns:
            The result returned by Odoo for the requested operation.

        Raises:
            ValueError: If the model name is invalid.
            OdooAuthenticationError: If auto-authentication fails.
            OdooRPCError: On Odoo-side errors.
            OdooConnectionError: On network failures.
        """
        _validate_model_name(model)

        if self.uid is None:
            await self.authenticate()

        self.logger.debug("execute_kw model=%r method=%r", model, method)

        return await self._jsonrpc_call(
            "object",
            "execute_kw",
            [
                self.config.database,
                self.uid,
                self.config.password,
                model,
                method,
                args or [],
                kwargs or {},
            ],
        )

    # ── CRUD Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _clean_kwargs(**kw: Any) -> dict[str, Any]:
        """Filter out None-valued entries from a kwargs dict.

        Args:
            **kw: Keyword arguments, possibly containing None values.

        Returns:
            A new dict with None entries removed.
        """
        return {k: v for k, v in kw.items() if v is not None}

    # ── CRUD Convenience Methods ──────────────────────────────────────────────

    async def search(
        self,
        model: str,
        domain: list | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[int]:
        """Search for record IDs matching the domain.

        Args:
            model: Odoo model technical name (e.g., "res.partner").
            domain: Odoo domain filter triplets, e.g. ``[("name", "=", "Bob")]``.
                Defaults to ``[]`` (all records).
            offset: Number of records to skip (pagination).
            limit: Maximum number of records to return.
            order: Sort order string, e.g. ``"name asc"``.

        Returns:
            A list of record IDs matching the domain.
        """
        kw = self._clean_kwargs(offset=offset, limit=limit, order=order)
        return await self.execute_kw(model, "search", [domain or []], kw)

    async def search_read(
        self,
        model: str,
        domain: list | None = None,
        fields: list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search and read records in a single call.

        Args:
            model: Odoo model technical name.
            domain: Odoo domain filter triplets. Defaults to ``[]``.
            fields: List of field names to return. Defaults to all fields.
            offset: Number of records to skip.
            limit: Maximum number of records to return.
            order: Sort order string.

        Returns:
            A list of dicts, one per matching record.
        """
        kw = self._clean_kwargs(fields=fields, offset=offset, limit=limit, order=order)
        return await self.execute_kw(model, "search_read", [domain or []], kw)

    async def read(
        self,
        model: str,
        ids: list[int],
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Read specific records by ID.

        Args:
            model: Odoo model technical name.
            ids: List of record IDs to read.
            fields: Field names to retrieve. Defaults to all fields.

        Returns:
            A list of dicts with the requested field values.
        """
        kw = self._clean_kwargs(fields=fields)
        return await self.execute_kw(model, "read", [ids], kw)

    async def create(
        self,
        model: str,
        values: dict[str, Any] | list[dict[str, Any]],
    ) -> int | list[int]:
        """Create one or more records.

        Args:
            model: Odoo model technical name.
            values: A single dict of field values to create one record, or
                a list of dicts to create multiple records in one call.

        Returns:
            The new record ID (int) when a single dict is provided, or a list
            of new record IDs when a list of dicts is provided.
        """
        return await self.execute_kw(model, "create", [values])

    async def write(
        self,
        model: str,
        ids: list[int],
        values: dict[str, Any],
    ) -> bool:
        """Update existing records.

        Args:
            model: Odoo model technical name.
            ids: List of record IDs to update.
            values: Dict of field names → new values.

        Returns:
            ``True`` on success.
        """
        return await self.execute_kw(model, "write", [ids, values])

    async def unlink(
        self,
        model: str,
        ids: list[int],
    ) -> bool:
        """Delete records by ID.

        Args:
            model: Odoo model technical name.
            ids: List of record IDs to delete.

        Returns:
            ``True`` on success.
        """
        return await self.execute_kw(model, "unlink", [ids])

    async def search_count(
        self,
        model: str,
        domain: list | None = None,
    ) -> int:
        """Return the count of records matching the domain.

        Args:
            model: Odoo model technical name.
            domain: Odoo domain filter. Defaults to ``[]``.

        Returns:
            Integer count of matching records.
        """
        return await self.execute_kw(model, "search_count", [domain or []])

    async def fields_get(
        self,
        model: str,
        attributes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get field definitions for a model.

        Args:
            model: Odoo model technical name.
            attributes: List of field attribute names to include in the
                response (e.g., ``["string", "type", "required"]``).
                Defaults to all attributes.

        Returns:
            A dict mapping field technical names to their attribute dicts.
        """
        kw = self._clean_kwargs(attributes=attributes)
        return await self.execute_kw(model, "fields_get", [], kw)
