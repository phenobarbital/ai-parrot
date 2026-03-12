# Feature Specification: Matrix Multi-Agent Crew Integration

**Feature ID**: FEAT-044
**Date**: 2026-03-11
**Author**: AI-Parrot Team
**Status**: approved
**Target version**: 1.6.0

---

## 1. Motivation & Business Requirements

> Enable multiple AI agents to operate simultaneously in Matrix rooms — each agent in its own room and all agents sharing a common room — mirroring the Telegram crew pattern for the Matrix protocol.

### Problem Statement

The current `parrot/integrations/matrix/` module supports a single-agent model:

1. **Single bot only**: `MatrixClientWrapper` manages one homeserver connection and one MXID. There is no orchestration layer for multiple agents.
2. **No crew coordination**: Unlike Telegram's `TelegramCrewTransport` (with `CrewRegistry`, `CoordinatorBot`, `CrewAgentWrapper`), Matrix has no multi-agent lifecycle management.
3. **No mention-based routing**: Messages in shared rooms cannot be routed to specific agents via `@mention`.
4. **No status board**: No coordinator bot to maintain a pinned status message showing agent availability.
5. **No per-agent rooms**: No mechanism for agents to own private rooms while also participating in a shared "general" room.

**Existing foundation** (ready to build on):
- `MatrixAppService` — provides virtual MXIDs per agent via the Application Service protocol.
- `MatrixA2ATransport` — agent-to-agent communication using custom `m.parrot.*` events.
- `MatrixClientWrapper` — async client wrapper with message sending, editing, event handling.
- `MatrixStreamHandler` — edit-based token streaming.
- Custom event types (`events.py`) — `AGENT_CARD`, `TASK`, `RESULT`, `STATUS`.

**Reference implementation**: `parrot/integrations/telegram/crew/` (7 modules, ~1,200 lines).

### Goals
- Support N agents in a single shared Matrix room with `@mention`-based routing.
- Support each agent having its own dedicated Matrix room for private conversations.
- Provide a coordinator bot that maintains a pinned status board in the shared room.
- Implement an agent registry tracking status (ready/busy/offline), current task, and last seen.
- Leverage `MatrixAppService` for virtual MXIDs (one per agent) managed by a single homeserver connection.
- Provide a YAML-based configuration for crew setup (parallel to `TelegramCrewConfig`).
- Create a comprehensive example script with documentation showing how to launch a crew with per-agent rooms + a shared general room.
- Integrate with `BotManager` for agent resolution (via `chatbot_id`).

### Non-Goals (explicitly out of scope)
- Federation across multiple homeservers (agents must be on the same homeserver).
- End-to-end encryption (E2EE) support for agent messages (future enhancement).
- Voice/video call integration.
- Replacing or modifying `AgentCrew` orchestration — this feature operates at the chat-protocol level, not the workflow level.
- Bridging Matrix rooms to Telegram crews or other platforms.

---

## 2. Architectural Design

### Overview

Create a `parrot/integrations/matrix/crew/` subpackage that mirrors Telegram's crew pattern, adapted for Matrix's protocol specifics (Application Service virtual users, room state events, `m.replace` edits). A top-level `MatrixCrewTransport` orchestrates per-agent wrappers, a coordinator bot, and the agent registry.

### Component Diagram

