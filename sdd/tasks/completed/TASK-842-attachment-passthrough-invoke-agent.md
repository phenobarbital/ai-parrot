# TASK-842: Attachment passthrough in _invoke_agent and handle_photo refactor

**Feature**: FEAT-120 — Telegram Wrapper Rich Message Integration
**Spec**: `sdd/specs/telegram-wrapper-audio-files-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 4. The `_invoke_agent` method currently does not accept an `attachments`
parameter. The photo handler (`handle_photo`) calls `agent.ask()` directly with
`attachments=attachment_paths`, bypassing `_invoke_agent` entirely. This task adds
`attachments` support to `_invoke_agent`, refactors `handle_photo` to use it, and
adds debug logging at each stage of the attachment pipeline.

---

## Scope

- Extend `_invoke_agent` signature with `attachments: Optional[List[str]] = None` parameter
- Forward `attachments` to both `agent.ask()` call sites inside `_invoke_agent`
  (singleton mode at line 1150 and per-user mode at line 1166)
- Add `self.logger.debug()` calls at attachment pipeline stages:
  - When `attachments` is received by `_invoke_agent`
  - When `attachments` is forwarded to `agent.ask()`
- Refactor `handle_photo` to call `_invoke_agent` instead of `agent.ask()` directly
  - The `ask_with_image` branch remains (for multimodal agents) but the else-branch
    must use `_invoke_agent`
  - Pass `attachments=attachment_paths` to `_invoke_agent`
- Write unit tests for the new parameter and the photo handler refactor

**NOT in scope**: Reply context (TASK-844), document handler (TASK-845), message ID tracking (TASK-843)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Extend `_invoke_agent`, refactor `handle_photo` |
| `tests/unit/test_telegram_attachments_feat120.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py
from typing import Optional, List, Dict, Any, Tuple  # line 1 area
import logging                                        # stdlib
import tempfile                                       # stdlib
from pathlib import Path                              # stdlib
from aiogram.types import Message                     # line 22
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:1114
async def _invoke_agent(
    self,
    session: TelegramUserSession,
    question: str,
    *,
    memory: Any,
    output_mode: OutputMode = OutputMode.TELEGRAM,
    message: Optional[Message] = None,
) -> Any:
    # Singleton branch — agent.ask() at line 1150:
    return await agent.ask(
        enriched,
        user_id=session.user_id,
        session_id=session.session_id,
        memory=memory,
        output_mode=output_mode,
        permission_context=permission_context,
    )
    # Per-user branch — agent.ask() at line 1166:
    return await agent.ask(
        enriched,
        user_id=session.user_id,
        session_id=session.session_id,
        memory=memory,
        output_mode=output_mode,
        permission_context=permission_context,
    )

# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:2476
async def handle_photo(self, message: Message) -> None:
    # Downloads photo to temp file
    # Calls agent.ask() directly at line 2532 (else branch) and
    # agent.ask_with_image() at line 2523 (if branch)
    # Uses: self.bot.get_file(), self.bot.download_file()
    # Uses: self._get_or_create_memory(), self._get_user_session()
    # Uses: self._enrich_question(), self._parse_response(), self._send_parsed_response()
    # Uses: telegram_chat_scope context manager

# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:62
class TelegramAgentWrapper:
    logger: logging.Logger                             # line 99
    _agent_lock: asyncio.Lock                          # line 112
```

### Does NOT Exist
- ~~`_invoke_agent(attachments=...)`~~ — does not accept `attachments` yet; this task adds it
- ~~`agent.ask(attachments=...)` forwarding~~ — `base.py` silently drops `attachments` from `**kwargs`; path in text is primary mechanism
- ~~`handle_photo` calling `_invoke_agent`~~ — currently calls `agent.ask()` directly; this task refactors it
- ~~`self._attachment_logger`~~ — no separate logger; use `self.logger`

---

## Implementation Notes

### Pattern to Follow

Add `attachments` as a keyword-only parameter to `_invoke_agent`:

```python
async def _invoke_agent(
    self,
    session: TelegramUserSession,
    question: str,
    *,
    memory: Any,
    output_mode: OutputMode = OutputMode.TELEGRAM,
    message: Optional[Message] = None,
    attachments: Optional[List[str]] = None,        # NEW
) -> Any:
    ...
    if attachments:
        self.logger.debug(
            "Chat %s: _invoke_agent received attachments: %s",
            session.telegram_id, attachments,
        )
    ...
    # In both agent.ask() call sites, add: attachments=attachments
