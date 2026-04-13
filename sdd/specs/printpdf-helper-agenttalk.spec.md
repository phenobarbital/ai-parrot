# Feature Specification: Print-to-PDF Helper for AgentTalk

**Feature ID**: FEAT-097
**Date**: 2026-04-13
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot agents produce rich HTML outputs (infographics, reports, dashboards) but
there is no built-in HTTP endpoint to convert arbitrary HTML into a downloadable PDF.
Users currently need external tools or browser print dialogs to obtain PDF versions
of agent-generated content.

The `PDFPrintTool` already exists for agent-internal use, but it is not exposed as a
standalone HTTP utility. A simple `POST /api/v1/utilities/print2pdf` endpoint would
let any frontend or integration convert an HTML body to PDF in a single request.

### Goals

- Expose a new `POST /api/v1/utilities/print2pdf` endpoint that accepts an HTML body
  and returns a PDF binary response.
- Reuse the existing `weasyprint` infrastructure from `PDFPrintTool`.
- Keep the handler thin — HTML-in, PDF-out — no agent or LLM involvement.
- Support content-disposition control (inline preview vs. attachment download).

### Non-Goals (explicitly out of scope)

- URL-to-PDF (fetching a remote URL and converting it) — future feature.
- Markdown-to-PDF conversion at this endpoint (callers must send HTML).
- Template rendering — the endpoint receives ready-to-print HTML.
- Authentication/authorization changes — reuse existing `@is_authenticated` decorator.

---

## 2. Architectural Design

### Overview

A new `PrintPDFHandler` (subclass of `BaseView`) handles `POST` requests. It reads
the HTML body, converts it to PDF via `weasyprint`, and streams the result back as
`application/pdf` using aiohttp's `web.Response` with the PDF bytes.

### Component Diagram

```
Client (browser / frontend)
    │
    │  POST /api/v1/utilities/print2pdf
    │  Content-Type: text/html  (or application/json with {"html": "..."})
    │  Body: <html>...</html>
    │
    ▼
PrintPDFHandler (BaseView)
    │
    │  1. Extract HTML from request body
    │  2. Convert HTML → PDF via weasyprint
    │  3. Return web.Response(body=pdf_bytes, content_type="application/pdf")
    │
    ▼
weasyprint.HTML(string=html).write_pdf()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator.views.BaseView` | extends | Handler base class |
| `weasyprint` | uses | HTML-to-PDF rendering engine |
| `parrot._imports.lazy_import` | uses | Lazy weasyprint import with clear error |
| `BotManager.setup_routes()` | registers | New route added here |

### Data Models

```python
# No new Pydantic models required.
# Request: raw HTML body (Content-Type: text/html)
#      or: JSON body {"html": "<html>...", "filename": "report.pdf", "disposition": "attachment"}
# Response: binary PDF (Content-Type: application/pdf)
```

### New Public Interfaces

```python
# parrot/handlers/print_pdf.py
class PrintPDFHandler(BaseView):
    """Converts HTML to PDF and returns the PDF as a binary response."""

    async def post(self) -> web.Response:
        """Accept HTML body, return PDF binary."""
        ...
```

---

## 3. Module Breakdown

### Module 1: PrintPDFHandler

- **Path**: `packages/ai-parrot/src/parrot/handlers/print_pdf.py`
- **Responsibility**: HTTP handler that receives HTML, converts to PDF via weasyprint,
  and returns the PDF as a binary `web.Response`.
- **Depends on**: `navigator.views.BaseView`, `weasyprint` (lazy-imported)

**Details**:

- Accept two content types:
  - `text/html`: raw HTML body is the content to convert.
  - `application/json`: JSON body with `html` (required), `filename` (optional,
    default `"document.pdf"`), `disposition` (optional, `"inline"` or `"attachment"`,
    default `"attachment"`).
- Run `weasyprint.HTML(string=html).write_pdf()` in a thread executor to avoid
  blocking the event loop (weasyprint is CPU-bound/synchronous).
- Return `web.Response(body=pdf_bytes, content_type="application/pdf")` with
  `Content-Disposition` header.
- On error (empty body, weasyprint failure), return `self.error(...)` with
  appropriate HTTP status.

### Module 2: Route Registration

- **Path**: `packages/ai-parrot/src/parrot/manager/manager.py` (edit existing)
- **Responsibility**: Register the new `/api/v1/utilities/print2pdf` route.
- **Depends on**: Module 1

**Details**:

- Import `PrintPDFHandler` at the top of `manager.py`.
- Add `router.add_view('/api/v1/utilities/print2pdf', PrintPDFHandler)` in
  `setup_routes()`.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_post_html_body_returns_pdf` | Module 1 | POST with `text/html` body returns `application/pdf` |
| `test_post_json_body_returns_pdf` | Module 1 | POST with JSON `{"html": "..."}` returns PDF |
| `test_custom_filename` | Module 1 | JSON body with `filename` sets Content-Disposition |
| `test_inline_disposition` | Module 1 | `disposition: "inline"` sets inline Content-Disposition |
| `test_empty_body_returns_400` | Module 1 | Empty or missing HTML returns 400 error |
| `test_invalid_html_still_produces_pdf` | Module 1 | Malformed HTML doesn't crash (weasyprint is lenient) |

### Integration Tests

| Test | Description |
|---|---|
| `test_print2pdf_endpoint_e2e` | Full HTTP round-trip: POST HTML, verify PDF magic bytes |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_html():
    return """<!DOCTYPE html>
<html><head><title>Test</title></head>
<body><h1>Hello PDF</h1><p>Test content.</p></body>
</html>"""

@pytest.fixture
def minimal_html():
    return "<h1>Minimal</h1>"
```