```
                     ┌────────────────────────────────────────┐
                     │         MatrixCrewTransport            │
                     │   (top-level orchestrator, lifecycle)   │
                     └──────────────────┬─────────────────────┘
                                        │
           ┌────────────────────────────┼─────────────────────────┐
           │                            │                         │
           ▼                            ▼                         ▼
┌─────────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐
│  MatrixCoordinator  │   │  MatrixCrewRegistry  │   │  MatrixCrewConfig    │
│  (pinned status     │   │  (agent tracking,    │   │  (YAML config,       │
│   board, lifecycle  │   │   status, lookup)    │   │   per-agent entries) │
│   hooks)            │   │                      │   │                      │
└─────────────────────┘   └──────────────────────┘   └──────────────────────┘
           │                            │
           │              ┌─────────────┼─────────────┐
           │              │             │             │
           ▼              ▼             ▼             ▼
┌─────────────────────────────┐  ┌──────────┐  ┌──────────┐
│  MatrixCrewAgentWrapper     │  │ Wrapper2 │  │ WrapperN │
│  (per-agent: mention route, │  │          │  │          │
│   typing, status notify,    │  └──────────┘  └──────────┘
│   response chunking)        │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────┐
│                    MatrixAppService                          │
│  (virtual MXIDs, HTTP push, event routing from homeserver)  │
└─────────────────────────────────────────────────────────────┘
           │
    ┌──────┴──────┐
    ▼             ▼
┌────────┐   ┌────────┐
│ Agent  │   │ Agent  │   ... (dedicated rooms)
│ Room 1 │   │ Room 2 │
└────────┘   └────────┘
    └────┬────┘
         ▼
   ┌──────────┐
   │ General  │   (shared room — all agents + coordinator)
   │  Room    │
   └──────────┘
```

### Room Topology

```
┌─────────────────────────────────────────────────────────┐
│                    GENERAL ROOM                          │
│  Members: @coordinator, @agent1, @agent2, ..., @agentN  │
│  Pinned: Status Board (updated by coordinator)          │
│  Routing: @mention → specific agent                     │
│  Fallback: unaddressed messages → configurable default  │
└─────────────────────────────────────────────────────────┘

┌──────────────┐  ┌──────────────┐       ┌──────────────┐
│  AGENT1 ROOM │  │  AGENT2 ROOM │  ...  │  AGENTN ROOM │
│  Members:    │  │  Members:    │       │  Members:    │
│   @agent1    │  │   @agent2    │       │   @agentN    │
│   (+ users)  │  │   (+ users)  │       │   (+ users)  │
│  Direct chat │  │  Direct chat │       │  Direct chat │
└──────────────┘  └──────────────┘       └──────────────┘
```

### Data Flow — Message in Shared Room

```
1. User sends: "@analyst What is AAPL's P/E ratio?"
2. Homeserver → MatrixAppService (HTTP push)
3. MatrixCrewTransport.on_room_message()
4. Parse mention → resolve to "analyst" agent
5. MatrixCrewRegistry.update_status("analyst", "busy", task="AAPL P/E")
6. MatrixCoordinator.refresh_status_board()
7. MatrixCrewAgentWrapper("analyst").handle_message()
   a. Send typing indicator (m.typing)
   b. agent = BotManager.get_bot(chatbot_id)
   c. response = await agent.ask(query)
   d. Send response as @analyst virtual user
8. MatrixCrewRegistry.update_status("analyst", "ready")
9. MatrixCoordinator.refresh_status_board()
```

### Data Flow — Message in Agent's Dedicated Room

```
1. User sends message in Agent1's room (no @mention needed)
2. Homeserver → MatrixAppService (HTTP push)
3. MatrixCrewTransport.on_room_message()
4. Room ID maps to agent1 (from config)
5. MatrixCrewAgentWrapper("agent1").handle_message()
   a. No mention parsing needed — room-level routing
   b. Process normally (typing, ask, respond)
6. Status updates propagated to General Room status board
```

---

## 3. Detailed Module Design

### 3.1 `parrot/integrations/matrix/crew/config.py` — MatrixCrewConfig

