# TASK-1889: Render request models + dataset decoding (3 transports, 50 MB cap)

**Feature**: FEAT-327 — Infographic Render Endpoint — Deterministic Render-as-a-Service
**Spec**: `sdd/specs/infographic-render-endpoint.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1888
**Assigned-to**: unassigned

---

## Context

Module 2 of FEAT-327. The endpoint accepts datasets three ways (resolved decisions): inline
JSON `records`, pandas `split` orientation, and multipart **Parquet/CSV** parts (parquet
preserves dtypes via `pyarrow`). This task builds the Pydantic request/response/job models and
the decoding layer with the **50 MB total body cap** (configurable) — the render route
(TASK-1890) consumes them.

---

## Scope

- Implement in ai-parrot-server (new sibling module recommended, e.g.
  `packages/ai-parrot-server/src/parrot/handlers/infographic_render.py`, imported by the
  handler): `InlineDataset`, `RenderRequest` (incl. `public: bool = False`,
  `async` alias field, `persist`, attribution, `marker_id`, embedded `SectionDescriptor` —
  IMPORTED, never redefined), `RenderResponse`, `RenderJob` — shapes per spec §2 Data Models,
  all `extra="forbid"`.
- Decoding: `records`/`split` → `pd.DataFrame`; multipart part named `dataset:<name>` with
  parquet content-type → `pyarrow` → DataFrame; CSV part → pandas. Decode CPU-bound work via
  `loop.run_in_executor`.
- **50 MB total cap** (config key per existing server conventions; default 50 MB) enforced at
  the transport level BEFORE buffering (aiohttp `client_max_size` for the app / streamed
  multipart size accounting) → `413`. Malformed part → `400` naming the part.
- Unit tests (no HTTP server needed beyond aiohttp test utilities for multipart parsing).

**NOT in scope**: the route/dispatch itself (TASK-1890), jobs (TASK-1891), pyproject changes
(TASK-1892 declares `pyarrow`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/infographic_render.py` | CREATE | Models + decoding + cap enforcement helpers |
| `packages/ai-parrot-server/tests/.../test_infographic_render_models.py` | CREATE | Unit tests (verify the server package's actual test layout first) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools import SectionDescriptor    # lazy export, tools/__init__.py:245,266
import pyarrow                                # 25.0.0 importable; DECLARED by TASK-1892
import pandas as pd
from aiohttp import web                       # used throughout handlers/infographic.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/infographic_sections.py
class SectionDescriptor(BaseModel): ...       # line 68 — embed by import in RenderRequest

# packages/ai-parrot-server/src/parrot/handlers/infographic.py — style reference
# (Pydantic ValidationError already imported/handled there: `from pydantic import ValidationError`)
```

### Does NOT Exist
- ~~`RenderRequest` / `RenderResponse` / `RenderJob` / `InlineDataset`~~ — created HERE.
- ~~`handlers/infographic_render.py`~~ — created HERE.
- ~~a server-side copy of `SectionDescriptor`~~ — FORBIDDEN; import from `parrot.tools`.
- ~~an existing body-size config key for infographics~~ — none found; create one following
  the server's config conventions `(verify how handlers read config before inventing the key)`.
- ~~server test layout assumption~~ — `packages/ai-parrot-server/tests/` structure NOT yet
  verified `(check before creating the test file path)`.

---

## Implementation Notes

### Key Constraints
- `async` is a Python keyword: model field `async_` with `Field(alias="async")` and
  `populate_by_name=True`.
- Parquet decode: `pyarrow.parquet` or `pd.read_parquet(BytesIO, engine="pyarrow")` — either
  is fine; dtype preservation is what the test pins.
- Multipart contract: one JSON part named `request` (the `RenderRequest`), dataset parts named
  `dataset:<name>`; a `datasets` entry with value `None` in the JSON means "hydrated from the
  part". Reject a request whose descriptor references a dataset neither inline nor as a part
  (that surfaces later as a 422 from the gate — but a missing PART named in `datasets` is a
  400 here).
- NaN/Inf policy lives downstream (FEAT-326 splice serializer) — decoding must NOT silently
  drop or coerce them.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/infographic.py` — model/error-handling style
- `sdd/specs/infographic-render-endpoint.spec.md` §2 Data Models — exact field list

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass (`pytest` on the created test module)
- [ ] No linting errors (`ruff check` on the new module)
- [ ] `records` and `split` decode to expected DataFrames; parquet round-trips dtypes
  (datetime, categorical); CSV decodes
- [ ] Total body cap (default 50 MB, configurable) → 413 pre-buffering; malformed part →
  400 naming the part
- [ ] `RenderRequest` rejects extra fields; `async` alias works; `SectionDescriptor` is the
  imported FEAT-326 model
- [ ] CPU-bound decode runs in an executor (asserted via test or code review note)

---

## Test Specification

```python
# test_infographic_render_models.py
class TestRenderRequestModel:
    def test_extra_fields_forbidden(self): ...
    def test_async_alias(self): ...
    def test_descriptor_is_feat326_model(self): ...

class TestDatasetDecoding:
    async def test_records_and_split(self): ...
    async def test_parquet_part_preserves_dtypes(self): ...
    async def test_csv_part(self): ...
    async def test_missing_declared_part_400(self): ...
    async def test_malformed_parquet_400_names_part(self): ...
    async def test_body_cap_413(self): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** (TASK-1888 in `completed/`); 3. **Verify the
Codebase Contract** (server test layout + config conventions are marked unverified);
4. **Update status** in `sdd/tasks/index/infographic-render-endpoint.json` → `"in-progress"`;
5. **Implement**; 6. **Verify criteria**; 7. **Move file to completed/**;
8. **Update index** → `"done"`; 9. **Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
