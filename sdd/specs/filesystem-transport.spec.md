# Feature Specification: FilesystemTransport

**Feature ID**: FEAT-011
**Date**: 2026-02-22
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot supports multiple communication channels (WebSockets, WhatsApp/Redis, A2A HTTP, MCP), but all require external infrastructure (Redis, HTTP server, Matrix homeserver). For development, CI/CD, and air-gapped environments, there is no zero-dependency option for multi-agent coordination on a single host.

The filesystem is the most reliable bus available for local multi-agent communication: zero deps, zero network latency, trivially debuggable with `cat`/`tail -f`, and fully reproducible.

Inspired by [pi-messenger](https://github.com/nicobailon/pi-messenger), the FilesystemTransport provides multi-agent coordination over the local filesystem with extensions for broadcast channels, resource reservations, and a CLI overlay for human-in-the-loop (HITL) participation.

### Goals

- **Zero-dependency local transport**: Multi-agent messaging on a single host using only the filesystem — no Redis, no HTTP server, no daemons.
- **Agent presence & discovery**: Agents register/deregister via JSON files; PID-based liveness detection eliminates stale entries instantly.
- **Point-to-point messaging**: Atomic write-then-rename inbox delivery with exactly-once semantics.
- **Broadcast channels**: JSONL-based append-only channels with offset-based polling (equivalent to rooms/topics).
- **Resource reservations**: Cooperative declarative locks so agents signal which files/resources they are working on.
- **Activity feed**: Global append-only JSONL log of all system events for observability.
- **CLI overlay (HITL)**: Terminal UI to observe agent state, activity feed, and send messages to agents — no daemon required.
- **Hook integration**: `FilesystemHook` following the `BaseHook` pattern so any `BasicAgent` receives filesystem messages without modification.
- **Sub-50ms latency**: Via optional `watchdog`/inotify integration, with automatic fallback to polling.

### Non-Goals (explicitly out of scope)

- **Multi-host deployment**: This transport is single-host only (unless NFS/SMB is used as shared filesystem).
- **Production use in cloud**: Not recommended for production cloud deployments — use Redis, Matrix, or A2A.
- **Windows support**: The project uses `uvloop`; Windows compatibility is not a target.
- **AbstractTransport interface**: Extracting a common interface across transports is deferred until a second transport (TelegramCrewTransport) is mature.
- **Encryption or authentication**: Messages are plaintext JSON on the local filesystem; security is delegated to OS-level permissions.

---

## 2. Architectural Design

### Overview

The FilesystemTransport uses a directory tree (default `.parrot/`) as a message bus. Each agent registers its presence via a JSON file, sends messages by writing to other agents' inbox directories, and broadcasts via append-only JSONL channel files. A global activity feed logs all events. Resource reservations are cooperative JSON declarations.

### Component Diagram

```
.parrot/
├── registry/           ← AgentRegistry (presence + PID-based liveness)
│   └── <agent-id>.json
├── inbox/              ← InboxManager (point-to-point, write-then-rename)
│   └── <agent-id>/
│       ├── msg-<uuid>.json
│       └── .processed/
├── feed.jsonl          ← ActivityFeed (global append-only log)
├── channels/           ← ChannelManager (broadcast, JSONL per channel)
│   ├── general.jsonl
│   └── <channel>.jsonl
├── reservations/       ← ReservationManager (cooperative file locks)
│   └── <hash>.json
└── .lock/              ← fcntl locks for atomic operations
    └── feed.lock

FilesystemTransport
├── AgentRegistry      (join, leave, heartbeat, gc_stale, resolve)
├── InboxManager       (deliver, poll — with inotify or polling fallback)
├── ActivityFeed       (emit, tail, rotate)
├── ChannelManager     (publish, poll with offset)
└── ReservationManager (acquire, release — all-or-nothing, TTL-based)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BaseHook` | extends | `FilesystemHook` inherits `BaseHook`, follows `WhatsAppRedisHook` pattern |
| `HookType` | extends | Add `FILESYSTEM = "filesystem"` to the enum |
| `HookEvent` | uses | Events emitted to orchestrator via `on_event()` |
| `HookManager` | registers | `FilesystemHook` registered like any other hook |
| `BasicAgent` | compatible | Agents receive messages via hook without modification |
| `BotManager` | uses | Hook resolves target agent from `BotManager` |

### Data Models

```python
# FilesystemTransportConfig (Pydantic)
class FilesystemTransportConfig(BaseModel):
    root_dir: Path = Path(".parrot")
    presence_interval: float = 10.0      # Heartbeat interval (seconds)
    stale_threshold: float = 60.0        # Seconds before agent is considered dead
    scope_to_cwd: bool = False           # Only see agents with same cwd
    poll_interval: float = 0.5           # Polling fallback interval
    use_inotify: bool = True             # Use watchdog/inotify if available
    message_ttl: float = 3600.0          # Message TTL (0 = no expiration)
    keep_processed: bool = True          # Move processed msgs to .processed/
    feed_retention: int = 500            # Max events before rotation
    default_channels: List[str] = ["general"]
    reservation_timeout: float = 300.0   # Reservation expiry (seconds)
    routes: Optional[List[Dict[str, Any]]] = None  # Routing rules

# FilesystemHookConfig (extends BaseHook pattern)
class FilesystemHookConfig(BaseModel):
    name: str = "filesystem_hook"
    enabled: bool = True
    target_type: Optional[str] = "agent"
    target_id: Optional[str] = None
    transport: FilesystemTransportConfig = FilesystemTransportConfig()
    command_prefix: str = ""
    allowed_agents: Optional[List[str]] = None
    metadata: Dict[str, Any] = {}
```

### New Public Interfaces

```python
class FilesystemTransport:
    """Multi-agent transport over local filesystem."""
    async def start() -> None: ...
    async def stop() -> None: ...
    async def send(to, content, msg_type="message", payload=None, reply_to=None) -> str: ...
    async def broadcast(content, channel="general", payload=None) -> None: ...
    async def messages() -> AsyncGenerator[Dict, None]: ...
    async def channel_messages(channel="general", since_offset=0) -> AsyncGenerator[Dict, None]: ...
    async def list_agents() -> List[Dict]: ...
    async def whois(name_or_id) -> Optional[Dict]: ...
    async def reserve(paths, reason="") -> bool: ...
    async def release(paths=None) -> None: ...
    async def set_status(status, message="") -> None: ...

class FilesystemHook(BaseHook):
    """Hook connecting agents to FilesystemTransport."""
    async def start() -> None: ...
    async def stop() -> None: ...
```

---

## 3. Module Breakdown

### Module 1: Configuration
- **Path**: `parrot/transport/filesystem/config.py`
- **Responsibility**: `FilesystemTransportConfig` Pydantic model with all transport settings. Path resolution validator.
- **Depends on**: None (standalone Pydantic model)

### Module 2: AgentRegistry
- **Path**: `parrot/transport/filesystem/registry.py`
- **Responsibility**: Agent presence management. Join/leave via write-then-rename. PID-based liveness detection via `os.kill(pid, 0)`. Heartbeat updates. GC of stale agents. Resolution by agent_id or name (case-insensitive).
- **Depends on**: Module 1 (config)

### Module 3: InboxManager
- **Path**: `parrot/transport/filesystem/inbox.py`
- **Responsibility**: Point-to-point message delivery. Atomic write-then-rename. Polling with inotify/watchdog fallback. Exactly-once delivery (move to `.processed/` before yield). TTL-based message expiration.
- **Depends on**: Module 1 (config)

### Module 4: ActivityFeed
- **Path**: `parrot/transport/filesystem/feed.py`
- **Responsibility**: Global append-only JSONL event log. Async-safe writes via `asyncio.Lock`. Auto-rotation when exceeding `feed_retention` lines. Tail reading.
- **Depends on**: Module 1 (config)

### Module 5: ChannelManager
- **Path**: `parrot/transport/filesystem/channel.py`
- **Responsibility**: Broadcast channels as JSONL files. Publish (append) and poll (read from offset). Channel listing. No subscription state — offset is caller-managed.
- **Depends on**: Module 1 (config)

### Module 6: ReservationManager
- **Path**: `parrot/transport/filesystem/reservation.py`
- **Responsibility**: Cooperative resource reservation via JSON files (hashed filenames). All-or-nothing acquisition. TTL-based expiration. Release by path or release-all.
- **Depends on**: Module 1 (config)

### Module 7: FilesystemTransport
- **Path**: `parrot/transport/filesystem/transport.py`
- **Responsibility**: Top-level orchestrator composing all managers. Lifecycle (start/stop), presence heartbeat loop, public API (send, broadcast, messages, list_agents, reserve, release, set_status). Async context manager support.
- **Depends on**: Module 1 (config), Module 2 (registry), Module 3 (inbox), Module 4 (feed), Module 5 (channel), Module 6 (reservation)

### Module 8: FilesystemHook
- **Path**: `parrot/transport/filesystem/hook.py`
- **Responsibility**: Integration with AI-Parrot's `BaseHook` system. Listens to inbox, filters by prefix/allowed_agents, dispatches to target agent via orchestrator, sends response back. Follows `WhatsAppRedisHook` pattern exactly.
- **Depends on**: Module 7 (transport), `BaseHook` from `parrot/autonomous/hooks/base.py`

### Module 9: CLI Overlay
- **Path**: `parrot/transport/filesystem/cli.py`
- **Responsibility**: Terminal CLI for HITL. Snapshot mode, watch mode (live updates), send message, view feed. Uses `click` for CLI, optional `rich` for formatting. Reads directly from filesystem — no running process required.
- **Depends on**: Module 2 (registry), Module 4 (feed), Module 7 (transport)

### Module 10: Package Init
- **Path**: `parrot/transport/filesystem/__init__.py`
- **Responsibility**: Public exports: `FilesystemTransport`, `FilesystemTransportConfig`, `FilesystemHook`, `FilesystemHookConfig`.
- **Depends on**: All modules

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_config_defaults` | Module 1 | Default config values are correct |
| `test_config_path_resolution` | Module 1 | `root_dir` is resolved to absolute path |
| `test_registry_join_leave` | Module 2 | Agent registers and deregisters cleanly |
| `test_registry_pid_detection` | Module 2 | Dead PID detected via `os.kill(pid, 0)` |
| `test_registry_gc_stale` | Module 2 | GC removes entries with dead PIDs |
| `test_registry_resolve_by_id` | Module 2 | Resolve agent by agent_id |
| `test_registry_resolve_by_name` | Module 2 | Resolve agent by name (case-insensitive) |
| `test_registry_list_active` | Module 2 | Only live agents returned |
| `test_registry_scope_to_cwd` | Module 2 | Scope filtering by working directory |
| `test_inbox_delivery_atomic` | Module 3 | Large message reads complete (no partial reads) |
| `test_inbox_exactly_once` | Module 3 | Message not processed twice after move to `.processed/` |
| `test_inbox_ttl_expiration` | Module 3 | Expired messages are silently filtered |
| `test_inbox_poll_order` | Module 3 | Messages polled in chronological order (mtime) |
| `test_feed_emit_and_tail` | Module 4 | Events written and read correctly |
| `test_feed_rotation` | Module 4 | Feed rotates at `feed_retention` limit |
| `test_feed_empty_tail` | Module 4 | Tail on non-existent feed returns empty list |
| `test_channel_publish_poll` | Module 5 | Publish and poll messages with offset |
| `test_channel_list` | Module 5 | List available channels |
| `test_channel_poll_empty` | Module 5 | Poll non-existent channel returns nothing |
| `test_reservation_acquire_release` | Module 6 | Basic acquire and release cycle |
| `test_reservation_all_or_nothing` | Module 6 | Partial conflict fails entire acquisition |
| `test_reservation_ttl_expiry` | Module 6 | Expired reservation allows re-acquisition |
| `test_reservation_release_all` | Module 6 | Release all reservations for an agent |
| `test_transport_start_stop` | Module 7 | Start registers presence, stop deregisters |
| `test_transport_send_receive` | Module 7 | AgentA sends to AgentB, AgentB receives |
| `test_transport_broadcast` | Module 7 | Broadcast to channel, poll from channel |
| `test_transport_discovery` | Module 7 | `list_agents()` returns both agents |
| `test_transport_set_status` | Module 7 | Status update visible in registry |
| `test_hook_config_validation` | Module 8 | FilesystemHookConfig validates correctly |

### Integration Tests

| Test | Description |
|---|---|
| `test_two_agent_conversation` | Two transports exchange messages bidirectionally |
| `test_three_agent_broadcast` | Three agents publish and read from a shared channel |
| `test_reservation_conflict` | Two agents compete for overlapping resources |
| `test_presence_lifecycle` | Agent joins, heartbeats, stops — registry reflects each state |
| `test_feed_captures_all_events` | Join, message, broadcast, reserve, release all appear in feed |
| `test_hook_dispatches_to_agent` | FilesystemHook receives message and dispatches to mock agent |

### Test Data / Fixtures

```python
@pytest.fixture
def fs_config(tmp_path: Path) -> FilesystemTransportConfig:
    return FilesystemTransportConfig(
        root_dir=tmp_path,
        presence_interval=0.1,
        poll_interval=0.05,
        use_inotify=False,       # Polling in tests (deterministic)
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

---

## 5. Acceptance Criteria

- [ ] All unit tests pass (`pytest tests/transport/filesystem/ -v`)
- [ ] All integration tests pass (`pytest tests/transport/filesystem/ -v -m integration`)
- [ ] Two Python processes on the same host can exchange messages via `.parrot/` directory
- [ ] `FilesystemTransport` supports async context manager (`async with`)
- [ ] Write-then-rename ensures no partial reads (atomic POSIX rename)
- [ ] PID-based presence detection: dead agents cleaned up without timeout wait
- [ ] Messages expire correctly based on `message_ttl`
- [ ] Processed messages move to `.processed/` (exactly-once delivery)
- [ ] Feed rotates when exceeding `feed_retention` lines
- [ ] Channel broadcast works with offset-based polling
- [ ] Reservation acquire is all-or-nothing; TTL-based expiry works
- [ ] `FilesystemHook` follows `BaseHook` pattern and dispatches to agents
- [ ] CLI overlay shows agent state, feed, and can send messages
- [ ] Optional `watchdog` integration provides sub-50ms latency (fallback to polling)
- [ ] No breaking changes to existing hooks, transports, or agents
- [ ] No new required dependencies beyond `aiofiles` (watchdog, rich, click are optional)
- [ ] Package exports are clean (`from parrot.transport.filesystem import FilesystemTransport`)

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- **Composition**: `FilesystemTransport` composes Registry, Inbox, Feed, Channel, Reservation managers — no deep inheritance.
- **Async-first**: All I/O operations use `aiofiles`. All locks use `asyncio.Lock`.
- **Write-then-rename**: All file writes use tmp + rename for POSIX atomicity.
- **Pydantic models**: All config and structured data use Pydantic v2 `BaseModel`.
- **Logging**: Use `logging.getLogger(__name__)` — no print statements.
- **BaseHook pattern**: `FilesystemHook` follows `WhatsAppRedisHook` exactly: init from config, start/stop lifecycle, listen loop, dispatch to orchestrator via `on_event()`.
- **Graceful degradation**: inotify/watchdog is optional; silently falls back to polling.

### Known Risks / Gotchas

- **Race condition in reservations**: The check-then-acquire pattern in `ReservationManager` has a TOCTOU window. Mitigated by: (1) cooperative agents, (2) reservation is advisory not mandatory. For hard exclusion, use `fcntl.flock()` directly.
- **NFS/SMB filesystems**: `rename()` atomicity is not guaranteed on all network filesystems. Document that local filesystem is required for full guarantees.
- **inotify limits**: Linux has a default inotify watch limit (`/proc/sys/fs/inotify/max_user_watches`). Many agents with watchdog could hit it. Polling fallback handles this.
- **Feed rotation under concurrent writes**: Rotation reads all lines, keeps last N, writes back. Concurrent `emit()` calls are serialized via `asyncio.Lock`, but external writers could cause data loss. Acceptable for dev/CI use case.

### External Dependencies

| Package | Version | Reason | Required |
|---|---|---|---|
| `aiofiles` | `>=23.0` | Async file I/O in all components | Yes |
| `watchdog` | `>=4.0` | inotify/FSEvents for sub-50ms inbox notification | Optional |
| `rich` | `>=13.0` | CLI overlay visual formatting | Optional |
| `click` | `>=8.0` | CLI command parsing | Optional |

---

## 7. Open Questions

- [x] **Hook integration approach**: Should `FilesystemHook` extend `BaseHook` directly or use a different integration point? — *Resolved*: Extends `BaseHook` following `WhatsAppRedisHook` pattern.
- [x] **HookType enum**: Need to add `FILESYSTEM = "filesystem"` to `HookType` in `parrot/autonomous/hooks/models.py`. — *Resolved*: Yes, add it.
- [ ] **Config loading**: Should `FilesystemTransportConfig` support loading from `parrot.yaml` transport section directly? — *Owner: Jesus*: Yes
- [ ] **AbstractTransport**: Should we define a common interface now or defer? — *Owner: Jesus*: if create an `AbstractTransport` cannot be an issue with other existing Transports, let's create it.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-22 | Jesus Lara | Initial spec from proposal document |
