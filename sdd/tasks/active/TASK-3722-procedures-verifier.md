# TASK-3722: ProcedureVerifier blocking completeness + evidence gate (M10)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3721
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 10** (`verifier.py`), review finding **R2** and **AC7**. Contracts' `CitationVerifier` (`parrot_tools/contracts/verifier.py:102-206`) *drops* unsupported claims and releases the rest — acceptable for contract Q&A, dangerous for an assembly procedure where a silently missing step is the worst failure. `ProcedureVerifier` therefore **blocks**: any `missing_required` or `unsupported_fields` from `assemble_procedure` (TASK-3721), or any citation that does not resolve verbatim in the archived revision, turns the answer into `answer_kind="incomplete"` with a `reason` and **zero steps released**. The optional model prose is the only model-authored text and is dropped if it names a step or value not present in the assembly.

Covers spec §4 tests `test_verifier_blocks_incomplete`, `test_verifier_prose_cannot_add_steps`.

---

## Scope

- Create `parrot_tools/procedures/verifier.py` with `RejectedCitation`, `VerificationOutcome`, an `EvidenceReader` protocol (`async load_section(manual_id, version_n, node_id) -> str | None`, satisfied by `ManualLibrary`, TASK-3713), and `ProcedureVerifier(catalog, evidence, allowed_revision).verify(...)`.
- Resolve every citation: `version_n == allowed_revision.n`, `source_sha256` prefix match, non-empty quote, quote verbatim (whitespace-normalized) in `await evidence.load_section(citation.manual_id, citation.version_n, citation.node_id)`.
- Completeness gate: `assembled.missing_required or assembled.unsupported_fields or rejected` ⇒ `incomplete`, `steps=[]`, `reason` names every missing step/field.
- Prose gate: drop `draft_prose` when it mentions a step number, torque/duration value or part number that is not in the assembly.
- Build the released `ProcedureAnswer` (TASK-3700) for the non-blocked kinds; `provenance = derive_provenance(citations)` is enforced by the model validator.
- Write `test_verifier.py`.

**NOT in scope**: audit, presign, streaming (TASK-3723); the archive's storage format (`sections.json` under `evidence_root/<manual_id>/<version_n>/`, owned by `ManualLibrary`, TASK-3713 — this task only consumes the `EvidenceReader` protocol; tests use a fake). Do NOT copy the `CitationVerifier.verify` drop loop.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/procedures/verifier.py` | CREATE | Blocking verifier |
| `packages/ai-parrot-tools/tests/procedures/test_verifier.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
import logging, re
from typing import Any, Optional, Protocol
from pydantic import BaseModel, Field

# created by TASK-3697 (packages/ai-parrot/src/parrot/knowledge/common/validation.py)
from parrot.knowledge.common.validation import normalize_whitespace
# created by TASK-3699 / TASK-3700 (packages/ai-parrot/src/parrot/knowledge/manuals/models.py)
from parrot.knowledge.manuals.models import ManualVersion, ProcedureAnswer, ProcedureAnswerKind, ProcedureCitation
# created by TASK-3721 (packages/ai-parrot-tools/src/parrot_tools/procedures/assembly.py)
from parrot_tools.procedures.assembly import AssembledProcedure
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/contracts/verifier.py — TEMPLATE for shapes only
class RejectedCitation(BaseModel): contract_id: str; node_id: str; reason: str          # line 81 (manuals: manual_id)
class VerificationOutcome(BaseModel): answer; rejected: list[RejectedCitation]; dropped_claims   # line 89
class CitationVerifier:                                                                   # line 102
    def __init__(self, *, catalog: Any, evidence: EvidenceArchive) -> None               # line 110
    async def verify(self, draft, *, dossier, pattern=None, question=None)                # line 114 — DROPS; do not copy

# Evidence source — created by TASK-3713 (packages/ai-parrot/src/parrot/knowledge/manuals/library.py)
class ManualLibrary:
    async def load_section(self, manual_id: str, version_n: int, node_id: str) -> str | None
        # library-owned per-revision archive: evidence_root/<manual_id>/<version_n>/sections.json
# ProcedureVerifier types `evidence` as the local EvidenceReader Protocol (any object with that method),
# so verifier.py does NOT import library.py and TASK-3722 does not depend on TASK-3713.
# Check order: version match → sha prefix (16) match → non-empty normalized quote →
# section present → quote verbatim in normalized section.

# created by TASK-3700 — ProcedureAnswer(answer_kind, answer, procedure, steps, prerequisites, hazards, media, tips,
#   citations, provenance, pattern, reason, manual_revision) with @model_validator _check_kind_invariants
#   (procedure ⇒ ≥1 step & ≥1 citation; incomplete ⇒ reason, no steps)
```

