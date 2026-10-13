# TASK-4195: `GET /forms` — `dialect` descriptor key, `?dialect=a2ui` manifest, `include=surface`

**Feature**: FEAT-650 — A2UI dialect for parrot-formdesigner
**Spec**: `sdd/specs/a2ui-dialect-formbuilder.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4194
**Assigned-to**: unassigned

---

## Context

Spec §2 wire shapes + §3 M2 (G2, codex S8). `list_forms`
(`api/handlers.py:724-826`) merges in-memory `FormSchema`s with storage
summary rows into descriptors. This task adds: `"dialect"` for in-memory
entries only (resolved §8 — DB-only rows omit the key); with `?dialect=a2ui`
a per-entry `surface_url` manifest (no rendering); with
`?dialect=a2ui&include=surface` the inline envelope + warnings, bounded by
`A2UI_LIST_MAX` (400 beyond, pointing at `POST /forms/export`). Depends on
TASK-4194 only because both edit `handlers.py`.

---

## Scope

- In `list_forms`: add `"dialect": form.dialect.value` to in-memory descriptors (both the `?slug=` branch and the merge loop).
- Parse `?dialect=` with `FormDialect` (400 on unknown); when `A2UI`: 415 if `get_renderer("a2ui")` is None; add `surface_url` per descriptor; with `include=surface`: enforce `A2UI_LIST_MAX`, render each form (`registry.get()` for DB-only rows) via `render_a2ui_schema` and add `surface` + `warnings`.
- Tests in `tests/unit/api/test_list_forms_dialect.py`.

**NOT in scope**: pagination (none exists today), `GET /forms/{uid}`, export endpoint (TASK-4197).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `list_forms` enrichment |
| `packages/parrot-formdesigner/tests/unit/api/test_list_forms_dialect.py` | CREATE | descriptor / manifest / inline / cap tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.api.dialect import A2UI_LIST_MAX, DialectError, render_a2ui_schema   # TASK-4192 (A2UI_LIST_MAX env FORMDESIGNER_A2UI_LIST_MAX, default 50)
from parrot_formdesigner.api.render import get_renderer, supported_formats                     # api/render.py:104, 109
from parrot_formdesigner.core import FormDialect                                                # TASK-4191
from parrot_formdesigner.api._utils import _loc_to_str                                          # api/_utils.py:37 (handlers.py:31)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py — FormAPIHandler.list_forms (line 724)
#   741: tenant = self._get_tenant(request); 742: slug = request.query.get("slug")
#   748-762: ?slug branch builds ONE descriptor dict {"form_uid","form_id","title","description","version","source":"memory","created_at"}
#   764-776: in_memory = await self.registry.list_forms(tenant=tenant); descriptors[form.form_uid] = {...same keys...}
#   777-823: storage rows merged (source "db"); DB-only rows have NO FormSchema in hand
#   825: forms = sorted(descriptors.values(), key=lambda d: d["form_id"] or "")      ← anchor
#   826: return JSONResponse({"forms": forms})
#   prefix for URLs: request.app.get("_form_prefix", "") (used by create_form at line 1181) → f"{prefix}/{tenant}/forms/{form_uid}"
# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:
    async def get(self, form_uid: uuid.UUID, *, tenant=None) -> FormSchema | None     # line 976 — read-through from storage on miss
    async def list_forms(self, *, tenant=None) -> list[FormSchema]                     # line 1102
    @property storage -> FormStorage | None                                            # line 1389
```

