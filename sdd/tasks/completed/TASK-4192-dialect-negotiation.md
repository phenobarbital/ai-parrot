# TASK-4192: `api/dialect.py` — `resolve_dialect`, `DialectError`, `render_a2ui_schema`

**Feature**: FEAT-650 — A2UI dialect for parrot-formdesigner
**Spec**: `sdd/specs/a2ui-dialect-formbuilder.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4191
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (G2, G8, AC3, AC4). One helper module owns the effective
dialect rule (`?dialect=` > `Accept: application/a2ui+json` > stored) and the
A2UI rendering path through the renderer already registered under `"a2ui"` by
`api/render.py` (FEAT-544). Handlers (TASK-4194/4195) only call this module,
so the precedence and the 400/415 payloads are tested once, here. The
`overrides_to_envelopes` translation table is TASK-4193; this task ships the
function with its *baseline* behaviour (every key → warning, no envelope) so
`render_a2ui_schema` has its final signature from day one.

---

## Scope

- Create `api/dialect.py` with `A2UI_MEDIA_TYPE`, `DIALECT_QUERY_PARAM`, `A2UI_LIST_MAX`, `DialectError`, `resolve_dialect`, `render_a2ui_schema`, and a baseline `overrides_to_envelopes` (warnings only).
- Write `tests/unit/api/test_dialect_negotiation.py` covering the 8 precedence combinations, 400, 415, and the single-envelope render.

**NOT in scope**: the override translation table (TASK-4193), any `handlers.py` edit (TASK-4194/4195), `with_meta` framing (handler concern, TASK-4194).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/dialect.py` | CREATE | negotiation + A2UI render helper |
| `packages/parrot-formdesigner/tests/unit/api/test_dialect_negotiation.py` | CREATE | precedence / error / render tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web
from parrot_formdesigner.core import FormDialect                                   # TASK-4191 (core/__init__.py)
from parrot_formdesigner.core.schema import FormSchema, RenderedForm              # core/schema.py:401, 671
from parrot_formdesigner.api.render import get_renderer, supported_formats, register_renderer  # api/render.py:104, 109, 91
from parrot_formdesigner.api.render import _RENDERERS                             # api/render.py (module dict; test fixture pattern tests/unit/api/test_render_dispatcher.py:41-47)
from parrot_formdesigner.renderers.base import AbstractFormRenderer               # renderers/base.py:58
from parrot_formdesigner.core.schema import FormField, FormSection                # core/schema.py:65, 229
from parrot_formdesigner.core.types import FieldType                              # core/types.py:16
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py
def register_renderer(format_key: str, renderer: AbstractFormRenderer) -> None   # line 91
def get_renderer(format_key: str) -> AbstractFormRenderer | None                  # line 104
def supported_formats() -> list[str]                                              # line 109
# 415 payload shape used by handle_render (line 183-186): web.json_response({"supported": supported_formats()}, status=415)
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py
class AbstractFormRenderer(ABC):
    async def render(self, form: FormSchema, style=None, *, locale: str = "en", prefilled=None, errors=None) -> RenderedForm   # line 69
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class RenderedForm(BaseModel): content: Any; content_type: str; metadata; warnings: list[RenderWarning]   # line 671-690
class RenderWarning(BaseModel): field_id: str; field_uid; field_type: str; renderer: str; reason: str   # line 650-668
# packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py
#   `from parrot.a2a.models import A2UI_MEDIA_TYPE` (line 88) — value "application/a2ui+json"; this module hard-codes the
#   same literal so it needs no ai-parrot import.
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py
class A2UIFormRenderer(AbstractFormRenderer): RENDERER_NAME = "a2ui"              # line 294, 309 (what get_renderer("a2ui") returns)
```

### Does NOT Exist
- ~~`A2UIFormRenderer.accepts_tenant`~~ — no such attribute; call `renderer.render(form, locale=locale)` only (tenant comes from `form.tenant`, renderers/a2ui.py:361).
- ~~`parrot_formdesigner.api.dialect`~~ — this task creates it.
- ~~`request.app["form_registry"]` inside this module~~ — the helper takes a `FormSchema`; registry lookup stays in the handlers.
- ~~an `Accept` wildcard match~~ — only the exact media type selects A2UI (spec §7).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/dialect.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/unit/api/test_dialect_negotiation.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py#get_renderer",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py#supported_formats",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py#AbstractFormRenderer",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#RenderedForm"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- No top-level import of `parrot.*` (AC12) — this module must import cleanly without the `ai-parrot` extra; it only needs `get_renderer`.
- Precedence is strict: query wins even over `Accept`; a wildcard/`application/json` Accept never selects A2UI.
- `DialectError(400)` payload: `{"error": "unknown dialect '<v>'", "supported": ["json_schema", "a2ui"]}`; `DialectError(415)` payload: `{"supported": supported_formats()}` (identical to `handle_render`).

### References in Codebase
- `api/render.py:165-235` — `handle_render` (the 415 shape and `with_meta` shape the handlers mirror).
- `tests/unit/api/test_render_dispatcher.py:41-47` — `_reset_renderers` fixture to register a fake renderer in tests.

---

## Implementation Blueprint

### Steps (in order)
1. Create the module with constants and `DialectError` — *why*: handlers turn the exception into `JSONResponse(payload, status=...)` uniformly.
2. Implement `resolve_dialect` exactly per the precedence table — *why*: AC3 is tested combination by combination.
3. Implement `render_a2ui_schema` over `get_renderer("a2ui")` — *why*: the dialect layer never instantiates its own renderer (spec Non-Goals).
4. Ship the baseline `overrides_to_envelopes` — *why*: TASK-4193 replaces the body, not the signature.
5. Tests with a fake renderer registered through `register_renderer` (so no ai-parrot needed) plus one `importorskip` test on the real renderer.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/dialect.py` (CREATE)
```python
"""Dialect negotiation for the form contract endpoints (FEAT-650, spec §3 M2).

Effective dialect = ``?dialect=`` query > ``Accept: application/a2ui+json`` >
``form.dialect``. ``GET /forms/{uid}`` never consults this module.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from aiohttp import web

from ..core import FormDialect
from ..core.schema import FormSchema, RenderedForm
from .render import get_renderer, supported_formats

logger = logging.getLogger(__name__)

A2UI_MEDIA_TYPE = "application/a2ui+json"  # == parrot.a2a.models.A2UI_MEDIA_TYPE (a2ui_wire.py:88); literal so no ai-parrot import
DIALECT_QUERY_PARAM = "dialect"
A2UI_LIST_MAX = int(os.environ.get("FORMDESIGNER_A2UI_LIST_MAX", "50"))
_SUPPORTED = [d.value for d in FormDialect]


class DialectError(Exception):
    """A negotiation failure: ``status`` (400 | 415) + the JSON ``payload`` to return."""

    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        super().__init__(payload.get("error") or f"dialect error {status}")
        self.status = status
        self.payload = payload


def resolve_dialect(request: web.Request, form: FormSchema) -> FormDialect:
    """Return the effective dialect for ``form`` on this request (spec G2).

    Raises:
        DialectError: 400 for an unknown ``?dialect=`` value; 415 (payload
            ``{"supported": supported_formats()}``) when A2UI is required but
            no ``"a2ui"`` renderer is registered (ai-parrot extra missing).
    """
    raw = request.query.get(DIALECT_QUERY_PARAM)
    if raw is not None:
        try:
            dialect = FormDialect(raw)
        except ValueError as exc:
            raise DialectError(400, {"error": f"unknown dialect {raw!r}", "supported": _SUPPORTED}) from exc
    elif A2UI_MEDIA_TYPE in request.headers.get("Accept", ""):
        dialect = FormDialect.A2UI
    else:
        dialect = form.dialect
    if dialect is FormDialect.A2UI and get_renderer("a2ui") is None:
        raise DialectError(415, {"supported": supported_formats()})
    return dialect


async def render_a2ui_schema(
    form: FormSchema, *, locale: str = "en", overrides: Mapping[str, Any] | None = None
) -> tuple[list[dict[str, Any]], RenderedForm, list[str]]:
    """Render ``form`` with the registered ``"a2ui"`` renderer; append translated overrides.

    Returns ``(envelopes, rendered, warnings)`` — ``envelopes[0]`` is the
    ``createSurface`` (``rendered.content``), the rest come from
    :func:`overrides_to_envelopes`. Raises ``RuntimeError`` when no ``"a2ui"``
    renderer is registered (callers resolve the dialect first, so this is a bug path).
    """
    renderer = get_renderer("a2ui")
    if renderer is None:
        raise RuntimeError("render_a2ui_schema: no 'a2ui' renderer registered (install parrot-formdesigner[ai-parrot])")
    rendered = await renderer.render(form, locale=locale)
    envelopes: list[dict[str, Any]] = [rendered.content]
    warnings = [w.reason for w in rendered.warnings]
    if overrides:
        extra, extra_warnings = overrides_to_envelopes(form, rendered, overrides, locale=locale)
        envelopes.extend(extra)
        warnings.extend(extra_warnings)
    return envelopes, rendered, warnings


def overrides_to_envelopes(
    form: FormSchema, rendered: RenderedForm, overrides: Mapping[str, Any], *, locale: str = "en"
) -> tuple[list[dict[str, Any]], list[str]]:
    """Translate shallow ``schema_overrides`` into A2UI envelopes (spec §7 table).

    TASK-4192 baseline: no key is translatable yet — every key yields an
    ``override_not_translatable:<key>`` warning. TASK-4193 implements the table.
    """
    return [], [f"override_not_translatable:{key}" for key in overrides]
```
**Why this shape**: the precedence rule is a straight transcription of G2/AC3; the 415 reuses `supported_formats()` so clients see the same payload `/render/{format}` gives; the baseline translator keeps the final signature so TASK-4194 can be written against it before TASK-4193 lands.

