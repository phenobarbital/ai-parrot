"""CliRunner tests for `parrot experts` (FEAT-890 TASK-5627). Fake experts, no LLM, no Redis."""

from __future__ import annotations

import re
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner

from parrot.bots.flows.core.checkpoint.model import FlowCheckpoint
from parrot.bots.flows.core.checkpoint.store.base import CheckpointStore
from parrot.experts import cli as experts_cli
from parrot.experts.stages import node as stage_node

# ── fakes ─────────────────────────────────────────────────────────────────


class FakeCheckpointStore(CheckpointStore):
    """In-memory CheckpointStore with the full contract (leases included)."""

    def __init__(self) -> None:
        self.by_flow: dict[str, list[FlowCheckpoint]] = {}
        self.leases: dict[str, str] = {}

    async def put(self, checkpoint: FlowCheckpoint) -> None:
        history = self.by_flow.setdefault(checkpoint.flow_id, [])
        history[:] = [c for c in history if c.checkpoint_id != checkpoint.checkpoint_id]
        history.append(checkpoint)
        history.sort(key=lambda c: c.checkpoint_id)

    async def latest(self, flow_id: str) -> FlowCheckpoint | None:
        history = self.by_flow.get(flow_id, [])
        return history[-1] if history else None

    async def get(self, flow_id: str, checkpoint_id: int) -> FlowCheckpoint | None:
        return next((c for c in self.by_flow.get(flow_id, []) if c.checkpoint_id == checkpoint_id), None)

    async def history(self, flow_id: str, limit: int = 10) -> list[FlowCheckpoint]:
        return list(reversed(self.by_flow.get(flow_id, [])))[:limit]

    async def list_flows(self, status: str | None = None) -> list[dict[str, Any]]:
        return [{"flow_id": flow_id, "status": h[-1].status} for flow_id, h in self.by_flow.items() if h]

    async def delete_flow(self, flow_id: str) -> None:
        self.by_flow.pop(flow_id, None)

    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        if flow_id in self.leases:
            return False
        self.leases[flow_id] = holder
        return True

    async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        return self.leases.get(flow_id) == holder

    async def release_lease(self, flow_id: str, holder: str) -> None:
        if self.leases.get(flow_id) == holder:
            del self.leases[flow_id]

    async def close(self) -> None:
        pass


class FakeExpert:
    """ExpertAgent stand-in with a canned answer."""

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
        self.tenants: list[str | None] = []

    def get(self, name: str, *, tenant: str | None = None) -> FakeExpert:
        self.tenants.append(tenant)
        return self.experts[name]


class FakeAgentRegistry:
    """AgentRegistry stand-in (compiled scopes carry no ``agent`` nodes)."""

    def get_bot_instance(self, name: str) -> Any:
        return None


# ── fixtures ──────────────────────────────────────────────────────────────


