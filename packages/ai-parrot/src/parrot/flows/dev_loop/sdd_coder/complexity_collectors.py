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
from parrot.flows.dev_loop.sdd_coder.complexity import parse_complexity_contract

logger = logging.getLogger(__name__)


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
    # Validate inputs
    if not worktree.is_absolute():
        raise ValueError("worktree must be an absolute path")

    if not worktree.exists() or not worktree.is_dir():
        raise ValueError(f"worktree does not exist or is not a directory: {worktree}")

    full_task_path = worktree / task_file
    if not full_task_path.exists():
        raise ValueError(f"task_file does not exist: {full_task_path}")

    full_index_path = worktree / index_path
    if not full_index_path.exists():
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

    # Collect target hashes
    for target in contract.targets:
        if target.action == "CREATE":
            target_hashes[target.path] = None
        else:  # MODIFY
            target_path = worktree / target.path
            if target_path.exists():
                target_hashes[target.path] = _sha256_file(target_path)
            else:
                target_hashes[target.path] = None

    # Collect metrics concurrently
    tasks = []

    # Cyclomatic complexity (Ruff)
    tasks.append(_collect_ruff_cyclomatic(worktree, contract, policy, semaphore))

    # Syntax errors (Ruff)
    tasks.append(_collect_ruff_syntax(worktree, contract, policy, semaphore))

    # Wiki blast radius
    if contract.contract_symbols:
        tasks.append(_collect_wiki_blast(worktree, contract, policy, semaphore))
    else:
        # No symbols to analyze
        metrics["blast_symbols"] = MetricEvidence(
            state="not_applicable",
            reason="No contract symbols to analyze",
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
            # Unpack collector results
            collector_metrics, collector_target_hashes, collector_wiki_hashes, collector_versions, collector_details = (
                result
            )

            # Merge results
            metrics.update(collector_metrics)
            target_hashes.update(collector_target_hashes)
            wiki_evidence_hashes.update(collector_wiki_hashes)
            collector_versions.update(collector_versions)
            details.update(collector_details)

    return metrics, target_hashes, wiki_evidence_hashes, collector_versions, details


# --- Individual collectors ---
async def _collect_ruff_cyclomatic(
    worktree: Path, contract: ComplexityContract, policy: ComplexityPolicy, semaphore: asyncio.Semaphore
) -> Tuple[Dict[str, MetricEvidence], Dict[str, Optional[str]], Dict[str, str], Dict[str, str], Dict[str, object]]:
    """Collect cyclomatic complexity using Ruff."""
    async with semaphore:
        try:
            # Get Python MODIFY targets
            python_modify_paths = [
                target.path
                for target in contract.targets
                if target.action == "MODIFY" and target.path.endswith((".py", ".pyi"))
            ]

            if not python_modify_paths:
                # No Python files to analyze
                return (
                    {
                        "cyclomatic_max": MetricEvidence(
                            state="not_applicable",
                            reason="No Python MODIFY targets to analyze",
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

            # Parse Ruff output
            try:
                ruff_output = json.loads(result.stdout)
                complexities = []

                # Extract complexity values from diagnostics
                for diagnostic in ruff_output.get("diagnostics", []):
                    if diagnostic.get("code") == "C901":
                        # Extract complexity value from message
                        message = diagnostic.get("message", "")
                        # Message format: "Function is too complex (12)"
                        match = re.search(r"\((\d+)\)", message)
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

            # Count syntax errors
            syntax_error_count = 0
            if result.returncode in (0, 1):
                try:
                    ruff_output = json.loads(result.stdout)
                    syntax_error_count = len(
                        [d for d in ruff_output.get("diagnostics", []) if d.get("code", "").startswith("E9")]
                    )
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
                return (
                    {
                        "blast_symbols": MetricEvidence(
                            state="not_applicable",
                            reason="No contract symbols to analyze",
                            source="wiki_collector",
                        )
                    },
                    {},
                    {},
                    {},
                    {},
                )

            total_impacted = 0
            all_files = set()
            wiki_hashes = {}
            all_impacted_details = []

            # Analyze each symbol
            for symbol in contract.contract_symbols:
                try:
                    # Run wikitoolkit symbols blast
                    cmd = [
                        "python",
                        "-m",
                        "parrot.knowledge.wiki.cli",
                        "--path",
                        str(worktree.absolute()),
                        "symbols",
                        "blast",
                        "--depth",
                        "2",
                        "--no-inferred",
                        "--tests",
                        "--json",
                        symbol,
                    ]

                    result = await _run_subprocess(cmd, worktree, policy.timeout_seconds, policy.max_output_bytes)

                    if result.returncode != 0:
                        # Command failed, continue with unknown state
                        continue

                    # Parse output
                    try:
                        blast_output = json.loads(result.stdout)

                        # Hash the evidence
                        evidence_hash = hashlib.sha256(result.stdout.encode()).hexdigest()
                        wiki_hashes[symbol] = evidence_hash

                        # Extract impacted count
                        impacted_symbols = blast_output.get("impacted", [])
                        files = blast_output.get("files", [])
                        truncated = blast_output.get("truncated", False)

                        # Add to totals
                        total_impacted += len(impacted_symbols)
                        all_files.update(files)

                        # Store details
                        all_impacted_details.append(
                            {
                                "symbol": symbol,
                                "impacted_count": len(impacted_symbols),
                                "file_count": len(files),
                                "truncated": truncated,
                            }
                        )

                    except json.JSONDecodeError:
                        # Invalid JSON, continue
                        continue

                except Exception:
                    # Individual symbol failed, continue with others
                    continue

            # Create metric evidence
            metric_state = "ok"
            metric_value = total_impacted
            metric_reason = f"Total impacted symbols across {len(contract.contract_symbols)} contract symbols"

            if not contract.contract_symbols:
                metric_state = "not_applicable"
                metric_value = None
                metric_reason = "No contract symbols to analyze"

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
                {"blast_details": all_impacted_details, "unique_files": list(all_files)},
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

        # Count acceptance criteria checkboxes, excluding fenced content.
        # `re.split` on the fence pattern already *removes* every fenced
        # block and returns only the non-fenced segments (unlike
        # `re.finditer`, it never alternates fenced/non-fenced groups) --
        # every returned part must be counted, not just even-indexed ones.
        criteria_count = 0
        parts = re.split(r"```.*?```", task_content, flags=re.DOTALL)

        for part in parts:
            # Count unchecked [-] and checked [x] or [X] checkboxes
            criteria_count += len(re.findall(r"^\s*[-*]\s+\[[xX\s-]\]\s+", part, re.MULTILINE))

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
                "acceptance_criteria": MetricEvidence(
                    state="ok",
                    value=criteria_count,
                    reason="Acceptance criteria checkboxes outside code fences",
                    source="scope_collector",
                ),
            },
            {},
            {},
            {},
            {
                "create_count": create_count,
                "modify_count": modify_count,
                "parent_directories": list(parent_dirs),
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

        # Find all tasks that depend on this task
        downstream_tasks = []

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

        # Look for tasks that depend on our task
        for task_entry in tasks_list:
            if isinstance(task_entry, dict):
                depends_on = task_entry.get("depends_on", [])
                if task_id in depends_on:
                    downstream_tasks.append(task_entry.get("id", "unknown"))

        downstream_count = len(downstream_tasks)

        return (
            {
                "downstream_tasks": MetricEvidence(
                    state="ok",
                    value=downstream_count,
                    reason=f"Tasks that declare dependency on {task_id}",
                    source="dependency_collector",
                )
            },
            {},
            {},
            {},
            {"direct_dependents": downstream_tasks},
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

    except asyncio.TimeoutError:
        # Kill the process if it timed out
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass  # Process already finished
        raise
