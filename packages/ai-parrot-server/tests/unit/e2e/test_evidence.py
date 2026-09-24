"""Unit tests for ``parrot.e2e.evidence.verify_evidence`` (TASK-3523, M2).

Every test builds a synthetic Git checkout under ``tmp_path`` (never the real
repository), a real ``e2e-plan.md``/spec pair ``load_plan`` can parse, and a
hand-written evidence pointer + ``E2EVerdict`` matching the read-only file
contract documented on ``parrot.e2e.evidence`` (``sdd/state/<feature_id>/
e2e/latest.json`` and ``.../runs/<run_id>/e2e-verdict.json``) -- there is no
production writer yet (the M3 runner is a separate, not-yet-implemented
task), so these tests are the executable specification for that future
writer as much as they are ``verify_evidence``'s own coverage. Only
``verify_evidence``'s own true collaborator, ``capture_identity``, is
exercised for real (never mocked) so a stale/tampered/mismatched identity is
detected exactly the way production code detects it. Environment variables
this module's identity fingerprint reads are isolated via ``monkeypatch``
for every test in this file, not only the ones that obviously need it.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest
import yaml

from parrot.e2e.errors import E2EEvidenceError
from parrot.e2e.evidence import capture_identity, verify_evidence
from parrot.e2e.models import E2EVerdict, ScenarioResult, SourceIdentity
from parrot.e2e.plan import load_plan

_FEATURE_ID = "FEAT-581"
_SPEC_RELATIVE = "sdd/specs/agentic-e2e-testing.spec.md"
_PLAN_RELATIVE = "sdd/state/e2e-plan.md"
_REQUIRED_NODE_ID = "tests/e2e/test_mcp_stdio.py::test_roundtrip"
_SCENARIO_ID = "scn-mcp-stdio"
_RUN_ID = "run-1"

# ---------------------------------------------------------------------------
# Isolation: never let the invoking shell's own env leak into a fingerprint.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_e2e_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every opt-in/credential variable ``capture_identity`` reads, for every test."""
    for name in ("PARROT_TEST_E2E", "PARROT_TEST_REAL_LLM", "E2E_MODEL", "E2E_MAX_LLM_CALLS", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Synthetic Git checkout + plan/spec frontmatter helpers
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
        {"type": "feature", "base_branch": "dev", "projects": ["ai-parrot-server"], "tags": ["e2e"]},
    )
    _write_frontmatter(root / _PLAN_RELATIVE, _plan_data())
    (root / "src_module.py").write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(root)
    return root


def _plan_path(worktree: Path) -> Path:
    return worktree / _PLAN_RELATIVE


def _write_plan(worktree: Path, **overrides: Any) -> None:
    """Overwrite and commit the plan with the given field overrides."""
    _write_frontmatter(worktree / _PLAN_RELATIVE, _plan_data(**overrides))
    _commit_all(worktree, "update plan")


async def _load_current_plan(worktree: Path):
    return load_plan(_plan_path(worktree), worktree=worktree)


# ---------------------------------------------------------------------------
# Evidence pointer / verdict writers (the executable contract a future M3
# runner must satisfy: see parrot.e2e.evidence's module docstring)
# ---------------------------------------------------------------------------


def _evidence_root(worktree: Path, *, feature_id: str = _FEATURE_ID) -> Path:
    return worktree / "sdd" / "state" / feature_id / "e2e"


def _write_pointer(worktree: Path, *, feature_id: str = _FEATURE_ID, run_id: Optional[str] = _RUN_ID) -> None:
    pointer_path = _evidence_root(worktree, feature_id=feature_id) / "latest.json"
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")


def _write_raw_pointer(worktree: Path, raw: str, *, feature_id: str = _FEATURE_ID) -> None:
    pointer_path = _evidence_root(worktree, feature_id=feature_id) / "latest.json"
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(raw, encoding="utf-8")


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


# ---------------------------------------------------------------------------
# policy "none": explicit exemption, never a fabricated execution
# ---------------------------------------------------------------------------


async def test_verify_evidence_policy_none_returns_pass_without_touching_evidence(git_worktree: Path) -> None:
    _write_plan(git_worktree, policy="none", scenarios=[])

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert result.status == "PASS"
    assert result.gate_satisfied is True
    assert "policy_none_no_execution" in result.reason_codes


# ---------------------------------------------------------------------------
# Missing evidence: synthesized MISSING, never a fabricated PASS
# ---------------------------------------------------------------------------