_REAL_CHECKPOINT_STORE = experts_cli._checkpoint_store


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    """Wire fake experts and an in-memory checkpoint store into the CLI."""
    analyst = FakeExpert("cve-analyst", "triage: CVE-2024-0001 is exploitable", ["validate", "write", "review"])
    remediation = FakeExpert("cve-remediation", "plan: upgrade libfoo to 2.1", ["write"])
    registry = FakeRegistry(analyst, remediation)
    store = FakeCheckpointStore()

    async def _registries(agents_dir: Path | None) -> tuple[Any, Any]:
        return FakeAgentRegistry(), registry

    async def _no_episode(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(experts_cli, "_build_registries", _registries)
    monkeypatch.setattr(experts_cli, "_checkpoint_store", lambda name, gate_db=None: store)
    monkeypatch.setattr(stage_node, "record_episode", _no_episode)
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    base = ["--agents-dir", str(agents_dir), "--gate-db", str(tmp_path / "gates.sqlite")]
    return SimpleNamespace(
        analyst=analyst,
        remediation=remediation,
        registry=registry,
        store=store,
        agents_dir=agents_dir,
        base=base,
        runner=CliRunner(),
    )


def _invoke(env: SimpleNamespace, *args: str) -> Any:
    return env.runner.invoke(experts_cli.experts, [*env.base, *args], catch_exceptions=False)


def _run_and_gate(env: SimpleNamespace, *extra: str) -> tuple[str, str]:
    result = _invoke(env, "run", "--scope", "security-patch", "--input", "patch CVE-2024-0001", *extra)
    assert result.exit_code == 0, result.output
    run_id = re.search(r"run ([0-9a-f]{32}) paused", result.output).group(1)
    gate_id = re.search(r"gate ([0-9a-f]{32}) \[approval\]", result.output).group(1)
    return run_id, gate_id


# ── tests ─────────────────────────────────────────────────────────────────


def test_help_lists_commands_through_parrot_cli() -> None:
    """`parrot experts --help` resolves via the lazy map and lists every command."""
    from parrot.cli import cli

    result = CliRunner().invoke(cli, ["experts", "--help"])

    assert result.exit_code == 0, result.output
    for command in ("scopes", "run", "gates", "approve", "reject", "resume"):
        assert command in result.output


def test_scopes_lists_bundled_scopes(env: SimpleNamespace) -> None:
    result = _invoke(env, "scopes")

    assert result.exit_code == 0
    assert "security-patch" in result.output
    assert "intake -> plan" in result.output


def test_run_pauses_at_gate_and_resume_continues_after_approve(env: SimpleNamespace) -> None:
    run_id, gate_id = _run_and_gate(env, "--tenant", "acme")

    assert len(env.analyst.prompts) == 1
    assert env.remediation.prompts == []
    assert gate_id in _invoke(env, "gates").output

    premature = env.runner.invoke(experts_cli.experts, [*env.base, "resume", "--run-id", run_id])
    assert premature.exit_code != 0
    assert "still pending" in premature.output
    assert env.remediation.prompts == []

    approved = _invoke(env, "approve", gate_id, "--comment", "go")
    assert approved.exit_code == 0
    assert f"gate {gate_id} approved" in approved.output
    assert "no pending gates" in _invoke(env, "gates").output

    resumed = _invoke(env, "resume", "--run-id", run_id)

    assert resumed.exit_code == 0, resumed.output
    assert f"run {run_id} completed" in resumed.output
    assert "plan: upgrade libfoo to 2.1" in resumed.output
    assert len(env.analyst.prompts) == 1  # the gated stage is never re-executed
    assert len(env.remediation.prompts) == 1
    assert "CVE-2024-0001 is exploitable" in env.remediation.prompts[0]
    assert env.registry.tenants[-1] == "acme"  # tenant survives the restart via the checkpoint

    again = env.runner.invoke(experts_cli.experts, [*env.base, "resume", "--run-id", run_id])
    assert again.exit_code != 0
    assert "already completed" in again.output


def test_rejected_gate_halts_the_run(env: SimpleNamespace) -> None:
    run_id, gate_id = _run_and_gate(env)

    assert _invoke(env, "reject", gate_id).exit_code == 0
    resumed = env.runner.invoke(experts_cli.experts, [*env.base, "resume", "--run-id", run_id])

    assert resumed.exit_code != 0
    assert "rejected" in resumed.output
    assert env.remediation.prompts == []


def test_checkpoint_carries_only_projected_shared_data(env: SimpleNamespace) -> None:
    run_id, gate_id = _run_and_gate(env)

    checkpoint = env.store.by_flow[run_id][-1]
    shared = checkpoint.context.shared_data

    assert set(shared) <= {"run_id", "tenant", "scope", "pending_gates"}
    assert shared["pending_gates"] == {"intake": gate_id}
    assert shared["scope"] == "security-patch"
    assert checkpoint.context.initial_task == "patch CVE-2024-0001"


def test_resolving_unknown_gate_fails(env: SimpleNamespace) -> None:
    result = env.runner.invoke(experts_cli.experts, [*env.base, "approve", "missing"])

    assert result.exit_code != 0
    assert "NOT_FOUND" in result.output


def test_unknown_scope_and_unknown_run_fail(env: SimpleNamespace) -> None:
    scope = env.runner.invoke(experts_cli.experts, [*env.base, "run", "--scope", "nope", "--input", "x"])
    run = env.runner.invoke(experts_cli.experts, [*env.base, "resume", "--run-id", "nope"])

    assert scope.exit_code != 0 and "unknown scope 'nope'" in scope.output
    assert run.exit_code != 0 and "no checkpoint for run nope" in run.output


def test_input_from_file(env: SimpleNamespace, tmp_path: Path) -> None:
    source = tmp_path / "task.md"
    source.write_text("patch from file", encoding="utf-8")

    result = _invoke(env, "run", "--scope", "security-patch", "--input", f"@{source}")

    assert result.exit_code == 0, result.output
    assert len(env.analyst.prompts) == 1
    assert env.analyst.prompts[0].startswith("patch from file")


def test_scope_compilation_runs_off_the_event_loop_thread(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """compile_scope/load_scopes are blocking: they run via asyncio.to_thread."""
    seen: dict[str, int] = {}
    real_compile = experts_cli.compile_scope
    real_load = experts_cli.load_scopes

    def _compile(*args: Any, **kwargs: Any) -> Any:
        seen["compile"] = threading.get_ident()
        return real_compile(*args, **kwargs)

    def _load(*args: Any, **kwargs: Any) -> Any:
        seen["load"] = threading.get_ident()
        return real_load(*args, **kwargs)

    monkeypatch.setattr(experts_cli, "compile_scope", _compile)
    monkeypatch.setattr(experts_cli, "load_scopes", _load)

    _run_and_gate(env)

    main = threading.get_ident()
    assert seen["compile"] != main
    assert seen["load"] != main


def test_sqlite_checkpoint_store_needs_no_redis_and_resumes(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--checkpoint-store sqlite`` checkpoints a real run through the lease-capable local store."""
    monkeypatch.setattr(experts_cli, "_checkpoint_store", _REAL_CHECKPOINT_STORE)
    env.base = [*env.base, "--checkpoint-store", "sqlite"]  # group option, before the subcommand
    run_id, gate_id = _run_and_gate(env)
    assert (Path(env.base[3]).parent / "checkpoints.sqlite").exists()

    assert _invoke(env, "approve", gate_id).exit_code == 0
    resumed = _invoke(env, "resume", "--run-id", run_id)

    assert resumed.exit_code == 0, resumed.output
    assert f"run {run_id} completed" in resumed.output
    assert len(env.analyst.prompts) == 1  # the gated stage is not re-run after restart
    assert len(env.remediation.prompts) == 1
