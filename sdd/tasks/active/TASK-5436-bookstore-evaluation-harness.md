# TASK-5436: Build pinned-question agentic evaluation harness

**Feature**: FEAT-858 — Bookstore Agentic Retrieval
**Spec**: `sdd/specs/bookstore-agentic-retrieval.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h; host wall time depends on provider when applicable)
**Depends-on**: TASK-5428
**Assigned-to**: unassigned

## Context

Implement this bounded deliverable of the approved FEAT-858 spec. Its behavioral authority
is the spec's §2 and owning §3 module, with §4 validation and §5 acceptance criteria.
Verified source base: `8387cd3e1b604955928064ff51a2fa207deceb36`. No implementation has been performed by this planning task.

## Scope

- Implement spec M6 EvalQuestion/EvalSettings/generate_questions/evaluate_library/main with frozen signatures.
- Validate exactly one gold kind, positive concurrency, immutable document/revision/generation addresses; reject stale fixtures before affected rows.
- Support explicit one-time generation of five >=40-token-segment questions per book, deterministic seed and bounded repair; never overwrite a fixture implicitly.
- Run exactly 56 baseline plus 84 handwritten sweeps, one independent Bookstore+client per worker, bounded invocation counts and safe error categories.
- Write metric-only timestamped report/JSON with all denominators, provenance split, tree shape and hashes; no excerpts/answers/provider error text.
- Apply the exact >=112/140 and >=17/21 coverage gates and fixed quality/median tie-break rule; never combine untested winning knobs. Do not run the host corpus in this task.

**NOT in scope**: files outside the table, provider SDK calls, PageIndex loop/validator changes,
unrelated refactoring, new dependencies, and other tasks' deliverables.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/agentic_eval.py` | CREATE | Scoped deliverable described above |
| `packages/ai-parrot/tests/knowledge/bookstore/test_agentic_eval.py` | CREATE | Task regression coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations  # verified: Python language; existing library.py:17
from pathlib import Path  # verified: stdlib; existing library.py:26
from typing import Any, Literal, Optional  # verified: stdlib typing; existing source annotations above
from pydantic import BaseModel  # verified: packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py:9; core pyproject.toml:54
from parrot.knowledge.bookstore._llm import resolve_adapter  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py:42
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:112,179
import pytest  # verified: existing Bookstore test_toolkit.py:5
from typing import Literal  # verified: stdlib; pageindex/agentic.py imports Literal
from typing import Any, Optional  # verified: stdlib; existing library.py:27
```

### Same-task planned import

`from parrot.knowledge.bookstore.agentic_eval import EvalQuestion, EvalSettings, generate_questions, evaluate_library` — Created by this task in packages/ai-parrot/src/parrot/knowledge/bookstore/agentic_eval.py; planned import, not present at base.

### Existing Signatures to Use

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:179
class Bookstore:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py:42
def resolve_adapter(
    llm_spec: Optional[str] = None,
    lightweight_model: Optional[str] = None,
) -> tuple[Optional[Any], Optional[str], Optional[Any]]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py:72
class EvidenceBundle(BaseModel):
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_eval.py:70
class EvalReport(BaseModel):
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py:59
class DocumentRevision(BaseModel):
```


### Dependency-produced contracts

- TASK-5428: consumes Bookstore.agentic_retrieve for the evaluation harness

Those newly created symbols/files are planned contracts, not claims that they exist at this base. Read prerequisite commits before implementation.

### Does NOT Exist

- parrot.knowledge.bookstore.agentic_eval does not exist; no golden evaluation fixture has been validated.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/agentic_eval.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_agentic_eval.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py#resolve_adapter",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py#EvidenceBundle",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_eval.py#EvalReport",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#DocumentRevision",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#BookstoreError"
  ]
}
```

## Implementation Notes

TASK-5428: consumes Bookstore.agentic_retrieve for the evaluation harness

Use the activated project environment, async I/O, strict types, Google-style docstrings,
self.logger and existing dependency patterns. Do not alter shared conftest.py. This task
has no Delegation Contract: its behavioral branches/tests or host evidence still require
normal implementation reasoning; blueprint placeholders are planning instructions only.

## Implementation Blueprint

### Steps (in order)

1. Implement spec M6 EvalQuestion/EvalSettings/generate_questions/evaluate_library/main with frozen signatures. **Why**: Models and CLI enforce the frozen schema and stale-address rules; generated gold comes from the supplied source address, not model output.
2. Validate exactly one gold kind, positive concurrency, immutable document/revision/generation addresses; reject stale fixtures before affected rows. **Why**: Synthetic execution creates exactly 140 planned rows, preserving skipped/error denominators and provenance.
3. Support explicit one-time generation of five >=40-token-segment questions per book, deterministic seed and bounded repair; never overwrite a fixture implicitly. **Why**: Coverage and recommendation logic matches spec §4 exactly, including safe error fields and baseline/tie rules.
4. Run exactly 56 baseline plus 84 handwritten sweeps, one independent Bookstore+client per worker, bounded invocation counts and safe error categories. **Why**: Reports contain only permitted metrics/IDs/hashes; tests use fake clients and temporary corpus, never credentials or real provider calls.
5. Write metric-only timestamped report/JSON with all denominators, provenance split, tree shape and hashes; no excerpts/answers/provider error text. **Why**: Models and CLI enforce the frozen schema and stale-address rules; generated gold comes from the supplied source address, not model output.
6. Apply the exact >=112/140 and >=17/21 coverage gates and fixed quality/median tie-break rule; never combine untested winning knobs. Do not run the host corpus in this task. **Why**: Synthetic execution creates exactly 140 planned rows, preserving skipped/error denominators and provenance.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/agentic_eval.py` (CREATE)