### Does NOT Exist
- ~~A manuals `EvidenceArchive`, or reuse of contracts `EvidenceArchive.resolve`~~ — manuals must not import contracts (M1/U2); evidence comes from `ManualLibrary.load_section` (TASK-3713) through the local `EvidenceReader` protocol.
- ~~`evidence.body(...)` / `evidence.resolve(...)`~~ — the only method used is `load_section(manual_id, version_n, node_id)`.
- ~~`CitationVerifier` reuse for procedures~~ — its drop semantics are exactly what R2 forbids.
- ~~Model-authored citations~~ — citations come only from `AssembledProcedure.citations`; prose can never add one.
- ~~Importing `normalize_quote` from `parrot.knowledge.contracts.evidence`~~ — use `normalize_whitespace` from `knowledge.common` (M1 decoupling).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/procedures/verifier.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/procedures/test_verifier.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/contracts/verifier.py#CitationVerifier"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Each `ProcedureCitation` is resolved against `evidence.load_section(manual_id, version_n, node_id)` (TASK-3713's library-owned archive) with a whitespace-normalized verbatim match. The outcome model mirrors contracts' `VerificationOutcome` but adds `blocked_reason`.

### Decisions fixed here
- `incomplete` is a first-class answer kind: `ProcedureAnswer(answer_kind="incomplete", reason=..., steps=[], answer="")`, carrying `procedure` (title only) and `manual_revision` so the technician knows *which* procedure is incomplete, but no step content, media or citations.
- `reason` format: `"missing: <comma-separated missing_required>; unsupported: <…>; rejected: <node_id…>"` (omit empty parts).
- Prose check is conservative: extract integers after `step|paso`, numbers with units (`N·m`, `Nm`, `min`) and part-number-like tokens; any not present in the assembled steps' text/torque/duration/parts ⇒ prose dropped (`answer=""`) and recorded in `dropped_claims`. Never *edit* prose.
- Kinds `procedure` / `step` / `prerequisites` go through the gate; `lookup`, `clarification`, `not_found`, `out_of_scope`, `denied` are built by the service (TASK-3723), not here.

### Key Constraints (all FEAT-601 tasks)
- Tests inside a worktree: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest <file> -q` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.
- Ontology symbols are imported from submodules only (`parrot.knowledge.ontology.schema/graph_store/tenant/parser/authorization`), never the package root (AC17, FEAT-540 lazy root).
- No new third-party dependency (AC18). `ruff check` (TID251 bans `requests`/`httpx`/langchain) and `black --check` (line-length 120) must pass.
- Google-style docstrings and strict type hints everywhere; Pydantic v2 models for data; `logger = logging.getLogger(__name__)` / `self.logger`, never `print`.
- async all the way down — no blocking I/O inside `async def`.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/contracts/verifier.py` — shapes
- `packages/ai-parrot/src/parrot/knowledge/manuals/library.py::ManualLibrary.load_section` (TASK-3713) — evidence source

---

## Implementation Blueprint

### Steps (in order)
1. Define `EvidenceReader` protocol and the outcome models — *because* the service (TASK-3723) injects an implementation per revision via `verifier_factory`.
2. Implement `_resolve` per citation — *because* AC7 requires every released citation to resolve verbatim in the archived revision.
3. Implement the completeness gate before building any released answer — *because* R2: a blocked answer must contain zero steps.
4. Implement the prose gate — *because* prose is the only model-authored field and must never add a step/value.
5. Write tests, run the Validation Command.

