"""Parses CloudSploit JSON output into typed ScanResult objects."""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import (
    ScanFinding,
    ScanResult,
    ScanSummary,
    SeverityLevel,
)


class ScanResultParser:
    """Parses CloudSploit JSON output into typed ScanResult objects."""

    # Map raw CloudSploit status strings to SeverityLevel enum values
    _STATUS_MAP: dict[str, SeverityLevel] = {
        "OK": SeverityLevel.OK,
        "PASS": SeverityLevel.OK,
        "WARN": SeverityLevel.WARN,
        "FAIL": SeverityLevel.FAIL,
        "UNKNOWN": SeverityLevel.UNKNOWN,
    }

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)

    def parse(
        self, raw_json: str, timestamp: Optional[datetime] = None
    ) -> ScanResult:
        """Parse raw CloudSploit JSON string into ScanResult.

        Args:
            raw_json: Raw JSON string from CloudSploit output.
            timestamp: Override scan timestamp. Defaults to now.

        Returns:
            Parsed ScanResult with findings and computed summary.
        """
        ts = timestamp or datetime.now()

        if not raw_json or not raw_json.strip():
            self.logger.warning("Empty scan output received.")
            return self._empty_result(ts)

        try:
            # Try parsing the whole string first
            data = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            # If it fails, try to find a JSON block (e.g., if there's logging noise)
            json_str = self._find_json_block(raw_json)
            if not json_str:
                self.logger.warning("Could not find a valid JSON block in output.")
                return self._empty_result(ts)
            
            try:
                data = json.loads(json_str)
            except (json.JSONDecodeError, TypeError) as exc:
                self.logger.warning("Malformed JSON input after extraction: %s", exc)
                return self._empty_result(ts)

        # Support both formats:
        # 1. Flat array: [{plugin, category, title, status, ...}, ...]
        # 2. Nested dict: {pluginId: {title, category, results: [...]}, ...}
        if isinstance(data, list):
            findings = self._extract_findings_from_array(data)
            raw_json_data = data
        elif isinstance(data, dict):
            # Detect a single flat finding dict (has 'plugin' and 'status' keys)
            if "plugin" in data and "status" in data:
                findings = self._extract_findings_from_array([data])
            else:
                findings = self._extract_findings(data)
            raw_json_data = data
        else:
            self.logger.warning("Expected JSON object or array, got %s", type(data).__name__)
            return self._empty_result(ts)

        summary = self._compute_summary(findings, ts)

        return ScanResult(
            findings=findings,
            summary=summary,
            raw_json=raw_json_data,
        )

    def _find_json_block(self, text: str) -> Optional[str]:
        """Find the first valid JSON object or array block in text."""
        decoder = json.JSONDecoder()
        # Try array first (flat format), then object (nested format)
        for start_char in ['[', '{']:
            pos = text.find(start_char)
            while pos != -1:
                try:
                    _, end_pos = decoder.raw_decode(text[pos:])
                    return text[pos : pos + end_pos]
                except (json.JSONDecodeError, ValueError):
                    pos = text.find(start_char, pos + 1)
        return None

    # -- Filtering -----------------------------------------------------------

    def filter_by_severity(
        self, result: ScanResult, levels: list[SeverityLevel]
    ) -> ScanResult:
        """Return a new ScanResult containing only findings with the given severity levels."""
        filtered = [f for f in result.findings if f.status in levels]
        summary = self._compute_summary(filtered, result.summary.scan_timestamp)
        return ScanResult(
            findings=filtered,
            summary=summary,
            raw_json=result.raw_json,
            collection_data=result.collection_data,
        )

    def filter_by_category(
        self, result: ScanResult, categories: list[str]
    ) -> ScanResult:
        """Return a new ScanResult containing only findings in the given categories."""
        filtered = [f for f in result.findings if f.category in categories]
        summary = self._compute_summary(filtered, result.summary.scan_timestamp)
        return ScanResult(
            findings=filtered,
            summary=summary,
            raw_json=result.raw_json,
            collection_data=result.collection_data,
        )

    def filter_by_region(
        self, result: ScanResult, regions: list[str]
    ) -> ScanResult:
        """Return a new ScanResult containing only findings in the given regions."""
        filtered = [f for f in result.findings if f.region in regions]
        summary = self._compute_summary(filtered, result.summary.scan_timestamp)
        return ScanResult(
            findings=filtered,
            summary=summary,
            raw_json=result.raw_json,
            collection_data=result.collection_data,
        )

    # -- Persistence ---------------------------------------------------------

    def save_result(self, result: ScanResult, path: str) -> str:
        """Save ScanResult as JSON to filesystem.

        Args:
            result: The ScanResult to persist.
            path: Destination file path.

        Returns:
            The absolute path of the saved file.
        """
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        self.logger.info("Saved scan result to %s", dest)
        return str(dest.resolve())

    def load_result(self, path: str) -> ScanResult:
        """Load a ScanResult from a previously saved JSON file.

        Args:
            path: Path to the JSON file.

        Returns:
            Deserialized ScanResult.
        """
        content = Path(path).read_text(encoding="utf-8")
        return ScanResult.model_validate_json(content)

    # -- Private helpers -----------------------------------------------------

    def _extract_findings(self, data: dict) -> list[ScanFinding]:
        """Walk the CloudSploit nested plugin dict and produce ScanFinding objects.

        Expected format: {pluginId: {title, category, description, results: [{status, region, resource, message}]}}
        """
        findings: list[ScanFinding] = []

        for plugin_id, plugin_data in data.items():
            if not isinstance(plugin_data, dict):
                self.logger.warning(
                    "Skipping non-dict plugin entry: %s", plugin_id
                )
                continue

            title = plugin_data.get("title", plugin_id)
            category = plugin_data.get("category", "Unknown")
            description = plugin_data.get("description", "")
            results = plugin_data.get("results")

            if not isinstance(results, list):
                continue

            for item in results:
                if not isinstance(item, dict):
                    continue

                raw_status = item.get("status", "UNKNOWN")
                status = self._STATUS_MAP.get(
                    raw_status.upper() if isinstance(raw_status, str) else "",
                    SeverityLevel.UNKNOWN,
                )

                findings.append(
                    ScanFinding(
                        plugin=plugin_id,
                        category=category,
                        title=title,
                        description=description,
                        status=status,
                        region=item.get("region", "global"),
                        resource=item.get("resource"),
                        message=item.get("message", ""),
                    )
                )

        return findings

    def _extract_findings_from_array(self, data: list) -> list[ScanFinding]:
        """Parse the flat-array CloudSploit JSON format.

        Expected format: [{plugin, category, title, description, resource, region, status, message, compliance}, ...]
        """
        findings: list[ScanFinding] = []

        for item in data:
            if not isinstance(item, dict):
                self.logger.warning("Skipping non-dict array entry: %s", type(item).__name__)
                continue

            raw_status = item.get("status", "UNKNOWN")
            status = self._STATUS_MAP.get(
                raw_status.upper() if isinstance(raw_status, str) else "",
                SeverityLevel.UNKNOWN,
            )

            findings.append(
                ScanFinding(
                    plugin=item.get("plugin", "unknown"),
                    category=item.get("category", "Unknown"),
                    title=item.get("title", ""),
                    description=item.get("description", ""),
                    status=status,
                    region=item.get("region", "global"),
                    resource=item.get("resource"),
                    message=item.get("message", ""),
                )
            )

        return findings

    def _compute_summary(
        self, findings: list[ScanFinding], timestamp: datetime
    ) -> ScanSummary:
        """Aggregate findings into a ScanSummary."""
        ok = warn = fail = unknown = 0
        categories: dict[str, int] = {}

        for f in findings:
            if f.status == SeverityLevel.OK:
                ok += 1
            elif f.status == SeverityLevel.WARN:
                warn += 1
            elif f.status == SeverityLevel.FAIL:
                fail += 1
            else:
                unknown += 1
            categories[f.category] = categories.get(f.category, 0) + 1

        return ScanSummary(
            total_findings=len(findings),
            ok_count=ok,
            warn_count=warn,
            fail_count=fail,
            unknown_count=unknown,
            categories=categories,
            scan_timestamp=timestamp,
        )

    def _empty_result(
        self, timestamp: datetime, raw_json: Optional[dict] = None
    ) -> ScanResult:
        """Return an empty ScanResult (used for error cases)."""
        return ScanResult(
            findings=[],
            summary=ScanSummary(
                total_findings=0,
                ok_count=0,
                warn_count=0,
                fail_count=0,
                unknown_count=0,
                categories={},
                scan_timestamp=timestamp,
            ),
            raw_json=raw_json,
        )
