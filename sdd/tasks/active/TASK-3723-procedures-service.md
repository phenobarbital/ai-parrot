# TASK-3723: ProceduresAnswerService release pipeline, audit, presign (M10)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3705, TASK-3722
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 10** (`service.py`), U4 and **G5**: the single release path every channel goes through — *authorize → plan → execute → assemble → (optional prose draft) → verify (blocking) → audit (before release) → presign media → release*. Copies the boundary of `ContractsAnswerService` (`parrot_tools/contracts/service.py:105-232`): audit failure means no release, and streaming buffers until release. Presigned figure URLs are minted **per answer, after audit**, never stored (G4, AC13).

Covers spec §4 tests `test_service_audit_before_release`, `test_stream_answer_buffers`; contributes to AC7, AC8, AC9, AC13.

---

## Scope

- Create `parrot_tools/procedures/service.py` with `AnswerProducer` (Protocol), `ServiceUnavailable`, `AnswerOutcome`, `ProceduresAnswerService` (`answer`, `stream_answer`).
- Map `AuthorizationDenied` ⇒ audited `denied` answer; unknown/ambiguous ⇒ `Clarification` (not audited, carries no evidence — contracts precedent); `needs_serial` ⇒ `Clarification(reason="equipment_serial_required")`; no graph rows ⇒ `fallback_lookup` ⇒ `lookup` answer with the "not a verified procedure" line; still nothing ⇒ `not_found`.
- Presign every released figure/photo `MediaView.storage_key` through `figures.presign(fm, key, expiry=presign_expiry)` (TASK-3705); `MediaUnavailable` ⇒ skip that URL and log; video segments go to `media_urls` as `uri` deep links (`?t=<int(t_start)>s` when the URI has no query) — never presigned.
- Write `test_service.py`.

**NOT in scope**: tools/agent/transport adapter (TASK-3724/3725); the `AnswerRecord` model and `record_answer` (TASK-3702 — reuse); rendering the answer text for chat (TASK-3725).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/procedures/service.py` | CREATE | Release pipeline |
| `packages/ai-parrot-tools/tests/procedures/test_service.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
import logging, uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Optional, Protocol
from pydantic import BaseModel, Field

# created by TASK-3702 (packages/ai-parrot/src/parrot/knowledge/manuals/catalog.py)
from parrot.knowledge.manuals.catalog import AnswerRecord, ManualCatalogStore
# created by TASK-3705 (packages/ai-parrot/src/parrot/knowledge/manuals/figures.py)
from parrot.knowledge.manuals.figures import MediaUnavailable, presign
# created by TASK-3699 / TASK-3700 (packages/ai-parrot/src/parrot/knowledge/manuals/models.py)
from parrot.knowledge.manuals.models import ManualVersion, ProcedureAnswer
# created by TASK-3720 / 3721 / 3722 (packages/ai-parrot-tools/src/parrot_tools/procedures/)
from parrot_tools.procedures.retrieval import AuthorizationDenied, Clarification, ProcedureRetrieval, RequestContext
from parrot_tools.procedures.assembly import AssembledProcedure, assemble_procedure
from parrot_tools.procedures.verifier import ProcedureVerifier
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/contracts/service.py — TEMPLATE (do not import)
class AnswerProducer(Protocol): async def draft(self, question, result, dossier) -> AnswerDraft   # line 68
class ServiceUnavailable(RuntimeError)                                                           # line 83 — raised instead of releasing unaudited
class AnswerOutcome(BaseModel): answer; answer_id; audited; rejected; dropped_claims              # line 95
class ContractsAnswerService:                                                                     # line 105
    async def answer(self, question, *, request_context, parameters=None, producer=None)          # line 146-212
        # AuthorizationDenied ⇒ self._release(ContractAnswer(answer_kind="denied", reason=exc.reason), allowed=False)
        # Clarification ⇒ returned as-is (not audited)
    async def stream_answer(self, question, *, request_context, producer=None) -> AsyncIterator[str]   # line 214-232 — awaits answer() fully, then yields
    async def _release(...)   # line 309-350 — builds AnswerRecord, `await self.catalog.record_answer(record)`;
                              # except ⇒ logger.error + raise ServiceUnavailable(...) from exc

# created by TASK-3705 — manuals/figures.py
async def presign(fm: Any, storage_key: str, *, expiry: int = 900) -> str   # fm.get_file_url(storage_key, expiry=expiry); raises MediaUnavailable on non-http(s)

