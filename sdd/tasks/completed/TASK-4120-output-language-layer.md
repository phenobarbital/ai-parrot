# TASK-4120: Define `OUTPUT_LANGUAGE_LAYER` and `GROUNDING_SENTINELS`

**Feature**: FEAT-638 — Bot-Level Output Language Directive
**Spec**: `sdd/specs/jiraspecialist-agent-multilang.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the **definition** half of spec §3 **Module 3**, plus the `GROUNDING_SENTINELS`
constant from **Module 5**. Both are pure data in `domain_layers.py`.

This task deliberately does **not** install the layer into any builder. Installing it
before `AbstractBot` knows how to remove it when unset would make every agent render a
literal `$output_language` — so installation and wiring ship together in TASK-4121.
Likewise `GROUNDING_SENTINELS` is defined here but `JIRA_GROUNDING_LAYER` is not changed
until TASK-4122, after TASK-4121 injects the sentinel variables. Splitting it this way
means no intermediate commit ever renders an unresolved placeholder.

---

## Scope

- Add `OUTPUT_LANGUAGE_LAYER` (CONFIGURE phase, priority `OUTPUT - 1` = 59, **no `condition=`**).
- Add `GROUNDING_SENTINELS` (`en` + `es`).
- Register `"output_language"` in `_DOMAIN_LAYERS`.
- Write unit tests.

**NOT in scope**: adding the layer to `PromptBuilder.default()`/`voice()` and the
`AbstractBot` wiring (TASK-4121); changing `JIRA_GROUNDING_LAYER`'s template (TASK-4122);
exporting the new names from `parrot/bots/prompts/__init__.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` | MODIFY | New layer + sentinel table + registry entry |
| `packages/ai-parrot/tests/bots/prompts/test_output_language_layer.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported at the top of domain_layers.py (verified: domain_layers.py:9-13):
from typing import Dict
from .layers import PromptLayer, LayerPriority, RenderPhase
# Add `Final` to the typing import for GROUNDING_SENTINELS.
# For tests:
from parrot.bots.prompts.domain_layers import get_domain_layer   # verified: domain_layers.py:805
from parrot.bots.prompts.layers import LayerPriority, RenderPhase  # verified: layers.py:22, :35
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/prompts/layers.py
@dataclass(frozen=True)
class PromptLayer:                                  # line 51
    name: str
    priority: LayerPriority | int
    template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    required_vars: frozenset[str] = field(default_factory=frozenset)
    cacheable: Optional[bool] = field(default=None)  # derives True for CONFIGURE (layers.py:76-80)
    def render(self, context: Dict[str, Any]) -> Optional[str]: ...  # line 82

class LayerPriority(IntEnum): ... OUTPUT = 60 ...   # line 22; priority 59 is unused (verified)

# packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py
_DOMAIN_LAYERS: Dict[str, PromptLayer] = {          # line 789
    ...
    "data_instructions": DATA_INSTRUCTIONS_LAYER,   # line 801 (last entry)
}
def get_domain_layer(name: str) -> PromptLayer: ... # line 805 — raises KeyError if unknown
```

### Does NOT Exist
- ~~`OUTPUT_LANGUAGE_LAYER`~~ / ~~`GROUNDING_SENTINELS`~~ — created by this task.
- ~~`get_domain_layer("output_language")`~~ — raises `KeyError` until this task registers it.
- ~~A `condition=` on this layer~~ — **forbidden** (S4): `partial_render()` keeps a false-condition layer live (`layers.py:116-117`) and `_build_prompt()` forwards `**kwargs` into the request context, so a request-time `language=` would reactivate it. Unset is handled by **removal** in TASK-4121.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/prompts/test_output_language_layer.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/prompts/layers.py#PromptLayer",
    "sym:packages/ai-parrot/src/parrot/bots/prompts/layers.py#LayerPriority",
    "sym:packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py#get_domain_layer"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The layer is installed for **every** text agent (TASK-4121), so its wording is generic;
  Jira appears only as an example.
- The template's only `$` variable is `$output_language`. Do not add others — any other
  `$name` would survive `safe_substitute` as a literal.
- Sentinel strings are **assertion targets** downstream (TASK-4122). Use exactly the values
  below; `en` must stay byte-identical to today's FEAT-138 sentinels.

---

## Implementation Blueprint

### Steps (in order)
1. Add `Final` to the `typing` import — *why*: `GROUNDING_SENTINELS` is a `Final` constant per spec §3 M5.
2. Insert both definitions above the registry comment — *why*: the registry must reference them after they are defined.
3. Register `"output_language"` — *why*: spec AC; makes `get_domain_layer("output_language")` resolve.
4. Write the tests.

### `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -cF 'from typing import Dict' domain_layers.py)
# REPLACE `from typing import Dict` (verified: domain_layers.py:11) with:
from typing import Dict, Final
```

### `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` (MODIFY — definitions)
```python
# occurrences: 1 (verified: grep -cF '# ── Domain layer registry ──' domain_layers.py)
# BEFORE — insert above the `# ── Domain layer registry ──…` line (verified: domain_layers.py:787)

