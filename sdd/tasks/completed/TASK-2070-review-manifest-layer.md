# TASK-2070: Review manifest layer (JSONL, sampler, agreement)

**Feature**: FEAT-402 — Supervised Wiki Ingestion (charter-driven triage + HITL manifest review)
**Spec**: `sdd/specs/supervised-wiki-ingestion.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2069
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec (§3). The JSONL review manifest is the
HITL contract: `--dry-run` writes it, a human edits `decision` fields,
`--review` applies it. This module owns the triage data models shared by
the router and the manifest (`DimensionScores`, `Claim`, `TriageOutput`),
the run-header/entry models, writer/reader, the stratified audit sampler,
and `agreement_rate()`.

Design reference (adapt, do NOT import):
`sdd/state/FEAT-402-supervised-wiki-ingestion/references/manifest.example.jsonl`
and `references/schemas.py`.

---

## Scope

- Implement `packages/ai-parrot/src/parrot/knowledge/wiki/review.py`:
  - Models (spec §2 Data Models, verbatim field lists): `DimensionScores`,
    `Claim`, `TriageOutput` (briefing, scores, claims, `sensitive`,
    `category_hint` — **no composite field**: composite is computed in
    code, TASK-2071), `ManifestRunHeader` (charter sha256/version, mode,
    `novelty_backend`, counts, created_at), `ManifestDocEntry` (source_uri,
    file_hash, briefing, scores, composite, proposed_action, claims,
    decision, decision_source, audit_sample, audit_stratum).
  - `ManifestWriter`: writes one `run_header` JSON line then one line per
    doc entry; `ManifestReader`: parses, validates decisions
    (`admit|archive|discard` or null), rejects malformed edits with a
    clear error naming the line number.
  - `stratified_sample(entries, near_fraction=0.6, uniform_fraction=0.4, seed=...)`:
    flags `audit_sample`/`audit_stratum` in place — near-threshold stratum =
    entries closest to the admit/reject bounds.
  - `agreement_rate(entries) -> Optional[float]`: fraction of decided
    entries where `decision == proposed_action`; `None` when nothing decided.
  - Gray-zone-widening **proposal** helper per `CalibrationPolicy`
    (returns suggested new thresholds; never mutates the charter — propose-only).
- Write `tests/knowledge/wiki/test_review.py`.

**NOT in scope**: LLM calls or routing (TASK-2071), CLI flags (TASK-2075),
persistence to SQLite (TASK-2073).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/review.py` | CREATE | Manifest models + writer/reader + sampler + agreement |
| `tests/knowledge/wiki/test_review.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `ad6365242` (2026-08-02).

### Verified Imports
```python
from pydantic import BaseModel, Field
from parrot.knowledge.wiki.charter import Charter, Thresholds, CalibrationPolicy  # created by TASK-2069
```

### Existing Signatures to Use
```python
# From TASK-2069 (verify it is completed and check actual signatures):
# packages/ai-parrot/src/parrot/knowledge/wiki/charter.py
#   class Thresholds: def route(self, composite: float) -> Literal["admit", "gray", "reject"]
#   class CalibrationPolicy: near_fraction / uniform_fraction / widening fields
```

### Does NOT Exist
- ~~`parrot/knowledge/wiki/review.py`~~ — you are creating it.
- ~~`ManifestDocEntry`~~, ~~`ManifestRunHeader`~~, ~~`TriageOutput`~~, ~~`agreement_rate`~~ — only in the non-importable design sketch under `sdd/state/.../references/schemas.py`; re-implement per spec.
- **Grep trap**: searching `review.py` matches `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py` — unrelated dev-loop judge code; do NOT touch or import it.
- ~~`TriageOutput.composite`~~ — deliberately NOT a field; the LLM never emits a composite (spec §5).

---

## Implementation Notes

### Key Constraints
- JSONL: one JSON object per line; header is line 1 with an explicit
  `"kind": "run_header"` discriminator (entries: `"kind": "doc"`), so the
  reader is order-tolerant and future-proof.
- File I/O sync is fine (manifest read/write happens outside the async
  apply pipeline), but keep functions small so TASK-2075 can offload via
  `asyncio.to_thread` if needed.
- Sampler must be deterministic given a seed (tests depend on it).
- Pydantic models for ALL structures; Google-style docstrings.

### References in Codebase
- `sdd/state/FEAT-402-supervised-wiki-ingestion/references/manifest.example.jsonl` — target shape (adapt).
- Spec §2 "Data Models" — authoritative field lists.

---

## Acceptance Criteria

- [ ] Manifest round-trips: write → hand-edit a `decision` → read back with edits applied; header preserved.
- [ ] Reader rejects an invalid decision value with an error naming the offending line.
- [ ] `stratified_sample` honors 60/40 near-threshold/uniform fractions (seeded, deterministic in tests).
- [ ] `agreement_rate` math correct; `None` when no decisions present.
- [ ] Widening helper proposes thresholds without mutating the charter object.
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_review.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/review.py` clean
- [ ] Import works: `from parrot.knowledge.wiki.review import ManifestWriter, ManifestReader, agreement_rate`

