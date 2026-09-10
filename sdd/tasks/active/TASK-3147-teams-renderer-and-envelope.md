# TASK-3147: `TeamsSubmitEnvelope` + `TeamsFormRenderer` core (envelope in the terminal Submit, metadata, tenant)

**Feature**: FEAT-551 — MS Teams FormDesigner Renderer (Adaptive Card + submit envelope via the Teams bot)
**Spec**: `sdd/specs/msteams-formdesigner-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3146
**Assigned-to**: unassigned
**Parallel**: false — overrides the hooks TASK-3146 introduces.

---

## Context

Spec §3 Module 1 (second half) and §2 Data Models. This is the deliverable the user asked for: a
renderer that exports a `FormSchema` as an MS Teams Adaptive Card whose Submit carries enough for
the bot to forward the answers to `POST …/forms/{form_uid}/data` — and that **never sends**.
The envelope model is shared with the bot (TASK-3150 imports it), so its shape is fixed here.

---

## Scope

- Create `renderers/teams.py` with `ENVELOPE_KEY`, `RESERVED_CONTROL_KEYS`, `TeamsSubmitEnvelope` (Pydantic v2, `canonical_payload`/`sign`/`verify`), `TeamsRenderConfigError`, and `TeamsFormRenderer(AdaptiveCardRenderer)` with `RENDERER_NAME = "teams"`, `accepts_tenant = True`, `__init__(public_base_url, *, api_base_path, ui_base_path, signing_secret, version)`, `build_envelope(form, tenant)`, `render(..., tenant=None)`, `_submit_action_data` override.
- Export `TeamsFormRenderer` and `TeamsSubmitEnvelope` from `renderers/__init__.py` (eager import — no heavy deps).
- Unit tests: envelope shape, sign/verify roundtrip, config errors, metadata, terminal-only envelope, `adaptive` untouched.

**NOT in scope**: upload-field posture (TASK-3148), HTTP registration (TASK-3149), any bot code (TASK-3150/3151).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py` | CREATE | envelope model + renderer |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/__init__.py` | MODIFY | export the two new symbols |
| `packages/parrot-formdesigner/tests/unit/test_teams_renderer.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer          # adaptive_card.py:121
from parrot_formdesigner.core.schema import FormField, FormSchema, RenderedForm, RenderWarning  # schema.py:65, :401, :671, :650
from parrot_formdesigner.core.style import StyleSchema                                # style.py:52
from parrot_formdesigner.core.types import FieldType, LocalizedString                 # types.py:16
from pydantic import BaseModel, Field, HttpUrl                                        # pydantic v2 (already a dependency)
import hashlib, hmac, json, os, uuid, logging                                         # stdlib
# tests
from parrot_formdesigner.core import FormSchema, FormSection                          # test_renderers.py:4 (same import works here)
from parrot_formdesigner.core.schema import FormField                                 # test_renderers.py:5
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py (post TASK-3146)
class AdaptiveCardRenderer(AbstractFormRenderer):                                     # 121
    RENDERER_NAME: str = "adaptive_card"; accepts_tenant: bool = False                # added by TASK-3146 below :144
    def __init__(self, version: str | None = None) -> None                            # 146
    async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None) -> RenderedForm   # 182 (returns RenderedForm(content=card, content_type=self.CONTENT_TYPE, warnings=warnings))
    def _submit_action_data(self, form: FormSchema | None, *, terminal: bool) -> dict[str, Any]   # TASK-3146 hook; default {"_action": "submit"}

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema(BaseModel):                                                          # 401
    form_uid: uuid.UUID (453); form_id: str (454); version: str = "1.0" (455); tenant: str | None = None (463)
    published_version: str | None = None (469); is_public: bool = False (471)
