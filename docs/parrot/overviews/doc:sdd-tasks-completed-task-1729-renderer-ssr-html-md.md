---
type: Wiki Overview
title: 'TASK-1729: SSR-HTML renderer'
id: doc:sdd-tasks-completed-task-1729-renderer-ssr-html-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements the **ssr-html renderer** of **Module 5** (spec §3): the reference'
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.outputs.a2ui
  rel: mentions
- concept: mod:parrot.outputs.a2ui_renderers
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
---

# TASK-1729: SSR-HTML renderer

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1723, TASK-1724, TASK-1728
**Assigned-to**: unassigned

---

## Context

Implements the **ssr-html renderer** of **Module 5** (spec §3): the reference
static renderer that turns a validated `CreateSurface` envelope into a single
**self-contained, baked HTML document**. It is the backbone of static delivery
(G5) — the PDF renderer (TASK-1732) rasterizes its output, and email delivery
attaches it directly.

This is a SATELLITE task: the renderer class lives in `ai-parrot-visualizations`
under `parrot/outputs/a2ui_renderers/`, registered into the core registry
(TASK-1723) via `register_a2ui_renderer` and resolved through the core→satellite
`importlib` namespace dispatch. It must render **both** native Parrot catalog
components **and** lowered Basic Catalog trees (G4 — lowering guarantees no
native-only islands, so a Basic tree is always available as input).

---

## Scope

- Implement the SSR-HTML renderer in
  `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py`:
  - Subclass the core `AbstractA2UIRenderer` (TASK-1723) — **never** the legacy
    `BaseRenderer` (contains the `exec()` sink, see contract).
  - Register via `register_a2ui_renderer` with capabilities:
    `interactive=False`, `supports_actions=False`, `supports_updates=False`,
    `output="text/html"`.
  - Accept native component trees AND lowered Basic Catalog trees.
  - **Always bake** (static renderer): call the TASK-1728 bake helper so the
    document contains zero live JSON Pointer bindings.
  - **Self-contained output**: one HTML document, all CSS inline, no external
    CDN/script/stylesheet/font references (contrast: legacy
    `formats/echarts.py:245` loads ECharts from jsdelivr — forbidden here).
  - **HTML-escape every data value** interpolated into markup: script injection
    from envelope data must be impossible (dedicated acceptance test). Data is
    data — never interpreted as HTML/JS.
  - `requires_actions` components (e.g. Form): degrade per capabilities (G6/D9) —
    if `DeepLink`s are provided on the artifact, render each action as a plain
    deep-link anchor; with no session context, render with actions stripped plus
    a visible notice (spec §7 gotcha). Never emit live action wiring
    (`supports_actions=False`).
  - Return a `RenderedArtifact` (`mime_type="text/html"`, `surface` = renderer
    name).
- Create the satellite package dir `a2ui_renderers/` (see packaging note in
  Implementation Notes — verified layout differs from naive assumptions).
- Wire the renderer name into the core registry's known-renderers table if
  TASK-1723 uses one (verify the merged code).
- Write unit tests + the integration test `test_e2e_tool_envelope_to_html`
  (spec §4): tool builder → validate → SSR-HTML render → self-contained
  document, no script injection from data.

**NOT in scope**:
- PDF rasterization of the HTML (TASK-1732).
- Adaptive Cards / folium / echarts renderers (TASK-1730/1731).
- Bake helper internals / `RenderedArtifact` model (TASK-1728).
- Deep-link minting (`DeepLinkService`, Module 8) — this task only *renders*
  `DeepLink` objects already attached to the render request/artifact.
- Delivery (`send_notification`, Module 7).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/__init__.py` | CREATE | Satellite-owned regular package init (see packaging note) |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py` | CREATE | SSR-HTML renderer class + registration |
| `packages/ai-parrot-visualizations/pyproject.toml` | MODIFY | Ensure `a2ui` extra exists (stdlib-only renderer; extra may carry only `jsonpointer` from TASK-1728) |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_ssr_html.py` | CREATE | Unit tests: escaping, self-containment, baking, degradation |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_e2e_ssr_html.py` | CREATE | `test_e2e_tool_envelope_to_html` integration test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verified references from the actual codebase (re-checked 2026-07-10).
> Do NOT invent imports/attributes not listed here — `grep`/`read` first.

