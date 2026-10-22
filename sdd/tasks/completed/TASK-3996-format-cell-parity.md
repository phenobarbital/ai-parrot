# TASK-3996: Align `format_cell` with `formatA2UIValue` + shared parity fixtures

**Feature**: FEAT-623 — Infographic → A2UI display hints
**Spec**: `sdd/specs/infographic-a2ui-display-hints.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (G3). The Python display formatter `format_cell` is used by
`ssr_html`, `interactive_html` and the PDF lane, and it disagrees with the admin
UI's `formatA2UIValue`, which the spec makes the reference:

- currency has no `$`;
- percent always prints 1 decimal (`100.0%`);
- `format == "number"` has no branch of its own and falls through to 2 decimals.

`formatA2UIValue` also formats with the browser locale (`undefined`). §8 Q2
(answered: yes) pins it to `'en-US'`, so every lane writes the same string in
every browser. One JSON fixture file pins both sides. It follows the FEAT-598
linked-contract pattern: JSON in `ai-parrot`, read by vitest, with vitest run
from pytest.

---

## Scope

- In `format_cell` (`_table_format.py`), for a numeric `col_type`:
  - **percent**: ratio × 100, at most 1 decimal, no trailing `.0`, grouped.
  - **currency**: sign, then `$`, then the grouped absolute value with 2
    decimals (`-$1,234.50`).
  - **number** (new explicit branch): grouped, at most 1 decimal, no
    trailing `.0`.
  - Leave the untyped / no-format fallback (`:79-81`) **unchanged**.
- In `a2ui-format.ts`, replace `undefined` with `'en-US'` in both
  `Intl.NumberFormat` constructors (`:16`, `:17`). Change nothing else.
- Create the shared fixture file `display_format.json` (a list of
  `{value, format, unit?, expected}`), seeded with the spec's M3 table plus
  the `unit` cases.
- Create a pytest parity test over the fixture. It composes `format_cell(...)`
  with the unit rule (append `" " + unit` unless `format == "percent"`),
  because the Python renderers render the unit separately.
- Create a vitest parity test over the same JSON. It includes one case run
  with a non-English default locale, to prove the `'en-US'` pin. Create the
  pytest wrapper that runs it via `run_vitest`.
- Update the existing tests whose expected strings change:
  - `a2ui-format.test.ts` builds its expectations with
    `new Intl.NumberFormat(undefined, …)`; switch them to `'en-US'`.
  - Re-run `test_rich_datatable.py` and `test_semantic_classes.py` and fix
    any expectation that relied on the old strings.

**NOT in scope**:
- Model fields (TASK-3994).
- The infographic HTML lane calling `format_cell` (TASK-3997).
- Any compact notation.
- The admin UI chart (TASK-3998/3999).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py` | MODIFY | percent/currency/number branches aligned to TS |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.ts` | MODIFY | pin `'en-US'` on both formatters |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.test.ts` | MODIFY | expectations built with `'en-US'` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/format_contract/fixtures/display_format.json` | CREATE | shared fixtures |
| `packages/ai-parrot-visualizations/tests/outputs/test_format_cell_parity.py` | CREATE | pytest side |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.parity.test.ts` | CREATE | vitest side |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_format_parity.py` | CREATE | pytest wrapper running the vitest file |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_rich_datatable.py` | MODIFY | only if an expectation breaks (fragments `"1,234"` / `"%"` still match) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui_renderers._table_format import format_cell, format_cell_html, is_numeric_column, NUMERIC_TYPES  # verified: packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py:25,28,41,84
from ._vitest import run_vitest  # verified: packages/ai-parrot-server/tests/ui/_vitest.py:14 (used by test_vitest_a2ui_linked_dsl.py:3)
```
```ts
import { formatA2UIValue } from './a2ui-format';            // verified: a2ui-format.test.ts:2
import { readFileSync } from 'node:fs';                     // precedent: linked/dsl.test.ts:2
import { resolve } from 'node:path';                        // precedent: linked/dsl.test.ts:3
import { describe, expect, it } from 'vitest';              // precedent: linked/dsl.test.ts:4
```

### Existing Signatures to Use
```python
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py
NUMERIC_TYPES: frozenset[str] = frozenset({"integer", "number", "duration"})   # :25
def is_numeric_column(col_type: str | None) -> bool:                           # :28
def format_cell(value: Any, *, col_type: str | None, col_format: str | None = None) -> str:  # :41
    # :66-67 None -> "—"; :68-69 non-numeric type -> str(value); :70-73 float() coercion, failure -> str(value)
    # :75-76 percent -> f"{number * 100:,.1f}%"
    # :77-78 currency -> f"{number:,.2f}"
    # :79-81 fallback: integer -> f"{int(number):,}", else f"{number:,.2f}"   (UNCHANGED)
