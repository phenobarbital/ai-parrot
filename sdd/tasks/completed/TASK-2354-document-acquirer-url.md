# TASK-2354: `DocumentAcquirer` — URL acquisition over aiohttp

**Feature**: FEAT-451 — `wikitoolkit ingest` — Binary Documents, URLs, and Metadata Frontmatter
**Spec**: `sdd/specs/wikitoolkit-ingest-documents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2353
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of the spec (§3). Completes the `is_url` branch that
TASK-2353 left stubbed, so `wikitoolkit ingest https://host/doc.pdf` works.

A URL is fetched to a temp file and then dispatched through the *same* two
branches TASK-2353 built — there is no separate extraction path for remote
documents. The only URL-specific concerns are the fetch itself, the suffix
resolution (a URL may not end in `.pdf`), the safety caps, and temp-file
cleanup.

---

## Scope

- ADD `_acquire_url(self, ref: DocumentRef) -> AcquiredDocument` to
  `DocumentAcquirer` and wire it into `acquire()`.
- Fetch with **aiohttp**:
  - `aiohttp.ClientSession` with `ClientTimeout(total=self._fetch_timeout)`.
  - Reject any scheme other than `http` / `https` with
    `DocumentAcquisitionError` — including after a redirect.
  - Stream the body to a `NamedTemporaryFile`, aborting with
    `DocumentAcquisitionError` once `self._max_bytes` is exceeded. Do **not**
    trust `Content-Length` alone; count what you actually read.
  - Non-2xx status → `DocumentAcquisitionError` naming the status.
- Resolve the suffix in this order: the `Content-Type` header mapped via
  `mimetypes.guess_extension`, then the URL path's own suffix, then `""`.
  Name the temp file with that suffix so `get_loader_class` dispatches
  correctly.
- After the fetch, delegate to the existing local branches with a
  `DocumentRef` pointing at the temp file, then:
  - set `metadata.source_url` to the **original URL**;
  - leave `AcquiredDocument.ref` as the original URL ref, so downstream code
    records the URL and not a temp path that will not exist.
- Remove the temp file in a `finally`, including on error.
- Extend `tests/knowledge/wiki/test_documents.py` with aiohttp mocked.

**NOT in scope**: link following / crawling (explicit spec Non-Goal); caching
downloads (deferred, spec §8); authentication headers; any edit to `cli.py`
(TASK-2357) or `ingest.py` (TASK-2356).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py` | MODIFY | Add `_acquire_url` |
| `tests/knowledge/wiki/test_documents.py` | MODIFY | Append URL tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import mimetypes
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import aiohttp   # existing core dep of ai-parrot
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py  (TASK-2351/2353)
class DocumentRef(BaseModel):
    uri: str
    is_url: bool = False
    suffix: str = ""

class DocumentAcquirer:
    def __init__(self, *, fetch_timeout: float = 30.0,
                 max_bytes: int = 100 * 1024 * 1024,
                 cache_dir: Path | None = None) -> None: ...
    async def acquire(self, ref: DocumentRef) -> AcquiredDocument: ...
    async def _acquire_plaintext(self, ref, path) -> AcquiredDocument: ...
    async def _acquire_via_loader(self, ref, path) -> AcquiredDocument: ...

class DocumentAcquisitionError(Exception): ...
```

### Does NOT Exist

