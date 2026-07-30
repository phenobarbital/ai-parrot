---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Stable UUID-Based Field Identity (field_uid)

**Feature ID**: FEAT-393
**Date**: 2026-07-31
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.next
**Brainstorm**: `sdd/proposals/formdesigner-field-uid.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

`FormField.field_id` is a bare, human-editable `str`
(`parrot_formdesigner/core/schema.py:74`) that serves simultaneously as the
identity of a field for the edit/design surface, the reference key of
conditional rules, a durable external key (blob storage object paths embed it
at `services/blob_storage.py:220`), and the data-binding key of submissions and
renderer output.

There is **no uniqueness warranty anywhere**: `field_id` has no format
validation, no model-level duplicate check (the set at `core/schema.py:338`
exists only for metadata-key collision), and edit-time uniqueness is checked
per section only (`api/operations.py:187`) with a traversal that disagrees with
the lookup traversal in the same module. A `FormSchema` with two identical
`field_id`s validates cleanly; renaming a `field_id` silently orphans
previously uploaded blobs and breaks rule references.

FEAT-389 (`sdd/specs/form-uid-stable-identity.spec.md`) fixes the same disease
at the form level with `form_uid` and explicitly declares FormField out of
scope. This feature is its sequel: give every structural element of a form —
field, section, subsection — a stable, auto-generated, immutable UUID identity
and move every internal reference onto it. FormDesigner is not in production;
a clean break without backward compatibility is approved (same posture as
FEAT-389).

### Goals

- Add `field_uid`, `section_uid`, `subsection_uid` (`uuid.UUID`, upsert-style:
  client-provided value accepted and validated, otherwise auto-generated;
  immutable once assigned) to `FormField`, `FormSection`, `FormSubsection`.
- Retrofit FEAT-389's `form_uid` from `str` to `uuid.UUID` so both identities
  share one type (first module of this spec — FEAT-389 merges as specced).
- Keep `field_id` (and `section_id`/`subsection_id`) as the human-editable
  name/key: data-binding key for submission payloads, renderer control names,
  prefill/error maps, and rule *authoring*.
- Enforce, at the validation layer, per-form uniqueness of all UIDs **and** of
  `field_id`, over the **full** field tree (sections → subsections → fields →
  `children` → `item_template`). Global uniqueness rests on uuid4
  collision-negligibility; no per-field DB table.
- Address all edit/design operations (`api/operations.py`, `EditToolkit`) by
  UID; renaming `field_id` becomes a legal patch.
- Switch internal references to `field_uid`: conditional rules
  (`FieldCondition`, `DependencyOperation`, `PostDependency`), cycle
  detection, rule evaluation graphs, blob storage keys, upload route param,
  partial-save internal keying, audio session manifests.
- Rules remain authored by `field_id` (humans, YAML, LLM); references are
  resolved to `field_uid` at build time; unknown or duplicate `field_id` at
  resolution time is a validation error.
- Rename the question bank's unrelated `field_id` identifier to `question_id`
  end to end (model, ref, DDL, SQL, params); mint a fresh `field_uid` on every
  bank-entry insertion into a form.
- Renderers emit `data-field-uid` attributes (HTML5/audio) and `RenderWarning`
  carries `field_uid` alongside `field_id`; control names stay `field_id`.
- Drop the drifted legacy fallback copy in
  `packages/ai-parrot/src/parrot/forms/` — the `parrot.forms` shim re-exports
  from `parrot_formdesigner` only and raises a clear `ImportError` if absent.
- Idempotent migrations: `form_uid` column type retrofit, JSONB backfill of
  element UIDs + rule-reference rewrite, question-bank column rename.

### Non-Goals (explicitly out of scope)

- **Per-field DB table / DB-enforced uniqueness** — rejected in brainstorm
  (Option B, see `proposals/formdesigner-field-uid.brainstorm.md`); fields
  stay embedded in `schema_json` JSONB.
- **Making `field_id` immutable or validated as the sole identifier** —
  rejected in brainstorm (Option C).
- **Backward compatibility**: no dual routing, no deprecation shims, no
  compat payloads (clean break, pre-production).
- **Changing submission payload keying** — `FormValidator.validate` output and
  `form_data.data` JSONB stay keyed by `field_id`.
- **Changing renderer control names** — HTML `id`/`name`, AcroForm widget
  names, JSON-Schema property names, XForms element names stay `field_id`.
- **Audio WS / Telegram wire protocols** — answer messages keep `field_id`
  keys (payload semantics); only internal manifests gain UIDs.
- **Question-bank method renames** — `get_field`, `create_field`,
  `list_fields`, `increment_usage` keep their names; only the identifier
  field/column/params rename to `question_id`.
- **Versioning semantics** — unchanged; UIDs are stable across versions of
  the same form.
- FEAT-389 itself — this spec depends on it but does not modify its scope
  beyond the type retrofit.

---

## 2. Architectural Design

### Overview

Mirror FEAT-389's approved pattern one level down (brainstorm Option A). Every
structural element gains a `uuid.UUID` identity with
`Field(default_factory=uuid4)` — client-supplied values are accepted
(upsert-style) and validated; a `FormSchema` model validator walks the full
recursive field tree and rejects duplicate UIDs and duplicate `field_id`s.
`form_uid` is retrofitted to `uuid.UUID` first so all identity fields share
one type (Pydantic serializes UUID → str on the wire; JSON payload shape is
unchanged).

Identity and naming are split: UIDs are immutable identity for machines
(edit operations, rule references, blob keys, internal maps); the `*_id`
slugs remain editable names for humans and data binding (submission payloads,
renderer control names, rule authoring). A build-time resolution pass converts
authored `field_id` rule references into `field_uid` references whenever a
schema is assembled (extractors, CreateFormTool, blank-form/edit APIs),
erroring on unknown or ambiguous references — which finally forces per-form
`field_id` uniqueness at every build boundary.

Storage stays document-shaped: fields remain embedded in
`form_schemas.schema_json`; migrations backfill UIDs into stored documents and
rewrite stored rule references. The question bank's colliding `field_id`
identifier (a minted bank UUID unrelated to `FormField.field_id`) is renamed
`question_id`. The drifted legacy copy of the form models in
`packages/ai-parrot/src/parrot/forms/` is deleted; the `parrot.forms` shim
becomes a thin re-export of `parrot_formdesigner`.

### Component Diagram

```
FormSchema (form_uid: UUID ← retrofit)
  ├── FormSection (section_uid: UUID, section_id: slug)
  │     ├── FormField (field_uid: UUID, field_id: editable key)
  │     │     ├── children: [FormField (field_uid…)]        ← GROUP
  │     │     └── item_template: FormField (field_uid…)     ← ARRAY
  │     └── FormSubsection (subsection_uid: UUID)
  │           └── fields: [FormField (field_uid…)]
  │
  ├── model validator: full-tree duplicate check (UIDs + field_id)
  │
  ├── Rules (internal = field_uid): FieldCondition.field_uid,
  │     DependencyOperation.operands/target, PostDependency.target
  │     ▲ build-time resolution: authored field_id ──→ field_uid
  │       (extractors, CreateFormTool, assembly boundary)
  │
  ├── Edit surface (address by UID): api/operations.py ops,
  │     EditToolkit tools, unified recursive lookup
  │
  ├── Blob keys: {prefix}{form_uid}/{field_uid}/{blob_uuid}
  │     upload route: POST /forms/{form_uid}/fields/{field_uid}/upload
  │
  ├── Partial saves: wire {field_id: value} ⇄ Redis {field_uid: value}
  │
  ├── Rule evaluator / validators: graphs keyed by field_uid,
  │     answers read via field_uid → field_id mapping
  │
  └── Renderers: control names stay field_id; + data-field-uid attr;
        RenderWarning(field_id, field_uid)

