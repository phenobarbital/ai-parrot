# TASK-2189: `RecipeRunner` narrative step + `dry_run` validation

**Feature**: FEAT-420 — FinanceReporter Tier-2 + Narrative Skill
**Spec**: `sdd/specs/finance-reporter-tier2-narrative.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2187, TASK-2188
**Assigned-to**: unassigned

---

## Context

Implements the **wiring half of Module 3**. This is where the fenced,
probabilistic narrative enters an otherwise strictly deterministic pipeline.

`RecipeRunner.run()` is a seven-step deterministic replay and the single path
behind chat, REST and scheduler (FEAT-324 G6). This task inserts an **eighth,
optional, awaited** step: if a `narrator` was injected AND the recipe declares
`narrative`, generate prose and write it to `data_model[output_key]`. If either
is absent, skip silently. If the narrator fails, log a warning and continue
without prose — never abort (criterion G-E).

Because `run_scheduled_refresh` takes a runner **instance**
(`system_account.py:129,145`), injecting the narrator at construction means the
scheduled path needs no change at all — whoever builds the runner decides
whether it can narrate.

---

## Scope

- Add `narrator: Optional[Narrator] = None` as a **keyword-only** ctor param on
  `RecipeRunner` (`runner.py:194-206`), stored as `self.narrator`.
- Add an async narrative step in `run()` between `_run_transforms_or_raise`
  (line 249) and `_check_bind_drift_or_raise` (line 250).
- Implement `async def _apply_narrative_best_effort(self, recipe, data_model) -> None`:
  - no-op when `recipe.narrative is None` or `self.narrator is None`
  - reads `data_model[recipe.narrative.facts_key]`; if that key is missing, log a
    warning and return (do not raise)
  - awaits `self.narrator.narrate(facts, recipe.narrative.skill)`
  - writes the result to `data_model[recipe.narrative.output_key]` only when it
    is a non-empty string; a `None` result writes nothing
  - wraps the call in `try/except Exception`, logging a WARNING and returning on
    any failure
- Extend `dry_run` (`runner.py:256`) to report a `RecipeRunError` when
  `recipe.narrative.facts_key` does not match any declared `TransformStep.output_key`.
- Write unit tests for every path.

**NOT in scope**:
- The `optional`-bind tolerance in `_check_bind_drift_or_raise` — that is
  TASK-2187, which lands first. Do not re-implement or modify it.
- The `NarrativeSpec` model or `Narrator` protocol — TASK-2188.
- Any concrete narrator implementation (TASK-2192) or figure guard (TASK-2190) —
  the runner must stay agnostic; the guard is applied *inside* the narrator.
- Validating that the skill **name** resolves against a live registry — the
  runner has no registry handle. Only the `facts_key` wiring is checkable here.
- Changing `run()`'s signature or `run_scheduled_refresh`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py` | MODIFY | `narrator` ctor param, narrative step, `dry_run` check |
| `packages/ai-parrot/tests/tools/infographic_recipes/test_runner.py` | MODIFY | Narrative-step unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Add to runner.py:
from parrot.tools.infographic_recipes.narrator import Narrator   # created by TASK-2188

# Already imported in runner.py — do not re-add:
from parrot.outputs.a2ui.recipes.models import InfographicRecipe, RecipeRunError
from parrot.outputs.a2ui.recipes.transformers import transformer_registry
import logging
from typing import Any, Optional
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunException(Exception):
    def __init__(self, error: RecipeRunError) -> None: ...   # line 88

class RecipeRunner:
    def __init__(self, store: AbstractRecipeStore, dataset_manager: DatasetManager, *,
                 artifact_store: Any = None,        # line 199
                 owner: Any = None) -> None:        # line 200   (def at line 194)
        self.store = store                          # line 202
        self.dataset_manager = dataset_manager      # line 203
        self.artifact_store = artifact_store        # line 204
        self.owner = owner                          # line 205
        self.logger = logging.getLogger(...)        # line 206   <-- use for warnings

    async def run(self, name: str, *, params=None, pctx=None,
                  recipe_owner: Optional[str] = None) -> RenderedArtifact:   # line 208
        recipe = await self._load_recipe(name, recipe_owner)                  # line 245
        resolved_params = self._resolve_params_or_raise(recipe, params)       # line 246
        frames = await self._fetch_frames(recipe, resolved_params, pctx)     # line 247
        self._run_gate_or_raise(recipe, frames)                              # line 248
        data_model = self._run_transforms_or_raise(recipe, frames, resolved_params)  # line 249
        # <<< INSERT THE AWAITED NARRATIVE STEP HERE >>>
        self._check_bind_drift_or_raise(recipe, data_model)                   # line 250
        envelope = self._assemble_envelope_or_raise(recipe, data_model)       # line 251
        artifact = await self._render_or_raise(recipe, envelope)              # line 252
        await self._deliver_best_effort(recipe, artifact)                     # line 253
        return artifact                                                      # line 254

    async def dry_run(self, recipe: InfographicRecipe) -> list[RecipeRunError]:  # line 256
        """Validates steps 1/3/5 only — no fetch, no render. Returns ALL problems."""
        errors: list[RecipeRunError] = []                                    # line 272
        ...  # existing checks: param resolution, transformer registration,
             # metadata column gate, layout $bind top-key vs declared output_key

    def _run_transforms_or_raise(self, recipe, frames, resolved_params
                                 ) -> dict[str, Any]: ...   # line 448 — SYNC, not async
        # data_model[step.output_key] = result               # line 487
        # returns data_model                                 # line 488

    def _check_bind_drift_or_raise(self, recipe, data_model) -> None: ...  # line 490
        # MODIFIED BY TASK-2187 to honour `optional` — do not touch it here

