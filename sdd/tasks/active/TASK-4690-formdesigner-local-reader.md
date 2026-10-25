# TASK-4690: Local-mode reader with membership authorization

**Feature**: FEAT-734 — Serve FormDesigner forms from a Teams agent
**Spec**: `sdd/specs/formdesigner-serve-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4682, TASK-4683
**Assigned-to**: unassigned

---

## Context

Spec §2 "Dual render" and §3 Delivery contracts, **"Local authorization and
toolkit parity"**: in `mode="local"` the agent runs inside the FormDesigner app,
so it reads the in-process `FormRegistry` and renders with `TeamsFormRenderer`.
The registry does no authorization, so every local operation must first call a
host-supplied `LocalFormAuthorizer.require_membership(...)` — no adapter or a
rejection denies BEFORE any registry call, even for public forms.

This task builds `LocalFormReader`: a `FormReader` (same signatures as the HTTP
client, so the toolkit cannot bypass authorization) plus a `render_teams` with
the same return type as the client's. Split out of M4 to keep the mixin within
the size cap.

Depends on TASK-4682 (models, `FormReader`, `FormDesignerError`) and TASK-4683
(`LocalFormAuthorizer`). Wave 2.

---

## Scope

- Create `formdesigner_local.py` with `LocalFormReader`:
  `list_forms`, `get_form`, `get_form_by_slug`, `render_teams(section_index=None)`.
- Every method calls `_authorize(tenant, bearer)` FIRST: missing authorizer,
  missing bearer, missing user id (from the injected `user_id_resolver`), or any
  exception from `require_membership` → `FormDesignerError("access denied", status=403)`
  and no registry call.
- `render_teams` refuses (`FormDesignerError(status=500)`) when no
  `signing_secret` or no `public_base_url` is configured — local mode never emits
  an unsigned card. Build a **fresh** `TeamsFormRenderer` per call.
- Section renders add `section_index`, `total_sections`, `form_version` to
  metadata exactly as the server does (TASK-4685), and set `metadata["envelope"]`.
- Write `tests/msteams/test_formdesigner_local.py` against a real `FormRegistry`.

**NOT in scope**: choosing local vs remote (mixin), sending cards, the HTTP client.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_local.py` | CREATE | LocalFormReader |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_local.py` | CREATE | membership-before-registry + signed render tests |


---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.schema import FormSchema                      # core/schema.py:426
from parrot_formdesigner.renderers.adaptive_card import _resolve            # adaptive_card.py:45 — LocalizedString -> str (teams.py imports it too)
from parrot_formdesigner.renderers.teams import TeamsFormRenderer           # renderers/teams.py:88
from .formdesigner_client import FormDescriptor, FormDesignerError, RenderedCard   # TASK-4682
from .formdesigner_identity import LocalFormAuthorizer                      # TASK-4683
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:                                                          # line 240
    async def get(self, form_uid: uuid.UUID, *, tenant: str | None = None) -> FormSchema | None: ...   # line 976
    async def get_by_slug(self, form_id: str, *, tenant: str | None = None) -> FormSchema | None: ...  # line 1004
    async def list_forms(self, *, tenant: str | None = None) -> list[FormSchema]: ...                  # line 1102
    async def register(self, form, ...) -> ...                               # used by test_render_dispatcher.py:~360

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py
class TeamsFormRenderer(AdaptiveCardRenderer):
    def __init__(self, public_base_url: str | None = None, *, api_base_path: str = "/api/v1",
                 ui_base_path: str = "", signing_secret: str | None = None, version: str | None = None)  # line 94
    def build_envelope(self, form, tenant) -> TeamsSubmitEnvelope          # line 112 — signs when signing_secret set
    async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None, tenant=None) -> RenderedForm  # line 126
    async def render_section(self, form, section_index, style=None, *, locale="en", prefilled=None,
                             errors=None, show_back=False, show_skip=False, tenant=None) -> RenderedForm  # line 150
    #   render() sets metadata {"channel", "envelope", "envelope_version"}; render_section() sets NO envelope metadata.
    #   Both store self._current_tenant on the INSTANCE -> never share one renderer across concurrent calls.

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema: form_uid (482), form_id (483), version (484), title: LocalizedString (485),
                  sections (487), description: LocalizedString | None (486), published_version (498)
class RenderedForm: content, content_type, metadata, warnings: list[RenderWarning]   # line 734
```

