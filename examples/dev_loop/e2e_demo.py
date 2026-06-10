"""FEAT-129 — Dev-Loop Orchestration: self-contained end-to-end demo.

Runs the REAL seven-node ``AgentsFlow`` (engine, scheduler, OR-join
routing, ``DevLoopRunner`` semaphore, lifecycle telemetry) end-to-end —
but with every external service simulated in-process:

* ``ClaudeCodeDispatcher``  → ``SimulatedDispatcher`` (canned subagent outputs)
* Jira toolkit              → ``SimulatedJira`` (records every call)
* Redis streams             → ``FakeRedis`` (captures XADDs in memory)
* git push / gh pr create   → patched to no-ops returning a fake PR URL
* Plan/summary LLM          → ``FakeLLM`` (deterministic text)

No Redis, no ``claude`` CLI, no Jira instance, no API keys required.
For the real-mode equivalents see ``quickstart.py`` (programmatic) and
``server.py`` (HTTP + WebSocket UI).

Run::

    source .venv/bin/activate
    python examples/dev_loop/e2e_demo.py

Four scenarios are executed:

1. Bug brief, everything green        → PR opened, Jira "Ready to Deploy".
2. Enhancement brief                  → BugIntake is skip-propagated.
3. QA fails                           → DeploymentHandoff skipped, escalation.
4. Hard error in Development          → on_error fan-in fires FailureHandler.
"""
from __future__ import annotations

import os

# Keep the duplicate-ticket JQL search quiet (a project key must exist for
# the search branch to run; the simulated Jira returns "empty" anyway).
os.environ.setdefault("JIRA_PROJECT", "DEMO")

import asyncio
import json
import logging
import tempfile
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from parrot import conf
from parrot.core.events.lifecycle.base import LifecycleEvent
from parrot.core.events.lifecycle.global_registry import get_global_registry
from parrot.flows.dev_loop import (
    BugBrief,
    DevLoopRunner,
    QAReport,
    ResearchOutput,
    ShellCriterion,
    WorkBrief,
    build_dev_loop_flow,
)
from parrot.flows.dev_loop.models import DevelopmentOutput
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode

logging.basicConfig(level=logging.WARNING)  # keep the demo output readable


# ---------------------------------------------------------------------------
# Simulated collaborators
# ---------------------------------------------------------------------------


class SimulatedDispatcher:
    """Stand-in for ``ClaudeCodeDispatcher`` with canned subagent outputs.

    Args:
        worktree_base: Directory used for the fake worktree path.
        qa_passed: Whether the simulated ``sdd-qa`` run reports success.
        fail_at_node: Optional node_id whose dispatch raises (hard error).
    """

    def __init__(
        self,
        worktree_base: str,
        *,
        qa_passed: bool = True,
        fail_at_node: Optional[str] = None,
    ) -> None:
        self._worktree_base = worktree_base
        self._qa_passed = qa_passed
        self._fail_at_node = fail_at_node

    async def dispatch(
        self, *, brief: Any, profile: Any, output_model: type,
        run_id: str, node_id: str, cwd: str,
    ) -> Any:
        print(f"    [dispatch] {node_id:<12} → subagent {profile.subagent!r}")
        await asyncio.sleep(0.05)  # simulate subagent wall-clock
        if node_id == self._fail_at_node:
            raise RuntimeError(f"simulated subagent crash in {node_id!r}")
        if output_model is ResearchOutput:
            return ResearchOutput(
                jira_issue_key="",  # ResearchNode injects the real key
                spec_path="sdd/specs/fix-customer-sync.spec.md",
                feat_id="FEAT-999",
                branch_name="feat-999-fix-customer-sync",
                worktree_path=os.path.join(
                    self._worktree_base, "feat-999-fix-customer-sync"
                ),
                log_excerpts=["ERROR row 1500 dropped (simulated excerpt)"],
            )
        if output_model is DevelopmentOutput:
            return DevelopmentOutput(
                files_changed=["etl/customers/sync.yaml", "tests/test_sync.py"],
                commit_shas=["a1b2c3d"],
                summary="Fixed off-by-one in the batch flush (simulated).",
            )
        if output_model is QAReport:
            return QAReport(
                passed=self._qa_passed,
                criterion_results=[],
                lint_passed=self._qa_passed,
                notes="(simulated QA run)",
            )
        raise AssertionError(f"unexpected output_model: {output_model!r}")