QuestionBank: ReusableField.question_id (renamed), definition: FormField
  └── resolve_ref() → fresh field_uid minted per insertion
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `core/schema.py` (`FormField`, `FormSection`, `FormSubsection`, `FormSchema`, `RenderWarning`) | extends/modifies | new UID fields + full-tree uniqueness validator; `form_uid` type retrofit; `RenderWarning.field_uid` |
| `core/constraints.py` (`FieldCondition`, `DependencyOperation`, `PostDependency`) | modifies | rule references become UID-valued (`field_uid` / UID-string operands & target) |
| `api/operations.py` | modifies | op payload models address by UID; one form-wide recursive lookup replaces `_field_index` + `_check_unique_field_id` |
| `api/handlers.py` (`_find_field`, `save_partial`) | modifies | UID lookup; partial-save wire↔storage re-keying |
| `api/uploads.py` + `api/routes.py` | modifies | `{field_id}` path param → `{field_uid}` with UUID validation (400/404) |
| `api/audio_ws.py` | modifies (light) | internal question lookup by UID; WS wire keys stay `field_id` |
| `tools/edit_toolkit.py` | modifies | 12 tool methods + `_find_field_and_section` switch to UID params; `search_fields` still matches `field_id`/label, returns UIDs |
| `tools/create_form.py` | modifies | prompt contract: UIDs are server-minted; resolution pass after generation |
| `extractors/{yaml,jsonschema,pydantic,tool}.py` | modifies | UID minting + rule-reference resolution pass at extraction |
| `services/validators.py` | modifies | uniqueness, `validate_rules`, cycle detection re-keyed on UID |
| `services/rule_evaluator.py` | modifies | `_topo_order`/condition reads resolve UID → `field_id` for `answers` |
| `services/blob_storage.py` | modifies | `BlobMetadata.field_uid`; `_build_key` uses `form_uid`/`field_uid` |
| `services/partial_saves.py` | modifies | Redis values keyed by `field_uid`; wire stays `field_id` |
| `services/question_bank.py` | modifies | `field_id` → `question_id` (model, `ReusableFieldRef.bank_field_id` → `question_id`, DDL + UNIQUE, SQL, params, in-memory keys); fresh `field_uid` in `resolve_ref` |
| `services/storage.py` + `migrations/` | modifies | `form_uid` column type retrofit; JSONB UID backfill + rule rewrite; question-bank column rename |
| `services/submissions.py` | modifies (light) | `form_uid` type retrofit only; answer keying unchanged |
| Renderers (`html5`, `adaptive_card`, `pdf`, `jsonschema`, `xforms`, `telegram`, `audio`) | modifies (light) | `data-field-uid` attributes (HTML5/audio); `RenderWarning.field_uid`; control names unchanged |
| `packages/ai-parrot/src/parrot/forms/` | removes | legacy fallback copies deleted; shim re-exports `parrot_formdesigner` only, clear `ImportError` otherwise |
| FEAT-389 artifacts | depends on | **hard gate: FEAT-389 must be merged to `dev` before the worktree is created** |

### Data Models

```python
import uuid
from pydantic import Field

class FormField(BaseModel):
    field_uid: uuid.UUID = Field(default_factory=uuid.uuid4)  # NEW — immutable identity
    field_id: str          # kept — editable name / data-binding key
    # ... rest unchanged (field_type, label, constraints, options,
    #     depends_on, post_depends, children, item_template, meta)

class FormSubsection(BaseModel):
    subsection_uid: uuid.UUID = Field(default_factory=uuid.uuid4)  # NEW
    subsection_id: str
    # ... rest unchanged

class FormSection(BaseModel):
    section_uid: uuid.UUID = Field(default_factory=uuid.uuid4)  # NEW
    section_id: str
    # ... rest unchanged

class FormSchema(BaseModel):
    form_uid: uuid.UUID = Field(default_factory=uuid.uuid4)  # RETROFIT: was str (FEAT-389)
    form_id: str           # slug, mutable
    # NEW model validator: full-tree walk (children + item_template included)
    # rejects duplicate field_uid/section_uid/subsection_uid AND duplicate field_id

class FieldCondition(BaseModel):
    field_uid: uuid.UUID | None = None  # internal reference (source="field")
    # authored field_id accepted at build boundaries, resolved before storage;
    # source="location_variable"/"visit_context" entries have no field reference (key-based)

class DependencyOperation(BaseModel):
    operands: list[str]    # UID strings after resolution
    target: str            # UID string after resolution

class PostDependency(BaseModel):
    target: str            # UID string after resolution

class RenderWarning(BaseModel):
    field_id: str
    field_uid: uuid.UUID | None = None  # NEW

class BlobMetadata(BaseModel):
    form_uid: uuid.UUID    # RETROFIT type
    field_uid: uuid.UUID   # NEW — key construction
    field_id: str          # kept as descriptive metadata

class ReusableField(BaseModel):        # question bank
    question_id: str       # RENAMED from field_id (minted UUID string, bank identity)
    definition: FormField  # gains field_uid like any FormField

class ReusableFieldRef(BaseModel):
    question_id: str       # RENAMED from bank_field_id
    overrides: dict[str, Any] | None = None
```

