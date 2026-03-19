# FilesystemTransport — Especificación Técnica

> **Para Claude Code** — Documento de referencia para implementar `FilesystemTransport` en AI-Parrot. Inspirado en [pi-messenger](https://github.com/nicobailon/pi-messenger): coordinación multi-agente sobre filesystem local, sin daemons ni servidores externos.

**Versión:** 0.1 · Draft · Febrero 2026

---

## Tabla de Contenidos

1. [Motivación](#1-motivación)
2. [Casos de Uso Target](#2-casos-de-uso-target)
3. [Comparativa con Transports Existentes](#3-comparativa-con-transports-existentes)
4. [Estructura de Módulos](#4-estructura-de-módulos)
5. [Estructura de Directorios en Disco](#5-estructura-de-directorios-en-disco)
6. [Modelos de Datos](#6-modelos-de-datos)
7. [Componentes — Especificación Detallada](#7-componentes--especificación-detallada)
8. [Integración con AI-Parrot](#8-integración-con-ai-parrot)
9. [CLI Overlay (HITL)](#9-cli-overlay-hitl)
10. [Configuración YAML](#10-configuración-yaml)
11. [Dependencias y Packaging](#11-dependencias-y-packaging)
12. [Compatibilidad de Plataforma](#12-compatibilidad-de-plataforma)
13. [Testing](#13-testing)
14. [Orden de Implementación](#14-orden-de-implementación)
15. [Decisiones de Diseño](#15-decisiones-de-diseño)

---

## 1. Motivación

AI-Parrot soporta actualmente múltiples canales de comunicación humano-agente y agente-agente: WebSockets con streaming JWT, WhatsApp via bridge Redis, el protocolo A2A HTTP, y MCP para distribución de tools. Todos comparten una característica: requieren infraestructura externa activa — un Redis, un servidor HTTP, un homeserver Matrix.

El **FilesystemTransport** surge de una observación simple: para desarrollo local, CI/CD, y entornos air-gapped, el filesystem es el bus de mensajes más confiable disponible.

**Principio central:** Para escenarios donde múltiples agentes AI-Parrot corren en el mismo host (o filesystem compartido), el sistema de archivos es suficiente como bus de mensajes. Zero deps, zero latencia de red, debug trivial con `cat` / `tail -f`, reproducibilidad total.

El diseño está inspirado en [pi-messenger](https://github.com/nicobailon/pi-messenger), que demuestra que coordinación multi-agente efectiva puede construirse sobre el filesystem sin ningún daemon. AI-Parrot adopta el mismo paradigma con extensiones: canales broadcast, reservaciones de recursos, y un CLI overlay para participación humana (HITL).

---

## 2. Casos de Uso Target

- Desarrollo y testing local de pipelines multi-agente sin infraestructura
- CI/CD pipelines donde múltiples agentes especializados colaboran en el mismo runner
- Entornos air-gapped o redes corporativas con restricciones de tráfico saliente
- "Dev mode" rápido antes de deployment con Matrix/Redis en producción
- Prototipado de orquestación multi-agente sin configurar Kubernetes

**Lo que NO es este transport:**
- No reemplaza Redis, Matrix, ni A2A para deployments multi-host
- No escala a más de un host (a menos de usar NFS/SMB como filesystem compartido)
- No recomendado para producción en entornos cloud

---

## 3. Comparativa con Transports Existentes

| Dimensión | A2A (HTTP) | WhatsApp/Redis | Matrix | FilesystemTransport |
|---|---|---|---|---|
| Deps externas | Servidor HTTP | Redis + Bridge | Homeserver | **Ninguna** |
| Escala | Multi-host | Multi-host | Federada | **Single-host** |
| Persistencia | Stateless | Ephemeral TTL | Histórico | **Archivos duraderos** |
| Debug | curl/logs | Redis CLI | Element | **`cat` / `tail -f`** |
| Setup time | Medio | Alto | Alto | **Segundos** |
| Producción | Sí | Sí | Sí | No recomendado |
| Human-in-loop | Difícil | WhatsApp | Nativo | **CLI overlay** |
| Discovery | `/.well-known` | Manual | Room directory | **Registry files** |

---

## 4. Estructura de Módulos

```
parrot/transport/filesystem/
├── __init__.py
├── config.py           # FilesystemTransportConfig (Pydantic)
├── transport.py        # FilesystemTransport — clase principal
├── registry.py         # AgentRegistry — presencia y discovery
├── inbox.py            # InboxManager — send / receive / poll
├── feed.py             # ActivityFeed — log append-only
├── channel.py          # ChannelManager — broadcast (rooms)
├── reservation.py      # ReservationManager — file locks declarativos
├── hook.py             # FilesystemHook — integración con BaseHook
└── cli.py              # CLI overlay — HITL en terminal
```

---

## 5. Estructura de Directorios en Disco

Todo el estado vive bajo `root_dir` (default: `.parrot/` en el cwd del proceso).

```
.parrot/
├── registry/                    # Presencia de agentes
│   ├── <agent-id>.json          # Registro de cada agente activo
│   └── .cleanup.lock            # Lock para GC de agentes muertos
│
├── inbox/                       # Mensajes pendientes por agente
│   └── <agent-id>/
│       ├── msg-<uuid>.json      # Mensaje pendiente (write-then-rename)
│       └── .processed/          # Mensajes ya leídos (para replay/auditoría)
│
├── feed.jsonl                   # Activity feed global, append-only
│
├── channels/                    # Canales broadcast (equivalente a rooms)
│   ├── general.jsonl            # Canal global
│   └── <channel-name>.jsonl     # Canales temáticos
│
├── reservations/                # Declaración de recursos en uso
│   └── <resource-hash>.json     # Quién tiene qué recurso reservado
│
└── .lock/                       # fcntl locks para operaciones atómicas
    └── feed.lock
```

### 5.1. Formato: registry/\<agent-id\>.json

```json
{
  "agent_id": "finance-agent-abc123",
  "name": "FinanceAgent",
  "pid": 12345,
  "hostname": "dev-machine.local",
  "cwd": "/home/user/myproject",
  "target_type": "agent",
  "model": "google:gemini-2.0-flash",
  "status": "active",
  "status_message": "Processing Q2 report...",
  "joined_at": "2026-02-22T10:00:00Z",
  "last_seen": "2026-02-22T10:05:30Z",
  "tool_calls": 42,
  "capabilities": ["tool_calling", "structured_output"],
  "channels": ["general", "finance-crew"]
}
```

### 5.2. Formato: inbox/\<agent-id\>/msg-\<uuid\>.json

```json
{
  "msg_id": "msg-550e8400-e29b-41d4-a716",
  "from_agent": "orchestrator-xyz",
  "from_name": "MainOrchestrator",
  "to_agent": "finance-agent-abc123",
  "channel": null,
  "type": "task",
  "content": "Analiza el Q2 y genera el reporte ejecutivo",
  "payload": {"context": "...", "output_format": "structured"},
  "reply_to": null,
  "created_at": "2026-02-22T10:05:00Z",
  "expires_at": "2026-02-22T11:05:00Z",
  "priority": 1
}
```

### 5.3. Formato: feed.jsonl (una línea por evento)

```jsonl
{"ts": "2026-02-22T10:00:00Z", "event": "join", "agent": "FinanceAgent", "agent_id": "finance-agent-abc123"}
{"ts": "2026-02-22T10:05:00Z", "event": "message", "from": "Orchestrator", "to": "FinanceAgent", "preview": "Analiza el Q2..."}
{"ts": "2026-02-22T10:07:30Z", "event": "broadcast", "from": "FinanceAgent", "channel": "general"}
{"ts": "2026-02-22T10:10:00Z", "event": "leave", "agent": "FinanceAgent"}
```

---

## 6. Modelos de Datos

### 6.1. FilesystemTransportConfig

```python
# parrot/transport/filesystem/config.py
from __future__ import annotations
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator


class FilesystemTransportConfig(BaseModel):
    """Configuración completa del FilesystemTransport."""

    # Directorio raíz
    root_dir: Path = Field(
        default=Path(".parrot"),
        description="Directorio raíz donde se almacena todo el estado"
    )

    # Presencia
    presence_interval: float = Field(
        default=10.0,
        description="Intervalo en segundos para actualizar heartbeat de presencia"
    )
    stale_threshold: float = Field(
        default=60.0,
        description="Segundos sin heartbeat para considerar agente muerto (stale)"
    )
    scope_to_cwd: bool = Field(
        default=False,
        description="Si True, solo ve agentes con el mismo cwd"
    )

    # Inbox / polling
    poll_interval: float = Field(
        default=0.5,
        description="Intervalo de polling en segundos (si inotify no está disponible)"
    )
    use_inotify: bool = Field(
        default=True,
        description="Usar watchdog/inotify para notificaciones inmediatas (sub-50ms)"
    )
    message_ttl: float = Field(
        default=3600.0,
        description="TTL de mensajes en segundos. 0 = sin expiración"
    )
    keep_processed: bool = Field(
        default=True,
        description="Mover mensajes procesados a .processed/ para replay/auditoría"
    )

    # Feed
    feed_retention: int = Field(
        default=500,
        description="Número máximo de eventos en el activity feed antes de rotar"
    )

    # Canales
    default_channels: List[str] = Field(
        default=["general"],
        description="Canales a los que el agente se suscribe automáticamente"
    )

    # Reservaciones
    reservation_timeout: float = Field(
        default=300.0,
        description="Timeout de reservación en segundos (se libera automáticamente)"
    )

    # Routing (para FilesystemHook)
    routes: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Reglas de routing por keywords o canal (patrón WhatsAppRedisHook)"
    )

    @field_validator("root_dir", mode="before")
    @classmethod
    def resolve_path(cls, v):
        return Path(v).resolve()
```

---

## 7. Componentes — Especificación Detallada

### 7.1. FilesystemTransport (Principal)

```python
# parrot/transport/filesystem/transport.py
from __future__ import annotations
import asyncio
import os
import socket
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from .config import FilesystemTransportConfig
from .registry import AgentRegistry
from .inbox import InboxManager
from .feed import ActivityFeed
from .channel import ChannelManager
from .reservation import ReservationManager


class FilesystemTransport:
    """
    Transport de comunicación multi-agente basado en filesystem local.

    Provee presencia, mensajería punto-a-punto, activity feed,
    canales broadcast, y reservaciones de recursos — sin dependencias externas.

    Uso básico::

        transport = FilesystemTransport(agent_name="FinanceAgent")
        async with transport:
            # Anunciar disponibilidad en el canal general
            await transport.broadcast("FinanceAgent online y disponible")

            # Escuchar mensajes entrantes
            async for msg in transport.messages():
                response = await agent.ask(msg["content"])
                await transport.send(
                    to=msg["from_name"],
                    content=response,
                    reply_to=msg["msg_id"],
                )

    Uso con context manager manual::

        transport = FilesystemTransport(agent_name="DataAgent")
        await transport.start()
        try:
            ...
        finally:
            await transport.stop()
    """

    def __init__(
        self,
        agent_name: str,
        agent_id: Optional[str] = None,
        config: Optional[FilesystemTransportConfig] = None,
        target_type: str = "agent",
    ):
        self.agent_name = agent_name
        self.agent_id = agent_id or f"{agent_name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}"
        self.config = config or FilesystemTransportConfig()
        self.target_type = target_type

        root = self.config.root_dir
        self._registry = AgentRegistry(root / "registry", self.config)
        self._inbox = InboxManager(root / "inbox", self.agent_id, self.config)
        self._feed = ActivityFeed(root / "feed.jsonl", self.config)
        self._channels = ChannelManager(root / "channels", self.config)
        self._reservations = ReservationManager(root / "reservations", self.agent_id)

        self._running = False
        self._presence_task: Optional[asyncio.Task] = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Registrar presencia e iniciar background tasks."""
        self.config.root_dir.mkdir(parents=True, exist_ok=True)

        await self._registry.join(
            agent_id=self.agent_id,
            name=self.agent_name,
            pid=os.getpid(),
            hostname=socket.gethostname(),
            cwd=str(Path.cwd()),
            target_type=self.target_type,
        )
        self._inbox.setup()
        await self._feed.emit("join", {"agent": self.agent_name, "agent_id": self.agent_id})

        self._running = True
        self._presence_task = asyncio.create_task(
            self._presence_loop(), name=f"presence_{self.agent_id}"
        )

    async def stop(self) -> None:
        """Desregistrar presencia y limpiar recursos."""
        self._running = False
        if self._presence_task:
            self._presence_task.cancel()
            try:
                await self._presence_task
            except asyncio.CancelledError:
                pass
        await self._reservations.release_all()
        await self._registry.leave(self.agent_id)
        await self._feed.emit("leave", {"agent": self.agent_name})

    @asynccontextmanager
    async def __aenter__(self):
        await self.start()
        try:
            yield self
        finally:
            await self.stop()

    async def __aexit__(self, *args):
        pass  # manejado por __aenter__

    # ── Messaging ──────────────────────────────────────────────────────────

    async def send(
        self,
        to: str,                          # agent_name o agent_id
        content: str,
        msg_type: str = "message",
        payload: Optional[Dict] = None,
        reply_to: Optional[str] = None,
    ) -> str:
        """
        Enviar mensaje directo a un agente.

        Retorna el msg_id generado.
        Lanza ValueError si el agente destino no está en el registry.
        """
        target = await self._registry.resolve(to)
        if not target:
            raise ValueError(f"Agent {to!r} not found in registry")

        msg_id = await self._inbox.deliver(
            from_agent=self.agent_id,
            from_name=self.agent_name,
            to_agent=target["agent_id"],
            content=content,
            msg_type=msg_type,
            payload=payload or {},
            reply_to=reply_to,
        )
        await self._feed.emit("message", {
            "from": self.agent_name,
            "to": to,
            "preview": content[:80],
        })
        return msg_id

    async def broadcast(
        self,
        content: str,
        channel: str = "general",
        payload: Optional[Dict] = None,
    ) -> None:
        """
        Emitir mensaje a un canal.

        Todos los agentes suscritos al canal lo reciben en su próximo poll.
        """
        await self._channels.publish(
            channel=channel,
            from_agent=self.agent_id,
            from_name=self.agent_name,
            content=content,
            payload=payload or {},
        )
        await self._feed.emit("broadcast", {
            "from": self.agent_name,
            "channel": channel,
        })

    async def messages(self) -> AsyncGenerator[Dict, None]:
        """
        AsyncGenerator que yield mensajes entrantes del inbox.

        Usa inotify/watchdog si disponible (latencia ~0ms),
        fallback a polling cada poll_interval segundos.
        El mensaje se mueve a .processed/ antes de hacer yield.
        """
        async for msg in self._inbox.poll():
            yield msg

    async def channel_messages(
        self, channel: str = "general", since_offset: int = 0
    ) -> AsyncGenerator[Dict, None]:
        """Yield mensajes de un canal broadcast desde un offset dado."""
        async for msg in self._channels.poll(channel, since_offset):
            yield msg

    # ── Discovery ──────────────────────────────────────────────────────────

    async def list_agents(self) -> List[Dict]:
        """Listar agentes activos (vivos según PID) en el registry."""
        return await self._registry.list_active()

    async def whois(self, name_or_id: str) -> Optional[Dict]:
        """Obtener info completa de un agente por nombre o agent_id."""
        return await self._registry.resolve(name_or_id)

    # ── Reservations ───────────────────────────────────────────────────────

    async def reserve(self, paths: List[str], reason: str = "") -> bool:
        """
        Reservar recursos (paths de archivos u otros identificadores).

        Retorna True si se adquirieron todas las reservas.
        Retorna False si algún recurso ya está reservado por otro agente.
        """
        ok = await self._reservations.acquire(paths, reason)
        if ok:
            await self._feed.emit("reserve", {
                "paths": paths,
                "agent": self.agent_name,
                "reason": reason,
            })
        return ok

    async def release(self, paths: Optional[List[str]] = None) -> None:
        """
        Liberar reservaciones.

        Sin paths = liberar todas las reservas del agente.
        """
        await self._reservations.release(paths)
        await self._feed.emit("release", {"agent": self.agent_name})

    # ── Status update ──────────────────────────────────────────────────────

    async def set_status(self, status: str, message: str = "") -> None:
        """Actualizar el status del agente en el registry (visible en CLI overlay)."""
        await self._registry.heartbeat(
            self.agent_id,
            status=status,
            status_message=message,
        )

    # ── Background tasks ───────────────────────────────────────────────────

    async def _presence_loop(self) -> None:
        """
        Heartbeat: actualiza last_seen en el registry y hace GC de agentes muertos.

        Corre cada presence_interval segundos mientras el transport está activo.
        """
        while self._running:
            try:
                await self._registry.heartbeat(self.agent_id)
                await self._registry.gc_stale()
            except Exception:
                pass  # No matar el loop por errores de I/O transitorios
            await asyncio.sleep(self.config.presence_interval)
```

### 7.2. AgentRegistry

```python
# parrot/transport/filesystem/registry.py
from __future__ import annotations
import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import aiofiles

from .config import FilesystemTransportConfig


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentRegistry:
    """
    Registro de presencia de agentes en el filesystem.

    Cada agente activo tiene un archivo JSON en registry/<agent-id>.json.
    La detección de agentes muertos usa PID: os.kill(pid, 0) verifica
    si el proceso existe sin enviarlo ninguna señal real.

    Garantías:
    - join() y leave() son write-then-rename (atómicos en POSIX)
    - gc_stale() elimina registros cuyo PID ya no existe en el sistema
    - list_active() solo retorna agentes vivos según PID
    - resolve() busca por agent_id o por name (case-insensitive)
    """

    def __init__(self, root: Path, config: FilesystemTransportConfig):
        self._root = root
        self._config = config
        self._root.mkdir(parents=True, exist_ok=True)

    async def join(
        self,
        agent_id: str,
        name: str,
        pid: int,
        hostname: str,
        cwd: str,
        target_type: str,
    ) -> None:
        record = {
            "agent_id": agent_id,
            "name": name,
            "pid": pid,
            "hostname": hostname,
            "cwd": cwd,
            "target_type": target_type,
            "status": "active",
            "status_message": "",
            "joined_at": _now(),
            "last_seen": _now(),
            "tool_calls": 0,
            "capabilities": [],
            "channels": list(self._config.default_channels),
        }
        await self._write(agent_id, record)

    async def leave(self, agent_id: str) -> None:
        path = self._root / f"{agent_id}.json"
        path.unlink(missing_ok=True)

    async def heartbeat(self, agent_id: str, **updates) -> None:
        """Actualizar last_seen y cualquier campo adicional."""
        rec = await self._read(agent_id) or {}
        rec.update({"last_seen": _now(), **updates})
        await self._write(agent_id, rec)

    async def list_active(self) -> List[Dict]:
        """Retornar todos los agentes vivos según PID."""
        agents = []
        for path in self._root.glob("*.json"):
            if path.name.startswith("."):
                continue
            rec = await self._read_path(path)
            if rec and self._is_alive(rec):
                if self._config.scope_to_cwd:
                    import os as _os
                    if rec.get("cwd") != str(Path.cwd()):
                        continue
                agents.append(rec)
        return agents

    async def resolve(self, name_or_id: str) -> Optional[Dict]:
        """Buscar agente por agent_id o por name (case-insensitive)."""
        for agent in await self.list_active():
            if agent["agent_id"] == name_or_id:
                return agent
            if agent["name"].lower() == name_or_id.lower():
                return agent
        return None

    async def gc_stale(self) -> List[str]:
        """Eliminar registros de agentes muertos. Retorna lista de IDs eliminados."""
        removed = []
        for path in self._root.glob("*.json"):
            if path.name.startswith("."):
                continue
            rec = await self._read_path(path)
            if rec and not self._is_alive(rec):
                path.unlink(missing_ok=True)
                removed.append(rec.get("agent_id", path.stem))
        return removed

    # ── Internals ─────────────────────────────────────────────────────────

    @staticmethod
    def _is_alive(rec: Dict) -> bool:
        """Verificar si el proceso sigue vivo via PID."""
        pid = rec.get("pid")
        if not pid:
            return False
        try:
            os.kill(pid, 0)   # signal 0 = solo comprobar existencia
            return True
        except ProcessLookupError:
            return False       # Proceso no existe
        except PermissionError:
            return True        # Proceso existe pero es de otro usuario

    async def _write(self, agent_id: str, data: Dict) -> None:
        """Escritura atómica via write-then-rename."""
        path = self._root / f"{agent_id}.json"
        tmp = self._root / f".tmp-{agent_id}.json"
        async with aiofiles.open(tmp, "w") as f:
            await f.write(json.dumps(data, ensure_ascii=False, default=str))
        tmp.rename(path)

    async def _read(self, agent_id: str) -> Optional[Dict]:
        return await self._read_path(self._root / f"{agent_id}.json")

    @staticmethod
    async def _read_path(path: Path) -> Optional[Dict]:
        try:
            async with aiofiles.open(path) as f:
                return json.loads(await f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return None
```

### 7.3. InboxManager

```python
# parrot/transport/filesystem/inbox.py
from __future__ import annotations
import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Dict, Optional

import aiofiles

from .config import FilesystemTransportConfig


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InboxManager:
    """
    Gestión del inbox de mensajes de un agente.

    Garantías de entrega:
    - Los mensajes se escriben en .tmp y luego se renombran (atómico POSIX)
    - El rename garantiza que el receptor nunca lee un mensaje parcial
    - El receptor mueve el mensaje a .processed/ antes de hacer yield
      (evita procesarlo dos veces en caso de reinicio)

    Polling vs inotify:
    - Si watchdog está instalado y use_inotify=True, se usa inotify/FSEvents
      para latencia sub-50ms (sin polling activo)
    - Fallback automático a polling cada poll_interval segundos
    """

    def __init__(
        self,
        inbox_root: Path,
        agent_id: str,
        config: FilesystemTransportConfig,
    ):
        self._root = inbox_root
        self._agent_id = agent_id
        self._my_inbox = inbox_root / agent_id
        self._processed = self._my_inbox / ".processed"
        self._config = config
        self._new_msg_event = asyncio.Event()
        self._watcher = None

    def setup(self) -> None:
        """Crear directorios y arrancar watcher si disponible."""
        self._my_inbox.mkdir(parents=True, exist_ok=True)
        if self._config.keep_processed:
            self._processed.mkdir(exist_ok=True)
        self._start_watcher()

    async def deliver(
        self,
        from_agent: str,
        from_name: str,
        to_agent: str,
        content: str,
        msg_type: str,
        payload: Dict,
        reply_to: Optional[str],
    ) -> str:
        """
        Entregar un mensaje al inbox del agente destino.

        Usa write-then-rename para garantizar atomicidad:
        el receptor nunca lee un archivo parcialmente escrito.
        """
        msg_id = f"msg-{uuid.uuid4().hex}"
        target_inbox = self._root / to_agent
        target_inbox.mkdir(parents=True, exist_ok=True)

        expires_at = None
        if self._config.message_ttl > 0:
            from datetime import timedelta
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=self._config.message_ttl)
            ).isoformat()

        msg = {
            "msg_id": msg_id,
            "from_agent": from_agent,
            "from_name": from_name,
            "to_agent": to_agent,
            "type": msg_type,
            "content": content,
            "payload": payload,
            "reply_to": reply_to,
            "created_at": _now(),
            "expires_at": expires_at,
        }

        tmp = target_inbox / f".tmp-{msg_id}.json"
        final = target_inbox / f"{msg_id}.json"

        async with aiofiles.open(tmp, "w") as f:
            await f.write(json.dumps(msg, ensure_ascii=False))
        tmp.rename(final)   # atómico en POSIX
        return msg_id

    async def poll(self) -> AsyncGenerator[Dict, None]:
        """
        AsyncGenerator que yield mensajes del inbox en orden de llegada.

        Mueve cada mensaje a .processed/ (o lo borra si keep_processed=False)
        antes de hacer yield para garantizar exactly-once delivery
        en caso de reinicio del agente.

        Filtra mensajes expirados silenciosamente.
        """
        while True:
            msgs = sorted(
                self._my_inbox.glob("msg-*.json"),
                key=lambda p: p.stat().st_mtime,
            )
            for path in msgs:
                try:
                    async with aiofiles.open(path) as f:
                        msg = json.loads(await f.read())

                    # Filtrar expirados
                    if msg.get("expires_at"):
                        exp = datetime.fromisoformat(msg["expires_at"])
                        if datetime.now(timezone.utc) > exp:
                            path.unlink(missing_ok=True)
                            continue

                    # Mover antes de yield (exactly-once)
                    if self._config.keep_processed:
                        dest = self._processed / path.name
                        path.rename(dest)
                    else:
                        path.unlink(missing_ok=True)

                    yield msg

                except (json.JSONDecodeError, OSError):
                    # Otro proceso lo procesó primero (race benigno) o I/O error
                    continue

            # Esperar hasta el próximo mensaje
            if self._config.use_inotify and self._new_msg_event:
                try:
                    await asyncio.wait_for(
                        self._new_msg_event.wait(),
                        timeout=self._config.poll_interval * 20,
                    )
                    self._new_msg_event.clear()
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(self._config.poll_interval)

    def _start_watcher(self) -> None:
        """Iniciar watchdog/inotify si disponible."""
        if not self._config.use_inotify:
            return
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            inbox_ref = self._my_inbox
            event_ref = self._new_msg_event

            class _Handler(FileSystemEventHandler):
                def on_created(self, event):
                    if not event.is_directory and event.src_path.endswith(".json"):
                        # Thread-safe: usar call_soon_threadsafe
                        try:
                            loop = asyncio.get_event_loop()
                            loop.call_soon_threadsafe(event_ref.set)
                        except RuntimeError:
                            pass

            self._watcher = Observer()
            self._watcher.schedule(
                _Handler(), str(self._my_inbox), recursive=False
            )
            self._watcher.start()
        except ImportError:
            pass  # Fallback a polling silenciosamente
```

### 7.4. ActivityFeed

```python
# parrot/transport/filesystem/feed.py
from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import aiofiles

from .config import FilesystemTransportConfig


class ActivityFeed:
    """
    Activity feed global append-only (feed.jsonl).

    Todos los eventos del sistema se escriben aquí:
    joins, leaves, mensajes, broadcasts, reservaciones.

    El feed rota automáticamente cuando supera feed_retention líneas,
    manteniendo solo las más recientes.

    Formato: una línea JSON por evento (JSONL).
    """

    def __init__(self, path: Path, config: FilesystemTransportConfig):
        self._path = path
        self._config = config
        self._lock = asyncio.Lock()

    async def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """Añadir un evento al feed. Thread-safe via asyncio.Lock."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            **data,
        }
        line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"

        async with self._lock:
            async with aiofiles.open(self._path, "a") as f:
                await f.write(line)
            await self._maybe_rotate()

    async def tail(self, n: int = 20) -> List[Dict]:
        """Leer las últimas n líneas del feed."""
        if not self._path.exists():
            return []
        try:
            async with aiofiles.open(self._path) as f:
                content = await f.read()
            lines = [l for l in content.strip().split("\n") if l]
            return [json.loads(l) for l in lines[-n:]]
        except Exception:
            return []

    async def _maybe_rotate(self) -> None:
        """Podar el feed si supera feed_retention líneas."""
        if self._config.feed_retention <= 0:
            return
        try:
            async with aiofiles.open(self._path) as f:
                content = await f.read()
            lines = [l for l in content.strip().split("\n") if l]
            if len(lines) > self._config.feed_retention:
                keep = lines[-self._config.feed_retention :]
                tmp = self._path.with_suffix(".tmp")
                async with aiofiles.open(tmp, "w") as f:
                    await f.write("\n".join(keep) + "\n")
                tmp.rename(self._path)
        except Exception:
            pass
```

### 7.5. ChannelManager

```python
# parrot/transport/filesystem/channel.py
from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

import aiofiles

from .config import FilesystemTransportConfig


class ChannelManager:
    """
    Canales broadcast: múltiples agentes suscritos a un canal reciben
    todos los mensajes publicados en él.

    Implementación: cada canal es un archivo JSONL append-only.
    Los suscriptores mantienen un offset local y leen desde ahí.
    No hay estado en disco sobre quién está suscrito — cualquier agente
    puede leer cualquier canal desde cualquier offset.

    Canales predefinidos:
        general    → canal global, todos los agentes
        <nombre>   → canal temático configurable
    """

    def __init__(self, channels_dir: Path, config: FilesystemTransportConfig):
        self._dir = channels_dir
        self._config = config
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def publish(
        self,
        channel: str,
        from_agent: str,
        from_name: str,
        content: str,
        payload: Dict,
    ) -> None:
        """Publicar un mensaje en el canal. Append-only, atómico via lock."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "from_agent": from_agent,
            "from_name": from_name,
            "content": content,
            "payload": payload,
        }
        line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
        path = self._dir / f"{channel}.jsonl"
        async with self._lock:
            async with aiofiles.open(path, "a") as f:
                await f.write(line)

    async def poll(
        self, channel: str, since_offset: int = 0
    ) -> AsyncGenerator[Dict, None]:
        """
        Yield mensajes del canal desde el offset dado.

        El offset es el número de línea (0-based). El caller mantiene
        el offset entre llamadas.
        """
        path = self._dir / f"{channel}.jsonl"
        if not path.exists():
            return
        try:
            async with aiofiles.open(path) as f:
                content = await f.read()
            lines = [l for l in content.strip().split("\n") if l]
            for line in lines[since_offset:]:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
        except FileNotFoundError:
            return

    async def list_channels(self) -> List[str]:
        """Listar canales disponibles (archivos .jsonl)."""
        return [p.stem for p in self._dir.glob("*.jsonl")]
```

### 7.6. ReservationManager

```python
# parrot/transport/filesystem/reservation.py
from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import hashlib

import aiofiles

from .config import FilesystemTransportConfig


class ReservationManager:
    """
    Reservaciones declarativas de recursos compartidos.

    Un agente puede declarar que está trabajando con un conjunto de
    recursos (paths de archivos, IDs de base de datos, etc.) para
    que otros agentes lo sepan y eviten colisiones.

    Implementación: cada recurso tiene un archivo JSON en reservations/.
    Las reservaciones expiran automáticamente (reservation_timeout).

    Nota: esto es una convención cooperativa, no un lock de sistema.
    Los agentes deben respetar las reservaciones por contrato.
    Para locks de sistema, usar fcntl en el archivo directamente.
    """

    def __init__(self, reservations_dir: Path, agent_id: str):
        self._dir = reservations_dir
        self._agent_id = agent_id
        self._dir.mkdir(parents=True, exist_ok=True)

    async def acquire(
        self,
        paths: List[str],
        reason: str = "",
        timeout: float = 300.0,
    ) -> bool:
        """
        Intentar adquirir reservaciones para múltiples recursos.

        Retorna True si se adquirieron todas (ninguna estaba reservada
        por otro agente activo). Retorna False si alguna falla.
        En caso de fallo, no adquiere ninguna (all-or-nothing).
        """
        # Verificar que ningún recurso esté reservado por otro agente
        for path in paths:
            existing = await self._read(path)
            if existing and existing.get("agent_id") != self._agent_id:
                # Verificar si la reserva está expirada
                expires = existing.get("expires_at")
                if expires:
                    exp_dt = datetime.fromisoformat(expires)
                    if datetime.now(timezone.utc) < exp_dt:
                        return False  # Reservado por otro agente

        # Adquirir todas
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=timeout)
        ).isoformat()

        for path in paths:
            record = {
                "resource": path,
                "agent_id": self._agent_id,
                "reason": reason,
                "acquired_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": expires_at,
            }
            await self._write(path, record)
        return True

    async def release(self, paths: Optional[List[str]] = None) -> None:
        """Liberar reservaciones. Sin paths = liberar todas del agente."""
        if paths is None:
            await self.release_all()
            return
        for path in paths:
            rec_path = self._reservation_path(path)
            rec = await self._read(path)
            if rec and rec.get("agent_id") == self._agent_id:
                rec_path.unlink(missing_ok=True)

    async def release_all(self) -> None:
        """Liberar todas las reservaciones del agente."""
        for p in self._dir.glob("*.json"):
            try:
                async with aiofiles.open(p) as f:
                    rec = json.loads(await f.read())
                if rec.get("agent_id") == self._agent_id:
                    p.unlink(missing_ok=True)
            except Exception:
                continue

    async def list_active(self) -> List[Dict]:
        """Listar todas las reservaciones activas (no expiradas)."""
        active = []
        for p in self._dir.glob("*.json"):
            try:
                async with aiofiles.open(p) as f:
                    rec = json.loads(await f.read())
                expires = rec.get("expires_at")
                if expires:
                    if datetime.now(timezone.utc) < datetime.fromisoformat(expires):
                        active.append(rec)
                else:
                    active.append(rec)
            except Exception:
                continue
        return active

    # ── Internals ─────────────────────────────────────────────────────────

    def _reservation_path(self, resource: str) -> Path:
        h = hashlib.sha256(resource.encode()).hexdigest()[:16]
        return self._dir / f"{h}.json"

    async def _read(self, resource: str) -> Optional[Dict]:
        p = self._reservation_path(resource)
        try:
            async with aiofiles.open(p) as f:
                return json.loads(await f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    async def _write(self, resource: str, data: Dict) -> None:
        p = self._reservation_path(resource)
        tmp = p.with_suffix(".tmp")
        async with aiofiles.open(tmp, "w") as f:
            await f.write(json.dumps(data, ensure_ascii=False, default=str))
        tmp.rename(p)
```

---

## 8. Integración con AI-Parrot

### 8.1. FilesystemHook (patrón BaseHook)

```python
# parrot/transport/filesystem/hook.py
from __future__ import annotations
import asyncio
from typing import Optional

from pydantic import Field

# Importar el sistema de hooks autónomo de AI-Parrot
from parrot.autonomous.hooks.base import BaseHook, BaseHookConfig

from .transport import FilesystemTransport
from .config import FilesystemTransportConfig


class FilesystemHookConfig(BaseHookConfig):
    """Configuración del FilesystemHook."""
    transport: FilesystemTransportConfig = Field(
        default_factory=FilesystemTransportConfig
    )
    command_prefix: str = Field(
        default="",
        description="Prefijo requerido para procesar el mensaje (e.g. '!ask')"
    )
    allowed_agents: Optional[list[str]] = Field(
        default=None,
        description="Lista blanca de agent_names. None = todos permitidos"
    )


class FilesystemHook(BaseHook):
    """
    Hook que conecta un agente AI-Parrot al FilesystemTransport.

    Sigue exactamente el patrón de WhatsAppRedisHook:
    - Se registra en el hook_manager del AutonomousOrchestrator
    - Arranca/para con el orchestrator
    - Escucha el inbox del agente target y despacha mensajes

    Uso::

        config = FilesystemHookConfig(
            name="fs_hook",
            target_type="agent",
            target_id="FinanceAgent",
            command_prefix="!ask",
        )
        hook = FilesystemHook(config=config)
        orchestrator.hook_manager.register_hook(hook)
        await hook.start()

    Esto permite que cualquier BasicAgent reciba mensajes de otros agentes
    o del HITL humano vía el filesystem, sin modificar el agente.
    """

    def __init__(self, config: FilesystemHookConfig):
        super().__init__(config)
        self._transport: Optional[FilesystemTransport] = None
        self._listen_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._transport = FilesystemTransport(
            agent_name=self._config.target_id,
            config=self._config.transport,
            target_type=self._config.target_type,
        )
        await self._transport.start()
        self._listen_task = asyncio.create_task(
            self._listen_loop(), name=f"fs_hook_{self.hook_id}"
        )
        self.logger.info(
            f"FilesystemHook started for {self._config.target_type}/{self._config.target_id}"
        )

    async def stop(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._transport:
            await self._transport.stop()

    async def _listen_loop(self) -> None:
        """Escuchar inbox y despachar mensajes al agente target."""
        async for msg in self._transport.messages():
            try:
                await self._dispatch(msg)
            except Exception as e:
                self.logger.error(f"Error dispatching message {msg.get('msg_id')}: {e}")

    async def _dispatch(self, msg: dict) -> None:
        """Filtrar y despachar un mensaje al agente target."""
        content = msg.get("content", "")
        from_name = msg.get("from_name", "unknown")

        # Filtro de prefix
        prefix = self._config.command_prefix
        if prefix:
            if not content.startswith(prefix):
                return
            content = content[len(prefix):].strip()

        # Filtro de agentes permitidos
        if self._config.allowed_agents and from_name not in self._config.allowed_agents:
            return

        # Obtener el agente target
        agent = await self._get_target()
        if not agent:
            self.logger.warning(f"Target agent {self._config.target_id!r} not found")
            return

        # Invocar al agente
        response = await agent.ask(content)

        # Responder al remitente si hay transport activo
        if self._transport and msg.get("from_name"):
            try:
                await self._transport.send(
                    to=msg["from_name"],
                    content=str(response),
                    msg_type="response",
                    reply_to=msg["msg_id"],
                )
            except ValueError:
                pass  # El agente remitente ya no está en el registry

    async def _get_target(self):
        """Resolver el agente target desde el orchestrator."""
        if hasattr(self, "_orchestrator_ref") and self._orchestrator_ref:
            return self._orchestrator_ref.get_agent(self._config.target_id)
        return None
```

### 8.2. Uso directo con BasicAgent

```python
# Ejemplo: agente que escucha y responde mensajes del filesystem
import asyncio
from parrot.bots import BasicAgent
from parrot.transport.filesystem import FilesystemTransport, FilesystemTransportConfig


async def run_agent(name: str, system_prompt: str):
    agent = BasicAgent(
        name=name,
        llm="google:gemini-2.0-flash",
        system_prompt=system_prompt,
    )
    await agent.configure()

    config = FilesystemTransportConfig(root_dir=".parrot", use_inotify=True)

    async with FilesystemTransport(agent_name=name, config=config) as transport:
        # Anunciar disponibilidad
        await transport.broadcast(f"{name} online")

        # Escuchar y responder
        async for msg in transport.messages():
            response = await agent.ask(msg["content"])
            await transport.send(
                to=msg["from_name"],
                content=str(response),
                reply_to=msg["msg_id"],
            )
```

### 8.3. Uso multi-agente (el caso de uso central)

```python
# Tres agentes especializados coordinándose en el mismo filesystem
# — el equivalente a pi-messenger pero con agentes AI-Parrot

import asyncio
from parrot.bots import BasicAgent
from parrot.transport.filesystem import FilesystemTransport, FilesystemTransportConfig

CFG = FilesystemTransportConfig(root_dir=".parrot", use_inotify=True)


async def specialist(name: str, prompt: str):
    """Agente especialista: escucha tareas, responde con resultados."""
    agent = BasicAgent(name=name, llm="google:gemini-2.0-flash", system_prompt=prompt)
    await agent.configure()

    async with FilesystemTransport(agent_name=name, config=CFG) as t:
        await t.broadcast(f"{name} online y disponible", channel="crew")
        async for msg in t.messages():
            # Reservar recursos si el mensaje los especifica
            files = msg.get("payload", {}).get("files", [])
            if files:
                await t.reserve(files, reason=f"{name} processing task")

            result = await agent.ask(msg["content"])

            if files:
                await t.release(files)

            await t.send(msg["from_name"], str(result), reply_to=msg["msg_id"])


async def orchestrator():
    """Orquestador: descubre agentes disponibles y delega tareas."""
    async with FilesystemTransport(agent_name="Orchestrator", config=CFG) as t:
        # Esperar que los especialistas se unan
        await asyncio.sleep(1.5)

        # Discovery: ver quién está disponible
        agents = await t.list_agents()
        available = {a["name"] for a in agents}
        print(f"Agentes disponibles: {available}")

        # Delegar tareas a especialistas específicos
        if "DataAgent" in available:
            await t.send(
                "DataAgent",
                "Extrae las métricas de revenue del Q2 2026",
                msg_type="task",
                payload={"files": ["data/q2.csv"]},
            )

        # Escuchar respuestas
        results = {}
        async for msg in t.messages():
            if msg["type"] == "response":
                results[msg["from_name"]] = msg["content"]
            if len(results) >= len(available) - 1:
                break

        print("Resultados:", results)


async def main():
    await asyncio.gather(
        specialist("DataAgent", "Extraes y analizas datos CSV y bases de datos."),
        specialist("ReportAgent", "Generas reportes ejecutivos estructurados."),
        orchestrator(),
    )

asyncio.run(main())
```

### 8.4. Registro en parrot.yaml

```yaml
# Activación vía hooks autónomos (patrón existente en AI-Parrot)

hooks:
  - type: filesystem
    name: fs_data_hook
    enabled: true
    target_type: agent
    target_id: DataAgent
    command_prefix: ""        # vacío = cualquier mensaje
    allowed_agents: null      # null = todos permitidos
    transport:
      root_dir: .parrot
      use_inotify: true
      presence_interval: 10.0
      poll_interval: 0.5
      message_ttl: 3600
      keep_processed: true
      feed_retention: 500
      default_channels:
        - general
        - crew
```

---

## 9. CLI Overlay (HITL)

El CLI overlay permite al humano observar el sistema en tiempo real, enviar mensajes a agentes, y ver el activity feed — sin ningún daemon adicional.

### 9.1. Invocación

```bash
# Ver estado actual (snapshot)
python -m parrot.transport.filesystem.cli --root .parrot

# Modo watch: actualiza cada segundo
python -m parrot.transport.filesystem.cli --root .parrot --watch

# Enviar un mensaje a un agente
python -m parrot.transport.filesystem.cli --root .parrot \
    --send "DataAgent" "Dame el CSV de ventas del Q2"

# Ver los últimos 20 eventos del feed
python -m parrot.transport.filesystem.cli --root .parrot --feed 20
```

### 9.2. Layout del overlay

```
╭─ AI-Parrot FilesystemTransport ── 3 agentes ──────────────────────╮
│                                                                    │
│  🟢 Orchestrator    [gemini-2.0-flash]   active   1m ago          │
│  🟢 DataAgent       [gemini-2.0-flash]   busy     10s ago         │
│     📁 data/q2.csv (reserved)                                      │
│  🟡 ReportAgent     [claude-sonnet-4-6]  idle     5m ago          │
│                                                                    │
│  Activity Feed                                                     │
│  10:42 DataAgent → ReportAgent: 'Datos listos para el reporte...' │
│  10:41 DataAgent reserved data/q2.csv                             │
│  10:40 Orchestrator → DataAgent: 'Extrae métricas Q2...'          │
│  10:38 DataAgent joined                                            │
│  10:38 Orchestrator joined                                         │
│                                                                    │
├────────────────────────────────────────────────────────────────────┤
│ > @DataAgent añade también las comparativas vs Q1      [Enter]    │
╰────────────────────────────────────────────────────────────────────╯
[↑↓] scroll feed   [Tab] completar @agent   [q] salir
```

### 9.3. Implementación (esquema)

```python
# parrot/transport/filesystem/cli.py
import asyncio
import json
from pathlib import Path
from typing import Optional

import click

try:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from .registry import AgentRegistry
from .feed import ActivityFeed
from .config import FilesystemTransportConfig
from .transport import FilesystemTransport


class CrewCLI:
    """
    CLI overlay para FilesystemTransport.

    Lee el estado directamente del filesystem — no requiere que
    ningún proceso esté corriendo (puede leer estados históricos).
    """

    def __init__(self, root_dir: Path):
        self._root = root_dir
        config = FilesystemTransportConfig(root_dir=root_dir)
        self._registry = AgentRegistry(root_dir / "registry", config)
        self._feed = ActivityFeed(root_dir / "feed.jsonl", config)

    async def get_state(self) -> dict:
        agents = await self._registry.list_active()
        feed = await self._feed.tail(n=10)
        return {"agents": agents, "feed": feed}

    def render_text(self, state: dict) -> str:
        status_icon = {"active": "🟢", "busy": "⏳", "idle": "🟡", "offline": "🔴"}
        lines = [f"AI-Parrot FilesystemTransport — {len(state['agents'])} agentes\n"]
        for a in state["agents"]:
            icon = status_icon.get(a.get("status", "active"), "🟢")
            msg = f"  {a.get('status_message', '')[:40]}" if a.get("status_message") else ""
            lines.append(f"  {icon} {a['name']:20} [{a.get('model', '?')}]{msg}")
        lines.append("\nActivity Feed:")
        for entry in reversed(state["feed"]):
            ts = entry.get("ts", "")[-8:-1]  # HH:MM:SS
            ev = entry.get("event", "")
            agent = entry.get("agent") or entry.get("from", "")
            lines.append(f"  {ts} {ev:12} {agent}")
        return "\n".join(lines)


@click.command()
@click.option("--root", default=".parrot", help="Root dir del FilesystemTransport")
@click.option("--watch", is_flag=True, help="Modo watch (actualiza cada segundo)")
@click.option("--send", nargs=2, metavar="AGENT MESSAGE", help="Enviar mensaje a un agente")
@click.option("--feed", default=0, type=int, help="Ver últimas N líneas del feed")
def main(root: str, watch: bool, send: tuple, feed: int):
    """CLI overlay para FilesystemTransport."""
    root_path = Path(root)
    cli = CrewCLI(root_path)

    async def run():
        if send:
            agent_name, message = send
            config = FilesystemTransportConfig(root_dir=root_path)
            async with FilesystemTransport(agent_name="human-cli", config=config) as t:
                try:
                    msg_id = await t.send(agent_name, message, msg_type="message")
                    click.echo(f"✓ Mensaje enviado a {agent_name} ({msg_id})")
                except ValueError as e:
                    click.echo(f"✗ {e}", err=True)
            return

        if feed > 0:
            state = await cli.get_state()
            activity = ActivityFeed(root_path / "feed.jsonl",
                                    FilesystemTransportConfig(root_dir=root_path))
            entries = await activity.tail(n=feed)
            for e in entries:
                click.echo(json.dumps(e, ensure_ascii=False))
            return

        if watch:
            while True:
                state = await cli.get_state()
                click.clear()
                click.echo(cli.render_text(state))
                await asyncio.sleep(1.0)
        else:
            state = await cli.get_state()
            click.echo(cli.render_text(state))

    asyncio.run(run())


if __name__ == "__main__":
    main()
```

---

## 10. Configuración YAML

```yaml
# parrot.yaml

transport:
  filesystem:
    root_dir: .parrot

    # Presencia
    presence_interval: 10.0      # Heartbeat cada 10s
    stale_threshold: 60.0        # Agente muerto si no heartbeat en 60s
    scope_to_cwd: false          # Ver agentes de todo el sistema, no solo del cwd

    # Inbox
    poll_interval: 0.5           # Polling fallback: cada 500ms
    use_inotify: true            # Preferir inotify/FSEvents/ReadDirectoryChanges
    message_ttl: 3600            # Mensajes expiran en 1 hora
    keep_processed: true         # Guardar mensajes procesados en .processed/

    # Feed
    feed_retention: 500          # Rotar feed al llegar a 500 eventos

    # Canales
    default_channels:
      - general
      - crew

    # Reservaciones
    reservation_timeout: 300     # Las reservas expiran en 5 minutos

hooks:
  - type: filesystem
    name: fs_hook_finance
    enabled: true
    target_type: agent
    target_id: FinanceAgent
    command_prefix: ""
    allowed_agents: null
    transport:
      root_dir: .parrot
      use_inotify: true
```

---

## 11. Dependencias y Packaging

### 11.1. Requeridas

| Paquete | Versión mínima | Uso |
|---|---|---|
| `aiofiles` | >=23.0 | I/O asíncrono de archivos en todos los componentes |

### 11.2. Opcionales

| Paquete | Uso | Activado cuando |
|---|---|---|
| `watchdog` | inotify (Linux), FSEvents (macOS), ReadDirectoryChanges (Windows) | `use_inotify=True` |
| `rich` | CLI overlay con formato visual | `cli.py` con rich instalado |
| `click` | CLI commands | `cli.py` |

### 11.3. pyproject.toml

```toml
[project.optional-dependencies]
filesystem-transport = [
    "aiofiles>=23.0",
]
filesystem-transport-full = [
    "aiofiles>=23.0",
    "watchdog>=4.0",
    "rich>=13.0",
    "click>=8.0",
]

[project.scripts]
parrot-fs = "parrot.transport.filesystem.cli:main"
```

---

## 12. Compatibilidad de Plataforma

| Feature | Linux | macOS | Windows |
|---|---|---|---|
| Atomicidad `rename()` | ✅ POSIX | ✅ POSIX | ⚠️ Misma unidad de disco |
| PID check `os.kill(pid, 0)` | ✅ | ✅ | ✅ |
| inotify (watchdog) | ✅ `inotify` | ✅ `FSEvents` | ✅ `ReadDirectoryChanges` |
| `fcntl.flock()` (ReservationManager) | ✅ | ✅ | ❌ Usar `msvcrt.locking` |
| CLI overlay (rich) | ✅ | ✅ | ✅ |

> **Windows:** En Windows, `rename()` atómico solo garantiza atomicidad en la misma unidad. `fcntl` no está disponible — el `ReservationManager` debe usar `msvcrt.locking` como fallback. Se recomienda WSL2 para máxima compatibilidad.
- El problema claro es que toda la infra debajo de ai-parrot usa uvloop, no creo que podamos ser compatibles con Windows (tampoco lo esperamos).

---

## 13. Testing

### 13.1. Estrategia

- Todos los tests usan `tmp_path` de pytest (filesystem temporal, limpiado automáticamente)
- No se necesitan mocks de red ni servicios externos
- Los tests de concurrencia usan `asyncio.gather()` para simular múltiples agentes

### 13.2. Estructura

```
tests/transport/filesystem/
├── conftest.py              # Fixtures: config, transport, agentes mock
├── test_registry.py         # AgentRegistry: join, leave, PID detection, GC
├── test_inbox.py            # InboxManager: deliver, poll, TTL, exactly-once
├── test_feed.py             # ActivityFeed: emit, tail, rotación
├── test_channel.py          # ChannelManager: publish, poll con offset
├── test_reservation.py      # ReservationManager: acquire, release, all-or-nothing
├── test_transport.py        # FilesystemTransport: integración de todos los componentes
└── test_hook.py             # FilesystemHook: patrón BaseHook
```

### 13.3. Fixtures clave

```python
# tests/transport/filesystem/conftest.py
import pytest
from pathlib import Path
from parrot.transport.filesystem.config import FilesystemTransportConfig
from parrot.transport.filesystem.transport import FilesystemTransport


@pytest.fixture
def fs_config(tmp_path: Path) -> FilesystemTransportConfig:
    return FilesystemTransportConfig(
        root_dir=tmp_path,
        presence_interval=0.1,   # Rápido para tests
        poll_interval=0.05,
        use_inotify=False,        # Polling en tests (más predecible)
        stale_threshold=1.0,
        message_ttl=60.0,
        feed_retention=100,
    )


@pytest.fixture
async def transport_a(fs_config):
    async with FilesystemTransport(
        agent_name="AgentA", config=fs_config
    ) as t:
        yield t


@pytest.fixture
async def transport_b(fs_config):
    async with FilesystemTransport(
        agent_name="AgentB", config=fs_config
    ) as t:
        yield t
```

### 13.4. Casos de test críticos

```python
# test_inbox.py

@pytest.mark.asyncio
async def test_delivery_is_atomic(fs_config, tmp_path):
    """El receptor nunca lee un mensaje parcialmente escrito."""
    from parrot.transport.filesystem.inbox import InboxManager

    inbox = InboxManager(tmp_path / "inbox", "agent-b", fs_config)
    inbox.setup()

    # Entregar un mensaje grande
    big_content = "x" * 100_000
    await inbox.deliver("agent-a", "AgentA", "agent-b", big_content, "msg", {}, None)

    # El mensaje debe leerse completo o no existir
    msgs = []
    async for msg in inbox.poll():
        msgs.append(msg)
        break  # Solo el primero

    assert len(msgs) == 1
    assert msgs[0]["content"] == big_content


@pytest.mark.asyncio
async def test_exactly_once_delivery(fs_config, tmp_path):
    """Un mensaje no se procesa dos veces aunque el agente se reinicie."""
    from parrot.transport.filesystem.inbox import InboxManager

    inbox = InboxManager(tmp_path / "inbox", "agent-b", fs_config)
    inbox.setup()
    await inbox.deliver("a", "A", "agent-b", "hello", "msg", {}, None)

    # Primera lectura
    first = []
    async for msg in inbox.poll():
        first.append(msg)
        break

    assert len(first) == 1

    # Segunda lectura del mismo inbox — el mensaje ya está en .processed/
    second = []
    async for msg in inbox.poll():
        second.append(msg)
        break

    # No debe haber segundo mensaje
    assert len(second) == 0


@pytest.mark.asyncio
async def test_send_and_receive(transport_a, transport_b):
    """AgentA envía un mensaje a AgentB y AgentB lo recibe."""
    await transport_a.send("AgentB", "Hola desde A")

    received = []
    async for msg in transport_b.messages():
        received.append(msg)
        break

    assert received[0]["content"] == "Hola desde A"
    assert received[0]["from_name"] == "AgentA"


@pytest.mark.asyncio
async def test_discovery(transport_a, transport_b):
    """list_agents retorna ambos agentes activos."""
    agents = await transport_a.list_agents()
    names = {a["name"] for a in agents}
    assert "AgentA" in names
    assert "AgentB" in names


@pytest.mark.asyncio
async def test_reservation_all_or_nothing(transport_a, transport_b):
    """Si un recurso está reservado, la adquisición falla completa."""
    ok1 = await transport_a.reserve(["file_a.csv", "file_b.csv"])
    assert ok1 is True

    # transport_b intenta reservar uno que ya tiene transport_a
    ok2 = await transport_b.reserve(["file_b.csv", "file_c.csv"])
    assert ok2 is False

    # file_c.csv no debe estar reservado (all-or-nothing)
    active = await transport_b._reservations.list_active()
    reserved_resources = {r["resource"] for r in active}
    assert "file_c.csv" not in reserved_resources


@pytest.mark.asyncio
async def test_feed_rotation(fs_config, tmp_path):
    """El feed rota cuando supera feed_retention líneas."""
    fs_config.feed_retention = 10
    from parrot.transport.filesystem.feed import ActivityFeed

    feed = ActivityFeed(tmp_path / "feed.jsonl", fs_config)

    for i in range(15):
        await feed.emit("test", {"i": i})

    entries = await feed.tail(n=20)
    # Solo debe haber feed_retention = 10 entradas
    assert len(entries) <= 10
    # Las más recientes deben estar presentes
    assert entries[-1]["i"] == 14
```

---

## 14. Orden de Implementación

### Phase 1 — Core (estimado: 2-3 días)

**Objetivo:** Mensajería básica funcional entre dos agentes.

1. `config.py` — `FilesystemTransportConfig` con Pydantic
2. `registry.py` — `AgentRegistry` con PID detection y GC
3. `inbox.py` — `InboxManager` con write-then-rename atómico
4. `feed.py` — `ActivityFeed` append-only con rotación
5. `transport.py` — `FilesystemTransport` con start/stop/send/messages
6. Tests de `registry`, `inbox`, `feed`, y `transport`

**Criterio de aceptación:** Dos procesos Python en el mismo sistema pueden enviarse mensajes via `.parrot/` y recibirlos correctamente. El test `test_send_and_receive` pasa.

### Phase 2 — Canales y Reservaciones (estimado: 1 día)

**Objetivo:** Broadcast y coordinación de recursos.

7. `channel.py` — `ChannelManager` con JSONL y offset-based polling
8. `reservation.py` — `ReservationManager` con all-or-nothing y TTL
9. Tests de `channel` y `reservation`

**Criterio de aceptación:** `test_reservation_all_or_nothing` pasa. Tres agentes pueden publicar y leer de un canal.

### Phase 3 — Integración con AI-Parrot (estimado: 1 día)

**Objetivo:** `FilesystemHook` funcionando con el sistema de hooks autónomo.

10. `hook.py` — `FilesystemHook` siguiendo el patrón `BaseHook`/`WhatsAppRedisHook`
11. `test_hook.py` — Tests con agente mock
12. Configuración vía `parrot.yaml`

**Criterio de aceptación:** Un `BasicAgent` registrado en `BotManager` responde mensajes recibidos via `FilesystemHook` sin ninguna modificación al agente.

### Phase 4 — CLI + inotify (estimado: 1 día)

**Objetivo:** HITL puede observar e interactuar desde la terminal.

13. `cli.py` — CLI overlay con snapshot, watch, send, y feed
14. Integración de watchdog/inotify en `InboxManager._start_watcher()`
15. `__init__.py` — Exports públicos del módulo

**Criterio de aceptación:** `python -m parrot.transport.filesystem.cli --root .parrot --watch` muestra el estado en tiempo real. `--send AgentA "mensaje"` entrega el mensaje.

---

## 15. Decisiones de Diseño

### 15.1. Write-then-rename para atomicidad

El patrón `write(tmp) → rename(final)` garantiza que el receptor nunca lee un archivo parcialmente escrito. En POSIX, `rename()` es atómico: el archivo existe completo o no existe. Esto elimina la necesidad de locks en las escrituras de mensajes y registros.

### 15.2. PID como mecanismo de presencia

A diferencia de los sistemas basados en TTL (Redis, heartbeat con timeout), la verificación de PID con `os.kill(pid, 0)` es instantánea y sin falsos positivos: si el proceso murió (crash, SIGKILL), su registro se elimina en el próximo GC cycle sin esperar un timeout. El timeout sigue siendo útil como fallback para procesos de otro host en un filesystem NFS.

### 15.3. Poll + inotify como estrategia de polling

El polling puro (cada 500ms) introduce latencia. inotify/FSEvents da latencia sub-50ms pero no está disponible en todos los entornos. La estrategia es: intentar inotify al startup, silenciosamente hacer fallback a polling si `watchdog` no está instalado. El código del receptor no cambia.

### 15.4. Canales con offset en lugar de estado de suscripción

Los canales no mantienen estado sobre quién está suscrito ni qué ha leído cada suscriptor. Cada agente mantiene su propio offset local. Esto simplifica enormemente el sistema: un canal es solo un archivo JSONL append-only. Un agente que se reinicia puede recuperar mensajes perdidos leyendo desde el último offset que tenía.

### 15.5. ReservationManager como convención, no como lock de sistema

Las reservaciones son declarativas (cooperativas), no exclusivas a nivel de sistema. Un agente que ignora las reservaciones puede acceder al recurso de todas formas. Esto es intencional: el objetivo es comunicar intención entre agentes que cooperan, no imponer acceso exclusivo. Para exclusión real, usar `fcntl.flock()` directamente sobre el archivo objetivo.

### 15.6. Convergencia futura con TelegramCrewTransport y Matrix

El `FilesystemTransport` establece el modelo conceptual: presencia, inbox, canales, reservaciones. `TelegramCrewTransport` y `MatrixTransport` implementan el mismo modelo sobre sus respectivos protocolos. La interfaz pública de `FilesystemTransport` (`send`, `broadcast`, `messages`, `list_agents`, `reserve`, `release`) puede extraerse como `AbstractTransport` cuando haya dos implementaciones maduras, permitiendo intercambiar transports sin modificar el código del agente.

---

*AI-Parrot Framework · FilesystemTransport Spec · v0.1 · Feb 2026*
*Para uso con Claude Code — contratos de código completos e implementables*