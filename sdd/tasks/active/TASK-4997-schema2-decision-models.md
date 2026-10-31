# TASK-4997: Schema-2 decision models, error codes, normative relation types

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (first half). Every other module of FEAT-784 reads or writes decision records with the
new schema-2 fields (`about`, `targets`, `normative`, `contradicts`, `supersedes_refs`, `document_id`,
`entry_id`, `batch_id`, `lifecycle`, `rationale`, `rejected_alternatives`). This task extends
`DecisionRecord` **additively** — schema-1 records must keep parsing with identical ids (AC2, G7) — adds the
two reference models `DecisionRef` / `DecisionTarget`, centralizes every new error-code constant the feature
uses (so later tasks import them instead of re-spelling them), widens `DecisionLink.relation` for the
projected cache, and adds three normative `RelationType` values.

The codec side (envelope v2, `spec_decision_id`) is TASK-4998.

---

## Scope

- Add `DecisionRef(_Strict)` and `DecisionTarget(_Strict)` to `models.py`.
- Add the schema-2 fields to `DecisionRecord`, widen `schema_version` to `Literal[1, 2]`, and add a validator:
  `schema_version == 1` ⇒ every schema-2 field is at its default.
- Widen `DecisionLink.relation` with `"contradicts"` and `"about"` (projected-cache only).
- Add the new error-code constants (full list below) to the vocabulary block of `models.py`.
- Add `CONSTRAINS`, `FORBIDS`, `REQUIRES` to `RelationType`; bump `test_ontology.py` count 18 → 21.
- Extend `test_models.py` with schema-1/schema-2 tests.

**NOT in scope**: codec / envelope marker / `spec_decision_id` (TASK-4998); spec block parsing (TASK-4999);
any eligibility logic (TASK-5003); `__init__.py` exports (TASK-4998).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` | MODIFY | error codes, `DecisionRef`, `DecisionTarget`, schema-2 fields + invariant, `DecisionLink.relation` |
| `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py` | MODIFY | `CONSTRAINS` / `FORBIDS` / `REQUIRES` |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_models.py` | MODIFY | schema-2 tests |
| `packages/ai-parrot/tests/knowledge/okf/test_ontology.py` | MODIFY | member count 18 → 21 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator  # verified: models.py:14
from parrot.knowledge.wiki.decisions.models import (  # verified: models.py:47,57,140,172
    DecisionError, DecisionLink, DecisionRecord, _Strict,
)
from parrot.knowledge.okf.ontology import RelationType  # verified: okf/ontology.py:85
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py
ADR_SCHEMA_UNSUPPORTED = "ADR_SCHEMA_UNSUPPORTED"   # line 19 — vocabulary block runs lines 19-38
ADR_READ_ONLY = "ADR_READ_ONLY"                     # line 38 — last line of the block
class DecisionError(ValueError):                    # line 47 — __init__(code, message, decision_id=None)
class _Strict(BaseModel):                           # line 57 — model_config = ConfigDict(extra="forbid") (line 60)
class DecisionLink(_Strict):                        # line 140
    relation: Literal["explains", "supported_by", "supersedes"]   # line 144
class DecisionRecord(_Strict):                      # line 172
    schema_version: Literal[1] = 1                  # line 175
    content_fingerprint: str = ""                   # line 194 — last field
    @model_validator(mode="after")                  # line 196
    def _check_invariants(self) -> "DecisionRecord":  # line 197 — returns self at line 212

# packages/ai-parrot/src/parrot/knowledge/okf/ontology.py
class RelationType(str, Enum):                      # line 85
    CONTRADICTS = "contradicts"                     # line 116
    ABOUT = "about"                                 # line 120
    SUPPORTED_BY = "supported_by"                   # line 121 — last member

# packages/ai-parrot/tests/knowledge/okf/test_ontology.py
        assert len(RelationType) == 18              # line 95 (inside test_total_count, line 92)
