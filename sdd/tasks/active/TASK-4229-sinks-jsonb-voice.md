# TASK-4229: Sink DDL emits JSONB for voice-capable fields; mapper serialises envelopes

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4210
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 12 (runtime half; the migration scripts are TASK-4230). Every
spoken answer is stored as a `VoiceEvidenceEnvelope` dict in
`FormSubmission.data[field_id]` (G6, AC8). Per-form Postgres sink tables
(FEAT-457) map each field to one column. Today a voice field maps to
`TEXT` (`_DEFAULT_DDL_TYPE`, `postgres_table.py:79`) and only `ARRAY` columns
go through the JSONB path (`jsonb_columns`, `:322`; `json.dumps` only for
ARRAY in `mapper.py:208-209`). An envelope dict reaching a TEXT column would
be written as a Python repr or fail.

This task makes **voice-capable** columns JSONB going forward:
- DDL emits `JSONB`;
- `write()` uses the existing `$n::text::jsonb` cast;
- `flatten_submission` JSON-serialises their values, so CSV/GSheet sinks
  receive the envelope as a JSON string, like ARRAY today (spec §7).

Legacy columns are converted by migration 009 (TASK-4230), and both tasks
must apply the same voice-capability rule.

---

## Scope

- Add the pure helper `voice_capable_columns(form) -> frozenset[str]` to
  `services/sinks/mapper.py`. It runs on the same traversal as
  `field_types_for`, so the column set can never drift.
- Add a keyword-only `voice: bool = False` parameter to `_extract_value`.
  When `voice` is True, return `json.dumps(value)` for any non-`None` value
  (envelope dict or plain scalar — a typed answer in a voice column becomes a
  JSON scalar). `None` stays `None` (SQL NULL), never the string `"null"`.
  `flatten_submission` passes `voice=column_name in voice_cols`.
- Change `_ddl_type_for(field_type, *, voice: bool = False)`: `voice=True` →
  `"JSONB"`. The compatible set for a voice column is `{"jsonb", "json"}`.
- In `PostgresTableSink`, record `self._voice_columns` in `ensure_target()`
  (next to `_known_field_types`). Use it for the DDL type, for the
  compatibility check, and in `write()`'s `jsonb_columns`.
- Write `test_sinks_voice_jsonb.py`.

