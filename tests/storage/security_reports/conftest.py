"""Fixtures for security_reports storage tests."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parrot.storage.security_reports import (
    ReportKind,
    ReportRef,
    SeverityBreakdown,
)


# ---------------------------------------------------------------------------
# Synthetic scanner fixture bytes
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_cloudsploit_json() -> bytes:
    """Minimal valid CloudSploit JSON with 2 critical, 3 high findings."""
    return b"""
{
  "summary": {
    "total": 5,
    "ok": 0,
    "warn": 0,
    "fail": 5,
    "unknown": 0
  },
  "findings": [
    {"plugin": "s3Encryption", "category": "S3", "title": "S3 Bucket Not Encrypted",
     "region": "us-east-1", "resource": "arn:aws:s3:::my-bucket",
     "status": "FAIL", "severity": "CRITICAL", "message": "Bucket lacks encryption"},
    {"plugin": "rootMfaEnabled", "category": "IAM", "title": "Root MFA Not Enabled",
     "region": "global", "resource": "arn:aws:iam::123:root",
     "status": "FAIL", "severity": "CRITICAL", "message": "Root MFA disabled"},
    {"plugin": "accessKeys", "category": "IAM", "title": "Access Key Age",
     "region": "global", "resource": "arn:aws:iam::123:user/svc1",
     "status": "FAIL", "severity": "HIGH", "message": "Key >90 days"},
    {"plugin": "accessKeys", "category": "IAM", "title": "Access Key Age",
     "region": "global", "resource": "arn:aws:iam::123:user/svc2",
     "status": "FAIL", "severity": "HIGH", "message": "Key >90 days"},
    {"plugin": "cloudtrailEnabled", "category": "CloudTrail",
     "title": "CloudTrail Not Enabled",
     "region": "us-east-1", "resource": "arn:aws:cloudtrail::trail1",
     "status": "FAIL", "severity": "HIGH", "message": "CloudTrail disabled"}
  ]
}
"""


@pytest.fixture
def synthetic_trivy_json() -> bytes:
    """Minimal valid Trivy filesystem-scan JSON with 1 critical, 1 high."""
    return b"""
{
  "SchemaVersion": 2,
  "ArtifactName": "/app",
  "ArtifactType": "filesystem",
  "Results": [
    {
      "Target": "/app/requirements.txt",
      "Class": "lang-pkgs",
      "Type": "pip",
      "Vulnerabilities": [
        {
          "VulnerabilityID": "CVE-2023-0001",
          "PkgName": "requests",
          "InstalledVersion": "2.26.0",
          "Severity": "CRITICAL",
          "Title": "Remote code execution in requests",
          "Description": "Critical vulnerability"
        },
        {
          "VulnerabilityID": "CVE-2023-0002",
          "PkgName": "pillow",
          "InstalledVersion": "9.0.0",
          "Severity": "HIGH",
          "Title": "Image processing vulnerability",
          "Description": "High severity issue"
        }
      ]
    }
  ]
}
"""


def _make_ref(
    produced_at: datetime | None = None,
    scope: dict | None = None,
    scanner: str = "cloudsploit",
    framework: str | None = "HIPAA",
    provider: str = "aws",
) -> ReportRef:
    """Helper to build a minimal valid ReportRef for testing."""
    return ReportRef(
        report_kind=ReportKind.SCAN,
        scanner=scanner,
        framework=framework,
        provider=provider,
        scope=scope or {"account_id": "123456789012", "region": "us-east-1"},
        severity_summary=SeverityBreakdown(critical=1, high=2),
        uri="",  # populated by save_report
        produced_at=produced_at or datetime.now(timezone.utc),
        produced_by="test",
        parser_version="1.0.0",
    )
