"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import BaseModel

from parrot.flows.dev_loop.sdd_coder import evidence as evidence_module
from parrot.flows.dev_loop.sdd_coder.evidence import (
    EvidenceConflictError,
    EvidenceCorruptionError,
    ExecutionEvidenceStore,
)
from parrot.flows.dev_loop.sdd_coder.optimization_models import WorkflowEvent
from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root

_FIXED_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _SamplePayload(BaseModel):
    """Minimal Pydantic v2 model used as a `put_artifact` payload in tests."""

    text: str


def _make_event(
    execution_id: str, event_id: str, *, task_id: str = "TASK-1", payload: dict | None = None
) -> WorkflowEvent:
    """Build a minimal valid `task.accepted` WorkflowEvent for one execution."""
    return WorkflowEvent(
        event_id=event_id,
        kind="task.accepted",
        execution_id=execution_id,
        task_id=task_id,
        timestamp=_FIXED_TS,
        source="engine",
        payload=payload or {},
    )


def _append_event_subprocess(root: str, event_json: str) -> None:
    """Child-process entry point: append the same event via a fresh store."""
    event = WorkflowEvent.model_validate_json(event_json)

    async def _run() -> None:
        store = ExecutionEvidenceStore(root=Path(root))
        await store.append_event(event)

    asyncio.run(_run())


