# TASK-3479: Decision models, error codes, and `DecisionConfig` wiring

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of the spec. Every other task in FEAT-578 imports from this module, so it
lands first and alone. It defines the typed contracts in spec §2 "Data Models",
the fixed error-code vocabulary in §2 "Errors and transport", and the additive
`decisions` field on `WikiProjectConfig` that keeps generation disabled by default.

Nothing here reads a store, parses Markdown, or invokes a model — those are
TASK-3485 / TASK-3486 / TASK-3491.

---

## Scope

- Create the `decisions` package with a docstring-only `__init__.py`. **Do not**
  add re-exports — TASK-3494 owns the public surface, and two tasks editing the
  same `__all__` would conflict.
- Implement every Pydantic v2 model listed in spec §2 "Data Models" in
  `decisions/models.py`, all with `extra="forbid"` and JSON-safe values.
- Implement `DecisionError(ValueError)` carrying `code`, `message`,
  `decision_id`, and the frozen error-code constants.
- Add `decisions: DecisionConfig` to `WikiProjectConfig` (additive, defaulted).
- Create the test package directory for FEAT-578 and unit-test the model
  invariants.

**NOT in scope**: serialization / page encoding (TASK-3480), identity helpers
(TASK-3480), the CAS primitive (TASK-3481), any store, CLI, or tool wiring.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/__init__.py` | CREATE | Package docstring only — no re-exports (TASK-3494 owns those) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` | CREATE | All typed contracts + `DecisionError` + error codes |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | Additive `decisions: DecisionConfig` field |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/__init__.py` | CREATE | Test package marker for the FEAT-578 suite |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_models.py` | CREATE | Model invariants and config defaults |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase at `a2989d086`.
> Use these exact imports and signatures. Do NOT invent alternatives.

### Verified Imports

```python
from pydantic import BaseModel, Field, field_validator, model_validator
# pydantic==2.12.5 — packages/ai-parrot/pyproject.toml:54
```

`models.py` imports **nothing from `parrot.knowledge.wiki`**. Keeping it
dependency-free is what lets `store.py` stay unaware of the decisions package.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:379
class WikiProjectConfig(BaseModel):
    wiki_name: str = Field(default="codebase")                      # line 414 block
    backend: Literal["sqlite", "memory", "arangodb"] = Field(default="sqlite")  # line 414
    body_max_chars: int = Field(default=16_000, ge=1_000)           # line 417
    symbol_depth: int = Field(default=2, ge=1, le=6, ...)           # line 455
    structural_backend: bool = Field(                               # line 465 — INSERTION ANCHOR
        default=True,
        description=(...),
    )
    sqlite_busy_timeout: float = Field(default=15.0, ge=1.0, le=120.0, ...)  # line 473
```

### Does NOT Exist

- ~~`parrot.knowledge.wiki.decisions`~~ — this task creates it. Nothing under it exists today.
- ~~`WikiPageRecord.metadata`~~ — absent (fields end at `content_hash`, `store.py:456`).
  Typed ADR fields cannot be smuggled through page constructor kwargs.
- ~~`WikiProjectConfig.decisions`~~ — absent; this task adds it.
- ~~`WikiProjectConfig.backend == "postgres"`~~ — the Literal is
  `sqlite|memory|arangodb` only (`project.py:414`). Do **not** widen it.
- ~~`parrot.knowledge.wiki.models.DecisionRecord`~~ — `wiki/models.py` exists but
  holds unrelated models; do not add ADR models there.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/project.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- Pydantic v2 only; every model sets `model_config = ConfigDict(extra="forbid")`.
- JSON-safe values only — no `datetime`, no `Path`, no `Enum` instances in fields.
  `ReviewEvent.timestamp` is an ISO-8601 **string**, mirroring
  `WikiPageRecord.updated_at` (`store.py:454`).
- `black` line length 120.
- An inferred record is permanently inferred: `origin='inferred'` and
  `source_status='unknown'` are invariants that review cannot change (spec §2
  "Candidate generation and attributed review", AC11). Enforce with a validator.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:20-115` —
  sibling feature's Pydantic output-model style.
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:379-480` — field style.

---

## Implementation Blueprint

### Steps (in order)

1. Create `decisions/__init__.py` with a docstring and **no imports** — *why*: an
   eager re-export here would make `project.py` import the decisions package at
   config-load time and risk a cycle; TASK-3494 adds the surface once it is safe.
2. Write `models.py` top-down: error codes → `DecisionError` → leaf models →
   `DecisionRecord` → result/dossier models — *why*: Pydantic resolves forward
   references at class-creation time, so a leaf must precede its container.
3. Add the `decisions` field to `WikiProjectConfig` **after** `structural_backend`
   — *why*: that keeps the new field next to the other FEAT-era toggles and the
   anchor is unique (verified count 1).
4. Write `test_models.py` covering defaults, bound rejection, and the inferred
   invariant — *why*: AC11 depends on the invariant being unforgeable, so it must
   fail loudly at construction, not at review time.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/__init__.py` (CREATE)

