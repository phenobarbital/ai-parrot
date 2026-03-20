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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from aiohttp import ClientSession

logger = logging.getLogger("SlackFiles")

PROCESSABLE_MIME_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "application/pdf",
    "text/plain", "text/csv", "text/markdown", "application/json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


async def download_slack_file(
    file_info: Dict[str, Any], bot_token: str, download_dir: Optional[str] = None,
) -> Optional[Path]:
    """Download a file from Slack using bot token authentication."""
    url = file_info.get("url_private_download") or file_info.get("url_private")
    if not url:
        return None

    mimetype = file_info.get("mimetype", "")
    if mimetype not in PROCESSABLE_MIME_TYPES:
        logger.info("Skipping unsupported: %s (%s)", file_info.get("name"), mimetype)
        return None

    filename = file_info.get("name", "unknown_file")
    dest = Path(download_dir or tempfile.mkdtemp()) / filename
    headers = {"Authorization": f"Bearer {bot_token}"}

    async with ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                logger.error("Download failed %s: HTTP %s", filename, resp.status)
                return None
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                async for chunk in resp.content.iter_chunked(8192):
                    f.write(chunk)

    logger.info("Downloaded: %s (%d bytes)", dest, dest.stat().st_size)
    return dest


async def extract_files_from_event(
    event: Dict[str, Any], bot_token: str,
) -> Tuple[List[Path], List[Dict[str, Any]]]:
    """Download all processable files from a Slack event."""
    files = event.get("files", [])
    if not files:
        return [], []

    downloaded, skipped = [], []
    for file_info in files:
        path = await download_slack_file(file_info, bot_token)
        (downloaded if path else skipped).append(path or file_info)
    return downloaded, skipped


async def upload_file_to_slack(
    bot_token: str, channel: str, file_path: Path,
    title: Optional[str] = None, thread_ts: Optional[str] = None,
    initial_comment: Optional[str] = None,
) -> bool:
    """
    Upload a file to Slack using the v2 async upload flow.
    Uses files.getUploadURLExternal + files.completeUploadExternal.
    """
    headers = {"Authorization": f"Bearer {bot_token}"}
    file_size = file_path.stat().st_size

    async with ClientSession() as session:
        # Step 1: Get upload URL
        async with session.get(
            "https://slack.com/api/files.getUploadURLExternal",
            headers=headers,
            params={"filename": file_path.name, "length": str(file_size)},
        ) as resp:
            data = await resp.json()
            if not data.get("ok"):
                logger.error("Get upload URL failed: %s", data.get("error"))
                return False
            upload_url, file_id = data["upload_url"], data["file_id"]

        # Step 2: Upload content
        with open(file_path, "rb") as f:
            async with session.post(upload_url, data=f) as resp:
                if resp.status != 200:
                    return False

        # Step 3: Complete upload
        complete = {
            "files": [{"id": file_id, "title": title or file_path.name}],
            "channel_id": channel,
        }
        if thread_ts:
            complete["thread_ts"] = thread_ts
        if initial_comment:
            complete["initial_comment"] = initial_comment

        async with session.post(
            "https://slack.com/api/files.completeUploadExternal",
            headers={**headers, "Content-Type": "application/json"},
            data=json.dumps(complete),
        ) as resp:
            data = await resp.json()
            return data.get("ok", False)
```

### Integración en _answer

```python
async def _answer(self, channel, user, text, thread_ts, session_id, files=None):
    memory = self._get_or_create_memory(session_id)

    # Procesar archivos adjuntos
    file_context = ""
    if files:
        downloaded, skipped = await extract_files_from_event(
            {"files": files}, self.config.bot_token
        )
        if downloaded:
            for fpath in downloaded:
                try:
                    from parrot.loaders import detect_and_load
                    content = await detect_and_load(fpath)
                    file_context += f"\n\n[File: {fpath.name}]\n{content}"
                except Exception as e:
                    self.logger.warning("Failed to load %s: %s", fpath, e)
        if skipped:
            file_context += f"\n\n({len(skipped)} file(s) skipped — unsupported format)"

    full_query = f"{text}\n\n--- Attached Files ---{file_context}" if file_context else text

    response = await self.agent.ask(
        full_query, memory=memory, output_mode=OutputMode.SLACK,
        session_id=session_id, user_id=user,
    )
    # ... format and send response
