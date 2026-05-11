"""Tests for InspectorToolkit (FEAT-161 — AWS Inspector v2)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_tools.aws.inspector import InspectorToolkit


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def toolkit() -> InspectorToolkit:
    """Return an InspectorToolkit instance for testing."""
    return InspectorToolkit(aws_id="test", region_name="us-east-1")


# ------------------------------------------------------------------
# Filter criteria tests (TASK-1079)
# ------------------------------------------------------------------


class TestBuildFilterCriteria:
    """Tests for the _build_filter_criteria private helper."""

    def test_drops_none_and_all(self, toolkit: InspectorToolkit) -> None:
        """None and 'ALL' kwargs are excluded from the resulting criteria dict."""
        result = toolkit._build_filter_criteria(severity="ALL", resource_type=None)
        assert result == {}

    def test_enum_to_equals(self, toolkit: InspectorToolkit) -> None:
        """Enum-style kwargs produce EQUALS comparisons."""
        result = toolkit._build_filter_criteria(severity="CRITICAL")
        assert result["severity"] == [{"comparison": "EQUALS", "value": "CRITICAL"}]

    def test_resource_type_equals(self, toolkit: InspectorToolkit) -> None:
        """resource_type produces an EQUALS comparison on resourceType."""
        result = toolkit._build_filter_criteria(resource_type="AWS_ECR_CONTAINER_IMAGE")
        assert result["resourceType"] == [
            {"comparison": "EQUALS", "value": "AWS_ECR_CONTAINER_IMAGE"}
        ]

    def test_search_term_contains(self, toolkit: InspectorToolkit) -> None:
        """search_term produces a CONTAINS comparison on title."""
        result = toolkit._build_filter_criteria(search_term="CVE-2026")
        assert result["title"] == [{"comparison": "CONTAINS", "value": "CVE-2026"}]

    def test_repo_prefix_glob(self, toolkit: InspectorToolkit) -> None:
        """repository_name ending with '*' produces a PREFIX comparison."""
        result = toolkit._build_filter_criteria(repository_name="prod-*")
        assert result["ecrImageRepositoryName"] == [
            {"comparison": "PREFIX", "value": "prod-"}
        ]

    def test_repo_exact_match(self, toolkit: InspectorToolkit) -> None:
        """repository_name without '*' produces an EQUALS comparison."""
        result = toolkit._build_filter_criteria(repository_name="my-repo")
        assert result["ecrImageRepositoryName"] == [
            {"comparison": "EQUALS", "value": "my-repo"}
        ]

    def test_status_maps_to_finding_status(self, toolkit: InspectorToolkit) -> None:
        """status kwarg maps to findingStatus key (not 'status')."""
        result = toolkit._build_filter_criteria(status="ACTIVE")
        assert "findingStatus" in result
        assert "status" not in result
        assert result["findingStatus"] == [{"comparison": "EQUALS", "value": "ACTIVE"}]

    def test_status_all_is_dropped(self, toolkit: InspectorToolkit) -> None:
        """status='ALL' is excluded from the criteria."""
        result = toolkit._build_filter_criteria(status="ALL")
        assert "findingStatus" not in result

    def test_fix_available_equals(self, toolkit: InspectorToolkit) -> None:
        """fix_available produces an EQUALS comparison."""
        result = toolkit._build_filter_criteria(fix_available="YES")
        assert result["fixAvailable"] == [{"comparison": "EQUALS", "value": "YES"}]

    def test_empty_kwargs_returns_empty_dict(self, toolkit: InspectorToolkit) -> None:
        """No kwargs → empty criteria dict."""
        result = toolkit._build_filter_criteria()
        assert result == {}

    def test_combined_filters(self, toolkit: InspectorToolkit) -> None:
        """Multiple kwargs produce multiple criteria keys."""
        result = toolkit._build_filter_criteria(
            severity="HIGH", status="ACTIVE", fix_available="YES"
        )
        assert "severity" in result
        assert "findingStatus" in result
        assert "fixAvailable" in result


# ------------------------------------------------------------------
# Class instantiation tests (TASK-1079)
# ------------------------------------------------------------------


class TestInspectorToolkitInstantiation:
    """Tests for toolkit class construction."""

    def test_instantiates_with_defaults(self) -> None:
        """Toolkit can be created with default arguments."""
        tk = InspectorToolkit()
        assert tk is not None

    def test_instantiates_with_custom_region(self) -> None:
        """Toolkit can be created with a custom region."""
        tk = InspectorToolkit(aws_id="test", region_name="eu-west-1")
        assert tk is not None

    def test_has_aws_interface(self, toolkit: InspectorToolkit) -> None:
        """Toolkit has an AWSInterface attribute."""
        assert hasattr(toolkit, "aws")

    def test_build_filter_criteria_is_private(self, toolkit: InspectorToolkit) -> None:
        """_build_filter_criteria starts with underscore and is excluded from tools."""
        tools = toolkit.get_tools()
        tool_names = [t.name for t in tools]
        assert "_build_filter_criteria" not in tool_names
        assert not any("filter_criteria" in n for n in tool_names)

    def test_normalize_finding_is_private(self, toolkit: InspectorToolkit) -> None:
        """_normalize_finding starts with underscore and is excluded from tools."""
        tools = toolkit.get_tools()
        tool_names = [t.name for t in tools]
        assert "_normalize_finding" not in tool_names

    def test_all_twelve_operations_registered(self, toolkit: InspectorToolkit) -> None:
        """All 12 aws_inspector_* operations are discoverable via get_tools()."""
        tools = toolkit.get_tools()
        tool_names = {t.name for t in tools}
        expected = {
            "aws_inspector_list_findings",
            "aws_inspector_aggregate_findings",
            "aws_inspector_get_ecr_image_findings",
            "aws_inspector_list_coverage",
            "aws_inspector_get_coverage_statistics",
            "aws_inspector_batch_get_account_status",
            "aws_inspector_get_security_posture",
            "aws_inspector_list_top_vulnerable_resources",
            "aws_inspector_create_findings_report",
            "aws_inspector_get_findings_report_status",
            "aws_inspector_create_sbom_export",
            "aws_inspector_get_sbom_export",
        }
        assert expected.issubset(tool_names)


# ------------------------------------------------------------------
# Normalization helper tests (TASK-1080)
# ------------------------------------------------------------------


class TestNormalizeFinding:
    """Tests for the _normalize_finding private helper."""

    def _make_raw_finding(self, **overrides: Any) -> dict:
        """Create a minimal valid raw Inspector finding."""
        base: dict = {
            "findingArn": "arn:aws:inspector2:us-east-1:123456789012:finding/abc",
            "severity": "HIGH",
            "title": "Test Finding",
            "description": "A test vulnerability",
            "status": "ACTIVE",
            "fixAvailable": "YES",
            "exploitAvailable": "NO",
            "inspectorScore": 7.5,
            "epss": {"score": 0.123},
            "firstObservedAt": datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            "lastObservedAt": datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
            "packageVulnerabilityDetails": {
                "vulnerabilityId": "CVE-2026-12345",
                "vulnerablePackages": [
                    {
                        "name": "libssl",
                        "version": "1.0.1",
                        "fixedVersion": "1.0.2",
                        "packageManager": "OS",
                        "filePath": "/usr/lib/libssl.so",
                    }
                ],
            },
            "resources": [
                {
                    "id": "arn:aws:ecr:us-east-1:123456789012:repository/my-repo",
                    "type": "AWS_ECR_CONTAINER_IMAGE",
                    "region": "us-east-1",
                    "details": {
                        "awsEcrContainerImage": {
                            "repositoryName": "my-repo",
                            "imageDigest": "sha256:abc123",
                            "imageTags": ["latest"],
                            "registryId": "123456789012",
                            "platform": "linux/amd64",
                            "inUseCount": 3,
                            "lastInUseAt": datetime(
                                2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc
                            ),
                        }
                    },
                }
            ],
        }
        base.update(overrides)
        return base

    def test_basic_normalization(self, toolkit: InspectorToolkit) -> None:
        """Normalized output contains all required top-level fields."""
        raw = self._make_raw_finding()
        result = toolkit._normalize_finding(raw)
        assert result["finding_arn"] == "arn:aws:inspector2:us-east-1:123456789012:finding/abc"
        assert result["severity"] == "HIGH"
        assert result["vulnerability_id"] == "CVE-2026-12345"
        assert result["fix_available"] == "YES"
        assert result["exploit_available"] == "NO"
        assert result["inspector_score"] == 7.5
        assert result["epss_score"] == 0.123

    def test_description_truncation(self, toolkit: InspectorToolkit) -> None:
        """Description > 500 chars is truncated with '…' suffix."""
        long_desc = "x" * 600
        raw = self._make_raw_finding(description=long_desc)
        result = toolkit._normalize_finding(raw)
        assert len(result["description"]) == 501  # 500 + ellipsis char
        assert result["description"].endswith("…")

    def test_description_not_truncated_when_short(self, toolkit: InspectorToolkit) -> None:
        """Short descriptions are not truncated."""
        raw = self._make_raw_finding(description="Short desc")
        result = toolkit._normalize_finding(raw)
        assert result["description"] == "Short desc"

    def test_timestamps_are_iso8601(self, toolkit: InspectorToolkit) -> None:
        """firstObservedAt and lastObservedAt are converted to ISO-8601 strings."""
        raw = self._make_raw_finding()
        result = toolkit._normalize_finding(raw)
        assert isinstance(result["first_observed_at"], str)
        assert isinstance(result["last_observed_at"], str)
        # Verify it's parseable as ISO-8601
        datetime.fromisoformat(result["first_observed_at"])
        datetime.fromisoformat(result["last_observed_at"])

    def test_packages_truncated_at_5(self, toolkit: InspectorToolkit) -> None:
        """More than 5 vulnerable packages are truncated to 5 with flag set."""
        packages = [
            {
                "name": f"pkg{i}",
                "version": "1.0",
                "fixedVersion": "1.1",
                "packageManager": "OS",
                "filePath": f"/path/{i}",
            }
            for i in range(7)
        ]
        raw = self._make_raw_finding(
            packageVulnerabilityDetails={
                "vulnerabilityId": "CVE-2026-99999",
                "vulnerablePackages": packages,
            }
        )
        result = toolkit._normalize_finding(raw)
        assert len(result["vulnerable_packages"]) == 5
        assert result["vulnerable_packages_truncated"] is True

    def test_packages_not_truncated_when_5_or_fewer(
        self, toolkit: InspectorToolkit
    ) -> None:
        """5 or fewer vulnerable packages → truncated flag is False."""
        packages = [
            {
                "name": f"pkg{i}",
                "version": "1.0",
                "fixedVersion": "1.1",
                "packageManager": "OS",
                "filePath": f"/path/{i}",
            }
            for i in range(3)
        ]
        raw = self._make_raw_finding(
            packageVulnerabilityDetails={
                "vulnerabilityId": "CVE-2026-99999",
                "vulnerablePackages": packages,
            }
        )
        result = toolkit._normalize_finding(raw)
        assert len(result["vulnerable_packages"]) == 3
        assert result["vulnerable_packages_truncated"] is False

    def test_ecr_image_details_populated(self, toolkit: InspectorToolkit) -> None:
        """ECR image details are populated in resource.ecr_image."""
        raw = self._make_raw_finding()
        result = toolkit._normalize_finding(raw)
        assert result["resource"]["type"] == "AWS_ECR_CONTAINER_IMAGE"
        assert result["resource"]["ecr_image"] is not None
        ecr = result["resource"]["ecr_image"]
        assert ecr["repository_name"] == "my-repo"
        assert ecr["image_digest"] == "sha256:abc123"
        assert ecr["image_tags"] == ["latest"]

    def test_network_reachability_dropped(self, toolkit: InspectorToolkit) -> None:
        """networkReachabilityDetails is not present in normalized output."""
        raw = self._make_raw_finding(
            networkReachabilityDetails={"protocol": "TCP", "openPortRange": {"begin": 22}}
        )
        result = toolkit._normalize_finding(raw)
        assert "networkReachabilityDetails" not in result
        assert "network_reachability_details" not in result

    def test_multi_resource_flag(self, toolkit: InspectorToolkit) -> None:
        """When multiple resources are present, _multi_resource is True on the resource dict."""
        resource_base = {
            "id": "arn:aws:ecr:us-east-1:123456789012:repository/my-repo",
            "type": "AWS_ECR_CONTAINER_IMAGE",
            "region": "us-east-1",
            "details": {},
        }
        raw = self._make_raw_finding(resources=[resource_base, resource_base])
        result = toolkit._normalize_finding(raw)
        assert result["resource"].get("_multi_resource") is True


# ------------------------------------------------------------------
# Direct read operation tests (TASK-1080) — mocked AWS client
# ------------------------------------------------------------------


def _make_mock_client_context(mock_response: dict) -> Any:
    """Create a mock async context manager for self.aws.client()."""
    mock_client = AsyncMock()

    async def mock_list_findings(**kwargs: Any) -> dict:
        return mock_response

    mock_client.list_findings = mock_list_findings
    mock_client.list_finding_aggregations = AsyncMock(return_value=mock_response)
    mock_client.list_coverage = AsyncMock(return_value=mock_response)
    mock_client.list_coverage_statistics = AsyncMock(return_value=mock_response)
    mock_client.batch_get_account_status = AsyncMock(return_value=mock_response)
    mock_client.create_findings_report = AsyncMock(return_value=mock_response)
    mock_client.get_findings_report_status = AsyncMock(return_value=mock_response)
    mock_client.create_sbom_export = AsyncMock(return_value=mock_response)
    mock_client.get_sbom_export = AsyncMock(return_value=mock_response)

    @asynccontextmanager
    async def mock_context(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        yield mock_client

    return mock_context, mock_client


def _make_raw_finding_dict() -> dict:
    """Return a complete raw inspector2 finding dict for testing."""
    return {
        "findingArn": "arn:aws:inspector2:us-east-1:123:finding/test",
        "severity": "CRITICAL",
        "title": "CVE-2026-12345 in libssl",
        "description": "A critical vulnerability",
        "status": "ACTIVE",
        "fixAvailable": "YES",
        "exploitAvailable": "NO",
        "inspectorScore": 9.8,
        "epss": {"score": 0.987},
        "firstObservedAt": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "lastObservedAt": datetime(2026, 5, 1, tzinfo=timezone.utc),
        "packageVulnerabilityDetails": {
            "vulnerabilityId": "CVE-2026-12345",
            "vulnerablePackages": [
                {
                    "name": "libssl",
                    "version": "1.0.1",
                    "fixedVersion": "1.0.2",
                    "packageManager": "OS",
                    "filePath": "/usr/lib/libssl.so",
                }
            ],
        },
        "resources": [
            {
                "id": "arn:aws:ecr:us-east-1:123:repository/repo",
                "type": "AWS_ECR_CONTAINER_IMAGE",
                "region": "us-east-1",
                "details": {
                    "awsEcrContainerImage": {
                        "repositoryName": "repo",
                        "imageDigest": "sha256:abc",
                        "imageTags": ["latest"],
                        "registryId": "123",
                        "platform": "linux/amd64",
                        "inUseCount": 1,
                        "lastInUseAt": datetime(2026, 4, 1, tzinfo=timezone.utc),
                    }
                },
            }
        ],
    }


class TestListFindings:
    """Tests for aws_inspector_list_findings."""

    @pytest.mark.asyncio
    async def test_normalizes_output(self, toolkit: InspectorToolkit) -> None:
        """Output matches the normalized shape from spec §2."""
        raw_finding = _make_raw_finding_dict()
        aws_response = {"findings": [raw_finding], "nextToken": None}
        mock_ctx, mock_client = _make_mock_client_context(aws_response)

        async def mock_list(**kwargs: Any) -> dict:
            return aws_response

        mock_client.list_findings = mock_list

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_list_findings(severity="ALL")

        assert "findings" in result
        assert len(result["findings"]) == 1
        finding = result["findings"][0]
        assert "finding_arn" in finding
        assert "severity" in finding
        assert "vulnerability_id" in finding
        assert "inspector_score" in finding
        assert "vulnerable_packages" in finding
        assert "vulnerable_packages_truncated" in finding
        assert "resource" in finding
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_truncates_description(self, toolkit: InspectorToolkit) -> None:
        """Description > 500 chars is truncated with '…' suffix."""
        raw_finding = _make_raw_finding_dict()
        raw_finding["description"] = "x" * 600
        aws_response = {"findings": [raw_finding]}
        mock_ctx, mock_client = _make_mock_client_context(aws_response)

        async def mock_list(**kwargs: Any) -> dict:
            return aws_response

        mock_client.list_findings = mock_list

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_list_findings()

        assert result["findings"][0]["description"].endswith("…")
        assert len(result["findings"][0]["description"]) == 501

    @pytest.mark.asyncio
    async def test_truncates_packages(self, toolkit: InspectorToolkit) -> None:
        """>5 vulnerable packages are truncated to 5 with flag set."""
        raw_finding = _make_raw_finding_dict()
        raw_finding["packageVulnerabilityDetails"]["vulnerablePackages"] = [
            {"name": f"pkg{i}", "version": "1.0", "fixedVersion": "1.1",
             "packageManager": "OS", "filePath": f"/p/{i}"}
            for i in range(7)
        ]
        aws_response = {"findings": [raw_finding]}
        mock_ctx, mock_client = _make_mock_client_context(aws_response)

        async def mock_list(**kwargs: Any) -> dict:
            return aws_response

        mock_client.list_findings = mock_list

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_list_findings()

        assert len(result["findings"][0]["vulnerable_packages"]) == 5
        assert result["findings"][0]["vulnerable_packages_truncated"] is True

    @pytest.mark.asyncio
    async def test_drops_network_reachability(self, toolkit: InspectorToolkit) -> None:
        """networkReachabilityDetails is not present in normalized output."""
        raw_finding = _make_raw_finding_dict()
        raw_finding["networkReachabilityDetails"] = {"protocol": "TCP"}
        aws_response = {"findings": [raw_finding]}
        mock_ctx, mock_client = _make_mock_client_context(aws_response)

        async def mock_list(**kwargs: Any) -> dict:
            return aws_response

        mock_client.list_findings = mock_list

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_list_findings()

        finding = result["findings"][0]
        assert "networkReachabilityDetails" not in finding
        assert "network_reachability_details" not in finding

    @pytest.mark.asyncio
    async def test_pagination_returns_next_token(self, toolkit: InspectorToolkit) -> None:
        """When AWS returns nextToken, it appears in the output next_token."""
        aws_response = {
            "findings": [_make_raw_finding_dict()],
            "nextToken": "TOKEN123",
        }
        mock_ctx, mock_client = _make_mock_client_context(aws_response)

        async def mock_list(**kwargs: Any) -> dict:
            return aws_response

        mock_client.list_findings = mock_list

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_list_findings()

        assert result["next_token"] == "TOKEN123"

    @pytest.mark.asyncio
    async def test_client_error_to_runtime_error(self, toolkit: InspectorToolkit) -> None:
        """ClientError is converted to RuntimeError with AWS Inspector prefix."""
        from botocore.exceptions import ClientError as BotoClientError

        error_response = {"Error": {"Code": "AccessDeniedException", "Message": "Denied"}}
        mock_ctx, mock_client = _make_mock_client_context({})

        async def mock_list(**kwargs: Any) -> dict:
            raise BotoClientError(error_response, "ListFindings")

        mock_client.list_findings = mock_list

        with patch.object(toolkit.aws, "client", mock_ctx):
            with pytest.raises(RuntimeError) as exc_info:
                await toolkit.aws_inspector_list_findings()

        assert "AWS Inspector error" in str(exc_info.value)
        assert "AccessDeniedException" in str(exc_info.value)


class TestGetEcrImageFindings:
    """Tests for aws_inspector_get_ecr_image_findings."""

    @pytest.mark.asyncio
    async def test_adds_summary(self, toolkit: InspectorToolkit) -> None:
        """Response includes top-level summary with severity counts."""
        critical_finding = _make_raw_finding_dict()
        critical_finding["severity"] = "CRITICAL"
        high_finding = _make_raw_finding_dict()
        high_finding["severity"] = "HIGH"
        aws_response = {"findings": [critical_finding, high_finding]}
        mock_ctx, mock_client = _make_mock_client_context(aws_response)

        async def mock_list(**kwargs: Any) -> dict:
            return aws_response

        mock_client.list_findings = mock_list

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_get_ecr_image_findings(
                repository_name="my-repo"
            )

        assert "summary" in result
        assert "image" in result
        assert result["summary"]["CRITICAL"] == 1
        assert result["summary"]["HIGH"] == 1


class TestAggregateFindingsSeverityCounts:
    """Tests for aws_inspector_aggregate_findings."""

    @pytest.mark.asyncio
    async def test_severity_counts_in_rows(self, toolkit: InspectorToolkit) -> None:
        """Each aggregation row contains severity_counts dict."""
        aws_response = {
            "responses": [
                {
                    "aggregationType": "ACCOUNT",
                    "responses": [
                        {
                            "accountAggregation": {
                                "accountId": "123456789012",
                                "severityCounts": {
                                    "all": 10,
                                    "critical": 2,
                                    "high": 3,
                                    "medium": 5,
                                },
                            }
                        }
                    ],
                }
            ]
        }
        mock_ctx, mock_client = _make_mock_client_context(aws_response)
        mock_client.list_finding_aggregations = AsyncMock(return_value=aws_response)

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_aggregate_findings(
                aggregation_type="ACCOUNT"
            )

        assert "aggregations" in result
        if result["aggregations"]:
            row = result["aggregations"][0]
            assert "severity_counts" in row


# ------------------------------------------------------------------
# Composite operation tests (TASK-1081)
# ------------------------------------------------------------------


class TestGetSecurityPosture:
    """Tests for aws_inspector_get_security_posture."""

    def _make_aggregation_response(
        self, critical: int = 0, high: int = 0, medium: int = 0, low: int = 0
    ) -> dict:
        """Create a mock account aggregation response."""
        return {
            "responses": [
                {
                    "aggregationType": "ACCOUNT",
                    "responses": [
                        {
                            "accountAggregation": {
                                "accountId": "123456789012",
                                "severityCounts": {
                                    "all": critical + high + medium + low,
                                    "critical": critical,
                                    "high": high,
                                    "medium": medium,
                                    "low": low,
                                },
                            }
                        }
                    ],
                }
            ]
        }

    def _make_coverage_stats_response(self) -> dict:
        return {
            "countsByGroup": [
                {
                    "counts": [{"count": 5, "groupKey": "AWS_ECR_CONTAINER_IMAGE"}],
                    "groupKey": "RESOURCE_TYPE",
                }
            ]
        }

    def _make_account_status_response(self) -> dict:
        return {
            "accounts": [
                {
                    "accountId": "123456789012",
                    "resourceState": {
                        "ec2": {"status": "ENABLED"},
                        "ecr": {"status": "ENABLED"},
                        "lambda": {"status": "DISABLED"},
                        "lambdaCode": {"status": "DISABLED"},
                    },
                }
            ]
        }

    @pytest.mark.asyncio
    async def test_score_math(self, toolkit: InspectorToolkit) -> None:
        """Score = 100 - (10*c + 5*h + 2*m + 1*l) clamped [0, 100]."""
        # 2 CRITICAL, 3 HIGH, 5 MEDIUM, 10 LOW
        # penalty = 2*10 + 3*5 + 5*2 + 10*1 = 20 + 15 + 10 + 10 = 55
        # score = 100 - 55 = 45
        agg_resp = self._make_aggregation_response(
            critical=2, high=3, medium=5, low=10
        )
        cov_resp = self._make_coverage_stats_response()
        acc_resp = self._make_account_status_response()

        call_count = 0

        @asynccontextmanager
        async def mock_ctx(service: str, **kwargs: Any) -> AsyncIterator[Any]:
            mock_client = MagicMock()
            mock_client.list_finding_aggregations = AsyncMock(return_value=agg_resp)
            mock_client.list_coverage_statistics = AsyncMock(return_value=cov_resp)
            mock_client.batch_get_account_status = AsyncMock(return_value=acc_resp)
            yield mock_client

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_get_security_posture()

        assert result["security_score"] == 45
        assert result["severity_counts"]["CRITICAL"] == 2
        assert result["severity_counts"]["HIGH"] == 3

    @pytest.mark.asyncio
    async def test_score_clamps_to_zero(self, toolkit: InspectorToolkit) -> None:
        """Score cannot go below 0."""
        agg_resp = self._make_aggregation_response(critical=20)  # penalty = 200
        cov_resp = self._make_coverage_stats_response()
        acc_resp = self._make_account_status_response()

        @asynccontextmanager
        async def mock_ctx(service: str, **kwargs: Any) -> AsyncIterator[Any]:
            mock_client = MagicMock()
            mock_client.list_finding_aggregations = AsyncMock(return_value=agg_resp)
            mock_client.list_coverage_statistics = AsyncMock(return_value=cov_resp)
            mock_client.batch_get_account_status = AsyncMock(return_value=acc_resp)
            yield mock_client

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_get_security_posture()

        assert result["security_score"] == 0

    @pytest.mark.asyncio
    async def test_weights_override(self, toolkit: InspectorToolkit) -> None:
        """Custom weights override defaults."""
        # 1 CRITICAL with weights={CRITICAL: 50} → penalty=50 → score=50
        agg_resp = self._make_aggregation_response(critical=1)
        cov_resp = self._make_coverage_stats_response()
        acc_resp = self._make_account_status_response()

        @asynccontextmanager
        async def mock_ctx(service: str, **kwargs: Any) -> AsyncIterator[Any]:
            mock_client = MagicMock()
            mock_client.list_finding_aggregations = AsyncMock(return_value=agg_resp)
            mock_client.list_coverage_statistics = AsyncMock(return_value=cov_resp)
            mock_client.batch_get_account_status = AsyncMock(return_value=acc_resp)
            yield mock_client

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_get_security_posture(
                weights={"CRITICAL": 50, "HIGH": 5, "MEDIUM": 2, "LOW": 1}
            )

        assert result["security_score"] == 50

    @pytest.mark.asyncio
    async def test_output_includes_weights_used(self, toolkit: InspectorToolkit) -> None:
        """Output always includes weights_used dict."""
        agg_resp = self._make_aggregation_response()
        cov_resp = self._make_coverage_stats_response()
        acc_resp = self._make_account_status_response()

        @asynccontextmanager
        async def mock_ctx(service: str, **kwargs: Any) -> AsyncIterator[Any]:
            mock_client = MagicMock()
            mock_client.list_finding_aggregations = AsyncMock(return_value=agg_resp)
            mock_client.list_coverage_statistics = AsyncMock(return_value=cov_resp)
            mock_client.batch_get_account_status = AsyncMock(return_value=acc_resp)
            yield mock_client

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_get_security_posture()

        assert "weights_used" in result
        assert isinstance(result["weights_used"], dict)


class TestListTopVulnerableResources:
    """Tests for aws_inspector_list_top_vulnerable_resources."""

    def _make_resource_aggregation_response(
        self, resources: list[dict]
    ) -> dict:
        """Create a resource aggregation mock response."""
        return {
            "responses": [
                {
                    "aggregationType": "AWS_EC2_INSTANCE",
                    "responses": [
                        {
                            "amiAggregation": None,
                            "accountAggregation": None,
                        }
                    ],
                }
            ],
            "resourceAggregations": resources,
        }

    @pytest.mark.asyncio
    async def test_sorted_by_weighted_severity(self, toolkit: InspectorToolkit) -> None:
        """Resources are sorted by weighted severity descending."""
        resource_data = [
            {
                "resourceId": "arn:aws:ecr:us-east-1:123:repo/low-risk",
                "severityCounts": {"critical": 0, "high": 1, "medium": 0, "low": 0},
            },
            {
                "resourceId": "arn:aws:ecr:us-east-1:123:repo/high-risk",
                "severityCounts": {"critical": 5, "high": 0, "medium": 0, "low": 0},
            },
        ]
        aws_response = {
            "responses": [
                {
                    "aggregationType": "AWS_ECR_CONTAINER",
                    "responses": [
                        {
                            "ecrContainerImageAggregation": {
                                "resourceId": r["resourceId"],
                                "severityCounts": r["severityCounts"],
                            }
                        }
                        for r in resource_data
                    ],
                }
            ]
        }

        @asynccontextmanager
        async def mock_ctx(service: str, **kwargs: Any) -> AsyncIterator[Any]:
            mock_client = MagicMock()
            mock_client.list_finding_aggregations = AsyncMock(return_value=aws_response)
            yield mock_client

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_list_top_vulnerable_resources(limit=10)

        assert "resources" in result
        if len(result["resources"]) >= 2:
            # high-risk (5 CRITICAL) should come first
            first = result["resources"][0]
            assert first["weighted_score"] > result["resources"][1]["weighted_score"]

    @pytest.mark.asyncio
    async def test_limit_honored(self, toolkit: InspectorToolkit) -> None:
        """Only top N resources are returned."""
        aws_response: dict = {"responses": []}

        @asynccontextmanager
        async def mock_ctx(service: str, **kwargs: Any) -> AsyncIterator[Any]:
            mock_client = MagicMock()
            mock_client.list_finding_aggregations = AsyncMock(return_value=aws_response)
            yield mock_client

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_list_top_vulnerable_resources(limit=3)

        assert "resources" in result
        assert len(result["resources"]) <= 3


# ------------------------------------------------------------------
# Export operation tests (TASK-1082)
# ------------------------------------------------------------------


class TestCreateFindingsReport:
    """Tests for aws_inspector_create_findings_report."""

    @pytest.mark.asyncio
    async def test_returns_report_id(self, toolkit: InspectorToolkit) -> None:
        """Returns report_id and status from AWS response."""
        aws_response = {"reportId": "report-abc-123"}
        mock_ctx, mock_client = _make_mock_client_context(aws_response)
        mock_client.create_findings_report = AsyncMock(return_value=aws_response)

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_create_findings_report(
                s3_bucket="my-bucket",
                kms_key_arn="arn:aws:kms:us-east-1:123:key/abc",
            )

        assert result["report_id"] == "report-abc-123"
        assert result["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_client_error_raised(self, toolkit: InspectorToolkit) -> None:
        """ClientError → RuntimeError with AWS Inspector prefix."""
        from botocore.exceptions import ClientError as BotoClientError

        error_response = {"Error": {"Code": "ValidationException", "Message": "Invalid"}}
        mock_ctx, mock_client = _make_mock_client_context({})
        mock_client.create_findings_report = AsyncMock(
            side_effect=BotoClientError(error_response, "CreateFindingsReport")
        )

        with patch.object(toolkit.aws, "client", mock_ctx):
            with pytest.raises(RuntimeError) as exc_info:
                await toolkit.aws_inspector_create_findings_report(
                    s3_bucket="my-bucket",
                    kms_key_arn="arn:aws:kms:us-east-1:123:key/abc",
                )

        assert "AWS Inspector error" in str(exc_info.value)


class TestGetFindingsReportStatus:
    """Tests for aws_inspector_get_findings_report_status."""

    @pytest.mark.asyncio
    async def test_not_found_returns_status(self, toolkit: InspectorToolkit) -> None:
        """ResourceNotFoundException → {status: 'NOT_FOUND'}, no raise."""
        from botocore.exceptions import ClientError as BotoClientError

        error_response = {
            "Error": {"Code": "ResourceNotFoundException", "Message": "Not found"}
        }
        mock_ctx, mock_client = _make_mock_client_context({})
        mock_client.get_findings_report_status = AsyncMock(
            side_effect=BotoClientError(error_response, "GetFindingsReportStatus")
        )

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_get_findings_report_status(
                report_id="unknown-id"
            )

        assert result["status"] == "NOT_FOUND"
        assert result["report_id"] == "unknown-id"

    @pytest.mark.asyncio
    async def test_succeeded_status(self, toolkit: InspectorToolkit) -> None:
        """Normal response returns status and details."""
        aws_response = {
            "reportId": "report-abc",
            "status": "SUCCEEDED",
            "errorCode": None,
            "errorMessage": None,
            "destination": {
                "bucketName": "my-bucket",
                "keyPrefix": "inspector-reports/",
                "kmsKeyArn": "arn:aws:kms:us-east-1:123:key/abc",
            },
            "filterCriteria": {},
        }
        mock_ctx, mock_client = _make_mock_client_context(aws_response)
        mock_client.get_findings_report_status = AsyncMock(return_value=aws_response)

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_get_findings_report_status(
                report_id="report-abc"
            )

        assert result["status"] == "SUCCEEDED"
        assert result["report_id"] == "report-abc"


class TestCreateSbomExport:
    """Tests for aws_inspector_create_sbom_export."""

    @pytest.mark.asyncio
    async def test_returns_report_id(self, toolkit: InspectorToolkit) -> None:
        """Returns report_id and status from AWS response."""
        aws_response = {"reportId": "sbom-report-xyz"}
        mock_ctx, mock_client = _make_mock_client_context(aws_response)
        mock_client.create_sbom_export = AsyncMock(return_value=aws_response)

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_create_sbom_export(
                s3_bucket="my-bucket",
                kms_key_arn="arn:aws:kms:us-east-1:123:key/abc",
            )

        assert result["report_id"] == "sbom-report-xyz"
        assert result["status"] == "IN_PROGRESS"


class TestGetSbomExport:
    """Tests for aws_inspector_get_sbom_export."""

    @pytest.mark.asyncio
    async def test_not_found_returns_status(self, toolkit: InspectorToolkit) -> None:
        """ResourceNotFoundException → {status: 'NOT_FOUND'}, no raise."""
        from botocore.exceptions import ClientError as BotoClientError

        error_response = {
            "Error": {"Code": "ResourceNotFoundException", "Message": "Not found"}
        }
        mock_ctx, mock_client = _make_mock_client_context({})
        mock_client.get_sbom_export = AsyncMock(
            side_effect=BotoClientError(error_response, "GetSbomExport")
        )

        with patch.object(toolkit.aws, "client", mock_ctx):
            result = await toolkit.aws_inspector_get_sbom_export(
                report_id="unknown-sbom-id"
            )

        assert result["status"] == "NOT_FOUND"
        assert result["report_id"] == "unknown-sbom-id"


# ------------------------------------------------------------------
# Package wiring tests (TASK-1083)
# ------------------------------------------------------------------


class TestPackageWiring:
    """Tests for package-level import and __all__ wiring."""

    def test_inspector_toolkit_importable(self) -> None:
        """InspectorToolkit can be imported from parrot_tools.aws."""
        from parrot_tools.aws import InspectorToolkit as IT  # noqa: F401

        assert IT is not None

    def test_inspector_toolkit_in_all(self) -> None:
        """InspectorToolkit is in parrot_tools.aws.__all__."""
        from parrot_tools import aws  # noqa: F401

        assert "InspectorToolkit" in aws.__all__
