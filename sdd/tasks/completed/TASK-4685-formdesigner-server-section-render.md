# TASK-4685: Remote section render in the render dispatcher (M9)

**Feature**: FEAT-734 — Serve FormDesigner forms from a Teams agent
**Spec**: `sdd/specs/formdesigner-serve-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 9**: the remote render endpoint renders whole forms only. A
Teams wizard served from a *remote* FormDesigner needs one section at a time
with the **server-signed** envelope on the terminal step. This task adds an
optional `section_index` query to the existing dispatcher — no new route, no
new renderer method (`TeamsFormRenderer.render_section` already exists and
already puts the envelope only on the terminal Submit).

Leaf task (server side, `parrot-formdesigner`), wave 1. TASK-4682's client
consumes this wire contract; TASK-4694 tests the two together.

---

## Scope

- In `api/render.py::handle_render`, after the existing lookup + 
  `enforce_membership_unless_public` check (unchanged), parse an optional
  `section_index` query:
  - absent → today's behaviour, byte-identical;
  - present with `format != "teams"` → HTTP 400;
  - not an int, negative, or `>= len(form.sections)` → HTTP 400;
  - valid → `renderer.render_section(form, N, locale=locale, tenant=tenant, show_back=False, show_skip=False)`
    (pass `tenant=` only when `accepts_tenant`, same as today).
- For a section render, merge into `rendered.metadata`: `section_index`,
  `total_sections`, `form_version` (`form.published_version or form.version`) —
  keep every existing metadata key and all warnings.
- Extend `tests/unit/api/test_render_dispatcher.py` with the M9 cases.

**NOT in scope**: any client code; changing authentication/membership; Back/Skip
(disabled in v1); adding upload warnings to `render_section` (renderer change, not dispatcher).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` | MODIFY | optional section_index query + section metadata |
| `packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py` | MODIFY | M9 dispatcher tests |


---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (already present in render.py)
```python
from aiohttp import web                                               # render.py:29
from .tenant import declared_tenant, enforce_membership_unless_public # render.py:33
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py
async def handle_render(request: web.Request) -> web.Response:         # line 165
    format_key = request.match_info["format"]                          # line 179
    tenant = declared_tenant(request)                                  # line ~194
    enforce_membership_unless_public(request, form, tenant)            # line 204
    render_kwargs: dict[str, Any] = {"locale": locale}                 # line 207
    if getattr(renderer, "accepts_tenant", False):                     # line 208
        render_kwargs["tenant"] = tenant
    try:
        rendered = await renderer.render(form, **render_kwargs)        # line 210  <- edit site (occurrences: 1)
    except ValueError as exc:  # TeamsRenderConfigError is a ValueError  # line 211 -> 400

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py
class TeamsFormRenderer(AdaptiveCardRenderer):                         # line 88
    async def render_section(self, form, section_index, style=None, *, locale="en",
        prefilled=None, errors=None, show_back=False, show_skip=False, tenant=None) -> RenderedForm  # line 150
    def _submit_action_data(self, form, *, terminal: bool) -> dict     # line 185 — envelope only when terminal

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema:  sections: list[FormSection]  # line 487;  version: str  # line 484;  published_version: str | None  # line 498
class RenderedForm(BaseModel):                                          # line 734 — .content .content_type .metadata .warnings

# packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py
async def _tenant_wrapped_render(request) -> web.Response: ...         # line 28 — reuse for routes
@pytest.fixture(autouse=True) def _reset_renderers(): ...              # line 41
@pytest.fixture def sample_form() -> FormSchema: ...                   # line 51 (ONE section, is_public=True)
from parrot_formdesigner.api.render import register_renderer           # line 9-16
```