```python
"""ADR extraction and decision retrieval (FEAT-578).

Deterministic ingestion of Architecture Decision Records into the wiki
retrieval plane, symbol-to-decision lookup, cited "why" dossiers, and
explicitly labeled candidate generation.

Public re-exports are added by the adapter task once the whole surface
exists; import from the submodules directly until then.
"""
```

**Why this shape**: the package must be importable by `project.py` without
pulling in the store, the parser, or a client. A docstring-only module
guarantees that. TASK-3494 replaces this file wholesale.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` (CREATE)

```python
"""Typed contracts for the ADR decision plane (FEAT-578 Module 1).

Every model is Pydantic v2 with ``extra="forbid"`` and JSON-safe field
types, so a record round-trips through the canonical JSON envelope in
``decisions/codec.py`` without custom encoders.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Fixed diagnostic/error vocabulary (spec §2 "Errors and transport"). These
#: strings are a public contract: CLI JSON, MCP errors and tests all match on
#: them, so never re-spell one.
ADR_SCHEMA_UNSUPPORTED = "ADR_SCHEMA_UNSUPPORTED"
ADR_REVISION_CONFLICT = "ADR_REVISION_CONFLICT"
ADR_WRITE_UNSUPPORTED = "ADR_WRITE_UNSUPPORTED"
ADR_MANAGED_PAGE = "ADR_MANAGED_PAGE"
ADR_RECORD_TOO_LARGE = "ADR_RECORD_TOO_LARGE"
ADR_STATUS_CONFLICT = "ADR_STATUS_CONFLICT"
ADR_SUPERSESSION_CYCLE = "ADR_SUPERSESSION_CYCLE"
ADR_INVENTORY_LIMIT = "ADR_INVENTORY_LIMIT"
ADR_GENERATION_LIMIT = "ADR_GENERATION_LIMIT"
ADR_EVIDENCE_CHANGED = "ADR_EVIDENCE_CHANGED"
ADR_MODEL_FAILED = "ADR_MODEL_FAILED"
ADR_MODEL_TIMEOUT = "ADR_MODEL_TIMEOUT"
ADR_MODEL_UNCONFIGURED = "ADR_MODEL_UNCONFIGURED"
ADR_INVALID_ARGUMENT = "ADR_INVALID_ARGUMENT"
ADR_PARSE_FAILED = "ADR_PARSE_FAILED"
ADR_REFERENCE_MISSING = "ADR_REFERENCE_MISSING"
ADR_REFERENCE_AMBIGUOUS = "ADR_REFERENCE_AMBIGUOUS"
ADR_SOURCE_UNAVAILABLE = "ADR_SOURCE_UNAVAILABLE"
ADR_PATH_OUTSIDE_ROOT = "ADR_PATH_OUTSIDE_ROOT"
ADR_READ_ONLY = "ADR_READ_ONLY"

#: Page category for every managed ADR record.
ADR_CATEGORY = "adr"

#: Maximum serialized page size before ``ADR_RECORD_TOO_LARGE`` (spec §2).
MAX_RECORD_BYTES = 1024 * 1024


class DecisionError(ValueError):
    """A typed ADR failure carrying one of the fixed codes above."""

    def __init__(self, code: str, message: str, decision_id: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.decision_id = decision_id


class _Strict(BaseModel):
    """Shared strict base — forbids unknown fields on every ADR model."""

    model_config = ConfigDict(extra="forbid")


class DecisionConfig(_Strict):
    """Project-level ADR settings; generation is opt-in and off by default."""

    enabled: bool = True
    adr_globs: list[str] = Field(
        default_factory=lambda: ["docs/adr/**/*.md", "docs/adrs/**/*.md", "docs/decisions/**/*.md"]
    )
    max_records: int = Field(default=10_000, ge=1, le=100_000)
    generation_enabled: bool = False
    max_input_tokens: int = Field(default=12_000, gt=0)
    max_output_tokens: int = Field(default=2_000, gt=0)
    max_files: int = Field(default=8, gt=0)
    max_candidates: int = Field(default=3, gt=0)
    timeout_seconds: int = Field(default=60, gt=0)


class EvidenceRef(_Strict):
    """One cited source span with the hash of the bytes it was read from."""

    page_id: str = Field(..., min_length=1)
    rel_path: str = Field(..., min_length=1)
    start_line: int = Field(..., ge=1)
    end_line: int = Field(..., ge=1)
    source_sha1: str = Field(..., min_length=1)
    excerpt: str = ""
    kind: Literal["adr", "code", "comment", "document"]

    # FILL IN: reject end_line < start_line and any rel_path that is absolute or
    # escapes the repository root (".." segments, drive letters) — bounded by spec
    # §2 "1-based inclusive valid ranges; repository-relative confined paths" and
    # the ADR_PATH_OUTSIDE_ROOT code. Raise ValueError; the service maps it.


class DecisionLink(_Strict):
    """A typed, provenance-tagged association to another page or record."""

    target_id: str = Field(..., min_length=1)
    relation: Literal["explains", "supported_by", "supersedes"]
    provenance: Literal["extracted", "inferred", "asserted"]
    evidence_indexes: list[int] = Field(default_factory=list)


class ReviewEvent(_Strict):
    """One attributed review action, hashed before and after."""

    revision: int = Field(..., ge=1)
    action: Literal["accept", "reject", "revise", "link"]
    actor: str = Field(..., min_length=1)
    timestamp: str = Field(..., min_length=1)
    reason: str = ""
    before_sha1: str = ""
    after_sha1: str = ""


class GenerationInfo(_Strict):
    """Provenance of one bounded model invocation that produced a candidate."""

    model_spec: str = Field(..., min_length=1)
    prompt_version: Literal[1] = 1
    scope_id: str = Field(..., min_length=1)
    input_sha1: str = Field(..., min_length=1)
    max_input_tokens: int = Field(..., gt=0)
    max_output_tokens: int = Field(..., gt=0)


class DecisionRecord(_Strict):
    """The single canonical, versioned record persisted per ``adr:`` page."""

    schema_version: Literal[1] = 1
    decision_id: str = Field(..., min_length=1)
    revision: int = Field(default=1, ge=1)
    title: str = ""
    context: str = ""
    decision: str = Field(..., min_length=1)
    consequences: str = ""
    source_status: Literal["unknown", "proposed", "accepted", "rejected", "deprecated", "superseded"] = "unknown"
    source_status_raw: str = ""
    origin: Literal["documented", "inferred"]
    review_status: Literal["unreviewed", "accepted", "rejected"] = "unreviewed"
    source_path: str | None = None
    external_id: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    links: list[DecisionLink] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    review_history: list[ReviewEvent] = Field(default_factory=list)
    generation: GenerationInfo | None = None
    content_fingerprint: str = ""

    @model_validator(mode="after")
    def _check_invariants(self) -> "DecisionRecord":
        """Enforce the provenance invariants review may never violate."""
        # FILL IN: an origin='inferred' record MUST keep source_status='unknown'
        # (raise otherwise), and every DecisionLink.evidence_indexes entry MUST
        # address this record's own `evidence` list — bounded by spec §2
        # "accepting it changes review status, not provenance" and AC11/AC4.
        raise NotImplementedError


class DecisionDiagnostic(_Strict):
    """A non-fatal condition reported alongside a typed result."""

    code: str = Field(..., min_length=1)
    message: str = ""
    path: str | None = None
    decision_id: str | None = None


class DecisionHit(_Strict):
    """One ranked decision with its labels, score, and citations."""

    decision_id: str = Field(..., min_length=1)
    revision: int = Field(..., ge=1)
    title: str = ""
    origin: Literal["documented", "inferred"]
    source_status: str = "unknown"
    review_status: Literal["unreviewed", "accepted", "rejected"] = "unreviewed"
    freshness: Literal["current", "stale", "missing", "unverified"] = "unverified"
    score: float = 0.0
    decision: str = ""
    applicability: list[DecisionLink] = Field(default_factory=list)
    citations: list[EvidenceRef] = Field(default_factory=list)


class DecisionDossier(_Strict):
    """The retrieval result — documented and candidate groups stay separate."""

    status: Literal["ok", "empty", "ambiguous", "partial", "error"] = "ok"
    documented: list[DecisionHit] = Field(default_factory=list)
    candidates: list[DecisionHit] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    diagnostics: list[DecisionDiagnostic] = Field(default_factory=list)
    truncated: bool = False


class SyncResult(_Strict):
    """Counts and diagnostics from one ADR refresh pass."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: int = 0
    unresolved: int = 0
    diagnostics: list[DecisionDiagnostic] = Field(default_factory=list)


