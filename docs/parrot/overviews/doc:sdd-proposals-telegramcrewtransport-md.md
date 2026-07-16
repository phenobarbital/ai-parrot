---
type: Wiki Overview
title: TelegramCrewTransport — Arquitectura
id: doc:sdd-proposals-telegramcrewtransport-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Versión 0.1 · Draft · Febrero 2026
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.integrations.telegram.crew
  rel: mentions
- concept: mod:parrot.integrations.telegram.crew.config
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
---

# TelegramCrewTransport — Arquitectura

**AI-Parrot Framework · Especificación de Diseño**  
Versión 0.1 · Draft · Febrero 2026

---

## 1. Contexto y Motivación

### 1.1. Estado Actual de la Integración Telegram

AI-Parrot ya tiene una integración Telegram madura (`parrot/integrations/telegram/`) con los siguientes componentes:

| Componente | Responsabilidad actual |
|---|---|
| `TelegramBotManager` | Ciclo de vida de bots: startup/shutdown, polling por agente |
| `TelegramAgentWrapper` | Routing de mensajes → agente, typing indicator, response formatting |
| `TelegramAgentConfig` | Configuración por bot: token, allowed_chat_ids, group_mentions, commands |
| `BotMentionedFilter` | Filtro aiogram: detecta `@username` en entidades de mensaje |
| `TelegramHumanChannel` | Canal HITL con inline keyboards para approval flows |

El modelo actual es **1 bot = 1 agente = 1 canal privado o grupo genérico**. El `TelegramCrewTransport` extiende este modelo para el escenario **N bots = N agentes = 1 supergrupo compartido como crew channel**, con presencia, discovery, y HITL mediante menciones.

### 1.2. Qué NO existe aún

Los siguientes elementos deben diseñarse e implementarse:

- **CrewRegistry sobre Telegram**: mensaje anclado que el coordinador edita como única fuente de verdad de presencia
- **AgentCard**: schema de auto-descripción emitida al unirse al grupo
- **DataPayload over Documents**: mecanismo para que un agente envíe datos estructurados (CSV, JSON) a otro mediante adjuntos
- **Multi-turn silencioso**: los agentes no publican tool calls intermedios; solo publican el resultado final
- **Coordinator bot**: bot especial que gestiona el pinned registry y actúa como árbitro de routing

### 1.3. Principios de Diseño

1. **Silencio en el proceso**: los tool calls internos del agente nunca se publican. El canal solo ve inputs y outputs finales.
2. **Mention-as-addressing**: toda respuesta incluye `@mention` al remitente (humano o bot).
3. **Pinned message como registry**: un único mensaje anclado es la fuente de verdad de qué agentes están online. El timeline no se usa para discovery.
4. **Attachments para datos**: CSV, JSON, Parquet y otros datasets se envían como documentos adjuntos, nunca inline.
5. **Bot-to-bot via group**: no hay DMs inter-bot. Todo pasa por el grupo, lo que mantiene visibilidad total para el HITL.

---

## 2. Arquitectura General

### 2.1. Estructura de Módulos

```
parrot/integrations/telegram/
├── __init__.py                    # exports existentes + nuevos
├── models.py                      # + TelegramCrewConfig, AgentCard
├── filters.py                     # + CrewMentionFilter (multi-bot aware)
├── wrapper.py                     # TelegramAgentWrapper (existente, extendido)
├── manager.py                     # TelegramBotManager (existente, extendido)
│
└── crew/                          # ← NUEVO MÓDULO
    ├── __init__.py
    ├── transport.py               # TelegramCrewTransport (orquestador principal)
    ├── coordinator.py             # CoordinatorBot (gestiona pinned registry)
    ├── registry.py                # CrewRegistry (estado en memoria + Telegram)
    ├── agent_card.py              # AgentCard schema + renderer
    ├── crew_wrapper.py            # CrewAgentWrapper (extiende TelegramAgentWrapper)
    ├── payload.py                 # DataPayload: send/receive de archivos entre agentes
    ├── mention.py                 # MentionBuilder: helpers para @mentions
    └── config.py                  # TelegramCrewConfig (Pydantic)
```

