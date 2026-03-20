# Feature Specification: TelegramCrewTransport

**Feature ID**: FEAT-010
**Date**: 2026-02-22
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot's current Telegram integration wrapper follows a **1 bot = 1 agent = 1 chat** model. When multiple agents need to collaborate on a task (e.g., data extraction + report generation + orchestration), there is no mechanism for them to operate as a visible crew in a shared Telegram supergroup. The human operator (HITL) cannot observe inter-agent communication, inject corrections mid-flow, or see the crew's collective state in one place.

### Goals

- **Multi-agent crew in a single Telegram supergroup**: N bots representing N agents, all visible to the human operator.
- **Pinned registry for presence**: A coordinator bot maintains a pinned message showing which agents are online, busy, or offline.
- **Mention-as-addressing**: All communication uses `@mention` for explicit routing between agents and humans.
- **Silent multi-turn processing**: Internal tool calls are never published to the group; only final results appear.
- **File exchange via documents**: Agents share structured data (CSV, JSON, Parquet, images) as Telegram document attachments, not inline text.
- **HITL visibility**: The human can observe all inter-agent exchanges, intervene via @mention, and receive results with @mention replies.
- **Custom coordinator commands** (`/list`, `/card`, `/status`): Deferred to a follow-up iteration.

### Non-Goals (explicitly out of scope)

- **Direct Messages between bots**: All communication flows through the group channel; no DM-based inter-bot protocol.
- **Persistent registry across restarts**: The in-memory `CrewRegistry` does not persist to Redis/DB in this iteration.
- **Approval workflows with inline keyboards**: The existing `TelegramHumanChannel` handles HITL approvals; this spec does not duplicate that.
- **Matrix/Slack/Teams transport**: This spec covers Telegram only. The architecture is designed for future portability but does not implement other transports.

---

## 2. Architectural Design

### Overview

The `TelegramCrewTransport` is a new orchestrator that manages a fleet of Telegram bots in a single supergroup. It introduces a **CoordinatorBot** (a non-agent bot that manages the pinned registry), **CrewAgentWrapper** (per-agent message handling with crew semantics), and supporting components for presence (`CrewRegistry`), self-description (`AgentCard`), and file exchange (`DataPayload`).

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Supergrupo Telegram (Crew Channel)               │
│                                                                     │
│  @coordinator_bot  ← CoordinatorBot (pinned registry)              │
│  @orchestrator_bot ← OrchestratorAgent                             │
│  @data_bot         ← DataAgent                                      │
│  @report_bot       ← ReportAgent                                    │
│  @jesus            ← HITL (human)                                   │
│                                                                     │
│  Pinned Message (managed by @coordinator_bot):                      │
│    ✅ @orchestrator_bot  OrchestratorAgent                          │
│    ⏳ @data_bot          DataAgent · processing Q2...               │
│    ✅ @report_bot        ReportAgent                                │
└─────────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
  TelegramBotManager   TelegramBotManager   TelegramBotManager
         │
         ▼
  TelegramCrewTransport
  (orchestrates all wrappers)
         │
    ┌────┴─────┐
    │          │
    ▼          ▼
CrewRegistry  CoordinatorBot
(in-memory)   (pinned msg editor)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `TelegramBotManager` | uses | Retrieves agent instances via `get_bot(chatbot_id)` |
| `BotMentionedFilter` | reuses | Used in `CrewAgentWrapper` handler registration |
| `extract_query_from_mention` | reuses | Extracts clean query from @mention messages |
| `TelegramHumanChannel` | compatible | Can coexist; crew HITL uses @mention, not inline keyboards |
| `AgentCrew` | parallel concept | `TelegramCrewTransport` provides the Telegram visibility layer; can wrap an `AgentCrew` flow |
| `OutputMode.TELEGRAM` | reuses | Passed to `agent.ask()` for Telegram-friendly formatting |
| `parse_response()` | reuses | Unified response parser for text, files, images |

### Data Models

