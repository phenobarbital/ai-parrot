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
    model: str                           # "google:gemini-2.0-flash"
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
        self.entry = entry
        self.transport = transport
        self.config = transport.config
        self.router = Router()
        self._dp = Dispatcher()
        self._dp.include_router(self.router)
        self.card: Optional[AgentCard] = None
        self._mention_builder = MentionBuilder()
        self._payload = DataPayload(
            bot=bot,
            group_id=self.config.group_id,
            temp_dir=Path(self.config.temp_dir),
        )
        self._register_handlers()

    async def start(self) -> None:
        """Iniciar: construir AgentCard, registrar en coordinator, anunciar."""
        bot_info = await self.bot.get_me()

        self.card = AgentCard(
            agent_id=self.entry.chatbot_id,
            agent_name=self.agent.name if hasattr(self.agent, 'name') else self.entry.chatbot_id,
            telegram_username=bot_info.username,
            telegram_user_id=bot_info.id,
            model=getattr(self.agent, 'llm_name', 'unknown'),
            skills=[AgentSkill(**s) for s in self.entry.skills],
            tags=self.entry.tags,
            accepts_files=self.entry.accepts_files,
            emits_files=self.entry.emits_files,
        )

        # Notificar al coordinator (actualiza pinned message)
        if self.transport.coordinator:
            await self.transport.coordinator.on_agent_join(self.card)

        # Anunciar AgentCard en el grupo
        if self.config.announce_on_join:
            await self.bot.send_message(
                chat_id=self.config.group_id,
                text=self.card.to_telegram_text(),
                parse_mode="Markdown",
            )

    async def run_polling(self) -> None:
        """Iniciar polling de mensajes del grupo."""
        await self._dp.start_polling(
            self.bot,
            allowed_updates=["message"],
        )

    # ── Handlers ──────────────────────────────────────────────────────────

    def _register_handlers(self) -> None:
        """Registrar handlers de mensajes."""
        from ..filters import BotMentionedFilter

        # Mensajes con @mention en el grupo del crew
        self.router.message.register(
            self._handle_crew_mention,
            BotMentionedFilter(),
            F.chat.id == self.config.group_id,
            F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
        )

        # Documentos adjuntos mencionando al bot
        self.router.message.register(
            self._handle_crew_document,
            F.document.as_("document"),
            F.chat.id == self.config.group_id,
        )

    async def _handle_crew_mention(self, message: Message) -> None:
        """
        Handler principal: procesa @mention en el crew channel.

        Flujo:
        1. Extraer query (sin @mention)
        2. Identificar remitente (humano o bot)
        3. Actualizar estado a "busy" en el coordinator
        4. Ejecutar agent.ask() - sin publicar tool calls
        5. Formatear respuesta con @mention al remitente
        6. Enviar resultado (texto y/o adjuntos)
        7. Actualizar estado a "ready"
        """
        from ..utils import extract_query_from_mention

        # Identificar remitente
        sender_mention = self._get_sender_mention(message)
        query = await extract_query_from_mention(message, self.bot)

        if not query:
            return

        # Verificar si hay documento adjunto adjunto al mensaje de texto
        # (e.g., caption de un documento que menciona al bot)
        incoming_file: Optional[Path] = None
        if message.document:
            incoming_file = await self._payload.download_document(message.document)

        # Marcar como ocupado
        await self._set_status("busy", query[:60])

        # Typing indicator mientras procesa
        typing_task = asyncio.create_task(
            self._typing_loop(message.chat.id)
        )

        try:
            # Construir pregunta enriquecida
            enriched_query = query
            if incoming_file:
                enriched_query = (
                    f"{query}\n\n[Archivo adjunto: {incoming_file}]"
                )

            # === Llamada al agente (silenciosa) ===
            # agent.ask() puede hacer N tool calls internamente.
            # Nada de eso se publica. Solo el resultado final llega aquí.
            response = await self.agent.ask(enriched_query)

            typing_task.cancel()

            # Extraer texto y posibles archivos de la respuesta
            response_text, output_files = self._parse_agent_response(response)

            # Responder con @mention al remitente
            await self._reply_with_mention(
                message=message,
                sender_mention=sender_mention,
                text=response_text,
                files=output_files,
            )

        except Exception as e:
            typing_task.cancel()
            await self.bot.send_message(
                chat_id=self.config.group_id,
                text=f"{sender_mention} ❌ Error procesando tu solicitud: {str(e)[:200]}",
                parse_mode="Markdown",
                reply_to_message_id=message.message_id,
            )
        finally:
            typing_task.cancel()
            await self._set_status("ready")

    async def _handle_crew_document(self, message: Message) -> None:
        """
        Handler para documentos adjuntos enviados al grupo.
        
        Si el caption menciona a este bot, procesa el documento como input.
        Permite que otros agentes o el humano envíen datasets al agente.
        """
        if not message.caption:
            return

        bot_info = await self.bot.get_me()
        if f"@{bot_info.username}" not in (message.caption or ""):
            return

        # Reusar el handler de mención con el documento disponible
        await self._handle_crew_mention(message)

    # ── Respuesta con @mention ────────────────────────────────────────────

    async def _reply_with_mention(
        self,
        message: Message,
        sender_mention: str,
        text: str,
        files: list,
    ) -> None:
        """
        Enviar respuesta al grupo con @mention obligatorio al remitente.

        Si hay archivos, se envían como documentos adjuntos con el texto
        como caption del primer archivo, o como mensaje separado previo.
        """
        # Preparar texto con @mention
        full_text = f"{sender_mention} {text}" if text else sender_mention
        max_len = self.config.max_message_length

        if not files:
            # Solo texto: enviar con reply al mensaje original
            await self._send_text_chunked(
                chat_id=message.chat.id,
                text=full_text,
                reply_to=message.message_id,
            )
        else:
            # Hay archivos: el texto es caption del primer archivo
            # Los archivos adicionales van sin caption
            caption = full_text[:1024] if full_text else sender_mention
            remainder_text = full_text[1024:] if len(full_text) > 1024 else ""

            for i, file_path in enumerate(files):
                file_caption = caption if i == 0 else file_path.name[:200]
                await self.bot.send_document(
                    chat_id=message.chat.id,
                    document=FSInputFile(file_path),
                    caption=file_caption,
                    parse_mode="Markdown",
                    reply_to_message_id=message.message_id if i == 0 else None,
                )
                await asyncio.sleep(0.5)  # Rate limiting

            if remainder_text:
                await self.bot.send_message(
                    chat_id=message.chat.id,
                    text=remainder_text,
                    parse_mode="Markdown",
                )

    async def _send_text_chunked(
        self, chat_id: int, text: str, reply_to: Optional[int] = None
    ) -> None:
        """Enviar texto dividiéndolo si supera max_message_length."""
        max_len = self.config.max_message_length
        if len(text) <= max_len:
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
                reply_to_message_id=reply_to,
            )
            return

        chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]
        for i, chunk in enumerate(chunks):
            await self.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode="Markdown",
                reply_to_message_id=reply_to if i == 0 else None,
            )
            await asyncio.sleep(0.3)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _get_sender_mention(self, message: Message) -> str:
        """Obtener el @mention del remitente (humano o bot)."""
        if message.from_user:
            if message.from_user.username:
                return f"@{message.from_user.username}"
            return f"[{message.from_user.full_name}](tg://user?id={message.from_user.id})"
        return ""

    def _parse_agent_response(self, response) -> tuple[str, list]:
        """
        Extraer texto y archivos de la respuesta del agente.
        
        Returns:
            (text, list_of_Path_files)
        """
        if isinstance(response, str):
            return response, []

        text = ""
        files = []

        if hasattr(response, 'content'):
            text = str(response.content)
        elif hasattr(response, 'text'):
            text = str(response.text)
        else:
            text = str(response)

        if hasattr(response, 'files') and response.files:
            files = [Path(f) for f in response.files if Path(f).exists()]

        return text, files

    async def _set_status(
        self, status: str, task: Optional[str] = None
    ) -> None:
        """Notificar cambio de estado al CoordinatorBot."""
        if self.card:
            self.card.status = status
            self.card.current_task = task
        if self.transport.coordinator:
            await self.transport.coordinator.on_agent_status_change(
                self.entry.username, status, task
            )

    async def _typing_loop(self, chat_id: int) -> None:
        """Loop de typing indicator mientras el agente procesa."""
        try:
            while True:
                await self.bot.send_chat_action(
                    chat_id=chat_id,
                    action=ChatAction.TYPING,
                )
                await asyncio.sleep(4)  # Telegram typing dura ~5s
        except asyncio.CancelledError:
            pass

    # ── API pública (usada por TelegramCrewTransport) ─────────────────────

    async def send_crew_message(
        self,
        mention: str,
        text: str,
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        """Enviar mensaje al grupo con @mention."""
        full_text = f"{mention} {text}"
        await self.bot.send_message(
            chat_id=self.config.group_id,
            text=full_text[:self.config.max_message_length],
            parse_mode="Markdown",
            reply_to_message_id=reply_to_message_id,
        )

    async def send_crew_document(
        self,
        mention: str,
        file_path: Path,
        caption: str = "",
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        """Enviar documento al grupo con @mention en el caption."""
        full_caption = f"{mention} {caption}"[:1024]
        await self.bot.send_document(
            chat_id=self.config.group_id,
            document=FSInputFile(file_path),
            caption=full_caption,
            parse_mode="Markdown",
            reply_to_message_id=reply_to_message_id,
        )
```

### 4.4. DataPayload

Gestión de envío y recepción de archivos entre agentes como documentos adjuntos.

```python
# parrot/integrations/telegram/crew/payload.py
from __future__ import annotations
import mimetypes
import tempfile
from pathlib import Path
from typing import Optional
import aiofiles
import aiohttp

from aiogram import Bot
from aiogram.types import Document, FSInputFile


# Tipos MIME permitidos → extensión esperada
ALLOWED_TYPES: dict[str, str] = {
    "text/csv": ".csv",
    "application/json": ".json",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/parquet": ".parquet",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
}


class DataPayload:
    """
    Gestión de archivos entre agentes vía Telegram (documentos adjuntos).

    Permite que un agente:
    - Descargue un documento que alguien envió al grupo
    - Suba un archivo generado como documento al grupo

    Los archivos temporales se guardan en temp_dir y deben ser limpiados
    por el caller una vez procesados.

    Principios:
    - No hay DMs inter-bot: los archivos pasan por el grupo
    - El caption del documento contiene el @mention del destinatario
    - El tipo MIME se valida antes de descargar
    """

    def __init__(self, bot: Bot, group_id: int, temp_dir: Path):
        self.bot = bot
        self.group_id = group_id
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def download_document(
        self,
        document: Document,
        allowed_types: Optional[list[str]] = None,
    ) -> Optional[Path]:
        """
        Descargar un documento de Telegram a un archivo temporal.

        Args:
            document: Objeto Document de aiogram
            allowed_types: Lista de MIME types permitidos. None = todos los de ALLOWED_TYPES

        Returns:
            Path al archivo descargado, o None si el tipo no está permitido
        """
        mime = document.mime_type or "application/octet-stream"
        permitted = allowed_types or list(ALLOWED_TYPES.keys())

        if mime not in permitted:
            return None

        ext = ALLOWED_TYPES.get(mime, "") or Path(document.file_name or "").suffix

        # Generar nombre temporal
        tmp_path = self.temp_dir / f"{document.file_unique_id}{ext}"

        if tmp_path.exists():
            return tmp_path  # Ya descargado

        # Descargar via aiogram
        file_info = await self.bot.get_file(document.file_id)
        await self.bot.download_file(file_info.file_path, destination=tmp_path)

        return tmp_path

    async def send_document(
        self,
        file_path: Path,
        mention: str,
        caption: str = "",
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        """
        Enviar un archivo al grupo con @mention en el caption.

        Args:
            file_path: Ruta al archivo a enviar
            mention: @mention del destinatario (e.g., "@data_bot" o "@jesus")
            caption: Texto descriptivo adicional
            reply_to_message_id: Opcional: reply al mensaje original
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        full_caption = f"{mention} {caption}"[:1024] if caption else mention

        await self.bot.send_document(
            chat_id=self.group_id,
            document=FSInputFile(file_path, filename=file_path.name),
            caption=full_caption,
            parse_mode="Markdown",
            reply_to_message_id=reply_to_message_id,
        )

    async def send_csv(
        self,
        data,              # pandas DataFrame o lista de dicts
        filename: str,
        mention: str,
        caption: str = "",
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        """
        Serializar datos como CSV y enviar al grupo.

        Convenience method para el caso de uso más común:
        un agente genera datos y los comparte con otro agente o con el humano.
        """
        import pandas as pd
        import io

        if not isinstance(data, pd.DataFrame):
            data = pd.DataFrame(data)

        tmp = self.temp_dir / filename
        data.to_csv(tmp, index=False, encoding="utf-8")
        await self.send_document(tmp, mention, caption, reply_to_message_id)

    def cleanup(self, file_path: Path) -> None:
        """Eliminar archivo temporal después de procesarlo."""
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass
```

### 4.5. CrewRegistry

Estado en memoria de qué agentes están online. La fuente de verdad para routing; el pinned message de Telegram es solo su reflejo visual.

```python
# parrot/integrations/telegram/crew/registry.py
from __future__ import annotations
from typing import Dict, List, Optional
from datetime import datetime, timezone
import threading

from .agent_card import AgentCard


class CrewRegistry:
    """
    Registro en memoria de agentes activos en el crew channel.

    Thread-safe (usa threading.Lock para compatibilidad con aiogram).
    El estado persiste solo mientras el proceso está vivo.
    Para persistencia cross-restart, se puede extender con Redis.
    """

    def __init__(self):
        self._agents: Dict[str, AgentCard] = {}
        self._lock = threading.Lock()

    def register(self, card: AgentCard) -> None:
        """Registrar un agente como online."""
        with self._lock:
            card.joined_at = datetime.now(timezone.utc)
            card.last_seen = card.joined_at
            self._agents[card.telegram_username] = card

    def unregister(self, username: str) -> Optional[AgentCard]:
        """Eliminar un agente del registry."""
        with self._lock:
            return self._agents.pop(username, None)

    def update_status(
        self,
        username: str,
        status: str,
        current_task: Optional[str] = None,
    ) -> None:
        """Actualizar estado de un agente."""
        with self._lock:
            if username in self._agents:
                self._agents[username].status = status
                self._agents[username].current_task = current_task
                self._agents[username].last_seen = datetime.now(timezone.utc)

    def get(self, username: str) -> Optional[AgentCard]:
        """Obtener card de un agente por username."""
        with self._lock:
            return self._agents.get(username)

    def list_active(self) -> List[AgentCard]:
        """Listar agentes con status != 'offline'."""
        with self._lock:
            return [
                card for card in self._agents.values()
                if card.status != "offline"
            ]

    def resolve(self, name_or_username: str) -> Optional[AgentCard]:
        """Resolver agente por @username o agent_name."""
        clean = name_or_username.lstrip("@")
        with self._lock:
            if clean in self._agents:
                return self._agents[clean]
            for card in self._agents.values():
                if card.agent_name.lower() == clean.lower():
                    return card
        return None
```

---

## 5. Configuración YAML

```yaml
# env/telegram_crew.yaml

crew:
  group_id: -1001234567890

  # Bot coordinador (solo gestiona el pinned registry, no es un agente)
  coordinator_token: "${PARROT_COORDINATOR_TELEGRAM_TOKEN}"
  coordinator_username: "parrot_coordinator_bot"

  # IDs de Telegram de los usuarios humanos con acceso HITL
  hitl_user_ids:
    - 123456789  # jesus

  # Comportamiento global
  announce_on_join: true
  update_pinned_registry: true
  reply_to_sender: true
  silent_tool_calls: true
  typing_indicator: true
  max_message_length: 4000
  temp_dir: "/tmp/parrot_crew"
  max_file_size_mb: 50

  # Agentes del crew
  agents:

    OrchestratorAgent:
      chatbot_id: orchestrator_agent
      bot_token: "${ORCHESTRATOR_TELEGRAM_TOKEN}"
      username: orchestrator_parrot_bot
      tags: [orchestration, planning, delegation]
      skills:
        - name: orchestrate
          description: Coordina múltiples agentes especializados para tareas complejas
          input_types: [text]
          output_types: [text]

    DataAgent:
      chatbot_id: data_agent
      bot_token: "${DATA_TELEGRAM_TOKEN}"
      username: data_parrot_bot
      tags: [data, analytics, sql]
      accepts_files: [csv, json, xlsx, parquet]
      emits_files: [csv, json, png]
      skills:
        - name: data_extraction
          description: Extrae y transforma datos de múltiples fuentes
          input_types: [text, csv, json]
          output_types: [csv, json]
        - name: visualization
          description: Genera gráficos y reportes visuales
          input_types: [csv, json]
          output_types: [png]

    ReportAgent:
      chatbot_id: report_agent
      bot_token: "${REPORT_TELEGRAM_TOKEN}"
      username: report_parrot_bot
      tags: [reports, writing, executive]
      accepts_files: [csv, json, txt]
      emits_files: [pdf, txt]
      skills:
        - name: executive_report
          description: Genera reportes ejecutivos estructurados
          input_types: [text, csv, json]
          output_types: [pdf, txt]
```

---

## 6. Integración con el Sistema Existente

### 6.1. Arranque desde BotManager

El `TelegramCrewTransport` se registra como un servicio adicional en el `BotManager`, de forma similar a como el `TelegramBotManager` actual se integra en el startup:

```python
# En el startup de la aplicación AI-Parrot

from parrot.integrations.telegram.crew import TelegramCrewTransport
from parrot.integrations.telegram.crew.config import TelegramCrewConfig

async def on_startup(app):
    # ... inicialización normal de BotManager ...
    
    # Verificar si hay configuración de crew
    crew_config_path = Path("env/telegram_crew.yaml")
    if crew_config_path.exists():
        crew_config = TelegramCrewConfig.from_yaml(crew_config_path)
        crew_transport = TelegramCrewTransport(
            config=crew_config,
            bot_manager=app["bot_manager"],
        )
        app["telegram_crew"] = crew_transport
        await crew_transport.start()

async def on_shutdown(app):
    if "telegram_crew" in app:
        await app["telegram_crew"].stop()
```

### 6.2. Herencia vs Composición

El `CrewAgentWrapper` usa **composición** sobre el `TelegramAgentWrapper` existente, no herencia directa. Esto es deliberado:

- `TelegramAgentWrapper` está optimizado para 1-a-1 (bot ↔ usuario)
- `CrewAgentWrapper` tiene semántica diferente (N-a-N, grupo exclusivo, @mention obligatorio)
- Evitamos romper el contrato del wrapper existente
- Ambos pueden coexistir: el mismo agente puede ser accesible por DM (via `TelegramAgentWrapper`) y por el crew (via `CrewAgentWrapper`)

### 6.3. Reutilización de Componentes Existentes

| Componente existente | Uso en TelegramCrewTransport |
|---|---|
| `BotMentionedFilter` | Reutilizado directamente en `CrewAgentWrapper._register_handlers()` |
| `extract_query_from_mention` | Reutilizado para extraer el query limpio |
| `TelegramHumanChannel` | Compatible: el HITL en el crew sigue siendo el humano con @mention; para approval flows complejos se puede usar en paralelo |
| `NavigatorAuthClient` | No se usa en el crew (el grupo cerrado actúa como auth) |
| `OutputMode.TELEGRAM` | Reutilizado en `agent.ask()` para formatting |

---

## 7. Flujos de Trabajo Detallados

### 7.1. Arranque del Crew

```
TelegramCrewTransport.start()
    │
    ├── CoordinatorBot.start()
    │       └── send_message(group, "🤖 AI-Parrot Crew · Online · 0 agentes")
    │       └── pin_chat_message(message_id)
    │
    ├── CrewAgentWrapper("OrchestratorAgent").start()
    │       ├── get_me() → bot_info
    │       ├── AgentCard(...)  ← construir card
    │       ├── coordinator.on_agent_join(card)
    │       │       └── registry.register(card)
    │       │       └── edit_message(pinned_id, "✅ @orchestrator_bot...")
    │       └── send_message(group, card.to_telegram_text())
    │
    ├── CrewAgentWrapper("DataAgent").start()
    │       └── [ídem]
    │
    └── CrewAgentWrapper("ReportAgent").start()
            └── [ídem]
```

### 7.2. HITL → Agente (Pregunta del Humano)

```
@jesus: "@data_parrot_bot dame el CSV de ventas Q2"
    │
    ├── BotMentionedFilter() → True para data_parrot_bot
    ├── CrewAgentWrapper._handle_crew_mention(message)
    │       ├── sender_mention = "@jesus"
    │       ├── query = "dame el CSV de ventas Q2"
    │       ├── _set_status("busy", "dame el CSV de ventas Q2")
    │       │       └── coordinator.on_agent_status_change(...)
    │       │       └── edit_message(pinned, "⏳ @data_bot · DataAgent · dame el CSV...")
    │       │
    │       ├── [typing indicator activo]
    │       │
    │       ├── agent.ask("dame el CSV de ventas Q2")
    │       │       ├── [tool: query_database("SELECT ... FROM sales WHERE quarter='Q2'")]
    │       │       ├── [tool: export_to_csv(results)]  ← silencioso, no publicado
    │       │       └── return AIMessage(content="Aquí tienes...", files=["/tmp/q2.csv"])
    │       │
    │       ├── _parse_agent_response(response) → ("Aquí tienes...", [Path("/tmp/q2.csv")])
    │       │
    │       └── _reply_with_mention(mention="@jesus", text="Aquí tienes...", files=[...])
    │               └── send_document(group, q2.csv, caption="@jesus Aquí tienes el CSV...")
    │
    └── _set_status("ready")
            └── edit_message(pinned, "✅ @data_bot · DataAgent")
```

### 7.3. Agente → Agente (Delegación)

```
@orchestrator_bot: "@data_parrot_bot necesito las métricas de Q2 para el reporte"
    │
    └── [mismo flujo que HITL→Agente]
        sender_mention = "@orchestrator_parrot_bot"
        
        DataAgent procesa y responde:
        "@orchestrator_parrot_bot Aquí tienes las métricas" + [adjunto: metrics.csv]
    │
    └── OrchestratorAgent recibe el resultado (via message handler si también escucha)
        y puede delegar el CSV al ReportAgent:
        "@report_parrot_bot adjunto las métricas Q2, genera el reporte ejecutivo"
        [adjunto reenviado: metrics.csv con caption que menciona a @report_parrot_bot]
```

### 7.4. Salida de un Agente

```
TelegramCrewTransport.stop()
    │
    ├── registry.unregister("data_parrot_bot")
    ├── coordinator.on_agent_leave("data_parrot_bot")
    │       └── edit_message(pinned, eliminar línea del DataAgent)
    └── [ídem para todos los agentes]
```

---

## 8. Limitaciones Conocidas y Mitigaciones

### 8.1. Bot-to-Bot Message Filtering

**Limitación**: Telegram filtra por defecto los mensajes enviados por bots a otros bots en grupos.

**Mitigación**: En aiogram v3, se puede configurar `allowed_updates` para incluir mensajes de bots usando el parámetro `allow_sending_without_reply`. Para que un bot reciba mensajes de otros bots en el grupo, cada bot debe ser configurado con:

```python
# En run_polling de cada CrewAgentWrapper
await self._dp.start_polling(
    self.bot,
    allowed_updates=["message"],
    # Los mensajes de bots se reciben si el bot NO tiene el flag
    # "Block bots" activado — el default en grupos normales los filtra.
    # Solución: usar bot.get_updates con offset explícito y sin filtro,
    # o configurar el bot via BotFather con /setjoingroups y grupos de bots.
)
```

La solución más robusta es que el `CoordinatorBot` actúe como proxy: cuando un agente quiere "enviarle" algo a otro agente, lo publica en el grupo (visible para todos), y el bot destinatario lo lee de ahí. Esto es exactamente el modelo propuesto.

### 8.2. Rate Limits de Telegram

**Limitación**: 30 mensajes/segundo por bot, 1 mensaje/segundo en el mismo chat.

**Mitigación**: 
- Los tool calls internos son silenciosos → drástica reducción de mensajes
- `asyncio.sleep(0.3-0.5)` entre mensajes consecutivos en `_send_text_chunked`
- Para crews con alta actividad, implementar una cola de mensajes con debouncing

### 8.3. Tamaño de Mensaje

**Limitación**: 4096 caracteres por mensaje, 1024 caracteres para captions.

**Mitigación**: 
- `_send_text_chunked()` divide automáticamente textos largos
- Respuestas muy largas se convierten en documentos `.txt` adjuntos
- El `max_message_length` configurable (default: 4000 para margen de seguridad)

### 8.4. Tamaño de Archivos

**Limitación**: 50 MB por archivo en Telegram (bots). 

**Mitigación**:
- `max_file_size_mb` configurable en `TelegramCrewConfig`
- Para archivos más grandes: comprimir en ZIP, o fragmentar CSVs grandes
- Para producción: usar S3/GCS y enviar solo el URL en el mensaje

---

## 9. Extensiones Futuras

### 9.1. Comandos del Coordinator

El `CoordinatorBot` puede extenderse con comandos útiles para el HITL:

| Comando | Acción |
|---|---|
| `/list` | Mostrar lista de agentes con sus skills |
| `/card @username` | Mostrar AgentCard completa de un agente |
| `/status` | Estado actual del crew (busy/ready por agente) |
| `/history` | Últimas N interacciones del activity feed |

### 9.2. Convergencia con FilesystemTransport

En un escenario donde AI-Parrot usa `FilesystemTransport` para coordinación local y `TelegramCrewTransport` para visibilidad HITL, los dos transports pueden coexistir sobre el mismo `AgentCrew`:

```
AgentCrew
├── FilesystemTransport  ← coordinación rápida local (sub-50ms)
└── TelegramCrewTransport ← visibilidad HITL + override del humano
```

El `TelegramCrewTransport` en este modo solo publica los resultados finales de cada tarea del crew, no el detalle de la coordinación interna entre agentes.

### 9.3. Convergencia con Matrix

Si en el futuro AI-Parrot implementa un `MatrixTransport`, el modelo conceptual es idéntico al `TelegramCrewTransport`:

| Concepto | TelegramCrewTransport | MatrixTransport |
|---|---|---|
| Channel | Supergrupo | Room |
| Pinned Registry | Mensaje anclado editado por coordinator | State event `m.parrot.registry` |
| AgentCard | Mensaje de anuncio | State event `m.parrot.agent_card` |
| @mention | Telegram entity | Matrix mention |
| DataPayload | `send_document()` | `m.file` event |

La transición de Telegram a Matrix preserva el mismo paradigma de diseño, solo cambia la capa de transporte.

---

## 10. Resumen de lo que Falta vs. lo que Existe

| Componente | Estado | Esfuerzo estimado |
|---|---|---|
| `BotMentionedFilter` | ✅ Existe | — |
| `extract_query_from_mention` | ✅ Existe | — |
| `TelegramBotManager` (multi-bot) | ✅ Existe | — |
| `FSInputFile` / `send_document` | ✅ Existe en wrapper | — |
| `TelegramCrewConfig` (Pydantic) | ❌ Nuevo | 2h |
| `AgentCard` schema + renderer | ❌ Nuevo | 3h |
| `CrewRegistry` (in-memory) | ❌ Nuevo | 2h |
| `CoordinatorBot` (pinned registry) | ❌ Nuevo | 4h |
| `CrewAgentWrapper` (silent calls, @mention) | ❌ Nuevo | 6h |
| `DataPayload` (CSV/JSON adjuntos) | ❌ Nuevo | 3h |
| `TelegramCrewTransport` (orquestador) | ❌ Nuevo | 4h |
| YAML config + integración BotManager | ❌ Nuevo | 2h |
| **Total estimado** | | **~26h** |

---

*AI-Parrot Framework · TelegramCrewTransport Architecture · Draft v0.1 · Feb 2026*
