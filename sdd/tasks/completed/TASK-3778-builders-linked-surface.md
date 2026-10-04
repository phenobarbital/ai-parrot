# TASK-3778: build_surface(surface_metadata) + build_linked_surface

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3769, TASK-3777
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. The builder is the pure, deterministic seam between "a tool fetched some frames"
and "a TOOL-origin `CreateSurface` carrying `metadata.extensions.parrot_data_sources`". The agent tool
`qs_build_linked_surface` (TASK-3785) runs the slug once (G6), then calls this builder. Today
`build_surface` can only set root-COMPONENT metadata (builders.py:101-104); linked surfaces need
SURFACE metadata, so `build_surface` gains `surface_metadata`. `build_linked_surface` validates axis
props against the fetched frames' real columns/dtypes, embeds an optional ≤ 500-row snapshot, and
always leaves every binding resolvable (`{"rows": []}` when no snapshot — S9). It then calls
`validate_envelope(origin=TOOL)`, whose surface pass (TASK-3777) checks the descriptor.

---

## Scope

- Add keyword-only `surface_metadata: SurfaceMetadata | None = None` to `build_surface`; when given,
  set it as `CreateSurface.metadata` (root component metadata behaviour unchanged).
- Add `build_linked_surface(components, sources, frames, *, surface_id, snapshot=True,
  max_snapshot_rows=500, catalog_id=DEFAULT_CATALOG_ID) -> CreateSurface` and export it in `__all__`.
- Axis validation rules (spec §7, adjusted to the real DataTable schema — see Does NOT Exist).
- Snapshot rules: `snapshot=True` → `dataModel[key] = {"rows": head(max_snapshot_rows) records}`,
  `snapshot_truncated = len(frame) > max_snapshot_rows`, `snapshot_at` stamped; `snapshot=False` →
  `dataModel[key] = {"rows": []}`, `snapshot_at=None`, `snapshot_truncated=False`.
- Two envelope fixtures in `linked/contract/fixtures/envelopes/`: `linked_chart.json` (golden,
  byte-equal) and `linked_no_snapshot.json`.
- Tests: `test_build_linked_surface.py`.

**NOT in scope**: executing the slug (TASK-3780 / TASK-3785); `derive_conditions` (the caller passes
descriptors whose `conditions` are already derived — tests build them with TASK-3770's function);
dashboard/multiquery envelope fixtures (TASK-3790); conformance registration (TASK-3790).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` | MODIFY | `surface_metadata` param; `build_linked_surface`; `__all__` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_chart.json` | CREATE | golden linked Chart envelope (snapshot, 3 rows) |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_no_snapshot.json` | CREATE | same surface, `snapshot=False` |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_build_linked_surface.py` | CREATE | M4 tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID, ProducerOrigin, validate_envelope  # builders.py:28-32 (already imported)
from parrot.outputs.a2ui.models import Action, Component, ComponentMetadata, CreateSurface       # builders.py:46 (already imported)
from parrot.outputs.a2ui.models import SurfaceMetadata, Extensions                             # models.py:378, 341 — ADD to the builders import
from parrot.outputs.a2ui.baking import bake_envelope                                           # baking.py:356 (tests only)
from parrot.outputs.a2ui.linked.models import LinkedDataSource                                  # TASK-3769 (net-new)
from parrot.outputs.a2ui.linked.conditions import derive_conditions                            # TASK-3770 (tests only)
import pandas as pd                                                                           # tests + lazy inside the builder (dtype checks)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
__all__ = [ ..., "build_surface", ]                                   # L48-58 ("build_surface" is the last entry, L57)
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str,
                  component_id: str = _ROOT_COMPONENT_ID, data_model: dict[str, Any] | None = None,
                  origin: ProducerOrigin = ProducerOrigin.LLM,
                  metadata: ComponentMetadata | None = None) -> CreateSurface:   # L69-78
    envelope = CreateSurface(surfaceId=surface_id, catalogId=DEFAULT_CATALOG_ID,
                             components=[Component(**component_kwargs, **remaining_properties)],
                             dataModel=data_model or {})                          # L106-111
    validate_envelope(envelope, origin=origin)                                    # L112
def build_html_document(...)   # L264 — TOOL-origin precedent: origin=ProducerOrigin.TOOL at L311
# Module docstring L1-15: "Pure functions: same input → byte-identical envelope. No clocks …" and the
# one-way import rule (a2ui core only — never DatasetManager/agents).

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class CreateSurface: surface_id (surfaceId), catalog_id (catalogId), components, data_model (dataModel),
                     metadata: SurfaceMetadata | None = None                     # L446-470, extra="forbid"
