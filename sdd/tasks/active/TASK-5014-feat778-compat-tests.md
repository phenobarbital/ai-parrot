# TASK-5014: FEAT-778 ADRSource compatibility tests (M11)

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5003, TASK-5007
**Assigned-to**: unassigned

---

## Context

Spec G7, §3 Module 11, AC17. FEAT-778's `ADRSource` (experts/knowledge/sources/adr.py:16) feeds accepted
ADRs to expert agents through `DecisionService.why()` and must keep its runtime behaviour and tests
unchanged. This task adds **tests only**, proving on fixtures with schema-1 and schema-2 records that:

1. among the records `why()` returns, `ADRSource.layers()` accepts exactly those `is_eligible()` accepts;
2. schema-2 envelopes round-trip through `DecisionService.why()` without diagnostics.

The equivalence relies on PLAN decision 5, implemented by TASK-5007: retirement sets **both**
`lifecycle="retired"` and `source_status="superseded"`, so `ADRSource` (filters `source_status`, adr.py:52)
and `DecisionService._visible()` (hides `HISTORICAL_STATUSES`, service.py:161-170) drop a retired record
with no runtime change.

---

## Scope

- Create `T/test_feat778_compat.py` (T = `packages/ai-parrot/tests/knowledge/wiki/decisions`):
  - fixture plane on `adr_store`: (a) legacy schema-1 `adr:doc:` accepted + `review_status="unreviewed"`;
    (b) legacy accepted + `review_status="rejected"`; (c) schema-2 `adr:spec:` record with `batch_id` of a
    **published** batch (marker written with TASK-5003's `batch_marker_id`/`BATCH_MARKER_CATEGORY`, state
    `published`); (d) schema-2 record retired per decision 5; (e) legacy `source_status="proposed"`.
    All decision texts share one query word so `why()` returns them.
  - `test_adr_source_equivalence`: ids accepted by `ADRSource(DecisionService(...)).layers(...)` ==
    ids among `why()` hits whose record `is_eligible(record, approved_batches={batch})`.
  - `test_schema2_roundtrip_through_why`: `dossier.diagnostics` is empty and the schema-2 hit carries
    the same `decision_id`/`revision`.
