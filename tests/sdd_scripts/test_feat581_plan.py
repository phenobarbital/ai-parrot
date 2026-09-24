"""Behavioral contract for FEAT-581 M5/M9 (TASK-3547): freeze the canonical
feature plan and confirm it is genuinely runnable against the integrated
revision.

This is deliberately NOT a set of string-only assertions that mirror the
plan's own YAML. Every claim below is proven against the real
``parrot.e2e.plan.load_plan`` loader / ``parrot.e2e.models.E2EPlan`` schema
(TASK-3520/3521), the real ``parrot.e2e.evidence.verify_evidence`` validator
(TASK-3523), and, for node-ID coverage, a real ``python -m pytest
--collect-only`` subprocess against this checkout's actual test tree -- never
a static substring check standing in for genuine collection.

Two closeout dispositions are exercised: the real committed
``sdd/state/FEAT-581/e2e-plan.md`` has no persisted evidence in this
checkout yet (no live/browser prerequisite -- e.g. ``redis-server`` -- has
ever run here), so ``verify_evidence`` must honestly report ``MISSING``,
never a fabricated ``PASS`` ("no-server/no-E2E compatibility"); a second,
self-contained synthetic plan is executed for real end-to-end (a genuine
``run_plan`` subprocess, then ``verify_evidence``) to prove the allow path
is reachable at all once real evidence exists.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]

# `parrot.e2e` ships from the ai-parrot-server distribution; add this
# worktree's own source tree explicitly (same convention as
# test_e2e_spec_contract.py / test_e2e_ci_plans.py / test_e2e_closeout_contract.py)
# so `pytest tests/sdd_scripts/test_feat581_plan.py -q` works exactly as this
# task's own Validation Commands state, with no extra env setup.
_SERVER_SRC = _REPO_ROOT / "packages" / "ai-parrot-server" / "src"
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))

from parrot.e2e.evidence import verify_evidence  # noqa: E402
from parrot.e2e.plan import load_plan  # noqa: E402
from parrot.e2e.runner import run_plan  # noqa: E402

_FEATURE_ID = "FEAT-581"
_PLAN_PATH = _REPO_ROOT / "sdd" / "state" / _FEATURE_ID / "e2e-plan.md"
_SPEC_PATH = _REPO_ROOT / "sdd" / "specs" / "agentic-e2e-testing.spec.md"

# The exact frozen scenario/node IDs from this task's own embedded "Canonical
# Feature Plan" -- copied verbatim from the task file, never invented here.
_FROZEN_SCENARIO_NODE_IDS: dict[str, str] = {
    "http-cli-stays-alive-and-stops": (
        "packages/ai-parrot-server/tests/e2e/test_mcp_http.py::test_http_cli_stays_alive_and_stops"
    ),
    "stdio-tool-roundtrip-and-eof": (
        "packages/ai-parrot-server/tests/e2e/test_mcp_stdio.py::test_stdio_tool_roundtrip_and_eof"
    ),
    "authenticated-minimal-profile": (
        "packages/ai-parrot-server/tests/e2e/test_botmanager.py::test_authenticated_minimal_profile"
    ),
    "botmanager-offline-boot": ("packages/ai-parrot-server/tests/e2e/test_botmanager.py::test_botmanager_offline_boot"),
    "controller-and-supervisor-death": (
        "packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_controller_and_supervisor_death"
    ),
    "timeout-and-grandchild-teardown": (
        "packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_timeout_and_grandchild_teardown"
    ),
    "two-worktrees-independent": (
        "packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_two_worktrees_independent"
    ),
    "wrong-checkout-cannot-pass": (
        "packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_wrong_checkout_cannot_pass"
    ),
    "required-evidence-rejections": (
        "packages/ai-parrot-server/tests/e2e/test_evidence.py::test_required_evidence_rejections"
    ),
}


def _load_frozen_plan():
    return load_plan(_PLAN_PATH, worktree=_REPO_ROOT)


def _subprocess_env() -> dict[str, str]:
    """Environment for a child pytest/collection subprocess that must resolve
    *this worktree's* own ``parrot.e2e`` package.

    ``parrot``'s own ``__init__.py`` calls ``pkgutil.extend_path``, merging
    every ``parrot/`` directory found on ``sys.path`` (see
    ``.claude/rules/worktree-management.md``: "the shared .venv is
    editable-installed against the main checkout"). Without this override a
    bare child process would resolve ``parrot.e2e`` against the main
    checkout's copy -- which may lag or lack this feature entirely -- instead
    of the worktree under test.
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    prefix = str(_SERVER_SRC)
    env["PYTHONPATH"] = f"{prefix}{os.pathsep}{existing}" if existing else prefix
    return env


# ---------------------------------------------------------------------------
# Schema/loader round-trip: the committed plan is genuinely valid, not merely
# plausible-looking YAML.
# ---------------------------------------------------------------------------


def test_plan_file_exists_at_the_task_owned_state_path() -> None:
    assert _PLAN_PATH.is_file()


def test_plan_loads_and_validates_against_the_real_schema() -> None:
    plan = _load_frozen_plan()

    assert plan.feature_id == _FEATURE_ID
    assert plan.spec_path == "sdd/specs/agentic-e2e-testing.spec.md"
    assert plan.policy == "required"


def test_plan_scenario_ids_match_the_frozen_canonical_set() -> None:
    plan = _load_frozen_plan()

    assert {scenario.id for scenario in plan.scenarios} == set(_FROZEN_SCENARIO_NODE_IDS)


def test_plan_node_ids_match_the_frozen_canonical_set_exactly() -> None:
    """One node ID per scenario, byte-for-byte -- "frozen task contracts"."""
    plan = _load_frozen_plan()

    by_scenario = {scenario.id: scenario.node_ids for scenario in plan.scenarios}
    for scenario_id, expected_node_id in _FROZEN_SCENARIO_NODE_IDS.items():
        assert by_scenario[scenario_id] == [expected_node_id]


def test_every_scenario_is_required_and_deterministic() -> None:
    plan = _load_frozen_plan()

    assert all(scenario.required for scenario in plan.scenarios)
    assert all(scenario.tier == "deterministic" for scenario in plan.scenarios)


@pytest.mark.parametrize("node_id", sorted(_FROZEN_SCENARIO_NODE_IDS.values()))
def test_plan_node_ids_reference_real_files_on_disk(node_id: str) -> None:
    path_part = node_id.split("::", 1)[0]
    assert (_REPO_ROOT / path_part).is_file(), f"plan references a node ID whose file does not exist: {node_id}"


# ---------------------------------------------------------------------------
# Spec/plan agreement: the spec's own e2e.policy/scenario_ids metadata
# activates the required intent this plan depends on (TASK-3547 scope note:
# "without that metadata the compatibility default is optional").
# ---------------------------------------------------------------------------


def test_spec_frontmatter_declares_matching_required_e2e_metadata() -> None:
    front_text = _SPEC_PATH.read_text(encoding="utf-8").split("---", 2)[1]
    declared = yaml.safe_load(front_text)["e2e"]

    assert declared["policy"] == "required"
    assert set(declared["scenario_ids"]) == set(_FROZEN_SCENARIO_NODE_IDS)


def test_plan_loader_cross_checks_the_real_spec_without_raising() -> None:
    """`load_plan` itself cross-validates plan vs. spec `e2e` metadata
    (parrot.e2e.plan._check_spec_consistency); a successful `_load_frozen_plan()`
    call already proves agreement, but this test names that guarantee
    explicitly so a future edit to either file fails loudly, not silently."""
    plan = _load_frozen_plan()
    assert plan.policy == "required"  # would have raised E2EConfigError otherwise


# ---------------------------------------------------------------------------
# Integrated collection: every frozen node ID is real, collectible pytest
# coverage on the current revision -- not merely a path that exists on disk.
# ---------------------------------------------------------------------------


def test_every_frozen_node_id_collects_via_a_real_pytest_subprocess() -> None:
    node_ids = sorted(_FROZEN_SCENARIO_NODE_IDS.values())
    process = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *node_ids],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env=_subprocess_env(),
    )

    assert process.returncode == 0, process.stdout + process.stderr
    for node_id in node_ids:
        # pytest reports paths relative to the nearest ini file it resolves
        # for each argument (here: packages/ai-parrot-server/pyproject.toml),
        # so the reported node ID drops the "packages/ai-parrot-server/"
        # prefix -- match on the package-relative suffix instead of the
        # plan's own repo-root-relative spelling.
        reported_node_id = node_id.removeprefix("packages/ai-parrot-server/")
        assert reported_node_id in process.stdout, f"node ID did not collect: {node_id}\n{process.stdout}"
    assert f"{len(node_ids)} tests collected" in process.stdout


