"""
UserSocketManager - WebSocket Manager with Redis PubSub for User Interactions.

This module provides a WebSocket manager that extends navigator's WebSocketManager
with features for:
- JWT-based authentication
- Redis-backed user info storage
- Geolocation tracking
- Channel-based messaging
- Direct user-to-user messaging
"""
import json
import asyncio
import logging
from typing import Dict, List, Any, Optional, Callable, Set
from datetime import datetime, timezone

from aiohttp import web
import redis.asyncio as aioredis
from navigator_auth.conf import exclude_list
from navigator.services.ws import WebSocketManager
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611

from ..conf import REDIS_SERVICES_URL


class UserSocketManager(WebSocketManager):
    """
    WebSocket Manager with Redis PubSub integration for per-user interactions.

    Features:
    - JWT authentication via msg_type="auth"
    - Configurable channel subscriptions
    - User info storage in Redis
    - Geolocation tracking
    - Direct messaging between users

    Usage:
    ```python
    from aiohttp import web
    from parrot.handlers.user import UserSocketManager

    app = web.Application()
    ws_manager = UserSocketManager(
        app,
        redis_url="redis://localhost:6379/4",
        default_channels=["information", "following", "alerts"]
    )

    # Optional: Register a custom message callback
    async def custom_handler(ws, channel, msg_type, content, username, client_info):
        print(f"Custom message from {username}: {content}")
        return True  # Return True to indicate message was handled

    ws_manager.register_message_handler(custom_handler)
    ```
    """

    # Default channels users are subscribed to on connection
    default_channels: List[str] = ["information", "following"]

    def __init__(
        self,
        app: web.Application,
        redis_url: str = None,
        default_channels: Optional[List[str]] = None,
        route_prefix: str = '/ws/user',
        **kwargs
    ):
        """
        Initialize the UserSocketManager.

        Args:
            app: aiohttp Application instance
            redis_url: Redis connection URL (default: REDIS_SERVICES_URL from conf)
            default_channels: List of channels to subscribe users to automatically
            route_prefix: URL prefix for WebSocket endpoint
            **kwargs: Additional arguments passed to WebSocketManager
        """
        super().__init__(app, route_prefix=route_prefix, **kwargs)
        # exclude from authentication middleware
        exclude_list.append(route_prefix)
        self.redis_url = redis_url or REDIS_SERVICES_URL
        self.redis: Optional[aioredis.Redis] = None
        self.pool: Optional[aioredis.ConnectionPool] = None

        if default_channels:
            self.default_channels = default_channels

        # User management
        self.authenticated_users: Dict[web.WebSocketResponse, Dict[str, Any]] = {}
        self.user_sockets: Dict[str, web.WebSocketResponse] = {}  # username -> ws
        self.pending_auth: Set[web.WebSocketResponse] = set()

        # PubSub management
        self.pubsub_tasks: List[asyncio.Task] = []
        self.channel_subscriptions: Dict[str, List[web.WebSocketResponse]] = {}

        # Custom message handlers
        self.custom_message_handlers: List[Callable] = []

        self.logger = logging.getLogger('UserSocketManager')
        self.logger.info(':: User WebSocket Manager initialized ::')

    async def _on_startup(self, app: web.Application):
        """Initialize Redis connection on application startup."""
        await super()._on_startup(app)

        try:
            self.pool = aioredis.ConnectionPool.from_url(
                self.redis_url,
                encoding='utf8',
                decode_responses=True,
                max_connections=5000
            )
            self.redis = aioredis.Redis(connection_pool=self.pool)
            await self.redis.ping()
            self.logger.info(':: Redis connection established ::')

            # Register default channels
            for channel in self.default_channels:
                self.register_channel(channel)
                self.channel_subscriptions[channel] = []

        except Exception as e:
            self.logger.error(f'Failed to connect to Redis: {e}')
            self.redis = None

    async def _on_shutdown(self, app: web.Application):
        """Cancel Redis PubSub tasks on shutdown."""
        # Cancel all running pubsub tasks
        for task in self.pubsub_tasks:
            if not task.done():
                task.cancel()
        try:
            await asyncio.gather(*self.pubsub_tasks, return_exceptions=True)
        except asyncio.CancelledError:
            pass

        # Call parent method to close WebSockets
        await super()._on_shutdown(app)

    async def _on_cleanup(self, app: web.Application):
        """Close Redis connection on cleanup."""
        await super()._on_cleanup(app)

        if self.redis:
            try:
                await asyncio.wait_for(self.redis.close(), timeout=2.0)
                if self.pool:
                    await self.pool.disconnect(inuse_connections=True)
                self.logger.info(':: Redis connection closed ::')
            except Exception as e:
                self.logger.error(f'Error closing Redis: {e}')

    def register_message_handler(self, handler: Callable):
        """
        Register a custom message handler callback.

        The handler signature should be:
        async def handler(ws, channel, msg_type, content, username, client_info) -> bool

        Return True to indicate the message was handled and should not be
        processed further.
        """
        self.custom_message_handlers.append(handler)

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    async def _validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validate JWT token and return user info.

        Args:
            token: JWT bearer token

        Returns:
            User info dict if valid, None otherwise
        """
        if not token:
            return None

        try:
            # Import SECRET_KEY and AUTH_JWT_ALGORITHM directly from navigator_auth
            # These are the same values used when creating tokens
            from navigator_auth.conf import SECRET_KEY, AUTH_JWT_ALGORITHM
            import jwt

            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[AUTH_JWT_ALGORITHM])
                return {
                    'user_id': payload.get('user_id', payload.get('sub')),
                    'username': payload.get('username', payload.get('preferred_username', 'user')),
                    'email': payload.get('email', ''),
                    'roles': payload.get('roles', []),
                    'raw_payload': payload
                }
            except jwt.ExpiredSignatureError:
                self.logger.warning('Token expired')
                return None
            except jwt.InvalidTokenError as e:
                self.logger.warning(f'Invalid token: {e}')
                return None

        except ImportError:
            # Fallback: accept any non-empty token for testing
            self.logger.warning('navigator_auth not available, using fallback validation')
            return {
                'user_id': 'test_user',
                'username': f'user_{token[:8]}',
                'email': 'test@example.com',
                'roles': []
            }

    async def _handle_auth(
        self,
        ws: web.WebSocketResponse,
        data: Dict[str, Any],
        client_info: Dict[str, Any]
    ) -> bool:
        """
        Handle authentication message.

        Args:
            ws: WebSocket response object
            data: Message data containing token
            client_info: Client connection info

        Returns:
            True if authentication successful
        """
        token = data.get('token', '')
        # Remove 'Bearer ' prefix if present
        if token.startswith('Bearer '):
            token = token[7:]

        user_info = await self._validate_token(token)

        if user_info:
            username = user_info['username']

            # Ensure unique username
            base_username = username
            counter = 1
            while username in self.user_sockets:
                username = f"{base_username}_{counter}"
                counter += 1
            user_info['username'] = username

            # Store authenticated user
            self.authenticated_users[ws] = user_info
            self.user_sockets[username] = ws
            self.pending_auth.discard(ws)

            # Store user info in Redis
            await self._store_user_info(username, user_info, client_info)

            # Subscribe to default channels
            subscribed_channels = []
            for channel in self.default_channels:
                await self._subscribe_to_channel(ws, channel)
                subscribed_channels.append(channel)

            # Send success response
            await ws.send_str(json_encoder({
                'type': 'auth_success',
                'username': username,
                'channels': subscribed_channels
            }))

            self.logger.info(f'User {username} authenticated successfully')
            return True
        else:
            await ws.send_str(json_encoder({
                'type': 'auth_error',
                'message': 'Invalid or expired token'
            }))
            return False

    async def _store_user_info(
        self,
        username: str,
        user_info: Dict[str, Any],
        client_info: Dict[str, Any]
    ):
        """Store user info in Redis."""
        if not self.redis:
            return

        try:
            key = f"user_socket:{username}"
            data = {
                'user_id': str(user_info.get('user_id', '')),
                'username': username,
                'email': user_info.get('email', ''),
                'connected_at': datetime.now(timezone.utc).isoformat(),
                'ip': client_info.get('ip', ''),
                'channels': json.dumps(self.default_channels)
            }
            await self.redis.hset(key, mapping=data)
            # Set TTL of 24 hours
            await self.redis.expire(key, 86400)
        except Exception as e:
            self.logger.error(f'Error storing user info: {e}')

    async def _remove_user_info(self, username: str):
        """Remove user info from Redis."""
        if not self.redis:
            return

        try:
            await self.redis.delete(f"user_socket:{username}")
            await self.redis.delete(f"user_location:{username}")
        except Exception as e:
            self.logger.error(f'Error removing user info: {e}')

    # -------------------------------------------------------------------------
    # Channel Management
    # -------------------------------------------------------------------------

    async def _subscribe_to_channel(self, ws: web.WebSocketResponse, channel_name: str):
        """
        Subscribe a client to a channel.

        Args:
            ws: WebSocket response object
            channel_name: Channel name to subscribe to
        """
        if channel_name not in self.channel_subscriptions:
            self.channel_subscriptions[channel_name] = []

        if ws not in self.channel_subscriptions[channel_name]:
            self.channel_subscriptions[channel_name].append(ws)

        user_info = self.authenticated_users.get(ws, {})
        username = user_info.get('username', 'Unknown')
        self.logger.debug(f'User {username} subscribed to channel {channel_name}')

    async def _unsubscribe_from_channel(self, ws: web.WebSocketResponse, channel_name: str):
        """
        Unsubscribe a client from a channel.

        Args:
            ws: WebSocket response object
            channel_name: Channel name to unsubscribe from
        """
        if channel_name in self.channel_subscriptions:
            if ws in self.channel_subscriptions[channel_name]:
                self.channel_subscriptions[channel_name].remove(ws)

        user_info = self.authenticated_users.get(ws, {})
        username = user_info.get('username', 'Unknown')
        self.logger.debug(f'User {username} unsubscribed from channel {channel_name}')

    async def broadcast_to_channel(
        self,
        channel: str,
        message: Dict[str, Any],
        exclude_ws: Optional[web.WebSocketResponse] = None
    ):
        """
        Broadcast a message to all subscribers of a channel.

        Args:
            channel: Channel name
            message: Message dict to send
            exclude_ws: Optional WebSocket to exclude from broadcast
        """
        if channel not in self.channel_subscriptions:
            return

        message_str = json_encoder(message)
        for ws in self.channel_subscriptions[channel]:
            if ws != exclude_ws and not ws.closed:
                try:
                    await ws.send_str(message_str)
                except Exception as e:
                    self.logger.error(f'Error broadcasting to channel {channel}: {e}')

    async def broadcast_to_all(
        self,
        message: Dict[str, Any],
        exclude_ws: Optional[web.WebSocketResponse] = None
    ):
        """
        Broadcast a message to all authenticated users.

        Args:
            message: Message dict to send
            exclude_ws: Optional WebSocket to exclude from broadcast
        """
        message_str = json_encoder(message)
        for ws in self.authenticated_users.keys():
            if ws != exclude_ws and not ws.closed:
                try:
                    await ws.send_str(message_str)
                except Exception as e:
                    self.logger.error(f'Error broadcasting: {e}')

    # -------------------------------------------------------------------------
    # Direct Messaging
    # -------------------------------------------------------------------------

    async def send_direct_message(
        self,
        from_username: str,
        to_username: str,
        content: Any
    ) -> bool:
        """
        Send a direct message to a specific user.

        Args:
            from_username: Sender username
            to_username: Recipient username
            content: Message content

        Returns:
            True if message was sent successfully
        """
        target_ws = self.user_sockets.get(to_username)
        if not target_ws or target_ws.closed:
            return False

        try:
            await target_ws.send_str(json_encoder({
                'type': 'direct',
                'from': from_username,
                'content': content,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }))
            return True
        except Exception as e:
            self.logger.error(f'Error sending direct message: {e}')
            return False

    def get_user_by_username(self, username: str) -> Optional[web.WebSocketResponse]:
        """Get WebSocket for a user by username."""
        return self.user_sockets.get(username)

    def get_online_users(self) -> List[str]:
        """Get list of all online usernames."""
        return list(self.user_sockets.keys())

    # -------------------------------------------------------------------------
    # Geolocation
    # -------------------------------------------------------------------------

    async def user_geolocation(
        self,
        username: str,
        latitude: float,
        longitude: float
    ):
        """
        Process and store user geolocation update.

        Args:
            username: User's username
            latitude: Latitude coordinate
            longitude: Longitude coordinate
        """
        if not self.redis:
            self.logger.warning('Redis not available for geolocation storage')
            return

        try:
            key = f"user_location:{username}"
            data = {
                'latitude': str(latitude),
                'longitude': str(longitude),
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            await self.redis.hset(key, mapping=data)
            # Set TTL of 1 hour for location data
            await self.redis.expire(key, 3600)

            self.logger.info(f'📍 Location received for {username}: lat={latitude}, lon={longitude}')
        except Exception as e:
            self.logger.error(f'Error storing geolocation: {e}')

    async def get_user_location(self, username: str) -> Optional[Dict[str, Any]]:
        """
        Get stored location for a user.

        Args:
            username: User's username

        Returns:
            Location dict or None
        """
        if not self.redis:
            return None

        try:
            data = await self.redis.hgetall(f"user_location:{username}")
            if data:
                return {
                    'latitude': float(data.get('latitude', 0)),
                    'longitude': float(data.get('longitude', 0)),
                    'updated_at': data.get('updated_at')
                }
        except Exception as e:
            self.logger.error(f'Error getting user location: {e}')

        return None

    # -------------------------------------------------------------------------
    # Message Handling Overrides
    # -------------------------------------------------------------------------

    async def on_connect(
        self,
        ws: web.WebSocketResponse,
        channel: str,
        client_info: Dict[str, Any],
        session: Any
    ):
        """
        Handle new WebSocket connection.

        Override parent method to mark connection as pending auth.
        Note: Signature matches parent: (ws, channel, client_info, session)
        """
        self.pending_auth.add(ws)

        # Send auth required message
        await ws.send_str(json_encoder({
            'type': 'auth_required',
            'message': 'Please authenticate with msg_type="auth" and your bearer token'
        }))

    async def on_message(
        self,
        ws: web.WebSocketResponse,
        channel: str,
        msg_type: str,
        msg_content: Any,
        username: str,
        client_info: Dict[str, Any],
        session: Any
    ):
        """
        Handle incoming WebSocket messages.

        Processes message types:
        - auth: JWT authentication
        - location: Geolocation update
        - message: Channel message
        - broadcast: Broadcast to all users
        - direct: Direct message to user
        - subscribe: Subscribe to channel
        - unsubscribe: Unsubscribe from channel

        Returns:
            True if message was handled
        """
        # Handle authentication
        if msg_type == 'auth':
            if isinstance(msg_content, dict):
                data = msg_content
            else:
                data = {'token': msg_content}
            return await self._handle_auth(ws, data, client_info)

        # All other messages require authentication
        if ws not in self.authenticated_users:
            await ws.send_str(json_encoder({
                'type': 'error',
                'message': 'Authentication required'
            }))
            return True

        user_info = self.authenticated_users[ws]
        auth_username = user_info['username']

        # Handle location update
        if msg_type == 'location':
            if isinstance(msg_content, dict):
                lat = msg_content.get('latitude')
                lon = msg_content.get('longitude')
                if lat is not None and lon is not None:
                    await self.user_geolocation(auth_username, float(lat), float(lon))
                    await ws.send_str(json_encoder({
                        'type': 'location_ack',
                        'status': 'received'
                    }))
                    return True

            await ws.send_str(json_encoder({
                'type': 'error',
                'message': 'Invalid location data. Expected {latitude, longitude}'
            }))
            return True

        # Handle channel message
        if msg_type == 'message':
            if isinstance(msg_content, dict):
                target_channel = msg_content.get('channel', channel)
                content = msg_content.get('content', msg_content)
            else:
                target_channel = channel
                content = msg_content

            await self.broadcast_to_channel(
                target_channel,
                {
                    'type': 'message',
                    'channel': target_channel,
                    'from': auth_username,
                    'content': content,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                },
                exclude_ws=ws
            )
            return True

        # Handle broadcast
        if msg_type == 'broadcast':
            if isinstance(msg_content, dict):
                content = msg_content.get('content', msg_content)
            else:
                content = msg_content

            await self.broadcast_to_all(
                {
                    'type': 'broadcast',
                    'from': auth_username,
                    'content': content,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                },
                exclude_ws=ws
            )
            return True

        # Handle direct message
        if msg_type == 'direct':
            if isinstance(msg_content, dict):
                target = msg_content.get('target')
                content = msg_content.get('content')
            else:
                await ws.send_str(json_encoder({
                    'type': 'error',
                    'message': 'Direct message requires {target, content}'
                }))
                return True

            if target and content:
                success = await self.send_direct_message(auth_username, target, content)
                if success:
                    await ws.send_str(json_encoder({
                        'type': 'direct_sent',
                        'to': target,
                        'status': 'delivered'
                    }))
                else:
                    await ws.send_str(json_encoder({
                        'type': 'direct_failed',
                        'to': target,
                        'status': 'user_offline'
                    }))
            return True

        # Handle subscribe
        if msg_type == 'subscribe':
            if isinstance(msg_content, dict):
                channel_name = msg_content.get('channel')
            else:
                channel_name = str(msg_content)

            if channel_name:
                await self._subscribe_to_channel(ws, channel_name)
                await ws.send_str(json_encoder({
                    'type': 'subscribed',
                    'channel': channel_name
                }))
            return True

        # Handle unsubscribe
        if msg_type == 'unsubscribe':
            if isinstance(msg_content, dict):
                channel_name = msg_content.get('channel')
            else:
                channel_name = str(msg_content)

            if channel_name:
                await self._unsubscribe_from_channel(ws, channel_name)
                await ws.send_str(json_encoder({
                    'type': 'unsubscribed',
                    'channel': channel_name
                }))
            return True

        # Handle get_users (list online users)
        if msg_type == 'get_users':
            users = self.get_online_users()
            await ws.send_str(json_encoder({
                'type': 'users_list',
                'users': users
            }))
            return True

        # Try custom message handlers
        for handler in self.custom_message_handlers:
            try:
                result = await handler(
                    ws, channel, msg_type, msg_content, auth_username, client_info
                )
                if result is True:
                    return True
            except Exception as e:
                self.logger.error(f'Error in custom message handler: {e}')

        # Unknown message type
        await ws.send_str(json_encoder({
            'type': 'error',
            'message': f'Unknown message type: {msg_type}'
        }))
        return True

    async def on_disconnect(
        self,
        ws: web.WebSocketResponse,
        channel: str,
        client_info: Dict[str, Any]
    ):
        """Handle client disconnection."""
        # Clean up authenticated user
        if ws in self.authenticated_users:
            user_info = self.authenticated_users[ws]
            username = user_info.get('username')

            # Remove from user sockets
            if username and username in self.user_sockets:
                del self.user_sockets[username]
                await self._remove_user_info(username)

            del self.authenticated_users[ws]
            self.logger.info(f'User {username} disconnected')

        # Remove from pending auth
        self.pending_auth.discard(ws)

        # Remove from all channel subscriptions
        for channel_subs in self.channel_subscriptions.values():
            if ws in channel_subs:
                channel_subs.remove(ws)
