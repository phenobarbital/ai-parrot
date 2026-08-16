# TASK-2063: Integration Tests for ArangoDB Wiki Backend

**Feature**: FEAT-400 — WikiToolkit ArangoDB Backend
**Spec**: `sdd/specs/wikitoolkit-arangodb-backend.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2057, TASK-2058, TASK-2059, TASK-2060, TASK-2061
**Assigned-to**: unassigned

---

## Context

End-to-end integration tests verifying the full ArangoDB wiki pipeline:
build → ingest → search → query. Requires a real ArangoDB instance.
Corresponds to Module 7 in the spec.

---

## Scope

- Write integration tests that exercise the full pipeline against a real
  ArangoDB instance.
- Test `wikitoolkit build --backend arangodb` → `wikitoolkit query`.
- Test ingest → FTS search → vector search round-trip.
- Test source tracking → staleness detection → re-ingest.
- Mark tests with `@pytest.mark.arangodb` so they can be skipped in CI
  when no ArangoDB instance is available.
- Add fixture for test database creation/teardown.

**NOT in scope**:
- Unit tests (covered by TASK-2057, TASK-2060)
- Performance benchmarking

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/knowledge/wiki/test_arango_integration.py` | CREATE | Integration tests |
| `tests/knowledge/wiki/conftest.py` | MODIFY | Add arango fixtures and pytest mark |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore  # CREATED BY TASK-2057
from parrot.knowledge.wiki.store import WikiPageRecord, BaseWikiStore  # verified: store.py
from parrot.knowledge.wiki.sources import SourceCollectionManager  # verified: sources.py
from parrot.knowledge.wiki.project import WikiProjectConfig, resolve_arango_params  # TASK-2058
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator  # verified: ingest.py
from parrot.knowledge.wiki.search import WikiCombinedSearch  # verified: search.py
```

### Does NOT Exist

- ~~`pytest.mark.arangodb`~~ — needs to be registered in `conftest.py` or `pyproject.toml`

---

## Implementation Notes

### Test Database Lifecycle

```python
@pytest.fixture
async def arango_test_db(arango_params):
    db_name = f"test_wiki_{uuid.uuid4().hex[:8]}"
    params = {**arango_params, "database": db_name}
    store = ArangoDBWikiStore(params, wiki_name="integration_test")
    await store.initialize()
    yield store
    await store.close()
    # Drop the test database
    from asyncdb import AsyncDB
    admin_db = AsyncDB("arangodb", params={**arango_params, "database": "_system"})
    await admin_db.connection()
    await admin_db.drop_database(db_name)
    await admin_db.close()
```

### Skip When No ArangoDB

```python
pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_ARANGODB_HOST"),
    reason="TEST_ARANGODB_HOST not set — skip ArangoDB integration tests",
)
```

### Key Test Scenarios

1. Build wiki from a small set of test files → verify pages in ArangoDB
2. Query via FTS → verify BM25-ranked results
3. Upsert embeddings → vector search → verify cosine-ranked results
4. Ingest source → modify source → detect stale → re-ingest
5. Edge creation → neighbor traversal
6. Stats → verify counts match
7. Lint methods → verify orphan/broken detection

---

## Acceptance Criteria

- [ ] All integration tests pass with a real ArangoDB instance
- [ ] Tests skip cleanly when `TEST_ARANGODB_HOST` is not set
- [ ] Full round-trip: build → query → verify results
- [ ] Source tracking: add → stale → re-ingest cycle
- [ ] Edge traversal: neighbors() returns correct results
- [ ] Test database cleaned up after each test run

---

## Completion Note

Added `tests/knowledge/wiki/test_arango_integration.py` covering all 7
Key Test Scenarios from the task/spec: build+FTS query, embedding
upsert+vector search round-trip, source add→stale-detect→re-ingest→
remove cycle, edge creation+bidirectional `neighbors()` traversal,
`stats()` counts, `orphan_sources`/`broken_edges`/`missing_bodies` lint
checks, and a full CLI round-trip (`wikitoolkit build --backend
arangodb` → `wikitoolkit query`) via `CliRunner` against a real server.
Every test is gated by `pytestmark = [pytest.mark.arangodb,
pytest.mark.skipif(not os.environ.get("TEST_ARANGODB_HOST"), ...)]` —
skips cleanly with no server configured (verified: all 7 report
`SKIPPED`, not `FAILED`/`ERROR`, and no `PytestUnknownMarkWarning`).

Extended `tests/knowledge/wiki/conftest.py` with: a `pytest_configure()`
hook registering the `arangodb` marker (its `addinivalue_line` call is
the actual registration site — the task's Codebase Contract said this
marker "needs to be registered in `conftest.py` or `pyproject.toml`";
this repo's real pytest config file is `pytest.ini`, not
`pyproject.toml`, but `pytest_configure()` in `conftest.py` was already
one of the two named options and keeps the change inside this task's
Files to Create/Modify — no `pytest.ini` edit needed); an `arango_params`
fixture reading `TEST_ARANGODB_*` env vars (deliberately NOT
`ARANGODB_*`, to keep integration-test credentials separate from any
real `.env`-configured wiki); and an `arango_test_db` async fixture that
creates a uniquely-named `test_wiki_<hex>` database, yields an
initialized `ArangoDBWikiStore`, and always tears it down (`close()` +
`drop_database()` in a `finally`) even if the test body raises.

**Verified in this sandbox** (no real ArangoDB server, no
`TEST_ARANGODB_HOST`, no docker container providing one — confirmed via
`docker ps`): the skip mechanism itself (all 7 tests → `SKIPPED`), that
`conftest.py`'s changes don't regress the rest of the suite (665 passed,
9 skipped — 7 new arangodb skips + 2 pre-existing), and lint parity
(`conftest.py` has fewer findings than its own baseline; the new test
file is fully clean after an import-sort fix).

**NOT verified in this sandbox** (documented limitation, not a gap in
the implementation): "All integration tests pass with a real ArangoDB
instance" — this repository has no provisioned ArangoDB service
reachable from this environment. The tests are written and structured
to run correctly per the spec's Key Test Scenarios and this task's own
`arango_test_db`/skip-mechanism design (mirrored faithfully from the
Implementation Notes), but have only been exercised via the skip path
here. Recommend running once against a real instance (e.g. the `docker
run arangodb/arangodb` command in the test module's docstring, with
`TEST_ARANGODB_HOST=127.0.0.1`) before/during `/sdd-done` review or in a
CI job with an ArangoDB service container.