### Does NOT Exist
- ~~`LocalFormReader`~~ — created here.
- ~~Authorization inside `FormRegistry`~~ — the registry never checks membership; this class must.
- ~~A Navigator membership API this module can call directly~~ — authorization is ONLY via the injected `LocalFormAuthorizer`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_local.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/msteams/test_formdesigner_local.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py#FormRegistry",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py#FormRegistry.get",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py#FormRegistry.get_by_slug",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py#FormRegistry.list_forms",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py#TeamsFormRenderer.render",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py#TeamsFormRenderer.render_section",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py#TeamsFormRenderer.build_envelope",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py#_resolve"
  ]
}
```

---

## Implementation Notes

- `FormDescriptor.source = "memory"` for local rows; `title = _resolve(form.title, "en")`.
- Membership is required even for `is_public` forms in local mode (spec: deliberate, conservative).
- The terminal-step envelope for a section render: `renderer.build_envelope(form, tenant).model_dump(mode="json")`.

---

## Implementation Blueprint

### Steps (in order)
1. Constructor + `_authorize` — *why*: one gate every method passes first.
2. The three reads — *why*: same signatures as `FormDesignerClient`, so `FormReader` is satisfied structurally.
3. `render_teams` — *why*: same return type as the HTTP path so the mixin treats both modes alike.
4. Tests with a recording authorizer and a spy registry.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_local.py` (CREATE) — part 1
```python
"""In-process FormDesigner reader for mode="local" (FEAT-734): authorize, then FormRegistry + TeamsFormRenderer."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.renderers.adaptive_card import _resolve
from parrot_formdesigner.renderers.teams import TeamsFormRenderer

from .formdesigner_client import FormDescriptor, FormDesignerError, RenderedCard
from .formdesigner_identity import LocalFormAuthorizer


class LocalFormReader:
    """FormReader over an embedded FormRegistry; membership is checked before every registry call."""

    def __init__(
        self,
        registry: Any,
        *,
        authorizer: LocalFormAuthorizer | None,
        user_id_resolver: Callable[[], str | None],
        public_base_url: str | None,
        signing_secret: str | None,
        api_base_path: str = "/api/v1",
    ) -> None:
        self._registry = registry
        self._authorizer = authorizer
        self._user_id_resolver = user_id_resolver
        self._public_base_url = public_base_url
        self._signing_secret = signing_secret
        self._api_base_path = api_base_path
        self.logger = logging.getLogger(__name__)

    async def _authorize(self, tenant: str, bearer_token: str | None) -> None:
        user_id = self._user_id_resolver()
        if self._authorizer is None or not bearer_token or not user_id:
            raise FormDesignerError("access denied", status=403)
        try:
            await self._authorizer.require_membership(tenant=tenant, bearer_token=bearer_token, user_id=user_id)
        except Exception as exc:  # PermissionError, authority outage — all deny
            self.logger.info("local formdesigner: membership denied for tenant %s (%s)", tenant, type(exc).__name__)
            raise FormDesignerError("access denied", status=403) from exc

    @staticmethod
    def _descriptor(form: FormSchema) -> FormDescriptor:
        return FormDescriptor(
            form_uid=form.form_uid, form_id=form.form_id, title=_resolve(form.title, "en"),
            description=_resolve(form.description, "en") if form.description else None,
            version=form.published_version or form.version, source="memory",
        )

    async def list_forms(self, *, tenant: str, bearer_token: str | None) -> list[FormDescriptor]:
        await self._authorize(tenant, bearer_token)
        return [self._descriptor(f) for f in await self._registry.list_forms(tenant=tenant)]

    async def get_form(self, *, tenant: str, form_uid: uuid.UUID, bearer_token: str | None) -> FormSchema:
        await self._authorize(tenant, bearer_token)
        form = await self._registry.get(form_uid, tenant=tenant)
        if form is None:
            raise FormDesignerError("form not found", status=404)
        return form

    async def get_form_by_slug(self, *, tenant: str, slug: str, bearer_token: str | None) -> FormDescriptor | None:
        await self._authorize(tenant, bearer_token)
        form = await self._registry.get_by_slug(slug, tenant=tenant)
        return self._descriptor(form) if form is not None else None
```

