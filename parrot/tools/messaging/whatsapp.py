"""WhatsApp Tool - Send and receive WhatsApp messages via whatsmeow bridge."""
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
import aiohttp
import asyncio
from navconfig.logging import logging

from ..abstract import AbstractTool
from ...conf import (
    WHATSAPP_BRIDGE_URL,
    WHATSAPP_BRIDGE_ENABLED,
    WHATSAPP_ALLOWED_PHONES,
    WHATSAPP_ALLOWED_GROUPS,
    WHATSAPP_COMMAND_PREFIX,
)


class WhatsAppSendInput(BaseModel):
    """Input schema for sending WhatsApp messages."""
    phone: str = Field(
        ...,
        description="Phone number in international format without + (e.g., '14155552671')"
    )
    message: str = Field(
        ...,
        description="Message content to send"
    )
    media_url: Optional[str] = Field(
        None,
        description="Optional media URL to send with the message"
    )


class WhatsAppTool(AbstractTool):
    """Send WhatsApp messages through the whatsmeow bridge.

    This tool communicates with the Go-based WhatsApp Bridge to send messages.
    The bridge handles authentication, session management, and message delivery.

    Features:
    - Send text messages
    - Send media (images, videos, documents)
    - Check connection status
    - Automatic reconnection handling

    Examples:
        # Send simple text message
        await tool.execute(
            phone="14155552671",
            message="Hello from AI-Parrot!"
        )

        # Send message with image
        await tool.execute(
            phone="14155552671",
            message="Check out this chart",
            media_url="https://example.com/chart.png"
        )
    """

    args_schema = WhatsAppSendInput

    def __init__(
        self,
        bridge_url: Optional[str] = None,
        timeout: int = 30,
        **kwargs
    ):
        """Initialize WhatsApp tool.

        Args:
            bridge_url: URL of the WhatsApp Bridge (default: from config).
            timeout: Request timeout in seconds.
            **kwargs: Additional arguments for AbstractTool.
        """
        super().__init__(**kwargs)
        self.name = "send_whatsapp"
        self.description = (
            "Send WhatsApp messages through the whatsmeow bridge. "
            "Supports text messages and media (images, videos, documents)."
        )
        self.bridge_url = (bridge_url or WHATSAPP_BRIDGE_URL).rstrip('/')
        self.timeout = timeout
        self.logger = logging.getLogger("Parrot.WhatsAppTool")
        # Store init kwargs for clone() support
        self._init_kwargs.update({
            "bridge_url": bridge_url,
            "timeout": timeout,
        })

    async def _check_bridge_health(self) -> Dict[str, Any]:
        """Check if the WhatsApp Bridge is healthy and connected."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.bridge_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return {"success": False, "error": f"Bridge returned {resp.status}"}
        except Exception as e:
            self.logger.error(f"Bridge health check failed: {e}")
            return {"success": False, "error": str(e)}

    async def _execute(
        self,
        phone: str,
        message: str,
        media_url: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Send WhatsApp message through the bridge.

        Args:
            phone: Phone number in international format without +.
            message: Message content.
            media_url: Optional media URL.
            **kwargs: Additional parameters.

        Returns:
            Dict with success status and message details.
        """
        # Check if bridge is enabled
        if not WHATSAPP_BRIDGE_ENABLED:
            return {
                "success": False,
                "error": "WhatsApp Bridge is disabled in configuration"
            }

        # Validate phone number format
        if not phone.isdigit():
            return {
                "success": False,
                "error": "Phone number must contain only digits (no + or spaces)"
            }

        # Check phone allowlist
        if WHATSAPP_ALLOWED_PHONES is not None:
            allowed = [
                p.strip() for p in WHATSAPP_ALLOWED_PHONES.split(',')
            ]
            if phone not in allowed:
                return {
                    "success": False,
                    "error": f"Phone {phone} is not in the allowed list"
                }

        # Check bridge health first
        health = await self._check_bridge_health()
        if not health.get("success"):
            return {
                "success": False,
                "error": f"Bridge is not available: {health.get('error')}"
            }

        data = health.get("data", {})
        if not data.get("connected") or not data.get("authenticated"):
            return {
                "success": False,
                "error": "WhatsApp not connected. Please authenticate using QR code."
            }

        # Prepare payload
        payload: Dict[str, str] = {
            "phone": phone,
            "message": message
        }
        if media_url:
            payload["media_url"] = media_url

        # Send message
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.bridge_url}/send",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as resp:
                    result = await resp.json()

                    if resp.status == 200 and result.get("success"):
                        self.logger.info(
                            f"Message sent to {phone}: {message[:50]}..."
                        )
                        return {
                            "success": True,
                            "message_id": result.get("data", {}).get("message_id"),
                            "timestamp": result.get("data", {}).get("timestamp"),
                            "phone": phone
                        }
                    error = result.get("error", "Unknown error")
                    self.logger.error(f"Failed to send message: {error}")
                    return {
                        "success": False,
                        "error": error
                    }

        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": f"Request timed out after {self.timeout}s"
            }
        except Exception as e:
            self.logger.error(f"Error sending WhatsApp message: {e}")
            return {
                "success": False,
                "error": str(e)
            }
