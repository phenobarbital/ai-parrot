"""Real runner/verify E2E evidence rejection scenarios (TASK-3547, M5/M9).

Unlike ``tests/unit/e2e/test_evidence.py`` (which hand-crafts an
:class:`~parrot.e2e.models.E2EVerdict` to exercise ``verify_evidence`` in
isolation), every scenario here drives the real process-boundary through
:func:`parrot.e2e.runner.run_plan`: a real ``python -m pytest -p
parrot.e2e.pytest_plugin`` child process, spawned by the real runner, against
a synthetic Git checkout built fresh under ``tmp_path``. Only the target
supervisor is faked for the cleanup-failure scenario (there is no real
target adapter this suite can start without external service prerequisites);
the pytest subprocess boundary itself is never faked.

Covers the frozen scenario ``required-evidence-rejections`` (spec-declared
``e2e.scenario_ids``) via the single frozen node ID
``test_required_evidence_rejections``: source tampering, evidence/log
artifact tampering, a required scenario whose only outcome is a skip, and a
target cleanup failure are all confirmed as real rejections -- never a
fabricated PASS -- from both the runner's own persisted verdict and
``verify_evidence``'s independent, read-only re-evaluation.
"""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pytest
import yaml

from parrot.e2e import runner as runner_module
from parrot.e2e.errors import E2EEvidenceError
from parrot.e2e.evidence import verify_evidence
from parrot.e2e.models import ProcessIdentity, RunState, TargetConfig
from parrot.e2e.runner import run_plan

_FEATURE_ID = "FEAT-581"
_SPEC_RELATIVE = "sdd/specs/agentic-e2e-testing.spec.md"
_PLAN_RELATIVE = "sdd/state/e2e-plan.md"
_FIXTURE_MODULE = "tests_fixture/test_synthetic.py"


# ---------------------------------------------------------------------------
# Synthetic Git checkout: a real repo, never the actual project checkout.
# ---------------------------------------------------------------------------


def _run(argv: list[str], *, cwd: Path) -> None:
    subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _run(["git", "init"], cwd=root)
    _run(["git", "config", "user.email", "e2e-test@example.com"], cwd=root)
    _run(["git", "config", "user.name", "E2E Test"], cwd=root)


def _commit_all(root: Path, message: str = "commit") -> None:
    _run(["git", "add", "-A"], cwd=root)
    _run(["git", "commit", "-m", message], cwd=root)


