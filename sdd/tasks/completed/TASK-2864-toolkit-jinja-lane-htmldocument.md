# TASK-2864: `render_template` / `render_data_template` emit an `HtmlDocument` surface

**Feature**: FEAT-527 — Infographic → A2UI migration (dual-emit)
**Spec**: `sdd/specs/infographic-a2ui-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2863, TASK-2856
**Assigned-to**: unassigned

---

## Context

Spec §1 G5, §2 Overview step 6, §3 Module 4. The Jinja lane today emits a **synthetic**
title+summary `InfographicResponse` envelope ("Data: key1, key2…") when `emit_a2ui` is on
(`render_template` `:613-630`; `_build_a2ui_envelope_from_layout` descriptor-less branch
`:940-956`). With dual-emit on by default that placeholder would reach every consumer. Replace
it with the real thing: an `HtmlDocument` surface carrying the rendered HTML (inline when
< 50 KB) or the signed artifact URL.

---

## Scope

- Add `InfographicToolkit._build_html_document_envelope(self, *, html: str, html_url: str,
  artifact_id: str, title: str, theme: Optional[str]) -> Optional[Dict[str, Any]]`: calls
  `build_html_document(title=..., html=html if len(html) < _INLINE_THRESHOLD else None,
  src_url=None if inline else html_url, theme=theme, surface_id=artifact_id)` then
  `serialize(envelope)`; same try/except-warning-return-None policy as `_build_a2ui_envelope`
  (`:846-899`).
- `render_template()` (`:524+`): replace the synthetic-blocks branch (`:614-630`) with
  `_build_html_document_envelope(...)`; `title` falls back to `f"Infographic — {template_name}"`
  (the artifact title convention in its docstring `:552`).
- `_build_a2ui_envelope_from_layout()` (`:923+`): in the `layout is None` branch (`:945-956`)
  call `_build_html_document_envelope(...)` instead of the synthetic `InfographicResponse` — this
  needs `html`/`html_url` passed in; extend the method signature with keyword-only
  `html: str = ""`, `html_url: str = ""` and update the single call site (`:754-760`). A supplied
  `SectionDescriptor` with a `layout` keeps today's descriptor-layout envelope untouched (FEAT-326).
- Update the docstrings of both methods and the module docstring tool list (`:181-196`).
- Record the `TemplateEngine` autoescape default in the completion note (spec §8 open question);
  if it is off, enable `autoescape=True` **for the toolkit's engine only** (`:262`), and add a test.
- Tests: `tests/unit/tools/test_infographic_toolkit.py` (extend `render_template`/`render_data_template`
  tests), `tests/tools/test_infographic_toolkit_a2ui_wiring.py`.

**NOT in scope**: `render()` (typed blocks lane, already correct); renderers (TASK-2865);
`InfographicTalk /render` route code (it calls `render_deterministic` → toolkit; no handler change needed — verify and note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | MODIFY | new helper; `render_template`; `_build_a2ui_envelope_from_layout` |
| `packages/ai-parrot/tests/unit/tools/test_infographic_toolkit.py` | MODIFY | HtmlDocument emission tests |
| `packages/ai-parrot/tests/tools/test_infographic_toolkit_a2ui_wiring.py` | MODIFY | root component assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.infographic_toolkit import InfographicToolkit, InfographicRenderResult   # :180, :159
from parrot.outputs.a2ui.builders import build_html_document                              # after TASK-2863
from parrot.outputs.a2ui.serialization import serialize                                    # used at :882 inside _build_a2ui_envelope
from parrot.template.engine import TemplateEngine                                          # infographic_toolkit.py:30
from parrot.tools.infographic_sections import SectionDescriptor                            # tools/infographic_sections.py:80
from parrot.models.infographic import InfographicResponse                                  # models/infographic.py:1027 (still used by render())
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
_INLINE_THRESHOLD   # module constant (50 KB) :81 ; used as `html if len(html) < _INLINE_THRESHOLD else None` :515,:633,:764
self._template_engine = TemplateEngine(template_dirs=template_dirs); self._template_engine.add_templates(templates)  # :260-264
def add_template(self, name: str, source: str) -> None                                     # :330
async def render_template(self, template_name: str, data: Optional[Dict] = None, theme: Optional[str] = None, title: Optional[str] = None) -> InfographicRenderResult  # :524
    html = await self._template_engine.render(template_name, context)                      # (excerpt line 33 of :560-640 block)
    artifact_id, html_url = await self._persist_template(html=html, ...)                   # :1018 def
    if self._emit_a2ui: synthetic_blocks = [{"type":"title",...}, {"type":"summary","content":"Data: ..."}]; a2ui_envelope = self._build_a2ui_envelope(InfographicResponse(...), artifact_id, title=title)  # :614-630 ← REPLACE
    return InfographicRenderResult(artifact_id, html_url, html_inline=html if len(html) < _INLINE_THRESHOLD else None, template_name, theme, data_variables=[], enhanced=False, a2ui_envelope)  # :632-641
async def render_data_template(self, ..., descriptor: Optional["SectionDescriptor"] = None, ...) -> InfographicRenderResult  # :643-647
    if self._emit_a2ui: a2ui_envelope = self._build_a2ui_envelope_from_layout(descriptor, payload, artifact_id, title=title, template_name=template_name)  # :753-760 ← extend call
def _build_a2ui_envelope(self, response, artifact_id, *, title=None) -> Optional[Dict]     # :846-899 (try/except → warning → None)
def _build_a2ui_envelope_from_layout(self, descriptor, payload, artifact_id, *, title=None, template_name="") -> Optional[Dict]  # :923
    layout = getattr(descriptor, "layout", None); surface_id = artifact_id               # :940-942
    if layout is None: blocks = [title, summary "Data: ..."]; return self._build_a2ui_envelope(InfographicResponse(template=template_name, blocks=blocks), artifact_id, title=title)  # :945-956 ← REPLACE
    properties = dict(layout.model_extra or {})                                            # :960 (descriptor path — KEEP)

# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py (after TASK-2863)
def build_html_document(*, title: str, html: str | None = None, src_url: str | None = None, theme: str | None = None,
                        surface_id: str = "html-document", metadata=None) -> CreateSurface
```