# _deliver_best_effort is the naming precedent for a non-fatal step:
    async def _deliver_best_effort(self, recipe, artifact): ...   # line ~549
```

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py  (from TASK-2188)
class NarrativeSpec(BaseModel):
    skill: str
    facts_key: str
    output_key: str = "narrative"
class InfographicRecipe(BaseModel):
    narrative: Optional[NarrativeSpec] = None      # added by TASK-2188
    transforms: list[TransformStep] = Field(default_factory=list)   # line 191
class TransformStep(BaseModel):
    output_key: str                                # the set dry_run checks facts_key against
class RecipeRunError(BaseModel):                   # line 240
    recipe: Optional[str]; stage: Optional[str]; detail: Optional[str]
    transformer: Optional[str] = None               # line 256
    dataset: Optional[str] = None                   # line 257
    missing_columns: list[str] = Field(default_factory=list)   # line 258
```

```python
# packages/ai-parrot/src/parrot/tools/infographic_recipes/narrator.py  (from TASK-2188)
@runtime_checkable
class Narrator(Protocol):
    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]: ...
    # Contract: implementations return None on failure, they do NOT raise.
    # This step still defends with try/except — belt and braces.
```

```python
# packages/ai-parrot/src/parrot/auth/system_account.py — WHY NO CHANGE IS NEEDED
async def run_scheduled_refresh(runner: Any, name: str, *, params=None,
                                recipe_owner=None, channel="scheduler",
                                account=None) -> Any: ...    # line 129
    """Args: runner: A ``RecipeRunner`` instance (its ``run`` coroutine is awaited)."""  # line 145
    # Docstring line 142: "RecipeRunner is NEVER modified and pctx=None is NEVER forwarded"
# => narrator injection happens at construction; this function is untouched.
```

### Does NOT Exist

- ~~`RecipeRunner.narrator`~~ — this task adds it.
- ~~`RecipeRunner._apply_narrative_best_effort`~~ — this task creates it.
- ~~any existing LLM/async step inside `run()`~~ — lines 245-254 contain none.
- ~~`_run_transforms_or_raise` being a coroutine~~ — it is **sync** (line 448).
  Do NOT `await` it and do NOT fold the narrative into its loop.
- ~~a `narrative` stage value in `RecipeRunError`~~ — `stage` is a free string;
  use `"narrative"` consistently if you must emit one, but note this step is
  **best-effort and does not raise at run time**, so it should not normally
  produce a `RecipeRunError` during `run()` — only during `dry_run()`.
- ~~a skill registry reachable from `runner.py`~~ — there is none. Do not import
  `parrot.skills` here; validating the skill *name* is out of scope.
- ~~`transformer_registry` containing narrative skills~~ — skills are not
  transformers; do not look the skill up there.
- ~~changing `run_scheduled_refresh`~~ — verified unnecessary.

---

## Implementation Notes

### Pattern to Follow

```python
# Follow the _deliver_best_effort naming/posture precedent: a non-fatal awaited
# step that logs and returns rather than raising.

async def _apply_narrative_best_effort(
    self, recipe: InfographicRecipe, data_model: dict[str, Any]
) -> None:
    """Populate ``data_model`` with LLM prose, best-effort (spec criterion G-E).

    Never raises: a missing narrator, a missing facts key, or any narrator
    failure leaves ``data_model`` untouched so the replay still renders.
    """
    spec = recipe.narrative
    if spec is None or self.narrator is None:
        return
    if spec.facts_key not in data_model:
        self.logger.warning(
            "Recipe %r declares narrative facts_key %r, absent from the data_model "
            "(keys: %s) — skipping narrative.",
            recipe.name, spec.facts_key, sorted(data_model),
        )
        return
    try:
        prose = await self.narrator.narrate(data_model[spec.facts_key], spec.skill)
    except Exception as exc:  # noqa: BLE001 — narrative is never fatal
        self.logger.warning(
            "Narrator failed for recipe %r (skill=%r): %s — rendering without prose.",
            recipe.name, spec.skill, exc,
        )
        return
    if isinstance(prose, str) and prose.strip():
        data_model[spec.output_key] = prose
    else:
        self.logger.info(
            "Narrator returned no prose for recipe %r — rendering without it.", recipe.name
        )

# In run(), between lines 249 and 250:
data_model = self._run_transforms_or_raise(recipe, frames, resolved_params)
await self._apply_narrative_best_effort(recipe, data_model)
self._check_bind_drift_or_raise(recipe, data_model)
```

