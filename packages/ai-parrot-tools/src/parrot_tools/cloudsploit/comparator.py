"""Scan comparator for diffing two CloudSploit scan results."""
from .models import ComparisonReport, ScanFinding, ScanResult


class ScanComparator:
    """Compares two CloudSploit scan results to track security posture changes."""

    def compare(self, baseline: ScanResult, current: ScanResult) -> ComparisonReport:
        """Compare baseline and current scan results.

        Args:
            baseline: The earlier (reference) scan result.
            current: The latest scan result to compare against baseline.

        Returns:
            ComparisonReport with new, resolved, unchanged, and severity-changed findings.
        """
        baseline_map: dict[tuple, ScanFinding] = {
            self._finding_key(f): f for f in baseline.findings
        }
        current_map: dict[tuple, ScanFinding] = {
            self._finding_key(f): f for f in current.findings
        }

        baseline_keys = set(baseline_map)
        current_keys = set(current_map)

        new_keys = current_keys - baseline_keys
        resolved_keys = baseline_keys - current_keys
        common_keys = baseline_keys & current_keys

        new_findings = [current_map[k] for k in new_keys]
        resolved_findings = [baseline_map[k] for k in resolved_keys]

        unchanged_findings: list[ScanFinding] = []
        severity_changed: list[dict] = []

        for key in common_keys:
            b_finding = baseline_map[key]
            c_finding = current_map[key]
            if b_finding.status != c_finding.status:
                severity_changed.append({
                    "plugin": c_finding.plugin,
                    "region": c_finding.region,
                    "resource": c_finding.resource,
                    "old_severity": b_finding.status.value,
                    "new_severity": c_finding.status.value,
                })
            else:
                unchanged_findings.append(c_finding)

        return ComparisonReport(
            new_findings=new_findings,
            resolved_findings=resolved_findings,
            unchanged_findings=unchanged_findings,
            severity_changed=severity_changed,
            baseline_timestamp=baseline.summary.scan_timestamp,
            current_timestamp=current.summary.scan_timestamp,
        )

    def _finding_key(self, finding: ScanFinding) -> tuple:
        """Generate identity key for a finding: (plugin, region, resource).

        Args:
            finding: The scan finding to generate a key for.

        Returns:
            Tuple of (plugin, region, resource) used as identity.
        """
        return (finding.plugin, finding.region, finding.resource or "")
