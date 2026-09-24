# TASK-3716: ParsedResponse URL lists + bounded download_to_temp (M12)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3715
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 12 (U1). `parse_response` is the single seam every channel wrapper goes through; today it
keeps an image/media entry only when `path.exists()` (parser.py:519-535), so a presigned URL would be
dropped. This task (a) adds `image_urls` / `media_urls` to `ParsedResponse`, carried **separately** from
the `Path` lists and never routed through `exists()`/`Path()`, and (b) creates
`integrations/media_download.py`, the bounded downloader Telegram (TASK-3718) and the WhatsApp fallback
(TASK-3719) use. Implements AC14 (parser + download half). Depends on TASK-3715 because `parse_response`
reads `AIMessage.image_urls` / `media_urls` added there and the tests construct `AIMessage` with them.

---

## Scope

- Add `image_urls: List[str]` and `media_urls: List[str]` dataclass fields to `ParsedResponse` after `media`.
- In `parse_response`, before `# Extract images`, copy `response.image_urls` / `response.media_urls` (and,
  for an `AgentResponse`, `response.response.image_urls` / `media_urls`) into the new lists: strings only,
  http(s) only, dedup, order preserved; **no** `exists()`, **no** `Path()` coercion.
- Create `media_download.py` with `download_to_temp(...)`, an async context-manager variant
  `temp_download(...)` that removes the file on exit, `allowed_media_hosts()` reading
  `PARROT_MEDIA_URL_HOSTS`, and `MediaDownloadRefused`.
- Tests: `test_parse_response_keeps_urls_and_paths` + downloader tests (allowlist, redirect to foreign
  host, oversize, timeout, cleanup).

**NOT in scope**: any wrapper change (TASK-3717/3718/3719); `AIMessage` fields (TASK-3715); signing URLs
(TASK-3705/3723).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/parser.py` | MODIFY | `ParsedResponse.image_urls/media_urls`; copy URLs in `parse_response` |
| `packages/ai-parrot-integrations/src/parrot/integrations/media_download.py` | CREATE | Bounded aiohttp downloader with host allowlist + redirect validation |
| `packages/ai-parrot-integrations/tests/test_media_urls.py` | CREATE | Parser URL tests |
| `packages/ai-parrot-integrations/tests/test_media_download.py` | CREATE | Downloader tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from dataclasses import dataclass, field                  # verified: integrations/parser.py:7
from pathlib import Path                                  # verified: parser.py:8
from typing import Any, List, Optional                    # verified: parser.py:9
from parrot.integrations.parser import parse_response, ParsedResponse, ChartData   # verified: parser.py:392, 83, 21
from parrot.models.responses import AIMessage, AgentResponse                     # verified: models/responses.py:75, 1081 (+ image_urls/media_urls from TASK-3715)
import aiohttp                                            # verified: used by integrations/msteams/wrapper.py:16
from urllib.parse import urlsplit                          # stdlib — host/scheme parsing in media_download.py
import contextlib, os, tempfile                           # stdlib
from aiohttp import web                                   # verified: msteams/wrapper.py:17
from aiohttp.test_utils import TestClient, TestServer     # verified: tests/integrations/telegram/test_oauth2_callback.py:5 (test-only)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/parser.py
@dataclass
class ParsedResponse:                                     # line 83
    text: str = ""                                        # line 87
    images: List[Path] = field(default_factory=list)      # line 90
    documents: List[Path] = field(default_factory=list)   # line 91
    media: List[Path] = field(default_factory=list)  # Videos, audio   # line 92
    charts: List[ChartData] = field(default_factory=list) # line 95

def parse_response(response: Any) -> ParsedResponse:      # line 392; str/None short-circuit at 407-415
    # "# Extract images" block at 519-525 keeps only existing paths; media 527-537; files 539-551;
    # documents 553-566 (data: strings pass through at 556-557); charts helper at 568-570
```

