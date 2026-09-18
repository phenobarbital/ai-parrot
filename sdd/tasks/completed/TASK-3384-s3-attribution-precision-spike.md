# TASK-3384: G3/S3 gate — attribution precision and verified-outcome evidence schema

**Feature**: FEAT-571 — Agent Memory Dynamics
**Spec**: `sdd/specs/memory-dynamics.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 row **G3** (Lane 0a gate, brainstorm spike S3). The whole review model rests on
one rule: *a review requires delivered memory, attribution and a verified outcome — no
signal means no review* (spec §1 Goals, AC04/AC05). Today nothing in the codebase can
supply that: `EpisodicMemoryMixin._safe_record_ask` hard-codes `SUCCESS`/importance 3
for every conversation; `ToolInvocation.status` defaults to `COMPLETED`; the coder
engine derives feedback *exposure* from a `[coder-feedback:` text marker in the prompt
and `CoderReview` carries fix commits, not memory ids (C3, C10, C14).

S3 must measure, on delivered-memory manifests with independently judged outcomes, how
precise **cited** vs **overlap** attribution is (precision, false reinforcement, missed
attribution, tool-overlap collisions), then **freeze**: the overlap default and cap
(candidate cap 3 — experiment input), the recovery-linkage predicate (what counts as
"verified success fixes the cited error"), the trusted-receipt adapter shape for
runtime tool outcomes and coder attempt outcomes, and the evidence schema
`ReviewSignal`/`MemoryExposure`/`MemoryCitation` need. U1 (citations first or both) and
U3 (precision target) are **owner acceptance decisions**; S3 collects the numbers.

---

## Scope

- Build a **judgment corpus** of 50 outcomes: each item = an exposure manifest (ordered
  delivered memory refs + packed-content digest), the attempt/turn outcome evidence, the
  candidate attributions from (a) explicit citation and (b) overlap heuristics, and an
  **independent judgment** (`relevant` / `not_relevant` / `unknown` per delivered memory).
  Source real traces where available (episodic mixin `get_warnings` output, sdd-coder
  attempts from the shared ledger); otherwise synthesize labeled traces and **declare the
  limitation** (spec §3 G3 "Insufficient real trace coverage is a gate limitation").
- Persist judgments as `judgments.jsonl` with **input hashes only** (sha256 of the
  packed content / transcript) — never commit transcripts (spec §4 Test Data).
- Implement the overlap heuristic candidates in `harness.py` (token/entity overlap
  between lesson text and tool args/results; error-signature equality; recovery
  linkage: a subsequent verified success whose correction references the cited
  memory) and compute per-strategy precision / false-reinforcement / missed-attribution
  / collision rate at caps 1, 3, 5 and unbounded.
- Enumerate **untrusted vs trusted** outcome sources from source (`ToolInvocation`
  default status, `getattr(tool_result, "success", True)` in
  `record_tool_episode`, empty corrections list, `CoderReview.fix_commits` reachability
  check, engine completion) and propose the trusted-receipt adapter table.
- Commit `REPORT.md`, `metrics.json`, `judgments.jsonl`, `amendment.md` (overlap
  default/cap, recovery predicate, evidence schema fields, receipt adapters, acceptance
  rubric; U1/U3 marked decided or pending). Logs → `artifacts/logs/`.

> **Amendment (sdd-worker, 2026-09-18): all spike artifacts (`judgments.jsonl`, REPORT.md,
> metrics.json, amendment.md) are relocated from `sdd/state/FEAT-571/spikes/s3-attribution/`
> to `packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/` throughout this file.
> The FEAT-549 sdd-coder engine's fidelity gate (`check_fidelity()`) unconditionally rejects
> any coder-committed path starting with `sdd/`, regardless of what a task's own contract
> lists — so these gate deliverables must live in a directory the coder already owns. The
> orchestrator (sdd-worker) is responsible for mirroring the final REPORT.md/metrics.json/
> amendment.md/judgments.jsonl into `sdd/state/FEAT-571/spikes/s3-attribution/` as a
> post-merge step for owner review.

**NOT in scope**: changing `EpisodicMemoryMixin`, `EpisodicMemoryToolkit`, the unified
manager/context or the coder engine (M3/M5); creating `parrot/memory/dynamics/*` (M1);
implementing `cite_memory` (M3); editing the spec (owner applies `amendment.md`);
deciding U1/U3 (owner).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/__init__.py` | CREATE | package marker |
| `packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/harness.py` | CREATE | manifest/citation/overlap models, strategies, metrics, corpus IO, report writer |
| `packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/test_s3_harness.py` | CREATE | fast strategy/metric tests + env-gated corpus evaluation |
| `packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/judgments.jsonl` | CREATE | 50 judged items (hashes, labels, provenance — no transcripts) |
| `packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/REPORT.md` | CREATE | reproducible gate report |
| `packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/metrics.json` | CREATE | raw per-strategy/per-cap metrics |
| `packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/amendment.md` | CREATE | proposed attribution/evidence-schema amendment |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `fc1a5728a55648566e264cb95c5df36190438204` on 2026-09-18.
> `core/` = `packages/ai-parrot/src/parrot/`.

### Verified Imports
```python
from parrot.memory.episodic.models import EpisodicMemory, EpisodeOutcome, EpisodeCategory, MemoryNamespace  # core/memory/episodic/models.py:55,20,29,214
from parrot.memory.episodic.tools import EpisodicMemoryToolkit          # core/memory/episodic/tools.py:22
from parrot.memory.compaction.models import ToolInvocation, ToolStatus  # core/memory/compaction/models.py:46,24
from parrot.memory.unified.models import MemoryContext                  # core/memory/unified/models.py:12
from parrot.memory.unified.context import ContextAssembler              # core/memory/unified/context.py:17
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedback, CoderFeedbackStore    # coder_feedback.py:24,80
from parrot.knowledge.wiki.ledger.coder_reviews import CoderReview, CoderReviewMeasurement   # coder_reviews.py:21,39
from parrot.flows.dev_loop.models import DevelopmentOutput              # core/flows/dev_loop/models/base.py:510 (re-exported by the package)
```

### Existing Signatures to Use (read-only evidence for the report)
```python
# core/memory/episodic/mixin.py
async def _safe_record_ask(self, namespace, query, response) -> None:   # :464 — record_episode(outcome=EpisodeOutcome.SUCCESS :477, importance=3 :479): unverified success today
def _stringify_episode_response(...)                                     # :36 ;  async def _record_post_ask(...) :423 schedules the above

# core/memory/episodic/tools.py
class EpisodicMemoryToolkit(AbstractToolkit):                            # :22 ; __init__(store, namespace, ...) :37
    async def search_episodic_memory(self, query: str, top_k: int = 5, failures_only: bool = False) -> str   # :47
    async def record_lesson(self, situation: str, lesson: str, category: str = "decision", importance: int = 5) -> str  # :97
    async def get_warnings(self, context: str = "") -> str               # :153  (text; no memory ids survive into the prompt)

# core/memory/episodic/store.py
async def record_tool_episode(self, namespace, tool_name, tool_args, tool_result, user_query=None) -> EpisodicMemory  # :235
#   success = getattr(tool_result, "success", True) :260 ; status = getattr(tool_result, "status", "success") :262 → defaults are NOT proof

# core/memory/compaction/models.py
class ToolStatus(str, Enum): COMPLETED = "completed"; ERROR = "error"    # :24
@dataclass class ToolInvocation:                                         # :46 ; status: ToolStatus = ToolStatus.COMPLETED  :71 (default = untrusted)

# core/memory/unified/models.py / context.py
class MemoryContext(BaseModel):  # :12 — strings + token counts; def to_prompt_string(self) -> str :47 ; NO exposure ids
class ContextAssembler:          # :17 ; def assemble(self, episodic_warnings="", relevant_skills="", conversation="", semantic_knowledge="") -> MemoryContext :49 (budget may trim text)

# core/knowledge/wiki/ledger/coder_reviews.py
class CoderReview(BaseModel):    # :21 — task_id :29, attempt_uid :30, backend :31, model :32, fix_commits :33, review_evidence :34, execution_id :35 ; no memory ids
class CoderReviewMeasurement(CoderReview): exposure: Literal["with_feedback","without_feedback","unavailable"] :42 ; feedback_tokens :43

# core/flows/dev_loop/sdd_coder/engine.py
async def record_review(self, feature, worktree, review: CoderReview, execution_id=None) -> CoderFeedbackReceipt   # :1456
#   fix commit must be reachable, subject startswith "fix(" and contain task id + "review fixes" :1476-1486
#   exposure derived from text marker `"[coder-feedback:" in context` :1488-1492  (the marker S3 replaces with manifests)
#   self._feedback_unknown_exposure: set[str] :393
# core/flows/dev_loop/sdd_coder/toolkit.py
async def coder_record_feedback(...)  # :218   async def coder_record_review(...)  # :239   (public signatures — preserved by M5)

# core/knowledge/wiki/ledger/coder_feedback.py
class CoderFeedback(BaseModel): pattern :39 (error-signature slug) ; correction :43 (lesson) ; verification :44 ; def feedback_id(self) -> str :67
class CoderFeedbackStore: from_root(root) :92 ; _read() :114 ; context(backend, model, files, max_tokens=1800, max_age_days=90) -> str :129

# core/flows/dev_loop/models/base.py
class DevelopmentOutput(BaseModel): files_changed, commit_shas, summary, incomplete_tasks, worker_summaries, merge_performed  # :510 ; NO checked_patterns
```

### Does NOT Exist
- ~~`MemoryExposure`, `MemoryCitation`, `ReviewSignal`, `CheckedPattern`~~ — proposed models (spec §2); the spike defines *local* dataclasses whose fields feed the amendment.
- ~~exposure ids / delivered-memory manifests in `MemoryContext` or the packed prompt~~ — absent (spec C8); today only text survives packing.
- ~~`checked_patterns` on `DevelopmentOutput`/`TaskResult`~~ — absent (spec C11); coder prompts claim checked patterns in prose only (`.claude/agents/sdd-coder.md:115-124` §a.1).
- ~~per-memory verified grades in `CoderReview`/`CoderFeedback`~~ — absent (spec §6). Zero fix commits ≠ verified application of every cited lesson.
- ~~a trusted "task success" signal from `ToolInvocation.status`, `ToolResult.success` defaults, or an empty corrections list~~ — spec §2 Review Admission step 2 lists these as insufficient.
- ~~`EpisodicMemoryToolkit.cite_memory`~~ — M3 adds it after this gate.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/harness.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/test_s3_harness.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/judgments.jsonl", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/REPORT.md", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/metrics.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/amendment.md", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/episodic/mixin.py#EpisodicMemoryMixin._safe_record_ask",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/tools.py#EpisodicMemoryToolkit",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/tools.py#EpisodicMemoryToolkit.get_warnings",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.record_tool_episode",
    "sym:packages/ai-parrot/src/parrot/memory/compaction/models.py#ToolInvocation",
    "sym:packages/ai-parrot/src/parrot/memory/compaction/models.py#ToolStatus",
    "sym:packages/ai-parrot/src/parrot/memory/unified/models.py#MemoryContext",
    "sym:packages/ai-parrot/src/parrot/memory/unified/context.py#ContextAssembler.assemble",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py#CoderReview",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py#CoderReviewMeasurement",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py#CoderFeedback",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py#CoderFeedbackStore",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.record_review",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py#DevelopmentOutput"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Independent judgment**: the judge must not see the strategy outputs; store `judge`
  (`human:<initials>` or `model:<id>`), `judged_at`, and the input hash per item. If a
  model judges, say so in REPORT.md limitations.
- **No transcripts in git**: `judgments.jsonl` rows carry `packed_sha256`,
  `outcome_sha256`, refs, labels, strategy outputs — never prompt or tool text.
- **Grade table is applied after admission**: compute, per item, which row of the spec
  §2 grade table would fire under each strategy (No review / AGAIN / EASY→GOOD cap /
  HARD / GOOD) so false reinforcement is counted as "a grade that would have been
  applied to a `not_relevant` memory".
- **Recovery linkage is structural**: string equality between lesson prose and a
  suggested action does **not** establish it (spec §2); the candidate predicate must
  reference the correction/check artifact (fix commit, passed check id, error signature
  before/after).
- **Collision metric**: count outcomes where ≥2 delivered memories match the same tool
  overlap and only one is `relevant`.
- Formatting: `black` 120 cols; `ruff check` clean on the spike package. No new deps.

### References in Codebase
- `core/flows/dev_loop/sdd_coder/engine.py:1476-1492` — the only verified outcome artifacts today (fix-commit reachability, exposure marker) → seed for the trusted-receipt adapter table.
- `core/memory/episodic/store.py:255-275` — how tool outcomes are mapped today (defaults → SUCCESS).
- `sdd/state/FEAT-569/findings/F004-outcomes.md`, `F008-context.md` — proposal findings this gate quantifies.

---

## Implementation Blueprint

### Steps (in order)
1. Write `harness.py` local models (`DeliveredRef`, `Exposure`, `OutcomeEvidence`, `Judgment`, `Item`) and corpus IO with hashing — *why*: the same record shape feeds metrics, `judgments.jsonl` and the amendment's evidence schema.
2. Implement strategies `cited`, `overlap_tokens`, `overlap_error_signature`, `recovery_linkage`, and `combine(strategies, cap)` — *why*: the gate compares strategies at several caps; each must be a pure function of (exposure, evidence).
3. Implement `grade_row(...)` mirroring spec §2's ordered table and the metrics (`precision`, `false_reinforcement`, `missed_attribution`, `collision_rate`) — *why*: false reinforcement is only meaningful in terms of grades that would have fired.
4. Assemble the 50-item corpus (real traces first, synthetic labeled fallbacks flagged `provenance: synthetic`), judge independently, write `judgments.jsonl` — *why*: spec §3 G3 requires 50 independently judged outcomes with manifests.
5. Write `test_s3_harness.py`: fast tests on fixture items + gated corpus evaluation writing REPORT.md/metrics.json; run once with `PARROT_SPIKE_FULL=1`, log to `artifacts/logs/feat-571-s3-<ts>.log`, fill `amendment.md` — *why*: reproducible numbers behind U1/U3.

### `packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/harness.py` (CREATE)
```python
"""S3 spike harness: delivered-memory manifests, attribution strategies, grade-table rows, metrics, corpus IO."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

logger = logging.getLogger(__name__)
SPIKE_DIR = Path(__file__).resolve().parent  # coder-owned spike package dir — sdd-coder fidelity gate forbids commits under sdd/
Label = Literal["relevant", "not_relevant", "unknown"]
GradeRow = Literal["no_review", "again", "easy", "good_capped", "hard", "good"]


def sha256_text(text: str) -> str:
    """Stable digest used in place of any transcript content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DeliveredRef:
    """One memory version delivered by final packing (spec §2 MemoryRef: namespace, kind, id, content_version)."""

    memory_id: str
    content_version: str
    kind: str  # "episode" | "brain"
    error_signature: str | None
    lesson_tokens: frozenset[str]


@dataclass(frozen=True)
class Exposure:
    """Spec §2 MemoryExposure — created by final packing, not by the LLM."""

    exposure_id: str
    attempt_or_turn_id: str
    delivered: tuple[DeliveredRef, ...]
    packed_sha256: str


@dataclass(frozen=True)
class OutcomeEvidence:
    """Trusted-receipt shaped outcome (spec §2 ReviewSignal): verified, first attempt, corrections, error signature, recovery."""

    outcome_id: str
    verified: bool
    success: bool
    first_attempt: bool
    correction_count: int
    error_signature: str | None
    recovery_refs: tuple[str, ...]  # memory_ids whose correction/check artifact is structurally linked
    cited: tuple[str, ...]  # explicit citations (untrusted until validated against `delivered`)
    tool_tokens: frozenset[str]
    source: str  # "tool_runtime" | "coder_engine" | "synthetic"


@dataclass
class Item:
    """One judged outcome: exposure + evidence + independent labels per delivered memory."""

    item_id: str
    provenance: str  # "real" | "synthetic"
    exposure: Exposure
    evidence: OutcomeEvidence
    labels: dict[str, Label]
    judge: str
    judged_at: str
    strategy_outputs: dict[str, list[str]] = field(default_factory=dict)


Strategy = Callable[[Exposure, OutcomeEvidence], list[str]]


def cited(exposure: Exposure, evidence: OutcomeEvidence) -> list[str]:
    """Citations restricted to refs actually delivered by this exposure (cross-scope ids are dropped)."""
    delivered = {ref.memory_id for ref in exposure.delivered}
    return [mid for mid in evidence.cited if mid in delivered]


def overlap_tokens(exposure: Exposure, evidence: OutcomeEvidence) -> list[str]:
    # FILL IN: Jaccard(lesson_tokens, tool_tokens) ≥ threshold → attributed; deterministic tie order by memory_id. Threshold is a report parameter.
    raise NotImplementedError


def overlap_error_signature(exposure: Exposure, evidence: OutcomeEvidence) -> list[str]:
    # FILL IN: nonempty normalized signature equality only (spec §2 grade table row AGAIN).
    raise NotImplementedError


def recovery_linkage(exposure: Exposure, evidence: OutcomeEvidence) -> list[str]:
    # FILL IN: memory_ids in evidence.recovery_refs ∩ delivered; NEVER prose equality (spec §2 "string equality ... does not establish it").
    raise NotImplementedError


def combine(strategies: list[Strategy], cap: int | None) -> Strategy:
    # FILL IN: union in strategy order, dedupe, truncate to cap (None = unbounded).
    raise NotImplementedError


def grade_row(evidence: OutcomeEvidence, *, attributed: bool, memory_error_signature: str | None, recovered: bool, overlap_only: bool) -> GradeRow:
    # FILL IN: ordered table from spec §2 "Review Admission and Grade Precedence"; EASY → good_capped when overlap_only.
    raise NotImplementedError


def metrics(items: list[Item], strategy_name: str) -> dict[str, float]:
    # FILL IN: precision, false_reinforcement (grade ≠ no_review on not_relevant), missed_attribution (relevant not attributed),
    # collision_rate (≥2 attributed, exactly 1 relevant); ignore 'unknown' labels but report their count.
    raise NotImplementedError


def load_corpus(path: Path = SPIKE_DIR / "judgments.jsonl") -> list[Item]:
    # FILL IN: parse JSONL → Item (tuples/frozensets restored); validate 50 rows, no transcript fields present.
    raise NotImplementedError


def write_report(results: dict[str, Any], *, commands: list[str], limitations: list[str]) -> Path:
    SPIKE_DIR.mkdir(parents=True, exist_ok=True)
    (SPIKE_DIR / "metrics.json").write_text(json.dumps(results, indent=2, sort_keys=True, default=str) + "\n")
    # FILL IN: REPORT.md — Commands · Corpus provenance (real/synthetic counts, judge identity) · Metrics table per strategy × cap ·
    # Untrusted-vs-trusted outcome source table (source line refs) · Pass/Fail vs U3 target (or "pending") · Limitations · amendment pointer.
    raise NotImplementedError
```
**Why this shape**: `cited()` is complete because its rule is fixed by the spec (citation is a *subset of delivered refs*); overlap and recovery are the experiment. `Item.labels` is per delivered memory so precision/false-reinforcement are computed at the granularity a review would be applied.

### `packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/test_s3_harness.py` (CREATE)
```python
"""S3 gate tests: fast strategy/metric checks (always) + corpus evaluation (PARROT_SPIKE_FULL=1)."""
from __future__ import annotations

import os

import pytest

from . import harness

FULL = os.environ.get("PARROT_SPIKE_FULL") == "1"


@pytest.fixture
def item() -> harness.Item:
    # FILL IN: one synthetic Item with 3 delivered refs (1 relevant, 1 not_relevant, 1 unknown), a cross-scope citation, an error signature match.
    raise NotImplementedError


def test_cited_drops_cross_scope_ids(item) -> None:
    out = harness.cited(item.exposure, item.evidence)
    assert all(mid in {r.memory_id for r in item.exposure.delivered} for mid in out)


def test_recovery_linkage_ignores_prose_equality(item) -> None:
    # FILL IN: lesson text == suggested action but recovery_refs empty → [] (spec §2).
    raise NotImplementedError


def test_grade_row_precedence(item) -> None:
    # FILL IN: repeated signature → again ; verified recovery → easy ; overlap-only recovery → good_capped ; corrections → hard ;
    # first-attempt clean → good ; unverified → no_review.
    raise NotImplementedError


def test_metrics_count_false_reinforcement(item) -> None:
    # FILL IN: strategy attributing the not_relevant ref yields false_reinforcement > 0 and precision < 1.
    raise NotImplementedError


@pytest.mark.skipif(not FULL, reason="set PARROT_SPIKE_FULL=1 to evaluate the 50-item corpus and write REPORT.md")
def test_corpus_evaluation_writes_report() -> None:
    # FILL IN: items = harness.load_corpus(); assert len(items) == 50; results per strategy × cap ∈ {1,3,5,None}; write_report(...).
    raise NotImplementedError
```
**Why**: the fast tests pin the admission rules the amendment freezes; the gated test produces the numbers behind U1/U3.

### `packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/amendment.md` (CREATE)
```markdown
# Proposed spec amendment — S3 (TASK-3384) · status: PROPOSED (owner review; U1/U3 decisions)

## Freeze
- Attribution default for generic agents: FILL IN (cited only | cited + overlap opt-in | both) — evidence: metrics rows FILL IN
- Overlap cap: FILL IN (candidate 3) · overlap token threshold: FILL IN
- Recovery-linkage predicate: FILL IN (structural refs: fix commit / passed check id / signature-before-after); prose equality excluded
- Evidence schema fields for ReviewSignal / MemoryExposure / MemoryCitation: FILL IN (from harness dataclasses)
- Trusted-receipt adapters: tool runtime = FILL IN ; coder engine = completion + relevant passed checks (merge alone ≠ application)
- Untrusted sources (never sufficient): ToolInvocation.status default, ToolResult.success default, empty corrections, model summary, transport success

## Pass/Fail
- Corpus: 50 items (real: N, synthetic: M, judge: FILL IN)
- Precision (cited / overlap / both @cap): FILL IN ; false reinforcement: FILL IN ; missed attribution: FILL IN ; collisions: FILL IN
- Against U3 target (FILL IN or "owner decision pending"): PASS|FAIL|PENDING

## Sections to edit on acceptance
§2 "Review Admission and Grade Precedence", §2 Data Models (ReviewSignal/MemoryExposure/MemoryCitation/CheckedPattern), §3 M1 (grade schema freeze), M3 eligibility, §8 overlap question, U1.
```
**Why**: spec §3 G3 "freeze overlap default/cap, recovery predicate and evidence schema" — this is the reviewable artifact; the spec edit is the owner's.

### FILL IN checklist
- [ ] `harness.py::overlap_tokens/overlap_error_signature/recovery_linkage/combine` — pure strategies; bounded by spec §2 admission rules
- [ ] `harness.py::grade_row` — exact ordered table incl. EASY→GOOD overlap cap; bounded by spec §2 table
- [ ] `harness.py::metrics/load_corpus/write_report` — four G3 metrics, hash-only corpus; bounded by spec §3 row G3 + §4 Test Data
- [ ] `judgments.jsonl` — 50 items, independent judge recorded, no transcripts
- [ ] `REPORT.md`, `metrics.json`, `amendment.md` — from the logged full run; U1/U3 status explicit

---

## Acceptance Criteria

- [ ] Fast tests pass (cross-scope citation drop, prose-equality exclusion, grade precedence, false-reinforcement counting)
- [ ] `judgments.jsonl` has 50 rows with input hashes, per-memory labels, judge identity and provenance; `git grep` finds no transcript text
- [ ] Full evaluation run once (`PARROT_SPIKE_FULL=1`), log in `artifacts/logs/`, REPORT.md quotes the command
- [ ] REPORT.md reports precision / false reinforcement / missed attribution / collision rate per strategy at caps 1, 3, 5, unbounded, plus the untrusted-vs-trusted source table with source line refs
- [ ] `amendment.md` proposes overlap default/cap, recovery predicate, evidence schema, receipt adapters and acceptance rubric; U1/U3 marked decided or pending; real-trace coverage limitation stated
- [ ] `black --check` and `ruff check` clean on `packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/`
- [ ] No production code or spec edits

---

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/test_s3_harness.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/test_s3_harness.py — see blueprint
def test_cited_drops_cross_scope_ids(item): ...
def test_recovery_linkage_ignores_prose_equality(item): ...
def test_grade_row_precedence(item): ...
def test_metrics_count_false_reinforcement(item): ...
def test_corpus_evaluation_writes_report(): ...   # PARROT_SPIKE_FULL=1 only
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 "Review Admission and Grade Precedence", §2 Data Models, §3 rows G3/M3/M5, §4 Test Data, §6 C3/C10/C11/C14, §8 U1/U3
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — every anchor with `grep`/`sed -n`
4. **Update status** in `sdd/tasks/index/memory-dynamics.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `FILL IN`; keep all code in the spike dir
6. **Build and judge the corpus**, run the full evaluation once, save the log
7. **Verify** acceptance criteria; the gate passes only when the owner reviews `amendment.md` and decides U1/U3
8. **Move this file** to `sdd/tasks/completed/TASK-3384-s3-attribution-precision-spike.md`, update the index → `"done"`, fill the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (orchestrated native `sonnet` delivery)
**Date**: 2026-09-18
**Notes**: 50-item judgment corpus (0 real / 50 synthetic — declared gate limitation, no
coder-review ledger or episodic-store snapshot was available in this worktree to mine real
traces) exercising every grade-table branch and attribution edge case. Metrics per
strategy×cap: `cited` holds precision=1.000 at every cap (missed_attribution=0.300,
false_reinforcement=0.000); `overlap_tokens` trades precision for recall
(1.000→0.920 as cap grows from 1→3/5, false_reinforcement/collision_rate rising to 0.080).
U1 (citations-first vs both) and U3 (precision target) explicitly marked PENDING — owner
acceptance decisions, not resolved by this gate. `amendment.md` proposes `cited`-only
default, overlap cap 3/threshold 0.3, the structural recovery-linkage predicate (never
prose equality), the evidence-schema field mapping, and 2 trusted-receipt adapters
(tool_runtime, coder_engine) plus the untrusted-source list. Fast tests (5 passed, 1
env-gated skip) verified green post-merge in the feature worktree; `judgments.jsonl`
confirmed 50 rows, zero transcript-shaped keys.
Full REPORT.md/metrics.json/amendment.md/judgments.jsonl:
`packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/` (mirrored by the
orchestrator to `sdd/state/FEAT-571/spikes/s3-attribution/` for owner/architecture review —
the gate itself is NOT passed until that review happens and U1/U3 are decided).

**Deviations from spec**: Task's own "Files to Create / Modify" list originally placed
`judgments.jsonl`/REPORT.md/metrics.json/amendment.md under
`sdd/state/FEAT-571/spikes/s3-attribution/`; amended by sdd-worker (2026-09-18, Option A,
user-approved) to `packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/` because
the FEAT-549 sdd-coder engine's fidelity gate unconditionally rejects any coder-committed
path under `sdd/`. No other deviation from the blueprint (one added fast test,
`test_metrics_ignores_unknown_labels`, scoped strictly to the `metrics()` contract already
in scope).

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: ~672s ·
Tokens: n/a (native — usage not tracked by the engine)
