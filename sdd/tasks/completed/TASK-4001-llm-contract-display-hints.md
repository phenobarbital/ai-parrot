# TASK-4001: Teach the LLM contract the new infographic display hints

**Feature**: FEAT-623 — Infographic → A2UI display hints
**Spec**: `sdd/specs/infographic-a2ui-display-hints.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3994
**Assigned-to**: unassigned

---

## Context

Spec Module 7. TASK-3994 (Module 1) adds optional display hints to the
infographic models:
- `HeroCardBlock.value: str | float` with `format` / `unit`;
- `ColumnDef.type` / `format`;
- `ChartDataSeries.axis`;
- `ChartBlock.y_axis_labels`.

The LLM only learns these from the infographic system-prompt addon and the
template contract text. Today both show only pre-formatted strings
(`"value": "$3.7M"`, `bots/prompts/__init__.py:83`) and say nothing about
the ratio rule. As a result the model keeps sending `"68.3%"` strings,
which renderers cannot format or sort.

---

## Scope

- In `INFOGRAPHIC_SYSTEM_PROMPT_ADDON` (`bots/prompts/__init__.py`):
  - keep the `"$3.7M"` hero example verbatim;
  - add one numeric hero example with `format`;
  - add a short "display hints" paragraph covering:
    - a numeric hero `value` + `format` (`percent` | `currency` | `number`) + optional `unit`;
    - **the ratio rule**: a percentage is sent as a ratio (`0.683` with `format="percent"`), never as `"68.3%"` and never as `68.3`;
    - literal table `columns` as `ColumnDef` objects with `type` / `format`;
    - `series[].axis = "right"` plus `y_axis_labels` when two series have different scales.
- In `InfographicTemplate.to_prompt_instruction()`
  (`models/infographic_templates.py`): append the same hints as a compact,
  template-agnostic block after the "Each block must include the 'type'
  field…" line, so every template's contract carries it.
- Add a test asserting both texts mention the new fields and still contain
  the `$3.7M` example.

**NOT in scope**:
- the model fields themselves (TASK-3994);
- `infographic_build_block` typed columns from dtypes (spec Module 6);
- per-template `BlockSpec.description` changes;
- the KPICard catalog instructions (`catalog/parrot/kpicard.py`), which
  already state the ratio rule.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/prompts/__init__.py` | MODIFY | numeric hero example + display-hints paragraph |
| `packages/ai-parrot/src/parrot/models/infographic_templates.py` | MODIFY | display-hints block in `to_prompt_instruction()` |
| `packages/ai-parrot/tests/unit/models/test_infographic_display_hints_prompt.py` | CREATE | assertions on both texts |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.prompts import INFOGRAPHIC_SYSTEM_PROMPT_ADDON  # verified: packages/ai-parrot/tests/unit/handlers/test_agent_format_infographic.py:19 ; defined bots/prompts/__init__.py:53
from parrot.models.infographic_templates import InfographicTemplate  # verified: models/infographic_templates.py:47
from parrot.models.infographic_templates import TEMPLATE_DASHBOARD   # verified: models/infographic_templates.py:250
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/prompts/__init__.py
INFOGRAPHIC_SYSTEM_PROMPT_ADDON = """ ... """                       # :53 (plain str, NOT an f-string)
#   step 3 bullets (:70-84):
#   :82  `                 infographic_build_block(block_type="hero_card",`
#   :83  `                 block={"type": "hero_card", "label": "Revenue", "value": "$3.7M"})`
#   :84  `   Add the blocks in the EXACT positional order of the template contract.`
# Consumed at tools/infographic_toolkit.py:424 as `f"{tmpl}\n{INFOGRAPHIC_SYSTEM_PROMPT_ADDON}"`,
# later rendered with `string.Template(...).safe_substitute(...)` (bots/abstract.py:1332-1333).

# packages/ai-parrot/src/parrot/models/infographic_templates.py
class InfographicTemplate(BaseModel):                                 # :47
    def to_prompt_instruction(self) -> str:                           # :69 — builds `lines`, returns "\n".join(lines)
