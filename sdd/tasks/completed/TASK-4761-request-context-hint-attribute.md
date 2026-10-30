# TASK-4761: RequestContext.a2ui_component + base method docstrings

**Feature**: FEAT-755 — Inline A2UI Component Routing
**Spec**: `sdd/specs/inline-a2ui-component-routing.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. Small but load-bearing: makes the component hint a
first-class, documented context attribute instead of something modules set by
duck-typing, and documents the FEAT-756 precedence slot on the two `AbstractBot`
base methods.

Independent of the rest of the router thread — it touches two files nothing else in
this feature touches, so it runs in the first wave. `route_labels.py` (TASK-4757)
deliberately duck-types the ctx precisely so these two tasks need no ordering
between them.

---

## Scope

- Add `a2ui_component: Optional[str] = None` to `RequestContext` with a docstring/comment naming FEAT-755.
- Extend `AbstractBot._resolve_output_mode`'s docstring: a composite route resolves to `A2UI` + `ctx.a2ui_component`, and cooperative overrides may fill the FEAT-756 slot.
- Extend `AbstractBot._apply_default_output_mode`'s docstring with the new precedence chain.
- Add a regression test asserting the attribute exists and defaults to `None`.

**NOT in scope**: Any behaviour change in `abstract.py` — **docstrings only**, bodies untouched. The router (TASK-4760) and the FEAT-756 implementation itself are elsewhere.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/utils/helpers.py` | MODIFY | New RequestContext attribute |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Docstrings only |
| `packages/ai-parrot/tests/bots/test_resolve_output_mode_noop.py` | MODIFY | Attribute regression test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED code references from the actual codebase. Use these exact
> imports, class names, and method signatures. DO NOT invent, guess, or assume any
> import, attribute, or method not listed here. Verified against `e21bc561e+ (dev @ 2026-10-27, re-verified at /sdd-task time)`.

### Verified Imports
```python
from typing import Optional  # already imported in helpers.py — confirm before adding
# No new cross-module imports. This task deliberately adds NO import of route_labels:
# the spec records the dependency as "docstring cross-reference only; no import".
```

### Existing Signatures to Use
```python
# parrot/utils/helpers.py:7
class RequestContext:
    output_mode: Any = None      # verified: helpers.py:41
    intent_score: Any = None     # verified: helpers.py:42

# parrot/bots/abstract.py:4168
async def _resolve_output_mode(self, query: str, ctx: "Optional[RequestContext]") -> "Optional[OutputMode]":
    """Cooperative no-op terminal of the MRO chain."""

# parrot/bots/abstract.py:4191
def _apply_default_output_mode(self, output_mode: OutputMode) -> OutputMode:
    """explicit > router > agent default."""
```

### Does NOT Exist
- ~~`RequestContext.a2ui_component`~~ — this task ADDS it; only `output_mode` and `intent_score` exist today (`helpers.py:41-42`).
- ~~`RequestContext` as a Pydantic model~~ — check the actual class style at `helpers.py:7` before adding the attribute and match it (plain class / dataclass), do not convert it.
- ~~a FEAT-756 metric registry~~ — does not exist; this task only documents the precedence slot where it will plug in.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/utils/helpers.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_resolve_output_mode_noop.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/utils/helpers.py#RequestContext",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._resolve_output_mode",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._apply_default_output_mode"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **`abstract.py` is docstrings only.** Do not change a single line of executable code in either method — the spec's Edit Sites table marks both rows `MODIFY (docstring)`. A behaviour change here would silently alter every bot.
- Match `RequestContext`'s existing declaration style exactly (read `helpers.py:7-45` first); do not restructure the class.
- No import of `parrot.registry.routing.route_labels` — referencing it in prose is the whole point; importing it would create a dependency the spec explicitly excluded.
- Default is `None`, and the attribute is `Optional[str]`.

### References in Codebase
- `parrot/utils/helpers.py:7,41-42` — the class and the two sibling attributes.
- `parrot/bots/abstract.py:4168-4210` — both methods and their current docstrings.
- Spec §2 "Hook contract for FEAT-756" — the precedence wording to mirror.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Business-logic branches, edge
> cases and test bodies are `FILL IN` stubs by design. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Read `helpers.py:7-45` and add the attribute in the surrounding style — *why*: the class may be a plain class or dataclass; matching it avoids changing construction semantics.
2. Extend both `abstract.py` docstrings — *why*: these are the methods a FEAT-756 author will read first, and the precedence chain is otherwise undocumented.
3. Add the attribute regression test — *why*: AC-1; cheap insurance that a later refactor does not drop the field.