async def test_verify_evidence_no_pointer_returns_missing(git_worktree: Path) -> None:
    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert result.status == "MISSING"
    assert result.gate_satisfied is False
    assert "evidence_pointer_missing" in result.reason_codes


async def test_verify_evidence_malformed_pointer_json_returns_missing(git_worktree: Path) -> None:
    _write_raw_pointer(git_worktree, "{not valid json")

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert result.status == "MISSING"
    assert "evidence_pointer_malformed" in result.reason_codes


async def test_verify_evidence_pointer_missing_run_id_key_returns_missing(git_worktree: Path) -> None:
    _write_raw_pointer(git_worktree, json.dumps({"not_run_id": "run-1"}))

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert result.status == "MISSING"
    assert "evidence_pointer_malformed" in result.reason_codes


async def test_verify_evidence_pointer_unsafe_run_id_returns_missing(git_worktree: Path) -> None:
    _write_raw_pointer(git_worktree, json.dumps({"run_id": "../escape"}))

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    # "../escape" fails the safe-slug pattern outright, so the pointer is
    # simply malformed (never resolved to a filesystem path at all).
    assert result.status == "MISSING"
    assert "evidence_pointer_malformed" in result.reason_codes


async def test_verify_evidence_missing_verdict_file_returns_missing(git_worktree: Path) -> None:
    _write_pointer(git_worktree)

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert result.status == "MISSING"
    assert "evidence_verdict_missing" in result.reason_codes


# ---------------------------------------------------------------------------
# Malformed/unknown schema: fails closed via a raised E2EEvidenceError
# ---------------------------------------------------------------------------


async def test_verify_evidence_malformed_verdict_json_raises_evidence_error(git_worktree: Path) -> None:
    _write_pointer(git_worktree)
    run_dir = _run_dir(git_worktree)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "e2e-verdict.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(E2EEvidenceError) as excinfo:
        await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert excinfo.value.reason_code == "evidence_verdict_invalid_json"
    assert excinfo.value.exit_code == 4


async def test_verify_evidence_verdict_failing_schema_validation_raises_evidence_error(git_worktree: Path) -> None:
    _write_pointer(git_worktree)
    run_dir = _run_dir(git_worktree)
    run_dir.mkdir(parents=True, exist_ok=True)
    # Missing every required field (feature_id, run_id, policy, identities, exit_code, ...).
    (run_dir / "e2e-verdict.json").write_text(json.dumps({"schema_version": 1}), encoding="utf-8")

    with pytest.raises(E2EEvidenceError) as excinfo:
        await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert excinfo.value.reason_code == "evidence_verdict_malformed"


async def test_verify_evidence_feature_id_mismatch_raises_evidence_error(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree, feature_id="FEAT-999")

    with pytest.raises(E2EEvidenceError) as excinfo:
        await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert excinfo.value.reason_code == "evidence_feature_mismatch"


# ---------------------------------------------------------------------------
# Interrupted runs: cannot validate at all (MISSING, not raised, not PASS)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("interrupted_exit_code", [130, 143])
async def test_verify_evidence_interrupted_run_returns_missing(git_worktree: Path, interrupted_exit_code: int) -> None:
    await _seed_matching_evidence(git_worktree, exit_code=interrupted_exit_code)

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert result.status == "MISSING"
    assert result.gate_satisfied is False
    assert "run_interrupted" in result.reason_codes


# ---------------------------------------------------------------------------
# Before/after identity mutation during the run's own execution
# ---------------------------------------------------------------------------


async def test_verify_evidence_before_after_identity_mismatch_raises_evidence_error(git_worktree: Path) -> None:
    plan = await _load_current_plan(git_worktree)
    before_identity = await capture_identity(plan, worktree=git_worktree)
    (git_worktree / "src_module.py").write_text("VALUE = 2\n", encoding="utf-8")
    after_identity = await capture_identity(plan, worktree=git_worktree)
    verdict = _build_verdict(before_identity, source_identity_after=after_identity)
    _write_pointer(git_worktree)
    _write_verdict(git_worktree, verdict)

    with pytest.raises(E2EEvidenceError) as excinfo:
        await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert excinfo.value.reason_code == "source_identity_changed_during_run"


# ---------------------------------------------------------------------------
# Artifact hashes: missing, tampered, escaping
# ---------------------------------------------------------------------------