#   :101-104
#        lines.append("")
#        lines.append(
#            "Each block must include the 'type' field matching the block type above."
#        )
#   :106 `        # Extended instructions for tab_view blocks`
TEMPLATE_DASHBOARD = InfographicTemplate(name="dashboard", ...)       # :250
```

### Does NOT Exist
- ~~A test pinning the full `to_prompt_instruction()` output~~: `tests/test_infographic_autodetect.py:195,203` only check substrings. Re-run it anyway.
- ~~A `DISPLAY_HINTS` constant~~ anywhere today. If you factor one out, define it in `infographic_templates.py` and use it there. Keep the prompt addon self-contained, since it is a plain string.
- ~~`format="compact"`~~: not a valid value (spec Non-Goals). Never mention it.
- ~~A `target` field on KPICard~~: do not document one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/prompts/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/models/infographic_templates.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/models/test_infographic_display_hints_prompt.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/prompts/__init__.py#INFOGRAPHIC_SYSTEM_PROMPT_ADDON",
    "sym:packages/ai-parrot/src/parrot/models/infographic_templates.py#InfographicTemplate.to_prompt_instruction",
    "sym:packages/ai-parrot/src/parrot/models/infographic_templates.py#TEMPLATE_DASHBOARD"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **No `$` followed by a letter or `{`** anywhere in the new prompt text.
  The addon reaches `string.Template.safe_substitute`, so `$name`-shaped
  tokens would be substituted. `$3.7M` is safe (a digit follows `$`). In
  examples, write currency as a number (`"value": 1203456, "format": "currency"`).
- The text must stay consistent with the models from TASK-3994. Use the
  exact field names: `format`, `unit`, `type`, `axis`, `y_axis_labels`.
- Keep it short, about 8–12 lines per location. The addon is already long.
- `percent` always means a ratio. Say it explicitly, because
  `ProgressItem.value` is 0–100 by contract and that is the one documented
  exception. Mention it as "progress items keep 0–100".

### References in Codebase
- `catalog/parrot/kpicard.py:56-66` (`KPICARD_INSTRUCTIONS`): existing ratio-rule wording to stay consistent with.

---

## Implementation Blueprint

### Steps (in order)
1. Confirm TASK-3994 is done and the field names match its models. *Why*: the prompt must not document a field that does not exist.
2. Add the numeric hero example and the display-hints paragraph to the addon. *Why*: this is the system-prompt path the LLM sees.
3. Append the hints to `to_prompt_instruction()`. *Why*: the template contract tool returns it on demand, independently of the addon.
4. Write the test, then run the validation commands, including the existing infographic prompt tests.

### `packages/ai-parrot/src/parrot/bots/prompts/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '   Add the blocks in the EXACT positional order of the template contract.' bots/prompts/__init__.py)
# BEFORE — insert above `   Add the blocks in the EXACT positional order of the template contract.` (verified: :84),
#          i.e. right after the existing "$3.7M" hero example (:82-83, kept verbatim)
     - a hero_card may also carry a NUMBER plus a display hint, which every
       renderer formats the same way:
                 block={"type": "hero_card", "label": "Completion rate",
                        "value": 0.683, "format": "percent"}
   Display hints (optional, never guessed by renderers):
     - format: "percent" | "currency" | "number". A percentage is a RATIO:
       send 0.683 with format "percent", never "68.3%" and never 68.3
       (progress items are the one exception: their value stays 0-100).
     - unit: appended after the number (e.g. "hrs"); not used with percent.
     - literal table columns may be objects: {"header": "MRR", "type": "number",
       "format": "currency"} instead of plain strings.
     - chart series on a different scale: {"name": "New MRR", "values": [...],
       "axis": "right"} plus "y_axis_labels": ["MRR", "New MRR"].
```
**Why**: the existing example stays valid, since a str value still renders
verbatim. The numeric example is the FEAT-611 ratio rule applied to hero
cards. FILL IN: re-indent to match the surrounding step-3 bullets exactly
(3/5/17-space columns at :78-83).

### `packages/ai-parrot/src/parrot/models/infographic_templates.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c "\"Each block must include the 'type' field matching the block type above.\"" models/infographic_templates.py)
# AFTER — insert below the closing `)` of that lines.append(...) call (verified: :102-104), before `# Extended instructions for tab_view blocks` (:106)
        lines.append("")
        lines.append("Optional display hints (renderers never guess them):")
        lines.append(
            "  - hero_card: value may be a number with format "
            "'percent' | 'currency' | 'number' and an optional unit."
        )
        lines.append(
            "  - percent means a RATIO: 0.683 with format 'percent', never '68.3%' "
            "(progress item values stay 0-100)."
        )
        lines.append(
            "  - table columns may be objects {header, type, format} instead of strings."
        )
        lines.append(
            "  - chart series may set axis='right' (with y_axis_labels [left, right]) "
            "when scales differ."
        )