### New Public Interfaces

```python
# Build-time rule-reference resolution (shared by extractors / CreateFormTool /
# blank-form and edit APIs; natural home alongside the FEAT-389 assembly boundary)
def resolve_rule_references(form: FormSchema) -> FormSchema:
    """Rewrite authored field_id rule references to field_uid.

    Raises ValueError naming the rule owner and the missing/ambiguous
    field_id when resolution fails.
    """

# Unified recursive lookup (replaces api/operations.py:_field_index and
# EditToolkit._find_field_and_section's traversal)
def find_field_by_uid(form: FormSchema, field_uid: uuid.UUID) -> tuple[FormField, FormSection] | None:
    """Form-wide, subsection- and nesting-aware field lookup by UID."""

# UUID path-param validation (generalizes FEAT-389's extract_form_uid)
def extract_uid(request: web.Request, param: str) -> uuid.UUID:
    """Extract and validate a UUID path param. Raises HTTPBadRequest if invalid."""

# Rule evaluator answer access
def resolve_answer(form: FormSchema, field_uid: uuid.UUID, answers: dict[str, Any]) -> Any:
    """Read an answer value for a UID-referenced field from a field_id-keyed answers dict."""
```

Edit-operation payloads (clean break — `field_id` params replaced):

```python
class RemoveField(_OpBase):
    section_uid: uuid.UUID
    field_uid: uuid.UUID

class UpdateField(_OpBase):
    section_uid: uuid.UUID
    field_uid: uuid.UUID
    patch: dict[str, Any]      # may change field_id; may NOT change field_uid (400)

class MoveField(_OpBase):
    from_: dict  # {"section_uid": ..., "field_uid": ...}
    to: dict     # {"section_uid": ..., "position": ...}

class DuplicateField(_OpBase):
    from_: dict                 # {"section_uid": ..., "field_uid": ...}
    as_field_id: str            # new editable key; fresh field_uid always minted
```

---

## 3. Module Breakdown