```

---

## 7. Block Kit Interactivo — Botones, Menús y Modals

### Problema

Block Kit es el sistema de UI de Slack (equivalente a Adaptive Cards en MS Teams, InlineKeyboardMarkup en Telegram). El wrapper actual genera bloques estáticos, pero no soporta **elementos interactivos**: botones, select menus, date pickers, ni modals.

MS Teams tiene un `FormOrchestrator` con formularios YAML y Adaptive Cards. Telegram tiene un `CallbackRegistry` con handlers por prefijo. Slack necesita un equivalente.

### Arquitectura

```
SlackAgentWrapper
├── _handle_events()           # Eventos de Slack
├── _handle_command()          # Slash commands
├── _handle_interactive()      # block_actions, view_submission, shortcuts
└── SlackInteractiveHandler
    ├── ActionRegistry         # Registro de handlers por action_id
    ├── handle_block_actions() # Botones, selects, etc.
    ├── handle_view_submission() # Modal submissions
    └── handle_shortcuts()     # Global/Message shortcuts
```

### Código de ejemplo

```python
# parrot/integrations/slack/interactive.py
"""Interactive Block Kit handler for Slack integration."""
import json
import logging
from typing import Callable, Dict, Optional
from aiohttp import web, ClientSession

logger = logging.getLogger("SlackInteractive")


class ActionRegistry:
    """Registry for Block Kit action handlers. Maps action_id patterns to handlers."""

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}
        self._prefix_handlers: Dict[str, Callable] = {}

    def register(self, action_id: str, handler: Callable):
        self._handlers[action_id] = handler

    def register_prefix(self, prefix: str, handler: Callable):
        self._prefix_handlers[prefix] = handler

    def get_handler(self, action_id: str) -> Optional[Callable]:
        if action_id in self._handlers:
            return self._handlers[action_id]
        for prefix, handler in self._prefix_handlers.items():
            if action_id.startswith(prefix):
                return handler
        return None


class SlackInteractiveHandler:
    """Handles all interactive payloads from Slack Block Kit."""

    def __init__(self, wrapper: 'SlackAgentWrapper'):
        self.wrapper = wrapper
        self.action_registry = ActionRegistry()
        self._register_defaults()

    def _register_defaults(self):
        self.action_registry.register_prefix("feedback_", self._handle_feedback)
        self.action_registry.register("clear_conversation", self._handle_clear)

    async def handle(self, request_or_payload) -> web.Response | None:
        """Entry point — accepts aiohttp Request (webhook) or dict (socket)."""
        if isinstance(request_or_payload, web.Request):
            form_data = await request_or_payload.post()
            payload = json.loads(form_data.get("payload", "{}"))
        else:
            payload = request_or_payload

        payload_type = payload.get("type")
        if payload_type == "block_actions":
            await self._handle_block_actions(payload)
        elif payload_type == "view_submission":
            await self._handle_view_submission(payload)
        elif payload_type in ("shortcut", "message_action"):
            await self._handle_shortcut(payload)

        if isinstance(request_or_payload, web.Request):
            return web.json_response({"ok": True})

    async def _handle_block_actions(self, payload: dict):
        for action in payload.get("actions", []):
            action_id = action.get("action_id", "")
            handler = self.action_registry.get_handler(action_id)
            if handler:
                await handler(payload, action)

    async def _handle_view_submission(self, payload: dict):
        callback_id = payload.get("view", {}).get("callback_id", "")
        handler = self.action_registry.get_handler(f"modal:{callback_id}")
        if handler:
            await handler(payload)

    async def _handle_shortcut(self, payload: dict):
        callback_id = payload.get("callback_id", "")
        handler = self.action_registry.get_handler(f"shortcut:{callback_id}")
        if handler:
            await handler(payload)

    # === Default handlers ===

    async def _handle_feedback(self, payload: dict, action: dict):
        feedback_type = action.get("action_id", "").replace("feedback_", "")
        user = payload.get("user", {}).get("id", "unknown")
        logger.info("Feedback: %s from %s", feedback_type, user)

        response_url = payload.get("response_url")
        if response_url:
            emoji = ":white_check_mark:" if feedback_type == "positive" else ":x:"
            async with ClientSession() as session:
                await session.post(response_url, json={
                    "response_type": "ephemeral",
                    "text": f"{emoji} Thanks for your feedback!",
                    "replace_original": False,
                })

    async def _handle_clear(self, payload: dict, action: dict):
        user = payload.get("user", {}).get("id", "unknown")
        channel = payload.get("channel", {}).get("id", "")
        self.wrapper.conversations.pop(f"{channel}:{user}", None)
        response_url = payload.get("response_url")
        if response_url:
            async with ClientSession() as session:
                await session.post(response_url, json={
                    "response_type": "ephemeral", "text": "Conversation cleared.",
                })