# Wire prop names (catalog/parrot/): Chart requires ("type","x","y"), binding field "data" (chart.py:28-29);
# DataTable requires "columns", each column dict has "name" (+ optional type/title/format), binding "data"
# (datatable.py:27-31, 44-47, 61-66); KPICard "value" = number|string|binding (kpicard.py:19).
```

### Does NOT Exist
- ~~`build_linked_surface`, `build_surface(surface_metadata=…)`~~ — net-new (this task).
- ~~`DataTable.columns[*].key`~~ — spec §7 says `key`, but the real DataTable column field is **`name`**
  (datatable.py:44-47, 61-66). Validate `columns[*].name`. (Report as a spec correction in the
  Completion Note.)
- ~~Any builder setting `CreateSurface.metadata` today~~ — only root-component metadata (L101-104).
- ~~Module-level `import pandas` in builders.py~~ — keep it lazy/`TYPE_CHECKING` (builders are imported by
  every emitter; pandas must stay off that path).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/builders.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_chart.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_no_snapshot.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_build_linked_surface.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/builders.py#build_surface",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py#validate_envelope",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/models.py#CreateSurface",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/baking.py#bake_envelope"
  ]
}
```

---

## Implementation Notes

### Axis validation (spec §7, with the DataTable correction)
- `Chart.x` must name a column (datetime allowed for `x` only); each `Chart.y[*]` a numeric column
  (int/float/bool → numeric) — `y` may be a str or a list of str; `DataTable.columns[*].name` must name a
  column; `KPICard.value` bound to `/<key>/rows/0/<col>` must name a column. Violations raise
  `ValueError("<prop> '<column>' not in source '<key>' columns [...]")` (numeric violations:
  `"<prop> '<column>' in source '<key>' is not numeric (dtype …)"`).
- Only components whose binding (`data` or KPICard `value`) points into `/<key>/rows` of a key in
  `sources` are checked; a key referenced by a component but missing from `frames` → `ValueError`.

### Clock decision (module says "no clocks")
Stamp `snapshot_at` as: keep `source.snapshot_at` when the caller already set it (the executor's
`SourceOutcome.snapshot_at`, TASK-3780, is the authoritative fetch time — TASK-3785 passes it through); only when
it is `None` and `snapshot=True`, fall back to `datetime.now(timezone.utc)`. The golden test passes a
fixed `snapshot_at`, so the envelope stays byte-deterministic. Amend the module docstring: "no clocks,
except the `snapshot_at` fallback of `build_linked_surface`".

### Records serialisation
Rows must serialise exactly like the DSL contract (`orient="records"`, ISO-8601 dates, `NaN` → `null`,
ints stay ints — spec §7). Use `json.loads(frame.to_json(orient="records", date_format="iso"))` — do
NOT import `linked.dsl` here (keeps TASK-3773 off this task's dependency path; both must agree, and
TASK-3790's conformance fixtures will catch drift).

### Key Constraints
- `origin=ProducerOrigin.TOOL` always (G5); `validate_envelope` is called last (L112 idiom).
- Never mutate the caller's `sources`: build updated copies with `model_copy(update=…)`.
- `extensions["parrot_data_sources"]` = `{key: src.model_dump(mode="json", exclude_none=False)}` — keep
  `None` fields so the golden shows the full descriptor; FILL IN if TASK-3769's schema test expects
  `exclude_none=True` (align with it).

---

## Implementation Blueprint

### Steps (in order)
1. Add `surface_metadata` to `build_surface` (block 1) — *why*: linked surfaces need surface metadata and
   every other builder keeps working unchanged (default `None`).
2. Add `SurfaceMetadata, Extensions` to the models import and `"build_linked_surface"` to `__all__` — *why*: public API (spec §2 New Public Interfaces).
3. Append `build_linked_surface` + two private helpers at the end of builders.py (block 2) — *why*:
   keeps the existing builders untouched.
4. Build the fixtures by calling the builder in a scratch session with the test's exact inputs, review
   them by eye against spec §2, then commit — *why*: this golden pins OUR builder's byte output (unlike
   the DSL fixtures, it is not a cross-language contract).
5. Write the tests.

