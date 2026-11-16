"""Integration tests for expert stages pipeline pause/resume (FEAT-890 AC6).

Tests the security-patch pipeline: run → paused at gate → simulated restart
(new process objects) → approve → cve-remediation runs.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner

from parrot.bots.flows.core.gates import GateHost, GateRecord, GateSpec, register_gate_kind
from parrot.experts import cli as experts_cli
from parrot.experts.cli import EXPERT_GATE_KINDS
from parrot.experts.lease_store import LeaseDurableCheckpointStore
from parrot.experts.stages import node as stage_node

# The gate kind registry is process-wide and rejects a different description for the same kind,
# so every test registers the CLI's canonical one.
register_gate_kind("approval", description=EXPERT_GATE_KINDS["approval"])


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


class FakeExpert:
    """ExpertAgent stand-in with a canned answer (no LLM)."""

    def __init__(self, name: str, answer: str, capabilities: list[str]) -> None:
        self.bundle = SimpleNamespace(
            manifest=SimpleNamespace(name=name, tier=SimpleNamespace(value="balanced"), capabilities=capabilities)
        )
        self.answer = answer
        self.prompts: list[str] = []
        self.model_config = SimpleNamespace(model="fake-model")

    async def ask(self, question: str, **kwargs: Any) -> Any:
        self.prompts.append(question)
        return SimpleNamespace(content=self.answer)


class FakeRegistry:
    """ExpertRegistry stand-in with a sync ``get``."""

    def __init__(self, *experts: FakeExpert) -> None:
        self.experts = {expert.bundle.manifest.name: expert for expert in experts}
        self.wiki_toolkit = None

    def get(self, name: str, *, tenant: str | None = None) -> FakeExpert:
        return self.experts[name]


class FakeAgentRegistry:
    """AgentRegistry stand-in (compiled scopes carry no ``agent`` nodes)."""

    def get_bot_instance(self, name: str) -> Any:
        return None


def test_security_patch_pipeline_pause_resume(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Bundled scope, real SQLite gate + checkpoint stores: run pauses at the gate, a restart, approve, resume.

    Every CLI invocation builds all of its objects afresh, so each one is a process restart. The only fakes
    are the experts (no LLM) and the registries that hand them out.
    """
    analyst = FakeExpert("cve-analyst", "triage: CVE-2024-0001 is exploitable", ["validate", "write", "review"])
    remediation = FakeExpert("cve-remediation", "plan: upgrade libfoo to 2.1", ["write"])
    registry = FakeRegistry(analyst, remediation)

    async def _registries(agents_dir: Path | None) -> tuple[Any, Any]:
        return FakeAgentRegistry(), registry

    async def _no_episode(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(experts_cli, "_build_registries", _registries)
    monkeypatch.setattr(stage_node, "record_episode", _no_episode)
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    base = [
        "--agents-dir",
        str(agents_dir),
        "--gate-db",
        str(tmp_path / "gates.sqlite"),
        "--checkpoint-store",
        "sqlite",
    ]
    runner = CliRunner()

    def invoke(*args: str) -> Any:
        return runner.invoke(experts_cli.experts, [*base, *args], catch_exceptions=False)

    run = invoke("run", "--scope", "security-patch", "--input", "patch CVE-2024-0001")
    assert run.exit_code == 0, run.output
    run_id = re.search(r"run ([0-9a-f]{32}) paused", run.output).group(1)
    gate_id = re.search(r"gate ([0-9a-f]{32}) \[approval\]", run.output).group(1)
    # Paused at the gate: the analyst ran, the remediation stage did not.
    assert len(analyst.prompts) == 1
    assert remediation.prompts == []

    # Resuming before approval is refused and still runs nothing.
    refused = runner.invoke(experts_cli.experts, [*base, "resume", "--run-id", run_id])
    assert refused.exit_code != 0
    assert remediation.prompts == []

    assert invoke("approve", gate_id, "--comment", "CVE is valid").exit_code == 0
    resumed = invoke("resume", "--run-id", run_id)

    assert resumed.exit_code == 0, resumed.output
    assert f"run {run_id} completed" in resumed.output
    assert len(analyst.prompts) == 1  # the gated stage is not re-run after the restart
    assert len(remediation.prompts) == 1  # cve-remediation runs once the gate is approved
    assert "CVE-2024-0001 is exploitable" in remediation.prompts[0]  # and it received the analyst's output


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

    # Recover at a clock past the TTL instead of sleeping: recover() takes an explicit ``now``.
    recovered = await gate_host.recover(now=gate_record.expires_at + 1)

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

    # Recover at a clock past the TTL instead of sleeping: recover() takes an explicit ``now``.
    recovered = await gate_host.recover(now=gate_record.expires_at + 1)

    # Should have recovered one gate with approved status
    assert len(recovered) == 1
    assert recovered[0].status == "approved"
    assert recovered[0].resolved_by == "system:ttl-auto-approve"
