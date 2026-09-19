# TASK-3492: Attributed, revision-checked review

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3480, TASK-3485
**Assigned-to**: unassigned

---

## Context

Module 5's review half, and the home of the feature's resolved open question:

> **Q3 (confirmed)**: a maintainer explicitly accepts a candidate through the
> CLI in the wiki; Markdown export and committing an ADR file are optional.
> Acceptance sets `review_status='accepted'`, **retains `origin='inferred'` and
> `source_status='unknown'`**, and appends an attributed review event through
> the same revision-checked write. No documented ADR is required for acceptance.

That is AC11 in full. Accepting a candidate changes what the team has agreed to,
never what the record claims about history. This module is pure transformation —
it takes a record and a request and returns the next revision; the repository
does the writing.

---

## Scope

- Implement `apply_review(record, request) -> DecisionRecord` covering the four
  actions: `accept`, `reject`, `revise`, `link`.
- Append an attributed `ReviewEvent` with correct before/after hashes on every
  action, and bump `revision`.
- Enforce the immutability of `origin`, `source_status`, `decision_id`,
  `evidence`, `generation` and `review_history`'s existing entries.
- Implement the revision precondition check that yields `ADR_REVISION_CONFLICT`.
- Implement `render_export(record) -> str` for `adr export`.
- Test the AC11 matrix, including the concurrent-reviewer case.

**NOT in scope**: persisting (TASK-3485 does the CAS), service wiring
(TASK-3493), CLI (TASK-3496).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/review.py` | CREATE | `apply_review`, immutability guards, export rendering |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_review.py` | CREATE | AC11 matrix + concurrency + immutability |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.decisions.codec import render_markdown, review_fingerprint  # TASK-3480
from parrot.knowledge.wiki.decisions.models import (                                   # TASK-3479
    ADR_INVALID_ARGUMENT, ADR_REVISION_CONFLICT, CandidateEdit, DecisionError,
    DecisionLink, DecisionRecord, ReviewEvent, ReviewRequest,
)
```

Standard library: `datetime` (for `datetime.now(tz=UTC).isoformat()`).

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py  (TASK-3480)
def review_fingerprint(record: DecisionRecord) -> str: ...
#   Covers title/context/decision/consequences/observations/hypotheses and
#   review_status ONLY — deliberately not review_history, which would make the
#   audit hash self-referential (spec §2 ReviewEvent).
def render_markdown(record: DecisionRecord) -> str: ...

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py  (TASK-3479)
class ReviewEvent(_Strict):
    revision: int; action: Literal["accept","reject","revise","link"]
    actor: str; timestamp: str; reason: str
    before_sha1: str; after_sha1: str
class CandidateEdit(_Strict):
    title | context | decision | consequences | observations | hypotheses   # ONLY these
```

The existing wiki timestamp convention is
`datetime.now(tz=UTC).strftime("%Y-%m-%d")` for notes (`tools.py:~432`); review
events need full ISO-8601, so use `.isoformat()`.

### Does NOT Exist

- ~~a review action that changes `origin` or `source_status`~~ — AC11 forbids
  it. `DecisionRecord`'s validator (TASK-3479) also rejects it structurally.
- ~~a delete/purge review action~~ — spec §2: "Rejection does not delete a
  record" and "Generic deletion is not an ADR review action."
- ~~`CandidateEdit` touching `evidence`, `links`, `decision_id` or
  `generation`~~ — the model has exactly six fields; spec §2: "immutable fields
  cannot be changed by `CandidateEdit`".
- ~~an MCP tool or a model path that accepts a candidate~~ — spec §2: "No model
  invocation or MCP tool automatically accepts a candidate." That gate is
  enforced in TASK-3494; this module simply has no such entry point.
- ~~acceptance requiring a documented ADR~~ — Q3: "No documented ADR is required
  for acceptance."

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/review.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_review.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Action semantics (spec §2)

