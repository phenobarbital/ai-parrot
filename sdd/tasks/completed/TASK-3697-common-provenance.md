# TASK-3697: Extract shared provenance primitives to knowledge/common (M1)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 1** (decision U2, narrowed). The manuals plane (`parrot.knowledge.manuals`) needs the
same evidence primitives contracts already has — `Evidence`, `Extracted[T]`, `FieldProvenance`, `trim_quote`,
the quote cap and the unsubstantiated-confidence cap, plus the verbatim-quote validators — but it must
**not** import `parrot.knowledge.contracts`. This task moves the domain-neutral primitives into a new
`parrot.knowledge.common` package and turns the contracts definitions into re-exports, so every existing
contracts import resolves to the *same objects* (AC2). It is the root lane of the feature: TASK-3699 (models)
and TASK-3707 (carding) import from it.

Parallelism: root lane — creates `parrot.knowledge.common`; the only task touching `contracts/models.py` and
`contracts/carding.py`.

---

## Scope

- Create `parrot/knowledge/common/provenance.py` holding, **moved verbatim** from `contracts/models.py`:
  `MAX_QUOTE_CHARS`, `trim_quote`, `UNSUBSTANTIATED_CONFIDENCE_CAP`, `VerificationState`, `ProvenanceOrigin`,
  `AnswerProvenance`, `T`, `Evidence`, `Extracted`, `FieldProvenance`.
- Create `parrot/knowledge/common/validation.py` with public `normalize_whitespace`, `quote_supported`,
  `validate_extracted`, `load_bodies` — bodies moved verbatim from `contracts/carding.py`.
- Create `parrot/knowledge/common/__init__.py` re-exporting both modules' public names.
- In `contracts/models.py`: delete the moved definitions and import them from `..common.provenance`
  (names stay in contracts' `__all__`, which already lists `MAX_QUOTE_CHARS`, `Evidence`, `Extracted`,
  `FieldProvenance`, …).
- In `contracts/carding.py`: replace `_quote_supported`, `_normalize_whitespace`, `_validate_extracted` and
  `load_bodies` bodies with aliases to the common functions (private names kept — carding.py itself calls
  `_quote_supported` at 475, 513, 529, 589, 600 and `_validate_extracted` at 506).
- Write `tests/knowledge/common/test_provenance.py` (identity + behaviour) and `test_boundary.py` (AST scan).

