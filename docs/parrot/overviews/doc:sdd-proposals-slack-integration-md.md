---
type: Wiki Overview
title: 'Brainstorm: Mejoras a la Integración de Slack en AI-Parrot'
id: doc:sdd-proposals-slack-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'El `SlackAgentWrapper` actual expone agentes de AI-Parrot via Slack Events
  API y slash commands. El wrapper ya maneja: eventos `app_mention` y `message`, slash
  commands, verificación de URL challenge, autorización por canal, memoria conversacional
  por sesión (`InMemoryConversatio'
relates_to:
- concept: mod:parrot.loaders
  rel: mentions
---

# Brainstorm: Mejoras a la Integración de Slack en AI-Parrot

## Contexto

El `SlackAgentWrapper` actual expone agentes de AI-Parrot via Slack Events API y slash commands. El wrapper ya maneja: eventos `app_mention` y `message`, slash commands, verificación de URL challenge, autorización por canal, memoria conversacional por sesión (`InMemoryConversation`), y formateo de respuestas con Block Kit (markdown, código, tablas, imágenes).

Este documento detalla las mejoras necesarias para llevar la integración de Slack a producción, incluyendo seguridad, rendimiento, soporte para la nueva API de Agents & AI Apps de Slack, y paridad de funcionalidades con los wrappers existentes de MS Teams, Telegram y WhatsApp.

**Dependencias principales:**
- `slack-sdk >= 3.40.0` (soporte para Assistant APIs, `chat_stream()`, `assistant.threads.*`)
- `slack-bolt >= 1.21.1` (soporte para Assistant middleware — opcional, se puede usar raw API)
- `aiohttp` (ya existente en AI-Parrot)

**Archivos afectados:**
- `parrot/integrations/slack/wrapper.py` (principal)
- `parrot/integrations/slack/models.py` (configuración)
- `parrot/integrations/slack/__init__.py` (exports)
- `parrot/integrations/manager.py` (arranque)
- Nuevos módulos: `security.py`, `assistant.py`, `interactive.py`, `files.py`, `dedup.py`, `socket_handler.py`

---

## 1. Verificación de Firma de Slack (Seguridad — Crítico)

### Problema

El `SlackAgentConfig` ya tiene el campo `signing_secret`, pero el wrapper actual **no valida las requests entrantes**. Cualquier request HTTP que llegue al endpoint será procesada, lo que permite ataques de suplantación.

En comparación, MS Teams valida a través del BotFramework SDK (en `Adapter`), y Telegram lo resuelve internamente con aiogram al verificar el token del bot.

### Solución

Crear un módulo `parrot/integrations/slack/security.py` con la lógica de verificación HMAC-SHA256.

**Flujo de verificación:**
1. Extraer los headers `X-Slack-Request-Timestamp` y `X-Slack-Signature` de la request.
2. Rechazar requests con timestamp mayor a 5 minutos (protección contra replay attacks).
3. Construir el `sig_basestring` como `v0:{timestamp}:{body}`.
4. Computar HMAC-SHA256 usando el `signing_secret` como clave.
5. Comparar el hash computado con `X-Slack-Signature` usando `hmac.compare_digest` (timing-safe).

### Código de ejemplo

```python
# parrot/integrations/slack/security.py
"""Slack request signature verification."""
import hashlib
import hmac
import time
import logging
from typing import Mapping

logger = logging.getLogger("SlackSecurity")


def verify_slack_signature_raw(
    raw_body: bytes,
    headers: Mapping[str, str],
    signing_secret: str,
    max_age_seconds: int = 300,
) -> bool:
    """
    Verify that an incoming request actually comes from Slack.

    Uses HMAC-SHA256 to validate the X-Slack-Signature header against
    the request body and the app's signing secret.

    Args:
        raw_body: The raw request body bytes.
        headers: The request headers mapping.
        signing_secret: The Slack app's signing secret.
        max_age_seconds: Maximum allowed age of the request (default: 5 min).

    Returns:
        True if the request is verified, False otherwise.
    """
    if not signing_secret:
        logger.warning("No signing_secret configured — skipping verification")
        return True

    timestamp = headers.get("X-Slack-Request-Timestamp", "")
    signature = headers.get("X-Slack-Signature", "")

    if not timestamp or not signature:
        logger.warning("Missing Slack signature headers")
        return False

    # Replay attack protection
    try:
        if abs(time.time() - int(timestamp)) > max_age_seconds:
            logger.warning(
                "Slack request timestamp too old: %s (current: %s)",
                timestamp, int(time.time())
            )
            return False
    except ValueError:
        logger.warning("Invalid timestamp format: %s", timestamp)
        return False

    # Compute HMAC-SHA256 signature
    sig_basestring = f"v0:{timestamp}:{raw_body.decode('utf-8')}"

    computed = "v0=" + hmac.new(
        signing_secret.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(computed, signature):
        logger.warning("Slack signature verification failed")
        return False

    return True
```

### Integración en el wrapper

**Nota sobre el body**: `aiohttp` permite leer el body una sola vez con `request.read()`. Dado que luego necesitamos `request.json()`, leemos el body raw una vez, verificamos, y luego parseamos con `json.loads()`:

```python
async def _handle_events(self, request: web.Request) -> web.Response:
    raw_body = await request.read()

    # Verificación de firma ANTES de cualquier procesamiento
    if not verify_slack_signature_raw(raw_body, request.headers, self.config.signing_secret):
        return web.Response(status=401, text="Unauthorized")

    payload = json.loads(raw_body)

    if payload.get("type") == "url_verification":
        return web.json_response({"challenge": payload.get("challenge")})
    # ... resto del handler
```

---

## 2. De-duplicación de Eventos

### Problema

Slack reintenta el envío de eventos si no recibe una respuesta HTTP 200 en ~3 segundos. Esto puede causar que el agente procese el mismo mensaje múltiples veces, generando respuestas duplicadas.

Los reintentos se identifican por el header `X-Slack-Retry-Num` y `X-Slack-Retry-Reason` (generalmente `"http_timeout"`).

### Solución

Dos niveles de protección:

1. **Rechazo inmediato de reintentos** basado en el header `X-Slack-Retry-Num`.
2. **Cache de event IDs** para deduplicación robusta (útil con múltiples instancias).

### Código de ejemplo

```python
# parrot/integrations/slack/dedup.py
"""Event deduplication for Slack integration."""
import time
import asyncio
import logging
from typing import Dict

logger = logging.getLogger("SlackDedup")


class EventDeduplicator:
    """
    Tracks processed Slack event IDs to prevent duplicate processing.
    Uses an in-memory TTL cache. For multi-instance deployments,
    replace with RedisEventDeduplicator.
    """

    def __init__(self, ttl_seconds: int = 300, cleanup_interval: int = 60):
        self._seen: Dict[str, float] = {}
        self._ttl = ttl_seconds
        self._cleanup_interval = cleanup_interval
        self._cleanup_task: asyncio.Task | None = None

    async def start(self):
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self):
        if self._cleanup_task:
            self._cleanup_task.cancel()

    def is_duplicate(self, event_id: str) -> bool:
        if not event_id:
            return False
        now = time.time()
        if event_id in self._seen:
            logger.debug("Duplicate event detected: %s", event_id)
            return True
        self._seen[event_id] = now
        return False

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(self._cleanup_interval)
            cutoff = time.time() - self._ttl
            expired = [k for k, v in self._seen.items() if v < cutoff]
            for k in expired:
                del self._seen[k]


class RedisEventDeduplicator:
    """Redis-backed deduplication for multi-instance deployments."""

    def __init__(self, redis_pool, prefix: str = "slack:dedup:", ttl: int = 300):
        self._redis = redis_pool
        self._prefix = prefix
        self._ttl = ttl

    async def is_duplicate(self, event_id: str) -> bool:
        if not event_id:
            return False
        key = f"{self._prefix}{event_id}"
        was_set = await self._redis.set(key, "1", nx=True, ex=self._ttl)
        return not was_set

    async def start(self):
        pass

    async def stop(self):
        pass
```

### Integración en el wrapper

```python
class SlackAgentWrapper:
    def __init__(self, agent, config, app):
        # ... existente ...
        self._dedup = EventDeduplicator(ttl_seconds=300)

    async def _handle_events(self, request: web.Request) -> web.Response:
        # 1. Rechazar reintentos inmediatamente
        if request.headers.get("X-Slack-Retry-Num"):
            self.logger.debug(
                "Ignoring Slack retry #%s (reason: %s)",
                request.headers.get("X-Slack-Retry-Num"),
                request.headers.get("X-Slack-Retry-Reason", "unknown"),
            )
            return web.json_response({"ok": True})

        # 2. Verificación de firma
        raw_body = await request.read()
        if not verify_slack_signature_raw(raw_body, request.headers, self.config.signing_secret):
            return web.Response(status=401)

        payload = json.loads(raw_body)

        # 3. URL verification
        if payload.get("type") == "url_verification":
            return web.json_response({"challenge": payload.get("challenge")})

        # 4. Deduplicación por event_id
        event_id = payload.get("event_id")
        if self._dedup.is_duplicate(event_id):
            return web.json_response({"ok": True})

        # 5. Procesar evento ...
```

---

## 3. Respuesta dentro de 3 Segundos (Procesamiento Asíncrono)

### Problema

Slack requiere un HTTP 200 dentro de ~3 segundos. Si no lo recibe, reintenta el evento (hasta 3 veces). El wrapper actual ejecuta `_answer()` de forma síncrona antes de retornar la respuesta HTTP, lo que excede fácilmente los 3 segundos cuando se consulta un LLM.

En comparación:
- **Telegram**: aiogram maneja esto internamente con polling.
- **MS Teams**: El wrapper envía un typing indicator y procesa en background.
- **WhatsApp**: Retorna 200 y procesa con `asyncio.create_task`.

### Solución

Disparar el procesamiento del agente como un `asyncio.Task` y retornar HTTP 200 inmediatamente.

### Código de ejemplo

```python
async def _handle_events(self, request: web.Request) -> web.Response:
    # ... verificación, dedup, parsing ...

    event = payload.get("event", {})
    if event.get("type") not in {"app_mention", "message"}:
        return web.json_response({"ok": True})
    if event.get("subtype") == "bot_message":
        return web.json_response({"ok": True})

    channel = event.get("channel")
    if not channel or not self._is_authorized(channel):
        return web.json_response({"ok": True})

    text = (event.get("text") or "").strip()
    user = event.get("user") or "unknown"
    thread_ts = event.get("thread_ts") or event.get("ts")
    session_id = f"{channel}:{user}"
    files = event.get("files")

    # Procesar en background — retornar 200 inmediatamente
    asyncio.create_task(
        self._safe_answer(
            channel=channel, user=user, text=text,
            thread_ts=thread_ts, session_id=session_id, files=files,
        )
    )
    return web.json_response({"ok": True})


async def _safe_answer(self, **kwargs) -> None:
    """Wrapper with error handling + timeout for background execution."""
    try:
        await asyncio.wait_for(self._answer(**kwargs), timeout=120.0)
    except asyncio.TimeoutError:
        self.logger.error("Slack answer timed out after 120s")
        await self._post_message(
            kwargs["channel"],
            "The request took too long. Please try again.",
            thread_ts=kwargs.get("thread_ts"),
        )
    except Exception as exc:
        self.logger.error("Unhandled error in background Slack answer: %s", exc, exc_info=True)
        try:
            await self._post_message(
                kwargs["channel"],
                "Sorry, an unexpected error occurred.",
                thread_ts=kwargs.get("thread_ts"),
            )
        except Exception:
            self.logger.error("Failed to send error message to Slack")
```

### Consideración: Límite de concurrencia

```python
class SlackAgentWrapper:
    def __init__(self, ...):
        self._concurrency_semaphore = asyncio.Semaphore(10)

    async def _safe_answer(self, **kwargs):
        async with self._concurrency_semaphore:
            try:
                await asyncio.wait_for(self._answer(**kwargs), timeout=120.0)
            except asyncio.TimeoutError:
                # ... timeout handling
            except Exception as exc:
                # ... error handling
```

---

## 4. Socket Mode

### Problema

El modo actual (HTTP webhooks) requiere un endpoint público, complicando el desarrollo local. Telegram resuelve esto con polling (aiogram); Slack ofrece **Socket Mode** como alternativa WebSocket.

### Solución

Soporte dual: webhooks para producción, Socket Mode para desarrollo.

### Cambios en SlackAgentConfig

```python
@dataclass
class SlackAgentConfig:
    # ... campos existentes ...
    app_token: Optional[str] = None         # Para Socket Mode (xapp-...)
    connection_mode: str = "webhook"         # "webhook" | "socket"

    # Agents & AI Apps configuration
    enable_assistant: bool = False
    suggested_prompts: Optional[list[Dict[str, str]]] = None

    def __post_init__(self):
        # ... existente ...
        if not self.app_token:
            self.app_token = config.get(f"{self.name.upper()}_SLACK_APP_TOKEN")
        if self.connection_mode == "socket" and not self.app_token:
            raise ValueError(
                f"Socket Mode requires app-level token (xapp-...) for '{self.name}'."
            )
```

### Socket Mode Handler

```python
# parrot/integrations/slack/socket_handler.py
"""Socket Mode handler for Slack integration."""
import asyncio
import logging
from typing import TYPE_CHECKING

from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

if TYPE_CHECKING:
    from .wrapper import SlackAgentWrapper

logger = logging.getLogger("SlackSocketMode")


class SlackSocketHandler:
    """
    Handles Slack events via Socket Mode (WebSocket connection).

    Recommended for: local development, environments behind firewalls.
    For production, prefer webhook mode.
    """

    def __init__(self, wrapper: 'SlackAgentWrapper'):
        self.wrapper = wrapper
        self.client = SocketModeClient(
            app_token=wrapper.config.app_token,
            web_client=AsyncWebClient(token=wrapper.config.bot_token),
        )
        self.client.socket_mode_request_listeners.append(self._handle_request)

    async def start(self):
        logger.info("Starting Slack Socket Mode for '%s'", self.wrapper.config.name)
        await self.client.connect()
        logger.info("Slack Socket Mode connected for '%s'", self.wrapper.config.name)

    async def stop(self):
        await self.client.disconnect()

    async def _handle_request(self, client: SocketModeClient, req: SocketModeRequest):
        """Route Socket Mode requests to appropriate handlers."""
        # Acknowledge immediately (equivalent to HTTP 200)
        response = SocketModeResponse(envelope_id=req.envelope_id)
        await client.send_socket_mode_response(response)

        if req.type == "events_api":
            await self._handle_event(req.payload)
        elif req.type == "slash_commands":
            await self._handle_slash_command(req.payload)
        elif req.type == "interactive":
            await self._handle_interactive(req.payload)

    async def _handle_event(self, payload: dict):
        event = payload.get("event", {})
        event_type = event.get("type")

        # Deduplication
        event_id = payload.get("event_id")
        if self.wrapper._dedup.is_duplicate(event_id):
            return

        # Route assistant events
        if event_type == "assistant_thread_started" and self.wrapper.config.enable_assistant:
            asyncio.create_task(
                self.wrapper._assistant_handler.handle_thread_started(event, payload)
            )
            return

        if event_type == "assistant_thread_context_changed" and self.wrapper.config.enable_assistant:
            asyncio.create_task(
                self.wrapper._assistant_handler.handle_context_changed(event)
            )
            return

        # message.im for assistant threads
        if (event_type == "message" and event.get("channel_type") == "im"
                and self.wrapper.config.enable_assistant):
            if event.get("subtype") == "bot_message":
                return
            asyncio.create_task(
                self.wrapper._assistant_handler.handle_user_message(event)
            )
            return

        # Regular message handling
        if event_type not in {"app_mention", "message"}:
            return
        if event.get("subtype") == "bot_message":
            return

        channel = event.get("channel")
        if not channel or not self.wrapper._is_authorized(channel):
            return

        text = (event.get("text") or "").strip()
        user = event.get("user") or "unknown"
        thread_ts = event.get("thread_ts") or event.get("ts")
        files = event.get("files")

        asyncio.create_task(
            self.wrapper._safe_answer(
                channel=channel, user=user, text=text,
                thread_ts=thread_ts, session_id=f"{channel}:{user}", files=files,
            )
        )

    async def _handle_slash_command(self, payload: dict):
        channel = payload.get("channel_id", "")
        user = payload.get("user_id", "unknown")
        text = (payload.get("text") or "").strip()
        session_id = f"{channel}:{user}"
        response_url = payload.get("response_url")

        if text.lower() in {"help", "clear", "commands"} and response_url:
            from aiohttp import ClientSession
            async with ClientSession() as session:
                if text.lower() == "help":
                    body = {"response_type": "ephemeral", "text": self.wrapper._help_text()}
                elif text.lower() == "clear":
                    self.wrapper.conversations.pop(session_id, None)
                    body = {"response_type": "ephemeral", "text": "Conversation cleared."}
                else:
                    body = {"response_type": "ephemeral", "text": "Commands: help, clear, commands"}
                await session.post(response_url, json=body)
            return

        asyncio.create_task(
            self.wrapper._safe_answer(
                channel=channel, user=user, text=text,
                thread_ts=None, session_id=session_id,
            )
        )

    async def _handle_interactive(self, payload: dict):
        if hasattr(self.wrapper, '_interactive_handler'):
            await self.wrapper._interactive_handler.handle(payload)
```

### Integración en IntegrationBotManager

```python
async def _start_slack_bot(self, name: str, config: SlackAgentConfig):
    agent = await self._get_agent(config.chatbot_id, getattr(config, 'system_prompt_override', None))
    if not agent:
        return

    wrapper = SlackAgentWrapper(agent=agent, config=config, app=self.bot_manager.get_app())
    self.slack_bots[name] = wrapper

    if config.connection_mode == "socket":
        from .slack.socket_handler import SlackSocketHandler
        handler = SlackSocketHandler(wrapper)
        wrapper._socket_handler = handler
        task = asyncio.create_task(handler.start(), name=f"slack_socket_{name}")
        self._polling_tasks.append(task)
        self.logger.info(f"✅ Started Slack bot '{name}' (Socket Mode)")
    else:
        self.logger.info(f"✅ Started Slack bot '{name}' (Webhook Mode)")
```

### Configuración YAML

```yaml
agents:
  mi_agente_dev:
    kind: slack
    chatbot_id: hr_agent
    connection_mode: socket       # WebSocket — no necesita URL pública
    # app_token se toma de MI_AGENTE_DEV_SLACK_APP_TOKEN env var

  mi_agente_prod:
    kind: slack
    chatbot_id: hr_agent
    connection_mode: webhook      # HTTP — requiere endpoint público
    webhook_path: /api/slack/hr/events
```

---

## 5. Typing Indicator

### Problema

Cuando el agente procesa una solicitud, el usuario no recibe feedback visual. Comparación:
- **Telegram**: `bot.send_chat_action(ChatAction.TYPING)`
- **MS Teams**: `send_typing(turn_context)`
- **WhatsApp**: No soporta typing indicator nativo vía API.

Slack ofrece dos mecanismos:
1. **Mensaje efímero** — funciona siempre, universal.
2. **`assistant.threads.setStatus`** — requiere Agents & AI Apps feature (sección 8).

### Código de ejemplo

```python
# Opción A: Typing via mensaje efímero (universal)
async def _send_typing_indicator(
    self, channel: str, user: str, thread_ts: str | None = None,
):
    """Send ephemeral 'thinking' message visible only to the user."""
    payload = {
        "channel": channel,
        "user": user,
        "text": ":hourglass_flowing_sand: Thinking...",
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    headers = {
        "Authorization": f"Bearer {self.config.bot_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    async with ClientSession() as session:
        async with session.post(
            "https://slack.com/api/chat.postEphemeral",
            headers=headers,
            data=json.dumps(payload),
        ) as resp:
            return (await resp.json()).get("message_ts")


# Opción B: Assistant status (requiere Agents & AI Apps)
async def _set_assistant_status(
    self, channel: str, thread_ts: str,
    status: str = "is thinking...",
    loading_messages: list[str] | None = None,
):
    """
    Set the assistant status indicator in the Slack AI container.
    Requires Agents & AI Apps feature and assistant:write scope.
    Supports rotating loading_messages for personality.
    """
    payload = {
        "channel_id": channel,
        "thread_ts": thread_ts,
        "status": status,
    }
    if loading_messages:
        payload["loading_messages"] = loading_messages

    headers = {
        "Authorization": f"Bearer {self.config.bot_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    async with ClientSession() as session:
        async with session.post(
            "https://slack.com/api/assistant.threads.setStatus",
            headers=headers,
            data=json.dumps(payload),
        ) as resp:
            data = await resp.json()
            if not data.get("ok"):
                self.logger.warning("Failed to set assistant status: %s", data.get("error"))
```

### Integración en `_answer`

```python
async def _answer(self, channel, user, text, thread_ts, session_id, files=None):
    memory = self._get_or_create_memory(session_id)

    # Enviar typing indicator según modo
    if self.config.enable_assistant and thread_ts:
        await self._set_assistant_status(
            channel, thread_ts,
            status="is thinking...",
            loading_messages=[
                "Analyzing your question...",
                "Consulting the knowledge base...",
                "Preparing a response...",
            ],
        )
    else:
        await self._send_typing_indicator(channel, user, thread_ts)

    # ... procesar con el agente y responder
```

---

## 6. Manejo de Archivos e Imágenes Entrantes

### Problema

El wrapper actual solo procesa texto. Si un usuario sube un archivo (PDF, imagen, CSV), el evento contiene la metadata pero el wrapper la ignora.

Comparación:
- **Telegram**: `handle_photo()` y `handle_document()` descargan y procesan archivos.
- **MS Teams**: Attachments vienen como URLs que se descargan.
- **WhatsApp**: pywa descarga media via `message.download()`.

### Slack File API

Los archivos vienen en `event.files[]`. Descarga requiere autenticación via bot token. Desde 2024, Slack usa upload asíncrono (`files.getUploadURLExternal` + `files.completeUploadExternal`).

### Código de ejemplo

```python
# parrot/integrations/slack/files.py
"""File handling for Slack integration."""
import json
import logging
import tempfile

…(truncated)…
