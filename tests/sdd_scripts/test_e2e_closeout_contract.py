"""Behavioral contract for FEAT-581 M7 (TASK-3543): required E2E evidence
before both SDD closeout surfaces (`.claude/commands/sdd-done.md` Step 4.6,
`.agents/skills/sdd-done/SKILL.md` step 4.5) may stamp, push, open a PR,
merge or clean up a feature.

This is deliberately NOT a set of string-only assertions that mirror the
docs' own prose. ``evaluate_closeout_gate`` below is the task-local decision
function both closeout surfaces document in prose; it is proven here against
the real ``parrot.e2e.evidence.verify_evidence`` validator (TASK-3523) fed
realistic, on-disk evidence artifacts built the same way
``packages/ai-parrot-server/tests/unit/e2e/test_evidence.py`` builds them --
never a mocked validator and never a fabricated ``VerificationResult``. The
doc-surface checks at the bottom only confirm the two closeout hosts
document the same required/optional/none policy and the same "force never
bypasses required" contract as this verified decision function, not merely
with each other's prose.
"""

from __future__ import annotations

import hashlib
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
# Task-local closeout decision function (Fixed interfaces: "Internal helpers
# remain task-local" -- no new cross-task public signature). This is exactly
# the decision table both closeout surfaces document: required/optional/none
# policy, consuming the same read-only `verify_evidence` validator, with
# `force` proven to never change a `required` outcome.
# ---------------------------------------------------------------------------


async def evaluate_closeout_gate(
    *, policy: str, plan_path: Optional[Path], worktree: Path, force: bool
) -> tuple[bool, list[str]]:
    """Return whether closeout may proceed, mirroring the documented gate.

    Args:
        policy: One of ``required``/``optional``/``none`` (or ``invalid`` for
            a malformed spec ``e2e.policy`` value, treated exactly like
            ``required`` with missing evidence).
        plan_path: Path to the feature's ``e2e-plan.md``, or ``None``/missing
            when no plan was generated.
        worktree: The feature worktree `verify_evidence` validates against.
        force: The command's generic ``--force`` flag. Documented (and
            proven below) to have **no effect** on this decision -- it only
            ever affects per-task partial-evidence and ledger merge-blocker
            handling elsewhere in the closeout flow.

    Returns:
        ``(allowed, reason_codes)``.
    """
    del force  # never consulted: AC9 "generic force does not bypass it"
    if policy == "none":
        return True, ["e2e_policy_none"]

    if plan_path is None or not plan_path.is_file():
        if policy in ("required", "invalid"):
            return False, ["e2e_required_missing_plan"]
        return True, ["e2e_optional_no_plan"]

    try:
        result = await verify_evidence(plan_path, worktree=worktree)
    except (E2EEvidenceError, E2EConfigError) as exc:
        # Fails closed exactly like a synthesized BLOCKED VerificationResult:
        # a malformed/tampered/stale evidence blob is never treated as PASS.
        result = VerificationResult(
            status="BLOCKED", gate_satisfied=False, reason_codes=[exc.reason_code or "evidence_error"]
        )

    if policy in ("required", "invalid"):
        if result.status == "PASS" and result.gate_satisfied:
            return True, ["e2e_required_satisfied", *result.reason_codes]
        return False, [f"e2e_required_not_satisfied:{result.status}", *result.reason_codes]

    # optional: advisory only, real status always carried through, never
    # upgraded to a pass.
    return True, [f"e2e_optional_advisory:{result.status}", *result.reason_codes]


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

    allowed, reasons = await evaluate_closeout_gate(
        policy="required", plan_path=missing_plan, worktree=git_worktree, force=False
    )

    assert allowed is False
    assert "e2e_required_missing_plan" in reasons


@pytest.mark.parametrize("force", [False, True])
async def test_required_policy_blocks_on_missing_evidence_regardless_of_force(git_worktree: Path, force: bool) -> None:
    """AC9: "generic force does not bypass it" -- proven for both flag values."""
    allowed, reasons = await evaluate_closeout_gate(
        policy="required", plan_path=_plan_path(git_worktree), worktree=git_worktree, force=force
    )

    assert allowed is False
    assert any("MISSING" in reason for reason in reasons)
    assert "evidence_pointer_missing" in reasons


async def test_required_policy_blocks_on_zero_collection(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree, collected_node_ids=[], results=[], counts={})

    allowed, reasons = await evaluate_closeout_gate(
        policy="required", plan_path=_plan_path(git_worktree), worktree=git_worktree, force=True
    )

    assert allowed is False
    assert any("BLOCKED" in reason for reason in reasons)
    assert "no_codified_scenario_executed" in reasons


