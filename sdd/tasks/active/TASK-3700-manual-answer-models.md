# TASK-3700: ProcedureAnswer, citations, view models and kind invariants (M2 answer)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3699
**Assigned-to**: unassigned

---

## Context

Spec §2 "Data Models" (`ProcedureAnswer`) and §3 **Module 2** (answer half). The release pipeline (TASK-3721..3725)
produces a single channel-agnostic `ProcedureAnswer` (G5). Its model validator is the last line of defence for U4/R2:
a `procedure` answer must carry ordered steps **and** citations; an `incomplete` answer must name what is missing and
release **no** steps (AC7); `denied`/`not_found`/`out_of_scope`/`clarification` carry no evidence; `provenance` is always
derived from citations, never taken from model output. `answer` is the **only** model-authored field.

Parallelism: modifies `manuals/models.py` created by TASK-3699 (same file — serialized) and uses its
`Step`/`MediaRef`/`Tip`.

---

## Scope

- Append to `parrot/knowledge/manuals/models.py`: `ProcedureCitation`, `derive_provenance`, `ProcedureRef`,
  `ProcedureView`, `StepView`, `HazardView`, `MediaView`, `TipView`, `Prerequisites`, `ProcedureAnswer` with
  `@model_validator(mode="after") _check_kind_invariants`.
- Write `tests/knowledge/manuals/test_answer_models.py`.

**NOT in scope**: `AssembledProcedure` (TASK-3721, lives in `parrot_tools/procedures/assembly.py`), verifier logic
(TASK-3722), presigned URLs (views carry media **ids**, never URLs — URLs are minted after release, G4). Do not touch
`manuals/__init__.py` (its lazy map already lists these names).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/manuals/models.py` | MODIFY | Append citation / view / answer models |
| `packages/ai-parrot/tests/knowledge/manuals/test_answer_models.py` | CREATE | Kind invariants, provenance derivation, citation rules |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported at the top of manuals/models.py by TASK-3699 — reuse, do not re-import:
#   MAX_QUOTE_CHARS, AnswerProvenance, VerificationState, Evidence, Extracted (parrot.knowledge.common.provenance)
#   BaseModel, ConfigDict, Field, field_validator, model_validator (pydantic)
#   Optional, Literal, Any, Sequence (typing); datetime (datetime)
from parrot.knowledge.manuals.models import (ProcedureAnswerKind, ProcedureKind, MediaKind, MediaRole, HazardSeverity,
    PartRef, ToolRef, manual_snapshot_payload)   # defined by TASK-3699 in the same module
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/contracts/models.py  (shapes to mirror — never import contracts from manuals)
class Citation(BaseModel):          # :701-737 contract_id (min 1), title, node_id (min 1), quote Field(..., min_length=1, max_length=MAX_QUOTE_CHARS),
                                    #   page ge=1, verification, version_n ge=1, source_sha256; _nonblank_quote validator :726-731;
    @property
    def key(self) -> tuple[str, str]    # :733-736 — a PROPERTY (spec §3 wrote `def key(self)`; mirror the property)
class ContractAnswer(BaseModel):    # :750-797; @model_validator(mode="after") _check_kind_invariants :775-797 sets provenance at the end
def derive_provenance(citations: list[Citation]) -> AnswerProvenance   # :800-818 — empty ⇒ "extracted"; all verified ⇒ "verified"; some ⇒ "mixed"
# packages/ai-parrot/src/parrot/knowledge/manuals/models.py (TASK-3699)
def manual_snapshot_payload(card: ManualCard) -> dict[str, Any]   # last definition in the file — the append anchor
```

