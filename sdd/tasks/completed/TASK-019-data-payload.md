# TASK-019: DataPayload

**Feature**: FEAT-010 — TelegramCrewTransport
**Spec**: `sdd/specs/telegram-crew-transport.spec.md`
**Status**: in-progress
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

This task implements Module 4 from the spec. `DataPayload` handles file exchange between agents via Telegram document attachments. It manages downloading documents from Telegram messages, uploading files to the group, MIME type validation, and CSV convenience methods.

Implements spec Section 3, Module 4.

---

## Scope

- Implement `DataPayload` class with file download/upload functionality
- Implement `download_document(bot, message)` — downloads a Telegram document to temp dir
- Implement `send_document(bot, chat_id, file_path, caption, reply_to_message_id)` — uploads file to group
- Implement `send_csv(bot, chat_id, dataframe, filename, caption)` — serializes pandas DataFrame to CSV and sends
- Implement MIME type validation against allowed list
- Implement temp file management (creation, cleanup)
- Handle caption length limit (1024 chars) — split into separate message if exceeded

**NOT in scope**: Agent logic, mention routing, coordinator integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/crew/payload.py` | CREATE | DataPayload implementation |
| `tests/test_telegram_crew/test_payload.py` | CREATE | Unit tests with mocked Bot |

---

## Implementation Notes

### Key Constraints
- Use `aiofiles` for async file operations
- Use `aiogram.types.FSInputFile` for uploads
- MIME type validation: reject files not in the allowed list
- Caption limit: 1024 chars for Telegram document captions
- Max file size: configurable (default 50MB)
- Temp dir: configurable, default `/tmp/parrot_crew`
- Clean up temp files after use
- Use `logging.getLogger(__name__)`

### References in Codebase
- `parrot/integrations/telegram/handlers/` — existing file handling patterns
- `parrot/integrations/telegram/utils.py` — existing Telegram utility functions

---

## Acceptance Criteria

- [ ] MIME type validation rejects disallowed types
- [ ] Document download works with mocked Bot (saves to temp dir)
- [ ] Document upload works with mocked Bot (uses FSInputFile)
- [ ] CSV serialization creates valid file and sends
- [ ] Caption splitting works when exceeding 1024 chars
- [ ] Temp files are cleaned up properly
- [ ] All tests pass: `pytest tests/test_telegram_crew/test_payload.py -v`
- [ ] Import works: `from parrot.integrations.telegram.crew.payload import DataPayload`

---

## Test Specification

```python
# tests/test_telegram_crew/test_payload.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.integrations.telegram.crew.payload import DataPayload


@pytest.fixture
def payload(tmp_path):
    return DataPayload(
        temp_dir=str(tmp_path),
        max_file_size_mb=50,
        allowed_mime_types=["text/csv", "application/json", "image/png"],
    )


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.download = AsyncMock()
    bot.send_document = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


class TestDataPayload:
    def test_mime_validation_allowed(self, payload):
        assert payload.validate_mime("text/csv") is True

    def test_mime_validation_rejected(self, payload):
        assert payload.validate_mime("application/x-executable") is False

    @pytest.mark.asyncio
    async def test_download_document(self, payload, mock_bot):
        # Setup mock message with document
        message = MagicMock()
        message.document.file_id = "file123"
        message.document.file_name = "data.csv"
        message.document.mime_type = "text/csv"
        message.document.file_size = 1024
        mock_bot.get_file = AsyncMock()
        path = await payload.download_document(mock_bot, message)
        assert path is not None

    @pytest.mark.asyncio
    async def test_send_document(self, payload, mock_bot, tmp_path):
        test_file = tmp_path / "test.csv"
        test_file.write_text("a,b\n1,2")
        await payload.send_document(
            mock_bot, chat_id=-100123, file_path=str(test_file), caption="Test data"
        )
        mock_bot.send_document.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_csv(self, payload, mock_bot):
        import pandas as pd
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        await payload.send_csv(mock_bot, chat_id=-100123, dataframe=df, filename="test.csv")
        mock_bot.send_document.assert_called_once()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/telegram-crew-transport.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-019-data-payload.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented `DataPayload` with download/upload, MIME validation, file size validation, caption splitting (1024 char limit), CSV serialization via pandas, and temp file cleanup. Uses `aiogram.types.FSInputFile` for uploads and `bot.get_file/download_file` for downloads. All 17 unit tests pass with mocked Bot.

**Deviations from spec**: none
