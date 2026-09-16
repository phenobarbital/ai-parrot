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


_FILES_HEADING = re.compile(r"^## Files to Create ?/ ?Modify\s*$", re.MULTILINE)  # sdd/templates/task.md:33
_NEXT_HEADING = re.compile(r"^## ", re.MULTILINE)
_TABLE_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(CREATE|MODIFY|create|modify)\s*\|")


def _parse_legacy_targets(task_text: str) -> List[Dict[str, str]]:
    """Fallback target list for a task with no '## Complexity Contract' section.

    Every task, old or new, has a '## Files to Create / Modify' table (it
    predates this feature -- see docs/sdd/WORKFLOW.md's Task Artifact
    Format); reuse it as the target declaration for legacy tasks instead of
    treating their absence of a Complexity Contract section as invalid.
    """
    heading = _FILES_HEADING.search(task_text)
    if not heading:
        return []
    body = task_text[heading.end() :]
    next_heading = _NEXT_HEADING.search(body)
    if next_heading:
        body = body[: next_heading.start()]

    targets: List[Dict[str, str]] = []
    seen: set = set()
    for line in body.splitlines():
        match = _TABLE_ROW.match(line.strip())
        if not match:
            continue
        path, action = match.group(1), match.group(2).upper()
        if path in seen:
            continue
        seen.add(path)
        targets.append({"path": path, "action": action})
    return targets


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

    A task with NO '## Complexity Contract' section is a legacy task, not an
    invalid one (spec §2: "Legacy tasks without this section remain parseable
    but yield unknown symbol coverage and therefore require the complex-task
    route until upgraded" -- AC12). Its targets are read from the
    '## Files to Create / Modify' table every task already has, and
    `contract_symbols` is `None` (the explicit legacy/unknown-coverage
    marker, distinct from an empty list meaning "declared zero symbols").

    Args:
        task_text: The full task markdown text.

    Returns:
        The parsed ComplexityContract.

    Raises:
        ComplexityContractError: If a present Complexity Contract section is malformed.
    """
    # Extract the complexity contract section
    contract_json = _extract_complexity_contract_section(task_text)
    if not contract_json:
        legacy_targets = _parse_legacy_targets(task_text)
        return ComplexityContract(
            schema_version=1,
            targets=tuple(
                ComplexityTarget(path=_normalize_path(t["path"]), action=t["action"]) for t in legacy_targets
            ),
            contract_symbols=None,
        )

    try:
        # Parse the JSON
        contract_data = json.loads(contract_json)
    except json.JSONDecodeError as e:
        raise ComplexityContractError(f"Invalid JSON in Complexity Contract: {e}", "complexity_contract_invalid") from e

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

    # Cross-validate against the task's own "Files to Create / Modify" table
    # (spec §2's Measurement Contract: "The parser must compare its targets
    # with Files to Create / Modify") -- an explicit Complexity Contract that
    # under- or over-declares relative to the real scope table is invalid,
    # not silently accepted at face value.
    files_table_targets = {(_normalize_path(t["path"]), t["action"]) for t in _parse_legacy_targets(task_text)}
    declared_targets = {(t["path"], t["action"]) for t in normalized_targets}
    if files_table_targets and declared_targets != files_table_targets:
        raise ComplexityContractError(
            "Complexity Contract targets do not match the Files to Create / Modify table",
            "complexity_contract_invalid",
            details={
                "contract_only": sorted(declared_targets - files_table_targets),
                "table_only": sorted(files_table_targets - declared_targets),
            },
        )

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
        raise ComplexityContractError(f"Invalid ComplexityContract: {e}", "complexity_contract_invalid") from e


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

    # 2 points at/above the metric's own two-point threshold (spec's "inclusive
    # bands" second boundary -- ALL SIX metrics have one, not just the three
    # hard_limits metrics: weighted_files/modules/acceptance_criteria can and
    # must reach 2 points too, they just never auto-trigger complex by
    # themselves the way hard_limits metrics do).
    if metric_name in policy.two_point_thresholds and value >= policy.two_point_thresholds[metric_name]:
        return 2

    # Check bands: `policy.bands[metric_name]` is the (0, max) zero-points
    # band from spec §2 (e.g. cyclomatic_max 0-10 scores 0). A value at or
    # below that band's max is 0 points; above it (but below the two-point
    # threshold, already handled above) is 1 point.
    if metric_name in policy.bands:
        _min_val, max_val = policy.bands[metric_name]
        if value <= max_val:
            return 0
        return 1

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

    # Calculate points for each metric. A metric ABSENT from evidence.metrics
    # (a defensive case -- a correctly-run collector always populates all six
    # keys) is treated exactly like an unknown-state metric: 0 points, but
    # still flagged for the has_unknown check below. Never a silent, fully
    # trusted zero (spec: never fabricate a zero for missing evidence).
    missing_metrics: List[str] = []
    for metric_name in metric_names:
        if metric_name in evidence.metrics:
            points = _calculate_component_points(metric_name, evidence.metrics[metric_name], policy)
            component_points[metric_name] = points
            total_points += points
        else:
            component_points[metric_name] = 0
            missing_metrics.append(metric_name)

    # Determine classification
    classification = "standard"

    # Check for hard limits that force complex classification, using the
    # POLICY's own hard_limits (not a hardcoded local copy) -- an
    # operator-reconfigured policy must actually change this behavior, not
    # just per-metric point scoring.
    for metric_name, threshold in policy.hard_limits.items():
        # A `state == "unknown"` metric may still carry an observed lower
        # bound (spec §2); if that bound already meets the hard limit, the
        # task is provably complex even though the exact value is unknown.
        # Only `not_applicable` (value always None) cannot trigger this.
        if (
            metric_name in evidence.metrics
            and evidence.metrics[metric_name].state in ("ok", "unknown")
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
            # Check if any metrics are unknown (or simply absent -- both are
            # "cannot determine", never a trusted zero) - if so, unknown.
            has_unknown = bool(missing_metrics) or any(
                metric_name in evidence.metrics and evidence.metrics[metric_name].state == "unknown"
                for metric_name in metric_names
            )

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