class RenderedForm(BaseModel): content; content_type; style_output; metadata: dict[str, Any] | None = None; warnings: list[RenderWarning] = []   # 671-688

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/__init__.py
from .jsonschema import JsonSchemaRenderer      # 17
__all__ = ["AbstractFormRenderer", "AdaptiveCardRenderer", "HTML5Renderer", "JsonSchemaRenderer", "TelegramRenderer"]   # 38-44
```

### Does NOT Exist
- ~~`parrot_formdesigner.renderers.teams`~~ — created by THIS task.
- ~~`FormSchema.form_version`~~ — use `form.published_version or form.version` (schema.py:469, :455).
- ~~`FormSchema.public_url` / `submit_url`~~ — no such fields; URLs are composed by `build_envelope`.
- ~~`AbstractFormRenderer.render(..., tenant=)`~~ — the base signature has NO tenant kwarg (base.py:68-76); only THIS subclass accepts it, advertised via `accepts_tenant = True`.
- ~~`navconfig` import in renderers~~ — read the env fallback with `os.environ.get("FORMDESIGNER_PUBLIC_URL")` (renderers stay framework-free; `navconfig` is used only under `core/auth.py:39` behind a try/except).
- ~~aiohttp / any HTTP client in this module~~ — forbidden (spec AC "renderer performs no network I/O").

---

## Implementation Notes

### Pattern to Follow
```python
# TASK-2545 precedent — routing envelope inside Action.Submit.data
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py:638-644
ActionSubmit(title=title, data={"a2ui_action": serialize_a2ui_message(message), "surfaceId": state.surface_id})
```

### Key Constraints
- `render()` resolves `tenant = tenant or form.tenant`; if still `None` → `TeamsRenderConfigError`. Store it on `self._current_tenant` right before `await super().render(...)`; the base calls the builders synchronously so no interleaving can occur (spec §7). Do NOT add awaits between set and use.
- `_submit_action_data` returns the base default unless `terminal and form is not None`.
- Envelope `sig` = HMAC-SHA256 hex over `canonical_payload()` = `json.dumps(model_dump(mode="json", exclude={"sig"}), sort_keys=True, separators=(",", ":")).encode()`.
- `metadata = {"channel": "msteams", "envelope": env.model_dump(mode="json"), "envelope_version": 1}`.
- Google docstrings, type hints, `self.logger` (inherited from `AdaptiveCardRenderer.__init__`, :156).

### References in Codebase
- `adaptive_card.py:182-273` — base `render` you wrap.
- `hitl_cards.py:1-25` — correlation-payload-in-Submit precedent.

---

## Implementation Blueprint

### Steps (in order)
1. Create `teams.py` with constants + `TeamsSubmitEnvelope` — *why*: the bot (TASK-3150) imports this exact model; its field names are the wire contract.
2. Add `TeamsRenderConfigError` and `TeamsFormRenderer` (`__init__`, `build_envelope`, `render`, `_submit_action_data`) — *why*: spec §3 M1 skeleton; only the terminal Submit carries the envelope.
3. Export both symbols in `renderers/__init__.py` — *why*: `api/render.py` (TASK-3149) and the bot import from the package root.
4. Write tests; run `pytest packages/parrot-formdesigner/tests/unit/test_teams_renderer.py packages/parrot-formdesigner/tests/unit/test_renderers.py -q` — *why*: the golden test from TASK-3146 must still pass (G5).

### `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py` (CREATE)
```python
"""MS Teams renderer for FormSchema — Adaptive Card + ``_formdesigner`` submit envelope (FEAT-551).

The renderer returns JSON only. The Teams bot (ai-parrot-integrations) unwraps the envelope and
POSTs the answers to ``submit_url``; see docs/formdesigner-msteams-renderer.md.
"""
from __future__ import annotations

import hashlib, hmac, json, logging, os, uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl

from ..core.schema import FormSchema, RenderedForm            # verified: schema.py:401, :671
from ..core.style import StyleSchema                          # verified: style.py:52
from .adaptive_card import AdaptiveCardRenderer               # verified: adaptive_card.py:121

logger = logging.getLogger(__name__)

ENVELOPE_KEY: str = "_formdesigner"
RESERVED_CONTROL_KEYS: frozenset[str] = frozenset({"_action", ENVELOPE_KEY})
PUBLIC_URL_ENV: str = "FORMDESIGNER_PUBLIC_URL"


