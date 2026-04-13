# TASK-660: Implement PrintPDFHandler

**Feature**: printpdf-helper-agenttalk
**Spec**: `sdd/specs/printpdf-helper-agenttalk.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the core task for FEAT-097. It creates the `PrintPDFHandler` — a thin
aiohttp handler that accepts HTML and returns PDF. Implements Spec Section 3,
Module 1.

---

## Scope

- Create `packages/ai-parrot/src/parrot/handlers/print_pdf.py` with `PrintPDFHandler`.
- The handler must:
  - Accept `POST` requests.
  - Support two content types:
    - `text/html`: raw HTML body is the content to convert.
    - `application/json`: JSON body with `html` (required), `filename` (optional,
      default `"document.pdf"`), `disposition` (optional, `"inline"` | `"attachment"`,
      default `"attachment"`).
  - Convert HTML to PDF using `weasyprint.HTML(string=html).write_pdf()`.
  - Run weasyprint in `asyncio.get_event_loop().run_in_executor(None, ...)` to avoid
    blocking the event loop.
  - Return `web.Response(body=pdf_bytes, content_type="application/pdf")` with
    `Content-Disposition` header.
  - Return `self.error(...)` with HTTP 400 for empty/missing HTML body.
- Add the handler to `parrot/handlers/__init__.py` lazy exports.
- Write unit tests.

**NOT in scope**: Route registration (TASK-654), URL-to-PDF, Markdown-to-PDF.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/print_pdf.py` | CREATE | PrintPDFHandler implementation |
| `packages/ai-parrot/src/parrot/handlers/__init__.py` | MODIFY | Add lazy import for PrintPDFHandler |
| `tests/test_print_pdf_handler.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from navigator.views import BaseView  # verified: handlers/agent.py:31
from navigator_auth.decorators import is_authenticated, user_session  # verified: handlers/agent.py:22
from aiohttp import web  # verified: handlers/agent.py:16
from navconfig.logging import logging  # verified: handlers/agent.py:20
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/handlers/agent.py:47
@is_authenticated()
@user_session()
class AgentTalk(BaseView):
    _logger_name: str = "Parrot.AgentTalk"  # line 64

    def post_init(self, *args, **kwargs):  # line 66
        self.logger = logging.getLogger(self._logger_name)

# navigator.views.BaseView (external — navigator framework)
class BaseView:
    request: web.Request
    def error(self, msg: str, status: int = 400, ...) -> web.Response: ...

# weasyprint (external, pinned ==68.0 in pyproject.toml:119)
# Usage: weasyprint.HTML(string=html_str).write_pdf()  → returns bytes when target=None
# Verified usage at: packages/ai-parrot-tools/src/parrot_tools/pdfprint.py:892-902

# Lazy import pattern (packages/ai-parrot/src/parrot/_imports.py:24)
def lazy_import(module_name: str, extra: str = "") -> ModuleType: ...
# Usage: _weasyprint = lazy_import("weasyprint", extra="pdf")

# handlers/__init__.py lazy export pattern (existing):
def __getattr__(name: str):
    if name == "ChatbotHandler":
        from .bots import ChatbotHandler
        return ChatbotHandler
    # ...
```

### Does NOT Exist

- ~~`BaseView.file_response()`~~ — not a BaseView method; use `web.Response(body=...)`
- ~~`BaseView.stream_response()`~~ — not a BaseView method; use `web.StreamResponse` directly
- ~~`PDFPrintTool.html_to_pdf()`~~ — no such method on PDFPrintTool
- ~~`parrot.handlers.print_pdf`~~ — does not exist yet (this task creates it)
- ~~`parrot.utils.pdf`~~ — does not exist

---

## Implementation Notes

### Pattern to Follow

```python
# Follow the same decorator + BaseView pattern as AgentTalk (handlers/agent.py:45-67)
@is_authenticated()
@user_session()
class PrintPDFHandler(BaseView):
    _logger_name: str = "Parrot.PrintPDF"

    def post_init(self, *args, **kwargs):
        self.logger = logging.getLogger(self._logger_name)

    async def post(self) -> web.Response:
        # 1. Determine content type and extract HTML
        # 2. Validate HTML is non-empty
        # 3. Run weasyprint in executor:
        #    loop = asyncio.get_event_loop()
        #    pdf_bytes = await loop.run_in_executor(None, _generate_pdf, html)
        # 4. Return web.Response(body=pdf_bytes, content_type="application/pdf", headers={...})
```

### Key Constraints

- Must use `run_in_executor` for weasyprint (it is synchronous/CPU-bound)
- Use `lazy_import("weasyprint", extra="pdf")` — NOT a top-level import
- Return `self.error("...", status=400)` for bad requests
- Keep the handler file small and focused — no templates, no Markdown conversion

### References in Codebase

- `packages/ai-parrot/src/parrot/handlers/agent.py` — handler pattern (decorators, BaseView, post_init)
- `packages/ai-parrot-tools/src/parrot_tools/pdfprint.py:890-902` — weasyprint usage pattern
- `packages/ai-parrot/src/parrot/handlers/google_generation.py:157-169` — binary response pattern

---

## Acceptance Criteria

- [ ] `PrintPDFHandler.post()` accepts `text/html` body and returns PDF bytes
- [ ] `PrintPDFHandler.post()` accepts JSON `{"html": "..."}` and returns PDF bytes
- [ ] Custom `filename` and `disposition` supported via JSON body
- [ ] Empty body returns HTTP 400
- [ ] weasyprint runs in thread executor (not blocking event loop)
- [ ] Handler registered in `handlers/__init__.py` lazy exports
- [ ] Unit tests pass: `pytest tests/test_print_pdf_handler.py -v`

---

## Test Specification

```python
# tests/test_print_pdf_handler.py
import pytest
from parrot.handlers.print_pdf import PrintPDFHandler


class TestPrintPDFHandler:
    """Tests for PrintPDFHandler PDF generation logic."""

    def test_handler_class_exists(self):
        """PrintPDFHandler is importable."""
        assert PrintPDFHandler is not None

    # Additional tests should mock aiohttp request and verify:
    # - HTML body → PDF bytes returned
    # - JSON body with html field → PDF bytes returned
    # - Empty body → 400 error
    # - Content-Disposition header set correctly
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/printpdf-helper-agenttalk.spec.md`
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm imports and signatures still match
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the handler following scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-660-printpdf-handler.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
