"""Behavioral contract for FEAT-581 M9 (TASK-3545): deterministic nightly/
manual and dispatch-only live CI plans.

This is deliberately NOT a set of string-only assertions that mirror the
workflow's own prose or a static YAML substring check. Every claim about
the two ``e2e-plan.md`` documents below is proven against the real
``parrot.e2e.plan.load_plan`` loader and the real ``parrot.e2e.models``
schema (TASK-3520/3521) -- the same validated model the CLI (``parrot e2e
run --plan`` / ``parrot e2e verify --plan``) consumes. Every claim about
``.github/workflows/e2e.yml`` is proven by parsing the file as real YAML
(``yaml.safe_load``) and asserting on the resulting mapping's structure --
never by grepping strings out of the raw text alone (the few substring
checks below only ever assert the *absence* of a banned pattern, as a
supplement to, never a replacement for, the structural assertions).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]

# `parrot.e2e` ships from the ai-parrot-server distribution; add this
# worktree's own source tree explicitly (same convention as
# test_e2e_spec_contract.py / test_e2e_closeout_contract.py) so
# `pytest tests/sdd_scripts/test_e2e_ci_plans.py -q` works exactly as this
# task's Validation Commands state, with no extra env setup.
_SERVER_SRC = _REPO_ROOT / "packages" / "ai-parrot-server" / "src"
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))

from parrot.e2e.errors import E2EConfigError  # noqa: E402
from parrot.e2e.plan import load_plan  # noqa: E402

_PLANS_DIR = _REPO_ROOT / "packages" / "ai-parrot-server" / "tests" / "e2e" / "plans"
_DETERMINISTIC_PLAN = _PLANS_DIR / "deterministic.md"
_LIVE_PLAN = _PLANS_DIR / "live.md"
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "e2e.yml"

_FEATURE_ID = "FEAT-581"

# The exact frozen integration node IDs declared by their owning tasks
# (TASK-3535/3536/3537/3548); this task's own scope note requires "exact
# frozen scenario node IDs" -- copied from each task's Completion Note, not
# invented here.
_FROZEN_REQUIRED_NODE_IDS = frozenset(
    {
        "packages/ai-parrot-server/tests/e2e/test_mcp_http.py::test_http_cli_stays_alive_and_stops",
        "packages/ai-parrot-server/tests/e2e/test_mcp_stdio.py::test_stdio_tool_roundtrip_and_eof",
        "packages/ai-parrot-server/tests/e2e/test_botmanager.py::test_authenticated_minimal_profile",
        "packages/ai-parrot-server/tests/e2e/test_botmanager.py::test_botmanager_offline_boot",
        "packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_controller_and_supervisor_death",
        "packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_timeout_and_grandchild_teardown",
        "packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_two_worktrees_independent",
        "packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_wrong_checkout_cannot_pass",
    }
)
_FROZEN_BROWSER_NODE_ID = "packages/ai-parrot-server/tests/e2e/test_ui.py::test_ui_browser_console_network"
_FROZEN_LIVE_NODE_ID = "packages/ai-parrot-server/tests/e2e/test_mcp_agent_live.py::test_live_google_tool_and_schema"


# ---------------------------------------------------------------------------
# Deterministic plan: real schema parsing, not a mirrored-constant check
# ---------------------------------------------------------------------------


def _load_deterministic_plan():
    return load_plan(_DETERMINISTIC_PLAN, worktree=_REPO_ROOT)


def test_deterministic_plan_loads_and_validates_against_the_real_schema() -> None:
    plan = _load_deterministic_plan()

    assert plan.feature_id == _FEATURE_ID
    assert plan.spec_path == "sdd/specs/agentic-e2e-testing.spec.md"
    assert plan.policy == "required"


def test_deterministic_plan_contains_no_live_tier_scenario() -> None:
    """Spec §4: 'the deterministic CI plan must contain no required live node IDs.'"""
    plan = _load_deterministic_plan()

    assert all(scenario.tier != "live" for scenario in plan.scenarios)
    assert all(scenario.tier != "exploratory" for scenario in plan.scenarios)


def test_deterministic_plan_required_scenarios_cover_exactly_the_frozen_node_ids() -> None:
    plan = _load_deterministic_plan()

    required_node_ids = {node_id for scenario in plan.scenarios if scenario.required for node_id in scenario.node_ids}
    assert required_node_ids == _FROZEN_REQUIRED_NODE_IDS


def test_deterministic_plan_browser_scenario_is_present_but_not_required() -> None:
    """Spec §3 M9: browser lane 'may be separately selected; it is not silently
    skipped as green' -- present, selected every run, but never gates policy."""
    plan = _load_deterministic_plan()

    browser_scenarios = [scenario for scenario in plan.scenarios if _FROZEN_BROWSER_NODE_ID in scenario.node_ids]
    assert len(browser_scenarios) == 1
    assert browser_scenarios[0].required is False
    assert browser_scenarios[0].tier == "deterministic"


