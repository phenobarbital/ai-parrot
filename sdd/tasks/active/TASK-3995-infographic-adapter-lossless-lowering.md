# TASK-3995: Lossless Infographic → A2UI lowering (progress group, hints, hero zero)

**Feature**: FEAT-623 — Infographic → A2UI display hints
**Spec**: `sdd/specs/infographic-a2ui-display-hints.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3994
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, plus codex S5/S7/S8 (§9). Today the adapter loses meaning
that the HTML lane keeps:
- `progress` becomes bare `KPICard{label, value}`. The title, the 0–100
  percent meaning and the target are dropped.
- Tables drop `align`, and cannot carry `type`/`format`.
- Charts cannot ask for `seriesAxes`.
- `_hero_card` turns a numeric `0` into `""`.
- The module docstring falsely claims nothing is dropped.

This task makes the lowering lossless, using only wire vocabulary that already
exists.

**Decision (Juan, 2026-09-30, spec §8 revised)**: a titled `progress` block
stays **inside the current section** as ONE `Column{Text(title),
Row{KPICard…}}` descriptor. It never opens a section, because more than one
section renders as tabs. That happens in the catalog lowering
(`catalog/parrot/infographic.py`, test
`test_infographic_lowering_preserves_section_order_as_tabs`) and in both
Svelte renderers.

---

## Scope

- `_progress`: map each item to
  `KPICard{label, value: value/100, format: "percent"}`, plus:
  - `comparisonPeriod: "vs N% target"` only when `target` is set;
  - `color` when set.
- New `_progress_group`: titled → `Column{children: [Text{text: title},
  Row{children: kpis}]}`; untitled → `Row{children: kpis}`. `walk` adds
  exactly ONE descriptor per progress block.
- `_hero_card`: explicit-None value check (`0` survives); forward
  `format`/`unit` when set.
- `_table`: each column becomes `{name, title}` plus `type`/`format` when
  the `ColumnDef` sets them. `align`/`width`/`color` are dropped (lossy,
  documented; follow-up per spec §8 Q3).
- `_chart`: when ≥1 series sets `axis`, emit `seriesAxes`, a list parallel
  to `y` with `"left"` for unset entries. Emit `yAxisLabels` when
  `y_axis_labels` is set.
- Correct the module docstring: the `progress` mapping row, the sectioning
  note, and the "Known lossy degradations" list, which must name
  `ColumnDef.align/width/color`.
- Update the two existing progress tests and add new ones, including the
  **envelope half** of the lanes-agree check (`test_display_hints_envelope`).

**NOT in scope**:
- HTML lane rendering, including the HTML half of `test_infographic_lanes_agree` (TASK-3997).
- `format_cell` (TASK-3996).
- Admin UI (TASK-3998/3999).
- The walkthrough (TASK-4002).
- **Do NOT regenerate `packages/ai-parrot/tests/outputs/a2ui/golden/infographic_lowered.json`.** It is the
  golden of the Infographic *component lowering* fed with a hand-built
  `Component` (`test_components_infographic_report.py:83`), not adapter
  output. This task cannot affect it, and it must stay byte-identical. The
  spec §6 Edit-Sites row for it is drift.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` | MODIFY | lossless `_progress` + `_progress_group`, hero/table/chart hints, docstring |
| `packages/ai-parrot/tests/outputs/a2ui/adapters/test_infographic_adapter.py` | MODIFY | update 2 progress tests; add hint / zero / group / envelope tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# adapter (unchanged imports — G8 one-way rule: a2ui core + parrot.models.infographic only)
from parrot.outputs.a2ui.builders import build_infographic   # adapters/infographic.py:69
from parrot.outputs.a2ui.models import CreateSurface         # :70
# tests (already imported at test_infographic_adapter.py:9-24)
from parrot.models.infographic import InfographicResponse
from parrot.outputs.a2ui.adapters import CHART_TYPE_MAP, infographic_response_to_envelope
from parrot.outputs.a2ui.catalog import ProducerOrigin, get_component, validate_envelope
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py
def _as_dict_or_none(value: Any) -> dict[str, Any] | None      # :118
def _clean(props: dict[str, Any]) -> dict[str, Any]            # :134 drops None values
def _descriptor(component: str, properties: dict[str, Any]) -> dict[str, Any]  # :139 {"component", "properties": _clean(props)}
def _unique(name: str, taken: dict[str, int]) -> str            # :144
class _SectionAccumulator:  # :172  add(descriptor) :201
class _Converter:           # :220
    def _chart(self, block) -> dict          # :236 ; `if block.get("y_axis_label") is not None:` :283 ;
                                             # `series_colors = [s.get("color") for s in series]` :289 ; `return _descriptor("Chart", properties)` :293
    def _table(self, block) -> dict          # :295 ; `names: list[str] = []` :300 ; loop `for column in block.get("columns") or []:` :301 ;
                                             # `names.append(_unique(header or "column", taken))` :306 ;
                                             # `"columns": [{"name": name, "title": name} for name in names],` :315
    def _hero_card(self, block) -> dict      # :323 ; `"value": block.get("value") or "",` :326 ;
                                             # `if block.get("comparison_period") is not None:` :334 ; `return _descriptor("KPICard", properties)` :336
    def _progress(self, block) -> list[dict] # :355-367 (current: {"label","value"} per item)
    def walk(...)                            # :532 ; `for descriptor in self._progress(block):` :588