```python
class MatrixCrewAgentEntry(BaseModel):
    """Configuration for a single agent in the Matrix crew."""
    chatbot_id: str                          # BotManager lookup key
    display_name: str                        # Human-readable name
    mxid_localpart: str                      # e.g., "analyst" → @analyst:server.com
    avatar_url: str | None = None            # mxc:// URL for agent avatar
    dedicated_room_id: str | None = None     # Agent's own room (optional)
    skills: list[str] = []                   # Skill descriptions for status board
    tags: list[str] = []                     # Routing tags
    file_types: list[str] = []              # Accepted file MIME types

class MatrixCrewConfig(BaseModel):
    """Root configuration for a Matrix multi-agent crew."""
    homeserver_url: str                      # e.g., "https://matrix.example.com"
    server_name: str                         # e.g., "example.com"
    as_token: str                            # Application Service token
    hs_token: str                            # Homeserver token
    bot_mxid: str                            # Coordinator bot MXID
    general_room_id: str                     # Shared room for all agents
    agents: dict[str, MatrixCrewAgentEntry]  # agent_name → config
    appservice_port: int = 8449              # AS HTTP listener port
    pinned_registry: bool = True             # Pin status board in general room
    typing_indicator: bool = True            # Show typing while processing
    streaming: bool = True                   # Use edit-based streaming
    unaddressed_agent: str | None = None     # Default agent for unmentioned msgs
    max_message_length: int = 4096           # Chunk responses beyond this
```

**YAML config file** (`matrix_crew.yaml`):
```yaml
homeserver_url: "${MATRIX_HOMESERVER_URL}"
server_name: "${MATRIX_SERVER_NAME}"
as_token: "${MATRIX_AS_TOKEN}"
hs_token: "${MATRIX_HS_TOKEN}"
bot_mxid: "@parrot-coordinator:${MATRIX_SERVER_NAME}"
general_room_id: "!general:${MATRIX_SERVER_NAME}"
appservice_port: 8449
pinned_registry: true
typing_indicator: true
streaming: true
unaddressed_agent: "general-assistant"

agents:
  analyst:
    chatbot_id: "finance-analyst"
    display_name: "Financial Analyst"
    mxid_localpart: "analyst"
    dedicated_room_id: "!analyst-room:${MATRIX_SERVER_NAME}"
    skills:
      - "Stock analysis"
      - "Financial ratios"
    tags: ["finance", "stocks"]

  researcher:
    chatbot_id: "web-researcher"
    display_name: "Research Assistant"
    mxid_localpart: "researcher"
    dedicated_room_id: "!researcher-room:${MATRIX_SERVER_NAME}"
    skills:
      - "Web search"
      - "Document summarization"
    tags: ["research", "search"]

  general-assistant:
    chatbot_id: "general-bot"
    display_name: "General Assistant"
    mxid_localpart: "assistant"
    skills:
      - "General Q&A"
      - "Task coordination"
    tags: ["general"]
```

### 3.2 `parrot/integrations/matrix/crew/registry.py` — MatrixCrewRegistry

```python
class MatrixCrewRegistry:
    """Thread-safe registry tracking agent status in a Matrix crew."""

    async def register(self, card: MatrixAgentCard) -> None: ...
    async def unregister(self, agent_name: str) -> None: ...
    async def update_status(
        self, agent_name: str, status: str, current_task: str | None = None
    ) -> None: ...
    async def get(self, agent_name: str) -> MatrixAgentCard | None: ...
    async def get_by_mxid(self, mxid: str) -> MatrixAgentCard | None: ...
    async def all_agents(self) -> list[MatrixAgentCard]: ...

class MatrixAgentCard(BaseModel):
    """Agent identity and runtime status for Matrix crew."""
    agent_name: str
    display_name: str
    mxid: str                               # Full @user:server MXID
    status: str = "offline"                  # ready | busy | offline
    current_task: str | None = None
    skills: list[str] = []
    joined_at: datetime | None = None
    last_seen: datetime | None = None

    def to_status_line(self) -> str:
        """Render a status line for the pinned board."""
        ...
```

### 3.3 `parrot/integrations/matrix/crew/coordinator.py` — MatrixCoordinator

```python
class MatrixCoordinator:
    """Manages the pinned status board in the general room."""

    def __init__(
        self,
        client: MatrixClientWrapper,
        registry: MatrixCrewRegistry,
        general_room_id: str,
    ): ...

    async def start(self) -> None:
        """Create or update pinned status board message."""
        ...

    async def stop(self) -> None:
        """Post shutdown notice, clean up."""
        ...

    async def on_agent_join(self, card: MatrixAgentCard) -> None: ...
    async def on_agent_leave(self, agent_name: str) -> None: ...
    async def on_status_change(self, agent_name: str) -> None: ...
    async def refresh_status_board(self) -> None:
        """Re-render and edit the pinned message with current agent statuses."""
        ...
```

