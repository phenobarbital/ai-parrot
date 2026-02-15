"""WhatsApp Redis Bridge Hook.

Listens to WhatsApp messages via Redis Pub/Sub (published by an external bridge)
and routes them to agents.

Based on user-provided implementation pattern.
"""
import asyncio
import json
from typing import Any, Dict, Optional, List

from navconfig.logging import logging

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
    """
    WhatsApp message listener via Redis Pub/Sub.
    
    Features:
    - Listens to 'whatsapp:messages' (configurable)
    - Filters by allowed_phones / allowed_groups
    - Supports command_prefix
    - Routes to specific agents based on keywords/phones via 'routes' config
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
        self._allowed_phones = set(config.allowed_phones) if config.allowed_phones else None
        self._allowed_groups = set(config.allowed_groups) if config.allowed_groups else None
        self._routes = config.routes or []

    async def start(self) -> None:
        if not aioredis:
            raise ImportError(
                "redis (with asyncio support) or aioredis is required for WhatsAppRedisHook. "
                "Install with: uv pip install redis"
            )
            
        redis_url = self._config.redis_url or "redis://localhost:6379"
        
        try:
            self._redis = await aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self._redis.ping()
            
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(self._config.channel)
            
            self._task = asyncio.create_task(self._listen_loop())
            self.logger.info(
                f"WhatsAppRedisHook '{self.name}' started on channel '{self._config.channel}'"
            )
        except Exception as exc:
            self.logger.error(f"Failed to start WhatsAppRedisHook: {exc}")
            raise

    async def stop(self) -> None:
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
                    
                    # Handle double-encoded JSON if necessary
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        self.logger.warning(f"Invalid JSON in Redis message: {data_str[:100]}")
                        continue
                        
                    await self._handle_message(data)
                except Exception as exc:
                    self.logger.error(f"Error processing Redis message: {exc}")
                    
        except asyncio.CancelledError:
            self.logger.debug("Redis listener loop cancelled")
        except Exception as exc:
            self.logger.error(f"Redis listener loop error: {exc}")
            # Simple restart logic handled by external supervisor or manual restart
            # Automatic restart could loop infinitely on auth errors

    async def _handle_message(self, data: Dict[str, Any]) -> None:
        """Process decoded message data."""
        from_phone = data.get("from")
        content = data.get("content", "")
        message_type = data.get("type", "text")
        is_group = data.get("is_group", False)
        group_name = data.get("group_name", "")
        # from_name = data.get("from_name", from_phone) # Optional usage
        
        # 1. Filters
        if self._allowed_phones and from_phone not in self._allowed_phones:
            return
            
        if is_group and self._allowed_groups and group_name not in self._allowed_groups:
            return

        # Only text supported for triggers currently
        if message_type != "text":
            return

        # Check prefix
        if self._config.command_prefix:
            if not content.startswith(self._config.command_prefix):
                return
            content = content[len(self._config.command_prefix):].strip()

        if not content:
            return

        # 2. Routing logic
        target_id = self.target_id  # Default
        
        # Check routes (first match wins)
        for route in self._routes:
            # Check phones
            route_phones = route.get("phones", [])
            if route_phones and from_phone in route_phones:
                target_id = route.get("target_id", target_id)
                break
                
            # Check keywords
            route_keywords = route.get("keywords", [])
            content_lower = content.lower()
            if route_keywords and any(k.lower() in content_lower for k in route_keywords):
                target_id = route.get("target_id", target_id)
                break

        # 3. Emit HookEvent
        event = self._make_event(
            event_type="whatsapp.redis.message",
            payload={
                "from": from_phone,
                "content": content,
                "is_group": is_group,
                "group_name": group_name,
                "raw_data": data,
                "reply_via_bridge": True # Signal that reply should go via bridge tool
            },
            task=content,
            target_id=target_id
        )
        
        self.logger.info(
            f"WhatsApp (Redis) trigger from {from_phone} -> {target_id or 'default'}"
        )
        await self.on_event(event)