# Docstring anchors: ``progress``       one ``KPICard`` per item  (:40) ;
#   "nothing presentation-relevant is dropped any more):" (:55) ; InfoCard lossy bullet (:57)
# Precedents for primitive wrappers: `_descriptor("Row", {"children": cards})` (:493, _card_grid);
#   `_descriptor("Column", {"children": pane_children})` (:525, _tabs); `_descriptor("Text", {"text": ...})` (_bullet_list :369+)

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/infographic.py
def _lower_child(descriptor, data_model, child_id) -> BasicNode   # :76 — a primitive's `children` list of
#   descriptors is lowered recursively (:109-118), so KPICard inside Row inside Column lowers.

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/kpicard.py
# KPICARD_SCHEMA :15 — format enum percent|currency|number (:43); unit; comparisonPeriod; color

# packages/ai-parrot/src/parrot/models/infographic.py (after TASK-3994)
# ProgressItem: label, value: float 0..100 (:905), color, target: Optional[float] 0..100 (:907)
# ColumnDef.type/format ; ChartDataSeries.axis ; ChartBlock.y_axis_labels ; HeroCardBlock.format/unit

# tests/outputs/a2ui/adapters/test_infographic_adapter.py
def _response(**overrides) -> InfographicResponse   # :27
def _sections(envelope) -> list                      # :58
def _validate_full_tree(envelope)                    # :62 lowers + validates the whole tree
# test_progress_expands_to_one_kpicard_per_item      # :467 — MUST be rewritten (now one Row)
# test_progress_with_malformed_item_does_not_raise   # :801 — MUST be rewritten (labels now inside the Row)
# TestAllBlocksEnvelope.test_a2ui_envelope_new_blocks # :892 — progress value "80" (str); must stay green
```

### Does NOT Exist
- ~~A `target` / `progress` prop on `KPICard`~~: the target travels as `comparisonPeriod` text.
- ~~`DataTable.columns[].align/width/color` on the wire~~: `TableColumn` is `name/type/title/format`. They are dropped.
- ~~`_SectionAccumulator.open()` for progress~~: never open a section for progress.
- ~~A `heading`/`variant: "h3"` on Basic `Text`~~: `Text.variant` is only `caption|body`, so the title is a plain `Text{text}`.
- ~~Adapter regeneration of `infographic_lowered.json`~~: see Scope.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/adapters/test_infographic_adapter.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py#_Converter",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py#_Converter._progress",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py#_Converter._hero_card",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py#_Converter._table",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py#_Converter._chart",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py#_Converter.walk",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py#_descriptor"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The adapter stays **pure and deterministic**: no clocks, uuids or I/O.
  Omit keys whose value is None (`_clean` does it), and never invent values.
- The section count is unchanged for every payload (spec §5).
- Wire vocabulary is unchanged: only `KPICard.format/comparisonPeriod/color/unit`,
  `DataTable.columns[].type/format`, and `Chart.seriesAxes/yAxisLabels`.
- Percent formatting of the target text: at most 1 decimal, no trailing `.0`
  (`80` → `"vs 80% target"`, `92.5` → `"vs 92.5% target"`).

---

## Implementation Blueprint

### Steps (in order)
1. Rewrite `_progress` and add `_progress_group` — *why*: the decided group
   shape keeps goals visible (no tabs).
2. Change the `walk` progress branch to add ONE descriptor — *why*: a group
   is one child of the section.
3. Fix `_hero_card` (value None check plus `format`/`unit`) — *why*: codex S7;
   a numeric `0` must survive.
4. Extend `_table` to forward `type`/`format` — *why*: renderers sort and
   format from declared types instead of guessing.
5. Extend `_chart` with `seriesAxes`/`yAxisLabels` — *why*: a rate and a
   count need two scales.
6. Correct the docstring — *why*: the "nothing dropped" claim is false.
7. Update and add tests — *why*: they pin every mapping, including the
   negatives (no `delta`, no new section).

### `adapters/infographic.py` (MODIFY) — progress
```python
# occurrences: 1 (verified: grep -cF 'def _progress(self, block: dict[str, Any]) -> list[dict[str, Any]]:' packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py)
# REPLACE the whole method starting at that anchor (verified: :355-367) with:
    def _progress(self, block: dict[str, Any]) -> list[dict[str, Any]]:
        """One ``KPICard`` per item: ``value/100`` with ``format='percent'``.

        ``ProgressItem.value`` is a 0–100 completion percentage by model contract,
        while ``KPICard.format='percent'`` means a RATIO — so divide here, and only
        here. A target becomes neutral ``comparisonPeriod`` text, never ``delta``
        (which carries trend colour and ``higherIsBetter`` judgement).
        """
        descriptors = []
        for raw in block.get("items") or []:
            item = _as_dict_or_none(raw)
            if item is None:
                continue
            props: dict[str, Any] = {
                "label": item.get("label") or "",
                "value": _percent_ratio(item.get("value")),
                "format": "percent",
                "comparisonPeriod": _target_text(item.get("target")),
                "color": item.get("color"),
            }
            descriptors.append(_descriptor("KPICard", props))
        return descriptors

    def _progress_group(self, block: dict[str, Any]) -> dict[str, Any]:
        """ONE descriptor for a progress block — never a new section (>1 section = tabs)."""
        row = _descriptor("Row", {"children": self._progress(block)})
        title = _text(block.get("title"))
        if not title:
            return row
        return _descriptor("Column", {"children": [_descriptor("Text", {"text": title}), row]})
