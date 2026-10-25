# TASK-4694: End-to-end round-trip tests and operator docs (M8)

**Feature**: FEAT-734 — Serve FormDesigner forms from a Teams agent
**Spec**: `sdd/specs/formdesigner-serve-forms.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-4685, TASK-4693
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 8**: the end-to-end proof and the operator guide. Unit tests
already live with each module; this task wires the REAL pieces together —
real `TeamsFormRenderer`, the real M9 render dispatcher behind an
`aiohttp_server`, the real `FormDesignerClient`, the real mixin and the real
wrapper seams — and feeds the renderer's own generated `Action.Submit` payloads
back through `MSTeamsAgentWrapper._handle_card_submission`. Then it writes
`docs/formdesigner-serve-forms.md`.

Depends on TASK-4693 (wrapper seams; transitively the whole mixin) and
TASK-4685 (server `section_index`). Wave 6 — last.

---

## Scope

- Create `tests/msteams/test_formdesigner_mixin_roundtrip.py` with:
  `test_getform_slug_sends_card_remote_e2e`, `test_wizard_generated_actions_route_to_mixin`
  (parameterized local/remote), `test_remote_wizard_section_contract`,
  `test_remote_wizard_rejects_old_server`, `test_toolkit_normal_chat_delivers_card`.
- The POST target (`…/forms/{uid}/data`) is captured by patching
  `parrot.integrations.msteams.formdesigner_mixin.post_submission` — no real submission server.
- Create `docs/formdesigner-serve-forms.md`: what it does; `class MyAgent(TeamsFormDesignerMixin, Agent)`;
  remote vs local modes; the config matrix (every `formdesigner_*` field + `{NAME}_FORMDESIGNER_*`
  env var, which mode uses it); tenant precedence; the signing-secret requirement;
  prerequisites FEAT-729 (`/login`) and FEAT-733 (`formdesigner_tenant_map`, mandatory signature);
  limits (1:1 only, process-local wizard state, upload fields → web-form link).

**NOT in scope**: any production-code change. If an e2e test exposes a bug in an
earlier task's code, record it in the Completion Note (and open a ledger issue) —
do not fix it here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_mixin_roundtrip.py` | CREATE | real renderer + dispatcher + client + mixin + wrapper |
| `docs/formdesigner-serve-forms.md` | CREATE | operator guide |


---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web
from parrot_formdesigner.api.render import handle_render, register_renderer       # api/render.py:165, :91
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, TeamsFormRenderer   # renderers/teams.py:36, :88
from parrot_formdesigner.services.registry import FormRegistry                    # services/registry.py:240
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection    # used by test_render_dispatcher.py:17-22
from parrot_formdesigner.core.types import FieldType                              # test_render_dispatcher.py:23
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper               # test_formdesigner_wrapper.py:10
from parrot.integrations.msteams.formdesigner_mixin import PICKER_ACTION_KEY, TeamsFormDesignerMixin   # TASK-4691
from parrot.integrations.msteams.formdesigner_client import FormDesignerClient    # TASK-4682
from parrot.integrations.msteams.formdesigner_submit import SubmitOutcome         # formdesigner_submit.py:65
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py
async def _tenant_wrapped_render(request) -> web.Response:  # line 28 — stashes request["tenant"] then handle_render
#   COPY this 3-line helper into the new test module (do not import from another package's tests).

# packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py
def _wrapper(...) -> MSTeamsAgentWrapper:   # line 15 — the __new__-based construction pattern to copy; set w.agent = <mixin agent>

# MSTeamsAgentWrapper (TASK-4693): _handle_card_submission(turn_context, dialog_context) (line 482),
#   _formdesigner_agent(), _wire_formdesigner_agent(), _formdesigner_turn(), _flush_formdesigner_cards_if_ok()
# TeamsFormDesignerMixin (TASK-4691/4692): formdesigner_client= and formdesigner_session_store= test seams,
#   formdesigner_turn(), flush_formdesigner_cards(), handle_formdesigner_card(), agent_tools()
```

### Does NOT Exist
- ~~`tests/msteams/conftest.py`~~ — there is none (the spec's "extend conftest" assumed one). Keep fixtures in the module; do NOT create a conftest (other tasks' tests would load it).
- ~~A FormDesigner test server fixture in ai-parrot-integrations~~ — build the `web.Application` in the test.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/tests/msteams/test_formdesigner_mixin_roundtrip.py",
      "action": "CREATE"
    },
    {
      "path": "docs/formdesigner-serve-forms.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py#handle_render",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper._handle_card_submission"
  ]
}
```

---

## Implementation Notes

