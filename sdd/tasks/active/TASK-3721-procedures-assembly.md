# TASK-3721: Pure assemble_procedure with serial applicability filter (M10)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3700, TASK-3720
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 10** (`assembly.py`) and goals **G1** (deterministic decides), **G10/Q7** (serial applicability). `assemble_procedure` is the pure, total function that turns one `RetrievalResult` (traversal rows + the selected `ManualCard` revision, TASK-3720) into an `AssembledProcedure`: ordered steps, union of prerequisites, inlined hazards, media by role, active tips, and citations built from step evidence. It **records** gaps (`missing_required`, `unsupported_fields`) and never fills them — the blocking decision belongs to `ProcedureVerifier` (TASK-3722, R2).

Covers spec §4 tests `test_assemble_procedure_complete_and_gaps`, `test_assemble_filters_by_serial_and_flags_unknown`; contributes to AC6 (orphaned tips excluded), AC7, AC20.

---

## Scope

- Create `parrot_tools/procedures/assembly.py` with `AssembledProcedure` and `assemble_procedure(...)`.
- Order steps by `has_step.order`; check `precedes` consistency (explicit `precedes` edges must agree with order, else record a gap).
- Union prerequisites (parts/tools across steps) **deduplicated by `_key`/id** (FEAT-539 lesson).
- Inline hazards per step and at procedure level; pick media by roles (primary first; `overview` at procedure level).
- Exclude tips whose row has `orphaned=true`, `active=false`, or whose target step is inactive.
- Build `ProcedureCitation`s from each released step's `text.evidence` (`node_id`, `page`, `quote`) for the selected revision (`version_n`, `source_sha256`).
- Apply `applies(step, model=…, serial=…)` (TASK-3699): `"no"` ⇒ excluded and listed in `filtered_by_serial`; `"unknown"` ⇒ kept with `StepView.applicability="unknown"`; `needs_serial=True` when any step is `"unknown"` because the serial is absent.
- A single-step answer (`step_order`) still carries that step's prerequisites and hazards.
- Write `test_assembly.py`.

**NOT in scope**: blocking release / prose checks (TASK-3722), audit/presign (TASK-3723), asking the technician for the serial (TASK-3724/3725 via `proc_set_equipment_serial`). No I/O at all in this module.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/procedures/assembly.py` | CREATE | `AssembledProcedure` + pure `assemble_procedure` |
| `packages/ai-parrot-tools/tests/procedures/test_assembly.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
import logging
from typing import Literal, Optional
from pydantic import BaseModel, Field

# created by TASK-3720 (packages/ai-parrot-tools/src/parrot_tools/procedures/retrieval.py)
from parrot_tools.procedures.retrieval import RequestContext, RetrievalResult
# created by TASK-3699 (packages/ai-parrot/src/parrot/knowledge/manuals/models.py)
from parrot.knowledge.manuals.models import ManualCard, ManualVersion, Procedure, Step, applies
# created by TASK-3700 (packages/ai-parrot/src/parrot/knowledge/manuals/models.py)
from parrot.knowledge.manuals.models import (
    HazardView, MediaView, Prerequisites, ProcedureAnswerKind, ProcedureCitation, ProcedureView, StepView, TipView,
)
```

### Existing Signatures to Use
```python
# created by TASK-3699 — manuals/models.py
def applies(step: "Step", *, model: str | None, serial: str | None) -> Literal["yes", "no", "unknown"]   # pure
class Step(BaseModel): identity: StepIdentity; order: int; text: Extracted[str]; torque; duration_minutes;
    applicability: Applicability; figure_refs; parts: list[PartRef]; tools: list[ToolRef]; hazards: list[Hazard];
    media: list[MediaLink]; cross_refs: list[str]
class ManualVersion(BaseModel): n: int; revision: str; valid_from; valid_to; source_sha256: str; ...
# created by TASK-3700 — ProcedureCitation(manual_id, node_id, quote(1..MAX_QUOTE_CHARS), page, verification, version_n, source_sha256)
#   StepView carries `applicability: Literal["yes", "unknown"]` (spec §3 M10 comment) — READ TASK-3700's actual
#   field list for ProcedureView/StepView/Prerequisites/HazardView/MediaView/TipView before writing.