### Module 1: form_uid str → UUID retrofit
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`,
  `services/{registry,storage,submissions,blob_storage}.py`, `api/{handlers,routes,operations}.py`,
  `tools/create_form.py`
- **Responsibility**: Convert `FormSchema.form_uid`, `FormSubmission.form_uid`,
  `BlobMetadata.form_uid` from `str` to `uuid.UUID`; registry keys and handler
  helpers (`extract_form_uid`) parse/emit `uuid.UUID`; storage column type
  aligned (Module 14). JSON wire shape unchanged (UUID serializes to str).
- **Depends on**: FEAT-389 merged to dev.

### Module 2: Core model UIDs + full-tree uniqueness validator
- **Path**: `core/schema.py`
- **Responsibility**: Add `field_uid`/`section_uid`/`subsection_uid`
  (`uuid.UUID`, `default_factory=uuid4`). Add a `FormSchema` model validator
  performing one **recursive** traversal (sections → subsections → fields →
  `children` → `item_template` — `_collect_nested_fields` semantics) rejecting
  duplicate UIDs across all three kinds and duplicate `field_id` per form.
  Add `RenderWarning.field_uid: uuid.UUID | None`. Expose the canonical
  recursive traversal as a public helper so operations/toolkit/validators stop
  maintaining three divergent walks.
- **Depends on**: Module 1.

### Module 3: Rule models + build-time resolution pass
- **Path**: `core/constraints.py`, new `core/resolution.py` (or the FEAT-389
  assembly module if one landed — verify at task time)
- **Responsibility**: `FieldCondition` carries `field_uid` for
  `source="field"`; `DependencyOperation.operands`/`target` and
  `PostDependency.target` hold UID strings. `resolve_rule_references()`
  rewrites authored `field_id` references to UIDs; unknown/ambiguous
  reference → `ValueError` naming rule owner and reference. Empty-string
  condition references (today silently produced by the YAML extractor) become
  errors.
- **Depends on**: Module 2.

### Module 4: Validators + rule evaluator re-keying
- **Path**: `services/validators.py`, `services/rule_evaluator.py`
- **Responsibility**: `validate_rules`, `_validate_operation`,
  `_detect_circular_dependencies` build `field_map`/`field_order`/graphs keyed
  by UID; `RuleEvaluator._topo_order` likewise; condition/answer reads resolve
  UID → field → `field_id` against the `answers` dict (which stays
  `field_id`-keyed). Result maps (`visible`, `required`, `computed`,
  `cleared`) stay keyed by `field_id` (they feed renderers/clients).
  `FormValidator.validate` output (sanitized data, errors) unchanged.
- **Depends on**: Module 3.

### Module 5: Edit operations API — UID addressing
- **Path**: `api/operations.py`
- **Responsibility**: Op models per §2 (UID targets). Replace `_field_index`
  (skips subsections) and `_check_unique_field_id` (per-section) with the
  Module 2 canonical lookup + per-form checks. `update_field` allows
  `field_id` renames, rejects `field_uid` changes (explicit error, not silent
  pin). `duplicate_field` mints a fresh `field_uid`. `add_field` accepts an
  optional client-supplied `field_uid` (upsert-style), rejecting duplicates.
  Section-level ops address by `section_uid`.
- **Depends on**: Module 2, Module 3 (rules revalidation on edit).

### Module 6: EditToolkit — UID params
- **Path**: `tools/edit_toolkit.py`
- **Responsibility**: `_find_field_and_section` and the 12 tool methods take
  UID params; `search_fields` keeps matching `field_id`/label (LLM ergonomics)
  and returns UIDs; `get_form_summary` emits both `field_uid` and `field_id`.
  Dependency tools (`add_dependency`, `add_post_dependency`, …) accept
  authored `field_id` references and route through the resolution pass.
- **Depends on**: Module 5.

### Module 7: Extractors + CreateFormTool
- **Path**: `extractors/{yaml,jsonschema,pydantic,tool}.py`, `tools/create_form.py`
- **Responsibility**: Extractors mint UIDs (model default suffices) and run
  `resolve_rule_references()` before returning a schema; YAML extractor's
  silent `field_id=""` condition default becomes an error. CreateFormTool:
  LLM keeps generating `field_id`-referenced rules; post-generation pass
  resolves references and enforces per-form `field_id` uniqueness with a
  retry-visible error message; prompt contract documents that UIDs are
  server-minted (clients/LLM never invent them).
- **Depends on**: Module 3.

### Module 8: Blob storage + upload route
- **Path**: `services/blob_storage.py`, `api/uploads.py`, `api/routes.py`
- **Responsibility**: `BlobMetadata.field_uid` (UUID) added, `field_id` kept
  as descriptive metadata; `_build_key` →
  `{prefix}{form_uid}/{field_uid}/{blob_id}`; `_from_ref` parses the new
  pattern (old refs remain resolvable as opaque stored refs). Upload route
  `POST /forms/{form_uid}/fields/{field_uid}/upload` with `extract_uid`
  validation (400 invalid UUID, 404 unknown field). `RestCallbackInput`
  passthrough gains `field_uid`, keeps `field_id`.
- **Depends on**: Module 2.

### Module 9: Partial saves — internal re-keying
- **Path**: `services/partial_saves.py`, `api/handlers.py` (`save_partial`)
- **Responsibility**: Wire payload stays `{"answers": {field_id: value}}`.
  On save: resolve each `field_id` to `field_uid` (unknown `field_id` →
  rejected with a field error, replacing today's silent acceptance at
  `api/handlers.py:380-385`) and persist Redis values keyed by `field_uid`.
  On read: map back to current `field_id`s. Renames mid-session no longer
  orphan answers.
- **Depends on**: Module 2.

### Module 10: Audio session manifests
- **Path**: `renderers/audio.py`, `audio/models.py`, `api/audio_ws.py`
- **Responsibility**: `AudioQuestion.field_uid` + `AudioAnswer.field_uid`
  added; WS wire messages keep `field_id` keys (payload semantics); internal
  lookups (`_question_for_field`, turn-order gate) may resolve via UID but the
  client contract is unchanged.
- **Depends on**: Module 2.

### Module 11: Renderers — data-field-uid + RenderWarning
- **Path**: `renderers/html5.py`, `renderers/fields/audio.py`,
  `renderers/{adaptive_card,pdf,jsonschema,xforms,telegram/}`
- **Responsibility**: HTML5 and audio field templates emit
  `data-field-uid="{field_uid}"` alongside existing `data-field-id`; all
  `RenderWarning` emissions include `field_uid`. Control names/ids, AcroForm
  names, JSON-Schema property keys, XForms element names, Telegram callback
  encoding: **unchanged** (`field_id`).
- **Depends on**: Module 2.

### Module 12: Question bank — question_id rename + fresh field_uid
- **Path**: `services/question_bank.py`
- **Responsibility**: Rename `ReusableField.field_id` → `question_id` and
  `ReusableFieldRef.bank_field_id` → `question_id`; DDL column + 
  `UNIQUE(question_id, tenant)`; `_INSERT_SQL`/`_SELECT_SQL`/`_SELECT_ALL_SQL`/
  `_INCREMENT_SQL`; method params and in-memory fallback keys. Method NAMES
  unchanged. `resolve_ref()` mints a fresh `field_uid` on the returned
  `FormField` (bank definitions are templates; same question in two forms =
  two field identities).
- **Depends on**: Module 2.

### Module 13: Legacy fallback removal (parrot.forms shim)
- **Path**: `packages/ai-parrot/src/parrot/forms/`
- **Responsibility**: Delete the drifted local copies (`schema.py`,
  `constraints.py`, `options.py`, `style.py`, `types.py`, `validators.py`,
  `registry.py`, `cache.py`, `storage.py`, `extractors/`, `renderers/`,
  `tools/`); `__init__.py` re-exports from `parrot_formdesigner.*` only and
  raises a clear `ImportError` ("install parrot-formdesigner") when the
  package is absent. Audit ai-parrot core for imports relying on the fallback
  branch.
- **Depends on**: Module 2 (so re-exported models already carry UIDs).

### Module 14: Migrations
- **Path**: `packages/parrot-formdesigner/migrations/`
- **Responsibility**: Following FEAT-389's numbered, idempotent convention:
  (a) SQL — `form_schemas.form_uid` (and `form_data.form_uid`) column type
  `VARCHAR(36)` → `UUID` (`USING form_uid::uuid`);
  (b) SQL — `question_bank` column rename `field_id` → `question_id` +
  constraint rename (guarded for re-run);
  (c) Python — load every stored `schema_json`, inject missing
  `field_uid`/`section_uid`/`subsection_uid` (deterministic walk), rewrite
  stored rule references `field_id` → resolved UID, re-save; report forms with
  pre-existing duplicate `field_id`s (manual repair) and blobs still on legacy
  key patterns.
- **Depends on**: Modules 1–3, 12.

### Module 15: Tests
- **Path**: `packages/parrot-formdesigner/tests/`, `packages/ai-parrot/tests/unit/forms/`
- **Responsibility**: Update fixtures/helpers for UID fields; new tests per
  §4; migrate or delete `packages/ai-parrot/tests/unit/forms/` tests that
  exercised the deleted legacy copies.
- **Depends on**: Modules 1–14.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_form_uid_is_uuid_type` | 1 | `FormSchema.form_uid` is `uuid.UUID`; JSON round-trip serializes to canonical string |
| `test_field_uid_auto_generated` | 2 | `FormField` without `field_uid` gets a uuid4 |
| `test_field_uid_client_supplied_accepted` | 2 | Valid client UUID preserved (upsert origin) |
| `test_duplicate_field_uid_rejected` | 2 | Two fields sharing a UID → ValidationError |
| `test_duplicate_field_id_rejected` | 2 | Two fields sharing `field_id` → ValidationError (new guarantee) |
| `test_uniqueness_covers_nested_fields` | 2 | Duplicates hidden in `children`/`item_template`/subsections are caught |
| `test_section_subsection_uids` | 2 | `section_uid`/`subsection_uid` generated and unique |
| `test_resolve_rule_references_rewrites` | 3 | Authored `field_id` conditions/operands/targets become UIDs |
| `test_resolve_unknown_reference_errors` | 3 | Missing `field_id` reference → error naming owner + reference |
| `test_resolve_empty_condition_errors` | 3 | YAML `field_id=""` condition no longer silent |
| `test_cycle_detection_uid_keyed` | 4 | `_detect_circular_dependencies` finds cycles through UID refs |
| `test_rule_evaluator_reads_answers_via_uid` | 4 | UID-referenced condition reads `answers[field_id]` correctly |
| `test_update_field_allows_field_id_rename` | 5 | Patch changing `field_id` succeeds; rules keep working (UID refs) |
| `test_update_field_rejects_field_uid_change` | 5 | Patch touching `field_uid` → explicit 4xx error |
| `test_operations_reach_subsection_fields` | 5 | UID lookup addresses a field inside a subsection (old `_field_index` bug) |
| `test_duplicate_field_mints_fresh_uid` | 5 | `duplicate_field` result has new `field_uid` |
| `test_edit_toolkit_uid_params` | 6 | `get_field`/`update_field`/`remove_field` by UID; `search_fields` matches by `field_id`, returns UID |
| `test_extractors_produce_resolved_rules` | 7 | YAML/JSON-Schema/Pydantic extractor outputs have UID-resolved rules |
| `test_create_form_duplicate_field_id_errors` | 7 | LLM output with duplicate `field_id` → retry-visible error |
| `test_blob_key_uses_uids` | 8 | `_build_key` → `{prefix}{form_uid}/{field_uid}/{blob_id}` |
| `test_upload_route_uid_validation` | 8 | invalid UUID → 400; unknown `field_uid` → 404 |
| `test_partial_save_rekeyed_by_uid` | 9 | Redis value keyed by UID; read maps back to current `field_id` |
| `test_partial_save_survives_rename` | 9 | Save → rename `field_id` → read returns answer under new key |
| `test_partial_save_unknown_field_rejected` | 9 | Unknown `field_id` in answers → field error (silent-accept removed) |
| `test_audio_question_carries_uid` | 10 | `AudioQuestion.field_uid` populated; WS wire keys stay `field_id` |
| `test_html5_data_field_uid_attr` | 11 | Rendered control includes `data-field-uid`; `name` stays `field_id` |
| `test_render_warning_field_uid` | 11 | Fallback warnings carry both identifiers |
| `test_question_bank_question_id` | 12 | Model/DDL/SQL use `question_id`; `UNIQUE(question_id, tenant)` |
| `test_resolve_ref_mints_fresh_field_uid` | 12 | Two insertions of one bank entry → two distinct `field_uid`s |
| `test_parrot_forms_shim_reexports` | 13 | `from parrot.forms import FormField` is `parrot_formdesigner`'s class; absent package → clear ImportError |
| `test_migration_backfill_idempotent` | 14 | Running the JSONB backfill twice yields identical documents |
| `test_migration_reports_duplicates` | 14 | Stored schema with duplicate `field_id` → reported, not silently mangled |

