"""GenericReportComparator — agnostic structural diff for S3-stored reports.

Provides two comparison modes:
1. Generic structural JSON diff (always available).
2. Parser-dispatch for scanner-aware comparison when scanner name is known.
   Currently dispatches to ``ScanComparator`` for CloudSploit; all other
   scanners fall back to generic diff.

Module implements Spec §3 Module 2 (FEAT-184).
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class GenericReportComparator:
    """Structural diff engine for S3-stored report documents.

    Supports two modes:

    - **Generic** (``comparison_mode="generic"``): Walks both dicts recursively
      and tracks keys added, removed, and changed with dotted-path notation.
    - **Parser-dispatch** (``comparison_mode="parser_dispatch"``): When
      ``scanner="cloudsploit"``, delegates to ``ScanComparator`` for
      richer, domain-aware comparison. Falls back to generic diff on any
      failure or for unknown scanners.

    Args:
        max_changes: Maximum number of change entries to include in the
            ``changes`` list. Larger diffs are truncated and the
            ``truncated`` flag is set to ``True``. Defaults to 50.
    """

    def __init__(self, max_changes: int = 50) -> None:
        """Initialize GenericReportComparator.

        Args:
            max_changes: Cap on the number of change entries returned.
        """
        self._max_changes = max_changes

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compare(
        self,
        baseline: dict | bytes,
        current: dict | bytes,
        *,
        scanner: str | None = None,
    ) -> dict:
        """Compare two report documents and return a structured diff.

        Both inputs can be Python dicts or raw JSON bytes. Bytes are
        decoded via ``json.loads`` before comparison.

        When ``scanner`` is ``"cloudsploit"`` and both inputs are valid
        CloudSploit scan results, the comparison is delegated to
        ``ScanComparator`` for domain-aware output. All other scanners
        (or any parse failure) fall back to generic structural diff.

        Args:
            baseline: Earlier (reference) report — dict or JSON bytes.
            current: Later report to compare against baseline.
            scanner: Scanner that produced the reports (e.g.,
                ``"cloudsploit"``). ``None`` triggers generic diff.

        Returns:
            Structured diff dict with keys:
            ``baseline_source``, ``current_source``, ``scanner``,
            ``comparison_mode``, ``summary``, ``changes``, ``truncated``.
        """
        # Decode bytes inputs
        baseline_bytes: bytes | None = None
        current_bytes: bytes | None = None

        if isinstance(baseline, bytes):
            baseline_bytes = baseline
            baseline = json.loads(baseline)
        if isinstance(current, bytes):
            current_bytes = current
            current = json.loads(current)

        # Attempt parser dispatch for known scanners
        if scanner == "cloudsploit":
            raw_baseline = baseline_bytes or json.dumps(baseline).encode()
            raw_current = current_bytes or json.dumps(current).encode()
            dispatch_result = self._dispatch_to_parser(raw_baseline, raw_current, scanner)
            if dispatch_result is not None:
                return dispatch_result

        # Fall back to generic structural diff
        diff = self._structural_diff(baseline, current)
        changes = diff["changes"]
        truncated = len(changes) > self._max_changes
        return {
            "baseline_source": "provided",
            "current_source": "provided",
            "scanner": scanner,
            "comparison_mode": "generic",
            "summary": {
                "keys_added": diff["keys_added"],
                "keys_removed": diff["keys_removed"],
                "keys_changed": diff["keys_changed"],
            },
            "changes": changes[: self._max_changes],
            "truncated": truncated,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _structural_diff(self, baseline: dict, current: dict) -> dict:
        """Walk both dicts recursively and produce a flat change list.

        Arrays are compared by length only — no element-level identity
        matching (that is the parser-dispatch responsibility).

        Args:
            baseline: Reference dict.
            current: Updated dict to compare against baseline.

        Returns:
            Dict with ``keys_added``, ``keys_removed``, ``keys_changed``
            (counts) and ``changes`` (list of change dicts with
            ``path``, ``change_type``, and optional ``old``/``new``).
        """
        changes: list[dict] = []
        self._walk(baseline, current, path="", changes=changes)
        added = sum(1 for c in changes if c["change_type"] == "added")
        removed = sum(1 for c in changes if c["change_type"] == "removed")
        changed = sum(1 for c in changes if c["change_type"] == "changed")
        return {
            "keys_added": added,
            "keys_removed": removed,
            "keys_changed": changed,
            "changes": changes,
        }

    def _walk(
        self,
        baseline: Any,
        current: Any,
        path: str,
        changes: list[dict],
    ) -> None:
        """Recursive walker for _structural_diff.

        Args:
            baseline: Value from baseline at this path.
            current: Value from current at this path.
            path: Dotted-path string for the current position.
            changes: Mutable list to append change entries to.
        """
        if isinstance(baseline, dict) and isinstance(current, dict):
            all_keys = set(baseline) | set(current)
            for key in sorted(all_keys):
                child_path = f"{path}.{key}" if path else key
                if key not in baseline:
                    changes.append(
                        {"path": child_path, "change_type": "added", "new": current[key]}
                    )
                elif key not in current:
                    changes.append(
                        {"path": child_path, "change_type": "removed", "old": baseline[key]}
                    )
                else:
                    self._walk(baseline[key], current[key], child_path, changes)
        elif isinstance(baseline, list) and isinstance(current, list):
            # Array: compare by length; do not recurse into elements
            if len(baseline) != len(current):
                changes.append(
                    {
                        "path": path,
                        "change_type": "changed",
                        "old": f"array[{len(baseline)}]",
                        "new": f"array[{len(current)}]",
                    }
                )
        else:
            if baseline != current:
                changes.append(
                    {"path": path, "change_type": "changed", "old": baseline, "new": current}
                )

    def _dispatch_to_parser(
        self,
        baseline: bytes,
        current: bytes,
        scanner: str,
    ) -> dict | None:
        """Try to delegate comparison to a scanner-specific comparator.

        Currently only ``"cloudsploit"`` has a dedicated comparator.
        For all other scanners, returns ``None`` immediately.

        Any exception raised during dispatch (parse error, model validation
        failure, etc.) is caught and logged as a warning, and ``None`` is
        returned so the caller can fall back to generic diff.

        Args:
            baseline: Raw JSON bytes for the baseline report.
            current: Raw JSON bytes for the current report.
            scanner: Scanner name identifying the dispatch target.

        Returns:
            Structured comparison dict on success, ``None`` on failure or
            for unsupported scanners.
        """
        if scanner != "cloudsploit":
            return None

        try:
            from parrot_tools.cloudsploit.comparator import ScanComparator
            from parrot_tools.cloudsploit.parser import ScanResultParser

            parser = ScanResultParser()
            baseline_result = parser.parse(baseline.decode("utf-8"))
            current_result = parser.parse(current.decode("utf-8"))

            comparator = ScanComparator()
            report = comparator.compare(baseline_result, current_result)

            new_count = len(report.new_findings)
            resolved_count = len(report.resolved_findings)
            severity_count = len(report.severity_changed)

            # Build a flat changes list from the three change categories
            changes: list[dict] = []
            for f in report.new_findings:
                changes.append(
                    {
                        "path": f"findings.{f.plugin}.{f.region}",
                        "change_type": "added",
                        "severity": f.status.value if hasattr(f.status, "value") else str(f.status),
                        "resource": f.resource,
                    }
                )
            for f in report.resolved_findings:
                changes.append(
                    {
                        "path": f"findings.{f.plugin}.{f.region}",
                        "change_type": "removed",
                        "severity": f.status.value if hasattr(f.status, "value") else str(f.status),
                        "resource": f.resource,
                    }
                )
            for sc in report.severity_changed:
                changes.append(
                    {
                        "path": f"findings.{sc.get('plugin', '')}.{sc.get('region', '')}",
                        "change_type": "severity_changed",
                        "old": sc.get("old_severity"),
                        "new": sc.get("new_severity"),
                        "resource": sc.get("resource"),
                    }
                )

            truncated = len(changes) > self._max_changes
            return {
                "baseline_source": "provided",
                "current_source": "provided",
                "scanner": scanner,
                "comparison_mode": "parser_dispatch",
                "summary": {
                    "keys_added": 0,
                    "keys_removed": 0,
                    "keys_changed": 0,
                    "findings_new": new_count,
                    "findings_resolved": resolved_count,
                    "severity_changes": severity_count,
                },
                "changes": changes[: self._max_changes],
                "truncated": truncated,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Parser dispatch failed for scanner %r — falling back to generic diff: %s",
                scanner,
                exc,
            )
            return None