**NOT in scope**: renaming `Citation.contract_id` / `EvidenceRef.contract_id`; moving `Citation`,
`ContractVersion`, `ContractAnswer`, `derive_provenance`, `EvidenceArchive` (they stay in contracts — spec §1
Non-Goals). No manuals code. No behaviour change of any kind (the 0.5 cap and verbatim check are preserved).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/common/__init__.py` | CREATE | Package facade re-exporting provenance + validation names |
| `packages/ai-parrot/src/parrot/knowledge/common/provenance.py` | CREATE | Evidence / Extracted / FieldProvenance / caps / literals (moved verbatim) |
| `packages/ai-parrot/src/parrot/knowledge/common/validation.py` | CREATE | normalize_whitespace / quote_supported / validate_extracted / load_bodies |
| `packages/ai-parrot/tests/knowledge/common/__init__.py` | CREATE | Test package marker |
| `packages/ai-parrot/tests/knowledge/common/test_provenance.py` | CREATE | Re-export identity + preserved behaviour |
| `packages/ai-parrot/tests/knowledge/common/test_boundary.py` | CREATE | AST import-boundary guard |
| `packages/ai-parrot/src/parrot/knowledge/contracts/models.py` | MODIFY | Replace moved definitions with re-exports |
| `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py` | MODIFY | Replace validator bodies with aliases |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field, field_validator, model_validator   # as used in contracts/models.py:20
from typing import Any, Callable, Generic, Iterable, Literal, Mapping, Optional, TypeVar
import asyncio, logging
# After this task (created here):
from parrot.knowledge.common.provenance import (MAX_QUOTE_CHARS, UNSUBSTANTIATED_CONFIDENCE_CAP, VerificationState,
    ProvenanceOrigin, AnswerProvenance, trim_quote, Evidence, Extracted, FieldProvenance)
from parrot.knowledge.common.validation import normalize_whitespace, quote_supported, validate_extracted, load_bodies
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/contracts/models.py
MAX_QUOTE_CHARS = 300                                           # :88
def trim_quote(value: Any) -> Any                               # :91-105 (word-boundary trim)
UNSUBSTANTIATED_CONFIDENCE_CAP = 0.5                            # :111
VerificationState = Literal["extracted", "verified", "stale"]  # :161
ProvenanceOrigin = Literal["llm", "rule", "manual"]            # :162
AnswerProvenance = Literal["verified", "mixed", "extracted"]   # :175
class Evidence(BaseModel):                                      # :205-229
    node_id: str = Field(..., min_length=1); quote: str = Field(default="", max_length=MAX_QUOTE_CHARS)
    _trim_quote field_validator("quote", mode="before"); page: Optional[int] = Field(default=None, ge=1)
    @property substantiates -> bool                             # PROPERTY, not a method (spec §3 wrote substantiates())
T = TypeVar("T")                                                # :232
class Extracted(BaseModel, Generic[T]):                         # :235-262 value/evidence/confidence; _cap_unsubstantiated_confidence; @property substantiated
class FieldProvenance(BaseModel):                               # :265-311 origin/verification/node_id/page/quote/confidence/verified_by/verified_at/derived_from/candidate; _check_axes; @property substantiates
__all__ = (...)  # :24-84 — a tuple already naming MAX_QUOTE_CHARS, UNSUBSTANTIATED_CONFIDENCE_CAP, VerificationState,
                 #   ProvenanceOrigin, AnswerProvenance, Evidence, Extracted, FieldProvenance (keep it unchanged)
from ..bookstore.models import TocEntry                         # :22 (stays)

# packages/ai-parrot/src/parrot/knowledge/contracts/carding.py
from .models import (UNSUBSTANTIATED_CONFIDENCE_CAP, ..., Evidence, Extracted, ...)   # :27-45 (keeps working via re-export)
async def load_bodies(loader: Callable[[str], Optional[str]], node_ids: Iterable[str]) -> dict[str, str]   # :185-213 (asyncio.to_thread; logger.debug on unreadable)
def _quote_supported(evidence: Optional[Evidence], bodies: Mapping[str, str]) -> bool   # :456-463
def _normalize_whitespace(text: str) -> str                                            # :466-468
def _validate_extracted(field: Extracted[Any], bodies: Mapping[str, str]) -> tuple[Extracted[Any], bool]  # :471-483
logger = logging.getLogger(__name__)  # module logger used by load_bodies
```

### Does NOT Exist
- ~~`parrot.knowledge.common`~~ — created by this task.
- ~~`Evidence.substantiates()` as a method~~ — it is a `@property`; call sites use `evidence.substantiates`.
- ~~`Citation.key()` as a method~~ — also a `@property` (relevant to TASK-3700, not moved here).
- ~~A `doc_id` field on `Citation`/`EvidenceRef`~~ — not renamed (spec Non-Goal).
- ~~`load_bodies(..., node_ids: Sequence[str])`~~ — the real annotation is `Iterable[str]`; keep it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/common/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/common/provenance.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/common/validation.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/common/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/common/test_provenance.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/common/test_boundary.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/contracts/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/contracts/carding.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/models.py#trim_quote",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/models.py#Evidence",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/models.py#Extracted",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/models.py#FieldProvenance",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/carding.py#load_bodies",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/carding.py#_quote_supported",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/carding.py#_normalize_whitespace",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/carding.py#_validate_extracted"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Byte-compatible behaviour**: move code, do not rewrite it. Serialized payloads, validator messages and the
  0.5 cap must be identical; `packages/ai-parrot/tests/knowledge/contracts/` must pass unchanged (AC2).
- `knowledge/common` must import nothing from `contracts`, `parrot_tools`, `asyncpg` or `arango` (test_boundary).
- Pydantic generic identity: `Extracted` must be the *same class object* in both modules — define it once in
  `common/provenance.py` only; contracts imports it. Never redefine or subclass.
