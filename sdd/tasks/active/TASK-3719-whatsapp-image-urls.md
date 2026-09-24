# TASK-3719: WhatsApp direct URL send with download fallback (M12)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3716
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 12 (U1): WhatsApp passes each `ParsedResponse.image_urls` entry straight to
`client.send_image(to=…, image=url)` — the same shape the charts loop already uses with
`chart.public_url` (whatsapp/wrapper.py:303) — and falls back to a bounded download
(`temp_download`, TASK-3716) when the provider rejects the URL. Implements AC14 (WhatsApp half).
Depends on TASK-3716 for `ParsedResponse.image_urls` and `temp_download`.

**Drift vs spec (recorded at task time, 2026-09-25):** spec §6 marks
`whatsapp/bridge_wrapper.py:260` as "verify only — routed through `_send_parsed_response`". Re-verification
shows `WhatsAppBridgeWrapper` (bridge_wrapper.py:80) has its **own** `_send_parsed_response`
(bridge_wrapper.py:276-301) that sends **text only** via the Go bridge `/send` endpoint — it does not reach
`WhatsAppAgentWrapper._send_parsed_response` and sends no images at all today. It stays out of this task's
files (no verified image endpoint on the bridge); flag it in the Completion Note for the orchestrator.

---

## Scope

- In `WhatsAppAgentWrapper._send_parsed_response`, after the existing Path images loop and before
  `# Send charts as images`, send each `parsed.image_urls` entry with
  `client.send_image(to=to, image=url)` via `loop.run_in_executor(_executor, …)` (pywa client is sync).
- On failure, fall back to `temp_download(url, allowed_hosts=allowed_media_hosts())` and send the local
  file path (`image=str(path)`, the existing Path shape); log and skip if the fallback is refused.
- Tests: direct URL success; provider error ⇒ download fallback; refused fallback ⇒ logged, no crash.

**NOT in scope**: `bridge_wrapper.py` (see drift); `media_urls` video sends (optional link text, see FILL IN);
the Path/charts/documents loops.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/wrapper.py` | MODIFY | URL image sends with download fallback in `_send_parsed_response` |
| `packages/ai-parrot-integrations/tests/test_media_urls_whatsapp.py` | CREATE | Direct / fallback / refused tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio                                                     # verified: whatsapp/wrapper.py:14
from concurrent.futures import ThreadPoolExecutor                  # verified: whatsapp/wrapper.py:16 (module-level _executor at :34)
from parrot.integrations.parser import ParsedResponse              # verified: whatsapp/wrapper.py:27 (`from ..parser import parse_response, ParsedResponse`)
from parrot.integrations.media_download import temp_download, allowed_media_hosts, MediaDownloadRefused   # created by TASK-3716
from parrot.integrations.whatsapp.wrapper import WhatsAppAgentWrapper   # verified: whatsapp/wrapper.py:37
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/wrapper.py
_executor = ThreadPoolExecutor(max_workers=4)                                    # line 34
class WhatsAppAgentWrapper:                                                      # line 37; self.logger at :60
    async def _send_parsed_response(self, to: str, parsed: ParsedResponse, client: WhatsApp) -> None:  # lines 246-248
        # loop = asyncio.get_event_loop() at 255
        # "        # Send images" at 286: for image_path in parsed.images: run_in_executor(_executor, lambda p=image_path: client.send_image(to=to, image=str(p)))
        # "        # Send charts as images" at 298: chart_source = chart.public_url or str(chart.path); client.send_image(to=to, image=src, caption=chart.title or None)   # 303-310
```

### Does NOT Exist
- ~~URL image handling in `WhatsAppAgentWrapper._send_parsed_response`~~ — only Paths and `chart.public_url`.
- ~~Image sending in `WhatsAppBridgeWrapper`~~ — text-only `_send_parsed_response` (bridge_wrapper.py:276-301).
- ~~An async pywa `send_image`~~ — the wrapper always calls it through `run_in_executor`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/test_media_urls_whatsapp.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/wrapper.py#WhatsAppAgentWrapper._send_parsed_response",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/parser.py#ParsedResponse"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
The charts loop (whatsapp/wrapper.py:298-311) — URL passed as `image=` through `run_in_executor` with a
default-bound lambda argument (avoid the late-binding closure bug: `lambda u=url: …`).

