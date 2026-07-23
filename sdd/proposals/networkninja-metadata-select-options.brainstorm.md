---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: NetworkNinja Importer — Select Options from `form_metadata`

**Date**: 2026-07-23
**Author**: Claude
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

The `NetworkninjaFormService` importer produces `FormSchema` objects with
`options: null` for select-type fields whose choices are stored **only** in
`networkninja.form_metadata.options`. The imported forms are therefore
un-fillable in FieldSync: rating scales (1–10 QUALITY / QUANTITY questions)
and any categorical `FIELD_SELECT` / `FIELD_SELECT_RADIO` / `FIELD_MULTISELECT`
whose options do not also appear inline in the question JSON or inside a
conditional `logic_group` come through empty.

**Who is affected**: FieldSync field teams filling imported NetworkNinja forms
(FLEXROC and other tenants). The recap/render layer receives select fields with
no selectable options. FieldSync consumes `parrot-formdesigner` from
`ai-parrot`, so the fix must land in this repository and be re-consumed
downstream.

**Why now**: The import of the 46 FLEXROC forms is validated and multi-form
render works, but every select whose catalog lives solely in
`form_metadata.options` is blocked. A live, per-form data patch was applied in
FieldSync as a stopgap; this brainstorm is the durable fix so no future import
needs manual patching.

### Root cause — a half-wired feature (four broken links)

Verified in
`packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/networkninja.py`
on `main` (commit `5fdf8ccb1`):

1. **`_FORM_QUERY` (lines 28–43)** builds the metadata `jsonb_build_object`
   with `column_id, column_name, description, data_type` — it **never selects
   `m.options`**.
2. **`_build_metadata_index` (lines 449–469)** stores only
   `column_id / data_type / description` per column — it **never stores
   `options`**, even if the query returned them.
3. **`_collect_select_options` (lines 504–594)** reads options from exactly two
   sources: (a) inline `options` arrays on the question JSON, and (b)
   `condition_comparison_value` inside `logic_groups`. It **never consults
   `form_metadata.options`**.
4. **The test fixtures already anticipate the field** but with an inconsistent
   key: `test_networkninja_importer.py` carries `"options": []` on metadata
   entries, and `test_feat300_integration.py` (line 106–111) builds
   `[{"option_id": 1, "option_label": "A"}]` — using `option_label`, while the
   **real column uses `option_value`**. The data contract anticipated options in
   metadata, but the plumbing was never connected and the real shape was never
   verified against a test.

### Verified source shape (staging, `navigator_staging`, 2026-07-23)

`networkninja.form_metadata.options` is a `jsonb` array:

```json
[
  {"is_active": true, "option_id": "6091", "column_name": 10211, "option_value": "Field Merchandiser"},
  {"is_active": true, "option_id": "6092", "column_name": 10211, "option_value": "Warehouse Manager"}
]
```

Live counts of option-bearing columns in `form_metadata`:
`FIELD_SELECT` = 111, `FIELD_SELECT_RADIO` = 227, `FIELD_MULTISELECT` = 243.

---

## Constraints & Requirements

- **Metadata is the canonical source.** `form_metadata.options` is the complete
  catalog; inline question options and logic-group-derived options are fallback
  only, used when the metadata catalog for a column is empty.
- **`FieldOption.value = option_id`, `FieldOption.label = option_value`.** The
  stable id is the submitted value; the human text is the label.
- **Conditions must stay consistent with option values.** Because option values
  become `option_id`, the `EQUALS` conditions in `logic_groups` (which compare
  against `condition_comparison_value`, the human text) must be **re-indexed to
  `option_id`** using the same metadata catalog, so `FieldCondition.value`
  lives in the same value-space as `FieldOption.value`. Otherwise conditional
  show/hide breaks for every select backed by metadata options.
- **Inactive options are preserved, not dropped.** Options with
  `is_active=false` are imported as `FieldOption(disabled=True)` so historical
  saved responses keep resolving to a label, while the option is not selectable.
- **No abort semantics change.** The import must remain non-aborting and keep
  producing an `ImportDiffReport`.
- **Backwards compatible.** Forms whose options come inline or from
  logic-groups must import exactly as before when metadata options are empty.
- **Scope is the importer only.** The 46-form re-import, per-tenant hydration,
  and program-aware selector are FieldSync work (NAV-9182), out of scope here.

---

## Options Explored

### Option A: Metadata-primary options wiring + condition re-indexing

