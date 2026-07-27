---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Vision Form Source — `epson.*` Importer for parrot-formdesigner

**Date**: 2026-07-23
**Author**: Claude
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

parrot-formdesigner can only import forms from **one** source schema:
`NetworkninjaFormService` reads `networkninja.forms` + `networkninja.form_metadata`
and turns their `question_blocks` structure into a canonical `FormSchema`.

The **epson** tenant's real production forms do **not** live in the
`networkninja.*` schema. In `networkninja.forms` there is exactly **one** epson
form (orgid 69, "Epson Visit Form"). Epson's actual catalog — **75 forms**, of
which **21** are `enabled=true` — lives in a dedicated **`epson.forms` /
`epson.form_metadata`** schema, authored in the **"Vision"** platform format.
That format is structurally different from NetworkNinja:

- There is **no `question_blocks` column** on `epson.forms`. The entire
  question structure NetworkNinja derives from `question_blocks` simply does not
  exist for Vision forms.
- The field/option structure is expressed **relationally** inside
  `epson.form_metadata` via a `parent_column` self-reference, not as nested JSON.
- The `data_type` vocabulary is a completely different set of tokens
  (`CheckBoxField`, `RadioButtonField`, `PhotoField`, `MultiLineTextField`, …)
  — **none** of which match the `FIELD_*` keys in
  `NetworkninjaFormService._FIELD_TYPE_MAP`.

Because of this, the existing importer cannot read a single epson Vision form.
FieldSync needs epson forms homologated into canonical `FormSchema` objects (and
downstream persisted into `navigator.form_schemas` with `tenant='epson'`, the
same way FLEXROC forms were handled) — but that persistence is FieldSync's job.
parrot's responsibility is a **new source adapter** that produces `FormSchema`
from the Vision format.

**Who is affected**: the epson field teams whose 21 enabled Vision forms are
currently un-importable; and FieldSync, which consumes parrot-formdesigner and
has no code path to ingest Vision forms today.

**Why now**: the NetworkNinja select-options fix (FEAT-325) is complete and the
FLEXROC import pipeline is validated end-to-end. Epson is the next tenant, and
its forms live in a different world that the current single-source importer
cannot reach.

### Verified source shape (staging `navigator_staging`, 2026-07-23)

**`epson.forms`** — 75 rows. `enabled=true` → **21**; `active=true` → 55;
`enabled ⊆ active`. formids **2662–4272**, all `orgid=69`. **Zero overlap** with
`networkninja.forms` formids. Columns:
`formid, form_name, is_store_stamp, is_apply_compliance, description,
is_toward_contribution, created_by, updated_on, enabled, orgid, inserted_at,
modified_by, created_on, active, is_public, guid`.
**No `question_blocks` column** (this is the column NetworkNinja gets its
question structure from — it is absent here).

**`epson.form_metadata`** — large per-form row counts (formid 2662 alone has
1379 rows). Columns:
`form_name, column_name, data_type, description, formid, col_id, is_active,
parent_column, orgid, is_metadata, vision_col_name, client_name, column_id,
client_id, vision_formid, inserted_at, options`.
The `options` **jsonb** column exists but is **EMPTY/null for ALL epson rows** —
options do NOT live there (unlike NetworkNinja, where `form_metadata.options`
is the canonical catalog per FEAT-325).

**Field vs. option structure (the key insight):**
- A **top-level FIELD** = a metadata row with `is_metadata=0` **AND**
  `parent_column IS NULL`. Its `description` is the field label.
- An **OPTION** = a child metadata row whose `parent_column` equals the parent
  field's `column_name`; the option label is the child's `description`.
- Worked example: parent field `194059` (`data_type=CheckBoxField`,
  desc "How was the training executed…") has children rows
  `194134 / 194135 / 194136 / 194137 / 194138` (`data_type=CheckBox`, desc
  "Solution Focus" / "Feature Focus" / "Value Focus" / "Store Benefit Focus" /
  "Other") — those five child rows are its options.
- Across the 21 enabled forms: **261 parent option-fields**, **1779 option
  child-rows**.
- `is_metadata=1` rows (`column_name` like `000_032`, raw SQL data_types) are
  internal/system columns, **NOT** user-facing fields.

**`data_type` vocabulary in epson (enabled forms only), with counts:**

