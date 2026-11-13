"""`parrot experts` CLI (FEAT-890).

Operator entry point for scope grids: compile a scope into an ``AgentsFlow``,
run it until a stage gate opens, resolve the gate, and resume the run.

Persistence:

* **Gates** go through :func:`resolve_gate_store` — the SQLite store under
  ``parrot_home()`` unless another backend is configured (no Redis needed).
* **Run state** uses AgentsFlow's own checkpointing
  (``AgentsFlow.from_definition(..., checkpoint=True)``); the run id is the
  checkpoint ``flow_id``, and ``resume`` rebuilds the run with
  ``AgentsFlow.resume``. Only an allowlisted projection of
  ``FlowContext.shared_data`` is checkpointed — the live expert registry and
  gate host never reach the store.

A gated stage completes with its gate pending and the compiler's gate edge
holds every downstream stage, so ``run`` returns with the run paused.
``resume`` refuses to continue while a gate of the run is pending, rejected or
expired: the definition-driven resume path re-dispatches every node whose
upstream completed, so the gate check here is what keeps a rejected stage from
flowing downstream.
"""

from __future__ import annotations

import asyncio
import getpass
import logging
import uuid
from pathlib import Path
from typing import Any, Literal

import click

from parrot.bots.flows.core.checkpoint.store.base import CheckpointStore
from parrot.bots.flows.core.checkpoint.store.factory import get_checkpoint_store
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.gates import GateError, GateHost, GateRecord, GateStore, register_gate_kind
from parrot.bots.flows.core.gates.stores import resolve_gate_store
from parrot.bots.flows.core.result import NodeResult
from parrot.bots.flows.flow.definition import FlowDefinition
from parrot.bots.flows.flow.flow import AgentsFlow
from parrot.experts.grid.compiler import compile_scope
from parrot.experts.grid.loader import load_scopes
from parrot.experts.grid.models import ScopeGrid, ScopeGridError
from parrot.experts.stages.node import (
    EXPERT_REGISTRY_KEY,
    GATE_HOST_KEY,
    PENDING_GATES_KEY,
    RUN_ID_KEY,
    TENANT_KEY,
)

logger = logging.getLogger(__name__)

#: Gate kinds the experts host registers (bundled scopes gate on ``approval``).
EXPERT_GATE_KINDS: dict[str, str] = {"approval": "Human approval between expert stages"}

#: ``shared_data`` key carrying the scope name of a run.
SCOPE_KEY = "scope"

#: ``shared_data`` keys persisted in checkpoints (plain, JSON-safe values only).
_CHECKPOINTED_KEYS: tuple[str, ...] = (RUN_ID_KEY, TENANT_KEY, SCOPE_KEY, PENDING_GATES_KEY)

_SENTINEL_NODES = frozenset({"__start__", "__end__"})
_END_NODE = "__end__"


# ── collaborators (module-level so hosts and tests can substitute them) ──────


def _register_gate_kinds() -> None:
    """Register the gate kinds used by expert scopes (idempotent)."""
    for kind, description in EXPERT_GATE_KINDS.items():
        register_gate_kind(kind, description=description)


async def _build_registries(agents_dir: Path | None) -> tuple[Any, Any]:
    """Build the agent registry and load the expert registry into it.

    Args:
        agents_dir: Agents directory, or ``None`` for the configured default.

    Returns:
        ``(agent_registry, expert_registry)``.

    Raises:
        click.ClickException: When the experts could not be loaded.
    """
    from parrot.experts.bootstrap import load_experts  # noqa: PLC0415
    from parrot.registry import AgentRegistry  # noqa: PLC0415

    agent_registry = AgentRegistry(agents_dir=agents_dir) if agents_dir is not None else AgentRegistry()
    experts = await load_experts(agent_registry, agents_dir=agents_dir)
    if experts is None:
        raise click.ClickException("experts could not be loaded (see the log for details)")
    return agent_registry, experts


def _gate_store(gate_db: Path | None) -> GateStore:
    """Resolve the gate store (SQLite default when no Redis client is configured).

    Args:
        gate_db: Optional SQLite path overriding the ``parrot_home()`` default.

    Returns:
        The gate store.
    """
    return resolve_gate_store(sqlite_path=gate_db)