| Action | Effect |
|---|---|
| `accept` | `review_status='accepted'`. Origin and source status unchanged. No documented ADR required. |
| `reject` | `review_status='rejected'`. The record is **kept**, hidden from default reads. |
| `revise` | Apply `CandidateEdit`'s six fields; evidence and provenance preserved; `review_status` reset to `'unreviewed'`. |
| `link` | Append a `DecisionLink(target=documented_decision_id, relation='supersedes'\|'explains', provenance='asserted')`. Origin stays `inferred`. Requires an **existing** documented record. |

Every action appends one `ReviewEvent` and bumps `revision` by 1.

### Review history is append-only

Spec §2: "Preserve full review history in the record." Existing events are never
edited or dropped — that is what AC6's "cannot lose review history" means.

---

## Implementation Blueprint

### Steps (in order)

1. Write `check_revision` — *why*: the precondition must be evaluated before any
   mutation, so a stale request cannot even build a candidate next-revision.
2. Write the four per-action transforms — *why*: keeping them separate makes the
   immutability guarantee auditable field by field.
3. Write `apply_review` as check → transform → append event — *why*: the event's
   `before_sha1` must be taken from the record *before* the transform.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/review.py` (CREATE)

```python
"""Attributed, revision-checked review transforms (FEAT-578 Module 5).

Pure: takes a record plus a request and returns the next revision. The CAS
write belongs to ``DecisionRepository.save``.

The invariant this module exists to protect (Q3 / AC11): accepting an
inferred candidate changes ``review_status`` and NOTHING else about its
provenance. It stays ``origin='inferred'`` with
``source_status='unknown'`` forever.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from parrot.knowledge.wiki.decisions.codec import render_markdown, review_fingerprint
from parrot.knowledge.wiki.decisions.models import (
    ADR_INVALID_ARGUMENT,
    ADR_REVISION_CONFLICT,
    CandidateEdit,
    DecisionError,
    DecisionLink,
    DecisionRecord,
    ReviewEvent,
    ReviewRequest,
)

logger = logging.getLogger(__name__)

#: Fields no review action may ever change (spec §2). Asserted after every
#: transform, so a future action cannot quietly widen the surface.
IMMUTABLE_FIELDS = (
    "decision_id",
    "origin",
    "source_status",
    "source_status_raw",
    "source_path",
    "evidence",
    "generation",
    "schema_version",
)


def check_revision(record: DecisionRecord, expected_revision: int) -> None:
    """Refuse a review built against a superseded revision.

    Raises:
        DecisionError: ``ADR_REVISION_CONFLICT``. There is no automatic
            re-read or retry — the reviewer must look at what changed
            (spec §2 "no automatic review overwrite/retry").
    """
    if record.revision != expected_revision:
        raise DecisionError(
            ADR_REVISION_CONFLICT,
            f"{record.decision_id} is at revision {record.revision}, review expected {expected_revision}",
            decision_id=record.decision_id,
        )


def _apply_edit(record: DecisionRecord, edit: CandidateEdit) -> dict:
    """Field updates for a ``revise``, from the six editable fields only."""
    # FILL IN: build a dict of the non-None CandidateEdit fields, and ALWAYS
    # include review_status='unreviewed' — a revision invalidates the previous
    # review (spec §2 "Revision ... resets review status to unreviewed").
    raise NotImplementedError


def _apply_link(record: DecisionRecord, documented_decision_id: str) -> dict:
    """Field updates for a ``link`` to an existing documented record."""
    # FILL IN: append a DecisionLink(target_id=documented_decision_id,
    # relation='supersedes', provenance='asserted', evidence_indexes=[]) to a
    # COPY of record.links; do not mutate the original list, and do not change
    # origin. Bounded by spec §2 "records an asserted association without
    # changing inferred origin".
    raise NotImplementedError


def apply_review(record: DecisionRecord, request: ReviewRequest) -> DecisionRecord:
    """Validate and apply one attributed review action.

    Args:
        record: The record as just read, at ``request.expected_revision``.
        request: The maintainer's action. ``actor`` is mandatory —
            attribution is not optional (spec §2 ``ReviewEvent``).

    Returns:
        The next revision, with one appended :class:`ReviewEvent`. Existing
        history is never edited or dropped (AC6).

    Raises:
        DecisionError: ``ADR_REVISION_CONFLICT`` when stale,
            ``ADR_INVALID_ARGUMENT`` for a malformed action payload or a
            ``link`` whose target is not a documented record.
    """
    check_revision(record, request.expected_revision)
    before = review_fingerprint(record)
    # FILL IN: dispatch on request.action to build the `updates` dict —
    #   accept -> {"review_status": "accepted"}
    #   reject -> {"review_status": "rejected"}
    #   revise -> _apply_edit(record, request.replacement)
    #   link   -> _apply_link(record, request.documented_decision_id)
    # then updated = record.model_copy(update={**updates, "revision":
    # record.revision + 1}); assert every IMMUTABLE_FIELDS value is unchanged
    # (raise ADR_INVALID_ARGUMENT if not); compute after = review_fingerprint,
    # and append ONE ReviewEvent(revision=updated.revision, action=...,
    # actor=request.actor, timestamp=datetime.now(tz=UTC).isoformat(),
    # reason=request.reason, before_sha1=before, after_sha1=after) to a COPY of
    # record.review_history. Bounded by AC11 and spec §2's review paragraph.
    raise NotImplementedError


def validate_link_target(target: DecisionRecord | None, target_id: str) -> None:
    """Ensure a ``link`` action names an existing DOCUMENTED record.

    Raises:
        DecisionError: ``ADR_INVALID_ARGUMENT`` when the target is missing
            or is itself inferred — spec §2: "Linking requires an existing
            documented ADR record."
    """
    # FILL IN: None -> raise; target.origin != 'documented' -> raise. Bounded
    # by spec §2.
    raise NotImplementedError


def render_export(record: DecisionRecord) -> str:
    """Render a record as Markdown for ``adr export``.

    Writing or committing this output is explicitly outside the feature
    (spec §2); the command prints to stdout. The origin/status labels are
    part of the rendering, so an exported candidate is still unmistakably a
    candidate.
    """
    return render_markdown(record)
```

**Why this shape**: `before` is captured before the transform and `after` after
it, so the pair genuinely brackets the change; computing both from
`review_fingerprint` (which excludes `review_history`) is what stops the audit
hash from depending on itself. Asserting `IMMUTABLE_FIELDS` after every transform
rather than trusting each branch means a future fifth action cannot silently
widen what review can touch — the AC11 guarantee survives the next edit to this
file. Copying `links` and `review_history` rather than appending in place keeps
the input record usable by a caller that needs to retry after a conflict.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_review.py` (CREATE)

```python
"""Review semantics, attribution and immutability (FEAT-578 M5, AC11/AC6)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.models import (
    CandidateEdit,
    DecisionError,
    DecisionRecord,
    EvidenceRef,
    GenerationInfo,
    ReviewRequest,
)
from parrot.knowledge.wiki.decisions.review import apply_review, render_export, validate_link_target