### `packages/ai-parrot/src/parrot/utils/helpers.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        self.intent_score = None' packages/ai-parrot/src/parrot/utils/helpers.py)
# AFTER — insert below `self.intent_score = None` (verified: helpers.py:42)
        #: FEAT-755 — A2UI component hint ("KPICard", "Timeline", ...) set by a composite
        #: route win (route_labels.set_output_shape) or by an explicit ask(a2ui_component=)
        #: kwarg. None means "no component hint"; the emitter is skipped.
        self.a2ui_component: Optional[str] = None
# FILL IN: if RequestContext declares its attributes as class-level annotations rather
#          than in __init__, add it there instead, matching the file's style
#          — bounded by AC-1/AC-2
```
**Why**: `route_labels.set_output_shape` writes this attribute and `get_component_hint` reads it; declaring it here makes the channel discoverable and gives it a default so `getattr` is never the only guard.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — docstring only)
```python
# occurrences: 1 (verified: grep -c '    async def _resolve_output_mode(' packages/ai-parrot/src/parrot/bots/abstract.py)
# AFTER — extend the DOCSTRING of `async def _resolve_output_mode(` (verified: abstract.py:4168).
# Do NOT touch the body.
#   Add: "A composite route (``a2ui:<Component>``) resolves to ``OutputMode.A2UI`` with the
#   component written to ``ctx.a2ui_component`` by
#   ``parrot.registry.routing.route_labels.set_output_shape`` (FEAT-755). An override that
#   chains ``super()`` first may fill the precedence slot between the router and the agent
#   default — this is the FEAT-756 metric-default-shape hook."
```
**Why**: this is the cooperative terminal of the MRO chain, so it is the canonical place to document what a mixin above it is allowed to return.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — docstring only)
```python
# occurrences: 1 (verified: grep -c '    def _apply_default_output_mode(self, output_mode: OutputMode) -> OutputMode:' packages/ai-parrot/src/parrot/bots/abstract.py)
# AFTER — extend the DOCSTRING of `_apply_default_output_mode` (verified: abstract.py:4191).
# Do NOT touch the body.
#   Precedence becomes: explicit caller mode > router (mode + hint)
#                       > metric default shape (FEAT-756 slot) > agent default.
```
**Why**: the precedence chain is the contract three in-flight features depend on; writing it down here stops each of them re-deriving it.

### `packages/ai-parrot/tests/bots/test_resolve_output_mode_noop.py` (MODIFY)
```python
# occurrences: 9 (verified: grep -c 'def test_' packages/ai-parrot/tests/bots/test_resolve_output_mode_noop.py)
# AMBIGUOUS ANCHOR — do not attach to `def test_`. This block APPENDS at end of file.
# FILL IN: this file is small — read it, then append ONE test asserting
#          RequestContext().a2ui_component is None and that the attribute exists.
#          Match the module's existing import and naming style.
#          — bounded by AC-1
```
**Why**: this module already guards the no-op terminal's contract, so the attribute's existence belongs beside it rather than in a new file.

### FILL IN checklist
- [ ] `helpers.py::RequestContext` — place the attribute in the class's actual declaration style; bounded by AC-1/AC-2
- [ ] `test_resolve_output_mode_noop.py` — one attribute-existence test; bounded by AC-1

---

## Acceptance Criteria

- [ ] **AC-1**: `RequestContext().a2ui_component is None` and the attribute is declared `Optional[str]`.
- [ ] **AC-2**: `RequestContext`'s declaration style is unchanged (still the same class kind; no new construction requirements).
- [ ] **AC-3**: `abstract.py` has **no executable change** — `git diff packages/ai-parrot/src/parrot/bots/abstract.py` shows docstring lines only.
- [ ] **AC-4**: both docstrings name `ctx.a2ui_component`, `set_output_shape`, and the FEAT-756 precedence slot.
- [ ] `ruff check` clean on all three files.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/bots/test_resolve_output_mode_noop.py -q`
- `pytest packages/ai-parrot/tests/bots/test_intent_router_output_mode.py -q`

---

## Test Specification

Append one test to `packages/ai-parrot/tests/bots/test_resolve_output_mode_noop.py` — do not create a
new module for a single attribute assertion.

Verify AC-3 by inspection before committing:
`git diff packages/ai-parrot/src/parrot/bots/abstract.py` must show only docstring lines.

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

**Completed by**: sdd-worker orchestrator; implemented by codex/gpt-5.6-sol (attempt 1, 693s)
**Date**: 2026-10-27
**Notes**: Added RequestContext.a2ui_component (default None), docstring-only updates in abstract.py, regression test. Fidelity gate clean. Merge-tier validation (chunk 0) green: exit 0. Closed via close_task.sh because finalize_task needs a durable review EvidenceRef that coder_record_review does not return; review recorded as coder-review feedback ids.

**Deviations from spec**: none