- Worktree tests: run with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src`.
- No new third-party deps; Google docstrings; module `logger = logging.getLogger(__name__)`; never `print`.

### References in Codebase
- `packages/ai-parrot/tests/knowledge/contracts/test_dependency_boundary.py` — AST boundary-test pattern (REPO_ROOT = `parents[5]` from a file under `tests/knowledge/contracts/`; from `tests/knowledge/common/` it is also `parents[5]`).

---

## Implementation Blueprint

### Steps (in order)
1. Create `common/provenance.py` by cutting `contracts/models.py:87-111`, `:159-162`, `:175`, `:200-311` — *why*: one definition, so identity checks hold.
2. Create `common/validation.py` from `contracts/carding.py:185-213, 456-483`, renaming to public names — *why*: manuals (TASK-3707) calls them without importing contracts.
3. Create `common/__init__.py` re-exporting both — *why*: stable facade for `from parrot.knowledge.common import …`.
4. Edit `contracts/models.py` to import the moved names — *why*: preserve every old import path (AC2).
5. Edit `contracts/carding.py` to alias the private helpers — *why*: its internal call sites keep working unchanged.
6. Write tests; run the whole contracts suite as a regression check — *why*: AC2 requires it to pass unchanged.

### `packages/ai-parrot/src/parrot/knowledge/common/provenance.py` (CREATE)
```python
"""Domain-neutral evidence and provenance primitives (FEAT-601 M1).

Moved verbatim from ``parrot.knowledge.contracts.models`` so that other
knowledge planes (manuals) can share them without importing contracts.
``parrot.knowledge.contracts.models`` re-exports every name defined here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

__all__ = (
    "MAX_QUOTE_CHARS",
    "UNSUBSTANTIATED_CONFIDENCE_CAP",
    "VerificationState",
    "ProvenanceOrigin",
    "AnswerProvenance",
    "trim_quote",
    "Evidence",
    "Extracted",
    "FieldProvenance",
)

#: Hard cap for any evidential quote persisted or released (spec §2).
MAX_QUOTE_CHARS = 300

# FILL IN: paste `trim_quote` verbatim from contracts/models.py:91-105 — bounded by AC2 (no behaviour change)

#: An absent or invalid quote caps extraction confidence at this value.
UNSUBSTANTIATED_CONFIDENCE_CAP = 0.5

VerificationState = Literal["extracted", "verified", "stale"]
ProvenanceOrigin = Literal["llm", "rule", "manual"]
AnswerProvenance = Literal["verified", "mixed", "extracted"]

T = TypeVar("T")

# FILL IN: paste `class Evidence`, `class Extracted(BaseModel, Generic[T])` and `class FieldProvenance`
#   verbatim from contracts/models.py:205-311 (docstrings, validators and properties included) — bounded by AC2
```
**Why this shape**: a single home for the classes guarantees `contracts.models.Evidence is common.provenance.Evidence`.
The literals and caps travel with them because the validators reference them.

### `packages/ai-parrot/src/parrot/knowledge/common/validation.py` (CREATE)
```python
"""Verbatim-quote validation helpers shared by knowledge carding passes (FEAT-601 M1)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Iterable, Mapping, Optional

from .provenance import UNSUBSTANTIATED_CONFIDENCE_CAP, Evidence, Extracted

__all__ = ("normalize_whitespace", "quote_supported", "validate_extracted", "load_bodies")

logger = logging.getLogger(__name__)


def normalize_whitespace(text: str) -> str:
    """Collapse whitespace so re-wrapped quotes still match their source."""
    return " ".join(text.split())


def quote_supported(evidence: Optional[Evidence], bodies: Mapping[str, str]) -> bool:
    """Whether an evidence quote appears verbatim in its cited node body."""
    # FILL IN: body of contracts/carding.py:458-463 using normalize_whitespace — bounded by AC2


def validate_extracted(field: Extracted[Any], bodies: Mapping[str, str]) -> tuple[Extracted[Any], bool]:
    """Drop unsupported evidence and cap the resulting confidence."""
    # FILL IN: body of contracts/carding.py:473-483 using quote_supported — bounded by AC2


async def load_bodies(loader: Callable[[str], Optional[str]], node_ids: Iterable[str]) -> dict[str, str]:
    """Read node bodies off the event loop; returns only nonempty bodies keyed by node id."""
    # FILL IN: body of contracts/carding.py:198-213 (asyncio.to_thread, logger.debug on unreadable) — bounded by AC2