### Does NOT Exist
- ~~`dialect` on DB-only descriptors~~ — resolved §8: the key is omitted; do NOT call `registry.get()` just to read it.
- ~~pagination parameters on `GET /forms`~~ — none; the cap is `A2UI_LIST_MAX` + 400.
- ~~`?include=surface` without `?dialect=a2ui`~~ — ignored (no error, no surface).
- ~~`FormStorage.list_forms()` returning schemas~~ — summary dicts only (`registry.py:130`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/api/test_list_forms_dialect.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py#FormRegistry",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/_utils.py#_loc_to_str"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `?dialect=a2ui` alone performs **zero** renders (S8) — test asserts `render_a2ui_schema` is not called (monkeypatch).
- Inline rendering isolates per-form failures: a render exception → `"surface": None, "warnings": ["render_failed: <exc>"]`, never a 500 for the whole list.
- Keep the two existing descriptor builders intact; add keys, do not reorder.

---

## Implementation Blueprint

### Steps (in order)
1. Add `"dialect": form.dialect.value` in the `?slug` descriptor and the in-memory loop descriptor — *why*: in-memory entries have the `FormSchema` in hand.
2. Parse `?dialect=` once at the top of `list_forms` (after `tenant`) into `want_a2ui: bool`, 400/415 early — *why*: a bad value must not do the merge work.
3. After the `forms = sorted(...)` line, enrich when `want_a2ui` — *why*: the manifest/inline step is a post-processing pass over finished descriptors.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — parse)
```python
# occurrences: 1 (verified: grep -c '        slug = request.query.get("slug")' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# AFTER — insert below `        slug = request.query.get("slug")` in list_forms (verified: api/handlers.py:742)
        # FEAT-650 — ?dialect=a2ui → manifest (surface_url); &include=surface → inline envelopes (capped)
        raw_dialect = request.query.get("dialect")
        want_a2ui = False
        if raw_dialect is not None:
            try:
                want_a2ui = FormDialect(raw_dialect) is FormDialect.A2UI
            except ValueError:
                return JSONResponse({"error": f"unknown dialect {raw_dialect!r}", "supported": [d.value for d in FormDialect]}, status=400)
            if want_a2ui and get_renderer("a2ui") is None:
                return JSONResponse({"supported": supported_formats()}, status=415)
        include_surface = want_a2ui and request.query.get("include") == "surface"
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — descriptors)
```python
# occurrences: 2 (verified: grep -c '                "source": "memory",' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# FILL IN: disambiguate — both occurrences are in list_forms: the ?slug branch (line ~759, inside `"forms": [ { ... } ]`) and
#          the in-memory loop (line ~774, inside `descriptors[form.form_uid] = { ... }`). In BOTH dicts add, right after
#          `"source": "memory",`:
                "dialect": form.dialect.value,
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — enrichment)
```python
# occurrences: 1 (verified: grep -c '        forms = sorted(descriptors.values(), key=lambda d: d\["form_id"\] or "")' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# AFTER — insert below `        forms = sorted(descriptors.values(), key=lambda d: d["form_id"] or "")` (verified: api/handlers.py:825)
        if want_a2ui:
            prefix = request.app.get("_form_prefix", "")
            if include_surface and len(forms) > A2UI_LIST_MAX:
                return JSONResponse(
                    {"error": "too many forms for inline a2ui; use POST /forms/export", "max": A2UI_LIST_MAX}, status=400
                )
            for d in forms:
                d["surface_url"] = f"{prefix}/{tenant}/forms/{d['form_uid']}/schema?dialect=a2ui"
                if not include_surface:
                    continue
                try:
                    form = await self.registry.get(d["form_uid"], tenant=tenant)
                    envelopes, _rendered, warnings = await render_a2ui_schema(form, locale=request.query.get("locale", "en"))
                    d["surface"], d["warnings"] = envelopes[0], warnings
                except Exception as exc:  # noqa: BLE001 — one bad form must not 500 the list
                    self.logger.warning("list_forms: a2ui render failed for %s: %s", d["form_uid"], exc)
                    d["surface"], d["warnings"] = None, [f"render_failed: {exc}"]
```
**Why this shape**: manifest-by-default is codex S8; the cap check runs before any render so the 400 is cheap; `registry.get()` read-through (`registry.py:976`) hydrates DB-only rows only when a surface was explicitly requested. Also extend `list_forms`' docstring with the three query params. Import `A2UI_LIST_MAX`, `render_a2ui_schema`, `get_renderer`, `supported_formats` next to the TASK-4194 import line (`get_renderer`/`supported_formats` may already be imported — check `grep -n 'from .render import' handlers.py`).