class TeamsSubmitEnvelope(BaseModel):
    """Routing envelope carried in ``Action.Submit.data["_formdesigner"]`` (spec §2 Data Models)."""
    v: Literal[1] = 1
    wire: Literal["legacy"] = "legacy"
    form_uid: uuid.UUID
    tenant: str = Field(min_length=1)
    form_version: str
    is_public: bool
    submit_url: HttpUrl
    form_url: HttpUrl
    sig: str | None = None

    def canonical_payload(self) -> bytes:
        """Bytes that ``sign``/``verify`` cover: every field except ``sig``, sorted keys, compact separators."""
        return json.dumps(self.model_dump(mode="json", exclude={"sig"}), sort_keys=True, separators=(",", ":")).encode("utf-8")

    def sign(self, secret: str) -> "TeamsSubmitEnvelope":
        """Return a copy whose ``sig`` is the HMAC-SHA256 hex digest of ``canonical_payload()``."""
        digest = hmac.new(secret.encode("utf-8"), self.canonical_payload(), hashlib.sha256).hexdigest()
        return self.model_copy(update={"sig": digest})

    def verify(self, secret: str) -> bool:
        """Constant-time check of ``sig``; ``False`` when ``sig`` is ``None``."""
        if self.sig is None:
            return False
        expected = hmac.new(secret.encode("utf-8"), self.canonical_payload(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, self.sig)


class TeamsRenderConfigError(ValueError):
    """Raised when absolute URLs cannot be built (no public base URL or no tenant)."""


class TeamsFormRenderer(AdaptiveCardRenderer):
    """FormSchema -> MS Teams Adaptive Card whose terminal Submit carries a TeamsSubmitEnvelope."""
    RENDERER_NAME = "teams"
    accepts_tenant = True

    def __init__(self, public_base_url: str | None = None, *, api_base_path: str = "/api/v1",
                 ui_base_path: str = "", signing_secret: str | None = None, version: str | None = None) -> None:
        """``public_base_url`` falls back to env ``FORMDESIGNER_PUBLIC_URL``; trailing slashes are stripped."""
        super().__init__(version=version)
        self.public_base_url = (public_base_url or os.environ.get(PUBLIC_URL_ENV) or "").rstrip("/") or None
        self.api_base_path = api_base_path.rstrip("/")
        self.ui_base_path = ui_base_path.rstrip("/")
        self.signing_secret = signing_secret
        self._current_tenant: str | None = None

    def build_envelope(self, form: FormSchema, tenant: str) -> TeamsSubmitEnvelope:
        """Compose submit_url/form_url from the configured base URL; raises TeamsRenderConfigError when unset."""
        if not self.public_base_url:
            raise TeamsRenderConfigError(f"{PUBLIC_URL_ENV} / public_base_url is not configured")
        # FILL IN: build TeamsSubmitEnvelope(form_uid=form.form_uid, tenant=tenant,
        #   form_version=form.published_version or form.version, is_public=form.is_public,
        #   submit_url=f"{self.public_base_url}{self.api_base_path}/{tenant}/forms/{form.form_uid}/data",
        #   form_url=f"{self.public_base_url}{self.ui_base_path}/{tenant}/forms/{form.form_uid}")
        #   and return env.sign(self.signing_secret) when a secret is set — bounded by spec §2 Data Models / S12.
        raise NotImplementedError

    async def render(self, form: FormSchema, style: StyleSchema | None = None, *, locale: str = "en",
                     prefilled: dict[str, Any] | None = None, errors: dict[str, str] | None = None,
                     tenant: str | None = None) -> RenderedForm:
        """Render via the base class, then attach ``metadata`` with the envelope (spec §3 M1)."""
        resolved = tenant or form.tenant
        if not resolved:
            raise TeamsRenderConfigError("tenant is required (pass tenant= or set FormSchema.tenant)")
        self._current_tenant = resolved
        result = await super().render(form, style, locale=locale, prefilled=prefilled, errors=errors)
        # FILL IN: env = self.build_envelope(form, resolved); result.metadata = {"channel": "msteams",
        #   "envelope": env.model_dump(mode="json"), "envelope_version": 1}; return result — bounded by AC "metadata".
        raise NotImplementedError

    def _submit_action_data(self, form: FormSchema | None, *, terminal: bool) -> dict[str, Any]:
        """Terminal Submit -> {"_action": "submit", "_formdesigner": <envelope>}; otherwise the base default."""
        if not terminal or form is None or self._current_tenant is None:
            return super()._submit_action_data(form, terminal=terminal)
        env = self.build_envelope(form, self._current_tenant)
        return {"_action": "submit", ENVELOPE_KEY: env.model_dump(mode="json")}
```
**Why this shape**: the envelope is a Pydantic model so the bot validates by `model_validate`; `sig` covers a canonical serialisation so producer/consumer agree byte-for-byte. `_current_tenant` is the only state, set immediately before the synchronous builder calls (spec §7 gotcha).

### `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .jsonschema import JsonSchemaRenderer' renderers/__init__.py)
# AFTER — insert below `from .jsonschema import JsonSchemaRenderer` (verified: renderers/__init__.py:17)
from .teams import TeamsFormRenderer, TeamsSubmitEnvelope

# occurrences: 1 (verified: grep -c '"JsonSchemaRenderer",' renderers/__init__.py)
# AFTER — insert below `    "JsonSchemaRenderer",` (verified: renderers/__init__.py:42)
    "TeamsFormRenderer",
    "TeamsSubmitEnvelope",
```
**Why**: eager export (no heavy deps, unlike `TelegramRenderer`); also update the module docstring list at `:3-7` with one line for the Teams renderer.

### `packages/parrot-formdesigner/tests/unit/test_teams_renderer.py` (CREATE)
```python
"""Unit tests for TeamsFormRenderer / TeamsSubmitEnvelope (FEAT-551 TASK-3147)."""
import json
import pytest
from parrot_formdesigner.core import FormSchema, FormSection          # verified: test_renderers.py:4
from parrot_formdesigner.core.schema import FormField                 # verified: test_renderers.py:5
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers import AdaptiveCardRenderer, TeamsFormRenderer, TeamsSubmitEnvelope
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, TeamsRenderConfigError

pytestmark = pytest.mark.asyncio


@pytest.fixture
def form() -> FormSchema:
    # FILL IN: a 2-field public form (TEXT + BOOLEAN) with tenant="navigator", form_id="teams-demo" — bounded by FormSchema fields schema.py:453-471
    raise NotImplementedError


@pytest.fixture
def renderer() -> TeamsFormRenderer:
    return TeamsFormRenderer("https://forms.test/", api_base_path="/api/v1", ui_base_path="", signing_secret="s3cr3t")


async def test_teams_envelope_shape(renderer, form):
    result = await renderer.render(form, tenant="navigator")
    submit = result.content["actions"][-1]
    assert submit["type"] == "Action.Submit" and submit["data"]["_action"] == "submit"
    env = TeamsSubmitEnvelope.model_validate(submit["data"][ENVELOPE_KEY])
    assert str(env.submit_url) == f"https://forms.test/api/v1/navigator/forms/{form.form_uid}/data"
    assert str(env.form_url) == f"https://forms.test/navigator/forms/{form.form_uid}"
    assert env.form_version == form.version and env.is_public is True and env.sig
    assert result.metadata["channel"] == "msteams" and result.metadata["envelope_version"] == 1


def test_teams_envelope_sign_verify_roundtrip(renderer, form):
    env = renderer.build_envelope(form, "navigator")
    assert env.verify("s3cr3t") and not env.verify("other")
    assert not env.model_copy(update={"sig": None}).verify("s3cr3t")
    assert not env.model_copy(update={"tenant": "evil"}).verify("s3cr3t")


async def test_teams_render_requires_tenant_and_base_url(form, monkeypatch):
    # FILL IN: (a) TeamsFormRenderer("https://x").render(form_without_tenant) raises TeamsRenderConfigError;
    #   (b) monkeypatch.delenv("FORMDESIGNER_PUBLIC_URL", raising=False); TeamsFormRenderer().render(form, tenant="t") raises — bounded by spec §3 M1
    raise NotImplementedError


async def test_adaptive_unaffected(form):
    result = await AdaptiveCardRenderer().render(form)
    assert result.content["actions"][-1]["data"] == {"_action": "submit"} and result.metadata is None
```
**Why**: pins the wire contract (URLs, version source, signature) the bot depends on, and re-asserts `adaptive` is untouched.

### FILL IN checklist
- [ ] `teams.py::TeamsFormRenderer.build_envelope` — URL composition + optional signing; bounded by spec §2 Data Models and S12 (`form_version` string).
- [ ] `teams.py::TeamsFormRenderer.render` — metadata attachment; bounded by AC "metadata".
- [ ] `test_teams_renderer.py::form` fixture and `test_teams_render_requires_tenant_and_base_url` — bounded by spec §3 M1 error contract.

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_teams_renderer.py packages/parrot-formdesigner/tests/unit/test_renderers.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/renderers/`
- [ ] Imports work: `from parrot_formdesigner.renderers import TeamsFormRenderer, TeamsSubmitEnvelope`
- [ ] `grep -c "aiohttp" packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py` prints `0` (AC "no network I/O")
- [ ] Only the LAST action of a full-form card carries `_formdesigner`; `render_section` non-last steps carry none

---

## Test Specification

See blueprint block for `test_teams_renderer.py`; add `test_teams_wizard_last_step_only_has_envelope` using `render_section` (index 0 vs last).

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3146 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm the TASK-3146 hooks exist (`grep -n "_submit_action_data" adaptive_card.py`)
4. **Update status** in `sdd/tasks/index/msteams-formdesigner-renderer.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3147-teams-renderer-and-envelope.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
