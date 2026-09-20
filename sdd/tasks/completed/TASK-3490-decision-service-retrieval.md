# TASK-3490: `DecisionService` — `for_symbol` and `why` retrieval

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3485, TASK-3487, TASK-3488
**Assigned-to**: unassigned

---

## Context

Module 4 — the read surface every adapter wraps. Two entry points, both
returning a `DecisionDossier`, both making **zero** LLM calls (AC5).

The load-bearing rule of the whole feature lives here: *"Edges are a cache:
retrieval validates the corresponding record link, so stale projected edges
never establish applicability"* (spec §2). A hit is admissible only if the
**record's own `links`** justify it. A graph edge alone never does.

Q2 in spec §8 sets the delivery order inside this task: symbol lookup is the
evidence-link foundation, `why` builds on it. Both ship here.

---

## Scope

- Implement `DecisionService.__init__`, `for_symbol` and `why`.
- Define `sync`, `generate` and `review` as stubs raising `NotImplementedError`;
  TASK-3493 fills them in (same file, sequenced after this task).
- Implement the deterministic `why` score and the three-tier group ordering.
- Implement symbol disambiguation via `StructuralService.lookup`, file-scope
  inclusion, and the `ambiguous` / `empty` statuses.
- Attach freshness per hit and hide history unless `include_history=True`.
- Unit-test ranking stability, disambiguation, budget interaction and the
  zero-LLM guarantee.

