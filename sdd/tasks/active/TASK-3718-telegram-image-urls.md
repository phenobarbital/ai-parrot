# TASK-3718: Telegram senders download URL images then send_photo (M12)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3716
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 12 (U1): Telegram cannot rely on remote URLs for figures here, so each
`ParsedResponse.image_urls` entry is downloaded to a bounded temp file (host allowlist from
`PARROT_MEDIA_URL_HOSTS`, redirect validation, 10 MB / 15 s caps, cleanup) and sent with the existing
`send_photo(FSInputFile)` path. Three Telegram send paths exist and all must handle URLs (AC14 "all seven
send paths covered"):

1. `TelegramAgentWrapper._send_attachments` (telegram/wrapper.py:2960) — images loop at `# Send images` :2987.
2. `TelegramAgentWrapper._send_parsed_response` (telegram/wrapper.py:3641) — images loop at `# Send images as photos` :3727.
3. `CrewAgentWrapper._send_response` (telegram/crew/crew_wrapper.py:314) — images loop at `# Send attachments (images)` :350.

**Drift vs spec (recorded at task time, 2026-09-25):** spec §6 Edit Sites cites the second sender as
`wrapper.py:3713-3716` "`if image_path.exists():` … `photo=FSInputFile(image_path),`" (2 occurrences, ambiguous).
Re-verification shows `photo=FSInputFile(image_path),` now occurs **4×** in telegram/wrapper.py
(2980, 2992, 3716, 3732) and lines 3713-3717 are the **charts** block of `_send_parsed_response`; that
method's own images loop is at 3727 (`# Send images as photos`, unique). This task anchors on the unique
comment lines below instead. Depends on TASK-3716 (`ParsedResponse.image_urls`, `temp_download`,
`allowed_media_hosts`).

---

## Scope

- Add one private helper `_send_url_photos(chat_id, urls, *, caption_prefix="")` on `TelegramAgentWrapper`
  that, for each URL, uses `temp_download(url, allowed_hosts=allowed_media_hosts())` and calls
  `self.bot.send_photo(chat_id=..., photo=FSInputFile(path), caption=...)`; refused/failed downloads are
  logged and skipped (never raise out of the sender).
- Call it from both Telegram wrapper senders right before their Path images loop.
- Add the equivalent URL loop to `CrewAgentWrapper._send_response` before `# Send attachments (images)`
  (crew wrapper is a separate class — inline the loop there, same semantics, `_SEND_DELAY` rate limit).
- Tests covering all three paths: allowlisted host ⇒ `send_photo` with a temp file that is removed
  afterwards; foreign host / oversize ⇒ no `send_photo`, no leftover file.

**NOT in scope**: `media_urls` video delivery via `send_video` (log + send as text link is acceptable, see
FILL IN); changing the Path loops; `media_download.py` itself (TASK-3716).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `_send_url_photos` helper + calls in `_send_attachments` and `_send_parsed_response` |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/crew/crew_wrapper.py` | MODIFY | URL download + `send_photo` loop in `_send_response` |
| `packages/ai-parrot-integrations/tests/test_media_urls_telegram.py` | CREATE | Tests for the three send paths |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiogram.types import FSInputFile                         # verified: telegram/crew/crew_wrapper.py:16; telegram/wrapper.py imports it inside `from aiogram.types import (` at :23-36
from parrot.integrations.parser import ParsedResponse         # verified: telegram/wrapper.py:57 (`from ..parser import parse_response, ParsedResponse`), crew_wrapper.py:24
from parrot.integrations.media_download import temp_download, allowed_media_hosts, MediaDownloadRefused   # created by TASK-3716
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper   # verified: telegram/wrapper.py:69
from parrot.integrations.telegram.crew.crew_wrapper import CrewAgentWrapper   # verified: crew_wrapper.py:82
import asyncio                                                # verified: telegram/wrapper.py:14, crew_wrapper.py:10
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper(OperatorCommandsMixin):                                   # line 69
    async def _send_attachments(self, chat_id: int, parsed: ParsedResponse) -> None:  # line 2960; "        # Send images" at 2987 (exact-line occurrences: 1)
    async def _send_parsed_response(self, message: Message, parsed: ParsedResponse, prefix: str = "") -> Optional[Message]:  # line 3641; chat_id = message.chat.id at 3653; "        # Send images as photos" at 3727 (occurrences: 1)
    # both loops: await self.bot.send_photo(chat_id=chat_id, photo=FSInputFile(image_path), caption=...); await asyncio.sleep(0.3)

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/crew/crew_wrapper.py
_SEND_DELAY = 0.3                                                                    # line 36
class CrewAgentWrapper:                                                              # line 82
    async def _send_response(self, chat_id: int, parsed: ParsedResponse, sender_mention: str, reply_to_message_id: Optional[int] = None) -> None:  # line 314; "        # Send attachments (images)" at 350 (occurrences: 1)
```

### Does NOT Exist
- ~~A URL/remote branch in any Telegram sender~~ — all three loops iterate `parsed.images` Paths only.
- ~~`TelegramAgentWrapper._send_url_photos`~~ — added here.
- ~~A shared sender between `TelegramAgentWrapper` and `CrewAgentWrapper`~~ — separate classes; crew does not inherit the wrapper.
- ~~Images in the `_send_parsed_response` block at 3713-3717~~ — that block sends **charts** (spec §6 row is stale).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/crew/crew_wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/test_media_urls_telegram.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._send_attachments",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._send_parsed_response",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/crew/crew_wrapper.py#CrewAgentWrapper._send_response",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/parser.py#ParsedResponse"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Existing Path loop in `_send_attachments` (telegram/wrapper.py:2987-2996). Test harness:
`TelegramAgentWrapper.__new__(TelegramAgentWrapper)` + `wrapper.bot = AsyncMock()` (precedent:
tests/integrations/test_telegram_photo_attachments.py:12-30). Patch `temp_download` at its import site in
the wrapper module to avoid real network, plus one test using a real `aiohttp.test_utils.TestServer` for
the allowlist path.

### Key Constraints
- Worktree tests: the shared `.venv` is editable-installed against the main checkout, so run tests with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest <file> -q`.
- No new third-party dependency (spec G8, AC18).
- Google-style docstrings and strict type hints on every function/class; Pydantic v2; `self.logger` / module
  `logging.getLogger(__name__)` — never `print`.
- HTTP is `aiohttp` only — never `requests` / `httpx` (ruff TID251 fails the merge gate).
- Existing `Path` attachment behaviour (`images` / `media` / `files` / `documents`) must stay byte-for-byte
  unchanged (AC14) — URL handling is strictly additive.
- Import `temp_download` / `allowed_media_hosts` at module top of both wrappers (they are in the same
  distribution — no optional-import guard needed).
- Send the temp file **inside** the `async with temp_download(...)` block so cleanup happens after
  `send_photo` returns.
- Never re-sign or fetch from chat history (spec §7 "Presigned URL lifetime") — only the URLs of the current parsed response.

---

## Implementation Blueprint

### Steps (in order)
1. Add the imports and `_send_url_photos` to `TelegramAgentWrapper` — *why*: one helper serves both wrapper senders, keeping each insertion to one line.
2. Call the helper above `        # Send images` in `_send_attachments` and above `        # Send images as photos` in `_send_parsed_response` — *why*: both are live send paths (AC14); unique exact-line anchors avoid the 4× `FSInputFile` ambiguity.
3. Add the inline loop to `CrewAgentWrapper._send_response` — *why*: crew is a separate class and a separate send path.
4. Write tests for the three paths — *why*: AC14 requires every send path covered, with cleanup verified.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'from ..parser import parse_response, ParsedResponse' packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py)
# AFTER — insert below `from ..parser import parse_response, ParsedResponse` (verified: telegram/wrapper.py:57)
from ..media_download import MediaDownloadRefused, allowed_media_hosts, temp_download
```
```python
# occurrences: 1 (verified: grep -cF 'async def _send_attachments(self, chat_id: int, parsed: ParsedResponse) -> None:' .../telegram/wrapper.py)
# BEFORE — insert above `    async def _send_attachments(self, chat_id: int, parsed: ParsedResponse) -> None:` (verified: telegram/wrapper.py:2960)
    async def _send_url_photos(self, chat_id: int, urls: List[str]) -> None:
        """Download each remote image URL (bounded, allowlisted) and send it as a photo.

        Args:
            chat_id: Target chat.
            urls: http(s) image URLs from ``ParsedResponse.image_urls``.
        """
        hosts = allowed_media_hosts()
        for url in urls:
            try:
                async with temp_download(url, allowed_hosts=hosts) as path:
                    await self.bot.send_photo(chat_id=chat_id, photo=FSInputFile(path))
                await asyncio.sleep(0.3)
            except MediaDownloadRefused as exc:
                self.logger.warning("Refused image URL %s: %s", url, exc)
            except Exception as exc:  # noqa: BLE001 — a failed attachment must not abort the reply
                self.logger.error("Failed to send image URL %s: %s", url, exc)
        # FILL IN: caption policy (e.g. "Figure n" when len(urls) > 1, mirroring the Path loop's multi-image caption) — bounded by spec §3 M12

```
```python
# occurrences: 1 (verified: grep -cxF '        # Send images' .../telegram/wrapper.py — exact line; the substring also appears in "# Send images as photos")
# BEFORE — insert above `        # Send images` inside _send_attachments (verified: telegram/wrapper.py:2987)
        # Remote image URLs (FEAT-601 M12)
        await self._send_url_photos(chat_id, list(getattr(parsed, "image_urls", []) or []))
```
```python
# occurrences: 1 (verified: grep -cxF '        # Send images as photos' .../telegram/wrapper.py)
# BEFORE — insert above `        # Send images as photos` inside _send_parsed_response (verified: telegram/wrapper.py:3727)
        # Remote image URLs (FEAT-601 M12)
        await self._send_url_photos(chat_id, list(getattr(parsed, "image_urls", []) or []))
        # FILL IN: parsed.media_urls → append as text links in this method's text flow or a follow-up message — bounded by spec §3 M12
```
**Why**: unique exact-line anchors (the 4× `FSInputFile` line is ambiguous); `chat_id` is already bound in
both methods (2960 signature, 3653); `List` is imported at telegram/wrapper.py:12.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/crew/crew_wrapper.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'from ...parser import parse_response, ParsedResponse' .../telegram/crew/crew_wrapper.py)
# AFTER — insert below `from ...parser import parse_response, ParsedResponse` (verified: crew_wrapper.py:24)
from ...media_download import MediaDownloadRefused, allowed_media_hosts, temp_download
```
```python
# occurrences: 1 (verified: grep -cxF '        # Send attachments (images)' .../telegram/crew/crew_wrapper.py)
# BEFORE — insert above `        # Send attachments (images)` (verified: crew_wrapper.py:350)
        # Remote image URLs (FEAT-601 M12) — bounded download, then the same send_photo path
        for url in getattr(parsed, "image_urls", []) or []:
            try:
                async with temp_download(url, allowed_hosts=allowed_media_hosts()) as path:
                    await self.bot.send_photo(chat_id=chat_id, photo=FSInputFile(path))
                await asyncio.sleep(_SEND_DELAY)
            except MediaDownloadRefused as exc:
                self.logger.warning("Refused image URL %s: %s", url, exc)
            except Exception as exc:  # noqa: BLE001
                self.logger.error("Failed to send image URL %s: %s", url, exc)
```
**Why**: crew wrapper does not share the main wrapper's helper; semantics identical, rate limit uses its own `_SEND_DELAY`.

### `packages/ai-parrot-integrations/tests/test_media_urls_telegram.py` (CREATE)
```python
"""FEAT-601 M12 — Telegram URL images: download → send_photo → cleanup (TASK-3718)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.parser import ParsedResponse
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper


def _wrapper() -> TelegramAgentWrapper:
    w = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    w.bot = AsyncMock()
    w.logger = MagicMock()
    # FILL IN: any other attribute the two senders read (config.use_html, _send_long_message, …) — verify in wrapper.py
    return w


async def test_telegram_downloads_then_send_photo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """_send_attachments: allowlisted URL ⇒ send_photo with a temp file that no longer exists afterwards."""
    # FILL IN: monkeypatch PARROT_MEDIA_URL_HOSTS; patch temp_download in the wrapper module with a fake
    #          async CM yielding a real temp file then deleting it; assert send_photo called and file gone


async def test_telegram_parsed_response_path_sends_url() -> None:
    """_send_parsed_response (second sender) also sends URL images."""
    # FILL IN


async def test_telegram_foreign_host_refused_no_send() -> None:
    """Foreign host / redirect / oversize ⇒ MediaDownloadRefused logged, no send_photo, no leftover file."""
    # FILL IN


async def test_crew_wrapper_sends_url_images() -> None:
    """CrewAgentWrapper._send_response downloads and sends URL images."""
    # FILL IN: CrewAgentWrapper.__new__ + bot AsyncMock + logger; verify attributes _send_response reads
    pass
```

### FILL IN checklist
- [ ] `_send_url_photos` caption policy — spec §3 M12
- [ ] `media_urls` handling in `_send_parsed_response` — spec §3 M12
- [ ] test harness attributes verified against the sender bodies

---

## Acceptance Criteria

- [ ] All three Telegram send paths deliver `image_urls` via bounded download + `send_photo(FSInputFile)`
- [ ] Temp files removed after send; refused URLs logged, not raised
- [ ] Path images/documents/media loops unchanged
- [ ] `ruff check` clean on both wrappers
- [ ] All tests pass (see Validation Commands)

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/test_media_urls_telegram.py -q`

---

## Test Specification

| Test | Description |
|---|---|
| `test_telegram_downloads_then_send_photo` | spec §4 M12: allowlisted host ⇒ temp file → `send_photo`; cleanup verified |
| `test_telegram_parsed_response_path_sends_url` | second sender path covered |
| `test_telegram_foreign_host_refused_no_send` | foreign host/redirect/oversize ⇒ refused, cleanup verified |
| `test_crew_wrapper_sends_url_images` | crew send path covered |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/training-agent.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
