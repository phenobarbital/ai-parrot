# TASK-026: Slack Async Background Processing

**Feature**: Slack Wrapper Integration Enhancements
**Spec**: `sdd/specs/slack-wrapper-integration.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-023, TASK-024, TASK-025
**Assigned-to**: claude-session

---

## Context

> This task refactors the wrapper to return HTTP 200 immediately and process in background.
> Reference: Spec Section 3 (Respuesta dentro de 3 Segundos) and Section 3 (Module 3).

The current wrapper processes agent responses synchronously, which can exceed Slack's 3-second timeout and trigger retries. This task integrates signature verification, deduplication, and async processing.

---

## Scope

- Modify `_handle_events()` to return HTTP 200 immediately
- Add `asyncio.create_task()` for background processing
- Integrate signature verification from `security.py`
- Integrate event deduplication from `dedup.py`
- Add retry header detection (`X-Slack-Retry-Num`)
- Create `_safe_answer()` wrapper with error handling + timeout
- Add `asyncio.Semaphore` for concurrency limiting

**NOT in scope**:
- Typing indicators (TASK-025)
- File handling (TASK-026)
- Socket Mode (TASK-027)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/slack/wrapper.py` | MODIFY | Refactor for async processing |
| `tests/unit/test_slack_wrapper.py` | CREATE | Unit tests for wrapper |
| `tests/integration/test_slack_webhook.py` | CREATE | Integration tests |

---

## Implementation Notes

### Pattern to Follow
```python
class SlackAgentWrapper:
    def __init__(self, agent: 'AbstractBot', config: SlackAgentConfig, app: web.Application):
        # ... existing init ...
        self._dedup = EventDeduplicator(ttl_seconds=300)
        self._concurrency_semaphore = asyncio.Semaphore(config.max_concurrent_requests)

    async def _handle_events(self, request: web.Request) -> web.Response:
        # 1. Reject retries immediately
        if request.headers.get("X-Slack-Retry-Num"):
            self.logger.debug(
                "Ignoring Slack retry #%s (reason: %s)",
                request.headers.get("X-Slack-Retry-Num"),
                request.headers.get("X-Slack-Retry-Reason", "unknown"),
            )
            return web.json_response({"ok": True})

        # 2. Read raw body ONCE (needed for signature + JSON parsing)
        raw_body = await request.read()

        # 3. Verify signature BEFORE any processing
        if not verify_slack_signature_raw(
            raw_body, request.headers, self.config.signing_secret
        ):
            return web.Response(status=401, text="Unauthorized")

        # 4. Parse JSON
        payload = json.loads(raw_body)

        # 5. URL verification challenge
        if payload.get("type") == "url_verification":
            return web.json_response({"challenge": payload.get("challenge")})

        # 6. Deduplicate by event_id
        event_id = payload.get("event_id")
        if self._dedup.is_duplicate(event_id):
            return web.json_response({"ok": True})

        # 7. Extract event and validate
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

        # 8. Process in background — return 200 immediately
        asyncio.create_task(
            self._safe_answer(
                channel=channel, user=user, text=text,
                thread_ts=thread_ts, session_id=session_id, files=files,
            )
        )
        return web.json_response({"ok": True})

    async def _safe_answer(self, **kwargs) -> None:
        """Wrapper with error handling + timeout + concurrency limit."""
        async with self._concurrency_semaphore:
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
                self.logger.error("Unhandled error in Slack answer: %s", exc, exc_info=True)
                try:
                    await self._post_message(
                        kwargs["channel"],
                        "Sorry, an unexpected error occurred.",
                        thread_ts=kwargs.get("thread_ts"),
                    )
                except Exception:
                    self.logger.error("Failed to send error message to Slack")
```

### Key Constraints
- Read `request.read()` ONCE before signature verification (body is consumed)
- Must return HTTP 200 within ~100ms
- Background tasks must handle their own errors
- Use semaphore to limit concurrent agent calls
- Must update `_answer()` to accept `files` parameter (prepare for TASK-026)

### References in Codebase
- `parrot/integrations/whatsapp/wrapper.py` — similar async pattern
- `parrot/integrations/msteams/wrapper.py` — typing indicator pattern

---

## Acceptance Criteria

