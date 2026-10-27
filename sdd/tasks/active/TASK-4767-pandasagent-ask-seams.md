# TASK-4767: PandasAgent ask(): hint kwarg, prompt addon, structured forcing, emitter call

**Feature**: FEAT-755 — Inline A2UI Component Routing
**Spec**: `sdd/specs/inline-a2ui-component-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4757, TASK-4762, TASK-4765, TASK-4766
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (REQUEST half) — where every thread of this feature finally
meets. Four edit sites in `PandasAgent.ask()`:

1. **`a2ui_component` kwarg** (`:1278`, through `**kwargs`): an explicit hint sets the
   shape and **skips the router entirely** (G2 — an explicit caller choice is never
   overridden).
2. **Prompt seam** (`:1418`): append `build_component_prompt(hint)` to the system
   prompt, *before* the main turn (G1 — one LLM call, no post-hoc authoring).
3. **Structured forcing** (`:1513`): force `component_model(hint)` instead of
   `PandasAgentResponse`. The FEAT-215 comment immediately above this line is both the
   precedent and the warning: forcing `PandasAgentResponse` there made the model "emit
   a prose-only {explanation} and omit the chart config".
4. **Emitter call** (before `:1960`): `emit_inline_component(...)` when the mode is
   A2UI with a hint and no tool already produced a surface; a degraded outcome falls
   through to the existing `DEFAULT` degradation.

Depends on `data.py` being free (TASK-4766 holds it first).

---

## Scope

- Accept and honour an explicit `a2ui_component` kwarg, skipping the router.
- Read the resolved hint after `_resolve_output_mode` via `get_component_hint(ctx)`.
- Append the component prompt addon at the system-prompt seam.
- Force `component_model(hint)` as `structured_output` for A2UI+hint.
- Call `emit_inline_component` before the existing A2UI fallback and log the outcome.
- Add tests for the kwarg, the forcing, and the emitter wiring.

**NOT in scope**: The default bank and configure (TASK-4766), the emitter internals (TASK-4765), and the UI (TASK-4768/4769).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | ask() hint kwarg, prompt addon, structured forcing, emitter call |
| `packages/ai-parrot/tests/bots/test_intent_router_component_routes.py` | MODIFY | ask() wiring tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED code references from the actual codebase. Use these exact
> imports, class names, and method signatures. DO NOT invent, guess, or assume any
> import, attribute, or method not listed here. Verified against `e21bc561e+ (dev @ 2026-10-27, re-verified at /sdd-task time)`.

### Verified Imports
```python
from parrot.registry.routing.route_labels import OutputShape, get_component_hint, set_output_shape  # TASK-4757
from parrot.outputs.a2ui.catalog._model import component_model      # TASK-4762
from parrot.outputs.a2ui.inline.emitter import emit_inline_component  # TASK-4765
from parrot.outputs.a2ui.inline.prompt import build_component_prompt  # TASK-4763
```

### Existing Signatures to Use
```python
# parrot/bots/data.py:1350
                _resolved_mode = await self._resolve_output_mode(question, ctx)
# parrot/bots/data.py:1358
                output_mode = self._apply_default_output_mode(output_mode)

# parrot/bots/data.py:1417-1419 — the prompt seam (VERIFIED FRESH)
                if output_mode != OutputMode.TABLE:
                    if system_prompt_addon := self.formatter.get_system_prompt(output_mode):
                        system_prompt += system_prompt_addon

# parrot/bots/data.py:1504-1515 — the structured-forcing seam (VERIFIED FRESH).
# The FEAT-215 comment at :1505-1511 is the precedent for this whole task.
                elif return_structured:
                    _forced_output_type = (
                        StructuredChartConfig if output_mode == OutputMode.STRUCTURED_CHART else PandasAgentResponse
                    )
                    llm_kwargs["structured_output"] = StructuredOutputConfig(output_type=_forced_output_type)

# parrot/bots/data.py:1957-1960 — the existing A2UI degradation the emitter slots in front of
                # There is no A2UI renderer to dispatch to — the mode is a request-side
                # signal handled by the render tools — so degrade to DEFAULT
                # rather than let the formatter raise "No renderer registered".
                if output_mode == OutputMode.A2UI:
```

### Does NOT Exist
- ~~an `a2ui_component` parameter in `ask()`'s explicit signature~~ — it arrives through `**kwargs` and must be `pop`ped, like the other request-side kwargs at `:1265-1278`.
- ~~a registered renderer for `OutputMode.A2UI`~~ — there is none; `register_renderer` is NOT used by this feature. The prompt addon is appended at the `ask()` seam and the emitter is called directly.
- ~~`self.formatter.get_system_prompt(OutputMode.A2UI)`~~ — returns nothing useful; the component addon comes from `build_component_prompt(hint)`, appended separately.
- ~~`response.a2ui_envelope` already set by a tool~~ — possible, and the reason the emitter call is guarded on `response.a2ui_envelope is None`: a tool-produced surface always wins.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/data.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_intent_router_component_routes.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/data.py#PandasAgent.ask",
    "sym:packages/ai-parrot/src/parrot/registry/routing/route_labels.py#get_component_hint",
    "sym:packages/ai-parrot/src/parrot/registry/routing/route_labels.py#set_output_shape",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/_model.py#component_model",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/inline/emitter.py#emit_inline_component",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/inline/prompt.py#build_component_prompt"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **G1 — one LLM call.** The prompt addon goes in *before* the main turn. Never author the component in a second call.
- **G2 — explicit wins.** An explicit `a2ui_component` kwarg skips `_resolve_output_mode` entirely; an explicit `output_mode` is never overridden by the router (today's precedence at `abstract.py:4191`).
- **G3 — never raise.** The emitter already guarantees this; do not wrap it in a bare `except` that would hide a real bug, and do not let a hint of `None` reach it.
- **Structured forcing**: extend the existing ternary at `:1513` into a three-way choice. Do not restructure the surrounding `elif return_structured:` block — the `_client_uses_split_structured_with_tools` fast-path below it (`:1524`) must keep applying to the component model with no new branch.
- **Emitter placement**: after structured post-processing, immediately *before* the A2UI fallback at `:1957-1960`, and guarded on `output_mode == A2UI and component_hint and response.a2ui_envelope is None`. A degraded outcome then flows into the very same `DEFAULT` degradation that exists today — log `outcome.reason`.
- Pass the DataFrame as `frame=` when `response.data` is one, so feasibility can consult it.
- The `:1957-1960` anchor is **ambiguous** (the bare `if output_mode == OutputMode.A2UI:` also appears at `:1880`) — attach using the three comment lines above it as context.

### References in Codebase
- `parrot/bots/data.py:1504-1515` — the FEAT-215 structured-forcing precedent and its explanatory comment.
- `parrot/bots/data.py:1955-1966` — the existing A2UI→DEFAULT degradation.
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_base.py:139-199` — how the structured renderers dual-emit, for comparison.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Business-logic branches, edge
> cases and test bodies are `FILL IN` stubs by design. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Pop `a2ui_component` from kwargs and, when present, `set_output_shape` + skip the router — *why*: G2; an explicit caller choice must never be second-guessed.
2. Read the hint with `get_component_hint(ctx)` after resolution — *why*: the router writes it to ctx because the return type is frozen.
3. Append `build_component_prompt(hint)` at the prompt seam — *why*: G1; the component must be authored in the main turn.
4. Extend the forcing ternary with the A2UI+hint branch — *why*: the FEAT-215 comment records that not advertising the real model makes the LLM emit prose and omit the config.
5. Call the emitter before the existing fallback, guarded and logged — *why*: a degraded outcome must land in the degradation path that already exists.

### `packages/ai-parrot/src/parrot/bots/data.py` (MODIFY — explicit hint kwarg + resolution)
```python
# occurrences: 1 (verified: grep -c '                _resolved_mode = await self._resolve_output_mode(question, ctx)' packages/ai-parrot/src/parrot/bots/data.py)
# AROUND — the resolution call (verified: bots/data.py:1350)
# FILL IN:
#   a) early in ask(), near the other kwargs (:1265-1278):
#        a2ui_component = kwargs.pop("a2ui_component", None)
#   b) when a2ui_component is set: set_output_shape(ctx, OutputShape(OutputMode.A2UI, a2ui_component))
#      and SKIP the _resolve_output_mode call entirely (G2)
#   c) otherwise resolve as today, then: component_hint = get_component_hint(ctx)
# — bounded by AC-1/AC-2
```
**Why**: the router is skipped rather than overridden so no embedding work happens for an explicit request, and so a caller can force a component the phrase bank has no utterances for.

### `packages/ai-parrot/src/parrot/bots/data.py` (MODIFY — prompt seam)
```python
# occurrences: 1 (verified: grep -c '                    if system_prompt_addon := self.formatter.get_system_prompt(output_mode):' packages/ai-parrot/src/parrot/bots/data.py)
# AFTER — below the `system_prompt += system_prompt_addon` line of this block
# (verified: bots/data.py:1418)
                if output_mode == OutputMode.A2UI and component_hint:
                    system_prompt += build_component_prompt(component_hint)
```
**Why**: appending here puts the component instructions in the *same* turn that computes the data (G1). `formatter.get_system_prompt(A2UI)` has nothing to give — the addon is component-specific and comes from the catalog.

### `packages/ai-parrot/src/parrot/bots/data.py` (MODIFY — structured forcing)
```python
# occurrences: 1 (verified: grep -c '                        StructuredChartConfig if output_mode == OutputMode.STRUCTURED_CHART else PandasAgentResponse' packages/ai-parrot/src/parrot/bots/data.py)
# REPLACE the ternary (verified: bots/data.py:1513) with a three-way choice:
                    if output_mode == OutputMode.A2UI and component_hint:
                        _forced_output_type = component_model(component_hint)
                    elif output_mode == OutputMode.STRUCTURED_CHART:
                        _forced_output_type = StructuredChartConfig
                    else:
                        _forced_output_type = PandasAgentResponse
                    llm_kwargs["structured_output"] = StructuredOutputConfig(output_type=_forced_output_type)
# Leave the surrounding `elif return_structured:` block and the
# _client_uses_split_structured_with_tools fast-path below (:1524) untouched.
```
**Why**: this is the decision the brainstorm settled — the schema reaches the model as a type, not as prompt text. The FEAT-215 comment directly above explains what happens otherwise: the model answers in prose and drops the config.

