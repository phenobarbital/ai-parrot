"""Deterministic complexity evaluation for SDD tasks (spec §2-§4).

Parses task contracts and evaluates deterministic complexity without invoking
external tools or filesystem operations. Pure functions only; no I/O, no side effects.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Dict, List, Optional


from parrot.flows.dev_loop.sdd_coder.complexity_models import (
    ComplexityAssessment,
    ComplexityContract,
    ComplexityEvidence,
    ComplexityPolicy,
    ComplexityTarget,
    MetricEvidence,
)


class ComplexityContractError(ValueError):
    """Raised when a task's complexity contract is invalid or malformed.

    Attributes:
        code: Error code identifying the specific contract violation.
        details: Additional diagnostic information about the error.
    """

    def __init__(
        self, message: str, code: str = "complexity_contract_invalid", details: Optional[Dict[str, object]] = None
    ):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _normalize_path(path: str) -> str:
    """Normalize a file path according to lexical rules.

    Collapses harmless ./ components and separators deterministically.
    Preserves case sensitivity. Rejects absolute paths, escapes and globs.

    Args:
        path: The path to normalize.

    Returns:
        The normalized path.

    Raises:
        ComplexityContractError: If the path contains invalid components.
    """
    # Check for absolute paths
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        raise ComplexityContractError(f"Absolute paths not allowed: {path!r}", "complexity_contract_invalid")

    # Check for escape sequences or glob patterns
    if ".." in path or "*" in path or "?" in path or "[" in path:
        raise ComplexityContractError(f"Invalid path components: {path!r}", "complexity_contract_invalid")

    # Normalize path separators
    normalized = path.replace("\\", "/")

    # Collapse multiple slashes
    while "//" in normalized:
        normalized = normalized.replace("//", "/")

    # Remove leading ./ components
    while normalized.startswith("./"):
        normalized = normalized[2:]

    # Remove trailing slash if present (except for root)
    if normalized != "/" and normalized.endswith("/"):
        normalized = normalized[:-1]

    return normalized


def _extract_complexity_contract_section(task_text: str) -> Optional[str]:
    """Extract the Complexity Contract section from task text.

    Args:
        task_text: The full task markdown text.

    Returns:
        The JSON content of the Complexity Contract section, or None if not found.
    """
    # Look for the Complexity Contract section
    pattern = r"## Complexity Contract\s*```json\s*(.*?)\s*```"
    match = re.search(pattern, task_text, re.DOTALL)
    if match:
        return match.group(1)
    return None


def parse_complexity_contract(task_text: str) -> ComplexityContract:
    """Parse the complexity contract from a task's markdown text.

    Args:
        task_text: The full task markdown text.

    Returns:
        The parsed ComplexityContract.

    Raises:
        ComplexityContractError: If the contract is malformed or invalid.
    """
    # Extract the complexity contract section
    contract_json = _extract_complexity_contract_section(task_text)
    if not contract_json:
        raise ComplexityContractError("No Complexity Contract section found", "complexity_contract_invalid")

    try:
        # Parse the JSON
        contract_data = json.loads(contract_json)
    except json.JSONDecodeError as e:
        raise ComplexityContractError(f"Invalid JSON in Complexity Contract: {e}", "complexity_contract_invalid")

    # Validate required fields
    if "schema_version" not in contract_data:
        raise ComplexityContractError("Missing schema_version in Complexity Contract", "complexity_contract_invalid")

    if contract_data.get("schema_version") != 1:
        raise ComplexityContractError(
            f"Unsupported schema version: {contract_data.get('schema_version')}", "complexity_contract_invalid"
        )

    if "targets" not in contract_data:
        raise ComplexityContractError("Missing targets in Complexity Contract", "complexity_contract_invalid")

    # Normalize target paths and actions
    normalized_targets = []
    for target in contract_data["targets"]:
        if "path" not in target or "action" not in target:
            raise ComplexityContractError("Target missing path or action", "complexity_contract_invalid")

        normalized_path = _normalize_path(target["path"])
        normalized_action = target["action"].upper()

        if normalized_action not in ("CREATE", "MODIFY"):
            raise ComplexityContractError(f"Invalid action: {target['action']}", "complexity_contract_invalid")

        normalized_targets.append({"path": normalized_path, "action": normalized_action})

    # Process contract_symbols
    contract_symbols = contract_data.get("contract_symbols")
    if contract_symbols is not None:
        if not isinstance(contract_symbols, list):
            raise ComplexityContractError("contract_symbols must be a list or null", "complexity_contract_invalid")
        contract_symbols = tuple(contract_symbols)

    # Create the ComplexityContract
    try:
        return ComplexityContract(
            schema_version=1,
            targets=tuple(ComplexityTarget(**target) for target in normalized_targets),
            contract_symbols=contract_symbols,
        )
    except Exception as e:
        raise ComplexityContractError(f"Invalid ComplexityContract: {e}", "complexity_contract_invalid")


def _calculate_component_points(metric_name: str, evidence: MetricEvidence, policy: ComplexityPolicy) -> int:
    """Calculate points for a single metric component.

    Args:
        metric_name: Name of the metric.
        evidence: Evidence for this metric.
        policy: The complexity policy.

    Returns:
        Points contributed by this metric (0-2).
    """
    # If not applicable, contributes zero points
    if evidence.state == "not_applicable":
        return 0

    # If unknown, contributes zero points (cannot determine)
    if evidence.state == "unknown":
        return 0

    # Must be "ok" state with a value
    if evidence.state != "ok" or evidence.value is None:
        return 0

    value = evidence.value

    # Check for hard limits first
    if metric_name in policy.hard_limits and value >= policy.hard_limits[metric_name]:
        # Hard limit reached, maximum points
        return 2

    # Check bands
    if metric_name in policy.bands:
        min_val, max_val = policy.bands[metric_name]
        if value >= min_val:
            if value <= max_val:
                # In band, 1 point
                return 1
            else:
                # Above band, 2 points
                return 2
        # Below minimum, 0 points
        return 0

    # Unknown metric, 0 points
    return 0


def _canonical_hash(obj: object) -> str:
    """Generate a canonical hash of an object.

    Args:
        obj: Object to hash (typically a Pydantic model).

    Returns:
        SHA-256 hash of the canonical JSON representation.
    """
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


def evaluate_complexity(evidence: ComplexityEvidence, policy: ComplexityPolicy) -> ComplexityAssessment:
    """Evaluate task complexity based on collected evidence and policy.

    Uses only the six metric keys fixed by TASK-3286. Inclusive bands are 11/21, 10/30, 4/8, 2/3, 5/8, 2/5;
    hard triggers 21 cyclomatic, 30 blast, 5 descendants. Sum ≥5 is complex.

    Args:
        evidence: Collected evidence for the task.
        policy: Complexity policy to apply.

    Returns:
        Complexity assessment with classification and scoring details.
    """
    component_points: Dict[str, int] = {}
    reason_codes: List[str] = []
    total_points = 0

    # Known metrics that contribute to complexity
    metric_names = [
        "cyclomatic_max",
        "blast_symbols",
        "weighted_files",
        "modules",
        "acceptance_criteria",
        "downstream_tasks",
    ]

    # Calculate points for each metric
    for metric_name in metric_names:
        if metric_name in evidence.metrics:
            points = _calculate_component_points(metric_name, evidence.metrics[metric_name], policy)
            component_points[metric_name] = points
            total_points += points
        else:
            # Metric not provided, contributes 0 points
            component_points[metric_name] = 0

    # Determine classification
    classification = "standard"

    # Check for hard limits that force complex classification
    hard_triggers = {"cyclomatic_max": 21, "blast_symbols": 30, "downstream_tasks": 5}

    for metric_name, threshold in hard_triggers.items():
        if (
            metric_name in evidence.metrics
            and evidence.metrics[metric_name].state == "ok"
            and evidence.metrics[metric_name].value is not None
            and evidence.metrics[metric_name].value >= threshold
        ):
            classification = "complex"
            reason_codes.append(f"hard_limit_{metric_name}")

    # If no hard limits triggered, use point-based classification
    if classification == "standard":
        if total_points >= policy.score_threshold:
            classification = "complex"
            reason_codes.append("score_threshold_met")
        else:
            # Check if any metrics are unknown - if so, classification is unknown
            has_unknown = False
            for metric_name in metric_names:
                if metric_name in evidence.metrics and evidence.metrics[metric_name].state == "unknown":
                    has_unknown = True
                    break

            if has_unknown:
                classification = "unknown"
                reason_codes.append("metric_unknown")
            else:
                reason_codes.append("score_below_threshold")

    # Create the assessment
    assessment = ComplexityAssessment(
        policy_version=policy.version,
        task_id=evidence.task_id,
        classification=classification,
        total_points=total_points,
        component_points=component_points,
        reason_codes=tuple(reason_codes),
        evidence=evidence,
        assessment_id="",  # Will be filled in by the validator
    )

    # Set the assessment_id using canonical hash
    assessment.assessment_id = _canonical_hash(assessment)

    return assessment