```

### Does NOT Exist
- ~~`ADR_UNSUPPORTED_SCHEMA`~~ — the spec's spelling; the repo's code is `ADR_SCHEMA_UNSUPPORTED` (models.py:19). Never add the re-spelled variant.
- ~~`DecisionRef`, `DecisionTarget`~~ — created by this task.
- ~~`RelationType.CONSTRAINS` / `FORBIDS` / `REQUIRES`~~ — created by this task (`ABOUT`, `CONTRADICTS`, `SUPERSEDES` already exist).
- ~~`DecisionRecord.tags`~~ — there is no tag field; do not add one.
- ~~`DecisionRecord.supersedes`~~ — the schema-2 field is named `supersedes_refs` (legacy supersession stays a `DecisionLink` with relation `"supersedes"`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/okf/ontology.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/okf/test_ontology.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#_Strict",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionLink",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/okf/ontology.py#RelationType"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Additive only: every existing field, default and validator of `DecisionRecord` stays exactly as is (G7).
- `extra="forbid"` is inherited from `_Strict`; keep it — a v1 reader must reject unknown fields.
- Default all schema-2 fields so a schema-1 payload validates unchanged (`Field(default_factory=list)` for lists).
- `DecisionTarget.kind` must agree with the id prefix (`sym:`→symbol, `file:`→file, `dir:`→dir); validate it.
- Error-code constants are a public contract ("never re-spell one", models.py:16-18).

### References in Codebase
- `models.py:196-212` — existing `_check_invariants` validator style.

---

## Implementation Blueprint

### Steps (in order)
1. Append the new error-code constants after `ADR_READ_ONLY` — *why*: every later FEAT-784 module imports codes from one vocabulary.
2. Add `DecisionRef` and `DecisionTarget` above `DecisionRecord` (after `GenerationInfo`) — *why*: `DecisionRecord` references them, and Pydantic needs them defined first (no forward refs needed).
3. Widen `DecisionLink.relation` — *why*: TASK-5007 projects `about` / `contradicts` edges into the cache.
4. Change `schema_version` to `Literal[1, 2]` and add the schema-2 fields after `content_fingerprint` — *why*: additive schema bump (spec §2 Data Models).
5. Add a second `model_validator` `_check_schema_fields` — *why*: a v1 record carrying v2 fields is ambiguous and must fail.
6. Add the three `RelationType` members and bump the count test — *why*: `test_ontology.py:95` asserts the exact count.
7. Write the tests in `test_models.py`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` (MODIFY — 1/4: error codes)
```python
# occurrences: 1 (verified: grep -c 'ADR_READ_ONLY = "ADR_READ_ONLY"' models.py)
# AFTER — insert below `ADR_READ_ONLY = "ADR_READ_ONLY"` (verified: models.py:38)
# FEAT-784 decision-audit vocabulary (spec §7 "Error codes introduced").
# The spec's ``ADR_UNSUPPORTED_SCHEMA`` IS ``ADR_SCHEMA_UNSUPPORTED`` above — never re-spell it.
ADR_INVALID_ID = "ADR_INVALID_ID"
SPEC_BLOCK_MISSING = "SPEC_BLOCK_MISSING"
SPEC_BLOCK_INVALID_YAML = "SPEC_BLOCK_INVALID_YAML"
SPEC_DUPLICATE_ENTRY_ID = "SPEC_DUPLICATE_ENTRY_ID"
SPEC_INVALID_ID = "SPEC_INVALID_ID"
SPEC_UNKNOWN_FIELD = "SPEC_UNKNOWN_FIELD"
SPEC_DANGLING_REF = "SPEC_DANGLING_REF"
SPEC_EMPTY_ABOUT = "SPEC_EMPTY_ABOUT"
SPEC_EMPTY_TARGETS = "SPEC_EMPTY_TARGETS"
TAXONOMY_INVALID = "TAXONOMY_INVALID"
APPROVAL_MANIFEST_INVALID = "APPROVAL_MANIFEST_INVALID"
APPROVAL_UNVERIFIED = "APPROVAL_UNVERIFIED"
APPROVAL_LOCAL_BASE = "APPROVAL_LOCAL_BASE"
TARGET_UNRESOLVED = "TARGET_UNRESOLVED"
TARGET_FOREIGN = "TARGET_FOREIGN"
SCOPE_INCOMPLETE = "SCOPE_INCOMPLETE"
SNAPSHOT_UNSTABLE = "SNAPSHOT_UNSTABLE"
SUPERSESSION_INVALID = "SUPERSESSION_INVALID"
WAIVER_INVALID = "WAIVER_INVALID"
BATCH_PARTIAL = "BATCH_PARTIAL"
AUDIT_NOT_CONFIGURED = "AUDIT_NOT_CONFIGURED"
```
**Why**: spec §7 lists these codes; centralizing them here keeps "never re-spell" enforceable and avoids
every later task touching this file again.

