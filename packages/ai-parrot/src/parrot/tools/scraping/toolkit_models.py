"""
Toolkit data models for WebScrapingToolkit.

Provides DriverConfig (browser configuration), PlanSummary (slim registry
projection), and PlanSaveResult (plan save operation result).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class DriverConfig(BaseModel):
    """Frozen browser configuration passed to the driver factory.

    Captures all browser parameters needed to create a driver instance.
    Use ``merge()`` to produce a new config with overrides applied.

    Args:
        driver_type: Browser driver backend to use.
        browser: Browser name to launch.
        headless: Run browser without a visible window.
        mobile: Enable mobile emulation.
        mobile_device: Specific mobile device to emulate.
        auto_install: Automatically install/update the browser driver.
        default_timeout: Default timeout in seconds for page operations.
        retry_attempts: Number of retry attempts for failed operations.
        delay_between_actions: Seconds to wait between plan steps.
        overlay_housekeeping: Dismiss overlays/popups between actions.
        disable_images: Block image loading for faster scraping.
        custom_user_agent: Override the default user agent string.
    """

    driver_type: Literal["selenium", "playwright"] = "selenium"
    browser: Literal[
        "chrome", "firefox", "edge", "safari", "undetected", "webkit"
    ] = "chrome"
    headless: bool = True
    mobile: bool = False
    mobile_device: Optional[str] = None
    auto_install: bool = True
    default_timeout: int = 10
    retry_attempts: int = 3
    delay_between_actions: float = 1.0
    overlay_housekeeping: bool = True
    disable_images: bool = False
    custom_user_agent: Optional[str] = None

    def merge(self, overrides: Optional[Dict[str, Any]] = None) -> DriverConfig:
        """Return a new DriverConfig with overrides applied.

        The original instance is never mutated.

        Args:
            overrides: Dictionary of field names to new values.
                If ``None`` or empty, returns a copy of the current config.

        Returns:
            A new ``DriverConfig`` with the overrides applied.
        """
        if not overrides:
            return self.model_copy()
        data = self.model_dump()
        data.update(overrides)
        return DriverConfig.model_validate(data)


class PlanSummary(BaseModel):
    """Slim projection of PlanRegistryEntry for plan listing results.

    Contains only the metadata needed for display and filtering,
    without the internal file path.

    Args:
        name: Plan name.
        version: Plan version string.
        url: Target URL the plan was created for.
        domain: Domain extracted from the URL.
        created_at: When the plan was first created.
        last_used_at: When the plan was last used for scraping.
        use_count: Number of times the plan has been used.
        tags: Categorization tags.
    """

    name: str
    version: str
    url: str
    domain: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    use_count: int = 0
    tags: List[str] = Field(default_factory=list)

    @classmethod
    def from_registry_entry(cls, entry: Any) -> PlanSummary:
        """Create a PlanSummary from a PlanRegistryEntry.

        Args:
            entry: A ``PlanRegistryEntry`` instance.

        Returns:
            A new ``PlanSummary`` with fields copied from the entry.
        """
        return cls(
            name=entry.name,
            version=entry.plan_version,
            url=entry.url,
            domain=entry.domain,
            created_at=entry.created_at,
            last_used_at=entry.last_used_at,
            use_count=entry.use_count,
            tags=entry.tags,
        )


class PlanSaveResult(BaseModel):
    """Result of a plan save operation.

    Args:
        success: Whether the save completed successfully.
        path: Relative path where the plan file was written.
        name: Plan name.
        version: Plan version that was saved.
        registered: Whether the plan was registered in the index.
        message: Human-readable status message.
    """

    success: bool
    path: str
    name: str
    version: str
    registered: bool
    message: str