```python
class AgentSkill(BaseModel):
    name: str
    description: str
    input_types: List[str] = []   # ["text", "csv", "json"]
    output_types: List[str] = []  # ["text", "csv", "chart"]
    example: Optional[str] = None

class AgentCard(BaseModel):
    agent_id: str
    agent_name: str
    telegram_username: str
    telegram_user_id: int
    model: str
    skills: List[AgentSkill] = []
    tags: List[str] = []
    accepts_files: List[str] = []
    emits_files: List[str] = []
    status: str = "ready"          # "ready" | "busy" | "offline"
    current_task: Optional[str] = None
    joined_at: datetime
    last_seen: datetime

class CrewAgentEntry(BaseModel):
    chatbot_id: str
    bot_token: str
    username: str
    skills: List[dict] = []
    tags: List[str] = []
    accepts_files: List[str] = []
    emits_files: List[str] = []
    system_prompt_override: Optional[str] = None

class TelegramCrewConfig(BaseModel):
    group_id: int
    coordinator_token: str
    coordinator_username: str
    hitl_user_ids: List[int] = []
    agents: Dict[str, CrewAgentEntry] = {}
    announce_on_join: bool = True
    update_pinned_registry: bool = True
    reply_to_sender: bool = True
    silent_tool_calls: bool = True
    typing_indicator: bool = True
    max_message_length: int = 4000
    temp_dir: str = "/tmp/parrot_crew"
    max_file_size_mb: int = 50
    allowed_mime_types: List[str] = [...]
```

### New Public Interfaces

```python
class TelegramCrewTransport:
    """Orchestrator for multi-agent crew in a Telegram supergroup."""
    async def start() -> None: ...
    async def stop() -> None: ...
    async def send_message(from_username, mention, text, reply_to_message_id=None) -> None: ...
    async def send_document(from_username, mention, file_path, caption="", reply_to_message_id=None) -> None: ...
    def list_online_agents() -> List[dict]: ...

class CoordinatorBot:
    """Non-agent bot managing the pinned registry message."""
    async def start() -> None: ...
    async def stop() -> None: ...
    async def on_agent_join(card: AgentCard) -> None: ...
    async def on_agent_leave(username: str) -> None: ...
    async def on_agent_status_change(username, status, task=None) -> None: ...
    async def update_registry() -> None: ...

class CrewRegistry:
    """Thread-safe in-memory registry of active agents."""
    def register(card: AgentCard) -> None: ...
    def unregister(username: str) -> Optional[AgentCard]: ...
    def update_status(username, status, current_task=None) -> None: ...
    def get(username: str) -> Optional[AgentCard]: ...
    def list_active() -> List[AgentCard]: ...
    def resolve(name_or_username: str) -> Optional[AgentCard]: ...
```

---

## 3. Module Breakdown

### Module 1: Configuration & Data Models
- **Path**: `parrot/integrations/telegram/crew/config.py`
- **Responsibility**: `TelegramCrewConfig`, `CrewAgentEntry` Pydantic models. YAML loading via `from_yaml()`.
- **Depends on**: None (standalone Pydantic models)

### Module 2: AgentCard
- **Path**: `parrot/integrations/telegram/crew/agent_card.py`
- **Responsibility**: `AgentCard`, `AgentSkill` Pydantic models. Rendering methods: `to_telegram_text()` (announcement), `to_registry_line()` (pinned message line).
- **Depends on**: None (standalone Pydantic models)

### Module 3: CrewRegistry
- **Path**: `parrot/integrations/telegram/crew/registry.py`
- **Responsibility**: Thread-safe in-memory registry. CRUD operations on `AgentCard` entries. Resolution by username or agent name.
- **Depends on**: Module 2 (AgentCard)

### Module 4: DataPayload
- **Path**: `parrot/integrations/telegram/crew/payload.py`
- **Responsibility**: Download documents from Telegram messages, upload files to group, MIME type validation, CSV convenience method, temp file management.
- **Depends on**: None (uses aiogram Bot directly)

### Module 5: MentionBuilder
- **Path**: `parrot/integrations/telegram/crew/mention.py`
- **Responsibility**: Helper utilities for constructing `@mention` strings from usernames, user IDs, and `AgentCard` instances.
- **Depends on**: Module 2 (AgentCard)

### Module 6: CoordinatorBot
- **Path**: `parrot/integrations/telegram/crew/coordinator.py`
- **Responsibility**: Manages the pinned registry message. Sends initial pinned message on startup, edits it on agent join/leave/status change. Uses asyncio Lock for edit serialization.
- **Depends on**: Module 2 (AgentCard), Module 3 (CrewRegistry)

### Module 7: CrewAgentWrapper
- **Path**: `parrot/integrations/telegram/crew/crew_wrapper.py`
- **Responsibility**: Per-agent message handler for crew context. Handles @mention routing, silent tool call execution, @mention-tagged responses, document send/receive, typing indicator, status updates to coordinator.
- **Depends on**: Module 2 (AgentCard), Module 4 (DataPayload), Module 5 (MentionBuilder), Module 6 (CoordinatorBot). Reuses existing `BotMentionedFilter` and `extract_query_from_mention`.

