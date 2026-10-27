# TASK-4758: EmbeddingIntentRouter: string labels + shared encoder

**Feature**: FEAT-755 — Inline A2UI Component Routing
**Spec**: `sdd/specs/inline-a2ui-component-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4757
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. The router engine currently keys its encoded phrase bank by
`OutputMode` and returns a bare `OutputMode` in `RouteScore`. This task makes the
engine label-agnostic (keys are `str`) so a composite `"a2ui:KPICard"` route can win,
and adds a keyword-only `encoder` so per-tenant routers (TASK-4760) share one
SentenceTransformer instead of loading the model N times.

**Backwards compatibility is the hard constraint**: `RouteScore(None, -1.0, -1.0, False)`
is constructed positionally at `embedding_router.py:168` and pinned by
`tests/routing/test_embedding_router.py:83`, so the two new fields MUST be trailing
and defaulted. `add_route(OutputMode, ...)` and `route_scores()` keep their public
behaviour (G5 / AC "no breaking change").

---

## Scope

- Add `label` and `component` as trailing defaulted fields on `RouteScore`.
- Add a keyword-only `encoder` parameter to `EmbeddingIntentRouter.__init__` (`None` keeps today's lazy load).
- Widen `add_route` to accept `OutputMode | str` (an `OutputMode` is stored as its `.value`).
- Add `route_label_scores()`; reimplement `route_scores()` as a compat view over it.
- Fill `label`/`component` in `route()` from the winning label via `parse_route_label`.
- Extend `tests/routing/test_embedding_router.py` for labels, the compat view, and the shared encoder.

**NOT in scope**: Validating that a component is inline (that is CONFIGURE's job, TASK-4760), reading `routes.yaml` (TASK-4759), and any change to `intent_router.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/routing/embedding_router.py` | MODIFY | Label-keyed bank, shared encoder, RouteScore fields |
| `packages/ai-parrot/tests/routing/test_embedding_router.py` | MODIFY | Label + encoder coverage |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED code references from the actual codebase. Use these exact
> imports, class names, and method signatures. DO NOT invent, guess, or assume any
> import, attribute, or method not listed here. Verified against `e21bc561e+ (dev @ 2026-10-27, re-verified at /sdd-task time)`.

### Verified Imports
```python
from parrot.models.outputs import OutputMode  # verified: parrot/models/outputs.py:23
from parrot.registry.routing.route_labels import OutputShape, parse_route_label  # verified: TASK-4757 (route_labels.py)
```

### Existing Signatures to Use
```python
# parrot/registry/routing/embedding_router.py:37 (BEFORE this task)
class RouteScore(NamedTuple):
    mode: Optional[OutputMode]
    score: float
    runner_up: float
    ambiguous: bool

# parrot/registry/routing/embedding_router.py:57
class EmbeddingIntentRouter:
    def __init__(self, model: str = "intfloat/multilingual-e5-small",
                 threshold: float = 0.85, margin: float = 0.05) -> None:  # :65-69
    def add_route(self, mode: OutputMode, utterances: list[str]) -> None:  # :108
    def route_scores(self, query: str) -> list[tuple[OutputMode, float]]:  # :125
    def route(self, query: str) -> RouteScore:  # :152 — builds RouteScore(None, -1.0, -1.0, False) at :168

