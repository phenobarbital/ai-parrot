"""WhatsApp Redis Bridge Hook.

Listens to WhatsApp messages via Redis Pub/Sub (published by an external bridge)
and routes them to agents in AutonomousOrchestrator.

Based on BaseHook pattern for AI-Parrot.
"""
import asyncio
import json
from typing import Any, Dict, Optional

from .base import BaseHook
from .models import HookType, WhatsAppRedisHookConfig

try:
    import redis.asyncio as aioredis
except ImportError:
    try:
        import aioredis
    except ImportError:
        aioredis = None


class WhatsAppRedisHook(BaseHook):
    """WhatsApp message listener via Redis Pub/Sub.

    Features:
    - Listens to 'whatsapp:messages' (configurable)
    - Filters by allowed_phones / allowed_groups
    - Supports command_prefix
    - Routes to specific agents based on keywords/phones via 'routes' config
    - Auto-reply support with WhatsApp Bridge integration
    - Session management per phone number

    Example configuration::

        config = WhatsAppRedisHookConfig(
            name="whatsapp_hook",
            enabled=True,
            target_type="agent",
            target_id="CustomerServiceAgent",
            redis_url="redis://localhost:6379",
            channel="whatsapp:messages",
            command_prefix="!",
            allowed_phones=["14155552671", "34612345678"],
            auto_reply=True,
            routes=[
                {
                    "name": "sales",
                    "keywords": ["precio", "comprar", "venta"],
                    "target_id": "SalesAgent",
                    "target_type": "agent"
                },
                {
                    "name": "vip_customer",
                    "phones": ["14155551234"],
                    "target_id": "VIPAgent",
                    "target_type": "agent"
                }
            ]
        )
    """

    hook_type = HookType.WHATSAPP_REDIS

    def __init__(self, config: WhatsAppRedisHookConfig, **kwargs) -> None:
        super().__init__(
            name=config.name,
            enabled=config.enabled,
            target_type=config.target_type,
            target_id=config.target_id,
            metadata=config.metadata,
            **kwargs,
        )
        self._config = config
        self._redis: Optional[Any] = None
        self._pubsub: Optional[Any] = None
        self._task: Optional[asyncio.Task] = None

        # Pre-process filters
        self._allowed_phones = (
            set(config.allowed_phones) if config.allowed_phones else None
        )
        self._allowed_groups = (
            set(config.allowed_groups) if config.allowed_groups else None
        )
        self._routes = config.routes or []

        # For auto-reply functionality
        self._bridge_url = config.bridge_url

    async def start(self) -> None:
        """Start listening to Redis Pub/Sub for WhatsApp messages."""
        if not aioredis:
            raise ImportError(
                "redis (with asyncio support) or aioredis is required for "
                "WhatsAppRedisHook. Install with: uv pip install redis"
            )

        redis_url = self._config.redis_url

        try:
            self._redis = await aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._redis.ping()

            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(self._config.channel)

            self._task = asyncio.create_task(self._listen_loop())
            self.logger.info(
                f"WhatsAppRedisHook '{self.name}' started on "
                f"channel '{self._config.channel}'"
            )

            if self._config.auto_reply:
                self.logger.info(
                    f"Auto-reply enabled via bridge at {self._bridge_url}"
                )

        except Exception as exc:
            self.logger.error(f"Failed to start WhatsAppRedisHook: {exc}")
            raise

    async def stop(self) -> None:
        """Stop listening and cleanup resources."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._pubsub:
            await self._pubsub.unsubscribe(self._config.channel)
            await self._pubsub.close()

        if self._redis:
            await self._redis.close()

        self.logger.info(f"WhatsAppRedisHook '{self.name}' stopped")

    async def _listen_loop(self) -> None:
        """Main listening loop for Redis Pub/Sub."""
        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue

                try:
                    data_str = message["data"]
                    if isinstance(data_str, bytes):
                        data_str = data_str.decode("utf-8")

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        self.logger.warning(
                            f"Invalid JSON in Redis message: {data_str[:100]}"
                        )
                        continue

                    await self._handle_message(data)
                except Exception as exc:
                    self.logger.error(
                        f"Error processing Redis message: {exc}",
                        exc_info=True,
                    )

        except asyncio.CancelledError:
            self.logger.debug("Redis listener loop cancelled")
        except Exception as exc:
            self.logger.error(
                f"Redis listener loop error: {exc}", exc_info=True
            )

    async def _handle_message(self, data: Dict[str, Any]) -> None:
        """Process decoded message data and route to appropriate agent."""
        from_phone = data.get("from")
        content = data.get("content", "")
        message_type = data.get("type", "text")
        is_group = data.get("is_group", False)
        group_name = data.get("group_name", "")
        from_name = data.get("from_name", from_phone)
        message_id = data.get("message_id", "")

        # 1. Apply filters
        if self._allowed_phones and from_phone not in self._allowed_phones:
            self.logger.debug(
                f"Ignoring message from non-allowed phone: {from_phone}"
            )
            return

        if is_group and self._allowed_groups and group_name not in self._allowed_groups:
            self.logger.debug(
                f"Ignoring message from non-allowed group: {group_name}"
            )
            return

        # Only text messages supported for triggers
        if message_type != "text":
            self.logger.debug(
                f"Ignoring non-text message type: {message_type}"
            )
            return

        # 2. Check command prefix
        original_content = content
        if self._config.command_prefix:
            if not content.startswith(self._config.command_prefix):
                return
            content = content[len(self._config.command_prefix):].strip()

        if not content:
            return

        # 3. Routing logic — find best matching route
        target_id = self.target_id  # Default
        target_type = self.target_type  # Default
        matched_route = None
        content_lower = content.lower()

        # Check routes (first match wins)
        for route in self._routes:
            # Phone-based routing (highest priority)
            route_phones = route.get("phones", [])
            if route_phones and from_phone in route_phones:
                target_id = route.get("target_id", target_id)
                target_type = route.get("target_type", target_type)
                matched_route = route.get("name", "phone_match")
                break

            # Keyword-based routing
            route_keywords = route.get("keywords", [])
            if route_keywords and any(
                k.lower() in content_lower for k in route_keywords
            ):
                target_id = route.get("target_id", target_id)
                target_type = route.get("target_type", target_type)
                matched_route = route.get("name", "keyword_match")
                break

        # 4. Build session_id for conversation continuity
        session_id = f"whatsapp_{from_phone}"
        if is_group:
            session_id = f"whatsapp_group_{group_name}_{from_phone}"

        # 5. Emit HookEvent to orchestrator
        event = self._make_event(
            event_type="whatsapp.redis.message",
            payload={
                # User identification
                "from": from_phone,
                "from_name": from_name,
                "user_id": from_phone,
                # Message content
                "content": content,
                "original_content": original_content,
                "message_id": message_id,
                # Group info
                "is_group": is_group,
                "group_name": group_name,
                # Session management
                "session_id": session_id,
                # Routing info
                "matched_route": matched_route,
                # Auto-reply configuration
                "reply_via_bridge": self._config.auto_reply,
                "bridge_config": {
                    "phone": from_phone,
                    "bridge_url": self._bridge_url,
                    "auto_reply": self._config.auto_reply,
                },
                # Raw data for debugging
                "raw_data": data,
            },
            task=content,
        )

        # Override target from routing
        if target_id:
            event.target_id = target_id
        if target_type:
            event.target_type = target_type

        self.logger.info(
            f"\U0001f4f1 WhatsApp from {from_name} ({from_phone}): "
            f"'{content[:50]}...' -> {target_id or 'default'} "
            f"via {matched_route or 'default'}"
        )

        # Send event to orchestrator
        await self.on_event(event)

    async def send_reply(self, phone: str, message: str) -> bool:
        """Send a WhatsApp reply via the bridge.

        Typically called by the orchestrator after processing.

        Args:
            phone: Recipient phone number.
            message: Message content.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self._config.auto_reply:
            self.logger.debug("Auto-reply disabled, skipping send")
            return False

        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._bridge_url}/send",
                    json={"phone": phone, "message": message},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get("success"):
                            self.logger.info(f"\u2705 Reply sent to {phone}")
                            return True
                        self.logger.error(
                            f"Bridge returned error: {result.get('error')}"
                        )
                        return False
                    self.logger.error(
                        f"Bridge returned status {resp.status}"
                    )
                    return False

        except Exception as exc:
            self.logger.error(f"Failed to send WhatsApp reply: {exc}")
            return False
