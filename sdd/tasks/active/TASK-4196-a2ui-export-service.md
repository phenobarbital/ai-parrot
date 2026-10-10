# TASK-4196: `A2UIExportService` + `ExportedSurface` (services/a2ui_export.py)

**Feature**: FEAT-650 — A2UI dialect for parrot-formdesigner
**Spec**: `sdd/specs/a2ui-dialect-formbuilder.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (G4, AC6, codex S7). One service exports every form of a
tenant as A2UI surfaces (or JSON Schema) — the library door that both
`POST /forms/export` (TASK-4197) and the CLI (TASK-4204) call. It wraps
`FormRegistry` + a renderer; it must hydrate from storage first (the
in-memory view is a cache), never cross tenants, and isolate per-form
render failures as `error` rows. There is deliberately **no**
`export_all_tenants` (S7).

---

## Scope

- Create `services/a2ui_export.py` with `ExportedSurface` and `A2UIExportService` (`export_form`, `export_tenant`).
- Write `tests/unit/services/test_a2ui_export.py` with a fake renderer (no ai-parrot needed) + one `importorskip` real-renderer test.

**NOT in scope**: HTTP handler/route (TASK-4197), CLI (TASK-4204), any cross-tenant enumeration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_export.py` | CREATE | service + model |
| `packages/parrot-formdesigner/tests/unit/services/test_a2ui_export.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.services.registry import FormRegistry, FormStorage       # services/registry.py:240, 63
from parrot_formdesigner.renderers.base import AbstractFormRenderer               # renderers/base.py:58
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer           # renderers/jsonschema.py:301
from parrot_formdesigner.api.render import get_renderer                           # api/render.py:104 (import lazily inside __init__ to avoid api↔services import cycles)
from parrot_formdesigner.core.schema import FormSchema, RenderedForm              # core/schema.py:401, 671
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:
    def __init__(self, storage: FormStorage | None = None, app=None, default_tenant: str = "navigator", require_tenant: bool = True)   # line 275
    async def register(self, form, *, persist=False, overwrite=True, tenant=None) -> None   # line 466
    async def get(self, form_uid: uuid.UUID, *, tenant=None) -> FormSchema | None            # line 976
    async def list_forms(self, *, tenant=None) -> list[FormSchema]                            # line 1102 — in-memory bucket of ONE tenant
    async def load_from_storage(self, *, tenant=None) -> int                                  # line 1320 — hydrates the bucket from storage
    @property storage -> FormStorage | None                                                   # line 1389
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema: form_uid: uuid.UUID (453); form_id (454); version (455); published_version: str | None (469)
class RenderedForm: content: Any; content_type: str; metadata; warnings: list[RenderWarning]   # 671-690
class RenderWarning: field_id; field_uid; field_type; renderer; reason                          # 650-668
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py
class AbstractFormRenderer(ABC): async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None) -> RenderedForm   # line 69
```