@pytest.fixture
def candidate() -> DecisionRecord:
    """An unreviewed inferred candidate with evidence and generation info."""
    return DecisionRecord(
        decision_id="adr:candidate:abc",
        revision=1,
        title="Retry with backoff",
        decision="Retries use exponential backoff.",
        origin="inferred",
        source_status="unknown",
        review_status="unreviewed",
        observations=["The client sleeps 2**n seconds."],
        hypotheses=["Probably to avoid thundering herd on the upstream."],
        evidence=[EvidenceRef(page_id="file:a.py", rel_path="a.py", start_line=1, end_line=3,
                              source_sha1="d", excerpt="code", kind="code")],
        generation=GenerationInfo(model_spec="p:m", scope_id="sym:a.py#f", input_sha1="i",
                                  max_input_tokens=12000, max_output_tokens=2000),
    )


def _req(action, **kw) -> ReviewRequest:
    return ReviewRequest(decision_id="adr:candidate:abc", expected_revision=1, action=action,
                         actor="human:maintainer", reason=kw.pop("reason", "reviewed"), **kw)


class TestMaintainerWikiAcceptance:
    def test_acceptance_needs_no_documented_adr(self, candidate):
        """Q3/AC11: acceptance in the wiki, no committed ADR file required."""
        accepted = apply_review(candidate, _req("accept"))
        assert accepted.review_status == "accepted"

    def test_acceptance_preserves_inferred_provenance(self, candidate):
        """AC11: the central invariant of the whole feature."""
        accepted = apply_review(candidate, _req("accept"))
        assert accepted.origin == "inferred"
        assert accepted.source_status == "unknown"

    def test_acceptance_records_the_actor_and_bumps_revision(self, candidate):
        accepted = apply_review(candidate, _req("accept"))
        assert accepted.revision == 2
        assert len(accepted.review_history) == 1
        event = accepted.review_history[0]
        assert event.actor == "human:maintainer" and event.action == "accept"
        assert event.revision == 2 and event.timestamp
        assert event.before_sha1 and event.after_sha1 and event.before_sha1 != event.after_sha1

    def test_stale_revision_is_rejected(self, candidate):
        """AC11: stale revisions are refused, with no automatic retry."""
        with pytest.raises(DecisionError) as exc:
            apply_review(candidate, ReviewRequest(decision_id="adr:candidate:abc", expected_revision=9,
                                                  action="accept", actor="a"))
        assert exc.value.code == "ADR_REVISION_CONFLICT"

    def test_observations_and_hypotheses_stay_separate(self, candidate):
        """AC4 survives review."""
        accepted = apply_review(candidate, _req("accept"))
        assert accepted.observations == candidate.observations
        assert accepted.hypotheses == candidate.hypotheses


