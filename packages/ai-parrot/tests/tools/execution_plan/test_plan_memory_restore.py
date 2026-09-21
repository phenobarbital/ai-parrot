"""FEAT-585 M2 — exact-version working-memory restoration tests."""
from __future__ import annotations

from typing import Any

import pytest

from parrot.tools.execution_plan.memory import PlanWorkingMemoryCatalog, RestoreError
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.models import EvidenceRef, TaskScope

pytestmark = pytest.mark.asyncio
SCOPE = TaskScope(chatbot_id="execution-plan", user_id="proc-1", session_id="sess-1")
OTHER = TaskScope(chatbot_id="execution-plan", user_id="proc-2", session_id="sess-1")


@pytest.fixture
def backend() -> InMemoryArtifactStore:
    """Return an enabled in-memory versioned artifact backend."""
    return InMemoryArtifactStore(TaskMemoryConfig(enabled=True))


async def _seed(backend: InMemoryArtifactStore, key: str, value: Any) -> EvidenceRef:
    """Write one version through a producer catalog and return its exact reference."""
    producer = PlanWorkingMemoryCatalog(backend=backend, scope=SCOPE)
    await producer.aput_generic(key, value)
    entry = await producer.aget(key)
    metadata = entry.version_metadata
    assert metadata is not None
    return EvidenceRef(artifact_id=metadata.artifact_id, version=metadata.version)


async def test_restore_publishes_locally_without_new_version(backend: InMemoryArtifactStore) -> None:
    """Restoration reads a prior version and does not allocate another version."""
    ref = await _seed(backend, "summary", {"answer": 42})
    catalog = PlanWorkingMemoryCatalog(backend=backend, scope=SCOPE)

    await catalog.restore_version("summary", ref, max_bytes=1_000)

    assert (await catalog.aget("summary")).data == {"answer": 42}
    producer = PlanWorkingMemoryCatalog(backend=backend, scope=SCOPE)
    await producer.aput_generic("summary", {"answer": 43})
    next_entry = await producer.aget("summary")
    assert next_entry.version_metadata is not None
    assert next_entry.version_metadata.version == ref.version + 1


async def test_restore_unknown_version_is_missing_or_expired(backend: InMemoryArtifactStore) -> None:
    """An unknown version is indistinguishable from an expired one."""
    catalog = PlanWorkingMemoryCatalog(backend=backend, scope=SCOPE)

    with pytest.raises(RestoreError, match="not available") as raised:
        await catalog.restore_version("summary", EvidenceRef(artifact_id="unknown", version=1), max_bytes=1_000)

    assert raised.value.code == "missing_or_expired"
    assert "summary" not in catalog._store


async def test_restore_other_scope_is_missing(backend: InMemoryArtifactStore) -> None:
    """A version owned by another scope reads as absent."""
    ref = await _seed(backend, "summary", "private")
    catalog = PlanWorkingMemoryCatalog(backend=backend, scope=OTHER)

    with pytest.raises(RestoreError) as raised:
        await catalog.restore_version("summary", ref, max_bytes=1_000)

    assert raised.value.code == "missing_or_expired"


async def test_restore_over_budget_is_refused(backend: InMemoryArtifactStore) -> None:
    """A byte-bound backend refusal is surfaced with the stable budget code."""
    ref = await _seed(backend, "summary", "long enough to exceed one byte")
    catalog = PlanWorkingMemoryCatalog(backend=backend, scope=SCOPE)

    with pytest.raises(RestoreError) as raised:
        await catalog.restore_version("summary", ref, max_bytes=1)

    assert raised.value.code == "restore_budget_exceeded"


async def test_conflicting_pin_is_alias_conflict(backend: InMemoryArtifactStore) -> None:
    """One local alias cannot be rebound to another exact version."""
    first = await _seed(backend, "summary", "first")
    producer = PlanWorkingMemoryCatalog(backend=backend, scope=SCOPE)
    await producer.aput_generic("summary", "second")
    second_entry = await producer.aget("summary")
    assert second_entry.version_metadata is not None
    second = EvidenceRef(
        artifact_id=second_entry.version_metadata.artifact_id,
        version=second_entry.version_metadata.version,
    )
    catalog = PlanWorkingMemoryCatalog(backend=backend, scope=SCOPE)
    catalog._bind_version("summary", first)

    with pytest.raises(RestoreError) as raised:
        catalog._bind_version("summary", second)

    assert raised.value.code == "artifact_alias_conflict"


async def test_alias_moved_later_still_reads_pinned_version(backend: InMemoryArtifactStore) -> None:
    """Lazy restoration uses the pinned version rather than the moved alias."""
    first = await _seed(backend, "summary", "first")
    producer = PlanWorkingMemoryCatalog(backend=backend, scope=SCOPE)
    await producer.aput_generic("summary", "second")
    catalog = PlanWorkingMemoryCatalog(backend=backend, scope=SCOPE)
    catalog._bind_version("summary", first)

    assert (await catalog.aget("summary")).data == "first"
