"""Pydantic v2 data models for the cross-session security report catalog.

All models are pure-data (no I/O). Every consumer of the catalog — producers,
persistence layer, and the LLM-facing toolkit — imports from this module.

Key design choices:
- ``produced_at`` is tz-aware UTC. Callers are responsible for passing
  ``datetime.now(timezone.utc)``; the model does not validate timezone
  awareness at instantiation (avoids overhead on every DB load).
- ``top_findings`` is capped at 10 entries in usage; no model-level
  validator enforces this to keep the Pydantic overhead minimal.
- ``ReportFilter.since`` has no default — the store applies NO implicit
  age filter (spec §5 hard requirement).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ReportKind(str, Enum):
    """Fractal kind hierarchy: raw scans and aggregated summaries share the same shape."""

    SCAN = "scan"
    WEEKLY_SUMMARY = "weekly_summary"
    MONTHLY_SUMMARY = "monthly_summary"
    DRIFT_COMPARISON = "drift_comparison"


class SeverityBreakdown(BaseModel):
    """Count container for findings by severity level.

    Note: do NOT confuse with ``parrot_tools.security.models.SeverityLevel``
    which is a level enum. This is a count container (see spec §7 R6).
    """

    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    informational: int = 0

    @property
    def total(self) -> int:
        """Sum of all severity counts."""
        return self.critical + self.high + self.medium + self.low + self.informational


class EmbeddedFinding(BaseModel):
    """A single security finding embedded in a ReportRef.

    Top-10 (by severity) per report — not a full finding record.
    For full finding detail, fetch the report content.
    """

    finding_id: str
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL"]
    title: str
    resource_id: str | None = None
    rule_id: str | None = None
    remediation_hint: str | None = None


class ReportRef(BaseModel):
    """Canonical metadata record for any security report.

    Fractal: used for raw scans (report_kind=SCAN) and for aggregated
    summaries (WEEKLY_SUMMARY, MONTHLY_SUMMARY, DRIFT_COMPARISON).

    The ``uri`` field points to the content in S3 (``s3://bucket/key``) or
    on the local filesystem (``file://path``). Content is NOT stored here.

    ``produced_at`` MUST be tz-aware UTC. Callers pass
    ``datetime.now(timezone.utc)`` — the model does not validate this.
    """

    report_id: UUID = Field(default_factory=uuid4)
    report_kind: ReportKind
    scanner: str
    """Scanner name: 'cloudsploit' | 'prowler' | 'trivy' | 'checkov' | 'aggregator'"""
    framework: str | None = None
    """Compliance framework: 'HIPAA' | 'PCI' | 'SOC2' | 'GDPR' | None for raw container scans"""
    provider: str
    """Cloud provider: 'aws' | 'azure' | 'gcp' | 'oci' | 'n/a'"""
    scope: dict
    """Scan scope context: {region, account_id, target_image, iac_path, source_report_ids?}"""
    severity_summary: SeverityBreakdown
    top_findings: list[EmbeddedFinding] = Field(default_factory=list)
    """Max 10, sorted by severity desc. Not the full finding list."""
    uri: str
    """'s3://bucket/key' or 'file://path' — set by the store after upload."""
    content_type: str = "application/json"
    content_bytes: int | None = None
    produced_at: datetime
    """Must be tz-aware UTC. Not validated at model level for performance."""
    produced_by: str
    """'schedule:run_hipaa_pci_compliance' | 'agent:<session_id>' | 'toolkit:ClassName'"""
    parser_version: str
    """Parser schema version for future migrations, e.g. '1.0.0'."""
    retention_class: Literal["standard", "compliance", "ephemeral"] = "compliance"


class ReportFilter(BaseModel):
    """Query filter for the security report store.

    IMPORTANT: No implicit age filtering at this layer — the store returns
    ALL reports that match the filter, including very old ones. The caller
    is responsible for setting ``since`` when a time window is desired
    (spec §5 hard requirement, test: test_store_query_no_implicit_since).
    """

    scanner: str | None = None
    framework: str | None = None
    provider: str | None = None
    report_kind: ReportKind | None = None
    since: datetime | None = None
    """Lower bound on produced_at (inclusive). None = no lower bound."""
    until: datetime | None = None
    """Upper bound on produced_at (inclusive). None = no upper bound."""
    scope_match: dict | None = None
    """Partial dict match via JSONB containment (account_id, region, etc.)."""
    limit: int = 50
    order_by: Literal["produced_at_desc", "produced_at_asc"] = "produced_at_desc"