### Integration Tests

| Test | Description |
|---|---|
| `test_edit_flow_rename_stability` | Create form → upload blob → rename `field_id` via operations → blob still reachable, rules still evaluate, partial save survives |
| `test_llm_create_edit_roundtrip` | CreateFormTool generates form → EditToolkit edits by UID → validate → store → reload → UIDs stable |
| `test_migration_end_to_end` | Legacy-shaped stored form (no UIDs, `field_id` rules) → migration → loads clean, rules resolved, re-run is a no-op |

### Test Data / Fixtures

```python
@pytest.fixture
def form_with_nested_fields():
    """FormSchema with sections, a subsection, a GROUP (children) and an
    ARRAY (item_template) — exercises the full-tree traversal."""

@pytest.fixture
def form_with_rules():
    """FormSchema whose depends_on / post_depends / operations reference
    fields by authored field_id, for resolution-pass tests."""

@pytest.fixture
def legacy_schema_json():
    """Stored-form JSON WITHOUT uid fields and WITH field_id-keyed rules,
    for migration tests."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All identity fields (`form_uid`, `field_uid`, `section_uid`,
  `subsection_uid`) are `uuid.UUID` with `default_factory=uuid4`; client-supplied
  values accepted and validated (upsert origin).
- [ ] A `FormSchema` with duplicate UIDs **or** duplicate `field_id`s anywhere
  in the full tree (including `children`/`item_template`) fails validation.
- [ ] All edit operations and EditToolkit tools address fields/sections by UID;
  `field_id` rename via patch succeeds; `field_uid` change via patch is
  explicitly rejected; fields inside subsections are addressable.
- [ ] Rule references (`FieldCondition`, `DependencyOperation.operands/target`,
  `PostDependency.target`) are stored as UIDs; authored `field_id` references
  resolve at every build boundary; unknown/ambiguous/empty references error.
- [ ] Blob keys follow `{prefix}{form_uid}/{field_uid}/{blob_id}`; upload route
  is `/forms/{form_uid}/fields/{field_uid}/upload` with 400/404 UUID handling.
- [ ] Partial saves persist UID-keyed, accept/return `field_id`-keyed wire
  payloads, survive renames, and reject unknown `field_id`s.
- [ ] Submission payloads, sanitized data, renderer control names, audio-WS and
  Telegram wire messages remain keyed by `field_id` (no client-facing change
  for form fillers).
- [ ] HTML5/audio renderers emit `data-field-uid`; `RenderWarning` carries
  `field_uid`.
- [ ] Question bank uses `question_id` end to end (model, ref, DDL, SQL,
  params); `resolve_ref` mints a fresh `field_uid` per insertion.
- [ ] Legacy `parrot/forms` local copies are deleted; the shim re-exports
  `parrot_formdesigner` with a clear `ImportError` fallback; ai-parrot test
  suite passes without the copies.
- [ ] Migrations are idempotent (re-run = no-op) and report pre-existing
  duplicate `field_id`s and legacy blob keys instead of silently mangling.
- [ ] All unit tests pass (`pytest packages/parrot-formdesigner/tests/ -v`)
  and the ai-parrot suite passes (`pytest packages/ai-parrot/tests/ -v`).
- [ ] No new external dependencies.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-07-31 on `dev` at `94d8fc543` (pre-FEAT-389-merge; Module 1
> anchors marked accordingly). Line numbers spot-re-checked after the last
> `dev` pull. Implementation agents MUST re-verify FEAT-389-touched files
> once it merges — those anchors WILL shift.

### Verified Imports

```python
# Confirmed working (formdesigner package):
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection, RenderWarning
from parrot_formdesigner.core.constraints import DependencyRule, FieldCondition, DependencyOperation, PostDependency
from parrot_formdesigner.services.validators import FormValidator
from parrot_formdesigner.services.blob_storage import BlobMetadata
from parrot_formdesigner.services.question_bank import ReusableField, ReusableFieldRef