def _checkpoint_store(name: str | None) -> CheckpointStore:
    """Resolve the AgentsFlow checkpoint store holding run state.

    Args:
        name: Backend name; ``None`` uses ``FLOW_CHECKPOINT_STORE``.

    Returns:
        The checkpoint store.
    """
    return get_checkpoint_store(name)


def _project_shared_data(ctx: FlowContext) -> dict[str, Any]:
    """Return the allowlisted, JSON-safe part of ``shared_data`` to checkpoint."""
    shared = ctx.shared_data
    projected = {key: shared[key] for key in _CHECKPOINTED_KEYS if key in shared}
    if PENDING_GATES_KEY in projected:
        projected[PENDING_GATES_KEY] = {str(k): str(v) for k, v in dict(projected[PENDING_GATES_KEY]).items()}
    return projected


def _build_flow(
    definition: FlowDefinition, agent_registry: Any, store: CheckpointStore, run_id: str
) -> AgentsFlow:
    """Materialize a checkpointed flow for one run.

    Args:
        definition: The compiled scope.
        agent_registry: Registry used for agent resolution.
        store: Checkpoint store.
        run_id: Run identifier, used as the checkpoint ``flow_id``.

    Returns:
        The configured flow.
    """
    flow = AgentsFlow.from_definition(
        definition,
        agent_registry=agent_registry,
        checkpoint=True,
        checkpoint_store=store,
        flow_id=run_id,
    )
    # from_definition() has no projector parameter; the constructor attribute is
    # what both run_flow() and resume() read (flow.py `_checkpoint_shared_data_arg`).
    flow._checkpoint_shared_data_arg = _project_shared_data
    return flow


# ── helpers ──────────────────────────────────────────────────────────────


def _read_input(value: str) -> str:
    """Return the run input: literal text, or a file's content for ``@path``."""
    if not value.startswith("@"):
        return value
    path = Path(value[1:]).expanduser()
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise click.BadParameter(f"cannot read input file {path}: {exc}", param_hint="--input") from exc


def _answer_of(value: Any) -> str:
    """Extract the textual answer of a stage result."""
    if isinstance(value, NodeResult):
        return _answer_of(value.result)
    if isinstance(value, dict) and "result" in value:
        return _answer_of(value["result"])
    for attr in ("content", "output"):
        inner = getattr(value, attr, None)
        if inner is not None:
            return str(inner)
    return "" if value is None else str(value)


def _final_answer(ctx: FlowContext) -> str:
    """Return the answer of the last completed stage of a run."""
    for node_id in reversed(ctx.completion_order):
        if node_id not in _SENTINEL_NODES and node_id in ctx.results:
            return _answer_of(ctx.results[node_id])
    return ""


def _shared_data(
    extra: dict[str, Any], *, registry: Any, host: GateHost, run_id: str, tenant: str | None
) -> dict[str, Any]:
    """Assemble the live ``shared_data`` for a run (fresh, empty pending-gate map)."""
    return {
        **extra,
        EXPERT_REGISTRY_KEY: registry,
        GATE_HOST_KEY: host,
        RUN_ID_KEY: run_id,
        TENANT_KEY: tenant,
        PENDING_GATES_KEY: {},
    }


async def _report(run_id: str, ctx: FlowContext, host: GateHost) -> None:
    """Echo the outcome of a run: failed, paused at gates, or completed.

    Raises:
        click.ClickException: When a stage failed.
    """
    if ctx.errors:
        details = "; ".join(f"{node}: {exc}" for node, exc in ctx.errors.items())
        raise click.ClickException(f"run {run_id} failed: {details}")
    pending: list[GateRecord] = []
    for gate_id in dict(ctx.shared_data.get(PENDING_GATES_KEY) or {}).values():
        record = await host.store.get(gate_id)
        if record is not None and record.status == "pending":
            pending.append(record)
    if pending:
        click.echo(f"run {run_id} paused")
        for record in pending:
            click.echo(f"  gate {record.gate_id} [{record.kind}] {record.spec.title}")
        click.echo(f"approve with `parrot experts approve <gate_id>`, then `parrot experts resume --run-id {run_id}`")
        return
    click.echo(f"run {run_id} completed")
    answer = _final_answer(ctx)
    if answer:
        click.echo(answer)


