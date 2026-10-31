"""FEAT-783 TASK-4992 — engine attribution end to end (AC-10, spec §4 Integration)."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from parrot.core.events.lifecycle import AfterClientCallEvent, TraceContext, get_global_registry
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import RosterSeat
from parrot.observability.recorders.spec_usage import read_spec_usage

from .test_engine_dispatch import FakeDispatcher, _roster


class EmittingDispatcher(FakeDispatcher):
    """FakeDispatcher that emits one AfterClientCallEvent through the wired resolver."""

    def __init__(self, behaviour: str = "ok") -> None:
        super().__init__(behaviour)
        self._resolver = None
        self.resolver_wired = False

    def set_event_registry_resolver(self, resolver) -> None:
        self._resolver = resolver
        self.resolver_wired = resolver is not None

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None, labels=None):
        if self._resolver is not None:
            registry = self._resolver(run_id)
            if registry is not None:
                # Mirrors claude.py::_emit_usage_event (emit, then forward_to_global).
                event = AfterClientCallEvent(
                    trace_context=TraceContext.new_root(),
                    client_name="claude-code",
                    model="m",
                    duration_ms=1.0,
                    input_tokens=11,
                    output_tokens=7,
                )
                await registry.emit(event)
                registry.forward_to_global(event)
        return await super().dispatch(
            brief=brief,
            profile=profile,
            output_model=output_model,
            run_id=run_id,
            node_id=node_id,
            cwd=cwd,
            session_host=session_host,
            labels=labels,
        )


def _builder(dispatchers: list):
    from parrot.flows.dev_loop.models import LLMCodeDispatchProfile

    def _build(spec, *, redis_url, max_concurrent, stream_ttl_seconds):
        d = EmittingDispatcher()
        dispatchers.append(d)
        return d, LLMCodeDispatchProfile()

    return _build


@pytest.fixture
def noop_probe():
    from parrot.flows.dev_loop.sdd_coder.roster import RosterProbe

    return RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/usr/bin/" + b, smoke=None)


async def test_attempt_produces_attributed_durable_row(git_sandbox_feature, noop_probe, tmp_path) -> None:
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    telemetry_dir = tmp_path / "telemetry"
    dispatchers: list = []
    engine = SddCoderEngine(
        roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=_builder(dispatchers),
        telemetry_dir=str(telemetry_dir),
    )
    try:
        job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
        result = await engine.wait(job.job_id, 10)
        task = result.tasks[0]
        assert task.outcome == "merged"
        assert any(d.resolver_wired for d in dispatchers)
        attempt = task.attempts[0]
        await asyncio.sleep(0.05)
        await engine.aclose()

        root = telemetry_dir / "spec-usage"
        rows = read_spec_usage(root, "FEAT-549")
        assert len(rows) == 1, "exactly one durable row per emitted event (no double delivery)"
        row = rows[0]
        assert row.feat_id == "FEAT-549"
        assert row.task_id == "TASK-0001"
        assert row.attempt_uid == attempt.attempt_uid
        assert row.roster_seat == attempt.seat_label
        assert row.dispatch_kind in {"in-process", "cli", "sdk"}
        assert row.input_tokens == 11

        # Readable by a second process (AC-10).
        code = (
            "import sys; from pathlib import Path;"
            "from parrot.observability.recorders.spec_usage import read_spec_usage;"
            "r = read_spec_usage(Path(sys.argv[1]), 'FEAT-549'); print('ROWS', len(r), r[0].attempt_uid)"
        )
        src = str(Path(__file__).resolve().parents[4] / "src")
        out = subprocess.run(
            [sys.executable, "-c", code, str(root)],
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "PYTHONPATH": src},
            check=True,
        )
        marker = [ln for ln in out.stdout.splitlines() if ln.startswith("ROWS ")]
        assert marker and marker[-1].split() == ["ROWS", "1", attempt.attempt_uid]
    finally:
        await engine.aclose()


async def test_telemetry_disabled_registers_no_sink(git_sandbox_feature, noop_probe) -> None:
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    dispatchers: list = []
    registry = get_global_registry()
    before = len(getattr(registry, "_subscriptions", []))
    engine = SddCoderEngine(
        roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=_builder(dispatchers),
    )
    try:
        job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
        result = await engine.wait(job.job_id, 10)
        assert result.tasks[0].outcome == "merged"
        assert engine._usage_subscriber is None
        assert not any(d.resolver_wired for d in dispatchers)
        assert len(getattr(registry, "_subscriptions", [])) == before
    finally:
        await engine.aclose()


def test_attribution_dispatch_kind_per_backend() -> None:
    from types import SimpleNamespace

    engine = SddCoderEngine.__new__(SddCoderEngine)
    ctx = SimpleNamespace(feature_id="FEAT-1")
    task = SimpleNamespace(task_id="TASK-1")
    kinds = {}
    for backend in ("claude-code", "codex", "nova"):
        seat = RosterSeat(label="a", backend=backend, model="m")  # type: ignore[arg-type]
        attr = engine._usage_attribution_for(ctx, task, seat, attempt_uid="u", execution_id="")
        kinds[backend] = attr.dispatch_kind
        assert attr.accounting_seat == "development.sdd-coder-a"
        assert attr.execution_id is None
    assert kinds == {"claude-code": "sdk", "codex": "cli", "nova": "in-process"}


async def test_usage_sink_released_when_idle_and_kept_while_owned(noop_probe, tmp_path) -> None:
    """issue:b293d771587b — the global subscription is dropped once no execution owns a worktree."""
    registry = get_global_registry()
    before = len(getattr(registry, "_subscriptions", []))
    engine = SddCoderEngine(
        roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
        probe=noop_probe,
        worktree_base_path=str(tmp_path / "worktrees"),
        telemetry_dir=str(tmp_path / "telemetry"),
    )
    try:
        assert engine._ensure_usage_sink() is True
        assert len(getattr(registry, "_subscriptions", [])) > before

        engine._execution_owners["/wt"] = "exec-1"
        await engine._release_usage_sink_if_idle()
        assert engine._usage_subscriber is not None, "sink must stay while an execution owns a worktree"

        engine._execution_owners.clear()
        await engine._release_usage_sink_if_idle()
        assert engine._usage_subscriber is None
        assert len(getattr(registry, "_subscriptions", [])) == before

        assert engine._ensure_usage_sink() is True, "re-registers lazily for the next execution"
    finally:
        await engine.aclose()
