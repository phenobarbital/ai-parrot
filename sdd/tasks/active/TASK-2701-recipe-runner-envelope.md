# TASK-2701: RecipeRunner envelope exposure (`include_envelope`)

**Feature**: FEAT-492 — A2UI Surface Rehydration
**Spec**: `sdd/specs/a2ui-surface-rehydration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (goal G8, resolved Open Question 1). The refresh lane needs
the **assembled `CreateSurface` envelope**, but `RecipeRunner.run()` returns
only a `RenderedArtifact`. The envelope already exists internally
(`_assemble_envelope_or_raise`, runner.py:607) — this task exposes it on the
result behind an opt-in flag, with zero behavior change for existing callers.

---

## Scope

- Add `include_envelope: bool = False` keyword to `RecipeRunner.run()`
  (`packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py:242`).
- When `True`: after `_assemble_envelope_or_raise(...)` produces the envelope
  and `_render_or_raise(...)` returns the artifact, attach
  `envelope.model_dump(by_alias=True, mode="json")` at
  `artifact.metadata["source_envelope"]` before returning.
- When `False` (default): byte-identical behavior — the key must NOT appear.
- Google-style docstring update for `run()` documenting the flag and the
  reserved metadata key.
- Unit tests in
  `packages/ai-parrot/tests/tools/test_recipe_runner_envelope.py`.

**NOT in scope**: any handler/store code (TASK-2700/2702), changes to
`_assemble_envelope_or_raise`/`_render_or_raise` themselves, changes to
`persist_envelope` or `RenderedArtifact`'s model.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py` | MODIFY | `include_envelope` flag + metadata attach |
| `packages/ai-parrot/tests/tools/test_recipe_runner_envelope.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-09-01 against `dev`.

### Verified Imports
```python
from parrot.tools.infographic_recipes.runner import RecipeRunner   # verified: runner.py:204
from parrot.outputs.a2ui.artifacts import RenderedArtifact         # verified: artifacts.py:54
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunner:                                                # line 204
    async def run(self, name: str, *, params: dict[str, Any] | None = None,
                  pctx: Any | None = None,
                  recipe_owner: Optional[str] = None) -> RenderedArtifact:   # line 242
        # pipeline (verbatim call order inside run()):
        #   recipe = await self._load_recipe(name, recipe_owner)
        #   resolved_params = self._resolve_params_or_raise(recipe, params)
        #   frames = await self._fetch_frames(recipe, resolved_params, pctx)
        #   self._run_gate_or_raise(recipe, frames)
        #   data_model = self._run_transforms_or_raise(recipe, frames, resolved_params)
        #   await self._apply_narrative_best_effort(recipe, data_model)
        #   self._check_bind_drift_or_raise(recipe, data_model)
        #   envelope = self._assemble_envelope_or_raise(recipe, data_model)   # ← the envelope
        #   artifact = await self._render_or_raise(recipe, envelope)
        #   await self._deliver_best_effort(recipe, artifact)
        #   return artifact
    def _assemble_envelope_or_raise(self, recipe, data_model): ...           # line 607 — returns CreateSurface
    async def _render_or_raise(self, recipe, envelope) -> RenderedArtifact:  # line 631

# packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py:54
class RenderedArtifact(BaseModel):
    metadata: dict[str, Any]          # free-form renderer metadata — attach here
```

### Does NOT Exist
- ~~`RecipeRunner.run(include_envelope=...)`~~ — THIS task adds it
- ~~`RenderedArtifact.metadata["source_envelope"]`~~ — key defined by THIS task
- ~~`RenderedArtifact.envelope` attribute~~ — do NOT add a model field; use `metadata`
- ~~an envelope-returning `run()` overload/second return value~~ — rejected; signature stays `-> RenderedArtifact`

---

## Implementation Notes

### Pattern to Follow
```python
artifact = await self._render_or_raise(recipe, envelope)
if include_envelope:
    artifact.metadata["source_envelope"] = envelope.model_dump(
        by_alias=True, mode="json"
    )
await self._deliver_best_effort(recipe, artifact)
```
(The dump call matches `persist_envelope`'s convention —
`outputs/a2ui/baking.py:399` — so the stored value is the exact
`navigator.ui_surfaces.envelope` shape.)

### Key Constraints
- Non-breaking: default `False`; no reordering of the pipeline; delivery
  still runs after the attach so delivered artifacts carry the key too.
- Do not deep-copy the envelope — the dump is already a fresh dict.
- Keep the flag keyword-only.

### References in Codebase
- `packages/ai-parrot/src/parrot/outputs/a2ui/baking.py:399` — dump convention
- `examples/agents/a2ui/deterministic_refresh_dashboard.py` — the consumer pattern this enables

---

## Acceptance Criteria

- [ ] `run(include_envelope=True)` → `metadata["source_envelope"]` present and
      validates via `CreateSurface.model_validate`
- [ ] `run()` default → key absent; existing tests untouched and green
- [ ] Docstring documents the flag and the reserved key
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/test_recipe_runner_envelope.py -v`
- [ ] Existing runner tests still pass: `pytest packages/ai-parrot/tests -k recipe -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_recipe_runner_envelope.py
# Stub the pipeline stages (monkeypatch _load_recipe/_fetch_frames/... or use
# the existing recipe test fixtures under packages/ai-parrot/tests/) so run()
# executes without a live DatasetManager.

async def test_include_envelope_attaches_valid_dump(): ...
async def test_default_run_has_no_source_envelope_key(): ...
async def test_envelope_dump_rehydrates_via_create_surface(): ...
async def test_delivery_receives_artifact_with_envelope_key(): ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 2, §6, §8 resolved Q1).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** (runner may have shifted — re-grep line numbers).
4. **Update status** in `sdd/tasks/index/a2ui-surface-rehydration.json` → `"in-progress"`.
5. **Implement**, **verify**, **move to completed**, update index, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