### Does NOT Exist
- ~~`InfographicToolkit._build_html_document_envelope`~~ — created here.
- ~~`InfographicRenderResult.html`~~ — use `html_inline` / `html_url`.
- ~~`render_template` receiving typed blocks~~ — the Jinja lane has no blocks (its own comment at `:615-617`).
- ~~a separate handler change for `/render`~~ — `InfographicTalk` reaches this code via `render_deterministic` (`handlers/infographic_render.py:758`); verify it consumes `InfographicRenderResult.a2ui_envelope` transparently.

---

## Implementation Notes

### Pattern to Follow
`_build_a2ui_envelope` (`:846-899`): import inside the method, `try: ... return serialize(envelope)
except Exception: self.logger.warning(..., exc_info=True); return None`.

### Key Constraints
- Surface id is the artifact id verbatim (already `infographic-` prefixed — see `:872-874` comment).
- Never emit both `html` and `srcUrl`; decide by `_INLINE_THRESHOLD` exactly like `html_inline`.
- The descriptor-with-layout branch must be byte-identical to today's output (FEAT-326/420 contract) — add a regression assertion.
- Keep the module importable without the visualizations satellite in tests (existing skip pattern).

### References in Codebase
- `packages/ai-parrot/tests/unit/tools/test_infographic_toolkit.py` — existing `render_template` tests (in-memory templates via `templates={...}`).
- `packages/ai-parrot/src/parrot/template/engine.py` — `TemplateEngine` (check `autoescape`).

---

## Acceptance Criteria

- [ ] `render_template()` envelope root component is `HtmlDocument` with `html` when the document is < 50 KB, else `srcUrl == html_url`; `title` defaults to `Infographic — <template_name>`
- [ ] `render_data_template()` without descriptor → `HtmlDocument`; with a descriptor carrying `layout` → unchanged descriptor-layout envelope
- [ ] Envelope build failure degrades to `a2ui_envelope=None` with a warning (HTML result intact)
- [ ] `TemplateEngine` autoescape status recorded in the completion note (and enforced if it was off)
- [ ] `timeout -s KILL 600 pytest packages/ai-parrot/tests/unit/tools/test_infographic_toolkit.py packages/ai-parrot/tests/tools/test_infographic_toolkit_a2ui_wiring.py -q` green; `ruff check packages/ai-parrot/src/parrot/tools/infographic_toolkit.py`

---

## Test Specification