```
**Why**: public names are the API manuals uses; bodies stay identical to keep contracts' behaviour.

### `packages/ai-parrot/src/parrot/knowledge/common/__init__.py` (CREATE)
```python
"""Shared, domain-neutral knowledge primitives (FEAT-601 M1). Imports no satellite or database driver."""

from .provenance import (
    MAX_QUOTE_CHARS,
    UNSUBSTANTIATED_CONFIDENCE_CAP,
    AnswerProvenance,
    Evidence,
    Extracted,
    FieldProvenance,
    ProvenanceOrigin,
    VerificationState,
    trim_quote,
)
from .validation import load_bodies, normalize_whitespace, quote_supported, validate_extracted

__all__ = (
    "MAX_QUOTE_CHARS", "UNSUBSTANTIATED_CONFIDENCE_CAP", "AnswerProvenance", "Evidence", "Extracted",
    "FieldProvenance", "ProvenanceOrigin", "VerificationState", "trim_quote",
    "load_bodies", "normalize_whitespace", "quote_supported", "validate_extracted",
)
```

### `packages/ai-parrot/src/parrot/knowledge/contracts/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'MAX_QUOTE_CHARS = 300' packages/ai-parrot/src/parrot/knowledge/contracts/models.py)
# REPLACE — the block from `#: Hard cap for any evidential quote` (:87) through `UNSUBSTANTIATED_CONFIDENCE_CAP = 0.5` (:111)
from ..common.provenance import (  # noqa: F401 — compatibility re-exports (FEAT-601 M1)
    MAX_QUOTE_CHARS,
    UNSUBSTANTIATED_CONFIDENCE_CAP,
    AnswerProvenance,
    Evidence,
    Extracted,
    FieldProvenance,
    ProvenanceOrigin,
    VerificationState,
    trim_quote,
)
from ..common.provenance import T  # noqa: F401 — generic parameter kept importable
# occurrences: 1 each (verified: grep -c 'class Evidence(BaseModel):' / 'class Extracted(BaseModel, Generic[T]):' /
#   'class FieldProvenance(BaseModel):' models.py) — DELETE the three class bodies (:205-311) and `T = TypeVar("T")` (:232)
# DELETE `VerificationState = …` / `ProvenanceOrigin = …` (:161-162) and `AnswerProvenance = …` (:175)
# FILL IN: remove now-unused imports (Generic/TypeVar) ONLY if ruff flags them — bounded by "keep __all__ (:24-84) unchanged"
```
**Why**: every existing `from parrot.knowledge.contracts.models import Evidence` keeps resolving, to the same object.

### `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _quote_supported(evidence: Optional[Evidence], bodies: Mapping[str, str]) -> bool:' carding.py)
# occurrences: 1 (verified: grep -c 'def _validate_extracted(field: Extracted[Any], bodies: Mapping[str, str]) -> tuple[Extracted[Any], bool]:' carding.py)
# REPLACE — the three definitions at :456-483 with:
from ..common.validation import normalize_whitespace, quote_supported, validate_extracted  # noqa: E402