- Remote setup: `register_renderer("teams", TeamsFormRenderer(public_base_url="https://forms.test", signing_secret="s3cret"))`;
  app route `/api/v1/{tenant}/forms/{form_uid}/render/{format}` → `_tenant_wrapped_render`; add GET
  `/api/v1/{tenant}/forms/{form_uid}` and `/api/v1/{tenant}/forms` handlers that serve the registry's forms as JSON
  (mirror `handlers.list_forms`' `{"forms": [...]}` shape). The mixin gets
  `formdesigner_base_url=str(server.make_url(""))`, `formdesigner_signing_secret="s3cret"`,
  `allowed_hosts=["forms.test"]` via `apply_teams_config` with a `SimpleNamespace` config.
- Reset the renderer registry around each test (copy `_reset_renderers` from test_render_dispatcher.py:41).
- `test_toolkit_normal_chat_delivers_card`: inside `async with agent.formdesigner_turn(ctx)`, call the
  `formdesigner_get_form` tool's coroutine directly, then `flush_formdesigner_cards(ctx)`; assert one card sent and the
  tool result has no card JSON.

---

## Implementation Blueprint

### Steps (in order)
1. Module fixtures: three-section form, fake store, fake ctx, remote app factory — *why*: every test shares them.
2. The five tests — *why*: they are the spec §4 integration rows not covered by unit tests.
3. The doc — *why*: spec §5 AC requires it.

### `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_mixin_roundtrip.py` (CREATE)
```python
"""FEAT-734 — end-to-end: real renderer + real dispatcher + real client + mixin + wrapper seams."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("botbuilder")
from aiohttp import web  # noqa: E402
from parrot_formdesigner.api.render import _RENDERERS, handle_render, register_renderer  # noqa: E402
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, TeamsFormRenderer  # noqa: E402
from parrot_formdesigner.services.registry import FormRegistry  # noqa: E402

from parrot.integrations.msteams.formdesigner_mixin import PICKER_ACTION_KEY, TeamsFormDesignerMixin  # noqa: E402
from parrot.integrations.msteams.formdesigner_submit import SubmitOutcome  # noqa: E402
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper  # noqa: E402


async def _tenant_wrapped_render(request: web.Request) -> web.Response:
    request["tenant"] = request.match_info["tenant"]
    return await handle_render(request)


@pytest.fixture(autouse=True)
def _reset_renderers():
    snapshot = dict(_RENDERERS)
    _RENDERERS.clear()
    yield
    _RENDERERS.clear()
    _RENDERERS.update(snapshot)

# FILL IN: three_section_form fixture (tenant "acme", is_public False is fine — render route checks membership,
#   so either mark it public for the server or stash programs; prefer is_public=True as test_render_dispatcher does)
# FILL IN: remote_app(aiohttp_server, form) -> server with list/get/render routes
# FILL IN: FakeStore (authenticated session, nav_session_token="nav-tok", tenant_id=<GUID>), ctx factory,
#   agent factory for "remote" and "local" (local: FormRegistry + an allow-all authorizer)
# FILL IN: wrapper factory copying test_formdesigner_wrapper._wrapper, with w.agent = agent and
#   w._session_store = store, then w._wire_formdesigner_agent()
# FILL IN: five tests from the Scope list
```

### `docs/formdesigner-serve-forms.md` (CREATE)
```markdown
# Serving FormDesigner forms from a Teams agent

<!-- FILL IN: one paragraph — what /getform, /listforms and the two tools do -->

## Quick start
<!-- FILL IN: class MyAgent(TeamsFormDesignerMixin, Agent) + minimal YAML for remote mode -->

## Modes
<!-- FILL IN: remote (HTTP, server-signed envelope, needs GET …/render/teams?with_meta=true and section_index support)
     vs local (in-process FormRegistry, agent signs with formdesigner_signing_secret, requires a LocalFormAuthorizer) -->

## Configuration
| Field | Env var | Mode | Default | Purpose |
|---|---|---|---|---|
<!-- FILL IN: formdesigner_mode, _base_url, _tenant, _public_url, _render_timeout, _api_base_path,
     _allowed_hosts, _submit_secret (signing/verification), _submit_timeout, formdesigner_tenant_map (FEAT-733) -->

## Tenant resolution
<!-- FILL IN: mapped activity AAD GUID > mapped session AAD GUID > formdesigner_tenant; never a raw GUID -->

## Prerequisites
<!-- FILL IN: FEAT-729 /login (per-user bearer; no service-token fallback), FEAT-733 tenant map + mandatory signatures -->

## Limits (v1)
<!-- FILL IN: 1:1 chats only; wizard state is per-process (multi-worker -> restart on miss); uploads -> web-form link -->
```

### FILL IN checklist
- [ ] fixtures and factories
- [ ] five e2e tests
- [ ] every doc section, config matrix complete against `models.py` after TASK-4687

---

## Acceptance Criteria

- [ ] Renderer-generated wizard actions (local AND remote) reach the mixin through the wrapper; only the terminal submit posts; no control object in posted answers.
- [ ] Remote wizard: each card holds only its section; terminal envelope verifies with the server secret; answers accumulate.
- [ ] A server ignoring `section_index` yields an error card, never a whole-form card.
- [ ] Natural-language tool path sends exactly one card; tool result has metadata only.
- [ ] `docs/formdesigner-serve-forms.md` covers both modes, the config matrix and the FEAT-729/733 prerequisites.
- [ ] No production file modified; `ruff check` clean on the test file.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_mixin_roundtrip.py -q`


---

## Test Specification

Five tests listed in Scope (spec §4: `test_wizard_generated_actions_route_to_mixin`,
`test_remote_wizard_section_contract`, `test_remote_wizard_rejects_old_server`,
`test_toolkit_normal_chat_delivers_card`, plus the e2e `/getform` check).

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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4694 formdesigner-serve-forms verified`
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
