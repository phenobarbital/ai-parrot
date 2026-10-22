# TASK-4002: Walkthrough sends raw numbers + display hints; README parity corrected

**Feature**: FEAT-623 — Infographic → A2UI display hints
**Spec**: `sdd/specs/infographic-a2ui-display-hints.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3994, TASK-3995, TASK-3997
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (G5). The A2UI walkthrough is the canonical example, and
navigator-svelte copies its `02_envelope_v1.json` as a fixture. Today it
sends pre-formatted strings: table cells use `as_money(...)` and
`f"{churn:.2f}"`, and New MRR shares the left axis. Its step-4 docstring
also claims both lanes "describe identical content by construction", which
FEAT-623 shows was not true. After TASK-3994/3995/3997, the walkthrough
should demonstrate the hints and assert them.

---

## Scope

- **`step3_blocks`, table block**: columns become `ColumnDef`-shaped dicts:
  - Month: `string`
  - MRR: `number` + `currency`, raw float
  - Churn %: `number` + `percent`, as the ratio `churn_rate / 100`
  - Accounts: `integer`
  - NPS: `integer`

  Rows carry raw numbers.
- **`step3_blocks`, MRR trend chart**: New MRR gets `"axis": "right"`, and
  the chart gets `"y_axis_labels": ["MRR (USD)", "New MRR (USD)"]` in place
  of `"y_axis_label": "USD"`.
- The hero card keeps its `as_money(...)` string headline, and
  `build_goals` stays as it is (no targets). Both are spec M8 decisions.
- **`step5_wire`**: add assertions, after the existing prints and before
  writing `02_envelope_v1.json`:
  1. The progress block arrives as one
     `Column{Text("Goal completion"), Row{KPICard…}}` group inside the
     existing section. The section count is unchanged.
  2. Those KPI cards carry `format: "percent"` with ratio values.
  3. The MRR chart carries `seriesAxes == ["left", "right"]` and
     `yAxisLabels`.
  4. The DataTable columns carry the `type` / `format` hints.
- Replace the step-4 docstring claim with an accurate statement.
- **README**: add a short "What each lane renders" note under the artifacts
  table. It says the HTML lane and the envelope now carry the same display
  hints, that `ColumnDef.align`/`width`/`color` are HTML-only (spec §8 Q3),
  and that the hero headline stays a hand-written string.
- Add a pytest that imports the walkthrough module and checks the step-3
  blocks against the adapter (pure, no agent and no network).

**NOT in scope**:
- `synthetic_data.py`: no change is required, since `build_goals` and
  `as_money` stay as they are.
- Adapter or renderer code (TASK-3995 / TASK-3997).
- Regenerating navigator-svelte's fixture, which happens in that repo.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/a2ui/a2ui_dashboard_walkthrough.py` | MODIFY | hinted table/chart blocks, step-5 assertions, step-4 docstring |
| `examples/agents/a2ui/README.md` | MODIFY | "What each lane renders" note |
| `packages/ai-parrot/tests/examples/test_a2ui_dashboard_walkthrough.py` | CREATE | step-3 blocks → envelope carries the hints |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# test file (load the example by path — examples/agents/a2ui is not a package):
import importlib.util  # stdlib
from parrot.models.infographic import InfographicResponse  # verified: packages/ai-parrot/src/parrot/models/infographic.py:1044
from parrot.outputs.a2ui.adapters.infographic import infographic_response_to_envelope  # verified: adapters/infographic.py:642 (__all__)
# walkthrough itself: `sys.path.insert(0, str(Path(__file__).resolve().parent))` (:67) then `from synthetic_data import (...)` (:84)
```

### Existing Signatures to Use
```python
# examples/agents/a2ui/a2ui_dashboard_walkthrough.py
REPO_ROOT = Path(__file__).resolve().parents[3]           # :64
OUTPUT_DIR = REPO_ROOT / "artifacts" / "a2ui_dashboard"   # :65
def step3_blocks(monthly: pd.DataFrame, plans: pd.DataFrame) -> List[Dict[str, Any]]:  # :270
    # chart MRR trend :313-325 ; `{"name": "New MRR", "values": [float(v) for v in monthly["new_mrr"]]},` :320 ; `"y_axis_label": "USD",` :322
    # table :334-350 ; `"columns": ["Month", "MRR", "Churn %", "Accounts", "NPS"],` :338 ; `as_money(float(row["mrr"])),` :342 ; `f"{row['churn_rate']:.2f}",` :343
    # progress :352 `{"type": "progress", "title": "Goal completion", "items": build_goals(monthly)}`