### Does NOT Exist
- ~~`ParsedResponse.image_urls` / `media_urls`~~ — added here.
- ~~URL pass-through in `parse_response`~~ — every media entry goes through `path.exists()` (spec F019).
- ~~`parrot.integrations.media_download`, `download_to_temp`, `PARROT_MEDIA_URL_HOSTS`~~ — all new (grep: 0 hits).
- ~~`requests` / `httpx`~~ — forbidden; aiohttp only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/parser.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/media_download.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/test_media_urls.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/test_media_download.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/parser.py#ParsedResponse",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/parser.py#parse_response",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AgentResponse"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`ChartData.public_url` (parser.py:21-38) is the existing URL-media precedent; the new lists generalise it.
Test server pattern: `async with TestClient(TestServer(app)) as c:` (tests/integrations/telegram/test_oauth2_callback.py:21).

### Key Constraints
- Worktree tests: the shared `.venv` is editable-installed against the main checkout, so run tests with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest <file> -q`.
- No new third-party dependency (spec G8, AC18).
- Google-style docstrings and strict type hints on every function/class; Pydantic v2; `self.logger` / module
  `logging.getLogger(__name__)` — never `print`.
- HTTP is `aiohttp` only — never `requests` / `httpx` (ruff TID251 fails the merge gate).
- Existing `Path` attachment behaviour (`images` / `media` / `files` / `documents`) must stay byte-for-byte
  unchanged (AC14) — URL handling is strictly additive.
- `download_to_temp` follows redirects **manually** (`allow_redirects=False`, max 3 hops) and validates the
  host of every hop against `allowed_hosts` before requesting it; a foreign hop ⇒ `MediaDownloadRefused`.
- Stream the body in chunks and abort as soon as `max_bytes` is exceeded (also reject an oversize
  `Content-Length` up front); `aiohttp.ClientTimeout(total=timeout_s)`. On any failure remove the partial file.
- Host matching is exact on `URL.host` (lower-cased); an empty allowlist refuses everything (default deny).
- `allowed_media_hosts()` parses the comma-separated `PARROT_MEDIA_URL_HOSTS` env var (via `os.environ`),
  stripping blanks; callers pass the result as `allowed_hosts`.
- The URL copy in `parse_response` must run for `AIMessage` **and** `AgentResponse` (read both
  `response.image_urls` and `getattr(response, "response", None).image_urls`), because Slack/WhatsApp/Telegram
  hand whatever `agent.ask()` returned to `parse_response`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the two dataclass fields after `media` — *why*: spec §3 M12 fixes them as separate lists so Path semantics stay intact.
2. Insert the URL-copy block above `# Extract images` — *why*: it must run before (and independent of) the `exists()` filters.
3. Create `media_download.py` — *why*: Telegram needs a local file for `send_photo(FSInputFile)` and WhatsApp needs a fallback; one bounded implementation serves both.
4. Write the two test modules — *why*: AC14 names parser URL survival and download caps/cleanup explicitly.

### `packages/ai-parrot-integrations/src/parrot/integrations/parser.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'media: List[Path] = field(default_factory=list)  # Videos, audio' packages/ai-parrot-integrations/src/parrot/integrations/parser.py)
# AFTER — insert below `    media: List[Path] = field(default_factory=list)  # Videos, audio` (verified: parser.py:92)
    # Remote http(s) media (presigned figures, video deep links) — never Path-coerced (FEAT-601 M12)
    image_urls: List[str] = field(default_factory=list)
    media_urls: List[str] = field(default_factory=list)
```
```python
# occurrences: 1 (verified: grep -cF '# Extract images' .../parser.py)
# BEFORE — insert above `    # Extract images` (verified: parser.py:519)
    # Extract remote URL media (FEAT-601 M12) — no exists() check, no Path() coercion
    _collect_url_media(response, parsed)
    inner = getattr(response, 'response', None)
    if inner is not None and not isinstance(inner, str):
        _collect_url_media(inner, parsed)