### 2.2. Diagrama de Componentes

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Supergrupo Telegram (Crew Channel)               │
│                                                                     │
│  Miembros:                                                          │
│    @coordinator_bot  ← CoordinatorBot (gestiona pinned registry)   │
│    @orchestrator_bot ← OrchestratorAgent                           │
│    @data_bot         ← DataAgent                                    │
│    @report_bot       ← ReportAgent                                  │
│    @jesus            ← HITL (tú)                                    │
│                                                                     │
│  📌 Pinned Message (editado por @coordinator_bot):                  │
│    ┌────────────────────────────────────────────┐                   │
│    │ 🤖 AI-Parrot Crew · Online                 │                   │
│    │ ✅ @orchestrator_bot  OrchestratorAgent    │                   │
│    │ ✅ @data_bot          DataAgent            │                   │
│    │ ✅ @report_bot        ReportAgent          │                   │
│    └────────────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
  TelegramBotManager   TelegramBotManager   TelegramBotManager
  (coordinator_bot)    (orchestrator_bot)   (data_bot, report_bot)
         │
         ▼
  TelegramCrewTransport
  (orquesta todos los wrappers)
         │
    ┌────┴─────┐
    │          │
    ▼          ▼
CrewRegistry  CoordinatorBot
(en memoria)  (pinned msg editor)
```

### 2.3. Flujo de Mensaje Completo

```
 Usuario (@jesus)                Telegram Group               DataAgent Bot
      │                               │                            │
      │── "@data_bot dame el CSV ────>│                            │
      │    del Q2 de ventas"          │── message event ──────────>│
      │                               │                  [agent.ask() interno]
      │                               │                  [tool: query_database]
      │                               │                  [tool: export_csv]
      │                               │                  [multi-turn silencioso]
      │                               │                            │
      │                               │<── send_document(q2.csv) ──│
      │                               │    + "@jesus aquí tienes   │
      │                               │    el CSV del Q2..."       │
      │<── documento CSV adjunto ─────│                            │
      │<── "@jesus aquí tienes..." ───│                            │
```

---

## 3. Modelos de Datos

### 3.1. AgentCard

La AgentCard es el schema de auto-descripción que cada agente emite al unirse al grupo. Es el equivalente al `/.well-known/agent.json` del protocolo A2A, pero serializado como mensaje de Telegram.

```python
# parrot/integrations/telegram/crew/agent_card.py
from __future__ import annotations
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class AgentSkill(BaseModel):
    """Capacidad específica de un agente."""
    name: str
    description: str
    input_types: List[str] = Field(default_factory=list)   # ["text", "csv", "json"]
    output_types: List[str] = Field(default_factory=list)  # ["text", "csv", "chart"]
    example: Optional[str] = None


