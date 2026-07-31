# TASK-1844: CAPABILITIES_LAYER + "identity" PromptBuilder preset

**Feature**: FEAT-321 — PromptBuilder Identity Capability
**Spec**: `sdd/specs/promptbuilder-identity-capability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1. `capabilities` is one of the five identity fields
`AbstractBot` resolves, but the composable prompt path silently drops it:
`IDENTITY_LAYER` omits `$capabilities` by design, and the only layer rendering
it (`KNOWLEDGE_SCOPE_LAYER`) is RAG-only. This task creates the reusable
`CAPABILITIES_LAYER`, registers it in the domain-layer registry, and registers
an `"identity"` preset (default stack + the layer) so builder-savvy agents can
adopt capabilities rendering via the existing `prompt_preset` kwarg without any
mixin.

---

## Scope

- Implement `CAPABILITIES_LAYER` in
  `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py`:
  - `name="capabilities"`, `priority=LayerPriority.IDENTITY + 1` (= 11, slots
    between `IDENTITY_LAYER` (10) and `AGENT_CONTEXT_LAYER` (12)),
    `phase=RenderPhase.CONFIGURE`,
    template `<capabilities>\n$capabilities\n</capabilities>`,
    `condition=lambda ctx: bool(ctx.get("capabilities", "").strip())`
    (mirror `KNOWLEDGE_SCOPE_LAYER`'s condition style at domain_layers.py:154-167).
- Register it: `_DOMAIN_LAYERS["capabilities"] = CAPABILITIES_LAYER` so
  `get_domain_layer("capabilities")` resolves.
- Register the preset in
  `packages/ai-parrot/src/parrot/bots/prompts/presets.py`:
  `register_preset("identity", lambda: PromptBuilder.default().add(CAPABILITIES_LAYER))`
  — a *fresh* builder per call (match how existing presets behave).
- Write unit tests (see Test Specification).

**NOT in scope**: the file loader (TASK-1845), the mixin/hot-reload
(TASK-1846), Porygon (TASK-1847), any edit to `IDENTITY_LAYER` or
`PromptBuilder.default()` (both stay untouched — spec non-goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` | MODIFY | Add `CAPABILITIES_LAYER` + `"capabilities"` registry entry |
| `packages/ai-parrot/src/parrot/bots/prompts/presets.py` | MODIFY | Register `"identity"` preset |
| `packages/ai-parrot/tests/bots/prompts/test_capabilities_layer.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-21 on `dev`. Use these VERBATIM; verify anything not listed.

### Verified Imports
```python
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase
from parrot.bots.prompts.domain_layers import get_domain_layer, _DOMAIN_LAYERS
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.presets import register_preset, get_preset
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/prompts/layers.py
class LayerPriority(IntEnum):   # line 22 — IDENTITY=10 (AGENT_CONTEXT_LAYER uses literal 12)
class RenderPhase(str, Enum):   # line 35 — CONFIGURE="configure" (46), REQUEST="request" (47)
@dataclass(frozen=True)
class PromptLayer:              # line 50 — fields: name, priority, template,
    ...                         # phase=REQUEST, condition=None, required_vars, cacheable
    def render(self, context: Dict[str, Any]) -> Optional[str]: ...  # line 82 — safe_substitute;
                                # returns None when condition fails
# cacheable derives from phase in __post_init__ (75-80): CONFIGURE ⇒ cacheable=True

# packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py
KNOWLEDGE_SCOPE_LAYER   # line 154-167 — style reference: CONFIGURE layer with
                        # condition=lambda ctx: bool(ctx.get("capabilities", "").strip())
_DOMAIN_LAYERS: Dict[str, PromptLayer]   # line 576 — 10 keys today
def get_domain_layer(name: str) -> PromptLayer: ...  # line 590 — raises KeyError on unknown

# packages/ai-parrot/src/parrot/bots/prompts/builder.py
class PromptBuilder:                                  # line 21
    @classmethod
    def default(cls) -> PromptBuilder: ...            # line 52 — IDENTITY..BEHAVIOR stack
    def add(self, layer: PromptLayer) -> PromptBuilder: ...  # line 152 — add-or-replace by
                                                      # name, MUTATES in place, returns self