# parrot/registry/routing/route_labels.py (TASK-4757)
def parse_route_label(label: str) -> OutputShape: ...  # raises ValueError on a bad label
```

### Does NOT Exist
- ~~`RouteScore.label` / `RouteScore.component`~~ — this task ADDS them; they do not exist yet.
- ~~`EmbeddingIntentRouter.route_label_scores()`~~ — this task adds it.
- ~~an `encoder=` kwarg on `__init__`~~ — not present today (`:65-69`); this task adds it keyword-only.
- ~~`EmbeddingIntentRouter.add_label_route()`~~ — do NOT add a second method; `add_route` is widened in place.
- ~~`route_labels.is_inline_component` used here~~ — the engine never consults the catalog; validation happens at CONFIGURE (TASK-4760).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/registry/routing/embedding_router.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/routing/test_embedding_router.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/registry/routing/embedding_router.py#RouteScore",
    "sym:packages/ai-parrot/src/parrot/registry/routing/embedding_router.py#EmbeddingIntentRouter",
    "sym:packages/ai-parrot/src/parrot/registry/routing/embedding_router.py#EmbeddingIntentRouter.add_route",
    "sym:packages/ai-parrot/src/parrot/registry/routing/embedding_router.py#EmbeddingIntentRouter.route_scores",
    "sym:packages/ai-parrot/src/parrot/registry/routing/embedding_router.py#EmbeddingIntentRouter.route",
    "sym:packages/ai-parrot/src/parrot/registry/routing/route_labels.py#parse_route_label"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Trailing + defaulted only.** `label` and `component` go AFTER `ambiguous` with defaults, so the positional `RouteScore(None, -1.0, -1.0, False)` at `:168` and its test at `test_embedding_router.py:83` keep working unchanged. This is an explicit acceptance criterion of the spec (G5).
- `add_route(OutputMode.X, ...)` must still work: normalize an `OutputMode` to its `.value` before using it as the dict key, so the internal bank is uniformly `dict[str, ndarray]`.
- `route_scores()` stays a *compat view*: it parses each label back to an `OutputMode`, so composite labels all map to `OutputMode.A2UI` and the returned list **may contain repeated modes**. Do not dedupe — callers that need precision use `route_label_scores()`.
- A label that fails `parse_route_label` must not crash `route_scores()`; skip it (it could only get there via a direct `add_route` call, since CONFIGURE validates first).
- `encoder` is **keyword-only** (`*, encoder: Any | None = None`) so the three positional args keep their meaning.
- Empty utterance lists are still ignored (today's behaviour, unchanged).

### References in Codebase
- `parrot/registry/routing/embedding_router.py:37-56` — `RouteScore` and its docstring.
- `parrot/registry/routing/embedding_router.py:152-173` — `route()`, including the `RouteScore(None, -1.0, -1.0, False)` abstain path at `:168`.
- `packages/ai-parrot/tests/routing/test_embedding_router.py:83` — the positional construction this task must not break.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Business-logic branches, edge
> cases and test bodies are `FILL IN` stubs by design. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the two trailing defaulted fields to `RouteScore` — *why*: positional construction at `:168` and its pinning test must keep working.
2. Add keyword-only `encoder` to `__init__`, using it instead of lazy-loading when provided — *why*: TASK-4760 builds one router per tenant and must not load the model N times.
3. Normalize `add_route`'s key to `str` — *why*: the bank becomes label-keyed so composites are storable.
4. Add `route_label_scores()` and rewrite `route_scores()` as a compat view over it — *why*: existing callers keep an `OutputMode`-typed API while the mixin gets label precision.
5. Fill `label`/`component` in `route()` from the winner — *why*: the mixin needs the component without re-parsing.
6. Extend the existing test module — *why*: AC-1..AC-5.

### `packages/ai-parrot/src/parrot/registry/routing/embedding_router.py` (MODIFY — RouteScore)
```python
# occurrences: 1 (verified: grep -c 'class RouteScore(NamedTuple):' packages/ai-parrot/src/parrot/registry/routing/embedding_router.py)
# AFTER — extend the existing NamedTuple at `class RouteScore(NamedTuple):` (verified: embedding_router.py:37)
# Keep mode/score/runner_up/ambiguous in place and APPEND these two, both defaulted:
    label: Optional[str] = None      # NEW (FEAT-755) — raw winning label, e.g. "a2ui:KPICard"
    component: Optional[str] = None  # NEW (FEAT-755) — component for "a2ui:<Name>" labels, else None
```
**Why**: trailing defaults keep `RouteScore(None, -1.0, -1.0, False)` (`:168`, pinned by `test_embedding_router.py:83`) valid. Do NOT reorder the existing four fields.

### `packages/ai-parrot/src/parrot/registry/routing/embedding_router.py` (MODIFY — shared encoder)
```python
# occurrences: 1 (verified: grep -c '    def add_route(self, mode: OutputMode, utterances: list\[str\]) -> None:' packages/ai-parrot/src/parrot/registry/routing/embedding_router.py)
# BEFORE this method, in __init__ (verified: embedding_router.py:65-69) — add a keyword-only parameter:
#     def __init__(self, model: str = "intfloat/multilingual-e5-small", threshold: float = 0.85,
#                  margin: float = 0.05, *, encoder: Any | None = None) -> None:
# FILL IN: store `encoder` and have the lazy-load path return it when not None
#          — bounded by AC-3 (no second model load when an encoder is supplied)

# REPLACE the signature at `def add_route(self, mode: OutputMode, ...)` (verified: embedding_router.py:108):
    def add_route(self, label: OutputMode | str, utterances: list[str]) -> None:
        """Encode ``utterances`` under ``label``.

        An :class:`OutputMode` is stored as its ``.value``, so the internal bank is
        uniformly keyed by ``str`` and composite ``"a2ui:<Name>"`` labels are storable.
        Empty utterance lists are ignored (unchanged).
        """
        # FILL IN: key = label.value if isinstance(label, OutputMode) else str(label)
        #          then the existing encode-and-store body — bounded by AC-2
```
**Why**: the engine stays dumb — it stores whatever label it is given and never asks the catalog whether the component is real. That check belongs to CONFIGURE (TASK-4760), which can then warn precisely.

### `packages/ai-parrot/src/parrot/registry/routing/embedding_router.py` (MODIFY — label scores + compat view)
```python
# occurrences: 1 (verified: grep -c '    def route_scores(self, query: str) -> list\[tuple\[OutputMode, float\]\]:' packages/ai-parrot/src/parrot/registry/routing/embedding_router.py)
# AFTER — insert `route_label_scores` directly ABOVE `def route_scores(...)` (verified: embedding_router.py:125)
    def route_label_scores(self, query: str) -> list[tuple[str, float]]:
        """Every label's max-cosine score, sorted descending; ``[]`` when no routes.

        CPU-bound — callers run it under ``asyncio.to_thread``.
        """
        # FILL IN: today's route_scores body, but yielding the raw str keys — bounded by AC-4