# ---------------------------------------------------------------------------
# Closeout paths: no execution never counts as a pass ("no-server/no-E2E
# compatibility"), and the allow path is genuinely reachable once real
# evidence exists.
# ---------------------------------------------------------------------------


async def test_frozen_plan_with_no_persisted_evidence_reports_missing_never_a_fabricated_pass() -> None:
    """This checkout has never run the full canonical plan for real (several
    scenarios need external prerequisites -- e.g. `redis-server` -- absent
    from this environment); `verify_evidence` must honestly report MISSING,
    never synthesize a PASS just because required policy demands one."""
    result = await verify_evidence(_PLAN_PATH, worktree=_REPO_ROOT)

    assert result.status == "MISSING"
    assert result.gate_satisfied is False


async def test_a_genuinely_executed_required_plan_reaches_the_allow_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A minimal, self-contained, real end-to-end run (real `run_plan`
    subprocess, real `verify_evidence`) proves the allow disposition is
    reachable at all -- the complement of the MISSING case above, using the
    same real validators, not a mocked/short-circuited stand-in."""
    # `run_plan`'s own child pytest process inherits `os.environ` verbatim
    # (see `_subprocess_env`'s docstring); mutate it here so that inherited
    # copy resolves this worktree's own `parrot.e2e`, not the main checkout's.
    monkeypatch.setenv("PYTHONPATH", _subprocess_env()["PYTHONPATH"])

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    _run(["git", "init"], cwd=worktree)
    _run(["git", "config", "user.email", "feat581-plan-test@example.com"], cwd=worktree)
    _run(["git", "config", "user.name", "FEAT-581 Plan Test"], cwd=worktree)

    spec_path = worktree / "sdd" / "specs" / "example.spec.md"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text("---\ntype: feature\nbase_branch: dev\n---\n\n# Example\n", encoding="utf-8")

    fixture_module = worktree / "tests_fixture" / "test_synthetic.py"
    fixture_module.parent.mkdir(parents=True)
    fixture_module.write_text("def test_passes() -> None:\n    assert True\n", encoding="utf-8")

    plan_path = worktree / "sdd" / "state" / "e2e-plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_payload: dict[str, Any] = {
        "feature_id": "FEAT-999",
        "spec_path": "sdd/specs/example.spec.md",
        "policy": "required",
        "scenarios": [
            {
                "id": "scn-allow-path",
                "tier": "deterministic",
                "required": True,
                "node_ids": ["tests_fixture/test_synthetic.py::test_passes"],
            }
        ],
    }
    plan_path.write_text("---\n" + yaml.safe_dump(plan_payload, sort_keys=False) + "---\n\nRationale.\n", encoding="utf-8")
    _run(["git", "add", "-A"], cwd=worktree)
    _run(["git", "commit", "-m", "seed real allow-path checkout"], cwd=worktree)

    verdict = await run_plan(plan_path, worktree=worktree, owner_id=f"pytest-plan-test-{uuid.uuid4().hex}")
    assert verdict.status == "PASS"

    result = await verify_evidence(plan_path, worktree=worktree)
    assert result.status == "PASS"
    assert result.gate_satisfied is True


def _run(argv: list[str], *, cwd: Path) -> None:
    subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# The plan body is a generated artifact, not an execution claim.
# ---------------------------------------------------------------------------


def test_plan_body_does_not_claim_execution() -> None:
    raw_body = _PLAN_PATH.read_text(encoding="utf-8").split("---", 2)[2]
    normalized = " ".join(raw_body.split())

    assert "runtime validation and successful execution remain pending implementation" in normalized
    assert "not claimed as executed by this plan" in normalized