Thread `form_metadata.options` through the full pipeline and make it the
canonical option catalog, with inline/logic-group options as fallback. Build a
per-column `option_value → option_id` translation catalog and use it to
re-index `EQUALS` conditions so conditional logic stays consistent with the new
`option_id`-based values.

Concretely (described, not coded):
- Add `'options', m.options` to the `jsonb_build_object` in `_FORM_QUERY`.
- Store `options` in each `_build_metadata_index` record.
- In `_collect_select_options`, add metadata as the **primary** source: for each
  option-typed column present in `meta_index`, emit
  `FieldOption(value=option_id, label=option_value, disabled=not is_active)`.
  Only fall back to inline + logic-group scanning when the metadata catalog for
  that column is empty.
- Build a `column_name → {option_value: option_id}` catalog from metadata and
  pass it to `_map_logic_groups`, which translates each
  `condition_comparison_value` to its `option_id` before constructing the
  `FieldCondition`. When the referenced column has no metadata catalog, keep the
  current text comparison (fallback path).

✅ **Pros:**
- Fixes every select backed by metadata options in one place, for all future
  imports — no per-form patching.
- Stable submitted values (`option_id`) survive label edits in NetworkNinja.
- Conditional logic remains correct because conditions and options share the
  `option_id` value-space.
- Preserves history via `disabled=True` for inactive options.
- Backwards compatible: inline/logic-group-only forms are untouched.

❌ **Cons:**
- Adds a metadata-derived translation step to condition mapping (more moving
  parts than a bare query patch).
- The fallback path (logic-group-only options) still uses text as value, so a
  small subset of forms remains label-keyed — must be documented as a known
  edge case.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | `pg` driver for the `_FORM_QUERY` fetch | already used by the service |
| `parrot-formdesigner.core` | `FieldOption`, `FieldCondition`, `DependencyRule`, `FormField`, `FormSchema` | in-repo, no new deps |

🔗 **Existing Code to Reuse:**
- `.../tools/services/networkninja.py` — `_FORM_QUERY`, `_build_metadata_index`,
  `_collect_select_options`, `_map_logic_groups`, `_map_question_to_field`
- `.../core/options.py:FieldOption` — has native `value`, `label`, `disabled`
- `.../core/constraints.py:FieldCondition` — `value: Any` accepts `option_id`

---

### Option B: Minimal query-only patch (metadata as a third inline-like source)

Add `m.options` to the query and store it in the index, then feed metadata
options into the existing collector as an additional source keyed the same way
the inline path is today (`value = value or option_id`, `label = option text`),
**without** re-indexing conditions.

✅ **Pros:**
- Smallest diff; touches the query, the index builder, and one collector branch.
- Immediately populates the missing scale/select options.

❌ **Cons:**
- Leaves the condition/value inconsistency unresolved: if `value = option_id`,
  conditional show/hide silently breaks for metadata-backed selects; if
  `value = text`, it contradicts the chosen `option_id` value semantics.
- No principled precedence between sources — risks mixing partial catalogs.
- Does not preserve inactive options with intent (`disabled`).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | query fetch | already used |

🔗 **Existing Code to Reuse:**
- Same files as Option A, but only the query + index + one collector branch.

---

### Option C: Runtime `OptionsSource` (dynamic options at render time)

Instead of baking options into the schema at import, attach an `OptionsSource`
(already defined in `core/options.py`, FEAT-167) to select fields, pointing at a
tool/endpoint/query that returns `form_metadata.options` on demand.

✅ **Pros:**
- Options always reflect the current NetworkNinja catalog without re-import.
- Keeps `FormSchema` lean; centralizes option resolution.

❌ **Cons:**
- Much larger blast radius: needs a resolver source, caching, auth wiring, and
  render-layer support in FieldSync — well beyond the importer.
