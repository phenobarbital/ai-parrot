# TASK-3073: Register the `a2ui` render format (guarded seed), lazy package export, optional extra

**Feature**: FEAT-544 — A2UI v1.0 Form Renderer for parrot-formdesigner (full interaction cycle)
**Spec**: `sdd/specs/a2ui-form-output-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3071
**Assigned-to**: unassigned
**Parallel**: true — Touches api/render.py, renderers/__init__.py and pyproject.toml only — no file overlap with TASK-3072 or TASK-3074; can run in a parallel worktree once TASK-3071 is merged.

---

## Context

Spec §3 Module 3. Makes `GET /api/v1/{tenant}/forms/{form_uid}/render/a2ui` work by seeding the renderer registry, exposes `A2UIFormRenderer` from `parrot_formdesigner.renderers` lazily, and adds an `a2ui` optional-extra alias. The seed must be guarded so parrot-formdesigner without the `ai-parrot` extra still seeds the other five renderers.

---

## Scope

- In `api/render.py::_seed_default_renderers`, after the existing five `setdefault`s, add a SEPARATE guarded block:
  ```python
  try:
      from ..renderers.a2ui import A2UIFormRenderer
      _RENDERERS.setdefault("a2ui", A2UIFormRenderer())
  except ImportError:  # ai-parrot extra not installed
      logger.info("render dispatcher: 'a2ui' format unavailable (install parrot-formdesigner[ai-parrot])")
  ```
  Do NOT put the a2ui import in the existing hard-dependency import group (render.py:50-54) — the docstring there says a failure means mis-install; a2ui is the one optional exception. Update the module docstring (render.py:8-15) to list `"a2ui"`.
- Note: `A2UIFormRenderer` itself imports `parrot.*` lazily (TASK-3071), so the `ImportError` may surface on first `render()` instead of at import. Make the seed guard robust: attempt `importlib.util.find_spec("parrot.outputs.a2ui")` first and skip registration when it is `None`.
- In `renderers/__init__.py`: add `"A2UIFormRenderer": ".a2ui"` to `_LAZY_EXPORTS`, add to `__all__` and the `TYPE_CHECKING` import; update the module docstring bullet list.
- In `packages/parrot-formdesigner/pyproject.toml` `[project.optional-dependencies]`: add `a2ui = ["ai-parrot>=1.0.0"]` next to the existing `ai-parrot` extra (alias; same pin).
- Tests: extend `tests/unit/api/test_render_dispatcher.py` (`test_default_seed_includes_a2ui_when_available`, `test_seed_skips_a2ui_when_spec_missing` via monkeypatching `importlib.util.find_spec`) and add `tests/unit/renderers/test_a2ui_export.py` (`from parrot_formdesigner.renderers import A2UIFormRenderer`; in `__all__`).
- Verify end-to-end through the dispatcher: `GET .../render/a2ui` → 200, `Content-Type: application/a2ui+json`, body deserialises (aiohttp test client, same fixture style as test_render_dispatcher.py:28-73).

**NOT in scope**: any change inside renderers/a2ui.py (TASK-3071/3072); handler changes (TASK-3074+); docs (TASK-3078).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` | MODIFY | guarded `a2ui` seed + docstring |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/__init__.py` | MODIFY | lazy export A2UIFormRenderer |
| `packages/parrot-formdesigner/pyproject.toml` | MODIFY | `a2ui` optional extra alias |
| `packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py` | MODIFY | seed tests |
| `packages/parrot-formdesigner/tests/unit/renderers/test_a2ui_export.py` | CREATE | lazy export test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against `dev` @ `213670ef2` (2026-09-10). Use these exact imports,
> class names and signatures. **DO NOT** invent, guess, or assume any import, attribute, or
> method not listed here. If you need something not listed, VERIFY it exists first with `grep`/`read`.

### Verified Imports
```python
from parrot_formdesigner.api.render import _RENDERERS, _seed_default_renderers, register_renderer, get_renderer, supported_formats, handle_render   # packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py:35 / :38 / :63 / :76 / :81 / :101
from parrot_formdesigner.renderers.base import AbstractFormRenderer   # renderers/base.py:57
from parrot_formdesigner.renderers.a2ui import A2UIFormRenderer       # created by TASK-3071
import importlib.util   # find_spec("parrot.outputs.a2ui")
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py
_RENDERERS: dict[str, AbstractFormRenderer] = {}                     # 35
def _seed_default_renderers() -> None:                                # 38-60
    from ..renderers.adaptive_card import AdaptiveCardRenderer        # 50   (hard deps group: 50-54 — do NOT add a2ui here)
    ...
    _RENDERERS.setdefault("html", HTML5Renderer())                    # 56
    _RENDERERS.setdefault("audio", AudioFormRenderer())               # 60   ← add the guarded a2ui block AFTER this line
