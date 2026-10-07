# TASK-4122: Localize the FEAT-138 grounding sentinels

**Feature**: FEAT-638 — Bot-Level Output Language Directive
**Spec**: `sdd/specs/jiraspecialist-agent-multilang.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4120, TASK-4121
**Assigned-to**: unassigned

---

## Context

Implements the template half of spec §3 **Module 5**. FEAT-138's `JIRA_GROUNDING_LAYER`
mandates two verbatim reply prefixes ("No results found for …", "Jira lookup failed: …").
The brainstorm decided to localize them (design research suggestion S9 to keep them invariant
was rejected — the user chose this explicitly). The anti-hallucination **rules** do not change;
only the surface wording becomes language-dependent.

The layer stays a module constant and a `_DOMAIN_LAYERS` entry. Its four literal sentinel
occurrences become `$sentinel_not_found` / `$sentinel_error`, which TASK-4121 already injects
into every bot's configure context (English when unset). Because the injection lands first,
there is never a commit where a real bot renders a literal `$sentinel_*`.

---

## Scope

- Replace the four sentinel literals in `JIRA_GROUNDING_LAYER.template` with `$sentinel_not_found` / `$sentinel_error`.
- Rewrite `test_jira_grounding_layer.py` to render with an explicit per-language context.
- Source the sentinel constants in `test_jira_specialist_grounding.py` from `GROUNDING_SENTINELS["en"]`.

**NOT in scope**: anything else in the policy text (rules 1–6 stay word-for-word);
`JIRA_WORKFLOW_LAYER`; the docs (TASK-4126); the `_load_prompts_module()` loader in
`test_jira_specialist_grounding.py` (TASK-4124 extends it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` | MODIFY | 4 sentinel literals → template variables |
| `packages/ai-parrot/tests/bots/prompts/test_jira_grounding_layer.py` | MODIFY | Per-language rendering tests |
| `packages/ai-parrot/tests/test_jira_specialist_grounding.py` | MODIFY | Sentinel constants from `GROUNDING_SENTINELS["en"]` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.prompts.domain_layers import GROUNDING_SENTINELS, JIRA_GROUNDING_LAYER  # TASK-4120 / domain_layers.py:223
from parrot.bots.prompts.layers import LayerPriority, PromptLayer, RenderPhase           # verified: test_jira_grounding_layer.py:3
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py
JIRA_GROUNDING_LAYER = PromptLayer(                    # line 223
    name="jira_grounding",
    priority=LayerPriority.BEHAVIOR - 5,               # 65
    phase=RenderPhase.CONFIGURE,
    template="""<jira_grounding_policy> ... """,       # sentinel literals at lines 230, 231, 242, 246
)
GROUNDING_SENTINELS: Final[Dict[str, Dict[str, str]]]  # TASK-4120: {"en": {...}, "es": {...}}