---

## Test Specification

```python
# tests/knowledge/wiki/test_review.py
import pytest
from parrot.knowledge.wiki.review import (
    DimensionScores, ManifestDocEntry, ManifestReader, ManifestRunHeader,
    ManifestWriter, TriageOutput, agreement_rate, stratified_sample,
)

def test_manifest_roundtrip(tmp_path): ...
def test_manifest_rejects_bad_decision(tmp_path): ...
def test_stratified_sampler_fractions(): ...
def test_agreement_rate(): ...
def test_agreement_rate_none_when_undecided(): ...
def test_widening_is_propose_only(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2069 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm charter.py's actual class/field
   names from TASK-2069's implementation before importing
4. **Update status** in `sdd/tasks/index/supervised-wiki-ingestion.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and **update index** → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude, autonomous)
**Date**: 2026-08-02
**Notes**: Implemented `DimensionScores`, `Claim`, `TriageOutput` (no
composite field — verified via `test_triage_output_has_no_composite_field`),
`ManifestRunHeader`, `ManifestDocEntry` (both with an explicit `kind`
discriminator per the task's order-tolerance requirement),
`ManifestWriter`/`ManifestReader` (line-numbered `ManifestParseError` on
malformed JSON, duplicate/missing header, unknown `kind`, or invalid
`decision`), `stratified_sample()` (near-threshold stratum ranked by
distance to the nearest admit/reject boundary, uniform stratum via seeded
`random.Random`; mutates `audit_sample`/`audit_stratum` in place, returns
`None`), `agreement_rate()` (fraction of decided entries where
`decision == proposed_action`, `None` when nothing decided — matches the
task's literal wording, no `audit_sample` filter), and
`propose_gray_zone_widening()` (returns a brand-new `Thresholds` instance,
never mutates its input; respects `calibration.autotune == "off"`). All 19
unit tests pass (`pytest tests/knowledge/wiki/test_review.py -v`); `ruff
check` clean. Import verified: `from parrot.knowledge.wiki.review import
ManifestWriter, ManifestReader, agreement_rate`.

One design decision not fully pinned by the spec: `stratified_sample`'s
public signature required an explicit `sample_size: int` parameter (spec's
`New Public Interfaces` shows `stratified_sample(entries, near_fraction=0.6,
uniform_fraction=0.4, ...)` with an elided `...`, and `CalibrationPolicy`
from TASK-2069 has no overall audit-rate field to derive it from). Chose to
require the caller (CLI, TASK-2075) to pass `sample_size` explicitly rather
than inventing a `CalibrationPolicy.audit_rate` field not specified by
either TASK-2069 or the spec's Data Models.

**Deviations from spec**: none (see design-decision note above for one
resolved ambiguity in an elided signature, not a deviation from any stated
field or behavior).
