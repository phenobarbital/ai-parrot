# TASK-3493: `DecisionService.sync` / `.generate` / `.review` — orchestration

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3489, TASK-3490, TASK-3491, TASK-3492
**Assigned-to**: unassigned

---

## Context

Module 5's wiring: replaces the three `NotImplementedError` stubs TASK-3490 left
in `decisions/service.py` with the real orchestration. Nothing new is designed here
— generation bounds live in TASK-3491, review semantics in TASK-3492,
persistence in TASK-3485. This task connects them and owns the two behaviours
that only exist at the seam:

- **Candidate dedup (AC6).** *"Before invoking a model, reuse existing
  candidates for the same scope/input fingerprint"* and *"Reviewed candidates
  remain intact when evidence changes; new evidence creates new candidates."*
  A rerun must return the existing ids without invoking anything.
- **Evidence re-check before persistence.** If any source hash drifted between
  packet construction and the write, the request persists **nothing**
  (`ADR_EVIDENCE_CHANGED`).

---

## Scope

- Implement `generate(target)`: resolve target → gather evidence → dedup probe →
  invoke once → validate → re-check hashes → persist each surviving candidate
  through the repository.
- Implement `sync(paths)`: delegate to `refresh_decisions`, refusing a
  store-only namespace. Never invokes a model (AC5).
- Implement `review(request)`: read → `apply_review` → CAS save, surfacing
  `ADR_REVISION_CONFLICT` untouched.
- Enforce that generation requires a local writable root and never runs on a
  remote/store-only namespace.
- Test dedup, review preservation across reruns, and evidence drift.

**NOT in scope**: generation internals (TASK-3491), review transforms
(TASK-3492), retrieval (TASK-3490), CLI/MCP gating (TASK-3494 / TASK-3496).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py` | MODIFY | Replace the `sync` / `generate` / `review` stubs |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_service_generation.py` | CREATE | Dedup, drift, review round-trip |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Add to the existing imports in `service.py`:

```python
from parrot.knowledge.wiki.decisions.codec import candidate_decision_id, content_fingerprint  # TASK-3480
from parrot.knowledge.wiki.decisions.generation import (                                      # TASK-3491
    PROMPT_VERSION, generate_candidates, recheck_evidence, resolve_client,
)
from parrot.knowledge.wiki.decisions.ingest import refresh_decisions                          # TASK-3489
from parrot.knowledge.wiki.decisions.review import apply_review, validate_link_target         # TASK-3492
from parrot.knowledge.wiki.decisions.models import GenerationInfo                             # TASK-3479
```

### Existing Signatures to Use

```python
# decisions/generation.py  (TASK-3491)
PROMPT_VERSION: int = 1
def resolve_client(config: DecisionConfig, client: AbstractClient | None) -> AbstractClient: ...
async def generate_candidates(client, target, evidence, config
    ) -> tuple[CandidateBatch, list[EvidenceRef], list[DecisionDiagnostic]]: ...
async def recheck_evidence(root, packet: list[EvidenceRef]) -> list[DecisionDiagnostic]: ...

# decisions/ingest.py  (TASK-3489)
async def refresh_decisions(store: BaseWikiStore, root: Path, config: DecisionConfig,
                            paths: list[str] | None = None) -> SyncResult: ...

# decisions/review.py  (TASK-3492)
def apply_review(record: DecisionRecord, request: ReviewRequest) -> DecisionRecord: ...
def validate_link_target(target: DecisionRecord | None, target_id: str) -> None: ...

# decisions/codec.py  (TASK-3480)
def candidate_decision_id(scope_id, evidence_fingerprint, prompt_version, decision_text) -> str: ...

# decisions/repository.py  (TASK-3485)
async def get(self, decision_id) -> tuple[DecisionRecord, str | None] | None: ...
async def save(self, record, expected_content_hash) -> DecisionRecord: ...

# decisions/service.py  (TASK-3490) — the stubs being replaced
async def sync(self, paths: list[str] | None = None) -> SyncResult: ...
async def generate(self, target: str) -> GenerationResult: ...
async def review(self, request: ReviewRequest) -> DecisionRecord: ...
```

### Does NOT Exist

- ~~a `--force` regeneration flag~~ — spec §2: "`--force` is not part of v1."
  A rerun always reuses.
- ~~overwriting an existing candidate record~~ — a matching fingerprint returns
  the existing id; changed evidence mints a **new** id (AC6). Never CAS over a
  reviewed candidate.