class TestOtherActions:
    def test_reject_keeps_the_record(self, candidate):
        """spec §2: rejection does not delete."""
        rejected = apply_review(candidate, _req("reject"))
        assert rejected.review_status == "rejected"
        assert rejected.decision == candidate.decision

    def test_revise_resets_review_status(self, candidate):
        edit = CandidateEdit(decision="Retries use jittered exponential backoff.")
        revised = apply_review(candidate, _req("revise", replacement=edit))
        assert revised.decision == "Retries use jittered exponential backoff."
        assert revised.review_status == "unreviewed"

    def test_revise_preserves_evidence_and_generation(self, candidate):
        # FILL IN: assert evidence and generation are byte-identical after a revise
        raise NotImplementedError

    def test_link_records_an_asserted_association(self, candidate):
        # FILL IN: apply a 'link' to "adr:doc:xyz"; assert a DecisionLink with
        # provenance='asserted' was appended and origin is still 'inferred'
        raise NotImplementedError

    def test_link_to_a_missing_or_inferred_target_is_invalid(self, candidate):
        with pytest.raises(DecisionError) as exc:
            validate_link_target(None, "adr:doc:xyz")
        assert exc.value.code == "ADR_INVALID_ARGUMENT"
        # FILL IN: also assert an inferred target is rejected
        raise NotImplementedError


