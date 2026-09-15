# TASK-3149: Register the `teams` format via `setup_form_api` + `handle_render` tenant pass-through, `?with_meta=true`, config-error → 400

**Feature**: FEAT-551 — MS Teams FormDesigner Renderer (Adaptive Card + submit envelope via the Teams bot)
**Spec**: `sdd/specs/msteams-formdesigner-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3147
**Assigned-to**: unassigned
**Parallel**: true — touches `api/render.py`, `api/routes.py` and the dispatcher test only; no overlap with TASK-3148 (`renderers/teams.py`) or TASK-3150 (integrations). Note: FEAT-544 (worktree `feat-FEAT-544-…`) also edits `api/render.py` to register `a2ui` — expect a trivial merge.

---

## Context

Spec §3 Module 3 (codex S1, S7, S12 confirmed). `GET …/forms/{form_uid}/render/{format}` dispatches
through the module-level `_RENDERERS` registry (`render.py:35`). This task makes the Teams card
fetchable under `teams`, but ONLY when a public base URL is configured (unset ⇒ not registered ⇒
the existing 415 answer). `handle_render` today forwards only `locale` (`render.py:145-146`) and
discards `warnings`/`metadata` (`:148-151`); it gains a tenant pass-through for renderers that
declare `accepts_tenant`, an opt-in `?with_meta=true` JSON envelope, and maps
`TeamsRenderConfigError`/`ValueError` to 400.

---

## Scope

- `render.py`: `TEAMS_PUBLIC_URL_ENV`, `register_teams_renderer(...) -> bool`; extend `handle_render` (tenant kwarg, `with_meta`, 400 mapping). Default response path byte-identical.
- `routes.py`: `setup_form_api(..., public_base_url: str | None = None, teams_renderer: AbstractFormRenderer | None = None)`; after `render_module._seed_default_renderers()` (`routes.py:299`) call `register_teams_renderer(public_base_url=public_base_url, api_base_path=base_path, ui_base_path=app.get("_form_prefix", ""), renderer=teams_renderer)`.
- Dispatcher tests (5).

**NOT in scope**: refactoring `_RENDERERS` into app state; renderer internals; bot.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` | MODIFY | registration helper + `handle_render` extensions |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | two kwargs + call |
| `packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py` | MODIFY | 5 new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ..renderers.base import AbstractFormRenderer                                    # render.py:26
from .handlers import extract_form_uid                                               # render.py:27
from .tenant import declared_tenant, enforce_membership_unless_public                # render.py:28
from ..renderers.teams import TeamsFormRenderer, TeamsRenderConfigError, PUBLIC_URL_ENV   # TASK-3147 (import lazily inside register_teams_renderer, like _seed_default_renderers does at :50-54)
from . import render as render_module                                                # routes.py:51
# tests (already imported at test_render_dispatcher.py:7-25)
from parrot_formdesigner.api.render import (_RENDERERS, handle_render, register_renderer, supported_formats, ...)   # :9-16
from parrot_formdesigner.renderers.base import AbstractFormRenderer                  # :24
from parrot_formdesigner.services.registry import FormRegistry                       # :25
```

### Existing Signatures to Use
```python
# api/render.py
_RENDERERS: dict[str, AbstractFormRenderer] = {}                                     # 35
def _seed_default_renderers() -> None                                                # 38-60 (last line: _RENDERERS.setdefault("audio", AudioFormRenderer()) :60)
def register_renderer(format_key: str, renderer: AbstractFormRenderer) -> None       # 63-73
def get_renderer(format_key) ; def supported_formats() -> list[str]                  # 76-78 ; 81-83
def _coerce_body(content: Any) -> bytes | str                                        # 86-98
async def handle_render(request: web.Request) -> web.Response                        # 101-151
    # tenant = declared_tenant(request) :131 ; form = await registry.get(form_uid, tenant=tenant) :132
    # enforce_membership_unless_public(request, form, tenant) :143
    # locale = request.query.get("locale", "en") :145 ; rendered = await renderer.render(form, locale=locale) :146
    # body = _coerce_body(rendered.content) :148 ; web.Response(text=..., content_type=rendered.content_type) :149-151
# api/routes.py
def setup_form_api(app, registry, *, ..., rbac_enforcing: bool = False, alias_registry: "SinkAliasRegistry | None" = None) -> None   # 191-212 (last kwarg :211)
    render_module._seed_default_renderers()                                          # 299
    bp = base_path.rstrip("/") :344 ; tp = f"{bp}/{{tenant}}" :352 ; render route :388-392
