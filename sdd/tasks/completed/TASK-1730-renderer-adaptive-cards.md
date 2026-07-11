# TASK-1730: Adaptive Cards renderer (display subset)

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1723, TASK-1725, TASK-1728
**Assigned-to**: unassigned

---

## Context

Implements the **adaptive-cards renderer** of **Module 5** (spec §3): transcodes
A2UI envelopes into **Adaptive Card JSON** for Teams-style surfaces. This is the
"AC fallback transcode" lane of the component diagram (spec §2): it consumes
**LOWERED Basic Catalog trees only** — mandatory lowering (G4/D8) guarantees every
Parrot component has one, so the AC renderer needs no per-component knowledge of
the custom catalog.

v1 is a **display subset**: display elements only (TextBlock/Container/ColumnSet/
FactSet/Image-class equivalents), **no `Action.*` elements** — action dispatch is
FEAT-B territory, and static-surface actions degrade via deep links (G6), not AC
actions. Satellite task; registered into the core registry from TASK-1723.

---

## Scope

- Implement the Adaptive Cards renderer in
  `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py`:
  - Subclass core `AbstractA2UIRenderer` (TASK-1723); **never** legacy
    `BaseRenderer` (exec sink — see contract).
  - Register via `register_a2ui_renderer` with capabilities:
    `interactive=False`, `supports_actions=False`, `supports_updates=False`,
    `output="application/vnd.microsoft.card.adaptive"`.
  - Input handling: obtain the **lowered Basic tree** for every component
    (call the catalog `lower()` contract from TASK-1725's components); do not
    branch on Parrot-native component names.
  - **Bake first** (TASK-1728 helper): the emitted card JSON contains zero live
    JSON Pointer bindings and no A2UI data-model section — pure static card.
  - Map the Basic display vocabulary → AC elements; card envelope carries
    `"$schema": "http://adaptivecards.io/schemas/adaptive-card.json"` and a
    pinned card `version` (match the version already used by
    `hitl_cards.py` — verify in code).
  - **No `Action.*` emission in v1.** `requires_actions` components: degrade to a
    deep-link line rendered as a display element (e.g. TextBlock with the resume
    URL) when `DeepLink`s are provided, else strip with a visible notice; if
    neither degradation is possible for the surface, reject with a structured
    error per capabilities.
  - Unsupported/unmappable Basic elements → deterministic fallback (e.g.
    TextBlock with the component title) — never silent drop, log at warning.
  - Return a `RenderedArtifact` whose `content` is the serialized card JSON.
- Write unit tests (mapping, no-Action invariant, baking, degradation, schema
  header) with golden-card comparisons where practical.

**NOT in scope**:
- Sending cards to Teams (`CardFactory`, `send_card`, Graph upload — Module 7 /
  existing integrations). This task produces card JSON only.
- `Action.Submit`/`Action.OpenUrl` or any interactive AC support (FEAT-B; note:
  even deep links are rendered as display text/URL, not `Action.OpenUrl`, to keep
  the no-`Action.*` invariant trivially greppable in v1).
- Other Module 5 renderers (TASK-1729/1731/1732).
- Lowering implementations themselves (TASK-1725 / Module 3).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py` | CREATE | Basic-tree → Adaptive Card JSON renderer + registration |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/__init__.py` | MODIFY | Created by TASK-1729; create it here if racing (regular package init, see packaging note) |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_adaptive_cards.py` | CREATE | Unit tests + golden cards |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verified references from the actual codebase (re-checked 2026-07-10).
> Do NOT invent imports/attributes not listed here — `grep`/`read` first.

### Verified Adaptive Cards precedent in this monorepo
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/handler.py
#   :55  return CardFactory.adaptive_card(card_data)      # get_card
#   :58  return CardFactory.adaptive_card(card_data)      # create_card
#   :72  attachment = CardFactory.adaptive_card(card_data)  # send_card
# → downstream consumers take a plain card-JSON dict; this renderer only has to
#   produce that dict correctly.

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/hitl_cards.py
#   :48  _AC_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
#   :110 / :138  "$schema": _AC_SCHEMA   # card bodies built as plain dicts
# → deterministic dict-built AC cards are an established in-repo pattern; check
#   the card "version" value used there and pin the same one.
```

### Verified Packaging Layout (same finding as TASK-1729 — summary)
- Satellite has NO `__init__.py` at `src/parrot/`, `src/parrot/outputs/`,
  `src/parrot/outputs/formats/` (PEP 420); core `outputs/__init__.py:23-24` and
  `formats/__init__.py:1-2` use `pkgutil.extend_path` to merge satellite dirs.
- `a2ui_renderers/` is satellite-owned → regular package with `__init__.py`
  (mirrors satellite-owned leaf packages `formats/assets|generators|mixins`).

### Forbidden legacy anchor
```python
# packages/ai-parrot/src/parrot/outputs/formats/base.py
class BaseRenderer(ABC):   # :54 — execute_code (:125) contains exec(code, ...) (:163)
# NEVER subclassed or imported by A2UI renderers (G1).
```

### Interfaces created by dependency tasks (spec §2 sketch — verify against merged code)
```python
# TASK-1723 (core): register_a2ui_renderer(name, capabilities) / AbstractA2UIRenderer
#   async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact | str
#   RendererCapabilities(interactive, supports_actions, supports_updates, output)
# TASK-1725 (core catalog components): each component implements
#   def lower(self, component, data_model) -> BasicTree   # pure, deterministic (D8)
# TASK-1728 (core): RenderedArtifact / DeepLink models + bake helper
```

### Does NOT Exist
- ~~`adaptive_cards.py` under any `parrot/outputs/`~~ — no AC renderer exists in
  the outputs pipeline today (AC building lives only in msteams integration
  modules cited above); this task creates the outputs-side one.
- ~~Teams `on_invoke_activity` handler~~ — card submits arrive as `message`
  activities with `activity.value` (`msteams/wrapper.py:305`, :457); irrelevant
  in v1 (no actions) but do not design for `invoke`.
- ~~A "Basic Catalog → AC" mapping table anywhere in the repo~~ — you define it
  in this task; keep it a module-level declarative dict, golden-tested.
- ~~`botbuilder` / `CardFactory` availability in ai-parrot-visualizations~~ — do
  NOT import msteams integration code here; emit plain JSON dicts only.

---

## Implementation Notes

### Key Constraints
- **Lowered-tree input only**: the renderer's walker understands the Basic
  Catalog vocabulary exclusively. If handed a native component, obtain its
  lowering via the catalog contract; if a component has no lowering, that is a
  registration-time bug upstream (G4 enforcement) — raise, don't work around.
- **No-`Action.*` invariant must be machine-checkable**: acceptance includes a
  grep/test asserting no `"type": "Action.` string can appear in any emitted card.
- Deterministic: same lowered tree + data → byte-identical card JSON
  (`sort_keys`/stable ordering) — golden-file friendly.
- Text values pass through as AC `text` fields (AC hosts treat them as text, but
  do not interpolate data into any field interpreted as markup/URL without
  validation; deep-link URLs come only from `DeepLink.url`).
- Async `render`; Pydantic v2 for any internal models; Google-style docstrings;
  module logger, no prints.

### References in Codebase
- `msteams/hitl_cards.py` — dict-built card shape, `$schema`/version fields.
- `formats/structured_base.py` / `structured_map.py:177` — the config-driven
  deterministic-renderer style (data in → markup out, no code execution) that
  the STRUCTURED_* family pioneered and A2UI generalizes.
- Spec §2 component diagram — "third-party renderers … + AC fallback transcode".

---

## Acceptance Criteria

- [ ] Renderer registered as `adaptive_cards` with capabilities
      `interactive=False`, `supports_actions=False`, `supports_updates=False`,
      `output="application/vnd.microsoft.card.adaptive"`
- [ ] Consumes lowered Basic trees; native components handled only via their `lower()`
- [ ] Card JSON carries the verified `$schema` value and a pinned version; zero
      live bindings (baked); no A2UI data-model section in output
- [ ] No `Action.*` element ever emitted (test + `grep -rn '"Action\.' ` on golden output)
- [ ] `requires_actions` components degrade (deep-link display line / stripped +
      notice) or reject with a structured error — never silently dropped
- [ ] Returns `RenderedArtifact` with serialized card JSON
- [ ] All tests pass: `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_adaptive_cards.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers`
- [ ] No exec/eval: `grep -rn "exec(\|eval(" packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers` returns nothing
- [ ] `BaseRenderer` and msteams integration modules are never imported

---

## Test Specification

> Minimal scaffold — names and intent only; the agent fills in bodies.

```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_adaptive_cards.py
class TestAdaptiveCardsRenderer:
    def test_capabilities_declared(self):
        """Capabilities: interactive=False, supports_actions=False,
        output='application/vnd.microsoft.card.adaptive'."""
        ...

    async def test_lowered_tree_maps_to_card_golden(self):
        """Golden test: a lowered Basic tree produces the expected Adaptive Card
        JSON (deterministic, byte-stable)."""
        ...

    async def test_card_has_schema_and_pinned_version(self):
        """Emitted card carries the adaptivecards.io $schema and the pinned version."""
        ...

    async def test_no_action_elements_emitted(self):
        """No 'Action.*' typed element appears anywhere in any emitted card (v1
        display-subset invariant)."""
        ...

    async def test_output_has_zero_live_bindings(self):
        """Baked card contains no unresolved JSON Pointer binding syntax and no
        A2UI data-model section."""
        ...

    async def test_requires_actions_degrades_or_rejects(self):
        """requires_actions component: deep-link display line when DeepLinks are
        provided; stripped with visible notice otherwise; structured error when
        neither degradation applies."""
        ...

    async def test_unmappable_element_falls_back_deterministically(self):
        """An unmappable Basic element degrades to the documented fallback element
        with a warning log — never a silent drop."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index (`sdd/tasks/index/`) → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1730-renderer-adaptive-cards.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Notes**: Implemented `AdaptiveCardsRenderer` (satellite) subclassing the core
`AbstractA2UIRenderer`, registered as `adaptive_cards` with capabilities all-False and
output `application/vnd.microsoft.card.adaptive`. Bakes first, lowers each component to
its Basic tree, then maps the Basic vocabulary → AC elements (Text→TextBlock with
title/heading styling, Column/Card→Container, Row→ColumnSet, Image→Image). Card carries
`$schema` = adaptivecards.io and pinned `version` "1.5" (matching msteams/hitl_cards.py).
No `Action.*` element is ever emitted; deep links render as display TextBlocks (not
Action.OpenUrl); Form degrades to its lowered "not available" notice; unmappable
elements fall back to a TextBlock with a warning log. Output is `json.dumps(sort_keys=True)`
(deterministic); no data-model section. 8 tests pass; ruff clean; no exec/eval; msteams
integration code never imported.

**Deviations from spec**: `render()` adds optional `deep_links` kwarg (as in
TASK-1729). The "reject with structured error when neither degradation applies" branch
is not reachable in practice because Form's lowering always supplies a visible notice —
so degradation never fails; documented here rather than adding dead code.