### `packages/parrot-formdesigner/tests/unit/api/test_dialect_negotiation.py` (CREATE)
```python
"""resolve_dialect / render_a2ui_schema — FEAT-650 TASK-4192."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import make_mocked_request

from parrot_formdesigner.api import dialect as d
from parrot_formdesigner.api.render import _RENDERERS, register_renderer
from parrot_formdesigner.core import FormDialect
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, RenderedForm
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.base import AbstractFormRenderer


class _FakeA2UI(AbstractFormRenderer):
    async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None) -> RenderedForm:
        return RenderedForm(content={"version": "v1.0", "createSurface": {"surfaceId": f"form-{form.form_uid}"}},
                            content_type=d.A2UI_MEDIA_TYPE, metadata={}, warnings=[])


@pytest.fixture(autouse=True)
def _reset():
    snap = dict(_RENDERERS); _RENDERERS.clear(); yield; _RENDERERS.clear(); _RENDERERS.update(snap)


def _form(dialect="json_schema") -> FormSchema:
    return FormSchema(form_id="f", title={"en": "F"}, tenant="navigator", dialect=dialect,
                      sections=[FormSection(section_id="s", fields=[FormField(field_id="a", field_type=FieldType.TEXT, label={"en": "A"})])])


def _req(query: str = "", accept: str | None = None):
    headers = {"Accept": accept} if accept else {}
    return make_mocked_request("GET", f"/x{query}", headers=headers)


@pytest.mark.parametrize(
    "query,accept,stored,expected",
    [
        ("", None, "json_schema", FormDialect.JSON_SCHEMA),
        ("", None, "a2ui", FormDialect.A2UI),
        ("", d.A2UI_MEDIA_TYPE, "json_schema", FormDialect.A2UI),
        ("", "application/json", "json_schema", FormDialect.JSON_SCHEMA),
        ("?dialect=json_schema", d.A2UI_MEDIA_TYPE, "a2ui", FormDialect.JSON_SCHEMA),
        ("?dialect=a2ui", None, "json_schema", FormDialect.A2UI),
        ("?dialect=a2ui", "application/json", "json_schema", FormDialect.A2UI),
        ("", "*/*", "json_schema", FormDialect.JSON_SCHEMA),
    ],
)
def test_precedence(query, accept, stored, expected):
    register_renderer("a2ui", _FakeA2UI())
    assert d.resolve_dialect(_req(query, accept), _form(stored)) is expected


def test_unknown_query_value_is_400():
    with pytest.raises(d.DialectError) as ei:
        d.resolve_dialect(_req("?dialect=xml"), _form())
    assert ei.value.status == 400 and ei.value.payload["supported"] == ["json_schema", "a2ui"]


def test_a2ui_without_renderer_is_415_with_supported_list():
    register_renderer("html", _FakeA2UI())
    with pytest.raises(d.DialectError) as ei:
        d.resolve_dialect(_req("?dialect=a2ui"), _form())
    assert ei.value.status == 415 and ei.value.payload == {"supported": ["html"]}


async def test_render_a2ui_schema_single_envelope_and_baseline_overrides():
    register_renderer("a2ui", _FakeA2UI())
    envelopes, rendered, warnings = await d.render_a2ui_schema(_form(), overrides={"title": "X"})
    # FILL IN: assert len(envelopes)==1, rendered.content_type==A2UI_MEDIA_TYPE, warnings==["override_not_translatable:title"] — bounded by AC3/AC4


async def test_real_renderer_when_extra_installed():
    pytest.importorskip("parrot.outputs.a2ui")
    # FILL IN: register parrot_formdesigner.renderers.A2UIFormRenderer(), render _form(), assert envelopes[0]["createSurface"]["surfaceId"] startswith "form-" — bounded by AC4
```
**Why this shape**: the fake renderer makes the precedence matrix run without ai-parrot (AC12); the real-renderer test is `importorskip`-guarded like `tests/unit/renderers/test_a2ui_export.py:12`.

