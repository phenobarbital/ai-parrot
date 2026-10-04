# TASK-3846: DashboardWidget model and _build_linked_source extraction

**Feature**: FEAT-610 — A2UI Linked Surfaces E2E example
**Spec**: `sdd/specs/a2ui-linked-e2e-test.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3841
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models + §3 Module 2 (FEAT-610), §7 "Patterns to Follow". The dashboard tool must reuse the
single-component source derivation of `build_linked_surface` (`toolkit.py:365-386`) — extract it, do not fork it.

---

## Scope

- `models.py`: add `DashboardWidget` exactly as spec §2.
- `toolkit.py`: extract `_build_linked_source(self, widget: DashboardWidget, detail: SlugDetail) -> LinkedDataSource`
  from `build_linked_surface` (placeholder/filter validation, `reject_variable_values`, forced/locked params,
  `derive_conditions`, transform, target `/{key}/rows`, refresh). `build_linked_surface` builds a `DashboardWidget`
  from its args and calls the helper — behaviour unchanged.
- New `test_dashboard_widget_model.py`.

**NOT in scope**: `build_linked_dashboard` itself (TASK-3847). `DashboardWidget` has no `transform` field in the spec;
pass the single-surface `transform` into the helper via an optional keyword.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/models.py` | MODIFY | DashboardWidget |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | _build_linked_source + caller |
| `packages/ai-parrot-tools/tests/querysource/test_dashboard_widget_model.py` | CREATE | model + helper tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `f20d82332` (dev, 2026-09-29). Re-check line numbers before editing — earlier tasks in this
> feature may have shifted them.

