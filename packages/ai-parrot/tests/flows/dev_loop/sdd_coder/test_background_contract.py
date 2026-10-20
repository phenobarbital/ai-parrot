"""FEAT-699 supervisor wiring for declared contracts, cache, and baseline verdicts."""

from __future__ import annotations

import json
import sys
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from parrot.flows.dev_loop.sdd_coder import background as background_module
from parrot.flows.dev_loop.sdd_coder.background import BackgroundRegistry, ValidationSupervisor
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.test_scope.contract import contract_to_header, parse_spec_contract
from parrot.flows.dev_loop.test_scope.datatypes import BaselineVerdict, Invocation, ScopePlan, TestTarget


def _supervisor(tmp_path: Path) -> tuple[ValidationSupervisor, BackgroundRegistry, Path]:
    """Build a supervisor with isolated evidence and worktree roots."""
    store = ExecutionEvidenceStore(root=tmp_path / "evidence")
    registry = BackgroundRegistry(store=store, owner_instance_id="owner-contract")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    return ValidationSupervisor(registry=registry, store=store), registry, worktree


def _index(worktree: Path, *, malformed: bool = False) -> Path:
    """Write one task and per-spec index carrying a deterministic test contract."""
    task_file = worktree / "task.md"
    task_file.write_text(
        "# Task\n\n## Validation Commands\n\n- `pytest tests/test_declared.py -q`\n",
        encoding="utf-8",
    )
    contract = parse_spec_contract("### Validation Contract\n\ntests:\n- tests/test_contract.py\nmarkers: none\n")
    assert contract is not None
    header = {
        "feature": "demo",
        "feature_id": "FEAT-699",
        "base_branch": "dev",
        "tasks": [{"id": "TASK-4451", "file": "task.md"}],
        "test_contract": contract_to_header(contract),
    }
    if malformed:
        header["test_contract"]["schema"] = 999
    index_path = worktree / "index.json"
    index_path.write_text(json.dumps(header), encoding="utf-8")
    return index_path


def _plan(argv: tuple[str, ...] = ("pytest", "tests/test_declared.py"), *, tier: str = "merge") -> ScopePlan:
    """Return one cacheable invocation plan."""
    target = TestTarget(path="tests/test_declared.py", distribution="root", reason="declared")
    invocation = Invocation(distribution="root", argv=argv, targets=(target,))
    return ScopePlan(
        tier=tier,
        invocations=(invocation,),
        escalated=(),
        core_hits=(),
        skipped_escalations=(),
        notes=(),
        mode="contract",
    )


async def test_supervisor_passes_declared_and_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The selected task commands and index contract reach ``plan_tests`` together."""
    supervisor, _registry, worktree = _supervisor(tmp_path)
    index_path = _index(worktree)
    captured: dict[str, object] = {}

    monkeypatch.setattr(background_module, "changed_files", lambda *_args: [])

    def fake_plan_tests(**kwargs):
        captured.update(kwargs)
        return _plan()

    monkeypatch.setattr(background_module, "plan_tests", fake_plan_tests)
    monkeypatch.setattr(background_module.green_cache, "filter_cached", lambda _worktree, plan, **_kwargs: plan)

    await supervisor._plan_selection(
        worktree=worktree,
        tier="merge",
        index_path=index_path,
        task_ids=["TASK-4451"],
        feature_id="FEAT-699",
    )

    assert captured["declared"] == [["pytest", "tests/test_declared.py", "-q"]]
    assert captured["contract"].pytest.targets == ("tests/test_contract.py",)


async def test_malformed_contract_is_admission_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed index contract raises before any child process is spawned."""
    supervisor, _registry, worktree = _supervisor(tmp_path)
    index_path = _index(worktree, malformed=True)
    spawned = False

    async def fake_spawn(*_args, **_kwargs):
        nonlocal spawned
        spawned = True

    monkeypatch.setattr(background_module.asyncio, "create_subprocess_exec", fake_spawn)
    with pytest.raises(ValueError, match="unsupported schema"):
        await supervisor.start(
            feature="demo",
            worktree=worktree,
            execution_id=str(uuid.uuid4()),
            task_ids=["TASK-4451"],
            tier="merge",
            timeout_seconds=60,
            request_id="malformed",
            index_path=index_path,
        )
    assert spawned is False