### `models.py` (MODIFY — 2/4: reference models)
```python
# occurrences: 1 (verified: grep -c 'class DecisionRecord(_Strict):' models.py)
# BEFORE — insert immediately above `class DecisionRecord(_Strict):` (verified: models.py:172)
_TARGET_PREFIXES: dict[str, str] = {"sym:": "symbol", "file:": "file", "dir:": "dir"}


class DecisionRef(_Strict):
    """Exact ``(decision_id, revision)`` reference to another decision (FEAT-784)."""

    decision_id: str = Field(..., min_length=1)
    revision: int = Field(..., ge=1)


class DecisionTarget(_Strict):
    """Typed structural target; ``kind`` must match the id prefix (FEAT-784)."""

    target_id: str = Field(..., min_length=1)
    kind: Literal["symbol", "file", "dir"]

    @model_validator(mode="after")
    def _check_prefix(self) -> "DecisionTarget":
        """Reject a target whose id prefix disagrees with ``kind``."""
        # FILL IN: find the matching prefix in _TARGET_PREFIXES; raise ValueError if none matches
        #          or if the mapped kind != self.kind — bounded by spec §3 M1 ("kind derived from the id prefix")
        return self


```
**Why**: spec §3 M1 skeleton fixes field names; the prefix map is reused by TASK-4999 to derive `kind`.

### `models.py` (MODIFY — 3/4: DecisionLink relation + schema field)
```python
# occurrences: 1 (verified: grep -c '    relation: Literal\["explains", "supported_by", "supersedes"\]' models.py)
# REPLACE line `    relation: Literal["explains", "supported_by", "supersedes"]` (verified: models.py:144) with:
    relation: Literal["explains", "supported_by", "supersedes", "contradicts", "about"]

# occurrences: 1 (verified: grep -c '    schema_version: Literal\[1\] = 1' models.py)
# REPLACE line `    schema_version: Literal[1] = 1` (verified: models.py:175) with:
    schema_version: Literal[1, 2] = 1
```

### `models.py` (MODIFY — 4/4: schema-2 fields + invariant)
```python
# occurrences: 1 (verified: grep -c '    content_fingerprint: str = ""' models.py)
# AFTER — insert below `    content_fingerprint: str = ""` (verified: models.py:194)
    # --- schema 2 (FEAT-784, additive; every field defaults so schema-1 payloads still validate) ---
    normative: Literal["constrains", "forbids", "requires"] | None = None
    about: list[str] = Field(default_factory=list)
    targets: list[DecisionTarget] = Field(default_factory=list)
    contradicts: list[DecisionRef] = Field(default_factory=list)
    supersedes_refs: list[DecisionRef] = Field(default_factory=list)
    document_id: str | None = None
    entry_id: str | None = None
    batch_id: str | None = None
    lifecycle: Literal["active", "retired"] = "active"
    rationale: str = ""
    rejected_alternatives: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_schema_fields(self) -> "DecisionRecord":
        """A schema-1 record must keep every schema-2 field at its default."""
        if self.schema_version == 1:
            # FILL IN: collect the names of schema-2 fields whose value differs from the field default
            #          (compare against type(self).model_fields[name].get_default(call_default_factory=True));
            #          raise ValueError naming them — bounded by spec §3 M1 invariant + AC2
            pass
        return self
```
**Why**: placing the fields after the last schema-1 field keeps canonical JSON keys sorted anyway
(`canonical_json` sorts keys, codec.py:47) — position is cosmetic, but defaults are load-bearing for AC2.

