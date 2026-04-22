# TASK-830: Shared Backend Contract Test Suite

**Feature**: FEAT-116 — Pluggable Storage Backends for Conversations & Artifacts
**Spec**: `sdd/specs/dynamodb-fallback-redis.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-822, TASK-824, TASK-826, TASK-827, TASK-828
**Assigned-to**: unassigned

---

## Context

The guardrail that makes "backend-agnostic" real. One parametrized pytest
file exercises every method on `ConversationBackend` against every available
backend, asserting identical observable behavior. Without this suite, backends
can silently drift in semantics and only be caught by end-to-end customer
issues.

Implements **Module 8** of the spec (§3).

---

## Scope

- Create `packages/ai-parrot/tests/storage/test_backend_contract.py` with a parametrized fixture `any_backend` that yields each of the four backends:
  - `sqlite` — always runs (in-memory / tmp file).
  - `dynamodb` — runs with `moto` mock OR skip if moto not installed.
  - `postgres` — runs only when `POSTGRES_TEST_DSN` is set; skip otherwise with a clear message.
  - `mongodb` — runs only when `MONGO_TEST_DSN` is set; skip otherwise with a clear message.
- Each test in the suite must work against all four backends — no backend-specific branching inside the test bodies (beyond what the fixture skips handle).
- Required test scenarios (one pytest function per row, parametrized with `any_backend`):
  1. `test_initialize_idempotent` — calling `initialize()` twice does not raise and leaves `is_connected == True`.
  2. `test_thread_roundtrip` — `put_thread` then `query_threads` returns the thread with correct fields.
  3. `test_turn_ordering_newest_first` — three turns inserted; `query_turns(newest_first=True)` returns them in descending turn_id.
  4. `test_turn_ordering_oldest_first` — same, `newest_first=False` returns ascending.
  5. `test_delete_turn` — `delete_turn` returns True on existing turn, False on missing.
  6. `test_delete_thread_cascade` — deletes all turns AND artifacts for the session; returns a non-zero count.
  7. `test_artifact_roundtrip_inline_payload` — `put_artifact` → `get_artifact` preserves nested dict structure.
  8. `test_artifact_list_excludes_definition` — `query_artifacts` returns summary-like rows (implementation may include definition; test checks id/type/title are present).
  9. `test_delete_session_artifacts` — removes all artifacts for a session.
  10. `test_overflow_prefix_default_format` — `backend.build_overflow_prefix("u","a","s","aid")` returns `"artifacts/USER#u#AGENT#a/THREAD#s/aid"` (DynamoDB backend MUST preserve this exactly; others inherit the default).
  11. `test_update_thread_changes_fields` — calling `update_thread(..., title="new")` reflects in `query_threads`.
- Add `packages/ai-parrot/tests/storage/conftest.py` augmentation with the `any_backend` fixture.
- Make sure every test uses its own `user_id` or cleans up so tests are order-independent.

**NOT in scope**: Performance benchmarking. Stress / concurrency tests (beyond one trivial concurrent-put check if the agent wants). Observability metrics testing (TASK-831). New test infrastructure like testcontainers setup (but agent MAY wire testcontainers if they prefer over DSN env vars — document the choice).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/storage/test_backend_contract.py` | CREATE | Parametrized contract suite |
| `packages/ai-parrot/tests/storage/conftest.py` | MODIFY (or CREATE if missing) | `any_backend` fixture |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import os
import pytest
from typing import Optional