### Does NOT Exist
- ~~`section_index` query support~~ — this task adds it.
- ~~A `/render/teams/section/{n}` route~~ — do not add routes; it is a query parameter.
- ~~`TeamsFormRenderer.render_sections()`~~ — only `render_section` (singular).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py#handle_render",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py#TeamsFormRenderer",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py#TeamsFormRenderer.render_section",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#RenderedForm"
  ]
}
```

---

## Implementation Notes

- Parse with `int(raw)` inside `try/except ValueError`; reject `bool`-like strings implicitly (they fail `int`).
- Validation must happen AFTER authorization, so an unauthorized caller never learns the section count.
- Server test for the signature: register a real `TeamsFormRenderer(public_base_url="https://forms.test", signing_secret="s3cret")`;
  verify the terminal action's `_formdesigner` envelope with `TeamsSubmitEnvelope.model_validate(...).verify("s3cret")`.

---

## Implementation Blueprint

### Steps (in order)
1. Replace the single render line with a branch on `section_index` — *why*: the whole-form path must stay byte-identical.
2. Merge section metadata only on the section branch — *why*: spec M9 says "preserve existing output" when the query is absent.
3. Add a three-section fixture and the tests — *why*: `sample_form` has one section.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        rendered = await renderer.render(form, \*\*render_kwargs)' render.py -> 1, line 210)
# REPLACE the `try:` block at lines 209-213 with:
    raw_section = request.query.get("section_index")
    section_index: int | None = None
    if raw_section is not None:
        if format_key != "teams":
            return web.json_response({"error": "section_index is only supported for format 'teams'"}, status=400)
        # FILL IN: int(raw_section) in try/except ValueError -> 400; 0 <= n < len(form.sections) else 400
    try:
        if section_index is None:
            rendered = await renderer.render(form, **render_kwargs)
        else:
            rendered = await renderer.render_section(
                form, section_index, show_back=False, show_skip=False, **render_kwargs
            )
            rendered.metadata = {
                **(rendered.metadata or {}),
                "section_index": section_index,
                "total_sections": len(form.sections),
                "form_version": form.published_version or form.version,
            }
    except ValueError as exc:  # TeamsRenderConfigError is a ValueError
        logger.warning("render dispatcher: %s renderer refused: %s", format_key, exc)
        return web.json_response({"error": str(exc)}, status=400)
```
**Why**: `render_kwargs` already carries `locale` and (when supported) `tenant`, so the section call gets the same tenant handling as whole-form rendering. Do not move or weaken `enforce_membership_unless_public`.

### `packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py` (MODIFY — append)
```python
# AFTER the last test in the module (append; do not edit existing tests)
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, TeamsFormRenderer, TeamsSubmitEnvelope


@pytest.fixture
def three_section_form() -> FormSchema:
    # FILL IN: like sample_form (tenant="navigator", is_public=True) but sections s1..s3, one TEXT field each
    ...


async def _teams_app(aiohttp_client, form):
    register_renderer("teams", TeamsFormRenderer(public_base_url="https://forms.test", signing_secret="s3cret"))
    registry = FormRegistry()
    await registry.register(form)
    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get("/api/v1/{tenant}/forms/{form_uid}/render/{format}", _tenant_wrapped_render)
    return await aiohttp_client(app)


async def test_section_render_returns_only_that_section(aiohttp_client, three_section_form): ...   # FILL IN
async def test_section_render_terminal_carries_signed_envelope(aiohttp_client, three_section_form): ...  # FILL IN: index 2 verifies; index 0 has no ENVELOPE_KEY
async def test_section_render_metadata(aiohttp_client, three_section_form): ...  # FILL IN: section_index/total_sections/form_version
async def test_section_render_rejects_bad_index(aiohttp_client, three_section_form): ...  # FILL IN: "x", "-1", "3" -> 400
async def test_section_render_rejects_other_format(aiohttp_client, three_section_form): ...  # FILL IN: adaptive + section_index -> 400
async def test_section_render_private_form_still_requires_membership(aiohttp_client, three_section_form): ...  # FILL IN: is_public=False -> not 200
async def test_whole_form_render_unchanged_without_query(aiohttp_client, three_section_form): ...  # FILL IN: no section keys in metadata
```

### FILL IN checklist
- [ ] `section_index` parsing + range check → 400; bounded by spec §3 M9
- [ ] `three_section_form` fixture
- [ ] seven test bodies (membership test: assert the response is not 200 without membership scaffolding — mirror how existing private-form tests behave, or mark the request without a session)

---

## Acceptance Criteria

- [ ] No query → identical behaviour and metadata to today (existing tests unchanged and passing).
- [ ] `section_index` on non-teams format, malformed, negative or out-of-range → 400.
- [ ] Section response carries only that section; terminal step's Submit has a valid server signature; intermediate steps have no `_formdesigner`.
- [ ] Metadata gains `section_index`, `total_sections`, `form_version`; existing keys preserved.
- [ ] Membership check runs before section validation.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py -q`


---

## Test Specification

Seven appended tests in the blueprint.

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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4685 formdesigner-serve-forms verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any


### Completion Note
Implemented by the sdd-coder pool; merged to the feature branch, file-fidelity gate green, merge-tier validation green, review recorded (0 corrections).
