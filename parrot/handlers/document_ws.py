
import logging
from typing import Dict, Any, Optional

from aiohttp import web
from navigator.services.ws import WebSocketManager
from datamodel.parsers.json import json_encoder
from parrot.interfaces.documentdb import DocumentDb

class DocumentSocketManager(WebSocketManager):
    """
    DocumentSocketManager.
    
    WebSocket Interface for DocumentDB.
    Supports fire-and-forget and request-response patterns.
    """
    
    def __init__(self, app: web.Application, route_prefix: str = '/ws/data', **kwargs):
        super().__init__(app, route_prefix=route_prefix, **kwargs)
        self.logger = logging.getLogger('DocumentSocketManager')
        self.authenticated_users: Dict[web.WebSocketResponse, Dict[str, Any]] = {}

    async def _get_db(self, bucket: Optional[str] = None) -> DocumentDb:
        return DocumentDb(database=bucket)

    # -------------------------------------------------------------------------
    # Authentication (Shim from UserSocketManager)
    # -------------------------------------------------------------------------

    async def _validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        try:
            from navigator_auth.conf import SECRET_KEY, AUTH_JWT_ALGORITHM
            import jwt
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[AUTH_JWT_ALGORITHM])
                return payload
            except jwt.ExpiredSignatureError:
                self.logger.warning('Token expired')
                return None
            except jwt.InvalidTokenError as e:
                self.logger.warning(f'Invalid token: {e}')
                return None
        except ImportError:
             self.logger.warning('navigator_auth not available/configured properly')
             return None

    async def _handle_auth(self, ws: web.WebSocketResponse, data: Dict[str, Any]) -> bool:
        token = data.get('token', '')
        if token.startswith('Bearer '):
            token = token[7:]
        
        user_info = await self._validate_token(token)
        if user_info:
            self.authenticated_users[ws] = user_info
            await ws.send_str(json_encoder({
                'type': 'auth_success',
                'user': user_info.get('username', 'user')
            }))
            return True
        else:
            await ws.send_str(json_encoder({
                'type': 'auth_error',
                'message': 'Invalid token'
            }))
            return False

    async def on_connect(self, ws: web.WebSocketResponse, channel: str, client_info: Dict[str, Any], session: Any):
        # Allow connection but require auth for operations
        await ws.send_str(json_encoder({
            'type': 'auth_required',
            'message': 'Please authenticate with msg_type="auth"'
        }))
        
    async def on_disconnect(self, ws: web.WebSocketResponse, channel: str, client_info: Dict[str, Any]):
        if ws in self.authenticated_users:
            del self.authenticated_users[ws]

    async def on_message(
        self,
        ws: web.WebSocketResponse,
        channel: str,
        msg_type: str,
        msg_content: Any,
        username: str,
        client_info: Dict[str, Any], # Not used directly if we use internal auth
        session: Any
    ):
        # Handle Auth
        if msg_type == 'auth':
             if isinstance(msg_content, dict):
                 data = msg_content
             else:
                 data = {'token': msg_content}
             return await self._handle_auth(ws, data)

        # Check Auth
        if ws not in self.authenticated_users:
             await ws.send_str(json_encoder({
                 'type': 'error',
                 'message': 'Authentication required'
             }))
             return True
        
        # Dispatch Operations
        try:
            if msg_type == 'get':
                await self._handle_get(ws, msg_content)
            elif msg_type == 'put':
                await self._handle_put(ws, msg_content)
            elif msg_type == 'post':
                await self._handle_post(ws, msg_content)
            elif msg_type == 'patch':
                await self._handle_patch(ws, msg_content)
            elif msg_type == 'delete':
                await self._handle_delete(ws, msg_content)
            else:
                 await ws.send_str(json_encoder({
                     'type': 'error',
                     'message': f'Unknown msg_type: {msg_type}'
                 }))
        except Exception as e:
             await ws.send_str(json_encoder({
                 'type': 'error',
                 'message': f'Server Error: {e}'
             }))
        return True

    # -------------------------------------------------------------------------
    # Handlers
    # -------------------------------------------------------------------------
    
    async def _handle_get(self, ws, payload):
        """Handle GET (Query)"""
        # Payload: { bucket, collection, filter, limit, request_id }
        collection = payload.get('collection')
        bucket = payload.get('bucket')
        filter_query = payload.get('filter', {})
        limit = payload.get('limit', 100)
        req_id = payload.get('request_id')
        
        db = await self._get_db(bucket)
        async with db:
            results = await db.read(collection, query=filter_query, limit=limit)
            await ws.send_str(json_encoder({
                'type': 'get_response',
                'request_id': req_id,
                'data': results
            }))

    async def _handle_put(self, ws, payload):
        """Handle PUT (Insert)"""
        # Payload: { bucket, collection, data, request_id }
        collection = payload.get('collection')
        bucket = payload.get('bucket')
        data = payload.get('data')
        req_id = payload.get('request_id')
        
        if not data:
             await ws.send_str(json_encoder({'type': 'error', 'message': 'Missing data', 'request_id': req_id}))
             return

        db = await self._get_db(bucket)
        async with db:
            try:
                res = await db.write(collection, data)
                await ws.send_str(json_encoder({
                    'type': 'put_response',
                    'request_id': req_id,
                    'status': 203,
                    'result': res
                }))
            except Exception as e:
                 if "Duplicate" in str(e):
                      await ws.send_str(json_encoder({
                          'type': 'warning',
                          'request_id': req_id,
                          'message': 'Record already exists'
                      }))
                 else:
                      raise e

    async def _handle_post(self, ws, payload):
        """Handle POST (Update)"""
        # Payload: { bucket, collection, filter, data, request_id }
        collection = payload.get('collection')
        bucket = payload.get('bucket')
        filter_query = payload.get('filter')
        data = payload.get('data')
        req_id = payload.get('request_id')

        if not filter_query or not data:
             await ws.send_str(json_encoder({'type': 'error', 'message': 'Missing filter or data', 'request_id': req_id}))
             return

        db = await self._get_db(bucket)
        async with db:
            exists = await db.exists(collection, filter_query)
            if not exists:
                 await ws.send_str(json_encoder({
                     'type': 'error',
                     'request_id': req_id,
                     'message': 'Document not found'
                 }))
                 return

            update_data = {"$set": data} if not any(k.startswith('$') for k in data.keys()) else data
            await db.update(collection, filter_query, update_data)
            await ws.send_str(json_encoder({
                'type': 'post_response',
                'request_id': req_id,
                'status': 202,
                'message': 'Accepted'
            }))
            
    async def _handle_patch(self, ws, payload):
         """Handle PATCH (Partial Update) -> Same as POST"""
         await self._handle_post(ws, payload)

    async def _handle_delete(self, ws, payload):
        """Handle DELETE"""
        # Payload: { bucket, collection, filter, request_id }
        collection = payload.get('collection')
        bucket = payload.get('bucket')
        filter_query = payload.get('filter')
        req_id = payload.get('request_id')

        if not filter_query:
              await ws.send_str(json_encoder({'type': 'error', 'message': 'Missing filter', 'request_id': req_id}))
              return

        db = await self._get_db(bucket)
        async with db:
             res = await db.delete(collection, filter_query)
             await ws.send_str(json_encoder({
                 'type': 'delete_response',
                 'request_id': req_id,
                 'result': res
             }))