from parrot.storage.backends.base import ConversationBackend
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.backends.postgres import ConversationPostgresBackend
from parrot.storage.backends.mongodb import ConversationMongoBackend
from parrot.storage.backends.dynamodb import ConversationDynamoDB
```

### Existing Signatures to Use

```python
# parrot/storage/backends/base.py (TASK-822) — all 14 abstract methods.
# Reference signatures:
async def put_thread(user_id, agent_id, session_id, metadata: dict) -> None
async def update_thread(user_id, agent_id, session_id, **updates) -> None
async def query_threads(user_id, agent_id, limit: int = 50) -> List[dict]
async def put_turn(user_id, agent_id, session_id, turn_id: str, data: dict) -> None
async def query_turns(user_id, agent_id, session_id, limit: int = 10, newest_first: bool = True) -> List[dict]
async def delete_turn(user_id, agent_id, session_id, turn_id: str) -> bool
async def delete_thread_cascade(user_id, agent_id, session_id) -> int
async def put_artifact(user_id, agent_id, session_id, artifact_id: str, data: dict) -> None
async def get_artifact(user_id, agent_id, session_id, artifact_id: str) -> Optional[dict]
async def query_artifacts(user_id, agent_id, session_id) -> List[dict]
async def delete_artifact(user_id, agent_id, session_id, artifact_id: str) -> None
async def delete_session_artifacts(user_id, agent_id, session_id) -> int
def build_overflow_prefix(user_id, agent_id, session_id, artifact_id) -> str
```

### `moto` for DynamoDB — Verify Before Using

`moto` is listed in the spec as "existing (dev)". Confirm via:
```bash
source .venv/bin/activate && uv pip show moto
```
If not installed, either skip the `dynamodb` parameterization or make the agent coordinate with the team. Do NOT require it as a hard dep for running the suite.

### Does NOT Exist

- ~~A `BackendFactory` test helper~~ — use the backends directly.
- ~~A pre-built parametrized fixture~~ — the agent writes it in this task.
- ~~`in_memory=True` constructor arg on any backend~~ — use file paths / DSN / moto mocks.
- ~~A global `cleanup_database` hook~~ — each test cleans up after itself or uses unique keys.
- ~~`pytest-asyncio` auto-mode configuration assumed~~ — check `pyproject.toml` for `asyncio_mode`; if not "auto", decorate each test with `@pytest.mark.asyncio`.

---

## Implementation Notes

### Fixture Skeleton

```python
# packages/ai-parrot/tests/storage/conftest.py
import os
import pytest

from parrot.storage.backends.base import ConversationBackend
from parrot.storage.backends.sqlite import ConversationSQLiteBackend

POSTGRES_DSN = os.environ.get("POSTGRES_TEST_DSN")
MONGO_DSN = os.environ.get("MONGO_TEST_DSN")


def _dynamodb_backend():
    try:
        import moto  # noqa: F401
    except ImportError:
        pytest.skip("moto not installed — skipping DynamoDB contract tests")
    # Set up moto mock, return ConversationDynamoDB pointed at a fake region.
    ...


@pytest.fixture(params=["sqlite", "dynamodb", "postgres", "mongodb"])
async def any_backend(request, tmp_path) -> ConversationBackend:
    name = request.param
    if name == "sqlite":
        b = ConversationSQLiteBackend(path=str(tmp_path / f"contract-{request.node.name}.db"))
    elif name == "dynamodb":
        b = _dynamodb_backend()
    elif name == "postgres":
        if not POSTGRES_DSN:
            pytest.skip("POSTGRES_TEST_DSN not set")
        from parrot.storage.backends.postgres import ConversationPostgresBackend
        b = ConversationPostgresBackend(dsn=POSTGRES_DSN)
    elif name == "mongodb":
        if not MONGO_DSN:
            pytest.skip("MONGO_TEST_DSN not set")
        from parrot.storage.backends.mongodb import ConversationMongoBackend
        b = ConversationMongoBackend(dsn=MONGO_DSN, database=f"parrot_test_{request.node.name}")
    await b.initialize()
    yield b
    # Teardown: try to delete all test rows for this session
    try:
        await b.delete_thread_cascade("u", "a", "s1")
        await b.delete_session_artifacts("u", "a", "s1")
    finally:
        await b.close()
```

### Test Skeleton

```python
# packages/ai-parrot/tests/storage/test_backend_contract.py
import pytest


@pytest.mark.asyncio
async def test_initialize_idempotent(any_backend):
    await any_backend.initialize()  # second call
    assert any_backend.is_connected is True


@pytest.mark.asyncio
async def test_thread_roundtrip(any_backend):
    await any_backend.put_thread("u", "a", "s1", {"title": "Hello", "message_count": 0})
    threads = await any_backend.query_threads("u", "a", limit=10)
    match = next((t for t in threads if t["session_id"] == "s1"), None)
    assert match is not None
    assert match["title"] == "Hello"


@pytest.mark.asyncio
async def test_turn_ordering_newest_first(any_backend):
    await any_backend.put_thread("u", "a", "s1", {"title": "t"})
    for i in range(3):
        await any_backend.put_turn("u", "a", "s1", f"{i:03d}", {"text": f"t-{i}"})
    turns = await any_backend.query_turns("u", "a", "s1", limit=10, newest_first=True)
    ids = [t["turn_id"] for t in turns]
    assert ids == ["002", "001", "000"]


