---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: NetworkNinja Importer — Select Options from `form_metadata`

**Feature ID**: FEAT-325
**Date**: 2026-07-23
**Author**: Claude
**Status**: approved
**Target version**: parrot-formdesigner 0.9.0

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The `NetworkninjaFormService` importer produces `FormSchema` objects with
`options: null` for select-type fields whose choices are stored **only** in
`networkninja.form_metadata.options`. The imported forms are therefore
un-fillable in FieldSync: rating scales (1–10 QUALITY / QUANTITY questions) and
any categorical `FIELD_SELECT` / `FIELD_SELECT_RADIO` / `FIELD_MULTISELECT`
whose options do not also appear inline in the question JSON or inside a
conditional `logic_group` come through empty.

The root cause is a half-wired feature — four broken links, all verified in
`packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/networkninja.py`:

1. `_FORM_QUERY` (lines 28–43) builds the metadata `jsonb_build_object` with
   `column_id, column_name, description, data_type` — it never selects
   `m.options`.
2. `_build_metadata_index` (lines 449–469) stores only
   `column_id / data_type / description` — it never stores `options`.
3. `_collect_select_options` (lines 504–594) reads options only from inline
   question arrays and `logic_groups` conditions — never from
   `form_metadata.options`.
4. Test fixtures already anticipate an `options` key on metadata entries but
   with an inconsistent shape: `test_feat300_integration.py` (lines 106–111)
   uses `option_label`, while the real column uses `option_value`.

The real source shape (staging `navigator_staging`, verified 2026-07-23) is a
`jsonb` array of
`{"is_active": bool, "option_id": str, "column_name": int, "option_value": str}`.
Live option-bearing counts: `FIELD_SELECT` = 111, `FIELD_SELECT_RADIO` = 227,
`FIELD_MULTISELECT` = 243.

### Goals

- Make `form_metadata.options` the canonical option catalog for select-type
  fields, threaded through query → metadata index → option collector.
- Emit `FieldOption(value=option_id, label=option_value)` for metadata options.
- Preserve inactive options (`is_active=false`) as `FieldOption(disabled=True)`.
- Keep conditional logic consistent by re-indexing `EQUALS`
  `condition_comparison_value` (human text) to `option_id` via the metadata
  catalog, so `FieldCondition.value` shares the option value-space.
- Record option provenance (`metadata | inline | logic_groups | none`) on each
  `ImportDiffEntry` for audit.
- Preserve backwards compatibility: inline / logic-group-only forms import
  exactly as before when the metadata catalog is empty.

### Non-Goals (explicitly out of scope)

- Re-importing the 46 FLEXROC forms, per-tenant hydration, and the
  program-aware selector — these are FieldSync work (NAV-9182).
- Runtime dynamic option resolution via `OptionsSource` — rejected in
  brainstorm (Option C, `proposals/networkninja-metadata-select-options.brainstorm.md`)
  because it adds render-time DB coupling and a render-layer dependency for a
  static catalog.
- Synthesizing surrogate ids for logic-group-only selects — rejected; see §7.

---

## 2. Architectural Design

### Overview

Recommended approach: **Option A — metadata-primary options wiring + condition
re-indexing** (from the brainstorm). All changes are contained in a single
service file plus its two test modules. The importer gains
`form_metadata.options` as the primary source of select options, keyed by
`option_id`; inline and logic-group sources remain as fallbacks used only when a
column's metadata catalog is empty. A per-column `option_value → option_id`
catalog derived from the same metadata drives re-indexing of `EQUALS`
conditions so conditional show/hide keeps working under the new value-space.

### Component Diagram