# created by TASK-3720 — RetrievalResult(pattern, rows, manual: ManualCard | None, revision: ManualVersion | None, fallback_sections)
#   RequestContext(... equipment_serial: str | None, equipment_model: str | None)

# template reference (not imported): packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py:552-629
#   (`execute` dedups obligations; FEAT-539 dedup-by-key lesson)
```

### Does NOT Exist
- ~~`assemble_procedure(..., context=...)` in the spec skeleton~~ — the §3 skeleton has no context parameter but its docstring reads `context.equipment_model/serial`; this task **adds** a keyword-only `context: RequestContext | None = None` (documented deviation — see Implementation Notes). Do not look for another source of the serial.
- ~~An LLM/adapter call in assembly~~ — pure function, no `await`.
- ~~`CitationVerifier` reuse~~ — verification is TASK-3722.
- ~~Filling a missing step / guessing order from text~~ — gaps are recorded, never filled (R2).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/procedures/assembly.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/procedures/test_assembly.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
The authoritative source for step content and evidence is the **card revision** (`result.manual`, `result.revision`); the traversal rows supply graph-only facts (`has_step.order`, `precedes` kind, `illustrated_by.roles`, `tech_tip_on` tips). Join rows to card steps by `step_id`. A row whose `step_id` has no card step is a projection inconsistency ⇒ record in `unsupported_fields`, never render it.

### Decisions fixed here
- **Signature deviation (documented):** `assemble_procedure(result, *, kind, step_order=None, include_tips=True, context=None)`. The spec docstring applies `models.applies(step, model=context.equipment_model, serial=context.equipment_serial)` but the skeleton omits the parameter; keyword-only + default `None` keeps every skeleton call valid. Record this in the Completion Note.
- `missing_required` entries are strings naming the gap (e.g. `"step:<step_id>:order"`, `"step_order:3"`); `unsupported_fields` entries name the field (e.g. `"step:<step_id>:text.evidence"`, `"step:<step_id>:torque"` when `torque` is present but has no substantiating evidence).
- Order gap rule: orders must be `1..N` contiguous among the **applicable** + unknown steps of the card; a hole (e.g. card has 1,2,4) ⇒ `missing_required`.
- `needs_serial = any(applicability == "unknown" and context.equipment_serial is None)`.
- Dedup prerequisites by `part_id`/`tool_id`; keep the first occurrence's display name; sum quantities.

### Key Constraints (all FEAT-601 tasks)
- Tests inside a worktree: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest <file> -q` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.
- Ontology symbols are imported from submodules only (`parrot.knowledge.ontology.schema/graph_store/tenant/parser/authorization`), never the package root (AC17, FEAT-540 lazy root).
- No new third-party dependency (AC18). `ruff check` (TID251 bans `requests`/`httpx`/langchain) and `black --check` (line-length 120) must pass.
- Google-style docstrings and strict type hints everywhere; Pydantic v2 models for data; `logger = logging.getLogger(__name__)` / `self.logger`, never `print`.
- async all the way down — no blocking I/O inside `async def`.

### References in Codebase
- spec §3 M10 `assembly.py` skeleton and §2 Data Models (`ProcedureAnswer` invariants)
- `packages/ai-parrot-tools/tests/procedures/_doubles.py` (TASK-3720) — `make_card`/`make_step` builders; import read-only

---

## Implementation Blueprint

### Steps (in order)
1. Read TASK-3700's `*View`/`Prerequisites`/`ProcedureCitation` fields — *because* the blueprint only names them; their constructors are fixed there.
2. Write `AssembledProcedure` exactly as the skeleton lists — *because* TASK-3722/3723 consume every field.
3. Implement `assemble_procedure` as a sequence of small private helpers (select procedure → applicability filter → order check → prerequisites → hazards → media → tips → citations) — *because* each helper maps to one test and stays under the size cap.
4. Write the tests and run the Validation Command.