# packages/ai-parrot/tests/test_jira_specialist_grounding.py
#   imports sys (line 23); _load_prompts_module() registers the REAL domain_layers module under
#   sys.modules["parrot.bots.prompts.domain_layers"] (line 124) inside a synthetic parrot.bots.prompts.
SENTINEL_NOT_FOUND = "No results found for"            # line 200
SENTINEL_ERROR = "Jira lookup failed"                  # line 201 — used at :270 :277 :333 :340 :366 :431
```

### Does NOT Exist
- ~~A per-language copy of `JIRA_GROUNDING_LAYER`~~ / ~~`build_jira_grounding_layer(language)` factory~~ — do not create one; the layer stays a single constant with template variables.
- ~~`required_vars` on `JIRA_GROUNDING_LAYER`~~ — do not add it; the spec does not, and an unconditional requirement could break callers that render the layer outside `AbstractBot`.
- ~~A real `parrot.bots.prompts` package inside `test_jira_specialist_grounding.py`~~ — it is synthetic; read `GROUNDING_SENTINELS` from `sys.modules`, not via `from parrot.bots.prompts import ...`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/prompts/test_jira_grounding_layer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_jira_specialist_grounding.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py#JIRA_GROUNDING_LAYER"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `$sentinel_error:` is safe — `string.Template` identifiers stop at `:`.
- The English rendering must be **byte-identical** to the pre-feature layer when given the
  English context. The rules-unchanged test below proves this structurally.
- `test_jira_specialist_grounding.py`'s 8 assertion sites stay untouched: the constants keep
  the exact same English values, they are just sourced from the table now.

---

## Implementation Blueprint

### Steps (in order)
1. Replace the four literals in the template — *why*: the only wording that varies by language.
2. Rewrite `test_jira_grounding_layer.py` — *why*: its `render({})` calls would now return literal placeholders.
3. Re-point the two constants in `test_jira_specialist_grounding.py` — *why*: single source of truth for the sentinels.

### `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` (MODIFY — 4 lines)
```python
# Each anchor: occurrences: 1 (verified: grep -cF '<anchor>' domain_layers.py)
# line 230: REPLACE  "No results found for <KEY|JQL>." and stop. On a tool error,
#           WITH     "$sentinel_not_found <KEY|JQL>." and stop. On a tool error,
# line 231: REPLACE  reply "Jira lookup failed: <message>." and stop.
#           WITH     reply "$sentinel_error: <message>." and stop.
# line 242: REPLACE     `No results found for <KEY|JQL>.` and stop. Do NOT retry the same
#           WITH        `$sentinel_not_found <KEY|JQL>.` and stop. Do NOT retry the same
# line 246: REPLACE     `Jira lookup failed: <message>.` and stop. Do NOT apologise and then
#           WITH        `$sentinel_error: <message>.` and stop. Do NOT apologise and then
```
Also add one comment line directly above `JIRA_GROUNDING_LAYER = PromptLayer(`:
```python
# FEAT-638: sentinel wording comes from GROUNDING_SENTINELS via $sentinel_not_found /
# $sentinel_error, injected by AbstractBot._configure_prompt_builder(). Rules are unchanged.
```
**Why**: nothing else in the policy may change — the regression test below compares the
English and Spanish renderings with sentinels masked.

### `packages/ai-parrot/tests/bots/prompts/test_jira_grounding_layer.py` (MODIFY — replace whole file)
```python
"""Tests for JIRA_GROUNDING_LAYER (FEAT-138 TASK-945; localized by FEAT-638 TASK-4122)."""
import pytest

from parrot.bots.prompts.domain_layers import GROUNDING_SENTINELS, JIRA_GROUNDING_LAYER
from parrot.bots.prompts.layers import LayerPriority, PromptLayer, RenderPhase

LANGS = sorted(GROUNDING_SENTINELS)


def _ctx(lang: str) -> dict:
    row = GROUNDING_SENTINELS[lang]
    return {"sentinel_not_found": row["not_found"], "sentinel_error": row["error"]}


def _masked(lang: str) -> str:
    row = GROUNDING_SENTINELS[lang]
    rendered = JIRA_GROUNDING_LAYER.render(_ctx(lang))
    return rendered.replace(row["not_found"], "<NF>").replace(row["error"], "<ER>")


def test_jira_grounding_layer_metadata():
    assert isinstance(JIRA_GROUNDING_LAYER, PromptLayer)
    assert JIRA_GROUNDING_LAYER.name == "jira_grounding"
    assert JIRA_GROUNDING_LAYER.phase == RenderPhase.CONFIGURE
    assert int(JIRA_GROUNDING_LAYER.priority) == int(LayerPriority.BEHAVIOR) - 5


@pytest.mark.parametrize("lang", LANGS)
def test_jira_grounding_layer_contains_sentinel_phrases(lang):
    rendered = JIRA_GROUNDING_LAYER.render(_ctx(lang))
    assert GROUNDING_SENTINELS[lang]["not_found"] in rendered
    assert GROUNDING_SENTINELS[lang]["error"] in rendered
    assert "$sentinel" not in rendered


@pytest.mark.parametrize("lang", LANGS)
def test_jira_grounding_layer_load_bearing_rules_in_first_paragraph(lang):
    first_paragraph = JIRA_GROUNDING_LAYER.render(_ctx(lang)).split("\n\n", 1)[0]
    assert "fabricate" in first_paragraph.lower() or "fabrication" in first_paragraph.lower()
    assert GROUNDING_SENTINELS[lang]["not_found"] in first_paragraph
    assert GROUNDING_SENTINELS[lang]["error"] in first_paragraph


def test_jira_grounding_layer_english_has_no_spanish():
    rendered = JIRA_GROUNDING_LAYER.render(_ctx("en"))
    for phrase in ["No encontré", "Hubo un error", "disculpa", "consultando",
                   GROUNDING_SENTINELS["es"]["not_found"], GROUNDING_SENTINELS["es"]["error"]]:
        assert phrase not in rendered


def test_jira_grounding_layer_spanish_replaces_english_sentinels():
    rendered = JIRA_GROUNDING_LAYER.render(_ctx("es"))
    assert GROUNDING_SENTINELS["en"]["not_found"] not in rendered
    assert GROUNDING_SENTINELS["en"]["error"] not in rendered


def test_jira_grounding_rules_unchanged_across_languages():
    """Only the sentinel wording varies — every rule is identical in every language."""
    assert len({_masked(lang) for lang in LANGS}) == 1


def test_jira_grounding_layer_needs_injected_vars():
    """Documents the dependency on AbstractBot's injection (TASK-4121)."""
    assert "$sentinel_not_found" in JIRA_GROUNDING_LAYER.render({})
```

### `packages/ai-parrot/tests/test_jira_specialist_grounding.py` (MODIFY)
```python
# occurrences: 1 each (verified: grep -cF 'SENTINEL_NOT_FOUND = "No results found for"' and
#   grep -cF 'SENTINEL_ERROR = "Jira lookup failed"' test_jira_specialist_grounding.py)
# REPLACE lines 200-201 with:
# FEAT-638: single source of truth; the REAL domain_layers module was registered in
# sys.modules by _load_prompts_module() above (the parrot.bots.prompts package is synthetic).
GROUNDING_SENTINELS = sys.modules["parrot.bots.prompts.domain_layers"].GROUNDING_SENTINELS
SENTINEL_NOT_FOUND = GROUNDING_SENTINELS["en"]["not_found"]
SENTINEL_ERROR = GROUNDING_SENTINELS["en"]["error"]
```

### FILL IN checklist
- [ ] none — this task is fully specified; if any anchor count is not 1, stop and report drift

---

## Acceptance Criteria

- [ ] `JIRA_GROUNDING_LAYER` renders the `en`/`es` sentinels for the matching context and leaves no `$sentinel` when the context is supplied.
- [ ] With sentinels masked, the English and Spanish renderings are identical (rules unchanged).
- [ ] The English rendering is byte-identical to the pre-feature layer.
- [ ] `test_jira_grounding_layer.py` and `test_jira_specialist_grounding.py` pass.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/prompts/test_jira_grounding_layer.py -q`
- `pytest packages/ai-parrot/tests/test_jira_specialist_grounding.py -q`
- `pytest packages/ai-parrot/tests/bots/prompts/test_domain_layer_registry_jira.py -q`

---

## Test Specification

See the `test_jira_grounding_layer.py` blueprint block above (it is the complete file).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug jiraspecialist-agent-multilang --feature-id FEAT-638`)
2. **Read the spec** at `sdd/specs/jiraspecialist-agent-multilang.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/jiraspecialist-agent-multilang.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - Re-run each blueprint `grep -c` anchor check; a count of `0` means the anchor is gone — stop and report
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/jiraspecialist-agent-multilang.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src` (add `packages/ai-parrot-server/src` for server files)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> jiraspecialist-agent-multilang verified`
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
