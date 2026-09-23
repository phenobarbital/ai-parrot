"""Execute one reviewed E2E plan and persist its final, immutable evidence.

The runner deliberately owns orchestration only: plans are validated by
``plan.load_plan``, targets by ``E2ESupervisor``, and pytest results by the
explicit ``pytest_plugin`` bridge.  It never discovers tests or starts a
provider during readiness.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import signal
import sys
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from parrot.e2e.errors import (
    EXIT_BLOCKED,
    EXIT_EVIDENCE,
    EXIT_FAILURE,
    EXIT_SIGINT,
    EXIT_SIGTERM,
    EXIT_SUCCESS,
    E2EError,
    E2EPrerequisiteError,
)
from parrot.e2e.evidence import capture_identity
from parrot.e2e.models import E2EPlan, E2EVerdict, ScenarioResult, ScenarioSpec
from parrot.e2e.plan import load_plan
from parrot.e2e.pytest_plugin import ENV_CONTROL_SOCKET, ENV_OWNER_ID, ENV_RESULTS_PATH, ENV_RUN_ID
from parrot.e2e.supervisor import E2ESupervisor

__all__ = ["run_plan"]

logger = logging.getLogger(__name__)
_VERDICT_NAME = "e2e-verdict.json"
_POINTER_NAME = "latest.json"


@dataclass
class _LiveBudgetContext:
    """One shared live budget identity for a single runner invocation.

    The optional live adapter currently has no public budget-hook interface.
    Keeping this single object in the run context prevents the runner from
    creating per-scenario allowances and documents the hand-off boundary
    without making a provider call.
    """

    plan: E2EPlan


async def run_plan(plan_path: Path, *, worktree: Path, owner_id: str) -> E2EVerdict:
    """Execute reviewed scenarios under supervision and atomically record evidence.

    Args:
        plan_path: The contained Markdown plan to validate and run.
        worktree: The checkout containing the plan, source, and evidence root.
        owner_id: Stable owner ID used to authorize all supervised targets.

    Returns:
        The completed verdict, including cleanup and source identities.
    """
    plan = load_plan(plan_path, worktree=worktree)
    resolved_worktree = worktree.resolve()
    started_at = datetime.now(timezone.utc)
    source_before = await capture_identity(plan, worktree=resolved_worktree)
    run_id = f"run-{uuid.uuid4().hex}"
    evidence_dir = resolved_worktree / "sdd" / "state" / plan.feature_id / "e2e" / "runs" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    live_budget = _LiveBudgetContext(plan=plan)
    supervisor = E2ESupervisor(worktree=resolved_worktree, owner_id=owner_id, feature_id=plan.feature_id)
    results: list[ScenarioResult] = []
    selected: list[str] = []
    collected: list[str] = []
    cleanup_results: dict[str, bool] = {}
    artifact_hashes: dict[str, str] = {}
    interrupted_exit: int | None = None

    try:
        if plan.policy != "none":
            async with asyncio.timeout(plan.run_timeout_s):
                for scenario in plan.scenarios:
                    scenario_results, scenario_collected, hashes = await _run_scenario(
                        scenario,
                        plan=plan,
                        supervisor=supervisor,
                        worktree=resolved_worktree,
                        owner_id=owner_id,
                        evidence_dir=evidence_dir,
                        live_budget=live_budget,
                        prior_results=results,
                        cleanup_results=cleanup_results,
                    )
                    results.extend(scenario_results)
                    selected.extend(scenario.node_ids)
                    collected.extend(scenario_collected)
                    artifact_hashes.update(hashes)
    except KeyboardInterrupt:
        interrupted_exit = EXIT_SIGINT
    except asyncio.CancelledError:
        interrupted_exit = EXIT_SIGTERM
    except TimeoutError:
        results.extend(_blocked_results(plan.scenarios, "run_timeout", cleanup_results))
    finally:
        for target_run_id in list(supervisor._runs):
            try:
                state = await supervisor.stop(target_run_id)
                cleanup_results[target_run_id] = state.cleanup_complete
            except Exception as exc:  # Persist unresolved teardown in final evidence.
                logger.exception("E2E cleanup failed for %s", target_run_id)
                cleanup_results[target_run_id] = False

    source_after = await capture_identity(plan, worktree=resolved_worktree)
    status, exit_code, gate_satisfied = _verdict_status(plan, results, cleanup_results, source_before == source_after, interrupted_exit)
    completed_at = datetime.now(timezone.utc)
    verdict = E2EVerdict(
        feature_id=plan.feature_id,
        run_id=run_id,
        policy=plan.policy,
        source_identity_before=source_before,
        source_identity_after=source_after,
        selected_node_ids=selected,
        collected_node_ids=collected,
        results=results,
        counts=dict(Counter(result.outcome for result in results)),
        argv=["parrot", "e2e", "run", "--plan", str(plan_path)],
        exit_code=exit_code,
        cleanup_results=cleanup_results,
        artifact_hashes=artifact_hashes,
        status=status,
        gate_satisfied=gate_satisfied,
        started_at=started_at,
        completed_at=completed_at,
    )
    _write_json(evidence_dir / _VERDICT_NAME, verdict.model_dump(mode="json"))
    _write_json(
        resolved_worktree / "sdd" / "state" / plan.feature_id / "e2e" / _POINTER_NAME,
        {"run_id": run_id},
    )
    return verdict


async def _run_scenario(
    scenario: ScenarioSpec,
    *,
    plan: E2EPlan,
    supervisor: E2ESupervisor,
    worktree: Path,
    owner_id: str,
    evidence_dir: Path,
    live_budget: _LiveBudgetContext,
    prior_results: list[ScenarioResult],
    cleanup_results: dict[str, bool],
) -> tuple[list[ScenarioResult], list[str], dict[str, str]]:
    """Run one declared scenario or record every node as explicitly blocked."""
    if scenario.tier == "exploratory":
        return [], [], {}
    reason = _scenario_block_reason(scenario, prior_results)
    if scenario.tier == "live" and not _live_enabled():
        reason = "live_opt_in_or_provider_key_missing"
    if reason:
        return _results_for_nodes(scenario, "blocked", reason), [], {}

    target_run_ids: list[str] = []
    try:
        for target_id in scenario.target_ids:
            state = await supervisor.start(target_id, plan.targets[target_id])
            target_run_ids.append(state.run_id)
        # The one context is intentionally retained for the entire run.  It
        # is not consulted by readiness and no model operation occurs here.
        _ = live_budget
        bridge_path = evidence_dir / f"pytest-{scenario.id}.json"
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "parrot.e2e.pytest_plugin",
            *scenario.node_ids,
            cwd=worktree,
            env={
                **os.environ,
                ENV_RUN_ID: target_run_ids[0] if target_run_ids else f"{scenario.id}-no-target",
                ENV_OWNER_ID: owner_id,
                ENV_CONTROL_SOCKET: "",
                ENV_RESULTS_PATH: str(bridge_path),
                "PARROT_TEST_E2E": "1",
            },
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=scenario.timeout_s)
        except asyncio.TimeoutError:
            process.terminate()
            await process.wait()
            return _results_for_nodes(scenario, "failed", "scenario_timeout", target_run_ids), [], {}
        bridge = _load_bridge(bridge_path)
        hashes = {bridge_path.name: _sha256(bridge_path)}
        return _bridge_results(scenario, bridge, target_run_ids), list(bridge.get("collected_node_ids", [])), hashes
    except E2EPrerequisiteError as exc:
        return _results_for_nodes(scenario, "blocked", exc.reason_code or "prerequisite_missing", target_run_ids), [], {}
    except E2EError as exc:
        return _results_for_nodes(scenario, "failed", exc.reason_code or "target_failure", target_run_ids), [], {}
    except Exception as exc:
        logger.exception("scenario %s failed before pytest evidence completed", scenario.id)
        return _results_for_nodes(scenario, "failed", type(exc).__name__.lower(), target_run_ids), [], {}
    finally:
        for target_run_id in target_run_ids:
            try:
                state = await supervisor.stop(target_run_id)
                cleanup_results[target_run_id] = state.cleanup_complete
            except Exception:
                logger.exception("scenario cleanup failed for %s", target_run_id)
                cleanup_results[target_run_id] = False


def _scenario_block_reason(scenario: ScenarioSpec, prior_results: list[ScenarioResult]) -> str | None:
    """Return an explicit unmet-prerequisite reason, if one exists."""
    passed = {result.scenario_id for result in prior_results if result.outcome == "passed"}
    missing = [item for item in scenario.prerequisites if item not in passed]
    return f"prerequisite_not_passed:{','.join(missing)}" if missing else None


def _live_enabled() -> bool:
    """Require both explicit live opt-in and the configured provider credential."""
    return os.environ.get("PARROT_TEST_REAL_LLM") == "1" and bool(os.environ.get("GOOGLE_API_KEY"))


def _results_for_nodes(
    scenario: ScenarioSpec, outcome: str, reason: str, target_run_ids: list[str] | None = None
) -> list[ScenarioResult]:
    """Build one uniform result per explicitly declared node."""
    return [
        ScenarioResult(
            scenario_id=scenario.id,
            node_id=node_id,
            outcome=outcome,
            reason_code=reason,
            duration_s=0,
            target_run_ids=target_run_ids or [],
        )
        for node_id in scenario.node_ids
    ]


def _load_bridge(path: Path) -> dict[str, Any]:
    """Load the pytest bridge output, failing closed on absent or malformed data."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise E2EPrerequisiteError("pytest bridge output was not produced", reason_code="pytest_bridge_missing") from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get("results"), list):
        raise E2EPrerequisiteError("pytest bridge output is malformed", reason_code="pytest_bridge_malformed")
    return loaded