### Does NOT Exist
- ~~`ProcedureCitation.contract_id`~~ — the field is `manual_id` (no rename of contracts' `Citation`, spec Non-Goal).
- ~~A URL field on `MediaView`~~ — media are released as ids; URLs live on `AnswerOutcome.image_urls` (TASK-3723).
- ~~`AnswerKind` values `interpretation_required` / handoff~~ — contracts-only; the manuals kinds are `ProcedureAnswerKind`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/manuals/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_answer_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/models.py#Citation",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/models.py#ContractAnswer",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/models.py#derive_provenance"
  ]
}
```

---

## Implementation Notes

### Kind invariants (fix these exactly — AC7, G5)
| `answer_kind` | Must carry | Must NOT carry |
|---|---|---|
| `procedure` | `procedure`, ≥1 step (orders strictly increasing, unique `step_id`), ≥1 citation | `reason` |
| `step` | exactly 1 step, ≥1 citation | — |
| `prerequisites` | `prerequisites`, ≥1 citation | steps |
| `lookup` | non-blank `answer`, ≥1 citation | steps, `procedure` |
| `incomplete` | non-blank `reason` naming the missing step/field | steps, media, tips |
| `clarification` / `not_found` / `out_of_scope` | — | steps, media, tips, citations |
| `denied` | — | anything: answer text, steps, media, tips, citations, procedure, prerequisites |

Always finish with `self.provenance = derive_provenance(self.citations)` (contracts `:796`).
- `StepView.applicability` is `Literal["yes", "unknown"]` — a `"no"` step is never released (Q7, AC20);
  `applicability_note` must be non-empty when `"unknown"`.
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src`.

---

## Implementation Blueprint

### Steps (in order)
1. Append the citation + provenance helper — *why*: views and the answer reference it.
2. Append the view models — *why*: answers expose views, never raw graph rows or card internals.
3. Append `ProcedureAnswer` with the invariant table as code — *why*: the model is the last release gate.
4. Write tests covering every row of the table.