class GenerationResult(_Strict):
    """Ids written, ids reused for the same evidence, and per-candidate failures."""

    decision_ids: list[str] = Field(default_factory=list)
    reused: list[str] = Field(default_factory=list)
    diagnostics: list[DecisionDiagnostic] = Field(default_factory=list)


class CandidateDraft(_Strict):
    """One model-authored candidate. The model supplies content only."""

    title: str = ""
    context: str = ""
    decision: str = Field(..., min_length=1)
    consequences: str = ""
    observations: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    evidence_indexes: list[int] = Field(default_factory=list)


class CandidateBatch(_Strict):
    """The structured-output contract handed to ``AbstractClient.invoke``."""

    candidates: list[CandidateDraft] = Field(default_factory=list)


class CandidateEdit(_Strict):
    """The only fields a maintainer revision may change."""

    title: str | None = None
    context: str | None = None
    decision: str | None = None
    consequences: str | None = None
    observations: list[str] | None = None
    hypotheses: list[str] | None = None


class ReviewRequest(_Strict):
    """An attributed, revision-checked review action."""

    decision_id: str = Field(..., min_length=1)
    expected_revision: int = Field(..., ge=1)
    action: Literal["accept", "reject", "revise", "link"]
    actor: str = Field(..., min_length=1)
    reason: str = ""
    replacement: CandidateEdit | None = None
    documented_decision_id: str | None = None

    # FILL IN: require `replacement` for action='revise' and
    # `documented_decision_id` for action='link'; reject either when the action
    # does not take it — bounded by spec §2 "Review supports typed revision,
    # rejection, and linking" and the ADR_INVALID_ARGUMENT code.


