"""
Research Memory Schemas
========================

Pydantic data models for the Collective Research Memory system.

This module defines:
- ResearchDocument: A research document stored in collective memory
- ResearchScheduleConfig: Configuration for research crew scheduling
- AuditEvent: An event in the audit trail log
- DEFAULT_RESEARCH_SCHEDULES: Default schedule configurations for all 5 crews
- generate_period_key(): Helper to generate ISO period keys

These models form the foundation of the filesystem-based research storage
system that replaces the Redis-based ResearchBriefingStore.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from parrot.finance.schemas import ResearchBriefing


# =============================================================================
# RESEARCH DOCUMENT - Core storage unit
# =============================================================================


class ResearchDocument(BaseModel):
    """A research document stored in collective memory.

    This is the core storage unit for research produced by research crews.
    Documents are indexed by (crew_id, period_key) and stored as JSON files.

    Attributes:
        id: Unique document ID (UUID hex string)
        crew_id: Research crew identifier (e.g., "research_crew_macro")
        domain: Research domain (macro, equity, crypto, sentiment, risk)
        period_key: Period identifier in ISO format (e.g., "2026-03-03" or "2026-03-03T14:00:00")
        generated_at: UTC timestamp when the research was generated
        briefing: The actual research briefing content
        metadata: Additional metadata (sources, duration, etc.)
    """

    id: str = Field(description="Unique document ID (UUID hex string)")
    crew_id: str = Field(description="Research crew identifier (e.g., 'research_crew_macro')")
    domain: str = Field(description="Research domain: macro, equity, crypto, sentiment, risk")
    period_key: str = Field(
        description="Period identifier in ISO format: 'YYYY-MM-DD' for daily or 'YYYY-MM-DDTHH:MM:SS' for hourly"
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the research was generated",
    )
    briefing: ResearchBriefing = Field(description="The research briefing content")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (sources, duration_ms, etc.)",
    )

    @computed_field
    @property
    def is_daily(self) -> bool:
        """Check if this is a daily-granularity document.

        Returns True if period_key is in 'YYYY-MM-DD' format (no time component).
        """
        return "T" not in self.period_key

    @computed_field
    @property
    def age_seconds(self) -> float:
        """Age of the document in seconds since generation."""
        now = datetime.now(timezone.utc)
        if self.generated_at.tzinfo is None:
            generated = self.generated_at.replace(tzinfo=timezone.utc)
        else:
            generated = self.generated_at
        return (now - generated).total_seconds()

    def is_stale(self, staleness_hours: float) -> bool:
        """Check if the document is stale based on staleness window.

        Args:
            staleness_hours: Maximum age in hours before considered stale.

        Returns:
            True if document is older than staleness_hours.
        """
        max_age_seconds = staleness_hours * 3600
        return self.age_seconds > max_age_seconds


# =============================================================================
# SCHEDULE CONFIGURATION - Per-crew scheduling settings
# =============================================================================


PeriodGranularity = Literal["daily", "4h", "6h", "hourly"]


class ResearchScheduleConfig(BaseModel):
    """Configuration for research crew scheduling.

    Defines when a crew runs and how its period keys are generated.

    Attributes:
        crew_id: Research crew identifier
        cron_expression: Cron expression for scheduling (UTC times)
        period_granularity: How period keys are generated
        staleness_hours: Hours after which research is considered stale
    """

    crew_id: str = Field(description="Research crew identifier (e.g., 'research_crew_macro')")
    cron_expression: str = Field(
        description="Cron expression for scheduling (UTC times), e.g., '0 6,14 * * *'"
    )
    period_granularity: PeriodGranularity = Field(
        default="daily",
        description="Period granularity: 'daily', '4h', '6h', or 'hourly'",
    )
    staleness_hours: int = Field(
        default=24,
        ge=1,
        description="Hours after which research is considered stale",
    )

    @computed_field
    @property
    def domain(self) -> str:
        """Extract domain from crew_id."""
        return self.crew_id.replace("research_crew_", "")

    def get_staleness_timedelta(self) -> timedelta:
        """Get staleness window as timedelta."""
        return timedelta(hours=self.staleness_hours)


# =============================================================================
# AUDIT EVENT - Audit trail logging
# =============================================================================


AuditEventType = Literal["stored", "accessed", "expired", "cleaned"]


class AuditEvent(BaseModel):
    """An event in the audit trail log.

    All research memory operations are logged for auditing and debugging.
    Events are stored in append-only JSONL format.

    Attributes:
        event_type: Type of event (stored, accessed, expired, cleaned)
        timestamp: UTC timestamp of the event
        crew_id: Research crew identifier
        period_key: Period key of the affected document
        domain: Research domain
        actor: Who triggered the event (crew_id, analyst_id, or "system")
        details: Additional event details
    """

    event_type: AuditEventType = Field(
        description="Event type: 'stored', 'accessed', 'expired', 'cleaned'"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the event",
    )
    crew_id: str = Field(description="Research crew identifier")
    period_key: str = Field(description="Period key of the affected document")
    domain: str = Field(description="Research domain")
    actor: str | None = Field(
        default=None,
        description="Who triggered the event (crew_id, analyst_id, or 'system')",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional event details",
    )


# =============================================================================
# PERIOD KEY GENERATION
# =============================================================================


def generate_period_key(granularity: PeriodGranularity) -> str:
    """Generate period key based on granularity.

    Creates an ISO 8601 formatted period key appropriate for the given
    granularity. The key uniquely identifies the time period for deduplication.

    Args:
        granularity: One of "daily", "4h", "6h", "hourly"

    Returns:
        ISO format period key:
        - "daily": "2026-03-03"
        - "4h": "2026-03-03T12:00:00" (rounded down to nearest 4h boundary)
        - "6h": "2026-03-03T12:00:00" (rounded down to nearest 6h boundary)
        - "hourly": "2026-03-03T14:00:00" (rounded down to hour)

    Raises:
        ValueError: If granularity is not a valid option.

    Examples:
        >>> generate_period_key("daily")
        '2026-03-03'
        >>> generate_period_key("4h")  # at 14:30 UTC
        '2026-03-03T12:00:00'
    """
    now = datetime.now(timezone.utc)

    if granularity == "daily":
        return now.strftime("%Y-%m-%d")

    elif granularity == "4h":
        # Round down to nearest 4-hour boundary (0, 4, 8, 12, 16, 20)
        hour = (now.hour // 4) * 4
        rounded = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        # Return without timezone suffix for cleaner keys
        return rounded.strftime("%Y-%m-%dT%H:%M:%S")

    elif granularity == "6h":
        # Round down to nearest 6-hour boundary (0, 6, 12, 18)
        hour = (now.hour // 6) * 6
        rounded = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        return rounded.strftime("%Y-%m-%dT%H:%M:%S")

    elif granularity == "hourly":
        # Round down to hour
        rounded = now.replace(minute=0, second=0, microsecond=0)
        return rounded.strftime("%Y-%m-%dT%H:%M:%S")

    else:
        raise ValueError(
            f"Invalid granularity: {granularity}. "
            f"Must be one of: 'daily', '4h', '6h', 'hourly'"
        )


def parse_period_key_date(period_key: str) -> datetime:
    """Parse a period key back to a datetime.

    Args:
        period_key: Period key in ISO format.

    Returns:
        Datetime object (UTC timezone).

    Raises:
        ValueError: If period_key format is invalid.
    """
    try:
        if "T" in period_key:
            # Hourly format: 2026-03-03T14:00:00
            dt = datetime.fromisoformat(period_key)
        else:
            # Daily format: 2026-03-03
            dt = datetime.strptime(period_key, "%Y-%m-%d")

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid period_key format: {period_key}") from e


# =============================================================================
# DEFAULT SCHEDULES - Pre-configured schedules for all 5 research crews
# =============================================================================


DEFAULT_RESEARCH_SCHEDULES: dict[str, ResearchScheduleConfig] = {
    "research_crew_macro": ResearchScheduleConfig(
        crew_id="research_crew_macro",
        cron_expression="0 6,14 * * *",  # 2x/day at 6am, 2pm UTC
        period_granularity="daily",
        staleness_hours=24,
    ),
    "research_crew_equity": ResearchScheduleConfig(
        crew_id="research_crew_equity",
        cron_expression="0 7,13 * * 1-5",  # 2x/day weekdays at 7am, 1pm UTC
        period_granularity="daily",
        staleness_hours=12,
    ),
    "research_crew_crypto": ResearchScheduleConfig(
        crew_id="research_crew_crypto",
        cron_expression="0 */4 * * *",  # Every 4 hours, 24/7
        period_granularity="4h",
        staleness_hours=4,
    ),
    "research_crew_sentiment": ResearchScheduleConfig(
        crew_id="research_crew_sentiment",
        cron_expression="0 */6 * * *",  # Every 6 hours, 24/7
        period_granularity="6h",
        staleness_hours=6,
    ),
    "research_crew_risk": ResearchScheduleConfig(
        crew_id="research_crew_risk",
        cron_expression="0 8,14,20 * * *",  # 3x/day at 8am, 2pm, 8pm UTC
        period_granularity="daily",
        staleness_hours=8,
    ),
}


# Convenience constant for all crew IDs
ALL_CREW_IDS: list[str] = list(DEFAULT_RESEARCH_SCHEDULES.keys())

# Domain to crew mapping
DOMAIN_TO_CREW: dict[str, str] = {
    config.domain: crew_id
    for crew_id, config in DEFAULT_RESEARCH_SCHEDULES.items()
}

# All domains
ALL_DOMAINS: list[str] = list(DOMAIN_TO_CREW.keys())