| data_type | count | interpretation |
|---|---|---|
| `CheckBox` | 1665 | OPTION child rows (note: no "Field" suffix) |
| `varchar(MAX)` | 1423 | underlying/system SQL column |
| `RadioButtonField` | 892 | user field (single-select) |
| `PhotoField` | 673 | user field (photo capture) |
| `varchar(50)` | 524 | underlying/system SQL column |
| `MultiLineTextField` | 419 | user field (multi-line text) |
| `CheckBoxField` | 246 | user field (multi-select parent) |
| `SingleLineTextField` | 213 | user field (single-line text) |
| `varchar(100)` | 207 | underlying/system SQL column |
| `InformationalPhotoField` | 203 | user field (display/reference image) |
| `varchar(20)` | 105 | underlying/system SQL column |
| `varchar(102)` | 84 | underlying/system SQL column |
| `datetime` | 84 | underlying/system SQL column |
| `varchar(8)` | 84 | underlying/system SQL column |
| `varchar(30)` | 63 | underlying/system SQL column |
| `varchar(5)` | 63 | underlying/system SQL column |
| `int` | 63 | underlying/system SQL column |
| `nvarchar(60)` | 60 | underlying/system SQL column |
| `IntegerField` | 47 | user field (integer) |
| `varchar(3)` | 43 | underlying/system SQL column |
| `bit` | 21 | underlying/system SQL column |
| `NumberField` | 10 | user field (decimal) |
| `ComboBoxField` | 4 | user field (dropdown single-select) |
| `DatePickerField` | 4 | user field (date) |
| `nvarchar(30)` | 3 | underlying/system SQL column |
| `varchar(255)` | 3 | underlying/system SQL column |
| `numeric` | 3 | underlying/system SQL column |

**Interpretation to carry forward:**
- The **`*Field`-suffixed** types are the real user-facing field types:
  `CheckBoxField`, `RadioButtonField`, `ComboBoxField`, `PhotoField`,
  `InformationalPhotoField`, `MultiLineTextField`, `SingleLineTextField`,
  `IntegerField`, `NumberField`, `DatePickerField`.
- The **raw SQL types** (`varchar/int/bit/datetime/numeric/nvarchar`) are the
  underlying/system columns (mostly `is_metadata=1`).
- **`CheckBox`** (no "Field") are the **option child rows**, not fields.
- **None** of `NetworkninjaFormService._FIELD_TYPE_MAP`'s keys (`FIELD_TEXT`,
  `FIELD_SELECT`, `FIELD_MULTISELECT`, …) match any epson `data_type`.

---

## Constraints & Requirements

- **Do not touch NetworkNinja behaviour.** The existing
  `NetworkninjaFormService` and its FEAT-325 select-options logic must remain
  bit-for-bit unchanged. Whatever we add for epson must not regress it.
- **Implement the existing strategy interface.** Any adapter must satisfy
  `AbstractFormService` (`fetch` + `to_form_schema`), and — to match
  NetworkNinja's usable surface — also offer `import_with_report` returning an
  `ImportDiffReport`, so the importer never aborts and every field is accounted
  for.
- **Options come from parent/child rows, NOT the `options` column.** For epson,
  `form_metadata.options` is empty; options are the child rows whose
  `parent_column` equals the parent field's `column_name` (label = child's
  `description`).
- **Scope is `enabled=true` forms only** (the 21 live forms), all `orgid=69`.
- **Ignore `is_metadata=1` rows and raw-SQL `data_type` rows.** Only
  `is_metadata=0` rows with a `*Field` data_type are user fields; `CheckBox`
  child rows are options of their parent field.
- **No new heavy dependencies.** Reuse `asyncdb` (`pg`) and the in-repo
  `core/` models exactly as NetworkNinja does.
- **Async-first, `self.logger`, English-only artifacts** — per repo standards.
- **Persistence is out of scope.** Writing into `navigator.form_schemas`
  (`tenant='epson'`) is FieldSync's downstream job; parrot only produces the
  `FormSchema` (and diff report). This mirrors how FLEXROC persistence lived in
  FieldSync, not parrot.

---

## Options Explored

### Option A: New `VisionFormService` adapter implementing `AbstractFormService`

