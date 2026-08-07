# TASK-2187: Optional data bindings (`optional` flag on `$bind`)

**Feature**: FEAT-420 — FinanceReporter Tier-2 + Narrative Skill
**Spec**: `sdd/specs/finance-reporter-tier2-narrative.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec. This is the mechanism that makes criterion
**G-E** true: *a pure replay must never fail for lack of an LLM.*

When no narrator is injected, the narrative step is skipped and `/narrative`
never lands in the `data_model`. Today that is fatal twice over — the runner's
bind-drift check raises (`runner.py:490-510`) and the bake pass raises
`BakeError` (`baking.py:78-81`). This task teaches both to tolerate a binding
explicitly marked `optional`.

The encoding was verified safe during spec research: `is_binding_expression` is a
membership test (`models.py:90`) and `_validate_bindings` validates only the
pointer shape then returns (`models.py:102-109`), so a sibling key breaks
neither detection nor validation. **`a2ui/models.py` needs no change** — do not
modify it.

---

## Scope

- Teach `_resolve_value` (`baking.py:60-86`) to honour `optional`: when an
  optional binding's pointer does not resolve, the property is **omitted**
  rather than raising `BakeError`. A non-optional unresolved pointer must still
  raise, unchanged.
- Teach `_check_bind_drift_or_raise` (`runner.py:490-510`) to exclude optional
  pointers from the fatal `missing` set, and to log them at INFO when absent so
  a genuine drift is never silently swallowed.
- Update `_collect_bind_pointers` (`runner.py`, used at line 496) so it can
  distinguish optional from required pointers.
- Ensure the `optional` marker key never leaks into rendered output (it is
  metadata, not a property value).
- Write unit tests covering both the tolerate and the still-raise paths.

**NOT in scope**:
- `parrot/outputs/a2ui/models.py` — verified tolerant, must stay untouched.
- The `narrative` recipe field or the `Narrator` protocol (TASK-2188).
- The runner's narrative step itself (TASK-2189).
- Any renderer change — `ReportComponent.lower` already omits absent
  `text`/`summary` (`report.py:105,124`) and `_render_infographic` already omits
  absent section `text` (`interactive_html.py:445-447`). Verified; do not touch
  `ai-parrot-visualizations`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/baking.py` | MODIFY | `_resolve_value` omits unresolved optional bindings instead of raising |
| `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py` | MODIFY | `_collect_bind_pointers` + `_check_bind_drift_or_raise` honour `optional` |
| `packages/ai-parrot/tests/outputs/a2ui/test_artifacts.py` | MODIFY | Bake-pass tests (this is where `bake_envelope` is already tested) |
| `packages/ai-parrot/tests/tools/infographic_recipes/test_runner.py` | MODIFY | Drift-check tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already imported in baking.py — do not re-add:
from parrot.outputs.a2ui.models import BINDING_KEY, CreateSurface, is_binding_expression  # baking.py:22

# For tests:
from parrot.outputs.a2ui.baking import BakeError, bake_envelope
from parrot.outputs.a2ui.models import BINDING_KEY, Component, CreateSurface
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/baking.py
class BakeError(Exception): ...                                     # line 31
def _load_jsonpointer(): ...                                        # line 42 (lazy, G8)
def _resolve_value(value: Any, data_model: dict[str, Any]) -> Any:   # line 60
    jsonpointer = _load_jsonpointer()                               # line 73
    if is_binding_expression(value):                                # line 74
        pointer = value[BINDING_KEY]                                # line 75
        try:
            return jsonpointer.resolve_pointer(data_model, pointer) # line 77
        except jsonpointer.JsonPointerException as exc:
            raise BakeError(                                        # lines 79-81  <-- CHANGE HERE
                f"Unresolvable data-model binding {pointer!r}: {exc}"
            ) from exc
    if isinstance(value, dict):                                     # line 82
        return {key: _resolve_value(item, data_model) for key, item in value.items()}  # line 83
    if isinstance(value, list): ...                                 # lines 84-85
    return value                                                    # line 86
def _has_live_binding(value: Any) -> bool: ...                       # line 89
def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]]: ...  # line 100
    # raises BakeError at line 120 if a live binding survives the pass
```

```python
# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
def _pointer_top_key(pointer: str) -> str: ...        # module-level helper
def _collect_bind_pointers(value: Any) -> ...: ...    # module-level helper  <-- CHANGE HERE

