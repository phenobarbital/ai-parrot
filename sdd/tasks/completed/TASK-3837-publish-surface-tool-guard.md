# TASK-3837: PublishSurfaceTool guard-backed service resolution

**Feature**: FEAT-611 — A2UI Linked Surfaces E2E (parallel track)
**Spec**: `sdd/specs/a2ui-linked-e2e-parallel.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements spec §3 Module 7. In its standalone lane (no mixin-composed bot), `PublishSurfaceTool` persists linked envelopes through `self._linked_service or LinkedSurfaceService(guard=None)` (ui_surfaces.py:217). Nothing in the codebase ever passes `linked_service=` ("~~Wiring of `PublishSurfaceTool(linked_service=…)`~~", spec §6), so every standalone linked publish fails closed with `LinkedGuardRequired` (→ 403). That happens even when a guard exists, either configured by the caller or attached to the bot as `bot._dataplane_guard` by BotManager (manager.py:2707-2731).

The S1 scenario needs a real guard-backed publish. The fail-closed default must stay when no guard exists anywhere (spec §5: "the default behaviour (no guard → 403) is preserved").

---

## Scope

- Add an optional `guard: Any = None` kwarg to `PublishSurfaceTool.__init__` and store it as `self._guard`.
- Add `_resolve_linked_service(self) -> LinkedSurfaceService`, which resolves in this fixed order:
  1. `self._linked_service` when not `None`;
  2. `LinkedSurfaceService(guard=self._guard)` when a `guard` kwarg was given;
  3. `LinkedSurfaceService(guard=getattr(self._bot, "_dataplane_guard", None))` when that attribute is not `None`;
  4. `LinkedSurfaceService(guard=None)`, the current fail-closed default.
- Replace ui_surfaces.py:217 with `service = self._resolve_linked_service()`.
- Update the `__init__` docstring for `linked_service` and `guard`.
- Create `packages/ai-parrot-tools/tests/test_publish_surface_tool_guard_resolution.py`. It covers each of the four steps and the end-to-end no-guard `LinkedGuardRequired` path.

**NOT in scope**:
- The bot lane (`self._bot.publish_surface(...)`, ui_surfaces.py:131-143). It already uses the mixin's own guard wiring (infographic_authoring.py:534-545).
- Any change to `LinkedSurfaceService`, BotManager, or `bot._linked_surface_service`, which does not exist.
- The example agent that constructs `PublishSurfaceTool(bot=self)`, which is M9.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py` | MODIFY | `guard` kwarg, `_resolve_linked_service()`, and the :217 call site |
| `packages/ai-parrot-tools/tests/test_publish_surface_tool_guard_resolution.py` | CREATE | The 4-step order and the fail-closed default |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# ui_surfaces.py module top (existing, :17-27) — unchanged:
from __future__ import annotations
from typing import Any
# ui_surfaces.py — the service is imported FUNCTION-LOCALLY today (:215); keep it lazy inside _resolve_linked_service:
from parrot.outputs.a2ui.linked.service import LinkedSurfaceService    # verified: service.py:76
# For the return annotation only (string annotation, no runtime import needed thanks to `from __future__ import annotations`).

# Test imports (verified in test_publish_surface_tool_linked.py:5-15):
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
import parrot.outputs.a2ui.catalog.parrot  # noqa: F401
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.linked.conditions import derive_conditions
from parrot.outputs.a2ui.linked.models import LinkedDataSource, SourceRequest
from parrot.outputs.a2ui.linked.service import LinkedGuardRequired, LinkedSurfaceService
from parrot.outputs.a2ui.models import Component, CreateSurface, Extensions, SurfaceMetadata
from parrot.tools.ui_surfaces import PublishSurfaceTool      # legacy path redirect, as the sibling test uses
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py
class PublishSurfaceTool(AbstractTool):     # :62, name="publish_surface" (:73)
    def __init__(self, bot: Any = None, surface_store: Any = None, agent_id: str | None = None,
                 user_id: str | None = None, session_id: str | None = None,
                 linked_service: Any = None, **kwargs: Any) -> None   # :83-91; docstring :92-110; body :111-117
    async def _execute(self, *, kind, title, envelope, recipe_name=None, recipe_owner=None,
                       recipe_params=None, overwrite=False, **kwargs) -> dict[str, Any]   # :119-158
        # bot lane iff `self._bot is not None and hasattr(self._bot, "publish_surface")` (:131)
    async def _publish_directly(self, *, kind, title, envelope, recipe_name, recipe_owner,
                                recipe_params, overwrite) -> str    # :160-240
        # linked branch :211-220:
        #   from parrot.outputs.a2ui.linked.service import LinkedSurfaceService   (:215)
        #   service = self._linked_service or LinkedSurfaceService(guard=None)    (:217)
        #   owner_pctx = self._current_pctx or build_principal_context(user_id, channel="ui_surfaces")  (:218)

# packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py
class LinkedGuardRequired(Exception)   # :31
class LinkedSurfaceService:
    def __init__(self, *, guard: Any | None, max_fetch_rows: int = 5000, max_snapshot_rows: int = 500)  # :76-80 (self.guard)
    def _require_guard(self) -> Any    # :82-85 raises LinkedGuardRequired when guard is None
    async def validate_for_persistence(self, envelope, *, owner_pctx) -> None   # :109
    async def ensure_snapshot(self, envelope: dict, *, owner_pctx) -> dict      # :119 (calls _require_guard :126)
```

### Does NOT Exist
- ~~`PublishSurfaceTool._guard`~~ / ~~a `guard` kwarg~~. This task creates them. `AbstractTool` defines no `_guard` attribute (verified: `grep -n "_guard\b" packages/ai-parrot/src/parrot/tools/abstract.py` finds only `_guardrail*` names).
- ~~`PublishSurfaceTool._resolve_linked_service`~~. This task creates it.
- ~~`bot._linked_surface_service`~~ as production wiring. The E2E test sets it on a mini bot only (test_linked_surfaces_e2e.py:334).
- ~~`LinkedSurfaceService.from_bot(...)`~~ or any factory. Use the constructor.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/test_publish_surface_tool_guard_resolution.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py#PublishSurfaceTool",
    "sym:packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py#PublishSurfaceTool.__init__",
    "sym:packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py#PublishSurfaceTool._execute",
    "sym:packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py#PublishSurfaceTool._publish_directly",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py#LinkedSurfaceService",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py#LinkedGuardRequired"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Copy `_linked_envelope()` and `_fake_store()` from `packages/ai-parrot-tools/tests/test_publish_surface_tool_linked.py:20-65`. The existing test `test_standalone_lane_guard_missing_fails_closed` (:108-115) is the model for the default path, and it must keep passing unchanged.

### Key Constraints
- Use `is not None` checks, never truthiness. A guard or service object could define `__bool__`/`__len__`, and the step-1 semantics of today's `or` must be preserved for real service objects. Use `self._linked_service is not None`, which differs from `or` only for falsy services, and none exist.
- Keep the `LinkedSurfaceService` import function-local inside `_resolve_linked_service`, because the module avoids importing `linked.service` at import time today (:215).
- The bot lane is untouched. Step 3 only applies in the standalone lane, where `_bot` is either `None` or lacks `publish_surface`. `getattr(None, "_dataplane_guard", None)` is `None`, so this is safe.
- `self.logger.debug(...)` records which step resolved (1-4), without logging the guard object. `AbstractTool` provides `self.logger`; verify it with `grep -n "self.logger" packages/ai-parrot/src/parrot/tools/abstract.py` before use. If it is absent, drop the log line rather than inventing a logger.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py:534-545`: the bot lane already builds the service from `bot._dataplane_guard`; step 3 mirrors it.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the `guard` kwarg after `linked_service` in `__init__`, and store `self._guard`. *Why*: it gives an explicit injection seam for standalone callers (spec skeleton).
2. Update the docstring. *Why*: the `linked_service` text currently says "built with guard=None when not given", which becomes false.
3. Add `_resolve_linked_service` directly above `async def _publish_directly(`. *Why*: it is the single decision point, and it can be unit-tested without a store.
4. Replace line :217. *Why*: this is the only call site.
5. Write the tests and run the Validation Commands, including the sibling suite.