async def step4_render(...)                                # :366 ; docstring claim :378 "outputs therefore describe identical content by construction; the envelope"
def step5_wire(wire: Dict[str, Any]) -> CreateSurface:     # :441 ; `print(f"  data bindings            : {_find_bindings(root)}")` :493 ; `wire_path = OUTPUT_DIR / "02_envelope_v1.json"` :499
# examples/agents/a2ui/synthetic_data.py
def build_monthly_metrics(...) -> pd.DataFrame             # columns used: month, mrr, new_mrr, churn_rate (percent units, e.g. 2.80), active_accounts, nps
def build_plan_mix(monthly) -> pd.DataFrame
def build_goals(monthly) -> List[Dict[str, Any]]           # :116  {"label","value"} 0–100, no target
def as_money(value: float) -> str                          # :144
# packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py
def infographic_response_to_envelope(response, *, surface_id="infographic", title=None, theme=None) -> CreateSurface  # :642
# examples/agents/a2ui/README.md — artifacts table ends with
#   `| \`06_live_envelope.json\` | \`--live\` only: the envelope the LLM's own render produced. |` :39
```

### Does NOT Exist
- ~~An existing pytest that runs or imports the walkthrough~~: none (`git grep`
  finds no reference outside the script). This task adds the first.
- ~~`examples.agents.a2ui` as an importable package~~: load the file with
  `importlib.util.spec_from_file_location`.
- ~~A README sentence "identical content by construction"~~: the claim is in
  the walkthrough's step-4 docstring (`:378`). README `:9` talks about
  run-to-run determinism and stays as it is.
- ~~A `target` on the walkthrough goals~~: deliberately absent (spec M8).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "examples/agents/a2ui/a2ui_dashboard_walkthrough.py", "action": "MODIFY"},
    {"path": "examples/agents/a2ui/README.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/examples/test_a2ui_dashboard_walkthrough.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:examples/agents/a2ui/a2ui_dashboard_walkthrough.py#step3_blocks",
    "sym:examples/agents/a2ui/a2ui_dashboard_walkthrough.py#step5_wire",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py#infographic_response_to_envelope"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Change the table and chart blocks in `step3_blocks`. *Why*: the example
   must demonstrate the hints it advertises (G5).
2. Add the step-5 assertions. *Why*: the walkthrough doubles as a
   wire-format smoke test (README `:11-13`), so it should fail loudly if
   the hints stop flowing.
3. Fix the step-4 docstring and add the README note. *Why*: the parity
   claim was false before FEAT-623.
4. Write the pytest. Run it and the walkthrough end to end.

### `examples/agents/a2ui/a2ui_dashboard_walkthrough.py` (MODIFY) — chart
```python
# occurrences: 1 (verified: grep -c '{"name": "New MRR", "values": [float(v) for v in monthly["new_mrr"]]},' ) — :320
# REPLACE with:
                {"name": "New MRR", "values": [float(v) for v in monthly["new_mrr"]], "axis": "right"},
# occurrences: 1 (verified: grep -c '"y_axis_label": "USD",') — :322
# REPLACE with:
            "y_axis_labels": ["MRR (USD)", "New MRR (USD)"],
```

### `examples/agents/a2ui/a2ui_dashboard_walkthrough.py` (MODIFY) — table
```python
# occurrences: 1 (verified: grep -c '"columns": ["Month", "MRR", "Churn %", "Accounts", "NPS"],') — :338
# REPLACE with:
            "columns": [
                {"header": "Month", "type": "string"},
                {"header": "MRR", "type": "number", "format": "currency"},
                {"header": "Churn %", "type": "number", "format": "percent"},
                {"header": "Accounts", "type": "integer"},
                {"header": "NPS", "type": "integer"},
            ],
# occurrences: 1 each (verified: grep -c 'as_money(float(row["mrr"])),' -> :342 ; grep -c "f\"{row['churn_rate']:.2f}\"," -> :343)
# REPLACE those two row cells with:
                    round(float(row["mrr"]), 2),
                    round(float(row["churn_rate"]) / 100.0, 4),  # percent means a RATIO (2.80% -> 0.028)
```

### `examples/agents/a2ui/a2ui_dashboard_walkthrough.py` (MODIFY) — step 5
```python
# occurrences: 1 (verified: grep -c 'print(f"  data bindings            : {_find_bindings(root)}")') — :493
# AFTER — insert below that line:
    _assert_display_hints(root)