### Verified Imports
```python
from parrot.outputs.a2ui.linked.conditions import derive_conditions      # conditions.py:17 (imported lazily inside methods)
from parrot.outputs.a2ui.linked.models import LinkedDataSource, RefreshPolicy, SourceRequest, TransformSpec  # models.py:192,43,30,178
from parrot_tools.querysource.models import SlugDetail                   # models.py:38
```
### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
    async def build_linked_surface(self, slug, component, request=None, tenant=None, snapshot=True, surface_id=None,
        target_key=None, refresh=None, transform=None) -> dict[str, Any]:   # line 339; source build lines 365-386:
        detail = await self.describe_slug(slug, tenant=tenant)
        req = SourceRequest.model_validate(request or {})
        validate_placeholders(dict(req.placeholders), set(detail.placeholders))
        validate_filter(dict(req.filter))
        forced = dict(self.forced_conditions)
        reject_variable_values({**req.placeholders, "filter": req.filter, **forced})
        params, locked = self._linked_params(detail, forced)
        key = target_key or self._default_target_key(slug)
        source = LinkedDataSource(slug=..., tenant=..., is_multiquery=detail.is_multiquery,
            conditions=derive_conditions(req, locked={name: forced[name] for name in locked}), request=req,
            params=params, locked=locked, transform=..., target=f"/{key}/rows", refresh=RefreshPolicy.model_validate(refresh or {}))
    def _linked_params(self, detail: SlugDetail, forced: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:  # line 415
# packages/ai-parrot-tools/src/parrot_tools/querysource/models.py — imports `Any, Literal`, `BaseModel, Field` already (lines 5-7); class SavedSlug at :119
```
### Does NOT Exist
- ~~`DashboardWidget`~~ / ~~`_build_linked_source`~~ — created here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/querysource/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/querysource/test_dashboard_widget_model.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit.build_linked_surface",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit._linked_params"
  ]
}
```

---

## Implementation Notes

- Parallelism: depends on TASK-3841: both modify querysource/models.py (DialectReference vs DashboardWidget) — serialized, lower id first.
- Production data: any live query uses `ENV=prod`, read-only. Never commit tokens, passwords or DSNs.
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src:packages/ai-parrot-server/src`
  as needed; never `uv sync` inside a worktree.

---

## Implementation Blueprint

**Steps (in order)**
1. Add `DashboardWidget` above `class DialectReference(BaseModel):` in models.py.
2. Add `_build_linked_source` directly above `def _linked_params` and move lines 367-386 into it.
3. Rewrite the top of `build_linked_surface` to use it (keep `describe_slug` in the caller — the helper is sync and
   gets `detail`). Existing tests must stay green — that is the proof the extraction is behaviour-neutral.

```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/models.py — BEFORE `class DialectReference(BaseModel):` (verified: models.py:127, occurrences: 1)
class DashboardWidget(BaseModel):
    """One widget of a linked dashboard: its own source key, slug, request, and unbound component (FEAT-610)."""

    key: str  # data-model root + source key (JSON-pointer-safe)
    slug: str
    component: dict[str, Any]  # Chart | DataTable | KPICard, without its binding
    request: dict[str, Any] | None = None  # qs grammar: placeholders/filter/fields/ordering/grouping/limit/offset
    tenant: str | None = None
    section: Literal["kpis", "charts", "table"] | None = None  # layout row; inferred from component when None
    refresh: dict[str, Any] | None = None  # RefreshPolicy payload
```
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py — BEFORE `    def _linked_params(self, detail: SlugDetail, forced: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:` (verified: toolkit.py:415, occurrences: 1)
    def _build_linked_source(
        self, widget: DashboardWidget, detail: SlugDetail, *, transform: dict[str, Any] | None = None
    ) -> LinkedDataSource:
        """Validate one widget's request and build its LinkedDataSource (shared by the linked-surface tools)."""
        from parrot.outputs.a2ui.linked.conditions import derive_conditions
        from parrot.outputs.a2ui.linked.models import LinkedDataSource, RefreshPolicy, SourceRequest, TransformSpec

        # FILL IN: move toolkit.py:366-386 here verbatim, using widget.request / widget.tenant / widget.slug /
        #   widget.key / widget.refresh — bounded by: identical validation order and identical LinkedDataSource fields.
```
**Why**: `LinkedDataSource` in the annotation needs `from __future__ import annotations` (already at toolkit.py:8)
plus a `TYPE_CHECKING` import — FILL IN: add `if TYPE_CHECKING: from parrot.outputs.a2ui.linked.models import LinkedDataSource`
only if ruff flags F821. Import `DashboardWidget` from `parrot_tools.querysource.models` next to `SlugDetail`.

```python
# packages/ai-parrot-tools/tests/querysource/test_dashboard_widget_model.py — CREATE
"""FEAT-610 TASK-3846 — DashboardWidget + _build_linked_source."""

from __future__ import annotations

from parrot_tools.querysource.models import DashboardWidget


def test_dashboard_widget_defaults() -> None:
    w = DashboardWidget(key="kpi_total", slug="polestar_graduates_directory", component={"component": "KPICard"})
    assert w.request is None and w.section is None and w.tenant is None


# FILL IN: one test using the `patched_qs` fixture (conftest.py) that builds a source via _build_linked_source
#   and asserts target == "/<key>/rows" and conditions match build_linked_surface's for the same request.
```
**FILL IN checklist**
- [ ] move the source-building body; rewire `build_linked_surface`; TYPE_CHECKING import if needed; helper test.

---

## Acceptance Criteria

- [ ] `DashboardWidget` matches spec §2.
- [ ] `build_linked_surface` behaviour unchanged (its existing test file passes).
- [ ] `_build_linked_source` is the only place a linked source is built in the toolkit.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/querysource/test_dashboard_widget_model.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_build_linked_surface_tool.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_models.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_dashboard_widget_defaults` | §2 model |
| helper parity test | extraction is neutral |

---

## Agent Instructions

1. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
2. Implement exactly the files listed; no refactors outside scope.
3. `ruff check --fix` the touched Python files; run the Validation Commands.
4. Commit code only: `feat(a2ui-linked-e2e-test): TASK-3846 — DashboardWidget model and _build_linked_source extraction`.
5. Close with `scripts/sdd/close_task.sh TASK-3846 a2ui-linked-e2e-test verified` and fill the Completion Note.

---

## Completion Note

Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Tokens: n/a

DashboardWidget model + QuerysourceToolkit._build_linked_source extracted from build_linked_surface (behaviour-preserving). querysource suite: 102 passed. Merge-tier sweep skipped (env-red, see TASK-3842).
