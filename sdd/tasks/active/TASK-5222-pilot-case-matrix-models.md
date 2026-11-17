# TASK-5222: Pilot case matrix models (M1)

**Feature**: FEAT-815 — Contracts Pilot Signoff & End-to-End Validation
**Spec**: `sdd/specs/contracts-pilot-signoff-e2e.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 M1 (W1). Covers AC1 and the model half of AC10. Pure data models — no catalog access.

## Scope

- Create `pilot.py` with `PilotCase`, `CaseDisposition`, `CaseMatrix`, `PilotSignoff` (spec §3 M1 skeleton; signatures are fixed).
- Tighten the skeleton's string enums to `Literal` types (`source`: `client_initial|common`; `disposition`: `pass|fail|skip|handoff`) — `handoff` is added because the FEAT-539 wiki page defines a handoff on an interpretation question as a pass-equivalent outcome.
- `CaseMatrix.from_yaml(path)` loader + validator: exactly 12 cases, unique `case_id`, exactly 2 `client_initial` + 10 `common`.
- Create the YAML template with 12 **placeholder** cases (questions read `<pending: Bob>`); never invent real questions.
- Unit tests for loading/validation.

**NOT in scope**: CLI (TASK-5223), any catalog/lookup execution, E2E work, wiki edits.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/contracts/pilot.py` | CREATE | Pilot models + YAML loader |
| `sdd/state/FEAT-815/case_matrix_template.yaml` | CREATE | 12 placeholder cases |
| `packages/ai-parrot/tests/knowledge/contracts/test_pilot_matrix.py` | CREATE | AC1 unit tests |

## Codebase Contract (Anti-Hallucination)

Re-verified on 2026-11-05 against `dev` (post `71ef3ad4c8`).

### Verified Imports

```python
from pydantic import BaseModel, Field, field_validator, model_validator  # pydantic v2, in tree
import yaml  # PyYAML, in tree (spec §7)
```

### Existing Signatures to Use

No existing signatures are extended — `pilot.py` is a new leaf module with no parrot imports.

### Does NOT Exist