- ~~generating against a remote namespace~~ — spec §2 Module 6: "A selected
  remote/store-only namespace ... cannot generate or sync local code."
  `self._root is None` must refuse.
- ~~a service-level retry after `ADR_REVISION_CONFLICT`~~ — spec §2: the
  conflict surfaces to the maintainer.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_service_generation.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py#DecisionService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)

1. Compute the evidence fingerprint and probe for existing candidates **before**
   resolving the client — *why*: AC6 says a rerun reuses, and resolving a client
   first would fail an offline rerun that should have succeeded for free.
2. Invoke, then re-check hashes, then persist — *why*: the re-check is only
   meaningful after the (slow) model call, which is when drift happens.
3. Wire `review` last — *why*: it is a three-line orchestration once TASK-3492
   exists.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '        raise NotImplementedError("DecisionService.generate is implemented in FEAT-578 Module 5")' packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py)
# REPLACE — the three stub methods written by TASK-3490, whose bodies are
# `raise NotImplementedError("DecisionService.generate is implemented in FEAT-578 Module 5")`
# and `raise NotImplementedError("DecisionService.review is implemented in FEAT-578 Module 5")`:

    async def _target_evidence(self, target: str) -> tuple[str, list[EvidenceRef]]:
        """Resolve one symbol id or repository-relative file into evidence.

        Returns:
            ``(scope_id, evidence)``. ``scope_id`` is the stable identity the
            candidate id is derived from, so it must be the RESOLVED id, not
            the user's possibly-ambiguous input.

        Raises:
            DecisionError: ``ADR_INVALID_ARGUMENT`` for an unresolvable or
                ambiguous target — generation never guesses a binding, for
                the same reason retrieval does not (AC2).
        """
        # FILL IN: for a "sym:" target use parse_sym_id to get its rel_path and
        # build evidence over the symbol's span; for a bare relative path build
        # evidence over the whole file; for a bare NAME reuse _resolve_symbol
        # and refuse on ambiguity. Read the COMPLETE file (asyncio.to_thread)
        # and use evidence.build_evidence. Bounded by spec §2 "Targets are one
        # symbol ID or one repository-relative file".
        raise NotImplementedError

    async def sync(self, paths: list[str] | None = None) -> SyncResult:
        """Refresh ADR sources. Never invokes a model (AC5).

        The import is function-local so that building or testing the retrieval
        surface never drags in the ingest pipeline (TASK-3490 keeps this module
        free of it by design).

        Raises:
            DecisionError: ``ADR_INVALID_ARGUMENT`` without a local root — a
                store-only namespace has no source tree to scan (spec §2
                Module 6).
        """
        from parrot.knowledge.wiki.decisions.ingest import refresh_decisions

        if self._root is None:
            raise DecisionError(ADR_INVALID_ARGUMENT, "sync requires a local project root")
        return await refresh_decisions(self._store, self._root, self._config, paths)

    async def generate(self, target: str) -> GenerationResult:
        """Generate bounded candidates, or reuse the same snapshot's candidates.

        Reuse is checked BEFORE the model is resolved or invoked, so a rerun
        over unchanged evidence costs nothing and cannot disturb a candidate
        a maintainer has already reviewed (AC6).

        Raises:
            DecisionError: ``ADR_INVALID_ARGUMENT`` without a local root,
                ``ADR_MODEL_UNCONFIGURED`` when generation is off or no model
                is configured, plus any code raised by the generation module.
        """
        if self._root is None:
            raise DecisionError(
                ADR_INVALID_ARGUMENT,
                "candidate generation requires a local project root; a store-only namespace cannot generate",
            )
        result = GenerationResult()
        scope_id, evidence = await self._target_evidence(target)
        # FILL IN:
        #   1. fingerprint the sorted evidence (same canonical ordering
        #      content_fingerprint uses, so ids are reproducible)
        #   2. inventory = await self._repo.inventory(); collect every record
        #      whose generation.scope_id == scope_id AND
        #      generation.input_sha1 == fingerprint -> result.reused = their
        #      ids; if any, RETURN NOW without resolving a client (AC6)
        #   3. client = resolve_client(self._config, self._client)
        #   4. batch, packet, diags = await generate_candidates(...)
        #   5. drift = await recheck_evidence(self._root, packet); if drift is
        #      non-empty, return a GenerationResult carrying those diagnostics
        #      and NO decision_ids — write nothing (spec §2)
        #   6. for each surviving draft: map its evidence_indexes onto packet
        #      entries, mint decision_id = candidate_decision_id(scope_id,
        #      fingerprint, PROMPT_VERSION, draft.decision), build a
        #      DecisionRecord with origin='inferred', source_status='unknown',
        #      review_status='unreviewed', generation=GenerationInfo(...), and
        #      save it with expected_content_hash=None; an
        #      ADR_REVISION_CONFLICT here means an identical candidate already
        #      exists -> record it in `reused`, not as an error
        # Bounded by AC4, AC5, AC6 and spec §2's generation paragraph.
        raise NotImplementedError

    async def review(self, request: ReviewRequest) -> DecisionRecord:
        """Validate and apply an attributed revision.

        Raises:
            DecisionError: ``ADR_INVALID_ARGUMENT`` when the record or a
                ``link`` target is missing, ``ADR_REVISION_CONFLICT`` when
                another reviewer wrote first. The conflict is surfaced, never
                retried (spec §2).
        """
        loaded = await self._repo.get(request.decision_id)
        if loaded is None:
            raise DecisionError(
                ADR_INVALID_ARGUMENT, f"no such decision: {request.decision_id}", decision_id=request.decision_id
            )
        record, page_hash = loaded
        # FILL IN: for action == 'link', load request.documented_decision_id and
        # pass it through validate_link_target BEFORE applying; then
        # updated = apply_review(record, request) and
        # return await self._repo.save(updated, page_hash).
        # Bounded by spec §2 "Linking requires an existing documented ADR
        # record" and AC11's revision-checked attribution.
        raise NotImplementedError