def as_json_dict(model: BaseModel) -> dict[str, Any]:
    """Dump a model in JSON mode — the only shape the codec and CLI emit."""
    return model.model_dump(mode="json")
```

**Why this shape**: `_Strict` centralizes `extra="forbid"` so a forged field in a
model response is rejected at parse time rather than silently stored (spec §2
"the model cannot supply status, actor, timestamps, or arbitrary paths"). The
error-code constants live beside the models because `store.py` must stay unaware
of this package, so the codes cannot live in the store. `CandidateBatch` wraps a
list because `AbstractClient.invoke(output_type=...)` needs a model class, not a
bare list. Never rename a code constant or a `Literal` member — CLI JSON, MCP
errors and the tests all match on the exact strings.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '    structural_backend: bool = Field(' packages/ai-parrot/src/parrot/knowledge/wiki/project.py)
# AFTER — insert below the field block opened by `    structural_backend: bool = Field(`
# (verified: packages/ai-parrot/src/parrot/knowledge/wiki/project.py:465), i.e.
# after its closing `)` and before `    sqlite_busy_timeout: float = Field(`:
    decisions: DecisionConfig = Field(
        default_factory=DecisionConfig,
        description=(
            "ADR decision-plane settings (FEAT-578): discovery globs, "
            "inventory bound, and the opt-in candidate-generation budget. "
            "Generation is disabled by default."
        ),
    )
```

Add the import at the top of `project.py`, grouped with the other
`parrot.knowledge.wiki` imports:

```python
from parrot.knowledge.wiki.decisions.models import DecisionConfig
```

Also extend the `WikiProjectConfig` class docstring's `Attributes:` block with a
`decisions:` entry — *why*: every other field there is documented, and `ruff`'s
docstring rules plus review convention expect parity.

**Why**: a nested model with `default_factory` keeps every existing
`.parrot/wiki.json` valid and loadable with no migration, which spec §2
"Integration Points" requires (`additive`; "defaults keep generation disabled").

### `packages/ai-parrot/tests/knowledge/wiki/decisions/__init__.py` (CREATE)

```python
"""Tests for the ADR decision plane (FEAT-578)."""
```

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_models.py` (CREATE)

```python
"""Model invariants for the ADR decision plane (FEAT-578 Module 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.knowledge.wiki.decisions.models import (
    DecisionConfig,
    DecisionError,
    DecisionLink,
    DecisionRecord,
    EvidenceRef,
    ReviewRequest,
)
from parrot.knowledge.wiki.project import WikiProjectConfig


def _evidence(**overrides) -> EvidenceRef:
    """Build a valid EvidenceRef, overriding single fields per test."""
    base = dict(
        page_id="file:a.py", rel_path="a.py", start_line=1, end_line=3,
        source_sha1="d0", excerpt="x", kind="code",
    )
    return EvidenceRef(**{**base, **overrides})


class TestDecisionConfig:
    def test_defaults_disable_generation(self):
        """Generation is opt-in — a bare config never enables a model call (AC5)."""
        # FILL IN: assert generation_enabled is False and the three default globs
        raise NotImplementedError

    def test_project_config_carries_decisions(self):
        """WikiProjectConfig gains the field without breaking existing configs."""
        # FILL IN: WikiProjectConfig() has .decisions == DecisionConfig();
        # a config dict WITHOUT a "decisions" key still validates
        raise NotImplementedError

    @pytest.mark.parametrize("field,value", [("max_records", 0), ("max_files", 0), ("timeout_seconds", 0)])
    def test_rejects_non_positive_limits(self, field, value):
        """Every numeric limit is positive (spec §2 Data Models)."""
        with pytest.raises(ValidationError):
            DecisionConfig(**{field: value})


class TestEvidenceRef:
    def test_rejects_inverted_range(self):
        """end_line < start_line is not a span."""
        with pytest.raises(ValidationError):
            _evidence(start_line=9, end_line=2)

    @pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.py"])
    def test_rejects_unconfined_path(self, bad):
        """Paths stay repository-relative (ADR_PATH_OUTSIDE_ROOT rationale)."""
        with pytest.raises(ValidationError):
            _evidence(rel_path=bad)


class TestDecisionRecord:
    def test_inferred_record_cannot_claim_a_source_status(self):
        """AC11: inferred provenance pins source_status to 'unknown'."""
        # FILL IN: constructing origin='inferred' with source_status='accepted'
        # raises ValidationError; origin='inferred' + 'unknown' succeeds
        raise NotImplementedError

    def test_link_evidence_indexes_must_address_own_evidence(self):
        """A link may only cite evidence this record actually carries (AC4)."""
        # FILL IN: one evidence entry + DecisionLink(evidence_indexes=[5]) raises
        raise NotImplementedError

    def test_extra_fields_are_forbidden(self):
        """A forged field never survives into a stored record."""
        with pytest.raises(ValidationError):
            DecisionRecord(decision_id="adr:doc:x", decision="d", origin="documented", forged=True)


class TestReviewRequest:
    def test_revise_requires_replacement(self):
        """A 'revise' with no CandidateEdit is an invalid argument."""
        # FILL IN
        raise NotImplementedError

    def test_link_requires_documented_id(self):
        """A 'link' with no documented_decision_id is an invalid argument."""
        # FILL IN
        raise NotImplementedError


def test_decision_error_carries_code_and_id():
    """DecisionError exposes code/message/decision_id for CLI + MCP rendering."""
    err = DecisionError("ADR_REVISION_CONFLICT", "stale", decision_id="adr:doc:a")
    assert (err.code, err.decision_id) == ("ADR_REVISION_CONFLICT", "adr:doc:a")
    assert isinstance(err, ValueError)
```

**Why**: the two `DecisionRecord` invariant tests are the executable form of
AC11 and AC4. If they can be made to pass by weakening the validator, the whole
provenance guarantee is gone, so they are written before the validator body.

### FILL IN checklist

- [ ] `models.py::EvidenceRef` — line-range and confined-path validators; bounded by spec §2 Data Models + `ADR_PATH_OUTSIDE_ROOT`
- [ ] `models.py::DecisionRecord._check_invariants` — inferred ⇒ `source_status='unknown'`, and link indexes address own evidence; bounded by AC11 / AC4
- [ ] `models.py::ReviewRequest` — action/payload cross-validation; bounded by `ADR_INVALID_ARGUMENT`
- [ ] `project.py` — `Attributes:` docstring entry for `decisions`; bounded by existing docstring convention
- [ ] `test_models.py` — five test bodies; bounded by the assertions named in each docstring

---

## Acceptance Criteria

- [ ] Every model in spec §2 "Data Models" exists in `decisions/models.py` with `extra="forbid"`
- [ ] `origin='inferred'` with any `source_status` other than `'unknown'` raises at construction (AC11)
- [ ] `DecisionLink.evidence_indexes` out of range raises at construction (AC4)
- [ ] `WikiProjectConfig()` validates with no `decisions` key and yields generation disabled (AC5)
- [ ] `from parrot.knowledge.wiki.decisions.models import DecisionRecord` works
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ packages/ai-parrot/src/parrot/knowledge/wiki/project.py` is clean
- [ ] `black --line-length 120 --check` is clean on every touched file

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_models.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli.py -q`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2 "Data Models", "Errors and transport", and §5 AC4/AC5/AC11.
2. **Verify the Codebase Contract** — re-check `project.py:465` still opens the
   `structural_backend` field before inserting below it.
3. **Implement** from the blueprint; complete every `# FILL IN:` marker.
4. **Verify** the Validation Commands pass.
5. **Move this file** to `sdd/tasks/completed/` and set the index entry to `done`.
6. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
