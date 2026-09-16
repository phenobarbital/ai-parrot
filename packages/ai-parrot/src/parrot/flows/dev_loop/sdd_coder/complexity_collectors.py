"""Collectors for deterministic complexity evidence (spec §2-§4).

Implements bounded subprocess collection for Ruff cyclomatic complexity,
wiki blast radius, file scope metrics and dependency analysis. No network I/O;
filesystem access is limited to worktree contents and subprocess output capture.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from parrot.flows.dev_loop.sdd_coder.complexity_models import (
    ComplexityAssessment,
    ComplexityContract,
    ComplexityEvidence,
    ComplexityPolicy,
    MetricEvidence,
)
from parrot.flows.dev_loop.sdd_coder.complexity import ComplexityContractError, parse_complexity_contract

logger = logging.getLogger(__name__)

# Extensions treated as documentation/configuration (spec §2 item 1:
# "Documentation/configuration gives not_applicable"), as opposed to a
# programming-language source file Ruff cannot analyze (which is "unknown").
_DOC_CONFIG_EXTENSIONS = frozenset(
    {".md", ".markdown", ".txt", ".rst", ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini", ".csv", ".xml", ".html"}
)


async def collect_complexity(
    worktree: Path, task_file: Path, index_path: Path, policy: ComplexityPolicy
) -> ComplexityEvidence:
    """Collect complexity evidence for a task using bounded subprocess collectors.

    Args:
        worktree: Absolute path to the feature worktree.
        task_file: Path to the task markdown file (relative to worktree).
        index_path: Path to the per-spec index file (relative to worktree).
        policy: Complexity policy governing collection limits.

    Returns:
        Complete evidence snapshot with all six metric families.
    """
    # Validate inputs. Filesystem checks are offloaded via asyncio.to_thread --
    # pathlib methods are blocking calls and this function is async (ASYNC240).
    if not worktree.is_absolute():
        raise ValueError("worktree must be an absolute path")

    worktree_exists, worktree_is_dir = await asyncio.gather(
        asyncio.to_thread(worktree.exists), asyncio.to_thread(worktree.is_dir)
    )
    if not worktree_exists or not worktree_is_dir:
        raise ValueError(f"worktree does not exist or is not a directory: {worktree}")

    full_task_path = worktree / task_file
    if not await asyncio.to_thread(full_task_path.exists):
        raise ValueError(f"task_file does not exist: {full_task_path}")

    full_index_path = worktree / index_path
    if not await asyncio.to_thread(full_index_path.exists):
        raise ValueError(f"index_path does not exist: {full_index_path}")

    # Read task content
    task_content = full_task_path.read_text(encoding="utf-8")
    task_id = _extract_task_id(task_content)

    # Parse contract
    contract = parse_complexity_contract(task_content)

    # Get git HEAD SHA
    head_sha = await _get_git_head_sha(worktree)

    # Calculate hashes
    task_sha256 = _sha256_file(full_task_path)
    index_sha256 = _sha256_file(full_index_path)
    policy_sha256 = _canonical_hash(policy)

    # Collect metrics concurrently with limit
    semaphore = asyncio.Semaphore(policy.max_concurrency)

    # Collect all evidence
    metrics, target_hashes, wiki_evidence_hashes, collector_versions, details = await _collect_all_evidence(
        worktree, task_file, index_path, contract, policy, semaphore
    )

    # Create evidence snapshot
    evidence = ComplexityEvidence(
        task_id=task_id,
        contract=contract,
        metrics=metrics,
        head_sha=head_sha,
        task_sha256=task_sha256,
        index_sha256=index_sha256,
        policy_sha256=policy_sha256,
        target_hashes=target_hashes,
        wiki_evidence_hashes=wiki_evidence_hashes,
        collector_versions=collector_versions,
        details=details,
    )

    return evidence


async def validate_complexity_snapshot(
    worktree: Path, task_file: Path, index_path: Path, assessment: ComplexityAssessment, policy: ComplexityPolicy
) -> bool:
    """Validate that a complexity assessment matches current inputs.

    Args:
        worktree: Absolute path to the feature worktree.
        task_file: Path to the task markdown file (relative to worktree).
        index_path: Path to the per-spec index file (relative to worktree).
        assessment: The assessment to validate.
        policy: Current complexity policy.

    Returns:
        True if the assessment matches current inputs, False otherwise.
    """
    try:
        # Recollect evidence
        current_evidence = await collect_complexity(worktree, task_file, index_path, policy)

        # Compare hashes
        return (
            current_evidence.head_sha == assessment.evidence.head_sha
            and current_evidence.task_sha256 == assessment.evidence.task_sha256
            and current_evidence.index_sha256 == assessment.evidence.index_sha256
            and current_evidence.policy_sha256 == assessment.evidence.policy_sha256
            and current_evidence.target_hashes == assessment.evidence.target_hashes
        )
    except Exception:
        logger.exception("Failed to validate complexity snapshot")
        return False


# --- Helper functions ---


def _extract_section(task_content: str, heading: str) -> Optional[str]:
    """Body text of `## <heading>` up to (not including) the next `## ` heading, or
    None if the heading is absent. Scopes counting to the declared section instead
    of scanning the whole document."""
    pattern = re.compile(rf"^## {re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(task_content)
    if not match:
        return None
    body = task_content[match.end() :]
    next_heading = re.search(r"^## ", body, re.MULTILINE)
    return body[: next_heading.start()] if next_heading else body


def _extract_task_id(task_content: str) -> str:
    """Extract task ID from task content."""
    # Look for task ID in the first few lines
    lines = task_content.split("\n")[:10]
    for line in lines:
        if line.startswith("# "):
            # Extract TASK-XXXX from header
            match = re.search(r"(TASK-\d+)", line)
            if match:
                return match.group(1)
    raise ValueError("Could not extract task ID from task content")


async def _get_git_head_sha(worktree: Path) -> str:
    """Get the current HEAD SHA from git."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "rev-parse",
        "HEAD",
        cwd=worktree,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
    if proc.returncode != 0:
        raise RuntimeError(f"git rev-parse failed: {stderr.decode()}")
    return stdout.decode().strip()