### `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` (MODIFY) — block 1: `build_surface`
```python
# occurrences: 3 (verified: grep -c '    metadata: ComponentMetadata | None = None,' builders.py) → disambiguate:
# anchor inside build_surface's signature (L77), preceded by:
#     data_model: dict[str, Any] | None = None,
#     origin: ProducerOrigin = ProducerOrigin.LLM,
#     metadata: ComponentMetadata | None = None,      <- insert the new parameter AFTER this line
    surface_metadata: SurfaceMetadata | None = None,

# occurrences: 1 (verified: grep -c '        dataModel=data_model or {},' builders.py) — L110; REPLACE the
# CreateSurface(...) call's closing lines so metadata is passed:
        dataModel=data_model or {},
        metadata=surface_metadata,
    )
```
Add to the docstring `Args:`: `surface_metadata: Optional SURFACE-level metadata (FEAT-598) set on
CreateSurface.metadata; independent of the root component's metadata.`
**Why**: `CreateSurface.metadata` defaults to `None`, so passing `None` is byte-identical to today (AC11).

### `…/builders.py` (MODIFY) — block 2: append at end of file
```python
# occurrences: 1 (verified: grep -c '    "build_surface",' builders.py) — add `"build_linked_surface",` to __all__ (alphabetical, before "build_map").

_LINKED_SOURCES_KEY = "parrot_data_sources"


def _rows_key(binding: Any, sources: Mapping[str, Any]) -> tuple[str, str | None] | None:
    """Return ``(source_key, column_or_None)`` for a ``{"path": "/<key>/rows[/0/<col>]"}`` binding into a source."""
    # FILL IN: parse the pointer; "/k/rows" → (k, None); "/k/rows/0/col" → (k, "col"); anything else or
    #   k not in sources → None.
    raise NotImplementedError


def _validate_axes(component: dict[str, Any], sources: Mapping[str, Any], frames: Mapping[str, Any]) -> None:
    """Check x / y / columns[*].name / KPICard value against the bound frame (spec §7 Axis validation)."""
    # FILL IN: implement the §7 rules above using pandas.api.types (is_numeric_dtype, is_bool_dtype,
    #   is_datetime64_any_dtype); raise ValueError with the exact message format; bounded by
    #   test_build_linked_surface_axis_validation.
    raise NotImplementedError


def build_linked_surface(
    components: Sequence[dict[str, Any]],
    sources: Mapping[str, "LinkedDataSource"],
    frames: Mapping[str, "pd.DataFrame"],
    *,
    surface_id: str,
    snapshot: bool = True,
    max_snapshot_rows: int = 500,
    catalog_id: str = DEFAULT_CATALOG_ID,
) -> CreateSurface:
    """Build a TOOL-origin linked ``CreateSurface`` (FEAT-598 M4).

    ``metadata.extensions['parrot_data_sources'] = sources``. Axis props are validated against the
    fetched frames. ``snapshot=True`` embeds ≤ ``max_snapshot_rows`` records per source (setting
    ``snapshot_truncated``/``snapshot_at``); ``snapshot=False`` writes ``{"rows": []}`` so every binding
    still resolves and renderers show a loading state (S9).

    Raises:
        ValueError: An axis prop names a missing / non-numeric column, or a bound key has no frame.
        CatalogValidationError: The envelope fails ``validate_envelope(origin=TOOL)``.
    """
    for comp in components:
        _validate_axes(comp, sources, frames)
    data_model: dict[str, Any] = {}
    stamped: dict[str, Any] = {}
    for key, src in sources.items():
        # FILL IN: per the Scope snapshot rules + "Clock decision": rows via
        #   json.loads(frame.head(max_snapshot_rows).to_json(orient="records", date_format="iso"));
        #   stamped[key] = src.model_copy(update={"snapshot_at": …, "snapshot_truncated": …}).
        raise NotImplementedError
    metadata = SurfaceMetadata(extensions=Extensions({
        _LINKED_SOURCES_KEY: {k: s.model_dump(mode="json") for k, s in stamped.items()}
    }))
    envelope = CreateSurface(
        surfaceId=surface_id,
        catalogId=catalog_id,
        components=[Component(**c) for c in components],
        dataModel=data_model,
        metadata=metadata,
    )
    validate_envelope(envelope, origin=ProducerOrigin.TOOL)
    return envelope
```
Imports to add at the top: `import json`, `from collections.abc import Mapping, Sequence` (Sequence is
already imported — add Mapping), `from datetime import datetime, timezone`, `from typing import TYPE_CHECKING`
and under `if TYPE_CHECKING:` `import pandas as pd` + `from parrot.outputs.a2ui.linked.models import LinkedDataSource`.
**Why**: `LinkedDataSource` stays a type-only import so builders.py does not import `linked` eagerly
(one-way rule is satisfied either way — linked imports only models — but keeping it lazy mirrors the
catalog). Validation runs last so the surface pass (TASK-3777) sees the final descriptor.

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_build_linked_surface.py` (CREATE)
```python
"""build_linked_surface / build_surface(surface_metadata) (FEAT-598 M4)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import parrot.outputs.a2ui.linked
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.builders import build_linked_surface, build_surface

ENVELOPES = Path(parrot.outputs.a2ui.linked.__file__).parent / "contract" / "fixtures" / "envelopes"
FIXED_AT = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _dump(envelope) -> bytes:
    return json.dumps(envelope.model_dump(mode="json", by_alias=True, exclude_none=True), sort_keys=True, indent=2).encode() + b"\n"


def test_build_surface_surface_metadata() -> None: ...            # FILL IN: lands on .metadata; root comp metadata unchanged
def test_build_surface_without_surface_metadata_unchanged() -> None: ...  # FILL IN: .metadata is None (AC11)
def test_build_linked_surface_axis_validation(activity_frame, linked_source) -> None: ...  # FILL IN: unknown x, non-numeric y
def test_build_linked_surface_snapshot_cap(linked_source) -> None: ...   # FILL IN: 501 rows → 500 + snapshot_truncated
def test_build_linked_surface_no_snapshot_bakes(activity_frame, linked_source) -> None: ...  # FILL IN: {"rows": []}, bake ok, snapshot_at None (S9)
def test_build_linked_surface_origin_tool(activity_frame, linked_source) -> None: ...  # FILL IN: validates under TOOL
def test_build_linked_surface_golden(activity_frame, linked_source) -> None: ...  # FILL IN: snapshot_at=FIXED_AT; == linked_chart.json bytes
def test_build_linked_surface_no_snapshot_golden(activity_frame, linked_source) -> None: ...  # FILL IN: == linked_no_snapshot.json
```
Golden convention: `json.dumps(model_dump(mode="json", …), sort_keys=True, indent=2)` byte-equal
(tests/outputs/a2ui/test_components_filterbar.py:15-16). Use `activity_frame.head(3)` for the golden
so the file stays small.

### FILL IN checklist
- [ ] `_rows_key` — pointer parsing
- [ ] `_validate_axes` — §7 rules with `name` for DataTable; message format
- [ ] snapshot loop — cap, truncation, clock decision
- [ ] `exclude_none` alignment with TASK-3769 / TASK-3771
- [ ] two envelope fixtures (generated, reviewed)
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `build_surface(surface_metadata=…)` sets `CreateSurface.metadata`; default path byte-identical (AC11)
- [ ] `build_linked_surface` emits `origin=TOOL`, validates axes vs frames, caps at 500 rows with `snapshot_truncated` (AC3)
- [ ] `snapshot=False` → `{"rows": []}` per key, `snapshot_at=None`, `bake_envelope` succeeds (AC16)
- [ ] Golden `linked_chart.json` byte-equal
- [ ] Existing builder tests green: `pytest packages/ai-parrot/tests/outputs/a2ui/test_builders.py -q`
- [ ] `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_build_linked_surface.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_builders.py -q`

---

## Test Specification

See the test block; rows map to spec §4 `test_build_surface_surface_metadata`,
`test_build_linked_surface_axis_validation`, `test_build_linked_surface_snapshot_cap`,
`test_build_linked_surface_no_snapshot_bakes`, `test_build_linked_surface_golden`.

---

## Agent Instructions

1. Read spec §3 M4 and §7 (axis validation); read TASK-3769's models and TASK-3777's surface pass.
2. Verify TASK-3769 and TASK-3777 are done.
3. Re-run the `grep -c` anchors; implement; fill every `# FILL IN:`.
4. Run the Validation Commands (worktree: `PYTHONPATH=packages/ai-parrot/src`).
5. Commit only the listed files; update the index; fill the Completion Note (record the `key`→`name` correction).

---

## Completion Note


- Task: TASK-3778
- Feature: a2ui-linked-surfaces
- Implementation SHA: 750c69256fb4a3c3150df754fe3a482f0bdc68af
- Closed at (UTC): 2026-09-26T01:27:08+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| coder_record_review | NOT recorded - coder_record_review MCP tool rejects every payload including {} (systemic tool outage, confirmed also on coder_record_feedback and coder_record_native_observation) |
| merge_validation_outcome | failed: same systemic pre-existing failures already characterized (parrot-formdesigner version/schema drift, ai-parrot-embeddings wheel-layout conftest collision), unrelated to this task's diff. See issue:181bd0c01bb4. |
| seat_summary | Seat: gpt-5.6-terra - Backend: codex - Model: gpt-5.6-terra - Attempts: 1 - Duration: 385.9s - Tokens: n/a |
