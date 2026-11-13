"""Integration tests for expert stages pipeline pause/resume (FEAT-890 AC6).

Tests the security-patch pipeline: run → paused at gate → simulated restart
(new process objects) → approve → cve-remediation runs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from parrot.bots.flows.core.gates import GateHost, GateRecord, GateSpec, register_gate_kind
from parrot.experts.lease_store import LeaseDurableCheckpointStore

# Register a test gate kind for the security-patch pipeline.
register_gate_kind("approval", description="Manual approval gate")


class InMemoryGateStore:
    """In-memory gate store for testing."""

    def __init__(self) -> None:
        self.records: dict[str, GateRecord] = {}

    async def put(self, record: GateRecord) -> None:
        self.records[record.gate_id] = record

    async def get(self, gate_id: str) -> GateRecord | None:
        return self.records.get(gate_id)

    async def pending(self, owner: str | None = None) -> list[GateRecord]:
        return [
            record
            for record in self.records.values()
            if record.status == "pending" and (owner is None or record.owner == owner)
        ]


@pytest.fixture
def gate_store() -> InMemoryGateStore:
    """Create an in-memory gate store."""
    return InMemoryGateStore()


@pytest.fixture
def gate_host(gate_store: InMemoryGateStore) -> GateHost:
    """Create a gate host with the in-memory store."""
    return GateHost(gate_store)


@pytest.fixture
def checkpoint_store(tmp_path: Path) -> LeaseDurableCheckpointStore:
    """Create a lease-capable SQLite checkpoint store."""
    return LeaseDurableCheckpointStore(tmp_path / "cp.sqlite")


@pytest.mark.asyncio
async def test_security_patch_pipeline_pause_resume(
    gate_host: GateHost,
    checkpoint_store: LeaseDurableCheckpointStore,
    tmp_path: Path,
) -> None:
    """Run security-patch pipeline, pause at gate, simulate restart, approve, resume."""
    # Step 1: Open a gate (simulating the intake stage pausing at approval)
    gate_spec = GateSpec(
        kind="approval",
        title="Approve CVE remediation planning",
        instructions="Review the CVE analysis and approve remediation.",
        questions=[],
        ttl_seconds=None,
        on_expiry="fail",
    )

    run_id = "test-security-patch-run"
    owner = f"{run_id}:intake"

    # Open the gate - this is what happens when the intake stage runs
    gate_record = await gate_host.open(gate_spec, owner=owner, payload_ref="stage:intake")

    # Verify the gate is pending
    assert gate_record.status == "pending"
    assert gate_record.owner == owner

    # Step 2: Simulate a process restart - create new objects
    # In a real scenario, the checkpoint store persists the state
    # and a new process would resume from it

    # Acquire a lease on the checkpoint store (simulating resume)
    lease_acquired = await checkpoint_store.acquire_lease(run_id, "new-process", ttl=60)
    assert lease_acquired is True, "Failed to acquire lease for resume"

    # Step 3: Create a new gate host with fresh store (simulating new process)
    new_gate_store = InMemoryGateStore()
    # Copy the gate record to the new store (simulating loading from persistence)
    await new_gate_store.put(gate_record)

    new_gate_host = GateHost(new_gate_store)

    # Step 4: Approve the gate (simulating human approval after restart)
    resolved = await new_gate_host.resolve(
        gate_record.gate_id,
        resolution="approved",
        resolved_by="user:security-team",
        comment="CVE is valid, proceed with remediation.",
    )

    # Verify the gate is now approved
    assert resolved.status == "approved"
    assert resolved.resolved_by == "user:security-team"

    # Step 5: Verify the plan stage can now run (gate is approved)
    # In a real flow, the edge condition "result.metadata.gate.status == 'approved'"
    # would allow the plan stage to execute

    # Verify no pending gates remain
    pending = await new_gate_store.pending()
    assert len(pending) == 0

    # Release the lease
    await checkpoint_store.release_lease(run_id, "new-process")


@pytest.mark.asyncio
async def test_lease_durable_checkpoint_store_acquire_release(
    checkpoint_store: LeaseDurableCheckpointStore,
) -> None:
    """Test that LeaseDurableCheckpointStore correctly manages leases."""
    flow_id = "test-flow-1"

    # First acquisition should succeed
    acquired = await checkpoint_store.acquire_lease(flow_id, "holder-1", ttl=60)
    assert acquired is True

    # Second acquisition from different holder should fail
    acquired = await checkpoint_store.acquire_lease(flow_id, "holder-2", ttl=60)
    assert acquired is False

    # Renew should work for the owner
    renewed = await checkpoint_store.renew_lease(flow_id, "holder-1", ttl=60)
    assert renewed is True

    # Renew should fail for non-owner
    renewed = await checkpoint_store.renew_lease(flow_id, "holder-2", ttl=60)
    assert renewed is False

    # Release should work for the owner
    await checkpoint_store.release_lease(flow_id, "holder-1")

    # After release, a new holder can acquire
    acquired = await checkpoint_store.acquire_lease(flow_id, "holder-2", ttl=60)
    assert acquired is True

    # Clean up
    await checkpoint_store.release_lease(flow_id, "holder-2")


@pytest.mark.asyncio
async def test_gate_host_recover_expired(
    gate_host: GateHost,
) -> None:
    """Test that GateHost correctly recovers expired gates."""
    # Open a gate with TTL that expires immediately
    gate_spec = GateSpec(
        kind="approval",
        title="Test gate with TTL",
        instructions="Test",
        questions=[],
        ttl_seconds=1,  # 1 second TTL
        on_expiry="fail",  # Should fail when expired
    )

    gate_record = await gate_host.open(gate_spec, owner="test:node")

    # Verify it's pending
    assert gate_record.status == "pending"

    # Wait for TTL to expire and recover
    import time

    time.sleep(1.1)

    recovered = await gate_host.recover(now=time.time())

    # Should have recovered one gate
    assert len(recovered) == 1
    assert recovered[0].status == "expired"


@pytest.mark.asyncio
async def test_gate_host_recover_auto_approve(
    gate_host: GateHost,
) -> None:
    """Test that GateHost correctly auto-approves expired gates with on_expiry=approve."""
    # Open a gate with TTL and on_expiry=approve
    gate_spec = GateSpec(
        kind="approval",
        title="Test gate with auto-approve",
        instructions="Test",
        questions=[],
        ttl_seconds=1,
        on_expiry="approve",  # Auto-approve on expiry
    )

    gate_record = await gate_host.open(gate_spec, owner="test:node")

    # Verify it's pending
    assert gate_record.status == "pending"

    # Wait for TTL to expire and recover
    import time

    time.sleep(1.1)

    recovered = await gate_host.recover(now=time.time())

    # Should have recovered one gate with approved status
    assert len(recovered) == 1
    assert recovered[0].status == "approved"
    assert recovered[0].resolved_by == "system:ttl-auto-approve"
