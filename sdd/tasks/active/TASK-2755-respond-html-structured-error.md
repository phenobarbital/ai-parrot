# TASK-2755: `_respond_html` returns a structured 422 instead of leaking a traceback

**Feature**: FEAT-499 — A2UI optional-binding lowering (`parrot_optional` reaches the wire)
**Spec**: `sdd/specs/a2ui-optional-binding-lowering.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2. `SurfaceNegotiationService._respond_html` (line 232) wraps only
its *import* in `try/except` and then calls `InteractiveHTMLRenderer().render(envelope)`
unguarded. Any render failure — the `BakeError` this feature fixes, but equally any stored
envelope whose binding stops resolving later — escapes as an uncaught 500 with a traceback
on **both** `GET /api/v1/ui/surfaces/{surface_id}` and the `A2UIHandler` mirror
`GET /api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id}` (`a2ui.py:246`).

The sibling `_refresh` (line 480) already models the correct behaviour, mapping
`RecipeRunException` to 502/422 and catching bare `Exception`.

This task is **independent of TASK-2753/2754** and can run in a separate worktree: it shares
no files with them. It is worth doing regardless of the bake fix — a stored surface can
always become unrenderable.

---

## Scope

- Wrap the `renderer.render(envelope)` call in `_respond_html` and return a structured JSON
  error body with status **422** on failure.
- Log the failure with `logger.exception` so the traceback reaches the logs, not the client.
- Leave the existing `ImportError` → 501 branch exactly as it is.
- Write unit tests for the failure path, the happy path, and the untouched 501 branch, plus
  an integration test proving BOTH routes behave identically.

**NOT in scope**: any change to `baking.py`, the builders, the renderers, or `RecipeRunner`
(TASK-2753/2754); any change to `_refresh`; any change to `A2UIHandler` (it inherits this
fix automatically through the shared negotiation service).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | MODIFY | Guard `_respond_html` (line 232) |
| `packages/ai-parrot-server/tests/handlers/test_a2ui_surfaces_route.py` | MODIFY | Add failure-path cases |
| `packages/ai-parrot-server/tests/integration/test_ui_surfaces_e2e.py` | MODIFY | Both-routes parity case |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `84932e839` (2026-09-02).

### Verified Imports
```python
from parrot.handlers.ui_surfaces import SurfaceNegotiationService, resolve_surface_access  # ui_surfaces.py:175, :138
from parrot.handlers.models.ui_surfaces import PgUISurfaceStore, UISurfaceKind, UISurfaceRecord
from parrot.outputs.a2ui.models import CreateSurface
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py
class SurfaceNegotiationService:                                      # line 175
    def negotiate(self, request: web.Request) -> str: ...             # line 183
    async def respond(self, record: UISurfaceRecord, accept: str) -> web.Response: ...  # line 206
    def _respond_json(self, record: UISurfaceRecord) -> web.Response: ...                # line 223

    async def _respond_html(self, record: UISurfaceRecord) -> web.Response:              # line 232
        try:
            from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer
        except ImportError:
            return web.json_response(
                {"status": "error", "message": ("HTML rendering requires ai-parrot-visualizations. "
                                                "Install with: pip install ai-parrot-visualizations")},
                status=501,
            )
        envelope = CreateSurface.model_validate(record.envelope)
        renderer = InteractiveHTMLRenderer()
        artifact = await renderer.render(envelope)                    # <-- UNGUARDED
        return web.Response(body=artifact.content, content_type="text/html")

# The precedent to copy — UISurfacesHandler._refresh, line 480:
        except RecipeRunException as exc:
            status = 502 if exc.error.stage == "data" else 422        # line 534
            return self.json_response({"status": "error", **exc.error.model_dump()}, status=status)
        except Exception as exc:
            self.logger.exception("UISurfaces refresh failed")
            return self.json_response({"status": "error", "message": str(exc)}, status=500)

# packages/ai-parrot-server/src/parrot/handlers/a2ui.py — inherits the fix, DO NOT EDIT
    async def _get_surface(self) -> web.Response:                     # line 246
        negotiation = self._ui_surfaces_negotiation()   # SAME app-wide instance as the REST lane
        accept = negotiation.negotiate(self.request)
        return await negotiation.respond(record, accept)