### FILL IN checklist
- [ ] `test_dialect_negotiation.py::test_render_a2ui_schema_single_envelope_and_baseline_overrides` — assertions; bounded by AC3/AC4.
- [ ] `test_dialect_negotiation.py::test_real_renderer_when_extra_installed` — real render smoke; bounded by AC4.

---

## Acceptance Criteria

- [ ] All eight precedence combinations resolve per spec G2; 400 and 415 payloads match §7.
- [ ] `import parrot_formdesigner.api.dialect` succeeds with ai-parrot uninstalled (no top-level `parrot.` import — add an AST assertion like `tests/unit/renderers/test_a2ui_export.py::test_package_import_does_not_import_ai_parrot_eagerly`).
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/api/test_dialect_negotiation.py -v`
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/dialect.py` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_dialect_negotiation.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py -q`

---

## Test Specification

See the CREATE block above. Add one AST test asserting no top-level `parrot.` import in `api/dialect.py` (pattern: `tests/unit/renderers/test_a2ui_export.py:19-30`).

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug a2ui-dialect-formbuilder --feature-id FEAT-650`)
2. **Read the spec** §3 M2 and §7 Patterns to Follow
3. **Check dependencies** — TASK-4191 must be `"done"`
4. **Verify the Codebase Contract** — `grep -n 'def get_renderer\|def supported_formats\|_RENDERERS' packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py`
5. **Update status** in `sdd/tasks/index/a2ui-dialect-formbuilder.json` → `"in-progress"` and commit only that index file
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src` + the Validation Commands
8. **Commit the code** — stage only the two files above
9. **Close** with `scripts/sdd/close_task.sh TASK-4192 a2ui-dialect-formbuilder verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

Implemented by codex gpt-5.6-terra; merged by sdd-worker orchestrator; merge-tier validation green (171 passed).

**Completed by**: sdd-worker orchestrator
**Date**: 2026-10-24
**Notes**:

**Deviations from spec**: none