def _sha256_file(file_path: Path) -> str:
    """Calculate SHA-256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def _canonical_hash(obj: object) -> str:
    """Generate a canonical hash of an object."""
    # Convert to dict if it's a Pydantic model
    if hasattr(obj, "model_dump"):
        data = obj.model_dump()
    elif hasattr(obj, "dict"):
        data = obj.dict()
    else:
        data = obj

    # Create canonical JSON representation
    json_str = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    # Generate SHA-256 hash
    return hashlib.sha256(json_str.encode("utf-8")).hexdigest()


async def _collect_all_evidence(
    worktree: Path,
    task_file: Path,
    index_path: Path,
    contract: ComplexityContract,
    policy: ComplexityPolicy,
    semaphore: asyncio.Semaphore,
) -> Tuple[Dict[str, MetricEvidence], Dict[str, Optional[str]], Dict[str, str], Dict[str, str], Dict[str, object]]:
    """Collect all evidence concurrently."""
    # Initialize results
    metrics: Dict[str, MetricEvidence] = {}
    target_hashes: Dict[str, Optional[str]] = {}
    wiki_evidence_hashes: Dict[str, str] = {}
    collector_versions: Dict[str, str] = {}
    details: Dict[str, object] = {}

    # Collect target hashes. Spec §2 item 3: "Missing MODIFY targets or
    # existing CREATE targets invalidate the contract and block dispatch; do
    # not silently change action." -- a CREATE target that already exists on
    # disk, or a MODIFY target that does not, means the declared action
    # disagrees with reality and the contract itself is unreliable, not just
    # one metric.
    for target in contract.targets:
        target_path = worktree / target.path
        target_exists = await asyncio.to_thread(target_path.exists)
        if target.action == "CREATE":
            if target_exists:
                raise ComplexityContractError(
                    f"CREATE target already exists on disk: {target.path}",
                    "complexity_contract_invalid",
                    details={"path": target.path, "action": target.action},
                )
            target_hashes[target.path] = None
        else:  # MODIFY
            if not target_exists:
                raise ComplexityContractError(
                    f"MODIFY target does not exist on disk: {target.path}",
                    "complexity_contract_invalid",
                    details={"path": target.path, "action": target.action},
                )
            target_hashes[target.path] = _sha256_file(target_path)

    # Collect metrics concurrently
    tasks = []

    # Cyclomatic complexity (Ruff)
    tasks.append(_collect_ruff_cyclomatic(worktree, contract, policy, semaphore))

    # Syntax errors (Ruff)
    tasks.append(_collect_ruff_syntax(worktree, contract, policy, semaphore))

    # Wiki blast radius. `contract_symbols` distinguishes `None` (legacy task,
    # coverage never declared -- unknown) from `()` (task explicitly declared
    # zero symbols -- not_applicable); a bare truthiness check collapses both
    # into the same conservative-losing branch (spec §2 item 2 / AC12).
    if contract.contract_symbols:
        tasks.append(_collect_wiki_blast(worktree, contract, policy, semaphore))
    elif contract.contract_symbols is None:
        metrics["blast_symbols"] = MetricEvidence(
            state="unknown",
            reason="Task contract does not declare contract_symbols (legacy/missing coverage)",
            source="wiki_collector",
        )
        wiki_evidence_hashes = {}
    else:
        # Explicit empty tuple: task declared zero symbols to analyze.
        metrics["blast_symbols"] = MetricEvidence(
            state="not_applicable",
            reason="Task contract explicitly declares zero contract symbols",
            source="wiki_collector",
        )
        wiki_evidence_hashes = {}

    # Weighted files, modules, acceptance criteria
    tasks.append(_collect_scope_metrics(worktree, task_file, contract, policy))

    # Downstream tasks
    tasks.append(_collect_dependency_metrics(worktree, task_file, index_path, contract, policy))

    # Wait for all collectors
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    for result in results:
        if isinstance(result, Exception):
            logger.warning(f"Collector failed: {result}")
            continue
        if isinstance(result, tuple) and len(result) == 5:
            # Unpack collector results. The per-collector version dict is named
            # `result_versions` here, NOT `collector_versions` -- reusing that
            # name rebound the outer accumulator on every iteration, so
            # `collector_versions.update(collector_versions)` was a no-op
            # against itself and the function silently returned only the
            # LAST collector's own (usually empty) version dict, discarding
            # every earlier collector's recorded version (spec §2's
            # "collector_versions" provenance field / AC1).
            collector_metrics, collector_target_hashes, collector_wiki_hashes, result_versions, collector_details = (
                result
            )

            # Merge results
            metrics.update(collector_metrics)
            target_hashes.update(collector_target_hashes)
            wiki_evidence_hashes.update(collector_wiki_hashes)
            collector_versions.update(result_versions)
            details.update(collector_details)

    return metrics, target_hashes, wiki_evidence_hashes, collector_versions, details


# --- Individual collectors ---
async def _collect_ruff_cyclomatic(
    worktree: Path, contract: ComplexityContract, policy: ComplexityPolicy, semaphore: asyncio.Semaphore
) -> Tuple[Dict[str, MetricEvidence], Dict[str, Optional[str]], Dict[str, str], Dict[str, str], Dict[str, object]]:
    """Collect cyclomatic complexity using Ruff."""
    async with semaphore:
        try:
            modify_targets = [target for target in contract.targets if target.action == "MODIFY"]

            if not modify_targets:
                # No MODIFY targets at all -- genuinely not applicable.
                return (
                    {
                        "cyclomatic_max": MetricEvidence(
                            state="not_applicable",
                            reason="No MODIFY targets to analyze",
                            source="ruff_cyclomatic",
                        )
                    },
                    {},
                    {},
                    {"ruff": "unknown"},
                    {},
                )

            python_modify_paths = [t.path for t in modify_targets if t.path.endswith((".py", ".pyi"))]

            # Any non-Python, non-doc/config MODIFY target is a language Ruff
            # cannot analyze. The score is a MAXIMUM over every MODIFY target
            # (spec §2 item 1), so this check must run regardless of whether
            # Python targets are ALSO present -- a task modifying both a .py
            # and a .rs file cannot claim "ok" from the .py file alone while
            # silently never measuring the .rs file.
            non_doc_non_python_targets = [
                t.path
                for t in modify_targets
                if not t.path.endswith((".py", ".pyi")) and Path(t.path).suffix.lower() not in _DOC_CONFIG_EXTENSIONS
            ]
            if non_doc_non_python_targets:
                return (
                    {
                        "cyclomatic_max": MetricEvidence(
                            state="unknown",
                            reason=f"Unsupported source language(s) for MODIFY targets: {non_doc_non_python_targets}",
                            source="ruff_cyclomatic",
                        )
                    },
                    {},
                    {},
                    {"ruff": "unknown"},
                    {},
                )

            if not python_modify_paths:
                # MODIFY targets exist but are all documentation/configuration.
                # Spec §2 item 1: "Documentation/configuration gives
                # not_applicable" -- distinct from the unsupported-language
                # `unknown` branch above.
                return (
                    {
                        "cyclomatic_max": MetricEvidence(
                            state="not_applicable",
                            reason="MODIFY targets are documentation/configuration only",
                            source="ruff_cyclomatic",
                        )
                    },
                    {},
                    {},
                    {"ruff": "unknown"},
                    {},
                )

            # Run Ruff for cyclomatic complexity
            cmd = [
                "ruff",
                "check",
                "--isolated",
                "--no-cache",
                "--no-fix",
                "--ignore-noqa",
                "--select",
                "C901",
                "--config",
                "lint.mccabe.max-complexity=0",
                "--output-format",
                "json",
                *python_modify_paths,
            ]

            result = await _run_subprocess(cmd, worktree, policy.timeout_seconds, policy.max_output_bytes)

            if result.returncode not in (0, 1):
                # Ruff failed
                return (
                    {
                        "cyclomatic_max": MetricEvidence(
                            state="unknown",
                            reason=f"Ruff failed with exit code {result.returncode}: {result.stderr[:200]}",
                            source="ruff_cyclomatic",
                        )
                    },
                    {},
                    {},
                    {"ruff": "unknown"},
                    {},
                )

            # Parse Ruff output. `ruff check --output-format json` prints a
            # top-level JSON *array* of diagnostic objects (verified against
            # the installed ruff binary) -- not `{"diagnostics": [...]}`.
            try:
                ruff_output = json.loads(result.stdout)
                complexities = []

                # A MODIFY target that fails to parse makes Ruff exit 1 with
                # `code: "invalid-syntax"` diagnostics instead of any `C901`
                # entries (verified empirically: `ruff check --select C901`
                # against a syntactically broken file). Left unchecked, that
                # reads as "zero functions over the complexity threshold" --
                # a clean `ok`/0 -- instead of the unmeasurable module it
                # actually is. Spec §2 item 1 requires `unknown` here, not a
                # silent pass.
                syntax_error_files = sorted(
                    {
                        diagnostic.get("filename")
                        for diagnostic in ruff_output
                        if str(diagnostic.get("code", "")).startswith("invalid-syntax")
                    }
                )
                if syntax_error_files:
                    return (
                        {
                            "cyclomatic_max": MetricEvidence(
                                state="unknown",
                                reason=f"Unparseable Python in MODIFY target(s): {syntax_error_files}",
                                source="ruff_cyclomatic",
                            )
                        },
                        {},
                        {},
                        {"ruff": "unknown"},
                        {},
                    )

                # Extract complexity values from diagnostics
                for diagnostic in ruff_output:
                    if diagnostic.get("code") == "C901":
                        # Extract complexity value from message. Real format:
                        # "`name` is too complex (11 > 0)" -- the value is the
                        # first integer in the parens, not the parens' whole
                        # content (which also has the threshold after "> ").
                        message = diagnostic.get("message", "")
                        match = re.search(r"\((\d+)\s*>", message)
                        if match:
                            complexities.append(int(match.group(1)))

                max_complexity = max(complexities) if complexities else 0

                return (
                    {
                        "cyclomatic_max": MetricEvidence(
                            state="ok",
                            value=max_complexity,
                            reason="Maximum cyclomatic complexity from Ruff C901 analysis",
                            source="ruff_cyclomatic",
                        )
                    },
                    {},
                    {},
                    {"ruff": "unknown"},
                    {"cyclomatic_values": complexities},
                )

            except json.JSONDecodeError:
                return (
                    {
                        "cyclomatic_max": MetricEvidence(
                            state="unknown",
                            reason=f"Invalid JSON from Ruff: {result.stdout[:200]}",
                            source="ruff_cyclomatic",
                        )
                    },
                    {},
                    {},
                    {"ruff": "unknown"},
                    {},
                )

        except asyncio.TimeoutError:
            return (
                {
                    "cyclomatic_max": MetricEvidence(
                        state="unknown",
                        reason="Ruff cyclomatic analysis timed out",
                        source="ruff_cyclomatic",
                    )
                },
                {},
                {},
                {"ruff": "unknown"},
                {},
            )
        except Exception as e:
            return (
                {
                    "cyclomatic_max": MetricEvidence(
                        state="unknown",
                        reason=f"Ruff cyclomatic analysis failed: {str(e)}",
                        source="ruff_cyclomatic",
                    )
                },
                {},
                {},
                {"ruff": "unknown"},
                {},
            )


async def _collect_ruff_syntax(
    worktree: Path, contract: ComplexityContract, policy: ComplexityPolicy, semaphore: asyncio.Semaphore
) -> Tuple[Dict[str, MetricEvidence], Dict[str, Optional[str]], Dict[str, str], Dict[str, str], Dict[str, object]]:
    """Collect syntax error count using Ruff."""
    async with semaphore:
        try:
            # Get Python targets (both CREATE and MODIFY)
            python_paths = [target.path for target in contract.targets if target.path.endswith((".py", ".pyi"))]

            if not python_paths:
                # No Python files to analyze
                return ({}, {}, {}, {"ruff_syntax": "unknown"}, {})

            # Run Ruff for syntax errors
            cmd = [
                "ruff",
                "check",
                "--isolated",
                "--no-cache",
                "--no-fix",
                "--select",
                "E9",
                "--output-format",
                "json",
                *python_paths,
            ]

            result = await _run_subprocess(cmd, worktree, policy.timeout_seconds, policy.max_output_bytes)

            # Count syntax errors. Same top-level-array shape as the
            # cyclomatic collector above -- not `{"diagnostics": [...]}`.
            syntax_error_count = 0
            if result.returncode in (0, 1):
                try:
                    ruff_output = json.loads(result.stdout)
                    syntax_error_count = len([d for d in ruff_output if d.get("code", "").startswith("E9")])
                except json.JSONDecodeError:
                    pass  # Ignore JSON errors for syntax collection

            # We don't return a metric for syntax errors directly, but we track the version
            return ({}, {}, {}, {"ruff": "unknown"}, {"syntax_errors": syntax_error_count})

        except Exception as e:
            # Syntax errors don't produce a metric, just log the error
            logger.warning(f"Ruff syntax analysis failed: {e}")
            return ({}, {}, {}, {"ruff": "unknown"}, {})


async def _collect_wiki_blast(
    worktree: Path, contract: ComplexityContract, policy: ComplexityPolicy, semaphore: asyncio.Semaphore
) -> Tuple[Dict[str, MetricEvidence], Dict[str, Optional[str]], Dict[str, str], Dict[str, str], Dict[str, object]]:
    """Collect blast radius evidence using wikitoolkit."""
    async with semaphore:
        try:
            if not contract.contract_symbols:
                # `None` (legacy/missing coverage) is unknown; `()` (explicit
                # empty declaration) is not_applicable -- see spec §2 item 2 /
                # AC12. Callers that already know the contract is legacy
                # short-circuit before this collector runs (`_collect_all_evidence`),
                # but keep this branch correct standalone too.
                state = "unknown" if contract.contract_symbols is None else "not_applicable"
                reason = (
                    "Task contract does not declare contract_symbols (legacy/missing coverage)"
                    if state == "unknown"
                    else "Task contract explicitly declares zero contract symbols"
                )
                return (
                    {
                        "blast_symbols": MetricEvidence(
                            state=state,
                            reason=reason,
                            source="wiki_collector",
                        )
                    },
                    {},
                    {},
                    {},
                    {},
                )

            impacted_ids: set = set()  # UNION across roots, not a sum of per-root lengths
            all_files: set = set()
            wiki_hashes = {}
            all_impacted_details = []
            # Any root that fails/times out/returns invalid JSON/reports
            # truncation makes the WHOLE measurement `unknown` (spec §2 item 2:
            # "Missing roots, failed queries, stale results or truncation are
            # unknown, with the observed count retained as a lower bound" --
            # never silently reported as a clean `ok` measurement).
            any_root_unreliable = False
            unreliable_reasons: List[str] = []

            # Analyze each symbol
            for symbol in contract.contract_symbols:
                try:
                    # Run wikitoolkit symbols blast. `--path` is a `symbols
                    # blast`-level option (path_option decorates that leaf
                    # command specifically, not the top-level `wiki` group --
                    # verified in wiki/cli.py), so it must come AFTER "symbols
                    # blast" on the command line, not before "symbols".
                    cmd = [
                        "python",
                        "-m",
                        "parrot.knowledge.wiki.cli",
                        "symbols",
                        "blast",
                        "--path",
                        # `worktree` is already required to be absolute
                        # (validated in `collect_complexity`); `.absolute()`
                        # is a redundant blocking pathlib call (ASYNC240).
                        str(worktree),
                        "--depth",
                        "2",
                        "--no-inferred",
                        "--tests",
                        "--json",
                        symbol,
                    ]

                    result = await _run_subprocess(cmd, worktree, policy.timeout_seconds, policy.max_output_bytes)

                    if result.returncode != 0:
                        any_root_unreliable = True
                        unreliable_reasons.append(f"{symbol}: exit {result.returncode}")
                        continue

                    # Parse output
                    try:
                        blast_output = json.loads(result.stdout)

                        # Hash the evidence
                        evidence_hash = hashlib.sha256(result.stdout.encode()).hexdigest()
                        wiki_hashes[symbol] = evidence_hash

                        # Extract impacted symbol IDs (deduplicated union, not a
                        # per-root count sum -- two roots sharing 15 callers
                        # must report 15, not 30). Real CLI JSON shape (verified
                        # against BlastRadiusOutput/ImpactedSymbol in
                        # structural/service.py, serialized via model_dump in
                        # structural/tools.py): `impacted` is a list of
                        # {"symbol": {"symbol_id": ..., "stale": ..., ...},
                        # "via": ..., "distance": ..., "provenance": ...} --
                        # the id and staleness live on the NESTED "symbol"
                        # object, not on the impacted entry itself.
                        impacted_symbols = blast_output.get("impacted", [])
                        root = blast_output.get("root")
                        files = blast_output.get("files", [])
                        truncated = blast_output.get("truncated", False)

                        if root is None:
                            # Missing root: observed count is a lower bound only.
                            any_root_unreliable = True
                            unreliable_reasons.append(f"{symbol}: missing root")
                        elif isinstance(root, dict) and root.get("stale"):
                            # Stale root: the wiki index disagrees with the
                            # file on disk (spec §2 item 2: "stale results ...
                            # are unknown").
                            any_root_unreliable = True
                            unreliable_reasons.append(f"{symbol}: stale root")

                        symbol_ids: set = set()
                        any_impacted_stale = False
                        for item in impacted_symbols:
                            if not isinstance(item, dict):
                                continue
                            hit = item.get("symbol")
                            if not isinstance(hit, dict):
                                continue
                            symbol_id = hit.get("symbol_id")
                            if symbol_id:
                                symbol_ids.add(symbol_id)
                            if hit.get("stale"):
                                any_impacted_stale = True
                        impacted_ids.update(symbol_ids)
                        all_files.update(files)

                        if any_impacted_stale:
                            any_root_unreliable = True
                            unreliable_reasons.append(f"{symbol}: stale impacted symbol(s)")

                        if truncated:
                            any_root_unreliable = True
                            unreliable_reasons.append(f"{symbol}: truncated")

                        # Store details
                        all_impacted_details.append(
                            {
                                "symbol": symbol,
                                "impacted_count": len(symbol_ids),
                                "file_count": len(files),
                                "truncated": truncated,
                            }
                        )

                    except json.JSONDecodeError:
                        any_root_unreliable = True
                        unreliable_reasons.append(f"{symbol}: invalid JSON")
                        continue

                except Exception as exc:
                    any_root_unreliable = True
                    unreliable_reasons.append(f"{symbol}: {exc}")
                    continue

            total_impacted = len(impacted_ids)

            if any_root_unreliable:
                metric_state = "unknown"
                metric_value = total_impacted  # observed union is a LOWER BOUND
                metric_reason = "Blast radius incomplete (" + "; ".join(unreliable_reasons) + ")"
            else:
                metric_state = "ok"
                metric_value = total_impacted
                metric_reason = f"Union of impacted symbols across {len(contract.contract_symbols)} contract symbols"

            return (
                {
                    "blast_symbols": MetricEvidence(
                        state=metric_state,
                        value=metric_value,
                        reason=metric_reason,
                        source="wiki_collector",
                    )
                },
                {},
                wiki_hashes,
                {},
                {"blast_details": all_impacted_details, "unique_files": sorted(all_files)},
            )

        except asyncio.TimeoutError:
            return (
                {
                    "blast_symbols": MetricEvidence(
                        state="unknown",
                        reason="Wiki blast analysis timed out",
                        source="wiki_collector",
                    )
                },
                {},
                {},
                {},
                {},
            )
        except Exception as e:
            return (
                {
                    "blast_symbols": MetricEvidence(
                        state="unknown",
                        reason=f"Wiki blast analysis failed: {str(e)}",
                        source="wiki_collector",
                    )
                },
                {},
                {},
                {},
                {},
            )


async def _collect_scope_metrics(
    worktree: Path, task_file: Path, contract: ComplexityContract, policy: ComplexityPolicy
) -> Tuple[Dict[str, MetricEvidence], Dict[str, Optional[str]], Dict[str, str], Dict[str, str], Dict[str, object]]:
    """Collect file scope and criteria metrics."""
    try:
        # Read task content
        full_task_path = worktree / task_file
        task_content = full_task_path.read_text(encoding="utf-8")

        # Count TOP-LEVEL acceptance criteria checkboxes, scoped to the
        # '## Acceptance Criteria' section and excluding fenced content and
        # nested/indented bullets (spec §2 item 4: "count top-level checkbox
        # criteria in the task's Acceptance Criteria section ... excluding
        # fenced code and nested explanatory bullets. Missing/malformed
        # sections are unknown."). A missing section is NOT a measured zero.
        ac_section = _extract_section(task_content, "Acceptance Criteria")
        criteria_count: Optional[int] = None
        if ac_section is not None:
            # Strip fenced blocks within the section before counting.
            unfenced = re.sub(r"```.*?```", "", ac_section, flags=re.DOTALL)
            criteria_count = 0
            for line in unfenced.splitlines():
                # Top-level only: no leading whitespace before the bullet marker.
                if re.match(r"^[-*]\s+\[[xX \-]\]\s+", line):
                    criteria_count += 1

        # Count file targets
        create_count = sum(1 for target in contract.targets if target.action == "CREATE")
        modify_count = sum(1 for target in contract.targets if target.action == "MODIFY")

        # Weighted file count: CREATE + 2*MODIFY
        weighted_files = create_count + 2 * modify_count

        # Module count (unique parent directories)
        parent_dirs = set()
        for target in contract.targets:
            parent = str(Path(target.path).parent)
            if parent == ".":
                parent = ""
            parent_dirs.add(parent)

        module_count = len(parent_dirs)

        if criteria_count is None:
            acceptance_criteria_evidence = MetricEvidence(
                state="unknown",
                reason="No '## Acceptance Criteria' section found",
                source="scope_collector",
            )
        else:
            acceptance_criteria_evidence = MetricEvidence(
                state="ok",
                value=criteria_count,
                reason="Top-level acceptance criteria checkboxes in the Acceptance Criteria section",
                source="scope_collector",
            )

        return (
            {
                "weighted_files": MetricEvidence(
                    state="ok",
                    value=weighted_files,
                    reason=f"{create_count} CREATE + 2*{modify_count} MODIFY targets",
                    source="scope_collector",
                ),
                "modules": MetricEvidence(
                    state="ok",
                    value=module_count,
                    reason="Unique target parent directories",
                    source="scope_collector",
                ),
                "acceptance_criteria": acceptance_criteria_evidence,
            },
            {},
            {},
            {},
            {
                "create_count": create_count,
                "modify_count": modify_count,
                # Sorted, not a raw `list(set(...))`: `_canonical_hash` only
                # sorts dict KEYS (`sort_keys=True`), never list contents, so
                # an unsorted set-derived list can serialize (and therefore
                # hash) differently across processes under hash randomization
                # -- undermining "same evidence/policy gives identical result".
                "parent_directories": sorted(parent_dirs),
            },
        )

    except Exception as e:
        return (
            {
                "weighted_files": MetricEvidence(
                    state="unknown",
                    reason=f"Scope metrics collection failed: {str(e)}",
                    source="scope_collector",
                ),
                "modules": MetricEvidence(
                    state="unknown",
                    reason=f"Module count collection failed: {str(e)}",
                    source="scope_collector",
                ),
                "acceptance_criteria": MetricEvidence(
                    state="unknown",
                    reason=f"Criteria count collection failed: {str(e)}",
                    source="scope_collector",
                ),
            },
            {},
            {},
            {},
            {},
        )


async def _collect_dependency_metrics(
    worktree: Path, task_file: Path, index_path: Path, contract: ComplexityContract, policy: ComplexityPolicy
) -> Tuple[Dict[str, MetricEvidence], Dict[str, Optional[str]], Dict[str, str], Dict[str, str], Dict[str, object]]:
    """Collect downstream dependency metrics."""
    try:
        # Read index file
        full_index_path = worktree / index_path
        index_content = full_index_path.read_text(encoding="utf-8")

        # Parse index as JSON
        try:
            index_data = json.loads(index_content)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown if it's a markdown file
            if index_path.suffix.lower() in (".md", ".markdown"):
                # Extract JSON from code blocks
                json_match = re.search(r"```json\s*(\{.*?\})\s*```", index_content, re.DOTALL)
                if json_match:
                    index_data = json.loads(json_match.group(1))
                else:
                    raise
            else:
                raise

        # Extract task ID from task file
        task_id = _extract_task_id((worktree / task_file).read_text(encoding="utf-8"))

        # Handle both list and dict formats
        tasks_list = []
        if isinstance(index_data, dict):
            if "tasks" in index_data:
                tasks_list = index_data["tasks"]
            else:
                # Assume the dict itself is the tasks mapping
                tasks_list = list(index_data.values())
        elif isinstance(index_data, list):
            tasks_list = index_data

        # Build the reverse dependency graph (task_id -> tasks that declare
        # `depends_on` including it) once, then BFS from the direct
        # dependents to the full transitive closure. Spec §2 item 5: "count
        # distinct direct dependents and distinct transitive descendants ...
        # Deduplicate diamond paths ... The score uses transitive count;
        # direct count remains visible." A missing depends_on reference or a
        # cycle back to task_id "invalidates the dependency contract" --
        # reported as unknown rather than a silently-wrong number.
        known_ids: set = set()
        reverse_deps: Dict[str, List[str]] = {}
        for task_entry in tasks_list:
            if not isinstance(task_entry, dict):
                continue
            entry_id = task_entry.get("id")
            if entry_id:
                known_ids.add(entry_id)
            for dep in task_entry.get("depends_on") or []:
                reverse_deps.setdefault(dep, []).append(entry_id)

        # A depends_on reference to a task ID that is never itself declared
        # as a task entry anywhere in the index is dangling -- checked
        # index-wide (this invalidates "the dependency contract" as a whole,
        # not just this task's own downstream slice), not merely within the
        # subgraph reachable from task_id's own descendants.
        dangling = {dep for dep in reverse_deps if dep not in known_ids}

        direct_dependents = sorted(d for d in reverse_deps.get(task_id, []) if d)

        cycle_detected = False
        transitive: set = set()
        queue = list(direct_dependents)
        while queue:
            current = queue.pop(0)
            if current == task_id:
                cycle_detected = True
                continue
            if current is None or current in transitive or current not in known_ids:
                continue
            transitive.add(current)
            queue.extend(reverse_deps.get(current, []))

        if cycle_detected or dangling:
            reason = "Dependency graph invalid: "
            reason += "cycle detected" if cycle_detected else ""
            if dangling:
                reason += (", " if cycle_detected else "") + f"dangling reference(s) to {sorted(dangling)}"
            return (
                {
                    "downstream_tasks": MetricEvidence(
                        state="unknown",
                        reason=reason,
                        source="dependency_collector",
                    )
                },
                {},
                {},
                {},
                {"direct_dependents": direct_dependents},
            )

        downstream_count = len(transitive)

        return (
            {
                "downstream_tasks": MetricEvidence(
                    state="ok",
                    value=downstream_count,
                    reason=f"Transitive descendants of {task_id} ({len(direct_dependents)} direct)",
                    source="dependency_collector",
                )
            },
            {},
            {},
            {},
            {"direct_dependents": direct_dependents, "transitive_descendants": sorted(transitive)},
        )

    except Exception as e:
        return (
            {
                "downstream_tasks": MetricEvidence(
                    state="unknown",
                    reason=f"Dependency metrics collection failed: {str(e)}",
                    source="dependency_collector",
                )
            },
            {},
            {},
            {},
            {},
        )


class SubprocessResult:
    """Result of a subprocess execution."""

    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


async def _run_subprocess(cmd: List[str], cwd: Path, timeout_seconds: int, max_output_bytes: int) -> SubprocessResult:
    """Run a subprocess with bounded output and timeout."""
    # Create subprocess
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        # Wait for completion with timeout
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)

        # Decode output, limiting size
        stdout_str = stdout.decode("utf-8", errors="replace")[:max_output_bytes]
        stderr_str = stderr.decode("utf-8", errors="replace")[:max_output_bytes]

        return SubprocessResult(proc.returncode, stdout_str, stderr_str)

    except (asyncio.TimeoutError, asyncio.CancelledError):
        # Kill and reap on EITHER a timeout OR the awaiting task being
        # cancelled (spec §7: "cancellation must terminate and reap their
        # processes") -- only handling TimeoutError left a cancelled
        # collection's subprocess un-reaped.
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass  # Process already finished
        raise