def format_cell_html(value: Any, *, col_type: str | None, col_format: str | None = None) -> str:  # :84
# _semantics.py:135 kpi_value_display -> format_cell(raw, col_type="number", col_format=fmt)  (caller; picks up the change)
# _semantics.py:102 kpi_unit_html -> renders parrot_unit in its own <span> (unit is NOT format_cell's job)

# packages/ai-parrot-server/tests/ui/_vitest.py
UI_DIR = Path(__file__).resolve().parents[2] / "ui"     # :11  -> packages/ai-parrot-server/ui
def run_vitest(*files: str) -> None:                     # :14  skips when pnpm / node_modules absent
```
```ts
// packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.ts
const ONE_DECIMAL_FMT = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });                 // :16
const CURRENCY_FMT = new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' });          // :17
export function formatA2UIValue(value: unknown, format?: unknown, unit?: unknown): unknown
// percent: `${ONE_DECIMAL_FMT.format(n * 100)}%`; number: ONE_DECIMAL_FMT; currency: CURRENCY_FMT;
// unit appended after a space unless percent; non-numeric passes through unchanged.
// linked/dsl.test.ts:7 — const DSL_DIR = resolve(process.cwd(), '../../ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl');
//   (vitest cwd = packages/ai-parrot-server/ui, so '../../ai-parrot/...' = packages/ai-parrot/...)
```

### Does NOT Exist
- ~~`outputs/a2ui/format_contract/`~~: new directory, created by this task.
- ~~An explicit `col_format == "number"` branch in `format_cell`~~: added here.
- ~~`unit` handling inside `format_cell`~~: units are rendered by the callers.
  The parity test composes the unit; do NOT add a `unit` parameter to
  `format_cell`, because the spec fixes its signature as unchanged.
- ~~A `compact` format~~: deliberately not added (spec non-goal).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.test.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/format_contract/fixtures/display_format.json", "action": "CREATE"},
    {"path": "packages/ai-parrot-visualizations/tests/outputs/test_format_cell_parity.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.parity.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_a2ui_format_parity.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_rich_datatable.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py#format_cell",
    "sym:packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py#is_numeric_column",
    "sym:packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_semantics.py#kpi_value_display",
    "sym:packages/ai-parrot-server/tests/ui/_vitest.py#run_vitest"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `formatA2UIValue` is the reference. Python changes to match TS, never the reverse.
- `format_cell`'s signature and its untyped fallback stay byte-identical.
- Fixture values must avoid exact rounding ties (e.g. `0.125`, `2.25`).
  Python's `format` rounds half-to-even on the binary value, while
  `Intl.NumberFormat` rounds half-expand, so a tie would make a "parity"
  failure that is really a rounding-mode difference.
- `-0.0` and `NaN` are out of scope for the fixtures.

---

## Implementation Blueprint

### Steps (in order)
1. Write `display_format.json`. *Why*: both suites read one source of truth,
   so drift is impossible to hide.
2. Pin `'en-US'` in `a2ui-format.ts` and update `a2ui-format.test.ts`.
   *Why*: the reference must be locale-independent before Python can match
   it (§8 Q2).
3. Change `format_cell`'s percent/currency branches and add the `number`
   branch. *Why*: these are the three strings the M3 table pins.
4. Write the pytest parity test, the vitest parity test and its pytest
   wrapper. Run them.
5. Run `test_rich_datatable.py` and `test_semantic_classes.py` and fix only
   the expectations that encode the old strings. *Why*: spec §8 Q1
   (answered: yes) accepts the output change for `ssr_html`/PDF.

### `packages/ai-parrot/src/parrot/outputs/a2ui/format_contract/fixtures/display_format.json` (CREATE)
```json
[
  {"value": 0.683, "format": "percent", "expected": "68.3%"},
  {"value": 1.0, "format": "percent", "expected": "100%"},
  {"value": 0.5, "format": "percent", "unit": "pts", "expected": "50%"},
  {"value": 1234.5, "format": "currency", "expected": "$1,234.50"},
  {"value": -1234.5, "format": "currency", "expected": "-$1,234.50"},
  {"value": 1234.56, "format": "number", "expected": "1,234.6"},
  {"value": 1903, "format": "number", "expected": "1,903"},
  {"value": 3, "format": "number", "unit": "visits", "expected": "3 visits"},
  {"value": 12.34, "format": "number", "unit": "visits", "expected": "12.3 visits"},
  {"value": "n/a", "format": "currency", "expected": "n/a"}
]
```
**Why**: these are the rows of spec M3's "Exact strings" table plus `unit`
cases. `expected` is what `formatA2UIValue` returns under `'en-US'`.

### `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'if col_format == "percent":' _table_format.py)
# REPLACE lines :75-78 — from `if col_format == "percent":` through the FIRST
# `return f"{number:,.2f}"` (that return occurs 2× — :78 and :81; touch ONLY :78,
# the one directly under `if col_format == "currency":`, occurrences: 1).
    if col_format == "percent":
        return f"{_max_one_decimal(number * 100)}%"
    if col_format == "currency":
        sign = "-" if number < 0 else ""
        return f"{sign}${abs(number):,.2f}"
    if col_format == "number":
        return _max_one_decimal(number)
