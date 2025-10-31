from typing import AsyncGenerator, Dict, Any
import asyncio
from aiohttp import web
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from navigator.views import BaseHandler
from parrot.bots import AbstractBot


class StreamHandler(BaseHandler):
    """Streaming Endpoints for Parrot LLM Responses.

    Supports:
    - SSE (Server-Sent Events)
    - WebSockets
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.active_connections = set()

    def _get_botmanager(self, request: web.Request):
        """Retrieve the bot manager from the application context."""
        try:
            return request.app['bot_manager']
        except KeyError as e:
            raise web.HTTPInternalServerError(
                reason="Bot manager not found in application."
            ) from e

    def _get_bot(self, request: web.Request) -> AbstractBot:
        """Retrieve the bot instance based on bot_id from the request."""
        bot_manager = self._get_botmanager(request)
        bot_id = request.match_info.get('bot_id')
        bot = bot_manager.get_bot(bot_id)
        if bot is None:
            raise web.HTTPNotFound(
                reason=f"Bot with ID '{bot_id}' not found."
            )
        return bot

    def _extract_stream_params(self, payload: Dict[str, Any], *extra_ignored_keys: str):
        """Split incoming payload into prompt and kwargs for ask_stream."""
        ignored_keys = {"prompt", *extra_ignored_keys}
        prompt = payload.get('prompt', '')
        kwargs = {k: v for k, v in payload.items() if k not in ignored_keys}
        return prompt, kwargs

    async def stream_sse(self, request: web.Request) -> web.StreamResponse:
        """
        Server-Sent Events (SSE) streaming endpoint
        Best for: Unidirectional streaming, HTTP/1.1 compatible
        """
        data = await request.json()
        prompt, ask_kwargs = self._extract_stream_params(data)
        bot = self._get_bot(request)
        response = web.StreamResponse(
            status=200,
            reason='OK',
            headers={
                'Content-Type': 'text/event-stream',
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'Access-Control-Allow-Origin': '*',
                'X-Accel-Buffering': 'no',  # Disable nginx buffering
            }
        )
        await response.prepare(request)
        try:
            async for chunk in bot.ask_stream(prompt, **ask_kwargs):
                # Format as SSE
                sse_data = f"data: {json_encoder({'content': chunk})}\n\n"
                await response.write(sse_data.encode('utf-8'))
                await response.drain()

            # Send completion event
            await response.write(b"data: [DONE]\n\n")
            await response.drain()
        except asyncio.CancelledError as e:
            raise web.HTTPInternalServerError(
                reason="Client disconnected during streaming."
            ) from e
        except Exception as e:
            await response.write(
                f"error: {str(e)}\n\n".encode('utf-8')
            )
        finally:
            await response.write_eof()
        return response

    async def stream_ndjson(self, request: web.Request) -> web.StreamResponse:
        """
        NDJSON (Newline Delimited JSON) streaming endpoint
        Best for: Clients that can parse JSON lines, more flexible than SSE
        """
        data = await request.json()
        prompt, ask_kwargs = self._extract_stream_params(data)
        bot = self._get_bot(request)
        response = web.StreamResponse(
            status=200,
            reason='OK',
            headers={
                'Content-Type': 'application/x-ndjson',
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'Access-Control-Allow-Origin': '*',
            }
        )
        await response.prepare(request)
        try:
            async for chunk in bot.ask_stream(prompt, **ask_kwargs):
                # Each line is a complete JSON object
                line = json_encoder({
                    'type': 'content',
                    'data': chunk,
                    'timestamp': asyncio.get_event_loop().time()
                }) + '\n'
                await response.write(line.encode('utf-8'))
                await response.drain()

            # Send completion line
            await response.write(
                json_encoder({'done': True}).encode('utf-8') + b'\n'
            )
            await response.drain()
        except asyncio.CancelledError as e:
            raise web.HTTPInternalServerError(
                reason="Client disconnected during streaming."
            ) from e
        except Exception as e:
            error_line = json_encoder({'error': str(e)}) + '\n'
            await response.write(error_line.encode('utf-8'))
        finally:
            await response.write_eof()
        return response

    async def stream_chunked(self, request: web.Request) -> web.StreamResponse:
        """
        Plain chunked transfer encoding
        Best for: Simple text streaming without special formatting
        """
        data = await request.json()
        prompt, ask_kwargs = self._extract_stream_params(data)
        bot = self._get_bot(request)
        response = web.StreamResponse(
            status=200,
            reason='OK',
            headers={
                'Content-Type': 'text/plain; charset=utf-8',
                'Transfer-Encoding': 'chunked',
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'Access-Control-Allow-Origin': '*',
            }
        )
        await response.prepare(request)
        try:
            async for chunk in bot.ask_stream(prompt, **ask_kwargs):
                await response.write(chunk.encode('utf-8'))
                await response.drain()

            # Indicate end of stream
            await response.write_eof()
        except asyncio.CancelledError as e:
            raise web.HTTPInternalServerError(
                reason="Client disconnected during streaming."
            ) from e
        except Exception as e:
            await response.write(f"\n[ERROR]: {str(e)}\n".encode('utf-8'))
        finally:
            await response.write_eof()
        return response

    async def stream_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """
        WebSocket endpoint for bidirectional streaming
        Best for: Real-time bidirectional communication, chat applications
        """
        ws = web.WebSocketResponse(
            heartbeat=30.0,  # Send ping every 30s
            max_msg_size=10 * 1024 * 1024  # 10MB max message size
        )
        await ws.prepare(request)
        self.active_connections.add(ws)
        bot = self._get_bot(request)

        try:
            await ws.send_json({
                'type': 'connection',
                'status': 'connected',
                'message': 'WebSocket connection established'
            })

            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    # Handle incoming messages
                    try:
                        data = json_decoder(msg.data)
                        await self._handle_message(ws, data, bot)
                    except Exception:
                        await ws.send_json({
                            'type': 'error',
                            'message': 'Invalid JSON'
                        })
                elif msg.type == web.WSMsgType.ERROR:
                    # Handle errors
                    print(f'WebSocket error: {ws.exception()}')
                    self.active_connections.remove(ws)
        except Exception as e:
            self.active_connections.remove(ws)
            raise web.HTTPInternalServerError(
                reason="Error occurred during WebSocket communication."
            ) from e
        return ws

    async def _handle_message(self, ws: web.WebSocketResponse, data: dict, bot: AbstractBot):
        """Handle incoming WebSocket messages"""
        msg_type = data.get('type')

        if msg_type == 'stream_request':
            prompt, ask_kwargs = self._extract_stream_params(data, 'type')

            # Send acknowledgment
            await ws.send_json({
                'type': 'stream_start',
                'prompt': prompt
            })

            try:
                # Stream the LLM response
                async for chunk in bot.ask_stream(prompt, **ask_kwargs):
                    await ws.send_json({
                        'type': 'content',
                        'data': chunk
                    })

                # Send completion
                await ws.send_json({
                    'type': 'stream_complete'
                })

            except Exception as e:
                await ws.send_json({
                    'type': 'error',
                    'message': str(e)
                })

        elif msg_type == 'ping':
            await ws.send_json({'type': 'pong'})

        else:
            await ws.send_json({
                'type': 'error',
                'message': f'Unknown message type: {msg_type}'
            })

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                print(f"Error broadcasting to client: {e}")
