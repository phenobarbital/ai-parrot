"""
Office365 Tools for AI-Parrot.

Base classes and utilities for Office365 integration tools.
Supports multiple authentication modes:
- Direct (admin/client credentials)
- On-Behalf-Of (OBO)
- Delegated (interactive user login)
"""
from typing import Dict, Any, Optional, Type, List
from abc import abstractmethod
import contextlib
from datetime import datetime
import asyncio
from pydantic import BaseModel, Field
from navconfig.logging import logging
from ..abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
# Import your O365Client
from ...interfaces.o365 import O365Client


class O365AuthMode:
    """Authentication modes for Office365 tools."""
    DIRECT = "direct"  # Admin/App credentials
    OBO = "on_behalf_of"  # On-Behalf-Of flow
    DELEGATED = "delegated"  # Interactive user login
    CACHED = "cached"  # Use cached interactive session


class O365ToolArgsSchema(AbstractToolArgsSchema):
    """Base schema for Office365 tool arguments."""
    auth_mode: Optional[str] = Field(
        default=None,
        description="Authentication mode: 'direct', 'on_behalf_of', 'delegated', or 'cached'. If not provided, uses the tool's default_auth_mode."
    )
    user_assertion: Optional[str] = Field(
        default=None,
        description="User assertion token for OBO flow"
    )
    user_id: Optional[str] = Field(
        default=None,
        description=(
            "Target mailbox user principal name or ID. Required when using app-only "
            "(client credentials) authentication to access user-specific resources."
        )
    )