```python
# tests/unit/tools/test_infographic_toolkit.py (add)
async def test_render_template_emits_htmldocument_inline(toolkit_with_template):
    res = await toolkit_with_template.render_template("hello", data={"title": "Hi"})
    root = res.a2ui_envelope["createSurface"]["components"][0]
    assert root["component"] == "HtmlDocument"
    assert root["html"].startswith("<") and "srcUrl" not in root
    assert res.a2ui_envelope["createSurface"]["surfaceId"] == res.artifact_id

async def test_render_template_large_document_uses_src_url(toolkit_with_big_template):
    res = await toolkit_with_big_template.render_template("big")
    root = res.a2ui_envelope["createSurface"]["components"][0]
    assert root["srcUrl"] == res.html_url and "html" not in root and res.html_inline is None

async def test_render_data_template_descriptor_layout_unchanged(toolkit, descriptor_with_layout, payload):
    before = snapshot  # captured from the pre-change behaviour / golden
    res = await toolkit.render_data_template(..., descriptor=descriptor_with_layout)
    assert res.a2ui_envelope == before
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2863 and TASK-2856 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — line numbers in `infographic_toolkit.py` will have shifted after TASK-2856; re-grep `if self._emit_a2ui`
4. **Update status** in `sdd/tasks/index/infographic-a2ui-migration.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2864-toolkit-jinja-lane-htmldocument.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below (include the autoescape finding)

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-05
**Notes**: Added `_build_html_document_envelope()` (same try/except-warning
policy as `_build_a2ui_envelope`). `render_template()`'s synthetic-blocks
branch replaced with a call to it (`title` defaults to
`f"Infographic — {template_name}"`). `_build_a2ui_envelope_from_layout()`
gained keyword-only `html: str = ""`, `html_url: str = ""`; its `layout is
None` branch now calls `_build_html_document_envelope()` instead of
building a synthetic `InfographicResponse`; the `layout is not None`
descriptor branch is BYTE-IDENTICAL to before (untouched code path,
verified: `test_declared_layout_is_used_verbatim_against_the_payload` /
`test_non_infographic_layout_dispatches_to_build_surface` pass unmodified).
Updated the two now-stale wiring tests in
`test_infographic_toolkit_a2ui_wiring.py` that asserted the old synthetic
`Infographic` root for the layout-less fallback — they now assert an
`HtmlDocument` root with the rendered `html`/`title`.

**Autoescape finding (spec §8 open question)**: `TemplateEngine`'s default
`JinjaConfig.autoescape` is `select_autoescape([...])` — CONDITIONALLY on,
per template NAME extension (`.html`/`.xml`/`.j2`/`.jinja`/`.jinja2`).
Verified: `test_infographic_render_template.py`'s existing
`test_render_template_autoescapes_data` already passed before this task
because its fixture templates are named e.g. `"echo.html.j2"` (recognized
extension). It was effectively OFF for a template registered under a BARE
name (no recognized extension) — the common shape for `templates=`/
`add_template()` in-memory registration, and now the rendered HTML also
reaches the HtmlDocument A2UI surface, not just the artifact. Per the
task's fallback instruction, forced `autoescape=True` UNCONDITIONALLY for
the toolkit's own `TemplateEngine` construction (both the constructor's
`template_dirs`/`templates` branch and `add_template()`'s lazy-engine
branch), via `config=JinjaConfig(autoescape=True)`. Verified this is a
strict improvement with zero regressions: `test_infographic_render_template.py`
(11 tests, uses recognized-extension names) and
`test_infographic_data_splice.py` (12 tests) both pass unmodified.

`InfographicTalk`'s `/render` route: verified it reaches this code via
`render_deterministic` → the toolkit's `render()`/`render_data_template()`
(not `render_template`, the Jinja-only lane) and consumes
`InfographicRenderResult.a2ui_envelope` transparently (no handler-side
shaping) — no handler change needed, per the task's own note.

52/52 targeted tests pass
(`test_infographic_toolkit.py` + `test_infographic_toolkit_a2ui_wiring.py`),
plus 11/11 (`test_infographic_render_template.py`) and 12/12
(`test_infographic_data_splice.py`) unmodified-and-still-green regression
checks. `ruff check infographic_toolkit.py`: 1 pre-existing unrelated
`F401` finding (verified present before this task, TASK-2856's completion
note already noted it).

**Deviations from spec**: none.
