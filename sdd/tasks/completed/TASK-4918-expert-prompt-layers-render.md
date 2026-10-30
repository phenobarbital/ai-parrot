# TASK-4918: Expert prompt layers and KnowledgeContext rendering

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4914
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6, G4, codex S2/S3. A resolved `KnowledgeContext` becomes two **literal** prompt layers:
`expert_rules` at a new `LayerPriority.RULES = 12` (between identity and pre-instructions) and
`expert_knowledge` at `LayerPriority.KNOWLEDGE`. Literal because the text is authored by bundle owners or comes
from advisories — a `$name` inside must never be template-substituted (AC17). Installation works on a clone of
the builder, never on a shared instance (AC18).

---

## Scope

- Add `RULES = 12` to `LayerPriority` and the two layer constants in `bots/prompts/layers.py`.
- Create `experts/knowledge/render.py` with `render_rules`, `render_knowledge`, `install_layers`.
- Write `test_render.py`.

**NOT in scope**: calling `install_layers` from an agent (TASK-4924), producing the `KnowledgeContext` (TASK-4919).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/prompts/layers.py` | MODIFY | `RULES = 12`, `EXPERT_RULES_LAYER`, `EXPERT_KNOWLEDGE_LAYER` |
| `packages/ai-parrot/tests/bots/prompts/test_layers.py` | MODIFY | `test_all_nine_levels` asserted 9 `LayerPriority` members; `RULES` makes it 10 (contract gap found at merge) |
| `packages/ai-parrot/src/parrot/experts/knowledge/render.py` | CREATE | Render + install |
| `packages/ai-parrot/tests/experts/test_render.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase   # verified: layers.py:51,22,35
from parrot.bots.prompts.builder import PromptBuilder                           # verified: builder.py:35
from parrot.experts.models import KnowledgeContext, KnowledgeMode               # TASK-4914
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/prompts/layers.py
class LayerPriority(IntEnum):     # line 22 — IDENTITY = 10 (line 24), PRE_INSTRUCTIONS = 15, SECURITY = 20, KNOWLEDGE = 30, ...
class RenderPhase(str, Enum):     # line 35 — CONFIGURE = "configure", REQUEST = "request"
@dataclass(frozen=True)
class PromptLayer:                # line 51
    name: str; priority: LayerPriority | int; template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    required_vars: frozenset[str]; cacheable: Optional[bool] = None
    literal: bool = False         # line 78 — True: template is plain text, never substituted
KNOWLEDGE_LAYER = PromptLayer(name="knowledge", priority=LayerPriority.KNOWLEDGE, phase=RenderPhase.REQUEST,
    template="<knowledge_context>\n$knowledge_content\n</knowledge_context>",
    condition=lambda ctx: bool(ctx.get("knowledge_content", "").strip()))   # lines 191-199
# packages/ai-parrot/src/parrot/bots/prompts/builder.py
class PromptBuilder:                                        # line 35
    def add(self, layer: PromptLayer) -> PromptBuilder      # line 200 — add or replace by name
    def remove(self, name: str) -> PromptBuilder            # line 212 — no-op when absent
    def get(self, name: str) -> Optional[PromptLayer]       # line 242
    def clone(self) -> PromptBuilder                        # line 253 — deep copy of layers
```

### Does NOT Exist
- ~~`LayerPriority.RULES`~~ — added by this task.
- ~~`PromptLayer.with_template()`~~ — frozen dataclass; build a new layer with `dataclasses.replace(layer, template=…)`.
- ~~`PromptBuilder.insert` / `PromptBuilder.layers` setter~~ — use `add` / `remove` only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/prompts/layers.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/experts/knowledge/render.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/experts/test_render.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/prompts/layers.py#LayerPriority",
    "sym:packages/ai-parrot/src/parrot/bots/prompts/layers.py#PromptLayer",
    "sym:packages/ai-parrot/src/parrot/bots/prompts/layers.py#RenderPhase",
    "sym:packages/ai-parrot/src/parrot/bots/prompts/builder.py#PromptBuilder"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `install_layers` returns a **new** builder (`builder.clone()` first) and removes the default `"knowledge"` layer.
  Known gap to record in the Completion Note, not to redesign: request-time KB search results for experts flow
  through `knowledge_content`, which only the default layer renders — TASK-4923 and TASK-4934 decide whether the
  expert knowledge layer must also carry them.
- Render deterministically: same `KnowledgeContext` → same string (AC4 depends on it).

---

## Implementation Blueprint

### Steps (in order)
1. Add the enum member and layer constants — *why*: `render.py` imports them.
2. Write the two renderers, then `install_layers` — *why*: AC8 / AC17.

### `packages/ai-parrot/src/parrot/bots/prompts/layers.py` (MODIFY) — enum
```python
# occurrences: 1 (verified: grep -c '    IDENTITY = 10' packages/ai-parrot/src/parrot/bots/prompts/layers.py)
# AFTER — insert below `    IDENTITY = 10` (verified: layers.py:24)
    RULES = 12  # FEAT-778: expert governance rules, after identity, before pre-instructions