@pytest.mark.asyncio
async def test_delete_thread_cascade(any_backend):
    await any_backend.put_thread("u", "a", "s1", {"title": "t"})
    for i in range(3):
        await any_backend.put_turn("u", "a", "s1", f"{i:03d}", {"text": "x"})
    await any_backend.put_artifact("u", "a", "s1", "art1", {"artifact_type": "chart", "title": "c"})

    deleted = await any_backend.delete_thread_cascade("u", "a", "s1")
    assert deleted >= 3  # 3 turns at minimum (some backends also count the thread row)
    assert await any_backend.query_turns("u", "a", "s1") == []


@pytest.mark.asyncio
async def test_artifact_roundtrip_preserves_nested(any_backend):
    payload = {
        "artifact_type": "chart",
        "title": "c",
        "definition": {"nested": {"a": 1, "b": [1, 2, 3]}},
        "created_by": "user",
    }
    await any_backend.put_artifact("u", "a", "s1", "art", payload)
    got = await any_backend.get_artifact("u", "a", "s1", "art")
    assert got is not None
    assert got["definition"] == {"nested": {"a": 1, "b": [1, 2, 3]}}


@pytest.mark.asyncio
async def test_build_overflow_prefix_matches_dynamodb_layout(any_backend):
    assert (
        any_backend.build_overflow_prefix("u", "a", "s", "aid")
        == "artifacts/USER#u#AGENT#a/THREAD#s/aid"
    )
```

### Key Constraints

- **Cleanliness**: tests MUST clean up after themselves (fixture teardown) so running the suite against a long-lived Postgres/Mongo is safe.
- **Skip messages**: every skip must say which env var to set.
- **pytest-asyncio mode**: check `packages/ai-parrot/pyproject.toml` or `pytest.ini` for `asyncio_mode`; if "strict", every async test needs `@pytest.mark.asyncio`.
- **Unique database names for Mongo**: use `parrot_test_<test_name>` so concurrent runs don't clobber.
- **No hardcoded paths**: always use `tmp_path` for SQLite.
- **Avoid Mongo TTL timing assertions**: Mongo's TTL reaper is minute-granular — do not assert instant expiry.

### References in Codebase

- `parrot/storage/backends/base.py` (TASK-822) — signatures.
- `parrot/storage/backends/dynamodb.py` (TASK-824) — the reference implementation whose semantics are the oracle.
- Each backend's own unit tests (from TASKs 826–828) — study to confirm implementations match expectations.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/tests/storage/test_backend_contract.py` exists and contains at least the 11 scenarios listed in Scope.
- [ ] All tests pass against `sqlite` unconditionally: `pytest packages/ai-parrot/tests/storage/test_backend_contract.py -v -k sqlite`.
- [ ] DynamoDB parametrization passes when `moto` is available, skips cleanly otherwise.
- [ ] Postgres parametrization skips cleanly when `POSTGRES_TEST_DSN` unset; passes when set.
- [ ] Mongo parametrization skips cleanly when `MONGO_TEST_DSN` unset; passes when set.
- [ ] No test-internal backend-specific branching (besides fixture skips).
- [ ] `test_build_overflow_prefix_matches_dynamodb_layout` passes for ALL backends (the default + DynamoDB override both yield the same string).
- [ ] Running the full file concurrently (`pytest -n 2`) does not cause cross-test interference (use unique session IDs / Mongo DB names if needed).

---

## Test Specification

See "Test Skeleton" above — the task IS the test file.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at §4 "Integration Tests" for the full desired matrix.
2. **Check dependencies** — TASK-822, TASK-824, TASK-826 are required; TASK-827/828 are optional (if they aren't complete, those parametrizations skip).
3. **Check `moto` availability** — `uv pip show moto` determines the DynamoDB strategy.
4. **Check `pytest-asyncio` mode** in `pyproject.toml` / `pytest.ini` to know whether `@pytest.mark.asyncio` is required per-test.
5. **Verify the Codebase Contract**.
6. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
7. **Implement** in order: conftest fixture → happy-path tests → edge cases → cleanup verification.
8. **Run the suite** with at least SQLite:
   ```bash
   source .venv/bin/activate
   pytest packages/ai-parrot/tests/storage/test_backend_contract.py -v
   ```
9. If possible, run with a local Postgres and Mongo to validate those paths.
10. **Move** this file to `sdd/tasks/completed/`.
11. **Update index** → `"done"`.
12. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