# created by TASK-3720 — ProcedureRetrieval.authorize/plan/execute/fallback_lookup; RetrievalResult.revision
# created by TASK-3721 — assemble_procedure(result, *, kind, step_order=None, include_tips=True, context=None) -> AssembledProcedure
# created by TASK-3722 — ProcedureVerifier(...).verify(assembled, *, draft_prose, kind, pattern) -> VerificationOutcome
```

### Does NOT Exist
- ~~Presigned URLs in the audit row, the answer model or the graph~~ — minted after audit, returned only on `AnswerOutcome.image_urls` (G4).
- ~~`get_file_url(path, expiry_seconds=...)`~~ — the kwarg is `expiry` (handled inside `figures.presign`).
- ~~Releasing on audit failure~~ — `record_answer` failure ⇒ `ServiceUnavailable`, no `AnswerOutcome`, zero presign calls.
- ~~A shared `ServiceUnavailable` from contracts~~ — define it locally (no `parrot_tools.contracts` import).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/procedures/service.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/procedures/test_service.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/contracts/service.py#ContractsAnswerService.answer",
    "sym:packages/ai-parrot-tools/src/parrot_tools/contracts/service.py#ContractsAnswerService.stream_answer",
    "sym:packages/ai-parrot-tools/src/parrot_tools/contracts/service.py#ContractsAnswerService._release"
  ]
}
```

---

## Implementation Notes

### Decisions fixed here
- **Pattern → kind:** `procedure_steps`/`procedure_in_force` ⇒ `procedure`; `step_detail` ⇒ `step`; `procedure_prerequisites` ⇒ `prerequisites`. Other patterns (`tips_for_procedure`, `part_for_callout`, `procedures_for_equipment`, `equipment_sharing_module`) are served by the toolkit's direct tools (TASK-3724) and here map to `lookup` over the rows (no steps). Document the table in the module docstring.
- **Audit covers every outcome** (released, incomplete, denied, lookup, not_found) — Clarifications excepted.
- **Presign order:** audit → presign → build `AnswerOutcome`. A `MediaUnavailable` drops that URL only (log `warning`); it never fails the answer.
- `producer.draft(...)` runs only when the assembly has no gaps (no point drafting prose for a blocked answer); its raw output is passed to the verifier and never returned.
- `stream_answer` yields nothing until `answer()` returns; then yields the released `answer.answer` prose (or the clarification reason). Rendering of steps is TASK-3725's job.

### Key Constraints (all FEAT-601 tasks)
- Tests inside a worktree: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest <file> -q` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.
- Ontology symbols are imported from submodules only (`parrot.knowledge.ontology.schema/graph_store/tenant/parser/authorization`), never the package root (AC17, FEAT-540 lazy root).
- No new third-party dependency (AC18). `ruff check` (TID251 bans `requests`/`httpx`/langchain) and `black --check` (line-length 120) must pass.
- Google-style docstrings and strict type hints everywhere; Pydantic v2 models for data; `logger = logging.getLogger(__name__)` / `self.logger`, never `print`.
- async all the way down — no blocking I/O inside `async def`.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/contracts/service.py:105-350` — boundary + audit pattern
- `packages/ai-parrot-tools/tests/contracts/test_service.py` — test style
- `packages/ai-parrot-tools/tests/procedures/_doubles.py` (TASK-3720) — `FakeCatalog(fail_audit=True)`

---

## Implementation Blueprint

### Steps (in order)
1. Define `AnswerProducer`, `ServiceUnavailable`, `AnswerOutcome` — *because* the agent (TASK-3725) imports these exact names.
2. Implement `answer()` as the fixed pipeline with the audit before presign — *because* AC8/AC13: no unaudited release and no URL minted for an unreleased answer.
3. Implement `_release`, `_presign_media`, `stream_answer`.
4. Write tests (fake file manager records `get_file_url` calls so "no presign" is assertable).