### `packages/ai-parrot-tools/src/parrot_tools/procedures/verifier.py` (CREATE) — block 1/2
```python
"""Blocking completeness + evidence verification for procedure answers (FEAT-601 M10, R2).

Unlike the contracts ``CitationVerifier`` (which drops unsupported claims), a missing required step,
an unsupported critical field or an unresolvable citation BLOCKS release: ``answer_kind="incomplete"``.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional, Protocol

from pydantic import BaseModel, Field

from parrot.knowledge.common.validation import normalize_whitespace
from parrot.knowledge.manuals.models import ManualVersion, ProcedureAnswer, ProcedureAnswerKind, ProcedureCitation
from parrot_tools.procedures.assembly import AssembledProcedure

logger = logging.getLogger(__name__)

_STEP_NUM_RE = re.compile(r"\b(?:step|paso)\s+(\d{1,3})\b", re.I)
_VALUE_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:n·m|nm|n-m|min|mm|kg)\b", re.I)


class EvidenceReader(Protocol):
    """Reads one archived section of a manual revision (satisfied by ``ManualLibrary``, TASK-3713)."""

    async def load_section(self, manual_id: str, version_n: int, node_id: str) -> Optional[str]: ...


class RejectedCitation(BaseModel):
    """One citation that did not resolve, and why."""

    manual_id: str
    node_id: str
    reason: str


class VerificationOutcome(BaseModel):
    """The answer that may be released, plus everything that blocked or was dropped."""

    answer: ProcedureAnswer
    rejected: list[RejectedCitation] = Field(default_factory=list)
    blocked_reason: str | None = None
    dropped_claims: list[str] = Field(default_factory=list)


class ProcedureVerifier:
    """Verify an assembled procedure against the archived revision; block on any gap.

    Args:
        catalog: The tenant-bound manual catalog (kept for parity with contracts; card lookups only).
        evidence: An :class:`EvidenceReader` (e.g. ``ManualLibrary``) over the archived revisions.
        allowed_revision: The only revision citations may come from.
    """

    def __init__(self, *, catalog: Any, evidence: Any, allowed_revision: ManualVersion) -> None:
        self.catalog = catalog
        self.evidence = evidence
        self.allowed_revision = allowed_revision
        self.logger = logging.getLogger(__name__)
```

### `verifier.py` — block 2/2
```python
    async def verify(self, assembled: AssembledProcedure, *, draft_prose: str, kind: ProcedureAnswerKind,
                     pattern: str | None) -> VerificationOutcome:
        """Return a released answer or an ``incomplete`` one with no steps.

        Raises:
            ValueError: When ``kind`` is not one this gate handles (procedure/step/prerequisites).
        """
        if kind not in ("procedure", "step", "prerequisites"):
            raise ValueError(f"{kind!r} is not verified here")
        rejected = [r for r in [await self._resolve(c) for c in assembled.citations] if r is not None]
        if assembled.missing_required or assembled.unsupported_fields or rejected:
            reason = self._reason(assembled, rejected)
            self.logger.warning("procedure answer blocked: %s", reason)
            # FILL IN: ProcedureAnswer(answer_kind="incomplete", answer="", reason=reason, steps=[], citations=[],
            #          procedure=assembled.procedure, manual_revision=self.allowed_revision.revision, pattern=pattern)
            #          — bounded by the TASK-3700 `incomplete` invariant (reason set, no steps)
            raise NotImplementedError
        prose, dropped = self._check_prose(draft_prose, assembled)
        # FILL IN: build the released ProcedureAnswer for `kind` from the assembly (steps, prerequisites, hazards,
        #          media, tips, citations) — bounded by the TASK-3700 kind invariants; provenance derived by the model
        raise NotImplementedError

    async def _resolve(self, citation: ProcedureCitation) -> Optional[RejectedCitation]:
        """Return ``None`` when the citation resolves verbatim, else the rejection in the archived section."""
        def reject(reason: str) -> RejectedCitation:
            return RejectedCitation(manual_id=citation.manual_id, node_id=citation.node_id, reason=reason)

        if citation.version_n != self.allowed_revision.n:
            return reject("citation version does not match the allowed revision")
        if citation.source_sha256 and not self.allowed_revision.source_sha256.startswith(citation.source_sha256[:16]):
            return reject("citation source hash does not match")
        quote = normalize_whitespace(citation.quote)
        if not quote:
            return reject("empty quotes never prove evidence")
        body = await self.evidence.load_section(citation.manual_id, citation.version_n, citation.node_id)
        if body is None:
            return reject(f"node {citation.node_id!r} is not in this revision")
        if quote not in normalize_whitespace(body):
            return reject("quote is not verbatim in the archived body")
        return None

    @staticmethod
    def _reason(assembled: AssembledProcedure, rejected: list[RejectedCitation]) -> str:
        """Human-readable reason naming every missing step/field and rejected node."""
        parts = []
        if assembled.missing_required:
            parts.append("missing: " + ", ".join(assembled.missing_required))
        if assembled.unsupported_fields:
            parts.append("unsupported: " + ", ".join(assembled.unsupported_fields))
        if rejected:
            parts.append("rejected: " + ", ".join(r.node_id for r in rejected))
        return "; ".join(parts)

    @staticmethod
    def _check_prose(prose: str, assembled: AssembledProcedure) -> tuple[str, list[str]]:
        """Drop prose that names a step number or value absent from the assembly."""
        # FILL IN: allowed step numbers = released orders; allowed values = normalized torque/duration strings and
        #          part numbers of released steps; any _STEP_NUM_RE/_VALUE_RE hit outside them ⇒ ("", [hits]) —
        #          bounded by AC7 ("prose can never add a step, value or citation")
        raise NotImplementedError
```
**Why this shape**: blocking happens *before* any released answer exists, so no code path can leak partial steps; `_resolve` checks each citation against the library-owned archive through a protocol, so the verifier never imports the library.