```

### Bloques de feedback reutilizables

```python
def build_feedback_blocks(message_id: str = "") -> list[dict]:
    """Feedback buttons to append to agent responses (like Slack's AI template)."""
    return [
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":thumbsup: Helpful"},
                    "action_id": "feedback_positive",
                    "value": message_id,
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":thumbsdown: Not helpful"},
                    "action_id": "feedback_negative",
                    "value": message_id,
                },
            ],
        },
    ]
```

### Modal de ejemplo (equivalente a Adaptive Card dialog)

```python
async def open_modal(self, trigger_id: str, form_definition: dict):
    """Open a Slack modal — equivalent to MS Teams Adaptive Card dialog."""
    view = {
        "type": "modal",
        "callback_id": form_definition.get("id", "generic_form"),
        "title": {"type": "plain_text", "text": form_definition.get("title", "Form")[:24]},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": self._build_form_blocks(form_definition.get("fields", [])),
    }
    headers = {
        "Authorization": f"Bearer {self.wrapper.config.bot_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    async with ClientSession() as session:
        await session.post(
            "https://slack.com/api/views.open",
            headers=headers,
            data=json.dumps({"trigger_id": trigger_id, "view": view}),
        )

def _build_form_blocks(self, fields: list[dict]) -> list[dict]:
    """Convert form field definitions to Block Kit input blocks."""
    blocks = []
    for field in fields:
        ft = field.get("type", "text")
        block = {
            "type": "input",
            "block_id": field["id"],
            "label": {"type": "plain_text", "text": field["label"]},
            "optional": field.get("optional", False),
        }
        if ft == "text":
            block["element"] = {
                "type": "plain_text_input", "action_id": field["id"],
                "multiline": field.get("multiline", False),
            }
        elif ft == "select":
            block["element"] = {
                "type": "static_select", "action_id": field["id"],
                "options": [
                    {"text": {"type": "plain_text", "text": o["label"]}, "value": o["value"]}
                    for o in field.get("options", [])
                ],
            }
        elif ft == "date":
            block["element"] = {"type": "datepicker", "action_id": field["id"]}
        blocks.append(block)
    return blocks
```

### Registro de ruta

```python
# En SlackAgentWrapper.__init__:
self._interactive_handler = SlackInteractiveHandler(self)
self.interactive_route = f"/api/slack/{safe_id}/interactive"
app.router.add_post(self.interactive_route, self._interactive_handler.handle)
if auth := app.get("auth"):
    auth.add_exclude_list(self.interactive_route)
```

---

## 8. Slack Agents & AI Apps (Assistant Container)

### Qué es

Slack ofrece una feature llamada **"Agents & AI Apps"** que proporciona una experiencia nativa de asistente de IA:

- **Entry point en la barra superior**: Los usuarios encuentran la app desde un punto de entrada dedicado.
- **Split view**: Conversación en panel lateral junto al canal actual (multitasking).
- **Tabs Chat e History**: Reemplazan el tab "Messages" en el App Home.
- **Suggested prompts**: Prompts dinámicos o estáticos al abrir un hilo (clickeables).
- **Loading states**: Shimmer UX y status indicators con mensajes rotativos personalizables.
- **Thread titles**: Títulos auto-generados para cada conversación, visibles en History tab.
- **Chat streaming**: Respuestas streameadas token por token (experiencia tipo ChatGPT) via `chat_stream()`.

### Eventos y APIs

| Evento / API | Descripción |
|---|---|
| `assistant_thread_started` | El usuario abre un nuevo hilo con el asistente |
| `assistant_thread_context_changed` | El usuario cambia de canal con el asistente abierto |
| `message.im` | Mensajes del usuario en el hilo del asistente |
| `assistant.threads.setStatus` | Estado de carga con loading_messages rotativas |
| `assistant.threads.setSuggestedPrompts` | Prompts sugeridos clickeables |
| `assistant.threads.setTitle` | Título del hilo (visible en History) |
| `chat.postMessage` + `thread_ts` | Responde en el hilo |
| `chat_stream()` helper | Streaming token por token (`startStream` → `appendStream` → `stopStream`) |

### Scopes y events requeridos

```
# OAuth Scopes
assistant:write    # APIs de assistant.threads.*
chat:write         # Enviar mensajes
im:history         # Leer historial de DMs

# Event Subscriptions (bot events)
assistant_thread_started
assistant_thread_context_changed
message.im
```

### Código de ejemplo: Assistant Handler

```python
# parrot/integrations/slack/assistant.py
"""
Slack Agents & AI Apps integration for AI-Parrot.

Implements the assistant container experience:
- Thread started → welcome + suggested prompts
- Context changed → update thread context
- User message → loading state → agent processing → streaming response
- Thread titles auto-generated from first message

Ref: https://api.slack.com/docs/apps/ai
Bolt Python: https://docs.slack.dev/tools/bolt-python/concepts/ai-apps/
SDK streaming: https://docs.slack.dev/tools/python-slack-sdk/reference/web/chat_stream.html
"""
import json
import asyncio
import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from aiohttp import ClientSession
from ..parser import parse_response
from ...models.outputs import OutputMode

if TYPE_CHECKING:
    from .wrapper import SlackAgentWrapper

logger = logging.getLogger("SlackAssistant")


class SlackAssistantHandler:
    """
    Handles Slack's Agents & AI Apps events.

    Provides native AI assistant experience with split-view panel,
    suggested prompts, loading states, thread titles, and streaming.
    """

    def __init__(self, wrapper: 'SlackAgentWrapper'):
        self.wrapper = wrapper
        self.config = wrapper.config
        self._thread_contexts: Dict[str, Dict[str, Any]] = {}

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.config.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    # === Event Handlers ===

    async def handle_thread_started(self, event: dict, payload: dict):
        """Handle assistant_thread_started — user opens the assistant container."""
        assistant_thread = event.get("assistant_thread", {})
        channel = assistant_thread.get("channel_id")
        thread_ts = assistant_thread.get("thread_ts")
        context = assistant_thread.get("context", {})

        if not channel or not thread_ts:
            return

        self._thread_contexts[thread_ts] = context

        # Welcome message
        welcome = self.config.welcome_message or "Hi! How can I help you today?"
        await self._post_message(channel, welcome, thread_ts=thread_ts)

        # Suggested prompts
        prompts = self.config.suggested_prompts or [
            {"title": "Summarize this channel", "message": "Summarize the recent discussion in this channel"},
            {"title": "Help me draft a message", "message": "Help me draft a professional message about"},
            {"title": "Explain a concept", "message": "Can you explain the following concept:"},
        ]
        await self._set_suggested_prompts(channel, thread_ts, prompts)

    async def handle_context_changed(self, event: dict):
        """Handle assistant_thread_context_changed — user switched channels."""
        assistant_thread = event.get("assistant_thread", {})
        thread_ts = assistant_thread.get("thread_ts")
        context = assistant_thread.get("context", {})
        if thread_ts:
            self._thread_contexts[thread_ts] = context

    async def handle_user_message(self, event: dict):
        """
        Handle message.im in an assistant thread.

        Flow:
        1. Set thread title (first message)
        2. Set loading status with rotating messages
        3. Process with AI-Parrot agent
        4. Stream or post response with feedback buttons
        """
        channel = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        text = (event.get("text") or "").strip()
        user = event.get("user") or "unknown"
        team = event.get("team")

        if not channel or not text:
            return

        session_id = f"assistant:{channel}:{user}"

        # 1. Set thread title
        await self._set_title(channel, thread_ts, text[:100])

        # 2. Set loading status
        await self._set_status(
            channel, thread_ts,
            status="is thinking...",
            loading_messages=[
                "Analyzing your question...",
                "Consulting the knowledge base...",
                "Preparing a thoughtful response...",
            ],
        )

        # 3. Process with agent
        memory = self.wrapper._get_or_create_memory(session_id)
        try:
            if hasattr(self.wrapper.agent, 'ask_stream') and team:
                await self._stream_response(
                    channel=channel, thread_ts=thread_ts, text=text,
                    user=user, team=team, memory=memory, session_id=session_id,
                )
            else:
                response = await self.wrapper.agent.ask(
                    text, memory=memory, output_mode=OutputMode.SLACK,
                    session_id=session_id, user_id=user,
                )
                parsed = parse_response(response)
                blocks = self.wrapper._build_blocks(parsed)
                from .interactive import build_feedback_blocks
                blocks.extend(build_feedback_blocks())
                await self._post_message(
                    channel, parsed.text or "Done.",
                    blocks=blocks, thread_ts=thread_ts,
                )
        except Exception as exc:
            logger.error("Assistant response error: %s", exc, exc_info=True)
            await self._clear_status(channel, thread_ts)
            await self._post_message(
                channel, "Sorry, I encountered an error. Please try again.",
                thread_ts=thread_ts,
            )

    async def _stream_response(
        self, channel: str, thread_ts: str, text: str,
        user: str, team: str, memory, session_id: str,
    ):
        """
        Stream the agent response using Slack's chat_stream API.

        Uses chat.startStream -> chat.appendStream -> chat.stopStream
        (via the slack-sdk chat_stream() helper).
        Provides ChatGPT-like streaming experience in Slack.
        """
        from slack_sdk.web.async_client import AsyncWebClient
        client = AsyncWebClient(token=self.config.bot_token)

        streamer = client.chat_stream(
            channel=channel,
            thread_ts=thread_ts,
            recipient_team_id=team,
            recipient_user_id=user,
        )

        try:
            async for chunk in self.wrapper.agent.ask_stream(
                text, memory=memory, output_mode=OutputMode.SLACK,
                session_id=session_id, user_id=user,
            ):
                content = getattr(chunk, 'content', chunk) if not isinstance(chunk, str) else chunk
                if content:
                    streamer.append(markdown_text=content)

            from .interactive import build_feedback_blocks
            streamer.stop(blocks=build_feedback_blocks())

        except Exception as exc:
            logger.error("Streaming error: %s", exc, exc_info=True)
            try:
                streamer.stop(markdown_text="\n\n:warning: An error occurred during generation.")
            except Exception:
                pass

    # === Slack API helpers ===

    async def _set_status(self, channel, thread_ts, status, loading_messages=None):
        payload = {"channel_id": channel, "thread_ts": thread_ts, "status": status}
        if loading_messages:
            payload["loading_messages"] = loading_messages
        async with ClientSession() as s:
            await s.post("https://slack.com/api/assistant.threads.setStatus",
                         headers=self._headers, data=json.dumps(payload))

    async def _clear_status(self, channel, thread_ts):
        await self._set_status(channel, thread_ts, status="")

    async def _set_title(self, channel, thread_ts, title):
        async with ClientSession() as s:
            await s.post("https://slack.com/api/assistant.threads.setTitle",
                         headers=self._headers,
                         data=json.dumps({"channel_id": channel, "thread_ts": thread_ts, "title": title}))

    async def _set_suggested_prompts(self, channel, thread_ts, prompts):
        async with ClientSession() as s:
            await s.post("https://slack.com/api/assistant.threads.setSuggestedPrompts",
                         headers=self._headers,
                         data=json.dumps({"channel_id": channel, "thread_ts": thread_ts, "prompts": prompts}))

    async def _post_message(self, channel, text, blocks=None, thread_ts=None):
        payload = {"channel": channel, "text": text}
        if blocks:
            payload["blocks"] = blocks
        if thread_ts:
            payload["thread_ts"] = thread_ts
        async with ClientSession() as s:
            await s.post("https://slack.com/api/chat.postMessage",
                         headers=self._headers, data=json.dumps(payload))
```

### Integración en el wrapper principal

```python
# En SlackAgentWrapper.__init__:
if self.config.enable_assistant:
    from .assistant import SlackAssistantHandler
    self._assistant_handler = SlackAssistantHandler(self)

# En _handle_events, agregar routing de eventos del assistant:
async def _handle_events(self, request: web.Request) -> web.Response:
    # ... verificación, dedup, parsing ...
    event = payload.get("event", {})
    event_type = event.get("type")

    # Assistant-specific events
    if event_type == "assistant_thread_started" and self.config.enable_assistant:
        asyncio.create_task(self._assistant_handler.handle_thread_started(event, payload))
        return web.json_response({"ok": True})

    if event_type == "assistant_thread_context_changed" and self.config.enable_assistant:
        asyncio.create_task(self._assistant_handler.handle_context_changed(event))
        return web.json_response({"ok": True})

    # message.im in assistant context
    if (event_type == "message" and event.get("channel_type") == "im"
            and self.config.enable_assistant):
        if event.get("subtype") == "bot_message":
            return web.json_response({"ok": True})
        asyncio.create_task(self._assistant_handler.handle_user_message(event))
        return web.json_response({"ok": True})

    # Regular events (app_mention, channel messages)
    # ... existing handling ...
```

### Configuración del Slack App Dashboard

1. **Sección "Agents & AI Apps"**: Activar el toggle, configurar overview text, elegir prompts estáticos o dinámicos.
2. **OAuth Scopes**: Agregar `assistant:write`.
3. **Event Subscriptions**: Agregar `assistant_thread_started`, `assistant_thread_context_changed`.
4. **Reinstalar la app** después de agregar scopes/features.

### Configuración YAML

```yaml
agents:
  hr_assistant:
    kind: slack
    chatbot_id: hr_agent
    connection_mode: webhook
    enable_assistant: true
    suggested_prompts:
      - title: "HR Policy Question"
        message: "What is the company policy on"
      - title: "Time Off Balance"
        message: "How many vacation days do I have remaining?"
      - title: "Benefits Info"
        message: "Can you explain our health insurance options?"
    welcome_message: "Hi! I'm your HR Assistant."
```

### Notas importantes

- **Requiere plan de pago de Slack** (Pro, Business+, Enterprise Grid). Se puede usar Sandbox del Developer Program.
- Publicación en Marketplace con `assistant:write` está **limitada a partners selectos**.
- **Socket Mode** OK para testing pero **no para producción** con esta feature.
- **Chat streaming** requiere `slack-sdk >= 3.40.0`.
- No almacenar datos de Slack. Guardar metadata y consultar datos en tiempo real si se necesitan.

---

## Resumen de Prioridades

| # | Feature | Prioridad | Complejidad | Dependencias |
|---|---------|-----------|-------------|--------------|
| 1 | Verificación de firma | **Crítica** | Baja | Ninguna nueva |
| 2 | De-duplicación de eventos | **Crítica** | Baja | Redis (opcional) |
| 3 | Respuesta < 3s (asyncio.create_task) | **Crítica** | Baja | Ninguna nueva |
| 4 | Socket Mode | Media | Media | `slack-sdk` |
| 5 | Typing Indicator | Media | Baja | Ninguna nueva |
| 6 | Manejo de archivos | Media | Media | Loaders existentes |
| 7 | Block Kit interactivo | Media | Alta | Ninguna nueva |
| 8 | Agents & AI Apps (Assistant) | Alta | Alta | `slack-sdk >= 3.40.0`, Slack paid plan |

### Orden de implementación sugerido

**Fase 1 — Seguridad y estabilidad (Sprint 1):**
Items 1, 2, 3 — Sin estos, el wrapper no es viable en producción.

**Fase 2 — UX básica (Sprint 2):**
Items 5, 6 — Typing indicators y archivos para paridad con otros wrappers.

**Fase 3 — Conectividad (Sprint 2-3):**
Item 4 — Socket Mode para simplificar desarrollo y testing.

**Fase 4 — Experiencia premium (Sprint 3-4):**
Items 7, 8 — Block Kit interactivo y Agents & AI Apps para la experiencia completa.

---

## Estructura de archivos propuesta

```
parrot/integrations/slack/
├── __init__.py              # Exports
├── models.py                # SlackAgentConfig (actualizado)
├── wrapper.py               # SlackAgentWrapper (refactorizado)
├── security.py              # Verificación de firma HMAC-SHA256
├── dedup.py                 # EventDeduplicator (in-memory + Redis)
├── files.py                 # Download/upload de archivos
├── interactive.py           # Block Kit interactivo + ActionRegistry
├── assistant.py             # Slack Agents & AI Apps handler
└── socket_handler.py        # Socket Mode handler
```

---

## Referencias

- Slack AI Apps docs: https://api.slack.com/docs/apps/ai
- Bolt for Python AI Apps: https://docs.slack.dev/tools/bolt-python/concepts/ai-apps/
- Slack SDK chat_stream: https://docs.slack.dev/tools/python-slack-sdk/reference/web/chat_stream.html
- assistant.threads.setStatus: https://api.slack.com/methods/assistant.threads.setStatus
- assistant.threads.setSuggestedPrompts: https://api.slack.com/methods/assistant.threads.setSuggestedPrompts
- Bolt Python Assistant template: https://github.com/slack-samples/bolt-python-assistant-template
- Slack Block Kit Builder: https://app.slack.com/block-kit-builder
- Slack Socket Mode: https://api.slack.com/apis/socket-mode