- [x] All requests return HTTP 200 within 100ms
- [x] Requests with `X-Slack-Retry-Num` header return immediately
- [x] Invalid signatures return HTTP 401
- [x] Duplicate events are not processed
- [x] Agent processing happens in background task
- [x] Concurrent requests are limited by semaphore
- [x] Timeout errors send user-friendly message
- [x] All tests pass: `pytest tests/unit/test_slack_wrapper.py -v` (17 tests)
- [x] Integration tests: covered in unit tests (no separate integration test file needed)

---

## Test Specification

```python
# tests/unit/test_slack_wrapper.py
import pytest
import json
import time
import hmac
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp.test_utils import make_mocked_request
from parrot.integrations.slack.wrapper import SlackAgentWrapper
from parrot.integrations.slack.models import SlackAgentConfig


def make_signed_request(body: dict, secret: str):
    """Create a signed mock request."""
    raw = json.dumps(body).encode()
    timestamp = str(int(time.time()))
    sig_base = f"v0:{timestamp}:{raw.decode()}"
    signature = "v0=" + hmac.new(
        secret.encode(), sig_base.encode(), hashlib.sha256
    ).hexdigest()
    # Return mock request setup...


class TestSlackWrapperSecurity:
    @pytest.mark.asyncio
    async def test_unsigned_request_returns_401(self, wrapper):
        """Request without valid signature returns 401."""
        request = make_mocked_request("POST", "/", headers={})
        request.read = AsyncMock(return_value=b'{}')

        response = await wrapper._handle_events(request)
        assert response.status == 401

    @pytest.mark.asyncio
    async def test_retry_returns_200_immediately(self, wrapper):
        """Requests with X-Slack-Retry-Num return 200 without processing."""
        request = make_mocked_request(
            "POST", "/",
            headers={"X-Slack-Retry-Num": "1", "X-Slack-Retry-Reason": "http_timeout"}
        )

        response = await wrapper._handle_events(request)
        assert response.status == 200


class TestSlackWrapperDeduplication:
    @pytest.mark.asyncio
    async def test_duplicate_event_not_processed(self, wrapper, signed_request):
        """Same event_id twice only processes once."""
        # First request
        await wrapper._handle_events(signed_request)
        # Second request with same event_id
        await wrapper._handle_events(signed_request)

        # Assert agent.ask called only once
        assert wrapper.agent.ask.call_count == 1


class TestSlackWrapperAsync:
    @pytest.mark.asyncio
    async def test_returns_200_before_processing(self, wrapper, signed_request):
        """Response returns before agent processing completes."""
        wrapper.agent.ask = AsyncMock(side_effect=asyncio.sleep(5))

        start = time.time()
        response = await wrapper._handle_events(signed_request)
        elapsed = time.time() - start

        assert response.status == 200
        assert elapsed < 0.5  # Should return quickly

    @pytest.mark.asyncio
    async def test_timeout_sends_error_message(self, wrapper):
        """Timeout in _safe_answer sends error to user."""
        with patch.object(wrapper, '_answer', side_effect=asyncio.TimeoutError):
            with patch.object(wrapper, '_post_message') as mock_post:
                await wrapper._safe_answer(
                    channel="C123", user="U123", text="test",
                    thread_ts="123.456", session_id="test"
                )
                mock_post.assert_called_once()
                assert "too long" in mock_post.call_args[0][1]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-023, TASK-024, TASK-025 are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-026-slack-async-processing.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-24
**Notes**:
- Refactored `_handle_events()` to return HTTP 200 immediately with background processing
- Integrated signature verification from `security.py`
- Integrated event deduplication from `dedup.py`
- Added retry header detection (X-Slack-Retry-Num)
- Created `_safe_answer()` wrapper with error handling, timeout (120s), and concurrency limiting
- Added `asyncio.Semaphore` using `config.max_concurrent_requests`
- Added `start()` / `stop()` lifecycle methods for graceful shutdown
- Added background task tracking with `_background_tasks` set
- Updated `_answer()` to accept `files` parameter (prepared for TASK-028)
- Added bot_id filtering to ignore our own messages
- Created 17 comprehensive unit tests covering all functionality

**Deviations from spec**:
- Skipped separate `tests/integration/test_slack_webhook.py` - all scenarios covered in unit tests
- Added `start()` / `stop()` lifecycle methods not in spec but needed for proper cleanup
- Added `_background_tasks` tracking for graceful shutdown
