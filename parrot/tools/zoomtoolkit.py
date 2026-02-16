from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from navconfig import config
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.decorators import tool_schema
from parrot.integrations.zoom.client import ZoomUsInterface


class GetAccountSettingsInput(BaseModel):
    """Input schema for get_account_settings."""
    option: Optional[str] = Field(
        None, 
        description="Optional parameter to filter settings (e.g., 'meeting_security', 'recording')."
    )


class ZoomUsToolkit(AbstractToolkit):
    """
    Toolkit for interacting with Zoom.us API.
    Wraps ZoomUsInterface to provide tools for AI agents.
    """
    
    def __init__(
        self,
        account_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        
        self.account_id = account_id or config.get("ZOOM_ACCOUNT_ID")
        self.client_id = client_id or config.get("ZOOM_CLIENT_ID")
        self.client_secret = client_secret or config.get("ZOOM_CLIENT_SECRET")
        
        if not all([self.account_id, self.client_id, self.client_secret]):
            self.logger.warning(
                "ZoomUsToolkit: Missing credentials. "
                "Ensure ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, and ZOOM_CLIENT_SECRET are set."
            )
            
        self.client = ZoomUsInterface(
            account_id=self.account_id,
            client_id=self.client_id,
            client_secret=self.client_secret,
            logger=self.logger
        )

    async def start(self):
        """Start the toolkit resources."""
        await self.client.connect()

    async def stop(self):
        """Stop the toolkit resources."""
        await self.client.close()
        
    async def cleanup(self):
        """Cleanup resources."""
        await self.stop()

    @tool_schema(GetAccountSettingsInput)
    async def get_account_settings(
        self,
        option: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get Zoom Phone Account Settings.
        
        Retrieves account-level settings for Zoom Phone.
        """
        try:
            return await self.client.get_account_settings(option=option)
        except Exception as e:
            self.logger.error(f"Error fetching account settings: {e}")
            return {"error": str(e)}