### `formdesigner_local.py` (CREATE) — part 2 (append inside `LocalFormReader`)
```python
    async def render_teams(
        self, *, tenant: str, form_uid: uuid.UUID, bearer_token: str | None, section_index: int | None = None
    ) -> RenderedCard:
        """Render with a fresh, signing TeamsFormRenderer; refuse when unsigned output would result."""
        if not self._signing_secret or not self._public_base_url:
            raise FormDesignerError("local mode requires formdesigner_signing_secret and public URL", status=500)
        form = await self.get_form(tenant=tenant, form_uid=form_uid, bearer_token=bearer_token)
        renderer = TeamsFormRenderer(
            self._public_base_url, api_base_path=self._api_base_path, signing_secret=self._signing_secret
        )
        # FILL IN: section_index None -> await renderer.render(form, tenant=tenant); else validate
        #   0 <= section_index < len(form.sections) (else FormDesignerError(status=400)) and
        #   await renderer.render_section(form, section_index, tenant=tenant, show_back=False, show_skip=False),
        #   then metadata = {**metadata, "envelope": renderer.build_envelope(form, tenant).model_dump(mode="json"),
        #   "section_index", "total_sections", "form_version": form.published_version or form.version} (match TASK-4685).
        #   TeamsRenderConfigError (ValueError) -> FormDesignerError(status=500).
        #   Return RenderedCard(content=..., content_type=..., warnings=[w.model_dump(mode="json") ...], metadata=...)
        raise NotImplementedError
```
**Why this shape**: authorization-before-registry is an AC ("deny before any registry call"); a per-call renderer avoids the instance-state race noted in the contract.

### `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_local.py` (CREATE)
```python
"""FEAT-734 — LocalFormReader: membership before registry, signed renders."""
import uuid

import pytest
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, TeamsSubmitEnvelope
from parrot_formdesigner.services.registry import FormRegistry

from parrot.integrations.msteams.formdesigner_client import FormDesignerError
from parrot.integrations.msteams.formdesigner_local import LocalFormReader


class Authorizer:
    def __init__(self, allow=True, boom=False):
        self.calls, self.allow, self.boom = [], allow, boom
    async def require_membership(self, *, tenant, bearer_token, user_id):
        self.calls.append((tenant, user_id))
        # FILL IN: boom -> RuntimeError; not allow -> PermissionError


class SpyRegistry:  # wraps FormRegistry and counts calls
    ...  # FILL IN


async def test_denied_before_registry(): ...            # FILL IN: no authorizer / reject / outage -> 403 and spy count 0
async def test_authorized_list_and_resolve(): ...       # FILL IN
async def test_public_form_still_requires_membership(): ...  # FILL IN
async def test_render_signed_with_agent_secret(): ...   # FILL IN: metadata envelope verifies with the secret
async def test_render_without_secret_refuses(): ...     # FILL IN: status 500, no card
async def test_section_render_metadata_and_terminal_envelope(): ...  # FILL IN: 3 sections; only last has ENVELOPE_KEY in actions
```

### FILL IN checklist
- [ ] `render_teams` both branches + metadata; bounded by TASK-4685's metadata keys
- [ ] `Authorizer` / `SpyRegistry` fakes and six test bodies

---

## Acceptance Criteria

- [ ] No authorizer, rejection, or authority outage → `FormDesignerError(403)` with zero registry calls.
- [ ] Public forms also require membership in local mode.
- [ ] Without `signing_secret` → refusal; never an unsigned card.
- [ ] Section renders carry the same metadata keys as the server (TASK-4685).
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_local.py -q`


---

## Test Specification

Six tests in the blueprint (cover spec §4 `test_local_membership_*` and `test_local_mode_*` at the reader level).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug formdesigner-serve-forms --feature-id FEAT-734`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/formdesigner-serve-forms.json`
4. **Verify the Codebase Contract** — confirm every import/signature before writing code; never use anything under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, never change a fixed signature or path
7. **Verify** — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src:packages/parrot-formdesigner/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4690 formdesigner-serve-forms verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