### `packages/parrot-formdesigner/tests/unit/api/test_list_forms_dialect.py` (CREATE)
```python
"""GET /forms dialect enrichment — FEAT-650 TASK-4195."""

from __future__ import annotations

import pytest

# FILL IN: reuse the app/client fixture approach of tests/unit/api/test_get_schema_dialect.py (TASK-4194); register two
#          forms (one dialect="a2ui") — bounded by that file's wiring


async def test_descriptor_carries_dialect_for_memory_entries(client):
    resp = await client.get("/api/v1/navigator/forms")
    forms = {f["form_id"]: f for f in (await resp.json())["forms"]}
    # FILL IN: assert forms["f1"]["dialect"] == "json_schema" and forms["f2"]["dialect"] == "a2ui"; "surface_url" not in forms["f1"] — bounded by G2


async def test_manifest_does_not_render(client, monkeypatch):
    pytest.importorskip("parrot.outputs.a2ui")
    calls = []
    import parrot_formdesigner.api.handlers as h
    monkeypatch.setattr(h, "render_a2ui_schema", lambda *a, **k: calls.append(1))
    resp = await client.get("/api/v1/navigator/forms?dialect=a2ui")
    body = await resp.json()
    assert all(f["surface_url"].endswith("/schema?dialect=a2ui") for f in body["forms"]) and calls == []


async def test_include_surface_inlines_envelopes(client):
    pytest.importorskip("parrot.outputs.a2ui")
    # FILL IN: ?dialect=a2ui&include=surface → every entry has "surface"["createSurface"] and "warnings" list — bounded by §2 wire shape


async def test_cap_returns_400(client, monkeypatch):
    pytest.importorskip("parrot.outputs.a2ui")
    import parrot_formdesigner.api.handlers as h
    monkeypatch.setattr(h, "A2UI_LIST_MAX", 1)
    resp = await client.get("/api/v1/navigator/forms?dialect=a2ui&include=surface")
    assert resp.status == 400 and (await resp.json())["max"] == 1


async def test_unknown_dialect_400_and_missing_renderer_415(client):
    # FILL IN: ?dialect=xml → 400; with _RENDERERS cleared → ?dialect=a2ui → 415 — bounded by AC3
```
**Why this shape**: each S8 decision (manifest, inline, cap) and the resolved §8 rule (DB-only rows omit the key) is asserted; the "no render on manifest" test is the one that guards the cost promise.

### FILL IN checklist
- [ ] `handlers.py` — `"dialect"` key in both `"source": "memory"` dicts (ambiguous anchor, 2 occurrences — quote context); bounded by §2.
- [ ] `test_list_forms_dialect.py` — fixtures + `FILL IN` bodies; bounded by G2/AC3.

---

## Acceptance Criteria

- [ ] Memory descriptors carry `dialect`; DB-only descriptors do not (AC-resolved §8).
- [ ] `?dialect=a2ui` adds `surface_url` without rendering; `include=surface` inlines envelopes; > `A2UI_LIST_MAX` → 400 with `max`.
- [ ] 400 on unknown dialect, 415 without the renderer.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/api/test_list_forms_dialect.py -v`; existing `test_api_feat300.py` list tests still pass.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_list_forms_dialect.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_api_feat300.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_get_schema_dialect.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug a2ui-dialect-formbuilder --feature-id FEAT-650`)
2. **Read the spec** §2 wire shapes (`GET /forms`) and §9 S8
3. **Check dependencies** — TASK-4194 `"done"`
4. **Verify the Codebase Contract** — `grep -n '"source": "memory",\|forms = sorted(descriptors\|slug = request.query.get("slug")' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
5. **Update status** in the per-spec index → `"in-progress"`, commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src` + Validation Commands
8. **Commit the code** — only the two files
9. **Close** with `scripts/sdd/close_task.sh TASK-4195 a2ui-dialect-formbuilder verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