- ~~`parrot.knowledge.contracts.temporal.TemporalDrain`~~ — does not exist; the spec §6 name is wrong. The drain lives on `ContractTemporalPublisher.drain(ctx, *, limit=10) -> TemporalDrainReport` (`temporal.py:156,184`).
- ~~`parrot.knowledge.contracts.datasource.ContractDatasource`~~ — wrong name; the class is `ContractCardDataSource` (`datasource.py:130`).
- ~~`ContractCatalogStore.lookup()` / `.query()`~~ — no such methods; use `search(query, top_k=8) -> list[SearchHit]` (`catalog.py:398`) and `get(contract_id)` (`catalog.py:367`).
- ~~A default Postgres DSN~~ — `PostgresContractCatalog` refuses to build without explicit `dsn` or `pool` (`catalog_postgres.py:294`).
- ~~`parrot.knowledge.contracts.models.PilotCase`~~ — pilot models live only in the new `pilot.py`.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/contracts/pilot.py",
      "action": "CREATE"
    },
    {
      "path": "sdd/state/FEAT-815/case_matrix_template.yaml",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/contracts/test_pilot_matrix.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

- Pydantic v2, strict type hints, Google docstrings, `logging.getLogger(__name__)` — never `print` (CLI output goes through `click.echo`).
- No real contract text anywhere in committed files (spec AC10): evidence is referenced only by `contract_id` / `node_id` / `version_n` / `answer_id`.
- Parallelism: root task, no dependencies; creates `parrot.knowledge.contracts.pilot` consumed by TASK-5223 and TASK-5228.

## Implementation Blueprint

### Steps (in order)

1. Create `pilot.py` from the block below — the skeleton signatures are fixed by spec §3 M1.
2. Fill the validator and `complete` property.
3. Write the YAML template with all 12 placeholder entries — because the test loads it as a fixture.
4. Write the tests, run them, `ruff check` the new files.

#### `packages/ai-parrot/src/parrot/knowledge/contracts/pilot.py` (CREATE)

```python
"""Pilot acceptance models for the contracts card (FEAT-815, W1)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

CaseSource = Literal["client_initial", "common"]
Disposition = Literal["pass", "fail", "skip", "handoff"]
EXPECTED_CASES = 12
EXPECTED_CLIENT_INITIAL = 2


class PilotCase(BaseModel):
    """One of the twelve review cases."""

    case_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    expected_answer: Optional[str] = None
    source: CaseSource


class CaseDisposition(BaseModel):
    """Reviewer's disposition for one case; evidence is by reference only (AC10)."""

    case_id: str = Field(..., min_length=1)
    actual_answer: Optional[str] = None
    citations: list[str] = Field(default_factory=list)  # "<contract_id>#<node_id>@v<version_n>" refs
    answer_id: Optional[str] = None
    feedback: str = ""
    disposition: Disposition
    reviewer: str = Field(..., min_length=1)
    reviewed_at: datetime


class CaseMatrix(BaseModel):
    """The full twelve-case review matrix."""

    cases: list[PilotCase]

    @model_validator(mode="after")
    def _check_shape(self) -> "CaseMatrix":
        # FILL IN: enforce len == EXPECTED_CASES, unique case_id, exactly EXPECTED_CLIENT_INITIAL
        #          client_initial cases — bounded by AC1; raise ValueError naming the offending ids.
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> "CaseMatrix":
        """Load and validate a matrix file; raises ValueError on a malformed file."""
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)


class PilotSignoff(BaseModel):
    """Explicit signoff record; ``signed_off_at`` stays None until the reviewer signs."""

    feature_id: str = "FEAT-815"
    reviewer: str
    signed_off_at: Optional[datetime] = None
    dispositions: list[CaseDisposition] = Field(default_factory=list)
    notes: str = ""

    @property
    def complete(self) -> bool:
        """True only when every case of the matrix has a disposition and the reviewer signed."""
        # FILL IN: signed_off_at is not None and len({d.case_id for d in dispositions}) == EXPECTED_CASES
        ...
```

**Why**: `Literal` instead of bare `str` so a typo'd disposition fails at load, not at signoff time; `datetime` instead of the skeleton's ISO `str` because Pydantic serialises it to ISO-8601 anyway and validates it on the way in. `yaml.safe_load` — never `yaml.load` — because the matrix is an operator-supplied file.

#### `sdd/state/FEAT-815/case_matrix_template.yaml` (CREATE)

```yaml
# Twelve-case pilot matrix (FEAT-815). Replace every <pending: Bob> with Bob's verbatim wording.
# Never paste contract text here — expected answers reference contract_id/node_id only.
cases:
  - {case_id: C1, source: client_initial, question: "<pending: Bob>", expected_answer: null}
  - {case_id: C2, source: client_initial, question: "<pending: Bob>", expected_answer: null}
  # FILL IN: Q1..Q10 with source: common, same shape (12 entries total — AC1)
```

**Why**: the template must itself pass `CaseMatrix.from_yaml` so the CLI can be exercised before Bob's inputs arrive.


### FILL IN checklist

- [ ] `CaseMatrix._check_shape` — count, uniqueness, 2+10 split (AC1)
- [ ] `PilotSignoff.complete`
- [ ] Remaining 10 template entries
- [ ] Test bodies (see Test Specification)

## Acceptance Criteria

- [ ] `CaseMatrix.from_yaml("sdd/state/FEAT-815/case_matrix_template.yaml")` returns 12 cases (AC1).
- [ ] 11 or 13 cases, a duplicate `case_id`, or a wrong client/common split each raise `ValueError`.
- [ ] An unknown `disposition` value is rejected.
- [ ] No contract text in the template (AC10).

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/contracts/test_pilot_matrix.py -q`

## Test Specification

| Test | Verifies |
|---|---|
| `test_template_loads_twelve_cases` | template file validates (AC1) |
| `test_wrong_case_count_rejected` | 11 and 13 cases fail |
| `test_duplicate_case_id_rejected` | uniqueness |
| `test_client_common_split_enforced` | 2 + 10 |
| `test_unknown_disposition_rejected` | Literal guard |
| `test_signoff_complete_requires_signature_and_all_cases` | `complete` |

## Agent Instructions

1. Read the spec and this task; confirm every `Depends-on` task is `done` in `sdd/tasks/index/contracts-pilot-signoff-e2e.json`.
2. Work in the feature worktree `feat-FEAT-815-contracts-pilot-signoff-e2e`; verify each Codebase Contract entry before writing code.
3. Implement only the files listed above; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Close with `parrot sdd task close TASK-5222 contracts-pilot-signoff-e2e verified` and fill in the Completion Note.

## Completion Note

*(Agent fills this in when done)*