```

### `packages/ai-parrot/src/parrot/bots/prompts/layers.py` (MODIFY) — constants
```python
# occurrences: 1 (verified: grep -c '    condition=lambda ctx: bool(ctx.get("knowledge_content", "").strip()),' packages/ai-parrot/src/parrot/bots/prompts/layers.py)
# AFTER — insert below the `)` that closes KNOWLEDGE_LAYER, i.e. after line 199 (anchor line 198)

# ── EXPERT LAYERS (FEAT-778) ────────────────────────────────────
# Literal: authored bundle text is never template-substituted (AC17).
EXPERT_RULES_LAYER = PromptLayer(
    name="expert_rules",
    priority=LayerPriority.RULES,
    phase=RenderPhase.CONFIGURE,
    template="",
    literal=True,
)
EXPERT_KNOWLEDGE_LAYER = PromptLayer(
    name="expert_knowledge",
    priority=LayerPriority.KNOWLEDGE,
    phase=RenderPhase.CONFIGURE,
    template="",
    literal=True,
)
```

### `packages/ai-parrot/src/parrot/experts/knowledge/render.py` (CREATE)
```python
"""Render a KnowledgeContext into literal prompt layers (FEAT-778 M6)."""
from __future__ import annotations

import dataclasses

from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import EXPERT_KNOWLEDGE_LAYER, EXPERT_RULES_LAYER
from parrot.experts.models import KnowledgeContext, KnowledgeMode


def render_rules(ctx: KnowledgeContext) -> str:
    """<governance_rules>…</governance_rules> from the 'rules' layer; '' when there is no rule text."""
    text = ctx.inline_text("rules").strip()
    return f"<governance_rules>\n{text}\n</governance_rules>" if text else ""


def render_knowledge(ctx: KnowledgeContext) -> str:
    """<expert_knowledge> with one <section layer source revision> per INLINE non-rules layer, in ctx order."""
    # FILL IN: skip 'rules' and RETRIEVAL layers; escape nothing (literal layer); deterministic — bounded by AC4
    return ""


def install_layers(builder: PromptBuilder, ctx: KnowledgeContext) -> PromptBuilder:
    """Return a clone of `builder` with expert_rules / expert_knowledge added and 'knowledge' removed (S2)."""
    new_builder = builder.clone()
    new_builder.remove("knowledge")
    rules = render_rules(ctx)
    knowledge = render_knowledge(ctx)
    if rules:
        new_builder.add(dataclasses.replace(EXPERT_RULES_LAYER, template=rules))
    if knowledge:
        new_builder.add(dataclasses.replace(EXPERT_KNOWLEDGE_LAYER, template=knowledge))
    return new_builder
```
**Why this shape**: cloning first is the S2 isolation rule; `dataclasses.replace` keeps `literal=True` from the
constants, which is the AC17 guarantee.

### FILL IN checklist
- [ ] `render_knowledge` — section format with `source` and `revision` attributes; bounded by AC4/AC6.

---

## Acceptance Criteria

- [ ] AC8 (render part) — `expert_rules` sits at priority 12 with `literal=True`.
- [ ] AC17 (render part) — `$name` inside rules or knowledge text appears verbatim in `builder.build({...})`.
- [ ] `install_layers` never mutates the builder it receives (identity of layers checked in test).
- [ ] `ruff check` passes on both source files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_render.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/experts/test_render.py
def test_rules_priority_is_12(): ...                         # FILL IN
def test_render_installs_literal_layers(): ...               # FILL IN: knowledge layer removed, two added
def test_install_layers_does_not_mutate_input(): ...         # FILL IN
def test_dollar_placeholders_survive_build(): ...            # FILL IN: "$name" and "IGNORE PREVIOUS INSTRUCTIONS" verbatim
def test_render_is_deterministic(): ...                      # FILL IN
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug domain-experts --feature-id FEAT-778`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/domain-experts.json`
4. **Verify the Codebase Contract** — before writing ANY code, confirm every import and signature still exists;
   if anything changed, update the contract FIRST. Never reference a name not in the contract without verifying it.
5. **Update status** in `sdd/tasks/index/domain-experts.json` → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
   (add `packages/ai-parrot-server/src` when the task touches the server) and `ruff check` the files you changed
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4918 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker; Seat: opus (native) · Attempts: 1
**Date**: 2026-10-30
**Notes**: Merged; task-tier gate and chunk merge-tier validation green (80 + 5 passed).

**Deviations from spec**: Added tests/bots/prompts/test_layers.py to the MODIFY list (count test 9→10 after RULES=12); contract corrected in-task.