# ui/routes.py
app.setdefault("_form_prefix", base_path.rstrip("/"))                                # 169 (set by setup_form_ui; may be absent)
# tests/unit/api/test_render_dispatcher.py
async def _tenant_wrapped_render(request) -> web.Response   # 28-39: request["tenant"] = request.match_info["tenant"]; return await handle_render(request)
@pytest.fixture(autouse=True) def _reset_renderers()        # 41-47 (snapshot/clear/restore _RENDERERS)
@pytest.fixture def sample_form() -> FormSchema             # 50-51
async def test_dispatcher_adaptive_delegates(aiohttp_client, sample_form)   # 175-212 (harness to copy)
# core/schema.py
class RenderWarning(BaseModel) ... .model_dump()             # 650
class RenderedForm: warnings: list[RenderWarning]; metadata: dict | None   # 687-688
```

### Does NOT Exist
- ~~`register_teams_renderer`~~, ~~`TEAMS_PUBLIC_URL_ENV`~~ in render.py — created by THIS task (`PUBLIC_URL_ENV` constant lives in `renderers/teams.py`, TASK-3147; re-export or alias it).
- ~~`handle_render` reading `style`, `prefilled`, `errors` or any query param besides `locale`~~ — only `locale` today.
- ~~`setup_form_api(public_base_url=…, teams_renderer=…)`~~ — kwargs added by THIS task.
- ~~app-scoped renderer registry~~ — `_RENDERERS` stays module-global (spec Non-Goals).
- ~~`RenderedForm.warnings` on the HTTP response~~ — only via the new `?with_meta=true`.

---

## Implementation Notes

### Pattern to Follow
```python
# render.py:38-60 — lazy imports inside the seeding function to keep `import parrot_formdesigner.api` light
def _seed_default_renderers() -> None:
    from ..renderers.adaptive_card import AdaptiveCardRenderer
    ...
```

### Key Constraints
- `register_teams_renderer` returns `False` and logs INFO when no URL is resolvable AND no renderer instance was passed; never raises.
- `with_meta` is truthy only for `"1"`, `"true"`, `"yes"` (case-insensitive).
- 400 mapping catches `ValueError` (TeamsRenderConfigError subclasses it) ONLY around the `renderer.render(...)` call.

---

## Implementation Blueprint

### Steps (in order)
1. Add `register_teams_renderer` after `supported_formats` — *why*: single place that decides "configured ⇒ registered".
2. Extend `handle_render` (tenant kwarg, try/except → 400, `with_meta`) — *why*: spec S12/S7; default path must stay byte-identical.
3. Add the two kwargs to `setup_form_api` and the call after `_seed_default_renderers()` — *why*: app-scoped injection (S1).
4. Tests; run `pytest packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py -q`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` (MODIFY — helper)
```python
# occurrences: 1 (verified: grep -c 'def supported_formats() -> list\[str\]:' api/render.py)
# AFTER — insert below the `supported_formats` function body (ends at render.py:83)
TEAMS_FORMAT_KEY: str = "teams"


def register_teams_renderer(*, public_base_url: str | None = None, api_base_path: str = "/api/v1",
                            ui_base_path: str = "", signing_secret: str | None = None,
                            renderer: AbstractFormRenderer | None = None) -> bool:
    """Register the MS Teams renderer under ``"teams"`` when a public base URL is resolvable (FEAT-551 M3).

    Returns:
        ``True`` when registered; ``False`` (logged at INFO) when neither ``renderer`` nor a public
        base URL (argument or env ``FORMDESIGNER_PUBLIC_URL``) is available — nothing is registered.
    """
    from ..renderers.teams import PUBLIC_URL_ENV, TeamsFormRenderer   # lazy, same posture as _seed_default_renderers

    if renderer is None:
        import os
        if not (public_base_url or os.environ.get(PUBLIC_URL_ENV)):
            logger.info("register_teams_renderer: no public base URL — 'teams' format not registered")
            return False
        renderer = TeamsFormRenderer(public_base_url, api_base_path=api_base_path,
                                     ui_base_path=ui_base_path, signing_secret=signing_secret)
    register_renderer(TEAMS_FORMAT_KEY, renderer)
    return True
```
**Why**: `setup_form_api` calls this once per app; an explicit `renderer` wins over URL composition (tests inject fakes).

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` (MODIFY — `handle_render`)
```python
# occurrences: 1 (verified: grep -c 'rendered = await renderer.render(form, locale=locale)' api/render.py)
# REPLACE the line at render.py:146 with:
    render_kwargs: dict[str, Any] = {"locale": locale}
    if getattr(renderer, "accepts_tenant", False):
        render_kwargs["tenant"] = tenant
    try:
        rendered = await renderer.render(form, **render_kwargs)
    except ValueError as exc:  # TeamsRenderConfigError is a ValueError
        logger.warning("render dispatcher: %s renderer refused: %s", format_key, exc)
        return web.json_response({"error": str(exc)}, status=400)

# occurrences: 1 (verified: grep -c 'body = _coerce_body(rendered.content)' api/render.py)
# BEFORE — insert above `    body = _coerce_body(rendered.content)` (verified: render.py:148)
    if request.query.get("with_meta", "").lower() in ("1", "true", "yes"):
        return web.json_response({
            "content": rendered.content,
            "content_type": rendered.content_type,
            "warnings": [w.model_dump(mode="json") for w in rendered.warnings],
            "metadata": rendered.metadata,
        })