# REPLACE the body of `route_scores` with a compat view:
    def route_scores(self, query: str) -> list[tuple[OutputMode, float]]:
        """Compat view of :meth:`route_label_scores`.

        Labels are parsed back to an :class:`OutputMode`; every composite label maps to
        :attr:`OutputMode.A2UI`, so the result MAY contain repeated modes. Unparseable
        labels are skipped.
        """
        # FILL IN: parse each label with parse_route_label, skipping ValueError
        #          — bounded by AC-4 (no dedupe, order preserved)
```
**Why**: `route_scores()` is public and used by the mixin's tie-breaker today; keeping it as a view means no caller breaks while `route_label_scores()` gives the mixin the precision it needs.

### `packages/ai-parrot/src/parrot/registry/routing/embedding_router.py` (MODIFY — route())
```python
# occurrences: 1 (verified: grep -c '    def route(self, query: str) -> RouteScore:' packages/ai-parrot/src/parrot/registry/routing/embedding_router.py)
# AFTER — inside `def route(...)` (verified: embedding_router.py:152), when a winner is found:
# FILL IN: derive shape = parse_route_label(winning_label); set mode=shape.mode,
#          label=winning_label, component=shape.component on the returned RouteScore.
#          The abstain path at :168 stays EXACTLY `RouteScore(None, -1.0, -1.0, False)`
#          — bounded by AC-1/AC-5
```
**Why**: the mixin reads `component` straight off the score; re-parsing in the mixin would duplicate the grammar. The abstain tuple is left untouched on purpose — it is pinned by an existing test.

### `packages/ai-parrot/tests/routing/test_embedding_router.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^class TestEmbeddingIntentRouter:' packages/ai-parrot/tests/routing/test_embedding_router.py)
# AFTER — append a NEW sibling test class below the existing `class TestEmbeddingIntentRouter:`
# (verified: packages/ai-parrot/tests/routing/test_embedding_router.py:39). Do not edit that
# class's existing assertions — `:83` pins the positional RouteScore construction.
# FILL IN: write the new class `TestLabelRoutes` with these cases:
#   - add_route accepts OutputMode and str, and both land in the same bank
#   - a composite win sets mode=OutputMode.A2UI, label="a2ui:KPICard", component="KPICard"
#   - route_scores() still returns OutputMode tuples and may repeat A2UI
#   - RouteScore(None, -1.0, -1.0, False) still constructs positionally
#   - passing encoder= reuses the instance (assert the loader is not called)
# — bounded by AC-1..AC-5
```
**Why**: this file already pins the positional construction at `:83`; the new class extends coverage without touching the existing assertions.

### FILL IN checklist
- [ ] `embedding_router.py::__init__` — store and honour the keyword-only `encoder`; bounded by AC-3
- [ ] `embedding_router.py::add_route` — normalize `OutputMode` to `.value`; bounded by AC-2
- [ ] `embedding_router.py::route_label_scores` — label-keyed scoring body; bounded by AC-4
- [ ] `embedding_router.py::route_scores` — compat view, skip unparseable, no dedupe; bounded by AC-4
- [ ] `embedding_router.py::route` — fill `label`/`component`, leave the abstain tuple alone; bounded by AC-1/AC-5
- [ ] `test_embedding_router.py` — anchor the new test class and write the five cases; bounded by AC-1..AC-5

---

## Acceptance Criteria

- [ ] **AC-1**: a composite route wins → `RouteScore.mode is OutputMode.A2UI`, `.label == "a2ui:KPICard"`, `.component == "KPICard"`.
- [ ] **AC-2**: `add_route(OutputMode.STRUCTURED_CHART, [...])` and `add_route("a2ui:KPICard", [...])` both populate the bank; an `OutputMode` is keyed by its `.value`.
- [ ] **AC-3**: passing `encoder=<instance>` reuses it — no second model load (assert the lazy loader is not invoked).
- [ ] **AC-4**: `route_label_scores()` returns `(str, float)` sorted desc; `route_scores()` returns `(OutputMode, float)`, maps every composite to `A2UI`, preserves order, and does not dedupe.
- [ ] **AC-5**: no breaking change — `RouteScore(None, -1.0, -1.0, False)` still constructs positionally and `tests/routing/test_embedding_router.py` passes unmodified in its existing assertions.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/routing/test_embedding_router.py -q`
- `pytest packages/ai-parrot/tests/routing/test_route_labels.py -q`

---

## Test Specification

Extend `packages/ai-parrot/tests/routing/test_embedding_router.py` — do NOT create a new module
(the existing one already holds the router's fixtures and the positional-construction
guard at `:83`).

Required coverage: the five acceptance criteria above. Stub the encoder with a fake
whose `encode()` returns deterministic vectors so the tests stay CPU-cheap and do not
download a model — follow whatever fake the existing module already uses.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug inline-a2ui-component-routing --feature-id FEAT-755`)
2. **Read the spec** at `sdd/specs/inline-a2ui-component-routing.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/inline-a2ui-component-routing.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/inline-a2ui-component-routing.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <ID> inline-a2ui-component-routing verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