### Verified Packaging Layout (checked 2026-07-10 — read carefully)
- Satellite `packages/ai-parrot-visualizations/src/parrot/` has **NO
  `__init__.py`** at `parrot/`, `parrot/outputs/`, or `parrot/outputs/formats/`
  levels (PEP 420 namespace portions).
- Core provides `parrot/outputs/__init__.py` and `parrot/outputs/formats/__init__.py`
  and both call `pkgutil.extend_path` (`outputs/__init__.py:23-24`,
  `formats/__init__.py:1-2`) — that is how satellite dirs merge under them.
- The ONLY satellite dirs with an `__init__.py` are satellite-owned leaf packages:
  `formats/assets/`, `formats/generators/`, `formats/mixins/`.
- `a2ui_renderers/` exists ONLY in the satellite (no core counterpart) → mirror
  the satellite-owned leaf-package pattern: give it a regular `__init__.py`.
  Do NOT add `__init__.py` at `src/parrot/` or `src/parrot/outputs/` level.

### Verified Signatures / Anchors
```python
# LEGACY — FORBIDDEN base class. packages/ai-parrot/src/parrot/outputs/formats/base.py
class BaseRenderer(ABC):            # :54
    def execute_code(...)           # :125 — contains `exec(code, namespace, locals_dict)` (:163)
# This is the exec() sink FEAT-273 exists to kill (G1). A2UI renderers NEVER subclass it.

# Forbidden external-CDN precedent (do NOT copy):
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/echarts.py:245
#   <script src="https://cdn.jsdelivr.net/npm/echarts@.../echarts.min.js">

# Dispatch pattern the core registry copies (TASK-1723):
# packages/ai-parrot/src/parrot/embeddings/registry.py
#   importlib.import_module(f"parrot.embeddings.{model_type}")
#   anchor: `raise ImportError(f"Cannot import embedding module '{module_path}': {exc}")`
# → A2UI: importlib.import_module(f"parrot.outputs.a2ui_renderers.{name}")
```

### Interfaces created by dependency tasks (spec §2 sketch — verify against merged code)
```python
# parrot/outputs/a2ui/renderers/__init__.py (TASK-1723, core)
def register_a2ui_renderer(name: str, capabilities: RendererCapabilities): ...
class AbstractA2UIRenderer(ABC):
    capabilities: RendererCapabilities
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact | str: ...

class RendererCapabilities(BaseModel):
    interactive: bool
    supports_actions: bool
    supports_updates: bool
    output: str        # mime type | "live"

# parrot/outputs/a2ui/artifacts.py (TASK-1728, core)
class RenderedArtifact(BaseModel): ...   # mime_type, content XOR path, deep_links, ...
class DeepLink(BaseModel): ...           # action_label, url, token_id, expires_at
```

### Does NOT Exist
- ~~`packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/`~~ —
  does not exist on `dev`; THIS task creates it.
- ~~`parrot.outputs.formats.register_renderer` for A2UI~~ — the legacy registry
  (`formats/__init__.py:47/:62`) is a different, deprecated system; A2UI uses
  `register_a2ui_renderer` from TASK-1723 only.
- ~~A tests/ tree in ai-parrot-visualizations~~ — the package has NO `tests/`
  directory today; create it (TASK-1728 may have created it first — check).
- ~~Any HTML-templating dep guaranteed in the `a2ui` extra~~ — keep the renderer
  stdlib-only (`html.escape`, string templates); do not add jinja2 to the extra
  without spec grounds.

---

## Implementation Notes

### Key Constraints
- **G1 is absolute**: no `exec`/`eval`; no LLM-generated code path; the envelope
  is data, the renderer is a pure function of it.
- Escaping: every string sourced from envelope/data model goes through
  `html.escape` (attribute-safe variant where needed). The injection test must
  feed `<script>`/`onerror=`-style payloads through *data values* and assert they
  appear only escaped.
- Self-containment check is testable: assert no `http(s)://` in `src=`/`href=`
  attributes except the deep-link anchors' own URLs.
- Deterministic output: same envelope → identical document (no timestamps/uuids
  in markup except what the envelope carries).