```
Add two module-level helpers next to `_text` (anchor `def _text(value: Any) -> str | None:`; run `grep -cF` first, it should be 1):
```python
def _percent_ratio(value: Any) -> Any:
    """0–100 completion → ratio; non-numeric values pass through unchanged."""
    # FILL IN: return float(value) / 100 for int/float/numeric str (the all-blocks test sends
    # "80"); return the raw value otherwise — bounded by "never invent", adapter docstring.


def _target_text(target: Any) -> str | None:
    """``vs N% target`` (max 1 decimal, no trailing .0) or ``None`` when unset/non-numeric."""
    # FILL IN: None → None; 80 → "vs 80% target"; 92.5 → "vs 92.5% target"; 0 → "vs 0% target".
```
**Why**: the helpers keep `_progress` flat (complexity budget) and are unit-testable.

### `adapters/infographic.py` (MODIFY) — walk branch
```python
# occurrences: 1 (verified: grep -cF 'for descriptor in self._progress(block):' ... → :588)
# REPLACE the 2 lines `for descriptor in self._progress(block):` / `sections.add(descriptor)` with:
                sections.add(self._progress_group(block))
```

### `adapters/infographic.py` (MODIFY) — hero card
```python
# occurrences: 1 (verified: grep -cF '"value": block.get("value") or "",' ... → :326)
# REPLACE that line with:
            "value": "" if block.get("value") is None else block.get("value"),
# occurrences: 1 (verified: grep -cF 'if block.get("comparison_period") is not None:' ... → :334)
# AFTER the 2-line comparison_period block (:334-335), before `return _descriptor("KPICard", properties)` (:336):
        if block.get("format") is not None:
            properties["format"] = block["format"]
        if block.get("unit") is not None:
            properties["unit"] = block["unit"]
```

### `adapters/infographic.py` (MODIFY) — table
```python
# occurrences: 1 (verified: grep -cF 'names.append(_unique(header or "column", taken))' ... → :306)
# FILL IN: inside the loop at :301-306 also collect `hints: list[dict]` — {} for a str
#   column, {"type": ..., "format": ...} (None-free) from the ColumnDef dict otherwise;
#   align/width/color are NOT forwarded — bounded by spec §8 Q3 (lossy, follow-up).
# occurrences: 1 (verified: grep -cF '"columns": [{"name": name, "title": name} for name in names],' ... → :315)
# REPLACE that line with:
            "columns": [{"name": name, "title": name, **hint} for name, hint in zip(names, hints, strict=True)],
```

### `adapters/infographic.py` (MODIFY) — chart
```python
# occurrences: 1 (verified: grep -cF 'return _descriptor("Chart", properties)' ... → :293)
# BEFORE `return _descriptor("Chart", properties)`:
        series_axes = [s.get("axis") for s in series]
        if any(a is not None for a in series_axes):
            properties["seriesAxes"] = [a or "left" for a in series_axes]
        if block.get("y_axis_labels") is not None:
            properties["yAxisLabels"] = block["y_axis_labels"]