- ~~`requests` / `httpx`~~ — **banned by CLAUDE.md** ("Never use `requests` or
  `httpx` — use `aiohttp`"). Neither is a dependency of `ai-parrot`.
- ~~`MarkdownLoader.load_url()` / `AbstractLoader.fetch()`~~ — not real.
  `AbstractLoader.from_url` (abstract.py:507) only wraps `_load(item)` in
  `asyncio.Task`s; it does no HTTP of its own. Fetch it yourself.
- ~~MarkItDown URL handling~~ — `MarkdownLoader.convert_to_markdown` calls
  `self.md_converter.convert(str(path))` (markdown.py:565) with a **path**.
  MarkItDown's own URI handling is not exercised anywhere in this repo — do
  not rely on it.
- ~~`SourceCollectionManager.add_source(<url>)`~~ — `add_source` takes a
  `Path` and calls `path.stat()` (sources.py:190, 200); passing a URL raises
  `FileNotFoundError`. That concern belongs to TASK-2355/2356, but do not
  design around the assumption that it works.
- ~~`aiohttp.ClientSession.get(..., timeout=<float>)`~~ — pass an
  `aiohttp.ClientTimeout` instance, not a bare float.

---

## Implementation Notes

### Pattern to Follow

```python
async def _acquire_url(self, ref: DocumentRef) -> AcquiredDocument:
    parsed = urlparse(ref.uri)
    if parsed.scheme not in ("http", "https"):
        raise DocumentAcquisitionError(
            f"Unsupported URL scheme {parsed.scheme!r}: {ref.uri}"
        )
    tmp_path: Path | None = None
    try:
        tmp_path, suffix = await self._download(ref.uri)
        local = DocumentRef(uri=str(tmp_path), is_url=False, suffix=suffix)
        acquired = await self.acquire(local)
        acquired.metadata.source_url = ref.uri
        acquired.ref = ref            # record the URL, not the temp path
        return acquired
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
```

> **Contract correction (verified 2026-08-23, at TASK-2354 pickup)**: TASK-2353's
> actual, committed `DocumentAcquirer.__init__` stores its constructor args as
> **public** attributes — `self.fetch_timeout`, `self.max_bytes`,
> `self.cache_dir` (documents.py:477-479) — not the private
> `self._fetch_timeout` / `self._max_bytes` spelling used in the pattern
> snippet above. Use the public spelling (`self.fetch_timeout`,
> `self.max_bytes`) when implementing `_acquire_url` / `_download`.

### Key Constraints

- **SSRF surface.** This is an operator-run CLI, not a server endpoint, so do
  not over-engineer — but do not omit the caps either: http(s) only (checked
  again after redirects), an explicit total timeout, and a hard byte cap
  enforced on bytes actually read.
- **Temp-file lifetime**: always `finally`-cleaned, including on
  `DocumentAcquisitionError` raised from the inner `acquire()`.
- Use `tempfile.NamedTemporaryFile(delete=False, suffix=<resolved suffix>)`
  and close it before handing the path to a loader — MarkItDown opens the path
  itself, and an open handle breaks on some platforms.
- Stream in chunks (`resp.content.iter_chunked(...)`); never
  `await resp.read()` into memory for a 100 MB cap.
- Write the file with `asyncio.to_thread` or an async-friendly loop — do not
  block the event loop on a large write.
- One `ClientSession` per `_acquire_url` call is acceptable here (the CLI
  fetches a handful of URLs, not thousands). Do not build a session pool.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py` — the local branches to delegate to (TASK-2353).
- CLAUDE.md / `.agent/CONTEXT.md` "What NOT to Do" — the `aiohttp`-only rule.

---

## Acceptance Criteria

- [ ] `wikitoolkit`-level: `DocumentAcquirer().acquire(DocumentRef(uri="https://…", is_url=True))`
      returns an `AcquiredDocument` whose `metadata.source_url` is the original URL.
- [ ] `AcquiredDocument.ref.uri` is the **URL**, not the temp path.
- [ ] The suffix is taken from `Content-Type` when present, else the URL path.
- [ ] A `ftp://` or `file://` URL raises `DocumentAcquisitionError`.
- [ ] A non-2xx response raises `DocumentAcquisitionError` naming the status.
- [ ] A response exceeding `max_bytes` raises `DocumentAcquisitionError`.
- [ ] A fetch timeout raises `DocumentAcquisitionError`.
- [ ] **No temp file remains** after success, after error, and after timeout
      (asserted by listing the temp dir).
- [ ] `grep -rn "requests\|httpx" packages/ai-parrot/src/parrot/knowledge/wiki/documents.py`
      returns nothing.
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_documents.py -v`
- [ ] `ruff check` and `mypy` clean.

---

## Test Specification

```python
# tests/knowledge/wiki/test_documents.py  (append)
import pytest

from parrot.knowledge.wiki.documents import (
    DocumentAcquirer, DocumentAcquisitionError, DocumentRef,
)


class TestAcquireUrl:
    async def test_fetch_sets_source_url(self, mock_aiohttp_pdf):
        ref = DocumentRef(uri="https://example.test/doc.pdf", is_url=True, suffix=".pdf")
        doc = await DocumentAcquirer().acquire(ref)
        assert doc.metadata.source_url == "https://example.test/doc.pdf"
        assert doc.ref.uri == "https://example.test/doc.pdf"

    async def test_suffix_from_content_type(self, mock_aiohttp_pdf_no_extension):
        """URL path has no extension; Content-Type: application/pdf decides."""
        ref = DocumentRef(uri="https://example.test/download", is_url=True, suffix="")
        doc = await DocumentAcquirer().acquire(ref)
        assert doc.metadata.content_type == "application/pdf"

    @pytest.mark.parametrize("url", ["ftp://h/a.pdf", "file:///etc/passwd"])
    async def test_rejects_non_http_scheme(self, url):
        ref = DocumentRef(uri=url, is_url=True, suffix=".pdf")
        with pytest.raises(DocumentAcquisitionError):
            await DocumentAcquirer().acquire(ref)

    async def test_non_2xx_raises(self, mock_aiohttp_404):
        ref = DocumentRef(uri="https://example.test/missing.pdf", is_url=True, suffix=".pdf")
        with pytest.raises(DocumentAcquisitionError, match="404"):
            await DocumentAcquirer().acquire(ref)

    async def test_size_cap(self, mock_aiohttp_huge):
        ref = DocumentRef(uri="https://example.test/big.pdf", is_url=True, suffix=".pdf")
        with pytest.raises(DocumentAcquisitionError):
            await DocumentAcquirer(max_bytes=1024).acquire(ref)

    async def test_timeout(self, mock_aiohttp_timeout):
        ref = DocumentRef(uri="https://example.test/slow.pdf", is_url=True, suffix=".pdf")
        with pytest.raises(DocumentAcquisitionError):
            await DocumentAcquirer(fetch_timeout=0.01).acquire(ref)

    async def test_no_temp_file_leaks(self, tmp_path, monkeypatch, mock_aiohttp_404):
        """Temp dir is empty after a failed fetch."""
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        ref = DocumentRef(uri="https://example.test/missing.pdf", is_url=True, suffix=".pdf")
        with pytest.raises(DocumentAcquisitionError):
            await DocumentAcquirer().acquire(ref)
        assert list(tmp_path.iterdir()) == []
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 3, §7 "URL security").
2. **Check dependencies** — TASK-2353 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm `DocumentAcquirer`'s local
   branches are named as listed before delegating to them.