def test_multiprocess_append_idempotency(tmp_path: Path) -> None:
    """Identical event ids deduplicate and conflicting payloads fail across writers."""
    execution_id = str(uuid.uuid4())
    event = _make_event(execution_id, "evt-1", payload={"note": "first"})

    # Same execution, same event_id, four independent OS processes racing to
    # append: only one durable line must ever land.
    processes = [
        multiprocessing.Process(target=_append_event_subprocess, args=(str(tmp_path), event.model_dump_json()))
        for _ in range(4)
    ]
    for proc in processes:
        proc.start()
    for proc in processes:
        proc.join(timeout=30)
        assert proc.exitcode == 0

    events_path = tmp_path / "executions" / execution_id / "events.jsonl"
    lines = [line for line in events_path.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 1

    # Concurrency ACROSS different executions: independent and non-interfering.
    other_execution_id = str(uuid.uuid4())
    other_event = _make_event(other_execution_id, "evt-2", payload={"note": "second"})

    async def _run_both() -> None:
        store = ExecutionEvidenceStore(root=tmp_path)
        await asyncio.gather(store.append_event(event), store.append_event(other_event))

    asyncio.run(_run_both())

    other_events_path = tmp_path / "executions" / other_execution_id / "events.jsonl"
    assert len(other_events_path.read_text(encoding="utf-8").splitlines()) == 1
    assert len(events_path.read_text(encoding="utf-8").splitlines()) == 1

    # Same event_id, DIFFERENT payload: a genuine conflict must fail loudly,
    # never silently overwrite the already-durable line.
    conflicting_event = _make_event(execution_id, "evt-1", payload={"note": "different"})

    async def _run_conflict() -> None:
        store = ExecutionEvidenceStore(root=tmp_path)
        await store.append_event(conflicting_event)

    with pytest.raises(EvidenceConflictError):
        asyncio.run(_run_conflict())
    # The conflict must not have mutated the durable file.
    assert len(events_path.read_text(encoding="utf-8").splitlines()) == 1


def test_crash_tail_and_disk_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Interrupted appends and failed persistence never publish valid missing evidence."""
    execution_id = str(uuid.uuid4())
    store = ExecutionEvidenceStore(root=tmp_path)

    first_event = _make_event(execution_id, "evt-crash-1", payload={"seq": 1})
    asyncio.run(store.append_event(first_event))

    events_path = tmp_path / "executions" / execution_id / "events.jsonl"

    # Simulate a crash mid-append: an incomplete trailing line, no newline.
    with events_path.open("ab") as handle:
        handle.write(b'{"event_id": "evt-crash-2", "kind": "task.acce')

    second_event = _make_event(execution_id, "evt-crash-3", payload={"seq": 3})
    asyncio.run(store.append_event(second_event))

    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # the crash tail was repaired away, not preserved
    joined = "\n".join(lines)
    assert "evt-crash-1" in joined
    assert "evt-crash-3" in joined
    assert "evt-crash-2" not in joined

    # Interior corruption (NOT the trailing line) must block reading, never
    # be silently skipped.
    corrupt_execution_id = str(uuid.uuid4())
    corrupt_dir = tmp_path / "executions" / corrupt_execution_id
    corrupt_dir.mkdir(parents=True)
    (corrupt_dir / "events.jsonl").write_text("not-json\n" + first_event.model_dump_json() + "\n", encoding="utf-8")
    with pytest.raises(EvidenceCorruptionError):
        asyncio.run(store.append_event(_make_event(corrupt_execution_id, "evt-x", payload={})))

    # A failed durable write must never leave a fake/partial success behind.
    failing_execution_id = str(uuid.uuid4())

    def _boom(_path: Path, _line_bytes: bytes) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(evidence_module, "_atomic_append_line", _boom)
    with pytest.raises(OSError):
        asyncio.run(store.append_event(_make_event(failing_execution_id, "evt-fail", payload={})))
    monkeypatch.undo()

    failing_events_path = tmp_path / "executions" / failing_execution_id / "events.jsonl"
    assert not failing_events_path.exists()

    # The store keeps working normally once the (simulated) failure clears.
    asyncio.run(store.append_event(_make_event(failing_execution_id, "evt-recovered", payload={})))
    assert "evt-recovered" in failing_events_path.read_text(encoding="utf-8")


def test_artifact_scope_and_unicode_pages(tmp_path: Path) -> None:
    """Cross-execution and traversal reads fail while Unicode pages reconstruct the exact snapshot."""
    execution_id = str(uuid.uuid4())
    other_execution_id = str(uuid.uuid4())
    store = ExecutionEvidenceStore(root=tmp_path)

    unicode_text = "café ☕ · naïve façade · 日本語のテスト · emoji 🎉🚀 end"
    payload = _SamplePayload(text=unicode_text)

    ref = asyncio.run(store.put_artifact(execution_id, payload))
    assert ref.artifact_id == ref.sha256

    # Publishing identical content again must reuse the same hash/ref, never
    # duplicate or rewrite the file.
    ref_again = asyncio.run(store.put_artifact(execution_id, payload))
    assert ref_again == ref

    # Page through in small chunks and reconstruct byte-for-byte.
    collected = ""
    offset = 0
    pages = 0
    page: dict[str, object] = {}
    while True:
        page = asyncio.run(store.read_artifact(execution_id, ref.artifact_id, offset=offset, limit=7))
        collected += page["content"]  # type: ignore[operator]
        pages += 1
        if page["eof"]:
            assert page["next_offset"] is None
            break
        offset = page["next_offset"]  # type: ignore[assignment]
        assert pages < 1000  # guard against an infinite-loop regression

    assert pages > 1  # confirms real pagination happened, not a single shot
    # `collected` is the exact canonical-JSON snapshot; decoding it must
    # reproduce the original Unicode text byte-for-byte.
    assert json.loads(collected) == {"text": unicode_text}
    assert hashlib.sha256(collected.encode("utf-8")).hexdigest() == ref.sha256
    assert page["sha256"] == ref.sha256
    assert page["size_bytes"] == ref.size_bytes

    # Cross-execution reads are confined: the same artifact_id was never
    # emitted under this OTHER execution_id.
    with pytest.raises(FileNotFoundError):
        asyncio.run(store.read_artifact(other_execution_id, ref.artifact_id, offset=0, limit=64))

    # Path-traversal-shaped artifact ids are rejected outright, never resolved.
    for bad_artifact_id in ("../../etc/passwd", "not-a-hash", ref.artifact_id + "/../x", ""):
        with pytest.raises(ValueError):
            asyncio.run(store.read_artifact(execution_id, bad_artifact_id, offset=0, limit=64))

    # A symlink planted where a legitimate artifact should live is rejected.
    outside_secret = tmp_path / "outside_secret.json"
    outside_secret.write_text('{"leak": true}', encoding="utf-8")
    fake_sha = "0" * 64
    artifacts_dir = tmp_path / "executions" / execution_id / "artifacts"
    (artifacts_dir / f"{fake_sha}.json").symlink_to(outside_secret)
    with pytest.raises(ValueError):
        asyncio.run(store.read_artifact(execution_id, fake_sha, offset=0, limit=64))

    # Invalid offsets/limits are rejected before touching the filesystem.
    with pytest.raises(ValueError):
        asyncio.run(store.read_artifact(execution_id, ref.artifact_id, offset=-1, limit=64))
    with pytest.raises(ValueError):
        asyncio.run(store.read_artifact(execution_id, ref.artifact_id, offset=0, limit=0))
    with pytest.raises(ValueError):
        asyncio.run(store.read_artifact(execution_id, ref.artifact_id, offset=0, limit=16385))
    with pytest.raises(ValueError):
        asyncio.run(store.read_artifact(execution_id, ref.artifact_id, offset=10_000_000, limit=64))


def test_evidence_survives_temp_worktree_deletion(tmp_path: Path) -> None:
    """Evidence published under the durable root outlives a deleted worktree checkout (AC7)."""
    durable_root = tmp_path / "durable-root"
    ephemeral_worktree = tmp_path / "worktrees" / "feat-demo"
    ephemeral_worktree.mkdir(parents=True)

    resolved_root = resolve_durable_root(str(durable_root), worktree_base_path=str(ephemeral_worktree))
    assert ephemeral_worktree not in resolved_root.parents
    assert resolved_root != ephemeral_worktree

    execution_id = str(uuid.uuid4())
    store = ExecutionEvidenceStore(root=resolved_root)
    event = _make_event(execution_id, "evt-durable", payload={"note": "outlives worktree"})
    ref = asyncio.run(store.append_event(event))
    assert ref.relative_path == f"executions/{execution_id}/events.jsonl"

    # The worktree checkout is removed, exactly as `git worktree remove` would.
    shutil.rmtree(ephemeral_worktree)

    events_path = resolved_root / "executions" / execution_id / "events.jsonl"
    assert events_path.exists()
    assert "evt-durable" in events_path.read_text(encoding="utf-8")
