"""
WebScrapingToolkit — AbstractToolkit-based entry point for scraping.

Each public async method is automatically exposed as an individual tool
for agents and chatbots via ``AbstractToolkit``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from parrot.tools.toolkit import AbstractToolkit

from .driver_context import DriverRegistry, driver_context, _quit_driver
from .executor import execute_plan_steps
from .models import ScrapingResult
from .plan import ScrapingPlan
from .plan_generator import PlanGenerator
from .plan_io import load_plan_from_disk, save_plan_to_disk
from .registry import PlanRegistry
from .toolkit_models import DriverConfig, PlanSaveResult, PlanSummary

logger = logging.getLogger(__name__)


class WebScrapingToolkit(AbstractToolkit):
    """Toolkit for intelligent web scraping and crawling with plan caching.

    Inherits from ``AbstractToolkit`` so that every public async method is
    auto-discovered as a tool.  Coordinates plan inference (LLM), single-page
    scraping, multi-page crawling, and plan persistence.

    Args:
        driver_type: Browser driver backend to use.
        browser: Browser to launch.
        headless: Run headless.
        session_based: Reuse driver across calls (sequential only).
        mobile: Enable mobile emulation.
        mobile_device: Specific mobile device name.
        auto_install: Auto-install/update browser driver.
        default_timeout: Default timeout in seconds.
        retry_attempts: Retries for failed operations.
        delay_between_actions: Seconds between plan steps.
        overlay_housekeeping: Dismiss overlays between actions.
        disable_images: Block image loading.
        custom_user_agent: Override user agent.
        plans_dir: Root directory for plan storage.
        llm_client: LLM client with ``async complete(prompt) -> str``.
        **kwargs: Passed through to ``AbstractToolkit``.
    """

    def __init__(
        self,
        driver_type: Literal["selenium", "playwright"] = "selenium",
        browser: Literal[
            "chrome", "firefox", "edge", "safari", "undetected", "webkit"
        ] = "chrome",
        headless: bool = True,
        session_based: bool = False,
        mobile: bool = False,
        mobile_device: Optional[str] = None,
        auto_install: bool = True,
        default_timeout: int = 10,
        retry_attempts: int = 3,
        delay_between_actions: float = 1.0,
        overlay_housekeeping: bool = True,
        disable_images: bool = False,
        custom_user_agent: Optional[str] = None,
        plans_dir: Optional[Union[str, Path]] = None,
        llm_client: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self._config = DriverConfig(
            driver_type=driver_type,
            browser=browser,
            headless=headless,
            mobile=mobile,
            mobile_device=mobile_device,
            auto_install=auto_install,
            default_timeout=default_timeout,
            retry_attempts=retry_attempts,
            delay_between_actions=delay_between_actions,
            overlay_housekeeping=overlay_housekeeping,
            disable_images=disable_images,
            custom_user_agent=custom_user_agent,
        )
        self._session_based = session_based
        self._session_driver: Optional[Any] = None
        self._registry: Optional[PlanRegistry] = None
        self._llm_client = llm_client
        self._plans_dir = Path(plans_dir) if plans_dir else Path("scraping_plans")
        self.logger = logging.getLogger(__name__)

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialise session driver when ``session_based=True``.

        In session mode a single browser instance is created and reused
        across all ``scrape()`` / ``crawl()`` calls until ``stop()`` is invoked.

        .. note:: Session mode is for **sequential** use only.
        """
        if self._session_based and self._session_driver is None:
            factory = DriverRegistry.get(self._config.driver_type)
            setup = factory(self._config)
            self._session_driver = await setup.get_driver()
            self.logger.info("Session driver started (%s)", self._config.driver_type)

    async def stop(self) -> None:
        """Shut down the session driver if active."""
        if self._session_driver is not None:
            await _quit_driver(self._session_driver)
            self._session_driver = None
            self.logger.info("Session driver stopped")

    # ── Internal helpers ──────────────────────────────────────────────

    async def _ensure_registry(self) -> PlanRegistry:
        """Lazy-load the ``PlanRegistry`` from disk."""
        if self._registry is None:
            self._registry = PlanRegistry(plans_dir=self._plans_dir)
            await self._registry.load()
        return self._registry

    def _get_llm_client(self) -> Any:
        """Resolve an LLM client or raise."""
        if self._llm_client is not None:
            return self._llm_client
        raise RuntimeError(
            "No LLM client available.  Pass llm_client= to the constructor "
            "or set the AIPARROT_DEFAULT_MODEL environment variable."
        )

    async def _resolve_plan(
        self,
        url: str,
        plan: Optional[Union[ScrapingPlan, Dict[str, Any]]] = None,
        objective: Optional[str] = None,
    ) -> ScrapingPlan:
        """Plan resolution chain: explicit -> cached -> auto-generate -> error.

        Args:
            url: Target URL.
            plan: Explicit plan (highest priority).
            objective: Scraping objective for auto-generation.

        Returns:
            A resolved ``ScrapingPlan``.

        Raises:
            ValueError: If no plan can be resolved.
        """
        # 1. Explicit plan argument
        if plan is not None:
            if isinstance(plan, dict):
                return ScrapingPlan.model_validate(plan)
            return plan

        # 2. Registry cache lookup
        registry = await self._ensure_registry()
        entry = registry.lookup(url)
        if entry is not None:
            plan_path = self._plans_dir / entry.path
            try:
                cached = await load_plan_from_disk(plan_path)
                await registry.touch(entry.fingerprint)
                self.logger.info("Plan cache hit for %s", url)
                return cached
            except (FileNotFoundError, OSError) as exc:
                self.logger.warning("Cached plan file missing: %s (%s)", plan_path, exc)

        # 3. Auto-generate via LLM if objective provided
        if objective:
            return await self.plan_create(url, objective)

        # 4. Error
        raise ValueError(
            f"No plan available for {url!r}. Provide an explicit plan, "
            "a cached plan must exist, or pass objective= to auto-generate."
        )

    # ── Tool methods (7 public async methods -> 7 tools) ──────────────

    async def plan_create(
        self,
        url: str,
        objective: str,
        hints: Optional[Dict[str, Any]] = None,
        force_regenerate: bool = False,
    ) -> ScrapingPlan:
        """Create a scraping plan for a URL via LLM or cache.

        Returns a cached plan if one exists for the URL (unless
        ``force_regenerate=True``), otherwise generates a new one via the
        configured LLM client.

        Args:
            url: Target URL.
            objective: What to extract.
            hints: Optional hints for the LLM (e.g. auth_required, pagination).
            force_regenerate: Bypass cache and always call the LLM.

        Returns:
            A ``ScrapingPlan`` ready for execution.
        """
        if not force_regenerate:
            registry = await self._ensure_registry()
            entry = registry.lookup(url)
            if entry is not None:
                plan_path = self._plans_dir / entry.path
                try:
                    cached = await load_plan_from_disk(plan_path)
                    await registry.touch(entry.fingerprint)
                    self.logger.info("plan_create: cache hit for %s", url)
                    return cached
                except (FileNotFoundError, OSError) as exc:
                    self.logger.warning("Cached plan file missing: %s", exc)

        client = self._get_llm_client()
        gen = PlanGenerator(client)
        plan = await gen.generate(url, objective, hints=hints)
        self.logger.info("plan_create: generated new plan for %s", url)
        return plan

    async def plan_save(
        self,
        plan: ScrapingPlan,
        overwrite: bool = False,
    ) -> PlanSaveResult:
        """Save a scraping plan to disk and register it.

        Args:
            plan: Plan to save.
            overwrite: Replace an existing file if it exists.

        Returns:
            ``PlanSaveResult`` with save status and file path.
        """
        registry = await self._ensure_registry()

        # Check for existing entry
        if not overwrite:
            existing = registry.lookup(plan.url)
            if existing is not None:
                return PlanSaveResult(
                    success=False,
                    path=existing.path,
                    name=existing.name,
                    version=existing.plan_version,
                    registered=True,
                    message="Plan already exists. Use overwrite=True to replace.",
                )

        try:
            saved_path = await save_plan_to_disk(plan, self._plans_dir)
            relative = str(saved_path.relative_to(self._plans_dir))
            await registry.register(plan, relative)
            return PlanSaveResult(
                success=True,
                path=relative,
                name=plan.name,
                version=plan.version,
                registered=True,
                message="Plan saved and registered successfully.",
            )
        except Exception as exc:
            self.logger.error("plan_save failed: %s", exc)
            return PlanSaveResult(
                success=False,
                path="",
                name=plan.name or "",
                version=plan.version,
                registered=False,
                message=f"Save failed: {exc}",
            )

    async def plan_load(self, url_or_name: str) -> Optional[ScrapingPlan]:
        """Load a plan by URL (registry lookup) or by name.

        Args:
            url_or_name: A URL to look up or a plan name.

        Returns:
            The loaded ``ScrapingPlan`` or ``None`` if not found.
        """
        registry = await self._ensure_registry()

        # Try URL lookup first
        entry = registry.lookup(url_or_name)
        if entry is None:
            # Try name lookup
            entry = registry.get_by_name(url_or_name)

        if entry is None:
            return None

        plan_path = self._plans_dir / entry.path
        try:
            plan = await load_plan_from_disk(plan_path)
            await registry.touch(entry.fingerprint)
            return plan
        except (FileNotFoundError, OSError) as exc:
            self.logger.warning("Plan file missing: %s (%s)", plan_path, exc)
            return None

    async def plan_list(
        self,
        domain_filter: Optional[str] = None,
        tag_filter: Optional[str] = None,
    ) -> List[PlanSummary]:
        """List registered plans with optional filtering.

        Args:
            domain_filter: Only include plans matching this domain.
            tag_filter: Only include plans containing this tag.

        Returns:
            List of ``PlanSummary`` objects.
        """
        registry = await self._ensure_registry()
        entries = registry.list_all()
        results: List[PlanSummary] = []

        for entry in entries:
            if domain_filter and entry.domain != domain_filter:
                continue
            if tag_filter and tag_filter not in entry.tags:
                continue
            results.append(PlanSummary.from_registry_entry(entry))

        return results

    async def plan_delete(
        self,
        name: str,
        delete_file: bool = True,
    ) -> bool:
        """Delete a plan from the registry and optionally from disk.

        Args:
            name: Plan name to delete.
            delete_file: Also remove the plan file from disk.

        Returns:
            ``True`` if the plan was found and removed.
        """
        registry = await self._ensure_registry()

        # Find the entry before removing
        entry = registry.get_by_name(name)
        if entry is None:
            return False

        # Remove file if requested
        if delete_file:
            plan_path = self._plans_dir / entry.path
            try:
                plan_path.unlink(missing_ok=True)
                self.logger.info("Deleted plan file: %s", plan_path)
            except OSError as exc:
                self.logger.warning("Could not delete file %s: %s", plan_path, exc)

        # Remove from registry
        return await registry.remove(name)

    async def scrape(
        self,
        url: str,
        plan: Optional[Union[ScrapingPlan, Dict[str, Any]]] = None,
        objective: Optional[str] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        selectors: Optional[List[Dict[str, Any]]] = None,
        save_plan: bool = False,
        browser_config_override: Optional[Dict[str, Any]] = None,
    ) -> ScrapingResult:
        """Scrape a single page using a plan, raw steps, or auto-generation.

        Plan resolution priority (when ``steps`` is not provided):
        1. Explicit ``plan`` argument
        2. Registry cache lookup by ``url``
        3. Auto-generate via LLM if ``objective`` is provided
        4. Raise ``ValueError``

        When ``steps`` is provided, they are executed directly without
        plan resolution.

        Args:
            url: Target URL.
            plan: Explicit ScrapingPlan or dict.
            objective: Scraping objective (for auto-generation).
            steps: Raw steps list for ad-hoc execution (bypasses plan resolution).
            selectors: Content extraction selectors (used with raw steps).
            save_plan: Save the resolved/generated plan after scraping.
            browser_config_override: Per-call driver config overrides.

        Returns:
            ``ScrapingResult`` with extracted data and metadata.
        """
        config = self._config.merge(browser_config_override)

        # Raw steps mode — bypass plan resolution
        if steps is not None:
            async with driver_context(config, session_driver=self._session_driver) as drv:
                return await execute_plan_steps(
                    drv,
                    steps=steps,
                    selectors=selectors,
                    config=config,
                    base_url=url,
                )

        # Plan resolution
        resolved = await self._resolve_plan(url, plan, objective)

        async with driver_context(config, session_driver=self._session_driver) as drv:
            result = await execute_plan_steps(
                drv,
                plan=resolved,
                config=config,
                base_url=url,
            )

        # Auto-save if requested
        if save_plan and result.success:
            try:
                await self.plan_save(resolved)
            except Exception as exc:
                self.logger.warning("Auto-save plan failed: %s", exc)

        return result

    async def crawl(
        self,
        start_url: str,
        depth: int = 1,
        max_pages: Optional[int] = None,
        follow_selector: Optional[str] = None,
        follow_pattern: Optional[str] = None,
        plan: Optional[Union[ScrapingPlan, Dict[str, Any]]] = None,
        objective: Optional[str] = None,
        save_plan: bool = False,
        concurrency: int = 1,
    ) -> Any:
        """Crawl multiple pages starting from a URL.

        Delegates to ``CrawlEngine`` (FEAT-013).  If the engine is not
        available, raises ``NotImplementedError``.

        Args:
            start_url: Entry point URL.
            depth: Maximum crawl depth.
            max_pages: Maximum number of pages to visit.
            follow_selector: CSS selector for links to follow.
            follow_pattern: URL regex pattern for links to follow.
            plan: Explicit scraping plan for each page.
            objective: Scraping objective for auto-generation.
            save_plan: Persist the plan after first scrape.
            concurrency: Number of concurrent page fetches.

        Returns:
            CrawlResult from the engine.

        Raises:
            NotImplementedError: If CrawlEngine is not available.
        """
        try:
            from .crawl_engine import CrawlEngine
        except ImportError:
            raise NotImplementedError(
                "CrawlEngine is not available. Install FEAT-013 to enable crawling."
            )

        # Resolve the per-page plan
        resolved = await self._resolve_plan(start_url, plan, objective)

        engine = CrawlEngine(
            start_url=start_url,
            plan=resolved,
            depth=depth,
            max_pages=max_pages,
            follow_selector=follow_selector,
            follow_pattern=follow_pattern,
            concurrency=concurrency,
            driver_config=self._config,
        )

        result = await engine.run()

        if save_plan and resolved:
            try:
                await self.plan_save(resolved)
            except Exception as exc:
                self.logger.warning("Auto-save plan failed: %s", exc)

        return result
