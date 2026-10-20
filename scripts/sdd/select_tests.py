"""``select_tests.py`` — tier-scoped pytest plans for SDD agents (FEAT-563).

Usage:
    python -m scripts.sdd.select_tests --tier {task,merge,feature} [--base origin/dev]
        [--task-file sdd/tasks/active/TASK-NNN-x.md ...] [--worktree .] [--run] [--json]
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"


def _load_kernel() -> ModuleType:
    """Import the stdlib kernel by path as top-level `test_scope` (never `import parrot`)."""
    if str(_KERNEL_PARENT) not in sys.path:
        sys.path.insert(0, str(_KERNEL_PARENT))
    import test_scope  # noqa: PLC0415 — path-dependent import

    return test_scope


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan (and optionally run) tier-scoped pytest invocations.")
    parser.add_argument("--tier", required=True, choices=("task", "merge", "feature"))
    parser.add_argument(
        "--base", default=None, help="diff + baseline ref (default: origin/<index base_branch> or origin/dev)"
    )
    parser.add_argument("--index", type=Path, default=None, help="per-spec index (FEAT-699 test_contract source)")
    cache = parser.add_mutually_exclusive_group()
    cache.add_argument("--use-cache", dest="use_cache", action="store_true", default=None)
    cache.add_argument("--fresh", dest="use_cache", action="store_false")
    baseline = parser.add_mutually_exclusive_group()
    baseline.add_argument("--baseline", dest="baseline", action="store_true", default=True)
    baseline.add_argument("--no-baseline", dest="baseline", action="store_false")
    parser.add_argument("--timeout-baseline", type=int, default=600, metavar="SECONDS")
    parser.add_argument("--task-file", action="append", default=[], type=Path)
    parser.add_argument("--worktree", type=Path, default=Path.cwd())
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verdict", action="store_true", help="run the plan and print only verdict JSON")
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path("artifacts/logs/validation"),
        help="verdict-mode report and child-output directory",
    )
    parser.add_argument("--feature", default=None, help="FEAT-<NNN>: record structured results (FEAT-695)")
    parser.add_argument("--report-task", default=None, help="TASK-<NNN> or _rerun: record owner (FEAT-695)")
    parser.add_argument("--no-ledger", action="store_true", help="report-only: never touch the escalation ledger")
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        metavar="SECONDS",
        help=(
            "Per-test timeout (pytest-timeout) applied to every planned invocation. "
            "FEAT-617: bounds a hung test so the sweep names it instead of stalling. "
            "Opt-in -- deliberately NOT a shared pytest config default, so slow suites "
            "do not flake for developers."
        ),
    )
    return parser


def _resolve_index(args: argparse.Namespace, worktree: Path, kernel: ModuleType) -> tuple[dict, list[str]]:
    """Return an index header and discovery notes, preferring an explicit ``--index``."""
    if args.index is not None:
        index_path = args.index if args.index.is_absolute() else worktree / args.index
        return kernel.contract.load_index_header(index_path), []
    if not args.feature:
        return {}, []

    matches: list[dict] = []
    for index_path in sorted((worktree / "sdd/tasks/index").glob("*.json")):
        try:
            header = kernel.contract.load_index_header(index_path)
        except ValueError:
            continue
        if header.get("feature_id") == args.feature:
            matches.append(header)
    if len(matches) == 1:
        return matches[0], []
    if not matches:
        return {}, [f"no index found for feature {args.feature}; no test contract applied"]
    return {}, [f"multiple indexes found for feature {args.feature}; no test contract applied"]


def _record_suite(
    report_mod: ModuleType | None,
    args: argparse.Namespace,
    suite: object,
    *,
    head_sha: str,
    base_ref: str,
) -> None:
    """Best-effort record of one suite result when a feature/task owner was supplied."""
    if report_mod is not None and args.feature and args.report_task:
        report_mod.append_suite(
            args.feature,
            args.report_task,
            suite,
            head_sha=head_sha,
            base_ref=base_ref,
            tier=args.tier,
            source="select_tests",
        )


def _write_verdict(verdict: object) -> None:
    """Write exactly one compact verdict JSON object to stdout."""
    import test_scope.verdict as verdict_mod  # noqa: PLC0415 — path-dependent import

    sys.stdout.write(json.dumps(verdict_mod.verdict_to_json(verdict), sort_keys=True) + "\n")


def _blocked_verdict(kernel: ModuleType, *, tier: str, note: str) -> object:
    """Build the blocked payload used when a task-tier plan is empty."""
    return kernel.ValidationVerdict(
        schema=1,
        status="blocked",
        tier=tier,
        runners=(),
        failures=(),
        notes=(note,),
    )


def _report_suffix(report_format: str) -> str:
    """Return a stable file suffix for one adapter report format."""
    return {
        "junit": ".xml",
        "e2e-verdict": ".json",
        "libtest": ".txt",
        "exit-code": ".txt",
    }.get(report_format, ".report")


def _safe_report_name(value: str) -> str:
    """Make a runner or suite label safe for a report filename."""
    return "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in value)


def _run_verdict_mode(
    *,
    args: argparse.Namespace,
    kernel: ModuleType,
    plan: object,
    worktree: Path,
    base_ref: str,
) -> int:
    """Run a plan through its adapters and emit only the normalized verdict."""
    import test_scope.baseline as baseline_mod  # noqa: PLC0415 — path-dependent import
    import test_scope.report as report_mod  # noqa: PLC0415 — path-dependent import
    import test_scope.verdict as verdict_mod  # noqa: PLC0415 — path-dependent import
    from test_scope.runners.registry import load_registry  # noqa: PLC0415 — path-dependent import

    log_dir = args.log_dir if args.log_dir.is_absolute() else worktree / args.log_dir
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        verdict = _blocked_verdict(kernel, tier=args.tier, note=f"cannot create validation log directory: {exc}")
        _write_verdict(verdict)
        return 2

    registry = load_registry(worktree)
    reports = []
    evidence: list[str] = []
    log_path = log_dir / "validation.log"
    log_lines = [f"tier: {args.tier}", f"base: {base_ref}"]

    for ordinal, invocation in enumerate(plan.invocations):
        adapter = registry.adapter_for_kind(invocation.runner)
        report_path = log_dir / (
            f"{ordinal:02d}-{_safe_report_name(invocation.runner)}-"
            f"{_safe_report_name(invocation.distribution)}{_report_suffix(invocation.report_format)}"
        )
        try:
            report_path.unlink(missing_ok=True)
        except OSError:
            pass

        run_invocation = replace(invocation, report_path=str(report_path))
        argv = list(run_invocation.argv)
        if invocation.runner == "pytest":
            argv = list(report_mod.with_report(run_invocation, report_path))
        elif invocation.report_format == "junit":
            argv = [
                f"--outputFile={report_path}" if argument.startswith("--outputFile=") else argument
                for argument in argv
            ]

        run_cwd = worktree / invocation.cwd
        timeout_s = invocation.timeout_s or registry.timeout_for(invocation.runner)
        started = time.monotonic()
        timed_out = False
        try:
            result = subprocess.run(
                argv,
                cwd=run_cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_s,
            )
            exit_code = result.returncode
            stdout = result.stdout
            stderr = result.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = 124
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
        except OSError as exc:
            exit_code = 127
            stdout = ""
            stderr = str(exc)

        duration_s = time.monotonic() - started
        suite = report_mod.suite_name(run_invocation)
        report = adapter.parse_report(
            report_path=report_path,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_s=duration_s,
            timed_out=timed_out,
            suite=suite,
        )
        reports.append(report)
        log_lines.extend(
            (
                "",
                f"$ {shlex.join(argv)}",
                f"cwd: {run_cwd}",
                f"exit: {exit_code}",
                "stdout:",
                stdout,
                "stderr:",
                stderr,
            )
        )
        try:
            evidence.append(report_path.relative_to(worktree).as_posix())
        except ValueError:
            evidence.append(str(report_path))

    pytest_failures = [
        nodeid
        for report in reports
        if report.runner == "pytest"
        for nodeid, status in report.nodes
        if status in {"failed", "error"}
    ]
    baseline = ()
    if pytest_failures and args.baseline:
        baseline = baseline_mod.classify_failures(
            worktree=worktree,
            base_ref=base_ref,
            failed_nodeids=pytest_failures,
            timeout_s=args.timeout_baseline or 600,
        )

    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    try:
        evidence.append(log_path.relative_to(worktree).as_posix())
    except ValueError:
        evidence.append(str(log_path))
    verdict = verdict_mod.build_verdict(
        tier=args.tier,
        reports=reports,
        baseline=baseline,
        cached=plan.cached,
        notes=plan.notes,
        evidence=evidence,
    )
    _write_verdict(verdict)
    return 0 if verdict.status == "passed" else 1


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: 0 ok, 1 an invocation failed, 2 usage error / empty task-tier plan."""
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit:
        return 2
    kernel = _load_kernel()
    worktree = args.worktree.resolve()

    try:
        index_header, index_notes = _resolve_index(args, worktree, kernel)
        contract = kernel.contract.contract_from_index_header(index_header) if index_header else None
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)  # noqa: T201 - CLI output
        return 2
    base_ref = args.base or f"origin/{index_header.get('base_branch', 'dev')}"

    declared: list[list[str]] = []
    for task_file in args.task_file:
        path = task_file if task_file.is_absolute() else worktree / task_file
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        declared.extend(kernel.contract.parse_validation_commands(text))

    plan = kernel.plan_tests(
        worktree=worktree,
        changed_files=kernel.changed_files(worktree, base_ref),
        tier=args.tier,
        declared=declared,
        contract=contract,
    )
    if index_notes:
        plan = replace(plan, notes=(*plan.notes, *index_notes))

    use_cache = args.use_cache if args.use_cache is not None else args.tier == "merge"
    namespace = None
    if args.feature:
        import test_scope.green_cache as green_cache  # noqa: PLC0415 — path-dependent import

        namespace = green_cache.cache_namespace(
            feature_id=args.feature,
            base_ref=base_ref,
            contract_digest=contract.digest if contract else "none",
        )
        if use_cache:
            plan = green_cache.filter_cached(worktree, plan, namespace=namespace, contract=contract)

    if not plan.invocations and args.tier == "task":
        import test_scope.guard as guard_mod  # noqa: PLC0415 — path-dependent import

        if args.verdict:
            _write_verdict(_blocked_verdict(kernel, tier=args.tier, note=guard_mod.BLOCK_MESSAGE))
            return 2
        print(guard_mod.BLOCK_MESSAGE)  # noqa: T201 - CLI output
        return 2

    if args.verdict:
        return _run_verdict_mode(args=args, kernel=kernel, plan=plan, worktree=worktree, base_ref=base_ref)
    if args.json:
        import test_scope.models as models_mod  # noqa: PLC0415 — the only kernel module importing pydantic

        print(models_mod.ScopePlanModel.from_plan(plan).model_dump_json(indent=2))  # noqa: T201 - CLI output
    else:
        for invocation in plan.invocations:
            print(shlex.join(invocation.argv))  # noqa: T201 - CLI output
        for target in plan.cached:
            print(f"# cached: {target}")  # noqa: T201 - CLI output
        for note in plan.notes:
            print(f"# note: {note}")  # noqa: T201 - CLI output
        for dist in plan.escalated:
            print(f"# escalated: {dist}")  # noqa: T201 - CLI output
        for dist in plan.skipped_escalations:
            print(f"# skipped: {dist}")  # noqa: T201 - CLI output

    if not args.run:
        return 0

    recording = bool(args.feature and args.report_task)
    report_mod: ModuleType | None = None
    head_sha = ""
    try:
        import test_scope.report as report_mod  # noqa: PLC0415 — path-dependent import
    except ImportError as exc:
        print(f"warning: junit recording disabled: {exc}", file=sys.stderr)  # noqa: T201

    if recording:
        try:
            head_result = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=worktree, capture_output=True, text=True, check=False
            )
            head_sha = head_result.stdout.strip()
        except OSError:
            head_sha = ""

        if recording and not plan.invocations:
            selection = report_mod.SuiteResult(
                suite="selection",
                tests=0,
                passed=0,
                failed=0,
                errors=0,
                skipped=0,
                duration_s=0.0,
                exit_code=0,
                argv=(),
                status="selection_error",
            )
            report_mod.append_suite(
                args.feature,
                args.report_task,
                selection,
                head_sha=head_sha,
                base_ref=base_ref,
                tier=args.tier,
                source="select_tests",
                note="selection_error: no test invocations planned",
            )

    exit_code = 0
    suites: list[object] = []
    failed_nodeids: list[str] = []
    unclassified_failure = False
    for ordinal, invocation in enumerate(plan.invocations):
        # FEAT-617: bound each test so a hang fails loudly, named, instead of stalling
        # the whole merge gate. Build a local argv -- invocation.argv is read elsewhere
        # (the printed plan) and must stay unmodified.
        argv = list(invocation.argv)
        if args.timeout is not None:
            argv.append(f"--timeout={args.timeout}")
        junit = None
        if recording and report_mod is not None:
            try:
                feature_id = args.feature or "_rerun"
                task_id = args.report_task or "_rerun"
                junit = report_mod.junit_path_for(feature_id, task_id, invocation.distribution, ordinal)
                invocation_copy = type(invocation)(
                    distribution=invocation.distribution,
                    argv=tuple(argv),
                    targets=invocation.targets,
                    runner=invocation.runner,
                    cwd=invocation.cwd,
                    report_path=invocation.report_path,
                    report_format=invocation.report_format,
                    timeout_s=invocation.timeout_s,
                )
                argv = list(report_mod.with_report(invocation_copy, junit))
            except OSError:
                junit = None
        started = time.monotonic()
        result = subprocess.run(argv, cwd=worktree)
        suite = None
        if report_mod is not None and junit is not None:
            suite = report_mod.parse_junit(
                junit,
                suite=report_mod.suite_name(invocation),
                argv=tuple(argv),
                exit_code=result.returncode,
                duration_s=time.monotonic() - started,
            )
            suites.append(suite)
            _record_suite(report_mod, args, suite, head_sha=head_sha, base_ref=base_ref)
        # FEAT-699: `plan_tests` no longer emits `core`/`escalated` targets (a core hit is a plan
        # note, "covered by nightly"), so these FEAT-604 ledger branches fire only for legacy plans.
        # Gate on the invocation's own targets -- the same rule as
        # `ValidationSupervisor._record_invocation_outcome` -- never on `plan.core_hits`: a
        # non-escalated run proves nothing about a suite and must leave the ledger alone.
        is_core_escalation = any(target.reason == "core" for target in invocation.targets)
        is_cap_escalation = any(target.reason == "escalated" for target in invocation.targets)
        if result.returncode != 0:
            exit_code = 1
            if suite is None or suite.status in {"no_junit", "report_parse_error"} or suite.unmapped:
                unclassified_failure = True
            else:
                nodes = [nodeid for nodeid, status in suite.nodes if status in {"failed", "error"}]
                if not nodes:
                    unclassified_failure = True
                failed_nodeids.extend(nodes)
            if not args.no_ledger and (is_core_escalation or is_cap_escalation):
                import test_scope.context as ledger  # noqa: PLC0415 -- path-dependent import

                # R14/AC9c: a red escalation run re-arms it, even when its driving file content is unchanged.
                ledger.record_red_run(worktree, [invocation.distribution])
            continue
        if not args.no_ledger and (is_core_escalation or is_cap_escalation):
            import test_scope.context as ledger  # noqa: PLC0415 -- path-dependent import

            dist = invocation.distribution
            core_files = [hit.path for hit in plan.core_hits]
            impact_files = list(plan.cap_hits.get(dist, ()))
            impacted_hashes = {dist: plan.cap_impacted[dist]} if dist in plan.cap_impacted else {}
            if core_files or impact_files:
                ledger.record_green_escalation(
                    worktree, [dist], core_files, impact_files=impact_files, impacted_hashes=impacted_hashes
                )

    verdicts = ()
    if failed_nodeids and args.baseline:
        import test_scope.baseline as baseline  # noqa: PLC0415 — path-dependent import

        verdicts = baseline.classify_failures(
            worktree=worktree,
            base_ref=base_ref,
            failed_nodeids=failed_nodeids,
            timeout_s=args.timeout_baseline or 600,
        )
        verdict_by_node = {verdict.nodeid: verdict.status for verdict in verdicts}
        if set(failed_nodeids) - set(verdict_by_node):
            unclassified_failure = True
        for suite in suites:
            baseline_nodes = tuple(
                (nodeid, verdict_by_node[nodeid]) for nodeid, _ in suite.nodes if nodeid in verdict_by_node
            )
            if baseline_nodes:
                _record_suite(
                    report_mod,
                    args,
                    replace(suite, baseline=baseline_nodes),
                    head_sha=head_sha,
                    base_ref=base_ref,
                )
        summary = baseline.summarize(verdicts)
        print(
            f"# baseline: new_red={summary.get('new_red', 0)} "
            f"baseline_red={summary.get('baseline_red', 0)} unknown={summary.get('unknown', 0)}"
        )  # noqa: T201 - CLI output
        exit_code = 1 if baseline.gate_failed(verdicts) or unclassified_failure else 0
    elif exit_code:
        unclassified_failure = True

    if namespace is not None and not args.no_ledger:
        import test_scope.green_cache as green_cache  # noqa: PLC0415 — path-dependent import

        all_nodes = tuple(node for suite in suites for node in suite.nodes)
        unmapped = sum(suite.unmapped for suite in suites)
        green_cache.record_green(
            worktree,
            namespace=namespace,
            plan=plan,
            nodes=all_nodes,
            unmapped=unmapped,
            baseline_reds=tuple(verdict.nodeid for verdict in verdicts if verdict.status == "baseline_red"),
        )
    if recording and report_mod is not None and plan.cached:
        report_mod.append_cached(
            args.feature,
            args.report_task,
            plan.cached,
            head_sha=head_sha,
            base_ref=base_ref,
            tier=args.tier,
            source="select_tests",
        )
    return 1 if unclassified_failure else exit_code


if __name__ == "__main__":
    raise SystemExit(main())