**NOT in scope**: migration scripts, `fd_unwrap_voice` and `form_data_scalar`
(TASK-4230); the generic `FormSubmissionStorage` path (its `data` column is
already JSONB, `test_submission_jsonb_shape.py`); `AsyncDBSink` / BigQuery
typing; reading envelopes back (`unwrap_voice` is TASK-4210's helper);
`nest_submission` (document mode keeps `data` nested and untouched).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/postgres_table.py` | MODIFY | JSONB DDL + compatibility + `jsonb_columns` for voice columns |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py` | MODIFY | `voice_capable_columns()`; `_extract_value(..., voice=)`; `flatten_submission` wiring |
| `packages/parrot-formdesigner/tests/formdesigner/test_sinks_voice_jsonb.py` | CREATE | DDL / insert / flatten tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# services/sinks/mapper.py (existing, :22-36)
import json
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSubsection, SectionItem
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.submissions import FormSubmission
# services/sinks/postgres_table.py (existing, :17-37)
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.sinks.mapper import column_names_for, field_types_for   # :36 — extend with voice_capable_columns
# tests
from parrot_formdesigner.services.sinks.mapper import flatten_submission                  # mapper.py:142
from parrot_formdesigner.services.sinks.postgres_table import PostgresTableSink           # postgres_table.py:93
from parrot_formdesigner.core.persistence import PostgresTableTarget                      # imported at postgres_table.py:23
```

#### Provided by dependency tasks
```python
from parrot_formdesigner.core.voice_answer import is_voice_envelope   # TASK-4210 — only if the FILL IN below needs it (e.g. logging)
# TASK-4209 (transitively via TASK-4210): FormSchema.voice: VoiceFormConfig | None ; VoiceFormConfig.enabled: bool = True
```

### Existing Signatures to Use
```python
# services/sinks/postgres_table.py
_FIELD_TYPE_PG: dict[FieldType, tuple[str, frozenset[str]]]           # :65 ; ARRAY → ("JSONB", {"jsonb", "json"}) :77
_DEFAULT_DDL_TYPE = "TEXT"                                            # :79
_DEFAULT_COMPATIBLE_TYPES = frozenset({"text", "character varying", "varchar"})   # :80
def _ddl_type_for(field_type: FieldType) -> str                       # :83
def _compatible_types_for(field_type: FieldType) -> frozenset[str]    # :88
class PostgresTableSink(AbstractSubmissionSink):                      # :93 ; self._known_field_types: dict[str, FieldType] = {} :128
    async def ensure_target(self, form: FormSchema) -> None           # :248 ; self._known_field_types = field_types :260 ;
                                                                      #   compatible = (...) :278-280 ; ddl_type = _ddl_type_for(...) :289
    async def write(self, submission, payload) -> str                 # :300 ; jsonb_columns = {"context", "extra_data"} | {...ARRAY} :322-324 ;
                                                                      #   non-str values json.dumps'd :330-331 ; _insert_sql(columns, jsonb_columns=...) :338
    def _insert_sql(self, columns=None, *, jsonb_columns=frozenset({"context"})) -> str   # :177 — "$n::text::jsonb" for jsonb columns
# services/sinks/mapper.py
def _iter_form_fields(form: FormSchema) -> Iterator[tuple[str, FormField]]   # :137 (GROUP children flattened as parent__child)
def flatten_submission(form: FormSchema, submission: FormSubmission) -> dict[str, Any]   # :142 ; row[column_name] = _extract_value(...) :166
def _extract_value(data: dict[str, Any], column_name: str, field: FormField) -> Any      # :176 ; ARRAY json.dumps :208-209 (only caller: :166)
def field_types_for(form: FormSchema) -> dict[str, FieldType]                            # :254-270
# core/schema.py:143 — FormField.answer_envelope: Literal["voice"] | None = None
```

### Does NOT Exist
- ~~`voice_capable_columns`~~, ~~`PostgresTableSink._voice_columns`~~, ~~`_ddl_type_for(..., voice=)`~~ — added here.
- ~~A `voice_data JSONB` sidecar column~~ — rejected by the owner (spec Non-Goals).
- ~~`ALTER COLUMN` in the sink~~ — the sink is additive only (`test_no_destructive_sql_anywhere`, `tests/unit/test_postgres_table_sink.py:170`). Type conversion is migration 009 (TASK-4230).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/postgres_table.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_sinks_voice_jsonb.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/postgres_table.py#_ddl_type_for",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/postgres_table.py#_compatible_types_for",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/postgres_table.py#PostgresTableSink",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/postgres_table.py#PostgresTableSink.ensure_target",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/postgres_table.py#PostgresTableSink.write",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py#_extract_value",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py#flatten_submission",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py#field_types_for",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py#_iter_form_fields"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `mapper.py` stays pure: no I/O, no sink or storage imports (module
  docstring `:19`).
- The voice-capability rule must be a **pure function of `FormSchema`**, and
  the exact same rule must be used by migration 009 (TASK-4230). Write it once in the
  docstring of `voice_capable_columns` so TASK-4230 can quote it. If
  TASK-4230 landed first with a different rule, align with it and note this
  in both Completion Notes.
- A pre-existing TEXT column for a now-voice field fails the compatibility
  check (`SinkTargetMismatchError`). That is intended: the sink never alters
  types. The error message must name migration
  `009_voice_envelope_sink_tables.py` so operators know the fix.
- Existing behaviour is unchanged for forms without voice: the same DDL, the
  same `jsonb_columns` and the same row values. The existing sink and mapper
  unit tests must stay green.

---

## Implementation Blueprint

### Steps (in order)
1. Add `voice_capable_columns` and the `voice=` parameter to `mapper.py` — *why*: the sink imports the helper from the mapper (it already imports `column_names_for` / `field_types_for` from there).
2. Thread `voice=` through `_ddl_type_for` / compatibility / `jsonb_columns` in `postgres_table.py`.
3. Write the tests, then run the existing sink and mapper suites.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def field_types_for(form: FormSchema) -> dict\[str, FieldType\]:' mapper.py → 1, line 254)
# AFTER — insert below the end of field_types_for (its `return {name: field.field_type ...}` line, mapper.py:270)
_NON_VOICE_TYPES: frozenset[FieldType] = frozenset({
    FieldType.HIDDEN, FieldType.PASSWORD, FieldType.ARRAY, FieldType.GROUP,
})


def voice_capable_columns(form: FormSchema) -> frozenset[str]:
    """Return the flattened columns that may carry a ``VoiceEvidenceEnvelope`` (FEAT-649).

    Rule (shared with migration 009, TASK-4230): a column is voice-capable when its field has
    ``answer_envelope == "voice"`` (FEAT-488), or when the form enables voice (``form.voice`` set and
    ``form.voice.enabled``) and the field type is not in ``_NON_VOICE_TYPES``.

    Args:
        form: The form whose tabular columns to classify.

    Returns:
        The set of column names whose values are JSON-serialised and stored as JSONB.
    """
    voice_on = bool(getattr(form, "voice", None) and form.voice.enabled)
    # FILL IN: confirm the excluded-type set against what the audio renderer can narrate (FILE/IMAGE_DROPZONE/SIGNATURE
    #          are visual-fallback, still voice-answerable via answer_payload? → keep them TEXT unless envelopes can reach
    #          them) — bounded by AC8 ("every spoken answer, any field type") and the same rule in TASK-4230.
    return frozenset(
        name for name, field in _iter_form_fields(form)
        if field.answer_envelope == "voice" or (voice_on and field.field_type not in _NON_VOICE_TYPES)
    )
```
```python
# occurrences: 1 (verified: grep -c '        row\[column_name\] = _extract_value(data, column_name, field)' mapper.py → 1, line 166)
# REPLACE the loop at mapper.py:165-166 with:
    voice_cols = voice_capable_columns(form)
    for column_name, field in _iter_form_fields(form):
        row[column_name] = _extract_value(data, column_name, field, voice=column_name in voice_cols)
```
```python
# occurrences: 1 (verified: grep -c 'def _extract_value(data: dict\[str, Any\], column_name: str, field: FormField) -> Any:' mapper.py → 1, line 176)
# REPLACE the signature line (mapper.py:176) with:
def _extract_value(data: dict[str, Any], column_name: str, field: FormField, *, voice: bool = False) -> Any:
# occurrences: 1 (verified: grep -c '    if field.field_type == FieldType.ARRAY:' mapper.py → 1, line 208)
# BEFORE — insert above `    if field.field_type == FieldType.ARRAY:` (mapper.py:208)
    if voice:
        # FEAT-649: envelopes AND typed scalars in a voice column are stored as JSON (JSONB column, ::text::jsonb cast);
        # None stays SQL NULL — never the string "null".
        return json.dumps(value) if value is not None else None
```
**Why**: a typed answer in a voice column must still be valid JSON for the
`::text::jsonb` cast, so scalars are serialised too. Readers unwrap with
`fd_unwrap_voice` / `unwrap_voice`. Document the new `voice` argument in the
`_extract_value` docstring (Args section).

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/postgres_table.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot_formdesigner.services.sinks.mapper import column_names_for, field_types_for' postgres_table.py)
# REPLACE (postgres_table.py:36) with:
from parrot_formdesigner.services.sinks.mapper import column_names_for, field_types_for, voice_capable_columns

# occurrences: 1 (verified: grep -c 'def _ddl_type_for(field_type: FieldType) -> str:' postgres_table.py → line 83)
# REPLACE _ddl_type_for / _compatible_types_for (postgres_table.py:83-90) with:
_VOICE_DDL_TYPE = "JSONB"
_VOICE_COMPATIBLE_TYPES = frozenset({"jsonb", "json"})


def _ddl_type_for(field_type: FieldType, *, voice: bool = False) -> str:
    """Return the ``ADD COLUMN`` SQL type fragment for ``field_type`` (``JSONB`` for voice-capable columns)."""
    if voice:
        return _VOICE_DDL_TYPE
    return _FIELD_TYPE_PG.get(field_type, (_DEFAULT_DDL_TYPE, _DEFAULT_COMPATIBLE_TYPES))[0]


def _compatible_types_for(field_type: FieldType, *, voice: bool = False) -> frozenset[str]:
    """Return the set of compatible ``information_schema`` data types."""
    if voice:
        return _VOICE_COMPATIBLE_TYPES
    return _FIELD_TYPE_PG.get(field_type, (_DEFAULT_DDL_TYPE, _DEFAULT_COMPATIBLE_TYPES))[1]

# occurrences: 1 (verified: grep -c '        self._known_field_types: dict\[str, FieldType\] = {}' postgres_table.py → line 128)
# AFTER — insert below it:
        self._voice_columns: frozenset[str] = frozenset()

# occurrences: 1 (verified: grep -c '        self._known_field_types = field_types' postgres_table.py → line 260)
# AFTER — insert below it:
        self._voice_columns = voice_capable_columns(form)

# ensure_target loop (postgres_table.py:277-289): pass voice=column in self._voice_columns to BOTH
#   _compatible_types_for(...) (:281, occurrences 1) and _ddl_type_for(...) (:289, occurrences 1);
# FILL IN: SinkTargetMismatchError message for a voice column names "009_voice_envelope_sink_tables.py" — bounded by §7 migration risk.

# occurrences: 1 (verified: grep -c '        jsonb_columns = {"context", "extra_data"} | {' postgres_table.py → line 322)
# REPLACE the set expression (postgres_table.py:322-324) with:
        jsonb_columns = (
            {"context", "extra_data"}
            | {column for column, field_type in self._known_field_types.items() if field_type == FieldType.ARRAY}
            | set(self._voice_columns)
        )
```
**Why**: voice columns reuse the FEAT-458 `::text::jsonb` hazard handling
unchanged. `flatten_submission` already returns a JSON `str` for them, so
the `not isinstance(value, str)` guard (`:330`) leaves those values alone.

### `packages/parrot-formdesigner/tests/formdesigner/test_sinks_voice_jsonb.py` (CREATE)
```python
"""FEAT-649 TASK-4229 — voice-capable sink columns are JSONB; envelopes serialised."""
from __future__ import annotations

import json

import pytest

from parrot_formdesigner.services.sinks.mapper import flatten_submission, voice_capable_columns
from parrot_formdesigner.services.sinks.postgres_table import PostgresTableSink, _ddl_type_for


def test_ddl_type_for_voice_is_jsonb() -> None:
    from parrot_formdesigner.core.types import FieldType

    assert _ddl_type_for(FieldType.TEXT, voice=True) == "JSONB"
    assert _ddl_type_for(FieldType.TEXT) == "TEXT"
```
Reuse the `_FakePool` / `_FakeConn` pattern from
`tests/unit/test_postgres_table_sink.py:23-95` (copy it locally; do not import
private test helpers across files).

### FILL IN checklist
- [ ] `voice_capable_columns` — final excluded-type set; bounded by AC8 and the shared rule with TASK-4230
- [ ] `ensure_target` — `voice=` passed to both helpers; mismatch message names migration 009; bounded by spec §7
- [ ] tests — DDL JSONB, `jsonb_columns` contains voice columns, envelope `json.dumps`, `None` → NULL, non-voice form unchanged

---

## Acceptance Criteria

- [ ] `test_sink_ddl_jsonb_for_voice_fields`: DDL emits JSONB for voice-capable fields; `jsonb_columns` includes them; `_extract_value` serialises envelopes (spec §4, AC18 "sink DDL emits JSONB … going forward").
- [ ] `test_generic_storage_and_sink_envelope_paths` (sink half): an envelope written to a per-form JSONB column round-trips as JSON (S10).
- [ ] A form without voice produces byte-identical DDL, `jsonb_columns` and rows to today.
- [ ] `tests/unit/test_postgres_table_sink.py` and `tests/unit/test_submission_mapper.py` still pass.
- [ ] `ruff check` passes on both modified source files.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_sinks_voice_jsonb.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_postgres_table_sink.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_submission_mapper.py -q`

---

## Test Specification

```python
class TestVoiceJsonbSink:
    def test_ddl_type_for_voice_is_jsonb(self): ...
    def test_voice_capable_columns_answer_envelope_and_form_voice(self): ...
    def test_flatten_serialises_envelope_and_scalar_in_voice_column(self): ...
    def test_flatten_none_stays_null(self): ...
    async def test_ensure_target_adds_jsonb_column_for_voice_field(self, fake_pool): ...
    async def test_ensure_target_text_column_for_voice_field_mismatch_names_migration(self, fake_pool): ...
    async def test_write_uses_text_jsonb_cast_for_voice_column(self, fake_pool): ...
    def test_non_voice_form_unchanged(self): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** (§3 M12, §5 AC8/AC18, §7 migration risks)
3. **Check dependencies** — TASK-4210 `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`; confirm `FormSchema.voice` exists (TASK-4209)
4. **Verify the Codebase Contract** — re-run every `grep -c` above
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** — blueprint blocks first, then every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`
8. **Commit the code** — only the three files listed
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4229 audio-form-interaction-workflow verified`
10. **Fill in the Completion Note** (quote the final voice-capability rule for TASK-4230), then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