class O365Tool(AbstractTool):
    """
    Base class for Office365 tools that interact with Microsoft Graph API.

    This class provides:
    - Integration with O365Client
    - Multiple authentication modes
    - Error handling and logging
    - Async execution support

    Subclasses should implement:
    - _execute_graph_operation(): Perform the actual Graph API operation

    Authentication Modes:
    1. DIRECT: Uses client credentials (app-only access)
       - Best for: Admin operations, bulk operations
       - Requires: client_id, client_secret, tenant_id

    2. ON_BEHALF_OF: Uses OBO flow with user assertion
       - Best for: Acting on behalf of authenticated user
       - Requires: client_id, client_secret, tenant_id, user_assertion

    3. DELEGATED: Interactive user login
       - Best for: User-specific operations with full permissions
       - Requires: Interactive browser login

    4. CACHED: Reuse cached interactive session
       - Best for: Subsequent operations after interactive login
       - Requires: Previous interactive_login() call
    """

    name: str = "o365_base"
    description: str = "Base Office365 tool"
    args_schema: Type[BaseModel] = O365ToolArgsSchema
    return_direct: bool = False

    def __init__(
        self,
        credentials: Optional[Dict[str, Any]] = None,
        default_auth_mode: str = O365AuthMode.DIRECT,
        scopes: Optional[List[str]] = None,
        **kwargs
    ):
        """
        Initialize Office365 tool.

        Args:
            credentials: Dict with O365 credentials (client_id, client_secret, tenant_id, etc.)
            default_auth_mode: Default authentication mode to use
            scopes: List of Graph API scopes
            **kwargs: Additional arguments for AbstractTool
        """
        super().__init__(**kwargs)

        self.credentials = credentials or {}
        self.default_auth_mode = default_auth_mode
        self.scopes = scopes
        self._client: Optional[O365Client] = None
        self._client_cache: Dict[str, O365Client] = {}  # Cache clients by auth mode
        self._authenticated = False  # Track auth state
        self.logger = logging.getLogger(f'Parrot.Tools.{self.__class__.__name__}')

    async def _get_client(
        self,
        auth_mode: str = None,
        user_assertion: str = None,
        scopes: List[str] = None
    ) -> O365Client:
        """
        Get or create O365Client based on authentication mode.

        Args:
            auth_mode: Authentication mode to use
            user_assertion: User assertion for OBO flow
            scopes: Graph API scopes

        Returns:
            Configured O365Client instance
        """
        auth_mode = auth_mode or self.default_auth_mode
        scopes = scopes or self.scopes
        cache_key = f"{auth_mode}_{user_assertion or 'none'}"

        # Check cache
        if cache_key in self._client_cache:
            cached_client = self._client_cache[cache_key]
            cached_client.set_auth_mode(auth_mode)
            return cached_client

        # Create new client
        client_credentials = self.credentials.copy()

        # Handle OBO flow
        if auth_mode == O365AuthMode.OBO:
            if not user_assertion:
                raise ValueError("user_assertion is required for OBO authentication")
            client_credentials['assertion'] = user_assertion

        # Create and configure client
        client = O365Client(
            credentials=client_credentials
        )
        client.processing_credentials()
        client.set_auth_mode(auth_mode)

        try:
            if auth_mode == O365AuthMode.DIRECT:
                # Client credentials flow
                self.logger.info("Using direct (client credentials) authentication")
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    client.acquire_token,
                    scopes or self.scopes
                )

            elif auth_mode == O365AuthMode.OBO:
                # On-Behalf-Of flow
                self.logger.info("Using On-Behalf-Of authentication")
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    client.acquire_token_on_behalf_of,
                    user_assertion,
                    scopes or self.scopes
                )

            elif auth_mode == O365AuthMode.DELEGATED:
                if not self._authenticated:
                    await client.interactive_login(scopes=scopes)
                    self._authenticated = True
                else:
                    await client.ensure_interactive_session(scopes=scopes)
            elif auth_mode == O365AuthMode.CACHED:
                # Use cached session
                self.logger.info("Using cached interactive session")
                await client.ensure_interactive_session(scopes=scopes or self.scopes)

            else:
                raise ValueError(
                    f"Unknown authentication mode: {auth_mode}"
                )

            # Cache the client
            self._client_cache[cache_key] = client

            return client

        except Exception as e:
            self.logger.error(f"Failed to authenticate O365Client: {e}")
            raise

    @abstractmethod
    async def _execute_graph_operation(
        self,
        client: O365Client,
        **kwargs
    ) -> Any:
        """
        Execute the actual Graph API operation.

        Subclasses must implement this method to perform specific operations.

        Args:
            client: Authenticated O365Client instance
            **kwargs: Operation-specific parameters

        Returns:
            Operation result
        """
        pass

    async def _execute(self, **kwargs) -> ToolResult:
        """
        Execute the Office365 tool.

        This method handles:
        1. Authentication setup
        2. Calling the specific Graph operation
        3. Error handling
        4. Result formatting

        Args:
            **kwargs: Tool arguments including auth parameters

        Returns:
            ToolResult with operation outcome
        """
        start_time = datetime.now()

        try:
            # Extract auth parameters
            auth_mode = kwargs.pop('auth_mode', None) or self.default_auth_mode
            user_assertion = kwargs.pop('user_assertion', None)
            scopes = kwargs.pop('scopes', None) or self.scopes

            self.logger.debug(
                f"Executing with auth_mode={auth_mode}, "
                f"default_auth_mode={self.default_auth_mode}"
            )

            # Get authenticated client
            client = await self._get_client(
                auth_mode=auth_mode,
                user_assertion=user_assertion,
                scopes=scopes
            )

            # Execute the operation
            self.logger.info(f"Executing {self.name} operation")
            result = await self._execute_graph_operation(client, **kwargs)

            # Calculate execution time
            execution_time = (datetime.now() - start_time).total_seconds()

            return ToolResult(
                status="success",
                result=result,
                metadata={
                    "tool": self.name,
                    "auth_mode": auth_mode,
                    "execution_time": execution_time,
                    "timestamp": datetime.now().isoformat()
                }
            )

        except Exception as e:
            self.logger.error(f"Error executing {self.name}: {e}", exc_info=True)
            execution_time = (datetime.now() - start_time).total_seconds()

            return ToolResult(
                status="error",
                result=None,
                error=str(e),
                metadata={
                    "tool": self.name,
                    "execution_time": execution_time,
                    "timestamp": datetime.now().isoformat()
                }
            )

    async def cleanup(self):
        """Clean up resources."""
        for client in self._client_cache.values():
            try:
                await client.close()
            except Exception as e:
                self.logger.warning(f"Error closing client: {e}")
        self._client_cache.clear()