### Does NOT Exist
- ~~`A2UIExportService.export_all_tenants`~~ / ~~`--all-tenants`~~ — removed by codex S7; `FormRegistry.list_tenants()` (line 1197) is a cache view and must not drive an export.
- ~~`FormStorage.list_forms()` returning `FormSchema`~~ — summary dicts (`registry.py:130`); use `load_from_storage` + `list_forms` instead.
- ~~`FormSchema.is_published`~~ — use `published_version is not None`.
- ~~`parrot_formdesigner.services.a2ui_export`~~ — this task creates it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_export.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/unit/services/test_a2ui_export.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py#FormRegistry",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py#AbstractFormRenderer",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#RenderedForm"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- No `parrot.*` import at module top (AC12). `get_renderer("a2ui")` is resolved lazily in `__init__` when `renderer is None`; `RuntimeError` with the standard "requires the 'ai-parrot' extra" wording when it is unavailable.
- `export_tenant` is an **async generator** so the HTTP handler can stream it line by line.
- A renderer exception never propagates: the row carries `error=str(exc)`, `envelope=None`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the model and the service — *why*: the model is the NDJSON line contract shared with TASK-4197/4204.
2. Hydrate then list — *why*: S7, DB-only forms must be exported.
3. Tests with a fake renderer and an in-memory `FormRegistry(storage=None)`; one test with a fake `FormStorage` proving `load_from_storage` is awaited.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_export.py` (CREATE)
```python
"""Bulk export of forms as A2UI surfaces / JSON Schema (FEAT-650, spec §3 M3).

The in-memory ``FormRegistry`` view is a cache: :meth:`A2UIExportService.export_tenant`
always hydrates from storage first (codex S7) and never crosses tenants.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

from pydantic import BaseModel, Field

from ..core.schema import FormSchema
from ..renderers.base import AbstractFormRenderer
from .registry import FormRegistry

logger = logging.getLogger(__name__)


class ExportedSurface(BaseModel):
    """One exported form — one NDJSON line (spec §2 Data Models)."""

    form_uid: str
    form_id: str
    version: str
    dialect: str
    envelope: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class A2UIExportService:
    """Export the forms of ONE tenant through a renderer (default: the registered ``"a2ui"`` one)."""

    def __init__(self, registry: FormRegistry, *, renderer: AbstractFormRenderer | None = None,
                 dialect: str = "a2ui", locale: str = "en") -> None:
        self.logger = logging.getLogger(__name__)
        self.registry = registry
        self.dialect = dialect
        self.locale = locale
        if renderer is None:
            from ..api.render import get_renderer  # lazy: avoids an api↔services import cycle at module import

            if dialect == "json_schema":
                from ..renderers.jsonschema import JsonSchemaRenderer

                renderer = JsonSchemaRenderer()
            else:
                renderer = get_renderer("a2ui")
            if renderer is None:
                raise RuntimeError("A2UIExportService requires the 'ai-parrot' extra (no 'a2ui' renderer registered)")
        self.renderer = renderer

    async def export_form(self, form_uid: uuid.UUID, *, tenant: str) -> ExportedSurface:
        """Render one form; a missing form or a renderer failure becomes ``error`` (never raises)."""
        form = await self.registry.get(form_uid, tenant=tenant)
        if form is None:
            return ExportedSurface(form_uid=str(form_uid), form_id="", version="", dialect=self.dialect, error="not found")
        return await self._render(form)

    async def export_tenant(self, tenant: str, *, form_uids: Sequence[uuid.UUID] | None = None,
                            published_only: bool = False) -> AsyncIterator[ExportedSurface]:
        """Yield every form of ``tenant`` (storage hydrated first); optional uid filter / published-only."""
        if self.registry.storage is not None:
            await self.registry.load_from_storage(tenant=tenant)
        wanted = {str(u) for u in form_uids} if form_uids else None
        for form in await self.registry.list_forms(tenant=tenant):
            if wanted is not None and str(form.form_uid) not in wanted:
                continue
            if published_only and form.published_version is None:
                continue
            yield await self._render(form)

    async def _render(self, form: FormSchema) -> ExportedSurface:
        base = {"form_uid": str(form.form_uid), "form_id": form.form_id, "version": form.version, "dialect": self.dialect}
        try:
            rendered = await self.renderer.render(form, locale=self.locale)
        except Exception as exc:  # noqa: BLE001 — isolate per form (AC6)
            self.logger.warning("export: render failed for %s: %s", form.form_uid, exc)
            return ExportedSurface(**base, error=str(exc))
        return ExportedSurface(**base, envelope=rendered.content, warnings=[w.reason for w in rendered.warnings])
```
**Why this shape**: `export_tenant` as an async generator is what lets the handler stream NDJSON without buffering; `load_from_storage` first is codex S7; `published_only` uses `published_version` (spec §3 M3). `JsonSchemaRenderer.content` is a dict too, so the same model carries both dialects.

### `packages/parrot-formdesigner/tests/unit/services/test_a2ui_export.py` (CREATE)
```python
"""A2UIExportService — FEAT-650 TASK-4196."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, RenderedForm
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.base import AbstractFormRenderer
from parrot_formdesigner.services.a2ui_export import A2UIExportService, ExportedSurface
from parrot_formdesigner.services.registry import FormRegistry