async def test_required_policy_blocks_on_failed_required_node(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree, results=[_passing_result(outcome="failed", call_outcome="failed")])

    allowed, reasons = await evaluate_closeout_gate(
        policy="required", plan_path=_plan_path(git_worktree), worktree=git_worktree, force=True
    )

    assert allowed is False
    assert any("FAIL" in reason for reason in reasons)
    assert any(reason.startswith(f"required_node_not_passed:{_REQUIRED_NODE_ID}:failed") for reason in reasons)


async def test_required_policy_blocks_on_incomplete_cleanup(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree, cleanup_results={_RUN_ID: False})

    allowed, reasons = await evaluate_closeout_gate(
        policy="required", plan_path=_plan_path(git_worktree), worktree=git_worktree, force=True
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
        policy="required", plan_path=_plan_path(git_worktree), worktree=git_worktree, force=True
    )

    assert allowed is False
    assert "evidence_artifact_tampered" in reasons


async def test_required_policy_blocks_on_stale_source_after_relevant_change(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree)
    (git_worktree / "src_module.py").write_text("VALUE = 2\n", encoding="utf-8")
    _commit_all(git_worktree, "relevant source change after the E2E run")

    allowed, reasons = await evaluate_closeout_gate(
        policy="required", plan_path=_plan_path(git_worktree), worktree=git_worktree, force=True
    )

    assert allowed is False
    assert "source_identity_stale" in reasons


async def test_required_policy_allows_on_fully_matching_evidence(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree)

    allowed, reasons = await evaluate_closeout_gate(
        policy="required", plan_path=_plan_path(git_worktree), worktree=git_worktree, force=False
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
        policy="required", plan_path=_plan_path(git_worktree), worktree=git_worktree, force=False
    )

    assert allowed is True
    assert "e2e_required_satisfied" in reasons


async def test_invalid_policy_value_is_blocked_like_required_missing_evidence(git_worktree: Path) -> None:
    """A malformed spec `e2e.policy` value is never coerced to a safe default."""
    allowed, reasons = await evaluate_closeout_gate(
        policy="invalid", plan_path=_plan_path(git_worktree), worktree=git_worktree, force=True
    )

    assert allowed is False
    assert any("MISSING" in reason for reason in reasons)


# ---------------------------------------------------------------------------
# Decision table: `optional` policy -- advisory only, never blocks
# ---------------------------------------------------------------------------


async def test_optional_policy_with_no_plan_is_advisory_skip(git_worktree: Path) -> None:
    missing_plan = git_worktree / "sdd" / "state" / _FEATURE_ID / "does-not-exist.md"

    allowed, reasons = await evaluate_closeout_gate(
        policy="optional", plan_path=missing_plan, worktree=git_worktree, force=False
    )

    assert allowed is True
    assert "e2e_optional_no_plan" in reasons


async def test_optional_policy_never_blocks_on_failed_required_node(git_worktree: Path) -> None:
    await _seed_matching_evidence(git_worktree, results=[_passing_result(outcome="failed", call_outcome="failed")])

    allowed, reasons = await evaluate_closeout_gate(
        policy="optional", plan_path=_plan_path(git_worktree), worktree=git_worktree, force=False
    )

    # Advisory only: closeout proceeds, but the real FAIL status is carried
    # through honestly -- never silently upgraded to a pass.
    assert allowed is True
    assert any(reason.startswith("e2e_optional_advisory:FAIL") for reason in reasons)


async def test_optional_policy_never_blocks_on_missing_evidence(git_worktree: Path) -> None:
    allowed, reasons = await evaluate_closeout_gate(
        policy="optional", plan_path=_plan_path(git_worktree), worktree=git_worktree, force=False
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
        policy="optional", plan_path=_plan_path(git_worktree), worktree=git_worktree, force=False
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

    allowed, reasons = await evaluate_closeout_gate(
        policy="none", plan_path=nonexistent_plan, worktree=git_worktree, force=False
    )

    assert allowed is True
    assert reasons == ["e2e_policy_none"]


# ---------------------------------------------------------------------------
# Cross-surface consistency: Claude command and Codex skill document the
# same required/optional/none policy and the same "force never bypasses a
# required gate" contract this file's decision function proves behaviorally.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _DOC_SURFACES, ids=lambda p: p.name)
def test_each_surface_invokes_verify_before_every_mutating_step(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "parrot e2e verify" in text
    for keyword in ("stamp", "push", "merge", "cleanup"):
        assert keyword in text.lower()


@pytest.mark.parametrize("path", _DOC_SURFACES, ids=lambda p: p.name)
def test_each_surface_states_the_three_policy_literals_with_no_coercion(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "required" in text and "optional" in text and "none" in text
    assert "coerc" in text.lower()


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