```

For `handle_photo` refactor, replace the else-branch direct `agent.ask()` call with
`_invoke_agent` while keeping the `ask_with_image` branch as-is (multimodal agents
have a different API).

### Key Constraints
- `_invoke_agent` is called from `handle_message` (line 1998), group handlers, and
  custom command handlers — adding `attachments=None` default is backward-compatible
- The `ask_with_image` branch in `handle_photo` stays separate — it has a different
  API (`image_path` kwarg) that `_invoke_agent` does not need to know about
- Debug-level logging only — never log file contents, only paths

### References in Codebase
- `wrapper.py:1114-1173` — current `_invoke_agent` implementation
- `wrapper.py:2476-2550` — current `handle_photo` implementation
- `wrapper.py:1997-2004` — how `handle_message` calls `_invoke_agent`

---

## Acceptance Criteria

- [ ] `_invoke_agent` accepts optional `attachments` keyword parameter
- [ ] `attachments` is forwarded to `agent.ask()` in both singleton and per-user branches
- [ ] Debug log emitted when `_invoke_agent` receives non-empty `attachments`
- [ ] `handle_photo` else-branch uses `_invoke_agent` instead of direct `agent.ask()`
- [ ] `handle_photo` `ask_with_image` branch still works (passes `attachments` directly)
- [ ] Existing `handle_message` calls to `_invoke_agent` are unaffected (no attachments)
- [ ] All unit tests pass: `pytest tests/unit/test_telegram_attachments_feat120.py -v`

---

## Test Specification

```python
# tests/unit/test_telegram_attachments_feat120.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestInvokeAgentAttachments:
    async def test_invoke_agent_forwards_attachments(self):
        """attachments kwarg reaches agent.ask()."""
        # Mock agent.ask, call _invoke_agent with attachments=["/tmp/photo.jpg"]
        # Assert agent.ask was called with attachments=["/tmp/photo.jpg"]

    async def test_invoke_agent_no_attachments_default(self):
        """When no attachments passed, agent.ask() is called without attachments kwarg."""
        # Verify backward compat — existing callers unaffected

    async def test_invoke_agent_logs_attachment_paths(self):
        """Debug log entries include attachment file paths."""
        # Verify logger.debug called with attachment path info


class TestHandlePhotoRefactor:
    async def test_handle_photo_uses_invoke_agent(self):
        """Photo handler (non-multimodal path) calls _invoke_agent with attachments."""
        # Mock _invoke_agent, trigger handle_photo
        # Assert _invoke_agent called with attachments=[path]

    async def test_handle_photo_ask_with_image_still_works(self):
        """Photo handler multimodal path still calls ask_with_image directly."""
        # Agent has ask_with_image → verify it's called with image_path and attachments
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `_invoke_agent` signature at line 1114, `handle_photo` at line 2476
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-842-attachment-passthrough-invoke-agent.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-23
**Notes**: Extended `_invoke_agent` with `attachments: Optional[List[str]] = None` kwarg forwarded to both `agent.ask()` call sites. Added debug logging when attachments present. Refactored `handle_photo` else-branch to use `_invoke_agent`. Also added missing `List` import from typing and `ChatAction` from aiogram.enums (pre-existing missing imports). All 6 unit tests pass.

**Deviations from spec**: Added `List` import and `ChatAction` import which were missing from wrapper.py (pre-existing issue, not scope creep — needed for the feature to work).
