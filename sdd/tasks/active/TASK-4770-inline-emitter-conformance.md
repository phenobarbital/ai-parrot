# TASK-4770: Conformance: sweep inline emitter envelopes

**Feature**: FEAT-755 — Inline A2UI Component Routing
**Spec**: `sdd/specs/inline-a2ui-component-routing.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4765
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (conformance half) and acceptance criterion G7.

Every A2UI emission point in the codebase is swept by
`tests/outputs/a2ui/conformance/test_all_emitters.py`, which asserts an envelope is
valid against both the catalog (with the producer's origin semantics) and, once
lowered, the Basic wire schema. The inline emitter is a new emission point and must
join that suite — otherwise it is the only producer in the tree whose output is not
checked against the wire contract.

Small task, but it is the one that makes G7 true for all four components.

---

## Scope

- Add a test that emits each of KPICard / InfoCard / Timeline / Graph through `emit_inline_component` and asserts conformance via the module's existing `_assert_conformant` helper.
- Assert the surface-level `parrot_presentation` marker survives validation (`Extensions` accepts it — no `a2ui_` prefix).

**NOT in scope**: The emitter itself (TASK-4765), the docs (TASK-4771), and adding new catalog components.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py` | MODIFY | Inline emitter conformance sweep |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED code references from the actual codebase. Use these exact
> imports, class names, and method signatures. DO NOT invent, guess, or assume any
> import, attribute, or method not listed here. Verified against `e21bc561e+ (dev @ 2026-10-27, re-verified at /sdd-task time)`.

### Verified Imports
```python
from parrot.outputs.a2ui.inline.emitter import PRESENTATION_EXTENSION, emit_inline_component  # TASK-4765
```

### Existing Signatures to Use
```python
# tests/outputs/a2ui/conformance/test_all_emitters.py:116 — the helper to reuse VERBATIM
def _assert_conformant(envelope: CreateSurface, *, origin: ProducerOrigin = ProducerOrigin.TOOL) -> None:
    """Validates against the catalog AND, lowered, against the Basic wire schema."""

# tests/outputs/a2ui/conformance/test_all_emitters.py:96
def _lower_to_basic_components(envelope: CreateSurface) -> list[Component]: ...

# Existing call sites to copy the style from (all inside the module's test classes):
#   :141 _assert_conformant(envelope)        (test_build_surface_generic)
#   :149 _assert_conformant(envelope)        (test_build_kpicard)
#   :180 _assert_conformant(envelope)        (test_build_graph)

# parrot/outputs/a2ui/inline/emitter.py (TASK-4765)
def emit_inline_component(response, component, *, frame=None, surface_id=None) -> InlineEmitOutcome: ...
```