```

### `adapters/infographic.py` (MODIFY) — docstring
```text
# occurrences: 1 each (verified: grep -cF) — ``progress``       one ``KPICard`` per item (:40);
#   nothing presentation-relevant is dropped any more): (:55)
# :40 → ``progress``       ``Row`` of ``KPICard`` (ratio + format='percent'); titled →
#                          ``Column{Text(title), Row}`` in the CURRENT section
# :52-55 → reword: drop the "nothing presentation-relevant is dropped" claim.
# FILL IN: add a lossy bullet after the InfoCard bullet (:57-59): "``ColumnDef``
#   ``align``/``width``/``color`` have no ``DataTable.columns[]`` counterpart and are
#   dropped (HTML lane only; extending ``TableColumn`` is a follow-up, FEAT-623 §8 Q3)."
#   Add one sentence to the sectioning policy: progress never opens a section.
```

### `tests/outputs/a2ui/adapters/test_infographic_adapter.py` (MODIFY)
```python
# Rewrite :467 test_progress_expands_to_one_kpicard_per_item → untitled block = ONE Row whose
#   children are 2 KPICards with value 0.8 / 0.45 and format "percent".
# Rewrite :801 malformed test → labels read from components[0]["properties"]["children"].
# Add (FILL IN bodies; use _response(), _sections(), _validate_full_tree()):
#   test_progress_titled_is_group_in_current_section  — len(_sections) unchanged; one Column
#       [Text(title), Row]; _validate_full_tree passes (nested KPICard lowers)
#   test_progress_zero_and_full — 0 → 0.0, 100 → 1.0; target 0 → "vs 0% target"; no target → key absent
#   test_progress_target_never_delta — "delta" not in any KPICard props
#   test_hero_numeric_zero_preserved — value 0 and 0.0 reach KPICard.value as 0 (not "")
#   test_hero_forwards_format_unit / test_table_forwards_type_format (align dropped) /
#   test_chart_series_axes_parallel_to_y (["left","right"] + yAxisLabels; absent when no axis)
#   test_display_hints_envelope — one payload: numeric hero (currency), typed table,
#       titled progress, right-axis chart → assert every forwarded prop in one place
#       (envelope half of spec §4 test_infographic_lanes_agree; HTML half is TASK-3997)
```

### FILL IN checklist
- [ ] `_percent_ratio` / `_target_text` bodies, plus their unit tests.
- [ ] `_table` hint collection (no align/width/color).
- [ ] Docstring: the lossy bullet and the sectioning sentence.
- [ ] Two rewritten tests and eight new tests, with no `...` left.

---

## Acceptance Criteria

- [ ] AC-1: a titled `progress` yields exactly one `Column{Text(title), Row{KPICard…}}` in the current section; an untitled one yields one `Row`. The section count is unchanged.
- [ ] AC-2: progress KPICards carry `value = item.value/100` and `format: "percent"`. A set target yields `comparisonPeriod: "vs N% target"`. `delta` is never set.
- [ ] AC-3: a numeric hero `value` of `0` survives. Hero `format`/`unit` are forwarded only when set.
- [ ] AC-4: table columns carry `type`/`format` only when declared. `align`/`width`/`color` are dropped and documented.
- [ ] AC-5: `seriesAxes` (parallel to `y`, with `"left"` defaults) is emitted only when some series sets `axis`. `yAxisLabels` is forwarded when set.
- [ ] AC-6: the docstring no longer claims nothing is dropped.
- [ ] AC-7: the adapter is deterministic (existing `TestPurity` green), and `infographic_lowered.json` is byte-identical.
- [ ] AC-8: `TestAllBlocksEnvelope` still validates the whole tree.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/adapters/test_infographic_adapter.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_components_infographic_report.py -q`
- `pytest packages/ai-parrot/tests/tools/test_infographic_toolkit_a2ui_wiring.py -q`

---

## Agent Instructions

1. Work in the feature worktree. TASK-3994 must be `done` first, because this task reads its fields.
2. Re-run every `grep -cF` above. A count of `0` means the anchor drifted: stop and report it.
3. Implement from the blueprint, complete every FILL IN, and run the Validation Commands.
4. Commit only the two listed files. Close with `scripts/sdd/close_task.sh TASK-3995 infographic-a2ui-display-hints verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
- `infographic_lowered.json` is NOT regenerated, because it is not adapter output (spec §6 drift).
- Progress is a group in the current section, not a new section (spec §8 revised).