async def test_verify_evidence_artifact_hash_matches_passes(git_worktree: Path) -> None:
    run_dir = _run_dir(git_worktree)
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = run_dir / "junit.xml"
    artifact_path.write_text("<testsuite/>\n", encoding="utf-8")
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

    await _seed_matching_evidence(git_worktree, artifact_hashes={"junit.xml": digest})

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert result.status == "PASS"


async def test_verify_evidence_artifact_missing_raises_evidence_error(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree, artifact_hashes={"missing.xml": "0" * 64})

    with pytest.raises(E2EEvidenceError) as excinfo:
        await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert excinfo.value.reason_code == "evidence_artifact_missing"


async def test_verify_evidence_artifact_tampered_hash_raises_evidence_error(git_worktree: Path) -> None:
    run_dir = _run_dir(git_worktree)
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = run_dir / "junit.xml"
    artifact_path.write_text("<testsuite/>\n", encoding="utf-8")

    await _seed_matching_evidence(git_worktree, artifact_hashes={"junit.xml": "0" * 64})

    with pytest.raises(E2EEvidenceError) as excinfo:
        await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert excinfo.value.reason_code == "evidence_artifact_tampered"


async def test_verify_evidence_artifact_path_escape_raises_evidence_error(git_worktree: Path) -> None:
    # A real file just outside the run directory (inside the feature's own
    # evidence root) so the escape is detected deterministically, rather
    # than being masked by a plain "does not exist" for a path that
    # resolves nowhere at all.
    evidence_root = _evidence_root(git_worktree)
    evidence_root.mkdir(parents=True, exist_ok=True)
    (evidence_root / "decoy.txt").write_text("decoy\n", encoding="utf-8")

    await _seed_matching_evidence(git_worktree, artifact_hashes={"../../decoy.txt": "0" * 64})

    with pytest.raises(E2EEvidenceError) as excinfo:
        await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert excinfo.value.reason_code == "evidence_artifact_path_escape"


# ---------------------------------------------------------------------------
# Staleness (AC8): any relevant implementation change requires a rerun, but
# bookkeeping-only closeout commits (sdd/tasks/) must NOT count as stale.
# ---------------------------------------------------------------------------


async def test_verify_evidence_source_changed_since_run_raises_evidence_error(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree)
    (git_worktree / "src_module.py").write_text("VALUE = 2\n", encoding="utf-8")
    _commit_all(git_worktree, "relevant source change")

    with pytest.raises(E2EEvidenceError) as excinfo:
        await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert excinfo.value.reason_code == "source_identity_stale"


async def test_verify_evidence_survives_bookkeeping_only_descendant_commit(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree)
    bookkeeping_path = git_worktree / "sdd" / "tasks" / "active" / "TASK-9999-bookkeeping.md"
    bookkeeping_path.parent.mkdir(parents=True, exist_ok=True)
    bookkeeping_path.write_text("bookkeeping\n", encoding="utf-8")
    _commit_all(git_worktree, "bookkeeping-only closeout commit")

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert result.status == "PASS"
    assert result.gate_satisfied is True


# ---------------------------------------------------------------------------
# Selected/collected node coverage sanity (tampering-shaped, not a normal
# coverage gap the runner would ever legitimately produce)
# ---------------------------------------------------------------------------


async def test_verify_evidence_selected_nodes_mismatch_raises_evidence_error(git_worktree: Path) -> None:
    await _seed_matching_evidence(
        git_worktree,
        selected_node_ids=[_REQUIRED_NODE_ID, "tests/e2e/test_other.py::test_bogus"],
    )

    with pytest.raises(E2EEvidenceError) as excinfo:
        await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert excinfo.value.reason_code == "selected_nodes_mismatch"


async def test_verify_evidence_collected_nodes_outside_selection_raises_evidence_error(git_worktree: Path) -> None:
    await _seed_matching_evidence(
        git_worktree,
        collected_node_ids=[_REQUIRED_NODE_ID, "tests/e2e/test_other.py::test_bogus"],
    )

    with pytest.raises(E2EEvidenceError) as excinfo:
        await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert excinfo.value.reason_code == "collected_nodes_unselected"


# ---------------------------------------------------------------------------
# Cleanup: fails the run even when every assertion passed (AC7/AC9 gate)
# ---------------------------------------------------------------------------


async def test_verify_evidence_cleanup_incomplete_returns_fail(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree, cleanup_results={_RUN_ID: False})

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert result.status == "FAIL"
    assert result.gate_satisfied is False
    assert "cleanup_incomplete" in result.reason_codes