- Append to `packages/ai-parrot/tests/experts/test_sources_inline.py` one stub-based test: a hit with
  `source_status="superseded"` (a retired schema-2 record's projection) produces no layer — locks the
  `ADRSource` filter the retirement design depends on.

**NOT in scope**: any change to `ADRSource`, `KnowledgeResolver`, `DecisionService` (spec Non-Goals,
AC17); the eligibility predicate itself (TASK-5003); retirement implementation (TASK-5007).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/experts/test_sources_inline.py` | MODIFY | Append superseded-hit filter test |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_feat778_compat.py` | CREATE | ADRSource ⇔ is_eligible equivalence + schema-2 why() round-trip |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.experts.knowledge.sources.adr import ADRSource, ADR_LIMIT, ADR_BUDGET_TOKENS   # verified: experts/knowledge/sources/adr.py:16,13,12
from parrot.experts.models import KnowledgeMode, KnowledgeSourceKind, KnowledgeSourceSpec   # verified: experts/models.py:62,82 (used by test_sources_inline.py:14)
from parrot.knowledge.wiki.decisions.models import DecisionConfig, DecisionRecord, DecisionDossier, DecisionHit  # verified: models.py:63,172,240,224
from parrot.knowledge.wiki.decisions.repository import DecisionRepository                    # verified: repository.py:26
from parrot.knowledge.wiki.decisions.service import DecisionService                          # verified: service.py:96
from parrot.knowledge.wiki.store import WikiPageRecord                                       # verified: store.py (WikiPageRecord)
from parrot.knowledge.wiki.decisions.inventory import BATCH_MARKER_CATEGORY, batch_marker_id, is_eligible   # created by TASK-5003
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/experts/knowledge/sources/adr.py
class ADRSource:                                                               # line 16
    def __init__(self, service: DecisionService) -> None                       # line 21
    async def layers(self, spec, bundle, *, workspace, counter) -> list[KnowledgeLayer]   # line 29
        # dossier = await self.service.why(bundle.manifest.description, limit=ADR_LIMIT, budget_tokens=ADR_BUDGET_TOKENS)  line 48
        # keeps hit iff hit.source_status in spec.filter.get("status", ["accepted"]) and hit.review_status != "rejected"  line 52
        # layer.source == f"adr:{hit.decision_id}"                             line 60
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py
class DecisionService:                                                         # line 96
    def __init__(self, store, root: Path | None, config: DecisionConfig, structural=None, client=None)  # line 99
    def _visible(self, record, include_history) -> bool                        # line 161 — hides HISTORICAL_STATUSES (line 73)
    async def why(self, question, *, include_history=False, limit=10, budget_tokens=3000) -> DecisionDossier  # line 276
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py
async def save(self, record: DecisionRecord, expected_content_hash: str | None) -> DecisionRecord   # line 96
# packages/ai-parrot/tests/knowledge/wiki/decisions/conftest.py
adr_store fixture  # line 190-195 — InMemoryWikiStore(tmp_path / "wiki-pages", wiki_name="adr-test")
# packages/ai-parrot/tests/experts/test_sources_inline.py
class StubDecisionService                     # line 28 — why(question, *, limit, budget_tokens)
def _spec(source, *, filter_=None)            # line 42
def _bundle(expert_bundle, *, tenant=None, global_only=False)  # line 47
def _hit(decision_id, *, status="accepted", review_status="accepted", links=None)  # line 56
class CharacterCounter                        # line 18
# last line of file (append anchor), count 1:
#     assert [layer.source for layer in layers] == ["adr:matching"]          # line 179
# Contracts from earlier tasks
# inventory.py (TASK-5003)
def is_eligible(record: DecisionRecord, *, approved_batches: frozenset[str]) -> bool
BATCH_MARKER_CATEGORY = "adr_batch"; def batch_marker_id(batch_id: str) -> str   # PLAN decision 4
```

### Does NOT Exist
- ~~any runtime change to `ADRSource` / `DecisionService`~~ — forbidden by AC17.
- ~~`ADRSource` checking `lifecycle` or `batch_id`~~ — it only reads `source_status` and `review_status`; equivalence for retired records depends on decision 5.
- ~~`expert_bundle` fixture in `tests/knowledge/wiki/decisions/`~~ — it lives in `tests/experts/conftest.py:22`; in the decisions test build a minimal bundle stand-in with `types.SimpleNamespace(manifest=SimpleNamespace(description=...))` (ADRSource reads only `bundle.manifest.description`).
- ~~`DecisionService` filtering pending-batch records~~ — it does not; see Implementation Notes.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/experts/test_sources_inline.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_feat778_compat.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/experts/knowledge/sources/adr.py#ADRSource",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py#DecisionService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Known gap, do not "fix"**: a record written by an in-flight (pending-marker) batch is visible to
  `DecisionService.why()` and therefore to `ADRSource`, but is not eligible. The batch publisher writes
  records then flips the marker, so the window is transient. Keep pending-batch records OUT of the
  equivalence fixtures, and record this window in the Completion Note as an ESCALATE item (AC17 forbids
  changing `ADRSource`).
- Use real `DecisionRepository.save` + `DecisionService` in the decisions test (no stubs) — the point is
  the real retrieval path.
- Marker page for the published batch: `WikiPageRecord(concept_id=batch_marker_id(batch), category=BATCH_MARKER_CATEGORY, body=<canonical JSON with state "published">, ...)` written with `adr_store.compare_and_swap_page(page, None)` — follow the exact body format TASK-5003/P11 use.

---

## Implementation Blueprint

### Steps (in order)
1. Read TASK-5003 `inventory.py` and TASK-5007 `publish.py` to confirm marker body and retirement fields — *why*: fixtures must look exactly like published data.
2. Write the decisions test module — *why*: AC17 equivalence evidence.
3. Append the stub test to `test_sources_inline.py` — *why*: locks the filter the retirement design relies on.
4. Run both validation commands; run the full existing `test_sources_inline.py` unchanged-tests too — *why*: AC17 "tests unchanged".

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_feat778_compat.py` (CREATE)
```python
"""FEAT-784 M11: FEAT-778 ADRSource stays equivalent to the shared eligibility predicate (AC17)."""

from __future__ import annotations

from types import SimpleNamespace

from parrot.experts.knowledge.sources.adr import ADRSource
from parrot.experts.models import KnowledgeMode, KnowledgeSourceKind, KnowledgeSourceSpec
from parrot.knowledge.wiki.decisions.inventory import BATCH_MARKER_CATEGORY, batch_marker_id, is_eligible
from parrot.knowledge.wiki.decisions.models import DecisionConfig, DecisionRecord
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.decisions.service import DecisionService
from parrot.knowledge.wiki.store import WikiPageRecord

BATCH = "batch-compat"
QUERY = "pgvector"


class _Counter:
    def count(self, text: str) -> int:
        return len(text)


async def _seed(store) -> list[DecisionRecord]:
    """Write fixtures (a)–(e) from the task Scope plus the published marker; return the records."""
    # FILL IN: build the five DecisionRecords (schema_version 1 for a/b/e with adr:doc: ids; schema_version 2
    #   with adr:spec:<doc>#<entry> ids, document_id, entry_id, batch_id=BATCH for c/d; d retired per
    #   PLAN decision 5); every decision text contains QUERY; save via DecisionRepository(store).save(r, None);
    #   write the published marker page — bounded by AC6/AC17
    raise NotImplementedError


async def test_adr_source_equivalence(adr_store) -> None:
    records = {r.decision_id: r for r in await _seed(adr_store)}
    service = DecisionService(adr_store, None, DecisionConfig())
    dossier = await service.why(QUERY, limit=50)
    returned = [h.decision_id for h in [*dossier.documented, *dossier.candidates]]
    expected = {d for d in returned if is_eligible(records[d], approved_batches=frozenset({BATCH}))}
    spec = KnowledgeSourceSpec(source=KnowledgeSourceKind.ADR, mode=KnowledgeMode.INLINE, filter={})
    bundle = SimpleNamespace(manifest=SimpleNamespace(description=QUERY))
    layers = await ADRSource(service).layers(spec, bundle, workspace=None, counter=_Counter())
    assert {layer.source.removeprefix("adr:") for layer in layers} == expected


async def test_schema2_roundtrip_through_why(adr_store) -> None:
    # FILL IN: after _seed, why(QUERY) has no diagnostics and contains record (c) with the same revision — AC2/AC17
    raise NotImplementedError
```
**Why**: real store + real service + real `ADRSource`, only the expert bundle is a stand-in (ADRSource
reads one attribute of it). NOTE: `ADRSource` passes `limit=ADR_LIMIT` (10); keep fixtures ≤ 10 so the
layer set is not truncated relative to `why(limit=50)`.

### `packages/ai-parrot/tests/experts/test_sources_inline.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    assert [layer.source for layer in layers] == ["adr:matching"]' packages/ai-parrot/tests/experts/test_sources_inline.py)
# AFTER — append below `    assert [layer.source for layer in layers] == ["adr:matching"]` (verified: test_sources_inline.py:179, end of file)


@pytest.mark.asyncio
async def test_adr_source_drops_retired_schema2_hits(expert_bundle: Path) -> None:
    """A retired FEAT-784 record projects as source_status='superseded' and never becomes a layer."""
    retired = _hit("adr:spec:demo#rule", status="superseded")
    live = _hit("adr:spec:demo#rule2")
    layers = await ADRSource(StubDecisionService(DecisionDossier(documented=[retired, live]))).layers(
        _spec(KnowledgeSourceKind.ADR), _bundle(expert_bundle), workspace=None, counter=CharacterCounter()
    )
    assert [layer.source for layer in layers] == ["adr:adr:spec:demo#rule2"]
```
**Why**: uses only helpers already in the module (lines 18–76); `source` is `f"adr:{decision_id}"`, hence
the doubled prefix.

### FILL IN checklist
- [ ] `_seed` — five records + published marker, bounded by AC6/AC17 and decision 5
- [ ] `test_schema2_roundtrip_through_why`
- [ ] Completion Note: pending-batch visibility window (ESCALATE)

---

## Acceptance Criteria

- [ ] `test_adr_source_equivalence` passes: ADRSource acceptance == `is_eligible` among `why()` hits (AC17).
- [ ] Schema-2 envelopes round-trip through `why()` with no diagnostics (AC2, AC17).
- [ ] Every pre-existing test in `test_sources_inline.py` is unchanged and passes (AC17).
- [ ] No runtime file touched.
- [ ] `ruff check` clean on both test files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_feat778_compat.py -q`
- `pytest packages/ai-parrot/tests/experts/test_sources_inline.py -q`

---

## Test Specification

See blueprint: `test_adr_source_equivalence`, `test_schema2_roundtrip_through_why`,
`test_adr_source_drops_retired_schema2_hits`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-decision-audit --feature-id FEAT-784`).
2. Confirm TASK-5003 and TASK-5007 are `done`; confirm marker body + retirement fields in their code.
3. Mark in-progress, implement, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the two listed files; close with `scripts/sdd/close_task.sh TASK-5014 sdd-decision-audit verified`.

---

## Completion Note

*(Agent fills this in when done)*