### `packages/ai-parrot-tools/src/parrot_tools/procedures/assembly.py` (CREATE) — block 1/2
```python
"""Pure, deterministic assembly of one procedure answer (FEAT-601 M10).

No I/O and no model: the traversal rows plus the selected card revision fully determine the output.
Gaps are recorded in ``missing_required`` / ``unsupported_fields`` — never filled (R2).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.manuals.models import (
    HazardView, ManualVersion, MediaView, Prerequisites, Procedure, ProcedureAnswerKind, ProcedureCitation,
    ProcedureView, Step, StepView, TipView, applies,
)
from parrot_tools.procedures.retrieval import RequestContext, RetrievalResult

logger = logging.getLogger(__name__)


class AssembledProcedure(BaseModel):
    """Everything a procedure answer may release, plus the recorded gaps."""

    procedure: ProcedureView
    steps: list[StepView] = Field(default_factory=list)
    prerequisites: Prerequisites
    hazards: list[HazardView] = Field(default_factory=list)
    media: list[MediaView] = Field(default_factory=list)
    tips: list[TipView] = Field(default_factory=list)
    citations: list[ProcedureCitation] = Field(default_factory=list)
    revision: ManualVersion
    missing_required: list[str] = Field(default_factory=list)
    unsupported_fields: list[str] = Field(default_factory=list)
    filtered_by_serial: list[str] = Field(default_factory=list)
    needs_serial: bool = False


def assemble_procedure(result: RetrievalResult, *, kind: ProcedureAnswerKind, step_order: int | None = None,
                       include_tips: bool = True, context: Optional[RequestContext] = None) -> AssembledProcedure:
    """Assemble ordered steps, prerequisites, hazards, media, tips and citations for one revision.

    Args:
        result: Retrieval output (rows + ``manual`` + ``revision``) for exactly one manual revision.
        kind: The answer kind being assembled (``procedure``/``step``/``prerequisites``).
        step_order: For ``kind="step"``, the requested step order.
        include_tips: Whether active technician tips are attached.
        context: Trusted request context; supplies ``equipment_model``/``equipment_serial`` for ``applies``.

    Returns:
        The assembled procedure; gaps are listed, never filled.

    Raises:
        ValueError: When ``result`` carries no manual or no revision (caller maps it to ``not_found``).
    """
    if result.manual is None or result.revision is None:
        raise ValueError("assembly needs the selected manual revision")
    procedure = _select_procedure(result)
    model = context.equipment_model if context else None
    serial = context.equipment_serial if context else None
    kept, filtered, needs_serial = _apply_applicability(procedure.steps, model=model, serial=serial)
    missing: list[str] = []
    unsupported: list[str] = []
    ordered = _order_steps(kept, result.rows, missing=missing, unsupported=unsupported)
    if kind == "step" and step_order is not None:
        # FILL IN: keep only the requested order (missing ⇒ missing_required "step_order:<n>") while still
        #          computing its prerequisites/hazards — bounded by spec §3 M10 ("a single-step answer still carries …")
        pass
    # FILL IN: build StepView/Prerequisites/HazardView/MediaView/TipView/citations via the helpers below and return
    #          AssembledProcedure(...) — bounded by the TASK-3700 view constructors
    raise NotImplementedError
```