class TestImmutabilityAndHistory:
    @pytest.mark.parametrize("action", ["accept", "reject"])
    def test_immutable_fields_never_change(self, candidate, action):
        result = apply_review(candidate, _req(action))
        for field in ("decision_id", "origin", "source_status", "evidence", "generation"):
            assert getattr(result, field) == getattr(candidate, field)

    def test_history_is_append_only(self, candidate):
        """AC6: a later review can never erase an earlier one."""
        first = apply_review(candidate, _req("accept"))
        second = apply_review(first, ReviewRequest(decision_id="adr:candidate:abc", expected_revision=2,
                                                   action="reject", actor="human:other", reason="changed my mind"))
        assert [e.action for e in second.review_history] == ["accept", "reject"]
        assert second.review_history[0] == first.review_history[0]

    def test_input_record_is_not_mutated(self, candidate):
        """A caller must be able to retry from the record it read."""
        apply_review(candidate, _req("accept"))
        assert candidate.revision == 1 and candidate.review_history == []

    def test_candidate_edit_cannot_reach_immutable_fields(self):
        """spec §2: CandidateEdit has exactly six fields."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CandidateEdit(origin="documented")


class TestExport:
    def test_export_keeps_the_inferred_label(self, candidate):
        """An exported candidate is still unmistakably a candidate (AC9)."""
        # FILL IN: assert "INFERRED" appears in render_export(candidate) and
        # that observations and hypotheses render as separate sections
        raise NotImplementedError
```

### FILL IN checklist

- [ ] `review.py::_apply_edit` — six editable fields + `unreviewed` reset; bounded by spec §2
- [ ] `review.py::_apply_link` — asserted link on a copied list; bounded by spec §2
- [ ] `review.py::apply_review` — dispatch, immutability assertion, event append; bounded by AC11 / AC6
- [ ] `review.py::validate_link_target` — missing/inferred rejection; bounded by spec §2
- [ ] `test_review.py` — six test bodies; bounded by the assertions named in each docstring

---

## Acceptance Criteria

- [ ] Acceptance succeeds with **no** documented ADR and no committed file (Q3, AC11)
- [ ] Acceptance sets `review_status='accepted'` and leaves `origin='inferred'`, `source_status='unknown'` (AC11)
- [ ] Every action appends exactly one attributed `ReviewEvent` and bumps `revision` by 1
- [ ] `before_sha1` / `after_sha1` bracket the change and exclude `review_history`
- [ ] A stale `expected_revision` raises `ADR_REVISION_CONFLICT` with no retry (AC11)
- [ ] `reject` keeps the record; nothing is ever deleted (spec §2)
- [ ] `revise` applies only `CandidateEdit`'s six fields, preserves evidence/provenance, resets to `unreviewed`
- [ ] `link` requires an existing **documented** record and leaves `origin='inferred'`
- [ ] Review history is append-only; earlier events are byte-identical afterwards (AC6)
- [ ] The input record is never mutated
- [ ] `render_export` keeps the `INFERRED` label and the observations/hypotheses split (AC9, AC4)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_review.py -q`

---

## Agent Instructions

1. **Read the spec** §2 "Candidate generation and attributed review", §8 Q3, and AC4/AC6/AC11.
2. **Verify the Codebase Contract** — confirm `review_fingerprint` and `CandidateEdit`'s field list from TASK-3479/3480.
3. **Implement** from the blueprint; complete every `# FILL IN:`.
4. **Verify** the Validation Command passes.
5. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
6. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (Fallback Sequential Loop —
`parrot-sdd-coder` MCP server unresponsive throughout this run)
**Date**: 2026-09-19
**Notes**: `apply_review` checks the revision precondition first (no
mutation is even built against a stale `expected_revision`), dispatches
the four actions into an `updates` dict, copies the record with the
bumped revision, then asserts every `IMMUTABLE_FIELDS` value is
byte-identical to the pre-transform record before appending one
`ReviewEvent` whose `before_sha1`/`after_sha1` bracket the change via
`review_fingerprint` (excludes `review_history`, so the audit hash never
depends on itself). `accept`/`reject` touch only `review_status`,
preserving `origin='inferred'`/`source_status='unknown'` forever — the
Q3/AC11 invariant. `revise` applies `CandidateEdit`'s six fields and
resets `review_status` to `'unreviewed'`. `link` appends an
`asserted`-provenance `DecisionLink` without touching `origin`.
`validate_link_target` is deliberately store-free and NOT called from
inside `apply_review` — this module never touches a store at all;
TASK-3493's service orchestration owns fetching the target record and
calling `validate_link_target` before invoking `apply_review`. Every
action returns a brand-new record via `model_copy`; the input is never
mutated, so a caller can retry from what it originally read after a
conflict. 16 tests covering the full AC11 acceptance matrix, reject/
revise/link semantics, immutability assertions, append-only history
(two sequential reviews), non-mutation of the input, `CandidateEdit`'s
closed six-field surface, and export rendering (`INFERRED` label +
separate Observations/Hypotheses sections).

**Deviations from spec**: none.
