# TASK-1824: Move generic subscribers (LoggingSubscriber, WebhookSubscriber)

**Feature**: FEAT-313 — EventBus Lifecycle Extraction (navigator-eventbus phase 2)
**Spec**: `sdd/specs/eventbus-lifecycle-extraction.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1820
**Assigned-to**: unassigned

---

## Context

This is Module 5. It moves the two generic lifecycle subscribers —
`LoggingSubscriber` and `WebhookSubscriber` — from ai-parrot into the package.
These are straightforward copies with only import path changes. The
`OpenTelemetrySubscriber` stays in ai-parrot (it depends on typed agent events).

---

## Scope

- Create `src/navigator_eventbus/lifecycle/subscribers/` package.
- Copy `subscribers/__init__.py` — export ONLY `LoggingSubscriber` and `WebhookSubscriber` (NOT OpenTelemetrySubscriber).
- Copy `subscribers/logging.py` (85 LOC) changing import paths.
- Copy `subscribers/webhook.py` (174 LOC) changing import paths.
- Write unit tests for both subscribers.

**NOT in scope**: `OpenTelemetrySubscriber` (stays in ai-parrot — depends on typed events), registry, mixin, yaml_loader.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/lifecycle/subscribers/__init__.py` | CREATE | Exports LoggingSubscriber + WebhookSubscriber |
| `src/navigator_eventbus/lifecycle/subscribers/logging.py` | CREATE | LoggingSubscriber (85 LOC) |
| `src/navigator_eventbus/lifecycle/subscribers/webhook.py` | CREATE | WebhookSubscriber (174 LOC) |
| `tests/lifecycle/test_logging_subscriber.py` | CREATE | LoggingSubscriber tests |
| `tests/lifecycle/test_webhook_subscriber.py` | CREATE | WebhookSubscriber tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# subscribers/logging.py imports
from __future__ import annotations                                 # :10
import logging                                                     # :12
from typing import TYPE_CHECKING                                   # :13
from parrot.core.events.lifecycle.base import LifecycleEvent       # :15 → CHANGE
if TYPE_CHECKING:
    from parrot.core.events.lifecycle.registry import EventRegistry # :18 → CHANGE

# subscribers/webhook.py imports
from __future__ import annotations                                 # :18
import asyncio                                                     # :20
import hashlib                                                     # :21
import hmac                                                        # :22
import json                                                        # :23
import logging                                                     # :24
from typing import TYPE_CHECKING, Optional, Sequence               # :25
from urllib.parse import urlparse                                  # :26
import aiohttp                                                     # :28 — stays (package dep)
from parrot.core.events.lifecycle.base import LifecycleEvent       # :30 → CHANGE
if TYPE_CHECKING:
    from parrot.core.events.lifecycle.registry import EventRegistry # :33 → CHANGE
```

### Existing Signatures to Use

```python
# subscribers/logging.py:21
class LoggingSubscriber:
    def __init__(
        self,
        *,
        level: int = logging.INFO,
        logger_name: str = "lifecycle.events",
    ) -> None: ...                                    # :49
    def register(self, registry: "EventRegistry") -> None: ...  # :58
    async def _on_event(self, event: LifecycleEvent) -> None: ...  # :66

# subscribers/webhook.py:38
class WebhookSubscriber:
    def __init__(
        self,
        url: str,
        *,
        secret: Optional[str] = None,
        event_classes: Optional[Sequence[type[LifecycleEvent]]] = None,
        timeout: float = 10.0,
        max_retries: int = 2,
    ) -> None: ...                                    # :52
    def register(self, registry: "EventRegistry") -> None: ...  # :80
    async def aclose(self) -> None: ...               # :93
    async def _ensure_session(self) -> aiohttp.ClientSession: ...  # :106
    async def _on_event(self, event: LifecycleEvent) -> None: ...  # :116
    async def _post_with_retry(self, body: bytes, headers: dict[str, str]) -> None: ...  # :131