- Introduces a runtime dependency on the NetworkNinja DB at form-render time.
- Overkill for a static, rarely-changing catalog; contradicts the current
  import-to-`form_schemas` model that FieldSync already relies on.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot-formdesigner.core` | `OptionsSource` | exists (FEAT-167) but unused by this importer |

🔗 **Existing Code to Reuse:**
- `.../core/options.py:OptionsSource`

---

## Recommendation

**Option A** is recommended. It is the only option that resolves the problem
completely and consistently: it makes `form_metadata.options` the canonical
catalog, honours the chosen `option_id`-as-value semantics, and keeps
conditional logic correct by re-indexing `EQUALS` conditions into the same
value-space. Option B is cheaper but ships a latent correctness bug in
conditional forms (the exact tension the value-semantics decision creates).
Option C solves a problem we do not have (live catalog freshness) at a cost
(runtime DB coupling, render-layer changes) that is out of scope for an importer
fix. Option A's accepted trade-offs are a modest translation step in condition
mapping and a documented fallback edge case where logic-group-only options stay
label-keyed.

---

## Feature Description

### User-Facing Behavior
After a form is (re-)imported, every select / radio / multi-select field backed
by `form_metadata.options` shows its full list of choices in FieldSync. Rating
scales (1–10) and categorical selects are selectable. Options that are inactive
in NetworkNinja appear disabled (not selectable) rather than vanishing, so
previously-saved answers still resolve to a readable label. Conditional
show/hide rules that key off a select continue to fire correctly.

### Internal Behavior
1. `fetch()` runs `_FORM_QUERY`, now aggregating `m.options` per column.
2. `_build_metadata_index` stores the raw `options` list alongside
   `column_id / data_type / description`.
3. `_collect_select_options` builds options **primarily** from the metadata
   catalog: `FieldOption(value=str(option_id), label=option_value,
   disabled=not is_active)`, deduping by `value`. Inline and logic-group sources
   are used only when a column's metadata catalog is empty.
4. A `column_name → {option_value: option_id}` catalog is derived from metadata.
5. `_map_logic_groups` translates each `condition_comparison_value` to its
   `option_id` via that catalog before building `FieldCondition`, so condition
   values match option values. Columns with no metadata catalog keep the current
   text comparison.
6. `_map_question_to_field` attaches the collected options exactly as today.
7. `ImportDiffEntry` gains an `options_source` provenance field
   (`"metadata" | "inline" | "logic_groups" | "none"`) recording where each
   option-typed field's choices came from; all other report behaviour is
   unchanged and the import still never aborts.

### Edge Cases & Error Handling
- **`options` is `null` / empty in metadata** → fall back to inline, then
  logic-group sources (current behaviour). No regression.
- **`option_value` collides across rows in one column** → dedup by `value`
  (`option_id`), so distinct ids are preserved even with duplicate labels.
- **Inactive option (`is_active=false`)** → imported with `disabled=True`.
- **Condition references a column with no metadata catalog** → keep text
  comparison (documented fallback; may leave value/label mismatch for
  logic-group-only options).
- **`condition_comparison_value` not found in the catalog** → leave the original
  value and log at debug; do not drop the condition.
- **`option_id` stored as int vs str in JSON** → cast to `str` (matches the
  existing `column_name` casting pattern in the service).

---

## Capabilities

### New Capabilities
- `networkninja-metadata-select-options`: import select/radio/multiselect
  options from `form_metadata.options` as the canonical catalog, with
  `option_id` values, `option_value` labels, `disabled` for inactive options,
  and condition re-indexing to keep conditional logic consistent.

### Modified Capabilities
- The NetworkNinja importer behaviour originally established under
  `formbuilder-database.spec.md` (FEAT-078) and extended by the FEAT-300 field
  work — this brainstorm extends the same importer.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `.../tools/services/networkninja.py` | modifies | query, metadata index, option collector, logic-group mapping |
| `packages/parrot-formdesigner/tests/unit/test_networkninja_importer.py` | modifies | add non-empty metadata-options fixtures + assertions; align key to `option_value` |
| `packages/parrot-formdesigner/tests/integration/test_feat300_integration.py` | modifies | fix `option_label` → `option_value`; assert options + disabled flow through |
| `.../tools/database_form.py` | depends on | consumes `NetworkninjaFormService`; no signature change expected |
| FieldSync `form_schemas` (downstream) | depends on | requires re-import of affected forms to persist populated options (NAV-9182, out of scope) |

---

## Code Context

### User-Provided Code
```text
# Source: user-provided (FieldSync stopgap diagnosis + live data patch, 2026-07-23)
# form_metadata.options real shape (staging navigator_staging):
#   {"is_active": true, "option_id": "6091", "column_name": 10211, "option_value": "Field Merchandiser"}
# The live FieldSync patch populated form_schemas directly from form_metadata.options
# for 2 forms (db-form-2-74, db-form-47-74); this brainstorm is the durable importer fix.
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py:13
class FieldOption(BaseModel):
    value: str            # line 25
    label: LocalizedString  # line 26
    description: LocalizedString | None = None  # line 27
    disabled: bool = False  # line 28
    icon: str | None = None  # line 29

# From packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py:144
class FieldCondition(BaseModel):
    value: Any = None     # line 158  (accepts the re-indexed option_id)