def register_renderer(format_key: str, renderer: AbstractFormRenderer) -> None   # 63
def supported_formats() -> list[str]                                  # 81  sorted keys
async def handle_render(request) -> web.Response                      # 101 — 415 {"supported": [...]} on unknown format (117-122); renderer.render(form, locale=locale) (146); dict content → json.dumps (98) → web.Response(text=..., content_type=rendered.content_type) (150)
logger = logging.getLogger(__name__)                                  # 31

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/__init__.py
_LAZY_EXPORTS = {"TelegramRenderer": ".telegram"}                     # 19-21
def __getattr__(name: str)                                            # 24-31 (PEP 562)
if TYPE_CHECKING: from .telegram import TelegramRenderer              # 34-35
__all__ = [...]                                                       # 38-44

# packages/parrot-formdesigner/pyproject.toml
[project.optional-dependencies]                                       # 48
ai-parrot = ["ai-parrot>=1.0.0"]                                      # 50-52

# packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py — fixtures: _reset_renderers autouse (41-47), sample_form (50-73), test_default_seed_includes_html_and_adaptive (76)
```

### Does NOT Exist
- ~~`_RENDERERS["a2ui"]` seeded unconditionally~~ — must be guarded; other renderers are hard deps, a2ui is not
- ~~`handle_render` passing `prefilled`/`errors`~~ — it passes only `locale` (render.py:146); do not widen it here
- ~~`register_renderer` returning a value~~ — returns None
- ~~a `parrot_formdesigner.renderers.a2ui` eager import at package import~~ — export MUST go through `_LAZY_EXPORTS`

---

## Implementation Notes

### Pattern to Follow
```python
# renderers/__init__.py:19-21 — lazy export slot
_LAZY_EXPORTS = {"TelegramRenderer": ".telegram", "A2UIFormRenderer": ".a2ui"}
```
- Keep `supported_formats()` output sorted (test `test_supported_formats_sorted` relies on it).
- The dispatcher's `_coerce_body` (render.py:86-98) json-dumps dict content — `RenderedForm.content` from the renderer is already a plain dict from `serialize()`; nothing else needed.

### References in Codebase
- `packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py` — fixture + aiohttp harness to copy

### Key Constraints
- Async-first; Google-style docstrings; strict type hints; Pydantic for any new model; `self.logger = logging.getLogger(__name__)` — never `print`.
- ai-parrot is an OPTIONAL dependency of parrot-formdesigner: every `parrot.*` import in this package must be lazy and guarded (pattern: `renderers/audio.py:151-154`).
- Never hand-write `"version"`; every outbound envelope goes through `serialize()`.
- No `Form` catalog component (spec G6). ai-parrot semantics ride in `metadata.extensions.parrot_*` only.
- Run `pytest` after ANY logic change; run `ruff check` on touched paths; `black` formatting.

---

## Acceptance Criteria

- [ ] `_seed_default_renderers()` registers `"a2ui"` when `parrot.outputs.a2ui` is importable and skips it (INFO log, no exception, other five present) when not.
- [ ] `from parrot_formdesigner.renderers import A2UIFormRenderer` works lazily and the name is in `__all__`; `import parrot_formdesigner.renderers` does not import `parrot.*`.
- [ ] `pip install -e packages/parrot-formdesigner[a2ui]` resolves (extra present in pyproject).
- [ ] aiohttp test: `GET /api/v1/{tenant}/forms/{uid}/render/a2ui` → 200, `Content-Type` starts with `application/a2ui+json`, body deserialises to a `createSurface` envelope; unknown format still 415 with `"a2ui"` in `supported`.
- [ ] `pytest packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py packages/parrot-formdesigner/tests/unit/renderers/test_a2ui_export.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py (additions)
def test_default_seed_includes_a2ui_when_available():
    pytest.importorskip("parrot.outputs.a2ui")
    _seed_default_renderers(); assert "a2ui" in _RENDERERS