# ── async bodies ─────────────────────────────────────────────────────────


async def _run_scope(
    scope: str,
    text: str,
    tenant: str | None,
    *,
    agents_dir: Path | None,
    gate_db: Path | None,
    checkpoint_store: str | None,
) -> None:
    """Compile ``scope`` and run it until it completes or pauses at a gate."""
    _register_gate_kinds()
    scopes: dict[str, ScopeGrid] = await asyncio.to_thread(load_scopes, agents_dir)
    grid = scopes.get(scope)
    if grid is None:
        known = ", ".join(sorted(scopes)) or "none"
        raise click.ClickException(f"unknown scope {scope!r} (known: {known})")
    agent_registry, registry = await _build_registries(agents_dir)
    try:
        definition = await asyncio.to_thread(compile_scope, grid, registry=registry)
    except ScopeGridError as exc:
        raise click.ClickException(str(exc)) from exc

    run_id = uuid.uuid4().hex
    host = GateHost(_gate_store(gate_db))
    flow = _build_flow(definition, agent_registry, _checkpoint_store(checkpoint_store), run_id)
    ctx = FlowContext(initial_task=text, agent_registry=agent_registry)
    ctx.shared_data.update(
        _shared_data({SCOPE_KEY: scope}, registry=registry, host=host, run_id=run_id, tenant=tenant)
    )
    click.echo(f"run {run_id} started (scope {scope})")
    await flow.run_flow(ctx)
    await _report(run_id, ctx, host)


async def _resume_run(
    run_id: str,
    *,
    agents_dir: Path | None,
    gate_db: Path | None,
    checkpoint_store: str | None,
) -> None:
    """Resume a paused run once every gate it waits on is approved."""
    _register_gate_kinds()
    store = _checkpoint_store(checkpoint_store)
    checkpoint = await store.latest(run_id)
    if checkpoint is None:
        raise click.ClickException(f"no checkpoint for run {run_id}")
    if _END_NODE in checkpoint.context.completed_tasks:
        raise click.ClickException(f"run {run_id} already completed")

    host = GateHost(_gate_store(gate_db))
    await host.recover()
    saved = dict(checkpoint.context.shared_data or {})
    for gate_id in dict(saved.get(PENDING_GATES_KEY) or {}).values():
        record = await host.store.get(str(gate_id))
        if record is None:
            raise click.ClickException(f"gate {gate_id} of run {run_id} not found in the gate store")
        if record.status == "pending":
            raise click.ClickException(f"gate {gate_id} is still pending; approve or reject it first")
        if record.status != "approved":
            raise click.ClickException(f"run {run_id} halted: gate {gate_id} is {record.status}")

    tenant = saved.get(TENANT_KEY)
    agent_registry, registry = await _build_registries(agents_dir)
    ctx = FlowContext(initial_task=checkpoint.context.initial_task, agent_registry=agent_registry)
    extra = {SCOPE_KEY: saved[SCOPE_KEY]} if SCOPE_KEY in saved else {}
    ctx.shared_data.update(_shared_data(extra, registry=registry, host=host, run_id=run_id, tenant=tenant))
    flow = await AgentsFlow.resume(
        run_id,
        agent_registry=agent_registry,
        store=store,
        flow_factory=lambda definition: _build_flow(definition, agent_registry, store, run_id),
        seed_context=ctx,
    )
    click.echo(f"run {run_id} resumed")
    await flow.run_flow()
    await _report(run_id, ctx, host)


async def _list_gates(gate_db: Path | None) -> list[GateRecord]:
    """Apply expiry policies, then return the pending gates."""
    host = GateHost(_gate_store(gate_db))
    await host.recover()
    return await host.store.pending()


async def _resolve_gate(
    gate_id: str, resolution: Literal["approved", "rejected"], comment: str, resolved_by: str, gate_db: Path | None
) -> GateRecord:
    """Resolve one gate through the GateHost."""
    _register_gate_kinds()
    host = GateHost(_gate_store(gate_db))
    try:
        return await host.resolve(gate_id, resolution, resolved_by=resolved_by, comment=comment)
    except GateError as exc:
        raise click.ClickException(str(exc)) from exc