class _Fake(AbstractFormRenderer):
    def __init__(self, fail_for: str | None = None): self.fail_for = fail_for
    async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None) -> RenderedForm:
        if form.form_id == self.fail_for:
            raise ValueError("boom")
        return RenderedForm(content={"createSurface": {"surfaceId": f"form-{form.form_uid}"}}, content_type="application/a2ui+json", metadata={}, warnings=[])


def _form(fid, tenant="t1", published=None):
    return FormSchema(form_id=fid, title={"en": fid}, tenant=tenant, published_version=published,
                      sections=[FormSection(section_id="s", fields=[FormField(field_id="a", field_type=FieldType.TEXT, label={"en": "A"})])])


@pytest.fixture
async def registry():
    r = FormRegistry(storage=None, default_tenant="t1")
    for f in (_form("a"), _form("b", published="1.0"), _form("c", tenant="t2")):
        await r.register(f, tenant=f.tenant)
    return r


async def test_export_tenant_isolates_failures_and_never_crosses_tenants(registry):
    svc = A2UIExportService(registry, renderer=_Fake(fail_for="b"))
    rows = [r async for r in svc.export_tenant("t1")]
    assert sorted(r.form_id for r in rows) == ["a", "b"]
    by_id = {r.form_id: r for r in rows}
    assert by_id["a"].envelope and by_id["a"].error is None
    assert by_id["b"].envelope is None and by_id["b"].error == "boom"


async def test_published_only_and_uid_filter(registry):
    # FILL IN: published_only=True → only "b"; form_uids=[a.form_uid] → only "a" — bounded by AC6


async def test_hydrates_from_storage_first():
    # FILL IN: a FormStorage stub whose list/load are recorded; assert registry.load_from_storage awaited before list_forms — bounded by codex S7
    pass


async def test_json_schema_dialect_uses_jsonschema_renderer(registry):
    svc = A2UIExportService(registry, dialect="json_schema")
    rows = [r async for r in svc.export_tenant("t1")]
    assert all(r.dialect == "json_schema" and r.envelope.get("type") == "object" for r in rows)


async def test_default_renderer_requires_extra(registry, monkeypatch):
    import parrot_formdesigner.api.render as render
    monkeypatch.setattr(render, "_RENDERERS", {})
    with pytest.raises(RuntimeError, match="ai-parrot"):
        A2UIExportService(registry)


async def test_real_a2ui_renderer(registry):
    pytest.importorskip("parrot.outputs.a2ui")
    # FILL IN: A2UIExportService(registry, renderer=A2UIFormRenderer()) → every envelope has "createSurface" — bounded by AC6
```
**Why this shape**: tenant isolation, failure isolation, filters, hydration order and the missing-extra path are the five AC6/S7 behaviours; the fake renderer keeps the suite runnable without ai-parrot.

### FILL IN checklist
- [ ] `test_a2ui_export.py::test_published_only_and_uid_filter` — bounded by AC6.
- [ ] `test_a2ui_export.py::test_hydrates_from_storage_first` — storage stub; bounded by S7.
- [ ] `test_a2ui_export.py::test_real_a2ui_renderer` — bounded by AC6.

---

## Acceptance Criteria

- [ ] `export_tenant` hydrates from storage, never yields another tenant's form, isolates failures as `error` rows (AC6).
- [ ] `dialect="json_schema"` works through `JsonSchemaRenderer`; missing extra → `RuntimeError` mentioning `ai-parrot`.
- [ ] Module imports without ai-parrot (no top-level `parrot.` import).
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/services/test_a2ui_export.py -v`; `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/services/test_a2ui_export.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_form_service_registry.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug a2ui-dialect-formbuilder --feature-id FEAT-650`)
2. **Read the spec** §3 M3 and §9 S7
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — `grep -n 'async def load_from_storage\|async def list_forms\|def storage' packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py`
5. **Update status** in the per-spec index → `"in-progress"`, commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src` + Validation Commands
8. **Commit the code** — only the two files
9. **Close** with `scripts/sdd/close_task.sh TASK-4196 a2ui-dialect-formbuilder verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