```

**Why**: the dedup probe running before `resolve_client` is the difference
between "a rerun is free" and "a rerun fails when the model env is unset" —
AC6 describes the former. Treating an `ADR_REVISION_CONFLICT` on a candidate
insert as *reuse* rather than an error closes the race where two generate calls
mint the same deterministic id concurrently: the id is a pure function of the
evidence, so the loser's record is byte-equivalent to the winner's.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_service_generation.py` (CREATE)

```python
"""generate/review orchestration: dedup, drift, persistence (FEAT-578 M5)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.models import (
    CandidateBatch,
    CandidateDraft,
    DecisionConfig,
    DecisionError,
    ReviewRequest,
)
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.decisions.service import DecisionService


class CountingClient:
    """Fake AbstractClient that records how many times it was invoked."""

    def __init__(self, decision: str = "Retries use backoff."):
        self.decision = decision
        self.calls = 0

    async def invoke(self, prompt, **kwargs):
        self.calls += 1
        batch = CandidateBatch(candidates=[CandidateDraft(decision=self.decision, evidence_indexes=[0])])
        return type("InvokeResult", (), {"output": batch, "model": "fake", "usage": {}})()


@pytest.fixture
def gen_config() -> DecisionConfig:
    return DecisionConfig(generation_enabled=True)


@pytest.fixture
def source_file(tmp_path):
    """One small Python file with no documented rationale."""
    path = tmp_path / "svc.py"
    path.write_text("def fetch():\n    for n in range(3):\n        sleep(2 ** n)\n")
    return path


class TestGenerationGates:
    async def test_remote_namespace_cannot_generate(self, adr_store, gen_config):
        """spec §2 Module 6: a store-only namespace has no local code."""
        service = DecisionService(adr_store, None, gen_config, client=CountingClient())
        with pytest.raises(DecisionError) as exc:
            await service.generate("sym:svc.py#fetch")
        assert exc.value.code == "ADR_INVALID_ARGUMENT"

    async def test_disabled_generation_never_invokes(self, adr_store, tmp_path, source_file):
        client = CountingClient()
        service = DecisionService(adr_store, tmp_path, DecisionConfig(), client=client)
        with pytest.raises(DecisionError) as exc:
            await service.generate("svc.py")
        assert exc.value.code == "ADR_MODEL_UNCONFIGURED"
        assert client.calls == 0

    async def test_ambiguous_target_is_refused(self, adr_store, tmp_path, gen_config):
        # FILL IN: a bare name matching two symbols raises ADR_INVALID_ARGUMENT
        # and invokes nothing
        raise NotImplementedError


class TestGenerationPersistence:
    async def test_candidate_is_persisted_as_inferred(self, adr_store, tmp_path, source_file, gen_config):
        """AC4: generated records stay inferred with unknown source status."""
        service = DecisionService(adr_store, tmp_path, gen_config, client=CountingClient())
        result = await service.generate("svc.py")
        assert result.decision_ids
        record, _ = await DecisionRepository(adr_store).get(result.decision_ids[0])
        assert record.origin == "inferred"
        assert record.source_status == "unknown"
        assert record.review_status == "unreviewed"
        assert record.generation is not None and record.generation.scope_id

    async def test_observations_and_hypotheses_are_stored_separately(self, adr_store, tmp_path, source_file, gen_config):
        # FILL IN: assert the persisted record keeps the draft's observations
        # and hypotheses in their own fields (AC4)
        raise NotImplementedError

    async def test_only_supplied_evidence_is_cited(self, adr_store, tmp_path, source_file, gen_config):
        # FILL IN: assert every EvidenceRef on the stored record appears in the
        # packet — no invented paths (AC4)
        raise NotImplementedError


class TestDedup:
    async def test_rerun_reuses_without_invoking(self, adr_store, tmp_path, source_file, gen_config):
        """AC6: same evidence returns the existing candidates for free."""
        client = CountingClient()
        service = DecisionService(adr_store, tmp_path, gen_config, client=client)
        first = await service.generate("svc.py")
        second = await service.generate("svc.py")
        assert client.calls == 1
        assert second.reused == first.decision_ids
        assert second.decision_ids == []

    async def test_rerun_preserves_a_reviewed_candidate(self, adr_store, tmp_path, source_file, gen_config):
        """AC6: review state survives regeneration."""
        # FILL IN: generate, accept the candidate via service.review, regenerate;
        # assert the record's review_status is still 'accepted' and its
        # review_history is unchanged
        raise NotImplementedError

    async def test_changed_evidence_creates_a_new_record(self, adr_store, tmp_path, source_file, gen_config):
        """AC6: new evidence mints a new id; the old record survives."""
        # FILL IN: generate, modify source_file, generate again; assert a second
        # distinct decision_id exists and the first is still retrievable
        raise NotImplementedError


class TestEvidenceDrift:
    async def test_mid_generation_change_writes_nothing(self, adr_store, tmp_path, source_file, gen_config):
        """spec §7: a concurrent build must not produce a stale candidate."""
        # FILL IN: use a client whose invoke() rewrites source_file before
        # returning; assert the GenerationResult has no decision_ids, carries an
        # ADR_EVIDENCE_CHANGED diagnostic, and that the plane holds no candidate
        raise NotImplementedError


class TestReview:
    async def test_accept_round_trips_through_the_store(self, adr_store, tmp_path, source_file, gen_config):
        """AC11 end to end: accepted in the wiki, still inferred."""
        service = DecisionService(adr_store, tmp_path, gen_config, client=CountingClient())
        decision_id = (await service.generate("svc.py")).decision_ids[0]
        record, _ = await DecisionRepository(adr_store).get(decision_id)
        updated = await service.review(ReviewRequest(decision_id=decision_id, expected_revision=record.revision,
                                                     action="accept", actor="human:maintainer", reason="agreed"))
        assert updated.review_status == "accepted"
        assert updated.origin == "inferred" and updated.source_status == "unknown"
        stored, _ = await DecisionRepository(adr_store).get(decision_id)
        assert stored.review_status == "accepted" and len(stored.review_history) == 1

    async def test_concurrent_reviews_have_one_winner(self, adr_store, tmp_path, source_file, gen_config):
        """AC6: the loser cannot erase the winner's history."""
        # FILL IN: generate; issue two reviews with the SAME expected_revision;
        # assert exactly one succeeds and the other raises
        # ADR_REVISION_CONFLICT, and that the stored history has one event
        raise NotImplementedError

    async def test_link_to_missing_documented_record_is_invalid(self, adr_store, tmp_path, source_file, gen_config):
        # FILL IN: assert a 'link' naming a nonexistent adr:doc: id raises
        # ADR_INVALID_ARGUMENT and writes nothing
        raise NotImplementedError

    async def test_review_of_unknown_id_is_invalid(self, adr_store, tmp_path, gen_config):
        service = DecisionService(adr_store, tmp_path, gen_config)
        with pytest.raises(DecisionError) as exc:
            await service.review(ReviewRequest(decision_id="adr:candidate:nope", expected_revision=1,
                                               action="accept", actor="a"))
        assert exc.value.code == "ADR_INVALID_ARGUMENT"
```

