# TASK-3788: PublishSurfaceTool + InfographicAuthoringMixin.publish_surface through LinkedSurfaceService

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3781, TASK-3786
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (programmatic half), S1/S2, AC14/AC18. Besides the REST handler (TASK-3787), two
programmatic save paths persist surfaces: `InfographicAuthoringMixin.publish_surface` (core) and
`PublishSurfaceTool`'s standalone fallback lane (`_publish_directly`, ai-parrot-tools). Today both
only run `CreateSurface.model_validate`, so a hand-written linked descriptor could be persisted
and executed later by the trusted-service refresh lane (S2 exfiltration). Both must delegate to
`LinkedSurfaceService.validate_for_persistence` + `ensure_snapshot` with the owner's context, and
the tool's `refreshable` must mirror the record rule (`recipe_name is not None or
has_data_sources(envelope)`, TASK-3786) instead of `recipe_name is not None`.

---

## Scope

- `publish_surface` (mixin): after `model_validate` (L501) and after `resolved_user_id` (L521), for
  a linked envelope build `owner_pctx = build_principal_context(resolved_user_id, channel="ui_surfaces")`,
  run `validate_for_persistence` + `ensure_snapshot` on the service
  (`getattr(self, "_linked_surface_service", None)` or `LinkedSurfaceService(guard=getattr(self,
  "_dataplane_guard", None))`), and build the record from the snapshotted dump. Errors propagate
  (`LinkedGuardRequired`, `AuthorizationRequired`, `CatalogValidationError`, `SnapshotError`) —
  nothing is saved. Log `refreshable` with the widened rule.
- `PublishSurfaceTool`: add constructor kwarg `linked_service: Any = None`; in `_publish_directly`
  do the same boundary with `owner_pctx = self._current_pctx or build_principal_context(user_id,
  channel="ui_surfaces")`; the bot lane delegates unchanged (the mixin enforces). Return
  `"refreshable": recipe_name is not None or has_data_sources(envelope)`.
- Baked envelopes: behaviour byte-for-byte unchanged (AC11) — the service is not even constructed.
- Tests next to the existing ones.

**NOT in scope**: the REST handler (TASK-3787); `LinkedSurfaceService` itself (TASK-3781); `PublishSurfaceArgs`
schema (unchanged); new app/bot wiring for the guard (built by TASK-3805, documented by TASK-3796).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py` | MODIFY | standalone lane boundary + snapshot; `refreshable` widened; `linked_service` kwarg |
| `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py` | MODIFY | `publish_surface` boundary + snapshot |
| `packages/ai-parrot-tools/tests/test_publish_surface_tool_linked.py` | CREATE | tool tests |
| `packages/ai-parrot/tests/bots/test_publish_surface_mixin_linked.py` | CREATE | mixin tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported
from parrot.outputs.a2ui.models import CreateSurface                 # parrot_tools/ui_surfaces.py:23 ; infographic_authoring.py:29
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema   # parrot_tools/ui_surfaces.py:24
# new for this task
from parrot.auth.permission import build_principal_context          # permission.py:166
from parrot.outputs.a2ui.linked import has_data_sources             # TASK-3769
from parrot.outputs.a2ui.linked.service import LinkedSurfaceService # TASK-3781
# tests
from parrot.tools.ui_surfaces import PublishSurfaceTool             # test_publish_surface_tool.py:9 (meta_path redirect)
from parrot.bots.data import PandasAgent                            # test_publish_surface_mixin.py:20
from parrot.bots.mixins import InfographicAuthoringMixin            # test_publish_surface_mixin.py:21
from parrot.auth.exceptions import AuthorizationRequired            # auth/exceptions.py:12
from parrot.outputs.a2ui.linked.service import LinkedGuardRequired, SnapshotError   # TASK-3781
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py
class PublishSurfaceTool(AbstractTool):                                # L60
    def __init__(self, bot=None, surface_store=None, agent_id=None, user_id=None, session_id=None, **kwargs)   # L81-110
    async def _execute(self, *, kind, title, envelope, recipe_name=None, recipe_owner=None,
                       recipe_params=None, overwrite=False, **kwargs) -> dict[str, Any]   # L112-150
        # bot lane: await self._bot.publish_surface(...) L123-134; else self._publish_directly(...) L136-144
        # return {"surface_id": ..., "kind": kind, "refreshable": recipe_name is not None}   L146-150 (anchor L149)
    async def _publish_directly(self, *, kind, title, envelope, recipe_name, recipe_owner, recipe_params, overwrite) -> str   # L152
        # envelope_model = CreateSurface.model_validate(envelope)   L185
        # surface_id = str(uuid.uuid4()) L192; store L193; agent_id L194; user_id = self._user_id or agent_id L195
        # record = UISurfaceRecord(..., envelope=envelope_model.model_dump(by_alias=True, mode="json"), ...) L198-213 (envelope L202)
        # return await store.save(record, overwrite=overwrite)   L214