### `packages/ai-parrot/src/parrot/bots/data.py` (MODIFY — emitter call)
```python
# occurrences: 2 (verified: grep -c '                if output_mode == OutputMode.A2UI:' packages/ai-parrot/src/parrot/bots/data.py) — AMBIGUOUS
# Disambiguate with the three comment lines above it (verified: bots/data.py:1957-1960):
#                 # There is no A2UI renderer to dispatch to — the mode is a request-side
#                 # signal handled by the render tools — so degrade to DEFAULT
#                 # rather than let the formatter raise "No renderer registered".
#                 if output_mode == OutputMode.A2UI:
# BEFORE that `if`, insert:
# FILL IN:
#   if output_mode == OutputMode.A2UI and component_hint and getattr(response, "a2ui_envelope", None) is None:
#       outcome = emit_inline_component(
#           response, component_hint,
#           frame=<response.data when it is a DataFrame, else None>,
#       )
#       if outcome.status == "degraded":
#           self.logger.info("Inline A2UI emit degraded (%s): %s", component_hint, outcome.reason)
#   # a degraded outcome leaves a2ui_envelope None, so the existing block below degrades to DEFAULT
# — bounded by AC-3/AC-4/AC-5
```
**Why**: placing the call immediately before the existing degradation means failure needs no new error handling — it falls into the path that has handled "A2UI with no surface" since FEAT-273. The `a2ui_envelope is None` guard means a tool-produced surface always wins over an LLM-authored one.

### `packages/ai-parrot/tests/bots/test_intent_router_component_routes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class TestConfigureValidation:' packages/ai-parrot/tests/bots/test_intent_router_component_routes.py)
# AFTER — append a new sibling class at end of file:
class TestAskWiring:
    # FILL IN:
    #   - explicit a2ui_component= skips the router (assert _resolve_output_mode not called)
    #   - A2UI+hint forces structured_output.output_type is component_model(hint)
    #   - STRUCTURED_CHART still forces StructuredChartConfig; every other mode still
    #     forces PandasAgentResponse
    #   - source-fidelity: data.py contains build_component_prompt(, component_model(
    #     and emit_inline_component( at the guarded sites
    # — bounded by AC-1..AC-5
```
**Why**: the source-fidelity assertion is the spec's own chosen technique for the `ask()` seams — the method is too large to exercise end-to-end in a unit test without a live client.

### FILL IN checklist
- [ ] `data.py::ask` — pop the kwarg, skip the router, read the hint; bounded by AC-1/AC-2
- [ ] `data.py::ask` — the emitter call with its three-part guard and frame passing; bounded by AC-3/AC-4/AC-5
- [ ] `test_intent_router_component_routes.py::TestAskWiring` — the four cases; bounded by AC-1..AC-5

---

## Acceptance Criteria

- [ ] **AC-1 (G2)**: an explicit `a2ui_component=` kwarg sets the shape and skips `_resolve_output_mode` entirely; an explicit `output_mode` is never overridden.
- [ ] **AC-2 (G1)**: for `output_mode=DEFAULT` the component addon is appended before the main turn and no second LLM call authors the component.
- [ ] **AC-3**: for A2UI+hint, `llm_kwargs["structured_output"].output_type is component_model(hint)`; `STRUCTURED_CHART` still forces `StructuredChartConfig`; all other modes still force `PandasAgentResponse`.
- [ ] **AC-4**: `emit_inline_component` is called only when the mode is A2UI, a hint is present, and `response.a2ui_envelope is None`; the DataFrame is passed as `frame=` when available.
- [ ] **AC-5 (G3)**: a degraded outcome logs its reason and falls through to the existing `DEFAULT` degradation — no exception escapes `ask()` and the user never gets an empty bubble.
- [ ] The `elif return_structured:` block's fast-path (`:1524`) still applies to the component model with no new branch.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/bots/test_intent_router_component_routes.py -q`
- `pytest packages/ai-parrot/tests/bots/test_intent_router_output_mode_integration.py -q`
- `pytest packages/ai-parrot/tests/outputs/formats/test_structured_chart.py -q`

---

## Test Specification

Extend `packages/ai-parrot/tests/bots/test_intent_router_component_routes.py` with `TestAskWiring`.

`ask()` is large and needs a live client to run end to end, so follow the spec's
approach: unit-test the forcing decision directly where it can be isolated, and use
**source-fidelity assertions** (the file contains the three call sites) for the seams
that cannot be. `test_structured_chart.py` must still pass — the forcing ternary is
shared with `STRUCTURED_CHART`.

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
