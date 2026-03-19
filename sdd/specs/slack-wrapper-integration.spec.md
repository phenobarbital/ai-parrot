# Feature Specification: Slack Wrapper Integration Enhancements

**Feature ID**: FEAT-010
**Date**: 2026-02-24
**Author**: AI-Parrot Team
**Status**: approved
**Target version**: 1.5.0

---

## 1. Motivation & Business Requirements

> Production-ready Slack integration with security, reliability, and feature parity with other wrappers.

### Problem Statement

The current `SlackAgentWrapper` exposes AI-Parrot agents via Slack Events API and slash commands but has critical gaps preventing production deployment:

1. **Security**: No request signature verification — any HTTP request is processed, allowing spoofing attacks.
2. **Reliability**: No event deduplication — Slack retries cause duplicate agent responses.
3. **Performance**: Synchronous processing exceeds Slack's 3-second response window, triggering retries.
4. **UX**: No typing indicators, file handling, or interactive Block Kit support.
5. **Feature gap**: No support for Slack's new Agents & AI Apps feature (Assistant Container).

Comparison with other AI-Parrot integrations:
- **MS Teams**: Has BotFramework signature validation, typing indicators, Adaptive Cards.
- **Telegram**: Has aiogram polling (no public URL needed), file handling, inline keyboards.
- **WhatsApp**: Has async processing with `asyncio.create_task`, media download.

### Goals
- Secure the Slack integration with HMAC-SHA256 signature verification
- Prevent duplicate message processing via event deduplication
- Return HTTP 200 within 3 seconds using async background processing
- Add Socket Mode for local development without public URLs
- Implement typing indicators for better UX
- Support file/image upload and download
- Enable Block Kit interactive components (buttons, menus, modals)
- Integrate with Slack Agents & AI Apps for native assistant experience

### Non-Goals (explicitly out of scope)
- Enterprise Grid multi-workspace support (future enhancement)
- Slack Connect (external organizations) support
- Custom emoji reactions as feedback mechanism
- Voice/Huddles integration

---

## 2. Architectural Design

### Overview

Enhance `SlackAgentWrapper` with modular components for security, reliability, and rich interactions. Support dual connection modes (webhook and Socket Mode) and optional Agents & AI Apps integration.

### Component Diagram
```
                            ┌─────────────────────────────────────┐
                            │        SlackAgentWrapper           │
                            │  (orchestrates all components)      │
                            └─────────────┬───────────────────────┘
                                          │
        ┌─────────────────────────────────┼─────────────────────────────────┐
        │                                 │                                 │
        ▼                                 ▼                                 ▼
┌───────────────────┐          ┌───────────────────┐          ┌───────────────────┐
│   security.py     │          │   dedup.py        │          │ socket_handler.py │
│  verify_signature │          │ EventDeduplicator │          │ SlackSocketHandler│
│  (HMAC-SHA256)    │          │ (in-memory/Redis) │          │ (WebSocket mode)  │
└───────────────────┘          └───────────────────┘          └───────────────────┘
        │                                 │                                 │
        └─────────────────────────────────┼─────────────────────────────────┘
                                          │
        ┌─────────────────────────────────┼─────────────────────────────────┐
        │                                 │                                 │
        ▼                                 ▼                                 ▼
┌───────────────────┐          ┌───────────────────┐          ┌───────────────────┐
│    files.py       │          │  interactive.py   │          │   assistant.py    │
│ download/upload   │          │  ActionRegistry   │          │ SlackAssistantHdlr│
│ Slack File API    │          │  Block Kit forms  │          │ Agents & AI Apps  │
└───────────────────┘          └───────────────────┘          └───────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `SlackAgentWrapper` | extends | Add new handlers and background processing |
| `SlackAgentConfig` | extends | Add `app_token`, `connection_mode`, `enable_assistant`, `suggested_prompts` |
| `InMemoryConversation` | uses | Continue using for session memory |
| `parse_response` | uses | Parse agent output to blocks |
| `OutputMode.SLACK` | uses | Agent output formatting |
| `parrot/loaders/` | uses | Process downloaded files (PDF, images, etc.) |
| `IntegrationBotManager` | extends | Support Socket Mode startup |

### Data Models

```python
# Updated SlackAgentConfig in parrot/integrations/slack/models.py
@dataclass
class SlackAgentConfig:
    name: str
    chatbot_id: str
    bot_token: Optional[str] = None
    signing_secret: Optional[str] = None
    kind: str = "slack"
    welcome_message: Optional[str] = None
    commands: Dict[str, str] = field(default_factory=dict)
    allowed_channel_ids: Optional[list[str]] = None
    webhook_path: Optional[str] = None

    # New fields
    app_token: Optional[str] = None           # For Socket Mode (xapp-...)
    connection_mode: str = "webhook"           # "webhook" | "socket"
    enable_assistant: bool = False             # Agents & AI Apps feature
    suggested_prompts: Optional[list[Dict[str, str]]] = None  # Assistant prompts
    max_concurrent_requests: int = 10          # Concurrency limit