# ── click commands ───────────────────────────────────────────────────────


@click.group(name="experts")
@click.option(
    "--agents-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Agents directory holding experts/ and experts/scopes/ (default: configured AGENTS_DIR).",
)
@click.option(
    "--gate-db",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="SQLite gate store path (default: <parrot home>/gates.sqlite).",
)
@click.option(
    "--checkpoint-store",
    default=None,
    help="AgentsFlow checkpoint backend for run state (default: FLOW_CHECKPOINT_STORE).",
)
@click.pass_context
def experts(ctx: click.Context, agents_dir: Path | None, gate_db: Path | None, checkpoint_store: str | None) -> None:
    """Run expert scopes and resolve their gates."""
    ctx.ensure_object(dict)
    ctx.obj.update(agents_dir=agents_dir, gate_db=gate_db, checkpoint_store=checkpoint_store)


@experts.command("scopes")
@click.pass_context
def scopes_cmd(ctx: click.Context) -> None:
    """List the scopes available to `parrot experts run`."""
    try:
        scopes = load_scopes(ctx.obj["agents_dir"])
    except ScopeGridError as exc:
        raise click.ClickException(str(exc)) from exc
    if not scopes:
        click.echo("no scopes found")
        return
    for name, grid in sorted(scopes.items()):
        stages = " -> ".join(stage.stage for stage in grid.stages)
        click.echo(f"{name}: {grid.description}" if grid.description else name)
        click.echo(f"  stages: {stages}")


@experts.command("run")
@click.option("--scope", required=True, help="Scope name (see `parrot experts scopes`).")
@click.option("--input", "input_", required=True, help="Task text, or @path to read it from a file.")
@click.option("--tenant", default=None, help="Tenant forwarded to expert resolution.")
@click.pass_context
def run_cmd(ctx: click.Context, scope: str, input_: str, tenant: str | None) -> None:
    """Compile a scope and run it; the run pauses at the first open gate."""
    text = _read_input(input_)
    asyncio.run(
        _run_scope(
            scope,
            text,
            tenant,
            agents_dir=ctx.obj["agents_dir"],
            gate_db=ctx.obj["gate_db"],
            checkpoint_store=ctx.obj["checkpoint_store"],
        )
    )


@experts.command("gates")
@click.pass_context
def gates_cmd(ctx: click.Context) -> None:
    """List pending gates."""
    records = asyncio.run(_list_gates(ctx.obj["gate_db"]))
    if not records:
        click.echo("no pending gates")
        return
    for record in records:
        click.echo(f"{record.gate_id}  [{record.kind}]  {record.owner}  {record.spec.title}")


def _resolve_command(ctx: click.Context, gate_id: str, resolution: Literal["approved", "rejected"], comment: str) -> None:
    """Shared body of `approve` / `reject`."""
    resolved_by = f"cli:{getpass.getuser()}"
    record = asyncio.run(_resolve_gate(gate_id, resolution, comment, resolved_by, ctx.obj["gate_db"]))
    click.echo(f"gate {record.gate_id} {record.status} by {record.resolved_by}")


@experts.command("approve")
@click.argument("gate_id")
@click.option("--comment", default="", help="Optional comment recorded on the gate.")
@click.pass_context
def approve_cmd(ctx: click.Context, gate_id: str, comment: str) -> None:
    """Approve a pending gate."""
    _resolve_command(ctx, gate_id, "approved", comment)


@experts.command("reject")
@click.argument("gate_id")
@click.option("--comment", default="", help="Optional comment recorded on the gate.")
@click.pass_context
def reject_cmd(ctx: click.Context, gate_id: str, comment: str) -> None:
    """Reject a pending gate; its run halts."""
    _resolve_command(ctx, gate_id, "rejected", comment)


@experts.command("resume")
@click.option("--run-id", required=True, help="Run id printed by `parrot experts run`.")
@click.pass_context
def resume_cmd(ctx: click.Context, run_id: str) -> None:
    """Resume a paused run after its gates were approved."""
    asyncio.run(
        _resume_run(
            run_id,
            agents_dir=ctx.obj["agents_dir"],
            gate_db=ctx.obj["gate_db"],
            checkpoint_store=ctx.obj["checkpoint_store"],
        )
    )