_quote_supported = quote_supported
_normalize_whitespace = normalize_whitespace
_validate_extracted = validate_extracted
# occurrences: 1 (verified: grep -c 'async def load_bodies(' carding.py) — REPLACE :185-213 with:
from ..common.validation import load_bodies  # noqa: E402,F401 — re-exported (was defined here)
# FILL IN: place the imports at the top import block (after `from .standards import …` :46) instead of inline if
#   ruff E402 fires — bounded by "call sites at :475/:506/:513/:529/:589/:600 stay untouched"
```
**Why**: aliases keep the private names that carding.py and its tests use; no call site changes.

### `packages/ai-parrot/tests/knowledge/common/test_boundary.py` (CREATE)
```python
"""knowledge/common must stay domain-neutral (FEAT-601 M1)."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
COMMON_SRC = REPO_ROOT / "packages" / "ai-parrot" / "src" / "parrot" / "knowledge" / "common"
FORBIDDEN = ("parrot.knowledge.contracts", "parrot_tools", "asyncpg", "arango")


def _imported_modules(path: Path) -> set[str]:
    """Absolute module names imported by one file (relative imports resolved against knowledge.common)."""
    # FILL IN: ast.walk over Import/ImportFrom; resolve level>0 relative imports — bounded by FORBIDDEN list


def test_common_import_boundary() -> None:
    # FILL IN: assert COMMON_SRC.is_dir(); for every *.py, no imported module startswith any FORBIDDEN prefix
    ...
```

### FILL IN checklist
- [ ] `provenance.py` — verbatim copies of `trim_quote`, `Evidence`, `Extracted`, `FieldProvenance`; bounded by AC2
- [ ] `validation.py` — verbatim bodies of the four helpers; bounded by AC2
- [ ] `contracts/models.py` — delete moved defs, add re-export import; `__all__` untouched
- [ ] `contracts/carding.py` — aliases + load_bodies re-export; import placement per ruff
- [ ] `test_boundary.py::_imported_modules` — relative-import resolution
- [ ] tests in `test_provenance.py` (below)

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.common.provenance import Evidence, Extracted, FieldProvenance, trim_quote` works (AC2)
- [ ] `parrot.knowledge.contracts.models.Evidence is parrot.knowledge.common.provenance.Evidence` (and Extracted, FieldProvenance, trim_quote, caps)
- [ ] `parrot.knowledge.contracts.carding._quote_supported is parrot.knowledge.common.validation.quote_supported`
- [ ] `packages/ai-parrot/tests/knowledge/contracts/` passes unchanged (spot-check with the files below)
- [ ] `knowledge/common` imports no `contracts`, `parrot_tools`, `asyncpg`, `arango`
- [ ] `ruff check` clean on all touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/common/test_provenance.py -q`
- `pytest packages/ai-parrot/tests/knowledge/common/test_boundary.py -q`
- `pytest packages/ai-parrot/tests/knowledge/contracts/test_models.py -q`
- `pytest packages/ai-parrot/tests/knowledge/contracts/test_carding.py -q`
- `pytest packages/ai-parrot/tests/knowledge/contracts/test_dependency_boundary.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/common/test_provenance.py
import pytest

from parrot.knowledge.common import provenance, validation
from parrot.knowledge.contracts import carding as contracts_carding
from parrot.knowledge.contracts import models as contracts_models


def test_common_reexports_identity():
    for name in ("Evidence", "Extracted", "FieldProvenance", "trim_quote",
                 "MAX_QUOTE_CHARS", "UNSUBSTANTIATED_CONFIDENCE_CAP"):
        assert getattr(contracts_models, name) is getattr(provenance, name)
    assert contracts_carding._quote_supported is validation.quote_supported
    assert contracts_carding._validate_extracted is validation.validate_extracted


def test_unsubstantiated_confidence_is_capped():
    field = provenance.Extracted[str](value="x", evidence=None, confidence=0.9)
    assert field.confidence == provenance.UNSUBSTANTIATED_CONFIDENCE_CAP


def test_quote_supported_is_whitespace_insensitive():
    ev = provenance.Evidence(node_id="0001", quote="torque  to 12 Nm")
    assert validation.quote_supported(ev, {"0001": "Then torque to\n12 Nm."})


def test_validate_extracted_drops_unsupported_quote():
    ...


def test_trim_quote_word_boundary():
    ...


async def test_load_bodies_skips_empty_and_unreadable():
    ...
```

---

## Agent Instructions

1. Read the spec §3 Module 1 and §5 AC2.
2. Confirm dependencies (none) and re-verify every line number above with `grep -n`.
3. Update the per-spec index status → `in-progress`.
4. Implement from the blueprint; complete every `# FILL IN:`; do not change signatures or paths.
5. Run the Validation Commands (with the worktree `PYTHONPATH`).
6. Move this file to `sdd/tasks/completed/`, update the index → `done`, fill the Completion Note.

---

## Completion Note


- Task: TASK-3697
- Feature: training-agent
- Implementation SHA: 4f5e0cc575a567a0104cde4abbe7147e0109d354
- Closed at (UTC): 2026-09-24T23:20:28+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 307.3s · Tokens: n/a |
| supplementary_test_evidence | 460 passed, 56 skipped, 0 failed (scoped direct pytest run over common/pageindex/contracts) |