### Does NOT Exist
- ~~`_assert_conformant` taking an envelope dict~~ — it takes a `CreateSurface`. `response.a2ui_envelope` is the **serialized dict**, so pass `response.a2ui_envelope["createSurface"]` or rebuild the model — check how the module's other tests obtain their `CreateSurface` and follow that.
- ~~a `ProducerOrigin.LLM` default on `_assert_conformant`~~ — the default is `TOOL`; the inline emitter is LLM-origin, so pass `origin=ProducerOrigin.LLM` explicitly or the gates checked will be the wrong ones.
- ~~an existing inline fixture in this module~~ — none; this task adds the first.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/inline/emitter.py#emit_inline_component",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/inline/emitter.py#PRESENTATION_EXTENSION"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Reuse `_assert_conformant` **verbatim** — do not write a parallel assertion helper. The whole point of the suite is that every producer passes the *same* check.
- Pass `origin=ProducerOrigin.LLM`: the inline emitter is an LLM producer, so the LLM-origin gates (`action` rejected, `parrot_data_sources` rejected) are the ones that must hold.
- Cover **all four** v1 components, not just KPICard — Graph is the one most likely to break, since it is the only viz-core component and the only one with a `SOURCE_MODEL`.
- The configs used must be *feasible* (TASK-4764's rules) or the emitter will degrade and produce no envelope — a degraded outcome in this test is a failure, so assert `outcome.status == "emitted"` first and let that be the error message.
- Do not modify `_assert_conformant` or any existing test in the module.

### References in Codebase
- `tests/outputs/a2ui/conformance/test_all_emitters.py:42` — the module docstring explaining what conformance means here.
- `tests/outputs/a2ui/conformance/test_all_emitters.py:116-180` — the helper and the existing per-builder tests.
- Spec §5, criterion G7 — the acceptance wording this test satisfies.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Business-logic branches, edge
> cases and test bodies are `FILL IN` stubs by design. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Read `_assert_conformant` and one existing caller — *why*: the envelope type it expects (`CreateSurface`, not a dict) decides how you unwrap the emitter's output.
2. Add one test looping the four components — *why*: a single parametrized test keeps the sweep honest as FEAT-753/754 add components.
3. Assert `outcome.status == "emitted"` before conformance — *why*: a degraded outcome yields no envelope, and the resulting `None` error would be confusing.
4. Assert the marker survives validation — *why*: AC-3; `Extensions` has `additionalProperties: false` on a UAX #31 pattern, so a bad key would be rejected here.

### `packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _assert_conformant(' packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py)
# AFTER — append a new test (or a small test class) below the existing classes.
# `def _assert_conformant(` is at packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py:116; the existing callers are at :141/:149/:180.

def test_inline_emitter_envelopes_conform() -> None:
    """FEAT-755 G7: every inline-emitted envelope is catalog- and wire-conformant.

    The inline emitter is an LLM-origin producer, so it is validated with LLM-origin
    semantics — the same gates that reject an `action` or `parrot_data_sources` from
    a model-authored surface.
    """
    # FILL IN:
    #   for component, config in [
    #       ("KPICard",  {"label": "Worked hours", "value": 1234.5, "unit": "h", "trend": "up"}),
    #       ("InfoCard", {"title": "...", "body": "..."}),
    #       ("Timeline", {"events": [{"title": "...", "timestamp": "2026-10-27"}]}),
    #       ("Graph",    {...nodes/edges/kind/direction/accessibleDescription...}),
    #   ]:
    #       response = SimpleNamespace(structured_output=config, output=None, content=None,
    #                                  response="", data=None, metadata={},
    #                                  a2ui_envelope=None, output_mode=None)
    #       outcome = emit_inline_component(response, component)
    #       assert outcome.status == "emitted", f"{component}: {outcome.reason}"
    #       _assert_conformant(<the CreateSurface from response.a2ui_envelope>,
    #                          origin=ProducerOrigin.LLM)
    #       assert PRESENTATION_EXTENSION in <the surface's metadata.extensions>
    #
    #   Each config MUST satisfy TASK-4764's feasibility rules, or the emitter degrades
    #   and there is no envelope to check.
    #   Check how the module's other tests hand a CreateSurface to _assert_conformant and
    #   unwrap response.a2ui_envelope (a serialized dict) the same way.
    # — bounded by AC-1/AC-2/AC-3
```
**Why**: one parametrized sweep rather than four separate tests, so a component added by FEAT-753/754 joins by appending a tuple. Asserting `outcome.status` first turns a feasibility mistake in the fixture into a readable failure instead of an `AttributeError` on `None`.

### FILL IN checklist
- [ ] `test_all_emitters.py::test_inline_emitter_envelopes_conform` — the four configs, the unwrap, and the three assertions; bounded by AC-1..AC-3

---

## Acceptance Criteria

- [ ] **AC-1**: all four v1 components (KPICard, InfoCard, Timeline, Graph) emit successfully (`outcome.status == "emitted"`) and pass `_assert_conformant(..., origin=ProducerOrigin.LLM)`.
- [ ] **AC-2**: the helper is reused verbatim — no parallel assertion logic is introduced, and no existing test in the module is modified.
- [ ] **AC-3**: `parrot_presentation` is present on the validated surface's `metadata.extensions`, proving `Extensions` accepts the key (no `a2ui_` prefix violation).
- [ ] `ruff check` clean on the file.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py -q`

---

## Test Specification

Extend `packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py` only. Do not create a new conformance module — the suite's value is
that every producer goes through the same `_assert_conformant`.

If a config you write degrades instead of emitting, fix the **config** (it violates a
feasibility rule), not the emitter.

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