### `packages/ai-parrot-tools/tests/procedures/test_verifier.py` (CREATE)
Start from the Test Specification below.

### FILL IN checklist
- [ ] `verify` — `incomplete` construction; bounded by TASK-3700 invariants / R2
- [ ] `verify` — released answer per kind; bounded by TASK-3700 invariants
- [ ] `_check_prose` — step/value extraction and comparison; bounded by AC7

---

## Acceptance Criteria

- [ ] Any `missing_required`/`unsupported_fields`/rejected citation ⇒ `answer_kind="incomplete"`, `steps == []`, `reason` names each gap (AC7, R2).
- [ ] A citation from another revision, with a foreign sha, an empty quote, a missing node or a non-verbatim quote is rejected.
- [ ] Prose naming an unknown step number or value is dropped (`answer == ""`), never edited.
- [ ] Complete assemblies release every step with its citation; `provenance` equals `derive_provenance(citations)`.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/procedures/test_verifier.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/procedures/test_verifier.py
from parrot_tools.procedures.verifier import ProcedureVerifier


class FakeEvidence:
    """Stands in for ManualLibrary.load_section (TASK-3713)."""

    def __init__(self, sections: dict[str, str]) -> None:
        self.sections = sections

    async def load_section(self, manual_id, version_n, node_id):
        return self.sections.get(node_id)


async def test_verifier_blocks_incomplete():
    """missing_required ⇒ answer_kind="incomplete", zero steps released (contrast with contracts drop semantics)."""
    # FILL IN: AssembledProcedure with missing_required=["step:x:order"] ⇒ outcome.answer.answer_kind == "incomplete",
    #          outcome.answer.steps == [], "step:x:order" in outcome.blocked_reason
    ...


async def test_verifier_rejects_non_verbatim_quote():
    # FILL IN: citation quote absent from FakeEvidence ⇒ incomplete with rejected[0].reason mentioning "verbatim"
    ...


async def test_verifier_prose_cannot_add_steps():
    """Prose naming an unknown step/value is dropped."""
    # FILL IN: 5-step assembly; draft_prose="Then do step 7 at 45 Nm" ⇒ answer == "" and dropped_claims non-empty
    ...


async def test_verifier_releases_complete_procedure():
    # FILL IN: all quotes verbatim ⇒ answer_kind "procedure", 5 steps, 5 citations
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
