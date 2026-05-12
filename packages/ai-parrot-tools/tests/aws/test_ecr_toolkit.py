"""Unit tests for ECRToolkit — include_attributes extension (TASK-1119)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_tools.aws.ecr import ECRToolkit


SAMPLE_ECR_RESPONSE = {
    "imageScanStatus": {"status": "COMPLETE"},
    "imageScanFindings": {
        "findingSeverityCounts": {"CRITICAL": 1, "HIGH": 2},
        "findings": [
            {
                "name": "CVE-2024-0001",
                "severity": "CRITICAL",
                "description": "boom",
                "uri": "https://example/cve",
                "attributes": [
                    {"key": "package_name", "value": "openssl"},
                    {"key": "package_version", "value": "1.1.1"},
                    {"key": "CVSS3_SCORE", "value": "9.8"},
                ],
            },
        ],
    },
}


@pytest.fixture
def toolkit():
    """ECRToolkit with mocked AWSInterface."""
    tk = ECRToolkit.__new__(ECRToolkit)
    tk.aws = MagicMock()

    class _CtxClient:
        async def __aenter__(self_):
            return self_

        async def __aexit__(self_, *a):
            return False

        describe_image_scan_findings = AsyncMock(
            return_value=SAMPLE_ECR_RESPONSE
        )

    tk.aws.client = MagicMock(return_value=_CtxClient())
    return tk


@pytest.mark.asyncio
async def test_default_payload_excludes_attributes(toolkit):
    """Default call (include_attributes=False) must not add 'attributes' key."""
    result = await toolkit.aws_ecr_get_image_scan_findings("r", "t")
    f = result["findings"][0]
    assert set(f.keys()) == {"name", "severity", "description", "uri"}


@pytest.mark.asyncio
async def test_include_attributes_surfaces_raw_list(toolkit):
    """include_attributes=True surfaces the raw ECR attributes list."""
    result = await toolkit.aws_ecr_get_image_scan_findings(
        "r", "t", include_attributes=True,
    )
    f = result["findings"][0]
    assert "attributes" in f
    assert isinstance(f["attributes"], list)
    keys = {a["key"] for a in f["attributes"]}
    assert "package_name" in keys
    assert "CVSS3_SCORE" in keys


@pytest.mark.asyncio
async def test_include_attributes_coerces_none_to_empty(toolkit, monkeypatch):
    """When ECR returns None for attributes, the result is an empty list."""
    # Monkeypatch the fixture response in-place
    SAMPLE_ECR_RESPONSE["imageScanFindings"]["findings"][0]["attributes"] = None
    try:
        result = await toolkit.aws_ecr_get_image_scan_findings(
            "r", "t", include_attributes=True,
        )
        assert result["findings"][0]["attributes"] == []
    finally:
        # Restore to avoid test pollution
        SAMPLE_ECR_RESPONSE["imageScanFindings"]["findings"][0]["attributes"] = [
            {"key": "package_name", "value": "openssl"},
            {"key": "package_version", "value": "1.1.1"},
            {"key": "CVSS3_SCORE", "value": "9.8"},
        ]


@pytest.mark.asyncio
async def test_scan_not_found_returns_expected_shape(toolkit, monkeypatch):
    """ScanNotFoundException still returns scan_status=NOT_FOUND (regression)."""
    from botocore.exceptions import ClientError

    not_found_response = {
        "Error": {"Code": "ScanNotFoundException", "Message": "No scan"},
        "ResponseMetadata": {},
    }

    class _CtxClientNotFound:
        async def __aenter__(self_):
            return self_

        async def __aexit__(self_, *a):
            return False

        async def describe_image_scan_findings(self_, **kwargs):
            raise ClientError(not_found_response, "describe_image_scan_findings")

    toolkit.aws.client = MagicMock(return_value=_CtxClientNotFound())
    result = await toolkit.aws_ecr_get_image_scan_findings("r", "t")
    assert result["scan_status"] == "NOT_FOUND"
    assert "message" in result