---

## 5. Acceptance Criteria

- [x] `POST /api/v1/utilities/print2pdf` with HTML body returns a valid PDF
- [x] Supports both `text/html` and `application/json` content types
- [x] PDF response has correct `Content-Type: application/pdf` header
- [x] `Content-Disposition` header defaults to `attachment; filename="document.pdf"`
- [x] Custom filename supported via JSON body
- [x] Empty body returns HTTP 400 with error message
- [x] weasyprint runs off the event loop (thread executor)
- [x] No breaking changes to existing routes or handlers
- [x] Unit tests pass

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
from navigator.views import BaseView  # verified: packages/ai-parrot/src/parrot/handlers/agent.py:31
from navigator_auth.decorators import is_authenticated, user_session  # verified: agent.py:22
from aiohttp import web  # verified: agent.py:16
from navconfig.logging import logging  # verified: agent.py:20
from parrot._imports import lazy_import  # verified: packages/ai-parrot-tools/src/parrot_tools/pdfprint.py:16
```

### Existing Class Signatures

```python
# navigator.views.BaseView (external — navigator framework)
# Used by: AgentTalk, InfographicTalk, ChatHandler, etc.
class BaseView:
    request: web.Request  # aiohttp request object
    def json_response(self, data, ...) -> web.Response: ...
    def error(self, msg: str, status: int = 400, ...) -> web.Response: ...
    def _negotiate_accept(self) -> str: ...  # content negotiation helper

# parrot._imports.lazy_import  (packages/ai-parrot/src/parrot/_imports.py:24-80)
def lazy_import(module_name: str, extra: str = "") -> ModuleType: ...
# Usage: weasyprint = lazy_import("weasyprint", extra="pdf")

# weasyprint (external library, pinned ==68.0 in pyproject.toml:119)
class HTML:
    def __init__(self, string: str = None, url: str = None, base_url: str = None): ...
    def write_pdf(self, target: str = None, stylesheets=None, presentational_hints: bool = False) -> bytes: ...
    # When target=None, returns bytes directly
```

### Existing Patterns — Binary Response

```python
# Pattern from google_generation.py:157-169 — StreamResponse for binary
stream = web.StreamResponse(
    status=200,
    headers={
        "Content-Type": content_type,
        "Content-Disposition": f'inline; filename="{file_path.name}"',
    },
)
await stream.prepare(self.request)

# Simpler pattern for in-memory bytes (preferred for PDF):
return web.Response(
    body=pdf_bytes,
    content_type="application/pdf",
    headers={"Content-Disposition": f'attachment; filename="{filename}"'},
)
```

### Route Registration Pattern

```python
# packages/ai-parrot/src/parrot/manager/manager.py:704+
router = self.app.router
router.add_view('/api/v1/agents/chat/{agent_id}', AgentTalk)  # line 720
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PrintPDFHandler` | `BaseView` | inheritance | `handlers/agent.py:31,47` |
| `PrintPDFHandler` | `weasyprint.HTML` | method call | `parrot_tools/pdfprint.py:892-895` |
| `setup_routes()` | `PrintPDFHandler` | `router.add_view()` | `manager/manager.py:704` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.handlers.utilities`~~ — no utilities handler module exists
- ~~`parrot.utils.pdf`~~ — no PDF utility module in parrot core
- ~~`BaseView.stream_response()`~~ — not a BaseView method; use `web.StreamResponse` directly
- ~~`BaseView.file_response()`~~ — not a BaseView method; use `web.Response(body=...)` or `web.FileResponse`
- ~~`PDFPrintTool.html_to_pdf()`~~ — no such method; the tool's `_execute()` takes markdown/text, not raw HTML
- ~~`parrot.handlers.print_pdf`~~ — does not exist yet (this spec creates it)

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Use `@is_authenticated()` and `@user_session()` decorators (same as AgentTalk).
- Use `lazy_import("weasyprint", extra="pdf")` for the import (gives clear install error).
- Run `weasyprint.HTML(...).write_pdf()` in `asyncio.get_event_loop().run_in_executor(None, ...)`
  to keep the event loop free.
- Return `web.Response(body=pdf_bytes, ...)` — no need for `StreamResponse` since the
  full PDF is generated in memory before sending.

### Known Risks / Gotchas

- **weasyprint is CPU-intensive**: Must run in executor. Large/complex HTML could take
  seconds. Consider a size limit on the HTML body (e.g., 10 MB).
- **weasyprint system dependencies**: Requires `pango`, `cairo`, `gdk-pixbuf` system
  libraries. These are already satisfied since `PDFPrintTool` works.
- **Security**: The HTML is rendered locally by weasyprint. External resources (images,
  CSS) referenced by the HTML will be fetched. Consider whether to disable network
  access in weasyprint via `base_url` controls.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `weasyprint` | `==68.0` | HTML to PDF rendering (already in `[pdf]` extras) |

---

## 8. Open Questions

- [x] Should external resource loading (images, fonts) be allowed in the HTML?
  *Default: yes, with base_url set to None so relative URLs resolve locally.*
- [ ] Should there be a request body size limit? *Suggested: 10 MB*

---

## Worktree Strategy

- **Isolation**: Not needed — single-task feature, only two files touched.
- **Recommended**: Work directly on a short-lived feature branch from `dev`.
- **Cross-feature dependencies**: None.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-13 | Jesus Lara | Initial draft |