The status board is a pinned message in the general room, edited on every status change (rate-limited to avoid spam):

```
🤖 AI-Parrot Crew — Agent Status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 @analyst — Financial Analyst (ready)
   Skills: Stock analysis, Financial ratios
🟡 @researcher — Research Assistant (busy: summarizing report)
   Skills: Web search, Document summarization
🟢 @assistant — General Assistant (ready)
   Skills: General Q&A, Task coordination
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Last updated: 2026-03-11 14:32 UTC
```

### 3.4 `parrot/integrations/matrix/crew/crew_wrapper.py` — MatrixCrewAgentWrapper

```python
class MatrixCrewAgentWrapper:
    """Per-agent wrapper handling message routing, typing, and responses."""

    def __init__(
        self,
        agent_name: str,
        config: MatrixCrewAgentEntry,
        appservice: MatrixAppService,
        registry: MatrixCrewRegistry,
        coordinator: MatrixCoordinator,
    ): ...

    async def handle_message(
        self,
        room_id: str,
        sender: str,
        body: str,
        event_id: str,
    ) -> None:
        """Process an incoming message directed at this agent."""
        # 1. Update status → busy
        # 2. Send typing indicator via virtual MXID
        # 3. Resolve agent via BotManager.get_bot(chatbot_id)
        # 4. response = await agent.ask(query)
        # 5. Send response (with streaming if enabled)
        # 6. Update status → ready
        ...

    async def _send_response(
        self, room_id: str, response: str
    ) -> None:
        """Send response, chunking if needed, via agent's virtual MXID."""
        ...

    async def _send_typing(self, room_id: str) -> None:
        """Background task sending typing indicators."""
        ...
```

### 3.5 `parrot/integrations/matrix/crew/mention.py` — Mention Utilities

```python
def parse_mention(body: str, server_name: str) -> str | None:
    """Extract the agent localpart from a Matrix @mention.

    Handles both:
    - Plain text: "@analyst what is AAPL?"
    - Matrix pill: <a href="https://matrix.to/#/@analyst:server">analyst</a>

    Returns the localpart (e.g., "analyst") or None.
    """
    ...

def format_reply(agent_mxid: str, display_name: str, text: str) -> str:
    """Format a reply with proper Matrix mention markup."""
    ...

def build_pill(mxid: str, display_name: str) -> str:
    """Build a Matrix 'pill' HTML mention: <a href=...>display_name</a>."""
    ...
```

### 3.6 `parrot/integrations/matrix/crew/transport.py` — MatrixCrewTransport

```python
class MatrixCrewTransport:
    """Top-level orchestrator for a Matrix multi-agent crew.

    Manages the MatrixAppService, coordinator, registry, and per-agent wrappers.
    Supports async context manager for lifecycle management.
    """

    def __init__(self, config: MatrixCrewConfig): ...

    @classmethod
    def from_yaml(cls, path: str) -> "MatrixCrewTransport":
        """Load crew configuration from a YAML file."""
        ...

    async def start(self) -> None:
        """Initialize and start all components:
        1. Start MatrixAppService (register virtual users)
        2. Create agent wrappers
        3. Join agents to general room + dedicated rooms
        4. Start coordinator (pin status board)
        5. Register event callbacks for message routing
        """
        ...

    async def stop(self) -> None:
        """Graceful shutdown: unregister agents, stop coordinator, stop AS."""
        ...

    async def on_room_message(
        self, room_id: str, sender: str, body: str, event_id: str
    ) -> None:
        """Route incoming message to the correct agent wrapper.

        Routing logic:
        1. If room_id matches an agent's dedicated_room_id → route to that agent
        2. If message contains @mention → route to mentioned agent
        3. If unaddressed_agent is configured → route to default agent
        4. Otherwise → ignore
        """
        ...

    async def __aenter__(self) -> "MatrixCrewTransport": ...
    async def __aexit__(self, *exc) -> None: ...
```