**NOT in scope**: the `sync`, `generate` and `review` bodies (TASK-3493), packing internals
(TASK-3488), CLI/tool adapters (TASK-3494 / TASK-3496).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py` | CREATE | `DecisionService` with `for_symbol` + `why` (generate/review stubbed) |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_service_retrieval.py` | CREATE | Disambiguation, ranking, freshness, zero-LLM |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.clients import AbstractClient                                  # clients/__init__.py:14
from parrot.knowledge.wiki.store import BaseWikiStore                      # store.py:525
from parrot.knowledge.wiki.structural.service import StructuralService     # structural/service.py:117
from parrot.knowledge.wiki.symbols import parse_sym_id, sym_concept_id     # symbols.py:159, :141
from parrot.knowledge.wiki.decisions.evidence import verify_freshness      # TASK-3487
from parrot.knowledge.wiki.decisions.models import (                       # TASK-3479
    ADR_INVALID_ARGUMENT, DecisionConfig, DecisionDiagnostic, DecisionDossier,
    DecisionError, DecisionHit, DecisionRecord, GenerationResult, ReviewRequest, SyncResult,
)
from parrot.knowledge.wiki.decisions.render import clamp_budget, clamp_limit, pack_dossier  # TASK-3488
from parrot.knowledge.wiki.decisions.repository import DecisionRepository  # TASK-3485
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:117
class StructuralService:
    def __init__(self, store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> None: ...  # line 127
    async def lookup(self, query: str, *, kind: SymbolKind | None = None, language: str | None = None,
                     path_prefix: str | None = None, limit: int = 20) -> SymbolLookupOutput: ...  # line 136
#   Returns SymbolLookupOutput(hits=[SymbolHit], total=int, repaired_files=[...]).
#   SymbolHit carries `symbol_id`, `rel_path`, `kind`, `start_line`, `end_line`,
#   `doc`, and `stale` (set when the read-repair lock was busy, service.py:~163).

# packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py:141,:159
def sym_concept_id(rel_path: str, qualname: str, ordinal: int = 1) -> str: ...
def parse_sym_id(concept_id: str) -> tuple[str, str, int]: ...
```

`StructuralService.__init__` takes `root: Path` (**not** optional) and a
`WikiProjectConfig`. `DecisionService` therefore accepts an already-built
`StructuralService` by injection — spec §2 Module 4: "inject the structural
service to avoid new cycles".

### Does NOT Exist

- ~~`WikiCombinedSearch.search` as the query entry point~~ — spec §6: the CLI
  `query` calls `search_fts` directly (`cli.py:1846`) as does `WikiQueryTool._execute`
  (`tools.py:225`). `why` implements its own deterministic scoring; do not route
  it through the generic search.
- ~~`store.neighbors` as proof of applicability~~ — edges are a rebuildable
  cache (spec §2). Every hit must be justified by the record's own `links`.
- ~~call-graph propagation~~ — spec §2: "do not propagate applicability through
  the call graph".
- ~~a namespace `'all'` read for ADR~~ — spec §2 Module 6: `all` is rejected
  with `ADR_INVALID_ARGUMENT` in v1.
- ~~`DecisionService` constructing an `AbstractClient`~~ — the client is injected
  and is `None` for every read path. Constructing one would break AC5.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_service_retrieval.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py#StructuralService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py#sym_concept_id",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py#parse_sym_id",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository"
  ]
}
```

---

## Implementation Notes

### The `why` score (spec §2, verbatim)

> Sum distinct token overlaps weighted 4/3/1/1 against **title, decision,
> context, observations** respectively, then explicit matching symbol-link
> presence, then decision ID as stable tie-breaker.

"Distinct" means each query token counts at most once per field. The decision ID
tie-breaker makes the ordering total, so the ranking is reproducible.

### Group ordering (spec §2)

1. documented **and** `current` **and** source-accepted
2. other `current` documented records
3. candidate groups

Relevance ordering applies *within* each group, never across them.

### Visibility

Rejected / deprecated / superseded records and locally rejected candidates are
hidden unless `include_history=True`. Unknown status is **displayed**, never
elevated to accepted (AC3).

---

## Implementation Blueprint

### Steps (in order)

1. Write `_hit_from_record` including freshness — *why*: both entry points build
   hits the same way, and the label set is exactly what AC3/AC9 police.
2. Write `for_symbol` — *why*: Q2 makes it the evidence-link foundation, and
   `why`'s symbol resolution reuses its ambiguity policy.
3. Write `_score` then `why` — *why*: the score is pure and testable on its own.
4. Stub `sync`/`generate`/`review` so the class is complete and importable —
   *why*: TASK-3494's tools bind the service before TASK-3493 lands, and keeping
   `ingest` out of this module entirely means retrieval can be built and tested
   before the sync pipeline exists.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py` (CREATE)

```python
"""Decision retrieval service (FEAT-578 Module 4).

Zero LLM calls on every path in this file (AC5). ``generate`` and ``review``
are declared here for a complete public surface and implemented by the
generation/review task.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from parrot.clients import AbstractClient
from parrot.knowledge.wiki.decisions.evidence import verify_freshness
from parrot.knowledge.wiki.decisions.models import (
    ADR_INVALID_ARGUMENT,
    DecisionConfig,
    DecisionDiagnostic,
    DecisionDossier,
    DecisionError,
    DecisionHit,
    DecisionRecord,
    GenerationResult,
    ReviewRequest,
    SyncResult,
)
from parrot.knowledge.wiki.decisions.render import clamp_budget, clamp_limit, pack_dossier
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.structural.service import StructuralService

#: Lifecycle values hidden unless ``include_history=True`` (spec §2).
HISTORICAL_STATUSES = frozenset({"rejected", "deprecated", "superseded"})

#: Field weights for the ``why`` score (spec §2), highest first.
FIELD_WEIGHTS = (("title", 4), ("decision", 3), ("context", 1), ("observations", 1))

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def tokenize_query(text: str) -> set[str]:
    """Lowercase alphanumeric tokens, deduplicated."""
    return {t.lower() for t in _TOKEN_RE.findall(text)}


class DecisionService:
    """Cited decision retrieval over one namespace's ADR plane."""

    def __init__(
        self,
        store: BaseWikiStore,
        root: Path | None,
        config: DecisionConfig,
        structural: StructuralService | None = None,
        client: AbstractClient | None = None,
    ) -> None:
        """Bind one namespace, optional local evidence root, optional client.

        Args:
            root: Local project root, or ``None`` for a store-only/remote
                namespace. ``None`` makes every freshness answer
                ``unverified`` and forbids generation (spec §2 Module 6).
            structural: Injected to avoid a service->service import cycle
                (spec §2 Module 4). ``None`` disables name-based symbol
                disambiguation; exact ``sym:`` ids still work.
            client: Present ONLY for explicit generation. Never constructed
                here — a read path that could build a client would break AC5.
        """
        self._store = store
        self._root = root
        self._config = config
        self._structural = structural
        self._client = client
        self._repo = DecisionRepository(store, max_records=config.max_records)
        self.logger = logging.getLogger(__name__)

    async def _hit_from_record(self, record: DecisionRecord, score: float) -> DecisionHit:
        """Build a labeled hit, verifying evidence freshness.

        Freshness is the WORST outcome across the record's evidence: one
        stale span makes the hit stale, because a decision cited against
        changed code is not verified (spec §2).
        """
        # FILL IN: call verify_freshness(self._root, ref) for each evidence ref,
        # reduce with precedence missing > stale > unverified > current, and
        # populate every DecisionHit label field plus applicability (the
        # record's own links) and citations. Bounded by spec §2 "Verify evidence
        # hashes against current on-disk bytes" and AC3.
        raise NotImplementedError

    def _visible(self, record: DecisionRecord, include_history: bool) -> bool:
        """Whether ``record`` is shown by default."""
        if include_history:
            return True
        # FILL IN: hide source_status in HISTORICAL_STATUSES, and hide
        # origin='inferred' records whose review_status == 'rejected'. 'unknown'
        # is VISIBLE — spec §2 "Unknown status is displayed, not elevated".
        raise NotImplementedError

    async def _resolve_symbol(self, symbol: str) -> tuple[str | None, list[str]]:
        """Resolve ``symbol`` to one exact ``sym:`` id.

        Returns:
            ``(symbol_id, alternatives)``. A bare name resolving to several
            symbols returns ``(None, [ids])`` so the caller can answer
            ``ambiguous`` — spec §2 forbids guessing a binding.
        """
        if symbol.startswith("sym:"):
            return symbol, []
        if self._structural is None:
            return None, []
        # FILL IN: await self._structural.lookup(symbol, limit=...) and keep
        # only hits whose exact name OR qualname equals `symbol`; exactly one
        # match -> (that symbol_id, []); several -> (None, sorted ids); none ->
        # (None, []). Bounded by spec §2 "require one exact name/qualname match"
        # and AC2.
        raise NotImplementedError

    async def for_symbol(
        self,
        symbol: str,
        *,
        include_history: bool = False,
        limit: int = 10,
        budget_tokens: int = 3000,
    ) -> DecisionDossier:
        """Return cited decisions applicable to one symbol.

        Includes links that name this exact symbol AND file-scope links for
        its file, labeled separately. Applicability is never propagated
        through the call graph (spec §2, AC2).

        Returns:
            A dossier with ``status='ambiguous'`` (plus ``alternatives``)
            when a bare name matches several symbols, ``'empty'`` when
            nothing matches, ``'ok'`` otherwise.
        """
        # FILL IN: resolve the symbol; on ambiguity return an 'ambiguous'
        # dossier carrying the alternatives; load the inventory; keep a record
        # only when one of ITS OWN links targets the symbol id or its
        # `file:<rel>` id (never a graph edge); split documented vs inferred;
        # build hits with score 0.0 (symbol lookup is not ranked by relevance);
        # pack with pack_dossier. Bounded by spec §2 "retrieval validates the
        # corresponding record link" and AC2.
        raise NotImplementedError

    def _score(self, record: DecisionRecord, tokens: set[str], symbol_ids: set[str]) -> float:
        """Deterministic relevance score (spec §2).

        Distinct token overlap weighted 4/3/1/1 over title / decision /
        context / observations, then a bonus for an explicit matching
        symbol link. The caller breaks remaining ties on ``decision_id`` so
        the ordering is total and reproducible.
        """
        # FILL IN: for each (field, weight) in FIELD_WEIGHTS, add
        # weight * len(tokens & tokenize_query(<that field's text>)); add the
        # symbol-link bonus when any of record.links targets an id in
        # symbol_ids. Bounded by spec §2's scoring sentence.
        raise NotImplementedError

    async def why(
        self,
        question: str,
        *,
        include_history: bool = False,
        limit: int = 10,
        budget_tokens: int = 3000,
    ) -> DecisionDossier:
        """Return ranked decision excerpts with citations and labeled candidates.

        A natural-language question need not name a symbol. When it does,
        the same ambiguity policy as :meth:`for_symbol` applies.
        """
        # FILL IN: tokenize; opportunistically resolve any symbol-looking token
        # (reusing _resolve_symbol, tolerating no match); load the inventory;
        # filter by _visible; score each record; order by the THREE GROUPS in
        # the Implementation Notes, with (-score, decision_id) inside each
        # group; split documented vs candidates; pack. Bounded by spec §2
        # "Rank documented/current/source-accepted hits first..." and AC3.
        raise NotImplementedError

    async def sync(self, paths: list[str] | None = None) -> SyncResult:
        """Refresh ADR sources. Implemented by the orchestration task."""
        raise NotImplementedError("DecisionService.sync is implemented in FEAT-578 Module 5")

    async def generate(self, target: str) -> GenerationResult:
        """Generate bounded candidates. Implemented by the generation task."""
        raise NotImplementedError("DecisionService.generate is implemented in FEAT-578 Module 5")

    async def review(self, request: ReviewRequest) -> DecisionRecord:
        """Apply an attributed review. Implemented by the review task."""
        raise NotImplementedError("DecisionService.review is implemented in FEAT-578 Module 5")
```

**Why this shape**: `client` being injectable-but-never-constructed is the
mechanical guarantee behind AC5 — there is no code path in this file that can
reach a provider. `_hit_from_record` reducing freshness to the worst span stops
a decision from being labeled `current` when only one of its three citations
still matches. Filtering on `record.links` rather than `store.neighbors` is the
spec's edges-are-a-cache rule made executable; swapping in a neighbor query
would pass most tests and silently break AC2. The `sync` import is function-local
to keep `ingest` (which imports the repository and parser) out of this module's
import cycle.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_service_retrieval.py` (CREATE)

```python
"""for_symbol / why retrieval semantics (FEAT-578 Module 4, AC2/AC3/AC5)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.models import DecisionConfig, DecisionLink, DecisionRecord, EvidenceRef
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.decisions.service import DecisionService, tokenize_query


def _record(decision_id, *, origin="documented", links=(), **kw) -> DecisionRecord:
    return DecisionRecord(
        decision_id=decision_id,
        decision=kw.pop("decision", "use pgvector for the primary store"),
        origin=origin,
        source_status=kw.pop("source_status", "accepted" if origin == "documented" else "unknown"),
        links=list(links),
        **kw,
    )


@pytest.fixture
async def service(adr_store, tmp_path):
    """A service over a seeded plane, with no client and no structural service."""
    return DecisionService(adr_store, tmp_path, DecisionConfig(), structural=None, client=None)


class TestForSymbol:
    async def test_exact_symbol_id_returns_linked_records(self, service, adr_store):
        # FILL IN: save a record linking sym:a.py#f; assert for_symbol returns
        # it with status 'ok'
        raise NotImplementedError

    async def test_file_scope_links_are_included_and_labeled(self, service, adr_store):
        """Module-level citations apply at file scope, labeled separately (spec §2)."""
        # FILL IN: save a record linking file:a.py; assert for_symbol("sym:a.py#f")
        # includes it and that its applicability link target is the file id
        raise NotImplementedError

    async def test_duplicate_names_are_ambiguous(self, adr_store, tmp_path):
        """AC2: a bare name matching two symbols never guesses."""
        # FILL IN: build a DecisionService with a stub structural service whose
        # lookup returns two exact-name hits; assert status == "ambiguous" and
        # both ids appear in `alternatives`
        raise NotImplementedError

    async def test_no_match_is_empty(self, service):
        dossier = await service.for_symbol("sym:nope.py#gone")
        assert dossier.status == "empty" and not dossier.documented and not dossier.candidates

    async def test_no_call_graph_inheritance(self, service, adr_store):
        """spec §2: applicability does not propagate through callers."""
        # FILL IN: link a record to sym:a.py#callee only; assert for_symbol on
        # sym:a.py#caller returns empty even with a calls edge present
        raise NotImplementedError

    async def test_a_graph_edge_alone_never_establishes_applicability(self, service, adr_store):
        """The edges-are-a-cache rule (spec §2) — the core retrieval guarantee."""
        # FILL IN: save a record with NO links, then add_edges a stale
        # (decision_id, sym:a.py#f, "explains") edge directly; assert for_symbol
        # returns empty
        raise NotImplementedError


class TestWhyRanking:
    def test_score_weights_fields_4_3_1_1(self, service):
        """The weighting is spec text, not a tuning knob."""
        tokens = tokenize_query("pgvector")
        title_hit = _record("adr:doc:t", title="pgvector", decision="x", context="", observations=[])
        decision_hit = _record("adr:doc:d", title="x", decision="pgvector", observations=[])
        assert service._score(title_hit, tokens, set()) > service._score(decision_hit, tokens, set())

    def test_distinct_tokens_count_once_per_field(self, service):
        # FILL IN: a record repeating the same token five times in `decision`
        # scores the same as one repeating it once
        raise NotImplementedError

    async def test_documented_current_accepted_ranks_first(self, service, adr_store):
        """The three-tier group order (spec §2)."""
        # FILL IN: seed an accepted+current documented record with a LOW token
        # score and an unknown-status one with a HIGH score; assert the
        # accepted one still comes first
        raise NotImplementedError

    async def test_candidates_never_enter_the_documented_group(self, service, adr_store):
        """AC3."""
        # FILL IN: seed one documented and one inferred record; assert the
        # inferred one appears only in dossier.candidates
        raise NotImplementedError

    async def test_decision_id_breaks_ties_stably(self, service, adr_store):
        # FILL IN: two records with identical scores; assert the order is by
        # decision_id and is identical across two calls
        raise NotImplementedError

    async def test_history_is_hidden_by_default(self, service, adr_store):
        # FILL IN: seed a superseded record; assert it is absent by default and
        # present with include_history=True
        raise NotImplementedError

    async def test_unknown_status_is_displayed_not_elevated(self, service, adr_store):
        """AC3: unknown shows up, labeled unknown — never as accepted."""
        # FILL IN
        raise NotImplementedError

    async def test_budget_is_respected(self, service, adr_store):
        # FILL IN: seed several long records; call with budget_tokens=256;
        # assert truncated is True and every returned hit still carries labels
        raise NotImplementedError


class TestOffline:
    async def test_lookup_and_why_make_zero_llm_calls(self, service, adr_store, monkeypatch):
        """AC5: no client is constructed or invoked on any read path."""
        # FILL IN: monkeypatch LLMFactory.create and AbstractClient.invoke to
        # raise AssertionError; run for_symbol and why; assert both complete
        raise NotImplementedError

    @pytest.mark.parametrize("method,args", [("sync", ()), ("generate", ("sym:a.py#f",))])
    async def test_orchestration_methods_are_declared_but_unimplemented(self, service, method, args):
        """The surface is complete before Module 5 lands."""
        with pytest.raises(NotImplementedError):
            await getattr(service, method)(*args)
```

### FILL IN checklist

- [ ] `service.py::_hit_from_record` — worst-of freshness + full label set; bounded by spec §2 / AC3
- [ ] `service.py::_visible` — historical hiding, `unknown` stays visible; bounded by AC3
- [ ] `service.py::_resolve_symbol` — exact-match-only disambiguation; bounded by AC2
- [ ] `service.py::for_symbol` — record-link validation, file scope, statuses; bounded by spec §2 / AC2
- [ ] `service.py::_score` — 4/3/1/1 + symbol-link bonus; bounded by spec §2
- [ ] `service.py::why` — three-tier grouping + stable tie-break; bounded by spec §2 / AC3
- [ ] `test_service_retrieval.py` — fourteen test bodies

---

## Acceptance Criteria

- [ ] A hit is admitted only when the **record's own `links`** justify it; a stale graph edge alone never does (spec §2)
- [ ] Exact `sym:` ids work with no structural service; a bare name needs exactly one exact name/qualname match (AC2)
- [ ] Several matches → `status='ambiguous'` with ids in `alternatives`; none → `'empty'`
- [ ] File-scope links for the symbol's file are included and labeled separately (AC2)
- [ ] Applicability is never propagated through the call graph
- [ ] `why` scores distinct token overlap 4/3/1/1 over title/decision/context/observations, then symbol-link presence, then `decision_id` (spec §2)
- [ ] Group order is documented+current+accepted → other current documented → candidates; relevance applies only within a group (AC3)
- [ ] Rejected/deprecated/superseded and locally rejected candidates hidden unless `include_history=True`; `unknown` is displayed (AC3)
- [ ] Every hit carries origin, source status, review status and freshness; `unverified` when `root is None`
- [ ] `for_symbol`, `why` and `sync` make zero LLM calls (AC5)
- [ ] `sync` / `generate` / `review` exist and raise `NotImplementedError` pending TASK-3493
- [ ] This module imports nothing from `decisions/ingest.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_service_retrieval.py -q`

---

## Agent Instructions

1. **Read the spec** §2 "Retrieval and freshness", Module 4, §8 Q2, and AC2/AC3/AC5.
2. **Verify the Codebase Contract** — confirm `structural/service.py:127`, `:136` and the `SymbolHit` fields.
3. **Implement** from the blueprint; complete every `# FILL IN:`.
4. **Verify** the Validation Command passes.
5. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
6. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (Fallback Sequential Loop —
`parrot-sdd-coder` MCP server unresponsive throughout this task)
**Date**: 2026-09-19
**Notes**: `_hit_from_record` reduces freshness to the worst outcome
across the record's evidence (`missing > stale > unverified > current`);
a record with zero evidence is vacuously `current` when a local root is
available (nothing on disk contradicts it), but `root is None` always
yields `unverified` regardless of evidence count, matching
`verify_freshness`'s own hard rule. `_resolve_symbol` uses
`SymbolHit.qualname` directly (exact or bare-name-suffix match) rather
than round-tripping through `parse_sym_id`, since `StructuralService.lookup`
already exposes `qualname` on every hit. `for_symbol` and `why` both admit
a record only via its OWN `links` (never `store.neighbors`/edges), matching
the "edges are a cache" guarantee. `why`'s score combines the spec's
4/3/1/1 weighted distinct-token-overlap sum with a small (0.5, below the
lowest field weight of 1) symbol-link bonus so it can only ever act as a
secondary tie-break, never override token-overlap ordering; `decision_id`
breaks remaining ties in the caller's sort key. 17 tests: all six
`for_symbol` cases (exact id, file-scope, ambiguous, empty, no-call-graph-
inheritance, edge-alone-never-applies), the 4/3/1/1 weighting and
distinct-token dedup, three-tier group ordering, candidates-never-in-
documented, stable tie-breaking, history hidden/shown, unknown displayed
not elevated, budget truncation, zero-LLM-calls, and both orchestration
stubs raising `NotImplementedError`.

**Deviations from spec**: none.