```python
"""Host evaluation for Bookstore agentic retrieval; persist metrics, never source text."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Literal, Optional
from pydantic import BaseModel
from parrot.knowledge.bookstore._llm import resolve_adapter
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError

class EvalQuestion(BaseModel):
    """Question provenance and exactly one pinned gold address."""
    question_id: str
    book_id: str
    question: str
    provenance: Literal["handwritten", "generated"]
    doc_id: str
    revision: str
    generation: int
    gold_kind: Literal["seq", "node", "page"]
    gold_seq: Optional[int] = None
    gold_node_id: Optional[str] = None
    gold_page: Optional[int] = None
    # FILL IN: Pydantic v2 validators for one valid gold kind and nonempty IDs; AC-1.

class EvalSettings(BaseModel):
    """Validated corpus paths and experiment settings."""
    library: Path
    questions: Path
    llm: str = "google:gemini-3.5-flash-lite"
    concurrency: int = 1
    out_dir: Path = Path("artifacts/logs/bookstore_agentic_eval")
    # FILL IN: validated positive concurrency and safe paths; AC-1, AC-4.

async def generate_questions(settings: EvalSettings) -> list[EvalQuestion]:
    """Generate questions once from known >=40-token segments without saving source text."""
    # FILL IN: deterministic seed, frozen sampled addresses, at most one repair/question; AC-1.
    raise NotImplementedError

async def evaluate_library(settings: EvalSettings) -> dict[str, Any]:
    """Run the frozen 140-row plan and return numeric report paths and recommendation."""
    # FILL IN: bounded scheduling, stale fixtures, metrics, exact selection policy; AC-2..AC-4.
    raise NotImplementedError

def main(argv: Optional[list[str]] = None) -> int:
    """Run library/questions/llm/concurrency options or explicit generate-questions mode."""
    # FILL IN: CLI boundary, no implicit corpus mutation or fixture overwrite; AC-1, AC-4.
    raise NotImplementedError

if __name__ == "__main__":
    raise SystemExit(main())
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot/tests/knowledge/bookstore/test_agentic_eval.py` (CREATE)

```python
"""Deterministic evaluation-plan, scoring, coverage and privacy regressions."""
from parrot.knowledge.bookstore.agentic_eval import EvalQuestion, EvalSettings, generate_questions, evaluate_library
from pathlib import Path
import pytest

def test_frozen_plan_has_140_rows() -> None:
    """Baseline and one-dimensional sweeps use exact denominators/provenance."""
    # FILL IN: synthetic 7-book fixture, no model; AC-2.
    raise NotImplementedError

def test_coverage_quality_and_tie_policy() -> None:
    """Insufficient evidence cannot tune and untested knob combinations never win."""
    # FILL IN: table-driven numeric rows for boundaries and ties; AC-3.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_stale_fixture_and_report_privacy(tmp_path: Path) -> None:
    """Stale gold is not scored and unsafe provider payloads never persist."""
    # FILL IN: fake failures containing source text, inspect every report artifact; AC-1, AC-4.
    raise NotImplementedError
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/bookstore/agentic_eval.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot/tests/knowledge/bookstore/test_agentic_eval.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.

## Acceptance Criteria

- [ ] AC-1: Models and CLI enforce the frozen schema and stale-address rules; generated gold comes from the supplied source address, not model output.
- [ ] AC-2: Synthetic execution creates exactly 140 planned rows, preserving skipped/error denominators and provenance.
- [ ] AC-3: Coverage and recommendation logic matches spec §4 exactly, including safe error fields and baseline/tie rules.
- [ ] AC-4: Reports contain only permitted metrics/IDs/hashes; tests use fake clients and temporary corpus, never credentials or real provider calls.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_agentic_eval.py -q`

## Test Specification

Exercise the observable cases in the blueprint and AC-1..AC-4 with synthetic temporary
state and bounded synchronization. Existing operands listed above are regression gates,
not authorization to edit them unless they appear in the file table. No live provider
calls in pytest. Save execution logs under artifacts/logs/.


## Agent Instructions

1. Run `$sdd-start TASK-5436` to provision the feature worktree; do not implement on dev.
2. Read the approved spec and dependency evidence before editing.
3. Reverify every MODIFY anchor; dependency-created files must be inspected after their creators land.
4. Implement only the declared files; final code must contain no blueprint placeholders.
5. Run the Validation Commands and appropriate formatting/lint checks; retain real logs.
6. Commit scoped work and finalize with `parrot sdd task finalize` using actual completion evidence.

## Completion Note

Populated by the task finalizer after implementation, validation and the exact implementation commit.