```
```python
# AFTER — new module-level helper, insert directly above `def parse_response(response: Any) -> ParsedResponse:` (occurrences: 1, verified: parser.py:392)
def _collect_url_media(source: Any, parsed: ParsedResponse) -> None:
    """Copy ``image_urls`` / ``media_urls`` from ``source`` into ``parsed``.

    Args:
        source: An AIMessage/AgentResponse-like object (attributes optional).
        parsed: The ParsedResponse being built; mutated in place.
    """
    for attr, target in (("image_urls", parsed.image_urls), ("media_urls", parsed.media_urls)):
        # FILL IN: iterate getattr(source, attr, None) or []; keep str items starting with http:// or https://,
        #          dedup preserving order — bounded by AC14 (never touch parsed.images/media)
        pass
```
**Why**: separate lists + a helper keep the existing Path code untouched byte-for-byte (AC14).

### `packages/ai-parrot-integrations/src/parrot/integrations/media_download.py` (CREATE)
```python
"""Bounded download of remote media URLs to temp files (FEAT-601 M12).

Used by channels that cannot send a remote URL directly (Telegram ``send_photo``) and as the WhatsApp
fallback. Default deny: only hosts in the allowlist are fetched, on every redirect hop.
"""
from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import AsyncIterator, Sequence

import aiohttp

logger = logging.getLogger(__name__)

MEDIA_HOSTS_ENV = "PARROT_MEDIA_URL_HOSTS"
MAX_REDIRECTS = 3


class MediaDownloadRefused(ValueError):
    """Raised when a URL, redirect hop, size or timeout violates the download policy."""


def allowed_media_hosts() -> tuple[str, ...]:
    """Return the lower-cased host allowlist from ``PARROT_MEDIA_URL_HOSTS`` (comma-separated)."""
    raw = os.environ.get(MEDIA_HOSTS_ENV, "")
    return tuple(h.strip().lower() for h in raw.split(",") if h.strip())


def _check_host(url: str, allowed_hosts: Sequence[str]) -> None:
    """Raise :class:`MediaDownloadRefused` unless ``url`` is http(s) and its host is allowlisted."""
    # FILL IN: parse with urllib.parse.urlsplit (stdlib; add `from urllib.parse import urlsplit`) — scheme in {http, https}, host.lower() in allowed_hosts;
    #          empty allowlist ⇒ refuse — bounded by spec §7 "Downloads" (never follow to non-allowlisted hosts)


async def download_to_temp(
    url: str,
    *,
    allowed_hosts: Sequence[str],
    max_bytes: int = 10 * 1024 * 1024,
    timeout_s: float = 15.0,
) -> Path:
    """Download ``url`` to a new temp file and return its path; the caller removes it.

    Args:
        url: Absolute http(s) URL.
        allowed_hosts: Hosts permitted for the initial request and every redirect hop.
        max_bytes: Hard cap on the body size.
        timeout_s: Total request timeout in seconds.

    Returns:
        Path of the downloaded temp file (suffix guessed from the URL path).

    Raises:
        MediaDownloadRefused: Foreign host, too many redirects, oversize body, non-2xx or timeout.
    """
    _check_host(url, allowed_hosts)
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    # FILL IN: aiohttp.ClientSession(timeout=timeout); loop up to MAX_REDIRECTS with allow_redirects=False,
    #          validating each Location via _check_host; reject Content-Length > max_bytes; stream
    #          resp.content.iter_chunked(65536) into tempfile.NamedTemporaryFile(delete=False), abort on overflow;
    #          wrap asyncio.TimeoutError/aiohttp.ClientError as MediaDownloadRefused; unlink partial file on any
    #          failure — bounded by spec §7 (10 MB / 15 s caps, cleanup)
    raise MediaDownloadRefused(url)


@contextlib.asynccontextmanager
async def temp_download(url: str, **kwargs: object) -> AsyncIterator[Path]:
    """Async context manager around :func:`download_to_temp` that always removes the file on exit."""
    path = await download_to_temp(url, **kwargs)  # type: ignore[arg-type]
    try:
        yield path
    finally:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