- Native + lowered: for Parrot custom components, prefer their native HTML
  treatment where you implement one, else render their `lower()`ed Basic tree —
  the Basic-tree walker is the mandatory baseline covering all nine v1 components.
- Async `render`; Pydantic v2; Google-style docstrings; module logger, no prints.

### References in Codebase
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py`
  — precedent for building a full self-contained HTML document in the satellite
  (`_ECHARTS_JS_PATH` :106 shows vendored-asset inlining; you do NOT need JS here).
- `packages/ai-parrot/src/parrot/embeddings/registry.py` — dispatch/ImportError shape.
- Spec §4 integration test row `test_e2e_tool_envelope_to_html`.

---

## Acceptance Criteria

- [ ] Renderer registered as `ssr_html` with capabilities `interactive=False`,
      `supports_actions=False`, `supports_updates=False`, `output="text/html"`
- [ ] Renders native components AND lowered Basic trees; output is one
      self-contained HTML document (no external CDN/script/style refs)
- [ ] Output is baked: zero live JSON Pointer bindings (uses TASK-1728 helper)
- [ ] Script-injection test passes: hostile data values render escaped, never executed
- [ ] `requires_actions` components degrade to deep-link anchors or stripped-with-notice
- [ ] Returns `RenderedArtifact` with `mime_type="text/html"`
- [ ] All tests pass: `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_ssr_html.py packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_e2e_ssr_html.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers`
- [ ] No exec/eval: `grep -rn "exec(\|eval(" packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers` returns nothing
- [ ] `AbstractA2UIRenderer` is the base class; `BaseRenderer` is never imported

---

## Test Specification

> Minimal scaffold — names and intent only; the agent fills in bodies.

```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_ssr_html.py
class TestSSRHTMLRenderer:
    def test_capabilities_declared(self):
        """Capabilities are interactive=False, supports_actions=False, output='text/html'."""
        ...

    async def test_renders_lowered_basic_tree(self):
        """A lowered Basic Catalog tree renders to a complete HTML document."""
        ...

    async def test_output_is_self_contained(self):
        """No external src/href (CDN, fonts, stylesheets) appears in the document."""
        ...

    async def test_data_values_are_escaped_no_script_injection(self):
        """<script>/attribute-injection payloads placed in DATA VALUES appear only
        HTML-escaped in the output — injection from data is impossible."""
        ...

    async def test_output_has_zero_live_bindings(self):
        """Rendered document contains no unresolved JSON Pointer binding syntax."""
        ...

    async def test_requires_actions_degrades_to_deep_link_or_notice(self):
        """Form-like components render as deep-link anchors when DeepLinks are
        provided, else actions are stripped with a visible notice."""
        ...


# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_e2e_ssr_html.py
async def test_e2e_tool_envelope_to_html():
    """Spec §4: tool builder → catalog validate → SSR-HTML render →
    self-contained document, no script injection from data."""
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index (`sdd/tasks/index/`) → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1729-renderer-ssr-html.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Notes**: Created the satellite `a2ui_renderers/` package (regular `__init__.py`) and
`SSRHTMLRenderer` subclassing the core `AbstractA2UIRenderer` (never `BaseRenderer`),
registered as `ssr_html` with capabilities interactive/supports_actions/supports_updates
=False, output="text/html". `render()` always bakes (via `bake_envelope` → zero live
bindings), lowers each catalog component to its Basic tree via the registry, and walks
the Basic tree to escaped, self-contained HTML (all CSS inline). Every data value goes
through `html.escape`; images with external URLs are emitted as a `data-image-url` data
attribute (never a loading `src`) to preserve self-containment. Form-like components
degrade to their lowered "not available" notice; when `DeepLink`s are supplied they
render as anchors (the only external hrefs). 8 tests pass (incl. e2e
tool→validate→render, script-injection, self-containment, zero-bindings); ruff clean;
no exec/eval.

**Deviations from spec**: `render()` adds an optional `deep_links` keyword beyond the
ABC's `(envelope, *, bake=True)` signature so degraded actions can be rendered as
anchors (the task requires rendering DeepLinks "already attached to the render
request"); this is an additive optional param, ABC-compatible. Viz tests run with
`--import-mode=importlib` (shared `tests` package name, per TASK-1728 note).