### 3.7 `parrot/integrations/matrix/crew/__init__.py` — Exports

```python
from .config import MatrixCrewConfig, MatrixCrewAgentEntry
from .registry import MatrixCrewRegistry, MatrixAgentCard
from .coordinator import MatrixCoordinator
from .crew_wrapper import MatrixCrewAgentWrapper
from .transport import MatrixCrewTransport
from .mention import parse_mention, format_reply, build_pill
```

---

## 4. Integration Points

### 4.1 BotManager Integration
Each agent entry references a `chatbot_id` that resolves via `BotManager.get_bot()`.
The bot must be pre-configured in the BotManager before starting the crew.

### 4.2 MatrixAppService Reuse
`MatrixCrewTransport` wraps the existing `MatrixAppService` to:
- Register virtual MXIDs for each agent.
- Use `appservice.bot_intent(mxid)` to send messages as specific agents.
- Receive events via the AS HTTP push callback.

### 4.3 MatrixA2ATransport (Optional)
For inter-agent communication within the crew, agents can use `MatrixA2ATransport.send_task()` to delegate sub-tasks to other agents via custom `m.parrot.task` events.

### 4.4 IntegrationManager Extension
Update `parrot/integrations/manager.py` to support a `matrix_crew` section:
```python
# In IntegrationManager.start()
if "matrix_crew" in config:
    transport = MatrixCrewTransport.from_yaml(config["matrix_crew"])
    await transport.start()
    self.matrix_crew = transport
```

### 4.5 Hooks Integration
The crew transport emits `HookEvent` for each message (parallel to Telegram crew). This enables `parrot/core/hooks/` to attach listeners for logging, analytics, or inter-platform bridging.

---

## 5. Configuration & Dependencies

### New Dependencies
- `mautrix>=0.20.0` (already used by existing Matrix integration)
- No new external dependencies required.

### Environment Variables
| Variable | Description |
|----------|-------------|
| `MATRIX_HOMESERVER_URL` | Homeserver URL (e.g., `https://matrix.example.com`) |
| `MATRIX_SERVER_NAME` | Server name (e.g., `example.com`) |
| `MATRIX_AS_TOKEN` | Application Service token |
| `MATRIX_HS_TOKEN` | Homeserver token |

### Files Created/Modified

**New files** (`parrot/integrations/matrix/crew/`):
| File | Purpose | Effort |
|------|---------|--------|
| `__init__.py` | Module exports | S |
| `config.py` | `MatrixCrewConfig`, `MatrixCrewAgentEntry` | S |
| `registry.py` | `MatrixCrewRegistry`, `MatrixAgentCard` | M |
| `coordinator.py` | `MatrixCoordinator` (pinned status board) | M |
| `crew_wrapper.py` | `MatrixCrewAgentWrapper` (per-agent handler) | L |
| `mention.py` | Mention parsing/formatting utilities | S |
| `transport.py` | `MatrixCrewTransport` (top-level orchestrator) | L |

**New files** (example + documentation):
| File | Purpose | Effort |
|------|---------|--------|
| `examples/matrix_crew/matrix_crew_example.py` | Comprehensive example script | M |
| `examples/matrix_crew/matrix_crew.yaml` | Example YAML config | S |
| `examples/matrix_crew/MATRIX_CREW_GUIDE.md` | Extensive documentation | L |

**Modified files**:
| File | Change | Effort |
|------|--------|--------|
| `parrot/integrations/matrix/__init__.py` | Add crew exports | S |
| `parrot/integrations/manager.py` | Add `matrix_crew` startup support | S |

---

## 6. Acceptance Criteria