# parrot.forms (packages/ai-parrot/src/parrot/forms/__init__.py) is a
# try/except re-export shim: prefers parrot_formdesigner.*, falls back to
# local legacy copies. Module 13 deletes the fallback branch.
```

### Existing Class Signatures

All paths relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`.

```python
# core/schema.py
class FormField(BaseModel):                     # :43-93
    model_config = ConfigDict(extra="forbid")   # :72
    field_id: str                               # :74 — bare str, NO validator/uniqueness
    depends_on: DependencyRule | None = None    # :85
    post_depends: list[PostDependency] | None   # :86
    children: list[FormField] | None            # :87 — GROUP nesting
    item_template: FormField | None             # :88 — ARRAY template
FormField.model_rebuild()                       # :93 — keep after adding fields

class FormSubsection(BaseModel):                # :96-121
    subsection_id: str                          # :116
class FormSection(BaseModel):                   # :127-159
    section_id: str                             # :146
    fields: list[SectionItem]                   # :149 (SectionItem = Union[FormField, FormSubsection], :124)
    def iter_fields(self) -> Iterator[FormField]  # :153 — flattens subsections, NOT children/item_template

class FormSchema(BaseModel):                    # :~260-373
    form_id: str                                # :305 — NO form_uid on dev yet (FEAT-389)
    version: str = "1.0"                        # :306
    tenant: str | None = None                   # :314
    def iter_all_fields(self) -> Iterator[FormField]  # :324 — sections+subsections only
    # _validate_metadata (:329-373) — metadata-key collision ONLY, not duplicate field_id

class RenderWarning(BaseModel):                 # :376-390
    field_id: str                               # :387

# core/constraints.py
class FieldCondition(BaseModel):                # :144-164
    field_id: str                               # :156; source: str = "field" (:163)
    # deliberately NO extra="forbid" (:153-154) — preserve when adding field_uid
class DependencyRule(BaseModel):                # :167-188
class DependencyOperation(BaseModel):           # :191-271
    operands: list[str]                         # :233
    target: str                                 # :234
    # _non_empty_operands (:237-253), _non_empty_target (:255-271) — shape-only
class PostDependency(BaseModel):                # :274+
    target: str                                 # :282

# api/operations.py
class RemoveField(_OpBase): section_id: str; field_id: str          # :82-87
class UpdateField(_OpBase): section_id: str; field_id: str; patch: dict[str, Any]  # :90-96
class DuplicateField(_OpBase): from_: dict; as_field_id: str        # :114-119
def _field_index(section: FormSection, field_id: str) -> int        # :178 — SKIPS subsections (:180-181)
def _check_unique_field_id(section: FormSection, field_id: str) -> None  # :187 — per-SECTION only
# _apply_update_field :271-283 — merged["field_id"] = op.field_id (:278) silent identity pin
async def handle_operations(request: web.Request) -> web.Response   # :358
# route: api/routes.py:255-256 → PATCH {bp}/forms/{form_id}/operations (field_id in BODY, not path)

# api/handlers.py
def _find_field(self, form: FormSchema, field_id: str) -> "FormField | None"  # :284-301
async def save_partial(self, request: web.Request) -> web.Response  # :306
# :380-385 — unknown field_ids silently accepted/stored (Module 9 removes this)

# api/uploads.py — the ONLY route with {field_id} in path (api/routes.py:261)
# field_id = request.match_info["field_id"] (:233); BlobMetadata(..., field_id=field_id) (:336-342)

# services/validators.py — class FormValidator (:92)
async def validate(self, form, data, *, locale="en", auth_context=None) -> ValidationResult  # :113
#   sanitized[field.field_id] = ... (:168) — submission data keyed by field_id (STAYS)
#   derived key: all_data.get(f"{field.field_id}__mime") (:265) — STAYS on field_id
def validate_rules(self, form: FormSchema) -> list[str]             # :791
#   field_map/field_order keyed by field_id (:819-820); ref checks :830-834, :869, :882-886
def check_schema(self, form: FormSchema) -> list[str]               # :959
def _detect_circular_dependencies(self, form) -> list[str]          # :974 — DFS (:1000-1053)
# _collect_fields (:736) / _collect_nested_fields (:753) — the ONLY traversal
#   recursing children/item_template → promote to canonical (Module 2)

# services/rule_evaluator.py
# raw = answers.get(condition.field_id) (:124); _topo_order (:355-410) keyed on
# field_id; on cycle: WARNS + declaration order (asymmetric with validators DFS — preserve behavior)

# services/blob_storage.py
class BlobMetadata(BaseModel):                  # :55-74 — form_id (:69), field_id (:70), extra="forbid"
def _build_key(self, metadata: BlobMetadata) -> str  # :211-220
#   f"{self._prefix}{metadata.form_id}/{metadata.field_id}/{blob_id}" (:220)
# _from_ref (:232-256) parses key back from stored ref — old refs stay resolvable

# services/partial_saves.py
async def save(self, form_id: str, session_id: str, answers: dict[str, Any]) -> PartialFormData  # :67
def _redis_key(self, form_id: str, session_id: str) -> str          # :174 — field_ids only inside JSON value

# services/question_bank.py — bank field_id is a MINTED UUID, unrelated to FormField.field_id
class ReusableField(BaseModel):                 # :29-48 — field_id: str (:43), definition: FormField (:44)
class ReusableFieldRef(BaseModel):              # :51-67 — bank_field_id: str (:66)
# DDL :74-85: field_id VARCHAR(255), UNIQUE(field_id, tenant) (:83)
# SQL: _INSERT_SQL :87-91, _SELECT_SQL :93, _SELECT_ALL_SQL :95, _INCREMENT_SQL :97-102
# create_field :176-190 — mints UUID4 regardless of source field_id
# resolve_ref :278-289 — expansion point for fresh field_uid (Module 12)

# services/storage.py — class PostgresFormStorage(FormStorage) (:63) — ZERO field_id refs
# _create_table_sql (:148-163): schema_json JSONB NOT NULL, UNIQUE(form_id, version) (:161)
# _upsert_sql (:165-176): whole-schema JSONB replace — FEAT-389 rewrites these; re-verify post-merge

# tools/edit_toolkit.py — class EditToolkit(AbstractToolkit) (:50)
def _find_field_and_section(self, field_id: str)                    # :111-125 — form-wide
# 12 tool methods with field_id params: get_field(:201), search_fields(:222),
# update_field(:282), add_field(:321), remove_field(:362), add_dependency(:396),
# update_dependency(:434), remove_dependency(:455), add_post_dependency(:474),
# remove_post_dependency(:512), move_field(:664); _replace_field_in_form(:548)

# extractors — field_id derivation points
# yaml.py: data["field_id"] (:269) | legacy data["name"] (:274) | dict-key (:279-284);
#   rule conds: cond.get("field_id", "") (:452, :541) — SILENT "" default (Module 3 errors)
# jsonschema.py: field_id=name (:207,:301); array item field_id="item" (:271)
# pydantic.py: field_id=attr name (:185); item (:260)
# tools/create_form.py: LLM prompt contract (:61, :91-113) — no uniqueness pass today

# renderers (control names STAY field_id — Module 11 only ADDS attributes)
# html5.py: id/name from field_id (:805-806 etc.), data-field-id (:1089),
#   upload URL (:1078), derived names {field_id}_svg/_png/_start/_end/_file/_available,
#   {field_id}.answer/.blob_ref (:1098-1101), {field_id}__arg__{name} (:1146)
# renderers/fields/audio.py:88-156 — 11 {field_id}-* DOM ids + JS literals
# telegram: FormStep.field_id (models.py:38); callback data uses positional indices, NOT field_id
# xforms.py:273 — field_id becomes an XML element name (NCName constraint)

# Legacy copies (Module 13 DELETES these):
# packages/ai-parrot/src/parrot/forms/schema.py — FormField :21-65 (field_id :47,
#   MISSING post_depends); FormSchema :150-175 (missing 8+ fields, no iter_all_fields,
#   no _validate_metadata); no RenderWarning
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `resolve_rule_references()` | extractor outputs / CreateFormTool result / operations revalidation | called before schema is registered/stored | extractors `yaml.py:344`, `tools/create_form.py`, `api/operations.py:358` |
| `find_field_by_uid()` | `api/operations.py` apply fns, `EditToolkit` | replaces `_field_index` (:178) / `_find_field_and_section` (:111) | `api/operations.py:178`, `tools/edit_toolkit.py:111` |
| `extract_uid()` | upload route, operations route | aiohttp `match_info` validation | `api/routes.py:255-261` |
| Full-tree uniqueness validator | `FormSchema` model_validator | Pydantic `mode="after"`, traversal per `_collect_nested_fields` | `services/validators.py:736,753` |
| Partial-save re-keying | `PartialSaveService.save/get` | UID resolution against registry form | `services/partial_saves.py:67,119` |
| Fresh UID minting on bank insert | `QuestionBankService.resolve_ref` | model_copy with new `field_uid` | `services/question_bank.py:278-289` |

### Does NOT Exist (Anti-Hallucination)

- ~~`FormSchema.form_uid`~~ — NOT on dev yet; lands with in-flight FEAT-389.
  **Hard gate: do not start implementation until FEAT-389 is merged.**
- ~~`FormField.field_uid` / `section_uid` / `subsection_uid`~~ — created by this feature
- ~~`FieldFallback` class~~ — the model at `core/schema.py:376-390` is `RenderWarning`;
  "FallbackRenderer" exists only in prose
- ~~duplicate-`field_id` validation in `FormSchema`~~ — none today; `core/schema.py:338`
  builds a set only for metadata-key collision
- ~~per-field table / per-field columns in `PostgresFormStorage`~~ — fields are embedded
  `schema_json` JSONB; only question-bank entries have per-field rows
- ~~format validation on `FormField.field_id`~~ — `validate_identifier`
  (`services/_identifiers.py`) exists but is NOT applied to field_id
- ~~`field_id` usage in `services/registry.py`~~ — registry is form-level only
- ~~`field_id` lookup in `services/rest_field_resolver.py`~~ — `RestCallbackInput.field_id`
  (:224) is a pass-through payload attribute; resolver never reads it
- ~~`field_id` as path param on the operations endpoint~~ — body-only; the sole
  `{field_id}` path param is the upload route (`api/routes.py:261`)
- ~~`field_id` in `api/controls.py`, `api/render.py`, `tools/database_form.py`, `ui/*`~~ — zero refs
- ~~`resolve_rule_references`, `find_field_by_uid`, `extract_uid`, `resolve_answer`~~ —
  new interfaces created by this spec; do not import until their module lands
- ~~`core/resolution.py`~~ — does not exist yet; Module 3 creates it (or extends the
  FEAT-389 assembly module if one landed — verify at task time)

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **FEAT-389 conventions throughout**: module/test taxonomy, numbered
  idempotent migrations under `packages/parrot-formdesigner/migrations/`,
  UUID path-param validation helper pattern, clean-break API changes.
- `uuid.UUID` fields with `Field(default_factory=uuid.uuid4)`; Pydantic v2
  serializes to canonical string in JSON — no custom serializers.
- Preserve `model_config` choices: `extra="forbid"` on schema models;
  `FieldCondition`/`DependencyRule` deliberately omit it (forward compat —
  `core/constraints.py:153-154`) — keep that when adding UID fields.
- Keep `FormField.model_rebuild()` (`core/schema.py:93`) after model changes
  (self-referential + PostDependency forward ref).
- One canonical recursive traversal (Module 2) — replace the three divergent
  walks (`iter_all_fields`, `_collect_nested_fields`, `_field_index`);
  do not add a fourth.
- Rule evaluator's cycle behavior stays warn-and-degrade
  (`rule_evaluator.py:355-410`) while validator's stays error — asymmetry is
  intentional (render-time resilience vs. save-time strictness).
- async/await throughout; `self.logger`; Google-style docstrings; strict type
  hints (project standards).

### Known Risks / Gotchas

- **FEAT-389 merge gate**: every Module-1 anchor (storage DDL, routes,
  handlers, blob keys) shifts when FEAT-389 lands. Tasks MUST re-verify
  contract line numbers post-merge before editing.
- **Client-supplied duplicate UID** (upsert origin): reject with 400 naming
  the UID and both element paths — never silently regenerate.
- **Duplicate `field_id` in stored/legacy schemas**: migration and build-time
  resolution cannot disambiguate rule references — hard error + report for
  manual repair; do not auto-rename.
- **`update_field` patch touching `field_uid`**: explicit rejection replaces
  today's silent pin of `field_id` (`api/operations.py:278`); tests must
  cover both the rename-allowed and uid-rejected paths.
- **Nested fields**: GROUP `children` / ARRAY `item_template` get UIDs too;
  any uniqueness or lookup done with `iter_all_fields()` semantics will miss
  them — use the canonical recursive traversal.
- **Blob refs written before migration**: old `{form_id}/{field_id}/...`
  keys stay resolvable via stored refs (`_from_ref` parses the ref itself);
  only new writes use the UID pattern. Migration reports legacy-keyed blobs;
  do not rewrite object-store keys.
- **YAML extractor silent `field_id=""`** (`yaml.py:452,541`): becomes an
  error in Module 3 — some previously "working" fixtures may start failing;
  fix the fixtures, not the check.
- **Legacy copy deletion (Module 13)**: audit ai-parrot core and tests for
  imports that only worked via the fallback branch; `parrot.tools.jiratoolkit`-style
  shim gotchas apply (patching the shim doesn't patch the real module).
- **Telegram callback encoding** uses positional indices, not field_id —
  no change needed; don't "fix" it to UIDs (callback-data size limit was the
  reason).
- **XForms**: `field_id` is an XML element name (NCName constraint,
  `xforms.py:273`) — unchanged by this feature, but do not swap it for a UID
  (UUIDs starting with a digit are invalid NCNames).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | none: stdlib `uuid`, existing `pydantic` v2, existing PostgreSQL `UUID` type |

---

## 8. Open Questions

> All questions raised during brainstorm and spec review are resolved;
> decision trail below.

- [x] Do sections/subsections get UIDs too? — *Resolved in brainstorm*: yes —
  all three levels (`field_uid`, `section_uid`, `subsection_uid`) in this
  feature.
- [x] Where does the `form_uid` str → UUID retrofit land? — *Resolved in
  brainstorm*: as the first module of THIS spec; FEAT-389 merges as specced
  (`str`).
- [x] How are rule references authored vs stored? — *Resolved in brainstorm*:
  authored by `field_id`, resolved to `field_uid` at build time; ambiguity =
  error.
- [x] Question-bank insertions? — *Resolved in brainstorm*: mint a fresh
  `field_uid` per insertion.
- [x] Question-bank `field_id` naming collision? — *Resolved in brainstorm*:
  rename to `question_id` (model, ref, DDL, SQL, params) in this spec.
- [x] Partial saves keying? — *Resolved at spec time*: wire stays
  `{field_id: value}`; Redis storage re-keyed by `field_uid` (rename-proof);
  unknown `field_id`s rejected.
- [x] Renderer exposure of UIDs? — *Resolved at spec time*: HTML5/audio emit
  `data-field-uid`; `RenderWarning` gains `field_uid`; control names stay
  `field_id`.
- [x] Legacy `parrot/forms` fallback copy? — *Resolved at spec time*: drop
  it — delete local copies, shim re-exports `parrot_formdesigner` only with a
  clear `ImportError`.
- [x] Audio WS wire protocol? — *Resolved at spec time*: `field_id` stays the
  wire key (payload semantics); UIDs only in internal manifests.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks sequential in one
  worktree.
- **Rationale**: every module transitively depends on the core model change
  (Modules 1–2); after that, consumer groups (edit surface, rules engine,
  blob/uploads, extractors, migrations) are mutually independent but share
  test fixtures and `core/schema.py` — splitting worktrees would serialize on
  merges anyway.
- **Cross-feature dependencies**: **FEAT-389 (`form-uid-stable-identity`)
  MUST be merged to `dev` before creating this feature's worktree.** Do not
  branch early — Module 1 edits files FEAT-389 rewrites. Also check at start
  time that no other in-flight spec targets `tools/edit_toolkit.py` or
  `api/operations.py`.
- **Worktree creation (after FEAT-389 merge)**:
  ```bash
  git checkout dev && git pull --ff-only origin dev
  git worktree add -b feat-393-formdesigner-field-uid \
    .claude/worktrees/feat-393-formdesigner-field-uid HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-31 | Jesus Lara | Initial draft from brainstorm (incl. question-bank `question_id` refinement) |