def _bridge_results(scenario: ScenarioSpec, bridge: dict[str, Any], target_run_ids: list[str]) -> list[ScenarioResult]:
    """Translate observed pytest phases without converting missing coverage to pass."""
    observed = {item.get("node_id"): item for item in bridge["results"] if isinstance(item, dict)}
    exit_code = bridge.get("exit_status")
    results: list[ScenarioResult] = []
    for node_id in scenario.node_ids:
        item = observed.get(node_id)
        if item is None:
            results.extend(_results_for_nodes(scenario.model_copy(update={"node_ids": [node_id]}), "missing", "node_not_collected", target_run_ids))
            continue
        outcome = str(item.get("outcome", "failed"))
        if outcome not in {"passed", "failed", "skipped", "xfailed", "xpassed"}:
            outcome = "failed"
        results.append(
            ScenarioResult(
                scenario_id=scenario.id,
                node_id=node_id,
                outcome=outcome,
                reason_code=None if outcome == "passed" else f"pytest_{outcome}",
                setup_outcome=item.get("setup_outcome"),
                call_outcome=item.get("call_outcome"),
                teardown_outcome=item.get("teardown_outcome"),
                exit_code=exit_code if isinstance(exit_code, int) else None,
                duration_s=float(item.get("duration_s", 0)),
                target_run_ids=target_run_ids,
            )
        )
    return results