```
**Why**: signature fixed by spec §3 M12 skeleton; `temp_download` is the "context manager variant" the spec
promises; module is aiohttp-only per codebase conventions.

### `packages/ai-parrot-integrations/tests/test_media_urls.py` (CREATE)
```python
"""FEAT-601 M12 — parse_response carries URL media separately (TASK-3716)."""
from __future__ import annotations

from pathlib import Path

from parrot.integrations.parser import parse_response
from parrot.models.responses import AIMessage, AgentResponse


def test_parse_response_keeps_urls_and_paths(tmp_path: Path) -> None:
    """URLs survive; an existing Path is kept in images; a missing Path is still dropped."""
    # FILL IN: real = tmp_path/"a.png" (write bytes); AIMessage(images=[real, tmp_path/"missing.png"],
    #          image_urls=["https://h/f.png"], media_urls=["https://h/v.mp4"]) → parsed.images == [real],
    #          parsed.image_urls == [...], parsed.media_urls == [...]


def test_parse_response_agent_response_roundtrip() -> None:
    """AgentResponse wrapping an AIMessage exposes the URLs once (sync_documents_and_paths + inner copy dedup)."""
    # FILL IN


def test_parse_response_plain_string_has_no_urls() -> None:
    assert parse_response("hi").image_urls == []
```

### `packages/ai-parrot-integrations/tests/test_media_download.py` (CREATE)
```python
"""FEAT-601 M12 — bounded media download (TASK-3716)."""
from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from parrot.integrations.media_download import MediaDownloadRefused, download_to_temp, temp_download


def _app() -> web.Application:
    # FILL IN: routes /ok (small png bytes), /big (> max_bytes), /redir-foreign (302 to http://evil.example/x),
    #          /redir-local (302 to /ok), /slow (sleep > timeout)
    return web.Application()


async def test_allowlisted_host_downloads_and_cleans_up() -> None:
    # FILL IN: TestServer(_app()); allowed_hosts=[server.host]; temp_download → file exists inside, gone after


async def test_foreign_host_and_redirect_refused() -> None:
    # FILL IN: initial foreign host refused without a request; /redir-foreign refused; /redir-local ok


async def test_oversize_and_timeout_refused_without_leftovers() -> None:
    # FILL IN: max_bytes small ⇒ MediaDownloadRefused; timeout_s tiny on /slow ⇒ refused; no temp file left
    pass
```

### FILL IN checklist
- [ ] `parser.py::_collect_url_media` — http(s) filter + dedup; bounded by AC14
- [ ] `media_download.py::_check_host` — scheme + allowlist; default deny
- [ ] `media_download.py::download_to_temp` — manual redirects, caps, cleanup; bounded by spec §7
- [ ] test bodies (both modules)

---

## Acceptance Criteria

- [ ] `ParsedResponse` has `image_urls` / `media_urls`; `parse_response` fills them for `AIMessage` and `AgentResponse`
- [ ] Non-existent Paths are still dropped; existing Path logic unchanged (diff limited to the new field lines, helper and call block)
- [ ] `download_to_temp` refuses foreign hosts (initial and redirect), oversize bodies and timeouts, and leaves no temp file behind
- [ ] `ruff check` clean on both source files; no `requests`/`httpx`
- [ ] All tests pass (see Validation Commands)

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/test_media_urls.py -q`
- `pytest packages/ai-parrot-integrations/tests/test_media_download.py -q`

---

## Test Specification

| Test | Description |
|---|---|
| `test_parse_response_keeps_urls_and_paths` | spec §4 M12: URL lists survive; non-existent Paths still dropped; `AgentResponse` round-trip |
| `test_parse_response_agent_response_roundtrip` | inner `AIMessage` URLs copied once |
| `test_allowlisted_host_downloads_and_cleans_up` | allowlisted host ⇒ temp file; removed by `temp_download` |
| `test_foreign_host_and_redirect_refused` | foreign host / foreign redirect ⇒ `MediaDownloadRefused` |
| `test_oversize_and_timeout_refused_without_leftovers` | caps enforced, cleanup verified |

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
