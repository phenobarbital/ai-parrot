# TASK-3488: Dossier rendering and token-budget packing

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3479
**Assigned-to**: unassigned

---

## Context

Module 4's presentation half, split out from the service so the packing rule can
be tested in isolation. Spec §2 states the rule precisely and it is unusual:

> Pack a hit only with its origin/status/freshness and at least one citation; if
> an excerpt cannot fit, shorten the excerpt while retaining the citation, or
> omit that hit with `truncated=True`.

In other words a budget overrun may **never** produce a hit whose labels or
citation were dropped to save room. A half-labeled candidate is worse than no
hit at all, because it reads like a documented decision (AC9).

---

## Scope

- Implement `pack_dossier(...)` enforcing the limit and the token budget with
  the label-and-citation invariant above.
- Implement the text rendering of a dossier for CLI/tool output, keeping the
  documented and candidate groups visibly separate.
- Unit-test the budget edge cases, including "budget too small for any hit".

**NOT in scope**: ranking and scoring (TASK-3490), freshness computation
(TASK-3487), CLI wiring (TASK-3496).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/render.py` | CREATE | Budgeted packing + dossier text rendering |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_render.py` | CREATE | Budget, truncation and label-invariant tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.context import truncate_to_tokens          # context.py:273
from parrot.knowledge.wiki.store import estimate_tokens               # store.py:318
from parrot.knowledge.wiki.decisions.models import (                  # TASK-3479
    DecisionDiagnostic, DecisionDossier, DecisionHit,
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/context.py
DEFAULT_BUDGET_TOKENS = 1200                                          # line 115
def truncate_to_tokens(text: str, max_tokens: int | None) -> tuple[str, bool]: ...   # line 273
def stub_line(result: dict[str, Any]) -> str: ...                     # line 161
def pack_results(...) -> ...                                          # line 208

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:318
def estimate_tokens(text: str) -> int: ...

# packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py — rendering precedent
def _render_text(lines: list[str], model: BaseModel, budget_tokens: int) -> str: ...
```

### Does NOT Exist

- ~~`context.pack_results` as a drop-in for dossiers~~ — it packs generic wiki
  search rows (`context.py:208`), which have no origin/status/freshness labels
  and no citation invariant. Do not route dossiers through it.
- ~~a default budget of 1200 for dossiers~~ — `DEFAULT_BUDGET_TOKENS` is the
  generic wiki value. Spec §2 sets the ADR dossier default to **3000** with a
  **minimum of 256**, and `limit` to **10** in `1..50`.
- ~~a "documented and candidates merged by score" ordering~~ — spec §2 ranks in
  groups and AC3 requires the groups stay distinct.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/render.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_render.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/context.py#truncate_to_tokens",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#estimate_tokens"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- Pure and synchronous. No store, no I/O, no CLI imports.
- Budget bounds: `budget_tokens` minimum 256; `limit` in `1..50`, default 10.
- Packing order is documented-group-first, then candidates, so a tight budget
  drops candidates before documented decisions.
- Setting `truncated=True` is mandatory whenever any hit or excerpt was dropped.

---

## Implementation Blueprint

### Steps (in order)

1. Write `_minimum_hit`, the shortest legal rendering of a hit — *why*: the
   invariant is "labels + one citation always survive", so the packer needs to
   know that floor before it can decide to shorten or omit.
2. Write `pack_dossier` around that floor — *why*: shorten-then-omit is only
   correct if omission is the fallback, never label-stripping.
3. Write `render_dossier_text` — *why*: it consumes an already-packed dossier,
   so it cannot reintroduce an overrun.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/render.py` (CREATE)

```python
"""Budgeted dossier packing and rendering (FEAT-578 Module 4).

The packing invariant (spec §2): a hit is emitted only WITH its
origin/status/freshness labels and at least one citation. When the budget
cannot hold that minimum, the hit is omitted and ``truncated`` is set — the
labels are never dropped to make room, because an unlabeled candidate reads
like a documented decision (AC3, AC9).
"""

from __future__ import annotations

from parrot.knowledge.wiki.decisions.models import DecisionDiagnostic, DecisionDossier, DecisionHit
from parrot.knowledge.wiki.store import estimate_tokens

#: Spec §2 "Retrieval and freshness" — ADR dossier defaults and bounds.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 50
DEFAULT_BUDGET_TOKENS = 3000
MIN_BUDGET_TOKENS = 256


def clamp_limit(limit: int) -> int:
    """Clamp ``limit`` into ``1..50`` (spec §2)."""
    return max(MIN_LIMIT, min(MAX_LIMIT, limit))


def clamp_budget(budget_tokens: int) -> int:
    """Raise ``budget_tokens`` to the 256-token floor (spec §2)."""
    return max(MIN_BUDGET_TOKENS, budget_tokens)


def labels_of(hit: DecisionHit) -> str:
    """The mandatory label prefix, e.g. ``[INFERRED / UNREVIEWED / stale]``."""
    origin = "DOCUMENTED" if hit.origin == "documented" else "INFERRED"
    status = hit.source_status.upper() if hit.origin == "documented" else hit.review_status.upper()
    return f"[{origin} / {status} / {hit.freshness}]"


def _citation_line(hit: DecisionHit) -> str:
    """Render the first citation as ``rel_path:start-end``; '' when there is none."""
    if not hit.citations:
        return ""
    first = hit.citations[0]
    return f"{first.rel_path}:{first.start_line}-{first.end_line}"


def minimum_cost(hit: DecisionHit) -> int:
    """Token cost of the shortest LEGAL rendering of ``hit``.

    That floor is labels + decision id + one citation reference, with the
    excerpt fully elided. A hit that does not fit this is omitted, never
    emitted without its labels.
    """
    return estimate_tokens(f"{labels_of(hit)} {hit.decision_id} {_citation_line(hit)}")


def _shorten_hit(hit: DecisionHit, available_tokens: int) -> DecisionHit:
    """Return a copy whose excerpts are shortened to fit ``available_tokens``.

    The citation's ``rel_path``/line range is always retained; only
    ``excerpt`` text is cut (spec §2 "shorten the excerpt while retaining
    the citation").
    """
    # FILL IN: model_copy(deep=True), then trim hit.decision and each
    # citation.excerpt — longest first — until estimate_tokens of the rendered
    # hit fits. NEVER drop a citation entry itself, and never touch
    # origin/source_status/review_status/freshness. Bounded by spec §2's
    # packing rule and AC9.
    raise NotImplementedError


def pack_dossier(
    documented: list[DecisionHit],
    candidates: list[DecisionHit],
    *,
    limit: int = DEFAULT_LIMIT,
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    status: str = "ok",
    alternatives: list[str] | None = None,
    diagnostics: list[DecisionDiagnostic] | None = None,
) -> DecisionDossier:
    """Assemble a dossier within ``limit`` hits and ``budget_tokens``.

    Documented hits are packed before candidates, so a tight budget drops
    candidates first. ``truncated`` is set whenever any hit was omitted or
    any excerpt shortened.

    Args:
        documented: Already-ranked documented hits.
        candidates: Already-ranked inferred hits. Kept in their own group —
            never merged into ``documented`` (AC3).
        limit: Total hits across both groups, clamped to ``1..50``.
        budget_tokens: Estimated output budget, floored at 256.
    """
    # FILL IN: clamp limit/budget; walk documented then candidates, stopping at
    # `limit` total; for each hit compute its full cost, and
    #   - if it fits, take it as-is
    #   - elif minimum_cost(hit) fits the remainder, take _shorten_hit(...) and
    #     set truncated
    #   - else omit it and set truncated
    # Return a DecisionDossier with the two groups still separate, carrying
    # `status` unless hits were dropped from an otherwise-'ok' result, in which
    # case 'partial' is the honest status. Bounded by spec §2's packing rule,
    # AC3 and AC9.
    raise NotImplementedError


def render_dossier_text(dossier: DecisionDossier) -> str:
    """Human-readable rendering for CLI and tool text output.

    Emits two clearly separated sections. The candidate section is headed so
    that a reader cannot mistake it for documented history, even when the
    documented section is empty.
    """
    # FILL IN: "Documented decisions" and "Candidates (INFERRED — not accepted
    # history)" headings, one line per hit built from labels_of + decision_id +
    # title + citation line, then diagnostics, then a trailing note when
    # dossier.truncated. An empty group prints an explicit "(none)" rather than
    # being omitted, so absence is visible. Bounded by AC3 and AC9.
    raise NotImplementedError
```

**Why this shape**: `minimum_cost` exists as a named function because the whole
correctness argument is "compare the remaining budget against the legal floor,
not against the full cost". Splitting `_shorten_hit` out keeps the field it must
never touch (`origin`, the two statuses, `freshness`) visible in one place.
`pack_dossier` downgrading `ok` to `partial` when it drops hits is what stops a
budget-truncated answer from looking complete.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_render.py` (CREATE)

```python
"""Dossier budget packing invariants (FEAT-578 Module 4, AC3/AC9)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.models import DecisionHit, EvidenceRef
from parrot.knowledge.wiki.decisions.render import (
    clamp_budget,
    clamp_limit,
    labels_of,
    pack_dossier,
    render_dossier_text,
)


def _hit(decision_id: str, origin: str = "documented", excerpt: str = "short", **kw) -> DecisionHit:
    return DecisionHit(
        decision_id=decision_id,
        revision=1,
        title=kw.pop("title", "t"),
        origin=origin,
        source_status=kw.pop("source_status", "accepted" if origin == "documented" else "unknown"),
        review_status=kw.pop("review_status", "unreviewed"),
        freshness=kw.pop("freshness", "current"),
        decision=kw.pop("decision", "use the thing"),
        citations=[EvidenceRef(page_id="file:a.py", rel_path="a.py", start_line=1, end_line=2,
                               source_sha1="d", excerpt=excerpt, kind="code")],
        **kw,
    )


class TestBounds:
    @pytest.mark.parametrize("given,expected", [(0, 1), (10, 10), (999, 50)])
    def test_limit_is_clamped(self, given, expected):
        assert clamp_limit(given) == expected

    @pytest.mark.parametrize("given,expected", [(0, 256), (3000, 3000)])
    def test_budget_has_a_floor(self, given, expected):
        assert clamp_budget(given) == expected


class TestPacking:
    def test_groups_stay_separate(self):
        """AC3: a candidate is never merged into the documented group."""
        d = pack_dossier([_hit("adr:doc:a")], [_hit("adr:candidate:b", origin="inferred")])
        assert [h.decision_id for h in d.documented] == ["adr:doc:a"]
        assert [h.decision_id for h in d.candidates] == ["adr:candidate:b"]

    def test_limit_counts_across_both_groups(self):
        # FILL IN: 3 documented + 3 candidates with limit=4 yields 4 hits total,
        # documented filled first
        raise NotImplementedError

    def test_tight_budget_drops_candidates_before_documented(self):
        # FILL IN: a budget that fits only one hit keeps the documented one and
        # sets truncated
        raise NotImplementedError

    def test_long_excerpt_is_shortened_not_dropped(self):
        """spec §2: shorten the excerpt, retain the citation."""
        hit = _hit("adr:doc:a", excerpt="x " * 5000)
        d = pack_dossier([hit], [], budget_tokens=256)
        assert d.documented, "the hit must survive with a shortened excerpt"
        kept = d.documented[0]
        assert kept.citations and kept.citations[0].rel_path == "a.py"
        assert kept.citations[0].start_line == 1 and kept.citations[0].end_line == 2
        assert d.truncated is True

    def test_labels_never_stripped_to_fit(self):
        """AC9: a hit is omitted rather than emitted unlabeled."""
        # FILL IN: with the smallest possible budget, assert every returned hit
        # still has its origin/source_status/review_status/freshness intact,
        # and that anything that could not fit is simply absent
        raise NotImplementedError

    def test_dropping_hits_downgrades_status_to_partial(self):
        # FILL IN: assert status == "partial" when a hit was omitted from an
        # otherwise 'ok' result
        raise NotImplementedError

    def test_nothing_dropped_leaves_truncated_false(self):
        d = pack_dossier([_hit("adr:doc:a")], [])
        assert d.truncated is False and d.status == "ok"


class TestRendering:
    def test_labels_show_origin_status_and_freshness(self):
        assert labels_of(_hit("adr:doc:a")) == "[DOCUMENTED / ACCEPTED / current]"
        assert labels_of(_hit("adr:candidate:b", origin="inferred")) == "[INFERRED / UNREVIEWED / current]"

    def test_candidate_section_is_explicitly_headed(self):
        """A reader must never mistake candidates for history (AC3)."""
        text = render_dossier_text(pack_dossier([], [_hit("adr:candidate:b", origin="inferred")]))
        assert "INFERRED" in text
        # FILL IN: assert the candidate heading text appears and that the
        # documented section prints an explicit "(none)"
        raise NotImplementedError
```

### FILL IN checklist

- [ ] `render.py::_shorten_hit` — excerpt trimming that preserves citations and labels; bounded by spec §2 / AC9
- [ ] `render.py::pack_dossier` — fit / shorten / omit walk + `partial` downgrade; bounded by spec §2
- [ ] `render.py::render_dossier_text` — two headed sections + `(none)`; bounded by AC3
- [ ] `test_render.py` — six test bodies; bounded by the assertions named in each docstring

---

## Acceptance Criteria

- [ ] `limit` clamps to `1..50` (default 10); `budget_tokens` floors at 256 (default 3000)
- [ ] Documented and candidate groups are never merged (AC3)
- [ ] An over-long excerpt is shortened while its citation's path and line range survive (spec §2)
- [ ] A hit that cannot fit the labels+citation floor is omitted, never emitted unlabeled (AC9)
- [ ] Any omission or shortening sets `truncated=True` and downgrades `ok` → `partial`
- [ ] Rendering heads the candidate section explicitly and prints `(none)` for an empty group
- [ ] Module is pure — no store, no I/O, no CLI import

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_render.py -q`

---

## Agent Instructions

1. **Read the spec** §2 "Retrieval and freshness" (final paragraph) and AC3/AC9.
2. **Verify the Codebase Contract** — confirm `context.py:115`, `:273` and `store.py:318`.
3. **Implement** from the blueprint; complete every `# FILL IN:`.
4. **Verify** the Validation Command passes.
5. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
6. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-coder (native, backend=native, model=sonnet), orchestrated by sdd-worker
**Date**: 2026-09-19
**Notes**: Implemented `decisions/render.py` exactly per blueprint — `_shorten_hit` (trims
decision text and citation excerpts longest-first, never touches origin/status/freshness or
citation path/line range), `pack_dossier` (documented-first walk, fit/shorten/omit against
`minimum_cost`'s label+citation floor, `ok`→`partial` downgrade on any drop, AC9's
never-emit-unlabeled invariant enforced), `render_dossier_text` (two headed sections,
explicit `(none)` for an empty group per AC3). Module confirmed pure (no store/I-O/CLI import).
`pytest test_render.py`: 14 passed (all 6 blueprint FILL-IN test bodies completed, calibrated
against this environment's real tiktoken-backed `estimate_tokens`). Only depends on TASK-3479
(already merged) — no dependency on the blocked store-CAS chain.

**Deviations from spec**: none