4. **Update status** in `sdd/tasks/index/wikitoolkit-ingest-documents.json` → `"in-progress"`.
5. **Implement** following the scope and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-2354-document-acquirer-url.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude session 2026-08-23)
**Date**: 2026-08-23
**Notes**: Implemented `_acquire_url` + `_download` + module-level
`_resolve_url_suffix` in `documents.py`. `_download` streams via
`aiohttp.ClientSession`/`ClientTimeout`, checks the scheme both up-front
and again on the post-redirect `resp.url`, caps on bytes actually read
(never trusting `Content-Length`), and always cleans up its temp file on
any failure path (tracked via a `success` flag in a `finally`).
`_acquire_url` delegates the downloaded temp file back through
`self.acquire()` (the same local branches TASK-2353 built), then restores
`ref`/`metadata.source_url` to the original URL and unlinks the temp file
in `finally`. No `aioresponses`-style dependency is installed in this
repo, so aiohttp is mocked with a hand-rolled async-context-manager double
(`_FakeClientSession`/`_FakeResponse`/`_FakeGetContextManager`), matching
the existing precedent in `tests/tools/gigsmart/test_client.py`. Added one
extra test beyond the task's Test Specification —
`test_no_temp_file_leaks_on_size_cap` — that exercises real mid-download
cleanup via `cache_dir=tmp_path` (the literal `test_no_temp_file_leaks`
test never actually creates a temp file, since its 404 status short-
circuits before temp-file creation). All 37 tests in
`tests/knowledge/wiki/test_documents.py` pass (9 new); `ruff check` clean;
`mypy` targeted at `documents.py` reports zero errors in that file (the
whole-repo follow-imports run surfaces ~2494 pre-existing errors across
182 unrelated files, none in `documents.py`).

**Deviations from spec**: Contract correction — the task's `_acquire_url`
pattern snippet referenced private `self._fetch_timeout`/`self._max_bytes`
attribute names, but TASK-2353's actual, committed `DocumentAcquirer.
__init__` stores them as public `self.fetch_timeout`/`self.max_bytes`
(documents.py, TASK-2353 commit). Updated the contract note in this task
file before implementing and used the public spelling throughout.