### `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    SUPPORTED_BY = "supported_by"' okf/ontology.py)
# AFTER — insert below `    SUPPORTED_BY = "supported_by"` (verified: okf/ontology.py:121)

    # --- Normative decision relations (FEAT-784) ---
    CONSTRAINS = "constrains"
    FORBIDS = "forbids"
    REQUIRES = "requires"
```

### `packages/ai-parrot/tests/knowledge/okf/test_ontology.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'assert len(RelationType) == 18' tests/knowledge/okf/test_ontology.py)
# REPLACE `        assert len(RelationType) == 18` (verified: test_ontology.py:95) with:
        assert len(RelationType) == 21
# and append "+ 3 FEAT-784 normative relations" to the docstring on lines 93-94.
```

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_models.py` (MODIFY — append at end of file)
```python
# --- FEAT-784 schema 2 -------------------------------------------------------
from parrot.knowledge.wiki.decisions.models import DecisionRef, DecisionTarget  # noqa: E402


def _v2(**overrides) -> DecisionRecord:
    base = dict(schema_version=2, decision_id="adr:spec:doc#rule", decision="x", origin="documented",
                source_status="accepted")
    return DecisionRecord(**{**base, **overrides})


def test_schema1_record_parses_unchanged():
    """AC2: a schema-1 payload validates with every schema-2 field at its default."""
    # FILL IN: build a schema-1 record (no schema_version kwarg); assert lifecycle=="active", about==[], ...


def test_schema1_with_schema2_fields_rejected():
    # FILL IN: DecisionRecord(..., schema_version=1, about=["memory"]) raises ValidationError


def test_schema2_round_trips_through_model_dump():
    # FILL IN: _v2(about=[...], targets=[DecisionTarget(...)], contradicts=[DecisionRef(...)]);
    #          DecisionRecord.model_validate(rec.model_dump(mode="json")) == rec


@pytest.mark.parametrize("target_id,kind,ok", [
    ("sym:a.py#f", "symbol", True), ("file:a.py", "file", True), ("dir:pkg", "dir", True),
    ("file:a.py", "dir", False), ("pkg/a.py", "file", False),
])
def test_decision_target_prefix(target_id, kind, ok):
    # FILL IN: ok → constructs; not ok → ValidationError


def test_decision_ref_revision_ge_1():
    # FILL IN: DecisionRef(decision_id="x", revision=0) raises ValidationError
```

### FILL IN checklist
- [ ] `DecisionTarget._check_prefix` — prefix/kind agreement; bounded by spec §3 M1
- [ ] `DecisionRecord._check_schema_fields` — schema-1 ⇒ defaults; bounded by AC2
- [ ] test bodies in `test_models.py`

---

## Acceptance Criteria

- [ ] Every existing test in `test_models.py`, `test_codec.py`, `test_backend_parity.py` still passes unchanged (AC2/G7).
- [ ] Schema-1 record with a schema-2 field raises `ValidationError`.
- [ ] `DecisionTarget` rejects a prefix/kind mismatch.
- [ ] `len(RelationType) == 21`; `RelationType("forbids") is RelationType.FORBIDS`.
- [ ] All 22 new constants importable from `parrot.knowledge.wiki.decisions.models`; no `ADR_UNSUPPORTED_SCHEMA` anywhere.
- [ ] `ruff check` clean on touched files.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_models.py -q`
- `pytest packages/ai-parrot/tests/knowledge/okf/test_ontology.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_codec.py -q`

---

## Test Specification

See the `test_models.py` blueprint block above (spec §4 `test_schema1_record_parses_unchanged`).

---

## Agent Instructions

1. Work in the feature worktree `feat-FEAT-784-sdd-decision-audit` (never on `dev`).
2. Read spec §2 Data Models and §3 Module 1.
3. Verify the Codebase Contract anchors (`grep -c`) before editing.
4. Implement the blueprint, complete every FILL IN, run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the four listed files; close with `scripts/sdd/close_task.sh TASK-4997 sdd-decision-audit verified`.

---

## Completion Note

*(filled in by the implementing agent)*
