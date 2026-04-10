# TASK-647: Content Negotiation Wiring

**Feature**: infographic-html-output
**Spec**: `sdd/specs/infographic-html-output.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-645, TASK-646
**Assigned-to**: unassigned

---

## Context

> Implements Module 4 from the spec. Wires the `InfographicHTMLRenderer` into
> the application so that `get_infographic()` returns HTML by default (backward
> compatible) and JSON when `Accept: application/json` is specified.

---

## Scope

- Modify `get_infographic()` in `parrot/bots/abstract.py` to accept an `accept`
  parameter (str, default `"text/html"`). After calling `self.ask()` and getting
  the AIMessage with `InfographicResponse`, check the accept value:
  - `"text/html"` (default) or unrecognized → render via `InfographicHTMLRenderer.render_to_html()`
    and set `response.content` to the HTML string, `response.output_mode` to `OutputMode.HTML`.
  - `"application/json"` → return as-is (current behavior, structured JSON).
- Register `InfographicHTMLRenderer` in `parrot/outputs/formats/__init__.py` lazy-load
  map. Since we don't want a separate `OutputMode`, the renderer is imported directly
  by `get_infographic()`, not via `get_renderer()`.
- Add the lazy-load entry anyway for future use (e.g., if handlers want to use it):
  add `infographic_html` to the `get_renderer` elif chain, but map it to a new
  convenience function rather than a new OutputMode.
- Update the handler layer: if an infographic endpoint is added in the future, it
  should inspect `Accept` header via existing `_get_output_format()` and pass the
  format to `get_infographic()`. For now, `get_infographic()` is called
  programmatically, so the `accept` parameter is sufficient.

**NOT in scope**:
- Creating new HTTP endpoint/route for infographics
- Modifying `_get_output_format()` or `_get_output_mode()` (they already work)
- Changing the InfographicRenderer (JSON) behavior

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Add `accept` param to `get_infographic()`, render HTML when text/html |
| `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` | MODIFY | Add lazy-load entry for infographic_html module |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# In abstract.py (already imported):
from ..models.outputs import OutputMode  # verified: abstract.py uses this throughout

# New import needed in abstract.py:
from ..outputs.formats.infographic_html import InfographicHTMLRenderer
# (created by TASK-645)

# In __init__.py (already imported):
from importlib import import_module  # verified: __init__.py:3
```

### Existing Signatures to Use
```python
# parrot/bots/abstract.py:2574-2653
async def get_infographic(
    self,
    question: str,
    template: Optional[str] = "basic",
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    use_vector_context: bool = True,
    use_conversation_history: bool = False,
    theme: Optional[str] = None,
    ctx: Optional[RequestContext] = None,
    **kwargs,
) -> AIMessage:
    # Line 2643-2653: calls self.ask() with structured_output=InfographicResponse
    # Returns AIMessage with response.structured_output = InfographicResponse

# parrot/models/responses.py — AIMessage fields:
# content: str  — main text content
# output_mode: OutputMode  — how to render
# structured_output: Optional[Any]  — structured data from LLM

# parrot/outputs/formats/__init__.py:82-83 (current INFOGRAPHIC lazy-load)
elif mode == OutputMode.INFOGRAPHIC:
    import_module('.infographic', 'parrot.outputs.formats')
```

### Does NOT Exist
- ~~`OutputMode.INFOGRAPHIC_HTML`~~ — no separate mode; content negotiation via `accept` param
- ~~`get_infographic(format=...)`~~ — no `format` param exists yet; we add `accept`
- ~~HTTP infographic endpoint~~ — no handler route exists; wiring is programmatic only

---

## Implementation Notes

### Modified get_infographic()
```python
async def get_infographic(
    self,
    question: str,
    template: Optional[str] = "basic",
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    use_vector_context: bool = True,
    use_conversation_history: bool = False,
    theme: Optional[str] = None,
    accept: str = "text/html",  # NEW — default HTML for backward compat
    ctx: Optional[RequestContext] = None,
    **kwargs,
) -> AIMessage:
    # ... existing template/question building ...

    response = await self.ask(
        question=augmented_question,
        session_id=session_id,
        user_id=user_id,
        use_vector_context=use_vector_context,
        use_conversation_history=use_conversation_history,
        structured_output=InfographicResponse,
        output_mode=OutputMode.INFOGRAPHIC,
        ctx=ctx,
        **kwargs,
    )

    # Content negotiation: render to HTML unless JSON explicitly requested
    if "application/json" not in accept:
        from ..outputs.formats.infographic_html import InfographicHTMLRenderer
        renderer = InfographicHTMLRenderer()
        html = renderer.render_to_html(
            response.structured_output or response.output,
            theme=theme,
        )
        response.content = html
        response.output_mode = OutputMode.HTML

    return response
```

### Key Constraints
- Default must be `"text/html"` (backward compatible)
- Do NOT create a new `OutputMode` enum value
- Import `InfographicHTMLRenderer` lazily (inside the if block) to avoid
  circular imports and unnecessary import cost
- The `theme` parameter already exists on `get_infographic()` — pass it to the renderer

---

## Acceptance Criteria

- [ ] `get_infographic(accept="text/html")` returns AIMessage with HTML in `.content`
- [ ] `get_infographic(accept="application/json")` returns AIMessage with structured JSON
- [ ] `get_infographic()` (no accept) defaults to HTML
- [ ] `response.output_mode` is `OutputMode.HTML` when returning HTML
- [ ] `response.structured_output` is preserved (not overwritten) in both cases
- [ ] Lazy-load entry added to `__init__.py` for `infographic_html`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.models.infographic import InfographicResponse, TitleBlock, SummaryBlock


class TestContentNegotiation:
    """Test content negotiation in get_infographic().

    These tests mock self.ask() to avoid needing a real LLM.
    """

    @pytest.fixture
    def mock_response(self):
        """AIMessage-like object with InfographicResponse."""
        response = MagicMock()
        response.structured_output = InfographicResponse(
            template="basic", theme="light",
            blocks=[
                TitleBlock(type="title", title="Test"),
                SummaryBlock(type="summary", content="Hello"),
            ],
        )
        response.output = response.structured_output
        response.content = ""
        response.output_mode = None
        return response

    async def test_default_returns_html(self, mock_response):
        """Default accept should return HTML."""
        # Would require bot instance; verify via integration test
        pass

    async def test_json_preserves_structured(self, mock_response):
        """application/json should not render HTML."""
        pass

    async def test_html_sets_output_mode(self, mock_response):
        """HTML rendering sets output_mode to HTML."""
        pass
```

*Note: Full integration tests require a bot instance. Unit tests here verify
the wiring logic. Comprehensive testing is in TASK-648.*

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/infographic-html-output.spec.md`
2. **Check dependencies** — verify TASK-645 and TASK-646 are in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `get_infographic()` signature at abstract.py:2574
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-647-content-negotiation.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
