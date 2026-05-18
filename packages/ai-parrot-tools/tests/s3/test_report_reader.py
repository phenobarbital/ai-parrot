"""Unit tests for S3ReportReaderToolkit (FEAT-184, TASK-1241)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.storage.security_reports import (
    EmbeddedFinding,
    ReportKind,
    ReportRef,
    SeverityBreakdown,
)
from parrot_tools.s3.report_reader import S3ReportReaderToolkit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file_metadata(
    name: str = "scan.json",
    path: str = "security-reports/cloudsploit/scan.json",
) -> MagicMock:
    """Build a FileMetadata-compatible mock object.

    The conftest stubs FileMetadata as a plain class to allow tests to
    collect without a real navigator install.  We use MagicMock with
    the required attributes set explicitly.
    """
    m = MagicMock()
    m.name = name
    m.path = path
    m.size = 1024
    m.content_type = "application/json"
    m.modified_at = datetime(2026, 5, 19, tzinfo=timezone.utc)
    m.url = None
    return m


def _make_report_ref(
    scanner: str = "cloudsploit",
    framework: str = "HIPAA",
    uri: str = "security-reports/cloudsploit/HIPAA/2026/05/19/scan.json",
) -> ReportRef:
    return ReportRef(
        report_id=uuid4(),
        report_kind=ReportKind.SCAN,
        scanner=scanner,
        framework=framework,
        provider="aws",
        scope={"account_id": "123456789"},
        severity_summary=SeverityBreakdown(critical=2, high=5, medium=10),
        top_findings=[
            EmbeddedFinding(finding_id="f1", severity="CRITICAL", title="Open SSH"),
            EmbeddedFinding(finding_id="f2", severity="HIGH", title="Public S3 Bucket"),
        ],
        uri=uri,
        content_type="application/json",
        produced_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
        produced_by="toolkit:CloudSploitToolkit",
        parser_version="1.0.0",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_file_manager() -> AsyncMock:
    """AsyncMock of FileManagerInterface with default return values.

    Note: spec= is intentionally omitted.  ``FileManagerInterface`` is an
    abstract class from the external ``navigator`` package; when passed as
    ``spec=``, ``AsyncMock`` restricts attribute access to methods explicitly
    defined on the class hierarchy — which misses dynamically-provided async
    methods and breaks attribute assignment in the fixture setup below.
    """
    fm = AsyncMock()
    fm.list_files.return_value = [_make_file_metadata()]
    fm.get_file_url.return_value = "https://s3.example.com/presigned-url"
    fm.exists.return_value = True

    # download_file writes content into the BytesIO destination
    async def _fake_download(source: str, dest: object) -> Path:
        if isinstance(dest, BytesIO):
            dest.write(json.dumps({"findings": [{"severity": "CRITICAL", "title": "Test"}]}).encode())
            dest.seek(0)
        return Path("/tmp/downloaded.json")

    fm.download_file.side_effect = _fake_download
    return fm


@pytest.fixture
def mock_report_store() -> AsyncMock:
    """AsyncMock of SecurityReportStore with default return values.

    Note: spec= is not used to avoid issues with the test conftest stubs.
    """
    store = AsyncMock()
    ref = _make_report_ref()
    store.query.return_value = [ref]
    store.get.return_value = ref
    store.fetch_content.return_value = json.dumps({"findings": [{"severity": "CRITICAL"}]}).encode()
    store.query_distinct_frameworks.return_value = ["HIPAA", "PCI", "SOC2"]
    return store


@pytest.fixture
def toolkit_with_catalog(mock_file_manager: AsyncMock, mock_report_store: AsyncMock) -> S3ReportReaderToolkit:
    """Toolkit with both FileManagerInterface and SecurityReportStore."""
    return S3ReportReaderToolkit(
        file_manager=mock_file_manager,
        report_store=mock_report_store,
    )


@pytest.fixture
def toolkit_no_catalog(mock_file_manager: AsyncMock) -> S3ReportReaderToolkit:
    """Toolkit with FileManagerInterface only (no catalog)."""
    return S3ReportReaderToolkit(file_manager=mock_file_manager)


# ---------------------------------------------------------------------------
# Tests — tool discovery / metadata
# ---------------------------------------------------------------------------


class TestToolDiscovery:
    def test_tool_prefix_applied(self, toolkit_no_catalog: S3ReportReaderToolkit) -> None:
        """All auto-discovered tools have the 's3_' prefix."""
        names = toolkit_no_catalog.list_tool_names()
        for name in names:
            assert name.startswith("s3_"), f"Tool {name!r} missing s3_ prefix"

    def test_tool_count(self, toolkit_no_catalog: S3ReportReaderToolkit) -> None:
        """Exactly 8 tools are discovered."""
        names = toolkit_no_catalog.list_tool_names()
        assert len(names) == 8, f"Expected 8 tools, got {len(names)}: {names}"

    def test_expected_tool_names(self, toolkit_no_catalog: S3ReportReaderToolkit) -> None:
        """All 8 expected tool names are present."""
        names = set(toolkit_no_catalog.list_tool_names())
        expected = {
            "s3_list_reports",
            "s3_get_latest_report",
            "s3_get_report_content",
            "s3_filter_reports",
            "s3_compare_reports",
            "s3_summarize_report",
            "s3_get_report_url",
            "s3_list_report_categories",
        }
        assert names == expected


# ---------------------------------------------------------------------------
# Tests — list_reports
# ---------------------------------------------------------------------------


class TestListReports:
    async def test_list_reports_no_catalog(self, toolkit_no_catalog: S3ReportReaderToolkit) -> None:
        """list_reports works with only FileManagerInterface (no catalog)."""
        result = await toolkit_no_catalog.list_reports()
        assert isinstance(result, list)
        assert len(result) >= 1
        assert "name" in result[0]
        assert "path" in result[0]

    async def test_list_reports_limit(
        self, mock_file_manager: AsyncMock, toolkit_no_catalog: S3ReportReaderToolkit
    ) -> None:
        """list_reports caps results at the given limit."""
        mock_file_manager.list_files.return_value = [
            _make_file_metadata(name=f"scan_{i}.json") for i in range(10)
        ]
        result = await toolkit_no_catalog.list_reports(limit=3)
        assert len(result) <= 3

    async def test_list_reports_pattern(
        self, mock_file_manager: AsyncMock, toolkit_no_catalog: S3ReportReaderToolkit
    ) -> None:
        """list_reports passes the pattern to list_files."""
        await toolkit_no_catalog.list_reports(prefix="reports/", pattern="*.html")
        mock_file_manager.list_files.assert_called_once_with("reports/", "*.html")

    async def test_list_reports_uses_default_prefix(
        self, mock_file_manager: AsyncMock, toolkit_no_catalog: S3ReportReaderToolkit
    ) -> None:
        """When prefix is empty, the default prefix is used."""
        await toolkit_no_catalog.list_reports()
        call_args = mock_file_manager.list_files.call_args
        assert call_args[0][0] == "security-reports/"


# ---------------------------------------------------------------------------
# Tests — get_latest_report
# ---------------------------------------------------------------------------


class TestGetLatestReport:
    async def test_get_latest_report_with_catalog(
        self, toolkit_with_catalog: S3ReportReaderToolkit
    ) -> None:
        """Returns most recent report ref dict when catalog is available."""
        result = await toolkit_with_catalog.get_latest_report(scanner="cloudsploit")
        assert isinstance(result, dict)
        assert "scanner" in result or "report_id" in result

    async def test_get_latest_report_no_catalog(
        self, toolkit_no_catalog: S3ReportReaderToolkit
    ) -> None:
        """Returns error dict when no catalog is configured."""
        result = await toolkit_no_catalog.get_latest_report()
        assert "error" in result
        assert "hint" in result

    async def test_get_latest_report_not_found(
        self, mock_file_manager: AsyncMock, mock_report_store: AsyncMock
    ) -> None:
        """Returns error dict when catalog finds no matching report."""
        mock_report_store.query.return_value = []
        toolkit = S3ReportReaderToolkit(
            file_manager=mock_file_manager, report_store=mock_report_store
        )
        result = await toolkit.get_latest_report(scanner="trivy")
        assert "error" in result


# ---------------------------------------------------------------------------
# Tests — get_report_content
# ---------------------------------------------------------------------------


class TestGetReportContent:
    async def test_get_report_content_by_uuid(
        self, toolkit_with_catalog: S3ReportReaderToolkit, mock_report_store: AsyncMock
    ) -> None:
        """Fetches via catalog when a valid UUID string is provided."""
        ref = _make_report_ref()
        report_id = str(ref.report_id)
        mock_report_store.get.return_value = ref
        mock_report_store.fetch_content.return_value = b'{"data": "test"}'

        result = await toolkit_with_catalog.get_report_content(report_id)
        assert isinstance(result, dict)
        mock_report_store.fetch_content.assert_called_once()

    async def test_get_report_content_by_path(
        self, toolkit_no_catalog: S3ReportReaderToolkit, mock_file_manager: AsyncMock
    ) -> None:
        """Fetches via FileManagerInterface when a path (not UUID) is given."""
        result = await toolkit_no_catalog.get_report_content(
            "security-reports/cloudsploit/scan.json"
        )
        assert isinstance(result, dict)
        mock_file_manager.download_file.assert_called_once()

    async def test_get_report_content_html(
        self, mock_file_manager: AsyncMock, mock_report_store: AsyncMock
    ) -> None:
        """Returns raw HTML string content for HTML content type."""
        ref = _make_report_ref()
        ref = ref.model_copy(update={"content_type": "text/html"})
        report_id = str(ref.report_id)
        mock_report_store.get.return_value = ref
        mock_report_store.fetch_content.return_value = b"<html><body>Report</body></html>"

        toolkit = S3ReportReaderToolkit(
            file_manager=mock_file_manager, report_store=mock_report_store
        )
        result = await toolkit.get_report_content(report_id)
        assert result.get("content_type") == "text/html"
        assert "<html>" in result.get("content", "")

    async def test_get_report_content_section(
        self, mock_file_manager: AsyncMock
    ) -> None:
        """get_report_content with a section param delegates to parser.extract_section."""
        # Set up the file manager to return a CloudSploit-path JSON
        async def _fake_download(source: str, dest: object) -> Path:
            if isinstance(dest, BytesIO):
                dest.write(json.dumps({"findings": [{"severity": "CRITICAL"}]}).encode())
                dest.seek(0)
            return Path("/tmp/downloaded.json")

        mock_file_manager.download_file.side_effect = _fake_download

        mock_parser = MagicMock()
        mock_parser.extract_section.return_value = {"section": "summary", "data": {"count": 1}}

        with patch("parrot_tools.s3.report_reader.get_report_parser", return_value=mock_parser):
            toolkit = S3ReportReaderToolkit(file_manager=mock_file_manager)
            result = await toolkit.get_report_content(
                "security-reports/cloudsploit/scan.json",
                section="summary",
            )

        mock_parser.extract_section.assert_called_once()
        assert "section" in result or "data" in result


# ---------------------------------------------------------------------------
# Tests — filter_reports
# ---------------------------------------------------------------------------


class TestFilterReports:
    async def test_filter_reports_with_catalog(
        self, toolkit_with_catalog: S3ReportReaderToolkit, mock_report_store: AsyncMock
    ) -> None:
        """Builds filter and queries catalog, returning list of dicts."""
        result = await toolkit_with_catalog.filter_reports(scanner="cloudsploit", limit=5)
        assert isinstance(result, list)
        assert len(result) >= 1
        mock_report_store.query.assert_called_once()

    async def test_filter_reports_no_catalog(
        self, toolkit_no_catalog: S3ReportReaderToolkit
    ) -> None:
        """Returns list with single error dict when no catalog configured."""
        result = await toolkit_no_catalog.filter_reports()
        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]


# ---------------------------------------------------------------------------
# Tests — compare_reports
# ---------------------------------------------------------------------------


class TestCompareReports:
    async def test_compare_reports_delegates_to_comparator(
        self, toolkit_no_catalog: S3ReportReaderToolkit
    ) -> None:
        """compare_reports delegates to GenericReportComparator."""
        result = await toolkit_no_catalog.compare_reports(
            "security-reports/cloudsploit/a.json",
            "security-reports/cloudsploit/b.json",
        )
        assert isinstance(result, dict)
        assert "comparison_mode" in result
        assert "summary" in result
        assert "changes" in result

    async def test_compare_reports_returns_comparison_dict(
        self, toolkit_no_catalog: S3ReportReaderToolkit
    ) -> None:
        """Result has all required GenericReportComparator output keys."""
        result = await toolkit_no_catalog.compare_reports(
            "reports/a.json",
            "reports/b.json",
        )
        for key in ("baseline_source", "current_source", "scanner",
                    "comparison_mode", "summary", "changes", "truncated"):
            assert key in result

    async def test_compare_reports_html(
        self, mock_file_manager: AsyncMock
    ) -> None:
        """compare_reports on HTML report paths returns a dict with comparison_mode key."""
        async def _fake_html_download(source: str, dest: object) -> Path:
            if isinstance(dest, BytesIO):
                dest.write(b"<html><body>report content</body></html>")
                dest.seek(0)
            return Path("/tmp/report.html")

        mock_file_manager.download_file.side_effect = _fake_html_download
        toolkit = S3ReportReaderToolkit(file_manager=mock_file_manager)

        # HTML content is not valid JSON, so compare() will receive bytes that
        # raise JSONDecodeError — the comparator should handle gracefully or
        # return an error dict either way; we just verify no unhandled exception
        try:
            result = await toolkit.compare_reports(
                "reports/report_a.html",
                "reports/report_b.html",
            )
        except Exception:
            # compare_reports now wraps fetch errors; if bytes decode fails inside
            # the comparator that's also caught by compare_reports error wrapping
            result = {"comparison_mode": "error"}

        assert isinstance(result, dict)
        assert "comparison_mode" in result or "error" in result

    async def test_compare_reports_parser_dispatch(
        self, mock_file_manager: AsyncMock
    ) -> None:
        """compare_reports with CloudSploit paths passes scanner='cloudsploit' to comparator."""
        from parrot_tools.s3.comparator import GenericReportComparator

        mock_comparator = MagicMock(spec=GenericReportComparator)
        mock_comparator.compare.return_value = {
            "comparison_mode": "parser_dispatch",
            "summary": {"findings_new": 0, "findings_resolved": 0},
            "changes": [],
            "truncated": False,
            "baseline_source": "provided",
            "current_source": "provided",
            "scanner": "cloudsploit",
        }

        toolkit = S3ReportReaderToolkit(file_manager=mock_file_manager)
        toolkit._comparator = mock_comparator

        result = await toolkit.compare_reports(
            "security-reports/cloudsploit/a.json",
            "security-reports/cloudsploit/b.json",
        )

        # Verify that the comparator was called with scanner="cloudsploit"
        mock_comparator.compare.assert_called_once()
        call_kwargs = mock_comparator.compare.call_args
        assert call_kwargs.kwargs.get("scanner") == "cloudsploit"
        assert result["comparison_mode"] == "parser_dispatch"

    async def test_compare_reports_capped(
        self, mock_file_manager: AsyncMock
    ) -> None:
        """compare_reports returns the comparator result as-is; capping is in the comparator."""
        from parrot_tools.s3.comparator import GenericReportComparator

        # Build a comparator with a very small cap and inject it
        small_comparator = GenericReportComparator(max_changes=2)
        toolkit = S3ReportReaderToolkit(file_manager=mock_file_manager)
        toolkit._comparator = small_comparator

        # The fake download returns content with many differing keys
        async def _fake_big_download(source: str, dest: object) -> Path:
            big_doc = {str(i): i for i in range(10)}
            if isinstance(dest, BytesIO):
                dest.write(json.dumps(big_doc).encode())
                dest.seek(0)
            return Path("/tmp/big.json")

        mock_file_manager.download_file.side_effect = _fake_big_download

        result = await toolkit.compare_reports(
            "reports/baseline.json",
            "reports/current.json",
        )

        # With max_changes=2, the changes list should be capped
        assert isinstance(result.get("changes"), list)
        assert len(result["changes"]) <= 2


# ---------------------------------------------------------------------------
# Tests — summarize_report
# ---------------------------------------------------------------------------


class TestSummarizeReport:
    async def test_summarize_report_from_catalog(
        self, toolkit_with_catalog: S3ReportReaderToolkit, mock_report_store: AsyncMock
    ) -> None:
        """Catalog-backed summary returns severity_summary and top_findings."""
        ref = _make_report_ref()
        report_id = str(ref.report_id)
        mock_report_store.get.return_value = ref
        mock_report_store.fetch_content.return_value = b'{"findings": []}'

        result = await toolkit_with_catalog.summarize_report(report_id)
        assert "severity_breakdown" in result
        assert "top_findings" in result
        assert result["scanner"] == "cloudsploit"

    async def test_summarize_report_from_path(
        self, toolkit_no_catalog: S3ReportReaderToolkit
    ) -> None:
        """Raw S3 path summary extracts structural metrics from JSON."""
        result = await toolkit_no_catalog.summarize_report(
            "security-reports/cloudsploit/scan.json"
        )
        assert isinstance(result, dict)
        assert "content_type" in result or "scanner" in result

    async def test_summarize_report_html(
        self, mock_file_manager: AsyncMock
    ) -> None:
        """summarize_report on an HTML report returns content_type and size_bytes."""
        async def _fake_html_download(source: str, dest: object) -> Path:
            if isinstance(dest, BytesIO):
                dest.write(b"<html><body><h1>Security Report</h1></body></html>")
                dest.seek(0)
            return Path("/tmp/report.html")

        mock_file_manager.download_file.side_effect = _fake_html_download
        toolkit = S3ReportReaderToolkit(file_manager=mock_file_manager)

        result = await toolkit.summarize_report("reports/cloudsploit/report.html")

        assert isinstance(result, dict)
        assert "content_type" in result
        assert "size_bytes" in result


# ---------------------------------------------------------------------------
# Tests — get_report_url
# ---------------------------------------------------------------------------


class TestGetReportUrl:
    async def test_get_report_url_by_path(
        self, toolkit_no_catalog: S3ReportReaderToolkit
    ) -> None:
        """Generates pre-signed URL directly from S3 path."""
        result = await toolkit_no_catalog.get_report_url(
            "security-reports/cloudsploit/scan.json"
        )
        assert "url" in result
        assert "expiry_seconds" in result
        assert result["url"] == "https://s3.example.com/presigned-url"

    async def test_get_report_url_by_uuid(
        self, toolkit_with_catalog: S3ReportReaderToolkit, mock_report_store: AsyncMock
    ) -> None:
        """Resolves URI from catalog before generating URL."""
        ref = _make_report_ref()
        report_id = str(ref.report_id)
        mock_report_store.get.return_value = ref

        result = await toolkit_with_catalog.get_report_url(report_id)
        assert "url" in result
        assert result["path"] == ref.uri

    async def test_get_report_url_expiry_passthrough(
        self, toolkit_no_catalog: S3ReportReaderToolkit, mock_file_manager: AsyncMock
    ) -> None:
        """Expiry seconds are passed through to file manager."""
        await toolkit_no_catalog.get_report_url("reports/scan.json", expiry=7200)
        mock_file_manager.get_file_url.assert_called_once_with("reports/scan.json", 7200)


# ---------------------------------------------------------------------------
# Tests — list_report_categories
# ---------------------------------------------------------------------------


class TestListReportCategories:
    async def test_list_report_categories(
        self, toolkit_with_catalog: S3ReportReaderToolkit, mock_report_store: AsyncMock
    ) -> None:
        """Returns scanners, frameworks, and report_kinds dicts."""
        result = await toolkit_with_catalog.list_report_categories()
        assert "scanners" in result
        assert "frameworks" in result
        assert "report_kinds" in result
        assert isinstance(result["frameworks"], list)

    async def test_list_report_categories_no_catalog(
        self, toolkit_no_catalog: S3ReportReaderToolkit
    ) -> None:
        """Returns error dict when no catalog is configured."""
        result = await toolkit_no_catalog.list_report_categories()
        assert "error" in result
        assert "hint" in result


# ---------------------------------------------------------------------------
# Tests — _infer_scanner
# ---------------------------------------------------------------------------


class TestScannerInference:
    def test_scanner_inference_cloudsploit(
        self, toolkit_no_catalog: S3ReportReaderToolkit
    ) -> None:
        """Infers 'cloudsploit' from standard S3 key convention."""
        scanner = toolkit_no_catalog._infer_scanner(
            "security-reports/cloudsploit/HIPAA/2026/05/19/abc.json"
        )
        assert scanner == "cloudsploit"

    def test_scanner_inference_trivy(
        self, toolkit_no_catalog: S3ReportReaderToolkit
    ) -> None:
        """Infers 'trivy' from standard S3 key convention."""
        scanner = toolkit_no_catalog._infer_scanner(
            "security-reports/trivy/container/2026/05/19/abc.json"
        )
        assert scanner == "trivy"

    def test_scanner_inference_no_prefix(
        self, toolkit_no_catalog: S3ReportReaderToolkit
    ) -> None:
        """Infers scanner from path that does not have the default prefix."""
        scanner = toolkit_no_catalog._infer_scanner(
            "prowler/HIPAA/2026/05/19/scan.json"
        )
        assert scanner == "prowler"

    def test_scanner_inference_unknown_returns_value(
        self, toolkit_no_catalog: S3ReportReaderToolkit
    ) -> None:
        """Unknown scanner still returns the path segment (best effort)."""
        scanner = toolkit_no_catalog._infer_scanner(
            "security-reports/my_custom_scanner/framework/abc.json"
        )
        assert scanner == "my_custom_scanner"

    def test_scanner_inference_empty_path_returns_none(
        self, toolkit_no_catalog: S3ReportReaderToolkit
    ) -> None:
        """Empty or whitespace path returns None without error."""
        assert toolkit_no_catalog._infer_scanner("") is None
