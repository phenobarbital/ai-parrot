---
type: Wiki Overview
title: FilesystemTransport — Especificación Técnica
id: doc:sdd-proposals-filesystem-transport-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 1. [Motivación](#1-motivación)
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.autonomous
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
---

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
  "model": "google:gemini-3.1-flash-lite-preview",
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

…(truncated)…