Add a sibling service, `VisionFormService`, next to `NetworkninjaFormService`
under `tools/services/`. It owns:
- a `_FORM_QUERY` against `epson.forms` + `epson.form_metadata`
  (`WHERE f.orgid = 69 AND f.enabled = true AND m.is_active = true`),
- a Vision-specific `data_type → FieldType` map (the `*Field` vocabulary),
- a relational field/option builder: rows with
  `is_metadata=0 AND parent_column IS NULL AND data_type LIKE '%Field'` become
  fields; rows whose `parent_column` matches a field's `column_name` become that
  field's `FieldOption`s (label = child `description`),
- and a `to_form_schema` / `import_with_report` pair mirroring NetworkNinja's
  pipeline shape (build index → collect options → map fields → emit
  `ImportDiffReport`).

Because Vision has no `question_blocks`, the schema is likely **flat**: one
section (or a small fixed grouping) holding all fields. The service maps
`epson.forms.form_name` → `FormSchema.title` and `epson.forms.description` →
`FormSchema.description`.

✅ **Pros:**
- Cleanest separation: epson logic is isolated; NetworkNinja is untouched
  (zero regression risk to FEAT-325).
- Mirrors an already-proven pattern (`NetworkninjaFormService`
  ⟶ `AbstractFormService`), so it slots into whatever selects a service by
  source (e.g. `DatabaseFormTool`) with an additional branch.
- The Vision→FieldType map and the parent/child option walk live in one place,
  easy to test against real staging shapes.
- Naturally extensible: a third tenant format later becomes a third adapter.

❌ **Cons:**
- Some structural code (metadata index, report assembly, DSN resolution) is
  conceptually similar to NetworkNinja and will be re-expressed rather than
  literally shared — a modest amount of parallel structure. (Shared helpers can
  be factored later if a third source appears; premature abstraction now would
  couple two live importers.)
- Whatever chooses which service to instantiate (source dispatch) needs one new
  branch — small, but it must be located and wired.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | `pg` driver for the epson query | already used by `NetworkninjaFormService` |
| `parrot-formdesigner.core` | `FieldType`, `FieldOption`, `FormField`, `FormSection`, `FormSchema` | in-repo, no new deps |

🔗 **Existing Code to Reuse:**
- `.../tools/services/abstract.py:AbstractFormService` — interface to implement.
- `.../tools/services/networkninja.py` — structural template for the pipeline
  (`fetch`, `_build_form_schema_with_report`, `_build_metadata_index`,
  `_collect_select_options`, `_map_question_to_field`, `ImportDiffEntry`,
  `ImportDiffReport`, DSN resolution).
- `.../core/options.py:FieldOption` — `value`, `label`, `disabled`.
- `.../core/schema.py:FormSchema/FormSection/FormField` — `tenant` field already
  documents the `"epson"` → `epson.form_schemas` intent (schema.py:288).

---

### Option B: ETL `epson.*` → `networkninja.*` (orgid 69), then reuse the existing importer

Write a one-way transform that reshapes epson Vision rows into the
`networkninja.forms` / `networkninja.form_metadata` shape (synthesizing a
`question_blocks` JSON, mapping `*Field` → `FIELD_*`, and materializing options
as `form_metadata.options`), landing them under orgid 69. Then run the existing
`NetworkninjaFormService` unchanged.

✅ **Pros:**
- Reuses the entire NetworkNinja pipeline (incl. FEAT-325 options + conditions)
  with zero importer changes.
- One canonical importer path to maintain going forward.

❌ **Cons:**
- Requires **writing** into the `networkninja.*` schema (or a staging clone) —
  the task explicitly forbids DB writes, and mutating a shared tenant schema is
  risky and out of parrot's remit.
- Must **synthesize `question_blocks`** — a format epson never produced —
  which is exactly the lossy, error-prone translation we would otherwise avoid;
  bugs surface as malformed NetworkNinja JSON far from their cause.
- Collides conceptually with the single "Epson Visit Form" already in
  `networkninja.forms` (orgid 69) — formid-space management and dedup become a
  problem.
- Two hops (Vision → NN shape → FormSchema) instead of one; harder to trace and
  test.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | read epson, write networkninja | write path is out of scope / disallowed |

🔗 **Existing Code to Reuse:**
- `NetworkninjaFormService` in full — but only if the upstream shape is faked
  first, which is the expensive part.