### `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py` (MODIFY) — signature
```python
# occurrences: 1 (verified: grep -cF '        linked_service: Any = None,' packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py)
# AFTER — insert below `        linked_service: Any = None,` (verified: ui_surfaces.py:90)
        guard: Any = None,
```

### `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py` (MODIFY) — docstring
```python
# occurrences: 1 (verified: grep -cF '                when not given.' packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py)
# REPLACE the linked_service entry (:106-109, ending in `                when not given.`) with:
            linked_service: ``LinkedSurfaceService`` used by the standalone
                lane for linked envelopes (FEAT-598). Takes precedence over
                ``guard`` and the bot's ``_dataplane_guard``.
            guard: Data-plane guard used to build a ``LinkedSurfaceService``
                for the standalone lane when no ``linked_service`` is given
                (FEAT-611 M7). Falls back to ``bot._dataplane_guard``, then to
                ``guard=None`` — fail-closed (``LinkedGuardRequired`` → 403).
```

### `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py` (MODIFY) — store
```python
# occurrences: 1 (verified: grep -cF '        self._linked_service = linked_service' packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py)
# AFTER — insert below `        self._linked_service = linked_service` (verified: ui_surfaces.py:117)
        self._guard = guard
```

### `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py` (MODIFY) — resolver
```python
# occurrences: 1 (verified: grep -cF '    async def _publish_directly(' packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py)
# BEFORE — insert above `    async def _publish_directly(` (verified: ui_surfaces.py:160)
    def _resolve_linked_service(self) -> "LinkedSurfaceService":
        """Resolve the standalone lane's ``LinkedSurfaceService`` (FEAT-611 M7).

        Order: ``linked_service`` > ``LinkedSurfaceService(guard)`` >
        ``LinkedSurfaceService(bot._dataplane_guard)`` > ``LinkedSurfaceService(guard=None)``
        (fail-closed: ``ensure_snapshot`` raises ``LinkedGuardRequired``).
        """
        from parrot.outputs.a2ui.linked.service import LinkedSurfaceService

        if self._linked_service is not None:
            return self._linked_service
        # FILL IN: step 2 (self._guard is not None) -> LinkedSurfaceService(guard=self._guard);
        #   step 3 (getattr(self._bot, "_dataplane_guard", None) is not None) -> LinkedSurfaceService(guard=<that>);
        #   step 4 -> LinkedSurfaceService(guard=None) — bounded by the fixed order above and `is not None` checks (Key Constraints)

```
**Why**: the signature is fixed by spec §3 M7 (`_resolve_linked_service(self) -> "LinkedSurfaceService"`). The string annotation works under `from __future__ import annotations` without a module-level import.

### `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py` (MODIFY) — call site
```python
# occurrences: 1 (verified: grep -cF '            service = self._linked_service or LinkedSurfaceService(guard=None)' packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py)
# REPLACE :217 with
            service = self._resolve_linked_service()
```
**Why**: after this change the function-local import at :215 is unused. Remove it (`ruff` F401), because the resolver owns the import now.

### `packages/ai-parrot-tools/tests/test_publish_surface_tool_guard_resolution.py` (CREATE)
```python
"""FEAT-611 M7 — PublishSurfaceTool standalone-lane LinkedSurfaceService resolution order (spec §4)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — registers Chart under DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.linked.conditions import derive_conditions
from parrot.outputs.a2ui.linked.models import LinkedDataSource, SourceRequest
from parrot.outputs.a2ui.linked.service import LinkedGuardRequired, LinkedSurfaceService
from parrot.outputs.a2ui.models import Component, CreateSurface, Extensions, SurfaceMetadata
from parrot.tools.ui_surfaces import PublishSurfaceTool


def _linked_envelope(surface_id: str = "linked-1") -> dict:
    # FILL IN: copy verbatim from test_publish_surface_tool_linked.py:20-48 (Chart bound to /activity/rows, one source)
    ...


def _fake_store(return_value: str = "surface-1") -> MagicMock:
    store = MagicMock()
    store.save = AsyncMock(return_value=return_value)
    return store


def test_step1_explicit_linked_service_wins() -> None:
    service, guard = MagicMock(), object()
    tool = PublishSurfaceTool(linked_service=service, guard=guard, bot=SimpleNamespace(_dataplane_guard=object()))
    assert tool._resolve_linked_service() is service


def test_step2_guard_kwarg_beats_bot_guard() -> None:
    # FILL IN: guard=g, bot=SimpleNamespace(_dataplane_guard=other) -> isinstance(LinkedSurfaceService) and .guard is g
    ...


def test_step3_bot_dataplane_guard() -> None:
    # FILL IN: bot=SimpleNamespace(_dataplane_guard=g) (no publish_surface attr -> standalone lane) -> .guard is g
    ...


def test_step4_default_is_fail_closed() -> None:
    # FILL IN: PublishSurfaceTool() and PublishSurfaceTool(bot=SimpleNamespace()) -> LinkedSurfaceService with .guard is None
    ...


@pytest.mark.asyncio
async def test_no_guard_anywhere_still_raises_linked_guard_required() -> None:
    """Default behaviour preserved end to end (spec §5: no guard → 403)."""
    # FILL IN: tool = PublishSurfaceTool(surface_store=_fake_store(), bot=SimpleNamespace());
    #   with pytest.raises(LinkedGuardRequired): await tool._execute(kind="dashboard", title="L", envelope=_linked_envelope())
    #   store.save.assert_not_awaited()
    ...
```
**Why**: use `SimpleNamespace` for bots, NOT `MagicMock`. `hasattr(MagicMock(), "publish_surface")` is `True` and would route the call to the bot lane (:131). The resolver tests stay synchronous because `_resolve_linked_service` does no I/O.

### FILL IN checklist
- [ ] `ui_surfaces.py::_resolve_linked_service`: steps 2-4 with `is not None`.
- [ ] `ui_surfaces.py`: remove the now-unused local import at :215.
- [ ] Test file: `_linked_envelope` copy, and every `...` body.

---

## Acceptance Criteria

- [ ] Resolution order: `linked_service` > `guard` kwarg > `bot._dataplane_guard` > `guard=None`.
- [ ] With no guard anywhere, the standalone linked publish still raises `LinkedGuardRequired` and saves nothing.
- [ ] `test_publish_surface_tool_linked.py` passes unchanged.
- [ ] The new kwarg is optional; no public API break (spec §5).
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py packages/ai-parrot-tools/tests/test_publish_surface_tool_guard_resolution.py` is clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-tools/tests/test_publish_surface_tool_guard_resolution.py -q`
- `pytest packages/ai-parrot-tools/tests/test_publish_surface_tool_linked.py -q`

---

## Test Specification

See the CREATE block above. It has 5 tests: steps 1-4 of the resolver, plus the end-to-end fail-closed default.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**
   (`python -m scripts.sdd.ensure_worktree --slug a2ui-linked-e2e-parallel --feature-id FEAT-611`).
2. **Read the spec**: §3 M7.
3. **Check dependencies**: none.
4. **Verify the Codebase Contract**: re-run each `grep -cF` anchor.
5. **Update status** in `sdd/tasks/index/a2ui-linked-e2e-parallel.json` → `"in-progress"`.
6. **Implement** from the Blueprint, and complete every `# FILL IN:`.
7. **Verify** by running the Validation Commands.
8. **Commit the code**. Stage only the two files listed.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3837 a2ui-linked-e2e-parallel verified`.
10. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: SDD sub-agent (session_01CFWijXsJLATx5g6k94o1EP), sub-worktree feat-FEAT-611-sub-TASK-3837 (commit 0bd67f579, merged)
**Date**: 2026-09-28
**Notes**: Added the optional `guard` kwarg and `PublishSurfaceTool._resolve_linked_service()`. It resolves in this order, using `is not None` checks only: explicit `linked_service`, then the `guard` kwarg, then `bot._dataplane_guard`, then `guard=None` (fail-closed). The standalone-lane call site uses the resolver; the bot lane is untouched. The new `test_publish_surface_tool_guard_resolution.py` has 5 tests, all passing. The existing `test_publish_surface_tool_linked.py` still passes 5/5. ruff check is clean.

**Deviations from spec**: A `TYPE_CHECKING`-only import of `LinkedSurfaceService` was added so the string return annotation passes ruff F821; the runtime import stays lazy.