# ---------------------------------------------------------------------------
# Coverage: zero collection, all-skipped, required regressions, phase
# failures (AC7: "cannot produce valid PASS")
# ---------------------------------------------------------------------------


async def test_verify_evidence_zero_collection_returns_blocked(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree, collected_node_ids=[], results=[], counts={})

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert result.status == "BLOCKED"
    assert result.gate_satisfied is False
    assert "no_codified_scenario_executed" in result.reason_codes


async def test_verify_evidence_all_skipped_returns_blocked(git_worktree: Path) -> None:
    skipped = _passing_result(outcome="skipped", call_outcome=None, setup_outcome=None, teardown_outcome=None)
    await _seed_matching_evidence(git_worktree, results=[skipped], counts={"skipped": 1})

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert result.status == "BLOCKED"
    assert "no_codified_scenario_executed" in result.reason_codes


@pytest.mark.parametrize("outcome", ["failed", "xfailed", "xpassed"])
async def test_verify_evidence_required_node_non_passing_outcome_returns_fail(git_worktree: Path, outcome: str) -> None:
    non_passing = _passing_result(outcome=outcome)
    await _seed_matching_evidence(git_worktree, results=[non_passing], counts={outcome: 1})

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert result.status == "FAIL"
    assert result.gate_satisfied is False
    assert any(
        code.startswith(f"required_node_not_passed:{_REQUIRED_NODE_ID}:{outcome}") for code in result.reason_codes
    )


async def test_verify_evidence_required_node_missing_from_results_returns_fail(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree, results=[], collected_node_ids=[_REQUIRED_NODE_ID], counts={})

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    # Collected but never reported: this is a genuine coverage gap, not
    # "nothing executed at all" -- still FAIL, matching AC7's "missing" case.
    assert result.status == "FAIL"
    assert any(code.startswith(f"required_node_missing:{_REQUIRED_NODE_ID}") for code in result.reason_codes)


async def test_verify_evidence_required_node_setup_failure_returns_fail(git_worktree: Path) -> None:
    failed_setup = _passing_result(setup_outcome="failed")
    await _seed_matching_evidence(git_worktree, results=[failed_setup])

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert result.status == "FAIL"
    assert any(code.startswith(f"required_node_setup_failure:{_REQUIRED_NODE_ID}") for code in result.reason_codes)


async def test_verify_evidence_required_node_teardown_failure_returns_fail(git_worktree: Path) -> None:
    failed_teardown = _passing_result(teardown_outcome="failed")
    await _seed_matching_evidence(git_worktree, results=[failed_teardown])

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert result.status == "FAIL"
    assert any(code.startswith(f"required_node_teardown_failure:{_REQUIRED_NODE_ID}") for code in result.reason_codes)


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------


async def test_verify_evidence_fully_matching_required_run_returns_pass(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree)

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert result.status == "PASS"
    assert result.gate_satisfied is True
    assert result.reason_codes == []


async def test_verify_evidence_ignores_non_required_scenario_failure(git_worktree: Path) -> None:
    _write_plan(
        git_worktree,
        scenarios=[
            {
                "id": _SCENARIO_ID,
                "tier": "deterministic",
                "target_ids": ["stdio"],
                "required": True,
                "node_ids": [_REQUIRED_NODE_ID],
            },
            {
                "id": "scn-optional-extra",
                "tier": "deterministic",
                "target_ids": ["stdio"],
                "required": False,
                "node_ids": ["tests/e2e/test_extra.py::test_optional"],
            },
        ],
    )
    plan = await _load_current_plan(git_worktree)
    identity = await capture_identity(plan, worktree=git_worktree)
    verdict = _build_verdict(
        identity,
        selected_node_ids=[_REQUIRED_NODE_ID, "tests/e2e/test_extra.py::test_optional"],
        collected_node_ids=[_REQUIRED_NODE_ID, "tests/e2e/test_extra.py::test_optional"],
        results=[
            _passing_result(),
            ScenarioResult(
                scenario_id="scn-optional-extra",
                node_id="tests/e2e/test_extra.py::test_optional",
                outcome="failed",
                call_outcome="failed",
                exit_code=1,
                duration_s=0.5,
            ),
        ],
        counts={"passed": 1, "failed": 1},
    )
    _write_pointer(git_worktree)
    _write_verdict(git_worktree, verdict)

    result = await verify_evidence(_plan_path(git_worktree), worktree=git_worktree)

    assert result.status == "PASS"
    assert result.gate_satisfied is True