def test_deterministic_plan_declares_no_pre_started_targets() -> None:
    """Every scenario's own test module owns its target lifecycle via the
    shared `e2e_supervisor_factory` fixture -- the plan must not ask the
    runner to pre-start a second, redundant target before invoking pytest."""
    plan = _load_deterministic_plan()

    assert plan.targets == {}
    assert all(scenario.target_ids == [] for scenario in plan.scenarios)


@pytest.mark.parametrize("node_id", sorted(_FROZEN_REQUIRED_NODE_IDS | {_FROZEN_BROWSER_NODE_ID}))
def test_deterministic_plan_node_ids_reference_real_files_on_disk(node_id: str) -> None:
    path_part = node_id.split("::", 1)[0]
    assert (_REPO_ROOT / path_part).is_file(), f"plan references a node ID whose file does not exist: {node_id}"


# ---------------------------------------------------------------------------
# Live plan: dispatch-only, explicit opt-in, real schema parsing
# ---------------------------------------------------------------------------


def _load_live_plan():
    return load_plan(_LIVE_PLAN, worktree=_REPO_ROOT)


def test_live_plan_loads_and_declares_exactly_one_required_live_scenario() -> None:
    plan = _load_live_plan()

    assert plan.feature_id == _FEATURE_ID
    assert plan.policy == "required"
    live_scenarios = [scenario for scenario in plan.scenarios if scenario.tier == "live"]
    assert len(live_scenarios) == 1
    assert live_scenarios[0].required is True
    assert live_scenarios[0].node_ids == [_FROZEN_LIVE_NODE_ID]


def test_live_plan_node_id_references_a_real_file_on_disk() -> None:
    path_part = _FROZEN_LIVE_NODE_ID.split("::", 1)[0]
    assert (_REPO_ROOT / path_part).is_file()


def test_live_plan_budget_model_matches_the_pinned_flash_lite_model() -> None:
    """AC11: pinned Flash-Lite resolved through LLMFactory; no Groq/fallback."""
    plan = _load_live_plan()

    assert plan.budget.model == "google:gemini-2.5-flash-lite"
    assert plan.budget.max_calls > 0


# ---------------------------------------------------------------------------
# Invalid input: the real loader still fails closed for a malformed plan
# (never a static-only assertion -- this exercises load_plan's own
# validation, using a synthetic on-disk plan, not either committed plan).
# ---------------------------------------------------------------------------


def test_malformed_plan_with_wildcard_node_id_is_rejected_by_the_real_loader(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    (worktree / "sdd" / "specs").mkdir(parents=True)
    (worktree / "sdd" / "specs" / "example.spec.md").write_text("---\ntype: feature\n---\n\nSpec.\n", encoding="utf-8")
    plan_path = worktree / "e2e-plan.md"
    plan_path.write_text(
        "---\n"
        f"feature_id: {_FEATURE_ID}\n"
        "spec_path: sdd/specs/example.spec.md\n"
        "policy: required\n"
        "targets: {}\n"
        "scenarios:\n"
        "  - id: bad-scenario\n"
        "    tier: deterministic\n"
        "    required: true\n"
        "    node_ids:\n"
        "      - packages/ai-parrot-server/tests/e2e/*\n"
        "---\n\nInvalid plan (wildcard node ID).\n",
        encoding="utf-8",
    )

    with pytest.raises(E2EConfigError):
        load_plan(plan_path, worktree=worktree)


def test_plan_with_required_policy_but_no_required_codified_scenario_is_rejected(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    (worktree / "sdd" / "specs").mkdir(parents=True)
    (worktree / "sdd" / "specs" / "example.spec.md").write_text("---\ntype: feature\n---\n\nSpec.\n", encoding="utf-8")
    plan_path = worktree / "e2e-plan.md"
    plan_path.write_text(
        "---\n"
        f"feature_id: {_FEATURE_ID}\n"
        "spec_path: sdd/specs/example.spec.md\n"
        "policy: required\n"
        "targets: {}\n"
        "scenarios:\n"
        "  - id: optional-only\n"
        "    tier: deterministic\n"
        "    required: false\n"
        "    node_ids:\n"
        "      - packages/ai-parrot-server/tests/e2e/test_mcp_stdio.py::test_stdio_tool_roundtrip_and_eof\n"
        "---\n\nInvalid plan (policy required, no required codified scenario).\n",
        encoding="utf-8",
    )

    with pytest.raises(E2EConfigError):
        load_plan(plan_path, worktree=worktree)


# ---------------------------------------------------------------------------
# `.github/workflows/e2e.yml`: real YAML schema parsing, structural
# assertions -- not static-only substring matching.
#
# Note: PyYAML's default (YAML 1.1) implicit resolver parses a bare `on:`
# mapping key as the boolean `True`, not the string `"on"` -- a well-known
# GitHub Actions/PyYAML interaction. `_trigger_block` reads whichever key is
# actually present so this suite parses the file exactly as PyYAML (the
# same library `parrot.e2e.cli`/`parrot.e2e.plan` themselves use) sees it.
# ---------------------------------------------------------------------------


def _load_workflow() -> dict[str, Any]:
    return yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))


