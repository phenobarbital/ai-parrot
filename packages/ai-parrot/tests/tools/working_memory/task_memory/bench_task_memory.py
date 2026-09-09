"""TASK-3005 — AC16 acceptance metrics and documentation checks.

Run it directly::

    PYTHONPATH=packages/ai-parrot/src \\
      python packages/ai-parrot/tests/tools/working_memory/task_memory/bench_task_memory.py

Named ``bench_`` rather than ``test_`` on purpose: pytest does not
collect it by default, because the 256 MiB measurement is far too slow
for the normal suite. The three required cases are the module-level
``test_docs_examples``, ``test_metrics`` and ``test_traceability``
functions, which :func:`main` runs and which pytest can be pointed at
explicitly.

**This module RECORDS numbers; it does not assert latency.** The spec is
explicit that no latency SLO may be claimed before measurement, so the
only assertions here are on things that are actually invariants —
deterministic byte and token caps, exactly-once recovery, and the
refusal of unverifiable evidence. Timings are reported for a human to
read, with the environment that produced them.

The 8/64/256 MiB snapshot and fingerprint costs are NOT re-implemented
here; they already live in ``bench_snapshot_costs.py`` and are imported,
so a single definition of that measurement stays authoritative.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# The sibling benchmark owns the payload-size measurements and the
# environment record; importing keeps one definition of each.
try:  # pragma: no cover - import shim for direct execution
    from .bench_snapshot_costs import TARGET_MIB, environment, measure_dataframe, measure_json_text
except ImportError:  # pragma: no cover - running as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bench_snapshot_costs import TARGET_MIB, environment, measure_dataframe, measure_json_text

from parrot.memory.compaction.models import ToolInvocation, ToolStatus
from parrot.memory.compaction.tokens import get_default_counter
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.context import turn_session
from parrot.tools.working_memory.task_memory.models import (
    EvidenceRef,
    InitialStepSpec,
    TaskScope,
)
from parrot.tools.working_memory.task_memory.observer import InvocationObserver
from parrot.tools.working_memory.task_memory.recall import MAX_RECALL_TOKENS, RecallReader, RecallStatus
from parrot.tools.working_memory.task_memory.store.memory import InMemoryTaskMemoryStore
from parrot.tools.working_memory.task_memory.tools import TaskMemory

#: The documentation this task produces, checked by two of the cases.
#: parents: task_memory/working_memory/tools/tests/ai-parrot/packages/<repo root>
DOC_PATH = Path(__file__).resolve().parents[6] / "docs" / "memory" / "recoverable-task-memory.md"

#: Repetitions for the timing samples. Small on purpose: these are
#: recorded observations, not a statistical claim.
SAMPLES: int = 20


def _scope(session: str = "sess-1") -> TaskScope:
    """Build a scope.

    Args:
        session: Session id.

    Returns:
        The scope.
    """
    return TaskScope(chatbot_id="bot-a", user_id="user-1", session_id=session)


async def _task_with_plan(tm: TaskMemory, steps: int) -> str:
    """Create a task with ``steps`` planned steps.

    Args:
        tm: The composition root.
        steps: How many steps to plan.

    Returns:
        The task id.
    """
    from parrot.tools.working_memory.task_memory.models import AddStep, PlanChanges

    # One journal event may not exceed Limits.MAX_EVENT_PAYLOAD_BYTES
    # (8 KiB), so a large plan is built in batches — which is also how a
    # real plan grows, rather than arriving whole.
    batch = 20
    first = min(steps, batch)
    specs = [InitialStepSpec(label=f"s{i}", title=f"step {i}", description="d" * 40) for i in range(first)]
    result = await tm.service.begin_task(
        tm.scope, goal="benchmark task " + ("g" * 80), constraints=("c" * 60,), steps=specs
    )
    task_id = result.state.task_id
    tm.select(task_id)

    added = first
    while added < steps:
        chunk = min(batch, steps - added)
        changes = PlanChanges(
            changes=tuple(
                AddStep(label=f"s{i}", title=f"step {i}", description="d" * 40) for i in range(added, added + chunk)
            )
        )
        revision = (await tm.service.get_task(tm.scope, task_id)).state.revision
        await tm.service.update_plan(tm.scope, task_id, expected_revision=revision, changes=changes)
        added += chunk
    return task_id


# ─────────────────────────────────────────────────────────────
# AC16: recall tokens and build time
# ─────────────────────────────────────────────────────────────


async def measure_recall() -> List[Dict[str, Any]]:
    """Measure recall build time and token cost at several plan sizes.

    Returns:
        One record per plan size.

    Raises:
        AssertionError: If a recall exceeds the requested token budget.
            That cap is an invariant, unlike the timings.
    """
    rows: List[Dict[str, Any]] = []
    counter = get_default_counter()
    for steps in (5, 25, 100):
        tm = TaskMemory(InMemoryTaskMemoryStore(), InMemoryArtifactStore(), _scope())
        task_id = await _task_with_plan(tm, steps)

        # Warm once so the first-call import cost is not reported as the
        # steady-state cost.
        await tm.reader.recall(tm.scope, task_id, use_cache=False)

        durations: List[float] = []
        result = None
        for _ in range(SAMPLES):
            started = time.perf_counter()
            result = await tm.reader.recall(tm.scope, task_id, use_cache=False)
            durations.append(time.perf_counter() - started)

        assert result is not None and result.status is RecallStatus.OK, result
        budget = tm.config.recall_max_tokens
        assert result.estimated_tokens <= budget, f"recall exceeded its budget: {result.estimated_tokens} > {budget}"
        assert result.estimated_tokens <= MAX_RECALL_TOKENS

        durations.sort()
        rows.append(
            {
                "plan_steps": steps,
                "samples": SAMPLES,
                "estimated_tokens": result.estimated_tokens,
                "tokens_estimated": result.tokens_estimated,
                "token_budget": budget,
                "payload_bytes": result.payload_bytes,
                "counter": getattr(counter, "name", "unknown"),
                "build_seconds_min": round(durations[0], 6),
                "build_seconds_median": round(durations[len(durations) // 2], 6),
                "build_seconds_max": round(durations[-1], 6),
                "truncation": result.truncation.model_dump(mode="json"),
            }
        )
    return rows


# ─────────────────────────────────────────────────────────────
# AC16: observer overhead
# ─────────────────────────────────────────────────────────────


async def measure_observer_overhead() -> Dict[str, Any]:
    """Measure the cost the observer adds to a dispatch.

    Compares the same number of begin/finish pairs against a no-op
    baseline. Journalling is left OFF (``append=None``) for the capture
    figure and ON for the journalled figure, because those are two
    genuinely different deployments and reporting one as the other would
    be misleading.

    Returns:
        The recorded overheads.
    """
    calls = 200
    scope = _scope()

    def _baseline() -> float:
        """Time the loop with no observer at all."""
        started = time.perf_counter()
        for i in range(calls):
            _ = {"tool": f"t{i}", "ok": True}
        return time.perf_counter() - started

    async def _observed(*, journal: bool) -> float:
        """Time the same loop through the observer.

        Args:
            journal: Whether to append events as well as capture them.

        Returns:
            Elapsed seconds.
        """
        tm = TaskMemory(InMemoryTaskMemoryStore(), InMemoryArtifactStore(), scope)
        task_id = await _task_with_plan(tm, 3)

        # The append MUST be bound to the store the session's task lives
        # in. Closing over a different one makes every append fail, and
        # a fail-closed observer then refuses to run the tool at all.
        async def _append(task: str, events: Any) -> Any:
            """Append to this run's own journal.

            Args:
                task: Task id.
                events: Events to append.

            Returns:
                The append result.
            """
            return await tm.store.append_events(scope, task, tuple(events))

        with turn_session(scope, task_id=task_id) as session:
            observer = InvocationObserver(session, append=_append if journal else None)
            started = time.perf_counter()
            for i in range(calls):
                call = await observer.begin(f"tool_{i}")
                # The same call shape the dispatcher uses: hand it the
                # value and let the observer classify the outcome.
                await observer.finish(call, value={"status": "ok", "rows": i})
            return time.perf_counter() - started

    baseline = min(_baseline() for _ in range(3))
    capture_only = await _observed(journal=False)
    journalled = await _observed(journal=True)

    return {
        "calls": calls,
        "baseline_seconds": round(baseline, 6),
        "capture_only_seconds": round(capture_only, 6),
        "journalled_seconds": round(journalled, 6),
        "capture_us_per_call": round(capture_only / calls * 1e6, 2),
        "journalled_us_per_call": round(journalled / calls * 1e6, 2),
        "note": (
            "Recorded, not an SLO. Capture-only is the disabled-journal path; the journalled "
            "figure includes an in-memory append and is NOT representative of PostgreSQL."
        ),
    }


# ─────────────────────────────────────────────────────────────
# AC16: invalid-reference rate
# ─────────────────────────────────────────────────────────────


async def measure_invalid_reference_rate() -> Dict[str, Any]:
    """Measure how often an unverifiable evidence reference is refused.

    Returns:
        Counts and the refusal rate.

    Raises:
        AssertionError: If any invalid reference is accepted. This one IS
            an invariant: accepting unverifiable evidence is precisely
            the failure the feature exists to prevent.
    """
    from parrot.tools.working_memory.task_memory.validators import CompletionValidationError

    tm = TaskMemory(InMemoryTaskMemoryStore(), InMemoryArtifactStore(), _scope())
    task_id = await _task_with_plan(tm, 4)
    state = (await tm.service.get_task(tm.scope, task_id)).state
    steps = [s.step_id for s in state.steps]

    attempted = 0
    refused = 0
    reasons: Dict[str, int] = {}

    async def _try(step: str, refs: Tuple[Any, ...], label: str) -> None:
        """Attempt a completion and record whether it was refused.

        Args:
            step: The step to complete.
            refs: Evidence references.
            label: Category name for the report.
        """
        nonlocal attempted, refused
        attempted += 1
        current = (await tm.service.get_task(tm.scope, task_id)).state.revision
        try:
            await tm.service.complete_step(
                tm.scope, task_id, step, expected_revision=current, evidence_refs=refs, note="n"
            )
        except (CompletionValidationError, Exception):  # noqa: BLE001 — any refusal counts
            refused += 1
            reasons[label] = reasons.get(label, 0) + 1

    # A reference to an artifact that was never registered.
    await _try(steps[0], (EvidenceRef(artifact_id="art_missing", version=1),), "missing_artifact")
    # A version that does not exist for an artifact that does.
    real = await tm.artifacts.put(tm.scope, "present", {"a": 1}, task_id=task_id)
    real_ref = real.ref if hasattr(real, "ref") else real
    await _try(steps[1], (EvidenceRef(artifact_id=real_ref.artifact_id, version=99),), "missing_version")
    # No evidence at all, on a policy that requires it.
    await _try(steps[2], (), "no_evidence")

    # A bare alias never even parses into a reference.
    bare_rejected = 0
    for bare in ("just_an_alias", "table", "results"):
        try:
            EvidenceRef.parse(bare)
        except Exception:  # noqa: BLE001 — a rejection is the point
            bare_rejected += 1

    assert refused == attempted, (
        f"{attempted - refused} invalid reference(s) were ACCEPTED; unverifiable evidence " "must never complete a step"
    )
    assert bare_rejected == 3, "a bare alias must not parse as an exact version reference"

    return {
        "attempted": attempted,
        "refused": refused,
        "invalid_reference_rate": 1.0 if attempted == 0 else refused / attempted,
        "by_reason": reasons,
        "bare_aliases_rejected": bare_rejected,
    }


# ─────────────────────────────────────────────────────────────
# AC16: repeated operations after recovery
# ─────────────────────────────────────────────────────────────


async def measure_repeated_operations() -> Dict[str, Any]:
    """Count physical work repeated across a simulated context loss.

    Returns:
        The execution counts before and after recovery.

    Raises:
        AssertionError: If any already-completed step is executed again.
    """
    executions: List[str] = []
    scope = _scope()
    store, artifacts = InMemoryTaskMemoryStore(), InMemoryArtifactStore()

    tm = TaskMemory(store, artifacts, scope)
    task_id = await _task_with_plan(tm, 4)
    state = (await tm.service.get_task(scope, task_id)).state
    steps = [s.step_id for s in state.steps]

    async def _do(step_id: str, name: str) -> None:
        """Run one step's physical work and complete it with evidence.

        Args:
            step_id: The step.
            name: Artifact alias for its output.
        """
        executions.append(name)
        descriptor = await tm.artifacts.put(scope, name, {"rows": [1, 2, 3]}, task_id=task_id)
        ref = descriptor.ref if hasattr(descriptor, "ref") else descriptor
        current = (await tm.service.get_task(scope, task_id)).state.revision
        await tm.service.complete_step(
            scope, task_id, step_id, expected_revision=current, evidence_refs=(ref,), note="done"
        )

    await _do(steps[0], "first")
    await _do(steps[1], "second")
    before = list(executions)

    # Context loss: a brand-new composition root over the same stores,
    # with nothing carried over in memory.
    recovered = TaskMemory(store, artifacts, scope)
    reader = RecallReader(store, artifacts, config=recovered.config)
    snapshot = await reader.recall(scope, task_id)
    assert snapshot.status is RecallStatus.OK

    ready = (await recovered.service.get_task(scope, task_id)).state.ready_step_ids
    for step_id in ready:
        await _do(step_id, f"after_{step_id[:6]}")

    repeated = [name for name in executions[len(before) :] if name in before]
    assert not repeated, f"recovery repeated work already done: {repeated}"
    assert steps[0] not in ready and steps[1] not in ready

    return {
        "executions_before_recovery": len(before),
        "executions_after_recovery": len(executions) - len(before),
        "repeated_operations": len(repeated),
        "ready_after_recovery": len(ready),
        "recall_tokens_at_recovery": snapshot.estimated_tokens,
    }


# ─────────────────────────────────────────────────────────────
# AC16: snapshot and fingerprint cost at 8/64/256 MiB
# ─────────────────────────────────────────────────────────────


def measure_payload_costs() -> Dict[str, Any]:
    """Record snapshot and fingerprint cost at the three required sizes.

    Delegates to ``bench_snapshot_costs`` so the measurement has exactly
    one definition. Sizes above ``TM_BENCH_MAX_MIB`` are reported as
    skipped, never as measured.

    Returns:
        The measurements, keyed by payload family.
    """
    cap = int(os.environ.get("TM_BENCH_MAX_MIB", "256"))
    out: Dict[str, Any] = {"cap_mib": cap, "measurements": []}
    for target in TARGET_MIB:
        if target > cap:
            out["measurements"].append(
                {"target_mib": target, "status": "skipped", "reason": f"above TM_BENCH_MAX_MIB={cap}"}
            )
            continue
        from bench_snapshot_costs import _numeric_string_frame  # local: heavy import

        frame = _numeric_string_frame(target * 1024 * 1024)
        out["measurements"].append(measure_dataframe("dataframe_numeric_string", frame, target).__dict__)
        del frame
        out["measurements"].append(measure_json_text(target, serializer="orjson").__dict__)
    return out


# ─────────────────────────────────────────────────────────────
# Required case: test_metrics
# ─────────────────────────────────────────────────────────────


def test_metrics() -> Dict[str, Any]:
    """Record every AC16 metric, with environment and inputs.

    Returns:
        The metrics report.

    Raises:
        AssertionError: If a metric is missing or a cap invariant fails.
    """
    report: Dict[str, Any] = {"environment": environment()}
    report["recall"] = asyncio.run(measure_recall())
    report["observer_overhead"] = asyncio.run(measure_observer_overhead())
    report["invalid_reference_rate"] = asyncio.run(measure_invalid_reference_rate())
    report["repeated_operations"] = asyncio.run(measure_repeated_operations())
    report["payload_costs"] = measure_payload_costs()

    # AC16 names five metrics; all five must be present, or this
    # benchmark is quietly under-reporting.
    required = {
        "recall",
        "observer_overhead",
        "invalid_reference_rate",
        "repeated_operations",
        "payload_costs",
    }
    missing = required - set(report)
    assert not missing, f"AC16 metrics missing from the report: {sorted(missing)}"

    sizes = {m.get("target_mib") for m in report["payload_costs"]["measurements"]}
    assert {8, 64, 256} <= sizes, f"the three required sizes were not covered: {sorted(sizes)}"

    report["reproduce"] = (
        "PYTHONPATH=packages/ai-parrot/src python "
        "packages/ai-parrot/tests/tools/working_memory/task_memory/bench_task_memory.py"
    )
    report["no_slo_claimed"] = (
        "Timings are recorded observations on the environment above. No latency SLO is "
        "claimed; only the byte/token caps and exactly-once recovery are asserted."
    )
    return report


# ─────────────────────────────────────────────────────────────
# Required case: test_docs_examples
# ─────────────────────────────────────────────────────────────


def _python_blocks(text: str) -> List[str]:
    """Extract fenced python blocks from markdown.

    Args:
        text: The document.

    Returns:
        The block bodies.
    """
    return re.findall(r"```python\n(.*?)```", text, re.S)


def test_docs_examples() -> Dict[str, Any]:
    """Every documented import and symbol must actually exist.

    A documentation example that names a symbol which does not exist is
    worse than no example: it is confidently wrong, and a reader has no
    way to tell without trying it.

    Returns:
        What was checked.

    Raises:
        AssertionError: If the document is missing, an example does not
            parse, a symbol does not resolve, or unsafe advice appears.
    """
    import ast
    import importlib

    assert DOC_PATH.is_file(), f"documentation not found at {DOC_PATH}"
    text = DOC_PATH.read_text(encoding="utf-8")
    blocks = _python_blocks(text)
    assert blocks, "the documentation contains no python examples to check"

    checked_imports: List[str] = []
    for i, block in enumerate(blocks):
        try:
            tree = ast.parse(block)
        except SyntaxError as exc:  # pragma: no cover - surfaced as a failure
            raise AssertionError(f"python example #{i} does not parse: {exc}") from exc

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("parrot"):
                module = importlib.import_module(node.module)
                for alias in node.names:
                    assert hasattr(module, alias.name), (
                        f"example #{i} imports {alias.name!r} from {node.module!r}, " "which does not exist"
                    )
                    checked_imports.append(f"{node.module}.{alias.name}")

    # The spec forbids advertising automatic retry of external effects,
    # and forbids implying Delivery A is durable. Documentation is where
    # both mistakes would do the most damage.
    lowered = text.lower()
    for banned in ("automatically retried", "automatically retries", "retry the effect"):
        assert banned not in lowered, f"documentation advertises unsafe retry behaviour: {banned!r}"
    assert (
        "non-durable" in lowered or "not durable" in lowered
    ), "documentation must state that Delivery A is not durable"

    return {"python_blocks": len(blocks), "imports_verified": sorted(set(checked_imports))}


# ─────────────────────────────────────────────────────────────
# Required case: test_traceability
# ─────────────────────────────────────────────────────────────


def test_traceability() -> Dict[str, Any]:
    """The document must link the real gates, migration and logs.

    Returns:
        What was found.

    Raises:
        AssertionError: If a referenced artefact does not exist on disk.
            A traceability link to a file that is not there is not
            traceability.
    """
    assert DOC_PATH.is_file(), f"documentation not found at {DOC_PATH}"
    text = DOC_PATH.read_text(encoding="utf-8")
    root = DOC_PATH.resolve().parents[2]  # docs/memory/<file> -> repo root

    # Both delivery gates, by their real module names.
    for gate in ("test_delivery_a.py", "test_delivery_b.py", "test_crash_matrix.py"):
        assert gate in text, f"documentation does not reference the {gate} gate"

    # Every repo-relative path the document cites must exist.
    cited = set(re.findall(r"`((?:packages|docs|sdd)/[^`\s]+?\.(?:py|md|sql|json))`", text))
    assert cited, "documentation cites no verifiable repository paths"
    missing = [p for p in sorted(cited) if not (root / p).exists()]
    assert not missing, f"documentation cites paths that do not exist: {missing}"

    # The migration is the one operational step a durable deployment
    # cannot skip, so it must be named explicitly.
    assert "apply_migrations" in text, "documentation does not describe applying the migration"
    assert "001_task_memory" in text, "documentation does not name the migration"

    return {"cited_paths": sorted(cited), "verified": len(cited)}


def main() -> int:
    """Run the three required cases and print a JSON report.

    Returns:
        ``0`` on success, ``1`` on any assertion failure.
    """
    report: Dict[str, Any] = {"feature": "FEAT-538", "task": "TASK-3005"}
    try:
        report["docs_examples"] = test_docs_examples()
        report["traceability"] = test_traceability()
        report["metrics"] = test_metrics()
    except AssertionError as exc:
        report["failure"] = str(exc)
        print(json.dumps(report, indent=2, default=str))
        return 1
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
