"""Baseline-aware verdict: classify branch failures against origin/<base_branch> (FEAT-699, spec §3 M5).

Only failed node ids are re-run, inside a temporary detached checkout of the base ref with the compiled
extensions copied from the main checkout. Anything that cannot be proven is ``unknown`` — a failure.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..native_artifacts import main_checkout_root, sync_native_artifacts
from .datatypes import BaselineVerdict
from .mirror import distribution_of
from .report import parse_junit

logger = logging.getLogger(__name__)


class BaselineUnavailable(RuntimeError):
    """The base ref cannot be checked out into a runnable tree."""


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git in ``cwd`` capturing text output."""
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)


def prepare_baseline_checkout(*, worktree: Path, base_ref: str, scratch: Path) -> Path:
    """Detached ``git worktree add`` of ``base_ref`` + compiled ``.so`` copies. Raises BaselineUnavailable."""
    try:
        sha_proc = _git(worktree, "rev-parse", "--verify", f"{base_ref}^{{commit}}")
    except OSError as exc:
        raise BaselineUnavailable(f"git unavailable: {exc}") from exc
    if sha_proc.returncode != 0:
        raise BaselineUnavailable(f"cannot resolve base ref {base_ref!r}: {sha_proc.stderr.strip()}")
    sha = sha_proc.stdout.strip()
    target = Path(scratch) / f"baseline-{sha[:12]}"
    add = _git(worktree, "worktree", "add", "--detach", str(target), sha)
    if add.returncode != 0:
        raise BaselineUnavailable(f"git worktree add failed: {add.stderr.strip()}")

    try:
        main_root = main_checkout_root(worktree)
        if main_root is not None:
            # One shared implementation (FEAT-722). `autobuild=False`: a verdict run must never trigger
            # a compile, so an unbuilt extension stays fatal here.
            report = sync_native_artifacts(main_root=main_root, target=target, autobuild=False)
            # Only an UNPAIRED SOURCE is fatal, which is exactly what the pre-FEAT-722
            # loop checked: a `.pyx` with no sibling `.so`. `no_match` (a declared group
            # whose artifacts are absent, e.g. navrules on a checkout that never built
            # it) and `abi_mismatch` (artifacts built for another interpreter) were
            # invisible to the old check and must not turn every baseline verdict into
            # `unknown` here.
            fatal = [entry for entry in report.missing if entry.reason == "unpaired_source"]
            for entry in report.missing:
                if entry not in fatal:
                    logger.warning(
                        "baseline: native artifact %s missing from the main checkout (%s), continuing",
                        entry.detail,
                        entry.reason,
                    )
            if fatal:
                raise BaselineUnavailable(f"no compiled extension for {fatal[0].detail} in main checkout")
    except BaselineUnavailable:
        remove_baseline_checkout(worktree, target)
        raise
    except OSError as exc:
        remove_baseline_checkout(worktree, target)
        raise BaselineUnavailable(f"copying compiled artifacts failed: {exc}") from exc
    return target


def remove_baseline_checkout(worktree: Path, path: Path) -> None:
    """Best-effort removal of a checkout created by ``prepare_baseline_checkout``; never raises."""
    try:
        proc = _git(worktree, "worktree", "remove", "--force", str(path))
        if proc.returncode != 0:
            logger.warning("could not remove baseline checkout %s: %s", path, proc.stderr.strip())
        _git(worktree, "worktree", "prune")
    except Exception:  # noqa: BLE001 - cleanup must never raise
        logger.warning("baseline checkout cleanup failed for %s", path, exc_info=True)