def _write_frontmatter(path: Path, data: dict[str, Any], *, body: str = "Rationale.\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = yaml.safe_dump(data, sort_keys=False)
    path.write_text(f"---\n{frontmatter}---\n\n{body}", encoding="utf-8")


def _write_fixture_module(root: Path) -> None:
    """Write one real, trivial pytest module the runner's subprocess collects.

    ``test_passes`` always passes; ``test_gets_skipped`` always skips -- the
    real subprocess boundary for the required-skip rejection scenario.
    """
    module_path = root / _FIXTURE_MODULE
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(
        "import pytest\n\n\n"
        "def test_passes() -> None:\n"
        "    assert True\n\n\n"
        "def test_gets_skipped() -> None:\n"
        "    pytest.skip('intentionally skipped: required-skip rejection coverage')\n",
        encoding="utf-8",
    )


def _plan_data(*, scenario_id: str, node_id: str, target_ids: Optional[list[str]] = None) -> dict[str, Any]:
    return {
        "feature_id": _FEATURE_ID,
        "spec_path": _SPEC_RELATIVE,
        "policy": "required",
        "targets": {"fixture-target": {"kind": "mcp-stdio"}} if target_ids else {},
        "scenarios": [
            {
                "id": scenario_id,
                "tier": "deterministic",
                "target_ids": target_ids or [],
                "required": True,
                "node_ids": [node_id],
            }
        ],
    }


@pytest.fixture
def git_worktree(tmp_path: Path) -> Path:
    """A minimal, real Git checkout with a committed spec and fixture module."""
    root = tmp_path / "worktree"
    root.mkdir()
    _init_repo(root)
    _write_frontmatter(
        root / _SPEC_RELATIVE,
        {"type": "feature", "base_branch": "dev", "projects": ["ai-parrot-server"], "tags": ["e2e"]},
    )
    _write_fixture_module(root)
    _commit_all(root)
    return root


def _write_plan(worktree: Path, **kwargs: Any) -> Path:
    plan_path = worktree / _PLAN_RELATIVE
    _write_frontmatter(plan_path, _plan_data(**kwargs))
    _commit_all(worktree, "add e2e plan")
    return plan_path


# ---------------------------------------------------------------------------
# A fake target supervisor -- only used for the cleanup-failure scenario.
# The pytest subprocess the runner spawns is always real (never faked here).
# ---------------------------------------------------------------------------


@dataclass
class _FakeSupervisor:
    """Minimal ``E2ESupervisor``-shaped fake that always fails teardown."""

    worktree: Path
    owner_id: str
    feature_id: str

    def __post_init__(self) -> None:
        self._runs: dict[str, str] = {}

    async def start(self, target_id: str, _config: TargetConfig) -> RunState:
        run_id = f"run-{target_id}-{uuid.uuid4().hex[:8]}"
        self._runs[run_id] = target_id
        identity = _fake_process_identity()
        return RunState(
            feature_id=self.feature_id,
            run_id=run_id,
            worktree=str(self.worktree),
            owner_id=self.owner_id,
            controller_identity=identity,
            supervisor_identity=identity,
            process_identity=identity,
            target_id=target_id,
            status="ready",
            control_socket=str(self.worktree / "control.sock"),
            started_at=_now(),
            deadline=_now(),
            log_path=str(self.worktree / "fixture.log"),
        )

    async def stop(self, run_id: str) -> RunState:
        target_id = self._runs.pop(run_id, "fixture-target")
        identity = _fake_process_identity()
        return RunState(
            feature_id=self.feature_id,
            run_id=run_id,
            worktree=str(self.worktree),
            owner_id=self.owner_id,
            controller_identity=identity,
            supervisor_identity=identity,
            process_identity=identity,
            target_id=target_id,
            status="stopped",
            control_socket=str(self.worktree / "control.sock"),
            started_at=_now(),
            deadline=_now(),
            log_path=str(self.worktree / "fixture.log"),
            shutdown_forced=True,
            cleanup_complete=False,
        )


def _fake_process_identity() -> ProcessIdentity:
    from datetime import datetime, timezone

    return ProcessIdentity(pid=1, pgid=1, create_time=datetime.now(timezone.utc), boot_id="boot", owned=True)


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# The frozen node ID: real runner + real verify rejection coverage.
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_required_evidence_rejections(git_worktree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Source tampering, log tampering, required skips and cleanup failures never pass.

    Every sub-scenario below drives the real :func:`run_plan` (a genuine
    ``python -m pytest`` child process) and then confirms the real
    :func:`verify_evidence` rejects the resulting evidence -- never a
    fabricated PASS, matching spec §2's coverage/staleness/cleanup gates.
    """
    owner_id = f"pytest-e2e-{uuid.uuid4().hex}"

    # -- Baseline: a genuinely passing run, used by the tampering scenarios --
    plan_path = _write_plan(
        git_worktree, scenario_id="scn-pass", node_id=f"{_FIXTURE_MODULE}::test_passes"
    )
    verdict = await run_plan(plan_path, worktree=git_worktree, owner_id=owner_id)
    assert verdict.status == "PASS"
    assert verdict.exit_code == 0
    assert verdict.artifact_hashes, "runner must record at least one hashed evidence artifact"

    baseline_result = await verify_evidence(plan_path, worktree=git_worktree)
    assert baseline_result.status == "PASS"
    assert baseline_result.gate_satisfied is True

    # -- Log/artifact tampering: mutate the persisted pytest bridge artifact --
    evidence_dir = git_worktree / "sdd" / "state" / _FEATURE_ID / "e2e" / "runs" / verdict.run_id
    artifact_relative_path = next(iter(verdict.artifact_hashes))
    artifact_path = evidence_dir / artifact_relative_path
    original_bytes = artifact_path.read_bytes()
    artifact_path.write_bytes(original_bytes + b"\ntampered")

    with pytest.raises(E2EEvidenceError) as artifact_excinfo:
        await verify_evidence(plan_path, worktree=git_worktree)
    assert artifact_excinfo.value.reason_code == "evidence_artifact_tampered"

    # Restore the artifact before testing source tampering in isolation.
    artifact_path.write_bytes(original_bytes)
    restored_result = await verify_evidence(plan_path, worktree=git_worktree)
    assert restored_result.status == "PASS"

    # -- Source tampering: mutate a tracked source file after the run --
    tampered_source = git_worktree / _FIXTURE_MODULE
    original_fixture_source = tampered_source.read_bytes()
    tampered_source.write_text(tampered_source.read_text(encoding="utf-8") + "\n# mutated after the run\n")

    with pytest.raises(E2EEvidenceError) as source_excinfo:
        await verify_evidence(plan_path, worktree=git_worktree)
    assert source_excinfo.value.reason_code == "source_identity_stale"

    # Restore before the next sub-scenario builds its own independent plan.
    tampered_source.write_bytes(original_fixture_source)

    # -- Required skip: the only required node is skipped, never a PASS --
    skip_plan_path = _write_plan(
        git_worktree, scenario_id="scn-skip", node_id=f"{_FIXTURE_MODULE}::test_gets_skipped"
    )
    skip_verdict = await run_plan(skip_plan_path, worktree=git_worktree, owner_id=owner_id)
    assert skip_verdict.status != "PASS", "a required-but-skipped node must never be recorded as a passing run"

    skip_result = await verify_evidence(skip_plan_path, worktree=git_worktree)
    assert skip_result.status == "BLOCKED"
    assert skip_result.gate_satisfied is False
    assert "no_codified_scenario_executed" in skip_result.reason_codes

    # -- Cleanup failure: the target supervisor never confirms teardown --
    cleanup_plan_path = _write_plan(
        git_worktree,
        scenario_id="scn-cleanup",
        node_id=f"{_FIXTURE_MODULE}::test_passes",
        target_ids=["fixture-target"],
    )
    monkeypatch.setattr(runner_module, "E2ESupervisor", _FakeSupervisor)
    cleanup_verdict = await run_plan(cleanup_plan_path, worktree=git_worktree, owner_id=owner_id)
    assert cleanup_verdict.status == "FAIL"
    assert cleanup_verdict.cleanup_results
    assert not all(cleanup_verdict.cleanup_results.values())

    cleanup_result = await verify_evidence(cleanup_plan_path, worktree=git_worktree)
    assert cleanup_result.status == "FAIL"
    assert cleanup_result.gate_satisfied is False
    assert "cleanup_incomplete" in cleanup_result.reason_codes