class RecipeRunner:
    def _check_bind_drift_or_raise(                    # line 490
        self, recipe: InfographicRecipe, data_model: dict[str, Any]
    ) -> None:
        missing = sorted(                                                   # line 493
            {
                pointer
                for pointer in _collect_bind_pointers(recipe.layout.properties)  # line 496
                if _pointer_top_key(pointer) not in data_model                   # line 497
            }
        )
        if missing:                                                         # line 500
            raise RecipeRunException(
                RecipeRunError(
                    recipe=recipe.name, stage="layout",                     # lines 503-504
                    detail=(f"$bind pointer(s) {missing!r} reference key(s) absent "
                            f"from the assembled data_model (keys present: ...)"),
                )
            )
```

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/models.py — VERIFIED, DO NOT MODIFY
BINDING_KEY = "$bind"                                            # line 50
def is_binding_expression(value: Any) -> bool:                    # line 79
    return isinstance(value, dict) and BINDING_KEY in value       # line 90
    # <-- membership test: {"$bind": ..., "optional": True} IS still a binding
def _validate_bindings(value: Any) -> None:                       # line 93
    if is_binding_expression(value):                              # line 102
        pointer = value[BINDING_KEY]                              # line 103
        if not isinstance(pointer, str) or not is_valid_pointer(pointer):  # line 104
            raise ValueError(...)                                 # lines 105-108
        return                                                    # line 109
    # <-- validates ONLY the pointer shape, then returns. Sibling keys are
    #     neither rejected nor stripped. NO CHANGE REQUIRED HERE.
class Component(BaseModel):                                       # line 123
    model_config = ConfigDict(populate_by_name=True, extra="allow")  # line 137
```

```python
# The binding shape this task introduces (no model change needed):
{"$bind": "/narrative/headline", "optional": True}
```

### Does NOT Exist

- ~~`is_optional_binding()`~~ / ~~`OPTIONAL_KEY` constant~~ — do not exist; if you
  add a helper, put it in `a2ui/models.py` **only** as a pure additive read-only
  predicate, or keep it local. Do NOT change `is_binding_expression`.
- ~~`_validate_bindings` rejecting sibling keys~~ — verified it does not
  (`models.py:102-109`). Do not "fix" it.
- ~~a `$optional` marker key convention~~ — the spec settled on a plain
  `optional` sibling key; verified compatible.