# ADD below step5_wire:
def _assert_display_hints(root: Dict[str, Any]) -> None:
    """Fail loudly if FEAT-623's display hints stop reaching the envelope.

    Args:
        root: The envelope's ``Infographic`` root component.

    Raises:
        AssertionError: When the progress group, percent KPIs, seriesAxes or column hints are missing.
    """
    # FILL IN: walk root["sections"][*]["components"] — (1) exactly one Column whose first child is Text "Goal completion" and second a Row of KPICard; section count unchanged; (2) those KPICards have format == "percent" and 0 <= value <= 1; (3) the "MRR trend" Chart has seriesAxes == ["left", "right"] and yAxisLabels; (4) the DataTable columns carry type/format — bounded by spec M8; print one "  display hints            : ok" line on success
```

### `examples/agents/a2ui/a2ui_dashboard_walkthrough.py` (MODIFY) — step 4 docstring
```python
# occurrences: 1 (verified: grep -c 'outputs therefore describe identical content by construction; the envelope') — :378
# FILL IN: rewrite the sentence (and its continuation on the next line) so it says both outputs are built from the SAME
# InfographicResponse and, since FEAT-623, carry the same display hints — but that ColumnDef align/width/color are HTML-only — bounded by spec §8 Q3
```

### `examples/agents/a2ui/README.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c "| `06_live_envelope.json` | `--live` only: the envelope the LLM's own render produced. |") — :39 -->
<!-- AFTER that table row, add: -->

### What each lane renders

Both lanes are built from the same `InfographicResponse`. Since FEAT-623 they
also carry the same display hints: numbers travel raw, with `format` / `type`;
a goal block keeps its title and percent meaning; and a series can ask for the
right axis. Two things still differ by design. `ColumnDef.align` / `width` /
`color` style only the HTML lane. The hero card's headline (`$1.20M`) is a
hand-written string, so every lane prints it verbatim.
<!-- FILL IN: keep it this short; link the spec path sdd/specs/infographic-a2ui-display-hints.spec.md -->
```

### `packages/ai-parrot/tests/examples/test_a2ui_dashboard_walkthrough.py` (CREATE)
```python
"""FEAT-623 (TASK-4002): the walkthrough's step-3 blocks carry the display hints into the envelope."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from parrot.models.infographic import InfographicResponse
from parrot.outputs.a2ui.adapters.infographic import infographic_response_to_envelope

_WALKTHROUGH = Path(__file__).resolve().parents[4] / "examples/agents/a2ui/a2ui_dashboard_walkthrough.py"


def _load():
    spec = importlib.util.spec_from_file_location("a2ui_dashboard_walkthrough", _WALKTHROUGH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_walkthrough_blocks_carry_display_hints() -> None:
    wt = _load()
    monthly = wt.build_monthly_metrics()
    blocks = wt.step3_blocks(monthly, wt.build_plan_mix(monthly))
    surface = infographic_response_to_envelope(InfographicResponse.model_validate({"blocks": blocks}))
    root = surface.model_dump(by_alias=True, exclude_none=True)["components"][0]
    wt._assert_display_hints(root)
    # FILL IN: confirm model_dump(by_alias=True) yields the same root shape step5_wire sees (camelCase seriesAxes/yAxisLabels); adjust the dump call, not the assertion helper
```

### FILL IN checklist
- [ ] `_assert_display_hints`: the four checks plus the success line;
      bounded by spec M8.
- [ ] Step-4 docstring: an accurate parity sentence.
- [ ] README note: keep it short and link the spec.
- [ ] The test's dump call matches the wire shape.

---

## Acceptance Criteria

- [ ] `python examples/agents/a2ui/a2ui_dashboard_walkthrough.py` runs
      green end to end, and step 5 prints `display hints : ok`.
- [ ] The generated `artifacts/a2ui_dashboard/02_envelope_v1.json` carries
      the progress group, the percent KPIs, `seriesAxes`/`yAxisLabels`, and
      the column `type`/`format`.
- [ ] `01_infographic_template.html` shows the table and hero strings
      formatted by the HTML lane (TASK-3997).
- [ ] The step-4 docstring and the README no longer claim unqualified parity.

## Validation Commands
- `pytest packages/ai-parrot/tests/examples/test_a2ui_dashboard_walkthrough.py -q`

---

## Agent Instructions

1. Work in the FEAT-623 feature worktree. TASK-3994, TASK-3995 and
   TASK-3997 must be `done`.
2. Re-run every `grep -c` above. Line numbers are as of `344549403`.
3. Implement from the blueprint, complete the `FILL IN`s, run the
   Validation Command, and run the walkthrough once.
4. Commit only the listed files (`artifacts/` is git-ignored output, so do
   not commit it), then run
   `scripts/sdd/close_task.sh TASK-4002 infographic-a2ui-display-hints verified`.

---

## Completion Note


