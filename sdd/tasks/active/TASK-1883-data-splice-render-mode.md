# TASK-1883: Data-splice render mode in InfographicToolkit

**Feature**: FEAT-326 — DataAgent Infographic — Infographic Authoring for Data Agents
**Spec**: `sdd/specs/dataagent-infographic.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1882
**Assigned-to**: unassigned

---

## Context

Module 2 of FEAT-326. The budget_variance template is NOT Jinja: it is a self-contained HTML
dashboard whose client-side JS reads a JSON payload from
`<script type="application/json" id="report-data">`. This task adds a **data-splice** render
mode to `InfographicToolkit` (spec G-4), generalizing `splice_into_template()` from
`sdd/artifacts/daily_report.py`: inject the validated payload into the marker script tag,
leave the template otherwise byte-identical, and persist through the existing artifact path.

---

## Scope

- Implement `InfographicToolkit.render_data_template(template_name, payload, descriptor=None,
  marker_id="report-data", title=None) -> InfographicRenderResult` (spec §2 New Public
  Interfaces).
- Expose it as tool `infographic_render_data_template` following the existing `infographic_*`
  naming and `return_direct` propagation.
- Splice logic: locate `<script type="application/json" id="{marker_id}">` … `</script>`;
  structured error (`InfographicValidationError`) when marker or closing tag is missing.
- JSON serialization safe for pandas/numpy values: coerce numpy scalars/Timestamps; REJECT
  NaN/Infinity loudly (plain `json.dumps` emits invalid JSON for them) — `allow_nan=False`
  plus a coercing `default=`.
- When a `SectionDescriptor` (TASK-1882) is supplied, run the validation gate before splicing.
- Templates for this mode resolve via the existing `template_dirs` registry (resolved
  brainstorm decision — the deployed template dir stays gitignored; tests copy from
  `sdd/artifacts/`).
- Persist via the same `ArtifactStore` path the existing render tools use.
- Unit tests.

**NOT in scope**: the mixin (TASK-1884), recipe publication (TASK-1885), descriptor models
(TASK-1882), e2e fixtures (TASK-1887).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | MODIFY | `render_data_template` + tool exposure |
| `packages/ai-parrot/tests/unit/tools/test_infographic_data_splice.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.infographic_sections import SectionDescriptor  # created by TASK-1882
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicValidationError(Exception):        # line 93; __init__(code, detail) line 114
class InfographicRenderResult(BaseModel): ...       # line 124
class InfographicToolkit(AbstractToolkit):          # line 144
    def __init__(self, *, artifact_store: ArtifactStore,
                 template_dirs: Optional[Any] = None,
                 templates: Optional[Dict[str, str]] = None, ...) -> None:   # line 177
    # self._artifact_store, self._template_engine (lazy TemplateEngine), self.return_direct=True
    async def render_template(self, template_name, data=None, theme=None, title=None): ...
    # ^ study its persistence flow — render_data_template must persist the SAME way.
    def add_template(self, name: str, source: str) -> None: ...

# packages/ai-parrot/src/parrot/storage/artifacts.py
class ArtifactStore:                                # line 27
    async def save_artifact(self, user_id: str, agent_id: str, session_id: str,
                            artifact: Artifact) -> None: ...
# user_id/agent_id/session_id resolution: see infographic_toolkit.py ~line 1540
# ("user_id / agent_id / session_id class attributes" fallback chain).
```

### Reference Code (verbatim from `sdd/artifacts/daily_report.py:185-200`)
```python
def splice_into_template(template_html: str, report_data: dict) -> str:
    start_marker = '<script type="application/json" id="report-data">'
    end_marker = "</script>"
    start_idx = template_html.find(start_marker)
    if start_idx == -1:
        raise ValueError("Could not find the report-data script tag in the template. ...")
    content_start = start_idx + len(start_marker)
    content_end = template_html.find(end_marker, content_start)
    if content_end == -1:
        raise ValueError("Could not find the closing </script> tag after report-data.")
    new_json = json.dumps(report_data)
    return template_html[:content_start] + "\n" + new_json + "\n" + template_html[content_end:]
```

### Does NOT Exist
- ~~data-splice / `report-data` handling anywhere in `infographic_toolkit.py`~~ — zero hits
  today; this task adds it.
- ~~`InfographicToolkit.render_data_template`~~ — created HERE.
- ~~a separate splice template registry~~ — reuse `template_dirs` / `_template_engine`
  loading; do NOT invent a second registry. (The engine is Jinja — for data-splice you need
  the RAW template source, so load the file content without Jinja-rendering it; check
  `parrot/template/engine.py` `TemplateEngine` for a raw-source accessor before hand-rolling
  file reads.)

---

## Implementation Notes

### Key Constraints
- Marker attribute order tolerance: accept `id` placement variations? NO — v1 matches the
  exact marker string with the given `marker_id` interpolated (document this); the reference
  template at `sdd/artifacts/budget_variance_dashboard_Template.html:106` uses
  `<script type="application/json" id="report-data">`.
- Except for the payload swap, output must be byte-identical to the template (test asserts).
- 259 KB-class artifacts exceed `OverflowStore.INLINE_THRESHOLD` (200 KB,
  `parrot/storage/overflow.py:34`) — offload happens automatically; if overflow falls back
  inline (its warning path), surface that in the render result metadata rather than hiding it.
- Follow existing `infographic_*` tool docstring style — the docstring IS the LLM tool
  description.

### References in Codebase
- `parrot/tools/infographic_toolkit.py` — `render_template()` flow (persistence + result shape)
- `packages/ai-parrot/tests/test_infographic_render_template.py` — test style for this toolkit

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/tools/test_infographic_data_splice.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/infographic_toolkit.py`
- [ ] Splice output byte-identical to template except payload
- [ ] Missing marker → `InfographicValidationError` naming the expected marker id
- [ ] NaN in payload → loud error (not silent invalid JSON); numpy scalars coerced
- [ ] Descriptor supplied → validation gate runs BEFORE any splice/persist
- [ ] `InfographicToolkit.__init__` signature unchanged (no breaking API change)

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/tools/test_infographic_data_splice.py
class TestRenderDataTemplate:
    async def test_splices_json_into_marker(self, toolkit, tiny_splice_template): ...
    async def test_template_otherwise_byte_identical(self, ...): ...
    async def test_marker_missing_raises_structured_error(self, ...): ...
    async def test_custom_marker_id(self, ...): ...
    async def test_nan_rejected_numpy_coerced(self, ...): ...
    async def test_descriptor_gate_runs_first(self, ...): ...   # unmet section -> no persist call
    async def test_persists_via_artifact_store(self, ...): ...  # save_artifact invoked
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1882 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/dataagent-infographic.json` → `"in-progress"`
5. **Implement**, 6. **Verify criteria**, 7. **Move file to completed/**, 8. **Update index**,
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