### Key Constraints

- **The narrative step must never raise during `run()`.** That is the whole
  point of criterion G-E. `dry_run()` is where narrative misconfiguration is
  surfaced loudly.
- **Do not mutate anything but `data_model[output_key]`.** No writes to the
  facts key, no reshaping of transform output.
- **Order matters**: the step must run *before* the drift check, so an optional
  narrative bind resolves when prose was produced.
- Keyword-only ctor param, defaulting to `None` — existing
  `RecipeRunner(store, dm)` call sites must keep working unchanged.
- `dry_run` collects **all** problems rather than raising on the first (see its
  docstring at line 258) — append to `errors`, do not raise.
- Use `self.logger` (line 206), never `print`.
- TASK-2187 lands first and also edits this file. Rebase/merge carefully and do
  not revert its `_check_bind_drift_or_raise` changes.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py:245-254` — the pipeline
- `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py:~549` —
  `_deliver_best_effort`, the best-effort posture to mirror
- `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py:1523-1548` —
  `_maybe_enhance`'s degrade-on-failure logging style (the established precedent
  for an optional LLM pass; note the lane itself is deprecated, only the *posture*
  is being reused)
- `packages/ai-parrot/tests/tools/infographic_recipes/test_runner.py` — existing
  pipeline/order/binding/error test style

---

## Acceptance Criteria

- [ ] `RecipeRunner(store, dm)` still constructs (backwards compatible)
- [ ] `RecipeRunner(store, dm, narrator=stub)` stores `self.narrator`
- [ ] `narrator=None` + recipe with `narrative` → run succeeds, `output_key` absent from `data_model`
- [ ] narrator present + recipe with `narrative` → prose lands at `narrative.output_key`
- [ ] narrator present + `recipe.narrative is None` → narrator is never called
- [ ] narrator raising → WARNING logged, run completes, no prose
- [ ] narrator returning `None` / `""` / whitespace → no key written, run completes
- [ ] `facts_key` absent from `data_model` → WARNING logged, narrator not called, run completes
- [ ] The narrative step runs **before** `_check_bind_drift_or_raise`
- [ ] `dry_run` returns a `RecipeRunError` when `facts_key` matches no declared `output_key`
- [ ] `dry_run` returns no narrative error for a correctly wired recipe
- [ ] `_run_transforms_or_raise` is still sync and unmodified
- [ ] `parrot/auth/system_account.py` is **unmodified**
- [ ] TASK-2187's `optional`-bind behaviour still passes (no regression)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/infographic_recipes/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/infographic_recipes/test_runner.py  (append)
from typing import Any, Optional

import pytest


class _OkNarrator:
    def __init__(self):
        self.calls = []

    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]:
        self.calls.append((facts, skill))
        return "Revenue is running behind budget, with the gap narrowing."


class _RaisingNarrator:
    async def narrate(self, facts, skill):
        raise RuntimeError("LLM exploded")


class _EmptyNarrator:
    async def narrate(self, facts, skill):
        return None


class TestNarrativeStep:
    async def test_no_narrator_skips_and_succeeds(self, ...):
        """G-E: pure replay never fails for lack of an LLM."""

    async def test_narrator_populates_output_key(self, ...):
        """Prose lands at narrative.output_key."""

    async def test_narrator_not_called_without_narrative_spec(self, ...):
        narrator = _OkNarrator()
        # run a recipe whose narrative is None
        assert narrator.calls == []

    async def test_narrator_exception_degrades(self, caplog, ...):
        """WARNING logged; run still returns an artifact."""

    async def test_empty_prose_writes_nothing(self, ...):
        """None/blank result must not create the key."""

    async def test_missing_facts_key_warns_and_skips(self, caplog, ...):
        """Narrator is not called when facts_key is absent from the data_model."""

    async def test_narrative_runs_before_drift_check(self, ...):
        """An optional narrative bind resolves when prose was produced."""

    def test_backwards_compatible_ctor(self, ...):
        """RecipeRunner(store, dm) still works."""


class TestDryRunNarrative:
    async def test_dry_run_flags_facts_key_mismatch(self, ...):
        """facts_key naming no declared output_key -> a RecipeRunError."""

    async def test_dry_run_clean_for_wired_narrative(self, ...):
        """Correctly wired narrative produces no error."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 Component Diagram shows exactly
   where the step sits; §7 Known Risks flags the sync-vs-async trap)
2. **Check dependencies** — TASK-2187 and TASK-2188 must be in
   `sdd/tasks/completed/`. TASK-2187 edits the same file; confirm its changes are
   present before you start and do not revert them.
3. **Verify the Codebase Contract** — re-read `runner.py:194-206` and `245-254`;
   confirm `Narrator` and `NarrativeSpec` exist as TASK-2188 left them
4. **Update status** in `sdd/tasks/index/finance-reporter-tier2-narrative.json`
   → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met, including the no-regression ones
7. **Move this file** to `sdd/tasks/completed/TASK-2189-runner-narrative-step.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