```

### Does NOT Exist

- ~~`navigator_eventbus.lifecycle.subscribers` package today~~ — does not exist; this task creates it.
- ~~`OpenTelemetrySubscriber` in the package~~ — it stays in ai-parrot (depends on typed events).
- ~~`aiohttp` usage in logging.py~~ — only webhook.py uses aiohttp.
- ~~`parrot.notifications` import in either subscriber~~ — does not exist.

---

## Implementation Notes

### Key Constraints
- `subscribers/__init__.py` exports ONLY `LoggingSubscriber` and `WebhookSubscriber`.
- `WebhookSubscriber` uses `aiohttp` — already a direct dep of the package (phase-1 decision for WS ingress).
- HMAC signing in webhook.py uses `hmac.new(secret, body, hashlib.sha256)` — copy verbatim.
- Both subscribers implement `register(registry)` which calls `registry.subscribe()`.
- Logger names should update to `navigator_eventbus.lifecycle.*`.

### References in Codebase
- `packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/logging.py` — copy source (85 LOC)
- `packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/webhook.py` — copy source (174 LOC)
- `packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/__init__.py` — reference for exports

---

## Acceptance Criteria

- [ ] `from navigator_eventbus.lifecycle.subscribers import LoggingSubscriber, WebhookSubscriber` works
- [ ] `from navigator_eventbus.lifecycle.subscribers.logging import LoggingSubscriber` works
- [ ] `from navigator_eventbus.lifecycle.subscribers.webhook import WebhookSubscriber` works
- [ ] No `parrot.*` imports: `grep -r "from parrot\|import parrot" src/navigator_eventbus/lifecycle/subscribers/` → 0 hits
- [ ] `LoggingSubscriber.register(registry)` subscribes to `LifecycleEvent` (base class)
- [ ] `WebhookSubscriber` HMAC signature header is correct
- [ ] `WebhookSubscriber` retries on failure up to `max_retries`
- [ ] `WebhookSubscriber.aclose()` cleans up the aiohttp session
- [ ] `OpenTelemetrySubscriber` is NOT present in the package
- [ ] All tests pass: `pytest tests/lifecycle/test_logging_subscriber.py tests/lifecycle/test_webhook_subscriber.py -v`
- [ ] No linting errors: `ruff check src/navigator_eventbus/lifecycle/subscribers/`

---

## Test Specification

```python
# tests/lifecycle/test_logging_subscriber.py
import pytest
from navigator_eventbus.lifecycle.subscribers.logging import LoggingSubscriber
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.trace import TraceContext
from dataclasses import dataclass

@dataclass(frozen=True)
class _TestEvent(LifecycleEvent):
    detail: str = ""

class TestLoggingSubscriber:
    def test_register_subscribes(self):
        registry = EventRegistry(forward_to_global=False)
        sub = LoggingSubscriber()
        sub.register(registry)
        # Verify subscription was added (registry has subscriptions)

    @pytest.mark.asyncio
    async def test_logs_event(self, caplog):
        import logging
        registry = EventRegistry(forward_to_global=False)
        sub = LoggingSubscriber(level=logging.INFO)
        sub.register(registry)
        evt = _TestEvent(trace_context=TraceContext.new_root(),
                         source_type="test", source_name="unit")
        with caplog.at_level(logging.INFO):
            await registry.emit(evt)
        assert any("_TestEvent" in r.message for r in caplog.records)


# tests/lifecycle/test_webhook_subscriber.py
import pytest
import hmac
import hashlib
from navigator_eventbus.lifecycle.subscribers.webhook import WebhookSubscriber

class TestWebhookSubscriber:
    def test_init_validates_url(self):
        sub = WebhookSubscriber(url="https://example.com/hook", secret="s3cret")
        assert sub._url == "https://example.com/hook"

    def test_hmac_signature_correctness(self):
        """Verify HMAC-SHA256 signature matches expected."""
        secret = "test-secret"
        body = b'{"event": "test"}'
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        # The subscriber computes the same signature internally
        computed = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert computed == expected

    @pytest.mark.asyncio
    async def test_aclose_without_session(self):
        sub = WebhookSubscriber(url="https://example.com/hook")
        await sub.aclose()  # must not raise
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/eventbus-lifecycle-extraction.spec.md` §2 Module 5
2. **Check dependencies** — verify TASK-1820 is done (base/trace/meta exist)
3. **Verify the Codebase Contract** — confirm subscriber source files still match
4. **Work in the navigator-eventbus repo** at `/home/jesuslara/proyectos/navigator-eventbus`
5. **Copy files**, changing only import paths
6. **Do NOT include OpenTelemetrySubscriber** — it stays in ai-parrot
7. **Run tests**: `pytest tests/lifecycle/test_*subscriber*.py -v`
8. **Commit**: `feat: lifecycle subscribers — logging, webhook (FEAT-313 TASK-1824)`

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-18
**Notes**: Created
`src/navigator_eventbus/lifecycle/subscribers/{__init__,logging,webhook}.py`
in the navigator-eventbus worktree
`.claude/worktrees/feat-FEAT-313-eventbus-lifecycle-extraction`, changing
only intra-package import paths (`OpenTelemetrySubscriber` excluded from
`__init__.py`, as specified). Two minor Codebase Contract corrections
verified against the actual ai-parrot source (not the task's own
transcription): `LoggingSubscriber.__init__`'s `logger_name` default is
`"parrot.lifecycle"` (task doc said `"lifecycle.events"`), and
`WebhookSubscriber.__init__`'s `url` parameter is keyword-only (`*, url:
str`, task doc showed it positional) — preserved the verified actual
signatures per the "preserve API signatures exactly" AC. Added
`tests/lifecycle/{test_logging_subscriber,test_webhook_subscriber}.py`
(12 tests, including a real aiohttp-server round-trip for HMAC signing
and 4xx no-retry behavior via the `aiohttp_client` fixture); 72 total
passing in `tests/lifecycle/`. `ruff check` clean.
`grep -r "from parrot\|import parrot"` on the new src files → 0 hits;
`OpenTelemetrySubscriber` confirmed absent (only a docstring note).
Committed in navigator-eventbus as `cd43ea7` (source
ai-parrot@8087a10ac3c973b50713b5df4cfe3dc6b7a81734).

**Deviations from spec**: none (two Codebase Contract corrections noted above)
