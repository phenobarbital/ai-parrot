# TASK-1892: pyarrow dependency declaration, e2e integration tests, docs

**Feature**: FEAT-327 — Infographic Render Endpoint — Deterministic Render-as-a-Service
**Spec**: `sdd/specs/infographic-render-endpoint.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1888, TASK-1889, TASK-1890, TASK-1891
**Assigned-to**: unassigned

---

## Context

Module 5 of FEAT-327 — closes the feature: declare `pyarrow` as a direct dependency (resolved
decision: currently importable but must be non-transitive), prove the whole endpoint end to
end (three transports, negotiation, async round-trip, error taxonomy), and document the API.

---

## Scope

- **Declare `pyarrow>=25.0`** in the `pyproject.toml` of the package that actually imports it
  (TASK-1889 put the decoding in ai-parrot-server — verify and declare there; if the adapter
  or shared code in core also imports it, declare accordingly). Use `uv` to sync/lock per the
  repo's dependency workflow.
- **Integration tests** (spec §4): `test_e2e_render_budget_variance_json` (inline records →
  data-splice render of the budget_variance template fixture from FEAT-326/TASK-1887 → HTML +
  persisted artifact), `test_e2e_render_multipart_parquet` (dtype-bearing parquet part →
  identical output on repeat call), `test_e2e_async_multiworker_poll` (job created by one app
  instance, polled through the shared Redis store), plus the error-taxonomy sweep
  (400/404/413/422) at the HTTP level.
- A dependency test/CI check that `pyarrow` appears in the declared deps
  (`test_pyarrow_declared_dependency`).
- **Docs**: `docs/` page for the render API — request/response examples (JSON + multipart),
  the URL two-behavior rule (`public`/S3-presigned/`url: null`), limits (50 MB), job
  lifecycle (202 → poll → TTL 1 day, watchdog 10 min), determinism guarantee. Match the style
  of `docs/toolkits/infographic_toolkit.md`.

**NOT in scope**: fixing bugs found by e2e beyond small adjustments (note deviations in the
Completion Note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/pyproject.toml` (verify target) | MODIFY | Declare `pyarrow>=25.0` |
| `packages/ai-parrot-server/tests/.../test_infographic_render_e2e.py` | CREATE | e2e tests (verify layout first) |
| `docs/api/infographic_render.md` (or per docs conventions) | CREATE | API documentation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pyarrow                                        # 25.0.0 importable in the venv TODAY —
# but NOT confirmed as a declared dependency anywhere: that is precisely what this task fixes.
```

### Existing Signatures to Use
```python
# Everything this task exercises was created by TASK-1888..1891 — read those modules first:
#   parrot/tools/infographic_sections.py  → AdhocDatasetAdapter (TASK-1888)
#   handlers/infographic_render.py        → RenderRequest/Response/Job + decoding (TASK-1889)
#   handlers/infographic.py               → render dispatch + URL rule (TASK-1890)
#   handlers/render_jobs.py               → Redis job store + watchdog (TASK-1891)

# Reference fixture source (FEAT-326, merged):
#   sdd/artifacts/budget_variance_dashboard_Template.html:106 — splice marker
#   packages/ai-parrot/tests/ — FEAT-326/TASK-1887 e2e fixtures (copy pattern: template into
#   tmp template_dirs; sample CSVs; sqlite+local-overflow ArtifactStore)
```

### Does NOT Exist
- ~~`pyarrow` in any `pyproject.toml`~~ — `(unverified — grep all pyproject.toml files first;
  declare in the package(s) that import it)`.
- ~~`docs/api/` directory~~ — `(unverified — check docs/ layout and follow its conventions;
  docs/toolkits/infographic_toolkit.md is the style reference)`.
- ~~a public docs page for the render endpoint~~ — created HERE.

---

## Implementation Notes

### Key Constraints
- Environment rules: `source .venv/bin/activate` first; dependency changes via `uv`
  (`uv add`/`uv pip install`) — never bare pip.
- e2e tests must not require a live Redis or S3: fakeredis (or injected fake) for jobs;
  sqlite + local-overflow store for artifacts; `PARROT_OVERFLOW_LOCAL_PATH`/`STATIC_DIR`
  pointed at pytest `tmp_path`.
- The determinism e2e compares the SPLICED HTML across two identical calls — artifact
  ids/timestamps/URLs are excluded by design (spec §7).
- Docs include a curl example for both JSON and multipart forms.

### References in Codebase
- `docs/toolkits/infographic_toolkit.md` — documentation style to match
- FEAT-326 e2e tests (TASK-1887 output) — fixture patterns to reuse

---

## Acceptance Criteria

- [ ] `pyarrow>=25.0` declared in the correct `pyproject.toml`; lock/sync updated via `uv`;
  `test_pyarrow_declared_dependency` passes
- [ ] All e2e tests pass: JSON transport, multipart parquet (dtype fidelity + determinism),
  async multi-worker poll, error taxonomy (400/404/413/422)
- [ ] No linting errors on new files (`ruff check`)
- [ ] Docs page created per `docs/` conventions with examples, URL rule, limits, job
  lifecycle
- [ ] Full suite green: `pytest packages/ -v` on the affected test paths

---

## Test Specification

```python
# test_infographic_render_e2e.py
class TestRenderE2E:
    async def test_e2e_render_budget_variance_json(self, render_app, sample_frames): ...
    async def test_e2e_render_multipart_parquet(self, render_app): ...
    async def test_e2e_async_multiworker_poll(self, render_app, fake_redis_jobstore): ...
    async def test_error_taxonomy(self, render_app): ...   # 400 / 404 / 413 / 422

def test_pyarrow_declared_dependency(): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** (TASK-1888..1891 ALL in `completed/`);
3. **Verify the Codebase Contract** (pyproject target + docs layout are marked unverified);
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
