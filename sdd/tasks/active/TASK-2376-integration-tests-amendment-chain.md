# TASK-2376: Integration tests — pipeline ingestion, incrementality, amendment chain

**Feature**: FEAT-449 — Legal Norms Graph (BOE consolidated legislation with temporal validity)
**Spec**: `sdd/specs/legal-norms-graph-boe.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2374, TASK-2375
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests and §5. This task proves the feature actually works end to end and
closes the spec's headline acceptance criterion: **the wording in force on a given date matches
hand-verified reality for a real Spanish norm**.

It also asserts the two guarantees that are easy to lose silently: that the sync is genuinely
incremental, and that **zero LLM calls** occur anywhere in ingestion or resolution (spec goal
G6 — asserted by test, not by convention).

> **Spec open question (§8)**: which norm and article back the amendment-chain test is
> **unresolved** and owned by Jesus Lara. Confirm the choice before writing the assertions;
> the wording on each chosen date must be verified by a human against the official BOE text,
> not inferred from the parser's own output (which would make the test circular).

---

## Scope

- Integration test: `OntologyRefreshPipeline.run(tenant, domain="legal")` ingests the fixture
  corpus, upserts `norma` + `articulo` nodes, and reports `RefreshReport.errors == []`.
- Integration test: a second consecutive run reports `inserted == 0` and `unchanged > 0`.
- Integration test: end-to-end amendment chain — ingest, then assert `article_in_force`
  returns the hand-verified wording on N dates, including both boundaries.
- Integration test: the `article_in_force` `query_template` passes `validate_aql`.
- Test: assert no LLM client is constructed or called during ingestion or resolution.
- Provide the `legal_tenant_ctx` fixture (spec §4) used by this and other test modules.

**NOT in scope**: production deployment or scheduling; performance benchmarking; any
implementation fix — if a test fails, the fix belongs to the owning task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/legal/conftest.py` | CREATE | `legal_tenant_ctx`, fixture-corpus helpers |
| `packages/ai-parrot-tools/tests/legal/test_boe_integration.py` | CREATE | Pipeline + incrementality + amendment-chain tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from datetime import date
from pathlib import Path
import pytest

from parrot.knowledge.ontology.refresh import (
    OntologyRefreshPipeline,   # refresh.py:61
    RefreshReport,             # refresh.py:41
)
from parrot.knowledge.ontology.tenant import TenantOntologyManager    # tenant.py:29
from parrot.knowledge.ontology.graph_store import (
    OntologyGraphStore,        # graph_store.py:33
    UpsertResult,              # graph_store.py:19
)
from parrot.knowledge.ontology.schema import TenantContext            # schema.py:406
from parrot.knowledge.ontology.validators import validate_aql         # validators.py:36 (ASYNC)
from parrot.knowledge.ontology.parser import OntologyParser           # parser.py:19

from parrot_tools.legal.boe import sync_boe                           # TASK-2374
from parrot_tools.legal.boe.queries import article_in_force           # TASK-2375
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py:41
class RefreshReport(BaseModel):
    tenant: str
    started_at: datetime
    completed_at: datetime | None
    entity_results: dict[str, UpsertResult]
    errors: list[str]

# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:19
class UpsertResult(BaseModel):
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0        # <- the incrementality assertion reads this

# packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py:94
async def run(self, tenant_id: str, domain: str | None = None) -> RefreshReport: ...
#   NOTE: entities whose entity_def.source is falsy are SKIPPED (refresh.py ~line 200).
#   Materia has no source by design, so it will NOT appear in entity_results.

# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:71
async def initialize_tenant(self, ctx: TenantContext) -> None: ...
#   Provisions collections from the ontology's entity/relation defs.

# packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py:92
def resolve(self, tenant_id: str, domain: str | None = None) -> TenantContext: ...
```

### Does NOT Exist

- ~~A shared ArangoDB test fixture for the ontology layer~~ — check
  `packages/ai-parrot/tests/knowledge/ontology/test_ontology_integration.py` and
  `test_tenant_pipeline_integration.py` for how existing integration tests obtain (or skip)
  a database. **Follow whatever they already do** rather than inventing a new harness.
- ~~`RefreshReport.inserted`~~ — counts live per-entity inside
  `RefreshReport.entity_results[entity_name].inserted`, not on the report itself.
- ~~`Materia` in `entity_results`~~ — it has no `source`, so the pipeline skips it. Asserting
  its presence will fail.
- ~~`validate_aql` as sync~~ — it is `async def` (`validators.py:36`); `await` it.
- ~~Network access in tests~~ — the BOE fetch must be mocked; parsing runs off checked-in
  fixtures (spec §4).

---

## Implementation Notes

### Pattern to Follow

Mirror the existing integration-test conventions:

```python
# packages/ai-parrot/tests/knowledge/ontology/test_tenant_pipeline_integration.py
# — how a tenant context is built and how the suite handles a missing ArangoDB
#   (skip marker vs. in-memory stub). Reuse that approach; do not invent a new one.
```

### Key Constraints

- **Read the existing ontology integration tests first.** If they skip without a live
  ArangoDB, this suite should too — mark it clearly rather than silently passing.
- The amendment-chain expectations must be **hand-verified against official BOE text** and
  written as literal constants in the test. Deriving them from the parser makes the test
  circular and worthless.
- Assert **both** boundaries explicitly: `as_of == valid_from` selects that version;
  `as_of == valid_to` selects the next.
- The no-LLM assertion should be structural — e.g. patch the LLM client factory and assert it
  is never invoked during `sync_boe` and `article_in_force`.
- No network. Mock the BOE fetch at the `aiohttp` boundary.

### References in Codebase

- `packages/ai-parrot/tests/knowledge/ontology/test_tenant_pipeline_integration.py` — tenant + pipeline integration conventions
- `packages/ai-parrot/tests/knowledge/ontology/test_ontology_integration.py` — DB-dependent test handling
- `packages/ai-parrot/tests/knowledge/ontology/test_ontology_refresh.py` — how refresh is exercised
- Spec §4 Test Specification and §5 Acceptance Criteria

---

## Acceptance Criteria

- [ ] `legal_tenant_ctx` fixture resolves a `TenantContext` with `domain="legal"`
- [ ] Pipeline run over the fixture corpus completes with `RefreshReport.errors == []`
- [ ] `norma` and `articulo` appear in `entity_results`; `materia` does **not** (no source)
- [ ] Second consecutive run yields `inserted == 0` and `unchanged > 0`
- [ ] `await validate_aql(article_in_force_template)` passes
- [ ] End-to-end: `article_in_force` returns the hand-verified wording on N dates for a real norm
- [ ] Both boundaries asserted: `valid_from` inclusive, `valid_to` exclusive
- [ ] A date before the first `valid_from` returns `None`
- [ ] **Zero LLM calls** asserted during ingestion and resolution (spec goal G6)
- [ ] No network access in the suite
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/legal/ -v`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/legal/test_boe_integration.py
from datetime import date
import pytest
from parrot.knowledge.ontology.validators import validate_aql
from parrot_tools.legal.boe.queries import article_in_force

# Hand-verified against the official BOE consolidated text — DO NOT derive from the parser.
NORM_KEY = "..."          # confirm with owner (spec §8 open question)
EXPECTED = {              # as_of -> expected wording fragment
    date(2016, 1, 1): "...",
    date(2019, 6, 1): "...",
}


class TestBOEIntegration:
    async def test_pipeline_ingests_without_errors(self, legal_tenant_ctx, boe_corpus):
        report = await run_sync(legal_tenant_ctx)
        assert report.errors == []
        assert "Norma" in report.entity_results
        assert "Articulo" in report.entity_results
        assert "Materia" not in report.entity_results   # no source -> skipped by design

    async def test_second_run_is_incremental(self, legal_tenant_ctx, boe_corpus):
        await run_sync(legal_tenant_ctx)
        second = await run_sync(legal_tenant_ctx)
        for result in second.entity_results.values():
            assert result.inserted == 0
            assert result.unchanged > 0

    @pytest.mark.asyncio
    async def test_traversal_passes_aql_validation(self, legal_tenant_ctx):
        tpl = legal_tenant_ctx.ontology.traversal_patterns["article_in_force"].query_template
        await validate_aql(tpl)

    @pytest.mark.parametrize("as_of,fragment", sorted(EXPECTED.items()))
    async def test_amendment_chain_end_to_end(self, store, legal_tenant_ctx, as_of, fragment):
        version = await article_in_force(store, legal_tenant_ctx, NORM_KEY, as_of)
        assert version is not None
        assert fragment in version.text

    async def test_boundaries(self, store, legal_tenant_ctx):
        """valid_from inclusive; valid_to exclusive."""
        ...

    async def test_before_entry_into_force_returns_none(self, store, legal_tenant_ctx):
        assert await article_in_force(store, legal_tenant_ctx, NORM_KEY, date(1900, 1, 1)) is None

    async def test_no_llm_calls(self, legal_tenant_ctx, boe_corpus, no_llm_guard):
        """Spec goal G6 — ingestion and resolution are fully deterministic."""
        await run_sync(legal_tenant_ctx)
        assert no_llm_guard.call_count == 0
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/legal-norms-graph-boe.spec.md` (§4, §5, §8).
2. **Check dependencies** — TASK-2374 and TASK-2375 must be in `sdd/tasks/completed/`.
3. **Confirm the amendment-chain norm with the owner** (spec §8 unresolved question) before
   writing assertions.
4. **Read the existing ontology integration tests first** and follow their DB-handling convention.
5. **Verify the Codebase Contract** before writing code.
6. **Update status** in `sdd/tasks/index/legal-norms-graph-boe.json` → `"in-progress"`.
7. **Implement** the fixtures and tests.
8. **Verify** all acceptance criteria.
9. **Move this file** to `sdd/tasks/completed/TASK-2376-integration-tests-amendment-chain.md`.
10. **Update index** → `"done"`, and set `completed_at` on the index header if this is the last task.
11. **Fill in the Completion Note** — including which norm/article backed the chain test.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Norm/article used for the amendment-chain test**:

**Deviations from spec**: none | describe if any
