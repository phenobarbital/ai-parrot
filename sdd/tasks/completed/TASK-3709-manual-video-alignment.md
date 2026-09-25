# TASK-3709: Whisper block → step alignment with bm25s and judged tail (M7)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3699
**Assigned-to**: unassigned

> Parallelism: produces MediaRef/MediaLink(video_segment) and reads Step/ManualCard from TASK-3699 (manuals/models.py).

---

## Context

Spec §2 Overview "Video", §3 **Module 7**. Turn whisper transcript blocks (`BaseVideoLoader.transcript_to_blocks`:
`start_seconds`/`end_seconds`/`text`) into `MediaRef(kind="video_segment", uri, t_start, t_end)` per step.
Deterministic first (`bm25s` over step text vs block text + a monotonic ordinal constraint), then one LLM-judged
call for the unaligned tail with a judgement log and `--force` (bookstore `relate_books` pattern, F014). A step
with no segment gets none. Coverage < 30 % ⇒ a single procedure-level `role="overview"` media only. Gemini
`VideoUnderstandingLoader` is **not** used (untimed scenes, F025). Thresholds are tuned by spike 3 (TASK-3726).

---

## Scope

- Create `manuals/video.py`: `TranscriptBlock`, `blocks_from_transcript`, `SegmentAlignment`, `align_deterministic`,
  `AlignmentJudgement`, `JudgementDraft`, `JudgementLog` (JSON-file backed), `AlignmentReport`, `judge_alignment`,
  `align_video`, `OVERVIEW_COVERAGE_THRESHOLD = 0.30`.
- Tests: `test_align_deterministic_monotonic`, `test_judge_alignment_drops_hallucinated_ids`,
  `test_align_video_low_coverage_overview`.

