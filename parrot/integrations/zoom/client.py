import asyncio
import base64
import time
from typing import Any, Dict, Optional
import aiohttp
from navconfig.logging import logging

class ZoomUsInterface:
    """
    Interface for interacting with Zoom.us API via Server-to-Server OAuth.
    """
    BASE_URL = "https://api.zoom.us/v2"
    AUTH_URL = "https://zoom.us/oauth/token"

    def __init__(
        self,
        account_id: str,
        client_id: str,
        client_secret: str,
        logger: Optional[logging.Logger] = None
    ):
        self.account_id = account_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.logger = logger or logging.getLogger("ZoomUsInterface")
        self._token: Optional[str] = None
        self._token_expires_at: float = 0
        self._session: Optional[aiohttp.ClientSession] = None

    async def connect(self):
        """Initialize the session."""
        if not self._session:
            self._session = aiohttp.ClientSession()

    async def close(self):
        """Close the session."""
        if self._session:
            await self._session.close()
            self._session = None

    async def _get_access_token(self) -> str:
        """
        Get or refresh the Server-to-Server OAuth access token.
        """
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        if not self._session:
            await self.connect()

        auth_str = f"{self.client_id}:{self.client_secret}"
        b64_auth = base64.b64encode(auth_str.encode()).decode()

        params = {
            "grant_type": "account_credentials",
            "account_id": self.account_id,
        }
        headers = {
            "Authorization": f"Basic {b64_auth}",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        self.logger.debug("Requesting new Zoom access token...")
        async with self._session.post(self.AUTH_URL, params=params, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                self.logger.error(f"Failed to get Zoom token: {resp.status} - {text}")
                raise Exception(f"Failed to get Zoom token: {resp.status}")

            data = await resp.json()
            self._token = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            self._token_expires_at = time.time() + expires_in
            self.logger.info("Successfully obtained Zoom access token.")
            return self._token

    async def request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """
        Make an authenticated request to the Zoom API.
        """
        token = await self._get_access_token()
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        headers["Content-Type"] = "application/json"
        kwargs["headers"] = headers

        url = f"{self.BASE_URL}{endpoint}"

        if not self._session:
            await self.connect()

        async with self._session.request(method, url, **kwargs) as resp:
            if resp.status == 401:
                # Token might be expired, retry once
                self.logger.warning("Zoom API 401, retrying with new token...")
                self._token = None
                token = await self._get_access_token()
                headers["Authorization"] = f"Bearer {token}"
                async with self._session.request(method, url, **kwargs) as resp_retry:
                    return await self._handle_response(resp_retry)
            
            return await self._handle_response(resp)

    async def _handle_response(self, response: aiohttp.ClientResponse) -> Dict[str, Any]:
        """Handle response processing."""
        if response.status >= 400:
            text = await response.text()
            self.logger.error(f"Zoom API Error {response.status}: {text}")
            raise Exception(f"Zoom API Error {response.status}: {text}")
        
        try:
            return await response.json()
        except:
            return {}

    async def get_account_settings(self, option: str = None, **kwargs) -> Dict[str, Any]:
        """
        Get Account Settings.
        https://developers.zoom.us/docs/api/rest/reference/phone/methods/#operation/getAccountSettings
        """
        params = kwargs
        if option:
            params['option'] = option
            
        return await self.request("GET", "/phone/account_settings", params=params)