```

### New Public Interfaces

```python
# parrot/integrations/slack/security.py
def verify_slack_signature_raw(
    raw_body: bytes,
    headers: Mapping[str, str],
    signing_secret: str,
    max_age_seconds: int = 300,
) -> bool:
    """Verify Slack request signature using HMAC-SHA256."""

# parrot/integrations/slack/dedup.py
class EventDeduplicator:
    """In-memory event deduplication with TTL."""
    def is_duplicate(self, event_id: str) -> bool: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...

class RedisEventDeduplicator:
    """Redis-backed deduplication for multi-instance deployments."""
    async def is_duplicate(self, event_id: str) -> bool: ...

# parrot/integrations/slack/files.py
async def download_slack_file(
    file_info: Dict[str, Any], bot_token: str, download_dir: Optional[str] = None
) -> Optional[Path]: ...

async def upload_file_to_slack(
    bot_token: str, channel: str, file_path: Path,
    title: Optional[str] = None, thread_ts: Optional[str] = None
) -> bool: ...

# parrot/integrations/slack/interactive.py
class ActionRegistry:
    """Registry for Block Kit action handlers."""
    def register(self, action_id: str, handler: Callable) -> None: ...
    def register_prefix(self, prefix: str, handler: Callable) -> None: ...

class SlackInteractiveHandler:
    """Handle Block Kit interactive payloads."""
    async def handle(self, request_or_payload) -> web.Response | None: ...

# parrot/integrations/slack/assistant.py
class SlackAssistantHandler:
    """Handle Slack Agents & AI Apps events."""
    async def handle_thread_started(self, event: dict, payload: dict) -> None: ...
    async def handle_context_changed(self, event: dict) -> None: ...
    async def handle_user_message(self, event: dict) -> None: ...

# parrot/integrations/slack/socket_handler.py
class SlackSocketHandler:
    """Socket Mode WebSocket handler."""
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
```

---

## 3. Module Breakdown

### Module 1: Security — Signature Verification
- **Path**: `parrot/integrations/slack/security.py`
- **Responsibility**: HMAC-SHA256 verification of Slack request signatures
- **Depends on**: None (standalone utility)
- **Priority**: Critical (Phase 1)

### Module 2: Event Deduplication
- **Path**: `parrot/integrations/slack/dedup.py`
- **Responsibility**: Track processed event IDs to prevent duplicates
- **Depends on**: None (standalone, optional Redis)
- **Priority**: Critical (Phase 1)

### Module 3: Async Background Processing
- **Path**: `parrot/integrations/slack/wrapper.py` (modification)
- **Responsibility**: Return HTTP 200 immediately, process in background
- **Depends on**: Module 1, Module 2
- **Priority**: Critical (Phase 1)

### Module 4: Typing Indicator
- **Path**: `parrot/integrations/slack/wrapper.py` (modification)
- **Responsibility**: Send ephemeral "thinking" messages or assistant status
- **Depends on**: Module 3
- **Priority**: Medium (Phase 2)

### Module 5: File Handling
- **Path**: `parrot/integrations/slack/files.py`
- **Responsibility**: Download/upload files using Slack File API v2
- **Depends on**: `parrot/loaders/` for file processing
- **Priority**: Medium (Phase 2)

### Module 6: Socket Mode Handler
- **Path**: `parrot/integrations/slack/socket_handler.py`
- **Responsibility**: WebSocket connection for local development
- **Depends on**: Module 1, Module 2, Module 3
- **Priority**: Medium (Phase 2-3)

### Module 7: Block Kit Interactive Handler
- **Path**: `parrot/integrations/slack/interactive.py`
- **Responsibility**: Handle buttons, selects, modals, shortcuts
- **Depends on**: Module 3
- **Priority**: Medium (Phase 3-4)

### Module 8: Agents & AI Apps (Assistant) Handler
- **Path**: `parrot/integrations/slack/assistant.py`
- **Responsibility**: Native assistant experience with split-view, streaming, suggested prompts
- **Depends on**: Module 3, Module 4, Module 7
- **Priority**: High (Phase 3-4)

### Module 9: Config Model Updates
- **Path**: `parrot/integrations/slack/models.py`
- **Responsibility**: Extend `SlackAgentConfig` with new fields
- **Depends on**: None
- **Priority**: Critical (Phase 1)

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_verify_signature_valid` | security | Valid signature passes verification |
| `test_verify_signature_invalid` | security | Invalid signature returns False |
| `test_verify_signature_expired` | security | Timestamp > 5 min is rejected |
| `test_verify_signature_missing_headers` | security | Missing headers return False |
| `test_dedup_first_event` | dedup | First event is not duplicate |
| `test_dedup_second_event` | dedup | Same event_id is duplicate |
| `test_dedup_cleanup_expired` | dedup | Expired events are cleaned up |
| `test_redis_dedup_set_nx` | dedup | Redis NX atomic set works |
| `test_download_file_success` | files | Downloads file with auth header |
| `test_download_file_unsupported_type` | files | Skips unsupported MIME types |
| `test_upload_file_v2_flow` | files | Uses 3-step async upload |
| `test_action_registry_exact` | interactive | Exact action_id match works |
| `test_action_registry_prefix` | interactive | Prefix matching works |
| `test_interactive_block_actions` | interactive | Routes block_actions payload |
| `test_interactive_view_submission` | interactive | Routes modal submission |
| `test_assistant_thread_started` | assistant | Welcome message + prompts sent |
| `test_assistant_user_message` | assistant | Sets status, processes, responds |
| `test_socket_mode_event_routing` | socket | Routes events to handlers |