# packages/ai-parrot/src/parrot/tools/abstract.py
#   self._current_pctx: Optional[Any] = None   L409 — set from `_permission_context` by execute() (L904, L943)

# packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py
async def publish_surface(self, *, kind, title, envelope, recipe_name=None, recipe_owner=None, recipe_params=None,
                          overwrite=False, surface_store=None, user_id=None, session_id=None) -> str   # L440-452
    # envelope_model = envelope if isinstance(envelope, CreateSurface) else CreateSurface.model_validate(envelope)   L501
    # PgUISurfaceStore, UISurfaceKind, UISurfaceRecord = self._lazy_import_ui_surfaces_models()   L514
    # agent_id L520; resolved_user_id = user_id or getattr(self, "user_id", None) or agent_id   L521
    # record = UISurfaceRecord(..., envelope=envelope_model.model_dump(by_alias=True, mode="json"), ...)   L523-537 (envelope L528)
    # persisted_id = await store.save(record, overwrite=overwrite)   L539
    # self.logger.info("publish_surface(%s): saved kind=%s title=%r refreshable=%s.", ..., recipe_name is not None)   L540-546
```

### Does NOT Exist
- ~~`self._linked_surface_service` / `self._dataplane_guard` on any bot~~ — nothing sets them in THIS task's code (read with `getattr(..., None)`); TASK-3805 injects `bot._dataplane_guard` from the app guard at server startup for managed bots. Standalone/un-wired bots still fail CLOSED for linked envelopes (`LinkedGuardRequired`) and are unaffected for baked ones — this task's unit tests construct bots without the attribute, so the fail-closed tests stay valid regardless of TASK-3805's landing order.
- ~~`PublishSurfaceTool(linked_service=…)`~~ — added here.
- ~~`validate_envelope` on any existing save path~~ — the service runs it for linked envelopes only (TASK-3781 Decision; running it on baked `components=[]` envelopes would break existing tests, AC11).
- ~~a record returned by `bot.publish_surface`~~ — it returns only the id; the tool computes `refreshable` with the same rule as `UISurfaceRecord.refreshable`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/test_publish_surface_tool_linked.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/bots/test_publish_surface_mixin_linked.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py#PublishSurfaceTool",
    "sym:packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py#PublishSurfaceTool._execute",
    "sym:packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py#PublishSurfaceTool._publish_directly",
    "sym:packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py#InfographicAuthoringMixin.publish_surface",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#build_principal_context"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Owner context (AC18)**: the mixin uses the resolved owner id; the tool prefers the live `_current_pctx` (the invoking user) and falls back to the attributed `user_id`.
- **Fail closed (AC14)**: no guard ⇒ `LinkedGuardRequired` propagates; nothing is saved.
- **No double enforcement**: the tool's bot lane must NOT call the service (the mixin does); only `_publish_directly` does.
- Tenant never from the bot/session (AC4) — the service reads it from each descriptor entry.
- Core file (`infographic_authoring.py`) imports only core modules — `parrot.outputs.a2ui.linked.*` is core; keep the server import lazy as today.

---

## Implementation Blueprint

### Steps (in order)
1. Mixin: add imports; insert the boundary between `resolved_user_id` (L521) and `record = UISurfaceRecord(` (L523); swap the record's envelope for the snapshotted dump; widen the log — *why*: AC14/AC8 on the programmatic lane.
2. Tool: add `linked_service` kwarg; insert the same boundary in `_publish_directly` after `user_id` (L195); widen `refreshable` in `_execute` — *why*: standalone lane parity + record-rule mirror.
3. Tests for both.

### `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py` (MODIFY) — imports
```python
# occurrences: 1 (verified: grep -c 'from parrot.outputs.a2ui.models import CreateSurface' packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py)
# AFTER — insert below `from parrot.outputs.a2ui.models import CreateSurface` (verified: infographic_authoring.py:29)
from parrot.auth.permission import build_principal_context
from parrot.outputs.a2ui.linked import has_data_sources
```

### `infographic_authoring.py` (MODIFY) — publish_surface boundary
```python
# occurrences: 1 (verified: grep -c '        resolved_user_id = user_id or getattr(self, "user_id", None) or agent_id' infographic_authoring.py)
# AFTER — insert below `        resolved_user_id = user_id or getattr(self, "user_id", None) or agent_id` (verified: infographic_authoring.py:521)
        envelope_dump = envelope_model.model_dump(by_alias=True, mode="json")
        linked = has_data_sources(envelope_model)
        if linked:
            # FEAT-598 S1/S2: the persistence boundary for linked envelopes — TOOL-origin validation, a mandatory
            # (fail-closed) data-plane guard, and a save-time snapshot executed ONCE in the owner's context.
            from parrot.outputs.a2ui.linked.service import LinkedSurfaceService

            service = getattr(self, "_linked_surface_service", None) or LinkedSurfaceService(
                guard=getattr(self, "_dataplane_guard", None)
            )
            owner_pctx = build_principal_context(resolved_user_id, channel="ui_surfaces")
            await service.validate_for_persistence(envelope_model, owner_pctx=owner_pctx)
            envelope_dump = await service.ensure_snapshot(envelope_dump, owner_pctx=owner_pctx)
# THEN in the UISurfaceRecord(...) call (L523-537) replace
#   `            envelope=envelope_model.model_dump(by_alias=True, mode="json"),`   (occurrences in this file: 1, L528)
# with
#   `            envelope=envelope_dump,`
# AND in the logger.info call (L540-546) replace the last argument `recipe_name is not None` with
#   `recipe_name is not None or linked`
```
**Why**: the service is imported function-locally so baked-only bots never import it; errors propagate by design so the caller (tool / agent) sees why nothing was saved.

### `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py` (MODIFY) — imports + constructor
```python
# occurrences: 1 (verified: grep -c 'from parrot.outputs.a2ui.models import CreateSurface' packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py)
# AFTER — insert below `from parrot.outputs.a2ui.models import CreateSurface` (verified: parrot_tools/ui_surfaces.py:23)
from parrot.auth.permission import build_principal_context
from parrot.outputs.a2ui.linked import has_data_sources

# __init__ (L81-110): add keyword `linked_service: Any = None` after `session_id`, document it in the Args block
#   ("LinkedSurfaceService used by the standalone lane for linked envelopes (FEAT-598); built with guard=None — i.e.
#   fail-closed for linked envelopes — when not given"), and store `self._linked_service = linked_service`.
```

### `parrot_tools/ui_surfaces.py` (MODIFY) — refreshable
```python
# occurrences: 1 (verified: grep -c '"refreshable": recipe_name is not None' packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py)
# REPLACE parrot_tools/ui_surfaces.py:149
            "refreshable": recipe_name is not None or has_data_sources(envelope),
```

### `parrot_tools/ui_surfaces.py` (MODIFY) — standalone lane boundary
```python
# occurrences: 1 (verified: grep -c '        user_id = self._user_id or agent_id' packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py)
# AFTER — insert below `        user_id = self._user_id or agent_id` (verified: parrot_tools/ui_surfaces.py:195)
        envelope_dump = envelope_model.model_dump(by_alias=True, mode="json")
        if has_data_sources(envelope_model):
            from parrot.outputs.a2ui.linked.service import LinkedSurfaceService

            service = self._linked_service or LinkedSurfaceService(guard=None)
            owner_pctx = self._current_pctx or build_principal_context(user_id, channel="ui_surfaces")
            await service.validate_for_persistence(envelope_model, owner_pctx=owner_pctx)
            envelope_dump = await service.ensure_snapshot(envelope_dump, owner_pctx=owner_pctx)
# THEN in the UISurfaceRecord(...) call replace
#   `            envelope=envelope_model.model_dump(by_alias=True, mode="json"),`   (occurrences in this file: 1, L202)
# with
#   `            envelope=envelope_dump,`
```
**Why**: `self._current_pctx` is populated by `AbstractTool.execute()` from `_permission_context` (abstract.py:904-943); when the tool is called directly (tests, scripts) it is `None` and the attributed user id is used.

### `packages/ai-parrot-tools/tests/test_publish_surface_tool_linked.py` (CREATE)
```python
"""FEAT-598 M8 — PublishSurfaceTool linked lane (spec §4)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.tools.ui_surfaces import PublishSurfaceTool

pytestmark = pytest.mark.asyncio

# FILL IN: _linked_envelope() helper (valid root component + metadata.extensions.parrot_data_sources built from
#          parrot.outputs.a2ui.linked.models.LinkedDataSource with conditions == derive_conditions(request)); fake
#          linked service (AsyncMock validate_for_persistence / ensure_snapshot returning a dump with rows).


async def test_publish_surface_tool_refreshable_from_record(): ...   # FILL IN: bot lane, linked envelope, no recipe → refreshable True; baked → False
async def test_standalone_lane_runs_service(): ...                   # FILL IN: no bot; service awaited; saved record envelope == ensure_snapshot result
async def test_standalone_lane_guard_missing_fails_closed(): ...     # FILL IN: no linked_service → LinkedGuardRequired, store.save not awaited
async def test_standalone_lane_baked_untouched(): ...                # FILL IN: baked envelope → service never constructed/called
async def test_bot_lane_does_not_call_service(): ...                 # FILL IN: bot present → tool never touches linked_service
```

### `packages/ai-parrot/tests/bots/test_publish_surface_mixin_linked.py` (CREATE)
```python
"""FEAT-598 M8 — InfographicAuthoringMixin.publish_surface linked boundary (spec §4)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.bots.data import PandasAgent
from parrot.bots.mixins import InfographicAuthoringMixin

pytestmark = pytest.mark.asyncio

# FILL IN: reuse the composition shape of test_publish_surface_mixin.py:25-45 (_AuthoringAgent, module-scoped agent,
#          fake_surface_store) — copied locally; set agent._linked_surface_service per test and reset it after.


async def test_publish_surface_linked_snapshot_persisted(): ...   # FILL IN: ensure_snapshot result is what store.save receives
async def test_publish_surface_owner_pctx(): ...                  # FILL IN: owner_pctx.user_id == resolved user id, channel "ui_surfaces"
async def test_publish_surface_denied_persists_nothing(): ...     # FILL IN: validate_for_persistence raises AuthorizationRequired → propagates; no save
async def test_publish_surface_baked_unchanged(): ...             # FILL IN: baked envelope → no service use; same record as before
```

### FILL IN checklist
- [ ] tool `__init__` — `linked_service` kwarg + docstring.
- [ ] tests — helpers + every body; bounded by spec §4 row `test_publish_surface_tool_refreshable_from_record` and AC14.

---

## Acceptance Criteria

- [ ] Both save paths run `LinkedSurfaceService.validate_for_persistence` + `ensure_snapshot` for linked envelopes, with the owner's context (AC14, AC18).
- [ ] No guard ⇒ `LinkedGuardRequired`; denial ⇒ propagated; nothing saved in either case.
- [ ] Tool `refreshable` mirrors `UISurfaceRecord.refreshable` (spec §4 row).
- [ ] Baked envelopes unchanged; existing `test_publish_surface_tool.py` and `test_publish_surface_mixin.py` green (AC11).
- [ ] `ruff check` clean on both modified files.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/test_publish_surface_tool_linked.py -q`
- `pytest packages/ai-parrot/tests/bots/test_publish_surface_mixin_linked.py -q`
- `pytest packages/ai-parrot-tools/tests/test_publish_surface_tool.py -q`
- `pytest packages/ai-parrot/tests/bots/test_publish_surface_mixin.py -q`

---

## Test Specification

See the two CREATE test blocks above.

---

## Agent Instructions

1. Read spec §3 Module 8 and S1/S2.
2. Check TASK-3781 and TASK-3786 are done.
3. Verify the Codebase Contract (re-grep every anchor).
4. Index → `"in-progress"`; implement; complete every `# FILL IN:`.
5. Run the Validation Commands (worktree: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-server/src`).
6. Move to `sdd/tasks/completed/`, index → `"done"`, Completion Note.

---

## Completion Note


- Task: TASK-3788
- Feature: a2ui-linked-surfaces
- Implementation SHA: 2eb39f07f1416496d39a95a101374dd64e76d56f
- Closed at (UTC): 2026-09-26T02:05:18+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| coder_record_review | NOT recorded - coder_record_review MCP tool rejects every payload including {} (systemic tool outage, confirmed also on coder_record_feedback and coder_record_native_observation) |
| merge_validation_outcome | failed: 82 pre-existing failures unrelated to this task's diff (this task touches publish_surface mixin + PublishSurfaceTool). Verified WORSE (88 failed, including new test_publish_surface_mixin.py ERRORs from an older dev-branch fixture mismatch) on clean origin/dev with the identical test selection -- confirmed pre-existing test-suite instability, not a regression from this diff. Task's own scoped tests: 5+4+8+10 passed (linked publish tests + unchanged baseline tests). See issue:181bd0c01bb4. |
| seat_summary | Seat: sonnet - Backend: native - Model: sonnet - Attempts: 1 - Duration: n/a - Tokens: n/a |