### `packages/ai-parrot-tools/src/parrot_tools/procedures/service.py` (CREATE) — block 1/2
```python
"""The single release path for procedure answers (FEAT-601 M10, U4).

authorize → plan → execute → assemble → (draft prose) → verify (blocking) → audit → presign → release.
Pattern → answer kind: procedure_steps/procedure_in_force ⇒ procedure; step_detail ⇒ step;
procedure_prerequisites ⇒ prerequisites; anything else ⇒ lookup (served in full by the toolkit tools).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Optional, Protocol

from pydantic import BaseModel, Field

from parrot.knowledge.manuals.catalog import AnswerRecord, ManualCatalogStore
from parrot.knowledge.manuals.figures import MediaUnavailable, presign
from parrot.knowledge.manuals.models import ManualVersion, ProcedureAnswer
from parrot_tools.procedures.assembly import AssembledProcedure, assemble_procedure
from parrot_tools.procedures.retrieval import AuthorizationDenied, Clarification, ProcedureRetrieval, RequestContext
from parrot_tools.procedures.verifier import ProcedureVerifier

logger = logging.getLogger(__name__)

_KIND_BY_PATTERN: dict[str, str] = {
    "procedure_steps": "procedure", "procedure_in_force": "procedure",
    "step_detail": "step", "procedure_prerequisites": "prerequisites",
}
NOT_VERIFIED_LINE = "This is a manual excerpt, not a verified procedure."


class AnswerProducer(Protocol):
    """Drafts optional intro prose — the only model-authored text."""

    async def draft(self, question: str, assembled: AssembledProcedure, *, context: RequestContext) -> str: ...


class ServiceUnavailable(RuntimeError):
    """A dependency the release path requires (the audit store) failed; nothing was released."""


class AnswerOutcome(BaseModel):
    """A released answer, its audit id and the per-answer media URLs."""

    answer: ProcedureAnswer
    audit_id: str
    image_urls: list[str] = Field(default_factory=list)
    media_urls: list[str] = Field(default_factory=list)


class ProceduresAnswerService:
    """One authorization, verification and audit gate for every channel."""

    def __init__(self, *, retrieval: ProcedureRetrieval, verifier_factory: Callable[[ManualVersion], ProcedureVerifier],
                 catalog: ManualCatalogStore, file_manager: Any, presign_expiry: int = 900,
                 producer: Optional[AnswerProducer] = None) -> None:
        self.retrieval = retrieval
        self.verifier_factory = verifier_factory
        self.catalog = catalog
        self.file_manager = file_manager
        self.presign_expiry = presign_expiry
        self.producer = producer
        self.logger = logging.getLogger(__name__)
```

### `service.py` — block 2/2
```python
    async def answer(self, question: str, *, request_context: RequestContext,
                     producer: Optional[AnswerProducer] = None) -> AnswerOutcome | Clarification:
        """Answer ``question`` or explain why not. Raw producer output never leaves this method.

        Raises:
            ServiceUnavailable: When the outcome could not be audited (nothing is released).
        """
        selected = producer if producer is not None else self.producer
        try:
            plan = await self.retrieval.plan(question, request_context)
            if isinstance(plan, Clarification):
                return plan
            kind = _KIND_BY_PATTERN.get(plan.pattern, "lookup")
            # FILL IN: kind == "lookup" or no rows ⇒ retrieval.fallback_lookup(question, plan.manual_id, ctx) ⇒
            #          ProcedureAnswer(answer_kind="lookup", answer=NOT_VERIFIED_LINE + excerpt refs, citations from
            #          sections); no sections ⇒ answer_kind="not_found" — bounded by G5 and TASK-3700 invariants
            result = await self.retrieval.execute(plan, request_context)
            assembled = assemble_procedure(result, kind=kind, step_order=plan.step_order, context=request_context)
            if assembled.needs_serial:
                return Clarification(reason="equipment_serial_required", pattern=plan.pattern)
            prose = ""
            if selected is not None and not (assembled.missing_required or assembled.unsupported_fields):
                prose = await selected.draft(question, assembled, context=request_context)
            outcome = await self.verifier_factory(assembled.revision).verify(
                assembled, draft_prose=prose, kind=kind, pattern=plan.pattern)
            released = outcome.answer
        except AuthorizationDenied as exc:
            denied = ProcedureAnswer(answer_kind="denied", answer="", reason=exc.reason)  # FILL IN: match TASK-3700 required fields
            return await self._release(denied, question=question, context=request_context, allowed=False)
        return await self._release(released, question=question, context=request_context, allowed=True)

    async def stream_answer(self, question: str, *, request_context: RequestContext,
                            producer: Optional[AnswerProducer] = None) -> AsyncIterator[str]:
        """Yield nothing until :meth:`answer` has released (contracts service.py:214-232)."""
        outcome = await self.answer(question, request_context=request_context, producer=producer)
        if isinstance(outcome, Clarification):
            yield outcome.reason
            return
        if outcome.answer.answer:
            yield outcome.answer.answer

    async def _release(self, answer: ProcedureAnswer, *, question: str, context: RequestContext,
                       allowed: bool) -> AnswerOutcome:
        """Audit first; only then presign media and release."""
        audit_id = f"proc-{uuid.uuid4().hex[:12]}"
        # FILL IN: AnswerRecord(...) with audit_id, datetime.now(timezone.utc), context.user_id/tenant_id, question,
        #          answer_kind, pattern, citations, allowed — bounded by the TASK-3702 AnswerRecord fields
        record: Any = None
        try:
            await self.catalog.record_answer(record)
        except Exception as exc:  # noqa: BLE001 — never release unaudited
            self.logger.error("Answer audit failed; refusing to release: %s", exc)
            raise ServiceUnavailable(f"the answer could not be audited and was not released: {exc}") from exc
        image_urls, media_urls = await self._presign_media(answer)
        return AnswerOutcome(answer=answer, audit_id=audit_id, image_urls=image_urls, media_urls=media_urls)

    async def _presign_media(self, answer: ProcedureAnswer) -> tuple[list[str], list[str]]:
        """Presign released figures/photos; deep-link released video segments."""
        images: list[str] = []
        videos: list[str] = []
        for media in answer.media:
            # FILL IN: figure/photo with storage_key ⇒ presign(self.file_manager, key, expiry=self.presign_expiry)
            #          (MediaUnavailable ⇒ logger.warning + skip); video_segment ⇒ uri + "?t=<int(t_start)>s" when no
            #          query string — bounded by G4/AC13 (never persist a URL)
            pass
        return images, videos
```
**Why this shape**: the `try` covers everything that can deny, so a denial is still audited; `_release` is the only place an `AnswerOutcome` is built, and presign runs strictly after the audit write.