def _blocked_results(scenarios: list[ScenarioSpec], reason: str, cleanup_results: dict[str, bool]) -> list[ScenarioResult]:
    """Record remaining codified coverage after a run-level timeout."""
    return [result for scenario in scenarios if scenario.tier != "exploratory" for result in _results_for_nodes(scenario, "blocked", reason)]


def _verdict_status(
    plan: E2EPlan,
    results: list[ScenarioResult],
    cleanup_results: dict[str, bool],
    source_unchanged: bool,
    interrupted_exit: int | None,
) -> tuple[str, int, bool]:
    """Apply the spec §2 exit/status mapping to complete run evidence."""
    if interrupted_exit is not None:
        return "BLOCKED", interrupted_exit, False
    if not source_unchanged:
        return "FAIL", EXIT_EVIDENCE, False
    if not all(cleanup_results.values()):
        return "FAIL", EXIT_FAILURE, False
    if plan.policy == "none":
        return "PASS", EXIT_SUCCESS, True
    required = {node_id for item in plan.scenarios if item.required for node_id in item.node_ids}
    by_node = {result.node_id: result for result in results}
    if any(by_node.get(node_id) is None or by_node[node_id].outcome == "blocked" for node_id in required):
        return "BLOCKED", EXIT_BLOCKED, False
    if any(by_node[node_id].outcome != "passed" for node_id in required):
        return "FAIL", EXIT_FAILURE, False
    return "PASS", EXIT_SUCCESS, True


def _write_json(path: Path, value: dict[str, Any]) -> None:
    """Atomically write a private JSON evidence file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
        json.dump(value, temporary, sort_keys=True, separators=(",", ":"))
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    os.chmod(temporary_path, 0o600)
    os.replace(temporary_path, path)


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of one immutable evidence artifact."""
    return hashlib.sha256(path.read_bytes()).hexdigest()