class AgentCard(BaseModel):
    """
    Descriptor público de un agente en el crew de Telegram.
    
    Emitida automáticamente al unirse al grupo.
    Almacenada en CrewRegistry para discovery por otros agentes.
    """
    # Identidad
    agent_id: str                        # Identificador interno AI-Parrot
    agent_name: str                      # Nombre legible
    telegram_username: str               # @username del bot
    telegram_user_id: int                # ID numérico del bot en Telegram

    # Capacidades
    model: str                           # "google:gemini-3.1-flash-lite-preview"
    skills: List[AgentSkill] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    accepts_files: List[str] = Field(   # Tipos de archivo que acepta
        default_factory=list            # ["csv", "json", "pdf"]
    )
    emits_files: List[str] = Field(     # Tipos de archivo que puede emitir
        default_factory=list            # ["csv", "json", "png"]
    )

    # Estado
    status: str = "ready"               # "ready" | "busy" | "offline"
    current_task: Optional[str] = None
    joined_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)

    def to_telegram_text(self) -> str:
        """Renderizar como mensaje de Telegram con formato Markdown."""
        skills_text = "\n".join(
            f"  • *{s.name}*: {s.description}" for s in self.skills
        )
        tags_text = " ".join(f"`#{t}`" for t in self.tags) if self.tags else "—"
        accepts = ", ".join(f"`{f}`" for f in self.accepts_files) or "—"
        emits = ", ".join(f"`{f}`" for f in self.emits_files) or "—"

        return (
            f"🤖 *{self.agent_name}* se ha unido al crew\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📛 *Agent:* @{self.telegram_username}\n"
            f"🧠 *Model:* `{self.model}`\n"
            f"🏷 *Tags:* {tags_text}\n"
            f"📥 *Acepta:* {accepts}\n"
            f"📤 *Emite:* {emits}\n"
            f"🛠 *Skills:*\n{skills_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )

    def to_registry_line(self) -> str:
        """Línea compacta para el pinned message del registry."""
        status_icon = {"ready": "✅", "busy": "⏳", "offline": "❌"}.get(
            self.status, "❓"
        )
        task = f" · _{self.current_task[:40]}_" if self.current_task else ""
        return f"{status_icon} @{self.telegram_username} · *{self.agent_name}*{task}"
```

### 3.2. TelegramCrewConfig

```python
# parrot/integrations/telegram/crew/config.py
from __future__ import annotations
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class CrewAgentEntry(BaseModel):
    """Entrada de un agente en el crew."""
    chatbot_id: str          # ID del agente en BotManager
    bot_token: str           # Token del bot de Telegram
    username: str            # @username (sin @)
    skills: List[dict] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    accepts_files: List[str] = Field(default_factory=list)
    emits_files: List[str] = Field(default_factory=list)
    system_prompt_override: Optional[str] = None


class TelegramCrewConfig(BaseModel):
    """
    Configuración completa del TelegramCrewTransport.
    
    YAML equivalente::
    
        crew:
          group_id: -1001234567890
          coordinator_token: "7xxx:CCC..."
          coordinator_username: "parrot_coordinator_bot"
          hitl_user_ids: [123456789]
          agents:
            OrchestratorAgent:
              chatbot_id: orchestrator_agent
              bot_token: "7xxx:AAA..."
              username: orchestrator_parrot_bot
              tags: [orchestration, planning]
            DataAgent:
              chatbot_id: data_agent  
              bot_token: "7xxx:BBB..."
              username: data_parrot_bot
              accepts_files: [csv, json, parquet]
              emits_files: [csv, json, png]
              tags: [data, analytics]
    """
    # Grupo objetivo
    group_id: int            # ID del supergrupo (negativo)

    # Coordinator bot (bot especial que gestiona el pinned registry)
    coordinator_token: str
    coordinator_username: str

    # HITL: IDs de usuarios humanos que pueden interactuar
    hitl_user_ids: List[int] = Field(default_factory=list)

    # Agentes del crew
    agents: Dict[str, CrewAgentEntry] = Field(default_factory=dict)

    # Comportamiento
    announce_on_join: bool = True       # Emitir AgentCard al unirse
    update_pinned_registry: bool = True # Coordinator edita pinned msg
    reply_to_sender: bool = True        # Siempre hacer @mention al responder
    silent_tool_calls: bool = True      # No publicar tool calls intermedios
    typing_indicator: bool = True       # Mostrar "escribiendo..." mientras procesa
    max_message_length: int = 4000      # Truncar antes del límite de Telegram (4096)

    # Archivos adjuntos
    temp_dir: str = "/tmp/parrot_crew"  # Directorio temporal para adjuntos
    max_file_size_mb: int = 50          # Límite de tamaño de adjunto
    allowed_mime_types: List[str] = Field(
        default=[
            "text/csv", "application/json", "application/parquet",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "image/png", "image/jpeg", "application/pdf",
        ]
    )

    @classmethod
    def from_yaml(cls, path: str) -> "TelegramCrewConfig":
        import yaml
        from pathlib import Path
        data = yaml.safe_load(Path(path).read_text())
        return cls(**data.get("crew", data))
```

---

## 4. Componentes Principales

### 4.1. TelegramCrewTransport

El orquestador central. Gestiona el ciclo de vida de todos los bots del crew, coordina el registry, y expone la API de alto nivel.

```python
# parrot/integrations/telegram/crew/transport.py
from __future__ import annotations
import asyncio
from typing import Dict, List, Optional, Any
from pathlib import Path

from aiogram import Bot
from aiogram.types import Message

from .config import TelegramCrewConfig, CrewAgentEntry
from .coordinator import CoordinatorBot
from .registry import CrewRegistry
from .crew_wrapper import CrewAgentWrapper
from .payload import DataPayload


class TelegramCrewTransport:
    """
    Transport que conecta múltiples agentes AI-Parrot en un único
    supergrupo de Telegram como crew channel colaborativo.

    Responsabilidades:
    - Iniciar y detener todos los bots del crew
    - Mantener el CrewRegistry (presencia en memoria)
    - Delegar al CoordinatorBot la gestión del pinned message
    - Proveer API de alto nivel para envío de mensajes y adjuntos

    Uso::

        config = TelegramCrewConfig.from_yaml("env/telegram_crew.yaml")
        transport = TelegramCrewTransport(config, bot_manager)
        
        async with transport:
            # Todos los bots están online y escuchando
            await asyncio.sleep(float('inf'))
    """

    def __init__(self, config: TelegramCrewConfig, bot_manager):
        self.config = config
        self.bot_manager = bot_manager
        self.registry = CrewRegistry()
        self.coordinator: Optional[CoordinatorBot] = None
        self._wrappers: Dict[str, CrewAgentWrapper] = {}
        self._tasks: List[asyncio.Task] = []

    async def start(self) -> None:
        """Iniciar coordinator y todos los agentes del crew."""
        # 1. Iniciar el CoordinatorBot
        self.coordinator = CoordinatorBot(
            token=self.config.coordinator_token,
            username=self.config.coordinator_username,
            group_id=self.config.group_id,
            registry=self.registry,
        )
        await self.coordinator.start()

        # 2. Iniciar cada agente del crew
        for name, entry in self.config.agents.items():
            await self._start_crew_agent(name, entry)

    async def stop(self) -> None:
        """Detener todos los bots y limpiar recursos."""
        for task in self._tasks:
            task.cancel()
        
        # Notificar salida de cada agente del registry
        for name, wrapper in self._wrappers.items():
            await self.registry.unregister(wrapper.card.telegram_username)
            if self.coordinator:
                await self.coordinator.update_registry()
        
        if self.coordinator:
            await self.coordinator.stop()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()

    # ── API pública ───────────────────────────────────────────────────────

    async def send_message(
        self,
        from_username: str,
        mention: str,           # "@username" del destinatario
        text: str,
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        """Enviar mensaje de texto desde un agente, con @mention al destinatario."""
        wrapper = self._wrappers.get(from_username)
        if not wrapper:
            raise ValueError(f"Agent @{from_username} not registered in crew")
        await wrapper.send_crew_message(mention, text, reply_to_message_id)

    async def send_document(
        self,
        from_username: str,
        mention: str,
        file_path: Path,
        caption: str = "",
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        """Enviar documento adjunto desde un agente con @mention."""
        wrapper = self._wrappers.get(from_username)
        if not wrapper:
            raise ValueError(f"Agent @{from_username} not registered in crew")
        await wrapper.send_crew_document(
            mention, file_path, caption, reply_to_message_id
        )

    def list_online_agents(self) -> List[dict]:
        """Listar agentes online según el CrewRegistry."""
        return self.registry.list_active()

    # ── Internals ─────────────────────────────────────────────────────────

    async def _start_crew_agent(
        self, name: str, entry: CrewAgentEntry
    ) -> None:
        """Iniciar un bot de crew individual."""
        agent = await self.bot_manager.get_bot(entry.chatbot_id)
        if not agent:
            raise ValueError(f"Agent '{entry.chatbot_id}' not found in BotManager")

        bot = Bot(token=entry.bot_token)

        wrapper = CrewAgentWrapper(
            agent=agent,
            bot=bot,
            entry=entry,
            transport=self,
        )
        await wrapper.start()
        self._wrappers[entry.username] = wrapper

        task = asyncio.create_task(
            wrapper.run_polling(),
            name=f"crew_polling_{name}"
        )
        self._tasks.append(task)
```

### 4.2. CoordinatorBot

Bot especial que no representa a ningún agente de AI-Parrot. Su única responsabilidad es gestionar el mensaje anclado del registry.

```python
# parrot/integrations/telegram/crew/coordinator.py
from __future__ import annotations
import asyncio
from typing import Optional
from aiogram import Bot
from aiogram.types import Message

from .registry import CrewRegistry
from .agent_card import AgentCard


class CoordinatorBot:
    """
    Bot coordinador del crew channel.

    No es un agente AI-Parrot. Sus responsabilidades son:
    1. Crear el mensaje anclado (pinned message) del registry al iniciar
    2. Editar dicho mensaje cada vez que un agente entra o sale
    3. Proveer el command /list para que cualquier agente consulte el registry
    4. Proveer el command /card @username para pedir la card de un agente

    El pinned message es la ÚNICA fuente de verdad de presencia.
    Los agentes leen el registry en memoria (CrewRegistry), no el mensaje.
    El mensaje anclado es solo para consumo humano (HITL).

    Formato del pinned message::

        🤖 AI-Parrot Crew · Online · 3 agentes
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        ✅ @orchestrator_bot · OrchestratorAgent
        ⏳ @data_bot · DataAgent · _procesando Q2..._
        ✅ @report_bot · ReportAgent
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        _Actualizado: 2026-02-22 10:15:30 UTC_
    """

    def __init__(
        self,
        token: str,
        username: str,
        group_id: int,
        registry: CrewRegistry,
    ):
        self.bot = Bot(token=token)
        self.username = username
        self.group_id = group_id
        self.registry = registry
        self._pinned_message_id: Optional[int] = None
        self._update_lock = asyncio.Lock()

    async def start(self) -> None:
        """Enviar y anclar el mensaje inicial del registry."""
        text = self._render_registry()
        msg: Message = await self.bot.send_message(
            chat_id=self.group_id,
            text=text,
            parse_mode="Markdown",
        )
        self._pinned_message_id = msg.message_id
        await self.bot.pin_chat_message(
            chat_id=self.group_id,
            message_id=msg.message_id,
            disable_notification=True,
        )

    async def stop(self) -> None:
        """Marcar todos los agentes como offline y actualizar pinned."""
        # El registry ya habrá sido vaciado por TelegramCrewTransport.stop()
        await self.update_registry()
        await self.bot.session.close()

    async def on_agent_join(self, card: AgentCard) -> None:
        """Llamado cuando un agente se une. Actualiza el pinned message."""
        self.registry.register(card)
        await self.update_registry()

    async def on_agent_leave(self, username: str) -> None:
        """Llamado cuando un agente se va. Actualiza el pinned message."""
        self.registry.unregister(username)
        await self.update_registry()

    async def on_agent_status_change(
        self, username: str, status: str, task: Optional[str] = None
    ) -> None:
        """Actualizar estado de un agente en el pinned message."""
        self.registry.update_status(username, status, task)
        await self.update_registry()

    async def update_registry(self) -> None:
        """Editar el pinned message con el estado actual del registry."""
        if not self._pinned_message_id:
            return
        async with self._update_lock:
            text = self._render_registry()
            try:
                await self.bot.edit_message_text(
                    chat_id=self.group_id,
                    message_id=self._pinned_message_id,
                    text=text,
                    parse_mode="Markdown",
                )
            except Exception:
                pass  # Ignorar "message not modified" de Telegram

    def _render_registry(self) -> str:
        """Renderizar el contenido del pinned message."""
        from datetime import datetime, timezone
        agents = self.registry.list_active()
        count = len(agents)

        header = f"🤖 *AI\\-Parrot Crew* · Online · {count} agente{'s' if count != 1 else ''}\n"
        separator = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

        if not agents:
            body = "_No hay agentes online_\n"
        else:
            body = "\n".join(card.to_registry_line() for card in agents) + "\n"

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        footer = f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n_Actualizado: {ts}_"

        return header + separator + body + footer
```

### 4.3. CrewAgentWrapper

Extiende `TelegramAgentWrapper` con comportamiento específico del crew: silencio durante tool calls, @mention obligatorio, anuncio de AgentCard, y envío de adjuntos.

```python
# parrot/integrations/telegram/crew/crew_wrapper.py
from __future__ import annotations
import asyncio
import tempfile
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, FSInputFile
from aiogram.enums import ChatType, ChatAction

from .agent_card import AgentCard, AgentSkill
from .mention import MentionBuilder
from .payload import DataPayload

if TYPE_CHECKING:
    from .transport import TelegramCrewTransport
    from .config import CrewAgentEntry


class CrewAgentWrapper:
    """
    Wrapper de agente AI-Parrot para el contexto de crew de Telegram.

    Diferencias clave vs TelegramAgentWrapper:
    - Solo escucha mensajes del grupo configurado (no privados)
    - Solo responde si es mencionado (@username)
    - Respuestas SIEMPRE incluyen @mention al remitente
    - Los tool calls internos NO se publican (silent_tool_calls)
    - Emite AgentCard al unirse al grupo
    - Puede enviar y recibir documentos adjuntos como DataPayload
    - Notifica al CoordinatorBot cambios de estado (busy/ready)
    """

    def __init__(
        self,
        agent,
        bot: Bot,
        entry: "CrewAgentEntry",
        transport: "TelegramCrewTransport",
    ):
        self.agent = agent
        self.bot = bot

…(truncated)…