def test_seed_skips_a2ui_when_spec_missing(monkeypatch, caplog):
    import importlib.util
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda n, *a: None if n == "parrot.outputs.a2ui" else real(n, *a))
    _seed_default_renderers()
    assert "a2ui" not in _RENDERERS and {"html","adaptive","xml","pdf","audio"} <= set(_RENDERERS)

async def test_render_a2ui_via_dispatcher(aiohttp_client, sample_form): ...   # 200 + media type + deserialize()

# packages/parrot-formdesigner/tests/unit/renderers/test_a2ui_export.py
def test_lazy_export():
    pytest.importorskip("parrot.outputs.a2ui")
    from parrot_formdesigner import renderers
    assert "A2UIFormRenderer" in renderers.__all__ and renderers.A2UIFormRenderer.__name__ == "A2UIFormRenderer"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/a2ui-form-output-renderer.spec.md` (§2 Overview, §3 Module Breakdown, §6 Codebase Contract, §7 mapping table).
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code confirm every import/signature above still exists (`grep`/`read`); update the contract FIRST if anything drifted.
4. **Update status** in `sdd/tasks/index/a2ui-form-output-renderer.json` → `"in-progress"` with your session ID.
5. **Implement** following the scope, contract and notes. Write the tests first (TDD).
6. **Verify** all acceptance criteria; run the listed pytest commands and `ruff check`.
7. **Move this file** to `sdd/tasks/completed/TASK-3073-a2ui-renderer-registration-packaging.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-11
**Notes**: `_seed_default_renderers` now probes
`importlib.util.find_spec("parrot.outputs.a2ui")` first and only imports
`A2UIFormRenderer` + `setdefault("a2ui", ...)` when the spec resolves,
logging one INFO line otherwise — the other five hard-dep renderers seed
unconditionally, unaffected. `renderers/__init__.py` adds
`"A2UIFormRenderer": ".a2ui"` to `_LAZY_EXPORTS`/`__all__`/the
`TYPE_CHECKING` block. `pyproject.toml` gets an `a2ui` optional-extra alias
(same pin as `ai-parrot`). Extended `test_render_dispatcher.py` with the
seed-available/seed-skipped/dispatcher-e2e tests and added
`test_a2ui_export.py` (lazy export + a static AST check that
`renderers/__init__.py` imports no `parrot.*` at module level, same
pattern as TASK-3071's eager-import test). 12 new/extended tests pass;
`ruff check` clean on all 5 touched files.

Verified a pre-existing, unrelated failure
(`test_form_controls_endpoint.py::test_form_controls_payload_shape`) is
present on the same commit *before* any FEAT-544 changes (confirmed via
`git stash`) — out of scope for this task, not touched.

**Post-review addendum (2026-09-11)**: the FEAT-544 `code-reviewer` pass
(cross-checked adversarially with `codex`) found that
`importlib.util.find_spec("parrot.outputs.a2ui")` RAISES
`ModuleNotFoundError` — it does not return `None` — when a parent package
earlier in the dotted chain (here: `parrot` itself) cannot be imported at
all, which is exactly the real "`ai-parrot` extra not installed"
deployment shape. The unguarded `find_spec()` call would have crashed
`setup_form_api()` at app startup instead of gracefully degrading.
Independently reproduced (both "top-level `parrot` entirely absent" and
"`parrot` exists, `a2ui` submodule doesn't" cases) before fixing: wrapped
the probe in `try/except (ImportError, ModuleNotFoundError)` and added
`test_seed_skips_a2ui_when_parent_package_genuinely_absent` (raises from
a monkeypatched `find_spec`, rather than the pre-existing test's
return-`None` monkeypatch, which never exercised the raising path). Fixed
in a follow-up commit on this branch; not a change to this note's
"Deviations from spec" (none) — a bug fix, not a design deviation.
