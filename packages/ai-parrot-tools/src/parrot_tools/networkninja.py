"""
NetworkNinja API Tool - Real World Implementation
Complete implementation for NetworkNinja batch processing API
"""
import os
from typing import Optional
from navconfig import config
from pydantic import BaseModel, Field
from .resttool import RESTTool
from . import ToolResult


# ============================================================================
# Configuration
# ============================================================================

# Environment from config or environment variable
NETWORKNINJA_ENV = config.get("NETWORKNINJA_ENV", "production")  # dev, staging, prod
NETWORKNINJA_API_KEY = config.get("NETWORKNINJA_API_KEY")
NETWORKNINJA_BASE_URL = config.get(
    "NETWORKNINJA_BASE_URL",
    "https://api.networkninja.com"
)


class NetworkNinjaArgsSchema(BaseModel):
    """Schema for NetworkNinja API calls."""
    action: str = Field(
        description="Action to perform: get_batch, get_batches"
    )
    batch_id: Optional[str] = Field(
        default=None,
        description="Batch ID for get_batch operation"
    )


class NetworkNinjaTool(RESTTool):
    """
    NetworkNinja Batch Processing API Tool.

    This tool provides access to NetworkNinja's batch processing capabilities.
    It automatically handles environment-based URL routing and provides
    convenient methods for batch operations.

    Natural Language Examples:
    - "please, run via GET get_batch for batch_id=xyz"
    - "list all completed batches"
    """

    name = "networkninja_api"
    description = """
    NetworkNinja Batch Processing API provides access to:
    - Batch status tracking
    - Batch data retrieval

    Use this tool when you need to:
    - Get batch information by ID
    - List batches
    """

    args_schema = NetworkNinjaArgsSchema

    # Environment-specific configuration
    ENV_PATHS = {
        "dev": "dev",
        "acceptance": "acceptance",
        "prod": "production"
    }

    def __init__(
        self,
        environment: str = NETWORKNINJA_ENV,
        api_key: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize NetworkNinja API tool.

        Args:
            environment: Environment (dev, staging, prod)
            api_key: API key for authentication
            **kwargs: Additional arguments
        """
        # Construct base URL with environment path
        env_path = self.ENV_PATHS.get(environment, "production")
        base_url = f"{NETWORKNINJA_BASE_URL}/{env_path}"
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            use_http2=True,  # Enable HTTP/2 for better performance
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Api-Key": NETWORKNINJA_API_KEY
            },
            **kwargs
        )
        self.environment = environment

    async def _execute(
        self,
        action: str,
        batch_id: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """
        Execute NetworkNinja API action.

        Args:
            action: Action to perform (get_batch, create_batch, etc.)
            batch_id: Batch ID for specific operations
            **kwargs: Additional arguments

        Returns:
            ToolResult with API response
        """
        # Route to appropriate method based on action
        action_map = {
            "get_batch": self._get_batch,
            "list_batches": self._list_batches,
        }

        handler = action_map.get(action)

        if not handler:
            return ToolResult(
                status="error",
                result=None,
                error=f"Unknown action: {action}. Available: {list(action_map.keys())}",
                metadata={"action": action}
            )

        # Call the appropriate handler
        return await handler(
            batch_id=batch_id,
            **kwargs
        )

    async def _get_batch(
        self,
        batch_id: str,
        **kwargs
    ) -> ToolResult:
        """Get batch by ID."""
        if not batch_id:
            return ToolResult(
                status="error",
                result=None,
                error="batch_id is required for get_batch",
                metadata={"action": "get_batch"}
            )

        return await self._make_request(
            endpoint="get_batch",
            method="GET",
            params={"batch_id": batch_id}
        )

    async def _list_batches(
        self,
        **kwargs
    ) -> ToolResult:
        """List batches with optional filters."""
        return await self._make_request(
            endpoint="get_batch",
            method="GET"
        )
