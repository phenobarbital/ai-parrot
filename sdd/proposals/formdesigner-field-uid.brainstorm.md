---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Stable UUID-Based Field Identity (field_uid)

**Date**: 2026-07-31
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`FormField.field_id` is a bare, human-editable `str` (`parrot_formdesigner/core/schema.py:74`)
that serves simultaneously as:

1. the **identity** of a field for the edit/design surface (batch operations in
   `api/operations.py`, `EditToolkit` in `tools/edit_toolkit.py`),
2. the **reference key** of conditional rules (`FieldCondition.field_id`,
   `DependencyOperation.operands/target`, `PostDependency.target`),
3. a **durable external key** — blob storage object paths embed it
   (`services/blob_storage.py:220`), and
4. the **data-binding key** of submissions, partial saves, prefill/error maps,
   and every renderer's output names.

There is **no uniqueness warranty anywhere**: `FormField.field_id` has no format
validation, no model-level duplicate check (the set at `core/schema.py:338` exists
only for metadata-key collision), and edit-time uniqueness is checked **per section
only** (`api/operations.py:187`), with a traversal that disagrees with the lookup
traversal in the same module. A `FormSchema` with two identical `field_id`s
validates cleanly; renaming a `field_id` silently orphans previously uploaded
blobs and breaks rule references.

FEAT-389 (`sdd/specs/form-uid-stable-identity.spec.md`, approved, in-flight) fixes
the same disease at the form level with `form_uid` and explicitly declares FormField
out of scope. This feature is its natural sequel: give every structural element of a
form — **field, section, subsection** (all string-addressed today: `field_id`,
`section_id` at `core/schema.py:146`, `subsection_id` at `:116`) — a stable,
auto-generated, immutable UUID identity, and move every internal reference onto it.

**Who is affected**: FormDesigner UI/API consumers (edit operations become
rename-proof), the LLM edit toolkit, blob storage integrity, rule evaluation.
FormDesigner is **not in production** — a clean break without backward
compatibility is approved (same posture as FEAT-389).

## Constraints & Requirements

Decisions locked during interactive discovery (4 rounds):

- **Sequencing**: this feature starts **only after FEAT-389 merges to dev**. It
  assumes `form_uid` exists on FormSchema, registry, storage, handlers, blob keys.
- **Type**: `uuid.UUID` (real Pydantic UUID type), not `str`. Includes a
  **retrofit task** converting FEAT-389's `form_uid: str` to `uuid.UUID` so both
  identities use the same type. Pydantic serializes UUID → str in JSON; DB columns
  become native `UUID`.
- **Scope**: all three levels — `field_uid`, `section_uid`, `subsection_uid` —
  one clean break, one migration.
- **`field_id` is kept** as the human-editable name/key: it remains the
  data-binding key for submission payloads, renderer output names, prefill/error
  maps. `section_id`/`subsection_id` likewise stay as editable labels/slugs.
- **UID origin**: upsert style — creation APIs accept a client-provided UUID when
  present (validated), otherwise server/model generates (`default_factory=uuid4`).
- **Uniqueness**: global uniqueness by uuid4 collision-negligibility; **enforced
  at the validation layer** (model validator + FormValidator), per-form duplicate
  UID = validation error. No per-field DB table (fields stay embedded JSONB).
- **Consumers switching to `field_uid`**: edit/design API operations, EditToolkit,
  conditional rules (pre/post depends, operations), blob storage keys, upload
  route param, internal partial-save keying, cycle detection, rule evaluator
  graphs. **Submission payload keys stay `field_id`.**
- **Rule authoring**: authors/LLM/YAML keep writing rules by `field_id`;
  extractors and creation/assembly paths **resolve `field_id` → `field_uid` at
  build time**. Ambiguous (duplicate) `field_id` at resolution time = validation
  error — this finally forces per-form `field_id` uniqueness at build boundaries.
- **Question bank**: bank entries are templates; every insertion into a form
  **mints a fresh `field_uid`** (bank's own `ReusableField.field_id` is already an
  unrelated minted UUID — see Code Context).