async def test_merge_validation_uses_green_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Merge selection filters cached targets and renders them in the selection header."""
    supervisor, _registry, worktree = _supervisor(tmp_path)
    index_path = _index(worktree)
    calls: list[str] = []
    monkeypatch.setattr(background_module, "changed_files", lambda *_args: [])
    monkeypatch.setattr(background_module, "plan_tests", lambda **_kwargs: _plan())

    def fake_filter(_worktree, plan, **kwargs):
        calls.append(kwargs["namespace"])
        return replace(plan, cached=("tests/test_declared.py",), invocations=())

    monkeypatch.setattr(background_module.green_cache, "filter_cached", fake_filter)
    selected = await supervisor._plan_selection(
        worktree=worktree,
        tier="merge",
        index_path=index_path,
        task_ids=["TASK-4451"],
        feature_id="FEAT-699",
    )

    assert len(calls) == 1
    assert "# cached: tests/test_declared.py" in supervisor._selection_header(selected)


async def test_feature_tier_is_fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Feature-tier selection never consults the green cache."""
    supervisor, _registry, worktree = _supervisor(tmp_path)
    index_path = _index(worktree)
    monkeypatch.setattr(background_module, "changed_files", lambda *_args: [])
    monkeypatch.setattr(background_module, "plan_tests", lambda **_kwargs: _plan(tier="feature"))

    def unexpected_filter(*_args, **_kwargs):
        pytest.fail("feature-tier validation must be fresh")

    monkeypatch.setattr(background_module.green_cache, "filter_cached", unexpected_filter)
    selected = await supervisor._plan_selection(
        worktree=worktree,
        tier="feature",
        index_path=index_path,
        task_ids=["TASK-4451"],
        feature_id="FEAT-699",
    )
    assert selected.cached == ()


_JUNIT_FAILURE_CHILD = (
    "import sys;"
    "p=[x for x in sys.argv if x.startswith('--junitxml=')][0].split('=',1)[1];"
    "open(p,'w').write(\"<testsuites><testsuite tests='1' failures='1'>"
    "<testcase file='tests/test_declared.py' classname='tests.test_declared' name='test_red'>"
    '<failure/></testcase></testsuite></testsuites>");'
    "sys.exit(1)"
)


async def _run_baseline_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, verdict: str, request_id: str
) -> tuple[str | None, str]:
    """Run one synthetic failing invocation and return terminal outcome plus log text."""
    supervisor, registry, worktree = _supervisor(tmp_path)
    index_path = _index(worktree)
    monkeypatch.setenv("SDD_TEST_REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(background_module, "changed_files", lambda *_args: [])
    argv = (sys.executable, "-c", _JUNIT_FAILURE_CHILD)
    monkeypatch.setattr(background_module, "plan_tests", lambda **_kwargs: _plan(argv))
    monkeypatch.setattr(background_module.green_cache, "filter_cached", lambda _worktree, plan, **_kwargs: plan)
    monkeypatch.setattr(background_module.green_cache, "record_green", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(background_module, "protected_argv", lambda _cwd, command: list(command))
    monkeypatch.setattr(
        background_module.baseline,
        "classify_failures",
        lambda **kwargs: tuple(BaselineVerdict(nodeid, verdict) for nodeid in kwargs["failed_nodeids"]),
    )

    execution_id = str(uuid.uuid4())
    registration = await supervisor.start(
        feature="demo",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-4451"],
        tier="merge",
        timeout_seconds=60,
        request_id=request_id,
        index_path=index_path,
    )
    await supervisor.wait(execution_id, registration.handle, 15)
    status = await registry.status(execution_id, registration.handle)
    return status.outcome, supervisor._log_path(execution_id, registration.handle).read_text(encoding="utf-8")


async def test_baseline_red_only_settles_completed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing invocation with only known baseline reds passes the terminal gate."""
    outcome, log = await _run_baseline_case(tmp_path, monkeypatch, verdict="baseline_red", request_id="baseline")
    assert outcome == "completed"
    assert "# baseline: only baseline reds — gate passes" in log


async def test_new_red_settles_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A branch-only new red remains a terminal validation failure."""
    outcome, log = await _run_baseline_case(tmp_path, monkeypatch, verdict="new_red", request_id="new-red")
    assert outcome == "failed"
    assert "only baseline reds" not in log


async def test_index_path_none_preserves_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Legacy callers still plan without declarations or a contract."""
    supervisor, _registry, worktree = _supervisor(tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr(background_module, "changed_files", lambda *_args: [])

    def fake_plan_tests(**kwargs):
        captured.update(kwargs)
        return _plan()

    monkeypatch.setattr(background_module, "plan_tests", fake_plan_tests)
    await supervisor._plan_selection(worktree=worktree, tier="merge")
    assert "declared" not in captured
    assert "contract" not in captured