# (lines :79-81 — `if number.is_integer():` … `return f"{number:,.2f}"` — stay as they are)


# ADD at module level, above `def format_cell(` (verified: :41, occurrences: 1)
def _max_one_decimal(number: float) -> str:
    """Grouped, at most one fraction digit, no trailing ``.0`` — ``Intl.NumberFormat('en-US', {maximumFractionDigits: 1})``."""
    # FILL IN: round to 1 decimal and drop a trailing ".0" — bounded by the fixture rows `1.0 percent -> 100%`, `1903 number -> 1,903`, `1234.56 number -> 1,234.6`
```
**Why**: this matches `formatA2UIValue`'s three formats exactly. The
fallback stays as it is because TS has no counterpart for an undeclared
format (spec M3: "out of parity scope").

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c "const ONE_DECIMAL_FMT = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });" a2ui-format.ts) — line :16
// occurrences: 1 (verified: grep -c "const CURRENCY_FMT = new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' });" a2ui-format.ts) — line :17
const ONE_DECIMAL_FMT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
const CURRENCY_FMT = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
```
**Why**: spec §8 Q2. Also update the module doc comment so it says the
locale is pinned.

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.test.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c "new Intl.NumberFormat(undefined, opts).format(n);" a2ui-format.test.ts) — line :5
  new Intl.NumberFormat('en-US', opts).format(n);
```

### `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.parity.test.ts` (CREATE)
```ts
// FEAT-623 (TASK-3996): formatA2UIValue matches the shared Python/TS display-format fixtures.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { formatA2UIValue } from './a2ui-format';

type Row = { value: unknown; format: string; unit?: string; expected: unknown };

const FIXTURE = resolve(
  process.cwd(),
  '../../ai-parrot/src/parrot/outputs/a2ui/format_contract/fixtures/display_format.json',
);
const rows: Row[] = JSON.parse(readFileSync(FIXTURE, 'utf-8'));