### Module 8: TelegramCrewTransport
- **Path**: `parrot/integrations/telegram/crew/transport.py`
- **Responsibility**: Top-level orchestrator. Lifecycle management (start/stop all bots), public API for sending messages/documents, manages CoordinatorBot and all CrewAgentWrappers. Async context manager support.
- **Depends on**: Module 1 (Config), Module 3 (CrewRegistry), Module 6 (CoordinatorBot), Module 7 (CrewAgentWrapper)

### Module 9: Package Init & Integration
- **Path**: `parrot/integrations/telegram/crew/__init__.py` + update to `parrot/integrations/telegram/__init__.py`
- **Responsibility**: Public exports. Integration hook in application startup (register `TelegramCrewTransport` alongside existing `TelegramBotManager`).
- **Depends on**: Module 8 (TelegramCrewTransport)

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_crew_config_from_dict` | Module 1 | Validates TelegramCrewConfig construction from dict |
| `test_crew_config_from_yaml` | Module 1 | Validates YAML loading with env var substitution |
| `test_agent_card_creation` | Module 2 | AgentCard instantiation with all fields |
| `test_agent_card_to_telegram_text` | Module 2 | Renders announcement message correctly |
| `test_agent_card_to_registry_line` | Module 2 | Renders compact registry line for each status |
| `test_registry_register_unregister` | Module 3 | Register and remove agents |
| `test_registry_update_status` | Module 3 | Status transitions (ready/busy/offline) |
| `test_registry_resolve_by_username` | Module 3 | Resolve by @username |
| `test_registry_resolve_by_name` | Module 3 | Resolve by agent_name (case-insensitive) |
| `test_registry_list_active` | Module 3 | Excludes offline agents |
| `test_registry_thread_safety` | Module 3 | Concurrent register/unregister from threads |
| `test_payload_mime_validation` | Module 4 | Rejects disallowed MIME types |
| `test_payload_download_document` | Module 4 | Downloads file to temp dir (mocked) |
| `test_payload_send_document` | Module 4 | Sends file with caption (mocked) |
| `test_payload_send_csv` | Module 4 | Serializes DataFrame to CSV and sends |
| `test_mention_builder` | Module 5 | Builds @mention from username, user_id, AgentCard |
| `test_coordinator_render_registry` | Module 6 | Renders pinned message text correctly |
| `test_coordinator_agent_join_updates_pinned` | Module 6 | Joining triggers pinned edit (mocked) |
| `test_coordinator_status_change` | Module 6 | Status change edits pinned (mocked) |
| `test_crew_wrapper_sender_mention` | Module 7 | Extracts @mention from message.from_user |
| `test_crew_wrapper_parse_response_text` | Module 7 | Parses string response |
| `test_crew_wrapper_parse_response_with_files` | Module 7 | Parses response with files attribute |
| `test_transport_start_stop` | Module 8 | Start initializes coordinator + wrappers, stop cleans up |
| `test_transport_send_message` | Module 8 | Delegates to correct wrapper |
| `test_transport_list_online` | Module 8 | Returns registry contents |

### Integration Tests

| Test | Description |
|---|---|
| `test_crew_startup_flow` | Full startup: coordinator sends pinned, agents register, pinned updated |
| `test_mention_to_agent_response` | Simulate @mention message, verify agent.ask() called and response sent with @mention |
| `test_agent_to_agent_delegation` | Agent A sends @mention to Agent B, B processes and replies to A |
| `test_document_exchange` | Agent sends CSV document, recipient downloads and processes |
| `test_status_lifecycle` | Agent goes ready→busy→ready, pinned message reflects each state |
| `test_graceful_shutdown` | All agents unregistered, pinned updated, bot sessions closed |

### Test Data / Fixtures

```python
@pytest.fixture
def crew_config():
    return TelegramCrewConfig(
        group_id=-1001234567890,
        coordinator_token="fake:coordinator_token",
        coordinator_username="test_coordinator_bot",
        hitl_user_ids=[123456789],
        agents={
            "TestAgent": CrewAgentEntry(
                chatbot_id="test_agent",
                bot_token="fake:agent_token",
                username="test_agent_bot",
                tags=["test"],
                skills=[{"name": "echo", "description": "Echoes input"}],
            )
        },
    )

