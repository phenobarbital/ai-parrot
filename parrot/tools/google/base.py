"""Base classes for Google Workspace tools."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, Optional, Type, Union, List, Callable
from abc import abstractmethod

from pydantic import BaseModel, Field
from navconfig.logging import logging

from ..abstract import AbstractTool, AbstractToolArgsSchema
from ...interfaces.google import GoogleClient


class GoogleAuthMode:
    """Authentication modes available for Google tools."""

    SERVICE_ACCOUNT = "service_account"
    USER = "user"
    CACHED = "cached"


class GoogleToolArgsSchema(AbstractToolArgsSchema):
    """Base schema for Google tool arguments."""

    auth_mode: Optional[str] = Field(
        default=None,
        description="Authentication mode: 'service_account', 'user', or 'cached'."
    )
    scopes: Optional[Union[str, List[str]]] = Field(
        default=None,
        description="Optional override of the default scopes for this tool execution."
    )


class GoogleBaseTool(AbstractTool):
    """Base class for Google Workspace tools leveraging :class:`GoogleClient`."""

    name: str = "google_base"
    description: str = "Base Google Workspace tool"
    args_schema: Type[BaseModel] = GoogleToolArgsSchema
    return_direct: bool = False

    def __init__(
        self,
        credentials: Optional[Union[str, Dict[str, Any], Path]] = None,
        default_auth_mode: str = GoogleAuthMode.SERVICE_ACCOUNT,
        scopes: Optional[Union[str, List[str]]] = None,
        user_creds_cache_file: Optional[Union[str, Path]] = None,
        open_browser: bool = True,
        login_callback: Optional[Callable[[str], Optional[bool]]] = None,
        interactive_login_kwargs: Optional[Dict[str, Any]] = None,
        interactive_timeout: int = 300,
        **kwargs
    ):
        super().__init__(**kwargs)

        self.credentials = credentials
        self.default_auth_mode = default_auth_mode
        self.scopes = scopes if scopes is not None else 'all'
        self.user_creds_cache_file = (
            Path(user_creds_cache_file).expanduser().resolve()
            if isinstance(user_creds_cache_file, (str, Path))
            else None
        )
        self.open_browser = open_browser
        self.login_callback = login_callback
        self.interactive_login_kwargs = interactive_login_kwargs or {}
        self.interactive_timeout = interactive_timeout

        self._client_cache: Dict[str, GoogleClient] = {}
        self.logger = logging.getLogger(f'Parrot.Tools.{self.__class__.__name__}')

    async def _execute(self, **kwargs) -> Any:  # type: ignore[override]
        auth_mode = kwargs.pop('auth_mode', None)
        scopes_override = kwargs.pop('scopes', None)
        client = await self._get_client(auth_mode=auth_mode, scopes=scopes_override)
        return await self._execute_google_operation(client=client, **kwargs)

    async def _get_client(
        self,
        auth_mode: Optional[str] = None,
        scopes: Optional[Union[str, List[str]]] = None
    ) -> GoogleClient:
        """Create or reuse a configured :class:`GoogleClient`."""

        resolved_auth_mode = auth_mode or self.default_auth_mode
        resolved_scopes = scopes if scopes is not None else self.scopes
        cache_key = self._build_cache_key(resolved_auth_mode, resolved_scopes)

        if cache_key in self._client_cache:
            return self._client_cache[cache_key]

        client_credentials: Optional[Union[str, Dict[str, Any], Path]]
        if isinstance(self.credentials, dict):
            client_credentials = self.credentials.copy()
        else:
            client_credentials = self.credentials

        client_kwargs: Dict[str, Any] = {}
        if self.user_creds_cache_file is not None:
            client_kwargs['user_creds_cache_file'] = self.user_creds_cache_file

        client = GoogleClient(
            credentials=client_credentials,
            scopes=resolved_scopes,
            **client_kwargs
        )

        if resolved_auth_mode == GoogleAuthMode.SERVICE_ACCOUNT:
            await client.initialize()
        elif resolved_auth_mode == GoogleAuthMode.USER:
            await client.interactive_login(
                scopes=resolved_scopes,
                open_browser=self.open_browser,
                login_callback=self.login_callback,
                timeout=self.interactive_timeout,
                **self.interactive_login_kwargs
            )
            await client.initialize()
        elif resolved_auth_mode == GoogleAuthMode.CACHED:
            try:
                await client.initialize()
            except RuntimeError as auth_error:
                if "User credentials not available" not in str(auth_error):
                    raise
                self.logger.info(
                    "No cached Google credentials found; launching interactive login"
                )
                await client.interactive_login(
                    scopes=resolved_scopes,
                    open_browser=self.open_browser,
                    login_callback=self.login_callback,
                    timeout=self.interactive_timeout,
                    **self.interactive_login_kwargs
                )
                await client.initialize()
        else:
            raise ValueError(f"Unsupported Google auth mode: {resolved_auth_mode}")

        self._client_cache[cache_key] = client
        return client

    def _build_cache_key(
        self,
        auth_mode: str,
        scopes: Optional[Union[str, List[str]]]
    ) -> str:
        normalized_scopes = self._normalize_scope_list(scopes)
        scope_fragment = ','.join(sorted(normalized_scopes)) if normalized_scopes else 'default'
        return f"{auth_mode}:{scope_fragment}"

    @staticmethod
    def _normalize_scope_list(scopes: Optional[Union[str, List[str]]]) -> List[str]:
        if scopes is None:
            return []
        return [scopes] if isinstance(scopes, str) else list(scopes)

    def clear_client_cache(self) -> None:
        """Clear cached client instances."""
        self._client_cache.clear()

    @abstractmethod
    async def _execute_google_operation(
        self,
        client: GoogleClient,
        **kwargs
    ) -> Any:
        """Execute the tool-specific Google API operation."""