describe('display-format parity fixtures', () => {
  it.each(rows)('$value / $format / $unit -> $expected', (row) => {
    expect(formatA2UIValue(row.value, row.format, row.unit)).toBe(row.expected);
  });

  it('is independent of the default locale', () => {
    // FILL IN: prove the 'en-US' pin — e.g. stub Intl.NumberFormat's default locale (vi.spyOn / re-import under a 'de-DE' default) and assert 1234.5 currency is still '$1,234.50' — bounded by spec §5 "Lockstep lanes"
  });
});
```

### `packages/ai-parrot-visualizations/tests/outputs/test_format_cell_parity.py` (CREATE)
```python
"""FEAT-623 (TASK-3996): format_cell matches the shared display-format fixtures (formatA2UIValue is the reference)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.outputs.a2ui_renderers._table_format import format_cell

# packages/ai-parrot-visualizations/tests/outputs/<this> -> packages/
_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "ai-parrot/src/parrot/outputs/a2ui/format_contract/fixtures/display_format.json"
)
_ROWS = json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _display(value, fmt, unit):
    """format_cell + the unit rule the Python renderers apply (unit after a space, never on percent)."""
    text = format_cell(value, col_type="number", col_format=fmt)
    # FILL IN: append f" {unit}" when unit and fmt != "percent" and the value was numeric — bounded by formatA2UIValue's unit rule
    return text


@pytest.mark.parametrize("row", _ROWS, ids=lambda r: f"{r['value']}-{r['format']}-{r.get('unit')}")
def test_format_cell_matches_fixture(row) -> None:
    assert _display(row["value"], row["format"], row.get("unit")) == row["expected"]
```

### `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_format_parity.py` (CREATE)
```python
"""FEAT-623 (TASK-3996): run the TS display-format parity suite from pytest."""

from ._vitest import run_vitest


def test_a2ui_format_parity_vitest() -> None:
    """formatA2UIValue passes every shared display-format fixture."""
    run_vitest(
        "src/lib/components/agents/canvas/a2ui/a2ui-format.parity.test.ts",
        "src/lib/components/agents/canvas/a2ui/a2ui-format.test.ts",
    )
```

### FILL IN checklist
- [ ] `_table_format.py::_max_one_decimal`: rounding + dropping `.0`;
      bounded by the fixture rows.
- [ ] `test_format_cell_parity.py::_display`: unit composition; bounded by
      `formatA2UIValue`'s unit rule.
- [ ] `a2ui-format.parity.test.ts`: the locale-independence case; bounded
      by spec §5 "Lockstep lanes".
- [ ] `test_rich_datatable.py` / `test_semantic_classes.py`: update only
      expectations that encode the old strings, and record which ones in
      the Completion Note.

---

## Acceptance Criteria

- [ ] Every fixture row passes in pytest (`format_cell`) and in vitest
      (`formatA2UIValue`).
- [ ] The vitest locale case passes under a non-English default locale.
- [ ] `format_cell(1903.0, col_type="integer")` and other untyped/no-format
      calls return exactly what they did before (fallback unchanged).
- [ ] `test_rich_datatable.py` and `test_semantic_classes.py` are green.
      Any changed expectation is intentional and listed in the Completion
      Note.
- [ ] No `xfail` / `skip` added.

## Validation Commands
- `pytest packages/ai-parrot-visualizations/tests/outputs/test_format_cell_parity.py -q`
- `pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_format_parity.py -q`
- `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_rich_datatable.py -q`
- `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_semantic_classes.py -q`

---

## Agent Instructions

1. Work in the FEAT-623 feature worktree, never on `dev`.
2. Read the spec (§3 Module 3, §5, §7 Known Risks, §8 Q1/Q2).
3. Verify the Codebase Contract lines before editing. Re-run every `grep -c`.
4. Implement from the blueprint, complete every `FILL IN`, and run the
   Validation Commands.
5. Commit only the listed files, then close with
   `scripts/sdd/close_task.sh TASK-3996 infographic-a2ui-display-hints verified`.

---

## Completion Note