### `packages/ai-parrot-tools/tests/procedures/test_service.py` (CREATE)
Start from the Test Specification below.

### FILL IN checklist
- [ ] `answer` — lookup / not_found branch; bounded by G5
- [ ] `answer` — `denied` answer fields; bounded by TASK-3700 invariants
- [ ] `_release` — `AnswerRecord` construction; bounded by TASK-3702 fields
- [ ] `_presign_media` — figure presign + video deep link; bounded by G4/AC13

---

## Acceptance Criteria

- [ ] A failing `record_answer` ⇒ `ServiceUnavailable`; no `AnswerOutcome`; zero `get_file_url` calls.
- [ ] `stream_answer` yields nothing before the release completes.
- [ ] Denials are audited (`allowed=False`); Clarifications are returned without audit.
- [ ] `needs_serial` ⇒ `Clarification(reason="equipment_serial_required")`.
- [ ] Released figures carry presigned `https://` URLs only in `AnswerOutcome.image_urls`; `file://` results are skipped.
- [ ] The draft prose reaches the caller only through the verifier's released `answer.answer`.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/procedures/test_service.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/procedures/test_service.py
import pytest

from parrot_tools.procedures.service import ProceduresAnswerService, ServiceUnavailable

from ._doubles import FakeCatalog, make_context


class RecordingFileManager:
    def __init__(self, url: str = "https://fake/figure.png") -> None:
        self.url = url
        self.calls: list[tuple[str, int]] = []

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        self.calls.append((path, expiry))
        return self.url


async def test_service_audit_before_release():
    """Failing record_answer ⇒ no AnswerOutcome, no presign call."""
    fm = RecordingFileManager()
    # FILL IN: service over FakeCatalog(fail_audit=True) + scripted retrieval rows for a 5-step procedure
    #          with one primary figure; `with pytest.raises(ServiceUnavailable)`; assert fm.calls == []
    ...


async def test_stream_answer_buffers():
    """Nothing yielded before release."""
    # FILL IN: producer whose draft() sets a flag; iterate stream_answer and assert the first chunk arrives only after
    #          FakeCatalog.answers has one record
    ...


async def test_presign_skips_non_http():
    # FILL IN: RecordingFileManager("file:///tmp/x.png") ⇒ outcome.image_urls == []
    ...


async def test_needs_serial_returns_clarification():
    # FILL IN: serial-qualified step + context without equipment_serial ⇒ Clarification(reason="equipment_serial_required")
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