```

### Does NOT Exist
- ~~`SurfaceNegotiationService._error()`~~ — `_error` (ui_surfaces.py:302) is a method on
  **`UISurfacesHandler`**, not on the negotiation service. `SurfaceNegotiationService` is a
  plain class with no `BaseView` base, so it must build `web.json_response(...)` directly —
  exactly as its own existing 501 branch already does.
- ~~`self.logger` on `SurfaceNegotiationService`~~ — it has no `logger` attribute. Use the
  module-level `logger` in `ui_surfaces.py` (confirm its name before use).
- ~~`BaseView.error(status=422)`~~ — `BaseView.error()` only recognizes
  400/401/403/404/406/412/428 and silently degrades anything else to 400. This is documented
  at `ui_surfaces.py:302-314`. Never route a 422 through it.
- ~~`A2UIHandler` needing its own guard~~ — it delegates to the same
  `SurfaceNegotiationService` instance via `app["ui_surfaces_negotiation"]`.

---

## Implementation Notes

### Pattern to Follow
```python
        envelope = CreateSurface.model_validate(record.envelope)
        renderer = InteractiveHTMLRenderer()
        try:
            artifact = await renderer.render(envelope)
        except Exception as exc:  # noqa: BLE001 - any render failure is a client-visible 422
            logger.exception("UISurfaces HTML render failed for surface %s", record.surface_id)
            return web.json_response(
                {
                    "status": "error",
                    "message": f"Stored surface could not be rendered: {exc}",
                    "surface_id": record.surface_id,
                },
                status=422,
            )
        return web.Response(body=artifact.content, content_type="text/html")
```

### Key Constraints
- Resolved decision (spec §8 Q2): **422**, never a 5xx. A stored surface that cannot be
  re-baked is an unprocessable entity, not a server fault. This matches `_refresh`, which
  reserves 502 exclusively for `stage="data"`.
- `CreateSurface.model_validate(record.envelope)` can also raise (a malformed stored row).
  Decide whether it belongs inside the same guard — it is the same class of failure and the
  same 422 answer. Cover it with a test either way.
- Do NOT change the 501 `ImportError` branch, and do not swallow it into the new guard.
- The error body must not leak a traceback or internal path to the client; the traceback
  goes to the log.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py:534-540` — the error-mapping
  shape to mirror.
- `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py:302-314` — why every error
  response here is built directly rather than via `BaseView.error()`.

---

## Acceptance Criteria

- [ ] A render failure returns HTTP **422** with a JSON body, not a traceback and not a 5xx
- [ ] The traceback is logged (`logger.exception`), not returned to the client
- [ ] The happy path still returns `text/html` with the rendered body, unchanged
- [ ] The missing-`ai-parrot-visualizations` branch still returns 501 with its install hint
- [ ] `GET /api/v1/ui/surfaces/{id}` and `GET /api/v1/agents/{agent_id}/a2ui/surfaces/{id}`
      return the SAME status and body shape for the same failing surface
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_a2ui_surfaces_route.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_a2ui_surfaces_route.py
import pytest
from unittest.mock import AsyncMock, patch


class TestRespondHtmlFailure:
    async def test_render_failure_returns_422_json(self, negotiation, record):
        with patch(
            "parrot.outputs.a2ui_renderers.interactive_html.InteractiveHTMLRenderer.render",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            resp = await negotiation.respond(record, "text/html")
        assert resp.status == 422
        assert b"traceback" not in resp.body.lower()

    async def test_render_success_unchanged(self, negotiation, record):
        resp = await negotiation.respond(record, "text/html")
        assert resp.status == 200
        assert resp.content_type == "text/html"

    async def test_missing_visualizations_still_501(self, negotiation, record):
        """The ImportError branch must not be swallowed by the new guard."""

    async def test_malformed_stored_envelope(self, negotiation):
        """A row whose envelope no longer validates is also a 422, not a 500."""


class TestBothRoutesAgree:
    async def test_rest_and_mirror_return_identical_error(self, client):
        """FEAT-492 G6: the mirror is not protocol-strict; both share one service."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none; this task is independent and may run in parallel
3. **Verify the Codebase Contract** — confirm `_respond_html`'s body and the module-level
   logger's name before writing
4. **Update status** in `sdd/tasks/index/a2ui-optional-binding-lowering.json` → `"in-progress"`
5. **Implement** following the scope and contract above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2755-respond-html-structured-error.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