```
**Why**: renderers that don't declare `accepts_tenant` get exactly today's call; `with_meta` short-circuits before `_coerce_body` so the default branch is untouched.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'alias_registry: "SinkAliasRegistry | None" = None,' api/routes.py)
# AFTER — insert below `    alias_registry: "SinkAliasRegistry | None" = None,` (verified: routes.py:211)
    public_base_url: str | None = None,
    teams_renderer: "AbstractFormRenderer | None" = None,

# occurrences: 1 (verified: grep -c '_seed_default_renderers()' api/routes.py)
# AFTER — insert below `    render_module._seed_default_renderers()` (verified: routes.py:299)
    render_module.register_teams_renderer(
        public_base_url=public_base_url,
        api_base_path=base_path,
        ui_base_path=app.get("_form_prefix", ""),
        renderer=teams_renderer,
    )
```
**Why**: `_form_prefix` is set by `setup_form_ui` (`ui/routes.py:169`) when the UI is mounted first; default `""` matches the UI's root-mount default. Add the two kwargs to the `setup_form_api` docstring Args list (`:213-`).

### `packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py` (MODIFY)
```python
# AFTER — append at end of file
from parrot_formdesigner.api.render import register_teams_renderer
from parrot_formdesigner.core.schema import RenderedForm, RenderWarning


def test_register_teams_renderer_noop_without_url(monkeypatch):
    monkeypatch.delenv("FORMDESIGNER_PUBLIC_URL", raising=False)
    assert register_teams_renderer() is False
    assert "teams" not in supported_formats()


async def test_dispatcher_teams_415_when_unregistered(aiohttp_client, sample_form):
    # FILL IN: copy the harness of test_dispatcher_adaptive_delegates (:175-212) without registering "teams";
    #   GET .../render/teams -> 415 and "teams" not in body["supported"] — bounded by render.py:117-122
    raise NotImplementedError


async def test_dispatcher_teams_passes_tenant(aiohttp_client, sample_form):
    captured: dict = {}

    class _T(AbstractFormRenderer):
        accepts_tenant = True
        async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None, tenant=None):
            captured["tenant"] = tenant
            return RenderedForm(content={"type": "AdaptiveCard"}, content_type="application/json")
    # FILL IN: register_renderer("teams", _T()); GET /api/v1/navigator/forms/{uid}/render/teams -> 200 and captured["tenant"] == "navigator";
    #   also register a plain renderer WITHOUT accepts_tenant under "plain" and assert its render() is called with only locale — bounded by S12
    raise NotImplementedError


async def test_dispatcher_with_meta_envelope(aiohttp_client, sample_form):
    # FILL IN: renderer returning warnings=[RenderWarning(field_id="f", field_type="image", renderer="teams", reason="r")],
    #   metadata={"channel": "msteams"}; GET ...?with_meta=true -> JSON with keys content/content_type/warnings/metadata;
    #   GET without it -> raw content and original content_type — bounded by S7
    raise NotImplementedError


async def test_dispatcher_render_config_error_400(aiohttp_client, sample_form):
    # FILL IN: renderer whose render raises ValueError("no base url") -> 400 {"error": "no base url"} — bounded by spec §3 M3
    raise NotImplementedError
```
**Why**: mirrors the existing harness (`_tenant_wrapped_render`, `_reset_renderers` autouse) so the registry is isolated per test.

### FILL IN checklist
- [ ] `render.py::handle_render` — `Any` must already be imported (`render.py:22` — yes); keep `logger` usage.
- [ ] `test_render_dispatcher.py` — four `FILL IN` test bodies; bounded by S7/S12 and render.py:117-122.
- [ ] `routes.py` docstring Args for the two new kwargs.

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
- [ ] With `FORMDESIGNER_PUBLIC_URL` unset and no `public_base_url`, `"teams" not in supported_formats()` and `GET …/render/teams` → 415
- [ ] With it set, `GET …/render/teams` → 200, `Content-Type: application/vnd.microsoft.card.adaptive`, last action carries `_formdesigner`
- [ ] `?with_meta=true` returns `content/content_type/warnings/metadata`; default response unchanged (existing `test_dispatcher_adaptive_delegates`/`html_delegates` still pass)

---

## Test Specification

See blueprint; existing tests `test_default_seed_includes_html_and_adaptive` (:76) and `test_dispatcher_*` must remain green.

---

## Agent Instructions

1. Read spec §3 M3 and §6.
2. Check TASK-3147 is in `sdd/tasks/completed/`.
3. Verify anchors (`grep -n "rendered = await renderer.render" api/render.py`).
4. Update index status → `"in-progress"`.
5. Implement from the blueprint; complete every `# FILL IN:`.
6. Verify acceptance criteria.
7. Move this file to `sdd/tasks/completed/TASK-3149-teams-format-registration-and-dispatcher.md`; index → `"done"`; Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