```
fetch() ──→ _FORM_QUERY (+ m.options)
                 │
                 ▼
        _build_metadata_index (stores options[])
                 │
      ┌──────────┴───────────────────────────────┐
      ▼                                            ▼
_collect_select_options                   _build_option_id_catalog
  primary: metadata options                 column_name → {option_value: option_id}
  fallback: inline → logic_groups                        │
      │                                                  ▼
      ▼                                          _map_logic_groups
FieldOption(value=option_id,                      reindex comparison_value → option_id
  label=option_value, disabled=not is_active)             │
      │                                                    ▼
      └────────────→ _map_question_to_field ──→ FormField(options=..., depends_on=...)
                                 │
                                 ▼
                     ImportDiffEntry(options_source=...)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `NetworkninjaFormService` | modifies | query, metadata index, option collector, logic-group mapping, report |
| `FieldOption` (`core/options.py`) | uses | native `value`, `label`, `disabled` fields — no model change |
| `FieldCondition` (`core/constraints.py`) | uses | `value: Any` receives re-indexed `option_id` |
| `DatabaseFormTool` (`tools/database_form.py`) | depends on | consumes the service; no signature change expected |
| FieldSync `form_schemas` (downstream) | depends on | requires re-import to persist populated options (NAV-9182, out of scope) |

### Data Models

```python
# Modified: ImportDiffEntry gains options_source (provenance).
class ImportDiffEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column_name: str
    source_data_type: str
    mapped_field_type: str | None = None
    status: str  # "mapeado" | "aproximado" | "requiere_intervencion"
    note: str = ""
    options_source: str | None = None  # NEW: "metadata" | "inline" | "logic_groups" | "none"
```

`options_source` is `None` for non-option field types and one of the four
literals for option-typed fields.

### New Public Interfaces

No new public classes. The change is internal to `NetworkninjaFormService`; the
`fetch()` / `to_form_schema()` / `import_with_report()` signatures are unchanged.

---

## 3. Module Breakdown

> All paths are under
> `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/networkninja.py`
> unless noted. This is a single tightly-coupled file; modules below map to
> sequential tasks.

### Module 1: Query + metadata index carry `options`
- **Path**: `networkninja.py` (`_FORM_QUERY`, `_build_metadata_index`)
- **Responsibility**: Add `'options', m.options` to the `jsonb_build_object`
  aggregate; store the raw `options` list in each metadata index record.
- **Depends on**: none

### Module 2: Metadata-primary option collection
- **Path**: `networkninja.py` (`_collect_select_options`)
- **Responsibility**: For each option-typed column present in `meta_index`,
  build options from `form_metadata.options` first:
  `FieldOption(value=str(option_id), label=option_value, disabled=not is_active)`,
  deduped by `value`. Fall back to the existing inline then logic-group scan
  only when the column's metadata catalog is empty. Return per-column provenance
  alongside the options so Module 4 can record it.
- **Depends on**: Module 1

### Module 3: Condition re-indexing to `option_id`
- **Path**: `networkninja.py` (new `_build_option_id_catalog` helper +
  `_map_logic_groups`, threaded from `_build_form_schema`)
- **Responsibility**: Build `column_name → {option_value: option_id}` from
  metadata. In `_map_logic_groups`, translate each `condition_comparison_value`
  to its `option_id` before constructing the `FieldCondition`. When the
  referenced column has no metadata catalog, keep the current text comparison.
  When a `comparison_value` is not found in the catalog, keep the original value
  and log at debug (do not drop the condition).
- **Depends on**: Module 1

### Module 4: `ImportDiffEntry.options_source` provenance
- **Path**: `networkninja.py` (`ImportDiffEntry`, `_map_question_to_field`)
- **Responsibility**: Add the `options_source` field; populate it for
  option-typed fields from Module 2's provenance; `None` otherwise.
- **Depends on**: Module 2

### Module 5: Tests
- **Path**:
  `packages/parrot-formdesigner/tests/unit/test_networkninja_importer.py`,
  `packages/parrot-formdesigner/tests/integration/test_feat300_integration.py`
- **Responsibility**: Add fixtures with non-empty `form_metadata.options`
  (real `option_value` shape) and assert options + `disabled` + provenance flow
  through; assert condition re-indexing produces `option_id` values; fix the
  integration fixture's `option_label` → `option_value`; assert the
  inline/logic-group fallback still works with empty metadata options.
- **Depends on**: Modules 1–4

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_metadata_options_populate_select` | 1,2 | `FIELD_SELECT` with `form_metadata.options` yields `FieldOption(value=option_id, label=option_value)` |
| `test_metadata_options_scale_1_10` | 2 | A 1–10 scale select (options only in metadata) yields 10 options |
| `test_inactive_option_marked_disabled` | 2 | `is_active=false` option imported with `disabled=True`, still present |
| `test_metadata_primary_over_inline` | 2 | When both metadata and inline options exist, metadata wins |
| `test_inline_fallback_when_metadata_empty` | 2 | Empty metadata options → inline options used (no regression) |
| `test_logic_group_fallback_when_no_metadata` | 2 | No metadata catalog → logic-group text used as value & label |
| `test_condition_reindexed_to_option_id` | 3 | `EQUALS` on a metadata-backed select → `FieldCondition.value == option_id` |
| `test_condition_unmatched_comparison_value_preserved` | 3 | `comparison_value` absent from catalog → original value kept, no crash |
| `test_options_source_provenance` | 4 | `ImportDiffEntry.options_source` is `metadata`/`inline`/`logic_groups`/`none` as appropriate |
| `test_option_id_cast_to_str` | 2 | Integer `option_id` cast to `str` for `FieldOption.value` |