def _file_part(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def _classify_group(
    checkout: Path, dist: str, nodeids: list[str], timeout_s: int, tmp_dir: Path
) -> dict[str, BaselineVerdict]:
    """Run one pytest over ``nodeids`` inside ``checkout`` and map each to a verdict."""
    src_dist = "ai-parrot" if dist == "root" else dist
    junit = tmp_dir / f"{dist}.xml"
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "-o",
        "junit_family=xunit1",
        f"--junitxml={junit}",
        "--confcutdir",
        str(checkout),
        "--rootdir",
        str(checkout),
        "-m",
        "not real_llm",
        *nodeids,
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(checkout / "packages" / src_dist / "src")
    timed_out = False
    exit_code = -1
    try:
        proc = subprocess.run(
            argv, cwd=str(checkout), env=env, capture_output=True, text=True, timeout=timeout_s, check=False
        )
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
    except OSError as exc:
        return {n: BaselineVerdict(n, "unknown", f"baseline run failed: {exc}") for n in nodeids}

    if timed_out:
        return {n: BaselineVerdict(n, "unknown", "baseline run timed out") for n in nodeids}

    result = parse_junit(junit, suite=dist, argv=tuple(argv), exit_code=exit_code, duration_s=0.0)
    by_node = dict(result.nodes)
    verdicts: dict[str, BaselineVerdict] = {}
    for nodeid in nodeids:
        status = by_node.get(nodeid)
        if status == "passed":
            verdicts[nodeid] = BaselineVerdict(nodeid, "new_red", "passes on baseline")
        elif status in ("failed", "error"):
            verdicts[nodeid] = BaselineVerdict(nodeid, "baseline_red", f"{status} on baseline")
        elif status == "skipped":
            verdicts[nodeid] = BaselineVerdict(nodeid, "unknown", "skipped on baseline")
        else:
            detail = "node missing from baseline report"
            if result.unmapped:
                detail += f" ({result.unmapped} unmapped testcases)"
            verdicts[nodeid] = BaselineVerdict(nodeid, "unknown", detail)
    return verdicts


def classify_failures(
    *,
    worktree: Path,
    base_ref: str,
    failed_nodeids: Sequence[str],
    timeout_s: int,
    scratch: Path | None = None,
    runner_of: Mapping[str, str] | None = None,
) -> tuple[BaselineVerdict, ...]:
    """Run ONLY ``failed_nodeids`` on the baseline; one verdict per input node id, input order kept."""
    nodeids = list(failed_nodeids)
    if not nodeids:
        return ()

    non_pytest = {nodeid for nodeid in nodeids if runner_of is not None and runner_of.get(nodeid) != "pytest"}
    pytest_nodeids = [nodeid for nodeid in nodeids if nodeid not in non_pytest]
    if not pytest_nodeids:
        return tuple(BaselineVerdict(nodeid, "unknown", "baseline only supports pytest") for nodeid in nodeids)

    owns_scratch = scratch is None
    scratch_dir = Path(tempfile.mkdtemp(prefix="parrot-baseline-")) if scratch is None else Path(scratch)
    tmp_dir = Path(tempfile.mkdtemp(prefix="parrot-baseline-junit-"))
    checkout: Path | None = None
    try:
        try:
            checkout = prepare_baseline_checkout(worktree=worktree, base_ref=base_ref, scratch=scratch_dir)
        except BaselineUnavailable as exc:
            return tuple(
                (
                    BaselineVerdict(nodeid, "unknown", "baseline only supports pytest")
                    if nodeid in non_pytest
                    else BaselineVerdict(nodeid, "unknown", str(exc))
                )
                for nodeid in nodeids
            )

        verdicts: dict[str, BaselineVerdict] = {}
        groups: dict[str, list[str]] = {}
        for nodeid in pytest_nodeids:
            file_part = _file_part(nodeid)
            if not (checkout / file_part).exists():
                verdicts[nodeid] = BaselineVerdict(nodeid, "new_red", "test only on branch")
                continue
            try:
                dist = distribution_of(file_part)
            except ValueError:
                verdicts[nodeid] = BaselineVerdict(nodeid, "unknown", "cannot map node id to a distribution")
                continue
            groups.setdefault(dist, []).append(nodeid)

        for dist, group in groups.items():
            verdicts.update(_classify_group(checkout, dist, group, timeout_s, tmp_dir))
        for nodeid in non_pytest:
            verdicts[nodeid] = BaselineVerdict(nodeid, "unknown", "baseline only supports pytest")
        return tuple(verdicts[nodeid] for nodeid in nodeids)
    finally:
        if checkout is not None:
            remove_baseline_checkout(worktree, checkout)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if owns_scratch:
            shutil.rmtree(scratch_dir, ignore_errors=True)


def gate_failed(verdicts: Sequence[BaselineVerdict]) -> bool:
    """True when any verdict is ``new_red`` or ``unknown``."""
    return any(v.status in ("new_red", "unknown") for v in verdicts)


def summarize(verdicts: Sequence[BaselineVerdict]) -> dict[str, int]:
    """Count verdicts per status (only statuses that occur)."""
    counts: dict[str, int] = {}
    for verdict in verdicts:
        counts[verdict.status] = counts.get(verdict.status, 0) + 1
    return counts
