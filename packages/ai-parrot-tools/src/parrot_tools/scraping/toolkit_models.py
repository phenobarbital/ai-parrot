"""
Toolkit data models for WebScrapingToolkit.

Provides DriverConfig (browser configuration), PlanSummary (slim registry
projection), and PlanSaveResult (plan save operation result).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

#: Environment/navconfig key holding a default Google Chrome executable,
#: used when no explicit ``browser_binary`` is configured (e.g. a machine
#: that only has ``/opt/google/chrome-beta/google-chrome-beta``).
DEFAULT_CHROME_EXECUTABLE_PATH_KEY = "DEFAULT_CHROME_EXECUTABLE_PATH"

#: Browser names (``DriverConfig.browser``) that launch a Chrome binary.
_CHROME_BROWSERS = frozenset({"chrome", "chromium", "undetected"})


def resolve_browser_binary(
    browser_binary: Optional[str],
    browser: str = "chrome",
    channel: Optional[str] = None,
) -> Optional[str]:
    """Resolve the browser executable a driver should launch.

    An explicit ``browser_binary`` always wins and is returned untouched.
    Otherwise, for Chrome-family browsers, the ``DEFAULT_CHROME_EXECUTABLE_PATH``
    setting (environment or navconfig) is used when it points at an existing
    file. The default is skipped when a non-Chrome Playwright channel
    (e.g. ``"msedge"``) is requested, so it never hijacks another browser.

    Args:
        browser_binary: Explicitly configured executable path, if any.
        browser: ``DriverConfig.browser`` name (``"chrome"``, ``"firefox"``...).
        channel: Playwright channel, if any.

    Returns:
        The executable path to launch, or ``None`` to let the driver use
        its own default (bundled Chromium, channel lookup, or driver manager).
    """
    if browser_binary:
        return browser_binary
    if (browser or "chrome").lower() not in _CHROME_BROWSERS:
        return None
    if channel and not channel.lower().startswith("chrom"):
        return None
    from navconfig import config

    default = config.get(DEFAULT_CHROME_EXECUTABLE_PATH_KEY)
    if not default:
        return None
    if not Path(default).is_file():
        logger.warning(
            "%s=%s does not exist; falling back to the driver's default browser",
            DEFAULT_CHROME_EXECUTABLE_PATH_KEY,
            default,
        )
        return None
    return str(default)


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
        user_data_dir: Path to a browser user-data directory (e.g. a
            Google Chrome profile root) so the automated browser reuses
            its cookies, saved sessions and credential store.
        profile_directory: Profile folder inside ``user_data_dir``
            (Chrome: ``"Default"``, ``"Profile 1"``, ...).
        browser_channel: Playwright browser channel (e.g. ``"chrome"``,
            ``"msedge"``) to launch a real installed browser instead of
            the bundled engine. Ignored by the Selenium backend.
        browser_binary: Path to the browser executable to launch
            (Playwright ``executable_path`` / Selenium ``binary_location``).
            For Chrome-family browsers it falls back to the
            ``DEFAULT_CHROME_EXECUTABLE_PATH`` setting when unset.
        cdp_endpoint_url: Explicit Obscura CDP endpoint (FEAT-530).
            Only used when ``driver_type="obscura"``.
        obscura_binary: Path to (or ``PATH``-resolvable name of) the
            Obscura binary. Not used by the driver itself — carried
            through for CLI/process-manager use.
        obscura_port: CDP port of the supervised Obscura process, used
            to derive ``cdp_endpoint_url`` when it is not set explicitly.
        obscura_stealth: Obscura stealth-mode flag.
        obscura_allow_private_network: Obscura
            ``--allow-private-network`` flag.
    """

    driver_type: Literal["selenium", "playwright", "obscura"] = "selenium"
    browser: Literal["chrome", "firefox", "edge", "safari", "undetected", "webkit"] = "chrome"
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
    user_data_dir: Optional[str] = None
    profile_directory: Optional[str] = None
    browser_channel: Optional[str] = None
    browser_binary: Optional[str] = None
    cdp_endpoint_url: Optional[str] = None
    obscura_binary: Optional[str] = None
    obscura_port: int = 9222
    obscura_stealth: bool = False
    obscura_allow_private_network: bool = False

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