1. **Multi-agent shared room**: N agents respond in a single general room, routed by `@mention`.
2. **Per-agent rooms**: Each agent has an optional dedicated room where all messages route to it (no mention needed).
3. **Status board**: A pinned message in the general room shows all agents with live status (ready/busy/offline).
4. **Virtual MXIDs**: Each agent uses its own Matrix identity via the Application Service protocol.
5. **Typing indicators**: Agents show typing while processing.
6. **Streaming responses**: Agents can stream responses via edit-based token streaming (using existing `MatrixStreamHandler`).
7. **YAML configuration**: Crew is fully configurable via YAML (parallel to Telegram crew config).
8. **Graceful lifecycle**: `start()` initializes all agents; `stop()` shuts down cleanly.
9. **Example script**: A comprehensive, runnable example with:
   - 3+ agents (e.g., analyst, researcher, general assistant)
   - Each agent in its own dedicated room
   - All agents in a shared general room
   - Coordinator bot managing the status board
10. **Documentation**: A separate `.md` guide covering setup, configuration, architecture, and usage.
11. **Tests**: Unit tests for registry, mention parsing, config loading; integration test for message routing.

---

## 7. Testing Strategy

### Unit Tests
| Test | Validates |
|------|-----------|
| `test_matrix_crew_config` | YAML loading, env var substitution, model validation |
| `test_matrix_crew_registry` | Register, unregister, status updates, concurrent access |
| `test_mention_parsing` | Plain text mentions, pill mentions, edge cases |
| `test_agent_card_rendering` | Status line formatting for the pinned board |
| `test_message_chunking` | Long messages split correctly |

### Integration Tests
| Test | Validates |
|------|-----------|
| `test_message_routing_shared_room` | @mention routes to correct agent |
| `test_message_routing_dedicated_room` | Room-based routing works |
| `test_unaddressed_default_agent` | Unmentioned messages go to default agent |
| `test_coordinator_status_updates` | Status board reflects agent state changes |
| `test_transport_lifecycle` | Start/stop initializes and cleans up all components |

### Test Fixtures
- Mock `MatrixAppService` (no real homeserver needed).
- Mock `BotManager.get_bot()` returning stub agents.
- In-memory registry for isolated tests.

---

## 8. Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Reason**: Tasks modify the same package (`parrot/integrations/matrix/crew/`) and share models/registry.
- **Cross-feature dependencies**: None — builds on existing `parrot/integrations/matrix/` which is stable.

---

## 9. Example Script Overview

The example in `examples/matrix_crew/matrix_crew_example.py` demonstrates:

```python
"""
Matrix Multi-Agent Crew Example
================================
Launches a crew of 3 agents on a Matrix homeserver:

1. Financial Analyst  — @analyst  — dedicated room + general room
2. Research Assistant  — @researcher — dedicated room + general room
3. General Assistant   — @assistant — general room only

Each agent uses its own virtual MXID via the Application Service protocol.
The coordinator bot maintains a pinned status board in the general room.

Usage:
    python matrix_crew_example.py --config matrix_crew.yaml
"""
```

The companion `MATRIX_CREW_GUIDE.md` covers:
1. **Prerequisites** — Synapse/Dendrite setup, AS registration
2. **Configuration** — YAML reference, environment variables
3. **Architecture** — Room topology, message flow diagrams
4. **Agent Setup** — Defining agents in BotManager, skill configuration
5. **Running the Crew** — Launch, monitoring, troubleshooting
6. **Extending** — Adding new agents, custom routing, inter-agent tasks
7. **Production Deployment** — Reverse proxy, TLS, monitoring, scaling

---

## 10. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Homeserver rate limits on edits (streaming) | Degraded UX | Rate-limit edits in `MatrixStreamHandler` (already implemented) |
| AS token compromise | Security | Store tokens in env vars, never in config files |
| Agent name collisions with real Matrix users | Routing errors | Namespace agent MXIDs under AS-reserved namespace (e.g., `@_parrot_analyst:server`) |
| Large crews (10+ agents) overwhelm status board | UX clutter | Paginate or collapse idle agents |
| Homeserver unavailable during startup | Crew fails to start | Retry with exponential backoff on AS registration |
