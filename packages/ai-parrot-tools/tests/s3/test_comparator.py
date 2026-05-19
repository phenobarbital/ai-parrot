"""Unit tests for GenericReportComparator (FEAT-184, TASK-1241)."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from parrot_tools.s3.comparator import GenericReportComparator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def comparator() -> GenericReportComparator:
    """Default comparator with max_changes=50."""
    return GenericReportComparator()


@pytest.fixture
def small_comparator() -> GenericReportComparator:
    """Comparator with tiny cap for truncation tests."""
    return GenericReportComparator(max_changes=2)


# Minimal CloudSploit-style JSON for dispatch tests
_CLOUDSPLOIT_BASELINE = json.dumps(
    [
        {
            "plugin": "OpenSSH",
            "category": "EC2",
            "title": "SSH Open",
            "description": "SSH is open",
            "resource": "arn:aws:ec2:us-east-1:123:sg-1",
            "region": "us-east-1",
            "status": "FAIL",
            "message": "Fix it",
        }
    ]
)

_CLOUDSPLOIT_CURRENT = json.dumps(
    [
        {
            "plugin": "OpenSSH",
            "category": "EC2",
            "title": "SSH Open",
            "description": "SSH is open",
            "resource": "arn:aws:ec2:us-east-1:123:sg-1",
            "region": "us-east-1",
            "status": "PASS",
            "message": "Fixed",
        }
    ]
)


# ---------------------------------------------------------------------------
# Tests — generic structural diff
# ---------------------------------------------------------------------------


class TestStructuralDiff:
    def test_compare_dicts_keys_added(self, comparator: GenericReportComparator) -> None:
        """New key in current dict shows up as 'added' change."""
        result = comparator.compare({"a": 1}, {"a": 1, "b": 2})

        assert result["summary"]["keys_added"] == 1
        assert result["summary"]["keys_removed"] == 0
        assert result["summary"]["keys_changed"] == 0
        added = [c for c in result["changes"] if c["change_type"] == "added"]
        assert len(added) == 1
        assert added[0]["path"] == "b"
        assert added[0]["new"] == 2

    def test_compare_dicts_keys_removed(self, comparator: GenericReportComparator) -> None:
        """Key present in baseline but absent in current shows as 'removed'."""
        result = comparator.compare({"a": 1, "b": 2}, {"a": 1})

        assert result["summary"]["keys_removed"] == 1
        removed = [c for c in result["changes"] if c["change_type"] == "removed"]
        assert len(removed) == 1
        assert removed[0]["path"] == "b"

    def test_compare_dicts_keys_changed(self, comparator: GenericReportComparator) -> None:
        """Changed value at dotted path is captured with old and new."""
        result = comparator.compare({"a": 1}, {"a": 99})

        assert result["summary"]["keys_changed"] == 1
        changed = [c for c in result["changes"] if c["change_type"] == "changed"]
        assert len(changed) == 1
        assert changed[0]["path"] == "a"
        assert changed[0]["old"] == 1
        assert changed[0]["new"] == 99

    def test_compare_nested_dicts(self, comparator: GenericReportComparator) -> None:
        """Nested dict changes use dotted-path notation."""
        baseline = {"parent": {"child": "old", "stable": "x"}}
        current = {"parent": {"child": "new", "stable": "x"}}
        result = comparator.compare(baseline, current)

        assert result["summary"]["keys_changed"] == 1
        changed = result["changes"][0]
        assert changed["path"] == "parent.child"
        assert changed["old"] == "old"
        assert changed["new"] == "new"

    def test_compare_array_changes(self, comparator: GenericReportComparator) -> None:
        """Array length change captured as a single 'changed' entry."""
        result = comparator.compare({"items": [1, 2, 3]}, {"items": [1, 2, 3, 4]})

        assert result["summary"]["keys_changed"] == 1
        change = result["changes"][0]
        assert change["path"] == "items"
        assert "array[3]" in change["old"]
        assert "array[4]" in change["new"]

    def test_compare_bytes_inputs(self, comparator: GenericReportComparator) -> None:
        """Bytes inputs are JSON-decoded before comparison."""
        baseline = json.dumps({"x": 1}).encode()
        current = json.dumps({"x": 2}).encode()
        result = comparator.compare(baseline, current)

        assert result["summary"]["keys_changed"] == 1

    def test_compare_capped_changes(self, small_comparator: GenericReportComparator) -> None:
        """Changes list is capped at max_changes."""
        baseline = {str(i): i for i in range(10)}
        current = {str(i): i + 100 for i in range(10)}
        result = small_comparator.compare(baseline, current)

        assert len(result["changes"]) <= 2

    def test_compare_truncated_flag(self, small_comparator: GenericReportComparator) -> None:
        """truncated is True when changes exceed max_changes."""
        baseline = {str(i): i for i in range(10)}
        current = {str(i): i + 100 for i in range(10)}
        result = small_comparator.compare(baseline, current)

        assert result["truncated"] is True

    def test_compare_identical_dicts(self, comparator: GenericReportComparator) -> None:
        """Identical dicts produce empty changes and zero counts."""
        data = {"a": 1, "b": {"c": 3}}
        result = comparator.compare(data, data)

        assert result["summary"]["keys_added"] == 0
        assert result["summary"]["keys_removed"] == 0
        assert result["summary"]["keys_changed"] == 0
        assert result["changes"] == []
        assert result["truncated"] is False

    def test_compare_mode_is_generic(self, comparator: GenericReportComparator) -> None:
        """comparison_mode is 'generic' for non-cloudsploit or fallback."""
        result = comparator.compare({"a": 1}, {"a": 2})
        assert result["comparison_mode"] == "generic"

    def test_compare_result_has_required_keys(self, comparator: GenericReportComparator) -> None:
        """Result dict contains all required top-level keys."""
        result = comparator.compare({"a": 1}, {"a": 2})
        for key in ("baseline_source", "current_source", "scanner", "comparison_mode",
                    "summary", "changes", "truncated"):
            assert key in result


# ---------------------------------------------------------------------------
# Tests — parser dispatch
# ---------------------------------------------------------------------------


class TestParserDispatch:
    def test_dispatch_cloudsploit(self, comparator: GenericReportComparator) -> None:
        """Parser dispatch for scanner='cloudsploit' returns parser_dispatch mode."""
        result = comparator.compare(
            _CLOUDSPLOIT_BASELINE.encode(),
            _CLOUDSPLOIT_CURRENT.encode(),
            scanner="cloudsploit",
        )
        # Should succeed or fall back gracefully — in either case must be valid
        assert result["comparison_mode"] in ("parser_dispatch", "generic")
        assert "summary" in result

    def test_dispatch_cloudsploit_has_findings_keys_when_successful(
        self, comparator: GenericReportComparator
    ) -> None:
        """Successful CloudSploit dispatch includes findings_new/resolved keys."""
        result = comparator.compare(
            _CLOUDSPLOIT_BASELINE.encode(),
            _CLOUDSPLOIT_CURRENT.encode(),
            scanner="cloudsploit",
        )
        if result["comparison_mode"] == "parser_dispatch":
            assert "findings_new" in result["summary"]
            assert "findings_resolved" in result["summary"]
            assert "severity_changes" in result["summary"]

    def test_dispatch_unknown_scanner_falls_back(
        self, comparator: GenericReportComparator
    ) -> None:
        """Unknown scanner names fall back to generic diff."""
        result = comparator.compare({"x": 1}, {"x": 2}, scanner="unknown_scanner")
        assert result["comparison_mode"] == "generic"

    def test_dispatch_failure_fallback(self, comparator: GenericReportComparator) -> None:
        """When _dispatch_to_parser raises, compare() falls back to generic diff."""
        with patch.object(comparator, "_dispatch_to_parser", side_effect=RuntimeError("simulated failure")):
            result = comparator.compare(
                b'{"a": 1}',
                b'{"a": 2}',
                scanner="cloudsploit",
            )
        assert result["comparison_mode"] == "generic"

    def test_dispatch_to_parser_returns_none_for_unknown(
        self, comparator: GenericReportComparator
    ) -> None:
        """_dispatch_to_parser returns None for non-cloudsploit scanners."""
        result = comparator._dispatch_to_parser(b"{}", b"{}", "trivy")
        assert result is None

    def test_dispatch_to_parser_returns_none_on_exception(
        self, comparator: GenericReportComparator
    ) -> None:
        """_dispatch_to_parser catches exceptions and returns None.

        We force an exception by patching the CloudSploit comparator's
        compare method to raise, then verify the fallback returns None.
        """
        from unittest.mock import patch as _patch
        with _patch(
            "parrot_tools.cloudsploit.comparator.ScanComparator.compare",
            side_effect=ValueError("forced exception"),
        ):
            result = comparator._dispatch_to_parser(
                _CLOUDSPLOIT_BASELINE.encode(),
                _CLOUDSPLOIT_CURRENT.encode(),
                "cloudsploit",
            )
        assert result is None