# ── Bot-level output language (FEAT-638) ──────────────────────
# Priority 59 = OUTPUT (60) - 1 → renders just before the output-format rules.
# CONFIGURE phase → cacheable (FEAT-181). NO condition=: when the bot's language
# is unset, AbstractBot._configure_prompt_builder() REMOVES this layer instead,
# because a false condition can be reactivated by a request-time kwarg (S4).
OUTPUT_LANGUAGE_LAYER = PromptLayer(
    name="output_language",
    priority=LayerPriority.OUTPUT - 1,
    phase=RenderPhase.CONFIGURE,
    template="""<output_language_policy>
Write every artifact you create or modify in $output_language: tickets, issue
summaries and descriptions, comments, reports, and any status, standup or
escalation message you author (for example Jira issues and comments). This
applies even when the user writes to you in another language.

Reply to the user in the language they used. Only the artifacts follow
$output_language.

Never translate identifiers. Keep these verbatim: issue keys, project keys,
status and transition names, labels, components, usernames and account IDs,
query strings such as JQL or SQL, URLs, file paths, and code blocks.

When you quote or summarize existing content (an existing ticket, comment,
description or document), keep the quoted text in its original language.
</output_language_policy>""",
    required_vars=frozenset({"output_language"}),
)

GROUNDING_SENTINELS: Final[Dict[str, Dict[str, str]]] = {
    "en": {"not_found": "No results found for", "error": "Jira lookup failed"},
    "es": {"not_found": "No se encontraron resultados para", "error": "La consulta a Jira falló"},
}
"""Localized FEAT-138 sentinel prefixes, keyed by ISO 639-1 code.

Injected into the prompt as ``$sentinel_not_found`` / ``$sentinel_error`` by
``AbstractBot._configure_prompt_builder()``; consumed by JIRA_GROUNDING_LAYER.
The ``en`` row must stay byte-identical to the original FEAT-138 phrases.
"""
```
**Why**: name/priority/phase are fixed by spec §3 M3; the four paragraphs are the four
rules the spec mandates (artifact language, reply exception, never-translate list, quote
preservation). Do not reword the `en` sentinels.

### `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py` (MODIFY — registry)
```python
# occurrences: 1 (verified: grep -cF '    "data_instructions": DATA_INSTRUCTIONS_LAYER,' domain_layers.py)
# AFTER — insert below that line (verified: domain_layers.py:801)
    "output_language": OUTPUT_LANGUAGE_LAYER,
```

### `packages/ai-parrot/tests/bots/prompts/test_output_language_layer.py` (CREATE)
```python
"""Tests for OUTPUT_LANGUAGE_LAYER and GROUNDING_SENTINELS (FEAT-638 TASK-4120)."""
from parrot.bots.prompts.domain_layers import (
    GROUNDING_SENTINELS,
    OUTPUT_LANGUAGE_LAYER,
    get_domain_layer,
)
from parrot.bots.prompts.layers import LayerPriority, RenderPhase


def test_layer_registered():
    assert get_domain_layer("output_language") is OUTPUT_LANGUAGE_LAYER


def test_layer_is_configure_and_cacheable():
    assert OUTPUT_LANGUAGE_LAYER.phase == RenderPhase.CONFIGURE
    assert OUTPUT_LANGUAGE_LAYER.cacheable is True
    assert int(OUTPUT_LANGUAGE_LAYER.priority) == int(LayerPriority.OUTPUT) - 1


def test_layer_has_no_condition():
    """S4 guard: unset must be handled by removal, never by a condition."""
    assert OUTPUT_LANGUAGE_LAYER.condition is None


def test_layer_renders_language_and_rules():
    rendered = OUTPUT_LANGUAGE_LAYER.render({"output_language": "Spanish"})
    # FILL IN: assert "Spanish" appears; assert no "$" placeholder survives; assert the
    #   never-translate list names issue keys, status and transition names, JQL, URLs and
    #   code blocks; assert the reply-in-user-language and quote-preservation rules are present
    #   — bounded by spec §3 M3 (four rules).


def test_grounding_sentinels_shape():
    # Subset, not equality: adding a language must not break this test. The
    # all-catalogs-cover-SUPPORTED_LANGUAGES check lives in TASK-4126's doc-sync test.
    assert {"en", "es"} <= set(GROUNDING_SENTINELS)
    for row in GROUNDING_SENTINELS.values():
        assert set(row) == {"not_found", "error"}


def test_grounding_sentinels_en_is_unchanged():
    """The en row must stay byte-identical to the FEAT-138 phrases."""
    assert GROUNDING_SENTINELS["en"] == {"not_found": "No results found for", "error": "Jira lookup failed"}
```

### FILL IN checklist
- [ ] `test_layer_renders_language_and_rules` — assertions for the four rules and no surviving `$`

---

## Acceptance Criteria

- [ ] `get_domain_layer("output_language")` resolves to `OUTPUT_LANGUAGE_LAYER`.
- [ ] `OUTPUT_LANGUAGE_LAYER.condition is None`, phase CONFIGURE, `cacheable is True`, priority 59.
- [ ] The rendered layer states all four rules and leaves no `$` placeholder when given `output_language`.
- [ ] `GROUNDING_SENTINELS["en"]` is byte-identical to the FEAT-138 sentinels.
- [ ] No builder installs the layer yet; `JIRA_GROUNDING_LAYER` is unchanged.
- [ ] Existing `test_domain_layers.py` and `test_domain_layer_registry_jira.py` still pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/prompts/test_output_language_layer.py -q`
- `pytest packages/ai-parrot/tests/bots/prompts/test_domain_layers.py -q`
- `pytest packages/ai-parrot/tests/bots/prompts/test_domain_layer_registry_jira.py -q`

---

## Test Specification

See the `test_output_language_layer.py` blueprint block above.

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

**Completed by**: sdd-worker (codex gpt-5.6-terra, 1 attempt)
**Date**: 2026-10-08
**Notes**: OUTPUT_LANGUAGE_LAYER + GROUNDING_SENTINELS in domain_layers.py; 6 tests pass.

**Deviations from spec**: none