# From .../tools/services/networkninja.py
#   _FORM_QUERY                      lines 28–43   (jsonb_build_object 33–36: MISSING 'options')
#   _OPTION_FIELD_TYPES              lines 162–166
#   _build_metadata_index            lines 449–469 (stores column_id/data_type/description only)
#   _collect_select_options          lines 504–594 (Source 1 inline 558–577; Source 2 logic 579–586)
#   _map_question_to_field options   lines 736–739
#   _map_logic_groups                lines 792–869 (FieldCondition.value = comparison_value, line 843)
```

#### Verified Imports
```python
# Confirmed to work (used by the service today):
from ...core.options import FieldOption            # options.py:13
from ...core.constraints import ConditionOperator, DependencyRule, FieldCondition
from ...core.schema import FormField, FormSchema, FormSection, FormType
```

#### Key Attributes & Constants
- `FieldOption.disabled` → `bool` (default `False`) — used for inactive options
  (`.../core/options.py:28`)
- `FieldCondition.value` → `Any` — target for re-indexed `option_id`
  (`.../core/constraints.py:158`)
- `_OPTION_FIELD_TYPES` = `{FIELD_SELECT, FIELD_SELECT_RADIO, FIELD_MULTISELECT}`
  (`networkninja.py:162`)

### Does NOT Exist (Anti-Hallucination)
- ~~`m.options` in `_FORM_QUERY`~~ — not selected today; must be added
- ~~`options` key in `_build_metadata_index` records~~ — not stored today
- ~~metadata as a source in `_collect_select_options`~~ — only inline + logic-groups exist
- ~~`option_label` in the real column~~ — the real key is `option_value`
  (only the integration-test fixture wrongly used `option_label`)
- ~~a `meta` attribute on `FieldOption`~~ — it does not exist; use `disabled`

---

## Parallelism Assessment

- **Internal parallelism**: Low. All changes live in a single file
  (`networkninja.py`) plus its two test modules; they are tightly coupled
  (query → index → collector → logic mapping). Best done as one sequential task
  set.
- **Cross-feature independence**: No known in-flight spec touches
  `networkninja.py`. Shared surface is limited to `core/options.py` and
  `core/constraints.py`, which are read-only for this change.
- **Recommended isolation**: `per-spec` (single worktree, sequential tasks).
- **Rationale**: The pipeline stages are interdependent and small; parallel
  worktrees would only create merge friction on one file.

---

## Open Questions

- [x] Flow type / base branch — *Owner: user*: `feature` on `dev`.
- [x] `FieldOption.value` semantics — *Owner: user*: `value = option_id`,
  `label = option_value`.
- [x] Source precedence — *Owner: user*: `form_metadata.options` is primary;
  inline + logic-groups are fallback when the metadata catalog is empty.
- [x] Condition consistency — *Owner: user*: re-index `EQUALS`
  `condition_comparison_value` to `option_id` via the metadata catalog.
- [x] Inactive options — *Owner: user*: import all, mark `is_active=false` as
  `FieldOption(disabled=True)` to preserve historical values.
- [x] Scope — *Owner: user*: importer fix only; re-import + hydration are
  FieldSync (NAV-9182).
- [x] Fallback value/label mismatch for logic-group-only selects (no metadata
  catalog) — *Owner: user*: accept text-as-value. When a select column has no
  `form_metadata.options`, no `option_id` exists anywhere at the source, so the
  only available value is the human text from `condition_comparison_value`; the
  importer emits `FieldOption(value=text, label=text)`. This is internally
  consistent within the form (the conditions on that same field also compare by
  `comparison_value`, so `FieldCondition.value == FieldOption.value`), so
  conditional logic still fires. The only inconsistency is cross-form (metadata
  forms use `option_id`, fallback forms use text). Synthesizing a surrogate id
  is explicitly rejected: it would be untraceable to NetworkNinja and would
  break the text-based conditions. Documented as a known edge case; a saved
  answer keyed by text will not re-resolve if NetworkNinja later edits the
  wording, which is an unavoidable limitation of source data that carries no
  stable id.
- [x] Should the `ImportDiffReport` gain a note when options are sourced from
  metadata vs inline vs logic-groups (provenance)? — *Owner: user*: yes. Add an
  option-provenance signal to `ImportDiffEntry` (e.g. `options_source` ∈
  `{"metadata", "inline", "logic_groups", "none"}`) so an audit can tell which
  of the ~338 live select columns were populated from the canonical metadata
  catalog versus a fallback source. Low effort, high audit value.