### `packages/ai-parrot/src/parrot/knowledge/manuals/models.py` (MODIFY)
```python
# occurrences: 1 (verify after TASK-3699 lands: grep -c 'def manual_snapshot_payload(card: ManualCard) -> dict\[str, Any\]:' packages/ai-parrot/src/parrot/knowledge/manuals/models.py)
# AFTER — append below the body of `def manual_snapshot_payload(card: ManualCard) -> dict[str, Any]:` (end of file, TASK-3699)


class ProcedureCitation(BaseModel):
    """One released evidence pointer pinned to an immutable manual version (mirrors contracts Citation :701-737)."""
    model_config = ConfigDict(extra="forbid")
    manual_id: str = Field(..., min_length=1); node_id: str = Field(..., min_length=1)
    quote: str = Field(..., min_length=1, max_length=MAX_QUOTE_CHARS); page: Optional[int] = Field(default=None, ge=1)
    verification: VerificationState = "extracted"; version_n: int = Field(default=1, ge=1); source_sha256: str = ""

    @field_validator("quote")
    @classmethod
    def _nonblank_quote(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a citation quote cannot be blank")
        return value

    @property
    def key(self) -> tuple[str, str]:
        """The ``(manual_id, node_id)`` pair."""
        return (self.manual_id, self.node_id)


def derive_provenance(citations: Sequence[ProcedureCitation]) -> AnswerProvenance:
    """Same rule as contracts/models.py:800-818."""
    # FILL IN: empty ⇒ "extracted"; all verified ⇒ "verified"; some ⇒ "mixed"; else "extracted"


class ProcedureRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    procedure_id: str; manual_id: str; slug: str; title: str; equipment_id: Optional[str] = None


class ProcedureView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    procedure_id: str; manual_id: str; title: str; kind: ProcedureKind; estimated_minutes: Optional[int] = None
    skill_level: Optional[str] = None; verification: VerificationState = "extracted"


class StepView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str; order: int = Field(..., ge=1); text: str = Field(..., min_length=1); torque: Optional[str] = None
    duration_minutes: Optional[int] = None; applicability: Literal["yes", "unknown"] = "yes"
    applicability_note: Optional[str] = None; part_ids: list[str] = Field(default_factory=list)
    tool_ids: list[str] = Field(default_factory=list); hazard_ids: list[str] = Field(default_factory=list)
    media_ids: list[str] = Field(default_factory=list)
    # FILL IN: model_validator — applicability == "unknown" ⇒ non-blank applicability_note (AC20)


class HazardView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hazard_id: str; severity: HazardSeverity; text: str; step_ids: list[str] = Field(default_factory=list)


class MediaView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_id: str; kind: MediaKind; role: MediaRole; step_id: Optional[str] = None; caption: Optional[str] = None
    label: Optional[str] = None; page: Optional[int] = None; t_start: Optional[float] = None; t_end: Optional[float] = None


class TipView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tip_id: str; step_id: str; text: str; author_employee_id: Optional[str] = None; created_at: Optional[datetime] = None


class Prerequisites(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parts: list[PartRef] = Field(default_factory=list); tools: list[ToolRef] = Field(default_factory=list)
    hazards: list[HazardView] = Field(default_factory=list)


class ProcedureAnswer(BaseModel):
    """The single channel-agnostic answer shape (spec §2). ``answer`` is the only model-authored field."""
    model_config = ConfigDict(extra="forbid")
    answer_kind: ProcedureAnswerKind; answer: str = ""; procedure: Optional[ProcedureView] = None
    steps: list[StepView] = Field(default_factory=list); prerequisites: Optional[Prerequisites] = None
    hazards: list[HazardView] = Field(default_factory=list); media: list[MediaView] = Field(default_factory=list)
    tips: list[TipView] = Field(default_factory=list); citations: list[ProcedureCitation] = Field(default_factory=list)
    provenance: AnswerProvenance = "extracted"; pattern: Optional[str] = None; reason: Optional[str] = None
    manual_revision: Optional[str] = None

    @model_validator(mode="after")
    def _check_kind_invariants(self) -> "ProcedureAnswer":
        # FILL IN: enforce the Implementation Notes table row by row (ValueError with a kind-specific message) — AC7
        self.provenance = derive_provenance(self.citations)
        return self
```
**Why**: the invariant table is the model-level form of R2 ("incomplete ⇒ no steps") and U4 ("provenance from
citations"); views keep graph internals and URLs out of every channel (G4, G5).

### FILL IN checklist
- [ ] `derive_provenance` — contracts rule
- [ ] `StepView` unknown ⇒ note validator
- [ ] `ProcedureAnswer._check_kind_invariants` — all nine kinds per the table
- [ ] tests below

---

## Acceptance Criteria

- [ ] `procedure` answer without steps or without citations ⇒ `ValueError`
- [ ] `incomplete` requires `reason` and rejects any step/media/tip (AC7)
- [ ] `denied` rejects every payload field
- [ ] `provenance` is derived even when the caller passes another value
- [ ] `ProcedureCitation(quote="  ")` rejected; `key` is `(manual_id, node_id)`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_answer_models.py -q`
- `pytest packages/ai-parrot/tests/knowledge/manuals/test_models.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/manuals/test_answer_models.py
import pytest

from parrot.knowledge.manuals.models import (ProcedureAnswer, ProcedureCitation, ProcedureView, StepView,
                                             derive_provenance)


def _cite(verified: bool = False) -> ProcedureCitation:
    return ProcedureCitation(manual_id="model-x-b", node_id="0003", quote="Torque to 12 Nm.", page=3,
                             verification="verified" if verified else "extracted")


def test_procedure_answer_kind_invariants():
    """procedure needs steps+citations; incomplete carries reason and no steps; denied carries nothing."""


def test_incomplete_releases_no_steps():
    with pytest.raises(ValueError):
        ProcedureAnswer(answer_kind="incomplete", reason="step 3 missing",
                        steps=[StepView(step_id="s1", order=1, text="Remove bolts.")])


def test_provenance_is_derived_not_trusted():
    answer = ProcedureAnswer(answer_kind="lookup", answer="See page 3.", citations=[_cite(True)], provenance="extracted")
    assert answer.provenance == "verified"


def test_derive_provenance_mixed():
    assert derive_provenance([_cite(True), _cite(False)]) == "mixed"


def test_unknown_applicability_requires_note():
    ...


def test_citation_rejects_blank_quote():
    ...
```

---

## Agent Instructions

1. Read spec §2 Data Models and §5 AC7.
2. Confirm TASK-3699 is done; re-run the anchor `grep -c` above (must be 1).
3. Update the per-spec index status → `in-progress`.
4. Implement from the blueprint; complete every `# FILL IN:`.
5. Run the Validation Commands with the worktree `PYTHONPATH`.
6. Move this file to `sdd/tasks/completed/`, update the index → `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