### `assembly.py` — block 2/2 (helpers)
```python
def _select_procedure(result: RetrievalResult) -> Procedure:
    """Return the card procedure the rows belong to (single procedure_id across rows)."""
    # FILL IN: read procedure_id from rows (fallback: result.manual.procedures when exactly one); >1 distinct
    #          procedure_id ⇒ ValueError — bounded by "one manual revision, one procedure" (spec §3 M10)
    raise NotImplementedError


def _apply_applicability(steps: list[Step], *, model: str | None,
                         serial: str | None) -> tuple[list[tuple[Step, str]], list[str], bool]:
    """Split steps by ``applies``: drop "no" (listed), keep "yes"/"unknown" tagged."""
    kept: list[tuple[Step, str]] = []
    filtered: list[str] = []
    needs_serial = False
    for step in steps:
        verdict = applies(step, model=model, serial=serial)
        if verdict == "no":
            filtered.append(step.identity.step_id)
            continue
        if verdict == "unknown" and serial is None:
            needs_serial = True
        kept.append((step, verdict))
    return kept, filtered, needs_serial


def _order_steps(kept: list[tuple[Step, str]], rows: list[dict[str, Any]], *, missing: list[str],
                 unsupported: list[str]) -> list[tuple[Step, str]]:
    """Order by has_step.order from rows; record holes, precedes conflicts and row/card mismatches."""
    # FILL IN: map step_id → row order; step without a row order ⇒ missing "step:<id>:order"; row step_id not in
    #          card ⇒ unsupported "row:<id>"; non-contiguous orders ⇒ missing "order_gap:<n>"; explicit precedes
    #          contradicting order ⇒ missing "precedes:<a>-><b>" — bounded by test_assemble_procedure_complete_and_gaps
    raise NotImplementedError


def _prerequisites(steps: list[Step]) -> Prerequisites:
    """Union parts/tools across steps, dedup by id (FEAT-539 lesson), sum quantities."""
    # FILL IN: bounded by the Prerequisites fields in TASK-3700
    raise NotImplementedError


def _tips(rows: list[dict[str, Any]], released_step_ids: set[str]) -> list[TipView]:
    """Active, non-orphaned tips attached to a released step."""
    # FILL IN: skip rows with orphaned is True, active is False, or attached step not released — bounded by AC6
    raise NotImplementedError


def _citations(steps: list[Step], *, manual_id: str, revision: ManualVersion) -> tuple[list[ProcedureCitation], list[str]]:
    """One citation per released step from its text evidence; unsubstantiated critical fields are reported."""
    # FILL IN: quote trimmed to MAX_QUOTE_CHARS by the model; torque/duration present without substantiating
    #          evidence ⇒ unsupported "step:<id>:<field>" — bounded by G2 / AC7
    raise NotImplementedError
```
**Why this shape**: each helper is independently testable; the public function only wires them, so TASK-3722 can rely on `missing_required`/`unsupported_fields` being the complete gap list.

### `packages/ai-parrot-tools/tests/procedures/test_assembly.py` (CREATE)
Start from the Test Specification below.

### FILL IN checklist
- [ ] `assemble_procedure` — step-kind narrowing and final construction; bounded by spec §3 M10
- [ ] `_select_procedure` — single procedure rule
- [ ] `_order_steps` — holes, precedes conflicts, row/card mismatch
- [ ] `_prerequisites` — dedup by id
- [ ] `_tips` — orphan/inactive exclusion (AC6)
- [ ] `_citations` — evidence → citations, unsupported critical fields (G2, AC7)

---

## Acceptance Criteria

- [ ] Steps are ordered by `has_step.order`; a hole or `precedes` conflict appears in `missing_required`.
- [ ] Prerequisites are the union across released steps, deduplicated by id.
- [ ] Orphaned/inactive tips never appear in `tips` (AC6).
- [ ] Steps with `applies()=="no"` are excluded and listed in `filtered_by_serial`; `"unknown"` steps are kept with `applicability="unknown"`; `needs_serial` is `True` when the serial is absent and needed (AC20).
- [ ] Single-step assembly carries that step's prerequisites and hazards.
- [ ] Every released step yields exactly one citation from its evidence for the selected revision.
- [ ] The module performs no I/O (no `await`, no adapter).

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/procedures/test_assembly.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/procedures/test_assembly.py
from parrot_tools.procedures.assembly import assemble_procedure
from parrot_tools.procedures.retrieval import RetrievalResult

from ._doubles import make_context  # plus make_card/make_step builders from TASK-3720


def _result(card, rows):
    # FILL IN: RetrievalResult(pattern="procedure_steps", rows=rows, manual=card, revision=card.versions[-1])
    ...


def test_assemble_procedure_complete_and_gaps():
    """Ordered steps + prerequisite union dedup by key; orphaned tips excluded; missing has_step order ⇒ missing_required."""
    # FILL IN: 5-step card; rows for 5 steps (one tip orphaned=True) ⇒ 5 ordered steps, 0 gaps, orphan absent;
    #          drop the row order of step 3 ⇒ "step:<id>:order" in missing_required
    ...


def test_assemble_filters_by_serial_and_flags_unknown():
    """Steps outside range excluded + listed; unknown kept with note; needs_serial when serial absent."""
    # FILL IN: step 4 serial_ranges A100–A250; context serial A300 ⇒ excluded; context serial None ⇒ kept "unknown",
    #          needs_serial True
    ...


def test_single_step_keeps_prerequisites_and_hazards():
    # FILL IN: kind="step", step_order=2 ⇒ one StepView plus its parts/tools/hazards
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/training-agent.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