---

### Option C: Generalize `NetworkninjaFormService` with a pluggable source strategy

Refactor `NetworkninjaFormService` into a generic base that delegates
source-specific concerns (query, `data_type` map, option-collection strategy,
structure normalization) to pluggable strategy objects, then implement a
"networkninja" strategy (existing behaviour) and a "vision" strategy (epson).

✅ **Pros:**
- Maximizes long-term code sharing (metadata index, report assembly, DSN).
- One class hierarchy for all present and future form sources.

❌ **Cons:**
- Forces an invasive refactor of a **freshly-shipped, load-bearing** importer
  (FEAT-325 just landed) purely to accommodate a second source — high
  regression risk on NetworkNinja for no NetworkNinja benefit.
- The two sources differ so fundamentally (JSON `question_blocks` vs. relational
  `parent_column`; `options` column vs. child rows; disjoint `data_type`
  vocabularies) that a "common" abstraction would be thin and leaky — most logic
  would still live in the strategies.
- Designing the right seams needs both sources fully understood first;
  abstracting on the strength of one-and-a-half examples tends to produce the
  wrong seams.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot-formdesigner.core` | shared models | in-repo |

🔗 **Existing Code to Reuse:**
- `AbstractFormService` — already the correct extension seam; the strategy-in-a-
  strategy adds a second layer of indirection on top of it.

---

## Recommendation

**Option A** is recommended. It is the approach the codebase's own strategy
interface (`AbstractFormService`) was designed for: add a new source as a new
adapter, leaving the proven NetworkNinja path untouched. It reads epson directly
in one hop (no synthesized `question_blocks`, no DB writes — satisfying the
"exploration only" and "no DB writes" constraints), and it localizes the Vision
`data_type → FieldType` map and the `parent_column` option walk in a single,
testable place.

Option B is rejected because it requires writing a fabricated
`networkninja.*` representation into a shared schema — disallowed here and
architecturally backwards (translating *into* a legacy shape to reach a
canonical one). Option C is rejected because it would refactor a just-shipped,
critical importer to serve a second source whose structure is so different that
the shared abstraction would be thin and the regression risk high; the honest
trade-off is that Option A carries some parallel structure between the two
services, which we accept now and can factor into shared helpers **later** if
and when a third source appears (the "rule of three").

---

## Feature Description

### User-Facing Behavior

For each `enabled=true` epson form (the 21 live forms, orgid 69), the new
`VisionFormService` produces a canonical `FormSchema` whose title/description
come from `epson.forms`, whose fields are the `*Field` user columns, and whose
select/radio/multi-select fields carry their options (built from the
`parent_column` child rows). Downstream, FieldSync persists these into
`navigator.form_schemas` with `tenant='epson'` (out of scope here) so epson
field teams can fill their real forms in FieldSync. An `ImportDiffReport`
accompanies each import so unmapped or approximate fields are auditable rather
than silently dropped.

### Internal Behavior

1. `fetch(*, formid, orgid=69, **kwargs)` runs a parameterized query against
   `epson.forms` JOIN `epson.form_metadata`, filtering
   `enabled=true AND is_active=true` (open question: exact filter placement),
   returning the form header plus all metadata rows.
2. A metadata pass partitions rows:
   - **fields** = `is_metadata=0 AND parent_column IS NULL AND data_type` ends
     with `Field`;
   - **options** = rows whose `parent_column` equals a field's `column_name`
     (grouped under that parent; label = child `description`);
   - everything else (`is_metadata=1`, raw-SQL data_types, orphan `CheckBox`
     rows) is ignored, recorded in the report as skipped/system.
3. Each field row is mapped via a Vision `data_type → FieldType` table (draft in
   Open Questions). Option-bearing fields (`CheckBoxField`, `RadioButtonField`,
   `ComboBoxField`) receive their collected `FieldOption`s.
4. Because Vision has no `question_blocks`, the form is assembled **flat** —
   most likely a single `FormSection` holding all fields (open question:
   whether any grouping concept exists).
5. `import_with_report` returns `(FormSchema, ImportDiffReport)`; `to_form_schema`
   returns just the schema. The import never aborts.

### Edge Cases & Error Handling

- **`data_type` not in the Vision map** → record `requiere_intervencion`
  in the report, skip the field (mirrors NetworkNinja).
- **Option-bearing field with zero child rows** → import the field with
  `options=None` and flag it in the report (empty select).
- **Orphan `CheckBox` child whose `parent_column` matches no field** → ignore +
  note (dangling option).
- **`is_metadata=1` / raw-SQL rows** → excluded from fields entirely.
- **Form with no user fields after filtering** → still produce a `FormSchema`
  (empty/near-empty) and a report explaining why, rather than raising.
- **`options` jsonb present but empty (always, for epson)** → never read; the
  parent/child walk is the sole option source.

---

## Capabilities

### New Capabilities
- `vision-form-source`: a new `VisionFormService` adapter that imports epson
  Vision forms (`epson.forms` / `epson.form_metadata`) into canonical
  `FormSchema` objects — mapping the `*Field` data_type vocabulary and building
  options from `parent_column` child rows — with an `ImportDiffReport`.

### Modified Capabilities
- None. The existing NetworkNinja importer capability
  (`networkninja-metadata-select-options`, FEAT-325) is explicitly **not**
  modified.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `.../tools/services/vision.py` (new) | creates | new `VisionFormService(AbstractFormService)` |
| `.../tools/services/abstract.py` | depends on | implements `fetch` + `to_form_schema` |
| `.../tools/services/networkninja.py` | none | left untouched; may share `ImportDiffEntry`/`ImportDiffReport` shape (open question: reuse vs. duplicate) |
| Source dispatch (e.g. `tools/database_form.py` / registry) | modifies | one branch to select `VisionFormService` for epson (needs locating) |
| `.../core/*` (`FieldType`, `FieldOption`, `FormSchema`) | uses | read-only; no model changes expected |
| FieldSync `navigator.form_schemas` (`tenant='epson'`) | depends on (downstream) | persistence of the produced schemas — out of scope for parrot |
| `packages/parrot-formdesigner/tests/unit/` (new tests) | creates | fixtures mirroring real epson row shapes |

---

## Code Context

### User-Provided Code

```text
# Source: user-provided (staging navigator_staging investigation, 2026-07-23)
#
# epson.form_metadata field vs. option structure:
#   FIELD  = row with is_metadata=0 AND parent_column IS NULL AND data_type ~ '%Field'
#            (its `description` is the field label)
#   OPTION = child row where parent_column == <parent field>.column_name
#            (its `description` is the option label; data_type = 'CheckBox')
#
# Worked example (parent field 194059, CheckBoxField,
#   "How was the training executed…"):
#     child 194134 CheckBox "Solution Focus"
#     child 194135 CheckBox "Feature Focus"
#     child 194136 CheckBox "Value Focus"
#     child 194137 CheckBox "Store Benefit Focus"
#     child 194138 CheckBox "Other"
#
# epson.form_metadata.options (jsonb) is EMPTY/null for ALL epson rows.
# Across the 21 enabled forms: 261 parent option-fields, 1779 option child-rows.
```

### Verified Codebase References

#### Classes & Signatures
```python
# From .../tools/services/abstract.py:11
class AbstractFormService(ABC):
    @abstractmethod
    async def fetch(self, **params: Any) -> dict[str, Any]: ...   # line 26 (keyword-only in impls)
    @abstractmethod
    def to_form_schema(self, raw: dict[str, Any]) -> FormSchema: ...  # line 36

# From .../tools/services/networkninja.py  (structural template — DO NOT MODIFY)
# Line numbers re-verified on dev after the FEAT-325 merge (commit 8dc34ba46).
class NetworkninjaFormService(AbstractFormService):     # line 174
    async def fetch(self, *, formid: int, orgid: int, **_: Any) -> dict[str, Any]:  # line 212
    def to_form_schema(self, raw: dict[str, Any]) -> FormSchema:                    # line 248
    def import_with_report(self, raw) -> tuple[FormSchema, ImportDiffReport]:       # line 261 (concrete, NOT on the abstract base)
    _FORM_QUERY                       # line 28 (networkninja.forms + form_metadata; has question_blocks)
    _FIELD_TYPE_MAP                   # line 107 (FIELD_* keys — none match epson)
    _OPTION_FIELD_TYPES               # line 167
    def _build_metadata_index         # line 459 (column_name → {column_id,data_type,description})
    def _collect_select_options       # line 576
    def _map_question_to_field        # line 783
class ImportDiffEntry(BaseModel)      # line 55 (column_name, source_data_type, mapped_field_type, status, note, options_source[FEAT-325])
class ImportDiffReport(BaseModel)     # line 82 (form_id, source, imported_at, fields[])

# From .../core/options.py:14
class FieldOption(BaseModel):
    value: str              # line 25
    label: LocalizedString  # line 26
    description: LocalizedString | None = None  # line 27
    disabled: bool = False  # line 28
    icon: str | None = None # line 29

# From .../core/schema.py
class FormField(BaseModel):     # line 43
    field_id: str                       # line 74
    field_type: FieldType               # line 75
    label: LocalizedString              # line 76
    options: list[FieldOption] | None = None   # line 83
    depends_on: DependencyRule | None = None   # line 85
    meta: dict[str, Any] | None = None         # line 89
class FormSection(BaseModel):   # line 127  (section_id, title, fields: list[SectionItem])
class FormSchema(BaseModel):    # line 267
    form_id: str                # line 305
    title: LocalizedString      # line 307
    sections: list[FormSection] # line 309
    tenant: str | None = None   # line 314  (docstring: "epson" → epson.form_schemas)
    form_type: FormType = FormType.SIMPLE  # line 318

# From .../core/types.py:16
class FieldType(str, Enum):
    TEXT / TEXT_AREA / NUMBER / INTEGER / BOOLEAN / DATE / DATETIME / TIME
    SELECT / MULTI_SELECT / FILE / IMAGE / ...     # lines 19–55  (no "photo" type — PhotoField → FILE or IMAGE)
```

#### Verified Imports
```python
# Confirmed to work (used by NetworkninjaFormService today):
from ...core.constraints import ConditionOperator, DependencyRule, FieldCondition
from ...core.options import FieldOption
from ...core.schema import FormField, FormSchema, FormSection, FormType
from ...core.types import FieldType
from .abstract import AbstractFormService
from asyncdb import AsyncDB  # lazy import inside NetworkninjaFormService.fetch()
```

#### Key Attributes & Constants
- `AbstractFormService` declares exactly TWO abstract methods: `fetch` and
  `to_form_schema` (abstract.py:26, :36). `import_with_report` is a **concrete
  convenience** on `NetworkninjaFormService`, not part of the base contract.
- `FieldOption.value` is `str` — an epson option value must be chosen (see Open
  Questions) and cast to `str`.
- `FormSchema.tenant` already exists and its docstring names `"epson"`
  (schema.py:288) — the downstream target, confirming persistence is a known
  FieldSync concern, not a parrot model change.

### Does NOT Exist (Anti-Hallucination)
- ~~`epson.forms.question_blocks`~~ — the column does NOT exist; Vision has no
  question_blocks. Any code assuming it will fail.
- ~~epson options in `epson.form_metadata.options`~~ — the `options` jsonb column
  is EMPTY/null for every epson row; options are `parent_column` child rows.
- ~~`FIELD_SELECT` / `FIELD_MULTISELECT` / any `FIELD_*` key for epson~~ — epson
  uses `CheckBoxField` / `RadioButtonField` / `ComboBoxField` / etc.; NONE of
  `_FIELD_TYPE_MAP`'s keys apply. A new Vision map is required.
- ~~`FieldType.PHOTO`~~ — no such enum member; `PhotoField` must map to `FILE` or
  `IMAGE` (Open Question).
- ~~`VisionFormService`~~ — does not exist yet; to be created under
  `tools/services/`.
- ~~`import_with_report` on `AbstractFormService`~~ — not on the base; only on
  the concrete NetworkNinja service (would need to be re-declared on the Vision
  service).
- ~~a `meta` attribute on `FieldOption`~~ — does not exist; use `disabled`
  for non-selectable options.

---

## Parallelism Assessment

- **Internal parallelism**: Low–Medium. The adapter is one new file with an
  internally sequential pipeline (query → partition rows → build options →
  map fields → assemble schema/report). Tests can be authored alongside. Not
  worth splitting into parallel worktrees.
- **Cross-feature independence**: High. The change is additive — a new file
  under `tools/services/` plus (at most) one dispatch branch. It does not touch
  `networkninja.py`. The only shared surface is read-only `core/` models and the
  `ImportDiffEntry`/`ImportDiffReport` shape (which may be reused or duplicated —
  an open question). No in-flight spec is known to modify `tools/services/`.
- **Recommended isolation**: `per-spec` (single worktree, sequential tasks).
- **Rationale**: The work is cohesive and localized to one new adapter; parallel
  worktrees would add coordination cost with no decomposition benefit.

---

## Open Questions

<!-- Convention: [ ] unresolved — *Owner: name*   /   [x] resolved — *Owner: name*: answer -->

**Resolved (decisions already made — constraints):**
- [x] Flow type / base branch — *Owner: user*: `feature` on `dev`.
- [x] Scope — *Owner: user*: `enabled=true` forms only (the 21 live forms),
  orgid 69.
- [x] Where options come from — *Owner: user*: from `parent_column` → child rows
  (option label = child `description`), NOT the empty `options` jsonb column.
- [x] Persistence target — *Owner: user*: FieldSync persists to
  `navigator.form_schemas` (`tenant='epson'`); this is downstream and **out of
  scope** for the parrot importer.
- [x] Recommended approach — *Owner: Claude*: Option A, a new
  `VisionFormService` implementing `AbstractFormService`; NetworkNinja untouched.

**Unresolved (need validation before / during spec):**
- [ ] **Vision `data_type → FieldType` mapping table** — *Owner: user*: draft
  below, MARK FOR VALIDATION (do not treat as final):
  - `SingleLineTextField` → `FieldType.TEXT`
  - `MultiLineTextField`  → `FieldType.TEXT_AREA`
  - `IntegerField`        → `FieldType.INTEGER`
  - `NumberField`         → `FieldType.NUMBER`
  - `DatePickerField`     → `FieldType.DATE`
  - `RadioButtonField`    → `FieldType.SELECT` (`meta.render_as="radio"`)
  - `ComboBoxField`       → `FieldType.SELECT`
  - `CheckBoxField`       → `FieldType.MULTI_SELECT`
  - `PhotoField`          → `FieldType.FILE` (`meta.accept="image/*"`) — or `IMAGE`?
  - `InformationalPhotoField` → `FieldType.IMAGE` (read-only display) — or `FILE`?
  Confirm each mapping (especially the two photo variants) against product
  intent and the renderer's capabilities.
- [ ] **Sectioning / grouping** — *Owner: user*: does Vision have any grouping
  concept (page/section/subsection), or are forms strictly flat? (No
  `question_blocks` exists.) If flat, confirm a single `FormSection` is
  acceptable; if some column signals grouping (e.g. an ordering or a
  `parent_column` used for layout rather than options), define it.
- [ ] **`FieldOption.value` source** — *Owner: user*: which epson child-row
  attribute becomes the stable option `value` — `column_name`, `col_id`,
  `column_id`, or `description`? (`description` is the label; a stable id is
  preferable for saved-answer resolution, but must be verified to exist and be
  stable across Vision edits.)
- [ ] **Conditional / dependency logic** — *Owner: user*: does the Vision format
  encode any conditional show/hide (equivalent to NetworkNinja `logic_groups`)?
  If so, where (which columns/relationship) and how should it map to
  `DependencyRule` / `FieldCondition`? If none exists, confirm epson forms are
  unconditional.
- [ ] **Form title / description mapping** — *Owner: user*: confirm
  `epson.forms.form_name` → `FormSchema.title` and `epson.forms.description` →
  `FormSchema.description`; and whether `is_public` (present on `epson.forms`)
  should flow to `FormSchema.is_public`.
- [ ] **`fetch()` filtering** — *Owner: user*: should `fetch` hard-filter
  `enabled=true AND orgid=69` in SQL (opinionated, epson-specific), or accept
  `formid`/`orgid` like NetworkNinja and let the caller pass a single form?
  (Leaning: parameterized per-form fetch like NetworkNinja, with the
  enabled/orgid filter as a guard.)
- [ ] **`ImportDiffReport` reuse** — *Owner: Claude/user*: reuse the existing
  `ImportDiffEntry`/`ImportDiffReport` classes from `networkninja.py` (import
  them) or define Vision-local equivalents? Reuse avoids drift; importing from a
  sibling service is a minor coupling to weigh.
