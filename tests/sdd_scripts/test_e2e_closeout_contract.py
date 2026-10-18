"""Behavioral contract for FEAT-581 M7 (TASK-3543): required E2E evidence
before both SDD closeout surfaces (`.claude/commands/sdd-done.md` Step 4.6,
`.agents/skills/sdd-done/SKILL.md` step 4.5) may stamp, push, open a PR,
merge or clean up a feature.

This is deliberately NOT a set of string-only assertions that mirror the
docs' own prose. ``evaluate_closeout_gate`` is imported from
``scripts/sdd/check_e2e_closeout.py`` -- the gate both closeout surfaces
actually invoke (FEAT-703) -- and is proven here against the real
``parrot.e2e.evidence.verify_evidence`` validator (TASK-3523) fed
realistic, on-disk evidence artifacts built the same way
``packages/ai-parrot-server/tests/unit/e2e/test_evidence.py`` builds them --
never a mocked validator and never a fabricated ``VerificationResult``.

Before FEAT-703 this module defined its own task-local copy of the decision
table, so the suite certified a reimplementation rather than the shipped
gate; that copy is gone and exactly one definition now exists, in
``scripts/sdd/``. The doc-surface checks at the bottom confirm the two
closeout hosts delegate to that gate and keep the "force never bypasses
required" contract, rather than restating the table in prose.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]

# `parrot.e2e` ships from the ai-parrot-server distribution; add this
# worktree's own source tree explicitly (see test_e2e_spec_contract.py for
# the same convention) so `pytest tests/sdd_scripts/test_e2e_closeout_contract.py -q`
# works exactly as the task's Validation Commands state, with no extra env setup.
_SERVER_SRC = _REPO_ROOT / "packages" / "ai-parrot-server" / "src"
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))

from parrot.e2e.errors import E2EConfigError, E2EEvidenceError  # noqa: E402
from parrot.e2e.evidence import capture_identity, verify_evidence  # noqa: E402
from parrot.e2e.models import E2EVerdict, ScenarioResult, SourceIdentity, VerificationResult  # noqa: E402
from parrot.e2e.plan import load_plan  # noqa: E402

from scripts.sdd.check_e2e_closeout import evaluate_closeout_gate  # noqa: E402

_SDD_DONE_COMMAND = _REPO_ROOT / ".claude" / "commands" / "sdd-done.md"
_SDD_DONE_SKILL = _REPO_ROOT / ".agents" / "skills" / "sdd-done" / "SKILL.md"
_DOC_SURFACES = (_SDD_DONE_COMMAND, _SDD_DONE_SKILL)

_FEATURE_ID = "FEAT-581"
_SPEC_RELATIVE = "sdd/specs/example.spec.md"
_PLAN_RELATIVE = f"sdd/state/{_FEATURE_ID}/e2e-plan.md"
_REQUIRED_NODE_ID = "tests/e2e/test_mcp_stdio.py::test_roundtrip"
_SCENARIO_ID = "scn-mcp-stdio"
_RUN_ID = "run-1"


# ---------------------------------------------------------------------------
# Synthetic Git checkout + plan/spec frontmatter helpers (mirrors
# packages/ai-parrot-server/tests/unit/e2e/test_evidence.py's own convention)
# ---------------------------------------------------------------------------


def _run(argv: list[str], *, cwd: Path) -> None:
    subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _run(["git", "init"], cwd=root)
    _run(["git", "config", "user.email", "e2e-closeout-test@example.com"], cwd=root)
    _run(["git", "config", "user.name", "E2E Closeout Test"], cwd=root)


def _commit_all(root: Path, message: str = "commit") -> None:
    _run(["git", "add", "-A"], cwd=root)
    _run(["git", "commit", "-m", message], cwd=root)


def _write_frontmatter(path: Path, data: dict[str, Any], *, body: str = "Rationale.\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = yaml.safe_dump(data, sort_keys=False)
    path.write_text(f"---\n{frontmatter}---\n\n{body}", encoding="utf-8")


def _plan_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "feature_id": _FEATURE_ID,
        "spec_path": _SPEC_RELATIVE,
        "policy": "required",
        "targets": {"stdio": {"kind": "mcp-stdio"}},
        "scenarios": [
            {
                "id": _SCENARIO_ID,
                "tier": "deterministic",
                "target_ids": ["stdio"],
                "required": True,
                "node_ids": [_REQUIRED_NODE_ID],
            }
        ],
    }
    data.update(overrides)
    return data


@pytest.fixture
def git_worktree(tmp_path: Path) -> Path:
    """A minimal, real Git checkout with a committed spec + required plan."""
    root = tmp_path / "worktree"
    root.mkdir()
    _init_repo(root)
    _write_frontmatter(
        root / _SPEC_RELATIVE,
        {
            "type": "feature",
            "base_branch": "dev",
            "projects": ["ai-parrot-server"],
            "tags": ["e2e"],
            "e2e": {"policy": "required", "scenario_ids": [_SCENARIO_ID]},
        },
    )
    _write_frontmatter(root / _PLAN_RELATIVE, _plan_data())
    (root / "src_module.py").write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(root)
    return root


def _plan_path(worktree: Path) -> Path:
    return worktree / _PLAN_RELATIVE


def _write_plan(worktree: Path, **overrides: Any) -> None:
    _write_frontmatter(worktree / _PLAN_RELATIVE, _plan_data(**overrides))
    _commit_all(worktree, "update plan")


async def _load_current_plan(worktree: Path):
    return load_plan(_plan_path(worktree), worktree=worktree)


def _evidence_root(worktree: Path, *, feature_id: str = _FEATURE_ID) -> Path:
    return worktree / "sdd" / "state" / feature_id / "e2e"


def _write_pointer(worktree: Path, *, feature_id: str = _FEATURE_ID, run_id: str = _RUN_ID) -> None:
    pointer_path = _evidence_root(worktree, feature_id=feature_id) / "latest.json"
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")


def _run_dir(worktree: Path, *, feature_id: str = _FEATURE_ID, run_id: str = _RUN_ID) -> Path:
    return _evidence_root(worktree, feature_id=feature_id) / "runs" / run_id


def _passing_result(**overrides: Any) -> ScenarioResult:
    data: dict[str, Any] = {
        "scenario_id": _SCENARIO_ID,
        "node_id": _REQUIRED_NODE_ID,
        "outcome": "passed",
        "setup_outcome": "passed",
        "call_outcome": "passed",
        "teardown_outcome": "passed",
        "exit_code": 0,
        "duration_s": 1.0,
    }
    data.update(overrides)
    return ScenarioResult(**data)


def _build_verdict(identity: SourceIdentity, **overrides: Any) -> E2EVerdict:
    now = datetime.now(timezone.utc)
    data: dict[str, Any] = {
        "feature_id": _FEATURE_ID,
        "run_id": _RUN_ID,
        "policy": "required",
        "source_identity_before": identity,
        "source_identity_after": identity,
        "selected_node_ids": [_REQUIRED_NODE_ID],
        "collected_node_ids": [_REQUIRED_NODE_ID],
        "results": [_passing_result()],
        "counts": {"passed": 1},
        "argv": ["pytest", _REQUIRED_NODE_ID],
        "exit_code": 0,
        "cleanup_results": {_RUN_ID: True},
        "artifact_hashes": {},
        "status": "PASS",
        "gate_satisfied": True,
        "started_at": now,
        "completed_at": now,
    }
    data.update(overrides)
    return E2EVerdict(**data)


def _write_verdict(
    worktree: Path, verdict: E2EVerdict, *, feature_id: str = _FEATURE_ID, run_id: str = _RUN_ID
) -> Path:
    run_dir = _run_dir(worktree, feature_id=feature_id, run_id=run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    verdict_path = run_dir / "e2e-verdict.json"
    verdict_path.write_text(verdict.model_dump_json(), encoding="utf-8")
    return verdict_path


async def _seed_matching_evidence(worktree: Path, **verdict_overrides: Any) -> E2EVerdict:
    """Seed a pointer + verdict whose recorded identity matches the current worktree."""
    plan = await _load_current_plan(worktree)
    identity = await capture_identity(plan, worktree=worktree)
    verdict = _build_verdict(identity, **verdict_overrides)
    _write_pointer(worktree)
    _write_verdict(worktree, verdict)
    return verdict


@pytest.fixture(autouse=True)
def _clean_e2e_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every opt-in/credential variable `capture_identity` reads, for every test."""
    for name in ("PARROT_TEST_E2E", "PARROT_TEST_REAL_LLM", "E2E_MODEL", "E2E_MAX_LLM_CALLS", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Decision table: `required` policy
# ---------------------------------------------------------------------------


async def test_required_policy_blocks_on_missing_plan(git_worktree: Path) -> None:
    missing_plan = git_worktree / "sdd" / "state" / _FEATURE_ID / "does-not-exist.md"

    allowed, reasons = await evaluate_closeout_gate(policy="required", plan_path=missing_plan, worktree=git_worktree)

    assert allowed is False
    assert "e2e_required_missing_plan" in reasons


async def test_required_policy_cannot_be_bypassed_by_force(git_worktree: Path) -> None:
    """AC9: "generic force does not bypass it" -- now structural, not documented.

    The gate exposes no ``force`` parameter at all, so there is nothing a
    ``--force`` flag could be threaded into; missing evidence still blocks.
    """
    assert "force" not in inspect.signature(evaluate_closeout_gate).parameters

    allowed, reasons = await evaluate_closeout_gate(
        policy="required", plan_path=_plan_path(git_worktree), worktree=git_worktree
    )

    assert allowed is False
    assert any("MISSING" in reason for reason in reasons)
    assert "evidence_pointer_missing" in reasons


async def test_required_policy_blocks_on_zero_collection(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree, collected_node_ids=[], results=[], counts={})

    allowed, reasons = await evaluate_closeout_gate(
        policy="required", plan_path=_plan_path(git_worktree), worktree=git_worktree
    )

    assert allowed is False
    assert any("BLOCKED" in reason for reason in reasons)
    assert "no_codified_scenario_executed" in reasons


async def test_required_policy_blocks_on_failed_required_node(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree, results=[_passing_result(outcome="failed", call_outcome="failed")])

    allowed, reasons = await evaluate_closeout_gate(
        policy="required", plan_path=_plan_path(git_worktree), worktree=git_worktree
    )

    assert allowed is False
    assert any("FAIL" in reason for reason in reasons)
    assert any(reason.startswith(f"required_node_not_passed:{_REQUIRED_NODE_ID}:failed") for reason in reasons)


async def test_required_policy_blocks_on_incomplete_cleanup(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree, cleanup_results={_RUN_ID: False})

    allowed, reasons = await evaluate_closeout_gate(
        policy="required", plan_path=_plan_path(git_worktree), worktree=git_worktree
    )

    assert allowed is False
    assert "cleanup_incomplete" in reasons


async def test_required_policy_blocks_on_tampered_artifact(git_worktree: Path) -> None:
    run_dir = _run_dir(git_worktree)
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = run_dir / "junit.xml"
    artifact_path.write_text("<testsuite/>\n", encoding="utf-8")
    await _seed_matching_evidence(git_worktree, artifact_hashes={"junit.xml": "0" * 64})

    allowed, reasons = await evaluate_closeout_gate(
        policy="required", plan_path=_plan_path(git_worktree), worktree=git_worktree
    )

    assert allowed is False
    assert "evidence_artifact_tampered" in reasons


async def test_required_policy_blocks_on_stale_source_after_relevant_change(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree)
    (git_worktree / "src_module.py").write_text("VALUE = 2\n", encoding="utf-8")
    _commit_all(git_worktree, "relevant source change after the E2E run")

    allowed, reasons = await evaluate_closeout_gate(
        policy="required", plan_path=_plan_path(git_worktree), worktree=git_worktree
    )

    assert allowed is False
    assert "source_identity_stale" in reasons


async def test_required_policy_allows_on_fully_matching_evidence(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree)

    allowed, reasons = await evaluate_closeout_gate(
        policy="required", plan_path=_plan_path(git_worktree), worktree=git_worktree
    )

    assert allowed is True
    assert "e2e_required_satisfied" in reasons


async def test_required_policy_allows_bookkeeping_only_descendant_commit(git_worktree: Path) -> None:
    """AC8: evidence survives a bookkeeping-only closeout commit (sdd/tasks/)."""
    await _seed_matching_evidence(git_worktree)
    bookkeeping_path = git_worktree / "sdd" / "tasks" / "active" / "TASK-9999-bookkeeping.md"
    bookkeeping_path.parent.mkdir(parents=True, exist_ok=True)
    bookkeeping_path.write_text("bookkeeping\n", encoding="utf-8")
    _commit_all(git_worktree, "sdd: close tasks for FEAT-581 -- bookkeeping only")

    allowed, reasons = await evaluate_closeout_gate(
        policy="required", plan_path=_plan_path(git_worktree), worktree=git_worktree
    )

    assert allowed is True
    assert "e2e_required_satisfied" in reasons


async def test_invalid_policy_value_is_blocked_like_required_missing_evidence(git_worktree: Path) -> None:
    """A malformed spec `e2e.policy` value is never coerced to a safe default."""
    allowed, reasons = await evaluate_closeout_gate(
        policy="invalid", plan_path=_plan_path(git_worktree), worktree=git_worktree
    )

    assert allowed is False
    assert any("MISSING" in reason for reason in reasons)


# ---------------------------------------------------------------------------
# Decision table: `optional` policy -- advisory only, never blocks
# ---------------------------------------------------------------------------


async def test_optional_policy_with_no_plan_is_advisory_skip(git_worktree: Path) -> None:
    missing_plan = git_worktree / "sdd" / "state" / _FEATURE_ID / "does-not-exist.md"

    allowed, reasons = await evaluate_closeout_gate(policy="optional", plan_path=missing_plan, worktree=git_worktree)

    assert allowed is True
    assert "e2e_optional_no_plan" in reasons


async def test_optional_policy_never_blocks_on_failed_required_node(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree, results=[_passing_result(outcome="failed", call_outcome="failed")])

    allowed, reasons = await evaluate_closeout_gate(
        policy="optional", plan_path=_plan_path(git_worktree), worktree=git_worktree
    )

    # Advisory only: closeout proceeds, but the real FAIL status is carried
    # through honestly -- never silently upgraded to a pass.
    assert allowed is True
    assert any(reason.startswith("e2e_optional_advisory:FAIL") for reason in reasons)


async def test_optional_policy_never_blocks_on_missing_evidence(git_worktree: Path) -> None:
    allowed, reasons = await evaluate_closeout_gate(
        policy="optional", plan_path=_plan_path(git_worktree), worktree=git_worktree
    )

    assert allowed is True
    assert any(reason.startswith("e2e_optional_advisory:MISSING") for reason in reasons)


async def test_optional_policy_never_blocks_on_tampered_artifact(git_worktree: Path) -> None:
    run_dir = _run_dir(git_worktree)
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = run_dir / "junit.xml"
    artifact_path.write_text("<testsuite/>\n", encoding="utf-8")
    await _seed_matching_evidence(git_worktree, artifact_hashes={"junit.xml": "0" * 64})

    allowed, reasons = await evaluate_closeout_gate(
        policy="optional", plan_path=_plan_path(git_worktree), worktree=git_worktree
    )

    assert allowed is True
    assert any(reason.startswith("e2e_optional_advisory:BLOCKED") for reason in reasons)
    assert "evidence_artifact_tampered" in reasons


# ---------------------------------------------------------------------------
# Decision table: `none` policy -- explicit exemption, never touches evidence
# ---------------------------------------------------------------------------


async def test_none_policy_never_reads_a_plan_or_evidence(git_worktree: Path) -> None:
    """Passing a nonexistent plan path under `none` must never raise or be
    treated as missing evidence -- `none` short-circuits before any plan or
    evidence lookup happens at all."""
    nonexistent_plan = git_worktree / "sdd" / "state" / _FEATURE_ID / "definitely-not-there.md"

    allowed, reasons = await evaluate_closeout_gate(policy="none", plan_path=nonexistent_plan, worktree=git_worktree)

    assert allowed is True
    assert reasons == ["e2e_policy_none"]


# ---------------------------------------------------------------------------
# Cross-surface consistency: the Claude command and the Codex skill both
# delegate the decision to the gate script this file proves behaviorally
# (FEAT-703), rather than restating its decision table in prose.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _DOC_SURFACES, ids=lambda p: p.name)
def test_each_surface_invokes_the_gate_script(path: Path) -> None:
    """FEAT-703: enforcement is an invocation, not an instruction."""
    text = path.read_text(encoding="utf-8")
    assert "scripts.sdd.check_e2e_closeout" in text
    for keyword in ("stamp", "push", "merge", "cleanup"):
        assert keyword in text.lower()


@pytest.mark.parametrize("path", _DOC_SURFACES, ids=lambda p: p.name)
def test_each_surface_branches_on_the_gate_exit_code(path: Path) -> None:
    """The surfaces must act on the exit code, not re-derive the decision."""
    text = path.read_text(encoding="utf-8").lower()
    assert "exit" in text
    assert "non-zero" in text or "nonzero" in text


@pytest.mark.parametrize("path", _DOC_SURFACES, ids=lambda p: p.name)
def test_each_surface_states_force_never_bypasses_required_gate(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "--force" in text
    assert "never bypasses" in text.lower() or "does not bypass" in text.lower()


@pytest.mark.parametrize("path", _DOC_SURFACES, ids=lambda p: p.name)
def test_each_surface_excludes_exploration_from_the_gate(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "exploration" in text.lower()
    assert "never" in text.lower()


@pytest.mark.parametrize("path", _DOC_SURFACES, ids=lambda p: p.name)
def test_each_surface_names_the_worktree_scoped_plan_path(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "sdd/state/" in text and "e2e-plan.md" in text