def _trigger_block(workflow: dict[str, Any]) -> dict[str, Any]:
    if "on" in workflow:
        return workflow["on"]
    return workflow[True]


def test_workflow_triggers_are_schedule_and_dispatch_only_never_push_or_pull_request() -> None:
    workflow = _load_workflow()
    triggers = _trigger_block(workflow)

    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert "push" not in triggers
    assert "pull_request" not in triggers


def test_workflow_cron_is_nightly_at_0300() -> None:
    workflow = _load_workflow()
    triggers = _trigger_block(workflow)

    schedules = triggers["schedule"]
    assert isinstance(schedules, list) and len(schedules) == 1
    assert schedules[0]["cron"] == "0 3 * * *"


def test_workflow_dispatch_declares_an_explicit_boolean_live_input() -> None:
    workflow = _load_workflow()
    triggers = _trigger_block(workflow)

    run_live_input = triggers["workflow_dispatch"]["inputs"]["run_live"]
    assert run_live_input["type"] == "boolean"
    assert run_live_input["default"] is False


def test_workflow_concurrency_is_scoped_by_workflow_and_ref() -> None:
    workflow = _load_workflow()

    group = workflow["concurrency"]["group"]
    assert "github.workflow" in group
    assert "github.ref" in group


def test_workflow_declares_deterministic_and_live_jobs() -> None:
    workflow = _load_workflow()
    jobs = workflow["jobs"]

    assert set(jobs) == {"deterministic", "live"}


def test_deterministic_job_runs_the_declared_plan_and_has_no_secrets_reference() -> None:
    workflow = _load_workflow()
    deterministic_job = workflow["jobs"]["deterministic"]

    run_steps = [step for step in deterministic_job["steps"] if "run" in step]
    plan_invocations = [step for step in run_steps if "parrot e2e run" in step["run"]]
    assert len(plan_invocations) == 1
    assert "packages/ai-parrot-server/tests/e2e/plans/deterministic.md" in plan_invocations[0]["run"]

    # Structural, not string-only: walk every step's own `env`/`with` mapping
    # (never the raw YAML text) and confirm no `secrets.` expression is used
    # anywhere in the deterministic job -- it must need no provider secret.
    for step in deterministic_job["steps"]:
        for mapping_key in ("env", "with"):
            mapping = step.get(mapping_key) or {}
            for value in mapping.values():
                assert "secrets." not in str(value)


def test_live_job_is_dispatch_only_explicit_opt_in_and_needs_deterministic() -> None:
    workflow = _load_workflow()
    live_job = workflow["jobs"]["live"]

    assert live_job["needs"] == "deterministic"
    condition = live_job["if"]
    assert "workflow_dispatch" in condition
    assert "run_live" in condition


def test_live_job_runs_the_declared_plan_and_requires_google_api_key_secret() -> None:
    workflow = _load_workflow()
    live_job = workflow["jobs"]["live"]

    run_steps = [step for step in live_job["steps"] if "run" in step]
    plan_invocations = [step for step in run_steps if "parrot e2e run" in step["run"]]
    assert len(plan_invocations) == 1
    assert "packages/ai-parrot-server/tests/e2e/plans/live.md" in plan_invocations[0]["run"]

    live_run_env = next(step["env"] for step in run_steps if "parrot e2e run" in step["run"])
    assert live_run_env["PARROT_TEST_REAL_LLM"] == "1"
    assert "secrets.GOOGLE_API_KEY" in str(live_run_env["GOOGLE_API_KEY"])


def test_no_job_uses_a_broad_root_e2e_marker_or_suppresses_collection_errors() -> None:
    """Spec §3 M9: 'no broad root pytest -m e2e, no collection-error suppression.'"""
    workflow = _load_workflow()

    for job in workflow["jobs"].values():
        for step in job["steps"]:
            command = step.get("run", "")
            assert "-m e2e" not in command
            assert '-m "e2e"' not in command
            assert "--continue-on-collection-errors" not in command


def test_every_job_uploads_evidence_only_on_failure() -> None:
    """Spec §3 M9: 'logs/evidence upload on failure.'"""
    workflow = _load_workflow()

    for job_name, job in workflow["jobs"].items():
        upload_steps = [step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact")]
        assert upload_steps, f"job {job_name!r} never uploads evidence"
        for step in upload_steps:
            assert step.get("if") == "failure()"