### FILL IN checklist

- [ ] `service.py::_target_evidence` — symbol/file/name resolution, complete-file read; bounded by spec §2 / AC2
- [ ] `service.py::generate` — the six numbered steps; bounded by AC4 / AC5 / AC6
- [ ] `service.py::review` — link validation + CAS save; bounded by spec §2 / AC11
- [ ] (`service.py::sync` needs no FILL IN — the blueprint block is complete)
- [ ] `test_service_generation.py` — nine test bodies; bounded by the assertions named in each docstring

---

## Acceptance Criteria

- [ ] `self._root is None` refuses generation with `ADR_INVALID_ARGUMENT`; no client is resolved (spec §2 Module 6)
- [ ] The dedup probe runs **before** the client is resolved — a rerun works with no model configured (AC6)
- [ ] A rerun over unchanged evidence invokes zero times and returns the existing ids in `reused` (AC6)
- [ ] A reviewed candidate's `review_status` and `review_history` survive a rerun byte-identically (AC6)
- [ ] Changed evidence mints a new id; the old record survives (AC6)
- [ ] Any evidence drift between packet and write persists **nothing** and reports `ADR_EVIDENCE_CHANGED`
- [ ] Persisted candidates are `origin='inferred'`, `source_status='unknown'`, `review_status='unreviewed'` with `GenerationInfo` (AC4)
- [ ] Every cited `EvidenceRef` came from the packet — no invented paths (AC4)
- [ ] `review` surfaces `ADR_REVISION_CONFLICT` with no retry; concurrent reviews leave exactly one event (AC6, AC11)
- [ ] A `link` to a missing or inferred target raises `ADR_INVALID_ARGUMENT` and writes nothing
- [ ] No `--force` path exists (spec §2)
- [ ] `sync` delegates to `refresh_decisions`, refuses a `None` root, and makes zero LLM calls (AC5)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_service_generation.py -q`

---

## Agent Instructions

1. **Read the spec** §2 "Candidate generation and attributed review" and AC4/AC5/AC6/AC11.
2. **Verify the Codebase Contract** — confirm the three dependency modules landed with the listed signatures.
3. **Implement** from the blueprint; complete every `# FILL IN:`. Do not change `for_symbol`/`why`.
4. **Verify** the Validation Command passes.
5. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
6. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (Fallback Sequential Loop —
`parrot-sdd-coder` MCP server unresponsive throughout this run)
**Date**: 2026-09-19
**Notes**: `_target_evidence` resolves a `sym:` id via the injected
structural service's `lookup()` (matching on exact `symbol_id`) to get a
real line span, a bare name via `_resolve_symbol` (refusing ambiguity
before ever reading a file), or a bare repository-relative path as
whole-file evidence. `_evidence_fingerprint` sorts the evidence the same
way `codec.content_fingerprint` sorts a record's evidence, so the same
snapshot always yields the same digest. `generate()` probes existing
records by `(generation.scope_id, generation.input_sha1)` BEFORE calling
`resolve_client` — a rerun over unchanged evidence returns `reused` with
zero client construction/invocation, satisfying AC6 for an offline rerun.
Otherwise: resolve → one `generate_candidates` call → `recheck_evidence`
(any drift persists nothing, reported as `ADR_EVIDENCE_CHANGED`) → mint a
deterministic `candidate_decision_id` per surviving draft → CAS-insert
with `expected_content_hash=None`, treating an `ADR_REVISION_CONFLICT`
there as `reused` (a concurrent generate minted the same byte-equivalent
id first) rather than an error. `sync`/`review` match the blueprint
exactly. 14 new tests (gates, persistence shape, three dedup scenarios
including a reviewed-candidate survival check, mid-generation drift, and
the full review round-trip including concurrent-reviewer and missing-
link-target cases); full `decisions/` suite re-verified at 164/164.

**Deviations from spec**: none in behavior. One necessary test-suite
correction outside this task's own file list: TASK-3490's
`test_service_retrieval.py::TestOffline::test_orchestration_methods_are_declared_but_unimplemented`
asserted `sync`/`generate` raise `NotImplementedError` — an assertion
TASK-3490's own scope explicitly flagged as temporary ("TASK-3493 fills
them in"). Replacing the stubs (this task's actual, listed scope)
necessarily falsifies that assertion; removed it in the same commit
rather than leave a known-broken test behind, with a `NOTE (TASK-3493)`
comment explaining why.