class SimulatedJira:
    """Records every Jira interaction the flow performs."""

    def __init__(self) -> None:
        self.actions: List[str] = []
        self._counter = 0

    async def jira_create_issue(self, *, summary: str, issuetype: str, **kw: Any) -> Dict:
        self._counter += 1
        key = f"DEMO-{self._counter}"
        self.actions.append(f"create_issue [{issuetype}] {key}: {summary[:50]}…")
        return {"key": key}

    async def jira_get_issue(self, issue: str, **kw: Any) -> Dict:
        return {"status": "error"}  # force the search/create path

    async def jira_search_issues(self, **kw: Any) -> Dict:
        return {"status": "empty"}

    async def jira_transition_issue(self, *, issue: str, transition: str, **kw: Any) -> Dict:
        self.actions.append(f"transition {issue} → {transition!r}")
        return {"ok": True}

    async def jira_add_comment(self, *, issue: str, body: str, **kw: Any) -> Dict:
        self.actions.append(f"comment on {issue}: {body.splitlines()[0][:60]}…")
        return {"id": "c1"}

    async def jira_assign_issue(self, *, issue: str, assignee: str, **kw: Any) -> Dict:
        self.actions.append(f"assign {issue} → {assignee}")
        return {"ok": True}


class FakeRedis:
    """In-memory stand-in for redis.asyncio — captures stream XADDs."""

    def __init__(self) -> None:
        self.entries: List[Tuple[str, Dict]] = []

    async def xadd(self, key: str, fields: Dict, **kw: Any) -> bytes:
        self.entries.append((key, json.loads(fields["event"])))
        return b"1-0"

    async def aclose(self) -> None:  # pragma: no cover - symmetry
        return None


class FakeLLM:
    """Deterministic stand-in for the plan/summary LLM clients."""

    async def ask(self, prompt: str, **kw: Any) -> Any:
        return SimpleNamespace(
            response="1. Reproduce with a 1500-row CSV\n"
                     "2. Fix the batch flush boundary\n"
                     "3. Add a regression test",
        )


# ---------------------------------------------------------------------------
# Scenario wiring
# ---------------------------------------------------------------------------


def make_brief(kind: str = "bug") -> WorkBrief:
    """A realistic brief for the demo scenarios."""
    cls = BugBrief if kind == "bug" else WorkBrief
    return cls(
        kind=kind,
        summary="Customer sync drops the last row when input has >1000 records",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[
            ShellCriterion(name="lint-clean", command="ruff check ."),
        ],
        reporter="reporter@example.com",
        escalation_assignee="oncall@example.com",
    )


def build_simulated_flow(
    dispatcher: SimulatedDispatcher, jira: SimulatedJira, fake_redis: FakeRedis
):
    """Build the real flow, then swap its I/O edges for the simulators."""
    flow = build_dev_loop_flow(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={},
        redis_url="redis://demo-not-used:0/0",
    )
    # Point every Redis consumer at the in-memory capture (the publisher
    # plus the two intake nodes that XADD their own validation events).
    flow._event_publisher._redis = fake_redis
    for node_id in ("intent_classifier", "bug_intake"):
        flow._nodes[node_id]._redis = fake_redis
    # Deterministic LLM stand-ins for the plan/summary helpers.
    flow._nodes["research"]._plan_client = FakeLLM()
    flow._nodes["research"]._summarizer_client = FakeLLM()
    return flow


