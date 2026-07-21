# TASK-1723: Renderer registry + capabilities (core side)

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1720, TASK-1721
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of the spec (§3, "Renderer registry + capabilities (core side)"). Core ships the renderer *contract* — `RendererCapabilities`, `AbstractA2UIRenderer`, registration and resolution — while ALL concrete renderers live in `ai-parrot-visualizations` behind the `a2ui`/`a2ui-pdf` extras (G8, PEP 420 namespace merge). Resolution follows the established core-registry → `importlib`-over-namespace dispatch used by `EmbeddingRegistry`, with an actionable `ImportError` naming the missing extra when the satellite is not installed.

---

## Scope

- Create `packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py`.
- Implement `RendererCapabilities` (Pydantic v2) per spec §2: `interactive: bool`, `supports_actions: bool`, `supports_updates: bool`, `output: str` (mime type or `"live"`).
- Implement `AbstractA2UIRenderer` ABC per spec §2 New Public Interfaces: class attribute `capabilities: RendererCapabilities` and abstract `async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact | str` (type the return as `Any`/forward-ref `"RenderedArtifact" | str` since `RenderedArtifact` ships in Module 6 — do NOT create it here).
- Implement `register_a2ui_renderer(name, capabilities)` registration (decorator, following the `register_renderer` precedent) populating a core registry dict.
- Implement `get_a2ui_renderer(name)` resolution: if `name` is not yet registered, `importlib.import_module(f"parrot.outputs.a2ui_renderers.{name}")` over the PEP 420 namespace (satellite module registers itself on import); on `ImportError`, raise an actionable error that names the extra `ai-parrot-visualizations[a2ui]`.
- Write unit tests: registration/lookup round-trip with a dummy renderer, capabilities model validation, and `test_renderer_registry_missing_extra` — missing satellite module → ImportError message contains `ai-parrot-visualizations[a2ui]`.

**NOT in scope**:
- Any concrete renderer (ssr_html, folium_map, echarts, adaptive_cards, pdf) — Module 5, satellite package.
- `RenderedArtifact` / baking (Module 6) — the ABC only forward-references it.
- The `a2ui`/`a2ui-pdf` extras in the visualizations `pyproject.toml` — added by the first Module 5 task.
- Capability-based renderer *selection* logic beyond name lookup (renderer choice policy belongs to emission wiring / delivery modules).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py` | CREATE | `RendererCapabilities`, `AbstractA2UIRenderer`, `register_a2ui_renderer`, `get_a2ui_renderer` |
| `packages/ai-parrot/tests/outputs/a2ui/test_renderer_registry.py` | CREATE | Registry round-trip + missing-extra error tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.outputs.a2ui.models import CreateSurface  # created by TASK-1720 — verify exact export names before use
import importlib  # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/embeddings/registry.py:173-181 — the dispatch
# pattern to COPY (verbatim-style, adapted names). Verified anchors:
cls_name = self._supported_embeddings[model_type]
module_path = f"parrot.embeddings.{model_type}"          # :174
try:
    module = importlib.import_module(module_path)        # :176
except ...:
    raise ImportError(
        f"Cannot import embedding module '{module_path}': {exc}"   # :180-181
    )
# A2UI adaptation: module_path = f"parrot.outputs.a2ui_renderers.{name}"
# and the ImportError message must additionally name the pip extra:
# ai-parrot-visualizations[a2ui]

# packages/ai-parrot/src/parrot/outputs/formats/__init__.py:47-60 — decorator
# registration precedent (registry dict + decorator inserting the class):
def register_renderer(mode: OutputMode, system_prompt: Optional[str] = None):
    def decorator(cls):
        RENDERERS[mode] = cls
        ...
        return cls
    return decorator
```

### Does NOT Exist
- ~~`parrot.outputs.a2ui_renderers`~~ (satellite namespace) — does not exist yet; Module 5 creates it in `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/`. `get_a2ui_renderer` must therefore fail with the actionable error TODAY, which is exactly what `test_renderer_registry_missing_extra` asserts.
- ~~`RenderedArtifact`~~ — Module 6 creates it in `parrot/outputs/a2ui/artifacts.py`; use a forward reference / `Any` in the ABC return annotation, do not import it.
- ~~A renderer for `OutputMode.CHART`~~ and other legacy `_MODULE_MAP` gaps — irrelevant here; never extend legacy `BaseRenderer` (`outputs/formats/base.py`) for A2UI.

### Packaging Facts (verified, spec §6)
- Host `parrot/__init__.py` uses `pkgutil.extend_path`; satellites have NO `parrot/__init__.py` (PEP 420 dirs) + `namespaces = true`; viz pyproject uses `[tool.uv.sources] ai-parrot = { workspace = true }`.