### Key Constraints
- Worktree tests: the shared `.venv` is editable-installed against the main checkout, so run tests with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest <file> -q`.
- No new third-party dependency (spec G8, AC18).
- Google-style docstrings and strict type hints on every function/class; Pydantic v2; `self.logger` / module
  `logging.getLogger(__name__)` — never `print`.
- HTTP is `aiohttp` only — never `requests` / `httpx` (ruff TID251 fails the merge gate).
- Existing `Path` attachment behaviour (`images` / `media` / `files` / `documents`) must stay byte-for-byte
  unchanged (AC14) — URL handling is strictly additive.
- The fallback `send_image(image=str(path))` must complete **inside** the `async with temp_download(...)`
  block so the temp file still exists while pywa uploads it.
- Test module must `pytest.importorskip("pywa")` because the wrapper imports `pywa` at module top (wrapper.py:20).

---

## Implementation Blueprint

### Steps (in order)
1. Import the downloader next to the parser import — *why*: fallback path needs it.
2. Insert the URL loop above `        # Send charts as images` — *why*: after the Path images keeps current output a strict prefix (AC14).
3. Write the tests — *why*: AC14 "WhatsApp direct URL then fallback".

### `packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/wrapper.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'from ..parser import parse_response, ParsedResponse' packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/wrapper.py)
# AFTER — insert below `from ..parser import parse_response, ParsedResponse` (verified: whatsapp/wrapper.py:27)
from ..media_download import MediaDownloadRefused, allowed_media_hosts, temp_download
```
```python
# occurrences: 1 (verified: grep -cxF '        # Send charts as images' .../whatsapp/wrapper.py)
# BEFORE — insert above `        # Send charts as images` (verified: whatsapp/wrapper.py:298)
        # Remote image URLs (FEAT-601 M12): direct URL first, bounded download on provider rejection
        for url in getattr(parsed, "image_urls", []) or []:
            try:
                await loop.run_in_executor(
                    _executor, lambda u=url: client.send_image(to=to, image=u)
                )
                continue
            except Exception as exc:  # noqa: BLE001 — provider rejection triggers the fallback
                self.logger.warning("WhatsApp rejected image URL %s (%s); downloading", url, exc)
            try:
                async with temp_download(url, allowed_hosts=allowed_media_hosts()) as path:
                    await loop.run_in_executor(
                        _executor, lambda p=path: client.send_image(to=to, image=str(p))
                    )
            except MediaDownloadRefused as exc:
                self.logger.warning("Refused image URL %s: %s", url, exc)
            except Exception as exc:  # noqa: BLE001
                self.logger.error("Failed to send image URL to %s: %s", to, exc)
        # FILL IN: parsed.media_urls → send as a text message with the links (client.send_message) — bounded by spec §3 M12

```
**Why**: direct-then-fallback order is fixed by spec §3 M12; `loop`, `client`, `to` are already bound in the method.

### `packages/ai-parrot-integrations/tests/test_media_urls_whatsapp.py` (CREATE)
```python
"""FEAT-601 M12 — WhatsApp URL images: direct send, download fallback (TASK-3719)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("pywa")

from parrot.integrations.parser import ParsedResponse  # noqa: E402
from parrot.integrations.whatsapp.wrapper import WhatsAppAgentWrapper  # noqa: E402


def _wrapper() -> WhatsAppAgentWrapper:
    w = WhatsAppAgentWrapper.__new__(WhatsAppAgentWrapper)
    w.logger = MagicMock()
    # FILL IN: w.config with max_message_length if the text path is exercised (verify attribute use in the method)
    return w


async def test_whatsapp_direct_url_then_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """send_image(image=url) succeeds ⇒ no download; provider error ⇒ download path sends a local file."""
    # FILL IN: client = MagicMock(); first case send_image ok; second case side_effect=[Exception, None] and
    #          patch temp_download in the wrapper module with a fake CM; assert second call image is a local path


async def test_whatsapp_refused_fallback_is_logged() -> None:
    # FILL IN: provider error + MediaDownloadRefused ⇒ logger.warning, no exception
    pass
```

### FILL IN checklist
- [ ] `media_urls` link message — spec §3 M12
- [ ] test harness attributes verified against the method body

---

## Acceptance Criteria

- [ ] `image_urls` sent directly via `client.send_image(to=…, image=url)`; provider error ⇒ bounded download fallback
- [ ] Refused fallback logged, never raised; Path/charts/documents loops unchanged
- [ ] `ruff check packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/wrapper.py` clean
- [ ] Bridge-wrapper drift recorded in the Completion Note
- [ ] All tests pass (see Validation Commands)

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/test_media_urls_whatsapp.py -q`

---

## Test Specification

| Test | Description |
|---|---|
| `test_whatsapp_direct_url_then_fallback` | spec §4 M12: `send_image(image=url)`; provider error ⇒ download path |
| `test_whatsapp_refused_fallback_is_logged` | refused download logged, no crash |

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