```
**Why**: it is template-agnostic, so it sits after the generic 'type'
rule and before the tab_view-only section.

### `packages/ai-parrot/tests/unit/models/test_infographic_display_hints_prompt.py` (CREATE)
```python
"""FEAT-623 (TASK-4001): the LLM-facing infographic contract teaches the display hints."""

from __future__ import annotations

import re

from parrot.bots.prompts import INFOGRAPHIC_SYSTEM_PROMPT_ADDON
from parrot.models.infographic_templates import TEMPLATE_DASHBOARD


def test_addon_keeps_string_hero_example() -> None:
    """The pre-formatted hero example stays valid and present."""
    assert '"value": "$3.7M"' in INFOGRAPHIC_SYSTEM_PROMPT_ADDON


def test_addon_teaches_display_hints() -> None:
    """Numeric hero + format, the ratio rule, typed columns and the right axis are all taught."""
    text = INFOGRAPHIC_SYSTEM_PROMPT_ADDON
    for needle in ('"format": "percent"', "RATIO", '"type"', '"axis": "right"', "y_axis_labels"):
        assert needle in text, needle


def test_addon_has_no_template_placeholders_added() -> None:
    """string.Template.safe_substitute must not see new $identifier tokens."""
    # FILL IN: assert no `$` followed by a letter/underscore/`{` occurs in the addon
    # (re.search(r"\$[A-Za-z_{]", ...) is None) — bounded by Key Constraints bullet 1.


def test_template_contract_teaches_display_hints() -> None:
    """Every template contract (dashboard as the sample) carries the hints block."""
    text = TEMPLATE_DASHBOARD.to_prompt_instruction()
    # FILL IN: assert "display hints", "RATIO", "axis='right'" and "{header, type, format}" are present.
```

### FILL IN checklist
- [ ] `bots/prompts/__init__.py`: indentation consistent with the step-3 bullets (:78-83).
- [ ] Test: the `$`-token guard body (Key Constraints bullet 1).
- [ ] Test: the template-contract assertions body (Scope bullet 2).
- [ ] The field names match TASK-3994's final models (Step 1).

---

## Acceptance Criteria

- [ ] The addon still contains the `"$3.7M"` hero example verbatim, plus a numeric `"format": "percent"` example.
- [ ] Both texts state the ratio rule, typed table columns, and `axis='right'` + `y_axis_labels`.
- [ ] No `$identifier` / `${` token is introduced (safe for `string.Template`).
- [ ] Existing infographic prompt tests still pass.
- [ ] The new test file passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/models/test_infographic_display_hints_prompt.py -q`
- `pytest packages/ai-parrot/tests/unit/handlers/test_agent_format_infographic.py -q`
- `pytest tests/test_infographic_autodetect.py -q`

---

## Test Specification

See the blueprint test file: the string example is kept, the hints are
present in both texts, and the `$`-token guard holds.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug infographic-a2ui-display-hints --feature-id FEAT-623`).
2. Read the spec (§3 Module 7, §2 Data Models).
3. TASK-3994 must be `done`.
4. Re-run each `grep -c` anchor.
5. Mark `"in-progress"` in the per-spec index.
6. Implement from the blueprint and complete the FILL INs.
7. Run the Validation Commands.
8. Commit only the three listed files.
9. Close with `scripts/sdd/close_task.sh TASK-4001 infographic-a2ui-display-hints verified`.
10. Fill in the Completion Note.

---

## Completion Note



**Completed by**: sdd-worker (Claude Sonnet 5.5, fallback sequential loop — parrot-sdd-coder unavailable)
**Date**: 2026-09-30
**Notes**: Prompt addon keeps the $3.7M hero example, adds a numeric+format example and a display-hints paragraph (ratio rule, ColumnDef type/format, axis right + y_axis_labels); to_prompt_instruction appends a compact template-agnostic hints line after the 'type' line. Tests pass.

**Deviations from spec**: none | describe if any