### Integration Tests

| Test | Description |
|---|---|
| `test_webhook_signature_rejection` | Unsigned request returns 401 |
| `test_webhook_retry_ignored` | X-Slack-Retry-Num header causes immediate 200 |
| `test_full_event_flow` | Event → dedup → background task → response |
| `test_file_attachment_processing` | Event with file → download → loader → agent |
| `test_interactive_feedback_flow` | User clicks button → handler → ephemeral response |
| `test_assistant_full_conversation` | Thread start → message → streaming response |
| `test_socket_mode_connection` | WebSocket connects and routes events |

### Test Data / Fixtures

```python
@pytest.fixture
def slack_event_payload():
    return {
        "type": "event_callback",
        "event_id": "Ev123456",
        "event": {
            "type": "message",
            "channel": "C123456",
            "user": "U123456",
            "text": "Hello agent",
            "ts": "1234567890.123456",
        }
    }

@pytest.fixture
def slack_signature_headers(signing_secret: str):
    import time, hmac, hashlib
    timestamp = str(int(time.time()))
    body = b'{"test": "data"}'
    sig_basestring = f"v0:{timestamp}:{body.decode()}"
    signature = "v0=" + hmac.new(
        signing_secret.encode(), sig_basestring.encode(), hashlib.sha256
    ).hexdigest()
    return {"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature}

@pytest.fixture
def mock_slack_client():
    """Mock AsyncWebClient for testing."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All requests without valid HMAC-SHA256 signature return 401
- [ ] Duplicate events (same `event_id`) are not processed twice
- [ ] All event handlers return HTTP 200 within 100ms (processing is background)
- [ ] Slack retries (`X-Slack-Retry-Num` header) are immediately acknowledged
- [ ] Users see a typing indicator while agent processes
- [ ] File attachments (PDF, images, text) are downloaded and passed to agent
- [ ] Interactive buttons/menus trigger registered handlers
- [ ] Modal forms can be opened and submissions handled
- [ ] Socket Mode works for local development without ngrok
- [ ] Agents & AI Apps integration shows in Slack's AI panel (when enabled)
- [ ] All unit tests pass (`pytest tests/unit/slack/ -v`)
- [ ] All integration tests pass (`pytest tests/integration/slack/ -v`)
- [ ] No breaking changes to existing `SlackAgentConfig` usage
- [ ] Documentation updated in `docs/integrations/slack.md`

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Use async/await throughout — no blocking I/O
- Use `aiohttp.ClientSession` for HTTP calls (reuse session when possible)
- Use `asyncio.create_task()` for background processing
- Use `asyncio.Semaphore` to limit concurrent requests
- Use Pydantic or dataclass for configuration
- Use `self.logger` for logging (no print statements)
- Follow existing wrapper patterns from MS Teams and Telegram

### Known Risks / Gotchas

| Risk | Mitigation |
|---|---|
| Multi-instance deduplication | Use `RedisEventDeduplicator` for production clusters |
| Socket Mode not for production | Document clearly, use webhook mode in prod |
| Agents & AI Apps requires paid Slack | Document requirement, graceful fallback |
| `chat_stream()` requires SDK 3.40+ | Pin dependency version |
| Rate limits on Slack API | Implement exponential backoff |
| File download auth | Use bot token in Authorization header |

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `slack-sdk` | `>=3.40.0` | Chat streaming, async client, Socket Mode |
| `slack-bolt` | `>=1.21.1` | Optional: Assistant middleware (can use raw API) |
| `aiohttp` | existing | HTTP client, already in AI-Parrot |
| `redis` | optional | Production deduplication |

---

## 7. Open Questions

- [x] Question 1: Should we support both in-memory and Redis deduplication? — *Yes, make Redis optional*
- [ ] Question 2: Should Socket Mode be the default for development? — *Owner: Team*: Yes
- [ ] Question 3: Should we auto-generate thread titles from first message? — *Owner: Team*: Yes
- [ ] Question 4: Should feedback buttons be opt-in or default? — *Owner: Team*: Yes

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-24 | Claude | Initial draft from brainstorm document |