**NOT in scope**: downloading / transcribing video (callers pass the whisper dict; TASK-3713 `add_video` wires
`YoutubeLoader`); graph edges (TASK-3712); keyframes, re-hosting (Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/manuals/video.py` | CREATE | block ingestion, bm25s alignment, judged tail, log |
| `packages/ai-parrot/tests/knowledge/manuals/test_video.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.manuals.models import ManualCard, MediaLink, MediaRef, Step   # created by TASK-3699
from parrot._imports import lazy_import        # verified: packages/ai-parrot/src/parrot/_imports.py:110 (module_path, package_name=None, extra=None)
# bm25s via lazy_import("bm25s", package_name="bm25s", extra="bookstore") — pattern: pageindex/hybrid_search.py:164, 171-172, 182-192
# parrot_loaders is OPTIONAL — core must not hard-require it:
#   try: from parrot_loaders.basevideo import BaseVideoLoader  except ImportError: BaseVideoLoader = None
```

### Existing Signatures to Use
```python
# packages/ai-parrot-loaders/src/parrot_loaders/basevideo.py:860-887
def transcript_to_blocks(self, transcript: str) -> list:
    # dict input despite the `str` hint (F025): iterates transcript['chunks'], chunk['timestamp'] = (start, end), chunk['text']
    # output keys: id, start_time, end_time, start_seconds (float), end_seconds (float), text; skips chunks with None timestamps (uses print)

# bm25s usage (packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py:171-192)
retriever = bm25s.BM25(); tokenized = bm25s.tokenize(texts, stopwords="en"); retriever.index(tokenized)
documents, scores = retriever.retrieve(bm25s.tokenize([query], stopwords="en"), k=k)

# judge pattern (packages/ai-parrot/src/parrot/knowledge/bookstore/relations.py:372-413)
async def judge_relations(adapter, card, candidates, *, model_name="") -> RelationDraft
    # ONE adapter.ask_structured(prompt, RelationDraft) per source; drops ids not in candidates
# judgement bookkeeping pattern: bookstore/library.py:640-677 (judged = set() if force else store.judged_pairs(book_id);
#   store.record_judgements(...); replace only re-judged LLM links, origin="llm")
```

### Does NOT Exist
- ~~A reusable judgement-log type in `parrot.knowledge.bookstore`~~ — bookstore logs judgements through `CatalogStore.record_judgements` / `judged_pairs` (bookstore catalog SQLite, `relation_judgements` table); there is no `JudgementLog` class. Define `JudgementLog` here.
- ~~`YoutubeLoader` in `parrot_loaders/video.py`~~ — it is in `youtube.py:30` (F025).
- ~~Timecoded scenes from `VideoUnderstandingLoader`~~ — "Scene N" labels only (F025); do not use it.
- ~~`bm25s` in core deps~~ — it is in the `bookstore` extra; import lazily.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/manuals/video.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_video.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-loaders/src/parrot_loaders/basevideo.py#BaseVideoLoader.transcript_to_blocks",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/relations.py#judge_relations",
    "sym:packages/ai-parrot/src/parrot/_imports.py#lazy_import"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src:packages/ai-parrot-loaders/src pytest …`.
- `blocks_from_transcript` must work **without** `parrot_loaders` installed: reimplement the 10-line block
  conversion when the import fails (same keys; log, don't print, skipped chunks).
- Monotonic constraint: aligned segments are non-overlapping and ordered by step order.
- Judged tail: exactly one `adapter.ask_structured(prompt, JudgementDraft, temperature=0.0)` call for all unaligned
  steps not already judged (unless `force`); drop any `step_id`/`block_id` outside the candidates.
- `MediaRef.media_id` for a segment: `f"{manual_id}:vid:{sha256(uri)[:10]}:{t_start:.1f}"` (stable).
- No new third-party dependency; Google docstrings, type hints, Pydantic v2, `logger`; bm25s work is CPU-light —
  keep sync inside `align_deterministic`.
- Spec marks M7 "partly" delegation-eligible: threshold 0.35 is provisional (spike 3).

---

## Implementation Blueprint

### Steps (in order)
1. Models + `blocks_from_transcript` — *why*: one typed block shape regardless of loader availability.
2. `align_deterministic` — *why*: deterministic first keeps cost and hallucination out of the common case.
3. `JudgementLog` + `judge_alignment` — *why*: the judged tail mirrors `judge_relations` (bounded, id-filtered, logged).
4. `align_video` — *why*: orchestrates deterministic → judged → coverage rule → MediaRef/MediaLink output.
5. Tests.

### `packages/ai-parrot/src/parrot/knowledge/manuals/video.py` (CREATE) — part 1
```python
"""Video segment alignment: whisper blocks → steps (FEAT-601 M7)."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, Field

from parrot._imports import lazy_import
from parrot.knowledge.manuals.models import ManualCard, MediaLink, MediaRef, Step

try:  # optional satellite
    from parrot_loaders.basevideo import BaseVideoLoader
except ImportError:  # pragma: no cover - depends on installed satellites
    BaseVideoLoader = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.35
OVERVIEW_COVERAGE_THRESHOLD = 0.30


class TranscriptBlock(BaseModel):
    id: int
    start_seconds: float
    end_seconds: float
    text: str


def blocks_from_transcript(transcript: Mapping[str, Any]) -> list[TranscriptBlock]:
    """Wrap BaseVideoLoader.transcript_to_blocks (dict input despite the `str` hint — F025)."""
    # FILL IN: when BaseVideoLoader is importable call BaseVideoLoader.transcript_to_blocks(None-safe self, dict(transcript))
    #   only if it can run without instance state (it uses self.format_timestamp) — otherwise reimplement: iterate
    #   transcript["chunks"], skip None timestamps with logger.debug, newline→space — bounded by output keys above.
    return []


class SegmentAlignment(BaseModel):
    step_id: str
    block_ids: list[int]
    t_start: float
    t_end: float
    score: float
    method: Literal["bm25", "ordinal", "judged"]


def align_deterministic(
    steps: Sequence[Step], blocks: Sequence[TranscriptBlock], *, threshold: float = DEFAULT_THRESHOLD
) -> tuple[list[SegmentAlignment], list[Step]]:
    """bm25s retrieval per step + monotonic ordinal constraint; returns (aligned, unaligned)."""
    if not steps or not blocks:
        return [], list(steps)
    bm25s = lazy_import("bm25s", package_name="bm25s", extra="bookstore")
    retriever = bm25s.BM25()
    retriever.index(bm25s.tokenize([b.text for b in blocks], stopwords="en"))
    # FILL IN: per step (in order) retrieve top-k blocks; normalize scores to [0,1] per step; keep the best block whose
    #   start >= previous aligned end (monotonic) and score >= threshold; ordinal hints ("step three", "next",
    #   "paso tres", "siguiente") may extend a match (method="ordinal"); merge adjacent blocks into one segment —
    #   bounded by test_align_deterministic_monotonic (non-overlapping, ordered).
    return [], list(steps)
```

### `packages/ai-parrot/src/parrot/knowledge/manuals/video.py` (CREATE) — part 2
```python
class AlignmentJudgement(BaseModel):
    step_id: str
    block_ids: list[int]
    confidence: float = Field(..., ge=0.0, le=1.0)
    model: str = ""
    judged_at: datetime


class JudgementDraft(BaseModel):
    """Structured-output schema of the single judged-tail call."""

    judgements: list[AlignmentJudgement] = Field(default_factory=list)


class JudgementLog:
    """JSON-file log of judged (uri, step_id) pairs — the relate_books `judged_pairs` idea (bookstore/library.py:640-677)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def judged(self, uri: str) -> set[str]:
        # FILL IN: read JSON {uri: {step_id: judgement dict}} (missing file ⇒ empty) and return the step ids.
        return set()

    def record(self, uri: str, judgements: Sequence[AlignmentJudgement]) -> None:
        # FILL IN: merge + atomic write (tmp file + replace) — bounded by: idempotent, never loses earlier entries.
        pass

    def reset(self, uri: str) -> None:
        # FILL IN: drop the uri's entries (used by force=True).
        pass


class AlignmentReport(BaseModel):
    uri: str
    steps: int
    aligned: int
    judged: int
    coverage: float
    overview_only: bool
    warnings: list[str] = Field(default_factory=list)


async def judge_alignment(
    adapter: Any, steps: Sequence[Step], blocks: Sequence[TranscriptBlock], *, judged: set[str], model_name: str = ""
) -> list[AlignmentJudgement]:
    """One structured call for the unaligned tail; drops any step_id/block_id not in the candidates."""
    pending = [s for s in steps if s.identity.step_id not in judged]
    if adapter is None or not pending or not blocks:
        return []
    # FILL IN: prompt listing pending steps (id + text) and blocks (id, [t], text) fenced as untrusted data;
    #   draft = await adapter.ask_structured(prompt, JudgementDraft, temperature=0.0); coerce dict ⇒ model;
    #   keep only judgements whose step_id ∈ pending ids and block_ids ⊆ block ids — bounded by relations.py:372-413.
    return []


async def align_video(
    card: ManualCard,
    *,
    uri: str,
    transcript: Mapping[str, Any],
    adapter: Any | None,
    judgement_log: JudgementLog,
    force: bool = False,
) -> tuple[list[MediaRef], list[MediaLink], AlignmentReport]:
    """Deterministic pass, then judged tail unless already judged (force resets); coverage < 0.30 ⇒ overview only."""
    blocks = blocks_from_transcript(transcript)
    if force:
        judgement_log.reset(uri)
    # FILL IN: per procedure: align_deterministic; judge_alignment(..., judged=judgement_log.judged(uri)); record;
    #   coverage = aligned_steps / total_steps; < OVERVIEW_COVERAGE_THRESHOLD ⇒ one MediaRef(kind="video_segment",
    #   uri, t_start=first block start, t_end=last block end) per procedure with role "overview" and no per-step links;
    #   else one MediaRef + MediaLink(role="primary", origin="manual" for bm25/ordinal, "llm" for judged) per step.
    #   MediaLinks are returned as (step_id is on the caller side) — return links in the same order as the refs.
    #   — bounded by M7 (a step with no segment gets none) and the stable media_id scheme.
    report = AlignmentReport(uri=uri, steps=0, aligned=0, judged=0, coverage=0.0, overview_only=False)
    return [], [], report
```
**Why**: the log is a small JSON file because M7 must not add a store dependency, and replacing only judged
entries preserves deterministic links across re-runs (bookstore asymmetry rule).

> Note for the executor: `align_video` returns `(refs, links, report)` per the spec skeleton; because `MediaLink`
> carries no step id, return links **index-aligned** with refs and put the step id in `MediaRef.label`
> (`label=step_id`) so TASK-3713 can attach them. Record this choice in the Completion Note.

### `packages/ai-parrot/tests/knowledge/manuals/test_video.py` (CREATE)
```python
"""FEAT-601 M7 — video alignment."""
from __future__ import annotations

import pytest

pytest.importorskip("bm25s")

from parrot.knowledge.manuals import video as vd  # noqa: E402


def _transcript(texts: list[str]) -> dict:
    return {"chunks": [{"timestamp": (i * 10.0, i * 10.0 + 9.0), "text": t} for i, t in enumerate(texts)]}


def test_align_deterministic_monotonic() -> None:
    # FILL IN: 3 Steps (build via TASK-3699 models with evidence) + blocks echoing steps 1 and 3 ⇒ aligned in order,
    #   non-overlapping, step 2 returned as unaligned.
    ...


async def test_judge_alignment_drops_hallucinated_ids(tmp_path) -> None:
    # FILL IN: scripted adapter returns one valid judgement and one with unknown step_id/block_id ⇒ only valid kept;
    #   JudgementLog.record then judged() excludes it; force=True via align_video resets.
    ...


async def test_align_video_low_coverage_overview(tmp_path) -> None:
    # FILL IN: 10 steps, transcript matching 2 ⇒ coverage 0.2 ⇒ report.overview_only and one overview MediaRef per procedure.
    ...
```

### FILL IN checklist
- [ ] `blocks_from_transcript` (optional-loader fallback).
- [ ] `align_deterministic` scoring, monotonic constraint, ordinal hints.
- [ ] `JudgementLog.judged/record/reset`.
- [ ] `judge_alignment` prompt + id filtering.
- [ ] `align_video` orchestration + coverage rule + media id scheme.
- [ ] Test bodies.

---

## Acceptance Criteria

- [ ] Deterministic alignment is monotonic and non-overlapping; unaligned steps returned.
- [ ] Judged ids outside the candidates are dropped; `force` resets the log.
- [ ] Coverage < 0.30 ⇒ one overview `MediaRef`, no per-step segments.
- [ ] Module imports without `parrot_loaders`; `ruff check` + `black --check -l 120` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_video.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_align_deterministic_monotonic` | bm25s + ordinal constraint ⇒ non-overlapping monotonic segments; unaligned returned |
| `test_judge_alignment_drops_hallucinated_ids` | judged ids outside candidates dropped; `force` resets `judged` |
| `test_align_video_low_coverage_overview` | coverage < 0.30 ⇒ one overview `MediaRef`, no per-step segments |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/training-agent.spec.md` (module section named in Context).
2. **Check dependencies** — every `Depends-on` task must be in `sdd/tasks/completed/` (or merged in your feature branch).
3. **Verify the Codebase Contract** — before writing ANY code confirm every import, signature and line anchor
   above still holds (`grep -n` / `read`). Symbols marked "created by TASK-<X>" must exist now that the
   dependency landed; if a name differs, follow the landed code and record the deviation.
4. **Update status** in `sdd/tasks/index/training-agent.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes.
6. **Verify** — run every command in *Validation Commands* (with the worktree `PYTHONPATH`), plus `ruff check`
   and `black --check -l 120` on the touched files.
7. **Move this file** to `sdd/tasks/completed/`, set the index entry to `"done"`, fill in the Completion Note.

---

## Completion Note


- Task: TASK-3709
- Feature: training-agent
- Implementation SHA: 3b5aeab5e7262567c97a9c7c657228a0896cf43a
- Closed at (UTC): 2026-09-25T09:39:16+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 335.64s · Tokens: n/a |
| supplementary_test_evidence | 109 passed, 1 skipped, 0 failed (scoped direct pytest over manuals+catalog+figures+carding+video+contracts/test_ontology_domain) |