@pytest.fixture
def sample_agent_card():
    return AgentCard(
        agent_id="test_agent",
        agent_name="TestAgent",
        telegram_username="test_agent_bot",
        telegram_user_id=999999,
        model="test:model",
        skills=[AgentSkill(name="echo", description="Echoes input")],
        tags=["test"],
        joined_at=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )

@pytest.fixture
def mock_bot():
    """Mock aiogram Bot with send_message, send_document, get_me, etc."""
    ...

@pytest.fixture
def mock_agent():
    """Mock AI-Parrot agent with ask() method."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] All unit tests pass (`pytest tests/test_telegram_crew/ -v`)
- [ ] Integration tests pass with mocked Telegram API (`pytest tests/test_telegram_crew/ -v -m integration`)
- [ ] `TelegramCrewTransport` can be instantiated from YAML config
- [ ] CoordinatorBot sends and pins a registry message on startup (verified via mocked Bot)
- [ ] CrewAgentWrapper responds only to @mentions in the configured group
- [ ] Responses always include @mention of the sender
- [ ] Tool calls during `agent.ask()` are not published to the group
- [ ] Documents can be sent and received between agents via DataPayload
- [ ] Pinned registry message updates on agent join, leave, and status change
- [ ] Typing indicator shows while agent is processing
- [ ] Long messages are chunked correctly (under 4096 chars)
- [ ] No breaking changes to existing `TelegramBotManager` or `TelegramAgentWrapper`
- [ ] All new Pydantic models validate correctly
- [ ] Package exports are clean (`from parrot.integrations.telegram.crew import TelegramCrewTransport`)

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- **Composition over inheritance**: `CrewAgentWrapper` composes (not extends) `TelegramAgentWrapper`. Both can coexist for the same agent.
- **Async-first**: All handlers and lifecycle methods are async. Use `asyncio.Lock` (not `threading.Lock`) for async-safe serialization in CoordinatorBot.
- **Pydantic models**: All config and data structures use Pydantic v2 `BaseModel`.
- **Logging**: Use `logging.getLogger(__name__)` in each module. No print statements.
- **Rate limiting**: 0.3-0.5s sleep between consecutive Telegram API calls to the same chat.
- **aiogram v3**: Use Router-based handler registration, `FSInputFile` for uploads, `Dispatcher` for polling.

### Known Risks / Gotchas

- **Bot-to-bot message filtering**: Telegram may filter messages from bots to other bots in groups. Mitigation: all bots read from the group timeline; the group acts as shared bus. The `allowed_updates=["message"]` setting should receive bot messages, but testing is required.
- **Rate limits**: Telegram allows ~30 msg/s per bot, 1 msg/s per chat. Silent tool calls drastically reduce message volume. For high-activity crews, a message queue with debouncing may be needed (deferred to future iteration).
- **Pinned message edit race**: Multiple status changes can trigger concurrent edits. The `asyncio.Lock` in `CoordinatorBot.update_registry()` serializes edits. Telegram's "message not modified" error is silently ignored.
- **Caption length limit**: Telegram captions are limited to 1024 chars. Text exceeding this is split into a separate message.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiogram` | `>=3.0` | Telegram Bot API framework (already in project) |
| `pydantic` | `>=2.0` | Data model validation (already in project) |
| `aiofiles` | `>=23.0` | Async file operations for DataPayload (already in project) |
| `pyyaml` | `>=6.0` | YAML config loading (already in project) |
| `pandas` | `>=2.0` | CSV serialization in DataPayload.send_csv() (already in project) |

No new external dependencies required.

---

## 7. Open Questions

- [ ] **Bot-to-bot visibility**: Does aiogram v3 polling reliably receive messages sent by other bots in a supergroup? Requires empirical testing with real Telegram group. — *Owner: Jesus*: allows but require testing.
- [ ] **Coordinator as proxy**: If bot-to-bot filtering is an issue, should the CoordinatorBot relay messages between agents? This would change the architecture from direct @mention to coordinator-mediated routing. — *Owner: Jesus*: not needed for now.
- [ ] **Concurrent crew instances**: Should TelegramCrewTransport support multiple supergroups (multiple crews) in a single process? Current design assumes one crew per transport instance. — *Owner: Jesus*: no required.
- [ ] **AgentCrew integration**: Should TelegramCrewTransport wrap an `AgentCrew` DAG execution and publish results to Telegram, or should it be a standalone transport independent of `AgentCrew`? — *Owner: Jesus*: not on this scope, Agent

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-22 | Jesus Lara | Initial draft from proposal document |