---

## Implementation Notes

### Pattern to Follow
Copy the `EmbeddingRegistry._build_model` dispatch shape from `packages/ai-parrot/src/parrot/embeddings/registry.py:153-181`: registry lookup first, then `importlib.import_module` on the computed namespace path, wrapping `ImportError`/`ModuleNotFoundError` in an actionable message. The A2UI version differs in two ways: (1) the module path template is `f"parrot.outputs.a2ui_renderers.{name}"`; (2) the error message must tell the user to `pip install ai-parrot-visualizations[a2ui]` (and mention `a2ui-pdf` for the pdf renderer).

### Key Constraints
- After a successful `import_module`, the satellite module's own `@register_a2ui_renderer` decorator (executed at import time) populates the core registry — `get_a2ui_renderer` then re-reads the registry; if the name is STILL missing after import, raise a clear "module imported but renderer not registered" error.
- `RendererCapabilities` is a required class attribute of every renderer; `register_a2ui_renderer` should validate it is present/valid at registration.
- Async-first: `render` is async in the ABC; no blocking I/O contracts.
- Zero new core deps; one-way import rule (no agents/clients/DatasetManager imports); no `exec(`/`eval(`.
- Google-style docstrings + strict type hints.

### References in Codebase
- `packages/ai-parrot/src/parrot/embeddings/registry.py:153-181` — dispatch pattern to copy.
- `packages/ai-parrot/src/parrot/outputs/formats/__init__.py:47` — decorator registration precedent.
- Spec §3 Module 5 — the renderer names that will resolve through this registry: `ssr_html`, `folium_map`, `echarts`, `adaptive_cards`, `pdf`.

---

## Acceptance Criteria

- [ ] `RendererCapabilities` validates the four fields (`interactive`, `supports_actions`, `supports_updates`, `output`).
- [ ] A dummy renderer registered via `register_a2ui_renderer` in tests resolves through `get_a2ui_renderer` by name.
- [ ] With no satellite installed, `get_a2ui_renderer("ssr_html")` raises `ImportError` whose message contains `ai-parrot-visualizations[a2ui]` (`test_renderer_registry_missing_extra`).
- [ ] `AbstractA2UIRenderer` cannot be instantiated directly (abstract `render`); subclass without `capabilities` is rejected at registration.
- [ ] No new core dependencies; `grep -rn "exec(\|eval(" packages/ai-parrot/src/parrot/outputs/a2ui/` returns nothing.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/test_renderer_registry.py -v` (and full `tests/outputs/a2ui/` still green)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/`
- [ ] Imports work: `from parrot.outputs.a2ui.renderers import AbstractA2UIRenderer, RendererCapabilities, register_a2ui_renderer, get_a2ui_renderer`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass.
> Add more tests as needed.

```python
# packages/ai-parrot/tests/outputs/a2ui/test_renderer_registry.py
import pytest


class TestRendererCapabilities:
    def test_capabilities_model_fields(self):
        """RendererCapabilities validates interactive/supports_actions/supports_updates/output."""
        ...


class TestRendererRegistry:
    def test_register_and_resolve_dummy_renderer(self):
        """A test-registered renderer resolves by name via get_a2ui_renderer."""
        ...

    def test_renderer_registry_missing_extra(self):
        """Unknown renderer with no satellite installed raises ImportError naming ai-parrot-visualizations[a2ui]."""
        ...

    def test_abstract_renderer_not_instantiable(self):
        """AbstractA2UIRenderer with unimplemented render() cannot be instantiated."""
        ...

    def test_registration_requires_capabilities(self):
        """Registering a renderer without a valid capabilities attribute fails."""
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
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1723-a2ui-renderer-registry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Notes**: Created `parrot.outputs.a2ui.renderers` with `RendererCapabilities`
(interactive/supports_actions/supports_updates/output), the `AbstractA2UIRenderer`
ABC (async `render(envelope, *, bake=True) -> Any|str`, forward-refs Module 6's
`RenderedArtifact`), `register_a2ui_renderer(name, capabilities)` decorator, and
`get_a2ui_renderer(name)` which copies the `EmbeddingRegistry` importlib dispatch:
registry lookup → `importlib.import_module("parrot.outputs.a2ui_renderers.{name}")`
→ actionable ImportError naming `ai-parrot-visualizations[a2ui]` (or `[a2ui-pdf]`
for the `pdf` renderer). 35 tests pass (7 new); ruff clean; no exec/eval; no new deps.

**Deviations from spec**: none.