- ~~`_resolve_value` returning a sentinel today~~ — it either resolves or raises;
  there is no existing "absent" representation. You must introduce one and
  ensure the caller (`_resolve_value`'s dict branch at line 83) drops the key
  rather than storing the sentinel.
- ~~`optionalBinds` list on `LayoutSpec`~~ — considered in brainstorm, NOT chosen.
- ~~a renderer-side change~~ — `ai-parrot-visualizations` is out of scope and an
  acceptance criterion in the spec forbids modifying it.

---

## Implementation Notes

### Pattern to Follow

```python
# baking.py — the dict branch (line 83) must DROP omitted keys, not store a sentinel.
_ABSENT = object()   # module-private sentinel

def _resolve_value(value: Any, data_model: dict[str, Any]) -> Any:
    jsonpointer = _load_jsonpointer()
    if is_binding_expression(value):
        pointer = value[BINDING_KEY]
        try:
            return jsonpointer.resolve_pointer(data_model, pointer)
        except jsonpointer.JsonPointerException as exc:
            if value.get("optional"):
                logger.info("Optional binding %r did not resolve; omitting.", pointer)
                return _ABSENT
            raise BakeError(f"Unresolvable data-model binding {pointer!r}: {exc}") from exc
    if isinstance(value, dict):
        resolved = {k: _resolve_value(v, data_model) for k, v in value.items()}
        return {k: v for k, v in resolved.items() if v is not _ABSENT}   # drop absent
    if isinstance(value, list):
        items = [_resolve_value(i, data_model) for i in value]
        return [i for i in items if i is not _ABSENT]
    return value
```

### Key Constraints

- **G8**: `baking.py` must keep importing `jsonpointer` lazily
  (`baking.py:35-57`). Do not hoist the import.
- **No regression**: a required (non-optional) unresolved binding must still
  raise `BakeError` with the *same* message text — there are existing tests
  depending on it.
- `bake_envelope` also raises if a live binding *survives* the pass
  (`baking.py:120`). Omitting a property removes the binding entirely, so this
  check stays satisfied — verify with a test.
- The `optional` key must not appear in baked output. Since the whole binding
  mapping is replaced (or dropped), this follows naturally — assert it.
- **Ordering**: TASK-2189 also edits `_check_bind_drift_or_raise`. This task
  lands first; TASK-2189 builds on it.
- Log at INFO, not DEBUG, when an optional bind is absent — an operator
  diagnosing "why is there no narrative" needs it visible without a debug build.

### References in Codebase

- `packages/ai-parrot/src/parrot/outputs/a2ui/baking.py:60-97` — the function to change
- `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py:490-510` — the drift check
- `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/report.py:105,124` —
  the graceful-omission behaviour downstream that this task's output feeds
- `packages/ai-parrot/tests/outputs/a2ui/test_artifacts.py` — existing bake tests

---

## Acceptance Criteria

- [ ] An unresolved binding marked `optional: True` omits the property; no exception
- [ ] An unresolved binding **without** `optional` still raises `BakeError`, message unchanged
- [ ] A resolvable binding marked `optional: True` resolves normally (flag is inert on success)
- [ ] `_check_bind_drift_or_raise` does not raise for a missing optional pointer
- [ ] `_check_bind_drift_or_raise` still raises for a missing required pointer, diagnostic unchanged
- [ ] An absent optional bind is logged at INFO with its pointer
- [ ] The `optional` key never appears in baked output
- [ ] `bake_envelope`'s surviving-live-binding check (`baking.py:120`) still passes when an optional bind was omitted
- [ ] `parrot/outputs/a2ui/models.py` is **unmodified** (`git diff --stat` shows no change)
- [ ] `ai-parrot-visualizations` is **unmodified**
- [ ] `jsonpointer` is still imported lazily (G8) — `import parrot.outputs.a2ui.baking` works without the extra installed
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/test_artifacts.py packages/ai-parrot/tests/tools/infographic_recipes/test_runner.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/baking.py packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/test_artifacts.py  (append)
import pytest
from parrot.outputs.a2ui.baking import BakeError, bake_envelope
from parrot.outputs.a2ui.models import Component, CreateSurface


def _surface(props: dict, data_model: dict) -> CreateSurface:
    return CreateSurface(
        surfaceId="s", catalogId="parrot.v1",
        components=[Component(id="blk-000", component="Card", properties=props)],
        dataModel=data_model,
    )


class TestOptionalBindings:
    def test_optional_absent_omits_property(self):
        baked = bake_envelope(_surface(
            {"title": "T", "body": {"$bind": "/narrative/headline", "optional": True}},
            {},
        ))
        assert "body" not in baked[0]["properties"]
        assert baked[0]["properties"]["title"] == "T"

    def test_required_absent_still_raises(self):
        with pytest.raises(BakeError, match="Unresolvable data-model binding"):
            bake_envelope(_surface({"body": {"$bind": "/narrative/headline"}}, {}))

    def test_optional_present_resolves(self):
        baked = bake_envelope(_surface(
            {"body": {"$bind": "/narrative/headline", "optional": True}},
            {"narrative": {"headline": "Revenue is behind plan."}},
        ))
        assert baked[0]["properties"]["body"] == "Revenue is behind plan."

    def test_optional_marker_never_leaks(self):
        baked = bake_envelope(_surface(
            {"body": {"$bind": "/x", "optional": True}}, {"x": "v"},
        ))
        assert "optional" not in str(baked)

    def test_no_live_binding_survives_omission(self):
        """bake_envelope's own surviving-binding check (baking.py:120) still passes."""
        bake_envelope(_surface({"body": {"$bind": "/absent", "optional": True}}, {}))


# packages/ai-parrot/tests/tools/infographic_recipes/test_runner.py  (append)
class TestDriftCheckOptional:
    def test_drift_tolerates_optional(self):
        """A layout binding marked optional does not abort the run."""

    def test_drift_still_fails_required(self):
        """A missing required pointer raises RecipeRunException, stage='layout'."""

    def test_absent_optional_logged_at_info(self, caplog):
        """Operator-visible: the absent optional pointer appears in INFO logs."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§7 Known Risks explains why the
   `baking.py` half is load-bearing: `_render_via_lowering` passes `{}` as
   data_model at `interactive_html.py:306`, so binds inside a `Report` are
   resolved by the bake pass, not the renderer)
2. **Check dependencies** — none; can start immediately
3. **Verify the Codebase Contract** — re-read `baking.py:60-86`,
   `runner.py:490-510` and `models.py:90,102-109` before changing anything
4. **Update status** in `sdd/tasks/index/finance-reporter-tier2-narrative.json`
   → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met — including the two "unmodified"
   criteria, via `git diff --stat`
7. **Move this file** to `sdd/tasks/completed/TASK-2187-optional-data-bindings.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
