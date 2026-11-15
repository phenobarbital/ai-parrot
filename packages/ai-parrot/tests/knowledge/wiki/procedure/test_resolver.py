"""Tests for the procedure resolver and the SDD probe runner (FEAT-891)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.knowledge.wiki.procedure.models import ProbeCheck, ProcedureSpec
from parrot.knowledge.wiki.procedure.resolver import resolve
from parrot.sdd.scripts import procedure_probes
from parrot.sdd.scripts.procedure_probes import PROBE_COSTS, SddProbeRunner, scope_for


class FakeRunner:
    """Answer checks from a probe-value table with selected remote probes."""

    def __init__(self, values: dict[str, bool | None], remote: tuple[str, ...] = ()) -> None:
        """Store deterministic probe values and their remote classification."""
        self.values = values
        self.remote = remote

    def cost(self, probe: str) -> str | None:
        """Return the fake probe cost, or None for an unknown probe."""
        return None if probe not in self.values else ("remote" if probe in self.remote else "local")

    def run(self, check: ProbeCheck, scope: object) -> bool | None:
        """Return the configured value for the check's probe."""
        del scope
        return self.values[check.probe]


def _graph() -> list[ProcedureSpec]:
    """Return spec -> task -> start -> task-close, matching the SDD graph shape."""
    return [
        ProcedureSpec(
            id="sdd:spec",
            title="Write specification",
            kind="command",
            done_when=[ProbeCheck(probe="spec.exists")],
        ),
        ProcedureSpec(
            id="sdd:task",
            title="Create tasks",
            kind="command",
            preconditions=[ProbeCheck(probe="task.depends_done")],
            done_when=[ProbeCheck(probe="index.exists")],
            requires_procedures=["sdd:spec"],
        ),
        ProcedureSpec(
            id="sdd:start",
            title="Start task",
            kind="command",
            done_when=[ProbeCheck(probe="task.status", expect="in-progress|done|done-with-issues")],
            requires_procedures=["sdd:task"],
        ),
        ProcedureSpec(
            id="sdd:task-close",
            title="Close task",
            kind="command",
            mode="mandatory",
            done_when=[ProbeCheck(probe="task.status", expect="done|done-with-issues")],
            requires_procedures=["sdd:start"],
        ),
    ]


def test_resolver_next_without_history() -> None:
    """A completed spec and incomplete task make the task the sole next node."""
    runner = FakeRunner(
        {
            "spec.exists": True,
            "index.exists": False,
            "task.depends_done": True,
            "task.status": False,
        }
    )

    resolution = resolve(_graph(), {"feature": "demo", "task": "TASK-1"}, runner)

    assert [item.spec.id for item in resolution.next] == ["sdd:task"]
    assert resolution.next[0].done is False
    assert resolution.next[0].ready is True
    assert resolution.next[0].preconditions[0].value is True
    assert [spec.id for spec in resolution.mandatory] == ["sdd:task-close"]


def test_resolver_remote_unknown_when_disallowed() -> None:
    """Disallowed remote probes are unknown and are never dispatched."""

    class RemoteMustNotRun(FakeRunner):
        """Fail if the resolver dispatches the remote check."""

        def run(self, check: ProbeCheck, scope: object) -> bool | None:
            """Reject every invocation because the remote probe is disabled."""
            raise AssertionError(f"unexpected remote probe call: {check.probe}, {scope}")

    spec = ProcedureSpec(
        id="sdd:push",
        title="Push branch",
        kind="command",
        preconditions=[ProbeCheck(probe="branch.pushed")],
        done_when=[ProbeCheck(probe="branch.pushed")],
    )
    resolution = resolve(
        [spec],
        {"branch": "feat-FEAT-1-demo"},
        RemoteMustNotRun({"branch.pushed": True}, remote=("branch.pushed",)),
        allow_remote=False,
    )

    assert resolution.next[0].done is None
    assert resolution.next[0].preconditions[0].value is None
    assert resolution.next[0].preconditions[0].cost == "remote"
    assert resolution.next[0].preconditions[0].detail


def test_resolver_is_deterministic() -> None:
    """Equal state yields equal resolutions ordered mandatory first and then by id."""
    specs = [
        ProcedureSpec(id="sdd:z", title="Z", kind="command"),
        ProcedureSpec(id="sdd:b", title="B", kind="rule", mode="mandatory"),
        ProcedureSpec(id="sdd:a", title="A", kind="command"),
        ProcedureSpec(id="sdd:constraint", title="Constraint", kind="rule", mode="constraint"),
    ]
    runner = FakeRunner({})

    first = resolve(specs, {"feature": "demo"}, runner, stale=True)
    second = resolve(specs, {"feature": "demo"}, runner, stale=True)

    assert first == second
    assert [item.spec.id for item in first.next] == ["sdd:b", "sdd:a", "sdd:z"]
    assert [spec.id for spec in first.mandatory] == ["sdd:b"]
    assert first.stale is True


def test_probe_costs_cover_the_table() -> None:
    """PROBE_COSTS has exactly the nine probes of spec section 2."""
    assert PROBE_COSTS == {
        "spec.exists": "local",
        "index.exists": "local",
        "task.status": "local",
        "task.depends_done": "local",
        "feature.tasks_done": "local",
        "flow.base_allowed": "local",
        "env.not_worker_sandbox": "local",
        "branch.pushed": "remote",
        "pr.open": "remote",
    }


def test_scope_for_from_branch_and_arguments(tmp_path: Path) -> None:
    """Feature scope accepts a slug or FEAT id and otherwise derives from branch or task."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    head = git_dir / "HEAD"
    head.write_text("ref: refs/heads/feat-FEAT-1-demo\n", encoding="utf-8")
    index_dir = tmp_path / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True)
    (index_dir / "demo.json").write_text(
        json.dumps({"feature": "demo", "feature_id": "FEAT-1", "tasks": [{"id": "TASK-1"}]}),
        encoding="utf-8",
    )

    expected = {"feature": "demo", "branch": "feat-FEAT-1-demo"}
    assert scope_for(tmp_path) == expected
    assert scope_for(tmp_path, feature="demo") == expected
    assert scope_for(tmp_path, feature="FEAT-1") == expected

    head.write_text("ref: refs/heads/dev\n", encoding="utf-8")
    assert scope_for(tmp_path, task="TASK-1") == {
        "feature": "demo",
        "task": "TASK-1",
        "branch": "dev",
    }


def test_runner_remote_probe_failure_is_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeouts and missing remote-probe binaries produce unknown results."""
    runner = SddProbeRunner(tmp_path)

    def timeout(*args: object, **kwargs: object) -> object:
        """Raise the timeout shape emitted by subprocess.run."""
        del args, kwargs
        raise procedure_probes.subprocess.TimeoutExpired("git", runner.timeout)

    monkeypatch.setattr(procedure_probes.subprocess, "run", timeout)
    assert runner.run(ProbeCheck(probe="branch.pushed"), {}) is None

    def missing(*args: object, **kwargs: object) -> object:
        """Raise the missing-binary shape emitted by subprocess.run."""
        del args, kwargs
        raise FileNotFoundError("gh")

    monkeypatch.setattr(procedure_probes.subprocess, "run", missing)
    assert runner.run(ProbeCheck(probe="pr.open"), {"branch": "feat-FEAT-1-demo"}) is None