async def run_scenario(
    title: str,
    *,
    worktree_base: str,
    kind: str = "bug",
    qa_passed: bool = True,
    fail_at_node: Optional[str] = None,
) -> None:
    """Build, run, and report one end-to-end scenario."""
    print(f"\n{'=' * 70}\n  {title}\n{'=' * 70}")

    dispatcher = SimulatedDispatcher(
        worktree_base, qa_passed=qa_passed, fail_at_node=fail_at_node
    )
    jira = SimulatedJira()
    fake_redis = FakeRedis()
    flow = build_simulated_flow(dispatcher, jira, fake_redis)

    # Typed FEAT-176 lifecycle events: collect everything this run emits
    # on the global registry (OTel/logging subscribers would see the same).
    lifecycle: List[LifecycleEvent] = []

    async def collect(event: LifecycleEvent) -> None:
        lifecycle.append(event)

    registry = get_global_registry()
    subscription = registry.subscribe(LifecycleEvent, collect)
    try:
        runner = DevLoopRunner(flow, max_concurrent_runs=2)
        result = await runner.run(make_brief(kind))
        await asyncio.sleep(0.1)  # drain fire-and-forget telemetry tasks
    finally:
        registry.unsubscribe(subscription)

    executed = list(result.responses)
    skipped = sorted(set(flow._nodes) - set(executed) - set(result.errors))
    print(f"\n  status      : {result.status.value}")
    print(f"  executed    : {executed}")
    print(f"  failed      : {list(result.errors) or '—'}")
    print(f"  skipped     : {skipped or '—'}")
    print(f"  flow output : {result.output}")

    print("\n  Jira actions (simulated):")
    for action in jira.actions:
        print(f"    - {action}")

    stream_kinds = [e["kind"] for _k, e in fake_redis.entries]
    print(f"\n  Redis stream events captured: {len(stream_kinds)}")
    print(f"    {stream_kinds}")

    flow_events = [type(e).__name__ for e in lifecycle if "Flow" in type(e).__name__ or "Node" in type(e).__name__]
    trace_ids = {e.trace_context.trace_id for e in lifecycle}
    print(f"\n  FEAT-176 lifecycle events: {len(flow_events)} "
          f"({len(trace_ids)} trace)")
    for event in lifecycle:
        name = type(event).__name__
        node = getattr(event, "node_id", "") or "(flow)"
        extra = ""
        if hasattr(event, "duration_ms") and event.duration_ms:
            extra = f"  {event.duration_ms:7.1f} ms"
        if hasattr(event, "status") and getattr(event, "status", ""):
            extra += f"  status={event.status}"
        print(f"    {name:<22} {node:<20}{extra}")


async def main() -> None:
    # SIMULATION: neutralize the two real-world side effects of the
    # handoff node (git push + gh pr create) for this offline demo.
    async def _fake_push(self: Any, branch: str, cwd: str) -> None:
        print(f"    [git] push -u origin {branch} (simulated)")

    async def _fake_pr(self: Any, branch: str, title: str, body: str) -> str:
        print(f"    [gh] pr create --head {branch} (simulated)")
        return "https://github.com/example/repo/pull/4242"

    DeploymentHandoffNode._push_branch = _fake_push       # type: ignore[method-assign]
    DeploymentHandoffNode._create_pr = _fake_pr           # type: ignore[method-assign]

    with tempfile.TemporaryDirectory(prefix="devloop-demo-") as tmp:
        # Keep the worktree-safety check inside the sandbox dir.
        conf.WORKTREE_BASE_PATH = tmp

        await run_scenario(
            "1) Bug brief — happy path (PR + Ready to Deploy)",
            worktree_base=tmp,
        )
        await run_scenario(
            "2) Enhancement brief — BugIntake is skip-propagated",
            worktree_base=tmp, kind="enhancement",
        )
        await run_scenario(
            "3) QA fails — handoff skipped, escalation to a human",
            worktree_base=tmp, qa_passed=False,
        )
        await run_scenario(
            "4) Hard error in Development — on_error fan-in fires",
            worktree_base=tmp, fail_at_node="development",
        )

    print("\nDone. See quickstart.py / server.py for the real-mode versions.")


if __name__ == "__main__":
    asyncio.run(main())