- Clean break: no dual-routing, no deprecation shims, no backward-compatible
  payloads (consistent with FEAT-389's approved posture).

---

## Options Explored

### Option A: Mirror FEAT-389 — additive UUID identity on the models, validation-layer uniqueness

Add `field_uid: uuid.UUID = Field(default_factory=uuid4)` to `FormField` (and
`section_uid`/`subsection_uid` to `FormSection`/`FormSubsection`). Retrofit
`form_uid` to `uuid.UUID`. Add a `FormSchema` model validator that walks the
**full** field tree (sections, subsections, `children`, `item_template`) and
rejects duplicate UIDs. Edit operations (`api/operations.py`, `EditToolkit`)
address elements by UID; `_field_index`-style lookups become form-wide,
subsection-aware UID lookups. Rules store `field_uid` internally, resolved from
authored `field_id` at build time by extractors/assembler. Blob keys become
`{prefix}{form_uid}/{field_uid}/{blob_uuid}`; upload route becomes
`/forms/{form_uid}/fields/{field_uid}/upload`. Fields remain embedded JSONB —
migration is a backfill script injecting UIDs into stored `schema_json`.

✅ **Pros:**
- Same architecture, vocabulary, and test patterns as the approved FEAT-389 —
  lowest cognitive and review cost; the two features read as one design.
- No storage redesign: JSONB stays; migration is a self-contained backfill.
- Fixes today's latent bugs as side effects: per-form duplicate detection
  (currently absent), subsection-unaddressable fields in `_field_index`
  (`api/operations.py:180-181`), blob orphaning on rename.
- UUID type gives format validation for free (Pydantic parses/rejects).

❌ **Cons:**
- Uniqueness is a validation-layer promise, not a DB constraint — a writer that
  bypasses the models could still persist duplicates.
- Big mechanical blast radius (~15 modules, see Impact) — though FormDesigner is
  pre-production, so no compat burden.
- Build-time `field_id → field_uid` rule resolution adds a step to every
  extractor/creation path.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `uuid` (stdlib) | uuid4 generation + UUID type | no new dependency |
| `pydantic` v2 (already pinned) | UUID field type, model validators | serializes UUID→str in JSON automatically |
| PostgreSQL `UUID` type | native columns where UIDs surface in DDL | already used by `form_schemas.id` |

🔗 **Existing Code to Reuse:**
- `sdd/specs/form-uid-stable-identity.spec.md` — the whole module/test breakdown pattern (FEAT-389)
- `parrot_formdesigner/services/validators.py:791-1053` — `validate_rules` + `_detect_circular_dependencies` already build field maps/graphs; re-key on UID
- `parrot_formdesigner/services/validators.py:736,753` — `_collect_fields`/`_collect_nested_fields`, the only traversal that recurses `children`/`item_template`; promote to the canonical traversal for UID uniqueness
- `api/operations.py:214-350` — the op-apply skeleton and `_DISPATCH` map stay; only lookup/uniqueness helpers change
- FEAT-389's migration artifacts under `packages/parrot-formdesigner/migrations/` — extend the same numbered, idempotent SQL + Python backfill convention

---

### Option B: Normalize fields into a per-field table (`form_fields`) with a real DB constraint

Break fields out of `schema_json` into `form_fields` rows
(`field_uid UUID PRIMARY KEY`, `form_uid FK`, `definition JSONB`, `field_id`,
`position`, `section_uid`), with `UNIQUE(field_uid)` enforced by PostgreSQL and
`UNIQUE(form_uid, field_id)` protecting the data-binding key.

✅ **Pros:**
- The uniqueness *warranty* is real (DB-enforced), not a model-layer promise.
- Enables per-field queries, cross-form field analytics, FK integrity from
  question-bank usage counters and blob metadata.

❌ **Cons:**
- Full storage redesign: `PostgresFormStorage` upsert/load becomes a multi-table
  transaction; every whole-schema read must reassemble the tree.
- Explicitly rejected during discovery ("Validation layer" chosen) — the JSONB
  document model is a deliberate architecture choice.
- Much larger migration; versioned forms multiply rows (`form_uid, version`
  dimensions).

📊 **Effort:** Very High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncpg` (already used) | multi-statement transactions | no new dependency |

🔗 **Existing Code to Reuse:**
- `services/question_bank.py:74-102` — the only existing per-field-row DDL/SQL pattern in the package

---

### Option C (unconventional): No new UID — make `field_id` itself immutable and validated

Keep a single identifier: apply `services/_identifiers.validate_identifier` to
`field_id` (it already exists and guards metadata keys), enforce per-form
uniqueness in a model validator, and make renames a **copy-and-migrate**
operation (new field + data migration) instead of an in-place edit.

✅ **Pros:**
- Near-zero blast radius: no new field, no migration of stored schemas, rules
  and blob keys stay valid by construction.
- One identifier — no dual-key bookkeeping anywhere.

❌ **Cons:**
- Contradicts the product requirement: `field_id` must stay *editable* as the
  human-facing data-binding key (users rename `q1` → `customer_email`).
- "Rename = new field" pushes migration pain onto every rename instead of
  solving identity once.
- Diverges from FEAT-389's already-approved two-key design (form_uid + slug).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | none | pure validation change |

🔗 **Existing Code to Reuse:**
- `services/_identifiers.py` — `validate_identifier` (already applied to metadata keys at `core/schema.py:342`)

---

## Recommendation

**Option A** is recommended because:

- It is the pattern the team already approved for the same problem one level up
  (FEAT-389); reusing its module breakdown, migration conventions, and test
  taxonomy minimizes design risk and review friction.
- The discovery rounds explicitly selected its pillars: UUID type everywhere
  (with the form_uid retrofit), validation-layer enforcement over a storage
  redesign (Option B's DB constraint was weighed and declined as
  disproportionate for a pre-production app), and keeping `field_id` editable
  (which eliminates Option C).
- What we trade off — uniqueness as a validation-layer promise rather than a DB
  constraint — is acceptable: uuid4 collisions are negligible, every write path
  goes through the Pydantic models, and the model validator closes the gap that
  today allows *silent* duplicates. If a hard warranty is later needed, Option B
  can be layered on without changing the application-level contract.

---

## Feature Description

### User-Facing Behavior

- Every field, section, and subsection in a form carries a `field_uid` /
  `section_uid` / `subsection_uid` (UUID) in API responses, alongside the
  editable `field_id` / `section_id` / `subsection_id`.
- Creating elements (blank-form editor, batch operations, LLM CreateFormTool,
  extractors): the client MAY supply a UID (validated as UUID, rejected on
  duplicate); otherwise one is generated. Response always echoes the final UID.
- Edit/design operations (`add_field`, `update_field`, `remove_field`,
  `move_field`, `duplicate_field`, and their section counterparts) address
  targets by UID. Renaming `field_id` via `update_field` becomes a legal patch —
  identity no longer pinned to the string (today `api/operations.py:278`
  silently reverts it).
- The upload endpoint becomes `POST /forms/{form_uid}/fields/{field_uid}/upload`;
  invalid UUID in path → 400, unknown UID → 404.
- Form authors (humans, YAML, LLM) keep writing conditional rules against
  `field_id`. On schema assembly the references are resolved to UIDs; a rule
  referencing a missing or duplicated `field_id` fails validation with a clear
  error. Duplicate `field_id` within a form is now rejected at build/save time.
- Submission payloads, partial-save payloads, rendered HTML control names, and
  prefill/error maps continue to use `field_id` — no change for form fillers.

### Internal Behavior

- **Models** (`core/schema.py`): `field_uid`/`section_uid`/`subsection_uid` as
  `uuid.UUID = Field(default_factory=uuid4)`. A `FormSchema` model validator
  performs a **full-tree traversal** (sections → subsections → fields →
  `children` → `item_template`, i.e. the `_collect_nested_fields` semantics) and
  rejects duplicate UIDs *and* duplicate `field_id`s per form. `form_uid` is
  retrofitted from `str` to `uuid.UUID` in the same stroke (FormSchema,
  FormSubmission, BlobMetadata, registry keys, handler helpers).
- **Rules** (`core/constraints.py`): `FieldCondition`, `DependencyOperation`
  (`operands`, `target`), `PostDependency.target` carry `field_uid` values
  internally. `FormValidator.validate_rules`, `_detect_circular_dependencies`,
  and `RuleEvaluator._topo_order` re-key their maps/graphs on UID. The rule
  evaluator resolves UID → field → `field_id` to read `answers` (which stay
  keyed by `field_id`).
- **Build-time resolution**: extractors (`yaml`, `jsonschema`, `pydantic`,
  `tool`) and `CreateFormTool` continue producing `field_id`-referenced rules;
  a shared resolution pass (natural home: the FEAT-389 FormAssembler /
  schema-assembly boundary) mints UIDs and rewrites rule references, erroring on
  unknown/ambiguous `field_id`.
- **Edit surface**: `api/operations.py` payload models gain UID target params;
  `_field_index`/`_check_unique_field_id` are replaced by one form-wide,
  subsection-aware UID lookup (fixing the current asymmetry).
  `EditToolkit._find_field_and_section` and all 12 tool methods switch to UID
  params, while `search_fields` keeps matching on `field_id`/label for LLM
  ergonomics (returning UIDs).
- **Blob storage**: `_build_key` → `{prefix}{form_uid}/{field_uid}/{blob_uuid}`;
  `BlobMetadata` gains `field_uid` (keeps `field_id` as descriptive metadata).
- **Partial saves**: wire payload stays `{"answers": {field_id: value}}`; the
  service re-keys internally to `field_uid` before persisting to Redis so a
  rename mid-session doesn't orphan saved answers, and maps back on read.
  (Flagged as open question — see below.)
- **Question bank**: `resolve_ref` insertion path mints a fresh `field_uid` for
  the inserted `FormField` (bank `ReusableField.field_id` — itself a minted
  UUID, unrelated to `FormField.field_id` — is untouched).
- **Storage/migration**: `form_schemas.schema_json` stays JSONB. Numbered,
  idempotent migration artifacts (FEAT-389 convention): SQL where columns are
  typed (`form_uid` VARCHAR(36) → UUID retrofit), plus a Python backfill that
  loads every stored schema, injects missing UIDs (deterministic walk), rewrites
  rule references from `field_id` to the resolved UID, and re-saves; reports
  forms with pre-existing duplicate `field_id`s for manual repair.

### Edge Cases & Error Handling

- **Client-supplied duplicate UID** (within form, or colliding on upsert): 400
  with the offending UID and both element paths.
- **Duplicate `field_id` in a stored/legacy schema** at migration or build-time
  resolution: hard error listing the duplicates (cannot auto-resolve rule
  references ambiguously).
- **Rule referencing unknown `field_id`** at build time: validation error naming
  the rule owner and the missing reference (extends today's
  `validate_rules` messages).
- **Invalid UUID in path/payload**: 400 via the FEAT-389 `extract_form_uid`-style
  helper, generalized for field/section UIDs.
- **update_field patch attempting to change `field_uid`**: rejected (identity is
  immutable) — mirror of today's silent `field_id` pin, but explicit.
- **GROUP `children` / ARRAY `item_template`**: nested fields get UIDs too; the
  uniqueness validator must use the recursive traversal, not
  `iter_all_fields()` (which skips nesting — `core/schema.py:324-327`).
- **Audio WS / Telegram flows**: wire messages keep `field_id` keys (they are
  answer payloads); internal manifests (`AudioQuestion`, `FormStep`) may carry
  both — UID for identity, `field_id` for answer keying.
- **Blob refs written before migration**: old `{form_id}/{field_id}/...` keys
  remain resolvable via stored refs (`_from_ref` parses the ref itself); only
  new writes use the UID pattern. Migration report lists legacy-keyed blobs.

---

## Capabilities

### New Capabilities
- `formdesigner-field-uid`: stable UUID identity (`field_uid`, `section_uid`,
  `subsection_uid`) for all structural form elements, with validation-layer
  uniqueness, UID-addressed edit operations, UID-keyed rules and blob storage,
  build-time `field_id → field_uid` rule resolution, and the `form_uid`
  str → UUID type retrofit.

### Modified Capabilities
- `form-uid-stable-identity` (FEAT-389): `form_uid` type changes `str → uuid.UUID`
  (model, registry keys, storage column, handlers, blob keys).
- `form-designer-edition`: batch operations address fields/sections by UID.
- `formdesigner-conditional-sections`: rule models reference UIDs internally.
- `formdesigner-partial-saves`: internal re-keying of saved answers by UID.
- `new-formdesigner-field-rest` / uploads: upload route param becomes `field_uid`.
- `formdesigner-audio-renderer`: `AudioQuestion`/session manifests carry UID.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `core/schema.py` (`FormField`, `FormSection`, `FormSubsection`, `FormSchema`, `RenderWarning`) | extends/modifies | new UID fields + full-tree uniqueness validator; `form_uid` type retrofit |
| `core/constraints.py` (`FieldCondition`, `DependencyRule`, `DependencyOperation`, `PostDependency`) | modifies | rule references become UID-valued |
| `api/operations.py` | modifies | op payload models, UID lookup replacing `_field_index`/`_check_unique_field_id` |
| `api/handlers.py` (`_find_field`, `save_partial`) | modifies | UID lookup; partial-save re-keying |
| `api/uploads.py` + `api/routes.py:261` | modifies | `{field_id}` path param → `{field_uid}`; UUID validation |
| `api/audio_ws.py` | modifies (light) | internal question lookup by UID; wire keys unchanged |
| `tools/edit_toolkit.py` | modifies | 12 tool methods + `_find_field_and_section` switch to UID |
| `tools/create_form.py` | modifies | prompt contract mentions UIDs are server-minted; build-time resolution after generation |
| `extractors/{yaml,jsonschema,pydantic,tool}.py` | modifies | UID minting + rule-reference resolution pass |
| `services/validators.py` | modifies | uniqueness, rule validation, cycle detection re-keyed on UID |
| `services/rule_evaluator.py` | modifies | `_topo_order`/condition reads resolve UID → `field_id` for answers |
| `services/blob_storage.py` | modifies | `BlobMetadata.field_uid`; `_build_key` uses `form_uid`/`field_uid` |
| `services/partial_saves.py` | modifies | internal UID keying (open question 1) |
| `services/question_bank.py` | modifies (light) | fresh `field_uid` minted on `resolve_ref` insertion |
| `services/storage.py` + `migrations/` | modifies | `form_uid` column type retrofit; JSONB backfill script for element UIDs |
| `services/submissions.py` | modifies (light) | `form_uid` type retrofit only; answer keying unchanged |
| Renderers (`html5`, `adaptive_card`, `jsonschema`, `pdf`, `xforms`, `telegram`, `audio`) | unchanged / light | output names stay `field_id`; optional `data-field-uid` attribute; `RenderWarning` may carry UID |
| `packages/ai-parrot/src/parrot/forms/schema.py` (legacy fallback copy) | decide | already drifted (missing `post_depends` + 10 FormSchema fields) — mirror or drop (open question 3) |
| FEAT-389 artifacts (in-flight) | depends on | this feature branches only after FEAT-389 merges to dev |

**Breaking changes**: yes, by design (pre-production clean break): API payload
shapes for edit operations, upload route, blob key pattern, rule reference
values, `form_uid` JSON type unchanged on the wire (still a UUID string) but
Python type changes.

**New dependencies**: none.

---

## Code Context

### User-Provided Code

_None — user described the change in prose; all references below were verified
in the codebase._

### Verified Codebase References

All paths relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`
unless absolute. Verified 2026-07-31 on `dev` (pre-FEAT-389-merge).

#### Classes & Signatures

```python
# core/schema.py:43-93
class FormField(BaseModel):
    model_config = ConfigDict(extra="forbid")   # :72
    field_id: str                               # :74 — bare str, NO validator/uniqueness
    field_type: FieldType                       # :75
    label: LocalizedString                      # :76
    constraints: FieldConstraints | None = None # :82
    options: list[FieldOption] | None = None    # :83
    depends_on: DependencyRule | None = None    # :85 — pre-depends
    post_depends: list[PostDependency] | None = None  # :86
    children: list[FormField] | None = None     # :87 — GROUP nesting
    item_template: FormField | None = None      # :88 — ARRAY template
    meta: dict[str, Any] | None = None          # :89
FormField.model_rebuild()                       # :93

# core/schema.py:96-121 / :127-159
class FormSubsection(BaseModel):
    subsection_id: str                          # :116
    fields: list[FormField]                     # :119
class FormSection(BaseModel):
    section_id: str                             # :146
    fields: list[SectionItem]                   # :149  (SectionItem = Union[FormField, FormSubsection], :124)
    def iter_fields(self) -> Iterator[FormField]:   # :153 — flattens subsections, NOT children/item_template

# core/schema.py:305-327
class FormSchema(BaseModel):
    form_id: str                                # :305 — NO form_uid yet (lands with FEAT-389)
    version: str = "1.0"                        # :306
    tenant: str | None = None                   # :314
    def iter_all_fields(self) -> Iterator[FormField]:  # :324 — sections+subsections only

# core/schema.py:376-390
class RenderWarning(BaseModel):
    field_id: str                               # :387

# core/constraints.py
class FieldCondition(BaseModel):                # :144-164
    field_id: str                               # :156 — rule reference; source: str = "field" (:163)
class DependencyRule(BaseModel):                # :167-188
    conditions: list[FieldCondition]
    operations: list["DependencyOperation"] | None
class DependencyOperation(BaseModel):           # :191-271
    operands: list[str]                         # :233 — "List of field_id strings"
    target: str                                 # :234
class PostDependency(BaseModel):                # :274+
    target: str                                 # :282 — field_id of later field

# api/operations.py
class RemoveField(_OpBase): section_id: str; field_id: str        # :82-87
class UpdateField(_OpBase): section_id: str; field_id: str; patch: dict[str, Any]  # :90-96
class DuplicateField(_OpBase): from_: dict; as_field_id: str      # :114-119
def _field_index(section: FormSection, field_id: str) -> int      # :178 — SKIPS subsections (:180-181)
def _check_unique_field_id(section: FormSection, field_id: str) -> None  # :187 — per-SECTION only
def _apply_update_field(...)  # :271-283 — merged["field_id"] = op.field_id (:278) silently pins identity
async def handle_operations(request: web.Request) -> web.Response # :358
# route: api/routes.py:255-256 → PATCH {bp}/forms/{form_id}/operations

# api/handlers.py
def _find_field(self, form: FormSchema, field_id: str) -> "FormField | None"  # :284-301
async def save_partial(self, request: web.Request) -> web.Response  # :306 — body {"answers": {field_id: value}}
# :380-385 — unknown field_ids silently accepted/stored

# api/uploads.py — ONLY route with field_id as path param (api/routes.py:261)
# field_id = request.match_info["field_id"] (:233); BlobMetadata(..., field_id=field_id) (:336-342)

# services/validators.py — class FormValidator (:92)
async def validate(self, form, data, *, locale="en", auth_context=None) -> ValidationResult  # :113
#   sanitized[field.field_id] = ... (:168) — submission data keyed by field_id
#   derived key: all_data.get(f"{field.field_id}__mime") (:265)
def validate_rules(self, form: FormSchema) -> list[str]            # :791
#   field_map/{field_order} keyed by field_id (:819-820); ref checks :830-834, :869, :882-886
def check_schema(self, form: FormSchema) -> list[str]              # :959
def _detect_circular_dependencies(self, form) -> list[str]         # :974 — DFS on field_id graph (:1000-1053)
# _collect_fields (:736) / _collect_nested_fields (:753) — the ONLY traversal recursing children/item_template

# services/rule_evaluator.py
# raw = answers.get(condition.field_id) (:124); _topo_order(fields) (:355-410) keyed on field_id;
# on cycle: warns + declaration order (NOT an error) — asymmetric with validators.py DFS

# services/blob_storage.py
class BlobMetadata(BaseModel):   # :55-74 — form_id (:69), field_id (:70), extra="forbid"
def _build_key(self, metadata: BlobMetadata) -> str  # :211-220
#   return f"{self._prefix}{metadata.form_id}/{metadata.field_id}/{blob_id}"  (:220)

# services/partial_saves.py
async def save(self, form_id: str, session_id: str, answers: dict[str, Any]) -> PartialFormData  # :67
def _redis_key(self, form_id: str, session_id: str) -> str  # :174 — field_ids only inside JSON value

# services/question_bank.py — bank's field_id is a MINTED UUID, unrelated to FormField.field_id
class ReusableField(BaseModel):   # :29-48 — field_id: str (:43, bank entry UUID), definition: FormField (:44)
class ReusableFieldRef(BaseModel) # :51-67 — bank_field_id: str (:66)
# DDL :74-85: field_id VARCHAR(255), UNIQUE(field_id, tenant) (:83)
# create_field :176-190 — mints UUID4 regardless of source field's field_id

# services/storage.py — class PostgresFormStorage(FormStorage) (:63) — ZERO field_id refs
# _create_table_sql (:148-163): schema_json JSONB NOT NULL, UNIQUE(form_id, version) (:161)
# _upsert_sql (:165-176): whole-schema JSONB replace

# tools/edit_toolkit.py — class EditToolkit(AbstractToolkit) (:50) — heaviest consumer (69 refs)
def _find_field_and_section(self, field_id: str)  # :111-125 — form-wide lookup
# 12 tool methods take field_id params: get_field(:201), search_fields(:222), update_field(:282),
# add_field(:321), remove_field(:362), add_dependency(:396), update_dependency(:434),
# remove_dependency(:455), add_post_dependency(:474), remove_post_dependency(:512), move_field(:664)

# extractors — field_id derivation
# yaml.py: data["field_id"] (:269) | legacy data["name"] (:274) | dict-key form (:279-284);
#   rule conds: cond.get("field_id", "") (:452, :541) — SILENT empty-string default
# jsonschema.py: field_id=name (:207,:301); array item field_id="item" (:271)
# pydantic.py: field_id=attr name (:185); item (:260)
# tools/create_form.py: LLM generates field_ids per prompt contract (:61,:91-113) — no post-hoc uniqueness pass
```

#### Verified Imports
```python
# Confirmed working (formdesigner package):
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection, RenderWarning
from parrot_formdesigner.core.constraints import DependencyRule, FieldCondition, DependencyOperation, PostDependency
from parrot_formdesigner.services.validators import FormValidator
from parrot_formdesigner.services.blob_storage import BlobMetadata
# parrot.forms (packages/ai-parrot/src/parrot/forms/__init__.py) is a try/except re-export shim:
#   prefers parrot_formdesigner.*, falls back to local legacy copies (.schema etc.)
```

#### Key Attributes & Constants
- `FormField.field_id` → `str` (core/schema.py:74) — no default, no validator
- `FormSection.section_id` → `str` (core/schema.py:146); `FormSubsection.subsection_id` → `str` (:116)
- Blob key pattern → `{prefix}{form_id}/{field_id}/{blob_id}` (services/blob_storage.py:220); FEAT-389 changes form part to `form_uid`
- Derived string-key conventions that reference field_id (all stay on field_id — data-binding surface):
  `{field_id}__mime` (validators.py:265), `{field_id}.answer`/`.blob_ref` (html5.py:1098-1101),
  `{field_id}__arg__{name}` (html5.py:1146), `{field_id}_svg/_png/_start/_end/_file/_available`
  (html5.py:785-786, 900-901, 1093, 860), 11 `{field_id}-*` DOM ids (renderers/fields/audio.py:88-156)
- `tools/services/networkninja.py:868,1009` — synthesizes `field_id = f"field_{col_name}"` from DB columns
- Three inconsistent traversals: `iter_all_fields` (no nesting), `_collect_nested_fields` (full),
  `_field_index` (no subsections) — UID work must standardize on the full recursive one

### Does NOT Exist (Anti-Hallucination)

- ~~`FormSchema.form_uid`~~ — not yet on dev; lands with in-flight FEAT-389 (this feature depends on it)
- ~~`FormField.field_uid` / `section_uid` / `subsection_uid`~~ — do not exist anywhere yet
- ~~`FieldFallback` class~~ — the model at core/schema.py:376-390 is `RenderWarning`; "FallbackRenderer" exists only in prose, not as a class
- ~~duplicate-`field_id` validation in `FormSchema`~~ — none; `core/schema.py:338` builds a *set* only for metadata-key collision; duplicates validate cleanly
- ~~per-field table / per-field columns in `PostgresFormStorage`~~ — fields are embedded `schema_json JSONB`; the only per-field rows are question-bank entries
- ~~`field_id` format validation~~ — `validate_identifier` exists (services/_identifiers.py) but is NOT applied to `FormField.field_id`
- ~~`field_id` usage in `services/registry.py`, `services/rest_field_resolver.py` (as lookup), `api/controls.py`, `api/render.py`, `tools/database_form.py`~~ — zero/lookup-free
- ~~`field_id` as path param on the operations endpoint~~ — operations carry it in the body; only the upload route has `{field_id}` in path (api/routes.py:261)
- ~~legacy `parrot/forms/schema.py` parity~~ — legacy FormField lacks `post_depends`; legacy FormSchema lacks 8+ fields, `iter_all_fields`, `_validate_metadata`; no `RenderWarning` there

---

## Parallelism Assessment

- **Internal parallelism**: Low. The model change (`core/schema.py`,
  `core/constraints.py`) is the root of a dependency chain; operations/toolkit,
  validators/evaluator, storage/migrations, and uploads/blob all depend on it.
  After the model+validator tasks land, the consumer groups (edit surface, rules
  engine, blob/uploads, extractors, migrations) are mutually independent and
  could proceed in parallel *within one worktree* as sequential tasks.
- **Cross-feature independence**: **Conflicts with FEAT-389** (in-flight) on
  `core/schema.py`, `services/storage.py`, `services/blob_storage.py`,
  `api/routes.py`, `api/handlers.py`, `services/submissions.py`, tests. By
  decision, this feature **starts only after FEAT-389 merges to dev** — do not
  create the worktree before that. Also touches `tools/edit_toolkit.py` and
  `api/operations.py` (form-designer-edition surface) — check no other
  in-flight spec targets them at start time.
- **Recommended isolation**: `per-spec` (single worktree, sequential tasks).
- **Rationale**: every task transitively depends on the model change; splitting
  across worktrees would serialize on merges anyway. The FEAT-389 ordering
  constraint is the only hard external gate.

---

## Open Questions

- [ ] Partial saves: confirm wire payload stays `{field_id: value}` with internal
      re-key to `field_uid` in Redis values (rename-proof), vs. keeping storage
      on `field_id` and accepting orphaned answers on rename — *Owner: Jesus*
- [ ] Should renderers emit `data-field-uid` attributes (HTML5/audio) and should
      `RenderWarning` carry `field_uid` alongside `field_id`, or stay
      `field_id`-only? — *Owner: Jesus*
- [ ] Legacy fallback copy `packages/ai-parrot/src/parrot/forms/schema.py`
      (already drifted: missing `post_depends`, 10 FormSchema fields): mirror
      the UID change, or delete the fallback branch of the shim entirely?
      — *Owner: Jesus*
- [ ] Question bank column `field_id` (a minted bank UUID, NOT a
      FormField.field_id) — rename to `bank_field_id` in this clean break to
      kill the naming collision, or leave as-is? — *Owner: Jesus*
- [ ] Audio WS wire protocol: keep `field_id` keys in WS messages (answer
      payload semantics) with UID only in internal manifests — confirm.
      — *Owner: Jesus*
- [x] Do sections/subsections get UIDs too? — *Owner: Jesus*: yes — all three
      levels (`field_uid`, `section_uid`, `subsection_uid`) in this feature.
- [x] Where does the `form_uid` str → UUID retrofit land? — *Owner: Jesus*:
      as the first task of THIS spec; FEAT-389 merges as specced (`str`).
- [x] How are rule references authored vs stored? — *Owner: Jesus*: authored by
      `field_id`, resolved to `field_uid` at build time; ambiguity = error.
- [x] Question-bank insertions? — *Owner: Jesus*: mint a fresh `field_uid` per
      insertion.