# packages/ai-parrot/src/parrot/bots/prompts/presets.py
_PRESETS   # line 15 — {"default","minimal","voice","agent","rag"} name → factory
def register_preset(name, factory)   # line 24
def get_preset(name)                 # line 34 — calls factory: fresh builder per call
```

### Does NOT Exist
- ~~`CAPABILITIES_LAYER`~~ / ~~`_DOMAIN_LAYERS["capabilities"]`~~ — created by THIS task.
- ~~an `"identity"` entry in `_PRESETS`~~ — created by THIS task.
- ~~`IDENTITY_LAYER` rendering `$capabilities`~~ — it does NOT (layers.py:137-152) and
  must NOT be edited.
- ~~`LayerPriority.CAPABILITIES`~~ — no such enum member; use `LayerPriority.IDENTITY + 1`
  (`PromptLayer.priority` accepts `LayerPriority | int`).
- ~~`PromptBuilder.add()` returning a new builder~~ — it mutates and returns `self`.

---

## Implementation Notes

### Pattern to Follow
Mirror `KNOWLEDGE_SCOPE_LAYER` (domain_layers.py:154-167): a module-level frozen
`PromptLayer` constant with a strip-checking condition, registered in the
`_DOMAIN_LAYERS` dict literal. Register the preset the same way existing
presets appear in `presets.py` (`_PRESETS` at line 15 / `register_preset` at 24);
importing `CAPABILITIES_LAYER` into `presets.py` is cycle-safe
(presets → domain_layers → layers; presets → builder → layers).

### Key Constraints
- `PromptLayer` is a frozen dataclass — compose, never mutate.
- Do NOT add the layer to `PromptBuilder.default()` — non-adopters must be
  byte-for-byte unchanged (spec AC).
- Preset factory must return a **fresh** builder each call (the class builders
  are shared; a cached instance would leak layers across agents).

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:154` — layer style
- `packages/ai-parrot/src/parrot/bots/prompts/presets.py:15-40` — preset registry
- `packages/ai-parrot/tests/bots/prompts/test_domain_layers.py` — test conventions

---

## Acceptance Criteria

- [ ] `get_domain_layer("capabilities")` returns the layer; priority == 11;
      `phase is RenderPhase.CONFIGURE`; `cacheable is True`.
- [ ] `CAPABILITIES_LAYER.render({"capabilities": "x"})` == `"<capabilities>\nx\n</capabilities>"`;
      empty/whitespace `capabilities` → `None`.
- [ ] `get_preset("identity")` returns default stack + capabilities layer; two
      calls return distinct builder objects.
- [ ] `PromptBuilder.default()` still does NOT contain a `"capabilities"` layer.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/bots/prompts/test_capabilities_layer.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/prompts/`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/prompts/test_capabilities_layer.py
from parrot.bots.prompts.domain_layers import CAPABILITIES_LAYER, get_domain_layer
from parrot.bots.prompts.layers import RenderPhase, LayerPriority
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.presets import get_preset


class TestCapabilitiesLayer:
    def test_registered(self):
        assert get_domain_layer("capabilities") is CAPABILITIES_LAYER

    def test_layer_metadata(self):
        assert CAPABILITIES_LAYER.priority == LayerPriority.IDENTITY + 1
        assert CAPABILITIES_LAYER.phase is RenderPhase.CONFIGURE
        assert CAPABILITIES_LAYER.cacheable is True

    def test_renders_capabilities(self):
        out = CAPABILITIES_LAYER.render({"capabilities": "- do X"})
        assert out == "<capabilities>\n- do X\n</capabilities>"

    def test_empty_capabilities_skipped(self):
        assert CAPABILITIES_LAYER.render({"capabilities": "  "}) is None
        assert CAPABILITIES_LAYER.render({}) is None


class TestIdentityPreset:
    def test_identity_preset_stack(self):
        builder = get_preset("identity")
        assert builder.get("capabilities") is not None
        assert builder.get("identity") is not None   # default stack present

    def test_fresh_builder_per_call(self):
        assert get_preset("identity") is not get_preset("identity")

    def test_default_unchanged(self):
        assert PromptBuilder.default().get("capabilities") is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — before writing ANY code, confirm every
   listed import/signature still exists; update the contract first if drifted
4. **Update status** in `sdd/tasks/index/promptbuilder-identity-capability.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1844-capabilities-layer-identity-preset.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-21
**Notes**: Implemented `CAPABILITIES_LAYER` in `domain_layers.py` (priority
`IDENTITY + 1` = 11, CONFIGURE phase, condition mirrors
`KNOWLEDGE_SCOPE_LAYER`'s strip-check style) and registered it under
`_DOMAIN_LAYERS["capabilities"]`. Registered the `"identity"` preset in
`presets.py` via a `_identity_preset()` factory (`PromptBuilder.default().add(
CAPABILITIES_LAYER)`), returning a fresh builder per call. All 7 new unit
tests pass; verified `PromptBuilder.default()` still has no `"capabilities"`
layer (non-adopters unchanged). Pre-existing baseline failures in
`test_yaml_prompt_config.py` / `test_pandasagent_prompt.py` (54 failed / 229
passed before this task, 54 failed / 236 passed after — same 54, all
attributable to a missing `BotManager._build_prompt_builder` unrelated to
this feature) confirmed via `git stash` comparison — no regressions
introduced. `ruff check` clean on both modified files and the new test file.

**Deviations from spec**: none