### Integration Tests
| Test | Description |
|---|---|
| `test_feat300_all_live_types_options` | `option_label` fixture corrected to `option_value`; SELECT/RADIO/MULTISELECT fields carry options |
| `test_end_to_end_metadata_form` | A row modeling a live metadata-backed select imports with populated, id-keyed options and consistent conditions |

### Test Data / Fixtures
```python
# Metadata option shape mirrors the real column (staging-verified):
{"is_active": True, "option_id": "6091", "column_name": 10211, "option_value": "Field Merchandiser"}
# Expected FieldOption: value="6091", label="Field Merchandiser", disabled=False
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `_FORM_QUERY` selects `m.options`; `_build_metadata_index` stores it.
- [ ] Select-type fields backed by `form_metadata.options` import with
      `FieldOption(value=option_id, label=option_value)`.
- [ ] `form_metadata.options` is the primary source; inline and logic-group
      sources are used only when the metadata catalog for a column is empty.
- [ ] Inactive options (`is_active=false`) import as `FieldOption(disabled=True)`
      and are not dropped.
- [ ] `EQUALS` conditions on metadata-backed selects are re-indexed so
      `FieldCondition.value` equals the referenced option's `option_id`.
- [ ] Conditions referencing a column with no metadata catalog keep the current
      text comparison; unmatched `comparison_value` is preserved (no crash).
- [ ] `ImportDiffEntry.options_source` records provenance for option-typed
      fields (`metadata | inline | logic_groups | none`) and is `None` otherwise.
- [ ] The integration fixture uses `option_value` (not `option_label`).
- [ ] Import never aborts; `ImportDiffReport` is still produced.
- [ ] All unit tests pass (`pytest packages/parrot-formdesigner/tests/unit/ -v`).
- [ ] All integration tests pass (`pytest packages/parrot-formdesigner/tests/integration/ -v`).
- [ ] No breaking changes to `fetch` / `to_form_schema` / `import_with_report`
      signatures.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Re-verified against `main`/`dev` on 2026-07-23.

### Verified Imports
```python
# All confirmed in use by the service today:
from ...core.options import FieldOption
from ...core.constraints import ConditionOperator, DependencyRule, FieldCondition
from ...core.schema import FormField, FormSchema, FormSection, FormType
from ...core.types import FieldType
from .abstract import AbstractFormService
# fetch() imports asyncdb lazily:
from asyncdb import AsyncDB  # networkninja.py:228
```

### Existing Class Signatures
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py:13
class FieldOption(BaseModel):
    value: str              # line 25
    label: LocalizedString  # line 26
    description: LocalizedString | None = None  # line 27
    disabled: bool = False  # line 28  ← used for is_active=false
    icon: str | None = None # line 29

# packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py:144
class FieldCondition(BaseModel):
    value: Any = None       # line 158  ← receives re-indexed option_id

# packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/networkninja.py
_FORM_QUERY                    # lines 28–43  (jsonb_build_object 33–36: add 'options', m.options)
_OPTION_FIELD_TYPES            # lines 162–166  {FIELD_SELECT, FIELD_SELECT_RADIO, FIELD_MULTISELECT}
class ImportDiffEntry          # lines 54–74  (add options_source field)
def _build_form_schema         # lines 328–396  (threads select_options + logic mapping)
def _build_metadata_index      # lines 449–469  (add 'options' to stored record)
def _collect_select_options    # lines 504–594  (Source 1 inline 558–577; Source 2 logic 579–586)
def _map_question_to_field     # lines 644–786  (options attach 736–739; report 741–776)
def _map_logic_groups          # lines 792–869  (FieldCondition.value = comparison_value, line 843)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| metadata option branch | `_collect_select_options` collector | dict `col_name → {value: label}` | `networkninja.py:525` |
| `_build_option_id_catalog` (new) | `_map_logic_groups` | passed from `_build_form_schema` | `networkninja.py:364–369, 731` |
| `options_source` | `ImportDiffEntry` | new field | `networkninja.py:54` |

### Does NOT Exist (Anti-Hallucination)
- ~~`m.options` in `_FORM_QUERY`~~ — not selected today; must be added
- ~~`options` key in `_build_metadata_index` records~~ — not stored today
- ~~metadata source in `_collect_select_options`~~ — only inline + logic-groups exist
- ~~`option_label` in the real `form_metadata.options` column~~ — real key is `option_value`
- ~~a `meta` attribute on `FieldOption`~~ — does not exist; use `disabled`
- ~~`_build_option_id_catalog`~~ — does not exist yet; to be created in Module 3

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Cast `option_id` and `column_name` to `str` for lookups — mirrors the
  existing `str(question.get("question_column_name", ""))` pattern
  (`networkninja.py:673`).
- Dedup options by `value` (as the current collector does with a
  `{value: label}` dict) so distinct ids survive duplicate labels.
- Async-first, `self.logger` for all logging; no new external dependencies.
- Keep the import non-aborting; every field still yields an `ImportDiffEntry`.

### Known Risks / Gotchas
- **Fallback value/label for logic-group-only selects (resolved).** When a
  select column has no `form_metadata.options`, no `option_id` exists at the
  source. The importer keeps `FieldOption(value=text, label=text)` from
  `condition_comparison_value`. This is internally consistent (conditions on
  that field also compare by `comparison_value`, so
  `FieldCondition.value == FieldOption.value`), so conditional logic fires. The
  only inconsistency is cross-form (metadata forms use `option_id`, fallback
  forms use text). A saved answer keyed by text will not re-resolve if
  NetworkNinja later edits the wording — an unavoidable limitation of source
  data with no stable id. Synthesizing surrogate ids is rejected: untraceable
  to NetworkNinja and would break the text-based conditions.
- **Re-import required downstream.** Existing `form_schemas` rows in FieldSync
  keep their old (empty) options until re-imported (NAV-9182).
- **Duplicate `option_value` within a column** → dedup by `option_id`, not by
  label, so both survive.
- **Edge cases (from brainstorm):** `options` null/empty → fallback;
  int vs str `option_id` → cast to str; `comparison_value` not in catalog →
  keep original + debug log.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `asyncdb` | (existing) | `pg` driver for `_FORM_QUERY` fetch — already a dependency |

No new dependencies.

---

## 8. Open Questions

> All brainstorm questions were resolved; carried forward here for the audit trail.

- [x] Flow type / base branch — *Resolved in brainstorm*: `feature` on `dev`.
- [x] `FieldOption.value` semantics — *Resolved in brainstorm*: `value = option_id`, `label = option_value`.
- [x] Source precedence — *Resolved in brainstorm*: `form_metadata.options` is primary; inline + logic-groups are fallback when the metadata catalog is empty.
- [x] Condition consistency — *Resolved in brainstorm*: re-index `EQUALS` `condition_comparison_value` to `option_id` via the metadata catalog.
- [x] Inactive options — *Resolved in brainstorm*: import all; `is_active=false` → `FieldOption(disabled=True)`.
- [x] Scope — *Resolved in brainstorm*: importer fix only; re-import + hydration are FieldSync (NAV-9182).
- [x] Fallback value/label for logic-group-only selects — *Resolved in brainstorm*: accept text-as-value; documented edge case (see §7).
- [x] `ImportDiffReport` provenance — *Resolved in brainstorm*: add `options_source` to `ImportDiffEntry` (`metadata | inline | logic_groups | none`).

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`.
- All tasks (Modules 1–5) run sequentially in one worktree — they modify a
  single tightly-coupled file (`networkninja.py`) plus its two test modules;
  parallel worktrees would only create merge friction.
- **Cross-feature dependencies**: none. No in-flight spec touches
  `networkninja.py`; `core/options.py` and `core/constraints.py` are read-only
  here.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-23 | Claude | Initial draft from networkninja-metadata-select-options.brainstorm.md (Option A) |
| 0.2 | 2026-07-23 | Claude | Status → approved |
